"""PG edit/extend consumers: real media/schema, injected offline Grok transport."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from unittest import mock

from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL"), "requires explicit isolated PostgreSQL URL")
class GrokPGOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(os.environ["VSC_TEST_DATABASE_URL"])
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.providers.xai_grok import credentials
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(self.temp.name))
        self.fixture = ResourceFixture(self.service, {"profile_id": "vsc.operation-fixture", "version": "1",
            "contract_policy": "production-v2", "stages": []})
        self.fixture.write("configure_budget", {"limits": {"remote_jobs": 20, "video_seconds": 100}, "reason": "Offline fixture bounds"})
        self.login = Path(self.temp.name) / "offline-login.json"
        self.login.write_text(json.dumps({"offline": {"user_id": "account-A", "key": "offline-token"}}))
        patch = mock.patch.object(credentials, "LOGIN_FILE", self.login)
        patch.start()
        self.addCleanup(patch.stop)
        from vsc.production.resource_settings import PRESETS, ResourceSettings
        config = {key: value for key, value in next(row for row in PRESETS if row["id"] == "xai-grok-video-operations").items() if key != "label"}
        saved = ResourceSettings(self.service.store).save(dict(config, id=None, enabled=True, model_version="offline-1"), "fixture-human")
        self.model, self.provider = saved["id"], saved["provider_id"]
        self.source = self.media("source", 1.3, "blue")
        self.result_bytes = self.video_bytes("result", 2, "red")
        self.calls = []

    def video_bytes(self, name, duration, color):
        path = Path(self.temp.name) / (name + ".mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=32x32:r=10:d={duration}",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
        return path.read_bytes()

    def media(self, name, duration, color):
        content = self.video_bytes(name, duration, color)
        staged = self.service.storage.stage_upload(BytesIO(content), name + ".mp4")
        identifier = self.fixture.write("register_media", {"name": name + ".mp4", "staged_upload": staged["staged_upload"],
            "source": {"kind": "fixture", "content": "offline owned synthetic video"}, "rights": "unknown"})["id"]
        source = self.service.get_media(self.fixture.p, identifier)["sources"][0]["source_id"]
        self.fixture.write("decide_rights", {"media_id": identifier, "source_id": source, "outcome": "owned", "scope": {"purposes": ["*"]}, "reason": "Synthetic fixture bytes"})
        self.fixture.write("record_media_check", {"media_id": identifier, "checker": "fixture-decoder", "criteria_version": "1", "outcome": "pass"})
        return identifier

    def job(self, operation="edit", source=None, overrides=None, approve_source=True):
        from vsc.adapters.persistence.postgres.budget_store import native_units, operation_key
        from vsc.production.run_authorization import normalize_request
        from vsc.production.video_operations import source_duration_ms
        source = source or self.source
        media = self.service.get_media(self.fixture.p, source)
        purpose = "video_" + operation
        context = self.service.compile_shot_context(self.fixture.p, self.fixture.objects["shot"], purpose)
        request = {"shot_id": self.fixture.objects["shot"], "purpose": purpose, "modality": "video", "prompt": "Synthetic fixed-source operation",
            "operation": operation, "source_media_id": source, "source_sha256": media["sha256"], "source_duration_ms": source_duration_ms(media)}
        if operation == "extend":
            request["duration_ms"] = 3000
        request.update(overrides or {})
        logical = normalize_request(request, request["shot_id"], purpose, "video")
        pins = [{"id": item["id"], "sha256": item["sha256"]} for item in context["artifacts"]]
        run = self.fixture.artifact("operation-run-" + uuid.uuid4().hex, "production-run", {
            "approved_inputs": pins, "approved_media_inputs": [{"media_id": source, "sha256": media["sha256"], "role": "operation_source"}] if approve_source else [],
            "jobs": [{"candidate_no": 0, "request": request}], "operations": {operation_key(logical, 0): native_units(logical)}}, [item["id"] for item in pins])
        return self.fixture.write("create_generation_job", {"shot_id": request["shot_id"], "purpose": purpose, "modality": "video",
            "model_id": self.model, "run_version_id": run, "candidate_no": 0, "context_sha256": context["sha256"], "request_payload": request})

    def worker(self, download=None, timeout=False):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.adapters.providers.xai_grok.resource_factory import xai_grok_factory
        from vsc.adapters.providers.xai_grok import api
        def transport(path, payload=None):
            self.calls.append((path, payload))
            if timeout:
                raise TimeoutError("offline submit acknowledgement lost")
            return {"request_id": "fixed-task-" + str(sum(value is not None for _, value in self.calls))} if payload is not None else {"status": "done", "video": {"url": "https://example.invalid/result.mp4"}}
        patch = mock.patch.object(api, "call", side_effect=transport)
        patch.start()
        self.addCleanup(patch.stop)
        return ResourceWorker(self.service, xai_grok_factory, download=download or (lambda url, path: path.write_bytes(self.result_bytes)))

    def test_edit_extend_pin_source_native_budget_endpoint_and_typed_lineage(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.providers.xai_grok.provider import ACCOUNT_FIELD
        for operation, seconds, endpoint in (("edit", 2, "/videos/edits"), ("extend", 3, "/videos/extensions")):
            with self.subTest(operation=operation):
                job = self.job(operation)
                worker = self.worker()
                worker.run_once(self.fixture.p)
                result = worker.run_once(self.fixture.p, poll=True)
                self.assertEqual(result["status"], "succeeded")
                saved = self.service.get_generation_job(self.fixture.p, job["id"])
                source = next(item for item in saved["input_media"] if item["role"] == "operation_source")
                self.assertEqual(source["media_id"], self.source)
                self.assertEqual(source["blob_sha256"], saved["request_payload"]["source_sha256"])
                self.assertIsNone(source["binding_decision_id"])
                self.assertEqual(self.calls[-2][0], endpoint)
                self.assertNotIn("source_seconds", self.calls[-2][1])
                self.assertEqual(self.calls[-2][1].get("duration"), 3 if operation == "extend" else None)
                self.assertIn(ACCOUNT_FIELD, saved["raw_response"])
                output = saved["outputs"][0]["media_id"]
                self.assertEqual(self.service.get_media_usage(self.fixture.p, output)["current_bindings"], [])
                with self.engine.connect() as conn:
                    bounds = conn.execute(select(S.job_budget_reservations.c.unit, S.job_budget_reservations.c.bound).where(
                        S.job_budget_reservations.c.project_id == self.fixture.p, S.job_budget_reservations.c.job_id == job["id"])).all()
                    self.assertEqual(dict(bounds), {"remote_jobs": 1, "video_seconds": seconds})
                    operation_id = conn.execute(select(S.operation_outputs.c.operation_id).where(S.operation_outputs.c.project_id == self.fixture.p,
                        S.operation_outputs.c.media_id == output)).scalar_one()
                    self.assertEqual(conn.execute(select(S.operation_inputs.c.media_id).where(S.operation_inputs.c.project_id == self.fixture.p,
                        S.operation_inputs.c.operation_id == operation_id)).scalar_one(), self.source)
                    self.assertEqual(conn.execute(select(S.media_operations.c.status).where(S.media_operations.c.project_id == self.fixture.p,
                        S.media_operations.c.id == operation_id)).scalar_one(), "succeeded")
                worker.finalize(self.fixture.p, job["id"])
                self.assertEqual(sum(payload is not None for _, payload in self.calls), 1 if operation == "edit" else 2)

    def test_source_authorization_cross_project_sha_duration_and_mode_fail_before_intent(self):
        with self.assertRaises(ResourceError) as caught:
            self.job(approve_source=False)
        self.assertEqual(caught.exception.code, "run_source_unauthorized")
        for operation, changes in (("edit", {"source_sha256": "0" * 64}), ("edit", {"source_duration_ms": 1000}),
                                   ("extend", {"duration_ms": 1000}), ("extend", {"duration_ms": 11000})):
            with self.subTest(operation=operation, changes=changes), self.assertRaises(ResourceError):
                self.job(operation, overrides=changes)
        other = ResourceFixture(self.service)
        from vsc.production.video_operations import verify_operation_source
        media = self.service.get_media(self.fixture.p, self.source)
        with self.assertRaises(ResourceError):
            verify_operation_source(self.service, other.p, {"shot_id": other.objects["shot"], "purpose": "video_edit", "modality": "video",
                "prompt": "Synthetic operation", "operation": "edit", "source_media_id": self.source, "source_sha256": media["sha256"], "source_duration_ms": 1300})
        too_long = self.media("long", 9, "green")
        with self.assertRaises(ResourceError):
            self.job(source=too_long)
        self.assertEqual(self.service.list_generation_jobs(self.fixture.p)["total"], 0)
        self.assertEqual(self.calls, [])

    def test_timeout_unknown_never_reposts_and_source_byte_drift_never_submits(self):
        job = self.job()
        worker = self.worker(timeout=True)
        with self.assertRaises(TimeoutError):
            worker.run_once(self.fixture.p)
        self.assertIsNone(worker.run_once(self.fixture.p))
        saved = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual((saved["status"], saved["attempt"]), ("submission_unknown", 1))
        self.assertEqual(len(self.calls), 1)
        second = self.job("extend")
        media = self.service.get_media(self.fixture.p, self.source)
        self.service.storage.resolve(media["locations"][0]["object_key"]).write_bytes(b"modified source bytes")
        with self.assertRaises(ResourceError):
            worker.run_once(self.fixture.p)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.service.get_generation_job(self.fixture.p, second["id"])["attempt"], 0)

    def test_replacement_source_bytes_require_a_new_fixed_run_and_job(self):
        first = self.job()
        replacement = self.media("replacement", 1.4, "yellow")
        second = self.job(source=replacement)
        old = self.service.get_generation_job(self.fixture.p, first["id"])
        new = self.service.get_generation_job(self.fixture.p, second["id"])
        self.assertNotEqual(old["run_version_id"], new["run_version_id"])
        self.assertNotEqual(old["request_sha256"], new["request_sha256"])
        self.assertNotEqual(old["request_payload"]["source_sha256"], new["request_payload"]["source_sha256"])
        self.assertEqual(old["request_payload"]["source_media_id"], self.source)
        self.assertEqual(new["request_payload"]["source_media_id"], replacement)

    def test_download_and_registration_crashes_resume_once_with_same_account(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        downloads = []
        def download(url, path):
            downloads.append(url)
            if len(downloads) == 1:
                raise OSError("offline transfer interruption")
            path.write_bytes(self.result_bytes)
        job = self.job("extend")
        worker = self.worker(download)
        worker.run_once(self.fixture.p)
        with self.assertRaises(OSError):
            worker.run_once(self.fixture.p, poll=True)
        saved = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual(saved["raw_response"]["status"], "done")
        self.login.write_text(json.dumps({"offline": {"user_id": "account-A", "key": "refreshed-token"}}))
        original = worker._write
        def crash(action, *args, **kwargs):
            if action == "update_generation_job" and args[1].get("status") == "succeeded":
                raise RuntimeError("offline crash after media registration")
            return original(action, *args, **kwargs)
        with mock.patch.object(worker, "_write", side_effect=crash), self.assertRaises(RuntimeError):
            worker.finalize(self.fixture.p, job["id"])
        register_operation = self.service.store._register_job_video_operation
        def transaction_crash(*args):
            register_operation(*args)
            raise RuntimeError("offline crash after lineage inserts before commit")
        with mock.patch.object(self.service.store, "_register_job_video_operation", side_effect=transaction_crash), self.assertRaises(RuntimeError):
            worker.finalize(self.fixture.p, job["id"])
        self.assertEqual(self.service.get_generation_job(self.fixture.p, job["id"])["outputs"], [])
        result = worker.finalize(self.fixture.p, job["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(self.calls), 2)  # one POST, one GET; done response survives both faults
        output = self.service.get_generation_job(self.fixture.p, job["id"])["outputs"][0]["media_id"]
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.operation_outputs).where(
                S.operation_outputs.c.project_id == self.fixture.p, S.operation_outputs.c.media_id == output)).scalar_one(), 1)
