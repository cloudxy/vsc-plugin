"""Six typed tools with original session, fixed-version downloads and imports."""
from fastapi import HTTPException,Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool


def install_standalone_text_tool_routes(app,catalog,actor):
    @app.post('/api/v1/text-tools/workspace')
    async def workspace(request:Request):
        identity=actor(request)
        if catalog.service is None:raise HTTPException(409,'独立工具需要已配置的资料库')
        return await run_in_threadpool(catalog.service.open_text_tool_workspace,actor=identity)


def install_text_tools_routes(router,catalog,etag,actor):
    def service(project_id):
        if catalog.service is None or catalog._reader(project_id) is not None:
            raise HTTPException(409,"文本与分析工具需要PostgreSQL项目")
        return catalog.service

    @router.get("/{project_id}/text-tools/capabilities")
    def capabilities(project_id:str,request:Request):
        service(project_id).get_project(project_id)
        return etag(request,service(project_id).text_tool_capabilities())

    @router.get("/{project_id}/text-tools/options")
    def options(project_id:str,request:Request):
        return etag(request,service(project_id).text_tool_options(project_id))

    @router.get("/{project_id}/text-tools")
    def listing(project_id:str,request:Request,tool:str,group_key:str=None):
        return etag(request,service(project_id).list_text_tools(project_id,tool,group_key))

    @router.get("/{project_id}/text-tools/units/{unit_id}")
    def detail(project_id:str,unit_id:str,request:Request):
        return etag(request,service(project_id).get_text_tool(project_id,unit_id))

    @router.get("/{project_id}/text-tools/attempts/{attempt_id}")
    def attempt(project_id:str,attempt_id:str,request:Request):
        return etag(request,service(project_id).get_text_tool_attempt(project_id,attempt_id))

    @router.post("/{project_id}/text-tools/extract")
    async def extract(project_id:str,request:Request,body:dict):
        actor(request)
        return await run_in_threadpool(service(project_id).extract_text_tool_source,project_id,body.get("payload"))

    @router.post("/{project_id}/text-tools/import-preview")
    def preview(project_id:str,request:Request,body:dict):
        return etag(request,service(project_id).preview_text_tool_import(project_id,body.get("payload")))

    @router.post('/{project_id}/text-tools/copy-preview')
    def copy_preview(project_id:str,request:Request,body:dict):
        return etag(request,service(project_id).preview_text_tool_copy(project_id,body.get('payload')))

    @router.post('/{project_id}/text-tools/copy')
    async def copy_project(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,'copy_text_tool_to_project')

    async def write(project_id,request,body,method):
        identity=actor(request)
        if not isinstance(body.get("payload"),dict) or "actor" in body:raise HTTPException(422,"输入须为payload；身份来自人工会话")
        return await run_in_threadpool(getattr(service(project_id),method),project_id,body["payload"],
            actor=identity,expected_revision=body.get("expected_revision"),idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/text-tools/units")
    async def save(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"save_text_tool")

    @router.post("/{project_id}/text-tools/lock")
    async def lock(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"set_text_tool_lock")

    @router.post("/{project_id}/text-tools/run")
    async def run(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"run_text_tool")

    @router.post("/{project_id}/text-tools/recover")
    async def recover(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"recover_text_tool_attempt")

    @router.post("/{project_id}/text-tools/accept")
    async def accept(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"accept_text_tool_result")

    @router.post("/{project_id}/text-tools/merge")
    async def merge(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"merge_text_tools")

    @router.post("/{project_id}/text-tools/import")
    async def import_result(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"import_text_tool")

    @router.get("/{project_id}/text-tools/exports/{version_id}")
    def export(project_id:str,version_id:str,format:str):
        data,mime,name=service(project_id).text_tool_export(project_id,version_id,format)
        return Response(data,media_type=mime,headers={"Content-Disposition":'attachment; filename="'+name+'"',"X-VSC-Source-Version":version_id})


    @router.get("/{project_id}/text-tools/styles")
    def styles(project_id:str,request:Request):return etag(request,service(project_id).list_translation_styles(project_id))

    @router.post("/{project_id}/text-tools/styles")
    async def save_style(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"save_translation_style")

    @router.post("/{project_id}/text-tools/novel-import-preview")
    def preview_novel(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_novel_tool_import(project_id,body.get("payload")))

    @router.post("/{project_id}/text-tools/novel-import")
    async def novel(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"import_text_tool_novel")

    @router.post("/{project_id}/text-tools/evidence")
    async def evidence(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"capture_text_tool_evidence")

    @router.post("/{project_id}/text-tools/subtitles-preview")
    def preview_subtitles(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_text_tool_subtitles(project_id,body.get("payload")))

    @router.post("/{project_id}/text-tools/subtitles-apply")
    async def apply_subtitles(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"apply_text_tool_subtitles")

    @router.post("/{project_id}/text-tools/overseas/merge-preview")
    def overseas_merge_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_overseas_merge(project_id,body.get("payload")))

    @router.post("/{project_id}/text-tools/overseas/run-preview")
    def overseas_run_preview(project_id:str,request:Request,body:dict):return etag(request,service(project_id).preview_overseas_group_run(project_id,body.get("payload")))

    @router.post("/{project_id}/text-tools/overseas/merge")
    async def overseas_merge(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"merge_overseas_entities")

    @router.post("/{project_id}/text-tools/overseas/baseline")
    async def overseas_baseline(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"stage_overseas_baseline")

    @router.post("/{project_id}/text-tools/overseas/prepare")
    async def overseas_prepare(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"prepare_overseas_group")

    @router.post("/{project_id}/text-tools/overseas/propose")
    async def overseas_propose(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"propose_overseas_group_run")

    @router.post("/{project_id}/text-tools/overseas/select")
    async def overseas_select(project_id:str,request:Request,body:dict):return await write(project_id,request,body,"select_overseas_candidate")
