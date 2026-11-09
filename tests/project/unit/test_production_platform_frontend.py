"""Project creation recovery and local home-discovery failures over the real UI module."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class ProductionPlatformFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_creation_recovery_and_home_discovery(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("production_platform_recovery.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
