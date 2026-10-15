"""Explicit, evidence-bound legacy → PostgreSQL migration.

No project is migrated on read or on schema installation. The editable manifest
contains typed rows with real schema columns; inventory coverage and original
bytes are reconciled before a single-authority pointer can be published.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
from datetime import datetime
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid

FORMAT = "vsc.resource-migration/v1"
MARKER = ".vsc-migration.json"
POINTER = ".vsc-postgres.json"
CONTROL = ".vsc-migration"
POLICY = "postgres-series-v1"
METADATA = {"schema_version", "runtime_version", "project_id", "title", "owner", "profile_id",
            "profile_version", "profile_snapshot", "profile_sha256", "revision", "created_at", "updated_at", "events"}
TABLE_MAP = {
    "project_state": (), "creative_objects": ("creative_objects",),
    "artifact_versions": ("artifact_versions",), "artifact_dependencies": ("artifact_dependencies",),
    "source_versions": ("source_versions",), "approval_decisions": (),
    "script_lines": ("script_lines",), "media_assets": ("media_items", "media_blobs", "blob_locations"),
    "asset_derivations": ("media_operations", "operation_inputs", "operation_outputs"),
    "continuity_edges": ("continuity_edges",), "media_bindings": ("binding_slots", "binding_candidates"),
    "media_binding_decisions": ("binding_decisions",), "providers": ("providers",),
    "provider_models": ("provider_models",), "provider_routes": ("provider_routes",),
    "generation_jobs": ("generation_jobs",), "job_events": ("job_events",),
    "generated_assets": ("job_outputs", "media_items"),
}
DECISIONS = {"artifact_decisions", "binding_decisions", "rights_decisions", "media_lifecycle_decisions"}
RESERVED = {"project_revisions", "command_receipts"}


class MigrationError(ValueError):
    def __init__(self, message, code="migration_invalid"):
        super().__init__(message)
        self.code, self.status_code = code, 409


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _serial(value):
    if isinstance(value, (bytes, memoryview)):
        return {"base64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serial(item) for item in value]
    return value


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".migration-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(path):
    if Path(path).is_symlink():
        raise MigrationError("迁移控制文件不能是符号链接")
    return json.loads(Path(path).read_text("utf-8"))


@contextlib.contextmanager
def _lock(project):
    project = Path(project).resolve()
    if not project.is_dir():
        raise MigrationError("项目目录不存在")
    with (project / ".vsc.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield project
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _safe(project, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise MigrationError("旧素材路径必须在项目目录内：" + str(relative))
    path = project / relative
    if any(part.is_symlink() for part in [path, *path.parents] if part != project.parent):
        raise MigrationError("迁移不读取符号链接：" + str(relative))
    if not path.resolve().is_relative_to(project):
        raise MigrationError("素材路径越过项目边界")
    return path


def _sqlite(project):
    path = project / ".vsc-series.sqlite3"
    if path.is_symlink():
        raise MigrationError("SQLite 权威不能是符号链接")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _required(category, payload):
    if category == "events" and payload.get("event") == "artifact_decided":
        return ["artifact_decisions"]
    if category == "objects":
        kind = payload.get("kind")
        return ["binding_candidates"] if kind == "take" else ["creative_objects", {"work": "works", "episode": "episodes", "scene": "scenes", "sequence": "sequences", "shot": "shots", "asset": "asset_identities"}.get(kind, "unsupported_object_type")]
    if category == "artifacts":
        return ["artifact_versions"]
    if category == "sources":
        return ["source_versions"]
    if category == "decisions":
        kind = payload.get("kind", "")
        return ["artifact_decisions"] if kind == "artifact" else ["binding_decisions"] if "binding" in kind else ["rights_decisions"] if "rights" in kind else []
    if category.startswith("sqlite:"):
        if category == "sqlite:creative_objects":
            return _required("objects", payload)
        if category == "sqlite:approval_decisions":
            return _required("decisions", payload)
        if category == "sqlite:media_bindings" and payload.get("status") == "approved":
            return ["binding_slots", "binding_candidates", "binding_decisions", "current_bindings"]
        return list(TABLE_MAP.get(category[7:], ()))
    return []


def inventory(project):
    """Read a consistent legacy snapshot. Neither SQLite nor legacy JSON is written."""
    project = Path(project).resolve()
    mirror_path = _safe(project, "vsc.json")
    if not mirror_path.is_file():
        raise MigrationError("旧项目缺少 vsc.json")
    mirror = _read(mirror_path)
    sqlite_rows, sqlite_schema = {}, {}
    if (project / ".vsc-series.sqlite3").exists():
        with contextlib.closing(_sqlite(project)) as conn:
            conn.execute("BEGIN")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                raise MigrationError("旧 SQLite schema 不受支持，不能猜测其关系语义")
            sqlite_schema["user_version"] = version
            row = conn.execute("SELECT revision,sha256,payload FROM project_state WHERE singleton=1").fetchone()
            if not row:
                raise MigrationError("旧 SQLite 缺少权威状态")
            state = json.loads(row["payload"])
            if _digest(state) != row["sha256"] or _digest(mirror) != row["sha256"]:
                raise MigrationError("旧 JSON 镜像与 SQLite 权威不一致，迁移前须修复")
            for table in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                name = table["name"]
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise MigrationError("旧 SQLite 表名不能安全读取")
                sqlite_schema[name] = table["sql"]
                sqlite_rows[name] = [_serial(dict(item)) for item in conn.execute('SELECT * FROM "' + name + '"')]
                sqlite_rows[name].sort(key=_json)
            conn.rollback()
        authority = "sqlite-series-v1"
    else:
        state, authority = mirror, "legacy-json"
        if state.get("profile_snapshot", {}).get("storage_policy") == "sqlite-series-v1":
            raise MigrationError("声明 SQLite 权威但数据库丢失，禁止降级读取镜像")
    if not isinstance(state, dict) or not isinstance(state.get("revision", 0), int) or isinstance(state.get("revision"), bool) or state.get("revision", 0) < 0:
        raise MigrationError("旧状态格式无效")
    facts, issues = [], []
    profile = state.get("profile_snapshot")
    # Legacy state.profile_digest predates the compact canonical JSON used by
    # relational snapshots. Both formats are fixed historical evidence.
    profile_hashes = {_digest(profile), hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()} if isinstance(profile, dict) else set()
    if not isinstance(profile, dict) or state.get("profile_sha256") not in profile_hashes:
        issues.append("源项目缺少可核实的固定 Profile 合同；须先显式恢复历史规则")
    for field in ("objects", "artifacts", "sources", "decisions"):
        if not isinstance(state.get(field, []), list) or any(not isinstance(row, dict) for row in state.get(field, [])):
            raise MigrationError("旧状态实体列表无效：" + field)

    def add(key, category, payload, archival=False):
        facts.append({"key": key, "category": category, "payload": payload,
                      "sha256": _digest(payload), "required_tables": _required(category, payload), "archival": archival})

    for key, value in sorted(state.items()):
        if key == "events" and isinstance(value, list) and value:
            for index, item in enumerate(value):
                add("events:" + str(item.get("id", index)), "events", item, True)
        elif key in ("objects", "artifacts", "sources", "decisions") and isinstance(value, list) and value:
            for index, item in enumerate(value):
                add(key + ":" + str(item.get("id", index)), key, item)
        else:
            add("state:" + key, "metadata" if key in METADATA or not value else "unknown", {key: value}, key in METADATA or not value)
    for table, rows in sqlite_rows.items():
        for item in rows:
            add("sqlite:" + table + ":" + _digest(item), "sqlite:" + table, item, table == "project_state")
    files = []
    ignored = {"vsc.json", ".vsc-series.sqlite3", ".vsc-series.sqlite3-wal", ".vsc-series.sqlite3-shm", ".vsc.lock", MARKER, POINTER}
    for path in sorted(project.rglob("*")):
        relative = path.relative_to(project)
        if relative.parts[0] == CONTROL or relative.as_posix() in ignored:
            continue
        if path.is_symlink():
            issues.append("存在符号链接须先明确转存：" + relative.as_posix())
        elif path.is_file():
            record = {"path": relative.as_posix(), "sha256": _sha(path), "size_bytes": path.stat().st_size}
            files.append(record)
            add("file:" + record["path"], "file", record)
    if len({fact["key"] for fact in facts}) != len(facts):
        raise MigrationError("旧台账存在重复身份，须先修复")
    for item in state.get("artifacts", []):
        if authority == "sqlite-series-v1":
            document = next((row.get("document") for row in sqlite_rows.get("artifact_versions", []) if row.get("id") == item["id"]), None)
            body = base64.b64decode(document["base64"]) if isinstance(document, dict) and "base64" in document else None
        else:
            path = _safe(project, item.get("path", ""))
            body = path.read_bytes() if path.is_file() else None
        if body is None or hashlib.sha256(body).hexdigest() != item.get("sha256"):
            issues.append("产物原始字节或 SHA 无法核实：" + str(item.get("id")))
    facts.sort(key=lambda fact: fact["key"])
    source = {"authority": authority, "legacy_project_id": state.get("project_id"), "revision": state.get("revision", 0),
              "state_sha256": _digest(state), "sqlite_sha256": _digest({"schema": sqlite_schema, "rows": sqlite_rows}) if sqlite_rows else None,
              "files_sha256": _digest(files), "facts_sha256": _digest([{key: fact[key] for key in ("key", "sha256")} for fact in facts])}
    return {"source": source, "state": state, "facts": facts, "files": files, "issues": issues}


def preview(project, manifest=None):
    with _lock(project) as project:
        if (project / POINTER).exists():
            raise MigrationError("项目已切换 PostgreSQL 权威", "already_cut_over")
        snapshot = inventory(project)
    if manifest is None:
        migration_id, target_id, archive_id = (str(uuid.uuid4()) for _ in range(3))
        archive = _json({"format": "vsc.legacy-snapshot/v1", "state": snapshot["state"], "source": snapshot["source"],
                         "inventory": [{key: fact[key] for key in ("key", "category", "sha256")} for fact in snapshot["facts"]]})
        state = snapshot["state"]
        manifest = {"format": FORMAT, "migration_id": migration_id, "target_project_id": target_id,
            "source": snapshot["source"], "inventory": snapshot["facts"], "tables": {
                "projects": [{"id": target_id, "name": state.get("title") or str(state.get("project_id")),
                    "profile": state.get("profile_id", "legacy"), "profile_snapshot": state.get("profile_snapshot", {}),
                    "storage_policy": POLICY, "revision": state.get("revision", 0), "decision_sequence": 0}],
                "artifact_versions": [{"project_id": target_id, "id": archive_id, "artifact_key": "migration.snapshot:" + migration_id,
                    "version": 1, "artifact_type": "vsc.legacy-snapshot/v1", "stage": "migration", "document": {"utf8": archive},
                    "mime_type": "application/json", "sha256": hashlib.sha256(archive.encode()).hexdigest(),
                    "project_wide": True, "parser_version": "vsc-migration/v1"}]},
            "mappings": {}, "decision_evidence": {}, "id_mapping": {}}
        for fact in snapshot["facts"]:
            if fact["archival"]:
                manifest["mappings"][fact["key"]] = {"targets": [{"table": "artifact_versions", "key": {"project_id": target_id, "id": archive_id}}]}
    gaps = _coverage(manifest, snapshot)
    return {"manifest": manifest, "gaps": gaps, "issues": snapshot["issues"], "ready": not gaps,
            "source": snapshot["source"], "counts": {"facts": len(snapshot["facts"]), "files": len(snapshot["files"])}}


def _coverage(manifest, snapshot):
    if manifest.get("format") != FORMAT or manifest.get("source") != snapshot["source"]:
        raise MigrationError("迁移清单与当前旧权威快照不一致", "source_changed")
    for name in ("migration_id", "target_project_id"):
        try:
            uuid.UUID(manifest[name])
        except (KeyError, ValueError, TypeError):
            raise MigrationError(name + " 必须是固定 UUID")
    mappings = manifest.get("mappings", {})
    facts = {fact["key"]: fact for fact in snapshot["facts"]}
    gaps = list(snapshot["issues"])
    for key, fact in facts.items():
        refs = mappings.get(key, {}).get("targets", [])
        tables = {ref.get("table") for ref in refs}
        if not refs or not set(fact["required_tables"]).issubset(tables):
            gaps.append("未完成类型映射：" + key + " → " + ",".join(fact["required_tables"]))
        if not fact["archival"] and any(ref.get("key", {}).get("id") == _archive_id(manifest) for ref in refs):
            gaps.append("业务事实不能仅归入迁移快照：" + key)
    for key in set(mappings) - set(facts):
        gaps.append("映射引用不存在的旧事实：" + key)
    return gaps


def prepare(project, actor, **options):
    """Build a typed legacy manifest without freezing or changing authority."""
    from vsc.project.migration_prepare import prepare as prepare_manifest
    return prepare_manifest(project, actor, **options)


def _mapped(manifest, domain, legacy_id):
    mapping = manifest.get("id_mapping", {})
    return mapping.get(domain + ":" + str(legacy_id), mapping.get(legacy_id))


def _archive_id(manifest):
    rows = manifest.get("tables", {}).get("artifact_versions", [])
    return next((row.get("id") for row in rows if row.get("artifact_type") == "vsc.legacy-snapshot/v1"), None)


def _decode(value, column, project):
    from sqlalchemy import DateTime, LargeBinary
    from sqlalchemy.dialects.postgresql import UUID
    if value is None:
        if not column.nullable:
            raise MigrationError("必填列不能为 null：" + column.name)
        return None
    if isinstance(column.type, UUID):
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError):
            raise MigrationError("目标 UUID 无效：" + column.name)
    if isinstance(column.type, LargeBinary):
        if not isinstance(value, dict) or set(value) not in ({"base64"}, {"utf8"}, {"legacy_file"}):
            raise MigrationError("二进制列须指定 base64、utf8 或 legacy_file：" + column.name)
        if "base64" in value:
            return base64.b64decode(value["base64"], validate=True)
        if "utf8" in value:
            return value["utf8"].encode("utf-8")
        path = _safe(project, value["legacy_file"])
        if path.stat().st_size > 64 * 1024 * 1024:
            raise MigrationError("文档过大，请以受控媒体登记而非数据库文档导入")
        return path.read_bytes()
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def validate_manifest(project, manifest, snapshot=None):
    """Validate actual schema columns and coverage; PostgreSQL checks all FKs on insert."""
    from vsc.adapters.persistence.postgres.schema import metadata
    project = Path(project).resolve()
    snapshot = snapshot or inventory(project)
    gaps = _coverage(manifest, snapshot)
    if gaps:
        raise MigrationError("迁移存在缺口：" + "；".join(gaps), "mapping_incomplete")
    target = manifest["target_project_id"]
    tables, refs = {}, {}
    for name, values in manifest.get("tables", {}).items():
        if name not in metadata.tables or name in RESERVED:
            raise MigrationError("不允许的目标表：" + name)
        table = metadata.tables[name]
        if not isinstance(values, list):
            raise MigrationError("目标表必须提供行列表")
        tables[name] = []
        for raw in values:
            if not isinstance(raw, dict) or set(raw) - set(table.c.keys()):
                raise MigrationError("目标含未知列：" + name)
            row = {key: _decode(value, table.c[key], project) for key, value in raw.items()}
            for column in table.c:
                if not column.nullable and column.default is None and column.server_default is None and column.name not in row:
                    raise MigrationError("目标行缺必填列：" + name + "." + column.name)
            if "project_id" in table.c and row.get("project_id") != target or name == "projects" and row.get("id") != target:
                raise MigrationError("迁移行跨越目标项目", "cross_project")
            for column in table.primary_key.columns:
                if column.name not in row:
                    raise MigrationError("目标行缺主键：" + name + "." + column.name)
            identity = (name, _json({column.name: _serial(row[column.name]) for column in table.primary_key.columns}))
            if identity in refs:
                raise MigrationError("目标行重复：" + name)
            refs[identity] = row
            tables[name].append(row)
    if len(tables.get("projects", [])) != 1:
        raise MigrationError("迁移只允许创建一个全新目标项目")
    project_row = tables["projects"][0]
    if project_row.get("storage_policy") != POLICY or project_row.get("revision") != snapshot["source"]["revision"]:
        raise MigrationError("目标必须采用 PostgreSQL 权威并保留源 revision")
    archive_id = _archive_id(manifest)
    archive = next((row for row in tables.get("artifact_versions", []) if row.get("id") == archive_id), None)
    if not archive:
        raise MigrationError("迁移必须保留不可变的旧状态审计快照")
    try:
        archived = json.loads(archive["document"])
    except (ValueError, TypeError):
        raise MigrationError("迁移审计快照不是有效 JSON")
    if archived.get("state") != snapshot["state"] or archived.get("source") != snapshot["source"]:
        raise MigrationError("迁移审计快照没有完整保留旧权威", "archive_mismatch")
    for key, mapping in manifest["mappings"].items():
        targets = []
        for reference in mapping["targets"]:
            name, identity = reference.get("table"), reference.get("key", {})
            if name not in metadata.tables or set(identity) != set(metadata.tables[name].primary_key.columns.keys()):
                raise MigrationError("映射必须引用目标行的完整主键：" + key)
            row = refs.get((name, _json(identity)))
            if row is None:
                raise MigrationError("映射目标行不存在：" + key)
            targets.append((name, row))
        fact = next(fact for fact in snapshot["facts"] if fact["key"] == key)
        payload = fact["payload"]
        if fact["category"] == "events" and payload.get("event") == "artifact_decided":
            outcome = {"approved": "approve", "rejected": "reject"}.get(payload.get("status"), payload.get("status"))
            if not any(name == "artifact_decisions" and row.get("artifact_id") == _mapped(manifest, "artifacts", payload.get("artifact_id"))
                       and row.get("actor") == payload.get("by") and row.get("outcome") == outcome for name, row in targets):
                raise MigrationError("历史产物批准事件没有保留原身份和结论")
        if fact["category"] in {"objects", "sqlite:creative_objects"}:
            legacy_id = payload.get("id")
            mapped_id = _mapped(manifest, "objects", legacy_id)
            expected_table = "binding_candidates" if payload.get("kind") == "take" else "creative_objects"
            typed = next((row for name, row in targets if name == expected_table and row.get("id") == mapped_id), None)
            if not typed or (expected_table == "creative_objects" and
                             (typed.get("display_code") != legacy_id or typed.get("kind") != payload.get("kind"))):
                raise MigrationError("对象身份或原显示编号未保留：" + key)
            parent_id = payload.get("parent") or payload.get("parent_id")
            if parent_id and expected_table == "creative_objects":
                subtype = next((row for name, row in targets if name in fact["required_tables"] and name != "creative_objects"), None)
                if not subtype or subtype.get("parent_id") != _mapped(manifest, "objects", parent_id):
                    raise MigrationError("对象的原父级关系未保留：" + key)
            artifact_refs = [payload.get("artifact") or payload.get("artifact_id")]
            artifact_refs += [history.get("artifact") for history in payload.get("binding_history", [])]
            for legacy_artifact in filter(None, artifact_refs):
                artifact_id = _mapped(manifest, "artifacts", legacy_artifact)
                if payload.get("kind") == "asset":
                    linked = any(row.get("asset_id") == mapped_id and row.get("artifact_id") == artifact_id
                                 for row in tables.get("asset_spec_versions", []))
                else:
                    linked = any(row.get("object_id") == mapped_id and row.get("artifact_id") == artifact_id
                                 for row in tables.get("artifact_object_scopes", []))
                if not linked:
                    raise MigrationError("对象的原产物版本绑定未保留：" + key)
        unmodeled = fact["category"] == "unknown" or fact["category"] in {"decisions", "sqlite:approval_decisions"} and not fact["required_tables"]
        unmodeled = unmodeled or fact["category"].startswith("sqlite:") and fact["category"][7:] not in TABLE_MAP
        if unmodeled:
            preserved = [row for name, row in targets if name == "artifact_versions" and
                         row.get("document") == _json(payload).encode("utf-8")]
            if mapping.get("classification") != "document" or not preserved:
                raise MigrationError("未知事实需要明确分类并完整保存为独立文档版本：" + key)
        if fact["category"] in ("artifacts", "sources", "file", "sqlite:artifact_versions", "sqlite:source_versions", "sqlite:media_assets"):
            sha = payload.get("sha256")
            candidates = [row for _, row in targets if row.get("sha256") == sha]
            if not candidates:
                raise MigrationError("目标没有保留原 SHA：" + key)
            for row in candidates:
                if "document" in row and hashlib.sha256(row["document"]).hexdigest() != sha:
                    raise MigrationError("文档字节与原 SHA 不符：" + key)
        if fact["category"] in {"artifacts", "sqlite:artifact_versions"}:
            artifact = next((row for name, row in targets if name == "artifact_versions" and
                             row.get("id") == _mapped(manifest, "artifacts", payload["id"])), None)
            if not artifact or artifact.get("artifact_type") != payload.get("type") or artifact.get("stage") != payload.get("stage"):
                raise MigrationError("产物的原身份、类型或阶段未保留：" + key)
            scope = payload.get("scope", "project")
            scoped = [row for row in tables.get("artifact_object_scopes", []) if row.get("artifact_id") == artifact["id"]]
            if scope == "project":
                if not artifact.get("project_wide") or scoped:
                    raise MigrationError("项目级产物的原范围不能改变")
            elif artifact.get("project_wide") or not any(row.get("object_id") == _mapped(manifest, "objects", scope) for row in scoped):
                raise MigrationError("产物的原分集范围未保留")
            if payload.get("asset_versions"):
                if "artifact_asset_spec_refs" not in metadata.tables:
                    raise MigrationError("此项目含消费者固定资产版本，尚未提供类型关联表，禁止只归档后切换", "asset_versions_unmapped")
                for asset_id, fixed in payload["asset_versions"].items():
                    fixed_artifacts = {row["id"] for row in tables.get("artifact_versions", [])
                                       if row["id"] == _mapped(manifest, "artifacts", fixed["id"]) and row["sha256"] == fixed.get("sha256")}
                    spec_ids = {row["id"] for row in tables.get("asset_spec_versions", [])
                                if row.get("asset_id") == _mapped(manifest, "objects", asset_id)
                                and row.get("artifact_id") in fixed_artifacts}
                    if not any(row.get("artifact_id") == artifact["id"] and row.get("asset_id") == _mapped(manifest, "objects", asset_id)
                               and row.get("spec_version_id") in spec_ids for row in tables.get("artifact_asset_spec_refs", [])):
                        raise MigrationError("消费者对资产的原固定版本未映射：" + asset_id, "asset_versions_unmapped")
            for dependency in payload.get("depends_on", []):
                found = any(row.get("artifact_id") == artifact["id"] and
                            row.get("dependency_id") == _mapped(manifest, "artifacts", dependency)
                            for row in tables.get("artifact_dependencies", []))
                if not found:
                    raise MigrationError("产物原依赖未保留：" + key)
            if payload.get("status") == "approved" and not any(
                    row.get("artifact_id") == artifact["id"] and row.get("outcome") == "approve"
                    for row in tables.get("artifact_decisions", [])):
                raise MigrationError("已批准产物缺少原人工决定，不能丢失或自动降为草稿", "approval_evidence_missing")
            try:
                body = json.loads(artifact["document"])
            except (ValueError, TypeError):
                body = {}
            structured = {"vsc.asset_bible": "asset_spec_versions", "vsc.scene_state": "state_versions",
                          "vsc.timeline": "timeline_versions", "vsc.selected_takes": "binding_decisions"}
            unindexed = mapping.get("classification") == "legacy_unindexed"
            if unindexed:
                if payload.get("status") == "approved" or artifact.get("parser_version") != "legacy-unindexed/v1":
                    raise MigrationError("已批准产物不能绕过正式关系索引", "approved_unindexed")
                if any(row.get("artifact_id") == artifact["id"] for row in tables.get("current_artifact_versions", [])):
                    raise MigrationError("未索引的历史草稿不能成为当前执行版本")
                if any(row.get("artifact_id") == artifact["id"] for row in tables.get("timeline_versions", [])):
                    raise MigrationError("未索引的历史草稿不能冻结为时间线")
            if payload.get("type") in structured:
                required_table = structured[payload["type"]]
                if not unindexed and not tables.get(required_table):
                    raise MigrationError("结构化产物尚未建立关系索引：" + required_table)
            if payload.get("type") == "vsc.screenplay" and not unindexed:
                for scene in body.get("scenes", []):
                    for line in scene.get("dialogue", []):
                        if not any(row.get("script_version_id") == artifact["id"] and row.get("line_key") == line.get("id")
                                   and row.get("text") == line.get("text") and row.get("scene_id") == _mapped(manifest, "objects", scene.get("id"))
                                   for row in tables.get("script_lines", [])):
                            raise MigrationError("剧本台词缺少逐行关系索引：" + str(line.get("id")))
        if fact["category"] == "sqlite:generation_jobs":
            job = next((row for name, row in targets if name == "generation_jobs" and
                        row.get("id") == _mapped(manifest, "jobs", payload["id"])), None)
            if not job:
                raise MigrationError("生成任务原身份未保留")
            original_request = json.loads(payload["request"])
            request = job.get("request_payload", {})
            preserved_request = request if request == original_request else request.get("legacy_request")
            if preserved_request != original_request or _digest(original_request) != payload["request_sha256"]:
                raise MigrationError("生成请求的完整原快照或原 SHA 未保留")
            if job.get("request_sha256") != _digest(request):
                raise MigrationError("迁移后的请求快照摘要不符")
            for field in ("external_task_id", "status", "attempt", "model_version", "idempotency_key", "context_sha256", "purpose", "modality", "candidate_no"):
                if job.get(field) != payload.get(field):
                    raise MigrationError("生成任务事实不能重置或重提交：" + field)
            for version in original_request.get("input_versions", []):
                if not any(row.get("job_id") == job["id"] and row.get("artifact_id") == _mapped(manifest, "artifacts", version["id"])
                           and row.get("sha256") == version["sha256"] for row in tables.get("job_input_versions", [])):
                    raise MigrationError("任务缺少固定版本输入关系")
            for media in original_request.get("reference_media", []):
                if not any(row.get("job_id") == job["id"] and row.get("media_id") == _mapped(manifest, "media", media["media_id"])
                           and row.get("blob_sha256") == media["sha256"] for row in tables.get("job_input_media", [])):
                    raise MigrationError("任务缺少固定媒体输入关系")
            logical = request.get("logical_request", request)
            used = set(logical.get("reference_media_ids", []))
            used.update(logical[field] for field in ("first_frame_media_id", "last_frame_media_id", "voice_media_id") if logical.get(field))
            fixed = {row["media_id"] for row in tables.get("job_input_media", []) if row["job_id"] == job["id"]}
            if used - fixed:
                raise MigrationError("任务逻辑媒体ID尚未映射至新固定输入；请显式保留legacy_request并翻译logical_request")
        if fact["category"] == "sqlite:generated_assets":
            if not any(name == "job_outputs" and row.get("job_id") == _mapped(manifest, "jobs", payload["job_id"])
                       and row.get("media_id") == _mapped(manifest, "media", payload["media_id"]) for name, row in targets):
                raise MigrationError("任务与输出媒体的原关联未保留")
    evidence = manifest.get("decision_evidence", {})
    facts = {fact["key"]: fact for fact in snapshot["facts"]}
    for name in DECISIONS:
        for row in tables.get(name, []):
            key = evidence.get(name + ":" + row["id"])
            fact = facts.get(key)
            if not fact:
                raise MigrationError("人工决定缺少旧证据：" + name, "approval_evidence_missing")
            payload = fact["payload"]
            detail = payload.get("payload", {})
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except ValueError:
                    detail = {}
            if not isinstance(detail, dict):
                detail = {}
            category = fact["category"]
            if name == "artifact_decisions":
                allowed = category in {"artifacts", "sqlite:artifact_versions"} or payload.get("kind") == "artifact" or payload.get("event") == "artifact_decided"
                old_artifact = payload.get("artifact_id") or payload.get("target") or payload.get("id")
                if not allowed or row.get("artifact_id") != _mapped(manifest, "artifacts", old_artifact):
                    raise MigrationError("产物批准证据不属于本条固定版本")
            if name == "binding_decisions":
                allowed = category in {"sqlite:media_bindings", "sqlite:media_binding_decisions"} or "binding" in payload.get("kind", "")
                old_binding = payload.get("binding_id") or payload.get("target") or payload.get("id")
                if not allowed or row.get("candidate_id") != _mapped(manifest, "bindings", old_binding):
                    raise MigrationError("素材选择证据不属于本条候选；文档批准不能冒充素材选择")
            if name == "media_lifecycle_decisions" and payload.get("kind") != "media_lifecycle":
                raise MigrationError("用途退役不能冒充全局素材弃用")
            decision = payload.get("decision") or detail.get("decision") or {}
            actor = payload.get("actor") or payload.get("by") or decision.get("by")
            outcome = payload.get("outcome") or payload.get("status") or decision.get("status")
            equivalent = {"approve": "approved", "select": "approved", "reject": "rejected", "retire": "retired"}.get(row["outcome"], row["outcome"])
            if not actor or actor != row.get("actor") or outcome not in (equivalent, row["outcome"]):
                raise MigrationError("人工决定与旧身份或结论不符", "approval_evidence_mismatch")
            original_reason = payload.get("reason") or payload.get("note") or detail.get("reason") or detail.get("note") or decision.get("note")
            if original_reason and row.get("reason") != original_reason:
                raise MigrationError("原人工决定的理由不能被迁移改写")
            if not original_reason and row.get("reason") != "迁移保留原人工决定；原记录无备注":
                raise MigrationError("没有历史备注时只可明确记录其缺失，不能补写创作理由")
            mapped = manifest["mappings"].get(key, {}).get("targets", [])
            if not any(ref.get("table") == name and ref.get("key", {}).get("id") == row["id"] for ref in mapped):
                raise MigrationError("批准证据未绑定到本条决定")
            if name == "rights_decisions" and payload.get("kind") not in ("media_rights", "rights"):
                raise MigrationError("素材选择不能冒充独立权属决定")
    max_decision = max((row["decision_sequence"] for name in DECISIONS for row in tables.get(name, [])), default=0)
    sequences = [row["decision_sequence"] for name in DECISIONS for row in tables.get(name, [])]
    if len(sequences) != len(set(sequences)) or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in sequences):
        raise MigrationError("迁移决定必须使用全项目唯一的正整数顺序")
    if project_row.get("decision_sequence", 0) < max_decision:
        raise MigrationError("项目决定序号不能落后于导入历史")
    # Reviews do not select takes, but a migrated human review still needs the
    # same fixed actor/outcome/input/output evidence as the original decision.
    original_reviews = snapshot["state"].get("production_reviews", [])
    candidates_by_id = {row["id"]: row for row in tables.get("binding_candidates", [])}
    slots_by_id = {row["id"]: row for row in tables.get("binding_slots", [])}
    media_by_id = {row["id"]: row for row in tables.get("media_items", [])}
    blobs_by_id = {row["id"]: row for row in tables.get("media_blobs", [])}
    artifacts_by_id = {row["id"]: row for row in tables.get("artifact_versions", [])}
    review_contexts = {}
    reviewed_outputs = set()
    for row in tables.get("media_reviews", []):
        if row.get("reviewer_type") != "human":
            continue
        proof = row.get("evidence", {}).get("legacy_review")
        proof_index = row.get("evidence", {}).get("legacy_review_index")
        if (row.get("criteria_version") != "legacy-production-review/v1" or not isinstance(proof_index, int)
                or isinstance(proof_index, bool) or not 0 <= proof_index < len(original_reviews)
                or proof != original_reviews[proof_index]):
            raise MigrationError("人工素材审核缺少完整原证据", "review_evidence_missing")
        expected = {"accepted": "pass", "rejected": "fail"}.get(proof.get("outcome"))
        candidate = candidates_by_id.get(row.get("candidate_id"), {})
        slot = slots_by_id.get(candidate.get("slot_id"), {})
        media = media_by_id.get(candidate.get("media_id"), {})
        blob = blobs_by_id.get(media.get("blob_id"), {})
        run = artifacts_by_id.get(_mapped(manifest, "artifacts", proof.get("run_id")), {})
        if (row.get("reviewer") != proof.get("by") or row.get("reason") != proof.get("reason", "")
                or row.get("outcome") != expected or row.get("context_sha256") != proof.get("run_sha256")
                or candidate.get("spec_version_id") != _mapped(manifest, "artifacts", proof.get("run_id"))
                or slot.get("role") != "legacy_review" or slot.get("slot_key") != str(proof.get("run_id")) + ":" + str(proof.get("job_id"))
                or run.get("sha256") != proof.get("run_sha256")
                or proof.get("outputs_sha256", {}).get(media.get("name")) != blob.get("sha256")):
            raise MigrationError("人工素材审核与原操作人、结论或固定输出不符", "review_evidence_mismatch")
        context_key = proof.get("run_id"), proof.get("job_id")
        if context_key not in review_contexts:
            try:
                run_document = json.loads(run["document"])
                batch_ref = run_document["batch"]
                inventory_files = {item["path"]: item for item in snapshot["files"]}
                batch_path = batch_ref["path"]
                if inventory_files.get(batch_path, {}).get("sha256") != batch_ref["sha256"]:
                    batch_path = next(item["path"] for item in snapshot["files"] if item["sha256"] == batch_ref["sha256"])
                batch = _read(_safe(project, batch_path))
                old_job = next(item for item in batch["jobs"] if item["id"] == proof["job_id"])
                journal_path = ".vsc-production/" + str(batch["id"]) + ".json"
                journal = _read(_safe(project, journal_path)) if journal_path in inventory_files else {}
                entry = journal.get("jobs", {}).get(proof["job_id"])
                target_code = old_job.get("args", {}).get("shot")
                review_contexts[context_key] = entry, target_code
            except (KeyError, StopIteration, ValueError):
                raise MigrationError("人工素材审核的原运行批次或任务证据缺失", "review_evidence_missing") from None
        entry, target_code = review_contexts[context_key]
        if row.get("evidence", {}).get("journal") != entry:
            raise MigrationError("人工素材审核的固定输入输出台账被改写", "review_evidence_mismatch")
        if target_code and slot.get("target_object_id") != _mapped(manifest, "objects", target_code):
            raise MigrationError("人工素材审核的原镜头归属被改写", "review_evidence_mismatch")
        if row.get("created_at") and proof.get("at"):
            original_time = datetime.fromisoformat(proof["at"].replace("Z", "+00:00"))
            if original_time.tzinfo is None and row["created_at"].tzinfo is not None:
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
                try:
                    original_time = original_time.replace(tzinfo=ZoneInfo(manifest["preparation"]["source_timezone"]))
                except (KeyError, ZoneInfoNotFoundError, ValueError):
                    raise MigrationError("原无时区时间需要明确源时间约定", "review_evidence_mismatch") from None
            if row["created_at"] != original_time:
                raise MigrationError("原人工审核时间不能改变", "review_evidence_mismatch")
        reviewed_key = proof_index, media.get("name")
        if reviewed_key in reviewed_outputs:
            raise MigrationError("原人工审核被重复导入", "review_evidence_mismatch")
        reviewed_outputs.add(reviewed_key)
    expected_reviews = {(index, path) for index, proof in enumerate(original_reviews) for path in proof.get("outputs_sha256", {})}
    if reviewed_outputs != expected_reviews:
        raise MigrationError("原人工素材审核缺少逐输出关系索引", "review_evidence_missing")
    # All local blob locations must be the original, hashed bytes under a named root.
    blobs = {row["id"]: row for row in tables.get("media_blobs", [])}
    storage_root = Path(manifest.get("media_root", project.parent)).resolve()
    for location in tables.get("blob_locations", []):
        if location.get("storage") != "local" or not location.get("available", True):
            raise MigrationError("迁移只接受已验证的本地受控副本；远程转存需先完成校验")
        path = _safe(storage_root, location["object_key"])
        blob = blobs.get(location["blob_id"])
        if not blob or not path.is_file() or _sha(path) != blob["sha256"] or path.stat().st_size != blob["size_bytes"]:
            raise MigrationError("媒体副本与导入原摘要不符")
    # Fixed migration provenance is a versioned document, never mutable EAV data.
    # It is generated outside the editable row list, avoiding a self-hash cycle.
    manifest_id = str(uuid.uuid5(uuid.UUID(manifest["migration_id"]), "manifest"))
    if any(row.get("id") == manifest_id for row in tables.get("artifact_versions", [])):
        raise MigrationError("清单占用了迁移审计文档的保留身份")
    document = _json(manifest).encode("utf-8")
    tables.setdefault("artifact_versions", []).append({"project_id": target, "id": manifest_id,
        "artifact_key": "migration.manifest:" + manifest["migration_id"], "version": 1,
        "artifact_type": "vsc.migration-manifest/v1", "stage": "migration", "document": document,
        "sha256": hashlib.sha256(document).hexdigest(), "mime_type": "application/json",
        "project_wide": True, "parser_version": "vsc-migration/v1"})
    return tables


def _manifest(path):
    value = _read(path)
    return value, _digest(value)


def status(project):
    project = Path(project)
    return {"migration": _read(project / MARKER) if (project / MARKER).exists() else None,
            "authority": _read(project / POINTER) if (project / POINTER).exists() else None}


def backup(project, manifest_path, actor):
    with _lock(project) as project:
        manifest, manifest_sha = _manifest(manifest_path)
        snapshot = inventory(project)
        _coverage(manifest, snapshot)
        existing = status(project)["migration"]
        if existing and existing.get("status") in ("frozen", "imported", "compared", "cut_over"):
            raise MigrationError("已冻结迁移不能覆盖备份")
        destination = project / CONTROL / "backups" / manifest["migration_id"]
        if destination.exists():
            raise MigrationError("备份已存在，拒绝覆盖")
        destination.mkdir(parents=True)
        copied = []
        for item in [{"path": "vsc.json", "sha256": _sha(project / "vsc.json")}, *snapshot["files"]]:
            target = destination / "files" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_safe(project, item["path"]), target)
            if _sha(target) != item["sha256"]:
                raise MigrationError("备份期间文件变化")
            copied.append({"path": str(target.relative_to(destination)), "sha256": item["sha256"]})
        if snapshot["source"]["authority"] == "sqlite-series-v1":
            with contextlib.closing(_sqlite(project)) as source, sqlite3.connect(destination / ".vsc-series.sqlite3") as target:
                source.backup(target)
            copied.append({"path": ".vsc-series.sqlite3", "sha256": _sha(destination / ".vsc-series.sqlite3")})
        if inventory(project)["source"] != snapshot["source"]:
            raise MigrationError("备份期间旧权威变化", "source_changed")
        record = {"status": "backed_up", "migration_id": manifest["migration_id"], "target_project_id": manifest["target_project_id"],
                  "source": snapshot["source"], "manifest_sha256": manifest_sha, "backup": str(destination.relative_to(project)),
                  "backup_files": copied, "actor": actor}
        _write(destination / "manifest.json", manifest)
        _write(destination / "backup.json", record)
        _write(project / MARKER, record)
        return record


def _frozen(project, manifest, digest, phases):
    record = status(project)["migration"]
    if not record or record.get("status") not in phases or record.get("manifest_sha256") != digest:
        raise MigrationError("迁移阶段或冻结清单不匹配")
    if inventory(project)["source"] != record["source"] or manifest["source"] != record["source"]:
        raise MigrationError("冻结后旧权威仍发生变化，禁止导入或切换", "source_changed")
    location = _safe(project, record["backup"])
    for item in record["backup_files"]:
        path = _safe(location, item["path"])
        if not path.is_file() or _sha(path) != item["sha256"]:
            raise MigrationError("备份缺失或损坏", "backup_changed")
    if _digest(_read(location / "manifest.json")) != digest:
        raise MigrationError("备份中的迁移清单变化")
    return record


def freeze(project, manifest_path, actor):
    with _lock(project) as project:
        manifest, digest = _manifest(manifest_path)
        record = _frozen(project, manifest, digest, {"backed_up"})
        validate_manifest(project, manifest)
        record.update(status="frozen", frozen_by=actor)
        _write(project / MARKER, record)
        return record


def _where(table, row):
    from sqlalchemy import and_
    return and_(*(column == row[column.name] for column in table.primary_key.columns))


def _insert_rows(conn, tables):
    from sqlalchemy import insert, select, update
    from vsc.adapters.persistence.postgres.schema import metadata
    # Foreign-key order is determined by the schema; deferred mask references are
    # allowed by that exact schema. No arbitrary SQL is accepted in the manifest.
    finalized = []
    for table in metadata.sorted_tables:
        for row in tables.get(table.name, []):
            existing = conn.execute(select(table).where(_where(table, row))).mappings().first()
            if existing:
                if "project_id" in table.c or table.name == "projects":
                    raise MigrationError("目标项目或行已存在，拒绝覆盖", "target_exists")
                if any(_serial(existing[key]) != _serial(value) for key, value in row.items()):
                    raise MigrationError("共享供应商或Blob身份冲突", "shared_conflict")
            else:
                inserted = row
                if table.name == "media_operations" and row.get("status") in {"succeeded", "failed"}:
                    # The ordinary operation guards apply to migration too:
                    # insert its fixed input/output graph before finalizing it.
                    inserted = dict(row, status="created")
                    finalized.append(row)
                conn.execute(insert(table).values(**inserted))
    operation_table = metadata.tables["media_operations"]
    for row in finalized:
        conn.execute(update(operation_table).where(_where(operation_table, row)).values(status=row["status"]))


def import_manifest(project, manifest_path, store, actor):
    from sqlalchemy import insert, select
    from vsc.adapters.persistence.postgres import schema as S
    with _lock(project) as project:
        manifest, digest = _manifest(manifest_path)
        record = _frozen(project, manifest, digest, {"frozen", "imported"})
        tables = validate_manifest(project, manifest)
        with store.engine.begin() as conn:
            existing = conn.execute(select(S.projects).where(S.projects.c.id == manifest["target_project_id"]).with_for_update()).mappings().first()
            if existing:
                event = conn.execute(select(S.project_revisions).where(S.project_revisions.c.project_id == manifest["target_project_id"],
                    S.project_revisions.c.action == "migration_import", S.project_revisions.c.command_key == "migration:" + digest)).first()
                if not event:
                    raise MigrationError("目标项目已存在，不能替换", "target_exists")
                _compare_rows(conn, tables)
            else:
                _insert_rows(conn, tables)
                conn.execute(insert(S.project_revisions).values(project_id=manifest["target_project_id"],
                    revision=manifest["source"]["revision"], actor=actor, action="migration_import", command_key="migration:" + digest))
        record.update(status="imported", imported_by=actor)
        _write(project / MARKER, record)
        return record


def _compare_rows(conn, tables):
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres.schema import metadata
    counts = {}
    for name, rows in tables.items():
        table = metadata.tables[name]
        for row in rows:
            existing = conn.execute(select(table).where(_where(table, row))).mappings().first()
            if not existing or any(not _equal(existing[key], value) for key, value in row.items()):
                raise MigrationError("PostgreSQL 对账失败：" + name, "reconciliation_failed")
        counts[name] = len(rows)
    # Extra project-owned rows would be unreviewed facts, and prevent activation.
    project_id = tables["projects"][0]["id"]
    for table in metadata.tables.values():
        if "project_id" in table.c and table.name not in RESERVED:
            actual = conn.execute(select(table).where(table.c.project_id == project_id)).all()
            if len(actual) != len(tables.get(table.name, [])):
                raise MigrationError("PostgreSQL 含未对账的额外行：" + table.name, "reconciliation_failed")
    return counts


def _equal(actual, expected):
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        return actual == expected
    if isinstance(actual, Decimal):
        try:
            return actual == Decimal(str(expected))
        except Exception:
            return False
    return _serial(actual) == _serial(expected)


def compare(project, manifest_path, store, actor):
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres import schema as S
    with _lock(project) as project:
        manifest, digest = _manifest(manifest_path)
        record = _frozen(project, manifest, digest, {"imported", "compared"})
        tables = validate_manifest(project, manifest)
        with store.engine.begin() as conn:
            conn.execute(select(S.projects).where(S.projects.c.id == manifest["target_project_id"]).with_for_update()).first()
            counts = _compare_rows(conn, tables)
        record.update(status="compared", compared_by=actor, compared_counts=counts)
        _write(project / MARKER, record)
        return record


def cutover(project, manifest_path, store, database_env, actor):
    from sqlalchemy import insert, select, update
    from vsc.adapters.persistence.postgres import schema as S
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database_env):
        raise MigrationError("database_env 必须是环境变量名，不能保存连接字符串")
    with _lock(project) as project:
        manifest, digest = _manifest(manifest_path)
        record = _frozen(project, manifest, digest, {"compared", "cut_over"})
        target = manifest["target_project_id"]
        pointer = {"project_id": target, "database_env": database_env, "storage_policy": POLICY,
                   "migration_id": manifest["migration_id"], "manifest_sha256": digest}
        existing = status(project)["authority"]
        if existing and existing != pointer:
            raise MigrationError("已有不同 PostgreSQL 权威指针，拒绝覆盖")
        tables = validate_manifest(project, manifest)
        with store.engine.begin() as conn:
            row = conn.execute(select(S.projects).where(S.projects.c.id == target).with_for_update()).mappings().first()
            if not row:
                raise MigrationError("PostgreSQL 目标不存在")
            activated = conn.execute(select(S.project_revisions).where(S.project_revisions.c.project_id == target,
                S.project_revisions.c.action == "migration_activate", S.project_revisions.c.command_key == "migration:" + digest)).first()
            if not activated:
                _compare_rows(conn, tables)
                # Publish only a fully reconciled target. Until the activation
                # transaction commits, its repository rejects every write.
                _write(project / POINTER, pointer)
                revision = row["revision"] + 1
                conn.execute(update(S.projects).where(S.projects.c.id == target).values(revision=revision))
                conn.execute(insert(S.project_revisions).values(project_id=target, revision=revision,
                    actor=actor, action="migration_activate", command_key="migration:" + digest))
            elif existing != pointer:
                raise MigrationError("已激活目标缺少本地权威指针，须人工恢复已备份指针")
        record.update(status="cut_over", activated_by=actor)
        _write(project / MARKER, record)
        return {"pointer": pointer, "status": "cut_over"}


def migrate(project, action, manifest_path=None, store=None, database_env="VSC_DATABASE_URL", actor=None, **prepare_options):
    project = Path(project).resolve()
    if manifest_path:
        location = Path(manifest_path).resolve()
        if location.is_relative_to(project) and location.relative_to(project).parts[0] != CONTROL:
            raise MigrationError("迁移清单请存于项目 .vsc-migration/ 下或项目目录外，避免清单的自身摘要循环")
    if action == "status":
        return status(project)
    if action == "preview":
        return preview(project, _read(manifest_path) if manifest_path and Path(manifest_path).is_file() else None)
    if action == "prepare":
        return prepare(project, actor, **prepare_options)
    if not actor or not actor.strip():
        raise MigrationError("迁移写入需要实际操作人")
    if not manifest_path:
        raise MigrationError("需要冻结的 --manifest 清单")
    if action in ("backup", "freeze"):
        try:
            return {"backup": backup, "freeze": freeze}[action](project, manifest_path, actor)
        except ImportError:
            raise MigrationError("freeze 需要 postgres 可选依赖；运行 uv sync --locked --extra postgres") from None
    if store is None:
        raise MigrationError("导入、对账和切换需要 PostgreSQL repository")
    from sqlalchemy.exc import SQLAlchemyError
    try:
        if action == "import":
            return import_manifest(project, manifest_path, store, actor)
        if action == "compare":
            return compare(project, manifest_path, store, actor)
        if action == "cutover":
            return cutover(project, manifest_path, store, database_env, actor)
    except SQLAlchemyError:
        # Do not echo connection secrets, full SQL values or private scripts.
        raise MigrationError("PostgreSQL 迁移事务失败；请检查连接和数据库约束。权威指针保持当前已知状态，禁止恢复旧写", "migration_transaction_failed") from None
    raise MigrationError("未知迁移阶段")


def migration_parser(subparsers):
    parser = subparsers.add_parser("migrate", help="显式旧权威迁移；缺口未补全不切换")
    parser.add_argument("project")
    parser.add_argument("action", choices=("preview", "prepare", "backup", "freeze", "import", "compare", "cutover", "status"))
    parser.add_argument("--manifest")
    parser.add_argument("--out", help="preview/prepare 清单输出路径；拒绝覆盖")
    parser.add_argument("--by", dest="actor")
    parser.add_argument("--work-code", help="显式单部技术容器编号；不从目录推断结构")
    parser.add_argument("--structure", help="显式父级/资产类型映射 JSON 文件")
    parser.add_argument("--media-root", default=argparse.SUPPRESS, help="已转存的受控媒体根目录")
    parser.add_argument("--media-prefix", help="受控副本对象键前缀，指定media-root时默认blobs")
    parser.add_argument("--archive-media", action="store_true", help="prepare 流式转存并校验所有原字节；保留源文件")
    parser.add_argument("--source-timezone", default="Asia/Shanghai", help="旧无时区时间的明确解释约定；原字符串保留审计")
    parser.add_argument("--database-env", default=argparse.SUPPRESS)
    return parser


def run_migration_args(args, store=None):
    options = {}
    if args.action == "prepare":
        media_root = getattr(args, "media_root", None)
        options = {"work_code": getattr(args, "work_code", None), "structure": _read(args.structure) if getattr(args, "structure", None) else None,
                   "media_root": media_root, "media_prefix": getattr(args, "media_prefix", None) or ("blobs" if media_root else None),
                   "archive_media": getattr(args, "archive_media", False), "source_timezone": getattr(args, "source_timezone", "Asia/Shanghai")}
    result = migrate(args.project, args.action, args.manifest, store, getattr(args, "database_env", "VSC_DATABASE_URL"), args.actor, **options)
    if args.action in ("preview", "prepare") and args.out:
        path = Path(args.out)
        project = Path(args.project).resolve()
        if path.resolve().is_relative_to(project) and path.resolve().relative_to(project).parts[0] != CONTROL:
            raise MigrationError("--out 请写入项目 .vsc-migration/ 下或项目目录外")
        if path.exists():
            raise MigrationError("迁移清单输出已存在")
        _write(path, result["manifest"])
    return result
