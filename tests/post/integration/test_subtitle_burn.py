#!/usr/bin/env python3
"""scripts/post/subtitle_burn.py 自测。真实烧录需要 uv、ffmpeg 与已安装的 noto-sans-sc；uv 首次拉取 Pillow 需要联网。

运行：python3 -B tests/run.py --test post.integration.test_subtitle_burn
"""
import shutil
import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from support.paths import ROOT
import vsc.post.subtitle_burn as SB

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
        self.assertIn("[0:v][1:v]overlay=x=10:y=20:enable='gte(t,0.200)*lt(t,1.000)'[v1]", graph)
        self.assertIn("[v1][2:v]overlay=x=5:y=6:enable='gte(t,2.000)*lt(t,3.500)'[v2]", graph)
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
        self.assertEqual("".join(cues[0]["lines"]), "这句话包含较长的前半句接着还有一段后半句")
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
    def test_render_plan_binds_the_real_formal_package_to_its_project_before_render(self):
        from vsc.post import remotion_plan as R
        import wave
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "isolated.wav"
            with wave.open(str(audio), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 32000)
            audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
            def snapshot(identifier, document):
                raw = json.dumps(document, ensure_ascii=False)
                return {"id": identifier, "document_utf8": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "approval_decision_id": "synthetic-approval-" + identifier}
            script = snapshot("script", {"script_lines": [{"line_key": "line-key", "scene_id": "scene", "text": "固定字幕"}]})
            measurement = {"method": "manual_waveform", "version": "isolated-fixture/v1", "line_key": "line-key",
                           "audio_media_sha256": audio_sha, "start_ms": 200, "end_ms": 800, "evidence": {"synthetic_fixture": True}}
            cue_artifact = snapshot("cue-artifact", {"cues": [{"key": "cue-key", "scope_object_id": "episode", "line_id": "line",
                "parameters": {"subtitle_alignment": {"measurement": measurement, "script_version_sha256": script["sha256"],
                                                          "audio_media_sha256": audio_sha}}}]})
            timeline = snapshot("timeline", {"composition": {"fps": 30}, "items": [{"offset_frame": 0, "media": [
                {"media_id": "audio", "binding_decision_id": "binding", "source_in_frame": 0, "source_out_frame": 60}]}]})
            package = SB.subtitles.seal_package({"format": SB.subtitles.PACKAGE_FORMAT, "project_id": "package-project",
                "scope_episode_id": "episode", "scope_object_ids": ["episode", "scene"], "timeline_id": "timeline",
                "status": "verified", "gaps": [], "duration_ms": 2000, "timeline_artifact": timeline,
                "cue_artifacts": [cue_artifact], "scripts": [script],
                "lines": [{"id": "line", "line_key": "line-key", "scene_id": "scene", "text": "固定字幕", "ordinal": 0,
                           "script_version_id": "script", "script_version_sha256": script["sha256"]}],
                "audio_sources": [{"item_id": "item", "line_id": "line", "item_ordinal": 0, "path": audio.name,
                    "sha256": audio_sha, "media_id": "audio", "binding_decision_id": "binding", "source_in_ms": 0,
                    "source_out_ms": 2000, "timeline_start_ms": 0, "duration_ms": 2000}],
                "cues": [{"cue_id": "cue", "cue_key": "cue-key", "line_id": "line", "item_id": "item", "source_text": "固定字幕",
                    "source_start_ms": 200, "source_end_ms": 800, "start_ms": 200, "end_ms": 800,
                    "script_version_sha256": script["sha256"], "audio_media_sha256": audio_sha, "measurement": measurement,
                    "cue_artifact_id": "cue-artifact", "cue_artifact_sha256": cue_artifact["sha256"],
                    "approval_decision_id": cue_artifact["approval_decision_id"]}]})
            # Exercise the actual package verifier, not a mock with a permissive return.
            self.assertEqual(SB.subtitles.package_cues(package, root, project_id="package-project", formal=True)["cues"], [(0.2, 0.8, "固定字幕")])
            value = {"format": R.FORMAT, "project_id": "package-project", "composition": {
                "id": "isolated", "width": 320, "height": 240, "fps": 30, "duration_in_frames": 60}, "subtitle_package": package,
                "segments": [{"id": "v", "kind": "video", "source": "input.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 60}]
                    + SB.subtitles.caption_segments(package, 30)}
            value["segments"][1]["subtitle_style"] = {"position": "top"}
            font = root / "not-rendered-font.otf"
            font.write_bytes(b"project checks happen before loading the actual render font")
            style = dict(STYLE, font=str(font))
            def stop_at_renderer(*args, **kwargs):
                raise RuntimeError("renderer boundary reached")
            with patch.object(SB, "probe_video", return_value=(320, 240, 2)), patch.object(SB.shutil, "which", return_value="offline-renderer"):
                for supplied in (None, value):
                    # Preserve package-only legacy behavior; a same-project plan also passes.
                    with self.subTest(valid_plan=supplied is not None), self.assertRaisesRegex(RuntimeError, "renderer boundary reached"):
                        SB.burn(root / "input.mp4", None, root / "out.mp4", style, run=stop_at_renderer,
                            subtitle_package=package, subtitle_root=root, formal_subtitles=True, render_plan=supplied)
                for project in ("other-project", None, "", 7):
                    changed_package = SB.subtitles.seal_package({**package, "project_id": project})
                    changed = copy.deepcopy(value)
                    changed["subtitle_package"] = changed_package
                    with self.subTest(package_project=project), self.assertRaisesRegex(SB.BurnError, "项目范围不一致"):
                        SB.burn(root / "input.mp4", None, root / "out.mp4", style, run=stop_at_renderer,
                            subtitle_root=root, formal_subtitles=True, render_plan=changed)
                other_plan = copy.deepcopy(value)
                other_plan["project_id"] = "other-project"
                with self.assertRaisesRegex(SB.BurnError, "项目范围不一致"):
                    SB.burn(root / "input.mp4", None, root / "out.mp4", style, run=stop_at_renderer,
                        subtitle_root=root, formal_subtitles=True, render_plan=other_plan)
                other_plan.pop("subtitle_package")
                with self.assertRaisesRegex(SB.BurnError, "项目范围不一致"):
                    SB.burn(root / "input.mp4", None, root / "out.mp4", style, run=stop_at_renderer,
                        subtitle_package=package, subtitle_root=root, formal_subtitles=True, render_plan=other_plan)

    def test_plan_mismatch_and_non_caption_overrides_fail_before_render(self):
        from vsc.post import remotion_plan as R
        value = {"format": R.FORMAT, "project_id": "isolated", "composition": {
            "id": "isolated", "width": 320, "height": 240, "fps": 30, "duration_in_frames": 60},
            "segments": [{"id": "v", "kind": "video", "source": "input.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 60},
                         {"id": "c", "kind": "caption", "text": "保留台词", "from_frame": 15, "duration_in_frames": 15,
                          "subtitle_style": {"position": "top"}}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            font = root / "fixture.otf"
            font.write_bytes(b"not loaded; reference checks fail before renderer")
            srt = root / "wrong.srt"
            srt.write_text("1\n00:00:00,500 --> 00:00:01,000\n另一句\n", "utf-8")
            for label, document, size in (("text", value, (320, 240, 2)),
                                           ("size", value, (640, 480, 2))):
                with self.subTest(label=label), patch.object(SB, "probe_video", return_value=size), self.assertRaises(SB.BurnError):
                    SB.burn(root / "in.mp4", srt, root / "out.mp4", dict(STYLE, font=str(font)), render_plan=document)
            invalid = copy.deepcopy(value)
            invalid["segments"][0]["subtitle_style"] = {"position": "top"}
            with patch.object(SB, "probe_video", return_value=(320, 240, 2)), self.assertRaises(SB.BurnError):
                SB.burn(root / "in.mp4", None, root / "out.mp4", dict(STYLE, font=str(font)), render_plan=invalid)

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


@unittest.skipUnless(importlib.util.find_spec("PIL") and SB.DEFAULT_FONT.is_file(), "跨消费者实际字体验证需要 Pillow 与固定字体")
class SharedConsumerTest(unittest.TestCase):
    def test_formal_consumers_require_fixed_package_for_plain_captions(self):
        from vsc.post import remotion_plan as R
        from vsc.adapters.editors import jianying_export as J
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            style = dict(STYLE, font=str(SB.DEFAULT_FONT), font_size=32)
            (root / "input.mp4").write_bytes(b"synthetic mapping fixture")
            srt = root / "input.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n需要固定来源\n")
            plan = {"format": R.FORMAT, "project_id": "isolated", "composition": {
                "id": "isolated", "width": 640, "height": 360, "fps": 30, "duration_in_frames": 30}, "subtitle_style": style,
                "segments": [{"id": "v", "kind": "video", "source": "input.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 30},
                    {"id": "caption", "kind": "caption", "text": "需要固定来源", "from_frame": 0, "duration_in_frames": 30}]}
            for consumer, consume in [
                ("burn", lambda: SB.burn(root / "input.mp4", srt, root / "out.mp4", style, formal_subtitles=True)),
                ("remotion", lambda: R.scaffold(plan, root / "remotion", formal_subtitles=True)),
                ("jianying", lambda: J.draft_payload(plan, root, formal_subtitles=True))]:
                with self.subTest(consumer=consumer), patch.object(SB, "probe_video", return_value=(640, 360, 1)), self.assertRaises((ValueError, RuntimeError)):
                    consume()

    def test_display_and_uneven_timecodes_reach_all_three_consumers(self):
        from vsc.post import remotion_plan as R
        from vsc.adapters.editors import jianying_export as J
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            style = dict(STYLE, font=str(SB.DEFAULT_FONT), font_size=60)
            original = ["价格3.14万元！", "2:30到场；比例2:1。"]
            entries = [(0.2, 0.8, original[0]), (1.1, 2.4, original[1])]
            srt = root / "original.srt"
            srt.write_text(SB.subtitles.to_srt(entries))
            before = srt.read_bytes()
            value = {"format": R.FORMAT, "project_id": "isolated", "composition": {
                "id": "isolated", "width": 1080, "height": 1920, "fps": 30, "duration_in_frames": 90},
                "subtitle_style": style, "segments": [{"id": "v", "kind": "video", "source": "input.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 90, "muted": True}] + [
                    {"id": f"c{index}", "kind": "caption", "text": text, "from_frame": round(begin * 30), "duration_in_frames": round((end - begin) * 30)}
                    for index, (begin, end, text) in enumerate(entries)]}
            (root / "input.mp4").write_bytes(b"synthetic mapping fixture, not decoded media")
            source = json.dumps(value, ensure_ascii=False)
            captured = []
            def renderer(command, **kwargs):
                if "render" in command:
                    SB.render(command[-1])
                    captured.extend(json.loads(Path(command[-1]).read_text())["cues"])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            with patch.object(SB, "probe_video", return_value=(1080, 1920, 3)), patch.object(SB.shutil, "which", return_value="offline-renderer"):
                burned = SB.burn(root / "input.mp4", srt, root / "out.mp4", style, run=renderer, script_texts=original)
            manifest = R.scaffold(value, root / "remotion", strict_subtitles=True, script_texts=original)
            generated = json.loads((root / "remotion/src/plan.ts").read_text().split(" = ", 1)[1].strip().removesuffix(";"))
            payload, captions, _ = J.draft_payload(value, root, script_texts=original)
            expected = [(begin, end, SB.subtitles.display_text(text)) for begin, end, text in entries]
            self.assertEqual([(cue["start"], cue["end"], cue["text"]) for cue in captured], expected)
            self.assertEqual(captions, expected)
            self.assertEqual([(s["from_frame"] / 30, (s["from_frame"] + s["duration_in_frames"]) / 30, s["text"]) for s in generated["segments"] if s["kind"] == "caption"], expected)
            for checks in (burned["subtitle_checks"], manifest["subtitle_checks"], payload["subtitle_checks"]):
                self.assertEqual(checks["text_coverage"], "passed")
                self.assertEqual(checks["font_layout"], "passed")
                self.assertEqual(checks["audio_alignment"], "not_verified")
            self.assertEqual(srt.read_bytes(), before)
            self.assertEqual(json.dumps(value, ensure_ascii=False), source)

    def test_actual_consumers_reject_repetition_loss_overlap_and_three_lines(self):
        from vsc.post import remotion_plan as R
        from vsc.adapters.editors import jianying_export as J
        cases = [("missing-repeat", [(0, 1, "好")], ["好", "好"]),
                 ("overlap", [(0, 1, "一"), (0.5, 1.5, "二")], ["一", "二"]),
                 ("long", [(0, 2, "字幕内容" * 30)], ["字幕内容" * 30]),
                 ("height", [(0, 2, "好")], ["好"])]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            style = dict(STYLE, font=str(SB.DEFAULT_FONT), font_size=60)
            (root / "input.mp4").write_bytes(b"synthetic")
            def renderer(command, **kwargs):
                if "render" in command:
                    SB.render(command[-1])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            for label, entries, original in cases:
                srt = root / "input.srt"
                srt.write_text(SB.subtitles.to_srt(entries))
                height = 50 if label == "height" else 1920
                value = {"format": R.FORMAT, "project_id": "isolated", "composition": {
                    "id": "isolated", "width": 1080, "height": height, "fps": 30, "duration_in_frames": 90}, "subtitle_style": style,
                    "segments": [{"id": "v", "kind": "video", "source": "input.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 90}] + [
                        {"id": f"c{n}", "kind": "caption", "text": text, "from_frame": round(begin * 30), "duration_in_frames": round((end - begin) * 30)} for n, (begin, end, text) in enumerate(entries)]}
                for name, consume in [
                    ("burn", lambda: SB.burn(root / "input.mp4", srt, root / "out.mp4", style, run=renderer, script_texts=original)),
                    ("remotion", lambda: R.scaffold(value, root / label, strict_subtitles=True, script_texts=original)),
                    ("jianying", lambda: J.draft_payload(value, root, script_texts=original))]:
                    with self.subTest(case=label, consumer=name), patch.object(SB, "probe_video", return_value=(1080, height, 3)), patch.object(SB.shutil, "which", return_value="offline-renderer"), self.assertRaises((ValueError, RuntimeError)):
                        consume()


@unittest.skipUnless(importlib.util.find_spec("PIL") and shutil.which("ffmpeg") and SB.DEFAULT_FONT.is_file(), "离线真实烧录需要本机 Pillow、ffmpeg 与 noto-sans-sc；不安装依赖")
class RealBurnTest(unittest.TestCase):
    def test_local_caption_position_produces_a_real_preview_and_preserves_other_cue_and_audio(self):
        from vsc.post import remotion_plan as R
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / "in.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True, timeout=60)
            style = dict(STYLE, font=str(SB.DEFAULT_FONT))
            original = {"format": R.FORMAT, "project_id": "isolated", "composition": {
                "id": "isolated", "width": 320, "height": 240, "fps": 30, "duration_in_frames": 60}, "subtitle_style": style,
                "segments": [{"id": "v", "kind": "video", "source": "in.mp4", "source_shot_id": "S", "from_frame": 0, "duration_in_frames": 60},
                    {"id": "selected", "kind": "caption", "text": "第一句", "from_frame": 6, "duration_in_frames": 18},
                    {"id": "untouched", "kind": "caption", "text": "第二句", "from_frame": 33, "duration_in_frames": 18}]}
            before = copy.deepcopy(original)
            edit = R.edit_caption_position(original, caption_id="selected", expected_sha256=R.document_sha256(original),
                layout={"position": "top"}, frame_range={"from_frame": 6, "duration_in_frames": 18})
            source_sha = hashlib.sha256(video.read_bytes()).hexdigest()
            def offline_runner(command, **kwargs):
                if "render" in command:
                    SB.render(command[-1])
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                return subprocess.run(command, **kwargs)
            for name, document in (("before", original), ("after", edit["document"])):
                with patch.object(SB.shutil, "which", return_value="offline-local-pillow"):
                    SB.burn(video, None, root / (name + ".mp4"), style, run=offline_runner, render_plan=document)
            self.assertEqual(original, before)
            self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(), source_sha)
            self.assertEqual(edit["document"]["segments"][2], original["segments"][2])
            def frame(name, at):
                return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(root / (name + ".mp4")),
                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True, timeout=60).stdout
            def bright_halves(pixels):
                half = len(pixels) // 2
                return sum(pixel > 180 for pixel in pixels[:half]), sum(pixel > 180 for pixel in pixels[half:])
            before_pixels, after_pixels = frame("before", .5), frame("after", .5)
            self.assertGreater(bright_halves(before_pixels)[1], 30)
            self.assertGreater(bright_halves(after_pixels)[0], 30)
            self.assertLess(bright_halves(after_pixels)[1], 10)
            self.assertLess(bright_halves(before_pixels)[0], 10)
            for at in (.1, 1.3, 1.8):
                a, b = frame("before", at), frame("after", at)
                self.assertLess(sum(abs(x - y) > 10 for x, y in zip(a, b)), len(a) // 100)
            def audio_hash(path):
                return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-c:a", "copy", "-f", "md5", "-"],
                    capture_output=True, check=True, timeout=60).stdout
            self.assertEqual(audio_hash(video), audio_hash(root / "before.mp4"))
            self.assertEqual(audio_hash(video), audio_hash(root / "after.mp4"))

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
            self.assertLess(sum(a != b for a, b in zip(frame(1.0), plain)), len(plain) // 100)
            self.assertLess(sum(a != b for a, b in zip(frame(1.5), plain)), len(plain) // 100)


if __name__ == "__main__":
    unittest.main()
