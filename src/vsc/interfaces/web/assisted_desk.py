"""Read-only HTTP entry for the task-oriented desk."""
from fastapi import Request
from vsc.assets.assisted_desk import AssistedDesk


def install_assisted_desk_routes(router, catalog, etag):
    desk = AssistedDesk(catalog)

    @router.get("/{project_id}/assisted-desk")
    def query(project_id: str, request: Request, bucket: str = "review", object_id: str = None,
              limit: int = 24, offset: int = 0, revision: int = None):
        return etag(request, desk.query(project_id, bucket=bucket, object_id=object_id,
            limit=limit, offset=offset, revision=revision))
