"""Bounded creative tool contracts; no provider call or separate media authority."""
from copy import deepcopy
import re


DRAFT_TYPE = "creative-tool-draft"
FORMAT = "vsc.creative-tool-draft/v1"
TOOLS = {
    "music_description": ("描述生成音乐候选", "audio", "music", ""),
    "ambience": ("环境声候选", "audio", "ambience", ""),
    "music_lyrics": ("歌词生成歌曲", "audio", "song", "尚未接入歌词到演唱歌曲适配器"),
    "instrumental": ("生成纯音乐", "audio", "music", "尚未接入纯音乐生成适配器"),
    "lyrics": ("歌词创作", "text", "lyrics", "文本歌词建议；不生成演唱音频"),
    "speech": ("台词配音", "audio", "dialogue_dry", ""),
    "voice": ("人物音色", "audio", "voice", "音色规格与授权沿人物资产入口；本工具不克隆声音"),
    "sfx": ("普通音效候选", "audio", "sfx", ""),
    "music_mix": ("视频配乐", "local", "music", ""),
    "mv": ("MV 镜头计划", "local", "mv", ""),
    "video_edit": ("视频编辑", "video", "video_edit", ""),
    "video_extend": ("视频续接", "video", "video_extend", ""),
    "segment_remake": ("已有片段区间替换", "local", "segment_remake", "使用已登记替换片实际拼接；不从提示词生成新画面"),
    "depth_motion": ("深度动作捕捉", "video", "depth_motion", "尚未接入源视频→深度中间视频→人物视频依赖链"),
    "native_long_video": ("原生长视频", "video", "native_long_video", "尚未接入原生长视频模型；短片拼接不视为原生长视频"),
    "upscale": ("视频超分", "video", "upscale", "尚未接入超分适配器"),
    "remove_subtitles": ("字幕区域擦除", "local", "remove_subtitles", "矩形边界插值；不自动识别字幕，不还原被遮挡原画"),
    "remove_watermark": ("水印区域处理", "local", "remove_watermark", "矩形边界插值；源片处理权限沿原素材权利核验"),
    "extract_frame": ("首尾/当前帧提取", "local", "extract_frame", "提取实际视频帧并登记原素材；不进行图像生成"),
    "separate_audio": ("音视频轨道分离", "local", "separate_audio", "完整视频轨和第一音轨分别回库；不做人声/伴奏分离"),
    "breakdown": ("分镜/视频/音频拉片", "text", "breakdown", "尚未接入三个维度的理解结果与画布节点落地用例"),
}


def _fail(message):
    raise ValueError(message)


def normalize_draft(value):
    from vsc.production.resource_settings import safe_parameters
    fields = {"tool", "episode_id", "shot_id", "title", "prompt", "lyrics", "lrc", "style", "model_id",
              "params", "source_media_id", "audio_media_id", "visual_media_ids", "ranges", "segments",
              "keep_original", "music_start_ms", "music_end_ms", "audio_in_ms", "duration_ms", "dimensions",
              "script_line_ids", "voice_media_id", "replacement_media_id"}
    if not isinstance(value, dict) or set(value) - fields or value.get("tool") not in TOOLS:
        _fail("工具草稿需要已知类型与支持的字段")
    result = deepcopy(value)
    for key, limit in (("episode_id", 100), ("shot_id", 100), ("title", 200), ("prompt", 20000),
                       ("lyrics", 50000), ("lrc", 50000), ("style", 4000), ("model_id", 100),
                       ("source_media_id", 100), ("audio_media_id", 100), ("voice_media_id", 100), ("replacement_media_id",100)):
        result.setdefault(key, "")
        if not isinstance(result[key], str) or len(result[key]) > limit:
            _fail("字段格式或长度不正确：" + key)
    if not result["episode_id"]:
        _fail("请先选择当前集")
    result.setdefault("keep_original", False)
    if type(result["keep_original"]) is not bool:
        _fail("保留原音须为开关")
    for key, default in (("music_start_ms", 0), ("music_end_ms", 0), ("audio_in_ms", 0), ("duration_ms", 5000)):
        result.setdefault(key, default)
        if type(result[key]) is not int or not 0 <= result[key] <= 3600000:
            _fail("时码须为一小时内的非负毫秒数")
    params = result.setdefault("params", {})
    if not isinstance(params, dict) or len(str(params)) > 20000:
        _fail("参数须为有界的对象")
    result["params"] = safe_parameters(params)
    refs = result.setdefault("visual_media_ids", [])
    if not isinstance(refs, list) or len(refs) > 50 or any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != len(refs):
        _fail("视觉参考须为最多 50 个不同素材")
    lines = result.setdefault("script_line_ids", [])
    if not isinstance(lines, list) or len(lines) > 100 or any(not isinstance(line, str) or not line for line in lines):
        _fail("配音须引用明确台词编号")
    dimensions = result.setdefault("dimensions", [])
    if not isinstance(dimensions, list) or any(item not in {"storyboard", "video", "audio"} for item in dimensions) or len(set(dimensions)) != len(dimensions):
        _fail("拉片维度只能为分镜、视频、音频")
    ranges = result.setdefault("ranges", [])
    if not isinstance(ranges, list) or len(ranges) > 50:
        _fail("区间最多 50 段")
    previous = 0
    for row in ranges:
        if not isinstance(row, dict) or set(row) != {"start_ms", "end_ms"}:
            _fail("区间需要起止毫秒")
        a, b = row["start_ms"], row["end_ms"]
        if type(a) is not int or type(b) is not int or not previous <= a < b <= 3600000:
            _fail("区间须有序、不重叠且结束晚于开始")
        previous = b
    segments = result.setdefault("segments", [])
    if not isinstance(segments, list) or len(segments) > 200:
        _fail("MV 最多 200 段")
    for row in segments:
        if not isinstance(row, dict) or set(row) - {"start_ms", "end_ms", "title", "lyrics", "prompt"}:
            _fail("MV 段落字段不正确")
        for key in ("title", "lyrics", "prompt"):
            if not isinstance(row.get(key, ""), str) or len(row.get(key, "")) > 4000:
                _fail("MV 段落文本超长")
    return result


