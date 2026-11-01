"""Project-scoped HTTP uses the original identity, revision and idempotency boundary."""
from fastapi import HTTPException,Request
from starlette.concurrency import run_in_threadpool


def install_intelligent_routes(router,catalog,etag,actor):
    def service(p):
        if catalog._reader(p) is not None or catalog.service is None:raise HTTPException(409,'智能制作需要PostgreSQL权威')
        return catalog.service
    @router.get('/{project_id}/intelligent-options')
    def options(project_id:str,request:Request):return etag(request,service(project_id).intelligent_options(project_id))
    @router.get('/{project_id}/intelligent-workflows')
    def listing(project_id:str,request:Request,episode_id:str=None):return etag(request,service(project_id).list_intelligent_workflows(project_id,episode_id))
    @router.get('/{project_id}/intelligent-workflows/{workflow_id}')
    def detail(project_id:str,workflow_id:str,request:Request,version_id:str=None):return etag(request,service(project_id).get_intelligent_workflow(project_id,workflow_id,version_id))
    @router.get('/{project_id}/intelligent-tasks/{task_id}')
    def task(project_id:str,task_id:str,request:Request):return etag(request,service(project_id).get_intelligent_task(project_id,task_id))
    @router.post('/{project_id}/intelligent-tasks/{task_id}/execute')
    async def execute(project_id:str,task_id:str,request:Request):
        actor(request);return await run_in_threadpool(service(project_id).execute_intelligent_task,project_id,task_id)
    async def write(p,request,body,method):
        identity=actor(request)
        if not isinstance(body.get('payload'),dict) or 'actor' in body:raise HTTPException(422,'需要结构化输入，身份来自当前会话')
        return await run_in_threadpool(getattr(service(p),method),p,body['payload'],expected_revision=body.get('expected_revision'),idempotency_key=body.get('idempotency_key'),actor=identity)
    @router.post('/{project_id}/intelligent-workflows')
    async def create(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'create_intelligent_workflow')
    @router.put('/{project_id}/intelligent-workflows/{workflow_id}')
    async def save(project_id:str,workflow_id:str,request:Request,body:dict):
        if body.get('payload',{}).get('workflow_id')!=workflow_id:raise HTTPException(422,'路径与流程身份不同')
        return await write(project_id,request,body,'save_intelligent_workflow')
    @router.post('/{project_id}/intelligent-change-preview')
    def change_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_intelligent_change(project_id,body.get('payload')))
    @router.post('/{project_id}/intelligent-tasks')
    async def create_task(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'create_intelligent_task')
    @router.post('/{project_id}/intelligent-tasks/{task_id}/decisions')
    async def decision(project_id:str,task_id:str,request:Request,body:dict):
        if body.get('payload',{}).get('task_id')!=task_id:raise HTTPException(422,'路径与任务身份不同')
        return await write(project_id,request,body,'decide_intelligent_task')
    @router.post('/{project_id}/intelligent-drafts')
    async def drafts(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'prepare_intelligent_drafts')
    @router.post('/{project_id}/intelligent-run-preview')
    def run_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_intelligent_runs(project_id,body.get('payload')))
    @router.post('/{project_id}/intelligent-run-proposals')
    async def run_proposals(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'propose_intelligent_runs')
    @router.post('/{project_id}/intelligent-unit-copies')
    async def copy_unit(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'copy_intelligent_unit')
    @router.post('/{project_id}/intelligent-missing-assets-preview')
    def missing_assets_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_intelligent_missing_assets(project_id,body.get('payload',{})))
    @router.post('/{project_id}/intelligent-missing-assets-proposals')
    async def missing_assets_propose(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'propose_intelligent_missing_assets')
    @router.post('/{project_id}/intelligent-advance')
    async def advance(project_id:str,request:Request,body:dict):return await run_in_threadpool(service(project_id).advance_intelligent_runs,project_id,body.get('payload',{}),actor(request))
