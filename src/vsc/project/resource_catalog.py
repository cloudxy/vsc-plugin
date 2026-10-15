"""One read facade for local legacy projects and the PostgreSQL authority."""
import json
from pathlib import Path

from vsc.adapters.persistence.legacy_json.panel import CatalogError, LegacyPanelReader, safe_path
from vsc.adapters.persistence.sqlite.panel import SQLitePanelReader


class ResourceCatalog:
    def __init__(self, projects_root, service=None, media_root=None):
        self.projects_root = Path(projects_root).resolve()
        self.service = service
        self.media_root = Path(media_root).resolve() if media_root else None

    def _local(self):
        readers, blocked = {}, {}
        if not self.projects_root.is_dir():
            return readers, blocked
        for directory in sorted(self.projects_root.iterdir()):
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                marker = safe_path(directory, ".vsc-postgres.json")
                if marker.is_file():
                    pointer = json.loads(marker.read_text("utf-8"))
                    if pointer.get("storage_policy") != "postgres-series-v1" or not isinstance(pointer.get("project_id"), str):
                        raise CatalogError("PostgreSQL 权威指针不合法", 409, "authority_mismatch")
                    blocked[pointer["project_id"]] = {"project_id": pointer["project_id"], "title": directory.name,
                        "profile_snapshot": {"storage_policy": "postgres-series-v1"}}
                    continue
                source = safe_path(directory, "vsc.json")
                if not source.is_file():
                    continue
                value = json.loads(source.read_text("utf-8"))
                project_id = value["project_id"]
                policy = value.get("profile_snapshot", {}).get("storage_policy", "legacy-json")
                if policy == "postgres-series-v1":
                    blocked[project_id] = value
                    continue
                reader = SQLitePanelReader(directory) if policy == "sqlite-series-v1" or (directory / ".vsc-series.sqlite3").exists() else LegacyPanelReader(directory)
                # Validate canonical authority before accepting an ID from a mirror.
                readers[reader.project()["id"]] = reader
            except (OSError, ValueError, KeyError) as error:
                blocked[directory.name] = {"project_id": directory.name, "title": directory.name,
                                           "error": getattr(error, "code", "invalid_project")}
        return readers, blocked

    def list_projects(self):
        readers, blocked = self._local()
        result = [reader.project() for reader in readers.values()]
        if self.service:
            value = self.service.list_projects()
            result.extend(value.get("items", []) if isinstance(value, dict) else value)
        known = {row["id"] for row in result}
        for project_id, value in blocked.items():
            if project_id not in known:
                result.append({"id": project_id, "name": value.get("title", project_id), "revision": value.get("revision", 0),
                               "storage_policy": value.get("profile_snapshot", {}).get("storage_policy", "unavailable"),
                               "read_only": True, "unavailable": True,
                               "error": value.get("error", "authority_unavailable")})
        # IDs cannot silently select a different project's authority.
        if len({row["id"] for row in result}) != len(result):
            raise CatalogError("项目 ID 在多个权威中重复，请明确迁移状态", 409, "authority_conflict")
        return {"items": result, "total": len(result)}

    def _reader(self, project_id):
        readers, blocked = self._local()
        if project_id in readers:
            return readers[project_id]
        if project_id in blocked and blocked[project_id].get("error"):
            raise CatalogError("项目权威不可用", 409, blocked[project_id]["error"])
        if self.service:
            return None
        if project_id in blocked:
            raise CatalogError("PostgreSQL 权威未配置，禁止回退读取镜像", 409, "authority_unavailable")
        raise CatalogError("项目不存在", 404, "not_found")

    def project_tree(self, project_id):
        reader = self._reader(project_id)
        return reader.tree() if reader else self.service.get_project_tree(project_id)

    def artifacts(self, project_id, object_id=None):
        reader = self._reader(project_id)
        return reader.artifacts(object_id) if reader else self.service.list_artifacts(project_id, object_id=object_id)

    def artifact(self, project_id, artifact_id):
        reader = self._reader(project_id)
        return reader.artifact(artifact_id) if reader else self.service.get_artifact_version(project_id, artifact_id)

    def sources(self, project_id):
        reader = self._reader(project_id)
        if reader:
            return {"items": [{key: value for key, value in row.items() if key not in {"path", "source_path", "snapshot"}}
                              for row in reader.state().get("sources", [])], "read_only": True}
        return self._public_relations(self.service.list_sources(project_id))

    def source(self, project_id, source_id):
        if self._reader(project_id):
            raise CatalogError("此来源正文接口用于 PostgreSQL 固定来源；旧项目保留原来源读取流程", 422, "legacy_read_only")
        return self._public_relations(self.service.get_source_version(project_id, source_id))

    def resources(self, project_id, **filters):
        reader = self._reader(project_id)
        if reader:
            return reader.resources(**filters)
        result = self.service.list_resources(project_id, **filters)
        result["items"] = [self._media_status(row) for row in result["items"]]
        return result

    def media(self, project_id, media_id):
        reader = self._reader(project_id)
        return reader.media(media_id) if reader else self._media_status(self.service.get_media(project_id, media_id), verify=True)

    def _media_status(self, row, verify=False):
        from vsc.adapters.persistence.legacy_json.panel import file_hash
        row = dict(row, registered=True, availability="unavailable", integrity="unverified")
        if not self.media_root:
            return row
        for location in row.get("locations", []):
            if location.get("storage") != "local" or not location.get("available", True):
                continue
            try:
                path = safe_path(self.media_root, location["object_key"])
            except CatalogError:
                row.update(availability="blocked", integrity="blocked")
                continue
            if not path.is_file():
                row.update(availability="missing", integrity="missing")
                continue
            row.update(availability="available", integrity=("verified" if file_hash(path) == row["sha256"] else "mismatch") if verify else "unverified")
            break
        return row

    def lineage(self, project_id, media_id):
        reader = self._reader(project_id)
        return reader.lineage(media_id) if reader else self.service.get_media_lineage(project_id, media_id)

    def usage(self, project_id, media_id):
        reader = self._reader(project_id)
        value = reader.usage(media_id) if reader else self.service.get_media_usage(project_id, media_id)
        return self._public_relations(value)

    @classmethod
    def _public_relations(cls, value):
        if isinstance(value, dict):
            # Remote temporary URLs remain in the task audit authority; the panel
            # exposes controlled media IDs and permanent storage locations.
            result = {key: cls._public_relations(item) for key, item in value.items()
                      if key not in {"original_uri", "raw_response", "auth_ref"}}
            if value.get("original_uri"):
                result["original_uri_archived"] = True
            return result
        if isinstance(value, list):
            return [cls._public_relations(item) for item in value]
        return value

    def content_path(self, project_id, media_id):
        reader = self._reader(project_id)
        if reader:
            return reader.content_path(media_id)
        row = self.service.get_media(project_id, media_id)
        if self.media_root:
            from vsc.adapters.persistence.legacy_json.panel import file_hash
            for location in row.get("locations", []):
                if location.get("storage") == "local" and location.get("available", True):
                    path = safe_path(self.media_root, location["object_key"])
                    if not path.is_file():
                        continue
                    if file_hash(path) != row["sha256"]:
                        raise CatalogError("素材 SHA 已变化", 409, "hash_mismatch")
                    return path
        raise CatalogError("素材未配置可读取的受控存储位置", 404, "storage_unavailable")

    def preview_jobs(self, project_id, media_id=None):
        if self._reader(project_id):
            return {"items": [], "read_only": True}
        value = self.service.list_preview_jobs(project_id, media_id=media_id)
        return value if isinstance(value, dict) else {"items": value}

    def preview(self, project_id, media_id, purpose=None):
        reader = self._reader(project_id)
        if reader:
            row = reader.media(media_id)
            if row["modality"] == "image" and purpose in (None, "thumbnail"):
                return reader.content_path(media_id), row
            raise CatalogError("旧项目未登记该预览副本", 404, "preview_missing")
        row = self.service.get_media_rendition(project_id, media_id, purpose=purpose)
        if self.media_root:
            from vsc.adapters.persistence.legacy_json.panel import file_hash
            for location in row.get("locations", []):
                if location.get("storage") == "local" and location.get("available", True):
                    path = safe_path(self.media_root, location["object_key"])
                    if path.is_file() and file_hash(path) == row["sha256"]:
                        return path, row
        raise CatalogError("预览副本字节缺失或摘要变化", 404, "preview_missing")

    def context(self, project_id, shot_id):
        if self._reader(project_id):
            raise CatalogError("旧项目面板只读；请经原 CLI 编译正式上下文", 422, "legacy_read_only")
        return self.service.compile_shot_context(project_id, shot_id)

    def write(self, action, project_id, payload, actor, expected_revision, idempotency_key):
        if self._reader(project_id):
            raise CatalogError("旧项目只读；写入须先显式迁移", 409, "legacy_read_only")
        return getattr(self.service, action)(project_id, payload, actor=actor, expected_revision=expected_revision,
                                             idempotency_key=idempotency_key)
