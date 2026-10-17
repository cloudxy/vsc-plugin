"""Panel authority, media boundary, browser rendering and trusted write contracts."""
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from support.paths import ROOT

from vsc.project.resource_catalog import ResourceCatalog

HAS_WEB = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
if HAS_WEB:
    from fastapi.testclient import TestClient
    from vsc.interfaces.web.app import create_app


@unittest.skipUnless(HAS_WEB, "requires optional web/test dependencies")
class ResourcePanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.text = self.project / "script.md"
        self.text.write_text('他说：“放下吧。”\n\n' + '一段较长文案，标点应当自然换行。' * 40 + '<script>alert(1)</script>', encoding="utf-8")
        self.media = self.project / "take.mp4"
        self.media.write_bytes(b"0123456789abcdef")
        self.state = {"project_id": "project-a", "title": "测试项目", "profile_id": "vsc.light-short", "revision": 4,
                      "profile_snapshot": {}, "objects": [{"id": "EP1", "kind": "episode", "label": "第一集", "parent": None},
                                                          {"id": "SH1", "kind": "shot", "label": "第一镜", "parent": "EP1", "artifact": "script-v1"}],
                      "artifacts": [{"id": "script-v1", "type": "vsc.screenplay", "path": "script.md", "status": "approved",
                                     "sha256": hashlib.sha256(self.text.read_bytes()).hexdigest(), "scope": ["EP1"]}]}
        self.save()
        self.catalog = ResourceCatalog(self.root)
        self.client = TestClient(create_app({"allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"]}, catalog=self.catalog))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def save(self):
        (self.project / "vsc.json").write_text(json.dumps(self.state), encoding="utf-8")

    def test_legacy_tree_and_document_preserve_real_relationships(self):
        tree = self.client.get("/api/v1/projects/project-a/tree").json()
        self.assertEqual(tree["nodes"][1]["parent_id"], "EP1")
        result = self.client.get("/api/v1/projects/project-a/artifacts?object_id=SH1").json()
        self.assertEqual([row["id"] for row in result["items"]], ["script-v1"])
        content = self.client.get("/api/v1/projects/project-a/artifacts/script-v1").json()
        self.assertIn("<script>", content["content"])
        html = self.client.get("/")
        self.assertNotIn("<script>alert", html.text)
        script = self.client.get("/static/panel.js").text
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)
        self.assertIn("frame-ancestors 'none'", html.headers["content-security-policy"])

    def test_inventory_is_unregistered_and_never_assigned_by_filename(self):
        response = self.client.get("/api/v1/projects/project-a/media")
        rows = response.json()["items"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["registered"])
        self.assertEqual(rows[0]["bindings"], [])
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media?object_id=SH1").json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media?status=deprecated").json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media?status=unselected").json()["total"], 1)
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media?object_id=missing").status_code, 404)

    def test_media_range_and_path_boundary(self):
        media_id = self.catalog.resources("project-a")["items"][0]["id"]
        response = self.client.get(f"/api/v1/projects/project-a/media/{media_id}/content", headers={"Range": "bytes=2-5"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"2345")
        outside = self.root / "private.mp4"
        outside.write_bytes(b"private")
        (self.project / "linked.mp4").symlink_to(outside)
        self.assertEqual(self.catalog.resources("project-a")["total"], 1)
        self.assertEqual(self.client.get("/api/v1/projects/project-a/media/../../private/content").status_code, 404)
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example"}).status_code, 403)

    def test_etag_and_changed_artifact_are_visible(self):
        response = self.client.get("/api/v1/projects/project-a/artifacts")
        self.assertEqual(self.client.get("/api/v1/projects/project-a/artifacts", headers={"If-None-Match": response.headers["etag"]}).status_code, 304)
        self.text.write_text("修改过的批准文件", encoding="utf-8")
        changed = self.client.get("/api/v1/projects/project-a/artifacts").json()
        self.assertEqual(changed["items"][0]["integrity"], "mismatch")
        self.text.unlink()
        missing = self.client.get("/api/v1/projects/project-a/artifacts").json()
        self.assertEqual(missing["items"][0]["availability"], "missing")

    def test_declared_postgres_authority_never_falls_back(self):
        self.state["profile_snapshot"]["storage_policy"] = "postgres-series-v1"
        self.save()
        response = self.client.get("/api/v1/projects/project-a/tree")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "authority_unavailable")
        self.assertTrue(self.client.get("/api/v1/projects").json()["items"][0]["unavailable"])

    def test_cutover_pointer_takes_precedence_over_legacy_mirror(self):
        (self.project / ".vsc-postgres.json").write_text(json.dumps({"project_id": "project-a", "storage_policy": "postgres-series-v1", "database_env": "VSC_DATABASE_URL"}), encoding="utf-8")
        self.assertEqual(self.client.get("/api/v1/projects/project-a/tree").status_code, 409)
        self.assertEqual(self.client.get("/api/v1/projects").json()["items"][0]["storage_policy"], "postgres-series-v1")

    def test_sqlite_reads_canonical_document_even_when_mirror_has_changed(self):
        self.state["profile_snapshot"]["storage_policy"] = "sqlite-series-v1"
        self.save()
        canonical = json.dumps(self.state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.project / ".vsc-series.sqlite3") as connection:
            connection.executescript("PRAGMA user_version=1; CREATE TABLE project_state(singleton INTEGER, payload TEXT, sha256 TEXT); CREATE TABLE artifact_versions(id TEXT, document BLOB, sha256 TEXT);")
            content = self.text.read_bytes()
            connection.execute("INSERT INTO project_state VALUES(1,?,?)", (canonical, hashlib.sha256(canonical.encode()).hexdigest()))
            connection.execute("INSERT INTO artifact_versions VALUES(?,?,?)", ("script-v1", content, hashlib.sha256(content).hexdigest()))
        self.text.write_text("镜像变化不能覆盖权威", encoding="utf-8")
        response = self.client.get("/api/v1/projects/project-a/artifacts/script-v1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("他说", response.json()["content"])
        self.assertEqual(response.json()["integrity"], "verified")

    def test_write_identity_csrf_revision_and_explicit_confirmation(self):
        class Service:
            def select_candidate(self, project_id, payload, **kwargs):
                if kwargs["expected_revision"] != 8:
                    from vsc.adapters.persistence.legacy_json.panel import CatalogError
                    raise CatalogError("版本冲突", 409, "revision_conflict")
                self.call = (project_id, payload, kwargs)
                return {"revision": 9}
        service = Service()
        class Catalog:
            def __init__(self): self.service = service
            def write(self, action, project_id, payload, **kwargs): return getattr(self.service, action)(project_id, payload, **kwargs)
        client = TestClient(create_app({"allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"], "human_identity": "实际审片人", "access_token": "local-token"}, catalog=Catalog()))
        body = {"payload": {"candidate_id": "c1", "reason": "已比较"}, "expected_revision": 8, "idempotency_key": "once", "confirmed": True}
        url = "/api/v1/projects/p1/binding-decisions"
        self.assertEqual(client.post(url, json=body).status_code, 403)
        self.assertEqual(client.post("/api/v1/session", json={"token": "local-token"}, headers={"Origin": "http://evil"}).status_code, 403)
        login = client.post("/api/v1/session", json={"token": "local-token"}, headers={"Origin": "http://testserver"})
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
        self.assertEqual(client.post(url, json={**body, "actor": "伪造"}, headers=headers).status_code, 422)
        self.assertEqual(client.post(url, json={**body, "confirmed": False}, headers=headers).status_code, 422)
        self.assertEqual(client.post(url, json={**body, "expected_revision": 7}, headers=headers).status_code, 409)
        self.assertEqual(client.post(url, json=body, headers=headers).status_code, 200)
        self.assertEqual(service.call[2]["actor"], "实际审片人")
        self.assertEqual(service.call[2]["idempotency_key"], "once")
        client.close()

    def test_postgres_bytes_require_controlled_location_and_hash(self):
        media_root = self.root / "blob-store"
        media_root.mkdir()
        blob = media_root / "blob.bin"
        blob.write_bytes(b"<html><script>alert(1)</script></html>")
        record = {"id": "media-a", "name": "test", "mime_type": "text/html", "modality": "image",
                  "sha256": hashlib.sha256(blob.read_bytes()).hexdigest(), "locations": [{"storage": "local", "object_key": "blob.bin"}],
                  "created_at": datetime.now(timezone.utc), "blob_id": uuid4()}
        class Service:
            def get_media(self, project_id, media_id): return record
            def get_media_usage(self, project_id, media_id):
                return {"job_outputs": [{"media_id": media_id, "original_uri": "https://temporary.example/private-signed-token"}]}
        catalog = ResourceCatalog(self.root / "empty-projects", Service(), media_root=media_root)
        client = TestClient(create_app({"allowed_hosts": ["testserver"]}, catalog=catalog))
        self.assertEqual(client.get("/api/v1/projects/p/media/media-a").status_code, 200)
        response = client.get("/api/v1/projects/p/media/media-a/content")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        usage = client.get("/api/v1/projects/p/media/media-a/usage").json()
        self.assertNotIn("original_uri", usage["job_outputs"][0])
        self.assertTrue(usage["job_outputs"][0]["original_uri_archived"])
        blob.write_bytes(b"changed")
        self.assertEqual(client.get("/api/v1/projects/p/media/media-a/content").status_code, 409)
        record["locations"][0]["object_key"] = "../private.txt"
        self.assertEqual(client.get("/api/v1/projects/p/media/media-a/content").status_code, 403)
        client.close()

    def test_upload_and_registration_use_storage_verified_bytes(self):
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        class Store:
            def get_project_tree(self, project_id):
                return {"project": {"id": project_id, "storage_policy": "postgres-series-v1"}, "revision": 0, "nodes": []}
            def register_media(self, project_id, payload, **kw):
                self.call = (project_id, payload, kw)
                return {"id": "m1", "revision": 1}
        store = Store()
        storage = LocalStorage(self.root / "storage", max_bytes=100)
        service = ResourceService(store, storage=storage)
        catalog = ResourceCatalog(self.root / "empty-projects", service, media_root=storage.root)
        client = TestClient(create_app({"allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"], "human_identity": "实际操作者", "access_token": "token"}, catalog=catalog))
        login = client.post("/api/v1/session", json={"token": "token"}, headers={"Origin": "http://testserver"}).json()
        headers = {"Origin": "http://testserver", "X-CSRF-Token": login["csrf_token"], "X-Filename": "notes.txt"}
        upload = client.post("/api/v1/projects/p/uploads", content="真实字节".encode(), headers=headers)
        self.assertEqual(upload.status_code, 200)
        body = {"expected_revision": 0, "idempotency_key": "register-1", "payload": {"sha256": "forged", "object_key": "../private"}}
        self.assertEqual(client.post("/api/v1/projects/p/media", json=body, headers=headers).status_code, 422)
        body["payload"]["staged_upload"] = upload.json()["staged_upload"]
        body["payload"]["name"] = "镜头旁白·第一版"
        self.assertEqual(client.post("/api/v1/projects/p/media", json=body, headers=headers).status_code, 200)
        self.assertEqual(store.call[1]["sha256"], hashlib.sha256("真实字节".encode()).hexdigest())
        self.assertEqual(store.call[1]["name"], "镜头旁白·第一版")
        self.assertTrue(store.call[1]["object_key"].startswith("blobs/"))
        self.assertEqual(client.post("/api/v1/projects/p/uploads", content=b"x" * 101, headers=headers).status_code, 413)
        client.close()

    def test_application_lifespan_checks_schema_and_closes_owned_pool(self):
        calls = []
        class Store:
            def check_schema(self): calls.append("schema_checked")
            def close(self): calls.append("pool_closed")
        class Service:
            store = Store()
        class Catalog:
            service = Service()
        with TestClient(create_app({"allowed_hosts": ["testserver"], "close_service_on_shutdown": True}, catalog=Catalog())) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(calls, ["schema_checked"])
        self.assertEqual(calls, ["schema_checked", "pool_closed"])


if __name__ == "__main__":
    unittest.main()
