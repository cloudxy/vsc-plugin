"""Real isolated PostgreSQL lifecycle, leases and recovery; no paid transports."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import support.paths  # noqa: F401
from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture, png_bytes
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.configuration import get_config
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
from vsc.production.resource_worker import ResourceWorker
from vsc.production.runtime import GenerationRuntime

TEST_URL = get_config("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


class Provider:
    def __init__(self, asynchronous=False, unknown=False, wait=None):
        self.asynchronous, self.unknown, self.wait = asynchronous, unknown, wait
        self.submits = self.polls = 0
        self.entered = threading.Event()

    def submit(self, request):
        self.submits += 1
        self.entered.set()
        if self.wait:
            self.wait.wait(10)
        if self.unknown:
            raise TimeoutError("synthetic unknown receipt")
        return JobHandle("runtime-fixture", "image", uuid.uuid4().hex if self.asynchronous else None,
                         {"synthetic": "persisted output"})

    def poll(self, handle):
        self.polls += 1
        return JobStatus("succeeded", raw={"synthetic": "persisted output"})

    def parse_result(self, raw):
        return [GeneratedAsset("image", inline_bytes=png_bytes())]


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires configured test PostgreSQL and dependencies")
class GenerationRuntimeTests(unittest.TestCase):
    def setUp(self):
        from vsc.adapters.persistence.postgres.store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        self.database = isolated_postgres(TEST_URL)
        self.engine = self.database.__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(self.temp.name))
        self.profile = {"profile_id": "vsc.synthetic", "version": "1", "stages": [],
                        "contract_policy": "production-v2"}
        self.fixture = ResourceFixture(self.service, self.profile)
        self.service.register_provider({"id": "runtime-fixture", "base_url": "https://example.invalid",
            "auth_ref": "SYNTHETIC_NOT_CONFIGURED"}, actor="fixture-human")
        self.model = self.service.register_model({"provider_id": "runtime-fixture", "model_key": "image",
            "model_version": "1", "modality": "image", "capabilities": {"purposes": ["keyframe"]}},
            actor="fixture-human")["id"]

    def job(self, fixture=None):
        from vsc.adapters.persistence.postgres.budget_store import native_units, operation_key
        fixture = fixture or self.fixture
        if not self.service.budget_status(fixture.p)["limits"]:
            fixture.write("configure_budget", {"limits": {"remote_jobs": 20, "images": 20},
                                               "reason": "bounded synthetic transport only"})
        context = self.service.compile_shot_context(fixture.p, fixture.objects["shot"], "keyframe")
        request = {"shot_id": fixture.objects["shot"], "purpose": "keyframe", "modality": "image",
                   "prompt": "synthetic", "params": {}, "reference_media_ids": []}
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        run = fixture.artifact("run-" + uuid.uuid4().hex, "production-run", {"approved_inputs": pins,
            "series_batch": {"jobs": [{"candidate_no": 0, "request": request}]},
            "operations": {operation_key(request, 0): native_units(request)}}, [row["id"] for row in pins])
        return fixture.write("create_generation_job", {"shot_id": fixture.objects["shot"], "purpose": "keyframe",
            "modality": "image", "model_id": self.model, "run_version_id": run, "candidate_no": 0,
            "request_payload": request, "context_sha256": context["sha256"]})

    def runtime(self, adapter, **kwargs):
        runtime = GenerationRuntime(self.service, adapter, interval_seconds=.02, poll_seconds=.02,
            retry_seconds=.1, max_retry_seconds=.2, **kwargs)
        self.addCleanup(runtime.stop, 5)
        return runtime

    def saved(self, job):
        return self.service.get_generation_job(job["project_id"], job["id"])

    def await_(self, predicate, seconds=8):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            result = predicate()
            if result:
                return result
            time.sleep(.02)
        self.fail("consumer did not reach expected durable state")

    def expire(self, job):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.begin() as conn:
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id == job["project_id"],
                S.generation_jobs.c.id == job["id"]).values(claim_until=datetime.now(timezone.utc) - timedelta(seconds=1)))

    def raw_write(self, action, job, **payload):
        return getattr(self.service, action)(job["project_id"], dict(job_id=job["id"], **payload),
            expected_revision=self.service.get_project(job["project_id"])["revision"],
            idempotency_key=uuid.uuid4().hex, actor="synthetic-worker")

    def test_persistent_queue_background_result_and_restart_do_not_repost(self):
        job, provider = self.job(), Provider(asynchronous=True)
        runtime = self.runtime(lambda *_: provider).start()
        self.await_(lambda: self.saved(job)["status"] == "succeeded")
        result = self.saved(job)
        media = self.service.get_media(job["project_id"], result["outputs"][0]["media_id"])
        self.assertEqual(media["modality"], "image")
        self.assertTrue(any(location["available"] for location in media["locations"]))
        self.assertEqual(self.service.get_media_usage(job["project_id"], media["id"])["current_bindings"], [])
        self.assertFalse(runtime.stop()["available"])
        restarted = self.runtime(lambda *_: provider).start()
        self.await_(lambda: restarted.health()["last_cycle_at"])
        restarted.stop()
        self.assertEqual(provider.submits, 1)
        self.assertEqual(provider.polls, 1)
        self.assertEqual(result["attempt"], 1)

    def test_unknown_receipt_restart_never_submits_again(self):
        job, provider = self.job(), Provider(unknown=True)
        runtime = self.runtime(lambda *_: provider).start()
        self.await_(lambda: runtime.health()["failed_steps"])
        runtime.stop()
        self.assertEqual(self.saved(job)["status"], "submission_unknown")
        restarted = self.runtime(lambda *_: provider).start()
        self.await_(lambda: restarted.health()["last_cycle_at"])
        restarted.stop()
        self.assertEqual(provider.submits, 1)
        self.assertIsNone(ResourceWorker(self.service, lambda *_: provider).run_once(job["project_id"]))

    def test_same_owner_new_epoch_rejects_stale_and_missing_fence(self):
        job = self.job()
        first = self.service.claim_generation_job("same-worker", project_id=job["project_id"])
        self.expire(job)
        second = self.service.claim_generation_job("same-worker", project_id=job["project_id"])
        self.assertEqual(second["claim_epoch"], first["claim_epoch"] + 1)
        for epoch in (None, first["claim_epoch"]):
            payload = {"worker_id": "same-worker"}
            if epoch is not None:
                payload["claim_epoch"] = epoch
            with self.assertRaises(Conflict):
                self.raw_write("mark_submission_started", job, **payload)
        with self.assertRaises(Conflict):
            self.service.renew_generation_job_lease(job["project_id"], job["id"], "same-worker",
                                                   first["claim_epoch"])
        with self.assertRaises(Conflict):
            self.raw_write("update_generation_job", job, status="failed",
                           recovery_evidence={"pretend_human": True})
        self.assertEqual(self.saved(job)["status"], "created")

    def test_heartbeat_covers_blocking_submit_and_stop_does_not_cancel(self):
        release, provider = threading.Event(), Provider()
        provider.wait = release
        self.addCleanup(release.set)
        job = self.job()
        runtime = self.runtime(lambda *_: provider, lease_seconds=1).start()
        self.assertTrue(provider.entered.wait(5))
        time.sleep(1.2)
        current = self.saved(job)
        self.assertGreater(datetime.fromisoformat(current["claim_until"]), datetime.now(timezone.utc))
        stopped = runtime.stop(timeout=.01)
        self.assertEqual(stopped["status"], "stopping")
        self.assertFalse(stopped["remote_cancelled"])
        release.set()
        self.await_(lambda: not runtime.health()["available"])
        self.assertEqual(self.saved(job)["status"], "succeeded")
        self.assertEqual(provider.submits, 1)

    def test_pause_new_submits_still_tracks_previous_task(self):
        existing, provider = self.job(), Provider(asynchronous=True)
        ResourceWorker(self.service, lambda *_: provider).run_once(self.fixture.p)
        waiting = self.job()
        runtime = self.runtime(lambda *_: provider)
        runtime.stop_new_submissions()
        runtime.start()
        self.await_(lambda: self.saved(existing)["status"] == "succeeded")
        self.assertEqual(self.saved(waiting)["status"], "created")
        self.assertEqual(runtime.health()["status"], "tracking")
        self.assertEqual(provider.submits, 1)
        runtime.resume_submissions()
        self.await_(lambda: self.saved(waiting)["status"] == "succeeded")
        self.assertEqual(provider.submits, 2)

    def test_project_fairness_and_database_provider_limit(self):
        first, other = self.job(), ResourceFixture(self.service, self.profile)
        second = self.job(other)
        barrier = threading.Barrier(2)
        def claim(owner):
            barrier.wait(timeout=5)
            return self.service.claim_generation_job(owner, serialize=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("first-worker", "second-worker")))
        self.assertEqual(sum(row is not None for row in results), 1)
        one = next(row for row in results if row)
        self.service.release_generation_job_lease(one["project_id"], one["id"], one["claim_owner"], one["claim_epoch"])
        two = self.service.claim_generation_job("second-worker", serialize=True)
        self.assertNotEqual(one["project_id"], two["project_id"])
        self.assertEqual({first["id"], second["id"]}, {one["id"], two["id"]})

    def test_bad_job_isolated_and_backoff_persists_while_next_job_completes(self):
        bad, good, provider = self.job(), self.job(), Provider()
        def factory(job, storage):
            if job["id"] == bad["id"]:
                raise ResourceError("synthetic local failure", "adapter_unavailable")
            return provider
        runtime = self.runtime(factory).start()
        self.await_(lambda: self.saved(good)["status"] == "succeeded")
        runtime.stop()
        blocked = self.saved(bad)
        self.assertEqual(blocked["status"], "created")
        self.assertIsNotNone(blocked["next_attempt_at"])
        retries = [event for event in blocked["events"] if event["event_type"] == "worker_retry"]
        self.assertTrue(retries)
        self.assertTrue(all(.1 <= event["evidence"]["retry_seconds"] <= .2 for event in retries))
        self.assertEqual(provider.submits, 1)

    def test_sync_success_storage_interruption_recovers_after_restart_without_post(self):
        job, provider = self.job(), Provider()
        worker = ResourceWorker(self.service, lambda *_: provider)
        with patch.object(self.service.storage, "stage_upload", side_effect=OSError("synthetic disk full")):
            with self.assertRaises(OSError):
                worker.run_once(self.fixture.p)
        pending = self.saved(job)
        self.assertEqual(pending["status"], "submission_unknown")
        self.assertTrue(any((row["evidence"] or {}).get("source") == "provider_success_awaiting_storage"
                            for row in pending["events"]))
        with self.assertRaises(ResourceError) as changed:
            worker.finalize(self.fixture.p, job["id"], raw={"synthetic": "unpersisted replacement"})
        self.assertEqual(changed.exception.code, "response_changed")
        runtime = self.runtime(lambda *_: provider).start()
        self.await_(lambda: self.saved(job)["status"] == "succeeded")
        runtime.stop()
        self.assertEqual((provider.submits, provider.polls), (1, 1))

    def test_expired_worker_cannot_publish_or_release_reclaimed_output(self):
        job, provider = self.job(), Provider()
        first = self.service.claim_generation_job("stable-worker", project_id=self.fixture.p)
        self.raw_write("mark_submission_started", job, worker_id="stable-worker", claim_epoch=first["claim_epoch"])
        self.raw_write("record_submission_result", job, worker_id="stable-worker", claim_epoch=first["claim_epoch"],
            external_task_id="synthetic-task", raw_response={"synthetic": "response"}, provider_status="submitted")
        self.expire(job)
        current = self.service.claim_generation_job("stable-worker", project_id=self.fixture.p,
                                                    statuses=("submitted", "running"))
        worker = ResourceWorker(self.service, lambda *_: provider, worker_id="stable-worker")
        with self.assertRaises(Conflict):
            with worker._leased(first):
                worker._finalize(first, adapter=provider, raw={"synthetic": "response"})
        saved = self.saved(job)
        self.assertEqual(saved["claim_epoch"], current["claim_epoch"])
        self.assertEqual(saved["claim_owner"], "stable-worker")
        self.assertEqual(saved["outputs"], [])
        with self.assertRaises(Conflict):
            self.raw_write("update_generation_job", job, status="failed", worker_id="stable-worker",
                           claim_epoch=first["claim_epoch"])

    def test_explicit_human_recovery_requires_proof_and_expired_lease(self):
        from vsc.assets.generation_recovery import verified_generation_recovery
        job = self.job()
        lease = self.service.claim_generation_job("unknown-worker", project_id=job["project_id"])
        self.raw_write("mark_submission_started", job, worker_id="unknown-worker", claim_epoch=lease["claim_epoch"])
        payload = {"job_id": job["id"], "status": "failed", "reason": "synthetic provider account reconciliation",
                   "recovery_evidence": {"provider_receipt": "not submitted"}, "actual_units": {"remote_jobs": 0}}
        def recover(proof=None):
            return self.service.recover_generation_job(job["project_id"], payload, human_decision=proof,
                actor="fixture-human", expected_revision=self.service.get_project(job["project_id"])["revision"],
                idempotency_key=uuid.uuid4().hex)
        with self.assertRaises(ResourceError):
            recover()
        with self.assertRaises(Conflict):
            recover(verified_generation_recovery("fixture-human"))
        self.expire(job)
        result = recover(verified_generation_recovery("fixture-human"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.saved(job)["attempt"], 1)

    def test_background_does_not_start_old_profile_and_revoked_run_is_blocked(self):
        legacy = ResourceFixture(self.service)
        old_job = legacy.job("image", "keyframe", self.model)
        job, provider = self.job(), Provider()
        self.fixture.write("decide_artifact", {"artifact_id": self.saved(job)["run_version_id"],
            "outcome": "revoke", "reason": "synthetic human veto before submission"})
        runtime = self.runtime(lambda *_: provider).start()
        self.await_(lambda: runtime.health()["failed_steps"])
        runtime.stop()
        self.assertEqual(runtime.health()["error_code"], "run_unapproved")
        self.assertEqual(self.saved(old_job)["status"], "created")
        self.assertEqual(self.saved(job)["status"], "created")
        self.assertEqual(provider.submits, 0)
        self.assertEqual(self.service.budget_status(self.fixture.p)["used"], {})


if __name__ == "__main__":
    unittest.main()
