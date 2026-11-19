"""Local validators, quotes and ffmpeg derivations for canvas video-script tools."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from vsc.assets.canvas_video_ops import (
    IMAGE_BYTES_MAX, IMAGE_TYPES, analyze_video, execute_operation, is_sample_params,
    quote_operation, sample_window, upscale_image, validate_depth, validate_image_spec,
    validate_lyrics, validate_mv_brief, validate_remake, validate_storyboard,
)
from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_capabilities import canvas_capabilities

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _png(width, height, color=(210, 24, 24)):
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _lavfi(color, duration):
    with tempfile.TemporaryDirectory(prefix="vsc-c2-video-") as directory:
        path = Path(directory) / "clip.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=12:d={duration}",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
        ], check=True, timeout=30)
        return path.read_bytes()


def _two_color():
    with tempfile.TemporaryDirectory(prefix="vsc-c2-cut-") as directory:
        path = Path(directory) / "colors.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=64x64:r=25:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
            "-movflags", "+faststart", str(path),
        ], check=True, timeout=30)
        return path.read_bytes()


def _message(exc):
    return exc.exception.message


class CanvasVideoScriptToolTests(unittest.TestCase):
    def test_image_spec_five_types_and_scales(self):
        raw = _png(32, 32)
        self.assertEqual(validate_image_spec(raw), (32, 32))
        self.assertEqual(validate_image_spec(_png(300, 100)), (300, 100))
        self.assertEqual(validate_image_spec(_png(100, 300)), (100, 300))
        for model_type in IMAGE_TYPES:
            blob, meta = upscale_image(_png(8, 8), model_type=model_type, scale=2)
            with Image.open(io.BytesIO(blob)) as image:
                self.assertEqual(image.size, (16, 16))
                red, _green, blue = image.convert("RGB").getpixel((4, 4))
            self.assertGreater(red, 120)
            self.assertLess(blue, 80)
            self.assertEqual((meta["model_type"], meta["scale"], meta["processor"]), (model_type, 2, "lanczos"))
        wide, meta = upscale_image(_png(8, 8), scale=6)
        with Image.open(io.BytesIO(wide)) as image:
            self.assertEqual(image.size, (48, 48))
        self.assertEqual(meta["scale"], 6)
        with self.assertRaises(ResourceError) as oversized:
            validate_image_spec(b"\xff\xd8\xff" + b"0" * (IMAGE_BYTES_MAX + 1))
        self.assertEqual(_message(oversized), "图片不能超过 4.7MB")
        with self.assertRaises(ResourceError) as kind:
            validate_image_spec(b"GIF89a-not-image")
        self.assertEqual(_message(kind), "仅支持单张 JPEG 或 PNG")
        with self.assertRaises(ResourceError) as count:
            validate_image_spec(raw, image_count=2)
        self.assertEqual(_message(count), "仅支持单张 JPEG 或 PNG")
        with self.assertRaises(ResourceError) as ratio:
            validate_image_spec(_png(100, 400))
        self.assertEqual(_message(ratio), "宽高比须在 1:3 至 3:1 之间")
        with self.assertRaises(ResourceError) as huge:
            validate_image_spec(_png(4097, 2000))
        self.assertEqual(_message(huge), "图片宽高不能超过 4096")
        with self.assertRaises(ResourceError) as scale:
            upscale_image(raw, scale=3)
        self.assertEqual(_message(scale), "倍率仅支持 2x、4x、6x")

    def test_remake_depth_lyrics_storyboard_and_sample_rules(self):
        accepted = validate_remake(8, [{"start": 0, "end": 4}], "[00:00.000-00:04.000]", resolution="720P")
        self.assertEqual(accepted["segments"], [{"start": 0.0, "end": 4.0}])
        self.assertEqual(accepted["resolution"], "720p")
        with self.assertRaises(ResourceError) as overlap:
            validate_remake(12, [{"start": 0, "end": 5}, {"start": 4, "end": 9}], "[00:00.000-00:05.000][00:04.000-00:09.000]")
        self.assertEqual(_message(overlap), "重拍片段之间不能重叠")
        with self.assertRaises(ResourceError) as short:
            validate_remake(3, [{"start": 0, "end": 4}], "[00:00.000-00:04.000]")
        self.assertEqual(_message(short), "仅支持不短于 4 秒的视频")
        with self.assertRaises(ResourceError) as limit:
            validate_remake(40, [{"start": index * 4, "end": index * 4 + 4} for index in range(6)], "")
        self.assertEqual(_message(limit), "最多支持 5 个重拍片段")
        with self.assertRaises(ResourceError) as brief:
            validate_remake(8, [{"start": 0, "end": 3}], "[00:00.000-00:03.000]")
        self.assertEqual(_message(brief), "每个片段至少 4 秒，且不能超出视频时长")
        with self.assertRaises(ResourceError) as tags:
            validate_remake(8, [{"start": 0, "end": 4}], "[00:00.000-00:05.000]")
        self.assertEqual(_message(tags), "提示词中的时间标签与重拍片段不一致")
        self.assertEqual(validate_depth("480p", 180), "480p")
        self.assertEqual(validate_depth("720p", 30), "720p")
        with self.assertRaises(ResourceError) as depth480:
            validate_depth("480p", 180.1)
        self.assertEqual(_message(depth480), "480P 最长支持 3 分钟")
        with self.assertRaises(ResourceError) as depth720:
            validate_depth("720p", 31)
        self.assertEqual(_message(depth720), "720P 最长支持 30 秒")
        self.assertEqual(validate_lyrics("第一行\n第二行"), ["第一行", "第二行"])
        with self.assertRaises(ResourceError) as empty_line:
            validate_lyrics("第一行\n\n第二行")
        self.assertEqual(_message(empty_line), "歌词内容不能为空")
        shots = validate_storyboard({"shots": [{"index": 1, "instrumental": True}, {"text": "副歌"}]})
        self.assertTrue(shots[0]["instrumental"])
        self.assertEqual(shots[1]["text"], "副歌")
        with self.assertRaises(ResourceError) as bad_board:
            validate_storyboard({"shots": [{"text": "  "}]})
        self.assertEqual(_message(bad_board), "歌词分镜格式异常")
        with self.assertRaises(ResourceError) as music:
            validate_mv_brief({"image_node_ids": []})
        self.assertEqual(_message(music), "请先接入一段音乐")
        with self.assertRaises(ResourceError) as images:
            validate_mv_brief({"has_music": True, "image_node_ids": ["a", "b", "c", "d", "e"]})
        self.assertEqual(_message(images), "参考图最多 4 张")
        self.assertTrue(is_sample_params({"sample": True}))
        self.assertTrue(is_sample_params({"resolution": "480p"}))
        self.assertTrue(is_sample_params({"draft_task_id": "draft-1"}))
        self.assertFalse(is_sample_params({"height": 480}))
        self.assertFalse(is_sample_params({"draft_task_id": "draft-1", "resolution": "1080P"}))
        self.assertFalse(is_sample_params({"sample": True, "resolution": "1080p"}))
        early = sample_window("2026-10-27T12:00:00+00:00")
        later = sample_window("2026-10-28T02:00:00Z")
        self.assertEqual(early["days"], 7)
        self.assertEqual(later["days"], 14)
        self.assertEqual((later["deadline"] - later["created_at"]).days, 14)
        expired = quote_operation("sample_upgrade", {"created_at": "2026-10-01T00:00:00Z", "duration_seconds": 2}, now=datetime(2026, 11, 19, tzinfo=timezone.utc))
        self.assertFalse(expired["ready"])
        self.assertEqual(expired["message"], "原样片任务已过有效期，保留原480p结果，无法再升级")
        self.assertFalse(expired["provider_called"])
        fresh = quote_operation("sample_upgrade", {"created_at": "2026-11-19T00:00:00Z", "duration_seconds": 2.2}, now=datetime(2026, 11, 19, 1, tzinfo=timezone.utc))
        self.assertTrue(fresh["ready"])
        self.assertEqual(fresh["deadline_days"], 14)
        self.assertEqual(fresh["total_price"], 3)
        image_quote = quote_operation("image_upscale", {"scale": 4, "model_type": "high_fidelity"}, models=[{"id": "configured-upscale", "enabled": True, "capabilities": {"image_operations": ["upscale"]}}])
        self.assertEqual(image_quote["model_id"], "configured-upscale")
        self.assertEqual(image_quote["total_price"], 4)
        self.assertEqual(image_quote["price_basis"], "native_units")
        self.assertFalse(image_quote["provider_called"])
        local_quote = quote_operation("video_upscale", {"duration_seconds": 1})
        self.assertEqual(local_quote["model_id"], "local-ffmpeg")
        self.assertFalse(local_quote["provider_called"])

    def test_catalogue_enables_video_upscale_without_adding_operations(self):
        operations = {row["op_type"]: row for row in canvas_capabilities([])["operations"]}
        self.assertEqual(len(operations), 55)
        video = operations["video_upscale"]
        self.assertEqual((video["consumer"], video["action"], video["available"], video["name"]), ("editor", "video_upscale", True, "视频高清"))
        self.assertEqual([item["value"] for item in video["params_schema"]["fields"][0]["options"]], ["1080p", "2k", "4k"])
        self.assertFalse(operations["image_upscale"]["available"])
        self.assertEqual(operations["smart_video_breakdown"]["action"], "video_breakdown")
        self.assertEqual(operations["video_story_parse"]["action"], "video_story")
        self.assertEqual(operations["video_dewatermark"]["name"], "智能去字幕")
        self.assertEqual(operations["multi_video_edit"]["name"], "多视频合成剪辑")

    def test_authority_excerpt_and_validation_do_not_need_ffmpeg(self):
        draft = {"exists": True, "content": {"scenes": [{"id": "SC1", "dialogue": [{"text": "今晚我等你"}]}]}, "content_sha256": "abc", "draft_revision": 3}
        with self.assertRaises(ResourceError) as blocked:
            execute_operation("script_document_bind", {"write_script": True}, [], draft=draft)
        self.assertEqual(blocked.exception.code, "canvas_script_authority")
        self.assertEqual(blocked.exception.message, "画布上的文字编辑不会改写剧本资料")
        bound = execute_operation("script_document_bind", {"scope_key": ""}, [], draft=draft)[0]
        self.assertTrue(bound["text"].startswith("节点预览节选"))
        self.assertIn("今晚我等你", bound["text"])
        self.assertTrue(bound["params"]["excerpt"])
        self.assertIsNone(bound["content"])
        with self.assertRaises(ResourceError) as clips:
            execute_operation("multi_video_edit", {"segments": []}, [])
        self.assertEqual(_message(clips), "当前轨道中没有可导出的视频片段")
        with self.assertRaises(ResourceError) as audio:
            execute_operation("multi_video_edit", {"segments": [{"source_node_id": "v"}], "background_audio_node_id": ["a", "b"]}, [])
        self.assertEqual(_message(audio), "最多只能接入 1 条背景或参考音轨")
        with self.assertRaises(ResourceError) as boxes:
            execute_operation("video_dewatermark", {"mode": "region", "regions": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}] * 11}, [{"node_id": "v", "type": "video", "content": b"mp4"}])
        self.assertEqual(_message(boxes), "最多框选 10 个擦除区域")

    @unittest.skipUnless(HAS_FFMPEG, "requires ffmpeg and ffprobe")
    def test_ffmpeg_breakdown_compose_erase_and_story(self):
        cut = _two_color()
        analysis = analyze_video(cut)
        self.assertEqual((analysis["width"], analysis["height"]), (64, 64))
        self.assertGreaterEqual(len(analysis["scenes"]), 2)
        self.assertGreater(analysis["scenes"][1]["start"], 0.5)
        source = {"node_id": "cut", "type": "video", "content": cut}
        grouped = execute_operation("video_breakdown", {"dimensions": ["storyboard", "video", "audio"]}, [source])
        self.assertEqual({item["params"]["smartVideoBreakdownResult"] for item in grouped}, {"storyboard", "video", "audio"})
        joined = "\n".join(item["text"] for item in grouped)
        self.assertNotIn("开场建立镜头", joined)
        self.assertNotIn("主体动作推进", joined)
        self.assertIn("64×64", joined)
        self.assertIn("镜头2", joined)
        script = execute_operation("video_script_extract", {}, [source])[0]
        self.assertRegex(script["text"], r"\[00:00\.000-")
        self.assertIn("64×64", script["text"])
        story = execute_operation("video_story", {}, [source])[0]
        table = json.loads(story["text"])
        self.assertEqual(table["columns"], ["镜号", "起止", "景别", "机位", "运动", "焦距景深", "光线", "叙事", "画面描述", "图像提示词", "运动提示词", "人声/音效", "背景音乐", "关键帧缩略图"])
        self.assertGreaterEqual(len(table["rows"]), 2)
        self.assertEqual(story["params"]["schema"], "video_story_node/v1")
        self.assertTrue(story["params"]["locked"])
        red = _lavfi("red", "0.4")
        blue = _lavfi("blue", "0.4")
        composed = execute_operation("multi_video_edit", {"segments": [
            {"source_node_id": "red", "start_seconds": 0},
            {"source_node_id": "blue", "start_seconds": 0, "end_seconds": 0.4},
        ]}, [
            {"node_id": "red", "type": "video", "content": red},
            {"node_id": "blue", "type": "video", "content": blue},
        ])[0]
        self.assertIn(b"ftyp", composed["content"][:64])
        self.assertEqual(composed["source_ids"], ["red", "blue"])
        with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
            handle.write(composed["content"])
            handle.flush()
            probed = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", handle.name,
            ], timeout=20))
        self.assertLess(abs(float(probed["format"]["duration"]) - 0.8), 0.35)
        erased = execute_operation("video_dewatermark", {"mode": "region", "regions": [{"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.3}]}, [{"node_id": "red", "type": "video", "content": red}])[0]
        self.assertIn(b"ftyp", erased["content"][:64])
        self.assertEqual(erased["params"]["erase_mode"], "region")
        depth = execute_operation("video_depth_map", {"clarity": "480p"}, [{"node_id": "red", "type": "video", "content": red}])[0]
        self.assertEqual(depth["params"]["clarity"], "480p")
        self.assertIn(b"ftyp", depth["content"][:64])
        long_clip = _lavfi("green", "8")
        remade = execute_operation("video_segment_remake", {
            "segments": [{"start": 0, "end": 4}],
            "prompt": "[00:00.000-00:04.000] 换成绿幕",
            "resolution": "480P",
        }, [{"node_id": "long", "type": "video", "content": long_clip}])[0]
        self.assertEqual(remade["params"]["resolution"], "480P")
        self.assertIn(b"ftyp", remade["content"][:64])
        upgraded = execute_operation("sample_upgrade", {
            "draft_task_id": "draft-local",
            "created_at": "2026-11-19T00:00:00Z",
            "duration_seconds": 0.4,
        }, [{"node_id": "red", "type": "video", "content": red}], now=datetime(2026, 11, 19, 1, tzinfo=timezone.utc))[0]
        self.assertEqual(upgraded["params"]["resolution"], "1080P")
        self.assertEqual(upgraded["params"]["draft_task_id"], "draft-local")
        self.assertNotIn("sample", upgraded["params"])
        self.assertIn(b"ftyp", upgraded["content"][:64])
