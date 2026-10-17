"""Durable PostgreSQL generation consumer; transports are injectable.

Only explicit worker invocation can contact a provider. Unknown submissions are
never re-submitted. Result bytes are committed before the job can succeed.
"""
from dataclasses import fields
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from vsc.assets.resource_service import ResourceError
from vsc.production.providers import AudioRequest, ImageRequest, JobHandle, VideoRequest

REQUEST_TYPES = {"image": ImageRequest, "video": VideoRequest, "audio": AudioRequest}


class ResourceWorker:
    def __init__(self, service, adapter_factory, worker_id=None, download=None):
        if service.storage is None:
            raise ResourceError("生成消费者需要受控存储", "storage_required")
        self.service, self.storage = service, service.storage
        self.adapter_factory = adapter_factory
        self.worker_id = worker_id or "resource-worker-" + uuid.uuid4().hex
        self.download = download

    def _write(self, action, project_id, payload, key):
        revision = self.service.get_project(project_id)["revision"]
        return getattr(self.service, action)(project_id, payload, expected_revision=revision,
            idempotency_key=key, actor=self.worker_id)

    def _request(self, job):
        raw = job["request_payload"]
        raw = raw.get("logical_request", raw)
        request_type = REQUEST_TYPES[job["modality"]]
        allowed = {field.name for field in fields(request_type)}
        values = {key: value for key, value in raw.items() if key in allowed}
        values.update(shot_id=job["shot_id"], purpose=job["purpose"], context_sha256=job["context_sha256"])
        if job.get("asset_id"):
            values["asset_id"] = job["asset_id"]
        request = request_type(**values)
        fixed = {item["media_id"] for item in job["input_media"]}
        used = set(request.reference_media_ids)
        used.update(getattr(request, "reference_audio_media_ids", ()))
        used.update(media_id for media_id, _ in (getattr(request, "keyframes", None) or ()))
        used.update(value for value in (getattr(request, "first_frame_media_id", None),
            getattr(request, "last_frame_media_id", None), getattr(request, "voice_media_id", None)) if value)
        if used - fixed:
            raise ResourceError("请求引用不属于任务固定输入", "unfixed_reference")
        return request

    def _verify_inputs(self, job):
        for item in job["input_media"]:
            verified = False
            for location in item.get("locations", []):
                if location["storage"] == "local" and location["available"]:
                    self.storage.verify(location["object_key"], item["blob_sha256"])
                    verified = True
                    break
            if not verified:
                raise ResourceError("固定输入未配置可验证字节", "media_unavailable")

    def run_once(self, project_id=None, poll=False):
        statuses = ("submitted", "running") if poll else ("created",)
        job = self.service.claim_generation_job(self.worker_id, project_id=project_id, statuses=statuses)
        if not job:
            return None
        self._verify_inputs(job)
        adapter = self.adapter_factory(job, self.storage)
        started = time.monotonic()
        if not poll:
            context = (self.service.compile_asset_context(job["project_id"], job["asset_id"], job["purpose"])
                       if job.get("asset_id") else self.service.compile_shot_context(job["project_id"], job["shot_id"], job["purpose"]))
            if not context["ready"] or context["sha256"] != job["context_sha256"]:
                raise ResourceError("任务固定输入已失效，须重编译后创建新候选", "stale_job")
            request = self._request(job)
            if hasattr(adapter, "preflight"):
                adapter.preflight(request)
            self._write("mark_submission_started", job["project_id"], {"job_id": job["id"], "worker_id": self.worker_id},
                        "intent:" + job["id"])
            # Exceptions deliberately leave a durable unknown result. A retry
            # cannot claim it and therefore cannot repeat a paid POST.
            handle = adapter.submit(request)
            self._write("record_submission_result", job["project_id"], {"job_id": job["id"], "worker_id": self.worker_id,
                "external_task_id": handle.external_task_id, "raw_response": handle.raw,
                "provider_status": "submitted"}, "response:" + job["id"])
            status = adapter.poll(handle) if handle.external_task_id is None else None
        else:
            handle = JobHandle(job["provider_id"], job["model"]["model_key"], job["external_task_id"], job.get("raw_response") or {})
            status = adapter.poll(handle)
        if status is None:
            return self.service.get_generation_job(job["project_id"], job["id"])
        if status.status == "succeeded":
            return self.finalize(job["project_id"], job["id"], adapter=adapter, raw=status.raw,
                                 latency_ms=round((time.monotonic() - started) * 1000))
        return self._write("update_generation_job", job["project_id"], {"job_id": job["id"], "worker_id": self.worker_id,
            "status": status.status, "external_task_id": handle.external_task_id, "raw_response": status.raw,
            "recovery_evidence": {"source": "provider_response", "error_code": status.error_code}},
            "status:" + job["id"] + ":" + uuid.uuid4().hex)

    def finalize(self, project_id, job_id, adapter=None, raw=None, latency_ms=None):
        job = self.service.get_generation_job(project_id, job_id)
        if job["status"] == "succeeded":
            return job
        raw = raw if raw is not None else job.get("raw_response")
        if not raw:
            raise ResourceError("没有已持久化的成功响应，不能恢复转存", "response_missing")
        adapter = adapter or self.adapter_factory(job, self.storage)
        outputs = adapter.parse_result(raw)
        if not outputs:
            raise ResourceError("Provider 返回空结果", "empty_output")
        registered = []
        for index, output in enumerate(outputs):
            if output.modality != job["modality"] and not (job["modality"] == "video" and output.modality == "image"):
                raise ResourceError("输出模态与任务不一致", "output_modality")
            suffix = {"image": ".png", "video": ".mp4", "audio": ".wav"}[output.modality]
            name = "generated-" + job_id + "-" + str(index) + suffix
            original = None
            if output.inline_bytes is not None:
                content = output.inline_bytes
            elif output.local_path:
                path = self.storage.resolve(output.local_path)
                if not output.sha256 or hashlib.sha256(path.read_bytes()).hexdigest() != output.sha256:
                    raise ResourceError("本地输出字节摘要不符", "output_changed")
                content = path.read_bytes()
                name = path.name
            elif output.temporary_uri:
                parsed = urlsplit(output.temporary_uri)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ResourceError("结果下载必须使用 HTTPS", "unsafe_output_url")
                original = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                with tempfile_for_download(self.storage, suffix) as path:
                    download = self.download
                    if download is None:
                        raise ResourceError("URL 结果需要已配置的下载适配器", "download_adapter_required")
                    download(output.temporary_uri, path)
                    content = path.read_bytes()
            else:
                raise ResourceError("输出没有可转存字节", "output_missing")
            staged = self.storage.stage_upload(BytesIO(content), name)
            media_id = str(uuid.uuid5(uuid.UUID(job_id), "output:" + str(index)))
            result = self._write("register_media", project_id, {"id": media_id, "name": name,
                "staged_upload": staged["staged_upload"], "rights": "unknown",
                "source": {"kind": "generation", "source_key": job_id + ":" + str(index),
                    "content": {"job_id": job_id, "request_sha256": job["request_sha256"], "provider": job["provider_id"],
                                "model_version": job["model_version"], "original_uri": original}}}, "output:" + job_id + ":" + str(index))
            registered.append({"media_id": result["id"], "asset_type": output.modality, "original_uri": original})
        return self._write("update_generation_job", project_id, {"job_id": job_id, "status": "succeeded",
            "outputs": registered, "raw_response": raw, "latency_ms": latency_ms,
            "recovery_evidence": {"source": "provider_response_and_verified_storage"}}, "finalize:" + job_id)


def tempfile_for_download(storage, suffix):
    import contextlib
    import tempfile
    @contextlib.contextmanager
    def work():
        with tempfile.TemporaryDirectory(prefix="result-", dir=storage.staging) as directory:
            yield Path(directory) / ("result" + suffix)
    return work()


