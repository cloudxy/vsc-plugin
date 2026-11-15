"""Session-bound operations UI across account/workspace/platform/project and Bearer API."""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool


def install_service_operations_routes(app, router, catalog, etag, actor, read_actor):
    def service(p):
        if catalog.service is None or catalog._reader(p) is not None:
            raise HTTPException(409, "运营与开放接口需要原PostgreSQL项目")
        return catalog.service

    def pg_service():
        if catalog.service is None:
            raise HTTPException(409, "运营与开放接口需要PostgreSQL")
        return catalog.service

    @app.get("/api/v1/discovery")
    def discover(request: Request):
        read_actor(request)
        if catalog.service is None:
            raise HTTPException(409, "创作目录需要PostgreSQL")
        from vsc.assets.discovery import discovery
        return etag(request, discovery(catalog.service))

    @app.get("/api/v1/discovery/tutorials/{identifier}")
    def tutorial(identifier: str, request: Request):
        read_actor(request)
        from vsc.assets.discovery import tutorial as read_tutorial
        return etag(request, read_tutorial(identifier))

    @app.get("/api/v1/discovery/capabilities")
    def capability_catalog(request: Request, source: str = None):
        read_actor(request)
        from vsc.assets.capability_catalog import CapabilityCatalog
        from vsc.assets.resource_service import ResourceError
        if set(request.query_params) - {"source"} or len(request.query_params.getlist("source")) > 1:
            raise ResourceError("能力来源无效", "invalid_capability_source", 422)
        if request.headers.get("content-length", "0") != "0" or request.headers.get("transfer-encoding"):
            raise ResourceError("只读目录不接受请求正文", "invalid_payload", 422)
        result = CapabilityCatalog().capabilities(source)
        if result["status"] == "unavailable":
            return JSONResponse(result, status_code=503)
        return etag(request, result)

    @app.get("/api/v1/discovery/documents/{document_id:path}")
    def capability_document(document_id: str, request: Request):
        read_actor(request)
        from vsc.assets.capability_catalog import CapabilityCatalog
        from vsc.assets.resource_service import ResourceError
        if request.query_params:
            raise ResourceError("文档不存在", "document_not_found", 404)
        if request.headers.get("content-length", "0") != "0" or request.headers.get("transfer-encoding"):
            raise ResourceError("只读文档不接受请求正文", "invalid_payload", 422)
        return etag(request, CapabilityCatalog().document(document_id))

    # --- Project-scoped routes (/api/v1/projects/{project_id}/service-operations*) ---

    @router.get("/{project_id}/service-operations")
    def snapshot(project_id: str, request: Request):
        read_actor(request)
        return etag(request, service(project_id).service_operations_snapshot(project_id))

    @router.get("/{project_id}/service-operations/feedback")
    def feedback(project_id: str, request: Request, scope: str = "mine", status: str = "all", query: str = "", category: str = "", offset: int = 0, limit: int = 24):
        read_actor(request)
        return etag(request, service(project_id).service_feedback(project_id, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit))

    @router.get("/{project_id}/service-operations/drama-requests")
    def drama_requests(project_id: str, request: Request, scope: str = "mine", status: str = "all", query: str = "", offset: int = 0, limit: int = 12):
        read_actor(request)
        return etag(request, service(project_id).service_drama_requests(project_id, scope=scope, status=status, query=query, offset=offset, limit=limit))

    async def write_project(p, request, body, method):
        identity = actor(request)
        if set(body) - {"payload", "expected_revision", "idempotency_key", "confirmed"} or not {"payload", "expected_revision", "idempotency_key"} <= set(body):
            raise HTTPException(422, "身份来自可信会话；提交固定版本和请求标识")
        return await run_in_threadpool(
            getattr(service(p), method),
            p, body["payload"], actor=identity,
            expected_revision=body["expected_revision"], idempotency_key=body["idempotency_key"],
        )

    async def write_scoped(scope_kind, scope_id, request, body, method):
        identity = actor(request)
        if set(body) - {"payload", "expected_revision", "idempotency_key", "confirmed"} or not {"payload", "expected_revision", "idempotency_key"} <= set(body):
            raise HTTPException(422, "身份来自可信会话；提交固定版本和请求标识")
        return await run_in_threadpool(
            getattr(pg_service(), method),
            scope_kind, scope_id, body["payload"], actor=identity,
            expected_revision=body["expected_revision"], idempotency_key=body["idempotency_key"],
        )

    @router.post("/{project_id}/service-operations/configuration")
    async def configure(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "configure_service_operations")

    @router.post("/{project_id}/service-operations/announcements")
    async def announce(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "publish_service_announcement")

    @router.post("/{project_id}/service-operations/requests")
    async def create(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "create_service_request")

    @router.post("/{project_id}/service-operations/requests/process")
    async def process(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "process_service_request")

    @router.post("/{project_id}/service-operations/requests/withdraw")
    async def withdraw(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "withdraw_service_request")

    @router.post("/{project_id}/service-operations/account-close/preview")
    async def close_preview(project_id: str, request: Request, body: dict):
        read_actor(request)
        return await run_in_threadpool(service(project_id).preview_account_close, project_id, body)

    @router.post("/{project_id}/service-operations/account-close/execute")
    async def close_account(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "close_service_account")

    @router.post("/{project_id}/service-operations/api-keys")
    async def key(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "issue_service_api_key")

    @router.post("/{project_id}/service-operations/api-keys/revoke")
    async def revoke(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "revoke_service_api_key")

    @router.post("/{project_id}/service-operations/exports/build")
    async def export(project_id: str, request: Request, body: dict):
        return await write_project(project_id, request, body, "build_service_export")

    @router.get("/{project_id}/service-operations/exports/{identifier}/content")
    def content(project_id: str, identifier: str, request: Request):
        read_actor(request)
        raw, sha = service(project_id).service_export_content(project_id, identifier)
        return Response(
            raw,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=personal-data.zip", "ETag": '"' + sha + '"', "Cache-Control": "private, no-store"},
        )

    @router.post("/{project_id}/service-operations/seedance-verify")
    async def seedance_verify(project_id: str, request: Request, body: dict):
        read_actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return await run_in_threadpool(service(project_id).verify_seedance_task, project_id, payload)

    @router.get("/{project_id}/service-operations/network-diagnostic/ping")
    async def diagnostic_ping(project_id: str, request: Request, probe: str = ""):
        read_actor(request)
        result = await run_in_threadpool(service(project_id).network_diagnostic_probe, project_id, probe)
        return JSONResponse(result, headers={"Cache-Control": "private, no-store"})

    # --- Account-scoped routes (/api/v1/account/service-operations*) ---

    @app.get("/api/v1/account/service-operations")
    def account_snapshot(request: Request):
        read_actor(request)
        return etag(request, pg_service().scoped_service_operations_snapshot("identity", None))

    @app.get("/api/v1/account/service-operations/feedback")
    def account_feedback(request: Request, scope: str = "mine", status: str = "all", query: str = "", category: str = "", offset: int = 0, limit: int = 24):
        read_actor(request)
        return etag(request, pg_service().scoped_service_feedback("identity", None, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit))

    @app.get("/api/v1/account/service-operations/drama-requests")
    def account_drama_requests(request: Request, scope: str = "mine", status: str = "all", query: str = "", offset: int = 0, limit: int = 12):
        read_actor(request)
        return etag(request, pg_service().scoped_service_drama_requests("identity", None, scope=scope, status=status, query=query, offset=offset, limit=limit))

    @app.post("/api/v1/account/service-operations/requests")
    async def account_create_request(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "create_scoped_service_request")

    @app.post("/api/v1/account/service-operations/requests/withdraw")
    async def account_withdraw_request(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "withdraw_scoped_service_request")

    @app.post("/api/v1/account/service-operations/api-keys")
    async def account_issue_key(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "issue_scoped_service_api_key")

    @app.post("/api/v1/account/service-operations/api-keys/revoke")
    async def account_revoke_key(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "revoke_scoped_service_api_key")

    @app.post("/api/v1/account/service-operations/exports/build")
    async def account_build_export(request: Request, body: dict):
        return await write_scoped("identity", None, request, body, "build_scoped_service_export")

    @app.get("/api/v1/account/service-operations/exports/{identifier}/content")
    def account_export_content(identifier: str, request: Request):
        read_actor(request)
        raw, sha = pg_service().scoped_service_export_content("identity", None, identifier)
        return Response(
            raw,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=personal-data.zip", "ETag": '"' + sha + '"', "Cache-Control": "private, no-store"},
        )

    @app.post("/api/v1/account/service-operations/account-close/preview")
    async def account_close_preview(request: Request, body: dict):
        read_actor(request)
        return await run_in_threadpool(pg_service().preview_account_close_identity, body)

    @app.post("/api/v1/account/service-operations/account-close/execute")
    async def account_close_execute(request: Request, body: dict):
        identity = actor(request)
        if set(body) - {"payload", "expected_revision", "idempotency_key", "confirmed"} or not {"payload", "expected_revision", "idempotency_key"} <= set(body):
            raise HTTPException(422, "身份来自可信会话；提交固定版本和请求标识")
        return await run_in_threadpool(
            pg_service().close_service_account_identity,
            body["payload"],
            confirmed=body.get("confirmed"),
            actor=identity,
            expected_revision=body["expected_revision"],
            idempotency_key=body["idempotency_key"],
        )

    @app.post("/api/v1/account/service-operations/seedance-verify")
    async def account_seedance_verify(request: Request, body: dict):
        read_actor(request)
        payload = body.get("payload") if isinstance(body, dict) and isinstance(body.get("payload"), dict) else body
        return await run_in_threadpool(pg_service().verify_account_seedance_task, payload)

    @app.get("/api/v1/account/service-operations/network-diagnostic/ping")
    async def account_diagnostic_ping(request: Request, probe: str = ""):
        read_actor(request)
        result = await run_in_threadpool(pg_service().account_network_diagnostic_probe, probe)
        return JSONResponse(result, headers={"Cache-Control": "private, no-store"})

    # --- Workspace-scoped routes (/api/v1/workspaces/{workspace_id}/service-operations*) ---

    @app.get("/api/v1/workspaces/{workspace_id}/service-operations")
    def workspace_snapshot(workspace_id: str, request: Request):
        read_actor(request)
        return etag(request, pg_service().scoped_service_operations_snapshot("workspace", workspace_id))

    @app.get("/api/v1/workspaces/{workspace_id}/service-operations/feedback")
    def workspace_feedback(workspace_id: str, request: Request, scope: str = "mine", status: str = "all", query: str = "", category: str = "", offset: int = 0, limit: int = 24):
        read_actor(request)
        return etag(request, pg_service().scoped_service_feedback("workspace", workspace_id, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit))

    @app.get("/api/v1/workspaces/{workspace_id}/service-operations/drama-requests")
    def workspace_drama_requests(workspace_id: str, request: Request, scope: str = "mine", status: str = "all", query: str = "", offset: int = 0, limit: int = 12):
        read_actor(request)
        return etag(request, pg_service().scoped_service_drama_requests("workspace", workspace_id, scope=scope, status=status, query=query, offset=offset, limit=limit))

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/configuration")
    async def workspace_configure(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "configure_scoped_service_operations")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/announcements")
    async def workspace_announce(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "publish_scoped_service_announcement")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/requests")
    async def workspace_create_request(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "create_scoped_service_request")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/requests/process")
    async def workspace_process_request(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "process_scoped_service_request")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/requests/withdraw")
    async def workspace_withdraw_request(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "withdraw_scoped_service_request")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/api-keys")
    async def workspace_issue_key(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "issue_scoped_service_api_key")

    @app.post("/api/v1/workspaces/{workspace_id}/service-operations/api-keys/revoke")
    async def workspace_revoke_key(workspace_id: str, request: Request, body: dict):
        return await write_scoped("workspace", workspace_id, request, body, "revoke_scoped_service_api_key")

    # --- Platform-scoped routes (/api/v1/platform/service-operations*) ---

    @app.get("/api/v1/platform/service-operations")
    def platform_snapshot(request: Request):
        read_actor(request)
        return etag(request, pg_service().scoped_service_operations_snapshot("platform", None))

    @app.get("/api/v1/platform/service-operations/feedback")
    def platform_feedback(request: Request, scope: str = "mine", status: str = "all", query: str = "", category: str = "", offset: int = 0, limit: int = 24):
        read_actor(request)
        return etag(request, pg_service().scoped_service_feedback("platform", None, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit))

    @app.get("/api/v1/platform/service-operations/drama-requests")
    def platform_drama_requests(request: Request, scope: str = "mine", status: str = "all", query: str = "", offset: int = 0, limit: int = 12):
        read_actor(request)
        return etag(request, pg_service().scoped_service_drama_requests("platform", None, scope=scope, status=status, query=query, offset=offset, limit=limit))

    @app.post("/api/v1/platform/service-operations/configuration")
    async def platform_configure(request: Request, body: dict):
        return await write_scoped("platform", None, request, body, "configure_scoped_service_operations")

    @app.post("/api/v1/platform/service-operations/announcements")
    async def platform_announce(request: Request, body: dict):
        return await write_scoped("platform", None, request, body, "publish_scoped_service_announcement")

    @app.post("/api/v1/platform/service-operations/requests/process")
    async def platform_process_request(request: Request, body: dict):
        return await write_scoped("platform", None, request, body, "process_scoped_service_request")

    # --- Dedicated Bearer service-api routes ---

    @app.get("/api/v1/service-api/projects/{project_id}/jobs")
    def jobs(project_id: str, request: Request, offset: int = 0, limit: int = 50):
        return etag(request, service(project_id).service_api_operation(project_id, "jobs", {"offset": offset, "limit": limit}, client_ip=request.client.host if request.client else None))

    @app.get("/api/v1/service-api/projects/{project_id}/capabilities")
    def capabilities(project_id: str, request: Request):
        return etag(request, service(project_id).service_api_operation(project_id, "capabilities", client_ip=request.client.host if request.client else None))

    @app.get("/api/v1/service-api/projects/{project_id}/jobs/{job_id}")
    def job(project_id: str, job_id: str, request: Request):
        return etag(request, service(project_id).service_api_operation(project_id, "job", {"job_id": job_id}, client_ip=request.client.host if request.client else None))

    @app.get("/api/v1/service-api/projects/{project_id}/usage")
    def usage(project_id: str, request: Request):
        return etag(request, service(project_id).service_api_operation(project_id, "usage", client_ip=request.client.host if request.client else None))

    @app.post("/api/v1/service-api/projects/{project_id}/runs/{operation}")
    async def run(project_id: str, operation: str, request: Request, body: dict):
        if operation not in {"preview", "execute"}:
            raise HTTPException(404, "操作不存在")
        return await run_in_threadpool(service(project_id).service_api_operation, project_id, operation, body, client_ip=request.client.host if request.client else None)

    @app.post("/api/v1/service-api/projects/{project_id}/jobs/{job_id}/cancel")
    async def cancel(project_id: str, job_id: str, request: Request, body: dict):
        if set(body) != {"expected_revision", "idempotency_key"}:
            raise HTTPException(422, "取消需要所见项目版本与请求标识")
        return await run_in_threadpool(service(project_id).service_api_operation, project_id, "cancel", dict(body, job_id=job_id), client_ip=request.client.host if request.client else None)
