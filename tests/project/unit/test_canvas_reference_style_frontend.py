"""Canvas reference, style, focus capture and input preflight frontend tests."""
from pathlib import Path
import shutil
import subprocess
import unittest

import support.paths
from support.paths import ROOT


class CanvasReferenceStyleFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_reference_style_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_reference_style.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_style_stylesheet_is_linked(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        self.assertIn('/static/canvas-reference-style.css', html)
        self.assertIn('/static/canvas-generator-composer.css', html)
