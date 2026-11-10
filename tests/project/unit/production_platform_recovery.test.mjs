import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createProductionPlatform} from '../../../src/vsc/interfaces/web/static/production-platform.js';

const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=async()=>{for(let n=0;n<8;n++)await Promise.resolve();};
const emptyDiscovery=()=>({recent:[],skills:[],templates:[],tutorials:[],projects:[]});

function setup({storage=new Map(),api,refresh,navigate,projects=[],createEmptyCanvasProject}={}){
  const document=new Document(''),root=document.createElement('section');document.body.append(root);
  globalThis.document=document;if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
  globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
  globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
  const calls=[],routes=[],notices=[];let refreshes=0;
  const session={actor:'human',csrf:'csrf',revision:0,writable:true,writeAvailable:true};
  const ctx={session:()=>session,projects:()=>projects,createEmptyCanvasProject,projectName:()=>'',setRevision(){},notice:value=>notices.push(String(value)),
    refreshProjects:async(options)=>{refreshes++;await refresh?.(options);},
    navigate:async(...args)=>{routes.push(args);await navigate?.(...args);},
    api:async(url,options={})=>{const body=typeof options.body==='string'?JSON.parse(options.body):options.body||null;const call={url,options,body};calls.push(call);if(api)return api(call);if(url==='/api/v1/discovery')return emptyDiscovery();return url.includes('episode-batches')?{revision:2}:{id:'p-created',revision:1};}};
  const platform=createProductionPlatform(root,ctx);
  const buttons=label=>root.querySelectorAll('button').filter(n=>n.textContent===label);
  async function open(){await root.querySelectorAll('button').find(node=>node.textContent.includes('新建项目')).click();return root.querySelectorAll('dialog').at(-1);}
  const posts=()=>calls.filter(call=>call.options.method==='POST');
  return {root,session,platform,storage,calls,routes,notices,posts,buttons,open,get refreshes(){return refreshes;}};
}

function fill(dialog,{name='新片',count=2,style='3d'}={}){
  const inputs=dialog.querySelectorAll('input'),title=inputs[0],episodes=inputs[1];title.value=name;episodes.value=String(count);for(const radio of inputs.filter(input=>input.type==='radio'))radio.checked=radio.value===style;
}
const submit=dialog=>dialog.querySelector('form').dispatch('submit');
const originalFile=()=>new File([new Uint8Array([1,2,3,4])],'cover.png',{type:'image/png'});
async function chooseCover(dialog,file=originalFile()){
  globalThis.createImageBitmap=async selected=>{if(selected.name==='bad.png')throw Object.assign(new Error('bad image'),{name:'InvalidStateError'});return {width:4,height:4,close(){}};};
  const input=dialog.querySelectorAll('input').find(input=>input.type==='file');input.files=[file];await input.dispatch('change');return input;
}
function coverBackend({lose=null,pause=null}={}){
  const receipts=new Map();let revision=0,status='awaiting_upload',media=null,failed=false;
  const mutations={project:0,batch:0,upload:0,process:0,cover:0};
  async function api(call){
    const {url,options,body}=call;
    if(options.method==='PUT'){mutations.upload++;status='uploaded';revision=3;if(lose==='upload'&&!failed){failed=true;throw new Error('lost upload response');}return {uploaded_bytes:4,status,revision};}
    if(options.method!=='POST')return {batch:{id:'b-cover'},revision,items:[{id:'i-cover',status,uploaded_bytes:status==='awaiting_upload'?0:4,has_upload:status!=='awaiting_upload',media_id:media}]};
    assert.equal(options.headers['X-CSRF-Token'],'csrf');
    const key=url+':'+body.idempotency_key;if(receipts.has(key))return receipts.get(key);
    let stage,result;
    if(url==='/api/v1/projects'){stage='project';revision=0;result={id:'p-created',revision};}
    else if(url.includes('episode-batches')){stage='episodes';revision=1;result={revision};}
    else if(url.endsWith('/media-imports')){stage='batch';revision=2;assert.equal(body.payload.rights,'unknown');assert.equal(body.payload.files[0].size_bytes,4);result={id:'b-cover',revision};}
    else if(url.endsWith('/process')){stage='process';status='completed';media='m-cover';revision=4;result={media_id:media,status,revision};}
    else if(url.endsWith('/cover')){stage='cover';revision=5;result={project_id:'p-created',revision,selection:{id:'cv1',media_id:media},cover:{media_id:media,content_url:'/controlled-cover.png'}};}
    else throw new Error('Unexpected '+url);
    if(stage in mutations)mutations[stage]++;receipts.set(key,result);
    if(stage===pause?.stage){pause.started.resolve();await pause.release.promise;}
    if(stage===lose&&!failed){failed=true;throw new Error('lost '+stage+' response');}return result;
  }
  return {api,mutations};
}

