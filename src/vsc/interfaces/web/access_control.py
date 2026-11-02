"""Same Cookie/CSRF session; project reads and downloads share the ACL boundary."""
import re
from dataclasses import asdict
from fastapi import Request,HTTPException
from starlette.concurrency import run_in_threadpool
from vsc.assets.access_control import Principal,current_principal,denied,set_principal,reset_principal
from vsc.assets.resource_service import ResourceError

READ_POSTS={'preview','preview-use','run-preview','import-preview','extract','capabilities','options','preview-proposal','quote'}
REVIEW_PATHS={'reviews','artifact-review-notes','review-process','script-notes','commit'}
APPROVE_PATHS={'artifact-decisions','binding-selections','binding-rejections','binding-retirements','rights-decisions','script-note-decisions','script-suggestion-decisions'}
EXECUTE_PATHS={'register-asset','execute','run','generate','local-production-enqueue','generation-jobs','edit-exports'}


def request_principal(request,sessions,local_read=False):
    session=sessions.get(request.cookies.get('vsc_session',''))
    if not session:return Principal(local_read=local_read)
    return Principal(**{k:session[k] for k in Principal.__dataclass_fields__ if k in session})


def authorize_http(service,request):
    if service is None or not hasattr(service,'authorize_access'):return
    path=request.url.path;principal=current_principal();method=request.method
    if not path.startswith('/api/v1/'):return
    if path.startswith('/api/v1/service-api/'):
        if not principal or not principal.api_key_id:denied('开放接口需要专用API凭据')
        with service.store.engine.connect() as conn:service.store._access_principal(conn)
        return
    if principal and principal.api_key_id:denied('API凭据不能用于界面与其他接口')
    # Credential exchange and same-origin session lifecycle perform their own checks.
    if path.startswith('/api/v1/authentication/') or path.startswith('/api/v1/session') or path in {'/api/v1/access/login','/api/v1/access/join'}:return
    if path=='/api/v1/access/share-view':return
    if path.startswith('/api/v1/access'):
        if not principal or not principal.identity_id:denied('账户与团队管理需要成员身份')
        with service.store.engine.connect() as conn:service.store._access_principal(conn)
        return
    if path.startswith('/api/v1/projects/'):
        bits=path.strip('/').split('/');project=bits[3];rest=bits[4:]
        if not re.fullmatch(r'[0-9a-fA-F-]{36}',project):
            if principal and (principal.share_id or principal.identity_id and not principal.local):denied('旧项目未授权给此成员')
            return
        capability='read'
        if method not in {'GET','HEAD','OPTIONS'}:
            end=rest[-1] if rest else ''
            capability='read' if end in READ_POSTS or end.endswith('-preview') else 'review' if end in REVIEW_PATHS else 'approve' if end in APPROVE_PATHS else 'execute' if end in EXECUTE_PATHS else 'edit'
        if method not in {'GET','HEAD','OPTIONS'} and rest and rest[0]=='service-operations':
            action='/'.join(rest[1:])
            if action in {'requests','requests/withdraw','exports/build','api-keys','api-keys/revoke','account-close/preview','account-close/execute'}:capability='read'
            elif action in {'configuration','announcements','requests/process'}:capability='manage'
        if method=='POST' and rest==['task-notifications','read']:capability='read'
        if method=='POST' and rest:
            if rest[0] in {'community-rules','community-moderation','distribution-channels'}:capability='manage'
            elif rest==['community-publications','state'] or rest[0]=='distribution-requests':capability='publish'
            elif rest==['community-reports']:capability='read'
        if method=='POST' and len(rest)==3 and rest[0]=='edit-exports' and rest[-1]=='cancel':capability='execute'
        target_type,target_id=None,None
        if len(rest)==2 and rest[0]=='creative-canvas-versions':target_type,target_id='canvas_version',rest[1]
        elif len(rest)==2 and rest[0]=='creative-canvases':target_type,target_id='canvas',rest[1]
        elif len(rest)==3 and rest[0]=='media' and rest[2]=='content':target_type,target_id='media',rest[1]
        if principal and principal.share_id and not principal.identity_id and method in {'GET','HEAD'} and target_type=='canvas':denied('协作链接使用独立分享视图')
        service.authorize_access(project,capability,target_type=target_type,target_id=target_id)
        return
    if path=='/api/v1/projects':
        if method!='GET' and (not principal or not principal.identity_id):denied('创建项目需要成员身份')
        return
    if principal and principal.share_id and not principal.identity_id:denied('分享会话只能访问明确共享的画布与媒体')
    if path.startswith('/api/v1/library') or path.startswith('/api/v1/asset-center'):
        if not principal or not principal.identity_id:denied('公共素材库需要成员身份，分享不授库访问')
        with service.store.engine.connect() as conn:service.store._access_principal(conn)
    if path.startswith('/api/v1/resource-settings') or path.startswith('/api/v1/execution'):
        if method not in {'GET','HEAD'} and (not principal or not principal.identity_id or not principal.local):denied('本机供应商与执行设置仅由本机操作人管理')


