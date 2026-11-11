"""Commerce and electronic invoice frontend regressions with bounded DOM and HTTP fixtures."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class CommerceFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_commerce_frontend_regressions(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("commerce_frontend.test.mjs"))],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
