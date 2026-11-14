import assert from 'node:assert/strict';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

// Component self-checks exercise request ownership and recovery. This small DOM
// does not stand in for the browser, authenticated HTTP, PostgreSQL or providers.
class Element {
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.attributes={};this.dataset={};this.className='';this.style={};this.clientWidth=Element.layoutWidth??1024;this.offsetHeight=560;this.scrollLeft=0;this._scrollTop=0;this.disabled=false;this.hidden=false;this.value='';this.isConnected=true;this.classList={add:(v)=>{this.className+=' '+v;},remove:(...values)=>{this.className=this.className.split(' ').filter(v=>!values.includes(v)).join(' ');}};}
  append(...nodes){for(const node of nodes)if(node instanceof Element){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(n=>n!==node);node.parentElement=this;this.children.push(node);}}
  get firstElementChild(){return this.children[0]||null;}
  get scrollTop(){return this._scrollTop;}
  set scrollTop(value){const next=Math.max(0,Number(value)||0);this._scrollTop=this.contentHeight()<next?0:next;}
  contentHeight(){const grid=this.walk().find(n=>n.className.split(' ').includes('marketing-case-grid'));if(!grid)return 100000;return grid.children.some(n=>n.className.split(' ').includes('marketing-case-card'))?100000:0;}
  reclampScroll(){this.scrollTop=this._scrollTop;if(this.parentElement)this.parentElement.reclampScroll();}
  replaceChildren(...nodes){this.children=[];this._text=null;this.append(...nodes);if(this.className.split(' ').includes('marketing-case-categories'))this.scrollLeft=0;if(this.className.split(' ').includes('marketing-case-grid'))this.reclampScroll();}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(n=>n!==fn);}
  contains(node){return node===this||this.walk().includes(node);}
  getBoundingClientRect(){return this.rect||{left:100,right:128,top:160,bottom:188,width:28,height:28};}
  setSelectionRange(start,end,direction='none'){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
  get textContent(){return (this._text??'')+this.children.map(n=>n.textContent).join('');}
  set textContent(value){this.children=[];this._text=String(value);}
  walk(){return this.children.flatMap(n=>[n,...n.walk()]);}
  querySelectorAll(selector){return this.walk().filter(n=>selector.startsWith('.')?n.className.split(' ').includes(selector.slice(1)):selector==='[role=status]'?n.attributes.role==='status':n.tagName===selector.toUpperCase());}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  addEventListener(type,fn){this.listeners??={};(this.listeners[type]??=[]).push(fn);}
  async fire(type,event={}){await this['on'+type]?.(event);for(const fn of this.listeners?.[type]||[])await fn(event);}
  showModal(){this.open=true;}close(){this.open=false;this.onclose?.();}remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;this.isConnected=false;}focus(){this.ownerDocument.activeElement=this;}play(){this.playCount=(this.playCount||0)+1;return this.playResult||Promise.resolve();}pause(){this.pauseCount=(this.pauseCount||0)+1;}
}
const document={documentElement:{},createElement(tag){return new Element(tag,this);},createTextNode(text){const n=new Element('#text',this);n.textContent=text;return n;},querySelector(){return null;}};
document.head=new Element('head',document);globalThis.document=document;
const documentListeners=new Map();document.addEventListener=(type,fn)=>{if(!documentListeners.has(type))documentListeners.set(type,new Set());documentListeners.get(type).add(fn);};document.removeEventListener=(type,fn)=>documentListeners.get(type)?.delete(fn);document.fire=(type,event={})=>{for(const fn of [...documentListeners.get(type)||[]])fn(event);};
if(!globalThis.crypto)globalThis.crypto=webcrypto;
globalThis.location={search:'',href:''};
const storage=new Map();globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
// Export fixtures from the owning pure catalogue. No PostgreSQL, HTTP, host or
// temporary developer fixture is needed when this checked-in test runs in CI.
const caseFixture=JSON.parse(execFileSync('python3',['-B','-c',`import json,sys
sys.path.insert(0,sys.argv[1])
from vsc.assets.marketing_cases import list_cases,get_case,case_spec_to_params
pages=[]
page=1
while page:
    value=list_cases(page=page)
    pages.append(value)
    page=value['next_page']
specs=[e for p in pages for g in p['items'] for e in g['examples']]
pin=lambda s:{k:s[k] for k in ('id','version','sha256')}
observed=next(s for s in specs if s['template_key']=='approved_7135edbbae7c4181')
print(json.dumps(dict(pages=pages,detail=get_case(pin(observed)),case=specs[0],case_ref=pin(specs[0]),params=case_spec_to_params(specs[0]),second_case=specs[1],second_case_ref=pin(specs[1]),catalog_sha256=pages[0]['catalog_sha256']),ensure_ascii=False))`,fileURLToPath(new URL('../../../src',import.meta.url))],{encoding:'utf8',maxBuffer:2*1024*1024}));
const allCaseGroups=caseFixture.pages.flatMap(page=>page.items);
const listCases=(url)=>{const p=new URL(url,'http://test').searchParams,category=p.get('category_name'),keyword=(p.get('keyword')||'').trim().toLocaleLowerCase(),page=Number(p.get('page')||1);const items=allCaseGroups.filter(g=>(!category||g.category_name===category)&&(!keyword||[g.group_name,g.group_description,g.category_label,...g.examples.map(e=>e.video_name)].some(v=>v.toLocaleLowerCase().includes(keyword))));return {...caseFixture.pages[0],page,total_available:items.length,next_page:page*20<items.length?page+1:null,items:items.slice((page-1)*20,page*20)};};
const {createMarketingStudio,marketingStartKey}=await import('../../../src/vsc/interfaces/web/static/marketing-studio.js');
const {createProductionPlatform}=await import('../../../src/vsc/interfaces/web/static/production-platform.js');
const {translate,msg,setLocale,getLocale}=await import('../../../src/vsc/interfaces/web/static/i18n.js');
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
    if(url.startsWith('/api/v1/marketing-cases?'))return listCases(url);
    if(url.startsWith('/api/v1/marketing-cases/')){const id=decodeURIComponent(url.split('/').at(-1).split('?')[0]),spec=allCaseGroups.flatMap(g=>g.examples).find(e=>e.id===id);return {catalog_version:caseFixture.pages[0].catalog_version,catalog_sha256:caseFixture.catalog_sha256,case:spec,detail_coverage:{basis:'list_projection',observed_source_detail:spec?.id===caseFixture.detail.case.id}};}
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
  assert.equal(e.root.querySelectorAll('.marketing-method').length,8);
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
  assert.equal(e.root.querySelectorAll('.marketing-method').filter(n=>n.attributes['aria-pressed']==='true').length,0);
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

const caseCards=e=>e.root.querySelectorAll('.marketing-case-card');
const caseLists=e=>e.calls.filter(c=>c.url.startsWith('/api/v1/marketing-cases?'));
const caseDetails=e=>e.calls.filter(c=>c.url.startsWith('/api/v1/marketing-cases/'));
const category=(e,name)=>e.root.querySelectorAll('.marketing-case-category').find(n=>n.dataset.category===name);
const chooseCase=(e,index=0)=>caseCards(e)[index].querySelector('.marketing-case-select').onclick({stopPropagation(){}});
const clone=value=>JSON.parse(JSON.stringify(value));

test('real packaged catalogue exposes all 114 groups across six pinned pages with the eleven category counts',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();assert.equal(caseCards(e).length,20);assert.equal(e.root.querySelectorAll('.marketing-case-category').length,12);
  for(const row of caseFixture.pages[0].categories)assert.match(category(e,row.category_name).textContent,new RegExp(String(row.available_group_count)+'$'));
  const sizes=[20];while(btn(e.root,'加载更多创意')){await btn(e.root,'加载更多创意').onclick();sizes.push(caseCards(e).length);}
  assert.deepEqual(sizes,[20,40,60,80,100,114]);assert.equal(new Set(caseCards(e).map(n=>n.dataset.groupKey)).size,114);
  assert.deepEqual(caseLists(e).map(c=>new URL(c.url,'http://test').searchParams.get('page')),['1','2','3','4','5','6']);
  for(const c of caseLists(e).slice(1))assert.equal(new URL(c.url,'http://test').searchParams.get('catalog_sha256'),caseFixture.catalog_sha256);
  assert.equal(Object.keys(caseFixture.case).length,18);assert.equal(writes(e).length,0);assert.equal(starts(e).length,0);e.panel.suspend();
});

test('category filtering uses real names and available totals while retaining the selected case',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();await chooseCase(e);const name=cls(e.root,'marketing-case-chip').textContent;
  for(const row of caseFixture.pages[0].categories){await category(e,row.category_name).onclick();while(btn(e.root,'加载更多创意'))await btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,row.available_group_count);assert.equal(cls(e.root,'marketing-case-chip').textContent,name);}
  assert.equal(writes(e).length,0);e.panel.suspend();
});

test('clicking the last category restores the category-row and page scroll positions',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();
  const last=caseFixture.pages[0].categories.at(-1);
  assert.equal(last.category_label,'活动促销');assert.equal(last.category_name,'活动促销');
  const beforeLeft=328,beforeTop=640;
  cls(e.root,'marketing-case-categories').scrollLeft=beforeLeft;e.root.scrollTop=beforeTop;
  await category(e,last.category_name).onclick();await settle();
  assert.deepEqual([cls(e.root,'marketing-case-categories').scrollLeft,e.root.scrollTop],[beforeLeft,beforeTop]);
  assert.equal(category(e,last.category_name).attributes['aria-pressed'],'true');
  assert.match(category(e,last.category_name).textContent,/^活动促销/);
  assert.equal(new URL(caseLists(e).at(-1).url,'http://test').searchParams.get('category_name'),'活动促销');
  assert.ok(caseCards(e).length>0);
  const popup=await openPicker(e),compactLeft=176,pageTop=e.root.scrollTop;
  popup.querySelector('.marketing-case-categories').scrollLeft=compactLeft;
  await popup.querySelectorAll('.marketing-case-category').find(n=>n.dataset.category==='活动促销').onclick();await settle();
  assert.equal(popup.querySelector('.marketing-case-categories').scrollLeft,compactLeft);
  assert.equal(e.root.scrollTop,pageTop);
  assert.equal(e.root.querySelectorAll('.marketing-case-categories').find(n=>!popup.contains(n)).scrollLeft,beforeLeft);
  e.panel.suspend();
});

