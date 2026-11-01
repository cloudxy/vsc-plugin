"""Creative canvas HTTP boundary, reusing the local trusted session."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_creative_canvas_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "创作画布需要 PostgreSQL 权威；旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/creative-canvases")
    def listing(project_id: str, request: Request, episode_id: str = None):
        return etag(request, service(project_id).list_creative_canvases(project_id, episode_id))

    @router.get("/{project_id}/creative-canvases/{canvas_id}")
    def detail(project_id: str, canvas_id: str, request: Request, version: int = None):
        return etag(request, service(project_id).get_creative_canvas(project_id, canvas_id, version))

    @router.get("/{project_id}/creative-canvases/{canvas_id}/history")
    def history(project_id: str, canvas_id: str, request: Request):
        return etag(request, service(project_id).creative_canvas_history(project_id, canvas_id))

    @router.get("/{project_id}/creative-canvas-jobs")
    def jobs(project_id: str, request: Request, offset: int = 0, limit: int = 50):
        value = service(project_id).list_generation_jobs(project_id, offset=offset, limit=limit)
        value["items"] = [{key: job[key] for key in ("id", "modality", "status", "purpose", "shot_id", "asset_id", "request_payload")}
                          for job in value["items"]]
        return etag(request, value)

    @router.get("/{project_id}/creative-canvas-run-options")
    def run_options(project_id: str, request: Request):
        use = service(project_id)
        tree = use.get_project_tree(project_id)
        return etag(request, {"nodes": tree["nodes"], "models": use.list_models(), "revision": tree["revision"]})

    @router.get("/{project_id}/creative-canvas-versions/{version_id}")
    def fixed_version(project_id:str,version_id:str,request:Request):
        return etag(request,service(project_id).get_creative_canvas_version(project_id,version_id))

    @router.get("/{project_id}/creative-canvas-agent-options")
    def agent_options(project_id:str,request:Request):
        return etag(request,service(project_id).canvas_agent_options(project_id))

    @router.get("/{project_id}/creative-canvases/{canvas_id}/agent-sessions")
    def agent_sessions(project_id:str,canvas_id:str,request:Request):
        return etag(request,service(project_id).list_canvas_agent_sessions(project_id,canvas_id))

    @router.get("/{project_id}/creative-canvas-agent-turns/{turn_id}")
    def agent_turn(project_id:str,turn_id:str,request:Request):
        return etag(request,service(project_id).get_canvas_agent_turn(project_id,turn_id))

    @router.get("/{project_id}/creative-canvas-agent-turns/{turn_id}/run-preview")
    def agent_run_preview(project_id:str,turn_id:str,request:Request):
        return etag(request,service(project_id).preview_canvas_agent_run(project_id,turn_id))

    @router.get("/{project_id}/creative-canvas-templates")
    def templates(project_id:str,request:Request):
        from vsc.assets.access_control import current_principal
        principal=current_principal()
        if principal is None or not principal.identity_id:raise HTTPException(403,"请先登录真实操作身份")
        return etag(request,service(project_id).list_canvas_templates(project_id,principal.actor))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/run-preview")
    def run_preview(project_id: str, canvas_id: str, request: Request, body: dict):
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise HTTPException(422, "需要已保存节点的运行请求")
        return etag(request, service(project_id).preview_creative_canvas_run(project_id, dict(payload, canvas_id=canvas_id)))

    async def write(project_id, request, body, method, canvas_id=None):
        identity = actor(request)
        payload = body.get("payload")
        if not isinstance(payload, dict) or "actor" in body:
            raise HTTPException(422, "需要画布输入；身份来自当前会话")
        if canvas_id:
            if "canvas_id" in payload and payload["canvas_id"] != canvas_id:
                raise HTTPException(422, "画布路径与输入身份不同")
            payload = dict(payload, canvas_id=canvas_id)
        return await run_in_threadpool(getattr(service(project_id), method), project_id, payload,
            expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"), actor=identity)

    @router.post("/{project_id}/creative-canvases")
    async def create(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "create_creative_canvas")

    @router.put("/{project_id}/creative-canvases/{canvas_id}")
    async def save(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "save_creative_canvas", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/copy")
    async def copy(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "copy_creative_canvas", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/prepare")
    async def prepare(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "prepare_creative_canvas", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/run-proposals")
    async def run_proposal(project_id: str, canvas_id: str, request: Request, body: dict):
        payload = body.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("request"), dict) or payload["request"].get("canvas_id") != canvas_id:
            raise HTTPException(422, "运行请求必须来自当前画布")
        return await write(project_id, request, body, "propose_creative_canvas_run")

    @router.post("/{project_id}/creative-canvases/{canvas_id}/agent-turns")
    async def agent_create(project_id:str,canvas_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"create_canvas_agent_turn",canvas_id)

    @router.post("/{project_id}/creative-canvas-agent-turns/{turn_id}/execute")
    async def agent_execute(project_id:str,turn_id:str,request:Request):
        actor(request)
        use=service(project_id)
        if hasattr(use,"authorize_access"):use.authorize_access(project_id,"execute")
        return await run_in_threadpool(use.execute_canvas_agent_turn,project_id,turn_id)

    @router.post("/{project_id}/creative-canvas-agent-turns/{turn_id}/decisions")
    async def agent_decide(project_id:str,turn_id:str,request:Request,body:dict):
        payload=body.get("payload")
        if not isinstance(payload,dict) or payload.get("turn_id",turn_id)!=turn_id:raise HTTPException(422,"任务路径不符")
        return await write(project_id,request,dict(body,payload=dict(payload,turn_id=turn_id)),"decide_canvas_agent_turn")

    @router.post("/{project_id}/creative-canvas-templates")
    async def template_publish(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"publish_canvas_template")

    @router.post("/{project_id}/creative-canvas-templates/{template_id}/favorite")
    async def template_favorite(project_id:str,template_id:str,request:Request,body:dict):
        payload=body.get("payload")
        if not isinstance(payload,dict) or payload.get("template_id",template_id)!=template_id:raise HTTPException(422,"模板路径不符")
        return await write(project_id,request,dict(body,payload=dict(payload,template_id=template_id)),"favorite_canvas_template")

    @router.post("/{project_id}/creative-canvas-template-copies")
    async def template_copy(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"copy_canvas_template")

    @router.post("/{project_id}/creative-canvases/{canvas_id}/execution-preview")
    def execution_preview(project_id:str,canvas_id:str,request:Request,body:dict):
        return etag(request,service(project_id).preview_canvas_execution_batch(project_id,dict(body.get('payload',{}),canvas_id=canvas_id)))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/advance")
    async def advance(project_id:str,canvas_id:str,request:Request,body:dict):
        identity=actor(request)
        return await run_in_threadpool(service(project_id).advance_canvas_execution,project_id,dict(body.get('payload',{}),canvas_id=canvas_id),identity)

    @router.get("/{project_id}/canvas-execution-steps/{step_id}/fallback-preview")
    def fallback_preview(project_id:str,step_id:str,request:Request):return etag(request,service(project_id).preview_canvas_fallback(project_id,step_id))

    @router.post("/{project_id}/canvas-execution-steps/{step_id}/fallback")
    async def fallback(project_id:str,step_id:str,request:Request,body:dict):
        return await write(project_id,request,dict(body,payload=dict(body.get('payload',{}),step_id=step_id)),'propose_canvas_fallback')
