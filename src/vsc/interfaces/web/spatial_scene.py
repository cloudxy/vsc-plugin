"""Shared scene editor routes for blocking units and independent previs."""
from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from vsc.assets.spatial_scene import (
    BODY_PRESETS,
    CAMERA_PRESETS,
    JOINT_GROUPS,
    POSE_CATALOG,
    default_scene,
    normalize_scene,
)
import shutil


def install_spatial_scene_routes(router,catalog,etag,actor):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409,"三维场景需要 PostgreSQL 权威；旧项目保持原状态")
        return catalog.service

    @router.get("/{project_id}/spatial-scene-options")
    def options(project_id:str,request:Request):
        tree=service(project_id).get_project_tree(project_id)
        return etag(request,{"nodes":tree["nodes"],"revision":tree["revision"],"default_document":default_scene(),
            "body_presets":BODY_PRESETS,"pose_catalog":POSE_CATALOG,"camera_presets":CAMERA_PRESETS,"joint_groups":JOINT_GROUPS,
            "capabilities":{"png":True,"glb_static":True,"mp4":bool(shutil.which("ffmpeg")),"skinned_glb":True,"textured_glb":True,"glb_animation":True,"scene_agent":True,"batch_views":True,"auto_frame":True,"panorama_sky":True}})

    @router.get("/{project_id}/spatial-scenes")
    def listing(project_id:str,request:Request,mode:str=None):
        return etag(request,service(project_id).list_spatial_scenes(project_id,mode))

    @router.get("/{project_id}/spatial-scenes/{scene_id}")
    def detail(project_id:str,scene_id:str,request:Request,version:int=None):
        return etag(request,service(project_id).get_spatial_scene(project_id,scene_id,version))

    @router.post("/{project_id}/spatial-preview")
    async def preview(project_id:str,body:dict):
        image=await run_in_threadpool(service(project_id).preview_spatial_scene,project_id,body)
        return Response(image,media_type="image/png")

    @router.post("/{project_id}/spatial-viewport")
    async def viewport(project_id:str,body:dict):
        image=await run_in_threadpool(service(project_id).capture_spatial_viewport,project_id,body)
        return Response(image,media_type="image/png")

    @router.post("/{project_id}/spatial-auto-frame")
    def auto_frame(project_id:str,request:Request,body:dict):
        actor(request)
        return service(project_id).auto_frame_spatial_scene(project_id,body.get("payload",body))

    @router.post("/{project_id}/spatial-scene-validate")
    def validate(project_id:str,body:dict):
        service(project_id).get_project(project_id)
        document=normalize_scene(body.get("document"))
        service(project_id).prepare_spatial_scene(project_id,document)
        return {"document":document,"model_catalog":service(project_id).spatial_model_catalog(project_id,document)}

    @router.post("/{project_id}/spatial-model-import")
    async def model_import(project_id:str,body:dict):
        return await run_in_threadpool(service(project_id).import_spatial_glb,project_id,body.get("media_id"))

    async def write(project_id,request,body,method,extra=None):
        identity=actor(request);payload=body.get("payload")
        if not isinstance(payload,dict) or "actor" in body:
            raise HTTPException(422,"需要场景输入；操作身份来自会话")
        if extra:
            if any(name in payload and payload[name]!=value for name,value in extra.items()):raise HTTPException(422,"路径与场景身份不符")
            payload=dict(payload,**extra)
        return await run_in_threadpool(getattr(service(project_id),method),project_id,payload,actor=identity,
            expected_revision=body.get("expected_revision"),idempotency_key=body.get("idempotency_key"))

    @router.post("/{project_id}/spatial-scenes")
    async def create(project_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"create_spatial_scene")

    @router.put("/{project_id}/spatial-scenes/{scene_id}")
    async def save(project_id:str,scene_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"save_spatial_scene",{"spatial_scene_id":scene_id})

    @router.post("/{project_id}/spatial-scenes/{scene_id}/batch-views")
    async def batch_views(project_id:str,scene_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"capture_spatial_batch_views",{"spatial_scene_id":scene_id})

    @router.post("/{project_id}/spatial-scenes/{scene_id}/exports")
    async def export(project_id:str,scene_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"create_spatial_export",{"spatial_scene_id":scene_id})

    @router.get("/{project_id}/spatial-exports/{export_id}")
    def export_detail(project_id:str,export_id:str,request:Request):
        result=service(project_id).get_spatial_export(project_id,export_id)
        result.pop("claim_token",None)
        return etag(request,result)

    @router.post("/{project_id}/spatial-exports/{export_id}/execute")
    async def execute(project_id:str,export_id:str,request:Request):
        actor(request)
        return await run_in_threadpool(service(project_id).execute_spatial_export,project_id,export_id)

    @router.post("/{project_id}/spatial-exports/{export_id}/cancel")
    async def cancel(project_id:str,export_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"cancel_spatial_export",{"export_id":export_id})

    @router.post("/{project_id}/spatial-exports/{export_id}/canvas")
    async def canvas(project_id:str,export_id:str,request:Request,body:dict):
        return await write(project_id,request,body,"spatial_export_to_canvas",{"export_id":export_id})

    @router.post("/{project_id}/spatial-scenes/{scene_id}/plans")
    async def plan_create(project_id:str,scene_id:str,request:Request,body:dict):
        return await write(project_id,request,body,'create_spatial_plan_task',{'spatial_scene_id':scene_id})

    @router.get("/{project_id}/spatial-plans/{task_id}")
    def plan_get(project_id:str,task_id:str,request:Request):return etag(request,service(project_id).get_spatial_plan_task(project_id,task_id))

    @router.post("/{project_id}/spatial-plans/{task_id}/execute")
    async def plan_execute(project_id:str,task_id:str,request:Request):
        actor(request)
        return await run_in_threadpool(service(project_id).execute_spatial_plan_task,project_id,task_id)

    @router.post("/{project_id}/spatial-plans/{task_id}/decisions")
    async def plan_decision(project_id:str,task_id:str,request:Request,body:dict):
        return await write(project_id,request,body,'decide_spatial_plan_task',{'task_id':task_id})
