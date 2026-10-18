"""Derive human-readable editor choices from fixed upstream facts."""
import json


def editor_inputs(service, project_id, draft):
    dependencies = draft.get("submission_context", {}).get("dependencies", [])
    plans = [row for row in dependencies if row["artifact_type"] == "vsc.adaptation_plan"]
    choices, narrative = [], {}
    for pin in plans:
        value = service.get_artifact_version(project_id, pin["id"])["document"]
        document = json.loads(value) if isinstance(value, str) else value
        if not isinstance(document, dict):
            continue
        for unit in document.get("screen_units", []):
            if draft["scope_key"] and unit.get("episode_id") != draft["scope_key"]:
                continue
            if unit.get("scene_id") and unit.get("id"):
                narrative.setdefault(unit["scene_id"], []).append({"id": unit["id"],
                    "label": unit.get("visible_action") or unit["id"]})
    nodes = service.get_project_tree(project_id)["nodes"]
    selected = {draft["scope_key"]} if draft["scope_key"] else {row["id"] for row in nodes}
    for _ in range(5):
        selected.update(row["id"] for row in nodes if row.get("parent_id") in selected)
    for row in nodes:
        if row["kind"] == "scene" and row["id"] in selected:
            choices.append({"id": row["id"], "label": row.get("title") or row.get("display_code") or row["id"]})
    draft["scene_choices"], draft["narrative_choices"] = choices, narrative
    if not draft["exists"]:
        draft["template_content"] = {"format": "vsc.screenplay/v1", "body": "", "scenes": [],
            "adaptation_refs": [{"id": pin["id"], "sha256": pin["sha256"]} for pin in plans]}
    return draft
