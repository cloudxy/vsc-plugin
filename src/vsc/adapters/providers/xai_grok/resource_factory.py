"""Resolve a frozen resource job to the xAI Grok Imagine provider implementation."""
import base64
from dataclasses import replace
from vsc.assets.resource_service import ResourceError


class ConfiguredGrokProvider:
    """Keep registry account IDs out of the subscription transport handle identity."""

    def __init__(self, adapter, provider_id):
        self.adapter, self.provider_id = adapter, provider_id

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def submit(self, request):
        return replace(self.adapter.submit(request), provider=self.provider_id)

    def poll(self, handle):
        if handle.provider != self.provider_id:
            raise ResourceError("任务不属于此配置", "invalid_provider_config")
        return self.adapter.poll(replace(handle, provider="xai_grok"))


def xai_grok_factory(job, storage):
    """Translate registered model defaults to the Grok subscription implementation."""
    from vsc.adapters.providers.xai_grok import credentials as grok_credentials
    from vsc.adapters.providers.xai_grok.provider import GrokImageProvider, GrokVideoProvider
    identity = job["provider"].get("configuration", {})
    configured_grok = ((identity.get("supplier"), identity.get("product"), identity.get("plan")) == ("xai", "grok-imagine", "subscription")
        and identity.get("execution") == "api")
    if job["provider_id"] != "xai_grok" and not configured_grok:
        raise ResourceError("此 Provider 尚未安装适配器", "adapter_unavailable")
    if job["provider"]["base_url"].rstrip("/") != grok_credentials.API_BASE or job["provider"].get("auth_ref"):
        raise ResourceError("Grok 订阅路线必须使用官方端点与 grok 登录态授权（不使用环境变量凭证）", "invalid_provider_config")
    problem = grok_credentials.key_problem()
    if problem:
        raise ResourceError(problem, "credential_missing")
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
        raise ResourceError("当前 Grok 适配器未声明这些逻辑参数映射，禁止静默忽略", "unsupported_params")
    if job["modality"] == "image":
        ratios, resolution = defaults.get("ratio_map", {}), defaults.get("resolution", "2k")
        return ConfiguredGrokProvider(GrokImageProvider(model, media_url,
            lambda w, h: ratios.get(str(w) + "x" + str(h)), resolution), job["provider_id"])
    if job["modality"] == "video":
        if not defaults.get("resolution"):
            raise ResourceError("Grok 视频模型需要 resolution 映射", "invalid_model_defaults")
        return ConfiguredGrokProvider(GrokVideoProvider(model, media_url, defaults["resolution"],
            defaults.get("ratio", "")), job["provider_id"])
    raise ResourceError("Grok 订阅路线未接音频适配器", "adapter_unavailable")
