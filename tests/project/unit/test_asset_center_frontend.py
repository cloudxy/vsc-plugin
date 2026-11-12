"""Global asset-library, specialized asset editors, folders, and ergonomic image viewer tests."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class AssetCenterFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_global_library_progress_recovery_and_tabs(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("asset_center.test.mjs"))],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_asset_editors_folders_and_image_viewer(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("asset_editors_and_folders.test.mjs"))],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_spa_routes_for_assets_and_recycle(self):
        panel_src = (ROOT / "src/vsc/interfaces/web/static/panel.js").read_text(encoding="utf-8")
        app_src = (ROOT / "src/vsc/interfaces/web/app.py").read_text(encoding="utf-8")
        for route in ('"/character"', '"/character/create"', '"/asset-center"', '"/recycle-bin"'):
            self.assertIn(route, app_src)
        for token in ("p==='/character'", "p==='/character/create'", "p==='/asset-center'", "p==='/recycle-bin'"):
            self.assertIn(token, panel_src)
