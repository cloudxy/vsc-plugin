"""Account, workspace, invitation and canvas-share UI event recovery."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class AccessControlFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_access_control_frontend_events(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("access_control_frontend.test.mjs"))],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
