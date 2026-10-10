#!/usr/bin/env python3
"""temp_voice.py 自测：不联网，用假的执行器模拟 edge-tts 进程。运行：python3 tests/test_temp_voice.py"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
import temp_voice as TV


class LinesTest(unittest.TestCase):
    def check(self, lines):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lines.json"
            path.write_text(json.dumps(lines, ensure_ascii=False), "utf-8")
            return TV.load_lines(path)

    def test_invalid_lines_are_rejected(self):
        for lines in ([], [{"id": "../x", "text": "a"}], [{"id": "A", "text": " "}], [{"id": "A", "text": "a"}, {"id": "A", "text": "b"}]):
            with self.assertRaises(TV.VoiceError):
                self.check(lines)

    def test_gender_suffix_is_dropped_for_edge(self):
        self.assertEqual(TV.edge_voice("zh-CN-YunxiNeural-Male"), "zh-CN-YunxiNeural")
        self.assertEqual(TV.edge_voice("zh-CN-XiaoxiaoNeural"), "zh-CN-XiaoxiaoNeural")


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / "vsc.json").write_text("{}", "utf-8")
        self.lines = root / "lines.json"
        self.lines.write_text(json.dumps([
            {"id": "DX-01", "text": "测试台词，第二句。"},
            {"id": "DX-02", "text": "另一条。", "voice": "zh-CN-YunjianNeural-Male", "rate": 0.9},
        ], ensure_ascii=False), "utf-8")
        patcher = mock.patch.object(TV.shutil, "which", return_value="/usr/bin/uv")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def fake_worker(self, cues_by_id, failing=()):
        def run(command, **kwargs):
            self.command = command
            job_path = Path(command[-1])
            job = json.loads(job_path.read_text("utf-8"))
            for item in job["lines"]:
                if item["id"] in failing:
                    item["cues"], item["error"] = [], "ConnectionError: offline"
                    continue
                Path(item["audio"]).write_bytes(b"mp3")
                item["cues"], item["error"] = cues_by_id[item["id"]], None
            job_path.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return run

    def test_sentences_word_fallback_and_record(self):
        cues = {"DX-01": [[0.1, 0.5, "测试"], [0.5, 0.9, "台词"], [1.1, 1.6, "第二句"]], "DX-02": [[0.0, 0.4, "别的"]]}
        output, record = TV.generate(self.project, self.lines, artifact="A-0004", run=self.fake_worker(cues))
        self.assertIn(TV.EDGE_TTS, self.command)
        first, second = record["outputs"]
        self.assertEqual((first["subtitle_mode"], second["subtitle_mode"]), ("sentence", "word"))
        self.assertEqual((second["voice"], second["rate"]), ("zh-CN-YunjianNeural", "-10%"))
        self.assertIn("00:00:00,100 --> 00:00:00,900\n测试台词", (output / "DX-01.srt").read_text("utf-8"))
        self.assertEqual(record["use"], TV.TEMP_USE)
        self.assertEqual(record["inputs"]["artifact"], "A-0004")
        self.assertEqual(json.loads((output / "生成记录.json").read_text("utf-8"))["errors"], [])

    def test_failed_line_is_recorded_without_losing_others(self):
        cues = {"DX-01": [[0.0, 1.0, "测试台词第二句"]]}
        output, record = TV.generate(self.project, self.lines, run=self.fake_worker(cues, failing={"DX-02"}))
        self.assertEqual([item["id"] for item in record["outputs"]], ["DX-01"])
        self.assertEqual(record["errors"], [{"id": "DX-02", "error": "ConnectionError: offline"}])
        self.assertFalse((output / "DX-02.mp3").exists())

    def test_non_project_directory_is_rejected(self):
        with self.assertRaises(TV.VoiceError):
            TV.generate(Path(self.temp.name), self.lines, run=self.fake_worker({}))


if __name__ == "__main__":
    unittest.main()
