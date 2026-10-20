"""Exercise actual desk modules with deterministic HTTP and late responses."""
import os
import shutil
import subprocess
import unittest
from support.paths import ROOT


@unittest.skipUnless(shutil.which("node"), "requires Node")
class AssistedDeskFrontendTests(unittest.TestCase):
    def test_desk_navigation_drafts_fixed_targets_and_recycle(self):
        result = subprocess.run(["node", "--test", "--test-timeout=10000",
            str(ROOT / "tests/project/unit/assisted_desk.test.cjs")],
            cwd=ROOT, env={**os.environ, "VSC_TEST_ROOT":str(ROOT)},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
