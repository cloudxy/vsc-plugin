"""Application seams for source intake and typed resource browsing.

Upload tokens cross this boundary once; repositories receive verified storage
facts through internal arguments and never resolve caller supplied paths.
"""
from vsc.assets.resource_service import ResourceError, required


class SourceResourceService:
    def get_source_workspace(self, project_id):
        from vsc.assets.source_intake import source_intake_capabilities
        project = self.store.get_project(project_id)
        sources = self.store.list_sources(project_id)
        if isinstance(sources, dict):
            sources = sources.get("items", sources.get("sources", []))
        documents = {row["source_id"]: row for row in self.store.list_source_intake_documents(project_id)["items"]}
        for source in sources:
            info = documents.get(source["id"])
            if info:
                source.update({key: info[key] for key in ("title", "intent", "format")})
            else:
                source["title"] = "来源材料 · " + str(source["version"])
        capabilities = source_intake_capabilities()
        capabilities["file_import"] = self.storage is not None
        return {"project_id": project_id, "revision": project["revision"],
                "capabilities": capabilities, "sources": sources,
                "jobs": self.store.list_parse_jobs(project_id)["jobs"]}

    def create_source_intake(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        forbidden = {"content_base64", "path", "object_key", "verified_media", "verified_media_id"}
        if forbidden & payload.keys():
            raise ResourceError("文件来源须使用受控上传凭据", "unsafe_source")
        if "staged_upload" in payload:
            if self.storage is None:
                raise ResourceError("未配置受控文件存储", "storage_unavailable")
            if "content" in payload:
                raise ResourceError("粘贴文本与文件上传只能选择一种", "invalid_payload")
            verified = self.storage.commit_upload(payload["staged_upload"])
            from vsc.assets.source_intake import MAX_SOURCE_BYTES
            if verified["size_bytes"] > MAX_SOURCE_BYTES:
                raise ResourceError("来源超过 10 MiB", "source_size_limit")
            return self.store.create_source_intake(project_id, payload, verified_media=verified, **kw)
        return self.store.create_source_intake(project_id, payload, **kw)

    def create_parse_job(self, project_id, payload, **kw):
        return self._write("create_parse_job", project_id, payload, **kw)

    def run_parse_job(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        job = self.store.get_parse_job(project_id, required(payload, "job_id"))
        verified = {}
        for item in job.get("inputs", []):
            source = self.store.get_source_version(project_id, item["source_id"])
            for reference in source.get("media", []):
                media = self.store.get_media(project_id, reference["id"])
                if self.storage is None:
                    continue
                for location in media.get("locations", []):
                    if location.get("available") and location["storage"] == "local":
                        try:
                            verified[item["source_id"]] = self.storage.read(location["object_key"], media["sha256"])
                            break
                        except (ResourceError, OSError):
                            continue
        return self.store.run_parse_job(project_id, payload, verified_sources=verified, **kw)

    def get_parse_job(self, project_id, job_id):
        return self.store.get_parse_job(project_id, job_id)

    def preview_parse_job(self, project_id, job_id):
        return self.store.preview_parse_job(project_id, job_id)

    def get_source_anchor(self, project_id, anchor_id):
        return self.store.get_source_anchor(project_id, anchor_id)

    def prepare_parse_import(self, project_id, payload, **kw):
        return self._write("prepare_parse_import", project_id, payload, **kw)

    def import_parse_job(self, project_id, payload, **kw):
        return self._write("import_parse_job", project_id, payload, **kw)

