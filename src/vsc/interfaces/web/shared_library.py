"""Global workspace browsing and project-local library commands."""
from pathlib import Path
import tempfile
from urllib.parse import unquote
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


def install_shared_library_routes(app, router, catalog, etag, actor, config=None):
    def service(project_id=None):
        if catalog.service is None:
            raise HTTPException(503, "共享素材库需要已配置的资源服务")
        if project_id and catalog._reader(project_id) is not None:
            raise HTTPException(409, "此项目为只读资料，无法改变引用")
        return catalog.service

    @app.get("/api/v1/library")
    def search(request: Request, query: str = "", category: str = None,
               offset: int = 0, limit: int = 24, include_retired: bool = False):
        return etag(request, service().search_library(query, category, offset, limit, include_retired))

    def migration():
        return service().legacy_library_migration((config or {}).get("legacy_library_root"))

    @app.get("/api/v1/library/migration")
    def migration_preview(request: Request):
        actor(request)
        return migration().preview()

    @app.get("/api/v1/library/migration/compare")
    def migration_compare(request: Request):
        actor(request)
        return migration().compare()

    @app.post("/api/v1/library/migration/preview")
    def migration_preview_permissions(request: Request, body: dict):
        actor(request)
        return migration().preview(body.get("permissions"))

    @app.post("/api/v1/library/migration/import")
    def migration_import(request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True:
            raise HTTPException(422, "请确认固定预览、备份与旧库冻结")
        return migration().import_items(body.get("inventory_sha256"), actor=identity,
            permissions=body.get("permissions"))

    @app.post("/api/v1/library/migration/cutover")
    def migration_cutover(request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True:
            raise HTTPException(422, "请确认迁移核对与旧库只读切换")
        return migration().cutover(actor=identity, allow_pending=body.get("allow_pending") is True)

    @app.get("/api/v1/library/versions/{version_id}")
    def detail(version_id: str, request: Request):
        return etag(request, service().get_library_version(version_id))

    @app.get("/api/v1/library/versions/{version_id}/members/{member_key}/content")
    def content(version_id: str, member_key: str):
        path, mime = service().library_member_content(version_id, member_key)
        safe = mime in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"} or mime.startswith(("audio/", "video/", "text/plain"))
        return FileResponse(path, media_type=mime if safe else "application/octet-stream",
            content_disposition_type="inline" if safe else "attachment")

    @app.post("/api/v1/library/import")
    def import_entry(request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True or not isinstance(body.get("payload"), dict):
            raise HTTPException(422, "请确认导入内容和工作区复用许可")
        return service().import_library(body["payload"], actor=identity)

    @app.post("/api/v1/library/uploads")
    async def upload(request: Request):
        actor(request)
        storage = service().storage
        if storage is None:
            raise HTTPException(422, "共享库导入需要受控存储")
        maximum = min((config or {}).get("max_upload_bytes", storage.max_bytes), storage.max_bytes)
        filename = Path(unquote(request.headers.get("x-filename", "upload.bin"))).name[:240]
        size = 0
        with tempfile.TemporaryFile("w+b") as stream:
            async for block in request.stream():
                size += len(block)
                if size > maximum:
                    raise HTTPException(413, "上传超过配置大小限制")
                await run_in_threadpool(stream.write, block)
            stream.seek(0)
            return await run_in_threadpool(storage.stage_upload, stream, filename)

    @app.post("/api/v1/library/entries/{entry_id}/retire")
    def retire(entry_id: str, request: Request, body: dict):
        identity = actor(request)
        if body.get("confirmed") is not True or not isinstance(body.get("payload"), dict):
            raise HTTPException(422, "请确认停用或权利撤回及原因")
        payload = dict(body["payload"], idempotency_key=body.get("idempotency_key"))
        return service().retire_library(entry_id, payload, actor=identity)

    @router.post("/{project_id}/library/preview-use")
    def preview(project_id: str, body: dict):
        payload = body.get("payload", body)
        if not isinstance(payload, dict):
            raise HTTPException(422, "需要目标与固定库版")
        if "expected_revision" in body:
            payload = dict(payload, expected_revision=body["expected_revision"])
        return service(project_id).preview_library_use(project_id, payload)

    def command(method, confirm_always=False):
        def execute(project_id: str, request: Request, body: dict):
            identity = actor(request)
            payload = body.get("payload")
            if not isinstance(payload, dict):
                raise HTTPException(422, "需要 payload")
            if (confirm_always or payload.get("select") is True) and body.get("confirmed") is not True:
                raise HTTPException(422, "请确认共享内容或本次目标使用决定")
            return getattr(service(project_id), method)(project_id, payload, actor=identity,
                expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))
        return execute
    router.add_api_route("/{project_id}/library/publish", command("publish_library", True), methods=["POST"])
    router.add_api_route("/{project_id}/library/use", command("use_library"), methods=["POST"])
