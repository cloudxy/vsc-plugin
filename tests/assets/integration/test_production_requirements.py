"""DS10 uses real isolated PostgreSQL, fixed projections and offline byte output."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import tempfile
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture
from support.fixtures.resources import png_bytes
from vsc.configuration import get_config

TEST_URL = get_config("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires configured isolated PostgreSQL")
class ProductionRequirementsTests(ResourceStoreFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        cls.db = isolated_postgres(TEST_URL)
        cls.engine = cls.db.__enter__()
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = PostgresResourceStore(engine=cls.engine)
        cls.service = ResourceService(cls.store, LocalStorage(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        super().tearDownClass()

    def fixed(self, key, document, kind="shot-plan", dependencies=()):
        payload = {"artifact_key": key, "artifact_type": kind, "document": document, "dependency_ids": list(dependencies)}
        for field in ("asset_specs", "state_versions"):
            if field in document:
                payload[field] = document[field]
        row = self.write("create_artifact", payload)
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "explicit synthetic test decision"})
        return row

    def asset(self, code, kind="character", title="同名角色"):
        return self.write("create_object", {"kind": "asset", "asset_kind": kind, "display_code": code, "title": title})["id"]

    def episode(self, work, suffix):
        objects = {"work": work}
        parent = work
        for kind in ("episode", "scene", "sequence", "shot"):
            parent = self.write("create_object", {"kind": kind, "parent_id": parent,
                "display_code": kind.upper() + suffix, "ordinal": int(suffix)})["id"]
            objects[kind] = parent
        return objects

    def media(self, name="synthetic"):
        staged = self.service.storage.stage_upload(BytesIO(png_bytes()), name + ".png")
        row = self.write("register_media", {"name": name, "staged_upload": staged["staged_upload"],
            "source": {"kind": "test-owned", "content": name}, "rights": "owned"})
        self.write("record_media_check", {"media_id": row["id"], "checker": "fixture-probe", "criteria_version": "1", "outcome": "pass"})
        return row["id"]

    def specifications(self, assets):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        bible = self.fixed("bible", {"asset_specs": [{"asset_id": asset, "variant_key": variant}
            for asset, variants in assets.items() for variant in variants]}, "asset-bible")
        with self.engine.connect() as conn:
            specs = {(row["asset_id"], row["variant_key"]): row["id"] for row in conn.execute(
                select(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id == self.p)).mappings()}
        return bible, specs

    def requirement(self, key, scope, asset, spec=None, slot=None, **extra):
        return dict({"requirement_key": key, "category_code": "character" if asset else "prop",
            "purpose": "keyframe", "description": "fixed use " + key,
            "scene_id": scope["scene"], "shot_id": scope["shot"], "asset_id": asset,
            "spec_version_id": spec, "slots": [{"slot_id": slot}] if slot else []}, **extra)

    def preview(self, *episodes):
        return self.service.preview_production_requirements(self.p, {"episode_ids": list(episodes), "purpose": "keyframe"})

    def test_two_episodes_share_identity_references_and_future_demands_do_not_queue(self):
        first = self.hierarchy()
        second, future = self.episode(first["work"], "2"), self.episode(first["work"], "3")
        hero, location = self.asset("HERO"), self.asset("PLACE", "location")
        bible, specs = self.specifications({hero: ["master"], location: ["master"]})
        rows = []
        for asset, role in ((hero, "identity_face"), (location, "location_master")):
            candidate = self.candidate(asset, self.media(role), role=role)
            self.select(candidate)
            for index, scope in enumerate((first, second)):
                row = self.requirement(role + str(index), scope, asset, specs[asset, "master"], candidate["slot_id"])
                if index == 0:
                    row.update(shot_id=None, purpose="*")
                rows.append(row)
        for index in range(20):
            rows.append(self.requirement("future" + str(index), future, self.asset("F" + str(index))))
        self.fixed("state", {"state_versions": [{"scene_id": scope["scene"]} for scope in (first, second, future)]}, "scene-state")
        self.fixed("requirements", {"resource_requirements": rows}, dependencies=[bible["id"]])
        revision = self.rev
        result = self.preview(first["episode"], second["episode"])
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual({row["classification"] for row in result["groups"]}, {"reuse"})
        self.assertTrue(all(len(row["consumer_shot_ids"]) == 2 for row in result["groups"]))
        self.assertTrue(all(row["ready"] for row in result["shot_readiness"]), result["shot_readiness"])
        self.assertEqual(result["future_count"], 20)
        self.assertEqual(result["asset_tasks"], [])
        self.assertEqual(result["sha256"], self.preview(second["episode"], first["episode"])["sha256"])
        self.assertEqual(self.service.get_project(self.p)["revision"], revision)
        only_first = self.preview(first["episode"])
        self.assertEqual(only_first["future_count"], 22)
        self.assertTrue(all(row["consumer_shot_ids"] == [first["shot"]] for row in only_first["groups"]))
        fixed_media = result["groups"][0]["selected_media"][0]["media_id"]
        location = self.service.get_media(self.p, fixed_media)["locations"][0]
        path = self.service.storage.resolve(location["object_key"])
        original = path.read_bytes()
        try:
            path.write_bytes(b"not the approved bytes")
            broken = self.preview(first["episode"])
            self.assertTrue(all(row["classification"] != "reuse" for row in broken["groups"]))
            self.assertFalse(broken["shot_readiness"][0]["ready"])
        finally:
            path.write_bytes(original)

        # A recycled future asset must not block this episode, while a
        # reference actually consumed by the shot cannot silently survive.
        future_asset = next(row['asset_id'] for row in rows if row['requirement_key'] == 'future0')
        self.write('management_command', {'operation': 'trash', 'target_type': 'object',
            'target_id': future_asset, 'reason': 'synthetic future asset retirement'})
        self.assertTrue(self.service.compile_shot_context(self.p, first['shot'], purpose='keyframe')['ready'])
        self.write('management_command', {'operation': 'trash', 'target_type': 'object',
            'target_id': hero, 'reason': 'synthetic active reference retirement'})
        retired = self.service.compile_shot_context(self.p, first['shot'], purpose='keyframe')
        self.assertFalse(retired['ready'])
        self.assertIn('asset_recycled', {row['code'] for row in retired['gaps']})
        self.write('management_command', {'operation': 'restore', 'target_type': 'object',
            'target_id': hero, 'reason': 'synthetic restore original identity'})
        self.assertTrue(self.service.compile_shot_context(self.p, first['shot'], purpose='keyframe')['ready'])

    def test_same_name_is_not_identity_merge_and_independent_instances_survive(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        scope = self.hierarchy()
        left, right = self.asset("LEFT", "prop", "剑"), self.asset("RIGHT", "prop", "剑")
        bible, specs = self.specifications({left: ["master"], right: ["master"]})
        self.fixed("state", {"state_versions": [{"scene_id": scope["scene"]}]}, "scene-state")
        relations = self.fixed("uses", {"format": "vsc.creative-relations/v1", "project_id": self.p,
            "instances": [{"key": hand, "label": hand, "asset_id": left, "scene_id": scope["scene"],
                "shot_id": scope["shot"]} for hand in ("left", "right")]}, "creative-relations")
        with self.engine.connect() as conn:
            instances = list(conn.execute(select(S.asset_use_instances.c.id).where(S.asset_use_instances.c.project_id == self.p)).scalars())
        rows = [self.requirement("use" + str(i), scope, left, specs[left, "master"], instance_id=instance)
                for i, instance in enumerate(instances)]
        rows.append(self.requirement("same-name", scope, right, specs[right, "master"]))
        rows.extend([self.requirement("unresolved" + str(i), scope, None, description="another same name") for i in range(2)])
        self.fixed("requirements", {"resource_requirements": rows}, dependencies=[bible["id"], relations["id"]])
        result = self.preview(scope["episode"])
        self.assertEqual(len(result["groups"]), 4)
        self.assertEqual(len(result["asset_tasks"]), 2)
        self.assertTrue(all(row["execution_available"] for row in result["asset_tasks"]))
        self.assertEqual(len(next(row for row in result["groups"] if row["asset_id"] == left)["instance_ids"]), 2)
        self.assertEqual(sum(row["classification"] == "new_identity" for row in result["groups"]), 2)
        self.assertEqual(len(self.service.get_asset_usage(self.p, left)["instances"]), 2)
        # A base identity is shared, but two physical uses cannot occupy the
        # same shot-level fulfilling slot and erase left/right instance intent.
        candidate = self.candidate(scope["shot"], self.media(), role="prop", identity_asset_id=left)
        invalid = [dict(row, slots=[{"slot_id": candidate["slot_id"]}]) for row in rows[:2]]
        from vsc.assets.resource_service import ResourceError
        with self.assertRaises(ResourceError) as caught:
            self.fixed("bad-instances", {"resource_requirements": invalid}, dependencies=[bible["id"], relations["id"]])
        self.assertEqual(caught.exception.code, "resource_instance_slot_conflict")

    def test_named_variant_never_reuses_base_and_wrong_scope_is_rejected(self):
        from vsc.assets.resource_service import ResourceError
        first = self.hierarchy()
        second = self.episode(first["work"], "2")
        asset = self.asset("HERO")
        bible, specs = self.specifications({asset: ["master", "rain-night"]})
        candidate = self.candidate(asset, self.media(), role="identity_face")
        self.select(candidate)
        self.fixed("state", {"state_versions": [{"scene_id": scope["scene"]} for scope in (first, second)]}, "scene-state")
        rows = [self.requirement("base", first, asset, specs[asset, "master"], candidate["slot_id"]),
                self.requirement("rain", second, asset, specs[asset, "rain-night"], candidate["slot_id"])]
        self.fixed("requirements", {"resource_requirements": rows}, dependencies=[bible["id"]])
        result = self.preview(first["episode"], second["episode"])
        self.assertEqual({row["classification"] for row in result["groups"]}, {"reuse", "variant"})
        self.assertEqual(len(result["asset_tasks"]), 1)
        self.assertEqual(result["asset_tasks"][0]["consumer_shot_ids"], [second["shot"]])
        self.assertTrue(result["asset_tasks"][0]["execution_available"])
        self.assertFalse(next(row for row in result["shot_readiness"] if row["shot_id"] == second["shot"])["ready"])
        wrong = self.candidate(first["shot"], self.media("wrong"), role="identity_face", identity_asset_id=asset)
        with self.assertRaises(ResourceError) as caught:
            self.fixed("invalid-scope", {"resource_requirements": [self.requirement("bad", second, asset,
                specs[asset, "rain-night"], wrong["slot_id"])]}, dependencies=[bible["id"]])
        self.assertEqual(caught.exception.code, "resource_slot_mismatch")
        rain = self.candidate(asset, self.media("rain"), role="identity_face", slot_key="rain",
                              variant_spec_id=specs[asset, "rain-night"])
        self.select(rain)
        rows[1]["slots"] = [{"slot_id": rain["slot_id"]}]
        self.fixed("requirements", {"resource_requirements": rows}, dependencies=[bible["id"]])
        result = self.preview(second["episode"])
        self.assertEqual(result["groups"][0]["classification"], "reuse")
        self.assertEqual(result["asset_tasks"], [])
        self.write("retire_binding", {"slot_id": rain["slot_id"], "reason": "explicit future use retirement"})
        self.assertEqual(self.preview(second["episode"])["groups"][0]["classification"], "variant")

    def test_project_isolation_invalid_scope_and_concurrent_revision(self):
        from vsc.assets.resource_service import ResourceError, NotFound, Conflict
        scope = self.hierarchy()
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        with self.assertRaises(NotFound):
            self.service.preview_production_requirements(other, {"episode_ids": [scope["episode"]]})
        with self.assertRaises(ResourceError):
            self.preview(scope["episode"], scope["episode"])
        compile_context = self.service.compile_shot_context
        def concurrent(*args, **kw):
            result = compile_context(*args, **kw)
            self.asset("concurrent")
            return result
        with patch.object(self.service, "compile_shot_context", side_effect=concurrent), self.assertRaises(Conflict):
            self.preview(scope["episode"])

    def test_conflicting_choices_never_queue_and_scenes_without_shots_remain_future(self):
        scope, asset = self.hierarchy(), self.asset("HERO")
        bible, specs = self.specifications({asset: ["master"]})
        for key in ("a", "b"):
            self.select(self.candidate(asset, self.media(key), role="identity_face", slot_key=key))
        empty = self.write("create_object", {"kind": "scene", "parent_id": scope["episode"],
            "display_code": "FUTURE-SCENE", "ordinal": 2})["id"]
        self.fixed("state", {"state_versions": [{"scene_id": scope["scene"]}]}, "scene-state")
        rows = [self.requirement("active", scope, asset, specs[asset, "master"]),
                self.requirement("future", {"scene": empty, "shot": None}, asset, specs[asset, "master"])]
        self.fixed("requirements", {"resource_requirements": rows}, dependencies=[bible["id"]])
        result = self.preview(scope["episode"])
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["classification"], "conflict")
        self.assertEqual(result["asset_tasks"], [])
        self.assertEqual(result["future_count"], 1)

    def test_revoked_library_rights_are_not_reported_as_reusable(self):
        media = self.media("library-source")
        version = self.write("publish_library", {"library_key": "requirements-" + uuid.uuid4().hex,
            "title": "Synthetic identity reference", "category": "image", "description": "Owned fixture",
            "specification": {"style": "flat"}, "allowed_purposes": ["identity_face"],
            "license": {"outcome": "owned", "allow_workspace_reuse": True, "evidence": "synthetic bytes"},
            "members": [{"media_id": media, "member_key": "face", "role": "identity_face"}]})
        project = self.service.create_project({"name": "target", "profile_snapshot": {
            "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        self.p, self.rev = project["id"], 0
        scope, asset = self.hierarchy(), self.asset("HERO")
        bible, specs = self.specifications({asset: ["master"]})
        used = self.write("use_library", {"library_version_id": version["library_version_id"], "member_key": "face",
            "target_object_id": asset, "role": "identity_face", "select": True})
        self.fixed("state", {"state_versions": [{"scene_id": scope["scene"]}]}, "scene-state")
        self.fixed("requirements", {"resource_requirements": [self.requirement("face", scope, asset,
            specs[asset, "master"], used["slot_id"])]}, dependencies=[bible["id"]])
        self.assertEqual(self.preview(scope["episode"])["groups"][0]["classification"], "reuse")
        self.service.retire_library(version["entry_id"], {"outcome": "revoke_rights", "reason": "synthetic revocation",
            "idempotency_key": uuid.uuid4().hex}, actor="test-human")
        result = self.preview(scope["episode"])
        self.assertEqual(result["groups"][0]["classification"], "needs_reference")
        self.assertFalse(result["shot_readiness"][0]["ready"])
        self.assertEqual(result["groups"][0]["selected_media"], [])

    def test_variant_run_executes_exact_pin_and_rejects_changed_variant(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.production.bounded import execute_batch, preview_batch
        from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
        from vsc.production.resource_worker import ResourceWorker
        asset, other = self.asset("HERO"), self.asset("OTHER")
        bible, specs = self.specifications({asset: ["master", "rain-night"], other: ["master"]})
        master = self.service.compile_asset_context(self.p, asset)
        explicit_master = self.service.compile_asset_context(self.p, asset, spec_version_id=specs[asset, "master"])
        rain = self.service.compile_asset_context(self.p, asset, spec_version_id=specs[asset, "rain-night"])
        self.assertTrue(master["ready"] and rain["ready"])
        self.assertNotEqual(master["sha256"], rain["sha256"])
        with self.assertRaises(ResourceError) as caught:
            self.service.compile_asset_context(self.p, asset, spec_version_id=specs[other, "master"])
        self.assertEqual(caught.exception.code, "variant_identity_mismatch")
        provider_id = "requirements-" + uuid.uuid4().hex
        self.service.register_provider({"id": provider_id, "base_url": "https://example.invalid", "auth_ref": "SYNTHETIC"}, actor="test-human")
        model = self.service.register_model({"provider_id": provider_id, "model_key": "offline", "model_version": "1",
            "modality": "image", "capabilities": {"purposes": ["asset_ref"], "reference_media": True}}, actor="test-human")["id"]
        self.write("configure_budget", {"limits": {"remote_jobs": 5, "images": 5}, "reason": "synthetic only"})
        request = {"asset_id": asset, "purpose": "asset_ref", "modality": "image", "prompt": "Synthetic rain-night reference",
                   "spec_version_id": specs[asset, "rain-night"]}
        quote = self.service.preview_generation_quote(self.p, {"document":{"jobs":[{"model_id":model,"candidate_no":0,
            "request":dict(request, context_sha256=rain["sha256"])}]}})
        self.assertEqual(quote["generation_quote"]["native_units"]["images"], 1)
        with self.assertRaises(ResourceError):
            self.service.preview_generation_quote(self.p, {"document":{"jobs":[{"model_id":model,"candidate_no":0,
                "request":dict(request, context_sha256=explicit_master["sha256"])}]}})
        now = datetime.now(timezone.utc)
        run = self.fixed("run", {"approved_inputs": [{"id": bible["id"], "sha256": bible["sha256"]}],
            "execution_policy": {"version": "bounded-v1", "first_draft_due_at": (now + timedelta(minutes=10)).isoformat(),
                "stop_submitting_at": (now + timedelta(minutes=20)).isoformat(), "max_attempts_per_purpose": 2, "max_repair_rounds": 1},
            "jobs": [{"task_key": "rain", "model_id": model, "candidate_no": 0, "request": request}]},
            "production-run", [bible["id"]])
        payload = {"run_version_id": run["id"], "asset_id": asset, "purpose": "asset_ref", "modality": "image",
            "model_id": model, "context_sha256": explicit_master["sha256"], "request_payload": dict(request, spec_version_id=specs[asset, "master"])}
        with self.assertRaises(ResourceError) as caught:
            self.write("create_generation_job", payload)
        self.assertEqual(caught.exception.code, "run_job_unauthorized")
        self.assertEqual(preview_batch(self.service, self.p, {"run_version_id": run["id"]})["ready_count"], 1)
        started = execute_batch(self.service, self.p, {"run_version_id": run["id"]}, "test-human")
        job_id = started["tasks"][0]["job_id"]
        class OfflineProvider:
            def submit(self, request):
                return JobHandle("fixture", "offline", None, {"synthetic": True})
            def poll(self, handle):
                return JobStatus("succeeded", raw=handle.raw)
            def parse_result(self, raw):
                return [GeneratedAsset("image", inline_bytes=png_bytes())]
        result = ResourceWorker(self.service, lambda *_: OfflineProvider()).run_once(self.p)
        self.assertEqual(result["status"], "succeeded")
        detail = self.service.get_generation_job(self.p, job_id)
        self.assertEqual(detail["request_payload"]["spec_version_id"], specs[asset, "rain-night"])
        self.assertEqual(detail["context_sha256"], rain["sha256"])
        self.assertEqual(len(detail["outputs"]), 1)
        self.assertEqual(self.service.get_asset_usage(self.p, asset)["jobs"][0]["status"], "succeeded")
        self.assertEqual(len(self.service.get_asset_usage(self.p, asset)["job_outputs"]), 1)
        self.assertEqual(self.service.get_asset_usage(self.p, other)["jobs"], [])
