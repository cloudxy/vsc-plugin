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
function setup({api,refresh,navigate,storage=new Map()}={}){
  const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;
  globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
  if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
  globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  const session={actor:'human',identityId:'id-1',workspaceId:'space-1',csrf:'csrf',writeAvailable:true,writable:true};
  const row={id:'ep-1',title:'原剧集',shot_count:2},calls=[],notices=[],navigations=[];let refreshes=0;
  const platform=createProductionPlatform(root,{session:()=>session,projectName:()=> '当前项目',notice:value=>notices.push(String(value)),setRevision:r=>session.revision=r,
    refreshProjects:async options=>{refreshes++;await refresh?.(options);},navigate:async(...args)=>{navigations.push(args);await navigate?.(...args);},
    api:async(url,options={})=>{const body=typeof options.body==='string'?JSON.parse(options.body):options.body,call={url,options,body};calls.push(call);if(api){const value=await api(call);if(value!==undefined)return value;}
      if(url.includes('/episode-editor?'))return {project_id:'project-1',revision:8,episode:url.includes('episode_id=')?{...row,position:1}:null,parent_id:'work-1',works:[{id:'work-1',title:'第一部'}],max_position:url.includes('episode_id=')?2:3,needs_parent:false};
      if(url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:{id:'canvas-latest'}};
      if(url.endsWith('/episode-save'))return {revision:9,episode_id:body.payload.episode_id||'ep-new',episode_index:0};
      if(url.endsWith('/creative-canvases'))return {revision:9,id:'canvas-new'};
      if(url.includes('/creative-canvases/'))return {id:'canvas-new',episode_id:'ep-1'};
      return {project_id:'project-1',revision:8,read_only:false,episodes:{items:[row],total:1,works:[{id:'work-1',title:'第一部'}],next_offset:null}};}});
  const open=async(edit=true)=>{const button=edit?root.querySelector('.episode-card-menu').querySelector('button'):root.querySelector('.episode-toolbar').querySelectorAll('button').find(n=>n.classList.contains('primary'));await button.click();const d=root.querySelector('dialog');assert.ok(d,notices.join(';'));return d;};
  return {root,platform,session,row,calls,notices,navigations,storage,open,get refreshes(){return refreshes;},posts:()=>calls.filter(c=>c.options.method==='POST')};
}
const load=h=>h.platform.load({page:'project',project:'project-1'});
function fill(d,{title='修改后',count=3,position='2'}={}){const inputs=d.querySelectorAll('input');inputs[0].value=title;inputs[1].value=String(count);inputs[2].value=position;}
const tool=(h,index=0)=>h.root.querySelectorAll('.episode-tool')[index];

test('episode card has four guarded buttons and retains the original specialist and batch entries',async()=>{
  const h=setup();await load(h);assert.equal(h.root.querySelectorAll('.episode-tool').length,4);
  const expected=[['creative-canvas',{episode:'ep-1',task_target:'canvas-latest'}],['intelligent-creation',{episode:'ep-1'}],['classic-production',{kind:'image',episode:'ep-1'}],['classic-production',{kind:'video',episode:'ep-1'}]];
  for(let n=0;n<4;n++){assert.equal(tool(h,n).tagName,'BUTTON');await tool(h,n).pressKey('Enter');assert.deepEqual(h.navigations[n],[expected[n][0],null,'project-1',expected[n][1]]);}
  assert.equal(h.posts().length,0);assert.ok(h.root.querySelector('.episode-card-menu').querySelectorAll('a').length>=2);assert.ok(h.root.querySelector('.episode-project-tools').querySelector('button'));
});

test('edit loads authoritative fields and saves title shots and same-work position through one command',async()=>{
  const h=setup();await load(h);const d=await h.open(),inputs=d.querySelectorAll('input');assert.equal(inputs[0].value,'原剧集');assert.equal(inputs[0].maxLength,50);assert.equal(inputs[1].max,'500');assert.equal(inputs[2].value,'');
  fill(d);await submit(d);assert.equal(h.posts().length,1);assert.deepEqual(h.posts()[0].body.payload,{episode_id:'ep-1',title:'修改后',shot_count:3,position:2});assert.equal(h.posts()[0].body.expected_revision,8);assert.equal(h.refreshes,1);assert.equal(h.root.querySelector('dialog'),null);
});

