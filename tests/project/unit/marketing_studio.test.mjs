import assert from 'node:assert/strict';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

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
  addEventListener(type,fn){this.listeners??={};(this.listeners[type]??=[]).push(fn);}
  async fire(type,event={}){await this['on'+type]?.(event);for(const fn of this.listeners?.[type]||[])await fn(event);}
}
const document={documentElement:{},createElement(tag){return new Element(tag,this);},createTextNode(text){const n=new Element('#text',this);n.textContent=text;return n;},querySelector(){return null;}};
document.head=new Element('head',document);globalThis.document=document;
if(!globalThis.crypto)globalThis.crypto=webcrypto;
globalThis.location={search:'',href:''};
const storage=new Map();globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
const {createMarketingStudio,marketingStartKey}=await import('../../../src/vsc/interfaces/web/static/marketing-studio.js');
const {createProductionPlatform}=await import('../../../src/vsc/interfaces/web/static/production-platform.js');
const {translate,msg}=await import('../../../src/vsc/interfaces/web/static/i18n.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(){for(let i=0;i<12;i++)await tick();}
const methods=['short-drama-commerce','product-poster','viral-video-clone','commercial-tvc','ugc-commerce','viral-creative-variation','product-visual-materials','video-localization'].map((id,i)=>({id,name:['短剧带货','商品海报','爆款视频复刻','TVC广告片','UGC种草与带货','爆款素材裂变','商品视觉物料','视频翻译与渠道适配'][i],version:'1.0',sha256:'sha-'+id,skill_id:i===1?'image-generation':'video-generation',description:'方法：'+id,input_hint:'提示：'+id}));
const options=(revision=7)=>({revision,methods,episodes:[{id:'ep',name:'第一集'}],models:[{id:'image-model',model_key:'图片模型',enabled:true,modality:'image'},{id:'video-model',model_key:'视频模型',enabled:true,modality:'video'}],provider_submit:false});
const prepared=()=>({id:'c',canvas_id:'c',canvas_revision:1,sha256:'canvas-sha',episode_id:'ep',revision:8,agent_handoff:{skill_id:'image-generation',node_ids:['marketing-brief','marketing-method'],message:'原输入'}});
const startReceipt=(body,project='p')=>({project_id:project,canvas_id:'c',episode_id:'ep',prepare_key:body.payload.prepare_key,start_key:body.idempotency_key,canvas_revision:1,canvas_sha256:'canvas-sha',turn_id:'t',session_id:'session',dispatch_id:'dispatch',turn_status_at_commit:'queued',provider_submitted:false,revision:9});
const turn=(status='queued',extra={})=>({id:'t',project_id:'p',canvas_id:'c',episode_id:'ep',session_id:'session',canvas_revision:1,revision:9,status,model_ids:[],...extra});
const btn=(root,title)=>root.walk().find(n=>n.tagName==='BUTTON'&&n.textContent===title);
const cls=(root,name)=>root.querySelector('.'+name);
const control=(root,label)=>root.walk().find(n=>n.attributes['aria-label']===label);
function prompt(root,value){const input=control(root,'广告创作需求');input.value=value;input.oninput();}
async function send(root){await cls(root,'marketing-composer').onsubmit({preventDefault(){}});await settle();}
function environment(handler=()=>undefined){
  const root=new Element('main',document),calls=[],nav=[],revisions=[],session={actor:'a',csrf:'csrf-a',writable:false,writeAvailable:true,revision:999};
  const projects=[{id:'p',name:'营销项目',storage_policy:'postgres-series-v1'},{id:'q',name:'第二项目',storage_policy:'postgres-series-v1'}];
  let start=null,turnStatus='queued';
  const ctx={projects:()=>projects,session:()=>session,notice(){},setRevision:(r,p)=>revisions.push([r,p]),navigate:async(...args)=>{nav.push(args);},api:async(url,init)=>{
    calls.push({url,init});const handled=await handler(url,init);if(handled!==undefined)return handled;
    if(url.endsWith('marketing-options'))return options();
    if(url.endsWith('execution-authorizations'))return {items:[],revision:7};
    if(url.includes('/media?'))return {items:[],total:0};
    if(url.endsWith('marketing-canvases'))return prepared();
    if(url.endsWith('creative-canvases/c?version=1'))return {id:'c',canvas_revision:1,sha256:'canvas-sha',revision:8,document:{nodes:[{id:'marketing-brief',text:'原输入'}]}};
    if(url.endsWith('/marketing-canvases/c/start')){const body=JSON.parse(init.body);start=body;return startReceipt(body,new URL(url,'http://test').pathname.split('/')[4]);}
    if(url.endsWith('/creative-canvas-agent-turns/t/execute')){turnStatus='needs_input';return {id:'t',status:turnStatus};}
    if(url.endsWith('/creative-canvas-agent-turns/t'))return {id:'t',project_id:new URL(url,'http://test').pathname.split('/')[4],canvas_id:'c',episode_id:'ep',session_id:'session',canvas_revision:1,revision:9,status:turnStatus,model_ids:start?.payload.model_ids||[]};
    throw Error('Unexpected '+url);
  }};
  const panel=createMarketingStudio(root,ctx);return {root,panel,calls,nav,revisions,ctx,session,projects};
}
const writes=e=>e.calls.filter(c=>c.init?.method==='POST'&&c.url.endsWith('marketing-canvases'));
const starts=e=>e.calls.filter(c=>c.init?.method==='POST'&&c.url.endsWith('/start'));
const executes=e=>e.calls.filter(c=>c.init?.method==='POST'&&c.url.endsWith('/execute'));

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
  assert.ok(e.calls.findIndex(c=>c.url.endsWith('creative-canvases/c?version=1'))>e.calls.findIndex(c=>c.init?.method==='POST'));
  assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);
  assert.deepEqual(e.nav[0],['creative-canvas',null,'p',{task_target:'c',episode:'ep',marketing:'1',agent_turn:'t'}]);
  assert.equal(new URLSearchParams(e.nav[0][3]).has('prompt'),false);e.panel.suspend();
});

