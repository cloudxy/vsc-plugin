"""Local costume catalog and the official 服饰 browser events."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vsc.assets.costume_gallery import PAGE_SIZE, cached_costumes, costume_file, costume_page, load_costumes


class CostumeGalleryTests(unittest.TestCase):
    def test_local_catalog_search_paging_and_escape(self):
        self.assertEqual(PAGE_SIZE, 24)
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
            self.assertEqual([item["id"] for item in costume_page(items, "", "白")["items"]], ["SPR-0001"])
            self.assertEqual(costume_page(items)["limit"], 24)
            self.assertEqual(costume_page(items)["categories"][0], {"name": "春", "count": 1})
            self.assertEqual(costume_page(items, "夏")["items"][0]["id"], "SPR-0001-2")
            self.assertEqual(costume_page(items, "", "deni")["total"], 1)
            self.assertEqual(costume_page(items, "", "ivory silk")["total"], 0)
            self.assertEqual(costume_page(items, "春")["total"], 1)
            first_page = costume_page(items, "", "", 0, 1)
            self.assertEqual(first_page["items"][0]["id"], "SPR-0001-2")
            self.assertEqual(first_page["next_offset"], 1)
            paged = costume_page(items, "", "", 1, 1)
            self.assertEqual(paged["items"][0]["id"], "SPR-0001")
            self.assertIsNone(paged["next_offset"])
            self.assertTrue(costume_file(files, "SPR-0001").is_file())
            many = [{"id": f"SPR-{i:04d}", "title": f"SPR-{i:04d}", "category": "春", "label": "春", "keywords": "white"} for i in range(30)]
            batch1 = costume_page(many, "春")
            self.assertEqual(len(batch1["items"]), 24)
            self.assertEqual(batch1["next_offset"], 24)
            batch2 = costume_page(many, "春", "", 24)
            self.assertEqual(len(batch2["items"]), 6)
            self.assertIsNone(batch2["next_offset"])
            with self.assertRaises(ValueError):
                costume_page(items, "未知")
            with self.assertRaises(ValueError):
                costume_page(items, "", "", True)
            with self.assertRaises(ValueError):
                costume_page(items, "", "", 0, 0)
            empty_items, empty_files = load_costumes(root / "missing")
            blank = costume_page(empty_items)
            self.assertEqual(blank["total_all"], 0)
            self.assertEqual(len(blank["categories"]), 8)
            self.assertIsNone(costume_file(empty_files, "SPR-0001"))

    def test_cached_costumes_and_http_cache_headers(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            assets = repo / "assets"
            spring = assets / "服饰" / "春"
            spring.mkdir(parents=True)
            for idx in range(26):
                png = spring / f"SPR-{idx + 1:04d}.png"
                png.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
                os.utime(png, (1_700_000_000 + idx, 1_700_000_000 + idx))
            (spring / "SPR-0026.json").write_text(
                json.dumps({"name": "SPR-0026", "关键词": "white shirt", "服饰分类": "春"}, ensure_ascii=False),
                encoding="utf-8",
            )
            c_items, c_files = cached_costumes(assets)
            self.assertEqual(len(c_items), 26)
            self.assertIs(cached_costumes(assets, files_only=True)[1], c_files)
            self.assertEqual(costume_page(c_items, "", "black")["total"], 0)
            # In-place sidecar update invalidates cached metadata automatically.
            (spring / "SPR-0026.json").write_text(
                json.dumps({"name": "SPR-0026", "关键词": "white black coat", "服饰分类": "春"}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.utime(spring / "SPR-0026.json", (1_700_001_000, 1_700_001_000))
            updated_items, _ = cached_costumes(assets)
            self.assertEqual(costume_page(updated_items, "", "black")["total"], 1)
            # Adding a new image invalidates directory signature for both list and content lookups.
            (spring / "SPR-0027.png").write_bytes(b"\x89PNG\r\n\x1a\nnew")
            self.assertIsNotNone(costume_file(cached_costumes(assets, files_only=True)[1], "SPR-0027"))
            projects = repo / "projects"
            projects.mkdir()
            with patch("vsc.interfaces.web.asset_center.repository_root", return_value=repo):
                app = create_app({
                    "projects_root": str(projects),
                    "allowed_hosts": ["testserver"],
                    "allowed_origins": ["http://testserver"],
                    "access_token": "costume-local-test",
                    "human_identity": "test-human",
                    "background_enabled": False,
                })
                with TestClient(app) as client:
                    login = client.post("/api/v1/session", json={"token": "costume-local-test"}, headers={"Origin": "http://testserver"})
                    self.assertEqual(login.status_code, 200, login.text)
                    headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
                    res = client.get("/api/v1/asset-center/costumes?category=春", headers=headers)
                    self.assertEqual(res.status_code, 200, res.text)
                    body = res.json()
                    self.assertEqual(body["limit"], 24)
                    self.assertEqual(len(body["items"]), 24)
                    self.assertEqual(body["next_offset"], 24)
                    self.assertEqual(res.headers.get("cache-control"), "no-store")
                    img_res = client.get("/api/v1/asset-center/costumes/SPR-0027/content")
                    self.assertEqual(img_res.status_code, 200)
                    self.assertEqual(img_res.headers.get("cache-control"), "private, max-age=3600")
                    missing = client.get("/api/v1/asset-center/costumes/SPR-9999/content")
                    self.assertEqual(missing.status_code, 404)
                    self.assertEqual(missing.headers.get("cache-control"), "no-store")


class CostumeGalleryDOMTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for frontend checks")
    def test_official_costume_tabs_search_and_paging(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        result = subprocess.run(["node", str(root / "support/fixtures/frontend/costume_gallery.cjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("costume gallery DOM PASS", result.stdout)
