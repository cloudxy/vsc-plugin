"""Trusted-session HTTP routes; all provider work stays in original jobs."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def install_standalone_creative_tool_routes(app,catalog,actor):
    @app.post('/api/v1/creative-tools/workspace')
    async def workspace(request:Request):
        identity=actor(request)
        if catalog.service is None:raise HTTPException(409,'独立工具需要已配置的资料库')
        return await run_in_threadpool(catalog.service.open_creative_tool_workspace,actor=identity)


def install_creative_tools_routes(router, catalog, etag, actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409, "音乐与视频工具需要 PostgreSQL 项目；旧项目保持只读")
        return catalog.service

    @router.get("/{project_id}/creative-tools")
    def options(project_id: str, request: Request, object_id: str = None):
        return etag(request, service(project_id).creative_tools_options(project_id, object_id))

    @router.post("/{project_id}/creative-tools/compile-mv")
    def compile_mv(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).compile_creative_mv(project_id, body.get("payload")))

    @router.post("/{project_id}/creative-tools/preview")
    def preview(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_creative_tool_run(project_id, body.get("payload")))

    async def write(project_id, request, body, method):
        identity = actor(request)
        if not isinstance(body.get("payload"), dict) or "actor" in body:
            raise HTTPException(422, "需要工具输入；身份来自可信会话")
        return await run_in_threadpool(getattr(service(project_id), method), project_id, body["payload"],
            actor=identity, expected_revision=body.get("expected_revision"), idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/creative-tools/drafts")
    async def save(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "save_creative_tool_draft")

    @router.post("/{project_id}/creative-tools/import-mv")
    async def import_mv(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "import_creative_mv")

    @router.post("/{project_id}/creative-tools/apply-music")
    async def apply_music(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "apply_creative_music")

    @router.post('/{project_id}/creative-tools/work-input')
    async def work_input(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'prepare_creative_tool_work')

    @router.post('/{project_id}/creative-tools/generate')
    async def generate_work(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'generate_creative_tool_work')

    @router.post('/{project_id}/creative-tools/advance')
    async def advance_work(project_id:str,request:Request,body:dict):return await run_in_threadpool(service(project_id).advance_creative_tool_work,project_id,body.get('payload',{}),actor=actor(request))

    @router.post('/{project_id}/creative-tools/mix-generated')
    async def mix_generated(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'mix_creative_tool_work')

    @router.get('/{project_id}/creative-tools/mv-workspace')
    def mv_workspace(project_id:str,request:Request,draft_version_id:str):return etag(request,service(project_id).creative_mv_workspace(project_id,draft_version_id))

    @router.post('/{project_id}/creative-tools/mv-shot-input')
    async def mv_shot_input(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'prepare_creative_mv_shot')

    @router.post('/{project_id}/creative-tools/mv-shot-preview')
    def mv_shot_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_workbench_generation(project_id,body.get('payload')))

    @router.post('/{project_id}/creative-tools/mv-shot-generate')
    async def mv_shot_generate(project_id:str,request:Request,body:dict):return await write(project_id,request,body,'generate_workbench')

    @router.post("/{project_id}/creative-tools/run-proposals")
    async def propose(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "propose_creative_tool_run")

    @router.post("/{project_id}/creative-tools/process-local")
    async def process_local(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "process_creative_tool_local")

    @router.post("/{project_id}/creative-tools/use-output")
    async def use_output(project_id: str, request: Request, body: dict):
        return await write(project_id, request, body, "use_creative_tool_output")

    @router.post('/{project_id}/creative-tools/import-preview')
    def import_preview(project_id:str,request:Request,body:dict):
        return etag(request,service(project_id).preview_creative_output_import(project_id,body.get('payload')))

    @router.post('/{project_id}/creative-tools/import-output')
    async def import_output(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,'import_creative_output')

    @router.get("/{project_id}/creative-tools/lyrics/{identifier}")
    def lyrics_result(project_id:str,identifier:str,request:Request):return etag(request,service(project_id).get_creative_lyrics(project_id,identifier))

    @router.post("/{project_id}/creative-tools/lyrics")
    async def lyrics(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"create_creative_lyrics")

    @router.post("/{project_id}/creative-tools/analyze-music")
    async def analyze(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"analyze_creative_music")

    @router.post("/{project_id}/creative-tools/accept-music-result")
    async def accept(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"accept_creative_music_result")

    @router.post("/{project_id}/creative-tools/mv-edit-preview")
    def mv_edit_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_creative_mv_edit(project_id,body.get('payload')))

    @router.post("/{project_id}/creative-tools/mv-edit")
    async def mv_edit(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"apply_creative_mv_edit")
