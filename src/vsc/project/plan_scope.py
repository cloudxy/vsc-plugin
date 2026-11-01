"""One applicability rule for explicitly scoped production plans."""
import json

PLAN_FORMATS = {"vsc.continuity-plan/v1", "vsc.sound-cue-sheet/v1", "vsc.animatic/v1"}


def plan_applies(artifact, object_keys):
    try:
        document = artifact["document"]
        document = json.loads(document) if isinstance(document, (str, bytes)) else document
    except (ValueError, TypeError, UnicodeDecodeError):
        return True  # Contract validation owns malformed documents.
    if not isinstance(document, dict) or document.get("format") not in PLAN_FORMATS:
        return True
    for kind in ("scene", "sequence"):
        owners = document.get(kind + "_ids")
        if owners is not None:
            # A multi-scene plan explicitly declares a set. Never broaden a
            # single-scene owner merely because some nested shot happens to fit.
            if not isinstance(owners, list) or not owners or any(not isinstance(owner, str) for owner in owners):
                return False
            if not set(owners) & set(object_keys.get(kind, [])):
                return False
        else:
            owner = document.get(kind + "_id")
            if owner and owner not in object_keys.get(kind, []):
                return False
    if document.get("format") == "vsc.continuity-plan/v1" and isinstance(document.get("shots"), list):
        shots = {row.get("id") for row in document["shots"] if isinstance(row, dict)}
        shots.update(link.get("shot_id") for unit in document.get("design_units", []) if isinstance(unit, dict)
                     for link in unit.get("shots", []) if isinstance(link, dict))
        return bool(shots & set(object_keys.get("shot", [])))
    return True


def partition_plans(service, project_id, scope, candidates):
    """Return a complete disjoint per-shot partition, or actionable conflicts."""
    tree = service.get_project_tree(project_id)
    nodes = {node["id"]: node for node in tree["nodes"]}
    documents = {row["id"]: service.get_artifact_version(project_id, row["id"]) for row in candidates}
    used, gaps, count = set(), [], 0
    for shot in (node for node in nodes.values() if node["kind"] == "shot"):
        ancestors, keys = [], {}
        node = shot
        while node and node["id"] not in ancestors:
            ancestors.append(node["id"])
            keys.setdefault(node["kind"], set()).update({node["id"], node.get("display_code", node["id"])})
            node = nodes.get(node.get("parent_id"))
        if scope and scope not in ancestors:
            continue
        count += 1
        applicable = []
        for row in candidates:
            owners = row.get("object_ids", [])
            if owners and not set(owners) & set(ancestors):
                continue
            if plan_applies(documents[row["id"]], keys):
                applicable.append(row["id"])
        if len(applicable) != 1:
            gaps.append({"code": "plan_scope_conflict" if applicable else "plan_scope_missing",
                         "shot_id": shot["id"], "artifact_ids": applicable})
        used.update(applicable)
    if not count:
        gaps.append({"code": "plan_scope_empty", "artifact_ids": sorted(documents)})
    return [row for row in candidates if row["id"] in used], gaps
