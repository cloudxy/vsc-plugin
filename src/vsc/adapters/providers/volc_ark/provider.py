#!/usr/bin/env python3
"""Volc Ark image/video and Agent Plan speech adapters for series requests.

Construction and parsing are local. submit/poll are the only network seams, and
the caller must durably mark submission intent and reserve budget beforehand.
This module does not dispatch jobs or import temporary result URLs itself.
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable
import urllib.error
import urllib.request
import uuid

from vsc.adapters.providers.speech import tts as speech
from vsc.adapters.providers.volc_ark import api as volc_ark
from vsc.adapters.providers import credentials as credentials
from vsc.production.providers import AudioRequest, GeneratedAsset, ImageRequest, JobHandle, JobStatus, VideoRequest


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
        audio_refs = [self.media_url(media_id) for media_id in req.reference_audio_media_ids]
        # The existing Ark contract distinguishes hard first/last frames from
        # reference mode. Never silently weaken a hard frame to a reference.
        if (first or last) and (refs or audio_refs):
            raise VolcAdapterError("硬首尾帧与其他参考图不可混用；先调整统一镜头规格")
        content = volc_ark.video_content(req.prompt, first=first, last=last, images=refs, audios=audio_refs)
        payload = {"model": self.model, "content": content, "resolution": self.resolution,
                   "duration": req.duration_ms // 1000,
                   "generate_audio": self.generate_audio, "return_last_frame": True, "watermark": False}
        if not first:
            payload["ratio"] = self.ratio
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


class VolcArkAudioProvider:
    """Synchronous personal-plan TTS, staged by job ID for crash-safe transfer.

    The database dispatcher owns submit intent, budget, and generated assets.
    This adapter owns only the vendor request and a verified local response.
    """

    def __init__(self, model: str, project, job_id: str, binding: dict, defaults: dict, transport=None):
        self.model = model
        self.project = Path(project).resolve()
        self.job_id = job_id
        self.binding = binding
        self.defaults = defaults
        self.transport = transport
        self._validate_config()

    def _validate_config(self):
        voice = self.binding.get("voice") if isinstance(self.binding, dict) else None
        if (self.model != "seed-tts-2.0" or not isinstance(voice, dict)
                or voice.get("engine") != speech.PROVIDER
                or voice.get("resource_id", "seed-tts-2.0") != "seed-tts-2.0"
                or not isinstance(voice.get("voice"), str)
                or not speech.SAFE_ID.fullmatch(voice["voice"])):
            raise VolcAdapterError("预置语音模型、资源或角色音色绑定无效")
        if not isinstance(self.job_id, str) or not self.job_id.startswith("J-") or not self.job_id[2:].isalnum():
            raise VolcAdapterError("音频任务 ID 无效")
        if not isinstance(self.defaults, dict) or set(self.defaults) - {"format", "sample_rate", "speech_rate"}:
            raise VolcAdapterError("语音模型默认参数包含未映射字段")
        fmt = self.defaults.get("format", "wav")
        rate = self.defaults.get("sample_rate", 24000)
        speed = self.defaults.get("speech_rate", 0)
        if (fmt not in ("wav", "mp3") or rate not in (16000, 24000, 32000, 48000)
                or type(speed) is not int or not -50 <= speed <= 100):
            raise VolcAdapterError("语音格式、采样率或语速不在已验证映射内")

    def preflight(self, req: AudioRequest | None = None):
        if req is not None and (req.purpose != "dialogue_dry"
                or list(req.script_line_ids) != [self.binding["line_id"]]
                or not req.prompt.strip() or req.reference_media_ids or req.voice_media_id or req.params):
            raise VolcAdapterError("音频请求与已批准台词或当前预置音色能力不符")
        if self.transport is None:
            speech.api_key()
        if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
            raise VolcAdapterError("缺少 ffprobe/ffmpeg，不能验证生成音频")
        stage = self.project / ".vsc-staging"
        if stage.exists() and (stage.is_symlink() or not stage.is_dir()):
            raise VolcAdapterError("音频暂存目录无效")
        if (stage / (self.job_id + "." + self.defaults.get("format", "wav"))).exists():
            raise VolcAdapterError("同任务音频暂存文件已存在，须先人工核对")

    def _request(self, payload, resource_id):
        key = speech.api_key()
        request = urllib.request.Request(speech.ENDPOINTS["agent-plan"],
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"X-Api-Key": key, "X-Api-Resource-Id": resource_id,
                     "X-Api-Request-Id": str(uuid.uuid4()),
                     "X-Control-Require-Usage-Tokens-Return": "*",
                     "Content-Type": "application/json", "Connection": "keep-alive"})
        with (tempfile.TemporaryFile(mode="w+", encoding="utf-8") as journal,
              tempfile.TemporaryFile(mode="w+b") as audio):
            record = {"engine": {}, "budget": {"usage": {}}}
            try:
                with speech.open_stream(request) as response:
                    speech.stream_audio(response, audio, journal, record, key)
            except urllib.error.HTTPError as exc:
                denied = credentials.permission_denied(exc.code, "豆包语音合成")
                if denied:
                    raise VolcAdapterError(denied) from None
                raise
            audio.seek(0)
            return audio.read(), record["budget"]["usage"]

    def submit(self, req: AudioRequest) -> JobHandle:
        self.preflight(req)
        fmt = self.defaults.get("format", "wav")
        rate = self.defaults.get("sample_rate", 24000)
        payload = {"req_params": {"text": req.prompt, "speaker": self.binding["voice"]["voice"],
                   "audio_params": {"format": fmt, "sample_rate": rate,
                                    "speech_rate": self.defaults.get("speech_rate", 0)}}}
        audio, usage = (self.transport or self._request)(payload, "seed-tts-2.0")
        if not isinstance(audio, bytes) or not audio or not isinstance(usage, dict):
            raise VolcAdapterError("语音响应没有有效音频或用量信息")
        stage = self.project / ".vsc-staging"
        stage.mkdir(exist_ok=True)
        target = stage / (self.job_id + "." + fmt)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=stage, prefix=".speech-", suffix="." + fmt, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(audio)
                handle.flush()
                os.fsync(handle.fileno())
            speech.probe_audio(temporary, fmt, rate)
            digest = hashlib.sha256(audio).hexdigest()
            temporary.replace(target)
            descriptor = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        raw = {"status": "succeeded", "stage": str(target.relative_to(self.project)),
               "sha256": digest, "usage": usage, "speaker": self.binding["voice"]["voice"],
               "resource_id": "seed-tts-2.0"}
        return JobHandle("volc_ark", self.model, None, raw)

    def poll(self, handle: JobHandle) -> JobStatus:
        if handle.provider != "volc_ark" or handle.model != self.model:
            raise VolcAdapterError("语音任务句柄与适配器不匹配")
        return JobStatus("succeeded" if handle.raw.get("status") == "succeeded" else "failed", raw=handle.raw)

    def parse_result(self, raw: dict) -> list[GeneratedAsset]:
        if (not isinstance(raw, dict) or raw.get("status") != "succeeded"
                or raw.get("speaker") != self.binding["voice"]["voice"]
                or raw.get("resource_id") != "seed-tts-2.0"):
            raise VolcAdapterError("语音结果与角色绑定不匹配")
        expected = ".vsc-staging/" + self.job_id + "." + self.defaults.get("format", "wav")
        digest = raw.get("sha256")
        if raw.get("stage") != expected or not isinstance(digest, str) or len(digest) != 64:
            raise VolcAdapterError("语音结果暂存路径或摘要无效")
        return [GeneratedAsset("audio", local_path=expected, sha256=digest,
            metadata={"speaker": raw["speaker"], "resource_id": raw["resource_id"],
                      "line_id": self.binding["line_id"], "entity_id": self.binding["entity_id"]})]
