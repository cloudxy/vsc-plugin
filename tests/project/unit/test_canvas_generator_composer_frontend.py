"""Canvas inline node generator composer (Work Package A2) frontend unit tests."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class CanvasGeneratorComposerFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_generator_composer_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_generator_composer.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_composer_stylesheet_is_linked_in_index_template(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        self.assertIn('/static/canvas-generator-composer.css', html)
