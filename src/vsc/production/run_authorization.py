"""Pure authorization of a frozen logical request against its approved run."""
import json
from vsc.assets.resource_service import ResourceError


def normalize_request(request, shot_id, purpose, modality, asset_id=None):
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ResourceError("逻辑请求需要非空prompt", "invalid_generation_request")
    base = {"shot_id": shot_id, "purpose": purpose, "modality": modality,
            "reference_media_ids": [], "params": {}}
    if asset_id is not None:
        if shot_id is not None or modality != "image":
            raise ResourceError("资产首参考任务只支持图像且不能同时指定镜头", "request_scope_mismatch")
        base["asset_id"] = asset_id
    if modality == "image":
        base.update(width=1080, height=1920)
    elif modality == "video":
        base.update(duration_ms=5000, first_frame_media_id=None, last_frame_media_id=None)
    elif modality == "audio":
        base.update(script_line_ids=[], voice_media_id=None)
    else:
        raise ResourceError("未知请求模态")
    allowed = set(base) | {"prompt", "format", "context_sha256"}
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
    return base


def authorize_run(run, run_type, context, logical, candidate_no):
    if run_type not in {"production-run", "vsc.production_run"} or not isinstance(run, dict):
        raise ResourceError("任务必须绑定正式production-run类型", "invalid_production_run")
    inputs = run.get("approved_inputs")
    if not isinstance(inputs, list) or any(not isinstance(x, dict) for x in inputs):
        raise ResourceError("run必须明确列出approved_inputs", "run_inputs_missing")
    pinned = {(x.get("id"), x.get("sha256")) for x in inputs}
    required = {(x["id"], x["sha256"]) for x in context["artifacts"]}
    if not required <= pinned:
        raise ResourceError("镜头所需固定版本没有全部获run授权", "run_inputs_mismatch")
    jobs = run.get("series_batch", {}).get("jobs", run.get("jobs", []))
    if not isinstance(jobs, list):
        raise ResourceError("run必须明确列出jobs")
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
    if logical["reference_media_ids"] and not caps.get("reference_media"):
        raise ResourceError("模型不支持参考素材", "model_capability_mismatch")
    modality = logical["modality"]
    if modality == "image":
        for key in ("width", "height"):
            value = logical[key]
            if type(value) is not int or value <= 0 or value > caps.get("max_" + key, value):
                raise ResourceError("图像尺寸超过模型能力", "model_capability_mismatch")
    if modality == "video":
        duration = logical["duration_ms"]
        if type(duration) is not int or duration <= 0 or duration > caps.get("max_duration_ms", duration):
            raise ResourceError("视频时长超过模型能力", "model_capability_mismatch")
        for key, role, capability in (("first_frame_media_id", "first_frame", "first_frame"),
                                       ("last_frame_media_id", "last_frame", "last_frame")):
            ref = logical[key]
            if ref and (not caps.get(capability) or ref not in refs or refs[ref]["role"] != role):
                raise ResourceError("首尾帧用途或模型能力不符", "model_capability_mismatch")
        if logical["purpose"] in {"video_clip", "image_to_video", "i2v"} and not logical["first_frame_media_id"]:
            raise ResourceError("图生视频必须显式使用获选首帧", "first_frame_required")
    if modality != "audio":
        return None
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
