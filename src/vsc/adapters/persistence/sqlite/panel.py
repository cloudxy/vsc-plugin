"""SQLite panel reader uses URI read-only connections and canonical DB bytes."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager

from vsc.adapters.persistence.legacy_json.panel import CatalogError, LegacyPanelReader, modality, safe_path


class SQLitePanelReader(LegacyPanelReader):
    storage_policy = "sqlite-series-v1"

    @contextmanager
    def connection(self):
        location = safe_path(self.root, ".vsc-series.sqlite3")
        if not location.is_file():
            raise CatalogError("声明的 SQLite 权威不存在，不能回退读取 JSON", 409, "authority_unavailable")
        connection = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise CatalogError("SQLite schema 不受支持", 409, "schema_version")
            yield connection
        finally:
            connection.close()

    def state(self):
        with self.connection() as connection:
            row = connection.execute("SELECT payload,sha256 FROM project_state WHERE singleton=1").fetchone()
        if row is None:
            raise CatalogError("SQLite 权威缺少项目状态", 409, "authority_unavailable")
        value = json.loads(row["payload"])
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != row["sha256"]:
            raise CatalogError("SQLite 项目状态 SHA 不符", 409, "hash_mismatch")
        return value

    def artifacts(self, object_id=None):
        result = super().artifacts(object_id)
        with self.connection() as connection:
            records = {row["id"]: row for row in connection.execute("SELECT id,document,sha256 FROM artifact_versions")}
        for row in result["items"]:
            source = records.get(row["id"])
            if source is None:
                row.update(availability="missing", integrity="missing")
            else:
                row.update(availability="available", size_bytes=len(source["document"]),
                           integrity="verified" if hashlib.sha256(source["document"]).hexdigest() == source["sha256"] else "mismatch")
        return result

    def artifact(self, artifact_id):
        with self.connection() as connection:
            source = connection.execute("SELECT document,sha256 FROM artifact_versions WHERE id=?", (artifact_id,)).fetchone()
        if source is None:
            raise CatalogError("产物版本不存在", 404, "not_found")
        result = next(row for row in self.artifacts()["items"] if row["id"] == artifact_id)
        result["content"] = bytes(source["document"]).decode("utf-8", errors="replace")
        result["revision"] = self.project()["revision"]
        return result

    def registered_media(self):
        with self.connection() as connection:
            media = [dict(row) for row in connection.execute("SELECT * FROM media_assets ORDER BY id")]
            bindings = [dict(row) for row in connection.execute("SELECT * FROM media_bindings ORDER BY created_at,id")]
            decisions = [dict(row) for row in connection.execute("SELECT * FROM media_binding_decisions ORDER BY created_at,id")]
        for row in media:
            row["relative_path"] = row.pop("path")
            row["name"] = row["id"]
            row["mime_type"] = modality(row["relative_path"])[1]
            row["registered"] = True
            row["metadata"] = json.loads(row["metadata"])
            row["bindings"] = [binding for binding in bindings if binding["media_id"] == row["id"]]
            binding_ids = {binding["id"] for binding in row["bindings"]}
            row["decisions"] = [decision for decision in decisions if decision["binding_id"] in binding_ids]
            row["reviews"] = []
            row.update(self._file_status(row["relative_path"], row["sha256"], verify=False))
        return media

    def lineage(self, media_id):
        self.media(media_id)
        with self.connection() as connection:
            incoming = [dict(row) for row in connection.execute("SELECT * FROM asset_derivations WHERE child_id=?", (media_id,))]
            outgoing = [dict(row) for row in connection.execute("SELECT * FROM asset_derivations WHERE parent_id=?", (media_id,))]
            jobs = [dict(row) for row in connection.execute("SELECT job_id,asset_type,metadata,created_at FROM generated_assets WHERE media_id=?", (media_id,))]
        for row in incoming + outgoing:
            row["parameters"] = json.loads(row["parameters"])
        return {"inputs": incoming, "outputs": outgoing, "jobs": jobs, "sources": [], "truncated": False}

    def usage(self, media_id):
        result = super().usage(media_id)
        result["operations"] = self.lineage(media_id)["outputs"]
        result["gaps"] = ["旧 SQLite 请求正文未具备结构化任务输入索引，任务反查不保证完整。"]
        return result
