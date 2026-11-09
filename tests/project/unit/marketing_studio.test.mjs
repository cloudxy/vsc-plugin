import assert from 'node:assert/strict';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';

// Component self-checks exercise request ownership and recovery. This small DOM
// does not stand in for the browser, authenticated HTTP, PostgreSQL or providers.
class Element {
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.attributes={};this.dataset={};this.className='';this.disabled=false;this.hidden=false;this.value='';this.isConnected=true;this.classList={add:(v)=>{this.className+=' '+v;},remove:(...values)=>{this.className=this.className.split(' ').filter(v=>!values.includes(v)).join(' ');}};}
  append(...nodes){for(const node of nodes)if(node instanceof Element){node.parentElement=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this._text=null;this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  get textContent(){return this._text??this.children.map(n=>n.textContent).join('');}
  set textContent(value){this.children=[];this._text=String(value);}
  walk(){return this.children.flatMap(n=>[n,...n.walk()]);}
  querySelectorAll(selector){return this.walk().filter(n=>selector.startsWith('.')?n.className.split(' ').includes(selector.slice(1)):selector==='[role=status]'?n.attributes.role==='status':n.tagName===selector.toUpperCase());}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  addEventListener(){}
}
const document={documentElement:{},createElement(tag){return new Element(tag,this);},createTextNode(text){const n=new Element('#text',this);n.textContent=text;return n;},querySelector(){return null;}};
document.head=new Element('head',document);globalThis.document=document;
if(!globalThis.crypto)globalThis.crypto=webcrypto;
globalThis.location={search:'',href:''};
const storage=new Map();globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
const {createMarketingStudio}=await import('../../../src/vsc/interfaces/web/static/marketing-studio.js');
const {createProductionPlatform}=await import('../../../src/vsc/interfaces/web/static/production-platform.js');
const {translate,msg}=await import('../../../src/vsc/interfaces/web/static/i18n.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(){for(let i=0;i<12;i++)await tick();}
const methods=['short-drama-commerce','product-poster','viral-video-clone','commercial-tvc','ugc-commerce','viral-creative-variation','product-visual-materials','video-localization'].map((id,i)=>({id,name:['短剧带货','商品海报','爆款视频复刻','TVC广告片','UGC种草与带货','爆款素材裂变','商品视觉物料','视频翻译与渠道适配'][i],version:'1.0',sha256:'sha-'+id,skill_id:i===1?'image-generation':'video-generation',description:'方法：'+id,input_hint:'提示：'+id}));
const options=(revision=7)=>({revision,methods,episodes:[{id:'ep',name:'第一集'}],models:[{id:'unused-model'}],provider_submit:false});
const btn=(root,title)=>root.walk().find(n=>n.tagName==='BUTTON'&&n.textContent===title);
const cls=(root,name)=>root.querySelector('.'+name);
const control=(root,label)=>root.walk().find(n=>n.attributes['aria-label']===label);
function prompt(root,value){const input=control(root,'广告创作需求');input.value=value;input.oninput();}
async function send(root){await cls(root,'marketing-composer').onsubmit({preventDefault(){}});await settle();}
function environment(handler=()=>undefined){
  const root=new Element('main',document),calls=[],nav=[],revisions=[],session={actor:'a',csrf:'csrf-a',writable:false,writeAvailable:true,revision:999};
  const projects=[{id:'p',name:'营销项目',storage_policy:'postgres-series-v1'},{id:'q',name:'第二项目',storage_policy:'postgres-series-v1'}];
  const ctx={projects:()=>projects,session:()=>session,notice(){},setRevision:(r,p)=>revisions.push([r,p]),navigate:async(...args)=>{nav.push(args);},api:async(url,init)=>{
    calls.push({url,init});const handled=await handler(url,init);if(handled!==undefined)return handled;
    if(url.endsWith('marketing-options'))return options();
    if(url.includes('/media?'))return {items:[],total:0};
    if(url.endsWith('marketing-canvases'))return {id:'c',canvas_id:'c',episode_id:'ep',revision:8,agent_handoff:{skill_id:'image-generation',node_ids:['marketing-brief','marketing-method'],message:'原输入'}};
    if(url.endsWith('creative-canvases/c'))return {id:'c',revision:8,document:{nodes:[{id:'marketing-brief',text:'原输入'}]}};
    throw Error('Unexpected '+url);
  }};
  const panel=createMarketingStudio(root,ctx);return {root,panel,calls,nav,revisions,ctx,session,projects};
}
const writes=e=>e.calls.filter(c=>c.init?.method==='POST');

test('selects the real method, episode and registered media, then reads the same canvas before Agent handoff',async()=>{
  storage.clear();const e=environment(url=>url.includes('/media?')?{items:[{id:'m',name:'商品原图',modality:'image'}],total:1}:undefined);
  await e.panel.load({project:'p'});await settle();
  assert.equal(e.root.querySelectorAll('.marketing-method').length,9);
  await btn(e.root,'商品海报').onclick();assert.equal(control(e.root,'广告创作需求').placeholder,'提示：product-poster');
  await e.root.querySelector('.marketing-media-card').querySelector('button').onclick();control(e.root,'归属剧集').value='ep';control(e.root,'归属剧集').onchange();
  const raw='  保留这款瓶身，做春季海报。\n真实原文  ';prompt(e.root,raw);await send(e.root);
  assert.equal(writes(e).length,1);const request=JSON.parse(writes(e)[0].init.body);
  assert.deepEqual(request.payload,{prompt:raw,episode_id:'ep',method_id:'product-poster',method_version:'1.0',method_sha256:'sha-product-poster',media_ids:['m']});
  assert.equal(request.expected_revision,7);assert.equal(writes(e)[0].init.headers['X-CSRF-Token'],'csrf-a');
  assert.ok(e.calls.findIndex(c=>c.url.endsWith('creative-canvases/c'))>e.calls.findIndex(c=>c.init?.method==='POST'));
  assert.deepEqual(e.nav[0],['creative-canvas',null,'p',{task_target:'c',episode:'ep',marketing:'1',skill:'image-generation'}]);
  assert.equal(new URLSearchParams(e.nav[0][3]).has('prompt'),false);e.panel.suspend();
});

test('method is optional and model preferences are deferred without pretending to consume them',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'只确认创意');await send(e.root);
  const body=JSON.parse(writes(e)[0].init.body);assert.equal(body.payload.method_id,null);assert.equal('method_version'in body.payload,false);assert.equal('model_ids'in body.payload,false);
  assert.equal(e.root.querySelectorAll('.marketing-method').filter(n=>n.attributes['aria-pressed']==='true').length,1);
  await control(e.root,'选择模型').onclick();assert.match(cls(e.root,'marketing-model-note').textContent,/画布 Agent 中选择/);e.panel.suspend();
});

