import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';

const require = createRequire(import.meta.url);
const {Document, Element} = require('../../support/fixtures/frontend/panel_dom.cjs');
const {moduleGraph} = require('../../support/fixtures/frontend/modules.cjs');
const {webcrypto} = require('node:crypto');
Element.prototype.contains = function(node) {
  while (node) { if (node === this) return true; node = node.parentElement; }
  return false;
};
Object.defineProperty(Element.prototype,'isConnected',{get(){for(let node=this;node;node=node.parentElement)if(node===this.ownerDocument.body)return true;return false;}});
Element.prototype.pause=function(){this.paused=true;};
Element.prototype.load=function(){this.released=true;};
Element.prototype.close=function(){this.open=false;};

const allModes={
 image:{modality:'image',slots:{reference_image:'image'}},
 omni:{modality:'video',slots:{reference_image:'image',reference_video:'video',reference_audio:'audio'},purpose:'reference_to_video'},
 first_last:{modality:'video',slots:{first_frame:'image',last_frame:'image'}},
 multi:{modality:'video',slots:{first_frame:'image',reference_image:'image'}},
 single:{modality:'video',slots:{first_frame:'image'}},text:{modality:'video',slots:{}},
 digital_human:{modality:'video',slots:{portrait:'image',subject_mask:'image',speech:'audio'},purpose:'digital_human',required_capabilities:['reference_media','reference_audio','subject_mask']},
 motion:{modality:'video',slots:{character:'image',motion_video:'video'},purpose:'motion_transfer',required_capabilities:['reference_media','reference_video']},
};
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(setImmediate);}throw new Error('controlled frontend request did not finish');}
async function fixture({intercept,configure,storage=new Map()}={}){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);
 const requests=[],notices=[],timers=new Map(),rows=[{id:'s1',parent_id:'group',title:'镜1'},{id:'s2',parent_id:'group',title:'镜2'}];let timerId=0;
 const session={actor:'human',identityId:'human',writable:true,csrf:'csrf',revision:5};
 const models=['image','video'].map(modality=>({id:modality,model_key:modality,modality,enabled:true,adapter_available:true,default_params:{resolution:'720p'},capabilities:{purposes:['reference_to_video','image_to_video','text_to_video','digital_human','motion_transfer','first_frame'],reference_media:true,reference_video:true,reference_audio:true,subject_mask:true,max_reference_images:2,max_duration_ms:15000}}));
 const media=[...['im1','im2','im3'].map(id=>({id,modality:'image',name:id,sha256:id})),{id:'v1',modality:'video',name:'v1',sha256:'v1'},{id:'a1',modality:'audio',name:'a1',sha256:'a1',duration_ms:5000}];
 configure?.({storage,models,rows,media,session});
 const api=async(url,init={})=>{
  requests.push({url,init});const override=intercept?.(url,init,{rows,models,media});if(override!==undefined)return override;
  const params=new URL(url,'http://fixture').searchParams;
  if(url.includes('/workbench?')){const current=rows.find(row=>row.id===params.get('object_id'));return {scope:current?{...current,kind:'shot'}:{id:'episode',kind:'episode'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:rows}}};}
  if(url.includes('/classic-production?'))return {shot:rows.find(row=>row.id===params.get('shot_id'))||rows[0],sibling_shots:rows,revision:5,drafts:[],models,media,media_total:media.length,modes:allModes};
  if(init.method&&init.method!=='GET')throw new Error('Unexpected write: '+url);
  if(url.includes('/working-selections?')||url.includes('/execution-authorizations'))return {items:[],revision:5};
  if(url.includes('/working-candidates?'))return {items:[],total:0,next_offset:null,revision:5};
  throw new Error('Unexpected read: '+url);
 };
 const graph=moduleGraph({document,sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},crypto:webcrypto,URLSearchParams,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)});
 await graph.load('classic-controls-messages.js');const {createClassicProduction}=await graph.load('classic-production.js');
 const app=createClassicProduction(root,{api,session:()=>session,setRevision(value){session.revision=value;},notice:message=>notices.push(message),navigate(){},media(){}});
 const load=(extra={})=>app.load({projectId:'p',episodeId:'episode',productionKind:'video',...extra});
 const switchMode=async id=>{const label=({omni:'全能参考',first_last:'首尾帧',multi:'多图',single:'单图',text:'文本',digital_human:'数字人',motion:'动作模仿'})[id];await root.querySelector('.classic-modes').querySelectorAll('button').find(node=>node.textContent===label).click();};
 const prompt=()=>root.querySelector('.classic-prompt').querySelector('textarea');
 const typePrompt=async value=>{const input=prompt();input.value=value;await root.querySelector('.classic-form').dispatch('input',{target:input});};
 const draft=id=>JSON.parse(storage.get('vsc-classic-draft:human:p:s1:'+id)||'null');
 const addReference=async(role,id)=>{const slot=root.querySelectorAll('.classic-reference-slot').find(node=>node.dataset.role===role),imports=slot?.querySelector('.classic-reference-imports');const select=imports?.querySelector('select')||root.querySelector('.classic-references').querySelectorAll('select').find(node=>node.options.some(option=>option.value===id));select.value=id;await select.parentElement.children[select.parentElement.children.indexOf(select)+1].click();};
 return {root,app,load,switchMode,prompt,typePrompt,draft,addReference,requests,storage,notices,timers,session};
}

