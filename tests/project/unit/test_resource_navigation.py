"""Execute real panel navigation in Node with the shared offline DOM fixture."""
import os
import shutil
import subprocess
import unittest

from support.paths import ROOT


@unittest.skipUnless(shutil.which("node"), "requires Node for frontend behavior verification")
class ResourceNavigationTests(unittest.TestCase):
    def test_disclosure_selection_keyboard_refresh_and_project_isolation(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests/project/unit/resource_navigation.test.cjs")],
            cwd=ROOT, env={**os.environ, "VSC_TEST_ROOT": str(ROOT)}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
