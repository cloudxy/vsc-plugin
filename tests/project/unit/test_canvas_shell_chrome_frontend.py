"""Canvas shell chrome, bottom toolbar and shortcut frontend tests."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class CanvasShellChromeFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_shell_chrome_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_shell_chrome.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
