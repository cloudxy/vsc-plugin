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
        report = {"format": QA.FORMAT, "project_id": "sample", "plan_path": str(source), "plan_sha256": "b" * 64,
                  "status": "passed", "adapter": QA.LocalProbeAdapter.name, "simulated": False,
                  "eligible_for_review": True, "errors": [], "expected": {"duration_seconds": 1, "fps": 30},
                  "sources": [{"status": "passed", "metadata": {"sha256": "c" * 64}}],
                  "render": {"status": "passed", "metadata": {"sha256": "a" * 64}}}
        self.report = report
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

    def test_checklist_summarizes_matching_actual_fields_without_replacing_strict_gate(self):
        checklist = QA.delivery_checklist([self.original], [self.report], [{"advisory": True}])
        self.assertTrue(checklist["matching_evidence_present"])
        self.assertNotIn("formal_delivery_ready", checklist)
        self.assertEqual(checklist["technical_qa"]["count"], 1)
        self.assertEqual(checklist["human_full_play"]["count"], 1)
        self.assertTrue(checklist["summary_only"])
        self.assertTrue(checklist["strict_validation_required"])
        self.reprobe.assert_not_called()
        self.assertFalse(QA.delivery_checklist(
            [{"review_method": "human_full_play", "scope_complete": True, "reviewer": "name"}],
            [{"passed": True, "real_adapter": True}])["matching_evidence_present"])

    def test_checklist_rejects_cross_media_partial_failed_or_unnamed_evidence(self):
        review_changes = {
            "different-media": lambda row: row.update(render_sha256="d" * 64),
            "different-project": lambda row: row.update(project_id="another"),
            "sample": lambda row: row["scope"].update(kind="sample"),
            "partial-range": lambda row: row["scope"].update(end_frame=29),
            "boolean-range": lambda row: row["scope"].update(start_frame=False),
            "no-delivery": lambda row: row["scope"].pop("delivery_id"),
            "failed": lambda row: row["assessments"][QA.REVIEW_CATEGORIES[0]].update(result="fail"),
            "missing-category": lambda row: row["assessments"].pop(QA.REVIEW_CATEGORIES[0]),
            "missing-evidence": lambda row: row["assessments"][QA.REVIEW_CATEGORIES[0]].update(evidence=[]),
            "unnamed": lambda row: row.update(reviewer=" "),
            "no-method": lambda row: row.pop("review_method"),
            "ai": lambda row: row.update(review_method="ai_with_audio"),
        }
        for name, change in review_changes.items():
            with self.subTest(review=name):
                review = copy.deepcopy(self.original)
                change(review)
                self.assertFalse(QA.delivery_checklist([review], [self.report])["matching_evidence_present"])
        qa_changes = {
            "failed": lambda row: row.update(status="failed"),
            "simulated": lambda row: row.update(simulated=True),
            "fault-adapter": lambda row: row.update(adapter="fault-probe/v1"),
            "no-render": lambda row: row.update(render=None),
            "render-failed": lambda row: row["render"].update(status="failed"),
            "no-sources": lambda row: row.update(sources=[]),
            "no-duration": lambda row: row.pop("expected"),
        }
        for name, change in qa_changes.items():
            with self.subTest(qa=name):
                report = copy.deepcopy(self.report)
                change(report)
                self.assertFalse(QA.delivery_checklist([self.original], [report])["matching_evidence_present"])


if __name__ == "__main__":
    unittest.main()
