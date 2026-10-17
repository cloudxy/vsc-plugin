"""豆包语音离线协议、计费续接与真实媒体检查；绝不连接供应商。"""
import base64
import http.client
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
import vsc.adapters.providers.speech.tts as speech


def wav_bytes():
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    return result.getvalue()


def frame(code=0, data=None, **fields):
    item = {"code": code, **fields}
    if data is not None:
        item["data"] = base64.b64encode(data).decode()
    return (json.dumps(item, ensure_ascii=False) + "\n").encode()


class Response(io.BytesIO):
    headers = {"X-Tt-Logid": "offline-log-id"}


class BrokenResponse(Response):
    def readline(self, limit=-1):
        result = super().readline(limit)
        if not result:
            raise http.client.IncompleteRead(b"partial chunk")
        return result


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "作品"
        self.project.mkdir()
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "speech-test"}), "utf-8")
        self.key = "private-speech-test-key"
        env = mock.patch.dict(os.environ, {speech.credentials.KEY_ENV: self.key}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        # Every live-path test has an explicit offline transport. A missed fixture fails closed.
        transport = mock.patch.object(speech, "open_stream", side_effect=AssertionError("unexpected network attempt"))
        self.remote = transport.start()
        self.addCleanup(transport.stop)
        tools = mock.patch.object(speech.shutil, "which", return_value="/offline/tool")
        tools.start()
        self.addCleanup(tools.stop)
        probe = mock.patch.object(speech, "probe_audio", return_value={"duration_ms": 100, "sample_rate": 24000,
                    "codec": "pcm_s16le", "container": "wav", "channels": 1})
        self.probe = probe.start()
        self.addCleanup(probe.stop)

    def args(self, *extra):
        return speech.parser().parse_args(["synthesize", "--project", str(self.project), "--out", "06-素材/声音",
            "--name", "VOICE-01", "--text", "你好。", "--speaker", "zh_female_vv_uranus_bigtts",
            "--format", "wav", "--max-chars", "20", *extra])

    def response(self, *parts, broken=False):
        self.remote.side_effect = None
        self.remote.return_value = (BrokenResponse if broken else Response)(b"".join(parts))

    def saved(self):
        return json.loads((self.project / "06-素材/声音/VOICE-01-生成记录.json").read_text("utf-8"))

    def test_dry_run_needs_no_key_or_media_tools_and_does_not_write(self):
        os.environ.clear()
        args = self.args("--dry-run", "--context", "克制而悲伤")
        request = speech.synthesize(args)
        self.assertTrue(request["dry_run"])
        self.assertFalse(request["billable"])
        payload = request["binding"]["payload"]
        self.assertEqual(json.loads(payload["req_params"]["additions"]), {"context_texts": ["克制而悲伤"]})
        self.assertEqual(request["text_chars"], 3)
        self.assertFalse((self.project / "06-素材").exists())
        self.remote.assert_not_called()
        self.probe.assert_not_called()

    def test_default_is_dry_run_and_missing_key_asks_for_agent_plan_key(self):
        self.assertTrue(speech.synthesize(self.args())["dry_run"])
        os.environ.clear()
        os.environ["HUO_SHAN_API_KEY"] = "other-ark-key"
        with self.assertRaisesRegex(speech.SpeechError, "火山方舟 Agent 版本") as error:
            speech.synthesize(self.args("--execute"))
        self.assertIn(speech.credentials.KEY_ENV, str(error.exception))
        self.assertIn("source ~/.zshenv", str(error.exception))
        self.remote.assert_not_called()
        self.assertFalse((self.project / "06-素材/声音/VOICE-01-任务.json").exists())

    def test_explicit_key_env_and_no_literal_key(self):
        os.environ.clear()
        os.environ["TEAM_SPEECH_KEY"] = "explicit-iam-key"
        self.response(frame(0, wav_bytes()), frame(20000000))
        speech.synthesize(self.args("--execute", "--key-env", "TEAM_SPEECH_KEY"))
        headers = {k.lower(): v for k, v in self.remote.call_args.args[0].headers.items()}
        self.assertEqual(headers["x-api-key"], "explicit-iam-key")
        with self.assertRaisesRegex(speech.SpeechError, "环境变量名"):
            speech.synthesize(self.args("--key-env", "literal secret key"))

    def test_agent_plan_is_default_route_and_cannot_resume_as_standard_service(self):
        self.response(frame(0, wav_bytes()), frame(20000000))
        record = speech.synthesize(self.args("--execute"))
        self.assertEqual(self.remote.call_args.args[0].full_url, speech.ENDPOINTS["agent-plan"])
        self.assertEqual(record["engine"]["provider"], "doubao_speech")
        os.environ.clear()
        self.assertEqual(speech.synthesize(self.args("--execute", "--service", "agent-plan")), record)
        with self.assertRaisesRegex(speech.SpeechError, "输入或预算已改变"):
            speech.synthesize(self.args("--execute", "--service", "speech"))
        self.remote.assert_called_once()

    def test_agent_plan_does_not_guess_clone_support_or_retry_auth_with_other_route(self):
        with self.assertRaisesRegex(speech.SpeechError, "不支持复刻"):
            speech.synthesize(self.args("--execute", "--service", "agent-plan", "--resource-id", "seed-icl-2.0", "--model", "seed-tts-2.0-standard"))
        self.remote.assert_not_called()
        self.remote.side_effect = urllib.error.HTTPError(speech.ENDPOINTS["agent-plan"], 401, "denied", {}, io.BytesIO())
        with self.assertRaisesRegex(speech.SpeechError, "HTTP 401：.*没有豆包语音合成的权限，请自行核对"):
            speech.synthesize(self.args("--execute", "--service", "agent-plan"))
        self.remote.assert_called_once()
        self.assertEqual(self.remote.call_args.args[0].full_url, speech.ENDPOINTS["agent-plan"])

    def test_success_concatenates_chunks_records_usage_and_is_idempotent_without_key(self):
        data = wav_bytes()
        self.response(frame(0, data[:73], sentence={"text": "你"}), frame(0, data[73:]),
                      frame(20000000, usage={"text_words": 3}))
        record = speech.synthesize(self.args("--execute", "--context", "平静地说"))
        self.assertEqual(consistency.record_errors(record), [])
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["purpose"], "asset")
        self.assertEqual(record["budget"]["usage"], {"text_words": 3})
        self.assertEqual(record["engine"]["completion_code"], 20000000)
        self.assertEqual(record["engine"]["response_chunks"], 3)
        self.assertEqual((self.project / record["outputs"][0]["path"]).read_bytes(), data)
        self.assertEqual(record["outputs"][0]["voice"], "zh_female_vv_uranus_bigtts")
        self.assertEqual(record["engine"]["params"]["resource_id"], "seed-tts-2.0")
        request = self.remote.call_args.args[0]
        self.assertEqual(request.full_url, speech.ENDPOINTS["agent-plan"])
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.assertEqual(headers["x-api-resource-id"], "seed-tts-2.0")
        self.assertEqual(headers["x-control-require-usage-tokens-return"], "*")
        self.assertEqual(headers["x-api-request-id"], record["engine"]["request_id"])
        chunks = self.project / record["engine"]["response_journal"]["path"]
        journal = [json.loads(line) for line in chunks.read_text().splitlines()]
        self.assertEqual(sum(chunk["audio_bytes"] for chunk in journal), len(data))
        self.assertNotIn("data", journal[0])
        os.environ.clear()
        resumed = speech.synthesize(self.args("--execute", "--context", "平静地说"))
        self.assertEqual(resumed, record)
        self.remote.assert_called_once()
        for path in (self.project / "06-素材/声音").glob("*.json*"):
            self.assertNotIn(self.key, path.read_text())

    def test_error_after_audio_keeps_usage_and_never_retries(self):
        self.response(frame(0, wav_bytes()), frame(45000001, message=f"denied {self.key}", usage={"text_words": 1}))
        with self.assertRaisesRegex(speech.SpeechError, "45000001"):
            speech.synthesize(self.args("--execute"))
        record = self.saved()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["budget"]["usage"], {"text_words": 1})
        self.assertNotIn(self.key, json.dumps(record))
        self.assertFalse(list((self.project / "06-素材/声音").glob("*.wav")))
        with self.assertRaises(speech.SpeechError):
            speech.synthesize(self.args("--execute"))
        self.remote.assert_called_once()

    def test_eof_and_network_truncation_are_failed_even_with_audio(self):
        for broken in (False, True):
            with self.subTest(broken=broken):
                args = self.args("--execute", "--name", "VOICE-broken-" + str(broken))
                self.response(frame(0, wav_bytes()), broken=broken)
                with self.assertRaises(speech.SpeechError):
                    speech.synthesize(args)
                path = self.project / f"06-素材/声音/{args.name}-生成记录.json"
                self.assertEqual(json.loads(path.read_text())["status"], "failed")
                with self.assertRaises(speech.SpeechError):
                    speech.synthesize(args)
        self.assertEqual(self.remote.call_count, 2)

    def test_bad_protocol_empty_audio_and_corrupt_media_fail(self):
        cases = (b"not-json\n", b'{"data":"YQ=="}\n', b'{"code":0,"data":"***"}\n',
                 frame(20000000), frame(0, b"garbage") + frame(20000000))
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                self.response(data)
                args = self.args("--execute", "--name", f"BAD-{index}")
                if index == 4:
                    self.probe.side_effect = speech.SpeechError("音频无法解码")
                with self.assertRaises(speech.SpeechError):
                    speech.synthesize(args)
                self.assertFalse((self.project / f"06-素材/声音/BAD-{index}.wav").exists())

    def test_http_and_unknown_transport_failures_do_not_resubmit(self):
        self.remote.side_effect = urllib.error.HTTPError(speech.ENDPOINT, 403, "denied", {}, io.BytesIO(self.key.encode()))
        with self.assertRaisesRegex(speech.SpeechError, "HTTP 403"):
            speech.synthesize(self.args("--execute"))
        with self.assertRaises(speech.SpeechError):
            speech.synthesize(self.args("--execute"))
        self.remote.assert_called_once()
        self.assertEqual(self.saved()["budget"]["usage"]["note"], "请求可能计费；未收到平台用量，金额未知")

    def test_input_drift_and_tampered_success_cannot_reuse_or_pay_again(self):
        self.response(frame(0, wav_bytes()), frame(20000000))
        record = speech.synthesize(self.args("--execute"))
        for options in (("--text", "再见。"), ("--context", "悲伤"), ("--max-chars", "21"),
                        ("--speaker", "another_voice"), ("--sample-rate", "16000")):
            with self.subTest(options=options), self.assertRaisesRegex(speech.SpeechError, "输入或预算已改变"):
                speech.synthesize(self.args("--execute", *options))
        output = self.project / record["outputs"][0]["path"]
        output.write_bytes(b"changed")
        with self.assertRaisesRegex(speech.SpeechError, "SHA-256"):
            speech.synthesize(self.args("--execute"))
        self.remote.assert_called_once()

    def test_text_file_drift_and_tampered_voice_record_are_rejected(self):
        text_file = self.project / "text.txt"
        text_file.write_text("第一句。", "utf-8")
        args = self.args("--execute")
        args.text, args.text_file = None, "text.txt"
        self.response(frame(0, wav_bytes()), frame(20000000))
        record = speech.synthesize(args)
        self.assertEqual(record["inputs"]["text"], "第一句。")
        text_file.write_text("另一句。", "utf-8")
        with self.assertRaisesRegex(speech.SpeechError, "输入或预算已改变"):
            speech.synthesize(args)
        text_file.write_text("第一句。", "utf-8")
        record["outputs"][0]["voice"] = "forged-voice"
        record_file = self.project / "06-素材/声音/VOICE-01-生成记录.json"
        record_file.write_text(json.dumps(record), "utf-8")
        with self.assertRaisesRegex(speech.SpeechError, "音色或人物"):
            speech.synthesize(args)
        self.remote.assert_called_once()

    def test_same_name_lock_prevents_second_submission(self):
        out = self.project / "06-素材/声音"
        out.mkdir(parents=True)
        with speech.generation_lock(out / ".VOICE-01-生成.lock"):
            with self.assertRaisesRegex(speech.SpeechError, "正在运行"):
                speech.synthesize(self.args("--execute"))
        self.remote.assert_not_called()

    def test_budget_and_path_escape_rejected_before_network(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.project / "link").symlink_to(outside, target_is_directory=True)
        for options in (("--max-chars", "2"), ("--max-chars", "0"), ("--out", "../outside"),
                        ("--out", str(outside)), ("--out", "link/voices"), ("--name", "../../outside"),
                        ("--name", "."), ("--out", "bad\\folder")):
            with self.subTest(options=options), self.assertRaises(speech.SpeechError):
                speech.synthesize(self.args("--execute", *options))
        self.remote.assert_not_called()

    def test_symlink_output_or_state_and_lock_refused(self):
        out = self.project / "06-素材/声音"
        out.mkdir(parents=True)
        outside = Path(self.temp.name) / "private"
        outside.write_text("unchanged")
        (out / "VOICE-01.wav").symlink_to(outside)
        with self.assertRaises(speech.SpeechError):
            speech.synthesize(self.args("--execute"))
        (out / "VOICE-01.wav").unlink()
        (out / ".VOICE-01-生成.lock").symlink_to(outside)
        with self.assertRaises(speech.SpeechError):
            speech.synthesize(self.args("--execute"))
        self.assertEqual(outside.read_text(), "unchanged")
        self.remote.assert_not_called()

    def test_entity_binding_and_clone_context_restrictions(self):
        bible = {"format": consistency.BIBLE_FORMAT, "project_id": "speech-test", "entities": [
            {"id": "CHAR-1", "kind": "character", "voice": {"engine": "doubao_speech",
                "voice": "zh_female_vv_uranus_bigtts", "resource_id": "seed-tts-2.0"}}]}
        (self.project / "bible.json").write_text(json.dumps(bible))
        args = self.args("--entity", "CHAR-1", "--bible", "bible.json")
        plan = speech.synthesize(args)
        self.assertEqual(plan["binding"]["inputs"]["entity"], "CHAR-1")
        with self.assertRaisesRegex(speech.SpeechError, "不一致"):
            speech.synthesize(self.args("--entity", "CHAR-1", "--bible", "bible.json", "--speaker", "changed"))
        with self.assertRaisesRegex(speech.SpeechError, "不支持 context_texts"):
            speech.synthesize(self.args("--service", "speech", "--resource-id", "seed-icl-2.0", "--context", "悲伤"))
        clone = speech.synthesize(self.args("--service", "speech", "--resource-id", "seed-icl-2.0", "--speaker",
                                           "S_existing_licensed", "--model", "seed-tts-2.0-standard"))
        self.assertEqual(clone["binding"]["payload"]["req_params"]["model"], "seed-tts-2.0-standard")
        self.assertNotIn("additions", clone["binding"]["payload"]["req_params"])

    def test_submitted_marker_exists_before_transport_and_crash_cannot_resubmit(self):
        def crash(request):
            task = json.loads((self.project / "06-素材/声音/VOICE-01-任务.json").read_text())
            self.assertEqual(task["status"], "submitted")
            self.assertEqual(task["binding"]["payload"], json.loads(request.data))
            raise KeyboardInterrupt()
        self.remote.side_effect = crash
        with self.assertRaises(KeyboardInterrupt):
            speech.synthesize(self.args("--execute"))
        with self.assertRaises(speech.SpeechError):
            speech.synthesize(self.args("--execute"))
        self.remote.assert_called_once()


@unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "真实媒体检查需要 ffprobe/ffmpeg")
class ActualMediaTests(unittest.TestCase):
    def test_actual_wav_and_mp3_probe_and_full_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / "voice.wav"
            wav.write_bytes(wav_bytes())
            metadata = speech.probe_audio(wav, "wav", 24000)
            self.assertEqual(metadata["duration_ms"], 100)
            mp3 = Path(folder) / "voice.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(mp3)], check=True, capture_output=True)
            self.assertEqual(speech.probe_audio(mp3, "mp3", 24000)["codec"], "mp3")
            with self.assertRaises(speech.SpeechError):
                speech.probe_audio(wav, "mp3", 24000)
            with self.assertRaises(speech.SpeechError):
                speech.probe_audio(wav, "wav", 16000)
            wav.write_bytes(wav_bytes()[:-1000])
            with self.assertRaises(speech.SpeechError):
                speech.probe_audio(wav, "wav", 24000)


if __name__ == "__main__":
    unittest.main()
