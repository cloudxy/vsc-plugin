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


def export_render_package(service, project_id, timeline_id, destination):
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
        errors = validate(plan)
        if errors:
            raise ResourceError("导出合成规格不符合编辑器契约: " + "; ".join(errors), "invalid_render_plan")
        serialized = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        (work / "render-plan.json").write_text(serialized, "utf-8")
        receipt = {"format": "vsc.resource-render-package/v1", "project_id": project_id, "timeline_id": timeline_id,
            "source_artifact": {"id": artifact["id"], "sha256": artifact["sha256"]}, "inputs": inputs,
            "plan_sha256": hashlib.sha256(serialized.encode()).hexdigest(), "authority": "read_only_projection",
            "verification": {"bytes": "verified", "editor_render": "not_run", "human_review": "not_run"}}
        (work / "render-inputs.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
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
