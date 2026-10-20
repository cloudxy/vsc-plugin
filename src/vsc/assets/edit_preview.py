"""Application entry points for one opinion to one restricted subtitle preview."""
from pathlib import Path


class EditPreviewService:
    def _edit_previews(self):
        from vsc.adapters.persistence.postgres.edit_preview_store import EditPreviewRepository
        return EditPreviewRepository(self.store)

    def get_edit_preview_capability(self, project_id, **target):
        from vsc.post.edit_preview import EditPreviewConverter
        result = self._edit_previews().capability(project_id, **target)
        worker = getattr(self, "edit_preview_worker", None)
        runtime = worker.status() if worker else {**EditPreviewConverter().capabilities(), "running": False}
        result["worker"] = runtime
        if not runtime["available"] or not runtime.get("running"):
            result.update(available=False, reason=runtime.get("reason") or "字幕后台处理未启用，请在应用运行设置中启用。")
        return result

    def request_edit_preview(self, project_id, payload, **kw):
        from vsc.post.edit_preview import EditPreviewConverter
        self._validate_write(payload, **kw)
        worker = getattr(self, "edit_preview_worker", None)
        tool = worker.status() if worker else {**EditPreviewConverter().capabilities(), "running": False}
        if not tool.get("running"):
            tool = dict(tool, available=False, reason="字幕后台处理未启用；原意见已保留。")
        return self._edit_previews().request(project_id, payload, tool, **kw)

    def list_edit_previews(self, project_id, artifact_note_id=None):
        repository = self._edit_previews()
        result = repository.list(project_id, artifact_note_id)
        self._observe_edit_previews(project_id, result["items"])
        return result

    def _observe_edit_previews(self, project_id, items):
        """Apply the same observation to polling and the original opinion view."""
        from vsc.assets.media_availability import media_availability
        repository = self._edit_previews()
        for item in items:
            if item.get("output"):
                fixed = repository.content(project_id, item["id"])
                item["result_availability"] = media_availability(self.storage, fixed)
                if item["result_availability"]["status"] == "unavailable":
                    item["output"].pop("content_url", None)
            else:
                item["result_availability"] = {"status": "unavailable", "check": "registration",
                                               "message": "本次任务尚未登记可回看的预览。"}

    def retry_edit_preview(self, project_id, job_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if payload:
            raise ResourceError("重试只恢复原固定任务，不能附加新编辑。", "invalid_payload")
        worker = getattr(self,"edit_preview_worker",None)
        if worker is None or not worker.status()["running"]:
            raise ResourceError("请先恢复字幕后台处理，再重试原任务。", "edit_preview_worker_unavailable")
        return self._edit_previews().retry(project_id,job_id,**kw)

    def edit_preview_content(self, project_id, job_id):
        from vsc.assets.resource_service import ResourceError
        result = self._edit_previews().content(project_id, job_id)
        location = next((row for row in result["locations"] if row["storage"] == "local"), None)
        if self.storage is None or location is None:
            raise ResourceError("字幕预览的受控本地副本不可用。", "edit_preview_output_unavailable")
        path = self.storage.verify(location["object_key"], result["blob_sha256"])
        return Path(path), result

    def produce_captioned_render(self, project_id, payload, **kw):
        """Professional local producer: keep the uncaptioned input and its font.

        The caller explicitly supplies the composed clean master. This does not
        render multiple shots or approve a plan; original freeze_render does the
        final approval check again. Partial registration reuses stable receipts.
        """
        import json
        import shutil
        import tempfile
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import Conflict, ResourceError
        from vsc.post import remotion_plan as RP
        from vsc.post.edit_preview import EditPreviewConverter, RECIPE_VERSION
        self._validate_write(payload, **kw)
        expected = {"timeline_id", "artifact_id", "clean_master_media_id", "font_media_id"}
        if set(payload) != expected or self.storage is None:
            raise ResourceError("字幕生产需要固定时间线、已批准计划、无字幕底片和原字体。", "invalid_payload")
        repository = self._edit_previews()
        converter = EditPreviewConverter()
        tool = converter.capabilities()
        if not tool["available"]:
            raise ResourceError(tool["reason"], "edit_preview_tool_unavailable")
        key = kw["idempotency_key"]
        if len(key) > 150:
            raise ResourceError("字幕生产请求键最多 150 字符。", "idempotency_required")
        def preflight(conn, project):
            p = project["id"]
            self.store._one(conn, S.timeline_versions, p, payload["timeline_id"])
            source, document = repository._baseline(conn, p, {"artifact_id": payload["artifact_id"]})
            master = self.store._media(conn, p, payload["clean_master_media_id"])
            font = self.store._media(conn, p, payload["font_media_id"])
            proof = {"plan_sha256": RP.document_sha256(document), "sha256": master["sha256"], "font_sha256": font["sha256"],
                "subtitles_absent": True, "caption_count": 0, "composition": RP.render_plan(document)["composition"],
                "producer": "vsc-caption-render-explicit-clean-master", "producer_version": RECIPE_VERSION}
            fixed = {"timeline_id": payload["timeline_id"], "parameters": {"edit_preview_clean_master": proof}}
            inputs = repository._inputs(conn, p, fixed, document, outputs=[
                {"media_id": master["id"], "role": "clean_master"}, {"media_id": font["id"], "role": "subtitle_font"}])
            return {"sha256": source["sha256"], "proof": proof, "tool_version": tool["tool_version"]}
        begun = self.store._mutate(project_id, "begin_caption_render", payload, callback=preflight, **kw)
        final_key = "caption-render-freeze:"+key
        with self.store.engine.connect() as conn:
            prior = conn.execute(select(S.command_receipts.c.response).where(S.command_receipts.c.project_id==project_id,
                S.command_receipts.c.idempotency_key==final_key)).scalar_one_or_none()
            if prior:
                return prior
            fixed = preflight(conn, self.store._project(conn, project_id))
            if fixed != {field: begun[field] for field in ("sha256", "proof", "tool_version")}:
                raise Conflict("字幕生产的固定输入或工具版本已变化。", "caption_render_input_changed")
            source = self.store._one(conn, S.artifact_versions, project_id, payload["artifact_id"])
            document = json.loads(source["document"])
            inputs = repository._inputs(conn, project_id, {"timeline_id": payload["timeline_id"],
                "parameters": {"edit_preview_clean_master": fixed["proof"]}}, document, outputs=[
                {"media_id": payload["clean_master_media_id"], "role": "clean_master"},
                {"media_id": payload["font_media_id"], "role": "subtitle_font"}])
        with tempfile.TemporaryDirectory(prefix="vsc-caption-render-") as directory:
            paths = {}
            for item in inputs:
                location = next((l for l in item["locations"] if l["storage"]=="local" and l["available"]), None)
                if not location:
                    raise ResourceError("字幕生产缺少固定输入的受控本地副本。", "edit_preview_input_missing")
                path = self.storage.verify(location["object_key"], item["sha256"])
                if item["role"]=="subtitle_audio":
                    target = Path(directory)/item["source_path"]
                    if not target.resolve().is_relative_to(Path(directory).resolve()):
                        raise ResourceError("字幕包用料路径越界。", "edit_preview_package_path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path,target)
                else:
                    paths[item["role"]] = path
            output, receipt = converter.convert({"recipe_version": RECIPE_VERSION, "tool_version": fixed["tool_version"],
                "document": document, "start_frame": 0, "end_frame": RP.render_plan(document)["composition"]["duration_in_frames"],
                "master_sha256": fixed["proof"]["sha256"], "font_sha256": fixed["proof"]["font_sha256"],
                "draft_sha256": source["sha256"]}, paths["clean_master"], paths["subtitle_font"], directory)
            with output.open("rb") as stream:
                staged = self.storage.stage_upload(stream, "caption-render.mp4")
            media_payload = {"staged_upload": staged["staged_upload"], "name": "固定字幕渲染",
                "rights": "unknown", "source": {"kind": "local_caption_render",
                    "content": json.dumps({"source_plan_sha256": source["sha256"], "technical_receipt": receipt}, ensure_ascii=False)}}
            for retry in range(5):
                try:
                    media = self.register_media(project_id, media_payload, actor=kw["actor"],
                        expected_revision=self.store.get_project(project_id)["revision"], idempotency_key="caption-render-media:"+key)
                    break
                except Conflict as error:
                    if error.code!="revision_conflict" or retry==4:
                        raise
        render_payload = {"timeline_id": payload["timeline_id"], "artifact_id": payload["artifact_id"],
            "tool": "vsc-caption-render", "tool_version": fixed["tool_version"],
            "parameters": {"edit_preview_clean_master": fixed["proof"], "technical_receipt": receipt},
            "outputs": [{"media_id": media["id"], "role": "delivery"}],
            "caption_inputs": [{"media_id": payload["clean_master_media_id"], "role": "clean_master"},
                               {"media_id": payload["font_media_id"], "role": "subtitle_font"}]}
        for retry in range(5):
            try:
                return self.freeze_render(project_id, render_payload, actor=kw["actor"],
                    expected_revision=self.store.get_project(project_id)["revision"], idempotency_key=final_key)
            except Conflict as error:
                if error.code!="revision_conflict" or retry==4:
                    raise
