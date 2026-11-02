"""Independent shot/mode drafts, compiled into the original production run."""
from copy import deepcopy
import json

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.production.quotes import fingerprint


MODES = {
    "audio_speech": {"label": "独立朗读", "modality": "audio", "slots": {}, "purpose": "speech"},
    "audio_song": {"label": "歌词演唱歌曲", "modality": "audio", "slots": {}, "purpose": "song", "required_capabilities": ["lyrics"]},
    "audio": {"label": "音乐与音效", "modality": "audio", "slots": {}},
    "image": {"label": "分镜图像", "modality": "image", "slots": {"reference_image": "image"}},
    "text": {"label": "文生视频", "modality": "video", "slots": {}},
    "single": {"label": "单图生视频", "modality": "video", "slots": {"first_frame": "image"}},
    "first_last": {"label": "首尾帧", "modality": "video", "slots": {"first_frame": "image", "last_frame": "image"}},
    "multi": {"label": "多图参考", "modality": "video", "slots": {"first_frame": "image", "reference_image": "image"}},
    "omni": {"label": "全能参考", "modality": "video", "slots": {"reference_image": "image", "reference_video": "video", "reference_audio": "audio"},
        "purpose": "reference_to_video"},
    "digital_human": {"label": "数字人", "modality": "video", "slots": {"portrait": "image", "subject_mask": "image", "speech": "audio"},
        "purpose": "digital_human", "required_capabilities": ["reference_media", "reference_audio", "subject_mask"]},
    "motion": {"label": "动作模仿", "modality": "video", "slots": {"character": "image", "motion_video": "video"},
        "purpose": "motion_transfer", "required_capabilities": ["reference_media", "reference_video"]},
}
from vsc.production.image_tools import TOOLS as IMAGE_TOOLS, BLOCKED as IMAGE_BLOCKED, normalize_tool, tool_instruction, normalize_edit, EDIT_TYPE, OUTPUT_TYPE
for tool,(label,defaults) in IMAGE_TOOLS.items():
    MODES['image_'+tool]={'label':label,'modality':'image','slots':{'reference_image':'image'},'image_tool':tool,'tool_defaults':deepcopy(defaults),'tool_unavailable':IMAGE_BLOCKED.get(tool)}
MODES['image_inpaint'].update(slots={'operation_source':'image','operation_mask':'image'},purpose='image_edit',tool_unavailable=None)
MODES['image_watermark'].update(slots={'operation_source':'image','operation_mask':'image'},purpose='image_edit',tool_unavailable=None)
for native in ('panorama','upscale'):
    MODES['image_'+native].update(slots={'operation_source':'image'},purpose='image_edit',tool_unavailable=None)
MODES['video_depth']={'label':'灰度深度中间视频','modality':'video','slots':{'operation_source':'video'},'purpose':'depth'}
MODES['video_upgrade']={'label':'样片升级1080p','modality':'video','slots':{'operation_source':'video'},'purpose':'video_upgrade'}
MODES['depth_motion']={'label':'深度动作工作输入','modality':'video','slots':{'operation_source':'video','character':'image'},'purpose':'reference_to_video','internal':True}
MODES['image_subject_detect']={'label':'主体识别','modality':'image','slots':{'operation_source':'image'},'purpose':'image_edit','internal':True}
DRAFT_TYPE = "classic-production-draft"


def draft_key(shot_id, mode):
    return "classic:" + shot_id + ":" + mode


