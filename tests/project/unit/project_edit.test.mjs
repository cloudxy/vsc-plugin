import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {createProductionPlatform} from '../../../src/vsc/interfaces/web/static/production-platform.js';

const {Document,Element}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.replaceWith=function(node){const parent=this.parentElement,index=parent.children.indexOf(this);parent.children[index]=node;node.parentElement=parent;this.parentElement=null;};
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const submit=dialog=>dialog.querySelector('form').dispatch('submit');
function setup({api,refresh,storage=new Map()}={}){
  const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;
  if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
  globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  const project={id:'project-1',name:'原项目',workspace_id:'space-1',workspace_name:'个人空间',storage_policy:'postgres-series-v1',profile_snapshot:{character_style:'2d'},counts:{episodes:2,images:0,videos:0}};
  const session={actor:'human',identityId:'id-1',workspaceId:'space-1',csrf:'csrf',writeAvailable:true,writable:true};
  const calls=[],notices=[];let refreshes=0;
  const platform=createProductionPlatform(root,{session:()=>session,projects:()=>[project],notice:value=>notices.push(String(value)),
    refreshProjects:async options=>{refreshes++;await refresh?.(options);},
    api:async(url,options={})=>{const body=typeof options.body==='string'?JSON.parse(options.body):options.body;const call={url,options,body};calls.push(call);if(api){const value=await api(call);if(value!==undefined)return value;}
      if(url.endsWith('/cover'))return {revision:8,selection:null,cover:null};
      if(options.method==='POST'){project.name=body.payload.title;project.counts.episodes=body.payload.episode_count;project.profile_snapshot.character_style=body.payload.character_style;return {project_id:project.id,revision:9};}
      return {revision:8,project,episode_count:2};}});
  const open=async()=>{assert.ok(!notices.length,notices.join(';'));await root.querySelectorAll('button').find(n=>n.getAttribute('aria-label')?.startsWith('重命名')).click();return root.querySelector('dialog');};
  return {root,platform,project,session,calls,notices,storage,open,get refreshes(){return refreshes;},posts:()=>calls.filter(c=>c.options.method==='POST')};
}
function fill(dialog,{name='编辑后的项目',count=3,style='3d'}={}){
  const inputs=dialog.querySelectorAll('input');inputs[0].value=name;inputs[1].value=String(count);
  for(const radio of inputs.filter(n=>n.type==='radio'))radio.checked=radio.value===style;
}

test('card pencil opens the complete original form and saves existing project plus refreshed card',async()=>{
  const h=setup();await h.platform.load({page:'projects'});const d=await h.open(),inputs=d.querySelectorAll('input');
  assert.equal(inputs[0].value,'原项目');assert.equal(inputs[0].maxLength,50);assert.equal(inputs[1].value,'2');assert.equal(inputs[1].max,'500');
  assert.equal(inputs.find(n=>n.type==='radio'&&n.checked).value,'2d');assert.ok(d.querySelector('.project-cover-field'));
  fill(d);await submit(d);assert.equal(h.posts().length,1);assert.deepEqual(h.posts()[0].body.payload,{operation:'edit',title:'编辑后的项目',episode_count:3,character_style:'3d'});
  assert.equal(h.posts()[0].body.expected_revision,8);assert.equal(h.refreshes,1);assert.ok(h.root.textContent.includes('编辑后的项目'));assert.equal(h.root.querySelector('dialog'),null);
});

test('reducing episodes and invalid fields preserve the edit without a write',async()=>{
  const h=setup();await h.platform.load({page:'projects'});const d=await h.open();
  for(const values of [{count:1},{count:501},{count:1.2},{name:' '},{name:'x'.repeat(51)}]){fill(d,values);await submit(d);assert.equal(h.posts().length,0);assert.equal(d.querySelector('input').value,values.name??'编辑后的项目');}
  assert.equal(d.querySelector('.project-create-confirm').disabled,false);
});