test('a delayed category response keeps the page scroll and the cards already on screen',async()=>{
  storage.clear();let finish;const wait=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('category_name')==='活动促销'?wait:undefined);
  await e.panel.load({project:'p'});await settle();assert.ok(caseCards(e).length>0);
  const beforeTop=2558,beforeLeft=355;e.root.scrollTop=beforeTop;cls(e.root,'marketing-case-categories').scrollLeft=beforeLeft;
  const pending=category(e,'活动促销').onclick();
  assert.equal(e.root.scrollTop,beforeTop);assert.notEqual(caseCards(e).length,0);
  finish(listCases('/api/v1/marketing-cases?category_name=活动促销'));await pending;await settle();
  assert.equal(e.root.scrollTop,beforeTop);assert.equal(cls(e.root,'marketing-case-categories').scrollLeft,beforeLeft);
  assert.equal(category(e,'活动促销').attributes['aria-pressed'],'true');assert.ok(caseCards(e).length>0);e.panel.suspend();
});

test('search waits 300 ms and sends only the final trimmed keyword without rewriting raw prompt',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();prompt(e.root,' 原需求\n  ');const count=caseLists(e).length,input=control(e.root,'搜索营销创意');input.value='风';input.oninput();input.value='  复古  ';input.oninput();
  await settle();assert.equal(caseLists(e).length,count);await new Promise(r=>setTimeout(r,340));await settle();assert.equal(caseLists(e).length,count+1);
  assert.equal(new URL(caseLists(e).at(-1).url,'http://test').searchParams.get('keyword'),'复古');assert.equal(control(e.root,'广告创作需求').value,' 原需求\n  ');assert.ok(caseCards(e).length>0);e.panel.suspend();
});

test('selecting, reselecting, replacing and deleting a case are zero-write operations independent of all other inputs',async()=>{
  storage.clear();const e=environment(url=>url.includes('/media?')?{items:Array.from({length:15},(_,i)=>({id:'product-'+i,name:'商品图'+i,modality:'image'})),total:15}:undefined);
  await e.panel.load({project:'p'});await settle();const raw='  商品事实原文\n保持换行  ';prompt(e.root,raw);await btn(e.root,'商品海报').onclick();for(const card of e.root.querySelectorAll('.marketing-media-card'))await card.querySelector('button').onclick();
  for(const name of ['视频模型','图片模型']){const c=control(e.root,'优先模型 '+name);c.checked=true;c.onchange();}const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();
  const scope=control(e.root,translate(msg('ui.production_authorization_scope'))),reason=control(e.root,translate(msg('ui.reason_for_the_new_batch')));scope.value='new_batch';reason.value='原有执行范围';
  await chooseCase(e);await chooseCase(e);assert.equal(e.root.querySelectorAll('.marketing-selected-case').length,1);await chooseCase(e,1);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.second_case.group_name));
  await control(e.root,'删除已选创意').onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,'');assert.equal(writes(e).length,0);assert.equal(starts(e).length,0);
  await send(e.root);const p=JSON.parse(writes(e)[0].init.body).payload,s=JSON.parse(starts(e)[0].init.body).payload;assert.equal('case_ref'in p,false);assert.equal(p.prompt,raw);assert.equal(p.method_id,'product-poster');assert.equal(p.media_ids.length,15);assert.deepEqual(s.model_ids,['video-model','image-model']);assert.equal(s.execution_settings.execution_policy.authorization.reason,'原有执行范围');e.panel.suspend();
});

test('a case alone cannot start; a real selection adds exactly its three-field pin to prepare and nothing to start',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();await chooseCase(e);await send(e.root);assert.equal(writes(e).length,0);
  prompt(e.root,' 与案例独立的真实需求 ');await send(e.root);const p=JSON.parse(writes(e)[0].init.body).payload,s=JSON.parse(starts(e)[0].init.body).payload;
  assert.deepEqual(p.case_ref,caseFixture.case_ref);assert.deepEqual(Object.keys(p.case_ref).sort(),['id','sha256','version']);assert.equal(p.prompt,' 与案例独立的真实需求 ');assert.equal('case_ref'in s,false);assert.equal('video_url'in p,false);e.panel.suspend();
});

test('unknown prepare or start locks the original case and resumes the same body and canvas/turn',async()=>{
  for(const phase of ['prepare','start']){
    storage.clear();let fail=true;const e=environment((url)=>{if(fail&&(phase==='prepare'?url.endsWith('marketing-canvases'):url.endsWith('/start')))throw Error('response lost');});
    await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'原案例需求');await send(e.root);const original=JSON.parse(writes(e)[0].init.body),chip=cls(e.root,'marketing-case-chip').textContent;
    await chooseCase(e,1);await control(e.root,'删除已选创意').onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,chip);assert.equal(control(e.root,'删除已选创意').disabled,true);
    fail=false;await e.panel.load({project:'p'});await send(e.root);assert.deepEqual(JSON.parse(writes(e)[0].init.body),original);if(phase==='prepare')assert.equal(writes(e)[0].init.body,writes(e)[1].init.body);assert.equal(e.nav[0][3].agent_turn,'t');assert.deepEqual(JSON.parse(writes(e).at(-1).init.body).payload.case_ref,caseFixture.case_ref);e.panel.suspend();
  }
});

test('history keeps the original display snapshot when the current catalogue upgrades or disappears',async()=>{
  storage.clear();let unavailable=false;const e=environment((url)=>{if(unavailable&&url.startsWith('/api/v1/marketing-cases'))throw Object.assign(Error('new catalogue unavailable'),{status:404});});
  await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'历史需求');await send(e.root);e.panel.suspend();unavailable=true;await e.panel.load({project:'p'});await settle();
  assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));const prior=caseDetails(e).length;await cls(e.root,'marketing-case-chip-open').onclick();assert.equal(caseDetails(e).length,prior);assert.equal(cls(e.root,'marketing-case-full-description').textContent,caseFixture.case.group_description);
  await send(e.root);assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(e.nav.at(-1)[3].agent_turn,'t');e.panel.suspend();
});

test('missing historical display restores only from the fixed brief params, never today catalogue',async()=>{
  storage.clear();let lostDisplay=false;const e=environment(url=>lostDisplay&&url.endsWith('creative-canvases/c?version=1')?{id:'c',canvas_revision:1,sha256:'canvas-sha',revision:9,document:{nodes:[{id:'marketing-brief',params:caseFixture.params}]}}:lostDisplay&&url.startsWith('/api/v1/marketing-cases')?Promise.reject(Error('catalogue offline')):undefined);
  await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'从原brief恢复');await send(e.root);e.panel.suspend();
  const key='vsc-marketing:request:'+JSON.stringify(['a','p']),r=JSON.parse(storage.get(key));delete r.case_display;storage.set(key,JSON.stringify(r));const dkey='vsc-marketing:draft:'+JSON.stringify(['a','p']),draft=JSON.parse(storage.get(dkey));delete draft.case;storage.set(dkey,JSON.stringify(draft));lostDisplay=true;
  const f=environment(url=>url.endsWith('creative-canvases/c?version=1')?{id:'c',canvas_revision:1,sha256:'canvas-sha',revision:9,document:{nodes:[{id:'marketing-brief',params:caseFixture.params}]}}:url.startsWith('/api/v1/marketing-cases')?Promise.reject(Error('catalogue offline')):undefined);
  await f.panel.load({project:'p'});assert.match(cls(f.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));assert.deepEqual(JSON.parse(storage.get(key)).case_display,caseFixture.case);assert.equal(writes(f).length,0);f.panel.suspend();
});

test('later-page failure retains successful cards and retries the exact page and catalogue SHA',async()=>{
  storage.clear();let fail=true;const e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('page')==='2'&&fail?Promise.reject(Error('page lost')):undefined);
  await e.panel.load({project:'p'});await settle();await btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,20);const failed=caseLists(e).at(-1).url;fail=false;await btn(e.root,'重试读取创意').onclick();assert.equal(caseLists(e).at(-1).url,failed);assert.equal(caseCards(e).length,40);e.panel.suspend();
});

test('duplicate groups deduplicate but conflicting content or a new catalogue never mixes into existing pages',async()=>{
  for(const variant of ['same','conflict','new-H']){
    storage.clear();const e=environment(url=>{if(url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('page')==='2'){const data=clone(caseFixture.pages[1]);data.items[0]=clone(caseFixture.pages[0].items[0]);if(variant==='conflict')data.items[0].group_description='changed';if(variant==='new-H')data.catalog_sha256='f'.repeat(64);return data;}});
    await e.panel.load({project:'p'});await settle();await btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,variant==='same'?39:20);if(variant!=='same')assert.ok(btn(e.root,'重新载入目录'));e.panel.suspend();
  }
});

test('catalogue-change retry drops only H, retaining a historical selected pin and name',async()=>{
  storage.clear();let changed=false;const e=environment(url=>{if(changed&&url.startsWith('/api/v1/marketing-cases?')){const p=new URL(url,'http://test').searchParams;if(p.has('catalog_sha256'))throw Object.assign(Error('catalogue changed'),{status:409,code:'marketing_catalog_changed'});return {...listCases(url),catalog_sha256:'f'.repeat(64)};}});
  await e.panel.load({project:'p'});await settle();await chooseCase(e);changed=true;await btn(e.root,'加载更多创意').onclick();await btn(e.root,'重新载入目录').onclick();assert.equal(new URL(caseLists(e).at(-1).url,'http://test').searchParams.has('catalog_sha256'),false);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));assert.equal(writes(e).length,0);e.panel.suspend();
});

test('late filter success and error cannot overwrite the newest category or choose a detached card',async()=>{
  storage.clear();let finish;const old=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('category_name')==='视觉吸睛'?old:undefined);
  await e.panel.load({project:'p'});await settle();const detached=caseCards(e)[0].querySelector('.marketing-case-select');const pending=category(e,'视觉吸睛').onclick();await category(e,'品牌心智').onclick();finish(listCases('/api/v1/marketing-cases?category_name=视觉吸睛'));await pending;
  assert.equal(caseCards(e).length,6);await detached.onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,'');assert.equal(category(e,'品牌心智').attributes['aria-pressed'],'true');e.panel.suspend();
});

test('case data is isolated by actor/project, while a projectless choice seeds only its first project',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:null});await settle();await chooseCase(e);control(e.root,'归属项目').value='p';await control(e.root,'归属项目').onchange();await settle();assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));
  await e.panel.load({project:'q'});assert.equal(cls(e.root,'marketing-case-chip').textContent,'');await e.panel.load({project:'p'});assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));e.session.actor='other';await e.panel.load({project:'p'});assert.equal(cls(e.root,'marketing-case-chip').textContent,'');e.panel.suspend();
});

