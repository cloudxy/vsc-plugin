"""Same project ACL and CSRF; reading notices never requires editing permission."""
from fastapi import Request, HTTPException
from starlette.concurrency import run_in_threadpool


def install_task_notification_routes(app_or_router, router_or_catalog=None, catalog_or_etag=None, etag_or_read_actor=None, read_actor=None):
    if read_actor is None:
        app = None
        router = app_or_router
        catalog = router_or_catalog
        etag = catalog_or_etag
        read_actor = etag_or_read_actor
    else:
        app = app_or_router
        router = router_or_catalog
        catalog = catalog_or_etag
        etag = etag_or_read_actor

    def pg_service():
        if catalog.service is None:
            raise HTTPException(409, '任务通知需要PostgreSQL权威数据库')
        return catalog.service

    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, '任务通知需要PostgreSQL项目')
        return catalog.service

    if app is not None:
        @app.get('/api/v1/account/task-notifications')
        async def account_listing(
            request: Request,
            limit: int = 20,
            cursor: str = None,
            unread_only: bool = False,
            project_id: str = None,
        ):
            data = await run_in_threadpool(
                pg_service().get_account_task_notifications,
                limit=limit,
                cursor=cursor,
                unread_only=unread_only,
                project_id=project_id,
            )
            return etag(request, data)

        @app.post('/api/v1/account/task-notifications/read')
        async def account_read(request: Request, body: dict):
            read_actor(request)
            if not isinstance(body, dict):
                raise HTTPException(422, '已读状态请求格式无效')
            payload = body['payload'] if set(body) == {'payload'} else body
            return await run_in_threadpool(pg_service().read_account_task_notifications, payload)

    @router.get('/{project_id}/task-notifications')
    async def listing(project_id: str, request: Request, limit: int = 20, cursor: str = None, unread_only: bool = False):
        return await run_in_threadpool(
            service(project_id).get_task_notifications,
            project_id,
            limit=limit,
            cursor=cursor,
            unread_only=unread_only,
        )

    @router.get('/{project_id}/task-center/{kind}/{task_id}')
    async def original(project_id: str, kind: str, task_id: str):
        return await run_in_threadpool(service(project_id).get_task_origin, project_id, kind, task_id)

    @router.post('/{project_id}/task-notifications/read')
    async def read(project_id: str, request: Request, body: dict):
        read_actor(request)
        if set(body) != {'payload'}:
            raise HTTPException(422, '已读状态仅接受通知范围；身份来自当前会话')
        return await run_in_threadpool(service(project_id).read_task_notifications, project_id, body['payload'])
