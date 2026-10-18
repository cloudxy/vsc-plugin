#!/usr/bin/env python3
"""Actual local media and fault adapter tests; no paid or remote generation."""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT  # noqa: F401  被测模块位于所属源码包
import vsc.adapters.media.qa as QA
from support.fixtures.plans import media_qa_plan as plan
from support.fixtures.review import write_review
from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture






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
        return write_review(self.root, report)

    def test_review_binds_report_media_and_plan_versions(self):
        path = self.review_fixture(self.report())
        self.assertEqual(QA.validate_review(path), [])
        original = self.plan_path.read_text()
        self.plan_path.write_text(original + "\n")
        self.assertTrue(any("plan_sha256" in e for e in QA.validate_review(path)))

    def test_structured_review_binds_real_media_and_complete_scope(self):
        path = write_review(self.root, self.report(), structured=True)
        self.assertEqual(QA.validate_review(path, strict=True), [])

    def test_pg_contract_requires_full_human_review_of_the_same_real_media(self):
        from vsc.project.pg_workflow import validate_contract
        path = write_review(self.root, self.report(), structured=True)
        original = json.loads(path.read_text())
        original["technical_report"] = str(self.root / "qa.json")
        self.assertEqual(validate_contract(original, "vsc.sample_review", "production-v2"), [])
        for method in ("ai_static_frame", "ai_with_audio", "tool_probe", None):
            with self.subTest(method=method):
                review = copy.deepcopy(original)
                if method is None:
                    review.pop("review_method")
                else:
                    review["review_method"] = method
                self.assertTrue(validate_contract(review, "vsc.sample_review", "production-v2"))
                self.assertEqual(validate_contract(review, "vsc.sample_review", "legacy"), [])
        for name, mutate in (
                ("partial", lambda row: row["scope"].update(kind="sample")),
                ("failure", lambda row: row["assessments"][QA.REVIEW_CATEGORIES[0]].update(result="fail")),
                ("different-render", lambda row: row.update(render_sha256="0" * 64))):
            with self.subTest(evidence=name):
                review = copy.deepcopy(original)
                mutate(review)
                self.assertTrue(validate_contract(review, "vsc.sample_review", "production-v2"))

    def test_checklist_uses_real_qa_review_fields_and_matching_render(self):
        report = self.report()
        path = write_review(self.root, report, structured=True)
        review = json.loads(path.read_text())
        checklist = QA.delivery_checklist([review], [report])
        self.assertTrue(checklist["matching_evidence_present"])
        self.assertTrue(checklist["strict_validation_required"])
        # A freshly re-encoded render is still a different fixed media version.
        review["render_sha256"] = QA.sha256(self.zero)
        self.assertFalse(QA.delivery_checklist([review], [report])["matching_evidence_present"])

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


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS
                     and shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "requires explicit isolated PostgreSQL and local FFmpeg")
