"""A sound opinion reaches the original proposal/job/output path via trusted HTTP."""
import os
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture
from support.fixtures.reviews import OfflineAudio, audio_bytes, seed_sound_review_source
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_worker import ResourceWorker


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL"), "requires explicit PostgreSQL test URL")
class ReviewSoundTests(unittest.TestCase):
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
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(self.temp.name))
        self.fixture = ResourceFixture(self.service)
        self.p = self.fixture.p
        self.clients = []; self.addCleanup(lambda: [client.__exit__(None, None, None) for client in self.clients])

    def client(self, service=None):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        client = TestClient(create_app({"projects_root": self.temp.name + "/empty", "media_root": self.temp.name,
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "access_token": "test-token", "human_identity": "fixture-human"}, service=service or self.service))
        client.__enter__(); self.clients.append(client)
        session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        return client, {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}

    def http(self, client, headers, endpoint, payload, *, key=None, revision=None, status=200):
        revision = self.service.get_project(self.p)["revision"] if revision is None else revision
        response = client.post(f"/api/v1/projects/{self.p}/{endpoint}", headers=headers,
            json={"payload": payload, "expected_revision": revision, "idempotency_key": key or uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def source(self):
        result = seed_sound_review_source(self.service, self.fixture)
        self.model, self.source_request = result["model_id"], result["request"]
        return result["job"], result["media_id"], result["selection"]

    def test_sound_http_original_opinion_actual_offline_audio_replay_and_rebuild(self):
        source_job, old_media, selection = self.source()
        client, headers = self.client()
        note = self.http(client, headers, "reviews", {"candidate_id": selection["candidate_id"], "outcome": "needs_changes",
            "reason": "只重做本镜声音，保持画面与其他镜头", "reviewer_type": "human"})["id"]
        payload = {"action": "redo_sound", "shot_id": self.fixture.objects["shot"], "purpose": "dialogue_dry", "media_review_id": note}
        preview = client.post(f"/api/v1/projects/{self.p}/local-production/preview", json={"payload": payload}).json()
        self.assertEqual(preview["review"]["body"], "只重做本镜声音，保持画面与其他镜头")
        proposal = self.http(client, headers, "local-production-proposals", dict(payload, preview_sha256=preview["preview_sha256"]), key="sound-once")
        replay = self.http(client, headers, "local-production-proposals", dict(payload, preview_sha256=preview["preview_sha256"]), key="sound-once", revision=0)
        self.assertEqual(proposal, replay)
        artifact = proposal["artifact"]["id"]
        self.http(client, headers, "local-production-enqueue", {"artifact_id": artifact}, status=422)
        self.http(client, headers, "artifact-decisions", {"artifact_id": artifact, "reason": "approve exact local audio request"})
        queued = self.http(client, headers, "local-production-enqueue", {"artifact_id": artifact}, key="queue-once")
        ResourceWorker(self.service, lambda job, service: OfflineAudio(audio_bytes(120))).run_once(self.p)
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        rebuilt = ResourceService(PostgresResourceStore(engine=self.engine), self.service.storage)
        second, _ = self.client(rebuilt)
        history = second.get(f"/api/v1/projects/{self.p}/media/{old_media}").json()["review_history"]
        original = next(row for row in history["items"] if row["source"].get("media_review_id") == note)
        new_job = original["responses"][0]["proposals"][0]["jobs"][0]
        self.assertEqual(new_job["status"], "succeeded")
        new_media = new_job["outputs"][0]["media_id"]
        self.assertNotEqual(new_media, old_media)
        actual = second.get(f"/api/v1/projects/{self.p}/media/{new_media}/content")
        self.assertEqual(actual.content, audio_bytes(120))
        self.assertEqual(rebuilt.get_generation_job(self.p, queued["jobs"][0]["id"])["shot_id"], self.fixture.objects["shot"])
        old = rebuilt.get_media(self.p, old_media)
        self.assertTrue(any(row.get("candidate_id") == selection["candidate_id"] and row.get("outcome") == "select" for row in old["decisions"]))
        self.assertEqual(rebuilt.get_generation_job(self.p, source_job["id"])["status"], "succeeded")

    def test_sound_wrong_review_unknown_source_stale_preview_and_cross_project_are_preserved(self):
        source_job, old_media, selection = self.source()
        review = self.fixture.write("record_review", {"candidate_id": selection["candidate_id"], "outcome": "needs_changes", "reason": "原话", "reviewer_type": "human"})["id"]
        payload = {"action": "redo_sound", "shot_id": self.fixture.objects["shot"], "purpose": "dialogue_dry", "media_review_id": review}
        preview = self.service.preview_local_production(self.p, payload)
        newer = self.fixture.job("audio", "dialogue_dry", self.model, self.source_request, candidate_no=1)
        self.fixture.write("update_generation_job", {"job_id": newer["id"], "status": "submission_unknown"})
        before = self.service.get_project(self.p)["revision"]
        client, headers = self.client()
        self.http(client, headers, "local-production-proposals", dict(payload, preview_sha256=preview["preview_sha256"]), status=422)
        self.assertEqual(self.service.get_project(self.p)["revision"], before)
        other = ResourceFixture(self.service)
        with self.assertRaises(ResourceError):
            self.service.preview_local_production(other.p, payload)
        history = self.service.get_review_history(self.p, media_review_id=review)["items"][0]
        self.assertEqual(history["body"], "原话")
        self.assertEqual(history["responses"], [])

    def test_review_sound_does_not_rebind_old_opinion_to_a_new_voice_specification(self):
        _, _, selection = self.source()
        review = self.fixture.write("record_review", {"candidate_id": selection["candidate_id"], "outcome": "needs_changes", "reason": "保留所听音色重做", "reviewer_type": "human"})["id"]
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            old = conn.execute(select(S.voice_spec_versions, S.character_voice_bindings.c.character_id).join(S.character_voice_bindings,
                (S.character_voice_bindings.c.project_id == S.voice_spec_versions.c.project_id) &
                (S.character_voice_bindings.c.voice_spec_id == S.voice_spec_versions.c.id)).where(
                    S.voice_spec_versions.c.project_id == self.p)).mappings().one()
        new_spec = str(uuid.uuid4())
        self.fixture.artifact("review-audio-voice", "voice-spec", {"voice_specs": [{"id": new_spec, "voice_id": old["voice_id"]}],
            "voice_bindings": [{"character_id": old["character_id"], "voice_spec_id": new_spec}]})
        with self.assertRaises(ResourceError) as caught:
            self.service.preview_local_production(self.p, {"action": "redo_sound", "shot_id": self.fixture.objects["shot"],
                "purpose": "dialogue_dry", "media_review_id": review})
        self.assertEqual(caught.exception.code, "review_target_stale")
        self.assertEqual(self.service.get_review_history(self.p, media_review_id=review)["items"][0]["responses"], [])
