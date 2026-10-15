#!/usr/bin/env python3
"""SQLite authority for new serial projects; legacy projects keep vsc.json.

The JSON mirror is for older readers. Only commit_state changes the canonical
project state. Large media stays outside SQLite and is registered by hash.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATABASE = ".vsc-series.sqlite3"
POLICY = "sqlite-series-v1"
SCHEMA = 1
MAX_DOCUMENT = 16 * 1024 * 1024


class SeriesStoreError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def path(project):
    result = Path(project) / DATABASE
    if result.is_symlink():
        raise SeriesStoreError("系列数据库不能是符号链接")
    return result


@contextmanager
def connect(project):
    location = path(project)
    if not location.is_file():
        raise SeriesStoreError("系列数据库不存在；旧项目须显式迁移 Profile")
    connection = sqlite3.connect(location, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA:
        connection.close()
        raise SeriesStoreError(f"系列数据库 schema {version} 不受支持")
    # Frozen or cut-over legacy authorities remain readable by explicit readers.
    # SQLite itself rejects mutations, including callers bypassing state.save.
    from vsc.project.pg_workflow import legacy_write_guard
    from vsc.assets.resource_service import ResourceError
    try:
        legacy_write_guard(project)
    except ResourceError:
        forbidden = {getattr(sqlite3, name) for name in (
            "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX",
            "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW", "SQLITE_DROP_TABLE", "SQLITE_DROP_INDEX",
            "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW", "SQLITE_ALTER_TABLE", "SQLITE_ATTACH", "SQLITE_DETACH")}
        connection.set_authorizer(lambda action, first, second, db, trigger:
            sqlite3.SQLITE_DENY if action in forbidden or (action == sqlite3.SQLITE_PRAGMA and second is not None) else sqlite3.SQLITE_OK)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _create(connection):
    connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS project_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            revision INTEGER NOT NULL, sha256 TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS creative_objects (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent_id TEXT,
            artifact_id TEXT, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS creative_objects_parent ON creative_objects(parent_id, kind);
        CREATE TABLE IF NOT EXISTS artifact_versions (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, stage TEXT NOT NULL,
            scope TEXT NOT NULL, status TEXT NOT NULL, sha256 TEXT NOT NULL,
            path TEXT NOT NULL, document BLOB NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS artifact_scope ON artifact_versions(type, scope, status);
        CREATE TABLE IF NOT EXISTS artifact_dependencies (
            artifact_id TEXT NOT NULL REFERENCES artifact_versions(id),
            dependency_id TEXT NOT NULL REFERENCES artifact_versions(id),
            dependency_sha256 TEXT NOT NULL,
            PRIMARY KEY(artifact_id, dependency_id)
        );
        CREATE TABLE IF NOT EXISTS source_versions (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, rights TEXT NOT NULL,
            path TEXT NOT NULL, sha256 TEXT NOT NULL, document BLOB,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approval_decisions (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
            outcome TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS script_lines (
            artifact_id TEXT NOT NULL REFERENCES artifact_versions(id),
            scene_id TEXT NOT NULL, line_id TEXT NOT NULL, speaker TEXT,
            text TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(artifact_id, line_id)
        );
        CREATE INDEX IF NOT EXISTS script_lines_scene ON script_lines(scene_id, artifact_id);
        CREATE INDEX IF NOT EXISTS script_lines_speaker ON script_lines(speaker, artifact_id);
        CREATE TABLE IF NOT EXISTS media_assets (
            id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, path TEXT NOT NULL,
            modality TEXT NOT NULL, rights TEXT NOT NULL, origin TEXT NOT NULL,
            metadata TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS media_sha ON media_assets(sha256);
        CREATE TABLE IF NOT EXISTS asset_derivations (
            child_id TEXT NOT NULL REFERENCES media_assets(id),
            parent_id TEXT NOT NULL REFERENCES media_assets(id),
            relation TEXT NOT NULL, parameters TEXT NOT NULL,
            PRIMARY KEY(child_id, parent_id, relation)
        );
        CREATE INDEX IF NOT EXISTS asset_derivations_parent ON asset_derivations(parent_id);
        CREATE TABLE IF NOT EXISTS continuity_edges (
            id TEXT PRIMARY KEY, from_shot TEXT NOT NULL, to_shot TEXT NOT NULL,
            from_state_sha256 TEXT NOT NULL, to_state_sha256 TEXT NOT NULL,
            from_signature TEXT NOT NULL, to_signature TEXT NOT NULL,
            strategy TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','superseded')),
            actor TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS continuity_edges_active ON continuity_edges(to_shot) WHERE status='active';
        CREATE TABLE IF NOT EXISTS media_bindings (
            id TEXT PRIMARY KEY, target_id TEXT NOT NULL, role TEXT NOT NULL,
            variant TEXT, media_id TEXT NOT NULL REFERENCES media_assets(id),
            status TEXT NOT NULL CHECK(status IN ('draft','approved','rejected','retired')),
            actor TEXT, reason TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS media_bindings_target ON media_bindings(target_id, role, status);
        CREATE UNIQUE INDEX IF NOT EXISTS media_binding_active ON media_bindings(target_id, role, IFNULL(variant,'')) WHERE status='approved';
        CREATE TABLE IF NOT EXISTS media_binding_decisions (
            id TEXT PRIMARY KEY, binding_id TEXT NOT NULL REFERENCES media_bindings(id),
            outcome TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS providers (
            name TEXT PRIMARY KEY, modalities TEXT NOT NULL, base_url TEXT,
            auth_ref TEXT, enabled INTEGER NOT NULL, rate_limit INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_models (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL REFERENCES providers(name),
            model_key TEXT NOT NULL, modality TEXT NOT NULL, model_version TEXT NOT NULL,
            capabilities TEXT NOT NULL, default_params TEXT NOT NULL,
            cost_rule TEXT NOT NULL, enabled INTEGER NOT NULL,
            UNIQUE(provider,model_key,modality)
        );
        CREATE TABLE IF NOT EXISTS provider_routes (
            modality TEXT NOT NULL, purpose TEXT NOT NULL,
            provider TEXT NOT NULL REFERENCES providers(name),
            model_id TEXT NOT NULL REFERENCES provider_models(id), enabled INTEGER NOT NULL,
            PRIMARY KEY(modality,purpose)
        );
        CREATE TABLE IF NOT EXISTS generation_jobs (
            id TEXT PRIMARY KEY, run_artifact_id TEXT NOT NULL,
            target_id TEXT NOT NULL, purpose TEXT NOT NULL, modality TEXT NOT NULL,
            candidate_no INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            model_version TEXT NOT NULL, context_sha256 TEXT NOT NULL,
            request_sha256 TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL, external_task_id TEXT, request TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0, cost TEXT, latency_ms INTEGER,
            raw_response TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(run_artifact_id, target_id, purpose, candidate_no)
        );
        CREATE INDEX IF NOT EXISTS generation_jobs_target ON generation_jobs(target_id, status);
        CREATE UNIQUE INDEX IF NOT EXISTS generation_external_task ON generation_jobs(provider,external_task_id) WHERE external_task_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS job_events (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES generation_jobs(id),
            status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generated_assets (
            job_id TEXT NOT NULL REFERENCES generation_jobs(id),
            media_id TEXT NOT NULL REFERENCES media_assets(id),
            asset_type TEXT NOT NULL, original_uri TEXT, metadata TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(job_id,media_id)
        );
        PRAGMA user_version=1;
    """)