test('method is optional and model preferences are fixed in the original start request',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'只确认创意');await send(e.root);
  const body=JSON.parse(writes(e)[0].init.body);assert.equal(body.payload.method_id,null);assert.equal('method_version'in body.payload,false);assert.equal('model_ids'in body.payload,false);
  assert.equal(e.root.querySelectorAll('.marketing-method').filter(n=>n.attributes['aria-pressed']==='true').length,1);
  assert.deepEqual(JSON.parse(starts(e)[0].init.body).payload.model_ids,[]);await control(e.root,'选择模型').onclick();assert.equal(cls(e.root,'marketing-execution-panel').hidden,false);e.panel.suspend();
});

test('prompt validation counts Unicode characters and keeps unmodified input',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});
  prompt(e.root,'😀'.repeat(2000));assert.equal(cls(e.root,'marketing-submit').disabled,false);
  prompt(e.root,'😀'.repeat(2001));assert.equal(cls(e.root,'marketing-submit').disabled,true);await send(e.root);assert.equal(writes(e).length,0);
  prompt(e.root,'   ');await send(e.root);assert.equal(writes(e).length,0);e.panel.suspend();
});

test('response loss restores a fixed payload, revision and idempotency key after remount',async()=>{
  storage.clear();let fail=true;const requests=[];
  const handler=(url,init)=>{if(init?.method==='POST'&&url.endsWith('marketing-canvases')){requests.push(init.body);if(fail)throw Error('响应丢失');}};
  const e=environment(handler);await e.panel.load({project:'p'});prompt(e.root,'固定需求');await send(e.root);
  assert.equal(control(e.root,'广告创作需求').disabled,true);assert.match(cls(e.root,'marketing-status').textContent,/恢复同一操作/);e.panel.suspend();
  fail=false;const f=environment(handler);f.session.revision=1000;await f.panel.load({project:'p'});await send(f.root);
  assert.equal(requests.length,2);assert.equal(requests[0],requests[1]);assert.equal(f.nav.length,1);f.panel.suspend();
});

