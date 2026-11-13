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

    def test_edit_project_preserves_existing_authorities_and_replays_atomic_episode_growth(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.access_control import action_capability
        o=self.hierarchy();before=self.service.get_project(self.p);key=uuid.uuid4().hex
        payload={'operation':'edit','title':'完整编辑','character_style':'3d','episode_count':3}
        result=self.write('management_command',payload,idempotency_key=key)
        self.assertEqual(result,self.service.management_command(self.p,payload,expected_revision=0,idempotency_key=key,actor='test-human'))
        after=self.service.get_project(self.p);self.assertEqual(after['id'],before['id'])
        self.assertEqual(after['profile_snapshot'],dict(before['profile_snapshot'],character_style='3d'))
        self.assertEqual(after['name'],'完整编辑');self.assertEqual(action_capability('management_edit'),'manage')
        episodes=self.service.get_production_episodes(self.p)
        self.assertEqual(episodes['total'],3);self.assertEqual(episodes['items'][0]['id'],o['episode'])
        self.assertEqual([r['title'] for r in episodes['items'][1:]],['第2集','第3集'])
        self.assertEqual(self.service.management_snapshot(self.p)['episode_count'],3)
        self.assertEqual(len(result['created_episode_ids']),2)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.shots.c.id).where(S.shots.c.project_id==self.p)).scalar_one(),o['shot'])
        for change in [{'episode_count':2},{'episode_count':0},{'episode_count':501},{'episode_count':True},{'episode_count':1.5},{'title':'x'*51},{'title':' '},{'character_style':'unknown'}]:
            with self.subTest(change=change),self.assertRaises(ResourceError):self.write('management_command',dict(payload,**change))
        self.assertEqual(self.service.get_project(self.p),after)
        self.assertEqual(self.service.get_production_episodes(self.p)['total'],3)

    def test_edit_multiple_works_and_stale_revision_do_not_partially_rename(self):
        from vsc.assets.resource_service import ResourceError,Conflict
        self.hierarchy();self.write('create_object',{'kind':'work','display_code':'WORK2','title':'第二部','ordinal':1})
        before=self.service.get_project(self.p)
        payload={'operation':'edit','title':'不得部分保存','character_style':'live','episode_count':2}
        with self.assertRaises(ResourceError) as error:self.write('management_command',payload)
        self.assertEqual(error.exception.code,'work_required');self.assertEqual(self.service.get_project(self.p),before)
        with self.assertRaises(Conflict):self.service.management_command(self.p,dict(payload,episode_count=1),actor='test-human',expected_revision=self.rev-1,idempotency_key=uuid.uuid4().hex)
        self.assertEqual(self.service.get_project(self.p),before)

    def test_edit_preserves_fixed_single_episode_profile_limit(self):
        from vsc.assets.resource_service import ResourceError
        project=self.service.create_project({'name':'单集合同','profile':'vsc.light-short'},actor='test-human')
        payload={'operation':'edit','title':'不可绕过Profile','character_style':'3d','episode_count':2}
        with self.assertRaises(ResourceError) as error:
            self.service.management_command(project['id'],payload,actor='test-human',expected_revision=0,idempotency_key=uuid.uuid4().hex)
        self.assertEqual(error.exception.code,'episode_limit')
        self.assertEqual(self.service.get_project(project['id']),project)
        self.assertEqual(self.service.get_production_episodes(project['id'])['total'],0)

    def test_concurrent_project_edits_share_original_project_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from vsc.assets.resource_service import Conflict
        self.hierarchy();revision=self.rev;start=Barrier(2)
        def edit(number):
            start.wait()
            try:return self.service.management_command(self.p,{'operation':'edit','title':'并发编辑%d'%number,'character_style':'2d','episode_count':3},actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(edit,[1,2]))
        self.assertEqual(results.count('conflict'),1);self.assertEqual(self.service.get_production_episodes(self.p)['total'],3)
        self.assertEqual(self.service.get_project(self.p)['revision'],revision+1)

    def test_http_edit_readback_keeps_project_identity_and_rejects_reduction(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        self.hierarchy()
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test-token','human_identity':'test-human','background_enabled':False},catalog=ResourceCatalog(root,self.service),service=self.service)
            with TestClient(app) as client:
                login=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'})
                headers={'X-CSRF-Token':login.json()['csrf_token'],'Origin':'http://testserver'}
                path='/api/v1/projects/'+self.p+'/management'
                body={'payload':{'operation':'edit','title':'HTTP完整编辑','character_style':'live','episode_count':2},'expected_revision':self.rev,'idempotency_key':uuid.uuid4().hex}
                result=client.post(path,json=body,headers=headers);self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json(),client.post(path,json=body,headers=headers).json())
                snapshot=client.get(path).json();self.assertEqual(snapshot['project']['name'],'HTTP完整编辑');self.assertEqual(snapshot['episode_count'],2)
                card=next(r for r in client.get('/api/v1/projects').json()['items'] if r['id']==self.p)
                self.assertEqual(card['counts']['episodes'],2);self.assertEqual(card['project_type'],'真人')
                body['expected_revision']=result.json()['revision'];body['idempotency_key']=uuid.uuid4().hex;body['payload']['episode_count']=1
                rejected=client.post(path,json=body,headers=headers);self.assertEqual(rejected.status_code,422,rejected.text)
                self.assertEqual(client.get(path).json()['revision'],result.json()['revision'])

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
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test-token','human_identity':'test-human'},catalog=ResourceCatalog(root,self.service),service=self.service)
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

    def test_canvas_recycle_preserves_versions_media_replays_and_filters_entries(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres.discovery import discover
        from vsc.adapters.persistence.postgres.project_presentation import project_cards
        from unittest.mock import patch
        o=self.hierarchy();media=self.media('画布原图')
        document={'nodes':[{'id':'image','type':'image','media_id':media}],'edges':[]}
        first=self.write('create_creative_canvas',dict(episode_id=o['episode'],title='仍可创作',document=document))
        canvas=self.write('create_creative_canvas',dict(episode_id=o['episode'],title='回收画布',document=document))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='固定模板'))
        self.assertEqual(self.service.get_episode_entry(self.p,o['episode'],'test-human')['canvas']['id'],canvas['id'])
        before=self.service.creative_canvas_history(self.p,canvas['id'])['items'];key=uuid.uuid4().hex
        payload=dict(operation='trash',target_type='canvas',target_id=canvas['id'],reason='稍后恢复')
        result=self.write('management_command',payload,idempotency_key=key)
        self.assertEqual(result,self.service.management_command(self.p,payload,actor='test-human',expected_revision=0,idempotency_key=key))
        self.assertEqual(self.service.get_operation_receipt(self.p,key,actor='test-human')['response'],result)
        self.assertEqual([r['id'] for r in self.service.list_creative_canvases(self.p)['items']],[first['id']])
        self.assertEqual(self.service.get_episode_entry(self.p,o['episode'],'test-human')['canvas']['id'],first['id'])
        self.assertEqual(project_cards(self.store,[self.service.get_project(self.p)])[0]['counts']['canvases'],1)
        with patch.object(self.store,'access_snapshot',return_value={'projects':[self.service.get_project(self.p)],'identity':{'actor':'test-human'}}):
            found=discover(self.store)
        self.assertEqual([r['target_id'] for r in found['recent'] if r['kind']=='canvas'],[first['id']])
        self.assertNotIn(template['id'],[r['id'] for r in found['templates']])
        with self.assertRaises(ResourceError):self.service.get_creative_canvas(self.p,canvas['id'])
        fixed=self.service.get_creative_canvas(self.p,canvas['id'],version=1)
        self.assertEqual(fixed['document']['nodes'][0]['media_id'],media)
        self.assertEqual(self.service.creative_canvas_history(self.p,canvas['id'])['items'],before)
        self.assertEqual(self.service.get_media(self.p,media)['id'],media)
        for method,body in [('save_creative_canvas',dict(canvas_id=canvas['id'],canvas_revision=1,document=document)),
                            ('copy_creative_canvas',dict(canvas_id=canvas['id'],title='不能复制')),
                            ('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=1,message='不能运行',skill_id='vsc-script'))]:
            with self.subTest(method=method),self.assertRaises(ResourceError):self.write(method,body)
        for operation in ('purge','move'):
            body=dict(target_type='canvas',target_id=canvas['id'])
            body.update(dict(reason='不支持',confirm_name='回收画布') if operation=='purge' else dict(folder_id=None))
            with self.subTest(operation=operation),self.assertRaises(ResourceError) as caught:self.command(operation,**body)
            self.assertEqual(caught.exception.code,'canvas_lifecycle_operation')
        row=next(r for r in self.service.management_recycle_items(kind='canvas')['items'] if r['target_id']==canvas['id'])
        self.assertEqual(row['target_type'],'canvas');self.assertTrue(row['can_restore'])
        self.assertTrue(any(r['id']==canvas['id'] and r['type']=='canvas' for r in self.service.management_snapshot(self.p,kind='trashed')['items']))
        self.command('restore',target_type='canvas',target_id=canvas['id'],reason='恢复原画布')
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['version_id'],canvas['version_id'])
        self.assertEqual(self.service.get_episode_entry(self.p,o['episode'],'test-human')['canvas']['id'],canvas['id'])
        self.assertEqual(self.service.creative_canvas_history(self.p,canvas['id'])['items'],before)
        self.assertFalse(any(r['target_id']==canvas['id'] for r in self.service.management_recycle_items(kind='canvas')['items']))

    def test_canvas_restore_requires_project_and_every_ancestor(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();canvas=self.write('create_creative_canvas',dict(episode_id=o['episode'],document={'nodes':[],'edges':[]}))
        self.command('trash',target_type='canvas',target_id=canvas['id'],reason='回收')
        for typ,identifier in [('object',o['episode']),('object',o['work']),('project',self.p)]:
            self.command('trash',target_type=typ,target_id=identifier,reason='父级回收')
            row=next(r for r in self.service.management_recycle_items(kind='canvas')['items'] if r['target_id']==canvas['id'])
            self.assertFalse(row['can_restore'])
            self.assertTrue(row['blocked_by_project'] if typ=='project' else row['blocked_by_ancestor'])
            with self.assertRaises(ResourceError) as caught:self.command('restore',target_type='canvas',target_id=canvas['id'],reason='不能绕过父级')
            self.assertEqual(caught.exception.code,'restore_parent_first')
            self.command('restore',target_type=typ,target_id=identifier,reason='恢复父级')
        self.command('restore',target_type='canvas',target_id=canvas['id'],reason='最后恢复画布')
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['id'],canvas['id'])

    def test_canvas_inflight_agent_protection_and_two_transaction_revision_conflict(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from vsc.assets.resource_service import Conflict
        canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        other=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        turn=self.write('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=1,message='固定计划',skill_id='vsc-script'))
        protected=self.command('trash',target_type='canvas',target_id=canvas['id'],reason='运行中')
        self.assertEqual(protected['status'],'protected');self.assertEqual(protected['state'],'active')
        self.assertTrue(any(r['table']=='canvas_agent_turns' and r['id']==turn['id'] for r in protected['reasons']))
        # Another canvas is not owned by that in-flight turn.
        self.command('trash',target_type='canvas',target_id=other['id'],reason='独立画布')
        self.write('decide_canvas_agent_turn',dict(turn_id=turn['id'],outcome='stop',reason='停止合成规划'))
        revision=self.rev;start=Barrier(2)
        def change(number):
            start.wait()
            try:
                if number==1:return self.service.management_command(self.p,dict(operation='trash',target_type='canvas',target_id=canvas['id'],reason='并发回收'),actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
                return self.service.save_creative_canvas(self.p,dict(canvas_id=canvas['id'],canvas_revision=1,title='并发保存',document={'nodes':[],'edges':[]}),actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,[1,2]))
        self.assertEqual(results.count('conflict'),1);self.assertEqual(self.service.get_project(self.p)['revision'],revision+1)

    def test_canvas_lifecycle_typed_constraints_and_viewer_permissions(self):
        from sqlalchemy import insert,select
        from sqlalchemy.exc import IntegrityError
        from datetime import datetime,timezone
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from vsc.assets.resource_service import ResourceError
        canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        other=self.service.create_project({'name':'另一个隔离项目'},actor='test-human')['id']
        values=dict(project_id=self.p,id=str(uuid.uuid4()),canvas_id=canvas['id'],state='trashed',reason='test',actor='test-human',changed_at=datetime.now(timezone.utc))
        for change in ({'project_id':other},{'state':'purged'}):
            with self.subTest(change=change),self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(insert(S.management_canvas_states).values(dict(values,**change)))
        self.command('trash',target_type='canvas',target_id=canvas['id'],reason='测试回收')
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(insert(S.management_canvas_states).values(values))
        identity,workspace=[str(uuid.uuid4()) for _ in range(2)];actor='viewer:'+identity
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_identities).values(id=identity,subject_key='remote:'+identity,actor=actor,display_name='viewer',preferences={},active=True))
            conn.execute(insert(S.access_workspaces).values(id=workspace,name='隔离工作室',kind='studio',created_by=identity))
            conn.execute(S.access_projects.update().where(S.access_projects.c.project_id==self.p).values(workspace_id=workspace,assigned_by=identity))
            conn.execute(insert(S.access_project_members).values(project_id=self.p,identity_id=identity,role='viewer',active=True))
        token=set_principal(Principal(identity_id=identity,actor=actor))
        try:
            row=next(r for r in self.service.management_recycle_items(kind='canvas')['items'] if r['target_id']==canvas['id'])
            self.assertFalse(row['can_restore'])
            with self.assertRaises(ResourceError) as caught:self.write('management_command',dict(operation='restore',target_type='canvas',target_id=canvas['id'],reason='无管理权'),actor=actor)
            self.assertEqual(caught.exception.code,'access_denied')
        finally:reset_principal(token)
        with self.engine.connect() as conn:self.assertEqual(conn.execute(select(S.management_canvas_states.c.state).where(S.management_canvas_states.c.project_id==self.p)).scalar_one(),'trashed')

    def test_canvas_migration_roundtrip_and_refuses_loss_of_lifecycle_facts(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from support.paths import ROOT
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.persistence.postgres import schema as S
        with isolated_postgres(os.environ['VSC_TEST_DATABASE_URL']) as engine:
            service=ResourceService(PostgresResourceStore(engine=engine));p=service.create_project({'name':'迁移回退夹具'},actor='test-human')['id']
            canvas=service.create_creative_canvas(p,dict(document={'nodes':[],'edges':[]}),actor='test-human',expected_revision=0,idempotency_key='migration-canvas')
            cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:cfg.attributes['connection']=conn;command.downgrade(cfg,'0051_project_cover_versions')
            with engine.connect() as conn:
                self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),'0051_project_cover_versions')
                self.assertIsNone(conn.execute(text("SELECT to_regclass('management_canvas_states')")).scalar_one())
                self.assertEqual(conn.execute(text('SELECT count(*) FROM creative_canvas_versions')).scalar_one(),1)
            with engine.begin() as conn:cfg.attributes['connection']=conn;command.upgrade(cfg,'head')
            with engine.connect() as conn:self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
            service.management_command(p,dict(operation='trash',target_type='canvas',target_id=canvas['id'],reason='保全新事实'),actor='test-human',expected_revision=1,idempotency_key='migration-trash')
            with self.assertRaises(DBAPIError),engine.begin() as conn:cfg.attributes['connection']=conn;command.downgrade(cfg,'0051_project_cover_versions')
            self.assertEqual(service.management_recycle_items(kind='canvas')['items'][0]['target_id'],canvas['id'])
            result=service.management_command(p,dict(operation='restore',target_type='canvas',target_id=canvas['id'],reason='显式恢复'),actor='test-human',expected_revision=2,idempotency_key='migration-restore')
            self.assertEqual(result['state'],'active');self.assertEqual(service.get_creative_canvas(p,canvas['id'])['version_id'],canvas['version_id'])

    def test_canvas_typed_draft_and_generation_job_cannot_escape_lifecycle(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();provider='canvas_lifecycle_'+uuid.uuid4().hex
        self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
        model=self.service.register_model(dict(provider_id=provider,model_key='video',model_version='offline',modality='video',capabilities=dict(purposes=['text_to_video','video_clip'],first_frame=True)),actor='test-admin')
        canvas=self.write('create_creative_canvas',dict(episode_id=o['episode'],document={'nodes':[dict(id='out',type='video',text='合成固定输入')],'edges':[]}))
        draft=self.write('prepare_canvas_work_input',dict(canvas_id=canvas['id'],canvas_revision=1,node_id='out',shot_id=o['shot'],model_id=model['id']))
        self.command('trash',target_type='canvas',target_id=canvas['id'],reason='草稿已固定后回收')
        with self.assertRaises(ResourceError) as caught:self.write('generate_canvas_work',dict(request={'draft_version_id':draft['draft_version_id']},preview_sha256='0'*64))
        self.assertEqual(caught.exception.code,'object_recycled')
        self.command('restore',target_type='canvas',target_id=canvas['id'],reason='恢复后检查原任务')
        self.artifact(objects=[o['shot']]);self.artifact('state','scene-state',[o['scene']],{'state_versions':[{'scene_id':o['scene']}]})
        import io
        from PIL import Image
        content=io.BytesIO();Image.new('RGB',(8,8),'green').save(content,format='PNG')
        staged=self.service.storage.stage_upload(io.BytesIO(content.getvalue()),'lifecycle.png')
        image=self.write('register_media',dict(staged_upload=staged['staged_upload'],rights='owned',source={'kind':'test','content':'synthetic owned image'}))['id']
        self.write('record_media_check',dict(media_id=image,checker='test-probe',criteria_version='1',outcome='pass'))
        self.select(self.candidate(o['shot'],image))
        request={'prompt':'固定画面','params':{},'first_frame_media_id':image};run=self.production_run(o['shot'],request)
        context=self.service.compile_shot_context(self.p,o['shot'],'video_clip')
        job=self.write('create_generation_job',dict(run_version_id=run,shot_id=o['shot'],purpose='video_clip',modality='video',model_id=model['id'],context_sha256=context['sha256'],request_payload=request))
        self.write('save_creative_canvas',dict(canvas_id=canvas['id'],canvas_revision=1,document={'nodes':[dict(id='out',type='video',job_id=job['id'])],'edges':[]}))
        protected=self.command('trash',target_type='canvas',target_id=canvas['id'],reason='在途任务不能回收')
        self.assertEqual(protected['status'],'protected');self.assertTrue(any(r['table']=='generation_jobs' for r in protected['reasons']))
        self.write('update_generation_job',dict(job_id=job['id'],status='failed',raw_response={'synthetic':'terminal local failure'}))
        self.command('trash',target_type='canvas',target_id=canvas['id'],reason='任务结束后可回收')
        self.assertEqual(self.service.get_generation_job(self.p,job['id'])['status'],'failed')
        self.assertEqual(self.service.get_artifact_version(self.p,run)['id'],run)

    def test_canvas_http_recycle_restore_and_current_readback(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test-token','human_identity':'test-human','background_enabled':False},catalog=ResourceCatalog(root,self.service),service=self.service)
            with TestClient(app) as client:
                login=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'})
                headers={'X-CSRF-Token':login.json()['csrf_token'],'Origin':'http://testserver'}
                endpoint='/api/v1/projects/'+self.p+'/management';revision=self.rev
                for operation in ('trash','restore'):
                    body={'payload':dict(operation=operation,target_type='canvas',target_id=canvas['id'],reason='HTTP生命周期'),'expected_revision':revision,'idempotency_key':uuid.uuid4().hex}
                    result=client.post(endpoint,json=body,headers=headers);self.assertEqual(result.status_code,200,result.text)
                    self.assertEqual(client.post(endpoint,json=body,headers=headers).json(),result.json());revision=result.json()['revision']
                    page=client.get('/api/v1/project-management/recycle-items?kind=canvas',headers=headers)
                    self.assertEqual(page.status_code,200,page.text)
                    self.assertEqual(any(r['target_id']==canvas['id'] for r in page.json()['items']),operation=='trash')
                self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['version_id'],canvas['version_id'])

    def test_canvas_identity_does_not_share_the_creative_object_namespace(self):
        from unittest.mock import patch
        o=self.hierarchy()
        with patch('vsc.adapters.persistence.postgres.creative_canvas.new_id',side_effect=[o['shot'],str(uuid.uuid4())]):
            canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        self.assertEqual(canvas['id'],o['shot'])
        self.command('trash',target_type='object',target_id=o['shot'],reason='仅回收创作对象')
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['id'],canvas['id'])
        self.command('restore',target_type='object',target_id=o['shot'],reason='恢复对象')
        self.command('trash',target_type='canvas',target_id=canvas['id'],reason='仅回收画布')
        self.assertIn(o['shot'],[r['id'] for r in self.service.get_project_tree(self.p)['nodes']])
        artifact=self.write('create_artifact',dict(artifact_type='memo',artifact_key='object-still-active',document='独立对象仍可写',object_ids=[o['shot']]))
        self.assertTrue(artifact['id'])

    def test_template_consumers_enforce_lifecycle_but_preserve_history_and_receipt_replay(self):
        from vsc.assets.resource_service import ResourceError
        o=self.hierarchy();canvas=self.write('create_creative_canvas',dict(episode_id=o['episode'],title='模板原画布',document={'nodes':[],'edges':[]}))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='固定模板'))
        payload=dict(source_project_id=self.p,template_id=template['id'],episode_id=None,title='有效副本')
        favorite=dict(template_id=template['id'],active=True)
        prior={}
        for method,body in [('copy_canvas_template',payload),('copy_fixed_canvas_template',payload),('favorite_canvas_template',favorite)]:
            key=uuid.uuid4().hex;prior[method]=(body,key,self.write(method,body,idempotency_key=key))
        for typ,identifier in [('canvas',canvas['id']),('object',o['episode']),('object',o['work']),('project',self.p)]:
            with self.subTest(source=typ,identifier=identifier):
                self.command('trash',target_type=typ,target_id=identifier,reason='模板来源暂停')
                if typ=='project':
                    with self.assertRaises(ResourceError):self.service.list_canvas_templates(self.p,'test-human')
                else:self.assertNotIn(template['id'],[r['id'] for r in self.service.list_canvas_templates(self.p,'test-human')['items']])
                for method,body in [('copy_canvas_template',payload),('copy_fixed_canvas_template',payload),('favorite_canvas_template',favorite)]:
                    with self.subTest(method=method),self.assertRaises(ResourceError):self.write(method,body)
                    original,key,result=prior[method]
                    replay=getattr(self.service,method)(self.p,original,actor='test-human',expected_revision=0,idempotency_key=key)
                    self.assertEqual(replay,result)
                with self.assertRaises(ResourceError):self.service.preview_canvas_template_copy(self.p,payload)
                self.assertEqual(self.service.get_creative_canvas_version(self.p,canvas['version_id'])['id'],canvas['version_id'])
                self.assertEqual(self.store.get_canvas_template(self.p,template['id'])['version_id'],canvas['version_id'])
                self.command('restore',target_type=typ,target_id=identifier,reason='恢复原来源')
                self.assertIn(template['id'],[r['id'] for r in self.service.list_canvas_templates(self.p,'test-human')['items']])
                self.assertEqual(self.service.preview_canvas_template_copy(self.p,payload)['source_sha256'],canvas['sha256'])
        for method in ('copy_canvas_template','copy_fixed_canvas_template'):
            copied=self.write(method,payload)
            self.assertEqual(copied['source_version_id'],canvas['version_id']);self.assertNotEqual(copied['id'],canvas['id'])
