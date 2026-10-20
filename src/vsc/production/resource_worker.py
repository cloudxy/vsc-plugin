"""Durable PostgreSQL generation consumer; transports are injectable.

Only explicit worker invocation can contact a provider. Unknown submissions are
never re-submitted. Result bytes are committed before the job can succeed.
"""
from dataclasses import fields
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
import threading
from urllib.parse import urlsplit, urlunsplit
import uuid

from vsc.assets.resource_service import Conflict, NotFound, ResourceError
from vsc.production.providers import AudioRequest, ImageRequest, JobHandle, VideoRequest

REQUEST_TYPES = {"image": ImageRequest, "video": VideoRequest, "audio": AudioRequest}


class ResourceWorker:
    def __init__(self, service, adapter_factory, worker_id=None, download=None, *,
                 lease_seconds=300, poll_seconds=0, retry_seconds=0, max_retry_seconds=300,
                 serialize=False, submit_allowed=None, managed_only=False):
        if service.storage is None:
            raise ResourceError("生成消费者需要受控存储", "storage_required")
        self.service, self.storage = service, service.storage
        self.adapter_factory = adapter_factory
        self.worker_id = worker_id or "resource-worker-" + uuid.uuid4().hex
        self.download = download
        self.lease_seconds, self.poll_seconds = lease_seconds, poll_seconds
        self.retry_seconds, self.serialize = retry_seconds, serialize
        self.max_retry_seconds, self.submit_allowed = max_retry_seconds, submit_allowed
        self.managed_only = managed_only
        self._active = None
        self._lease_error = None
        self.last_job = None
        self.last_heartbeat_at = None

    def _write(self, action, project_id, payload, key):
        if self._active:
            self._check_lease()
            if action in {"mark_submission_started", "record_submission_result", "update_generation_job"}:
                payload = dict(payload, worker_id=self.worker_id, claim_epoch=self._active["claim_epoch"])
                if action == "update_generation_job":
                    payload["keep_lease"] = True
                key += ":lease:" + str(self._active["claim_epoch"])
        for attempt in range(3):
            revision = self.service.get_project(project_id)["revision"]
            try:
                return getattr(self.service, action)(project_id, payload, expected_revision=revision,
                    idempotency_key=key, actor=self.worker_id)
            except Conflict as exc:
                if exc.code != "revision_conflict" or attempt == 2:
                    raise

    def _renew(self, job=None):
        job = job or self._active
        result = self.service.renew_generation_job_lease(job["project_id"], job["id"],
            self.worker_id, job["claim_epoch"], lease_seconds=self.lease_seconds)
        self.last_heartbeat_at = time.time()
        return result

    def _check_lease(self):
        if self._lease_error:
            raise Conflict("worker心跳失败，停止当前轮次写入", "worker_lease_conflict")
        self._renew()

    @contextmanager
    def _leased(self, job):
        """Keep blocking provider/storage calls leased; loss fences all writes."""
        self._active, self.last_job, self._lease_error = job, job, None
        done = threading.Event()
        def heartbeat():
            while not done.wait(max(.1, self.lease_seconds / 3)):
                try:
                    self._renew(job)
                except Exception as exc:
                    if self._active is job:
                        self._lease_error = exc
                    return
        thread = threading.Thread(target=heartbeat, name="generation-lease", daemon=True)
        thread.start()
        error = None
        try:
            yield
        except Exception as exc:
            error = exc
            raise
        finally:
            done.set()
            thread.join(timeout=2)
            try:
                prior_errors = sum(event["event_type"] == "worker_retry" for event in job.get("events", []))
                retry = min(self.max_retry_seconds, self.retry_seconds * (2 ** min(prior_errors, 10)))
                self.service.release_generation_job_lease(job["project_id"], job["id"],
                    self.worker_id, job["claim_epoch"],
                    retry_seconds=retry if error else self.poll_seconds,
                    error_code=getattr(error, "code", "worker_error") if error else None)
            except Exception:
                # Terminal writes release atomically. A lost owner must never
                # clear a newer lease, including when shutdown interrupts I/O.
                pass
            self._active = None

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
            getattr(request, "last_frame_media_id", None), getattr(request, "voice_media_id", None),
            getattr(request, "source_media_id", None)) if value)
        if used - fixed:
            raise ResourceError("请求引用不属于任务固定输入", "unfixed_reference")
        if getattr(request, "operation", None):
            source = next((item for item in job["input_media"] if item["media_id"] == request.source_media_id
                           and item["role"] == "operation_source"), None)
            if source is None or source["blob_sha256"] != request.source_sha256:
                raise ResourceError("加工源SHA不属于任务固定输入", "unfixed_reference")
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
        self.last_job = None
        job = self.service.claim_generation_job(self.worker_id, project_id=project_id, statuses=statuses,
            lease_seconds=self.lease_seconds, serialize=self.serialize, managed_only=self.managed_only,
            resume_storage=poll)
        if not job:
            return None
        with self._leased(job):
            return self._execute(job, poll)

    def _execute(self, job, poll):
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
            if self.submit_allowed is not None and not self.submit_allowed():
                raise ResourceError("已停止新提交；已提交任务继续追踪", "submissions_paused")
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
            if any((event.get("evidence") or {}).get("source") == "provider_success_awaiting_storage" for event in job.get("events", [])):
                return self._finalize(job, adapter=adapter, raw=handle.raw)
            status = adapter.poll(handle)
        if status is None:
            return self.service.get_generation_job(job["project_id"], job["id"])
        if status.status == "succeeded":
            # Preserve the terminal response before downloading. A failed transfer
            # can be resumed from this evidence without another provider GET.
            self._write("update_generation_job", job["project_id"], {"job_id": job["id"], "worker_id": self.worker_id,
                "status": "running" if handle.external_task_id else "submission_unknown",
                "external_task_id": handle.external_task_id, "raw_response": status.raw,
                "recovery_evidence": {"source": "provider_success_awaiting_storage"}},
                "terminal-response:" + job["id"])
            return self._finalize(job, adapter=adapter, raw=status.raw,
                                 latency_ms=round((time.monotonic() - started) * 1000))
        return self._write("update_generation_job", job["project_id"], {"job_id": job["id"], "worker_id": self.worker_id,
            "status": status.status, "external_task_id": handle.external_task_id, "raw_response": status.raw,
            "recovery_evidence": {"source": "provider_response", "error_code": status.error_code}},
            "status:" + job["id"] + ":" + uuid.uuid4().hex)

    def finalize(self, project_id, job_id, adapter=None, raw=None, latency_ms=None):
        """Explicit storage recovery claims a fresh lease; it never submits."""
        job = self.service.get_generation_job(project_id, job_id)
        if job["status"] == "succeeded":
            return job
        claimed = self.service.claim_generation_job(self.worker_id, project_id=project_id, job_id=job_id,
            statuses=("submitted", "running", "submission_unknown"), recovery=True,
            lease_seconds=self.lease_seconds, serialize=self.serialize)
        if not claimed:
            raise Conflict("任务没有可恢复响应或仍被其他worker持有", "worker_lease_conflict")
        with self._leased(claimed):
            if raw is not None and raw != claimed.get("raw_response"):
                raise ResourceError("恢复转存必须使用已持久化供应商响应", "response_changed")
            return self._finalize(claimed, adapter=adapter, raw=raw, latency_ms=latency_ms)

    def _finalize(self, job, adapter=None, raw=None, latency_ms=None):
        project_id, job_id = job["project_id"], job["id"]
        self._check_lease()
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
            media_id = str(uuid.uuid5(uuid.UUID(job_id), "output:" + str(index)))
            recovered = self._registered_output(job, media_id, output.modality)
            if recovered:
                registered.append(recovered)
                continue
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
            result = self._write("register_media", project_id, {"id": media_id, "name": name,
                "staged_upload": staged["staged_upload"], "rights": "unknown",
                "source": {"kind": "generation", "source_key": job_id + ":" + str(index),
                    "content": {"job_id": job_id, "request_sha256": job["request_sha256"], "provider": job["provider_id"],
                                "model_version": job["model_version"], "original_uri": original}}}, "output:" + job_id + ":" + str(index))
            registered.append({"media_id": result["id"], "asset_type": output.modality, "original_uri": original})
        return self._write("update_generation_job", project_id, {"job_id": job_id, "status": "succeeded",
            "outputs": registered, "raw_response": raw, "latency_ms": latency_ms,
            "recovery_evidence": {"source": "provider_response_and_verified_storage"}}, "finalize:" + job_id)

    def _registered_output(self, job, media_id, modality):
        """Recover the registration/commit gap without a new upload token."""
        try:
            media = self.service.get_media(job["project_id"], media_id)
        except NotFound:
            return None
        if media["modality"] != modality:
            raise ResourceError("已登记输出与固定模态不符", "output_changed")
        evidence = None
        for source in media.get("sources", []):
            if source.get("kind") != "generation":
                continue
            value = self.service.get_source_version(job["project_id"], source["source_id"]).get("content")
            try:
                candidate = json.loads(value)
            except (ValueError, TypeError):
                continue
            if candidate.get("job_id") == job["id"] and candidate.get("request_sha256") == job["request_sha256"]:
                evidence = candidate
                break
        if evidence is None:
            raise ResourceError("已登记输出没有匹配的任务来源事实", "output_changed")
        for location in media.get("locations", []):
            if location["storage"] == "local" and location["available"]:
                self.storage.verify(location["object_key"], media["sha256"])
                return {"media_id": media_id, "asset_type": modality, "original_uri": evidence.get("original_uri")}
        raise ResourceError("已登记输出字节不可读取", "media_unavailable")


def tempfile_for_download(storage, suffix):
    import contextlib
    import tempfile
    @contextlib.contextmanager
    def work():
        with tempfile.TemporaryDirectory(prefix="result-", dir=storage.staging) as directory:
            yield Path(directory) / ("result" + suffix)
    return work()


