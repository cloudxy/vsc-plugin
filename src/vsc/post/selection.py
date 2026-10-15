#!/usr/bin/env python3
"""Keep series post selections consistent with the relational media registry.

In vsc.series-db projects the database holds media bytes, human rights decisions
and approved selection bindings; vsc.selected_takes stays the approved handoff
to post. `compile` drafts that handoff from approved video and dialogue bindings and
never approves anything. `selection_errors` runs inside selected-takes project
validation, so a hand-written list cannot contradict the database.
"""
import argparse
import json
import shlex
import sqlite3
import sys
from pathlib import Path

from vsc.adapters.persistence.sqlite import series as db
from vsc.production.series import SeriesError, _scope, build_shot_context, covered_script_units, series_state
from vsc.project.state import write_json

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
            chosen = [entry for entry in found if entry["id"] == row.get("output_id")]
            if not chosen:
                errors.append("output_id 与系列素材库中的文件不一致：" + str(row.get("id")))
                continue
            if len({entry["rights"] for entry in chosen}) != 1:
                errors.append("同一媒体在素材库有多个权属不同的 ID，须用 output_id 指明：" + str(row.get("id")))
                continue
            registered = chosen[0]
            if registered["rights"] not in ("owned", "licensed"):
                errors.append("获选媒体权属尚未经人审确认为 owned/licensed：" + str(row.get("id")))
            elif row.get("usage_rights") != registered["rights"]:
                errors.append("usage_rights 与素材库权属决定不一致：" + str(row.get("id")))
            role = SELECTION_FOR.get(registered["modality"])
            if registered["modality"] == "audio":
                origin = connection.execute("SELECT j.purpose FROM generated_assets g "
                    "JOIN generation_jobs j ON j.id=g.job_id WHERE g.media_id=?", (registered["id"],)).fetchone()
                if origin and origin["purpose"] == "dialogue_dry" and row.get("purpose") != "dialogue":
                    errors.append("对白干声不能改作其他声音用途：" + str(row.get("id")))
                if row.get("purpose") != "dialogue":
                    role = None
            if row.get("shot_id") and role:
                variant = row.get("cue_id") if role == "dialogue_dry" else None
                approved_rows = connection.execute(
                    "SELECT m.sha256 FROM media_bindings b JOIN media_assets m ON m.id=b.media_id "
                    "WHERE b.target_id=? AND b.role=? AND b.status='approved' AND IFNULL(b.variant,'')=IFNULL(?,'')",
                    (row["shot_id"], role, variant)).fetchall()
                approved = {entry["sha256"] for entry in approved_rows}
                if role == "dialogue_dry" and not approved:
                    errors.append("对白干声缺对应台词行的已批准选片：" + str(row.get("id")))
                if approved and media.get("sha256") not in approved:
                    errors.append(f"与数据库已批准的 {role} 选片不一致：" + str(row.get("id")))
    return errors


def compile_selected_takes(project, episode_id):
    """Draft visual and line-specific dialogue takes from approved bindings."""
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
            for role in ("video_take", "dialogue_dry"):
                rows = connection.execute("SELECT b.actor,b.variant,m.id,m.path,m.sha256,m.rights FROM media_bindings b "
                    "JOIN media_assets m ON m.id=b.media_id WHERE b.target_id=? AND b.role=? "
                    "AND b.status='approved' ORDER BY b.variant,m.id", (shot, role)).fetchall()
                if role == "video_take" and len(rows) > 1:
                    raise SeriesError(f"{shot} 有多个已批准 video_take；先退役多余选片")
                if role == "dialogue_dry" and len({row["variant"] for row in rows}) != len(rows):
                    raise SeriesError(f"{shot} 同一台词有多个已批准干声")
                if role == "dialogue_dry" and rows:
                    context = build_shot_context(project, shot)
                    _, covered_units = covered_script_units(project, shot)
                    line_order = {line["id"]: index for index, line in enumerate(
                        context["script_scene"].get("dialogue", [])) if isinstance(line, dict) and "id" in line}
                    if any(row["variant"] not in line_order or row["variant"] not in covered_units
                           for row in rows):
                        raise SeriesError(f"{shot} 已批准干声与当前镜头台词覆盖版本不一致")
                    rows = sorted(rows, key=lambda row: line_order[row["variant"]])
                for chosen in rows:
                    if role == "dialogue_dry" and not chosen["variant"]:
                        raise SeriesError(f"{shot} 的干声选片缺台词行 ID")
                    if chosen["rights"] not in ("owned", "licensed"):
                        raise SeriesError(f"{shot} 的获选素材权属未确认")
                    origin = connection.execute("SELECT job_id FROM generated_assets WHERE media_id=?", (chosen["id"],)).fetchone()
                    if not origin:
                        raise SeriesError(f"{shot} 的获选素材不是系列生成结果；手工素材按 selected-takes 模板写 manual 条目")
                    matches = records.get(origin["job_id"], [])
                    if len(matches) != 1:
                        raise SeriesError(f"{shot}：先导出并登记任务 {origin['job_id']} 的唯一生成记录")
                    record, document = matches[0]
                    if not any(out.get("id") == chosen["id"] and out.get("sha256") == chosen["sha256"]
                               for out in document.get("outputs", [])):
                        raise SeriesError(f"{shot}：生成记录 {record['id']} 不含获选输出")
                    owners = takes.get((shot, record["id"]), [])
                    if len(owners) != 1:
                        raise SeriesError(f"{shot}：先为生成记录 {record['id']} 登记唯一 take 对象")
                    if role == "dialogue_dry" and document.get("inputs", {}).get("line_id") != chosen["variant"]:
                        raise SeriesError(f"{shot}：干声生成记录与台词行绑定不一致")
                    item = {"id": "SEL-" + shot + ("-" + chosen["variant"] if role == "dialogue_dry" else ""),
                            "shot_id": shot, "take_id": owners[0], "output_id": chosen["id"],
                            "scope": episode_id, "purpose": "dialogue" if role == "dialogue_dry" else "visual",
                            "usage_rights": chosen["rights"], "selected_by": chosen["actor"],
                            "media": {"path": chosen["path"], "sha256": chosen["sha256"]},
                            "source": {"kind": "generation", "artifact": {"id": record["id"], "sha256": record["sha256"]}}}
                    if role == "dialogue_dry":
                        item["cue_id"] = chosen["variant"]
                    items.append(item)
                    depends.append(record["id"])
    if not items:
        raise SeriesError("本集没有已批准的视频或干声选片")
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
