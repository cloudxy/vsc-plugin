#!/usr/bin/env python3
"""subtitle_burn.py 自测。真实烧录需要 uv、ffmpeg 与已安装的 noto-sans-sc；uv 首次拉取 Pillow 需要联网。

运行：python3 tests/test_subtitle_burn.py
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
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


class InputTest(unittest.TestCase):
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


@unittest.skipUnless(shutil.which("uv") and shutil.which("ffmpeg") and SB.DEFAULT_FONT.is_file(), "真实烧录需要 uv、ffmpeg 与 noto-sans-sc")
class RealBurnTest(unittest.TestCase):
    def test_burned_frame_differs_only_inside_cue_window(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video, output = root / "in.mp4", root / "out.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
            srt = root / "a.srt"
            srt.write_text("1\n00:00:00,500 --> 00:00:01,000\n测试字幕\n", "utf-8")
            result = SB.burn(video, srt, output, STYLE)
            self.assertEqual((result["cues"], result["size"]), (1, [320, 240]))

            def frame(at):
                return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                                      capture_output=True, check=True, timeout=60).stdout
            plain = bytes([frame(0.1)[0]]) * len(frame(0.1))
            self.assertNotEqual(frame(0.75), frame(0.1))
            self.assertLess(sum(a != b for a, b in zip(frame(1.5), plain)), len(plain) // 100)


if __name__ == "__main__":
    unittest.main()