test('successful write and failed readback retry only the original canvas GET',async()=>{
  storage.clear();let fail=true;const e=environment(url=>{if(url.endsWith('creative-canvases/c?version=1')&&fail)throw Error('读回断网');});
  await e.panel.load({project:'p'});prompt(e.root,'测试读回');await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.nav.length,0);
  fail=false;await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.nav.length,1);assert.equal(e.calls.filter(c=>c.url.endsWith('creative-canvases/c?version=1')).length,2);e.panel.suspend();
});

test('navigation failure retries navigation without another write or readback',async()=>{
  storage.clear();let fail=true;const e=environment();e.ctx.navigate=async(...args)=>{e.nav.push(args);if(fail)throw Error('打开失败');};
  await e.panel.load({project:'p'});prompt(e.root,'测试导航');await send(e.root);assert.equal(e.nav.length,1);
  fail=false;await send(e.root);assert.equal(writes(e).length,1);assert.equal(e.calls.filter(c=>c.url.endsWith('creative-canvases/c?version=1')).length,1);assert.equal(e.nav.length,2);e.panel.suspend();
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
  const e=environment((url,init)=>{if(init?.method==='POST'&&url.endsWith('marketing-canvases')){
    const request=JSON.parse(init.body);keys.push(request.idempotency_key);attempt++;
    if(attempt===2)throw Object.assign(Error('操作会话已过期'),{status:403});
    committed.add(request.idempotency_key);if(attempt===1)throw Error('响应丢失');
  }});
  await e.panel.load({project:'p'});prompt(e.root,'未知结果后恢复');await send(e.root);await send(e.root);
  assert.equal(control(e.root,'广告创作需求').disabled,true);await send(e.root);
  assert.equal(committed.size,1);assert.equal(new Set(keys).size,1);assert.equal(e.nav.length,1);e.panel.suspend();
});

test('duplicate submit is blocked while the first request is running',async()=>{
  storage.clear();let finish;const hold=new Promise(r=>finish=r),e=environment((url,init)=>init?.method==='POST'&&url.endsWith('marketing-canvases')?hold:undefined);
  await e.panel.load({project:'p'});prompt(e.root,'重复点击');const a=send(e.root);await tick();await send(e.root);assert.equal(writes(e).length,1);
  finish(prepared());await a;assert.equal(e.nav.length,1);e.panel.suspend();
});

test('late project options, media and write callbacks cannot change the new project',async()=>{
  storage.clear();let finishOptions;const holdOptions=new Promise(r=>finishOptions=r);const e=environment(url=>url.includes('/p/marketing-options')?holdOptions:undefined);
  const a=e.panel.load({project:'p'});await e.panel.load({project:'q'});prompt(e.root,'第二项目');finishOptions(options(400));await a;
  assert.equal(control(e.root,'归属项目').value,'q');assert.equal(control(e.root,'广告创作需求').value,'第二项目');assert.equal(e.revisions.some(([r])=>r===400),false);e.panel.suspend();
  let finishWrite;const holdWrite=new Promise(r=>finishWrite=r),f=environment((url,init)=>init?.method==='POST'&&url.endsWith('marketing-canvases')?holdWrite:undefined);
  await f.panel.load({project:'p'});prompt(f.root,'第一项目操作');const pending=send(f.root);await tick();await f.panel.load({project:'q'});prompt(f.root,'第二项目保稿');
  finishWrite({...prepared(),revision:9999});await pending;assert.equal(f.nav.length,0);assert.equal(f.revisions.some(([r])=>r===9999),false);assert.equal(control(f.root,'广告创作需求').value,'第二项目保稿');
  await f.panel.load({project:'p'});assert.equal(btn(f.root,'继续开始创作').disabled,false);f.panel.suspend();
});

