"""Script working copy, human confirmation hard stop and notes against real PostgreSQL."""
import importlib.util
import unittest
import uuid

import support.paths  # noqa: F401 - put src on sys.path before vsc imports
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError

SCREENPLAY_TYPES = ["vsc.screenplay"]


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit test PostgreSQL URL and dependencies")
class ScriptWorkspaceFlow(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        self.project = self.service.create_project({"name": "剧本工作区测试", "profile_snapshot": {
            "profile_id": "vsc.synthetic-script", "version": "1", "dependency_policy": "previous_stage",
            "stages": [{"id": "script", "required": ["screenplay"]},
                       {"id": "design", "required": ["asset-bible"]},
                       {"id": "animatic", "required": ["animatic"]}]}}, actor="test-human")
        self.p, self.rev = self.project["id"], 0
        self.objects = self.hierarchy()
        self.episode = self.objects["episode"]

    def draft_document(self, line="今晚我等你"):
        return {"scenes": [{"id": "SC1", "estimated_duration_ms": 4000,
                            "actions": [{"id": "A1", "text": "他停下脚步"}],
                            "dialogue": [{"id": "L1", "speaker": "char", "text": line}],
                            "silence": []}]}

    def bible_payload(self):
        return dict(artifact_key="bible", artifact_type="asset-bible", stage="design",
                    document={"synthetic": True}, object_ids=[self.episode])

    def test_autosave_never_creates_formal_versions(self):
        before = self.service.get_project(self.p)["revision"]
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 0,
                                                "content": self.draft_document()}, actor="editor-a")
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1,
                                                "content": self.draft_document("明天再来")}, actor="editor-a")
        self.assertEqual(self.service.get_project(self.p)["revision"], before)
        self.assertEqual(self.service.list_artifacts(self.p)["items"], [])
        draft = self.service.get_script_draft(self.p, self.episode)
        self.assertEqual((draft["phase"], draft["draft_revision"]), ("editing", 2))
        self.assertEqual(draft["content"]["scenes"][0]["dialogue"][0]["text"], "明天再来")

    def test_stale_revision_conflict_keeps_latest(self):
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 0,
                                                "content": self.draft_document()}, actor="editor-a")
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1,
                                                "content": self.draft_document()}, actor="editor-b")
        with self.assertRaises(ResourceError) as caught:
            self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1,
                                                    "content": self.draft_document("过期写入")}, actor="editor-a")
        self.assertEqual("draft_revision_conflict", caught.exception.code)
        self.assertIn("r2", caught.exception.message)
        draft = self.service.get_script_draft(self.p, self.episode)
        self.assertEqual(draft["content"]["scenes"][0]["dialogue"][0]["text"], "今晚我等你")

    def test_submit_confirmation_gate_and_design_blocking(self):
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", self.bible_payload())
        self.assertEqual("script_confirmation_required", caught.exception.code)
        saved = self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 0,
                                                        "content": self.draft_document()}, actor="editor-a")
        submitted = self.write("submit_script_draft", {"scope_key": self.episode,
            "base_draft_revision": saved["draft_revision"], "artifact_type": "screenplay", "stage": "script"})
        artifact_id = submitted["artifact"]["id"]
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["phase"], "pending")
        with self.assertRaises(ResourceError) as caught:  # 已提交但未批准仍然阻断
            self.write("create_artifact", self.bible_payload())
        self.assertEqual("script_confirmation_required", caught.exception.code)
        self.write("decide_artifact", {"artifact_id": artifact_id, "reason": "synthetic human approval"})
        draft = self.service.get_script_draft(self.p, self.episode)
        self.assertEqual(draft["phase"], "approved")
        self.assertEqual(draft["base"], None)  # 基线推导自提交版本，不另写事实
        bible = self.write("create_artifact", self.bible_payload())
        self.assertTrue(bible["id"])

    def test_resubmit_after_reject_and_compare(self):
        saved = self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 0,
                                                        "content": self.draft_document()}, actor="editor-a")
        first = self.write("submit_script_draft", {"scope_key": self.episode,
            "base_draft_revision": saved["draft_revision"], "artifact_type": "screenplay", "stage": "script"})
        self.write("decide_artifact", {"artifact_id": first["artifact"]["id"], "outcome": "reject", "reason": "台词动机不足"})
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["phase"], "rejected")
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": saved["draft_revision"],
                                                "content": self.draft_document("今晚我等你，不见不散")}, actor="editor-a")
        second = self.write("submit_script_draft", {"scope_key": self.episode,
            "base_draft_revision": saved["draft_revision"] + 1, "artifact_type": "screenplay", "stage": "script"})
        self.assertEqual(second["artifact"]["version"], 2)
        compare = self.service.compare_script_draft(self.p, self.episode, base_artifact_id=first["artifact"]["id"])
        self.assertTrue(compare["changes"]["changed"])
        texts = [row for row in compare["changes"]["lines"] if row.get("field") == "text"]
        self.assertEqual((texts[0]["before"], texts[0]["after"]), ("今晚我等你", "今晚我等你，不见不散"))

    def test_notes_anchor_and_decisions(self):
        note = self.write("add_script_note", {"scene_id": "SC1", "line_id": "L1", "body": "这句要口语一些"})
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["notes"][0]["status"], "open")
        self.write("decide_script_note", {"note_id": note["id"], "outcome": "resolve", "reason": "已改写"})
        row = self.service.get_script_draft(self.p, self.episode)["notes"][0]
        self.assertEqual((row["status"], row["decision"]["outcome"]), ("resolved", "resolve"))
        self.write("decide_script_note", {"note_id": note["id"], "outcome": "reopen", "reason": "复看后仍不稳"})
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["notes"][0]["status"], "open")

    def test_project_wide_design_waits_for_project_wide_confirmation(self):
        self.service.save_script_draft(self.p, {"scope_key": "", "base_draft_revision": 0,
                                                "content": self.draft_document()}, actor="editor-a")
        saved = self.service.get_script_draft(self.p, "")
        submitted = self.write("submit_script_draft", {"scope_key": "", "base_draft_revision": saved["draft_revision"],
                                                       "artifact_type": "screenplay", "stage": "script"})
        with self.assertRaises(ResourceError) as caught:  # 已提交未批准的项目级剧本不放行项目级 design
            self.write("create_artifact", dict(artifact_key="wide", artifact_type="asset-bible", stage="design",
                                               document={"synthetic": True}, project_wide=True))
        self.assertEqual("script_confirmation_required", caught.exception.code)
        self.write("decide_artifact", {"artifact_id": submitted["artifact"]["id"], "reason": "synthetic human approval"})
        row = self.write("create_artifact", dict(artifact_key="wide", artifact_type="asset-bible", stage="design",
                                                 document={"synthetic": True}, project_wide=True))
        self.assertTrue(row["id"])


