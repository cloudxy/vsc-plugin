#!/usr/bin/env python3
"""jianying_export.py 自测。映射不依赖外部工具；真实写入需要 ffmpeg/ffprobe。

运行：python3 tests/test_jianying_export.py
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from _paths import SCRIPTS  # noqa: F401  被测模块位于 scripts/
import jianying_export as JY


def plan():
    return {
        "format": "vsc.remotion-render-plan/v1", "project_id": "sample",
        "composition": {"id": "sample", "width": 320, "height": 240, "fps": 30, "duration_in_frames": 90},
        "segments": [
            {"id": "V1", "kind": "video", "source": "takes/v1.mp4", "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": 60, "muted": True},
            {"id": "V2", "kind": "video", "source": "takes/v2.mp4", "source_shot_id": "SH-002", "from_frame": 45, "duration_in_frames": 45, "source_in_frame": 6, "fade_in_frames": 15},
            {"id": "BGM", "kind": "audio", "source": "audio/bgm.wav", "from_frame": 0, "duration_in_frames": 90, "volume": 0.5,
             "volume_keyframes": [{"frame": 0, "volume": 1}, {"frame": 60, "volume": 0.3}]},
            {"id": "CAP", "kind": "caption", "text": "门外是谁？", "from_frame": 30, "duration_in_frames": 30},
            {"id": "IMG", "kind": "image", "source": "stills/card.png", "source_shot_id": "SH-003", "from_frame": 60, "duration_in_frames": 30},
        ],
    }


class MediaFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("takes/v1.mp4", "takes/v2.mp4", "audio/bgm.wav", "stills/card.png"):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(b"x")

    def tearDown(self):
        self.temp.cleanup()


class MappingTest(MediaFixture):
    def test_supported_fps_and_duration_are_fixed_fractional_fps_rejected(self):
        for fps in (24, 25, 30):
            value = plan()
            value["composition"].update(fps=fps, duration_in_frames=fps * 4)
            payload, _, _ = JY.draft_payload(value, self.root)
            self.assertEqual((payload["fps"], payload["duration_us"]), (fps, 4_000_000))
            self.assertEqual(payload["black_intervals_frames"][-1][1], fps * 4)
        for fps in (60, 23.976, {"numerator": 30000, "denominator": 1001}, {"numerator": 24, "denominator": 1}):
            value = plan()
            value["composition"]["fps"] = fps
            with self.subTest(fps=fps), self.assertRaises(JY.ExportError):
                JY.draft_payload(value, self.root)

    def test_shared_style_is_preserved_and_unsupported_background_rejected(self):
        payload, _, _ = JY.draft_payload(plan(), self.root, {"font_size": 48, "color": "#FF0000", "position": "top"})
        self.assertEqual((payload["subtitle_style"]["font_size"], payload["subtitle_style"]["position"]), (48, "top"))
        with self.assertRaises(JY.ExportError):
            JY.draft_payload(plan(), self.root, {"background": "#000000"})

    def test_jianying_uses_shared_strict_subtitle_parser(self):
        srt = self.root / "bad.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:00,500\n有效\n\n2\nbad time\n坏块")
        self.assertEqual(len(JY.jd._parse_srt_entries(str(srt))), 1)
        with self.assertRaises(ValueError):
            JY.jd._parse_srt_entries(str(srt), strict=True, duration=1)

    def test_tracks_timing_volume_and_dropped_features(self):
        payload, captions, dropped = JY.draft_payload(plan(), self.root)
        self.assertEqual([(item["id"], item["track"]) for item in payload["video"]], [("V1", 0), ("V2", 1)])
        self.assertEqual(payload["video"][0]["volume"], 0.0)
        self.assertEqual((payload["video"][1]["start_us"], payload["video"][1]["source_start_us"]), (1_500_000, 200_000))
        self.assertEqual(payload["audio"][0]["volume"], 0.5)
        self.assertEqual(captions, [(1.0, 2.0, "门外是谁？")])
        self.assertEqual(len(dropped), 3)
        self.assertTrue(any(item.startswith("IMG") for item in dropped))
        self.assertTrue(any("fade_in_frames" in item for item in dropped))
        self.assertTrue(any("音量关键帧" in item for item in dropped))

    def test_missing_media_and_invalid_plan_are_rejected(self):
        (self.root / "takes/v2.mp4").unlink()
        with self.assertRaises(JY.ExportError):
            JY.draft_payload(plan(), self.root)
        bad = plan()
        bad["format"] = "other"
        with self.assertRaises(JY.ExportError):
            JY.draft_payload(bad, self.root)


class DryRunTest(MediaFixture):
    def test_dry_run_writes_nothing(self):
        (self.root / "vsc.json").write_text("{}", "utf-8")
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan(), ensure_ascii=False), "utf-8")
        output, record = JY.export(plan_path, self.root, drafts_root=self.root / "drafts", dry_run=True)
        self.assertIsNone(output)
        self.assertEqual(record["summary"], {"video": 2, "video_tracks": 2, "audio_tracks": 1, "captions": 1})
        self.assertFalse((self.root / "07-后期").exists())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "真实写入需要 ffmpeg 与 ffprobe")
class RealExportTest(unittest.TestCase):
    def test_explicit_tail_black_keeps_24_25_30_fps_and_complete_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=2", "-c:v", "mpeg4", str(media)], check=True, timeout=60)
            for fps in (24, 25, 30):
                value = plan()
                value["composition"].update(fps=fps, duration_in_frames=2 * fps)
                value["segments"] = [{"id": "V1", "kind": "video", "source": media.name, "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": fps, "muted": True},
                                     {"id": "C1", "kind": "caption", "text": "尾字幕", "from_frame": fps, "duration_in_frames": fps}]
                payload, captions, _ = JY.draft_payload(value, root)
                srt = root / f"captions-{fps}.srt"
                srt.write_text(JY.subtitles.to_srt(captions))
                payload.update(drafts_root=str(root), name=f"black-{fps}", srt=str(srt))
                result = JY.build_draft(payload)
                draft_path = Path(result["draft_path"])
                draft = json.loads((draft_path / "draft_info.json").read_text())
                self.assertEqual((draft["fps"], draft["duration"]), (fps, 2_000_000))
                video_segments = draft["tracks"][0]["segments"]
                self.assertEqual(sorted((s["target_timerange"]["start"], s["target_timerange"]["duration"]) for s in video_segments), [(0, 1_000_000), (1_000_000, 1_000_000)])
                probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=avg_frame_rate,nb_read_frames", "-of", "json", str(draft_path / "assets/video/vsc-black-1.mp4")], capture_output=True, text=True, check=True, timeout=30)
                stream = json.loads(probe.stdout)["streams"][0]
                self.assertEqual((stream["avg_frame_rate"], int(stream["nb_read_frames"])), (f"{fps}/1", fps))

    def test_multitrack_draft_is_written_with_backup_and_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "vsc.json").write_text("{}", "utf-8")
            (root / "takes").mkdir()
            (root / "audio").mkdir()
            for name in ("v1", "v2"):
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=3", "-c:v", "mpeg4", str(root / f"takes/{name}.mp4")], check=True, timeout=60)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(root / "audio/bgm.wav")], check=True, timeout=60)
            value = plan()
            value["segments"] = [segment for segment in value["segments"] if segment["kind"] != "image"]
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
            drafts = root / "drafts"
            drafts.mkdir()
            (drafts / "root_meta_info.json").write_text('{"all_draft_store": [], "draft_ids": 0, "root_path": ""}', "utf-8")
            output, record = JY.export(plan_path, root, drafts_root=drafts, name="VSC-real")
            draft = json.loads((Path(record["draft"]["draft_path"]) / "draft_info.json").read_text("utf-8"))
            self.assertEqual([track["type"] for track in draft["tracks"]], ["video", "video", "audio", "text"])
            self.assertEqual(draft["canvas_config"]["width"], 320)
            self.assertEqual(draft["duration"], 3_000_000)
            self.assertTrue((output / "root_meta_info.json.backup").is_file())
            self.assertTrue(Path(record["draft"]["draft_path"], "assets/audio/bgm.wav").is_file())
            meta = json.loads((drafts / "root_meta_info.json").read_text("utf-8"))
            self.assertEqual([item["draft_name"] for item in meta["all_draft_store"]], ["VSC-real"])
            self.assertEqual(len(record["dropped"]), 2)


if __name__ == "__main__":
    unittest.main()
