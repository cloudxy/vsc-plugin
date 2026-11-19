"""In-canvas director stage, panorama, recognition and reference-video routes."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_canvas_director_stage_routes(router, catalog, etag, actor, *, hub=None):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "创作画布需要 PostgreSQL 权威；旧项目保持只读")
        return catalog.service

    async def write(project_id, request, body, method, canvas_id):
        identity = actor(request)
        payload = body.get("payload")
        if not isinstance(payload, dict) or "actor" in body:
            raise HTTPException(422, "需要画布输入；身份来自当前会话")
        if "canvas_id" in payload and payload["canvas_id"] != canvas_id:
            raise HTTPException(422, "画布路径与输入身份不同")
        payload = dict(payload, canvas_id=canvas_id)
        result = await run_in_threadpool(
            getattr(service(project_id), method), project_id, payload,
            expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"), actor=identity,
        )
        if hub is not None:
            await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/pic-recognize")
    async def create_recognize(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "create_canvas_pic_recognize", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/pic-recognize/refresh")
    def refresh_recognize(project_id: str, canvas_id: str, request: Request, body: dict):
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if not task_id:
            raise HTTPException(422, "需要识图记录标识")
        return etag(request, service(project_id).refresh_canvas_pic_recognize(project_id, canvas_id, task_id))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/pic-recognize/list")
    def list_recognize(project_id: str, canvas_id: str, request: Request, body: dict):
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        return etag(request, service(project_id).list_canvas_pic_recognize(project_id, canvas_id, payload))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/pic-recognize/delete")
    async def delete_recognize(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "delete_canvas_pic_recognize", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/director-screenshot")
    async def screenshot(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "capture_director_stage_screenshots", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/director-panorama")
    async def panorama(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "generate_director_panorama", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/preview-chat")
    async def preview_chat(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "edit_preview_scene", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/reference-video")
    async def reference_video(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "export_director_reference_video", canvas_id)
