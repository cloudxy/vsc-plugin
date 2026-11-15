"""Governance header capsules, safe return links, and settings triage."""
from pathlib import Path
import shutil
import subprocess
import unittest


class GovernanceHeaderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_governance_header_navigation(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("governance_header.test.mjs"))],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
