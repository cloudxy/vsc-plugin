"""Cross-project fixed media goes through the canvas command and original receipt."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import struct
import tempfile
import unittest
import uuid
import zlib

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class CanvasProjectReferenceTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        old=self.service.storage;self.addCleanup(setattr,self.service,'storage',old)
        self.service.storage=LocalStorage(self.directory.name)
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        self.bytes=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x30\x60\x90'))+chunk(b'IEND',b'')
        key='synthetic/source.png';path=self.service.storage.resolve(key);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.bytes)
        self.media_id=self.write('register_media',dict(name='固定素材',modality='image',sha256=hashlib.sha256(self.bytes).hexdigest(),
            size_bytes=len(self.bytes),mime_type='image/png',storage='local',object_key=key,rights='owned',
            source={'kind':'test-owned','content':'synthetic fixture'}))['id']
        self.write('record_media_check',dict(media_id=self.media_id,checker='fixture',criteria_version='1',outcome='pass'))
        self.asset=self.write('save_asset_card',dict(name='固定角色',asset_kind='character',base_revision=0,
            forms=[dict(form_key='master',name='默认',base_version_id=None,description='',media_id=self.media_id,voice_spec_id=None)]))
        self.target=self.service.create_project({'name':'目标合成项目'},actor='test-human')['id']
        self.canvas=self.service.create_creative_canvas(self.target,dict(title='画布',document={'nodes':[],'edges':[]}),
            expected_revision=0,idempotency_key='canvas',actor='test-human')
        self.revision=self.canvas['revision']

    def payload(self,source=None):
        return dict(canvas_id=self.canvas['id'],canvas_revision=1,source_project_id=self.p,x=100,y=120,
            source=source or dict(kind='asset_form',asset_id=self.asset['id'],form_version_id=self.asset['forms'][0]['version_id'],media_id=self.media_id))

    def command(self,payload=None,key='reference',expected=None):
        return self.service.add_canvas_project_media_node(self.target,payload or self.payload(),actor='test-human',
            expected_revision=self.revision if expected is None else expected,idempotency_key=key)

    def test_http_fixed_form_replay_refresh_and_source_rights(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        app=create_app({'projects_root':self.directory.name+'/projects','media_root':self.directory.name,'allowed_hosts':['testserver'],
            'allowed_origins':['http://testserver'],'human_identity':'test-human','access_token':'test-token','background_enabled':False},service=self.service)
        with TestClient(app) as client:
            session=client.post('/api/v1/session',headers={'Origin':'http://testserver'},json={'token':'test-token'}).json()
            headers={'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']};path='/api/v1/projects/'+self.target+'/creative-canvases/'+self.canvas['id']
            payload=self.payload();payload.pop('canvas_id');request={'payload':payload,'expected_revision':self.revision,'idempotency_key':'same-request'}
            saved=client.post(path+'/project-media-node',headers=headers,json=request);self.assertEqual(saved.status_code,200,saved.text)
            replay=client.post(path+'/project-media-node',headers=headers,json=request);self.assertEqual(replay.status_code,200,replay.text);self.assertEqual(saved.json(),replay.json())
            result=saved.json();read=client.get(path,params={'version':result['canvas_revision']});self.assertEqual(read.status_code,200,read.text)
            node=read.json()['document']['nodes'][0];self.assertEqual(node['id'],result['node_id']);self.assertEqual(node['media_id'],result['media_id'])
            content=client.get('/api/v1/projects/'+self.target+'/media/'+result['media_id']+'/content');self.assertEqual(content.status_code,200,content.text);self.assertEqual(content.content,self.bytes)
        self.assertEqual(self.service.list_asset_cards(self.target)['total'],0)
        with self.engine.connect() as conn:
            links=conn.execute(select(S.canvas_project_media_links).where(S.canvas_project_media_links.c.project_id==self.target)).mappings().all()
            self.assertEqual(len(links),1);self.assertEqual(links[0]['source_media_id'],self.media_id)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==self.target)),1)
            _,gaps=self.store._usable(conn,self.target,result['media_id'],'reference_image')
            self.assertEqual('technical_check_missing' not in gaps,result['byte_check']['checked'])
        self.write('decide_rights',dict(media_id=self.media_id,outcome='revoked',reason='撤销测试来源'))
        with self.engine.connect() as conn:
            _,gaps=self.store._usable(conn,self.target,result['media_id'],'reference_image');self.assertIn('copy_source_rights_restricted',gaps)

    def test_fixed_blocking_media(self):
        objects=self.hierarchy();candidate=self.write('propose_binding',dict(target_object_id=objects['shot'],media_id=self.media_id,role='first_frame',slot_key='station'))
        selection=self.write('save_working_selection',dict(shot_id=objects['shot'],output_kind='image',candidate_id=candidate['candidate_id'],base_version_id=None))
        flow=self.write('create_intelligent_workflow',dict(episode_id=objects['episode'],route='storyboard',script_text='固定剧本'))['id']
        current=self.service.get_intelligent_workflow(self.p,flow);state=current['state']
        state['units']=[dict(unit_key='station',kind='blocking',title='站位',description='',duration_ms=5000,
            segments=[dict(start_ms=0,end_ms=5000,text='等待')],skip_reason='',lineart_purpose='none',shot_id=objects['shot'],spatial_version_id=None)]
        state['media']=[dict(unit_key='station',purpose='blocking',media_id=self.media_id,decision_id=None,
            working_selection_version_id=selection['selection_version_id'],spatial_export_id=None)]
        change=dict(workflow_id=flow,base_version_id=current['version']['id'],state=state)
        saved=self.write('save_intelligent_workflow',dict(change,impact_sha256=self.service.preview_intelligent_change(self.p,change)['sha256']))
        source=dict(kind='blocking',workflow_id=flow,version_id=saved['version_id'],episode_id=objects['episode'],unit_key='station',media_id=self.media_id,spatial_export_id=None)
        result=self.command(self.payload(source));fixed=self.service.get_creative_canvas(self.target,self.canvas['id'],result['canvas_revision'])
        self.assertEqual(fixed['document']['nodes'][0]['media_id'],result['media_id']);self.assertEqual(self.service.list_asset_cards(self.target)['total'],0)
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            row=conn.execute(select(S.canvas_project_media_links).where(S.canvas_project_media_links.c.project_id==self.target)).mappings().one()
            self.assertEqual(row['source_workflow_version_id'],saved['version_id']);self.assertEqual(row['source_unit_key'],'station')
        origin=self.service.get_media(self.p,self.media_id)['sources'][0]['source_id']
        self.write('decide_rights',dict(media_id=self.media_id,outcome='licensed',source_id=origin,
            scope={'purposes':['first_frame']},reason='限定首帧测试'))
        station=self.service.list_asset_cards(self.p,asset_kind='blocking',include_blocking=True)['items'][0]
        self.assertEqual(station['preview']['media_id'],self.media_id)
        second=self.service.add_canvas_project_media_node(self.target,dict(self.payload(source),canvas_revision=result['canvas_revision']),
            actor='test-human',expected_revision=result['revision'],idempotency_key='station-first-frame')
        with self.engine.connect() as conn:
            _,allowed=self.store._usable(conn,self.target,second['media_id'],'first_frame')
            _,other=self.store._usable(conn,self.target,second['media_id'],'reference_image')
        self.assertNotIn('rights_scope_mismatch',allowed);self.assertIn('rights_scope_mismatch',other)

    def test_import_does_not_assume_a_production_purpose(self):
        source=self.service.get_media(self.p,self.media_id)['sources'][0]['source_id']
        for purpose in ('first_frame','image_edit'):
            with self.subTest(purpose=purpose):
                self.write('decide_rights',dict(media_id=self.media_id,outcome='licensed',source_id=source,
                    scope={'purposes':[purpose]},reason='限定测试用途'))
                self.target=self.service.create_project({'name':'目标 '+purpose},actor='test-human')['id']
                self.canvas=self.service.create_creative_canvas(self.target,dict(title='画布',document={'nodes':[],'edges':[]}),
                    expected_revision=0,idempotency_key='canvas',actor='test-human');self.revision=self.canvas['revision']
                result=self.command(key='restricted-'+purpose)
                with self.engine.connect() as conn:
                    _,allowed=self.store._usable(conn,self.target,result['media_id'],purpose)
                    _,other=self.store._usable(conn,self.target,result['media_id'],'reference_image')
                self.assertNotIn('rights_scope_mismatch',allowed);self.assertNotIn('copy_source_rights_scope_mismatch',allowed)
                self.assertIn('rights_scope_mismatch',other)

    def test_successful_3d_blocking_export_is_fixed_and_copied(self):
        from vsc.assets.spatial_scene import default_scene
        objects=self.hierarchy();document=default_scene();document.update(width=320,height=180)
        spatial=self.write('create_spatial_scene',dict(mode='blocking',scene_id=objects['scene'],document=document,title='三维站位'))
        export=self.write('create_spatial_export',dict(spatial_scene_id=spatial['id'],scene_revision=1,camera_id='camera-b',format='png',time=.25))
        complete=self.service.execute_spatial_export(self.p,export['id']);self.rev=self.service.get_project(self.p)['revision']
        self.assertEqual(complete['status'],'succeeded');image=complete['media_id']
        fixed=self.service.get_spatial_scene(self.p,spatial['id'])['version_id']
        flow=self.write('create_intelligent_workflow',dict(episode_id=objects['episode'],route='storyboard',script_text='固定剧本'))['id']
        current=self.service.get_intelligent_workflow(self.p,flow);state=current['state'];state['blocking_mode']='3d'
        state['units']=[dict(unit_key='station3d',kind='blocking',title='三维站位',description='',duration_ms=5000,
            segments=[dict(start_ms=0,end_ms=5000,text='等待')],skip_reason='',lineart_purpose='none',shot_id=objects['shot'],spatial_version_id=fixed)]
        state['media']=[dict(unit_key='station3d',purpose='blocking',media_id=image,decision_id=None,spatial_export_id=export['id'])]
        change=dict(workflow_id=flow,base_version_id=current['version']['id'],state=state)
        saved=self.write('save_intelligent_workflow',dict(change,impact_sha256=self.service.preview_intelligent_change(self.p,change)['sha256']))
        source=dict(kind='blocking',workflow_id=flow,version_id=saved['version_id'],episode_id=objects['episode'],unit_key='station3d',media_id=image,spatial_export_id=export['id'])
        result=self.command(self.payload(source),key='station-3d');target=self.service.get_creative_canvas(self.target,self.canvas['id'],result['canvas_revision'])
        self.assertEqual(target['document']['nodes'][0]['media_id'],result['media_id']);self.assertEqual(self.service.list_asset_cards(self.target)['total'],0)

    def test_missing_local_storage_retains_real_detection_gap(self):
        self.service.storage=None
        result=self.command(key='without-storage');self.assertEqual(result['byte_check'],{'checked':False,'status':'unavailable','reason':'local_storage_unavailable'})
        with self.engine.connect() as conn:
            _,gaps=self.store._usable(conn,self.target,result['media_id'],'reference_image')
        self.assertIn('technical_check_missing',gaps)

    def test_missing_or_changed_local_bytes_roll_back_without_a_canvas_node(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        path=self.service.storage.resolve('synthetic/source.png')
        for name,change in [('missing',lambda:path.unlink()),('changed',lambda:path.write_bytes(b'changed'))]:
            with self.subTest(case=name):
                path.write_bytes(self.bytes);change()
                with self.assertRaises(ResourceError) as failure:self.command(key='invalid-'+name)
                self.assertEqual(failure.exception.code,'canvas_project_source_bytes_invalid')
                with self.engine.connect() as conn:
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==self.target)),0)
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.canvas_project_media_links).where(S.canvas_project_media_links.c.project_id==self.target)),0)
                self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)

    def test_sha_matched_but_undecodable_image_is_rejected(self):
        broken=b'\x89PNG\r\n\x1a\n'+b'not-a-complete-image';path=self.service.storage.resolve('synthetic/broken.png');path.write_bytes(broken)
        media=self.write('register_media',dict(name='损坏图片',modality='image',sha256=hashlib.sha256(broken).hexdigest(),
            size_bytes=len(broken),mime_type='image/png',storage='local',object_key='synthetic/broken.png',rights='owned',
            source={'kind':'test-owned','content':'synthetic broken image'}))['id']
        asset=self.write('save_asset_card',dict(name='损坏素材',asset_kind='character',base_revision=0,
            forms=[dict(form_key='master',name='默认',base_version_id=None,description='',media_id=media,voice_spec_id=None)]))
        payload=self.payload(dict(kind='asset_form',asset_id=asset['id'],form_version_id=asset['forms'][0]['version_id'],media_id=media))
        with self.assertRaises(ResourceError) as failure:self.command(payload,key='broken-image')
        self.assertEqual(failure.exception.code,'canvas_project_source_bytes_invalid')
        self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)

    def test_bad_local_copy_falls_back_to_valid_local_copy(self):
        from sqlalchemy import insert,select
        from unittest.mock import patch
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.begin() as conn:
            blob=conn.execute(select(S.media_items.c.blob_id).where(S.media_items.c.project_id==self.p,S.media_items.c.id==self.media_id)).scalar_one()
            conn.execute(insert(S.blob_locations).values(id=str(uuid.uuid4()),blob_id=blob,storage='local',object_key='synthetic/other.png'))
        locations=self.service.get_media(self.p,self.media_id)['locations']
        local=[row for row in locations if row['storage']=='local' and row['available']];self.assertEqual(len(local),2)
        first=self.service.storage.resolve(local[0]['object_key']);second=self.service.storage.resolve(local[1]['object_key'])
        first.write_bytes(b'bad');second.write_bytes(self.bytes)
        with patch.object(self.service.storage,'verify',wraps=self.service.storage.verify) as verify:
            result=self.command(key='local-fallback')
        checked_keys=[call.args[0] for call in verify.call_args_list]
        self.assertIn(local[0]['object_key'],checked_keys);self.assertIn(local[1]['object_key'],checked_keys)
        self.assertEqual(result['byte_check']['status'],'verified')
        self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['document']['nodes'][0]['media_id'],result['media_id'])

    def test_changed_form_version_is_not_silently_substituted(self):
        old=self.asset['forms'][0]['version_id']
        self.write('save_asset_card',dict(asset_id=self.asset['id'],name='新名称',asset_kind='character',base_revision=self.asset['asset_revision'],
            forms=[dict(form_key='master',name='默认',base_version_id=old,description='新版本',media_id=self.media_id,voice_spec_id=None)]))
        with self.assertRaises(ResourceError) as failure:self.command(key='old-form')
        self.assertEqual(failure.exception.code,'canvas_project_source_changed')
        self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)

    def test_rejected_requests_rollback(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        wrong=self.payload();wrong['source']=dict(wrong['source'],media_id=str(uuid.uuid4()))
        with self.assertRaises(ResourceError):self.command(wrong)
        with self.assertRaises(ResourceError):self.command(dict(self.payload(),canvas_revision=2),key='wrong-version')
        self.write('decide_rights',dict(media_id=self.media_id,outcome='revoked',reason='撤销测试来源'))
        with self.assertRaises(ResourceError):self.command(key='revoked')
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==self.target)),0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.canvas_project_media_links).where(S.canvas_project_media_links.c.project_id==self.target)),0)
        self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)

    def test_target_editor_without_source_read_is_denied(self):
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        owner=self.service.ensure_local_access('test-human');outsider=self.service.ensure_local_access('other-human')
        token=set_principal(Principal(**owner))
        try:
            preview=self.service.access_migration_preview(self.p,owner['workspace_id'])
            self.service.access_command('assign-project',dict(project_id=self.p,workspace_id=owner['workspace_id'],preview_sha256=preview['sha256']),
                expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
        finally:reset_principal(token)
        token=set_principal(Principal(**outsider))
        try:
            with self.assertRaises(ResourceError):
                self.service.add_canvas_project_media_node(self.target,self.payload(),actor='other-human',expected_revision=self.revision,idempotency_key='denied-source')
            self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)
        finally:reset_principal(token)

    def test_recycled_source_or_failed_inspection_is_not_sent(self):
        self.write('management_command',dict(operation='trash',target_type='object',target_id=self.asset['id'],reason='回收测试素材'))
        with self.assertRaises(ResourceError):self.command(key='recycled')
        self.write('management_command',dict(operation='restore',target_type='object',target_id=self.asset['id'],reason='恢复测试素材'))
        self.write('record_media_check',dict(media_id=self.media_id,checker='fixture',criteria_version='1',outcome='fail'))
        with self.assertRaises(ResourceError) as failure:self.command(key='failed-check')
        self.assertIn('technical_check_failed',str(failure.exception))
        self.assertEqual(self.service.get_creative_canvas(self.target,self.canvas['id'])['canvas_revision'],1)
    def test_same_request_real_concurrency_returns_one_receipt(self):
        payload=self.payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.command,payload,'concurrent',self.revision) for _ in range(2)]
            results=[future.result(timeout=30) for future in futures]
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.service.get_creative_canvas(self.target,self.canvas['id'])['document']['nodes']),1)