test('create uses single episode endpoint and preserves bulk form in tools',async()=>{
  const h=setup();await load(h);const d=await h.open(false);fill(d,{count:500,position:''});await submit(d);
  assert.equal(h.posts().length,1);assert.deepEqual(h.posts()[0].body.payload,{title:'修改后',shot_count:500,parent_id:'work-1'});
  await h.root.querySelector('.episode-project-tools').querySelector('button').click();assert.ok(h.root.querySelector('textarea'));
});

test('invalid names counts reduction and positions keep draft without writing',async()=>{
  const h=setup();await load(h);const d=await h.open();
  for(const values of [{title:' '},{title:'x'.repeat(51)},{count:1},{count:501},{count:1.5},{position:'3'},{position:'0'},{position:'1.5'}]){fill(d,values);await submit(d);assert.equal(h.posts().length,0);assert.equal(d.querySelector('input').disabled,false);}
  fill(d);await d.querySelector('form').dispatch('input');await d.close();const reopened=await h.open();assert.equal(reopened.querySelector('input').value,'修改后');assert.equal(reopened.querySelectorAll('input')[2].value,'2');
});

test('editor read failure and cross-scope results never become an empty write',async()=>{
  let bad=true;const h=setup({api:async c=>{if(c.url.includes('/episode-editor?')&&bad)return {project_id:'other',episode:{id:'ep-1'}};}});
  await load(h);const d=await h.open();assert.equal(d.querySelector('input').disabled,true);await submit(d);assert.equal(h.posts().length,0);bad=false;await submit(d);assert.equal(d.querySelector('input').disabled,false);assert.equal(h.posts().length,0);
});

for(const status of [undefined,403])test(`unconfirmed episode write ${status||'network failure'} survives reopened form and replays same request`,async()=>{
  let failed=false;const h=setup({api:async c=>{if(c.options.method==='POST'&&!failed){failed=true;throw Object.assign(new Error('unconfirmed'),{status});}}});
  await load(h);let d=await h.open();fill(d);await submit(d);assert.equal(d.querySelector('input').disabled,true);await d.close();d=await h.open();await submit(d);assert.equal(h.posts().length,2);assert.deepEqual(h.posts()[0].body,h.posts()[1].body);
});

test('saved episode with failed refresh retries only readback',async()=>{
  let failed=false;const h=setup({refresh:async()=>{if(!failed){failed=true;throw new Error('refresh offline');}}});await load(h);const d=await h.open();fill(d);await submit(d);assert.ok(d.textContent.includes('只刷新'));await submit(d);assert.equal(h.posts().length,1);assert.equal(h.refreshes,2);
});

test('episode conflict preserves fields and requires fresh baseline before a new request',async()=>{
  let conflicted=false;const h=setup({api:async c=>{if(c.url.endsWith('/episode-save')&&!conflicted){conflicted=true;throw Object.assign(new Error('stale'),{status:409});}if(c.url.includes('/episode-editor?')&&conflicted)return {project_id:'project-1',revision:20,episode:{...h.row,position:1},parent_id:'work-1',works:[{id:'work-1',title:'一部'}],max_position:2};}});
  await load(h);const d=await h.open();fill(d);await submit(d);assert.equal(d.querySelector('input').value,'修改后');await submit(d);assert.equal(h.posts().length,1);await submit(d);assert.equal(h.posts()[1].body.expected_revision,20);assert.notEqual(h.posts()[0].body.idempotency_key,h.posts()[1].body.idempotency_key);
});

for(const change of ['scope','identity'])test(`late episode response after ${change} keeps receipt without changing current view`,async()=>{
  const waiting=deferred(),started=deferred();const h=setup({api:async c=>{if(c.url.endsWith('/episode-save')){started.resolve();await waiting.promise;return {episode_id:'ep-1',episode_index:0,revision:9};}}});
  await load(h);const d=await h.open();fill(d);const saving=submit(d);await started.promise;await submit(d);assert.equal(h.posts().length,1);
  if(change==='scope')await load(h);else if(change==='identity')h.session.identityId='id-2';else h.session.workspaceId='space-2';waiting.resolve();await saving;assert.equal(h.refreshes,0);assert.equal(h.root.querySelector('dialog'),null);assert.ok([...h.storage.values()].some(s=>JSON.parse(s).phase==='readback'));
});

