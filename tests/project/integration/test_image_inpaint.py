"""Isolated PG, real exported PNGs and original worker; HTTP is MockTransport."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class ImageInpaintTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_settings import PRESETS,ResourceSettings
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-inpaint-test-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service.storage=LocalStorage(self.root/'media');self.objects=self.hierarchy()
        preset=next(p for p in PRESETS if p['id']=='openai-image-inpaint')
        self.assertFalse(preset['enabled'])
        self.model=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':4,'images':4},reason='isolated mask worker test'))
        self.source=self.upload()

    def upload(self,color='blue'):
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(64,64),color).save(stream,format='PNG');stream.seek(0)
        stage=self.service.storage.stage_upload(stream,'source.png')
        return self.write('register_media',{'staged_upload':stage['staged_upload'],'rights':'owned','source':{'kind':'synthetic','content':'generated test pixels'}})

    def policy(self):
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=1,max_repair_rounds=0,authorization={'mode':'new_batch','reason':'isolated fixed-mask verification'})

    def edit(self,source=None,empty=False):
        source=source or self.source
        return dict(id=uuid.uuid4().hex,source_media_id=source['id'],source_sha256=source['sha256'],source_modality='image',time_ms=0,width=64,height=64,description='将圈选区域改成红色',operations=[] if empty else [dict(id='mask',tool='mask',points=[[.5,.5]],color='#ffffff',width=.1)])

    def export(self,empty=False):
        saved=self.write('save_classic_reference_edit',dict(shot_id=self.objects['shot'],mode='image_inpaint',document=self.edit(empty=empty),base_edit_id=None))
        return self.write('export_classic_reference_edit',dict(edit_version_id=saved['id']))

    def draft(self,output):
        mask=next(row for row in output['outputs'] if row['role']=='inpaint-mask')
        return dict(shot_id=self.objects['shot'],mode='image_inpaint',model_id=self.model,purpose='image_edit',prompt='将圈选区域改成红色',width=1024,height=1024,count=1,params={},
            references=[dict(role='operation_source',media_id=self.source['id'],sha256=self.source['sha256']),dict(role='operation_mask',media_id=mask['media_id'],sha256=mask['sha256'])],
            tool_settings=dict(mask_media_id=mask['media_id'],mask_sha256=mask['sha256'],mask_export_id=output['id']))

    def queue(self):
        output=self.export();saved=self.write('save_classic_draft',dict(document=self.draft(output),base_draft_id=None))
        request=dict(draft_version_id=saved['id'],execution_policy=self.policy());quote=self.service.preview_workbench_generation(self.p,request);self.assertTrue(quote['ready'],quote)
        return self.write('generate_workbench',dict(request=request,preview_sha256=quote['preview_sha256']))

    def adapter(self,transport):
        import httpx
        from vsc.adapters.providers.openai_image import openai_image_factory
        client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(client.close)
        return lambda job,storage:openai_image_factory(job,storage,client=client,read_key=lambda:'isolated-openai-key')

    def test_http_export_fixed_draft_quote_worker_candidate_and_reuse(self):
        import httpx
        from PIL import Image
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.production.resource_worker import ResourceWorker
        from vsc.adapters.persistence.postgres import schema as S
        from sqlalchemy import select
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='isolated-token',human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            login=client.post('/api/v1/session',json={'token':'isolated-token'},headers={'Origin':'http://testserver'});self.assertEqual(login.status_code,200,login.text)
            headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']};base='/api/v1/projects/'+self.p
            def post(path,payload,mutation=True,key=None):
                body={'payload':payload}
                if mutation:body.update(expected_revision=self.service.get_project(self.p)['revision'],idempotency_key=key or uuid.uuid4().hex)
                if path=='generate':body['confirmed']=True
                response=client.post(base+'/classic-production/'+path,json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);return response.json()
            saved=post('reference-edits',dict(shot_id=self.objects['shot'],mode='image_inpaint',document=self.edit(),base_edit_id=None))
            output=post('reference-exports',dict(edit_version_id=saved['id']));value=self.draft(output)
            mask=client.get(base+'/media/'+value['tool_settings']['mask_media_id']+'/content');self.assertEqual(mask.status_code,200)
            pixels=Image.open(io.BytesIO(mask.content));self.assertEqual(pixels.getpixel((32,32))[3],0);self.assertEqual(pixels.getpixel((0,0))[3],255)
            fixed=post('drafts',dict(document=value,base_draft_id=None))
            with self.store.engine.connect() as conn:
                refs=conn.execute(select(S.classic_draft_media.c.role).where(S.classic_draft_media.c.project_id==self.p,S.classic_draft_media.c.draft_version_id==fixed['id'])).scalars().all();self.assertEqual(set(refs),{'operation_source','operation_mask'})
                dependencies=conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==self.p,S.artifact_dependencies.c.artifact_id==fixed['id'])).scalars().all();self.assertIn(output['id'],dependencies)
            request=dict(draft_version_id=fixed['id'],execution_policy=self.policy());quote=post('quote',request,False);self.assertTrue(quote['ready'],quote)
            logical=quote['artifact']['document']['series_batch']['jobs'][0]['request'];self.assertEqual(logical['operation'],'inpaint');self.assertEqual(logical['reference_media_ids'],[])
            key=uuid.uuid4().hex;payload=dict(request=request,preview_sha256=quote['preview_sha256']);run=post('generate',payload,key=key);self.assertEqual(run,post('generate',payload,key=key))
            job_id=run['jobs'][0]['id'];calls=[];image=io.BytesIO();Image.new('RGB',(1024,1024),'red').save(image,format='PNG')
            def transport(request):calls.append(request);return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(image.getvalue()).decode()}]})
            worker=ResourceWorker(self.service,self.adapter(transport));worker.run_once(self.p)
            job=self.service.get_generation_job(self.p,job_id);self.assertEqual(job['status'],'succeeded');self.assertEqual(len(calls),1)
            self.assertEqual({row['role'] for row in job['input_media']},{'operation_source','operation_mask'})
            result=client.get(base+'/working-candidates',params={'shot_id':self.objects['shot'],'output_kind':'image'}).json();self.assertEqual(result['total'],1);self.assertTrue(result['items'][0]['selected']);self.assertIsNotNone(result['items'][0]['candidate_id'])
            content=client.get(base+'/media/'+result['items'][0]['media_id']+'/content');self.assertEqual(content.content,image.getvalue())
            config=client.get(base+'/classic-production/candidate-configuration',params={'shot_id':self.objects['shot'],'media_id':result['items'][0]['media_id']}).json();self.assertTrue(config['available']);self.assertEqual(config['document']['mode'],'image_inpaint')
            self.assertIsNone(worker.run_once(self.p));self.assertIsNone(worker.run_once(self.p,poll=True));self.assertEqual(len(calls),1)

    def test_export_source_scope_sha_and_empty_mask_fail_before_job(self):
        output=self.export();draft=self.draft(output);other=self.upload('green')
        cases=[]
        changed=deepcopy(draft);changed['references'][0].update(media_id=other['id'],sha256=other['sha256']);cases.append(changed)
        changed=deepcopy(draft);changed['references'][1]['sha256']='0'*64;cases.append(changed)
        changed=deepcopy(draft);changed['tool_settings']['mask_export_id']=uuid.uuid4().hex;cases.append(changed)
        gray=next(row for row in output['outputs'] if row['role']=='mask');changed=deepcopy(draft);changed['references'][1].update(media_id=gray['media_id'],sha256=gray['sha256']);changed['tool_settings'].update(mask_media_id=gray['media_id'],mask_sha256=gray['sha256']);cases.append(changed)
        for index,value in enumerate(cases):
            with self.subTest(case=index),self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document=value,base_draft_id=None))
        with self.assertRaises(ResourceError):self.write('save_classic_draft',dict(document=self.draft(self.export(empty=True)),base_draft_id=None))
        foreign=self.service.create_project({'name':'foreign image scope'},actor='test-human')['id']
        with self.assertRaises(ResourceError):self.service.save_classic_draft(foreign,dict(document=draft,base_draft_id=None),expected_revision=0,idempotency_key=uuid.uuid4().hex,actor='test-human')
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_unknown_submission_never_resubmits_original_mask_request(self):
        import httpx
        from vsc.production.resource_worker import ResourceWorker
        run=self.queue();calls=[]
        def transport(request):calls.append(request);raise httpx.ReadTimeout('isolated lost response',request=request)
        worker=ResourceWorker(self.service,self.adapter(transport))
        with self.assertRaises(ResourceError):worker.run_once(self.p)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'submission_unknown');self.assertIsNone(job['external_task_id']);self.assertEqual(job['request_payload']['operation'],'inpaint')
        self.assertIsNone(worker.run_once(self.p));self.assertIsNone(worker.run_once(self.p,poll=True));self.assertEqual(len(calls),1)
