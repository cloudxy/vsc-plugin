"""Exercise original editor recovery events with a controlled DOM, not Chrome."""
import shutil
import subprocess
import unittest
from pathlib import Path

from support.paths import ROOT


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend behavior checks')
class EditWorkspaceFrontendTests(unittest.TestCase):
    def run_case(self, case):
        result = subprocess.run(['node', str(Path(__file__).with_name('edit_workspace_recovery.cjs')), case],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(case + ' PASS', result.stdout)

    def test_lost_save_response_recovers_original_receipt_and_preserves_unapplied_srt(self):
        self.run_case('lost-response')

    def test_remounted_equal_server_document_reconciles_revision_without_another_save(self):
        self.run_case('equal-remount')

    def test_different_server_document_keeps_conflict_local_edits_and_unapplied_srt(self):
        self.run_case('different-conflict')
