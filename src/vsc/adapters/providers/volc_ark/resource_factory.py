"""Resolve a frozen resource job to the Ark provider implementation."""
import base64
from vsc.assets.resource_service import ResourceError

def volc_ark_factory(job, storage):
    """Translate registered model defaults to the first provider implementation."""
    from vsc.adapters.providers import credentials
    from vsc.adapters.providers.volc_ark.provider import VolcArkAudioProvider, VolcArkImageProvider, VolcArkVideoProvider
    if job["provider_id"] != "volc_ark":
        raise ResourceError("此 Provider 尚未安装适配器", "adapter_unavailable")
    if job["provider"]["base_url"].rstrip("/") != credentials.PLAN_BASE or job["provider"]["auth_ref"] != credentials.KEY_ENV:
        raise ResourceError("方舟必须使用已配置的 Agent Plan 凭证引用与地址", "invalid_provider_config")
    fixed = {item["media_id"]: item for item in job["input_media"]}
    def media_url(media_id):
        item = fixed.get(media_id)
        if item is None:
            raise ResourceError("未固定的媒体引用", "unfixed_reference")
        for location in item["locations"]:
            if location["storage"] == "local" and location["available"]:
                content = storage.read(location["object_key"], item["blob_sha256"])
                return "data:" + item["mime_type"] + ";base64," + base64.b64encode(content).decode("ascii")
        raise ResourceError("固定媒体字节不可用", "media_unavailable")
    defaults, model = job["model"]["default_params"], job["model"]["model_key"]
    logical = job["request_payload"].get("logical_request", job["request_payload"])
    if logical.get("params"):
        raise ResourceError("当前方舟适配器未声明这些逻辑参数映射，禁止静默忽略", "unsupported_params")
    if job["modality"] == "image":
        sizes = defaults.get("size_map", {})
        return VolcArkImageProvider(model, media_url, lambda w, h: sizes.get(str(w) + "x" + str(h)))
    if job["modality"] == "video":
        if not defaults.get("resolution") or not defaults.get("ratio"):
            raise ResourceError("视频模型需要 resolution 和 ratio 映射", "invalid_model_defaults")
        return VolcArkVideoProvider(model, media_url, defaults["resolution"], defaults["ratio"], defaults.get("generate_audio", False))
    binding = job["request_payload"].get("voice_binding")
    voice_defaults = {key: value for key, value in defaults.items() if key in {"format", "sample_rate", "speech_rate"}}
    return VolcArkAudioProvider(model, storage.root, "J-" + job["id"].replace("-", ""), binding, voice_defaults)
