import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {createCanvasLibrary,openCanvasLibraryDialog,readCanvasLibraryPending} from '../../../src/vsc/interfaces/web/static/canvas-library.js';
import {createProductionPlatform} from '../../../src/vsc/interfaces/web/static/production-platform.js';
const {Document,Element}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const submit=d=>d.querySelector('form').dispatch('submit');
const record=storage=>JSON.parse([...storage.entries()].find(([k])=>!k.includes('draft'))?.[1]||'null');
function setup({count=1,api,projects,episodes,navigate,storage=new Map(),permissions}={}){
  const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
  globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  const session={actor:'human',identityId:'identity-1',workspaceId:'workspace-1',csrf:'csrf',writeAvailable:true},calls=[],notices=[],navigations=[],revisions=[];
  const rows=Array.from({length:count},(_,i)=>({id:'canvas-'+i,project_id:'p1',project_name:'项目一',episode_id:'ep1',episode_name:'第一集',title:'画布'+i,canvas_revision:1,version_id:'version-'+i,updated_at:'2026-11-10T00:00:00Z',creator_id:'identity-1',creator_name:'创建者',collaboration_enabled:false,permissions:permissions||{can_read:true,can_edit:true,can_rename:true,can_copy:true,can_delete:true,can_manage_collaboration:true}}));
  const ctx={session:()=>session,projects:projects||(async()=>({items:[{id:'p1',name:'项目一',permissions:{can_edit:true}},{id:'p2',name:'只读项目',permissions:{can_edit:false}}],creators:[{id:'identity-1',name:'创建者'},{id:'member-2',name:'成员二'}]})),episodes:episodes||(async p=>({items:[{id:p==='p1'?'ep1':'ep2',title:'第一集'}],revision:8})),notice:s=>notices.push(String(s)),setRevision:(r,p)=>revisions.push([r,p]),navigate:async(...args)=>{navigations.push(args);await navigate?.(...args);},
    api:async(url,options={})=>{const body=typeof options.body==='string'?JSON.parse(options.body):options.body,call={url,options,body};calls.push(call);if(api){const v=await api(call);if(v!==undefined)return v;}
      if(url.startsWith('/api/v1/canvas-library?')){const q=new URLSearchParams(url.split('?')[1]),start=Number(q.get('offset'));return {items:rows.slice(start,start+30),total:rows.length,next_offset:start+30<rows.length?start+30:null,capabilities:{collaboration:false,cross_episode_copy:false}};}
      if(url.includes('/operation-receipts/'))return {found:false,response:null};
      if(options.method==='POST'||options.method==='PUT')return {id:'saved-canvas',revision:9,canvas_revision:2,title:body.payload.title,status:body.payload.operation==='trash'?'trashed':undefined};
      if(url.includes('creative-canvases?'))return {items:rows,revision:8};
      if(url.includes('/creative-canvases/'))return {id:url.split('/').at(-1),project_id:'p1',episode_id:'ep1',revision:8,canvas_revision:1,title:rows[0]?.title||'画布',document:{viewport:{x:2,y:3,zoom:1},nodes:[{id:'n1',type:'image',title:'原图',x:1,y:2,params:{seed:3},media_id:'media-1',job_id:'job-1',preview_url:'/preview.png'}],edges:[]}};
      throw new Error('unexpected route '+url);}};
  const library=createCanvasLibrary(root,ctx);return {root,ctx,library,session,calls,rows,notices,navigations,revisions,storage,posts:()=>calls.filter(c=>['POST','PUT'].includes(c.options.method)),lists:()=>calls.filter(c=>c.url.startsWith('/api/v1/canvas-library?'))};
}
const filters=h=>h.root.querySelector('.cl-filters').querySelectorAll('select');
const action=(h,index)=>h.root.querySelector('.cl-card-actions').querySelectorAll('button')[index];
async function openCreate(h){await h.library.openCreate();const d=h.root.querySelector('dialog');assert.ok(d,h.notices.join(';'));return d;}
async function fillCreate(d,{project='p1',episode='ep1',title='新画布'}={}){const [p,e]=d.querySelectorAll('select');p.value=project;await p.dispatch('change');e.value=episode;await e.dispatch('change');const name=d.querySelectorAll('input').find(n=>n.type!=='checkbox');name.value=title;await name.dispatch('input');}
const escapeDialog=async d=>{const e=await d.dispatch('cancel');if(!e.defaultPrevented)await d.close();};

