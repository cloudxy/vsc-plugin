"""Classic mode capability filtering through the real frontend module."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class ClassicCapabilitiesFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_classic_mode_capabilities(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("classic_capabilities.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
