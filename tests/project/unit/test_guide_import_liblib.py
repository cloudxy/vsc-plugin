"""LibTV academy article projection: HTML media tags to local guide markdown."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import support.paths
from tools.maintenance.guide_import_liblib import (ARTICLES, convert_markdown,
    import_article, import_highlights, local_name)


def article(**extra):
    base = dict(articleUuid="01a0d2362f7a7267bf58f4cb881b2e07", title="「基础功能」画布与节点",
                summary="涉及功能：画布，文本、图片、视频、音频节点",
                contentMd="", cover="", canvasUrl="")
    base.update(extra)
    return base


class GuideImportLiblibTests(unittest.TestCase):
    def test_local_name_lowercases_extension_and_remaps_mov(self):
        self.assertEqual(local_name("https://x.cloud/a/1790074399406.PNG"), "1790074399406.png")
        self.assertEqual(local_name("https://x.cloud/a/1790072955479.MP4?x=1"), "1790072955479.mp4")
        self.assertEqual(local_name("https://x.cloud/a/1790153326503.mov"), "1790153326503.mp4")
        self.assertEqual(local_name("https://x.cloud/a/cover.jpeg"), "cover.jpeg")

    def test_convert_rewrites_img_and_video_and_strips_layout_tags(self):
        md = (
            "## 画布\n\n<p align=\"center\">\n"
            '<img src="https://liblibai-online.liblib.cloud/academy/content/1.PNG" width="80%" />\n'
            "</p>\n<p align=\"center\">\n"
            '<video src="https://liblibai-online.liblib.cloud/academy/video/2.MP4" controls></video>\n'
            "</p>\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder)
            (media / "1.png").write_bytes(b"i")
            (media / "2.mp4").write_bytes(b"v")
            root = Path(folder) / "guides"
            with patch("tools.maintenance.guide_import_liblib.guides_root", return_value=root):
                out = convert_markdown(md, "liblib-canvas-nodes", media)
            self.assertIn("![](/creation-guide-media/liblib/liblib-canvas-nodes/1.png)", out)
            self.assertIn("[video:2.mp4](/creation-guide-media/liblib/liblib-canvas-nodes/2.mp4)", out)
            self.assertNotIn("<img", out)
            self.assertNotIn("<video", out)
            self.assertNotIn("<p", out)
            self.assertIn("## 画布", out)
            self.assertTrue((root / "images" / "liblib" / "liblib-canvas-nodes" / "1.png").exists())
            self.assertTrue((root / "videos" / "liblib" / "liblib-canvas-nodes" / "2.mp4").exists())

    def test_convert_fails_closed_for_missing_media(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("tools.maintenance.guide_import_liblib.guides_root", return_value=Path(folder)):
                with self.assertRaises(FileNotFoundError):
                    convert_markdown('<img src="https://x.cloud/academy/content/gone.png" />',
                                     "liblib-x", Path(folder))

    def test_import_article_projects_summary_canvas_and_dry_run_store(self):
        with tempfile.TemporaryDirectory() as folder:
            capture = Path(folder) / "out"
            (capture / "media").mkdir(parents=True)
            (capture / "media" / "1790606715644.png").write_bytes(b"c")
            root = Path(folder) / "guides"
            data = article(
                contentMd='## 节点\n\n<img src="https://liblibai-online.liblib.cloud/academy/content/1790606715644.png" />',
                cover="https://liblibai-online.liblib.cloud/course/asset/1790606715644.png",
                canvasUrl="https://www.liblib.tv/canvas/share?spaceId=1")
            with patch("tools.maintenance.guide_import_liblib.guides_root", return_value=root):
                stats = import_article(data, capture, store=None, dry_run=True)
                md_path = root / "liblib" / "liblib-canvas-nodes.md"
                self.assertTrue(md_path.exists())
                body = md_path.read_text("utf-8")
                self.assertTrue(body.startswith("> 涉及功能"))
                self.assertIn("在 LibTV 中打开", body)
                placed = root / "images" / "liblib" / "liblib-canvas-nodes" / "1790606715644.png"
                self.assertTrue(placed.exists())
            self.assertEqual(stats["slug"], "liblib-canvas-nodes")
            self.assertEqual((stats["images"], stats["videos"], stats["h2"]), (1, 0, 1))
            self.assertTrue(stats["cover"])

    def test_article_map_covers_all_fourteen_academy_slugs(self):
        self.assertEqual(len(ARTICLES), 14)
        self.assertIn("01a0d24709f37af79589c9dbaa5303f1", ARTICLES)
        self.assertTrue(all(slug.startswith("liblib-") for slug in ARTICLES.values()))

    def test_import_highlights_projects_cards_and_copies_videos(self):
        feature_news = {"code": 0, "data": {"list": [{
            "id": 3, "versionNo": "1.5.1", "releaseDate": "2026-11-13",
            "features": [
                {"id": 23, "onlineDate": "2026-11-13", "name": "Seedance 2.5 Flash首发",
                 "description": "生成速度提升一倍", "mediaType": 3,
                 "mediaUrl": "https://libtv-res.liblib.art/upload-images/x/a9021e5c.mp4",
                 "buttonText": "去体验",
                 "linkUrl": "https://www.liblib.tv/canvas?selectNode=video", "sortOrder": 1},
                {"id": 24, "onlineDate": "2026-11-13", "name": "元素替换-一键复刻爆款",
                 "description": "沿用原视频的动作与镜头", "mediaType": 3,
                 "mediaUrl": "https://libtv-res.liblib.art/upload-images/y/f3321c33.mp4",
                 "buttonText": "去体验", "linkUrl": "javascript:alert(1)", "sortOrder": 2},
            ]}]}}
        with tempfile.TemporaryDirectory() as folder:
            capture = Path(folder) / "out"
            (capture / "media").mkdir(parents=True)
            (capture / "media" / "a9021e5c.mp4").write_bytes(b"v1")
            (capture / "media" / "f3321c33.mp4").write_bytes(b"v2")
            (capture / "feature_news.json").write_text(
                json.dumps(feature_news, ensure_ascii=False), "utf-8")
            root = Path(folder) / "guides"
            calls = []

            class FakeStore:
                def upsert_highlight(self, **kw):
                    calls.append(kw)

            with patch("tools.maintenance.guide_import_liblib.guides_root", return_value=root):
                records = import_highlights(capture, store=FakeStore())
            placed = root / "videos" / "liblib" / "highlights"
            self.assertTrue((placed / "a9021e5c.mp4").exists())
            self.assertTrue((placed / "f3321c33.mp4").exists())
            self.assertEqual([r["slug"] for r in records],
                             ["liblib-feature-23", "liblib-feature-24"])
            self.assertEqual(records[0]["video"],
                             "/creation-guide-media/liblib/highlights/a9021e5c.mp4")
            self.assertEqual(records[0]["link"], "https://www.liblib.tv/canvas?selectNode=video")
            self.assertEqual(records[1]["link"], "")  # non-http links dropped
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["online_date"], "2026-11-13")
            self.assertEqual(calls[1]["button_text"], "")

    def test_import_highlights_fails_closed_for_missing_media(self):
        feature_news = {"data": {"list": [{"versionNo": "1.5.1", "features": [
            {"id": 9, "name": "缺视频", "mediaUrl": "https://libtv-res.liblib.art/x/gone.mp4"}]}]}}
        with tempfile.TemporaryDirectory() as folder:
            capture = Path(folder)
            (capture / "feature_news.json").write_text(
                json.dumps(feature_news, ensure_ascii=False), "utf-8")
            with patch("tools.maintenance.guide_import_liblib.guides_root",
                       return_value=Path(folder)):
                with self.assertRaises(FileNotFoundError):
                    import_highlights(capture)


if __name__ == "__main__":
    unittest.main()
