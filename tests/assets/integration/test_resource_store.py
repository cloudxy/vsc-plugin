"""Real PostgreSQL invariants, concurrency and frozen production evidence.

Explicit VSC_TEST_DATABASE_URL only. Each run creates/drops its own random schema;
it never resets public, an existing project, or a user's production database.
"""
import hashlib
import importlib.util
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import unittest
import uuid

from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB_DEPS = all(importlib.util.find_spec(p) for p in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires explicit VSC_TEST_DATABASE_URL and postgres dependencies")
class PostgresResourceTest(ResourceStoreFixture, unittest.TestCase):

    def test_previous_note_schema_allows_only_readonly_status_and_next(self):
        import contextlib,io,json,tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService,ResourceError
        from vsc.interfaces.cli.pg_state import handle_project_command
        from support.fixtures.postgres import isolated_postgres
        with isolated_postgres(TEST_URL) as engine, tempfile.TemporaryDirectory() as directory:
            service=ResourceService(PostgresResourceStore(engine=engine))
            project=service.create_project({'name':'Historical synthetic fixture','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='fixture-human')
            cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:
                cfg.attributes['connection']=conn;command.downgrade(cfg,'0007_script_suggestions')
            with self.assertRaises(ResourceError):service.check_schema()
            (Path(directory)/'.vsc-postgres.json').write_text(json.dumps({'project_id':project['id'],'storage_policy':'postgres-series-v1'}))
            for verb in ('status','next'):
                service.store=PostgresResourceStore(engine=engine)
                output=io.StringIO()
                with patch('vsc.bootstrap.service_from_environment',return_value=service),contextlib.redirect_stdout(output):
                    self.assertTrue(handle_project_command(SimpleNamespace(command=verb,project=directory)))
                value=json.loads(output.getvalue())
                self.assertEqual(value['schema']['migration'],'0007_script_suggestions')
                from vsc.adapters.persistence.postgres.schema import SCHEMA_REVISION
                self.assertEqual(value['schema']['required_migration'],SCHEMA_REVISION)
                self.assertTrue(value['schema']['read_only'])
                self.assertFalse(value['schema']['ready'])
                with self.assertRaises(DBAPIError),service.store.engine.begin() as conn:
                    conn.execute(text("UPDATE projects SET name='must not write' WHERE id=:id"),{'id':project['id']})
            service.store=PostgresResourceStore(engine=engine)
            with patch('vsc.bootstrap.service_from_environment',return_value=service),patch('vsc.interfaces.cli.pg_state.execute') as execute,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):handle_project_command(SimpleNamespace(command='source',project=directory))
                execute.assert_not_called()
            with engine.begin() as conn:
                self.assertEqual(conn.execute(text('SELECT name FROM projects WHERE id=:id'),{'id':project['id']}).scalar_one(),'Historical synthetic fixture')
                conn.execute(text("UPDATE alembic_version SET version_num='0006_script_workspace'"))
            service.store=PostgresResourceStore(engine=engine)
            with self.assertRaises(ResourceError):service.check_schema(read_only=True)
            with engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num='0007_script_suggestions'"))
                cfg.attributes['connection']=conn;command.upgrade(cfg,'head')
            self.assertTrue(service.check_schema()['ready'])


    def test_migration_matches_model_and_typed_hierarchy(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from vsc.adapters.persistence.postgres.schema import metadata
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        tree = self.service.get_project_tree(self.p)
        self.assertEqual([r["kind"] for r in tree["nodes"]], ["work", "episode", "scene", "sequence", "shot"])
        with self.engine.connect() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn), metadata), [])
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.works).values(project_id=self.p, id=objects["shot"], ordinal=10, object_kind="work"))

    def test_project_isolation_is_database_enforced(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import NotFound
        shot = self.hierarchy()["shot"]
        media_id = self.media()
        candidate = self.candidate(shot, media_id)
        other = self.service.create_project({"name": "另一项目"}, actor="test-human")["id"]
        with self.assertRaises(NotFound):
            self.service.get_media(other, media_id)
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.binding_candidates).values(project_id=other, id=str(uuid.uuid4()),
                    slot_id=candidate["slot_id"], media_id=media_id, proposer="test-human"))

    def test_command_receipt_replay_and_conflicting_payload(self):
        from vsc.assets.resource_service import Conflict
        payload = {"kind": "work", "display_code": "W", "ordinal": 0}
        row = self.write("create_object", payload, idempotency_key="same-command")
        replay = self.service.create_object(self.p, payload, expected_revision=0,
            idempotency_key="same-command", actor="test-human")
        self.assertEqual(replay, row)
        self.assertEqual(self.store.get_project(self.p)["revision"], 1)
        with self.assertRaises(Conflict):
            self.service.create_object(self.p, dict(payload, title="different"), expected_revision=0,
                idempotency_key="same-command", actor="test-human")

    def test_versions_bytes_and_decisions_are_immutable(self):
        from sqlalchemy import delete, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        artifact = self.artifact()
        for statement in (update(S.artifact_versions).where(S.artifact_versions.c.id == artifact).values(document=b"changed"),
                          delete(S.artifact_decisions).where(S.artifact_decisions.c.artifact_id == artifact)):
            with self.assertRaises(IntegrityError):
                with self.engine.begin() as conn:
                    conn.execute(statement)
        self.assertIn("固定规格", self.service.get_artifact_version(self.p, artifact)["content"])

    def test_projection_must_match_immutable_source(self):
        from vsc.assets.resource_service import ResourceError
        scene = self.hierarchy()["scene"]
        with self.assertRaises(ResourceError):
            self.write("create_artifact", {"artifact_key": "script", "artifact_type": "screenplay",
                "document": {"script_lines": []}, "script_lines": [{"scene_id": scene, "line_key": "L1", "text": "伪造"}]})
        self.assertEqual(self.store.get_project(self.p)["revision"], self.rev)

    def test_current_artifact_projection_preserves_approved_history(self):
        first = self.artifact("identity", "asset-bible")
        second = self.artifact("identity", "asset-bible")
        rows = self.service.list_artifacts(self.p)["items"]
        self.assertEqual([r["id"] for r in rows if r["current"]], [second])
        self.assertTrue(self.service.get_artifact_version(self.p, first)["approved"])
        self.assertTrue(self.service.get_artifact_version(self.p, second)["approved"])

    def test_unknown_rights_and_ai_review_do_not_authorize_selection(self):
        from vsc.assets.resource_service import ResourceError
        shot = self.hierarchy()["shot"]
        unknown = self.media("未授权", rights="unknown")
        candidate = self.candidate(shot, unknown)
        with self.assertRaises(ResourceError):
            self.select(candidate)
        media_id = self.media("有权利")
        other = self.write("propose_binding", {"target_object_id": shot, "media_id": media_id, "role": "first_frame"})
        self.write("record_review", {"candidate_id": other["candidate_id"], "outcome": "pass", "reason": "AI建议", "reviewer_type": "ai"})
        with self.assertRaises(ResourceError):
            self.select(other)

    def test_concurrent_selection_one_transaction_wins(self):
        from vsc.assets.resource_service import Conflict
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        shot = self.hierarchy()["shot"]
        a = self.candidate(shot, self.media("A"))
        b = self.candidate(shot, self.media("B"))
        barrier = Barrier(2)
        revision = self.rev
        def choose(candidate):
            barrier.wait(timeout=5)
            try:
                return self.service.select_candidate(self.p, {"candidate_id": candidate["candidate_id"], "reason": "并发选择"},
                    actor="test-human", expected_revision=revision, idempotency_key=uuid.uuid4().hex)
            except Conflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(choose, (a, b)))
        self.assertEqual(results.count("conflict"), 1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.current_bindings).where(S.current_bindings.c.project_id == self.p)).scalar_one(), 1)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.binding_decisions).where(S.binding_decisions.c.project_id == self.p)).scalar_one(), 1)

    def test_reject_retire_and_global_deprecation_are_distinct(self):
        from vsc.assets.resource_service import ResourceError
        shot = self.hierarchy()["shot"]
        image = self.media()
        a = self.candidate(shot, image)
        chosen = self.select(a)
        b = self.candidate(shot, image, role="last_frame")
        self.write("reject_candidate", {"candidate_id": b["candidate_id"], "reason": "该用途不匹配"})
        self.assertEqual(len(self.service.get_media_usage(self.p, image)["current_bindings"]), 1)
        self.write("decide_media_lifecycle", {"media_id": image, "outcome": "deprecate", "reason": "停用新用途"})
        with self.assertRaises(ResourceError):
            self.select(b)
        self.assertEqual(len(self.service.get_media_usage(self.p, image)["current_bindings"]), 1)
        self.write("retire_binding", {"slot_id": a["slot_id"], "reason": "今后不再使用"})
        self.assertEqual(self.service.get_media_usage(self.p, image)["current_bindings"], [])
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            self.assertIsNotNone(conn.execute(select(S.binding_decisions).where(S.binding_decisions.c.id == chosen["decision_id"])).first())

    def test_composite_repeated_inputs_and_cycle_guard(self):
        from vsc.assets.resource_service import ResourceError
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        window, composite = self.media("窗景"), self.media("合成房间")
        operation = self.write("create_media_operation", {"operation_type": "composite", "recipe_version": "1", "tool": "test", "tool_version": "1",
            "inputs": [{"media_id": window, "transform": {"x": 10}}, {"media_id": window, "transform": {"x": 50}}],
            "outputs": [{"media_id": composite}]})
        lineage = self.service.get_media_lineage(self.p, composite)
        self.assertEqual(len(lineage["inputs"]), 2)
        self.assertEqual({r["transform"]["x"] for r in lineage["inputs"]}, {10, 50})
        with self.assertRaises(ResourceError):
            self.write("create_media_operation", {"operation_type": "cycle", "recipe_version": "1", "tool": "test", "tool_version": "1",
                "inputs": [{"media_id": composite}], "outputs": [{"media_id": window}]})
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.operation_inputs).values(project_id=self.p, id=str(uuid.uuid4()), operation_id=operation["id"],
                    media_id=window, role="layer", layer_order=3, transform={}, opacity=1))

    def test_structured_reverse_usage_and_historical_media(self):
        self.seed_generation_timeline_render()

    def test_preview_jobs_are_durable_without_becoming_production_media(self):
        image = self.media()
        a = self.write("create_preview_job", {"media_id": image, "purpose": "thumbnail", "recipe_version": "1"})
        b = self.write("create_preview_job", {"media_id": image, "purpose": "thumbnail", "recipe_version": "1"})
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(self.service.list_resources(self.p)["total"], 1)

    def ready_job(self, candidate_count=1):
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        self.artifact("state", "scene-state", [objects["scene"]], {"state_versions": [{"scene_id": objects["scene"]}]})
        first = self.media("worker首帧")
        self.select(self.candidate(objects["shot"], first))
        request = {"prompt": "固定描述", "params": {"seed": 123}, "first_frame_media_id": first}
        run = self.production_run(objects["shot"], request, candidate_count=candidate_count)
        provider_id = "offline_" + uuid.uuid4().hex
        self.service.register_provider({"id": provider_id, "base_url": "https://example.invalid", "auth_ref": "OFFLINE_TEST_KEY"}, actor="test-admin")
        model = self.service.register_model({"provider_id": provider_id, "model_key": "fake-video", "model_version": "1", "modality": "video",
            "capabilities": {"purposes": ["video_clip"], "first_frame": True}}, actor="test-admin")
        self.service.register_route({"modality": "video", "purpose": "video_clip", "preferred_provider": provider_id}, actor="test-admin")
        context = self.service.compile_shot_context(self.p, objects["shot"], purpose="video_clip")
        job = self.write("create_generation_job", {"run_version_id": run, "shot_id": objects["shot"], "purpose": "video_clip", "modality": "video",
            "model_id": model["id"], "context_sha256": context["sha256"], "request_payload": request})
        return job, model

    def test_standard_documents_project_without_rewriting_and_ignore_unrelated_bible_changes(self):
        import copy
        import json
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        char = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "CHAR"})["id"]
        room = self.write("create_object", {"kind": "asset", "asset_kind": "location", "display_code": "ROOM"})["id"]
        other = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "OTHER"})["id"]
        self.select(self.candidate(char, self.media("角色参考"), role="identity_face"))
        self.select(self.candidate(room, self.media("场景母版"), role="location_master"))
        bible = {"format": "vsc.asset-bible/v1", "project_id": self.p, "entities": [
            {"id": "CHAR", "kind": "character", "name": "人物", "identity": ["左眉有疤"], "variants": {"default": "蓝衣"}},
            {"id": "ROOM", "kind": "location", "name": "房间", "identity": ["门在右侧"], "variants": {"default": "日光"}}]}
        def save_bible(document):
            raw = json.dumps(document, ensure_ascii=False, indent=2)
            row = self.write("create_artifact", {"artifact_key": "bible", "artifact_type": "vsc.asset_bible", "document": raw})
            self.write("decide_artifact", {"artifact_id": row["id"], "reason": "批准原规范资产"})
            self.assertEqual(self.service.get_artifact_version(self.p, row["id"])["document"], raw)
            self.assertEqual(row["sha256"], hashlib.sha256(raw.encode()).hexdigest())
            return row["id"]
        original_bible = save_bible(bible)
        state = {"format": "vsc.scene-state/v1", "project_id": self.p, "scenes": [{"id": "SCENE", "location_id": "ROOM",
            "baseline": {"entities": {"CHAR": {"variant": "default", "position": "门边"}}},
            "shots": [{"id": "SHOT", "in_frame": ["CHAR"], "changes": {}}]}]}
        row = self.write("create_artifact", {"artifact_key": "state", "artifact_type": "vsc.scene_state", "document": state})
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "批准逐镜状态"})
        before = self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")
        self.assertTrue(before["ready"], before["gaps"])
        # Migrated historical review slots remain queryable without becoming
        # required production inputs or changing a shot's fixed context.
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.begin() as conn:
            conn.execute(insert(S.binding_slots).values(project_id=self.p, id=str(uuid.uuid4()),
                target_object_id=objects["shot"], role="legacy_review", slot_key="legacy:run:task"))
        historical = self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")
        self.assertTrue(historical["ready"], historical["gaps"])
        self.assertEqual(historical["sha256"], before["sha256"])
        unchanged = copy.deepcopy(bible)
        unchanged["entities"].append({"id": "OTHER", "kind": "character", "name": "另一人物", "identity": ["长发"], "variants": {"default": "红衣"}})
        save_bible(unchanged)
        after = self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")
        self.assertEqual(after["sha256"], before["sha256"])
        changed = copy.deepcopy(unchanged)
        changed["entities"][0]["identity"] = ["左眉没有疤"]
        save_bible(changed)
        self.assertNotEqual(self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")["sha256"], before["sha256"])
        fixed = self.service.get_artifact_version(self.p, original_bible)
        pinned = self.write("create_artifact", {"artifact_key": "shot", "artifact_type": "shot-plan", "object_ids": [objects["shot"]],
            "document": {"spec": "固定规格"}, "asset_versions": {asset: {"id": original_bible, "sha256": fixed["sha256"]} for asset in (char, room)}})
        self.write("decide_artifact", {"artifact_id": pinned["id"], "reason": "明确固定每资产版本"})
        stable = self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")
        self.assertTrue(stable["ready"], stable["gaps"])
        self.assertEqual(len(self.service.get_artifact_version(self.p, pinned["id"])["asset_versions"]), 2)
        changed["entities"][0]["identity"] = ["又一版人物"]
        save_bible(changed)
        self.assertEqual(self.service.compile_shot_context(self.p, objects["shot"], "shot_keyframe")["sha256"], stable["sha256"])

    def test_first_asset_reference_job_requires_no_self_reference_and_pins_identity_spec(self):
        from vsc.assets.resource_service import ResourceError
        char = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "INITIAL_CHAR"})["id"]
        spec_id = str(uuid.uuid4())
        bible = self.artifact("initial-bible", "asset-bible", objects=[char], projections={
            "asset_specs": [{"id": spec_id, "asset_id": char, "variant_key": "master"}]})
        context = self.service.compile_asset_context(self.p, char, "identity_ref")
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["media"], [])
        self.assertEqual([a["id"] for a in context["artifacts"]], [bible])
        pins = [{"id": a["id"], "sha256": a["sha256"]} for a in context["artifacts"]]
        request = {"shot_id": None, "asset_id": char, "purpose": "identity_ref", "modality": "image", "prompt": "人物首个参考：蓝衣，左眉有疤"}
        run = self.write("create_artifact", {"artifact_key": "asset-run", "artifact_type": "production-run",
            "document": {"approved_inputs": pins, "jobs": [{"request": request}]}, "dependency_ids": [bible], "object_ids": [char]})
        self.write("decide_artifact", {"artifact_id": run["id"], "reason": "批准第一张参考请求"})
        provider = "offline_" + uuid.uuid4().hex
        self.service.register_provider({"id": provider, "base_url": "https://example.invalid", "auth_ref": "OFFLINE_TEST_KEY"}, actor="test-admin")
        model = self.service.register_model({"provider_id": provider, "model_key": "fake-image", "model_version": "1", "modality": "image",
            "capabilities": {"purposes": ["identity_ref"]}}, actor="test-admin")
        job = self.write("create_generation_job", {"run_version_id": run["id"], "asset_id": char, "purpose": "identity_ref", "modality": "image",
            "model_id": model["id"], "context_sha256": context["sha256"], "request_payload": request})
        saved = self.service.get_generation_job(self.p, job["id"])
        self.assertIsNone(saved["shot_id"])
        self.assertEqual(saved["asset_id"], char)
        self.assertEqual(saved["input_media"], [])
        self.assertEqual(saved["input_versions"][0]["artifact_id"], bible)
        with self.assertRaises(ResourceError):
            self.write("create_generation_job", {"run_version_id": run["id"], "asset_id": char, "purpose": "voice_clone", "modality": "audio",
                "model_id": model["id"], "context_sha256": context["sha256"], "request_payload": request})

    def test_managed_native_budget_unknown_reservation_blocks_next_submission(self):
        from vsc.assets.resource_service import Conflict
        project = self.service.create_project({"name": "预算测试", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": [], "contract_policy": "production-v2"}}, actor="test-human")
        self.p, self.rev = project["id"], 0
        first, model = self.ready_job(candidate_count=2)
        detail = self.service.get_generation_job(self.p, first["id"])
        request = {k: v for k, v in detail["request_payload"].items() if k not in {"input_media", "input_versions"}}
        second = self.write("create_generation_job", {"run_version_id": detail["run_version_id"], "shot_id": detail["shot_id"], "candidate_no": 1,
            "purpose": detail["purpose"], "modality": "video", "model_id": model["id"], "context_sha256": detail["context_sha256"], "request_payload": request})
        self.write("configure_budget", {"limits": {"remote_jobs": 1, "video_seconds": 5}, "reason": "限定单次试制"})
        a = self.service.claim_generation_job("budget-a", project_id=self.p)
        b = self.service.claim_generation_job("budget-b", project_id=self.p)
        self.rev = b["revision"]
        self.write("mark_submission_started", {"job_id": a["id"], "worker_id": "budget-a"})
        with self.assertRaises(Conflict) as caught:
            self.write("mark_submission_started", {"job_id": b["id"], "worker_id": "budget-b"})
        self.assertEqual(caught.exception.code, "budget_exceeded")
        self.assertEqual(self.service.budget_status(self.p)["used"], {"remote_jobs": 1, "video_seconds": 5})
        self.write("update_generation_job", {"job_id": a["id"], "worker_id": "budget-a", "status": "failed", "recovery_evidence": {"human_confirmed_not_submitted": True},
            "actual_units": {"remote_jobs": 0, "video_seconds": 0}})
        self.write("mark_submission_started", {"job_id": b["id"], "worker_id": "budget-b"})
        self.assertEqual(self.service.budget_status(self.p)["remaining"], {"remote_jobs": 0, "video_seconds": 0})

    def test_original_timeline_projects_explicit_selected_media_without_changing_bytes(self):
        import json
        from vsc.assets.resource_service import ResourceError
        objects = self.hierarchy()
        video = self.media("原格式获选视频", modality="video")
        decision = self.select(self.candidate(objects["shot"], video, role="video_take"))
        media = self.service.get_media(self.p, video)
        source = self.artifact("source", "manual-import")
        source_ref = self.service.get_artifact_version(self.p, source)
        selected_doc = {"format": "vsc.selected-takes/v1", "project_id": self.p, "scope": "EPISODE", "items": [{
            "id": "SEL1", "shot_id": "SHOT", "take_id": "TK1", "output_id": "OUT1", "scope": "EPISODE", "purpose": "visual", "usage_rights": "owned",
            "selected_by": "test-human", "media": {"path": "media/video.mp4", "sha256": media["sha256"]},
            "source": {"kind": "manual", "artifact": {"id": source, "sha256": source_ref["sha256"]}, "imported_by": "test-human", "provenance": "Synthetic test bytes"}}]}
        selected = self.write("create_artifact", {"artifact_key": "selected", "artifact_type": "vsc.selected_takes", "document": selected_doc, "dependency_ids": [source]})
        self.write("decide_artifact", {"artifact_id": selected["id"], "reason": "批准固定选择清单"})
        timeline_doc = {"format": "vsc.timeline/v1", "project_id": self.p, "scope": "EPISODE",
            "selected_takes": {"id": selected["id"], "sha256": selected["sha256"]}, "sound_plans": [],
            "render_plan": {"format": "vsc.remotion-render-plan/v1", "project_id": self.p,
                "composition": {"id": "Fixture", "width": 320, "height": 240, "fps": 24, "duration_in_frames": 24},
                "segments": [{"id": "V1", "kind": "video", "source": "media/video.mp4", "source_shot_id": "SHOT", "from_frame": 0, "duration_in_frames": 24, "muted": True}]},
            "bindings": [{"segment_id": "V1", "selected_item_id": "SEL1", "sha256": media["sha256"], "purpose": "visual", "usage_rights": "owned", "audio_role": "none", "cue_id": None}]}
        raw = json.dumps(timeline_doc, ensure_ascii=False, indent=2)
        timeline = self.write("create_artifact", {"artifact_key": "timeline", "artifact_type": "vsc.timeline", "document": raw, "dependency_ids": [selected["id"]]})
        self.write("decide_artifact", {"artifact_id": timeline["id"], "reason": "批准原格式时间线"})
        with self.assertRaises(ResourceError) as caught:
            self.write("freeze_timeline", {"artifact_id": timeline["id"], "episode_id": objects["episode"]})
        self.assertEqual(caught.exception.code, "selected_media_mapping_required")
        frozen = self.write("freeze_timeline", {"artifact_id": timeline["id"], "episode_id": objects["episode"],
            "selected_media": {"SEL1": {"media_id": video, "binding_decision_id": decision["decision_id"]}}})
        self.assertEqual(len(self.store.get_timeline_media(self.p, frozen["id"])), 1)
        exported = self.service.get_timeline(self.p, frozen["id"])
        self.assertEqual(exported["artifact"]["document"], raw)
        self.assertEqual(exported["items"][0]["ordinal"], 0)
        self.assertEqual(exported["items"][0]["media"][0]["blob_sha256"], media["sha256"])
        self.assertEqual(exported["items"][0]["media"][0]["mime_type"], "video/mp4")
        self.assertEqual(self.service.get_artifact_version(self.p, timeline["id"])["document"], raw)

    def test_original_coverage_uses_declared_script_version_and_exact_character_range(self):
        import json
        from vsc.assets.resource_service import ResourceError
        objects = self.hierarchy()
        self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "CHAR"})
        adaptation = self.artifact("adaptation", "adaptation-plan")
        shot = self.artifact("shot", "shot-plan")
        sound = self.artifact("sound", "sound-plan")
        def ref(row_id):
            row = self.service.get_artifact_version(self.p, row_id)
            return {"id": row_id, "sha256": row["sha256"]}
        script_doc = {"format": "vsc.screenplay/v1", "project_id": self.p, "scope": "EPISODE", "body": "测试对白原稿",
            "adaptation_refs": [ref(adaptation)], "scenes": [{"id": "SCENE", "estimated_duration_ms": 5000,
                "actions": [], "dialogue": [{"id": "L1", "speaker": "CHAR", "text": "前半句，后半句。", "narrative_refs": ["N1"]}], "silence": []}]}
        script = self.write("create_artifact", {"artifact_key": "script", "artifact_type": "vsc.screenplay", "document": script_doc, "dependency_ids": [adaptation]})
        self.write("decide_artifact", {"artifact_id": script["id"], "reason": "批准固定剧本"})
        coverage_doc = {"format": "vsc.coverage-plan/v1", "project_id": self.p, "scope": "EPISODE", "screenplay": ref(script["id"]), "omissions": [],
            "scenes": [{"id": "SCENE", "sequences": [{"id": "SEQUENCE", "shot_plan": ref(shot), "sound_plan": ref(sound),
                "shots": [{"id": "SHOT", "screenplay_unit_ids": ["L1"], "line_ranges": [{"line_id": "L1", "start_char": 4, "end_char": 8}]}]}]}]}
        raw = json.dumps(coverage_doc, ensure_ascii=False, indent=2)
        with self.assertRaises(ResourceError):
            self.write("create_artifact", {"artifact_key": "bad-coverage", "artifact_type": "vsc.coverage_plan", "document": raw})
        coverage = self.write("create_artifact", {"artifact_key": "coverage", "artifact_type": "vsc.coverage_plan", "document": raw,
            "dependency_ids": [script["id"], shot, sound]})
        self.write("decide_artifact", {"artifact_id": coverage["id"], "reason": "批准覆盖范围"})
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            row = conn.execute(select(S.shot_line_coverage, S.script_lines.c.script_version_id).select_from(
                S.shot_line_coverage.join(S.script_lines, (S.shot_line_coverage.c.project_id == S.script_lines.c.project_id) & (S.shot_line_coverage.c.line_id == S.script_lines.c.id)))
                .where(S.shot_line_coverage.c.coverage_version_id == coverage["id"], S.shot_line_coverage.c.project_id == self.p)).mappings().one()
            self.assertEqual((row["start_char"], row["end_char"], row["script_version_id"]), (4, 8, script["id"]))
        self.assertEqual(coverage["sha256"], hashlib.sha256(raw.encode()).hexdigest())

    def test_supersedes_drafts_cannot_replace_another_approved_revision(self):
        from vsc.assets.resource_service import Conflict
        old = self.artifact("spec", "shot-plan")
        payload = {"artifact_key": "spec", "artifact_type": "shot-plan", "document": {"spec": "新规格"}, "supersedes_id": old}
        a = self.write("create_artifact", payload)
        b = self.write("create_artifact", dict(payload, document={"spec": "另一个草稿"}))
        self.write("decide_artifact", {"artifact_id": a["id"], "reason": "批准A替代旧版"})
        with self.assertRaises(Conflict) as caught:
            self.write("decide_artifact", {"artifact_id": b["id"], "reason": "旧B不能覆盖A"})
        self.assertEqual(caught.exception.code, "supersedes_stale")
        self.assertTrue(self.service.get_artifact_version(self.p, old)["approved"])

    def test_worker_claims_once_and_unknown_submission_never_reposts(self):
        from vsc.assets.resource_service import Conflict
        job, model = self.ready_job()
        barrier = Barrier(2)
        def claim(worker):
            barrier.wait(timeout=5)
            return self.service.claim_generation_job(worker, project_id=self.p)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(claim, ("worker-one", "worker-two")))
        self.assertEqual(sum(item is not None for item in claimed), 1)
        claim = next(item for item in claimed if item is not None)
        self.rev = claim["revision"]
        self.assertEqual(claim["request_payload"]["input_media"][0]["media_id"], claim["input_media"][0]["media_id"])
        self.assertEqual(claim["request_payload"]["context_sha256"], claim["context_sha256"])
        with self.assertRaises(Conflict):
            self.write("mark_submission_started", {"job_id": job["id"], "worker_id": "wrong-worker"})
        self.write("mark_submission_started", {"job_id": job["id"], "worker_id": claim["claim_owner"]})
        self.assertIsNone(self.service.claim_generation_job("another-worker", project_id=self.p))
        self.write("update_generation_job", {"job_id": job["id"], "worker_id": claim["claim_owner"], "status": "submitted", "external_task_id": "lease-test-task",
            "recovery_evidence": {"source": "actual provider response"}})
        poll = self.service.claim_generation_job("poll-worker", project_id=self.p, statuses=("submitted", "running"))
        self.assertEqual(poll["status"], "submitted")
        self.assertEqual(poll["attempt"], 1)

    def test_model_version_is_immutable_and_expired_worker_cannot_submit(self):
        from vsc.assets.resource_service import Conflict
        from sqlalchemy import update
        from datetime import datetime, timedelta, timezone
        from vsc.adapters.persistence.postgres import schema as S
        job, model = self.ready_job()
        with self.assertRaises(Conflict):
            self.service.register_model({"provider_id": model["provider_id"], "model_key": model["model_key"], "model_version": "1",
                "modality": "video", "capabilities": {"voice_clone": True}}, actor="test-admin")
        first = self.service.claim_generation_job("old-worker", project_id=self.p)
        self.rev = first["revision"]
        with self.engine.begin() as conn:
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.id == job["id"], S.generation_jobs.c.project_id == self.p)
                .values(claim_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        with self.assertRaises(Conflict):
            self.write("mark_submission_started", {"job_id": job["id"], "worker_id": "old-worker"})
        second = self.service.claim_generation_job("new-worker", project_id=self.p)
        self.assertEqual(second["id"], job["id"])
        self.assertEqual(second["claim_owner"], "new-worker")

    def test_sixty_episode_capacity_pagination_and_inverse_index(self):
        """Synthetic 60 x 36 x 5s, 10k blobs; bounded page and real reverse join."""
        from sqlalchemy import event, insert
        from vsc.adapters.persistence.postgres import schema as S
        work_id = str(uuid.uuid4())
        objects = [{"project_id": self.p, "id": work_id, "kind": "work", "display_code": "W", "title": "合成容量样本"}]
        episodes, scenes, sequences, shots = [], [], [], []
        for episode in range(60):
            episode_id, scene_id, sequence_id = [str(uuid.uuid4()) for _ in range(3)]
            for kind, row_id in (("episode", episode_id), ("scene", scene_id), ("sequence", sequence_id)):
                objects.append({"project_id": self.p, "id": row_id, "kind": kind, "display_code": "%s-%03d" % (kind, episode), "title": kind})
            episodes.append({"project_id": self.p, "id": episode_id, "parent_id": work_id, "ordinal": episode})
            scenes.append({"project_id": self.p, "id": scene_id, "parent_id": episode_id, "ordinal": 0})
            sequences.append({"project_id": self.p, "id": sequence_id, "parent_id": scene_id, "ordinal": 0})
            for shot in range(36):
                shot_id = str(uuid.uuid4())
                objects.append({"project_id": self.p, "id": shot_id, "kind": "shot", "display_code": "E%03d-SH%03d" % (episode, shot), "title": "镜"})
                shots.append({"project_id": self.p, "id": shot_id, "parent_id": sequence_id, "ordinal": shot, "duration_ms": 5000})
        blobs, locations, media = [], [], []
        for number in range(10000):
            blob_id, media_id = str(uuid.uuid4()), str(uuid.uuid4())
            sha = hashlib.sha256((self.p + str(number)).encode()).hexdigest()
            blobs.append({"id": blob_id, "sha256": sha, "size_bytes": 100, "mime_type": "image/png", "probe": {}})
            locations.append({"id": str(uuid.uuid4()), "blob_id": blob_id, "storage": "local", "object_key": sha + ".png"})
            media.append({"project_id": self.p, "id": media_id, "blob_id": blob_id, "name": "图%05d" % number, "modality": "image", "registered_by": "capacity-fixture"})
        slots, candidates = [], []
        for number, shot in enumerate(shots):
            slot_id = str(uuid.uuid4())
            slots.append({"project_id": self.p, "id": slot_id, "target_object_id": shot["id"], "role": "first_frame", "slot_key": "main"})
            for candidate in range(5):
                candidates.append({"project_id": self.p, "id": str(uuid.uuid4()), "slot_id": slot_id,
                    "media_id": media[(number * 5 + candidate) % len(media)]["id"], "proposer": "capacity-fixture"})
        with self.engine.begin() as conn:
            conn.execute(insert(S.creative_objects), objects)
            conn.execute(insert(S.works), [{"project_id": self.p, "id": work_id, "ordinal": 0}])
            for table, rows in ((S.episodes, episodes), (S.scenes, scenes), (S.sequences, sequences), (S.shots, shots),
                                (S.media_blobs, blobs), (S.blob_locations, locations), (S.media_items, media),
                                (S.binding_slots, slots), (S.binding_candidates, candidates)):
                conn.execute(insert(table), rows)
        statements = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", observe)
        start = time.perf_counter()
        try:
            page = self.service.list_resources(self.p, offset=5000, limit=50)
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        elapsed = time.perf_counter() - start
        self.assertEqual(page["total"], 10000)
        self.assertEqual(len(page["items"]), 50)
        self.assertLessEqual(len(statements), 10, "one batched query per relation, never one per card")
        self.assertLess(elapsed, 10, "bounded indexed page should not scan/decode all media bytes")
        usage = self.service.get_media_usage(self.p, media[0]["id"])
        self.assertEqual(len(usage["candidates"]), 2)
        self.assertEqual(len(self.service.get_project_tree(self.p)["nodes"]), 2341)


if __name__ == "__main__":
    unittest.main()