def normalize_draft(value):
    from vsc.production.resource_settings import safe_parameters
    fields = {"shot_id", "mode", "model_id", "purpose", "prompt", "lyrics", "duration_ms", "width", "height", "count", "params", "references", "tool_settings", "draft", "performance_prompt", "subject_selection"}
    if not isinstance(value, dict) or set(value) - fields or value.get("mode") not in MODES:
        raise ResourceError("经典制作草稿需要明确镜头、模式与已支持字段", "invalid_classic_draft")
    result = deepcopy(value)
    if 'draft' in result:
        if type(result['draft']) is not bool or (result['draft'] and (MODES[result['mode']]['modality']!='video' or result['mode'] in {'video_depth','video_upgrade','depth_motion','digital_human'})):
            raise ResourceError('样片开关仅用于原生视频生成','sample_options_invalid')
        if not result['draft']:result.pop('draft')
    for key, default, bound in (("prompt", "", 50000), ("purpose", "", 100), ("model_id", "", 100), ("shot_id", "", 100)):
        result.setdefault(key, default)
        if not isinstance(result[key], str) or len(result[key]) > bound:
            raise ResourceError("草稿文本字段格式不正确", "invalid_classic_draft")
    for key, default, low, high in (("duration_ms", 5000, 1, 3600000), ("width", 1080, 1, 16384),
                                  ("height", 1920, 1, 16384), ("count", 1, 1, 8)):
        result.setdefault(key, default)
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ResourceError("草稿数值超出允许范围：" + key, "invalid_classic_draft")
    params = result.setdefault("params", {})
    if not isinstance(params, dict) or len(params) > 40 or len(str(params)) > 20000:
        raise ResourceError("模型参数需要有界的 JSON 对象")
    result["params"] = safe_parameters(params)
    if result['mode'] == 'digital_human':
        from vsc.production.digital_human import avatar_params, performance_prompt, normalize_selection
        result['params'] = avatar_params(params)
        result['performance_prompt'] = performance_prompt(result.get('performance_prompt', ''))
        result['subject_selection'] = normalize_selection(result.get('subject_selection'))
        if result['count'] != 1:raise ResourceError('数字人每次固定一个主体与一个输出', 'avatar_inputs_invalid')
    elif 'subject_selection' in result or 'performance_prompt' in result:
        raise ResourceError('主体选择与表演提示只用于数字人模式', 'avatar_inputs_invalid')
    if result['mode'] == 'image_subject_detect':
        from vsc.production.digital_human import DETECTION_PROMPT, detection_params
        if result['prompt'] not in {'', DETECTION_PROMPT} or result['count'] != 1:
            raise ResourceError('每次主体识别只提交一个人物检测请求', 'subject_inputs_invalid')
        result['prompt'] = DETECTION_PROMPT; result['params'] = detection_params(params)
    if result['mode']=='audio_song':
        lyrics=result.get('lyrics')
        if not isinstance(lyrics,str) or not lyrics.strip() or len(lyrics)>5000:
            raise ResourceError('歌曲输入需要固定的 1–5000 字符歌词','song_lyrics_required')
        if len(result['prompt'])>1024 or params:
            raise ResourceError('歌曲风格最多 1024 字符，当前不接受扩展参数','song_inputs_unsupported')
    elif 'lyrics' in result:
        raise ResourceError('歌词字段仅用于歌词演唱模式','song_mode_required')
    tool=MODES[result['mode']].get('image_tool')
    if tool:result['tool_settings']=normalize_tool(tool,result.get('tool_settings',{}))
    elif result['mode'] in {'video_depth','depth_motion'}:
        from vsc.production.fal_tools import normalize_params
        settings=dict(result.get('tool_settings',{}));depth_model=settings.pop('depth_model_id',None)
        result['tool_settings']=normalize_params('depth',settings)
        if result['mode']=='depth_motion':
            if not isinstance(depth_model,str) or not depth_model:raise ResourceError('请固定深度中间模型','depth_model_required')
            result['tool_settings']['depth_model_id']=depth_model
    elif result['mode']=='audio_speech':
        import re
        settings=result.setdefault('tool_settings',{})
        if not isinstance(settings,dict) or set(settings)!={'speaker'} or not isinstance(settings['speaker'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',settings['speaker']):raise ResourceError('请选择已配置预置音色','speech_voice_required')
    elif result.get('tool_settings'):raise ResourceError('当前模式没有图像工具参数')
    refs = result.setdefault("references", [])
    if not isinstance(refs, list) or len(refs) > 50:
        raise ResourceError("草稿最多记录 50 个固定媒体引用")
    seen = set()
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) - {"role", "media_id", "sha256", "annotation_id", "annotation_source_id", "prompt_mention", "episode_asset_form_version_id"}
                or ref.get("role") not in MODES[result["mode"]]["slots"]
                or not isinstance(ref.get("media_id"), str) or not ref["media_id"]):
            raise ResourceError("参考用途与模式不匹配", "classic_reference_role")
        pair = (ref["role"], ref["media_id"])
        if pair in seen:
            raise ResourceError("同一用途不能重复添加同一媒体")
        if not isinstance(ref.get('prompt_mention',''),str) or len(ref.get('prompt_mention',''))>22000:raise ResourceError('参考提示引用格式无效')
        if ref.get('annotation_source_id') and not ref.get('annotation_id'):raise ResourceError('标注来源必须连接固定标注输出')
        seen.add(pair)
    return result


