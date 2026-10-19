"""Read routes for source work and resource design; writes use the common guard."""
from fastapi import HTTPException, Request


def install_source_resource_routes(router, catalog, etag):
    def service(project_id):
        if catalog._reader(project_id):
            raise HTTPException(409, "旧项目只读；来源解析与资源关系须先显式迁移")
        if catalog.service is None:
            raise HTTPException(503, "PostgreSQL资源服务未配置")
        return catalog.service

    @router.get("/{project_id}/source-workspace")
    def workspace(project_id: str, request: Request):
        return etag(request, service(project_id).get_source_workspace(project_id))

    @router.get("/{project_id}/source-workspace/parse-jobs/{job_id}")
    def job(project_id: str, job_id: str, request: Request):
        return etag(request, service(project_id).get_parse_job(project_id, job_id))

    @router.get("/{project_id}/source-workspace/parse-jobs/{job_id}/preview")
    def preview(project_id: str, job_id: str, request: Request):
        return etag(request, service(project_id).preview_parse_job(project_id, job_id))

    @router.get("/{project_id}/source-workspace/anchors/{anchor_id}")
    def anchor(project_id: str, anchor_id: str, request: Request):
        return etag(request, service(project_id).get_source_anchor(project_id, anchor_id))

    @router.get("/{project_id}/resource-model/categories")
    def categories(project_id: str, request: Request):
        return etag(request, service(project_id).get_resource_taxonomy(project_id))

    @router.get("/{project_id}/resource-model")
    def resources(project_id: str, request: Request, section: str = "resources", object_id: str = None,
                  category: str = None, query: str = "", target_type: str = None,
                  offset: int = 0, limit: int = 100):
        if offset < 0 or not 1 <= limit <= 200:
            raise HTTPException(422, "分页范围不合法")
        current = service(project_id)
        if section == "resources":
            value = current.browse_resources(project_id, object_id=object_id, category=category,
                query=query, target_type=target_type, offset=offset, limit=limit)
        elif section in {"designs", "requirements", "locations"}:
            method, key = {"designs": (current.get_shot_designs, "units"),
                "requirements": (current.get_resource_requirements, "requirements"),
                "locations": (current.get_scene_locations, "locations")}[section]
            value = method(project_id, object_id=object_id)
            rows = value[key]
            value = dict(value, items=rows[offset:offset + limit], total=len(rows),
                         next_offset=offset + limit if offset + limit < len(rows) else None)
        else:
            raise HTTPException(422, "未知资源视图")
        return etag(request, value)

    @router.get("/{project_id}/resource-model/identities/{asset_id}/usage")
    def usage(project_id: str, asset_id: str, request: Request):
        return etag(request, service(project_id).get_asset_usage(project_id, asset_id))
