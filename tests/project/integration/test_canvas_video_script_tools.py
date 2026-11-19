"""HTTP integration: in-canvas ffmpeg export, upscale, breakdown and script isolation."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image

if not os.environ.get("VSC_TEST_DATABASE_URL"):
    try:
        from vsc.configuration import get_config
        loaded = get_config("VSC_TEST_DATABASE_URL")
    except Exception:
        loaded = None
    if loaded:
        os.environ["VSC_TEST_DATABASE_URL"] = str(loaded)

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _png(width=16, height=16):
    image = Image.new("RGB", (width, height), (220, 30, 20))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _clip(color, duration="0.4"):
    with tempfile.TemporaryDirectory(prefix="vsc-c2-http-") as directory:
        path = Path(directory) / "clip.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=12:d={duration}",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
        ], check=True, timeout=30)
        return path.read_bytes()


def _two_color():
    with tempfile.TemporaryDirectory(prefix="vsc-c2-http-cut-") as directory:
        path = Path(directory) / "colors.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=64x64:r=25:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
            "-movflags", "+faststart", str(path),
        ], check=True, timeout=30)
        return path.read_bytes()


def _duration(content):
    with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
        handle.write(content)
        handle.flush()
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", handle.name,
        ], timeout=20)
    return float(json.loads(raw)["format"]["duration"])


@unittest.skipUnless(TEST_URL and HAS_DEPS and HAS_FFMPEG, "requires isolated PostgreSQL, web dependencies, and ffmpeg")
class CanvasVideoScriptIntegrationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.directory = tempfile.TemporaryDirectory(prefix="vsc-canvas-video-script-")
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.client = TestClient(create_app({
            "projects_root": self.directory.name + "/projects",
            "media_root": self.directory.name,
            "allowed_hosts": ["testserver"],
            "allowed_origins": ["http://testserver"],
            "human_identity": "test-human",
            "access_token": "test-token",
        }, service=self.service))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def command(self, path, payload):
        response = self.client.post(self.base + path, headers=self.headers, json={
            "payload": payload, "expected_revision": self.rev, "idempotency_key": uuid.uuid4().hex,
        })
        if response.status_code == 200 and "revision" in response.json():
            self.rev = response.json()["revision"]
        return response

    def upload_media(self, content, filename, name):
        staged = self.client.post(self.base + "/uploads", content=content, headers={**self.headers, "X-Filename": filename})
        self.assertEqual(staged.status_code, 200, staged.text)
        registered = self.command("/media", {
            "staged_upload": staged.json()["staged_upload"],
            "name": name,
            "rights": "owned",
            "rights_scope": {"purposes": ["*"]},
            "source": {"kind": "synthetic-owned", "content": "canvas video script fixture"},
        })
        self.assertEqual(registered.status_code, 200, registered.text)
        return registered.json()["id"]

    def test_multi_video_export_conflict_upscale_and_breakdown(self):
        red = self.upload_media(_clip("red"), "red.mp4", "红片段")
        blue = self.upload_media(_clip("blue"), "blue.mp4", "蓝片段")
        created = self.command("/creative-canvases", {"title": "画布合成", "document": {"nodes": [
            {"id": "red", "type": "video", "title": "红", "x": 20, "y": 40, "media_id": red},
            {"id": "blue", "type": "video", "title": "蓝", "x": 20, "y": 260, "media_id": blue},
        ], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id
        stale = self.command(path + "/video-script-tools", {
            "canvas_revision": created.json()["canvas_revision"] + 9,
            "operation": "multi_video_edit",
            "node_id": "red",
            "settings": {"segments": [{"source_node_id": "red", "start_seconds": 0}, {"source_node_id": "blue", "start_seconds": 0}]},
        })
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["message"], "画布版本已变化，请返回画布刷新后重试")
        exported = self.command(path + "/video-script-tools", {
            "canvas_revision": created.json()["canvas_revision"],
            "operation": "multi_video_edit",
            "node_id": "red",
            "settings": {"segments": [
                {"source_node_id": "red", "start_seconds": 0},
                {"source_node_id": "blue", "start_seconds": 0, "end_seconds": 0.4},
            ]},
        })
        self.assertEqual(exported.status_code, 200, exported.text)
        body = exported.json()
        self.assertTrue(body["node_ids"][0].startswith("vst-"))
        media = self.client.get(f"{self.base}/media/{body['media_ids'][0]}/content").content
        self.assertIn(b"ftyp", media[:64])
        self.assertLess(abs(_duration(media) - 0.8), 0.35)
        document = self.client.get(self.base + path, params={"version": body["canvas_revision"]}).json()["document"]
        node = next(item for item in document["nodes"] if item["id"] == body["node_ids"][0])
        self.assertEqual(node["type"], "video")
        self.assertTrue(any(edge["source"] == "red" and edge["target"] == node["id"] and edge["port"] == "derived_from" for edge in document["edges"]))
        self.assertTrue(any(edge["source"] == "blue" and edge["target"] == node["id"] and edge["port"] == "derived_from" for edge in document["edges"]))

        picture = self.upload_media(_png(), "still.png", "小图")
        image_canvas = self.command("/creative-canvases", {"title": "高清放大", "document": {"nodes": [
            {"id": "still", "type": "image", "title": "原图", "x": 10, "y": 10, "media_id": picture},
        ], "edges": []}})
        self.assertEqual(image_canvas.status_code, 200, image_canvas.text)
        image_path = "/creative-canvases/" + image_canvas.json()["id"]
        scaled = self.command(image_path + "/video-script-tools", {
            "canvas_revision": image_canvas.json()["canvas_revision"],
            "operation": "image_upscale",
            "node_id": "still",
            "settings": {"model_type": "text_optimization", "scale": 4},
        })
        self.assertEqual(scaled.status_code, 200, scaled.text)
        scaled_bytes = self.client.get(f"{self.base}/media/{scaled.json()['media_ids'][0]}/content").content
        with Image.open(io.BytesIO(scaled_bytes)) as image:
            self.assertEqual(image.size, (64, 64))
            red, _green, blue = image.convert("RGB").getpixel((8, 8))
        self.assertGreater(red, 150)
        self.assertLess(blue, 80)

        source = self.upload_media(_two_color(), "colors.mp4", "红蓝切换")
        story_canvas = self.command("/creative-canvases", {"title": "拉片", "document": {"nodes": [
            {"id": "cut", "type": "video", "title": "切换", "x": 30, "y": 30, "media_id": source},
        ], "edges": []}})
        self.assertEqual(story_canvas.status_code, 200, story_canvas.text)
        story_path = "/creative-canvases/" + story_canvas.json()["id"]
        broken = self.command(story_path + "/video-script-tools", {
            "canvas_revision": story_canvas.json()["canvas_revision"],
            "operation": "video_breakdown",
            "node_id": "cut",
            "settings": {"dimensions": ["storyboard", "video", "audio"]},
        })
        self.assertEqual(broken.status_code, 200, broken.text)
        saved = self.client.get(self.base + story_path, params={"version": broken.json()["canvas_revision"]}).json()["document"]
        results = [item for item in saved["nodes"] if item["id"] in broken.json()["node_ids"]]
        self.assertEqual({item["params"]["smartVideoBreakdownResult"] for item in results}, {"storyboard", "video", "audio"})
        text = "\n".join(item["text"] for item in results)
        self.assertNotIn("开场建立镜头", text)
        self.assertNotIn("主体动作推进", text)
        self.assertNotIn("情绪特写高潮", text)
        self.assertIn("64×64", text)
        self.assertIn("镜头2", text)
        self.assertTrue(all(edge["port"] == "derived_from" and set(edge) == {"id", "source", "target", "port"} for edge in saved["edges"]))

    def test_script_document_preview_does_not_rewrite_authority(self):
        content = {"scenes": [{"id": "SC1", "estimated_duration_ms": 4000, "actions": [{"id": "A1", "text": "他停下脚步"}], "dialogue": [{"id": "L1", "speaker": "char", "text": "今晚我等你"}], "silence": []}]}
        self.service.save_script_draft(self.p, {"scope_key": "", "base_draft_revision": 0, "content": content}, actor="test-human")
        before = self.client.get(self.base + "/script-draft").json()
        self.assertTrue(before["exists"])
        self.assertEqual(before["content"]["scenes"][0]["dialogue"][0]["text"], "今晚我等你")
        created = self.command("/creative-canvases", {"title": "剧本资料", "document": {"nodes": [
            {"id": "doc-anchor", "type": "text", "title": "锚点", "x": 40, "y": 40, "text": "锚点"},
        ], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id
        rejected = self.command(path + "/video-script-tools", {
            "canvas_revision": created.json()["canvas_revision"],
            "operation": "script_document_bind",
            "node_id": "doc-anchor",
            "settings": {"write_script": True, "scope_key": ""},
        })
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(rejected.json()["message"], "画布上的文字编辑不会改写剧本资料")
        self.assertEqual(self.client.get(self.base + "/script-draft").json()["content"], before["content"])
        bound = self.command(path + "/video-script-tools", {
            "canvas_revision": created.json()["canvas_revision"],
            "operation": "script_document_bind",
            "node_id": "doc-anchor",
            "settings": {"scope_key": ""},
        })
        self.assertEqual(bound.status_code, 200, bound.text)
        current = self.client.get(self.base + path, params={"version": bound.json()["canvas_revision"]}).json()
        document = current["document"]
        preview = next(item for item in document["nodes"] if item["id"] == bound.json()["node_ids"][0])
        self.assertTrue(preview["text"].startswith("节点预览节选"))
        self.assertIn("今晚我等你", preview["text"])
        preview["text"] = "画布改写，不应回写权威剧本"
        saved = self.client.put(self.base + path, headers=self.headers, json={
            "payload": {"canvas_revision": bound.json()["canvas_revision"], "title": current["title"], "document": document},
            "expected_revision": self.rev,
            "idempotency_key": uuid.uuid4().hex,
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        after = self.client.get(self.base + "/script-draft").json()
        self.assertEqual(after["content"], before["content"])
        self.assertEqual(after["draft_revision"], before["draft_revision"])
        reread = self.client.get(self.base + path, params={"version": saved.json()["canvas_revision"]}).json()["document"]
        changed = next(item for item in reread["nodes"] if item["id"] == preview["id"])
        self.assertEqual(changed["text"], "画布改写，不应回写权威剧本")