test('full catalogue requests source defaults and exposes unavailable controls without fake writes',async()=>{
  const h=setup();await h.library.load();const q=new URLSearchParams(h.lists()[0].url.split('?')[1]);assert.equal(q.get('limit'),'30');assert.equal(q.get('creator_filter'),'mine');assert.equal(q.get('permission'),'all');assert.equal(q.get('order'),'updated_desc');assert.equal(q.has('project_id'),false);assert.equal(filters(h)[1].disabled,true);assert.equal(h.root.querySelectorAll('.cl-card').length,1);
  assert.equal(h.root.querySelector('.cl-collaboration-switch').disabled,true);assert.equal(action(h,2).disabled,true);await action(h,2).click();assert.equal(h.posts().length,0);
});

test('incremental 30-row loading retains the first page on continuation failure and retries the same offset',async()=>{
  let failed=false;const h=setup({count:61,api:async c=>{if(c.url.includes('offset=30')&&!failed){failed=true;throw new Error('continuation offline');}}});await h.library.load();assert.equal(h.root.querySelectorAll('.cl-card').length,30);await h.library.loadMore();assert.equal(h.root.querySelectorAll('.cl-card').length,30);assert.ok(h.root.textContent.includes('continuation offline'));await h.root.querySelector('.cl-retry').click();assert.equal(h.root.querySelectorAll('.cl-card').length,60);await h.library.loadMore();assert.equal(h.root.querySelectorAll('.cl-card').length,61);assert.ok(h.root.textContent.includes('没有更多数据了'));assert.equal(h.lists().filter(c=>c.url.includes('offset=30')).length,2);
});

test('first page failure clears old rows and provides an explicit retry',async()=>{
  let fail=false;const h=setup({api:async c=>{if(c.url.includes('/canvas-library?')&&fail)throw new Error('first offline');}});await h.library.load();fail=true;await h.library.reload();assert.equal(h.root.querySelectorAll('.cl-card').length,0);assert.ok(h.root.querySelector('.cl-retry'));fail=false;await h.root.querySelector('.cl-retry').click();assert.equal(h.root.querySelectorAll('.cl-card').length,1);
});

test('search debounces for 300ms and newer filters discard an older response and finally',async()=>{
  const old=deferred(),started=deferred();const h=setup({api:async c=>{if(c.url.includes('query=old')){started.resolve();return old.promise;}}});await h.library.load();const search=h.root.querySelector('input');search.value='o';await search.dispatch('input');search.value='old';await search.dispatch('input');await wait(150);assert.equal(h.lists().length,1);await started.promise;
  search.value='new';await search.dispatch('input');await wait(330);old.resolve({items:[],total:0,next_offset:null});await wait(0);assert.equal(h.root.querySelectorAll('.cl-card').length,1);assert.equal(h.lists().length,3);h.library.suspend();
});

test('project change clears episode immediately and ignores stale episode options',async()=>{
  const first=deferred(),started=deferred();const h=setup({episodes:async p=>{if(p==='p1'){started.resolve();return first.promise;}return {items:[{id:'ep2',title:'第二项目集'}]};}});await h.library.load();const [project,episode]=filters(h);project.value='p1';const a=project.dispatch('change');await started.promise;project.value='p2';await project.dispatch('change');first.resolve({items:[{id:'old',title:'旧集'}]});await a;assert.equal(episode.value,'');assert.equal(episode.options.some(n=>n.value==='old'),false);assert.ok(episode.options.some(n=>n.value==='ep2'));assert.ok(!h.lists().at(-1).url.includes('episode_id='));
});

