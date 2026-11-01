"""Real isolated state and HTTP; the planner is an explicitly synthetic test backend."""
from copy import deepcopy
import json,os,tempfile,unittest,uuid
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS
from vsc.assets.resource_service import ResourceError,Conflict


def proposal(stage):
    return dict(message='合成工程计划',questions=[],assets=[dict(key='person',name='测试人物',kind='character',description='合成角色描述',variants=['master','coat'])] if stage=='assets' else [],units=[] if stage=='assets' else [dict(unit_key='bu1' if stage=='blocking' else 'vs1',kind='blocking' if stage=='blocking' else 'shot',title='合成单元',description='明确动作',duration_ms=5000,segments=[dict(start_ms=0,end_ms=5000,text='角色向前走')],parent_key='')])
class SyntheticPlanner:
    def __init__(self,result=None):self.result=result;self.calls=0
    def available(self):return True
    def generate(self,packet,task,skill):
        self.calls+=1
        if callable(self.result):return self.result(packet,task,skill)
        return deepcopy(self.result or proposal(task['stage']))

@unittest.skipUnless(HAS_DB_DEPS and os.environ.get('VSC_TEST_DATABASE_URL'),'requires isolated PostgreSQL')
class IntelligentProductionTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.service.intelligent_planner=SyntheticPlanner()
        self.flow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='合成智能流程',route='storyboard',script_text='五秒原创测试剧本。'))['id']
    def detail(self):return self.service.get_intelligent_workflow(self.p,self.flow)
    def save(self,state=None):
        current=self.detail();payload=dict(workflow_id=self.flow,base_version_id=current['version']['id'],state=state or current['state']);impact=self.service.preview_intelligent_change(self.p,payload)
        return self.write('save_intelligent_workflow',dict(payload,impact_sha256=impact['sha256']))
    def task(self,stage='assets',result=None):
        task=self.write('create_intelligent_task',dict(workflow_id=self.flow,base_version_id=self.detail()['version']['id'],stage=stage,message='合成当前阶段计划'))
        self.service.intelligent_planner=SyntheticPlanner(result);out=self.service.execute_intelligent_task(self.p,task['id']);self.rev=self.service.get_project(self.p)['revision'];return out
    def confirm(self,task,**extra):return self.write('decide_intelligent_task',dict(task_id=task['id'],outcome='confirm',reason='确认工程操作计划',sequence_id=self.objects['sequence'],**extra))
    def unit(self,key='u1',kind='shot',shot=None):return dict(unit_key=key,kind=kind,title=key,description='合成动作描述',duration_ms=5000,segments=[dict(start_ms=0,end_ms=5000,text='走近')],skip_reason='',lineart_purpose='none',shot_id=shot or self.objects['shot'],spatial_version_id=None)

    def test_real_role_plan_edits_import_assets_variants_shots_and_fixed_templates(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        task=self.task();self.assertEqual(task['status'],'planned');edited=deepcopy(task['plan']);edited['assets'][0]['name']='人工修改角色';self.confirm(task,plan=edited)
        current=self.detail();self.assertEqual(len(current['state']['assets']),2);self.assertEqual(len({a['asset_id'] for a in current['state']['assets']}),1)
        self.assertIn('人工修改角色',[n['title'] for n in self.service.get_project_tree(self.p)['nodes']])
        self.save();template=self.detail()['state']['template_artifact_id'];self.assertTrue(template)
        task=self.task('script');self.confirm(task);current=self.detail();self.assertEqual(current['state']['units'][0]['kind'],'shot');self.assertNotEqual(current['state']['units'][0]['shot_id'],self.objects['shot'])
        self.assertEqual(current['state']['template_artifact_id'],template)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.dispatch_returns).where(S.dispatch_returns.c.project_id==self.p)).scalar_one(),2)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).scalar_one(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p)).scalar_one(),0)

    def test_anchor_dependency_is_fixed_unrelated_unit_proceeds_and_invalid_decision_rejected(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        state=self.detail()['state'];state['units']=[self.unit('anchor','blocking'),self.unit('child','blocking'),self.unit('independent','blocking')];state['dependencies']=[dict(unit_key='child',source_version_id='current',source_unit_key='anchor',purpose='anchor')];self.save(state)
        v=self.detail()['version']['id'];drafts=self.service._compile_intelligent_drafts(self.p,dict(workflow_id=self.flow,version_id=v,unit_keys=['child','independent'],purpose='blocking',model_id=''))
        self.assertEqual(drafts[0]['gaps'][0]['code'],'anchor_not_selected');self.assertEqual(drafts[1]['gaps'],[])
        media=self.media('固定锚');decision=self.select(self.candidate(self.objects['shot'],media));state=self.detail()['state'];state['media']=[dict(unit_key='anchor',purpose='blocking',media_id=media,decision_id=decision['decision_id'],spatial_export_id=None)];self.save(state)
        current=self.detail();self.assertEqual(current['dependency_inputs'][0]['selected'],[])
        state=current['state'];state['dependencies'][0]['source_version_id']='current';self.save(state);self.assertEqual(self.detail()['dependency_inputs'][0]['selected'][0]['media_id'],media)
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.intelligent_media).values(project_id=self.p,version_id=v,unit_key='independent',purpose='reference_image',media_id=media,decision_id=decision['decision_id']))
        state=self.detail()['state'];state['dependencies'][0]['source_version_id']='current';state['dependencies'].append(dict(unit_key='anchor',source_version_id='current',source_unit_key='child',purpose='anchor'))
        with self.assertRaises(ResourceError):self.save(state)
        self.assertEqual(len(self.detail()['state']['dependencies']),1)

    def test_same_task_unknown_stop_late_result_and_stale_plan_preserve_history(self):
        def unknown(*args):raise ResourceError('合成超时','intelligent_submission_unknown')
        task=self.task(result=unknown);self.assertEqual(task['status'],'submission_unknown');backend=self.service.intelligent_planner
        self.service.execute_intelligent_task(self.p,task['id']);self.assertEqual(backend.calls,1)
        self.write('decide_intelligent_task',dict(task_id=task['id'],outcome='stop',reason='停止原未知任务'))
        self.store.persist_intelligent_result(self.p,task['id'],proposal('assets'),None)
        self.assertEqual(self.service.get_intelligent_task(self.p,task['id'])['status'],'stopped')
        planned=self.task();state=self.detail()['state'];state['document']['notes']='其他人更新';self.save(state)
        with self.assertRaises(Conflict):self.confirm(planned)
        self.assertEqual(self.detail()['state']['document']['notes'],'其他人更新')

    def test_timing_change_impact_copy_and_reset_keep_original_objects(self):
        state=self.detail()['state'];state['units']=[self.unit()];self.save(state);first=self.detail();state=deepcopy(first['state']);state['units'][0]['duration_ms']=4000
        payload=dict(workflow_id=self.flow,base_version_id=first['version']['id'],state=state);impact=self.service.preview_intelligent_change(self.p,payload)
        self.assertEqual(impact['warnings'][0]['code'],'duration_mismatch');self.assertFalse(impact['original_media_deleted']);self.save(state)
        copied=self.write('copy_intelligent_unit',dict(workflow_id=self.flow,base_version_id=self.detail()['version']['id'],unit_key='u1'));units=self.detail()['state']['units'];self.assertNotEqual(units[0]['shot_id'],units[1]['shot_id'])
        state=self.detail()['state'];state['units']=[];self.save(state)
        self.assertEqual(self.detail()['state']['units'],[]);self.assertIn(units[1]['shot_id'],[n['id'] for n in self.service.get_project_tree(self.p)['nodes']]);self.assertEqual(len(self.service.get_intelligent_workflow(self.p,self.flow,first['version']['id'])['state']['units']),1)

    def test_historical_routes_use_original_runs_and_unconfigured_models_fail_closed(self):
        self.artifact(objects=[self.objects['shot']]);self.artifact('state','scene-state',[self.objects['scene']],{'state_versions':[{'scene_id':self.objects['scene']}]})
        media=self.media('首帧');decision=self.select(self.candidate(self.objects['shot'],media))
        state=self.detail()['state'];state['route']='storyboard_video';state['units']=[self.unit()];state['media']=[dict(unit_key='u1',purpose='first_frame',media_id=media,decision_id=decision['decision_id'],spatial_export_id=None)];self.save(state)
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        preset=next(r for r in PRESETS if r['id']=='xai-grok-imagine-video');settings={k:v for k,v in preset.items() if k not in ('id','label')};settings.update(enabled=True,model_version='intelligent-offline')
        model=ResourceSettings(self.store).save(settings,'test-human')['id']
        v=self.detail()['version']['id'];drafts=self.write('prepare_intelligent_drafts',dict(workflow_id=self.flow,version_id=v,unit_keys=['u1'],purpose='video',model_id=model))
        policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=3,max_repair_rounds=1,authorization={'mode':'new_batch','reason':'隔离批次'})
        request=dict(workflow_id=self.flow,version_id=v,purpose='video',items=[{k:r[k] for k in ('unit_key','draft_artifact_id')} for r in drafts['items']],execution_policy=policy,commerce_account_actor=None)
        preview=self.service.preview_intelligent_runs(self.p,request);self.assertTrue(preview['ready'],preview)
        result=self.write('propose_intelligent_runs',dict(request=request,preview_sha256=preview['sha256']));artifact=self.service.get_artifact_version(self.p,result['items'][0]['artifact_id']);doc=json.loads(artifact['document']);self.assertEqual(doc['series_batch']['jobs'][0]['request']['first_frame_media_id'],media);self.assertFalse(artifact['approved'])
        state=self.detail()['state'];state['route']='multi_reference_video';self.save(state)
        drafts=self.write('prepare_intelligent_drafts',dict(workflow_id=self.flow,version_id=self.detail()['version']['id'],unit_keys=['u1'],purpose='video',model_id=''))
        request.update(version_id=self.detail()['version']['id'],items=[{k:r[k] for k in ('unit_key','draft_artifact_id')} for r in drafts['items']]);blocked=self.service.preview_intelligent_runs(self.p,request);self.assertFalse(blocked['ready']);self.assertIn('classic_model_unavailable',[g['code'] for g in blocked['items'][0]['preview']['gaps']])

    def test_three_dimensional_reference_pins_real_export_camera_time_and_rejects_new_version(self):
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.spatial_scene import default_scene
        with tempfile.TemporaryDirectory() as directory:
            self.service.storage=LocalStorage(directory)
            doc=default_scene();doc.update(width=320,height=180)
            scene=self.write('create_spatial_scene',dict(mode='blocking',scene_id=self.objects['scene'],document=doc,title='合成三维站位'))
            exported=self.write('create_spatial_export',dict(spatial_scene_id=scene['id'],scene_revision=1,camera_id='camera-b',format='png',time=.25))
            complete=self.service.execute_spatial_export(self.p,exported['id']);self.rev=self.service.get_project(self.p)['revision'];self.assertEqual(complete['status'],'succeeded')
            media=complete['media_id'];self.write('record_media_check',dict(media_id=media,checker='synthetic-check',criteria_version='1',outcome='pass'))
            decision=self.select(self.candidate(self.objects['shot'],media))
            fixed=self.service.get_spatial_scene(self.p,scene['id'])['version_id'];state=self.detail()['state'];state['blocking_mode']='3d';unit=self.unit('bu','blocking');unit['spatial_version_id']=fixed;state['units']=[unit];state['media']=[dict(unit_key='bu',purpose='blocking',media_id=media,decision_id=decision['decision_id'],spatial_export_id=exported['id'])];self.save(state)
            reopened=self.detail();self.assertEqual(reopened['state']['media'][0]['spatial_export_id'],exported['id']);job=self.service.get_spatial_export(self.p,exported['id']);self.assertEqual(job['camera_key'],'camera-b');self.assertEqual(job['time_seconds'],.25)
            doc['objects'][1]['position']=[2,0,0];self.write('save_spatial_scene',dict(spatial_scene_id=scene['id'],scene_revision=1,title='新场景',document=doc));latest=self.service.get_spatial_scene(self.p,scene['id'])['version_id']
            state=self.detail()['state'];state['units'][0]['spatial_version_id']=latest
            with self.assertRaises(ResourceError):self.save(state)
            self.assertEqual(self.detail()['state']['units'][0]['spatial_version_id'],fixed)

    def test_http_original_workflow_reopen_and_same_save_request_replay(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app({'projects_root':directory+'/projects','media_root':directory,'access_token':'test-token','human_identity':'test-human','allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'background_enabled':False},service=self.service)) as client:
            session=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'});self.assertEqual(session.status_code,200,session.text)
            csrf=session.json()['csrf_token'];headers={'Origin':'http://testserver','X-CSRF-Token':csrf};url='/api/v1/projects/'+self.p
            data=client.get(url+'/intelligent-workflows/'+self.flow);self.assertEqual(data.status_code,200,data.text);current=data.json();state=current['state'];state['document']['notes']='HTTP持久正文';payload=dict(workflow_id=self.flow,base_version_id=current['version']['id'],state=state)
            impact=client.post(url+'/intelligent-change-preview',json={'payload':payload},headers=headers);self.assertEqual(impact.status_code,200,impact.text)
            body=dict(payload=dict(payload,impact_sha256=impact.json()['sha256']),expected_revision=current['revision'],idempotency_key='same-http-save')
            first=client.put(url+'/intelligent-workflows/'+self.flow,json=body,headers=headers);self.assertEqual(first.status_code,200,first.text);again=client.put(url+'/intelligent-workflows/'+self.flow,json=body,headers=headers);self.assertEqual(again.json(),first.json())
            reopened=client.get(url+'/intelligent-workflows/'+self.flow).json();self.assertEqual(reopened['state']['document']['notes'],'HTTP持久正文');self.assertEqual(reopened['version']['version'],2)

class SharedRolePlannerTests(unittest.TestCase):
    def test_shared_canvas_and_episode_transport_has_no_tools_and_keeps_timeout_unknown(self):
        import subprocess
        from types import SimpleNamespace
        from unittest.mock import patch
        from vsc.production.canvas_agent import GrokBuildCanvasAgent
        from vsc.production.intelligent_production import GrokBuildIntelligentPlanner
        commands=[]
        def runner(command,**kw):
            commands.append(command);schema=json.loads(command[-1]);result={'message':'合成文本','questions':[],'action':{'kind':'append_text','title':'草稿','text':'文字','source_node_id':''}} if 'action' in schema['required'] else proposal('assets')
            return SimpleNamespace(returncode=0,stdout=json.dumps({'structuredOutput':result}))
        with patch('vsc.production.role_planner._run_bounded',runner):
            first=GrokBuildCanvasAgent(runner=runner).generate({}, {}, '固定技能');second=GrokBuildIntelligentPlanner().generate({}, {}, '固定技能')
        self.assertEqual(first['action']['kind'],'append_text');self.assertTrue(second['assets']);self.assertEqual(len(commands),2)
        for command in commands:self.assertEqual(command[command.index('--tools')+1],'');self.assertIn('--no-subagents',command);self.assertIn('--disable-web-search',command)
        def timed_out(*args,**kw):raise subprocess.TimeoutExpired('grok',120)
        with self.assertRaises(ResourceError) as caught:GrokBuildCanvasAgent(runner=timed_out).generate({}, {}, '')
        self.assertEqual(caught.exception.code,'canvas_agent_submission_unknown')

@unittest.skipUnless(HAS_DB_DEPS and os.environ.get('VSC_TEST_DATABASE_URL'),'requires isolated PostgreSQL')
class IntelligentExecutionTests(ResourceStoreFixture,unittest.TestCase):
    detail=IntelligentProductionTests.detail
    task=IntelligentProductionTests.task
    confirm=IntelligentProductionTests.confirm
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.service.intelligent_planner=SyntheticPlanner();self.flow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='当前集缺图',script_text='合成测试'))['id']
    def test_current_batch_asset_runs_original_approval_and_task_center(self):
        from unittest.mock import patch
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        task=self.task();self.confirm(task);current=self.detail()
        center=self.service.get_task_center(self.p,kind='intelligent');item=next(r for r in center['items'] if r['id']==task['id']);self.assertIn('task_target='+self.flow,item['href']);self.assertIn('episode='+self.objects['episode'],item['href'])
        with self.engine.connect() as conn:artifacts=list(conn.execute(select(S.asset_spec_versions.c.artifact_id).where(S.asset_spec_versions.c.id.in_([a['spec_id'] for a in current['state']['assets']]))).scalars())
        for identifier in dict.fromkeys(artifacts):self.write('decide_artifact',dict(artifact_id=identifier,reason='合成工程批准固定资产规格'))
        future=self.write('create_object',dict(kind='asset',asset_kind='character',display_code='FUTURE_ONLY'))['id'];self.artifact('future','asset-bible',[future],{'asset_specs':[{'id':str(uuid.uuid4()),'asset_id':future,'variant_key':'master'}]})
        provider='synthetic_'+uuid.uuid4().hex;self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin');model=self.service.register_model(dict(provider_id=provider,model_key='offline-image',model_version='1',modality='image',capabilities={'purposes':['identity_ref']}),actor='test-admin')
        request=dict(workflow_id=self.flow,version_id=current['version']['id'],model_id=model['id'],execution_policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=3,max_repair_rounds=1))
        with patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':[dict(model,adapter_available=True,enabled=True)]}):
            preview=self.service.preview_intelligent_missing_assets(self.p,request);self.assertEqual(len(preview['items']),2);self.assertTrue(all(x['ready'] for x in preview['items']),preview)
            self.assertTrue(all(x['artifact']['object_ids']!=[future] for x in preview['items']))
            saved=self.write('propose_intelligent_missing_assets',dict(request=request,preview_sha256=preview['sha256']));self.assertEqual(len(saved['items']),2)
        result=self.service.advance_intelligent_runs(self.p,dict(workflow_id=self.flow,version_id=current['version']['id']),'test-human');self.assertTrue(all(x['status']=='needs_approval' for x in result['runs']));self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
    def test_recycled_episode_hides_current_drafts_keeps_fixed_versions(self):
        from vsc.assets.spatial_scene import default_scene
        canvas=self.write('create_creative_canvas',dict(episode_id=self.objects['episode'],document={'nodes':[],'edges':[]}));spatial=self.write('create_spatial_scene',dict(mode='blocking',scene_id=self.objects['scene'],document=default_scene()));version=self.detail()['version']['id']
        self.write('management_command',dict(operation='trash',target_type='object',target_id=self.objects['episode'],reason='合成工程回收'))
        self.assertEqual(self.service.list_creative_canvases(self.p)['items'],[]);self.assertEqual(self.service.list_spatial_scenes(self.p)['items'],[]);self.assertEqual(self.service.list_intelligent_workflows(self.p)['items'],[])
        for method,identifier in [('get_creative_canvas',canvas['id']),('get_spatial_scene',spatial['id']),('get_intelligent_workflow',self.flow)]:
            with self.assertRaises(ResourceError):getattr(self.service,method)(self.p,identifier)
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'],1)['canvas_revision'],1);self.assertEqual(self.service.get_spatial_scene(self.p,spatial['id'],1)['scene_revision'],1);self.assertEqual(self.service.get_intelligent_workflow(self.p,self.flow,version)['version']['id'],version)
