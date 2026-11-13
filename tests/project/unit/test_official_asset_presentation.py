"""Scoped UI regressions for official/reference browsing and member presentation."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class OfficialAssetPresentationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_source_paging_and_member_presentation(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("official_asset_presentation.test.mjs"))],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