test('prompt validation counts Unicode characters and keeps unmodified input',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});
  prompt(e.root,'😀'.repeat(2000));assert.equal(cls(e.root,'marketing-submit').disabled,false);
  prompt(e.root,'😀'.repeat(2001));assert.equal(cls(e.root,'marketing-submit').disabled,true);await send(e.root);assert.equal(writes(e).length,0);
  prompt(e.root,'   ');await send(e.root);assert.equal(writes(e).length,0);e.panel.suspend();
});

test('response loss restores a fixed payload, revision and idempotency key after remount',async()=>{
  storage.clear();let fail=true;const requests=[];
  const handler=(url,init)=>{if(init?.method==='POST'){requests.push(init.body);if(fail)throw Error('响应丢失');}};
  const e=environment(handler);await e.panel.load({project:'p'});prompt(e.root,'固定需求');await send(e.root);
  assert.equal(control(e.root,'广告创作需求').disabled,true);assert.match(cls(e.root,'marketing-status').textContent,/恢复同一操作/);e.panel.suspend();
  fail=false;const f=environment(handler);f.session.revision=1000;await f.panel.load({project:'p'});await send(f.root);
  assert.equal(requests.length,2);assert.equal(requests[0],requests[1]);assert.equal(f.nav.length,1);f.panel.suspend();
});

test('successful write and failed readback retry only the original canvas GET',async()=>{
  storage.clear();let fail=true;const e=environment(url=>{if(url.endsWith('creative-canvases/c')&&fail)throw Error('读回断网');});
  await e.panel.load({project:'p'});prompt(e.root,'测试读回');await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.nav.length,0);
  fail=false;await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.nav.length,1);assert.equal(e.calls.filter(c=>c.url.endsWith('creative-canvases/c')).length,2);e.panel.suspend();
});

test('navigation failure retries navigation without another write or readback',async()=>{
  storage.clear();let fail=true;const e=environment();e.ctx.navigate=async(...args)=>{e.nav.push(args);if(fail)throw Error('打开失败');};
  await e.panel.load({project:'p'});prompt(e.root,'测试导航');await send(e.root);assert.equal(e.nav.length,1);
  fail=false;await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.calls.filter(c=>c.url.endsWith('creative-canvases/c')).length,1);assert.equal(e.nav.length,2);e.panel.suspend();
});

test('resolved navigation keeps the original canvas receipt across return until an explicit new creation',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'同一创意');await send(e.root);
  e.panel.suspend();const f=environment();await f.panel.load({project:'p'});await send(f.root);
  assert.equal(writes(e).length,1);assert.equal(writes(f).length,0);assert.equal(f.nav[0][3].task_target,'c');
  await btn(f.root,'开始新创作').onclick();await send(f.root);
  assert.equal(writes(f).length,1);assert.notEqual(JSON.parse(writes(e)[0].init.body).idempotency_key,JSON.parse(writes(f)[0].init.body).idempotency_key);f.panel.suspend();
});

