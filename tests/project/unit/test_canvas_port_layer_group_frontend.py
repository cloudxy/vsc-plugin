"""Port, layer, group and asset canvas interactions."""
from pathlib import Path
import shutil
import subprocess
import unittest


class CanvasPortLayerGroupFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_port_layer_group_frontend(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_port_layer_group.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
