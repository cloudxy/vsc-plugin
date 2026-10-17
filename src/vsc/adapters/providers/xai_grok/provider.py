#!/usr/bin/env python3
"""xAI Grok Imagine image/video adapters for series and PostgreSQL worker requests.

Construction and parsing are local. submit/poll are the only network seams, and
the caller must durably mark submission intent and reserve budget beforehand.
This module does not dispatch jobs or import temporary result URLs itself.
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
    """Synchronous text-to-image on the subscription login route."""

    def __init__(self, model: str, ratio_for: Callable[[int, int], str], resolution: str = "2k",
                 transport=None):
        self.model = model
        self.ratio_for = ratio_for
        self.resolution = resolution
        self.transport = transport or grok.call

    def submit(self, req: ImageRequest) -> JobHandle:
        if req.width < 1 or req.height < 1 or not req.prompt.strip():
            raise GrokAdapterError("图像规格缺宽高或提示词")
        if req.reference_media_ids:
            raise GrokAdapterError("Grok 订阅图像路线未接参考图编辑；先按统一规格出图，不要夹带参考素材")
        ratio = self.ratio_for(req.width, req.height)
        if not isinstance(ratio, str) or not ratio:
            raise GrokAdapterError("此图像尺寸没有已配置的 Grok 画幅映射")
        payload = grok.image_payload(self.model, req.prompt, ratio, self.resolution, 1)
        raw = self.transport("/images/generations", payload)
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
    """First-frame-anchored image-to-video; the ratio always follows the source image."""

    def __init__(self, model: str, media_url: Callable[[str], str], resolution: str, transport=None):
        self.model = model
        self.media_url = media_url
        self.resolution = resolution
        self.transport = transport or grok.call

    def submit(self, req: VideoRequest) -> JobHandle:
        if req.duration_ms < 1000 or req.duration_ms % 1000 or req.duration_ms > 15000 or not req.prompt.strip():
            raise GrokAdapterError("Grok 视频时长须为 1–15 整秒且提示词非空")
        if req.last_frame_media_id:
            raise GrokAdapterError("Grok 图生视频不支持尾帧锁定；尾帧需求请单独出图")
        if req.reference_media_ids or req.reference_audio_media_ids:
            raise GrokAdapterError("Grok 视频路线仅支持首帧锚定，不接其他参考素材")
        if not req.first_frame_media_id:
            raise GrokAdapterError("Grok 视频路线需要首帧（图生视频）")
        payload = grok.video_payload(self.model, req.prompt, self.media_url(req.first_frame_media_id),
                                     req.duration_ms // 1000, self.resolution)
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