API_DEPS = HAS_DB_DEPS and TEST_URL and all(importlib.util.find_spec(name)
                                            for name in ("fastapi", "httpx"))


@unittest.skipUnless(API_DEPS, "requires explicit PostgreSQL test URL and web dependencies")
class ScriptWorkspaceAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        cls.database = isolated_postgres(TEST_URL)
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from fastapi.testclient import TestClient
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.interfaces.web.app import create_app
        self.service = ResourceService(PostgresResourceStore(engine=self.engine))
        self.project = self.service.create_project({"name": "剧本工作区API", "profile_snapshot": {
            "profile_id": "vsc.synthetic-script", "version": "1",
            "stages": [{"id": "script", "required": ["screenplay"]},
                       {"id": "design", "required": ["asset-bible"]}]}}, actor="fixture-human")
        self.p, self.revision = self.project["id"], 0
        self.client = TestClient(create_app({"projects_root": "empty-projects",
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "human_identity": "fixture-human", "access_token": "fixture-token"}, service=self.service))
        self.client.__enter__()
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"},
                                   json={"token": "fixture-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def write(self, endpoint, payload, status=200, confirmed=False):
        response = self.client.post(self.base + "/" + endpoint, headers=self.headers,
            json={"payload": payload, "expected_revision": self.revision, "idempotency_key": uuid.uuid4().hex,
                  "confirmed": confirmed})
        self.assertEqual(response.status_code, status, response.text)
        result = response.json()
        if status == 200:
            self.revision = result["revision"]
        return result

    def test_session_autosave_submit_confirm_and_gate_over_http(self):
        content = {"scenes": [{"id": "SC1", "estimated_duration_ms": 3000, "actions": [],
                               "dialogue": [{"id": "L1", "speaker": "char", "text": "今晚我等你"}], "silence": []}]}
        denied = self.client.post(self.base + "/script-draft/autosave", headers={"Origin": "http://testserver"},
                                  json={"payload": {"scope_key": "", "base_draft_revision": 0, "content": content}})
        self.assertEqual(denied.status_code, 403)
        saved = self.client.post(self.base + "/script-draft/autosave", headers=self.headers,
                                 json={"payload": {"scope_key": "", "base_draft_revision": 0, "content": content}})
        self.assertEqual(saved.status_code, 200, saved.text)
        draft = self.client.get(self.base + "/script-draft").json()
        self.assertEqual((draft["phase"], draft["draft_revision"]), ("editing", 1))
        blocked = self.write("artifacts", {"artifact_key": "wide", "artifact_type": "asset-bible", "stage": "design",
                                           "document": {"synthetic": True}, "project_wide": True}, status=409)
        self.assertEqual(blocked["error"], "script_confirmation_required")
        submitted = self.write("script-submit", {"scope_key": "", "base_draft_revision": 1,
                                                 "artifact_type": "screenplay", "stage": "script"})
        artifact_id = submitted["artifact"]["id"]
        unconfirmed = self.client.post(self.base + "/artifact-decisions", headers=self.headers,
            json={"payload": {"artifact_id": artifact_id, "outcome": "approve", "reason": "未确认提交"},
                  "expected_revision": self.revision, "idempotency_key": uuid.uuid4().hex})
        self.assertEqual(unconfirmed.status_code, 422)
        self.write("artifact-decisions", {"artifact_id": artifact_id, "outcome": "approve", "reason": "HTTP 确认"},
                   status=200, confirmed=True)
        self.assertEqual(self.client.get(self.base + "/script-draft").json()["phase"], "approved")
        opened = self.write("artifacts", {"artifact_key": "wide", "artifact_type": "asset-bible", "stage": "design",
                                          "document": {"synthetic": True}, "project_wide": True})
        self.assertTrue(opened["id"])
        compare = self.client.get(self.base + "/script-draft/compare").json()
        self.assertFalse(compare["changes"]["changed"])


if __name__ == "__main__":
    unittest.main()
