"""Batch file intake with original media registration and explicit asset choices."""
from vsc.assets.resource_service import ResourceError


class MediaImportService:
    def _imports(self):
        from vsc.adapters.persistence.postgres.media_imports import MediaImportRepository
        return MediaImportRepository(self.store)

    def list_media_imports(self, project_id, offset=0, limit=50):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200:
            raise ResourceError("导入清单分页范围无效")
        return self._imports().list(project_id, offset, limit)

    def get_media_import(self, project_id, batch_id):
        value = self._imports().get(project_id, batch_id)
        from vsc.adapters.storage.local.import_upload import ImportUpload
        upload = ImportUpload(self.storage) if self.storage else None
        for item in value["items"]:
            key = item.pop("upload_key")
            item["has_upload"] = bool(item["uploaded_metadata"])
            item.pop("uploaded_metadata", None)
            item["uploaded_bytes"] = item["size_bytes"] if item["status"] in {"uploaded", "completed"} else upload.progress(key) if upload else 0
        return value

    def create_media_import(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if self.storage is None:
            raise ResourceError("受控媒体存储未配置", "storage_unavailable", 409)
        if set(payload) - {"title", "episode_id", "asset_kind", "rights", "rights_scope", "source_evidence", "files"}:
            raise ResourceError("导入清单含未知字段", "invalid_import_manifest")
        files = payload.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 200:
            raise ResourceError("每批需要 1–200 个文件", "invalid_import_manifest")
        for file in files:
            if (not isinstance(file, dict) or set(file)-{"filename","size_bytes","sha256"}
                    or not isinstance(file.get("filename"), str) or not 1 <= len(file["filename"]) <= 240
                    or "/" in file["filename"] or "\\" in file["filename"]
                    or type(file.get("size_bytes")) is not int or not 1 <= file["size_bytes"] <= self.storage.max_bytes):
                raise ResourceError("文件名称或大小无效", "invalid_import_manifest")
            import re
            if not isinstance(file.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"]):
                raise ResourceError("续传清单需要每个文件的完整 SHA-256 摘要", "import_sha_required")
        if payload.get("asset_kind") not in {None,"character","location","prop","voice"}:
            raise ResourceError("请选择明确的资产类型", "invalid_import_manifest")
        rights = payload.get("rights", "unknown")
        scope = payload.get("rights_scope", {"purposes": ["*"] if rights=="owned" else []})
        if rights not in {"owned", "licensed", "unknown"} or not isinstance(scope, dict) or not isinstance(scope.get("purposes"), list):
            raise ResourceError("素材权利与用途范围无效", "invalid_import_manifest")
        evidence = payload.get("source_evidence", "")
        if not isinstance(evidence, str) or len(evidence)>20000 or (rights!="unknown" and not evidence.strip()):
            raise ResourceError("已知权利需要明确来源依据", "rights_evidence_required")
        return self._imports().create(project_id, dict(payload, rights=rights, rights_scope=scope, source_evidence=evidence), **kw)

    def upload_import_chunk(self, project_id, batch_id, item_id, offset, content, *, actor):
        self._actor(actor)
        if self.storage is None:
            raise ResourceError("受控存储未配置", "storage_unavailable", 409)
        from vsc.adapters.storage.local.import_upload import ImportUpload
        item = self._imports().item(project_id, batch_id, item_id)
        if item["status"] == "cancelled":
            raise ResourceError("此文件已取消导入", "import_cancelled", 409)
        if item["status"] in {"uploaded", "completed"}:
            return {"id": item_id, "status": item["status"], "uploaded_bytes": item["size_bytes"]}
        try:
            result = ImportUpload(self.storage).append(item["upload_key"], offset, content, item["size_bytes"], item["filename"])
        except ResourceError as error:
            if error.status_code != 409:
                self._imports().fail(project_id, batch_id, item_id, error.message, actor)
            raise
        if result["metadata"]:
            if item["expected_sha256"] and result["metadata"]["sha256"] != item["expected_sha256"]:
                self._imports().fail(project_id, batch_id, item_id, "文件摘要与固定清单不符", actor)
                raise ResourceError("文件摘要与固定清单不符", "import_sha_mismatch")
            accepted = self._imports().uploaded(project_id, batch_id, item_id, result["metadata"], actor)
            return dict(accepted, uploaded_bytes=result["uploaded_bytes"])
        return {"id": item_id, "status": "awaiting_upload", "uploaded_bytes": result["uploaded_bytes"]}

    def process_media_import_item(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"batch_id", "item_id"}:
            raise ResourceError("请选择清单内的单个文件", "invalid_import_item")
        if self.storage is None:
            raise ResourceError("受控存储未配置", "storage_unavailable", 409)
        item = self._imports().item(project_id, payload["batch_id"], payload["item_id"])
        if item["uploaded_metadata"]:
            metadata = item["uploaded_metadata"]
            self.storage.verify(metadata["object_key"], metadata["sha256"])
        return self._imports().process(project_id, payload, **kw)

    def cancel_media_import_item(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"batch_id", "item_id"}:
            raise ResourceError("请选择单个待导入文件", "invalid_import_item")
        return self._imports().cancel(project_id, payload, **kw)
