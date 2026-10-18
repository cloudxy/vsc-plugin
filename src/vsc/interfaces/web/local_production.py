"""Local edit previews use the same fixed facts as the eventual proposal."""
from fastapi import HTTPException, Request


def install_local_routes(router, catalog, etag):
    def service(project_id):
        if catalog._reader(project_id) is not None or catalog.service is None:
            raise HTTPException(409, "局部制作需要PostgreSQL权威；旧项目不自动迁移")
        return catalog.service

    @router.get("/{project_id}/local-production/options")
    def options(project_id: str, request: Request, action: str, entity_id: str):
        return etag(request, service(project_id).local_production_options(project_id, action, entity_id))

    @router.post("/{project_id}/local-production/preview")
    def preview(project_id: str, request: Request, body: dict):
        return etag(request, service(project_id).preview_local_production(project_id, body.get("payload")))
