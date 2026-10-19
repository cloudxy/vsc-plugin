"""Fixed asset evidence and migrated plan scope through real PostgreSQL."""
import copy
import hashlib
import importlib.util
import json
import os
import unittest
import uuid

from support.paths import ROOT

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DB_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, "requires explicit VSC_TEST_DATABASE_URL and postgres dependencies")
class ShotContextAssetSpecsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        cls.db = isolated_postgres(TEST_URL)
        cls.engine = cls.db.__enter__()
        cls.service = ResourceService(PostgresResourceStore(engine=cls.engine))

    @classmethod
    def tearDownClass(cls):
        cls.db.__exit__(None, None, None)

    def write(self, method, payload):
        result = getattr(self.service, method)(self.p, payload, actor="test-human", expected_revision=self.rev,
                                              idempotency_key=uuid.uuid4().hex)
        self.rev = result["revision"]
        return result

    def artifact(self, key, kind, document, **extra):
        result = self.write("create_artifact", dict(artifact_key=key, artifact_type=kind, document=document, **extra))
        self.write("decide_artifact", {"artifact_id": result["id"], "reason": "测试操作者明确批准"})
        return result

    def setUp(self):
        self.p = self.service.create_project({"name": "固定资产上下文", "profile_snapshot": {
            "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")["id"]
        self.rev, parent, self.objects = 0, None, {}
        for kind in ("work", "episode", "scene", "sequence", "shot"):
            row = self.write("create_object", {"kind": kind, "display_code": kind.upper(), "parent_id": parent})
            self.objects[kind], parent = row["id"], row["id"]
        self.assets = {}
        for alias in ("CHAR", "OTHER"):
            self.assets[alias] = self.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": alias})["id"]
        self.bible_doc = {"format": "vsc.asset-bible/v1", "project_id": self.p, "entities": [
            {"id": alias, "name": alias, "kind": "character", "identity": ["左眉有疤"], "variants": {"default": "蓝衣"}}
            for alias in self.assets]}
        self.old = self.artifact("bible", "vsc.asset_bible", self.bible_doc)
        spec = self.spec(self.old, self.assets["CHAR"])
        state = [{"scene_id": self.objects["scene"], "shot_id": self.objects["shot"], "entities": [
            {"asset_id": self.assets["CHAR"], "spec_version_id": spec, "relation": "in_frame"}]}]
        self.artifact("state", "scene-state", {"state_versions": state}, state_versions=state)
        self.plan("shot", self.old)
        sha = hashlib.sha256(b"test-reference").hexdigest()
        media = self.write("register_media", {"name": "测试参考", "modality": "image", "sha256": sha,
            "size_bytes": 14, "mime_type": "image/png", "storage": "local", "object_key": sha + ".png",
            "rights": "owned", "source": {"kind": "test", "content": "owned evidence"}})
        self.write("record_media_check", {"media_id": media["id"], "checker": "test", "criteria_version": "1", "outcome": "pass"})
        candidate = self.write("propose_binding", {"target_object_id": self.assets["CHAR"], "media_id": media["id"], "role": "identity_face"})
        self.write("record_review", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reason": "匹配", "reviewer_type": "human"})
        self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "人工选择"})

    def spec(self, bible, asset):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            return conn.execute(select(S.asset_spec_versions.c.id).where(S.asset_spec_versions.c.project_id == self.p,
                S.asset_spec_versions.c.artifact_id == bible["id"], S.asset_spec_versions.c.asset_id == asset,
                S.asset_spec_versions.c.variant_key == "master")).scalar_one()

    def plan(self, key, bible, sound=False, scene="SCENE", sequence="SEQUENCE", shot="SHOT", assets=None):
        template = "sound-cue-sheet.json" if sound else "continuity-plan.json"
        doc = json.loads((ROOT / "templates" / template).read_text("utf-8"))
        doc.update(project_id=self.p, scene_id=scene, sequence_id=sequence)
        if sound:
            doc.update(ambience_beds=[], music_cues=[], boundaries=[])
        else:
            doc["shots"] = [doc["shots"][0]]
            doc["shots"][0].update(id=shot, reference_asset_ids=["CHAR"])
            doc["shots"][0].pop("bridge_to_next", None)
        return self.artifact(key, "vsc.sound_plan" if sound else "vsc.shot_plan", doc,
            asset_versions={self.assets[alias]: {"id": bible["id"], "sha256": bible["sha256"]}
                            for alias in (assets or ["CHAR"])})

    def context(self):
        return self.service.compile_shot_context(self.p, self.objects["shot"], "shot_keyframe")

    def test_compatible_revisions_retain_exact_state_and_consumer_evidence(self):
        before = self.context()
        revised = copy.deepcopy(self.bible_doc)
        revised["entities"][0].update(notes="补充生成说明", references=[{
            "path": "synthetic/reference.png", "sha256": "a" * 64, "media_type": "image", "purpose": "identity"}])
        revised["entities"][0]["variants"]["night"] = "夜间外套"
        newer = self.artifact("bible", "vsc.asset_bible", revised)
        self.plan("sound", newer, sound=True)
        context = self.context()
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["state_entity_refs"], before["state_entity_refs"])
        self.assertTrue({self.old["id"], newer["id"]}.issubset({a["id"] for a in context["artifacts"]}))
        self.assertTrue(self.service.get_artifact_version(self.p, self.old["id"])["approved"])
        self.assertEqual(context["sha256"], self.context()["sha256"])
        bible_inputs = [item["content"]["entities"] for item in context["semantic_inputs"]
                        if item["artifact_type"] == "vsc.asset_bible"]
        expected = {key: value for key, value in self.bible_doc["entities"][0].items() if key != "name"}
        self.assertEqual([row for rows in bible_inputs for row in rows], [expected])

    def test_identity_kind_and_existing_variant_changes_still_block(self):
        from vsc.assets.resource_service import ResourceError
        revised = copy.deepcopy(self.bible_doc)
        revised["entities"][0]["kind"] = "prop"
        before = self.context()
        revision = self.rev
        with self.assertRaises(ResourceError) as caught:
            self.artifact("bible", "vsc.asset_bible", revised)
        self.assertEqual(caught.exception.code, "asset_kind_mismatch")
        self.assertEqual(self.service.get_project(self.p)["revision"], revision)
        self.assertEqual(self.context()["sha256"], before["sha256"])
        for field, value in (("identity", ["没有疤"]), ("variants", {"default": "红衣"})):
            with self.subTest(field=field):
                revised = copy.deepcopy(self.bible_doc)
                revised["entities"][0][field] = value
                newer = self.artifact("bible", "vsc.asset_bible", revised)
                self.plan("sound", newer, sound=True)
                context = self.context()
                self.assertFalse(context["ready"])
                self.assertIn({"code": "asset_version_conflict", "asset_id": self.assets["CHAR"]}, context["gaps"])

    def test_unrelated_scene_sequence_and_shot_plans_do_not_pollute_context(self):
        before = self.context()
        revised = copy.deepcopy(self.bible_doc)
        revised["entities"][0]["identity"] = ["其他场次身份"]
        newer = self.artifact("bible", "vsc.asset_bible", revised)
        ignored = [self.plan("other-scene", newer, scene="ELSEWHERE"),
                   self.plan("other-scene-sound", newer, sound=True, scene="ELSEWHERE"),
                   self.plan("other-sequence", newer, sequence="ELSEWHERE"),
                   self.plan("other-shot", newer, shot="ELSEWHERE")]
        context = self.context()
        self.assertTrue(context["ready"], context["gaps"])
        self.assertTrue({row["id"] for row in ignored}.isdisjoint({a["id"] for a in context["artifacts"]}))
        self.assertEqual(context["sha256"], before["sha256"])

    def test_unneeded_asset_identity_change_does_not_block_this_shot(self):
        revised = copy.deepcopy(self.bible_doc)
        revised["entities"][1]["identity"] = ["另一人物已改身份"]
        newer = self.artifact("bible", "vsc.asset_bible", revised)
        self.plan("shot", self.old, assets=["CHAR", "OTHER"])
        self.plan("sound", newer, sound=True, assets=["CHAR", "OTHER"])
        context = self.context()
        self.assertTrue(context["ready"], context["gaps"])

    def test_separate_bible_families_cannot_silently_merge(self):
        other = self.artifact("independent-bible", "vsc.asset_bible", self.bible_doc)
        self.plan("sound", other, sound=True)
        self.assertIn({"code": "asset_version_conflict", "asset_id": self.assets["CHAR"]}, self.context()["gaps"])

    def test_revoked_compatible_pin_remains_blocked(self):
        newer = self.artifact("bible", "vsc.asset_bible", self.bible_doc)
        self.plan("sound", newer, sound=True)
        self.write("decide_artifact", {"artifact_id": newer["id"], "outcome": "revoke", "reason": "测试撤销固定输入"})
        context = self.context()
        self.assertFalse(context["ready"])
        self.assertIn({"code": "identity_spec_unapproved", "artifact_id": newer["id"]}, context["gaps"])
