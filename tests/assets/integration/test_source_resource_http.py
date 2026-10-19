"""Real HTTP/service/storage/PG seams for source and resource workspaces."""
import io
import tempfile
import unittest
import uuid
from pathlib import Path

import support.paths  # noqa: F401
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit test PostgreSQL URL")
class SourceResourceHTTP(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        from vsc.interfaces.web.app import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ResourceService(self.store, storage=LocalStorage(self.temp.name))
        app = create_app({"projects_root": self.temp.name, "access_token": "synthetic-token",
            "human_identity": "synthetic-human", "allowed_hosts": ["testserver"],
            "allowed_origins": ["http://testserver"]}, service=self.service)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Origin": "http://testserver"}
        response = self.client.post("/api/v1/session", json={"token": "synthetic-token"}, headers=self.headers)
        self.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        self.base = "/api/v1/projects/" + self.p

    def post(self, route, payload, confirmed=False):
        response = self.client.post(self.base + "/" + route, headers=self.headers,
            json={"expected_revision": self.rev, "idempotency_key": uuid.uuid4().hex,
                  "payload": payload, "confirmed": confirmed})
        if response.status_code == 200:
            self.rev = response.json()["revision"]
        return response

    def test_empty_project_parse_preview_prepare_import_and_read(self):
        source = self.post("source-workspace/sources", {"title": "测试剧本", "intent": "screenplay",
            "content": "SC1\nAlice: Hello\nHe turns."}).json()
        workspace = self.client.get(self.base + "/source-workspace").json()
        self.assertEqual(workspace["sources"][0]["intent"], "screenplay")
        job = self.post("source-workspace/parse-jobs", {"intent": "screenplay", "inputs": [
            {"source_id": source["id"], "source_sha256": source["sha256"]}]}).json()
        result = self.post("source-workspace/parse-jobs/run", {"job_id": job["id"]}).json()
        self.assertEqual(result["status"], "succeeded")
        preview = self.client.get(self.base + "/source-workspace/parse-jobs/" + job["id"] + "/preview").json()
        first = preview["proposal"]["scenes"][0]
        anchor = first["units"][0]["anchor_id"]
        self.assertEqual(self.client.get(self.base + "/source-workspace/anchors/" + anchor).status_code, 200)
        payload = {"job_id": job["id"], "attempt_id": result["attempt_id"]}
        self.assertEqual(self.post("source-workspace/prepare-import", payload).status_code, 422)
        prepared = self.post("source-workspace/prepare-import", payload, confirmed=True)
        self.assertEqual(prepared.status_code, 200, prepared.text)
        prepared = prepared.json()
        payload.update({"scene_mapping": prepared["scene_mapping"], "speaker_mapping": prepared["speaker_mapping"],
            "scope_key": prepared["scope_key"], "base_draft_revision": 0,
            "durations_ms": {s["key"]: 4000 for s in preview["proposal"]["scenes"]}})
        imported = self.post("source-workspace/import", payload)
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertFalse(imported.json()["automatic_approval"])
        draft = self.service.get_script_draft(self.p, prepared["scope_key"])
        self.assertTrue(draft["character_choices"])
        self.assertEqual(draft["character_choices"][0]["label"], "Alice")
        self.assertEqual(self.service.list_artifacts(self.p)["items"], [])
        for section in ("resources", "designs", "requirements", "locations"):
            response = self.client.get(self.base + "/resource-model", params={"section": section,
                "object_id": prepared["scope_key"]})
            self.assertEqual(response.status_code, 200, response.text)
        categories = self.client.get(self.base + "/resource-model/categories").json()["categories"]
        self.assertEqual(len([r for r in categories if not r["parent_code"]]), 11)

    def test_staged_docx_remains_controlled_manifest_and_missing_bytes_records_failure(self):
        from support.fixtures.source_intake import docx_bytes
        raw = docx_bytes()
        staged = self.client.post(self.base + "/uploads", content=raw,
            headers=dict(self.headers, **{"X-Filename": "script.docx"})).json()
        response = self.post("source-workspace/sources", {"title": "上传剧本", "intent": "screenplay",
            "staged_upload": staged["staged_upload"], "filename": "script.docx"})
        self.assertEqual(response.status_code, 200, response.text)
        source = response.json()
        fixed = self.service.get_source_version(self.p, source["id"])
        self.assertLess(fixed["content_size_bytes"], len(raw))
        self.assertEqual(len(fixed["media"]), 1)
        media = self.service.get_media(self.p, fixed["media"][0]["id"])
        for location in media["locations"]:
            if location["storage"] == "local":
                self.service.storage.resolve(location["object_key"]).unlink()
        job = self.post("source-workspace/parse-jobs", {"intent": "screenplay", "inputs": [
            {"source_id": source["id"], "source_sha256": source["sha256"]}]}).json()
        result = self.post("source-workspace/parse-jobs/run", {"job_id": job["id"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "failed")
        self.assertEqual(len(self.service.get_parse_job(self.p, job["id"])["attempts"]), 1)

    def test_write_session_and_unsafe_source_are_rejected(self):
        denied = self.client.post(self.base + "/source-workspace/sources", json={"payload": {}})
        self.assertEqual(denied.status_code, 403)
        response = self.post("source-workspace/sources", {"title": "bad", "intent": "screenplay",
            "content": "text", "path": "/etc/passwd"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "unsafe_source")

    def test_migration_roundtrip_matches_metadata(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import text
        from support.fixtures.postgres import isolated_postgres
        from vsc.bootstrap import repository_root
        from vsc.adapters.persistence.postgres.schema import metadata
        with isolated_postgres(TEST_URL) as engine:
            config = Config(str(repository_root() / "migrations/postgres/alembic.ini"))
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                command.downgrade(config, "0009_role_memory")
                self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0009_role_memory")
                command.upgrade(config, "head")
                self.assertEqual(conn.execute(text("SELECT count(*) FROM asset_categories WHERE parent_code IS NULL")).scalar_one(), 11)
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), metadata), [])

    def test_uploaded_encoded_text_is_preserved_until_explicit_decoding(self):
        for encoding, parameters in (("utf-16", {}), ("gbk", {"encoding": "gbk"})):
            with self.subTest(encoding=encoding):
                raw = "SC1\nAlice: 明天见。".encode(encoding)
                upload = self.client.post(self.base + "/uploads", content=raw,
                    headers=dict(self.headers, **{"X-Filename": "encoded.txt"})).json()
                source = self.post("source-workspace/sources", {"title": "编码来源", "intent": "screenplay",
                    "staged_upload": upload["staged_upload"], "filename": "encoded.txt"})
                self.assertEqual(source.status_code, 200, source.text)
                source = source.json()
                job = self.post("source-workspace/parse-jobs", {"intent": "screenplay", "inputs": [
                    {"source_id": source["id"], "source_sha256": source["sha256"]}], "parameters": parameters}).json()
                result = self.post("source-workspace/parse-jobs/run", {"job_id": job["id"]})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["status"], "succeeded")
                preview = self.service.preview_parse_job(self.p, job["id"])
                self.assertIn("明天见。", preview["extractions"][0]["text"])
