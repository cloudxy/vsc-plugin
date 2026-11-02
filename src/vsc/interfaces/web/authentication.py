"""Browser-bound login proofs reuse the original Cookie/CSRF session authority."""
import re,secrets
from urllib.parse import urlencode,urlparse
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse,RedirectResponse
from starlette.concurrency import run_in_threadpool
from vsc.assets.access_control import current_principal


def install_authentication_routes(app,catalog,origin,actor,new_session,sessions):
    def service():
        if catalog.service is None:raise HTTPException(503,'身份登录需要已配置的 PostgreSQL 服务')
        return catalog.service
    def browser(request):
        value=request.cookies.get('vsc_auth_browser','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',value):raise HTTPException(403,'请先打开登录页面，再开始身份验证')
        return value
    def binding_guard(request):
        principal=current_principal()
        if principal and principal.identity_id:actor(request)
    def finish(request,result):
        # Only the real verified subject is allowed to create the existing session.
        old=request.cookies.get('vsc_session','')
        response=new_session(result['session'])
        if request.url.scheme=='https':response.headers['set-cookie']+='; Secure'
        if old:sessions.pop(old,None)
        return response
    @app.get('/api/v1/authentication/options')
    def options(request:Request):
        response=JSONResponse(service().authentication_options())
        value=request.cookies.get('vsc_auth_browser','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',value):response.set_cookie('vsc_auth_browser',secrets.token_urlsafe(32),httponly=True,secure=request.url.scheme=='https',samesite='lax',max_age=3600,path='/')
        return response
    @app.get('/api/v1/authentication/bindings')
    async def bindings(request:Request):
        return await run_in_threadpool(service().authentication_bindings)
    @app.post('/api/v1/authentication/graphic')
    async def graphic(request:Request):
        origin(request);return await run_in_threadpool(service().authentication_graphic,browser(request))
    @app.post('/api/v1/authentication/otp')
    async def otp(request:Request,body:dict):
        origin(request);binding_guard(request)
        return await run_in_threadpool(service().authentication_send_otp,browser(request),body)
    @app.get('/api/v1/authentication/otp/{challenge_id}')
    async def otp_status(challenge_id:str,request:Request):
        return await run_in_threadpool(service().authentication_otp_status,browser(request),challenge_id)
    @app.post('/api/v1/authentication/otp/{challenge_id}/verify')
    async def verify(challenge_id:str,request:Request,body:dict):
        origin(request);binding_guard(request)
        if set(body)!={'code'}:raise HTTPException(422,'只需提交原挑战的验证码')
        result=await run_in_threadpool(service().authentication_verify_otp,browser(request),challenge_id,body['code'])
        return finish(request,result)
    @app.post('/api/v1/authentication/oidc/{provider}/start')
    async def oidc_start(provider:str,request:Request,body:dict):
        origin(request);binding_guard(request)
        if set(body)!={'purpose'}:raise HTTPException(422,'请选择登录或明确绑定当前账号')
        value=await run_in_threadpool(service().authentication_start_oidc,browser(request),provider,body['purpose'])
        return value
    @app.get('/api/v1/authentication/oidc/{provider}/callback')
    async def oidc_callback(provider:str,request:Request,state:str='',code:str='',error:str=''):
        # Cross-site callback carries only the Lax browser cookie. Never trust an
        # absent Strict member cookie for binding; completion is a same-origin POST.
        settings=service()._auth_oidc_settings(provider)
        expected=urlparse(settings['redirect_uri'])
        if str(request.url).split('?',1)[0] != expected.geturl():raise HTTPException(403,'回调地址与固定部署配置不符')
        result=await run_in_threadpool(service().authentication_oidc_callback,browser(request),provider,state,code,bool(error))
        return RedirectResponse('/?'+urlencode({'page':'access','auth_result':result['id'],'auth_status':result['status']}),status_code=303)
    @app.post('/api/v1/authentication/oidc/{attempt_id}/complete')
    async def oidc_complete(attempt_id:str,request:Request,body:dict):
        origin(request);binding_guard(request)
        if body:raise HTTPException(422,'使用原验证完成凭据，不接受替换身份')
        result=await run_in_threadpool(service().authentication_complete_oidc,browser(request),attempt_id)
        return finish(request,result)
