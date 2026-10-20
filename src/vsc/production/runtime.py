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
                 retry_seconds=5, max_retry_seconds=300, lease_seconds=300):
        if not 0.01 <= interval_seconds <= 60:
            raise ValueError("运行间隔需要0.01..60秒")
        if not 0 <= poll_seconds <= 3600 or not 0 <= retry_seconds <= max_retry_seconds <= 3600:
            raise ValueError("轮询与退避间隔需要0..3600秒")
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
        self._state = "stopped"
        self._last_error = None
        self._completed = self._failed = 0
        self._last_cycle_at = None
        self.interval_seconds = interval_seconds
        self.project_id = project_id
        self.worker = ResourceWorker(service, adapter_factory, worker_id=worker_id,
            download=download, lease_seconds=lease_seconds, poll_seconds=poll_seconds,
            retry_seconds=retry_seconds, max_retry_seconds=max_retry_seconds,
            serialize=True, managed_only=True,
            submit_allowed=lambda: not (self._pause.is_set() or self._stop.is_set()))

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self
            self._stop.clear()
            self._state = "starting"
            self._thread = threading.Thread(target=self._run, name="vsc-generation", daemon=True)
            self._thread.start()
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
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0, min(timeout, 60)))
        return self.health()

    def health(self):
        alive = bool(self._thread and self._thread.is_alive())
        active = self.worker._active
        with self._lock:
            status = ("stopping" if self._stop.is_set() else
                      "tracking" if self._pause.is_set() else self._state) if alive else "stopped"
            return {"available": alive, "status": status, "worker_id": self.worker.worker_id,
                "accepting_submissions": alive and not (self._pause.is_set() or self._stop.is_set()),
                "remote_cancelled": False, "active_job_id": active["id"] if active else None,
                "active_project_id": active["project_id"] if active else None,
                "last_cycle_at": self._last_cycle_at, "last_heartbeat_at": self.worker.last_heartbeat_at,
                "completed_steps": self._completed, "failed_steps": self._failed,
                "error_code": self._last_error, "scope": "postgres-production-v2",
                "concurrency": {"per_project": 1, "per_provider": 1}}

    def _run(self):
        poll_first = True
        try:
            while not self._stop.is_set():
                worked = False
                modes = (True,) if self._pause.is_set() else (poll_first, not poll_first)
                poll_first = not poll_first
                for poll in modes:
                    if self._stop.is_set() or (not poll and self._pause.is_set()):
                        continue
                    with self._lock:
                        self._state = "running"
                    try:
                        result = self.worker.run_once(self.project_id, poll=poll)
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
