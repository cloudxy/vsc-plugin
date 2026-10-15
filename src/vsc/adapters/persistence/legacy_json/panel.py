"""Read-only resource projection of a legacy project; never invent relationships."""
import hashlib
import json
import mimetypes
from pathlib import Path


MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff",
                  ".mp4", ".mov", ".webm", ".mkv", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aiff",
                  ".txt", ".md", ".json", ".srt", ".vtt", ".pdf", ".docx", ".xlsx", ".epub"}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".srt", ".vtt"}


class CatalogError(ValueError):
    def __init__(self, message, status_code=422, code="invalid_resource"):
        super().__init__(message)
        self.message, self.status_code, self.code = message, status_code, code


def safe_path(root, relative):
    root = Path(root).resolve()
    candidate = root / str(relative)
    # No linked component is accepted, including links that currently point inside.
    try:
        parts = candidate.relative_to(root).parts
    except ValueError:
        raise CatalogError("文件路径超出项目范围", 403, "path_boundary")
    cursor = root
    for part in parts:
        if part in ("..", "."):
            raise CatalogError("文件路径不合法", 403, "path_boundary")
        cursor = cursor / part
        if cursor.is_symlink():
            raise CatalogError("不允许通过符号链接读取项目文件", 403, "path_boundary")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise CatalogError("文件路径超出项目范围", 403, "path_boundary")
    return resolved


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def modality(path):
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if mime.split("/")[0] in ("image", "video", "audio"):
        return mime.split("/")[0], mime
    return ("text" if Path(path).suffix.lower() in TEXT_SUFFIXES else "document"), mime


