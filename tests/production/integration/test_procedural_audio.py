import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from support.paths import ROOT
import consistency as C
import procedural_audio as P


class ProceduralAudioTest(unittest.TestCase):
    def test_all_presets_are_original_deterministic_nonclipping_pcm(self):
        for preset in P.PRESETS:
            with self.subTest(preset=preset):
                samples = P.synthesize(preset, 0.15, seed=17)
                self.assertEqual(samples, P.synthesize(preset, 0.15, seed=17))
                self.assertEqual(len(samples), 3600)
                self.assertGreater(max(samples), 0)
                self.assertLess(max(abs(x) for x in samples), 32767)
                self.assertEqual((samples[0], samples[-1]), (0, 0))

    def test_budget_and_invalid_float_are_rejected(self):
        for value in (-1, 0, 121, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                P.synthesize("wind", value)

    def test_generate_record_reuse_and_drift_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "vsc.json").write_text(json.dumps({"project_id": "audio-test"}))
            argv = ["--project", tmp, "--name", "wind", "--preset", "wind", "--duration", "0.2"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(P.main(argv), 0)
                self.assertEqual(P.main(argv), 0)
                record_path = project / "06-素材/程序化声音/wind-生成记录.json"
                record = json.loads(record_path.read_text("utf-8"))
                self.assertEqual(C.record_errors(record), [])
                self.assertEqual((record["purpose"], record["budget"]["billable"], record["selection"]), ("asset", False, None))
                path = project / record["outputs"][0]["path"]
                with wave.open(str(path)) as audio:
                    self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getnframes()), (24000, 1, 4800))
                original = path.read_bytes()
                self.assertEqual(P.main([*argv, "--seed", "1"]), 1)
                self.assertEqual(path.read_bytes(), original)
                path.write_bytes(b"edited")
                self.assertEqual(P.main(argv), 1)
                self.assertEqual(path.read_bytes(), b"edited")

    def test_forged_hash_or_target_cannot_bypass_actual_audio_and_request_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "vsc.json").write_text('{"project_id":"audio-test"}')
            argv = ["--project", tmp, "--name", "rain", "--preset", "rain", "--duration", "0.1"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(P.main(argv), 0)
                record_path = project / "06-素材/程序化声音/rain-生成记录.json"
                original = json.loads(record_path.read_text())
                target = project / original["outputs"][0]["path"]
                for payload in (b'{"not":"audio"}', None):
                    if payload is None:
                        P.write_wave(target, P.synthesize("wind", 0.1))
                    else:
                        target.write_bytes(payload)
                    record = json.loads(json.dumps(original))
                    record["outputs"][0]["sha256"] = P.A.sha256(target)
                    record_path.write_text(json.dumps(record))
                    self.assertEqual(P.main(argv), 1)
                P.write_wave(target, P.synthesize("rain", 0.1))
                for field, value in (("inputs", {"prompt":"forged", "references":[]}), ("purpose", "candidate")):
                    record = json.loads(json.dumps(original)); record[field] = value
                    record_path.write_text(json.dumps(record))
                    self.assertEqual(P.main(argv), 1)
                other = target.with_name("other.wav"); other.write_bytes(target.read_bytes())
                record = json.loads(json.dumps(original)); record["outputs"][0]["path"] = str(other.relative_to(project))
                record_path.write_text(json.dumps(record))
                self.assertEqual(P.main(argv), 1)

    def test_output_cannot_leave_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "vsc.json").write_text('{"project_id":"audio-test"}')
            (project / "link").symlink_to(root, target_is_directory=True)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(P.main(["--project", str(project), "--out", "link", "--name", "bad", "--preset", "wind"]), 1)
            self.assertFalse((root / "bad.wav").exists())


if __name__ == "__main__":
    unittest.main()
