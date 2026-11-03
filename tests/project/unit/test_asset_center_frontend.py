"""Global asset-library component request and route behavior."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class AssetCenterFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_global_library_progress_recovery_and_tabs(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("asset_center.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
