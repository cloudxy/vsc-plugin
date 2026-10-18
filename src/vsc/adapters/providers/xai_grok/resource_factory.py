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
    from vsc.adapters.providers.xai_grok import api as grok
    grok.base_url()  # validate the actual environment-selected transport endpoint before intent
    problem = grok_credentials.key_problem()
    if problem:
        raise ResourceError(problem, "credential_missing")
    fixed = {item["media_id"]: item for item in job["input_media"]}
    logical = job["request_payload"].get("logical_request", job["request_payload"])

    def media_url(media_id):
        item = fixed.get(media_id)
        if item is None:
            raise ResourceError("未固定的媒体引用", "unfixed_reference")
        for location in item["locations"]:
            if location["storage"] == "local" and location["available"]:
                if item["role"] == "operation_source":
                    from vsc.production.video_operations import verify_source_bytes
                    # Decode/check the fixed local source again before paid
                    # submission; never consume an unchecked client path.
                    verify_source_bytes(storage, item, logical)
                content = storage.read(location["object_key"], item["blob_sha256"])
                return "data:" + item["mime_type"] + ";base64," + base64.b64encode(content).decode("ascii")
        raise ResourceError("固定媒体字节不可用", "media_unavailable")

    defaults, model = job["model"]["default_params"], job["model"]["model_key"]
    params = logical.get("params") or {}
    unsupported_operations = {"source_video", "video", "source_video_media_id"} & (set(logical) | set(params) | set(defaults))
    unsupported_operations |= {"operation"} & (set(params) | set(defaults))
    if unsupported_operations:
        raise ResourceError("视频加工须使用固定typed operation/source字段，不能混入路径或params", "unsupported_params")
    if logical.get("operation"):
        source = fixed.get(logical.get("source_media_id"))
        if (job["modality"] != "video" or logical["operation"] not in job["model"]["capabilities"].get("video_operations", []) or
                not source or source["role"] != "operation_source" or source["blob_sha256"] != logical.get("source_sha256")):
            raise ResourceError("模型加工能力或固定源片不符", "model_capability_mismatch")
        return ConfiguredGrokProvider(GrokVideoProvider(model, media_url, "", transport=None), job["provider_id"])
    supported = {"resolution", "aspect_ratio", "generate_audio", "reference_voice_ids"} if job["modality"] == "video" else {"resolution", "aspect_ratio"}
    if set(params) - supported:
        raise ResourceError("当前 Grok 适配器未声明这些逻辑参数映射，禁止静默忽略: "
                            + ",".join(sorted(set(params) - supported)), "unsupported_params")
    if job["modality"] == "image":
        ratios, resolution = defaults.get("ratio_map", {}), defaults.get("resolution", "2k")
        return ConfiguredGrokProvider(GrokImageProvider(model, media_url,
            lambda w, h: ratios.get(str(w) + "x" + str(h)), resolution), job["provider_id"])
    if job["modality"] == "video":
        if not defaults.get("resolution"):
            raise ResourceError("Grok 视频模型需要 resolution 映射", "invalid_model_defaults")
        return ConfiguredGrokProvider(GrokVideoProvider(model, media_url,
            params.get("resolution", defaults["resolution"]),
            params.get("aspect_ratio", defaults.get("ratio", "")),
            defaults.get("reference_voice_ids", []),
            params.get("generate_audio", defaults.get("generate_audio", True))), job["provider_id"])
    raise ResourceError("Grok 订阅路线未接音频适配器", "adapter_unavailable")
