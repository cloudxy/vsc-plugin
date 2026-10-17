"""Seed-Audio MediaKit 协议与恢复测试，全程替代网络。"""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import wave

import vsc.story.consistency as consistency
import vsc.adapters.providers.speech.audio as audio

TASK_ID = "amk-tool-call-maas-proxy-test-1"


def completed(data=b"offline-mp3"):
    return {"success": True, "task_id": TASK_ID, "status": "completed", "result": {
        "api": "doubao.audio_generation", "duration": 9.5,
        "maas_result": {"audio": base64.b64encode(data).decode(), "usage": {"generated_seconds": 9.5}}}}


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "作品"
        self.project.mkdir()
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "audio-test"}), "utf-8")
        self.key = "private-mediakit-test-key"
        patch = mock.patch.dict(os.environ, {audio.credentials.KEY_ENV: self.key}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(audio, "call", side_effect=AssertionError("unexpected network attempt"))
        self.remote = patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(audio.shutil, "which", return_value="/offline/tool")
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(audio, "probe_audio", return_value={"duration_ms": 9500, "sample_rate": 48000,
            "codec": "mp3", "container": "mp3", "channels": 1})
        self.probe = patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(audio.time, "sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def args(self, *extra):
        return audio.parser().parse_args(["generate", "--project", str(self.project), "--name", "BGM-01",
            "--prompt", "雨夜，克制的钢琴，约十秒，无对白。", "--max-chars", "100", "--max-polls", "2", *extra])

    def task(self):
        return json.loads((self.project / "06-素材/声音/BGM-01-任务.json").read_text("utf-8"))

    def record(self):
        return json.loads((self.project / "06-素材/声音/BGM-01-生成记录.json").read_text("utf-8"))

    def replies(self, *responses):
        self.remote.side_effect = list(responses)

    def test_dry_run_protocol_and_no_key_or_writes(self):
        os.environ.clear()
        request = audio.generate(self.args("--dry-run"))
        self.assertTrue(request["dry_run"])
        self.assertFalse(request["billable"])
        payload = request["binding"]["payload"]
        self.assertEqual(payload["api"], "doubao.audio_generation")
        self.assertEqual(payload["maas_params"]["model"], "seed-audio-1.0")
        self.assertEqual(payload["maas_params"]["audio_config"], {
            "format": "mp3", "sample_rate": 48000, "pitch_rate": 0, "speech_rate": 0, "loudness_rate": 0})
        self.assertNotIn("duration", payload["maas_params"])
        self.assertFalse((self.project / "06-素材").exists())
        self.remote.assert_not_called()
        self.probe.assert_not_called()

    def test_missing_key_asks_for_agent_plan_key_and_explicit_names_still_work(self):
        os.environ.clear()
        os.environ["DOUBAO_MEDIAKIT_API_KEY"] = "other-mediakit-key"
        self.assertTrue(audio.generate(self.args())["dry_run"])
        with self.assertRaisesRegex(audio.AudioError, "火山方舟 Agent 版本") as error:
            audio.generate(self.args("--execute"))
        self.assertIn(audio.credentials.KEY_ENV, str(error.exception))
        self.assertIn("source ~/.zshenv", str(error.exception))
        self.remote.assert_not_called()
        self.assertFalse((self.project / "06-素材/声音/BGM-01-任务.json").exists())
        os.environ["TEAM_AUDIO_KEY"] = "explicit-key"
        self.replies({"success": True, "task_id": TASK_ID}, completed())
        audio.generate(self.args("--execute", "--key-env", "TEAM_AUDIO_KEY"))
        self.assertEqual(self.remote.call_args_list[0].args[1], "explicit-key")
        with self.assertRaisesRegex(audio.AudioError, "环境变量名"):
            audio.generate(self.args("--key-env", "actual secret literal"))

    def test_success_persists_id_result_usage_and_idempotently_returns_without_key(self):
        self.replies({"success": True, "task_id": TASK_ID, "request_id": "provider-request-id"}, completed())
        record = audio.generate(self.args("--execute"))
        self.assertEqual(consistency.record_errors(record), [])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["purpose"], "asset")
        self.assertEqual(record["engine"]["task_id"], TASK_ID)
        self.assertEqual(record["engine"]["reported_duration_s"], 9.5)
        self.assertEqual(record["budget"]["usage"], {"maas": {"generated_seconds": 9.5}})
        self.assertNotIn("actual", record["budget"])
        self.assertNotIn("estimated", record["budget"])
        self.assertEqual((self.project / record["outputs"][0]["path"]).read_bytes(), b"offline-mp3")
        self.assertEqual(len(record["engine"]["responses"]), 2)
        self.assertEqual(self.remote.call_args_list[0].args[0], audio.SUBMIT)
        self.assertEqual(self.remote.call_args_list[1].args[0], "/api/v1/tasks/" + TASK_ID)
        self.assertEqual(self.task()["status"], "succeeded")
        os.environ.clear()
        self.assertEqual(audio.generate(self.args("--execute")), record)
        self.assertEqual(self.remote.call_count, 2)
        for path in (self.project / "06-素材/声音").glob("*.json"):
            self.assertNotIn(self.key, path.read_text())

    def test_poll_limit_and_network_failure_resume_get_without_new_post(self):
        pending = {"success": True, "task_id": TASK_ID, "status": "running"}
        self.replies({"success": True, "task_id": TASK_ID}, pending, pending)
        with self.assertRaisesRegex(audio.AudioError, "max-polls"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.task()["task_id"], TASK_ID)
        self.assertEqual(self.task()["polls"], 2)
        self.replies(urllib.error.URLError("offline disconnect"))
        with self.assertRaises(audio.AudioError):
            audio.generate(self.args("--execute"))
        self.replies(completed())
        self.assertEqual(audio.generate(self.args("--execute"))["status"], "succeeded")
        calls = self.remote.call_args_list
        self.assertEqual(sum(call.args[0] == audio.SUBMIT for call in calls), 1)
        self.assertEqual(self.task()["polls"], 4)

    def test_uncertain_submission_is_never_automatically_repeated(self):
        def uncertain(path, key, payload=None):
            self.assertEqual(self.task()["status"], "submitted")
            self.assertEqual(self.task()["binding"]["payload"], payload)
            raise audio.AudioError("connection lost after send")
        self.remote.side_effect = uncertain
        with self.assertRaises(audio.AudioError):
            audio.generate(self.args("--execute"))
        with self.assertRaisesRegex(audio.AudioError, "禁止自动重新提交"):
            audio.generate(self.args("--execute"))
        self.remote.assert_called_once()
        self.assertTrue(self.record()["budget"]["billable"])

    def test_missing_invalid_task_id_and_remote_failure_are_not_new_jobs(self):
        self.replies({"success": True, "task_id": "../../escape"})
        with self.assertRaisesRegex(audio.AudioError, "task_id"):
            audio.generate(self.args("--execute"))
        with self.assertRaises(audio.AudioError):
            audio.generate(self.args("--execute"))
        self.remote.assert_called_once()

    def test_remote_failure_preserves_usage_and_error_redacts_key(self):
        self.replies({"success": True, "task_id": TASK_ID}, {"success": True, "task_id": TASK_ID,
            "status": "failed", "message": "denied " + self.key, "usage": {"requests": 1}})
        with self.assertRaisesRegex(audio.AudioError, "远程音频生成失败"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.task()["status"], "remote_failed")
        self.assertEqual(self.record()["budget"]["usage"], {"mediakit": {"requests": 1}})
        with self.assertRaisesRegex(audio.AudioError, "远程任务已失败"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.remote.call_count, 2)

    def test_cached_completion_recovers_local_media_failure_without_network_or_key(self):
        self.replies({"success": True, "task_id": TASK_ID}, completed())
        self.probe.side_effect = audio.AudioError("media decode failed")
        with self.assertRaisesRegex(audio.AudioError, "media decode"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.task()["status"], "completed")
        self.assertFalse((self.project / "06-素材/声音/BGM-01.mp3").exists())
        os.environ.clear()
        self.probe.side_effect = None
        record = audio.generate(self.args("--execute"))
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(self.remote.call_count, 2)

    def test_bad_base64_empty_audio_task_mismatch_and_bad_api_cannot_succeed(self):
        fixtures = []
        bad = completed()
        bad["result"]["maas_result"]["audio"] = "***"
        fixtures.append(bad)
        fixtures.append(completed(b""))
        bad = completed()
        bad["task_id"] = "different-task"
        fixtures.append(bad)
        bad = completed()
        bad["result"]["api"] = "other.api"
        fixtures.append(bad)
        for index, result in enumerate(fixtures):
            with self.subTest(index=index):
                self.replies({"success": True, "task_id": TASK_ID}, result)
                with self.assertRaises(audio.AudioError):
                    audio.generate(self.args("--execute", "--name", f"BAD-{index}"))
                self.assertFalse((self.project / f"06-素材/声音/BAD-{index}.mp3").exists())

    def test_input_drift_and_changed_success_output_refuse_network(self):
        self.replies({"success": True, "task_id": TASK_ID}, completed())
        record = audio.generate(self.args("--execute"))
        for options in (("--prompt", "另一段"), ("--max-chars", "101"), ("--asset-kind", "sfx")):
            with self.subTest(options=options), self.assertRaisesRegex(audio.AudioError, "请求或预算已改变"):
                audio.generate(self.args("--execute", *options))
        (self.project / record["outputs"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(audio.AudioError, "SHA-256"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.remote.call_count, 2)

    def test_path_budget_and_poll_bounds_rejected_before_network(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.project / "escape").symlink_to(outside, target_is_directory=True)
        for options in (("--out", "../outside"), ("--out", str(outside)), ("--out", "escape/audio"),
                        ("--name", "../bad"), ("--name", "."), ("--max-chars", "1"),
                        ("--max-polls", "0"), ("--poll-interval", "nan"), ("--poll-interval", "61")):
            with self.subTest(options=options), self.assertRaises(audio.SpeechError):
                audio.generate(self.args("--execute", *options))
        self.remote.assert_not_called()

    def test_concurrent_same_name_cannot_submit(self):
        out = self.project / "06-素材/声音"
        out.mkdir(parents=True)
        with audio.generation_lock(out / ".BGM-01-生成.lock"):
            with self.assertRaisesRegex(audio.SpeechError, "正在运行"):
                audio.generate(self.args("--execute"))
        self.remote.assert_not_called()

    def test_saved_submission_response_recovers_task_id_after_crash(self):
        self.replies({"success": True, "task_id": TASK_ID}, completed())
        original = audio.valid_task_id
        with mock.patch.object(audio, "valid_task_id", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                audio.generate(self.args("--execute"))
        self.assertEqual(self.task()["status"], "submitted")
        self.assertNotIn("task_id", self.task())
        self.assertTrue(callable(original))
        self.replies(completed())
        self.assertEqual(audio.generate(self.args("--execute"))["status"], "succeeded")
        self.assertEqual(sum(call.args[0] == audio.SUBMIT for call in self.remote.call_args_list), 1)

    def test_http_transport_uses_bearer_and_single_bounded_request(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"success":true,"task_id":"task-1"}'
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            ORIGINAL_CALL(audio.SUBMIT, self.key, {"api": "doubao.audio_generation"})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, audio.BASE + audio.SUBMIT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer " + self.key)
        response.__enter__.return_value.read.assert_called_once_with(audio.MAX_RESPONSE_BYTES + 1)
        opener.open.assert_called_once()

    def test_http_permission_denial_asks_user_to_check_key_without_retry(self):
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(audio.BASE + audio.SUBMIT, 401, "denied", {}, io.BytesIO())
        with mock.patch.object(urllib.request, "build_opener", return_value=opener), \
                self.assertRaisesRegex(audio.AudioError, "没有Seed-Audio（MediaKit）的权限，请自行核对"):
            ORIGINAL_CALL(audio.SUBMIT, self.key, {"api": "doubao.audio_generation"})
        opener.open.assert_called_once()

    def test_resume_refuses_mutated_original_record_and_bad_response_snapshot(self):
        self.replies({"success": True, "task_id": TASK_ID}, completed())
        record = audio.generate(self.args("--execute"))
        task_path = self.project / "06-素材/声音/BGM-01-任务.json"
        task = self.task()
        original = json.loads(json.dumps(task))
        task["record"]["inputs"]["prompt"] = "forged prompt"
        task_path.write_text(json.dumps(task), "utf-8")
        with self.assertRaisesRegex(audio.AudioError, "绑定不一致"):
            audio.generate(self.args("--execute"))
        task_path.write_text(json.dumps(original), "utf-8")
        snapshot = self.project / record["engine"]["responses"][-1]["path"]
        snapshot.write_text("{}", "utf-8")
        with self.assertRaisesRegex(audio.AudioError, "SHA-256"):
            audio.generate(self.args("--execute"))
        self.assertEqual(self.remote.call_count, 2)


ORIGINAL_CALL = audio.call


@unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "真实媒体验证需要ffprobe/ffmpeg")
class ActualAudioTests(unittest.TestCase):
    def test_generated_mp3_really_probes_and_decodes(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / "source.wav"
            with wave.open(str(wav), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(b"\0\0" * 4800)
            mp3 = Path(folder) / "sound.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(mp3)], check=True, capture_output=True)
            self.assertEqual(audio.probe_audio(mp3, "mp3", 48000)["sample_rate"], 48000)
            mp3.write_bytes(b"garbage")
            with self.assertRaises(audio.SpeechError):
                audio.probe_audio(mp3, "mp3", 48000)


if __name__ == "__main__":
    unittest.main()