test('the project dialog exposes the 50-character counter, bounded stepper, default live-action radios and optional cover',async()=>{
  const h=setup();await h.platform.load({page:'projects'});const dialog=await h.open();
  const inputs=dialog.querySelectorAll('input'),name=inputs[0],count=inputs[1],radios=inputs.filter(input=>input.type==='radio');
  assert.equal(name.maxLength,50);name.value='新作品';await name.dispatch('input');assert.equal(dialog.querySelector('.project-name-count').textContent,'3 / 50');
  assert.equal(count.min,'1');assert.equal(count.max,'500');assert.equal(count.step,'1');
  const step=label=>dialog.querySelectorAll('button').find(button=>button.getAttribute('aria-label')===label);
  await step('减少集数').click();assert.equal(count.value,'1');await step('增加集数').click();assert.equal(count.value,'2');count.value='500';await step('增加集数').click();assert.equal(count.value,'500');
  assert.deepEqual(radios.map(radio=>[radio.value,radio.checked]),[['2d',false],['3d',false],['live',true]]);
  assert.equal(dialog.querySelector('select'),null);assert.ok(dialog.textContent.includes('大小不超过5MB'));assert.ok(dialog.querySelectorAll('button').some(button=>button.textContent==='确定'));
  await dialog.querySelector('.project-create-close').click();assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.posts().length,0);
});

test('bad images and files above 5MiB are rejected before project creation',async()=>{
  const h=setup();await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);
  await chooseCover(dialog,new File([new Uint8Array(5*1024*1024+1)],'large.png'));assert.ok(dialog.textContent.includes('封面大小不能超过5MB'));assert.equal(dialog.querySelector('.project-cover-preview').querySelector('img'),null);
  await chooseCover(dialog,new File(['broken'],'bad.png'));assert.ok(dialog.textContent.includes('请选择可读取的图像文件'));assert.equal(h.posts().length,0);
});

test('the legacy new-canvas form keeps its original fields and does not inherit the project-cover UI',async()=>{
  const h=setup();await h.platform.load({page:'projects',create:'canvas'});const dialog=h.root.querySelector('dialog');
  assert.equal(dialog.classList.contains('project-create-dialog'),false);assert.equal(dialog.querySelectorAll('input').length,1);assert.equal(dialog.querySelector('.project-cover-field'),null);assert.equal(dialog.querySelector('.project-name-count'),null);
  dialog.querySelector('input').value='画布项目';await submit(dialog);assert.equal(h.posts().length,1);assert.equal(h.routes[0][0],'creative-canvas');
});

for(const stage of ['batch','upload','process','cover'])test(`cover recovery after a lost ${stage} response keeps one project, import, media and selection`,async()=>{
  const backend=coverBackend({lose:stage}),h=setup({api:backend.api});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await chooseCover(dialog);await submit(dialog);
  assert.ok(dialog.textContent.includes('原创建操作已保留'));const fixed=JSON.parse([...h.storage.values()][0]);assert.equal(fixed.project_id,'p-created');assert.equal(fixed.cover.size_bytes,4);
  await submit(dialog);assert.deepEqual(backend.mutations,{project:1,batch:1,upload:1,process:1,cover:1});assert.equal(h.routes.length,1);assert.equal(h.storage.size,0);
  if(stage==='cover'){const calls=h.posts().filter(call=>call.url.endsWith('/cover'));assert.equal(calls.length,2);assert.deepEqual(calls[0].body,calls[1].body);}
});