test('an unconfirmed edit replays identical body after reopening and cannot create episodes twice',async()=>{
  let lost=false;const h=setup({api:async c=>{if(c.options.method==='POST'&&!lost){lost=true;throw new Error('response lost');}}});
  await h.platform.load({page:'projects'});let d=await h.open();fill(d);await submit(d);assert.ok(d.textContent.includes('原编辑操作已保留'));
  await d.close();d=await h.open();assert.equal(d.querySelector('input').value,'编辑后的项目');await submit(d);
  assert.equal(h.posts().length,2);assert.deepEqual(h.posts()[0].body,h.posts()[1].body);assert.equal(h.storage.size,0);
});

test('after write success a failed directory refresh retries only readback',async()=>{
  let failed=false;const h=setup({refresh:async()=>{if(!failed){failed=true;throw new Error('directory offline');}}});
  await h.platform.load({page:'projects'});const d=await h.open();fill(d);await submit(d);assert.ok(d.textContent.includes('刷新未完成'));await submit(d);
  assert.equal(h.posts().length,1);assert.equal(h.refreshes,2);assert.equal(h.storage.size,0);
});

test('conflict preserves fields, reloads the baseline explicitly and then uses a new request',async()=>{
  let conflict=false;const h=setup({api:async c=>{if(c.options.method==='POST'&&!conflict){conflict=true;throw Object.assign(new Error('changed baseline'),{status:409});}if(conflict&&c.url.includes('management?'))return {revision:10,project:h.project,episode_count:2};}});
  await h.platform.load({page:'projects'});const d=await h.open();fill(d);await submit(d);assert.equal(d.querySelector('input').value,'编辑后的项目');assert.equal(d.querySelector('input').disabled,true);
  await submit(d);assert.equal(h.posts().length,1);assert.equal(d.querySelector('input').disabled,false);await submit(d);
  assert.equal(h.posts()[1].body.expected_revision,10);assert.notEqual(h.posts()[0].body.idempotency_key,h.posts()[1].body.idempotency_key);
});

test('loading failure is retryable and does not turn into an empty-project write',async()=>{
  let failed=false;const h=setup({api:async c=>{if(c.url.includes('management?')&&!failed){failed=true;throw new Error('offline');}}});
  await h.platform.load({page:'projects'});const d=await h.open();assert.equal(d.querySelector('input').disabled,true);assert.equal(h.posts().length,0);await submit(d);assert.equal(d.querySelector('input').disabled,false);assert.equal(h.posts().length,0);
});

for(const change of ['scope','identity'])test(`late edit receipt after ${change} cannot refresh or alter the new view`,async()=>{
  const wait=deferred(),started=deferred();const h=setup({api:async c=>{if(c.options.method==='POST'){started.resolve();await wait.promise;return {revision:9};}}});
  await h.platform.load({page:'projects'});const d=await h.open();fill(d);const saving=submit(d);await started.promise;
  assert.ok(d.querySelectorAll('input').every(n=>n.disabled));await submit(d);assert.equal(h.posts().length,1);
  if(change==='scope')await h.platform.load({page:'projects'});else if(change==='identity')h.session.identityId='id-2';else h.session.workspaceId='space-2';
  wait.resolve();await saving;assert.equal(h.refreshes,0);assert.equal(h.root.querySelector('dialog'),null);assert.ok([...h.storage.values()].some(s=>JSON.parse(s).saved));
});

test('unsaved form fields survive close and reopening without issuing a write',async()=>{
  const h=setup();await h.platform.load({page:'projects'});let d=await h.open();fill(d);await d.querySelector('form').dispatch('input');await d.close();d=await h.open();
  assert.equal(d.querySelector('input').value,'编辑后的项目');assert.equal(d.querySelectorAll('input')[1].value,'3');assert.equal(h.posts().length,0);
});

