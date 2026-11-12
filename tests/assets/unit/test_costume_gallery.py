"""Local costume catalog and the official 服饰 browser events."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vsc.assets.costume_gallery import costume_file, costume_page, load_costumes


class CostumeGalleryTests(unittest.TestCase):
    def test_local_catalog_search_paging_and_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spring = root / "服饰" / "春"
            summer = root / "服饰" / "夏"
            spring.mkdir(parents=True)
            summer.mkdir()
            (spring / "SPR-0001.png").write_bytes(b"png")
            os.utime(spring / "SPR-0001.png", (1_700_000_100, 1_700_000_100))
            (spring / "SPR-0001.json").write_text(json.dumps({
                "name": "SPR-0001", "关键词": "ivory frill knit denim white sneakers", "服饰分类": "春",
            }, ensure_ascii=False), encoding="utf-8")
            (spring / ".hidden.png").write_bytes(b"no")
            (summer / "SPR-0001.png").write_bytes(b"png")
            os.utime(summer / "SPR-0001.png", (1_700_000_200, 1_700_000_200))
            outside = root / "outside.png"
            outside.write_bytes(b"secret")
            (spring / "escape.png").symlink_to(outside)
            wardrobe = root / "服装" / "旗袍"
            wardrobe.mkdir(parents=True)
            (wardrobe / "fu-qipao.png").write_bytes(b"sheet")
            items, files = load_costumes(root)
            identities = [item["id"] for item in items]
            self.assertNotIn("escape", identities)
            self.assertNotIn("fu-qipao", identities)
            self.assertIsNone(costume_file(files, "escape"))
            self.assertEqual(identities, ["SPR-0001-2", "SPR-0001"])
            self.assertEqual([item["id"] for item in costume_page(items, "", "白", 0, 120)["items"]], ["SPR-0001"])
            self.assertEqual(costume_page(items, "", "", 0, 120)["categories"][0], {"name": "春", "count": 1})
            self.assertEqual(costume_page(items, "夏", "", 0, 120)["items"][0]["id"], "SPR-0001-2")
            self.assertEqual(costume_page(items, "", "deni", 0, 120)["total"], 1)
            self.assertEqual(costume_page(items, "", "ivory silk", 0, 120)["total"], 0)
            self.assertEqual(costume_page(items, "春", "", 0, 120)["total"], 1)
            first_page = costume_page(items, "", "", 0, 1)
            self.assertEqual(first_page["items"][0]["id"], "SPR-0001-2")
            self.assertEqual(first_page["next_offset"], 1)
            paged = costume_page(items, "", "", 1, 1)
            self.assertEqual(paged["items"][0]["id"], "SPR-0001")
            self.assertIsNone(paged["next_offset"])
            self.assertTrue(costume_file(files, "SPR-0001").is_file())
            with self.assertRaises(ValueError):
                costume_page(items, "未知", "", 0, 120)
            with self.assertRaises(ValueError):
                costume_page(items, "", "", True, 120)
            with self.assertRaises(ValueError):
                costume_page(items, "", "", 0, 0)
            empty_items, empty_files = load_costumes(root / "missing")
            blank = costume_page(empty_items, "", "", 0, 120)
            self.assertEqual(blank["total_all"], 0)
            self.assertEqual(len(blank["categories"]), 8)
            self.assertIsNone(costume_file(empty_files, "SPR-0001"))


class CostumeGalleryDOMTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for frontend checks")
    def test_official_costume_tabs_search_and_paging(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        result = subprocess.run(["node", str(root / "support/fixtures/frontend/costume_gallery.cjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("costume gallery DOM PASS", result.stdout)
