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
    def test_missing_key_points_to_configuration_without_loading_or_network(self):
        with mock.patch.dict(A.os.environ, {}, clear=True), \
                mock.patch.object(A.Path, "read_text", side_effect=AssertionError("must not read shell config")), \
                mock.patch.object(A.urllib.request, "urlopen") as remote:
            with self.assertRaisesRegex(A.ArkError, "火山方舟 Agent 版本.*ARK_AGENT_PLAN_API_KEY") as error:
                A.call("/images/generations", {"prompt": "offline"})
            self.assertIn("source ~/.zshenv", str(error.exception))
            remote.assert_not_called()

    def test_other_ark_variables_are_ignored_and_plan_base_is_default(self):
        with mock.patch.dict(A.os.environ, {"HUO_SHAN_API_KEY": "other"}, clear=True), \
                mock.patch.object(A.urllib.request, "urlopen") as remote:
            with self.assertRaisesRegex(A.ArkError, "火山方舟 Agent 版本"):
                A.call("/images/generations", {"prompt": "offline"})
            remote.assert_not_called()
        with mock.patch.dict(A.os.environ, {}, clear=True):
            self.assertEqual(A.base_url(), "https://ark.cn-beijing.volces.com/api/plan/v3")
        for bad in ("http://ark.cn-beijing.volces.com/api/v3", "https://example.com/api/v3",
                    "https://ark.cn-beijing.volces.com/v3", "https://ark.cn-beijing.volces.com/api/v3",
                    "https://ark.cn-beijing.volces.com/api/plan/v3/other"):
            with mock.patch.dict(A.os.environ, {"ARK_BASE_URL": bad}, clear=True), self.assertRaises(A.ArkError):
                A.base_url()
        with mock.patch.dict(A.os.environ, {"ARK_BASE_URL": A.PLAN_BASE + "/"}, clear=True):
            self.assertEqual(A.base_url(), A.PLAN_BASE)

    def test_agent_plan_key_never_calls_text_models(self):
        with mock.patch.dict(A.os.environ, {"ARK_AGENT_PLAN_API_KEY": "plan"}, clear=True), \
                mock.patch.object(A.urllib.request, "urlopen") as remote:
            for path in ("/chat/completions", "/responses", "/embeddings"):
                with self.assertRaisesRegex(A.ArkError, "Agent Plan"):
                    A.call(path, {"model": "m"})
            remote.assert_not_called()

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
        key_patch = mock.patch.object(A, "api_key", return_value="offline-test-key")
        key_patch.start()
        self.addCleanup(key_patch.stop)

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

    def test_poll_budget_exits_and_resumes_same_task_without_post(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "waiting", "--shot", "SH-001",
                "--prompt", "动作", "--max-polls", "2", "--poll-interval", "0"]
        def processing(path, payload=None):
            self.calls.append((path, payload))
            return {"id": "cgt-waiting"} if payload else {"status": "processing"}
        with mock.patch.object(A, "call", side_effect=processing), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
        self.assertEqual(len(self.calls), 3)
        task = json.loads((self.project / "视频/waiting-任务.json").read_text())
        self.assertEqual((task["id"], task["polling"]["state"], task["polling"]["polls_total"]), ("cgt-waiting", "waiting", 2))
        self.assertNotIn("result", task)
        self.assertIsNone(task["record"]["selection"])
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual([path for path, _ in self.calls], ["/contents/generations/tasks/cgt-waiting"])

    def test_poll_deadline_is_per_run_and_invalid_limits_do_not_submit(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "deadline", "--shot", "SH-001", "--prompt", "动作"]
        def processing(path, payload=None):
            self.calls.append((path, payload))
            return {"id": "cgt-deadline"} if payload else {"status": "processing"}
        with mock.patch.object(A, "call", side_effect=processing), mock.patch.object(A.time, "monotonic", side_effect=[0, 0, .5, 1.2]), \
                mock.patch.object(A.time, "sleep") as sleep, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main([*argv, "--deadline-seconds", "1"]), 1)
            sleep.assert_called_once_with(.5)
        self.assertEqual(len(self.calls), 2)
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(len(self.calls), 1)
        for flag, value in (("--max-polls", "0"), ("--deadline-seconds", "0"), ("--poll-interval", "-1")):
            self.calls.clear()
            self.assertEqual(self.run_cli(*argv, "--name", "invalid-" + flag[2:], flag, value), 1)
            self.assertEqual(self.calls, [])

    def test_expired_input_transport_resumes_original_video_download(self):
        ref = self.project / "source.png"
        ref.write_bytes(PNG)
        digest = A.sha256(ref)
        origin = {digest: {"source_url": "https://tos/trusted-original", "source_url_expires_at": A.stamp(A.now() + datetime.timedelta(hours=1))}}
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "expired-input", "--shot", "SH-001",
                "--prompt", "动作", "--first-frame", str(ref)]
        with mock.patch.object(A, "originals", return_value=origin), mock.patch.object(A, "call", side_effect=self.fake_call), \
                mock.patch.object(A, "download", side_effect=A.ArkError("offline download interruption")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
        path = self.project / "视频/expired-input-任务.json"
        original = json.loads(path.read_text())
        origin[digest]["source_url_expires_at"] = A.stamp(A.now() - datetime.timedelta(hours=1))
        with mock.patch.object(A, "originals", return_value=origin), mock.patch.object(A, "call", side_effect=AssertionError("must not POST or GET")), \
                mock.patch.object(A, "download", side_effect=self.fake_download), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 0)
        resumed = json.loads(path.read_text())
        self.assertEqual(resumed["binding"], original["binding"])
        self.assertEqual(resumed["credential_sha256"], original["credential_sha256"])
        self.assertEqual(resumed["record"]["engine"]["payload_sha256"], original["binding"]["payload_sha256"])
        ref.write_bytes(PNG + b"changed")
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 1)
        self.assertEqual(self.calls, [])

    def test_expired_input_transport_resumes_original_image_download(self):
        ref = self.project / "source.png"
        ref.write_bytes(PNG)
        origin = {A.sha256(ref): {"source_url": "https://tos/original", "source_url_expires_at": A.stamp(A.now() + datetime.timedelta(hours=1))}}
        argv = ["image", "--project", str(self.project), "--out", "资产", "--name", "expired-input", "--purpose", "asset",
                "--prompt", "图像", "--ref", str(ref)]
        with mock.patch.object(A, "originals", return_value=origin), mock.patch.object(A, "call", side_effect=self.fake_call), \
                mock.patch.object(A, "download", side_effect=A.ArkError("offline interruption")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 1)
        with mock.patch.object(A, "originals", return_value={}), mock.patch.object(A, "call", side_effect=AssertionError("must not call")), \
                mock.patch.object(A, "download", side_effect=self.fake_download), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(argv), 0)

    def test_resume_rejects_a_different_credential_before_network(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "credential", "--shot", "SH-001", "--prompt", "动作"]
        self.assertEqual(self.run_cli(*argv), 0)
        self.calls.clear()
        with mock.patch.object(A, "api_key", return_value="another-offline-test-key"):
            self.assertEqual(self.run_cli(*argv), 1)
        self.assertEqual(self.calls, [])

    def test_multimodal_reference_metadata_and_audio_baseline_are_retained(self):
        image, video, audio = (self.project / name for name in ("identity.png", "action.mp4", "sound.wav"))
        image.write_bytes(PNG)
        video.write_bytes(b"synthetic action")
        audio.write_bytes(b"synthetic sound")
        bible = json.loads(BIBLE.read_text())
        bible["entities"][0]["references"] = [{"path": image.name, "sha256": A.sha256(image), "media_type": "image", "purpose": "identity"},
            {"path": video.name, "sha256": A.sha256(video), "media_type": "video", "purpose": "action"}]
        bible["entities"][1]["references"] = []
        bible["entities"][2]["sound"].update(path=audio.name, sha256=A.sha256(audio))
        bible_path = self.project / "bible.json"
        bible_path.write_text(json.dumps(bible))
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "multimodal", "--shot", "SH-002",
                "--prompt", "动作", "--bible", str(bible_path), "--state", str(STATE), "--ref-image", str(image),
                "--ref-video", str(video), "--ref-audio", str(audio)]
        self.assertEqual(self.run_cli(*argv), 0)
        record = json.loads((self.project / "视频/multimodal-生成记录.json").read_text())
        refs = record["inputs"]["references"]
        self.assertEqual([(r["media_type"], r["purpose"], r["entity_id"]) for r in refs],
                         [("image", "identity", "主角"), ("video", "action", "主角"), ("audio", "sound", "信封")])
        self.assertEqual(C.record_problems(record, bible, json.loads(STATE.read_text())), ([], []))
        self.assertEqual(self.run_cli(*argv, "--name", "silent", "--no-audio"), 0)
        silent = json.loads((self.project / "视频/silent-生成记录.json").read_text())
        self.assertIn("audio_anchors_sha256", silent["inputs"])  # 声音参考仍是声音消费者。

    def test_paid_post_uses_budget_reservation_once_but_resume_does_not(self):
        import vsc_budget
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "budget", "--shot", "SH-001", "--prompt", "动作",
                "--budget-reservation", "BR-offline-fixture"]
        with mock.patch.object(vsc_budget, "check_authorization") as check:
            self.assertEqual(self.run_cli(*argv), 0)
            self.assertEqual(check.call_count, 1)
            self.assertEqual(check.call_args.args, (str(self.project), "BR-offline-fixture", "video:视频/budget", {"remote_jobs": 1, "video_seconds": 5}))
            self.assertEqual(check.call_args.kwargs["request"]["prompt"], "动作")
        with mock.patch.object(vsc_budget, "check_authorization", side_effect=AssertionError("resume must not reserve again")):
            self.assertEqual(self.run_cli(*argv), 0)
        self.calls.clear()
        with mock.patch.object(vsc_budget, "check_authorization", side_effect=ValueError("invalid reservation")):
            self.assertEqual(self.run_cli(*argv, "--name", "budget-rejected"), 1)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.project / "视频/budget-rejected-任务.json").exists())

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
            raise A.ArkHTTPError(400, "HTTP 400: InputImageSensitiveContentDetected")
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

    def test_unknown_submission_never_posts_twice_and_is_possibly_billable(self):
        failures = [A.ArkError("network response lost"), A.ArkHTTPError(503, "service error"),
                    json.JSONDecodeError("invalid response", "x", 0), KeyboardInterrupt()]
        for kind in ("image", "video"):
            for number, failure in enumerate(failures):
                name = f"unknown-{kind}-{number}"
                argv = [kind, "--project", str(self.project), "--out", "unknown", "--name", name, "--prompt", "test"]
                argv += ["--purpose", "asset"] if kind == "image" else ["--shot", "SH-001"]
                def uncertain(path, payload=None):
                    task = json.loads((self.project / f"unknown/{name}-任务.json").read_text())
                    self.assertEqual(task["submission_state"], "intent")
                    self.assertTrue(task["record"]["budget"]["billable"])
                    raise failure
                with self.subTest(kind=kind, failure=type(failure).__name__), \
                        mock.patch.object(A, "call", side_effect=uncertain) as call, \
                        contextlib.redirect_stderr(io.StringIO()):
                    if isinstance(failure, KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            A.main(argv)
                    else:
                        self.assertEqual(A.main(argv), 1)
                    self.assertEqual(A.main(argv), 1)
                    self.assertEqual(call.call_count, 1)
                task = json.loads((self.project / f"unknown/{name}-任务.json").read_text())
                record = json.loads((self.project / f"unknown/{name}-生成记录.json").read_text())
                self.assertEqual(task["submission_state"], "unknown")
                self.assertTrue(record["budget"]["billable"])
                self.assertIn("未知", record["budget"]["usage"]["note"])
                self.assertEqual(C.record_errors(record), [])

    def test_explicit_http_rejection_never_posts_twice(self):
        for kind in ("image", "video"):
            argv = [kind, "--project", str(self.project), "--out", "reject", "--name", kind, "--prompt", "test"]
            argv += ["--purpose", "asset"] if kind == "image" else ["--shot", "SH-001"]
            with mock.patch.object(A, "call", side_effect=A.ArkHTTPError(400, "explicit rejected")) as call, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(A.main(argv), 1)
                self.assertEqual(A.main(argv), 1)
                self.assertEqual(call.call_count, 1)
            task = json.loads((self.project / f"reject/{kind}-任务.json").read_text())
            self.assertEqual(task["submission_state"], "rejected")
            self.assertFalse(task["record"]["budget"]["billable"])

    def test_missing_local_api_key_does_not_create_submission_evidence(self):
        for kind in ("image", "video"):
            argv = [kind, "--project", str(self.project), "--out", "no-key", "--name", kind, "--prompt", "test"]
            argv += ["--purpose", "asset"] if kind == "image" else ["--shot", "SH-001"]
            with mock.patch.object(A, "api_key", side_effect=A.ArkError("missing key")), \
                    mock.patch.object(A, "call") as call, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(A.main(argv), 1)
                self.assertEqual(A.main(argv), 1)
                call.assert_not_called()
            self.assertFalse((self.project / f"no-key/{kind}-任务.json").exists())
            self.assertFalse((self.project / f"no-key/{kind}-生成记录.json").exists())

    def test_direct_functions_keep_intent_after_process_interruption(self):
        from types import SimpleNamespace
        for kind in ("image", "video"):
            args = SimpleNamespace(project=str(self.project), out="direct", name=kind, prompt="test", prompt_file=None,
                                   bible=None, state=None, shot="SH-001", model=A.IMAGE_MODEL if kind == "image" else A.VIDEO_MODEL,
                                   purpose="asset", moment=None, ref=[], base_frame=None, base_use="edit", size="2K",
                                   first_frame=None, last_frame=None, first_frame_ref=None, ref_image=[], ref_video=[], ref_audio=[],
                                   duration=5, ratio="adaptive", resolution="480p", no_audio=True, draft=False, dry_run=False)
            generate = A.generate_image if kind == "image" else A.generate_video
            with mock.patch.object(A, "call", side_effect=KeyboardInterrupt()) as call:
                with self.assertRaises(KeyboardInterrupt):
                    generate(args)
                with self.assertRaises(A.ArkError):
                    generate(args)
                self.assertEqual(call.call_count, 1)

    def test_call_http_classification_and_post_never_retries(self):
        error = A.urllib.error.HTTPError("https://fake", 403, "denied", {}, io.BytesIO(b"offline-test-key rejected"))
        with mock.patch.object(A.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(A.ArkHTTPError) as caught:
                A.call("/images/generations", {"prompt": "test"})
        self.assertEqual(caught.exception.status_code, 403)
        self.assertNotIn("offline-test-key", str(caught.exception))
        self.assertIn("没有方舟图像／视频接口的权限，请自行核对", str(caught.exception))
        busy = A.urllib.error.HTTPError("https://fake", 503, "busy", {}, io.BytesIO(b"busy"))
        with mock.patch.object(A.urllib.request, "urlopen", side_effect=busy):
            with self.assertRaises(A.ArkHTTPError) as caught:
                A.call("/images/generations", {"prompt": "test"})
        self.assertTrue(str(caught.exception).startswith("HTTP 503:"))
        self.assertNotIn("权限", str(caught.exception))
        with mock.patch.object(A.urllib.request, "urlopen", side_effect=TimeoutError("response lost")) as urlopen:
            with self.assertRaises(A.ArkError):
                A.call("/images/generations", {"prompt": "test"}, attempts=3)
            self.assertEqual(urlopen.call_count, 1)


class VisualTest(unittest.TestCase):
    def setUp(self):
        key = mock.patch.object(A, "api_key", return_value="offline-test-key")
        key.start()
        self.addCleanup(key.stop)
        allowed = mock.patch.object(A.credentials, "text_model_problem", return_value=None)
        allowed.start()
        self.addCleanup(allowed.stop)

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
            variants = [good[:-1], good + [{"item": "不相关条目", "verdict": "pass", "evidence": "有"}],
                        [good[0]] * len(good), [{**item, "evidence": ""} for item in good]]
            for index, results in enumerate(variants):
                media = project / f"a{index}.png"
                media.write_bytes(PNG)
                argv = ["inspect", "--project", str(project), "--media", str(media), "--bible", str(BIBLE), "--entity", entity]
                response = {"choices": [{"message": {"content": json.dumps({"results": results})}}]}
                with mock.patch.object(A, "call", return_value=response), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(A.main(argv), 1)
                self.assertFalse(media.with_name(f"a{index}-视觉检查.json").exists())


class InspectionBudgetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.bible = self.project / "bible.json"
        self.bible.write_bytes(BIBLE.read_bytes())
        self.state = self.project / "state.json"
        self.state.write_bytes(STATE.read_bytes())
        self.pid = json.loads(self.bible.read_text("utf-8"))["project_id"]
        self.entity = json.loads(self.bible.read_text("utf-8"))["entities"][0]["id"]
        (self.project / "vsc.json").write_text(json.dumps({"project_id": self.pid}), "utf-8")
        self.media = self.project / "a.png"
        self.media.write_bytes(PNG)
        key = mock.patch.object(A, "api_key", return_value="offline-test-key")
        key.start()
        self.addCleanup(key.stop)
        allowed = mock.patch.object(A.credentials, "text_model_problem", return_value=None)
        self.text_models = allowed.start()
        self.addCleanup(allowed.stop)

    def args(self, *extra):
        return A.parser().parse_args(["inspect", "--project", str(self.project), "--bible", "bible.json",
                                     "--media", "a.png", "--entity", self.entity, *extra])

    def response(self, args):
        items = A.prepare_inspection(args)[1]
        return {"choices": [{"message": {"content": json.dumps({"results": [
            {"item": item, "verdict": "pass", "evidence": "可见对应特征"} for item in items],
            "people": 1, "issues": []})}}], "usage": {"total_tokens": 123}}

    def attempt(self):
        return json.loads(next(self.project.glob("*-视觉检查-*-尝试.json")).read_text("utf-8"))

    def test_prepare_is_pure_and_binds_exact_local_inputs(self):
        args = self.args("--state", "state.json", "--check", "手指数量", "--budget-reservation", "BR-test")
        before = {p.name: p.read_bytes() for p in self.project.iterdir()}
        with mock.patch.object(A, "api_key", side_effect=AssertionError("must not read key")), \
                mock.patch.object(A, "call", side_effect=AssertionError("must not call provider")), \
                mock.patch.object(A, "write_json", side_effect=AssertionError("must not write")), \
                mock.patch.object(A.subprocess, "run", side_effect=AssertionError("must not extract frames")):
            binding, items, pack, media = A.prepare_inspection(args)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.project.iterdir()})
        self.assertEqual(media, self.media.resolve())
        self.assertIsNone(pack)
        self.assertEqual(binding["checklist"], items)
        self.assertEqual(binding["project_id"], self.pid)
        self.assertEqual(binding["model"], A.VISION_MODEL)
        self.assertEqual(binding["kind"], "inspect")
        self.assertNotIn("budget_reservation", binding)
        self.assertEqual(binding["inputs"], {"bible": {"path": "bible.json", "sha256": A.sha256(self.bible)},
                                             "state": {"path": "state.json", "sha256": A.sha256(self.state)},
                                             "media": {"path": "a.png", "sha256": A.sha256(self.media)}})
        original = A.digest_json(binding)
        for flag, value in (("--check", "新的检查项"), ("--model", "another-model")):
            self.assertNotEqual(original, A.digest_json(A.prepare_inspection(self.args("--state", "state.json", flag, value))[0]))
        for path in (self.bible, self.state, self.media):
            previous = path.read_bytes()
            path.write_bytes(previous + b" ")
            self.assertNotEqual(original, A.digest_json(A.prepare_inspection(args)[0]))
            path.write_bytes(previous)
        shot = A.parser().parse_args(["inspect", "--project", str(self.project), "--bible", "bible.json", "--state", "state.json",
                                      "--media", "a.png", "--shot", "SH-001", "--moment", "entry"])
        shot_binding, _, pack, _ = A.prepare_inspection(shot)
        self.assertEqual(shot_binding["inputs"]["anchors_sha256"], C.pack_sha256(pack))
        self.assertEqual(shot_binding["shot_id"], "SH-001")
        self.assertEqual(shot_binding["moment"], "entry")

    def test_invalid_preflight_never_reads_credentials_or_submits(self):
        cases = [("--entity", "missing"), ("--model", "bad model"), ("--check", " "), ("--moment", "entry")]
        with mock.patch.object(A, "api_key") as key, mock.patch.object(A, "call") as remote:
            for flags in cases:
                with self.subTest(flags=flags), self.assertRaises(A.ArkError):
                    A.inspect(self.args(*flags))
            key.assert_not_called()
            remote.assert_not_called()
        self.assertFalse(list(self.project.glob("*-尝试.json")))

    def test_agent_plan_policy_refuses_new_submission_before_key_budget_or_attempt(self):
        import vsc_budget
        self.text_models.return_value = A.credentials.TEXT_MODELS_FORBIDDEN
        with mock.patch.object(A, "api_key") as key, mock.patch.object(A, "call") as remote, \
                mock.patch.object(vsc_budget, "check_authorization") as budget:
            with self.assertRaisesRegex(A.ArkError, "Agent Plan"):
                A.inspect(self.args("--budget-reservation", "BR-plan"))
            key.assert_not_called()
            remote.assert_not_called()
            budget.assert_not_called()
        self.assertFalse(list(self.project.glob("*-尝试.json")))

    def test_strict_inspection_without_budget_cannot_post(self):
        (self.project / "vsc.json").write_text(json.dumps({"project_id": self.pid,
            "profile_snapshot": {"contract_policy": "production-v2"}}), "utf-8")
        with mock.patch.object(A, "call") as remote, self.assertRaisesRegex(A.ArkError, "预算授权无效"):
            A.inspect(self.args())
        remote.assert_not_called()
        self.assertFalse(list(self.project.glob("*-尝试.json")))

    def test_budget_receives_binding_and_valid_report_is_read_only_reused(self):
        import vsc_budget
        args = self.args("--budget-reservation", "BR-test")
        binding = A.prepare_inspection(args)[0]
        with mock.patch.object(vsc_budget, "check_authorization") as budget, \
                mock.patch.object(A, "call", return_value=self.response(args)) as remote:
            target = A.inspect(args)
        budget.assert_called_once_with(str(self.project), "BR-test", "inspect:a.png", {"remote_jobs": 1, "vision_jobs": 1}, request=binding)
        remote.assert_called_once()
        report = json.loads(target.read_text("utf-8"))
        self.assertEqual(report["binding"], binding)
        self.assertEqual(report["binding_sha256"], A.digest_json(binding))
        self.assertEqual(report["budget_reservation"], "BR-test")
        self.assertIs(report["advisory"], True)
        self.assertNotIn("selection", report)
        self.assertEqual(self.attempt()["submission_state"], "responded")
        self.assertNotIn("offline-test-key", next(self.project.glob("*-尝试.json")).read_text("utf-8"))
        before = {p.name: p.read_bytes() for p in self.project.iterdir() if p.is_file()}
        with mock.patch.object(vsc_budget, "check_authorization", side_effect=AssertionError("must not charge")), \
                mock.patch.object(A, "api_key", side_effect=AssertionError("must not need key")), \
                mock.patch.object(A, "call", side_effect=AssertionError("must not POST")):
            self.assertEqual(A.inspect(self.args("--budget-reservation", "BR-later")), target)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.project.iterdir() if p.is_file()})
        # A crash after writing the valid report but before recording its digest is also free to resume.
        attempt_path = next(self.project.glob("*-尝试.json"))
        attempt = self.attempt()
        attempt.pop("report_sha256")
        A.write_json(attempt_path, attempt)
        with mock.patch.object(A, "call", side_effect=AssertionError("must not POST")):
            self.assertEqual(A.inspect(args), target)

    def test_old_report_preserved_and_binding_change_writes_new_report(self):
        args = self.args()
        with mock.patch.object(A, "call", return_value=self.response(args)):
            first = A.inspect(args)
        original = first.read_bytes()
        changed = self.args("--check", "新的要求")
        with mock.patch.object(A, "call", return_value=self.response(changed)) as remote:
            second = A.inspect(changed)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(json.loads(second.read_text("utf-8"))["checklist"], A.prepare_inspection(changed)[1])
        remote.assert_called_once()
        with mock.patch.object(A, "call", side_effect=AssertionError("must not POST")):
            self.assertEqual(A.inspect(changed), second)

    def test_unknown_submit_persists_evidence_and_cannot_repost_same_reservation(self):
        import vsc_budget
        for index, failure in enumerate((A.ArkError("response lost offline-test-key"), KeyboardInterrupt())):
            media = self.project / f"unknown{index}.png"
            media.write_bytes(PNG)
            args = self.args("--media", media.name, "--budget-reservation", f"BR-{index}")
            with mock.patch.object(vsc_budget, "check_authorization"), mock.patch.object(A, "call", side_effect=failure):
                with self.assertRaises(type(failure)):
                    A.inspect(args)
            saved = next(self.project.glob(f"unknown{index}-*-尝试.json"))
            evidence = json.loads(saved.read_text("utf-8"))
            self.assertEqual(evidence["submission_state"], "unknown")
            self.assertEqual(evidence["budget_reservation"], f"BR-{index}")
            self.assertNotIn("offline-test-key", saved.read_text("utf-8"))
            with mock.patch.object(vsc_budget, "check_authorization") as budget, mock.patch.object(A, "call") as remote:
                with self.assertRaisesRegex(A.ArkError, "不能自动重提"):
                    A.inspect(args)
                with self.assertRaisesRegex(A.ArkError, "不能重复提交"):
                    A.inspect(self.args("--media", media.name, "--budget-reservation", f"BR-{index}", "--check", "改变输入"))
                budget.assert_not_called()
                remote.assert_not_called()

    def test_malformed_response_retained_and_retry_only_parses_locally(self):
        args = self.args()
        with mock.patch.object(A, "call", return_value={"choices": []}) as remote:
            with self.assertRaises(A.ArkError):
                A.inspect(args)
        remote.assert_called_once()
        self.assertEqual(self.attempt()["submission_state"], "responded")
        with mock.patch.object(A, "call") as remote, mock.patch.object(A, "api_key") as key:
            with self.assertRaises(A.ArkError):
                A.inspect(args)
            remote.assert_not_called()
            key.assert_not_called()

    def test_paid_response_survives_input_drift_without_rebilling(self):
        args = self.args()
        original = self.bible.read_bytes()
        response = self.response(args)
        def drift(*unused, **kwargs):
            self.bible.write_bytes(original + b" ")
            return response
        with mock.patch.object(A, "call", side_effect=drift):
            with self.assertRaisesRegex(A.ArkError, "检查期间输入已改变"):
                A.inspect(args)
        self.assertEqual(self.attempt()["response"], response)
        self.assertFalse((self.project / "a-视觉检查.json").exists())
        self.bible.write_bytes(original)
        with mock.patch.object(A, "call", side_effect=AssertionError("must not POST")):
            self.assertTrue(A.inspect(args).exists())

    def test_tampered_report_refuses_overwrite_and_never_rebills(self):
        args = self.args()
        with mock.patch.object(A, "call", return_value=self.response(args)):
            target = A.inspect(args)
        report = json.loads(target.read_text("utf-8"))
        report["results"][0]["verdict"] = "fail"
        A.write_json(target, report)
        with mock.patch.object(A, "call") as remote, self.assertRaisesRegex(A.ArkError, "拒绝重新付费或覆盖"):
            A.inspect(args)
        remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