test('closing an import wait retains the File in this component and resumes the same project',async()=>{
  const pause={stage:'batch',started:deferred(),release:deferred()},backend=coverBackend({pause}),h=setup({api:backend.api});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await chooseCover(dialog);
  const pending=submit(dialog);await pause.started.promise;await dialog.close();pause.release.resolve();await pending;assert.equal(h.routes.length,0);
  const restored=await h.open();assert.ok(restored.querySelector('.project-cover-preview').querySelector('img'));await submit(restored);assert.equal(backend.mutations.project,1);assert.equal(backend.mutations.batch,1);assert.equal(h.routes.length,1);
});

test('after a component restart, an unuploaded cover requires the same SHA file without recreating the project',async()=>{
  const backend=coverBackend({lose:'batch'}),storage=new Map(),h=setup({api:backend.api,storage});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await chooseCover(dialog);await submit(dialog);h.platform.suspend();
  const next=setup({api:backend.api,storage});await next.platform.load({page:'projects'});const restored=await next.open();await submit(restored);assert.ok(restored.textContent.includes('请重新选择上次的原封面文件继续上传'));
  await chooseCover(restored,new File([new Uint8Array([9,8,7,6])],'other.png'));assert.ok(restored.textContent.includes('文件内容不能更换'));assert.equal(backend.mutations.upload,0);
  await chooseCover(restored);await submit(restored);assert.equal(backend.mutations.project,1);assert.equal(backend.mutations.batch,1);assert.equal(backend.mutations.upload,1);assert.equal(next.routes.length,1);
});

test('an actor change during cover selection cannot navigate or transfer the original cover to the new actor',async()=>{
  const pause={stage:'cover',started:deferred(),release:deferred()},backend=coverBackend({pause}),h=setup({api:backend.api});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await chooseCover(dialog);const pending=submit(dialog);await pause.started.promise;
  h.session.actor='new-actor';const fresh=await h.open();fill(fresh,{name:'新身份稿件'});pause.release.resolve();await pending;
  assert.equal(h.routes.length,0);assert.equal(h.refreshes,0);assert.equal(fresh.querySelector('input').value,'新身份稿件');assert.equal(fresh.querySelector('.project-cover-preview').querySelector('img'),null);
});

test('normal multi-batch creation opens the original project only after directory readback',async()=>{
  const h=setup();await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog,{count:51});
  await submit(dialog);
  assert.equal(h.posts().length,3);assert.equal(h.posts()[0].body.payload.character_style,'3d');
  assert.equal(h.posts()[1].body.payload.titles.length,50);assert.deepEqual(h.posts()[2].body.payload.titles,['第51集']);
  assert.equal(h.posts()[2].body.expected_revision,2);assert.equal(h.refreshes,1);
  assert.deepEqual(h.routes,[['project',null,'p-created',{}]]);assert.equal(h.storage.size,0);assert.equal(h.root.querySelector('dialog'),null);
});

test('the original creation dialog closes when the shell suspends this view during navigation',async()=>{
  const h=setup({navigate:()=>h.platform.suspend()});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await submit(dialog);
  assert.equal(dialog.open,false);assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.storage.size,0);assert.equal(h.routes.length,1);
});

