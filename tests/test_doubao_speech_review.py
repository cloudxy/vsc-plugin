"""Real local audio + offline protocol regression for formal speech/performance integration."""
import base64
import copy
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from _paths import ROOT  # noqa: F401
from test_vsc_budget import FixedRunFixture
import consistency
import doubao_speech as speech
import vsc_artifacts as artifacts
import vsc_audio_run as audio_run
import vsc_budget as budget
import vsc_run as formal
import vsc_state as state_module


class OfflineResponse(io.BytesIO):
    headers = {"X-Tt-Logid": "offline-review-fixture"}


@unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "Real offline speech media requires FFmpeg")
class SpeechReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory(prefix="vsc-real-speech-review-")
        cls.addClassCleanup(cls.media_temp.cleanup)
        wav = Path(cls.media_temp.name) / "synthetic-voice.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=0.75:sample_rate=24000", "-c:a", "pcm_s16le", str(wav)],
                       check=True, capture_output=True, timeout=30)
        cls.audio_bytes = wav.read_bytes()
        cls.measured = speech.probe_audio(wav, "wav", 24000)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-speech-review-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = FixedRunFixture(Path(self.temp.name) / "project")
        self.project = self.fixture.project
        self.key = "offline-review-fixture-not-a-credential"
        env = mock.patch.dict(os.environ, {"DOUBAO_SPEECH_API_KEY": self.key})
        env.start(); self.addCleanup(env.stop)
        for module in (artifacts, formal, state_module):
            check = mock.patch.object(module, "validate_artifact", side_effect=self.fixture.validator)
            check.start(); self.addCleanup(check.stop)
        # The adapter's sole transport seam is explicit; any missed path fails closed.
        transport = mock.patch.object(speech, "open_stream", side_effect=self.offline_stream)
        self.remote = transport.start(); self.addCleanup(transport.stop)
        forbidden = mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("live networking is forbidden"))
        forbidden.start(); self.addCleanup(forbidden.stop)
        self.line = "Synthetic dialogue."
        bible_data = {"format": consistency.BIBLE_FORMAT, "project_id": self.fixture.state["project_id"], "entities": [{
            "id": "CHAR-001", "kind": "character", "name": "Synthetic character", "identity": ["synthetic fixture"],
            "variants": {"default": "synthetic costume"}, "references": [],
            "voice": {"engine": speech.PROVIDER, "voice": "fixture-speaker", "resource_id": "seed-tts-2.0", "rights": "temp_only"}}]}
        self.assertEqual(consistency.bible_errors(bible_data), [])
        bible = self.fixture.register("vsc.asset_bible", bible_data, stage="animatic")
        screenplay = self.fixture.register("vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [{"dialogue": [
            {"id": "DL-001", "speaker": "CHAR-001", "text": self.line}]}]}, stage="animatic")
        animatic = self.fixture.register("vsc.animatic", {"format": "vsc.animatic/v1", "fixture": "isolated creative approval"}, stage="animatic")
        request = {"kind": "speech", "argv": ["--out", "audio", "--name", "voice", "--text", self.line,
                   "--speaker", "fixture-speaker", "--format", "wav", "--sample-rate", "24000", "--max-chars", "100",
                   "--line-id", "DL-001", "--screenplay", screenplay["path"], "--entity", "CHAR-001", "--bible", bible["path"],
                   "--acting-choice", "restrained", "--context", "restrained delivery", "--lip-sync-intent", "required"]}
        _, self.args, self.binding, self.operation, self.bound = audio_run.prepare(self.project, request)
        approved = [animatic, screenplay, bible]
        data = {"format": formal.FORMAT, "project_id": self.fixture.state["project_id"], "scope": "project",
                "audio_request": {**request, "binding": self.binding}, "plan_sha256": speech.digest_json(self.binding),
                "approved_inputs": [{"id": a["id"], "sha256": a["sha256"]} for a in approved],
                "review_after": [], "operations": {self.operation: self.bound}}
        self.run = self.fixture.register("vsc.production_run", data, approved)
        self.assertEqual(audio_run.project_errors(data, self.project, self.fixture.read_state(), self.run), [])
        self.assertEqual(formal.validation_errors(data), [])
        budget.configure(self.project, self.bound, "isolated fixture reviewer", "one local synthetic protocol response")

    def ledger(self):
        with budget.ledger(self.project) as data:
            return copy.deepcopy(data)

    def offline_stream(self, request):
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), self.binding["payload"])
        task = json.loads((self.project / "audio/voice-任务.json").read_text())
        self.assertEqual(task["status"], "submitted")
        self.assertEqual(task["binding"], self.binding)
        held = list(self.ledger()["reservations"].values())
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["status"], "submitted_unknown")
        middle = len(self.audio_bytes) // 2
        frames = [{"code": 0, "data": base64.b64encode(chunk).decode()} for chunk in (self.audio_bytes[:middle], self.audio_bytes[middle:])]
        frames.append({"code": 20000000})
        return OfflineResponse(b"".join((json.dumps(frame) + "\n").encode() for frame in frames))

    def assert_performance_and_import(self, record):
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(consistency.record_errors(record), [])
        output = record["outputs"][0]
        performance = output["performance"]
        self.assertEqual({k: performance[k] for k in ("line_id", "acting_choice", "lip_sync_intent")},
                         {k: self.binding["inputs"][k] for k in ("line_id", "acting_choice", "lip_sync_intent")})
        self.assertTrue(math.isfinite(performance["measured_duration_seconds"]))
        self.assertEqual(performance["measured_duration_seconds"], self.measured["duration_ms"] / 1000)
        self.assertEqual(performance["measured_duration_seconds"], 0.75)
        self.assertEqual(output["entity"], "CHAR-001")
        self.assertEqual(output["speaker"], self.binding["payload"]["req_params"]["speaker"])
        target = self.project / output["path"]
        self.assertEqual(target.read_bytes(), self.audio_bytes)
        self.assertEqual(output["sha256"], speech.sha256(target))
        self.assertEqual(speech.probe_audio(target, "wav", 24000), self.measured)
        saved = json.loads((self.project / "audio/voice-生成记录.json").read_text())
        self.assertEqual(saved, record)
        state = self.fixture.read_state()
        candidates = [a for a in state["artifacts"] if a.get("run_id") == self.run["id"]]
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual((candidate["status"], candidate["decision"]), ("draft", None))
        self.assertEqual(json.loads((self.project / candidate["path"]).read_text()), record)
        self.assertEqual(candidate["sha256"], artifacts.digest(self.project / candidate["path"]))
        self.assertIsNone(record["selection"])
        held = list(self.ledger()["reservations"].values())
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["status"], "usage_unknown")
        self.assertEqual(held[0]["line_id"], "DL-001")
        self.assertIsNone(held[0]["currency_cost"])

    def test_real_performance_duration_survives_formal_run_and_draft_import(self):
        record = audio_run.execute(self.project, self.run["id"])
        self.assert_performance_and_import(record)
        # Same formal run reuses the checked real record, never another POST.
        resumed = audio_run.execute(self.project, self.run["id"])
        self.assertEqual(resumed, record)
        self.assert_performance_and_import(resumed)
        self.remote.assert_called_once()

    def test_denied_authorization_writes_no_task_then_same_name_can_execute(self):
        self.args.execute, self.args.dry_run = True, False
        with self.assertRaises(budget.BudgetError):
            speech.synthesize(self.args)
        self.remote.assert_not_called()
        for filename in ("voice-任务.json", "voice-生成记录.json", "voice-响应.jsonl", "voice.wav"):
            self.assertFalse((self.project / "audio" / filename).exists(), filename)
        self.assertEqual(self.ledger()["reservations"], {})
        # Actual reservation/authorization succeeds; the denied name was not poisoned.
        record = audio_run.execute(self.project, self.run["id"])
        self.assert_performance_and_import(record)
        self.remote.assert_called_once()


if __name__ == "__main__":
    unittest.main()
