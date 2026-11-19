"""Local panorama, layer separation, free composition, stitch and history visibility."""
import io
import unittest

from PIL import Image

from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_image_ops import (
    PANORAMA_HD_HEIGHT,
    PANORAMA_HD_WIDTH,
    _render_equirect_perspective,
    _render_equirect_perspective_mesh,
    capture_panorama_views,
    compose_image_layers,
    hidden_job_ids,
    normalize_layer_selections,
    panorama_view_specs,
    separate_image_layers,
    stitch_images,
)


def _png(width, height, color, marks=()):
    image = Image.new("RGB", (width, height), color)
    draw = None
    for box, fill in marks:
        if draw is None:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
        draw.rectangle(box, fill=fill)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pixel(content, x, y):
    with Image.open(io.BytesIO(content)) as image:
        return image.convert("RGBA").getpixel((x, y))


class CanvasPortLayerGroupTests(unittest.TestCase):
    def test_panorama_views_are_relative_to_the_current_heading(self):
        four = panorama_view_specs("four", 15, 8)
        self.assertEqual([round(item[3]) for item in four], [0, 180, -90, 90])
        self.assertEqual([round(item[0] - 15) for item in four], [0, 180, -90, 90])
        self.assertTrue(all(item[1] == 8 for item in four))
        self.assertIn("0°", four[0][2])
        self.assertIn("180°", four[1][2])
        self.assertIn("-90°", four[2][2])
        self.assertIn("+90°", four[3][2])
        twelve = panorama_view_specs("twelve", 15, -4)
        self.assertEqual(len(twelve), 12)
        self.assertEqual([item[0] for item in twelve], [15 + index * 30 for index in range(12)])
        self.assertTrue(all(item[1] == -4 for item in twelve))
        current = panorama_view_specs("current", 20, 5)
        self.assertEqual(current, [(20, 5, "全景当前截图", 0.0)])

    def test_panorama_capture_defaults_to_hd_and_matches_the_center_sample(self):
        source = _png(64, 32, (220, 20, 20), [((16, 0, 48, 31), (0, 180, 40))])
        small = capture_panorama_views(source, mode="current", yaw_deg=0, pitch_deg=0, fov_deg=75, out_width=32, out_height=18)
        self.assertEqual((small[0]["width"], small[0]["height"]), (32, 18))
        center = _pixel(small[0]["bytes"], 16, 9)
        self.assertGreater(center[1], center[0])
        self.assertGreater(center[1], center[2])
        slow = _render_equirect_perspective(Image.open(io.BytesIO(source)).convert("RGB"), 0, 0, 75, 32, 18)
        mesh = _render_equirect_perspective_mesh(Image.open(io.BytesIO(source)).convert("RGB"), 0, 0, 75, 32, 18)
        slow_px, mesh_px = _pixel(slow, 16, 9), _pixel(mesh, 16, 9)
        self.assertLess(abs(slow_px[1] - mesh_px[1]), 40)
        hd = capture_panorama_views(source, mode="four", yaw_deg=10, pitch_deg=3, fov_deg=75)
        self.assertEqual(len(hd), 4)
        self.assertTrue(all(item["width"] >= 1280 and item["height"] >= 720 for item in hd))
        self.assertEqual((hd[0]["width"], hd[0]["height"]), (PANORAMA_HD_WIDTH, PANORAMA_HD_HEIGHT))
        self.assertEqual(hd[2]["offset"], -90.0)
        self.assertAlmostEqual(hd[2]["yaw"], -80.0)

    def test_layer_separation_limits_boxes_and_writes_transparent_pngs(self):
        source = _png(40, 40, (0, 0, 200), [((8, 8, 24, 24), (220, 0, 0))])
        with self.assertRaises(ResourceError):
            normalize_layer_selections([{"id": "a%s" % index, "description": "", "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}} for index in range(17)])
        produced = separate_image_layers(source, [{"id": "hero", "description": "红块", "bbox": [0.2, 0.2, 0.4, 0.4]}])
        self.assertEqual(produced["snapshot"]["kind"], "layer_separation")
        self.assertEqual(produced["snapshot"]["credits"], 0)
        self.assertEqual(produced["snapshot"]["foreground_count"], 1)
        outside = _pixel(produced["foregrounds"][0]["bytes"], 1, 1)
        inside = _pixel(produced["foregrounds"][0]["bytes"], 16, 16)
        self.assertEqual(outside[3], 0)
        self.assertEqual(inside[3], 255)
        self.assertGreater(inside[0], inside[2])
        background = _pixel(produced["background"]["bytes"], 16, 16)
        self.assertLess(background[0], 180)

    def test_free_composition_skips_hidden_layers_and_stitch_builds_real_images(self):
        red = _png(8, 8, (200, 0, 0))
        blue = _png(8, 8, (0, 0, 200))
        merged = compose_image_layers([
            {"bytes": red, "x": 0, "y": 0, "scale": 1, "z": 0, "visible": True},
            {"bytes": blue, "x": 8, "y": 0, "scale": 1, "z": 1, "visible": False},
        ])
        with Image.open(io.BytesIO(merged)) as image:
            self.assertEqual(image.size, (8, 8))
            self.assertGreater(image.convert("RGBA").getpixel((1, 1))[0], 150)
        scaled = compose_image_layers([{"bytes": red, "x": 0, "y": 0, "scale": 2, "z": 0, "visible": True}], width=20, height=20)
        with Image.open(io.BytesIO(scaled)) as image:
            self.assertEqual(image.size, (20, 20))
        long_image = stitch_images([red, blue], mode="long")
        with Image.open(io.BytesIO(long_image)) as image:
            self.assertEqual(image.size[1], 8)
            self.assertGreaterEqual(image.size[0], 16)
        grid = stitch_images([red, blue, red, blue], mode="grid")
        with Image.open(io.BytesIO(grid)) as image:
            self.assertEqual(image.size, (16, 16))

    def test_hidden_history_keeps_the_latest_flag(self):
        events = [
            {"job_id": "a", "evidence": {"hidden": True}},
            {"job_id": "b", "evidence": {"hidden": True}},
            {"job_id": "a", "evidence": {"hidden": False}},
        ]
        self.assertEqual(hidden_job_ids(events), {"b"})


if __name__ == "__main__":
    unittest.main()
