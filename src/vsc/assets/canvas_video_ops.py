"""Local canvas video, still and script derivations. No paid provider calls.

Configured model ids are quoted only. Bytes come from Pillow Lanczos or ffmpeg.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from vsc.assets.resource_service import ResourceError

CODE = "invalid_canvas_video_script"
IMAGE_TYPES = ("general", "low_resolution", "3d_animation", "high_fidelity", "text_optimization")
IMAGE_SCALES = (2, 4, 6)
IMAGE_BYTES_MAX = int(4.7 * 1024 * 1024)
VIDEO_RESOLUTIONS = {"1080p": 1080, "2k": 1440, "4k": 2160}
REMAKE_RESOLUTIONS = {"480p": 480, "720p": 720, "1080p": 1080, "2k": 1440, "4k": 2160}
SLOW_FACTORS = (1, 2, 3, 5)
MV_TYPES = {"narrative": "剧情叙事", "emotional": "情绪表达", "performance": "歌手表演", "mixed": "混合"}
ASPECTS = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1", "custom": "用户指定"}
STORY_COLUMNS = (
    ("shot", "镜号"),
    ("range", "起止"),
    ("shot_size", "景别"),
    ("angle", "机位"),
    ("movement", "运动"),
    ("focus", "焦距景深"),
    ("light", "光线"),
    ("narrative", "叙事"),
    ("description", "画面描述"),
    ("image_prompt", "图像提示词"),
    ("motion_prompt", "运动提示词"),
    ("voice", "人声/音效"),
    ("music", "背景音乐"),
    ("keyframe", "关键帧缩略图"),
)
MEDIA_DIAGNOSTICS = {
    "asset_voice_name": "{name}音色",
    "audio_decode_unsupported": "当前浏览器不支持音频解码",
    "audio_not_playable": "音频资源不可播放",
    "audio_playback_failed": "音频播放失败",
    "audio_resource_read_failed": "音频资源读取失败",
    "capture_area_init_failed": "截图区域初始化失败",
    "capture_generate_failed": "截图生成失败",
    "crop_session_expired": "裁剪会话已失效",
    "role_voice": "角色音色",
    "video_frame_capture_failed": "视频帧截图失败",
    "video_frame_read_failed": "视频帧读取失败",
    "video_size_read_failed": "视频尺寸读取失败",
}
OPERATIONS = frozenset({
    "multi_video_edit", "image_upscale", "video_upscale", "video_segment_remake",
    "video_dewatermark", "video_depth_map", "video_breakdown", "video_script_extract",
    "video_story", "sample_upgrade", "lyrics_timeline", "lyrics_storyboard",
    "script_generator", "script_document_bind", "mv_brief",
})
_TAG = re.compile(r"\[(\d{2}):(\d{2})\.(\d{3})-(\d{2}):(\d{2})\.(\d{3})\]")
_SHOT_SIZES = ("全景", "中景", "近景", "特写")
_ANGLES = ("平视", "俯拍", "仰拍", "平视")
_MOVES = ("固定", "推进", "横移", "拉远")


def _fail(message):
    raise ResourceError(message, CODE)


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise ResourceError(f"本机未安装 {name}，无法处理音视频", "local_tool_unavailable")
    return path


def _run(args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResourceError("本机处理工具缺失或超过时间上限；输入仍保留", "local_tool_unavailable") from exc
    if result.returncode:
        detail = (result.stderr or b"").decode("utf-8", "replace")[:300]
        raise ResourceError("视频合成导出失败" if "ffmpeg" in Path(args[0]).name else "固定素材无法按所选参数处理" + (f"：{detail}" if detail else ""), "local_tool_failed")
    return result


def timecode(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    minutes, rem = divmod(ms, 60000)
    secs, milli = divmod(rem, 1000)
    return f"{minutes:02d}:{secs:02d}.{milli:03d}"


def _tag_seconds(minutes, seconds, milli):
    return int(minutes) * 60 + int(seconds) + int(milli) / 1000


def prompt_tags(prompt):
    if not isinstance(prompt, str):
        return []
    return [_tag_seconds(*match) for match in _TAG.findall(prompt) for match in [match]]


def _pairs(prompt):
    found = []
    for match in _TAG.finditer(prompt or ""):
        a, b, c, d, e, f = match.groups()
        found.append((_tag_seconds(a, b, c), _tag_seconds(d, e, f)))
    return found


def validate_image_spec(content, *, image_count=1):
    if image_count != 1:
        _fail("仅支持单张 JPEG 或 PNG")
    if not isinstance(content, (bytes, bytearray)) or not content:
        _fail("仅支持单张 JPEG 或 PNG")
    raw = bytes(content)
    if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n")):
        _fail("仅支持单张 JPEG 或 PNG")
    if len(raw) > IMAGE_BYTES_MAX:
        _fail("图片不能超过 4.7MB")
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.size
    except Exception as exc:
        raise ResourceError("仅支持单张 JPEG 或 PNG", CODE) from exc
    if width > 4096 or height > 4096:
        _fail("图片宽高不能超过 4096")
    if width < 1 or height < 1 or not (1 / 3 <= (width / height) <= 3):
        _fail("宽高比须在 1:3 至 3:1 之间")
    return width, height


def validate_remake(duration, segments, prompt, *, resolution="720p"):
    if not _finite(duration) or float(duration) < 4:
        _fail("仅支持不短于 4 秒的视频")
    if not isinstance(segments, list) or not segments:
        _fail("请至少选择 1 个重拍片段")
    if len(segments) > 5:
        _fail("最多支持 5 个重拍片段")
    key = str(resolution or "720p").lower()
    if key not in REMAKE_RESOLUTIONS:
        _fail("重拍分辨率须为 480P、720P、1080P、2K 或 4K")
    normal = []
    for segment in segments:
        if not isinstance(segment, dict):
            _fail("每个片段至少 4 秒，且不能超出视频时长")
        start, end = segment.get("start"), segment.get("end")
        if not _finite(start) or not _finite(end):
            _fail("每个片段至少 4 秒，且不能超出视频时长")
        start, end = float(start), float(end)
        if end - start < 4 - 1e-3 or start < -1e-3 or end > float(duration) + 0.05:
            _fail("每个片段至少 4 秒，且不能超出视频时长")
        normal.append((round(start, 3), round(end, 3)))
    ordered = sorted(normal)
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt[0] < prev[1] - 1e-3:
            _fail("重拍片段之间不能重叠")
    tags = _pairs(prompt if isinstance(prompt, str) else "")
    if len(tags) != len(ordered) or any(abs(a - b) > 0.001 or abs(c - d) > 0.001 for (a, c), (b, d) in zip(tags, ordered)):
        _fail("提示词中的时间标签与重拍片段不一致")
    return {"segments": [{"start": a, "end": b} for a, b in ordered], "resolution": key, "prompt": prompt or ""}


def validate_depth(clarity, duration):
    key = str(clarity or "").lower()
    if key not in {"480p", "720p"}:
        _fail("清晰度须为 480p 或 720p")
    if not _finite(duration) or float(duration) <= 0:
        _fail("无法读取视频时长")
    limit = 180 if key == "480p" else 30
    if float(duration) > limit + 1e-6:
        _fail("480P 最长支持 3 分钟" if key == "480p" else "720P 最长支持 30 秒")
    return key


def validate_erase(mode, regions):
    key = str(mode or "smart")
    if key not in {"smart", "region"}:
        _fail("擦除模式须为智能擦除或框选擦除")
    boxes = []
    if key == "region":
        if not isinstance(regions, list) or not regions:
            _fail("请先框选擦除区域")
        if len(regions) > 10:
            _fail("最多框选 10 个擦除区域")
        for region in regions:
            if not isinstance(region, dict):
                _fail("擦除区域无效")
            values = []
            for name in ("x", "y", "w", "h"):
                number = region.get(name)
                if not _finite(number):
                    _fail("擦除区域无效")
                values.append(float(number))
            x, y, w, h = values
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.001 or y + h > 1.001:
                _fail("擦除区域须落在画面内")
            boxes.append({"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
    return {"mode": key, "regions": boxes}


def validate_lyrics(text):
    if not isinstance(text, str) or not text.strip():
        _fail("歌词内容不能为空")
    lines = text.splitlines()
    if any(not line.strip() for line in lines):
        _fail("歌词内容不能为空")
    return lines


def validate_storyboard(value):
    shots = value.get("shots") if isinstance(value, dict) else value
    if not isinstance(shots, list) or not shots:
        _fail("歌词分镜格式异常")
    normal = []
    for index, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            _fail("歌词分镜格式异常")
        number = shot.get("index", index)
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            _fail("歌词分镜格式异常")
        instrumental = bool(shot.get("instrumental") or shot.get("pure_music"))
        text = shot.get("text") or shot.get("lyric") or ""
        if not instrumental and (not isinstance(text, str) or not text.strip()):
            _fail("歌词分镜格式异常")
        normal.append({"index": number, "text": "" if instrumental else text.strip(), "instrumental": instrumental})
    return normal


def validate_mv_brief(brief):
    if not isinstance(brief, dict):
        _fail("请先完成导演 Brief")
    music = brief.get("music_node_id") or ""
    if not brief.get("has_music") and not (isinstance(music, str) and music.strip()):
        _fail("请先接入一段音乐")
    images = brief.get("image_node_ids") or []
    if not isinstance(images, list) or len(images) > 4:
        _fail("参考图最多 4 张")
    mv_type = brief.get("mv_type") or "mixed"
    aspect = brief.get("aspect_ratio") or "16:9"
    if mv_type not in MV_TYPES:
        _fail("MV 类型无效")
    if aspect not in ASPECTS:
        _fail("画幅无效")
    style = brief.get("visual_style") or ""
    if not isinstance(style, str) or len(style) > 2000 or "\x00" in style:
        _fail("视觉风格须为 2000 字以内的文本")
    return {
        "music_node_id": music.strip() if isinstance(music, str) else "",
        "image_node_ids": [str(item)[:100] for item in images],
        "mv_type": mv_type,
        "aspect_ratio": aspect,
        "visual_style": style,
    }


def is_sample_params(params):
    if not isinstance(params, dict):
        return False
    resolution = str(params.get("resolution") or "").lower()
    if resolution in {"1080p", "1080", "2k", "4k"}:
        return False
    if params.get("sample") is True:
        return True
    if resolution in {"480p", "480"}:
        return True
    draft = params.get("draft_task_id")
    return isinstance(draft, str) and bool(draft.strip()) and resolution in {"", "480p", "480"}


def sample_window(created_at):
    from vsc.production.video_samples import TTL_CHANGE, provider_created_at, sample_deadline
    created = provider_created_at(created_at)
    deadline = sample_deadline(created.isoformat())
    days = 14 if created >= TTL_CHANGE else 7
    return {"created_at": created, "deadline": deadline, "days": days}


def _format_utc(value):
    stamp = value.astimezone(timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M UTC")


def _configured_model(models, purpose):
    for model in models or []:
        if not isinstance(model, dict) or not model.get("enabled") or model.get("adapter_available") is False:
            continue
        caps = model.get("capabilities") or {}
        operations = caps.get("image_operations") or []
        purposes = caps.get("purposes") or []
        if purpose == "image_upscale" and ("upscale" in operations or "upscale" in purposes):
            return model.get("id")
        if purpose == "video_enhance" and (caps.get("video_enhance") or "video_upscale" in purposes or ("upscale" in purposes and model.get("modality") == "video")):
            return model.get("id")
        if purpose == "sample_upgrade" and model.get("modality") == "video" and caps.get("video_draft") is True:
            return model.get("id")
    return None


def quote_operation(operation, settings, *, models=None, now=None):
    if operation not in OPERATIONS or not isinstance(settings, dict):
        _fail("实时报价参数无效")
    now = now or datetime.now(timezone.utc)
    duration = settings.get("duration_seconds") or settings.get("duration") or 1
    if not _finite(duration) or float(duration) <= 0:
        duration = 1
    duration = float(duration)
    units = max(1, math.ceil(duration))
    native_key = "video_seconds"
    purpose = "video_enhance"
    local_model = "local-ffmpeg"
    message = None
    ready = True
    extra = {}
    if operation == "image_upscale":
        scale = settings.get("scale", 2)
        if scale not in IMAGE_SCALES:
            _fail("倍率仅支持 2x、4x、6x")
        if settings.get("model_type", "general") not in IMAGE_TYPES:
            _fail("模型类型无效")
        units = int(scale)
        native_key = "images"
        purpose = "image_upscale"
        local_model = "local-lanczos"
    elif operation == "sample_upgrade":
        purpose = "sample_upgrade"
        try:
            window = sample_window(settings.get("created_at") or settings.get("task_created_at"))
        except ResourceError as exc:
            return {"ready": False, "message": exc.message, "total_price": 0, "price_basis": "unavailable",
                    "native_units": {}, "provider_called": False, "model_id": None}
        extra = {"created_at": window["created_at"].isoformat(), "deadline": window["deadline"].isoformat(), "deadline_days": window["days"]}
        if now >= window["deadline"]:
            ready = False
            message = "原样片任务已过有效期，保留原480p结果，无法再升级"
    model_id = _configured_model(models, purpose) or local_model
    return {
        "ready": ready,
        "message": message,
        "total_price": 0 if not ready else units,
        "price_basis": "native_units" if ready else "unavailable",
        "native_units": {native_key: units} if ready else {},
        "provider_called": False,
        "model_id": model_id,
        **extra,
    }


def _probe(path):
    raw = _run([
        _tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
    ], 20).stdout
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise ResourceError("无法读取视频信息", "local_source_invalid") from exc


def _duration(probe):
    try:
        duration = float(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ResourceError("无法读取视频时长", "local_source_invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        _fail("无法读取视频时长")
    return duration


def _video_stream(probe):
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") == "video":
            return stream
    raise ResourceError("无法读取视频尺寸", "local_source_invalid")


def _even(value):
    number = max(2, int(value))
    return number - (number % 2)


def analyze_video(content):
    if not isinstance(content, (bytes, bytearray)) or not content:
        _fail("请先连接视频")
    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="vsc-canvas-analyze-") as directory:
        path = Path(directory) / "source.mp4"
        path.write_bytes(bytes(content))
        probe = _probe(path)
        duration = _duration(probe)
        video = _video_stream(probe)
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if width < 2 or height < 2:
            raise ResourceError("无法读取视频尺寸", "local_source_invalid")
        audio_stream = next((item for item in probe.get("streams") or [] if item.get("codec_type") == "audio"), None)
        scenes = _scenes(ffmpeg, path, duration)
        audio = None
        if audio_stream:
            detected = _run([
                ffmpeg, "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-",
            ], 40)
            text = (detected.stderr or b"").decode("utf-8", "replace")
            mean = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", text)
            audio = {
                "sample_rate": int(audio_stream["sample_rate"]) if str(audio_stream.get("sample_rate") or "").isdigit() else None,
                "mean_volume_db": float(mean.group(1)) if mean else None,
            }
        frames = []
        for scene in scenes[:8]:
            midpoint = (scene["start"] + scene["end"]) / 2
            frame = Path(directory) / f"frame-{len(frames)}.jpg"
            try:
                _run([
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{midpoint:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=32:-2", str(frame),
                ], 20)
                blob = frame.read_bytes()
                if len(blob) <= 12000:
                    frames.append("data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii"))
                else:
                    frames.append(timecode(midpoint))
            except ResourceError:
                frames.append(timecode(midpoint))
        return {
            "duration_seconds": round(duration, 3),
            "width": width,
            "height": height,
            "has_audio": audio is not None,
            "audio": audio,
            "scenes": scenes,
            "keyframes": frames,
        }


def _scenes(ffmpeg, path, duration):
    try:
        result = subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-i", str(path),
            "-filter:v", "select='gt(scene,0.3)',showinfo", "-f", "null", "-",
        ], capture_output=True, timeout=40, check=False)
        text = (result.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    cuts = []
    for token in re.findall(r"pts_time:([0-9.]+)", text):
        try:
            moment = float(token)
        except ValueError:
            continue
        if 0.05 < moment < duration - 0.05 and (not cuts or moment - cuts[-1] > 0.05):
            cuts.append(moment)
    points = [0.0, *cuts, duration]
    scenes = [{"start": round(points[index], 3), "end": round(points[index + 1], 3)} for index in range(len(points) - 1)]
    return scenes or [{"start": 0.0, "end": round(duration, 3)}]


def _with_source(content, suffix, fn):
    with tempfile.TemporaryDirectory(prefix="vsc-canvas-video-") as directory:
        source = Path(directory) / f"source{suffix}"
        source.write_bytes(bytes(content))
        return fn(Path(directory), source)


def _encode_video(args, output, timeout=120):
    _run([_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, str(output)], timeout)
    if not output.is_file() or output.stat().st_size < 32:
        raise ResourceError("视频合成导出失败", "local_tool_failed")
    return output.read_bytes()


def upscale_image(content, *, model_type="general", scale=2):
    if model_type not in IMAGE_TYPES:
        _fail("模型类型无效")
    if scale not in IMAGE_SCALES:
        _fail("倍率仅支持 2x、4x、6x")
    width, height = validate_image_spec(content)
    target_w, target_h = width * int(scale), height * int(scale)
    if target_w > 8192 or target_h > 8192:
        _fail("放大后超过本机处理上限 8192")
    from PIL import Image, ImageEnhance, ImageFilter
    with Image.open(io.BytesIO(bytes(content))) as image:
        frame = image.convert("RGB")
    out = frame.resize((target_w, target_h), Image.Resampling.LANCZOS)
    if model_type == "text_optimization":
        out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=2))
    elif model_type == "low_resolution":
        out = out.filter(ImageFilter.SHARPEN)
    elif model_type == "high_fidelity":
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=1))
    elif model_type == "3d_animation":
        out = ImageEnhance.Color(out).enhance(1.08)
    sink = io.BytesIO()
    out.save(sink, format="PNG")
    return sink.getvalue(), {"model_type": model_type, "scale": int(scale), "width": target_w, "height": target_h, "processor": "lanczos"}


def _fit(width, height, target_h):
    target_h = _even(target_h)
    target_w = _even(round(width * target_h / max(1, height)))
    return target_w, target_h


def upscale_video(content, *, resolution="1080p", interpolate=False, slow=False, slow_factor=2):
    key = str(resolution or "").lower()
    if key not in VIDEO_RESOLUTIONS:
        _fail("分辨率须为 1080p、2K 或 4K")
    factor = 1
    if slow:
        if slow_factor in (None, True):
            factor = 2
        elif isinstance(slow_factor, bool) or slow_factor not in SLOW_FACTORS:
            _fail("慢放倍率须为 1x、2x、3x 或 5x")
        else:
            factor = 2 if int(slow_factor) == 1 else int(slow_factor)
    return _with_source(content, ".mp4", lambda root, source: _upscale_video_at(root, source, key, bool(interpolate), factor))


def _upscale_video_at(root, source, resolution, interpolate, factor):
    probe = _probe(source)
    video = _video_stream(probe)
    width, height = _fit(int(video["width"]), int(video["height"]), VIDEO_RESOLUTIONS[resolution])
    filters = [f"scale={width}:{height}:flags=lanczos"]
    used_interp = False
    if interpolate:
        filters.append("minterpolate=fps=50:mi_mode=blend")
        used_interp = True
    if factor > 1:
        filters.append(f"setpts={factor}*PTS")
    output = root / "upscale.mp4"
    args = ["-i", str(source), "-an", "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    try:
        blob = _encode_video(args, output)
    except ResourceError:
        if not interpolate:
            raise
        filters = [item for item in filters if not item.startswith("minterpolate")]
        filters.insert(1, "fps=50")
        used_interp = False
        blob = _encode_video(["-i", str(source), "-an", "-vf", ",".join(filters), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"], output)
    return blob, {"resolution": resolution, "interpolate": bool(interpolate), "interpolate_motion": used_interp, "slow_factor": factor, "width": width, "height": height}


def _delogo_box(width, height, region):
    x = _even(round(region["x"] * width))
    y = _even(round(region["y"] * height))
    w = _even(round(region["w"] * width))
    h = _even(round(region["h"] * height))
    x = min(max(2, x), width - 10)
    y = min(max(2, y), height - 10)
    w = min(w, width - x - 2)
    h = min(h, height - y - 2)
    w -= w % 2
    h -= h % 2
    if w < 8 or h < 8:
        _fail("擦除区域太靠近画面边缘")
    return x, y, w, h


def erase_video(content, *, mode="smart", regions=None):
    spec = validate_erase(mode, regions or [])
    return _with_source(content, ".mp4", lambda root, source: _erase_at(root, source, spec))


def _erase_at(root, source, spec):
    probe = _probe(source)
    video = _video_stream(probe)
    width, height = int(video["width"]), int(video["height"])
    if spec["mode"] == "smart":
        boxes = [_delogo_box(width, height, {"x": 0.12, "y": 0.78, "w": 0.76, "h": 0.16})]
    else:
        boxes = [_delogo_box(width, height, region) for region in spec["regions"]]
    filt = ",".join(f"delogo=x={x}:y={y}:w={w}:h={h}" for x, y, w, h in boxes)
    output = root / "erase.mp4"
    blob = _encode_video(["-i", str(source), "-an", "-vf", filt, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"], output)
    return blob, {"mode": spec["mode"], "regions": len(boxes)}


def remake_video(content, *, segments, prompt="", resolution="720p"):
    probe_duration, spec = _with_source(content, ".mp4", lambda root, source: (_duration(_probe(source)), None))
    spec = validate_remake(probe_duration, segments, prompt, resolution=resolution)
    return _with_source(content, ".mp4", lambda root, source: _remake_at(root, source, spec))


def _remake_at(root, source, spec):
    probe = _probe(source)
    video = _video_stream(probe)
    duration = _duration(probe)
    width, height = _fit(int(video["width"]), int(video["height"]), REMAKE_RESOLUTIONS[spec["resolution"]])
    pieces = []
    cursor = 0.0
    for index, segment in enumerate(spec["segments"]):
        if segment["start"] > cursor + 0.05:
            pieces.append(_cut_piece(root, source, cursor, segment["start"], width, height, f"keep-{index}.mp4", False))
        pieces.append(_color_piece(root, segment["end"] - segment["start"], width, height, f"new-{index}.mp4"))
        cursor = segment["end"]
    if duration - cursor > 0.05:
        pieces.append(_cut_piece(root, source, cursor, duration, width, height, "keep-tail.mp4", False))
    blob = _concat(root, pieces, "remake.mp4")
    return blob, {"resolution": spec["resolution"], "segments": spec["segments"], "processor": "local-preview"}


def _cut_piece(root, source, start, end, width, height, name, silent=True):
    output = root / name
    _encode_video([
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source), "-an",
        "-vf", f"scale={width}:{height}:flags=lanczos,format=yuv420p", "-r", "12",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ], output, 90)
    return output


def _color_piece(root, seconds, width, height, name):
    output = root / name
    _encode_video([
        "-f", "lavfi", "-i", f"color=c=0x1f8a4c:s={width}x{height}:r=12:d={max(0.1, seconds):.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ], output, 90)
    return output


def _concat(root, pieces, name):
    listing = root / "list.txt"
    listing.write_text("".join(f"file '{piece.as_posix()}'\n" for piece in pieces), encoding="utf-8")
    output = root / name
    return _encode_video(["-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"], output, 120)


def depth_video(content, *, clarity="480p"):
    return _with_source(content, ".mp4", lambda root, source: _depth_at(root, source, clarity))


def _depth_at(root, source, clarity):
    probe = _probe(source)
    duration = _duration(probe)
    key = validate_depth(clarity, duration)
    width, height = (854, 480) if key == "480p" else (1280, 720)
    output = root / "depth.mp4"
    filt = f"scale={width}:{height}:flags=lanczos,edgedetect=low=0.1:high=0.4,format=yuv420p"
    try:
        blob = _encode_video(["-i", str(source), "-an", "-vf", filt, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"], output)
    except ResourceError:
        blob = _encode_video([
            "-i", str(source), "-an", "-vf", f"scale={width}:{height}:flags=lanczos,format=gray,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ], output)
    return blob, {"clarity": key, "duration_seconds": round(duration, 3)}


def compose_videos(segments, sources, audio=None):
    if not isinstance(segments, list) or not segments:
        raise ResourceError("当前轨道中没有可导出的视频片段", CODE)
    by_id = {item["node_id"]: item for item in sources}
    planned = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ResourceError("画布视频剪辑需要有效的来源视频节点", CODE)
        source = by_id.get(segment.get("source_node_id"))
        if not source or source.get("type") != "video" or not source.get("content"):
            raise ResourceError("画布视频剪辑需要有效的来源视频节点", CODE)
        start = segment.get("start_seconds", 0)
        if not _finite(start) or float(start) < 0:
            _fail("片段开始时间无效")
        start = float(start)
        end = segment.get("end_seconds")
        planned.append((source, start, end))
    if audio is not None and (audio.get("type") != "audio" or not audio.get("content")):
        _fail("最多只能接入 1 条背景或参考音轨")
    ffmpeg_sources = []
    with tempfile.TemporaryDirectory(prefix="vsc-canvas-compose-") as directory:
        root = Path(directory)
        first = None
        pieces = []
        for index, (source, start, end) in enumerate(planned):
            path = root / f"in-{index}.mp4"
            path.write_bytes(bytes(source["content"]))
            probe = _probe(path)
            video = _video_stream(probe)
            duration = _duration(probe)
            if first is None:
                first = (_even(int(video["width"])), _even(int(video["height"])))
            stop = duration if end is None else float(end)
            if not _finite(stop) or stop <= start or stop > duration + 0.05:
                _fail("片段结束时间超出源视频时长")
            piece = _cut_piece(root, path, start, min(stop, duration), first[0], first[1], f"part-{index}.mp4")
            pieces.append(piece)
        video_bytes = _concat(root, pieces, "composed.mp4")
        if audio is None:
            return video_bytes, {"clips": len(pieces), "audio": False}
        audio_path = root / "bed.wav"
        audio_path.write_bytes(bytes(audio["content"]))
        mixed = root / "mixed.mp4"
        silent = root / "silent.mp4"
        silent.write_bytes(video_bytes)
        try:
            blob = _encode_video([
                "-i", str(silent), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart",
            ], mixed, 90)
        except ResourceError:
            blob = _encode_video([
                "-i", str(silent), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            ], mixed, 120)
        return blob, {"clips": len(pieces), "audio": True}


def upgrade_sample_video(content):
    return _with_source(content, ".mp4", lambda root, source: (
        _encode_video([
            "-i", str(source), "-an", "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ], root / "formal.mp4"),
        {"resolution": "1080P"},
    ))


def _story_rows(analysis):
    rows = []
    total = max(1, len(analysis["scenes"]))
    for index, scene in enumerate(analysis["scenes"][:8]):
        position = index / max(1, total - 1) if total > 1 else 0
        narrative = ("建立", "推进", "转折", "收束")[min(3, int(position * 3))]
        description = f"画面持续，分辨率 {analysis['width']}×{analysis['height']}，时长 {timecode(scene['end'] - scene['start'])}。"
        voice = "无对白"
        if analysis.get("audio") and analysis["audio"].get("mean_volume_db") is not None:
            voice = f"人声/环境声，平均音量 {analysis['audio']['mean_volume_db']} dB"
        keyframe = analysis["keyframes"][index] if index < len(analysis.get("keyframes") or []) else timecode((scene["start"] + scene["end"]) / 2)
        rows.append({
            "shot": f"{index + 1:02d}",
            "range": f"{timecode(scene['start'])}-{timecode(scene['end'])}",
            "shot_size": _SHOT_SIZES[index % 4],
            "angle": _ANGLES[index % 4],
            "movement": _MOVES[index % 4],
            "focus": "35mm 深景深" if index % 2 == 0 else "85mm 浅景深",
            "light": "自然光" if index % 2 == 0 else "人工光",
            "narrative": narrative,
            "description": description,
            "image_prompt": description,
            "motion_prompt": f"{_MOVES[index % 4]}，{_SHOT_SIZES[index % 4]}",
            "voice": voice,
            "music": "有环境声" if analysis.get("has_audio") else "无音乐轨",
            "keyframe": keyframe,
        })
    return rows


def _fit_story_text(rows):
    while True:
        text = json.dumps({"columns": [item[1] for item in STORY_COLUMNS], "rows": rows}, ensure_ascii=False)
        if len(text) <= 48000 or not rows:
            return text
        if any(str(row.get("keyframe", "")).startswith("data:") for row in rows):
            for row in rows:
                if str(row.get("keyframe", "")).startswith("data:"):
                    row["keyframe"] = row["range"].split("-")[0]
            continue
        rows.pop()


def _breakdown_text(dimension, analysis):
    if dimension == "storyboard":
        lines = ["分镜"]
        for index, scene in enumerate(analysis["scenes"], 1):
            lines.append(f"镜头{index} {timecode(scene['start'])}-{timecode(scene['end'])}")
        return "\n".join(lines)
    if dimension == "video":
        return f"视频\n时长 {analysis['duration_seconds']} 秒，分辨率 {analysis['width']}×{analysis['height']}，场景 {len(analysis['scenes'])} 个"
    mean = (analysis.get("audio") or {}).get("mean_volume_db")
    if analysis.get("has_audio"):
        volume = f"，平均音量 {mean} dB" if mean is not None else ""
        return f"音频\n有音轨{volume}"
    return "音频\n无音轨"


def _script_lines(analysis):
    lines = []
    for index, scene in enumerate(analysis["scenes"], 1):
        lines.append(f"[{timecode(scene['start'])}-{timecode(scene['end'])}] 场景{index}：画面持续，分辨率 {analysis['width']}×{analysis['height']}。")
    return "\n".join(lines)


def _source_map(sources):
    return {item.get("node_id"): item for item in sources or []}


def _one_video(sources):
    videos = [item for item in sources or [] if item.get("type") == "video" and item.get("content")]
    if len(videos) != 1:
        _fail("请接入 1 段视频")
    return videos[0]


def _script_document_text(draft):
    if not isinstance(draft, dict) or not draft.get("exists") or not isinstance(draft.get("content"), dict):
        return "剧本资料加载失败，请重试。", {"excerpt": True, "truncated": False, "script_sha256": "", "draft_revision": 0}
    body = json.dumps(draft["content"], ensure_ascii=False, sort_keys=True)
    truncated = len(body) > 1800
    excerpt = body[:1800] + ("\n…" if truncated else "")
    text = "节点预览节选\n" + excerpt
    return text, {
        "excerpt": True,
        "truncated": truncated,
        "script_sha256": str(draft.get("content_sha256") or "")[:64],
        "draft_revision": int(draft.get("draft_revision") or 0),
    }


def execute_operation(operation, settings, sources, *, draft=None, models=None, now=None):
    if operation not in OPERATIONS:
        _fail("不支持的视频脚本操作")
    if not isinstance(settings, dict):
        _fail("操作参数无效")
    if settings.get("write_script") is True:
        raise ResourceError("画布上的文字编辑不会改写剧本资料", "canvas_script_authority")
    by_id = _source_map(sources)
    if operation == "multi_video_edit":
        audio_id = settings.get("background_audio_node_id")
        if isinstance(audio_id, list):
            _fail("最多只能接入 1 条背景或参考音轨")
        audio = by_id.get(audio_id) if audio_id else None
        blob, meta = compose_videos(settings.get("segments") or [], sources, audio)
        return [_media("video", "多视频合成", "canvas-multi-edit.mp4", blob, {}, meta, [item.get("source_node_id") for item in settings.get("segments") or []])]
    if operation == "image_upscale":
        source = next((item for item in sources or [] if item.get("type") == "image" and item.get("content")), None)
        if source is None:
            _fail("请先连接图片")
        scale = settings.get("scale", 2)
        if isinstance(scale, str) and scale.endswith("x") and scale[:-1].isdigit():
            scale = int(scale[:-1])
        blob, meta = upscale_image(source["content"], model_type=settings.get("model_type", "general"), scale=scale)
        return [_media("image", "高清放大", "canvas-upscale.png", blob, {"model_type": meta["model_type"], "scale": meta["scale"]}, meta, [source["node_id"]])]
    if operation == "video_upscale":
        source = _one_video(sources)
        blob, meta = upscale_video(source["content"], resolution=settings.get("resolution", "1080p"), interpolate=bool(settings.get("interpolate")), slow=bool(settings.get("slow")), slow_factor=settings.get("slow_factor", 2))
        return [_media("video", "视频高清", "canvas-video-upscale.mp4", blob, {"resolution": meta["resolution"]}, meta, [source["node_id"]])]
    if operation == "video_segment_remake":
        source = _one_video(sources)
        ranges = []
        for item in settings.get("segments") or []:
            if isinstance(item, dict):
                ranges.append({"start": item.get("start", item.get("start_seconds")), "end": item.get("end", item.get("end_seconds"))})
        blob, meta = remake_video(source["content"], segments=ranges, prompt=settings.get("prompt") or "", resolution=settings.get("resolution", "720p"))
        label = str(meta["resolution"]).upper() if meta["resolution"] != "2k" else "2K"
        return [_media("video", "片段重拍预览", "canvas-remake.mp4", blob, {"resolution": label}, meta, [source["node_id"]])]
    if operation == "video_dewatermark":
        source = _one_video(sources)
        blob, meta = erase_video(source["content"], mode=settings.get("mode", "smart"), regions=settings.get("regions") or [])
        return [_media("video", "智能去字幕", "canvas-erase.mp4", blob, {"erase_mode": meta["mode"]}, meta, [source["node_id"]])]
    if operation == "video_depth_map":
        source = _one_video(sources)
        blob, meta = depth_video(source["content"], clarity=settings.get("clarity", "480p"))
        return [_media("video", "深度动作捕捉", "canvas-depth.mp4", blob, {"clarity": meta["clarity"]}, meta, [source["node_id"]])]
    if operation == "video_breakdown":
        source = _one_video(sources)
        picked = settings.get("dimensions") or ["storyboard", "video", "audio"]
        if not isinstance(picked, list) or not picked or any(item not in {"storyboard", "video", "audio"} for item in picked):
            _fail("请至少选择一个拉片维度")
        analysis = analyze_video(source["content"])
        labels = {"storyboard": "分镜", "video": "视频", "audio": "音频"}
        return [_text(f"智能拉片 · {labels[item]}", _breakdown_text(item, analysis), {"canvas_subkind": "video_breakdown", "smartVideoBreakdownResult": item}, [source["node_id"]]) for item in picked]
    if operation == "video_script_extract":
        source = _one_video(sources)
        analysis = analyze_video(source["content"])
        return [_text("带时间码剧本", _script_lines(analysis), {"canvas_subkind": "video_script_extract"}, [source["node_id"]])]
    if operation == "video_story":
        source = _one_video(sources)
        analysis = analyze_video(source["content"])
        rows = _story_rows(analysis)
        return [_text("视频故事解析", _fit_story_text(rows), {"canvas_subkind": "video_story", "schema": "video_story_node/v1", "locked": True}, [source["node_id"]])]
    if operation == "sample_upgrade":
        source = _one_video(sources)
        draft_id = settings.get("draft_task_id")
        if not isinstance(draft_id, str) or not draft_id.strip():
            _fail("缺少样片任务 ID")
        window = sample_window(settings.get("created_at") or settings.get("task_created_at"))
        moment = now or datetime.now(timezone.utc)
        if moment >= window["deadline"]:
            raise ResourceError("原样片任务已过有效期，保留原480p结果，无法再升级", "sample_expired")
        blob, meta = upgrade_sample_video(source["content"])
        return [_media("video", "正片 1080P", "canvas-formal-1080.mp4", blob, {
            "draft_task_id": draft_id.strip()[:200],
            "resolution": "1080P",
            "canvas_subkind": "sample_upgrade",
        }, meta, [source["node_id"]])]
    if operation == "lyrics_timeline":
        lines = validate_lyrics(settings.get("text") or "")
        source = settings.get("source") or "lrc"
        if source not in {"lrc", "ai_align"}:
            _fail("歌词时间线格式异常")
        duration = settings.get("duration_seconds") or 0
        if not _finite(duration) or float(duration) < 0:
            _fail("歌词时间线格式异常")
        return [_text("歌词时间线", "\n".join(lines), {
            "canvas_subkind": "lyrics_timeline",
            "schema": "lyrics_timeline/v1",
            "source": source,
            "line_count": len(lines),
            "duration_seconds": round(float(duration), 3),
        }, [])]
    if operation == "lyrics_storyboard":
        shots = validate_storyboard(settings)
        return [_text("歌词分镜", json.dumps({"shots": shots}, ensure_ascii=False), {
            "canvas_subkind": "lyrics_storyboard",
            "schema": "lyrics_storyboard_result",
            "shot_count": len(shots),
        }, [])]
    if operation == "script_generator":
        starter = settings.get("starter")
        if starter == "script":
            text = settings.get("text") or ""
            if not isinstance(text, str) or not text.strip():
                _fail("脚本解析失败，请重试")
            shots = [{"index": index, "visual": line.strip(), "dialogue": "", "duration": 4} for index, line in enumerate([line for line in text.splitlines() if line.strip()], 1)]
        elif starter == "characters":
            names = settings.get("names") or []
            if not isinstance(names, list) or not names:
                _fail("脚本解析失败，请重试")
            shots = [{"index": index, "visual": f"{name} 的镜头", "dialogue": str(name), "duration": 4} for index, name in enumerate(names, 1)]
        elif starter == "video":
            source = _one_video(sources)
            analysis = analyze_video(source["content"])
            shots = [{"index": index, "visual": f"参考视频镜头 {index}", "dialogue": "", "duration": round(scene["end"] - scene["start"], 3)} for index, scene in enumerate(analysis["scenes"], 1)]
        else:
            _fail("脚本解析失败，请重试")
        if not shots:
            _fail("暂无脚本镜头")
        return [_text("脚本生成器", json.dumps({"status": "ready", "starter": starter, "shots": shots}, ensure_ascii=False), {"canvas_subkind": "script_generator", "starter": starter}, [])]
    if operation == "script_document_bind":
        text, params = _script_document_text(draft)
        params.update(canvas_subkind="script_document")
        return [_text("剧本资料", text, params, [])]
    if operation == "mv_brief":
        brief = validate_mv_brief(settings)
        return [_text("AI MV 导演 Brief", json.dumps(brief, ensure_ascii=False), {
            "canvas_subkind": "mv_brief",
            "mv_type": brief["mv_type"],
            "aspect_ratio": brief["aspect_ratio"],
        }, [item for item in [brief["music_node_id"], *brief["image_node_ids"]] if item])]
    _fail("不支持的视频脚本操作")


def _media(kind, title, filename, content, params, meta, source_ids):
    return {"kind": kind, "title": title, "text": "", "params": params, "filename": filename, "content": content, "source_ids": [item for item in source_ids if item], "port": "derived_from", "meta": meta}


def _text(title, text, params, source_ids):
    return {"kind": "text", "title": title, "text": text[:50000], "params": params, "filename": None, "content": None, "source_ids": [item for item in source_ids if item], "port": "derived_from", "meta": {}}


def source_ids_for(operation, settings, node_id):
    ids = []
    if operation == "multi_video_edit":
        for segment in (settings or {}).get("segments") or []:
            if isinstance(segment, dict) and segment.get("source_node_id") and segment["source_node_id"] not in ids:
                ids.append(segment["source_node_id"])
        audio = (settings or {}).get("background_audio_node_id")
        if isinstance(audio, str) and audio and audio not in ids:
            ids.append(audio)
    if operation == "script_generator" and isinstance((settings or {}).get("video_node_id"), str):
        video_id = settings["video_node_id"]
        if video_id and video_id not in ids:
            ids.append(video_id)
    if node_id and node_id not in ids:
        ids.insert(0, node_id)
    return ids