def _document(project, relative, expected):
    root = Path(project).resolve()
    document = (root / relative).resolve()
    if not document.is_relative_to(root) or not document.is_file() or document.stat().st_size > MAX_DOCUMENT:
        raise SeriesStoreError(f"版本文件缺失、越界或过大：{relative}")
    content = document.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise SeriesStoreError(f"版本文件 SHA 不符：{relative}")
    return content


def _source_document(project, item):
    """Verify every source snapshot; keep only bounded text bytes in SQLite."""
    root = Path(project).resolve()
    source = (root / item["path"]).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise SeriesStoreError(f"来源快照缺失或越界：{item['path']}")
    actual = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            actual.update(block)
    if actual.hexdigest() != item.get("sha256"):
        raise SeriesStoreError(f"来源快照 SHA 不符：{item['path']}")
    if item["kind"] in ("novel", "original", "brief", "document", "handoff") and source.stat().st_size <= MAX_DOCUMENT:
        return source.read_bytes()
    return None


def _index_artifact(connection, project, item):
    existing = connection.execute("SELECT sha256,path,type,stage,scope FROM artifact_versions WHERE id=?", (item["id"],)).fetchone()
    fixed = (item["sha256"], item["path"], item["type"], item["stage"], item.get("scope", "project"))
    if existing and tuple(existing[key] for key in ("sha256", "path", "type", "stage", "scope")) != fixed:
        raise SeriesStoreError("已登记产物版本不能原地修改")
    if existing:
        old_deps = {(row["dependency_id"], row["dependency_sha256"]) for row in connection.execute(
            "SELECT dependency_id,dependency_sha256 FROM artifact_dependencies WHERE artifact_id=?", (item["id"],))}
        new_deps = {(ref, item.get("dependency_versions", {}).get(ref, "")) for ref in item.get("depends_on", [])}
        if old_deps != new_deps:
            raise SeriesStoreError("已登记产物依赖不能原地修改")
    content = None if existing else _document(project, item["path"], item["sha256"])
    if existing:
        connection.execute("UPDATE artifact_versions SET status=?, payload=? WHERE id=?",
                           (item["status"], canonical(item), item["id"]))
    else:
        connection.execute("INSERT INTO artifact_versions VALUES (?,?,?,?,?,?,?,?,?)",
                           (item["id"], item["type"], item["stage"], item.get("scope", "project"),
                            item["status"], item["sha256"], item["path"], content, canonical(item)))
        if item["type"] == "vsc.screenplay":
            try:
                document = json.loads(content)
            except (ValueError, UnicodeError):
                document = {}
            for scene in document.get("scenes", []):
                for line in scene.get("dialogue", []):
                    connection.execute("INSERT INTO script_lines VALUES (?,?,?,?,?,?)",
                                       (item["id"], scene["id"], line["id"],
                                        line.get("speaker"), line.get("text", ""), canonical(line)))
    for dependency in item.get("depends_on", []):
        connection.execute("INSERT OR IGNORE INTO artifact_dependencies VALUES (?,?,?)",
                           (item["id"], dependency, item.get("dependency_versions", {}).get(dependency, "")))


