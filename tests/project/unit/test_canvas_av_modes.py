"""Local FFmpeg helpers and canvas audio/video operation contracts."""
import io
import math
import shutil
import struct
import unittest
import wave

from vsc.assets.canvas_av_process import atempo_chain, canvas_quote_extras, extract_frame_bytes, process_audio_bytes
from vsc.assets.creative_canvas import normalize_document
from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_capabilities import canvas_capabilities, validate_work_operation


def _wav(duration_ms=2000, sample_rate=16000):
    frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        samples = [int(8000 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate)) for index in range(frames)]
        handle.writeframes(struct.pack("<" + "h" * frames, *samples))
    return buf.getvalue()


class CanvasAvModeContractTests(unittest.TestCase):
    def test_atempo_chain_stays_inside_ffmpeg_stage_limits(self):
        self.assertEqual(atempo_chain(4.0), "atempo=2.0,atempo=2.0")
        # 0.1 = 0.5×0.5×0.5×0.8；ffmpeg 单级 atempo 不能低于 0.5，所以不能写成 0.4。
        self.assertEqual(atempo_chain(0.1), "atempo=0.5,atempo=0.5,atempo=0.5,atempo=0.8")
        for token in atempo_chain(0.1).split(","):
            rate = float(token.split("=", 1)[1])
            self.assertGreaterEqual(rate, 0.5)
            self.assertLessEqual(rate, 2.0)
        with self.assertRaises(ResourceError):
            atempo_chain(True)
        with self.assertRaises(ResourceError):
            atempo_chain(0.05)

    def test_quote_extras_reject_out_of_range_seed_and_lyrics(self):
        extras = canvas_quote_extras({
            "audio_mode": "lyrics", "voice_id": "zh_female_vv_uranus_bigtts", "music_style": "古风,流行",
            "lyrics_chars": 12, "camera_motion_id": "builtin-push-in", "seed_sample_rate": 24000,
            "seed_format": "wav", "seed_speed": 1, "seed_pitch": -2, "seed_volume": 0.8,
        })
        self.assertEqual(extras["audio_mode"], "lyrics")
        self.assertEqual(extras["lyrics_chars"], 12)
        self.assertEqual(extras["seed_sample_rate"], 24000)
        for payload in (
            {"seed_sample_rate": 44100},
            {"audio_mode": "song"},
            {"lyrics_chars": True},
            {"seed_pitch": 1.5},
            {"seed_speed": 3},
            {"camera_motion_id": "x" * 81},
        ):
            with self.subTest(payload=payload), self.assertRaises(ResourceError) as caught:
                canvas_quote_extras(payload)
            self.assertEqual(caught.exception.code, "invalid_canvas_quote")

    def test_new_video_modes_are_generation_operations(self):
        operations = {row["op_type"]: row for row in canvas_capabilities([])["operations"]}
        self.assertEqual(len(operations), 55)
        self.assertEqual(operations["audio_to_video"]["name"], "音频生视频")
        self.assertEqual(operations["video_edit"]["name"], "视频编辑")
        self.assertEqual(operations["audio_to_video"]["consumer"], "work_generation")
        nodes = {
            "a": {"id": "a", "type": "audio"},
            "v": {"id": "v", "type": "video", "params": {"vsc_operation": "audio_to_video"}},
            "src": {"id": "src", "type": "video"},
            "edit": {"id": "edit", "type": "video", "params": {"vsc_operation": "video_edit"}},
        }
        with self.assertRaises(ResourceError):
            validate_work_operation(nodes["v"], [], nodes)
        self.assertEqual(validate_work_operation(nodes["v"], [{"source": "a", "target": "v", "port": "reference_audio"}], nodes)["op_type"], "audio_to_video")
        self.assertEqual(validate_work_operation(nodes["edit"], [{"source": "src", "target": "edit", "port": "reference_video"}], nodes)["mode"], "video_edit")
        normalize_document({"nodes": [{"id": "n", "type": "video", "params": {"vsc_operation": "video_edit"}}], "edges": []})


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local ffmpeg and ffprobe")
class CanvasAvFfmpegTests(unittest.TestCase):
    def test_clip_and_speed_change_measured_duration(self):
        source = _wav(2000)
        clipped, clip_meta = process_audio_bytes(source, operation="clip", start_seconds=0.4, end_seconds=1.2)
        self.assertLess(abs(clip_meta["output_duration_ms"] - 800), 80)
        self.assertGreater(clip_meta["source_duration_ms"], clip_meta["output_duration_ms"])
        self.assertTrue(clipped.startswith(b"RIFF"))
        sped, speed_meta = process_audio_bytes(source, operation="speed", speed=2)
        self.assertLess(abs(speed_meta["output_duration_ms"] - 1000), 150)
        self.assertLess(speed_meta["output_duration_ms"], speed_meta["source_duration_ms"])
        self.assertIn("atempo=2.0", speed_meta["filter"])

    def test_first_and_last_frames_are_png(self):
        import subprocess
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=64x64:r=25:d=1",
                "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25:d=1",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
                "-movflags", "+faststart", str(path),
            ], check=True, timeout=30)
            content = path.read_bytes()
        self.assertIn(b"ftyp", content[:32])
        first, _ = extract_frame_bytes(content, frame="first")
        last, _ = extract_frame_bytes(content, frame="last")
        self.assertTrue(first.startswith(b"\x89PNG"))
        self.assertTrue(last.startswith(b"\x89PNG"))
        self.assertNotEqual(first, last)
        with self.assertRaises(ResourceError):
            extract_frame_bytes(content, frame="current")
