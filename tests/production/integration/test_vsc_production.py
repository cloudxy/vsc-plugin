#!/usr/bin/env python3
"""原生批队列离线集成测试：真实 adapter 参数解析、任务凭证与下载恢复。"""
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.paths import ROOT
from support.fixtures.production import ProductionFixture
import vsc.adapters.providers.volc_ark.api as A
import vsc.production.production as P


class QueueTest(ProductionFixture, unittest.TestCase):

    def test_real_args_dependency_last_frame_and_no_duplicate_generation(self):
        self.batch["jobs"].reverse()
        plan = self.plan()
        self.assertEqual([job["id"] for job in plan["jobs"]], ["image", "first", "second"])
        self.assertFalse((self.project / ".vsc-production").exists())
        journal = self.run_queue(plan)
        self.assertTrue(all(item["status"] == "succeeded" for item in journal["jobs"].values()))
        self.assertEqual(self.calls[0][1]["prompt"], "--literal $(do-not-run)")
        videos = [payload for path, payload in self.calls if path == "/contents/generations/tasks"]
        self.assertEqual(videos[1]["content"][1]["image_url"]["url"], "https://fake/last-task-1")
        self.assertFalse(videos[1]["generate_audio"])
        second = json.loads((self.project / "takes/second-生成记录.json").read_text())
        self.assertEqual(second["inputs"]["first_frame"]["from"], "previous_exit")
        self.assertIn("--first-frame-ref=" + str(self.project.resolve() / "takes/first-尾帧.jpeg"), self.argv[-1])
        count = len(self.calls)
        self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_download_failure_resume_keeps_authoritative_remote_task(self):
        self.fail_download = "last-task-1"
        with self.assertRaises(P.ProductionError):
            self.run_queue()
        journal = json.loads(P.journal_path(self.project, "batch-1").read_text())
        self.assertNotIn("second", journal["jobs"])
        self.assertEqual(journal["jobs"]["first"]["status"], "failed")
        self.run_queue()
        self.assertEqual(sum(path == "/images/generations" for path, _ in self.calls), 1)
        self.assertEqual(sum(path == "/contents/generations/tasks" for path, _ in self.calls), 2)
        self.assertEqual(sum(path.endswith("/task-1") for path, _ in self.calls), 1)

    def test_first_last_frame_mode_passes_real_roles(self):
        for name in ("entry.jpeg", "exit.jpeg"):
            (self.project / name).write_bytes(self.jpeg)
        job = self.batch["jobs"][1]
        job["depends_on"] = []
        job["args"].pop("first_frame_ref")
        job["args"].update(first_frame={"path": "entry.jpeg"}, last_frame={"path": "exit.jpeg"})
        self.batch["jobs"] = [job]
        self.run_queue()
        payload = next(payload for path, payload in self.calls if path == "/contents/generations/tasks")
        self.assertEqual([item.get("role") for item in payload["content"]], [None, "first_frame", "last_frame"])

    def test_output_reference_missing_remote_tail_stops_downstream(self):
        original = self.fake_call
        def without_tail(path, payload=None):
            result = original(path, payload)
            if "content" in result:
                result["content"].pop("last_frame_url")
            return result
        with mock.patch.object(self, "fake_call", side_effect=without_tail):
            with self.assertRaisesRegex(P.ProductionError, "所需输出"):
                self.run_queue()
        self.assertEqual(sum(path == "/contents/generations/tasks" for path, _ in self.calls), 1)

    def test_crash_after_remote_success_before_journal_recovers_without_call(self):
        plan = self.plan()
        def interrupted(argv):
            self.runner(argv)
            raise RuntimeError("journal acknowledgement interrupted")
        with self.assertRaises(P.ProductionError):
            P.run(self.project, plan, plan["plan_sha256"], interrupted)
        self.run_queue(plan)
        self.assertEqual(sum(path == "/images/generations" for path, _ in self.calls), 1)

    def test_unknown_submission_does_not_auto_retry(self):
        plan = self.plan()
        failing = mock.Mock(side_effect=RuntimeError("submission response lost"))
        with self.assertRaises(P.ProductionError):
            P.run(self.project, plan, plan["plan_sha256"], failing)
        with self.assertRaisesRegex(P.ProductionError, "提交状态未知"):
            P.run(self.project, plan, plan["plan_sha256"], failing)
        self.assertEqual(failing.call_count, 1)

    def test_budget_and_attempt_limits(self):
        for key, value in (("max_images", 0), ("max_video_seconds", 9)):
            batch = copy.deepcopy(self.batch)
            batch["budget"][key] = value
            with self.assertRaisesRegex(P.ProductionError, "预算"):
                self.plan(batch)
        batch = copy.deepcopy(self.batch)
        batch["max_remote_jobs"] = 2
        with self.assertRaises(P.ProductionError):
            self.plan(batch)
        self.batch["max_attempts"] = 1
        self.fail_download = "image"
        with self.assertRaises(P.ProductionError):
            self.run_queue()
        with self.assertRaisesRegex(P.ProductionError, "max_attempts"):
            self.run_queue()
        self.assertEqual(len(self.calls), 1)

    def test_plan_and_input_drift_refused(self):
        plan = self.plan()
        with self.assertRaises(P.ProductionError):
            P.run(self.project, plan, "wrong", self.runner)
        self.run_queue(plan)
        self.batch["jobs"][0]["args"]["prompt"] = "new"
        with self.assertRaisesRegex(P.ProductionError, "漂移"):
            self.run_queue()
        (self.project / "bible.json").write_text((self.project / "bible.json").read_text() + "\n")
        with self.assertRaisesRegex(P.ProductionError, "漂移"):
            self.run_queue(plan)

    def test_output_drift_and_lock_refused(self):
        plan = self.plan()
        with P.queue_lock(self.project, plan["id"]):
            with self.assertRaisesRegex(P.ProductionError, "正在执行"):
                self.run_queue(plan)
        self.run_queue(plan)
        (self.project / "takes/image.png").write_bytes(b"edited")
        with self.assertRaisesRegex(P.ProductionError, "漂移"):
            self.run_queue(plan)

    def test_preflight_rejects_all_before_any_invocation(self):
        mutations = [
            lambda b: b["jobs"].append(copy.deepcopy(b["jobs"][0])),
            lambda b: b["jobs"][0]["depends_on"].append("second"),
            lambda b: b["jobs"][1]["depends_on"].append("absent"),
            lambda b: b["jobs"][2]["args"]["first_frame_ref"].update(output="video"),
            lambda b: b["jobs"][2]["args"].update(bible={"path": "../bible.json"}),
            lambda b: b["jobs"][2]["args"].update(bible={"path": "missing.json"}),
            lambda b: b["jobs"][2]["args"].update(shot="not-in-state"),
            lambda b: b["jobs"][2]["args"].pop("state"),
            lambda b: b["jobs"][0]["args"].update(command="rm -rf"),
            lambda b: b["jobs"][0]["args"].update(out="../escape"),
            lambda b: b["jobs"][0]["args"].update(model="aliyun-model"),
            lambda b: b["jobs"][1]["args"].update(first_frame_ref="https://fake/url"),
            lambda b: b["jobs"][1]["args"].update(duration=-1),
        ]
        for mutate in mutations:
            batch = copy.deepcopy(self.batch)
            mutate(batch)
            with self.subTest(batch=batch), self.assertRaises((P.ProductionError, A.ArkError, ValueError)):
                self.plan(batch)
        self.assertFalse(self.calls)
        self.assertFalse((self.project / ".vsc-production").exists())

    def test_library_requires_existing_use_manifest(self):
        ref = {"library": "LIB-1", "path": "06-素材/素材库/LIB-1/ref.jpeg"}
        self.batch["jobs"][0]["args"]["ref"] = [ref]
        with self.assertRaises(P.ProductionError):
            self.plan()
        folder = self.project / "06-素材/素材库/LIB-1"
        folder.mkdir(parents=True)
        image = folder / "ref.jpeg"
        image.write_bytes(self.jpeg)
        manifest = {"format": "vsc.library-use/v1", "item_id": "LIB-1", "project_id": "test-project",
                    "files": [{"path": ref["path"], "sha256": A.sha256(image)}]}
        (folder / "来源.json").write_text(json.dumps(manifest))
        self.assertIn(ref["path"], self.plan()["inputs_sha256"])
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(P.ProductionError, "漂移"):
            self.plan()

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.project / "escape").symlink_to(outside, target_is_directory=True)
            self.batch["jobs"][0]["args"]["out"] = "escape/takes"
            with self.assertRaises(P.ProductionError):
                self.plan()

    def test_local_media_content_categories_and_complete_decode_preflight(self):
        candidates = [("spec.png", b'{"not":"media"}', "first_frame_ref"),
                      ("image.mp4", self.png, "ref_video"),
                      ("video.jpeg", self.mp4, "first_frame_ref"),
                      ("voice.png", self.wav, "first_frame_ref"),
                      ("truncated.png", self.png[:32], "first_frame_ref")]
        for name, data, key in candidates:
            (self.project / name).write_bytes(data)
            batch = copy.deepcopy(self.batch)
            if key == "ref_video":
                batch["jobs"][2]["args"][key] = [{"path": name}]
            else:
                batch["jobs"][2]["args"][key] = {"path": name}
            with self.subTest(name=name), self.assertRaises(P.ProductionError):
                self.plan(batch)
        # 有效图片允许真实内容与扩展名不一致；视频不因此变成图片。
        (self.project / "valid-image.bin").write_bytes(self.png)
        (self.project / "valid-video.bin").write_bytes(self.mp4)
        (self.project / "valid-audio.bin").write_bytes(self.wav)
        batch = copy.deepcopy(self.batch)
        batch["jobs"][2]["args"].update(first_frame_ref={"path": "valid-image.bin"},
                                          ref_video=[{"path": "valid-video.bin"}], ref_audio=[{"path": "valid-audio.bin"}])
        self.plan(batch)
        self.assertFalse(self.calls)
        self.assertFalse((self.project / ".vsc-production").exists())

    def test_library_spec_file_is_not_image_even_with_matching_hash(self):
        folder = self.project / "06-素材/素材库/LIB-spec"
        folder.mkdir(parents=True)
        relative = "06-素材/素材库/LIB-spec/spec.json"
        spec = self.project / relative
        spec.write_text('{"format":"vsc.asset-bible/v1"}')
        manifest = {"format": "vsc.library-use/v1", "project_id": "test-project", "item_id": "LIB-spec",
                    "files": [{"path": relative, "sha256": A.sha256(spec)}]}
        (folder / "来源.json").write_text(json.dumps(manifest))
        self.batch["jobs"][2]["args"]["first_frame_ref"] = {"library": "LIB-spec", "path": relative}
        with self.assertRaisesRegex(P.ProductionError, "媒体"):
            self.plan()
        self.assertFalse(self.calls)

    def test_completed_record_and_task_must_match_rebuilt_binding_and_plan(self):
        self.batch["jobs"] = [self.batch["jobs"][0]]
        self.run_queue()
        record_path = self.project / "takes/image-生成记录.json"
        task_path = self.project / "takes/image-任务.json"
        original_record = json.loads(record_path.read_text())
        original_task = json.loads(task_path.read_text())
        mutations = [lambda r: r["inputs"].update(prompt="changed"),
                     lambda r: r["engine"].update(model="doubao-seedream-other"),
                     lambda r: r.update(shot_id="SH-001"),
                     lambda r: r["engine"]["params"].update(size="4K")]
        count = len(self.calls)
        for mutate in mutations:
            record = copy.deepcopy(original_record)
            mutate(record)
            record_path.write_text(json.dumps(record))
            with self.assertRaisesRegex(P.ProductionError, "绑定"):
                self.run_queue()
        record_path.write_text(json.dumps(original_record))
        task = copy.deepcopy(original_task)
        task["record"]["inputs"]["prompt"] = "task-only edit"
        task_path.write_text(json.dumps(task))
        with self.assertRaisesRegex(P.ProductionError, "绑定"):
            self.run_queue()
        # 即使把 task、记录与签名一起改成自洽内容，也必须匹配原计划。
        record = copy.deepcopy(original_record)
        task = copy.deepcopy(original_task)
        record["engine"]["model"] = "doubao-seedream-other"
        task["binding"]["model"] = record["engine"]["model"]
        record["engine"]["request_sha256"] = A.digest_json(task["binding"])
        task["record"] = record
        record_path.write_text(json.dumps(record))
        task_path.write_text(json.dumps(task))
        with self.assertRaisesRegex(P.ProductionError, "计划"):
            self.run_queue()
        self.assertEqual(len(self.calls), count)

    def test_completed_semantic_binding_survives_expired_transport_and_detects_tampering(self):
        plan = self.plan()
        self.run_queue(plan)
        count = len(self.calls)
        later = A.now() + A.datetime.timedelta(days=2)
        with mock.patch.object(A, "now", return_value=later):
            self.run_queue(plan)
        self.assertEqual(len(self.calls), count)
        record_path, task_path = self.project / "takes/first-生成记录.json", self.project / "takes/first-任务.json"
        record, task = json.loads(record_path.read_text()), json.loads(task_path.read_text())
        self.assertEqual(record["engine"]["semantic_payload_sha256"], task["binding"]["semantic_payload_sha256"])
        record["engine"]["semantic_payload_sha256"] = "f" * 64
        task["binding"]["semantic_payload_sha256"] = "f" * 64
        record["engine"]["request_sha256"] = A.digest_json(task["binding"])
        task["record"] = record
        record_path.write_text(json.dumps(record))
        task_path.write_text(json.dumps(task))
        with self.assertRaisesRegex(P.ProductionError, "语义请求"):
            self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_completed_typed_references_keep_media_roles_and_content_binding(self):
        for name, data in (("identity.png", self.png), ("action.mp4", self.mp4), ("sound.wav", self.wav)):
            (self.project / name).write_bytes(data)
        job = self.video("multimodal", "SH-001", [], {"path": "identity.png"})
        job["args"].update(ref_image=[{"path": "identity.png"}], ref_video=[{"path": "action.mp4"}], ref_audio=[{"path": "sound.wav"}])
        self.batch["jobs"] = [job]
        plan = self.plan()
        self.run_queue(plan)
        count = len(self.calls)
        record_path, task_path = self.project / "takes/multimodal-生成记录.json", self.project / "takes/multimodal-任务.json"
        record, task = json.loads(record_path.read_text()), json.loads(task_path.read_text())
        self.assertEqual([ref["media_type"] for ref in record["inputs"]["references"]], ["image", "video", "audio"])
        self.run_queue(plan)
        self.assertEqual(len(self.calls), count)
        ref = record["inputs"]["references"][1]
        ref.update(media_type="audio", role="reference_audio", purpose="sound")
        task["binding"]["inputs"] = record["inputs"]
        record["engine"]["request_sha256"] = A.digest_json(task["binding"])
        task["record"] = record
        record_path.write_text(json.dumps(record))
        task_path.write_text(json.dumps(task))
        with self.assertRaisesRegex(P.ProductionError, "参考媒体角色"):
            self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_generated_fake_video_is_rejected_before_downstream(self):
        original = self.fake_download
        def jpeg_as_video(url, target):
            if target.suffix == ".mp4":
                target.write_bytes(self.jpeg)
            else:
                original(url, target)
        with mock.patch.object(self, "fake_download", side_effect=jpeg_as_video):
            with self.assertRaisesRegex(P.ProductionError, "媒体类别"):
                self.run_queue()
        self.assertEqual(sum(path == "/contents/generations/tasks" for path, _ in self.calls), 1)
        count = len(self.calls)
        with self.assertRaisesRegex(P.ProductionError, "媒体类别"):
            self.run_queue()
        self.assertEqual(len(self.calls), count)

    def test_output_ids_and_roles_are_verified_and_png_tail_is_allowed(self):
        original = self.fake_download
        def png_tail(url, target):
            if "last-" in url:
                target.write_bytes(self.png)
            else:
                original(url, target)
        with mock.patch.object(self, "fake_download", side_effect=png_tail):
            self.run_queue()
        record_path = self.project / "takes/first-生成记录.json"
        task_path = self.project / "takes/first-任务.json"
        record = json.loads(record_path.read_text())
        task = json.loads(task_path.read_text())
        record["outputs"][0]["id"] = "forged-role"
        task["record"] = record
        record_path.write_text(json.dumps(record))
        task_path.write_text(json.dumps(task))
        count = len(self.calls)
        with self.assertRaisesRegex(P.ProductionError, "ID 或角色"):
            self.run_queue()
        self.assertEqual(len(self.calls), count)

    def test_existing_and_planned_output_file_ancestors_fail_before_generation(self):
        (self.project / "blocked").write_text("ordinary file")
        self.batch["jobs"][2]["args"]["out"] = "blocked/nested"
        with self.assertRaisesRegex(P.ProductionError, "祖先不是目录"):
            self.plan()
        self.batch["jobs"][2]["args"]["out"] = "takes/image.png/nested"
        with self.assertRaisesRegex(P.ProductionError, "目录祖先"):
            self.plan()
        self.assertFalse(self.calls)
        self.assertFalse((self.project / ".vsc-production").exists())

    def test_cli_plan_and_unexecuted_run_are_read_only(self):
        batch_path = self.project / "batch.json"
        batch_path.write_text(json.dumps(self.batch))
        for command in ("plan", "validate", "status", "run"):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(P.main([command, str(batch_path), "--project", str(self.project)]), 0)
        self.assertFalse((self.project / ".vsc-production").exists())


if __name__ == "__main__":
    unittest.main()
