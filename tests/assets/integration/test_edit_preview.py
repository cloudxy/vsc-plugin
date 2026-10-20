"""Real PostgreSQL and FFmpeg evidence for the assisted subtitle vertical slice."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS
from support.fixtures.edit_preview import EditPreviewFixture
from vsc.configuration import get_config
from vsc.assets.resource_service import ResourceError
from vsc.post.edit_preview import EditPreviewConverter, EditPreviewWorker, RECIPE_VERSION

TEST_URL = get_config("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires configured isolated PostgreSQL")
class EditPreviewTests(EditPreviewFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        cls.db = isolated_postgres(TEST_URL)
        cls.engine = cls.db.__enter__()
        cls.store = PostgresResourceStore(engine=cls.engine)
        cls.service = ResourceService(cls.store)

    def setUp(self):
        super().setUp()
        from vsc.adapters.persistence.postgres.edit_preview_store import EditPreviewRepository
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-edit-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = LocalStorage(self.root / "storage")
        self.service.storage = self.storage
        self.repository = EditPreviewRepository(self.store)
        self.converter = EditPreviewConverter()
        if not self.converter.capabilities()["available"]:
            self.skipTest(self.converter.capabilities()["reason"])
        self.workers = []
        self.addCleanup(lambda: [w.stop() for w in self.workers])
        self.addCleanup(setattr, self.service, "edit_preview_worker", None)

    def worker(self, **kwargs):
        worker = EditPreviewWorker(self.store, self.storage, **kwargs)
        self.workers.append(worker)
        return worker


    def request(self, key=None):
        result = self.repository.request(self.p, {"target": self.target, "body": "这句字幕放到顶部", "caption_id": self.caption_id, "operation": "top"},
            self.converter.capabilities(), actor="test-human", expected_revision=self.rev, idempotency_key=key or uuid.uuid4().hex)
        self.rev = result["revision"]
        return result

    def pixels(self, path, seconds):
        return subprocess.run([self.converter.ffmpeg, "-v", "error", "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout

    def test_real_background_http_opinion_returns_draft_playable_slice_without_double_subtitles(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        self.assertTrue(self.seed()["available"])
        app = create_app({"projects_root": str(self.root/"empty"), "media_root": str(self.storage.root),
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "access_token": "test-token", "human_identity": "test-human"}, service=self.service)
        with TestClient(app) as client:
            worker = self.worker(poll_seconds=.03).start()
            self.service.edit_preview_worker = worker
            session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
            headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
            body = {"expected_revision": self.rev, "idempotency_key": "one-click",
                    "payload": {"target": self.target, "body": "只移动这句到顶部", "caption_id": "C2", "operation": "top"}}
            denied = client.post(f"/api/v1/projects/{self.p}/edit-preview-requests", json=body)
            self.assertEqual(denied.status_code, 403)
            submitted = client.post(f"/api/v1/projects/{self.p}/edit-preview-requests", headers=headers, json=body)
            self.assertEqual(submitted.status_code, 200, submitted.text)
            result = submitted.json()
            replay = client.post(f"/api/v1/projects/{self.p}/edit-preview-requests", headers=headers, json=body)
            self.assertEqual(replay.json()["job_id"], result["job_id"])
        # HTTP/browser closure leaves the independently hosted worker running.
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            job = self.repository.list(self.p, result["note_id"])["items"][0]
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(.05)
        worker.stop()
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual((job["start_frame"], job["end_frame"]), (48, 120))
        path, _ = self.service.edit_preview_content(self.p, job["id"])
        pixels = self.pixels(path, 1.5)  # global 3.5 seconds, selected second cue
        self.assertGreater(sum(p > 180 for p in pixels[:240*160]), 50)
        self.assertLess(sum(p > 180 for p in pixels[240*160:]), 10)
        original = self.pixels(self.original, 3.5)
        self.assertGreater(sum(p > 180 for p in original[240*160:]), 50)
        for moment in (.25, 2.75):
            unchanged = self.pixels(path, moment)
            self.assertLess(sum(p > 180 for p in unchanged[:240*160]), 10)
            self.assertGreater(sum(p > 180 for p in unchanged[240*160:]), 50)
        # Compare actual waveform content on the global/local frame offset.
        # AAC reencoding is allowed; changing or replacing the source sound is not.
        from array import array
        import math
        def pcm(media, start):
            raw = subprocess.run([self.converter.ffmpeg, "-v", "error", "-i", str(media), "-ss", str(start),
                "-t", "3", "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                check=True, capture_output=True).stdout
            values = array("h")
            values.frombytes(raw)
            return values
        before, after = pcm(self.master, 2), pcm(path, 0)
        length = min(len(before), len(after))
        self.assertLess(abs(len(before)-len(after)), 1600/24)
        correlation = sum(a*b for a,b in zip(before,after))/math.sqrt(
            sum(a*a for a in before[:length])*sum(b*b for b in after[:length]))
        self.assertGreater(correlation, .98)
        self.assertEqual(hashlib.sha256(self.master.read_bytes()).hexdigest(), self.master_sha)
        draft = self.service.get_artifact_version(self.p, job["draft_artifact_id"])
        self.assertFalse(draft["approved"])
        changed = json.loads(draft["content"])
        original_plan = copy.deepcopy(changed)
        original_plan["segments"][2].pop("subtitle_style")
        self.assertEqual(original_plan, self.plan)
        with self.assertRaises(ResourceError) as caught:
            self.service.freeze_render(self.p, {"artifact_id": draft["id"], "timeline_id": self.timeline_id,
                "tool": "test", "tool_version": "1"}, actor="test-human", expected_revision=self.store.get_project(self.p)["revision"],
                idempotency_key="cannot-freeze-unapproved")
        self.assertEqual(caught.exception.code, "render_unapproved")
        history = self.service.get_review_history(self.p, artifact_note_id=result["note_id"])["items"][0]
        self.assertEqual(history["body"], "只移动这句到顶部")
        self.assertEqual(history["edit_previews"][0]["id"], job["id"])
        self.assertEqual(len(history["responses"][0]["dispatches"][0]["returns"]), 1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id==self.p)).scalar_one(), 1)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.render_versions).where(S.render_versions.c.project_id==self.p)).scalar_one(), 1)
        # Read back through a newly constructed service and HTTP app.
        from vsc.assets.resource_service import ResourceService
        rebuilt = ResourceService(self.store, self.storage)
        with TestClient(create_app({"projects_root": str(self.root/"empty"), "media_root": str(self.storage.root),
                "allowed_hosts": ["testserver"]}, service=rebuilt)) as client:
            media = client.get(job["output"]["content_url"])
            self.assertEqual(media.status_code, 200, media.text[:300] if media.status_code != 200 else "")
            self.assertEqual(media.content, path.read_bytes())
            other = self.service.create_project({"name": "isolated other"}, actor="test-human")["id"]
            self.assertEqual(client.get(job["output"]["content_url"].replace(self.p, other)).status_code, 404)

    def test_missing_clean_master_keeps_original_opinion_blocked(self):
        capability = self.seed(missing=True)
        self.assertFalse(capability["available"])
        result = self.request()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(self.worker().run_once(self.p))
        history = self.service.get_review_history(self.p, artifact_note_id=result["note_id"])["items"][0]
        self.assertEqual(history["body"], "这句字幕放到顶部")
        self.assertIn("底片", history["edit_previews"][0]["error"])
        self.assertIsNone(history["edit_previews"][0]["output"])

    def test_failed_job_retries_through_http_and_desk_reopens_original_opinion(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.seed()
        requested = self.request()
        worker = self.worker(poll_seconds=.03)
        app = create_app({"projects_root": str(self.root/"empty"), "media_root": str(self.storage.root),
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "access_token": "test-token", "human_identity": "test-human"}, service=self.service)
        with TestClient(app) as client:
            progress = client.get(f"/api/v1/projects/{self.p}/assisted-desk?bucket=progress").json()
            row = next(item for item in progress["items"] if item["kind"] == "preview")
            self.assertEqual(row["id"], "edit-preview:"+requested["job_id"])
            with patch.object(worker.converter, "convert", side_effect=ResourceError("合成暂时失败", "edit_preview_tool_failed")):
                self.assertEqual(worker.run_once(self.p)["status"], "failed")
            worker.start()
            self.service.edit_preview_worker = worker
            session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
            headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
            body = {"expected_revision": self.store.get_project(self.p)["revision"],
                    "idempotency_key": "retry-same-caption", "payload": {}}
            url = f"/api/v1/projects/{self.p}/edit-previews/{requested['job_id']}/retry"
            retried = client.post(url, headers=headers, json=body)
            self.assertEqual(retried.status_code, 200, retried.text)
            self.assertEqual(retried.json()["note_id"], requested["note_id"])
            self.assertEqual(client.post(url, headers=headers, json=body).json(), retried.json())
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                job = self.repository.list(self.p, requested["note_id"])["items"][0]
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.05)
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["attempt"], 2)
            review = client.get(f"/api/v1/projects/{self.p}/assisted-desk?bucket=review").json()
            row = next(item for item in review["items"] if item["kind"] == "preview")
            self.assertEqual(row["id"], "edit-preview:"+requested["job_id"])
            self.assertEqual(row["ref"]["id"], self.source_id)
            self.assertEqual(row["ref"]["artifact_note_id"], requested["note_id"])
            self.assertEqual(len(self.repository.list(self.p, requested["note_id"])["items"]), 1)

    def test_missing_preview_bytes_do_not_erase_success_or_claim_playable_output(self):
        self.seed()
        requested = self.request()
        worker = self.worker()
        self.assertEqual(worker.run_once(self.p)["status"], "succeeded")
        listed = self.service.list_edit_previews(self.p, requested["note_id"])["items"][0]
        self.assertEqual(listed["result_availability"]["status"], "available")
        self.assertIn("content_url", listed["output"])
        path, fixed = self.service.edit_preview_content(self.p, requested["job_id"])
        original = path.read_bytes()
        path.write_bytes(b"synthetic truncated result")
        unavailable = self.service.list_edit_previews(self.p, requested["note_id"])["items"][0]
        self.assertEqual(unavailable["status"], "succeeded", "Execution history is not a read-time availability verdict.")
        self.assertEqual(unavailable["result_availability"]["status"], "unavailable")
        self.assertNotIn("content_url", unavailable["output"])
        self.assertEqual(unavailable["output"]["blob_sha256"], fixed["blob_sha256"])
        history = self.service.get_review_history(self.p, artifact_note_id=requested["note_id"])
        reviewed = history["items"][0]["edit_previews"][0]
        self.assertEqual(reviewed["result_availability"]["status"], "unavailable")
        self.assertNotIn("content_url", reviewed["output"])
        with self.assertRaises(ResourceError):
            self.service.edit_preview_content(self.p, requested["job_id"])
        path.write_bytes(original)
        restored = self.service.list_edit_previews(self.p, requested["note_id"])["items"][0]
        self.assertEqual(restored["result_availability"]["status"], "available")
        self.assertEqual(restored["attempt"], listed["attempt"])
        self.assertFalse(restored["adopted"])

    def test_preview_output_must_match_actual_composition_and_duration(self):
        from vsc.post import subtitle_burn as SB
        self.seed()
        self.request()
        worker = self.worker()
        job = self.repository.claim(worker.worker_id, self.p, 60)
        prepared = self.repository.prepare(job, worker.worker_id)
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            output, receipt = self.converter.convert(prepared, self.master, SB.DEFAULT_FONT, directory)
            with output.open("rb") as stream:
                staged = self.storage.stage_upload(stream, output.name)
            media = self.storage.commit_upload(staged["staged_upload"])
            for changes in ({"width": media["width"] + 1}, {"duration_ms": media["duration_ms"] + 1000},
                            {"modality": "image"}):
                with self.subTest(changes=changes), self.assertRaises(ResourceError) as caught:
                    self.repository.record_output(prepared, worker.worker_id, dict(media, **changes), receipt)
                self.assertEqual(caught.exception.code, "edit_preview_output_mismatch")
            self.repository.record_output(prepared, worker.worker_id, media, receipt)
        self.assertEqual(self.repository.finish(prepared, worker.worker_id)["status"], "succeeded")

    def produce_output(self, worker, job):
        prepared = self.repository.prepare(job, worker.worker_id)
        self.save_output(worker,prepared)
        return prepared

    def save_output(self,worker,prepared):
        from vsc.post import subtitle_burn as SB
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            output, receipt = self.converter.convert(prepared, self.master, SB.DEFAULT_FONT, directory)
            with output.open("rb") as data:
                staged = self.storage.stage_upload(data, output.name)
            self.repository.record_output(prepared, worker.worker_id, self.storage.commit_upload(staged["staged_upload"]), receipt)

    def test_leased_restart_reuses_real_output_and_fences_old_worker(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        self.seed()
        result = self.request()
        first, second = self.worker(), self.worker()
        job = self.repository.claim(first.worker_id, self.p, 60)
        self.assertIsNone(self.repository.claim(second.worker_id, self.p, 60))
        prepared = self.produce_output(first, job)
        self.repository.heartbeat(self.p, job["id"], first.worker_id, job["attempt"], 60)
        with self.engine.begin() as conn:
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id==self.p,
                S.edit_preview_jobs.c.id==job["id"]).values(claim_until=datetime.now(timezone.utc)-timedelta(seconds=1)))
        replacement = self.repository.claim(second.worker_id, self.p, 60)
        with self.assertRaises(ResourceError) as caught:
            self.repository.finish(prepared, first.worker_id)
        self.assertEqual(caught.exception.code, "edit_preview_lease_lost")
        resumed = self.repository.prepare(replacement, second.worker_id)
        self.assertIsNotNone(resumed["output"])
        self.repository.finish(resumed, second.worker_id)
        listed = self.repository.list(self.p, result["note_id"])["items"][0]
        self.assertEqual(listed["status"], "succeeded")
        self.assertEqual(listed["attempt"], 2)

    def test_expired_context_preserves_real_output_and_refuses_success_return(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        self.seed()
        result = self.request()
        worker = self.worker()
        job = self.repository.claim(worker.worker_id, self.p, 60)
        prepared = self.produce_output(worker, job)
        class FutureDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz or timezone.utc)+timedelta(days=2)
        with patch("vsc.adapters.persistence.postgres.memory_store.datetime", FutureDatetime):
            with self.assertRaises(ResourceError) as caught:
                self.repository.finish(prepared, worker.worker_id)
        self.assertEqual(caught.exception.code, "dispatch_expired")
        ended = self.repository.fail(prepared, worker.worker_id, caught.exception)
        self.assertEqual(ended["status"], "stale")
        stored = self.repository.list(self.p, result["note_id"])["items"][0]
        self.assertTrue(stored["output"]["content_url"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.dispatch_returns).where(
                S.dispatch_returns.c.project_id==self.p)).scalar_one(), 0)

    def test_source_changes_reject_old_publish_and_keep_playable_output(self):
        self.seed()
        result = self.request()
        worker = self.worker()
        job = self.repository.claim(worker.worker_id, self.p, 60)
        prepared = self.produce_output(worker, job)
        self.rev = self.store.get_project(self.p)["revision"]
        changed = copy.deepcopy(self.plan)
        changed["segments"][2]["text"] = "人工编辑后的新字幕"
        newer = self.write("create_artifact", {"artifact_key": "caption-render", "artifact_type": "render-plan", "document": changed})
        with self.assertRaises(ResourceError) as caught:
            self.repository.finish(prepared, worker.worker_id)
        self.assertEqual(caught.exception.code, "review_target_stale")
        self.repository.fail(prepared, worker.worker_id, caught.exception)
        stored = self.repository.list(self.p, result["note_id"])["items"][0]
        self.assertEqual(stored["status"], "stale")
        self.assertTrue(stored["output"]["content_url"])
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p, newer["id"])["content"]), changed)

    def test_original_baseline_can_edit_another_cue_after_unapproved_preview(self):
        self.seed()
        first = self.request()
        self.assertEqual(self.worker().run_once(self.p)["status"],"succeeded")
        capability = self.repository.capability(self.p,render_id=self.render_id)
        self.assertTrue(capability["available"],capability)
        self.rev = self.store.get_project(self.p)["revision"]
        second = self.repository.request(self.p, {"target": dict(self.target,start_frame=36,end_frame=60),
            "body":"把第一句放顶部","caption_id":"C1","operation":"top"},self.converter.capabilities(),
            actor="test-human",expected_revision=self.rev,idempotency_key="second-cue")
        self.assertEqual(self.worker().run_once(self.p)["status"],"succeeded")
        self.assertNotEqual(first["job_id"],second["job_id"])
        self.assertTrue(self.repository.capability(self.p,render_id=self.render_id)["available"])

    def test_late_old_attempt_output_never_replaces_new_attempt_playback(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        self.seed()
        requested = self.request()
        first, second = self.worker(), self.worker()
        old = self.repository.prepare(self.repository.claim(first.worker_id,self.p,60),first.worker_id)
        with self.engine.begin() as conn:
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id==self.p,
                S.edit_preview_jobs.c.id==old["id"]).values(claim_until=datetime.now(timezone.utc)-timedelta(seconds=1)))
        newer = self.produce_output(second,self.repository.claim(second.worker_id,self.p,60))
        self.repository.finish(newer,second.worker_id)
        before = self.repository.list(self.p,requested["note_id"])["items"][0]["output"]["id"]
        self.save_output(first,old)
        after = self.repository.list(self.p,requested["note_id"])["items"][0]
        self.assertEqual(after["status"],"succeeded")
        self.assertEqual(after["output"]["id"],before)

    def test_canonical_measured_package_materializes_fixed_audio_and_keeps_real_approvals(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        capability = self.seed(canonical=True)
        self.assertTrue(capability["available"], capability)
        result = self.request()
        complete = self.worker().run_once(self.p)
        self.assertEqual(complete["status"], "succeeded", complete)
        job = self.repository.list(self.p,result["note_id"])["items"][0]
        draft = json.loads(self.service.get_artifact_version(self.p, job["draft_artifact_id"])["content"])
        self.assertEqual(draft["subtitle_package"], self.plan["subtitle_package"])
        self.assertEqual(job["output"]["receipt"]["subtitle_checks"]["audio_alignment"], "measured_timecodes_verified")
        with self.engine.connect() as conn:
            sources = conn.execute(select(S.edit_preview_inputs).where(S.edit_preview_inputs.c.project_id==self.p,
                S.edit_preview_inputs.c.job_id==job["id"], S.edit_preview_inputs.c.role=="subtitle_audio")).mappings().all()
            self.assertEqual(len(sources), 3)
            self.assertEqual({r["media_id"] for r in sources}, {self.audio_id})
            self.assertEqual(len({r["timeline_item_id"] for r in sources}), 3)
        output,_ = self.service.edit_preview_content(self.p,job["id"])
        pixels = self.pixels(output,1.5)
        self.assertGreater(sum(p>180 for p in pixels[:240*160]),50)
        self.assertLess(sum(p>180 for p in pixels[240*160:]),10)

    def test_canonical_audio_withdrawal_blocks_before_execution(self):
        self.seed(canonical=True)
        result = self.request()
        self.write("decide_rights", {"media_id": self.audio_id, "outcome": "revoked", "scope": {"purposes": ["*"]},
            "reason": "Synthetic withdrawal before processing"})
        finished = self.worker().run_once(self.p)
        self.assertEqual(finished["status"], "failed")
        self.assertIn("edit_preview_package_audio_invalid", finished["error"])
        self.assertIsNone(self.repository.list(self.p,result["note_id"])["items"][0]["output"])

    def test_caption_render_cli_records_real_clean_inputs_without_user_json_and_replays(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.post import subtitle_burn
        self.seed(missing=True, canonical=True)
        self.assertFalse(self.repository.capability(self.p,render_id=self.render_id)["available"])
        args = ["subtitle_burn.py", "caption-render", self.p, "--timeline-id", self.timeline_id,
            "--artifact-id", self.source_id, "--clean-master-media-id", self.master_id, "--font-media-id", self.font_id,
            "--expected-revision", str(self.rev), "--key", "real-caption-producer", "--by", "test-human"]
        output = StringIO()
        with patch("sys.argv",args), patch("vsc.bootstrap.service_from_environment", return_value=self.service), \
                patch.object(self.store,"close"), redirect_stdout(output):
            subtitle_burn.main()
        created = json.loads(output.getvalue())
        self.assertTrue(self.repository.capability(self.p,render_id=created["id"])["available"])
        with self.engine.connect() as conn:
            pins = conn.execute(select(S.render_caption_inputs).where(S.render_caption_inputs.c.project_id==self.p,
                S.render_caption_inputs.c.render_id==created["id"])).mappings().all()
            self.assertEqual({r["role"] for r in pins},{"clean_master","subtitle_font"})
            outputs = conn.execute(select(S.render_outputs).where(S.render_outputs.c.project_id==self.p,
                S.render_outputs.c.render_id==created["id"])).mappings().all()
            self.assertEqual(len(outputs),1)
            self.assertEqual(outputs[0]["role"],"delivery")
        again = StringIO()
        with patch("sys.argv",args), patch("vsc.bootstrap.service_from_environment", return_value=self.service), \
                patch.object(self.store,"close"), patch.object(EditPreviewConverter,"convert",side_effect=AssertionError("must reuse completed receipt")), \
                redirect_stdout(again):
            subtitle_burn.main()
        self.assertEqual(json.loads(again.getvalue())["id"],created["id"])

    def test_migration_matches_metadata_and_cross_project_input_fk(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import insert, text
        from sqlalchemy.exc import IntegrityError
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres import schema as S
        with isolated_postgres(TEST_URL) as engine:
            config = Config(str(support.paths.ROOT/"migrations/postgres/alembic.ini"))
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                command.downgrade(config, "0011_review_feedback")
                command.upgrade(config, "head")
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
                schema_name = conn.execute(text("SELECT current_schema()")).scalar_one()
            checked = subprocess.run([str(support.paths.ROOT/".venv/bin/python"), "-B", "scripts/project/schema.py",
                "check", "--database-env", "VSC_TEST_DATABASE_URL", "--schema", schema_name],
                cwd=support.paths.ROOT, capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(checked.stdout)["passed"])
        self.seed()
        result = self.request()
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.edit_preview_attempts).values(project_id=other, id=str(uuid.uuid4()), job_id=result["job_id"],
                attempt=1, worker_id="wrong", status="running"))


class EditPreviewLifecycleTests(unittest.TestCase):
    def test_pause_resume_during_active_work_continues_consumption(self):
        import threading
        from vsc.assets.execution_runtime import ExecutionRuntime
        active, release, resumed = threading.Event(),threading.Event(),threading.Event()
        worker = EditPreviewWorker(None,None,poll_seconds=.01)
        runtime = ExecutionRuntime(None, preview=worker)
        calls = []
        def controlled_run():
            calls.append(1)
            if len(calls)==1:
                active.set()
                release.wait(20)
            else:
                resumed.set()
            return None
        worker.run_once = controlled_run
        worker.start()
        self.assertTrue(active.wait(3))
        stopper = threading.Thread(target=worker.stop)
        stopper.start()
        deadline = time.monotonic()+2
        while not worker._stop.is_set() and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertFalse(worker.status()["running"])
        stopper.join(6)
        self.assertFalse(stopper.is_alive())
        self.assertTrue(worker.status()["finishing"])
        self.assertTrue(runtime.has_live_workers())
        worker.start()
        release.set()
        self.assertTrue(resumed.wait(3))
        worker.stop()
        stopper.join(3)
        self.assertFalse(worker.status()["running"])
        self.assertFalse(runtime.has_live_workers())
