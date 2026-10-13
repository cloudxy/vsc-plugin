#!/usr/bin/env python3
"""subtitle_burn.py 自测。真实烧录需要 uv、ffmpeg 与已安装的 noto-sans-sc；uv 首次拉取 Pillow 需要联网。

运行：python3 tests/test_subtitle_burn.py
"""
import shutil
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from _paths import ROOT
import subtitle_burn as SB

STYLE = {"font": None, "font_size": 24, "color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 1.5,
         "position": "bottom", "custom_position": 70.0, "background": None, "rounded": False}


class LayoutTest(unittest.TestCase):
    def test_placement_matches_position_rules(self):
        self.assertEqual(SB.placement("bottom", 70, 1000, 100), 850)
        self.assertEqual(SB.placement("top", 70, 1000, 100), 50)
        self.assertEqual(SB.placement("center", 70, 1000, 100), 450)
        self.assertEqual(SB.placement("custom", 70, 1000, 100), 630)

    def test_overlay_chain_enables_each_cue_in_its_window(self):
        cues = [{"png": "a.png", "x": 10, "y": 20, "start": 0.2, "end": 1.0}, {"png": "b.png", "x": 5, "y": 6, "start": 2.0, "end": 3.5}]
        command = SB.overlay_command("in.mp4", cues, "out.mp4")
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[0:v][1:v]overlay=x=10:y=20:enable='between(t,0.200,1.000)'[v1]", graph)
        self.assertIn("[v1][2:v]overlay=x=5:y=6:enable='between(t,2.000,3.500)'[v2]", graph)
        self.assertEqual(command[command.index("-map") + 1], "[v2]")


@unittest.skipUnless(importlib.util.find_spec("PIL") and SB.DEFAULT_FONT.is_file(), "字幕排版测试需要本机 Pillow 与 noto-sans-sc")
class RenderLayoutTest(unittest.TestCase):
    def render_cues(self, texts):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "job.json"
            path.write_text(json.dumps({"directory": temp, "width": 1080, "height": 1920,
                                        "style": dict(STYLE, font=str(SB.DEFAULT_FONT), font_size=60),
                                        "cues": [{"text": value, "start": 0, "end": 1} for value in texts]}, ensure_ascii=False), "utf-8")
            SB.render(path)
            return json.loads(path.read_text("utf-8"))["cues"]

    def test_long_chinese_cue_uses_two_safe_lines_without_orphan_marks(self):
        cues = self.render_cues(["这句话包含较长的前半句，接着还有一段后半句……"])
        self.assertEqual(len(cues[0]["lines"]), 2)
        self.assertTrue(cues[0]["lines"][-1].endswith("……"))
        self.assertFalse(any(line[0] in SB.subtitles.LINE_START_PUNCTUATION for line in cues[0]["lines"]))

    def test_paragraph_requiring_three_lines_is_rejected_with_cue_number(self):
        with self.assertRaisesRegex(SB.subtitles.SubtitleError, "第 1 条字幕"):
            self.render_cues(["这段对白太长，需要按真正的语音停顿重新拆分字幕。" * 4])


class StyleTest(unittest.TestCase):
    def test_arguments_override_bible_which_overrides_defaults(self):
        bible = ROOT / "templates/asset-bible.json"
        style, source = SB.resolve_style(bible, {"font_size": 48, "color": None})
        self.assertEqual(source, "bible+args")
        self.assertEqual(style["font_size"], 48)
        self.assertEqual(style["stroke_color"], "#000000")
        self.assertEqual(Path(style["font"]), ROOT / "vendor/noto-sans-sc/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf")
        self.assertEqual(SB.resolve_style()[1], "default")


class InputTest(unittest.TestCase):
    def test_delivery_rejects_partial_bad_srt_and_out_of_range_before_render(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            font = root / "fixture.otf"
            font.write_bytes(b"not loaded because SRT must fail first")
            for text in ("1\n00:00:00,000 --> 00:00:00,500\n有效\n\n2\nbad time\n丢失", "1\n00:01:30,000 --> 00:01:31,000\n越界"):
                (root / "a.srt").write_text(text)
                with patch.object(SB, "probe_video", return_value=(320, 240, 1)), self.assertRaises(SB.BurnError):
                    SB.burn(root / "in.mp4", root / "a.srt", root / "out.mp4", dict(STYLE, font=str(font)))

    def test_bad_inputs_are_rejected_before_rendering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "out.mp4").write_bytes(b"x")
            (root / "a.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", "utf-8")
            with self.assertRaises(SB.BurnError):
                SB.burn(root / "in.mp4", root / "a.srt", root / "out.mp4", STYLE)
            with self.assertRaises(SB.BurnError):
                SB.burn(root / "in.mp4", root / "a.srt", root / "new.mp4", dict(STYLE, position="left"))
            with self.assertRaises(SB.BurnError):
                SB.burn(root / "in.mp4", root / "a.srt", root / "new.mp4", dict(STYLE, font=str(root / "missing.otf")))


@unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and SB.DEFAULT_FONT.is_file(), "离线真实烧录需要本机 Pillow、ffmpeg 与 noto-sans-sc；不安装依赖")
class RealBurnTest(unittest.TestCase):
    def test_burned_frame_differs_only_inside_cue_window(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video, output = root / "in.mp4", root / "out.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
            srt = root / "a.srt"
            srt.write_text("1\n00:00:00,500 --> 00:00:01,000\n测试字幕\n", "utf-8")
            def offline_runner(command, **kwargs):
                if "render" in command:
                    # Exercise the real Pillow renderer without uv cache writes or downloads.
                    SB.render(command[-1])
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                return subprocess.run(command, **kwargs)
            with patch.object(SB.shutil, "which", return_value="offline-test-renderer"):
                result = SB.burn(video, srt, output, STYLE, run=offline_runner)
            self.assertEqual((result["cues"], result["size"]), (1, [320, 240]))

            def frame(at):
                return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                      capture_output=True, check=True, timeout=60).stdout
            plain = bytes([frame(0.1)[0]]) * len(frame(0.1))
            self.assertNotEqual(frame(0.75), frame(0.1))
            self.assertLess(sum(a != b for a, b in zip(frame(1.5), plain)), len(plain) // 100)


if __name__ == "__main__":
    unittest.main()