test('mode choices use declared purpose and required capabilities without starting work', async () => {
  globalThis.document = new Document('');
  const storage = new Map();
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const root = document.createElement('section');
  document.body.append(root);
  const {createClassicProduction} = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-production.js'));
  const rows = [{id:'shot', parent_id:'group', title:'镜头'}];
  const model = (id, capabilities, enabled=true) => ({id, model_key:id, modality:'video', enabled, adapter_available:true, capabilities, default_params:{resolution:'720p'}});
  const models = [
    model('ordinary', {purposes:['reference_to_video']}),
    model('motion-good', {purposes:['motion_transfer'],reference_media:true,reference_video:true,max_duration_ms:15000}),
    model('motion-no-video', {purposes:['motion_transfer'],reference_media:true}),
    model('motion-wrong-purpose', {purposes:['image_to_video'],reference_media:true,reference_video:true}),
    model('motion-disabled', {purposes:['motion_transfer'],reference_media:true,reference_video:true}, false),
    model('avatar-good', {purposes:['digital_human'],reference_media:true,reference_audio:true,subject_mask:true}),
    model('avatar-no-audio', {purposes:['digital_human'],reference_media:true,subject_mask:true}),
    model('avatar-wrong-purpose', {purposes:['image_to_video'],reference_media:true,reference_audio:true,subject_mask:true}),
  ];
  const modes = {
    omni:{modality:'video',slots:{reference_image:'image',reference_video:'video',reference_audio:'audio'},purpose:'reference_to_video'},
    motion:{modality:'video',slots:{character:'image',motion_video:'video'},purpose:'motion_transfer',required_capabilities:['reference_media','reference_video']},
    digital_human:{modality:'video',slots:{portrait:'image',subject_mask:'image',speech:'audio'},purpose:'digital_human',required_capabilities:['reference_media','reference_audio','subject_mask']},
  };
  const writes = [];
  const api = async (url, init={}) => {
    if (init.method && init.method !== 'GET') { writes.push({url, method:init.method}); throw new Error('unexpected write'); }
    if (url.includes('section=shots')) return {scope:{kind:'shot',id:'shot'},ancestors:[{kind:'episode',id:'episode'}],sections:{shots:{items:rows}}};
    if (url.includes('/classic-production?')) return {shot:rows[0],sibling_shots:rows,revision:5,drafts:[],models,media:[],media_total:0,modes};
    if (url.includes('/working-selections?')) return {items:[],revision:5};
    return {items:[],total:0};
  };
  const ctx = {api,session:()=>({actor:'human',identityId:'human',writable:true,csrf:'x',revision:5}),setRevision(){},notice(){},navigate(){},media(){}};
  const app = createClassicProduction(root,ctx);
  const scope = {projectId:'p',objectId:'shot',productionKind:'video'};
  const choices = () => root.querySelector('.classic-model-choices').querySelectorAll('button').map(node=>node.dataset.modelId);
  const switchMode = async label => {const button=root.querySelector('.classic-modes').querySelectorAll('button').find(node=>node.textContent===label);assert.ok(button);await button.click();};
  try {
    await app.load({...scope,mode:'omni'});
    assert.deepEqual(choices(), ['', 'ordinary']);
    await switchMode('动作模仿');
    assert.deepEqual(choices(), ['', 'motion-good', 'motion-disabled']);
    const good = root.querySelector('.classic-model-choices').querySelectorAll('button').find(node=>node.dataset.modelId==='motion-good');
    await good.click();
    assert.equal(root.querySelector('.classic-model-choices').querySelectorAll('button').find(node=>node.dataset.modelId==='motion-good').getAttribute('aria-selected'),'true');
    assert.ok(root.textContent.includes('输出时长 ≤ 15s'));
    assert.ok(!root.textContent.includes('30s 内'));
    await switchMode('数字人');
    assert.deepEqual(choices(), ['', 'avatar-good']);
    assert.ok(root.textContent.includes('预览报价并确认识别'));
    assert.deepEqual(writes, []);
  } finally {
    app.suspend();
  }
});

