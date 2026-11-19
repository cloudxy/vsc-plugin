"""Director stage frontend wiring and pure-function tests."""
from pathlib import Path
import shutil
import subprocess
import unittest

import support.paths
from support.paths import ROOT


class CanvasDirectorStageFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_director_stage_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_director_stage.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_director_stage_assets_are_wired(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        canvas = (ROOT / "src/vsc/interfaces/web/static/creative-canvas.js").read_text(encoding="utf-8")
        drawer = (ROOT / "src/vsc/interfaces/web/static/canvas-left-drawer.js").read_text(encoding="utf-8")
        cards = (ROOT / "src/vsc/interfaces/web/static/canvas-node-cards.js").read_text(encoding="utf-8")
        self.assertIn('/static/canvas-director-stage.css', html)
        self.assertIn("from './canvas-director-stage.js'", canvas)
        self.assertIn("applyDirectorStageTypes(TYPES, PORTS)", canvas)
        self.assertIn("ensureDirectorStageDocuments(s.document)", canvas)
        self.assertIn("syncDirectorStagePanorama(s.document)", canvas)
        self.assertIn("mountDirectorStageInspector", canvas)
        self.assertIn("openLegacyDirectorStage", canvas)
        self.assertIn("openLegacySpatialPreview", canvas)
        self.assertIn("panorama_image", canvas)
        self.assertIn("'director-stage':'导演台'", drawer)
        self.assertIn("'3d-preview':'3D预演'", drawer)
        self.assertIn("director:'站位导演台'", drawer)
        self.assertIn("spatial:'三维预演'", drawer)
        self.assertIn("director-stage", cards)
        self.assertIn("3d-preview", cards)