test('changing work rereads its range and cannot submit while loading',async()=>{
  const waiting=deferred(),started=deferred();const h=setup({api:async c=>{if(c.url.includes('/episode-editor?')){if(c.url.includes('parent_id=work-2')){started.resolve();await waiting.promise;return {project_id:'project-1',revision:9,episode:null,parent_id:'work-2',works:[{id:'work-1',title:'一'},{id:'work-2',title:'二'}],max_position:1};}return {project_id:'project-1',revision:8,episode:null,parent_id:null,works:[{id:'work-1',title:'一'},{id:'work-2',title:'二'}],max_position:1,needs_parent:true};}}});
  await load(h);const d=await h.open(false);fill(d);await submit(d);assert.equal(h.posts().length,0);const parent=d.querySelector('select');parent.value='work-2';const changing=parent.dispatch('change');await started.promise;await submit(d);assert.equal(h.posts().length,0);waiting.resolve();await changing;assert.equal(d.querySelectorAll('input')[2].value,'');await submit(d);assert.equal(h.posts()[0].body.payload.parent_id,'work-2');assert.equal(h.posts()[0].body.expected_revision,9);
});

test('empty canvas entry creates one stable request and recovers lost response',async()=>{
  let failed=false;const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:null};if(c.url.endsWith('/creative-canvases')&&!failed){failed=true;throw new Error('lost');}}});
  await load(h);await tool(h).click();assert.equal(h.navigations.length,0);await tool(h).click();assert.equal(h.posts().length,2);assert.deepEqual(h.posts()[0].body,h.posts()[1].body);assert.equal(h.calls.filter(c=>c.url.includes('/episode-entry?')).length,1);assert.equal(h.navigations[0][3].task_target,'canvas-new');assert.equal(h.storage.size,0);
});

test('read failure or wrong episode cannot trigger canvas creation',async()=>{
  let mode='fail';const h=setup({api:async c=>{if(c.url.includes('/episode-entry?')){if(mode==='fail')throw new Error('offline');return {project_id:'project-1',episode_id:'other',revision:8,canvas:null};}}});
  await load(h);await tool(h).click();mode='wrong';await tool(h).click();assert.equal(h.posts().length,0);assert.equal(h.navigations.length,0);
});

test('confirmed canvas with navigation failure retries a read without a second creation',async()=>{
  let failed=false;const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:null};},navigate:async()=>{if(!failed){failed=true;throw new Error('route failed');}}});
  await load(h);await tool(h).click();await tool(h).click();assert.equal(h.posts().length,1);assert.equal(h.calls.filter(c=>c.url.includes('/creative-canvases/canvas-new')).length,1);assert.equal(h.storage.size,0);
});

test('pending canvas authorization failure preserves request and duplicate clicks are locked',async()=>{
  const wait=deferred(),started=deferred();let first=true;const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:null};if(c.url.endsWith('/creative-canvases')&&first){first=false;started.resolve();await wait.promise;throw Object.assign(new Error('expired session'),{status:403});}}});
  await load(h);const pending=tool(h).click();await started.promise;await tool(h).click();assert.equal(h.posts().length,1);wait.resolve();await pending;assert.equal(h.storage.size,1);await tool(h).click();assert.deepEqual(h.posts()[0].body,h.posts()[1].body);
});

for(const change of ['scope','identity'])test(`late canvas creation after ${change} stores receipt and cannot navigate`,async()=>{
  const wait=deferred(),started=deferred();const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:null};if(c.url.endsWith('/creative-canvases')){started.resolve();await wait.promise;return {id:'canvas-new'};}}});
  await load(h);const pending=tool(h).click();await started.promise;if(change==='scope')await load(h);else if(change==='identity')h.session.identityId='id-2';else h.session.workspaceId='space-2';wait.resolve();await pending;assert.equal(h.navigations.length,0);assert.ok([...h.storage.values()].some(s=>JSON.parse(s).canvas_id==='canvas-new'));
});

test('missing canvas field is an incomplete read and cannot masquerade as an empty list',async()=>{
  const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8};}});await load(h);await tool(h).click();assert.equal(h.posts().length,0);assert.equal(h.navigations.length,0);assert.ok(h.notices[0].includes('读取不完整'));
});

test('read-only member can open an existing canvas but cannot create an empty one',async()=>{
  let empty=false;const h=setup({api:async c=>{if(c.url.includes('/episode-entry?'))return {project_id:'project-1',episode_id:'ep-1',revision:8,canvas:empty?null:{id:'canvas-latest'}};}});h.session.writable=false;h.session.writeAvailable=false;await load(h);await tool(h).click();assert.equal(h.navigations.length,1);empty=true;await tool(h).click();assert.equal(h.posts().length,0);assert.equal(h.navigations.length,1);
});
