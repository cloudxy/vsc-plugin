"""Real PostgreSQL + FastAPI integration tests for 0.47.43 Canvas Core & AI MV/Audio runtime."""
import importlib.util
import io
import json
import math
import os
import struct
import tempfile
import unittest
import uuid
import wave

from PIL import Image

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS = all(
    importlib.util.find_spec(name)
    for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx")
)
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


def _make_png_bytes(width=120, height=80, *, base_rgb=(40, 90, 160)):
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (base_rgb[0] + x * 2) % 256,
                (base_rgb[1] + y * 3) % 256,
                (base_rgb[2] + x + y) % 256,
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_wav_bytes(duration_ms=250, sample_rate=16000):
    frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        samples = [
            int(8000 * math.sin(2.0 * math.pi * 440.0 * idx / sample_rate))
            for idx in range(frames)
        ]
        wav_file.writeframes(struct.pack("<" + "h" * frames, *samples))
    return buf.getvalue()


@unittest.skipUnless(
    TEST_URL and HAS_DEPS,
    "requires configured isolated PostgreSQL and web dependencies",
)
class CanvasCoreReplicaIntegrationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.directory = tempfile.TemporaryDirectory(prefix="vsc-canvas-core-")
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.client = TestClient(
            create_app(
                {
                    "projects_root": self.directory.name + "/projects",
                    "media_root": self.directory.name,
                    "allowed_hosts": ["testserver"],
                    "allowed_origins": ["http://testserver"],
                    "human_identity": "test-human",
                    "access_token": "test-token",
                },
                service=self.service,
            )
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post(
            "/api/v1/session",
            headers={"Origin": "http://testserver"},
            json={"token": "test-token"},
        ).json()
        self.headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": session["csrf_token"],
        }
        self.base = "/api/v1/projects/" + self.p

    def command(self, path, payload, method="POST", expected=None, key=None, base=None):
        target_base = base or self.base
        response = self.client.request(
            method,
            target_base + path,
            headers=self.headers,
            json={
                "payload": payload,
                "expected_revision": self.rev if expected is None else expected,
                "idempotency_key": key or uuid.uuid4().hex,
            },
        )
        if response.status_code == 200 and target_base == self.base and "revision" in response.json():
            self.rev = response.json()["revision"]
        return response

    def upload_media(self, content_bytes, filename, name, *, rights="owned", purposes=None):
        staged = self.client.post(
            self.base + "/uploads",
            content=content_bytes,
            headers={**self.headers, "X-Filename": filename},
        )
        self.assertEqual(staged.status_code, 200, staged.text)
        registered = self.command(
            "/media",
            {
                "staged_upload": staged.json()["staged_upload"],
                "name": name,
                "rights": rights,
                "rights_scope": {"purposes": purposes if purposes is not None else ["*"]},
                "source": {"kind": "synthetic-owned", "content": "Canvas core replica fixture"},
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        return registered.json()["id"]

    def test_local_image_transforms_lineage_and_grid_parent_rights(self):
        png = _make_png_bytes(120, 80)
        media_id = self.upload_media(png, "source.png", "原始画布图片")
        created = self.command(
            "/creative-canvases",
            {
                "title": "本地图片编辑画布",
                "document": {
                    "nodes": [
                        {
                            "id": "img-1",
                            "type": "image",
                            "title": "主视角原图",
                            "x": 100,
                            "y": 120,
                            "media_id": media_id,
                        }
                    ],
                    "edges": [],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id

        # 1. Crop -> creates derived transform-* node + derived_from edge + 60x40 PNG
        cropped = self.command(
            path + "/transform-image",
            {
                "canvas_revision": 1,
                "node_id": "img-1",
                "operation": "crop",
                "settings": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "ratio": "free"},
                "in_place": False,
                "group_name": "镜头A组",
            },
        )
        self.assertEqual(cropped.status_code, 200, cropped.text)
        crop_body = cropped.json()
        self.assertEqual(len(crop_body["node_ids"]), 1)
        crop_node_id = crop_body["node_ids"][0]
        self.assertTrue(crop_node_id.startswith("transform-"))
        crop_media_id = crop_body["media_ids"][0]
        with Image.open(io.BytesIO(self.client.get(f"{self.base}/media/{crop_media_id}/content").content)) as out_img:
            self.assertEqual(out_img.size, (60, 40))

        # 2. Rotate 90 deg + flip_x -> 80x120 PNG
        rotated = self.command(
            path + "/transform-image",
            {
                "canvas_revision": crop_body["canvas_revision"],
                "node_id": "img-1",
                "operation": "rotate",
                "settings": {"degrees": 90, "flip_x": True, "flip_y": False},
                "in_place": False,
            },
        )
        self.assertEqual(rotated.status_code, 200, rotated.text)
        rot_body = rotated.json()
        rot_media_id = rot_body["media_ids"][0]
        with Image.open(io.BytesIO(self.client.get(f"{self.base}/media/{rot_media_id}/content").content)) as out_img:
            self.assertEqual(out_img.size, (80, 120))

        # 3. Color adjust with warm_film filter + HSL
        colored = self.command(
            path + "/transform-image",
            {
                "canvas_revision": rot_body["canvas_revision"],
                "node_id": "img-1",
                "operation": "color_adjust",
                "settings": {
                    "filter_id": "warm_film",
                    "strength": 85,
                    "hue": 12,
                    "saturation": 20,
                    "brightness": 10,
                    "contrast": 15,
                },
                "in_place": False,
            },
        )
        self.assertEqual(colored.status_code, 200, colored.text)
        col_body = colored.json()
        self.assertNotEqual(col_body["media_ids"][0], media_id)

        # 4. Doodle in_place=True -> updates crop_node_id media_id without adding extra node
        doodled = self.command(
            path + "/transform-image",
            {
                "canvas_revision": col_body["canvas_revision"],
                "node_id": crop_node_id,
                "operation": "doodle",
                "settings": {
                    "strokes": [
                        {
                            "color": "#ff2200",
                            "width": 8,
                            "points": [[0.1, 0.1], [0.5, 0.5], [0.85, 0.75]],
                        }
                    ]
                },
                "in_place": True,
            },
        )
        self.assertEqual(doodled.status_code, 200, doodled.text)
        doodle_body = doodled.json()
        self.assertEqual(doodle_body["node_ids"], [crop_node_id])

        reopened = self.client.get(self.base + path).json()
        self.assertEqual(len(reopened["document"]["nodes"]), 4)
        derived_edges = [e for e in reopened["document"]["edges"] if e["port"] == "derived_from"]
        self.assertEqual(len(derived_edges), 3)

        # 5. Split grid & verify _grid_parent source rights enforcement
        split = self.command(
            path + "/split-image",
            {
                "canvas_revision": doodle_body["canvas_revision"],
                "node_id": "img-1",
                "rows": 2,
                "columns": 2,
                "cells": [{"row": 1, "column": 1}],
                "group_name": "九宫切分",
            },
        )
        self.assertEqual(split.status_code, 200, split.text)
        tile_media_id = split.json()["media_ids"][0]

        # Restrict original parent media rights so image_edit is no longer allowed
        restricted = self.service.decide_rights(
            self.p,
            {
                "media_id": media_id,
                "outcome": "revoked",
                "reason": "收回父图编辑授权",
            },
            actor="test-human",
            expected_revision=self.rev,
            idempotency_key=uuid.uuid4().hex,
        )
        self.rev = restricted["revision"]

        blocked_replace = self.command(
            path + "/replace-media",
            {
                "canvas_revision": split.json()["canvas_revision"],
                "node_id": crop_node_id,
                "media_id": tile_media_id,
            },
        )
        self.assertEqual(blocked_replace.status_code, 422, blocked_replace.text)
        self.assertEqual(blocked_replace.json()["error"], "copy_source_rights_unavailable")

        tile_node_id = split.json()["node_ids"][0]
        blocked_transform = self.command(
            path + "/transform-image",
            {
                "canvas_revision": split.json()["canvas_revision"],
                "node_id": tile_node_id,
                "operation": "rotate",
                "settings": {"degrees": 90, "flip_x": False, "flip_y": False},
                "in_place": False,
            },
        )
        self.assertEqual(blocked_transform.status_code, 422, blocked_transform.text)
        self.assertEqual(blocked_transform.json()["error"], "canvas_image_source_unusable")

    def test_panorama_capture_current_four_and_twelve_views(self):
        pano_png = _make_png_bytes(240, 120, base_rgb=(20, 120, 80))
        pano_media_id = self.upload_media(pano_png, "equirect.png", "720全景源图")
        created = self.command(
            "/creative-canvases",
            {
                "title": "720全景空间画布",
                "document": {
                    "nodes": [
                        {
                            "id": "pano-src",
                            "type": "image",
                            "title": "大厅全景图",
                            "x": 80,
                            "y": 80,
                            "media_id": pano_media_id,
                        }
                    ],
                    "edges": [],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id

        cur = self.command(
            path + "/capture-panorama",
            {
                "canvas_revision": 1,
                "node_id": "pano-src",
                "mode": "current",
                "yaw": 35.0,
                "pitch": -10.0,
                "fov": 75.0,
                "group_name": "全景机位",
            },
        )
        self.assertEqual(cur.status_code, 200, cur.text)
        self.assertEqual(len(cur.json()["node_ids"]), 1)

        four = self.command(
            path + "/capture-panorama",
            {
                "canvas_revision": cur.json()["canvas_revision"],
                "node_id": "pano-src",
                "mode": "four",
                "yaw": 0.0,
                "pitch": 0.0,
                "fov": 80.0,
            },
        )
        self.assertEqual(four.status_code, 200, four.text)
        self.assertEqual(len(four.json()["node_ids"]), 4)

        twelve = self.command(
            path + "/capture-panorama",
            {
                "canvas_revision": four.json()["canvas_revision"],
                "node_id": "pano-src",
                "mode": "twelve",
                "yaw": 15.0,
                "pitch": 5.0,
                "fov": 70.0,
            },
        )
        self.assertEqual(twelve.status_code, 200, twelve.text)
        self.assertEqual(len(twelve.json()["node_ids"]), 12)

        detail = self.client.get(self.base + path).json()
        # 1 source + 1 current + 4 cardinal + 12 full = 18 nodes, 17 derived_from edges
        self.assertEqual(len(detail["document"]["nodes"]), 18)
        self.assertEqual(len(detail["document"]["edges"]), 17)
        sample_media = twelve.json()["media_ids"][0]
        sample_resp = self.client.get(f"{self.base}/media/{sample_media}/content")
        self.assertEqual(sample_resp.status_code, 200)
        with Image.open(io.BytesIO(sample_resp.content)) as view_img:
            self.assertGreaterEqual(view_img.width, 64)
            self.assertGreaterEqual(view_img.height, 64)

    def test_replace_node_media_preserves_edges_and_rejects_mismatched_or_recycled(self):
        img1 = self.upload_media(_make_png_bytes(64, 64, base_rgb=(10, 20, 30)), "a.png", "首帧A")
        img2 = self.upload_media(_make_png_bytes(64, 64, base_rgb=(90, 40, 20)), "b.png", "首帧B")
        img_recycled = self.upload_media(_make_png_bytes(64, 64, base_rgb=(50, 50, 50)), "trash.png", "待回收图")
        wav_id = self.upload_media(_make_wav_bytes(), "bgm.wav", "测试配乐")

        trashed = self.service.recycle_media(
            self.p,
            {"media_ids": [img_recycled], "action": "trash", "reason": "移入回收站测试"},
            actor="test-human",
            expected_revision=self.rev,
            idempotency_key=uuid.uuid4().hex,
        )
        self.rev = trashed["revision"]

        created = self.command(
            "/creative-canvases",
            {
                "title": "素材替换测试画布",
                "document": {
                    "nodes": [
                        {"id": "frame-node", "type": "image", "title": "首帧节点", "media_id": img1},
                        {"id": "video-node", "type": "video", "title": "镜头生成"},
                    ],
                    "edges": [
                        {"id": "e-first", "source": "frame-node", "target": "video-node", "port": "first_frame"}
                    ],
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id

        # Reject modality mismatch (audio media into image node)
        bad_modality = self.command(
            path + "/replace-media",
            {"canvas_revision": 1, "node_id": "frame-node", "media_id": wav_id},
        )
        self.assertEqual(bad_modality.status_code, 422, bad_modality.text)
        self.assertEqual(bad_modality.json()["error"], "canvas_media_type")

        # Reject recycled media (409)
        bad_recycled = self.command(
            path + "/replace-media",
            {"canvas_revision": 1, "node_id": "frame-node", "media_id": img_recycled},
        )
        self.assertEqual(bad_recycled.status_code, 409, bad_recycled.text)
        self.assertEqual(bad_recycled.json()["error"], "canvas_replace_media_recycled")

        # Valid replacement preserves node ID and outgoing first_frame edge
        replaced = self.command(
            path + "/replace-media",
            {"canvas_revision": 1, "node_id": "frame-node", "media_id": img2, "title": "替换后首帧B"},
        )
        self.assertEqual(replaced.status_code, 200, replaced.text)
        reopened = self.client.get(self.base + path).json()
        frame_node = next(n for n in reopened["document"]["nodes"] if n["id"] == "frame-node")
        self.assertEqual(frame_node["media_id"], img2)
        self.assertEqual(frame_node["title"], "替换后首帧B")
        self.assertEqual(len(reopened["document"]["edges"]), 1)
        self.assertEqual(reopened["document"]["edges"][0]["id"], "e-first")

    def test_nineteen_canvas_image_tools_inpaint_mapping_and_clean_spa_routes(self):
        from vsc.production.canvas_execution import draft_logical

        run_opts = self.client.get(self.base + "/creative-canvas-run-options")
        self.assertEqual(run_opts.status_code, 200, run_opts.text)
        tools = run_opts.json()["image_tools"]
        expected_tools = {
            "angle",
            "lighting",
            "three_view",
            "headshot",
            "face_views",
            "texture",
            "expression",
            "panorama",
            "upscale",
            "watermark",
            "inpaint",
            "outpaint",
            "matting",
            "multi_camera_grid_2k",
            "multi_camera_grid_4k",
            "story_four_grid",
            "cinematic_lighting",
            "frame_predict_3s_after",
            "frame_predict_5s_before",
        }
        self.assertEqual(set(tools.keys()), expected_tools)

        created = self.command(
            "/creative-canvases",
            {"title": "19项AI图像工具画布", "document": {"nodes": [], "edges": []}},
        )
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id

        tool_overrides = {
            "texture": {
                "strength": 0.65,
                "scene_blend": "deep",
                "light_match": "dramatic",
                "skin_polish": "micro",
                "grain": "film_grain",
                "sharpness": "hd_sharp",
            },
            "expression": {
                "expression": "惊讶",
                "strength": 0.8,
                "valence": 0.35,
                "arousal": 0.75,
                "brow": 25,
                "eye": 30,
                "mouth": 40,
                "head_tilt": -10,
            },
            "outpaint": {"ratio": "21:9", "padding": 0.5},
            "matting": {"subject": "foreground"},
            "inpaint": {"mask_media_id": "mask-1", "mask_sha256": "a" * 64, "mask_export_id": "exp-1"},
        }
        nodes = []
        for idx, tool_key in enumerate(sorted(expected_tools)):
            cfg = dict(tools[tool_key], **tool_overrides.get(tool_key, {}))
            nodes.append(
                {
                    "id": f"tool-{idx}",
                    "type": "image",
                    "title": f"工具节点 {tool_key}",
                    "x": (idx % 5) * 260,
                    "y": (idx // 5) * 220,
                    "params": {
                        "vsc_image_tool": tool_key,
                        "vsc_image_tool_settings": json.dumps(cfg, ensure_ascii=False),
                    },
                }
            )
        saved = self.command(
            path,
            {"canvas_revision": 1, "title": "19项AI图像工具画布", "document": {"nodes": nodes, "edges": []}},
            method="PUT",
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(len(self.client.get(self.base + path).json()["document"]["nodes"]), 19)

        # Reject invalid fixed-spec override on story_four_grid
        bad_nodes = [
            {
                "id": "bad-fixed",
                "type": "image",
                "params": {
                    "vsc_image_tool": "story_four_grid",
                    "vsc_image_tool_settings": json.dumps({"layout": "3x3"}),
                },
            }
        ]
        rejected = self.command(
            path,
            {"canvas_revision": 2, "title": "非法固定工具规格", "document": {"nodes": bad_nodes, "edges": []}},
            method="PUT",
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(rejected.json()["error"], "invalid_canvas_image_tool")

        # Verify draft_logical compiles operation_source + operation_mask for inpaint without provider submission
        logical = draft_logical(
            {
                "mode": "image_inpaint",
                "shot_id": "shot-demo",
                "purpose": "image_edit",
                "prompt": "将前景水杯替换为古典茶盏",
                "params": {},
                "width": 1280,
                "height": 720,
                "references": [
                    {"role": "operation_source", "media_id": "src-media", "sha256": "b" * 64},
                    {"role": "operation_mask", "media_id": "mask-media", "sha256": "c" * 64},
                ],
            }
        )
        self.assertEqual(logical["operation"], "inpaint")
        self.assertEqual(logical["source_media_id"], "src-media")
        self.assertEqual(logical["mask_media_id"], "mask-media")

        # Verify clean SPA routes & new static worker/editor scripts
        for route in (
            "/canvas",
            f"/canvas?project_id={self.p}&canvas_id={canvas_id}",
            f"/canvas/share?project_id={self.p}&canvas_id={canvas_id}&focus_node_key=tool-0",
            "/static/canvas-media-editors.js",
            "/static/canvas-persistence-worker.js",
        ):
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"{route}: {res.text[:200]}")

    def test_agent_session_state_queue_camera_motions_and_zero_jobs(self):
        created = self.command(
            "/creative-canvases",
            {
                "title": "Agent与运镜模板画布",
                "document": {"nodes": [{"id": "n-text", "type": "text", "text": "雨夜霓虹追逐"}], "edges": []},
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id

        turn = self.command(
            path + "/agent-turns",
            {
                "canvas_revision": 1,
                "message": "拆解三镜头分镜方案",
                "skill_id": "vsc-script",
                "node_ids": ["n-text"],
            },
        )
        self.assertEqual(turn.status_code, 200, turn.text)
        session_id = turn.json()["session_id"]

        # Rename & enable auto_approve
        state_res = self.command(
            f"{path}/agent-sessions/{session_id}/state",
            {"title": "第一集追逐戏导演会话", "auto_approve": True, "archived": False},
        )
        self.assertEqual(state_res.status_code, 200, state_res.text)
        self.assertEqual(state_res.json()["title"], "第一集追逐戏导演会话")
        self.assertTrue(state_res.json()["auto_approve"])

        # Enqueue 2 follow-up messages, steer #2 to front, take #1 for edit, then cancel #1
        q1 = self.command(
            f"{path}/agent-sessions/{session_id}/queue",
            {"action": "enqueue", "message": "补充男主特写眼神", "skill_id": "vsc-direct", "mode": "manual"},
        )
        self.assertEqual(q1.status_code, 200, q1.text)
        q1_id = q1.json()["item"]["id"]

        q2 = self.command(
            f"{path}/agent-sessions/{session_id}/queue",
            {"action": "enqueue", "message": "优先加入AI MV副歌卡点", "skill_id": "ai-mv-production", "mode": "auto_drafts"},
        )
        self.assertEqual(q2.status_code, 200, q2.text)
        q2_id = q2.json()["item"]["id"]

        steered = self.command(
            f"{path}/agent-sessions/{session_id}/queue",
            {"action": "steer", "queue_item_id": q2_id},
        )
        self.assertEqual(steered.status_code, 200, steered.text)

        sessions = self.client.get(self.base + path + "/agent-sessions").json()["items"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["title"], "第一集追逐戏导演会话")
        self.assertTrue(sessions[0]["auto_approve"])
        self.assertEqual([item["id"] for item in sessions[0]["queue"]], [q2_id, q1_id])
        self.assertEqual(sessions[0]["queue"][0]["status"], "steered")

        editing = self.command(
            f"{path}/agent-sessions/{session_id}/queue",
            {"action": "take_for_edit", "queue_item_id": q1_id},
        )
        self.assertEqual(editing.status_code, 200, editing.text)
        self.assertEqual(editing.json()["item"]["status"], "editing")

        cancelled = self.command(
            f"{path}/agent-sessions/{session_id}/queue",
            {"action": "cancel", "queue_item_id": q1_id},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        after_cancel = self.client.get(self.base + path + "/agent-sessions").json()["items"][0]["queue"]
        self.assertEqual([item["id"] for item in after_cancel], [q2_id])

        # Archive session -> hidden unless include_archived=true
        archived = self.command(
            f"{path}/agent-sessions/{session_id}/state",
            {"archived": True},
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.client.get(self.base + path + "/agent-sessions").json()["items"], [])
        with_arch = self.client.get(self.base + path + "/agent-sessions?include_archived=true").json()["items"]
        self.assertEqual(len(with_arch), 1)
        self.assertTrue(with_arch[0]["archived"])

        # Camera motion templates: 8 builtin + custom CRUD + project isolation
        motions_initial = self.client.get(self.base + "/camera-motion-templates").json()
        self.assertEqual(len(motions_initial["builtin"]), 8)
        self.assertEqual(motions_initial["custom"], [])

        created_motion = self.command(
            "/camera-motion-templates",
            {
                "action": "create",
                "name": "希区柯克变焦 Dolly Zoom",
                "prompt_fragment": "摄影机后拉同时长焦前推，主体大小不变背景急速压缩",
                "horizontal_pan": 0,
                "vertical_tilt": 5,
                "zoom_delta": 70,
                "roll_deg": -5,
                "speed_preset": "fast",
                "favorite": False,
            },
        )
        self.assertEqual(created_motion.status_code, 200, created_motion.text)
        tpl_id = created_motion.json()["item"]["id"]

        fav_motion = self.command(
            "/camera-motion-templates",
            {"action": "favorite", "template_id": tpl_id, "favorite": True},
        )
        self.assertEqual(fav_motion.status_code, 200, fav_motion.text)
        self.assertTrue(fav_motion.json()["item"]["favorite"])

        motions_after = self.client.get(self.base + "/camera-motion-templates").json()
        self.assertEqual(len(motions_after["custom"]), 1)
        self.assertEqual(motions_after["custom"][0]["id"], tpl_id)
        self.assertTrue(motions_after["custom"][0]["favorite"])

        # Project isolation check on second project
        other_project = self.service.create_project(
            {"slug": "isolated-proj-" + uuid.uuid4().hex[:6], "name": "隔离测试项目"},
            actor="test-human",
            idempotency_key=uuid.uuid4().hex,
        )
        other_motions = self.client.get(f"/api/v1/projects/{other_project['id']}/camera-motion-templates").json()
        self.assertEqual(other_motions["custom"], [])

        del_motion = self.command(
            "/camera-motion-templates",
            {"action": "delete", "template_id": tpl_id},
        )
        self.assertEqual(del_motion.status_code, 200, del_motion.text)
        self.assertEqual(self.client.get(self.base + "/camera-motion-templates").json()["custom"], [])

        # Confirm zero real supplier generation jobs were submitted anywhere
        jobs = self.client.get(self.base + "/creative-canvas-jobs").json()
        self.assertEqual(jobs["total"], 0)
        self.assertEqual(jobs["items"], [])


if __name__ == "__main__":
    unittest.main()
