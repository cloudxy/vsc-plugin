"""Read-only 创作精选 routes over the local showcase snapshot."""
from fastapi import HTTPException, Request

from vsc.assets.featured_showcase import list_works, read_process, showcase_root


def install_featured_showcase_routes(app, etag, read_actor, root=None):
    def directory():
        return showcase_root(root)

    @app.get("/api/v1/featured-showcase")
    def listing(request: Request, tag_id: str = "0", q: str = "", offset: int = 0, limit: int = 20):
        read_actor(request)
        return etag(request, list_works(directory(), tag_id, q, offset, limit))

    @app.get("/api/v1/featured-showcase/{template_uuid}")
    def process(template_uuid: str, request: Request):
        read_actor(request)
        try:
            payload = read_process(directory(), template_uuid)
        except FileNotFoundError:
            raise HTTPException(404, "创作过程尚未保存到本机") from None
        return etag(request, payload)
