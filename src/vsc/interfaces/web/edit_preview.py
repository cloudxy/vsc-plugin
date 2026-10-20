"""Short HTTP requests; the application lifespan owns the persistent executor."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


def install_edit_preview_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "字幕修改预览需要 PostgreSQL 权威，旧项目保持只读。")
        return catalog.service

    @router.get("/{project_id}/edit-preview-capability")
    def capability(project_id: str, request: Request, render_id: str = None, media_id: str = None, artifact_id: str = None):
        return etag(request, service(project_id).get_edit_preview_capability(project_id,
            render_id=render_id, media_id=media_id, artifact_id=artifact_id))

    @router.post("/{project_id}/edit-preview-requests")
    async def create(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).request_edit_preview, project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.get("/{project_id}/edit-previews")
    def jobs(project_id: str, request: Request, artifact_note_id: str = None):
        return etag(request, service(project_id).list_edit_previews(project_id, artifact_note_id))

    @router.post("/{project_id}/edit-previews/{job_id}/retry")
    async def retry(project_id: str, job_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).retry_edit_preview, project_id, job_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.get("/{project_id}/edit-previews/{job_id}/content")
    def content(project_id: str, job_id: str):
        path, result = service(project_id).edit_preview_content(project_id, job_id)
        return FileResponse(path, media_type="video/mp4", content_disposition_type="inline",
                            headers={"X-VSC-Adoption": "unapproved-edit-preview"})
