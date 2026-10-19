"""Real resource consumers for stage/round-isolated draft comparison evidence."""
import unittest

from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "需要已配置的 PostgreSQL 测试库")
class LearningEvidence(ResourceStoreFixture, unittest.TestCase):
    def record(self, stage="script", round_id="EXP-001-R1", **extra):
        payload = {"artifact_key": f"vsc.learning_evaluation:{stage}:project:{round_id}",
                   "artifact_type": "vsc.learning_evaluation", "stage": stage,
                   "document": "# 合成比较\n\n仅作工程记录，没有真人效果结论。\n",
                   "project_wide": True, "object_ids": [], "dependency_ids": []}
        payload.update(extra)
        return self.write("create_artifact", payload)

    def test_stage_round_currents_and_fixed_history_are_independent(self):
        records = [self.record(), self.record("post"), self.record(round_id="EXP-001-R2")]
        original = [self.service.get_artifact_version(self.p, r["id"]) for r in records]
        for record in records:
            self.assertEqual(record["version"], 1)
            self.write("decide_artifact", {"artifact_id": record["id"], "reason": "隔离合成证据决定"})
        current = {r["id"] for r in self.service.list_artifacts(self.p)["items"] if r["current"]}
        self.assertEqual(current, {r["id"] for r in records})
        revised = self.record(document="# 同轮修订\n\n保留原话与失败。\n", supersedes_id=records[0]["id"])
        self.write("decide_artifact", {"artifact_id": revised["id"], "reason": "替代此流当前合成记录"})
        current = {r["id"] for r in self.service.list_artifacts(self.p)["items"] if r["current"]}
        self.assertEqual(current, {revised["id"], records[1]["id"], records[2]["id"]})
        for before in original:
            after = self.service.get_artifact_version(self.p, before["id"])
            self.assertEqual((after["content"], after["sha256"]), (before["content"], before["sha256"]))

    def test_draft_revision_is_append_only_not_supersedes(self):
        first = self.record()
        revised = self.record(document="# 草稿第二版\n\nprevious_revision仅记录沿革，不作生产依赖。\n")
        self.assertEqual(revised["version"], 2)
        self.write("decide_artifact", {"artifact_id": revised["id"], "reason": "选择合成草稿第二版"})
        self.assertNotEqual(first["id"], revised["id"])
        self.assertEqual(self.service.get_artifact_version(self.p, first["id"])["content"],
                         "# 合成比较\n\n仅作工程记录，没有真人效果结论。\n")

    def test_cross_stream_replacement_and_nonartifact_dependencies_rejected(self):
        from vsc.assets.resource_service import ResourceError
        first = self.record()
        self.write("decide_artifact", {"artifact_id": first["id"], "reason": "合成记录"})
        for payload in ({"stage": "post", "supersedes_id": first["id"]},
                        {"round_id": "EXP-002-R1", "supersedes_id": first["id"]}):
            with self.subTest(payload=payload), self.assertRaises(ResourceError):
                self.record(**payload)
        media = self.media("非产物引用")
        with self.assertRaises(ResourceError):
            self.record(dependency_ids=[media])
        with self.assertRaises(ResourceError):
            self.record(document={"format": "vsc.learning-evaluation/v1", "result": "pass"})


if __name__ == "__main__":
    unittest.main()
