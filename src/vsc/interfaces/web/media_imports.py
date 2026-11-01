"""Per-file upload, registration and recovery within a fixed import manifest."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_media_import_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, "批量导入需要 PostgreSQL 项目")
        return catalog.service

    @router.get("/{project_id}/media-imports")
    def list_imports(project_id: str, request: Request, offset: int = 0, limit: int = 50):
        return etag(request, service(project_id).list_media_imports(project_id, offset, limit))

    @router.get("/{project_id}/media-imports/{batch_id}")
    def get_import(project_id: str, batch_id: str, request: Request):
        return etag(request, service(project_id).get_media_import(project_id, batch_id))

    async def write(project_id, request, body, method):
        return await run_in_threadpool(getattr(service(project_id), method), project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/media-imports")
    async def create(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "create_media_import")

    @router.post("/{project_id}/media-imports/process")
    async def process(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "process_media_import_item")

    @router.post("/{project_id}/media-imports/cancel")
    async def cancel(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "cancel_media_import_item")

    @router.put("/{project_id}/media-imports/{batch_id}/items/{item_id}/upload")
    async def upload(project_id: str, batch_id: str, item_id: str, request: Request, offset: int = 0):
        identity, data = actor(request), bytearray()
        from vsc.adapters.storage.local.import_upload import ImportUpload
        async for block in request.stream():
            if len(data)+len(block)>ImportUpload.MAX_CHUNK:
                raise HTTPException(413, "每个上传分片最多 8 MiB")
            data.extend(block)
        return await run_in_threadpool(service(project_id).upload_import_chunk, project_id, batch_id,
            item_id, offset, bytes(data), actor=identity)
