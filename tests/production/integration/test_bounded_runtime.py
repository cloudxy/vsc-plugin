"""Real PostgreSQL bounded execution; providers return owned synthetic bytes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import tempfile
import threading
import time
import unittest
import uuid

import support.paths  # noqa: F401
from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture, png_bytes
from vsc.configuration import get_config
from vsc.production.bounded import execute_batch, preview_batch
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
from vsc.production.resource_worker import ResourceWorker
from vsc.production.runtime import GenerationRuntime

TEST_URL = get_config("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


class Provider:
    def __init__(self, barrier=None, unknown=False):
        self.submits = 0
        self.barrier, self.unknown = barrier, unknown

    def preflight(self, request):
        if self.barrier:
            self.barrier.wait(10)

    def submit(self, request):
        self.submits += 1
        if self.unknown:
            raise TimeoutError("synthetic unknown")
        return JobHandle("bounded-fixture", "image", None, {"output": "synthetic"})

    def poll(self, handle):
        return JobStatus("succeeded", raw=handle.raw)

    def parse_result(self, raw):
        return [GeneratedAsset("image", inline_bytes=png_bytes())]


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires configured test PostgreSQL and dependencies")
class BoundedRuntimeTests(unittest.TestCase):
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
        self.fixture = ResourceFixture(self.service, {"profile_id": "vsc.synthetic", "version": "1", "stages": [],
                                                    "contract_policy": "production-v2"})
        self.p = self.fixture.p
        self.shots = [self.fixture.objects["shot"]]
        for index in range(2):
            self.shots.append(self.fixture.write("create_object", {"kind": "shot", "parent_id": self.fixture.objects["sequence"],
                "display_code": "SH" + str(index), "ordinal": index + 1})["id"])
        self.fixture.artifact("scene-state", "scene-state", {"state_versions": [
            {"scene_id": self.fixture.objects["scene"], "entities": []}]})
        self.service.register_provider({"id": "bounded-fixture", "base_url": "https://example.invalid",
            "auth_ref": "SYNTHETIC_NOT_CONFIGURED", "rate_limit": {"max_concurrency": 2}}, actor="fixture-human")
        self.model = self.service.register_model({"provider_id": "bounded-fixture", "model_key": "image", "model_version": "1",
            "modality": "image", "capabilities": {"purposes": ["keyframe"], "reference_media": True}}, actor="fixture-human")["id"]
        self.fixture.write("configure_budget", {"limits": {"remote_jobs": 10, "images": 10}, "reason": "synthetic test only"})

    def policy(self, maximum=2, expired=False):
        now = datetime.now(timezone.utc)
        return {"version": "bounded-v1", "first_draft_due_at": (now + timedelta(minutes=-2 if expired else 10)).isoformat(),
            "stop_submitting_at": (now + timedelta(minutes=-1 if expired else 20)).isoformat(),
            "max_attempts_per_purpose": maximum, "max_repair_rounds": 1}

    def task(self, index=0, depends=None):
        return {"task_key": "task-" + str(index), "candidate_no": 0, "model_id": self.model,
            "depends_on": depends or [], "request": {"shot_id": self.shots[index], "purpose": "keyframe",
            "modality": "image", "prompt": "synthetic", "reference_media_ids": [], "params": {}}}

    def make_run(self, tasks, policy=None):
        from vsc.adapters.persistence.postgres.budget_store import native_units, operation_key
        context = self.service.compile_shot_context(self.p, self.shots[0], "keyframe")
        self.assertTrue(context["ready"], context["gaps"])
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        document = {"approved_inputs": pins, "execution_policy": policy or self.policy(), "series_batch": {"jobs": tasks},
            "operations": {operation_key(row["request"], row["candidate_no"]): native_units(row["request"]) for row in tasks}}
        return self.fixture.artifact("run-" + uuid.uuid4().hex, "production-run", document, [row["id"] for row in pins])

    def direct_job(self, run_id):
        context = self.service.compile_shot_context(self.p, self.shots[0], "keyframe")
        return self.fixture.write("create_generation_job", {"shot_id": self.shots[0], "purpose": "keyframe", "modality": "image",
            "model_id": self.model, "run_version_id": run_id, "candidate_no": 0,
            "context_sha256": context["sha256"], "request_payload": self.task()["request"]})

    def test_concurrent_runs_share_atomic_attempt_limit(self):
        policy = self.policy(maximum=1)
        jobs = [self.direct_job(self.make_run([self.task()], policy)) for _ in range(2)]
        provider = Provider(barrier=threading.Barrier(2))
        workers = [ResourceWorker(self.service, lambda *_: provider, worker_id="bounded-" + str(index)) for index in range(2)]
        def consume(worker):
            # Project locks deliberately skip rather than wait while another
            # claimant owns the transaction. Retry that empty queue observation.
            for _ in range(50):
                result = worker.run_once(self.p)
                if result is not None:
                    return result
                time.sleep(.02)
            self.fail("worker never claimed an available job")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, workers))
        self.assertEqual(provider.submits, 1)
        self.assertEqual({row["status"] for row in results}, {"succeeded", "cancelled"})
        stored = [self.service.get_generation_job(self.p, job["id"]) for job in jobs]
        self.assertEqual(sum(row["attempt"] for row in stored), 1)

    def test_unknown_submit_uses_attempt_and_never_reposts_after_restart(self):
        policy = self.policy(maximum=1)
        first = self.direct_job(self.make_run([self.task()], policy))
        provider = Provider(unknown=True)
        with self.assertRaises(TimeoutError):
            ResourceWorker(self.service, lambda *_: provider).run_once(self.p)
        self.assertEqual(self.service.get_generation_job(self.p, first["id"])["status"], "submission_unknown")
        self.direct_job(self.make_run([self.task()], dict(policy, max_attempts_per_purpose=3)))
        result = ResourceWorker(self.service, lambda *_: provider).run_once(self.p)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(provider.submits, 1)
        self.assertIsNone(ResourceWorker(self.service, lambda *_: provider).run_once(self.p))
        self.assertEqual(self.service.budget_status(self.p)["used"]["remote_jobs"], 1)

    def test_deadline_stops_unsubmitted_job_without_touching_provider(self):
        run_id = self.make_run([self.task()], self.policy(expired=True))
        job = self.direct_job(run_id)
        provider = Provider()
        result = ResourceWorker(self.service, lambda *_: provider).run_once(self.p)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(provider.submits, 0)
        detail = self.service.get_generation_job(self.p, job["id"])
        self.assertTrue(any((event.get("evidence") or {}).get("error_code") == "production_deadline_reached" for event in detail["events"]))
        renewed = self.make_run([self.task()], self.policy())
        self.assertEqual(preview_batch(self.service, self.p, {"run_version_id": renewed})["blocked_count"], 1)

    def test_selected_upstream_sha_advances_same_run_after_runtime_restart(self):
        first, later, independent = self.task(), self.task(1, ["task-0"]), self.task(2)
        later["output_inputs"] = [{"task_key": "task-0", "field": "reference_media_ids", "role": "composition"}]
        run_id = self.make_run([first, later, independent])
        started = execute_batch(self.service, self.p, {"run_version_id": run_id}, "fixture-human")
        self.assertEqual(started["created_count"], 2)
        provider = Provider()
        worker = ResourceWorker(self.service, lambda *_: provider)
        worker.run_once(self.p)
        worker.run_once(self.p)
        waiting = preview_batch(self.service, self.p, {"run_version_id": run_id})
        self.assertEqual(waiting["waiting_count"], 1)
        first_job = next(row for row in started["tasks"] if row["task_key"] == "task-0")["job_id"]
        output = self.service.get_generation_job(self.p, first_job)["outputs"][0]["media_id"]
        self.fixture.select_media(output, "composition", self.shots[1])
        runtime = GenerationRuntime(self.service, lambda *_: provider, project_id=self.p, interval_seconds=.02,
                                    poll_seconds=.02, workers=2, project_concurrency=2, provider_concurrency=2)
        self.addCleanup(runtime.stop, 5)
        runtime.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            jobs = self.service.list_generation_jobs(self.p)["items"]
            if len(jobs) == 3 and all(row["status"] == "succeeded" for row in jobs):
                break
            time.sleep(.05)
        runtime.stop()
        jobs = self.service.list_generation_jobs(self.p)["items"]
        self.assertEqual(len(jobs), 3)
        self.assertTrue(all(row["status"] == "succeeded" for row in jobs), jobs)
        child = next(row for row in jobs if row["shot_id"] == self.shots[1])
        detail = self.service.get_generation_job(self.p, child["id"])
        self.assertEqual(detail["request_payload"]["reference_media_ids"], [output])
        self.assertTrue(any(item["media_id"] == output and item["blob_sha256"] == self.service.get_media(self.p, output)["sha256"]
                            for item in detail["input_media"]))
        self.assertEqual(provider.submits, 3)
        self.assertEqual(execute_batch(self.service, self.p, {"run_version_id": run_id}, "fixture-human")["existing_count"], 3)

    def test_explicit_approved_new_batch_renews_window_but_continuation_keeps_cap(self):
        old = self.make_run([self.task()], self.policy(expired=True))
        self.direct_job(old)
        provider = Provider()
        worker = ResourceWorker(self.service, lambda *_: provider)
        self.assertEqual(worker.run_once(self.p)["status"], "cancelled")
        renewed_policy = dict(self.policy(maximum=1), authorization={
            "mode": "new_batch", "reason": "Explicit synthetic second production authorization"})
        renewed = self.make_run([self.task()], renewed_policy)
        self.assertEqual(preview_batch(self.service, self.p, {"run_version_id": renewed})["ready_count"], 1)
        self.direct_job(renewed)
        self.assertEqual(worker.run_once(self.p)["status"], "succeeded")
        original = self.service.get_artifact_version(self.p, renewed)
        continuation = dict(self.policy(maximum=4), authorization={"mode": "continue",
            "run_version_id": renewed, "sha256": original["sha256"]})
        child = self.make_run([self.task()], continuation)
        self.assertEqual(preview_batch(self.service, self.p, {"run_version_id": child})["blocked_count"], 1)
        self.direct_job(child)
        self.assertEqual(worker.run_once(self.p)["status"], "cancelled")
        self.assertEqual(provider.submits, 1)
        self.assertEqual(self.service.budget_status(self.p)["used"]["remote_jobs"], 1)

    def test_continuation_requires_fixed_approved_origin_and_same_target(self):
        from vsc.assets.resource_service import ResourceError
        root_policy = dict(self.policy(), authorization={"mode": "new_batch", "reason": "Synthetic authorization"})
        root = self.make_run([self.task(1)], root_policy)
        original = self.service.get_artifact_version(self.p, root)
        continuation = dict(self.policy(), authorization={"mode": "continue",
            "run_version_id": root, "sha256": original["sha256"]})
        wrong_scope = self.make_run([self.task()], continuation)
        with self.assertRaises(ResourceError) as caught:
            self.direct_job(wrong_scope)
        self.assertEqual(caught.exception.code, "execution_authorization_scope")
        bad_sha = dict(continuation, authorization=dict(continuation["authorization"], sha256="0" * 64))
        with self.assertRaises(ResourceError) as caught:
            self.direct_job(self.make_run([self.task()], bad_sha))
        self.assertEqual(caught.exception.code, "execution_authorization_invalid")
        unapproved = self.fixture.write("create_artifact", {"artifact_type": "production-run",
            "artifact_key": "unapproved-origin", "document": {"execution_policy": root_policy}, "dependency_ids": []})["id"]
        raw = self.service.get_artifact_version(self.p, unapproved)
        not_approved = dict(continuation, authorization={"mode": "continue", "run_version_id": unapproved, "sha256": raw["sha256"]})
        with self.assertRaises(ResourceError) as caught:
            self.direct_job(self.make_run([self.task()], not_approved))
        self.assertEqual(caught.exception.code, "execution_authorization_invalid")


if __name__ == "__main__":
    unittest.main()
