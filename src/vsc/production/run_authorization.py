"""Pure authorization of a frozen logical request against its approved run."""
import json
from vsc.assets.resource_service import ResourceError


def normalize_request(request, shot_id, purpose, modality, asset_id=None):
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ResourceError("逻辑请求需要非空prompt", "invalid_generation_request")
    if modality=='video' and 'draft' in request:
        if type(request['draft']) is not bool:raise ResourceError('样片开关须为布尔值','sample_options_invalid')
        if request['draft'] is False:request={k:v for k,v in request.items() if k!='draft'}
    if modality == 'video' and purpose != 'digital_human':
        request = {key: value for key, value in request.items() if not (
            key in {'subject_mask_media_id', 'subject_mask_sha256'} and value is None)}
    if modality in {"video", "image"} and not request.get("operation"):
        request = {key: value for key, value in request.items() if not (
            key in {"operation", "source_media_id", "source_sha256", "source_duration_ms", "mask_media_id", "mask_sha256", "subject_mask_media_id", "subject_mask_sha256"} and value is None)}
    base = {"shot_id": shot_id, "purpose": purpose, "modality": modality,
            "reference_media_ids": [], "params": {}}
    if asset_id is not None:
        if shot_id is not None or modality != "image":
            raise ResourceError("资产首参考任务只支持图像且不能同时指定镜头", "request_scope_mismatch")
        base["asset_id"] = asset_id
    if modality == "image":
        base.update(width=1080, height=1920)
        if request.get('operation'):
            base.update(operation=None,source_media_id=None,source_sha256=None,mask_media_id=None,mask_sha256=None)
    elif modality == "video":
        base.update(duration_ms=5000, first_frame_media_id=None, last_frame_media_id=None,
                    reference_audio_media_ids=[], reference_video_media_ids=[], keyframes=[])
        if 'draft' in request:base['draft']=False
        if purpose == 'digital_human':
            base.update(subject_mask_media_id=None, subject_mask_sha256=None)
        if request.get("operation"):
            base.update(operation=None, source_media_id=None, source_sha256=None, source_duration_ms=None)
    elif modality == "audio":
        base.update(script_line_ids=[], voice_media_id=None)
        if purpose == 'song':base['lyrics'] = None
    else:
        raise ResourceError("未知请求模态")
    allowed = set(base) | {"prompt", "format", "context_sha256"}
    if asset_id is not None:
        allowed.add("spec_version_id")
        if "spec_version_id" in request and (not isinstance(request["spec_version_id"], str) or not request["spec_version_id"]):
            raise ResourceError("固定资产变体须为非空规格ID", "invalid_generation_request")
    if any(key not in allowed for key in request):
        raise ResourceError("逻辑请求含未知字段，请把模型参数放入params", "invalid_generation_request")
    base.update({k: v for k, v in request.items() if k not in {"format", "context_sha256"}})
    if (base["shot_id"], base["purpose"], base["modality"]) != (shot_id, purpose, modality):
        raise ResourceError("请求的镜头、用途或模态归属不一致", "request_scope_mismatch")
    if base.get("asset_id") != asset_id:
        raise ResourceError("请求的资产身份不一致", "request_scope_mismatch")
    if not isinstance(base["params"], dict) or any(k in base["params"] for k in ("provider", "model", "external_task_id", "base_url", "auth_ref")):
        raise ResourceError("逻辑参数不能混入供应商连接信息", "provider_parameter_leak")
    if not isinstance(base["reference_media_ids"], (tuple, list)):
        raise ResourceError("reference_media_ids必须是列表")
    base["reference_media_ids"] = list(base["reference_media_ids"])
    if modality == 'image' and base.get('operation'):
        if base['operation'] not in {'inpaint','panorama','upscale','subject_detect'} or purpose!='image_edit' or asset_id or base['reference_media_ids']:
            raise ResourceError('独立遮罩编辑需要明确镜头、原图和遮罩，不混入普通参考','invalid_image_operation')
        for name in (('source','mask') if base['operation']=='inpaint' else ('source',)):
            identifier,digest=base[name+'_media_id'],base[name+'_sha256']
            if not isinstance(identifier,str) or not identifier or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise ResourceError('原图和遮罩需要固定身份及摘要','invalid_image_operation')
        if base['operation']=='inpaint' and base['source_media_id']==base['mask_media_id']:
            raise ResourceError('原图与遮罩必须分别固定','invalid_image_operation')
        if base['operation'] in {'panorama','upscale'}:
            from vsc.production.fal_tools import normalize_params
            if base['mask_media_id'] or base['mask_sha256']:raise ResourceError('全景与超分不接受遮罩','invalid_image_operation')
            base['params']=normalize_params(base['operation'],base['params'])
        if base['operation'] == 'subject_detect':
            from vsc.production.digital_human import DETECTION_PROMPT, detection_params
            if base['prompt'] != DETECTION_PROMPT or base['mask_media_id'] or base['mask_sha256']:
                raise ResourceError('主体识别只接受固定原图及人物识别用途', 'subject_inputs_invalid')
            base['params'] = detection_params(base['params'])
    if modality == 'audio' and purpose == 'song':
        if not isinstance(base['lyrics'],str) or not base['lyrics'].strip() or len(base['lyrics'])>5000:
            raise ResourceError('歌词演唱需要固定的 1–5000 字符歌词','song_lyrics_required')
        if len(base['prompt'])>1024 or base['params'] or base['script_line_ids'] or base['voice_media_id'] or base['reference_media_ids']:
            raise ResourceError('歌曲风格最多 1024 字符；当前歌曲路线不接受参考音色或扩展参数','song_inputs_unsupported')
    if modality == "video":
        if purpose == 'digital_human':
            from vsc.production.digital_human import avatar_params, audio_duration, performance_prompt
            base['params'] = avatar_params(base['params']); performance_prompt(base['prompt'])
            audio_duration(base['duration_ms'], base['params'])
            if (not isinstance(base['subject_mask_media_id'], str) or not base['subject_mask_media_id'] or
                    not isinstance(base['subject_mask_sha256'], str) or len(base['subject_mask_sha256']) != 64 or
                    any(c not in '0123456789abcdef' for c in base['subject_mask_sha256']) or base.get('draft') or base.get('operation')):
                raise ResourceError('数字人需要固定主体mask，不能作为样片或视频加工', 'subject_selection_required')
        if base.get("operation"):
            operation = base["operation"]
            sha = base["source_sha256"]
            if operation not in {"edit", "extend", "depth", "draft_upgrade"} or not isinstance(base["source_media_id"], str) or not base["source_media_id"]:
                raise ResourceError("加工需要明确edit/extend与固定source_media_id", "invalid_video_operation")
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ResourceError("加工需要固定source_sha256", "invalid_video_operation")
            if type(base["source_duration_ms"]) is not int or base["source_duration_ms"] <= 0:
                raise ResourceError("加工需要真实source_duration_ms", "invalid_video_operation")
            if base.get('draft') or (base["params"] and operation not in {'depth','draft_upgrade'}) or any(base.get(key) for key in ("first_frame_media_id", "last_frame_media_id", "reference_media_ids", "reference_audio_media_ids", "reference_video_media_ids", "keyframes")):
                raise ResourceError("加工源模式不能混入生成参数或其他参考", "invalid_video_operation")
            if operation == 'draft_upgrade':
                from vsc.production.video_samples import UPGRADE_PROMPT, upgrade_options
                if purpose!='video_upgrade' or base['prompt']!=UPGRADE_PROMPT or base['duration_ms']!=base['source_duration_ms']:
                    raise ResourceError('升级须沿用原样片时长与内容','sample_options_invalid')
                base['params']=upgrade_options(base['params'])
            elif operation == 'depth':
                from vsc.production.fal_tools import DEPTH_PROMPT, normalize_params
                if purpose!='depth' or base['prompt']!=DEPTH_PROMPT or base['duration_ms']!=base['source_duration_ms']:raise ResourceError('深度估计须固定原时长及处理说明','invalid_video_operation')
                base['params']=normalize_params('depth',base['params'])
            elif operation == "edit":
                if "duration_ms" in request and request["duration_ms"] != base["source_duration_ms"]:
                    raise ResourceError("编辑时长跟随源片，不允许另设", "invalid_video_operation")
                base["duration_ms"] = base["source_duration_ms"]
            elif type(base["duration_ms"]) is not int or base["duration_ms"] % 1000 or not 2000 <= base["duration_ms"] <= 10000:
                raise ResourceError("续接须新增2–10整秒", "invalid_video_operation")
        audio_refs = base["reference_audio_media_ids"]
        if not isinstance(audio_refs, (tuple, list)) or any(not isinstance(x, str) or not x for x in audio_refs):
            raise ResourceError("reference_audio_media_ids必须是媒体ID列表")
        base["reference_audio_media_ids"] = list(audio_refs)
        video_refs = base['reference_video_media_ids']
        if not isinstance(video_refs, (tuple, list)) or any(not isinstance(x, str) or not x for x in video_refs):
            raise ResourceError('reference_video_media_ids必须是媒体ID列表')
        base['reference_video_media_ids'] = list(video_refs)
        keyframes = base["keyframes"]
        if not isinstance(keyframes, (tuple, list)) or any(
                not isinstance(item, (tuple, list)) or len(item) != 2
                or not isinstance(item[0], str) or not item[0]
                or isinstance(item[1], bool) or not isinstance(item[1], (int, float))
                for item in keyframes):
            raise ResourceError("keyframes必须是[媒体ID, 秒]对列表")
        base["keyframes"] = [[item[0], float(item[1])] for item in keyframes]
    return base