test('closing or switching details fences late replies and Escape returns focus without selection',async()=>{
  storage.clear();let finish;const wait=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases/'+encodeURIComponent(caseFixture.case.id)+'?')?wait:undefined);
  await e.panel.load({project:'p'});await settle();const first=caseCards(e)[0],pending=first.onclick();await caseCards(e)[1].onclick();const title=cls(e.root,'marketing-case-dialog').attributes['aria-label'];finish({...caseFixture.detail,case:caseFixture.case});await pending;assert.equal(cls(e.root,'marketing-case-dialog').attributes['aria-label'],title);
  const dialog=cls(e.root,'marketing-case-dialog'),trigger=caseCards(e)[1];await dialog.oncancel({preventDefault(){}});assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.equal(document.activeElement,trigger);assert.equal(cls(e.root,'marketing-case-chip').textContent,'');e.panel.suspend();
});

test('single explicit preview reads local bytes and pauses on error, filtering, hiding and suspend',async()=>{
  storage.clear();const e=environment();await e.panel.load({project:'p'});await settle();let stopped=false;const first=caseCards(e)[0],video=first.querySelector('video');await first.querySelector('.marketing-case-play').onclick({stopPropagation(){stopped=true;}});assert.equal(stopped,true);assert.equal(caseDetails(e).length,0);assert.equal(video.src,'/api/v1/marketing-assets/cases/'+caseFixture.case.template_key+'/video');assert.equal(first.querySelector('img').src,'/api/v1/marketing-assets/cases/'+caseFixture.case.template_key+'/cover');assert.equal(video.crossOrigin,'anonymous');assert.equal(video.preload,'none');assert.equal(video.muted,true);assert.equal(video.playsInline,true);
  const second=caseCards(e)[1],v2=second.querySelector('video');await second.querySelector('.marketing-case-play').onclick();assert.ok(video.pauseCount>0);v2.onerror();assert.match(second.querySelector('.marketing-case-play').textContent,/暂不可用/);
  await first.querySelector('.marketing-case-play').onclick();document.hidden=true;document.fire('visibilitychange');document.hidden=false;assert.ok(video.pauseCount>=2);await first.querySelector('.marketing-case-play').onclick();await category(e,'品牌心智').onclick();assert.ok(video.pauseCount>=3);
  const active=caseCards(e)[0].querySelector('video');await caseCards(e)[0].querySelector('.marketing-case-play').onclick();e.panel.suspend();assert.ok(active.pauseCount>0);assert.equal(e.calls.some(c=>c.url.startsWith('https:')),false);
});

test('hover honours pointer and reduced-motion settings while keyboard/touch playback remains explicit',async()=>{
  storage.clear();const prior=globalThis.matchMedia;globalThis.matchMedia=q=>({matches:q.includes('hover')});const e=environment();await e.panel.load({project:'p'});await settle();const card=caseCards(e)[0],video=card.querySelector('video');card.onpointerenter({pointerType:'mouse'});assert.equal(video.playCount,1);card.onpointerleave();assert.equal(video.pauseCount,1);
  globalThis.matchMedia=()=>({matches:true});card.onpointerenter({pointerType:'mouse'});assert.equal(video.playCount,1);await card.querySelector('.marketing-case-play').onclick();assert.equal(video.playCount,2);card.onpointerleave();card.onpointerenter({pointerType:'touch'});assert.equal(video.playCount,2);e.panel.suspend();globalThis.matchMedia=prior;
});

test('late preview resolution and detail errors after suspend never revive media or a dialog',async()=>{
  storage.clear();let resolve,reject;const play=new Promise(r=>resolve=r),detail=new Promise((_r,r)=>reject=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases/')?detail:undefined);
  await e.panel.load({project:'p'});await settle();const card=caseCards(e)[0],video=card.querySelector('video');video.playResult=play;await card.querySelector('.marketing-case-play').onclick();const pending=card.onclick();e.panel.suspend();resolve();reject(Error('late detail'));await pending;await settle();assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.ok(video.pauseCount>=1);
});

test('synthetic multi-example groups switch the real selected example and fence the old detail',async()=>{
  storage.clear();const group=clone(caseFixture.pages[0].items[0]),second={...clone(caseFixture.second_case),group_key:group.group_key,group_name:group.group_name,video_name:'合成多例测试二'};group.examples.push(second);let resolve;const late=new Promise(r=>resolve=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')?{...caseFixture.pages[0],items:[group],total_available:1,next_page:null}:url.startsWith('/api/v1/marketing-cases/'+encodeURIComponent(caseFixture.case.id)+'?')?late:url.startsWith('/api/v1/marketing-cases/')?{...caseFixture.detail,case:second}:undefined);
  await e.panel.load({project:'p'});await settle();const pending=caseCards(e)[0].onclick(),select=control(e.root,'切换详情案例');select.value=second.template_key;await select.onchange();resolve({...caseFixture.detail,case:caseFixture.case});await pending;assert.equal(control(e.root,'切换详情案例').value,second.template_key);await cls(e.root,'marketing-case-detail-select').onclick();assert.equal(JSON.parse(storage.get('vsc-marketing:draft:'+JSON.stringify(['a','p']))).case.id,second.id);assert.equal(writes(e).length,0);e.panel.suspend();
});

test('late catalogue responses are fenced by actor, project, account, locale and route',async()=>{
  for(const change of ['actor','project','account','locale','route']){
    storage.clear();let finish;const wait=new Promise(r=>finish=r),beforeLang=document.documentElement.lang,beforeRoute=location.search,e=environment(url=>url.startsWith('/api/v1/marketing-cases?')?wait:undefined);
    await e.panel.load({project:'p'});if(change==='actor'){e.session.actor='b';await e.panel.load({project:'p'});}else if(change==='project')await e.panel.load({project:'q'});else if(change==='account')e.session.account_id='other-account';else if(change==='locale')document.documentElement.lang='different-locale';else location.search='?page=other';
    finish(caseFixture.pages[0]);await settle();if(change==='actor'||change==='project')assert.equal(caseCards(e).length,20);else assert.equal(caseCards(e).length,0);
    assert.equal(writes(e).length,0);e.panel.suspend();document.documentElement.lang=beforeLang;location.search=beforeRoute;
  }
});

test('an obsolete catalogue error cannot replace the newest successful category',async()=>{
  storage.clear();let reject;const wait=new Promise((_r,r)=>reject=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('category_name')==='视觉吸睛'?wait:undefined);
  await e.panel.load({project:'p'});await settle();const pending=category(e,'视觉吸睛').onclick();await category(e,'品牌心智').onclick();reject(Error('obsolete error'));await pending;assert.equal(caseCards(e).length,6);assert.doesNotMatch(cls(e.root,'marketing-case-feedback').textContent,/obsolete error/);e.panel.suspend();
});

test('actual setLocale keeps visible case selection, details and preview usable without changing the composer',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();prompt(e.root,' 原文\n不随语言变化 ');const composer=control(e.root,'广告创作需求');
    setLocale('en',{persist:false});assert.equal(caseCards(e).length,20);await chooseCase(e);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));
    await caseCards(e)[0].onclick();assert.equal(caseDetails(e).length,1);await control(e.root,'关闭创意详情').onclick();const video=caseCards(e)[0].querySelector('video');await caseCards(e)[0].querySelector('.marketing-case-play').onclick();assert.equal(video.playCount,1);
    assert.equal(control(e.root,'广告创作需求'),composer);assert.equal(composer.value,' 原文\n不随语言变化 ');assert.equal(writes(e).length,0);assert.equal(starts(e).length,0);
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('actual locale change automatically restarts an unfinished catalogue and rejects old success or error',async()=>{
  for(const outcome of ['success','error']){
    storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let resolve,reject,count=0;const wait=new Promise((a,b)=>{resolve=a;reject=b;}),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&++count===1?wait:undefined);
    try{
      await e.panel.load({project:'p'});assert.equal(caseCards(e).length,0);setLocale('en',{persist:false});await settle();assert.equal(caseCards(e).length,20);assert.equal(caseLists(e).length,2);
      if(outcome==='success')resolve({...caseFixture.pages[0],items:[]});else reject(Error('old-language error'));await settle();assert.equal(caseCards(e).length,20);assert.doesNotMatch(cls(e.root,'marketing-case-feedback').textContent,/old-language error/);
      await chooseCase(e);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));assert.equal(writes(e).length,0);
    }finally{e.panel.suspend();setLocale(locale,{persist:false});}
  }
});