test('clear cover uses the original automatic-cover command and a failed refresh cannot repeat it',async()=>{
  let clearCalls=0,failed=false;const h=setup({api:async c=>{if(c.url.endsWith('/cover')){if(c.options.method==='POST'){clearCalls++;assert.deepEqual(c.body.payload,{media_id:null});return {revision:10};}return {revision:8,selection:{media_id:'old-cover'},cover:{content_url:'/old-cover.png'}};}},refresh:async()=>{if(!failed){failed=true;throw new Error('offline');}}});
  await h.platform.load({page:'projects'});const d=await h.open();assert.equal(d.querySelector('.project-cover-preview').querySelector('img').src,'/old-cover.png');
  const clear=d.querySelector('.project-cover-remove');assert.equal(clear.textContent,'恢复自动封面');await clear.click();fill(d);await submit(d);await submit(d);assert.equal(clearCalls,1);assert.equal(h.posts().length,2);
});

test('edited cover upload recovers the same selection without saving metadata or importing twice',async()=>{
  let uploaded=false,processed=false,lost=false;const h=setup({api:async c=>{
    if(c.url.endsWith('/cover')){if(c.options.method!=='POST')return {revision:8,selection:null,cover:null};if(!lost){lost=true;throw new Error('cover response lost');}return {revision:13,selection:{media_id:'media-1'},cover:{content_url:'/edited-cover.png'}};}
    if(c.url.endsWith('/media-imports'))return {revision:10,id:'batch-1'};
    if(c.options.method==='PUT'){uploaded=true;return {revision:11};}
    if(c.url.endsWith('/process')){processed=true;return {revision:12,media_id:'media-1'};}
    if(c.url.includes('/media-imports/'))return {revision:processed?12:uploaded?11:10,items:[{id:'item-1',uploaded_bytes:uploaded?4:0,has_upload:uploaded,media_id:processed?'media-1':null}]};
  }});
  await h.platform.load({page:'projects'});let d=await h.open();fill(d);
  globalThis.createImageBitmap=async()=>({width:2,height:2,close(){}});
  const file=d.querySelectorAll('input').find(n=>n.type==='file');file.files=[new File([new Uint8Array([1,2,3,4])],'cover.png',{type:'image/png'})];await file.dispatch('change');await submit(d);
  assert.ok(d.textContent.includes('原编辑操作已保留'));await d.close();d=await h.open();await submit(d);
  assert.equal(h.posts().filter(c=>c.url.endsWith('/management')).length,1);assert.equal(h.posts().filter(c=>c.url.endsWith('/media-imports')).length,1);assert.equal(h.calls.filter(c=>c.options.method==='PUT').length,1);
  const selections=h.posts().filter(c=>c.url.endsWith('/cover'));assert.equal(selections.length,2);assert.deepEqual(selections[0].body,selections[1].body);assert.equal(h.storage.size,0);
});

test('an explicit retry after a cover conflict reads a fresh revision without repeating the saved project edit',async()=>{
  let conflict=false;const h=setup({api:async c=>{if(c.url.endsWith('/cover')){
    if(c.options.method!=='POST')return {revision:conflict?20:8,selection:{media_id:'old'},cover:{content_url:'/old.png'}};
    if(!conflict){conflict=true;throw Object.assign(new Error('cover revision changed'),{status:409});}
    assert.equal(c.body.expected_revision,20);return {revision:21};
  }}});
  await h.platform.load({page:'projects'});const d=await h.open();await d.querySelector('.project-cover-remove').click();fill(d);await submit(d);
  assert.ok(d.textContent.includes('重试会读取最新版本'));assert.equal(h.posts().length,2);await submit(d);
  assert.equal(h.posts().filter(c=>c.url.endsWith('/management')).length,1);const attempts=h.posts().filter(c=>c.url.endsWith('/cover'));
  assert.equal(attempts[0].body.idempotency_key,attempts[1].body.idempotency_key);assert.equal(h.storage.size,0);
});
