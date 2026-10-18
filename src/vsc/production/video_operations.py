"""Fixed-source video operation validation shared by service, PG and worker."""
import math
from vsc.assets.resource_service import ResourceError

SOURCE_ROLE = "operation_source"


def source_duration_ms(media):
    value = (media.get("probe") or {}).get("duration_seconds")
    if value is not None:
        try:
            if math.isfinite(float(value)) and float(value) > 0:
                return math.ceil(float(value) * 1000)
        except (TypeError, ValueError):
            pass
    duration = media.get("duration_ms")
    if type(duration) is not int or duration <= 0:
        raise ResourceError("加工源片缺少已核实的真实时长", "operation_source_invalid")
    return duration


def validate_source_metadata(request, media):
    if media.get("modality") != "video" or media.get("sha256") != request.get("source_sha256"):
        raise ResourceError("加工源片类型或固定SHA不符", "operation_source_mismatch")
    if request.get("source_duration_ms") != source_duration_ms(media):
        raise ResourceError("加工源片时长与已核实字节不符", "operation_source_mismatch")
    if request["operation"] == "edit" and (source_duration_ms(media) > 8700 or
            min(media.get("width") or 0, media.get("height") or 0) > 720):
        raise ResourceError("Grok编辑源片须不超过8.7秒且短边不超过720", "operation_source_invalid")


def verify_operation_source(service, project_id, raw):
    """Before intent: verify registered SHA and decode actual controlled bytes."""
    if not isinstance(raw, dict) or not raw.get("operation"):
        return
    from vsc.production.run_authorization import normalize_request
    request = normalize_request(raw, raw.get("shot_id"), raw.get("purpose", "video_" + raw["operation"]), raw.get("modality", "video"))
    media = service.get_media(project_id, request["source_media_id"])
    validate_source_metadata(request, media)
    if service.storage is None:
        raise ResourceError("加工需要可验证实际源片的受控存储", "storage_required")
    verify_source_bytes(service.storage, media, request)


def verify_source_bytes(storage, media, request):
    """Recheck actual bytes on first submit without changing the approved input."""
    from vsc.adapters.providers.xai_grok.api import video_source_info
    for location in media.get("locations", []):
        if location.get("available") and location.get("storage") == "local":
            path = storage.verify(location["object_key"], request["source_sha256"])
            # LocalStorage.verify returns a path. No arbitrary client path is read.
            try:
                details = video_source_info(path, request["operation"])
            except RuntimeError as exc:
                raise ResourceError(str(exc), "operation_source_invalid") from None
            if math.ceil(float(details["duration"]) * 1000) != request["source_duration_ms"]:
                raise ResourceError("源片实际时长与批准请求不符", "operation_source_mismatch")
            return
    raise ResourceError("加工源片的固定字节不可读取", "media_unavailable")
