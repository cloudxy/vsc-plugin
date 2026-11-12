"""Character studio routes: reference galleries, provider proxy and local ComfyUI proxy.

Provider API keys never reach the server's storage; the browser keeps them locally and
these routes only relay a single request to an allow-listed HTTPS provider or to the
local ComfyUI process.  Both relays require a same-origin page with a live session.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response

from vsc.assets import pose_gallery
from vsc.bootstrap import repository_root

DEFAULT_ALLOWED_ORIGINS = (
    "https://dashscope.aliyuncs.com",
    "https://ark.cn-beijing.volces.com",
    "https://generativelanguage.googleapis.com",
    "https://api.openai.com",
)
MAX_PROXY_BYTES = 10 * 1024 * 1024
FORWARD_HEADERS = ("content-type", "authorization", "x-goog-api-key", "x-dashscope-async")
COMFY_FORWARD_HEADERS = ("content-type", "authorization", "accept")
COMFY_DEFAULTS = ("http://127.0.0.1:8000", "http://127.0.0.1:8188")
_WILDCARD = re.compile(r"^(?:(https?)://)?\*\.([a-z0-9.-]+)(?::(\d+))?(?:/.*)?$", re.I)


def _rule_matches(target, rule: str) -> bool:
    rule = rule.strip()
    if not rule:
        return False
    if rule == "*":
        return True
    wildcard = _WILDCARD.match(rule)
    if wildcard:
        proto, base, port = wildcard.groups()
        if proto and proto.lower() != target.scheme:
            return False
        if (port or "") != (str(target.port) if target.port else ""):
            return False
        host = (target.hostname or "").lower()
        suffix = "." + base.lower().strip(".")
        return host.endswith(suffix) and len(host) > len(suffix)
    parsed = urlsplit(rule if "://" in rule else "https://" + rule)
    return (parsed.scheme, (parsed.hostname or "").lower(), parsed.port) == (target.scheme, (target.hostname or "").lower(), target.port)


def proxy_target_allowed(url: str, extra: str = "") -> bool:
    try:
        target = urlsplit(url)
        target.port  # noqa: B018 - validates the port
    except ValueError:
        return False
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        return False
    try:
        address = ipaddress.ip_address(target.hostname.strip("[]"))
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local
                                or address.is_reserved or address.is_multicast or address.is_unspecified):
        return False
    if (target.hostname or "").lower() in {"localhost"} or (target.hostname or "").lower().endswith(".localhost"):
        return False
    rules = list(DEFAULT_ALLOWED_ORIGINS) + [r for r in re.split(r"[\s,;]+", extra or "") if r]
    return any(_rule_matches(target, rule) for rule in rules)


def _comfy_bases():
    configured = (os.environ.get("COMFYUI_URL") or "").strip().rstrip("/")
    return [configured] if configured else list(COMFY_DEFAULTS)


def install_character_studio_routes(app, etag, read_actor, origin, *, allowed_hosts, origins, sessions):
    def repo():
        return repository_root()

    def page(request, build):
        read_actor(request)
        try:
            return etag(request, build())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/v1/asset-center/pose-gallery/costumes")
    def costumes(request: Request, top: str = "", source: str = "", category: str = "", tag: str = "", q: str = "",
                 safe: bool = True, offset: int = 0, limit: int = pose_gallery.PAGE_SIZE):
        return page(request, lambda: pose_gallery.costume_page(repo(), top=top, source=source, category=category, tag=tag,
                                                               q=q, safe=safe, offset=offset, limit=limit))

    @app.get("/api/v1/asset-center/pose-gallery/poses")
    def poses(request: Request, view: str = "group", system: str = "", category: str = "", angle: str = "", q: str = "",
              safe: bool = True, offset: int = 0, limit: int = pose_gallery.PAGE_SIZE):
        return page(request, lambda: pose_gallery.pose_page(repo(), view=view, system=system, category=category, angle=angle,
                                                            q=q, safe=safe, offset=offset, limit=limit))

    @app.get("/api/v1/asset-center/pose-gallery/portraits")
    def portraits(request: Request, section: str = "", hair: str = "", style: str = "", hot: bool = False, q: str = "",
                  offset: int = 0, limit: int = pose_gallery.PAGE_SIZE):
        return page(request, lambda: pose_gallery.portrait_page(repo(), section=section, hair=hair, style=style, hot=hot,
                                                                q=q, offset=offset, limit=limit))

    @app.post("/api/v1/asset-center/pose-gallery/random")
    def random_pick(request: Request, body: dict):
        read_actor(request)
        slot, safe = body.get("slot"), body.get("safe", True) is not False
        try:
            if slot == "recipe":
                return pose_gallery.random_recipe(repo(), safe=safe)
            item = pose_gallery.random_reference(repo(), slot, scope=body.get("scope", "similar"),
                                                 current_id=str(body.get("current_id") or ""), safe=safe)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"item": item}

    @app.get("/api/v1/asset-center/pose-gallery/media/{subpath:path}")
    def media(subpath: str):
        # Image tags send the session cookie but cannot attach the CSRF header.
        path = pose_gallery.media_file(repo(), subpath)
        if path is None:
            raise HTTPException(404, "参考图不存在")
        return FileResponse(path, media_type=pose_gallery.media_type(path), content_disposition_type="inline",
                            headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/proxy")
    async def provider_proxy(request: Request):
        origin(request)
        read_actor(request)
        target = request.headers.get("x-target-url", "")
        if not target:
            return JSONResponse({"error": {"message": "Missing x-target-url header"}}, status_code=400)
        if not proxy_target_allowed(target, os.environ.get("PROXY_ALLOWED_ORIGINS", "")):
            return JSONResponse({"error": {"message": "Target origin not allowed"}}, status_code=403)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_PROXY_BYTES:
            return JSONResponse({"error": {"message": f"Request body exceeds {MAX_PROXY_BYTES} bytes"}}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_PROXY_BYTES:
                return JSONResponse({"error": {"message": f"Request body exceeds {MAX_PROXY_BYTES} bytes"}}, status_code=413)
        headers = {k: request.headers[k] for k in FORWARD_HEADERS if request.headers.get(k)}
        import httpx
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=False) as client:
                upstream = await client.post(target, content=bytes(body), headers=headers)
        except httpx.HTTPError as error:
            return JSONResponse({"error": {"message": f"Upstream proxy error: {type(error).__name__}"}}, status_code=502)
        return Response(upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get("content-type") or "application/json; charset=utf-8")

    async def comfy_forward(request: Request, subpath: str):
        if request.method != "GET":
            origin(request)
        read_actor(request)
        if ".." in subpath.split("/"):
            raise HTTPException(404, "ComfyUI 路径无效")
        body = await request.body()
        if len(body) > 64 * 1024 * 1024:
            raise HTTPException(413, "上传超过大小限制")
        headers = {k: request.headers[k] for k in COMFY_FORWARD_HEADERS if request.headers.get(k)}
        import httpx
        last = None
        for base in _comfy_bases():
            url = f"{base}/{subpath}"
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    upstream = await client.request(request.method, url, params=list(request.query_params.multi_items()),
                                                    content=body or None, headers=headers)
            except httpx.ConnectError as error:
                last = error
                continue
            except httpx.HTTPError as error:
                return JSONResponse({"error": "comfy_unreachable", "message": f"ComfyUI 请求失败：{type(error).__name__}"}, status_code=502)
            return Response(upstream.content, status_code=upstream.status_code,
                            media_type=upstream.headers.get("content-type") or "application/octet-stream")
        return JSONResponse({"error": "comfy_unreachable", "message": "无法连接本机 ComfyUI（已尝试 " + "、".join(_comfy_bases())
                             + "）。请确认 ComfyUI 已启动，或设置 COMFYUI_URL。" + (f"（{type(last).__name__}）" if last else "")},
                            status_code=502)

    app.add_api_route("/comfy/{subpath:path}", comfy_forward, methods=["GET", "POST"], include_in_schema=False)

    @app.websocket("/comfy/ws")
    async def comfy_ws(websocket: WebSocket):
        from vsc.interfaces.web.creative_canvas import parse_request_host  # noqa: PLC0415
        host = parse_request_host(websocket.headers.get("host", ""))
        ws_origin = websocket.headers.get("origin")
        if host not in allowed_hosts or (ws_origin is not None and ws_origin not in origins) \
                or websocket.cookies.get("vsc_session", "") not in sessions:
            await websocket.close(code=1008)
            return
        requested = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        from websockets.asyncio.client import connect  # noqa: PLC0415
        upstream = None
        for base in _comfy_bases():
            ws_url = re.sub(r"^http", "ws", base) + "/ws"
            if websocket.url.query:
                ws_url += "?" + websocket.url.query
            try:
                upstream = await connect(ws_url, subprotocols=requested or None, open_timeout=8, max_size=None)
                break
            except (OSError, Exception):  # noqa: BLE001 - try the next local port
                upstream = None
        if upstream is None:
            await websocket.close(code=1011)
            return
        await websocket.accept(subprotocol=upstream.subprotocol)

        async def downstream():
            async for message in upstream:
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_text(message)

        async def upstream_pump():
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if message.get("text") is not None:
                    await upstream.send(message["text"])
                elif message.get("bytes") is not None:
                    await upstream.send(message["bytes"])

        tasks = [asyncio.create_task(downstream()), asyncio.create_task(upstream_pump())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except Exception:  # noqa: BLE001
            pass
        finally:
            for task in tasks:
                task.cancel()
            await upstream.close()
            try:
                await websocket.close()
            except RuntimeError:
                pass
