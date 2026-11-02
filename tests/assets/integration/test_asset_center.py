"""Fixed library reuse, catalog revisions and private selection/download consumers."""
import io
import tempfile
import unittest
import uuid
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from support.fixtures.resources import png_bytes
from vsc.assets.resource_service import ResourceError,Conflict


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,"requires isolated PostgreSQL")
class AssetCenterTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service.storage=LocalStorage(self.tmp.name)

    def shared(self,key=None):
        key=key or "center-"+uuid.uuid4().hex
        staged=self.service.storage.stage_upload(io.BytesIO(png_bytes()),"reference.png")
        return self.service.import_library({"library_key":key,"title":"合成共享人物","category":"image","description":"Synthetic owned reference",
            "specification":{},"allowed_purposes":["identity_face"],"license":{"outcome":"owned","allow_workspace_reuse":True,"evidence":"owned synthetic bytes"},
            "import_key":uuid.uuid4().hex,"members":[{"member_key":"front","staged_upload":staged["staged_upload"]}]},actor="test-human")

    def test_catalog_fixed_confirmation_tags_conflicts_and_owner(self):
        key="catalog-"+uuid.uuid4().hex;fixed=self.shared(key)
        payload=dict(entry_id=fixed["entry_id"],library_version_id=fixed["version_id"],expected_revision=0,
            asset_kind="character",form_name="青年",workspace_id=None,review_status="confirmed",notes="合成目录人工确认",
            tags=["青年","主角"],command_key="catalog-save")
        first=self.service.edit_asset_catalog(payload,"test-human")
        self.assertEqual(self.service.edit_asset_catalog(payload,"test-human")["id"],first["id"])
        selected=self.service.search_asset_center({"tag":"主角","form_name":"青年","review_status":"confirmed"},"test-human")
        self.assertEqual(selected["total"],1);self.assertEqual(selected["items"][0]["catalog"]["revision"],1)
        with self.assertRaises(Conflict):self.service.edit_asset_catalog(dict(payload,command_key="stale",notes="stale edit"),"test-human")
        with self.assertRaises(ResourceError):self.service.edit_asset_catalog(dict(payload,command_key="other-person"),"other-human")
        newer=self.shared(key)
        self.assertNotEqual(newer["version_id"],fixed["version_id"])
        self.assertEqual(self.service.search_asset_center({"review_status":"confirmed"},"test-human")["total"],0)
        self.assertEqual(self.service.search_asset_center({"review_status":"draft","asset_kind":"character"},"test-human")["total"],1)

    def test_cart_reuses_bytes_as_independent_candidates_and_restores_receipts(self):
        fixed=self.shared()
        selection={"library_version_id":fixed["version_id"],"member_key":"front","active":True}
        item=self.service.change_asset_center_cart(selection,"test-human")
        self.assertEqual(self.service.change_asset_center_cart(selection,"test-human"),item)
        self.assertEqual(self.service.asset_center_cart("other-human")["items"],[])
        payload={"cart_id":item["id"],"asset_kind":"character","role":"identity_face"}
        first=self.write("import_asset_center_item",payload,idempotency_key="first-import")
        replay=self.service.import_asset_center_item(self.p,payload,actor="test-human",expected_revision=0,idempotency_key="first-import")
        self.assertEqual(first,replay)
        again=self.write("import_asset_center_item",payload,idempotency_key="new-response-key")
        self.assertEqual(first["media_id"],again["media_id"])
        card=self.service.get_asset_card(self.p,first["target_object_id"])
        self.assertEqual(card["forms"][0]["media_id"],first["media_id"])
        self.assertIsNotNone(card["forms"][0]["spec_id"])
        self.assertEqual(len(card["forms"][0]["history"]),1)
        source_project=self.p
        other=self.service.create_project({"name":"另一个合成目标","profile_snapshot":{"profile_id":"vsc.synthetic","version":"1","stages":[]}},actor="test-human")
        second=self.service.import_asset_center_item(other["id"],payload,actor="test-human",expected_revision=0,idempotency_key="second-project")
        self.assertNotEqual(first["media_id"],second["media_id"])
        self.assertEqual(self.service.get_media(source_project,first["media_id"])["blob_id"],self.service.get_media(other["id"],second["media_id"])["blob_id"])
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.media_reviews)).scalar_one(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs)).scalar_one(),0)
        with self.assertRaises(ResourceError):self.write("import_asset_center_item",dict(payload,role="voice_sample"))
        request={"library_version_id":fixed["version_id"],"member_key":"front","command_key":"download-fixed"}
        download=self.service.request_asset_download(request,"test-human")
        self.assertEqual(download["id"],self.service.request_asset_download(request,"test-human")["id"])
        self.assertEqual(self.service.asset_download_history("test-human")["total"],1)
        self.assertEqual(self.service.asset_download_history("other-human")["total"],0)

    def test_task_center_reads_original_import_state(self):
        from hashlib import sha256
        content=b"synthetic upload"
        manifest=self.write("create_media_import",{"title":"合成导入任务","files":[{"filename":name,"size_bytes":len(content),"sha256":sha256(content).hexdigest()} for name in ['one.txt','two.txt','three.txt']]})
        first=self.service.get_task_center(self.p,kind="import")
        self.assertEqual(first["total"],3);self.assertEqual(first["items"][0]["status"],"awaiting_upload")
        pages=[self.service.get_task_center(self.p,kind='import',offset=i,limit=1)['items'][0]['id'] for i in range(3)]
        self.assertEqual(pages,[row['id'] for row in first['items']])
        self.assertIn('task_target='+manifest['id'], first['items'][0]['href'])
        self.write("cancel_media_import_item",{"batch_id":manifest["id"],"item_id":first["items"][0]["id"]})
        self.assertEqual(self.service.get_task_center(self.p,status="cancelled")["total"],1)
