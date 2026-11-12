"""Classic production 06A-06F & 15D (/fcp/:locale) frontend unit tests."""
from pathlib import Path
import shutil
import subprocess
import unittest

from support.paths import ROOT


class ClassicProductionReplicaFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_classic_production_replica_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("classic_production_replica.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_spa_routes_for_classic_production_and_fcp(self):
        panel_src = (ROOT / "src/vsc/interfaces/web/static/panel.js").read_text(encoding="utf-8")
        app_src = (ROOT / "src/vsc/interfaces/web/app.py").read_text(encoding="utf-8")
        for route in ("/storyboard", "/storyboard/repaint", "/video", "/video/review", "/video/multi-clip", "/fcp"):
            self.assertIn(f'"{route}"', app_src)
        self.assertIn("storyboard-repaint", panel_src)
        self.assertIn("video-review", panel_src)
        self.assertIn("fcp-portal", panel_src)
        self.assertIn("/api/v1/fcp-embed/", app_src)
