from fastapi import Request,HTTPException
from starlette.concurrency import run_in_threadpool

def install_team_review_routes(router,catalog,etag,actor):
    def service():
        if catalog.service is None:raise HTTPException(409,'团队审核需要PostgreSQL')
        return catalog.service
    @router.get('/{project_id}/team-review')
    def queue(project_id:str,request:Request,lane:str='character',offset:int=0,limit:int=24,status:str|None=None,episode_id:str|None=None,query:str=''):
        return etag(request,service().team_review_queue(project_id,lane,offset=offset,limit=limit,status=status,episode_id=episode_id,query=query))
    async def write(project_id,request,body,method):
        return await run_in_threadpool(getattr(service(),method),project_id,body.get('payload'),actor=actor(request),expected_revision=body.get('expected_revision'),idempotency_key=body.get('idempotency_key'))
    @router.post('/{project_id}/team-review/submit')
    async def submit(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'submit_team_review')
    @router.post('/{project_id}/team-review/commit')
    async def commit(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'commit_team_review')