for(const interruption of ['close','scope','actor'])test(`a late episode batch after ${interruption} preserves progress and cannot continue or navigate`,async()=>{
  const batch=deferred();const h=setup({api:call=>call.url.includes('episode-batches')?batch.promise:{id:'p-created',revision:1}});
  await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog,{count:51});const pending=submit(dialog);await tick();
  assert.equal(h.posts().length,2);await submit(dialog);assert.equal(h.posts().length,2,'duplicate submit is ignored while pending');
  let newDraft;
  if(interruption==='close')await dialog.close();
  else if(interruption==='scope')await h.platform.load({page:'projects'});
  else{h.session.actor='other';newDraft=await h.open();fill(newDraft,{name:'其他人的新稿'});}
  const before=h.root.textContent;batch.resolve({revision:2});await pending;
  assert.equal(h.posts().length,2);assert.equal(h.refreshes,0);assert.equal(h.routes.length,0);assert.equal(h.notices.length,0);
  if(newDraft){assert.equal(newDraft.querySelector('input').value,'其他人的新稿');assert.equal(newDraft.open,true);}else assert.equal(h.root.textContent,before);
  const retained=JSON.parse([...h.storage.values()][0]);assert.equal(retained.project_id,'p-created');assert.equal(retained.offset,50);assert.equal(retained.revision,2);
});

test('closing during project creation retains the successful receipt and resumes without another project',async()=>{
  const created=deferred();let projectPosts=0;
  const h=setup({api:call=>call.url.includes('episode-batches')?{revision:2}:(projectPosts++,created.promise)});
  await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);const pending=submit(dialog);await tick();
  await dialog.close();created.resolve({id:'p-created',revision:1});await pending;
  assert.equal(h.posts().length,1);assert.equal(h.routes.length,0);
  const recovered=await h.open();assert.equal(recovered.querySelector('input').value,'新片');assert.equal(recovered.querySelector('input').disabled,true);
  await submit(recovered);assert.equal(projectPosts,1);assert.equal(h.posts().length,2);assert.equal(h.routes[0][2],'p-created');assert.equal(h.storage.size,0);
});

test('a lost project response survives reopening and retries the identical payload and receipt',async()=>{
  let attempted=false;const h=setup({api:call=>{if(call.url.includes('episode-batches'))return {revision:2};if(!attempted){attempted=true;throw new Error('response lost');}return {id:'p-created',revision:1};}});
  await h.platform.load({page:'projects'});let dialog=await h.open();fill(dialog);await submit(dialog);
  const original=h.posts()[0].body;await dialog.close();dialog=await h.open();await submit(dialog);
  assert.deepEqual(h.posts()[1].body,original);assert.equal(h.routes[0][2],'p-created');assert.equal(h.storage.size,0);
});

test('a lost batch response retries the same batch key and revision after a component restart',async()=>{
  let failed=false;const storage=new Map();const h=setup({storage,api:call=>{if(!call.url.includes('episode-batches'))return {id:'p-created',revision:1};if(!failed){failed=true;throw new Error('batch response lost');}return {revision:2};}});
  await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog,{count:51});await submit(dialog);const batch=h.posts()[1].body;
  h.platform.suspend();const recovered=setup({storage});await recovered.platform.load({page:'projects'});const reopened=await recovered.open();await submit(reopened);
  assert.equal(recovered.posts().length,2);assert.deepEqual(recovered.posts()[0].body,batch);assert.ok(recovered.posts().every(call=>call.url.includes('/p-created/episode-batches')));
  assert.deepEqual(recovered.posts()[1].body.payload.titles,['第51集']);assert.equal(storage.size,0);
});

for(const stage of ['refresh','navigate'])test(`a ${stage} failure after writing retries only opening the existing result`,async()=>{
  let failure=true;const fail=()=>{if(failure)throw new Error('readback unavailable');};
  const h=setup(stage==='refresh'?{refresh:fail}:{navigate:fail});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);await submit(dialog);
  assert.ok(dialog.textContent.includes('项目已创建'));assert.ok(dialog.textContent.includes('重试将继续打开已创建项目'));
  const written=h.posts().length;assert.equal(JSON.parse([...h.storage.values()][0]).phase,'readback');
  failure=false;await submit(dialog);assert.equal(h.posts().length,written);assert.equal(h.routes.at(-1)[2],'p-created');assert.equal(h.storage.size,0);
});

