"""Table-driven render-plan validation; no render or external tools."""
import unittest

from _paths import SCRIPTS  # noqa: F401
import remotion_plan
from support.plans import remotion_plan as plan


class InvalidRenderPlans(unittest.TestCase):
    def test_invalid_plan_matrix(self):
        cases = []
        value = plan()
        value["segments"][0].update(source_in_frame=5, handle_in_frames=6, handle_out_frames=10, source_duration_in_frames=190)
        cases.append(("source_handles", value, ("handle_in_frames", "尾手柄")))
        value = plan()
        value["segments"][1].update(volume=2, audio_fade_out_frames=181,
            volume_keyframes=[{"frame": 120, "volume": 1}, {"frame": 0, "volume": 0.2}, {"frame": 180, "volume": 0.2}])
        cases.append(("audio_envelope", value, (".volume ", "audio_fade_out_frames", "帧必须递增")))
        cases.append(("non_object", [], ()))
        value = plan()
        value["composition"].update(duration_in_frames="bad", fps={"numerator": 30, "denominator": 0})
        cases.append(("malformed_numbers", value, ()))
        value = plan()
        value["segments"][0].pop("source_shot_id")
        value["segments"][1]["source"] = "../secret.mp3"
        cases.append(("unsafe_source", value, ("source_shot_id", "安全相对路径")))
        for name, value, expected in cases:
            with self.subTest(case=name):
                errors = remotion_plan.validate(value)
                self.assertTrue(errors)
                for text in expected:
                    self.assertTrue(any(text in error for error in errors), (name, text, errors))


if __name__ == "__main__":
    unittest.main()
