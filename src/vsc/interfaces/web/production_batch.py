"""Ready-subset execution of an already approved, fixed production run."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from vsc.production.bounded import preview_batch, execute_batch


def install_production_batch_routes(router, catalog, etag, actor):
    def service(project_id, body):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, "批量制作需要 PostgreSQL 项目")
        payload = body.get("payload")
        if not isinstance(payload, dict) or set(payload) - {"run_version_id", "run_sha256", "task_keys"}:
            raise HTTPException(422, "选择固定运行版本及其中需要执行的任务")
        return catalog.service, payload

    @router.post("/{project_id}/production-batch/preview")
    async def preview(project_id: str, request: Request, body: dict):
        current, payload = service(project_id, body)
        return etag(request, await run_in_threadpool(preview_batch, current, project_id, payload))

    @router.post("/{project_id}/production-batch/execute")
    async def execute(project_id: str, request: Request, body: dict):
        current, payload = service(project_id, body)
        return await run_in_threadpool(execute_batch, current, project_id, payload, actor(request))
