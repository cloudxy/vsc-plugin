#!/usr/bin/env python3
"""scripts/providers/xai/grok.py 自测：不联网，用假的接口与下载模拟 xAI Grok。运行：python3 -B tests/run.py --test production.integration.test_grok_cli"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.paths import ROOT
import vsc.story.consistency as C
import vsc.adapters.providers.xai_grok.api as A
import vsc.adapters.providers.xai_grok.credentials as grok_credentials

BIBLE = ROOT / "templates/asset-bible.json"
STATE = ROOT / "templates/scene-state.json"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class InputTest(unittest.TestCase):
    def test_missing_login_points_to_grok_cli_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(grok_credentials, "LOGIN_FILE", Path(temp) / "auth.json"), \
                    mock.patch.object(A.urllib.request, "urlopen") as remote:
                with self.assertRaisesRegex(A.GrokError, "grok.*auth.json") as error:
                    A.call("/images/generations", {"prompt": "offline"})
                self.assertIn("登录", str(error.exception))
                remote.assert_not_called()

    def test_base_url_is_pinned_to_the_official_plane(self):
        with mock.patch.dict(A.os.environ, {}, clear=True):
            self.assertEqual(A.base_url(), "https://api.x.ai/v1")
        for bad in ("http://api.x.ai/v1", "https://api.x.ai/v1/other", "https://example.com/v1"):
            with mock.patch.dict(A.os.environ, {"GROK_BASE_URL": bad}, clear=True), self.assertRaises(A.GrokError):
                A.base_url()
        with mock.patch.dict(A.os.environ, {"GROK_BASE_URL": "https://api.x.ai/v1/"}, clear=True):
            self.assertEqual(A.base_url(), "https://api.x.ai/v1")

    def test_resolve_builds_data_uri_only_for_local_images(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            image = project / "首帧.png"
            image.write_bytes(PNG)
            url, item = A.resolve(str(image), project)
            self.assertTrue(url.startswith("data:image/png;base64,"))
            self.assertEqual(item, {"path": "首帧.png", "sha256": A.sha256(image)})
            self.assertEqual(A.resolve("https://example.com/a.png", project), ("https://example.com/a.png", None))
            with self.assertRaises(A.GrokError):
                A.resolve("asset://asset-1", project)
            (project / "note.txt").write_text("text", "utf-8")
            with self.assertRaises(A.GrokError):
                A.resolve(str(project / "note.txt"), project)


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "vsc.json").write_text(json.dumps({"project_id": json.loads(BIBLE.read_text("utf-8"))["project_id"]}), "utf-8")
        self.frame = self.project / "first.png"
        self.frame.write_bytes(PNG)
        self.calls = []
        key_patch = mock.patch.object(A, "api_key", return_value="offline-test-key")
        key_patch.start()
        self.addCleanup(key_patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def fake_call(self, path, payload=None, attempts=None):
        self.calls.append((path, payload))
        if path == "/images/generations":
            return {"data": [{"url": "https://example.invalid/out.png"}], "usage": {"generated_images": 1}}
        if path == "/videos/generations":
            return {"request_id": "grok-req-1"}
        return {"status": "done", "video": {"url": "https://example.invalid/v.mp4", "duration": 6}, "usage": {"video_seconds": 6}}

    @staticmethod
    def fake_download(url, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG if url.endswith(".png") else b"\x00\x00\x00\x18ftypmp4" + b"0" * 8)

    def run_cli(self, *argv):
        with mock.patch.object(A, "call", self.fake_call), mock.patch.object(A, "download", self.fake_download), \
                mock.patch.object(A.time, "sleep", lambda _: None), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return A.main(list(argv))

    def test_asset_image_records_provider_and_sniffed_suffix(self):
        self.assertEqual(self.run_cli("image", "--project", str(self.project), "--out", "资产", "--name", "主角-定妆",
                                      "--purpose", "asset", "--prompt", "主角定妆照"), 0)
        record = json.loads((self.project / "资产/主角-定妆-生成记录.json").read_text("utf-8"))
        self.assertEqual(C.record_errors(record), [])
        self.assertEqual(record["engine"]["provider"], "xai_grok")
        self.assertEqual(record["engine"]["params"], {"aspect_ratio": "9:16", "resolution": "2k", "n": 1})
        self.assertEqual(record["outputs"][0]["path"], "资产/主角-定妆.png")
        self.assertTrue(record["outputs"][0]["source_url"].startswith("https://example.invalid/"))
        payload = self.calls[0][1]
        self.assertEqual((payload["aspect_ratio"], payload["resolution"], payload["model"]), ("9:16", "2k", "grok-imagine-image-2.0"))

    def test_candidate_image_requires_anchor_inputs(self):
        self.assertEqual(self.run_cli("image", "--project", str(self.project), "--out", "资产", "--name", "bad",
                                      "--purpose", "candidate", "--prompt", "关键帧"), 1)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.project / "资产/bad-生成记录.json").exists())

    def test_video_dry_run_needs_no_login_or_network(self):
        with mock.patch.object(A, "call", side_effect=AssertionError("no network")), \
                mock.patch.object(A, "api_key", side_effect=AssertionError("no key needed")), \
                contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(A.main(["video", "--project", str(self.project), "--out", "视频", "--name", "dry",
                                     "--shot", "SH-001", "--prompt", "动作", "--first-frame", str(self.frame),
                                     "--dry-run"]), 0)
        shown = json.loads(captured.getvalue())
        url = shown["payload"]["image"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertTrue(url.endswith("…"))
        self.assertEqual(len(url), 41)
        self.assertEqual(shown["payload"]["duration"], 6)
        self.assertNotIn("aspect_ratio", shown["payload"])
        self.assertEqual(self.calls, [])

    def test_video_submission_poll_and_completed_rerun_never_reposts(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "SH-001-T1", "--shot", "SH-001",
                "--prompt", "动作", "--first-frame", str(self.frame)]
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual([path for path, _ in self.calls], ["/videos/generations", "/videos/grok-req-1"])
        record = json.loads((self.project / "视频/SH-001-T1-生成记录.json").read_text("utf-8"))
        self.assertEqual(C.record_errors(record), [])
        self.assertEqual(record["engine"]["task_id"], "grok-req-1")
        self.assertEqual(record["engine"]["params"]["actual"], {"duration": 6})
        self.assertEqual(record["outputs"][0]["duration_ms"], 6000)
        self.assertTrue(self.calls[0][1]["image"]["url"].startswith("data:image/png;base64,"))
        task = json.loads((self.project / "视频/SH-001-T1-任务.json").read_text("utf-8"))
        self.assertEqual(task["format"], "vsc.grok-task/v1")
        # 重跑同一命令只核对已完成的本地产物；不再查询或提交。
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual(self.calls, [])

    def test_poll_budget_exits_keep_task_resumable(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "waiting", "--shot", "SH-001",
                "--prompt", "动作", "--first-frame", str(self.frame), "--max-polls", "2", "--poll-interval", "0"]

        def processing(path, payload=None):
            self.calls.append((path, payload))
            return {"request_id": "grok-waiting"} if payload else {"status": "pending"}

        with mock.patch.object(A, "call", side_effect=processing), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(list(argv)), 1)
        task = json.loads((self.project / "视频/waiting-任务.json").read_text("utf-8"))
        self.assertEqual((task["id"], task["polling"]["state"]), ("grok-waiting", "waiting"))
        self.assertNotIn("result", task)
        self.calls.clear()
        self.assertEqual(self.run_cli(*argv), 0)
        self.assertEqual([path for path, _ in self.calls], ["/videos/grok-waiting"])

    def test_remote_failure_is_recorded_and_never_resubmitted(self):
        argv = ["video", "--project", str(self.project), "--out", "视频", "--name", "failing", "--shot", "SH-001",
                "--prompt", "动作", "--first-frame", str(self.frame)]

        def failing(path, payload=None):
            self.calls.append((path, payload))
            return {"request_id": "grok-failed"} if payload else {"status": "failed", "error": {"code": "internal_error"}}

        with mock.patch.object(A, "call", side_effect=failing), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(list(argv)), 1)
        record = json.loads((self.project / "视频/failing-生成记录.json").read_text("utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertIn("internal_error", record["errors"][0]["error"])
        self.calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(list(argv)), 1)  # 终态失败不自动重提
        self.assertEqual(self.calls, [])

    def test_changed_inputs_cannot_reuse_the_same_task_name(self):
        common = ["video", "--project", str(self.project), "--out", "视频", "--name", "SH-001-T1", "--shot", "SH-001",
                  "--prompt", "动作", "--first-frame", str(self.frame)]
        self.assertEqual(self.run_cli(*common), 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main([*common, "--prompt", "另一个动作"]), 1)
        record = json.loads((self.project / "视频/SH-001-T1-生成记录.json").read_text("utf-8"))
        self.assertEqual(record["inputs"]["prompt"], "动作")

    def test_video_requires_first_frame_and_bounds(self):
        base = ["video", "--project", str(self.project), "--out", "视频", "--name", "bounds", "--shot", "SH-001", "--prompt", "动作"]
        for extra in ([], ["--first-frame", str(self.frame), "--duration", "16"],
                      ["--first-frame", str(self.frame), "--resolution", "4k"]):
            self.assertEqual(self.run_cli(*base, *extra), 1)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