def install_access_routes(app,router,catalog,etag,actor,origin,new_session,sessions):
    def service():
        if catalog.service is None:raise HTTPException(409,'身份与团队管理需要PostgreSQL')
        return catalog.service

    @app.post('/api/v1/access/login')
    async def login(request:Request,body:dict):
        origin(request)
        if set(body)!={'secret'}:raise HTTPException(422,'登录仅接受凭据')
        binding=await run_in_threadpool(service().authenticate_access,body['secret'])
        # A logged-in member can keep their own destination-project authority
        # while adding a read-only source share; a share never creates an identity.
        prior=sessions.get(request.cookies.get('vsc_session',''))
        if binding.get('share_id') and prior and prior.get('identity_id'):
            binding={k:prior[k] for k in Principal.__dataclass_fields__ if k in prior}|{'share_id':binding['share_id']}
        return new_session(binding)

    @app.post('/api/v1/access/join')
    async def join(request:Request,body:dict):
        origin(request)
        binding=await run_in_threadpool(service().accept_access_invitation,body)
        return new_session(binding)

    @app.get('/api/v1/access')
    def snapshot(request:Request):return etag(request,service().access_snapshot())

    @app.get('/api/v1/access/workspaces/{workspace_id}/resources')
    def resources(workspace_id:str,request:Request,offset:int=0,limit:int=24,query:str=''):
        return etag(request,service().access_workspace_resources(workspace_id,offset=offset,limit=limit,query=query))

    @app.post('/api/v1/access/commands/{action}')
    async def command(action:str,request:Request,body:dict):
        identity=actor(request)
        if set(body)!={'payload','expected_revision','idempotency_key'}:raise HTTPException(422,'权限变更需要payload、权限版本和幂等键')
        return await run_in_threadpool(service().access_command,action,body['payload'],actor=identity,expected_revision=body['expected_revision'],idempotency_key=body['idempotency_key'])

    @app.post('/api/v1/access/switch-workspace')
    def switch(request:Request,body:dict):
        actor(request)
        if set(body)!={'workspace_id'}:raise HTTPException(422,'选择一个工作室')
        service().authorize_workspace(body['workspace_id'],'read')
        session=sessions[request.cookies['vsc_session']];session['workspace_id']=body['workspace_id']
        return {'workspace_id':body['workspace_id']}

    @router.get('/{project_id}/access')
    def scope(project_id:str,request:Request):return etag(request,service().access_scope(project_id))

    @router.post('/{project_id}/access-migration-preview')
    def preview(project_id:str,request:Request,body:dict):
        if set(body)!={'workspace_id'}:raise HTTPException(422,'选择目标工作室')
        return etag(request,service().access_migration_preview(project_id,body['workspace_id']))

    @app.get('/api/v1/access/share-view')
    def share_view(request:Request):return etag(request,service().access_share_view())
