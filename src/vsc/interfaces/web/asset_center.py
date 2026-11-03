"""Authenticated discovery and cart commands; target writes use original revisions."""
from fastapi import Request,HTTPException


def install_asset_center_routes(app,router,catalog,etag,actor,read_actor):
    def service():
        if catalog.service is None:raise HTTPException(503,"素材中台需要已配置资源服务")
        return catalog.service

    @app.get("/api/v1/asset-center")
    def search(request:Request,query:str="",tag:str="",form_name:str="",asset_kind:str="",workspace_id:str="",review_status:str="",offset:int=0,limit:int=24,media_only:bool=False,source:str="shared",role_level:str="",role_tag:str="",gender:str="",age_band:str=""):
        identity=read_actor(request)
        return etag(request,service().search_asset_center(dict(query=query,tag=tag,form_name=form_name,asset_kind=asset_kind,workspace_id=workspace_id,review_status=review_status,offset=offset,limit=limit,media_only=media_only,source=source,role_level=role_level,role_tag=role_tag,gender=gender,age_band=age_band),identity))

    @app.post("/api/v1/asset-center/official/publish")
    def publish_official(request:Request,body:dict):
        return service().publish_official_asset(body.get("payload"),actor(request))

    @app.post("/api/v1/asset-center/catalog")
    def edit(request:Request,body:dict):
        return service().edit_asset_catalog(body.get("payload"),actor(request))

    @app.get("/api/v1/asset-center/cart")
    def cart(request:Request):return service().asset_center_cart(read_actor(request))

    @app.post("/api/v1/asset-center/cart")
    def cart_change(request:Request,body:dict):return service().change_asset_center_cart(body.get("payload"),actor(request))

    @router.post("/{project_id}/asset-center/import")
    def use(project_id:str,request:Request,body:dict):
        if catalog._reader(project_id) is not None:raise HTTPException(409,"旧项目只读")
        return service().import_asset_center_item(project_id,body.get("payload"),actor=actor(request),
            expected_revision=body.get("expected_revision"),idempotency_key=body.get("idempotency_key"))

    @app.post("/api/v1/asset-center/downloads")
    def download(request:Request,body:dict):return service().request_asset_download(body.get("payload"),actor(request))

    @app.get("/api/v1/asset-center/downloads")
    def downloads(request:Request,offset:int=0,limit:int=24):return service().asset_download_history(read_actor(request),offset,limit)