test('locale change during page two preserves page one, rebinds its buttons and resumes the same page/H',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let finish,count=0;const old=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('page')==='2'&&++count===1?old:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const loading=btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,20);await chooseCase(e);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));
    setLocale('en',{persist:false});await settle();assert.equal(caseCards(e).length,40);const reads=caseLists(e).filter(c=>new URL(c.url,'http://test').searchParams.get('page')==='2');assert.equal(reads.length,2);assert.equal(reads[0].url,reads[1].url);
    finish({...caseFixture.pages[1],items:[]});await loading;assert.equal(caseCards(e).length,40);await chooseCase(e,1);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.second_case.group_name));
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('locale change closes old details and pauses preview without letting late media or detail callbacks affect the new view',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let failOld,resolvePlay,detailCount=0;const detail=new Promise((_r,r)=>failOld=r),playing=new Promise(r=>resolvePlay=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases/')&&++detailCount===1?detail:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const oldCard=caseCards(e)[0],oldVideo=oldCard.querySelector('video');oldVideo.playResult=playing;await oldCard.querySelector('.marketing-case-play').onclick();const reading=oldCard.onclick();assert.ok(cls(e.root,'marketing-case-dialog'));
    setLocale('en',{persist:false});assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.ok(oldVideo.pauseCount>0);const video=caseCards(e)[1].querySelector('video');await caseCards(e)[1].querySelector('.marketing-case-play').onclick();assert.equal(video.playCount,1);
    failOld(Error('obsolete detail'));resolvePlay();await reading;await settle();assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.equal(video.pauseCount||0,0);assert.doesNotMatch(cls(e.root,'marketing-case-feedback').textContent,/obsolete detail/);
    await caseCards(e)[1].onclick();assert.equal(caseDetails(e).length,2);assert.equal(cls(e.root,'marketing-case-detail-status').textContent,'');
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('language change retains selected case, raw prompt, method, fifteen media, model order and original scope through unknown R or S',async()=>{
  for(const phase of ['prepare','start']){
    storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let fail=true;const e=environment(url=>url.includes('/media?')?{items:Array.from({length:15},(_,i)=>({id:'locale-product-'+i,name:'原图'+i,modality:'image'})),total:15}:fail&&(phase==='prepare'?url.endsWith('marketing-canvases'):url.endsWith('/start'))?Promise.reject(Error('unknown response')):undefined);
    try{
      await e.panel.load({project:'p'});await settle();const raw=' 原商品事实\n不改空格 ';prompt(e.root,raw);await btn(e.root,'商品海报').onclick();for(const card of e.root.querySelectorAll('.marketing-media-card'))await card.querySelector('button').onclick();
      for(const name of ['视频模型','图片模型']){const check=control(e.root,'优先模型 '+name);check.checked=true;check.onchange();}const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();const scope=control(e.root,translate(msg('ui.production_authorization_scope'))),reason=control(e.root,translate(msg('ui.reason_for_the_new_batch')));scope.value='new_batch';reason.value='语言切换前固定范围';await chooseCase(e);await send(e.root);
      const first=writes(e)[0].init.body,original=JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p']))),chip=cls(e.root,'marketing-case-chip').textContent,composer=control(e.root,'广告创作需求'),counts=[writes(e).length,starts(e).length,executes(e).length];
      setLocale('en',{persist:false});await settle();assert.deepEqual([writes(e).length,starts(e).length,executes(e).length],counts);assert.equal(composer,control(e.root,'广告创作需求'));assert.equal(composer.value,raw);assert.equal(scope.value,'new_batch');assert.equal(reason.value,'语言切换前固定范围');assert.equal(cls(e.root,'marketing-case-chip').textContent,chip);await chooseCase(e,1);await control(e.root,'删除已选创意').onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,chip);
      const after=JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p'])));assert.deepEqual(after,original);fail=false;await send(e.root);if(phase==='prepare')assert.equal(writes(e)[1].init.body,first);else assert.equal(starts(e)[0].init.body,starts(e)[1].init.body);
      const preparedBody=JSON.parse(writes(e)[0].init.body),started=JSON.parse(starts(e)[0].init.body);assert.equal(preparedBody.payload.media_ids.length,15);assert.equal(preparedBody.payload.method_id,'product-poster');assert.deepEqual(preparedBody.payload.case_ref,caseFixture.case_ref);assert.deepEqual(started.payload.model_ids,['video-model','image-model']);assert.equal(started.payload.execution_settings.execution_policy.authorization.reason,'语言切换前固定范围');assert.equal(e.nav.at(-1)[3].agent_turn,'t');
    }finally{e.panel.suspend();setLocale(locale,{persist:false});}
  }
});

test('language change neither sends a new turn nor executes an unknown original T',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let status='queued';const e=environment(url=>url.endsWith('/creative-canvas-agent-turns/t')?turn(status):url.endsWith('/execute')?(status='submission_unknown',Promise.reject(Error('execute response lost'))):undefined);
  try{
    await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'已有T');await send(e.root);const old=JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p'])));setLocale('en',{persist:false});await settle();assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);await send(e.root);assert.equal(executes(e).length,1);assert.equal(e.nav.at(-1)[3].agent_turn,old.startResult.turn_id);
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('a language change applies the current debounced search once instead of stranding its pending timer',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const input=control(e.root,'搜索营销创意'),initial=caseLists(e).length;input.value=' 复古 ';input.oninput();setLocale('en',{persist:false});await settle();assert.equal(caseLists(e).length,initial+1);assert.equal(new URL(caseLists(e).at(-1).url,'http://test').searchParams.get('keyword'),'复古');await new Promise(r=>setTimeout(r,340));assert.equal(caseLists(e).length,initial+1);await chooseCase(e);assert.ok(cls(e.root,'marketing-case-chip').textContent);
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('suspending unsubscribes locale work and a reloaded catalogue restores exactly one current subscription',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let calls=0,finish;const wait=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&++calls===2?wait:undefined);
  try{
    await e.panel.load({project:'p'});await settle();e.panel.suspend();const grid=cls(e.root,'marketing-case-grid'),before=grid.textContent,first=caseCards(e)[0],reads=caseLists(e).length;setLocale('en',{persist:false});await settle();assert.equal(cls(e.root,'marketing-case-grid'),grid);assert.equal(grid.textContent,before);assert.equal(caseCards(e)[0],first);assert.equal(caseLists(e).length,reads);
    await e.panel.load({project:'p'});setLocale('zh-cn',{persist:false});await settle();assert.equal(caseLists(e).length,reads+2);assert.equal(caseCards(e).length,20);finish(caseFixture.pages[0]);await settle();await chooseCase(e);assert.ok(cls(e.root,'marketing-case-chip').textContent);
  }finally{e.panel.suspend();setLocale(locale,{persist:false});}
});

test('locale rebinding disconnects stale masonry observers and preserves measured card reflow',async()=>{
  storage.clear();const locale=getLocale(),previousObserver=globalThis.ResizeObserver,observers=[];setLocale('zh-cn',{persist:false});globalThis.ResizeObserver=class {constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}};const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const old=observers.at(-1);setLocale('en',{persist:false});const current=observers.at(-1);assert.notEqual(old,current);assert.equal(old.disconnected,true);const card=caseCards(e)[0],before=card.style.gridRowEnd;card.offsetHeight=80;old.fn();assert.equal(card.style.gridRowEnd,before);current.fn();assert.ok(Number(card.style.gridRowEnd.split(' ').at(-1))<Number(before.split(' ').at(-1)));assert.equal(caseCards(e).length,20);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();globalThis.ResizeObserver=previousObserver;setLocale(locale,{persist:false});}
});

function scrollObservers({width=1024,intersection=true}={}){
  const previousIO=globalThis.IntersectionObserver,previousRO=globalThis.ResizeObserver,previousWidth=Element.layoutWidth,intersections=[],layouts=[];Element.layoutWidth=width;
  class IO{constructor(fn,options){this.fn=fn;this.options=options;intersections.push(this);}observe(target){this.target=target;}disconnect(){this.disconnected=true;}enter(isIntersecting=true){return this.fn([{target:this.target,isIntersecting}]);}}
  globalThis.IntersectionObserver=intersection?IO:undefined;globalThis.ResizeObserver=class {constructor(fn){this.fn=fn;layouts.push(this);}observe(){}disconnect(){this.disconnected=true;}};
  return {intersections,layouts,active:()=>intersections.findLast(o=>!o.disconnected&&o.target),restore(){globalThis.IntersectionObserver=previousIO;globalThis.ResizeObserver=previousRO;Element.layoutWidth=previousWidth;}};
}

test('intersecting the sentinel uses the scroll root and loads the next pinned page once while busy callbacks cannot repeat it',async()=>{
  storage.clear();const o=scrollObservers();let finish;const hold=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('page')==='2'?hold:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const observer=o.active();assert.ok(observer);assert.equal(observer.options.root,e.root);assert.equal(observer.options.rootMargin,'160px');assert.equal(observer.options.threshold,0);assert.equal(observer.target.attributes['aria-hidden'],'true');const initial=caseLists(e).length;observer.enter(false);assert.equal(caseLists(e).length,initial);
    const pending=observer.enter();observer.enter();assert.equal(observer.disconnected,true);assert.equal(o.active(),undefined);assert.equal(btn(e.root,'加载更多创意').disabled,true);await btn(e.root,'加载更多创意').onclick();assert.equal(caseLists(e).length,initial+1);
    const request=new URL(caseLists(e).at(-1).url,'http://test');assert.equal(request.searchParams.get('page'),'2');assert.equal(request.searchParams.get('catalog_sha256'),caseFixture.catalog_sha256);finish(caseFixture.pages[1]);await pending;assert.equal(caseCards(e).length,40);assert.ok(o.active());assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();o.restore();}
});

test('unmeasured masonry defers sentinel observation until container and card measurements are ready',async()=>{
  storage.clear();const o=scrollObservers({width:0}),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();assert.equal(caseCards(e).length,20);assert.equal(o.active(),undefined);assert.equal(btn(e.root,'加载更多创意').disabled,true);const reads=caseLists(e).length;await btn(e.root,'加载更多创意').onclick();assert.equal(caseLists(e).length,reads);
    const grid=cls(e.root,'marketing-case-grid');grid.clientWidth=900;caseCards(e)[0].offsetHeight=0;o.layouts.at(-1).fn();assert.equal(o.active(),undefined);
    for(const card of caseCards(e))card.offsetHeight=240;o.layouts.at(-1).fn();assert.ok(o.active());assert.equal(btn(e.root,'加载更多创意').disabled,false);await o.active().enter();assert.equal(caseCards(e).length,40);
  }finally{e.panel.suspend();o.restore();}
});

test('rerendering measurements, filtering and locale changes disconnect obsolete sentinels without breaking current observation',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});const o=scrollObservers(),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const first=o.active();o.layouts.at(-1).fn();assert.equal(first.disconnected,true);const measured=o.active(),reads=caseLists(e).length;first.enter();assert.equal(caseLists(e).length,reads);
    await category(e,'视觉吸睛').onclick();assert.equal(measured.disconnected,true);const filtered=o.active();assert.ok(filtered);const after=caseLists(e).length;measured.enter();assert.equal(caseLists(e).length,after);
    setLocale('en',{persist:false});assert.equal(filtered.disconnected,true);const rebound=o.active();filtered.enter();assert.equal(o.active(),rebound);assert.equal(caseLists(e).length,after);
    const search=control(e.root,'搜索营销创意');search.value='新筛选';search.oninput();assert.equal(rebound.disconnected,true);rebound.enter();assert.equal(caseLists(e).length,after);
  }finally{e.panel.suspend();o.restore();setLocale(locale,{persist:false});}
});

test('late sentinel callbacks cannot load under another actor/project/account/route or after suspend',async()=>{
  for(const change of ['actor','project','account','route','suspend']){
    storage.clear();const route=location.search,o=scrollObservers(),e=environment();
    try{
      await e.panel.load({project:'p'});await settle();const old=o.active();if(change==='actor'){e.session.actor='other';await e.panel.load({project:'p'});}else if(change==='project')await e.panel.load({project:'q'});else if(change==='account')e.session.account_id='different';else if(change==='route')location.search='?page=other';else e.panel.suspend();
      await settle();const current=o.active(),reads=caseLists(e).length;old.enter();assert.equal(caseLists(e).length,reads);assert.equal(old.disconnected,true);if(change==='actor'||change==='project')assert.equal(o.active(),current);
    }finally{e.panel.suspend();o.restore();location.search=route;}
  }
});