test('suspend and actor changes reject success, error and finally callbacks',async()=>{
  storage.clear();let finish;const hold=new Promise(r=>finish=r),e=environment((url,init)=>init?.method==='POST'&&url.endsWith('marketing-canvases')?hold:undefined);
  await e.panel.load({project:'p'});prompt(e.root,'旧身份需求');const a=send(e.root);await tick();e.session.actor='b';await e.panel.load({project:'p'});prompt(e.root,'新身份保稿');
  finish({...prepared(),revision:500});await a;assert.equal(e.nav.length,0);assert.equal(control(e.root,'广告创作需求').value,'新身份保稿');assert.equal(cls(e.root,'marketing-submit').disabled,false);e.panel.suspend();
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

test('start key uses the fixed UTF-8 SHA256 vector and exact strict request envelope',async()=>{
  assert.equal(await marketingStartKey('00000000-0000-4000-8000-000000000000'),'marketing-start:db8055e0e0307d5a016bec4dc338d69875eb0fb7e614a8b125b08fb082095d98');
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'固定首句');await send(e.root);
  const r=JSON.parse(writes(e)[0].init.body),s=JSON.parse(starts(e)[0].init.body);
  assert.deepEqual(Object.keys(s).sort(),['expected_revision','idempotency_key','payload']);assert.deepEqual(Object.keys(s.payload).sort(),['canvas_revision','canvas_sha256','execution_settings','mode','model_ids','prepare_key']);
  assert.equal(s.idempotency_key,await marketingStartKey(r.idempotency_key));assert.equal(s.payload.canvas_sha256,'canvas-sha');assert.equal(s.payload.canvas_revision,1);assert.equal(s.expected_revision,8);e.panel.suspend();
});

test('model selection records click order and manual or auto-drafts never grants automatic media',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});
  for(const name of ['视频模型','图片模型']){const c=control(e.root,'优先模型 '+name);c.checked=true;c.onchange();}
  const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();prompt(e.root,'只排节点');await send(e.root);
  const payload=JSON.parse(starts(e)[0].init.body).payload;assert.deepEqual(payload.model_ids,['video-model','image-model']);assert.equal(payload.mode,'auto_drafts');assert.equal('auto_media'in payload.execution_settings,false);e.panel.suspend();
});

test('bounded automatic media freezes the original scope, explicit allowance and absolute deadlines through a lost start',async()=>{
  storage.clear();let fail=true;const attempts=[];const e=environment((url,init)=>{if(url.endsWith('/start')){attempts.push(init.body);if(fail)throw Error('start response lost');}});
  await e.panel.load({project:'p'});const c=control(e.root,'优先模型 图片模型');c.checked=true;c.onchange();const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();const auto=control(e.root,'自动生成图片和视频（有界）');auto.checked=true;auto.onchange();
  for(const [name,value]of [['本轮最多任务','3'],['本轮最多图片','2'],['本轮视频总秒数','7'],['本轮商业额度上限','15']]){const f=control(e.root,name);f.value=value;f.oninput();}
  const scope=control(e.root,translate(msg('ui.production_authorization_scope'))),reason=control(e.root,translate(msg('ui.reason_for_the_new_batch')));scope.value='new_batch';reason.value='本轮明确有界测试';
  prompt(e.root,'测试有界范围');await send(e.root);assert.equal(starts(e).length,1);const first=JSON.parse(attempts[0]).payload;
  assert.equal(first.mode,'auto_drafts');assert.equal(first.execution_settings.auto_media.max_credits,15);assert.equal(first.execution_settings.auto_media.max_jobs,3);assert.equal(first.execution_settings.auto_media.max_video_ms,7000);assert.equal(first.execution_settings.execution_policy.authorization.mode,'new_batch');assert.match(first.execution_settings.auto_media.stop_submitting_at,/Z$/);
  e.panel.suspend();fail=false;await e.panel.load({project:'p'});await send(e.root);assert.equal(attempts.length,2);assert.equal(attempts[0],attempts[1]);assert.equal(writes(e).length,1);e.panel.suspend();
});

test('model panel groups real local models, uses two source modes and enforces the eight-model ordered limit',async()=>{
  storage.clear();const e=environment(url=>url.endsWith('marketing-options')?{...options(),models:Array.from({length:9},(_,i)=>({id:'model-'+i,enabled:true,modality:i%2?'video':'image',model_key:'本机模型'+i}))}:undefined);
  await e.panel.load({project:'p'});assert.deepEqual(control(e.root,'创作模式').children.map(n=>n.textContent),['手动模式','自动模式']);assert.equal(e.root.querySelectorAll('.marketing-model-group').length,2);
  for(let i=0;i<9;i++){const c=control(e.root,'优先模型 本机模型'+i);c.checked=true;c.onchange();}assert.equal(control(e.root,'优先模型 本机模型8').checked,false);
  prompt(e.root,'最多八模型');await send(e.root);assert.deepEqual(JSON.parse(starts(e)[0].init.body).payload.model_ids,Array.from({length:8},(_,i)=>'model-'+i));e.panel.suspend();
});