def authorize_run(run, run_type, context, logical, candidate_no, task_outputs=None, model_id=None):
    if run_type not in {"production-run", "vsc.production_run", "workbench-generation-run"} or not isinstance(run, dict):
        raise ResourceError("任务必须绑定正式production-run类型", "invalid_production_run")
    if run_type == "workbench-generation-run" and run.get("workbench_draft") != context.get("working_draft"):
        raise ResourceError("工作生成输入没有固定到本次草稿", "working_input_mismatch")
    inputs = run.get("approved_inputs")
    if not isinstance(inputs, list) or any(not isinstance(x, dict) for x in inputs):
        raise ResourceError("run必须明确列出approved_inputs", "run_inputs_missing")
    pinned = {(x.get("id"), x.get("sha256")) for x in inputs}
    required = {(x["id"], x["sha256"]) for x in context["artifacts"]}
    if not required <= pinned:
        raise ResourceError("镜头所需固定版本没有全部获run授权", "run_inputs_mismatch")
    if logical.get("operation"):
        sources = run.get("approved_media_inputs", [])
        expected_source = {"media_id": logical["source_media_id"], "sha256": logical["source_sha256"], "role": "operation_source"}
        if expected_source not in sources:
            raise ResourceError("加工源片SHA没有得到run明确固定授权", "run_source_unauthorized")
        if logical.get('operation')=='inpaint' and {'media_id':logical['mask_media_id'],'sha256':logical['mask_sha256'],'role':'operation_mask'} not in sources:
            raise ResourceError('独立遮罩SHA没有得到run明确固定授权','run_source_unauthorized')
    if logical.get('subject_mask_media_id') and {'media_id':logical['subject_mask_media_id'],'sha256':logical['subject_mask_sha256'],'role':'subject_mask'} not in run.get('approved_media_inputs',[]):
        raise ResourceError('主体mask没有得到run明确固定授权','run_source_unauthorized')
    jobs = run.get("series_batch", {}).get("jobs", run.get("jobs", []))
    if not isinstance(jobs, list):
        raise ResourceError("run必须明确列出jobs")
    bounded = any(isinstance(job, dict) and 'task_key' in job for job in jobs)
    if bounded:
        from vsc.production.bounded import graph_errors
        errors = graph_errors(run)
        if errors:
            raise ResourceError("；".join(errors), "invalid_task_graph")
    matched = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("candidate_no", 0) != candidate_no:
            continue
        request = job.get("request", job.get("request_payload"))
        if not isinstance(request, dict):
            continue
        target = request.get("shot_id", job.get("shot_id"))
        asset = request.get("asset_id", job.get("asset_id"))
        purpose = request.get("purpose", job.get("purpose"))
        modality = request.get("modality", job.get("modality"))
        if (target, asset, purpose, modality) != (logical["shot_id"], logical.get("asset_id"), logical["purpose"], logical["modality"]):
            continue
        if bounded:
            if job.get('model_id') != model_id:
                continue
            from vsc.production.bounded import resolve_request
            request = resolve_request(job, context, task_outputs or {})
        expected = normalize_request(request, target, purpose, modality, asset_id=asset)
        if expected == logical and request.get("context_sha256", context["sha256"]) == context["sha256"]:
            matched.append(job)
    if len(matched) != 1:
        raise ResourceError("镜头、用途、候选与完整请求没有得到run唯一授权", "run_job_unauthorized")
    return pinned


