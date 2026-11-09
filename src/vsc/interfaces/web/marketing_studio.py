"""Marketing preparation over the existing trusted session and canvas use case."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_marketing_studio_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "营销工作室需要 PostgreSQL 权威；旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/marketing-options")
    def options(project_id: str, request: Request):
        return etag(request, service(project_id).marketing_options(project_id))

    @router.post("/{project_id}/marketing-canvases")
    async def prepare(project_id: str, request: Request, body: dict):
        identity = actor(request)
        if not isinstance(body.get("payload"), dict) or "actor" in body:
            raise HTTPException(422, "需要营销输入；身份来自当前会话")
        return await run_in_threadpool(service(project_id).create_marketing_canvas,
            project_id, body["payload"], expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"), actor=identity)