test('an expired session after an unknown committed write never discards the original request',async()=>{
  storage.clear();let attempt=0;const committed=new Set(),keys=[];
  const e=environment((_url,init)=>{if(init?.method==='POST'){
    const request=JSON.parse(init.body);keys.push(request.idempotency_key);attempt++;
    if(attempt===2)throw Object.assign(Error('操作会话已过期'),{status:403});
    committed.add(request.idempotency_key);if(attempt===1)throw Error('响应丢失');
  }});
  await e.panel.load({project:'p'});prompt(e.root,'未知结果后恢复');await send(e.root);await send(e.root);
  assert.equal(control(e.root,'广告创作需求').disabled,true);await send(e.root);
  assert.equal(committed.size,1);assert.equal(new Set(keys).size,1);assert.equal(e.nav.length,1);e.panel.suspend();
});

test('duplicate submit is blocked while the first request is running',async()=>{
  storage.clear();let finish;const hold=new Promise(r=>finish=r),e=environment((url,init)=>init?.method==='POST'?hold:undefined);
  await e.panel.load({project:'p'});prompt(e.root,'重复点击');const a=send(e.root);await tick();await send(e.root);assert.equal(writes(e).length,1);
  finish({canvas_id:'c',revision:8,agent_handoff:{skill_id:'vsc-assets'}});await a;assert.equal(e.nav.length,1);e.panel.suspend();
});

test('late project options, media and write callbacks cannot change the new project',async()=>{
  storage.clear();let finishOptions;const holdOptions=new Promise(r=>finishOptions=r);const e=environment(url=>url.includes('/p/marketing-options')?holdOptions:undefined);
  const a=e.panel.load({project:'p'});await e.panel.load({project:'q'});prompt(e.root,'第二项目');finishOptions(options(400));await a;
  assert.equal(control(e.root,'归属项目').value,'q');assert.equal(control(e.root,'广告创作需求').value,'第二项目');assert.equal(e.revisions.some(([r])=>r===400),false);e.panel.suspend();
  let finishWrite;const holdWrite=new Promise(r=>finishWrite=r),f=environment((url,init)=>init?.method==='POST'?holdWrite:undefined);
  await f.panel.load({project:'p'});prompt(f.root,'第一项目操作');const pending=send(f.root);await tick();await f.panel.load({project:'q'});prompt(f.root,'第二项目保稿');
  finishWrite({canvas_id:'c',revision:9999});await pending;assert.equal(f.nav.length,0);assert.equal(f.revisions.some(([r])=>r===9999),false);assert.equal(control(f.root,'广告创作需求').value,'第二项目保稿');
  await f.panel.load({project:'p'});assert.equal(btn(f.root,'继续打开画布').disabled,false);f.panel.suspend();
});

test('suspend and actor changes reject success, error and finally callbacks',async()=>{
  storage.clear();let finish;const hold=new Promise(r=>finish=r),e=environment((url,init)=>init?.method==='POST'?hold:undefined);
  await e.panel.load({project:'p'});prompt(e.root,'旧身份需求');const a=send(e.root);await tick();e.session.actor='b';await e.panel.load({project:'p'});prompt(e.root,'新身份保稿');
  finish({canvas_id:'c',revision:500});await a;assert.equal(e.nav.length,0);assert.equal(control(e.root,'广告创作需求').value,'新身份保稿');assert.equal(cls(e.root,'marketing-submit').disabled,false);e.panel.suspend();
  let reject;const blocked=new Promise((_r,r)=>reject=r),f=environment(url=>url.endsWith('marketing-options')?blocked:undefined);
  const pending=f.panel.load({project:'q'});f.panel.suspend();const before=f.root.textContent;reject(Error('旧错误'));await pending;assert.equal(f.root.textContent,before);
});

test('drafts are isolated by actor and project, with an editable projectless entry',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:null});assert.equal(control(e.root,'广告创作需求').disabled,false);prompt(e.root,'先写的创意');
  control(e.root,'归属项目').value='p';await control(e.root,'归属项目').onchange();await settle();assert.equal(control(e.root,'广告创作需求').value,'先写的创意');
  await e.panel.load({project:'q'});prompt(e.root,'第二项目');await e.panel.load({project:'p'});assert.equal(control(e.root,'广告创作需求').value,'先写的创意');
  e.session.actor='b';await e.panel.load({project:'p'});assert.equal(control(e.root,'广告创作需求').value,'');e.panel.suspend();
});