test('member, permission and ascending filters go to the server and preserve row permissions',async()=>{
  const h=setup({permissions:{can_read:true,can_edit:false,can_rename:false,can_copy:false,can_delete:false,can_manage_collaboration:false}});await h.library.load();const [, ,creator,permission,order]=filters(h);creator.value='member:member-2';await creator.dispatch('change');permission.value='view';await permission.dispatch('change');order.value='updated_asc';await order.dispatch('change');await wait(0);const q=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);assert.equal(q.get('creator_id'),'member-2');assert.equal(q.get('creator_filter'),'member');assert.equal(q.get('permission'),'view');assert.equal(q.get('order'),'updated_asc');assert.equal(h.root.querySelectorAll('.cl-icon-action').length,0);
});

test('create requires a real editable project, an episode and a trimmed name of at most 100',async()=>{
  const h=setup();await h.library.load();const d=await openCreate(h);assert.equal(d.querySelectorAll('select')[0].options.some(n=>n.value==='p2'),false);assert.equal(d.querySelector('.cl-confirm').disabled,true);await fillCreate(d,{title:'  '});assert.equal(d.querySelector('.cl-confirm').disabled,true);await submit(d);assert.equal(h.posts().length,0);await fillCreate(d,{title:'x'.repeat(101)});await submit(d);assert.equal(h.posts().length,0);await fillCreate(d,{title:'  '+'x'.repeat(100)+'  '});await submit(d);assert.equal(h.posts().length,1);assert.equal(h.posts()[0].url,'/api/v1/projects/p1/creative-canvases');assert.deepEqual(h.posts()[0].body.payload,{title:'x'.repeat(100),episode_id:'ep1',document:{nodes:[],edges:[]}});assert.equal(h.posts()[0].body.expected_revision,8);assert.equal(h.root.querySelector('dialog'),null);
});

test('create baseline failure never creates a project or an empty fallback canvas',async()=>{
  const h=setup({api:async c=>{if(c.url.includes('creative-canvases?'))throw new Error('baseline failed');}});await h.library.load();const d=await openCreate(h);await fillCreate(d);await submit(d);assert.equal(h.posts().length,0);assert.equal(d.querySelectorAll('input')[0].value,'新画布');assert.ok(d.textContent.includes('baseline failed'));
});

test('rename preserves original canvas content and strips only the display preview URL',async()=>{
  const h=setup();await h.library.load();await action(h,0).click();const d=h.root.querySelector('dialog');d.querySelector('input').value='改名';await submit(d);const post=h.posts()[0];assert.equal(post.options.method,'PUT');assert.equal(post.body.payload.title,'改名');assert.equal(post.body.payload.canvas_revision,1);assert.equal(post.body.payload.document.nodes[0].job_id,'job-1');assert.equal(post.body.payload.document.nodes[0].preview_url,undefined);assert.deepEqual(post.body.payload.document.nodes[0].params,{seed:3});assert.equal(h.root.querySelector('dialog'),null);
});

test('ordinary copy confirms, pins the original revision and keeps the generated name within 100',async()=>{
  const h=setup();h.rows[0].title='x'.repeat(100);await h.library.load();await action(h,1).click();assert.equal(h.posts().length,0);await submit(h.root.querySelector('dialog'));const post=h.posts()[0];assert.equal(post.url,'/api/v1/projects/p1/creative-canvases/canvas-0/copy');assert.equal(post.body.payload.canvas_revision,1);assert.equal([...post.body.payload.title].length,100);assert.ok(post.body.payload.title.endsWith(' Copy'));
});

for(const status of [undefined,403])test(`unconfirmed mutation ${status||'network error'} retains original body and scope across modal closure`,async()=>{
  let failed=false;const h=setup({api:async c=>{if(c.options.method==='POST'&&!failed){failed=true;throw Object.assign(new Error('unconfirmed'),{status});}}});await h.library.load();await action(h,1).click();const d=h.root.querySelector('dialog');await submit(d);const first=h.posts()[0].body;await escapeDialog(d);assert.ok(record(h.storage));await h.root.querySelector('.cl-recovery-button').click();assert.equal(h.posts().length,2);assert.deepEqual(h.posts()[1].body,first);assert.equal(record(h.storage),null);
});

