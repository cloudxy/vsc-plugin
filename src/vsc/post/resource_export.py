"""Export frozen relational timeline inputs for the existing local editors."""
import copy
import hashlib
import json
import mimetypes
from pathlib import Path
import shutil
import tempfile

from vsc.assets.resource_service import ResourceError
from vsc.post.remotion_plan import validate


def _subtitle_package(service, project_id, fixed, inputs, plan, *, formal):
    """Resolve approved Cue/line/selection relations, never JSON approval flags."""
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres import schema as S
    from vsc.post import subtitles as sub
    from vsc.post.remotion_plan import frame_rate
    fps = frame_rate(plan["composition"]["fps"])
    gaps, cue_rows, snapshots, lines, audio_sources = [], [], {}, [], []
    timeline_id, episode = fixed["id"], fixed["episode_id"]
    item_by_id = {item["id"]: item for item in fixed["items"]}
    inputs_by_item = {item["item_id"]: item for item in inputs}
    with service.store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            project = service.store._project(conn, project_id)
            if project["revision"] != fixed["revision"]:
                raise ResourceError("导出期间项目版本已改变", "export_revision_changed")
            p = project["id"]
            def approved_snapshot(identifier):
                if identifier not in snapshots:
                    row = service.store._one(conn, S.artifact_versions, p, identifier)
                    raw = bytes(row["document"])
                    if hashlib.sha256(raw).hexdigest() != row["sha256"] or not service.store._artifact_approved(conn, p, identifier):
                        raise ResourceError("字幕来源产物未批准或摘要失效", "subtitle_unapproved_source")
                    decision = service.store._latest(conn, S.artifact_decisions, p, "artifact_id", identifier)
                    snapshots[identifier] = {"id": identifier, "sha256": row["sha256"], "document_utf8": raw.decode("utf-8"),
                        "approval_decision_id": decision["id"]}
                return snapshots[identifier]
            approved_snapshot(fixed["artifact"]["id"])
            dependencies, queue = set(), [fixed["artifact"]["id"]]
            while queue:
                identifier = queue.pop()
                if identifier in dependencies:
                    continue
                dependencies.add(identifier)
                queue.extend(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                    S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == identifier)).scalars())
            scope_ids = service.store._descendant_ids(conn, p, episode)
            line_rows = conn.execute(select(S.script_lines).where(S.script_lines.c.project_id == p,
                S.script_lines.c.script_version_id.in_(dependencies), S.script_lines.c.scene_id.in_(scope_ids),
                S.script_lines.c.line_kind.in_(["dialogue", "narration"])).order_by(S.script_lines.c.ordinal, S.script_lines.c.id)).mappings().all()
            for row in line_rows:
                snapshot = approved_snapshot(row["script_version_id"])
                lines.append({"id": row["id"], "line_key": row["line_key"], "scene_id": row["scene_id"],
                    "ordinal": row["ordinal"], "text": row["text"], "script_version_id": row["script_version_id"],
                    "script_version_sha256": snapshot["sha256"]})
            line_by_id = {row["id"]: row for row in lines}
            audio_items = {}
            for item in fixed["items"]:
                for source in item.get("media", []):
                    if not source["mime_type"].startswith("audio/") or source["role"] not in {"dialogue_dry", "narration", "narration_dry"}:
                        continue
                    if item["id"] in audio_items:
                        gaps.append("声音用料不是唯一采用音频：" + item["id"])
                        continue
                    media = service.store._media(conn, p, source["media_id"])
                    decision = service.store._one(conn, S.binding_decisions, p, source["binding_decision_id"])
                    candidate = service.store._one(conn, S.binding_candidates, p, decision["candidate_id"])
                    slot = service.store._one(conn, S.binding_slots, p, decision["slot_id"])
                    coverage = service.store._one(conn, S.shot_line_coverage, p, slot["line_coverage_id"]) if slot.get("line_coverage_id") else None
                    if decision["outcome"] != "select" or candidate["media_id"] != source["media_id"] or media["sha256"] != source["blob_sha256"]:
                        gaps.append("采用决定、音频身份与固定SHA不一致")
                    record = {"item_id": item["id"], "media_id": source["media_id"], "sha256": source["blob_sha256"],
                        "item_ordinal": item["ordinal"],
                        "binding_decision_id": source["binding_decision_id"], "path": inputs_by_item[item["id"]]["path"],
                        "line_id": coverage["line_id"] if coverage else None,
                        "source_in_ms": source["source_in_frame"] * 1000 / fps,
                        "source_out_ms": source["source_out_frame"] * 1000 / fps,
                        "timeline_start_ms": item["offset_frame"] * 1000 / fps, "duration_ms": media["duration_ms"]}
                    audio_items[item["id"]] = record
                    audio_sources.append(record)
            # Separate timeline audio items may not replay the same source range
            # merely because a line/Cue spans several shots.
            for index, a in enumerate(audio_sources):
                for b in audio_sources[index + 1:]:
                    if a["sha256"] == b["sha256"] and max(a["source_in_ms"], b["source_in_ms"]) < min(a["source_out_ms"], b["source_out_ms"]):
                        gaps.append("跨镜Cue重复播放同一采用音频区间")
            links = conn.execute(select(S.cue_timeline_items).where(S.cue_timeline_items.c.project_id == p,
                S.cue_timeline_items.c.item_id.in_(item_by_id))).mappings().all()
            by_cue = {}
            for link in links:
                if link["item_id"] in audio_items:
                    by_cue.setdefault(link["cue_id"], []).append(link["item_id"])
            used_items = set()
            current_cue_versions = set(conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
                S.current_artifact_versions.c.project_id == p)).scalars())
            for identifier, item_ids in by_cue.items():
                cue = service.store._one(conn, S.sound_cues, p, identifier)
                if cue["cue_kind"] not in {"dialogue", "narration"} or cue["artifact_id"] not in current_cue_versions:
                    continue
                try:
                    cue_snapshot = approved_snapshot(cue["artifact_id"])
                    if cue["line_id"] not in line_by_id or cue["scope_object_id"] not in scope_ids:
                        raise ValueError("声音Cue超出批准剧本或分集范围")
                    if len(set(item_ids)) != 1:
                        raise ValueError("跨镜Cue须使用一个连续音频用料，不能按镜重复播放")
                    line, source = line_by_id[cue["line_id"]], audio_items[item_ids[0]]
                    if source["line_id"] != line["id"]:
                        raise ValueError("声音Cue与采用决定的批准台词行不一致")
                    covers = conn.execute(select(S.shot_line_coverage.c.shot_id).where(S.shot_line_coverage.c.project_id == p,
                        S.shot_line_coverage.c.line_id == cue["line_id"], S.shot_line_coverage.c.coverage_version_id.in_(dependencies))).scalars().all()
                    cue_shots = conn.execute(select(S.cue_shots.c.shot_id).where(S.cue_shots.c.project_id == p,
                        S.cue_shots.c.cue_id == identifier)).scalars().all()
                    if not covers or set(covers) != set(cue_shots) or not set(covers) <= scope_ids:
                        raise ValueError("声音Cue与固定镜头台词覆盖范围不一致")
                    alignment = cue["parameters"].get("subtitle_alignment")
                    if not isinstance(alignment, dict):
                        raise ValueError("缺少真实字幕时码测量")
                    if alignment.get("script_version_sha256") != line["script_version_sha256"] or alignment.get("audio_media_sha256") != source["sha256"]:
                        raise ValueError("字幕测量绑定了其他剧本或音频SHA")
                    start, end = alignment.get("start_ms"), alignment.get("end_ms")
                    errors = sub.measurement_errors(alignment.get("measurement"), line_key=line["line_key"], audio_sha256=source["sha256"], start_ms=start, end_ms=end)
                    if errors:
                        raise ValueError("；".join(errors))
                    if type(start) is not int or type(end) is not int or not source["source_in_ms"] <= start < end <= min(source["source_out_ms"], source["duration_ms"]):
                        raise ValueError("字幕实测区间超出采用音频裁切范围")
                    begin = source["timeline_start_ms"] + start - source["source_in_ms"]
                    finish = source["timeline_start_ms"] + end - source["source_in_ms"]
                    cue_rows.append({"cue_id": identifier, "cue_key": cue["cue_key"], "line_id": line["id"], "source_text": line["text"],
                        "script_version_sha256": line["script_version_sha256"], "audio_media_sha256": source["sha256"],
                        "item_id": source["item_id"], "source_start_ms": start, "source_end_ms": end, "start_ms": begin, "end_ms": finish,
                        "cue_artifact_id": cue["artifact_id"], "cue_artifact_sha256": cue_snapshot["sha256"],
                        "approval_decision_id": cue_snapshot["approval_decision_id"], "measurement": alignment["measurement"]})
                    used_items.add(source["item_id"])
                except (ValueError, ResourceError) as exc:
                    gaps.append(str(exc))
            if set(audio_items) - used_items:
                gaps.append("存在未绑定字幕Cue的采用对白音频")
            counts = {line["id"]: sum(cue["line_id"] == line["id"] for cue in cue_rows) for line in lines}
            gaps.extend("台词行缺失或重复字幕覆盖：" + key for key, count in counts.items() if count != 1)
            if audio_items and not lines:
                gaps.append("采用对白音频缺少时间线固定批准剧本行")
            if not lines and not audio_items:
                if formal and any(segment["kind"] == "caption" for segment in plan["segments"]):
                    raise ResourceError("正式字幕片段缺少固定批准台词行与采用音频", "subtitle_binding_missing")
                return None
            if formal and gaps:
                raise ResourceError("正式字幕交接失败：" + "；".join(gaps), "subtitle_binding_invalid")
            scripts = [snapshots[key] for key in dict.fromkeys(line["script_version_id"] for line in lines)]
            cue_artifacts = [snapshots[key] for key in dict.fromkeys(cue["cue_artifact_id"] for cue in cue_rows)]
            return sub.seal_package({"format": sub.PACKAGE_FORMAT, "project_id": p, "timeline_id": timeline_id,
                "source_project_revision": fixed["revision"],
                "scope_episode_id": episode, "timeline_artifact": snapshots[fixed["artifact"]["id"]],
                "scope_object_ids": sorted(scope_ids),
                "scope_scene_keys": list(conn.execute(select(S.creative_objects.c.display_code).where(S.creative_objects.c.project_id == p,
                    S.creative_objects.c.id.in_(scope_ids), S.creative_objects.c.kind == "scene")).scalars()),
                "duration_ms": plan["composition"]["duration_in_frames"] * 1000 / fps,
                "scripts": scripts, "lines": lines, "cue_artifacts": cue_artifacts, "audio_sources": audio_sources,
                "cues": sorted(cue_rows, key=lambda cue: (cue["start_ms"], cue["line_id"])),
                "status": "not_verified" if gaps else "verified", "gaps": gaps,
                "authority": "postgres_fixed_projection", "human_review": "not_run"})


