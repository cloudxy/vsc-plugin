"""Canvas core 09A-09G & 11-audio-mv frontend unit tests and clean SPA route checks."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class CanvasCoreReplicaFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_core_replica_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_core_replica.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_spa_routes_for_canvas_and_share(self):
        panel_src = (ROOT / "src/vsc/interfaces/web/static/panel.js").read_text(encoding="utf-8")
        app_src = (ROOT / "src/vsc/interfaces/web/app.py").read_text(encoding="utf-8")
        self.assertIn("p==='/canvas'", panel_src)
        self.assertIn("page:'creative-canvas'", panel_src)
        self.assertIn("p==='/canvas/share'", panel_src)
        self.assertIn("focus_node_key", panel_src)
        self.assertIn('"/canvas"', app_src)
        self.assertIn('"/canvas/share"', app_src)