class LegacyPanelReader:
    read_only = True
    storage_policy = "legacy-json"

    def __init__(self, project):
        self.root = Path(project).resolve()

    def state(self):
        source = safe_path(self.root, "vsc.json")
        if not source.is_file():
            raise CatalogError("项目状态文件不存在", 404, "not_found")
        value = json.loads(source.read_text("utf-8"))
        if value.get("profile_snapshot", {}).get("storage_policy") in ("sqlite-series-v1", "postgres-series-v1"):
            raise CatalogError("该项目须从其声明的关系数据库读取", 409, "authority_mismatch")
        return value

    def project(self):
        value = self.state()
        return {"id": value["project_id"], "name": value.get("title", self.root.name),
                "profile": value.get("profile_id"), "revision": value.get("revision", 0),
                "storage_policy": self.storage_policy, "read_only": True,
                "created_at": value.get("created_at"), "updated_at": value.get("updated_at"),
                "object_count": len(value.get("objects", [])), "artifact_count": len(value.get("artifacts", []))}

    def tree(self):
        value = self.state()
        nodes = [{"id": row["id"], "kind": row["kind"], "display_code": row["id"],
                  "title": row.get("label", row["id"]), "parent_id": row.get("parent"),
                  "artifact_id": row.get("artifact"), "ordinal": index}
                 for index, row in enumerate(value.get("objects", []))]
        return {"project": self.project(), "nodes": nodes, "revision": value.get("revision", 0),
                "gaps": [] if nodes else ["未建立结构关系；目录名称不会被自动认作集、场或镜头。"]}

    def descendants(self, object_id):
        if not object_id:
            return None
        nodes = self.tree()["nodes"]
        if object_id not in {row["id"] for row in nodes}:
            raise CatalogError("结构对象不存在", 404, "not_found")
        included = {object_id}
        while True:
            more = {row["id"] for row in nodes if row.get("parent_id") in included}
            if more.issubset(included):
                return included
            included.update(more)

    def _file_status(self, relative, expected=None, verify=True):
        try:
            path = safe_path(self.root, relative)
        except CatalogError:
            return {"availability": "blocked", "integrity": "blocked", "size_bytes": None}
        if not path.is_file():
            return {"availability": "missing", "integrity": "missing", "size_bytes": None}
        integrity = ("verified" if file_hash(path) == expected else "mismatch") if expected and verify else "unverified"
        return {"availability": "available", "integrity": integrity, "size_bytes": path.stat().st_size}

    def artifacts(self, object_id=None):
        value = self.state()
        included = self.descendants(object_id)
        ids = {row.get("artifact") for row in value.get("objects", []) if included is not None and row["id"] in included}
        rows = []
        for source in value.get("artifacts", []):
            scope = source.get("scope") or []
            if isinstance(scope, str):
                scope = [scope]
            if included is not None and source["id"] not in ids and not included.intersection(scope):
                continue
            row = {key: source.get(key) for key in ("id", "type", "stage", "status", "sha256", "scope", "created_at", "depends_on", "dependency_versions", "decision", "supersedes")}
            row.update(name=Path(source.get("path", source["id"])).name,
                       **self._file_status(source.get("path", ""), source.get("sha256")))
            rows.append(row)
        return {"items": rows, "total": len(rows), "revision": value.get("revision", 0)}

    def artifact(self, artifact_id):
        value = self.state()
        source = next((row for row in value.get("artifacts", []) if row["id"] == artifact_id), None)
        if source is None:
            raise CatalogError("产物版本不存在", 404, "not_found")
        result = next(row for row in self.artifacts()["items"] if row["id"] == artifact_id)
        path = safe_path(self.root, source["path"])
        if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024:
            result["content"] = path.read_text("utf-8", errors="replace")
        else:
            result["content"] = None
        result["revision"] = value.get("revision", 0)
        return result

    def registered_media(self):
        return []

    def _inventory(self):
        artifacts = {row.get("path") for row in self.state().get("artifacts", [])}
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in MEDIA_SUFFIXES
                    or path.name == "vsc.json" or str(relative) in artifacts
                    or any(part.startswith(".") and part != ".vsc-media" for part in relative.parts)):
                continue
            try:
                safe_path(self.root, relative)
            except CatalogError:
                continue
            kind, mime = modality(path)
            yield {"id": "inventory-" + hashlib.sha256(str(relative).encode()).hexdigest()[:24],
                   "name": path.name, "relative_path": str(relative), "modality": kind, "mime_type": mime,
                   "registered": False, "rights": "unknown", "availability": "available", "integrity": "unverified",
                   "size_bytes": path.stat().st_size, "bindings": [], "sources": [], "reviews": [], "decisions": []}

    def resources(self, object_id=None, offset=0, limit=50, modality=None, registration=None, query=None, role=None, status=None, **unused):
        included = self.descendants(object_id)
        registered = self.registered_media()
        known_paths = {row.get("relative_path") for row in registered}
        rows = registered + [row for row in self._inventory() if row["relative_path"] not in known_paths]
        if included is not None:
            rows = [row for row in rows if any(binding.get("target_id") in included for binding in row.get("bindings", []))]
        if modality:
            rows = [row for row in rows if row["modality"] == modality]
        if role:
            rows = [row for row in rows if any(binding.get("role") == role for binding in row.get("bindings", []))]
        if status in ("selected", "unselected"):
            rows = [row for row in rows if any(binding.get("status") == "approved" for binding in row.get("bindings", [])) == (status == "selected")]
        if status == "deprecated":
            # These authorities have no global lifecycle decision relation.
            # A retired individual binding does not deprecate the entire media.
            rows = []
        if registration in ("registered", "unregistered"):
            rows = [row for row in rows if row["registered"] == (registration == "registered")]
        if query:
            rows = [row for row in rows if query.casefold() in row["name"].casefold() or query.casefold() in row.get("id", "").casefold()]
        rows.sort(key=lambda row: (not row["registered"], row["name"], row["id"]))
        return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit,
                "revision": self.project()["revision"], "read_only": True}

    def media(self, media_id):
        for row in self.registered_media():
            if row["id"] == media_id:
                row.update(self._file_status(row["relative_path"], row.get("sha256")))
                return row
        for row in self._inventory():
            if row["id"] == media_id:
                return row
        raise CatalogError("素材不存在", 404, "not_found")

    def content_path(self, media_id):
        row = self.media(media_id)
        path = safe_path(self.root, row["relative_path"])
        if not path.is_file():
            raise CatalogError("素材字节缺失", 404, "missing_bytes")
        if row.get("sha256") and file_hash(path) != row["sha256"]:
            raise CatalogError("素材 SHA 已变化，已停止正式读取", 409, "hash_mismatch")
        return path

    def lineage(self, media_id):
        self.media(media_id)
        return {"inputs": [], "outputs": [], "sources": [], "gaps": ["未登记加工与来源关系"], "truncated": False}

    def usage(self, media_id):
        row = self.media(media_id)
        return {"bindings": row.get("bindings", []), "jobs": [], "operations": [], "timelines": [], "renders": [],
                "gaps": [] if row.get("bindings") else ["未建立用途关系"], "truncated": False}
