#!/usr/bin/env python3
"""Bounded, read-only relational queries for series production and AI context.

Results contain stable IDs, fixed versions and local media references. Provider
task IDs, temporary URLs and raw responses stay out of this business interface.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from vsc.story import consistency as consistency
from vsc.adapters.persistence.sqlite import series as db
from vsc.production.context import SeriesError, _select, build_shot_context, series_state, sha256


def _object(state, identifier, kind):
    item = next((row for row in state["objects"] if row["id"] == identifier), None)
    if not item or item["kind"] != kind:
        raise SeriesError(f"对象不是已登记的 {kind}：{identifier}")
    return item


def _media(project, row):
    root = Path(project).resolve()
    path = (root / row["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha256(path) != row["sha256"]:
        raise SeriesError("媒体文件或摘要失效：" + row["id"])
    return {key: row[key] for key in ("id", "path", "sha256", "modality", "rights")}


def asset(project, asset_id):
    state = series_state(project)
    _object(state, asset_id, "asset")
    with db.connect(project) as connection:
        bindings = connection.execute("SELECT b.id AS binding_id,b.role,b.variant,b.status,m.* "
            "FROM media_bindings b JOIN media_assets m ON m.id=b.media_id "
            "WHERE b.target_id=? AND b.status='approved' ORDER BY b.role,b.variant,b.id", (asset_id,)).fetchall()
        media_ids = [row["id"] for row in bindings]
        parents = {}
        for media_id in media_ids:
            parents[media_id] = [dict(row) for row in connection.execute(
                "SELECT parent_id,relation,parameters FROM asset_derivations WHERE child_id=? ORDER BY parent_id",
                (media_id,)).fetchall()]
    if any(row["rights"] not in ("owned", "licensed") for row in bindings):
        raise SeriesError("已批准资产绑定的媒体权属不可用")
    return {"format": "vsc.series-asset-query/v1", "asset_id": asset_id,
        "bindings": [{"binding_id": row["binding_id"], "role": row["role"],
                      "variant": row["variant"], "status": row["status"],
                      "media": _media(project, row), "parents": parents[row["id"]]}
                     for row in bindings]}


def shot_jobs(project, shot_id):
    state = series_state(project)
    _object(state, shot_id, "shot")
    with db.connect(project) as connection:
        rows = connection.execute("SELECT id,purpose,modality,candidate_no,provider,model,model_version,status,"
            "created_at FROM generation_jobs WHERE target_id=? ORDER BY created_at,id", (shot_id,)).fetchall()
        jobs = []
        for row in rows:
            outputs = connection.execute("SELECT m.* FROM generated_assets g "
                "JOIN media_assets m ON m.id=g.media_id WHERE g.job_id=? ORDER BY m.id", (row["id"],)).fetchall()
            media = []
            for output in outputs:
                bindings = connection.execute("SELECT id,role,status FROM media_bindings WHERE media_id=? "
                    "AND target_id=? ORDER BY id", (output["id"], shot_id)).fetchall()
                media.append({**_media(project, output), "bindings": [dict(binding) for binding in bindings]})
            jobs.append({**dict(row), "outputs": media})
    return {"format": "vsc.series-shot-jobs/v1", "shot_id": shot_id, "jobs": jobs}


def episode(project, episode_id):
    state = series_state(project)
    _object(state, episode_id, "episode")
    children = {}
    for item in state["objects"]:
        children.setdefault(item.get("parent"), []).append(item)
    shots = []
    for scene in children.get(episode_id, []):
        if scene["kind"] != "scene":
            continue
        for sequence in children.get(scene["id"], []):
            if sequence["kind"] != "sequence":
                continue
            for shot in children.get(sequence["id"], []):
                if shot["kind"] == "shot":
                    shots.append({"id": shot["id"], "scene_id": scene["id"], "sequence_id": sequence["id"]})
    with db.connect(project) as connection:
        for shot in shots:
            rows = connection.execute("SELECT status,count(*) AS count FROM generation_jobs WHERE target_id=? "
                "GROUP BY status", (shot["id"],)).fetchall()
            shot["job_counts"] = {row["status"]: row["count"] for row in rows}
            selected = connection.execute("SELECT b.role,m.* FROM media_bindings b "
                "JOIN media_assets m ON m.id=b.media_id WHERE b.target_id=? "
                "AND b.status='approved' AND b.role IN ('composition','first_frame','last_frame','video_take','dialogue_dry') "
                "ORDER BY b.role", (shot["id"],)).fetchall()
            if any(row["rights"] not in ("owned", "licensed") for row in selected):
                raise SeriesError("本集已选媒体权属不可用：" + shot["id"])
            shot["selected_media"] = [{"role": row["role"], **_media(project, row)} for row in selected]
    return {"format": "vsc.series-episode-query/v1", "episode_id": episode_id, "shots": shots}


def script_line(project, episode_id, line_id):
    state = series_state(project)
    _object(state, episode_id, "episode")
    ref, _ = _select(project, state, "vsc.screenplay", episode_id)
    with db.connect(project) as connection:
        row = connection.execute("SELECT scene_id,payload FROM script_lines WHERE artifact_id=? AND line_id=?",
                                 (ref["id"], line_id)).fetchone()
    if not row:
        raise SeriesError("台词 ID 不在本集当前已批准剧本中")
    return {"format": "vsc.series-script-line/v1", "episode_id": episode_id,
            "scene_id": row["scene_id"], "line": json.loads(row["payload"]),
            "screenplay": {"id": ref["id"], "sha256": ref["sha256"]}}


def scene(project, scene_id):
    """Entry/exit continuity state of every shot in one scene from its approved scene_state."""
    state = series_state(project)
    episode_id = _object(state, scene_id, "scene").get("parent")
    ref, document = _select(project, state, "vsc.scene_state", episode_id,
        lambda doc: any(item.get("id") == scene_id for item in doc.get("scenes", [])))
    shots = [{"id": shot_id, **{key: value for key, value in item.items() if key != "scene"}}
             for shot_id, item in consistency.derive(document).items() if item["scene"] == scene_id]
    with db.connect(project) as connection:
        edges = [dict(row) for row in connection.execute(
            "SELECT from_shot,to_shot,strategy,actor,reason,created_at FROM continuity_edges "
            "WHERE status='active' ORDER BY created_at,id").fetchall()]
    inside = {shot["id"] for shot in shots}
    return {"format": "vsc.series-scene-state/v1", "scene_id": scene_id, "episode_id": episode_id,
            "scene_state": {"id": ref["id"], "sha256": ref["sha256"]}, "shots": shots,
            "cross_episode_boundaries": [edge for edge in edges if edge["to_shot"] in inside or edge["from_shot"] in inside]}


def media(project, media_id):
    """Every recorded consumer of one media item: bindings, derivations, origin job and referencing jobs."""
    series_state(project)
    root = Path(project).resolve()
    with db.connect(project) as connection:
        row = connection.execute("SELECT * FROM media_assets WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise SeriesError("媒体 ID 不存在：" + media_id)
        bindings = [dict(item) for item in connection.execute("SELECT id,target_id,role,variant,status,actor,reason "
            "FROM media_bindings WHERE media_id=? ORDER BY created_at,id", (media_id,)).fetchall()]
        parents = [dict(item) for item in connection.execute("SELECT parent_id,relation,parameters "
            "FROM asset_derivations WHERE child_id=? ORDER BY parent_id", (media_id,)).fetchall()]
        children = [dict(item) for item in connection.execute("SELECT child_id,relation,parameters "
            "FROM asset_derivations WHERE parent_id=? ORDER BY child_id", (media_id,)).fetchall()]
        origin = connection.execute("SELECT j.id AS job_id,j.target_id,j.purpose,j.candidate_no FROM generated_assets g "
            "JOIN generation_jobs j ON j.id=g.job_id WHERE g.media_id=?", (media_id,)).fetchone()
        rights = [{"rights": item["outcome"], "by": item["actor"], **json.loads(item["payload"])}
                  for item in connection.execute("SELECT outcome,actor,payload FROM approval_decisions "
                      "WHERE kind='media_rights' AND target=? ORDER BY id", (media_id,)).fetchall()]
        consumers = []
        for job in connection.execute("SELECT id,target_id,purpose,modality,candidate_no,status,request "
                "FROM generation_jobs WHERE instr(request, ?) > 0 ORDER BY created_at,id",
                (json.dumps(media_id, ensure_ascii=False),)).fetchall():
            logical = json.loads(job["request"])["logical_request"]
            used = {*logical.get("reference_media_ids", []),
                    *(logical.get(key) for key in ("first_frame_media_id", "last_frame_media_id", "voice_media_id"))}
            if media_id in used:
                consumers.append({key: job[key] for key in ("id", "target_id", "purpose", "modality", "candidate_no", "status")})
    path = (root / row["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        integrity = "missing"
    else:
        integrity = "ok" if sha256(path) == row["sha256"] else "sha_mismatch"
    return {"format": "vsc.series-media-query/v1",
            "media": {key: row[key] for key in ("id", "path", "sha256", "modality", "rights", "origin")},
            "bytes": integrity, "rights_decisions": rights, "generated_by": dict(origin) if origin else None,
            "derived_from": parents, "derivatives": children, "bindings": bindings, "referenced_by_jobs": consumers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("shot", "shot-jobs", "asset", "episode", "scene", "media", "line"))
    parser.add_argument("project"); parser.add_argument("id")
    parser.add_argument("--episode")
    args = parser.parse_args(argv)
    try:
        if args.command == "shot":
            result = build_shot_context(args.project, args.id)
        elif args.command == "shot-jobs":
            result = shot_jobs(args.project, args.id)
        elif args.command == "asset":
            result = asset(args.project, args.id)
        elif args.command == "episode":
            result = episode(args.project, args.id)
        elif args.command == "scene":
            result = scene(args.project, args.id)
        elif args.command == "media":
            result = media(args.project, args.id)
        else:
            if not args.episode:
                raise SeriesError("line 查询须指定 --episode")
            result = script_line(args.project, args.episode, args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SeriesError, db.SeriesStoreError, sqlite3.Error, OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
