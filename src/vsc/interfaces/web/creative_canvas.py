"""Creative canvas HTTP and WebSocket collaboration boundary, reusing the local trusted session."""
import asyncio
import json
import time
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from vsc.assets.resource_service import ResourceError


def _now_ms():
    return int(time.time() * 1000)


def parse_request_host(host_header: str) -> str:
    raw = (host_header or "").strip()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[: end + 1] if end != -1 else raw
    return raw.rsplit(":", 1)[0] if ":" in raw else raw


def _with_preview_urls(project_id, document):
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
        return document
    nodes = []
    for node in document["nodes"]:
        item = dict(node)
        if item.get("media_id"):
            item["preview_url"] = f"/api/v1/projects/{project_id}/media/{item['media_id']}/content"
        nodes.append(item)
    return {**document, "nodes": nodes}


class CanvasCollabHub:
    """In-process room broadcaster for live WebSocket canvas collaboration (`sync_protocol = 2`)."""

    def __init__(self):
        self._rooms = {}
        self._lock = asyncio.Lock()

    async def register(self, project_id, canvas_id, session_id, websocket, meta):
        key = (project_id, canvas_id)
        async with self._lock:
            room = self._rooms.setdefault(key, {})
            room[session_id] = {"ws": websocket, "meta": dict(meta), "kicked": False}

    async def unregister(self, project_id, canvas_id, session_id):
        key = (project_id, canvas_id)
        async with self._lock:
            room = self._rooms.get(key)
            if not room:
                return None
            entry = room.pop(session_id, None)
            if not room:
                self._rooms.pop(key, None)
            return entry

    async def _room_snapshot(self, project_id, canvas_id):
        async with self._lock:
            room = self._rooms.get((project_id, canvas_id), {})
            return [(sid, dict(info, meta=dict(info["meta"]))) for sid, info in room.items()]

    async def send(self, project_id, canvas_id, session_id, message):
        peers = await self._room_snapshot(project_id, canvas_id)
        for sid, info in peers:
            if sid == session_id:
                try:
                    await info["ws"].send_json(message)
                except Exception:
                    pass
                break

    async def broadcast(self, project_id, canvas_id, message, *, exclude_session_id=None):
        peers = await self._room_snapshot(project_id, canvas_id)
        for sid, info in peers:
            if exclude_session_id and sid == exclude_session_id:
                continue
            try:
                await info["ws"].send_json(message)
            except Exception:
                pass

    async def kick_sessions(self, project_id, canvas_id, session_ids, reason="same_user_takeover"):
        if not session_ids:
            return
        targets = set(session_ids)
        async with self._lock:
            room = self._rooms.get((project_id, canvas_id), {})
            kicked = []
            for sid in targets:
                entry = room.pop(sid, None)
                if entry:
                    entry["kicked"] = True
                    kicked.append((sid, entry["ws"]))
            if not room and (project_id, canvas_id) in self._rooms:
                self._rooms.pop((project_id, canvas_id), None)
        for sid, ws in kicked:
            try:
                await ws.send_json({
                    "type": "session.kicked",
                    "session_id": sid,
                    "server_ts": _now_ms(),
                    "payload": {"reason": reason, "session_id": sid},
                })
                await ws.close(code=4009, reason=reason)
            except Exception:
                pass

    async def notify_collaboration_changed(self, store, project_id, canvas_id, result):
        peers = await self._room_snapshot(project_id, canvas_id)
        if not peers or store is None:
            return
        room_state = await run_in_threadpool(store.canvas_collab_room_state, project_id, canvas_id)
        if not room_state:
            return
        unlocked_keys = result.get("unlocked_node_keys") or []
        if unlocked_keys:
            await self.broadcast(project_id, canvas_id, {
                "type": "node.unlocked",
                "server_ts": _now_ms(),
                "payload": {"node_keys": unlocked_keys, "fencing_token": 0, "locks": room_state["locks"]},
            })
        session_perms = room_state.get("session_permissions") or {}
        for sid, info in peers:
            s_perm = session_perms.get(sid)
            if s_perm:
                if s_perm["permission"].get("mode") == "forbidden":
                    try:
                        await info["ws"].close(code=4003, reason="access_denied")
                    except Exception:
                        pass
                    continue
                try:
                    await info["ws"].send_json({
                        "type": "permission.changed",
                        "session_id": sid,
                        "server_ts": _now_ms(),
                        "payload": {
                            "canvas_id": canvas_id,
                            "collaboration_enabled": room_state["collaboration_enabled"],
                            "canvas_seq": room_state["canvas_seq"],
                            "permission": s_perm["permission"],
                            "mode": s_perm["mode"],
                        },
                    })
                except Exception:
                    pass
        await self.broadcast(project_id, canvas_id, {
            "type": "members.snapshot",
            "server_ts": _now_ms(),
            "payload": {"members": room_state["members"], "locks": room_state["locks"]},
        })

    async def notify_canvas_saved(self, service, project_id, canvas_id, result, *, actor=None, op_kind="version_saved"):
        peers = await self._room_snapshot(project_id, canvas_id)
        if not peers or service is None:
            return
        try:
            detail = await run_in_threadpool(service.get_creative_canvas, project_id, canvas_id)
        except Exception:
            return
        await self.broadcast(project_id, canvas_id, {
            "type": "canvas.ops.applied",
            "server_ts": _now_ms(),
            "payload": {
                "canvas_seq": detail.get("canvas_seq", result.get("canvas_seq", 1)),
                "version": detail.get("canvas_revision"),
                "version_id": detail.get("version_id"),
                "revision": detail.get("revision"),
                "title": detail.get("title"),
                "document": detail.get("document"),
                "op_kind": op_kind,
                "ops": [{"op": "replace_document", "title": detail.get("title"), "document": detail.get("document")}],
                "actor": actor or "",
            },
        })

    async def notify_node_run_updated(self, project_id, canvas_id, payload):
        peers = await self._room_snapshot(project_id, canvas_id)
        if not peers:
            return
        await self.broadcast(project_id, canvas_id, {
            "type": "node.run.updated",
            "server_ts": _now_ms(),
            "payload": payload,
        })


