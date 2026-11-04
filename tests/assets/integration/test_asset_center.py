"""Fixed library reuse, catalog revisions and private selection/download consumers."""
import io
import tempfile
import unittest
import uuid
from unittest.mock import patch
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

    def official_payload(self,fixed,**changes):
        return dict(dict(entry_id=fixed["entry_id"],library_version_id=fixed["version_id"],asset_kind="character",
            role_level="lead",role_tag="test-"+uuid.uuid4().hex,gender="female",age_band="young_adult",
            notes="合成自有测试素材的官方分类；不代表第三方素材许可",command_key=uuid.uuid4().hex),**changes)

    def publish(self,payload):
        with patch("vsc.configuration.get_config",return_value=["test-human"]):
            return self.service.publish_official_asset(payload,"test-human")

    def test_official_authority_filters_fixed_version_and_legacy_compatibility(self):
        key="official-"+uuid.uuid4().hex;fixed=self.shared(key);payload=self.official_payload(fixed)
        self.assertEqual(self.service.search_asset_center({"source":"official","role_tag":payload["role_tag"]})["total"],0)
        with patch("vsc.configuration.get_config",return_value=[]):
            with self.assertRaises(ResourceError) as denied:self.service.publish_official_asset(payload,"test-human")
        self.assertEqual(denied.exception.code,"official_publisher_required")
        with patch("vsc.configuration.get_config",return_value=["platform-publisher"]):
            with self.assertRaises(ResourceError):self.service.publish_official_asset(payload,"test-human")
        published=self.publish(payload)
        self.assertEqual(self.publish(payload)["id"],published["id"])
        with self.assertRaises(Conflict):self.publish(dict(payload,notes="同一请求标识内容改变"))
        with self.assertRaises(Conflict):self.publish(dict(payload,command_key=uuid.uuid4().hex))
        filters=dict(source="official",asset_kind="character",role_level="lead",role_tag=payload["role_tag"],
            gender="female",age_band="young_adult",query="合成共享",media_only=True,limit=1)
        page=self.service.search_asset_center(filters,"test-human")
        self.assertEqual(page["total"],1);self.assertIsNone(page["next_offset"])
        row=page["items"][0]
        self.assertEqual(row["source"],"official");self.assertEqual(row["official"]["publisher"],"test-human")
        self.assertEqual(row["official"]["id"],published["id"])
        self.assertEqual(row["library_version_id"],fixed["version_id"])
        for changes in ({"gender":"male"},{"age_band":"child"},{"role_level":"extra"},{"asset_kind":"prop"},{"query":"missing"},{"role_tag":"missing"}):
            with self.subTest(changes=changes):self.assertEqual(self.service.search_asset_center(dict(filters,**changes))["total"],0)
        # New shared versions do not rewrite the explicit official version.
        newer=self.shared(key)
        self.assertNotEqual(newer["version_id"],fixed["version_id"])
        self.assertEqual(self.service.search_asset_center(filters)["items"][0]["version_id"],fixed["version_id"])
        shared=self.service.search_asset_center({"query":"合成共享"})
        self.assertTrue(all(row["source"]=="shared" for row in shared["items"]))
        self.assertIn(newer["version_id"],[row["version_id"] for row in shared["items"]])
        with self.assertRaises(ResourceError):self.service.search_asset_center({"source":"official","gender":"invented"})
        with self.assertRaises(ResourceError):self.service.search_asset_center({"source":"pretend-official"})

    def test_official_cross_project_reuse_and_revoked_source_rejected(self):
        fixed=self.shared();payload=self.official_payload(fixed);published=self.publish(payload)
        cart=self.service.change_asset_center_cart({"library_version_id":fixed["version_id"],"member_key":"front","active":True},"test-human")
        selected=next(row for row in self.service.asset_center_cart("test-human")["items"] if row["id"]==cart["id"])
        self.assertEqual(selected["official"]["id"],published["id"])
        use={"cart_id":cart["id"],"asset_kind":"character","role":"identity_face"}
        first=self.write("import_asset_center_item",use)
        other=self.service.create_project({"name":"官方素材第二目标"},actor="test-human")
        second=self.service.import_asset_center_item(other["id"],use,actor="test-human",expected_revision=0,idempotency_key="official-second")
        self.assertNotEqual(first["media_id"],second["media_id"])
        self.assertNotEqual(first["candidate_id"],second["candidate_id"])
        self.assertEqual(self.service.get_media(self.p,first["media_id"])["blob_id"],self.service.get_media(other["id"],second["media_id"])["blob_id"])
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            reuses=conn.execute(select(S.library_reuses).where(S.library_reuses.c.library_version_id==fixed["version_id"],S.library_reuses.c.reuse_mode=="reference")).mappings().all()
            self.assertEqual({str(row["project_id"]) for row in reuses},{self.p,other["id"]})
            self.assertEqual(conn.execute(select(func.count()).select_from(S.binding_decisions).where(S.binding_decisions.c.project_id.in_([self.p,other["id"]]))).scalar_one(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id.in_([self.p,other["id"]]))).scalar_one(),0)
        self.service.retire_library(fixed["entry_id"],{"outcome":"revoke_rights","reason":"合成撤权证据","idempotency_key":uuid.uuid4().hex},actor="test-human")
        self.assertEqual(self.service.search_asset_center({"source":"official","role_tag":payload["role_tag"]})["total"],0)
        third=self.service.create_project({"name":"撤权后目标"},actor="test-human")
        with self.assertRaises(ResourceError):self.service.import_asset_center_item(third["id"],use,actor="test-human",expected_revision=0,idempotency_key="revoked-official")
        with self.assertRaises(ResourceError):self.publish(self.official_payload(fixed))

    def test_official_database_constraints_and_immutable_publication(self):
        from sqlalchemy import insert,update,delete
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import new_id,digest
        fixed=self.shared();other=self.shared();published=self.publish(self.official_payload(fixed))
        row=dict(self.official_payload(other),id=new_id(),publisher="test-human",request_sha256=digest({}))
        cases=[({"entry_id":fixed["entry_id"]},"23503"),({"role_level":"invented"},"23514"),
            ({"asset_kind":"prop"},"23514"),({"gender":"invented"},"23514"),({"age_band":"invented"},"23514"),
            ({"role_tag":""},"23514"),({"library_version_id":fixed["version_id"],"entry_id":fixed["entry_id"]},"23505")]
        for changes,code in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError) as rejected:
                    with self.engine.begin() as conn:conn.execute(insert(S.official_asset_publications).values(**dict(row,**changes)))
                self.assertEqual(rejected.exception.orig.sqlstate,code)
        for statement in (update(S.official_asset_publications).values(publisher="spoofed"),delete(S.official_asset_publications)):
            with self.assertRaises(IntegrityError) as rejected:
                with self.engine.begin() as conn:conn.execute(statement.where(S.official_asset_publications.c.id==published["id"]))
            self.assertEqual(rejected.exception.orig.sqlstate,"23514")

    def test_official_facets_pagination_and_competing_publishers(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        prefix="facet-"+uuid.uuid4().hex
        fixed=[]
        for n in range(3):
            item=self.shared();fixed.append(item)
            self.publish(self.official_payload(item,role_tag=prefix+str(n),gender="male" if n==0 else "female"))
        filters={"source":"official","asset_kind":"character","query":prefix,"limit":1}
        pages=[self.service.search_asset_center(dict(filters,offset=n)) for n in range(3)]
        self.assertEqual([page["total"] for page in pages],[3,3,3])
        self.assertEqual([page["next_offset"] for page in pages],[1,2,None])
        self.assertEqual(len({page["items"][0]["version_id"] for page in pages}),3)
        filtered=self.service.search_asset_center(dict(filters,gender="male",role_tag=prefix+"0"))
        self.assertEqual(filtered["total"],1)
        self.assertTrue({prefix+str(n) for n in range(3)}<=set(filtered["facets"]["role_tag"]))
        self.assertEqual(set(filtered["facets"]["gender"]),{"female","male"})
        unrelated=self.shared()
        self.service.edit_asset_catalog(dict(entry_id=unrelated["entry_id"],library_version_id=unrelated["version_id"],expected_revision=0,
            asset_kind="character",form_name="共享来源标签",workspace_id=None,review_status="draft",notes="",tags=[prefix+"shared"],command_key=uuid.uuid4().hex),"test-human")
        self.assertNotIn(prefix+"shared",self.service.search_asset_center(filters)["facets"]["role_tag"])
        with self.assertRaises(ResourceError):self.service.search_asset_center({"source":"shared","gender":"female"})
        with self.assertRaises(ResourceError):self.service.search_asset_center({"source":"official","tag":prefix+"shared"})
        candidate=self.shared();payload=self.official_payload(candidate);barrier=Barrier(2)
        def attempt(n):
            barrier.wait(timeout=10)
            try:return self.service.publish_official_asset(dict(payload,command_key="race-"+str(n)),"test-human")
            except Conflict as error:return error.code
        with patch("vsc.configuration.get_config",return_value=["test-human"]):
            with ThreadPoolExecutor(max_workers=2) as workers:results=list(workers.map(attempt,range(2)))
        self.assertEqual(sum(isinstance(row,dict) for row in results),1)
        self.assertEqual(sum(row=="official_publication_exists" for row in results),1)

    def test_official_http_publisher_gate_facets_and_original_import(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        fixed=self.shared();payload=self.official_payload(fixed)
        app=create_app({"projects_root":self.tmp.name,"allowed_hosts":["testserver"],"allowed_origins":["http://testserver"],
            "access_token":"official-local-test","human_identity":"test-human","background_enabled":False},service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/asset-center?source=official').status_code,403)
            login=client.post('/api/v1/session',json={"token":"official-local-test"},headers={"Origin":"http://testserver"})
            self.assertEqual(login.status_code,200,login.text)
            headers={"Origin":"http://testserver","X-CSRF-Token":login.json()["csrf_token"]}
            with patch("vsc.configuration.get_config",return_value=[]):
                denied=client.post('/api/v1/asset-center/official/publish',headers=headers,json={"payload":payload})
            self.assertEqual(denied.status_code,403,denied.text)
            with patch("vsc.configuration.get_config",return_value=["test-human"]):
                published=client.post('/api/v1/asset-center/official/publish',headers=headers,json={"payload":payload})
            self.assertEqual(published.status_code,200,published.text)
            response=client.get('/api/v1/asset-center',headers=headers,params={"source":"official","asset_kind":"character","role_tag":payload["role_tag"],"gender":"female","age_band":"young_adult","role_level":"lead","media_only":"true"})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["total"],1)
            self.assertIn(payload["role_tag"],response.json()["facets"]["role_tag"])
            self.assertEqual(client.get('/api/v1/asset-center?source=official&gender=invented',headers=headers).status_code,422)
            cart=client.post('/api/v1/asset-center/cart',headers=headers,json={"payload":{"library_version_id":fixed["version_id"],"member_key":"front","active":True}})
            self.assertEqual(cart.status_code,200,cart.text)
            result=client.post('/api/v1/projects/'+self.p+'/asset-center/import',headers=headers,json={"payload":{"cart_id":cart.json()["id"],"asset_kind":"character","role":"identity_face"},"expected_revision":self.rev,"idempotency_key":"official-http-import"})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(self.service.get_asset_card(self.p,result.json()["target_object_id"])["forms"][0]["media_id"],result.json()["media_id"])

    def test_official_migration_preserves_legacy_and_refuses_lost_publications(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import text,select,func
        from sqlalchemy.exc import IntegrityError
        from support.paths import ROOT
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres import schema as S
        def migrate(connection,target,action):
            config=Config(str(ROOT/'migrations/postgres/alembic.ini'));config.attributes['connection']=connection
            getattr(command,action)(config,target)
        with isolated_postgres(TEST_URL) as engine:
            from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
            from vsc.assets.resource_service import ResourceService
            service=ResourceService(PostgresResourceStore(engine=engine),storage=self.service.storage)
            # Old sharing command remains usable before the additive migration.
            with engine.begin() as conn:migrate(conn,'0047_professional_inputs','downgrade')
            staged=service.storage.stage_upload(io.BytesIO(png_bytes()),"legacy.png")
            fixed=service.import_library({"library_key":uuid.uuid4().hex,"title":"旧共享数据","category":"image","description":"legacy synthetic",
                "specification":{},"allowed_purposes":["identity_face"],"license":{"outcome":"owned","allow_workspace_reuse":True,"evidence":"legacy owned bytes"},
                "import_key":uuid.uuid4().hex,"members":[{"member_key":"front","staged_upload":staged["staged_upload"]}]},actor="test-human")
            with engine.begin() as conn:
                before=conn.execute(select(S.library_entry_versions.c.sha256).where(S.library_entry_versions.c.id==fixed["version_id"])).scalar_one()
                migrate(conn,'head','upgrade')
                self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
                self.assertEqual(conn.execute(select(func.count()).select_from(S.official_asset_publications)).scalar_one(),0)
                self.assertEqual(conn.execute(select(S.library_entry_versions.c.sha256).where(S.library_entry_versions.c.id==fixed["version_id"])).scalar_one(),before)
            with patch("vsc.configuration.get_config",return_value=["test-human"]):service.publish_official_asset(self.official_payload(fixed),"test-human")
            with self.assertRaises(IntegrityError):
                with engine.begin() as conn:migrate(conn,'0047_professional_inputs','downgrade')
            with engine.connect() as conn:
                self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),S.SCHEMA_REVISION)
                self.assertEqual(conn.execute(select(func.count()).select_from(S.official_asset_publications)).scalar_one(),1)
