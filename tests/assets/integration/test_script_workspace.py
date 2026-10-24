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
            "profile_id": "vsc.synthetic-script", "version": "1", "dependency_policy": "previous_stage", "scope_required_from": "script",
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

    def test_scoped_pages_and_latest_decisions_do_not_expand_other_episode_history(self):
        from sqlalchemy import event, insert
        from vsc.adapters.persistence.postgres import schema as S
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "content": self.draft_document()}, actor="editor")
        notes = []
        for n in range(5):
            notes.append(self.write('add_script_note', {'scope_key': self.episode, 'scene_id': 'SC1', 'line_id': 'L1',
                'body': '当前集意见' + str(n), 'base_draft_revision': 1})['id'])
        for n in range(3):
            self.write('decide_script_note', {'note_id': notes[-1], 'outcome': 'dismiss' if n == 1 else 'resolve', 'reason': '合成决定' + str(n)})
        def measure():
            rows=[]
            def observed(conn,cursor,statement,parameters,context,executemany):
                if statement.lstrip().upper().startswith(('SELECT','WITH')):rows.append(cursor.rowcount)
            event.listen(self.engine,'after_cursor_execute',observed)
            try:value=self.service.get_script_draft(self.p,self.episode,limit=2)
            finally:event.remove(self.engine,'after_cursor_execute',observed)
            return value,rows
        other_scope=self.write('create_object', {'kind':'episode','display_code':'SCALE-EP2',
            'parent_id':self.objects['work'],'ordinal':2})['id']
        def seed_other(count):
            with self.engine.begin() as conn:
                conn.execute(insert(S.script_notes), [{'project_id':self.p,'id':str(uuid.uuid4()),'scope_key':other_scope,
                    'scene_id':'foreign-scene','line_id':'foreign-line','body':'其他集历史' + str(n),'author':'fixture'} for n in range(count)])
        seed_other(100)
        first, before = measure()
        self.assertEqual(len(first['notes']),2);self.assertEqual(first['notes_page']['next_offset'],2)
        self.assertEqual(first['notes'][0]['status'],'resolved')
        seed_other(900)
        second, after = measure()
        self.assertEqual(before,after)
        self.assertEqual([row['id'] for row in first['notes']],[row['id'] for row in second['notes']])
        next_page=self.service.get_script_draft(self.p,self.episode,note_offset=2,limit=2)
        self.assertEqual(len(next_page['notes']),2)
        self.assertFalse(set(row['id'] for row in first['notes']) & set(row['id'] for row in next_page['notes']))
        choice_ids=[str(uuid.uuid4()) for _ in range(150)]
        with self.engine.begin() as conn:
            conn.execute(insert(S.creative_objects), [{'project_id':self.p,'id':identifier,'kind':'asset',
                'display_code':'CHOICE-'+str(n),'title':'人物'+str(n).zfill(3)} for n,identifier in enumerate(choice_ids)])
            conn.execute(insert(S.asset_identities), [{'project_id':self.p,'id':identifier,'asset_kind':'character'} for identifier in choice_ids])
        choices=self.store.script_editor_choice_page(self.p,self.episode,'character','',100)
        self.assertEqual(len(choices['items']),50)
        self.assertEqual(choices['items'][-1]['id'],choice_ids[-1])
        self.assertEqual(self.store.script_editor_choice_page(self.p,self.episode,'character','人物149')['items'][0]['id'],choice_ids[-1])
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        client=TestClient(create_app({'allowed_hosts':['testserver']},service=self.service))
        response=client.get('/api/v1/projects/'+self.p+'/script-draft/choices',params={'scope_key':self.episode,'kind':'character','query':'人物149'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['items'][0]['id'],choice_ids[-1])

    def test_suggestion_requires_original_revision_and_verified_before(self):
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "content": self.draft_document()}, actor="editor")
        payload = {"scope_key": self.episode, "base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1",
                   "kind": "dialogue", "field": "text", "before_value": "伪造原值", "after_value": "建议", "reason": "test"}
        with self.assertRaises(ResourceError) as caught:
            self.write("add_script_suggestion", payload)
        self.assertEqual(caught.exception.code, "suggestion_before_mismatch")
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1,
                                               "content": self.draft_document("较新稿")}, actor="editor")
        with self.assertRaises(ResourceError) as caught:
            self.write("add_script_suggestion", dict(payload, before_value="今晚我等你"))
        self.assertEqual(caught.exception.code, "suggestion_stale")

    def test_working_copy_does_not_inherit_frozen_approval(self):
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "content": self.draft_document()}, actor="editor")
        submitted = self.write("submit_script_draft", {"scope_key": self.episode, "base_draft_revision": 1,
                                                       "artifact_type": "screenplay"})["artifact"]
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1,
                                               "content": self.draft_document("另一个工作副本")}, actor="editor")
        self.write("decide_artifact", {"artifact_id": submitted["id"], "reason": "approved frozen version"})
        draft = self.service.get_script_draft(self.p, self.episode)
        self.assertEqual(draft["phase"], "editing")
        self.assertEqual(draft["submitted"]["state"], "approved")
        self.assertFalse(draft["submitted"]["matches_draft"])

    def confirmed_job_payload(self):
        original = self.write("create_artifact", {"artifact_key": "script", "artifact_type": "screenplay",
            "document": self.draft_document(), "object_ids": [self.episode]})
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "baseline"})
        canonical = self.write("create_artifact", {"artifact_key": "canonical-script", "artifact_type": "vsc.screenplay",
            "document": {"format": "vsc.screenplay/v1", "project_id": self.p, "scope": self.episode,
                "body": "Synthetic fixed screenplay", "adaptation_refs": [{"id": "SYNTHETIC", "sha256": "0" * 64}],
                "scenes": [{"id": self.objects["scene"], "estimated_duration_ms": 1000,
                    "actions": [{"id": "A1", "text": "Synthetic action", "narrative_refs": ["N1"]}], "dialogue": [], "silence": []}]},
            "object_ids": [self.episode]})
        self.write("decide_artifact", {"artifact_id": canonical["id"], "reason": "Synthetic canonical script approval"})
        design = self.write("create_artifact", {"artifact_key": "gate-design", "artifact_type": "asset-bible",
            "document": {"synthetic": True}, "object_ids": [self.episode], "dependency_ids": [original["id"], canonical["id"]]})
        self.write("decide_artifact", {"artifact_id": design["id"], "reason": "Synthetic design approval"})
        animatic = self.write("create_artifact", {"artifact_key": "gate-animatic", "artifact_type": "animatic",
            "document": {"synthetic": True}, "object_ids": [self.episode], "dependency_ids": [design["id"]]})
        self.write("decide_artifact", {"artifact_id": animatic["id"], "reason": "Synthetic animatic approval"})
        self.artifact(objects=[self.objects["shot"]])
        self.artifact("state", "scene-state", [self.objects["scene"]], {"state_versions": [{"scene_id": self.objects["scene"]}]})
        first = self.media("script gate first frame")
        self.select(self.candidate(self.objects["shot"], first))
        from vsc.project.pg_workflow import check_gate
        gate = check_gate(self.service, self.p, "animatic", scope=self.episode)
        self.assertTrue(gate["passed"], gate["gaps"])
        request = {"prompt": "Synthetic fixed shot", "first_frame_media_id": first}
        run = self.production_run(self.objects["shot"], request, candidate_count=4)
        provider = "script_gate_" + uuid.uuid4().hex
        self.service.register_provider({"id": provider, "base_url": "https://example.invalid", "auth_ref": "OFFLINE_TEST_KEY"}, actor="fixture-admin")
        model = self.service.register_model({"provider_id": provider, "model_key": "offline", "model_version": "1", "modality": "video",
            "capabilities": {"purposes": ["video_clip"], "first_frame": True}}, actor="fixture-admin")
        context = self.service.compile_shot_context(self.p, self.objects["shot"], purpose="video_clip")
        payload = {"run_version_id": run, "shot_id": self.objects["shot"], "purpose": "video_clip", "modality": "video",
            "model_id": model["id"], "context_sha256": context["sha256"], "request_payload": request}
        return payload

    def test_cli_pending_script_stops_create_claim_first_submit_but_keeps_inflight(self):
        payload = self.confirmed_job_payload()
        inflight = self.write("create_generation_job", dict(payload, candidate_no=0))
        lease = self.service.claim_generation_job("old-worker", project_id=self.p)
        self.rev = lease["revision"]
        self.write("mark_submission_started", {"job_id": inflight["id"], "worker_id": "old-worker"})
        self.write("update_generation_job", {"job_id": inflight["id"], "worker_id": "old-worker", "status": "submitted",
            "external_task_id": "fixed-existing-provider-task", "recovery_evidence": {"source": "offline receipt"}})
        before_pending = self.write("create_generation_job", dict(payload, candidate_no=1))
        claimed = self.service.claim_generation_job("new-worker", project_id=self.p)
        self.rev = claimed["revision"]
        self.assertEqual(claimed["id"], before_pending["id"])
        self.write("create_generation_job", dict(payload, candidate_no=2))
        revision = self.write("create_artifact", {"artifact_key": "cli-other-key", "artifact_type": "screenplay",
            "document": self.draft_document("New CLI candidate"), "object_ids": [self.episode]})
        for method, args in (("create_generation_job", dict(payload, candidate_no=3)),
                             ("mark_submission_started", {"job_id": before_pending["id"], "worker_id": "new-worker"})):
            with self.assertRaises(ResourceError) as caught:
                self.write(method, args)
            self.assertEqual(caught.exception.code, "script_revision_pending")
        with self.assertRaises(ResourceError) as caught:
            self.service.claim_generation_job("blocked-worker", project_id=self.p)
        self.assertEqual(caught.exception.code, "script_revision_pending")
        resumed = self.service.claim_generation_job("poll-worker", project_id=self.p, statuses=("submitted", "running"))
        self.rev = resumed["revision"]
        self.assertEqual(resumed["id"], inflight["id"])
        self.assertEqual((resumed["status"], resumed["attempt"], resumed["external_task_id"]),
                         ("submitted", 1, "fixed-existing-provider-task"))
        self.write("decide_artifact", {"artifact_id": revision["id"], "outcome": "reject", "reason": "closed candidate"})
        self.assertIsNotNone(self.service.claim_generation_job("restored-worker", project_id=self.p))

    def test_global_claim_skips_blocked_project_and_preserves_inflight_recovery(self):
        fixtures = []
        for number in range(2):
            if number:
                self.setUp()
            payload = self.confirmed_job_payload()
            inflight = self.write("create_generation_job", dict(payload, candidate_no=0))
            lease = self.service.claim_generation_job("submit-worker", project_id=self.p)
            self.rev = lease["revision"]
            self.write("mark_submission_started", {"job_id": inflight["id"], "worker_id": "submit-worker"})
            external = "fixed-task-" + self.p
            self.write("update_generation_job", {"job_id": inflight["id"], "worker_id": "submit-worker", "status": "submitted",
                "external_task_id": external, "recovery_evidence": {"source": "offline receipt"}})
            created = self.write("create_generation_job", dict(payload, candidate_no=1))
            fixtures.append({"project": self.project, "objects": self.objects, "episode": self.episode,
                             "inflight": inflight["id"], "created": created["id"], "external": external,
                             "input_versions": self.service.get_generation_job(self.p, inflight["id"])["input_versions"]})
        blocked, ready = sorted(fixtures, key=lambda item: item["project"]["id"])
        self.project, self.objects, self.episode = blocked["project"], blocked["objects"], blocked["episode"]
        self.p = self.project["id"]
        self.rev = self.service.get_project(self.p)["revision"]
        revision = self.write("create_artifact", {"artifact_key": "script", "artifact_type": "screenplay",
            "document": self.draft_document("Pending lower-ID project revision"), "object_ids": [self.episode]})
        with self.assertRaises(ResourceError) as caught:
            self.service.claim_generation_job("explicit-blocked-worker", project_id=self.p)
        self.assertEqual(caught.exception.code, "script_revision_pending")
        # The lower project remains first in the real queue. A global worker
        # must still reach the ready project instead of raising forever.
        claimed = self.service.claim_generation_job("global-create-worker")
        self.assertEqual((claimed["project_id"], claimed["id"]), (ready["project"]["id"], ready["created"]))
        untouched = self.service.get_generation_job(self.p, blocked["created"])
        self.assertEqual((untouched["status"], untouched["attempt"], untouched["claim_owner"]), ("created", 0, None))
        self.assertIsNone(self.service.claim_generation_job("global-no-ready-worker"))
        # Existing provider work in the blocked project keeps its original
        # external receipt and pinned inputs; polling does not resubmit it.
        resumed = self.service.claim_generation_job("global-poll-worker", statuses=("submitted", "running"))
        self.assertEqual((resumed["project_id"], resumed["id"], resumed["attempt"], resumed["external_task_id"]),
                         (self.p, blocked["inflight"], 1, blocked["external"]))
        self.assertEqual(resumed["input_versions"], blocked["input_versions"])
        self.rev = self.service.get_project(self.p)["revision"]
        self.write("decide_artifact", {"artifact_id": revision["id"], "outcome": "reject", "reason": "Close pending revision"})
        unblocked = self.service.claim_generation_job("global-after-decision-worker")
        self.assertEqual((unblocked["project_id"], unblocked["id"]), (self.p, blocked["created"]))

    def test_cli_pending_revision_blocks_new_work_and_cannot_change_stream_scope(self):
        other = self.write("create_object", {"kind": "episode", "display_code": "EP2", "parent_id": self.objects["work"], "ordinal": 1})["id"]
        original = self.write("create_artifact", {"artifact_key": "script-ab", "artifact_type": "screenplay",
            "document": self.draft_document(), "object_ids": [self.episode, other]})
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "baseline"})
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "content": self.draft_document("new")}, actor="editor")
        with self.assertRaises(ResourceError) as caught:
            self.write("submit_script_draft", {"scope_key": self.episode, "base_draft_revision": 1,
                "artifact_type": "screenplay", "artifact_key": "escape"})
        self.assertIn(caught.exception.code, {"script_stream_mismatch", "script_scope_change_required"})
        with self.assertRaises(ResourceError) as caught:
            self.write("submit_script_draft", {"scope_key": self.episode, "base_draft_revision": 1, "artifact_type": "screenplay"})
        self.assertEqual(caught.exception.code, "script_scope_change_required")
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", {"artifact_key": "script-ab", "artifact_type": "screenplay",
                "document": self.draft_document("narrowed CLI"), "object_ids": [self.episode]})
        self.assertEqual(caught.exception.code, "script_scope_change_required")
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", {"artifact_key": "script-ab", "artifact_type": "asset-bible",
                "document": {"synthetic": True}, "object_ids": [self.episode, other]})
        self.assertEqual(caught.exception.code, "script_scope_change_required")
        pending = self.write("create_artifact", {"artifact_key": "script-ab", "artifact_type": "screenplay",
            "document": self.draft_document("revision"), "object_ids": [self.episode, other]})
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", self.bible_payload())
        self.assertEqual(caught.exception.code, "script_revision_pending")
        self.write("decide_artifact", {"artifact_id": pending["id"], "outcome": "reject", "reason": "closed"})
        self.assertTrue(self.write("create_artifact", self.bible_payload())["id"])

    def test_cli_pending_other_scope_is_not_a_project_stop(self):
        other = self.write("create_object", {"kind": "episode", "display_code": "EP2", "parent_id": self.objects["work"], "ordinal": 1})["id"]
        for scope in (self.episode, other):
            row = self.write("create_artifact", {"artifact_key": "script-" + scope, "artifact_type": "screenplay",
                "document": self.draft_document(), "object_ids": [scope]})
            self.write("decide_artifact", {"artifact_id": row["id"], "reason": "baseline"})
        pending = self.write("create_artifact", {"artifact_key": "script-" + self.episode, "artifact_type": "screenplay",
            "document": self.draft_document("pending"), "object_ids": [self.episode]})
        self.assertTrue(self.write("create_artifact", {"artifact_key": "unrelated", "artifact_type": "asset-bible",
            "document": {"synthetic": True}, "object_ids": [other]})["id"])
        self.write("decide_artifact", {"artifact_id": pending["id"], "outcome": "reject", "reason": "close"})

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

    def test_notes_keep_exact_saved_baseline_and_reject_stale_note_start(self):
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "content": self.draft_document()}, actor="editor")
        frozen = self.write("submit_script_draft", {"scope_key": self.episode, "base_draft_revision": 1, "artifact_type": "screenplay"})["artifact"]
        note = self.write("add_script_note", {"scope_key": self.episode, "base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1", "body": "Saved version comment"})
        self.assertEqual(note["base_artifact_id"], frozen["id"])
        self.assertEqual(note["base_draft_revision"], 1)
        self.assertEqual(len(note["base_content_sha256"]), 64)
        self.service.save_script_draft(self.p, {"scope_key": self.episode, "base_draft_revision": 1, "content": self.draft_document("New working copy")}, actor="editor")
        with self.assertRaises(ResourceError) as caught:
            self.write("add_script_note", {"scope_key": self.episode, "base_draft_revision": 1, "scene_id": "SC1", "body": "Stale comment"})
        self.assertEqual(caught.exception.code, "draft_revision_conflict")
        saved_note = self.service.get_script_draft(self.p, self.episode)["notes"][0]
        self.assertEqual((saved_note["base_draft_revision"], saved_note["base_artifact_id"]), (1, frozen["id"]))

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
        note_a = self.write("add_script_note", {"scope_key": episode, "base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1", "body": "口语化"})
        self.write("add_script_note", {"scope_key": other, "scene_id": "SC1", "line_id": "L1", "body": "另一集的批注"})
        notes = self.service.get_script_draft(self.p, episode)["notes"]
        self.assertEqual([row["id"] for row in notes], [note_a["id"]])  # 只见本范围批注
        # 建议：接受逐处应用并推进修订；过期建议不能覆盖较新编辑
        suggestion = self.write("add_script_suggestion", {"scope_key": episode, "scene_id": "SC1",
            "base_draft_revision": 1,
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
            "base_draft_revision": draft["draft_revision"],
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


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit PostgreSQL URL")
class RealProfileScriptWorkspace(ResourceStoreFixture, unittest.TestCase):
    def test_blank_draft_real_profiles_pin_approved_upstream_and_trusted_scope(self):
        import json
        from support.paths import ROOT
        from vsc.project.state import profile_for
        for profile_id in ("vsc.light-short", "vsc.series-pg"):
            with self.subTest(profile=profile_id):
                profile = profile_for(profile_id)
                self.project = self.service.create_project({"name": "isolated real profile fixture", "profile_snapshot": profile}, actor="fixture-human")
                self.p, self.rev = self.project["id"], 0
                self.objects = self.hierarchy()
                episode = self.objects["episode"]
                context = self.service.get_script_draft(self.p, episode)["submission_context"]
                expected = ["vsc.adaptation_plan"] + (["vsc.episode_beats"] if profile_id == "vsc.series-pg" else [])
                self.assertEqual(context["missing_dependency_types"], expected)
                document = {"format": "vsc.screenplay/v1", "body": "Synthetic working copy", "adaptation_refs": [],
                    "scenes": [{"id": self.objects["scene"], "estimated_duration_ms": 1000,
                                "actions": [{"id": "A1", "text": "Synthetic action", "narrative_refs": ["SC-001"]}],
                                "dialogue": [], "silence": []}]}
                # No project_id/scope are supplied by the browser. Those fields
                # are server authority; source/body fields remain user content.
                self.service.save_script_draft(self.p, {"scope_key": episode, "content": document}, actor="fixture-human")
                with self.assertRaises(ResourceError):
                    self.write("submit_script_draft", {"scope_key": episode, "base_draft_revision": 1,
                        "artifact_type": "vsc.screenplay", "dependency_ids": []})
                pins = {}
                for stage in profile["stages"][:3]:
                    for kind in stage.get("required", []):
                        if kind == "vsc.creative_brief":
                            body = {"format": "vsc.creative-brief/v1", "audience": "Fixture audience",
                                "desired_experience": "Synthetic clarity", "decision_owner": "fixture-human",
                                "objectives": [{"id": "clarity", "goal": "Synthetic goal", "success_evidence": "Fixture check"}],
                                "nonnegotiables": [], "conflict_policy": "Fixture human decides"}
                        elif kind in {"vsc.adaptation_contract", "vsc.story_bible"}:
                            body = "Synthetic fixed upstream evidence"
                        else:
                            filename = {"vsc.source_map": "source-map", "vsc.adaptation_plan": "adaptation-map", "vsc.episode_beats": "episode-beats"}[kind]
                            body = json.loads((ROOT / "templates" / (filename + ".json")).read_text())
                            if kind == "vsc.source_map":
                                body["summary"] = "Synthetic source summary"
                                body["source_units"][0].update(fact_or_claim="Synthetic source fact", narrative_function="Establish action")
                            elif kind == "vsc.adaptation_plan":
                                body["project_id"] = self.p
                                body["episodes"][0]["id"] = episode
                                body["screen_units"][0].update(episode_id=episode, scene_id=self.objects["scene"])
                            elif kind == "vsc.episode_beats":
                                body["episodes"][0].update(id=episode, ending="Synthetic closure")
                                body["episodes"][0]["beats"][0].update(action="Synthetic action", change="Action changes", screen_unit_ids=["SC-001"])
                        from vsc.assets.resource_service import dependency_requirements
                        requirements, _ = dependency_requirements(profile, kind)
                        deps = [pins[value]["id"] for value in requirements]
                        row = self.write("create_artifact", {"artifact_key": kind, "artifact_type": kind, "stage": "forged-stage",
                            "document": body, "project_wide": True, "dependency_ids": deps})
                        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "Synthetic human fixture decision"})
                        pins[kind] = row
                context = self.service.get_script_draft(self.p, episode)["submission_context"]
                self.assertEqual(context["missing_dependency_types"], [])
                self.assertEqual({row["artifact_type"] for row in context["dependencies"]}, set(expected))
                self.assertEqual(set(context["dependency_ids"]), {pins[kind]["id"] for kind in expected})
                document["adaptation_refs"] = [{"id": pins["vsc.adaptation_plan"]["id"], "sha256": pins["vsc.adaptation_plan"]["sha256"]}]
                self.service.save_script_draft(self.p, {"scope_key": episode, "base_draft_revision": 1, "content": document}, actor="fixture-human")
                # CLI stage spoof cannot bypass requirements on approval.
                forged = self.write("create_artifact", {"artifact_key": "cli-no-deps", "artifact_type": "vsc.screenplay", "stage": "brief",
                    "object_ids": [episode], "document": dict(document, project_id=self.p, scope=episode)})
                self.assertEqual(self.service.get_artifact_version(self.p, forged["id"])["stage"], "script")
                with self.assertRaises(ResourceError) as caught:
                    self.write("decide_artifact", {"artifact_id": forged["id"], "reason": "Must be blocked"})
                self.assertEqual(caught.exception.code, "artifact_dependency_required")
                self.write("decide_artifact", {"artifact_id": forged["id"], "outcome": "reject", "reason": "Close fixture"})
                submitted = self.write("submit_script_draft", {"scope_key": episode, "base_draft_revision": 2,
                    "artifact_type": context["artifact_type"], "stage": "brief", "dependency_ids": context["dependency_ids"]})["artifact"]
                frozen = self.service.get_artifact_version(self.p, submitted["id"])
                frozen_document = json.loads(frozen["content"])
                self.assertEqual(frozen_document["project_id"], self.p)
                self.assertEqual(frozen_document["scope"], episode)
                self.write("decide_artifact", {"artifact_id": submitted["id"], "reason": "Approve exact frozen fixture"})
                draft = self.service.get_script_draft(self.p, episode)
                self.assertEqual(draft["phase"], "approved")
                self.assertTrue(draft["submitted"]["matches_draft"])


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
