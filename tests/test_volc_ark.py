#!/usr/bin/env python3
"""volc_ark.py 自测：不联网，用假的接口与下载模拟火山方舟。运行：python3 tests/test_volc_ark.py"""
import contextlib
import datetime
import io
import json
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT
import consistency as C
import volc_ark as A

BIBLE = ROOT / "templates/asset-bible.json"
STATE = ROOT / "templates/scene-state.json"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class ContentTest(unittest.TestCase):
    def test_frame_and_reference_modes_are_exclusive(self):
        content = A.video_content("走向门口", first="f", last="l")
        self.assertEqual([item.get("role") for item in content], [None, "first_frame", "last_frame"])
        with self.assertRaises(A.ArkError):
            A.video_content("p", first="f", images=["r"])
        with self.assertRaises(A.ArkError):
            A.video_content("p", last="l")

    def test_first_frame_reference_becomes_picture_one(self):
        content = A.video_content("走向门口", first_ref="prev", images=["hero"], audios=["voice"])
        self.assertTrue(content[0]["text"].startswith("图片1是本镜首帧"))
        self.assertEqual([item["image_url"]["url"] for item in content if item["type"] == "image_url"], ["prev", "hero"])
        self.assertEqual(content[-1]["role"], "reference_audio")


class InputTest(unittest.TestCase):
    def test_media_type_is_sniffed_from_content(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "看似.png"
            fake.write_bytes(JPEG)
            self.assertEqual(A.media_type(fake), "image/jpeg")
            fake.write_bytes(PNG)
            self.assertEqual(A.media_type(fake), "image/png")

    def test_unexpired_original_is_sent_as_its_url(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            image = project / "a.png"
            image.write_bytes(PNG)
            digest = A.sha256(image)
            later = (A.now() + datetime.timedelta(hours=1)).isoformat()
            sources = {digest: {"source_url": "https://tos/a.png", "source_url_expires_at": later}}
            url, item = A.resolve(str(image), project, sources)
            self.assertEqual((url, item), ("https://tos/a.png", {"path": "a.png", "sha256": digest}))
            expired = A.now() + datetime.timedelta(hours=2)
            url, _ = A.resolve(str(image), project, sources, at=expired)
            self.assertTrue(url.startswith("data:image/png;base64,"))
            self.assertEqual(A.resolve("asset://asset-1", project, {}), ("asset://asset-1", None))
            with self.assertRaises(A.ArkError):
                A.resolve(str(project / "missing.png"), project, {})

    def test_library_original_requires_provider_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            folder = project / "06-素材/素材库/资产-1"
            folder.mkdir(parents=True)
            image = folder / "人物.png"
            image.write_bytes(PNG)
            item = {"path": str(image.relative_to(project)), "sha256": A.sha256(image), "source_url": "https://tos/original.png",
                    "source_url_expires_at": (A.now() + datetime.timedelta(hours=1)).isoformat(), "face_trust_until": "2026-11-01T00:00:00+08:00"}
            manifest = {"format": "vsc.library-use/v1", "provider": A.PROVIDER, "files": [item]}
            receipt = folder / "来源.json"
            receipt.write_text(json.dumps(manifest), "utf-8")
            self.assertEqual(A.resolve(str(image), project, A.originals(project))[0], item["source_url"])
            manifest["provider"] = "other"
            receipt.write_text(json.dumps(manifest), "utf-8")
            self.assertEqual(A.originals(project), {})
            manifest["provider"] = A.PROVIDER
            receipt.write_text(json.dumps(manifest), "utf-8")
            image.write_bytes(JPEG)
            self.assertEqual(A.originals(project), {})

    def test_failed_download_does_not_leave_a_partial_target(self):
        class BrokenResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                raise urllib.error.URLError("disconnected")
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "out.mp4"
            with mock.patch.object(A.urllib.request, "urlopen", return_value=BrokenResponse()), mock.patch.object(A.time, "sleep"):
                with self.assertRaises(A.ArkError):
                    A.download("https://tos/out.mp4", target)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])

    def test_trust_follows_the_platform_rules(self):
        made = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
        self.assertEqual(A.trust_until("doubao-seedream-5-0-flash-260915", made, True), "2026-10-31T00:00:00+00:00")
        self.assertIsNone(A.trust_until("doubao-seedream-5-0-flash-260915", made, False))
        self.assertIsNone(A.trust_until("doubao-seedream-4-5-251128", made, True))
        self.assertIsNotNone(A.trust_until("doubao-seedance-2-5-260628", made, False))


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "vsc.json").write_text(json.dumps({"project_id": json.loads(BIBLE.read_text("utf-8"))["project_id"]}), "utf-8")
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def fake_call(self, path, payload=None, attempts=None):
        self.calls.append((path, payload))
        if path == "/images/generations":
            return {"data": [{"url": "https://tos/out.png"}], "usage": {"generated_images": 1}}
        if path == "/contents/generations/tasks":
            return {"id": "cgt-1"}
        return {"status": "succeeded", "duration": 5, "usage": {"completion_tokens": 10},
                "content": {"video_url": "https://tos/v.mp4", "last_frame_url": "https://tos/last.jpeg"}}

    @staticmethod
    def fake_download(url, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(url.encode())

    def run_cli(self, *argv):
        with mock.patch.object(A, "call", self.fake_call), mock.patch.object(A, "download", self.fake_download), \
                mock.patch.object(A.time, "sleep", lambda _: None), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return A.main(list(argv))

    def test_text_only_asset_image_is_trusted_and_recorded(self):
        self.assertEqual(self.run_cli("image", "--project", str(self.project), "--out", "资产", "--name", "主角-定妆",
                                      "--purpose", "asset", "--prompt", "主角定妆照"), 0)
        record = json.loads((self.project / "资产/主角-定妆-生成记录.json").read_text("utf-8"))
        self.assertEqual(C.record_errors(record), [])
        output = record["outputs"][0]
        self.assertEqual((output["source_url"], record["shot_id"]), ("https://tos/out.png", None))
        self.assertIsNotNone(output["face_trust_until"])
        self.assertNotIn("image", self.calls[0][1])

    def test_video_records_last_frame_and_chains_from_it(self):
        common = ["--project", str(self.project), "--out", "视频", "--bible", str(BIBLE), "--state", str(STATE), "--prompt", "动作"]
        self.assertEqual(self.run_cli("video", *common, "--name", "SH-001-T1", "--shot", "SH-001"), 0)
        first = json.loads((self.project / "视频/SH-001-T1-生成记录.json").read_text("utf-8"))
        self.assertEqual(C.record_errors(first), [])
        self.assertEqual([output.get("role") for output in first["outputs"]], [None, "last_frame"])
        # 下一镜以上一镜返回的尾帧为首帧：记录写明取自上一镜出点，交界核对通过。
        tail = self.project / first["outputs"][1]["path"]
        self.assertEqual(self.run_cli("video", *common, "--name", "SH-002-T1", "--shot", "SH-002", "--first-frame", str(tail)), 0)
        second = json.loads((self.project / "视频/SH-002-T1-生成记录.json").read_text("utf-8"))
        self.assertEqual(second["inputs"]["first_frame"]["from"], "previous_exit")
        self.assertEqual(second["inputs"]["first_frame"]["shot"], "SH-001")
        self.assertEqual(self.calls[-2][1]["content"][1]["image_url"]["url"], "https://tos/last.jpeg")
        state = json.loads(STATE.read_text("utf-8"))
        self.assertEqual(C.chain_problems([first, second], state), [])
        self.assertIn(first["outputs"][1]["sha256"], C.keyframe_index([first, second]))

    def test_resubmission_resumes_the_saved_task(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "SH-001-T1", "--shot", "SH-001", "--prompt", "动作"]
        def interrupted(path, payload=None, attempts=None):
            self.calls.append((path, payload))
            if payload is not None:
                return {"id": "cgt-old"}
            raise A.ArkError("查询中断")
        with mock.patch.object(A, "call", interrupted), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
        task = json.loads((self.project / "视频/SH-001-T1-任务.json").read_text("utf-8"))
        self.assertEqual(task["binding"]["inputs"]["prompt"], "动作")
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual([path for path, _ in self.calls], ["/contents/generations/tasks/cgt-old"])

    def test_saved_task_rejects_changed_request_before_any_network(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "SH-001-T1", "--shot", "SH-001", "--prompt", "动作"]
        self.assertEqual(self.run_cli(*argv), 0)
        original = (self.project / "视频/SH-001-T1-生成记录.json").read_bytes()
        self.calls.clear()
        for change in (["--prompt", "新动作"], ["--model", "different-model"], ["--duration", "9"]):
            self.assertEqual(self.run_cli(*argv, *change), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.project / "视频/SH-001-T1-生成记录.json").read_bytes(), original)
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(self.calls, [])

    def test_legacy_task_requires_verifiable_completed_record(self):
        out = self.project / "视频"
        out.mkdir()
        task_path = out / "SH-001-T1-任务.json"
        task_path.write_text(json.dumps({"id": "cgt-old", "submitted_at": "2026-10-01T00:00:00+08:00"}), "utf-8")
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "SH-001-T1", "--shot", "SH-001", "--prompt", "动作"]
        self.assertEqual(self.run_cli(*argv), 1)
        self.assertEqual(self.calls, [])
        # 有完整、可核实的纯文本任务记录时，旧格式可直接恢复已有结果。
        argv[argv.index("SH-001-T1")] = "已完成"
        self.assertEqual(self.run_cli(*argv), 0)
        modern = out / "已完成-任务.json"
        task = json.loads(modern.read_text("utf-8"))
        modern.write_text(json.dumps({"id": task["id"], "submitted_at": task["submitted_at"]}), "utf-8")
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(self.calls, [])
        (out / "已完成.mp4").write_bytes(b"modified")
        self.assertEqual(self.run_cli(*argv), 1)
        self.assertEqual(self.calls, [])

    def test_reference_mode_is_part_of_the_bound_payload(self):
        ref = self.project / "reference.png"
        ref.write_bytes(PNG)
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "模式", "--shot", "SH-001", "--prompt", "动作"]
        self.assertEqual(self.run_cli(*argv, "--ref-image", str(ref)), 0)
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv, "--ref-video", str(ref)), 1)
        self.assertEqual(self.calls, [])

    def test_output_and_candidate_preflight_happen_before_charge(self):
        image = ["image", "--project", str(self.project), "--out", "资产", "--name", "候选", "--prompt", "动作"]
        self.assertEqual(self.run_cli(*image), 1)
        for extras in (["--out", "../escape"], ["--out", str(self.project / "absolute")], ["--name", "../escape"]):
            self.assertEqual(self.run_cli(*image, "--purpose", "asset", *extras), 1)
        self.assertEqual(self.run_cli(*image, "--shot", "不存在", "--moment", "entry", "--bible", str(BIBLE), "--state", str(STATE)), 1)
        wrong_state = self.project / "state.json"
        state = json.loads(STATE.read_text("utf-8"))
        state["project_id"] = "wrong-project"
        wrong_state.write_text(json.dumps(state), "utf-8")
        self.assertEqual(self.run_cli(*image, "--shot", "SH-001", "--moment", "entry", "--bible", str(BIBLE), "--state", str(wrong_state)), 1)
        with tempfile.TemporaryDirectory() as other:
            (self.project / "outside").symlink_to(other, target_is_directory=True)
            self.assertEqual(self.run_cli(*image, "--purpose", "asset", "--out", "outside"), 1)
        self.assertEqual(self.calls, [])

    def test_existing_image_is_never_overwritten_or_rebilled(self):
        argv = ["image", "--project", str(self.project), "--out", "资产", "--name", "人物", "--purpose", "asset", "--prompt", "人物"]
        self.assertEqual(self.run_cli(*argv), 0)
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_cli(*argv, "--prompt", "新人物"), 1)
        self.assertEqual(self.calls, [])
        (self.project / "资产/手工.png").write_bytes(b"manual")
        self.assertEqual(self.run_cli(*argv, "--name", "手工"), 1)
        self.assertEqual((self.project / "资产/手工.png").read_bytes(), b"manual")
        self.assertEqual(self.calls, [])

    def test_billed_image_download_is_resumable_without_generation(self):
        argv = ["image", "--project", str(self.project), "--out", "资产", "--name", "人物", "--purpose", "asset", "--prompt", "人物"]
        made = A.now() - datetime.timedelta(hours=3)
        response = {"created": made.timestamp(), "data": [{"url": "https://tos/out.png"}], "usage": {"generated_images": 1}}
        with mock.patch.object(A, "call", return_value=response) as call, mock.patch.object(A, "download", side_effect=A.ArkError("断线")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
            self.assertEqual(call.call_count, 1)
        record_path = self.project / "资产/人物-生成记录.json"
        record = json.loads(record_path.read_text("utf-8"))
        self.assertEqual((record["status"], record["budget"]), ("failed", {"billable": True, "usage": response["usage"]}))
        self.assertEqual(C.record_errors(record), [])
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(self.calls, [])
        output = json.loads(record_path.read_text("utf-8"))["outputs"][0]
        self.assertEqual(datetime.datetime.fromisoformat(output["face_trust_until"]),
                         datetime.datetime.fromisoformat(A.stamp(made + A.TRUST_WINDOW)))

    def test_partial_video_download_preserves_usage_and_retries_only_missing_file(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "片段", "--shot", "SH-001", "--prompt", "动作"]
        def fail_tail(url, target):
            if target.suffix == ".jpeg":
                raise A.ArkError("尾帧下载断线")
            self.fake_download(url, target)
        with mock.patch.object(A, "call", self.fake_call), mock.patch.object(A, "download", side_effect=fail_tail), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
        record_path = self.project / "视频/片段-生成记录.json"
        record = json.loads(record_path.read_text("utf-8"))
        self.assertEqual((record["status"], record["budget"]["billable"], len(record["outputs"])), ("partial", True, 1))
        self.assertEqual(C.record_errors(record), [])
        self.calls.clear()
        with mock.patch.object(A, "call", side_effect=AssertionError("must not call API")), \
                mock.patch.object(A, "download", side_effect=self.fake_download) as download, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 0)
            self.assertEqual(download.call_count, 1)
        self.assertEqual(json.loads(record_path.read_text("utf-8"))["status"], "succeeded")

    def test_rejected_submission_is_recorded_as_unbilled_failure(self):
        def reject(path, payload=None, attempts=None):
            raise A.ArkError("HTTP 400: InputImageSensitiveContentDetected")
        with mock.patch.object(A, "call", reject), contextlib.redirect_stderr(io.StringIO()):
            code = A.main(["video", "--project", str(self.project), "--out", "视频", "--name", "X", "--shot", "SH-001", "--prompt", "动作"])
        record = json.loads((self.project / "视频/X-生成记录.json").read_text("utf-8"))
        self.assertEqual((code, record["status"], record["budget"]["billable"]), (1, "failed", False))

    def test_submission_without_task_id_cannot_be_rebilled_on_rerun(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "响应异常", "--shot", "SH-001", "--prompt", "动作"]
        with mock.patch.object(A, "call", return_value={"unexpected": "response"}) as call, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
            self.assertEqual(call.call_count, 1)
        task = json.loads((self.project / "视频/响应异常-任务.json").read_text("utf-8"))
        self.assertEqual(task["submission"], {"unexpected": "response"})
        self.assertEqual(self.run_cli(*argv), 1)
        self.assertEqual(self.calls, [])