test('automatic loading ends at the real filtered tail and never asks for a seventh source page',async()=>{
  storage.clear();const o=scrollObservers(),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();let final;while(o.active()){final=o.active();await final.enter();}
    assert.equal(caseCards(e).length,114);assert.deepEqual(caseLists(e).map(c=>new URL(c.url,'http://test').searchParams.get('page')),['1','2','3','4','5','6']);assert.equal(cls(e.root,'marketing-case-sentinel'),null);assert.equal(btn(e.root,'加载更多创意'),undefined);const reads=caseLists(e).length;final.enter();final.enter();assert.equal(caseLists(e).length,reads);
    await category(e,'视觉吸睛').onclick();await o.active().enter();assert.equal(caseCards(e).length,27);assert.equal(o.active(),undefined);assert.equal(btn(e.root,'加载更多创意'),undefined);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();o.restore();}
});

test('automatic page failures stop observation and explicit retry retains the exact page and H',async()=>{
  storage.clear();const o=scrollObservers();let fail=true;const e=environment(url=>fail&&url.startsWith('/api/v1/marketing-cases?')&&new URL(url,'http://test').searchParams.get('page')==='2'?Promise.reject(Error('page transport error')):undefined);
  try{
    await e.panel.load({project:'p'});await settle();const old=o.active();await old.enter();assert.equal(caseCards(e).length,20);assert.equal(o.active(),undefined);const reads=caseLists(e).length,url=caseLists(e).at(-1).url;old.enter();assert.equal(caseLists(e).length,reads);fail=false;await btn(e.root,'重试读取创意').onclick();assert.equal(caseLists(e).at(-1).url,url);assert.equal(caseCards(e).length,40);assert.ok(o.active());
  }finally{e.panel.suspend();o.restore();}
});

test('manual loading remains available and bounded when IntersectionObserver is not supported',async()=>{
  storage.clear();const o=scrollObservers({intersection:false}),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();assert.equal(cls(e.root,'marketing-case-sentinel'),null);const manual=btn(e.root,'加载更多创意');assert.equal(manual.tagName,'BUTTON');assert.equal(manual.type,'button');assert.equal(manual.disabled,false);while(btn(e.root,'加载更多创意'))await btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,114);assert.equal(caseLists(e).length,6);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();o.restore();}
});

test('a total already reached or an empty next page cannot manufacture further observation or pseudo pages',async()=>{
  for(const variant of ['total','empty']){
    storage.clear();const o=scrollObservers(),e=environment(url=>{if(!url.startsWith('/api/v1/marketing-cases?'))return;const page=new URL(url,'http://test').searchParams.get('page');if(variant==='total'&&page==='1')return {...caseFixture.pages[0],total_available:20,next_page:2};if(variant==='empty'&&page==='2')return {...caseFixture.pages[1],items:[],next_page:3};});
    try{
      await e.panel.load({project:'p'});await settle();if(variant==='empty')await o.active().enter();assert.equal(o.active(),undefined);assert.equal(btn(e.root,'加载更多创意'),undefined);assert.equal(caseLists(e).length,variant==='total'?1:2);
    }finally{e.panel.suspend();o.restore();}
  }
});

test('hidden or leaving pages disconnect the observer and a visible current view can safely resume',async()=>{
  storage.clear();const previousWindow=globalThis.window,listeners=new Map();globalThis.window={addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn);},removeEventListener(type,fn){listeners.get(type)?.delete(fn);}};const o=scrollObservers(),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const old=o.active();document.hidden=true;document.fire('visibilitychange');assert.equal(old.disconnected,true);assert.equal(o.active(),undefined);const reads=caseLists(e).length;old.enter();assert.equal(caseLists(e).length,reads);document.hidden=false;document.fire('visibilitychange');assert.ok(o.active());const visible=o.active();
    for(const fn of listeners.get('popstate'))fn();assert.equal(visible.disconnected,true);visible.enter();assert.equal(caseLists(e).length,reads);
  }finally{e.panel.suspend();document.hidden=false;o.restore();globalThis.window=previousWindow;}
});

test('a busy original marketing write prevents auto or manual paging and resumes only read-only continuation afterwards',async()=>{
  storage.clear();const o=scrollObservers();let finish;const hold=new Promise(r=>finish=r),e=environment((url,init)=>init?.method==='POST'&&url.endsWith('marketing-canvases')?hold:undefined);
  try{
    await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'固定原意图');const old=o.active(),reads=caseLists(e).length,pending=send(e.root);await tick();assert.equal(old.disconnected,true);assert.equal(o.active(),undefined);old.enter();await btn(e.root,'加载更多创意').onclick();assert.equal(caseLists(e).length,reads);finish(prepared());await pending;assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);await o.active().enter();assert.equal(caseCards(e).length,40);assert.equal(writes(e).length,1);assert.equal(e.nav[0][3].agent_turn,'t');
  }finally{e.panel.suspend();o.restore();}
});

test('an obsolete catalogue-H observer cannot continue after an explicit directory reload',async()=>{
  storage.clear();const o=scrollObservers();let changed=false;const nextH='f'.repeat(64),e=environment(url=>{if(changed&&url.startsWith('/api/v1/marketing-cases?')){const p=new URL(url,'http://test').searchParams;if(p.get('catalog_sha256')===caseFixture.catalog_sha256)throw Object.assign(Error('catalogue changed'),{status:409,code:'marketing_catalog_changed'});return {...listCases(url),catalog_sha256:nextH};}});
  try{
    await e.panel.load({project:'p'});await settle();await chooseCase(e);const old=o.active();changed=true;await old.enter();assert.equal(o.active(),undefined);await btn(e.root,'重新载入目录').onclick();const current=o.active(),reads=caseLists(e).length;assert.ok(current);old.enter();assert.equal(o.active(),current);assert.equal(caseLists(e).length,reads);await current.enter();assert.equal(new URL(caseLists(e).at(-1).url,'http://test').searchParams.get('catalog_sha256'),nextH);assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();o.restore();}
});

test('automatic paging pauses while details are open and rearms only after the user closes them',async()=>{
  storage.clear();const o=scrollObservers(),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const old=o.active();await caseCards(e)[0].onclick();assert.equal(old.disconnected,true);assert.equal(o.active(),undefined);const reads=caseLists(e).length;old.enter();assert.equal(caseLists(e).length,reads);assert.ok(cls(e.root,'marketing-case-dialog'));await control(e.root,'关闭创意详情').onclick();assert.ok(o.active());await o.active().enter();assert.equal(caseCards(e).length,40);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();o.restore();}
});

const picker=e=>cls(e.root,'marketing-creative-picker');
const pickerRows=e=>picker(e)?.querySelectorAll('.marketing-case-option')||[];
async function openPicker(e){await control(e.root,'创意').onclick();await settle();return picker(e);}

test('composer creative picker selects the same pin, closes and restores the original raw text selection without writing',async()=>{
  storage.clear();const e=environment(url=>url.includes('/media?')?{items:Array.from({length:15},(_,i)=>({id:'picker-product-'+i,name:'商品'+i,modality:'image'})),total:15}:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const raw=' 原商品事实\n保留光标和原文 ';prompt(e.root,raw);const input=control(e.root,'广告创作需求');input.setSelectionRange(2,8,'backward');await btn(e.root,'商品海报').onclick();for(const card of e.root.querySelectorAll('.marketing-media-card'))await card.querySelector('button').onclick();
    for(const name of ['视频模型','图片模型']){const n=control(e.root,'优先模型 '+name);n.checked=true;n.onchange();}const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();const scope=control(e.root,translate(msg('ui.production_authorization_scope'))),reason=control(e.root,translate(msg('ui.reason_for_the_new_batch')));scope.value='new_batch';reason.value='选择案例不改范围';
    const popup=await openPicker(e);assert.ok(popup);assert.equal(popup.style.width,'407px');assert.equal(pickerRows(e).length,20);assert.equal(popup.querySelector('header'),null);assert.equal(popup.querySelector('h2'),null);assert.equal(popup.querySelector('.marketing-picker-close'),null);assert.equal(popup.querySelector('.marketing-case-count'),null);assert.equal(popup.querySelectorAll('.marketing-case-category').some(n=>n.querySelector('small')),false);assert.ok(cls(e.root,'marketing-case-count'));assert.ok(category(e,'品牌心智').querySelector('small'));assert.equal(document.activeElement,control(e.root,'搜索紧凑创意'));await pickerRows(e)[0].onclick();assert.equal(picker(e),null);assert.equal(document.activeElement,input);assert.deepEqual([input.selectionStart,input.selectionEnd,input.selectionDirection],[2,8,'backward']);assert.equal(input.value,raw);assert.equal(scope.value,'new_batch');assert.equal(reason.value,'选择案例不改范围');assert.equal(writes(e).length,0);assert.equal(starts(e).length,0);assert.equal(executes(e).length,0);
    await send(e.root);const p=JSON.parse(writes(e)[0].init.body).payload,s=JSON.parse(starts(e)[0].init.body).payload;assert.equal(p.prompt,raw);assert.equal(p.method_id,'product-poster');assert.equal(p.media_ids.length,15);assert.deepEqual(p.case_ref,caseFixture.case_ref);assert.deepEqual(s.model_ids,['video-model','image-model']);assert.equal(s.execution_settings.execution_policy.authorization.reason,'选择案例不改范围');
  }finally{e.panel.suspend();}
});

