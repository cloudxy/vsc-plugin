"""Private account/commerce routes use the original trusted operation session."""
from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool


def install_commerce_routes(router,catalog,etag,actor,read_actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409,"商业账本需要原 PostgreSQL 项目")
        return catalog.service

    @router.get("/{project_id}/commerce")
    def summary(project_id:str,request:Request):
        return etag(request,service(project_id).commerce_summary(project_id,actor=read_actor(request)))

    async def write(project_id,request,body,method):
        identity=actor(request)
        if not isinstance(body.get("payload"),dict) or "actor" in body:raise HTTPException(422,"操作身份来自可信会话")
        return await run_in_threadpool(getattr(service(project_id),method),project_id,body["payload"],
            actor=identity,expected_revision=body.get("expected_revision"),idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/commerce/plans")
    async def plans(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"configure_commerce_plan")

    @router.post("/{project_id}/commerce/orders")
    async def orders(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"create_commerce_order")

    @router.post("/{project_id}/commerce/orders/refresh")
    async def refresh(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"refresh_commerce_order")

    @router.post("/{project_id}/commerce/orders/cancel")
    async def cancel(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"cancel_commerce_order")

    @router.post("/{project_id}/commerce/orders/renew")
    async def renew(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"renew_commerce_order")

    @router.post("/{project_id}/commerce/orders/refund")
    async def refund(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"refund_commerce_order")

    @router.post("/{project_id}/commerce/campaigns")
    async def campaigns(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"configure_commerce_campaign")

    @router.post("/{project_id}/commerce/redeem")
    async def redeem(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"redeem_commerce_campaign")

    @router.post("/{project_id}/commerce/allocations")
    async def allocate(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"allocate_commerce_credits")

    @router.post("/{project_id}/commerce/invoices")
    async def invoices(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"request_commerce_invoice")

    @router.post("/{project_id}/commerce/invoices/refresh")
    async def invoice_refresh(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"refresh_commerce_invoice")

    @router.get("/{project_id}/commerce/invoices/{invoice_id}/content")
    def invoice_content(project_id:str,invoice_id:str,request:Request):
        content,sha=service(project_id).commerce_invoice_content(project_id,invoice_id,actor=read_actor(request))
        return Response(content,media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=invoice.pdf","ETag":'"'+sha+'"',"Cache-Control":"private, no-store"})

    @router.post("/{project_id}/commerce/quote")
    def quote(project_id:str,request:Request,body:dict):
        return etag(request,service(project_id).preview_commerce_charge(project_id,body.get("payload"),actor=actor(request)))


NOTIFICATION_LIMIT = 128 * 1024


def is_commerce_notification(request):
    import re
    return request.method=='POST' and bool(re.fullmatch(r'/api/v1/commerce-notifications/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[0-9a-fA-F-]{36}',request.url.path))


def install_commerce_notification_routes(app,catalog):
    @app.post('/api/v1/commerce-notifications/{gateway_id}/{project_id}')
    async def notification(gateway_id:str,project_id:str,request:Request):
        from vsc.assets.resource_service import ResourceError
        if not is_commerce_notification(request):raise HTTPException(404,'回调入口不存在')
        if catalog.service is None:raise ResourceError('支付服务未配置','payment_unconfigured',503)
        length=request.headers.get('content-length')
        if length is not None:
            try:declared=int(length)
            except ValueError:raise HTTPException(400,'回调长度不合法')
            if declared<0 or declared>NOTIFICATION_LIMIT:raise HTTPException(413,'支付回调超过128KiB')
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>NOTIFICATION_LIMIT:raise HTTPException(413,'支付回调超过128KiB')
            chunks.append(chunk)
        return await run_in_threadpool(catalog.service.handle_commerce_notification,project_id,dict(request.headers),b''.join(chunks),gateway_id=gateway_id)
