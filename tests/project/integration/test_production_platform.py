"""Real project management transactions, fixed scope previews and HTTP consumers."""
import importlib.util
import os
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS,
                     'requires explicit isolated PostgreSQL test connection')
class ProductionPlatformTests(ResourceStoreFixture, unittest.TestCase):
    def test_first_production_preview_save_and_replay_do_not_approve_or_generate(self):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import Conflict, ResourceError
        objects = self.hierarchy()
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']],
                      {'state_versions': [{'scene_id': objects['scene']}]})
        first = self.media('首帧')
        self.select(self.candidate(objects['shot'], first))
        provider_id, model_id = 'offline_' + uuid.uuid4().hex, str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider_id, name='offline test', modality='video',
                base_url='https://example.invalid', auth_ref='none', enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model_id, provider_id=provider_id, model_key='test',
                modality='video', model_version='1', capabilities={'purposes':['video_clip'],'first_frame':True},
                default_params={}, cost_rule={}, enabled=True))
        now = datetime.now(timezone.utc)
        request = {'episode_id': objects['episode'], 'model_id':model_id, 'purpose':'video_clip',
            'shots':[{'shot_id':objects['shot'],'prompt':'固定动作','duration_ms':5000,'params':{}}],
            'execution_policy':{'version':'bounded-v1','first_draft_due_at':(now+timedelta(minutes=45)).isoformat(),
                'stop_submitting_at':(now+timedelta(minutes=60)).isoformat(), 'max_attempts_per_purpose':2,
                'max_repair_rounds':1, 'authorization':{'mode':'new_batch','reason':'明确的合成新批次'}}}
        preview = self.service.preview_first_production(self.p, request)
        self.assertEqual(preview['generation_quote']['native_units']['video_seconds'], 5)
        self.assertFalse(preview['generation_quote']['all_prices_known'])
        price = self.write('configure_commerce_plan', {'document':{
            'plan_key':'synthetic-video', 'title':'隔离报价', 'amount_minor':100, 'currency':'TST',
            'credits':100, 'bucket_kind':'credit', 'validity_days':2, 'checkout_minutes':10,
            'purposes':['video_clip'], 'rates':[{'model_id':model_id,'unit':'video_seconds','credits_per_unit':3}],
            'refund_policy':'unused_order_only', 'max_concurrent_jobs':1, 'invoice_enabled':False,
            'seat_limit':3, 'watermark_required':False, 'renewal_policy':'manual_from_payment'},
            'base_version_id':None, 'metering_enabled':True})
        with self.assertRaises(ResourceError) as missing_account:
            self.service.preview_first_production(self.p, request)
        self.assertEqual(missing_account.exception.code, 'commerce_account_required')
        request['commerce_account_actor'] = 'test-human'
        preview = self.service.preview_first_production(self.p, request)
        charge = preview['artifact']['document']['commerce_charge']
        self.assertEqual(charge['price_version_id'], price['id'])
        self.assertEqual(charge['account_actor'], 'test-human')
        self.assertEqual(sum(charge['max_credits_by_operation'].values()), 15)
        payload = {'request':request,'preview_sha256':preview['preview_sha256']}
        key = uuid.uuid4().hex
        proposal = self.write('propose_first_production', payload, idempotency_key=key)
        self.assertFalse(self.service.get_artifact_version(self.p, proposal['id'])['approved'])
        import json
        saved_document = json.loads(self.service.get_artifact_version(self.p, proposal['id'])['document'])
        self.assertEqual(saved_document['commerce_charge'], charge)
        self.assertEqual(self.service.get_execution_authorizations(self.p)['items'], [])
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'], 0)
        self.write('create_episode_batch', {'titles':['后续集'],'parent_id':objects['work']})
        replay = self.service.propose_first_production(self.p, payload, expected_revision=0,
            idempotency_key=key, actor='test-human')
        self.assertEqual(replay, proposal)
        with self.assertRaises(Conflict):
            self.write('propose_first_production', dict(payload,preview_sha256='0'*64))
        self.write('decide_artifact', {'artifact_id':proposal['id'],'reason':'合成用户明确批准新批次'})
        choices=self.service.get_execution_authorizations(self.p)['items']
        self.assertEqual([row['id'] for row in choices], [proposal['id']])
        request['execution_policy']['authorization']={'mode':'continue','run_version_id':proposal['id'],'sha256':choices[0]['sha256']}
        continuation=self.service.preview_first_production(self.p,request)
        self.assertEqual(continuation['artifact']['document']['execution_policy']['authorization']['run_version_id'],proposal['id'])

    def test_batch_creation_idempotency_order_and_scope(self):
        from vsc.assets.resource_service import Conflict, ResourceError
        key = uuid.uuid4().hex
        batch = self.write('create_episode_batch', {'titles': ['第一集', '第二集']}, idempotency_key=key)
        original = [row['id'] for row in batch['items']]
        replay = self.service.create_episode_batch(self.p, {'titles': ['第一集', '第二集']},
            expected_revision=0, idempotency_key=key, actor='test-human')
        self.assertEqual(replay, batch)
        page = self.service.get_production_episodes(self.p)
        self.assertEqual(page['total'], 2)
        third = self.write('create_episode_batch', {'titles': ['插入集'], 'parent_id': batch['parent_id']})['items'][0]['id']
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.begin() as conn:
            conn.execute(update(S.episodes).where(S.episodes.c.project_id == self.p,
                S.episodes.c.id == third).values(ordinal=500))
        order = [original[0], third, original[1]]
        self.write('reorder_episodes', {'parent_id': batch['parent_id'], 'episode_ids': order})
        readback = self.service.get_production_episodes(self.p)
        self.assertEqual([row['id'] for row in readback['items']], order)
        self.assertEqual({row['id']: row['title'] for row in readback['items']}[original[1]], '第二集')
        with self.assertRaises(Conflict):
            self.service.reorder_episodes(self.p, {'parent_id': batch['parent_id'], 'episode_ids': order},
                expected_revision=0, idempotency_key=uuid.uuid4().hex, actor='test-human')
        with self.assertRaises(ResourceError):
            self.write('reorder_episodes', {'parent_id': batch['parent_id'], 'episode_ids': original})
        other = self.service.create_project({'name': '另一项目'}, actor='test-human')['id']
        with self.assertRaises(ResourceError):
            self.service.reorder_episodes(other, {'parent_id': batch['parent_id'], 'episode_ids': order},
                expected_revision=0, idempotency_key=uuid.uuid4().hex, actor='test-human')
        self.assertEqual(self.service.get_production_episodes(self.p, limit=1, offset=1)['items'][0]['id'], third)

    def test_initial_shots_middle_insert_and_page_boundary_move_keep_identity(self):
        batch=self.write('create_episode_batch',{'titles':['集'+str(n) for n in range(26)],'initial_shot_count':1})
        ids=[r['id'] for r in batch['items']]
        tree=self.service.get_project_tree(self.p)['nodes'];shot=next(n['id'] for n in tree if n['kind']=='shot')
        media=self.media();candidate=self.write('propose_binding',{'target_object_id':shot,'media_id':media,'role':'first_frame','slot_key':'workbench'})
        self.write('save_working_selection',{'shot_id':shot,'candidate_id':candidate['candidate_id'],'output_kind':'image','base_version_id':None})
        inserted=self.write('create_episode_batch',{'titles':['中间集'],'parent_id':batch['parent_id'],'initial_shot_count':2,'insert_before_id':ids[1]})['items'][0]['id']
        read=self.service.get_production_episodes(self.p)
        self.assertEqual([r['id'] for r in read['items']][:3],[ids[0],inserted,ids[1]])
        self.assertEqual(read['items'][1]['shot_count'],2);self.assertEqual(read['items'][0]['shot_count'],1)
        moving=read['items'][24]['id'];before=read['items'][23]['id']
        self.write('reorder_episodes',{'episode_id':moving,'direction':'up'})
        self.assertEqual(self.service.get_production_episodes(self.p,offset=23,limit=2)['items'][0]['id'],moving)
        self.assertEqual(self.service.get_production_episodes(self.p,offset=24,limit=1)['items'][0]['id'],before)
        selected=self.service.list_working_selections(self.p,shot_id=shot)['items'][0]
        self.assertEqual(selected['media_id'],media)
        foreign=self.write('create_object',{'kind':'work','title':'另一部','display_code':'OTHER','ordinal':1})['id']
        from vsc.assets.resource_service import ResourceError
        with self.assertRaises(ResourceError):self.write('create_episode_batch',{'titles':['不应写入'],'parent_id':foreign,'insert_before_id':ids[0]})

    def test_batch_preview_keeps_readiness_and_rejects_other_episode(self):
        from vsc.assets.resource_service import ResourceError, Conflict
        objects = self.hierarchy()
        result = self.service.preview_shot_batch(self.p, {'episode_id': objects['episode'], 'shot_ids': [objects['shot']]})
        self.assertEqual(result['total'], 1)
        self.assertFalse(result['items'][0]['ready'])
        self.assertTrue(result['items'][0]['gaps'])
        next_episode = self.write('create_episode_batch', {'titles': ['另一集'], 'parent_id': objects['work']})['items'][0]['id']
        with self.assertRaises(ResourceError) as error:
            self.service.preview_shot_batch(self.p, {'episode_id': next_episode, 'shot_ids': [objects['shot']]})
        self.assertEqual(error.exception.code, 'shot_scope_mismatch')
        context = self.service.compile_shot_context(self.p, objects['shot'])
        context['revision'] -= 1
        with patch.object(self.service, 'compile_shot_context', return_value=context), self.assertRaises(Conflict):
            self.service.preview_shot_batch(self.p, {'episode_id': objects['episode'], 'shot_ids': [objects['shot']]})

    def test_http_management_and_readback_require_session(self):
        if not all(importlib.util.find_spec(name) for name in ('fastapi', 'httpx')):
            self.skipTest('requires optional web dependencies')
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            catalog = ResourceCatalog(root, service=self.service)
            app = create_app({'allowed_hosts': ['testserver'], 'allowed_origins': ['http://testserver'],
                'access_token': 'test', 'human_identity': 'test-human'}, catalog=catalog)
            with TestClient(app) as client:
                payload = {'payload': {'titles': ['API 第一集', 'API 第二集']}, 'expected_revision': 0,
                           'idempotency_key': uuid.uuid4().hex}
                path = '/api/v1/projects/' + self.p
                self.assertEqual(client.post(path+'/episode-batches', json=payload).status_code, 403)
                login = client.post('/api/v1/session', json={'token': 'test'}, headers={'origin':'http://testserver'}).json()
                headers = {'origin':'http://testserver','x-csrf-token':login['csrf_token']}
                saved = client.post(path+'/episode-batches', json=payload, headers=headers)
                self.assertEqual(saved.status_code, 200, saved.text)
                body = saved.json()
                self.assertEqual(client.post(path+'/episode-batches', json=payload, headers=headers).json(), body)
                readback = client.get(path+'/production-platform').json()
                self.assertEqual(readback['episodes']['total'], 2)
                episode = body['items'][0]['id']
                detail = client.get(path+'/production-platform', params={'episode_id':episode})
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(detail.json()['shots']['total'], 0)
                self.assertEqual(detail.json()['episode']['id'], episode)
                self.assertEqual(client.get(path+'/production-platform', params={'limit':0}).status_code, 422)
                self.assertIn('production-platform.js', client.get('/static/panel.js').text)
                self.assertIn('production-platform.css', client.get('/').text)


