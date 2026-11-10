"""Marketing preparation over the existing trusted session and canvas use case."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_marketing_case_routes(app, etag):
    from vsc.assets.marketing_cases import list_cases, get_case

    @app.get("/api/v1/marketing-cases")
    def cases(request: Request, category_name: str = None, keyword: str = "", page: int = 1,
              page_size: int = 20, catalog_sha256: str = None):
        return etag(request, list_cases(category_name, keyword, page, page_size, catalog_sha256))

    @app.get("/api/v1/marketing-cases/{case_id}")
    def detail(case_id: str, request: Request, version: int, sha256: str):
        return etag(request, get_case(dict(id=case_id, version=version, sha256=sha256)))


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

    @router.post("/{project_id}/marketing-canvases/{canvas_id}/start")
    async def start(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        if set(body) != {"payload", "expected_revision", "idempotency_key"} or not isinstance(body.get("payload"), dict):
            raise HTTPException(422, "需要固定开始请求；身份来自当前会话")
        if "canvas_id" in body["payload"]:
            raise HTTPException(422, "画布身份由路径固定")
        return await run_in_threadpool(service(project_id).start_marketing_canvas, project_id,
            dict(body["payload"], canvas_id=canvas_id), expected_revision=body["expected_revision"],
            idempotency_key=body["idempotency_key"], actor=identity)
