"""Real, isolated relational task projection and authority boundaries."""
import unittest
from types import SimpleNamespace
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "isolated PostgreSQL required")
class AssistedDeskTest(ResourceStoreFixture, unittest.TestCase):
    def query(self, **kwargs):
        from vsc.assets.assisted_desk import AssistedDesk
        return AssistedDesk(SimpleNamespace(_reader=lambda p: None, service=self.service)).query(self.p, **kwargs)

    def test_pending_latest_versions_scope_counts_and_revision(self):
        from vsc.assets.resource_service import Conflict, NotFound, ResourceError
        h = self.hierarchy()
        approved = self.artifact("剧本", "generic", [h["scene"]])
        first = self.write("create_artifact", dict(artifact_key="修改稿", artifact_type="generic",
            document={"正文": "第一稿"}, object_ids=[h["scene"]]))
        second = self.write("create_artifact", dict(artifact_key="修改稿", artifact_type="generic",
            document={"title": "清楚的剧本标题", "正文": "第二稿"}, object_ids=[h["scene"]]))
        page = self.query(object_id=h["shot"], limit=1)
        self.assertEqual(page["counts"], {"review": 1, "progress": 0, "results": 1})
        self.assertEqual(page["items"][0]["ref"]["id"], second["id"])
        self.assertNotEqual(page["items"][0]["ref"]["id"], first["id"])
        self.assertEqual(page["items"][0]["ref"]["kind"], "artifact")
        self.assertEqual(page["items"][0]["status_label"], "等待审阅")
        self.assertEqual(page["items"][0]["title"], "清楚的剧本标题")
        self.assertEqual(self.query(bucket="results")["items"][0]["ref"]["id"], approved)
        self.write("create_artifact", dict(artifact_key="剧本", artifact_type="generic",
            document={"正文": "等待决定的新稿"}, object_ids=[h["scene"]]))
        self.assertEqual(self.query(bucket="results")["items"][0]["ref"]["id"], approved,
            "A new draft must not hide the still-current approved version.")
        with self.assertRaises(Conflict):
            self.query(revision=0)
        with self.assertRaises(ResourceError):
            self.query(limit=101)
        other = self.service.create_project(dict(name="另一个项目",
            profile_snapshot={"profile_id":"vsc.synthetic","version":"1","stages":[]}), actor="test")["id"]
        foreign = self.service.create_object(other, dict(kind="asset", display_code="OTHER", asset_kind="prop"),
            expected_revision=0, idempotency_key="other-object", actor="test")["id"]
        with self.assertRaises(NotFound):
            self.query(object_id=foreign)

    def test_candidate_and_media_pages_exclude_recycle_but_preserve_original(self):
        h = self.hierarchy()
        a = self.media("重复素材 A")
        b = self.media("独立素材 B")
        self.candidate(h["shot"], a)
        self.assertEqual(self.query()["counts"]["review"], 1)
        self.assertEqual(self.query(bucket="results", limit=1)["next_offset"], 1)
        self.write("recycle_media", dict(media_ids=[a], action="trash", reason="测试可恢复回收"))
        self.assertEqual(self.query()["counts"]["review"], 0)
        results = self.query(bucket="results")
        self.assertEqual(results["total"], 1)
        self.assertEqual(results["items"][0]["ref"]["id"], b)
        self.assertEqual(self.service.get_media(self.p, a)["id"], a)
