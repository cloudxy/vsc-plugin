"""Fixed localization semantics, compiled into the existing classic/run path."""
from copy import deepcopy
import json

from vsc.assets.resource_service import ResourceError

BASELINE_TYPES = {"understanding": "overseas-understanding", "localization": "overseas-localization"}


def entity_refs(value):
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def duration(group):
    return group.get("target_duration_ms") or group["source_end_ms"] - group["source_start_ms"]


def normalize(document):
    entities = {r["key"]: r for r in document["entities"]}
    if len(entities) != len(document["entities"]):
        raise ResourceError("实体 UID 不可重复")
    for row in entities.values():
        row["kind"] = row.get("kind") or "character"
        if row["kind"] not in {"character", "scene"}:
            raise ResourceError("实体类型须为 character 或 scene")
    if len({r["key"] for r in document["segments"]}) != len(document["segments"]):
        raise ResourceError("镜头 UID 不可重复")
    groups = {r["key"]: r for r in document["groups"]}
    for row in document["segments"]:
        refs = entity_refs(row["entity_keys"])
        if any(key not in entities or entities[key]["kind"] != "character" for key in refs):
            raise ResourceError("角色引用须使用当前角色 UID；删除前请迁移引用")
        if row["scene_key"] and (row["scene_key"] not in entities or entities[row["scene_key"]]["kind"] != "scene"):
            raise ResourceError("场景引用须使用当前场景 UID；删除前请迁移引用")
        row["entity_keys"] = ",".join(refs)
        group = groups[row["group"]]
        if not row["target_end_ms"]:
            row["target_start_ms"] = row["source_start_ms"] - group["source_start_ms"]
            row["target_end_ms"] = row["source_end_ms"] - group["source_start_ms"]
        if not 0 <= row["target_start_ms"] < row["target_end_ms"] <= duration(group):
            raise ResourceError("目标组内区间须位于目标生成时长内")
    return document


def snapshot(document, phase):
    """Exclude mutable selection/production controls from the understanding basis."""
    result = {"source_media_id": document["source_media_id"], "understanding": document["understanding"],
              "evidence_kind": "human-observation", "entities": [], "segments": []}
    for entity in document["entities"]:
        fields = ("key", "kind", "name") if phase == "understanding" else ("key", "kind", "name", "localized", "asset_id", "media_id")
        result["entities"].append({k: entity[k] for k in fields})
    for row in document["segments"]:
        fields = ("key", "source_start_ms", "source_end_ms", "source_text", "entity_keys", "scene_key")
        if phase == "localization": fields += ("group", "target_start_ms", "target_end_ms", "localized_text")
        result["segments"].append({k: row[k] for k in fields})
    if phase == "localization":
        result.update(target_language=document["target_language"], body=document["body"],
                      understanding_version_id=document["understanding_version_id"],
                      groups=[{k: g[k] for k in ("key", "source_start_ms", "source_end_ms", "target_duration_ms", "shot_id", "prompt", "first_frame_media_id")} for g in document["groups"]])
    return result


def coverage(document, source_duration):
    cursor = 0
    for row in sorted(document["segments"], key=lambda r: r["source_start_ms"]):
        if row["source_start_ms"] != cursor or not row["source_text"].strip():
            raise ResourceError("理解确认需要从 0 开始连续覆盖源片的镜头及人工观察；请检查空隙、重叠或空正文", "overseas_coverage")
        cursor = row["source_end_ms"]
    if not cursor or cursor != source_duration:
        raise ResourceError("理解镜头结束时间须覆盖完整源片", "overseas_coverage")


def merge(document, source_key, target_key):
    result = deepcopy(document)
    entities = {r["key"]: r for r in result["entities"]}
    source, target = entities.get(source_key), entities.get(target_key)
    if not source or not target or source_key == target_key or source["kind"] != target["kind"]:
        raise ResourceError("请选择两个不同的同类实体 UID")
    affected = []
    for row in result["segments"]:
        before = {k: row[k] for k in ("entity_keys", "scene_key")}
        row["entity_keys"] = ",".join(dict.fromkeys(target_key if k == source_key else k for k in entity_refs(row["entity_keys"])))
        if row["scene_key"] == source_key: row["scene_key"] = target_key
        after = {k: row[k] for k in before}
        if before != after: affected.append({"segment_key": row["key"], "group_key": row["group"], "before": before, "after": after})
    result["entities"] = [r for r in result["entities"] if r["key"] != source_key]
    # An edit never reuses confirmation of different understanding content.
    result["understanding_version_id"] = ""
    return result, {"source": source, "target": target, "affected_segments": affected,
                    "affected_groups": [g for g in document["groups"] if g["key"] in {r["group_key"] for r in affected}],
                    "asset_policy": "保留目标实体的显式资产与图片映射；原全局资产身份不改动", "confirmation_invalidated": True}


def classic_document(document, group_key, settings):
    group = next((r for r in document["groups"] if r["key"] == group_key), None)
    if not group or not group["shot_id"]:
        raise ResourceError("分组需要明确映射到原项目镜头")
    if duration(group) % 1000:
        raise ResourceError("原视频预算与执行协议要求目标生成时长为整秒；源片区间仍保留毫秒，不自动取整", "overseas_duration")
    allowed = {"mode", "model_id", "count", "width", "height", "params", "references"}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ResourceError("分组制作参数格式无效")
    mode = settings.get("mode", "single")
    if mode not in {"single", "first_last", "multi", "text"}:
        raise ResourceError("分组仅支持原已接入视频模式")
    refs = deepcopy(settings.get("references", []))
    if not refs and group["first_frame_media_id"] and mode in {"single", "first_last", "multi"}:
        refs = [{"role": "first_frame", "media_id": group["first_frame_media_id"]}]
    prompt = json.dumps({"target_language": document["target_language"], "localized_body": document["body"],
        "group_prompt": group["prompt"], "source_interval_ms": [group["source_start_ms"], group["source_end_ms"]],
        "target_duration_ms": duration(group), "entities": document["entities"],
        "segments": [r for r in document["segments"] if r["group"] == group_key]}, ensure_ascii=False)
    return {**settings, "mode": mode, "shot_id": group["shot_id"], "purpose": "text_to_video" if mode == "text" else "image_to_video", "prompt": prompt,
            "duration_ms": duration(group), "references": refs}
