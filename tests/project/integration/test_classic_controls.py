"""D06 controls consume real PostgreSQL, original identities, artifacts, and image bytes."""
import base64
import io
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ClassicControlsTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.assets.access_control import Principal, set_principal, reset_principal
        self.owner = self.service.ensure_local_access('test-human')
        self.token = set_principal(Principal(**self.owner))
        self.addCleanup(reset_principal, self.token)
        self.addCleanup(lambda: self.service.__dict__.pop('prompt_assistant', None))

    def local_media(self, name='用户上传.png', kind='user_upload'):
        from PIL import Image
        from vsc.adapters.storage.local.store import LocalStorage
        if self.service.storage is None:
            tmp = tempfile.TemporaryDirectory(prefix='vsc-classic-controls-')
            self.addCleanup(tmp.cleanup)
            self.service.storage = LocalStorage(Path(tmp.name)/'storage')
            self.addCleanup(setattr, self.service, 'storage', None)
        output = io.BytesIO(); Image.new('RGB', (32, 48), (12, 34, 56)).save(output, format='PNG'); output.seek(0)
        staged = self.service.storage.stage_upload(output, name)
        return self.write('register_media', dict(staged_upload=staged['staged_upload'], name=name, rights='owned',
            source={'kind': kind, 'content': '隔离用户上传证据'}))

    def favorite(self, media_id, active=True, version=0, key=None):
        return self.service.favorite_classic_media(self.p, dict(media_id=media_id, active=active, base_version=version),
            actor='test-human', expected_revision=self.rev, idempotency_key=key or uuid.uuid4().hex)

    def prompt_draft(self):
        objects = self.hierarchy(); media = self.local_media()
        document = dict(shot_id=objects['shot'], mode='image', model_id='', purpose='first_frame', prompt='窗边一只蓝色杯子',
            width=1024, height=1024, duration_ms=5000, count=1, params={},
            references=[{'role':'reference_image','media_id':media['id']}])
        draft = self.write('save_classic_draft', {'document': document, 'base_draft_id': None})
        request = dict(draft_version_id=draft['id'], draft_sha256=draft['sha256'], operation='recognize', target_language='en', include_references=True)
        return objects, media, document, draft, request

    def test_favorites_identity_paging_replay_conflict_and_no_creative_revision(self):
        from sqlalchemy import select, update, insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.access_control import Principal, set_principal, reset_principal
        from vsc.assets.resource_service import Conflict, ResourceError
        objects=self.hierarchy(); first=self.local_media(); other=self.local_media('第二张.png')
        self.candidate(objects['shot'], first['id']); self.candidate(objects['shot'], other['id'])
        revision=self.rev; key=uuid.uuid4().hex
        initial=self.favorite(first['id'], key=key)
        self.assertEqual(initial['version'],1)
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        page=self.service.list_working_candidates(self.p,objects['shot'],'image',filter_kind='favorites',limit=1)
        self.assertEqual((page['total'],page['items'][0]['media_id']), (1,first['id']))
        self.favorite(other['id']); page=self.service.list_working_candidates(self.p,objects['shot'],'image',filter_kind='favorites',limit=1)
        self.assertEqual((page['total'],page['next_offset']),(2,1))
        self.favorite(first['id'],False,1)
        self.assertEqual(self.favorite(first['id'],key=key), initial)
        with self.assertRaises(Conflict): self.favorite(first['id'],True,1)
        self.assertEqual(self.service.list_working_candidates(self.p,objects['shot'],'image',filter_kind='favorites')['total'],1)
        self.assertEqual(self.service.get_project(self.p)['revision'], revision)
        second=self.service.ensure_local_access('other-human');token=set_principal(Principal(**second))
        try:
            self.assertEqual(self.service.list_working_candidates(self.p,objects['shot'],'image',filter_kind='favorites')['total'],0)
            with self.assertRaises(ResourceError): self.favorite(other['id'])
        finally: reset_principal(token)
        with self.engine.connect() as conn:
            row=conn.execute(select(S.classic_media_favorites).where(S.classic_media_favorites.c.project_id==self.p,S.classic_media_favorites.c.media_id==first['id'])).mappings().one()
        with self.assertRaises(IntegrityError) as failure:
            with self.engine.begin() as conn: conn.execute(update(S.classic_media_favorites).where(S.classic_media_favorites.c.id==row['id']).values(media_id=other['id'],version=row['version']+1))
        self.assertEqual(failure.exception.orig.sqlstate,'23514')
        foreign=self.service.create_project({'name':'另一个项目'},actor='test-human')['id']
        with self.assertRaises(IntegrityError) as failure:
            with self.engine.begin() as conn: conn.execute(insert(S.classic_media_favorites).values(id=str(uuid.uuid4()),project_id=foreign,media_id=first['id'],identity_id=self.owner['identity_id'],version=1,active=True))
        self.assertEqual(failure.exception.orig.sqlstate,'23503')

    def ready_video(self):
        from datetime import datetime, timedelta, timezone
        from vsc.production.resource_settings import ResourceSettings, PRESETS
        objects = self.hierarchy(); reference = self.media('候选过滤的固定首帧')
        preset = next(item for item in PRESETS if item['id'] == 'xai-grok-imagine-video')
        model = ResourceSettings(self.store).save(dict({k: v for k, v in preset.items() if k not in {'id', 'label'}},
            enabled=True, model_version='isolated-d06-filter'), 'test-human')
        draft = self.write('save_classic_draft', {'base_draft_id': None, 'document': dict(
            shot_id=objects['shot'], mode='single', model_id=model['id'], purpose='image_to_video',
            prompt='隔离候选过滤测试', count=1, duration_ms=5000, references=[{'role':'first_frame','media_id':reference}])})
        now = datetime.now(timezone.utc)
        return objects, dict(draft_version_id=draft['id'], execution_policy=dict(version='bounded-v1',
            first_draft_due_at=(now+timedelta(minutes=10)).isoformat(), stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),
            max_attempts_per_purpose=2, max_repair_rounds=0,
            authorization={'mode':'new_batch','reason':'隔离验证用户明确生成一次'}))

    def test_local_filter_uses_original_sources_and_excludes_generated_outputs(self):
        objects, request = self.ready_video()
        local = self.media('local-looking.mp4', modality='video')
        self.candidate(objects['shot'],local,role='video_take')
        self.assertEqual(self.service.list_working_candidates(self.p,objects['shot'],'video',filter_kind='local')['total'],0)
        def uploaded(name):
            return self.write('register_media',dict(name=name,modality='video',sha256=uuid.uuid4().hex*2,size_bytes=10,mime_type='video/mp4',duration_ms=5000,width=720,height=1280,storage='local',object_key=uuid.uuid4().hex+'.mp4',rights='owned',source={'kind':'file-import','content':'真实导入记录'}))['id']
        imported=uploaded('导入结果'); self.candidate(objects['shot'],imported,role='video_take')
        quote=self.service.preview_workbench_generation(self.p,request)
        generated=self.write('generate_workbench',{'request':request,'preview_sha256':quote['preview_sha256']})
        self.write('configure_budget',{'limits':{'remote_jobs':2,'video_seconds':10},'reason':'isolated metadata output'})
        job=generated['jobs'][0]['id']; self.write('update_generation_job',{'job_id':job,'status':'submitted','external_task_id':'offline-d06'})
        output=uploaded('虽有导入证据但也是任务输出'); self.write('update_generation_job',{'job_id':job,'status':'succeeded','outputs':[{'media_id':output}]})
        page=self.service.list_working_candidates(self.p,objects['shot'],'video',filter_kind='local',limit=1)
        self.assertEqual((page['total'],page['items'][0]['media_id']),(1,imported))
        self.assertEqual(self.service.list_working_candidates(self.p,objects['shot'],'video')['total'],3)

    def test_prompt_assistant_reads_image_bytes_fixed_draft_and_never_applies_automatically(self):
        from PIL import Image
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.production.prompt_assist import GrokBuildPromptAssistant
        from vsc.assets.resource_service import Conflict
        objects, media, document, draft, request = self.prompt_draft()
        calls=[]
        def runner(command, **kwargs):
            blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text())
            self.assertEqual(command[command.index('--tools')+1],'')
            self.assertIn('--disable-web-search',command); self.assertIn('--no-subagents',command)
            pictures=[b for b in blocks if b['type']=='image'];self.assertEqual(len(pictures),1)
            im=Image.open(io.BytesIO(base64.b64decode(pictures[0]['data'])));self.assertEqual(im.size,(32,48))
            self.assertIn(draft['sha256'],blocks[0]['text']);calls.append(blocks)
            return subprocess.CompletedProcess(command,0,json.dumps({'text':'A blue cup beside a window.','explanation':'Based on the fixed prompt and supplied image.'}),'')
        self.service.prompt_assistant=GrokBuildPromptAssistant(executable='isolated-grok',runner=runner)
        with patch('vsc.production.prompt_assist.shutil.which',return_value='/isolated/grok'):
            value=self.write('start_prompt_assist',request,idempotency_key='prompt-original')
            self.assertEqual(value['status'],'completed',value)
            replay=self.service.start_prompt_assist(self.p,request,expected_revision=0,idempotency_key='prompt-original',actor='test-human')
        self.assertEqual(value['id'],replay['id']);self.assertEqual(len(calls),1)
        self.assertEqual(self.service.classic_production_options(self.p,objects['shot'])['drafts'][0]['document']['prompt'],document['prompt'])
        changed=self.write('save_classic_draft',{'document':dict(document,prompt='新的输入'), 'base_draft_id':draft['id']})
        old=self.service.get_prompt_assist(self.p,value['id']);self.assertEqual(old['request']['prompt'],document['prompt'])
        self.assertEqual(old['request']['reference_images'][0]['id'],media['id'])
        with self.engine.connect() as conn:
            dependencies=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==self.p,S.artifact_dependencies.c.artifact_id==value['id'])).scalars())
            self.assertEqual(dependencies,{draft['id']})
            self.assertFalse(conn.execute(select(S.artifact_decisions.c.id).where(S.artifact_decisions.c.project_id==self.p,S.artifact_decisions.c.artifact_id.in_([draft['id'],value['id'],value['result_artifact_id']]))).first())
        with self.assertRaises(Conflict): self.write('start_prompt_assist',dict(request,draft_sha256='0'*64))
        self.assertEqual(self.service.classic_production_options(self.p,objects['shot'])['drafts'][0]['id'],changed['id'])

    def test_unknown_prompt_receipt_recovers_original_without_second_host_call(self):
        from vsc.production.prompt_assist import GrokBuildPromptAssistant
        _,_,_,_,request=self.prompt_draft();calls=[]
        def runner(command,**kw):calls.append(command);raise subprocess.TimeoutExpired(command,120)
        self.service.prompt_assistant=GrokBuildPromptAssistant(executable='isolated-grok',runner=runner)
        with patch('vsc.production.prompt_assist.shutil.which',return_value='/isolated/grok'):
            result=self.write('start_prompt_assist',request,idempotency_key='unknown-original')
            self.assertEqual(result['status'],'submission_unknown',result)
            replay=self.service.start_prompt_assist(self.p,request,expected_revision=0,idempotency_key='unknown-original',actor='test-human')
        self.assertEqual(len(calls),1);self.assertEqual(replay['id'],result['id'])
        self.assertEqual(self.service.get_prompt_assist(self.p,result['id'])['status'],'submission_unknown')


