"""Application-owned generation consumer; HTTP only reads or controls lifecycle.

One call at a time per runtime and conservative project/provider DB leases bound
parallelism across processes. Persisted queue, next-attempt times and receipts
survive restarts; this module owns no separate business queue or budget.
"""
import re
import threading
import time

from vsc.production.resource_worker import ResourceWorker


class GenerationRuntime:
    def __init__(self, service, adapter_factory=None, *, download=None, worker_id=None,
                 project_id=None, interval_seconds=1, poll_seconds=5,
                 retry_seconds=5, max_retry_seconds=300, lease_seconds=300,
                 workers=1, project_concurrency=1, provider_concurrency=1):
        if not 0.01 <= interval_seconds <= 60:
            raise ValueError("运行间隔需要0.01..60秒")
        if not 0 <= poll_seconds <= 3600 or not 0 <= retry_seconds <= max_retry_seconds <= 3600:
            raise ValueError("轮询与退避间隔需要0..3600秒")
        if any(type(value) is not int or not 1 <= value <= 8
               for value in (workers, project_concurrency, provider_concurrency)):
            raise ValueError("worker与项目/供应商并发上限需要1..8")
        if adapter_factory is None:
            from vsc.adapters.providers.worker_factory import worker_adapter_factory
            adapter_factory = worker_adapter_factory
        if download is None:
            from vsc.adapters.storage.transfer import download_https
            download = download_https
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._threads = []
        self._state = "stopped"
        self._last_error = None
        self._completed = self._failed = 0
        self._last_cycle_at = None
        self._last_batch_advance = 0
        self.interval_seconds = interval_seconds
        self.project_id = project_id
        self.project_concurrency, self.provider_concurrency = project_concurrency, provider_concurrency
        self._workers = [ResourceWorker(service, adapter_factory,
            worker_id=(worker_id + ":" + str(index) if worker_id and index else worker_id),
            download=download, lease_seconds=lease_seconds, poll_seconds=poll_seconds,
            retry_seconds=retry_seconds, max_retry_seconds=max_retry_seconds,
            serialize=True, managed_only=True, project_concurrency=project_concurrency,
            provider_concurrency=provider_concurrency,
            submit_allowed=lambda: not (self._pause.is_set() or self._stop.is_set())) for index in range(workers)]
        self.worker = self._workers[0]

    def start(self):
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return self
            self._stop.clear()
            self._state = "starting"
            self._threads = [threading.Thread(target=self._run, args=(worker,),
                name="vsc-generation-" + str(index), daemon=True) for index, worker in enumerate(self._workers)]
            self._thread = self._threads[0]
            for thread in self._threads:
                thread.start()
        return self

    def wake(self):
        self._wake.set()

    def stop_new_submissions(self):
        """Keep polling and storing existing remote tasks; never calls cancel."""
        self._pause.set()
        self.wake()
        return self.health()

    def resume_submissions(self):
        self._pause.clear()
        self.wake()
        return self.health()

    def stop(self, timeout=5):
        """Stop scheduling, finish the active call within its provider timeout."""
        self._stop.set()
        self.wake()
        until = time.monotonic() + max(0, min(timeout, 60))
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0, until - time.monotonic()))
        return self.health()

    def health(self):
        alive = any(thread.is_alive() for thread in self._threads)
        active_jobs = [worker._active for worker in self._workers if worker._active]
        active = active_jobs[0] if active_jobs else None
        with self._lock:
            status = ("stopping" if self._stop.is_set() else
                      "tracking" if self._pause.is_set() else self._state) if alive else "stopped"
            return {"available": alive, "status": status, "worker_id": self.worker.worker_id,
                "accepting_submissions": alive and not (self._pause.is_set() or self._stop.is_set()),
                "remote_cancelled": False, "active_job_id": active["id"] if active else None,
                "active_job_ids": [job["id"] for job in active_jobs],
                "active_project_id": active["project_id"] if active else None,
                "last_cycle_at": self._last_cycle_at, "last_heartbeat_at": self.worker.last_heartbeat_at,
                "completed_steps": self._completed, "failed_steps": self._failed,
                "error_code": self._last_error, "scope": "postgres-production-v2",
                "concurrency": {"workers": len(self._workers), "per_project": self.project_concurrency,
                                "per_provider": self.provider_concurrency}}

    def _run(self, worker):
        poll_first = True
        try:
            while not self._stop.is_set():
                worked = False
                if worker is self.worker and not self._pause.is_set() and time.monotonic() - self._last_batch_advance >= 2:
                    # Rebuild successors from immutable runs and durable jobs;
                    # restarting never loses a dependency or starts a new run.
                    from vsc.production.bounded import advance_batches
                    try:
                        advance_batches(worker.service, self.project_id, worker.worker_id)
                    except Exception:
                        with self._lock:
                            self._last_error = "batch_advance_failed"
                    self._last_batch_advance = time.monotonic()
                modes = (True,) if self._pause.is_set() else (poll_first, not poll_first)
                poll_first = not poll_first
                for poll in modes:
                    if self._stop.is_set() or (not poll and self._pause.is_set()):
                        continue
                    with self._lock:
                        self._state = "running"
                    try:
                        result = worker.run_once(self.project_id, poll=poll)
                        worked = worked or result is not None
                        with self._lock:
                            self._completed += int(result is not None)
                            if result is not None:
                                self._last_error = None
                    except Exception as exc:
                        # A task failure is isolated. Only stable codes reach
                        # health; provider bodies and secrets stay out of logs.
                        code = str(getattr(exc, "code", "worker_error"))
                        if not re.fullmatch(r"[a-zA-Z0-9_]{1,100}", code):
                            code = "worker_error"
                        with self._lock:
                            self._last_error = code
                            self._failed += 1
                    finally:
                        with self._lock:
                            self._last_cycle_at = time.time()
                with self._lock:
                    self._state = "degraded" if self._last_error else "idle"
                # Even a nonempty queue is paced; no busy polling on failures.
                self._wake.wait(self.interval_seconds if not worked else min(self.interval_seconds, .1))
                self._wake.clear()
        finally:
            with self._lock:
                self._state = "stopped"