test('switching pages while reading the directory prevents the old creation navigation',async()=>{
  const readback=deferred();let isCurrent;const h=setup({refresh:options=>{isCurrent=options.isCurrent;return readback.promise;}});await h.platform.load({page:'projects'});const dialog=await h.open();fill(dialog);const pending=submit(dialog);await tick();
  assert.equal(h.refreshes,1);assert.equal(isCurrent(),true);await h.platform.load({page:'projects'});assert.equal(isCurrent(),false);readback.resolve();await pending;
  assert.equal(h.routes.length,0);assert.equal(JSON.parse([...h.storage.values()][0]).phase,'readback');
});

test('home discovery authentication failures stay local and retry without reloading the homepage',async()=>{
  let denied=true;const h=setup({api:()=>{if(denied)throw Object.assign(new Error('need session'),{status:403});return emptyDiscovery();}});
  await h.platform.load({page:'home'});
  assert.equal(h.root.querySelectorAll('.home-tool').length,8);assert.ok(h.root.querySelector('.home-canvas-card'));assert.ok(h.root.querySelector('.home-footer'));
  const region=h.root.querySelector('.home-discovery');assert.ok(region.textContent.includes('会话'));assert.ok(!h.root.textContent.includes('加载不完整'));assert.equal(h.notices.length,0);
  denied=false;await region.querySelector('button').click();assert.ok(region.querySelector('.discovery'));assert.equal(region.getAttribute('aria-busy'),null);
  assert.equal(h.root.querySelectorAll('.home-tool').length,8);assert.equal(h.calls.length,2);
});

test('a late homepage discovery failure cannot append an error to the new page',async()=>{
  const discovery=deferred();const h=setup({api:()=>discovery.promise});const pending=h.platform.load({page:'home'});await tick();
  await h.platform.load({page:'projects'});const before=h.root.textContent;discovery.reject(Object.assign(new Error('old denied'),{status:403}));await pending;
  assert.equal(h.root.textContent,before);assert.equal(h.root.querySelector('.home-discovery'),null);assert.equal(h.notices.length,0);
});

// Execute the owning shell function from the real source. Only module creation
// is intercepted so these tests can exercise its injected callback directly.
async function shellRefreshFixture(){
  const source=readFileSync(new URL('../../../src/vsc/interfaces/web/static/panel.js',import.meta.url),'utf8');
  const start=source.indexOf('async function loadProductionPlatform(){'),end=source.indexOf('async function loadCustomView(',start);
  assert.ok(start>=0&&end>start);
  const functionSource=source.slice(start,end).replace("await import('./production-platform.js')",'await Promise.resolve({createProductionPlatform:globalThis.createProductionPlatform})');
  const response=deferred(),recent=[],calls=[];let injected;
  const state={actor:'original',view:'projects',project:null,object:null,projectRows:new Map([['kept',{id:'kept',name:'原目录'}]])};
  const context={state,episodeScope:null,productionPlatform:null,URLSearchParams,
    api:async path=>{calls.push(path);return response.promise;},$:()=>({}),notice(){},
    createProductionPlatform:(_root,ctx)=>{injected=ctx;return {load:async()=>{}};},
    currentEntry:()=>new URLSearchParams(),renderRecentProjects:rows=>recent.push(rows),
    createEmptyCanvasProject(){},setEntryOptions(){},loadProjects(){},selectProject(){},openMedia(){},switchView(){},openArtifact(){},openResourceSettings(){},openRoleMemory(){}};
  vm.runInNewContext(functionSource+';globalThis.load=loadProductionPlatform;',context);
  await context.load();return {state,response,recent,calls,refresh:injected.refreshProjects};
}

test('the shell rejects an old actor directory before either state or sidebar adoption',async()=>{
  const h=await shellRefreshFixture();const pending=h.refresh();h.state.actor='different';h.response.resolve({items:[{id:'old-actor'}]});await pending;
  assert.equal(h.state.projectRows.has('kept'),true);assert.equal(h.state.projectRows.has('old-actor'),false);assert.equal(h.recent.length,0);
});

