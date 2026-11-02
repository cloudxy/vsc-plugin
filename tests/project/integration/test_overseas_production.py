"""Original upload, fixed overseas stages and provider registration boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import support.paths
from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError
from vsc.assets.text_tools import DEFAULTS,COMMON


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class OverseasProductTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-overseas-test-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.service.storage=LocalStorage(self.root/'storage')

    def test_original_chunk_manifest_source_reuses_media_and_rejects_cross_project(self):
        raw='第1章 起点\n固定原文'.encode();sha=hashlib.sha256(raw).hexdigest()
        batch=self.write('create_media_import',dict(title='original source',files=[dict(filename='novel.txt',size_bytes=len(raw),sha256=sha)],rights='unknown',source_evidence=''))
        item=self.service.get_media_import(self.p,batch['id'])['items'][0]
        self.service.upload_import_chunk(self.p,batch['id'],item['id'],0,raw[:10],actor='test-human')
        self.service.upload_import_chunk(self.p,batch['id'],item['id'],0,raw[:10],actor='test-human')
        self.assertEqual(self.service.get_media_import(self.p,batch['id'])['items'][0]['uploaded_bytes'],10)
        result=self.service.upload_import_chunk(self.p,batch['id'],item['id'],10,raw[10:],actor='test-human');self.rev=result['revision']
        registered=self.write('process_media_import_item',dict(batch_id=batch['id'],item_id=item['id']))
        source=self.write('create_source_intake',dict(import_item_id=item['id'],title='原件',intent='novel',format='txt'))
        repeated=self.write('create_source_intake',dict(import_item_id=item['id'],title='原件',intent='novel',format='txt'))
        self.assertEqual(source['id'],repeated['id']);self.assertEqual(source['media_id'],registered['media_id'])
        extraction=self.service.extract_text_tool_source(self.p,dict(media_id=registered['media_id'],format='txt',split='chapters'))
        self.assertEqual(extraction['text'],raw.decode())
        other=self.service.create_project(dict(name='other',profile_snapshot={'profile_id':'vsc.synthetic','version':'1','stages':[]}),actor='test-human')
        with self.assertRaises(ResourceError):self.service.create_source_intake(other['id'],dict(import_item_id=item['id'],intent='novel',format='txt'),actor='test-human',expected_revision=0,idempotency_key=uuid.uuid4().hex)

    @unittest.skipUnless(shutil.which('node'),'requires Node for browser hash implementation')
    def test_incremental_browser_sha_matches_standard_for_chunk_and_padding_boundaries(self):
        module=ROOT/'src/vsc/interfaces/web/static/media-upload.js'
        script="""import fs from 'node:fs';import crypto from 'node:crypto';import assert from 'node:assert/strict';
