"""Isolated PG + original native adapter/worker with decoded local videos."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError
from vsc.production.video_samples import UPGRADE_PROMPT


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class VideoSamplesTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_settings import PRESETS,ResourceSettings
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-video-samples-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service.storage=LocalStorage(self.root/'media');self.objects=self.hierarchy()
        preset=next(p for p in PRESETS if p['id']=='volcengine-native-sample');self.assertFalse(preset['enabled'])
        self.preset={k:v for k,v in preset.items() if k not in {'id','label'}}
        self.account=ResourceSettings(self.store).save(dict(self.preset,enabled=True),'test-human')
        self.model_ids={}
        for resolution,price in [('480p','0.1'),('1080p','0.3')]:
            caps=deepcopy(self.account['capabilities'])
            if resolution=='1080p':caps.update(purposes=['video_upgrade'],video_operations=['draft_upgrade'])
            self.model_ids[resolution]=self.store.register_model(dict(provider_id=self.account['provider_id'],model_key=self.account['model_key'],model_version='synthetic-'+resolution,modality='video',capabilities=caps,default_params=dict(self.account['default_params'],resolution=resolution),
                cost_rule={'unit':'video_seconds','unit_price':price,'currency':'CNY','basis':'cash','source_url':'https://example.test/synthetic-only-price','source_date':'2026-10-01'},enabled=True),actor='test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':8,'video_seconds':40},reason='isolated native sample test'))
        self.videos={}
        for resolution,size in [('480p','854x480'),('1080p','1920x1080')]:
            path=self.root/(resolution+'.mp4')
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=navy:s='+size+':r=10','-t','5','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True)
            self.videos[resolution]=path.read_bytes()
        self.posts=[];self.tasks={};self.created=datetime.now(timezone.utc)-timedelta(minutes=1)

    def policy(self):
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=3,max_repair_rounds=0,authorization={'mode':'new_batch','reason':'isolated sample verification'})

    def sample_document(self):
        return dict(shot_id=self.objects['shot'],mode='text',model_id=self.model_ids['480p'],purpose='text_to_video',prompt='蓝色背景中一只纸船轻轻移动',draft=True,duration_ms=5000,count=1,params={},references=[])

    def queue(self,document):
        drafts=self.service.classic_production_options(self.p,self.objects['shot'])['drafts']
        old=next((row for row in drafts if row['document']['mode']==document['mode']),None)
        saved=self.write('save_classic_draft',dict(document=document,base_draft_id=old['id'] if old else None))
        request=dict(draft_version_id=saved['id'],execution_policy=self.policy())
        preview=self.service.preview_workbench_generation(self.p,request);self.assertTrue(preview['ready'],preview)
        result=self.write('generate_workbench',dict(request=request,preview_sha256=preview['preview_sha256']))
        return result,preview

    def worker(self,unknown=False):
        import httpx
        from vsc.adapters.providers.volc_ark.resource_factory import volc_ark_factory
        from vsc.adapters.providers.credentials import PLAN_BASE
        from vsc.production.resource_worker import ResourceWorker
        def handler(request):
            if request.method=='POST':
                payload=json.loads(request.content);self.posts.append(payload)
                if unknown:raise httpx.ReadTimeout('synthetic lost response',request=request)
                task='cgt-'+str(len(self.posts));self.tasks[task]=payload;return httpx.Response(200,json={'id':task})
            task=request.url.path.rsplit('/',1)[-1];payload=self.tasks[task];resolution=payload['resolution']
            return httpx.Response(200,json={'id':task,'status':'succeeded','model':self.account['model_key'],'resolution':resolution,'draft':payload.get('draft',False),'created_at':int(self.created.timestamp()),'content':{'video_url':'https://example.test/'+resolution+'.mp4'}})
        client=httpx.Client(transport=httpx.MockTransport(handler));self.addCleanup(client.close)
        def transport(path,payload=None):return client.request('POST' if payload is not None else 'GET',PLAN_BASE+path,json=payload).json()
        mocked=patch('vsc.adapters.providers.volc_ark.provider.volc_ark.call',side_effect=transport);mocked.start();self.addCleanup(mocked.stop)
        return ResourceWorker(self.service,volc_ark_factory,download=lambda url,path:path.write_bytes(self.videos[url.rsplit('/',1)[-1][:-4]]))

    def complete_sample(self):
        run,preview=self.queue(self.sample_document());worker=self.worker();worker.run_once(self.p);worker.run_once(self.p,poll=True)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'succeeded',job)
        self.rev=self.service.get_project(self.p)['revision']
        media=self.service.get_media(self.p,job['outputs'][0]['media_id'])
        return job,media,worker,preview

    def upgrade_document(self,media):
        return dict(shot_id=self.objects['shot'],mode='video_upgrade',model_id=self.model_ids['1080p'],purpose='video_upgrade',prompt=UPGRADE_PROMPT,duration_ms=media['duration_ms'],count=1,params={},references=[dict(role='operation_source',media_id=media['id'],sha256=media['sha256'])])

    def test_native_draft_quote_worker_upgrade_keeps_original_and_typed_inputs(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        sample,media,worker,first_preview=self.complete_sample()
        self.assertIs(self.posts[0]['draft'],True);self.assertEqual(self.posts[0]['resolution'],'480p')
        config=self.service.classic_candidate_configuration(self.p,self.objects['shot'],media['id'])
        self.assertTrue(config['document']['draft']);self.assertIn(self.model_ids['1080p'],config['sample_upgrade']['model_ids'])
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='isolated-token',human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            login=client.post('/api/v1/session',json={'token':'isolated-token'},headers={'Origin':'http://testserver'});self.assertEqual(login.status_code,200,login.text)
            headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']};base='/api/v1/projects/'+self.p+'/classic-production/'
            def post(path,payload,mutation=True):
                body={'payload':payload}
                if mutation:body.update(expected_revision=self.service.get_project(self.p)['revision'],idempotency_key=uuid.uuid4().hex)
                if path=='generate':body['confirmed']=True
                response=client.post(base+path,json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);return response.json()
            saved=post('drafts',dict(document=self.upgrade_document(media),base_draft_id=None))
            request=dict(draft_version_id=saved['id'],execution_policy=self.policy())
            preview=post('quote',request,False)
            self.assertTrue(preview['ready'],preview)
            run=post('generate',dict(request=request,preview_sha256=preview['preview_sha256']))
        worker.run_once(self.p);worker.run_once(self.p,poll=True)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'succeeded',job)
        self.assertEqual(self.posts[1],{'model':self.account['model_key'],'content':[{'type':'draft_task','draft_task':{'id':sample['external_task_id']}}],'resolution':'1080p','draft':False})
        self.assertEqual(job['request_payload']['sample_binding']['source_job_id'],sample['id'])
        self.assertEqual([(r['media_id'],r['role'],r['blob_sha256']) for r in job['input_media']],[(media['id'],'operation_source',media['sha256'])])
        upgraded=self.service.get_media(self.p,job['outputs'][0]['media_id']);self.assertEqual(min(upgraded['width'],upgraded['height']),1080);self.assertNotEqual(upgraded['id'],media['id'])
        items=self.service.list_working_candidates(self.p,self.objects['shot'],'video')['items'];self.assertEqual(len(items),2);self.assertEqual(sum(bool(row['native_sample']) for row in items),1)
        with self.engine.connect() as conn:
            events=conn.execute(select(S.job_events.c.job_id,S.job_events.c.evidence).where(S.job_events.c.project_id==self.p,S.job_events.c.event_type=='intent_recorded')).mappings().all()
        quotes={row['job_id']:row['evidence']['generation_quote'] for row in events}
        self.assertEqual(quotes[sample['id']]['amount'],'0.5');self.assertEqual(quotes[job['id']]['amount'],'1.5')
        self.assertNotEqual(quotes[sample['id']]['quote_sha256'],quotes[job['id']]['quote_sha256'])
        self.assertIsNone(worker.run_once(self.p));self.assertIsNone(worker.run_once(self.p,poll=True));self.assertEqual(len(self.posts),2)

    def test_expired_missing_receipt_wrong_account_and_forged_binding_are_refused(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.production.resource_settings import ResourceSettings
        sample,media,worker,_=self.complete_sample();doc=self.upgrade_document(media)
        saved=self.write('save_classic_draft',dict(document=doc,base_draft_id=None));request=dict(draft_version_id=saved['id'],execution_policy=self.policy())
        original=sample['raw_response']
        for changed in [dict(original,created_at=int((self.created-timedelta(days=30)).timestamp())),{k:v for k,v in original.items() if k!='created_at'},dict(original,id='cgt-forged')]:
            with self.engine.begin() as conn:conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.id==sample['id']).values(raw_response=changed))
            with self.subTest(receipt=sorted(changed)),self.assertRaises(ResourceError):self.service.preview_workbench_generation(self.p,request)
        with self.engine.begin() as conn:conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.id==sample['id']).values(raw_response=original))
        other=ResourceSettings(self.store).save(dict(self.preset,model_version='other-account',enabled=True),'test-human')
        wrong=self.store.register_model(dict(provider_id=other['provider_id'],model_key=self.account['model_key'],model_version='wrong-1080p',modality='video',capabilities={'purposes':['video_upgrade'],'video_draft':True,'video_operations':['draft_upgrade']},default_params={'resolution':'1080p','ratio':'16:9'},enabled=True),actor='test-human')
        changed=dict(doc,model_id=wrong['id']);wrong_saved=self.write('save_classic_draft',dict(document=changed,base_draft_id=saved['id']))
        with self.assertRaises(ResourceError):self.service.preview_workbench_generation(self.p,dict(request,draft_version_id=wrong_saved['id']))
        from vsc.production.run_authorization import normalize_request
        with self.assertRaises(ResourceError):normalize_request(dict(prompt=UPGRADE_PROMPT,sample_binding={'external_task_id':'forged'}),self.objects['shot'],'video_upgrade','video')
        self.assertEqual(len(self.posts),1)

    def test_same_account_configuration_and_unknown_upgrade_never_repost(self):
        from vsc.production.resource_settings import ResourceSettings
        settings=ResourceSettings(self.store)
        payload=dict(self.preset,reuse_model_id=self.account['id'],model_version='second-1080p',enabled=False,capabilities={'purposes':['video_upgrade'],'video_draft':True,'video_operations':['draft_upgrade']},default_params=dict(self.account['default_params'],resolution='1080p'))
        second=settings.save(payload,'test-human');self.assertEqual(second['provider_id'],self.account['provider_id']);self.assertNotEqual(second['id'],self.account['id'])
        with self.assertRaises(ResourceError):settings.save(dict(payload,model_key='doubao-seedance-wrong'),'test-human')
        sample,media,_,_=self.complete_sample();run,_=self.queue(self.upgrade_document(media));worker=self.worker(unknown=True)
        with self.assertRaises(Exception):worker.run_once(self.p)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'submission_unknown');self.assertIsNone(job['external_task_id'])
        self.assertEqual(job['request_payload']['sample_binding']['external_task_id'],sample['external_task_id'])
        self.assertIsNone(worker.run_once(self.p));self.assertIsNone(worker.run_once(self.p,poll=True));self.assertEqual(len(self.posts),2)
