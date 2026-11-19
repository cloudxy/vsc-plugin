"""HTTP SSE resume and agent stream commands over the migrated store."""
import importlib.util
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires configured isolated PostgreSQL and web dependencies")
class CanvasAgentStreamWebTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app
        import tempfile
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.client = TestClient(create_app({
            "projects_root": self.directory.name + "/projects",
            "media_root": self.directory.name,
            "allowed_hosts": ["testserver"],
            "allowed_origins": ["http://testserver"],
            "human_identity": "test-human",
            "access_token": "test-token",
        }, service=self.service))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p
        created = self.command("/creative-canvases", {
            "title": "Agent 流",
            "document": {"nodes": [{"id": "n1", "type": "text", "title": "雨夜", "text": "追逐", "x": 40, "y": 50, "params": {}, "group": ""}], "edges": []},
        })
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.canvas = body["id"]
        self.canvas_revision = body["canvas_revision"]

    def command(self, path, payload, key=None):
        response = self.client.post(self.base + path, headers=self.headers, json={
            "payload": payload,
            "expected_revision": self.rev,
            "idempotency_key": key or uuid.uuid4().hex,
        })
        if response.status_code == 200:
            self.rev = response.json()["revision"]
        return response

    def stream(self, payload, key=None):
        return self.command("/creative-canvases/" + self.canvas + "/agent/stream", payload, key=key)

    def snapshot(self, **query):
        response = self.client.get(self.base + "/creative-canvases/" + self.canvas + "/agent/stream", headers=self.headers, params=query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_sse_frames_resume_from_last_event_id_and_json_poll(self):
        created = self.stream({"action": "create_session", "title": "雨夜会话"})
        self.assertEqual(created.status_code, 200, created.text)
        session_id = created.json()["session_id"]
        sent = self.stream({
            "action": "send", "session_id": session_id, "canvas_revision": self.canvas_revision,
            "message": "", "node_ids": ["n1"], "skill_id": "vsc-script",
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["disposition"], "started")
        self.assertFalse(sent.json()["provider_submitted"])
        observed = self.stream({
            "action": "observe", "session_id": session_id, "kind": "assistant_delta",
            "payload": {"text": "继续", "turn_id": sent.json()["turn_id"]},
        })
        self.assertEqual(observed.status_code, 200, observed.text)
        first_seq = created.json()["cursor"]
        headers = dict(self.headers, Accept="text/event-stream", **{"Last-Event-ID": str(first_seq)})
        resumed = self.client.get(self.base + "/creative-canvases/" + self.canvas + "/agent/events", headers=headers)
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertIn("text/event-stream", resumed.headers["content-type"])
        self.assertIn("event: heartbeat", resumed.text)
        self.assertIn("event: user_message", resumed.text)
        self.assertIn("请理解所引用的素材。", resumed.text)
        self.assertNotIn("id: " + str(first_seq) + "\n", resumed.text)
        replay = self.client.get(
            self.base + "/creative-canvases/" + self.canvas + "/agent/events",
            headers=dict(self.headers, Accept="text/event-stream", **{"Last-Event-ID": "not-a-cursor"}),
        )
        self.assertIn("id: " + str(first_seq) + "\n", replay.text)
        polled = self.client.get(
            self.base + "/creative-canvases/" + self.canvas + "/agent/events",
            headers=dict(self.headers, Accept="application/json"),
            params={"after": first_seq},
        )
        self.assertEqual(polled.status_code, 200, polled.text)
        self.assertIn("application/json", polled.headers["content-type"])
        self.assertTrue(all(event["seq"] > first_seq for event in polled.json()["events"]))
        self.assertGreaterEqual(polled.json()["cursor"], first_seq)
        page = self.snapshot()
        self.assertEqual(page["messages"][0]["text"], "请理解所引用的素材。")

    def test_session_controls_feedback_and_chinese_failure_text(self):
        first = self.stream({"action": "create_session", "title": "第一会话"}).json()
        second = self.stream({"action": "create_session", "title": "第二会话"})
        self.assertEqual(second.status_code, 200, second.text)
        selected = self.stream({"action": "select_session", "session_id": first["session_id"]})
        self.assertEqual(selected.json()["current_session_id"], first["session_id"])
        renamed = self.stream({"action": "rename_session", "session_id": first["session_id"], "title": "雨夜定稿"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["title"], "雨夜定稿")
        invalid = self.stream({"action": "rename_session", "session_id": first["session_id"], "title": "超" * 31})
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(invalid.json()["message"], "标题不能为空，且不能超过 30 个字符")
        sent = self.stream({
            "action": "send", "session_id": first["session_id"], "canvas_revision": self.canvas_revision,
            "message": "规划追逐", "skill_id": "vsc-script",
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        busy = self.stream({"action": "delete_session", "session_id": first["session_id"]})
        self.assertEqual(busy.status_code, 409, busy.text)
        self.assertEqual(busy.json()["message"], "正在执行中的会话不可删除")
        failed = self.stream({
            "action": "observe", "session_id": first["session_id"], "kind": "assistant_message",
            "payload": {"error": "TimeoutError", "turn_id": sent.json()["turn_id"]},
        })
        self.assertEqual(failed.status_code, 200, failed.text)
        snap = self.snapshot(session_id=first["session_id"])
        assistant = next(item for item in snap["messages"] if item["role"] == "assistant")
        self.assertEqual(assistant["error_text"], "回合执行失败")
        self.assertNotIn("Timeout", assistant["text"])
        liked = self.stream({"action": "feedback", "session_id": first["session_id"], "message_id": assistant["id"], "verdict": "up"})
        self.assertEqual(liked.status_code, 200, liked.text)
        again = self.snapshot(session_id=first["session_id"])
        self.assertEqual(next(item for item in again["messages"] if item["id"] == assistant["id"])["feedback"], "up")
        prefs = self.stream({
            "action": "set_prefs", "session_id": first["session_id"],
            "chat_model": "grok-fast", "reasoning_effort": "high", "selected_skill": "vsc-direct", "tier_seen": True,
        })
        self.assertEqual(prefs.status_code, 200, prefs.text)
        self.assertEqual(prefs.json()["prefs"]["chat_model"], "grok-fast")
        self.assertEqual(prefs.json()["prefs"]["selected_skill"], "vsc-direct")
        unknown_model = self.stream({"action": "set_prefs", "session_id": first["session_id"], "chat_model": "cloud-x"})
        self.assertEqual(unknown_model.status_code, 422)
        self.assertEqual(unknown_model.json()["message"], "对话模型不可用")

    def test_questions_tickets_steer_stop_and_batch_do_not_call_providers(self):
        session_id = self.stream({"action": "create_session", "title": "票据会话"}).json()["session_id"]
        sent = self.stream({
            "action": "send", "session_id": session_id, "canvas_revision": self.canvas_revision,
            "message": "先问再画", "skill_id": "vsc-script", "node_ids": ["n1"],
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        turn_id = sent.json()["turn_id"]
        asked = self.stream({
            "action": "observe", "session_id": session_id, "kind": "question_required",
            "payload": {"items": [{"id": "look", "kind": "single", "required": True, "prompt": "选光线", "options": [{"id": "neon", "label": "霓虹"}], "max_length": 20}], "turn_id": turn_id},
        })
        self.assertEqual(asked.status_code, 200, asked.text)
        batch_id = asked.json()["record_id"]
        rejected = self.stream({"action": "answer", "batch_id": batch_id, "version": 1, "answers": []})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["message"], "请回答所有必答问题")
        answered = self.stream({
            "action": "answer", "batch_id": batch_id, "version": 1,
            "answers": [{"question_id": "look", "selected_option_ids": ["neon"], "custom_text": ""}],
        })
        self.assertEqual(answered.status_code, 200, answered.text)
        self.assertEqual(answered.json()["question_batch"]["status"], "answered")
        expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        paid = []
        for name, credits in (("生图", 2), ("生视频", 5)):
            ticket = self.stream({
                "action": "observe", "session_id": session_id, "kind": "authorization_required",
                "payload": {
                    "ticket_type": "paid", "operation": name, "model": "seedream", "unit_price": credits,
                    "quantity": 1, "total_credits": credits, "canvas_version": self.canvas_revision, "expires_at": expires,
                },
            })
            self.assertEqual(ticket.status_code, 200, ticket.text)
            paid.append(ticket.json()["record_id"])
        deleted = self.stream({
            "action": "observe", "session_id": session_id, "kind": "authorization_required",
            "payload": {
                "ticket_type": "delete", "canvas_version": self.canvas_revision, "node_count": 1,
                "node_list": [{"id": "n1", "title": "雨夜"}], "cascade_edge_count": 0, "expires_at": expires,
            },
        })
        batch = self.stream({"action": "authorize_batch", "session_id": session_id})
        self.assertEqual(batch.status_code, 200, batch.text)
        self.assertEqual(sorted(item["authorization_id"] for item in batch.json()["results"]), sorted(paid))
        self.assertTrue(all(item["status"] == "approved" for item in batch.json()["results"]))
        approved = self.stream({"action": "authorize", "authorization_id": deleted.json()["record_id"], "approve": True})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["node_ids"], ["n1"])
        self.assertFalse(approved.json()["provider_submitted"])
        canvas = self.client.get(self.base + "/creative-canvases/" + self.canvas, headers=self.headers)
        self.assertEqual([node["id"] for node in canvas.json()["document"]["nodes"]], ["n1"])
        queued = self.stream({
            "action": "send", "session_id": session_id, "canvas_revision": self.canvas_revision,
            "message": "插队改成近景", "skill_id": "vsc-script", "node_ids": ["n1"],
        })
        self.assertEqual(queued.json()["disposition"], "queued")
        steered = self.stream({
            "action": "steer", "session_id": session_id, "queue_item_id": queued.json()["queue_id"],
            "expected_active_turn_id": turn_id,
        })
        self.assertEqual(steered.status_code, 200, steered.text)
        self.assertEqual(steered.json()["canceled_turn_id"], turn_id)
        self.assertNotEqual(steered.json()["successor_turn_id"], turn_id)
        stopped = self.stream({"action": "stop", "session_id": session_id, "turn_id": steered.json()["successor_turn_id"]})
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertTrue(stopped.json()["stopped"])
        receipt = self.stream({
            "action": "action_event", "session_id": session_id, "event": "frontend_action_completed",
            "action_id": "arrange_selected", "focus_ids": ["n1"], "message": "整理选中节点布局",
        })
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["focus_ids"], ["n1"])
        removed = self.stream({"action": "delete_session", "session_id": session_id})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertTrue(removed.json()["deleted"])
        self.assertEqual(self.snapshot()["sessions"], [])