class ProductionPlatformFrontendTests(unittest.TestCase):
    def test_old_page_failures_and_write_retries_preserve_scope_and_request(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node for deterministic frontend races')
        source = r'''
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
const document=new Document(''),root=document.createElement('section');
globalThis.document=document;
globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
Object.defineProperty(Element.prototype,'options',{get(){return this.children.filter(n=>n.tagName==='OPTION');}});
const module=await import(pathToFileURL('src/vsc/interfaces/web/static/production-platform.js').href);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const first=deferred(),writeFail=deferred(),notices=[],calls=[];
const page=title=>({project_id:title,revision:4,read_only:false,episodes:{items:[],works:[],total:0,next_offset:null}});
let active='old',postCount=0,session={actor:'human',csrf:'csrf',revision:4,writable:true};
const ctx={session:()=>session,setRevision:r=>session.revision=r,projectName:()=>active,notice:s=>notices.push(s),
  api:async(url,opts)=>{calls.push({url,opts});if(opts?.method==='POST'){postCount++;if(postCount===1)throw new Error('response lost');if(postCount===3)return writeFail.promise;return {revision:5};}if(url.includes('/old/'))return first.promise;return page(active);}};
const platform=module.createProductionPlatform(root,ctx);
const old=platform.load({page:'project',project:'old'});
active='new';await platform.load({page:'project',project:'new'});
first.reject(new Error('old failure'));await old;
assert.ok(root.textContent.includes('new'));assert.ok(!root.textContent.includes('old failure'));assert.equal(notices.length,0);
await root.querySelectorAll('button').find(n=>n.textContent==='+ 创建剧集').click();
let form=root.querySelector('form'),titles=form.querySelector('textarea');titles.value='第一集';await titles.dispatch('input');
await form.dispatch('submit');assert.equal(titles.value,'第一集');
await form.dispatch('submit');
const writes=calls.filter(c=>c.opts?.method==='POST').map(c=>JSON.parse(c.opts.body));
assert.equal(writes.length,2);assert.equal(writes[0].idempotency_key,writes[1].idempotency_key);
assert.equal(writes[0].expected_revision,4);assert.equal(writes[1].expected_revision,4);
await root.querySelectorAll('button').find(n=>n.textContent==='+ 创建剧集').click();
form=root.querySelector('form');titles=form.querySelector('textarea');titles.value='旧集保稿';await titles.dispatch('input');
const pending=form.dispatch('submit');await Promise.resolve();
active='next';await platform.load({page:'project',project:'next'});
const before=notices.length;writeFail.reject(new Error('late write failure'));await pending;
assert.ok(root.textContent.includes('next'));assert.equal(notices.length,before);platform.suspend();
console.log('PASS old read/write isolation and stable idempotency retry');
'''
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_project_dialog_collects_name_episode_count_and_style(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node for the project dialog')
        source = r'''
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
const document=new Document(''),root=document.createElement('section');
globalThis.document=document;
globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const module=await import(pathToFileURL('src/vsc/interfaces/web/static/production-platform.js').href);
const calls=[];
const ctx={session:()=>({actor:'human',csrf:'csrf',revision:0,writable:true,writeAvailable:true}),setRevision(){},projectName:()=>'',notice(){},
  projects:()=>[],refreshProjects:async()=>{},navigate(){},created:async()=>{},
  api:async(url,opts)=>{calls.push({url,opts});if(String(url).includes('episode-batches'))return {revision:2};return {id:'p9',revision:1};}};
const platform=module.createProductionPlatform(root,ctx);
await platform.load({page:'projects'});
await [...root.querySelectorAll('button')].find(node=>node.textContent.includes('新建项目')).click();
const dialog=root.querySelector('dialog');
assert.equal(dialog.querySelector('h2').textContent,'新建项目');
assert.ok(dialog.textContent.includes('项目名称'));
assert.ok(dialog.textContent.includes('集数'));
assert.ok(dialog.textContent.includes('2D动漫'));
assert.ok(dialog.textContent.includes('真人'));
const [name,count]=dialog.querySelectorAll('input');
name.value='新片';count.value='2';
dialog.querySelector('select').value='3d';
await dialog.querySelector('form').dispatch('submit');
const posts=calls.filter(call=>call.opts?.method==='POST').map(call=>({url:call.url,body:JSON.parse(call.opts.body)}));
assert.equal(posts[0].body.payload.name,'新片');
assert.equal(posts[0].body.payload.profile,'vsc.series-pg');
assert.equal(posts[0].body.payload.character_style,'3d');
assert.deepEqual(posts[1].body.payload.titles,['第1集','第2集']);
assert.equal(posts[1].body.payload.initial_shot_count,0);
platform.suspend();
console.log('PASS new project dialog');
'''
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_project_card_delete_confirms_without_a_typed_reason(self):
        import shutil
        import subprocess
        from support.paths import ROOT
        if not shutil.which('node'):
            self.skipTest('requires Node for the project card dialog')
        source = r'''
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
const document=new Document(''),root=document.createElement('section');
globalThis.document=document;
globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
Element.prototype.replaceWith=function(node){const parent=this.parentElement;if(!parent)return;const index=parent.children.indexOf(this);parent.children.splice(index,1,node);this.parentElement=null;node.parentElement=parent;};
const store=new Map();
globalThis.sessionStorage={getItem:key=>store.has(key)?store.get(key):null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
const module=await import(pathToFileURL('src/vsc/interfaces/web/static/production-platform.js').href);
const calls=[],notices=[];
let projects=[{id:'p1',name:'示例项目',profile:'vsc.series-pg',read_only:false,counts:{episodes:1,images:0,videos:0,canvases:0}}];
const ctx={session:()=>({actor:'human',csrf:'csrf',revision:4,writable:true}),setRevision(){},projectName:()=>'',notice:value=>notices.push(String(value)),
  projects:()=>projects,refreshProjects:async()=>{projects=[];},navigate(){},
  api:async(url,opts)=>{calls.push({url,opts});if(opts?.method==='POST')return {status:'trashed',revision:5};return {revision:4};}};
const platform=module.createProductionPlatform(root,ctx);
await platform.load({page:'projects'});
const cardButton=label=>[...root.querySelectorAll('button')].find(node=>node.getAttribute('aria-label')===label);
const remove=cardButton('删除');
assert.ok(remove);
await remove.click();
let dialog=root.querySelector('dialog');
assert.equal(dialog.getAttribute('aria-label'),'提示');
assert.ok(dialog.textContent.includes('确定要删除项目“示例项目”吗？'));
assert.equal(dialog.querySelector('input'),null);
await [...dialog.querySelectorAll('button')].find(node=>node.textContent==='取消').click();
assert.equal(calls.filter(call=>call.opts?.method==='POST').length,0);
assert.equal(root.querySelector('dialog'),null);
await cardButton('删除').click();
dialog=root.querySelector('dialog');
await dialog.querySelector('form').dispatch('submit');
const posts=calls.filter(call=>call.opts?.method==='POST');
assert.equal(posts.length,1);
const body=JSON.parse(posts[0].opts.body);
assert.equal(body.payload.operation,'trash');
assert.equal(body.payload.target_type,'project');
assert.equal(body.payload.target_id,'p1');
assert.equal(body.payload.reason,'删除项目');
assert.equal(body.expected_revision,4);
assert.ok(body.idempotency_key);
assert.deepEqual(notices,['删除成功']);
assert.ok(!root.textContent.includes('示例项目'));
platform.suspend();
console.log('PASS project card delete confirms into recycle without a typed reason');
'''
        result = subprocess.run(['node', '--input-type=module', '-e', source], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
