"""Seed-Audio MediaKit adapter for original PG jobs, without the CLI ledger."""
import base64
import binascii
import hashlib
import json

from vsc.assets.resource_service import ResourceError
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
from vsc.adapters.providers.credentials import KEY_ENV
from vsc.adapters.providers.speech import audio


PURPOSES = {"music", "bgm", "ambience", "sfx"}


class MediaKitAudioProvider:
    def __init__(self, job, storage, *, transport=None, read_key=None):
        self.job, self.storage = job, storage
        self.transport, self.read_key = transport or audio.call, read_key or audio.api_key
        self.maximum = job["model"].get("default_params", {}).get("max_prompt_chars", 2000)

    def preflight(self, request):
        if request.purpose not in PURPOSES or request.script_line_ids or request.voice_media_id or request.reference_media_ids:
            raise ResourceError("Seed-Audio 仅接文本描述的音乐、环境声或音效候选，不接对白、音色或参考输入", "audio_request_unsupported")
        if request.params or not request.prompt.strip() or len(request.prompt) > self.maximum:
            raise ResourceError("Seed-Audio 提示词超出固定字符预算或存在未支持参数", "audio_request_unsupported")
        self.read_key(KEY_ENV)

    def _call(self, path, payload=None):
        key = self.read_key(KEY_ENV)
        value = self.transport(path, key, payload)
        # External task evidence never records the credential value.
        return json.loads(json.dumps(value, ensure_ascii=False).replace(key, "[REDACTED]"))

    def submit(self, request):
        self.preflight(request)
        raw = self._call(audio.SUBMIT, {"api": "doubao.audio_generation", "maas_params": {"model": audio.MODEL,
            "text_prompt": request.prompt, "audio_config": {"format": "mp3", "sample_rate": 48000,
                "pitch_rate": 0, "speech_rate": 0, "loudness_rate": 0}}})
        return JobHandle(self.job["provider_id"], audio.MODEL, audio.valid_task_id(raw), raw)

    def poll(self, handle):
        if not isinstance(handle.external_task_id, str) or not audio.SAFE_ID.fullmatch(handle.external_task_id):
            raise ResourceError("固定任务编号无效", "audio_task_invalid")
        raw = self._call("/api/v1/tasks/" + handle.external_task_id)
        if raw.get("success") is not True or raw.get("task_id") != handle.external_task_id:
            raise ResourceError("MediaKit 回执与固定任务不符", "audio_task_mismatch")
        status = raw.get("status")
        if status == "completed":
            audio.completed_response(raw, handle.external_task_id)
            return JobStatus("succeeded", raw=raw)
        if status in {"failed", "cancelled", "canceled"}:
            return JobStatus("failed", error_code="mediakit_audio_failed", raw=raw)
        if status in {"pending", "queued", "running", "processing"}:
            return JobStatus("running", raw=raw)
        raise ResourceError("MediaKit 状态无法识别，保留任务编号等待核对", "audio_status_unknown")

    def parse_result(self, raw):
        result = audio.completed_response(raw, raw.get("task_id"))
        encoded = result["maas_result"].get("audio")
        if not isinstance(encoded, str) or len(encoded) > audio.MAX_AUDIO_BYTES * 4 // 3 + 8:
            raise ResourceError("音频结果缺失或过大", "audio_result_invalid")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ResourceError("音频结果不是有效 Base64", "audio_result_invalid") from None
        if not content or len(content) > audio.MAX_AUDIO_BYTES:
            raise ResourceError("音频结果为空或过大", "audio_result_invalid")
        digest = hashlib.sha256(content).hexdigest()
        key = "provider-audio/" + digest + ".mp3"
        target = self.storage.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Content address makes retry/recovery refer to the same bytes.
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ResourceError("缓存的原音频已改变", "audio_result_changed")
        if not target.exists():
            target.write_bytes(content)
        metadata = audio.probe_audio(target, "mp3", 48000)
        return [GeneratedAsset("audio", local_path=key, sha256=digest,
            metadata=dict(metadata, intended_purpose=self.job["purpose"], professional_review="not_performed",
                          billing_amount="unknown"))]


def mediakit_audio_factory(job, storage, *, transport=None, read_key=None):
    provider, model = job["provider"], job["model"]
    identity = provider.get("configuration", {})
    if (identity.get("supplier") != "volcengine" or identity.get("product") != "mediakit"
            or identity.get("plan") != "agent-plan" or identity.get("execution") != "api"
            or provider.get("base_url", "").rstrip("/") != audio.BASE or provider.get("auth_ref") != KEY_ENV
            or model.get("model_key") != audio.MODEL or job.get("modality") != "audio"
            or job.get("purpose") not in PURPOSES):
        raise ResourceError("MediaKit 音频配置与固定路线不符", "invalid_provider_config")
    maximum = model.get("default_params", {}).get("max_prompt_chars", 2000)
    if type(maximum) is not int or not 1 <= maximum <= 20000:
        raise ResourceError("音频固定字符预算无效", "invalid_model_defaults")
    return MediaKitAudioProvider(job, storage, transport=transport, read_key=read_key)
