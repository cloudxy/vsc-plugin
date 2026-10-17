"""Execute creative reading, relation drill-down and query isolation in the real module."""
import os
import shutil
import subprocess
import unittest

from support.paths import ROOT


@unittest.skipUnless(shutil.which('node'), 'requires Node for frontend behavior verification')
class WorkbenchFrontendTests(unittest.TestCase):
    def test_reading_search_relations_and_isolation(self):
        result = subprocess.run(['node', '--test', str(ROOT / 'tests/project/unit/workbench.test.cjs')],
            cwd=ROOT, env={**os.environ, 'VSC_TEST_ROOT': str(ROOT)}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
