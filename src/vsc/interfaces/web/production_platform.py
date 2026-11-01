"""Independent management pages consume the shared application projection."""
from fastapi import HTTPException, Request
from vsc.assets.production_platform import ProductionPlatform


def install_production_platform_routes(router, catalog, etag):
    platform = ProductionPlatform(catalog)

    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "旧项目保持只读；任务与用量需要原 PostgreSQL 权威")
        catalog.service.get_project(project_id)
        return catalog.service

    @router.get("/{project_id}/production-platform")
    def query(project_id: str, request: Request, episode_id: str = None, offset: int = 0, limit: int = 24):
        return etag(request, platform.query(project_id, episode_id=episode_id, offset=offset, limit=limit))

    @router.post("/{project_id}/shot-batch/preview")
    def preview(project_id: str, request: Request, body: dict):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "旧项目只读；制作预览需要原 PostgreSQL 权威")
        return etag(request, catalog.service.preview_shot_batch(project_id, body.get("payload")))

    @router.post("/{project_id}/first-production/preview")
    def first_production(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_first_production(project_id, body.get("payload")))

    @router.get("/{project_id}/execution-authorizations")
    def authorizations(project_id: str, request: Request):
        return etag(request, service(project_id).get_execution_authorizations(project_id))

    @router.post("/{project_id}/production-requirements/preview")
    def requirements(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_production_requirements(project_id, body.get("payload")))

    @router.get("/{project_id}/production-platform/budget")
    def budget(project_id: str, request: Request):
        return etag(request, service(project_id).budget_status(project_id))

    @router.get("/{project_id}/task-center")
    def tasks(project_id: str,request: Request,offset: int=0,limit: int=24,kind: str=None,status: str=None):
        return etag(request,service(project_id).get_task_center(project_id,offset,limit,kind,status))

    @router.get("/{project_id}/production-platform/jobs/{job_id}")
    def job(project_id: str, job_id: str, request: Request):
        value = service(project_id).get_generation_job(project_id, job_id)
        # Connection/auth configuration and raw provider responses never enter a management projection.
        fields = ("id", "project_id", "shot_id", "asset_id", "purpose", "modality", "status", "candidate_no",
            "attempt", "created_at", "updated_at", "model_version", "run_version_id", "outputs", "input_versions")
        result = {key: value.get(key) for key in fields}
        result["events"] = [{key: row.get(key) for key in ("event_type", "created_at")}
                            for row in value.get("events", [])]
        return etag(request, result)
