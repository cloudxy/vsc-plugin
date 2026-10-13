#!/usr/bin/env python3
"""Volc Ark image/video adapters for the provider-neutral series request contract.

Construction and parsing are local. submit/poll are the only network seams, and
the caller must durably mark submission intent and reserve budget beforehand.
This module does not dispatch jobs or import temporary result URLs itself.
"""
import base64
import binascii
from typing import Callable

import volc_ark
from vsc_provider import GeneratedAsset, ImageRequest, JobHandle, JobStatus, VideoRequest


class VolcAdapterError(ValueError):
    pass


class VolcArkImageProvider:
    def __init__(self, model: str, media_url: Callable[[str], str], size_for: Callable[[int, int], str],
                 transport=None):
        self.model = model
        self.media_url = media_url
        self.size_for = size_for
        self.transport = transport or volc_ark.call

    def submit(self, req: ImageRequest) -> JobHandle:
        if req.width < 1 or req.height < 1 or not req.prompt.strip():
            raise VolcAdapterError("图像规格缺宽高或提示词")
        size = self.size_for(req.width, req.height)
        if not isinstance(size, str) or not size:
            raise VolcAdapterError("此图像尺寸没有已配置的方舟映射")
        images = [self.media_url(media_id) for media_id in req.reference_media_ids]
        payload = volc_ark.image_payload(self.model, req.prompt, size, images)
        raw = self.transport("/images/generations", payload)
        if not isinstance(raw, dict):
            raise VolcAdapterError("方舟图像响应不是对象；提交结果须按未知处理并对账")
        return JobHandle("volc_ark", self.model, None, raw)

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "volc_ark" or handle.model != self.model:
            raise VolcAdapterError("图像任务句柄与适配器不匹配")
        if isinstance(handle.raw.get("data"), list) and handle.raw["data"]:
            return JobStatus("succeeded", raw=handle.raw)
        return JobStatus("failed", error_code="invalid_image_response", raw=handle.raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        items = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(items, list) or not items:
            raise VolcAdapterError("图像响应没有候选素材")
        output = []
        for item in items:
            if not isinstance(item, dict):
                raise VolcAdapterError("图像候选格式无效")
            uri = item.get("url")
            encoded = item.get("b64_json")
            if isinstance(uri, str) and uri.startswith("https://"):
                output.append(GeneratedAsset("image", temporary_uri=uri,
                    metadata={k: v for k, v in item.items() if k not in ("url", "b64_json")}))
            elif isinstance(encoded, str):
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise VolcAdapterError("图像 base64 响应无效") from exc
                output.append(GeneratedAsset("image", inline_bytes=data,
                    metadata={k: v for k, v in item.items() if k not in ("url", "b64_json")}))
            else:
                raise VolcAdapterError("图像候选缺 URL 或 base64")
        return output


class VolcArkVideoProvider:
    def __init__(self, model: str, media_url: Callable[[str], str], resolution: str, ratio: str,
                 generate_audio: bool = False, transport=None):
        self.model = model
        self.media_url = media_url
        self.resolution = resolution
        self.ratio = ratio
        self.generate_audio = generate_audio
        self.transport = transport or volc_ark.call

    def submit(self, req: VideoRequest) -> JobHandle:
        if req.duration_ms < 1000 or req.duration_ms % 1000 or not req.prompt.strip():
            raise VolcAdapterError("方舟视频时长须为整秒且提示词非空")
        first = self.media_url(req.first_frame_media_id) if req.first_frame_media_id else None
        last = self.media_url(req.last_frame_media_id) if req.last_frame_media_id else None
        refs = [self.media_url(media_id) for media_id in req.reference_media_ids]
        # The existing Ark contract distinguishes hard first/last frames from
        # reference mode. Never silently weaken a hard frame to a reference.
        if (first or last) and refs:
            raise VolcAdapterError("硬首尾帧与其他参考图不可混用；先调整统一镜头规格")
        content = volc_ark.video_content(req.prompt, first=first, last=last, images=refs)
        payload = {"model": self.model, "content": content, "resolution": self.resolution,
                   "ratio": self.ratio, "duration": req.duration_ms // 1000,
                   "generate_audio": self.generate_audio, "return_last_frame": True, "watermark": False}
        raw = self.transport("/contents/generations/tasks", payload)
        task_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise VolcAdapterError("方舟视频响应缺任务 ID；提交结果须按未知处理并对账")
        return JobHandle("volc_ark", self.model, task_id, raw)

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "volc_ark" or handle.model != self.model or not handle.external_task_id:
            raise VolcAdapterError("视频任务句柄与适配器不匹配")
        raw = self.transport(f"/contents/generations/tasks/{handle.external_task_id}")
        if not isinstance(raw, dict):
            raise VolcAdapterError("方舟视频查询响应不是对象")
        status = raw.get("status")
        if status == "succeeded":
            return JobStatus("succeeded", raw=raw)
        if status in ("failed", "cancelled", "expired"):
            return JobStatus("failed", error_code=str(status), raw=raw)
        if status in ("queued", "pending", "submitted"):
            return JobStatus("submitted", raw=raw)
        return JobStatus("running", raw=raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        content = raw.get("content") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or raw.get("status") != "succeeded" or not isinstance(content, dict):
            raise VolcAdapterError("视频任务尚未成功")
        url = content.get("video_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise VolcAdapterError("视频结果缺有效下载 URL")
        output = [GeneratedAsset("video", temporary_uri=url,
            metadata={k: raw[k] for k in ("duration", "resolution", "ratio", "framespersecond") if k in raw})]
        last = content.get("last_frame_url")
        if isinstance(last, str) and last.startswith("https://"):
            output.append(GeneratedAsset("image", temporary_uri=last, metadata={"role": "last_frame"}))
        return output
