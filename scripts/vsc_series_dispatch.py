#!/usr/bin/env python3
"""Approved series jobs: budget, durable intent, provider, recovery and local media.

Adapters are injected for offline tests. A real submit is possible only through
an approved series_batch run and the shared native-unit budget ledger.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import vsc_budget as budget
import vsc_series_db as db
import vsc_series_jobs as jobs
from vsc_provider import JobHandle
from vsc_series import SeriesError, _artifact_document, build_shot_context, import_media, series_state, sha256
from vsc_state import gate_problems


def _load(project, job_id, current=True):
    state = series_state(project)
    with db.connect(project) as connection:
        row = connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise SeriesError("系列任务不存在")
    job = dict(row)
    frozen = json.loads(job["request"])
    if db.digest(frozen) != job["request_sha256"]:
        raise SeriesError("任务固定请求摘要不符")
    if current:
        run_item, run = _artifact_document(project, state, job["run_artifact_id"])
    else:
        run_item = next((item for item in state["artifacts"] if item["id"] == job["run_artifact_id"]), None)
        if not run_item:
            raise SeriesError("历史 run 版本不存在")
        run = json.loads(db.artifact_document(project, job["run_artifact_id"]))
    if run_item["type"] != "vsc.production_run" or not run.get("series_batch"):
        raise SeriesError("任务缺已批准的系列 production_run")
    matched = [item for item in run["series_batch"]["jobs"]
               if item.get("candidate_no") == job["candidate_no"] and item.get("request") == frozen["logical_request"]]
    if len(matched) != 1 or frozen.get("operation") not in run["operations"]:
        raise SeriesError("任务已与批准的 run 请求或操作脱钩")
    if current:
        context = build_shot_context(project, job["target_id"])
        if context["sha256"] != job["context_sha256"]:
            raise SeriesError("镜头上下文已改变；不得提交旧任务")
    return state, job, frozen, run


def _request(frozen, modality):
    fields = {key: value for key, value in frozen["logical_request"].items()
              if key not in ("format", "modality")}
    return jobs.REQUEST_TYPES[modality](**fields)


def _reservation(project, job_id):
    with db.connect(project) as connection:
        row = connection.execute("SELECT payload FROM job_events WHERE job_id=? AND status='submission_unknown' "
            "ORDER BY created_at,id LIMIT 1", (job_id,)).fetchone()
    return json.loads(row["payload"]).get("reservation_id") if row else None


def _settle_unknown(project, job_id, evidence):
    reservation = _reservation(project, job_id)
    if reservation:
        budget.settle(project, reservation, evidence=evidence)


def _stable_original(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SeriesError("生成结果缺 HTTPS 下载地址")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def finalize_job(project, job_id, adapter=None, download=None):
    """Transfer succeeded outputs into content-addressed local storage, resumably."""
    _, job, _, _ = _load(project, job_id, current=False)
    if job["status"] != "succeeded":
        raise SeriesError("只能转存已成功的生成任务")
    details = json.loads(job["raw_response"] or "{}")
    raw = details.get("raw")
    if not isinstance(raw, dict):
        raise SeriesError("成功任务缺原始结果，无法恢复转存")
    adapter = adapter or jobs.adapter_for_job(project, job_id)
    outputs = adapter.parse_result(raw)
    if not outputs:
        raise SeriesError("成功任务没有可转存的素材")
    if download is None:
        import volc_ark
        download = volc_ark.download
    stored = []
    root = Path(project).resolve()
    with tempfile.TemporaryDirectory(prefix="vsc-result-", dir=project) as work:
        for index, output in enumerate(outputs, 1):
            if output.modality != job["modality"] and not (job["modality"] == "video" and output.modality == "image"):
                raise SeriesError("Provider 结果模态与固定任务不符")
            media_id = f"{job_id}-output-{index}"
            with db.connect(project) as connection:
                prior = connection.execute("SELECT m.path,m.sha256,m.modality FROM generated_assets g "
                    "JOIN media_assets m ON m.id=g.media_id WHERE g.job_id=? AND g.media_id=?",
                    (job_id, media_id)).fetchone()
            if prior:
                path = (root / prior["path"]).resolve()
                if (prior["modality"] != output.modality or not path.is_relative_to(root)
                        or not path.is_file() or sha256(path) != prior["sha256"]):
                    raise SeriesError("已转存生成素材失效：" + media_id)
                stored.append({"media_id": media_id, "sha256": prior["sha256"], "path": prior["path"]})
                continue
            suffix = ".mp4" if output.modality == "video" else ".wav" if output.modality == "audio" else ".png"
            source = Path(work) / f"output-{index}{suffix}"
            if output.inline_bytes is not None:
                source.write_bytes(output.inline_bytes)
            elif output.temporary_uri:
                download(output.temporary_uri, source)
            else:
                raise SeriesError("结果既无下载地址也无内联字节")
            stable = _stable_original(output.temporary_uri) if output.temporary_uri else None
            stored.append(import_media(project, media_id, source, output.modality, "unknown",
                f"generated:{job_id}", job_id=job_id, original_uri=stable))
    _settle_unknown(project, job_id, "已转存并校验生成任务 " + job_id)
    return stored


def _handle_status(project, job_id, status, adapter, download):
    job_status = status.status
    if job_status == "succeeded":
        jobs.record_status(project, job_id, "succeeded", details={"raw": status.raw})
        return {"status": "succeeded", "assets": finalize_job(project, job_id, adapter, download)}
    if job_status == "failed":
        jobs.record_status(project, job_id, "failed", details={"raw": status.raw, "error_code": status.error_code})
        _settle_unknown(project, job_id, "Provider 报告任务失败；实际计费用量待核对")
        return {"status": "failed", "error_code": status.error_code}
    jobs.record_status(project, job_id, job_status, details={"raw": status.raw})
    return {"status": job_status}


def submit_job(project, job_id, adapter=None, download=None):
    state, job, frozen, run = _load(project, job_id)
    if job["status"] != "created":
        raise SeriesError("任务已有提交意图或结果；只能恢复／对账，不得重提")
    if job["modality"] == "audio" and adapter is None:
        raise SeriesError("音频服务适配器尚未配置")
    gaps = gate_problems(Path(project), state, "animatic", run["scope"])
    if gaps:
        raise SeriesError("正式制作质量门未通过：" + "；".join(gaps))
    adapter = adapter or jobs.adapter_for_job(project, job_id)
    operation = frozen["operation"]
    bound = run["operations"][operation]
    reservation = budget.reserve(project, job["run_artifact_id"], operation, bound)
    # The ledger turns unknown before any POST. A crash after this line can only
    # leave a conservative unknown charge; it cannot create a second POST.
    budget.check_authorization(project, reservation, operation, bound, request=frozen["logical_request"])
    jobs.record_status(project, job_id, "submission_unknown", details={"reservation_id": reservation})
    try:
        handle = adapter.submit(_request(frozen, job["modality"]))
    except BaseException:
        _settle_unknown(project, job_id, "提交响应未知；不得自动重提，先核对平台任务和账单")
        raise
    if not isinstance(handle, JobHandle) or handle.provider != job["provider"] or handle.model != job["model"]:
        raise SeriesError("Provider 返回的任务句柄与固定任务不符；提交结果待人工对账")
    if handle.external_task_id:
        jobs.record_status(project, job_id, "submitted", handle.external_task_id,
                           {"raw": handle.raw})
        return {"status": "submitted", "external_task_id": handle.external_task_id}
    return _handle_status(project, job_id, adapter.poll(handle), adapter, download)


def resume_job(project, job_id, adapter=None, download=None):
    _, job, _, _ = _load(project, job_id, current=False)
    if job["status"] == "succeeded":
        return {"status": "succeeded", "assets": finalize_job(project, job_id, adapter, download)}
    if job["status"] not in ("submitted", "running") or not job["external_task_id"]:
        raise SeriesError("此任务没有可安全续查的外部编号；未知提交须人工对账")
    adapter = adapter or jobs.adapter_for_job(project, job_id)
    handle = JobHandle(job["provider"], job["model"], job["external_task_id"])
    return _handle_status(project, job_id, adapter.poll(handle), adapter, download)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("submit", "resume"))
    parser.add_argument("project"); parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    try:
        result = submit_job(args.project, args.job) if args.command == "submit" else resume_job(args.project, args.job)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SeriesError, db.SeriesStoreError, budget.BudgetError, sqlite3.Error, OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
