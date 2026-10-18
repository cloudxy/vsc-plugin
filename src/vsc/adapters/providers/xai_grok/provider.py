#!/usr/bin/env python3
"""xAI Grok Imagine image/video adapters for series and PostgreSQL worker requests.

Construction, validation and payload compilation are local via the shared
``spec`` module (B2-01): CLI, series and this provider get identical payloads or
identical rejections. ``preflight`` runs every local check (parameters, model
combination, credentials) without network so callers refuse invalid requests
before reserving budget or recording submission intent. submit/poll remain the
only network seams.
"""
from __future__ import annotations
import base64
import binascii
from typing import Callable

from vsc.adapters.providers.xai_grok import api as grok
from vsc.adapters.providers.xai_grok import spec
from vsc.adapters.providers.xai_grok import credentials as credentials
from vsc.production.providers import GeneratedAsset, ImageRequest, JobHandle, JobStatus, VideoRequest


class GrokAdapterError(ValueError):
    pass


ACCOUNT_FIELD = "_vsc_grok_account_sha256"

def bound_response(raw, account):
    return {**raw, ACCOUNT_FIELD: account}

def verify_account(raw):
    saved = raw.get(ACCOUNT_FIELD) if isinstance(raw, dict) else None
    if not saved:
        raise GrokAdapterError("旧任务缺少稳定账号身份证据，不能猜测归属；请人工核对原提交账号")
    if saved != credentials.account_sha256(error=GrokAdapterError):
        raise GrokAdapterError("当前登录账号与原任务提交账号不一致，拒绝查询或下载")

def local_auth():
    grok.base_url()
    problem = credentials.key_problem()
    if problem:
        raise GrokAdapterError(problem)
    return credentials.account_sha256(error=GrokAdapterError)


class GrokImageProvider:
    """Synchronous text-to-image and reference-guided edits on the subscription login route."""

    def __init__(self, model: str, media_url: Callable[[str], str], ratio_for: Callable[[int, int], str],
                 resolution: str = "2k", transport=None):
        self.model = model
        self.media_url = media_url
        self.ratio_for = ratio_for
        self.resolution = resolution
        self.transport = transport or grok.call

    def _compile(self, req: ImageRequest):
        params = req.params or {}
        if set(params) - {"resolution", "aspect_ratio"}:
            raise GrokAdapterError("Grok 图像未支持参数：" + ",".join(sorted(set(params) - {"resolution", "aspect_ratio"})))
        references = [self.media_url(media_id) for media_id in req.reference_media_ids]
        ratio = params.get("aspect_ratio", self.ratio_for(req.width, req.height))
        try:
            return spec.compile_image(self.model, req.prompt, references, ratio, params.get("resolution", self.resolution), 1)
        except spec.GrokSpecError as exc:
            raise GrokAdapterError(str(exc)) from None

    def preflight(self, req: ImageRequest = None):
        """All local checks (no network): invalid requests must fail before budget."""
        if req is not None:
            if req.width < 1 or req.height < 1:
                raise GrokAdapterError("图像规格缺宽高")
            self._compile(req)
        local_auth()

    def submit(self, req: ImageRequest) -> JobHandle:
        self.preflight(req)
        path, payload = self._compile(req)
        account = local_auth()
        raw = self.transport(path, payload)
        if not isinstance(raw, dict):
            raise GrokAdapterError("Grok 图像响应不是对象；提交结果须按未知处理并对账")
        return JobHandle("xai_grok", self.model, None, bound_response(raw, account))

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "xai_grok" or handle.model != self.model:
            raise GrokAdapterError("图像任务句柄与适配器不匹配")
        if isinstance(handle.raw.get("data"), list) and handle.raw["data"]:
            return JobStatus("succeeded", raw=handle.raw)
        return JobStatus("failed", error_code="invalid_image_response", raw=handle.raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        verify_account(raw)
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

    Modes are chosen by the frozen request; every local rule (duration, model
    generation limits, reference/keyframe/voice caps, resolution ceilings) lives
    in ``spec.compile_video`` so the CLI and both job stacks judge identically.
    """

    def __init__(self, model: str, media_url: Callable[[str], str], resolution: str,
                 ratio: str = "", voice_ids=(), generate_audio=True, transport=None):
        self.model = model
        self.media_url = media_url
        self.resolution = resolution
        self.ratio = ratio or ""
        self.voice_ids = tuple(voice_ids or ())
        self.generate_audio = generate_audio
        self.transport = transport or grok.call

    def _compile(self, req: VideoRequest):
        params = req.params or {}
        supported = {"resolution", "aspect_ratio", "generate_audio", "reference_voice_ids"}
        if set(params) - supported:
            raise GrokAdapterError("Grok 视频生成未支持参数（PG edit/extend 加工协议尚未接通）：" + ",".join(sorted(set(params) - supported)))
        keyframes = [(self.media_url(media_id), float(seconds)) for media_id, seconds in (req.keyframes or ())]
        first = self.media_url(req.first_frame_media_id) if req.first_frame_media_id else None
        last = self.media_url(req.last_frame_media_id) if req.last_frame_media_id else None
        references = [self.media_url(media_id) for media_id in req.reference_media_ids]
        try:
            return spec.compile_video(self.model, req.prompt, req.duration_ms, first, last, references,
                                      keyframes, params.get("reference_voice_ids", self.voice_ids), params.get("aspect_ratio", self.ratio),
                                      params.get("resolution", self.resolution), params.get("generate_audio", self.generate_audio))
        except spec.GrokSpecError as exc:
            raise GrokAdapterError(str(exc)) from None

    def preflight(self, req: VideoRequest = None):
        """All local checks (no network) before any budget reservation or intent."""
        if req is not None:
            if req.reference_audio_media_ids:
                raise GrokAdapterError("Grok 视频的 reference_audios 只接平台预置 voice_id（模型默认参数 reference_voice_ids），不能传音频素材文件")
            self._compile(req)
        local_auth()

    def submit(self, req: VideoRequest) -> JobHandle:
        self.preflight(req)
        payload = self._compile(req)
        account = local_auth()
        raw = self.transport("/videos/generations", payload)
        task_id = raw.get("request_id") if isinstance(raw, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise GrokAdapterError("Grok 视频响应缺 request_id；提交结果须按未知处理并对账")
        return JobHandle("xai_grok", self.model, task_id, bound_response(raw, account))

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "xai_grok" or handle.model != self.model or not handle.external_task_id:
            raise GrokAdapterError("视频任务句柄与适配器不匹配")
        local_auth()
        verify_account(handle.raw)
        raw = self.transport(f"/videos/{handle.external_task_id}")
        if not isinstance(raw, dict):
            raise GrokAdapterError("Grok 视频查询响应不是对象")
        raw = bound_response(raw, handle.raw[ACCOUNT_FIELD])
        status = raw.get("status")
        if status == "done":
            return JobStatus("succeeded", raw=raw)
        if status in ("failed", "expired"):
            return JobStatus("failed", error_code=str(status), raw=raw)
        if status == "pending":
            return JobStatus("submitted", raw=raw)
        return JobStatus("running", raw=raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        verify_account(raw)
        content = raw.get("video") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or raw.get("status") != "done" or not isinstance(content, dict):
            raise GrokAdapterError("视频任务尚未成功")
        url = content.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise GrokAdapterError("视频结果缺有效下载 URL")
        return [GeneratedAsset("video", temporary_uri=url,
            metadata={k: content[k] for k in ("duration", "respect_moderation") if k in content})]
