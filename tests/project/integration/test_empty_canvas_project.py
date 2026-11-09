"""Empty canvas project: one request creates the project, first episode and canvas."""
import os
import unittest
import uuid

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS, "requires isolated PostgreSQL")
class EmptyCanvasProjectTests(ResourceStoreFixture, unittest.TestCase):
    def test_one_request_opens_an_empty_canvas_and_replay_does_not_duplicate(self):
        from vsc.assets.resource_service import ResourceError

        key = uuid.uuid4().hex
        created = self.service.create_empty_canvas_project({"mode": "empty_canvas"}, actor="test-human", idempotency_key=key)
        again = self.service.create_empty_canvas_project({"mode": "empty_canvas"}, actor="test-human", idempotency_key=key)
        self.assertEqual(created, again)
        self.assertEqual(created["project_name"], "未命名项目")
        self.assertEqual(created["episode_name"], "第一集")
        self.assertEqual(created["canvas_name"], "未命名画布")
        project = self.service.get_project(created["project_id"])
        self.assertEqual(project["profile"], "vsc.light-short")
        episodes = self.service.get_production_episodes(created["project_id"])
        self.assertEqual(episodes["total"], 1)
        self.assertEqual(episodes["items"][0]["id"], created["episode_id"])
        self.assertEqual(episodes["items"][0]["shot_count"], 0)
        canvas = self.service.get_creative_canvas(created["project_id"], created["canvas_id"])
        self.assertEqual(canvas["document"]["nodes"], [])
        self.assertEqual(canvas["document"]["edges"], [])
        listed = self.service.list_creative_canvases(created["project_id"])
        self.assertEqual([row["id"] for row in listed["items"]], [created["canvas_id"]])
        with self.assertRaises(ResourceError):
            self.service.create_empty_canvas_project({"mode": "agent"}, actor="test-human", idempotency_key=uuid.uuid4().hex)

    def test_character_style_is_stored_on_the_project_snapshot(self):
        from vsc.assets.resource_service import ResourceError
        project = self.service.create_project(
            {"name": "样式项目", "profile": "vsc.light-short", "character_style": "3d"},
            actor="test-human", idempotency_key="style-project")
        self.assertEqual(self.service.get_project(project["id"])["profile_snapshot"]["character_style"], "3d")
        with self.assertRaises(ResourceError):
            self.service.create_project(
                {"name": "坏类型", "character_style": "other"},
                actor="test-human", idempotency_key="bad-style")
