"""Table-driven render-plan validation; no render or external tools."""
import copy
import unittest

import vsc.post.remotion_plan as remotion_plan
from support.fixtures.plans import remotion_plan as plan


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


class CaptionPositionEdits(unittest.TestCase):
    def document(self):
        value = plan()
        caption = next(s for s in value["segments"] if s["kind"] == "caption")
        caption["id"] = "selected-caption"
        return {"format": "vsc.timeline/v1", "bindings": {"fixed_media": "media-v1"}, "render_plan": value}

    def test_one_caption_edit_preserves_every_other_fact_and_returns_range_mapping(self):
        document = self.document()
        original = copy.deepcopy(document)
        selected = next(s for s in document["render_plan"]["segments"] if s["id"] == "selected-caption")
        bounds = {key: selected[key] for key in ("from_frame", "duration_in_frames")}
        layout = {"position": "custom", "custom_position": 35}
        result = remotion_plan.edit_caption_position(document, caption_id="selected-caption",
            expected_sha256=remotion_plan.document_sha256(document), layout=layout, frame_range=bounds)
        expected = copy.deepcopy(original)
        next(s for s in expected["render_plan"]["segments"] if s["id"] == "selected-caption")["subtitle_style"] = layout
        self.assertEqual(result["document"], expected)
        self.assertEqual(document, original)
        self.assertEqual(result["diff"]["old_range"], bounds)
        self.assertEqual(result["diff"]["new_range"], bounds)
        self.assertEqual(result["diff"]["before"], {"position": "bottom"})
        self.assertEqual(result["diff"]["after"], layout)
        self.assertNotEqual(result["source_sha256"], result["result_sha256"])
        self.assertEqual(remotion_plan.validate(result["document"]), [])

    def test_old_references_partial_ranges_unknown_fields_and_out_of_bounds_fail(self):
        document = self.document()
        sha = remotion_plan.document_sha256(document)
        for layout in (None, {}, [], {"position": "left"}, {"position": "custom"},
                       {"position": "custom", "custom_position": True},
                       {"position": "custom", "custom_position": float("nan")},
                       {"position": "custom", "custom_position": -1},
                       {"position": "custom", "custom_position": 101},
                       {"position": "top", "text": "不能改台词"}, {"position": "top", "from_frame": 0},
                       {"position": "top", "font_size": 100}, {"position": "top", "custom_position": 20}):
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                remotion_plan.edit_caption_position(document, caption_id="selected-caption", expected_sha256=sha, layout=layout)
        for selection in ("missing", document["render_plan"]["segments"][0]["id"]):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                remotion_plan.edit_caption_position(document, caption_id=selection, expected_sha256=sha, layout={"position": "top"})
        for bounds in ({"from_frame": 0, "duration_in_frames": 1}, {"from_frame": -1, "duration_in_frames": 1},
                       {"from_frame": True, "duration_in_frames": 1}, {"from_frame": 0}, {"extra": 1}, []):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                remotion_plan.edit_caption_position(document, caption_id="selected-caption", expected_sha256=sha,
                    layout={"position": "top"}, frame_range=bounds)
        document["bindings"]["fixed_media"] = "new-media-reference"
        with self.assertRaisesRegex(ValueError, "摘要已改变"):
            remotion_plan.edit_caption_position(document, caption_id="selected-caption", expected_sha256=sha, layout={"position": "top"})

    def test_segment_layout_is_strict_and_cannot_attach_to_media(self):
        for index, layout in ((0, {"position": "top"}), (2, None), (2, {"font_size": 48})):
            value = self.document()["render_plan"]
            # Use the actual caption index rather than relying on fixture ordering.
            if index == 2:
                index = next(i for i, s in enumerate(value["segments"]) if s["kind"] == "caption")
            value["segments"][index]["subtitle_style"] = layout
            self.assertTrue(remotion_plan.validate(value))


if __name__ == "__main__":
    unittest.main()
