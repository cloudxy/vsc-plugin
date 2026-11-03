"""Canvas placement and selection through the real frontend module."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CanvasPlacementFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_placement_and_selection(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_placement.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
