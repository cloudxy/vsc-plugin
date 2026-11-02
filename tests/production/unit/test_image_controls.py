"""Controlled DOM/parameter evidence, not browser or visual acceptance."""
import pathlib
import shutil
import subprocess
import unittest

class ImageControlsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is required for the existing frontend fixture')
    def test_shared_draft_drag_slider_keys_presets_reset_and_stale_scope(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        result=subprocess.run(['node',str(root/'support/fixtures/frontend/image_controls.cjs')],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('image controls PASS',result.stdout)
