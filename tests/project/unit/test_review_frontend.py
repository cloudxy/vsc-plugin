"""Bound original review forms and durable result navigation in the real JS."""
import os
import shutil
import subprocess
import unittest
from support.paths import ROOT


class ReviewFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_original_review_forms_and_result_navigation(self):
        result = subprocess.run(["node", "--test", "--test-timeout=5000", str(ROOT / "tests/project/unit/review.test.cjs")],
            capture_output=True, text=True, cwd=ROOT, env={"VSC_TEST_ROOT": str(ROOT), "PATH": os.environ.get("PATH", "")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
