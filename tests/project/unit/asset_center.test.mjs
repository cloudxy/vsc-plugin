import assert from 'node:assert/strict';
import {test} from 'node:test';

// This deliberately small DOM tests the component and request boundaries, not
// browser layout or the real authenticated API.
class Element {
  constructor(tag, doc) {
    this.tagName=tag.toUpperCase(); this.ownerDocument=doc; this.children=[];
    this.parentElement=null; this.attributes={}; this.dataset={}; this.className='';
    this.isConnected=true; this.classList={add(){}};
  }
  append(...nodes) {
    for (const node of nodes) if (node instanceof Element) {
      if (node.parentElement) node.parentElement.children=node.parentElement.children.filter(n=>n!==node);
      node.parentElement=this; this.children.push(node);
    }
  }
  replaceChildren(...nodes) { for (const n of this.children) n.parentElement=null; this.children=[]; this.append(...nodes); }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  querySelectorAll(selector) {
    return this.walk().filter(n=>selector==='dialog' ? n.tagName==='DIALOG' :
      selector.startsWith('.') && n.className.split(' ').includes(selector.slice(1)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
  walk() { return this.children.flatMap(n=>[n,...n.walk()]); }
  addEventListener() {} close() {} showModal() {} remove() { this.isConnected=false; }
  get options() { return this.children; }
  get textContent() { return this._text??this.children.map(n=>n.textContent).join(''); }
  set textContent(value) { this._text=String(value); }
}
const document={documentElement:{},createElement(tag){return new Element(tag,this);},
  createTextNode(text){const n=new Element('#text',this);n.textContent=text;return n;},querySelector(){return null;}};
document.head=new Element('head',document);
globalThis.document=document;
globalThis.location={search:'',href:''};
globalThis.history={pushState(_a,_b,url){location.search=url;},replaceState(_a,_b,url){location.search=url;}};
globalThis.sessionStorage={getItem(){return null;},setItem(){},removeItem(){}};
const {createAssetCenter}=await import('../../../src/vsc/interfaces/web/static/asset-center.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle() { for(let i=0;i<15;i++) await tick(); }
const asset=i=>({id:'id'+i,name:'资产'+i,asset_kind:'character',forms:[]});
const context=(projects,api)=>({session:()=>({actor:'tester'}),projects:()=>projects,notice(){},api});
const button=(root,name)=>root.walk().find(n=>n.tagName==='BUTTON'&&n.textContent===name);
const cards=root=>root.querySelectorAll('.global-asset-card');

// A slow project never blocks the first page of a fast project.  Scrolling
// through bounded views must still expose every page and preserve failures.
test('progressively loads all pages with bounded concurrency and retry',async()=>{
  location.search='?page=asset-center';
  let releaseSlow,active=0,maxActive=0,failed=true; const requests=[];
  const slow=new Promise(resolve=>{releaseSlow=resolve;});
  const api=async url=>{
    active++; maxActive=Math.max(maxActive,active); requests.push(url);
    try {
      await tick();
      if(url.includes('/slow/')) {await slow;return {items:[asset(101)],next_offset:null,revision:2};}
      if(url.includes('/bad/')) {if(failed)throw Error('读取失败');return {items:[],next_offset:null,revision:3};}
      const offset=Number(new URL(url,'http://test').searchParams.get('offset'));
      return {items:Array.from({length:Math.min(24,101-offset)},(_,i)=>asset(offset+i)),
        next_offset:offset+24<101?offset+24:null,revision:1};
    } finally {active--;}
  };
  const root=new Element('main',document),panel=createAssetCenter(root,context([
    {id:'fast',name:'快项目'},{id:'slow',name:'慢项目'},{id:'bad',name:'失败项目'}],api));
  await panel.load(); await settle();
  assert.equal(cards(root).length,48);
  assert.match(root.querySelector('.global-asset-count').textContent,/正在加载/);
  assert.ok(requests.some(url=>url.includes('offset=24')));
  assert.match(root.querySelector('.global-asset-failures').textContent,/失败项目/);
  assert.equal(maxActive,3);
  const seen=new Set(),collect=()=>{
    assert.ok(cards(root).length<=72);
    for(const card of cards(root)) seen.add(card.walk().find(n=>n.tagName==='H3').textContent);
  };
  collect(); assert.ok(button(root,'继续浏览')); await button(root,'继续浏览').onclick();
  releaseSlow(); await settle(); collect();
  while(button(root,'继续浏览')) {await button(root,'继续浏览').onclick();await settle();collect();}
  failed=false; assert.ok(button(root,'重试失败项目')); await button(root,'重试失败项目').onclick(); await settle();
  while(button(root,'继续浏览')) {collect();await button(root,'继续浏览').onclick();await settle();collect();}
  assert.equal(seen.size,102);
  assert.match(root.querySelector('.global-asset-count').textContent,/共102个资产/);
  assert.ok(maxActive<=3); panel.suspend();
});

test('suspending aborts reads and ignores a late response even if abort is ignored',async()=>{
  location.search='?page=asset-center'; let finish,signal;
  const pending=new Promise(resolve=>{finish=resolve;});
  const root=new Element('main',document),panel=createAssetCenter(root,context([{id:'old',name:'旧项目'}],
    (_url,options)=>{signal=options.signal;return pending;}));
  await panel.load(); await tick(); panel.suspend(); assert.equal(signal.aborted,true);
  finish({items:[asset(999)],next_offset:null,revision:1}); await settle();
  assert.equal(cards(root).length,0);
});

test('official and shared tabs query their own sources and restore from the URL',async()=>{
  const row={id:'official-1',version_id:'v1',title:'官方角色',source:'official',
    official:{asset_kind:'character',role_level:'lead',role_tag:'医生',gender:'female',age_band:'young_adult'},
    catalog:{asset_kind:'character',tags:[],form_name:''},members:[{modality:'image',preview_url:'/fixture.png',member_key:'front'}],
    allowed_purposes:['identity_face']};
  const calls=[],api=async url=>{
    calls.push(url);
    if(url.startsWith('/api/v1/asset-center?'))return url.includes('source=official') ?
      {items:[row],total:1,facets:{role_tag:['医生']},next_offset:null} : {items:[],total:0,next_offset:null};
    throw Error('unexpected '+url);
  };
  location.search='?page=asset-center&tab=official';
  const root=new Element('main',document),panel=createAssetCenter(root,context([],api));await panel.load();
  assert.ok(root.querySelector('.center-workbench-official'));
  assert.ok(root.querySelector('.center-official-kinds'));
  assert.match(root.querySelector('.center-official-tags').textContent,/主角医生女青年/);
  assert.ok(root.querySelector('.center-cover').querySelector('.center-actions'));
  assert.ok(calls.some(url=>url.includes('source=official')));
  await button(root,'场景').onclick();
  assert.ok(calls.some(url=>url.includes('source=official')&&url.includes('asset_kind=location')));
  await button(root,'项目资产').onclick();assert.equal(location.search,'?page=asset-center');
  assert.ok(root.querySelector('.global-asset-grid'));
  await button(root,'官方资产NEW').onclick();assert.match(location.search,/tab=official/);
  const shared=root.walk().find(n=>n.tagName==='A'&&n.textContent==='公共素材库');
  shared.onclick({preventDefault(){},metaKey:false,ctrlKey:false,shiftKey:false,altKey:false});await settle();
  assert.match(location.search,/tab=shared/);assert.ok(root.querySelector('.center-empty'));
  assert.ok(calls.some(url=>url.startsWith('/api/v1/asset-center?')&&!url.includes('source=official')));
  // Simulate the route supplied on refresh or by the host's popstate handler.
  location.search='?page=asset-center&tab=official';await panel.load();assert.ok(root.querySelector('.center-workbench-official'));
  location.search='?page=asset-center';await panel.load();assert.ok(root.querySelector('.global-asset-grid'));
  panel.suspend();
});
