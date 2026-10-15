"""CLI contract dispatch and invalid-record reporting for continuity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from support.paths import ROOT, SCRIPTS
from support.fixtures.consistency import RecordFixture


class RecordTest(RecordFixture, unittest.TestCase):
    def test_check_reports_invalid_record_before_indexing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "malformed.json"
            record = self.record()
            record["kind"] = "image"
            record["inputs"].pop("first_frame", None)
            record["outputs"][0].pop("sha256")
            path.write_text(json.dumps(record), "utf-8")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "consistency.py"), "check",
                                     "--bible", str(ROOT / "templates/asset-bible.json"),
                                     "--state", str(ROOT / "templates/scene-state.json"), "--record", str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("INVALID:", result.stderr)
            self.assertIn("sha256", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


class KernelTest(unittest.TestCase):
    def test_contracts_dispatch_through_the_kernel(self):
        for fmt, template in (("vsc.asset-bible/v1", "asset-bible.json"), ("vsc.scene-state/v1", "scene-state.json"),
                              ("vsc.generation-record/v1", "generation-record.json")):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_kernel.py"), "contract", "validate", fmt, str(ROOT / "templates" / template)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
