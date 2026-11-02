"""UI language bindings preserve creative state; controlled DOM, not Chrome."""
import pathlib
import shutil
import subprocess
import unittest

class I18nTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for frontend checks')
    def test_locale_binding_preserves_inputs_selection_pending_and_user_content(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        result = subprocess.run(['node', str(root / 'support/fixtures/frontend/i18n.cjs')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('i18n bindings PASS', result.stdout)