def validate_capabilities(model, logical, context):
    caps = model["capabilities"]
    if not isinstance(caps, dict) or logical["purpose"] not in caps.get("purposes", []):
        raise ResourceError("模型未声明支持该用途", "model_capability_mismatch")
    refs = {m["media_id"]: m for m in context["media"]}
    if any(ref not in refs for ref in logical["reference_media_ids"]):
        raise ResourceError("请求引用了未获选的素材", "reference_not_selected")
    if logical["modality"] in {"image", "video"} and any(
            refs[ref]["role"] in {"reference_audio", "voice_sample", "speech", "reference_video", "motion_video"} for ref in logical["reference_media_ids"]):
        raise ResourceError("音视频参考必须使用各自的固定输入类型", "reference_modality_mismatch")
    if logical["reference_media_ids"] and not caps.get("reference_media"):
        raise ResourceError("模型不支持参考素材", "model_capability_mismatch")
    modality = logical["modality"]
    if modality == "image":
        if logical.get('operation'):
            if logical['operation'] not in caps.get('image_operations',[]):
                raise ResourceError('模型或固定工作稿未声明独立遮罩编辑','model_capability_mismatch')
            fixed=context.get('working_inpaint') if logical['operation']=='inpaint' else context.get('working_native_media')
            if not fixed:raise ResourceError('原生图像操作须使用固定工作稿','model_capability_mismatch')
            for name in (('source','mask') if logical['operation']=='inpaint' else ('source',)):
                ref=refs.get(logical[name+'_media_id'])
                if not ref or ref['role']!='operation_'+name or ref['sha256']!=logical[name+'_sha256'] or fixed[name+'_media_id']!=ref['media_id']:
                    raise ResourceError('原图或遮罩未固定为本次编辑输入','inpaint_input_mismatch')
            if logical['operation']=='inpaint':
                from vsc.adapters.providers.openai_image import SIZES
                if (logical['width'],logical['height']) not in SIZES or len(logical['prompt'])>32000 or set(logical['params'])-{'quality'} or logical['params'].get('quality','auto') not in {'auto','low','medium','high'}:
                    raise ResourceError('局部重绘尺寸、说明或质量参数不受当前执行器支持','inpaint_params_unsupported')
            elif any(logical.get(key)!=fixed.get(key) for key in ('operation','source_sha256','width','height','params')):
                raise ResourceError('原生操作参数与固定源尺寸不符','fal_working_input_mismatch')
        for key in ("width", "height"):
            value = logical[key]
            if type(value) is not int or value <= 0 or value > caps.get("max_" + key, value):
                raise ResourceError("图像尺寸超过模型能力", "model_capability_mismatch")
    if modality == "video":
        if logical.get('draft') or logical.get('operation')=='draft_upgrade':
            from vsc.production.video_samples import SAMPLE_MODELS
            resolution='1080p' if logical.get('operation')=='draft_upgrade' else '480p'
            if caps.get('video_draft') is not True or model.get('model_key') not in SAMPLE_MODELS or model.get('default_params',{}).get('resolution')!=resolution:
                raise ResourceError('原生样片或升级需要明确能力与固定分辨率配置','sample_capability_missing')
        if logical.get("operation"):
            if logical["operation"] not in caps.get("video_operations", []):
                raise ResourceError("模型未声明支持此视频加工模式", "model_capability_mismatch")
            if logical['operation']=='depth':
                fixed=context.get('working_native_media')
                ref=refs.get(logical['source_media_id'])
                if not fixed or not ref or ref['role']!='operation_source' or ref['sha256']!=logical['source_sha256'] or any(logical.get(key)!=fixed.get(key) for key in ('operation','source_media_id','source_sha256','source_duration_ms','duration_ms','prompt','params')):
                    raise ResourceError('深度估计须使用原工作稿固定源视频','fal_working_input_mismatch')
            return None
        audio_refs = logical.get("reference_audio_media_ids", [])
        if audio_refs and (not caps.get("reference_audio") or any(
                ref not in refs or refs[ref]["role"] not in {"reference_audio", "speech"} for ref in audio_refs)):
            raise ResourceError("音频参考未获选或模型不支持", "model_capability_mismatch")
        video_refs = logical.get('reference_video_media_ids', [])
        if video_refs and (not caps.get('reference_video') or any(
                ref not in refs or refs[ref]['role'] not in {'reference_video', 'motion_video'} for ref in video_refs)):
            raise ResourceError('视频参考未固定或模型不支持', 'model_capability_mismatch')
        if logical['purpose'] == 'digital_human' and (len(logical['reference_media_ids']) != 1 or len(audio_refs) != 1):
            raise ResourceError('数字人需要唯一形象图片和驱动声音', 'digital_human_inputs')
        if logical['purpose'] == 'digital_human':
            fixed = context.get('working_avatar'); mask = refs.get(logical.get('subject_mask_media_id'))
            if (not caps.get('subject_mask') or not fixed or not mask or mask['role'] != 'subject_mask' or
                    mask['sha256'] != logical['subject_mask_sha256'] or any(logical.get(k) != v for k, v in fixed['request'].items())):
                raise ResourceError('数字人任务须与固定图像、音轨和选中主体一致', 'subject_selection_mismatch')
        if logical['purpose'] == 'motion_transfer' and (len(logical['reference_media_ids']) != 1 or len(video_refs) != 1):
            raise ResourceError('动作模仿需要唯一角色图片和动作视频', 'motion_transfer_inputs')
        duration = logical["duration_ms"]
        if type(duration) is not int or duration <= 0 or duration > caps.get("max_duration_ms", duration):
            raise ResourceError("视频时长超过模型能力", "model_capability_mismatch")
        for key, role, capability in (("first_frame_media_id", "first_frame", "first_frame"),
                                       ("last_frame_media_id", "last_frame", "last_frame")):
            ref = logical[key]
            if ref and (not caps.get(capability) or ref not in refs or refs[ref]["role"] != role):
                raise ResourceError("首尾帧用途或模型能力不符", "model_capability_mismatch")
        keyframes = logical.get("keyframes") or []
        if keyframes:
            if not caps.get("keyframes"):
                raise ResourceError("模型不支持中段关键帧", "model_capability_mismatch")
            if len(keyframes) > 4:
                raise ResourceError("中段关键帧最多 4 个", "model_capability_mismatch")
            for media_id, _ in keyframes:
                if media_id not in refs:
                    raise ResourceError("关键帧引用了未获选的素材", "reference_not_selected")
                if refs[media_id]["role"] in {"reference_audio", "voice_sample"}:
                    raise ResourceError("音频不能作为关键帧", "reference_modality_mismatch")
        if logical["purpose"] in {"video_clip", "image_to_video", "i2v"} and not logical["first_frame_media_id"]:
            raise ResourceError("图生视频必须显式使用获选首帧", "first_frame_required")
    if modality != "audio":
        return None
    if logical['purpose']=='song':
        fixed=context.get('working_song')
        if not caps.get('lyrics') or not context.get('working_draft') or not fixed or logical['lyrics']!=fixed['lyrics'] or logical['prompt']!=fixed['prompt']:
            raise ResourceError('演唱必须使用原工作稿固定的歌词与风格','song_working_input_required')
        return None
    if logical["purpose"] in {"music", "bgm", "ambience", "sfx"}:
        if logical["script_line_ids"] or logical["voice_media_id"] or logical["reference_media_ids"]:
            raise ResourceError("描述音频不接受对白覆盖或人物音色引用", "audio_request_unsupported")
        if logical["params"]:
            raise ResourceError("描述音频尚无逻辑参数映射，不能静默忽略", "audio_request_unsupported")
        maximum = model.get("default_params", {}).get("max_prompt_chars", 2000)
        if type(maximum) is not int or not 1 <= maximum <= 20000 or len(logical["prompt"]) > maximum:
            raise ResourceError("音频提示词超出模型固定字符预算", "audio_prompt_budget")
        return None
    if logical['purpose']=='speech':
        fixed=context.get('working_speech')
        if not context.get('working_draft') or not fixed or logical['prompt']!=fixed['text'] or logical['script_line_ids'] or logical['voice_media_id'] or logical['reference_media_ids'] or logical['params']:
            raise ResourceError('独立朗读须使用固定工作文本与预置音色','speech_working_input_required')
        voices=model.get('capabilities',{}).get('preset_voices',[{'id':'zh_female_vv_uranus_bigtts','name':'Vivi · 预置女声'}])
        if not isinstance(voices,list) or fixed['speaker'] not in {v.get('id') for v in voices if isinstance(v,dict)}:raise ResourceError('音色不在该模型的已配置目录中','speech_voice_unavailable')
        return {'working_draft_id':fixed['draft_id'],'voice':{'engine':'doubao_speech','resource_id':'seed-tts-2.0','voice':fixed['speaker']}}
    requested = logical["script_line_ids"]
    if not isinstance(requested, (list, tuple)) or not requested:
        raise ResourceError("对白生成必须指定固定台词覆盖", "dialogue_coverage_required")
    by_id = {key: line for line in context.get("script_lines", []) for key in (line["line_id"], line["line_key"])}
    if any(key not in by_id for key in requested):
        raise ResourceError("对白台词不属于本镜覆盖", "dialogue_coverage_mismatch")
    lines = [by_id[key] for key in requested]
    if logical["prompt"] != "\n".join(line["spoken_text"] for line in lines):
        raise ResourceError("对白prompt必须等于固定覆盖原文", "dialogue_text_mismatch")
    speakers = {line["speaker_id"] for line in lines}
    if len(speakers) != 1 or None in speakers:
        raise ResourceError("一次对白任务只能有一个明确人物说话人", "dialogue_speaker_mismatch")
    speaker = next(iter(speakers))
    voices = [v for v in context.get("voices", []) if v["character_id"] == speaker]
    if len(voices) != 1:
        raise ResourceError("说话人没有唯一批准音色规格", "voice_missing")
    voice = voices[0]
    ref = logical["voice_media_id"]
    if ref and (not caps.get("voice_reference") or ref not in refs or refs[ref]["role"] != "voice_sample"):
        raise ResourceError("音色参考未获选或模型不支持", "model_capability_mismatch")
    mapping = model.get("default_params", {}).get("voice_map", {}).get(voice["voice_id"])
    if not mapping and not (ref and caps.get("voice_reference")):
        raise ResourceError("模型版本没有该逻辑音色的Provider映射", "voice_provider_mapping_missing")
    for key in ("voice", "voice_id", "speaker", "speaker_id", "resource_id"):
        if key in logical["params"] and (not isinstance(mapping, dict) or logical["params"][key] != mapping.get(key)):
            raise ResourceError("请求不能任意替换人物音色", "voice_parameter_override")
    return {"line_id": requested[0], "entity_id": speaker, "logical_voice_id": voice["voice_id"],
            "voice_spec_id": voice["id"], "voice": mapping or {"reference_media_id": ref}}