test('storyboard and video selections remain separate within the episode and across reloads',async()=>{
 const f=await fixture();
 const current=()=>f.root.querySelector('.classic-shot-rail').querySelectorAll('button').find(node=>node.getAttribute('aria-current')==='true')?.dataset.shotId;
 try{
  await f.load({productionKind:'image',mode:'image'});
  await f.root.querySelectorAll('.classic-shot').find(node=>node.dataset.shotId==='s2').click();assert.equal(current(),'s2');
  await f.load({objectId:'s2'});assert.equal(current(),'s1');
  await f.load({objectId:'s1',productionKind:'image'});assert.equal(current(),'s2');
  f.app.suspend();await f.load({productionKind:'image'});assert.equal(current(),'s2');
  await f.load({productionKind:'video',shotId:'s2',objectId:'s2'});assert.equal(current(),'s2');
  f.session.actor=f.session.identityId='other';await f.load({productionKind:'image'});assert.equal(current(),'s1');
  assert.equal(f.requests.some(row=>row.init.method),false);
 }finally{f.app.suspend();}
});

test('all seven video modes retain separate prompts and references',async()=>{
 const f=await fixture();const modes=['omni','first_last','multi','single','text','digital_human','motion'];
 try{
  await f.load({mode:'omni'});
  for(const id of modes){await f.switchMode(id);await f.typePrompt('本模式 '+id);if(id==='first_last')await f.addReference('first_frame','im1');if(id==='multi'){await f.addReference('first_frame','im2');await f.addReference('reference_image','im3');}if(id==='omni')await f.addReference('reference_video','v1');}
  for(const id of modes){await f.switchMode(id);assert.equal(f.prompt().value,'本模式 '+id);const saved=f.draft(id);assert.equal(id==='digital_human'?saved.document.performance_prompt:saved.document.prompt,'本模式 '+id);}
  assert.deepEqual(f.draft('text').document.references,[]);
  assert.equal(f.draft('omni').document.references[0].media_id,'v1');
  assert.equal(f.draft('first_last').document.references[0].media_id,'im1');
  assert.deepEqual(f.draft('multi').document.references.map(row=>row.media_id),['im2','im3']);
  assert.equal(f.requests.some(row=>row.init.method),false);
 }finally{f.app.suspend();}
});

test('empty modes and declared limits block quote submission while preserving inputs',async()=>{
 const f=await fixture(),generate=()=>f.root.querySelector('.classic-primary');
 try{
  await f.load({mode:'first_last'});assert.equal(generate().disabled,true);assert.equal(f.prompt().maxLength,20000);
  await f.addReference('first_frame','im1');assert.equal(generate().disabled,false);
  await f.typePrompt('a'.repeat(20001));assert.equal(generate().disabled,true);assert.equal(f.draft('first_last').document.prompt.length,20001);
  await f.switchMode('multi');assert.equal(generate().disabled,true);await f.addReference('first_frame','im1');assert.equal(generate().disabled,true);
  await f.addReference('reference_image','im2');assert.equal(generate().disabled,false);await f.addReference('reference_image','im3');assert.equal(generate().disabled,true);
  for(const id of ['digital_human','motion']){await f.switchMode(id);assert.equal(generate().disabled,true);await generate().click();}
  await f.switchMode('digital_human');assert.equal(f.prompt().maxLength,300);
  assert.equal(f.requests.some(row=>row.init.method),false);
 }finally{f.app.suspend();}
});

test('first candidate loading and failure are distinct from an empty result and read retry recovers',async()=>{
 let pending,attempt=0;const f=await fixture({intercept(url){if(url.includes('/working-candidates?')&&attempt++===0)return new Promise((resolve,reject)=>pending={resolve,reject});}});
 try{
  await f.load();await waitFor(()=>pending);const aside=f.root.querySelector('.classic-results');
  assert.equal(aside.dataset.loadState,'loading');assert.equal(aside.getAttribute('aria-busy'),'true');assert.equal(f.root.querySelector('.classic-result-add'),null);
  pending.reject(new Error('首次网络失败'));await waitFor(()=>aside.dataset.loadState==='error');
  assert.equal(f.root.querySelector('.classic-result-add'),null);assert.match(aside.textContent,/首次网络失败/);
  await f.root.querySelector('.classic-candidate-paging').querySelector('button').click();
  assert.equal(aside.dataset.loadState,'empty');assert.equal(aside.getAttribute('aria-busy'),'false');assert.ok(f.root.querySelector('.classic-result-add'));
  assert.equal(f.requests.some(row=>row.init.method),false);
 }finally{f.app.suspend();}
});