class VisualTest(unittest.TestCase):
    def test_checklist_follows_the_anchor_pack(self):
        bible, state = C.load(BIBLE, C.BIBLE_FORMAT), C.load(STATE, C.STATE_FORMAT)
        items = A.checklist(C.anchor_pack(bible, state, "SH-002"), "exit")
        self.assertTrue(any("在画面中" in item for item in items))
        self.assertTrue(any("不可变特征" in item for item in items))
        self.assertTrue(any("地点是" in item for item in items))
        self.assertTrue(any("环境：" in item for item in items))
        self.assertTrue(any("外观为" in item for item in items))
        self.assertTrue(A.entity_checklist(bible, [bible["entities"][0]["id"]]))
        with self.assertRaises(A.ArkError):
            A.entity_checklist(bible, ["不存在"])

    def test_report_must_stay_advisory(self):
        report = {"format": C.VISUAL_FORMAT, "project_id": "p", "shot_id": None, "entities": ["主角"],
                  "subject": {"path": "a.png", "sha256": "0" * 64}, "anchors_sha256": None,
                  "engine": {"provider": "x", "model": "m"}, "advisory": True,
                  "results": [{"item": "光头", "verdict": "pass", "evidence": "是"}], "issues": []}
        self.assertEqual(C.visual_errors(report), [])
        report.update(advisory=False, results=[{"item": "光头", "verdict": "ok"}], entities=None)
        errors = C.visual_errors(report)
        self.assertTrue(any("advisory" in error for error in errors))
        self.assertTrue(any("verdict" in error for error in errors))
        self.assertTrue(any("shot_id" in error for error in errors))
        self.assertEqual(A.parse_json('思考……{"results": []}'), {"results": []})

    def test_inspection_sends_sniffed_mime_and_records_the_exact_checklist(self):
        bible = C.load(BIBLE, C.BIBLE_FORMAT)
        entity = bible["entities"][0]["id"]
        items = A.entity_checklist(bible, [entity]) + ["额外条目"]
        received = []
        def vision(path, payload=None, attempts=None):
            received.append(payload)
            return {"choices": [{"message": {"content": json.dumps({"results": [
                {"item": item, "verdict": "pass", "evidence": "画面显示对应特征"} for item in reversed(items)], "issues": []})}}]}
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "vsc.json").write_text(json.dumps({"project_id": bible["project_id"]}), "utf-8")
            media = project / "实际PNG.jpeg"
            media.write_bytes(PNG)
            argv = ["inspect", "--project", str(project), "--media", str(media), "--bible", str(BIBLE), "--entity", entity, "--check", "额外条目"]
            with mock.patch.object(A, "call", side_effect=vision), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(A.main(argv), 0)
            images = [entry for entry in received[0]["messages"][0]["content"] if entry["type"] == "image_url"]
            self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/png;base64,"))
            report = json.loads(media.with_name("实际PNG-视觉检查.json").read_text("utf-8"))
            self.assertEqual(report["checklist"], items)
            self.assertEqual(C.visual_errors(report), [])

    def test_inspection_rejects_missing_extra_duplicate_and_unevidenced_results(self):
        bible = C.load(BIBLE, C.BIBLE_FORMAT)
        entity = bible["entities"][0]["id"]
        items = A.entity_checklist(bible, [entity])
        good = [{"item": item, "verdict": "pass", "evidence": "对应特征"} for item in items]
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "vsc.json").write_text(json.dumps({"project_id": bible["project_id"]}), "utf-8")
            media = project / "a.png"
            media.write_bytes(PNG)
            argv = ["inspect", "--project", str(project), "--media", str(media), "--bible", str(BIBLE), "--entity", entity]
            variants = [good[:-1], good + [{"item": "不相关条目", "verdict": "pass", "evidence": "有"}],
                        [good[0]] * len(good), [{**item, "evidence": ""} for item in good]]
            for results in variants:
                response = {"choices": [{"message": {"content": json.dumps({"results": results})}}]}
                with mock.patch.object(A, "call", return_value=response), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(A.main(argv), 1)
                self.assertFalse(media.with_name("a-视觉检查.json").exists())


if __name__ == "__main__":
    unittest.main()
