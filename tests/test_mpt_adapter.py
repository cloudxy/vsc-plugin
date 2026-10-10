#!/usr/bin/env python3
"""mpt_adapter.py 自测：不联网，用假的 CLI 执行器代替 MoneyPrinterTurbo。运行：python3 tests/test_mpt_adapter.py"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
import mpt_adapter as MPT


def touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class LinesTest(unittest.TestCase):
    def check(self, lines):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lines.json"
            path.write_text(json.dumps(lines, ensure_ascii=False), "utf-8")
            return MPT.load_lines(path)

    def test_valid_lines_load(self):
        self.assertEqual(len(self.check([{"id": "DX-01", "text": "测试台词。"}])), 1)

    def test_invalid_lines_are_rejected(self):
        for lines in ([], [{"id": "../x", "text": "a"}], [{"id": "A", "text": " "}], [{"id": "A", "text": "a"}, {"id": "A", "text": "b"}]):
            with self.assertRaises(MPT.AdapterError):
                self.check(lines)

    def test_cli_result_is_the_last_json_line(self):
        stdout = 'log {"not": "result"}\n{"task_id": "t", "result": {"subtitle_path": "/x/subtitle.srt"}}\n'
        self.assertEqual(MPT.cli_result(stdout)["result"]["subtitle_path"], "/x/subtitle.srt")
        with self.assertRaises(MPT.AdapterError):
            MPT.cli_result("no json here")


class ResourceTest(unittest.TestCase):
    def test_bundled_assets_are_linked_only_when_installed_and_prefixed(self):
        with tempfile.TemporaryDirectory() as temp:
            vendor = Path(temp)
            touch(vendor / "noto-sans-sc/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf")
            self.assertEqual(list(MPT.resource_links(vendor)), ["fonts/NotoSansSC-Bold.otf"])
            touch(vendor / "moneyprinterturbo-assets/resource/fonts/STHeitiMedium.ttc")
            touch(vendor / "moneyprinterturbo-assets/resource/songs/output000.mp3")
            self.assertEqual(sorted(MPT.resource_links(vendor)),
                             ["fonts/NotoSansSC-Bold.otf", "fonts/assets-STHeitiMedium.ttc", "songs/assets-output000.mp3"])

    def test_local_config_defaults_to_licensed_font_and_keeps_user_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            mpt = Path(temp)
            (mpt / "config.example.toml").write_text("[app]\nx = 1\n\n[ui]\nhide_log = false\nopen_task_folder_on_completion = true\n", "utf-8")
            text = MPT.ensure_config(mpt).read_text("utf-8")
            self.assertIn(f'font_name = "{MPT.DEFAULT_FONT}"', text)
            self.assertIn("open_task_folder_on_completion = false", text)
            (mpt / "config.toml").write_text('[ui]\nfont_name = "assets-STHeitiMedium.ttc"\n', "utf-8")
            self.assertIn("assets-STHeitiMedium.ttc", MPT.ensure_config(mpt).read_text("utf-8"))


class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.project = root / "project"
        touch(self.project / "vsc.json", b"{}")
        self.mpt = root / "mpt"
        (self.mpt).mkdir()
        (self.mpt / "config.example.toml").write_text("[ui]\n", "utf-8")
        self.lines = root / "lines.json"
        self.lines.write_text(json.dumps([{"id": "DX-01", "text": "测试台词一"}, {"id": "DX-02", "text": "测试台词二。", "voice": "zh-CN-YunjianNeural-Male"}], ensure_ascii=False), "utf-8")
        self.commands = []
        patches = [mock.patch.object(MPT, "require_installed", return_value=self.mpt),
                   mock.patch.object(MPT, "locked_source", return_value={"revision": "a" * 40}),
                   mock.patch.object(MPT.shutil, "which", return_value="/usr/bin/uv")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, fail_text=None):
        def run(command, **kwargs):
            self.commands.append(command)
            text = command[command.index("--video-script") + 1]
            if text == fail_text:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="edge-tts connection error")
            task = self.mpt / "storage" / command[command.index("--task-id") + 1]
            touch(task / "audio.mp3", text.encode())
            touch(task / "subtitle.srt", b"1\n00:00:00,000 --> 00:00:01,000\n" + text.encode() + b"\n")
            result = {"task_id": task.name, "result": {"subtitle_path": str(task / "subtitle.srt")}}
            return subprocess.CompletedProcess(command, 0, stdout="log line\n" + json.dumps(result) + "\n", stderr="")
        return run

    def test_outputs_are_copied_and_the_record_restricts_use(self):
        output, record = MPT.generate_voice(self.project, self.lines, artifact="A-0004", vendor_root=Path(self.temp.name), run=self.runner())
        self.assertEqual([item["id"] for item in record["outputs"]], ["DX-01", "DX-02"])
        self.assertTrue((output / "DX-02.mp3").is_file() and (output / "DX-02.srt").is_file())
        self.assertEqual(record["outputs"][1]["voice"], "zh-CN-YunjianNeural-Male")
        self.assertIn("不得进入交付物", record["use"])
        self.assertFalse(record["budget"]["billable"])
        self.assertEqual(record["inputs"]["artifact"], "A-0004")
        self.assertIn("--stop-at", self.commands[0])
        self.assertEqual(json.loads((output / "生成记录.json").read_text("utf-8"))["errors"], [])

    def test_failed_line_is_recorded_without_losing_others(self):
        _, record = MPT.generate_voice(self.project, self.lines, vendor_root=Path(self.temp.name), run=self.runner(fail_text="测试台词一"))
        self.assertEqual([item["id"] for item in record["outputs"]], ["DX-02"])
        self.assertEqual(record["errors"][0]["id"], "DX-01")
        self.assertIn("edge-tts", record["errors"][0]["error"])

    def test_non_project_directory_is_rejected(self):
        with self.assertRaises(MPT.AdapterError):
            MPT.generate_voice(Path(self.temp.name), self.lines, vendor_root=Path(self.temp.name), run=self.runner())


if __name__ == "__main__":
    unittest.main()
