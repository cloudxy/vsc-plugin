#!/usr/bin/env python3
"""Compile transferred series jobs into existing VSC generation-record drafts.

This is a read-only projection of the relational job/media facts. The caller
registers the draft artifact and makes any take selection through VSC's
existing approval workflow; this command never approves a candidate.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from vsc.story import consistency as consistency
from vsc.adapters.persistence.sqlite import series as db
from vsc.production import jobs as jobs
from vsc.production.series import SeriesError, sha256
from vsc.production.dispatch import _load
from vsc.project.state import write_json


ROLE_PURPOSE = {
    "identity_face": "identity", "costume": "appearance", "location_master": "composition",
    "location_view": "composition", "composition": "composition", "first_frame": "composition",
    "last_frame": "composition", "voice_sample": "voice", "ambience": "sound",
    "music": "sound", "sfx": "sound",
}


def _pinned_document(project, frozen, kind):
    ref = next((item for item in frozen["input_versions"] if item["type"] == kind), None)
    if not ref:
        raise SeriesError("任务固定输入缺 " + kind)
    content = db.artifact_document(project, ref["id"])
    if hashlib.sha256(content).hexdigest() != ref["sha256"]:
        raise SeriesError("任务固定输入版本不符：" + ref["id"])
    return json.loads(content)


def _frame(connection, entry, shot_id):
    """Frame provenance from the media store: own keyframe, prior shot's last frame, or reference."""
    origin = connection.execute("SELECT j.target_id,j.modality FROM generated_assets g "
        "JOIN generation_jobs j ON j.id=g.job_id WHERE g.media_id=?", (entry["media_id"],)).fetchone()
    frame = {"path": entry["path"], "sha256": entry["sha256"], "from": "reference"}
    if origin and origin["target_id"] == shot_id:
        frame["from"] = "generated"
    elif origin and origin["modality"] == "video":
        frame.update({"from": "previous_exit", "shot": origin["target_id"]})
    elif origin:
        frame["shot"] = origin["target_id"]
    return frame


