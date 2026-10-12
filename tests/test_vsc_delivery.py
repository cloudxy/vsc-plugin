#!/usr/bin/env python3
"""Offline synthetic packaging/migration regressions; no real creative approval."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
from test_vsc_handoffs import Fixture
from vsc_delivery import build_bundle, verify_bundle


class Delivery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-delivery-")
        self.root = Path(self.temp.name)
        self.f = Fixture(self.root)
        self.destination = self.root / "bundle"

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return build_bundle(self.f.project, self.f.state, self.f.manifest["id"], self.destination)

    def test_migrate_disconnect_original_and_verify_all_sha(self):
        self.f.media("private/source.txt", b"private source never implicitly copied")
        bundle = self.build()
        migrated = self.root / "migrated"
        shutil.copytree(self.destination, migrated)
        shutil.rmtree(self.f.project)
        report = verify_bundle(migrated, rerun_qa=False)
        self.assertEqual(report["errors"], [], report)
        self.assertEqual(report["integrity"], "passed")
        self.assertEqual(report["qa"][0]["status"], "not_checked")
        self.assertFalse((migrated / "project/private/source.txt").exists())
        self.assertTrue(all(not Path(row["path"]).is_absolute() for row in bundle["files"]))

    def test_missing_media_or_changed_dependency_fails_after_migration(self):
        self.build()
        path = self.destination / "project" / self.f.render["path"]
        path.unlink()
        self.assertTrue(verify_bundle(self.destination, rerun_qa=False)["errors"])
        path.write_bytes(b"wrong final version")
        self.assertTrue(any("SHA不匹配" in e for e in verify_bundle(self.destination, rerun_qa=False)["errors"]))

    def test_unlisted_private_payload_and_symlink_rejected(self):
        self.build()
        (self.destination / "private.txt").write_text("unexpected")
        self.assertTrue(any("未声明" in e for e in verify_bundle(self.destination, rerun_qa=False)["errors"]))
        (self.destination / "link").symlink_to(self.root)
        self.assertTrue(any("符号链接" in e for e in verify_bundle(self.destination, rerun_qa=False)["errors"]))

    def test_source_symlink_escape_and_missing_permission_rejected(self):
        path = self.f.project / self.f.render["path"]
        external = self.root / "external"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.destination.exists())

    def test_no_permission_and_wrong_version_rejected_before_copy(self):
        data = copy.deepcopy(self.f.manifest_data)
        data["package_media"][0]["package_permission"] = False
        item = self.f.register("vsc.delivery_manifest", data, [self.f.timeline, self.f.mix, self.f.qa, self.f.review])
        with self.assertRaises(ValueError):
            build_bundle(self.f.project, self.f.state, item["id"], self.destination)
        self.assertFalse(self.destination.exists())
        self.f.timeline["sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.build()

    def test_engineering_lock_and_parameters_are_explicitly_archived(self):
        code = self.f.media("engineering/Composition.tsx", b"synthetic code")
        lock = self.f.media("engineering/package-lock.json", b"{}")
        data = copy.deepcopy(self.f.manifest_data)
        data["engineering_files"] = [code, lock]
        data["tool_versions"] = {"remotion": "synthetic-version"}
        data["render_parameters"] = {"codec": "synthetic-codec"}
        item = self.f.register("vsc.delivery_manifest", data, [self.f.timeline, self.f.mix, self.f.qa, self.f.review])
        bundle = build_bundle(self.f.project, self.f.state, item["id"], self.destination)
        self.assertTrue((self.destination / "project" / lock["path"]).exists())
        self.assertEqual(bundle["render_parameters"], data["render_parameters"])

    def test_source_bytes_require_explicit_permission_and_locators_recheck_when_included(self):
        f = self.f
        source = f.media("private/source.txt", b"Synthetic permitted line.\n")
        f.state["sources"] = [dict(source, id="S1", kind="original", rights="owned", snapshot=True)]
        adaptation = f.register("vsc.adaptation_plan", {"format": "vsc.adaptation-map/v1", "source_units": [{"id": "SU1", "source_id": "S1", "source_sha256": source["sha256"], "locator": {"kind": "lines", "start": 1, "end": 1}}], "screen_units": []})
        deps = [f.timeline, f.mix, f.qa, f.review, adaptation]
        item = f.register("vsc.delivery_manifest", f.manifest_data, deps)
        without = self.root / "without-source"
        build_bundle(f.project, f.state, item["id"], without)
        self.assertFalse((without / "project" / source["path"]).exists())
        self.assertEqual(verify_bundle(without, rerun_qa=False)["source_revalidation"], "not_checked")
        data = copy.deepcopy(f.manifest_data)
        data["package_media"].append(dict(source, usage_rights="owned", package_permission=True))
        item = f.register("vsc.delivery_manifest", data, deps)
        build_bundle(f.project, f.state, item["id"], self.destination)
        shutil.rmtree(f.project)
        report = verify_bundle(self.destination, rerun_qa=False)
        self.assertEqual(report["errors"], [], report)
        self.assertEqual(report["source_revalidation"], "passed", report)

    def test_fresh_qa_failure_never_becomes_success(self):
        self.build()
        from media_qa import FaultProbeAdapter
        report = verify_bundle(self.destination, adapter=FaultProbeAdapter("missing_tool"))
        self.assertEqual(report["integrity"], "passed", report)
        self.assertEqual(report["status"], "failed", report)
        self.assertTrue(report["errors"])
        self.assertTrue((self.destination / report["qa"][0]["report"]).exists())

    def test_bundle_index_tampering_and_path_traversal_fail(self):
        self.build()
        index = self.destination / "bundle.json"
        data = json.loads(index.read_text("utf-8"))
        data["files"][0]["path"] = "../external"
        index.write_text(json.dumps(data), "utf-8")
        self.assertTrue(verify_bundle(self.destination, rerun_qa=False)["errors"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg")
    def test_real_synthetic_video_rechecks_after_original_is_deleted(self):
        """Actual decode/spec checks prove portability; no fixture passes for fake bytes."""
        from media_qa import LocalProbeAdapter, check_plan
        f = self.f
        source = self.root / "actual.mp4"
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24", "-t", "2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        selected_data = copy.deepcopy(f.selected_data)
        sources = []
        for row in selected_data["items"]:
            row["media"] = f.media(row["media"]["path"], source.read_bytes())
            artifact = f.register("vsc.video_take", source.read_bytes())
            row["source"]["artifact"] = f.ref(artifact)
            next(obj for obj in f.state["objects"] if obj["id"] == row["take_id"])["artifact"] = artifact["id"]
            sources.append(artifact)
        selected = f.register("vsc.selected_takes", selected_data, sources)
        timeline_data = copy.deepcopy(f.timeline_data)
        timeline_data["selected_takes"] = f.ref(selected)
        for row, binding in zip(selected_data["items"], timeline_data["bindings"]):
            binding["sha256"] = row["media"]["sha256"]
        timeline = f.register("vsc.timeline", timeline_data, [selected])
        mix_data = copy.deepcopy(f.mix_data)
        mix_data["timeline"] = f.ref(timeline)
        mix = f.register("vsc.mix", mix_data, [timeline])
        render = f.media(f.render["path"], source.read_bytes())
        qa_data = check_plan(f.project / timeline["path"], f.project, LocalProbeAdapter(), f.project / render["path"])
        self.assertEqual(qa_data["status"], "passed", qa_data)
        qa = f.register("vsc.media_qa", qa_data, [timeline])
        review_data = copy.deepcopy(f.review_data)
        review_data["technical_report_sha256"] = qa["sha256"]
        review_data["render_sha256"] = render["sha256"]
        review = f.register("vsc.sample_review", review_data, [qa])
        manifest_data = copy.deepcopy(f.manifest_data)
        variant = manifest_data["release_variants"][0]
        variant.update(render=render, timeline=f.ref(timeline), mix=f.ref(mix), qa=f.ref(qa), reviews=[f.ref(review)])
        manifest_data["package_media"] = [dict(media, usage_rights="owned", package_permission=True) for media in [render, *[row["media"] for row in selected_data["items"]]]]
        manifest = f.register("vsc.delivery_manifest", manifest_data, [timeline, mix, qa, review])
        build_bundle(f.project, f.state, manifest["id"], self.destination)
        shutil.rmtree(f.project)
        report = verify_bundle(self.destination)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["qa"][0]["status"], "passed", report)
        regenerated = json.loads((self.destination / report["qa"][0]["report"]).read_text("utf-8"))
        self.assertEqual(regenerated["plan_sha256"], timeline["sha256"])


if __name__ == "__main__":
    unittest.main()
