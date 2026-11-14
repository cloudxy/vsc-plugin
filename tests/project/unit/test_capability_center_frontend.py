"""Capability discovery, reading, cancellation and standalone sidebar entry."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CapabilityCenterFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node.js')
    def test_capability_center(self):
        result = subprocess.run(
            ['node', '--test', str(Path(__file__).with_name('capability_center.test.mjs'))],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
