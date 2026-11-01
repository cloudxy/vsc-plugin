"""Working edits shared by the web editor and local render consumer."""
from pathlib import Path


class EditorWorkspaceService:
    def _editor_handoff(self):
        from vsc.adapters.persistence.postgres.editor_handoff import EditorHandoffRepository
        return EditorHandoffRepository(self.store)

    def edit_timeline_options(self, project_id, version_id):
        return self._editor_handoff().options(project_id, version_id)

    def preview_edit_timeline(self, project_id, payload):
        from vsc.assets.resource_service import ResourceError
        if not isinstance(payload,dict) or set(payload)!={'edit_version_id','selected_takes_id','assignments'}:
            raise ResourceError('时间线需要固定剪辑、选片清单与逐片段映射','edit_mapping_required')
        return self._editor_handoff().preview(project_id,payload)

    def propose_edit_timeline(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload,**kw)
        if set(payload)!={'request','preview_sha256'}:
            raise ResourceError('先预览固定时间线再登记','edit_handoff_preview_required')
        self.preview_edit_timeline(project_id,payload['request'])
        return self._editor_handoff().propose(project_id,payload,**kw)

    def freeze_edit_timeline(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload,**kw)
        if set(payload)!={'artifact_id'}:raise ResourceError('须指定已批准时间线','edit_handoff_required')
        frozen=self._editor_handoff().frozen_payload(project_id,payload['artifact_id'])
        return self.freeze_timeline(project_id,frozen,**kw)

    def export_edit_workspace(self, project_id, version_id, kind):
        import tempfile
        from vsc.assets.resource_service import ResourceError
        from vsc.post.edit_workspace_export import subtitles, write_archive
        if kind not in {'srt', 'project'}:
            raise ResourceError('只支持字幕或可恢复剪辑工程', 'invalid_edit_export_kind')
        fixed = self._editor().export_inputs(project_id, version_id)
        temporary = tempfile.TemporaryDirectory(prefix='vsc-edit-download-')
        try:
            if kind == 'srt':
                path = Path(temporary.name) / 'subtitles.srt'
                path.write_text(subtitles(fixed['document']), encoding='utf-8')
                return path, 'application/x-subrip', temporary
            if self.storage is None:
                raise ResourceError('素材存储未配置', 'edit_input_missing')
            paths = {}
            for row in fixed['inputs']:
                location = next((item for item in row['locations'] if item['storage']=='local' and item.get('available',True)), None)
                if not location:
                    raise ResourceError('工程素材缺少受控本地副本', 'edit_input_missing')
                paths[row['clip_key']] = self.storage.verify(location['object_key'], row['blob_sha256'])
            path = Path(temporary.name) / 'edit-workspace.zip'
            write_archive(fixed, paths, path)
            return path, 'application/zip', temporary
        except Exception:
            temporary.cleanup()
            raise

    def _editor(self):
        from vsc.adapters.persistence.postgres.editor_workspace import EditorWorkspaceRepository
        return EditorWorkspaceRepository(self.store)

    def get_edit_workspace(self, project_id, episode_id):
        from vsc.post.edit_workspace import FirstCutRenderer
        value = self._editor().get(project_id, episode_id)
        worker = getattr(self, "first_cut_worker", None)
        value["renderer"] = worker.status() if worker else dict(FirstCutRenderer().capabilities(), running=False)
        return value

    def seed_edit_workspace(self, project_id, episode_id):
        return self._editor().seed(project_id, episode_id)

    def save_edit_workspace(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) - {"episode_id", "edit_revision", "document", "restore_version_id"}:
            raise ResourceError("剪辑保存含未知字段", "invalid_payload")
        return self._editor().save(project_id, payload, **kw)

    def request_edit_export(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        from vsc.post.edit_workspace import FirstCutRenderer
        self._validate_write(payload, **kw)
        if set(payload) != {"edit_version_id"}:
            raise ResourceError("合成须指定保存的剪辑版本", "invalid_payload")
        capability = FirstCutRenderer().capabilities()
        if not capability["available"] or self.storage is None:
            raise ResourceError(capability["reason"] or "媒体存储未配置", "edit_renderer_unavailable", 409)
        return self._editor().request(project_id, payload, **kw)

    def cancel_edit_export(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {'job_id'}:raise ResourceError('取消须指定单次合成任务','invalid_payload')
        return self._editor().cancel(project_id, payload, **kw)

    def edit_export_content(self, project_id, job_id):
        from vsc.assets.resource_service import ResourceError
        value = self._editor().content(project_id, job_id)
        location = next((l for l in value["locations"] if l["storage"] == "local"), None)
        if not location or self.storage is None:
            raise ResourceError("合成文件的受控副本不可用", "edit_export_unavailable")
        return Path(self.storage.verify(location["object_key"], value["sha256"])), value

    def edit_export_cover(self, project_id, job_id, at_ms=0):
        import subprocess
        import tempfile
        from vsc.assets.resource_service import ResourceError
        source, fixed = self.edit_export_content(project_id, job_id)
        duration = fixed['receipt'].get('duration_ms', 0)
        if type(at_ms) is not int or not 0 <= at_ms < duration:
            raise ResourceError('封面时刻须位于所选合成版本内', 'edit_cover_range')
        temporary = tempfile.TemporaryDirectory(prefix='vsc-edit-cover-')
        try:
            target = Path(temporary.name) / 'cover.png'
            result = subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss',str(at_ms/1000),
                '-i',str(source),'-frames:v','1',str(target)],capture_output=True,timeout=30)
            if result.returncode or not target.is_file():
                raise ResourceError('无法提取此固定输出的封面，请检查本机 FFmpeg。', 'edit_cover_unavailable')
            return target, temporary
        except Exception:
            temporary.cleanup()
            raise