class PostgresReviewTests(ResourceStoreFixture, unittest.TestCase):
    """Exercise production-v2 service and Gate wiring, including historical rows.

    Upstream store-only stubs represent already stored history and establish the
    actual Profile dependency graph. They are not claimed to pass their contracts
    or the whole delivery Gate. Only this test's media QA and review are real.
    """

    def setUp(self):
        from vsc.project.state import profile_for
        self.profile = profile_for("vsc.series-pg")
        self.project = self.service.create_project({"name": "Synthetic strict review wiring",
            "profile_snapshot": self.profile}, actor="test-human")
        self.p, self.rev = self.project["id"], 0
        self.objects = self.hierarchy()
        temp = tempfile.TemporaryDirectory(prefix="vsc-pg-review-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.media_path = self.root / "take.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "mpeg4",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.media_path)],
                       check=True, capture_output=True, timeout=30)
        plan_path = self.root / "plan.json"
        value = plan()
        value["project_id"] = self.p
        plan_path.write_text(json.dumps(value))
        self.report = QA.check_plan(plan_path, self.root, QA.LocalProbeAdapter(), self.media_path)
        self.assertEqual(self.report["status"], "passed", self.report["errors"])
        path = write_review(self.root, self.report, structured=True)
        self.review = json.loads(path.read_text())
        self.review.update(project_id=self.p, technical_report=str(self.root / "qa.json"))

    def store_write(self, method, payload):
        import uuid
        result = getattr(self.store, method)(self.p, payload, expected_revision=self.rev,
            idempotency_key=uuid.uuid4().hex, actor="test-human")
        self.rev = result["revision"]
        return result

    def seed_upstream_history(self):
        from vsc.assets.resource_service import dependency_requirements
        pins = {}
        for stage in self.profile["stages"]:
            if stage["id"] == "delivery":
                break
            for kind in stage["required"]:
                requirements, _ = dependency_requirements(self.profile, kind)
                row = self.store_write("create_artifact", {"artifact_key": kind, "artifact_type": kind,
                    "document": {"historical_synthetic_stub": kind}, "stage": stage["id"],
                    "dependency_ids": [pins[key] for key in requirements]})
                self.store_write("decide_artifact", {"artifact_id": row["id"], "reason": "Synthetic historical dependency"})
                pins[kind] = row["id"]
        qa = self.write("create_artifact", {"artifact_key": "qa", "artifact_type": "vsc.media_qa", "document": self.report,
            "dependency_ids": [pins["vsc.timeline"], pins["vsc.mix"]]})
        self.write("decide_artifact", {"artifact_id": qa["id"], "reason": "Synthetic real decoded media QA fixture"})
        return qa["id"]

    def test_creation_approval_and_gate_recheck_strict_review_policy(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.project.pg_workflow import check_gate
        qa_id = self.seed_upstream_history()
        for method in ("ai_static_frame", "ai_with_audio", "tool_probe", None):
            with self.subTest(method=method):
                review = copy.deepcopy(self.review)
                if method is None:
                    review.pop("review_method")
                else:
                    review["review_method"] = method
                payload = {"artifact_key": "review", "artifact_type": "vsc.sample_review", "document": review,
                           "dependency_ids": [qa_id]}
                with self.assertRaises(ResourceError) as created:
                    self.write("create_artifact", payload)
                self.assertEqual(created.exception.code, "invalid_contract")
                # Import an old row through the repository to exercise both later
                # enforcement points without mutating immutable document bytes.
                old = self.store_write("create_artifact", payload)
                with self.assertRaises(ResourceError) as approved:
                    self.write("decide_artifact", {"artifact_id": old["id"], "reason": "Must be rechecked"})
                self.assertEqual(approved.exception.code, "invalid_contract")
                self.store_write("decide_artifact", {"artifact_id": old["id"], "reason": "Synthetic historical approval fixture"})
                gate = check_gate(self.service, self.p, "delivery", self.objects["episode"])
                self.assertTrue(any(gap.get("code") == "invalid_contract" and gap.get("artifact_id") == old["id"]
                                    for gap in gate["gaps"]), gate)
                self.assertNotIn(old["id"], [pin["id"] for pin in gate["artifacts"]])
        valid = self.write("create_artifact", {"artifact_key": "review", "artifact_type": "vsc.sample_review",
            "document": self.review, "dependency_ids": [qa_id]})
        self.write("decide_artifact", {"artifact_id": valid["id"], "reason": "Synthetic operator decision on full-play evidence"})
        gate = check_gate(self.service, self.p, "delivery", self.objects["episode"])
        self.assertIn(valid["id"], [pin["id"] for pin in gate["artifacts"]])
        self.assertFalse(any(gap.get("artifact_id") == valid["id"] for gap in gate["gaps"]))
        # SHA drift after the decision must force a new QA/review at the next Gate.
        self.media_path.write_bytes(self.media_path.read_bytes() + b"new-version")
        gate = check_gate(self.service, self.p, "delivery", self.objects["episode"])
        self.assertTrue(any(gap.get("code") == "invalid_contract" and gap.get("artifact_id") == valid["id"]
                            for gap in gate["gaps"]))


if __name__ == "__main__":
    unittest.main()