test('both case views and creative button reflect the single selected pin including replacement and chip removal',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();await openPicker(e);await pickerRows(e)[0].onclick();assert.equal(caseCards(e)[0].querySelector('.marketing-case-select').attributes['aria-pressed'],'true');assert.ok(caseCards(e)[0].className.includes('is-selected'));assert.equal(control(e.root,'创意').attributes['aria-pressed'],'true');
    await openPicker(e);assert.equal(pickerRows(e)[0].attributes['aria-pressed'],'true');await chooseCase(e,1);assert.equal(picker(e),null);assert.equal(caseCards(e)[0].querySelector('.marketing-case-select').attributes['aria-pressed'],'false');assert.equal(caseCards(e)[1].querySelector('.marketing-case-select').textContent,'已选');
    await openPicker(e);assert.equal(pickerRows(e)[1].attributes['aria-pressed'],'true');await control(e.root,'删除已选创意').onclick();assert.equal(pickerRows(e).some(n=>n.attributes['aria-pressed']==='true'),false);assert.equal(caseCards(e).some(n=>n.className.includes('is-selected')),false);assert.equal(control(e.root,'创意').attributes['aria-pressed'],'false');assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('compact filtering and paging never overwrite the large catalogue DOM, filter or next page',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const grid=cls(e.root,'marketing-case-grid');const popup=await openPicker(e),filter=popup.querySelectorAll('.marketing-case-category').find(n=>n.dataset.category==='视觉吸睛');await filter.onclick();assert.equal(caseCards(e).length,20);assert.equal(pickerRows(e).length,20);assert.equal(category(e,'').attributes['aria-pressed'],'true');
    await btn(popup,'加载更多创意').onclick();assert.equal(pickerRows(e).length,27);assert.equal(caseCards(e).length,20);await btn(e.root,'加载更多创意').onclick();assert.equal(caseCards(e).length,40);assert.equal(pickerRows(e).length,27);assert.equal(cls(e.root,'marketing-case-grid'),grid);
    const search=control(e.root,'搜索紧凑创意');search.value=' 不存在的创意-xh7 ';search.oninput();await new Promise(r=>setTimeout(r,340));await settle();assert.equal(control(e.root,'搜索营销创意').value,'');assert.equal(caseCards(e).length,40);assert.equal(pickerRows(e).length,0);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('compact and large infinite-scroll observers own different roots and closing compact cannot revive its old callback',async()=>{
  storage.clear();const o=scrollObservers(),e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const large=o.active();await openPicker(e);const compact=o.active();assert.notEqual(compact,large);assert.equal(compact.options.root,cls(e.root,'marketing-picker-results'));assert.equal(large.options.root,e.root);assert.notEqual(large.disconnected,true);const reads=caseLists(e).length;
    await control(e.root,'创意').onclick();assert.equal(compact.disconnected,true);compact.enter();assert.equal(caseLists(e).length,reads);assert.notEqual(large.disconnected,true);await large.enter();assert.equal(caseCards(e).length,40);assert.equal(picker(e),null);
  }finally{e.panel.suspend();o.restore();}
});

test('closing during compact search debounce preserves raw search and applies it once on reopening',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();await openPicker(e);const search=control(e.root,'搜索紧凑创意');search.value='  复古  ';search.oninput();await control(e.root,'创意').onclick();const before=caseLists(e).length;await new Promise(r=>setTimeout(r,340));assert.equal(caseLists(e).length,before);await openPicker(e);assert.equal(control(e.root,'搜索紧凑创意').value,'  复古  ');assert.equal(caseLists(e).length,before+1);const query=new URL(caseLists(e).at(-1).url,'http://test').searchParams;assert.equal(query.get('keyword'),'复古');assert.ok(pickerRows(e).length>0);assert.equal(caseCards(e).length,20);assert.equal(control(e.root,'搜索营销创意').value,'');assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('Escape and outside pointer close compact with the correct focus policy and stale handlers cannot close a reopened picker',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const input=control(e.root,'广告创作需求');prompt(e.root,'保留选择范围');input.setSelectionRange(1,4);await openPicker(e);const oldEscape=[...documentListeners.get('keydown')].at(-1);let prevented=false;document.fire('keydown',{key:'Escape',preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(picker(e),null);assert.equal(document.activeElement,input);assert.deepEqual([input.selectionStart,input.selectionEnd],[1,4]);
    const current=await openPicker(e);oldEscape({key:'Escape',preventDefault(){}});assert.equal(picker(e),current);const outside=control(e.root,'归属项目');outside.focus();document.fire('pointerdown',{target:outside});assert.equal(picker(e),null);assert.equal(document.activeElement,outside);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('closed picker list replies cannot resurrect or replace a freshly reopened view',async()=>{
  for(const result of ['success','error']){
    storage.clear();let resolve,reject,count=0;const wait=new Promise((a,b)=>{resolve=a;reject=b;}),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&++count===2?wait:undefined);
    try{
      await e.panel.load({project:'p'});await settle();await openPicker(e);assert.equal(pickerRows(e).length,0);await control(e.root,'创意').onclick();const current=await openPicker(e);assert.equal(pickerRows(e).length,20);if(result==='success')resolve({...caseFixture.pages[0],items:[]});else reject(Error('closed popup response'));await settle();assert.equal(picker(e),current);assert.equal(pickerRows(e).length,20);assert.doesNotMatch(picker(e).textContent,/closed popup response/);assert.equal(caseCards(e).length,20);assert.equal(writes(e).length,0);
    }finally{e.panel.suspend();}
  }
});

test('compact stale replies and rows are rejected after actor/project/locale changes or destruction',async()=>{
  for(const change of ['actor','project','locale','destroy']){
    storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});let resolve,count=0;const wait=new Promise(r=>resolve=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases?')&&++count===2?wait:undefined);
    try{
      await e.panel.load({project:'p'});await settle();await openPicker(e);if(change==='actor'){e.session.actor='other';await e.panel.load({project:'p'});}else if(change==='project')await e.panel.load({project:'q'});else if(change==='locale')setLocale('en',{persist:false});else e.panel.suspend();resolve(caseFixture.pages[0]);await settle();assert.equal(picker(e),null);assert.equal(cls(e.root,'marketing-case-chip').textContent,'');assert.equal(writes(e).length,0);
    }finally{e.panel.suspend();setLocale(locale,{persist:false});}
  }
});

test('unknown R/S locks compact opening and stale row selection while retaining the original pin and request',async()=>{
  for(const phase of ['prepare','start']){
    storage.clear();let fail=true;const e=environment(url=>fail&&(phase==='prepare'?url.endsWith('marketing-canvases'):url.endsWith('/start'))?Promise.reject(Error('lost receipt')):undefined);
    try{
      await e.panel.load({project:'p'});await settle();await chooseCase(e);prompt(e.root,'原固定需求');await openPicker(e);const stale=pickerRows(e)[1];await send(e.root);assert.equal(picker(e),null);const request=JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p'])));await stale.onclick();await control(e.root,'创意').onclick();assert.equal(picker(e),null);assert.equal(control(e.root,'创意').disabled,true);assert.deepEqual(JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p']))),request);fail=false;await send(e.root);assert.deepEqual(JSON.parse(writes(e)[0].init.body).payload.case_ref,caseFixture.case_ref);assert.equal(e.nav.at(-1)[3].agent_turn,'t');
    }finally{e.panel.suspend();}
  }
});