def commit_state(project, state, expected_revision):
    """Commit one complete state revision and its relational indexes atomically."""
    from vsc.project.pg_workflow import legacy_write_guard
    from vsc.assets.resource_service import ResourceError
    try:
        legacy_write_guard(project)
    except ResourceError as error:
        raise SeriesStoreError(str(error)) from error
    location = path(project)
    fresh = not location.exists()
    connection = sqlite3.connect(location, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        if fresh:
            _create(connection)
        elif connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
            raise SeriesStoreError("系列数据库 schema 不受支持")
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT revision FROM project_state WHERE singleton=1").fetchone()
        if current and current[0] != expected_revision:
            raise SeriesStoreError("数据库状态已被其他写入改变")
        if not current and not fresh:
            raise SeriesStoreError("数据库缺项目状态，拒绝推断历史")
        for item in state.get("objects", []):
            old = connection.execute("SELECT kind,parent_id FROM creative_objects WHERE id=?", (item["id"],)).fetchone()
            if old and (old["kind"], old["parent_id"]) != (item["kind"], item.get("parent")):
                raise SeriesStoreError("已登记对象的类型与父级不能原地修改")
            connection.execute("INSERT INTO creative_objects VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                               "artifact_id=excluded.artifact_id,payload=excluded.payload",
                               (item["id"], item["kind"], item.get("parent"), item.get("artifact"), canonical(item)))
        for item in state.get("artifacts", []):
            _index_artifact(connection, project, item)
        for item in state.get("sources", []):
            existing = connection.execute("SELECT path,sha256,kind,rights FROM source_versions WHERE id=?", (item["id"],)).fetchone()
            if existing and tuple(existing[key] for key in ("path", "sha256", "kind", "rights")) != (
                    item["path"], item["sha256"], item["kind"], item.get("rights", "unknown")):
                raise SeriesStoreError("已登记来源版本不能原地修改")
            content = None if existing else _source_document(project, item)
            connection.execute("INSERT INTO source_versions VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                               "payload=excluded.payload",
                               (item["id"], item["kind"], item.get("rights", "unknown"), item["path"],
                                item.get("sha256", ""), content, canonical(item)))
        for item in state.get("decisions", []):
            old = connection.execute("SELECT payload FROM approval_decisions WHERE id=?", (item["id"],)).fetchone()
            if old and old["payload"] != canonical(item):
                raise SeriesStoreError("已登记人工决定不能原地修改")
            connection.execute("INSERT OR IGNORE INTO approval_decisions VALUES (?,?,?,?,?,?)",
                               (item["id"], item["kind"], item["target"], item["outcome"], item["by"], canonical(item)))
        for item in state.get("artifacts", []):
            decision = item.get("decision")
            if decision:
                key = "artifact:" + item["id"]
                payload = {"artifact_id": item["id"], "sha256": item["sha256"],
                           "status": item["status"], "decision": decision}
                connection.execute("INSERT INTO approval_decisions VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                                   "outcome=excluded.outcome,actor=excluded.actor,payload=excluded.payload",
                                   (key, "artifact", item["id"], item["status"], decision["by"], canonical(payload)))
        connection.execute("INSERT INTO project_state VALUES (1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                           "revision=excluded.revision,sha256=excluded.sha256,payload=excluded.payload",
                           (state["revision"], digest(state), canonical(state)))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_state(project):
    with connect(project) as connection:
        row = connection.execute("SELECT payload,sha256 FROM project_state WHERE singleton=1").fetchone()
        if not row:
            raise SeriesStoreError("系列数据库缺项目状态")
        value = json.loads(row["payload"])
        if digest(value) != row["sha256"]:
            raise SeriesStoreError("系列数据库状态摘要不符")
        return value


def artifact_document(project, artifact_id):
    with connect(project) as connection:
        row = connection.execute("SELECT document,sha256 FROM artifact_versions WHERE id=?", (artifact_id,)).fetchone()
        if not row or hashlib.sha256(row["document"]).hexdigest() != row["sha256"]:
            raise SeriesStoreError(f"数据库产物版本不可用：{artifact_id}")
        return row["document"]
