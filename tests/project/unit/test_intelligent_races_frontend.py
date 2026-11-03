"""Controlled DOM regression for intelligent workflow races and ordering."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class IntelligentRacesFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_intelligent_races_and_ordering(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("intelligent_races.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
