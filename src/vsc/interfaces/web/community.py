"""Readable local community and fixed template-copy consumers."""
from fastapi import Request,HTTPException,Response
from starlette.concurrency import run_in_threadpool

def install_community_routes(app,router,catalog,etag,actor,read_actor):
    def service():
        if catalog.service is None:raise HTTPException(409,'社区操作需要 PostgreSQL 权威')
        return catalog.service
    @app.get('/api/v1/community')
    def feed(request:Request,query:str='',offset:int=0,limit:int=24):
        read_actor(request);return etag(request,service().community_feed(query,offset,limit))
    @router.get('/{project_id}/community')
    def snapshot(project_id:str,request:Request):return etag(request,service().community_snapshot(project_id))
    @router.get('/{project_id}/community-publications/{publication_id}')
    def detail(project_id:str,publication_id:str,request:Request,version_id:str=None):return etag(request,service().community_detail(project_id,publication_id,version_id))
    @router.get('/{project_id}/community-versions/{version_id}/content')
    def content(project_id:str,version_id:str,request:Request):
        data,mime=service().community_content(project_id,version_id);return Response(data,media_type=mime,headers={'Cache-Control':'private, no-store'})
    async def write(p,request,body,method):
        trusted_actor=actor(request)
        if set(body)!={'payload','expected_revision','idempotency_key'} or not isinstance(body['payload'],dict):raise HTTPException(422,'需要固定内容、所见版本及原请求标识')
        return await run_in_threadpool(getattr(service(),method),p,body['payload'],actor=trusted_actor,expected_revision=body['expected_revision'],idempotency_key=body['idempotency_key'])
    @router.post('/{project_id}/community-rules')
    async def rule(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'save_community_rule')
    @router.post('/{project_id}/community-publications')
    async def save(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'save_community_publication')
    @router.post('/{project_id}/community-publications/state')
    async def state(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'set_community_publication_state')
    @router.post('/{project_id}/community-reports')
    async def report(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'report_community_publication')
    @router.post('/{project_id}/community-moderation')
    async def moderate(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'moderate_community_publication')
    @router.post('/{project_id}/distribution-channels')
    async def channel(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'save_distribution_channel')
    @router.post('/{project_id}/distribution-requests')
    async def prepare(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'prepare_distribution')
    @router.get('/{project_id}/distribution-requests/{request_id}')
    def distribution(project_id:str,request_id:str,request:Request):return etag(request,service().distribution_detail(project_id,request_id))
    @router.post('/{project_id}/distribution-requests/{request_id}/{action}')
    async def execute(project_id:str,request_id:str,action:str,request:Request,body:dict):
        trusted_actor=actor(request)
        if set(body)!={'payload','expected_revision','idempotency_key'}:raise HTTPException(422,'需要固定分发请求及原回执')
        return await run_in_threadpool(service().run_distribution,project_id,request_id,action,body['payload'],actor=trusted_actor,expected_revision=body['expected_revision'],idempotency_key=body['idempotency_key'])
    @router.post('/{project_id}/canvas-template-copy-preview')
    def template_preview(project_id:str,request:Request,body:dict):
        actor(request);return service().preview_canvas_template_copy(project_id,body.get('payload',{}))
    @router.post('/{project_id}/canvas-template-copies')
    async def template_copy(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'copy_fixed_canvas_template')
