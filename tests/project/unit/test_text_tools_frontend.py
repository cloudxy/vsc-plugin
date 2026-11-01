"""Actual text-tool save race, with bounded DOM and HTTP fixtures."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths


class TextToolsFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_save_keeps_input_typed_while_fixed_request_is_in_flight(self):
        root=Path(__file__).resolve().parents[3]
        result=subprocess.run(["node",str(Path(__file__).with_name("text_tools.test.mjs"))],cwd=root,
            capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
