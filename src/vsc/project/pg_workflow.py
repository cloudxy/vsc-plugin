"""Fixed Profile gates over the PostgreSQL resource authority."""
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from vsc.assets.resource_service import ResourceError

POINTER = ".vsc-postgres.json"


def authority_pointer(project):
    path = Path(project) / POINTER
    if path.is_symlink():
        raise ResourceError("数据库权威指针不能是符号链接", "unsafe_authority")
    if path.is_file():
        value = json.loads(path.read_text("utf-8"))
        if value.get("storage_policy") != "postgres-series-v1" or not value.get("project_id"):
            raise ResourceError("数据库权威指针无效", "invalid_authority")
        return value
    return None


def legacy_write_guard(project):
    root = Path(project)
    if (root / POINTER).exists():
        raise ResourceError("项目已采用 PostgreSQL 权威；请使用 scripts/assets/resources.py 或资源面板", "authority_changed", 409)
    migration = root / ".vsc-migration.json"
    if migration.exists():
        value = json.loads(migration.read_text("utf-8"))
        if value.get("status") in {"frozen", "imported", "compared", "cutover"}:
            raise ResourceError("项目为数据库迁移冻结，旧入口不能写入", "migration_frozen", 409)


def create_project(service, name, actor, directory=None, database_env="VSC_DATABASE_URL"):
    from vsc.project.state import profile_for, write_json
    if directory:
        target = Path(directory)
        if any((target / file).exists() for file in ("vsc.json", ".vsc-series.sqlite3", POINTER)):
            raise ResourceError("目标已有项目，必须显式迁移而非覆盖", "project_exists", 409)
    profile = profile_for("vsc.series-pg")
    result = service.create_project({"name": name, "profile": profile["profile_id"], "profile_snapshot": profile,
                                     "storage_policy": "postgres-series-v1"}, actor=actor)
    work = service.create_object(result["id"], {"kind": "work", "display_code": "W001", "title": name, "ordinal": 0},
                                 expected_revision=0, idempotency_key="initial-work", actor=actor)
    result["revision"] = work["revision"]
    result["work_id"] = work["id"]
    if directory:
        write_json(Path(directory) / POINTER, {"project_id": result["id"], "storage_policy": "postgres-series-v1", "database_env": database_env})
    return result


def validate_contract(document, artifact_type, policy="production-v2"):
    """Validate exact immutable bytes via existing canonical VSC validators."""
    if not artifact_type.startswith("vsc."):
        return []
    from vsc.project.artifacts import content_errors
    raw = document if isinstance(document, bytes) else (document if isinstance(document, str) else json.dumps(document, ensure_ascii=False)).encode("utf-8")
    suffix = ".json" if raw.lstrip().startswith((b"{", b"[")) else ".md"
    with tempfile.TemporaryDirectory(prefix="vsc-contract-") as directory:
        path = Path(directory) / ("document" + suffix)
        path.write_bytes(raw)
        return content_errors(path, artifact_type, policy)


def _migrated_legacy_profile(service, project_id, profile, artifacts):
    """Recognize immutable migration evidence, not arbitrary custom Profiles."""
    if profile.get("storage_policy") == "postgres-series-v1" or profile.get("profile_id") == "vsc.series-pg":
        return False
    legacy_rows = [row for row in artifacts if row.get("parser_version") == "legacy-relations/v1"]
    snapshots = [row for row in artifacts if row.get("artifact_type") == "vsc.legacy-snapshot/v1"
                 and row.get("parser_version") == "vsc-migration/v1" and row.get("stage") == "migration"]
    if not legacy_rows or len(snapshots) != 1:
        return False
    fixed = service.get_artifact_version(project_id, snapshots[0]["id"])
    document = fixed.get("document")
    try:
        snapshot = json.loads(document) if isinstance(document, (str, bytes)) else document
        state, source = snapshot["state"], snapshot["source"]
        digest = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        original_shas = {row["sha256"] for row in state.get("artifacts", [])}
        return (snapshot.get("format") == "vsc.legacy-snapshot/v1"
                and source.get("authority") in {"legacy-json", "sqlite-series-v1"}
                and source.get("state_sha256") == digest
                and source.get("legacy_project_id") == state.get("project_id")
                and state.get("profile_snapshot") == profile
                and any(row.get("sha256") in original_shas for row in legacy_rows))
    except (KeyError, TypeError, ValueError):
        return False


