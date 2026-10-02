#!/usr/bin/env python3
"""remotion_plan.py 自测。运行：python3 scripts/test_remotion_plan.py"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("remotion_plan", HERE / "remotion_plan.py")
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
    def test_valid_plan(self):
        self.assertEqual(REMOTION.validate(plan()), [])

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
            self.assertIn("npm install", (output / "README.md").read_text("utf-8"))
            with self.assertRaises(ValueError):
                REMOTION.scaffold(plan(), output)


if __name__ == "__main__":
    unittest.main()
