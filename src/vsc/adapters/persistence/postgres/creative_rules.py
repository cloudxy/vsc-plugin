"""Read opt-in constraints through existing PG facts and immutable approvals."""
import json
from sqlalchemy import select, text
from . import schema as S
from vsc.project.creative_rules import context_diagnostics


def _sound_report(store, conn, project, artifact, data):
    """Only newly declared sound fields enable this PG approval check."""
    from vsc.post.sound_rules import extra_cue_errors
    from vsc.assets.resource_service import ResourceError
    from .values import checked_id
    music = data.get("music_cues", [])
    active = "sfx_cues" in data or any(isinstance(row, dict) and set(row) & {
        "bpm", "dynamics", "instrumentation", "ducking"} for row in (music if isinstance(music, list) else []))
    result = {"errors": [], "warnings": [], "metrics": {}, "rules": {}}
    if not active:
        return result
    errors, p = result["errors"], project["id"]
    errors.extend(extra_cue_errors(data))
    if errors:
        return result
    if data.get("project_id") != p:
        errors.append("声音计划不属于当前项目")
    dependencies = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
        S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == artifact["id"])).scalars())
    for cue in data.get("sfx_cues", []):
        if cue.get("silence") is True:
            continue
        for field in ("media", "spec_ref", "source_ref"):
            ref = cue.get(field)
            if not ref:
                continue
            identifier = ref.get("id")
            if not identifier:
                errors.append("PG声音" + field + "须选择本项目已登记固定ID/SHA；文件路径须先通过原登记入口导入")
                continue
            try:
                identifier = checked_id(identifier)
                # Use typed same-project facts. The metadata-only source ref
                # is evidence, while actual audio must pass the old usability
                # and library-license checks for the sfx purpose.
                if field == "media":
                    media, gaps = store._usable(conn, p, identifier, "sfx")
                    if media["sha256"] != ref["sha256"] or media["modality"] != "audio" or gaps:
                        errors.append("SFX素材SHA/模态或原用途检查失效: " + cue["id"])
                    continue
                fixed = conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == p,
                    S.artifact_versions.c.id == identifier)).mappings().first()
                if fixed:
                    if fixed["sha256"] != ref["sha256"] or identifier not in dependencies or not store._artifact_approved(conn, p, identifier):
                        errors.append("声音" + field + "必须明确依赖本项目已批准固定版本: " + cue["id"])
                elif field == "source_ref":
                    source = conn.execute(select(S.source_versions).where(S.source_versions.c.project_id == p,
                        S.source_versions.c.id == identifier)).mappings().first()
                    if not source or source["sha256"] != ref["sha256"]:
                        errors.append("SFX固定来源不存在或摘要漂移: " + cue["id"])
                    elif cue.get("media", {}).get("id"):
                        linked = conn.execute(select(S.media_sources.c.id).where(S.media_sources.c.project_id == p,
                            S.media_sources.c.source_id == identifier,
                            S.media_sources.c.media_id == checked_id(cue["media"]["id"]))).first()
                        if not linked:
                            errors.append("SFX来源并非所选素材的原登记来源: " + cue["id"])
                else:
                    errors.append("SFX固定规格不存在: " + cue["id"])
            except ResourceError:
                errors.append("SFX引用不属于当前项目或已不可用: " + cue["id"])
    return result


