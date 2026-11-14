"""Original facts in an isolated PostgreSQL schema; no remote generation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import uuid
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError
from vsc.assets.access_control import Principal,set_principal,reset_principal
from vsc.assets.text_tools import COMMON,DEFAULTS


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class TaskCenterPresentationTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        temporary=tempfile.TemporaryDirectory(prefix='vsc-task-presentation-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.service.storage=LocalStorage(self.root/'storage')
        self.owner=self.service.ensure_local_access('test-human')
        token=set_principal(Principal(**self.owner));self.addCleanup(reset_principal,token)
        self.objects=self.hierarchy()

    def jobs(self,statuses):
        """Persist synthetic native facts, without a provider client or worker."""
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        run=self.write('create_artifact',dict(artifact_key='presentation:'+uuid.uuid4().hex,
            artifact_type='production-run',document={'synthetic_task_presentation':True}))
        provider='presentation-'+uuid.uuid4().hex;model=str(uuid.uuid4());ids=[]
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider,name='isolated synthetic',modality='image',
                base_url='https://example.invalid',auth_ref='none',enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model,provider_id=provider,model_key='fixture',
                modality='image',model_version='1',capabilities={},default_params={},cost_rule={},enabled=True))
            for number,status in enumerate(statuses):
                identifier=str(uuid.uuid4());ids.append(identifier)
                conn.execute(insert(S.generation_jobs).values(project_id=self.p,id=identifier,run_version_id=run['id'],
                    shot_id=self.objects['shot'],purpose='first_frame',modality='image',candidate_no=number,
                    provider_id=provider,model_id=model,model_version='1',request_payload={},
                    request_sha256='0'*64,context_sha256='0'*64,idempotency_key=identifier,status=status,attempt=1))
        return ids

    def output(self,job,name='合成结果'):
        import io
        from support.fixtures.media import production_media
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        staged=self.service.storage.stage_upload(io.BytesIO(production_media()['png']),name+'.png')
        media=self.write('register_media',dict(staged_upload=staged['staged_upload'],rights='owned',
            source={'kind':'synthetic-owned','content':'isolated fixture pixels'}))['id']
        self.write('record_media_check',dict(media_id=media,checker='fixture-probe',criteria_version='1',outcome='pass'))
        with self.engine.begin() as conn:conn.execute(insert(S.job_outputs).values(
            project_id=self.p,id=str(uuid.uuid4()),job_id=job,media_id=media,asset_type='image'))
        return media

    def test_groups_use_filtered_mother_set_not_current_page(self):
        from sqlalchemy import event
        ids=self.jobs(['created']*25+['failed','submission_unknown','cancelled','succeeded','succeeded'])
        self.output(ids[-1]);statements=[]
        def record(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        event.listen(self.engine,'before_cursor_execute',record)
        try:page=self.service.get_task_center(self.p,kind='generation',limit=2)
        finally:event.remove(self.engine,'before_cursor_execute',record)
        self.assertEqual(page['groups'],dict(all=30,attention=1,running=25,result=1,ended=1,unknown=2))
        self.assertEqual(page['total'],30);self.assertEqual(len(page['items']),2);self.assertEqual(page['next_offset'],2)
        first_queries=len(statements)
        for group,count in page['groups'].items():
            if group=='all':continue
            with self.subTest(group=group):
                found=self.service.get_task_center(self.p,kind='generation',group=group,limit=100)
                self.assertEqual(found['groups'],page['groups']);self.assertEqual(found['total'],count)
                self.assertTrue(all(row['presentation']['group']==group for row in found['items']))
        second=self.service.get_task_center(self.p,kind='generation',offset=2,limit=2)
        self.assertTrue({r['id'] for r in page['items']}.isdisjoint(r['id'] for r in second['items']))
        episode=self.service.get_task_center(self.p,episode_id=self.objects['episode'],kind='generation',status='failed')
        self.assertEqual(episode['groups'],dict(all=1,attention=1,running=0,result=0,ended=0,unknown=0))
        # Another 30 rows change the mother set, not the per-page enrichment query count.
        self.jobs(['created']*30);statements.clear();event.listen(self.engine,'before_cursor_execute',record)
        try:larger=self.service.get_task_center(self.p,kind='generation',limit=2)
        finally:event.remove(self.engine,'before_cursor_execute',record)
        self.assertEqual(larger['total'],60);self.assertEqual(len(statements),first_queries)
        self.assertLess(first_queries,25)
        print('TASK_PRESENTATION_QUERY_COUNTS',{'tasks_30':first_queries,'tasks_60':len(statements),'returned':2})
        for kwargs in ({'group':'invented'},{'limit':0},{'episode_id':self.objects['shot']}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ResourceError):self.service.get_task_center(self.p,**kwargs)

    def test_result_working_choice_and_formal_adoption_are_separate_facts(self):
        job=self.jobs(['succeeded'])[0];media=self.output(job)
        before=self.service.get_task_origin(self.p,'generation',job)['task']
        self.assertEqual(before['result']['count'],1);self.assertTrue(before['result']['available'])
        self.assertEqual(before['result']['working_selection'],{'known':True,'count':0})
        self.assertEqual(before['result']['adoption'],{'known':True,'count':0})
        self.assertIn('EPISODE',before['presentation']['object_path']);self.assertIn('SHOT',before['presentation']['object_path'])
        other_shot=self.write('create_object',dict(kind='shot',display_code='OTHER_SHOT',parent_id=self.objects['sequence'],ordinal=1))['id']
        unrelated=self.candidate(other_shot,media);self.select(unrelated)
        self.write('save_working_selection',dict(shot_id=other_shot,output_kind='image',
            candidate_id=unrelated['candidate_id'],base_version_id=None))
        reused=self.service.get_task_origin(self.p,'generation',job)['task']['result']
        self.assertEqual(reused['adoption']['count'],0);self.assertEqual(reused['working_selection']['count'],0)
        candidate=self.candidate(self.objects['shot'],media)
        self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='image',
            candidate_id=candidate['candidate_id'],base_version_id=None))
        selected=self.service.get_task_origin(self.p,'generation',job)['task']
        self.assertEqual(selected['result']['working_selection']['count'],1)
        self.assertEqual(selected['result']['adoption']['count'],0)
        self.select(candidate)
        adopted=self.service.get_task_origin(self.p,'generation',job)['task']
        self.assertEqual(adopted['result']['adoption']['count'],1)
        self.assertEqual(adopted['href'],before['href']);self.assertFalse(adopted['usage']['amount_known'])
        self.assertIsNone(adopted['usage']['actual_cost']);self.assertEqual(adopted['usage']['units'],[])
        notices=self.service.get_task_notifications(self.p)['items']
        notice=next(row for row in notices if row['origin_id']==job)
        self.assertEqual(notice['href'],adopted['href'])

    def test_usage_pages_reuse_reservations_actual_bound_and_release(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        ids=self.jobs(['running','failed','cancelled'])
        self.write('configure_budget',dict(limits={'remote_jobs':10,'images':30},reason='Synthetic native budget fixture'))
        with self.engine.begin() as conn:
            for identifier in ids:
                for unit,bound in (('remote_jobs',1),('images',5)):
                    conn.execute(insert(S.job_budget_reservations).values(project_id=self.p,id=str(uuid.uuid4()),
                        job_id=identifier,unit=unit,bound=bound,status='reserved',limit_revision=self.rev))
            self.store._settle_budget(conn,self.p,{'id':ids[1]},{'remote_jobs':1,'images':2})
            self.store._settle_budget(conn,self.p,{'id':ids[2]},{'remote_jobs':0,'images':0})
        before=self.service.budget_status(self.p);revision=self.rev
        usage=self.service.get_task_usage(self.p,limit=1)
        self.assertEqual(usage['total'],3);self.assertEqual(usage['next_offset'],1)
        self.assertEqual(usage['used'],before['used']);self.assertEqual(usage['used'],{'remote_jobs':2,'images':7})
        self.assertEqual(usage['reported_actual'],{'remote_jobs':1,'images':2})
        self.assertEqual(usage['bounded'],{'remote_jobs':1,'images':5})
        self.assertEqual(usage['remaining'],{'remote_jobs':8,'images':23})
        rows=[]
        for offset in range(3):rows.extend(self.service.get_task_usage(self.p,offset=offset,limit=1)['items'])
        self.assertEqual({row['id'] for row in rows},set(ids));self.assertEqual(len(rows),3)
        by_id={row['id']:row for row in rows}
        reserved=next(unit for unit in by_id[ids[0]]['units'] if unit['unit']=='images')
        self.assertIsNone(reserved['actual']);self.assertEqual((reserved['occupied'],reserved['basis']),(5,'bound'))
        settled=next(unit for unit in by_id[ids[1]]['units'] if unit['unit']=='images')
        self.assertEqual((settled['actual'],settled['occupied'],settled['released'],settled['basis']),(2,2,3,'actual'))
        released=next(unit for unit in by_id[ids[2]]['units'] if unit['unit']=='images')
        self.assertEqual((released['actual'],released['occupied'],released['released'],released['basis']),(0,0,5,'released'))
        self.assertTrue(all(row['actual_cost'] is None and not row['amount_known'] for row in rows))
        self.write('record_generation_bill',dict(job_id=ids[1],actual_cost={'amount':'0.80','currency':'CNY',
            'evidence':'Synthetic isolated invoice, not a production bill'}))
        detail=self.service.get_task_origin(self.p,'generation',ids[1])['task']['usage']
        self.assertEqual(detail['actual_cost']['amount'],'0.80');self.assertTrue(detail['amount_known'])
        self.assertEqual(detail['units'],by_id[ids[1]]['units'])
        self.assertEqual(self.service.budget_status(self.p)['used'],before['used'])
        self.assertEqual(self.service.get_task_usage(self.p,offset=3)['items'],[])
        self.assertEqual(self.service.get_project(self.p)['revision'],revision+1)

    def test_batch_mixed_children_are_not_recounted_as_usage(self):
        class Host:
            name='synthetic-task-presentation'
            def available(self):return True
            def generate(self,tool,action,document,references):
                if document['source_text'].startswith('失败'):raise ResourceError('synthetic failure','text_host_failed')
                return {'analysis':'固定第一行分析','category':'短剧','channel':'家庭','card_start_line':1,'card_end_line':2}
        self.service.text_tool_host=Host();self.addCleanup(delattr,self.service,'text_tool_host');units=[]
        for index,title in enumerate(('成功片段','失败片段')):
            unit=self.write('save_text_tool',dict(tool='scoring',group_key='presentation',unit_key=str(index),
                title=title,ordinal=index,episode_id=self.objects['episode'],base_version_id=None,
                document={**deepcopy(COMMON),**deepcopy(DEFAULTS['scoring']),'source_text':title+'\n第二行'}))
            units.append(unit['unit_id'])
        batch=self.write('create_text_batch',dict(tool='scoring',action='analyze',unit_ids=units,auto_accept=False))
        for _ in range(3):self.write('process_text_batch',dict(batch_id=batch['id']))
        page=self.service.get_task_center(self.p,kind='text_batch',episode_id=self.objects['episode'])
        self.assertEqual(page['groups']['all'],1);self.assertEqual(page['groups']['attention'],1)
        row=page['items'][0];self.assertEqual(row['presentation']['group'],'attention');self.assertEqual(len(row['children']),2)
        self.assertEqual(row['progress']['completed'],1);self.assertEqual(row['progress']['failed'],1)
        self.assertTrue(row['result']['available']);self.assertFalse(row['result']['adoption']['known'])
        self.assertEqual(self.service.get_task_usage(self.p)['total'],0)
        detail=self.service.get_task_origin(self.p,'text_batch',batch['id'])['task']
        self.assertEqual(detail['usage']['coverage'],'not_recorded');self.assertFalse(detail['usage']['amount_known'])
        self.write('stop_text_batch',dict(batch_id=batch['id']))
        stopped=self.service.get_task_origin(self.p,'text_batch',batch['id'])['task']
        self.assertEqual(stopped['presentation']['group'],'ended');self.assertTrue(stopped['result']['available'])

    def test_empty_and_fully_released_project_keep_sparse_native_facts(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        empty=self.service.get_task_usage(self.p)
        self.assertEqual(empty['items'],[]);self.assertEqual(empty['total'],0)
        self.assertEqual(empty['used'],{});self.assertEqual(empty['reported_actual'],{})
        job=self.jobs(['cancelled'])[0]
        self.write('configure_budget',dict(limits={'remote_jobs':3,'video_seconds':40},reason='Synthetic release-only project'))
        with self.engine.begin() as conn:conn.execute(insert(S.job_budget_reservations).values(
            project_id=self.p,id=str(uuid.uuid4()),job_id=job,unit='remote_jobs',bound=1,status='reserved',limit_revision=self.rev))
        unreported=self.service.get_task_usage(self.p)
        self.assertEqual(unreported['used'],{'remote_jobs':1,'video_seconds':0});self.assertEqual(unreported['reported_actual'],{})
        self.assertEqual(unreported['bounded'],{'remote_jobs':1,'video_seconds':0})
        self.assertIsNone(unreported['items'][0]['units'][0]['actual'])
        with self.engine.begin() as conn:self.store._settle_budget(conn,self.p,{'id':job},{'remote_jobs':0})
        released=self.service.get_task_usage(self.p)
        self.assertEqual(self.service.budget_status(self.p)['used'],{})
        self.assertEqual(released['used'],{'remote_jobs':0,'video_seconds':0})
        self.assertEqual(released['reported_actual'],{'remote_jobs':0});self.assertEqual(released['remaining'],{'remote_jobs':3,'video_seconds':40})
        self.assertEqual(released['total'],1);self.assertEqual(released['items'][0]['units'][0]['released'],1)
        other=self.service.create_project({'name':'Other owned task scope'},actor='test-human')['id']
        self.assertEqual(self.service.get_task_usage(other)['items'],[])
        with self.assertRaises(ResourceError):self.service.get_task_origin(other,'generation',job)
        with self.assertRaises(ResourceError):self.service.get_task_center(other,episode_id=self.objects['episode'])

    def test_all_ten_domains_project_original_targets_and_registered_results(self):
        from vsc.assets.spatial_scene import default_scene
        class Lyrics:
            name='synthetic-lyrics-presentation'
            def available(self):return True
            def generate(self,*args):return dict(title='合成歌词',lyrics='合成建议',notes='无供应商调用')
        class Text:
            name='synthetic-text-presentation'
            def available(self):return True
            def generate(self,*args):return dict(analysis='第一行固定分析',category='短剧',channel='家庭',card_start_line=1,card_end_line=2)
        self.service.lyric_planner=Lyrics();self.addCleanup(delattr,self.service,'lyric_planner')
        self.service.text_tool_host=Text();self.addCleanup(delattr,self.service,'text_tool_host')
        job=self.jobs(['succeeded'])[0];media=self.output(job)
        self.write('create_media_import',dict(title='合成导入',episode_id=self.objects['episode'],
            files=[dict(filename='fixture.txt',size_bytes=1,sha256='a'*64)],rights='unknown',source_evidence=''))
        unit=self.write('save_text_tool',dict(tool='scoring',group_key='ten-domains',unit_key='one',title='原文单元',
            ordinal=0,episode_id=self.objects['episode'],base_version_id=None,
            document={**deepcopy(COMMON),**deepcopy(DEFAULTS['scoring']),'source_text':'原文第一行\n第二行'}))
        self.write('create_text_batch',dict(tool='scoring',action='analyze',unit_ids=[unit['unit_id']],auto_accept=False))
        self.write('run_text_tool',dict(unit_id=unit['unit_id'],input_version_id=unit['version_id'],action='analyze',new_attempt=False))
        self.rev=self.service.get_project(self.p)['revision']
        canvas=self.write('create_creative_canvas',dict(episode_id=self.objects['episode'],document=dict(nodes=[],edges=[])))
        turn=self.write('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=1,message='隔离原任务',skill_id='vsc-assets'))
        spatial=self.write('create_spatial_scene',dict(mode='blocking',scene_id=self.objects['scene'],title='原空间场景',document=default_scene()))
        self.write('create_spatial_export',dict(spatial_scene_id=spatial['id'],scene_revision=1,camera_id='camera-a',format='png',time=0))
        self.write('create_spatial_plan_task',dict(spatial_scene_id=spatial['id'],scene_revision=1,message='隔离场景计划'))
        workflow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='原智能制作',script_text='合成输入'))
        detail=self.service.get_intelligent_workflow(self.p,workflow['id'])
        self.write('create_intelligent_task',dict(workflow_id=workflow['id'],base_version_id=detail['version']['id'],stage='assets',message='隔离资产计划'))
        draft=self.write('save_creative_tool_draft',dict(base_draft_id=None,document=dict(tool='lyrics',
            episode_id=self.objects['episode'],prompt='合成主题',lyrics='人工固定稿')))
        self.write('create_creative_lyrics',dict(draft_version_id=draft['id'],new_attempt=False));self.rev=self.service.get_project(self.p)['revision']
        edit=self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,
            document=dict(format='vsc.edit-workspace/v1',width=128,height=128,fps=24,
                clips=[dict(id='one',media_id=media,in_frame=0,out_frame=12,volume=1)],audio=[],captions=[])))
        self.write('request_edit_export',dict(edit_version_id=edit['edit_version_id']))
        # Original result_ready fact is registration in progress, with no plan yet.
        self.store.claim_canvas_agent_turn(self.p,turn['id'])
        self.store.persist_canvas_agent_result(self.p,turn['id'],{'synthetic_unregistered_result':True},None)
        revision=self.rev;page=self.service.get_task_center(self.p,limit=100)
        self.assertEqual({row['kind'] for row in page['items']},{'generation','editing','spatial','spatial_plan',
            'lyrics','import','text','text_batch','canvas','intelligent'})
        self.assertEqual(page['total'],sum(value for key,value in page['groups'].items() if key!='all'))
        for row in page['items']:
            with self.subTest(kind=row['kind']):
                origin=self.service.get_task_origin(self.p,row['kind'],row['id'])['task']
                self.assertEqual(origin['href'],row['href']);self.assertIn('task_id='+row['id'],row['href'])
                self.assertTrue(origin['presentation']['object_path']);self.assertIn('available',origin['result'])
                if row['kind']!='generation':self.assertEqual(origin['usage']['coverage'],'not_recorded')
                if row['kind']=='canvas':
                    self.assertEqual(row['presentation']['group'],'running');self.assertEqual(row['presentation']['state_label'],'登记中')
                    self.assertFalse(row['result']['available'])
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)

    def test_http_project_acl_episode_scope_and_legacy_budget_consumer(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        job=self.jobs(['submission_unknown'])[0]
        app=create_app(dict(projects_root=str(self.root/'projects'),allowed_hosts=['testserver'],
            allowed_origins=['http://testserver'],access_token='synthetic-task-presentation',
            human_identity='test-human',background_enabled=False),service=self.service)
        with TestClient(app) as client:
            url='/api/v1/projects/'+self.p
            self.assertEqual(client.get(url+'/task-usage').status_code,403)
            response=client.post('/api/v1/session',json={'token':'synthetic-task-presentation'},headers={'Origin':'http://testserver'})
            self.assertEqual(response.status_code,200,response.text)
            for suffix in ('/task-center?group=unknown','/task-center/generation/'+job,'/task-usage','/production-platform/budget'):
                value=client.get(url+suffix);self.assertEqual(value.status_code,200,value.text)
            value=client.get(url+'/task-center?group=unknown').json()
            self.assertEqual(value['groups']['unknown'],1);self.assertEqual(value['items'][0]['presentation']['primary_label'],'核对原任务')
            self.assertEqual(client.get(url+'/task-center?group=invalid').status_code,422)
            self.assertEqual(client.get(url+'/task-usage?limit=0').status_code,422)
            self.assertEqual(client.get(url+'/task-center?episode_id='+self.objects['shot']).status_code,404)
            token=set_principal(None)
            try:other=self.service.create_project({'name':'different owner'},actor='different-owner')['id']
            finally:reset_principal(token)
            for suffix in ('/task-center','/task-center/generation/'+job,'/task-usage','/production-platform/budget'):
                denied=client.get('/api/v1/projects/'+other+suffix);self.assertEqual(denied.status_code,403,denied.text)

