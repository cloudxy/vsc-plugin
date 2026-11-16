"""Local 创作精选 catalog, search, and canvas process projection."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from support.paths import ROOT
from vsc.assets.featured_showcase import list_works, localize_value, project_snapshot, read_process, showcase_root, store_media
from vsc.interfaces.web.featured_showcase import install_featured_showcase_routes


def write_snapshot(root, identity, snapshot, snapshot_id=7):
    record = {"templateUuid": identity, "name": "旧日", "snapshotId": snapshot_id, "snapshot": snapshot,
              "finalOutput": "https://example.test/out.mp4"}
    target = root / "processes" / f"{identity}.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(json.dumps(record).encode()))


class FeaturedShowcaseTests(unittest.TestCase):
    def test_workspace_assets_default_and_explicit_override(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(showcase_root(), ROOT / "assets" / "featured-showcase")
            with patch.dict("os.environ", {"VSC_FEATURED_SHOWCASE_ROOT": "/explicit/showcase"}):
                self.assertEqual(showcase_root(), Path("/explicit/showcase"))
                self.assertEqual(showcase_root("/override/showcase"), Path("/override/showcase"))

    def test_localized_links_are_rechecked_after_media_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            url = "https://example.test/cover.png"
            stored = store_media(root, url, b"\x89PNG\r\n\x1a\ncover")
            local = "/featured-showcase-media/" + stored.name
            payload = {"coverUrl": local, "prompt": "参考 " + local}
            self.assertEqual(localize_value(root, payload), payload)
            stored.unlink()
            self.assertEqual(localize_value(root, payload), {"coverUrl": "", "prompt": "参考 "})
            self.assertEqual(localize_value(root, payload, drop_missing=False), payload)

    def catalog(self, root):
        cards = {
            "a" * 32: {"templateUuid": "a" * 32, "name": "旧日将尽", "description": "末世", "nickname": "熵变",
                       "snapshotId": 7, "coverUrl": "https://example.test/cover.png",
                       "tags": [{"code": "viral_likes_30", "label": "全网点赞30万+"}], "userTags": [{"name": "先锋"}]},
            "b" * 32: {"templateUuid": "b" * 32, "name": "绵羊奶粉", "description": "", "nickname": "阿松", "snapshotId": None},
        }
        payload = {"schema": "vsc.featured-showcase/v1", "tags": [{"id": 0, "code": "all", "label": "全部"},
                   {"id": 1800, "code": "short_play", "label": "短剧漫剧"}],
                   "feeds": {"0": ["a" * 32, "b" * 32], "1800": ["a" * 32]}, "cards": cards}
        root.mkdir(parents=True, exist_ok=True)
        (root / "catalog.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return cards

    def test_search_tag_and_closed_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            page = list_works(root, "0", "旧日", 0, 20)
            self.assertTrue(page["ready"])
            self.assertEqual([item["name"] for item in page["items"]], ["旧日将尽"])
            self.assertFalse(page["items"][0]["processReady"])
            self.assertTrue(page["items"][0]["processAvailable"])
            tagged = list_works(root, "1800", "", 0, 20)
            self.assertEqual(tagged["total"], 1)
            self.assertEqual(list_works(root, "999", "", 0, 20)["total"], 2)
            closed = list_works(root, "0", "绵羊", 0, 20)["items"][0]
            self.assertFalse(closed["processAvailable"])

    def test_process_uses_parent_offsets_and_mixed_refs(self):
        snapshot = {"nodes": [
            {"id": "g-1", "type": "group", "position": {"x": 100, "y": 40}, "width": 800, "height": 500,
             "data": {"type": "group", "name": "第一幕", "childNodeIds": ["v-1"], "groupColor": "#F4B740"}},
            {"id": "v-1", "type": "video", "parentId": "g-1", "position": {"x": 12, "y": 20},
             "measured": {"width": 320, "height": 180},
             "data": {"type": "video", "name": "镜头", "action": "video_generate",
                      "url": ["https://example.test/a.mp4", "https://example.test/b.mp4"],
                      "params": {"model": "star-video2.5", "modeType": "mixed2video", "prompt": "林芸调动无人机",
                                 "settings": {"ratio": "21:9", "duration": 10},
                                 "imageList": [{"nodeId": "i-1", "label": "忽略"}],
                                 "mixedList": [{"nodeId": "i-2", "label": "调度员"}]},
                      "taskInfo": {"status": 2}}},
        ], "edges": [{"id": "e-1", "source": "i-missing", "target": "v-1"}, {"id": "e-2", "source": "g-1", "target": "v-1"}]}
        projected = project_snapshot(snapshot)
        video = next(node for node in projected["nodes"] if node["id"] == "v-1")
        self.assertEqual((video["x"], video["y"]), (112, 60))
        self.assertEqual(video["url"], "https://example.test/a.mp4")
        self.assertEqual(video["refs"], [{"nodeId": "i-2", "label": "调度员", "kind": "mixed"}])
        self.assertEqual(video["settings"]["ratio"], "21:9")
        self.assertEqual([edge["id"] for edge in projected["edges"]], ["e-2"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            write_snapshot(root, "a" * 32, snapshot)
            loaded = read_process(root, "a" * 32)
            self.assertEqual(loaded["process"]["nodes"][1]["prompt"], "林芸调动无人机")
            self.assertEqual(loaded["process"]["nodes"][1]["url"], "")
            self.assertEqual(loaded["finalOutput"], "")
            self.assertNotIn("https://", json.dumps(loaded))
            self.assertTrue(list_works(root)["items"][0]["processReady"])
            self.assertEqual(list_works(root)["items"][0]["coverUrl"], "")
            store_media(root, "https://example.test/cover.png", b"\x89PNG\r\n\x1a\ncover")
            self.assertTrue(list_works(root)["items"][0]["coverUrl"].startswith("/featured-showcase-media/"))
            with self.assertRaises(FileNotFoundError):
                read_process(root, "../secret")

    def test_http_reads_local_snapshot_without_remote_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.catalog(root)
            app = FastAPI()
            install_featured_showcase_routes(app, lambda _request, value: value, lambda _request: None, root=root)
            with TestClient(app) as client:
                listed = client.get("/api/v1/featured-showcase", params={"q": "旧日"})
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["items"][0]["name"], "旧日将尽")
                self.assertEqual(listed.json()["items"][0]["coverUrl"], "")
                self.assertNotIn("https://", listed.text)
                missing = client.get("/api/v1/featured-showcase/" + "a" * 32)
                self.assertEqual(missing.status_code, 404)
                stored = store_media(root, "https://example.test/cover.png", b"\x89PNG\r\n\x1a\ncover")
                media = client.get("/featured-showcase-media/" + stored.name)
                self.assertEqual(media.status_code, 200)
                self.assertEqual(media.content, b"\x89PNG\r\n\x1a\ncover")
                again = client.get("/api/v1/featured-showcase", params={"q": "旧日"})
                self.assertEqual(again.json()["items"][0]["coverUrl"], "/featured-showcase-media/" + stored.name)
                self.assertNotIn("https://", again.text)

    def test_shell_keeps_community_and_adds_showcase(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        panel = (ROOT / "src/vsc/interfaces/web/static/panel.js").read_text(encoding="utf-8")
        self.assertIn('id="community-view"', html)
        self.assertIn('id="nav-featured-showcase"', html)
        self.assertIn('id="featured-showcase-view"', html)
        self.assertIn("'featured-showcase'", panel)
        self.assertIn("createFeaturedShowcase", panel)
        app = (ROOT / "src/vsc/interfaces/web/app.py").read_text(encoding="utf-8")
        self.assertIn("install_featured_showcase_routes", app)


if __name__ == "__main__":
    unittest.main()