test('switching a synthetic large multi-example card selects its real template pin, and compact still chooses the first example',async()=>{
  storage.clear();const group=clone(caseFixture.pages[0].items[0]),second={...clone(caseFixture.second_case),group_key:group.group_key,group_name:group.group_name,video_name:'合成多例选择二'};group.examples.push(second);const e=environment(url=>url.startsWith('/api/v1/marketing-cases?')?{...caseFixture.pages[0],items:[group],total_available:1,next_page:null}:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const input=control(e.root,'广告创作需求');prompt(e.root,'多例不改正文');input.setSelectionRange(2,3);const select=control(e.root,'切换 '+group.group_name+' 的案例');select.value=second.template_key;await select.onchange({stopPropagation(){}});assert.equal(JSON.parse(storage.get('vsc-marketing:draft:'+JSON.stringify(['a','p']))).case.id,second.id);assert.equal(caseCards(e)[0].dataset.caseId,second.id);assert.equal(document.activeElement,input);
    await openPicker(e);assert.equal(pickerRows(e)[0].attributes['aria-pressed'],'true');await pickerRows(e)[0].onclick();const stored=JSON.parse(storage.get('vsc-marketing:draft:'+JSON.stringify(['a','p'])));assert.deepEqual({id:stored.case.id,version:stored.case.version,sha256:stored.case.sha256},caseFixture.case_ref);assert.equal(control(e.root,'切换 '+group.group_name+' 的案例').value,caseFixture.case.template_key);assert.equal(input.value,'多例不改正文');assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('detail choice stays disabled through GET and unrelated input updates, then selects only a verified H/spec',async()=>{
  storage.clear();let finish;const wait=new Promise(r=>finish=r),e=environment(url=>url.startsWith('/api/v1/marketing-cases/')?wait:undefined);
  try{
    await e.panel.load({project:'p'});await settle();const read=caseCards(e)[0].onclick(),choose=cls(e.root,'marketing-case-detail-select');assert.equal(choose.disabled,true);await choose.onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,'');prompt(e.root,'加载时继续保稿');assert.equal(choose.disabled,true);finish({...caseFixture.detail,case:caseFixture.case});await read;assert.equal(choose.disabled,false);await choose.onclick();assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.equal(document.activeElement,control(e.root,'广告创作需求'));assert.match(cls(e.root,'marketing-case-chip').textContent,new RegExp(caseFixture.case.group_name));assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('failed or mismatched detail remains unselectable, while historical fixed display stays readable without GET',async()=>{
  for(const failure of ['transport','H','spec']){
    storage.clear();const e=environment(url=>url.startsWith('/api/v1/marketing-cases/')?failure==='transport'?Promise.reject(Error('detail unavailable')):{...caseFixture.detail,catalog_sha256:failure==='H'?'f'.repeat(64):caseFixture.catalog_sha256,case:failure==='spec'?caseFixture.second_case:caseFixture.case}:undefined);
    try{
      await e.panel.load({project:'p'});await settle();await caseCards(e)[0].onclick();const choose=cls(e.root,'marketing-case-detail-select');assert.equal(choose.disabled,true);prompt(e.root,'失败仍保稿');await choose.onclick();assert.equal(cls(e.root,'marketing-case-chip').textContent,'');await control(e.root,'关闭创意详情').onclick();await chooseCase(e);const reads=caseDetails(e).length;await cls(e.root,'marketing-case-chip-open').onclick();assert.equal(caseDetails(e).length,reads);assert.equal(cls(e.root,'marketing-case-full-description').textContent,caseFixture.case.group_description);assert.equal(writes(e).length,0);
    }finally{e.panel.suspend();}
  }
});

test('preview activity is exclusive across large cards, compact rows and details and stops on close/hide',async()=>{
  storage.clear();const previous=globalThis.matchMedia;globalThis.matchMedia=q=>({matches:q.includes('hover')});const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const big=caseCards(e)[0].querySelector('video');await caseCards(e)[0].querySelector('.marketing-case-play').onclick();await openPicker(e);assert.ok(big.pauseCount>0);pickerRows(e)[0].onpointerenter({pointerType:'mouse'});const compact=cls(e.root,'marketing-picker-preview').querySelector('video');assert.equal(compact.playCount,1);await caseCards(e)[0].onclick();assert.equal(picker(e),null);assert.ok(compact.pauseCount>0);await control(e.root,'关闭创意详情').onclick();
    await openPicker(e);const row=pickerRows(e)[0];row.onpointerenter({pointerType:'mouse'});const active=cls(e.root,'marketing-picker-preview').querySelector('video');document.hidden=true;document.fire('visibilitychange');row.onpointerenter({pointerType:'mouse'});assert.equal(active.playCount,1);document.hidden=false;assert.ok(active.pauseCount>0);await control(e.root,'创意').onclick();assert.equal(cls(e.root,'marketing-picker-preview'),null);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();globalThis.matchMedia=previous;document.hidden=false;}
});

test('picker positioning clamps its anchored width into a narrow viewport without rebuilding the demand input',async()=>{
  storage.clear();const previousWidth=globalThis.innerWidth,previousHeight=globalThis.innerHeight;globalThis.innerWidth=390;globalThis.innerHeight=500;const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const input=control(e.root,'广告创作需求');control(e.root,'创意').rect={left:350,right:378,top:160,bottom:188,width:28,height:28};const popup=await openPicker(e);assert.ok(parseFloat(popup.style.width)<=390-24);assert.ok(parseFloat(popup.style.left)>=12);assert.ok(parseFloat(popup.style.left)+parseFloat(popup.style.width)<=390-12);assert.ok(parseFloat(popup.style.maxHeight)<=500*.7);assert.ok(parseFloat(popup.style.top)+parseFloat(popup.style.maxHeight)<=500-12);assert.equal(control(e.root,'广告创作需求'),input);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();globalThis.innerWidth=previousWidth;globalThis.innerHeight=previousHeight;}
});

const methodPicker=e=>cls(e.root,'marketing-method-picker');
const methodRows=e=>methodPicker(e)?.querySelectorAll('.marketing-method-option')||[];
const methodRow=(e,id)=>methodRows(e).find(n=>n.dataset.methodId===id);
const savedDraft=(actor='a',project='p')=>JSON.parse(storage.get('vsc-marketing:draft:'+JSON.stringify([actor,project])));
async function openMethods(e,origin='toolbar'){const opener=control(e.root,origin==='toolbar'?'技能':'全部技能');opener.focus();await opener.onclick();return methodPicker(e);}
function filterMethods(e,value){const search=control(e.root,'搜索技能');search.value=value;search.oninput();return search;}

test('skill toolbar and All share local query, keep the toolbar anchor and leave focus on the actual opener',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const calls=e.calls.length,toolbar=control(e.root,'技能'),all=control(e.root,'全部技能');toolbar.rect={left:180,right:210,top:160,bottom:190};all.rect={left:900,right:940,top:560,bottom:590};const popup=await openMethods(e);assert.equal(methodRows(e).length,8);assert.equal(document.activeElement,toolbar);assert.equal(popup.querySelector('header'),null);assert.equal(popup.querySelector('.marketing-case-count'),null);assert.equal(all.attributes['aria-pressed'],undefined);const left=popup.style.left,top=popup.style.top;
    filterMethods(e,' 海报 ');assert.deepEqual(methodRows(e).map(n=>n.dataset.methodId),['product-poster']);all.focus();await all.onclick();assert.equal(methodPicker(e),popup);assert.equal(popup.style.left,left);assert.equal(popup.style.top,top);assert.equal(control(e.root,'搜索技能').value,' 海报 ');control(e.root,'搜索技能').focus();document.fire('keydown',{key:'Escape',preventDefault(){}});assert.equal(methodPicker(e),null);assert.equal(document.activeElement,all);
    await openMethods(e);assert.equal(control(e.root,'搜索技能').value,' 海报 ');filterMethods(e,' no-such-skill-xh7 ');assert.equal(methodRows(e).length,0);assert.equal(cls(popup.parentElement||e.root,'marketing-method-empty')?.textContent,'没有匹配的技能');filterMethods(e,'');assert.equal(methodRows(e).length,8);filterMethods(e,'SHORT-DRAMA');assert.deepEqual(methodRows(e).map(n=>n.dataset.methodId),['short-drama-commerce']);filterMethods(e,' UGC ');await toolbar.onclick();await openMethods(e,'all');assert.equal(control(e.root,'搜索技能').value,' UGC ');assert.equal(methodRows(e).length,1);control(e.root,'搜索技能').focus();document.fire('keydown',{key:'Escape',preventDefault(){}});assert.equal(document.activeElement,all);assert.equal(e.calls.length,calls);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('directory same-selection retains the method, popular same-selection cancels, and an independent chip restores raw selection focus',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const input=control(e.root,'广告创作需求'),raw=' 原文😀\n不混入方法标签 ';prompt(e.root,raw);input.setSelectionRange(2,9,'backward');const popular=btn(e.root,'商品海报');popular.focus();await popular.onclick();assert.equal(document.activeElement,input);assert.equal(popular.attributes['aria-pressed'],'true');assert.equal(cls(e.root,'marketing-method-chip').textContent,'商品海报×');assert.equal(input.placeholder,'提示：product-poster');assert.equal(cls(e.root,'marketing-method-summary').textContent,'方法：product-poster');
    await openMethods(e,'all');assert.equal(savedDraft().method_id,'product-poster');assert.equal(methodRow(e,'product-poster').attributes['aria-pressed'],'true');await methodRow(e,'product-poster').onclick();assert.equal(methodPicker(e),null);assert.equal(savedDraft().method_id,'product-poster');assert.equal(input.value,raw);assert.equal(control(e.root,'广告创作需求'),input);assert.equal(document.activeElement,input);assert.deepEqual([input.selectionStart,input.selectionEnd,input.selectionDirection],[2,9,'backward']);
    popular.focus();await popular.onclick();assert.equal(savedDraft().method_id,'');assert.equal(document.activeElement,popular);assert.equal(cls(e.root,'marketing-method-chip').textContent,'');await btn(e.root,'短剧带货').onclick();assert.equal(savedDraft().method_id,'short-drama-commerce');await control(e.root,'删除已选技能').onclick();assert.equal(savedDraft().method_id,'');assert.equal(document.activeElement,input);assert.equal(input.value,raw);assert.deepEqual([input.selectionStart,input.selectionEnd],[2,9]);assert.equal(control(e.root,'技能').attributes['aria-pressed'],'false');assert.equal(writes(e).length,0);assert.equal(starts(e).length,0);assert.equal(executes(e).length,0);
    prompt(e.root,'');await openMethods(e);await methodRow(e,'product-poster').onclick();assert.equal(cls(e.root,'marketing-submit').disabled,true);await send(e.root);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('method directory selection keeps the case, fifteen materials, ordered models and original execution scope out of raw text',async()=>{
  storage.clear();const e=environment(url=>url.includes('/media?')?{items:Array.from({length:15},(_,i)=>({id:'method-media-'+i,name:'商品'+i,modality:'image'})),total:15}:undefined);
  try{
    await e.panel.load({project:'p'});await settle();await chooseCase(e);for(const card of e.root.querySelectorAll('.marketing-media-card'))await card.querySelector('button').onclick();for(const name of ['视频模型','图片模型']){const n=control(e.root,'优先模型 '+name);n.checked=true;n.onchange();}const episode=control(e.root,'归属剧集');episode.value='ep';episode.onchange();const mode=control(e.root,'创作模式');mode.value='auto_drafts';mode.onchange();const scope=control(e.root,translate(msg('ui.production_authorization_scope'))),reason=control(e.root,translate(msg('ui.reason_for_the_new_batch')));scope.value='new_batch';reason.value='方法目录保留原范围';const raw=' 商品原始事实\n请先规划 ';prompt(e.root,raw);const before=savedDraft();await openMethods(e);await methodRow(e,'product-poster').onclick();const after=savedDraft();assert.equal(after.prompt,raw);assert.deepEqual(after.case,before.case);assert.deepEqual(after.media,before.media);assert.deepEqual(after.model_ids,before.model_ids);assert.equal(after.episode_id,'ep');assert.equal(after.mode,'auto_drafts');assert.equal(scope.value,'new_batch');assert.equal(reason.value,'方法目录保留原范围');assert.equal(writes(e).length,0);
    await send(e.root);const p=JSON.parse(writes(e)[0].init.body).payload,start=JSON.parse(starts(e)[0].init.body).payload;assert.equal(p.prompt,raw);assert.deepEqual(p.case_ref,caseFixture.case_ref);assert.equal(p.method_id,'product-poster');assert.equal(p.method_version,'1.0');assert.equal(p.method_sha256,'sha-product-poster');assert.equal(p.media_ids.length,15);assert.deepEqual(start.model_ids,['video-model','image-model']);assert.equal(start.execution_settings.execution_policy.authorization.reason,'方法目录保留原范围');assert.equal('cover_url'in p,false);assert.equal('method_cover'in p,false);
  }finally{e.panel.suspend();}
});

test('method, case, model, material and detail views exclude each other without deleting any chosen input',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();await chooseCase(e);await btn(e.root,'商品海报').onclick();const before=savedDraft();await caseCards(e)[0].querySelector('.marketing-case-play').onclick();const video=caseCards(e)[0].querySelector('video');await openMethods(e);assert.ok(video.pauseCount>0);await openPicker(e);assert.equal(methodPicker(e),null);await openMethods(e);assert.equal(picker(e),null);await control(e.root,'选择模型').onclick();assert.equal(methodPicker(e),null);assert.equal(cls(e.root,'marketing-execution-panel').hidden,false);await openMethods(e);assert.equal(cls(e.root,'marketing-execution-panel').hidden,true);await control(e.root,'引用素材').onclick();assert.equal(methodPicker(e),null);assert.equal(cls(e.root,'marketing-material-panel').hidden,false);await openMethods(e);assert.equal(cls(e.root,'marketing-material-panel').hidden,true);await caseCards(e)[0].onclick();assert.equal(methodPicker(e),null);assert.ok(cls(e.root,'marketing-case-dialog'));await openMethods(e);assert.equal(cls(e.root,'marketing-case-dialog'),null);assert.equal(savedDraft().method_id,before.method_id);assert.deepEqual(savedDraft().case,before.case);assert.deepEqual(savedDraft().model_ids,before.model_ids);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();}
});

test('closed method menu unregisters all listeners and rejects old row, query, image, Escape and positioning callbacks after reopening',async()=>{
  storage.clear();const previousWindow=globalThis.window,listeners=new Map();globalThis.window={innerWidth:1000,innerHeight:700,addEventListener:(t,f)=>{if(!listeners.has(t))listeners.set(t,new Set());listeners.get(t).add(f);},removeEventListener:(t,f)=>listeners.get(t)?.delete(f)};const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const keys=documentListeners.get('keydown')?.size||0,pointers=documentListeners.get('pointerdown')?.size||0;await openMethods(e);const oldRow=methodRows(e)[0],oldImage=oldRow.querySelector('img'),oldQuery=control(e.root,'搜索技能'),oldEscape=[...documentListeners.get('keydown')].at(-1),oldPosition=[...listeners.get('resize')].at(-1);assert.equal(documentListeners.get('keydown').size,keys+1);assert.equal(listeners.get('resize').size,1);await control(e.root,'技能').onclick();assert.equal(documentListeners.get('keydown').size,keys);assert.equal(documentListeners.get('pointerdown').size,pointers);assert.equal(listeners.get('resize').size,0);assert.equal(e.root.listeners.scroll.length,0);const current=await openMethods(e,'all'),focus=document.activeElement;await oldRow.onclick();oldQuery.value='obsolete';oldQuery.oninput();oldImage.onerror();oldEscape({key:'Escape',preventDefault(){assert.fail('stale Escape');}});oldPosition();assert.equal(methodPicker(e),current);assert.equal(document.activeElement,focus);assert.equal(control(e.root,'搜索技能').value,'');assert.equal(oldImage.hidden,false);assert.equal(savedDraft().method_id,'');const outside=control(e.root,'归属项目');outside.focus();document.fire('pointerdown',{target:outside});assert.equal(methodPicker(e),null);assert.equal(document.activeElement,outside);assert.equal(documentListeners.get('keydown').size,keys);assert.equal(listeners.get('resize').size,0);
  }finally{e.panel.suspend();globalThis.window=previousWindow;}
});

test('method scope fences account, identity, actor, project, route, locale and destroyed instances without stealing focus',async()=>{
  for(const change of ['account','identity','actor','project','route','locale','destroy']){
    storage.clear();const locale=getLocale(),route=globalThis.location.search;setLocale('zh-cn',{persist:false});const e=environment();
    try{
      await e.panel.load({project:'p'});await settle();await openMethods(e);const row=methodRows(e)[0],image=row.querySelector('img'),escape=[...documentListeners.get('keydown')].at(-1),position=e.root.listeners.scroll.at(-1),search=control(e.root,'搜索技能'),all=control(e.root,'全部技能'),popular=btn(e.root,'短剧带货');
      if(change==='account')e.session.account_id='other';else if(change==='identity')e.session.identityId='other';else if(change==='actor')e.session.actor='other';else if(change==='project')await e.panel.load({project:'q'});else if(change==='route')globalThis.location.search='?route=elsewhere';else if(change==='locale')setLocale('en',{persist:false});else e.panel.suspend();await (change==='account'?all:change==='identity'?popular:row).onclick();assert.equal(methodPicker(e),null);position();if(change!=='destroy')await e.panel.load({project:change==='project'?'q':'p'});else await e.panel.load({project:'p'});await settle();const current=await openMethods(e,'all'),focus=document.activeElement;await row.onclick();image.onerror();search.value='stale';search.oninput();escape({key:'Escape',preventDefault(){assert.fail('old scope Escape');}});position();assert.equal(methodPicker(e),current);assert.equal(document.activeElement,focus);assert.equal(image.hidden,false);assert.equal(control(e.root,'搜索技能').value,'');assert.equal(cls(e.root,'marketing-method-chip').textContent,'');assert.equal(writes(e).length,0);
    }finally{e.panel.suspend();globalThis.location.search=route;setLocale(locale,{persist:false});}
  }
});

test('hidden keeps a valid method menu and query while locale closes its old DOM and retains the page query',async()=>{
  storage.clear();const locale=getLocale();setLocale('zh-cn',{persist:false});const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const current=await openMethods(e);filterMethods(e,' 海报 ');document.hidden=true;document.fire('visibilitychange');assert.equal(methodPicker(e),current);assert.equal(control(e.root,'搜索技能').value,' 海报 ');document.hidden=false;document.fire('visibilitychange');assert.equal(methodPicker(e),current);setLocale('en',{persist:false});assert.equal(methodPicker(e),null);await openMethods(e,'all');assert.equal(control(e.root,'搜索技能').value,' 海报 ');assert.equal(methodRows(e).length,1);await methodRow(e,'product-poster').onclick();assert.equal(savedDraft().method_id,'product-poster');assert.equal(document.activeElement,control(e.root,'广告创作需求'));assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();document.hidden=false;setLocale(locale,{persist:false});}
});

test('a busy prepare closes and locks method UI before any stale selection can change the fixed request',async()=>{
  storage.clear();let finish;const wait=new Promise(r=>finish=r),e=environment(url=>url.endsWith('marketing-canvases')?wait:undefined);
  try{
    await e.panel.load({project:'p'});await settle();await btn(e.root,'商品海报').onclick();prompt(e.root,'正在准备也不能改方法');await openMethods(e);const stale=methodRow(e,'commercial-tvc'),remove=control(e.root,'删除已选技能'),start=send(e.root);await tick();assert.equal(methodPicker(e),null);assert.equal(control(e.root,'技能').disabled,true);assert.equal(control(e.root,'全部技能').disabled,true);await stale.onclick();await remove.onclick();await btn(e.root,'短剧带货').onclick();await control(e.root,'全部技能').onclick();assert.equal(methodPicker(e),null);assert.equal(savedDraft().method_id,'product-poster');assert.equal(JSON.parse(writes(e)[0].init.body).payload.method_id,'product-poster');finish(prepared());await start;assert.equal(e.nav.at(-1)[3].agent_turn,'t');
  }finally{e.panel.suspend();}
});

test('unknown R or S preserves the exact method pin and denies menu or stale chip changes until the same operation recovers',async()=>{
  for(const phase of ['prepare','start']){
    storage.clear();let fail=true;const e=environment(url=>fail&&(phase==='prepare'?url.endsWith('marketing-canvases'):url.endsWith('/start'))?Promise.reject(Error('lost method receipt')):undefined);
    try{
      await e.panel.load({project:'p'});await settle();await openMethods(e);await methodRow(e,'product-poster').onclick();prompt(e.root,'固定原方法');const remove=control(e.root,'删除已选技能');await openMethods(e);const stale=methodRow(e,'commercial-tvc');await send(e.root);const request=JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p']))),body=writes(e)[0].init.body;await stale.onclick();await remove.onclick();await control(e.root,'技能').onclick();await control(e.root,'全部技能').onclick();assert.equal(methodPicker(e),null);assert.deepEqual(JSON.parse(storage.get('vsc-marketing:request:'+JSON.stringify(['a','p']))),request);assert.equal(request.request.payload.method_version,'1.0');assert.equal(request.request.payload.method_sha256,'sha-product-poster');fail=false;await send(e.root);assert.equal(writes(e).at(-1).init.body,body);assert.equal(e.nav.at(-1)[3].agent_turn,'t');
    }finally{e.panel.suspend();}
  }
});

test('lost execution keeps the original T and method while subsequent recovery only reads the same running turn',async()=>{
  storage.clear();let executeAttempted=false;const e=environment(url=>{if(url.endsWith('/creative-canvas-agent-turns/t/execute')){executeAttempted=true;throw Error('execute response lost');}if(executeAttempted&&url.endsWith('/creative-canvas-agent-turns/t'))return turn('running');});
  try{
    await e.panel.load({project:'p'});await settle();await btn(e.root,'商品海报').onclick();prompt(e.root,'继续原T');await send(e.root);assert.equal(executes(e).length,1);await control(e.root,'技能').onclick();await btn(e.root,'短剧带货').onclick();await send(e.root);assert.equal(methodPicker(e),null);assert.equal(savedDraft().method_id,'product-poster');assert.equal(writes(e).length,1);assert.equal(starts(e).length,1);assert.equal(executes(e).length,1);assert.equal(e.nav.at(-1)[3].agent_turn,'t');
  }finally{e.panel.suspend();}
});

test('all eight skill covers use local files with failed-image fallbacks and never enter creation inputs',async()=>{
  storage.clear();const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const popular=e.root.querySelectorAll('.marketing-method');assert.equal(popular.length,8);assert.equal(popular.filter(n=>n.querySelector('img')).length,8);for(const n of popular){assert.equal(n.attributes['aria-label'],methods.find(m=>m.id===n.dataset.methodId).name);assert.equal(n.textContent,n.attributes['aria-label']);}assert.equal(btn(e.root,'商品海报').querySelector('img').src,'/api/v1/marketing-assets/methods/product-poster');const publicImage=popular[0].querySelector('img');assert.equal(publicImage.src,'/api/v1/marketing-assets/methods/short-drama-commerce');publicImage.onerror();assert.equal(publicImage.hidden,true);await openMethods(e);assert.equal(methodRows(e).filter(n=>n.querySelector('img')).length,8);assert.ok(methodRow(e,'product-poster').querySelector('img'));for(const row of methodRows(e)){const original=popular.find(n=>n.dataset.methodId===row.dataset.methodId)?.querySelector('img');if(original)assert.equal(row.querySelector('img').src,original.src);}const row=methodRows(e)[0],image=row.querySelector('img');image.onerror();assert.equal(image.hidden,true);assert.ok(row.querySelector('.marketing-method-thumb').className.includes('is-fallback'));await row.onclick();assert.equal(savedDraft().method_id,'short-drama-commerce');prompt(e.root,'只用原商品输入');await send(e.root);const payload=JSON.parse(writes(e)[0].init.body).payload;assert.deepEqual(payload.media_ids,[]);assert.equal(payload.prompt,'只用原商品输入');assert.equal(Object.keys(payload).some(k=>/cover|thumb|image/.test(k)),false);
  }finally{e.panel.suspend();}
});

