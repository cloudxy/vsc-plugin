"""Left drawer, history restore and asset-library frontend behavior."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CanvasLeftDrawerFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_left_drawer_frontend(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_left_drawer.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
