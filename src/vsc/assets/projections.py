"""Read-only projections from canonical VSC documents, preserving source bytes.

Object aliases are supplied by the typed repository. Missing mappings are errors;
the parser never invents hierarchy, assets, approval or a narrator identity.
"""
import copy
import hashlib
import json
import uuid
from vsc.assets.resource_service import ResourceError

PARSER_VERSION = "vsc-resource-projections-v1"
SUPPORTED_FORMATS = frozenset({"vsc.asset-bible/v1", "vsc.scene-state/v1", "vsc.screenplay/v1", "vsc.coverage-plan/v1"})


def normalize_artifact_payload(original_doc, id_map):
    """Return untouched document plus deterministic relational projections.

    ``id_map`` has typed dictionaries (scene/shot/asset/script_lines/asset_specs)
    and line_texts. A UUID may be used directly. Projections are derived inside
    the repository transaction; they are never separately editable input facts.
    """
    if isinstance(original_doc, (str, bytes)):
        doc = json.loads(original_doc)
    else:
        doc = original_doc
    if not isinstance(doc, dict):
        return {"document": original_doc, "projections": {}, "parser_version": PARSER_VERSION}
    signature = hashlib.sha256((json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + str(id_map.get("_artifact_version_id", ""))).encode()).hexdigest()
    def identity(kind, key, optional=False):
        if key is None and optional:
            return None
        found = id_map.get(kind, {}).get(key) if isinstance(id_map.get(kind), dict) else None
        if found is None:
            found = id_map.get(key)
        if found is None:
            try:
                found = str(uuid.UUID(str(key)))
            except (ValueError, TypeError, AttributeError):
                raise ResourceError("原规范文档缺少%s映射: %s" % (kind, key), "projection_mapping_missing")
        return found
    def projected_id(kind, key):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc-projection:" + signature + ":" + kind + ":" + str(key)))
    projections = {}
    fmt = doc.get("format")
    if fmt == "vsc.asset-bible/v1":
        specs = []
        for entity in doc.get("entities", []):
            asset_id = identity("asset", entity["id"])
            for variant in entity.get("variants", {"default": None}):
                specs.append({"id": projected_id("asset-spec", entity["id"] + ":" + variant),
                    "asset_id": asset_id, "variant_key": "master" if variant == "default" else variant})
        projections["asset_specs"] = specs
    elif fmt == "vsc.screenplay/v1":
        lines = []
        for scene in doc.get("scenes", []):
            scene_id = identity("scene", scene["id"])
            for key in ("actions", "dialogue", "silence"):
                for unit in scene.get(key, []):
                    kind = "dialogue" if key == "dialogue" else "action"
                    speaker = unit.get("speaker")
                    if unit.get("kind") == "narration":
                        kind = "narration"
                    lines.append({"id": projected_id("script-line", unit["id"]), "scene_id": scene_id,
                        "line_key": unit["id"], "line_kind": kind,
                        "speaker_id": identity("asset", speaker) if speaker and kind == "dialogue" else None,
                        "text": unit.get("text", unit.get("purpose", "静默"))})
        projections["script_lines"] = lines
    elif fmt == "vsc.scene-state/v1":
        from vsc.story.consistency import derive
        derived = derive(doc)
        states = []
        for scene in doc.get("scenes", []):
            for shot in scene.get("shots", []):
                state = derived[shot["id"]]
                present = set(state["entry"]["entities"]) | set(state["exit"]["entities"])
                framed = set(state.get("in_frame", present))
                entities = []
                for key in sorted(present):
                    asset_id = identity("asset", key)
                    variant = state["entry"]["entities"].get(key, state["exit"]["entities"].get(key, {})).get("variant", "default")
                    spec = id_map.get("asset_specs", {}).get(key + ":" + variant)
                    entities.append({"asset_id": asset_id, "relation": "present", "spec_version_id": spec})
                    if key in framed:
                        entities.append({"asset_id": asset_id, "relation": "in_frame", "spec_version_id": spec})
                states.append({"id": projected_id("state", shot["id"]), "scene_id": identity("scene", scene["id"]),
                    "shot_id": identity("shot", shot["id"]), "location_id": identity("asset", state["location_id"]), "entities": entities})
        projections["state_versions"] = states
    elif fmt == "vsc.coverage-plan/v1":
        coverage = []
        script = doc.get("screenplay", {}).get("id")
        for scene in doc.get("scenes", []):
            for sequence in scene.get("sequences", []):
                for shot in sequence.get("shots", []):
                    explicit_ranges = {r["line_id"]: r for r in shot.get("line_ranges", [])}
                    for key in shot.get("screenplay_unit_ids", []):
                        scoped_key = str(script) + ":" + key
                        line_id = id_map.get("script_lines", {}).get(scoped_key)
                        if not line_id:
                            raise ResourceError("覆盖计划缺少固定剧本行映射: " + key, "projection_mapping_missing")
                        line_text = id_map.get("line_texts", {}).get(line_id)
                        if line_text is None:
                            raise ResourceError("覆盖计划缺少固定剧本原文", "projection_mapping_missing")
                        segment = explicit_ranges.get(key, {})
                        coverage.append({"id": projected_id("coverage", shot["id"] + ":" + key),
                            "shot_id": identity("shot", shot["id"]), "line_id": line_id,
                            "start_char": segment.get("start_char", 0), "end_char": segment.get("end_char", len(line_text))})
        projections["line_coverage"] = coverage
    return {"document": original_doc, "projections": projections, "parser_version": PARSER_VERSION}