test('the shell rejects a directory whose calling creation scope changed while reading',async()=>{
  const h=await shellRefreshFixture();let current=true;const pending=h.refresh({isCurrent:()=>current});current=false;h.response.resolve({items:[{id:'stale-scope'}]});await pending;
  assert.equal(h.state.projectRows.has('kept'),true);assert.equal(h.state.projectRows.has('stale-scope'),false);assert.equal(h.recent.length,0);
});

test('the shell does not start a directory request for an already stale caller',async()=>{
  const h=await shellRefreshFixture();await h.refresh({isCurrent:()=>false});assert.equal(h.calls.length,0);assert.equal(h.recent.length,0);
});

test('the current actor directory still refreshes state and sidebar without optional arguments',async()=>{
  const h=await shellRefreshFixture();const pending=h.refresh();h.response.resolve({items:[{id:'current'}]});await pending;
  assert.equal(h.state.projectRows.has('kept'),false);assert.equal(h.state.projectRows.has('current'),true);assert.equal(h.recent.length,1);
});

const homeProject=id=>({id,name:id,storage_policy:'postgres-series-v1',profile:'vsc.light-short'});
const homeTool=(h,index)=>h.root.querySelectorAll('.home-tool')[index];
const homeCanvas=h=>h.root.querySelector('.home-canvas-card');
const episodePage=(items,next_offset=null)=>({revision:4,episodes:{items,total:items.length,next_offset}});

test('home video, storyboard, Agent and canvas enter the same recent project and episode without a selector',async()=>{
  for(const [index,page,kind]of [[0,'classic-production','video'],[1,'classic-production','image'],[3,'intelligent-creation',null],[-1,'creative-canvas',null]]){
    const h=setup({projects:[homeProject('p-first'),homeProject('p-recent')],api:async({url})=>{
      if(url==='/api/v1/discovery')return {...emptyDiscovery(),recent:[{project_id:'missing',episode_id:'old'},{project_id:'p-recent',episode_id:'ep-late',kind:'canvas',target_id:'original-canvas'}]};
      if(url.includes('/p-recent/production-platform?offset=0'))return episodePage([{id:'ep-first'}],100);
      if(url.includes('/p-recent/production-platform?offset=100'))return episodePage([{id:'ep-late'}]);
      if(url.endsWith('/creative-canvases?episode_id=ep-late'))return {revision:4,items:[{id:'other-canvas'},{id:'original-canvas'}]};
      throw new Error('Unexpected '+url);
    }});
    await h.platform.load({page:'home'});await (index<0?homeCanvas(h):homeTool(h,index)).click();
    assert.deepEqual(h.routes,[[page,null,'p-recent',{...(kind?{kind}:{}),episode:'ep-late',...(index<0?{task_target:'original-canvas'}:{})}]]);
    assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.posts().length,0);assert.equal(h.refreshes,1);
  }
});

test('home falls back to the first eligible project and episode and ignores tool workspaces',async()=>{
  const h=setup({projects:[{...homeProject('tools'),profile:'vsc.text-tools'},homeProject('p-first')],api:async({url})=>url==='/api/v1/discovery'?{...emptyDiscovery(),recent:[{project_id:'tools',episode_id:'tool-ep'}]}:episodePage([{id:'first'},{id:'second'}])});
  await h.platform.load({page:'home'});await homeTool(h,0).click();assert.deepEqual(h.routes,[['classic-production',null,'p-first',{kind:'video',episode:'first'}]]);
  const second=setup({projects:[homeProject('p')],api:async({url})=>url==='/api/v1/discovery'?{...emptyDiscovery(),recent:[{project_id:'p',episode_id:'deleted'}]}:episodePage([{id:'remaining'}])});
  await second.platform.load({page:'home'});await homeTool(second,1).click();assert.equal(second.routes[0][3].episode,'remaining');
});

