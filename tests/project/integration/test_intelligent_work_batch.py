"""Episode workspace batches reuse original artifacts/jobs; no real host or provider."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json,os,tempfile,unittest,uuid
from unittest.mock import patch
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS
from vsc.assets.resource_service import ResourceError,Conflict
from support.fixtures.intelligent_batch import IntelligentBatchSetup


class SyntheticPlanner:
    def __init__(self,plan):self.plan=plan;self.calls=0
    def available(self):return True
    def generate(self,packet,task,skill):self.calls+=1;return deepcopy(self.plan)


@unittest.skipUnless(HAS_DB_DEPS and os.environ.get('VSC_TEST_DATABASE_URL'),'requires isolated PostgreSQL')
class IntelligentWorkBatchTests(IntelligentBatchSetup,ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy()
        self.flow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='本集固定批次',route='storyboard_video',script_text='角色确认门外声音后，走近门边。'))['id']
    def counts(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:return {name:conn.scalar(select(func.count()).select_from(getattr(S,name)).where(getattr(S,name).c.project_id==self.p)) for name in ('generation_jobs','intelligent_runs','workbench_run_inputs')}

    def test_episode_script_freeze_replay_scope_and_stale_autosave(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        content=dict(format='vsc.screenplay/v1',body='从原稿继续：门外突然传来敲门声。',adaptation_refs=[],scenes=[])
        self.service.save_script_draft(self.p,dict(scope_key=self.objects['episode'],base_draft_revision=0,content=content),actor='test-human')
        payload=dict(episode_id=self.objects['episode'],title='从原稿继续',script_draft_revision=1)
        result=self.write('create_intelligent_workflow',payload,idempotency_key='continue-script')
        self.assertEqual(result,self.write('create_intelligent_workflow',payload,idempotency_key='continue-script'))
        reopened=self.service.get_intelligent_workflow(self.p,result['id']);source=reopened['state']['source_artifact_id']
        self.assertEqual(reopened['state']['document']['script_text'],content['body'])
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p,source)['document'])['body'],content['body'])
        self.service.save_script_draft(self.p,dict(scope_key=self.objects['episode'],base_draft_revision=1,content=dict(content,body='另一个尚未制作的新稿')),actor='test-human')
        with self.assertRaises(Conflict):self.write('create_intelligent_workflow',payload)
        other=self.write('create_object',dict(kind='episode',display_code='EP-OTHER',parent_id=self.objects['work'],ordinal=1))['id']
        with self.assertRaises(ResourceError):self.write('create_intelligent_workflow',dict(episode_id=other,source_artifact_id=source))
        with self.engine.connect() as conn:self.assertEqual(conn.scalar(select(func.count()).select_from(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p)),0)
        self.assertEqual(self.service.get_intelligent_workflow(self.p,result['id'])['state']['document']['script_text'],content['body'])

    def test_fixed_form_reuse_keeps_original_spec_media_and_missing_scope(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        image=self.media('已有雨衣形态')
        card=self.write('save_asset_card',dict(name='原人物',asset_kind='character',base_revision=0,forms=[dict(form_key='coat',name='雨衣',base_version_id=None,description='已固定雨衣',media_id=image)]))
        plan=dict(message='复用原人物形态',questions=[],assets=[dict(key='person',name='原人物',kind='character',description='不要重造',variants=['coat'])],units=[])
        self.service.intelligent_planner=SyntheticPlanner(plan)
        task=self.write('create_intelligent_task',dict(workflow_id=self.flow,base_version_id=self.detail()['version']['id'],stage='assets',message='复用已固定形态'))
        self.service.execute_intelligent_task(self.p,task['id']);self.rev=self.service.get_project(self.p)['revision']
        with self.engine.connect() as conn:before=conn.scalar(select(func.count()).select_from(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id==self.p))
        self.write('decide_intelligent_task',dict(task_id=task['id'],outcome='confirm',reason='明确使用已有雨衣',asset_mapping={'person':card['id']},asset_form_mapping={'person_coat':dict(kind='asset_card',version_id=card['forms'][0]['version_id'])}))
        current=self.detail();self.assertEqual(current['asset_inputs'][0]['media_id'],image);self.assertEqual(current['state']['assets'][0]['spec_id'],card['forms'][0]['spec_id'])
        with self.engine.connect() as conn:self.assertEqual(conn.scalar(select(func.count()).select_from(S.asset_spec_versions).where(S.asset_spec_versions.c.project_id==self.p)),before)
        missing=self.service.preview_intelligent_missing_assets(self.p,dict(workflow_id=self.flow,version_id=current['version']['id']))
        self.assertEqual(missing['items'][0]['status'],'already_selected')
        state=current['state'];state['units']=[dict(self.unit('shot',self.objects['shot']),asset_keys=['person_coat'])];state['route']='multi_reference_video';self.save(state)
        compiled=self.service._compile_intelligent_drafts(self.p,dict(workflow_id=self.flow,version_id=self.detail()['version']['id'],unit_keys=['shot'],purpose='video'))
        self.assertEqual(compiled[0]['document']['references'][0]['media_id'],image)
        self.assertEqual(compiled[0]['document']['references'][0]['episode_asset_form_version_id'],self.detail()['asset_inputs'][0]['episode_asset_form_version_id'])

    def test_partial_batch_original_jobs_professional_inputs_receipt_and_replay(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        request=self.prepared(blocked=True);preview=self.service.preview_intelligent_work_batch(self.p,request)
        self.assertTrue(preview['ready']);self.assertFalse(preview['all_ready']);self.assertEqual(len(preview['ready_items']),2);self.assertEqual([r['unit_key'] for r in preview['blocked_items']],['missing'])
        self.assertEqual(preview['native_units']['remote_jobs'],2)
        payload=dict(request=request,preview_sha256=preview['preview_sha256']);out=self.write('generate_intelligent_work_batch',payload,idempotency_key='fixed-batch')
        self.assertEqual(out,self.write('generate_intelligent_work_batch',payload,idempotency_key='fixed-batch'));self.assertEqual(self.counts(),dict(generation_jobs=2,intelligent_runs=2,workbench_run_inputs=2))
        receipt=json.loads(self.service.get_artifact_version(self.p,out['id'])['document']);self.assertEqual(receipt['state_sha256'],preview['state_sha256']);self.assertFalse(receipt['auto_first_cut']);self.assertEqual(receipt['blocked_items'],preview['blocked_items'])
        source=self.detail()['state']['source_artifact_id']
        with self.engine.connect() as conn:
            for run in out['runs']:
                doc=json.loads(self.store._one(conn,S.artifact_versions,self.p,run['run_artifact_id'])['document']);self.assertEqual(doc['execution_policy'],request['execution_policy']);self.assertNotIn(source,[p['id'] for p in doc['approved_inputs']])
                deps=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==self.p,S.artifact_dependencies.c.artifact_id==run['draft_artifact_id'])).scalars());self.assertIn(source,deps)
                job=self.service.get_generation_job(self.p,run['job_ids'][0]);self.assertIn('建立门外威胁',job['request_payload']['prompt']);self.assertIn('保留门外敲击声',job['request_payload']['prompt'])
        self.assertEqual(len(self.detail()['batches']),1)
        self.assertEqual(self.service.budget_status(self.p)['bounded_reservations'],[])

    def test_whole_batch_rejects_duplicate_scope_drift_and_rolls_back(self):
        request=self.prepared(duplicate=True)
        with self.assertRaises(ResourceError) as duplicate:self.service.preview_intelligent_work_batch(self.p,request)
        self.assertEqual(duplicate.exception.code,'batch_duplicate_target');self.assertEqual(self.counts()['generation_jobs'],0)
        state=self.detail()['state'];shot=self.write('create_object',dict(kind='shot',display_code='SHOT-C',parent_id=self.objects['sequence'],ordinal=2))['id'];state['units'][1]['shot_id']=shot
        link=next(row for row in state['media'] if row['unit_key']=='two')
        candidate=self.write('propose_binding',dict(target_object_id=shot,media_id=link['media_id'],role='first_frame',slot_key='workbench'))
        link['working_selection_version_id']=self.write('save_working_selection',dict(shot_id=shot,output_kind='image',candidate_id=candidate['candidate_id'],base_version_id=None))['selection_version_id'];self.save(state)
        request.update(version_id=self.detail()['version']['id'])
        prepared=self.write('prepare_intelligent_drafts',{k:request[k] for k in ('workflow_id','version_id','unit_keys','purpose')}|request['preparation']);request['items']=[dict(unit_key=r['unit_key'],draft_artifact_id=r['draft_artifact_id']) for r in prepared['items']]
        quote=self.service.preview_intelligent_work_batch(self.p,request);body=dict(request=request,preview_sha256=quote['preview_sha256']);original=self.store.generate_workbench;calls=[]
        def fail_second(*args,**kw):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('synthetic downstream fault')
            return original(*args,**kw)
        with patch.object(self.store,'generate_workbench',side_effect=fail_second),self.assertRaises(RuntimeError):self.write('generate_intelligent_work_batch',body)
        self.assertEqual(self.counts(),dict(generation_jobs=0,intelligent_runs=0,workbench_run_inputs=0));self.assertEqual(self.detail()['batches'],[])
        from vsc.production.resource_settings import ResourceSettings
        ResourceSettings(self.store).enabled(self.model['id'],False,'test-human')
        with self.assertRaises(Conflict):self.write('generate_intelligent_work_batch',body)
        self.assertEqual(self.counts()['generation_jobs'],0)
        ResourceSettings(self.store).enabled(self.model['id'],True,'test-human')
        self.write('configure_budget',dict(limits={'remote_jobs':10,'video_seconds':50},reason='模拟确认后的预算变化'))
        with self.assertRaises(Conflict):self.write('generate_intelligent_work_batch',body)
        self.assertEqual(self.counts()['generation_jobs'],0)
        # Merely changing the client manifest may not hide a ready unit.
        omitted=deepcopy(request);omitted['items']=omitted['items'][:1]
        with self.assertRaises(ResourceError):self.service.preview_intelligent_work_batch(self.p,omitted)

    def test_http_confirmation_and_planning_material_drift_fail_before_execution(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        request=self.prepared();quote=self.service.preview_intelligent_work_batch(self.p,request)
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app({'projects_root':directory+'/projects','media_root':directory,'access_token':'test-token','human_identity':'test-human','allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'background_enabled':False},service=self.service)) as client:
            session=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'});headers={'Origin':'http://testserver','X-CSRF-Token':session.json()['csrf_token']}
            body=dict(payload=dict(request=request,preview_sha256=quote['preview_sha256']),expected_revision=self.rev,idempotency_key='http-batch')
            url='/api/v1/projects/'+self.p+'/intelligent-work-batches'
            self.assertEqual(client.post(url,json=body,headers=headers).status_code,422);self.assertEqual(self.counts()['generation_jobs'],0)
            response=client.post(url,json=dict(body,confirmed=True),headers=headers);self.assertEqual(response.status_code,200,response.text);self.rev=response.json()['revision']
            self.assertEqual(client.post(url,json=dict(body,confirmed=True),headers=headers).json(),response.json())
        planner=SyntheticPlanner(dict(message='不会调用',questions=[],assets=[],units=[]));self.service.intelligent_planner=planner
        task=self.write('create_intelligent_task',dict(workflow_id=self.flow,base_version_id=self.detail()['version']['id'],stage='assets',message='明确读取固定专业方法'))
        packet=self.service.get_role_dispatch(self.p,task['dispatch_id'])['packet'];manifest=json.loads(packet['parent_brief']['content'])['role_materials_manifest'];self.assertTrue(manifest['entries'])
        with patch('vsc.production.role_materials.compile_role_materials',side_effect=ResourceError('fixed materials changed','role_materials_changed')):
            failed=self.service.execute_intelligent_task(self.p,task['id'])
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['error'],'role_materials_changed');self.assertEqual(planner.calls,0)
