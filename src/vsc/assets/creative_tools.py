"""Music, MV and video-tool use cases over existing resources and execution."""
from copy import deepcopy
import json

from vsc.production.creative_tools import DRAFT_TYPE, FORMAT, TOOLS, compile_mv, music_edit, normalize_draft


class CreativeToolsService:
    def open_creative_tool_workspace(self, *, actor):
        from dataclasses import replace
        from vsc.assets.access_control import current_principal,set_principal,reset_principal
        self._actor(actor)
        identity=self._creative_tools().workspace_identity(actor)
        token=set_principal(replace(current_principal(),workspace_id=None))
        try:
            project=self.create_project({'name':'独立音乐与视频工具','profile':'vsc.creative-tools','profile_snapshot':{
                'profile_id':'vsc.creative-tools','version':'1.0','stages':[],
                'storage_policy':'postgres-series-v1','workspace_kind':'creative-tools'}},
                actor=actor,idempotency_key='creative-tools-workspace:'+identity)
            return self._creative_tools().ensure_workspace(project['id'],identity,actor)
        finally:reset_principal(token)

    def preview_creative_output_import(self, project_id, payload):
        return self._creative_tools().preview_import(project_id,payload,storage=self.storage)

    def import_creative_output(self, project_id, payload, **kw):
        self._validate_write(payload,**kw)
        return self._creative_tools().import_output(project_id,payload,storage=self.storage,**kw)

    def _creative_tools(self):
        from vsc.adapters.persistence.postgres.creative_tools import CreativeToolsRepository
        return CreativeToolsRepository(self.store)

    def creative_tools_options(self, project_id, object_id=None):
        self.authorize_access(project_id,'read')
        from vsc.production.resource_settings import ResourceSettings
        from vsc.assets.resource_service import Conflict, ResourceError
        tree = self.get_project_tree(project_id)
        nodes = {row["id"]: row for row in tree["nodes"]}
        standalone=tree['project'].get('profile_snapshot',{}).get('workspace_kind')=='creative-tools'
        if standalone and not object_id:
            object_id=next((row['id'] for row in tree['nodes'] if row['kind']=='episode' and row['display_code']=='TOOL-SCOPE'),None)
        episode, seen = nodes.get(object_id), set()
        if object_id and not episode:
            raise ResourceError("工具范围不属于当前项目", "tool_scope_mismatch")
        while episode and episode["kind"] != "episode" and episode["id"] not in seen:
            seen.add(episode["id"])
            episode = nodes.get(episode.get("parent_id"))
        models = ResourceSettings(self.store).list()["configurations"]
        from vsc.production.music_tools import LyricPlanner
        lyric_host=getattr(self,"lyric_planner",None) or LyricPlanner()
        fields = ("id", "name", "model_key", "model_version", "modality", "enabled", "capabilities",
                  "adapter_available", "connection_status")
        models = [{key: row.get(key) for key in fields} for row in models]
        tools = []
        for key, (label, modality, purpose, reason) in TOOLS.items():
            matches = [row["id"] for row in models if row["modality"] == modality and row["enabled"]
                and row["adapter_available"] and purpose in row["capabilities"].get("purposes", [])]
            tools.append(dict(id=key, label=label, modality=modality, purpose=purpose, model_ids=matches,
                mode="local" if modality == "local" else "text_host" if key=="lyrics" and lyric_host.available() else "provider" if not reason and matches else "draft_only",
                reason=reason or ("需要启用已接通的实际模型" if modality != "local" and not matches else ""),
                execution_consumer="lyrics-draft" if key == "lyrics" else "edit-workspace" if key == "music_mix" else "shot-plan-and-edit-workspace" if key == "mv" else "local-media-output" if modality == "local" else "production-run"))
        media = self.list_resources(project_id, limit=200)
        drafts = self._creative_tools().list(project_id, episode["id"]) if episode else {"items": [], "revision": tree["revision"]}
        local_outputs = self._creative_tools().outputs(project_id, episode["id"]) if episode else []
        canvases = self.list_creative_canvases(project_id, episode["id"])["items"] if episode else []
        music_results=self._creative_tools().music_results(project_id,episode["id"]) if episode else []
        if self.get_project(project_id)["revision"] != tree["revision"]:
            raise Conflict("工具资料读取期间已改变，请刷新")
        return dict(project_id=project_id, revision=tree["revision"], episode=episode, standalone=standalone,
            episodes=[row for row in tree["nodes"] if row["kind"] == "episode"],
            shots=[row for row in tree["nodes"] if row["kind"] == "shot" and self._tool_in_episode(nodes, row, episode)],
            tools=tools, models=models, drafts=drafts["items"],
            media=[{key: row.get(key) for key in ("id", "name", "modality", "sha256", "duration_ms")} for row in media["items"]],
            media_total=media["total"], local_outputs=local_outputs, canvases=canvases,
            music_results=music_results)

    def create_creative_lyrics(self,p,payload,**kw):
        from vsc.assets.resource_service import ResourceError
        from vsc.production.music_tools import LyricPlanner,validate_lyrics
        from vsc.bootstrap import repository_root
        import hashlib,uuid
        self._validate_write(payload,**kw)
        if set(payload)!={'draft_version_id','new_attempt'} or type(payload['new_attempt'])is not bool:raise ResourceError('歌词创作需要固定稿与明确新尝试选择')
        backend=getattr(self,'lyric_planner',None) or LyricPlanner();caller=uuid.uuid4().hex;repo=self._creative_tools()
        started=repo.start_lyrics(p,payload,caller=caller,backend=backend.name,**kw)
        request=repo.lyrics_result(p,started['id'])
        if started.get('caller')!=caller:return request
        result,error=None,None
        try:
            if not backend.available():raise ResourceError('本机歌词规划宿主尚不可用','lyrics_host_unavailable')
            skill=(repository_root()/'skills'/request['skill_id']/'SKILL.md').read_text(encoding='utf8')
            if hashlib.sha256(skill.encode()).hexdigest()!=request['skill_sha256']:raise ResourceError('固定Skill版本已变，请保存新稿','lyrics_skill_changed')
            packet=self.get_role_dispatch(p,request['dispatch_id'])['packet'];_,saved=self._fixed_creative_tool(p,request['draft_version_id'])
            result=validate_lyrics(backend.generate(packet,saved['input'],skill))
        except ResourceError as exc:error=exc.code
        except Exception:error='lyrics_submission_unknown'
        return repo.finish_lyrics(p,request['id'],result,error)

    def get_creative_lyrics(self,p,identifier):return self._creative_tools().lyrics_result(p,identifier)

    def analyze_creative_music(self,p,payload,**kw):
        from vsc.assets.resource_service import ResourceError
        from vsc.production.music_tools import analyze_audio
        self._validate_write(payload,**kw)
        if set(payload)!={'draft_version_id','beats_per_segment'}:raise ResourceError('分析需要固定音乐稿与每段起音数')
        def build(media,count):
            if self.storage is None:raise ResourceError('节拍分析需要本机受控音频')
            location=next((r for r in media['locations'] if r['storage']=='local' and r.get('available')),None)
            if not location:raise ResourceError('音乐没有可用本地副本')
            return analyze_audio(self.storage.verify(location['object_key'],media['sha256']),count)
        return self._creative_tools().analyze_music(p,payload,build=build,**kw)

    def accept_creative_music_result(self,p,payload,**kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload,**kw)
        if set(payload)!={'result_version_id','base_draft_id'}:raise ResourceError('接受建议需固定结果和所见人工稿')
        return self._creative_tools().accept_music_result(p,payload,build=self._creative_tool_document,**kw)

    def preview_creative_mv_edit(self,p,payload):return self._creative_tools().preview_mv_edit(p,payload)

    def apply_creative_mv_edit(self,p,payload,**kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload,**kw)
        if set(payload)!={'request','preview_sha256'}:raise ResourceError('请先预览固定MV剪辑差异')
        return self._creative_tools().apply_mv_edit(p,payload,**kw)

    def process_creative_tool_local(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"draft_version_id"}:
            raise ResourceError("本机加工需要固定已保存草稿")
        if self.storage is None:
            raise ResourceError("本机加工需要受控素材存储", "storage_unavailable")
        def build(value, media, replacement=None):
            import tempfile
            from vsc.post.local_media_tools import process
            location = next((r for r in media["locations"] if r["storage"] == "local" and r.get("available")), None)
            if not location:
                raise ResourceError("源媒体缺少可用本地副本", "local_source_missing")
            path = self.storage.verify(location["object_key"], media["sha256"])
            replacement_path=None
            if replacement:
                location=next((r for r in replacement["locations"] if r["storage"]=="local" and r.get("available")),None)
                if not location:raise ResourceError("替换素材缺少可用本地副本")
                replacement_path=self.storage.verify(location["object_key"],replacement["sha256"])
            with tempfile.TemporaryDirectory(prefix="vsc-local-tool-") as directory:
                outputs, receipt = process(path, value, directory, replacement_path)
                registered = []
                for item in outputs:
                    with item["path"].open("rb") as stream:
                        staged = self.storage.stage_upload(stream, item["path"].name)
                    registered.append({"role": item["role"], "media": self.storage.commit_upload(staged["staged_upload"])})
                return registered, receipt
        return self._creative_tools().process_local(project_id, payload, build=build, **kw)

    def use_creative_tool_output(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if not isinstance(payload, dict) or set(payload) - {"output_version_id", "media_id", "target", "shot_id", "canvas_id", "canvas_revision", "edit_revision", "audio_purpose"}:
            raise ResourceError("输出使用目标无效")
        return self._creative_tools().use_output(project_id, payload, **kw)

    @staticmethod
    def _tool_in_episode(nodes, row, episode):
        seen = set()
        while row and row["id"] not in seen:
            if episode and row["id"] == episode["id"]:
                return True
            seen.add(row["id"])
            row = nodes.get(row.get("parent_id"))
        return False

    def _creative_tool_document(self, project_id, value):
        from vsc.assets.resource_service import ResourceError
        try:
            value = normalize_draft(value)
        except ValueError as error:
            raise ResourceError(str(error), "invalid_tool_draft") from error
        tree = self.get_project_tree(project_id)
        nodes = {row["id"]: row for row in tree["nodes"]}
        episode = nodes.get(value["episode_id"])
        if not episode or episode["kind"] != "episode":
            raise ResourceError("请选择当前项目的集", "tool_scope_mismatch")
        if value["shot_id"] and (nodes.get(value["shot_id"], {}).get("kind") != "shot" or not self._tool_in_episode(nodes, nodes[value["shot_id"]], episode)):
            raise ResourceError("镜头不属于所选集", "tool_scope_mismatch")
        pins = []
        refs = [("source", value["source_media_id"]), ("audio", value["audio_media_id"]), ("voice", value["voice_media_id"]), ("replacement",value["replacement_media_id"])]
        refs += [("visual", identifier) for identifier in value["visual_media_ids"]]
        for role, identifier in refs:
            if not identifier:
                continue
            media = self.get_media(project_id, identifier)
            expected = {"source": {"video"}, "audio": {"audio"}, "voice": {"audio"}, "visual": {"image", "video"}, "replacement":{"video"}}[role]
            if media["modality"] not in expected:
                raise ResourceError("所选素材类型与工具用途不符", "tool_media_type")
            pins.append(dict(role=role, media_id=identifier, sha256=media["sha256"], duration_ms=media.get("duration_ms")))
            if role == "source" and value["ranges"] and (not media.get("duration_ms") or value["ranges"][-1]["end_ms"] > media["duration_ms"]):
                raise ResourceError("处理区间超过固定源视频", "tool_range_invalid")
        return dict(format=FORMAT, input=value, media=pins,
            blocked_reason=TOOLS[value["tool"]][3], generated=False)

    def save_creative_tool_draft(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"document", "base_draft_id"}:
            raise ResourceError("保存需要工具输入与当前草稿版本")
        return self._creative_tools().save(project_id, payload, build=self._creative_tool_document, **kw)

    def _fixed_creative_tool(self, project_id, identifier):
        from vsc.assets.resource_service import Conflict, ResourceError
        artifact = self.get_artifact_version(project_id, identifier)
        if artifact["artifact_type"] != DRAFT_TYPE:
            raise ResourceError("需要已保存的工具草稿", "tool_draft_required")
        saved = json.loads(artifact["document"])
        current = self._creative_tool_document(project_id, saved["input"])
        if current["media"] != saved["media"]:
            raise Conflict("固定媒体摘要或时长已改变，请另存新版本", "tool_source_changed")
        return artifact, saved

    def compile_creative_mv(self, project_id, payload):
        from vsc.assets.resource_service import ResourceError
        if not isinstance(payload, dict) or set(payload) != {"document"}:
            raise ResourceError("MV 编译需要当前工具输入")
        doc = self._creative_tool_document(project_id, payload["document"])
        if doc["input"]["tool"] != "mv" or not doc["input"]["audio_media_id"]:
            raise ResourceError("MV 需要已登记的音乐音频", "mv_audio_required")
        try:
            plan = compile_mv(doc["input"], self.get_media(project_id, doc["input"]["audio_media_id"]))
        except ValueError as error:
            raise ResourceError(str(error), "invalid_mv_plan") from error
        return dict(plan=plan, revision=self.get_project(project_id)["revision"])

    def import_creative_mv(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"draft_version_id"}:
            raise ResourceError("导入须指定已保存 MV 草稿版本")
        return self._creative_tools().import_mv(project_id, payload, service=self, **kw)

    def apply_creative_music(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"draft_version_id", "edit_revision"}:
            raise ResourceError("配乐需要固定草稿及所见剪辑版本")
        _, saved = self._fixed_creative_tool(project_id, payload["draft_version_id"])
        value = saved["input"]
        if value["tool"] != "music_mix" or not value["source_media_id"] or not value["audio_media_id"]:
            raise ResourceError("配乐需要原视频与完整音频", "music_inputs_required")
        try:
            edit = music_edit(value, self.get_media(project_id, value["source_media_id"]), self.get_media(project_id, value["audio_media_id"]))
        except ValueError as error:
            raise ResourceError(str(error), "music_range_invalid") from error
        return self.save_edit_workspace(project_id, dict(episode_id=value["episode_id"], edit_revision=payload["edit_revision"], document=edit), **kw)

    def preview_creative_tool_run(self, project_id, payload):
        from vsc.assets.resource_service import ResourceError, Conflict
        from vsc.production.resource_settings import ResourceSettings
        from vsc.production.run_authorization import normalize_request, validate_capabilities
        from vsc.production.run_policy import policy_errors
        from vsc.production.quotes import fingerprint
        if not isinstance(payload, dict) or set(payload)-{"commerce_account_actor"} != {"draft_version_id", "execution_policy"}:
            raise ResourceError("预览需要已保存工具草稿与固定执行时限")
        errors = policy_errors(payload["execution_policy"])
        if payload["execution_policy"] is None or errors:
            raise ResourceError("；".join(errors) or "需要执行时限")
        artifact, saved = self._fixed_creative_tool(project_id, payload["draft_version_id"])
        value, gaps = saved["input"], []
        tool = value["tool"]
        model = next((row for row in ResourceSettings(self.store).list()["configurations"] if row["id"] == value["model_id"]), None)
        if tool not in {"speech", "music_description", "ambience", "sfx", "video_edit", "video_extend"}:
            gaps.append(dict(code="tool_adapter_unavailable", message=TOOLS[tool][3] or "此工具使用原剪辑或镜头计划入口"))
        if not model or not model["enabled"] or not model["adapter_available"]:
            gaps.append(dict(code="tool_model_unavailable", message="请选择已启用且已接通的实际模型"))
        if not value["shot_id"]:
            gaps.append(dict(code="tool_shot_required", message="生成须关联本集明确镜头"))
        if not value["prompt"].strip():
            gaps.append(dict(code="tool_prompt_required", message="请填写提示词；配音须等于固定台词原文"))
        if gaps:
            return dict(ready=False, gaps=gaps, revision=self.get_project(project_id)["revision"])
        modality, purpose = TOOLS[tool][1:3]
        if model["modality"] != modality:
            raise ResourceError("模型模态与工具不匹配", "model_capability_mismatch")
        context = self.compile_shot_context(project_id, value["shot_id"], purpose=purpose)
        gaps.extend(context.get("gaps", []))
        raw = dict(prompt=value["prompt"], params=value["params"])
        if tool in {"music_description", "ambience", "sfx"} and value["style"].strip():
            raw["prompt"] += "\n" + value["style"].strip()
        if modality == "audio":
            raw.update(script_line_ids=value["script_line_ids"] if tool == "speech" else [], voice_media_id=(value["voice_media_id"] or None) if tool == "speech" else None)
        else:
            from vsc.production.video_operations import source_duration_ms, verify_operation_source
            if value["ranges"]:
                raise ResourceError("整片编辑/续接不接受局部重拍区间；请使用片段重拍输入草稿", "operation_range_unsupported")
            if not value["source_media_id"]:
                raise ResourceError("视频加工需要固定源片", "operation_source_invalid")
            source = self.get_media(project_id, value["source_media_id"])
            operation = "edit" if tool == "video_edit" else "extend"
            raw.update(operation=operation, source_media_id=source["id"], source_sha256=source["sha256"],
                source_duration_ms=source_duration_ms(source), duration_ms=source_duration_ms(source) if operation == "edit" else value["duration_ms"])
            verify_operation_source(self, project_id, dict(raw, shot_id=value["shot_id"], purpose=purpose))
        request = normalize_request(raw, value["shot_id"], purpose, modality)
        validate_capabilities(model, request, context)
        request["context_sha256"] = context["sha256"]
        if gaps:
            return dict(ready=False, gaps=gaps, revision=context["revision"])
        history, offset = [], 0
        while True:
            page = self.list_generation_jobs(project_id, offset=offset, limit=200)
            history.extend(page["items"])
            offset += len(page["items"])
            if offset >= page["total"] or not page["items"]:
                break
        candidate = max([row["candidate_no"] for row in history if row.get("shot_id") == value["shot_id"] and row.get("purpose") == purpose] + [-1]) + 1
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        run = dict(format="vsc.production-run/v1", project_id=project_id, approved_inputs=pins,
            creative_tool_draft=dict(id=artifact["id"], sha256=artifact["sha256"]), execution_policy=payload["execution_policy"],
            approved_media_inputs=[dict(media_id=raw["source_media_id"], sha256=raw["source_sha256"], role="operation_source")] if modality == "video" else [],
            series_batch=dict(jobs=[dict(task_key="tool:" + artifact["id"], model_id=model["id"], candidate_no=candidate, request=request)]))
        quote = self.preview_generation_quote(project_id, {"document": run})
        if quote["revision"] != context["revision"]:
            raise Conflict("预览期间输入已改变，请重新预览")
        run["generation_quote"] = quote["generation_quote"]
        run["operations"] = {row["operation"]: row["native_units"] for row in quote["generation_quote"]["jobs"]}
        from vsc.production.commerce_quote import attach_commerce_quote
        commerce=attach_commerce_quote(self,project_id,run,quote,payload)
        output = dict(artifact_key="creative-tool-run:" + artifact["id"], artifact_type="production-run", stage="production",
            document=run, dependency_ids=[row["id"] for row in pins], object_ids=[value["shot_id"]])
        return dict(ready=True, gaps=[], artifact=output, preview_sha256=fingerprint(output), revision=quote["revision"],
                    generation_quote=quote["generation_quote"], commerce_quote=commerce, needs_approval=True)

    def propose_creative_tool_run(self, project_id, payload, **kw):
        from vsc.assets.resource_service import ResourceError
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            raise ResourceError("保存运行方案需要固定预览摘要")
        return self._creative_tools().propose(project_id, payload, preview=self.preview_creative_tool_run, **kw)