test('project, discovery and episode failures never become an empty-project creation path',async()=>{
  for(const failure of ['projects','discovery','episodes','no-episode']){
    let started=false;const h=setup({projects:[homeProject('p')],refresh:async()=>{started=true;if(failure==='projects')throw new Error('project read failed');},api:async({url})=>{
      if(url==='/api/v1/discovery'){if(started&&failure==='discovery')throw new Error('recent read failed');return emptyDiscovery();}
      if(failure==='episodes')throw new Error('episode read failed');return episodePage([]);
    }});
    await h.platform.load({page:'home'});await homeTool(h,0).click();assert.equal(h.routes.length,0);assert.equal(h.posts().length,0);assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.notices.length,1);assert.equal(homeTool(h,0).disabled,false);
  }
});

test('empty home entries open the original creation form while the canvas uses its direct creation consumer',async()=>{
  let quick=0;const h=setup({createEmptyCanvasProject:async({isCurrent})=>{assert.ok(isCurrent());quick++;}});
  await h.platform.load({page:'home'});await homeCanvas(h).click();assert.equal(quick,1);assert.equal(h.root.querySelector('dialog'),null);
  await homeTool(h,0).click();assert.ok(h.root.querySelector('.project-create-dialog'));assert.equal(h.root.querySelectorAll('dialog').length,1);assert.equal(h.posts().length,0);
  await h.root.querySelector('dialog').close();h.session.writeAvailable=false;await homeTool(h,3).click();assert.equal(h.root.querySelector('dialog'),null);assert.equal(h.notices.length,1);
});

test('home creation keeps the selected entry and first episode through the original project form',async()=>{
  const h=setup({api:async({url})=>url==='/api/v1/discovery'?emptyDiscovery():url.includes('production-platform?')?episodePage([{id:'new-first'}]):url.includes('episode-batches')?{revision:2}:{id:'p-created',revision:1}});
  await h.platform.load({page:'home'});await homeTool(h,1).click();const dialog=h.root.querySelector('dialog');fill(dialog);await submit(dialog);
  assert.deepEqual(h.routes,[['classic-production',null,'p-created',{kind:'image',episode:'new-first'}]]);assert.equal(h.posts().length,2);
});

test('rapid home clicks share one entry operation and old identity or view responses cannot navigate',async()=>{
  for(const change of ['none','actor','identity','workspace','view']){
    const pause=deferred();let started=false;const h=setup({projects:[homeProject('p')],refresh:async()=>{started=true;await pause.promise;},api:async({url})=>url==='/api/v1/discovery'?emptyDiscovery():episodePage([{id:'ep'}])});
    await h.platform.load({page:'home'});const click=homeTool(h,0).click();await tick();assert.ok(started);await homeTool(h,1).click();assert.equal(h.refreshes,1);
    if(change==='actor')h.session.actor='other';if(change==='identity')h.session.identityId='other';if(change==='workspace')h.session.workspaceId='other';if(change==='view')await h.platform.load({page:'tasks'});
    pause.resolve();await click;assert.equal(h.routes.length,change==='none'?1:0,change);assert.deepEqual(h.notices,[],change);assert.equal(h.posts().length,0,change);
  }
});

test('a missing episode canvas is created in that project once and a lost response replays the same body',async()=>{
  const bodies=[];let lost=true;const h=setup({projects:[homeProject('p')],api:async({url,options,body})=>{
    if(url==='/api/v1/discovery')return emptyDiscovery();if(url.includes('production-platform?'))return episodePage([{id:'ep'}]);
    if(options.method==='POST'){bodies.push(body);if(lost){lost=false;throw new Error('lost canvas response');}return {id:'canvas',revision:5};}
    if(url.includes('creative-canvases?'))return {revision:4,items:[]};throw new Error('Unexpected '+url);
  }});
  await h.platform.load({page:'home'});await homeCanvas(h).click();assert.equal(h.routes.length,0);assert.equal(h.posts().length,1);
  await homeCanvas(h).click();assert.deepEqual(bodies[0],bodies[1]);assert.deepEqual(bodies[0].payload,{episode_id:'ep',title:'未命名画布',document:{nodes:[],edges:[]}});
  assert.deepEqual(h.routes,[['creative-canvas',null,'p',{episode:'ep',task_target:'canvas'}]]);assert.equal(h.storage.size,0);assert.ok(h.posts().every(call=>call.url==='/api/v1/projects/p/creative-canvases'));
});

