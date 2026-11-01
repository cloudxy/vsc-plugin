"""Resumed bytes and per-file original media registration in isolated PostgreSQL."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError, Conflict


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires isolated PostgreSQL")
class MediaImportTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-import-test-")
        self.addCleanup(self.temp.cleanup)
        self.storage = self.service.storage = LocalStorage(Path(self.temp.name)/"media")

    def batch(self, files, **extra):
        result = self.write("create_media_import", {"title": "两文件导入", "rights": "owned",
            "source_evidence": "isolated synthetic files", "files": [{"filename": name, "size_bytes": len(data),
            "sha256": sha256(data).hexdigest()} for name,data in files], **extra})
        return self.service.get_media_import(self.p, result["id"])

    def refresh(self):
        self.rev = self.service.get_project(self.p)["revision"]

    def test_resume_and_response_loss_do_not_duplicate_registration(self):
        data = ("可恢复的素材文件。"*100).encode()
        batch = self.batch([("part.txt", data), ("later.txt", b"retained")])
        batch_id, item_id = batch["batch"]["id"], batch["items"][0]["id"]
        half=len(data)//2
        self.service.upload_import_chunk(self.p, batch_id, item_id, 0, data[:half], actor="test-human")
        duplicate = self.service.upload_import_chunk(self.p, batch_id, item_id, 0, data[:half], actor="test-human")
        self.assertEqual(duplicate["uploaded_bytes"], half)
        with self.assertRaises(Conflict):
            self.service.upload_import_chunk(self.p, batch_id, item_id, 0, b"changed", actor="test-human")
        self.assertEqual(self.service.get_media_import(self.p, batch_id)["items"][0]["uploaded_bytes"], half)
        from vsc.assets.resource_service import ResourceService
        resumed = ResourceService(self.store, storage=self.storage)
        resumed.upload_import_chunk(self.p, batch_id, item_id, half, data[half:], actor="test-human")
        self.refresh()
        payload={"batch_id": batch_id, "item_id": item_id}; key=uuid.uuid4().hex
        result = self.write("process_media_import_item", payload, idempotency_key=key)
        replay=resumed.process_media_import_item(self.p, payload, expected_revision=0, idempotency_key=key, actor="test-human")
        self.assertEqual(replay, result)
        self.assertEqual(self.service.get_media(self.p,result["media_id"])["sha256"],sha256(data).hexdigest())
        detail=self.service.get_media_import(self.p,batch_id)
        self.assertNotIn("upload_key",detail["items"][0]);self.assertNotIn("uploaded_metadata",detail["items"][0])
        self.assertEqual(detail["items"][0]["status"],"completed")
        self.assertEqual(detail["items"][1]["status"],"awaiting_upload")

    def test_one_failed_asset_keeps_successful_file_and_cancelled_file_stops(self):
        from PIL import Image
        out=BytesIO();Image.new("RGB",(64,64),(10,40,100)).save(out,format="PNG");image=out.getvalue()
        batch=self.batch([("face.png",image),("wrong.txt",b"not an image"),("cancel.txt",b"cancel")],asset_kind="character")
        batch_id=batch["batch"]["id"]
        for item,data in zip(batch["items"],(image,b"not an image")):
            self.service.upload_import_chunk(self.p,batch_id,item["id"],0,data,actor="test-human")
            self.refresh()
            if item["filename"]=="face.png":
                good=self.write("process_media_import_item",{"batch_id":batch_id,"item_id":item["id"]})
                self.assertIsNotNone(good["asset_id"])
            else:
                with self.assertRaises(ResourceError):
                    self.write("process_media_import_item",{"batch_id":batch_id,"item_id":item["id"]})
        self.refresh();last=batch["items"][2]
        self.write("cancel_media_import_item",{"batch_id":batch_id,"item_id":last["id"]})
        with self.assertRaises(ResourceError):
            self.service.upload_import_chunk(self.p,batch_id,last["id"],0,b"cancel",actor="test-human")
        items=self.service.get_media_import(self.p,batch_id)["items"]
        self.assertEqual([i["status"] for i in items],["completed","failed","cancelled"])
        self.assertEqual(items[0]["media_id"],good["media_id"])

    def test_http_scope_digest_and_manifest_seal(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import new_id
        batch=self.batch([("one.txt",b"original")]);batch_id=batch["batch"]["id"];item=batch["items"][0]
        other=self.batch([("two.txt",b"other")])["batch"]["id"]
        with self.assertRaises(ResourceError):
            self.service.upload_import_chunk(self.p,other,item["id"],0,b"original",actor="test-human")
        with self.assertRaises(ResourceError):
            self.service.upload_import_chunk(self.p,batch_id,item["id"],0,b"modified",actor="test-human")
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.media_import_items).values(project_id=self.p,id=new_id(),batch_id=batch_id,ordinal=1,
                filename="append.txt",size_bytes=1,expected_sha256="0"*64,upload_key="a"*48,status="awaiting_upload"))
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app=create_app({"projects_root":self.temp.name,"media_root":str(self.storage.root),"allowed_hosts":["testserver"],
            "allowed_origins":["http://testserver"],"access_token":"token","human_identity":"test-human"},service=self.service)
        with TestClient(app) as client:
            path=f"/api/v1/projects/{self.p}/media-imports/{other}/items/{item['id']}/upload?offset=0"
            self.assertEqual(client.put(path,content=b"original").status_code,403)
            session=client.post("/api/v1/session",headers={"Origin":"http://testserver"},json={"token":"token"}).json()
            self.assertEqual(client.put(path,headers={"Origin":"http://testserver","X-CSRF-Token":session["csrf_token"]},content=b"original").status_code,422)

    def test_corrupt_media_is_a_persisted_file_failure(self):
        data = b"\x89PNG\r\n\x1a\n" + b"truncated synthetic PNG"
        batch = self.batch([("broken.png", data), ("retained.txt", b"good")])
        item = batch["items"][0]
        with self.assertRaises(ResourceError) as caught:
            self.service.upload_import_chunk(self.p, batch["batch"]["id"], item["id"], 0, data, actor="test-human")
        self.assertTrue(caught.exception.code.startswith("media_"))
        result = self.service.get_media_import(self.p, batch["batch"]["id"])
        self.assertEqual(result["items"][0]["status"], "failed")
        self.assertEqual(result["items"][0]["uploaded_bytes"], len(data))
        self.assertIsNone(result["items"][0]["media_id"])
        self.assertEqual(result["items"][1]["status"], "awaiting_upload")
