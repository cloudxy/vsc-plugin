"""HTTP integration for in-canvas director stage, recognition and reference video."""
import base64
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid

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


def _png(color=(20, 40, 200)):
    image = Image.new("RGB", (16, 16), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _probe(content):
    with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
        handle.write(content)
        handle.flush()
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-show_entries", "format=duration,size", "-of", "json", handle.name,
        ], timeout=20)
    payload = json.loads(raw)
    stream = payload["streams"][0]
    rate = stream.get("avg_frame_rate") or "0/1"
    num, den = rate.split("/")
    fps = float(num) / float(den) if float(den) else 0
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "duration": float(payload["format"]["duration"]),
        "size": len(content),
    }


@unittest.skipUnless(TEST_URL and HAS_DEPS and HAS_FFMPEG, "requires isolated PostgreSQL, web dependencies, and ffmpeg")
class CanvasDirectorStageIntegrationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.directory = tempfile.TemporaryDirectory(prefix="vsc-canvas-director-")
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
            "source": {"kind": "synthetic-owned", "content": "canvas director fixture"},
        })
        self.assertEqual(registered.status_code, 200, registered.text)
        return registered.json()["id"]

    def canvas_document(self, canvas_id, version=None):
        params = {"version": version} if version is not None else None
        response = self.client.get(self.base + "/creative-canvases/" + canvas_id, headers=self.headers, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_director_stage_recognition_capture_and_reference_video(self):
        source_media = self.upload_media(_png((180, 40, 40)), "source.png", "识图原图")
        panorama_media = self.upload_media(_png((40, 80, 180)), "pano-source.png", "全景原图")
        created = self.command("/creative-canvases", {"title": "导演台", "document": {"nodes": [
            {"id": "stage-1", "type": "director-stage", "title": "导演台", "x": 40, "y": 40, "text": ""},
            {"id": "preview-1", "type": "3d-preview", "title": "3D预演", "x": 420, "y": 40, "text": ""},
            {"id": "img-a", "type": "image", "title": "识图原图", "x": 40, "y": 320, "text": "", "media_id": source_media},
            {"id": "img-b", "type": "image", "title": "全景原图", "x": 360, "y": 320, "text": "", "media_id": panorama_media},
        ], "edges": [
            {"id": "pano-edge-1", "source": "img-b", "target": "stage-1", "port": "panorama_image"},
        ]}})
        self.assertEqual(created.status_code, 200, created.text)
        canvas_id = created.json()["id"]
        canvas_revision = created.json()["canvas_revision"]
        path = "/creative-canvases/" + canvas_id
        opened = self.canvas_document(canvas_id)
        stage = json.loads(next(node["text"] for node in opened["document"]["nodes"] if node["id"] == "stage-1"))
        preview = json.loads(next(node["text"] for node in opened["document"]["nodes"] if node["id"] == "preview-1"))
        self.assertEqual(stage["schemaVersion"], 1)
        self.assertEqual(stage["panorama"]["sourceType"], "linked")
        self.assertEqual(stage["panorama"]["linkedNodeId"], "img-b")
        self.assertEqual(preview["documentRef"]["schemaVersion"], 1)
        self.assertEqual(preview["timelineSummary"]["durationSeconds"], 15)
        self.assertEqual(preview["timelineSummary"]["shotCount"], 1)
        self.assertEqual(next(node["type"] for node in opened["document"]["nodes"] if node["id"] == "preview-1"), "3d-preview")
        self.assertFalse(any(node.get("ports") for node in opened["document"]["nodes"] if node["id"] == "preview-1"))

        inserted = self.command(path + "/pic-recognize", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "stage-1",
            "image_node_id": "img-a", "strategy": "insert",
        })
        self.assertEqual(inserted.status_code, 200, inserted.text)
        self.assertEqual(inserted.json()["status"], 2)
        canvas_revision = inserted.json()["canvas_revision"]
        task_id = inserted.json()["task_id"]
        recognized = json.loads(inserted.json()["result"])
        self.assertTrue(any(item["kind"] == "character" for item in recognized["objects"]))
        after_insert = json.loads(next(node["text"] for node in self.canvas_document(canvas_id)["document"]["nodes"] if node["id"] == "stage-1"))
        self.assertEqual(after_insert["panorama"]["sourceType"], "linked")
        self.assertTrue(any(item["id"] == "recog-a" for item in after_insert["objects"]))

        replaced = self.command(path + "/pic-recognize", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "stage-1",
            "image_node_id": "img-a", "strategy": "replace",
        })
        self.assertEqual(replaced.status_code, 200, replaced.text)
        canvas_revision = replaced.json()["canvas_revision"]
        after_replace = json.loads(next(node["text"] for node in self.canvas_document(canvas_id)["document"]["nodes"] if node["id"] == "stage-1"))
        self.assertEqual(after_replace["panorama"]["sourceType"], "linked")
        self.assertFalse(any(item["id"].endswith("-x") for item in after_replace["objects"]))

        blocked = self.command(path + "/pic-recognize", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "stage-1",
            "image_node_id": "img-b", "strategy": "insert",
        })
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(blocked.json()["error"], "linked_image_ai_import_unsupported")
        self.assertEqual(self.canvas_document(canvas_id)["canvas_revision"], canvas_revision)

        listed = self.client.post(self.base + path + "/pic-recognize/list", headers=self.headers, json={
            "payload": {"kind": "recognize", "offset": 0, "limit": 20},
        })
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertGreaterEqual(listed.json()["total"], 2)
        self.assertTrue(any(row["id"] == task_id and row["status"] == 2 for row in listed.json()["list"]))
        refreshed = self.client.post(self.base + path + "/pic-recognize/refresh", headers=self.headers, json={"payload": {"task_id": task_id}})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["status"], 2)
        deleted = self.command(path + "/pic-recognize/delete", {"canvas_id": canvas_id, "task_id": task_id})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        listed_again = self.client.post(self.base + path + "/pic-recognize/list", headers=self.headers, json={
            "payload": {"kind": "recognize", "offset": 0, "limit": 20},
        })
        self.assertTrue(all(row["id"] != task_id for row in listed_again.json()["list"]))

        shot = base64.b64encode(_png()).decode("ascii")
        for mode, count in (("current", 1), ("four", 4), ("twelve", 12)):
            captured = self.command(path + "/director-screenshot", {
                "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "stage-1",
                "mode": mode, "images": [shot] * count,
            })
            self.assertEqual(captured.status_code, 200, captured.text)
            canvas_revision = captured.json()["canvas_revision"]
            document = self.canvas_document(canvas_id)["document"]
            for node_id in captured.json()["node_ids"]:
                self.assertTrue(any(edge["source"] == "stage-1" and edge["target"] == node_id and edge["port"] == "directorStageCapture" for edge in document["edges"]))
                self.assertEqual(next(node["type"] for node in document["nodes"] if node["id"] == node_id), "image")
        stage = json.loads(next(node["text"] for node in self.canvas_document(canvas_id)["document"]["nodes"] if node["id"] == "stage-1"))
        self.assertGreaterEqual(len(stage["cameras"][0]["screenshots"]), 1)
        self.assertNotIn("createdAt", stage["cameras"][0]["screenshots"][0])
        self.assertEqual(stage["cameras"][0]["screenshots"][0]["mode"], "current")

        generated = self.command(path + "/director-panorama", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "stage-1",
        })
        self.assertEqual(generated.status_code, 200, generated.text)
        canvas_revision = generated.json()["canvas_revision"]
        document = self.canvas_document(canvas_id)["document"]
        self.assertTrue(any(edge["source"] == generated.json()["node_id"] and edge["target"] == "stage-1" and edge["port"] == "panorama_image" for edge in document["edges"]))
        stage = json.loads(next(node["text"] for node in document["nodes"] if node["id"] == "stage-1"))
        self.assertEqual(stage["panorama"]["origin"], "image_to_panorama")
        self.assertEqual(stage["panorama"]["sourceType"], "linked")
        history = self.client.post(self.base + path + "/pic-recognize/list", headers=self.headers, json={
            "payload": {"kind": "panorama", "offset": 0, "limit": 20},
        })
        self.assertEqual(history.status_code, 200, history.text)
        self.assertGreaterEqual(history.json()["total"], 1)

        edited = self.command(path + "/preview-chat", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "preview-1", "text": "添加一个女角色",
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        canvas_revision = edited.json()["canvas_revision"]
        preview = json.loads(next(node["text"] for node in self.canvas_document(canvas_id)["document"]["nodes"] if node["id"] == "preview-1"))
        self.assertTrue(any(item.get("variant") == "female_low_poly" for item in preview["stage"]["objects"]))
        self.assertGreaterEqual(preview["documentRef"]["revision"], 2)

        exported = self.command(path + "/reference-video", {
            "canvas_id": canvas_id, "canvas_revision": canvas_revision, "node_id": "preview-1",
            "images": [shot], "frame_count": 24,
        })
        self.assertEqual(exported.status_code, 200, exported.text)
        canvas_revision = exported.json()["canvas_revision"]
        video = self.client.get(self.base + "/media/" + exported.json()["media_id"] + "/content", headers=self.headers)
        self.assertEqual(video.status_code, 200, video.text)
        meta = _probe(video.content)
        self.assertGreater(meta["duration"], 0)
        self.assertLessEqual(meta["duration"], 15)
        self.assertLessEqual(max(meta["width"], meta["height"]), 960)
        self.assertLess(abs(meta["fps"] - 24), 0.2)
        self.assertLessEqual(meta["size"], 8 * 1024 * 1024)
        document = self.canvas_document(canvas_id)["document"]
        source_id = exported.json()["reference_node_id"]
        generator_id = exported.json()["generator_node_id"]
        self.assertTrue(any(edge["source"] == source_id and edge["target"] == generator_id and edge["port"] == "reference_video" for edge in document["edges"]))
        generator = next(node for node in document["nodes"] if node["id"] == generator_id)
        self.assertEqual(generator["params"]["vsc_operation"], "seedance_omni_video")
        self.assertIsNone(generator["media_id"])

        before = self.canvas_document(canvas_id)
        conflict = self.command(path + "/preview-chat", {
            "canvas_id": canvas_id, "canvas_revision": 1, "node_id": "preview-1", "text": "添加一个角色",
        })
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"], "canvas_revision_conflict")
        after = self.canvas_document(canvas_id)
        self.assertEqual(after["canvas_revision"], before["canvas_revision"])
        self.assertEqual(after["sha256"], before["sha256"])
        self.assertGreater(canvas_revision, 1)
