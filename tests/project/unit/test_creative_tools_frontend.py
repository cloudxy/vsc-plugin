"""Creative-tool tab scrolling over the real panel module."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CreativeToolsFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_tool_tab_scroll(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("creative_tools_tabs.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
