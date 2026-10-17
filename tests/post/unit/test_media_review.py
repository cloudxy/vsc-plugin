"""Review rules isolate reprobe; integration tests still use real decoding."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vsc.adapters.media.qa as QA
from support.fixtures.review import write_review


class ReviewRules(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="vsc-review-rules-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        source = self.root / "plan.json"
        source.write_text(json.dumps({"composition": {"duration_in_frames": 30}, "segments": [
            {"id": "shot-1", "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": 30}]}))
        # The reprobe seam is mocked explicitly; these bytes are never technical evidence.
        report = {"project_id": "sample", "plan_path": str(source), "render": {"metadata": {"sha256": "a" * 64}}}
        self.path = write_review(self.root, report, structured=True)
        self.original = json.loads(self.path.read_text())
        reprobe = patch.object(QA, "validate_report", return_value=[])
        self.reprobe = reprobe.start()
        self.addCleanup(reprobe.stop)

    def validate(self, review, strict=True):
        self.path.write_text(json.dumps(review))
        return QA.validate_review(self.path, strict=strict)

    def test_structured_evidence_matrix(self):
        self.assertEqual(self.validate(self.original), [])
        for key, value, error in (("end_frame", 31, "范围"), ("shot_id", "SH-UNKNOWN", "shot_id"),
                                  ("segment_id", "missing", "segment_id")):
            with self.subTest(field=key):
                bad = copy.deepcopy(self.original)
                bad["assessments"][QA.REVIEW_CATEGORIES[0]]["evidence"][0][key] = value
                self.assertTrue(any(error in item for item in self.validate(bad)))
        bad = copy.deepcopy(self.original)
        bad["render_sha256"] = "0" * 64
        self.assertTrue(any("render_sha256" in item for item in self.validate(bad)))

    def test_legacy_and_sample_delivery_policies(self):
        legacy = copy.deepcopy(self.original)
        legacy.pop("evidence_mode")
        for assessment in legacy["assessments"].values():
            assessment["evidence"] = "synthetic timecode"
        self.assertEqual(self.validate(legacy, strict=False), [])
        self.assertTrue(any("legacy" in item for item in self.validate(legacy)))
        sample = copy.deepcopy(self.original)
        sample["scope"]["kind"] = "sample"
        self.assertEqual(self.validate(sample, strict=False), [])
        self.assertTrue(any("完整审片" in item for item in self.validate(sample)))

    def test_reprobe_failure_is_propagated(self):
        self.reprobe.return_value = ["synthetic reprobe failure"]
        self.assertIn("synthetic reprobe failure", self.validate(self.original))
        self.reprobe.assert_called_once_with(self.root / "qa.json")


if __name__ == "__main__":
    unittest.main()