def artifact_rule_report(store, conn, project, artifact, *, context_scope=None, cache=None):
    cache = cache if cache is not None else {}
    try:
        raw = artifact.get("document")
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (ValueError, UnicodeError):
        return {"errors": [], "warnings": [], "metrics": {}, "rules": {}}
    if not isinstance(data, dict) or data.get("format") not in {
        "vsc.creative-brief/v1", "vsc.quality-plan/v1", "vsc.screenplay/v1", "vsc.continuity-plan/v1", "vsc.timeline/v1", "vsc.remotion-render-plan/v1", "vsc.sound-cue-sheet/v1"}:
        return {"errors": [], "warnings": [], "metrics": {}, "rules": {}}
    if data.get("format") == "vsc.sound-cue-sheet/v1":
        return _sound_report(store, conn, project, artifact, data)
    p = project["id"]
    if "records" not in cache:
        records = []
        candidates = list(conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id == p,
                S.artifact_versions.c.artifact_type.in_(["vsc.creative_brief", "vsc.quality_plan", "quality-plan"]))).mappings())
        approvals = store._approval_map(conn, p) if candidates else {}
        scope_map = {}
        if candidates:
            for owner, object_id in conn.execute(select(S.artifact_object_scopes.c.artifact_id, S.artifact_object_scopes.c.object_id).where(
                    S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id.in_([row["id"] for row in candidates]))):
                scope_map.setdefault(owner, []).append(object_id)
        for row in candidates:
            if not approvals.get(row["id"]):
                continue
            try:
                body = json.loads(row["document"])
            except (ValueError, UnicodeError):
                continue
            if not isinstance(body, dict):
                continue
            scopes = scope_map.get(row["id"], [])
            records.append({"id": row["id"], "type": row["artifact_type"], "sha256": row["sha256"],
                "status": "approved", "scopes": ["project"] if row["project_wide"] else scopes, "document": body})
        cache["records"] = records
    records = cache["records"]
    if (not project.get("profile_snapshot", {}).get("creative_rules")
            and not any(row["document"].get("creative_rules") for row in records)
            and not data.get("creative_rules") and not data.get("render_plan", {}).get("creative_rules")
            and not (data.get("format") == "vsc.quality-plan/v1" and data.get("risks"))
            and not any("risk_ids" in row or "risks" in row for row in data.get("shots", []) if isinstance(row, dict))):
        return {"errors": [], "warnings": [], "metrics": {}, "rules": {}}
    if "objects" not in cache:
        objects = {row["id"]: dict(row) for row in conn.execute(select(S.creative_objects).where(S.creative_objects.c.project_id == p)).mappings()}
        for table in (S.episodes, S.scenes, S.sequences, S.shots):
            for identifier, parent in conn.execute(select(table.c.id, table.c.parent_id).where(table.c.project_id == p)):
                objects[identifier]["parent"] = parent
        cache["objects"] = objects
    objects = cache["objects"]
    aliases = {row["display_code"]: row["id"] for row in objects.values()}
    aliases.update({identifier: identifier for identifier in objects})
    def ancestry(identifier):
        cursor, seen, result = aliases.get(identifier, identifier), set(), ["project"]
        while cursor in objects and cursor not in seen:
            seen.add(cursor)
            result.append(cursor)
            cursor = objects[cursor].get("parent")
        return result
    def within(identifier, scope):
        return aliases.get(scope, scope) in ancestry(identifier)
    scope_ids = list(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
        S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == artifact["id"])).scalars())
    owner_scopes = ["project"] if artifact["project_wide"] else scope_ids
    scopes = owner_scopes
    if context_scope:
        context_scope = aliases.get(context_scope, context_scope)
        # A consumer can narrow a project/episode artifact, but an episode
        # consumer must retain the more specific fixed sequence/shot scope.
        scopes = [context_scope if within(context_scope, owner) else owner
            for owner in owner_scopes if within(context_scope, owner) or within(owner, context_scope)]
    scopes = sorted(set(scopes))
    dependencies = {str(identifier) for identifier in conn.execute(text("""WITH RECURSIVE dependencies(id) AS (
        SELECT dependency_id FROM artifact_dependencies WHERE project_id=CAST(:p AS uuid) AND artifact_id=CAST(:a AS uuid)
        UNION SELECT d.dependency_id FROM artifact_dependencies d JOIN dependencies r ON r.id=d.artifact_id
              WHERE d.project_id=CAST(:p AS uuid)
        ) SELECT id FROM dependencies"""), {"p": p, "a": artifact["id"]}).scalars()}
    reports, scope_errors = [], []
    declared_targets = data.get("creative_rules", {}).get("duration", {}).get("scope_targets", {}) if (
        isinstance(data.get("creative_rules"), dict) and isinstance(data["creative_rules"].get("duration", {}), dict)) else {}
    if data.get("format") == "vsc.creative-brief/v1" and isinstance(declared_targets, dict):
        for target in declared_targets:
            if aliases.get(target, target) not in objects or not any(within(target, owner) for owner in owner_scopes):
                scope_errors.append("创作目标时长引用的范围不存在或超出登记范围: " + str(target))
    risks = data.get("risks", [])
    if data.get("format") == "vsc.quality-plan/v1" and isinstance(risks, list):
        for risk in risks:
            if not isinstance(risk, dict):
                continue
            target = risk.get("scope")
            if isinstance(target, str) and not any(within(target, owner) for owner in owner_scopes):
                scope_errors.append("quality-plan风险范围超出登记范围: " + str(risk.get("id")))
            for shot in risk.get("shot_ids", []) if isinstance(risk.get("shot_ids", []), list) else []:
                if isinstance(shot, str) and not any(within(shot, owner) for owner in owner_scopes):
                    scope_errors.append("quality-plan风险镜头超出登记范围: " + shot)
    for scope in scopes:
        scoped_records = []
        for record in records:
            matching = [owner for owner in record["scopes"] if within(scope, owner)]
            if matching:
                # One fixed brief can cover multiple scopes. Present it once
                # at its deepest applicable scope, preserving original
                # Profile -> most-specific pinned brief precedence.
                scoped_records.append(dict(record, scope=max(matching, key=lambda owner: len(ancestry(owner)))))
        scoped_data = data
        if data.get("format") == "vsc.screenplay/v1" and scope != "project":
            scoped_data = dict(data, scenes=[scene for scene in data.get("scenes", []) if within(scene.get("id"), scope)])
        elif data.get("format") == "vsc.creative-brief/v1" and isinstance(declared_targets, dict) and declared_targets:
            rules = dict(data["creative_rules"])
            rules["duration"] = dict(rules["duration"], scope_targets={key: value for key, value in declared_targets.items() if within(key, scope)})
            scoped_data = dict(data, creative_rules=rules)
        elif data.get("format") == "vsc.quality-plan/v1" and isinstance(risks, list):
            scoped_risks = []
            for risk in risks:
                if not isinstance(risk, dict) or not isinstance(risk.get("scope", scope), str):
                    scoped_risks.append(risk)
                    continue
                target = risk.get("scope", scope)
                if "scope" not in risk or within(scope, target) and scope != target:
                    item = dict(risk, scope=scope)
                    if isinstance(risk.get("shot_ids"), list):
                        item["shot_ids"] = [shot for shot in risk["shot_ids"] if not isinstance(shot, str) or within(shot, scope)]
                    scoped_risks.append(item)
                elif within(target, scope):
                    scoped_risks.append(risk)
            scoped_data = dict(data, risks=scoped_risks)
        reports.append(context_diagnostics(scoped_data, project.get("profile_snapshot", {}),
            scoped_records, dependencies, scope, objects))
    report = reports[0] if len(reports) == 1 else {
        "errors": [message for item in reports for message in item["errors"]],
        "warnings": [message for item in reports for message in item["warnings"]],
        "metrics": {scope: item["metrics"] for scope, item in zip(scopes, reports)},
        "rules": reports[0]["rules"] if reports and all(item["rules"] == reports[0]["rules"] for item in reports) else {},
        "scope_reports": {scope: item for scope, item in zip(scopes, reports)}}
    if not scopes:
        report["errors"].append("规则检查范围与固定产物登记范围不相交")
    report["errors"].extend(scope_errors)
    if data.get("project_id") is not None and data["project_id"] != p:
        report["errors"].append("创作规则/风险来源正文不属于当前项目")
    declared = data.get("scope", data.get("sequence_id"))
    if declared and declared != "project" and aliases.get(declared, declared) not in objects:
        report["errors"].append("规则检查目标范围不在当前项目中: " + str(declared))
    return report
