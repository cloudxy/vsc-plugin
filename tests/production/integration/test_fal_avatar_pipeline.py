"""Original quote/worker/PG paths with decoded synthetic subjects; no live service."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import wave
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image, ImageDraw

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.adapters.storage.local.store import LocalStorage
from vsc.adapters.providers.fal_avatar import fal_avatar_factory
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import PRESETS, ResourceSettings
from vsc.production.resource_worker import ResourceWorker


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS and shutil.which('ffmpeg'), 'requires isolated PostgreSQL and media decoding')
class FalAvatarPipelineTests(ResourceStoreFixture, unittest.TestCase):
    def write(self, method, payload, **kw):
        self.rev = self.service.get_project(self.p)['revision']
        return super().write(method, payload, **kw)

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-avatar-pg-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.service.storage = LocalStorage(self.root / 'media')
        self.objects = self.hierarchy(); self.models = {}
        for name in ('fal-subject-detect', 'fal-digital-human'):
            preset = next(row for row in PRESETS if row['id'] == name)
            self.models[name] = ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':10,'images':10,'video_seconds':20},reason='Controlled subject test only'))
        def png(image):
            stream=io.BytesIO(); image.save(stream,format='PNG'); return stream.getvalue()
        self.bytes={}
        self.bytes['source']=png(Image.new('RGB',(80,60),(50,80,100)))
        self.bytes['other']=png(Image.new('RGB',(80,60),(80,100,50)))
        for index,bounds in enumerate([(5,10,30,50),(45,10,70,50)]):
            image=Image.new('L',(80,60),0); ImageDraw.Draw(image).rectangle(bounds,fill=255); self.bytes['mask'+str(index)]=png(image)
        sound=io.BytesIO()
        with wave.open(sound,'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000); stream.writeframes(b'\0\0'*9600)
        self.bytes['audio']=sound.getvalue()
        path=self.root/'avatar.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=blue:size=1280x720:rate=10',
            '-f','lavfi','-i','anullsrc=r=8000:cl=mono','-t','1.2','-c:v','libx264','-preset','ultrafast',
            '-pix_fmt','yuv420p','-c:a','aac',str(path)],check=True,capture_output=True,timeout=30)
        self.bytes['avatar']=path.read_bytes()
        self.source=self.upload('source.png',self.bytes['source']); self.other=self.upload('other.png',self.bytes['other'])
        self.audio=self.upload('speech.wav',self.bytes['audio']); self.calls=[]; self.requests={}

    def upload(self,name,content):
        staged=self.service.storage.stage_upload(io.BytesIO(content),name)
        return self.write('register_media',dict(name=name,staged_upload=staged['staged_upload'],rights='unknown',source={'kind':'synthetic','content':'controlled two subjects, no real likeness'}))

    def policy(self):
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),
            stop_submitting_at=(now+timedelta(minutes=20)).isoformat(),max_attempts_per_purpose=1,max_repair_rounds=0,
            authorization={'mode':'new_batch','reason':'controlled subject verification'})

    def worker(self,empty=False):
        def transport(request):
            self.calls.append((request.method,str(request.url),json.loads(request.content) if request.content else None))
            if request.method=='POST':
                task=uuid.uuid4().hex; model=request.url.path.strip('/'); self.requests[task]=model; app='/'.join(model.split('/')[:2])
                return httpx.Response(200,json={'request_id':task,'status':'IN_QUEUE',**{k:'https://queue.fal.run/'+app+'/requests/'+task+suffix for k,suffix in [('response_url',''),('status_url','/status'),('cancel_url','/cancel')]}})
            task=request.url.path.split('/requests/')[1].split('/')[0]
            if request.url.path.endswith('/status'):return httpx.Response(200,json={'request_id':task,'status':'COMPLETED'})
            if self.requests[task].endswith('/image'):
                return httpx.Response(200,json={'masks':[] if empty else [{'url':'https://controlled.invalid/mask0'},{'url':'https://controlled.invalid/mask1'}], 'metadata':[]})
            return httpx.Response(200,json={'video':{'url':'https://controlled.invalid/avatar'},'duration':1.2})
        client=httpx.Client(transport=httpx.MockTransport(transport)); self.addCleanup(client.close)
        return ResourceWorker(self.service,lambda job,storage:fal_avatar_factory(job,storage,client=client,read_key=lambda:'mock-only'),download=lambda url,path:path.write_bytes(self.bytes[url.rsplit('/',1)[-1]]))

    def submit(self,document,base=None):
        draft=self.write('save_classic_draft',dict(document=document,base_draft_id=base))
        request={'draft_version_id':draft['id'],'execution_policy':self.policy()}
        preview=self.service.preview_classic_run(self.p,request,working=True); self.assertTrue(preview['ready'],preview)
        run=self.write('generate_workbench',{'request':request,'preview_sha256':preview['preview_sha256']})
        return draft,preview,run

    def detect(self,empty=False,expect_reserved=False):
        doc=dict(shot_id=self.objects['shot'],mode='image_subject_detect',purpose='image_edit',model_id=self.models['fal-subject-detect'],
            prompt='person',references=[{'role':'operation_source','media_id':self.source['id']}],params={'max_masks':6})
        draft,quote,run=self.submit(doc); self.assertEqual(quote['generation_quote']['native_units'],{'remote_jobs':1,'images':1})
        worker=self.worker(empty); worker.run_once(self.p)
        if expect_reserved:
            # mark_submission_started reserves before POST; merely creating a
            # job does not reserve. The async response has not been polled yet.
            self.assertEqual(self.service.get_generation_job(self.p,run['jobs'][0]['id'])['status'],'submitted')
            status=self.service.budget_status(self.p)
            self.assertEqual(status['used'],{'remote_jobs':1,'images':1})
            self.assertEqual({row['unit']:row['status'] for row in status['bounded_reservations']},
                {'remote_jobs':'reserved','images':'reserved'})
        worker.run_once(self.p,poll=True)
        return self.service.get_generation_job(self.p,run['jobs'][0]['id'])

    def avatar_document(self,choice):
        return dict(shot_id=self.objects['shot'],mode='digital_human',purpose='digital_human',model_id=self.models['fal-digital-human'],
            prompt='',performance_prompt='选定人物平静讲话。',subject_selection=choice,params={'resolution':'720p','turbo_mode':False},
            references=[{'role':'portrait','media_id':self.source['id']},{'role':'subject_mask','media_id':choice['mask_media_id']},
                        {'role':'speech','media_id':self.audio['id']}])

    def test_detect_choose_second_save_refresh_quote_original_worker_and_video_download(self):
        cards=self.service.list_asset_cards(self.p)['total']; job=self.detect(); self.assertEqual(job['status'],'succeeded')
        options=self.service.classic_production_options(self.p,self.objects['shot']); choices=options['subject_candidates']
        self.assertEqual(len(choices),2); choice=next(row for row in choices if row['output_index']==1)
        self.assertEqual(self.service.list_asset_cards(self.p)['total'],cards)
        self.assertEqual(self.service.list_working_candidates(self.p,self.objects['shot'],'image')['total'],0)
        doc=self.avatar_document(choice); saved=self.write('save_classic_draft',dict(document=doc,base_draft_id=None))
        refreshed=self.service.classic_production_options(self.p,self.objects['shot'])
        fixed=next(row for row in refreshed['drafts'] if row['document']['mode']=='digital_human')
        self.assertEqual(fixed['document']['subject_selection'],choice)
        draft,preview,run=self.submit(fixed['document'],base=saved['id'])
        self.assertEqual(preview['generation_quote']['native_units'],{'remote_jobs':1,'video_seconds':2})
        final=self.service.get_generation_job(self.p,run['jobs'][0]['id'])
        self.assertEqual(final['request_payload']['duration_ms'],1200)
        self.assertEqual(final['request_payload']['subject_mask_media_id'],choice['mask_media_id'])
        self.assertEqual({r['role'] for r in final['input_media']},{'portrait','speech','subject_mask'})
        worker=self.worker(); worker.run_once(self.p); worker.run_once(self.p,poll=True)
        final=self.service.get_generation_job(self.p,final['id']); self.assertEqual(final['status'],'succeeded')
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='controlled',human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            response=client.post('/api/v1/session',json={'token':'controlled'},headers={'Origin':'http://testserver'}); self.assertEqual(response.status_code,200)
            content=client.get('/api/v1/projects/'+self.p+'/media/'+final['outputs'][0]['media_id']+'/content?download=true')
            self.assertEqual(content.status_code,200); self.assertEqual(content.content,self.bytes['avatar'])
        self.assertEqual(sum(method=='POST' for method,_,_ in self.calls),2)
        import base64
        body=next(body for method,url,body in self.calls if method=='POST' and 'omnihuman' in url)
        self.assertEqual(base64.b64decode(body['mask_url'].split(',')[1]),self.bytes['mask1'])

    def test_changed_portrait_foreign_job_output_index_and_mask_bytes_are_rejected(self):
        self.detect(); choice=self.service.classic_production_options(self.p,self.objects['shot'])['subject_candidates'][1]
        doc=self.avatar_document(choice)
        changed={**doc,'references':[{**r,'media_id':self.other['id']} if r['role']=='portrait' else r for r in doc['references']]}
        with self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document=changed,base_draft_id=None))
        with self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document={**doc,'subject_selection':{**choice,'output_index':0}},base_draft_id=None))
        other=self.service.create_project({'name':'isolated other subject project','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
        from vsc.adapters.persistence.postgres.workbench_generation import subject_sources
        fixed_document=self.service._classic_document(self.p,doc)
        with self.store.engine.connect() as conn, self.assertRaises(ResourceError):subject_sources(self.store,conn,other['id'],fixed_document)
        # Selected image must still be the original black/white region, not an arbitrary uploaded image.
        bad={**choice,'mask_media_id':self.other['id'],'mask_sha256':self.other['sha256']}
        with self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document=self.avatar_document(bad),base_draft_id=None))

    def test_manual_mask_uses_original_export_and_keeps_independent_performance(self):
        edit=self.write('save_classic_reference_edit',dict(shot_id=self.objects['shot'],mode='digital_human',base_edit_id=None,
            document=dict(id=uuid.uuid4().hex,source_media_id=self.source['id'],source_sha256=self.source['sha256'],source_modality='image',
                time_ms=0,width=80,height=60,description='right person',operations=[dict(id='right',tool='mask',points=[[.7,.5]],color='#ffffff',width=.1)])))
        output=self.write('export_classic_reference_edit',dict(edit_version_id=edit['id'])); mask=next(row for row in output['outputs'] if row['role']=='mask')
        choice=dict(origin='manual',source_media_id=self.source['id'],source_sha256=self.source['sha256'],mask_media_id=mask['media_id'],mask_sha256=mask['sha256'],export_id=output['id'])
        draft,preview,run=self.submit(self.avatar_document(choice))
        request=preview['artifact']['document']['series_batch']['jobs'][0]['request']
        self.assertEqual(request['prompt'],'选定人物平静讲话。'); self.assertEqual(request['duration_ms'],1200)
        transparent=next(row for row in output['outputs'] if row['role']=='inpaint-mask')
        wrong={**choice,'mask_media_id':transparent['media_id'],'mask_sha256':transparent['sha256']}
        with self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document=self.avatar_document(wrong),base_draft_id=draft['id']))

    def test_no_subject_is_local_terminal_failure_preserves_provider_completion_and_budget(self):
        # Legacy synthetic projects intentionally have no budget reservations.
        # Exercise the actual production budget contract in this accounting case.
        self.project=self.service.create_project({'name':'受预算约束的空主体测试','profile_snapshot':{
            'profile_id':'vsc.synthetic','version':'1','stages':[],'contract_policy':'production-v2'}},actor='test-human')
        self.p=self.project['id']; self.rev=0; self.objects=self.hierarchy()
        self.source=self.upload('source.png',self.bytes['source'])
        self.write('configure_budget',dict(limits={'remote_jobs':1,'images':1},reason='Controlled empty subject accounting'))
        job=self.detect(empty=True,expect_reserved=True); self.assertEqual(job['status'],'failed'); self.assertEqual(job['raw_response']['status'],'COMPLETED')
        evidence=next(row['evidence'] for row in job['events'] if row['event_type']=='failed')
        self.assertEqual(evidence['error_code'],'subject_not_found'); self.assertFalse(evidence['remote_failed'])
        self.assertFalse(job['outputs']); self.assertFalse(self.service.classic_production_options(self.p,self.objects['shot'])['subject_candidates'])
        worker=self.worker(); worker.run_once(self.p); worker.run_once(self.p,poll=True)
        self.assertEqual(sum(method=='POST' for method,_,_ in self.calls),1)
        status=self.service.budget_status(self.p)
        self.assertEqual(status['used']['remote_jobs'],1); self.assertEqual(status['used']['images'],1)
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.store.engine.connect() as conn:
            actual={row['unit']:(row['actual'],row['status']) for row in conn.execute(select(S.job_budget_reservations.c.unit,S.job_budget_reservations.c.actual,S.job_budget_reservations.c.status)
                .where(S.job_budget_reservations.c.project_id==self.p,S.job_budget_reservations.c.job_id==job['id'])).mappings()}
        self.assertEqual(actual,{'remote_jobs':(1,'settled'),'images':(1,'settled')})
