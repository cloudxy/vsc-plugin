"""Canvas sequential source and editor origin checks over original PostgreSQL relations."""
import json,os,unittest,uuid
from copy import deepcopy
from unittest.mock import patch
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS


def action(kind,text='fixed',source='',ref=None):
    return dict(kind=kind,title='隔离节点',text=text,source_node_id=source,**({'source_action':ref} if ref else {}))


class PlanFixture:
    def __init__(self,value):self.value=value
    def available(self):return True
    def generate(self,*args):
        self.received=args
        return deepcopy(self.value)


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS,'requires isolated PostgreSQL')
class CanvasSourceHandoffTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy()
        provider='canvas_sources_'+uuid.uuid4().hex
        self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
        self.model=self.service.register_model(dict(provider_id=provider,model_key='source-video',model_version='1',modality='video',capabilities=dict(purposes=['text_to_video','image_to_video','reference_to_video','video_clip'],first_frame=True,reference_media=True)),actor='test-admin')
        mocked=patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':[dict(self.model,enabled=True,adapter_available=True)]});mocked.start();self.addCleanup(mocked.stop)
        self.policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=4,max_repair_rounds=0,authorization={'mode':'new_batch','reason':'isolated explicit task'})
        self.addCleanup(lambda:self.service.__dict__.pop('canvas_agent_backend',None))

    def canvas(self,nodes=None,episode=None):
        return self.write('create_creative_canvas',dict(episode_id=episode or self.objects['episode'],document={'nodes':nodes or [dict(id='original',type='text',text='最初输入')],'edges':[]}))
    def turn(self,canvas,actions):
        current=self.service.get_creative_canvas(self.p,canvas['id'])
        turn=self.write('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=current['canvas_revision'],skill_id='vsc-direct',message='固定隔离计划',node_ids=[n['id'] for n in current['document']['nodes']],model_ids=[self.model['id']],shot_id=self.objects['shot'],execution_settings={'execution_policy':self.policy}))
        self.service.canvas_agent_backend=PlanFixture(dict(message='固定计划',questions=[],actions=actions(turn['id']) if callable(actions) else actions))
        result=self.service.execute_canvas_agent_turn(self.p,turn['id']);self.rev=self.service.get_project(self.p)['revision'];self.assertEqual(result['status'],'planned',result)
        return turn
    def decide(self,turn,index,key=None,**extra):
        return self.write('decide_canvas_agent_turn',dict(turn_id=turn['id'],action_index=index,outcome='confirm',reason='隔离操作者确认当前动作',**extra),idempotency_key=key or uuid.uuid4().hex)

    def test_same_turn_text_and_media_edges_feed_fixed_drafts_and_replay_original_action(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        design='固定专业设计'+('完整动作与连续性。'*800)
        canvas=self.canvas()
        turn=self.turn(canvas,lambda id:[action('append_text',design),action('create_video_node','镜头请求',ref=dict(turn_id=id,action_index=0,node_type='text')),action('prepare_run')])
        packet,received,_=self.service.canvas_agent_backend.received
        manifest=json.loads(packet['parent_brief']['content'])['role_materials_manifest']
        self.assertEqual(received['_materials']['manifest'],manifest)
        self.assertTrue(any(item['kind']=='reference' and item['text'] for item in received['_materials']['materials']))
        first=self.decide(turn,0,key='first-action');rev=self.rev
        replay=self.service.decide_canvas_agent_turn(self.p,dict(turn_id=turn['id'],action_index=0,outcome='confirm',reason='隔离操作者确认当前动作'),actor='test-human',expected_revision=0,idempotency_key='first-action')
        self.assertEqual(replay,first)
        self.decide(turn,1);current=self.service.get_creative_canvas(self.p,canvas['id']);source='agent-'+turn['id']+'-0';target='agent-'+turn['id']+'-1'
        self.assertTrue(any(edge['source']==source and edge['target']==target and edge['port']=='prompt' for edge in current['document']['edges']))
        request=self.store.get_canvas_agent_run_request(self.p,turn['id'])
        draft=self.service.get_artifact_version(self.p,request['draft_version_id']);self.assertEqual(json.loads(draft['document'])['prompt'],design+'\n镜头请求')
        with self.engine.connect() as conn:
            binding=conn.execute(select(S.canvas_generation_inputs).where(S.canvas_generation_inputs.c.project_id==self.p,S.canvas_generation_inputs.c.draft_version_id==draft['id'])).mappings().one()
            self.assertEqual(binding['version_id'],current['version_id'])
        quote=self.service.preview_canvas_agent_run(self.p,turn['id']);self.assertTrue(quote['ready'],quote)
        last=self.decide(turn,2,key='original-job',preview_sha256=quote['preview_sha256'])
        repeated=self.service.decide_canvas_agent_turn(self.p,dict(turn_id=turn['id'],action_index=2,outcome='confirm',reason='隔离操作者确认当前动作',preview_sha256=quote['preview_sha256']),actor='test-human',expected_revision=0,idempotency_key='original-job')
        self.assertEqual(repeated,last)
        jobs=self.service.list_generation_jobs(self.p)['items'];self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['request_payload']['prompt'],design+'\n镜头请求')
        media=self.media('同轮复用图片');second=self.canvas([dict(id='ref',type='image',media_id=media)])
        media_turn=self.turn(second,lambda id:[action('reuse_media',source='ref'),action('create_video_node','引用图像',ref=dict(turn_id=id,action_index=0,node_type='image'))])
        self.decide(media_turn,0);self.decide(media_turn,1)
        saved=self.service.get_creative_canvas(self.p,second['id']);self.assertEqual(saved['document']['edges'][0]['port'],'first_frame')
        with self.engine.connect() as conn:
            binding=conn.execute(select(S.canvas_generation_inputs).where(S.canvas_generation_inputs.c.project_id==self.p,S.canvas_generation_inputs.c.version_id==saved['version_id'])).mappings().one()
        fixed=json.loads(self.service.get_artifact_version(self.p,binding['draft_version_id'])['document'])
        self.assertEqual(fixed['references'][0]['media_id'],media)

    def test_missing_failed_or_changed_action_source_cannot_create_another_node(self):
        from vsc.assets.resource_service import ResourceError,Conflict
        canvas=self.canvas();turn=self.turn(canvas,lambda id:[action('create_video_node','空生成器'),action('create_video_node','不允许空引用',ref=dict(turn_id=id,action_index=0,node_type='video'))])
        self.decide(turn,0);before=self.service.get_creative_canvas(self.p,canvas['id'])
        with self.assertRaises(ResourceError) as caught:self.decide(turn,1)
        self.assertEqual(caught.exception.code,'canvas_plan_source_unavailable')
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['version_id'],before['version_id'])
        with self.engine.connect() as conn:
            original=self.store._canvas_agent_turn(conn,self.store._project(conn,self.p),turn['id'])
            with self.assertRaises(ResourceError):self.store._canvas_action_source(conn,self.p,original,original['plan']['actions'][1],[],before['document'])
            failed=[dict(turn_id=turn['id'],ordinal=0,output_version_id=None)]
            with self.assertRaises(ResourceError):self.store._canvas_action_source(conn,self.p,original,original['plan']['actions'][1],failed,before['document'])
        changed=deepcopy(before['document']);changed['nodes'][-1]['text']='他人修改'
        self.write('save_creative_canvas',dict(canvas_id=canvas['id'],canvas_revision=before['canvas_revision'],document=changed))
        with self.assertRaises(Conflict):self.decide(turn,1)

    def test_changed_pinned_materials_stop_before_host_and_retain_original_turn(self):
        from pathlib import Path
        import tempfile
        from vsc.bootstrap import repository_root
        canvas=self.canvas()
        turn=self.write('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=canvas['canvas_revision'],skill_id='vsc-direct',message='固定材料检查',node_ids=['original']))
        packet=self.service.get_role_dispatch(self.p,turn['dispatch_id'])['packet']
        manifest=json.loads(packet['parent_brief']['content'])['role_materials_manifest']
        backend=PlanFixture(dict(message='should not call',questions=[],actions=[action('none')]))
        self.service.canvas_agent_backend=backend
        with tempfile.TemporaryDirectory(prefix='vsc-canvas-materials-') as directory:
            root=Path(directory)
            for entry in manifest['entries']:
                target=root/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((repository_root()/entry['path']).read_bytes())
            target=root/next(entry['path'] for entry in manifest['entries'] if entry['kind']=='reference')
            target.write_text(target.read_text()+'\nChanged after original turn.\n')
            with patch('vsc.production.role_materials.repository_root',return_value=root):
                result=self.service.execute_canvas_agent_turn(self.p,turn['id'])
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'role_materials_changed')
        self.assertFalse(hasattr(backend,'received'))
        recovered=self.service.execute_canvas_agent_turn(self.p,turn['id'])
        self.assertEqual(recovered['id'],turn['id']);self.assertEqual(recovered['status'],'failed')
        self.assertFalse(hasattr(backend,'received'))
        self.assertEqual(self.service.get_role_dispatch(self.p,turn['dispatch_id'])['packet'],packet)

    def generated_video(self,shot=None,media=None):
        shot=shot or self.objects['shot']
        draft=self.write('save_classic_draft',dict(base_draft_id=None,document=dict(shot_id=shot,mode='text',model_id=self.model['id'],purpose='text_to_video',prompt='隔离视频',duration_ms=5000,count=1,references=[])))
        request=dict(draft_version_id=draft['id'],execution_policy=self.policy)
        quote=self.service.preview_workbench_generation(self.p,request)
        result=self.write('generate_workbench',dict(request=request,preview_sha256=quote['preview_sha256']))
        self.write('configure_budget',dict(limits={'remote_jobs':10,'video_seconds':50},reason='isolated output facts'))
        job=result['jobs'][0]['id'];self.write('update_generation_job',dict(job_id=job,status='submitted',external_task_id='isolated-'+job))
        if media is None:
            media=self.write('register_media',dict(name='原任务输出',modality='video',sha256=uuid.uuid4().hex*2,size_bytes=10,mime_type='video/mp4',duration_ms=5000,width=720,height=1280,storage='local',object_key=uuid.uuid4().hex+'.mp4',rights='owned',source={'kind':'synthetic-generation','content':'隔离任务输出'}))['id']
            self.write('record_media_check',dict(media_id=media,checker='fixture',criteria_version='1',outcome='pass'))
        self.write('update_generation_job',dict(job_id=job,status='succeeded',outputs=[{'media_id':media}]))
        return job,media

    def test_canvas_edit_keeps_shot_selection_trim_and_allows_formal_handoff_after_real_adoption(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        job,media=self.generated_video()
        working=self.service.list_working_selections(self.p,shot_id=self.objects['shot'])['items'][0]
        selection=self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='video',candidate_id=working['candidate_id'],base_version_id=working['id'],event_kind='trim',trim_in_ms=500,trim_out_ms=4500))
        canvas=self.canvas([dict(id='output',type='video',media_id=media,job_id=job)])
        added=self.write('canvas_node_to_edit',dict(canvas_id=canvas['id'],canvas_revision=canvas['canvas_revision'],node_id='output',edit_revision=0))
        workspace=self.service.get_edit_workspace(self.p,self.objects['episode']);clip=workspace['current']['document']['clips'][0]
        self.assertEqual((clip['shot_id'],clip['working_selection_version_id'],clip['in_frame'],clip['out_frame']),(self.objects['shot'],selection['id'],12,108))
        with self.engine.connect() as conn:
            member=conn.execute(select(S.edit_revision_media).where(S.edit_revision_media.c.project_id==self.p,S.edit_revision_media.c.edit_version_id==added['edit_version_id'])).mappings().one();self.assertEqual(member['shot_id'],self.objects['shot'])
            pin=conn.execute(select(S.edit_revision_working_selections).where(S.edit_revision_working_selections.c.project_id==self.p,S.edit_revision_working_selections.c.edit_version_id==added['edit_version_id'])).mappings().one();self.assertEqual(pin['selection_version_id'],selection['id'])
        # The user explicitly mutes this working cut; audible clips still require a sound cue.
        muted=deepcopy(workspace['current']['document']);muted['clips'][0]['muted']=True
        fixed=self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=workspace['workspace']['revision'],document=muted))
        clip=muted['clips'][0]
        adopted=self.select(self.candidate(self.objects['shot'],media,role='video_take'))
        origin=self.artifact('owned-video','source-evidence',[self.objects['shot']]);sha=self.service.get_artifact_version(self.p,origin)['sha256']
        selected=self.write('create_artifact',dict(artifact_key='formal-choice',artifact_type='vsc.selected_takes',object_ids=[self.objects['episode']],dependency_ids=[origin],document=dict(format='vsc.selected-takes/v1',project_id=self.p,scope=self.objects['episode'],items=[dict(id='chosen',shot_id=self.objects['shot'],take_id='take',output_id='out',scope=self.objects['episode'],purpose='visual',usage_rights='owned',selected_by='test-human',media={'path':'media/isolated.mp4','sha256':self.service.get_media(self.p,media)['sha256']},source={'kind':'manual','artifact':{'id':origin,'sha256':sha},'imported_by':'test-human','provenance':'isolated known task output'})])))
        self.write('decide_artifact',dict(artifact_id=selected['id'],reason='隔离操作者确认选片'))
        request=dict(edit_version_id=fixed['edit_version_id'],selected_takes_id=selected['id'],assignments={clip['id']:dict(selected_item_id='chosen',binding_decision_id=adopted['decision_id'],audio_role='none')})
        preview=self.service.preview_edit_timeline(self.p,request);self.assertTrue(preview['needs_approval'])
        proposed=self.write('propose_edit_timeline',dict(request=request,preview_sha256=preview['preview_sha256']))
        with self.assertRaises(ResourceError):self.write('freeze_edit_timeline',dict(artifact_id=proposed['artifact_id']))
        self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='video',candidate_id=None,base_version_id=selection['id']))
        self.assertEqual(self.service.get_edit_workspace(self.p,self.objects['episode'])['current']['document']['clips'][0],clip)

    def test_cross_episode_and_ambiguous_origins_reject_while_legacy_unmapped_clip_stays_previewable(self):
        from vsc.assets.resource_service import ResourceError
        job,media=self.generated_video()
        episode=self.write('create_object',dict(kind='episode',parent_id=self.objects['work'],display_code='OTHER',ordinal=1))['id'];parent=episode
        for kind in ['scene','sequence','shot']:parent=self.write('create_object',dict(kind=kind,parent_id=parent,display_code='OTHER-'+kind,ordinal=0))['id']
        with self.assertRaises(ResourceError) as error:self.canvas([dict(id='cross',type='video',media_id=media,job_id=job)],episode=episode)
        self.assertEqual(error.exception.code,'canvas_job_scope')
        wrong=self.canvas([dict(id='cross',type='video',media_id=media)],episode=episode)
        with self.assertRaises(ResourceError) as error:self.write('canvas_node_to_edit',dict(canvas_id=wrong['id'],canvas_revision=wrong['canvas_revision'],node_id='cross',edit_revision=0))
        self.assertEqual(error.exception.code,'canvas_edit_episode_mismatch')
        self.generated_video(shot=parent,media=media)
        ambiguous=self.canvas([dict(id='shared',type='video',media_id=media)])
        with self.assertRaises(ResourceError) as error:self.write('canvas_node_to_edit',dict(canvas_id=ambiguous['id'],canvas_revision=ambiguous['canvas_revision'],node_id='shared',edit_revision=0))
        self.assertEqual(error.exception.code,'canvas_edit_shot_ambiguous')
        legacy=self.media('手工导入视频',modality='video');old=self.canvas([dict(id='legacy',type='video',media_id=legacy)])
        added=self.write('canvas_node_to_edit',dict(canvas_id=old['id'],canvas_revision=old['canvas_revision'],node_id='legacy',edit_revision=0))
        doc=self.service.get_edit_workspace(self.p,self.objects['episode'])['current']['document']
        self.assertNotIn('shot_id',doc['clips'][0]);self.assertEqual(doc['clips'][0]['media_id'],legacy)
        from vsc.post.edit_workspace import validate_edit
        validate_edit(doc)
