"""Run the real artifact panel consumers with isolated asynchronous HTTP fixtures."""
import os
import shutil
import subprocess
import unittest

from support.paths import ROOT


@unittest.skipUnless(shutil.which("node"), "requires Node for frontend behavior verification")
class ArtifactReaderFrontendTests(unittest.TestCase):
    def test_reading_version_controls_and_async_scope_isolation(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests/project/unit/artifact_reader.test.cjs")],
            cwd=ROOT, env={**os.environ, "VSC_TEST_ROOT": str(ROOT)}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
