"""Resolve a frozen resource job to the Ark provider implementation."""
import base64
from copy import deepcopy
from dataclasses import replace
from vsc.assets.resource_service import ResourceError


class ConfiguredArkProvider:
    """Keep registry account IDs out of the vendor's transport handle identity."""
    def __init__(self, adapter, provider_id, transport=None):
        self.adapter, self.provider_id = adapter, provider_id
        self.transport = transport

    def preflight(self, request=None):
        if self.transport is not None:
            self.transport.preflight(request)
        if hasattr(self.adapter, "preflight"):
            self.adapter.preflight(request)

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def submit(self, request):
        return replace(self.adapter.submit(request), provider=self.provider_id)

    def poll(self, handle):
        if handle.provider != self.provider_id:
            raise ResourceError("任务不属于此配置", "invalid_provider_config")
        result = self.adapter.poll(replace(handle, provider="volc_ark"))
        previous = handle.raw.get("vsc_execution")
        if self.transport is not None and handle.external_task_id and isinstance(previous, dict) and isinstance(result.raw.get("vsc_execution"), dict):
            raw = deepcopy(result.raw)
            raw["vsc_execution"]["submission"] = deepcopy(previous.get("submission", previous))
            result = replace(result, raw=raw)
        return result

def volc_ark_factory(job, storage, *, sdk_http_client=None):
    """Translate registered model defaults to the first provider implementation."""
    from vsc.adapters.providers import credentials
    from vsc.adapters.providers.volc_ark.provider import VolcArkAudioProvider, VolcArkImageProvider, VolcArkVideoProvider
    identity = job["provider"].get("configuration", {})
    configured_ark = ((identity.get("supplier"), identity.get("product"), identity.get("plan")) == ("volcengine", "ark", "agent-plan")
        and identity.get("execution") in {"api", "official_sdk"})
    if job["provider_id"] != "volc_ark" and not configured_ark:
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
    transport = None
    if identity.get("execution") == "official_sdk":
        if job["modality"] not in {"image", "video"}:
            raise ResourceError("官方 SDK 路线仅核验图像和视频，语音沿已登记 API 路线", "adapter_unavailable")
        from vsc.adapters.providers.volc_ark.official_sdk import OfficialArkTransport
        transport = OfficialArkTransport(defaults.get("sdk_runtime"), {
            "host": "vsc-python-worker", "service_provider": "volcengine", "product": "ark", "plan": "agent-plan",
            "region": identity.get("region"), "account_reference": job["provider_id"], "credential_reference": credentials.KEY_ENV,
            "account_identity_verified": False,
            "configuration_id": job["model"]["id"], "model_id": model, "model_version": job["model_version"],
            "job_id": job["id"], "logical_request_sha256": job["request_sha256"]}, http_client=sdk_http_client)
    logical = job["request_payload"].get("logical_request", job["request_payload"])
    if logical.get("params"):
        raise ResourceError("当前方舟适配器未声明这些逻辑参数映射，禁止静默忽略", "unsupported_params")
    if job["modality"] == "image":
        sizes = defaults.get("size_map", {})
        return ConfiguredArkProvider(VolcArkImageProvider(model, media_url, lambda w, h: sizes.get(str(w) + "x" + str(h)), transport=transport), job["provider_id"], transport)
    if job["modality"] == "video":
        if not defaults.get("resolution") or not defaults.get("ratio"):
            raise ResourceError("视频模型需要 resolution 和 ratio 映射", "invalid_model_defaults")
        return ConfiguredArkProvider(VolcArkVideoProvider(model, media_url, defaults["resolution"], defaults["ratio"], defaults.get("generate_audio", False), transport=transport), job["provider_id"], transport)
    binding = job["request_payload"].get("voice_binding")
    voice_defaults = {key: value for key, value in defaults.items() if key in {"format", "sample_rate", "speech_rate", "context_texts"}}
    return ConfiguredArkProvider(VolcArkAudioProvider(model, storage.root, "J-" + job["id"].replace("-", ""), binding, voice_defaults), job["provider_id"])
