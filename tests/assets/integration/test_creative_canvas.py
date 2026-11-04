"""Real PostgreSQL canvas history, typed references, preparation and recovery."""
from copy import deepcopy
import importlib.util
import os
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DB, "requires configured isolated PostgreSQL")
class CreativeCanvasTests(ResourceStoreFixture, unittest.TestCase):
    def test_grid_tracks_copied_media_source_rights(self):
        import io, tempfile
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from threading import Event
        from PIL import Image
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceError
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                data=io.BytesIO();Image.new('RGB',(8,8),'green').save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'source.png')
                parent=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned',
                    'source':{'kind':'test','content':'owned image'}})['id']
                card=self.write('save_asset_card',dict(name='source',asset_kind='character',base_revision=0,
                    forms=[dict(form_key='master',name='default',base_version_id=None,media_id=parent)]))
                source_project,source_revision=self.p,self.rev
                target=self.service.create_project({'name':'copy target'},actor='test-human')['id']
                copied=self.service.copy_asset_card(target,dict(source_project_id=source_project,source_asset_id=card['id'],
                    form_version_ids=[card['forms'][0]['version_id']]),actor='test-human',expected_revision=0,idempotency_key='copy-grid')
                self.p,self.rev=target,copied['revision']
                copy_media=copied['forms'][0]['media_id']
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':copy_media}],'edges':[]}})
                child=self.write('split_canvas_image',dict(canvas_id=canvas['id'],canvas_revision=1,node_id='source',
                    rows=2,columns=2,cells=[{'row':1,'column':1}]))['media_ids'][0]
                def gaps():
                    with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:
                        return self.store._usable(conn,self.p,child,'identity_face')[1]
                self.assertEqual(gaps(),[])
                shot=self.hierarchy()['shot'];candidate=self.candidate(shot,child,role='first_frame')
                locked,release=Event(),Event();original=self.store._one
                def hold_source(conn,table,p,identifier):
                    row=original(conn,table,p,identifier)
                    if p==source_project and table is S.media_items and identifier==parent:
                        locked.set()
                        if not release.wait(10):raise RuntimeError('source lock test timed out')
                    return row
                def revoke():
                    return self.service.decide_rights(source_project,dict(media_id=parent,outcome='revoked',reason='revoked'),
                        actor='test-human',expected_revision=source_revision,idempotency_key='revoke-copy-source')
                def select_child():
                    return self.service.select_candidate(self.p,dict(candidate_id=candidate['candidate_id'],reason='choose'),
                        actor='test-human',expected_revision=self.rev,idempotency_key='concurrent-grid-select')
                with patch.object(self.store,'_one',side_effect=hold_source),ThreadPoolExecutor(max_workers=2) as pool:
                    changing=pool.submit(revoke);self.assertTrue(locked.wait(10));choosing=pool.submit(select_child)
                    try:
                        with self.assertRaises(TimeoutError):choosing.result(timeout=.25)
                    finally:release.set()
                    changing.result(timeout=10)
                    with self.assertRaises(ResourceError):choosing.result(timeout=10)
                self.assertTrue(any('copy_source_rights_restricted' in gap for gap in gaps()))
            finally:self.service.storage=previous

    def test_grid_tracks_shared_library_live_rights(self):
        import io, tempfile
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                data=io.BytesIO();Image.new('RGB',(8,8),'blue').save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'library.png')
                library=self.service.import_library(dict(library_key='grid-'+uuid.uuid4().hex,title='Grid source',category='image',
                    description='synthetic',specification={},allowed_purposes=['image_edit','identity_face'],
                    license={'outcome':'owned','allow_workspace_reuse':True,'evidence':'synthetic'},
                    import_key=uuid.uuid4().hex,members=[{'member_key':'front','staged_upload':staged['staged_upload']}]),actor='test-human')
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[],'edges':[]}})
                added=self.write('add_canvas_library_node',dict(canvas_id=canvas['id'],canvas_revision=1,
                    library_version_id=library['version_id'],member_key='front',role='identity_face',x=0,y=0))
                result=self.write('split_canvas_image',dict(canvas_id=canvas['id'],canvas_revision=2,node_id=added['node_id'],
                    rows=2,columns=2,cells=[{'row':1,'column':1}]))
                child=result['media_ids'][0]
                def gaps():
                    with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:
                        return self.store._usable(conn,self.p,child,'identity_face')[1]
                self.assertEqual(gaps(),[])
                self.service.retire_library(library['entry_id'],{'outcome':'revoke_rights','reason':'revoked',
                    'idempotency_key':'grid-library-revoke'},actor='test-human')
                self.assertTrue(any('library_rights_revoked' in gap for gap in gaps()))
            finally:self.service.storage=previous

    def test_grid_inherited_rights_are_live_and_generic_operations_cannot_forge_them(self):
        import io, tempfile
        from PIL import Image
        from sqlalchemy import select, func, insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                data=io.BytesIO();Image.new('RGB',(8,8),'red').save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'source.png')
                parent=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned',
                    'source':{'kind':'test','content':'owned image'}})['id']
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':parent}],'edges':[]}})
                payload={'canvas_id':canvas['id'],'canvas_revision':1,'node_id':'source','rows':2,'columns':2,'cells':[{'row':1,'column':1}]}
                before=self.rev;first=self.write('split_canvas_image',payload,idempotency_key='first-grid')
                self.assertEqual(self.service.split_canvas_image(self.p,payload,expected_revision=before,idempotency_key='first-grid',actor='test-human'),first)
                child=first['media_ids'][0]
                def gaps(identifier,purpose='identity_face'):
                    with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:
                        return self.store._usable(conn,self.p,identifier,purpose)[1]
                self.assertEqual(gaps(child),[])
                with self.engine.connect() as conn:
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_checks).where(
                        S.media_checks.c.project_id==self.p,S.media_checks.c.media_id==child)),1)
                nested=self.write('split_canvas_image',dict(payload,canvas_revision=2,node_id=first['node_ids'][0]),idempotency_key='second-grid')['media_ids'][0]
                with patch.object(self.store,'_grid_parent',wraps=self.store._grid_parent) as lookups:
                    self.assertEqual(gaps(nested),[])
                    # One per distinct media/purpose; repeated image_edit
                    # ancestry is reused only within this call.
                    self.assertEqual(lookups.call_count,5)
                self.write('decide_rights',dict(media_id=parent,outcome='revoked',reason='source revoked'))
                self.assertTrue(any('rights_unknown_or_restricted' in gap for gap in gaps(nested)))
                source=self.service.get_media(self.p,parent)['sources'][0]['source_id']
                self.write('decide_rights',dict(media_id=parent,outcome='licensed',source_id=source,
                    scope={'purposes':['image_edit']},reason='edit only'))
                self.assertTrue(any('rights_scope_mismatch' in gap for gap in gaps(nested)))
                self.write('decide_rights',dict(media_id=parent,outcome='licensed',source_id=source,
                    scope={'purposes':['image_edit','identity_face']},expires_at='2000-01-01T00:00:00+00:00',reason='expired'))
                self.assertTrue(any('rights_expired' in gap for gap in gaps(nested)))
                self.write('decide_rights',dict(media_id=parent,outcome='owned',source_id=source,
                    scope={'purposes':['*']},reason='restored'))
                self.write('record_media_check',dict(media_id=child,checker='independent-review',criteria_version='1',outcome='fail'))
                self.assertIn('technical_check_failed',gaps(child))
                self.assertTrue(any('technical_check_failed' in gap for gap in gaps(nested)))
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'fake.png')
                fake=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'unknown'})['id']
                self.write('create_media_operation',dict(operation_type='image-grid-split',recipe_version='canvas-grid/v1',
                    tool='vsc-local-image-grid',tool_version='1',parameters={'source_sha256':self.service.get_media(self.p,parent)['sha256'],'cells':[{'row':1,'column':1}]},
                    inputs=[{'media_id':parent,'role':'source'}],outputs=[{'media_id':fake,'role':'tile'}]))
                self.assertIn('rights_unknown_or_restricted',gaps(fake))
                # Historical duplicate authority evidence is ambiguous and must fail closed.
                with self.engine.begin() as conn:
                    response=conn.execute(select(S.command_receipts.c.response).where(
                        S.command_receipts.c.project_id==self.p,S.command_receipts.c.idempotency_key=='first-grid')).scalar_one()
                    conn.execute(insert(S.project_revisions).values(project_id=self.p,revision=self.rev+1000,
                        actor='test-fixture',action='split_canvas_image',command_key='duplicate-fixture'))
                    conn.execute(insert(S.command_receipts).values(project_id=self.p,idempotency_key='duplicate-fixture',
                        request_sha256='0'*64,response=response))
                self.assertIn('rights_unknown_or_restricted',gaps(child))
            finally:self.service.storage=previous

    def test_grid_split_preserves_selection_receipt_pixels_and_lineage(self):
        import io, tempfile
        from PIL import Image
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import Conflict, ResourceError
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                image=Image.new('RGB',(8,8),'red')
                for y in range(4,8):
                    for x in range(4,8):image.putpixel((x,y),(0,0,255))
                data=io.BytesIO();image.save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'source.png')
                media=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned','source':{'kind':'test','content':'synthetic owned image'}})['id']
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':media}],'edges':[]}})
                payload={'canvas_id':canvas['id'],'canvas_revision':1,'node_id':'source','rows':2,'columns':2,'cells':[{'row':2,'column':2},{'row':1,'column':1}]}
                before=self.rev;result=self.write('split_canvas_image',payload,idempotency_key='grid-replay')
                replay=self.service.split_canvas_image(self.p,payload,expected_revision=before,idempotency_key='grid-replay',actor='test-human')
                self.assertEqual(replay,result);self.assertEqual(result['canvas_revision'],2);self.assertEqual(len(result['node_ids']),2)
                opened=self.service.get_creative_canvas(self.p,canvas['id'],2)['document'];by_id={node['id']:node for node in opened['nodes']}
                self.assertEqual([by_id[key]['media_id'] for key in result['node_ids']],result['media_ids'])
                self.assertEqual([(edge['source'],edge['target'],edge['port']) for edge in opened['edges']], [('source',key,'derived_from') for key in result['node_ids']])
                for identifier,color in zip(result['media_ids'],[(0,0,255),(255,0,0)]):
                    row=self.service.get_media(self.p,identifier);self.assertEqual(row['rights']['outcome'],'unknown')
                    path=next(item for item in row['locations'] if item['storage']=='local')['object_key']
                    with Image.open(io.BytesIO(self.service.storage.read(path,row['sha256']))) as tile:self.assertEqual(tile.convert('RGB').getpixel((0,0)),color)
                with self.engine.connect() as conn:
                    operation=conn.execute(select(S.media_operations).where(S.media_operations.c.id==result['operation_id'])).mappings().one()
                    self.assertEqual(operation['parameters']['cells'],payload['cells'])
                    outputs=conn.execute(select(S.operation_outputs.c.media_id).where(S.operation_outputs.c.operation_id==result['operation_id']).order_by(S.operation_outputs.c.ordinal)).scalars().all()
                    self.assertEqual(outputs,result['media_ids'])
                from fastapi.testclient import TestClient
                from vsc.interfaces.web.app import create_app
                from vsc.project.resource_catalog import ResourceCatalog
                app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test-token','human_identity':'test-human'},catalog=ResourceCatalog(directory,self.service),service=self.service)
                with TestClient(app) as client:
                    unauthorized=client.post('/api/v1/projects/'+self.p+'/creative-canvases/'+canvas['id']+'/split-image',json={'payload':payload,'expected_revision':before,'idempotency_key':'other'})
                    self.assertIn(unauthorized.status_code,(401,403))
                    login=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'})
                    response=client.post('/api/v1/projects/'+self.p+'/creative-canvases/'+canvas['id']+'/split-image',
                        json={'payload':{key:value for key,value in payload.items() if key!='canvas_id'},'expected_revision':before,'idempotency_key':'grid-replay'},
                        headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']})
                    self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json(),result)
                with self.assertRaises(Conflict):self.write('split_canvas_image',payload)
                with self.assertRaises(ResourceError):self.write('split_canvas_image',dict(payload,canvas_revision=2,cells=[{'row':1,'column':1},{'row':1,'column':1}]))
            finally:self.service.storage=previous

    def test_grid_split_rolls_back_failed_registration_and_checks_source_bytes(self):
        import io, tempfile
        from PIL import Image
        from sqlalchemy import func,select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceError
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                data=io.BytesIO();Image.new('RGB',(2,2),'red').save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'source.png')
                media=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'owned','source':{'kind':'test','content':'synthetic source'}})['id']
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':media}],'edges':[]}})
                payload={'canvas_id':canvas['id'],'canvas_revision':1,'node_id':'source','rows':2,'columns':2,'cells':[{'row':1,'column':1},{'row':2,'column':2}]}
                with self.assertRaises(ResourceError) as dimensions:self.write('split_canvas_image',dict(payload,rows=3))
                self.assertEqual(dimensions.exception.code,'canvas_grid_dimensions')
                original=self.store._register_media;calls=[]
                def fail_second(*args):
                    calls.append(1)
                    if len(calls)==2:raise ResourceError('synthetic failure')
                    return original(*args)
                with patch.object(self.store,'_register_media',side_effect=fail_second),self.assertRaises(ResourceError):
                    self.write('split_canvas_image',payload,idempotency_key='retry-grid')
                self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['canvas_revision'],1)
                with self.engine.connect() as conn:
                    self.assertEqual(conn.execute(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==self.p)).scalar_one(),1)
                result=self.write('split_canvas_image',payload,idempotency_key='retry-grid');self.assertEqual(len(result['node_ids']),2)
                original_media=self.service.get_media(self.p,media);location=next(item for item in original_media['locations'] if item['storage']=='local')
                self.service.storage.resolve(location['object_key']).write_bytes(b'tampered')
                with self.assertRaises(ResourceError) as error:self.write('split_canvas_image',dict(payload,canvas_revision=2))
                self.assertEqual(error.exception.code,'media_sha_mismatch')
                self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['canvas_revision'],2)
            finally:self.service.storage=previous

    def test_grid_split_rejects_unusable_and_preserves_canvas_on_failure(self):
        import io, tempfile
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceError
        with tempfile.TemporaryDirectory() as directory:
            previous=self.service.storage;self.service.storage=LocalStorage(directory)
            try:
                data=io.BytesIO();Image.new('RGB',(2,2),'red').save(data,format='PNG')
                staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'source.png')
                media=self.write('register_media',{'staged_upload':staged['staged_upload'],'rights':'unknown'})['id']
                canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'source','type':'image','media_id':media}],'edges':[]}})
                payload={'canvas_id':canvas['id'],'canvas_revision':1,'node_id':'source','rows':2,'columns':2,'cells':[{'row':1,'column':1}]}
                with self.assertRaises(ResourceError) as error:self.write('split_canvas_image',payload)
                self.assertEqual(error.exception.code,'canvas_grid_source_unusable')
                self.assertIn('素材权利待确认或受限制',str(error.exception))
                for cells in ([],[{'row':3,'column':1}],[{'row':True,'column':1}]):
                    with self.assertRaises(ResourceError):self.write('split_canvas_image',dict(payload,cells=cells))
                self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['canvas_revision'],1)
            finally:self.service.storage=previous

    def test_library_node_preserves_fixed_source_without_asset_or_generation(self):
        import io
        import tempfile
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.storage.local.store import LocalStorage
        from support.fixtures.resources import png_bytes
        from vsc.assets.resource_service import Conflict, ResourceError
        with tempfile.TemporaryDirectory() as directory:
            previous = self.service.storage
            self.service.storage = LocalStorage(directory)
            try:
                uploaded = self.service.storage.stage_upload(io.BytesIO(png_bytes()), "reference.png")
                fixed = self.service.import_library({"library_key": "canvas-" + uuid.uuid4().hex,
                    "title": "Fixed library reference", "category": "image", "description": "Synthetic owned image",
                    "specification": {}, "allowed_purposes": ["identity_face"],
                    "license": {"outcome": "owned", "allow_workspace_reuse": True, "evidence": "synthetic bytes"},
                    "import_key": uuid.uuid4().hex, "members": [{"member_key": "front", "staged_upload": uploaded["staged_upload"]}]}, actor="test-human")
                canvas = self.write("create_creative_canvas", {"title": "Reference canvas", "document": {"nodes": [], "edges": []}})
                payload = {"canvas_id": canvas["id"], "canvas_revision": 1, "library_version_id": fixed["version_id"],
                    "member_key": "front", "role": "identity_face", "x": 80, "y": 100}
                before = self.rev
                result = self.write("add_canvas_library_node", payload, idempotency_key="library-node")
                replay = self.service.add_canvas_library_node(self.p, payload, actor="test-human", expected_revision=before, idempotency_key="library-node")
                self.assertEqual(result, replay)
                opened = self.service.get_creative_canvas(self.p, canvas["id"])
                self.assertEqual(opened["canvas_revision"], 2)
                self.assertEqual(opened["document"]["nodes"][0]["media_id"], result["media_id"])
                self.assertEqual(opened["document"]["nodes"][0]["id"], result["node_id"])
                with self.engine.connect() as conn:
                    for table in (S.creative_objects, S.binding_candidates, S.generation_jobs):
                        self.assertEqual(conn.execute(select(func.count()).select_from(table).where(table.c.project_id == self.p)).scalar_one(), 0)
                    reuse = conn.execute(select(S.library_reuses).where(S.library_reuses.c.project_id == self.p)).mappings().one()
                    self.assertEqual(reuse["library_version_id"], fixed["version_id"])
                    self.assertEqual(reuse["member_key"], "front")
                with self.assertRaises(Conflict):self.write("add_canvas_library_node", payload)
                with self.assertRaises(ResourceError):self.write("add_canvas_library_node", dict(payload, canvas_revision=2, role="voice_sample"))
                self.service.retire_library(fixed["entry_id"], {"outcome": "revoke_rights", "reason": "Synthetic revocation",
                    "idempotency_key": "revoke-canvas-reference"}, actor="test-human")
                with self.assertRaises(ResourceError):self.write("add_canvas_library_node", dict(payload, canvas_revision=2))
                with self.engine.connect() as conn:
                    self.assertEqual(conn.execute(select(func.count()).select_from(S.library_reuses).where(S.library_reuses.c.project_id == self.p)).scalar_one(), 1)
            finally:
                self.service.storage = previous

    def document(self, media=None, job=None):
        return {"nodes": [{"id": "prompt", "type": "text", "text": "固定画面"},
            {"id": "image", "type": "image", "media_id": media},
            {"id": "video", "type": "video", "job_id": job}],
            "edges": [{"id": "text-video", "source": "prompt", "target": "video", "port": "prompt"},
                {"id": "image-video", "source": "image", "target": "video", "port": "first_frame"}]}

    def test_saved_versions_reopen_replay_conflict_and_copy_clear_execution(self):
        from vsc.assets.resource_service import Conflict
        media = self.media()
        canvas = self.write("create_creative_canvas", {"title": "草稿", "document": self.document(media)})
        opened = self.service.get_creative_canvas(self.p, canvas["id"])
        document = opened["document"]
        for node in document["nodes"]:
            node.pop("preview_url", None)
        document["nodes"][0]["text"] = "保存后的画面"
        payload = {"canvas_id": canvas["id"], "canvas_revision": 1, "title": "已编辑", "document": document}
        revision = self.rev
        saved = self.write("save_creative_canvas", payload, idempotency_key="save-canvas")
        replay = self.service.save_creative_canvas(self.p, payload, actor="test-human", expected_revision=revision,
            idempotency_key="save-canvas")
        self.assertEqual(saved, replay)
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"])["document"]["nodes"][0]["text"], "保存后的画面")
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"], 1)["document"]["nodes"][0]["text"], "固定画面")
        with self.assertRaises(Conflict):
            self.write("save_creative_canvas", payload)
        self.assertEqual(len(self.service.creative_canvas_history(self.p, canvas["id"])["items"]), 2)
        copied = self.write("copy_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 1})
        duplicate = self.service.get_creative_canvas(self.p, copied["id"])
        self.assertEqual(duplicate["document"]["nodes"][1]["media_id"], media)
        self.assertEqual(duplicate["preparations"], [])
        self.assertTrue(all(n["job_id"] is None for n in duplicate["document"]["nodes"]))

    def test_rejects_cross_project_type_cycle_dangling_and_sealed_append(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres import schema as S
        from sqlalchemy import insert, select, update
        from sqlalchemy.exc import IntegrityError
        media = self.media()
        for scenario in ("wrong_port", "cycle", "missing_node", "wrong_media", "foreign_media"):
            document = self.document(media)
            if scenario == "wrong_port":
                document["edges"][1]["port"] = "reference_audio"
            elif scenario == "cycle":
                document["nodes"].append({"id": "other", "type": "image"})
                document["edges"].extend([{"id": "a", "source": "image", "target": "other", "port": "reference"},
                    {"id": "b", "source": "other", "target": "image", "port": "reference"}])
            elif scenario == "missing_node":
                document["edges"][1]["source"] = "absent"
            elif scenario == "wrong_media":
                document["nodes"][2]["media_id"] = media
            else:
                document["nodes"][1]["media_id"] = str(uuid.uuid4())
            with self.subTest(scenario=scenario), self.assertRaises(ResourceError):
                self.write("create_creative_canvas", {"title": scenario, "document": document})
        canvas = self.write("create_creative_canvas", {"document": self.document(media)})
        with self.engine.connect() as conn:
            original = dict(conn.execute(select(S.creative_canvas_nodes).where(S.creative_canvas_nodes.c.project_id == self.p,
                S.creative_canvas_nodes.c.version_id == canvas["version_id"])).mappings().first())
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.creative_canvas_nodes).values(dict(original, node_key="late", ordinal=99)))
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.creative_canvas_nodes).where(S.creative_canvas_nodes.c.project_id == self.p).values(title="tampered"))
        other = self.service.create_project({"name": "other", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.service.create_creative_canvas(other["id"], {"document": self.document(media)}, expected_revision=0,
                idempotency_key=uuid.uuid4().hex, actor="test-human")

    def test_preparation_consumes_graph_and_original_job_unknown_is_not_resubmitted(self):
        from sqlalchemy import insert, select, func
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        self.artifact("state", "scene-state", [objects["scene"]], {"state_versions": [{"scene_id": objects["scene"]}]})
        image = self.media()
        self.select(self.candidate(objects["shot"], image))
        provider, model = "synthetic_" + uuid.uuid4().hex, str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name="synthetic nonexecuting", modality="video",
                base_url="https://example.invalid", auth_ref="none", enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key="synthetic", modality="video",
                model_version="1", capabilities={"purposes": ["video_clip"], "first_frame": True}, default_params={}, cost_rule={}, enabled=True))
        request = {"prompt": "固定画面", "params": {}, "first_frame_media_id": image}
        run = self.production_run(objects["shot"], request)
        context = self.service.compile_shot_context(self.p, objects["shot"], "video_clip")
        job = self.write("create_generation_job", {"run_version_id": run, "shot_id": objects["shot"], "purpose": "video_clip",
            "modality": "video", "model_id": model, "context_sha256": context["sha256"], "request_payload": request})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submission_unknown"})
        canvas = self.write("create_creative_canvas", {"episode_id": objects["episode"], "document": self.document(image, job["id"])})
        payload = {"canvas_id": canvas["id"], "canvas_revision": 1, "node_id": "video"}
        with patch("httpx.Client.post") as provider_submit:
            prepared = self.write("prepare_creative_canvas", payload, idempotency_key="prepare")
            provider_submit.assert_not_called()
        self.assertTrue(prepared["ready"], prepared["gaps"])
        self.assertEqual(prepared["inputs"][0]["media_id"], image)
        self.assertEqual(prepared["prompt"], request["prompt"])
        self.assertEqual(prepared["job"]["status"], "submission_unknown")
        self.assertTrue(prepared["job"]["recovery_required"])
        self.assertFalse(prepared["provider_submitted"])
        replay = self.service.prepare_creative_canvas(self.p, payload, expected_revision=0,
            idempotency_key="prepare", actor="test-human")
        self.assertEqual(prepared, replay)
        run_request = {"canvas_id": canvas["id"], "canvas_revision": 1, "node_id": "video", "shot_id": objects["shot"],
            "model_id": model, "duration_ms": 5000, "execution_policy": {"version": "bounded-v1",
                "first_draft_due_at": "2099-01-01T00:00:00Z", "stop_submitting_at": "2099-01-01T01:00:00Z",
                "max_attempts_per_purpose": 3, "max_repair_rounds": 1}}
        unavailable = self.service.preview_creative_canvas_run(self.p, run_request)
        self.assertFalse(unavailable["ready"])
        self.assertEqual(unavailable["gaps"][0]["code"], "canvas_no_applicable_model")
        self.assertEqual(unavailable["routing"]["original_model_ids"], [model])
        self.assertEqual(unavailable["routing"]["candidates"][0]["code"], "model_adapter_unavailable")
        self.assertNotIn("preview_sha256", unavailable)
        # This provider is deliberately synthetic. Only the offline compiler
        # fixture supplies availability; no real adapter or transport is invoked.
        configuration = {"id": model, "enabled": True, "adapter_available": True,
            "modality": "video", "capabilities": {"purposes": ["video_clip"], "first_frame": True}}
        with patch("vsc.production.resource_settings.ResourceSettings.list", return_value={"configurations": [configuration]}), patch("httpx.Client.post") as provider_submit:
            preview = self.service.preview_creative_canvas_run(self.p, run_request)
            self.assertTrue(preview["ready"], preview["gaps"])
            proposed = self.write("propose_creative_canvas_run", {"request": run_request, "preview_sha256": preview["preview_sha256"]})
            provider_submit.assert_not_called()
        self.assertTrue(proposed["needs_approval"])
        self.assertFalse(proposed["provider_submitted"])
        import json
        run_artifact = self.service.get_artifact_version(self.p, proposed["artifact_id"])
        run_document = json.loads(run_artifact["document"])
        self.assertEqual(run_document["series_batch"]["jobs"][0]["request"]["prompt"], "固定画面")
        self.assertEqual(run_document["series_batch"]["jobs"][0]["request"]["first_frame_media_id"], image)
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"])["runs"][0]["artifact_id"], proposed["artifact_id"])
        doc = self.document(image, job["id"])
        doc["nodes"][0]["text"] = "不同输入"
        self.write("save_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 1, "document": doc})
        mismatch = self.write("prepare_creative_canvas", dict(payload, canvas_revision=2))
        self.assertIn("job_prompt_mismatch", mismatch["gaps"])
        self.assertFalse(mismatch["ready"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id == self.p)).scalar_one(), 1)
        self.write("save_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 2, "document": {"nodes": [], "edges": []}})
        self.assertEqual(self.service.get_generation_job(self.p, job["id"])["status"], "submission_unknown")
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"], 1)["preparations"][0]["job_id"], job["id"])

@unittest.skipUnless(TEST_URL and HAS_DB, 'requires isolated PostgreSQL')
class CanvasExecutionTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.artifact(objects=[self.objects['shot']]);self.artifact('state','scene-state',[self.objects['scene']],{'state_versions':[{'scene_id':self.objects['scene']}]})
        self.policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=3,max_repair_rounds=1,authorization={'mode':'new_batch','reason':'合成工程批次'})
        self.models=[]
        for modality,purpose in [('image','shot_keyframe'),('image','shot_keyframe'),('audio','sfx'),('video','video_clip')]:
            provider='synthetic_'+uuid.uuid4().hex;self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
            model=self.service.register_model(dict(provider_id=provider,model_key=modality,model_version='offline',modality=modality,capabilities=dict(purposes=[purpose],first_frame=True)),actor='test-admin');self.models.append(dict(model,adapter_available=True,enabled=True))
        self.config=patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':self.models});self.config.start();self.addCleanup(self.config.stop)
        self.canvas=self.write('create_creative_canvas',dict(episode_id=self.objects['episode'],document={'nodes':[{'id':'i','type':'image','text':'独立构图'},{'id':'a','type':'audio','text':'雨声'},{'id':'v','type':'video','text':'走近'}],'edges':[{'id':'iv','source':'i','target':'v','port':'first_frame'}]}))
    def request(self,node='i'):
        model=self.models[0 if node=='i' else 2 if node=='a' else 3]
        return dict(canvas_id=self.canvas['id'],canvas_revision=1,node_id=node,shot_id=self.objects['shot'],purpose=model['capabilities']['purposes'][0],model_ids=[model['id']]+([self.models[1]['id']] if node=='i' else []),execution_policy=self.policy)
    def prepare(self,node='i'):
        request=self.request(node);preview=self.service.preview_creative_canvas_run(self.p,request);self.assertTrue(preview['ready'],preview)
        return self.write('propose_creative_canvas_run',dict(request=request,preview_sha256=preview['preview_sha256']))
    def test_typed_image_audio_dependency_and_original_approval_boundary(self):
        batch=self.service.preview_canvas_execution_batch(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,nodes=[{k:v for k,v in self.request(n).items() if k not in {'canvas_id','canvas_revision'}} for n in ['i','a','v']]))
        self.assertEqual([x['result']['ready'] for x in batch['items']],[True,True,False]);self.assertEqual(batch['items'][2]['result']['gaps'][0]['code'],'canvas_dependency_waiting')
        image=self.prepare();audio=self.prepare('a');result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id'],audio['step_id']]),'test-human')
        self.assertTrue(all(r['status']=='needs_approval' for r in result['runs']));self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        self.write('decide_artifact',dict(artifact_id=image['artifact_id'],reason='合成工程批准固定运行'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id']]),'test-human');self.rev=result['revision']
        self.assertEqual(result['runs'][0]['created_count'],1,result)
        again=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id']]),'test-human');self.assertEqual(again['runs'][0]['existing_count'],1);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
        self.write('decide_artifact',dict(artifact_id=audio['artifact_id'],reason='合成声音固定运行批准'))
        sound=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[audio['step_id']]),'test-human');self.rev=sound['revision'];self.assertEqual(sound['runs'][0]['created_count'],1,sound)
        sound_job=self.service.get_generation_job(self.p,sound['runs'][0]['tasks'][0]['job_id']);self.assertEqual((sound_job['modality'],sound_job['purpose']),('audio','sfx'))
        step=self.service.get_creative_canvas(self.p,self.canvas['id'])['execution_steps'][0];self.assertEqual(step['shot_id'],self.objects['shot']);self.assertEqual(step['run_artifact_id'],image['artifact_id'])
    def test_unknown_job_never_creates_a_fallback_or_resubmits(self):
        from vsc.assets.resource_service import ResourceError
        row=self.prepare();self.write('decide_artifact',dict(artifact_id=row['artifact_id'],reason='合成工程批准'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.rev=result['revision'];job=result['runs'][0]['tasks'][0]['job_id']
        self.write('update_generation_job',dict(job_id=job,status='submission_unknown',raw_response={'synthetic':'unknown submission'}))
        with self.assertRaises(ResourceError) as caught:self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.assertEqual(caught.exception.code,'canvas_fallback_not_terminal')
        again=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.assertEqual(again['runs'][0]['existing_count'],1);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1);self.assertEqual(self.service.get_generation_job(self.p,job)['status'],'submission_unknown')

    def test_ordered_fallback_rejects_unfinished_and_requires_new_approval(self):
        from vsc.assets.resource_service import ResourceError
        row=self.prepare()
        with self.assertRaises(ResourceError):self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.write('decide_artifact',dict(artifact_id=row['artifact_id'],reason='合成工程批准'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.rev=result['revision'];job=result['runs'][0]['tasks'][0]['job_id']
        with self.assertRaises(ResourceError):self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.write('update_generation_job',dict(job_id=job,status='failed',raw_response={'synthetic':'definite local failure before submission'}))
        preview=self.service.preview_canvas_fallback(self.p,row['step_id']);self.assertEqual(preview['model_ids'],[self.models[1]['id']]);self.assertEqual(preview['artifact']['document']['execution_policy']['authorization']['run_version_id'],row['artifact_id'])
        successor=self.write('propose_canvas_fallback',dict(step_id=row['step_id'],preview_sha256=preview['preview_sha256']));self.assertFalse(self.service.get_artifact_version(self.p,successor['artifact_id'])['approved']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)


@unittest.skipUnless(TEST_URL and HAS_DB, "requires configured isolated PostgreSQL")
class CanvasInputModeTests(ResourceStoreFixture, unittest.TestCase):
    def test_canvas_reference_modes_fix_original_input_and_purpose(self):
        objects=self.hierarchy()
        provider='canvas_modes_'+uuid.uuid4().hex
        self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
        model=self.service.register_model(dict(provider_id=provider,model_key='video',model_version='offline',modality='video',capabilities=dict(purposes=['image_to_video','reference_to_video','text_to_video'],reference_media=True,reference_video=True,reference_audio=True,first_frame=True)),actor='test-admin')
        image=self.media('image');video=self.media('video',modality='video');audio=self.media('audio',modality='audio')
        cases=[([], 'text','text_to_video'),([('image',image,'first_frame')], 'single','image_to_video'),([('image',image,'reference_image')], 'omni','reference_to_video'),([('image',image,'reference_image'),('video',video,'reference_video'),('audio',audio,'reference_audio')],'omni','reference_to_video')]
        for refs,mode,purpose in cases:
            with self.subTest(mode=mode,ports=[r[2] for r in refs]):
                nodes=[dict(id='out',type='video',text='Follow these fixed references.')]
                edges=[]
                for index,(kind,mid,port) in enumerate(refs):
                    key='ref'+str(index);nodes.append(dict(id=key,type=kind,media_id=mid));edges.append(dict(id='edge'+str(index),source=key,target='out',port=port))
                canvas=self.write('create_creative_canvas',dict(episode_id=objects['episode'],document=dict(nodes=nodes,edges=edges)))
                result=self.write('prepare_canvas_work_input',dict(canvas_id=canvas['id'],canvas_revision=1,node_id='out',shot_id=objects['shot'],model_id=model['id']))
                fixed=result['document'];self.assertEqual((fixed['mode'],fixed['purpose']),(mode,purpose))
                self.assertEqual([r['media_id'] for r in fixed['references']],[r[1] for r in refs])
                from vsc.adapters.persistence.postgres.workbench_generation import working_context
                with self.engine.connect() as conn:
                    context=working_context(self.store,conn,self.store._project(conn,self.p),result['draft_version_id'])
                self.assertEqual({r['media_id'] for r in context['media']},{r[1] for r in refs})
                self.assertFalse(context['gaps'])
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
