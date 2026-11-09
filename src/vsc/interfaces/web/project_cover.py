"""Project cover reads and writes reuse the original session and command envelope."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_project_cover_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, '封面设置需要 PostgreSQL 项目')
        return catalog.service

    @router.get('/{project_id}/cover')
    def get_cover(project_id: str, request: Request):
        return etag(request, service(project_id).get_project_cover(project_id))

    @router.post('/{project_id}/cover')
    async def set_cover(project_id: str, request: Request, body: dict):
        identity = actor(request)
        if set(body) != {'payload', 'expected_revision', 'idempotency_key'}:
            raise HTTPException(422, '封面写入需要 payload、项目版本和幂等键')
        return await run_in_threadpool(service(project_id).set_project_cover, project_id,
            body['payload'], expected_revision=body['expected_revision'],
            idempotency_key=body['idempotency_key'], actor=identity)
