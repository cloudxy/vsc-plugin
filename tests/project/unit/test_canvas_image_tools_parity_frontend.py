"""Image-tool parity overlays, credits and serialized generation settings."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CanvasImageToolsParityFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_image_tools_parity_frontend(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_image_tools_parity.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
