"""Browser module tests for the canvas agent stream panel."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths
from support.paths import ROOT


class CanvasAgentStreamFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_agent_stream_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_agent_stream.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stream_stylesheet_is_linked(self):
        html = (ROOT / "src/vsc/interfaces/web/templates/index.html").read_text(encoding="utf-8")
        css = (ROOT / "src/vsc/interfaces/web/static/canvas-agent-stream.css").read_text(encoding="utf-8")
        self.assertIn("/static/canvas-agent-stream.css", html)
        self.assertIn(".cc-agent.cc-agent-stream-on", css)
        self.assertIn(".cc-agent-stream-batch", css)