test('an already committed receipt recovers lost response without resending the write',async()=>{
  let committed=false;const h=setup({api:async c=>{if(c.options.method==='POST'){committed=true;throw new Error('response lost');}if(c.url.includes('/operation-receipts/'))return {found:committed,response:{id:'saved-copy',revision:9}};}});await h.library.load();await action(h,1).click();await submit(h.root.querySelector('dialog'));await h.root.querySelector('dialog').close();await h.root.querySelector('.cl-recovery-button').click();assert.equal(h.posts().length,1);assert.equal(record(h.storage),null);
});

test('saved mutation with failed list readback retries only the list',async()=>{
  let saved=false,fail=true;const h=setup({api:async c=>{if(c.options.method==='PUT'){saved=true;return {id:'canvas-0',revision:9};}if(c.url.includes('/canvas-library?')&&saved&&fail)throw new Error('list offline');}});await h.library.load();await action(h,0).click();const d=h.root.querySelector('dialog');d.querySelector('input').value='原稿保留';await submit(d);assert.ok(record(h.storage).result);fail=false;await submit(d);assert.equal(h.posts().length,1);assert.equal(record(h.storage),null);
});

test('explicit initial conflict preserves the title and a later save rereads its baseline',async()=>{
  let conflicted=false;const h=setup({api:async c=>{if(c.options.method==='PUT'&&!conflicted){conflicted=true;throw Object.assign(new Error('changed version'),{status:409});}if(c.url.includes('/creative-canvases/')&&!c.options.method&&conflicted)return {id:'canvas-0',revision:20,canvas_revision:3,title:'新的基线',document:{nodes:[],edges:[]}};}});await h.library.load();await action(h,0).click();const d=h.root.querySelector('dialog');d.querySelector('input').value='我的名称';await submit(d);assert.equal(record(h.storage),null);assert.equal(d.querySelector('input').value,'我的名称');await submit(d);assert.equal(h.posts()[1].body.expected_revision,20);assert.notEqual(h.posts()[0].body.idempotency_key,h.posts()[1].body.idempotency_key);
});

for(const change of ['scope','identity','workspace','close'])test(`late mutation after ${change} keeps the committed receipt without refreshing a new surface`,async()=>{
  const pending=deferred(),started=deferred();const h=setup({api:async c=>{if(c.options.method==='POST'){started.resolve();return pending.promise;}}});await h.library.load();await action(h,1).click();const d=h.root.querySelector('dialog'),saving=submit(d);await started.promise;await submit(d);assert.equal(h.posts().length,1);if(change==='scope')await h.library.load({projectId:'p2'});else if(change==='identity')h.session.identityId='identity-2';else if(change==='workspace')h.session.workspaceId='workspace-2';else await d.close();const count=h.lists().length;pending.resolve({id:'late-copy',revision:9});await saving;assert.equal(h.lists().length,count);assert.equal(record(h.storage).result.id,'late-copy');
});

test('trash uses original management command and a protected receipt does not claim deletion',async()=>{
  const h=setup({api:async c=>{if(c.url.endsWith('/management'))return {status:'protected',reasons:[{message:'仍有在途任务'}],revision:9};}});await h.library.load();await action(h,3).click();await submit(h.root.querySelector('dialog'));assert.deepEqual({...h.posts()[0].body.payload,reason:undefined},{operation:'trash',target_type:'canvas',target_id:'canvas-0',reason:undefined});assert.ok(h.root.textContent.includes('仍有在途任务'));assert.equal(record(h.storage),null);assert.equal(h.notices.some(n=>n==='已移入回收站'),false);
});

test('browser storage failure prevents starting an unrecoverable creation',async()=>{
  const h=setup();await h.library.load();const d=await openCreate(h);await fillCreate(d);sessionStorage.setItem=()=>{throw new Error('quota');};await submit(d);assert.equal(h.posts().length,0);assert.ok(d.textContent.includes('恢复浏览器存储'));
});