test('automatic media rejects missing models, blank or fractional allowance before creating any canvas',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'边界测试');const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();const auto=control(e.root,'自动生成图片和视频（有界）');auto.checked=true;auto.onchange();await send(e.root);assert.equal(writes(e).length,0);
  const model=control(e.root,'优先模型 图片模型');model.checked=true;model.onchange();for(const value of ['', '0.5','-1']){const cap=control(e.root,'本轮商业额度上限');cap.value=value;cap.oninput();await send(e.root);assert.equal(writes(e).length,0);}e.panel.suspend();
});

test('lost start followed by an expired session retains the same start body, R, S and one turn',async()=>{
  storage.clear();let attempt=0;const bodies=[];const e=environment((url,init)=>{if(url.endsWith('/start')){bodies.push(init.body);attempt++;if(attempt===1)throw Error('response lost');if(attempt===2)throw Object.assign(Error('expired'),{status:403});}});
  await e.panel.load({project:'p'});prompt(e.root,'首轮只补问');await send(e.root);await send(e.root);assert.equal(control(e.root,'广告创作需求').disabled,true);await send(e.root);
  assert.equal(bodies.length,3);assert.equal(new Set(bodies).size,1);assert.equal(writes(e).length,1);assert.equal(executes(e).length,1);assert.equal(e.nav[0][3].agent_turn,'t');e.panel.suspend();
});

test('a lost turn readback after start never repeats prepare or start',async()=>{
  storage.clear();let fail=true;const e=environment(url=>{if(url.endsWith('/creative-canvas-agent-turns/t')&&fail)throw Error('turn read lost');});
  await e.panel.load({project:'p'});prompt(e.root,'读回规划');await send(e.root);assert.equal(executes(e).length,0);fail=false;await send(e.root);assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);e.panel.suspend();
});

for(const status of ['running','needs_input','planned','applied','submission_unknown','failed'])test(`execute response loss recovers status ${status} with GET of the same turn only`,async()=>{
  storage.clear();let current='queued';const e=environment((url)=>{if(url.endsWith('/creative-canvas-agent-turns/t'))return turn(current);if(url.endsWith('/execute')){current=status;throw Error('execute response lost');}});
  await e.panel.load({project:'p'});prompt(e.root,'只执行原规划');await send(e.root);await send(e.root);
  assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);assert.equal(e.nav[0][3].agent_turn,'t');e.panel.suspend();
});

test('result_ready recovery finishes the same turn while a dropped pre-submit execute may resume queued',async()=>{
  for(const intermediate of ['queued','result_ready']){
    storage.clear();let current='queued',attempts=0;const e=environment(url=>{if(url.endsWith('/creative-canvas-agent-turns/t'))return turn(current);if(url.endsWith('/execute')){attempts++;if(attempts===1){current=intermediate;throw Error('lost execute');}current='planned';return {status:current};}});
    await e.panel.load({project:'p'});prompt(e.root,'恢复原执行');await send(e.root);await send(e.root);assert.equal(executes(e).length,2);assert.equal(starts(e).length,1);assert.equal(e.nav[0][3].agent_turn,'t');e.panel.suspend();
  }
});

test('a swallowed navigation error retains both original receipts and reads T before navigating again',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});prompt(e.root,'导航恢复');await send(e.root);await send(e.root);
  assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);assert.equal(e.nav.length,2);assert.equal(e.nav[0][3].agent_turn,e.nav[1][3].agent_turn);e.panel.suspend();
});