def install_canvas_library_routes(app, catalog, etag):
    def service():
        if catalog.service is None:
            raise HTTPException(409, '画布库需要已连接的 PostgreSQL 权威')
        return catalog.service

    @app.get('/api/v1/canvas-library/options')
    def options(request: Request):
        return etag(request, service().canvas_library_options())

    @app.get('/api/v1/canvas-library')
    def library(request: Request, project_id: str = None, episode_id: str = None,
                creator_filter: str = 'mine', creator_id: str = None, permission: str = 'all',
                collaboration_only: bool = False, order: str = 'updated_desc', query: str = '',
                offset: int = 0, limit: int = 30):
        return etag(request, service().list_canvas_library(project_id=project_id, episode_id=episode_id,
            creator_filter=creator_filter, creator_id=creator_id, permission=permission,
            collaboration_only=collaboration_only, order=order, query=query, offset=offset, limit=limit))


def install_creative_canvas_routes(router, catalog, etag, actor, *, hub=None):
    hub = hub or CanvasCollabHub()

    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "创作画布需要 PostgreSQL 权威；旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/creative-canvases")
    def listing(project_id: str, request: Request, episode_id: str = None, collaboration_only: bool = False):
        return etag(request, service(project_id).list_creative_canvases(project_id, episode_id, collaboration_only=collaboration_only))

    @router.get("/{project_id}/creative-canvases/{canvas_id}")
    def detail(project_id: str, canvas_id: str, request: Request, version: int = None):
        return etag(request, service(project_id).get_creative_canvas(project_id, canvas_id, version))

    @router.get("/{project_id}/creative-canvases/{canvas_id}/history")
    def history(project_id: str, canvas_id: str, request: Request):
        return etag(request, service(project_id).creative_canvas_history(project_id, canvas_id))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/library-node")
    async def library_node(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "add_canvas_library_node", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/project-media-node")
    async def project_media_node(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "add_canvas_project_media_node", canvas_id)

    @router.get("/{project_id}/creative-canvas-jobs")
    def jobs(project_id: str, request: Request, offset: int = 0, limit: int = 50):
        value = service(project_id).list_generation_jobs(project_id, offset=offset, limit=limit)
        value["items"] = [{key: job[key] for key in ("id", "modality", "status", "purpose", "shot_id", "asset_id", "request_payload")}
                          for job in value["items"]]
        return etag(request, value)

    @router.get("/{project_id}/creative-canvas-run-options")
    def run_options(project_id: str, request: Request):
        from vsc.assets.creative_canvas import canvas_image_tool_options
        use = service(project_id)
        tree = use.get_project_tree(project_id)
        return etag(request, {"nodes": tree["nodes"], "models": use.list_models(), "revision": tree["revision"],
                              "image_tools": canvas_image_tool_options()})

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

    @router.post("/{project_id}/canvas-copies")
    async def direct_copy(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "copy_direct_canvas")

    @router.post("/{project_id}/canvas-copies/preview")
    def direct_copy_preview(project_id: str, request: Request, body: dict):
        payload = body.get('payload')
        if not isinstance(payload, dict) or 'actor' in body:
            raise HTTPException(422, '需要固定画布与目标分集')
        return etag(request, service(project_id).preview_direct_canvas_copy(project_id, payload))

    @router.put("/{project_id}/creative-canvases/{canvas_id}")
    async def save(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "save_creative_canvas", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/collaboration")
    async def collaboration(project_id: str, canvas_id: str, request: Request, body: dict):
        result = await write(project_id, request, body, "set_canvas_collaboration", canvas_id)
        await hub.notify_collaboration_changed(getattr(service(project_id), "store", None), project_id, canvas_id, result)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/collab/ticket")
    async def collab_ticket(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
        if not isinstance(payload, dict) or "actor" in body or "actor" in payload:
            raise HTTPException(422, "需要协作票据参数；身份来自当前会话")
        return await run_in_threadpool(service(project_id).issue_canvas_collab_ticket, project_id, canvas_id, payload, actor=identity)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/recovery/batch")
    async def recovery_batch(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "recover_canvas_batch", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity, op_kind="recovery_batch")
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/copy")
    async def copy(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "copy_creative_canvas", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/split-image")
    async def split_image(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "split_canvas_image", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/prepare")
    async def prepare(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "prepare_creative_canvas", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/domain-nodes")
    async def domain_node(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "create_canvas_domain_node", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/to-edit")
    async def to_edit(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "canvas_node_to_edit", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/candidates")
    async def candidates(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "canvas_node_candidates", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/domain-outputs")
    async def domain_outputs(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "use_canvas_domain_output", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/work-input")
    async def work_input(project_id: str, canvas_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "prepare_canvas_work_input", canvas_id)

    @router.post("/{project_id}/creative-canvases/{canvas_id}/work-quote")
    def work_quote(project_id: str, canvas_id: str, request: Request, body: dict):
        use=service(project_id);use.get_creative_canvas(project_id,canvas_id)
        return etag(request,use.preview_canvas_work_generation(project_id,body.get('payload',{})))

    @router.post("/{project_id}/creative-canvases/{canvas_id}/generate")
    async def generate(project_id: str, canvas_id: str, request: Request, body: dict):
        result = await write(project_id, request, body, "generate_canvas_work", canvas_id)
        await hub.notify_node_run_updated(project_id, canvas_id, {
            "canvas_id": canvas_id,
            "node_id": result.get("node_id"),
            "step_id": result.get("step_id"),
            "run_version_id": result.get("run_version_id"),
            "jobs": result.get("jobs", []),
            "status": "queued",
        })
        return result

    @router.post("/{project_id}/creative-canvases/{canvas_id}/generation-outputs")
    async def generation_outputs(project_id: str, canvas_id: str, request: Request, body: dict):
        identity = actor(request)
        result = await write(project_id, request, body, "adopt_canvas_work_outputs", canvas_id)
        await hub.notify_canvas_saved(service(project_id), project_id, canvas_id, result, actor=identity)
        return result

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


def install_canvas_collab_ws(app, catalog, *, allowed_hosts, origins, hub):
    @app.websocket("/api/v1/projects/{project_id}/creative-canvases/{canvas_id}/collab/ws")
    async def collab_ws(websocket: WebSocket, project_id: str, canvas_id: str):
        host = parse_request_host(websocket.headers.get("host", ""))
        if host not in allowed_hosts:
            await websocket.close(code=1008)
            return
        ws_origin = websocket.headers.get("origin")
        if ws_origin is not None and ws_origin not in origins:
            await websocket.close(code=1008)
            return

        store = getattr(getattr(catalog, "service", None), "store", None)
        if store is None or catalog._reader(project_id) is not None:
            await websocket.close(code=4001, reason="postgres_required")
            return

        sync_protocol = websocket.query_params.get("sync_protocol", "2")
        if sync_protocol != "2":
            await websocket.close(code=4002, reason="unsupported_sync_protocol")
            return

        raw_ticket = websocket.query_params.get("ticket", "")
        raw_last_seq = websocket.query_params.get("client_last_seq")
        client_last_seq = None
        if raw_last_seq is not None and raw_last_seq != "":
            try:
                client_last_seq = int(raw_last_seq)
            except ValueError:
                await websocket.close(code=4002, reason="invalid_client_last_seq")
                return

        try:
            consumed = await run_in_threadpool(
                store.consume_canvas_collab_ticket,
                project_id,
                canvas_id,
                raw_ticket,
                client_last_seq=client_last_seq,
            )
        except ResourceError as exc:
            await websocket.close(code=4003, reason=exc.code)
            return

        await websocket.accept()

        session = consumed["session"]
        sid = session["id"]
        if consumed.get("kicked_session_ids"):
            await hub.kick_sessions(project_id, canvas_id, consumed["kicked_session_ids"], reason="same_user_takeover")
        if consumed.get("unlocked_node_keys"):
            await hub.broadcast(project_id, canvas_id, {
                "type": "node.unlocked",
                "server_ts": _now_ms(),
                "payload": {"node_keys": consumed["unlocked_node_keys"], "fencing_token": 0, "locks": consumed["locks"]},
            })

        await hub.register(project_id, canvas_id, sid, websocket, session)

        ping_task = None
        try:
            doc_with_urls = _with_preview_urls(project_id, consumed["document"])
            await websocket.send_json({
                "type": "session.ready",
                "session_id": sid,
                "server_ts": _now_ms(),
                "payload": {
                    **session,
                    "canvas_id": canvas_id,
                    "project_id": project_id,
                    "version": consumed["version"],
                    "canvas_seq": consumed["canvas_seq"],
                    "revision": consumed["revision"],
                },
            })
            await websocket.send_json({
                "type": "canvas.sync.snapshot",
                "session_id": sid,
                "server_ts": _now_ms(),
                "payload": {
                    "protocol_version": 2,
                    "canvas_seq": consumed["canvas_seq"],
                    "version": consumed["version"],
                    "version_id": consumed["version_id"],
                    "revision": consumed["revision"],
                    "title": consumed["title"],
                    "permission": consumed["permission"],
                    "members": consumed["members"],
                    "locks": consumed["locks"],
                    "canvas_patch": doc_with_urls,
                },
            })
            if consumed.get("sync_required"):
                await websocket.send_json({
                    "type": "canvas.sync.required",
                    "session_id": sid,
                    "server_ts": _now_ms(),
                    "payload": {
                        "canvas_seq": consumed["canvas_seq"],
                        "version": consumed["version"],
                    },
                })
            else:
                for missed in consumed.get("missed_ops") or []:
                    await websocket.send_json({
                        "type": "canvas.ops.applied",
                        "session_id": sid,
                        "server_ts": _now_ms(),
                        "payload": {
                            "canvas_seq": missed["seq"],
                            "op_kind": missed["op_kind"],
                            "ops": missed["ops"],
                            "actor": missed["actor"],
                            "version_id": missed["version_id"],
                        },
                    })

            my_member = next((m for m in consumed["members"] if m["session_id"] == sid), None)
            if my_member:
                await hub.broadcast(project_id, canvas_id, {
                    "type": "member.joined",
                    "server_ts": _now_ms(),
                    "payload": {"member": my_member},
                }, exclude_session_id=sid)
            await hub.broadcast(project_id, canvas_id, {
                "type": "members.snapshot",
                "server_ts": _now_ms(),
                "payload": {"members": consumed["members"], "locks": consumed["locks"]},
            }, exclude_session_id=sid)

            async def heartbeat_loop():
                while True:
                    await asyncio.sleep(20)
                    ts = _now_ms()
                    await websocket.send_json({"type": "ping", "session_id": sid, "server_ts": ts, "payload": {"server_ts": ts}})

            ping_task = asyncio.create_task(heartbeat_loop())

            while True:
                raw_text = await websocket.receive_text()
                raw_bytes = len(raw_text.encode("utf-8"))
                try:
                    envelope = json.loads(raw_text)
                except ValueError:
                    continue
                if not isinstance(envelope, dict) or not isinstance(envelope.get("type"), str):
                    continue
                msg_type = envelope["type"]
                req_id = envelope.get("request_id")
                payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}

                if msg_type == "pong":
                    await run_in_threadpool(store.touch_canvas_collab_session, project_id, canvas_id, sid)
                elif msg_type == "cursor.move":
                    x, y = payload.get("x"), payload.get("y")
                    if (not isinstance(x, bool) and not isinstance(y, bool)
                            and isinstance(x, (int, float)) and isinstance(y, (int, float))
                            and -100000 <= x <= 100000 and -100000 <= y <= 100000):
                        zoom = payload.get("viewport_zoom")
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "cursor.moved",
                            "server_ts": _now_ms(),
                            "payload": {
                                "session_id": sid,
                                "user_id": session["user_id"],
                                "actor": session["actor"],
                                "nickname": session["display_name"],
                                "color": session["color"],
                                "x": float(x),
                                "y": float(y),
                                "viewport_zoom": float(zoom) if isinstance(zoom, (int, float)) and not isinstance(zoom, bool) else 1.0,
                                "ttl_ms": 1500,
                            },
                        }, exclude_session_id=sid)
                elif msg_type == "node.lock.acquire":
                    try:
                        res = await run_in_threadpool(
                            store.acquire_canvas_node_locks,
                            project_id,
                            canvas_id,
                            sid,
                            payload.get("node_keys"),
                            payload.get("intent", "edit"),
                        )
                    except ResourceError as exc:
                        await websocket.send_json({
                            "type": "node.lock.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {
                                "reason": exc.code,
                                "message": str(exc),
                                "node_keys": payload.get("node_keys") or [],
                                "conflicts": [],
                            },
                        })
                        continue
                    if not res["accepted"]:
                        await websocket.send_json({
                            "type": "node.lock.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {
                                "reason": res["reason"],
                                "node_keys": res["node_keys"],
                                "conflicts": res.get("conflicts", []),
                                "permission": res.get("permission"),
                            },
                        })
                    else:
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "node.locked",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {
                                "node_keys": res["node_keys"],
                                "session_id": sid,
                                "owner_user_id": res["owner_user_id"],
                                "owner_actor": res["owner_actor"],
                                "owner_name": res["owner_name"],
                                "color": res["color"],
                                "intent": res["intent"],
                                "fencing_token": res["fencing_token"],
                                "expires_at": res["expires_at"],
                                "participants": res["members"],
                                "locks": res["locks"],
                            },
                        })
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "members.snapshot",
                            "server_ts": _now_ms(),
                            "payload": {"members": res["members"], "locks": res["locks"]},
                        })
                elif msg_type == "node.lock.renew":
                    res = await run_in_threadpool(
                        store.renew_canvas_node_locks,
                        project_id,
                        canvas_id,
                        sid,
                        payload.get("locks"),
                    )
                    if res.get("rejected"):
                        await websocket.send_json({
                            "type": "node.lock.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {"reason": "lease_expired", "node_keys": res["rejected"], "conflicts": []},
                        })
                elif msg_type == "node.lock.release":
                    res = await run_in_threadpool(
                        store.release_canvas_node_locks,
                        project_id,
                        canvas_id,
                        sid,
                        payload.get("locks"),
                    )
                    if res.get("unlocked"):
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "node.unlocked",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {
                                "unlocked": res["unlocked"],
                                "node_keys": [u["node_key"] for u in res["unlocked"]],
                                "fencing_token": max(u["fencing_token"] for u in res["unlocked"]),
                                "locks": res["locks"],
                            },
                        })
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "members.snapshot",
                            "server_ts": _now_ms(),
                            "payload": {"members": res["members"], "locks": res["locks"]},
                        })
                elif msg_type == "node.state.update":
                    if raw_bytes > 262144:
                        await websocket.send_json({
                            "type": "node.state.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {"reason": "payload_too_large"},
                        })
                        continue
                    res = await run_in_threadpool(
                        store.validate_transient_node_preview,
                        project_id,
                        canvas_id,
                        sid,
                        payload.get("updates"),
                    )
                    if not res.get("accepted"):
                        await websocket.send_json({
                            "type": "node.state.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {"reason": res.get("reason", "rejected"), "node_key": res.get("node_key")},
                        })
                    else:
                        await hub.broadcast(project_id, canvas_id, {
                            "type": "node.state.updated",
                            "server_ts": _now_ms(),
                            "payload": {
                                "session_id": sid,
                                "owner_user_id": res["owner_user_id"],
                                "owner_name": res["owner_name"],
                                "color": res["color"],
                                "updates": res["updates"],
                                "ttl_ms": 1300,
                            },
                        }, exclude_session_id=sid)
                elif msg_type == "canvas.ops.submit":
                    res = await run_in_threadpool(
                        store.submit_canvas_collab_ops,
                        project_id,
                        canvas_id,
                        sid,
                        payload,
                    )
                    if not res.get("accepted"):
                        await websocket.send_json({
                            "type": "canvas.ops.rejected",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {k: v for k, v in res.items() if k != "accepted"},
                        })
                    else:
                        doc_out = _with_preview_urls(project_id, res["document"])
                        ack_payload = {
                            "canvas_seq": res["canvas_seq"],
                            "version": res["version"],
                            "version_id": res["version_id"],
                            "revision": res["revision"],
                            "title": res["title"],
                            "document": doc_out,
                            "client_op_id": res.get("client_op_id"),
                        }
                        await websocket.send_json({
                            "type": "canvas.ops.ack",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": ack_payload,
                        })
                        if not res.get("duplicate"):
                            await hub.broadcast(project_id, canvas_id, {
                                "type": "canvas.ops.applied",
                                "server_ts": _now_ms(),
                                "payload": {
                                    "canvas_seq": res["canvas_seq"],
                                    "version": res["version"],
                                    "version_id": res["version_id"],
                                    "revision": res["revision"],
                                    "title": res["title"],
                                    "document": doc_out,
                                    "ops": res["ops"],
                                    "actor": res["actor"],
                                    "author_name": res["author_name"],
                                    "session_id": sid,
                                },
                            }, exclude_session_id=sid)
                elif msg_type == "canvas.sync.request":
                    try:
                        res = await run_in_threadpool(
                            store.sync_canvas_collab_ops,
                            project_id,
                            canvas_id,
                            sid,
                            payload.get("client_last_seq"),
                        )
                    except ResourceError as exc:
                        await websocket.close(code=4003, reason=exc.code)
                        return
                    doc_out = _with_preview_urls(project_id, res["document"])
                    if res.get("sync_required"):
                        await websocket.send_json({
                            "type": "canvas.sync.required",
                            "request_id": req_id,
                            "session_id": sid,
                            "server_ts": _now_ms(),
                            "payload": {
                                "canvas_seq": res["canvas_seq"],
                                "version": res["version"],
                                "title": res["title"],
                                "document": doc_out,
                                "members": res["members"],
                                "locks": res["locks"],
                            },
                        })
                    else:
                        for op_entry in res.get("ops") or []:
                            await websocket.send_json({
                                "type": "canvas.ops.applied",
                                "request_id": req_id,
                                "session_id": sid,
                                "server_ts": _now_ms(),
                                "payload": {
                                    "canvas_seq": op_entry["seq"],
                                    "op_kind": op_entry["op_kind"],
                                    "ops": op_entry["ops"],
                                    "actor": op_entry["actor"],
                                    "version": res["version"],
                                    "title": res["title"],
                                    "document": doc_out,
                                },
                            })
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if ping_task:
                ping_task.cancel()
            entry = await hub.unregister(project_id, canvas_id, sid)
            if entry is not None and not entry.get("kicked"):
                try:
                    closed = await run_in_threadpool(store.close_canvas_collab_session, project_id, canvas_id, sid)
                except Exception:
                    closed = {"unlocked": [], "members": [], "locks": []}
                if closed.get("unlocked"):
                    await hub.broadcast(project_id, canvas_id, {
                        "type": "node.unlocked",
                        "server_ts": _now_ms(),
                        "payload": {
                            "unlocked": closed["unlocked"],
                            "node_keys": closed.get("unlocked_node_keys", []),
                            "fencing_token": max(u["fencing_token"] for u in closed["unlocked"]),
                            "locks": closed.get("locks", []),
                        },
                    })
                await hub.broadcast(project_id, canvas_id, {
                    "type": "member.left",
                    "server_ts": _now_ms(),
                    "payload": {
                        "session_id": sid,
                        "user_id": session["user_id"],
                        "actor": session["actor"],
                    },
                })
                await hub.broadcast(project_id, canvas_id, {
                    "type": "members.snapshot",
                    "server_ts": _now_ms(),
                    "payload": {"members": closed.get("members", []), "locks": closed.get("locks", [])},
                })
