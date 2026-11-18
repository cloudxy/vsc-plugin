"""Resolve a frozen resource job to the Kuaishou Kling AI provider implementation."""
from __future__ import annotations

import base64
from dataclasses import replace

from vsc.assets.resource_service import ResourceError


class ConfiguredKlingProvider:
    """Keep registry provider IDs out of the Kling transport handle identity."""

    def __init__(self, adapter, provider_id: str):
        self.adapter, self.provider_id = adapter, provider_id

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def submit(self, request):
        return replace(self.adapter.submit(request), provider=self.provider_id)

    def poll(self, handle):
        if handle.provider != self.provider_id:
            raise ResourceError("任务不属于此配置", "invalid_provider_config")
        return self.adapter.poll(replace(handle, provider="kling"))


def kling_factory(job, storage, *, client=None, transport=None):
    """Translate registered Kling configuration defaults to `KlingImageProvider` / `KlingVideoProvider`."""
    from vsc.adapters.providers.kling import credentials as kling_credentials
    from vsc.adapters.providers.kling.provider import (
        IMAGE_SUPPORTED_PARAMS,
        VIDEO_SUPPORTED_PARAMS,
        KlingImageProvider,
        KlingVideoProvider,
    )

    provider = job.get("provider") or {}
    identity = provider.get("configuration", {}) if isinstance(provider, dict) else {}
    configured_kling = (
        (identity.get("supplier"), identity.get("product"), identity.get("plan")) == ("kling", "kling", "api")
        and identity.get("execution") == "api"
    )
    if job.get("provider_id") != "kling" and not configured_kling:
        raise ResourceError("此 Provider 尚未安装适配器", "adapter_unavailable")

    base_url = (provider.get("base_url") or "").rstrip("/")
    auth_ref = (provider.get("auth_ref") or "").strip()
    if base_url not in kling_credentials.ALLOWED_BASES or not auth_ref:
        raise ResourceError("快手可灵生产路线须使用官方 HTTPS 端点与环境变量凭证引用", "invalid_provider_config")
    try:
        kling_credentials.resolve_auth(auth_ref, error=ValueError)
    except ValueError as exc:
        raise ResourceError(str(exc), "credential_missing") from None

    fixed = {item["media_id"]: item for item in job.get("input_media", [])}
    logical = job["request_payload"].get("logical_request", job["request_payload"])

    def media_data(media_id: str) -> str:
        item = fixed.get(media_id)
        if item is None:
            raise ResourceError("未固定的媒体引用", "unfixed_reference")
        for location in item.get("locations", []):
            if location.get("storage") == "local" and location.get("available"):
                content = storage.read(location["object_key"], item["blob_sha256"])
                return base64.b64encode(content).decode("ascii")
        raise ResourceError("固定媒体字节不可用", "media_unavailable")

    defaults, model = job["model"]["default_params"], job["model"]["model_key"]
    params = logical.get("params") or {}
    unsupported_operations = {"source_video", "video", "source_video_media_id"} & (
        set(logical) | set(params) | set(defaults)
    )
    unsupported_operations |= {"operation"} & (set(params) | set(defaults))
    if unsupported_operations or logical.get("operation"):
        raise ResourceError("当前快手可灵适配器不支持固定源编辑或续接操作", "unsupported_params")

    supported = VIDEO_SUPPORTED_PARAMS if job["modality"] == "video" else IMAGE_SUPPORTED_PARAMS
    if set(params) - supported:
        raise ResourceError(
            "当前可灵适配器未声明这些逻辑参数映射，禁止静默忽略: " + ",".join(sorted(set(params) - supported)),
            "unsupported_params",
        )

    if job["modality"] == "image":
        ratios, resolution = defaults.get("ratio_map", {}), defaults.get("resolution", "2k")
        return ConfiguredKlingProvider(
            KlingImageProvider(
                model,
                media_data,
                lambda w, h: ratios.get(f"{w}x{h}"),
                resolution,
                base_url=base_url,
                auth_ref=auth_ref,
                client=client,
                transport=transport,
            ),
            job["provider_id"],
        )
    if job["modality"] == "video":
        if not defaults.get("resolution"):
            raise ResourceError("可灵视频模型需要 resolution 映射", "invalid_model_defaults")
        return ConfiguredKlingProvider(
            KlingVideoProvider(
                model,
                media_data,
                params.get("resolution", defaults["resolution"]),
                params.get("aspect_ratio", defaults.get("ratio", "16:9")),
                params.get("generate_audio", defaults.get("generate_audio", True)),
                base_url=base_url,
                auth_ref=auth_ref,
                client=client,
                transport=transport,
            ),
            job["provider_id"],
        )
    raise ResourceError("快手可灵当前未接音频适配器", "adapter_unavailable")
