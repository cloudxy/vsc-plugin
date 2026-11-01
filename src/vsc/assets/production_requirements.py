"""Read-only demand reduction over fixed requirements and actual ShotContexts.

Identity/specification IDs are the grouping authority. Names never create or
merge identities. Task candidates still need the ordinary approved run; this
module neither selects media nor manufactures prompts or another job queue.
"""
import hashlib
import json

from vsc.assets.resource_service import Conflict, ResourceError


REFERENCE_ROLES = {
    "character": {"identity_face"}, "location": {"location_master", "location_view"},
    "prop": {"prop"}, "object": {"prop"}, "creature": {"prop"}, "vehicle": {"prop"},
    "plant": {"prop"}, "voice": {"voice_sample"}, "style": {"style_reference"}, "costume": {"costume"},
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def preview_requirements(service, project_id, payload):
    if not isinstance(payload, dict):
        raise ResourceError("需求预览须为对象", "invalid_requirement_batch")
    episodes = payload.get("episode_ids")
    if (not isinstance(episodes, list) or not 1 <= len(episodes) <= 200 or
            any(not isinstance(item, str) or not item for item in episodes) or len(set(episodes)) != len(episodes)):
        raise ResourceError("须选择1至200个不重复的分集ID", "invalid_requirement_batch")
    purpose = payload.get("purpose", "video_clip")
    if purpose not in {"video_clip", "image_to_video", "i2v", "keyframe", "shot_keyframe", "ref"}:
        raise ResourceError("需求汇总仅支持画面制作用途", "invalid_requirement_purpose")
    facts = service.store.production_requirement_facts(project_id, sorted(episodes), purpose)
    objects = {row["id"]: row for row in facts["objects"]}
    shots = sorted(identifier for identifier, row in objects.items() if row["kind"] == "shot")
    contexts = {shot: service.compile_shot_context(project_id, shot, purpose=purpose) for shot in shots}
    identities = {row["id"]: row for row in facts["identities"]}
    specs = {row["id"]: row for row in facts["specifications"]}
    instances = {row["id"]: row for row in facts["instances"]}
    bindings = {row["id"]: row for row in facts["bindings"]}
    pins = {(row["artifact_id"], row["asset_id"]): row["spec_version_id"] for row in facts["asset_pins"]}
    artifacts = {row["id"]: row for row in facts["artifacts"]}

    def consumers(row):
        if row["shot_id"]:
            return [row["shot_id"]] if row["shot_id"] in contexts else []
        return [shot for shot in shots if objects.get(objects[shot]["parent_id"], {}).get("parent_id") == row["scene_id"]]

    groups = {}
    for row in facts["requirements"]:
        used_by = consumers(row)
        if not used_by:
            continue
        asset_id = row["asset_id"]
        instance = instances.get(row["instance_id"], {})
        spec_id = row["spec_version_id"] or instance.get("spec_version_id") or pins.get((row["artifact_id"], asset_id))
        spec = specs.get(spec_id, {})
        identity = identities.get(asset_id, {})
        # Unresolved identities remain individual source requirements even when
        # their descriptions happen to be identical.
        key = _digest([asset_id or row["id"], spec_id, purpose])
        group = groups.setdefault(key, {"key": key, "asset_id": asset_id,
            "title": identity.get("title") or identity.get("display_code") or row["description"],
            "spec_version_id": spec_id, "variant_key": spec.get("variant_key"), "purpose": purpose,
            "classification": "needs_reference", "consumer_shot_ids": [], "instance_ids": [],
            "requirements": [], "source_refs": [], "selected_media": [], "gaps": [], "missing_reference": False})
        group["consumer_shot_ids"].extend(used_by)
        if row["instance_id"]:
            group["instance_ids"].append(row["instance_id"])
        group["requirements"].append(row)
        group["source_refs"].append({"id": row["artifact_id"], "sha256": row["source_sha256"],
                                     "line_ids": row["line_ids"], "requirement_id": row["id"]})
        if spec:
            group["source_refs"].append({"id": spec["artifact_id"], "sha256": artifacts[spec["artifact_id"]]["sha256"]})
        if not asset_id:
            group["gaps"].append({"code": "identity_unresolved", "requirement_id": row["id"]})
            continue
        if not spec or not spec.get("approved"):
            group["gaps"].append({"code": "fixed_spec_missing_or_unapproved", "requirement_id": row["id"]})
        if instance.get("spec_version_id") and spec_id != instance["spec_version_id"]:
            group["gaps"].append({"code": "instance_spec_conflict", "requirement_id": row["id"]})
        roles = REFERENCE_ROLES.get(identity.get("asset_kind"), set())
        required = [slot for slot in row["slots"] if slot["role"] in {"fulfills", "post"}]
        for shot in used_by:
            selected = []
            for media in contexts[shot]["media"]:
                if any(gap.get("media_id") == media["media_id"] for gap in contexts[shot]["gaps"]):
                    continue
                slot = bindings.get(media.get("slot_id"), {})
                bound_asset = slot.get("identity_asset_id") or slot.get("target_object_id")
                if bound_asset != asset_id or media["role"] not in roles:
                    continue
                variant = slot.get("variant_spec_id")
                if variant and variant != spec_id or spec.get("variant_key") not in {None, "master", "default"} and variant != spec_id:
                    continue
                selected.append({key: media.get(key) for key in (
                    "media_id", "sha256", "role", "slot_id", "candidate_id", "binding_decision_id")})
            group["selected_media"].extend(selected)
            if not selected:
                group["missing_reference"] = True
                group["gaps"].append({"code": "reference_missing", "shot_id": shot, "requirement_id": row["id"]})
            available_slots = {media["slot_id"] for media in contexts[shot]["media"]}
            for slot in required:
                if not slot["usable"] or slot["slot_id"] not in available_slots:
                    group["gaps"].append({"code": "requirement_binding_unusable", "shot_id": shot,
                        "requirement_id": row["id"], "slot_id": slot["slot_id"], "reasons": slot["reasons"]})
        if not required:
            group["gaps"].append({"code": "requirement_binding_missing", "requirement_id": row["id"]})

    tasks = []
    for group in groups.values():
        for field in ("consumer_shot_ids", "instance_ids"):
            group[field] = sorted(set(group[field]))
        for field in ("source_refs", "selected_media", "gaps"):
            group[field] = [value for _, value in sorted({_digest(value): value for value in group[field]}.items())]
        missing = group.pop("missing_reference")
        errors = {gap["code"] for gap in group["gaps"]}
        identity_slots = {identifier for identifier, slot in bindings.items()
                          if (slot.get("identity_asset_id") or slot.get("target_object_id")) == group["asset_id"]}
        conflict = "instance_spec_conflict" in errors or any(
            gap["code"] in {"asset_version_conflict", "binding_conflict"} and
            (gap.get("asset_id") == group["asset_id"] or set(gap.get("slot_ids", [])) &
             identity_slots)
            for shot in group["consumer_shot_ids"] for gap in contexts[shot]["gaps"])
        if conflict:
            group["classification"] = "conflict"
            group["gaps"].append({"code": "identity_or_binding_conflict"})
        elif not group["asset_id"]:
            group["classification"] = "new_identity"
        elif not missing and "fixed_spec_missing_or_unapproved" not in errors:
            group["classification"] = "reuse"
        elif group["variant_key"] not in {None, "master", "default"}:
            group["classification"] = "variant"
        if missing and not conflict and group["asset_id"] and "fixed_spec_missing_or_unapproved" not in errors:
            available = False
            asset_context = None
            limitations = []
            if identities[group["asset_id"]]["asset_kind"] == "voice":
                limitations.append({"code": "asset_generation_unsupported"})
            else:
                asset_context = service.compile_asset_context(project_id, group["asset_id"], purpose="asset_ref",
                    spec_version_id=group["spec_version_id"])
                available = asset_context["ready"] and any(row["id"] == specs[group["spec_version_id"]]["artifact_id"]
                    for row in asset_context["artifacts"])
                limitations = asset_context["gaps"]
                if not available and not limitations:
                    limitations = [{"code": "asset_context_spec_mismatch"}]
            tasks.append({"key": group["key"], "asset_id": group["asset_id"],
                "spec_version_id": group["spec_version_id"], "variant_key": group["variant_key"],
                "purpose": "asset_ref", "consumer_shot_ids": group["consumer_shot_ids"],
                "requirement_ids": [row["id"] for row in group["requirements"]], "reason": "reference_missing",
                "execution_available": available, "gaps": limitations,
                "context_sha256": asset_context["sha256"] if asset_context else None,
                "requires": ["fixed_prompt", "provider_model", "approved_production_run"]})
    # Contexts compile through the normal live authority. A concurrent edit must
    # not yield a digest mixing two revisions or be mistaken for approval.
    if service.get_project(project_id)["revision"] != facts["revision"]:
        raise Conflict("需求预览期间项目发生变化，请刷新后重试")
    result = {"project_id": facts["project_id"], "revision": facts["revision"],
        "episode_ids": facts["episode_ids"], "purpose": purpose,
        "groups": sorted(groups.values(), key=lambda row: row["key"]),
        "asset_tasks": sorted(tasks, key=lambda row: row["key"]), "future_count": facts["future_count"],
        "shot_readiness": [{"shot_id": shot, "ready": contexts[shot]["ready"], "gaps": contexts[shot]["gaps"],
            "context_sha256": contexts[shot]["sha256"]} for shot in shots]}
    result["sha256"] = _digest(result)
    return result