test('embedded library pins initial scope and closes only after navigation succeeds',async()=>{
  const started=deferred(),waitOpen=deferred();const h=setup({navigate:async()=>{started.resolve();await waitOpen.promise;}}),opener=document.createElement('button');document.body.append(opener);opener.focus();const modal=await openCanvasLibraryDialog(h.ctx,{projectId:'p1',episodeId:'ep1',opener});const d=document.body.querySelector('.cl-management-dialog');assert.ok(d);const q=new URLSearchParams(h.lists()[0].url.split('?')[1]);assert.equal(q.get('project_id'),'p1');assert.equal(q.get('episode_id'),'ep1');const opening=d.querySelector('.cl-open').click();await started.promise;assert.equal(d.open,true);waitOpen.resolve();await opening;assert.equal(document.body.querySelector('.cl-management-dialog'),null);assert.equal(document.activeElement,opener);modal.close();
});

test('embedded navigation failure keeps the modal and Escape returns focus without a write',async()=>{
  const h=setup({navigate:async()=>{throw new Error('open failed');}}),opener=document.createElement('button');document.body.append(opener);opener.focus();await openCanvasLibraryDialog(h.ctx,{opener});const d=document.body.querySelector('.cl-management-dialog');await d.querySelector('.cl-open').click();assert.equal(d.open,true);assert.ok(d.textContent.includes('open failed'));await escapeDialog(d);assert.equal(document.activeElement,opener);assert.equal(h.posts().length,0);
});

test('embedded ready handle can close during loading and whenClosed resolves after cleanup',async()=>{
  const pending=deferred(),started=deferred();let ready,closedCount=0;const h=setup({api:async c=>{if(c.url.startsWith('/api/v1/canvas-library?')){started.resolve();return pending.promise;}}}),opener=document.createElement('button');document.body.append(opener);opener.focus();
  const opening=openCanvasLibraryDialog({...h.ctx,onDialogReady:handle=>{ready=handle;assert.equal(document.body.querySelector('.cl-management-dialog').open,true);assert.equal(h.lists().length,0);handle.whenClosed.then(()=>{closedCount++;assert.equal(document.body.querySelector('.cl-management-dialog'),null);assert.equal(document.activeElement,opener);});}},{opener});await started.promise;assert.ok(ready);ready.close();await ready.whenClosed;ready.close();assert.equal(closedCount,1);pending.resolve({items:h.rows,total:1,next_offset:null});assert.equal(await opening,ready);assert.equal(document.body.querySelector('.cl-management-dialog'),null);assert.equal(h.posts().length,0);
});

test('closing from embedded ready hook never starts library reads or reopens the dialog',async()=>{
  const h=setup();let ready;const result=await openCanvasLibraryDialog({...h.ctx,onDialogReady:handle=>{ready=handle;handle.close();}});await result.whenClosed;assert.equal(result,ready);assert.equal(h.calls.length,0);assert.equal(document.body.querySelector('.cl-management-dialog'),null);
});

test('empty successful page is an empty state while missing page fields are a retryable failure',async()=>{
  const h=setup({count:0});await h.library.load();assert.ok(h.root.querySelector('.cl-empty'));const bad=setup({api:async c=>{if(c.url.includes('/canvas-library?'))return {items:[]};}});await bad.library.load();assert.equal(bad.root.querySelector('.cl-empty'),null);assert.ok(bad.root.querySelector('.cl-retry'));assert.equal(bad.posts().length,0);
});

test('changing a filter flushes the latest search without a later duplicate timer',async()=>{
  const h=setup();await h.library.load();const search=h.root.querySelector('input');search.value='最新';await search.dispatch('input');const permission=filters(h)[3];permission.value='view';await permission.dispatch('change');await wait(330);assert.equal(h.lists().length,2);const q=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);assert.equal(q.get('query'),'最新');assert.equal(q.get('permission'),'view');
});