def check_gate(service, project_id, stage_id, scope=None):
    project = service.get_project(project_id)
    profile = project["profile_snapshot"]
    stages = profile.get("stages", [])
    stage = next((row for row in stages if row["id"] == stage_id), None)
    if not stage:
        raise ResourceError("项目固定 Profile 没有该阶段", "invalid_stage")
    ids = [s["id"] for s in stages]
    stage_index = ids.index(stage_id)
    required_from = profile.get("scope_required_from")
    scoped_index = ids.index(required_from) if required_from else len(stages)
    if stage_index >= scoped_index and not scope:
        episodes = [node["id"] for node in service.get_project_tree(project_id)["nodes"] if node["kind"] == "episode"]
        if not episodes:
            return {"stage": stage_id, "scope": scope, "passed": False, "gaps": [{"code": "scope_required"}]}
        results = [check_gate(service, project_id, stage_id, episode) for episode in episodes]
        return {"stage": stage_id, "scope": None, "passed": all(row["passed"] for row in results),
                "episodes": results, "gaps": [{"scope": row["scope"], **gap} for row in results for gap in row["gaps"]],
                "warnings": [{"scope": row["scope"], **warning} for row in results for warning in row.get("warnings", [])], "revision": project["revision"]}
    if scope and not any(node["id"] == scope and node["kind"] == "episode" for node in service.get_project_tree(project_id)["nodes"]):
        raise ResourceError("Gate 范围必须是已登记的集", "invalid_scope")
    artifacts = service.list_artifacts(project_id, object_id=scope)["items"]
    legacy_gate = _migrated_legacy_profile(service, project_id, profile, artifacts)
    gaps, pins, warnings = [], [], []
    if stage_index >= 1:
        sources = service.list_sources(project_id)
        if not (sources.get("items", []) if isinstance(sources, dict) else sources):
            gaps.append({"code": "source_required"})
    requirements = [(index, row["id"], kind) for index, row in enumerate(stages[:stage_index + 1]) for kind in row.get("required", [])]
    for owner_index, owner_stage, artifact_type in requirements:
        candidates = [a for a in artifacts if a["artifact_type"] == artifact_type and a.get("stage") == owner_stage
                      and a.get("current") and a.get("approved") and (owner_index >= scoped_index or a.get("project_wide", True))]
        if not candidates or not legacy_gate and len(candidates) != 1:
            gaps.append({"code": "missing_or_conflicting_artifact", "artifact_type": artifact_type, "count": len(candidates)})
            continue
        valid, invalid = [], []
        # Logical streams remain distinct. Deterministic validation retains all
        # valid pins while preserving the legacy Profile's any-valid Gate.
        for candidate in sorted(candidates, key=lambda row: (str(row.get("created_at") or ""), row.get("artifact_key", ""), row["id"])):
            artifact = service.get_artifact_version(project_id, candidate["id"])
            errors = validate_contract(artifact["document"], artifact_type, profile.get("contract_policy", "production-v2"))
            from vsc.adapters.persistence.postgres.creative_rules import artifact_rule_report
            with service.store.engine.connect() as conn:
                report = artifact_rule_report(service.store, conn, project, artifact, context_scope=scope)
            errors.extend(report["errors"])
            warnings.extend({"artifact_id": artifact["id"], "message": message} for message in report["warnings"])
            if errors:
                invalid.append({"code": "invalid_contract", "artifact_id": artifact["id"], "errors": errors})
            else:
                valid.append({"id": artifact["id"], "sha256": artifact["sha256"]})
        if valid:
            pins.extend(valid)
        else:
            gaps.extend(invalid)
    return {"stage": stage_id, "scope": scope, "passed": not gaps, "gaps": gaps, "warnings": warnings,
            "artifacts": pins, "revision": project["revision"]}


def workflow_status(service, project_id, scope=None):
    project = service.get_project(project_id)
    gates = [check_gate(service, project_id, s["id"], scope) for s in project["profile_snapshot"].get("stages", [])]
    return {"project": project, "gates": gates, "next_stage": next((g["stage"] for g in gates if not g["passed"]), None)}


def legacy_status_command(args):
    from vsc.interfaces.cli.pg_state import handle_project_command
    return handle_project_command(args)
