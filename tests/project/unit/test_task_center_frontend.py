"""Task and usage UI state, permissions and recovery over the real ES module."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class TaskCenterFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_task_center_ui(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("task_center.test.mjs"))],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
