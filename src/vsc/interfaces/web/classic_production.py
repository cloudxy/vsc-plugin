"""Classic mode HTTP consumer of the shared trusted session and resource service."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_classic_production_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "经典制作草稿需要 PostgreSQL 权威；旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/classic-production")
    def options(project_id: str, request: Request, shot_id: str):
        return etag(request, service(project_id).classic_production_options(project_id, shot_id))

    @router.post("/{project_id}/classic-production/preview")
    def preview(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_classic_run(project_id, body.get("payload")))

    async def write(project_id, request, body, method):
        identity = actor(request)
        if not isinstance(body.get("payload"), dict) or "actor" in body:
            raise HTTPException(422, "需要草稿输入；身份来自当前会话")
        return await run_in_threadpool(getattr(service(project_id), method), project_id, body["payload"],
            expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"), actor=identity)

    @router.post("/{project_id}/classic-production/drafts")
    async def save(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "save_classic_draft")

    @router.post("/{project_id}/classic-production/run-proposals")
    async def propose(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "propose_classic_run")

    @router.get('/{project_id}/classic-production/candidate-configuration')
    def candidate_configuration(project_id:str,request:Request,shot_id:str,media_id:str):
        return etag(request,service(project_id).classic_candidate_configuration(project_id,shot_id,media_id))

    @router.post('/{project_id}/classic-production/reference-edits')
    async def reference_save(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'save_classic_reference_edit')

    @router.post('/{project_id}/classic-production/reference-exports')
    async def reference_export(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'export_classic_reference_edit')

    @router.post('/{project_id}/classic-production/shots')
    async def shots(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'change_classic_shots')
