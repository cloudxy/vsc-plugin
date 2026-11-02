"""Episode candidate gallery consumes original media, jobs and working trims."""
import hashlib
import unittest
import uuid
import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class EditorCandidateTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy()

    def video(self,name):
        sha=hashlib.sha256(name.encode()).hexdigest()
        return self.write('register_media',dict(name=name,modality='video',sha256=sha,size_bytes=10,mime_type='video/mp4',storage='local',object_key=sha+'.mp4',duration_ms=7000,rights='owned',source={'kind':'test-owned','content':'synthetic candidate query'}))['id']

    def bind(self,shot,media):return self.write('propose_binding',dict(target_object_id=shot,media_id=media,role='video_take',slot_key='main'))['candidate_id']

    def test_same_episode_all_video_candidates_paginate_and_preserve_selection_trim_on_edit(self):
        shot=self.objects['shot'];a,b,c=(self.video(name) for name in ('selected','unselected','second shot'))
        selected=self.bind(shot,a);self.bind(shot,b)
        second=self.write('create_object',dict(kind='shot',parent_id=self.objects['sequence'],ordinal=1,display_code='SHOT-2',title='第二镜'))['id'];self.bind(second,c)
        png=self.media('只应出现在图像集合');self.write('propose_binding',dict(target_object_id=shot,media_id=png,role='first_frame'))
        choice=self.write('save_working_selection',dict(shot_id=shot,output_kind='video',candidate_id=selected,base_version_id=None,trim_in_ms=1000,trim_out_ms=5000))
        first=self.service.list_edit_candidates(self.p,self.objects['episode'],limit=2);self.assertEqual(first['total'],3);self.assertEqual(first['next_offset'],2)
        self.assertEqual({r['media_id'] for r in first['items']},{a,b});self.assertTrue(all(r['modality']=='video' and r['shot_number']==1 for r in first['items']))
        page=self.service.list_edit_candidates(self.p,self.objects['episode'],offset=2,limit=2);self.assertEqual([r['media_id'] for r in page['items']],[c]);self.assertEqual(page['items'][0]['shot_number'],2);self.assertIsNone(page['next_offset'])
        by_id={r['media_id']:r for r in first['items']};self.assertEqual((by_id[a]['trim_in_ms'],by_id[a]['trim_out_ms'],by_id[a]['working_selection_version_id']),(1000,5000,choice['id']))
        self.assertFalse(by_id[b]['selected']);self.assertEqual(by_id[b]['trim_out_ms'],7000);self.assertIsNone(by_id[b]['working_selection_version_id'])
        document=dict(format='vsc.edit-workspace/v1',width=720,height=1280,fps=24,clips=[dict(id='selected',shot_id=shot,media_id=a,in_frame=24,out_frame=120,working_selection_version_id=choice['id']),dict(id='unselected',shot_id=shot,media_id=b,in_frame=0,out_frame=168)],audio=[],captions=[])
        self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=document))
        self.write('save_working_selection',dict(shot_id=shot,output_kind='video',candidate_id=None,base_version_id=choice['id']))
        read=self.service.get_edit_workspace(self.p,self.objects['episode'])['current']['document'];self.assertEqual(read['clips'],document['clips'])
        with self.assertRaises(ResourceError):self.service.list_edit_candidates(self.p,self.objects['episode'],limit=101)

    def test_depth_and_other_episode_outputs_do_not_enter_gallery(self):
        shot=self.objects['shot'];self.artifact(objects=[shot]);self.artifact('state','scene-state',[self.objects['scene']],{'state_versions':[{'scene_id':self.objects['scene']}]})
        image=self.media('depth first frame');self.select(self.candidate(shot,image))
        provider='synthetic_editor_'+uuid.uuid4().hex;self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
        model=self.service.register_model(dict(provider_id=provider,model_key='depth-fixture',model_version='1',modality='video',capabilities={'purposes':['depth'],'first_frame':True}),actor='test-admin')
        request={'prompt':'synthetic depth intermediate','params':{},'first_frame_media_id':image,'duration_ms':5000}
        run=self.production_run(shot,request,purpose='depth');context=self.service.compile_shot_context(self.p,shot,purpose='depth')
        job=self.write('create_generation_job',dict(run_version_id=run,shot_id=shot,purpose='depth',modality='video',model_id=model['id'],context_sha256=context['sha256'],request_payload=request))
        self.write('update_generation_job',dict(job_id=job['id'],status='submitted',external_task_id='synthetic-depth-task'))
        depth=self.video('depth intermediate');self.write('update_generation_job',dict(job_id=job['id'],status='succeeded',outputs=[{'media_id':depth}]))
        self.bind(shot,depth)
        episode=self.write('create_object',dict(kind='episode',parent_id=self.objects['work'],ordinal=1,display_code='EP-2'))['id'];parent=episode
        for kind in ('scene','sequence','shot'):parent=self.write('create_object',dict(kind=kind,parent_id=parent,ordinal=0,display_code=kind+'-other'))['id']
        other=self.video('other episode');self.bind(parent,other)
        self.assertEqual(self.service.list_edit_candidates(self.p,self.objects['episode'])['total'],0)
        self.assertEqual([r['media_id'] for r in self.service.list_edit_candidates(self.p,episode)['items']],[other])
        another=self.service.create_project({'name':'isolated other project','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
        with self.assertRaises(ResourceError):self.service.list_edit_candidates(another['id'],self.objects['episode'])
