"""Real PG and HTTP management paths, original identities and protected retirement."""
import os,unittest,uuid,tempfile
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS,'requires isolated PostgreSQL')
class ProjectManagementTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from pathlib import Path
        from vsc.adapters.storage.local.store import LocalStorage
        temp=tempfile.TemporaryDirectory(prefix='vsc-management-test-');self.addCleanup(temp.cleanup)
        self.service.storage=LocalStorage(Path(temp.name)/'storage')

    def edit_document(self,media=None):
        return {'format':'vsc.edit-workspace/v1','width':128,'height':128,'fps':24,'clips':[{'id':'clip','media_id':media,'in_frame':0,'out_frame':24}] if media else [],'audio':[],'captions':[]}

    def command(self,operation,**payload):return self.write('management_command',dict(operation=operation,**payload))

    def test_rename_folder_order_move_filter_scope_and_receipt(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();media=self.media('目录媒资')
        key=uuid.uuid4().hex;payload={'operation':'rename','title':'已改名'}
        result=self.write('management_command',payload,idempotency_key=key)
        self.assertEqual(self.service.get_project(self.p)['name'],'已改名')
        self.assertEqual(result,self.service.management_command(self.p,payload,expected_revision=0,idempotency_key=key,actor='test-human'))
        a=self.command('folder_create',title='分集',parent_id=None)['folder_id'];b=self.command('folder_create',title='素材',parent_id=None)['folder_id']
        self.command('folder_order',parent_id=None,folder_ids=[b,a]);self.command('move',target_type='object',target_id=o['episode'],folder_id=a);self.command('move',target_type='media',target_id=media,folder_id=b)
        rows=self.service.management_snapshot(self.p,folder_id=a)['items'];self.assertEqual([x['id'] for x in rows],[o['episode']])
        self.assertEqual([x['id'] for x in self.service.management_snapshot(self.p,folder_id=b)['items']],[media])
        child=self.command('folder_create',title='子目录',parent_id=a)['folder_id']
        with self.assertRaises(ResourceError):self.command('folder_move',folder_id=a,parent_id=child)
        with self.assertRaises(ResourceError):self.command('folder_remove',folder_id=a)
        other=self.service.create_project({'name':'另一项目'},actor='test-human')['id']
        with self.assertRaises(ResourceError):self.service.management_command(other,{'operation':'move','target_type':'object','target_id':o['episode'],'folder_id':a},expected_revision=0,idempotency_key=uuid.uuid4().hex,actor='test-human')
        self.assertEqual(self.service.get_project_tree(self.p)['nodes'][1]['id'],o['episode'])

    def test_recycle_ancestors_restore_fixed_identity_and_project_list(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();artifact=self.artifact(objects=[o['shot']]);media=self.media()
        self.command('retention',days=7);f=self.command('folder_create',title='第一部分',parent_id=None)['folder_id'];self.command('move',target_type='object',target_id=o['episode'],folder_id=f)
        recycle_key=uuid.uuid4().hex
        self.write('management_command',{'operation':'trash','target_type':'object','target_id':o['shot'],'reason':'单镜回收'},idempotency_key=recycle_key)
        self.command('trash',target_type='object',target_id=o['episode'],reason='整集暂不使用')
        self.assertNotIn(o['episode'],[r['id'] for r in self.service.get_project_tree(self.p)['nodes']])
        with self.assertRaises(ResourceError):self.command('restore',target_type='object',target_id=o['shot'],reason='先恢复子项')
        self.assertEqual(self.service.get_artifact_version(self.p,artifact)['id'],artifact)
        with self.assertRaises(ResourceError):self.service.compile_shot_context(self.p,o['shot'])
        with self.assertRaises(ResourceError):self.write('create_artifact',{'artifact_type':'memo','artifact_key':'no','document':'不能写','object_ids':[o['shot']]})
        self.command('restore',target_type='object',target_id=o['episode'],reason='恢复父级');self.command('restore',target_type='object',target_id=o['shot'],reason='恢复单镜')
        row=next(r for r in self.service.management_snapshot(self.p)['items'] if r['id']==o['episode']);self.assertEqual(row['folder_id'],f)
        receipt=self.service.get_operation_receipt(self.p,recycle_key,actor='test-human')['response']
        self.assertEqual(receipt['reason'],'单镜回收');self.assertEqual(receipt['previous_state'],'active');self.assertEqual(receipt['state'],'trashed')
        self.command('trash',target_type='project',target_id=self.p,reason='暂时回收')
        self.assertNotIn(self.p,[r['id'] for r in self.service.list_projects()]);self.assertEqual(self.service.management_recycled_projects()['items'][0]['id'],self.p)
        from pathlib import Path
        import json
        from vsc.project.resource_catalog import ResourceCatalog
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'pointer';folder.mkdir();(folder/'.vsc-postgres.json').write_text(json.dumps({'storage_policy':'postgres-series-v1','project_id':self.p}))
            self.assertNotIn(self.p,[r['id'] for r in ResourceCatalog(root,self.service).list_projects()['items']])
        self.assertEqual(self.service.get_media(self.p,media)['id'],media)
        with self.assertRaises(ResourceError):self.write('create_object',{'kind':'work','display_code':'NO','ordinal':1})
        self.command('restore',target_type='project',target_id=self.p,reason='恢复项目');self.assertIn(self.p,[r['id'] for r in self.service.list_projects()])
        self.assertEqual(self.service.management_snapshot(self.p)['retention_days'],7)

    def test_permanent_retirement_reference_and_inflight_protection(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();a=self.artifact(objects=[o['shot']])
        self.command('trash',target_type='object',target_id=o['shot'],reason='回收')
        title=next(r['title'] for r in self.service.management_snapshot(self.p,kind='trashed')['items'] if r['id']==o['shot'])
        r=self.command('purge',target_type='object',target_id=o['shot'],reason='永久停用',confirm_name=title)
        self.assertEqual(r['status'],'protected');self.assertTrue(any(x['code']=='referenced' for x in r['reasons']))
        empty=self.write('create_object',{'kind':'shot','parent_id':o['sequence'],'display_code':'EMPTY','title':'空镜','ordinal':1})['id']
        self.command('trash',target_type='object',target_id=empty,reason='空镜回收')
        r=self.command('purge',target_type='object',target_id=empty,reason='空镜永久停用',confirm_name='空镜');self.assertEqual(r['state'],'purged');self.assertEqual(r['released_bytes'],0)
        with self.assertRaises(ResourceError):self.command('restore',target_type='object',target_id=empty,reason='不能恢复永久停用')
        self.command('restore',target_type='object',target_id=o['shot'],reason='恢复已引用镜头')
        video=self.media('导出用料',modality='video')
        saved=self.write('save_edit_workspace',{'episode_id':o['episode'],'edit_revision':0,'document':self.edit_document(video)})
        job=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']})
        protected=self.command('trash',target_type='object',target_id=o['episode'],reason='导出中回收')
        self.assertEqual(protected['status'],'protected');self.assertTrue(any(r['code']=='in_flight' for r in protected['reasons']))

    def test_typed_old_draft_guard_and_http_recycle_entry(self):
        from vsc.assets.resource_service import ResourceError
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        o=self.hierarchy();saved=self.write('save_edit_workspace',{'episode_id':o['episode'],'edit_revision':0,'document':self.edit_document()})
        self.command('trash',target_type='object',target_id=o['episode'],reason='整集暂停')
        with self.assertRaises(ResourceError) as caught:self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']})
        self.assertEqual(caught.exception.code,'object_recycled')
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test-token','human_identity':'browser-test'},catalog=ResourceCatalog(root,self.service),service=self.service)
            with TestClient(app) as client:
                login=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'});self.assertEqual(login.status_code,200,login.text)
                headers={'X-CSRF-Token':login.json()['csrf_token'],'Origin':'http://testserver'}
                response=client.get('/api/v1/projects/'+self.p+'/management');self.assertEqual(response.status_code,200,response.text)
                key=uuid.uuid4().hex;body={'payload':{'operation':'rename','title':'HTTP管理'},'expected_revision':self.rev,'idempotency_key':key}
                result=client.post('/api/v1/projects/'+self.p+'/management',json=body,headers=headers);self.assertEqual(result.status_code,200,result.text)
                replay=client.post('/api/v1/projects/'+self.p+'/management',json=body,headers=headers);self.assertEqual(result.json(),replay.json())
                archived=client.post('/api/v1/projects/'+self.p+'/management',json={'payload':{'operation':'trash','target_type':'project','target_id':self.p,'reason':'HTTP回收'},'expected_revision':result.json()['revision'],'idempotency_key':uuid.uuid4().hex},headers=headers)
                self.assertEqual(archived.status_code,200,archived.text)
                self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,409)
                self.assertEqual(client.get('/api/v1/projects/'+self.p+'/management').status_code,200)
                self.assertEqual(client.get('/api/v1/projects/'+self.p+'/artifacts').status_code,200)
                self.assertEqual(client.get('/api/v1/project-management/recycled',headers=headers).status_code,200)

    def test_saved_canvas_and_spatial_ids_do_not_bypass_recycle_scope(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.spatial_scene import default_scene
        o=self.hierarchy()
        canvas=self.write('create_creative_canvas',{'episode_id':o['episode'],'title':'本集画布','document':{'nodes':[],'edges':[]}})
        spatial=self.write('create_spatial_scene',{'mode':'blocking','scene_id':o['scene'],'title':'本场站位','document':default_scene()})
        self.command('trash',target_type='object',target_id=o['episode'],reason='本集回收')
        calls=[('save_creative_canvas',{'canvas_id':canvas['id'],'canvas_revision':1,'title':'不得写入','document':{'nodes':[],'edges':[]}}),('save_spatial_scene',{'spatial_scene_id':spatial['id'],'scene_revision':1,'title':'不得写入','document':default_scene()})]
        for method,payload in calls:
            with self.subTest(method=method),self.assertRaises(ResourceError) as caught:self.write(method,payload)
            self.assertEqual(caught.exception.code,'object_recycled')
        self.command('restore',target_type='object',target_id=o['episode'],reason='恢复')
        saved=self.write('save_creative_canvas',calls[0][1]);self.assertEqual(saved['canvas_revision'],2)

    def test_failed_spatial_retry_cannot_restart_after_recycle(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.spatial_scene import default_scene
        o=self.hierarchy();scene=self.write('create_spatial_scene',{'mode':'blocking','scene_id':o['scene'],'title':'失败重试范围','document':default_scene()})
        job=self.write('create_spatial_export',{'spatial_scene_id':scene['id'],'scene_revision':1,'camera_id':'camera-a','format':'png','time':0})
        claimed=self.store.claim_spatial_export(self.p,job['id'])
        self.store.fail_spatial_export(self.p,job['id'],claimed['claim_token'],'synthetic failure before rendering')
        self.command('trash',target_type='object',target_id=o['episode'],reason='失败任务后回收')
        with self.assertRaises(ResourceError) as caught:self.store.claim_spatial_export(self.p,job['id'])
        self.assertEqual(caught.exception.code,'object_recycled')
        self.assertEqual(self.store.get_spatial_export(self.p,job['id'])['status'],'failed')