def generation_record(project, job_id, adapter=None):
    state, job, frozen, run = _load(project, job_id, current=False)
    if job["status"] != "succeeded":
        raise SeriesError("只有成功并完成转存的任务可以导出生成记录")
    details = json.loads(job["raw_response"] or "{}")
    raw = details.get("raw")
    if not isinstance(raw, dict):
        raise SeriesError("任务缺可核对的成功响应")
    adapter = adapter or jobs.adapter_for_job(project, job_id)
    expected = adapter.parse_result(raw)
    if not expected:
        raise SeriesError("成功响应没有素材")
    root = Path(project).resolve()
    shot_id = job["target_id"]
    logical = frozen["logical_request"]
    available = {entry["media_id"]: entry for entry in frozen["reference_media"]}
    assets = {item["id"] for item in state["objects"] if item["kind"] == "asset"}
    inputs = {"prompt": logical["prompt"], "context_sha256": frozen["context_sha256"], "references": []}
    voice_binding = frozen.get("voice_binding") if job["modality"] == "audio" else None
    if voice_binding:
        inputs.update({"line_id": voice_binding["line_id"], "entity": voice_binding["entity_id"],
                       "text": logical["prompt"],
                       "pronunciations": voice_binding["voice"].get("pronunciations", [])})
    with db.connect(project) as connection:
        rows = connection.execute("SELECT g.media_id,m.modality,m.path,m.sha256,m.metadata FROM generated_assets g "
            "JOIN media_assets m ON m.id=g.media_id WHERE g.job_id=?", (job_id,)).fetchall()
        events = connection.execute("SELECT status,created_at FROM job_events WHERE job_id=? "
            "AND status IN ('submission_unknown','succeeded') ORDER BY created_at,id", (job_id,)).fetchall()
        for key in ("first_frame", "last_frame"):
            media_id = logical.get(key + "_media_id")
            if media_id:
                if media_id not in available:
                    raise SeriesError(f"{key} 不在任务固定参考中")
                inputs[key] = _frame(connection, available[media_id], shot_id)
    by_id = {row["media_id"]: row for row in rows}
    if len(by_id) != len(expected):
        raise SeriesError("任务结果尚未全部转存，不能导出记录")
    outputs = []
    for index, generated in enumerate(expected, 1):
        media_id = f"{job_id}-output-{index}"
        row = by_id.get(media_id)
        if not row or row["modality"] != generated.modality:
            raise SeriesError("任务输出顺序或模态与转存资产不符")
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != row["sha256"]:
            raise SeriesError("已转存媒体字节失效：" + media_id)
        output = {"id": media_id, "path": row["path"], "sha256": row["sha256"]}
        if voice_binding:
            output.update({"line_id": voice_binding["line_id"], "entity": voice_binding["entity_id"],
                           "voice": voice_binding["voice"]["voice"],
                           "speaker": voice_binding["voice"]["voice"],
                           "resource_id": voice_binding["voice"].get("resource_id", "seed-tts-2.0")})
        if job["modality"] == "video" and generated.modality == "image":
            output["role"] = "last_frame"
        probe = json.loads(row["metadata"]).get("probe", {})
        seconds = probe.get("duration_seconds")
        if generated.modality in ("video", "audio") and isinstance(seconds, (int, float)) and seconds > 0:
            output["duration_ms"] = round(seconds * 1000)
        outputs.append(output)
    submitted = next((entry["created_at"] for entry in events if entry["status"] == "submission_unknown"), None)
    finished = next((entry["created_at"] for entry in reversed(events) if entry["status"] == "succeeded"), None)
    if not submitted or not finished:
        raise SeriesError("任务缺提交或成功事件")
    for media_id in [*logical.get("reference_media_ids", []), *([logical["voice_media_id"]] if logical.get("voice_media_id") else [])]:
        entry = available.get(media_id)
        if not entry:
            raise SeriesError("参考媒体不在任务固定参考中：" + media_id)
        reference = {"path": entry["path"], "sha256": entry["sha256"], "media_type": entry["modality"],
                     "purpose": ROLE_PURPOSE.get(entry["role"], "composition"), "role": "reference_" + entry["modality"]}
        if entry["target_id"] in assets:
            reference["entity_id"] = entry["target_id"]
        inputs["references"].append(reference)
    # Anchors are recomputed from the pinned versions, so they equal the plan-time ShotContext.
    bible = _pinned_document(project, frozen, "vsc.asset_bible")
    scene_state = _pinned_document(project, frozen, "vsc.scene_state")
    if job["modality"] in ("image", "video"):
        inputs["anchors_sha256"] = consistency.pack_sha256(consistency.anchor_pack(bible, scene_state, shot_id))
    if job["modality"] == "audio" or frozen["default_params"].get("generate_audio") or any(
            item["media_type"] == "audio" for item in inputs["references"]):
        inputs["audio_anchors_sha256"] = consistency.pack_sha256(consistency.audio_pack(bible, scene_state, shot_id))
    record = {"format": "vsc.generation-record/v1", "project_id": state["project_id"],
        "kind": job["modality"], "purpose": "asset" if logical["purpose"].startswith("asset_") else "candidate",
        "shot_id": shot_id, "inputs": inputs,
        "engine": {"provider": voice_binding["voice"]["engine"] if voice_binding else job["provider"],
                   "series_provider": job["provider"], "model": job["model"], "version": job["model_version"],
                   "params": {**logical.get("params", {}), **({"resource_id": voice_binding["voice"].get("resource_id", "seed-tts-2.0")}
                       if voice_binding else {})}, "defaults": frozen["default_params"]},
        "budget": {"billable": True, "usage": run["operations"][frozen["operation"]],
                   "usage_basis": "approved_bound", "currency_status": "unknown"},
        "submitted_at": submitted, "finished_at": finished, "status": "succeeded",
        "outputs": outputs, "errors": [], "selection": None,
        "series_job_id": job_id, "request_sha256": job["request_sha256"], "run_artifact_id": job["run_artifact_id"]}
    problems = consistency.record_errors(record)
    if problems:
        raise SeriesError("生成记录不符合现有契约：" + "；".join(problems))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project"); parser.add_argument("--job", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        record = generation_record(args.project, args.job)
        if args.out:
            path = Path(args.out)
            if path.exists():
                raise SeriesError("导出目标已存在，拒绝覆盖")
            write_json(path, record)
        else:
            print(json.dumps(record, ensure_ascii=False, indent=2))
    except (SeriesError, db.SeriesStoreError, sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
