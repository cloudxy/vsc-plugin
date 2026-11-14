"""Authenticated discovery and cart commands; target writes use original revisions."""
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse
from vsc.assets.costume_gallery import PAGE_SIZE, cached_costumes, costume_file, costume_page
from vsc.bootstrap import repository_root


def install_asset_center_routes(app, router, catalog, etag, actor, read_actor):
    def service():
        if catalog.service is None:
            raise HTTPException(503, "素材中台需要已配置资源服务")
        return catalog.service

    def costume_assets(*, files_only: bool = False):
        return cached_costumes(repository_root() / "assets", files_only=files_only)

    @app.get("/api/v1/asset-center/costumes")
    def costumes(request: Request, category: str = "", q: str = "", offset: int = 0, limit: int = PAGE_SIZE):
        read_actor(request)
        try:
            page = costume_page(costume_assets()[0], category, q, offset, limit)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return etag(request, page)

    @app.get("/api/v1/asset-center/costumes/{item_id}/content")
    def costume_content(item_id: str):
        # Image tags send the session cookie and cannot attach the CSRF header.
        stem = item_id.replace("-", "").replace("_", "")
        if not item_id.isascii() or not stem.isalnum():
            raise HTTPException(404, "服饰不存在")
        path = costume_file(costume_assets(files_only=True)[1], item_id)
        if path is None:
            path = costume_file(costume_assets(files_only=False)[1], item_id)
        if path is None:
            raise HTTPException(404, "服饰不存在")
        mime = {
            ".png": "image/png",
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(
            path,
            media_type=mime,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/v1/asset-center")
    def search(
        request: Request,
        query: str = "",
        tag: str = "",
        form_name: str = "",
        asset_kind: str = "",
        workspace_id: str = "",
        review_status: str = "",
        offset: int = 0,
        limit: int = 24,
        media_only: bool = False,
        source: str = "shared",
        role_level: str = "",
        role_tag: str = "",
        gender: str = "",
        age_band: str = "",
        order_by: str = "",
    ):
        identity = read_actor(request)
        params = dict(
            query=query,
            tag=tag,
            form_name=form_name,
            asset_kind=asset_kind,
            workspace_id=workspace_id,
            review_status=review_status,
            offset=offset,
            limit=limit,
            media_only=media_only,
            source=source,
            role_level=role_level,
            role_tag=role_tag,
            gender=gender,
            age_band=age_band,
        )
        if order_by:
            params["order_by"] = order_by
        return etag(request, service().search_asset_center(params, identity))

    @app.get("/api/v1/asset-center/official/capabilities")
    def official_capabilities(request: Request):
        return service().official_asset_capabilities(read_actor(request))

    @app.post("/api/v1/asset-center/official/publish")
    def publish_official(request: Request, body: dict):
        return service().publish_official_asset(body.get("payload"), actor(request))

    @app.get('/api/v1/asset-center/official/recycle')
    def official_recycle(request: Request, offset: int = 0, limit: int = 24):
        return etag(request, service().official_media_recycle(read_actor(request), offset, limit))

    @app.get('/api/v1/asset-center/official/recycle/content/{version_id}/{member_key}')
    def official_recycle_content(version_id: str, member_key: str, request: Request):
        # Media elements send the session cookie, without a custom CSRF header.
        # The HTTP boundary already authenticated this library member request.
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        path, mime = service().official_media_recycle_content(version_id, member_key, principal.actor if principal else None)
        return FileResponse(path, media_type=mime, headers={'Cache-Control': 'no-store'}, content_disposition_type='inline')

    @app.get('/api/v1/asset-center/official/entries/{entry_id}')
    def official_detail(entry_id: str, request: Request):
        return etag(request, service().official_asset_detail(entry_id, read_actor(request)))

    @app.post('/api/v1/asset-center/official/media-actions')
    def official_media_action(request: Request, body: dict):
        if body.get('confirmed') is not True:
            raise HTTPException(422, '请确认媒体操作')
        return service().official_media_command(body.get('payload'), actor(request))

    @app.post('/api/v1/asset-center/official/backups')
    def official_backup(request: Request, body: dict):
        return service().attach_official_backup(body.get('payload'), actor(request))

    @app.post('/api/v1/asset-center/official/media-cleanup')
    def official_media_cleanup(request: Request, body: dict):
        return service().official_media_cleanup(body.get('payload'), actor(request))

    @app.post("/api/v1/asset-center/catalog")
    def edit(request: Request, body: dict):
        return service().edit_asset_catalog(body.get("payload"), actor(request))

    @app.get("/api/v1/asset-center/cart")
    def cart(request: Request):
        return service().asset_center_cart(read_actor(request))

    @app.post("/api/v1/asset-center/cart")
    def cart_change(request: Request, body: dict):
        return service().change_asset_center_cart(body.get("payload"), actor(request))

    @app.post("/api/v1/asset-center/cart/clear")
    def cart_clear(request: Request):
        return service().clear_asset_center_cart(actor(request))

    @router.post("/{project_id}/asset-center/import")
    def use(project_id: str, request: Request, body: dict):
        if catalog._reader(project_id) is not None:
            raise HTTPException(409, "旧项目只读")
        return service().import_asset_center_item(
            project_id,
            body.get("payload"),
            actor=actor(request),
            expected_revision=body.get("expected_revision"),
            idempotency_key=body.get("idempotency_key"),
        )

    @app.post("/api/v1/asset-center/downloads")
    def download(request: Request, body: dict):
        return service().request_asset_download(body.get("payload"), actor(request))

    @app.get("/api/v1/asset-center/downloads")
    def downloads(request: Request, offset: int = 0, limit: int = 24):
        return service().asset_download_history(read_actor(request), offset, limit)
