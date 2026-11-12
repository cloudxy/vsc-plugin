"""Asset card UI uses the existing project session, revision and receipt boundaries."""
from fastapi import Request, HTTPException
from starlette.concurrency import run_in_threadpool


def install_asset_card_routes(router, catalog, etag, actor):
    def service(p):
        if catalog._reader(p) is not None or catalog.service is None:
            raise HTTPException(409, '项目资产卡需要PostgreSQL权威')
        return catalog.service

    @router.get('/{project_id}/asset-cards')
    def listing(
        project_id: str,
        request: Request,
        query: str = '',
        asset_kind: str = '',
        offset: int = 0,
        limit: int = 24,
        favorites: bool = False,
        include_object: bool = False,
        include_blocking: bool = False,
        folder_id: str = '',
        order_by: str = 'name_asc',
    ):
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        return etag(
            request,
            service(project_id).list_asset_cards(
                project_id,
                query,
                asset_kind,
                offset,
                limit,
                principal.actor if principal else None,
                favorites,
                include_object,
                include_blocking,
                folder_id=folder_id,
                order_by=order_by,
            ),
        )

    @router.get('/{project_id}/asset-card-options')
    def options(project_id: str, request: Request):
        return etag(request, service(project_id).asset_card_options(project_id))

    @router.get('/{project_id}/asset-cards/{asset_id}')
    def detail(project_id: str, asset_id: str, request: Request):
        return etag(request, service(project_id).get_asset_card(project_id, asset_id))

    async def write(p, request, body, method):
        if not isinstance(body.get('payload'), dict):
            raise HTTPException(422, '需要完整资产输入')
        return await run_in_threadpool(
            getattr(service(p), method),
            p,
            body['payload'],
            actor=actor(request),
            expected_revision=body.get('expected_revision'),
            idempotency_key=body.get('idempotency_key'),
        )

    @router.post('/{project_id}/asset-cards')
    async def save(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'save_asset_card')

    @router.post('/{project_id}/asset-cards/favorite')
    async def favorite(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'favorite_asset_card')

    @router.post('/{project_id}/asset-cards/reference')
    async def reference(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'reference_asset_card')

    @router.post('/{project_id}/asset-cards/copy')
    async def copy(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'copy_asset_card')

    @router.post('/{project_id}/asset-cards/folders')
    async def create_folder(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'create_asset_folder')

    @router.post('/{project_id}/asset-cards/folders/update')
    async def update_folder(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'update_asset_folder')

    @router.post('/{project_id}/asset-cards/folders/delete')
    async def delete_folder(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'delete_asset_folder')

    @router.post('/{project_id}/asset-cards/folders/move')
    async def move_folder_items(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'move_assets_to_folder')

    @router.post('/{project_id}/asset-cards/batch-recycle')
    async def batch_recycle(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'batch_recycle_assets')

    @router.post('/{project_id}/asset-cards/manifestation-voice')
    async def manifestation_voice(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, 'save_manifestation_voice')
