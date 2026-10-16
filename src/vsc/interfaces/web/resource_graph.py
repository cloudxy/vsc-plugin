"""HTTP seam for the shared, read-only resource graph use case."""
from fastapi import Request
from vsc.assets.resource_graph import ResourceGraph


def install_graph_routes(router, catalog, etag):
    graph = ResourceGraph(catalog)

    @router.get("/{project_id}/graph")
    def query(project_id: str, request: Request, object_id: str = None, focus: str = None,
              direction: str = "both", depth: int = 2, limit: int = 100, offset: int = 0, revision: int = None):
        return etag(request, graph.query(project_id, object_id=object_id, focus=focus,
                    direction=direction, depth=depth, limit=limit, offset=offset, revision=revision))
