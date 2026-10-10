#!/usr/bin/env python3
"""Actual local media and fault adapter tests; no paid or remote generation."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
import media_qa as QA


def plan():
    return {"format": "vsc.remotion-render-plan/v1", "project_id": "sample", "composition": {"id": "sample", "width": 320, "height": 240, "fps": 30, "duration_in_frames": 30}, "segments": [{"id": "shot-1", "kind": "video", "source": "take.mp4", "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": 30, "muted": True}, {"id": "bgm", "kind": "audio", "source": "take.mp4", "from_frame": 0, "duration_in_frames": 30}]}


class FaultTests(unittest.TestCase):
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
        errors = QA.validate_review(Path(__file__).resolve().parents[1] / "templates" / "sample-review.json")
        self.assertTrue(errors)
        self.assertTrue(any("reviewer" in error for error in errors))


@unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "Real local adapter integration requires ffprobe and ffmpeg")
class LocalMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.media = cls.root / "take.mp4"
        result = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.media)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(f"Real ffmpeg fixture generation failed: {result.stderr}")
        cls.silent = cls.root / "silent.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.media), "-c:v", "copy", "-an", str(cls.silent)], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(plan()))

    def report(self, render=True):
        return QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.media if render else None)

    def test_real_probe_and_source_render_range(self):
        report = self.report()
        self.assertEqual(report["status"], "passed", report["errors"])
        self.assertTrue(report["eligible_for_review"])
        self.assertFalse(report["simulated"])
        metadata = report["render"]["metadata"]
        self.assertEqual(metadata["sha256"], QA.sha256(self.media))
        self.assertEqual({s["codec_type"] for s in metadata["streams"]}, {"audio", "video"})
        self.assertAlmostEqual(metadata["duration_seconds"], 1, places=2)

    def test_render_loudness_is_measured_and_checked_against_target(self):
        loudness = self.report()["render"]["loudness"]
        self.assertLess(loudness["integrated_lufs"], 0)
        self.assertIsNotNone(loudness["true_peak_dbtp"])
        near = {"integrated_lufs": loudness["integrated_lufs"], "tolerance_lu": 1.0, "true_peak_max_dbtp": 0.0}
        self.assertEqual(QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.media, near)["status"], "passed")
        far = dict(near, integrated_lufs=loudness["integrated_lufs"] - 20)
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.media, far)
        self.assertEqual(report["render"]["error_code"], "render_loudness_out_of_range")
        self.assertFalse(report["eligible_for_review"])

    def test_source_range_overflow_is_detected_from_actual_media(self):
        value = plan()
        value["segments"][0]["source_in_frame"] = 15
        self.plan_path.write_text(json.dumps(value))
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["sources"][0]["error_code"], "source_range_overflow")

    def test_real_missing_audio_and_dimension_mismatch(self):
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.silent)
        self.assertEqual(report["render"]["error_code"], "missing_audio")
        value = plan()
        value["composition"]["width"] = 640
        self.plan_path.write_text(json.dumps(value))
        report = self.report()
        self.assertEqual(report["render"]["error_code"], "render_dimensions_mismatch")

    def test_symbolic_link_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.mp4"
            target.write_bytes(self.media.read_bytes())
            link = self.root / "outside-link.mp4"
            try:
                link.symlink_to(target)
                value = plan()
                value["segments"][0]["source"] = link.name
                self.plan_path.write_text(json.dumps(value))
                report = self.report()
                self.assertEqual(report["sources"][0]["error_code"], "unsafe_media")
            finally:
                link.unlink(missing_ok=True)

    def test_corrupt_real_media_is_failure(self):
        corrupt = self.root / "corrupt.mp4"
        corrupt.write_bytes(b"not a video")
        with self.assertRaises(QA.ProbeFailure) as failure:
            QA.LocalProbeAdapter().probe(corrupt)
        self.assertEqual(failure.exception.code, "probe_error")

    def review_fixture(self, report):
        qa_path = self.root / "qa.json"
        qa_path.write_text(json.dumps(report))
        review = {"format": QA.REVIEW_FORMAT, "project_id": "sample", "reviewer": "director", "technical_report": qa_path.name, "technical_report_sha256": QA.sha256(qa_path), "assessments": {category: {"result": "pass", "evidence": "00:00–00:01 SH-001 synthetic fixture manually inspected"} for category in QA.REVIEW_CATEGORIES}, "run": {"elapsed_seconds": 1, "cost_amount": 0, "currency": "CNY", "failures": []}}
        path = self.root / "review.json"
        path.write_text(json.dumps(review))
        return path

    def test_review_binds_report_media_and_plan_versions(self):
        path = self.review_fixture(self.report())
        self.assertEqual(QA.validate_review(path), [])
        original = self.plan_path.read_text()
        self.plan_path.write_text(original + "\n")
        self.assertTrue(any("plan_sha256" in e for e in QA.validate_review(path)))

    def test_sources_only_report_cannot_complete_review(self):
        path = self.review_fixture(self.report(render=False))
        self.assertTrue(any("成片技术报告" in e for e in QA.validate_review(path)))

    def test_render_changed_after_probe_requires_new_report(self):
        copy = self.root / "render-copy.mp4"
        copy.write_bytes(self.media.read_bytes())
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), copy)
        path = self.review_fixture(report)
        self.assertEqual(QA.validate_review(path), [])
        copy.write_bytes(copy.read_bytes() + b"changed")
        self.assertTrue(any("render" in e for e in QA.validate_review(path)))

    def test_approval_validator_reprobes_and_rejects_forged_metadata(self):
        report = self.report()
        path = self.root / "validate-report.json"
        path.write_text(json.dumps(report))
        self.assertEqual(QA.validate_report(path), [])
        report["render"]["metadata"]["duration_seconds"] = 900
        path.write_text(json.dumps(report))
        self.assertTrue(any("render" in error for error in QA.validate_report(path)))

    def test_approval_validator_rejects_empty_sources_and_render(self):
        report = self.report()
        path = self.root / "validate-report-empty.json"
        report["sources"] = []
        path.write_text(json.dumps(report))
        self.assertTrue(any("sources" in error for error in QA.validate_report(path)))
        report = self.report()
        report["render"] = {}
        path.write_text(json.dumps(report))
        self.assertTrue(any("metadata" in error for error in QA.validate_report(path)))


if __name__ == "__main__":
    unittest.main()