test('append failure keeps prior results and retries the same offset without duplicates',async()=>{
 let second=0;const f=await fixture({intercept(url){if(!url.includes('/working-candidates?'))return;const offset=new URL(url,'http://fixture').searchParams.get('offset');if(offset==='30'&&second++===0)throw new Error('追加失败');return {items:[{media_id:offset==='0'?'old':'next',name:offset==='0'?'旧候选':'新候选'}],total:2,next_offset:offset==='0'?30:null};}});
 try{
  await f.load();await waitFor(()=>f.root.querySelector('.classic-candidate'));
  await f.root.querySelector('.classic-candidate-paging').querySelector('button').click();
  assert.equal(f.root.querySelector('.classic-results').dataset.loadState,'error');assert.equal(f.root.querySelectorAll('.classic-candidate').length,1);assert.match(f.root.textContent,/旧候选/);
  await f.root.querySelector('.classic-candidate-paging').querySelector('button').click();
  assert.deepEqual(f.root.querySelectorAll('.classic-candidate').map(row=>row.dataset.mediaId),['old','next']);
  assert.deepEqual(f.requests.filter(row=>row.url.includes('/working-candidates?')).map(row=>new URL(row.url,'http://fixture').searchParams.get('offset')),['0','30','30']);
 }finally{f.app.suspend();}
});

for(const outcome of ['success','failure'])test(`late candidate ${outcome} cannot overwrite another shot`,async()=>{
 let previous;const f=await fixture({intercept(url){if(url.includes('/working-candidates?')&&new URL(url,'http://fixture').searchParams.get('shot_id')==='s1')return new Promise((resolve,reject)=>previous={resolve,reject});}});
 try{
  await f.load();await waitFor(()=>previous);await f.load({shotId:'s2',objectId:'s2'});await waitFor(()=>f.root.querySelector('.classic-results')?.dataset.loadState==='empty');const current=f.root.textContent;
  if(outcome==='success')previous.resolve({items:[{media_id:'old',name:'过时内容'}],total:1});else previous.reject(new Error('旧范围错误'));
  await new Promise(setImmediate);assert.equal(f.root.textContent,current);assert.equal(f.notices.length,0);
 }finally{f.app.suspend();}
});

test('starting another load stops polling and releases the old video before the new scope resolves',async()=>{
 let blocked;const f=await fixture({configure({storage}){storage.set('vsc-classic-draft:human:p:s1:omni',JSON.stringify({document:{shot_id:'s1',mode:'omni',model_id:'video',purpose:'reference_to_video',prompt:'',duration_ms:5000,width:1080,height:1920,count:1,params:{},references:[]},lastGeneration:{jobs:[{id:'job'}]},dirty:false}));},intercept(url){
  if(url.includes('/workbench?')&&url.includes('object_id=s2'))return new Promise(resolve=>blocked=resolve);
  if(url.includes('/production-platform/jobs/'))return {status:'running'};
  if(url.includes('/working-candidates?'))return {items:[{media_id:'movie',name:'结果'}],total:1};
 }});
 try{
  await f.load();await waitFor(()=>f.timers.size===1);assert.equal([...f.timers.values()][0].delay,5000);const video=f.root.querySelector('.classic-candidate').querySelector('video');
  const next=f.load({objectId:'s2',shotId:'s2'});await waitFor(()=>blocked);assert.equal(f.timers.size,0);assert.equal(video.paused,true);assert.equal(video.released,true);
  f.app.suspend();blocked({scope:{id:'s2',kind:'shot'},sections:{shots:{items:[]}}});await next;assert.equal(f.timers.size,0);
 }finally{f.app.suspend();}
});

