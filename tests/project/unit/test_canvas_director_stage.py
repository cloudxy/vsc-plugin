"""Director stage document, panorama sync and local reference-video constraints."""
import base64
import io
import json
import shutil
import unittest

from PIL import Image

from vsc.assets.canvas_director_stage import (
    BODY_PRESETS, CAMERA_PRESETS, IDENTITY_APPLIED, IDENTITY_STALE, JOINT_AXES, PALETTE, POSE_PRESETS, PRIMITIVES,
    apply_identity_colors, auto_frame, clamp_crowd, clamp_fov, default_preview, default_stage, dump_json,
    encode_reference_video, expand_frames, group_objects, hex_to_rgb, linked_panorama_blocked, load_stage,
    mark_identity_stale, rgb_to_hsl, ungroup_objects,
)
from vsc.assets.creative_canvas import accepts_port, normalize_document
from vsc.assets.resource_service import ResourceError


def _png_b64(color=(20, 40, 200)):
    image = Image.new("RGB", (8, 8), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class CanvasDirectorStageTests(unittest.TestCase):
    def test_catalog_and_default_documents(self):
        self.assertEqual(len(BODY_PRESETS), 8)
        self.assertEqual(BODY_PRESETS[0]["id"], "male_basic")
        self.assertEqual(len(POSE_PRESETS), 21)
        self.assertEqual([item[0] for item in PRIMITIVES], ["cube", "sphere", "cylinder", "cone", "pyramid", "torus"])
        self.assertEqual(len(CAMERA_PRESETS), 14)
        self.assertEqual([item["id"] for item in CAMERA_PRESETS if item["id"] == "dutch"][0], "dutch")
        self.assertEqual(len(JOINT_AXES), 25)
        self.assertEqual(PALETTE[0], "#829BB5")
        stage = default_stage()
        self.assertEqual(stage["cameras"][0]["id"], "cam-front-medium")
        self.assertEqual(stage["cameras"][0]["preset"], "front_medium")
        self.assertEqual(stage["cameras"][0]["fov"], 50)
        self.assertEqual(stage["panorama"]["radius"], 60)
        preview = default_preview("preview-1")
        self.assertEqual(preview["documentRef"], {"documentId": "preview-1", "revision": 1, "schemaVersion": 1})
        self.assertEqual(preview["timelineSummary"], {"durationSeconds": 15, "shotCount": 1})
        self.assertEqual(clamp_fov(10), 15)
        self.assertEqual(clamp_fov(120), 90)
        self.assertEqual(clamp_crowd(0, 99, 0.1), {"rows": 1, "columns": 40, "spacing": 0.2})
        self.assertEqual(hex_to_rgb("#829BB5"), {"r": 130, "g": 155, "b": 181})
        hsl = rgb_to_hsl(130, 155, 181)
        self.assertGreater(hsl["h"], 0)
        loaded = load_stage(dump_json({"schemaVersion": 1, "cameras": [{"id": "cam-dutch", "preset": "dutch", "name": "荷兰角"}]}))
        self.assertEqual(loaded["cameras"][0]["roll"], 12)

    def test_normalize_seeds_nodes_and_syncs_panorama(self):
        self.assertTrue(accepts_port("director-stage", "panorama_image", "image"))
        self.assertFalse(accepts_port("director-stage", "panorama_image", "video"))
        self.assertTrue(accepts_port("image", "directorStageCapture", "director-stage"))
        self.assertTrue(accepts_port("image", "directorStageCapture", "director"))
        self.assertFalse(accepts_port("video", "directorStageCapture", "director-stage"))
        created = normalize_document({"nodes": [
            {"id": "stage-1", "type": "director-stage", "title": "导演台", "x": 0, "y": 0, "text": ""},
            {"id": "preview-1", "type": "3d-preview", "title": "3D预演", "x": 20, "y": 0, "text": ""},
            {"id": "img-1", "type": "image", "title": "全景", "x": 40, "y": 0, "text": ""},
        ], "edges": [{"id": "edge-1", "source": "img-1", "target": "stage-1", "port": "panorama_image"}]})
        stage = json.loads(next(node["text"] for node in created["nodes"] if node["id"] == "stage-1"))
        preview = json.loads(next(node["text"] for node in created["nodes"] if node["id"] == "preview-1"))
        self.assertEqual(stage["panorama"]["sourceType"], "linked")
        self.assertEqual(stage["panorama"]["linkedNodeId"], "img-1")
        self.assertEqual(stage["panorama"]["origin"], "linked")
        self.assertEqual(stage["panorama"]["radius"], 60)
        self.assertEqual(preview["documentRef"]["schemaVersion"], 1)
        self.assertEqual(preview["timelineSummary"]["durationSeconds"], 15)
        stage["panorama"]["origin"] = "image_to_panorama"
        kept = normalize_document({"nodes": [
            {"id": "stage-1", "type": "director-stage", "title": "导演台", "x": 0, "y": 0, "text": dump_json(stage)},
            {"id": "img-1", "type": "image", "title": "全景", "x": 40, "y": 0, "text": ""},
        ], "edges": [{"id": "edge-1", "source": "img-1", "target": "stage-1", "port": "panorama_image"}]})
        kept_stage = json.loads(kept["nodes"][0]["text"])
        self.assertEqual(kept_stage["panorama"]["origin"], "image_to_panorama")
        self.assertEqual(kept_stage["panorama"]["sourceType"], "linked")
        cleared = normalize_document({"nodes": kept["nodes"], "edges": []})
        cleared_stage = json.loads(next(node["text"] for node in cleared["nodes"] if node["id"] == "stage-1"))
        self.assertEqual(cleared_stage["panorama"]["sourceType"], "none")
        self.assertEqual(cleared_stage["panorama"]["radius"], 60)
        self.assertTrue(linked_panorama_blocked(stage, "stage-1", "img-1", [{"target": "stage-1", "source": "img-1", "port": "panorama_image"}]))
        with self.assertRaises(ResourceError) as raised:
            normalize_document({"nodes": [
                {"id": "stage-1", "type": "director-stage", "title": "导演台", "x": 0, "y": 0, "text": "", "media_id": "media-1"},
            ], "edges": []})
        self.assertEqual(raised.exception.code, "invalid_director_stage")
        with self.assertRaises(ResourceError):
            normalize_document({"nodes": [
                {"id": "stage-1", "type": "director-stage", "title": "导演台", "x": 0, "y": 0, "text": ""},
                {"id": "img-1", "type": "image", "title": "甲", "x": 1, "y": 0, "text": ""},
                {"id": "img-2", "type": "image", "title": "乙", "x": 2, "y": 0, "text": ""},
            ], "edges": [
                {"id": "edge-1", "source": "img-1", "target": "stage-1", "port": "panorama_image"},
                {"id": "edge-2", "source": "img-2", "target": "stage-1", "port": "panorama_image"},
            ]})

    def test_identity_grouping_and_framing_keep_screenshots(self):
        stage = load_stage(dump_json({
            "schemaVersion": 1,
            "objects": [
                {"id": "hero", "kind": "character", "name": "主角", "transform": {"position": [0, 0, 0]}},
                {"id": "extra", "kind": "prop", "name": "道具", "transform": {"position": [2, 0, 0]}},
            ],
            "cameras": [{
                "id": "cam-front-medium", "preset": "front_medium", "name": "正面中景",
                "screenshots": [{"id": "rec-1", "mediaId": "media-shot", "label": "当前视角1", "mode": "current"}],
            }],
        }))
        before = json.dumps(stage["cameras"][0]["screenshots"], ensure_ascii=False)
        updated, message = apply_identity_colors(stage)
        self.assertEqual(message, IDENTITY_APPLIED)
        self.assertEqual(json.dumps(updated["cameras"][0]["screenshots"], ensure_ascii=False), before)
        self.assertEqual(updated["objects"][0]["identity"]["markerColor"], "#829BB5")
        self.assertEqual(updated["objects"][0]["identity"]["colorCode"], "01")
        self.assertFalse(updated["identityStale"])
        updated["objects"].append({"id": "new-prop", "kind": "prop", "name": "新道具", "semanticRole": "prop", "transform": {"position": [0, 0, 0]}})
        mark_identity_stale(updated)
        self.assertTrue(updated["identityStale"])
        self.assertEqual(IDENTITY_STALE, "场景已变化，请重新应用身份配色。")
        group_objects(updated, ["hero", "extra"], "group-1")
        self.assertEqual(updated["objects"][0]["groupId"], "group-1")
        ungroup_objects(updated, "group-1")
        self.assertIsNone(updated["objects"][0]["groupId"])
        framed = auto_frame(updated, "cam-front-medium", ["hero"], ["extra"], "relationship")
        self.assertEqual(framed["framing"]["scope"], "relationship")
        self.assertEqual(framed["framing"]["subjectIds"], ["hero"])
        self.assertIn("extra", framed["framing"]["contextIds"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg")
    def test_reference_video_meets_local_constraints(self):
        encoded, meta = encode_reference_video(expand_frames([_png_b64()], 24))
        self.assertLessEqual(len(encoded), 8 * 1024 * 1024)
        self.assertGreater(meta["duration_seconds"], 0)
        self.assertLessEqual(meta["duration_seconds"], 15)
        self.assertLessEqual(max(meta["width"], meta["height"]), 960)
        self.assertLess(abs(meta["fps"] - 24), 0.2)
        self.assertTrue(encoded[4:8] == b"ftyp")
