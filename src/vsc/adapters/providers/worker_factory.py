"""Dispatch a frozen resource job to the adapter factory of its registered provider.

The worker injects this single seam; each supplier keeps its own factory module so
account invariants and transport choices stay local to the provider package.
"""
from vsc.assets.resource_service import ResourceError


def worker_adapter_factory(job, storage):
    provider = job.get("provider") or {}
    identity = provider.get("configuration", {}) if isinstance(provider, dict) else {}
    if job.get("provider_id") == "volc_ark" or identity.get("supplier") == "volcengine":
        from vsc.adapters.providers.volc_ark.resource_factory import volc_ark_factory
        return volc_ark_factory(job, storage)
    if job.get("provider_id") == "xai_grok" or identity.get("supplier") == "xai":
        from vsc.adapters.providers.xai_grok.resource_factory import xai_grok_factory
        return xai_grok_factory(job, storage)
    raise ResourceError("此 Provider 尚未安装适配器", "adapter_unavailable")
