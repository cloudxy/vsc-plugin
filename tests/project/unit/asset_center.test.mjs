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
  prepend(...nodes) { for (const node of nodes.reverse()) { node.parentElement=this; this.children.unshift(node); } }
  replaceChildren(...nodes) { for (const n of this.children) n.parentElement=null; this.children=[]; this.append(...nodes); }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  getAttribute(k) { return this.attributes[k]??null; }
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
const {legacyPreviewForm,applyLegacySuggestion,mountAssetCards}=await import('../../../src/vsc/interfaces/web/static/asset-cards.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle() { for(let i=0;i<15;i++) await tick(); }
const asset=i=>({id:'id'+i,name:'资产'+i,asset_kind:'character',forms:[]});
const context=(projects,api)=>({session:()=>({actor:'tester'}),projects:()=>projects,notice(){},api});
const button=(root,name)=>root.walk().find(n=>n.tagName==='BUTTON'&&n.textContent===name);
const cards=root=>root.querySelectorAll('.global-asset-card');

test('legacy reference suggestion is scoped to an unambiguous form and preserves retained drafts',()=>{
  const forms=[{form_key:'one',spec_id:'s1',media_id:null},{form_key:'two',spec_id:'s2',media_id:null}];
  const card={forms,preview:{variant_spec_id:'s2',media_id:'selected'}};
  assert.equal(legacyPreviewForm(card).form_key,'two');
  assert.equal(legacyPreviewForm({...card,preview:{variant_spec_id:null}}),null);
  assert.equal(legacyPreviewForm({forms:[forms[0]],preview:{variant_spec_id:null}}).form_key,'one');
  const draft={forms:forms.map(f=>({...f}))};
  assert.equal(applyLegacySuggestion(draft,true,{form_key:'two',media_id:'selected'}),false);
  assert.equal(draft.forms[1].media_id,null);
  assert.equal(applyLegacySuggestion(draft,false,{form_key:'two',media_id:'selected'}),true);
  assert.equal(draft.forms[1].media_id,'selected');assert.equal(forms[1].media_id,null);
});

test('project cards show a selected-reference preview without altering forms',async()=>{
  location.search='?page=asset-center';const legacy={id:'old',name:'旧道具',asset_kind:'object',forms:[{media_id:null}],preview:{media_id:'selected',source:'current_binding'}};
  const working={id:'new',name:'当前形态',asset_kind:'character',forms:[{media_id:'form'}],preview:{media_id:'older',source:'current_binding'}};
  const root=new Element('main',document),panel=createAssetCenter(root,context([{id:'p',name:'项目'}],async()=>({items:[legacy,working],next_offset:null,revision:1})));
  await panel.load();await settle();const result=cards(root);assert.equal(result.length,2);const image=card=>card.walk().find(n=>n.tagName==='IMG');
  assert.equal(image(result[0]).src,'/api/v1/projects/p/media/selected/content');assert.equal(image(result[0]).title,'已选参考图，仅用于预览');assert.equal(result[0].querySelector('.global-asset-badge').textContent,'道具');assert.equal(legacy.forms[0].media_id,null);
  assert.equal(image(result[1]).src,'/api/v1/projects/p/media/form/content');panel.suspend();
});

test('prop category asks for both current props and legacy objects',async()=>{
  location.search='?page=asset-center';const calls=[];
  const rows=[{id:'p1',name:'道具',asset_kind:'prop',forms:[]},{id:'p2',name:'旧物件',asset_kind:'object',forms:[]},{id:'p3',name:'人物',asset_kind:'character',forms:[]}];
  const api=async url=>{calls.push(url);const params=new URL(url,'http://test').searchParams,kind=params.get('asset_kind');return {items:rows.filter(r=>!kind||r.asset_kind===kind||kind==='prop'&&params.get('include_object')==='true'&&r.asset_kind==='object'),next_offset:null,revision:1};};
  const root=new Element('main',document),panel=createAssetCenter(root,context([{id:'project',name:'项目'}],api));await panel.load();await settle();
  await button(root,'道具').onclick();await settle();assert.equal(cards(root).length,2);const params=new URL(calls.at(-1),'http://test').searchParams;assert.equal(params.get('asset_kind'),'prop');assert.equal(params.get('include_object'),'true');
  await button(root,'人设').onclick();await settle();assert.equal(cards(root).length,1);assert.equal(new URL(calls.at(-1),'http://test').searchParams.has('include_object'),false);panel.suspend();
});

test('blocking pictures are filterable and previewed without asset identity actions',async()=>{
  location.search='?page=asset-center';const calls=[];
  const blocking={id:'projection',record_kind:'blocking',asset_kind:'blocking',name:'第一集站位',forms:[],preview:{media_id:'fixed-media'}};
  const api=async url=>{calls.push(url);const q=new URL(url,'http://test').searchParams;return {items:q.get('asset_kind')&&q.get('asset_kind')!=='blocking'?[]:[blocking,{...blocking,id:'restricted',name:'不可用站位',preview:null}],next_offset:null,revision:1};};
  const root=new Element('main',document),panel=createAssetCenter(root,context([{id:'project',name:'项目'}],api));await panel.load();await settle();
  await button(root,'站位').onclick();await settle();const q=new URL(calls.at(-1),'http://test').searchParams;assert.equal(q.get('include_blocking'),'true');assert.equal(q.get('asset_kind'),'blocking');
  const card=cards(root)[0];assert.equal(card.querySelector('.global-asset-badge').textContent,'站位');assert.equal(card.querySelector('.global-asset-actions'),null);
  assert.equal(card.walk().find(n=>n.tagName==='IMG').src,'/api/v1/projects/project/media/fixed-media/content');
  await card.querySelector('.global-asset-preview').onclick();assert.equal(root.querySelectorAll('dialog').length,1);await cards(root)[1].querySelector('.global-asset-preview').onclick();assert.match(root.querySelectorAll('dialog')[1].textContent,/素材当前不可预览/);assert.equal(calls.length,2);panel.suspend();
});

test('project batch operations never treat a blocking projection as an asset identity',async()=>{
  const station={id:'blocking:key',record_kind:'blocking',asset_kind:'blocking',name:'站位',forms:[],preview:{media_id:'fixed'}};
  const ordinary={...asset(1),record_kind:'asset'};const calls=[];
  const ctx={...context([{id:'project',name:'项目'}],async url=>{calls.push(url);if(url.endsWith('/asset-card-options'))return {nodes:[],media:[],revision:1};return {items:[station,ordinary],total:2,next_offset:null,revision:1};}),setRevision(){}};
  const root=new Element('main',document),panel=await mountAssetCards(root,ctx,{projectId:'project'});assert.equal(root.querySelectorAll('.asset-card').length,2);
  assert.equal(root.querySelectorAll('.asset-card-menu').length,1);await button(root,'批量操作').onclick();assert.equal(root.querySelectorAll('.asset-card-check').length,1);
  assert.equal(new URL(calls.at(-1),'http://test').searchParams.get('include_blocking'),'true');panel.suspend();
});

// All-projects mode issues a single cross-project query (/api/v1/account/project-asset-cards)
// instead of per-project N+1 fanout, while explicit single-project selection keeps /projects/{id}/asset-cards.
test('all-projects mode loads 30 authorized projects in a single request with cursor pagination and retry',async()=>{
  location.search='?page=asset-center&owner_kind=workspace&workspace_id=ws-1&favorites=true';
  const thirtyProjects=Array.from({length:30},(_,i)=>({id:`proj-${i}`,name:`短剧项目${i}`}));
  let failNext=false;const requests=[];
  const api=async url=>{
    requests.push(url);
    await tick();
    if(url.includes('/projects/'))throw new Error('unexpected per-project fanout '+url);
    if(failNext)throw new Error('网络抖动读取失败');
    const u=new URL(url,'http://test'),q=u.searchParams;
    assert.equal(u.pathname,'/api/v1/account/project-asset-cards');
    assert.equal(q.get('owner_kind'),'workspace');
    assert.equal(q.get('workspace_id'),'ws-1');
    assert.equal(q.get('favorites'),'true');
    assert.equal(q.get('limit'),'24');
    const cursor=q.get('cursor');
    if(!cursor){
      return {items:Array.from({length:24},(_,i)=>({...asset(i),project_id:`proj-${i}`,project_name:`短剧项目${i}`,project_revision:1})),
        total:30,next_offset:24,next_cursor:'cursor-page-2',authorized_project_count:30};
    }
    assert.equal(cursor,'cursor-page-2');
    return {items:Array.from({length:6},(_,i)=>({...asset(24+i),project_id:`proj-${24+i}`,project_name:`短剧项目${24+i}`,project_revision:1})),
      total:30,next_offset:null,next_cursor:null,authorized_project_count:30};
  };
  const root=new Element('main',document),panel=createAssetCenter(root,context(thirtyProjects,api));
  await panel.load(); await settle();
  assert.equal(requests.length,1);
  assert.equal(cards(root).length,24);
  assert.equal(root.querySelector('.global-asset-count').textContent,'已加载24个资产');
  assert.equal(root.querySelector('.global-asset-grid').getAttribute('aria-busy'),'false');
  assert.ok(button(root,'继续浏览'));
  failNext=true;
  await button(root,'继续浏览').onclick(); await settle();
  assert.match(root.querySelector('.global-asset-failures').textContent,/网络抖动读取失败/);
  failNext=false;
  await button(root,'重试失败项目').onclick(); await settle();
  assert.equal(cards(root).length,30);
  assert.equal(root.querySelector('.global-asset-count').textContent,'共30个资产');
  assert.equal(requests.some(u=>u.includes('/projects/')),false);
  panel.suspend();
});

test('single-project selection keeps /api/v1/projects/{id}/asset-cards pagination and retry',async()=>{
  location.search='?page=asset-center';
  const requests=[];let failProject=false;
  const api=async url=>{
    requests.push(url);
    await tick();
    if(url.startsWith('/api/v1/account/project-asset-cards?')){
      return {items:[{...asset(1),project_id:'fast',project_name:'快项目'}],total:1,next_offset:null,next_cursor:null,authorized_project_count:2};
    }
    if(failProject)throw new Error('单项目读取失败');
    const offset=Number(new URL(url,'http://test').searchParams.get('offset'));
    return {items:Array.from({length:Math.min(24,30-offset)},(_,i)=>asset(offset+i)),
      next_offset:offset+24<30?offset+24:null,revision:1};
  };
  const root=new Element('main',document),panel=createAssetCenter(root,context([
    {id:'fast',name:'快项目'},{id:'other',name:'另一项目'}],api));
  await panel.load(); await settle();
  const select=root.querySelector('.global-asset-toolbar').walk().find(n=>n.tagName==='SELECT');
  failProject=true;
  select.value='fast'; await select.onchange(); await settle();
  assert.ok(requests.at(-1).startsWith('/api/v1/projects/fast/asset-cards?'));
  assert.match(root.querySelector('.global-asset-failures').textContent,/单项目读取失败/);
  failProject=false;
  await button(root,'重试失败项目').onclick(); await settle();
  assert.equal(cards(root).length,30);
  assert.equal(root.querySelector('.global-asset-count').textContent,'共30个资产');
  panel.suspend();
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

test('category transitions retain the toolbar and search draft while ignoring late results and errors',async()=>{
  location.search='?page=asset-center';const reads=[];
  const api=(url,{signal}={})=>{
    const q=new URL(url,'http://test').searchParams;
    if(!q.get('asset_kind'))return Promise.resolve({items:[asset('initial')],next_offset:null,revision:1});
    return new Promise((resolve,reject)=>reads.push({kind:q.get('asset_kind'),query:q.get('query'),signal,resolve,reject}));
  };
  const root=new Element('main',document),panel=createAssetCenter(root,context([{id:'p',name:'项目'}],api));await panel.load();await settle();
  const toolbar=root.querySelector('.global-asset-toolbar'),count=root.querySelector('.global-asset-count'),search=toolbar.walk().find(n=>n.tagName==='INPUT'),batch=button(root,'批量操作'),grid=root.querySelector('.global-asset-grid');
  search.value='茶馆草稿';search.selectionStart=1;search.selectionEnd=3;document.activeElement=search;
  await button(root,'人设').onclick();await settle();
  assert.equal(root.querySelector('.global-asset-toolbar'),toolbar);assert.equal(root.querySelector('.global-asset-count'),count);assert.equal(button(root,'批量操作'),batch);
  assert.equal(toolbar.walk().find(n=>n.tagName==='INPUT'),search);assert.equal(search.value,'茶馆草稿');assert.equal(search.selectionStart,1);assert.equal(document.activeElement,search);
  assert.equal(count.textContent,'资产数待读取');assert.equal(cards(root).length,0);assert.equal(root.querySelector('.global-asset-status').textContent,'');
  assert.equal(button(root,'人设').getAttribute('aria-pressed'),'true');assert.notEqual(button(root,'人设').disabled,true);assert.equal(reads[0].query,'茶馆草稿');
  await new Promise(resolve=>setTimeout(resolve,170));assert.match(root.querySelector('.global-asset-status').textContent,/正在读取人设资产/);
  await button(root,'场景').onclick();await settle();assert.equal(reads[0].signal.aborted,true);assert.equal(count.textContent,'资产数待读取');
  reads[1].resolve({items:[{...asset('scene'),asset_kind:'location'}],next_offset:null,revision:1});await settle();
  assert.equal(count.textContent,'共1个资产');assert.equal(grid.getAttribute('aria-busy'),'false');assert.equal(root.querySelector('.global-asset-status').textContent,'');
  reads[0].reject(Error('late old-category error'));await settle();assert.equal(cards(root).length,1);assert.match(cards(root)[0].textContent,/资产scene/);assert.equal(root.querySelector('.global-asset-failures').hidden,true);
  const before=reads.length;await button(root,'场景').onclick();await settle();assert.equal(reads.length,before);
  await button(root,'道具').onclick();await settle();reads[2].reject(Error('HTTP 403 permission denied'));await settle();
  assert.equal(count.textContent,'已加载0个资产');assert.equal(root.querySelector('.global-asset-empty'),null);assert.match(root.querySelector('.global-asset-failures').textContent,/HTTP 403/);assert.match(root.querySelector('.global-asset-status').textContent,/读取失败/);
  await button(root,'重试失败项目').onclick();await settle();reads[3].resolve({items:[],next_offset:null,revision:1});await settle();
  assert.equal(count.textContent,'共0个资产');assert.match(root.querySelector('.global-asset-empty').textContent,/没有匹配的资产/);assert.equal(search.value,'茶馆草稿');
  panel.suspend();
});

test('a retained toolbar never carries another actor’s content or search draft into a new session',async()=>{
  location.search='?page=asset-center';let actor='first',finish;
  const ctx=context([{id:'p',name:'项目'}],()=>actor==='first'?Promise.resolve({items:[asset('private')],next_offset:null,revision:1}):new Promise(resolve=>{finish=resolve;}));
  ctx.session=()=>({actor});const root=new Element('main',document),panel=createAssetCenter(root,ctx);await panel.load();await settle();
  const toolbar=root.querySelector('.global-asset-toolbar'),search=toolbar.walk().find(n=>n.tagName==='INPUT');search.value='private draft';
  actor='second';await panel.load();await settle();assert.notEqual(root.querySelector('.global-asset-toolbar'),toolbar);assert.equal(cards(root).length,0);assert.equal(root.querySelector('.global-asset-toolbar').walk().find(n=>n.tagName==='INPUT').value,'');
  actor=null;await panel.load();finish({items:[asset('late-second')],next_offset:null,revision:1});await settle();
  assert.match(root.textContent,/请先建立操作会话/);assert.equal(root.querySelector('.global-asset-toolbar'),null);assert.equal(cards(root).length,0);panel.suspend();
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
    if(url.startsWith('/api/v1/account/project-asset-cards?'))return {items:[],total:0,next_offset:null,next_cursor:null,authorized_project_count:0};
    throw Error('unexpected '+url);
  };
  location.search='?page=asset-center&tab=official';
  const root=new Element('main',document),panel=createAssetCenter(root,context([],api));await panel.load();
  assert.ok(root.querySelector('.center-workbench-official'));
  assert.deepEqual(root.querySelector('.center-official-kinds').walk().filter(n=>n.tagName==='BUTTON').map(n=>n.textContent),['人设','场景','道具','音频']);
  assert.equal(root.querySelector('.ref-page-title'),null);
  const filterRow=root.querySelector('.center-official-filter-row');
  assert.ok(filterRow);
  const filterChildren=root.querySelector('.center-official-filters').children.filter(n=>n.tagName!=='#TEXT');
  assert.equal(filterChildren[0],root.querySelector('.center-official-kinds'));
  assert.equal(filterChildren[1],filterRow);
  assert.ok(filterRow.querySelector('.center-count'));
  assert.ok(filterRow.walk().some(n=>n.tagName==='INPUT'));
  assert.deepEqual(filterRow.walk().filter(n=>n.tagName==='SELECT').map(n=>n.getAttribute('aria-label')),['角色级别','性别','年龄段','角色标签']);
  assert.deepEqual(filterRow.walk().find(n=>n.getAttribute('aria-label')==='性别').children.filter(n=>n.tagName==='OPTION').map(n=>n.textContent),['性别','男','女','其他']);
  const rowDirect=filterRow.children.filter(n=>n.tagName!=='#TEXT');
  assert.equal(rowDirect.at(-1),filterRow.querySelector('.center-count'));
  await button(root,'场景').onclick();
  assert.equal(root.querySelector('.center-clear-filters'),null);
  assert.ok(calls.some(url=>url.includes('source=official')&&url.includes('asset_kind=location')));
  assert.deepEqual(root.querySelector('.center-official-filter-row').walk().filter(n=>n.tagName==='SELECT').map(n=>n.getAttribute('aria-label')),['场景类型','空间属性']);
  await button(root,'道具').onclick();
  assert.deepEqual(root.querySelector('.center-official-filter-row').walk().filter(n=>n.tagName==='SELECT').map(n=>n.getAttribute('aria-label')),['道具类型']);
  await button(root,'人设').onclick();
  assert.equal(root.querySelector('.center-official-tags').textContent,'主角医生女青年');
  assert.equal(root.querySelector('.official-list-media').querySelector('.center-card-tools'),root.querySelector('.center-card-tools'));
  assert.ok(button(root,'引用生成'));
  assert.ok(root.querySelector('.center-card-menu'));
  assert.ok(calls[0].includes('source=official')&&calls[0].includes('media_only=true')&&calls[0].includes('asset_kind=character'));
  assert.equal(button(root,'站位'),undefined);
  await button(root,'音频').onclick();
  assert.ok(calls.some(url=>url.includes('asset_kind=voice')));
  await button(root,'人设').onclick();
  assert.match(calls.at(-1),/source=official/);
  assert.match(calls.at(-1),/asset_kind=character/);
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