test('read-only projects and a missing operation identity cannot submit',async()=>{
  storage.clear();const e=environment();e.projects[0].read_only=true;await e.panel.load({project:'p'});prompt(e.root,'只读');await send(e.root);assert.equal(writes(e).length,0);
  e.projects[0].read_only=false;e.session.actor=null;await e.panel.load({project:'p'});assert.equal(e.root.querySelectorAll('.marketing-composer').length,1);prompt(e.root,'未登录');await send(e.root);assert.equal(writes(e).length,0);e.panel.suspend();
});

test('media selection uses original paged resources, supports removal and limits to fifteen',async()=>{
  storage.clear();const e=environment(url=>url.includes('/media?')?{items:Array.from({length:24},(_,i)=>({id:'m'+i,name:'素材'+i,modality:'image'})),total:25}:undefined);
  await e.panel.load({project:'p'});await settle();assert.equal(e.root.querySelectorAll('.marketing-media-card').length,24);
  for(const card of e.root.querySelectorAll('.marketing-media-card').slice(0,16))await card.querySelector('button').onclick();
  assert.equal(e.root.querySelectorAll('.marketing-material-chip').length,15);assert.match(cls(e.root,'marketing-status').textContent,/最多选择15/);
  await control(e.root,'移除素材 素材0').onclick();assert.equal(e.root.querySelectorAll('.marketing-material-chip').length,14);
  await btn(e.root,'下一页').onclick();assert.ok(e.calls.some(c=>c.url.includes('offset=24')));e.panel.suspend();
});

test('a rejected write retains the draft and refreshes revision before a new intent',async()=>{
  storage.clear();let fail=true;const e=environment((_url,init)=>{if(init?.method==='POST'&&fail)throw Object.assign(Error('版本冲突'),{status:409});});
  await e.panel.load({project:'p'});prompt(e.root,'冲突保稿');await send(e.root);assert.equal(control(e.root,'广告创作需求').value,'冲突保稿');assert.ok(btn(e.root,'重新读取项目'));
  const original=JSON.parse(writes(e)[0].init.body);fail=false;await btn(e.root,'重新读取项目').onclick();await send(e.root);
  assert.equal(writes(e).length,2);assert.notEqual(JSON.parse(writes(e)[1].init.body).idempotency_key,original.idempotency_key);e.panel.suspend();
});

test('late media failure does not replace the new project material list',async()=>{
  storage.clear();let reject;const hold=new Promise((_r,r)=>reject=r),e=environment(url=>url.includes('/p/media?')?hold:url.includes('/q/media?')?{items:[{id:'new',name:'新项目素材',modality:'image'}],total:1}:undefined);
  await e.panel.load({project:'p'});await e.panel.load({project:'q'});await settle();reject(Error('旧素材失败'));await settle();assert.match(cls(e.root,'marketing-media-grid').textContent,/新项目素材/);assert.doesNotMatch(cls(e.root,'marketing-media-grid').textContent,/旧素材失败/);e.panel.suspend();
});

test('the original import manifest supplies a registered material and advances the selected project revision',async()=>{
  storage.clear();const e=environment(url=>{
    if(url.endsWith('/media-imports'))return {items:[{id:'batch',title:'原清单',created_at:'2026-11-09T01:00:00Z'}],revision:10};
    if(url.endsWith('/media-imports/batch'))return {batch:{id:'batch',title:'原清单'},items:[{id:'item',filename:'上传商品图.png',status:'completed',media_id:'uploaded',uploaded_bytes:4,size_bytes:4}],revision:11};
    if(url.endsWith('/media/uploaded'))return {id:'uploaded',name:'上传商品图.png',modality:'image'};
  });
  await e.panel.load({project:'p'});const details=cls(e.root,'marketing-upload');details.open=true;await details.ontoggle();
  const select=control(e.root,'继续已有导入清单');select.value='batch';await btn(e.root,translate(msg('ui.read_original_manifest'))).onclick();
  await btn(e.root,translate(msg('ui.use_registered_file'))).onclick();assert.equal(e.root.querySelectorAll('.marketing-material-chip').length,1);
  assert.ok(e.revisions.some(([r,p])=>r===11&&p==='p'));prompt(e.root,'使用上传商品图');await send(e.root);
  const body=JSON.parse(writes(e)[0].init.body);assert.equal(body.expected_revision,11);assert.deepEqual(body.payload.media_ids,['uploaded']);e.panel.suspend();
});

test('the homepage marketing card points to the dedicated shared composer',async()=>{
  storage.clear();const e=environment(url=>url==='/api/v1/discovery'?{recent:[],skills:[],templates:[],tutorials:[],projects:[]}:undefined);
  const platform=createProductionPlatform(e.root,e.ctx);await platform.load({page:'home'});
  const card=e.root.querySelectorAll('.home-feature').find(n=>n.href?.includes('marketing-studio'));
  assert.ok(card);assert.equal(card.tagName,'A');assert.equal(new URLSearchParams(card.href.slice(1)).get('page'),'marketing-studio');platform.suspend();
});