const {mediaFileSha256}=await import('data:text/javascript;base64,'+fs.readFileSync(process.argv[1]).toString('base64'));
for(const size of [0,1,55,56,63,64,65,1048576+65]){const bytes=Buffer.alloc(size);for(let i=0;i<size;i++)bytes[i]=i%251;assert.equal(await mediaFileSha256(new Blob([bytes])),crypto.createHash('sha256').update(bytes).digest('hex'));}
const controller=new AbortController();controller.abort();await assert.rejects(()=>mediaFileSha256(new Blob(['abc']),{signal:controller.signal}),{name:'AbortError'});
console.log('eight digest boundaries and cancellation passed');"""
        value=subprocess.run(['node','--input-type=module','-e',script,str(module)],capture_output=True,text=True,timeout=30)
        self.assertEqual(value.returncode,0,value.stderr)

    def save_unit(self,document,old=None,episode=None):
        return self.write('save_text_tool',dict(tool='overseas',group_key='overseas-test',unit_key='fixed',title='实际媒体转绘',ordinal=0,episode_id=episode,document=document,unit_id=old['unit_id'] if old else None,base_version_id=old['id'] if old else None))

    def actual_media(self):
        from io import BytesIO
        from support.fixtures.media import production_media
        path=self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=64x64:rate=24','-t','4','-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True,capture_output=True,timeout=30)
        output={}
        for name,raw in [('source.mp4',path.read_bytes()),('reference.png',production_media()['png'])]:
            staged=self.service.storage.stage_upload(BytesIO(raw),name)
            output[name]=self.write('register_media',dict(staged_upload=staged['staged_upload'],name=name,rights='unknown',source={'kind':'synthetic-test','content':'generated local pixels'}))['id']
        return output['source.mp4'],output['reference.png'],path

    def understood(self):
        objects=self.hierarchy();second=self.write('create_object',dict(kind='shot',display_code='SHOT2',parent_id=objects['sequence'],ordinal=1))['id']
        source,image,path=self.actual_media();calls=[]
        class Observer:
            name='isolated-actual-media';basis='sampled-visual-no-audio';capabilities={'understand'}
            def available(self):return True
            def analyze(self,request,media_path):
                calls.append(request);assert hashlib.sha256(media_path.read_bytes()).hexdigest()==request['media']['sha256']
                return {'understanding':'合成测试画面，无对白判断','entities':[{'key':'a','kind':'character','name':'图案主体'},{'key':'place','kind':'scene','name':'色块背景'}],
                    'segments':[dict(key='s'+str(i),start_ms=i*2000,end_ms=(i+1)*2000,observed='可见合成色块',inferred='无人物身份判断',character_keys=['a'],scene_key='place') for i in range(2)]}
        self.service.media_understanding_host=Observer();self.addCleanup(delattr,self.service,'media_understanding_host')
        saved=self.save_unit({**deepcopy(COMMON),**deepcopy(DEFAULTS['overseas']), 'source_media_id':source,'target_language':'English'},episode=objects['episode'])
        key=uuid.uuid4().hex;payload=dict(unit_id=saved['unit_id'],input_version_id=saved['id'],action='understand')
        run=self.write('run_text_tool',payload,idempotency_key=key);self.assertEqual(run['status'],'completed',run)
        self.assertEqual(self.write('run_text_tool',payload)['id'],run['id']);self.assertEqual(len(calls),1)
        accepted=self.write('accept_text_tool_result',dict(attempt_id=run['id'],base_version_id=saved['id']))
        unit=self.service.get_text_tool(self.p,saved['unit_id']);doc=unit['document'];self.assertEqual(doc['observation_basis'],'sampled-visual-no-audio');self.assertEqual(doc['segments'][0]['inference'],'无人物身份判断')
        stage=self.write('stage_overseas_baseline',dict(unit_id=saved['unit_id'],version_id=accepted['id'],phase='understanding'))
        self.assertFalse(self.service.get_artifact_version(self.p,stage['id'])['approved'])
        self.write('decide_artifact',dict(artifact_id=stage['id'],reason='测试操作者明确确认固定观察'))
        doc['understanding_version_id']=stage['id'];doc['body']='Localized synthetic patterns.'
        for entity in doc['entities']:entity['media_id']=image;entity['localized']=entity['name']
        for group,shot in zip(doc['groups'],[objects['shot'],second]):group.update(shot_id=shot,first_frame_media_id=image)
        for segment in doc['segments']:segment['localized_text']='A visible pattern.'
        saved=self.save_unit(doc,accepted,objects['episode'])
        return objects,source,image,path,saved

    def test_real_media_understanding_fixed_confirmation_and_registration_receipts(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.providers.asset_registry import CommandAssetRegistry
        objects,source,image,path,saved=self.understood()
        self.service.asset_registry=CommandAssetRegistry({});self.addCleanup(delattr,self.service,'asset_registry')
        payload=dict(unit_id=saved['unit_id'],version_id=saved['id'],entity_key='a')
        with self.assertRaises(ResourceError) as error:self.write('register_overseas_asset',payload)
        self.assertEqual(error.exception.code,'asset_registry_unavailable')
        calls=[]
        class Registry:
            provider='isolated-registry';account_scope='isolated-account'
            def available(self):return True
            def register(self,request,media_path):
                calls.append(request);assert hashlib.sha256(media_path.read_bytes()).hexdigest()==request['media_sha256']
                return {k:request[k] for k in ('provider','account_scope','request_id','media_sha256')}|{'remote_asset_id':'asset-123','evidence':{'fixture':'explicit synthetic receipt'}}
        self.service.asset_registry=Registry()
        receipt=self.write('register_overseas_asset',payload);self.assertEqual(receipt['status'],'completed',receipt)
        repeated=self.write('register_overseas_asset',payload);self.assertEqual(receipt['id'],repeated['id']);self.assertEqual(len(calls),1)
        forged={k:receipt[k] for k in S.provider_asset_registrations.c.keys() if k in receipt};forged.update(id=str(uuid.uuid4()),media_sha256='0'*64)
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(insert(S.provider_asset_registrations).values(**forged))
        original=self.service.asset_registry.register
        def bad(request,media_path):return dict(original(request,media_path),remote_asset_id='https://example.invalid/picture.png')
        self.service.asset_registry.register=bad
        unknown=self.write('register_overseas_asset',dict(payload,entity_key='place'));self.assertEqual(unknown['status'],'submission_unknown');self.assertIsNone(unknown['remote_asset_id'])
        self.assertEqual(self.write('register_overseas_asset',dict(payload,entity_key='place',new_attempt=True))['id'],unknown['id']);self.assertEqual(len(calls),2)
        from vsc.production.overseas_production import understanding_patch
        with self.assertRaises(ResourceError):understanding_patch({'understanding':'x','entities':[],'segments':[dict(key='s',start_ms=1,end_ms=4000,observed='x',inferred='',character_keys=[],scene_key='')]},4000,'sampled')

    def test_asset_image_two_working_groups_actual_local_composition_and_download(self):
        from datetime import datetime,timedelta,timezone
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        from vsc.production.providers import GeneratedAsset,JobHandle,JobStatus
        from vsc.production.resource_worker import ResourceWorker
        from vsc.post.first_cut_worker import FirstCutWorker
        from support.fixtures.media import production_media
        objects,source,image,path,saved=self.understood()
        models={}
        for kind in ('image','video'):
            preset=next(r for r in PRESETS if r['id']=='xai-grok-imagine-'+kind)
            models[kind]=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True,'model_version':'isolated-overseas-working'},'test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':10,'video_seconds':20,'images':5},reason='本地隔离适配器测试'))
        now=datetime.now(timezone.utc);policy=dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=20)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=3,max_repair_rounds=1,authorization={'mode':'new_batch','reason':'测试操作者明确生成固定候选'})
        submissions=[];rawvideo=path.read_bytes();rawimage=production_media()['png']
        class Adapter:
            def submit(self,request):submissions.append(request);self.kind='image' if type(request).__name__=='ImageRequest' else 'video';return JobHandle('isolated','job-'+str(len(submissions)),None,{'kind':self.kind})
            def poll(self,handle):return JobStatus('succeeded',raw=handle.raw)
            def parse_result(self,raw):return [GeneratedAsset(raw['kind'],inline_bytes=rawimage if raw['kind']=='image' else rawvideo)]
        worker=ResourceWorker(self.service,lambda *_:Adapter())
        def generate(fixed):
            request=dict(draft_version_id=fixed['classic_draft_id'],execution_policy=policy);preview=self.service.preview_workbench_generation(self.p,request);self.assertTrue(preview['ready'],preview.get('gaps'))
            result=self.write('generate_workbench',dict(request=request,preview_sha256=preview['preview_sha256']));done=worker.run_once(self.p);self.assertEqual(done['status'],'succeeded',done);self.rev=self.service.get_project(self.p)['revision']
            job=self.service.get_generation_job(self.p,result['jobs'][0]['id']);return job['id'],job['outputs'][0]['media_id']
        asset=self.write('prepare_overseas_asset_image',dict(unit_id=saved['unit_id'],version_id=saved['id'],entity_key='a',settings={'shot_id':objects['shot'],'model_id':models['image'],'count':1,'width':720,'height':1280},attempt_key=str(uuid.uuid4()),base_classic_draft_id=None))
        job,media=generate(asset);saved=self.write('select_overseas_asset_image',dict(unit_id=saved['unit_id'],version_id=saved['id'],asset_draft_id=asset['id'],job_id=job,media_id=media))
        doc=self.service.get_text_tool(self.p,saved['unit_id'])['document'];self.assertEqual(doc['entities'][0]['media_id'],media)
        baseline=self.write('stage_overseas_baseline',dict(unit_id=saved['unit_id'],version_id=saved['id'],phase='localization'));self.write('decide_artifact',dict(artifact_id=baseline['id'],reason='测试操作者明确确认本地化版'))
        for group in doc['groups']:
            fixed=self.write('prepare_overseas_group',dict(unit_id=saved['unit_id'],version_id=saved['id'],localization_version_id=baseline['id'],group_key=group['key'],settings={'mode':'single','model_id':models['video']},attempt_key=str(uuid.uuid4()),new_attempt=False))
            job,media=generate(fixed);status=self.service.get_text_tool(self.p,saved['unit_id'])['overseas'];row=next(r for r in status['groups'] if r['id']==fixed['id'])
            self.assertTrue(row['runs'][0]['working'])
            saved=self.write('select_overseas_candidate',dict(unit_id=saved['unit_id'],version_id=saved['id'],group_draft_id=fixed['id'],job_id=job,media_id=media,candidate_in_ms=500,working_selection_version_id=row['working_selection_version_id']))
        request=dict(unit_id=saved['unit_id'],version_id=saved['id'],episode_id=objects['episode']);preview=self.service.preview_text_tool_import(self.p,request)
        self.assertEqual(len(preview['plan']['document']['clips']),2);self.assertTrue(all(r['working_selection_version_id'] for r in preview['plan']['document']['clips']))
        imported=self.write('import_text_tool',dict(request=request,preview_sha256=preview['preview_sha256']))
        render=self.write('request_edit_export',dict(edit_version_id=imported['edit_version_id']));done=FirstCutWorker(self.store,self.service.storage).run_once(self.p);self.assertEqual(done['status'],'succeeded',done)
        output,receipt=self.service.edit_export_content(self.p,render['id']);self.assertTrue(output.is_file());self.assertGreater(output.stat().st_size,1000)
        archive,mime,temporary=self.service.export_edit_workspace(self.p,imported['edit_version_id'],'clips',[r['id'] for r in preview['plan']['document']['clips']]);self.addCleanup(temporary.cleanup)
        import zipfile
        with zipfile.ZipFile(archive) as zip_:self.assertEqual(len([n for n in zip_.namelist() if n.endswith('.mp4')]),2)
        self.assertEqual(len(submissions),3)

    def test_command_registry_transfers_actual_file_and_http_requires_confirmation(self):
        from vsc.adapters.providers.asset_registry import CommandAssetRegistry,validated_receipt
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from types import SimpleNamespace
        objects,source,image,path,saved=self.understood()
        raw=b'actual copied bytes';source_path=self.root/'fixture.png';source_path.write_bytes(raw)
        request=dict(provider='synthetic-command',account_scope='local',request_id=str(uuid.uuid4()),media_sha256=hashlib.sha256(raw).hexdigest(),entity_key='a',media_id=image)
        def runner(argv,**kwargs):
            manifest=json.loads(Path(argv[argv.index('--request')+1]).read_text());self.assertEqual(Path(manifest['media_file']).read_bytes(),raw);self.assertNotEqual(manifest['media_file'],str(source_path))
            Path(argv[argv.index('--response')+1]).write_text(json.dumps({k:request[k] for k in ('provider','account_scope','request_id','media_sha256')}|dict(remote_asset_id='remote-command-identity',evidence={'fixture':'local command protocol'})))
            return SimpleNamespace(returncode=0)
        host=CommandAssetRegistry({'command':[shutil.which('python3')],'provider':request['provider'],'account_scope':'local'},runner=runner)
        self.assertEqual(validated_receipt(host.register(request,source_path),request)['remote_asset_id'],'remote-command-identity')
        self.service.asset_registry=CommandAssetRegistry({});self.addCleanup(delattr,self.service,'asset_registry')
        app=create_app({'projects_root':str(self.root/'projects'),'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'test','human_identity':'test-human','background_enabled':False},service=self.service)
        with TestClient(app) as client:
            base='/api/v1/projects/'+self.p+'/text-tools/overseas/register-asset';body=dict(payload=dict(unit_id=saved['unit_id'],version_id=saved['id'],entity_key='a'),expected_revision=self.rev,idempotency_key=uuid.uuid4().hex)
            self.assertEqual(client.post(base,json=body).status_code,403)
            session=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json();headers={'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']}
            self.assertEqual(client.post(base,json=body,headers=headers).status_code,422)
            response=client.post(base,json=dict(body,confirmed=True),headers=headers);self.assertEqual(response.status_code,422,response.text);self.assertIn('asset_registry_unavailable',response.text)

    def test_overseas_migration_allows_empty_domain_and_refuses_new_history(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        with isolated_postgres(TEST_URL) as engine:
            cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:
                cfg.attributes['connection']=conn;command.downgrade(cfg,'0040_canvas_sound_completion')
                self.assertIsNone(conn.scalar(text("SELECT to_regclass('provider_asset_registrations')")));command.upgrade(cfg,'head')
            service=ResourceService(PostgresResourceStore(engine=engine));project=service.create_project(dict(name='migration fixture',profile_snapshot={'profile_id':'vsc.synthetic','version':'1','stages':[]}),actor='test-human')
            artifact=service.create_artifact(project['id'],dict(artifact_type='overseas-asset-image-draft',artifact_key='migration-fact',document={'fixture':'fixed new-domain history'}),actor='test-human',expected_revision=0,idempotency_key=uuid.uuid4().hex)
            with engine.connect() as conn:
                cfg.attributes['connection']=conn
                with self.assertRaises(IntegrityError):
                    with conn.begin():command.downgrade(cfg,'0040_canvas_sound_completion')
                self.assertEqual(conn.scalar(text('SELECT count(*) FROM artifact_versions WHERE id=:id'),{'id':artifact['id']}),1)

    def test_manual_observation_mode_never_invokes_media_host(self):
        objects,source,image,path,saved=self.understood()
        document=self.service.get_text_tool(self.p,saved['unit_id'])['document'];document['understanding_mode']='manual';saved=self.save_unit(document,saved,objects['episode'])
        def forbidden(*args):raise AssertionError('manual mode invoked the media host')
        self.service.media_understanding_host.analyze=forbidden
        attempt=self.write('run_text_tool',dict(unit_id=saved['unit_id'],input_version_id=saved['id'],action='understand'))
        self.assertEqual(attempt['status'],'failed');self.assertEqual(attempt['error_code'],'media_capability_unavailable')