class ClassicProductionServiceMixin:
    def list_working_candidates(self, project_id, shot_id, output_kind, *, offset=0, limit=24, filter_kind='all'):
        if filter_kind not in {'all', 'favorites', 'local'} or output_kind not in {'image', 'video'} or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ResourceError('候选需要图像或视频类型和有效分页', 'invalid_candidate_page')
        return self.store.list_working_candidates(project_id, shot_id, output_kind, offset=offset, limit=limit, filter_kind=filter_kind)

    def _classic_shot(self, project_id, shot_id):
        tree = self.get_project_tree(project_id)
        node = next((n for n in tree["nodes"] if n["id"] == shot_id and n["kind"] == "shot"), None)
        if node is None:
            raise ResourceError("经典制作需要当前项目中的明确镜头", "shot_scope_mismatch")
        return tree, node

    def classic_production_options(self, project_id, shot_id):
        from vsc.production.resource_settings import ResourceSettings
        tree, shot = self._classic_shot(project_id, shot_id)
        drafts = self.store.list_classic_drafts(project_id, shot_id)
        models = ResourceSettings(self.store).list()["configurations"]
        # The settings projection already removes credential literals and exposes adapter status.
        fields = ("id", "name", "model_key", "model_version", "modality", "enabled", "capabilities",
                  "default_params", "adapter_available", "connection_status")
        media = self.list_resources(project_id, limit=200)
        from vsc.adapters.persistence.postgres.workbench_generation import subject_candidates
        with self.store.engine.connect() as conn:
            subjects = subject_candidates(self.store, conn, project_id, shot_id)
        if self.get_project(project_id)["revision"] != tree["revision"]:
            raise Conflict("制作资料读取期间已改变，请刷新")
        return {"project_id": project_id, "shot": shot, "revision": tree["revision"], "modes": deepcopy(MODES),
            "sibling_shots":[row for row in tree["nodes"] if row["kind"]=="shot" and row["parent_id"]==shot["parent_id"]], "models": [{k: row.get(k) for k in fields} for row in models if row["modality"] in {"image", "video"}],
            "drafts": drafts["items"], "subject_candidates": subjects, "reference_edits": self.store.list_classic_reference_edits(project_id,shot_id)["items"], "media": [{k: row.get(k) for k in ("id", "name", "modality", "sha256", "width", "height", "duration_ms")}
                for row in media["items"]], "media_total": media["total"]}

    def _classic_document(self, project_id, value):
        document = normalize_draft(value)
        self._classic_shot(project_id, document["shot_id"])
        for ref in document["references"]:
            media = self.store.get_media(project_id, ref["media_id"])
            if media["modality"] != MODES[document["mode"]]["slots"][ref["role"]]:
                raise ResourceError("参考媒体类型与插槽不匹配", "classic_reference_modality")
            if ref.get("sha256", media["sha256"]) != media["sha256"]:
                raise Conflict("参考媒体摘要不匹配", "classic_reference_changed")
            ref["sha256"] = media["sha256"]
            if ref.get('annotation_id'):
                artifact=self.get_artifact_version(project_id,ref['annotation_id']);output=json.loads(artifact['document'])
                if artifact['artifact_type']!=OUTPUT_TYPE or output['shot_id']!=document['shot_id'] or ref.get('annotation_source_id',output['source_media_id'])!=output['source_media_id'] or not any(row['media_id']==ref['media_id'] for row in output['outputs']):raise ResourceError('标注引用不属于此镜头固定输出','classic_annotation_mismatch')
        settings=document.get('tool_settings',{})
        if document['mode'] == 'digital_human' and document.get('subject_selection'):
            from vsc.adapters.persistence.postgres.workbench_generation import subject_sources
            from vsc.production.digital_human import validate_mask_bytes
            with self.store.engine.connect() as conn:
                fixed = subject_sources(self.store, conn, project_id, document)
            if self.storage is None:raise ResourceError('主体选择需要原图和mask真实字节', 'storage_unavailable')
            source = self.get_media(project_id, fixed['source_media_id']); mask = self.get_media(project_id, fixed['mask_media_id'])
            self._verify_media(project_id, source['id'], source['sha256'])
            location = next((r for r in mask['locations'] if r['storage'] == 'local' and r.get('available')), None)
            if not location:raise ResourceError('主体mask本机字节不可用', 'media_unavailable')
            validate_mask_bytes(self.storage.read(location['object_key'], mask['sha256']), (source['width'], source['height']))
        elif document['mode'] == 'digital_human' and any(r['role'] == 'subject_mask' for r in document['references']):
            raise ResourceError('主体mask须来自当前检测或手绘导出', 'subject_selection_required')
        if settings.get('mask_media_id'):
            mask=self.store.get_media(project_id,settings['mask_media_id'])
            if mask['modality']!='image' or settings.get('mask_sha256') and settings['mask_sha256']!=mask['sha256']:raise Conflict('遮罩身份或摘要不符')
            settings['mask_sha256']=mask['sha256']
        if document['mode'] in {'image_inpaint','image_watermark'} and any(r['role']=='operation_mask' for r in document['references']):
            from vsc.adapters.persistence.postgres.workbench_generation import inpaint_sources
            from vsc.adapters.providers.openai_image import validate_inpaint_bytes
            with self.store.engine.connect() as conn:inpaint_sources(self.store,conn,project_id,document)
            if self.storage is None:raise ResourceError('局部重绘需要受控原图与遮罩字节','storage_unavailable')
            contents={}
            for ref in document['references']:
                media=self.store.get_media(project_id,ref['media_id'])
                location=next((row for row in media['locations'] if row['storage']=='local' and row.get('available')),None)
                if not location:raise ResourceError('原图或遮罩没有可用本地字节','media_unavailable')
                contents[ref['role']]=self.storage.read(location['object_key'],ref['sha256'])
            validate_inpaint_bytes(contents['operation_source'],contents['operation_mask'])
        return document

    def save_classic_draft(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"document", "base_draft_id"}:
            raise ResourceError("保存需要模式草稿与所见草稿版本")
        return self.store.save_classic_draft(project_id, payload, build_document=self._classic_document, **kw)

    def preview_classic_run(self, project_id, payload, *, working=False):
        from vsc.production.resource_settings import ResourceSettings
        from vsc.production.run_authorization import normalize_request
        from vsc.production.run_policy import policy_errors
        if not isinstance(payload, dict) or set(payload)-{"commerce_account_actor"} != {"draft_version_id", "execution_policy"}:
            raise ResourceError("预览需要已保存草稿与固定执行时限")
        errors = policy_errors(payload["execution_policy"])
        if payload["execution_policy"] is None or errors:
            raise ResourceError("；".join(errors) or "需要固定执行时限")
        artifact = self.get_artifact_version(project_id, payload["draft_version_id"])
        if artifact["artifact_type"] != DRAFT_TYPE:
            raise ResourceError("该版本不是经典制作草稿", "classic_draft_required")
        document = self._classic_document(project_id, json.loads(artifact["document"]))
        if document['mode']=='depth_motion':raise ResourceError('深度动作须从原工具页确认两阶段报价','depth_run_required')
        mode = MODES[document["mode"]]
        model = next((row for row in ResourceSettings(self.store).list()["configurations"]
                      if row["id"] == document["model_id"]), None)
        gaps = []
        def gap(code, message):
            gaps.append({"code": code, "message": message})
        tool=mode.get('image_tool')
        if document['mode'] == 'digital_human' and not document.get('subject_selection'):
            return {'project_id':project_id,'revision':self.get_project(project_id)['revision'],'ready':False,
                'gaps':[{'code':'subject_selection_required','message':'请选择当前图像的讲话主体，或手绘白色主体区域。'}],
                'draft_version_id':artifact['id'],'draft_sha256':artifact['sha256']}
        if tool in {'inpaint','watermark'} and (len(document['references'])!=2 or not document.get('tool_settings',{}).get('mask_export_id')):
            return {'project_id':project_id,'revision':self.get_project(project_id)['revision'],'ready':False,'gaps':[{'code':'inpaint_inputs_required','message':'请从原图绘制并固定修改区域。'}],'draft_version_id':artifact['id'],'draft_sha256':artifact['sha256']}
        if tool and mode.get('tool_unavailable'):gap('image_tool_unavailable',mode['tool_unavailable'])
        if tool and not document['references']:gap('image_tool_source_required','此工具需要显式固定人物或场景参考图。')
        if tool and document['purpose']!='image_edit':gap('image_tool_purpose','图像工具必须选择图像编辑用途。')
        operation='inpaint' if tool=='watermark' else tool if tool in {'inpaint','panorama','upscale'} else 'depth' if document['mode']=='video_depth' else 'subject_detect' if document['mode']=='image_subject_detect' else None
        if operation and model and operation not in model['capabilities'].get('video_operations' if operation=='depth' else 'image_operations',[]):gap('model_capability_mismatch','此模型没有当前原生处理能力。')
        if tool=='watermark' and document['tool_settings'].get('rights_confirmed') is not True:gap('watermark_rights_required','请明确确认有权处理此图，并在原图圈选水印。')
        if operation in {'panorama','upscale','depth'} and document['params']:gap('fal_parameters_invalid','原生处理参数须在本工具参数区固定。')
        if mode.get("unsupported"):
            gap("classic_mode_unavailable", mode["unsupported"])
        if not model or not model["enabled"] or not model.get("adapter_available"):
            gap("classic_model_unavailable", "请选择已启用且已接通的实际模型；已有输入已保存在草稿。")
        if not document["prompt"].strip() and document['mode'] != 'digital_human':
            gap("prompt_missing", "请填写当前模式的提示词。")
        if document["count"] > payload["execution_policy"]["max_attempts_per_purpose"]:
            gap("classic_attempt_limit", "候选数量超过本次同用途尝试上限，请修改草稿或执行范围。")
        if model and (model["modality"] != mode["modality"] or document["purpose"] not in model["capabilities"].get("purposes", [])):
            gap("model_capability_mismatch", "所选模型未声明该模态与用途。")
        if mode.get('purpose') and document['purpose'] != mode['purpose']:
            gap('model_capability_mismatch', '当前模式需要模型声明对应用途：' + mode['label'])
        if model and any(not model['capabilities'].get(capability) for capability in mode.get('required_capabilities', [])):
            gap('model_capability_mismatch', '所选模型没有当前模式需要的媒体驱动能力。')
        refs = document["references"]
        if (operation in {'panorama','upscale','depth','subject_detect'} or document['mode']=='video_upgrade') and len(refs)!=1:gap('classic_reference_count','原生处理需要唯一固定原件。')
        by_role = {role: [r["media_id"] for r in refs if r["role"] == role] for role in mode["slots"]}
        for role in ("first_frame", "last_frame", "portrait", "subject_mask", "speech", "character", "motion_video"):
            if role in by_role and (len(by_role[role]) > 1 or role not in {"first_frame", "last_frame"} and len(by_role[role]) != 1
                                   or role == "first_frame" and document["mode"] in {"single", "first_last"} and not by_role[role]):
                gap("classic_reference_count", "该模式需要唯一的 " + role + " 固定输入。")
        if document["mode"] == "multi" and len(refs) < 2:
            gap("classic_reference_count", "多图参考至少需要两张固定图片。")
        image_count = sum(mode['slots'][ref['role']] == 'image' for ref in refs)
        if model and image_count > model["capabilities"].get("max_reference_images", image_count):
            gap("model_capability_mismatch", "图片数量超过所选模型声明的上限。")
        if working:
            from vsc.adapters.persistence.postgres.workbench_generation import working_context
            with self.store.engine.connect() as conn:
                project = self.store._project(conn, project_id)
                context = working_context(self.store, conn, project, artifact["id"])
            if self.storage is not None:
                for reference in context["media"]:
                    self._verify_media(project_id, reference["media_id"], reference["sha256"])
        else:
            context = self.compile_shot_context(project_id, document["shot_id"], purpose=document["purpose"] or "video_clip")
        gaps.extend(context.get("gaps", []))
        selected = {item["media_id"]: item for item in context.get("media", [])}
        for ref in refs:
            if ref["media_id"] not in selected or selected[ref["media_id"]]["sha256"] != ref["sha256"]:
                gap("reference_not_selected", "参考素材尚未在当前镜头选为可用用途，请从候选与输入确认。")
        if gaps:
            return {"project_id": project_id, "revision": context["revision"], "ready": False, "gaps": gaps,
                    "draft_version_id": artifact["id"], "draft_sha256": artifact["sha256"]}
        prompt=document['prompt']
        for index,ref in enumerate(refs,1):
            prompt=prompt.replace('[[ref:'+ref['media_id']+']]',{'first_frame':'首帧','last_frame':'尾帧'}.get(ref['role'],'固定参考'+str(index)))
        if any(ref.get('annotation_id') for ref in refs):prompt+='\n标注图的覆盖记号用于表达修改要求；请依据修改说明理解，不把记号本身作为最终画面元素。'
        if tool and tool not in {'inpaint','watermark','panorama','upscale'}:prompt='\n'.join(part for part in [prompt,tool_instruction(tool,document['tool_settings'])] if part)
        if tool=='watermark':prompt+='\n仅重建已圈选水印区域，保持其他主体内容。用户已确认有权处理此来源。'
        if document['mode'] == 'motion':
            prompt += '\n保持固定角色形象，参考动作视频中的动作顺序、节奏与身体运动，不替换角色身份。'
        logical = {"prompt": prompt, "params": document["params"],
                   "reference_media_ids": by_role.get("reference_image", []) + by_role.get('portrait', []) + by_role.get('character', [])}
        if document['mode']=='audio_song':logical['lyrics']=document['lyrics']
        if mode["modality"] == "image":
            logical.update(width=document["width"], height=document["height"])
            if tool in {'inpaint','watermark'}:
                for name in ('source','mask'):
                    ref=next(r for r in refs if r['role']=='operation_'+name)
                    logical[name+'_media_id']=ref['media_id'];logical[name+'_sha256']=ref['sha256']
                logical['operation']='inpaint'
            elif tool in {'panorama','upscale'}:
                from vsc.production.fal_tools import image_operation_fields
                logical.update(image_operation_fields(tool,self.get_media(project_id,refs[0]['media_id']),document['tool_settings']))
            elif document['mode'] == 'image_subject_detect':
                from vsc.production.digital_human import detection_request_fields
                logical.update(detection_request_fields(self.get_media(project_id,refs[0]['media_id']),document['params']))
        elif mode["modality"] == "video":
            if document.get("draft"):logical["draft"]=True
            logical.update(duration_ms=document["duration_ms"],
                first_frame_media_id=next(iter(by_role.get("first_frame", [])), None),
                last_frame_media_id=next(iter(by_role.get("last_frame", [])), None),
                reference_audio_media_ids=by_role.get('reference_audio', []) + by_role.get('speech', []),
                reference_video_media_ids=by_role.get('reference_video', []) + by_role.get('motion_video', []))
            if document['mode']=='video_depth':
                from vsc.production.fal_tools import depth_operation_fields
                logical.update(depth_operation_fields(self.get_media(project_id,refs[0]['media_id']),document['tool_settings']))
            if document['mode']=='video_upgrade':
                from vsc.production.video_samples import upgrade_request
                logical.update(upgrade_request(self.get_media(project_id,refs[0]['media_id'])))
            if document['mode'] == 'digital_human':
                from vsc.production.digital_human import avatar_request_fields
                logical.update(avatar_request_fields(self.get_media(project_id,by_role['portrait'][0]),
                    self.get_media(project_id,by_role['speech'][0]), self.get_media(project_id,by_role['subject_mask'][0]),
                    document['performance_prompt'], document['params']))
        request = normalize_request(logical, document["shot_id"], document["purpose"], mode["modality"])
        request["context_sha256"] = context["sha256"]
        candidate = self.store.next_classic_candidate(project_id, document['shot_id'], document['purpose'])
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        run = {"format": "vsc.production-run/v1", "project_id": project_id, "approved_inputs": pins,
               "classic_draft": {"id": artifact["id"], "sha256": artifact["sha256"], "mode": document["mode"]},
               "approved_media_inputs": deepcopy(refs), "execution_policy": payload["execution_policy"],
               "series_batch": {"jobs": [{"task_key": "classic:" + artifact["id"] + ":" + str(i),
                   "model_id": model["id"], "candidate_no": candidate + i, "request": request}
                   for i in range(document["count"])]}}
        if working:
            run["workbench_draft"] = {"id": artifact["id"], "sha256": artifact["sha256"]}
        quote = self.preview_generation_quote(project_id, {"document": run})
        if quote["revision"] != context["revision"]:
            raise Conflict("制作输入已变化，请重新预览")
        run["generation_quote"] = quote["generation_quote"]
        run["operations"] = {row["operation"]: row["native_units"] for row in quote["generation_quote"]["jobs"]}
        from vsc.production.commerce_quote import attach_commerce_quote
        commerce=attach_commerce_quote(self,project_id,run,quote,payload)
        output = {"artifact_key": "classic-run:" + artifact["id"], "artifact_type": "production-run", "stage": "production",
                  "document": run, "dependency_ids": [row["id"] for row in pins], "object_ids": [document["shot_id"]]}
        if working:
            output.update(artifact_key="workbench-run:" + artifact["id"],
                          artifact_type="workbench-generation-run", stage="workspace")
        return {"project_id": project_id, "revision": quote["revision"], "ready": True, "gaps": [], "artifact": output,
                "preview_sha256": fingerprint(output), "generation_quote": quote["generation_quote"], "commerce_quote":commerce,
                "needs_approval": not working, "needs_confirmation": working}

    def preview_workbench_generation(self, project_id, payload):
        return self.preview_classic_run(project_id, payload, working=True)

    def generate_workbench(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            raise ResourceError("生成需要已保存输入与当前报价", "working_preview_required")
        return self.store.generate_workbench(project_id, payload,
            build_preview=self.preview_workbench_generation, **kw)

    def propose_classic_run(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        if set(payload) != {"request", "preview_sha256"}:
            raise ResourceError("保存运行方案需要所预览请求与固定摘要")
        return self.store.propose_classic_run(project_id, payload, build_preview=self.preview_classic_run, **kw)

    def save_classic_reference_edit(self, project_id, payload, **kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'shot_id','mode','document','base_edit_id'} or payload['mode'] not in MODES:raise ResourceError('标注保存需要镜头、模式与所见版本')
        self._classic_shot(project_id,payload['shot_id']);document=normalize_edit(payload['document']);media=self.store.get_media(project_id,document['source_media_id'])
        if media['sha256']!=document['source_sha256'] or media['modality']!=document['source_modality']:raise Conflict('标注源媒体身份或摘要不匹配')
        if document['source_modality']=='video' and (not media.get('duration_ms') or document['time_ms']>=media['duration_ms']):raise ResourceError('标注时码必须位于原视频内','reference_time_outside')
        return self.store.save_classic_reference_edit(project_id,dict(payload,document=document),**kw)

    def export_classic_reference_edit(self, project_id, payload, **kw):
        self._validate_write(payload,**kw)
        if set(payload)!={'edit_version_id'}:raise ResourceError('导出必须固定已保存标注版本')
        if self.storage is None:raise ResourceError('参考图导出需要受控素材存储','storage_unavailable')
        def build(document):
            import io
            from vsc.production.image_tools import render_reference
            media=self.store.get_media(project_id,document['source_media_id']);self._verify_media(project_id,media['id'],document['source_sha256'])
            location=next((r for r in media['locations'] if r['storage']=='local' and r.get('available')),None)
            if not location:raise ResourceError('源媒体缺少可用本地副本')
            path=self.storage.verify(location['object_key'],document['source_sha256']);output=[]
            for item in render_reference(path,document):
                staged=self.storage.stage_upload(io.BytesIO(item['bytes']),'reference-'+item['role']+'.png')
                output.append({'role':item['role'],'media':self.storage.commit_upload(staged['staged_upload'])})
            return output
        return self.store.export_classic_reference_edit(project_id,payload,build=build,**kw)

    def change_classic_shots(self, project_id, payload, **kw):
        self._validate_write(payload,**kw)
        if payload.get('action') not in {'create','reorder'} or set(payload)-{'action','parent_id','title','shot_ids'}:raise ResourceError('镜号操作无效')
        return self.store.change_classic_shots(project_id,payload,**kw)

    def classic_candidate_configuration(self, project_id, shot_id, media_id):
        self._classic_shot(project_id,shot_id)
        source=self.store.classic_candidate_configuration(project_id,shot_id,media_id)
        if not source:return {'available':False,'reason':'此候选没有本镜头原生成任务；不能猜测配置。'}
        if source['request_payload'].get('operation') in {'inpaint','draft_upgrade','panorama'} or source['request_payload'].get('draft') is True:
            run=self.get_artifact_version(project_id,source['run_version_id'])
            fixed=json.loads(run['document']).get('workbench_draft')
            if not fixed:return {'available':False,'reason':'此局部重绘结果缺少固定工作草稿。'}
            original=self.get_artifact_version(project_id,fixed['id'])
            if original['sha256']!=fixed['sha256']:raise Conflict('候选原配置摘要不符')
            result={'available':True,'source_job_id':source['id'],'document':self._classic_document(project_id,json.loads(original['document']))}
            if source['request_payload'].get('operation') == 'panorama':
                if result['document']['mode'] != 'image_panorama':
                    return {'available':False,'reason':'原全景任务的固定工作稿模式不符。'}
                result['source_operation']='panorama'
            if source['request_payload'].get('draft') is True:
                from vsc.production.resource_settings import ResourceSettings
                from vsc.production.video_samples import upgrade_request, sample_deadline
                media=self.get_media(project_id,media_id)
                targets=[row for row in ResourceSettings(self.store).list()['configurations'] if row['provider_id']==source['provider_id'] and row['enabled'] and row.get('adapter_available') and row['default_params'].get('resolution')=='1080p' and row['capabilities'].get('video_draft') is True and 'draft_upgrade' in row['capabilities'].get('video_operations',[])]
                fixed=upgrade_request(media)
                result['sample_upgrade']={'expires_at':sample_deadline((source.get('raw_response') or {}).get('created_at')).isoformat(),
                    'model_ids':[row['id'] for row in targets], 'document':normalize_draft(dict(shot_id=shot_id,mode='video_upgrade',purpose='video_upgrade',model_id=targets[0]['id'] if targets else '',
                    prompt=fixed['prompt'],duration_ms=media['duration_ms'],count=1,params={},references=[dict(role='operation_source',media_id=media_id,sha256=media['sha256'])]))}
            return result
        request=source['request_payload'];mode='image' if source['modality']=='image' else 'first_last' if request.get('last_frame_media_id') else 'single' if request.get('first_frame_media_id') else 'text'
        refs=[{'role':role,'media_id':request[field]} for role,field in [('first_frame','first_frame_media_id'),('last_frame','last_frame_media_id')] if request.get(field)]
        refs.extend({'role':'reference_image','media_id':mid} for mid in request.get('reference_media_ids',[]))
        if mode=='single' and any(r['role']=='reference_image' for r in refs):mode='multi'
        if mode=='text' and refs:mode='multi'
        document=normalize_draft(dict(shot_id=shot_id,mode=mode,model_id=source['model_id'],purpose=source['purpose'],prompt=request.get('prompt',''),duration_ms=request.get('duration_ms',5000),width=request.get('width',1080),height=request.get('height',1920),count=1,params=request.get('params',{}),references=refs))
        return {'available':True,'source_job_id':source['id'],'document':self._classic_document(project_id,document)}