test('create episode failure has an explicit retry and preserves the entered name',async()=>{
  let failed=false;const h=setup({episodes:async()=>{if(!failed){failed=true;throw new Error('episodes offline');}return {items:[{id:'ep1',title:'第一集'}]};}});await h.library.load();const d=await openCreate(h);await fillCreate(d);assert.ok(d.querySelector('.cl-episode-retry'));assert.equal(d.querySelector('.cl-confirm').disabled,true);await submit(d);assert.equal(h.posts().length,0);await d.querySelector('.cl-episode-retry').click();assert.equal(d.querySelectorAll('input')[0].value,'新画布');const episode=d.querySelectorAll('select')[1];episode.value='ep1';await episode.dispatch('change');await submit(d);assert.equal(h.posts().length,1);
});

test('stale canvas scope on the authoritative rename read never sends a write',async()=>{
  const h=setup({api:async c=>{if(c.url.includes('/creative-canvases/')&&!c.options.method)return {id:'canvas-0',project_id:'p2',episode_id:'ep1',revision:8,canvas_revision:1,title:'foreign',document:{nodes:[],edges:[]}};}});await h.library.load();await action(h,0).click();await submit(h.root.querySelector('dialog'));assert.equal(h.posts().length,0);assert.equal(record(h.storage),null);
});


test('a missing collaboration state does not become a fabricated off switch',async()=>{
  const h=setup();delete h.rows[0].collaboration_enabled;await h.library.load();assert.equal(h.root.querySelector('.cl-collaboration-switch'),null);assert.equal(h.posts().length,0);
});

test('missing session write capability cannot enable controls from row permissions alone',async()=>{
  const h=setup();delete h.session.writeAvailable;await h.library.load();assert.equal(h.root.querySelector('.cl-create').disabled,true);assert.ok(h.root.querySelectorAll('.cl-icon-action').every(control=>control.disabled));await h.library.openCreate();assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.posts().length,0);
});

const platformOptions=()=>({projects:[{id:'p1',name:'可编辑项目',permissions:{can_edit:true}},{id:'p2',name:'仅查看项目',permissions:{can_edit:false}}],creators:[{id:'option-member',name:'选项成员'}]});
test('projects canvas tab uses global server options without inheriting the shell project or guessing permissions',async()=>{
  const h=setup({projects:()=>{throw new Error('legacy project catalogue must not supply canvas permissions');},api:async c=>{if(c.url==='/api/v1/canvas-library/options')return platformOptions();if(c.url.startsWith('/api/v1/canvas-library?'))return {items:[],total:0,next_offset:null};}});
  const platform=createProductionPlatform(h.root,h.ctx);await platform.load({page:'projects',tab:'canvases',project:'current-project',episode:'current-episode'});
  const q=new URLSearchParams(h.lists()[0].url.split('?')[1]);assert.equal(q.has('project_id'),false);assert.equal(q.has('episode_id'),false);assert.equal(filters(h)[0].value,'');assert.ok(filters(h)[2].options.some(o=>o.value==='member:option-member'));assert.equal(h.calls.length,2);assert.equal(h.root.querySelectorAll('input').length,1);assert.ok(h.root.textContent.includes('查看和管理所有项目中的画布'));
  await h.root.querySelector('.cl-create').click();const project=h.root.querySelector('dialog').querySelectorAll('select')[0];assert.equal(project.value,'');assert.deepEqual(project.options.map(o=>o.value),['','p1']);platform.suspend();
});

test('projects canvas tab obtains all episode pages from the original production projection',async()=>{
  const h=setup({api:async c=>{if(c.url==='/api/v1/canvas-library/options')return platformOptions();if(c.url.includes('/production-platform?')){const offset=Number(new URLSearchParams(c.url.split('?')[1]).get('offset'));assert.equal(new URLSearchParams(c.url.split('?')[1]).get('limit'),'100');return {episodes:{items:Array.from({length:offset===0?100:1},(_,i)=>({id:'episode-'+(offset+i),title:'集 '+(offset+i)})),next_offset:offset===0?100:null}};}}});
  const platform=createProductionPlatform(h.root,h.ctx);await platform.load({page:'projects',tab:'canvases'});const [project,episode]=filters(h);project.value='p1';await project.dispatch('change');assert.equal(episode.options.length,102);assert.ok(episode.options.some(o=>o.value==='episode-100'));assert.equal(h.calls.filter(c=>c.url.includes('/production-platform?')).length,2);platform.suspend();
});