function shellQuickCanvasFixture({api,load}={}){
  const source=readFileSync(new URL('../../../src/vsc/interfaces/web/static/panel.js',import.meta.url),'utf8');
  const start=source.indexOf('let emptyCanvasOpening=null;'),end=source.indexOf("$('new-canvas-project')?.addEventListener",start);
  assert.ok(start>=0&&end>start);const storage=new Map(),calls=[],entries=[],button={disabled:false};let loads=0;
  const state={actor:'actor',identityId:'identity',workspaceId:'workspace',writeAvailable:true,csrf:'csrf',view:'home',project:null};
  const context={state,episodeScope:null,crypto:webcrypto,$:()=>button,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    api:async(url,options)=>{const call={url,body:JSON.parse(options.body),headers:options.headers};calls.push(call);return api?api(call):{project_id:'new-project',episode_id:'first',canvas_id:'new-canvas'};},
    setEntryOptions:(...args)=>entries.push(args),loadProjects:async()=>{loads++;await load?.();}};
  vm.runInNewContext(source.slice(start,end)+';globalThis.create=createEmptyCanvasProject;',context);
  return {state,storage,calls,entries,button,create:context.create,get loads(){return loads;}};
}

test('home and sidebar share the original quick-canvas request and keep its receipt until opening succeeds',async()=>{
  let lost=true,failOpen=true;const h=shellQuickCanvasFixture({api:async()=>{if(lost){lost=false;throw new Error('lost quick response');}return {project_id:'new-project',episode_id:'first',canvas_id:'new-canvas'};},load:async()=>{if(failOpen){failOpen=false;throw new Error('opening failed');}}});
  await assert.rejects(h.create(),/lost quick response/);assert.equal(h.storage.size,1);assert.equal(h.button.disabled,false);
  await assert.rejects(h.create(),/opening failed/);assert.equal(h.storage.size,1);
  await h.create();assert.equal(h.storage.size,0);assert.equal(h.loads,2);assert.equal(h.calls.length,3);
  assert.ok(h.calls.every(call=>call.url==='/api/v1/projects/empty-canvas'&&call.headers['X-CSRF-Token']==='csrf'));
  assert.deepEqual(h.calls.map(call=>call.body),[h.calls[0].body,h.calls[0].body,h.calls[0].body]);
  assert.deepEqual(JSON.parse(JSON.stringify(h.entries.at(-1))),['creative-canvas','new-project',null,{episode:'first',task_target:'new-canvas'}]);
});

test('quick canvas ignores duplicate clicks and cannot adopt a late receipt after identity, workspace or page changes',async()=>{
  for(const change of ['none','actor','identity','workspace','view']){
    const pause=deferred(),h=shellQuickCanvasFixture({api:()=>pause.promise});let active=true;
    const pending=h.create({isCurrent:()=>active});await h.create();assert.equal(h.calls.length,1);assert.equal(h.button.disabled,true);
    if(change==='actor')h.state.actor='other';if(change==='identity')h.state.identityId='other';if(change==='workspace')h.state.workspaceId='other';if(change==='view')active=false;
    pause.resolve({project_id:'new-project',episode_id:'first',canvas_id:'new-canvas'});await pending;
    assert.equal(h.loads,change==='none'?1:0,change);assert.equal(h.entries.length,change==='none'?1:0,change);assert.equal(h.storage.size,change==='none'?0:1,change);assert.equal(h.button.disabled,false);
  }
});