test('method anchor stays on the toolbar at 390px and uses measured natural menu height after filtering',async()=>{
  storage.clear();const previousWidth=globalThis.innerWidth,previousHeight=globalThis.innerHeight;globalThis.innerWidth=390;globalThis.innerHeight=500;const e=environment();
  try{
    await e.panel.load({project:'p'});await settle();const toolbar=control(e.root,'技能'),all=control(e.root,'全部技能');toolbar.rect={left:350,right:378,top:430,bottom:458};all.rect={left:20,right:80,top:80,bottom:110};const popup=await openMethods(e,'all');assert.ok(parseFloat(popup.style.width)<=366);assert.ok(parseFloat(popup.style.left)>=12);assert.ok(parseFloat(popup.style.left)+parseFloat(popup.style.width)<=378);assert.ok(parseFloat(popup.style.top)+Math.min(popup.offsetHeight,parseFloat(popup.style.maxHeight))<=488);assert.equal(popup.style.height,undefined);filterMethods(e,'海报');popup.offsetHeight=108;await e.root.fire('scroll');assert.equal(methodRows(e).length,1);assert.ok(parseFloat(popup.style.top)>=toolbar.rect.top-108-8);assert.equal(document.activeElement,all);assert.equal(writes(e).length,0);
  }finally{e.panel.suspend();globalThis.innerWidth=previousWidth;globalThis.innerHeight=previousHeight;}
});