test('adding a storyboard creates one original shot immediately and selects its readback',async()=>{
 const f=await fixture({intercept(url,init,{rows}){if(url.endsWith('/classic-production/shots')){const payload=JSON.parse(init.body).payload;assert.equal(payload.action,'create');rows.push({id:'new',parent_id:'group',title:payload.title});return {id:'new',revision:6};}}});
 try{
  await f.load({productionKind:'image',mode:'image'});await f.root.querySelector('.classic-add-menu').querySelector('button').click();
  const current=f.root.querySelectorAll('.classic-shot').find(node=>node.getAttribute('aria-current')==='true');assert.equal(current.dataset.shotId,'new');
  assert.equal(f.requests.filter(row=>row.init.method==='POST').length,1);assert.equal(f.root.querySelector('dialog'),null);
 }finally{f.app.suspend();}
});

test('a failed shot listing never creates a first shot or presents an empty production state',async()=>{
 const f=await fixture({intercept(url){if(url.includes('/workbench?'))throw new Error('镜头列表失败');}});
 try{await f.load();assert.match(f.root.textContent,/镜头列表失败/);assert.equal(f.root.querySelector('.classic-add-shot'),null);assert.equal(f.requests.some(row=>row.init.method),false);}
 finally{f.app.suspend();}
});

test('mode selection survives changing shots and ended jobs stop background polling',async()=>{
 let jobReads=0;const f=await fixture({configure({storage}){storage.set('vsc-classic-draft:human:p:s1:text',JSON.stringify({document:{shot_id:'s1',mode:'text',model_id:'video',purpose:'text_to_video',prompt:'文本专用',duration_ms:5000,width:1080,height:1920,count:1,params:{},references:[]},lastGeneration:{jobs:[{id:'job'}]},dirty:false}));},intercept(url){if(url.includes('/production-platform/jobs/'))return {status:++jobReads===1?'running':'succeeded'};}});
 try{
  await f.load({mode:'omni'});await f.switchMode('text');await waitFor(()=>f.timers.size===1);
  const [id,timer]=[...f.timers.entries()][0];f.timers.delete(id);timer.fn();await waitFor(()=>jobReads===2&&f.root.querySelector('.classic-results').getAttribute('aria-busy')==='false');assert.equal(f.timers.size,0);
  await f.root.querySelectorAll('.classic-shot').find(node=>node.dataset.shotId==='s2').click();assert.equal(f.root.dataset.mode,'text');assert.equal(f.prompt().value,'');
  await f.root.querySelectorAll('.classic-shot').find(node=>node.dataset.shotId==='s1').click();assert.equal(f.root.dataset.mode,'text');assert.equal(f.prompt().value,'文本专用');
 }finally{f.app.suspend();}
});

test('background refresh respects original page limits and preserves the full loaded prefix on failure',async()=>{
 let failBackground=true;const f=await fixture({configure({storage}){storage.set('vsc-classic-draft:human:p:s1:omni',JSON.stringify({document:{shot_id:'s1',mode:'omni',model_id:'video',purpose:'reference_to_video',prompt:'',duration_ms:5000,width:1080,height:1920,count:1,params:{},references:[]},lastGeneration:{jobs:[{id:'job'}]},dirty:false}));},intercept(url){
  if(url.includes('/production-platform/jobs/'))return {status:'running'};
  if(!url.includes('/working-candidates?'))return;
  const params=new URL(url,'http://fixture').searchParams,offset=Number(params.get('offset')),limit=Number(params.get('limit'));assert.ok(limit<=100);
  if(offset===100&&failBackground){failBackground=false;throw new Error('后台第二页失败');}
  const end=Math.min(120,offset+limit);return {items:Array.from({length:end-offset},(_,index)=>({media_id:'v'+(offset+index),name:'候选'+(offset+index)})),total:120,next_offset:end<120?end:null};
 }});
 try{
  await f.load();await waitFor(()=>f.timers.size===1);
  for(let i=0;i<3;i++)await f.root.querySelector('.classic-candidate-paging').querySelector('button').click();
  assert.equal(f.root.querySelectorAll('.classic-candidate').length,120);
  const [id,timer]=[...f.timers.entries()][0];f.timers.delete(id);timer.fn();await waitFor(()=>f.root.querySelector('.classic-results').dataset.loadState==='error');
  assert.equal(f.root.querySelectorAll('.classic-candidate').length,120);assert.equal(f.root.querySelectorAll('.classic-candidate')[119].dataset.mediaId,'v119');
  await f.root.querySelector('.classic-candidate-paging').querySelector('button').click();assert.equal(f.root.querySelectorAll('.classic-candidate').length,120);
  assert.deepEqual(f.requests.filter(row=>row.url.includes('/working-candidates?')).map(row=>Number(new URL(row.url,'http://fixture').searchParams.get('limit'))),[30,30,30,30,100,20,100,20]);
 }finally{f.app.suspend();}
});