def export_render_package(service, project_id, timeline_id, destination, *, formal_subtitles=True):
    """Read fixed selections, relocate verified bytes, preserve approved effects.

    This creates a reproducible projection, never a new approval or editable
    authority. Original captions/transitions/styles survive an embedded plan.
    A generic timeline must already specify its composition in approved content.
    """
    target = Path(destination)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ResourceError("导出目标必须是空目录", "export_not_empty")
    if service.storage is None:
        raise ResourceError("导出需要受控媒体存储", "storage_required")
    fixed = service.get_timeline(project_id, timeline_id)
    artifact = fixed["artifact"]
    document = json.loads(artifact["document"]) if isinstance(artifact["document"], str) else artifact["document"]
    embedded = isinstance(document, dict) and isinstance(document.get("render_plan"), dict)
    if embedded:
        plan = copy.deepcopy(document["render_plan"])
    else:
        composition = document.get("composition") if isinstance(document, dict) else None
        if not composition:
            raise ResourceError("固定时间线没有批准的合成规格", "render_composition_missing")
        plan = {"format": "vsc.remotion-render-plan/v1", "project_id": project_id, "composition": copy.deepcopy(composition), "segments": []}
        if document.get("subtitle_style"):
            plan["subtitle_style"] = copy.deepcopy(document["subtitle_style"])
    if plan.get("project_id") != project_id:
        raise ResourceError("合成规格与项目不一致", "render_project_mismatch")
    fps = plan.get("composition", {}).get("fps")
    timeline = fixed.get("timeline", fixed)
    from vsc.post.remotion_plan import frame_rate
    if frame_rate(fps) != timeline["fps_num"] / timeline["fps_den"]:
        raise ResourceError("固定时间线与合成规格帧率不一致", "render_fps_mismatch")
    inputs = []
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".vsc-export-", dir=target.parent) as temporary:
        work = Path(temporary)
        (work / "media").mkdir()
        for item in fixed["items"]:
            sources = item.get("media", [])
            if embedded and len(sources) != 1:
                raise ResourceError("原时间线片段没有唯一固定媒体", "ambiguous_timeline_source")
            for index, source in enumerate(sources):
                sha = source["blob_sha256"]
                path = None
                for location in source["locations"]:
                    if location["storage"] == "local" and location["available"]:
                        path = service.storage.verify(location["object_key"], sha)
                        break
                if path is None:
                    raise ResourceError("时间线固定输入缺少可读副本", "media_unavailable")
                suffix = mimetypes.guess_extension(source["mime_type"]) or ".bin"
                relative = "media/" + sha + suffix
                destination_path = work / relative
                shutil.copyfile(path, destination_path)
                if hashlib.sha256(destination_path.read_bytes()).hexdigest() != sha:
                    raise ResourceError("素材在导出时改变", "media_changed")
                if embedded:
                    ordinal = item["ordinal"]
                    if ordinal >= len(plan["segments"]) or "source" not in plan["segments"][ordinal]:
                        raise ResourceError("固定关系与原时间线片段不一致", "timeline_projection_mismatch")
                    segment = plan["segments"][ordinal]
                    if (segment["from_frame"], segment["duration_in_frames"], segment.get("source_in_frame", 0)) != (
                            item["offset_frame"], item["duration_frames"], source["source_in_frame"]):
                        raise ResourceError("片段裁切与固定关系不一致", "timeline_projection_mismatch")
                    segment["source"] = relative
                else:
                    kind = source["mime_type"].split("/", 1)[0]
                    if kind not in {"video", "audio", "image"}:
                        raise ResourceError("编辑器不支持该固定输入格式", "editor_format_unsupported")
                    segment = {"id": "segment-" + item["id"] + "-" + str(index), "kind": kind,
                        "source": relative, "from_frame": item["offset_frame"],
                        "duration_in_frames": item["duration_frames"], "source_in_frame": source["source_in_frame"]}
                    if item.get("shot_id"):
                        segment["source_shot_id"] = item["shot_id"]
                    if kind == "video":
                        segment["muted"] = True
                    segment.update(item.get("envelope", {}))
                    plan["segments"].append(segment)
                inputs.append({"item_id": item["id"], "media_id": source["media_id"], "blob_id": source["blob_id"],
                    "sha256": sha, "binding_decision_id": source["binding_decision_id"], "role": source["role"], "path": relative})
        from vsc.post import subtitles as sub
        package = _subtitle_package(service, project_id, fixed, inputs, plan, formal=formal_subtitles)
        if package is not None:
            sub.package_cues(package, work, project_id=project_id, formal=formal_subtitles)
            plan["subtitle_package"] = package
            plan["segments"] = [segment for segment in plan["segments"] if segment["kind"] != "caption"] + sub.caption_segments(package, frame_rate(fps))
            (work / "subtitles.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", "utf-8")
        errors = validate(plan)
        if errors:
            raise ResourceError("导出合成规格不符合编辑器契约: " + "; ".join(errors), "invalid_render_plan")
        serialized = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        (work / "render-plan.json").write_text(serialized, "utf-8")
        receipt = {"format": "vsc.resource-render-package/v1", "project_id": project_id, "timeline_id": timeline_id,
            "source_artifact": {"id": artifact["id"], "sha256": artifact["sha256"]}, "inputs": inputs,
            "plan_sha256": hashlib.sha256(serialized.encode()).hexdigest(), "authority": "read_only_projection",
            "subtitle_package_sha256": package["package_sha256"] if package else None,
            "subtitle_status": package["status"] if package else "not_verified" if any(s["kind"] == "caption" for s in plan["segments"]) else "not_applicable",
            "subtitle_gaps": package["gaps"] if package else ["字幕没有固定批准台词行与采用音频"] if any(s["kind"] == "caption" for s in plan["segments"]) else [],
            "verification": {"bytes": "verified", "editor_render": "not_run", "human_review": "not_run"}}
        (work / "render-inputs.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
        if service.get_project(project_id)["revision"] != fixed["revision"]:
            raise ResourceError("导出期间批准关系已改变，请重试", "export_revision_changed")
        if target.exists():
            target.rmdir()
        shutil.move(str(work), str(target))
    return dict(receipt, directory=str(target))


def scaffold_render_package(directory, destination):
    """Prepare the existing Remotion engine with all verified fixed media."""
    from vsc.post.remotion_plan import scaffold
    root = Path(directory).resolve()
    receipt = json.loads((root / "render-inputs.json").read_text("utf-8"))
    plan_path = root / "render-plan.json"
    if hashlib.sha256(plan_path.read_bytes()).hexdigest() != receipt["plan_sha256"]:
        raise ResourceError("导出合成计划摘要已改变", "render_plan_changed")
    sources = []
    for item in receipt["inputs"]:
        source = (root / item["path"]).resolve()
        if not source.is_relative_to(root) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ResourceError("导出媒体缺失或摘要不符", "media_changed")
        sources.append((item, source))
    result = scaffold(json.loads(plan_path.read_text("utf-8")), destination, plan_path=plan_path)
    for item, source in sources:
        target = Path(destination) / "public" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise ResourceError("媒体在编辑器准备过程中改变", "media_changed")
    (Path(destination) / "vsc-resource-inputs.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return result
