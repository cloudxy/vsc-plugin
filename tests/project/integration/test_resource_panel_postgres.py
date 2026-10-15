"""Real PostgreSQL HTTP workflow in a random disposable schema; no provider calls."""
import importlib.util
import os
import struct
import tempfile
import unittest
import uuid
import zlib
from datetime import datetime, timedelta, timezone

from support.paths import ROOT
from support.fixtures.postgres import isolated_postgres

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))


def fixture_png():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x30\x70\x60" * 2 + b"\x00" + b"\x30\x70\x60" * 2)) + chunk(b"IEND", b"")


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires explicit PostgreSQL test URL and web/postgres dependencies")
class PostgresPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(TEST_URL)
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from fastapi.testclient import TestClient
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        from vsc.interfaces.web.app import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.temp.name)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), storage=self.storage)
        self.project = self.service.create_project({"name": "合成测试项目"}, actor="fixture-human")
        self.p, self.revision = self.project["id"], 0
        self.client = TestClient(create_app({"projects_root": self.temp.name + "/empty-projects", "media_root": self.temp.name,
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"], "human_identity": "fixture-human", "access_token": "fixture-token"}, service=self.service))
        self.client.__enter__()
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "fixture-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def write(self, endpoint, payload, status=200, revision=None, key=None):
        response = self.client.post(self.base + "/" + endpoint, headers=self.headers,
            json={"payload": payload, "expected_revision": self.revision if revision is None else revision,
                  "idempotency_key": key or uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(response.status_code, status, response.text)
        result = response.json()
        if status == 200:
            self.revision = result["revision"]
        return result

    def hierarchy(self):
        objects, parent = {}, None
        for kind in ("work", "episode", "scene", "sequence", "shot"):
            row = self.write("objects", {"kind": kind, "display_code": kind.upper(), "parent_id": parent})
            objects[kind] = parent = row["id"]
        return objects

    def upload(self, data=None):
        uploaded = self.client.post(self.base + "/uploads", content=fixture_png() if data is None else data, headers={**self.headers, "X-Filename": "fixture.png"})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        return self.write("media", {"staged_upload": uploaded.json()["staged_upload"], "rights": "owned",
            "rights_scope": {"purposes": ["first_frame"]}, "source": {"kind": "synthetic_test", "content": "test fixture source"}})["id"]

    def test_upload_review_select_and_fixed_shot_context(self):
        objects = self.hierarchy()
        state = [{"scene_id": objects["scene"], "shot_id": objects["shot"], "entities": []}]
        artifact = self.write("artifacts", {"artifact_key": "shot-plan", "artifact_type": "shot-plan",
            "object_ids": [objects["shot"]], "document": {"state_versions": state}, "state_versions": state})
        self.write("artifact-decisions", {"artifact_id": artifact["id"], "reason": "synthetic fixture decision"})
        media = self.upload()
        candidate = self.write("binding-candidates", {"target_object_id": objects["shot"], "media_id": media, "role": "first_frame"})
        self.write("binding-decisions", {"candidate_id": candidate["candidate_id"], "reason": "incomplete"}, status=422)
        detail = self.client.get(self.base + "/media/" + media).json()
        self.assertEqual(detail["integrity"], "verified")
        self.write("media-checks", {"media_id": media, "checker": "fixture-ffprobe", "criteria_version": "1", "outcome": "pass", "report": detail["probe"]})
        self.write("reviews", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reviewer_type": "human", "reason": "synthetic fixture review"})
        decision = self.write("binding-decisions", {"candidate_id": candidate["candidate_id"], "reason": "synthetic fixture choice"})
        context = self.client.get(self.base + "/shots/" + objects["shot"] + "/context")
        self.assertEqual(context.status_code, 200, context.text)
        self.assertTrue(context.json()["ready"], context.text)
        self.assertEqual(context.json()["media"][0]["binding_decision_id"], decision["decision_id"])
        content = self.client.get(self.base + "/media/" + media + "/content", headers={"Range": "bytes=0-7"})
        self.assertEqual(content.status_code, 206)
        self.assertEqual(content.content, b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.client.get(self.base + "/media?object_id=" + objects["work"]).json()["total"], 1)

    def test_http_revision_conflict_and_project_media_isolation(self):
        objects = self.hierarchy()
        media = self.upload()
        self.write("binding-candidates", {"target_object_id": objects["shot"], "media_id": media, "role": "first_frame"}, status=409, revision=0)
        self.write("media-lifecycle-decisions", {"media_id": media, "reason": "synthetic fixture retirement"})
        self.assertEqual(self.client.get(self.base + "/media?status=deprecated").json()["total"], 1)
        self.assertEqual(self.client.get(self.base + "/media?status=active").json()["total"], 0)
        self.assertEqual(self.client.get(self.base + "/media/" + media + "/content").content, fixture_png())
        other = self.service.create_project({"name": "另一合成项目"}, actor="fixture-human")
        response = self.client.get("/api/v1/projects/" + other["id"] + "/media/" + media + "/content")
        self.assertEqual(response.status_code, 404)

    def test_durable_preview_worker_publishes_only_rendition_and_http_preview(self):
        from vsc.post.previews import PreviewWorker, RECIPE_VERSION
        media = self.upload()
        job = self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        result = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual((result["id"], result["status"]), (job["id"], "succeeded"))
        detail = self.client.get(self.base + "/media/" + media).json()
        self.assertEqual(len(detail["renditions"]), 1)
        self.assertEqual(detail["renditions"][0]["source_sha256"], detail["sha256"])
        self.assertEqual(detail["renditions"][0]["source_blob_id"], detail["blob_id"])
        self.assertEqual(detail["renditions"][0]["recipe_version"], RECIPE_VERSION)
        self.assertIn("ffmpeg version", detail["renditions"][0]["tool_version"])
        self.assertEqual(detail["decisions"], [])
        self.assertEqual(self.client.get(self.base + "/media").json()["total"], 1)
        response = self.client.get(self.base + "/media/" + media + "/preview?purpose=thumbnail")
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else "")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        jobs = self.client.get(self.base + "/preview-jobs?media_id=" + media).json()["items"]
        self.assertEqual(jobs[0]["status"], "succeeded")

    def test_expired_preview_lease_is_resumed_and_old_attempt_is_fenced(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import Conflict
        from vsc.post.previews import PreviewWorker, RECIPE_VERSION
        media = self.upload()
        self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        old = self.service.store.claim_preview_job(project_id=self.p)
        with self.engine.begin() as connection:
            connection.execute(update(S.preview_jobs).where(S.preview_jobs.c.project_id == self.p,
                S.preview_jobs.c.id == old["id"]).values(claim_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        resumed = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(resumed["status"], "succeeded")
        self.assertEqual(resumed["attempt"], old["attempt"] + 1)
        with self.assertRaises(Conflict) as conflict:
            self.service.store.finish_preview_job(self.p, old["id"], old["attempt"], {})
        self.assertEqual(conflict.exception.code, "preview_attempt_conflict")
        self.assertEqual(self.service.list_preview_jobs(self.p)["items"][0]["status"], "succeeded")

    def test_failed_preview_requires_explicit_retry_and_keeps_source(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.post.previews import PreviewConverter, PreviewWorker, RECIPE_VERSION
        class MissingConverter(PreviewConverter):
            def convert(self, *args, **kw):
                raise ResourceError("fixture conversion unavailable", "preview_tool_unavailable")
        media = self.upload()
        job = self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        failed = PreviewWorker(self.service.store, self.storage, converter=MissingConverter()).run_once(project_id=self.p)
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p))
        self.revision = failed["revision"]
        self.write("preview-retries", {"job_id": job["id"]})
        retried = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(retried["status"], "succeeded")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(self.client.get(self.base + "/media/" + media + "/content").content, fixture_png())

    def test_preview_provenance_survives_identical_byte_deduplication(self):
        import hashlib
        from pathlib import Path
        from vsc.post.previews import PreviewConverter, PreviewWorker, RECIPE_VERSION
        root = Path(self.temp.name)
        source = root / "source.png"
        raw = fixture_png()
        source.write_bytes(raw)
        canonical, _ = PreviewConverter().convert(source, {"modality": "image", "sha256": hashlib.sha256(raw).hexdigest()}, "thumbnail", root)
        media = self.upload(canonical.read_bytes())
        self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        result = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(result["status"], "succeeded")
        detail = self.client.get(self.base + "/media/" + media).json()
        rendition = detail["renditions"][0]
        self.assertEqual(rendition["sha256"], detail["sha256"])
        self.assertEqual(rendition["blob_id"], rendition["source_blob_id"])
        self.assertIn("ffmpeg version", rendition["tool_version"])
        self.assertNotIn("preview", detail["probe"])

    def test_registration_retry_keeps_same_media_and_revision_after_staging_move(self):
        uploaded = self.client.post(self.base + "/uploads", content=fixture_png(), headers={**self.headers, "X-Filename": "fixture.png"}).json()
        payload = {"staged_upload": uploaded["staged_upload"], "rights": "unknown", "source": {"kind": "synthetic_test", "content": "test-only upload source"}}
        first = self.write("media", payload, key="same-upload-once")
        repeated = self.write("media", payload, revision=0, key="same-upload-once")
        self.assertEqual(first, repeated)
        self.assertEqual(self.client.get(self.base + "/media").json()["total"], 1)