def parse_lrc(text, duration_ms):
    """LRC is supplied timing, never inferred speech alignment."""
    points = []
    for line in text.splitlines():
        tags = list(re.finditer(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]", line))
        if not tags:
            if line.strip() and not re.fullmatch(r"\[(?:ar|ti|al|by|offset):[^\]]*\]", line.strip()):
                _fail("LRC 每行需要 [分:秒.毫秒]，或明确提供段落时码")
            if line.strip().startswith("[offset:") and line.strip() != "[offset:0]":
                _fail("请先把 LRC offset 换算到每行时码")
            continue
        lyric = line[tags[-1].end():].strip()
        for tag in tags:
            if int(tag[2]) >= 60:
                _fail("LRC 秒数须小于 60")
            at = (int(tag[1]) * 60 + int(tag[2])) * 1000 + int((tag[3] or "0").ljust(3, "0"))
            if at >= duration_ms:
                _fail("LRC 时码超过所选音频")
            points.append((at, lyric))
    points.sort()
    if len(points) > 200 or len({p[0] for p in points}) != len(points):
        _fail("LRC 时码重复或超过 200 行")
    if points and points[0][0] > 0:
        points.insert(0, (0, ""))
    return [{"start_ms": at, "end_ms": points[i + 1][0] if i + 1 < len(points) else duration_ms,
             "title": "段落 %s" % (i + 1), "lyrics": lyric, "prompt": ""}
            for i, (at, lyric) in enumerate(points)]


def compile_mv(document, audio):
    duration = audio.get("duration_ms")
    if type(duration) is not int or not 0 < duration <= 3600000:
        _fail("MV 音频需要已核实且不超过一小时的时长")
    segments = document["segments"] or parse_lrc(document["lrc"], duration)
    if not segments:
        _fail("请提供带时码的段落或 LRC；普通歌词不会自动伪造节拍")
    shots, previous = [], 0
    for index, row in enumerate(segments):
        a, b = row.get("start_ms"), row.get("end_ms")
        if type(a) is not int or type(b) is not int or a != previous or not a < b <= duration:
            _fail("MV 段落须连续覆盖音频，且时码不能越界或重叠")
        prompt = row.get("prompt", "").strip() or document["prompt"].strip()
        shots.append(dict(key="mv-%03d" % (index + 1), start_ms=a, end_ms=b, duration_ms=b-a,
            title=row.get("title") or "段落 %s" % (index + 1), lyrics=row.get("lyrics", ""),
            prompt=prompt, style=document["style"], visual_media_ids=deepcopy(document["visual_media_ids"])))
        previous = b
    if previous != duration:
        _fail("MV 段落须覆盖到完整音频结尾")
    return {"format": "vsc.mv-plan/v1", "audio_media_id": audio["id"], "audio_sha256": audio["sha256"],
            "audio_duration_ms": duration, "timing_source": "user_segments" if document["segments"] else "user_lrc",
            "shots": shots, "generated_video": False}


def music_edit(document, source, audio, *, fps=24, width=720, height=1280):
    """Compile an explicit interval into the existing first-cut renderer recipe."""
    from vsc.post.edit_workspace import FORMAT as EDIT_FORMAT, validate_edit
    duration, audio_duration = source.get("duration_ms"), audio.get("duration_ms")
    a, b, start = document["music_start_ms"], document["music_end_ms"], document["audio_in_ms"]
    if (type(duration) is not int or type(audio_duration) is not int or not 0 <= a < b <= duration
            or start + b - a > audio_duration):
        _fail("配乐区间须位于视频中，且所选完整音频长度足够")
    frame = lambda ms: round(ms * fps / 1000)
    result = dict(format=EDIT_FORMAT, width=width, height=height, fps=fps,
        clips=[dict(id="music-source", media_id=source["id"], in_frame=0, out_frame=frame(duration),
                    muted=not document["keep_original"], volume=1)],
        audio=[dict(id="music-track", media_id=audio["id"], purpose="music", in_frame=frame(start),
                    out_frame=frame(start + b - a), at_frame=frame(a), volume=.7 if document["keep_original"] else 1)],
        captions=[])
    validate_edit(result)
    return result
