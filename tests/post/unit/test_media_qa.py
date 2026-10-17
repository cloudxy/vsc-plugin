"""Media fault/rule checks with injected runners; no real decoder process."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from support.paths import ROOT
import vsc.adapters.media.qa as QA
from support.fixtures.plans import media_qa_plan as plan


class FaultTests(unittest.TestCase):
    def test_nonfinite_and_negative_loudness_targets_are_rejected(self):
        target = {"integrated_lufs": -18, "tolerance_lu": 1, "true_peak_max_dbtp": -1}
        for key, value in (("integrated_lufs", float("nan")), ("true_peak_max_dbtp", float("inf")), ("tolerance_lu", -1), ("tolerance_lu", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                QA.validate_loudness_target({**target, key: value})

    def test_complete_decode_timeout_is_unverified(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with self.assertRaises(QA.ProbeFailure) as failure:
            QA.LocalProbeAdapter(runner=runner, decode_timeout=1).decode("unused.mp4")
        self.assertEqual(failure.exception.code, "decode_timeout")
    def test_faults_use_real_error_handling(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "placeholder.mp4"
            path.write_bytes(b"test media")
            for fault in ("timeout", "missing_tool", "invalid_metadata", "probe_error"):
                with self.subTest(fault=fault):
                    with self.assertRaises(QA.ProbeFailure) as failure:
                        QA.FaultProbeAdapter(fault).probe(path)
                    self.assertEqual(failure.exception.code, fault)

    def test_fault_report_never_eligible_for_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "take.mp4").write_bytes(b"test")
            source = root / "plan.json"
            source.write_text(json.dumps(plan()))
            report = QA.check_plan(source, root, QA.FaultProbeAdapter("probe_error"), root / "take.mp4")
            self.assertTrue(report["simulated"])
            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["eligible_for_review"])

    def test_missing_media_is_structured_failure(self):
        with self.assertRaises(QA.ProbeFailure) as failure:
            QA.LocalProbeAdapter().probe("/private/tmp/vsc-nonexistent-media-qa-test.mp4")
        self.assertEqual(failure.exception.code, "missing_media")

    def test_media_mutation_during_probe_does_not_bind_wrong_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mutating.mp4"
            path.write_bytes(b"old")
            def runner(command, **kwargs):
                path.write_bytes(b"new")
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"streams": [{"codec_type": "video"}], "format": {"duration": "1"}}), stderr="")
            with self.assertRaises(QA.ProbeFailure) as failure:
                QA.LocalProbeAdapter(runner=runner).probe(path)
            self.assertEqual(failure.exception.code, "media_changed_during_probe")

    def test_unfinished_review_template_does_not_pass(self):
        errors = QA.validate_review(ROOT / "templates/sample-review.json")
        self.assertTrue(errors)
        self.assertTrue(any("reviewer" in error for error in errors))
