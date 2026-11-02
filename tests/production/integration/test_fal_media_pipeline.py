"""Controlled decodable media and native FAL transport; never live inference."""
from dataclasses import replace
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
import subprocess
import uuid

import httpx
from PIL import Image
from support.fixtures.media import production_media
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.adapters.providers.fal_media import BASE, FalMediaProvider
from vsc.adapters.storage.local.store import LocalStorage
from vsc.assets.resource_service import ResourceError
from vsc.production.fal_tools import ENDPOINTS, depth_operation_fields, image_operation_fields, validate_output
from vsc.production.providers import VideoRequest


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires actual local video decode')
class FalMediaBytesTests(unittest.TestCase):
    def test_depth_input_is_real_fixed_video_and_output_requires_complete_duration(self):
        with tempfile.TemporaryDirectory(prefix='vsc-fal-bytes-') as directory:
            storage = LocalStorage(directory)
            content = production_media()['mp4']; path = Path(directory) / 'source.mp4'; path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            source = {'id': 'source', 'sha256': digest, 'modality': 'video', 'duration_ms': 400}
            fields = depth_operation_fields(source); prompt = fields.pop('prompt')
            request = VideoRequest('shot', 'depth', 'a' * 64, prompt, **fields)
            row = {'media_id': 'source', 'role': 'operation_source', 'blob_sha256': digest, 'mime_type': 'video/mp4',
                   'locations': [{'storage': 'local', 'available': True, 'object_key': 'source.mp4'}]}
            calls = []
            receipt = {'request_id': 'depth-task', 'status': 'IN_QUEUE', **{name: BASE + '/' + ENDPOINTS['depth'] + '/requests/depth-task' + suffix
                for name, suffix in [('response_url', ''), ('status_url', '/status'), ('cancel_url', '/cancel')]}}
            def transport(wire):
                calls.append(wire)
                if wire.method == 'POST':
                    body = json.loads(wire.content)
                    self.assertEqual(base64.b64decode(body['video_url'].split(',', 1)[1]), content)
                    self.assertEqual(body['max_frames'], 2); self.assertEqual(body['model'], 'VDA-Large')
                    self.assertEqual(body['colormap'], 'grayscale'); self.assertFalse(body['side_by_side'])
                    self.assertFalse(body['include_raw_depths']); self.assertNotIn('prompt', body)
                    return httpx.Response(200, json=receipt)
                if wire.url.path.endswith('/status'):
                    return httpx.Response(200, json={'request_id': 'depth-task', 'status': 'COMPLETED'})
                return httpx.Response(200, json={'video': {'url': 'https://v3.fal.media/depth.mp4'}})
            with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                provider = FalMediaProvider(ENDPOINTS['depth'], 'fal', [row], storage, client=client, read_key=lambda: 'test-fal-key')
                handle = provider.submit(request); status = provider.poll(handle)
                self.assertEqual(provider.parse_result(status.raw)[0].modality, 'video')
                with self.assertRaises(ResourceError): provider.preflight(replace(request, source_duration_ms=3000, duration_ms=3000))
                with self.assertRaises(ResourceError): provider.preflight(replace(request, prompt='不能静默忽略用户运动说明'))
            staged = storage.stage_upload(io.BytesIO(content), 'controlled-depth.mp4')
            registered = storage.commit_upload(staged['staged_upload'])
            self.assertEqual(registered['probe']['decode']['status'], 'passed')
            validate_output(vars(request), registered)
            with self.assertRaises(ResourceError): validate_output(vars(request), {**registered, 'duration_ms': 100})
            self.assertEqual([wire.method for wire in calls], ['POST', 'GET', 'GET'])

    def test_upscale_and_panorama_contracts_use_actual_registered_pixel_dimensions(self):
        with tempfile.TemporaryDirectory(prefix='vsc-fal-images-') as directory:
            storage = LocalStorage(directory)
            source = {'id': 'source', 'sha256': 'a' * 64, 'modality': 'image', 'width': 960, 'height': 540}
            for operation, size in [('upscale', (3840, 2160)), ('panorama', (1920, 960))]:
                with self.subTest(operation=operation):
                    logical = image_operation_fields(operation, source, {})
                    stream = io.BytesIO(); Image.new('RGB', size, (50, 100, 160)).save(stream, format='PNG')
                    staged = storage.stage_upload(io.BytesIO(stream.getvalue()), 'actual.png')
                    registered = storage.commit_upload(staged['staged_upload'])
                    self.assertEqual((registered['width'], registered['height']), size)
                    validate_output(logical, registered)
                    with self.assertRaises(ResourceError): validate_output(logical, {**registered, 'width': 960, 'height': 540})


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS and shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires isolated PG and real media decoding')
class FalMediaPipelineTests(ResourceStoreFixture,unittest.TestCase):
    def write(self,method,payload,**kw):
        self.rev=self.service.get_project(self.p)['revision']
        return super().write(method,payload,**kw)

    def setUp(self):
        super().setUp()
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-fal-pipeline-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service.storage=LocalStorage(self.root/'media');self.objects=self.hierarchy();self.models={}
        for operation in ENDPOINTS:
            preset=next(row for row in PRESETS if row['id']=='fal-'+operation)
            self.models[operation]=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        from vsc.adapters.providers.credentials import PLAN_BASE,KEY_ENV
        self.models['final']=ResourceSettings(self.store).save(dict(name='Controlled final video',supplier='volcengine',product='ark',plan='agent-plan',region='cn-beijing',execution='api',modality='video',model_key='doubao-seedance-2-0-260128',model_version='test-fixed',base_url=PLAN_BASE,auth_ref=KEY_ENV,enabled=True,capabilities={'purposes':['reference_to_video'],'reference_media':True,'reference_video':True,'max_duration_ms':15000},default_params={'resolution':'480p','ratio':'16:9','generate_audio':False}),'test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':10,'images':10,'video_seconds':20},reason='controlled native-media contract'))
        self.contents={'source':production_media()['mp4']}
        for name,color,duration in [('depth','gray',.4),('final','black',1)]:
            path=self.root/(name+'.mp4');subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color='+color+':size=16x16:rate=5','-t',str(duration),'-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True,capture_output=True,timeout=30);self.contents[name]=path.read_bytes()
        stream=io.BytesIO();Image.new('RGB',(960,540),(20,60,100)).save(stream,format='PNG');self.contents['image']=stream.getvalue()
        self.source=self.upload('source.mp4',self.contents['source']);self.character=self.upload('character.png',self.contents['image'])

    def upload(self,name,content):
        staged=self.service.storage.stage_upload(io.BytesIO(content),name)
        return self.write('register_media',dict(name=name,staged_upload=staged['staged_upload'],rights='unknown',source={'kind':'user_upload','content':'controlled synthetic fixture'}))

    def policy(self):
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=1,max_repair_rounds=0,authorization={'mode':'new_batch','reason':'controlled fal verification'})

    def depth_queue(self):
        draft=self.write('save_creative_tool_draft',dict(document=dict(tool='depth_motion',episode_id=self.objects['episode'],shot_id=self.objects['shot'],source_media_id=self.source['id'],visual_media_ids=[self.character['id']],model_id=self.models['final'],depth_model_id=self.models['depth'],duration_ms=1000,prompt='Keep the chosen character and follow the grayscale motion.'),base_draft_id=None))
        fixed=self.write('prepare_creative_tool_work',dict(draft_version_id=draft['id']))
        request=dict(draft_version_id=draft['id'],execution_policy=self.policy());preview=self.service.preview_creative_tool_run(self.p,request);self.assertTrue(preview['ready'],preview)
        self.assertEqual(len(preview['generation_quote']['jobs']),2)
        self.assertEqual(preview['generation_quote']['native_units'],{'remote_jobs':2,'video_seconds':2})
        result=self.write('generate_creative_tool_work',dict(request=request,preview_sha256=preview['preview_sha256']))
        self.assertEqual(len(result['jobs']),1)
        return draft,fixed,result

    def worker(self,calls,*,failure=False,unknown=False,download=None):
        from vsc.adapters.providers.fal_media import fal_media_factory
        from vsc.adapters.providers.volc_ark.resource_factory import volc_ark_factory
        from vsc.production.resource_worker import ResourceWorker
        task_id='controlled-'+uuid.uuid4().hex
        def transport(wire):
            calls.append((wire.method,str(wire.url),json.loads(wire.content) if wire.content else None))
            if wire.url.host=='queue.fal.run':
                endpoint=wire.url.path.split('/requests/')[0].lstrip('/')
                if wire.method=='POST':
                    if unknown:raise httpx.ReadTimeout('controlled lost submit',request=wire)
                    return httpx.Response(200,json={'request_id':task_id,'status':'IN_QUEUE',**{key:BASE+'/'+endpoint+'/requests/'+task_id+suffix for key,suffix in [('status_url','/status'),('response_url',''),('cancel_url','/cancel')]}})
                if wire.url.path.endswith('/status'):
                    return httpx.Response(200,json={'request_id':task_id,'status':'COMPLETED',**({'error':'controlled failure','error_type':'runner_error'} if failure else {})})
                field='video' if endpoint==ENDPOINTS['depth'] else 'image'
                return httpx.Response(200,json={field:{'url':'https://v3.fal.media/'+('depth' if field=='video' else 'image')}})
            return httpx.Response(200,json={'id':'final-task'} if wire.method=='POST' else {'status':'succeeded','content':{'video_url':'https://v3.fal.media/final'}})
        client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(client.close)
        def factory(job,storage):
            if job['provider']['configuration']['supplier']=='fal':return fal_media_factory(job,storage,client=client,read_key=lambda:'mock-fal-only')
            provider=volc_ark_factory(job,storage)
            provider.adapter.transport=lambda path,payload=None:client.request('POST' if payload is not None else 'GET','https://controlled-ark.invalid'+path,**({'json':payload} if payload is not None else {})).json()
            return provider
        return ResourceWorker(self.service,factory,download=download or (lambda url,path:path.write_bytes(self.contents[url.rsplit('/',1)[-1]])))

    def test_native_images_use_original_http_quote_worker_and_storage_recovery(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='isolated',human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            login=client.post('/api/v1/session',json={'token':'isolated'},headers={'Origin':'http://testserver'});self.assertEqual(login.status_code,200,login.text)
            headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']};base='/api/v1/projects/'+self.p
            def post(path,payload,mutation=True):
                body={'payload':payload}
                if mutation:body.update(expected_revision=self.service.get_project(self.p)['revision'],idempotency_key=uuid.uuid4().hex)
                if path=='generate':body['confirmed']=True
                response=client.post(base+'/classic-production/'+path,json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);return response.json()
            for operation,size in [('panorama',(1920,960)),('upscale',(3840,2160))]:
                with self.subTest(operation=operation):
                    document=dict(shot_id=self.objects['shot'],mode='image_'+operation,purpose='image_edit',model_id=self.models[operation],prompt='Preserve the landscape.',references=[dict(role='operation_source',media_id=self.character['id'])])
                    draft=post('drafts',dict(document=document,base_draft_id=None));request=dict(draft_version_id=draft['id'],execution_policy=self.policy());quote=post('quote',request,False);self.assertTrue(quote['ready'],quote)
                    run=post('generate',dict(request=request,preview_sha256=quote['preview_sha256']));calls=[];downloads=[]
                    stream=io.BytesIO();Image.new('RGB',size,(20,40,80)).save(stream,format='PNG');content=stream.getvalue()
                    def download(url,path):
                        downloads.append(url)
                        if len(downloads)==1:raise OSError('controlled interrupted transfer')
                        path.write_bytes(content)
                    worker=self.worker(calls,download=download);worker.run_once(self.p)
                    with self.assertRaises(OSError):worker.run_once(self.p,poll=True)
                    worker.run_once(self.p,poll=True);job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'succeeded');self.assertEqual([c[0] for c in calls],['POST','GET','GET'])
                    media=self.service.get_media(self.p,job['outputs'][0]['media_id']);self.assertEqual((media['width'],media['height']),size)
                    response=client.get(base+'/media/'+media['id']+'/content?download=true');self.assertEqual(response.status_code,200);self.assertEqual(response.content,content)

    def test_panorama_configuration_reads_original_fixed_mode_without_regenerating_output(self):
        document=dict(shot_id=self.objects['shot'],mode='image_panorama',purpose='image_edit',model_id=self.models['panorama'],
            prompt='Original panorama configuration.',references=[dict(role='operation_source',media_id=self.character['id'])])
        draft=self.write('save_classic_draft',dict(document=document,base_draft_id=None))
        request=dict(draft_version_id=draft['id'],execution_policy=self.policy())
        quote=self.service.preview_classic_run(self.p,request,working=True);self.assertTrue(quote['ready'],quote)
        run=self.write('generate_workbench',dict(request=request,preview_sha256=quote['preview_sha256']))
        stream=io.BytesIO();Image.new('RGB',(1920,960),(20,40,80)).save(stream,format='PNG');content=stream.getvalue()
        calls=[];worker=self.worker(calls,download=lambda url,path:path.write_bytes(content))
        worker.run_once(self.p);worker.run_once(self.p,poll=True)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'succeeded')
        media_id=job['outputs'][0]['media_id']
        self.write('save_classic_draft',dict(document={**document,'prompt':'Later unsampled draft must not replace provenance.'},base_draft_id=draft['id']))
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='isolated',
            human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/v1/session',json={'token':'isolated'},headers={'Origin':'http://testserver'}).status_code,200)
            response=client.get('/api/v1/projects/'+self.p+'/classic-production/candidate-configuration',params={'shot_id':self.objects['shot'],'media_id':media_id})
            self.assertEqual(response.status_code,200,response.text);fixed=response.json()
        self.assertTrue(fixed['available']);self.assertEqual(fixed['source_operation'],'panorama');self.assertEqual(fixed['source_job_id'],job['id'])
        self.assertEqual(fixed['document']['mode'],'image_panorama');self.assertEqual(fixed['document']['prompt'],document['prompt'])
        self.assertEqual(fixed['document']['references'][0]['media_id'],self.character['id'])
        self.assertEqual(fixed['document']['references'][0]['sha256'],self.character['sha256'])
        self.assertFalse(self.service.classic_candidate_configuration(self.p,self.objects['shot'],self.character['id'])['available'])
        other=self.write('create_object',dict(kind='shot',display_code='OTHER',parent_id=self.objects['sequence'],ordinal=1))['id']
        self.assertFalse(self.service.classic_candidate_configuration(self.p,other,media_id)['available'])
        self.assertEqual(sum(method=='POST' for method,_,_ in calls),1)

    def test_depth_graph_resolves_original_output_then_publishes_four_media_three_edges(self):
        from vsc.production.bounded import execute_batch
        draft,fixed,run=self.depth_queue();calls=[];worker=self.worker(calls)
        first=execute_batch(self.service,self.p,{'run_version_id':run['run_version_id']},'test-human');self.assertEqual(first['waiting_count'],1)
        worker.run_once(self.p);worker.run_once(self.p,poll=True)
        depth_job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);depth_id=depth_job['outputs'][0]['media_id'];self.assertEqual(depth_job['status'],'succeeded')
        self.assertNotIn(depth_id,{r['media_id'] for r in self.service.list_working_candidates(self.p,self.objects['shot'],'video')['items']})
        advanced=execute_batch(self.service,self.p,{'run_version_id':run['run_version_id']},'test-human');self.assertEqual(advanced['created_count'],1,advanced)
        final_id=next(task['job_id'] for task in advanced['tasks'] if task['purpose']=='reference_to_video');final=self.service.get_generation_job(self.p,final_id)
        self.assertEqual(final['request_payload']['reference_video_media_ids'],[depth_id]);self.assertEqual(final['request_payload']['reference_media_ids'],[self.character['id']])
        execute_batch(self.service,self.p,{'run_version_id':run['run_version_id']},'test-human');worker.run_once(self.p);worker.run_once(self.p,poll=True)
        final=self.service.get_generation_job(self.p,final_id);self.assertEqual(final['status'],'succeeded')
        final_body=next(body for method,url,body in calls if method=='POST' and 'controlled-ark' in url)
        videos=[row['video_url']['url'] for row in final_body['content'] if row['type']=='video_url'];self.assertEqual(len(videos),1);self.assertEqual(base64.b64decode(videos[0].split(',',1)[1]),self.contents['depth']);self.assertNotEqual(self.contents['depth'],self.contents['source'])
        self.service.advance_creative_tool_work(self.p,{'run_version_id':run['run_version_id']},actor='test-human')
        output=next(row for row in self.service.creative_tools_options(self.p,self.objects['episode'])['local_outputs'] if row.get('run_version_id')==run['run_version_id'])
        self.assertEqual({row['role'] for row in output['outputs']},{'depth_intermediate','generated_video'})
        canvas=self.write('create_creative_canvas',dict(title='Depth provenance',episode_id=self.objects['episode'],document={'nodes':[],'edges':[]}))
        self.write('use_creative_tool_output',dict(output_version_id=output['id'],media_id=final['outputs'][0]['media_id'],target='canvas',canvas_id=canvas['id'],canvas_revision=1))
        graph=self.service.get_creative_canvas(self.p,canvas['id'])['document'];self.assertEqual(len(graph['nodes']),4);self.assertEqual(len(graph['edges']),3)
        with self.assertRaises(ResourceError):self.write('use_creative_tool_output',dict(output_version_id=output['id'],media_id=depth_id,target='candidate',shot_id=self.objects['shot']))
        self.assertEqual(sum(method=='POST' for method,_,_ in calls),2)

    def test_failed_depth_blocks_only_successor_and_does_not_submit_final(self):
        from vsc.production.bounded import execute_batch
        _,_,run=self.depth_queue();calls=[];worker=self.worker(calls,failure=True);worker.run_once(self.p);worker.run_once(self.p,poll=True)
        result=execute_batch(self.service,self.p,{'run_version_id':run['run_version_id']},'test-human');self.assertEqual(result['blocked_count'],1);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1);self.assertEqual(sum(row[0]=='POST' for row in calls),1)

    def test_unknown_depth_submit_waits_original_job_without_repost(self):
        from vsc.production.bounded import execute_batch
        _,_,run=self.depth_queue();calls=[];worker=self.worker(calls,unknown=True)
        with self.assertRaises(ResourceError):worker.run_once(self.p)
        for _ in range(2):
            result=execute_batch(self.service,self.p,{'run_version_id':run['run_version_id']},'test-human');self.assertEqual(result['waiting_count'],1);worker.run_once(self.p);worker.run_once(self.p,poll=True)
        self.assertEqual(self.service.get_generation_job(self.p,run['jobs'][0]['id'])['status'],'submission_unknown');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1);self.assertEqual(len(calls),1)

    def test_watermark_requires_explicit_rights_and_original_exported_mask(self):
        from vsc.production.resource_settings import PRESETS,ResourceSettings
        from vsc.adapters.providers.openai_image import openai_image_factory
        from vsc.production.resource_worker import ResourceWorker
        preset=next(row for row in PRESETS if row['id']=='openai-image-inpaint')
        model=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        edit=self.write('save_classic_reference_edit',dict(shot_id=self.objects['shot'],mode='image_watermark',base_edit_id=None,document=dict(id=uuid.uuid4().hex,source_media_id=self.character['id'],source_sha256=self.character['sha256'],source_modality='image',time_ms=0,width=960,height=540,description='remove my own test watermark',operations=[dict(id='mask',tool='mask',points=[[.5,.5]],color='#ffffff',width=.1)])))
        exported=self.write('export_classic_reference_edit',dict(edit_version_id=edit['id']));mask=next(row for row in exported['outputs'] if row['role']=='inpaint-mask')
        value=dict(shot_id=self.objects['shot'],mode='image_watermark',model_id=model,purpose='image_edit',prompt='Restore the marked background.',width=1024,height=1024,
            references=[dict(role='operation_source',media_id=self.character['id'],sha256=self.character['sha256']),dict(role='operation_mask',media_id=mask['media_id'],sha256=mask['sha256'])],
            tool_settings=dict(rights_confirmed=False,mask_media_id=mask['media_id'],mask_sha256=mask['sha256'],mask_export_id=exported['id']))
        draft=self.write('save_classic_draft',dict(document=value,base_draft_id=None));request=dict(draft_version_id=draft['id'],execution_policy=self.policy())
        with self.assertRaises(ResourceError) as error:self.service.preview_workbench_generation(self.p,request)
        self.assertEqual(error.exception.code,'watermark_rights_required')
        value['tool_settings']['rights_confirmed']=True;draft=self.write('save_classic_draft',dict(document=value,base_draft_id=draft['id']));request['draft_version_id']=draft['id']
        quote=self.service.preview_workbench_generation(self.p,request);self.assertTrue(quote['ready']);run=self.write('generate_workbench',dict(request=request,preview_sha256=quote['preview_sha256']))
        stream=io.BytesIO();Image.new('RGB',(1024,1024),(80,80,80)).save(stream,format='PNG');calls=[]
        def transport(wire):calls.append(wire);return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]})
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            ResourceWorker(self.service,lambda job,storage:openai_image_factory(job,storage,client=client,read_key=lambda:'mock-openai-only')).run_once(self.p)
        self.assertEqual(self.service.get_generation_job(self.p,run['jobs'][0]['id'])['status'],'succeeded');self.assertEqual(len(calls),1)
