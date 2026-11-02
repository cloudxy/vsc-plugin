"""Same project ACL and CSRF; reading notices never requires editing permission."""
from fastapi import Request,HTTPException
from starlette.concurrency import run_in_threadpool


def install_task_notification_routes(router,catalog,etag,read_actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:raise HTTPException(409,'任务通知需要PostgreSQL项目')
        return catalog.service

    @router.get('/{project_id}/task-notifications')
    async def listing(project_id:str,request:Request,limit:int=20,cursor:str=None,unread_only:bool=False):
        return await run_in_threadpool(service(project_id).get_task_notifications,project_id,limit=limit,cursor=cursor,unread_only=unread_only)

    @router.get('/{project_id}/task-center/{kind}/{task_id}')
    async def original(project_id:str,kind:str,task_id:str):
        return await run_in_threadpool(service(project_id).get_task_origin,project_id,kind,task_id)

    @router.post('/{project_id}/task-notifications/read')
    async def read(project_id:str,request:Request,body:dict):
        read_actor(request)
        if set(body)!={'payload'}:raise HTTPException(422,'已读状态仅接受通知范围；身份来自当前会话')
        return await run_in_threadpool(service(project_id).read_task_notifications,project_id,body['payload'])
