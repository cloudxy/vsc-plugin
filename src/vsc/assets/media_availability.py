"""Read-time availability, separate from immutable production and review facts."""
from vsc.assets.resource_service import ResourceError


def media_availability(storage, media):
    """Check bounded local metadata only; content delivery still verifies SHA.

    A list refresh must not decode or hash every movie. This observation is not
    a persisted quality verdict, a right to use the media, or human adoption.
    """
    result = {"check": "local_presence_and_size"}
    if storage is None:
        return dict(result, status="unverified", message="素材已登记，当前入口尚不能核验存储副本。")
    locations = [row for row in media.get("locations", []) if row.get("available", True)]
    remote = any(row.get("storage") != "local" for row in locations)
    for row in locations:
        if row.get("storage") != "local":
            continue
        try:
            path = storage.resolve(row["object_key"])
            if not path.is_file() or path.stat().st_size != media.get("size_bytes"):
                continue
            with path.open("rb") as handle:
                handle.read(0)
        except (OSError, ResourceError, KeyError):
            continue
        return dict(result, status="available",
                    message="本地副本可读取；打开内容时核对固定字节，效果仍需审阅。")
    if remote:
        return dict(result, status="unverified", message="素材已登记，远端副本尚未在此入口核验。")
    return dict(result, status="unavailable",
                message="素材记录仍保留，但本地副本缺失或大小不符，请恢复原文件后再回看。")
