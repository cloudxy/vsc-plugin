"""Real PostgreSQL trash decisions, protection, shared bytes and HTTP boundaries."""
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit PostgreSQL test URL")
class MediaRecycleTests(ResourceStoreFixture, unittest.TestCase):
    def test_same_blob_registers_remain_distinct_and_restore_does_not_select(self):
        a, b = self.media("duplicate"), self.media("duplicate")
        original, revision = self.p, self.rev
        self.p = self.service.create_project({"name": "another work"}, actor="test-human")["id"]
        self.rev = 0
        other_media = self.media("duplicate")
        other_project = self.p
        self.p, self.rev = original, revision
        groups = self.service.list_recycled_media(self.p, view="duplicates")
        self.assertEqual(groups["total"], 1)
        self.assertEqual({item["id"] for item in groups["items"][0]["items"]}, {a, b})
        payload = {"media_ids": [a], "action": "trash", "reason": "remove redundant registration"}
        revision = self.rev
        result = self.write("recycle_media", payload, idempotency_key="trash-once")
        self.assertEqual(result["items"][0]["status"], "trashed")
        replay = self.service.recycle_media(self.p, payload, actor="test-human",
            expected_revision=revision, idempotency_key="trash-once")
        self.assertEqual(replay, result)
        self.assertEqual([x["id"] for x in self.service.list_resources(self.p)["items"]], [b])
        trash = self.service.list_recycled_media(self.p)
        self.assertEqual(trash["released_bytes"], 0)
        self.assertEqual(trash["items"][0]["id"], a)
        self.assertEqual(self.service.get_media(self.p, a)["sha256"],
                         self.service.get_media(self.p, b)["sha256"])
        self.assertFalse(self.service.get_media(other_project, other_media)["deprecated"])
        self.assertEqual(self.service.list_resources(other_project)["total"], 1)
        restored = self.write("recycle_media", dict(payload, action="restore"))
        self.assertEqual(restored["items"][0]["status"], "restored")
        self.assertEqual(self.service.list_recycled_media(self.p)["total"], 0)
        self.assertEqual(self.service.list_resources(self.p)["total"], 2)

    def test_selected_and_fixed_inputs_protected_with_partial_batch_and_cross_project(self):
        objects = self.hierarchy()
        selected, spare = self.media("selected"), self.media("spare")
        candidate = self.candidate(objects["shot"], selected)
        self.select(candidate)
        preview = self.service.preview_media_recycle(self.p, [selected, spare])
        self.assertTrue(preview["items"][0]["protected"])
        self.assertFalse(preview["items"][1]["protected"])
        result = self.write("recycle_media", {"media_ids": [selected, spare], "action": "trash", "reason": "cleanup"})
        self.assertEqual([r["status"] for r in result["items"]], ["protected", "trashed"])
        self.assertEqual(self.service.get_media(self.p, selected)["deprecated"], False)
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        with self.assertRaises(ResourceError):
            self.service.recycle_media(other, {"media_ids": [spare], "action": "restore", "reason": "cross"},
                actor="test-human", expected_revision=0, idempotency_key="cross")
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            self.assertIsNotNone(conn.execute(select(S.current_bindings).where(
                S.current_bindings.c.project_id == self.p,
                S.current_bindings.c.candidate_id == candidate["candidate_id"])).first())

    def test_http_session_bootstrap_readonly_confirmation_and_create_replay(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        with tempfile.TemporaryDirectory() as root:
            config = {"projects_root": root, "allowed_hosts": ["testserver"],
                      "allowed_origins": ["http://testserver"], "access_token": "ordinary-token",
                      "human_identity": "test-human", "bootstrap_token": "one-use"}
            with TestClient(create_app(config, service=self.service), client=("127.0.0.1", 50000)) as client:
                url = "/api/v1/session/bootstrap"
                self.assertEqual(client.post(url, json={"token": "one-use"}).status_code, 403)
                session = client.post(url, headers={"Origin": "http://testserver"}, json={"token": "one-use"})
                self.assertEqual(session.status_code, 200, session.text)
                self.assertTrue(session.json()["write_available"])
                self.assertIn("HttpOnly", session.headers["set-cookie"])
                self.assertEqual(client.post(url, headers={"Origin": "http://testserver"},
                                             json={"token": "one-use"}).status_code, 403)
                headers = {"Origin": "http://testserver", "X-CSRF-Token": session.json()["csrf_token"]}
                body = {"payload": {"name": "new work"}, "idempotency_key": "create-once"}
                first = client.post("/api/v1/projects", headers=headers, json=body)
                again = client.post("/api/v1/projects", headers=headers, json=body)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.json(), again.json())
                changed = client.post("/api/v1/projects", headers=headers,
                    json=dict(body, payload={"name": "different work"}))
                self.assertEqual(changed.status_code, 409)
                media = self.media("http-spare")
                endpoint = f"/api/v1/projects/{self.p}/recycle-actions"
                action = {"payload": {"media_ids": [media], "action": "trash", "reason": "cleanup"},
                          "expected_revision": self.rev, "idempotency_key": uuid.uuid4().hex}
                self.assertEqual(client.post(endpoint, headers=headers, json=action).status_code, 422)
                result = client.post(endpoint, headers=headers, json=dict(action, confirmed=True))
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["items"][0]["status"], "trashed")
                receipt_url = f"/api/v1/projects/{self.p}/operation-receipts/{action['idempotency_key']}"
                self.assertEqual(client.get(receipt_url).status_code, 403)
                receipt = client.get(receipt_url, headers={"X-CSRF-Token": session.json()["csrf_token"]})
                self.assertEqual(receipt.json()["response"], result.json())
                self.assertFalse(self.service.get_operation_receipt(
                    self.p, action["idempotency_key"], actor="another-person")["found"])
            readonly = dict(config, access_token=None, human_identity=None)
            with TestClient(create_app(readonly, service=self.service), client=("127.0.0.1", 50000)) as client:
                self.assertEqual(client.post(url, headers={"Origin": "http://testserver"},
                                             json={"token": "one-use"}).status_code, 403)
            from unittest.mock import patch
            expired_app = create_app(config, service=self.service)
            with TestClient(expired_app, client=("127.0.0.1", 50000)) as client:
                with patch("vsc.interfaces.web.app.time.monotonic", return_value=10**15):
                    self.assertEqual(client.post(url, headers={"Origin": "http://testserver"},
                                                 json={"token": "one-use"}).status_code, 403)
            with TestClient(create_app(config, service=self.service), client=("198.51.100.1", 50000)) as client:
                self.assertEqual(client.post(url, headers={"Origin": "http://testserver"},
                                             json={"token": "one-use"}).status_code, 403)
