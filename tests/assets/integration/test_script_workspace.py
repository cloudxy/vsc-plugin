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
            "stages": [{"id": "script", "required": ["screenplay", "vsc.screenplay"]},
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
        self.assertEqual((draft["base"] or {}).get("id"), artifact_id)  # 已批准基线（含只读派生）指向该版本
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
        note = self.write("add_script_note", {"scope_key": self.episode, "scene_id": "SC1", "line_id": "L1",
                                              "body": "这句要口语一些"})
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["notes"][0]["status"], "open")
        self.write("decide_script_note", {"note_id": note["id"], "outcome": "resolve", "reason": "已改写"})
        row = self.service.get_script_draft(self.p, self.episode)["notes"][0]
        self.assertEqual((row["status"], row["decision"]["outcome"]), ("resolved", "resolve"))
        self.write("decide_script_note", {"note_id": note["id"], "outcome": "reopen", "reason": "复看后仍不稳"})
        self.assertEqual(self.service.get_script_draft(self.p, self.episode)["notes"][0]["status"], "open")

    def test_hard_stop_closes_bypasses_and_pending_revision(self):
        episode_a = self.objects["episode"]
        episode_b = self.write("create_object", {"kind": "episode", "display_code": "EP2",
                                                 "parent_id": self.objects["work"], "ordinal": 1})["id"]
        # F05-1：伪造 stage=script 不能改变类型→阶段归属
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", dict(artifact_key="lie", artifact_type="asset-bible", stage="script",
                                               document={"synthetic": True}, object_ids=[episode_a]))
        self.assertEqual("script_confirmation_required", caught.exception.code)
        saved = self.service.save_script_draft(self.p, {"scope_key": episode_a, "base_draft_revision": 0,
                                                        "content": self.draft_document()}, actor="editor-a")
        # F05-2：script-submit 不接受非剧本类型
        with self.assertRaises(ResourceError) as caught:
            self.write("submit_script_draft", {"scope_key": episode_a, "base_draft_revision": saved["draft_revision"],
                                               "artifact_type": "asset-bible", "stage": "script"})
        self.assertEqual("invalid_artifact_type", caught.exception.code)
        # F04：提交必须携带准确 draft_revision
        with self.assertRaises(ResourceError) as caught:
            self.write("submit_script_draft", {"scope_key": episode_a, "artifact_type": "screenplay", "stage": "script"})
        self.assertEqual("draft_revision_conflict", caught.exception.code)
        first = self.write("submit_script_draft", {"scope_key": episode_a,
            "base_draft_revision": saved["draft_revision"], "artifact_type": "screenplay", "stage": "script"})
        self.write("decide_artifact", {"artifact_id": first["artifact"]["id"], "reason": "synthetic human approval"})
        # F05-3/4：范围逐一覆盖——仅 A 批准时 B、A+B、项目级一律拒绝
        self.assertTrue(self.write("create_artifact", dict(artifact_key="a-ok", artifact_type="asset-bible",
            stage="design", document={"synthetic": True}, object_ids=[episode_a]))["id"])
        for payload in (dict(artifact_key="b-no", artifact_type="asset-bible", stage="design",
                             document={"synthetic": True}, object_ids=[episode_b]),
                        dict(artifact_key="ab-no", artifact_type="asset-bible", stage="design",
                             document={"synthetic": True}, object_ids=[episode_a, episode_b]),
                        dict(artifact_key="wide-no", artifact_type="asset-bible", stage="design",
                             document={"synthetic": True}, project_wide=True)):
            with self.assertRaises(ResourceError) as caught:
                self.write("create_artifact", payload)
            self.assertEqual("script_confirmation_required", caught.exception.code)
        # F06：待审修订阻断受影响新制作；退回后恢复
        self.service.save_script_draft(self.p, {"scope_key": episode_a,
            "base_draft_revision": saved["draft_revision"],
            "content": self.draft_document("今晚我等你，不见不散")}, actor="editor-a")
        second = self.write("submit_script_draft", {"scope_key": episode_a,
            "base_draft_revision": saved["draft_revision"] + 1, "artifact_type": "screenplay", "stage": "script"})
        self.assertEqual(second["artifact"]["artifact_key"], first["artifact"]["artifact_key"])  # 同一 stream
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", dict(artifact_key="a-pending", artifact_type="asset-bible", stage="design",
                                               document={"synthetic": True}, object_ids=[episode_a]))
        self.assertEqual("script_revision_pending", caught.exception.code)
        self.write("decide_artifact", {"artifact_id": second["artifact"]["id"], "outcome": "reject", "reason": "台词动机不足"})
        self.assertTrue(self.write("create_artifact", dict(artifact_key="a-resumed", artifact_type="asset-bible",
            stage="design", document={"synthetic": True}, object_ids=[episode_a]))["id"])

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


    def test_real_contract_roundtrip_and_stream_reuse(self):
        """F03/F06：真实 vsc.screenplay 契约往返 + 不同 key 既有流被工作区复用。"""
        episode = self.objects["episode"]
        scene, speaker = self.objects["scene"], self.objects["asset"] if "asset" in self.objects else None
        document = {"format": "vsc.screenplay/v1", "project_id": self.p, "body": "合成契约剧本",
                    "scope": episode, "adaptation_refs": [{"id": "A1", "sha256": "270c0d536da1e328c882cda409fc95a131d86851b817f538836313cad3b9ed03"}],
                    "scenes": [{"id": scene, "estimated_duration_ms": 3000,
                    "actions": [{"id": "A1", "text": "他停下脚步", "narrative_refs": ["N1"]}],
                    "dialogue": [], "silence": []}]}
        # 先以 CLI 风格用独立 key 登记并批准剧本（F06：既有不同 key 流）
        original = self.write("create_artifact", dict(artifact_key="original_script", artifact_type="vsc.screenplay",
            stage="script", document=document, object_ids=[episode]))
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "synthetic human approval"})
        # 工作区从既有批准基线起草修订（真实契约文档，仅改一处台词文本）
        document["scenes"][0]["actions"][0]["text"] = "他停下脚步，回头看了一眼"
        self.service.save_script_draft(self.p, {"scope_key": episode, "base_draft_revision": 0,
                                                "content": document}, actor="editor-a")
        draft = self.service.get_script_draft(self.p, episode)
        self.assertEqual((draft["base"] or {}).get("id"), original["id"])  # 基线绑定既有批准
        submitted = self.write("submit_script_draft", {"scope_key": episode, "base_draft_revision": 1,
            "artifact_type": "vsc.screenplay", "stage": "script"})
        self.assertEqual(submitted["artifact"]["artifact_key"], "original_script")  # 沿既有 stream，不另造 key
        self.assertEqual(submitted["baseline_artifact_id"], original["id"])
        fresh = self.service.get_script_draft(self.p, episode)
        self.assertEqual(fresh["phase"], "pending")
        with self.assertRaises(ResourceError) as caught:  # 待审修订阻断该范围新制作
            self.write("create_artifact", dict(artifact_key="blocked", artifact_type="asset-bible", stage="design",
                                               document={"synthetic": True}, object_ids=[episode]))
        self.assertEqual("script_revision_pending", caught.exception.code)

    def test_suggestions_apply_reject_undo_and_scope_notes(self):
        episode = self.objects["episode"]
        self.service.save_script_draft(self.p, {"scope_key": episode, "base_draft_revision": 0,
                                                "content": self.draft_document()}, actor="editor-a")
        # 批注范围：两集互不串扰（F07/B1-08）
        other = self.write("create_object", {"kind": "episode", "display_code": "EP2",
                                             "parent_id": self.objects["work"], "ordinal": 1})["id"]
        note_a = self.write("add_script_note", {"scope_key": episode, "scene_id": "SC1", "line_id": "L1", "body": "口语化"})
        self.write("add_script_note", {"scope_key": other, "scene_id": "SC1", "line_id": "L1", "body": "另一集的批注"})
        notes = self.service.get_script_draft(self.p, episode)["notes"]
        self.assertEqual([row["id"] for row in notes], [note_a["id"]])  # 只见本范围批注
        # 建议：接受逐处应用并推进修订；过期建议不能覆盖较新编辑
        suggestion = self.write("add_script_suggestion", {"scope_key": episode, "scene_id": "SC1",
            "line_id": "L1", "kind": "dialogue", "field": "text", "before_value": "今晚我等你",
            "after_value": "今晚我等你，不见不散", "reason": "更贴合挽留语气", "origin": "ai"})
        accepted = self.write("decide_script_suggestion", {"scope_key": episode,
            "suggestion_id": suggestion["id"], "outcome": "accept", "reason": "采纳"})
        draft = self.service.get_script_draft(self.p, episode)
        self.assertEqual(draft["content"]["scenes"][0]["dialogue"][0]["text"], "今晚我等你，不见不散")
        self.assertEqual(draft["draft_revision"], accepted["draft_revision"])
        self.assertEqual(next(row["status"] for row in draft["suggestions"] if row["id"] == suggestion["id"]), "accepted")
        # 撤销：接受后无新编辑时可回滚
        undone = self.write("decide_script_suggestion", {"scope_key": episode,
            "suggestion_id": suggestion["id"], "outcome": "undo_accept", "reason": "复看后不稳"})
        draft = self.service.get_script_draft(self.p, episode)
        self.assertEqual(draft["content"]["scenes"][0]["dialogue"][0]["text"], "今晚我等你")
        self.assertEqual(draft["draft_revision"], undone["draft_revision"])
        # 过期建议：基于旧修订，接受被拒
        stale = self.write("add_script_suggestion", {"scope_key": episode, "scene_id": "SC1",
            "line_id": "L1", "kind": "dialogue", "field": "text", "before_value": "今晚我等你",
            "after_value": "过期建议", "reason": "基于旧稿"})
        self.service.save_script_draft(self.p, {"scope_key": episode, "base_draft_revision": draft["draft_revision"],
                                                "content": self.draft_document("新编辑")}, actor="editor-b")
        with self.assertRaises(ResourceError) as caught:
            self.write("decide_script_suggestion", {"scope_key": episode, "suggestion_id": stale["id"],
                                                    "outcome": "accept", "reason": "应被过期拒绝"})
        self.assertEqual("suggestion_stale", caught.exception.code)
        self.write("decide_script_suggestion", {"scope_key": episode, "suggestion_id": stale["id"],
                                                "outcome": "reject", "reason": "关闭过期建议"})
        self.assertEqual(next(row["status"] for row in
                              self.service.get_script_draft(self.p, episode)["suggestions"]
                              if row["id"] == stale["id"]), "rejected")

    def test_revision_impact_lists_real_consumers(self):
        episode = self.objects["episode"]
        scene = self.objects["scene"]
        document = {"format": "vsc.screenplay/v1", "project_id": self.p, "body": "合成契约剧本",
                    "scope": episode, "adaptation_refs": [{"id": "A1", "sha256": "270c0d536da1e328c882cda409fc95a131d86851b817f538836313cad3b9ed03"}],
                    "scenes": [{"id": scene, "estimated_duration_ms": 3000,
                    "actions": [{"id": "A1", "text": "他停下", "narrative_refs": ["N1"]}],
                    "dialogue": [], "silence": []}]}
        original = self.write("create_artifact", dict(artifact_key="impact_script", artifact_type="vsc.screenplay",
            stage="script", document=document, object_ids=[episode]))
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "synthetic human approval"})
        # 直接在数据库登记覆盖与声音关系（复用真实表，避免构造完整 coverage 契约）
        from vsc.adapters.persistence.postgres import schema as S
        from sqlalchemy import insert as sa_insert, select as sa_select
        with self.store.engine.connect() as conn:
            line_id = conn.execute(sa_select(S.script_lines.c.id).where(
                S.script_lines.c.project_id == self.p, S.script_lines.c.script_version_id == original["id"],
                S.script_lines.c.line_key == "A1")).scalar_one()
        with self.store.engine.begin() as conn:
            conn.execute(sa_insert(S.shot_line_coverage).values(project_id=self.p, id=new_uuid(),
                coverage_version_id=original["id"], shot_id=self.objects["shot"], line_id=line_id,
                start_char=0, end_char=3))
            cue = new_uuid()
            conn.execute(sa_insert(S.sound_cues).values(project_id=self.p, id=cue, artifact_id=original["id"],
                cue_key="cue-1", label="环境声", cue_kind="ambience", scope_object_id=episode,
                line_id=line_id, parameters={}))
        document["scenes"][0]["actions"][0]["text"] = "他停下脚步，回头看了一眼"
        self.service.save_script_draft(self.p, {"scope_key": episode, "base_draft_revision": 0,
                                                "content": document}, actor="editor-a")
        self.write("submit_script_draft", {"scope_key": episode, "base_draft_revision": 1,
                                           "artifact_type": "vsc.screenplay", "stage": "script"})
        impact = self.service.script_revision_impact(self.p, episode)
        self.assertTrue(any(row.get("line_id") == "A1" for row in impact["changed_lines"]))
        self.assertTrue(any(row["id"] == self.objects["shot"] for row in impact["shots"]))
        self.assertTrue(any(row["cue_key"] == "cue-1" for row in impact["cues"]))



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
            "stages": [{"id": "script", "required": ["screenplay", "vsc.screenplay"]},
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


def new_uuid():
    import uuid
    return uuid.uuid4().hex


if __name__ == "__main__":
    unittest.main()
