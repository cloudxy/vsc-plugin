#!/usr/bin/env python3
"""scripts/post/remotion_plan.py 自测。运行：python3 -B tests/run.py --test post.integration.test_remotion_plan"""
import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from support.fixtures.plans import remotion_plan as plan
import vsc.post.remotion_plan as REMOTION


class TestRemotionPlan(unittest.TestCase):
    def test_scaffold_keeps_caption_override_in_the_actual_text_layer(self):
        from vsc.post.subtitle_burn import DEFAULT_FONT
        if not importlib.util.find_spec("PIL") or not DEFAULT_FONT.is_file():
            self.skipTest("局部字幕脚手架需要已安装实际字体与Pillow")
        value = plan()
        value["subtitle_style"] = {"font": str(DEFAULT_FONT), "font_size": 48}
        caption = next(s for s in value["segments"] if s["kind"] == "caption")
        result = REMOTION.edit_caption_position(value, caption_id=caption["id"], expected_sha256=REMOTION.document_sha256(value),
            layout={"position": "custom", "custom_position": 30})
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "scaffold"
            REMOTION.scaffold(result["document"], output, strict_subtitles=True)
            generated = json.loads((output / "src/plan.ts").read_text().split(" = ", 1)[1].strip().removesuffix(";"))
            actual = next(s for s in generated["segments"] if s["id"] == caption["id"])
            self.assertEqual(actual["subtitle_style"], {"position": "custom", "custom_position": 30})
            self.assertIn("style={{...subtitleStyle, ...segment.subtitle_style}}", (output / "src/ShortDrama.tsx").read_text())
            from vsc.adapters.editors import jianying_export as J
            with self.assertRaisesRegex(J.ExportError, "未接通单Cue位置覆盖"):
                J.draft_payload(result["document"], Path(temp))

    def test_resource_export_preserves_local_layout_or_rejects_a_changed_line(self):
        from vsc.post import resource_export as export
        from vsc.post import subtitles
        from vsc.assets.resource_service import ResourceError
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "input.mp4"
            media.write_bytes(b"isolated fixed byte-copy fixture; no rendering claim")
            media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
            package = {"cues": [{"cue_id": "one", "line_id": "line-one", "source_text": "保留台词", "start_ms": 4000, "end_ms": 5500}],
                       "package_sha256": "0" * 64, "status": "not_verified", "gaps": []}
            value = plan()
            value["segments"] = [value["segments"][0]] + subtitles.caption_segments(package, 30)
            value["segments"][1]["subtitle_style"] = {"position": "top"}
            document = {"format": "vsc.timeline/v1", "render_plan": value}
            fixed = {"revision": 1, "artifact": {"id": "artifact", "sha256": "1" * 64, "document": document},
                     "timeline": {"fps_num": 30, "fps_den": 1}, "items": [{"id": "item", "ordinal": 0,
                     "offset_frame": 0, "duration_frames": 180, "media": [{"blob_sha256": media_sha,
                     "locations": [{"storage": "local", "available": True, "object_key": "isolated"}],
                     "mime_type": "video/mp4", "source_in_frame": 0, "media_id": "media", "blob_id": "blob",
                     "binding_decision_id": "binding", "role": "video"}]}]}
            service = SimpleNamespace(storage=SimpleNamespace(verify=lambda key, sha: media),
                                      get_timeline=lambda project, timeline: fixed, get_project=lambda project: {"revision": 1})
            # This test owns the real export projection/copy path. Package provenance
            # is exercised in its existing resource tests; no DB is used here.
            with patch.object(export, "_subtitle_package", return_value=package), patch.object(subtitles, "package_cues"):
                export.export_render_package(service, value["project_id"], "timeline", root / "export", formal_subtitles=False)
                generated = json.loads((root / "export/render-plan.json").read_text())
                self.assertEqual(generated["segments"][1]["subtitle_style"], {"position": "top"})
                self.assertEqual(generated["segments"][1]["line_id"], "line-one")
                value["segments"][1]["line_id"] = "changed-line"
                with self.assertRaisesRegex(ResourceError, "无法唯一匹配"):
                    export.export_render_package(service, value["project_id"], "timeline", root / "rejected", formal_subtitles=False)
                self.assertFalse((root / "rejected").exists())

    def test_timeline_wrapper_preserves_outer_sha_and_font_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            font = root / "bound-font.otf"
            font.write_bytes(b"fixture font content for copy/hash test")
            value = plan()
            # This fixture verifies immutable font packaging, without claiming
            # the intentionally synthetic font can lay out actual captions.
            value["segments"] = [s for s in value["segments"] if s["kind"] not in {"caption", "text"}]
            value["subtitle_style"] = {"font": font.name, "font_size": 48, "color": "#FF0000", "position": "top"}
            document = {"format": "vsc.timeline/v1", "render_plan": value, "bindings": {"approved_artifact": "ART-001"}}
            source = root / "timeline.json"
            source.write_text(json.dumps(document, indent=4) + "\n")
            self.assertEqual(REMOTION.validate(document), [])
            output = root / "scaffold"
            manifest = REMOTION.scaffold(document, output, plan_path=source, strict_subtitles=True)
            self.assertEqual(manifest["source_plan"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual((output / "vsc-source-plan.json").read_bytes(), source.read_bytes())
            font_record = manifest["subtitle_style"]["font"]
            self.assertEqual((output / font_record["path"]).read_bytes(), font.read_bytes())
            self.assertEqual(font_record["sha256"], hashlib.sha256(font.read_bytes()).hexdigest())
            self.assertEqual(manifest["subtitle_style"]["resolved"]["position"], "top")
            self.assertEqual(manifest["verification"]["render"], "not_run")
            source_code = (output / "src/ShortDrama.tsx").read_text()
            self.assertIn("fontSize: style.font_size", source_code)
            self.assertIn("const safeMargin = 0.05", source_code)
            self.assertIn("face.load()", source_code)
            self.assertIn("cancelRender", source_code)
            self.assertNotIn("padding: 72", source_code)
            self.assertNotIn("fontSize: 42", source_code)

    def test_bad_style_missing_font_and_stale_source_are_rejected(self):
        value = plan()
        value["subtitle_style"] = {"stroke_width": float("nan")}
        self.assertTrue(REMOTION.validate(value))
        value["subtitle_style"] = {"font": "missing-fixture-font.otf"}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "render"
            with self.assertRaises(ValueError):
                REMOTION.scaffold(value, output)
            self.assertFalse(output.exists())
            source = Path(temp) / "source.json"
            source.write_text(json.dumps({**plan(), "project_id": "changed"}))
            with self.assertRaises(ValueError):
                REMOTION.scaffold(plan(), output, plan_path=source)
            self.assertFalse(output.exists())

    def test_valid_plan(self):
        self.assertEqual(REMOTION.validate(plan()), [])

    def test_rational_rate_and_media_range(self):
        value = plan()
        value["composition"]["fps"] = {"numerator": 30000, "denominator": 1001}
        value["segments"][0].update(source_in_frame=12, handle_in_frames=12, handle_out_frames=8, source_duration_in_frames=200, muted=True)
        value["segments"][1].update(volume=0.4, audio_fade_in_frames=15, audio_fade_out_frames=20, volume_keyframes=[{"frame": 0, "volume": 1}, {"frame": 120, "volume": 0.3}])
        self.assertEqual(REMOTION.validate(value), [])
        self.assertAlmostEqual(REMOTION.frame_rate(value["composition"]["fps"]), 29.97002997)

    def test_still_motion_is_bounded_and_image_only(self):
        value = plan()
        image = value["segments"][0]
        image["kind"] = "image"
        image["source"] = "stills/SH-001.png"
        image["still_motion"] = {"from": {"x": 0.2, "y": 0.5, "scale": 1.1},
            "to": {"x": 0.8, "y": 0.5, "scale": 1.3}, "easing": "ease_in_out"}
        self.assertEqual(REMOTION.validate(value), [])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "render"
            REMOTION.scaffold(value, output)
            source = (output / "src/ShortDrama.tsx").read_text()
            self.assertIn("stillMotionAtFrame(segment, frame)", source)
            self.assertIn("overflow: 'hidden'", source)
        image["still_motion"]["to"]["scale"] = 0.9
        self.assertTrue(any("still_motion.to" in error for error in REMOTION.validate(value)))
        image["still_motion"]["to"]["scale"] = 1.3
        image["kind"] = "video"
        self.assertTrue(any("仅适用于 image" in error for error in REMOTION.validate(value)))

    def test_scaffold_writes_editable_project_without_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "remotion-project"
            REMOTION.scaffold(plan(), output)
            self.assertTrue((output / "package.json").is_file())
            self.assertTrue((output / "src" / "ShortDrama.tsx").is_file())
            package = json.loads((output / "package.json").read_text("utf-8"))
            self.assertEqual(package["dependencies"]["@remotion/cli"], package["dependencies"]["remotion"])
            self.assertEqual(package["scripts"]["typecheck"], "tsc --noEmit")
            self.assertTrue((output / "tsconfig.json").is_file())
            self.assertIn("npm install", (output / "README.md").read_text("utf-8"))
            with self.assertRaises(ValueError):
                REMOTION.scaffold(plan(), output)

    @unittest.skipUnless(shutil.which("node"), "Node not installed; pure generated TS runtime test skipped")
    def test_generated_frame_math_executes_without_remotion_dependencies(self):
        version = subprocess.check_output(["node", "--version"], text=True)
        if int(version[1:].split(".")[0]) < 23:
            self.skipTest("Native TypeScript stripping test requires Node 23+")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "render"
            REMOTION.scaffold(plan(), output)
            code = f"const m = await import({json.dumps((output / 'src' / 'timing.ts').as_uri())});" + """
const segment = {id:'audio',kind:'audio',from_frame:0,duration_in_frames:180,volume:0.5,audio_fade_in_frames:10,audio_fade_out_frames:10,volume_keyframes:[{frame:0,volume:1},{frame:60,volume:0.2},{frame:120,volume:1}]};
console.log(JSON.stringify({begin:m.volumeAtFrame(segment,0),end:m.volumeAtFrame(segment,179),duck:m.volumeAtFrame(segment,60),recover:m.volumeAtFrame(segment,120),muted:m.volumeAtFrame({...segment,muted:true},120),fps:m.toFps({numerator:30000,denominator:1001}),middle:m.fadeGain(60,180,10,10),bottom:m.captionPlacement({position:'bottom'},.05),top:m.captionPlacement({position:'top'},.05),custom:m.captionPlacement({position:'custom',custom_position:70},.05)}));
"""
            result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", code], text=True))
            self.assertEqual(result["begin"], 0)
            self.assertEqual(result["end"], 0)
            self.assertAlmostEqual(result["duck"], 0.1)
            self.assertEqual(result["recover"], 0.5)
            self.assertEqual(result["muted"], 0)
            self.assertEqual(result["middle"], 1)
            self.assertEqual(result["bottom"], {"bottom": "5%"})
            self.assertEqual(result["top"], {"top": "5%"})
            self.assertEqual(result["custom"], {"top": "70%", "transform": "translateY(-70%)"})

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_still_motion_frame_math(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "render"
            REMOTION.scaffold(plan(), output)
            segment = {"kind": "image", "duration_in_frames": 3,
                "still_motion": {"from": {"x": 0, "y": 0.5, "scale": 1.2},
                                 "to": {"x": 1, "y": 0.5, "scale": 1.2}, "easing": "linear"}}
            code = f"const m = await import({json.dumps((output / 'src' / 'timing.ts').as_uri())});" + \
                f"const s = {json.dumps(segment)}; console.log(JSON.stringify([0,1,2].map(f=>m.stillMotionAtFrame(s,f))));"
            result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", code], text=True))
            self.assertAlmostEqual(result[0]["translateX"], 10)
            self.assertAlmostEqual(result[1]["translateX"], 0)
            self.assertAlmostEqual(result[2]["translateX"], -10)


if __name__ == "__main__":
    unittest.main()