test('platform navigation suspends canvas reads, search timers and action dialogs',async()=>{
  const old=deferred(),started=deferred();let delayed=false;const h=setup({projects:()=>[],api:async c=>{if(c.url==='/api/v1/canvas-library/options')return platformOptions();if(c.url.startsWith('/api/v1/canvas-library?')&&delayed){started.resolve();return old.promise;}}});
  const platform=createProductionPlatform(h.root,h.ctx);await platform.load({page:'projects',tab:'canvases'});await h.root.querySelector('.cl-create').click();assert.ok(h.root.querySelector('dialog'));const search=h.root.querySelector('.cl-toolbar').querySelector('input');search.value='pending search';await search.dispatch('input');delayed=true;const permission=filters(h)[3];permission.value='view';const changing=permission.dispatch('change');await started.promise;
  await platform.load({page:'projects'});assert.equal(h.root.querySelector('dialog'),null);old.resolve({items:[{...h.rows[0],title:'late canvas'}],total:1,next_offset:null});await changing;await wait(330);assert.equal(h.root.querySelector('.cl-library'),null);assert.ok(h.root.querySelector('.project-grid'));assert.equal(h.root.textContent.includes('late canvas'),false);assert.equal(h.lists().length,2);platform.suspend();
});

test('platform suspend stops episode pagination before issuing a later page',async()=>{
  const old=deferred(),started=deferred();const h=setup({api:async c=>{if(c.url==='/api/v1/canvas-library/options')return platformOptions();if(c.url.includes('/production-platform?')){started.resolve();return old.promise;}}});const platform=createProductionPlatform(h.root,h.ctx);await platform.load({page:'projects',tab:'canvases'});const project=filters(h)[0];project.value='p1';const reading=project.dispatch('change');await started.promise;platform.suspend();old.resolve({episodes:{items:[{id:'old',title:'旧集'}],next_offset:100}});await reading;assert.equal(h.calls.filter(c=>c.url.includes('/production-platform?')).length,1);assert.equal(filters(h)[1].options.some(o=>o.value==='old'),false);
});

for(const outcome of ['success','conflict'])test(`late original ${outcome} cannot replace or clear a newer pending request after receipt recovery`,async()=>{
  const old=deferred(),newer=deferred(),startedA=deferred(),startedB=deferred();let writes=0;const resultA={id:'copy-a',project_id:'p1',revision:9};const h=setup({api:async c=>{if(c.options.method==='POST'){if(++writes===1){startedA.resolve();return old.promise;}startedB.resolve();return newer.promise;}if(c.url.includes('/operation-receipts/'))return {found:true,response:resultA};}});
  await h.library.load();await action(h,1).click();const savingA=submit(h.root.querySelector('dialog'));await startedA.promise;const first=record(h.storage);await h.library.load();await h.root.querySelector('.cl-recovery-button').click();assert.equal(record(h.storage),null);
  await action(h,1).click();const savingB=submit(h.root.querySelector('dialog'));await startedB.promise;const intended=record(h.storage);assert.notEqual(first.request.body.idempotency_key,intended.request.body.idempotency_key);
  if(outcome==='success')old.resolve(resultA);else old.reject(Object.assign(new Error('late conflict'),{status:409}));await savingA;assert.deepEqual(record(h.storage),intended);assert.equal(h.posts().length,2);newer.resolve({id:'copy-b',project_id:'p1',revision:10});await savingB;assert.equal(record(h.storage),null);h.library.suspend();
});

