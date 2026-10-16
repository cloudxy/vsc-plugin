"""Resource settings routes; all actions use the panel's human session guard."""
from fastapi import APIRouter, Request
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import ResourceSettings


def register_resource_settings(app, catalog, actor, config=None):
    settings = ResourceSettings(getattr(getattr(catalog, "service", None), "store", None))
    from tools.maintenance.provider_sync import ProviderSync, SyncError
    updater = ProviderSync(root=(config or {}).get("workflow_root"),
        active_jobs=settings.repository.active_jobs if settings.repository else None,
        task_guard=settings.repository.execution_guard if settings.repository else None)
    router = APIRouter(prefix="/api/v1/resource-settings")

    @router.get("")
    def listing():
        result = settings.list()
        try:
            result.update(updater.list())
        except SyncError:
            result.update(tools=[], update_message="本机工具来源登记不可读")
        return result

    @router.post("/configurations")
    def save(request: Request, body: dict):
        identity = actor(request)
        if set(body) != {"payload"}:
            raise ResourceError("保存需要 payload；操作身份来自会话")
        return settings.save(body["payload"], identity)

    @router.post("/configurations/{configuration_id}/enabled")
    def enabled(configuration_id: str, request: Request, body: dict):
        identity = actor(request)
        if set(body) != {"enabled"}:
            raise ResourceError("启停需要 enabled；操作身份来自会话")
        return settings.enabled(configuration_id, body.get("enabled"), identity)

    @router.post("/defaults")
    def defaults(request: Request, body: dict):
        identity = actor(request)
        if set(body) != {"purpose", "configuration_id"}:
            raise ResourceError("默认用途需要 purpose 与 configuration_id")
        return settings.bind_default(body["purpose"], body["configuration_id"], identity)

    @router.post("/configurations/{configuration_id}/check")
    def check(configuration_id: str, request: Request):
        actor(request)
        return settings.check(configuration_id)

    @router.post("/configurations/{configuration_id}/models")
    def models(configuration_id: str, request: Request):
        actor(request)
        return settings.models(configuration_id)

    @router.post("/updates/check")
    def updates(request: Request, body: dict = None):
        actor(request)
        try:
            return updater.check((body or {}).get("tool_id"))
        except SyncError as exc:
            raise ResourceError(str(exc), "provider_sync_failed", 409) from exc

    @router.post("/updates/{tool_id}")
    def update(tool_id: str, request: Request, body: dict):
        identity = actor(request)
        if set(body) != {"expected_revision"}:
            raise ResourceError("更新需要检查所得 expected_revision；本次点击即授权")
        try:
            return updater.update(tool_id, body["expected_revision"], identity)
        except SyncError as exc:
            raise ResourceError(str(exc), "provider_sync_failed", 409) from exc

    app.include_router(router)
    app.state.resource_settings = settings
    return settings
