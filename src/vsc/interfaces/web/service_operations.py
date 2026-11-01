"""Session-bound operations UI and dedicated Bearer API over original consumers."""
from fastapi import Request,HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool


def install_service_operations_routes(app,router,catalog,etag,actor,read_actor):
    def service(p):
        if catalog.service is None or catalog._reader(p) is not None:raise HTTPException(409,'运营与开放接口需要原PostgreSQL项目')
        return catalog.service

    @router.get('/{project_id}/service-operations')
    def snapshot(project_id:str,request:Request):
        read_actor(request);return etag(request,service(project_id).service_operations_snapshot(project_id))

    async def write(p,request,body,method):
        identity=actor(request)
        if set(body)!={'payload','expected_revision','idempotency_key'}:raise HTTPException(422,'身份来自可信会话；提交固定版本和请求标识')
        return await run_in_threadpool(getattr(service(p),method),p,body['payload'],actor=identity,expected_revision=body['expected_revision'],idempotency_key=body['idempotency_key'])

    @router.post('/{project_id}/service-operations/configuration')
    async def configure(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'configure_service_operations')
    @router.post('/{project_id}/service-operations/announcements')
    async def announce(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'publish_service_announcement')
    @router.post('/{project_id}/service-operations/requests')
    async def create(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'create_service_request')
    @router.post('/{project_id}/service-operations/requests/process')
    async def process(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'process_service_request')
    @router.post('/{project_id}/service-operations/requests/withdraw')
    async def withdraw(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'withdraw_service_request')
    @router.post('/{project_id}/service-operations/account-close/preview')
    async def close_preview(project_id:str,request:Request,body:dict):
        read_actor(request)
        return await run_in_threadpool(service(project_id).preview_account_close,project_id,body)
    @router.post('/{project_id}/service-operations/account-close/execute')
    async def close_account(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'close_service_account')
    @router.post('/{project_id}/service-operations/api-keys')
    async def key(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'issue_service_api_key')
    @router.post('/{project_id}/service-operations/api-keys/revoke')
    async def revoke(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'revoke_service_api_key')
    @router.post('/{project_id}/service-operations/exports/build')
    async def export(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'build_service_export')
    @router.get('/{project_id}/service-operations/exports/{identifier}/content')
    def content(project_id:str,identifier:str,request:Request):
        read_actor(request);raw,sha=service(project_id).service_export_content(project_id,identifier)
        return Response(raw,media_type='application/zip',headers={'Content-Disposition':'attachment; filename=personal-data.zip','ETag':'"'+sha+'"','Cache-Control':'private, no-store'})

    @app.get('/api/v1/service-api/projects/{project_id}/jobs')
    def jobs(project_id:str,request:Request,offset:int=0,limit:int=50):return etag(request,service(project_id).service_api_operation(project_id,'jobs',{'offset':offset,'limit':limit},client_ip=request.client.host if request.client else None))
    @app.get('/api/v1/service-api/projects/{project_id}/jobs/{job_id}')
    def job(project_id:str,job_id:str,request:Request):return etag(request,service(project_id).service_api_operation(project_id,'job',{'job_id':job_id},client_ip=request.client.host if request.client else None))
    @app.get('/api/v1/service-api/projects/{project_id}/usage')
    def usage(project_id:str,request:Request):return etag(request,service(project_id).service_api_operation(project_id,'usage',client_ip=request.client.host if request.client else None))
    @app.post('/api/v1/service-api/projects/{project_id}/runs/{operation}')
    async def run(project_id:str,operation:str,request:Request,body:dict):
        if operation not in {'preview','execute'}:raise HTTPException(404,'操作不存在')
        return await run_in_threadpool(service(project_id).service_api_operation,project_id,operation,body,client_ip=request.client.host if request.client else None)
    @app.post('/api/v1/service-api/projects/{project_id}/jobs/{job_id}/cancel')
    async def cancel(project_id:str,job_id:str,request:Request,body:dict):
        if set(body)!={'expected_revision','idempotency_key'}:raise HTTPException(422,'取消需要所见项目版本与请求标识')
        return await run_in_threadpool(service(project_id).service_api_operation,project_id,'cancel',dict(body,job_id=job_id),client_ip=request.client.host if request.client else None)
