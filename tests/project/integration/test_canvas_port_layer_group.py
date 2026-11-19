"""Real PostgreSQL + FastAPI integration tests for C3 layer separation/composition, stitching, and workflow cancel."""
import hashlib
import importlib.util
import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image
from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


def _png_bytes(width=120, height=90, color=(40, 120, 200)):
    im = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires configured isolated PostgreSQL and web dependencies")
class CanvasPortLayerGroupIntegrationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app

        self.directory = tempfile.TemporaryDirectory()
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

    def _register_image(self, name, color):
        raw = _png_bytes(120, 90, color)
        staged = self.service.storage.stage_upload(io.BytesIO(raw), name + ".png")
        committed = self.service.storage.commit_upload(staged["staged_upload"])
        row = self.write("register_media", {
            "name": name, "modality": "image", "sha256": committed["sha256"],
            "size_bytes": committed["size_bytes"], "mime_type": "image/png",
            "storage": "local", "object_key": committed["object_key"], "rights": "owned",
            "source": {"kind": "test-owned", "content": name},
        })
        self.write("record_media_check", {"media_id": row["id"], "checker": "test-probe", "criteria_version": "1", "outcome": "pass"})
        return row["id"]

    def _post(self, path, payload):
        resp = self.client.post(self.base + path, headers=self.headers, json={
            "payload": payload,
            "expected_revision": self.rev,
            "idempotency_key": uuid.uuid4().hex,
        })
        if resp.status_code == 200 and "revision" in resp.json():
            self.rev = resp.json()["revision"]
        return resp

    def test_separate_compose_stitch_and_workflow_cancel_over_http(self):
        img1 = self._register_image("图层源图A", (220, 60, 60))
        img2 = self._register_image("拼合源图B", (60, 180, 90))
        created = self._post("/creative-canvases", {
            "title": "图层与拼图测试",
            "document": {
                "nodes": [
                    {"id": "n1", "type": "image", "title": "源图A", "x": 80, "y": 80, "text": "", "params": {}, "media_id": img1, "job_id": None, "group": "组1"},
                    {"id": "n2", "type": "image", "title": "源图B", "x": 360, "y": 80, "text": "", "params": {}, "media_id": img2, "job_id": None, "group": "组1"},
                ],
                "edges": [],
            },
        })
        self.assertEqual(created.status_code, 200, created.text)
        cid = created.json()["id"]
        crev = created.json()["canvas_revision"]

        sep = self._post(f"/creative-canvases/{cid}/separate-layers", {
            "canvas_id": cid, "canvas_revision": crev, "node_id": "n1",
            "selections": [{"id": "s1", "description": "前景主角", "bbox": [0.1, 0.1, 0.7, 0.6]}],
        })
        self.assertEqual(sep.status_code, 200, sep.text)
        sep_body = sep.json()
        crev = sep_body["canvas_revision"]
        self.assertGreaterEqual(len(sep_body["node_ids"]), 2)

        comp = self._post(f"/creative-canvases/{cid}/compose-layers", {
            "canvas_id": cid, "canvas_revision": crev,
            "layers": [
                {"node_id": sep_body["node_ids"][0], "x": 0, "y": 0, "scale": 1.0, "z": 0, "visible": True},
                {"node_id": sep_body["node_ids"][1], "x": 12, "y": 8, "scale": 1.0, "z": 1, "visible": True},
            ],
        })
        self.assertEqual(comp.status_code, 200, comp.text)
        comp_body = comp.json()
        crev = comp_body["canvas_revision"]
        self.assertEqual(len(comp_body["node_ids"]), 1)

        stitched = self._post(f"/creative-canvases/{cid}/stitch-images", {
            "canvas_id": cid, "canvas_revision": crev, "node_ids": ["n1", "n2"], "mode": "long",
        })
        self.assertEqual(stitched.status_code, 200, stitched.text)
        stitched_media = stitched.json()["media_ids"][0]
        dl = self.client.get(f"{self.base}/media/{stitched_media}/content")
        self.assertEqual(dl.status_code, 200)
        with Image.open(io.BytesIO(dl.content)) as out_im:
            self.assertGreater(out_im.width * out_im.height, 120 * 90)

        canceled = self._post(f"/creative-canvases/{cid}/workflow-cancel", {
            "canvas_id": cid, "step_id": "step-demo-1",
        })
        self.assertEqual(canceled.status_code, 200, canceled.text)
        self.assertEqual(canceled.json()["status"], "canceled")
