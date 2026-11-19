"""Node cards, port dragging and connection checks through the real frontend module."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CanvasNodeCardsFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_node_cards_ports_and_connections(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_node_cards.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
