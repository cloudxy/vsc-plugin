#!/usr/bin/env python3
"""remotion_plan.py 自测。运行：python3 tests/test_remotion_plan.py"""
import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import SCRIPTS
SPEC = importlib.util.spec_from_file_location("remotion_plan", SCRIPTS / "remotion_plan.py")
REMOTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REMOTION)


def plan():
    return {
        "format": "vsc.remotion-render-plan/v1", "project_id": "rain-letter",
        "composition": {"id": "ep-001", "width": 1080, "height": 1920, "fps": 30, "duration_in_frames": 180},
        "segments": [
            {"id": "SH-001", "kind": "video", "source": "takes/SH-001.mp4", "source_shot_id": "SH-001", "from_frame": 0, "duration_in_frames": 180, "fade_in_frames": 6},
            {"id": "AUD-001", "kind": "audio", "source": "audio/bgm.mp3", "from_frame": 0, "duration_in_frames": 180},
            {"id": "CAP-001", "kind": "caption", "text": "门外是谁？", "from_frame": 120, "duration_in_frames": 45},
        ],
    }


class TestRemotionPlan(unittest.TestCase):
    def test_timeline_wrapper_preserves_outer_sha_and_font_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            font = root / "bound-font.otf"
            font.write_bytes(b"fixture font content for copy/hash test")
            value = plan()
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

    def test_rejects_range_overflow_and_insufficient_handles(self):
        value = plan()
        value["segments"][0].update(source_in_frame=5, handle_in_frames=6, handle_out_frames=10, source_duration_in_frames=190)
        errors = REMOTION.validate(value)
        self.assertTrue(any("handle_in_frames" in error for error in errors))
        self.assertTrue(any("尾手柄" in error for error in errors))

    def test_rejects_bad_audio_envelopes(self):
        value = plan()
        value["segments"][1].update(volume=2, audio_fade_out_frames=181, volume_keyframes=[{"frame": 120, "volume": 1}, {"frame": 0, "volume": 0.2}, {"frame": 180, "volume": 0.2}])
        errors = REMOTION.validate(value)
        self.assertTrue(any(".volume " in error for error in errors))
        self.assertTrue(any("audio_fade_out_frames" in error for error in errors))
        self.assertTrue(any("帧必须递增" in error for error in errors))

    def test_malformed_plan_is_rejected_without_crashing(self):
        self.assertTrue(REMOTION.validate([]))
        value = plan()
        value["composition"]["duration_in_frames"] = "bad"
        value["composition"]["fps"] = {"numerator": 30, "denominator": 0}
        self.assertTrue(REMOTION.validate(value))

    def test_rejects_unsafe_media_and_unlinked_visual(self):
        value = plan()
        value["segments"][0].pop("source_shot_id")
        value["segments"][1]["source"] = "../secret.mp3"
        errors = REMOTION.validate(value)
        self.assertTrue(any("source_shot_id" in error for error in errors))
        self.assertTrue(any("安全相对路径" in error for error in errors))

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


if __name__ == "__main__":
    unittest.main()
