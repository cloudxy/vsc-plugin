"""Local pixel tools: filter aliases, doodle shapes, masks and storyboard fields."""
from __future__ import annotations
import io
import json
from types import SimpleNamespace
import unittest

from PIL import Image

from vsc.assets.resource_service import ResourceError
from vsc.assets.creative_canvas import CreativeCanvasService, canvas_image_tool_options
from vsc.production.canvas_image_ops import (
    build_grid_storyboard_node_fields, color_adjust_image_bytes, doodle_overlay_image_bytes,
    mask_image_bytes, resolve_filter_id,
)
from vsc.production.image_tools import TOOLS, normalize_tool


LOCALE_FILTERS = (
    "autumn", "black_gold", "bw", "bw_hard", "comic", "cool_white", "cream", "cyber", "faded",
    "forest", "green_film", "instant", "jp_fresh", "moody", "natural", "night", "none", "sepia",
    "teal_orange", "vivid", "warm_film",
)


def png(size=(80, 40), color=(180, 40, 40, 255)):
    data = io.BytesIO()
    Image.new("RGBA", size, color).save(data, format="PNG")
    return data.getvalue()


def pixel(data, x, y):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA").getpixel((x, y))


class CanvasImageToolsParityTests(unittest.TestCase):
    def test_locale_filters_resolve_to_existing_pixel_presets(self):
        source = png()
        original = color_adjust_image_bytes(source, filter_id="original")
        self.assertEqual(color_adjust_image_bytes(source, filter_id="none"), original)
        self.assertNotEqual(color_adjust_image_bytes(source, filter_id="vivid"), original)
        self.assertEqual(resolve_filter_id("none"), "original")
        self.assertEqual(resolve_filter_id("natural"), "natural_enhance")
        self.assertEqual(resolve_filter_id("bright"), "vivid")
        self.assertEqual(resolve_filter_id("warm"), "warm_film")
        self.assertEqual(resolve_filter_id("cool"), "cool_clear")
        self.assertEqual(resolve_filter_id("cool_white"), "cool_clear")
        self.assertEqual(resolve_filter_id("warm_film"), "warm_film")
        for filter_id in LOCALE_FILTERS:
            self.assertIn(resolve_filter_id(filter_id), {
                "original", "natural_enhance", "vivid", "anime_crisp", "teal_orange", "cinema_dark",
                "black_gold", "cyberpunk", "warm_film", "cyan_film", "vintage_fade", "polaroid",
                "jp_fresh", "cream_sun", "cool_clear", "classic_bw", "high_contrast_bw", "sepia_retro",
                "night_blue", "forest", "autumn_orange",
            })
        with self.assertRaises(ResourceError) as caught:
            resolve_filter_id("not-a-filter")
        self.assertEqual(caught.exception.code, "invalid_canvas_color_adjust")

    def test_doodle_shapes_and_mask_pixels(self):
        source = png()
        brush = {"color": "#ffffff", "width": 20, "points": [[0.5, 0.5]]}
        painted = doodle_overlay_image_bytes(source, [brush])
        self.assertEqual(pixel(painted, 40, 20), (255, 255, 255, 255))
        arrow = {"tool": "arrow", "color": "#ff0000", "width": 4, "points": [[0.1, 0.5], [0.9, 0.5]]}
        self.assertEqual(pixel(doodle_overlay_image_bytes(source, [arrow]), 40, 20), (255, 0, 0, 255))
        rect = {"tool": "rect", "color": "#0000ff", "width": 4, "points": [[0.1, 0.25], [0.9, 0.75]]}
        self.assertEqual(pixel(doodle_overlay_image_bytes(source, [rect]), 40, 10)[:3], (0, 0, 255))
        text = doodle_overlay_image_bytes(source, [{"tool": "text", "color": "#ffffff", "width": 12, "points": [[0.05, 0.2]], "text": "A"}])
        self.assertNotEqual(text, source)
        erased = doodle_overlay_image_bytes(source, [brush, {"tool": "eraser", "color": "#000000", "width": 20, "points": [[0.5, 0.5]]}])
        self.assertEqual(pixel(erased, 40, 20), pixel(source, 40, 20))
        mask = mask_image_bytes(source, [brush])
        self.assertEqual(pixel(mask, 40, 20), (255, 255, 255, 255))
        self.assertEqual(pixel(mask, 0, 0), (0, 0, 0, 255))
        with self.assertRaises(ResourceError):
            mask_image_bytes(source, [])

    def test_storyboard_node_fields_and_service_whitelist(self):
        fields = build_grid_storyboard_node_fields({"row": 2, "column": 3}, 1, 8, 8, "人物原图 · 分镜组")
        self.assertEqual(fields["title"], "宫格切片 1")
        self.assertEqual(fields["group"], "人物原图 · 分镜组")
        self.assertEqual(fields["text"], "")
        raw = fields["params"]["grid_storyboard_group"]
        self.assertLessEqual(len(raw), 2000)
        payload = json.loads(raw)
        self.assertEqual(payload["kind"], "grid_storyboard_group")
        self.assertEqual(payload["index"], 1)
        self.assertEqual(payload["row"], 2)
        self.assertEqual(payload["column"], 3)
        self.assertEqual(build_grid_storyboard_node_fields({"row": 1, "column": 1}, 2, 2, 2, "")["group"], "宫格分镜组")
        store = SimpleNamespace(calls=[])

        def split_canvas_image(project_id, body, **kwargs):
            store.calls.append(("split", project_id, body["storyboard_group"]))
            return {"ok": True}

        def transform_canvas_image(project_id, body, **kwargs):
            store.calls.append(("transform", body["operation"]))
            return {"ok": True}

        dummy = SimpleNamespace(store=SimpleNamespace(split_canvas_image=split_canvas_image, transform_canvas_image=transform_canvas_image), _validate_write=lambda body, **kwargs: None)
        grid = {"canvas_id": "canvas-1", "canvas_revision": 1, "node_id": "img-1", "rows": 2, "columns": 2, "cells": [{"row": 1, "column": 1}], "group_name": "人物原图 · 分镜组", "storyboard_group": True}
        CreativeCanvasService.split_canvas_image(dummy, "project-1", grid, actor="actor", expected_revision=0, idempotency_key="grid-1")
        self.assertEqual(store.calls, [("split", "project-1", True)])
        with self.assertRaises(ResourceError) as caught:
            CreativeCanvasService.split_canvas_image(dummy, "project-1", {**grid, "storyboard_group": "true"}, actor="actor", expected_revision=0, idempotency_key="grid-2")
        self.assertEqual(caught.exception.code, "invalid_canvas_grid")
        self.assertEqual(len(store.calls), 1)
        mask = {"canvas_id": "canvas-1", "canvas_revision": 1, "node_id": "img-1", "operation": "mask", "settings": {"strokes": [{"tool": "brush", "color": "#ffffff", "width": 8, "points": [[0.2, 0.2], [0.4, 0.4]]}]}}
        CreativeCanvasService.transform_canvas_image(dummy, "project-1", mask, actor="actor", expected_revision=0, idempotency_key="mask-1")
        self.assertEqual(store.calls[-1], ("transform", "mask"))
        with self.assertRaises(ResourceError) as rejected:
            CreativeCanvasService.transform_canvas_image(dummy, "project-1", {**mask, "operation": "paint"}, actor="actor", expected_revision=0, idempotency_key="mask-2")
        self.assertEqual(rejected.exception.code, "invalid_canvas_transform")

    def test_tool_settings_keep_lighting_defaults_and_accept_reference_fields(self):
        self.assertEqual(TOOLS["lighting"][1]["intensity"], 1)
        self.assertEqual(TOOLS["lighting"][1]["view"], "front")
        options = canvas_image_tool_options()
        self.assertEqual(options["lighting"]["intensity"], 0.5)
        self.assertEqual(options["lighting"]["view"], "perspective")
        self.assertEqual(TOOLS["lighting"][1]["intensity"], 1)
        lighting = normalize_tool("lighting", {"direction": "left_top_front", "direction_x": -1, "direction_y": 1, "direction_z": 1, "brightness": 1.5, "description": "主光"})
        self.assertEqual(lighting["direction"], "left_top_front")
        self.assertEqual(lighting["brightness"], 1.5)
        texture = normalize_tool("texture", {"scene_blend": "深度融合", "light_match": "氛围强化", "skin_polish": "真实肌理", "grain": "颗粒质感", "sharpness": "高清锐化", "quality": "高画质"})
        self.assertEqual(texture["scene_blend"], "deep")
        self.assertEqual(texture["light_match"], "dramatic")
        self.assertEqual(texture["skin_polish"], "micro")
        self.assertEqual(texture["grain"], "film_grain")
        self.assertEqual(texture["sharpness"], "hd_sharp")
        self.assertEqual(texture["quality"], "high")
        emotion = normalize_tool("expression", {"emotion": "e03_03", "emotion_x": 50, "emotion_y": 50, "quality": "标准画质"})
        self.assertEqual(emotion["emotion"], "e03_03")
        self.assertEqual(emotion["quality"], "medium")
        with self.assertRaises(ResourceError):
            normalize_tool("expression", {"emotion": "e99_99"})
        outpaint = normalize_tool("outpaint", {"source_width": 0, "source_height": 0, "rect_x": -0.3889, "rect_y": 0, "rect_w": 1.7778, "rect_h": 1, "padding": 0.3889, "ratio": "16:9"})
        self.assertEqual(outpaint["source_width"], 0)
        self.assertEqual(outpaint["rect_w"], 1.7778)
        with self.assertRaises(ResourceError):
            normalize_tool("outpaint", {"source_width": -1})
        angle = normalize_tool("angle", {"preset": "frontBottom", "scale": "close", "zoom": 2})
        self.assertEqual(angle["preset"], "frontBottom")
        self.assertEqual(angle["scale"], "close")
        self.assertTrue(angle["include_instructions"])
        with self.assertRaises(ResourceError):
            normalize_tool("angle", {"preset": "nope"})
