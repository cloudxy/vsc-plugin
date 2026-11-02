"""Original API sources and typed first-cut references in isolated PostgreSQL."""
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS,TEST_URL,ResourceStoreFixture
from vsc.assets.resource_service import Conflict,ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class EditorProfessionalTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.persistence.postgres.editor_workspace import EditorWorkspaceRepository
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-editor-professional-')
        self.addCleanup(self.temp.cleanup)
        self.service.storage=LocalStorage(Path(self.temp.name)/'storage')
        self.repo=EditorWorkspaceRepository(self.store)
        self.objects=self.hierarchy()

    def timed_media(self,name,modality,duration):
        if not shutil.which('ffmpeg'):self.skipTest('requires FFmpeg for real stored input')
        path=Path(self.temp.name)/(uuid.uuid4().hex+('.mp4' if modality=='video' else '.wav'))
        inputs=(['-f','lavfi','-i','color=blue:size=128x128:rate=24','-f','lavfi','-i','sine=frequency=220:sample_rate=48000',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac'] if modality=='video' else
            ['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-c:a','pcm_s16le'])
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y',*inputs,'-t',str(duration/1000),str(path)],
            check=True,capture_output=True,timeout=30)
        with path.open('rb') as stream:upload=self.service.storage.stage_upload(stream,path.name)
        media=self.write('register_media',dict(name=name,staged_upload=upload['staged_upload'],
            rights='owned',source={'kind':'test-owned','content':'real FFmpeg synthetic editor fixture'}))['id']
        self.write('record_media_check',dict(media_id=media,checker='fixture',criteria_version='1',outcome='pass'))
        return media

    def sources(self):
        from sqlalchemy import insert,select
        from vsc.adapters.persistence.postgres import schema as S
        video=self.timed_media('video','video',3000);audio=self.timed_media('music','audio',1500)
        choice=self.candidate(self.objects['shot'],audio,role='music',track_key='music');decision=self.select(choice)
        cue=self.write('create_artifact',dict(artifact_key='cue',artifact_type='creative-relations',object_ids=[self.objects['episode']],
            document={'format':'vsc.creative-relations/v1','project_id':self.p,'cues':[dict(key='music',kind='music',
                scope_object_id=self.objects['episode'],shots=[dict(shot_id=self.objects['shot'],start_ms=500,end_ms=2000)],
                slot_ids=[choice['slot_id']],parameters={'source_in_ms':0})]}))
        rules=self.write('create_artifact',dict(artifact_key='rules',artifact_type='creative-brief',object_ids=[self.objects['episode']],
            document={'creative_rules':{'subtitle':{'max_cps':{'value':4,'level':'warning'}}}}))
        lines=[dict(line_key='line-'+str(i),scene_id=self.objects['scene'],line_kind=kind,text=text) for i,(kind,text) in enumerate(
            [('dialogue','固定对白'),('narration','固定对白'),('action','动作无需强制字幕')])]
        script=self.write('create_artifact',dict(artifact_key='script',artifact_type='script',object_ids=[self.objects['episode']],
            document={'body':'未标注原稿不能推断字幕覆盖','script_lines':lines},script_lines=lines))
        pins=[dict(id=cue['id'],sha256=cue['sha256'],kind='sound_plan'),dict(id=rules['id'],sha256=rules['sha256'],kind='creative_rules'),
              dict(id=script['id'],sha256=script['sha256'],kind='screenplay')]
        draft=self.write('save_classic_draft',dict(base_draft_id=None,document=dict(shot_id=self.objects['shot'],mode='text',
            prompt='synthetic fixed source',references=[],professional_inputs=pins)))
        provider='editor-'+uuid.uuid4().hex;model=str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider,name='offline fixture',modality='video',base_url='https://example.invalid',auth_ref='none',enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model,provider_id=provider,model_key='offline',model_version='1',modality='video',capabilities={},default_params={},cost_rule={},enabled=True))
        def fixed_job(conn,project):
            artifact=self.store._create_artifact(conn,project,dict(artifact_key='run',artifact_type='workbench-generation-run',
                document={'workbench_draft':{'id':draft['id'],'sha256':draft['sha256']}},object_ids=[self.objects['shot']],dependency_ids=[draft['id']]))
            conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p,id=str(uuid.uuid4()),run_version_id=artifact['id'],
                shot_id=self.objects['shot'],draft_version_id=draft['id'],draft_sha256=draft['sha256'],output_kind='video'))
            job_id=str(uuid.uuid4())
            conn.execute(insert(S.generation_jobs).values(project_id=self.p,id=job_id,run_version_id=artifact['id'],shot_id=self.objects['shot'],
                purpose='video_clip',modality='video',candidate_no=0,provider_id=provider,model_id=model,model_version='1',request_payload={},
                request_sha256='0'*64,context_sha256='0'*64,idempotency_key=uuid.uuid4().hex,status='succeeded',attempt=0))
            conn.execute(insert(S.job_outputs).values(project_id=self.p,id=str(uuid.uuid4()),job_id=job_id,media_id=video,asset_type='video'))
            return {'id':job_id}
        result=self.store._mutate(self.p,'test_editor_source',{},expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human',callback=fixed_job)
        self.rev=result['revision']
        candidate=self.write('propose_binding',dict(target_object_id=self.objects['shot'],media_id=video,role='video_take',slot_key='workbench'))
        self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='video',candidate_id=candidate['candidate_id'],
            base_version_id=None,trim_in_ms=500,trim_out_ms=2500))
        with self.engine.connect() as conn:
            cue_id=conn.scalar(select(S.sound_cues.c.id).where(S.sound_cues.c.project_id==self.p,S.sound_cues.c.artifact_id==cue['id']))
        return dict(video=video,audio=audio,pins=pins,cue_id=cue_id,sound=cue,decision=decision)

    def test_seed_original_run_projects_cue_and_prepare_rechecks_rights(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        source=self.sources();seed=self.repo.seed(self.p,self.objects['episode']);doc=seed['document']
        self.assertEqual(doc['professional_inputs'],source['pins']);self.assertEqual(len(doc['audio']),1)
        self.assertEqual((doc['audio'][0]['in_frame'],doc['audio'][0]['out_frame'],doc['audio'][0]['at_frame']),(0,36,0))
        saved=self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=doc))
        with self.engine.connect() as conn:
            pins=conn.execute(select(S.edit_revision_professional_inputs).where(S.edit_revision_professional_inputs.c.project_id==self.p,
                S.edit_revision_professional_inputs.c.edit_version_id==saved['edit_version_id'])).mappings().all()
            members=conn.execute(select(S.edit_revision_media).where(S.edit_revision_media.c.project_id==self.p,
                S.edit_revision_media.c.edit_version_id==saved['edit_version_id'],S.edit_revision_media.c.track=='audio')).mappings().all()
        self.assertEqual(len(pins),3);self.assertEqual(members[0]['source_cue_id'],source['cue_id'])
        self.write('request_edit_export',dict(edit_version_id=saved['edit_version_id']))
        job=self.repo.claim('editor-professional',self.p)
        prepared=self.repo.prepare(job,'editor-professional')
        self.assertEqual(prepared['document'],doc);self.assertEqual(prepared['edit_sha256'],saved['sha256'])
        self.assertEqual(prepared['professional_context']['creative_rules']['subtitle']['max_cps']['value'],4)
        self.assertEqual(prepared['professional_context']['script_texts'],['固定对白','固定对白'])
        self.write('decide_rights',dict(media_id=source['audio'],outcome='revoked',reason='fixture source revocation'))
        with self.assertRaises(ResourceError) as error:self.repo.prepare(job,'editor-professional')
        self.assertEqual(error.exception.code,'edit_input_unusable')

    def test_wrong_sha_scope_cue_media_and_direct_projection_tamper_are_rejected(self):
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        source=self.sources();doc=self.repo.seed(self.p,self.objects['episode'])['document']
        wrong=copy.deepcopy(doc);wrong['professional_inputs'][0]['sha256']='f'*64
        with self.assertRaises(ResourceError):self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=wrong))
        wrong=copy.deepcopy(doc);wrong['audio'][0]['media_id']=self.timed_media('other audio','audio',1500)
        with self.assertRaises(ResourceError):self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=wrong))
        other=self.write('create_object',dict(kind='episode',parent_id=self.objects['work'],ordinal=1,display_code='OTHER'))['id']
        wrong=copy.deepcopy(doc);wrong['clips'][0].pop('shot_id');wrong['clips'][0].pop('working_selection_version_id')
        with self.assertRaises(ResourceError):self.write('save_edit_workspace',dict(episode_id=other,edit_revision=0,document=wrong))
        saved=self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=doc))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.edit_revision_professional_inputs).where(S.edit_revision_professional_inputs.c.project_id==self.p,
                S.edit_revision_professional_inputs.c.edit_version_id==saved['edit_version_id']).values(artifact_sha256='0'*64))

    def test_seed_save_request_share_outer_transaction_and_conflict_preserves_baseline(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        self.sources()
        def work(conn,project):
            doc=self.repo.seed(self.p,self.objects['episode'],_transaction=(conn,project))['document']
            kw=dict(expected_revision=project['revision'],idempotency_key='inside',actor='test-human',_transaction=(conn,project))
            saved=self.repo.save(self.p,dict(episode_id=self.objects['episode'],edit_revision=0,document=doc),**kw)
            self.repo.request(self.p,dict(edit_version_id=saved['edit_version_id']),**kw)
            raise ResourceError('synthetic rollback','test_rollback')
        with self.assertRaises(ResourceError):
            self.store._mutate(self.p,'test_outer_editor',{},expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human',callback=work)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.edit_workspaces).where(S.edit_workspaces.c.project_id==self.p)),0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==self.p)),0)
        doc=self.repo.seed(self.p,self.objects['episode'])['document']
        saved=self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=doc))
        with self.assertRaises(Conflict):self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,document=doc))
        self.assertEqual(self.service.get_edit_workspace(self.p,self.objects['episode'])['current']['id'],saved['edit_version_id'])

