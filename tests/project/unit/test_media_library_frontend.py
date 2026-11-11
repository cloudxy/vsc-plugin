"""Media library filters, pagination, preview sequences and cleanup in the real UI."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class MediaLibraryFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_media_library_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("media_library.test.mjs"))],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
