"""B3-07–09 through real migrations, APIs and random PostgreSQL schemas only."""
import copy
import json
import os
import unittest
import uuid

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS,
    "requires explicit isolated PostgreSQL test connection")
class ResourceModelPostgresTests(ResourceStoreFixture, unittest.TestCase):
    def asset(self, kind, code=None):
        return self.write("create_object", {"kind": "asset", "asset_kind": kind,
            "display_code": code or kind.upper(), "title": code or kind})["id"]

    def fixed(self, key, document, *, kind="shot-plan", dependencies=(), objects=()):
        payload = {"artifact_key": key, "artifact_type": kind,
            "document": document, "dependency_ids": list(dependencies), "object_ids": list(objects)}
        for field in ("state_versions", "script_lines", "asset_specs"):
            if field in document:
                payload[field] = document[field]
        row = self.write("create_artifact", payload)
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "合成测试人工决定"})
        return row

    def test_legal_kinds_bible_roundtrip_and_mismatch_rejected(self):
        from vsc.assets.resource_service import ResourceError
        assets = {kind: self.asset(kind) for kind in ("creature", "vehicle", "object", "plant")}
        doc = {"format": "vsc.asset-bible/v1", "project_id": self.p, "entities": [
            {"id": kind.upper(), "name": "合成" + kind, "kind": kind, "identity": [],
             "variants": {"default": "合成规格"}} for kind in assets]}
        fixed = self.fixed("bible", doc, kind="vsc.asset_bible")
        mapping = self.store.get_projection_id_map(self.p)
        self.assertTrue(all(kind.upper() + ":default" in mapping["asset_specs"] for kind in assets))
        rows = self.service.browse_resources(self.p, target_type="identity")
        self.assertEqual({row["kind"] for row in rows["items"]}, set(assets))
        changed = copy.deepcopy(doc)
        changed["entities"][0]["kind"] = "prop"
        with self.assertRaises(ResourceError) as caught:
            self.fixed("bad-bible", changed, kind="vsc.asset_bible")
        self.assertEqual(caught.exception.code, "asset_kind_mismatch")
        self.assertEqual(self.service.get_artifact_version(self.p, fixed["id"])["sha256"], fixed["sha256"])

    def test_eleven_typed_categories_sql_pages_and_project_isolation(self):
        from vsc.assets.resource_service import NotFound, ResourceError
        from vsc.assets.taxonomy import TOP_LEVEL_CATEGORIES
        from sqlalchemy import insert, update
        from sqlalchemy.exc import IntegrityError, DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        voice = self.asset("voice")
        self.assertEqual(self.service.browse_resources(self.p, category="sound")["items"][0]["target_id"], voice)
        self.assertEqual(self.service.browse_resources(self.p, category="character")["items"][0]["target_id"], voice)
        media = self.media("multi-category")
        artifact = self.fixed("resource-doc", {"text": "固定文档"}, kind="resource-spec")
        for n, category in enumerate(TOP_LEVEL_CATEGORIES):
            target_type, target_id = (("identity", voice), ("media", media), ("artifact", artifact["id"]))[n % 3]
            self.write("classify_resource", {"target_type": target_type, "target_id": target_id, "category_code": category})
            found = self.service.browse_resources(self.p, category=category)
            self.assertIn(target_id, {row["target_id"] for row in found["items"]})
            self.assertTrue(all(not row["execution_available"] for row in found["items"]))
        first = self.service.browse_resources(self.p, limit=1)
        second = self.service.browse_resources(self.p, limit=1, offset=first["next_offset"])
        self.assertNotEqual(first["items"][0]["target_id"], second["items"][0]["target_id"])
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        with self.assertRaises(NotFound):
            self.service.get_asset_usage(other, voice)
        with self.assertRaises(ResourceError):
            self.write("classify_resource", {"target_type": "media", "target_id": media, "category_code": "unknown"})
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.media_category_links).values(project_id=other, media_id=media,
                category_code="sound", registered_by="test"))
        # A cycle in one INSERT statement is rejected by the database itself.
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(insert(S.asset_categories), [dict(code="cycle.a", label="a", ordinal=0, parent_code="cycle.b"),
                dict(code="cycle.b", label="b", ordinal=0, parent_code="cycle.a")])
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(S.identity_category_links).where(S.identity_category_links.c.project_id == self.p)
                .values(category_code="prop"))

    def test_design_versions_panels_scope_and_deterministic_projection(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        second = self.write("create_object", {"kind": "shot", "display_code": "SHOT2",
            "parent_id": objects["sequence"], "ordinal": 1})["id"]
        panel = self.media("shared-panel")
        doc = {"project_id": self.p, "design_units": [{"design_key": "design-a", "scene_id": objects["scene"],
            "picture": "合成画面", "action": "转身", "camera": {"motion": "pan"}, "duration_ms": 6000,
            "shots": [{"shot_id": objects["shot"]}, {"shot_id": second}],
            "panels": [{"panel_key": "p1", "media_id": panel, "picture": "左侧"},
                       {"panel_key": "p2", "media_id": panel, "picture": "右侧"}]}]}
        first = self.fixed("design", doc, objects=[objects["scene"]])
        with self.engine.begin() as conn:
            self.store._project_resource_model(conn, self.store._project(conn, self.p), first["id"], doc)
            self.assertEqual(len(conn.execute(select(S.shot_design_units).where(
                S.shot_design_units.c.project_id == self.p)).all()), 1)
        before = self.service.get_shot_designs(self.p, shot_id=objects["shot"])["units"]
        self.assertEqual(len(before[0]["panels"]), 2)
        self.assertEqual({row["media_id"] for row in before[0]["panels"]}, {panel})
        revised = copy.deepcopy(doc)
        revised["design_units"][0]["action"] = "停住"
        latest = self.fixed("design", revised, objects=[objects["scene"]])
        versions = self.service.get_shot_designs(self.p, shot_id=second)["units"]
        self.assertEqual({row["artifact_id"] for row in versions}, {first["id"], latest["id"]})
        self.assertEqual(self.service.get_shot_designs(self.p, artifact_id=first["id"])["units"][0]["content"]["action"], "转身")
        self.assertEqual(len(self.service.get_shot_designs(self.p, object_id=objects["episode"])["units"]), 2)
        foreign = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        self.assertEqual(self.service.get_shot_designs(foreign)["units"], [])

    def test_location_reuse_shot_override_scope_and_database_guards(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        location, insert_location = self.asset("location", "PLACE"), self.asset("location", "INSERT")
        rows = [{"scene_id": objects["scene"], "location_id": location},
            {"scene_id": objects["scene"], "shot_id": objects["shot"], "location_id": insert_location}]
        for n in range(1, 3):
            ep = self.write("create_object", {"kind": "episode", "display_code": "EP" + str(n), "parent_id": objects["work"], "ordinal": n})["id"]
            scene = self.write("create_object", {"kind": "scene", "display_code": "SC" + str(n), "parent_id": ep, "ordinal": 0})["id"]
            rows.append({"scene_id": scene, "location_id": location})
        art = self.fixed("locations", {"scene_locations": rows}, kind="scene-state")
        usage = self.service.get_asset_usage(self.p, location)
        self.assertEqual(len(usage["locations"]), 3)
        scoped = self.service.get_scene_locations(self.p, shot_id=objects["shot"])["locations"]
        self.assertEqual({row["location_id"] for row in scoped if row["effective"]}, {insert_location})
        self.assertEqual(len(self.service.get_scene_locations(self.p, object_id=objects["episode"])["locations"]), 2)
        self.assertEqual(self.service.browse_resources(self.p, object_id=objects["episode"], category="environment")["total"], 2)
        nonlocation = self.asset("prop")
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(insert(S.scene_location_refs).values(project_id=self.p, id=str(uuid.uuid4()), artifact_id=art["id"],
                source_sha256=art["sha256"], scene_id=objects["scene"], location_id=nonlocation, role="insert", ordinal=99))

    def test_requirements_distinguish_absence_unmet_and_independent_instances(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        cup = self.asset("prop", "CUP")
        self.assertFalse(self.service.get_resource_requirements(self.p)["has_requirements"])
        bible = self.fixed("cup-spec", {"asset_specs": [{"asset_id": cup, "variant_key": "master"}]}, kind="asset-bible")
        self.fixed("state", {"state_versions": [{"scene_id": objects["scene"]}]}, kind="scene-state")
        instances = [{"key": hand, "label": hand, "asset_id": cup, "scene_id": objects["scene"],
            "shot_id": objects["shot"]} for hand in ("left", "right")]
        relations = self.fixed("instances", {"format": "vsc.creative-relations/v1", "project_id": self.p,
            "instances": instances}, kind="creative-relations")
        with self.engine.connect() as conn:
            uses = {row["instance_key"]: row["id"] for row in conn.execute(select(S.asset_use_instances).where(
                S.asset_use_instances.c.project_id == self.p)).mappings()}
            spec = conn.execute(select(S.asset_spec_versions.c.id).where(S.asset_spec_versions.c.project_id == self.p,
                S.asset_spec_versions.c.asset_id == cup)).scalar_one()
        candidates = [self.candidate(objects["shot"], self.media(hand), role="prop", slot_key=hand,
            identity_asset_id=cup) for hand in ("left", "right")]
        for candidate in candidates:
            self.select(candidate)
        requirements = [{"requirement_key": hand, "category_code": "prop", "purpose": "keyframe", "description": "合成杯子" + hand,
            "scene_id": objects["scene"], "shot_id": objects["shot"], "asset_id": cup, "instance_id": uses[hand],
            "spec_version_id": spec,
            "slots": [{"slot_id": candidate["slot_id"]}]} for hand, candidate in zip(("left", "right"), candidates)]
        self.fixed("requirements", {"resource_requirements": requirements}, dependencies=[relations["id"], bible["id"]])
        result = self.service.get_resource_requirements(self.p, shot_id=objects["shot"])
        self.assertEqual(result["unmet_count"], 0)
        before = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertTrue(before["ready"], before["gaps"])
        self.assertEqual({row["slot_id"] for row in before["media"]}, {candidate["slot_id"] for candidate in candidates})
        self.write("retire_binding", {"slot_id": candidates[0]["slot_id"], "reason": "只替换左杯"})
        result = self.service.get_resource_requirements(self.p, object_id=objects["episode"])
        self.assertEqual({row["requirement_key"]: row["status"] for row in result["requirements"]},
            {"left": "unmet", "right": "satisfied"})
        self.assertEqual(len(self.service.get_asset_usage(self.p, cup)["instances"]), 2)
        new_left = self.candidate(objects["shot"], self.media("new-left"), role="prop", slot_key="left", identity_asset_id=cup)
        self.select(new_left)
        after = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertTrue(after["ready"], after["gaps"])
        old_by_slot = {row["slot_id"]: row["media_id"] for row in before["media"]}
        new_by_slot = {row["slot_id"]: row["media_id"] for row in after["media"]}
        self.assertNotEqual(new_by_slot[candidates[0]["slot_id"]], old_by_slot[candidates[0]["slot_id"]])
        self.assertEqual(new_by_slot[candidates[1]["slot_id"]], old_by_slot[candidates[1]["slot_id"]])

    def test_design_and_scene_location_are_real_fixed_generation_inputs(self):
        from sqlalchemy import insert, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.production.resource_worker import ResourceWorker
        objects = self.hierarchy()
        location = self.asset("location", "MASTER")
        reference, panel = self.media("location-master"), self.media("design-panel")
        self.select(self.candidate(location, reference, role="location_master"))
        bible = self.fixed("location-spec", {"asset_specs": [{"asset_id": location, "variant_key": "master"}]}, kind="asset-bible")
        with self.engine.connect() as conn:
            spec = conn.execute(select(S.asset_spec_versions.c.id).where(S.asset_spec_versions.c.project_id == self.p,
                S.asset_spec_versions.c.asset_id == location)).scalar_one()
        self.fixed("state", {"state_versions": [{"scene_id": objects["scene"]}]}, kind="scene-state")
        doc = {"design_units": [{"design_key": "primary", "scene_id": objects["scene"], "picture": "合成设计",
            "shots": [{"shot_id": objects["shot"], "purpose": "keyframe"}],
            "panels": [{"panel_key": "panel", "media_id": panel}]}],
            "scene_locations": [{"scene_id": objects["scene"], "location_id": location, "spec_version_id": spec}]}
        state = {"scene_id": objects["scene"], "location_id": location, "time_state": "日间",
            "lighting_id": "synthetic-day", "soundscape_id": "synthetic-quiet", "characters": {"none": "无人物空景"},
            "camera": {"framing": "wide", "motion": "static", "screen_direction": "left-to-right"}}
        doc.update(format="vsc.continuity-plan/v1", project_id=self.p, sequence_id=objects["sequence"], max_clip_ms=8000,
            shots=[{"id": objects["shot"], "duration_ms": 6000, "reference_asset_ids": [location],
                "handles": {"head_ms": 300, "tail_ms": 300}, "entry_state": state, "exit_state": copy.deepcopy(state)}])
        design = self.fixed("design", doc, kind="vsc.shot_plan", dependencies=[bible["id"]])
        before = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertTrue(before["ready"], before["gaps"])
        self.assertEqual({row["media_id"] for row in before["media"]}, {reference, panel})
        model, provider = str(uuid.uuid4()), "offline_" + uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name="offline", modality="image", base_url="https://example.invalid",
                auth_ref="none", enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key="offline", modality="image",
                model_version="1", capabilities={"purposes": ["keyframe"], "reference_media": True}, default_params={}, cost_rule={}, enabled=True))
        request = {"prompt": "合成画面", "reference_media_ids": [reference, panel], "params": {"seed": 1}}
        run = self.production_run(objects["shot"], request, purpose="keyframe", modality="image", candidate_count=2)
        payload = {"run_version_id": run, "shot_id": objects["shot"], "purpose": "keyframe", "modality": "image",
            "model_id": model, "context_sha256": before["sha256"], "request_payload": request}
        job = self.write("create_generation_job", payload)
        retry = self.write("create_generation_job", dict(payload, candidate_no=1))
        self.assertNotEqual(job["id"], retry["id"])
        self.write("update_generation_job", {"job_id": retry["id"], "status": "failed", "raw_response": {"error": "synthetic failure"}})
        first = self.service.get_generation_job(self.p, job["id"])
        self.assertIn(design["id"], {row["artifact_id"] for row in first["input_versions"]})
        self.assertEqual({row["media_id"] for row in first["input_media"]}, {reference, panel})
        # The actual provider-neutral adapter compiler accepts these fixed IDs.
        worker = object.__new__(ResourceWorker)
        compiled = worker._request(first)
        self.assertEqual(set(compiled.reference_media_ids), {reference, panel})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submission_unknown"})
        changed = copy.deepcopy(doc)
        changed["design_units"][0]["picture"] = "新设计"
        self.fixed("design", changed, kind="vsc.shot_plan", dependencies=[bible["id"]])
        after = self.service.get_generation_job(self.p, job["id"])
        self.assertEqual(after["status"], "submission_unknown")
        self.assertEqual(after["request_sha256"], first["request_sha256"])
        self.assertEqual(after["input_versions"], first["input_versions"])
        self.assertEqual(after["input_media"], first["input_media"])
        revisions = self.service.get_shot_designs(self.p, shot_id=objects["shot"])["units"]
        original = next(row for row in revisions if row["artifact_id"] == design["id"])
        self.assertEqual(len(original["jobs"]), 2)
        self.assertTrue(all(row["outputs"] == [] for row in original["jobs"]))
        self.assertEqual({row["status"] for row in original["jobs"]}, {"submission_unknown", "failed"})
        from vsc.assets.resource_service import ResourceError
        with self.assertRaises(ResourceError) as caught:
            self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "synthetic-1"})
        self.assertEqual(caught.exception.code, "recovery_evidence_required")
        self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "synthetic-1",
            "recovery_evidence": {"lookup": "existing external task found"}})
        recovered = self.service.get_generation_job(self.p, job["id"])
        self.assertEqual(recovered["request_sha256"], first["request_sha256"])
        self.assertEqual(recovered["input_versions"], first["input_versions"])
        self.assertEqual(recovered["attempt"], after["attempt"])
        self.assertNotEqual(self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")["sha256"], before["sha256"])

    def test_font_rights_revocation_keeps_history_and_post_out_of_generation(self):
        import hashlib
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        self.fixed("state", {"state_versions": [{"scene_id": objects["scene"]}]}, kind="scene-state")
        sha = hashlib.sha256(b"synthetic-font").hexdigest()
        font = self.write("register_media", {"name": "合成字体", "modality": "other", "sha256": sha,
            "size_bytes": 14, "mime_type": "font/ttf", "storage": "local", "object_key": sha + ".ttf", "rights": "owned",
            "source": {"kind": "test-owned", "content": "synthetic permission"}})["id"]
        self.write("record_media_check", {"media_id": font, "checker": "font-fixture", "criteria_version": "1", "outcome": "pass"})
        candidate = self.candidate(objects["shot"], font, role="font")
        selected = self.select(candidate)
        self.fixed("font-requirement", {"resource_requirements": [{"requirement_key": "subtitle-font",
            "category_code": "text.font", "purpose": "font", "description": "合成字幕字体",
            "scene_id": objects["scene"], "shot_id": objects["shot"], "slots": [{"slot_id": candidate["slot_id"], "role": "post"}]}]})
        before = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertTrue(before["ready"], before["gaps"])
        self.assertNotIn(font, {row["media_id"] for row in before["media"]})
        self.assertEqual(self.service.get_resource_requirements(self.p)["unmet_count"], 0)
        self.write("decide_rights", {"media_id": font, "outcome": "revoked", "reason": "合成授权撤销"})
        current = self.service.get_resource_requirements(self.p)
        self.assertEqual(current["unmet_count"], 1)
        self.assertIn("rights_unknown_or_restricted", current["requirements"][0]["slots"][0]["reasons"])
        after = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertEqual(after["sha256"], before["sha256"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.current_bindings.c.decision_id).where(S.current_bindings.c.project_id == self.p,
                S.current_bindings.c.slot_id == candidate["slot_id"])).scalar_one(), selected["decision_id"])

    def test_fixed_line_dependencies_design_ambiguity_and_missing_spec_are_explicit(self):
        from vsc.assets.resource_service import ResourceError
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        script = self.fixed("script", {"script_lines": [{"line_key": "L1", "scene_id": objects["scene"],
            "line_kind": "action", "text": "合成动作"}]}, kind="screenplay")
        with self.engine.connect() as conn:
            line = conn.execute(select(S.script_lines.c.id).where(S.script_lines.c.project_id == self.p)).scalar_one()
        unit = {"design_key": "a", "scene_id": objects["scene"], "picture": "合成画面", "line_ids": [line],
            "shots": [{"shot_id": objects["shot"]}]}
        with self.assertRaises(ResourceError) as caught:
            self.fixed("no-dependency", {"design_units": [unit]})
        self.assertEqual(caught.exception.code, "resource_dependency_missing")
        design = self.fixed("design", {"design_units": [unit]}, dependencies=[script["id"]])
        self.assertEqual(self.service.get_shot_designs(self.p, artifact_id=design["id"])["units"][0]["line_ids"], [line])
        duplicate = copy.deepcopy(unit)
        duplicate["design_key"] = "b"
        with self.assertRaises(ResourceError):
            self.fixed("ambiguous", {"design_units": [unit, duplicate]}, dependencies=[script["id"]])
        with self.assertRaises(ResourceError) as caught:
            self.fixed("duplicate-keys", {"design_units": [unit, unit]}, dependencies=[script["id"]])
        self.assertEqual(caught.exception.code, "duplicate_design_key")
        location = self.asset("location")
        self.select(self.candidate(location, self.media("unversioned-location"), role="location_master"))
        self.fixed("state", {"state_versions": [{"scene_id": objects["scene"]}]}, kind="scene-state")
        self.fixed("location", {"scene_locations": [{"scene_id": objects["scene"], "location_id": location}]}, kind="scene-state")
        context = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertIn("resource_spec_missing", {row["code"] for row in context["gaps"]})

    def test_classification_does_not_change_context_or_create_generation_jobs(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        plan = self.fixed("plan", {"design_units": [{"design_key": "a", "shots": [{"shot_id": objects["shot"]}], "picture": "合成"}]})
        self.fixed("state", {"state_versions": [{"scene_id": objects["scene"]}]}, kind="scene-state")
        before = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.write("classify_resource", {"target_type": "artifact", "target_id": plan["id"], "category_code": "document.storyboard"})
        after = self.service.compile_shot_context(self.p, objects["shot"], purpose="keyframe")
        self.assertTrue(before["ready"], before["gaps"])
        self.assertEqual(before["sha256"], after["sha256"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id == self.p)).scalar_one(), 0)


if __name__ == "__main__":
    unittest.main()
