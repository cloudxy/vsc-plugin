"""Original opinions, professional results and trusted HTTP over real isolated PG."""
import copy
import json
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError


class OfflineSuggestions:
    name = "offline-review-host"
    def __init__(self, unknown=False, outside=False):
        self.calls, self.unknown, self.outside = 0, unknown, outside
    def available(self):
        return True
    def generate(self, document, goal):
        self.calls += 1
        if self.unknown:
            raise TimeoutError("offline uncertain submission")
        return [{"scene_id": "SC1", "line_id": "L2" if self.outside else "L1", "kind": "dialogue", "field": "text",
                 "after_value": "走。", "reason": "保留离开的意思，缩短解释"}]


class UnavailableSuggestions:
    def available(self):
        return False


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit PostgreSQL test URL")
class ReviewFeedbackTests(ResourceStoreFixture, unittest.TestCase):
    def test_schema_new_migration_roundtrip_matches_metadata(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres import schema as S
        with isolated_postgres(TEST_URL) as engine:
            config = Config(str(support.paths.ROOT / "migrations/postgres/alembic.ini"))
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                command.downgrade(config, "0010_source_resources")
                command.upgrade(config, "head")
                self.assertEqual(compare_metadata(MigrationContext.configure(conn), S.metadata), [])
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.document = {"scenes": [{"id": "SC1", "actions": [{"id": "A1", "text": "手按门把"}],
            "dialogue": [{"id": "L1", "speaker": "C1", "text": "我现在必须离开这里"},
                         {"id": "L2", "speaker": "C1", "text": "留下"}], "silence": []}]}
        self.service.script_suggester = OfflineSuggestions()
        self.addCleanup(setattr, self.service, "script_suggester", None)
        self.clients = []
        self.addCleanup(lambda: [client.__exit__(None, None, None) for client in self.clients])

    def client(self, service=None):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        client = TestClient(create_app({"projects_root": self.temp.name + "/empty", "media_root": self.temp.name,
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "access_token": "test-token", "human_identity": "test-human"}, service=service or self.service))
        client.__enter__(); self.clients.append(client)
        session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        return client, {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}

    def http_write(self, client, headers, endpoint, payload, *, status=200, key=None, revision=None):
        result = client.post("/api/v1/projects/" + self.p + "/" + endpoint, headers=headers,
            json={"payload": payload, "expected_revision": self.rev if revision is None else revision,
                  "idempotency_key": key or uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(result.status_code, status, result.text)
        if status == 200:
            self.rev = result.json()["revision"]
        return result.json()

    def note(self):
        self.service.save_script_draft(self.p, {"content": self.document}, actor="test-human")
        return self.write("add_script_note", {"base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1",
                                               "body": "解释太多，保留离开的意思与按门把的动作"})["id"]

    def test_script_http_exact_opinion_local_difference_replay_rebuild_and_reject(self):
        note = self.note()
        client, headers = self.client()
        result = self.http_write(client, headers, "review-process", {"script_note_id": note}, key="one-note")
        self.assertEqual(result["status"], "completed")
        self.http_write(client, headers, "review-process", {"script_note_id": note}, key="one-note", revision=0)
        self.assertEqual(self.service.script_suggester.calls, 1)
        history = self.service.get_review_history(self.p, script_note_id=note)["items"][0]
        self.assertEqual(history["body"], "解释太多，保留离开的意思与按门把的动作")
        self.assertEqual(history["note"]["anchor"]["excerpt"], "我现在必须离开这里")
        suggestion = history["responses"][0]["runs"][0]["suggestions"][0]
        self.http_write(client, headers, "script-suggestion-decisions", {"suggestion_id": suggestion["id"], "outcome": "reject", "reason": "保留原文"})
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        rebuilt = ResourceService(PostgresResourceStore(engine=self.engine))
        second, _ = self.client(rebuilt)
        fresh = second.get(f"/api/v1/projects/{self.p}/script-draft").json()
        self.assertEqual(fresh["content"], self.document)
        self.assertNotIn('review_history',fresh['notes'][0])
        expanded=second.get(f'/api/v1/projects/{self.p}/review-history',params={'script_note_id':note}).json()
        linked = expanded['items'][0]['responses'][0]['runs'][0]['suggestions'][0]
        self.assertEqual(linked["decisions"][0]["outcome"], "reject")
        self.assertEqual(fresh["notes"][0]["status"], "open")
        self.service.save_script_draft(self.p, {"base_draft_revision": 1, "content": dict(self.document, body="changed")}, actor="test-human")
        self.http_write(client, headers, "review-process", {"script_note_id": note}, status=409)

    def test_history_pages_keep_older_responses_reachable_and_do_not_eagerly_expand_notes(self):
        from sqlalchemy import insert
        from datetime import datetime, timezone, timedelta
        from vsc.adapters.persistence.postgres import schema as S
        note=self.note()
        start=datetime(2026,1,1,tzinfo=timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(insert(S.review_responses), [{'project_id':self.p,'id':str(uuid.uuid4()),'script_note_id':note,
                'action':'script_suggestions','explanation':'处理'+str(n),'preserve':'固定原事实','limitations':'无媒体生成',
                'author':'fixture','created_at':start+timedelta(seconds=n)} for n in range(25)])
        client,_=self.client()
        path=f'/api/v1/projects/{self.p}/review-history'
        first=client.get(path,params={'script_note_id':note}).json()['items'][0]
        self.assertEqual(len(first['responses']),10)
        self.assertEqual(first['response_page']['total'],25)
        self.assertEqual(first['response_page']['next_offset'],10)
        self.assertEqual(first['responses'][-1]['explanation'],'处理24')
        second=client.get(path,params={'script_note_id':note,'response_offset':10}).json()['items'][0]
        self.assertEqual(second['response_page']['previous_offset'],0)
        self.assertEqual(second['responses'][-1]['explanation'],'处理14')
        last=client.get(path,params={'script_note_id':note,'response_offset':20}).json()['items'][0]
        self.assertEqual(len(last['responses']),5)
        self.assertIsNone(last['response_page']['next_offset'])
        self.assertEqual(last['responses'][0]['explanation'],'处理0')
        self.assertEqual(client.get(path,params={'script_note_id':note,'response_limit':0}).status_code,422)
        self.assertNotIn('review_history',self.service.get_script_draft(self.p)['notes'][0])

    def test_script_unknown_outside_scope_missing_host_and_http_identity_have_no_extra_effect(self):
        note = self.note()
        client, headers = self.client()
        self.http_write(client, {}, "review-process", {"script_note_id": note}, status=403)
        self.http_write(client, headers, "review-process", {"script_note_id": note, "actor": "other"}, status=422)
        self.service.script_suggester = OfflineSuggestions(unknown=True)
        first = self.http_write(client, headers, "review-process", {"script_note_id": note}, key="unknown")
        self.assertEqual(first["status"], "submission_unknown")
        self.http_write(client, headers, "review-process", {"script_note_id": note}, key="unknown", revision=0)
        reused = self.http_write(client, headers, "review-process", {"script_note_id": note}, key="refresh-new-key")
        self.assertEqual(reused["id"], first["id"])
        self.assertEqual(self.service.script_suggester.calls, 1)
        self.service.script_suggester = OfflineSuggestions(outside=True)
        outside = self.http_write(client, headers, "review-process", {"script_note_id": note, "new_attempt": True})
        self.assertEqual(outside["status"], "failed")
        self.assertEqual(outside["result"]["suggestion_ids"], [])
        self.service.script_suggester = UnavailableSuggestions()
        before = self.rev
        self.http_write(client, headers, "review-process", {"script_note_id": note, "new_attempt": True}, status=503)
        self.assertEqual(self.service.get_project(self.p)["revision"], before)
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        cross = client.post(f"/api/v1/projects/{other}/review-process", headers=headers,
            json={"payload": {"script_note_id": note}, "expected_revision": 0, "idempotency_key": "cross"})
        self.assertEqual(cross.status_code, 404)
        with self.assertRaises(ResourceError):
            self.write("add_script_note", {"base_draft_revision": 1, "scene_id": "SC1", "line_id": "missing", "body": "wrong"})

    def test_long_opinion_is_preserved_and_has_explicit_processing_limit(self):
        self.service.save_script_draft(self.p, {"content": self.document}, actor="test-human")
        note = self.write("add_script_note", {"base_draft_revision": 1, "scene_id": "SC1", "line_id": "L1", "body": "长" * 2001})["id"]
        client, headers = self.client()
        response = self.http_write(client, headers, "review-process", {"script_note_id": note}, status=422)
        self.assertEqual(response["error"], "review_opinion_too_long")
        self.assertEqual(len(self.service.get_review_history(self.p, script_note_id=note)["items"][0]["body"]), 2001)
        self.assertEqual(self.service.script_suggester.calls, 0)

    def artifact_note(self, artifact_id, category, **target):
        source = self.service.get_artifact_version(self.p, artifact_id)
        return self.write("add_artifact_review_note", {"artifact_id": artifact_id, "artifact_sha256": source["sha256"],
            "category": category, "body": "合成原意见 " + category, **target})["id"]

    def professional_return(self, dispatch, artifact):
        packet = dispatch["packet"]
        binding = {"dispatch_id": dispatch["dispatch_id"], "role_id": packet["role"]["id"],
            "context_sha256": packet["context_sha256"], "instance_id": packet["dispatch"]["instance_id"]}
        actor = packet["dispatch"]["actor"]
        self.assertTrue(actor.startswith("agent:" + packet["role"]["id"] + ":review-"))
        for wrong in ("test-human", "agent:unassigned"):
            with self.assertRaises(ResourceError) as caught:
                self.write("consume_role_dispatch", dict(binding, packet=packet), actor=wrong)
            self.assertEqual(caught.exception.code, "dispatch_identity")
        self.write("consume_role_dispatch", dict(binding, packet=packet), actor=actor)
        result = {**binding, "role_sha256": packet["dispatch"]["role_sha256"], "context_id": packet["context_id"],
            "result_refs": [{"kind": "artifact", "id": artifact["id"], "sha256": artifact["sha256"]}],
            "memory_proposals": [], "session_summary": "固定目标已有局部修改；媒体与正式交付仍待实际制作和人审。"}
        for wrong in ("test-human", "agent:unassigned"):
            with self.assertRaises(ResourceError) as caught:
                self.write("return_role_dispatch", {**binding, "return_key": "one-result", "result": result}, actor=wrong)
            self.assertEqual(caught.exception.code, "dispatch_identity")
        return self.write("return_role_dispatch", {**binding, "return_key": "one-result", "result": result}, actor=actor)

    def render_target(self, objects, video_data=None):
        def video(name):
            if video_data is None:
                return self.media(name, modality="video")
            from io import BytesIO
            staged = self.service.storage.stage_upload(BytesIO(video_data), name + ".mp4")
            result = self.write("register_media", {"staged_upload": staged["staged_upload"], "name": name,
                "rights": "owned", "source": {"kind": "synthetic_test", "content": "local FFmpeg synthetic fixture bytes"}})
            self.write("record_media_check", {"media_id": result["id"], "checker": "synthetic-fixture", "criteria_version": "1", "outcome": "pass"})
            return result["id"]
        media = video("render source")
        selected = self.select(self.candidate(objects["shot"], media, role="video_take"))
        items = [{"shot_id": objects["shot"], "track_key": "video", "offset_frame": 0, "duration_frames": 360,
            "media": [{"media_id": media, "binding_decision_id": selected["id"], "role": "video_take", "source_out_frame": 360}]}]
        timeline = self.artifact("review-timeline", "timeline", projections={"items": items})
        timeline_id = self.write("freeze_timeline", {"artifact_id": timeline, "episode_id": objects["episode"], "items": items, "fps_num": 30})["id"]
        plan = json.loads((support.paths.ROOT / "templates/remotion-render-plan.json").read_text())
        # This fixture tests base-film feedback; overlay selection has its own integration fixture.
        plan["segments"] = [segment for segment in plan["segments"] if "overlay" not in segment]
        plan["project_id"] = self.p
        if video_data is not None:
            plan["composition"].update(width=240, height=320)
            plan["subtitle_style"].update(font_size=24)
        artifact = self.write("create_artifact", {"artifact_key": "review-render", "artifact_type": "render-plan", "document": plan})
        self.write("decide_artifact", {"artifact_id": artifact["id"], "reason": "fixed synthetic plan"})
        rendered = video("render output fixture")
        render = self.write("freeze_render", {"timeline_id": timeline_id, "artifact_id": artifact["id"], "tool": "synthetic", "tool_version": "1", "outputs": [{"media_id": rendered}]})
        targets = self.service.get_media(self.p, rendered)["review_targets"]
        self.assertEqual({r["target"]["category"] for r in targets}, {"subtitle", "edit"})
        return artifact, targets

    def test_four_artifact_categories_dispatch_real_type_return_and_rebuild(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        director = self.write("create_artifact", {"artifact_key": "review-design", "artifact_type": "shot-plan", "document": {
            "design_units": [{"design_key": "fixed-design", "scene_id": objects["scene"], "picture": "看不清行动", "shots": [{"shot_id": objects["shot"]}]}]}})
        self.write("decide_artifact", {"artifact_id": director["id"], "reason": "fixed design"})
        asset = self.write("create_object", {"kind": "asset", "asset_kind": "prop", "display_code": "CUP"})["id"]
        specification = self.write("create_artifact", {"artifact_key": "review-spec", "artifact_type": "asset-bible", "document": {"description": "合成旧规格", "asset_specs": [{"asset_id": asset, "variant_key": "default"}]},
            "asset_specs": [{"asset_id": asset, "variant_key": "default"}]})
        self.write("decide_artifact", {"artifact_id": specification["id"], "reason": "fixed spec"})
        with self.engine.connect() as conn:
            design_id = conn.execute(select(S.shot_design_units.c.id).where(S.shot_design_units.c.project_id == self.p,
                S.shot_design_units.c.artifact_id == director["id"])).scalar_one()
            spec_id = conn.execute(select(S.asset_spec_versions.c.id).where(S.asset_spec_versions.c.project_id == self.p,
                S.asset_spec_versions.c.artifact_id == specification["id"])).scalar_one()
        rendered, targets = self.render_target(objects)
        notes = [(self.artifact_note(director["id"], "director", design_unit_id=design_id), director, "director"),
                 (self.artifact_note(specification["id"], "asset", spec_version_id=spec_id), specification, "asset-director")]
        for row in targets:
            target = dict(row["target"], body="所选这句字幕上移" if row["target"]["category"] == "subtitle" else "这段节奏需要缩短")
            if target["category"] == "subtitle":
                target.update(start_frame=225, end_frame=285)
            notes.append((self.write("add_artifact_review_note", target)["id"], rendered, "remotion-composer" if target["category"] == "subtitle" else "editor"))
        client, headers = self.client()
        dispatched = []
        for note, source, role in notes:
            source = self.service.get_artifact_version(self.p, source["id"])
            dispatch = self.http_write(client, headers, "review-process", {"artifact_note_id": note}, key="dispatch:" + note)
            replay = self.http_write(client, headers, "review-process", {"artifact_note_id": note}, key="dispatch:" + note, revision=0)
            self.assertEqual(dispatch["dispatch_id"], replay["dispatch_id"])
            duplicate = self.http_write(client, headers, "review-process", {"artifact_note_id": note}, key="refresh:" + note)
            self.assertEqual(duplicate["dispatch_id"], dispatch["dispatch_id"])
            self.assertEqual(len(self.service.get_review_history(self.p, artifact_note_id=note)["items"][0]["responses"]), 1)
            self.assertEqual(dispatch["packet"]["role"]["id"], role)
            self.assertEqual(dispatch["packet"]["delivery"]["format"], "vsc.role-delivery/v1")
            self.assertEqual(dispatch["packet"]["delivery"]["artifact_type"], source["artifact_type"])
            pending = self.service.get_review_history(self.p, artifact_note_id=note)["items"][0]["responses"][0]["dispatches"][0]
            self.assertEqual(pending["returns"], [])
            self.assertEqual(pending["delivery"], dispatch["packet"]["delivery"])
            dispatched.append((note, source, role, dispatch))
        for note, source, role, dispatch in dispatched:
            content = json.loads(self.service.get_artifact_version(self.p, source["id"])["content"])
            if role == "remotion-composer":
                from vsc.post.remotion_plan import edit_caption_position, document_sha256
                content = edit_caption_position(content, caption_id="CAP-001", expected_sha256=document_sha256(content),
                    layout={"position": "top"}, frame_range={"from_frame": 225, "duration_in_frames": 60})["document"]
            else:
                content = copy.deepcopy(content)
                if role == "director":
                    content["design_units"][0]["picture"] = "近景拍手握门把；行动清晰可见"
                elif role == "asset-director":
                    content["description"] = "指定道具改为无反光陶瓷杯，其他身份保持"
                else:
                    content["segments"][0]["duration_in_frames"] = 150
                    content["segments"][1]["from_frame"] = 150
                    content["segments"][2]["duration_in_frames"] = 330
                    content["segments"][3]["from_frame"] = 195
                    content["composition"]["duration_in_frames"] = 330
            changed = self.write("create_artifact", {"artifact_key": source["artifact_key"], "artifact_type": source["artifact_type"],
                "document": content, "supersedes_id": source["id"],
                **({"asset_specs": content["asset_specs"]} if role == "asset-director" else {})})
            self.professional_return(dispatch, changed)
            from vsc.assets.resource_service import ResourceService
            recovered = ResourceService(self.store).get_review_history(self.p, artifact_note_id=note)
            result = recovered["items"][0]["responses"][0]["dispatches"][0]["returns"][0]
            self.assertEqual(result["artifacts"][0]["id"], changed["id"])
            self.assertEqual(result["artifacts"][0]["previews"], [])
            self.assertFalse(self.service.get_artifact_version(self.p, changed["id"])["approved"])
        self.http_write(client, headers, "review-process", {"artifact_note_id": notes[0][0]}, status=409)

    def test_professional_empty_completion_blocked_recovery_and_scope(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        document = {"design_units": [{"design_key": "door", "scene_id": objects["scene"],
            "picture": "手握门把", "shots": [{"shot_id": objects["shot"]}]}]}
        source = self.write("create_artifact", {"artifact_key": "review-source", "artifact_type": "shot-plan",
            "document": document})
        self.write("decide_artifact", {"artifact_id": source["id"], "reason": "固定合成原稿"})
        with self.engine.connect() as conn:
            design = conn.execute(select(S.shot_design_units.c.id).where(S.shot_design_units.c.project_id == self.p,
                S.shot_design_units.c.artifact_id == source["id"])).scalar_one()
        note = self.artifact_note(source["id"], "director", design_unit_id=design)
        dispatch = self.write("process_review", {"artifact_note_id": note})
        packet = dispatch["packet"]
        binding = {"dispatch_id": dispatch["dispatch_id"], "role_id": packet["role"]["id"],
            "context_sha256": packet["context_sha256"], "instance_id": packet["dispatch"]["instance_id"]}
        actor = packet["dispatch"]["actor"]
        self.write("consume_role_dispatch", dict(binding, packet=packet), actor=actor)
        result = dict(binding, role_sha256=packet["dispatch"]["role_sha256"], context_id=packet["context_id"],
            result_refs=[], memory_proposals=[], session_summary="无法交付：本轮镜头正文尚未改写")
        with self.assertRaises(ResourceError) as caught:
            self.write("return_role_dispatch", dict(binding, result=result, return_key="empty-finish"), actor=actor)
        self.assertEqual(caught.exception.code, "invalid_dispatch_return")
        self.write("return_role_dispatch", dict(binding, result=result, return_key="blocked", closed=False), actor=actor)
        history = self.service.get_review_history(self.p, artifact_note_id=note)["items"][0]
        pending = history["responses"][0]["dispatches"][0]
        self.assertFalse(pending["returns"][0]["closed"])
        self.assertEqual(pending["returns"][0]["artifacts"], [])
        self.assertIn("尚缺成果", pending["message"])
        changed = copy.deepcopy(document)
        changed["design_units"][0]["picture"] = "近景：手指压住门把，停一拍后松开"
        wrong_scope = self.write("create_artifact", {"artifact_key": "wrong-scope", "artifact_type": "shot-plan",
            "document": changed, "dependency_ids": [source["id"]], "object_ids": [objects["scene"]]})
        with self.assertRaises(ResourceError) as caught:
            self.professional_return(dispatch, wrong_scope)
        self.assertEqual(caught.exception.code, "review_result_scope")
        actual = self.write("create_artifact", {"artifact_key": "review-source", "artifact_type": "shot-plan",
            "document": changed, "supersedes_id": source["id"]})
        self.professional_return(dispatch, actual)
        restored = self.service.get_review_history(self.p, artifact_note_id=note)["items"][0]["responses"][0]["dispatches"][0]
        self.assertEqual(len(restored["returns"]), 2)
        self.assertTrue(restored["returns"][-1]["closed"])
        self.assertEqual(restored["returns"][-1]["artifacts"][0]["id"], actual["id"])

    def test_returned_plan_reads_only_real_render_output_preview_after_service_rebuild(self):
        import shutil
        import subprocess
        from pathlib import Path
        from io import BytesIO
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.post.remotion_plan import edit_caption_position, document_sha256
        from vsc.post import subtitle_burn as SB
        from unittest.mock import patch
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("requires local FFmpeg for real synthetic MP4 preview")
        clip = Path(self.temp.name) / "local-preview.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=240x320:r=30:d=12",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=24000:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(clip)], check=True, capture_output=True)
        data = clip.read_bytes()
        self.service.storage = LocalStorage(self.temp.name)
        source, targets = self.render_target(self.hierarchy(), video_data=data)
        target = dict(next(row["target"] for row in targets if row["target"]["category"] == "subtitle"), start_frame=225, end_frame=285, body="所选字幕上移")
        note = self.write("add_artifact_review_note", target)["id"]
        dispatch = self.write("process_review", {"artifact_note_id": note})
        original = self.service.get_artifact_version(self.p, source["id"])
        document = json.loads(original["content"])
        edited = edit_caption_position(document, caption_id="CAP-001", expected_sha256=document_sha256(document), layout={"position": "top"})["document"]
        changed = self.write("create_artifact", {"artifact_key": original["artifact_key"], "artifact_type": original["artifact_type"],
            "supersedes_id": original["id"], "document": edited})
        self.write("decide_artifact", {"artifact_id": changed["id"], "reason": "explicit fixture human approves this preview plan"})
        if not SB.DEFAULT_FONT.is_file():
            self.skipTest("requires the existing installed default subtitle font")
        burned = Path(self.temp.name) / "caption-top-preview.mp4"
        def offline_runner(command, **kwargs):
            if "render" in command:
                SB.render(command[-1])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return subprocess.run(command, **kwargs)
        with patch.object(SB.shutil, "which", return_value="offline-local-pillow"):
            SB.burn(clip, None, burned, dict(edited["subtitle_style"], font=str(SB.DEFAULT_FONT)), run=offline_runner, render_plan=edited)
        preview_data = burned.read_bytes()
        self.assertNotEqual(preview_data, data)
        pixels = subprocess.run([ffmpeg, "-v", "error", "-ss", "8", "-i", str(burned), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True).stdout
        self.assertGreater(sum(value > 180 for value in pixels[:len(pixels)//2]), 30)
        self.assertLess(sum(value > 180 for value in pixels[len(pixels)//2:]), 10)
        def audio_hash(path):
            return subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a", "-c:a", "copy", "-f", "md5", "-"], capture_output=True, check=True).stdout
        self.assertEqual(audio_hash(clip), audio_hash(burned))
        staged = self.service.storage.stage_upload(BytesIO(preview_data), "actual-local-preview.mp4")
        output = self.write("register_media", {"staged_upload": staged["staged_upload"], "name": "actual local synthetic preview",
            "rights": "owned", "source": {"kind": "local_synthetic_preview", "content": "FFmpeg fixture for typed output readback, not aesthetic approval"}})["id"]
        with self.engine.connect() as conn:
            timeline = conn.execute(select(S.render_versions.c.timeline_id).where(S.render_versions.c.project_id == self.p,
                S.render_versions.c.id == target["render_id"])).scalar_one()
        self.write("freeze_render", {"artifact_id": changed["id"], "timeline_id": timeline, "tool": "local-ffmpeg-fixture", "tool_version": "test",
            "outputs": [{"media_id": output, "role": "local_preview"}]})
        self.professional_return(dispatch, changed)
        rebuilt = ResourceService(PostgresResourceStore(engine=self.engine), self.service.storage)
        history = rebuilt.get_review_history(self.p, artifact_note_id=note)
        preview = history["items"][0]["responses"][0]["dispatches"][0]["returns"][0]["artifacts"][0]["previews"][0]
        self.assertEqual((preview["media_id"], preview["role"]), (output, "local_preview"))
        client, _ = self.client(rebuilt)
        response = client.get(f"/api/v1/projects/{self.p}/media/{output}/content")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, preview_data)

    def test_professional_context_reuses_approved_own_memory_and_excludes_other_and_invalid(self):
        from vsc.assets.role_memory import verified_memory_decision
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        original = self.write("create_artifact", {"artifact_key": "memory-design", "artifact_type": "shot-plan", "document": {
            "design_units": [{"design_key": "clear-action", "scene_id": objects["scene"], "picture": "合成原意见 director",
                              "shots": [{"shot_id": objects["shot"]}]}]}})
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "fixed source"})
        old_source = self.artifact("memory-old-source", "shot-plan")
        memory_ids = []
        for role, source in (("director", original["id"]), ("editor", original["id"]), ("director", old_source)):
            memory = self.write("propose_role_memory", {"role": role, "proposal_key": uuid.uuid4().hex, "kind": "lesson", "content": "合成原意见 director 行动要清楚可见",
                "sources": [{"kind": "artifact", "id": source, "sha256": self.service.get_artifact_version(self.p, source)["sha256"]}],
                "association_complete": True, "tags": ["director", "合成原意见"]})
            entry = next(row for row in self.service.list_role_memories(self.p)["items"] if row["version_id"] == memory["version_id"])
            self.write("decide_role_memory", {"version_id": memory["version_id"], "content_sha256": entry["content_sha256"],
                "outcome": "approved", "reason": "test human"}, human_decision=verified_memory_decision("test-human"))
            memory_ids.append(memory["version_id"])
        self.write("decide_artifact", {"artifact_id": old_source, "outcome": "revoke", "reason": "synthetic expired evidence"})
        with self.engine.connect() as conn:
            design = conn.execute(select(S.shot_design_units.c.id).where(S.shot_design_units.c.project_id == self.p,
                S.shot_design_units.c.artifact_id == original["id"])).scalar_one()
        note = self.artifact_note(original["id"], "director", design_unit_id=design)
        packet = self.write("process_review", {"artifact_note_id": note})["packet"]
        self.assertEqual([row["version_id"] for row in packet["approved_memories"]], memory_ids[:1])
        self.assertGreater(packet["retrieval"]["used_chars"], 0)
        with self.engine.connect() as conn:
            refs = conn.execute(select(S.dispatch_memory_refs.c.memory_version_id).where(
                S.dispatch_memory_refs.c.project_id == self.p, S.dispatch_memory_refs.c.dispatch_id == packet["dispatch"]["id"])).scalars().all()
        self.assertEqual(refs, memory_ids[:1])

    def test_expired_professional_dispatch_requires_explicit_new_round_and_keeps_old_receipt(self):
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        original = self.write("create_artifact", {"artifact_key": "expiry-design", "artifact_type": "shot-plan", "document": {
            "design_units": [{"design_key": "one", "scene_id": objects["scene"], "picture": "原画面", "shots": [{"shot_id": objects["shot"]}]}]}})
        self.write("decide_artifact", {"artifact_id": original["id"], "reason": "fixed source"})
        with self.engine.connect() as conn:
            design = conn.execute(select(S.shot_design_units.c.id).where(S.shot_design_units.c.project_id == self.p,
                S.shot_design_units.c.artifact_id == original["id"])).scalar_one()
        note = self.artifact_note(original["id"], "director", design_unit_id=design)
        class EarlierClock(datetime):
            @classmethod
            def now(cls, tz=None):
                value = datetime.now(timezone.utc) - timedelta(hours=48)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        with patch("vsc.project.role_runtime.datetime", EarlierClock), patch("vsc.adapters.persistence.postgres.memory_store.datetime", EarlierClock):
            expired = self.write("process_review", {"artifact_note_id": note}, idempotency_key="old-professional")
        replay = self.write("process_review", {"artifact_note_id": note}, idempotency_key="old-professional")
        self.assertEqual(replay["dispatch_id"], expired["dispatch_id"])
        with self.assertRaises(ResourceError) as caught:
            self.write("process_review", {"artifact_note_id": note})
        self.assertEqual(caught.exception.code, "review_dispatch_expired")
        packet = expired["packet"]
        with self.assertRaises(ResourceError) as caught:
            self.write("consume_role_dispatch", {"dispatch_id": expired["dispatch_id"], "role_id": packet["role"]["id"],
                "instance_id": packet["dispatch"]["instance_id"], "context_sha256": packet["context_sha256"], "packet": packet}, actor=packet["dispatch"]["actor"])
        self.assertEqual(caught.exception.code, "dispatch_expired")
        new = self.write("process_review", {"artifact_note_id": note, "new_attempt": True})
        self.assertNotEqual(new["dispatch_id"], expired["dispatch_id"])
        duplicate = self.write("process_review", {"artifact_note_id": note})
        self.assertEqual(duplicate["dispatch_id"], new["dispatch_id"])
        history = self.service.get_review_history(self.p, artifact_note_id=note)
        self.assertEqual(len(history["items"][0]["responses"]), 2)

    def test_database_rejects_cross_project_wrong_artifact_empty_range_and_mutation(self):
        from sqlalchemy import insert, select, update
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        _, targets = self.render_target(objects)
        good = dict(targets[0]["target"], body="原话", author="test-human", project_id=self.p, id=str(uuid.uuid4()))
        bad_cases = [dict(good, artifact_sha256="0" * 64), dict(good, start_frame=None), dict(good, end_frame=361),
                     dict(good, media_sha256="f" * 64), dict(good, project_id=self.service.create_project({"name": "other"}, actor="test-human")["id"])]
        for payload in bad_cases:
            with self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(insert(S.artifact_review_notes).values(**payload))
        note = self.write("add_artifact_review_note", dict(targets[0]["target"], body="固定原话"))["id"]
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(S.artifact_review_notes).where(S.artifact_review_notes.c.project_id == self.p,
                S.artifact_review_notes.c.id == note).values(body="silently changed"))
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(insert(S.review_responses).values(project_id=self.p,id=str(uuid.uuid4()),action="professional",
                explanation="invalid",preserve="",limitations="",author="test-human"))
