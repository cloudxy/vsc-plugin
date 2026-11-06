"""Classic modes preserve drafts and consume the original quote/run authorities."""
import importlib.util
import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ClassicProductionTests(ResourceStoreFixture, unittest.TestCase):
    def ready_shot(self):
        objects = self.hierarchy()
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']], {'state_versions': [{'scene_id': objects['scene']}]})
        media = self.media('经典首帧')
        self.select(self.candidate(objects['shot'], media))
        from vsc.production.resource_settings import ResourceSettings, PRESETS
        settings = ResourceSettings(self.store)
        preset = next(row for row in PRESETS if row['id'] == 'xai-grok-imagine-video')
        payload = {k: v for k, v in preset.items() if k not in ('id', 'label')}
        payload.update(enabled=True, model_version='offline-test')
        model = settings.save(payload, 'test-human')
        return objects, media, model['id']

    def document(self, shot, media=None, model='', mode='single', prompt='固定动作'):
        value = dict(shot_id=shot, mode=mode, model_id=model, purpose='image_to_video',
                     prompt=prompt, duration_ms=5000, width=1080, height=1920, count=1, params={}, references=[])
        if media:
            value['references'] = [{'role': 'first_frame', 'media_id': media}]
        return value

    def policy(self):
        now = datetime.now(timezone.utc)
        return dict(version='bounded-v1', first_draft_due_at=(now+timedelta(minutes=45)).isoformat(),
                    stop_submitting_at=(now+timedelta(minutes=60)).isoformat(),
                    max_attempts_per_purpose=2, max_repair_rounds=1)

    def test_mode_versions_replay_conflict_and_project_isolation(self):
        from vsc.assets.resource_service import Conflict, ResourceError
        objects = self.hierarchy()
        single = self.document(objects['shot'])
        payload = {'document': single, 'base_draft_id': None}
        key = uuid.uuid4().hex
        first = self.write('save_classic_draft', payload, idempotency_key=key)
        text = self.document(objects['shot'], mode='text', prompt='另一个模式')
        second = self.write('save_classic_draft', {'document': text, 'base_draft_id': None})
        replay = self.service.save_classic_draft(self.p, payload, expected_revision=0,
            idempotency_key=key, actor='test-human')
        self.assertEqual(first, replay)
        options = self.service.classic_production_options(self.p, objects['shot'])
        self.assertEqual({row['document']['mode'] for row in options['drafts']}, {'single', 'text'})
        with self.assertRaises(Conflict):
            self.write('save_classic_draft', payload)
        updated = self.write('save_classic_draft', {'document': dict(single, prompt='已修改'), 'base_draft_id': first['id']})
        self.assertEqual(updated['version'], 2)
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p, second['id'])['document'])['prompt'], '另一个模式')
        other = self.service.create_project({'name':'另一项目'}, actor='test-human')['id']
        with self.assertRaises(ResourceError):
            self.service.save_classic_draft(other, payload, expected_revision=0,
                idempotency_key=uuid.uuid4().hex, actor='test-human')

    def test_fixed_draft_to_original_quote_and_unapproved_run(self):
        from vsc.assets.resource_service import Conflict
        objects, media, model = self.ready_shot()
        saved = self.write('save_classic_draft', {'document': self.document(objects['shot'], media, model), 'base_draft_id': None})
        document = json.loads(self.service.get_artifact_version(self.p, saved['id'])['document'])
        self.assertEqual(document['references'][0]['sha256'], self.service.get_media(self.p, media)['sha256'])
        request = {'draft_version_id': saved['id'], 'execution_policy': self.policy()}
        preview = self.service.preview_classic_run(self.p, request)
        self.assertTrue(preview['ready'], preview.get('gaps'))
        self.assertEqual(preview['generation_quote']['native_units']['video_seconds'], 5)
        payload = {'request': request, 'preview_sha256': preview['preview_sha256']}
        key = uuid.uuid4().hex
        run = self.write('propose_classic_run', payload, idempotency_key=key)
        artifact = self.service.get_artifact_version(self.p, run['id'])
        artifact['document'] = json.loads(artifact['document'])
        self.assertFalse(artifact['approved'])
        self.assertEqual(artifact['document']['classic_draft']['id'], saved['id'])
        self.assertEqual(artifact['document']['series_batch']['jobs'][0]['request']['first_frame_media_id'], media)
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'], 0)
        # Synthetic human approval still goes through the original run consumer.
        self.write('decide_artifact', {'artifact_id':run['id'], 'reason':'隔离测试操作者批准明确固定输入'})
        from vsc.production.bounded import preview_batch
        batch = preview_batch(self.service, self.p, {'run_version_id':run['id']})
        self.assertEqual(batch['ready_count'], 1, batch)
        self.write('create_episode_batch', {'titles':['新的集'], 'parent_id': objects['work']})
        self.assertEqual(run, self.service.propose_classic_run(self.p, payload, expected_revision=0,
            idempotency_key=key, actor='test-human'))
        with self.assertRaises(Conflict):
            self.write('propose_classic_run', dict(payload, preview_sha256='0'*64))

    def test_unavailable_modes_preserve_typed_drafts_and_fail_closed(self):
        from vsc.assets.resource_service import ResourceError
        objects, media, model = self.ready_shot()
        audio = self.media('驱动音频', modality='audio')
        doc = self.document(objects['shot'], model=model, mode='digital_human')
        doc['references'] = [{'role':'portrait', 'media_id':media}, {'role':'speech', 'media_id':audio}]
        saved = self.write('save_classic_draft', {'document':doc, 'base_draft_id':None})
        request = {'draft_version_id':saved['id'], 'execution_policy':self.policy()}
        preview = self.service.preview_classic_run(self.p, request)
        self.assertFalse(preview['ready'])
        self.assertIn('subject_selection_required', [gap['code'] for gap in preview['gaps']])
        with self.assertRaises(ResourceError):
            self.write('propose_classic_run', {'request':request, 'preview_sha256':'0'*64})
        bad = dict(doc, references=[{'role':'speech','media_id':media}])
        with self.assertRaises(ResourceError):
            self.write('save_classic_draft', {'document':bad, 'base_draft_id':saved['id']})
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p, saved['id'])['document'])['references'][1]['media_id'], audio)
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'], 0)

    def test_http_session_save_and_readback(self):
        if not all(importlib.util.find_spec(name) for name in ('fastapi','httpx')):
            self.skipTest('requires web dependencies')
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        import tempfile
        objects = self.hierarchy()
        with tempfile.TemporaryDirectory() as root:
            catalog = ResourceCatalog(root, service=self.service)
            app = create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],
                'access_token':'test','human_identity':'test-human'}, catalog=catalog)
            with TestClient(app) as client:
                path = '/api/v1/projects/'+self.p+'/classic-production'
                body = {'payload':{'document':self.document(objects['shot']), 'base_draft_id':None},
                    'expected_revision':self.rev, 'idempotency_key':uuid.uuid4().hex}
                self.assertEqual(client.post(path+'/drafts',json=body).status_code,403)
                login=client.post('/api/v1/session',json={'token':'test'},headers={'origin':'http://testserver'}).json()
                headers={'origin':'http://testserver','x-csrf-token':login['csrf_token']}
                result=client.post(path+'/drafts',json=body,headers=headers)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(client.post(path+'/drafts',json=body,headers=headers).json(),result.json())
                readback=client.get(path,params={'shot_id':objects['shot']})
                self.assertEqual(readback.status_code,200,readback.text)
                self.assertEqual(readback.json()['drafts'][0]['id'],result.json()['id'])
                self.assertIn('classic-production.js',client.get('/static/panel.js').text)
                self.assertIn('classic-production.css',client.get('/').text)

    def reference_media(self,video=False):
        import tempfile,io,subprocess
        from pathlib import Path
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage
        temp=tempfile.TemporaryDirectory(prefix='vsc-reference-edit-');self.addCleanup(temp.cleanup)
        old=self.service.storage;self.service.storage=LocalStorage(Path(temp.name)/'storage');self.addCleanup(setattr,self.service,'storage',old)
        path=Path(temp.name)/('source.mp4' if video else 'source.png')
        if video:
            result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=12:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(path)],capture_output=True,timeout=20);self.assertEqual(result.returncode,0,result.stderr)
        else:Image.new('RGB',(64,64),'blue').save(path)
        with path.open('rb') as stream:stage=self.service.storage.stage_upload(stream,path.name)
        media=self.write('register_media',{'staged_upload':stage['staged_upload'],'rights':'owned','source':{'kind':'synthetic','content':'本地合成像素'}})
        return media,self.service.storage

    def edit_document(self,media,video=False):
        return {'format':'vsc.reference-edit/v1','id':uuid.uuid4().hex,'source_media_id':media['id'],'source_sha256':media['sha256'],'source_modality':'video' if video else 'image','time_ms':500 if video else 0,'width':64,'height':64,'description':'固定区域修改','brightness':1,'saturation':1,'operations':[{'id':'rectangle','tool':'rectangle','points':[[.1,.1],[.8,.8]],'color':'#ff0000','width':.03},{'id':'mask','tool':'mask','points':[[.5,.5],[.7,.5]],'color':'#ffffff','width':.1}]}

    def test_reference_edit_real_pixels_lineage_replay_and_conflict(self):
        from PIL import Image
        from vsc.assets.resource_service import Conflict
        objects=self.hierarchy();media,storage=self.reference_media();document=self.edit_document(media);document['grid']={'rows':2,'columns':2}
        payload={'shot_id':objects['shot'],'mode':'image','document':document,'base_edit_id':None};saved=self.write('save_classic_reference_edit',payload)
        with self.assertRaises(Conflict):self.write('save_classic_reference_edit',payload)
        output=self.write('export_classic_reference_edit',{'edit_version_id':saved['id']},idempotency_key='edit-export')
        replay=self.write('export_classic_reference_edit',{'edit_version_id':saved['id']},idempotency_key='edit-export');self.assertEqual(output,replay)
        fresh=self.write('export_classic_reference_edit',{'edit_version_id':saved['id']});self.assertEqual(output['id'],fresh['id'])
        self.assertEqual(len([r for r in output['outputs'] if r['role'].startswith('tile-')]),4)
        by_role={r['role']:r for r in output['outputs']};annotation=self.service.get_media(self.p,by_role['annotation']['media_id']);mask=self.service.get_media(self.p,by_role['mask']['media_id'])
        image=Image.open(storage.verify(annotation['locations'][0]['object_key'],annotation['sha256']));mask_image=Image.open(storage.verify(mask['locations'][0]['object_key'],mask['sha256']))
        self.assertGreater(image.getpixel((6,6))[0],200);self.assertGreater(image.getpixel((0,0))[2],200);self.assertGreater(mask_image.getpixel((32,32)),200);self.assertEqual(mask_image.getpixel((0,0)),0)
        lineage=self.service.get_media_lineage(self.p,annotation['id']);self.assertTrue(any(i['media_id']==media['id'] for i in lineage['inputs']),lineage)
        doc=self.document(objects['shot'],mode='image');doc['purpose']='image_edit';doc['references']=[{'role':'reference_image','media_id':annotation['id'],'annotation_id':output['id'],'annotation_source_id':media['id']}]
        ref=self.write('save_classic_draft',{'document':doc,'base_draft_id':None});self.assertEqual(json.loads(self.service.get_artifact_version(self.p,ref['id'])['document'])['references'][0]['sha256'],annotation['sha256'])
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_video_annotation_pins_time_and_rejects_outside_or_foreign_source(self):
        from PIL import Image
        from vsc.assets.resource_service import ResourceError
        objects=self.hierarchy();media,storage=self.reference_media(video=True);doc=self.edit_document(media,True)
        saved=self.write('save_classic_reference_edit',{'shot_id':objects['shot'],'mode':'omni','document':doc,'base_edit_id':None});output=self.write('export_classic_reference_edit',{'edit_version_id':saved['id']});self.assertEqual(output['time_ms'],500)
        row=self.service.get_media(self.p,output['outputs'][0]['media_id']);pixels=Image.open(storage.verify(row['locations'][0]['object_key'],row['sha256']));self.assertGreater(pixels.getpixel((0,0))[2],200)
        for bad in [dict(doc,time_ms=3000),dict(doc,source_sha256='0'*64),dict(doc,source_media_id=str(uuid.uuid4()))]:
            with self.assertRaises(ResourceError):self.write('save_classic_reference_edit',{'shot_id':objects['shot'],'mode':'omni','document':bad,'base_edit_id':saved['id']})

    def test_image_tools_fixed_semantic_request_and_required_native_capabilities(self):
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        objects,media,_=self.ready_shot();preset=next(r for r in PRESETS if r['id']=='xai-grok-imagine-image');payload={k:v for k,v in preset.items() if k not in {'id','label'}};payload.update(enabled=True,model_version='offline-image-tools')
        model=ResourceSettings(self.store).save(payload,'test-human')['id']
        doc=self.document(objects['shot'],model=model,mode='image_angle');doc.update(purpose='image_edit',tool_settings={'yaw':37,'pitch':12,'zoom':1.5},references=[{'role':'reference_image','media_id':media}])
        saved=self.write('save_classic_draft',{'document':doc,'base_draft_id':None});preview=self.service.preview_classic_run(self.p,{'draft_version_id':saved['id'],'execution_policy':self.policy()});self.assertTrue(preview['ready'],preview)
        job=preview['artifact']['document']['series_batch']['jobs'][0];self.assertEqual(job['request']['reference_media_ids'],[media]);self.assertIn('37',job['request']['prompt']);self.assertIn('12',job['request']['prompt'])
        for tool in ['three_view','face_views','headshot','texture','expression','lighting']:
            typed=dict(doc,mode='image_'+tool,tool_settings={});version=self.write('save_classic_draft',{'document':typed,'base_draft_id':None});value=self.service.preview_classic_run(self.p,{'draft_version_id':version['id'],'execution_policy':self.policy()});self.assertTrue(value['ready'],value);self.assertEqual(value['artifact']['document']['series_batch']['jobs'][0]['request']['reference_media_ids'],[media])
        for mode in ['image_panorama','image_upscale','image_watermark']:
            blocked=dict(doc,mode=mode,tool_settings={},references=[{'role':'operation_source','media_id':media}]);version=self.write('save_classic_draft',{'document':blocked,'base_draft_id':None});value=self.service.preview_classic_run(self.p,{'draft_version_id':version['id'],'execution_policy':self.policy()});self.assertFalse(value['ready']);self.assertIn('inpaint_inputs_required' if mode=='image_watermark' else 'model_capability_mismatch',[g['code'] for g in value['gaps']])
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_classic_shot_creation_sparse_reordering_and_candidate_configuration_scope(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        objects=self.hierarchy();first=objects['shot']
        with self.engine.begin() as conn:conn.execute(update(S.shots).where(S.shots.c.project_id==self.p,S.shots.c.id==first).values(ordinal=100))
        second=self.write('change_classic_shots',{'action':'create','parent_id':objects['sequence'],'title':'下一镜'})['id']
        self.write('change_classic_shots',{'action':'reorder','parent_id':objects['sequence'],'shot_ids':[second,first]})
        options=self.service.classic_production_options(self.p,first);self.assertEqual([r['id'] for r in options['sibling_shots']],[second,first])
        with self.assertRaises(ResourceError):self.write('change_classic_shots',{'action':'reorder','parent_id':objects['sequence'],'shot_ids':[first]})
        media=self.media();self.assertFalse(self.service.classic_candidate_configuration(self.p,first,media)['available'])

    def test_candidate_configuration_uses_same_shot_original_job_and_fixed_references(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.seed_generation_timeline_render()
        with self.engine.connect() as conn:
            job=conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).mappings().one()
            media=conn.execute(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==self.p,S.job_outputs.c.job_id==job['id'])).scalar_one()
            parent=conn.execute(select(S.shots.c.parent_id).where(S.shots.c.project_id==self.p,S.shots.c.id==job['shot_id'])).scalar_one()
        value=self.service.classic_candidate_configuration(self.p,job['shot_id'],media)
        self.assertTrue(value['available']);self.assertEqual(value['source_job_id'],job['id']);self.assertEqual(value['document']['prompt'],job['request_payload']['prompt']);self.assertEqual(value['document']['params'],job['request_payload']['params']);self.assertEqual(value['document']['references'][0]['media_id'],job['request_payload']['first_frame_media_id']);self.assertEqual(len(value['document']['references'][0]['sha256']),64)
        other=self.write('change_classic_shots',{'action':'create','parent_id':parent,'title':'禁止跨镜配置猜测'})['id']
        self.assertFalse(self.service.classic_candidate_configuration(self.p,other,media)['available'])

    def test_ordinary_omni_candidate_restores_fixed_draft_without_new_generation(self):
        """Reading ordinary omni output retains its fixed mode and parameters, without new jobs."""
        objects, first, model = self.ready_shot()
        second = self.media("第二张固定参考")
        document = dict(shot_id=objects["shot"], mode="omni", model_id=model, purpose="reference_to_video", prompt="保留普通全能参考原配置",
            width=1080, height=1920, duration_ms=5000, count=2, params={"seed":314, "generate_audio":False},
            references=[{"role":"reference_image","media_id":first}, {"role":"reference_image","media_id":second}])
        draft = self.write("save_classic_draft", {"document":document, "base_draft_id":None})
        expected = json.loads(self.service.get_artifact_version(self.p,draft["id"])["document"])
        policy = dict(self.policy(), authorization={"mode":"new_batch", "reason":"隔离固定候选种子，无供应商执行"})
        request = dict(draft_version_id=draft["id"], execution_policy=policy)
        quote = self.service.preview_workbench_generation(self.p, request)
        self.assertTrue(quote["ready"], quote)
        # The fixture has no execution runtime. This records normal run/job intent only.
        generated = self.write("generate_workbench", {"request":request, "preview_sha256":quote["preview_sha256"]})
        job = generated["jobs"][0]
        self.write("update_generation_job", {"job_id":job["id"], "status":"submitted", "external_task_id":"offline-fixed-omni"})
        import io
        import shutil
        import tempfile
        from pathlib import Path
        from support.fixtures.media import production_media
        from vsc.adapters.storage.local.store import LocalStorage
        if not shutil.which('ffmpeg'):
            self.skipTest('requires FFmpeg for a real output duration')
        storage_temp = tempfile.TemporaryDirectory(prefix='vsc-classic-config-output-')
        self.addCleanup(storage_temp.cleanup)
        previous_storage = self.service.storage
        self.addCleanup(setattr, self.service, 'storage', previous_storage)
        self.service.storage = LocalStorage(Path(storage_temp.name)/'storage')
        staged = self.service.storage.stage_upload(io.BytesIO(production_media()['mp4']), 'offline-config-output.mp4')
        output = self.write('register_media', {'staged_upload':staged['staged_upload'], 'name':'离线候选输出', 'rights':'owned',
            'source':{'kind':'synthetic','content':'本地真实字节 API 回归视频，无供应商调用'}})['id']
        self.write("update_generation_job", {"job_id":job["id"], "status":"succeeded", "outputs":[{"media_id":output}]})
        before_jobs, before_revision = self.service.list_generation_jobs(self.p)["total"], self.service.get_project(self.p)["revision"]
        for _ in range(2):
            restored = self.service.classic_candidate_configuration(self.p, objects["shot"], output)
            self.assertTrue(restored["available"])
            self.assertEqual(restored["configuration_source"], "fixed_workbench_draft")
            self.assertEqual(restored["source_job_id"], job["id"])
            self.assertEqual(restored["document"], expected)
        self.assertEqual(self.service.list_generation_jobs(self.p)["total"], before_jobs)
        self.assertEqual(self.service.get_project(self.p)["revision"], before_revision)
        self.assertEqual(json.loads(self.service.get_artifact_version(self.p,draft["id"])["document"]), expected)


