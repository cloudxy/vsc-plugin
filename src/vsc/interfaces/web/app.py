"""Built-in, local resource panel. HTTP delegates to the shared catalog/service."""
import hashlib
import json
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from vsc.adapters.persistence.legacy_json.panel import CatalogError, TEXT_SUFFIXES
from vsc.project.resource_catalog import ResourceCatalog
from vsc.assets.resource_service import ResourceError
from vsc.interfaces.web.resource_graph import install_graph_routes
from vsc.interfaces.web.resource_settings import register_resource_settings
from vsc.interfaces.web.workbench import install_workbench_routes
from vsc.interfaces.web.resource_impact import install_impact_routes
from vsc.interfaces.web.script_workspace import install_script_routes
from vsc.interfaces.web.local_production import install_local_routes
from vsc.interfaces.web.memory import install_memory_routes
from vsc.interfaces.web.source_resource import install_source_resource_routes
from vsc.interfaces.web.review import install_review_routes


def create_app(config=None, catalog=None, service=None):
    config = dict(config or {})
    catalog = catalog or ResourceCatalog(config.get("projects_root", "projects"), service=service,
                                         media_root=config.get("media_root"))
    @asynccontextmanager
    async def lifespan(app):
        store = getattr(getattr(catalog, "service", None), "store", None)
        try:
            if store is not None and hasattr(store, "check_schema"):
                await run_in_threadpool(store.check_schema)
            yield
        finally:
            if config.get("close_service_on_shutdown") and store is not None:
                await run_in_threadpool(store.close)
    app = FastAPI(title="VSC 资源面板", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.catalog = catalog
    sessions = {}
    root = Path(__file__).resolve().parent
    allowed_hosts = set(config.get("allowed_hosts", ["127.0.0.1", "localhost", "[::1]"]))
    origins = set(config.get("allowed_origins", ["http://127.0.0.1:8765", "http://localhost:8765"]))

    @app.middleware("http")
    async def boundary(request, call_next):
        host = request.headers.get("host", "").rsplit(":", 1)[0] if ":" in request.headers.get("host", "") else request.headers.get("host", "")
        if host not in allowed_hosts:
            return JSONResponse({"error": "invalid_host", "message": "仅接受配置的本机地址"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(CatalogError)
    async def catalog_error(request, error):
        return JSONResponse({"error": error.code, "message": error.message}, status_code=error.status_code)

    @app.exception_handler(ResourceError)
    async def resource_error(request, error):
        return JSONResponse({"error": error.code, "message": error.message}, status_code=error.status_code)

    # Keep the core service optional; errors follow its common protocol.
    @app.exception_handler(Exception)
    async def service_error(request, error):
        if hasattr(error, "status_code") and hasattr(error, "code"):
            return JSONResponse({"error": error.code, "message": str(error)}, status_code=error.status_code)
        return JSONResponse({"error": "internal_error", "message": "读取失败，请检查本机服务日志和权威配置"}, status_code=500)

    def etag(request, value):
        value = jsonable_encoder(value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        key = '"' + hashlib.sha256(encoded).hexdigest() + '"'
        if request.headers.get("if-none-match") == key:
            return Response(status_code=304, headers={"ETag": key})
        return JSONResponse(value, headers={"ETag": key})

    def origin(request):
        if request.headers.get("origin") not in origins:
            raise HTTPException(403, "操作来源不可信")

    def actor(request):
        origin(request)
        session = sessions.get(request.cookies.get("vsc_session", ""))
        if not session or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"]):
            raise HTTPException(403, "请先建立本机人工操作会话")
        return session["actor"]

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((root / "templates" / "index.html").read_text("utf-8"))

    @app.post("/api/v1/session")
    def login(request: Request, body: dict):
        origin(request)
        token = config.get("access_token")
        identity = config.get("human_identity")
        if not token or not identity:
            raise HTTPException(403, "本次面板以只读方式启动")
        if not isinstance(body.get("token"), str) or not secrets.compare_digest(body["token"], token):
            raise HTTPException(403, "本机会话凭据无效")
        key, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[key] = {"actor": identity, "csrf": csrf}
        response = JSONResponse({"actor": identity, "csrf_token": csrf})
        response.set_cookie("vsc_session", key, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/v1/session")
    def current_session(request: Request):
        session = sessions.get(request.cookies.get("vsc_session", ""))
        return {"actor": session["actor"] if session else None, "csrf_token": session["csrf"] if session else None,
                "write_available": bool(config.get("access_token") and config.get("human_identity"))}

    router = APIRouter(prefix="/api/v1/projects")

    @router.get("")
    def projects(request: Request):
        return etag(request, catalog.list_projects())

    @router.get("/{project_id}/tree")
    def tree(project_id: str, request: Request):
        return etag(request, catalog.project_tree(project_id))

    @router.get("/{project_id}/artifacts")
    def artifacts(project_id: str, request: Request, object_id: str = None):
        return etag(request, catalog.artifacts(project_id, object_id))

    @router.get("/{project_id}/artifacts/{artifact_id}")
    def artifact(project_id: str, artifact_id: str, request: Request):
        return etag(request, catalog.artifact(project_id, artifact_id))

    @router.get("/{project_id}/sources")
    def sources(project_id: str, request: Request):
        return etag(request, catalog.sources(project_id))

    @router.get("/{project_id}/sources/{source_id}")
    def source_version(project_id: str, source_id: str, request: Request):
        return etag(request, catalog.source(project_id, source_id))

    @router.get("/{project_id}/media")
    def resources(project_id: str, request: Request, object_id: str = None, offset: int = 0, limit: int = 50,
                  modality: str = None, registration: str = None, query: str = None, role: str = None, status: str = None):
        if offset < 0 or not 1 <= limit <= 200:
            raise HTTPException(422, "分页范围不合法")
        return etag(request, catalog.resources(project_id, object_id=object_id, offset=offset, limit=limit,
                                               modality=modality, registration=registration, query=query, role=role, status=status))

    @router.get("/{project_id}/media/{media_id}")
    def media(project_id: str, media_id: str, request: Request):
        return etag(request, catalog.media(project_id, media_id))

    @router.get("/{project_id}/media/{media_id}/lineage")
    def lineage(project_id: str, media_id: str, request: Request):
        return etag(request, catalog.lineage(project_id, media_id))

    @router.get("/{project_id}/media/{media_id}/usage")
    def usage(project_id: str, media_id: str, request: Request):
        return etag(request, catalog.usage(project_id, media_id))

    @router.get("/{project_id}/media/{media_id}/content")
    def content(project_id: str, media_id: str, download: bool = False):
        path = catalog.content_path(project_id, media_id)
        row = catalog.media(project_id, media_id)
        mime = row.get("mime_type", "application/octet-stream")
        if path.suffix.lower() in TEXT_SUFFIXES:
            mime = "text/plain; charset=utf-8"
        # Formats capable of active embedded content are always attachments.
        safe_image = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif", "image/bmp", "image/tiff"}
        safe_inline = mime in safe_image or mime.startswith(("video/", "audio/", "text/plain"))
        disposition = "attachment" if download or not safe_inline else "inline"
        if not safe_inline:
            mime = "application/octet-stream"
        return FileResponse(path, media_type=mime, filename=path.name, content_disposition_type=disposition)

    @router.get("/{project_id}/media/{media_id}/preview")
    def preview(project_id: str, media_id: str, purpose: str = None):
        path, row = catalog.preview(project_id, media_id, purpose=purpose)
        if row.get("mime_type") not in {"image/png", "image/jpeg", "image/webp", "video/mp4"}:
            raise HTTPException(422, "预览副本格式不支持内嵌显示")
        return FileResponse(path, media_type=row["mime_type"], content_disposition_type="inline")

    @router.get("/{project_id}/preview-jobs")
    def preview_jobs(project_id: str, request: Request, media_id: str = None):
        return etag(request, catalog.preview_jobs(project_id, media_id))

    @app.get("/api/v1/preview-capabilities")
    def preview_capabilities():
        from vsc.post.previews import PreviewConverter
        return PreviewConverter().capabilities()

    @router.get("/{project_id}/shots/{shot_id}/context")
    def context(project_id: str, shot_id: str, request: Request):
        return etag(request, catalog.context(project_id, shot_id))

    @router.post("/{project_id}/uploads")
    async def upload(project_id: str, request: Request):
        actor(request)
        project = await run_in_threadpool(catalog.project_tree, project_id)
        if project.get("project", {}).get("read_only") or project.get("project", {}).get("storage_policy") != "postgres-series-v1":
            raise HTTPException(409, "旧项目只读，上传前须显式迁移")
        storage = getattr(getattr(catalog, "service", None), "storage", None)
        if storage is None:
            raise HTTPException(422, "未配置受控上传存储")
        maximum = min(config.get("max_upload_bytes", storage.max_bytes), storage.max_bytes)
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

    actions = {"source-workspace/sources": "create_source_intake",
               "source-workspace/parse-jobs": "create_parse_job",
               "source-workspace/parse-jobs/run": "run_parse_job",
               "source-workspace/prepare-import": "prepare_parse_import",
               "source-workspace/import": "import_parse_job",
               "resource-model/classifications": "classify_resource",
               "media": "register_media", "binding-candidates": "propose_binding", "reviews": "record_review",
               "binding-decisions": "select_candidate", "binding-retirements": "retire_binding",
               "media-lifecycle-decisions": "deprecate_media", "media-operations": "create_media_operation",
               "preview-jobs": "create_preview_job", "media-checks": "record_media_check",
               "binding-rejections": "reject_candidate", "rights-decisions": "decide_rights",
               "objects": "create_object", "artifacts": "create_artifact", "artifact-decisions": "decide_artifact",
               "preview-retries": "retry_preview_job",
               "script-submit": "submit_script_draft", "script-notes": "add_script_note",
               "script-note-decisions": "decide_script_note", "script-suggestions": "add_script_suggestion",
               "script-suggestion-decisions": "decide_script_suggestion",
               "local-production-proposals": "propose_local_production",
               "local-production-enqueue": "enqueue_local_production"}

    def write_endpoint(action):
        def execute(project_id: str, request: Request, body: dict):
            identity = actor(request)
            expected = body.get("expected_revision")
            key = body.get("idempotency_key")
            payload = body.get("payload")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0 or not isinstance(key, str) or not 1 <= len(key) <= 200 or not isinstance(payload, dict):
                raise HTTPException(422, "需要 expected_revision、idempotency_key 和 payload")
            if "actor" in body or "actor" in payload:
                raise HTTPException(422, "操作身份来自本机会话，正文不能指定 actor")
            if action in ("select_candidate", "reject_candidate", "retire_binding", "deprecate_media", "decide_rights", "decide_artifact", "enqueue_local_production") and body.get("confirmed") is not True:
                raise HTTPException(422, "正式选择或停用需要明确人工确认")
            if not hasattr(getattr(catalog, "service", None), action):
                raise HTTPException(422, "当前权威尚未提供该操作")
            if action == "prepare_parse_import":
                if body.get("confirmed") is not True:
                    raise HTTPException(422, "请确认预览中的默认结构与身份映射")
                payload = dict(payload, confirmed=True)
            if action == "register_media" and (not payload.get("staged_upload") or getattr(catalog.service, "storage", None) is None):
                raise HTTPException(422, "登记必须引用受控存储已暂存的上传，不能提交任意路径或自行声明摘要")
            return catalog.write(action, project_id, payload, actor=identity, expected_revision=expected, idempotency_key=key)
        return execute

    for path, action in actions.items():
        router.add_api_route("/{project_id}/" + path, write_endpoint(action), methods=["POST"], name=action)
    install_graph_routes(router, catalog, etag)
    install_workbench_routes(router, catalog, etag)
    install_impact_routes(router, catalog, etag)
    install_script_routes(router, catalog, etag, actor)
    install_local_routes(router, catalog, etag)
    install_memory_routes(router, catalog, etag, actor)
    install_source_resource_routes(router, catalog, etag)
    install_review_routes(router, catalog, etag, actor)
    app.include_router(router)
    register_resource_settings(app, catalog, actor, config)
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")
    return app
