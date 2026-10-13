#!/usr/bin/env python3
"""Keep series post selections consistent with the relational media registry.

In vsc.series-db projects the database holds media bytes, human rights decisions
and approved selection bindings; vsc.selected_takes stays the approved handoff
to post. `compile` drafts that handoff from approved video_take bindings and
never approves anything. `selection_errors` runs inside selected-takes project
validation, so a hand-written list cannot contradict the database.
"""
import argparse
import json
import shlex
import sqlite3
import sys
from pathlib import Path

import vsc_series_db as db
from vsc_series import SeriesError, _scope, series_state
from vsc_state import write_json

SELECTION_FOR = {"video": "video_take", "audio": "dialogue_dry"}


def selection_errors(project, data):
    """Each item must use registered bytes, a human rights decision and any approved selection of its shot."""
    errors = []
    with db.connect(project) as connection:
        for row in data.get("items", []):
            media = row.get("media", {})
            found = connection.execute("SELECT id,modality,rights FROM media_assets WHERE path=? AND sha256=?",
                                       (media.get("path"), media.get("sha256"))).fetchall()
            if not found:
                errors.append("获选媒体须先导入系列素材库：" + str(row.get("id")))
                continue
            chosen = [entry for entry in found if entry["id"] == row.get("output_id")] or found
            if len({entry["rights"] for entry in chosen}) != 1:
                errors.append("同一媒体在素材库有多个权属不同的 ID，须用 output_id 指明：" + str(row.get("id")))
                continue
            registered = chosen[0]
            if registered["rights"] not in ("owned", "licensed"):
                errors.append("获选媒体权属尚未经人审确认为 owned/licensed：" + str(row.get("id")))
            elif row.get("usage_rights") != registered["rights"]:
                errors.append("usage_rights 与素材库权属决定不一致：" + str(row.get("id")))
            role = SELECTION_FOR.get(registered["modality"])
            if row.get("shot_id") and role:
                approved = {entry["sha256"] for entry in connection.execute(
                    "SELECT m.sha256 FROM media_bindings b JOIN media_assets m ON m.id=b.media_id "
                    "WHERE b.target_id=? AND b.role=? AND b.status='approved'", (row["shot_id"], role)).fetchall()}
                if approved and media.get("sha256") not in approved:
                    errors.append(f"与数据库已批准的 {role} 选片不一致：" + str(row.get("id")))
    return errors


def compile_selected_takes(project, episode_id):
    """Draft one episode's selected takes from approved video_take bindings; returns (document, depends)."""
    state = series_state(project)
    if not any(item["id"] == episode_id and item["kind"] == "episode" for item in state["objects"]):
        raise SeriesError("分集不存在：" + episode_id)
    shots = [item["id"] for item in state["objects"]
             if item["kind"] == "shot" and _scope(state, item["id"])[0] == episode_id]
    animatics = [item["id"] for item in state["artifacts"] if item["type"] == "vsc.animatic"
                 and item["status"] == "approved" and not item.get("superseded_by")
                 and item.get("scope", "project") in ("project", episode_id)]
    if not animatics:
        raise SeriesError("本集缺已批准 animatic，选片清单无法登记")
    records = {}
    for item in state["artifacts"]:
        if item["type"] == "vsc.generation_record" and not item.get("superseded_by") and item["status"] != "rejected":
            document = json.loads(db.artifact_document(project, item["id"]))
            if document.get("series_job_id"):
                records.setdefault(document["series_job_id"], []).append((item, document))
    takes = {}
    for item in state["objects"]:
        if item["kind"] == "take" and item.get("artifact"):
            takes.setdefault((item.get("parent"), item["artifact"]), []).append(item["id"])
    items, depends = [], [animatics[-1]]
    with db.connect(project) as connection:
        for shot in shots:
            rows = connection.execute("SELECT b.actor,m.id,m.path,m.sha256,m.rights FROM media_bindings b "
                "JOIN media_assets m ON m.id=b.media_id WHERE b.target_id=? AND b.role='video_take' "
                "AND b.status='approved'", (shot,)).fetchall()
            if not rows:
                continue
            if len(rows) > 1:
                raise SeriesError(f"{shot} 有多个已批准 video_take；先退役多余选片")
            chosen = rows[0]
            if chosen["rights"] not in ("owned", "licensed"):
                raise SeriesError(f"{shot} 的获选视频权属未确认")
            origin = connection.execute("SELECT job_id FROM generated_assets WHERE media_id=?", (chosen["id"],)).fetchone()
            if not origin:
                raise SeriesError(f"{shot} 的获选视频不是系列生成结果；手工素材按 selected-takes 模板写 manual 条目")
            matches = records.get(origin["job_id"], [])
            if len(matches) != 1:
                raise SeriesError(f"{shot}：先用 vsc_series_export.py 导出并登记任务 {origin['job_id']} 的唯一生成记录")
            record, document = matches[0]
            if not any(out.get("id") == chosen["id"] and out.get("sha256") == chosen["sha256"]
                       for out in document.get("outputs", [])):
                raise SeriesError(f"{shot}：生成记录 {record['id']} 不含获选输出")
            owners = takes.get((shot, record["id"]), [])
            if len(owners) != 1:
                raise SeriesError(f"{shot}：先为生成记录 {record['id']} 登记唯一 take 对象")
            items.append({"id": "SEL-" + shot, "shot_id": shot, "take_id": owners[0], "output_id": chosen["id"],
                          "scope": episode_id, "purpose": "visual", "usage_rights": chosen["rights"],
                          "selected_by": chosen["actor"],
                          "media": {"path": chosen["path"], "sha256": chosen["sha256"]},
                          "source": {"kind": "generation", "artifact": {"id": record["id"], "sha256": record["sha256"]}}})
            depends.append(record["id"])
    if not items:
        raise SeriesError("本集没有已批准的 video_take 选片")
    document = {"format": "vsc.selected-takes/v1", "project_id": state["project_id"], "scope": episode_id, "items": items}
    return document, list(dict.fromkeys(depends))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("compile"); command.add_argument("project")
    command.add_argument("--episode", required=True); command.add_argument("--out", required=True)
    command = sub.add_parser("check"); command.add_argument("project"); command.add_argument("file")
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            document, depends = compile_selected_takes(args.project, args.episode)
            out = Path(args.out)
            if out.exists():
                raise SeriesError("输出已存在，拒绝覆盖")
            write_json(out, document)
            register = ["python3", "-B", "scripts/vsc_state.py", "artifact", "add", args.project,
                        "--type", "vsc.selected_takes", "--stage", "production", "--scope", args.episode, "--file", str(out)]
            for ref in depends:
                register += ["--depends", ref]
            print(f"OK 已编译 {len(document['items'])} 条获选草稿；登记后仍须人工批准：")
            print(shlex.join(register))
        else:
            series_state(args.project)
            problems = selection_errors(args.project, json.loads(Path(args.file).read_text("utf-8")))
            if problems:
                print("SELECTION: FAIL\n" + "\n".join(problems))
                return 1
            print("SELECTION: PASS（与素材库权属和已批准选片一致）")
    except (SeriesError, db.SeriesStoreError, sqlite3.Error, OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
