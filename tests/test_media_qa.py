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
        cls.full = cls.root / "full-2s.mp4"
        cls.short_audio = cls.root / "short-audio-2s.mp4"
        cls.half_audio = cls.root / "half-audio.mp4"
        cls.zero = cls.root / "zero.mp4"
        for path, video_length, audio_length in ((cls.full, 2, 2), (cls.short_audio, 2, 1), (cls.half_audio, 1, 0.5)):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=blue:s=320x240:r=30:d={video_length}",
                            "-f", "lavfi", "-i", f"sine=frequency=440:duration={audio_length}", "-c:v", "mpeg4", "-c:a", "aac", str(path)],
                           check=True, capture_output=True, timeout=30)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.media), "-af", "volume=0", "-c:v", "copy", "-c:a", "aac", str(cls.zero)], check=True, capture_output=True, timeout=30)

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
        self.assertEqual(metadata["decode"]["mode"], "complete")

    def test_corrupt_payload_with_valid_header_cannot_pass(self):
        damaged = self.root / "damaged-payload.mp4"
        data = bytearray(self.media.read_bytes())
        marker = data.index(b"mdat")
        atom_size = int.from_bytes(data[marker - 4:marker], "big")
        data[marker + 4:marker - 4 + atom_size] = bytes(atom_size - 8)
        damaged.write_bytes(data)
        metadata_only = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(damaged)], capture_output=True, timeout=30)
        self.assertEqual(metadata_only.returncode, 0, "fixture must retain readable header")
        with self.assertRaises(QA.ProbeFailure) as failure:
            QA.LocalProbeAdapter().probe(damaged)
        self.assertEqual(failure.exception.code, "decode_error")

    def test_audio_early_end_is_rejected_and_planned_silent_tail_is_legal(self):
        value = plan()
        value["composition"]["duration_in_frames"] = 60
        for segment in value["segments"]:
            segment.update(source=self.full.name, duration_in_frames=60)
        self.plan_path.write_text(json.dumps(value))
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.short_audio)
        self.assertEqual(report["render"]["error_code"], "render_audio_coverage_gap")
        value["segments"][1]["duration_in_frames"] = 30
        self.plan_path.write_text(json.dumps(value))
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.short_audio)
        self.assertEqual(report["status"], "passed", report["errors"])

    def test_muted_audio_and_zero_keyframe_tail_do_not_require_samples(self):
        value = plan()
        value["segments"][1]["muted"] = True
        self.plan_path.write_text(json.dumps(value))
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.silent)
        self.assertEqual(report["status"], "passed", report["errors"])
        value["segments"][1].pop("muted")
        value["segments"][1]["volume_keyframes"] = [{"frame": 0, "volume": 1}, {"frame": 14, "volume": 1}, {"frame": 15, "volume": 0}, {"frame": 29, "volume": 0}]
        self.plan_path.write_text(json.dumps(value))
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.half_audio)
        self.assertEqual(report["status"], "passed", report["errors"])
        self.assertEqual(report["render"]["required_audio_intervals_seconds"], [[0, 0.5]])

    def test_decoded_silence_is_legal_without_loudness_target(self):
        report = QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.zero)
        self.assertEqual(report["status"], "passed", report["errors"])
        self.assertTrue(report["render"]["loudness"]["silent"])

    def test_timeline_wrapper_binds_outer_file_hash(self):
        self.plan_path.write_text(json.dumps({"format": "vsc.timeline/v1", "render_plan": plan()}))
        report = self.report()
        self.assertEqual(report["status"], "passed", report["errors"])
        self.assertEqual(report["plan_sha256"], QA.sha256(self.plan_path))

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
        peak = dict(near, true_peak_max_dbtp=-100)
        self.assertEqual(QA.check_plan(self.plan_path, self.root, QA.LocalProbeAdapter(), self.media, peak)["render"]["error_code"], "render_true_peak_exceeded")

    def test_report_recheck_keeps_fixed_loudness_specification(self):
        report = self.report()
        report["loudness_target"] = {"integrated_lufs": report["render"]["loudness"]["integrated_lufs"] - 20, "tolerance_lu": 1, "true_peak_max_dbtp": 0}
        path = self.root / "forged-target.json"
        path.write_text(json.dumps(report))
        self.assertTrue(any("render_loudness_out_of_range" in e for e in QA.validate_report(path)))
        report["loudness_target"]["tolerance_lu"] = float("nan")
        path.write_text(json.dumps(report))
        self.assertTrue(QA.validate_report(path))

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

    def test_structured_review_rejects_bad_ranges_ids_versions_and_sample_delivery(self):
        report = self.report()
        path = self.review_fixture(report)
        legacy = json.loads(path.read_text())
        self.assertTrue(any("legacy" in e for e in QA.validate_review(path, strict=True)))
        review = {**legacy, "evidence_mode": "structured", "render_sha256": report["render"]["metadata"]["sha256"],
                  "scope": {"kind": "complete", "start_frame": 0, "end_frame": 30, "delivery_id": "DEL-001"},
                  "assessments": {category: {"result": "pass", "evidence": [{"start_frame": 0, "end_frame": 30, "shot_id": "SH-001", "segment_id": "shot-1", "note": "synthetic coverage"}]} for category in QA.REVIEW_CATEGORIES}}
        path.write_text(json.dumps(review))
        self.assertEqual(QA.validate_review(path, strict=True), [])
        for key, value in (("end_frame", 31), ("shot_id", "SH-UNKNOWN"), ("segment_id", "missing")):
            bad = json.loads(json.dumps(review))
            bad["assessments"][QA.REVIEW_CATEGORIES[0]]["evidence"][0][key] = value
            path.write_text(json.dumps(bad))
            self.assertTrue(QA.validate_review(path, strict=True), key)
        review["scope"]["kind"] = "sample"
        path.write_text(json.dumps(review))
        self.assertEqual(QA.validate_review(path), [])
        self.assertTrue(any("完整审片" in e for e in QA.validate_review(path, strict=True)))
        review["scope"]["kind"] = "complete"
        review["render_sha256"] = "0" * 64
        path.write_text(json.dumps(review))
        self.assertTrue(any("render_sha256" in e for e in QA.validate_review(path, strict=True)))

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