class PromptAssistFrontendTests(unittest.TestCase):
    def test_explicit_apply_changed_input_and_unknown_recovery(self):
        import shutil
        from support.paths import ROOT
        if not shutil.which('node'):self.skipTest('requires Node')
        source=r"""
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url),{Document}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');const root=document.createElement('section');document.body.append(root);
const {mountPromptAssist}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/prompt-assist.js'));
let state={document:{prompt:'原输入'},saved:{id:'draft',sha256:'a'.repeat(64)},dirty:false},applied=[],calls=0,reads=0,release;
const deferred=new Promise(resolve=>release=resolve),notes=[];
const completed={id:'request',status:'completed',result:{text:'A suggestion',explanation:'basis'}};
const controller=mountPromptAssist(root,{state,saveDraft:async()=>{},getDraft:()=>state,write:async()=>{calls++;return calls===1?deferred:completed;},read:async()=>{reads++;return completed;},isCurrent:()=>true,remember(){},onApply:text=>{applied.push(text);state.document.prompt=text;},writable:true,notice:v=>notes.push(v)});
const button=label=>root.querySelectorAll('button').find(b=>b.textContent===label);
const started=button('优化').click();await Promise.resolve();await Promise.resolve();state.document.prompt='新输入';release(completed);await started;
assert.equal(applied.length,0);assert.equal(button('应用建议').disabled,true);assert.equal(state.document.prompt,'新输入');
await button('收起建议').click();await button('翻译').click();assert.equal(applied.length,0);await button('应用建议').click();assert.deepEqual(applied,['A suggestion']);
state.assist={request:{draft_version_id:'draft'},snapshot:JSON.stringify(state.document),value:{id:'unknown',status:'submission_unknown'}};controller.refresh();
assert.equal(button('优化').disabled,true);await button('恢复助手请求').click();assert.equal(calls,2);assert.equal(reads,1);assert.equal(button('应用建议').disabled,false);
console.log('PASS explicit apply, stale-input refusal, original unknown recovery');
"""
        result=subprocess.run(['node','--input-type=module','-e',source],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_late_suggestion_remains_with_original_identity_after_switch(self):
        import shutil
        from support.paths import ROOT
        if not shutil.which('node'):self.skipTest('requires Node')
        source=r"""
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
globalThis.document=new Document('');Element.prototype.contains=function(node){while(node){if(node===this)return true;node=node.parentElement;}return false;};
const data=new Map();globalThis.sessionStorage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
const root=document.createElement('section');document.body.append(root);let actor='account-a',revision=5,release;
const delayed=new Promise(resolve=>release=resolve),notes=[];const {createClassicProduction}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/classic-production.js'));
const api=async(url,opts)=>{
 if(url.endsWith('/drafts'))return {id:'fixed',sha256:'a'.repeat(64),version:1,revision:++revision};
 if(url.endsWith('/prompt-assist'))return delayed;
 if(url.includes('section=shots'))return {scope:{kind:'shot',id:'shot'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:[{id:'shot',title:'当前镜头'}]}}};
 if(url.includes('/classic-production?'))return {revision,shot:{id:'shot'},drafts:[],models:[],media:[],media_total:0,modes:{image:{modality:'image',slots:{reference_image:'image'}}}};
 return {items:[],total:0};
};
const app=createClassicProduction(root,{api,session:()=>({actor,identityId:actor,writable:true,csrf:'x',revision}),setRevision:v=>revision=v,notice:v=>notes.push(v),navigate(){},media(){}});
await app.load({projectId:'project',objectId:'shot',productionKind:'image'});
let form=root.querySelector('form'),prompt=form.querySelector('textarea');prompt.value='账户A输入';await form.dispatch('input',{target:prompt});
const request=root.querySelectorAll('button').find(n=>n.textContent==='优化').click();for(let i=0;i<12;i++)await Promise.resolve();
actor='account-b';await app.load({projectId:'project',objectId:'shot',productionKind:'image'});
release({id:'original-request',revision:++revision,status:'completed',result:{text:'账户A迟到建议',explanation:''}});await request;
assert.equal(root.querySelector('form').querySelector('textarea').value,'');assert.ok(!root.textContent.includes('账户A迟到建议'));
assert.ok(data.get('vsc-classic-draft:account-a:project:shot:image').includes('账户A迟到建议'));
assert.equal(data.has('vsc-classic-draft:account-b:project:shot:image'),false);app.suspend();
console.log('PASS late original-identity suggestion isolation');
"""
        result=subprocess.run(['node','--input-type=module','-e',source],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
