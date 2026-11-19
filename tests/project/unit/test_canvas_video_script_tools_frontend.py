"""Frontend behavior for canvas video, sample, breakdown and script nodes."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CanvasVideoScriptToolsFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_video_script_tools_frontend(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_video_script_tools.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
