#!/usr/bin/env python3
"""Grok Imagine 有效请求的共用编译与能力校验（纯函数，无 IO）。

CLI、series 与 PostgreSQL worker 三个人口共用同一实现（B2-01/F09/F10）：
所有本地可判定的错误（时长、分辨率与模式上限、张数、经典模型组合、预置声音）
都在这里抛出，发生在预算预留与提交意图之前；有效请求返回最终 payload。
"""
from __future__ import annotations


class GrokSpecError(ValueError):
    """本地可判定的无效请求；调用方必须在预留预算与写提交意图之前拒绝。"""


REFERENCE_LIMIT = 14
VOICE_LIMIT = 3
KEYFRAME_LIMIT = 4
EDIT_SOURCE_LIMIT = 5
REFERENCE_RESOLUTIONS = ("480p", "720p")
FRAME_RESOLUTIONS = ("480p", "720p", "1080p")
ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20", "21:9", "5:2", "auto")
IMAGE_RESOLUTIONS = ("1k", "2k")


def advanced_model(model: str) -> bool:
    return "1.5" in (model or "")


def compile_image(model, prompt, references, ratio, resolution, count):
    """文生图（无参考）或 /v1/images/edits 编辑（1–5 源图，一候选一张）。"""
    if not str(prompt or "").strip():
        raise GrokSpecError("图像请求需要非空提示词")
    references = list(references or [])
    if len(references) > EDIT_SOURCE_LIMIT:
        raise GrokSpecError(f"Grok 图像编辑一次最多 {EDIT_SOURCE_LIMIT} 张源图")
    if references and count != 1:
        raise GrokSpecError("图像编辑每个逻辑候选固定一张输出；多张仅支持纯文生图，待单独核实后开放")
    if resolution not in IMAGE_RESOLUTIONS:
        raise GrokSpecError("图像分辨率须为 1k 或 2k")
    if references:
        if len(references) == 1:
            return "/images/edits", {"model": model, "prompt": prompt,
                                     "image": {"url": references[0], "type": "image_url"}}
        return "/images/edits", {"model": model, "prompt": prompt,
                                 "images": [{"url": url, "type": "image_url"} for url in references]}
    if ratio not in ASPECT_RATIOS:
        raise GrokSpecError(f"画幅 {ratio} 不在平台支持列表")
    return "/images/generations", {"model": model, "prompt": prompt, "n": count,
                                   "aspect_ratio": ratio, "resolution": resolution, "response_format": "url"}


def compile_video(model, prompt, duration_ms, first, last, references, keyframes, voice_ids,
                  ratio, resolution, generate_audio=True):
    """按官方模式组装 /v1/videos/generations 的最终 payload；先做全部本地校验。

    keyframes 为 (url, 秒) 序列；voice_ids 为平台预置 voice_id（≤3）。
    """
    advanced = advanced_model(model)
    maximum_ms = 15000 if advanced else 10000
    seconds = duration_ms // 1000
    if (not isinstance(duration_ms, int) or isinstance(duration_ms, bool)
            or duration_ms < 1000 or duration_ms % 1000 or duration_ms > maximum_ms):
        raise GrokSpecError(f"视频时长须为 1–{maximum_ms // 1000} 整秒")
    if not str(prompt or "").strip():
        raise GrokSpecError("视频请求需要非空提示词")
    references = list(references or [])
    voice_ids = list(voice_ids or [])
    keyframes = list(keyframes or [])
    if len(references) > REFERENCE_LIMIT:
        raise GrokSpecError(f"Grok 参考模式一次最多 {REFERENCE_LIMIT} 张参考图")
    if len(voice_ids) > VOICE_LIMIT:
        raise GrokSpecError(f"Grok 预置声音参考最多 {VOICE_LIMIT} 个")
    if len(keyframes) > KEYFRAME_LIMIT:
        raise GrokSpecError(f"Grok 中段关键帧最多 {KEYFRAME_LIMIT} 个")
    if ratio and ratio not in ASPECT_RATIOS:
        raise GrokSpecError(f"画幅 {ratio} 不在平台支持列表")
    if not advanced:  # 经典 grok-imagine-video 的官方限制
        blocked = []
        if last:
            blocked.append("尾帧钉定")
        if keyframes:
            blocked.append("中段关键帧")
        if voice_ids:
            blocked.append("预置声音参考")
        if first and references:
            blocked.append("首帧与参考图同用")
        if blocked:
            raise GrokSpecError("经典 grok-imagine-video 不支持" + "、".join(blocked) + "；请使用 1.5 系列模型")
    if references and resolution not in REFERENCE_RESOLUTIONS:
        raise GrokSpecError("Grok 参考模式分辨率最高 720p；更高分辨率请走首帧图生视频")
    if not references and resolution not in FRAME_RESOLUTIONS:
        raise GrokSpecError("Grok 视频分辨率须为 480p、720p 或 1080p")
    for _, at in keyframes:
        if not 0 < float(at) < seconds:
            raise GrokSpecError(f"关键帧时间戳必须严格落在片内（0–{seconds}s）")
    stamps = sorted(float(at) for _, at in keyframes)
    for before, after in zip(stamps, stamps[1:]):
        if after - before < 1 / 3:
            raise GrokSpecError("关键帧时间戳须彼此间隔至少 1/3 秒")
    payload = {"model": model, "prompt": prompt, "duration": seconds, "resolution": resolution}
    if first:
        payload["image"] = {"url": first}
    if last:
        payload["last_frame"] = {"url": last}
    if references:
        payload["reference_images"] = [{"url": url} for url in references]
    if keyframes:
        payload["keyframes"] = [{"image": {"url": url}, "timestamp_s": float(at)} for url, at in keyframes]
    if voice_ids:
        payload["reference_audios"] = [{"voice_id": voice} for voice in voice_ids]
    if ratio:
        payload["aspect_ratio"] = ratio
    if generate_audio is False:
        payload["generate_audio"] = False
    return payload


def compile_video_operation(model, video, prompt, operation):
    """/v1/videos/edits 与 /v1/videos/extensions（输出跟随输入；extensions 的 prompt 平台必填）。"""
    if operation not in ("edit", "extend"):
        raise GrokSpecError("视频加工操作只能是 edit 或 extend")
    if advanced_model(model):
        raise GrokSpecError("视频编辑/续接由经典 grok-imagine-video 承担（线上实证 1.5 返回不支持）")
    if operation == "extend" and not str(prompt or "").strip():
        raise GrokSpecError("视频续接需要提示词（平台必填）")
    path = {"edit": "/videos/edits", "extend": "/videos/extensions"}[operation]
    payload = {"model": model, "video": {"url": video}}
    if str(prompt or "").strip():
        payload["prompt"] = str(prompt).strip()
    return path, payload
