#!/usr/bin/env python3
"""xAI Grok Imagine image/video adapters for series and PostgreSQL worker requests.

Construction and parsing are local. submit/poll are the only network seams, and
the caller must durably mark submission intent and reserve budget beforehand.
This module does not dispatch jobs or import temporary result URLs itself.

Video modes on grok-imagine-video-1.5 (official spec): text-to-video, image-to-video
(``image`` pins the first frame), reference-to-video (up to 14 ``reference_images``,
``image`` may combine with references and then takes the pinned first frame,
``last_frame`` pins the closing frame). Preset voice references and mid-clip
keyframes exist on the platform but are not wired here.
"""
from __future__ import annotations
import base64
import binascii
from typing import Callable

from vsc.adapters.providers.xai_grok import api as grok
from vsc.production.providers import GeneratedAsset, ImageRequest, JobHandle, JobStatus, VideoRequest


class GrokAdapterError(ValueError):
    pass


class GrokImageProvider:
    """Synchronous text-to-image and reference-guided edits on the subscription login route."""

    def __init__(self, model: str, media_url: Callable[[str], str], ratio_for: Callable[[int, int], str],
                 resolution: str = "2k", transport=None):
        self.model = model
        self.media_url = media_url
        self.ratio_for = ratio_for
        self.resolution = resolution
        self.transport = transport or grok.call

    def submit(self, req: ImageRequest) -> JobHandle:
        if req.width < 1 or req.height < 1 or not req.prompt.strip():
            raise GrokAdapterError("图像规格缺宽高或提示词")
        references = list(req.reference_media_ids)
        if len(references) > 5:
            raise GrokAdapterError("Grok 图像编辑一次最多 5 张源图")
        if references:
            # /v1/images/edits：单源图 image，多源图 images 合成；提示词只写要改的内容。
            payload = grok.edit_payload(self.model, req.prompt, [self.media_url(m) for m in references])
            path = "/images/edits"
        else:
            ratio = self.ratio_for(req.width, req.height)
            if not isinstance(ratio, str) or not ratio:
                raise GrokAdapterError("此图像尺寸没有已配置的 Grok 画幅映射")
            payload = grok.image_payload(self.model, req.prompt, ratio, self.resolution, 1)
            path = "/images/generations"
        raw = self.transport(path, payload)
        if not isinstance(raw, dict):
            raise GrokAdapterError("Grok 图像响应不是对象；提交结果须按未知处理并对账")
        return JobHandle("xai_grok", self.model, None, raw)

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "xai_grok" or handle.model != self.model:
            raise GrokAdapterError("图像任务句柄与适配器不匹配")
        if isinstance(handle.raw.get("data"), list) and handle.raw["data"]:
            return JobStatus("succeeded", raw=handle.raw)
        return JobStatus("failed", error_code="invalid_image_response", raw=handle.raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        items = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(items, list) or not items:
            raise GrokAdapterError("图像响应没有候选素材")
        output = []
        for item in items:
            if not isinstance(item, dict):
                raise GrokAdapterError("图像候选格式无效")
            uri = item.get("url")
            encoded = item.get("b64_json")
            if isinstance(uri, str) and uri.startswith("https://"):
                output.append(GeneratedAsset("image", temporary_uri=uri,
                    metadata={k: v for k, v in item.items() if k not in ("url", "b64_json")}))
            elif isinstance(encoded, str):
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise GrokAdapterError("图像 base64 响应无效") from exc
                output.append(GeneratedAsset("image", inline_bytes=data,
                    metadata={k: v for k, v in item.items() if k not in ("url", "b64_json")}))
            else:
                raise GrokAdapterError("图像候选缺 URL 或 base64")
        return output


class GrokVideoProvider:
    """Text-to-video, first/last-frame pinning, keyframes and reference-to-video.

    Modes (chosen by the frozen request): ``image`` alone is image-to-video with the
    first frame anchored; ``reference_images`` (1–14) guide identity/scene without
    pinning; ``image`` + references keeps the pinned first frame (prompt then numbers
    it <IMAGE_0> and references from <IMAGE_1>); ``last_frame`` pins the closing
    frame and may combine with references; prompt-only is text-to-video.
    ``keyframes`` pins up to 4 mid-clip frames at second timestamps; ``voice_ids``
    carries platform preset voice ids from the provider registry (the DB field for
    platform resource ids) into ``reference_audios``. last_frame/keyframes/voices
    and image+reference combination require the 1.5 generation of the model.
    """

    REFERENCE_LIMIT = 14
    VOICE_LIMIT = 3
    KEYFRAME_LIMIT = 4
    REFERENCE_RESOLUTIONS = ("480p", "720p")
    FRAME_RESOLUTIONS = ("480p", "720p", "1080p")

    def __init__(self, model: str, media_url: Callable[[str], str], resolution: str,
                 ratio: str = "", voice_ids=(), generate_audio=True, transport=None):
        self.model = model
        self.media_url = media_url
        self.resolution = resolution
        self.ratio = ratio or ""
        self.voice_ids = tuple(voice_ids or ())
        if len(self.voice_ids) > self.VOICE_LIMIT:
            raise GrokAdapterError(f"Grok 预置声音参考最多 {self.VOICE_LIMIT} 个")
        self.generate_audio = generate_audio
        self.transport = transport or grok.call
        self.advanced = "1.5" in model

    def submit(self, req: VideoRequest) -> JobHandle:
        maximum_ms = 15000 if self.advanced else 10000
        if req.duration_ms < 1000 or req.duration_ms % 1000 or req.duration_ms > maximum_ms or not req.prompt.strip():
            raise GrokAdapterError(f"Grok 视频时长须为 1–{maximum_ms // 1000} 整秒且提示词非空")
        if req.reference_audio_media_ids:
            raise GrokAdapterError("Grok 视频的 reference_audios 只接平台预置 voice_id（登记在模型默认参数 reference_voice_ids），不能传音频素材文件")
        keyframes = [(self.media_url(media_id), float(seconds)) for media_id, seconds in (req.keyframes or ())]
        if len(keyframes) > self.KEYFRAME_LIMIT:
            raise GrokAdapterError(f"Grok 中段关键帧最多 {self.KEYFRAME_LIMIT} 个")
        if not self.advanced:  # 经典 grok-imagine-video 的官方限制
            classic_features = []
            if req.last_frame_media_id:
                classic_features.append("尾帧钉定")
            if keyframes:
                classic_features.append("中段关键帧")
            if self.voice_ids:
                classic_features.append("预置声音参考")
            if req.first_frame_media_id and req.reference_media_ids:
                classic_features.append("首帧与参考图同用")
            if classic_features:
                raise GrokAdapterError("经典 grok-imagine-video 不支持" + "、".join(classic_features) + "；请使用 1.5 系列模型")
        seconds = req.duration_ms // 1000
        for _, at in keyframes:
            if not 0 < at < seconds:
                raise GrokAdapterError("关键帧时间戳必须严格落在片内（大于 0 且小于时长）")
        stamps = sorted(at for _, at in keyframes)
        for before, after in zip(stamps, stamps[1:]):
            if after - before < 1 / 3:
                raise GrokAdapterError("关键帧时间戳须彼此间隔至少 1/3 秒")
        first = self.media_url(req.first_frame_media_id) if req.first_frame_media_id else None
        last = self.media_url(req.last_frame_media_id) if req.last_frame_media_id else None
        references = [self.media_url(media_id) for media_id in req.reference_media_ids]
        if len(references) > self.REFERENCE_LIMIT:
            raise GrokAdapterError(f"Grok 参考模式一次最多 {self.REFERENCE_LIMIT} 张参考图")
        reference_mode = bool(references)
        if reference_mode and self.resolution not in self.REFERENCE_RESOLUTIONS:
            raise GrokAdapterError("Grok 参考模式分辨率最高 720p；更高分辨率请走首帧图生视频")
        if not reference_mode and self.resolution not in self.FRAME_RESOLUTIONS:
            raise GrokAdapterError("Grok 视频分辨率须为 480p、720p 或 1080p")
        payload = grok.video_payload(self.model, req.prompt, first, seconds, self.resolution,
                                     last_frame=last, reference_images=references, aspect_ratio=self.ratio,
                                     keyframes=keyframes, voice_ids=self.voice_ids,
                                     generate_audio=self.generate_audio)
        raw = self.transport("/videos/generations", payload)
        task_id = raw.get("request_id") if isinstance(raw, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise GrokAdapterError("Grok 视频响应缺 request_id；提交结果须按未知处理并对账")
        return JobHandle("xai_grok", self.model, task_id, raw)

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "xai_grok" or handle.model != self.model or not handle.external_task_id:
            raise GrokAdapterError("视频任务句柄与适配器不匹配")
        raw = self.transport(f"/videos/{handle.external_task_id}")
        if not isinstance(raw, dict):
            raise GrokAdapterError("Grok 视频查询响应不是对象")
        status = raw.get("status")
        if status == "done":
            return JobStatus("succeeded", raw=raw)
        if status in ("failed", "expired"):
            return JobStatus("failed", error_code=str(status), raw=raw)
        if status == "pending":
            return JobStatus("submitted", raw=raw)
        return JobStatus("running", raw=raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        content = raw.get("video") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or raw.get("status") != "done" or not isinstance(content, dict):
            raise GrokAdapterError("视频任务尚未成功")
        url = content.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise GrokAdapterError("视频结果缺有效下载 URL")
        return [GeneratedAsset("video", temporary_uri=url,
            metadata={k: content[k] for k in ("duration", "respect_moderation") if k in content})]
