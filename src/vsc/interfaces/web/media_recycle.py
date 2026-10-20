"""Recycle routes retain the standard session, revision and command receipts."""
from fastapi import HTTPException, Request


def install_recycle_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "此项目为只读资料，无法回收；仍可正常查阅")
        return catalog.service

    @router.get("/{project_id}/recycle")
    def read(project_id: str, request: Request, view: str = "trash", offset: int = 0, limit: int = 24):
        return etag(request, service(project_id).list_recycled_media(
            project_id, view=view, offset=offset, limit=limit))

    @router.post("/{project_id}/recycle-preview")
    def preview(project_id: str, body: dict):
        return service(project_id).preview_media_recycle(project_id, body.get("media_ids"))

    @router.post("/{project_id}/recycle-actions")
    def action(project_id: str, request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True:
            raise HTTPException(422, "请先查看影响并确认本次回收或恢复")
        return service(project_id).recycle_media(
            project_id, body.get("payload"), actor=identity,
            expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
