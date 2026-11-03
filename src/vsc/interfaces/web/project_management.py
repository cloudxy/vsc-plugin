"""Authenticated management routes; fixed historical evidence remains readable."""
from fastapi import Request, HTTPException
from starlette.concurrency import run_in_threadpool


def install_project_management_routes(app,router,catalog,etag,actor,read_actor):
    def service():
        if catalog.service is None:raise HTTPException(409,'项目管理需要PostgreSQL权威')
        return catalog.service

    @app.get('/api/v1/project-management/recycled')
    def recycled(request:Request):
        read_actor(request)
        return etag(request,service().management_recycled_projects())

    @app.get('/api/v1/project-management/recycle-items')
    def recycle_items(request:Request, kind:str='all', limit:int=24, cursor:str=None):
        read_actor(request)
        return etag(request,service().management_recycle_items(kind=kind,limit=limit,cursor=cursor))

    @router.get('/{project_id}/management')
    def snapshot(project_id:str,request:Request,folder_id:str=None,kind:str=None,q:str='',offset:int=0,limit:int=100):
        return etag(request,service().management_snapshot(project_id,folder_id=folder_id,kind=kind,q=q,offset=offset,limit=limit))

    @router.post('/{project_id}/management')
    async def command(project_id:str,request:Request,body:dict):
        identity=actor(request)
        if set(body)!={'payload','expected_revision','idempotency_key'}:raise HTTPException(422,'管理操作需要固定输入、项目版本和请求标识')
        return await run_in_threadpool(service().management_command,project_id,body['payload'],actor=identity,expected_revision=body['expected_revision'],idempotency_key=body['idempotency_key'])


def management_http_guard(service,request):
    """Working views are closed after recycle; fixed read evidence is preserved."""
    import re
    from sqlalchemy import select
    from vsc.adapters.persistence.postgres import schema as S
    from vsc.adapters.persistence.postgres.project_management import management_project_guard,hidden_object_ids,ProjectManagementRepository
    from vsc.assets.resource_service import ResourceError
    if service is None:return
    match=re.match(r'^/api/v1/projects/([0-9a-fA-F-]{36})/(.+)$',request.url.path)
    if not match:return
    p,rest=match.groups();bits=rest.split('/');read=request.method in {'GET','HEAD','OPTIONS'}
    if bits[0]=='management':return
    fixed=read and (bits[0] in {'artifacts','sources','operation-receipts'} or bits[0]=='media' and len(bits)>=2 or bits[0]=='creative-canvas-versions' or bits[0]=='edit-exports' and bits[-1] in {'content','cover'} or bits[0]=='edit-workspace' and bits[-1]=='download')
    if fixed:return
    with service.store.engine.connect() as conn:
        management_project_guard(conn,p)
        hidden=hidden_object_ids(conn,p)
        if not hidden:return
        for key in ('object_id','shot_id','episode_id','scene_id','scope'):
            if request.query_params.get(key) in hidden:raise ResourceError('此工作范围已回收，请先恢复原关系','object_recycled',409)
        targets=set()
        if bits[0]=='shots' and len(bits)>1:targets.add(bits[1])
        typed={'creative-canvases':'creative_canvases','spatial-scenes':'spatial_scenes','intelligent-workflows':'intelligent_workflows','intelligent-tasks':'intelligent_tasks','creative-canvas-agent-turns':'canvas_agent_turns'}
        if bits[0] in typed and len(bits)>1 and re.fullmatch(r'[0-9a-fA-F-]{36}',bits[1]):
            table=S.metadata.tables[typed[bits[0]]];row=conn.execute(select(table).where(table.c.project_id==p,table.c.id==bits[1])).mappings().first()
            if row:targets=ProjectManagementRepository()._management_targets(conn,p,table,dict(row))
        if targets & hidden:raise ResourceError('此工作稿所属对象已回收；固定审计仍可回看','object_recycled',409)
