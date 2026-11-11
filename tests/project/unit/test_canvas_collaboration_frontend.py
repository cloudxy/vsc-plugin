"""Canvas collaboration OE permissions, recovery queue, WS sync_protocol=2 and UI dialogs."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CanvasCollaborationFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_collaboration_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_collaboration.test.mjs"))],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
