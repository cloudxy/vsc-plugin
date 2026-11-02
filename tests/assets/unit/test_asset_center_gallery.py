"""Actual gallery component event checks with a controlled DOM, not Chrome."""
import pathlib
import shutil
import subprocess
import unittest


class AssetCenterGalleryDOMTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for frontend checks')
    def test_gallery_fixed_import_recovery_scope_and_locale(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        result = subprocess.run(['node', str(root / 'support/fixtures/frontend/asset_center_gallery.cjs')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('asset gallery DOM PASS', result.stdout)