test('a late start receipt after actor switch cannot read, execute or navigate in the new identity',async()=>{
  storage.clear();let resolve,body;const wait=new Promise(r=>resolve=r),e=environment((url,init)=>{if(url.endsWith('/start')){body=JSON.parse(init.body);return wait;}});
  await e.panel.load({project:'p'});prompt(e.root,'原身份首句');const pending=send(e.root);while(!body)await tick();e.session.actor='b';await e.panel.load({project:'p'});prompt(e.root,'新身份保稿');resolve(startReceipt(body));await pending;
  assert.equal(executes(e).length,0);assert.equal(e.nav.length,0);assert.equal(control(e.root,'广告创作需求').value,'新身份保稿');e.session.actor='a';await e.panel.load({project:'p'});await send(e.root);assert.equal(starts(e).length,1);assert.equal(e.nav[0][3].agent_turn,'t');e.panel.suspend();
});

test('foreign turn or mismatched fixed canvas cannot proceed to execution',async()=>{
  for(const mismatch of ['canvas','turn','turn-version']){
    storage.clear();const e=environment(url=>mismatch==='canvas'&&url.includes('?version=1')?{id:'c',canvas_revision:2,sha256:'changed',revision:9}:mismatch==='turn'&&url.endsWith('/creative-canvas-agent-turns/t')?turn('queued',{project_id:'foreign'}):mismatch==='turn-version'&&url.endsWith('/creative-canvas-agent-turns/t')?turn('queued',{canvas_revision:2}):undefined);
    await e.panel.load({project:'p'});prompt(e.root,'核归属');await send(e.root);assert.equal(executes(e).length,0);assert.equal(e.nav.length,0);if(mismatch==='canvas')assert.equal(starts(e).length,0);assert.ok(btn(e.root,'开始新创作'));e.panel.suspend();
  }
});

test('a legacy prepared receipt remains inert on load and continues with its original R only after a click',async()=>{
  storage.clear();const body={payload:{prompt:'旧版本已准备需求',episode_id:'ep',method_id:null,media_ids:[]},expected_revision:7,idempotency_key:'legacy-prepare-key'};
  storage.set('vsc-marketing:request:'+JSON.stringify(['a','p']),JSON.stringify({actor:'a',project:'p',request:body,result:prepared(),readback:true}));
  const e=environment();await e.panel.load({project:'p'});assert.equal(starts(e).length,0);assert.equal(executes(e).length,0);await send(e.root);assert.equal(writes(e).length,0);assert.equal(JSON.parse(starts(e)[0].init.body).payload.prepare_key,body.idempotency_key);assert.equal(e.nav[0][3].agent_turn,'t');e.panel.suspend();
});

test('shell routing preserves agent_turn for its canvas and clears it when opening a different canvas or project',()=>{
  const source=readFileSync(new URL('../../../src/vsc/interfaces/web/static/panel.js',import.meta.url),'utf8'),names=['setEntryOptions','openedCreativeTarget','syncRoute'];
  const functions=names.map(name=>{const body=source.match(new RegExp('function '+name+'\\([\\s\\S]*?\\n}'));assert.ok(body);return body[0];}).join('\n');
  const win={location:{search:''},history:{pushState(_a,_b,url){win.location.search=url;},replaceState(_a,_b,url){win.location.search=url;}}},context={window:win,URLSearchParams,state:{project:'p',view:'creative-canvas',object:null},episodeScope:'ep',restoringDeskRoute:false,deskRouteReady:false,currentEntry:()=>new URLSearchParams(win.location.search),updateShell(){}};
  vm.createContext(context);vm.runInContext(functions,context);context.setEntryOptions('creative-canvas','p',null,{task_target:'c',episode:'ep',marketing:'1',agent_turn:'t'});context.syncRoute();assert.equal(new URLSearchParams(win.location.search).get('agent_turn'),'t');
  context.openedCreativeTarget('c','p','ep');assert.equal(new URLSearchParams(win.location.search).get('agent_turn'),'t');context.openedCreativeTarget('other','p','ep');assert.equal(new URLSearchParams(win.location.search).has('agent_turn'),false);
  context.setEntryOptions('creative-canvas','p',null,{task_target:'c',agent_turn:'t'});context.state.project='q';context.syncRoute();assert.equal(new URLSearchParams(win.location.search).has('agent_turn'),false);
});
