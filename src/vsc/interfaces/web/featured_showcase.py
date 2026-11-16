"""Read-only 创作精选 routes over the local showcase snapshot."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from vsc.assets.featured_showcase import list_works, read_process, resolve_media_name, showcase_root

MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".avif": "image/avif", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".m4v": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg",
}


def install_featured_showcase_routes(app, etag, read_actor, root=None):
    def directory():
        return showcase_root(root)

    @app.get("/featured-showcase-media/{name}")
    def media(name: str):
        path = resolve_media_name(directory(), name)
        if path is None:
            raise HTTPException(404, "媒体不在本机")
        return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix, "application/octet-stream"))

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
