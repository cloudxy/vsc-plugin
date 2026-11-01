"""Editable cuts and fixed draft exports; no implicit creative approvals."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.background import BackgroundTask


def install_editor_workspace_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, "剪辑工作稿需要 PostgreSQL 项目")
        return catalog.service

    @router.get("/{project_id}/edit-workspace")
    def get(project_id: str, request: Request, episode_id: str):
        return etag(request, service(project_id).get_edit_workspace(project_id, episode_id))

    @router.post("/{project_id}/edit-workspace")
    async def save(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).save_edit_workspace, project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.get("/{project_id}/edit-seed")
    def seed(project_id: str, request: Request, episode_id: str):
        return etag(request, service(project_id).seed_edit_workspace(project_id, episode_id))

    @router.get('/{project_id}/edit-workspace/{version_id}/timeline-options')
    def timeline_options(project_id: str, version_id: str, request: Request):
        return etag(request, service(project_id).edit_timeline_options(project_id,version_id))

    @router.post('/{project_id}/edit-timeline/preview')
    async def timeline_preview(project_id: str, request: Request, body: dict):
        actor(request)
        return await run_in_threadpool(service(project_id).preview_edit_timeline,project_id,body.get('payload'))

    @router.post('/{project_id}/edit-timeline/proposals')
    async def timeline_propose(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).propose_edit_timeline,project_id,body.get('payload'),
            actor=actor(request),expected_revision=body.get('expected_revision'),idempotency_key=body.get('idempotency_key'))

    @router.post('/{project_id}/edit-timeline/freeze')
    async def timeline_freeze(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).freeze_edit_timeline,project_id,body.get('payload'),
            actor=actor(request),expected_revision=body.get('expected_revision'),idempotency_key=body.get('idempotency_key'))

    @router.post("/{project_id}/edit-exports")
    async def render(project_id: str, request: Request, body: dict):
        return await run_in_threadpool(service(project_id).request_edit_export, project_id, body.get("payload"),
            actor=actor(request), expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.post('/{project_id}/edit-exports/{job_id}/cancel')
    async def cancel(project_id: str, job_id: str, request: Request, body: dict):
        if body.get('payload', {}) not in ({}, {'job_id':job_id}):raise HTTPException(422,'取消仅针对路径中的单次合成')
        return await run_in_threadpool(service(project_id).cancel_edit_export,project_id,{'job_id':job_id},
            actor=actor(request),expected_revision=body.get('expected_revision'),idempotency_key=body.get('idempotency_key'))

    @router.get('/{project_id}/edit-workspace/{version_id}/download')
    def download(project_id: str, version_id: str, kind: str):
        path, mime, temporary = service(project_id).export_edit_workspace(project_id, version_id, kind)
        return FileResponse(path, media_type=mime, filename=path.name,
            background=BackgroundTask(temporary.cleanup), headers={'X-VSC-Adoption':'unapproved-working-edit'})

    @router.get("/{project_id}/edit-exports/{job_id}/content")
    def content(project_id: str, job_id: str, download: bool = False):
        path, result = service(project_id).edit_export_content(project_id, job_id)
        return FileResponse(path, media_type="video/mp4", filename="first-cut.mp4" if download else None,
            content_disposition_type="attachment" if download else "inline", headers={"X-VSC-Adoption": "unapproved-first-cut"})

    @router.get('/{project_id}/edit-exports/{job_id}/cover')
    def cover(project_id: str, job_id: str, at_ms: int = 0):
        path, temporary = service(project_id).edit_export_cover(project_id, job_id, at_ms)
        return FileResponse(path, media_type='image/png', filename='cover.png',
            background=BackgroundTask(temporary.cleanup), headers={'X-VSC-Adoption':'unapproved-working-edit'})
