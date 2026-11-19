"""Canvas audio/video mode bar frontend unit tests."""
from pathlib import Path
import shutil
import subprocess
import unittest

import support.paths
from support.paths import ROOT


class CanvasAvModesFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_av_modes_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_av_modes.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_av_modes_stylesheet_and_import_are_wired(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        canvas = (ROOT / "src/vsc/interfaces/web/static/creative-canvas.js").read_text(encoding="utf-8")
        composer = (ROOT / "src/vsc/interfaces/web/static/canvas-generator-composer.js").read_text(encoding="utf-8")
        self.assertIn('/static/canvas-av-modes.css', html)
        self.assertIn("from './canvas-av-modes.js'", canvas)
        self.assertIn("mountAvAudioTools", canvas)
        self.assertIn("mountAvVideoFrameTools", canvas)
        self.assertIn("generatorQuoteFields", composer)