for(const outcome of ['success','conflict'])test(`recovery claims the same key so an original late ${outcome} cannot mutate its recovery record`,async()=>{
  const old=deferred(),receipt=deferred(),started=deferred(),receiptStarted=deferred();const resultA={id:'copy-a',project_id:'p1',revision:9};const h=setup({api:async c=>{if(c.options.method==='POST'){started.resolve();return old.promise;}if(c.url.includes('/operation-receipts/')){receiptStarted.resolve();return receipt.promise;}}});
  await h.library.load();await action(h,1).click();const saving=submit(h.root.querySelector('dialog'));await started.promise;const original=record(h.storage);await h.library.load();const recovering=h.root.querySelector('.cl-recovery-button').click();await receiptStarted.promise;const claimed=record(h.storage);assert.equal(claimed.request.body.idempotency_key,original.request.body.idempotency_key);assert.notEqual(claimed.owner,original.owner);
  if(outcome==='success')old.resolve(resultA);else old.reject(Object.assign(new Error('late conflict'),{status:409}));await saving;assert.deepEqual(record(h.storage),claimed);receipt.resolve({found:true,response:resultA});await recovering;assert.equal(record(h.storage),null);assert.equal(h.posts().length,1);h.library.suspend();
});

for(const found of [true,false])test(`late receipt found=${found} cannot overwrite or resend after a newer recovery completed`,async()=>{
  const receipt=deferred(),started=deferred(),newer=deferred(),newStarted=deferred();let receipts=0,writes=0;const resultA={id:'copy-a',project_id:'p1',revision:9};const h=setup({api:async c=>{if(c.options.method==='POST'){if(++writes===1)throw new Error('lost response');newStarted.resolve();return newer.promise;}if(c.url.includes('/operation-receipts/')){if(++receipts===1){started.resolve();return receipt.promise;}return {found:true,response:resultA};}}});
  await h.library.load();await action(h,1).click();await submit(h.root.querySelector('dialog'));await h.library.load();const oldRecovery=h.root.querySelector('.cl-recovery-button').click();await started.promise;await h.library.load();await h.root.querySelector('.cl-recovery-button').click();assert.equal(record(h.storage),null);
  await action(h,1).click();const savingB=submit(h.root.querySelector('dialog'));await newStarted.promise;const intended=record(h.storage);receipt.resolve({found,response:found?resultA:null});await oldRecovery;assert.deepEqual(record(h.storage),intended);assert.equal(h.posts().length,2);newer.resolve({id:'copy-b',project_id:'p1',revision:10});await savingB;h.library.suspend();
});

test('pending export isolates the complete session identity and project without changing the stored record',async()=>{
  const h=setup({api:async c=>{if(c.options.method==='POST')throw new Error('unconfirmed');}});await h.library.load();assert.equal(readCanvasLibraryPending(h.session,'p1'),null);await action(h,1).click();await submit(h.root.querySelector('dialog'));const snapshot=record(h.storage);assert.deepEqual(readCanvasLibraryPending(h.session,'p1'),snapshot);assert.equal(readCanvasLibraryPending(h.session,'p2'),null);
  for(const field of ['actor','identityId','workspaceId'])assert.equal(readCanvasLibraryPending({...h.session,[field]:'other'},'p1'),null);const returned=readCanvasLibraryPending(h.session,'p1');returned.title='changed outside';assert.deepEqual(record(h.storage),snapshot);h.library.suspend();
});

test('pending export throws storage and JSON errors instead of treating them as no pending write',()=>{
  const h=setup(),key='vsc-canvas-library:v1:'+JSON.stringify([h.session.actor,h.session.identityId,h.session.workspaceId]);h.storage.set(key,'invalid JSON');assert.throws(()=>readCanvasLibraryPending(h.session,'p1'),SyntaxError);sessionStorage.getItem=()=>{throw new Error('storage denied');};assert.throws(()=>readCanvasLibraryPending(h.session,'p1'),/storage denied/);
});

test('creator filters and episode scope comply with the real list protocol',async()=>{
  const h=setup();await h.library.load({episodeId:'unscoped-episode'});assert.equal(new URLSearchParams(h.lists()[0].url.split('?')[1]).has('episode_id'),false);const creator=filters(h)[2];creator.value='member:member-2';await creator.dispatch('change');await wait(0);let q=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);assert.equal(q.get('creator_id'),'member-2');
  for(const value of ['mine','all']){creator.value=value;await creator.dispatch('change');await wait(0);q=new URLSearchParams(h.lists().at(-1).url.split('?')[1]);assert.equal(q.get('creator_filter'),value);assert.equal(q.has('creator_id'),false);}h.library.suspend();
});
