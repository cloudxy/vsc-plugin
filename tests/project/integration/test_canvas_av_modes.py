"""HTTP integration: local FFmpeg audio processing and video frame capture create derived nodes."""
import importlib.util
import io
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import patch

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


def _wav(duration_ms=2000, sample_rate=16000):
    frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        samples = [int(8000 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate)) for index in range(frames)]
        handle.writeframes(struct.pack("<" + "h" * frames, *samples))
    return buf.getvalue()


def _color_video():
    with tempfile.TemporaryDirectory(prefix="vsc-av-video-") as directory:
        path = Path(directory) / "colors.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=64x64:r=25:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
            "-movflags", "+faststart", str(path),
        ], check=True, timeout=30)
        return path.read_bytes()


def _duration_ms(content, suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(content)
        handle.flush()
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", handle.name,
        ], timeout=20)
    return round(float(json.loads(raw)["format"]["duration"]) * 1000)


@unittest.skipUnless(TEST_URL and HAS_DEPS and HAS_FFMPEG, "requires isolated PostgreSQL, web dependencies, and ffmpeg")
class CanvasAvModesIntegrationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.directory = tempfile.TemporaryDirectory(prefix="vsc-canvas-av-")
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
            "source": {"kind": "synthetic-owned", "content": "canvas av fixture"},
        })
        self.assertEqual(registered.status_code, 200, registered.text)
        return registered.json()["id"]

    def test_audio_clip_and_speed_create_shorter_audio_nodes(self):
        media_id = self.upload_media(_wav(2000), "source.wav", "两秒音频")
        created = self.command("/creative-canvases", {"title": "音频处理", "document": {"nodes": [{
            "id": "aud-1", "type": "audio", "title": "原音频", "x": 40, "y": 80, "media_id": media_id,
        }], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        path = "/creative-canvases/" + canvas_id
        clipped = self.command(path + "/process-audio", {
            "canvas_revision": created.json()["canvas_revision"], "node_id": "aud-1", "operation": "clip",
            "start_seconds": 0.4, "end_seconds": 1.2,
        })
        self.assertEqual(clipped.status_code, 200, clipped.text)
        clip_body = clipped.json()
        self.assertTrue(clip_body["node_ids"][0].startswith("audio-"))
        clip_bytes = self.client.get(f"{self.base}/media/{clip_body['media_ids'][0]}/content").content
        clip_ms = _duration_ms(clip_bytes, ".wav")
        self.assertLess(abs(clip_ms - 800), 80)
        self.assertLess(clip_ms, 2000)
        document = self.client.get(self.base + path, params={"version": clip_body["canvas_revision"]}).json()["document"]
        self.assertTrue(any(edge["source"] == "aud-1" and edge["target"] == clip_body["node_ids"][0] and edge["port"] == "derived_from" for edge in document["edges"]))
        self.assertEqual(next(node["type"] for node in document["nodes"] if node["id"] == clip_body["node_ids"][0]), "audio")

        sped = self.command(path + "/process-audio", {
            "canvas_revision": clip_body["canvas_revision"], "node_id": "aud-1", "operation": "speed", "speed": 2,
        })
        self.assertEqual(sped.status_code, 200, sped.text)
        speed_bytes = self.client.get(f"{self.base}/media/{sped.json()['media_ids'][0]}/content").content
        speed_ms = _duration_ms(speed_bytes, ".wav")
        self.assertLess(abs(speed_ms - 1000), 150)
        self.assertLess(speed_ms, 2000)

    def test_video_frame_capture_creates_distinct_image_nodes(self):
        media_id = self.upload_media(_color_video(), "colors.mp4", "红蓝视频")
        created = self.command("/creative-canvases", {"title": "截帧", "document": {"nodes": [{
            "id": "vid-1", "type": "video", "title": "原视频", "x": 20, "y": 30, "media_id": media_id,
        }], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        path = "/creative-canvases/" + created.json()["id"]
        first = self.command(path + "/capture-frame", {"canvas_revision": created.json()["canvas_revision"], "node_id": "vid-1", "frame": "first"})
        self.assertEqual(first.status_code, 200, first.text)
        last = self.command(path + "/capture-frame", {"canvas_revision": first.json()["canvas_revision"], "node_id": "vid-1", "frame": "last"})
        self.assertEqual(last.status_code, 200, last.text)
        first_bytes = self.client.get(f"{self.base}/media/{first.json()['media_ids'][0]}/content").content
        last_bytes = self.client.get(f"{self.base}/media/{last.json()['media_ids'][0]}/content").content
        self.assertTrue(first_bytes.startswith(b"\x89PNG"))
        self.assertNotEqual(first_bytes, last_bytes)
        with Image.open(io.BytesIO(first_bytes)) as image:
            red, green, blue = image.convert("RGB").getpixel((32, 32))
        with Image.open(io.BytesIO(last_bytes)) as image:
            last_red, last_green, last_blue = image.convert("RGB").getpixel((32, 32))
        self.assertGreater(red, blue)
        self.assertGreater(last_blue, last_red)
        document = self.client.get(self.base + path, params={"version": last.json()["canvas_revision"]}).json()["document"]
        for body in (first.json(), last.json()):
            node_id = body["node_ids"][0]
            self.assertTrue(node_id.startswith("frame-"))
            self.assertEqual(next(node["type"] for node in document["nodes"] if node["id"] == node_id), "image")
            self.assertTrue(any(edge["source"] == "vid-1" and edge["target"] == node_id and edge["port"] == "derived_from" for edge in document["edges"]))

    def test_audio_quote_includes_lyrics_and_rejects_bad_seed(self):
        created = self.command("/creative-canvases", {"title": "报价", "document": {"nodes": [], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        path = self.base + "/creative-canvases/" + created.json()["id"] + "/work-quote"
        model = {
            "id": "audio-quote-model", "modality": "audio", "enabled": True, "adapter_available": True,
            "model_key": "doubao-seed-audio-1.0", "model_version": "1", "provider_id": "seed-audio", "name": "Seed Audio",
        }
        payload = {"op_type": "audio_generate", "model_id": model["id"], "audio_mode": "lyrics", "lyrics_chars": 12, "duration": 30, "voice_id": "zh_female_vv_uranus_bigtts", "music_style": "古风"}
        plain = {"op_type": "audio_generate", "model_id": model["id"], "audio_mode": "description", "duration": 30}
        with patch("vsc.production.resource_settings.ResourceSettings.list", return_value={"configurations": [model]}):
            lyrics = self.client.post(path, headers=self.headers, json={"payload": payload})
            description = self.client.post(path, headers=self.headers, json={"payload": plain})
        self.assertEqual(lyrics.status_code, 200, lyrics.text)
        self.assertEqual(description.status_code, 200, description.text)
        lyric_job = lyrics.json()["generation_quote"]["jobs"][0]
        plain_job = description.json()["generation_quote"]["jobs"][0]
        self.assertEqual(lyric_job["native_units"]["speech_chars"], 12)
        self.assertNotEqual(lyric_job["request_sha256"], plain_job["request_sha256"])
        if lyrics.json()["price_basis"] == "native_units":
            self.assertEqual(lyrics.json()["total_price"], 12)
        bad = self.client.post(path, headers=self.headers, json={"payload": {**plain, "seed_sample_rate": 44100}})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"], "invalid_canvas_quote")