class ClassicProductionFrontendTests(unittest.TestCase):
    def test_first_shot_creation_resumes_group_after_reload(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node')
        source = r"""
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');
globalThis.Option=function(label,value){const n=document.createElement('option');n.textContent=label;n.value=value;return n;};
const storage=new Map();globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
Object.defineProperty(Element.prototype,'isConnected',{get(){return !!this.parentElement;}});
Element.prototype.showModal=function(){this.open=true;};Element.prototype.close=function(){this.open=false;this.dispatch('close');};
const root=document.createElement('section');document.body.append(root);
const {createClassicProduction}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/classic-production.js'));
const objects=[],attempts=[],receipts=new Map(),notices=[],opened=[];let revision=1,loseSequence=true;
const api=async(url,opts)=>{
 if(url.endsWith('/tree'))return {revision,nodes:[{id:'episode',kind:'episode'},...objects]};
 if(url.endsWith('/objects')){const request=JSON.parse(opts.body);attempts.push(request);if(receipts.has(request.idempotency_key))return receipts.get(request.idempotency_key);
   const row={...request.payload,revision:++revision};objects.push(row);receipts.set(request.idempotency_key,row);if(row.kind==='sequence'&&loseSequence){loseSequence=false;throw new Error('lost sequence receipt');}return row;}
 if(url.includes('section=shots'))return {scope:{kind:'episode',id:'episode'},ancestors:[],sections:{shots:{items:objects.filter(row=>row.kind==='shot')}}};
 if(url.includes('classic-production?'))return {shot:objects.find(row=>row.kind==='shot'),sibling_shots:objects.filter(row=>row.kind==='shot'),revision,drafts:[],models:[],media:[],modes:{image:{label:'分镜图像',modality:'image',slots:{reference_image:'image'}}}};
 if(url.includes('/execution-authorizations'))return {items:[]};return {sections:{candidates:{items:[]}}};
};
const ctx={api,session:()=>({actor:'operator',csrf:'csrf',writable:true,revision}),setRevision:value=>revision=value,notice:value=>notices.push(value),onShot:(...args)=>opened.push(args),navigate(){},media(){}};
const button=title=>root.querySelectorAll('button').find(row=>row.textContent===title),control=label=>root.querySelectorAll('input').find(row=>row.getAttribute('aria-label')===label);
let app=createClassicProduction(root,ctx);await app.load({projectId:'project',episodeId:'episode',productionKind:'image'});
assert.ok(root.querySelector('.classic-layout'));await button('＋新增分镜').click();
control('镜组名称').value='保留的镜组名称';await control('镜组名称').dispatch('input');await root.querySelector('form').dispatch('submit');
assert.equal(objects.length,2);assert.ok(root.textContent.includes('lost sequence receipt'));assert.equal(storage.size,1);app.suspend();
// Recreating the controller models a refreshed page: the original Map is gone.
app=createClassicProduction(root,ctx);await app.load({projectId:'project',episodeId:'episode',productionKind:'image'});await button('＋新增分镜').click();
assert.equal(control('镜组名称').value,'保留的镜组名称');await root.querySelector('form').dispatch('submit');
assert.deepEqual(objects.map(row=>row.kind),['scene','sequence','shot']);assert.equal(attempts[1].idempotency_key,attempts[2].idempotency_key);assert.deepEqual(attempts[1],attempts[2]);
assert.equal(storage.size,0);assert.deepEqual(opened.at(-1),[objects[2].id,'episode']);assert.ok(root.textContent.includes('生成分镜方式'));app.suspend();
"""
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mode_buffers_stable_retries_and_old_scope_responses(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node')
        source = r"""
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');
globalThis.Option=function(label,value){const n=document.createElement('option');n.textContent=label;n.value=value;return n;};
Element.prototype.contains=function(node){while(node){if(node===this)return true;node=node.parentElement;}return false;};
const root=document.createElement('section'),notes=[],writes=[];
const module=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/classic-production.js'));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const late=deferred();let count=0,revision=5;
const fixture=shot=>({shot:{id:shot,title:shot},revision:5,drafts:[],models:[],media:[],media_total:0,modes:{
 image:{label:'分镜图像',modality:'image',slots:{reference_image:'image'}},
 single:{label:'单图生视频',modality:'video',slots:{first_frame:'image'}},
 text:{label:'文生视频',modality:'video',slots:{}}
}});
const api=async(url,opts)=>{
 if(opts?.method==='POST'){writes.push(JSON.parse(opts.body));count++;if(count===1)throw new Error('lost response');if(count===3)return late.promise;return {id:'saved',revision:6,version:1};}
 if(url.includes('section=shots'))return {scope:{kind:'shot',id:url.includes('other')?'other':'shot'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:[{id:url.includes('other')?'other':'shot',title:'shot'}]}}};
 if(url.includes('classic-production?'))return fixture(url.includes('other')?'other':'shot');
 if(url.includes('/execution-authorizations'))return {items:[]};
 return {sections:{candidates:{items:[]}}};
};
const app=module.createClassicProduction(root,{api,session:()=>({actor:'human',csrf:'x',revision,writable:true}),setRevision:v=>revision=v,notice:v=>notes.push(v),onShot(){},navigate(){},media(){},openArtifact(){}});
const button=name=>root.querySelectorAll('button').find(row=>row.textContent===name||row.getAttribute('aria-label')===name);
await app.load({projectId:'p',objectId:'shot'});
let form=root.querySelector('form'),prompt=form.querySelector('textarea');prompt.value='单图草稿';await form.dispatch('input',{target:prompt});
await button('文生视频').click();form=root.querySelector('form');prompt=form.querySelector('textarea');prompt.value='文生草稿';await form.dispatch('input',{target:prompt});
await button('单图生视频').click();form=root.querySelector('form');assert.equal(form.querySelector('textarea').value,'单图草稿');
await form.dispatch('submit');assert.ok(notes.at(-1).includes('lost response'));
await form.dispatch('submit');assert.equal(writes[0].idempotency_key,writes[1].idempotency_key);assert.equal(writes[0].expected_revision,5);
prompt=form.querySelector('textarea');prompt.value='待保存旧镜头';await form.dispatch('input',{target:prompt});
const save=form.dispatch('submit');await Promise.resolve();await app.load({projectId:'p',objectId:'other'});
const noteCount=notes.length;late.reject(new Error('old failure'));await save;
assert.equal(notes.length,noteCount);assert.ok(!root.textContent.includes('old failure'));assert.equal(root.querySelector('textarea').value,'');app.suspend();
// Image and video entries share persistence but show only their own controls.
await app.load({projectId:'p',objectId:'shot',productionKind:'image'});
assert.ok(root.textContent.includes('生成分镜方式'));assert.equal(button('文生视频'),undefined);
await app.load({projectId:'p',objectId:'shot',productionKind:'video'});
assert.ok(root.textContent.includes('生成视频方式'));assert.equal(button('分镜图像'),undefined);app.suspend();
// The compact preview action must save successfully before quoting fixed input.
let failDraft=true,previewCalls=0;const attempts=[];
const compact=module.createClassicProduction(root,{api:async(url,opts)=>{
 if(url.endsWith('/drafts')){attempts.push(JSON.parse(opts.body));if(failDraft){failDraft=false;throw new Error('save unavailable');}}
 if(url.endsWith('/quote')){previewCalls++;return {revision:6,ready:false,gaps:[]};}
 return api(url,opts);
},session:()=>({actor:'human',csrf:'x',revision,writable:true}),setRevision:v=>revision=v,notice:v=>notes.push(v),navigate(){},media(){},openArtifact(){}});
await compact.load({projectId:'compact',objectId:'shot'});
form=root.querySelector('form');prompt=form.querySelector('textarea');prompt.value='预览前必须保存';await form.dispatch('input',{target:prompt});
await button('生成').click();assert.equal(previewCalls,0);assert.equal(prompt.value,'预览前必须保存');
await button('生成').click();assert.equal(previewCalls,1);assert.equal(attempts[0].idempotency_key,attempts[1].idempotency_key);compact.suspend();
console.log('PASS mode buffers, idempotent retry and old write isolation');
"""
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_catalog_reuse_preserves_drafts_cancel_scope_permissions_and_searchable_models(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node')
        source = r"""
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');
Element.prototype.contains=function(node){while(node){if(node===this)return true;node=node.parentElement;}return false;};
const storage=new Map();let failStorage=false;globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>{if(failStorage)throw new Error('quota');storage.set(k,v);},removeItem:k=>storage.delete(k)};
const root=document.createElement('section');document.body.append(root);
const {createClassicProduction}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/classic-production.js'));
const notes=[],posts=[],reuseReads=[],gates=new Map();let writable=true,revision=5;
const clone=v=>JSON.parse(JSON.stringify(v)),sha='a'.repeat(64),media=[{id:'image',modality:'image',sha256:sha,name:'图片'},{id:'video',modality:'video',sha256:sha,name:'视频'},{id:'audio',modality:'audio',sha256:sha,name:'音频'}];
const original=shot=>({shot_id:shot,mode:'omni',model_id:'model-a',purpose:'reference_to_video',prompt:shot==='shot'?'原保存稿':'另一镜头原稿',duration_ms:5000,width:1080,height:1920,count:1,params:{seed:9},references:[]});
const reused=shot=>({shot_id:shot,mode:'omni',model_id:'model-b',purpose:'reference_to_video',prompt:'来自原候选的完整配置',duration_ms:8000,width:1280,height:720,count:2,params:{seed:314,resolution:'720p',generate_audio:false},references:media.map(row=>({role:'reference_'+row.modality,media_id:row.id,sha256:sha}))});
const configured=shot=>({available:true,configuration_source:'fixed_workbench_draft',source_job_id:'fixed-job',document:reused(shot)});
const rows=[{id:'shot',parent_id:'group',title:'当前镜头'},{id:'other',parent_id:'group',title:'另一镜头'}];
const models=['model-a','model-b'].map((id,index)=>({id,name:index?'secondary connection':'primary connection',model_key:'grok-imagine-video-1.5',model_version:'fixed-'+index,modality:'video',enabled:true,adapter_available:true,capabilities:{purposes:['reference_to_video','text_to_video'],max_duration_ms:10000},default_params:{resolution:'720p',generate_audio:true}}));
const api=async(url,opts)=>{
 const query=new URL(url,'http://fixture').searchParams;
 if(opts?.method==='POST'){const body=JSON.parse(opts.body);posts.push({url,body});return {id:'saved-next',sha256:sha,version:2,revision:++revision};}
 if(url.includes('section=shots')){const shot=query.get('object_id')||'shot';return {scope:{kind:'shot',id:shot},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:rows}}};}
 if(url.includes('/candidate-configuration?')){const id=query.get('media_id'),shot=query.get('shot_id');reuseReads.push({id,shot});if(gates.has(id))return gates.get(id).promise;if(id==='forbidden')throw Object.assign(new Error('无权读取此候选'),{status:403});if(id==='unavailable')return {available:false,reason:'没有原生成配置'};if(id==='wrong-shot')return configured('foreign');return configured(shot);}
 if(url.includes('/classic-production?')){const shot=query.get('shot_id');return {shot:rows.find(row=>row.id===shot),sibling_shots:rows,revision,drafts:[{id:'saved-'+shot,sha256:sha,version:1,document:original(shot)}],models,media,media_total:media.length,modes:{omni:{modality:'video',slots:{reference_image:'image',reference_video:'video',reference_audio:'audio'},purpose:'reference_to_video'},text:{modality:'video',slots:{}},single:{modality:'video',slots:{first_frame:'image'}},image:{modality:'image',slots:{reference_image:'image'}}}};}
 if(url.includes('/working-candidates?'))return {items:[{media_id:query.get('shot_id')+'-'+query.get('output_kind'),name:'真实已选结果',selected:true,sha256:sha}],total:1,next_offset:null};
 if(url.includes('/working-selections?'))return {items:rows.flatMap(row=>['image','video'].map(kind=>({shot_id:row.id,output_kind:kind,media_id:row.id+'-'+kind}))),revision};
 if(url.includes('/media/')){const id=url.split('/media/')[1];return {id,name:'真实选取媒体',sha256:sha,modality:id.endsWith('-video')?'video':'image'};}
 return {items:[],total:0};
};
const ctx={api,session:()=>({actor:'human',identityId:'human',writable,csrf:'x',revision}),setRevision:v=>revision=v,notice:value=>notes.push(String(value)),navigate(){},media(){}};
let app=createClassicProduction(root,ctx);const scope={projectId:'p',objectId:'shot',productionKind:'video',mode:'omni'};
const button=name=>root.querySelectorAll('button').find(node=>node.textContent===name||node.getAttribute('aria-label')===name),prompt=()=>root.querySelector('form').querySelector('textarea');
const edit=async text=>{prompt().value=text;await root.querySelector('form').dispatch('input',{target:prompt()});};
const ticks=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const gate=id=>{let resolve;const promise=new Promise(done=>resolve=done);const value={promise,resolve};gates.set(id,value);return value;};
await app.load(scope);await edit('原稿的未保存修改');await app.load({...scope,reuseMediaId:'output'});
assert.equal(prompt().value,'来自原候选的完整配置');assert.equal(root.querySelectorAll('.classic-reference-thumb').length,3);assert.equal(posts.length,0);
let params=root.querySelectorAll('textarea').find(node=>node.getAttribute('aria-label')?.includes('模型参数'));assert.deepEqual(JSON.parse(params.value),reused('shot').params);
assert.equal(root.querySelector('.classic-shot-rail').querySelector('video').dataset.mediaId,'shot-video');
await edit('复用后的后续修改');app.suspend();app=createClassicProduction(root,ctx);await app.load({...scope,reuseMediaId:'output'});
assert.equal(prompt().value,'复用后的后续修改');await app.load({...scope,reuseMediaId:'second-output'});assert.equal(prompt().value,'来自原候选的完整配置');await button('还原原草稿').click();assert.equal(prompt().value,'复用后的后续修改');await button('还原原草稿').click();assert.equal(prompt().value,'原稿的未保存修改');
params=root.querySelectorAll('textarea').find(node=>node.getAttribute('aria-label')?.includes('模型参数'));assert.deepEqual(JSON.parse(params.value),{seed:9});assert.equal(posts.length,0);
const search=root.querySelector('.classic-model-picker').querySelector('input'),beforeSearch=JSON.stringify([...storage]);search.value='secondary';await search.dispatch('input');await root.querySelector('form').dispatch('input',{target:search});
assert.equal(JSON.stringify([...storage]),beforeSearch);const choices=root.querySelector('.classic-model-choices').querySelectorAll('button');assert.equal(choices.length,1);assert.equal(choices[0].dataset.modelId,'model-b');await choices[0].click();
await root.querySelector('form').dispatch('submit');assert.equal(posts.length,1);assert.equal(posts[0].body.payload.base_draft_id,'saved-shot');assert.equal(posts[0].body.payload.document.model_id,'model-b');assert.equal(posts[0].body.payload.document.prompt,'原稿的未保存修改');assert.deepEqual(posts[0].body.payload.document.params,{seed:9});
let delayed=gate('late'),pending=app.load({...scope,reuseMediaId:'late'});await ticks();await app.load({...scope,objectId:'other'});delayed.resolve(configured('shot'));await pending;assert.equal(prompt().value,'另一镜头原稿');assert.equal(root.querySelector('.classic-shot-rail').querySelector('video').dataset.mediaId,'shot-video');
delayed=gate('cancel');pending=app.load({...scope,objectId:'other',reuseMediaId:'cancel'});await ticks();await button('取消').click();delayed.resolve(configured('other'));await pending;assert.equal(prompt().value,'另一镜头原稿');assert.ok(notes.at(-1).includes('已取消'));
delayed=gate('edited');pending=app.load({...scope,objectId:'other',reuseMediaId:'edited'});await ticks();await edit('等待期间的新修改');delayed.resolve(configured('other'));await pending;assert.equal(prompt().value,'等待期间的新修改');assert.ok(notes.at(-1).includes('输入已改变'));
for(const id of ['forbidden','unavailable','wrong-shot']){await app.load({...scope,objectId:'other',reuseMediaId:id});assert.equal(prompt().value,'等待期间的新修改');}
writable=false;const readsBefore=reuseReads.length;await app.load({...scope,objectId:'other',reuseMediaId:'output'});assert.equal(reuseReads.length,readsBefore);assert.equal(prompt().value,'等待期间的新修改');assert.ok(notes.at(-1).includes('只读'));
writable=true;failStorage=true;await app.load({...scope,objectId:'other',reuseMediaId:'output'});assert.equal(prompt().value,'等待期间的新修改');assert.ok(notes.at(-1).includes('无法保留原草稿'));failStorage=false;await button('重试读取配置').click();assert.equal(prompt().value,'来自原候选的完整配置');await button('还原原草稿').click();assert.equal(prompt().value,'等待期间的新修改');
assert.equal(posts.length,1);assert.ok(posts.every(row=>row.url.endsWith('/drafts')));app.suspend();
console.log('PASS catalog reuse, full params/references, original draft restore, repeated open, cancellation, changed inputs, stale scope, permissions, thumbnails, searchable models, no implicit writes');
"""
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frame_library_uses_project_media_and_recovers_the_same_request(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node')
        source = r"""
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');
globalThis.Option=function(label,value){const n=document.createElement('option');n.textContent=label;n.value=value;return n;};
const storage=new Map();globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
Object.defineProperty(Element.prototype,'isConnected',{get(){return !!this.parentElement;}});
Element.prototype.showModal=function(){this.open=true;};Element.prototype.close=function(){this.open=false;this.dispatch('close');};
const root=document.createElement('section');document.body.append(root);
const {createClassicProduction}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/classic-production.js'));
const sha='a'.repeat(64),posts=[],notes=[];let revision=4,lose=true;
const modes={first_last:{label:'首尾帧',modality:'video',slots:{first_frame:'image',last_frame:'image'}},multi:{label:'多图参考',modality:'video',slots:{first_frame:'image',reference_image:'image'}}};
const api=async(url,opts)=>{
 if(url==='/api/v1/projects')return [{id:'p',name:'当前项目'},{id:'other',name:'其他项目'}];
 if(url.includes('/asset-cards?')){const project=url.split('/projects/')[1].split('/')[0];
  if(project==='other')return {items:[{id:'station',name:'第2集-站位图2',record_kind:'blocking',preview:{media_id:'src-media'},source:{workflow_id:'w',version_id:'v',episode_id:'e',unit_key:'station',media_id:'src-media',spatial_export_id:null},forms:[]}]};
  return {items:[{id:'local-card',name:'本项目图',record_kind:'asset',forms:[{name:'默认',media_id:'local-media',version_id:'form-1'}]}]};}
 if(url.includes('/media/')&&!url.includes('/content'))return {id:url.split('/media/')[1],name:'本项目图',sha256:sha,modality:'image'};
 if(opts?.method==='POST'&&url.endsWith('/classic-production/frame-media')){const body=JSON.parse(opts.body);posts.push(body);if(lose){lose=false;throw new Error('lost frame receipt');}
  return {media_id:'copied-'+body.payload.role,sha256:sha,name:'第2集-站位图2',modality:'image',role:body.payload.role,shot_id:body.payload.shot_id,source_project_id:body.payload.source_project_id,source_media_id:body.payload.source.media_id,revision:++revision};}
 if(url.includes('section=shots'))return {scope:{kind:'shot',id:'shot'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:[{id:'shot',title:'第2集'}]}}};
 if(url.includes('/classic-production?'))return {shot:{id:'shot',title:'第2集',parent_id:'group'},sibling_shots:[{id:'shot',title:'第2集'}],revision,drafts:[],models:[],media:[{id:'local-media',name:'本项目图',modality:'image'}],media_total:1,modes};
 if(url.includes('/execution-authorizations'))return {items:[]};
 if(url.includes('/working-candidates'))return {items:[],total:0};
 return {items:[],total:0};
};
const ctx={api,session:()=>({actor:'human',csrf:'x',revision,writable:true}),setRevision:value=>revision=value,notice:value=>notes.push(String(value)),onShot(){},navigate(){},media(){}};
const buttonIn=(node,title)=>[...node.querySelectorAll('button')].find(row=>row.textContent===title);
const slot=role=>[...root.querySelectorAll('.classic-reference-slot')].find(node=>node.dataset.role===role);
let app=createClassicProduction(root,ctx);
await app.load({projectId:'p',objectId:'shot',shotId:'shot',productionKind:'video',mode:'first_last'});
await buttonIn(slot('first_frame'),'资料库').click();
const opened=root.querySelector('.classic-frame-library');
assert.equal(opened.getAttribute('aria-label'),'资料库');
assert.ok(buttonIn(opened,'本项目图'),'library text: '+opened.textContent);
await buttonIn(opened,'本项目图').click();
assert.equal(posts.length,0);assert.equal(root.querySelector('.classic-frame-library'),null);
assert.ok(slot('first_frame').querySelector('img').src.includes('/projects/p/media/local-media/content'));
await buttonIn(slot('first_frame'),'资料库').click();
const dialog=root.querySelector('.classic-frame-library'),project=dialog.querySelector('select');
project.value='other';await project.dispatch('change');
await buttonIn(dialog,'第2集-站位图2').click();
assert.equal(posts.length,1);assert.equal(posts[0].payload.role,'first_frame');assert.equal(posts[0].payload.source.kind,'blocking');
assert.equal(posts[0].payload.source.spatial_export_id,null);assert.ok(dialog.textContent.includes('lost frame receipt'));
assert.ok([...storage.keys()].some(key=>key.includes('vsc-classic-request:')));
app.suspend();app=createClassicProduction(root,ctx);
await app.load({projectId:'p',objectId:'shot',shotId:'shot',productionKind:'video',mode:'first_last'});
await buttonIn(root,'恢复上次请求').click();
assert.equal(posts.length,2);assert.equal(posts[0].idempotency_key,posts[1].idempotency_key);
assert.ok(slot('first_frame').querySelector('img').src.includes('/media/copied-first_frame/content'));
assert.equal(root.querySelector('.classic-frame-library'),null);
await buttonIn(slot('last_frame'),'资料库').click();
const again=root.querySelector('.classic-frame-library');again.querySelector('select').value='other';await again.querySelector('select').dispatch('change');
await buttonIn(again,'第2集-站位图2').click();
assert.equal(posts.length,3);assert.equal(posts[2].payload.role,'last_frame');assert.equal(posts[2].payload.source_project_id,'other');
assert.ok(slot('last_frame').querySelector('img').src.includes('/media/copied-last_frame/content'));
assert.ok(!posts.some(row=>String(row.url||'').includes('/drafts')));
const modeButton=name=>[...root.querySelectorAll('button')].find(row=>row.getAttribute('aria-label')===name);
await modeButton('多图参考').click();await buttonIn(slot('first_frame'),'资料库').click();
assert.equal(root.querySelector('.classic-frame-library'),null);app.suspend();
console.log('PASS classic frame library project switch and request recovery');
"""
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
