"""Independent management pages consume the shared application projection."""
from fastapi import HTTPException, Request
from vsc.assets.production_platform import ProductionPlatform


def install_production_platform_routes(app_or_router, router_or_catalog=None, catalog_or_etag=None, etag=None, actor=None, read_actor=None):
    if etag is None:
        app = None
        router = app_or_router
        catalog = router_or_catalog
        etag = catalog_or_etag
    else:
        app = app_or_router
        router = router_or_catalog
        catalog = catalog_or_etag

    platform = ProductionPlatform(catalog)

    def pg_service():
        if catalog.service is None:
            raise HTTPException(409, "本次服务没有配置项目数据库")
        return catalog.service

    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "旧项目保持只读；任务与用量需要原 PostgreSQL 权威")
        catalog.service.get_project(project_id)
        return catalog.service

    if app is not None:
        @app.get("/api/v1/account/tasks")
        @app.get("/api/v1/account/task-center")
        def account_tasks(
            request: Request,
            offset: int = 0,
            limit: int = 24,
            kind: str = None,
            status: str = None,
            group: str = None,
            project_id: str = None,
        ):
            if read_actor is not None:
                read_actor(request)
            return etag(
                request,
                pg_service().get_account_tasks(
                    offset=offset,
                    limit=limit,
                    kind=kind,
                    status=status,
                    group=group,
                    project_id=project_id,
                ),
            )

        @app.post("/api/v1/account/tasks/batch-cancel")
        def batch_cancel_tasks(request: Request, body: dict):
            identity = actor(request) if actor is not None else (read_actor(request) if read_actor is not None else None)
            if not isinstance(body, dict):
                raise HTTPException(422, "批量取消请求格式无效")
            payload = body.get("payload") if isinstance(body.get("payload"), dict) else dict(body)
            if "confirmed" in body and "confirmed" not in payload:
                payload = dict(payload, confirmed=body.get("confirmed"))
            idem_key = body.get("idempotency_key") or payload.get("idempotency_key")
            return pg_service().batch_cancel_account_tasks(
                payload, actor=identity, idempotency_key=idem_key
            )

    @router.get("/{project_id}/production-platform")
    def query(project_id: str, request: Request, episode_id: str = None, offset: int = 0, limit: int = 24):
        return etag(request, platform.query(project_id, episode_id=episode_id, offset=offset, limit=limit))

    @router.get('/{project_id}/production-platform/episode-editor')
    def episode_editor(project_id: str, request: Request, episode_id: str = None, parent_id: str = None):
        return etag(request,service(project_id).get_episode_editor(project_id,episode_id,parent_id))

    @router.get('/{project_id}/production-platform/episode-entry')
    def episode_entry(project_id: str, request: Request, episode_id: str):
        from vsc.assets.access_control import current_principal
        principal=current_principal()
        if principal is None or not principal.actor:raise HTTPException(403,'请先建立操作会话')
        return etag(request,service(project_id).get_episode_entry(project_id,episode_id,principal.actor))

    @router.post("/{project_id}/shot-batch/preview")
    def preview(project_id: str, request: Request, body: dict):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "旧项目只读；制作预览需要原 PostgreSQL 权威")
        return etag(request, catalog.service.preview_shot_batch(project_id, body.get("payload")))

    @router.post("/{project_id}/first-production/preview")
    def first_production(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_first_production(project_id, body.get("payload")))

    @router.get("/{project_id}/execution-authorizations")
    def authorizations(project_id: str, request: Request):
        return etag(request, service(project_id).get_execution_authorizations(project_id))

    @router.post("/{project_id}/production-requirements/preview")
    def requirements(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_production_requirements(project_id, body.get("payload")))

    @router.get("/{project_id}/production-platform/budget")
    def budget(project_id: str, request: Request):
        return etag(request, service(project_id).budget_status(project_id))

    @router.get("/{project_id}/task-center")
    def tasks(project_id: str,request: Request,offset: int=0,limit: int=24,kind: str=None,status: str=None,episode_id: str=None,group: str=None):
        return etag(request,service(project_id).get_task_center(project_id,offset,limit,kind,status,episode_id,group))

    @router.get('/{project_id}/task-usage')
    def task_usage(project_id: str,request: Request,offset: int=0,limit: int=24):
        return etag(request,service(project_id).get_task_usage(project_id,offset,limit))

    @router.get("/{project_id}/production-platform/jobs/{job_id}")
    def job(project_id: str, job_id: str, request: Request):
        value = service(project_id).get_generation_job(project_id, job_id)
        # Connection/auth configuration and raw provider responses never enter a management projection.
        fields = ("id", "project_id", "shot_id", "asset_id", "purpose", "modality", "status", "candidate_no",
            "attempt", "created_at", "updated_at", "model_version", "run_version_id", "outputs", "input_versions")
        result = {key: value.get(key) for key in fields}
        result["events"] = [{key: row.get(key) for key in ("event_type", "created_at")}
                            for row in value.get("events", [])]
        result['usage'] = service(project_id).get_generation_quote_status(project_id, job_id)
        from datetime import datetime
        result['elapsed_ms'] = max(0, round((datetime.fromisoformat(value['updated_at']) - datetime.fromisoformat(value['created_at'])).total_seconds() * 1000))
        return etag(request, result)
