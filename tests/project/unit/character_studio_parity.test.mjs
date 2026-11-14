import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const nativeFetch=globalThis.fetch;
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
const matches=Element.prototype.matches;
Element.prototype.matches=function(selector){const key=selector.match(/^\[data-focus-key="([^"]+)"\]$/);return key?this.dataset.focusKey===key[1]:matches.call(this,selector);};
globalThis.CSS={escape:value=>String(value)};
const doc=new Document('');doc.documentElement=doc.createElement('html');doc.addEventListener=()=>{};doc.removeEventListener=()=>{};
globalThis.document=doc;
Object.defineProperty(Element.prototype,'style',{get(){return this._style??={};}});
Object.defineProperty(Element.prototype,'isConnected',{get(){for(let n=this;n;n=n.parentElement)if(n===doc.body)return true;return false;}});
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;for(const fn of this.listeners.get('close')||[])fn();};
Element.prototype.getBoundingClientRect=function(){return this._box||{left:0,top:0,width:400,height:400};};
const local=new Map(),copied=[];
globalThis.window={location:{protocol:'http:',hostname:'127.0.0.1'},localStorage:{getItem:k=>local.get(k)||null,setItem:(k,v)=>local.set(k,v),removeItem:k=>local.delete(k)}};
globalThis.sessionStorage={getItem:()=>null,setItem(){},removeItem(){}};
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>copied.push(text)}}});
const flush=()=>new Promise(resolve=>setTimeout(resolve,5));
function database(){
 const values=new Map(),control={failOpen:false,failRead:false,failWrite:false};
 return {values,control,api:{open(){
  const request={error:new Error('storage unavailable'),result:{close(){},transaction(){
   const tx={error:new Error('storage full'),objectStore(){return {
    get(key){const r={error:new Error('read failed')};queueMicrotask(()=>{if(control.failRead)r.onerror();else{r.result=structuredClone(values.get(key));r.onsuccess();}});return r;},
    put(value,key){queueMicrotask(()=>{if(control.failWrite)tx.onerror();else{values.set(key,structuredClone(value));tx.oncomplete();}});},
   };}};
   return tx;
  }}};
  queueMicrotask(()=>control.failOpen?request.onerror():request.onsuccess());return request;
 }}};
}
const mainDb=database();globalThis.indexedDB=mainDb.api;
const resizeObservers=[];
globalThis.ResizeObserver=class{constructor(callback){this.callback=callback;resizeObservers.push(this);}observe(node){this.node=node;}disconnect(){this.disconnected=true;}};
const store=await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createAssetCenter}=await import('../../../src/vsc/interfaces/web/static/asset-center.js');
const {createCharacterStudio}=await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const button=(node,label)=>node.querySelectorAll('button').find(b=>b.textContent===label);
const click=async(node,label)=>{const b=button(node,label);assert.ok(b,label);await b.onclick();await flush();};
const notices=[];
const pose=angle=>({id:`p-${angle}`,体系:'全身单人・标准系',姿势编号:'P001',分类:'站姿',姿势名称:'自然站立',角度:angle,缩略图:`thumbs/p-${angle}.jpg`,原图:`img/p-${angle}.png`});
const poseItems=[pose('正面'),pose('侧面')];
const costume={id:'c-1',source:'shisei',selectedView:'front',服装名称:'宽袖长衫',来源:'Shisei',来源地址:'https://github.com/wquguru/shisei',分类:'中国历代',标签:['长衫','宽袖'],关键词:'wide sleeves robe',缩略图:'thumbs/costumes/shisei/c.webp',原图:'img/costumes/shisei/c.png',views:[{id:'front',label:'正面',缩略图:'thumbs/costumes/shisei/c.webp',原图:'img/costumes/shisei/c.png'},{id:'back',label:'背面',缩略图:'thumbs/costumes/shisei/b.webp',原图:'img/costumes/shisei/b.png'}]};
const portrait={id:'portrait-1',标题:'短发人像',分区:'正脸参考',发长:'短发',发型名称:'直发',宽:1600,高:2000,缩略图:'thumbs/portrait/1.webp',原图:'img/portrait/1.webp'};
const ctx={session:()=>({actor:'audit',csrf:'csrf'}),notice:m=>notices.push(m),api:async url=>{
 if(url.includes('/auth/status'))return {};
 if(url.includes('/poses'))return {items:url.includes('view=single')?poseItems:[{key:'group',name:'自然站立',system:poseItems[0].体系,category:'站姿',items:poseItems}],total:1,next_offset:null,systems:[],categories:[],angles:['正面','侧面']};
 if(url.includes('/costumes'))return {items:[costume],total:1,next_offset:null,tops:[],sources:[],categories:[],tags:[]};
 if(url.includes('/portraits'))return {items:[portrait],total:1,next_offset:null,sections:[],hair_lengths:[],hair_styles:[]};
 throw new Error('Unexpected request '+url);
}};
async function gallery(kind,overrides={}){
 globalThis.location={search:'?kind='+kind};
 const root=doc.createElement('main');doc.body.append(root);
 const center=createAssetCenter(root,{...ctx,...overrides},{source:'official',workbench:true});await center.load();await flush();
 return {root,center};
}
function modal(){return doc.body.querySelector('.ref-modal');}

test('Depth preview, download, angle, copied ID and recipe stay aligned without closing the modal',async()=>{
 const {root,center}=await gallery('pose');
 await root.querySelector('.costume-open').onclick();
 const original=modal();await click(original,'Depth');
 assert.equal(modal(),original);assert.ok(original.open);
 const download=()=>original.querySelectorAll('a').find(a=>a.textContent==='下载原图');
 assert.match(original.querySelector('img').src,/img\/depth\/p-正面.webp$/);
 assert.equal(download().href,original.querySelector('img').src);
 assert.equal(download().getAttribute('download'),'p-正面_depth.webp');
 assert.match(root.querySelector('.costume-open').querySelector('img').src,/thumbs\/depth\//);
 await click(original,'侧面');await click(original,'复制姿势 ID');assert.equal(copied.at(-1),'p-侧面');
 assert.match(download().href,/p-侧面.webp$/);
 await click(original,'加入配方');assert.equal(store.getState().recipe.pose.id,'p-侧面');assert.equal(store.getState().recipe.pose.useDepth,true);
 await click(original,'白模');assert.equal(download().href,original.querySelector('img').src);assert.match(download().href,/img\/p-侧面.png$/);
 assert.equal(download().getAttribute('download'),'p-侧面.png');
 assert.ok(original.textContent.includes('900 × 1200 PNG'));
 original.close();
 const view=root.querySelectorAll('select').find(s=>s.getAttribute('aria-label')==='视图');view.value='single';await view.onchange();await flush();
 await root.querySelector('.costume-open').onclick();await click(modal(),'Depth');
 assert.equal(modal().querySelectorAll('a').find(a=>a.textContent==='下载原图').href,modal().querySelector('img').src);
 modal().close();center.suspend();root.remove();
});

test('reference details retain English costume prompt, tags, source links, view downloads and portrait ID/dimensions',async()=>{
 let {root,center}=await gallery('costume');await root.querySelector('.costume-open').onclick();
 assert.ok(modal().textContent.includes(costume.关键词));assert.ok(modal().textContent.includes('长衫 · 宽袖'));
 await click(modal(),'复制英文服装 Prompt');assert.equal(copied.at(-1),costume.关键词);
 assert.ok(modal().querySelectorAll('a').some(a=>a.href.endsWith('/LICENSE-images')));
 await click(modal(),'背面');assert.match(modal().querySelectorAll('a').find(a=>a.textContent==='下载原图').href,/\/b.png$/);
 modal().close();center.suspend();root.remove();
 ({root,center}=await gallery('portrait'));await root.querySelector('.costume-open').onclick();
 await click(modal(),'复制人像 ID');assert.equal(copied.at(-1),portrait.id);assert.ok(modal().textContent.includes('1600 × 2000'));
 // A rejected clipboard write must not produce a success message.
 const before=notices.length;globalThis.navigator.clipboard.writeText=async()=>{throw new Error('clipboard denied');};
 await click(modal(),'复制人像 ID');assert.deepEqual(notices.slice(before),['clipboard denied']);
 globalThis.navigator.clipboard.writeText=async text=>copied.push(text);
 modal().close();center.suspend();root.remove();
});

test('history menus close on a repeated trigger, outside mouse/touch click, Escape, focus departure and suspension',async()=>{
 const saved=structuredClone(store.getState()),add=doc.addEventListener,remove=doc.removeEventListener,listeners=new Map();
 let root,center;
 doc.addEventListener=(type,fn,capture)=>{assert.equal(capture,true);if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn);};
 doc.removeEventListener=(type,fn)=>listeners.get(type)?.delete(fn);
 const dispatch=(type,target,extra={})=>{const e=event({target,...extra});for(const fn of [...(listeners.get(type)||[])])fn(e);return e;};
 try{
  store.getState().history=[1,2].map(i=>({id:`menu-${i}`,createdAt:i,imageUrl:'data:image/png;base64,AA==',provider:'agy_auth',prompt:'menu fixture'}));
  ({root,center}=await gallery('composite'));
  const menus=root.querySelectorAll('.cs-history-menu'),toolbar=menus[0],summary=toolbar.querySelector('summary'),search=root.querySelector('input');
  const toggle=menu=>menu.querySelector('summary').onclick(event({target:menu.querySelector('summary')}));
  toggle(toolbar);assert.equal(toolbar.open,true);assert.equal(summary.getAttribute('aria-expanded'),'true');
  toggle(toolbar);assert.equal(toolbar.open,false);assert.equal(summary.getAttribute('aria-expanded'),'false');
  toggle(toolbar);dispatch('pointerdown',toolbar.querySelector('button'),{pointerType:'touch'});assert.equal(toolbar.open,true);
  dispatch('pointerdown',search,{pointerType:'mouse'});assert.equal(toolbar.open,false);assert.equal(summary.getAttribute('aria-expanded'),'false');
  toggle(toolbar);dispatch('pointerdown',doc.body,{pointerType:'touch'});assert.equal(toolbar.open,false);
  toggle(toolbar);dispatch('click',search);assert.equal(toolbar.open,false);
  toggle(toolbar);toggle(menus[1]);assert.equal(toolbar.open,false);assert.equal(menus[1].open,true);
  toggle(menus[2]);assert.equal(menus[1].open,false);assert.equal(menus[2].open,true);
  const escaped=dispatch('keydown',doc.body,{key:'Escape'});assert.equal(escaped.prevented,true);assert.equal(menus[2].open,false);assert.equal(doc.activeElement,menus[2].querySelector('summary'));
  toggle(toolbar);search.focus();dispatch('focusin',search);assert.equal(toolbar.open,false);assert.equal(doc.activeElement,search);
  toggle(toolbar);center.suspend();assert.equal(toolbar.open,false);assert.ok([...listeners.values()].every(set=>set.size===0));
  await center.load();await flush();assert.ok([...listeners.values()].every(set=>set.size===1));
  center.suspend();assert.ok([...listeners.values()].every(set=>set.size===0));
 }finally{
  center?.suspend();root?.remove();doc.addEventListener=add;doc.removeEventListener=remove;
  Object.assign(store.getState(),saved);store.setPreviewUrl(saved.previewUrl);
 }
});

test('AI composite library follows portraits and owns existing, live, filtered and recoverable generation history',async()=>{
 const saved=structuredClone(store.getState()),oldConfirm=globalThis.confirm,oldFetch=globalThis.fetch,originalClick=Element.prototype.click;
 const routes=[],downloads=[];let center,root,studio,studioRoot;
 const old={id:'existing',createdAt:1,imageUrl:'data:image/png;base64,old-result',provider:'codex_auth',prompt:'雨夜人像',recipeSummary:'旧合成记录',snapshot:{recipe:{portrait,extraImages:[]}}};
 Element.prototype.click=function(...args){if(this.tagName==='A'&&this.download){downloads.push(this.href);return;}return originalClick.apply(this,args);};
 try{
  store.getState().history=[old];
  ({root,center}=await gallery('composite',{navigate:(...args)=>routes.push(args)}));
  const tabs=root.querySelector('.center-official-kinds').querySelectorAll('button').map(b=>b.textContent);
  assert.equal(tabs[tabs.indexOf('人像颜值库')+1],'AI角色合成库');
  assert.equal(button(root,'AI角色合成库').getAttribute('aria-pressed'),'true');
  assert.equal(root.querySelector('.cs-history-item').querySelector('img').src,old.imageUrl);
  assert.equal(store.getState().history[0],old);
  await click(root,'查看详情');const detail=doc.body.querySelector('.cs-history-detail');assert.ok(detail.textContent.includes(old.recipeSummary));assert.ok(detail.textContent.includes(old.prompt));
  await click(detail,'复制提示词');assert.equal(copied.at(-1),old.prompt);await click(detail,'×');assert.equal(doc.body.querySelector('.cs-history-detail'),null);assert.equal(doc.activeElement.tagName,'SUMMARY');
  root.querySelector('.cs-history-item').querySelector('img').onerror();assert.match(root.textContent,/图片暂时无法显示/);
  const menu=root.querySelector('.cs-history-menu');menu.open=true;menu.onkeydown(event({key:'Escape'}));assert.equal(menu.open,false);
  store.getState().hydrated=false;store.getState().generationError='';store.setPreviewUrl(old.imageUrl);await flush();assert.equal(root.querySelectorAll('.cs-history-skeleton').length,2);assert.equal(root.querySelector('.cs-history').getAttribute('aria-busy'),'true');
  store.getState().generationError='storage unavailable';store.setPreviewUrl(old.imageUrl);await flush();assert.match(root.textContent,/暂时无法读取合成记录/);assert.ok(button(root,'重试读取'));assert.doesNotMatch(root.textContent,/还没有合成记录/);
  store.getState().hydrated=true;store.getState().generationError='';store.setPreviewUrl(old.imageUrl);await flush();
  await click(root,'下载图片');assert.equal(downloads.at(-1),old.imageUrl);
  await click(root,'复用提示词');assert.equal(store.getState().customPrompt,old.prompt);assert.deepEqual(routes.at(-1),['character-studio']);
  const search=root.querySelector('input');search.value='不匹配';search.oninput();assert.equal(root.querySelectorAll('.cs-history-item').length,0);assert.match(root.textContent,/没有找到合成记录/);
  search.value='CODEX';search.oninput();assert.equal(root.querySelectorAll('.cs-history-item').length,1);
  search.value='';search.oninput();
  store.getState().recipe={portrait:{...portrait,source:'upload',原图:'data:image/png;base64,AA=='},costume:null,pose:null,extraImages:[]};
  globalThis.fetch=async()=>({ok:true,json:async()=>({image_url:'data:image/png;base64,bmV3',model:'synthetic'})});
  await store.startGeneration();await flush();
  const added=store.getState().history[0];assert.notEqual(added.id,old.id);assert.equal(mainDb.values.get('pose_atlas_history_v3')[0].id,added.id);
  assert.equal(root.querySelectorAll('.cs-history-item').length,2);assert.equal(root.querySelector('.cs-history-item').querySelector('img').src,added.imageUrl);
  globalThis.confirm=()=>true;mainDb.control.failWrite=true;await click(root.querySelector('.cs-history-item'),'删除记录');assert.equal(root.querySelectorAll('.cs-history-item').length,2);assert.match(notices.at(-1),/删除失败/);
  mainDb.control.failWrite=false;await click(root.querySelector('.cs-history-item'),'删除记录');assert.equal(root.querySelectorAll('.cs-history-item').length,1);assert.equal(mainDb.values.get('pose_atlas_history_v3')[0].id,old.id);
  globalThis.confirm=()=>false;await click(root,'清空全部记录');assert.equal(store.getState().history.length,1);
  studioRoot=doc.createElement('main');doc.body.append(studioRoot);studio=createCharacterStudio(studioRoot,{...ctx,navigate:(...args)=>routes.push(args)});await studio.load();await flush();
  assert.equal(studioRoot.querySelector('.cs-history'),null);
  await click(studioRoot,'AI角色合成库 (1)');assert.deepEqual(routes.at(-1),['asset-center',{tab:'official',kind:'composite'}]);
  globalThis.confirm=()=>true;await click(root,'清空全部记录');assert.equal(mainDb.values.get('pose_atlas_history_v3').length,0);assert.match(root.textContent,/还没有合成记录/);assert.equal(button(root,'清空全部记录').disabled,true);
  center.suspend();store.getState().history=[added];store.setPreviewUrl(added.imageUrl);await flush();assert.match(root.textContent,/还没有合成记录/);
  center.suspend();await center.load();await flush();assert.equal(root.querySelectorAll('.cs-history-item').length,1);
  await click(root,'人像颜值库');assert.ok(root.querySelector('.ref-library')||root.className.includes('ref-portrait'));assert.equal(root.querySelector('.cs-history-library'),null);
  await click(root,'AI角色合成库');assert.equal(root.querySelectorAll('.cs-history-item').length,1);
 }finally{
  mainDb.control.failWrite=false;center?.suspend();root?.remove();studio?.suspend();studioRoot?.remove();Object.assign(store.getState(),saved);
  globalThis.fetch=oldFetch;Element.prototype.click=originalClick;if(oldConfirm===undefined)delete globalThis.confirm;else globalThis.confirm=oldConfirm;
 }
});

test('browser-only composite records are not offered as server catalog assets inside the canvas picker',async()=>{
 const root=doc.createElement('main');doc.body.append(root);
 const center=createAssetCenter(root,{...ctx,api:async(url,...args)=>url.startsWith('/api/v1/asset-center?')?{items:[],total:0,facets:{},next_offset:null}:ctx.api(url,...args)},{source:'official',canvas:true,workbench:true});
 try{
  await center.load();await flush();assert.equal(button(root,'AI角色合成库'),undefined);
  await click(root,'人像颜值库');assert.equal(button(root,'AI角色合成库'),undefined);assert.ok(root.className.includes('ref-portrait'));
 }finally{center.suspend();root.remove();}
});

async function comparison(result){
 store.getState().history=[result];
 const {root,center}=await gallery('composite');
 const compare=button(root,'对比参考'),trigger=compare.parentElement.parentElement.querySelector('summary');trigger.focus();await compare.onclick();
 return {root,studio:center,trigger,dialog:doc.body.querySelector('.cs-compare')};
}
function loadImages(dialog,width=800,height=800){
 for(const img of dialog.querySelectorAll('img')){img.naturalWidth=width;img.naturalHeight=height;img.onload();}
}
const event=values=>({preventDefault(){this.prevented=true;},...values});
const history={id:'h-1',createdAt:1,imageUrl:'data:image/png;base64,AA==',prompt:'测试',recipeSummary:'合成参考',snapshot:{recipe:{portrait,pose:poseItems[0],extraImages:[]}}};

test('comparison synchronizes wheel, keyboard, drag, pinch, slider and resize at the original 1–8x limits',async()=>{
 const {root,studio,trigger,dialog}=await comparison(history);loadImages(dialog);
 let [a,b]=dialog.querySelectorAll('img'),vp=dialog.querySelector('.cs-compare-viewport');
 await vp.dispatch('wheel',{clientX:200,clientY:200,deltaY:-10000});
 assert.equal(a.style.transform,b.style.transform);assert.match(a.style.transform,/scale\(8\)/);
 assert.equal(button(dialog,'＋').disabled,true);
 vp.onkeydown(event({key:'0'}));assert.match(a.style.transform,/scale\(1\)/);assert.equal(button(dialog,'−').disabled,true);
 for(let i=0;i<12;i++)await button(dialog,'＋').onclick();assert.equal(button(dialog,'＋').disabled,true);assert.match(a.style.transform,/scale\(8\)/);
 vp.onkeydown(event({key:'0'}));
 vp.onkeydown(event({key:'+'}));assert.match(a.style.transform,/scale\(1.25\)/);
 vp.onkeydown(event({key:'ArrowLeft'}));assert.notEqual(a.style.transform,'translate(0%, 0%) scale(1.25)');
 assert.equal(a.style.transform,b.style.transform);
 vp.onkeydown(event({key:'Home'}));
 vp.onpointerdown(event({button:0,pointerId:1,clientX:100,clientY:200}));
 vp.onpointerdown(event({button:0,pointerId:2,clientX:300,clientY:200}));
 vp.onpointermove(event({pointerId:2,clientX:500,clientY:200}));assert.match(a.style.transform,/scale\(2\)/);
 vp.onpointercancel(event({pointerId:2}));const beforeDrag=a.style.transform;
 vp.onpointermove(event({pointerId:1,clientX:140,clientY:230}));assert.notEqual(a.style.transform,beforeDrag);assert.equal(a.style.transform,b.style.transform);
 vp.onlostpointercapture(event({pointerId:1}));const released=a.style.transform;
 vp.onpointermove(event({pointerId:1,clientX:150,clientY:250}));assert.equal(a.style.transform,released);
 await click(dialog,'滑杆');loadImages(dialog);
 const range=dialog.querySelectorAll('input').find(i=>i.type==='range');range.value='25';range.oninput();
 assert.equal(dialog.querySelector('.cs-compare-top').style.clipPath,'inset(0 75% 0 0)');
 assert.equal(range.getAttribute('aria-valuetext'),'25% 参考图');
 [a,b]=dialog.querySelectorAll('img');vp=dialog.querySelector('.cs-compare-viewport');
 vp.onkeydown(event({key:'+'}));assert.equal(a.style.transform,b.style.transform);
 const select=dialog.querySelector('select');select.value='pose';select.onchange();loadImages(dialog);
 assert.ok(dialog.querySelectorAll('img').every(i=>i.style.transform==='translate(0%, 0%) scale(1)'));
 await click(dialog,'并排');loadImages(dialog);
 vp=dialog.querySelector('.cs-compare-viewport');
 vp.onkeydown(event({key:'+'}));vp.onkeydown(event({key:'ArrowLeft'}));
 // Different aspect ratios intersect their pan bounds, including after resize.
 const imgs=dialog.querySelectorAll('img');imgs[0].naturalWidth=1600;imgs[0].naturalHeight=200;imgs[0].onload();
 assert.ok(imgs.every(i=>i.style.transform.startsWith('translate(')));
 for(const observer of resizeObservers.filter(o=>!o.disconnected)){observer.node._box={left:0,top:0,width:2000,height:100};observer.callback();}
 assert.ok(imgs.every(i=>i.style.transform.startsWith('translate(0%, 0%)')));
 dialog.close();assert.equal(doc.activeElement,trigger);assert.ok(resizeObservers.every(o=>o.disconnected));
 studio.suspend();root.remove();
});

test('comparison preserves a result without a snapshot and reports individual image load failures',async()=>{
 let ui=await comparison({...history,id:'old',snapshot:undefined});
 assert.ok(ui.dialog.textContent.includes('仍可查看生成结果'));assert.equal(ui.dialog.querySelectorAll('img').length,1);
 const img=ui.dialog.querySelector('img');img.onerror();assert.ok(img.hidden);assert.ok(ui.dialog.textContent.includes('加载失败'));
 ui.dialog.close();ui.studio.suspend();ui.root.remove();
});

let sequence=0;
async function isolatedStore(db){
 globalThis.indexedDB=db.api;
 const s=await import(`../../../src/vsc/interfaces/web/static/character-studio-store.js?parity=${++sequence}`),notes=[];
 s.configureStudio({notice:m=>notes.push(m)});await flush();return {s,notes};
}
const image='data:image/png;base64,AA==';
test('reloading starts with an empty result while keeping native and legacy history available',async()=>{
 const key='pose_atlas_history_v3',entry={id:'retained-history',createdAt:1,imageUrl:image,prompt:'Retained prompt'};
 const db=database();db.values.set(key,[entry]);
 const native=await isolatedStore(db);assert.equal(native.s.getState().previewUrl,'');assert.deepEqual(native.s.getState().history,[entry]);
 const previous=local.get(key);local.set(key,JSON.stringify([entry]));
 try{
  const legacy=await isolatedStore(database());assert.equal(legacy.s.getState().previewUrl,'');assert.deepEqual(legacy.s.getState().history,[entry]);
  legacy.s.setPreviewUrl(image);await flush();assert.equal(legacy.s.getState().previewUrl,image);
  assert.deepEqual(legacy.s.getState().history,[entry]);
 }finally{if(previous===undefined)local.delete(key);else local.set(key,previous);}
});
test('history commits before success, restores on reload, and keeps old history on failed save/delete/clear',async()=>{
 const db=database(),{s,notes}=await isolatedStore(db);let requests=0;
 s.setSlot('portrait',{...portrait,source:'upload',原图:image,缩略图:image});await flush();
 globalThis.fetch=async()=>{requests++;return {ok:true,json:async()=>({image_url:image,model:'synthetic'})};};
 await s.startGeneration();assert.equal(requests,1);assert.equal(db.values.get('pose_atlas_history_v3').length,1);assert.equal(notes.at(-1),'角色图已完成并保存');
 const reloaded=await isolatedStore(db);assert.equal(reloaded.s.getState().history.length,1);assert.equal(reloaded.s.getState().previewUrl,'');
 db.control.failWrite=true;await s.startGeneration();
 assert.equal(s.getState().history.length,1);assert.equal(db.values.get('pose_atlas_history_v3').length,1);
 assert.equal(s.getState().previewUrl,image);assert.match(notes.at(-1),/生成记录保存失败/);assert.equal(requests,2);
 await s.removeHistoryItem(s.getState().history[0].id);assert.match(notes.at(-1),/删除失败/);assert.equal(s.getState().history.length,1);
 await s.clearHistory();assert.match(notes.at(-1),/清空记录失败/);assert.equal(s.getState().history.length,1);
 db.control.failWrite=false;await s.clearHistory();assert.equal(db.values.get('pose_atlas_history_v3').length,0);
});

test('unreadable storage blocks generation and media transfer failures never report saved output',async()=>{
 for(const failure of ['failOpen','failRead']){
  const db=database();db.control[failure]=true;const {s,notes}=await isolatedStore(db);let requests=0;
  globalThis.fetch=async()=>{requests++;throw new Error('must not submit');};
  assert.equal(s.getState().hydrated,false);await s.startGeneration();assert.equal(requests,0);assert.match(notes.at(-1),/无法读取浏览器存储/);
 }
 const db=database(),{s,notes}=await isolatedStore(db);
 s.setSlot('portrait',{...portrait,source:'upload',原图:image,缩略图:image});await flush();
 globalThis.fetch=async url=>{
  if(url==='/api/v1/character-studio/generate')return {ok:true,json:async()=>({image_url:'https://imgen.x.ai/temp.png',model:'synthetic'})};
  throw new Error('image download offline');
 };
 await s.startGeneration();assert.equal(s.getState().history.length,0);assert.match(notes.at(-1),/图片转存失败/);
 assert.equal(s.getState().previewUrl,'https://imgen.x.ai/temp.png');
});

test('reference sheet preview opens separately and never replaces or downloads as the generated result',async()=>{
 store.configureStudio({api:ctx.api,notice:ctx.notice});await flush();
 const saved=structuredClone(store.getState()),originalImage=globalThis.Image;
 const originalContext=Element.prototype.getContext,originalDataUrl=Element.prototype.toDataURL,originalClick=Element.prototype.click,downloads=[];
 const result='data:image/png;base64,generated-result',sheet='data:image/jpeg;base64,reference-sheet';
 let failImage=false;
 globalThis.Image=class{
  constructor(){this.width=100;this.height=100;}
  set src(value){queueMicrotask(()=>failImage?this.onerror():this.onload());}
 };
 Element.prototype.getContext=()=>({fillRect(){},drawImage(){},fillText(){}});
 Element.prototype.toDataURL=()=>sheet;
 Element.prototype.click=function(...args){if(this.tagName==='A'&&this.download){downloads.push(this.href);return;}return originalClick.apply(this,args);};
 const root=doc.createElement('main');doc.body.append(root);
 const studio=createCharacterStudio(root,ctx);
 try{
  Object.assign(store.getState(),{recipe:{portrait:{...portrait,source:'upload',原图:'data:image/png;base64,reference'},costume:null,pose:null,extraImages:[]},previewUrl:result,isGenerating:false,generationError:''});
  await studio.load();await flush();
  const resultImage=()=>root.querySelector('.cs-result').querySelector('img');
  assert.equal(resultImage().src,result);
  for(let i=0;i<2;i++){
   await click(root,'查看拼图');
   const dialog=doc.body.querySelector('.cs-stitch');assert.ok(dialog.open);
   assert.equal(dialog.querySelector('img').src,sheet);
   assert.equal(resultImage().src,result);assert.equal(store.getState().previewUrl,result);
   await click(dialog,'下载拼图');assert.equal(downloads.at(-1),sheet);
   await click(dialog,'关闭');
   assert.equal(resultImage().src,result);
   await click(root,'下载');assert.equal(downloads.at(-1),result);
  }
  failImage=true;await click(root,'查看拼图');
  assert.equal(doc.body.querySelector('.cs-stitch'),null);
  assert.equal(resultImage().src,result);assert.equal(store.getState().previewUrl,result);
  failImage=false;store.setPreviewUrl('');await flush();await click(root,'查看拼图');
  assert.equal(root.querySelector('.cs-result').querySelector('img'),null);
  assert.equal(store.getState().previewUrl,'');
  doc.body.querySelector('.cs-stitch').close();
 }finally{
  studio.suspend();root.remove();Object.assign(store.getState(),saved);
  if(originalImage===undefined)delete globalThis.Image;else globalThis.Image=originalImage;
  if(originalContext===undefined)delete Element.prototype.getContext;else Element.prototype.getContext=originalContext;
  if(originalDataUrl===undefined)delete Element.prototype.toDataURL;else Element.prototype.toDataURL=originalDataUrl;
  Element.prototype.click=originalClick;
 }
});


test('saving a new character keeps older library entries beyond the former 30-record cutoff',async()=>{
 const db=database(),older=Array.from({length:30},(_,i)=>({id:`old-${i}`,createdAt:i,imageUrl:image,prompt:'旧提示词',recipeSummary:'已保存角色'}));
 db.values.set('pose_atlas_history_v3',older);
 const {s}=await isolatedStore(db);
 s.setSlot('portrait',{...portrait,source:'upload',原图:image,缩略图:image});await flush();
 globalThis.fetch=async()=>({ok:true,json:async()=>({image_url:image,model:'synthetic'})});
 await s.startGeneration();assert.equal(s.getState().history.length,31);assert.ok(s.getState().history.some(h=>h.id==='old-0'));
 assert.equal((await isolatedStore(db)).s.getState().history.length,31);
});

const entryId='10000000-0000-4000-8000-000000000001',versionId='20000000-0000-4000-8000-000000000001';
const publicationRecord=(id='managed-result')=>({id,createdAt:1700000000000,imageUrl:'data:image/webp;base64,QUJD',provider:'codex_auth',model:'frozen-model',prompt:'frozen prompt',recipeSummary:'原始角色',snapshot:{recipe:{portrait:{id:'original-reference',标题:'原人像',source:'upload',原图:'data:image/png;base64,reference'}},settings:{stylePreset:'realistic',apiKey:'must-not-publish'},models:{gpt:{model:'frozen-model',apiKey:'also-secret'}}}});
async function publicationHarness(options={}){
 const db=database(),record=publicationRecord(options.id);db.values.set('pose_atlas_history_v3',[record]);
 const {s,notes}=await isolatedStore(db),calls=[];let actor='publisher',failure=options.failure||'',allowed=options.allowed!==false;
 const control={set actor(v){actor=v;},set failure(v){failure=v;},set allowed(v){allowed=v;},hold:null};
 const api=async(path,opts={})=>{
  const body=opts.body instanceof Blob?opts.body:opts.body?JSON.parse(opts.body):null;
  calls.push({path,opts,body});
  assert.equal(opts.headers?.['X-CSRF-Token'],'publication-csrf');
  if(path.endsWith('/capabilities')){if(failure==='capability')throw new Error('权限服务离线');return {can_publish:allowed};}
  if(control.hold&&path===control.hold.path)await control.hold.promise;
  if(path.endsWith('/uploads')){if(failure==='upload')throw new Error('上传离线');return {staged_upload:'controlled-upload'};}
  if(path.endsWith('/import')){if(failure==='import')throw new Error('共享库响应丢失');return {entry_id:entryId,version_id:versionId};}
  if(path.endsWith('/publish')){if(failure==='publish')throw new Error('官方发布响应丢失');if(options.failReceiptWrite)db.control.failWrite=true;return {id:'official-receipt',entry_id:entryId,library_version_id:versionId};}
  throw new Error('Unexpected '+path);
 };
 s.configureStudio({api,session:()=>({actor,csrf:'publication-csrf'}),csrf:()=> 'publication-csrf'});
 s.getState().currentResult=s.getState().history[0];s.getState().previewUrl=record.imageUrl;
 return {db,s,notes,calls,control,record:s.getState().currentResult,api};
}
const publish=h=>h.s.publishCurrentResult(h.record.id,{title:'确认的人设',allowWorkspaceReuse:true,actor:'publisher'});

test('generation keeps an independent result ID and original snapshot even when writing its local history fails',async()=>{
 const db=database(),{s}=await isolatedStore(db),previousFetch=globalThis.fetch;
 s.setSlot('portrait',{...portrait,source:'upload',原图:image,缩略图:image});await flush();
 let release;const pending=new Promise(resolve=>release=resolve);
 globalThis.fetch=async()=>{await pending;return {ok:true,json:async()=>({image_url:image,model:'original-model',provider:'codex_auth'})};};
 const generation=s.startGeneration('original-prompt');await flush();
 s.clearRecipe();s.setCustomPrompt('new draft prompt');db.control.failWrite=true;release();await generation;
 const result=s.getState().currentResult;
 assert.ok(result.id);assert.equal(result.imageUrl,image);assert.equal(result.prompt,'original-prompt');assert.equal(result.model,'original-model');assert.equal(result.snapshot.recipe.portrait.id,portrait.id);
 assert.equal(s.getState().history.length,0);assert.match(s.getState().generationError,/生成记录保存失败/);
 db.control.failWrite=false;assert.equal(await s.deleteCurrentResult(result.id),true);assert.equal(s.getState().currentResult,null);assert.equal(s.getState().previewUrl,'');
 globalThis.fetch=previousFetch;
});

test('deletion uses the result ID, preserves a different generation with the same bytes, and keeps failed deletes intact',async()=>{
 const h=await publicationHarness();const other={...h.record,id:'same-image-other-generation'};
 h.s.getState().history.push(other);h.db.values.set('pose_atlas_history_v3',structuredClone(h.s.getState().history));
 h.db.control.failWrite=true;
 assert.equal(await h.s.deleteCurrentResult(h.record.id),false);assert.equal(h.s.getState().currentResult.id,h.record.id);assert.equal(h.s.getState().history.length,2);
 assert.match(h.s.getState().resultError,/删除失败/);
 h.db.control.failWrite=false;
 assert.equal(await h.s.deleteCurrentResult(h.record.id),true);assert.equal(h.s.getState().currentResult,null);assert.deepEqual(h.s.getState().history.map(x=>x.id),[other.id]);
 // A late delete of an older ID must not clear a replacement result.
 h.s.getState().currentResult=other;h.s.getState().previewUrl=other.imageUrl;
 const pending=h.s.removeHistoryItem(other.id),newer={...other,id:'newer-result'};h.s.getState().currentResult=newer;h.s.getState().previewUrl=newer.imageUrl;
 await pending;assert.equal(h.s.getState().currentResult.id,newer.id);assert.equal(h.s.getState().previewUrl,newer.imageUrl);
});

test('clear local history clears only its linked current result and keeps a newer late result',async()=>{
 const h=await publicationHarness();await h.s.clearHistory();assert.equal(h.s.getState().currentResult,null);assert.equal(h.s.getState().previewUrl,'');
 const other=publicationRecord('old');h.s.getState().history=[other];h.s.getState().currentResult=other;
 const pending=h.s.clearHistory(),newer=publicationRecord('new');h.s.getState().currentResult=newer;h.s.getState().previewUrl=newer.imageUrl;
 await pending;assert.equal(h.s.getState().currentResult.id,'new');
});

test('official publication checks permission before writes and distinguishes denied from unavailable capability',async()=>{
 for(const options of [{allowed:false},{failure:'capability'}]){
  const h=await publicationHarness(options);assert.equal(await publish(h),false);
  assert.deepEqual(h.calls.map(x=>x.path),['/api/v1/asset-center/official/capabilities']);assert.equal(h.s.getState().currentResult.id,h.record.id);assert.equal(h.s.getState().history.length,1);
  assert.match(h.s.getState().resultError,options.allowed===false?/没有发布官方资产的权限/:/权限服务离线/);
 }
});

test('official publication uploads generated bytes and a frozen nonsecret specification before publishing the fixed character version',async()=>{
 const h=await publicationHarness(),previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;
 try{
  h.s.setCustomPrompt('later draft');h.s.updateApiConfig({stylePreset:'anime'});
  const receipt=await publish(h);assert.equal(receipt.entry_id,entryId);
  assert.deepEqual(h.calls.map(x=>x.path),['/api/v1/asset-center/official/capabilities','/api/v1/library/uploads','/api/v1/library/import','/api/v1/asset-center/official/publish']);
  const upload=h.calls[1];assert.ok(upload.body instanceof Blob);assert.equal(await upload.body.text(),'ABC');assert.equal(upload.body.type,'image/webp');assert.match(decodeURIComponent(upload.opts.headers['X-Filename']),/\.webp$/);
  const imported=h.calls[2].body;assert.equal(imported.confirmed,true);assert.equal(imported.payload.specification.prompt,'frozen prompt');assert.equal(imported.payload.specification.style_preset,'realistic');
  assert.equal(imported.payload.license.outcome,'licensed');assert.equal(imported.payload.license.allow_workspace_reuse,true);assert.match(imported.payload.license.evidence,/用户明确确认/);
  assert.equal(imported.payload.members[0].staged_upload,'controlled-upload');assert.equal(JSON.stringify(imported).includes('must-not-publish'),false);assert.equal(JSON.stringify(imported).includes('also-secret'),false);assert.equal(JSON.stringify(imported).includes('data:image'),false);
  const published=h.calls[3].body.payload;assert.equal(published.library_version_id,versionId);assert.equal(published.asset_kind,'character');assert.equal(published.gender,'unspecified');assert.equal(published.role_level,'unspecified');
  const saved=h.db.values.get('pose_atlas_history_v3')[0];assert.equal(saved.publication.officialReceipt.id,'official-receipt');assert.equal(h.s.getState().currentResult.publication.officialReceipt.id,'official-receipt');
  assert.equal((await publish(h)).id,'official-receipt');assert.equal(h.calls.length,4);
 }finally{globalThis.fetch=previousFetch;}
});

test('phase failures resume the original request without uploading or importing completed phases again',async()=>{
 const previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;
 try{for(const phase of ['upload','import','publish']){
  const h=await publicationHarness({failure:phase});assert.equal(await publish(h),false);
  const first=h.calls.filter(c=>c.path.endsWith('/'+phase)).at(-1),savedTitle=h.s.getState().currentResult.publication.title;
  h.control.failure='';const receipt=await h.s.publishCurrentResult(h.record.id,{title:'later changed title',allowWorkspaceReuse:true,actor:'publisher'});assert.equal(receipt.id,'official-receipt');
  assert.equal(h.s.getState().currentResult.publication.title,savedTitle);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/uploads')).length,phase==='upload'?2:1);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/import')).length,phase==='import'?2:1);
  if(phase!=='upload'){const requests=h.calls.filter(c=>c.path.endsWith('/'+phase));assert.deepEqual(requests[0].body,requests[1].body);}
  assert.ok(first||phase==='upload');
 }}finally{globalThis.fetch=previousFetch;}
});

test('pending publication blocks generation, deletion and duplicate submit while preserving its original receipt across replacement',async()=>{
 const h=await publicationHarness(),previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;
 let release;h.control.hold={path:'/api/v1/asset-center/official/publish',promise:new Promise(resolve=>release=resolve)};
 try{
  const pending=publish(h);while(!h.calls.some(x=>x.path.endsWith('/publish')))await flush();
  assert.equal(await publish(h),false);assert.equal(await h.s.deleteCurrentResult(h.record.id),false);await h.s.startGeneration();assert.equal(h.s.getState().isGenerating,false);
  const newer=publicationRecord('newer-result');h.s.getState().currentResult=newer;h.s.getState().previewUrl=newer.imageUrl;
  release();assert.equal((await pending).id,'official-receipt');assert.equal(h.s.getState().currentResult.id,'newer-result');assert.equal(h.s.getState().currentResult.publication,undefined);
  assert.equal(h.s.getState().history.find(x=>x.id===h.record.id).publication.officialReceipt.id,'official-receipt');
 }finally{globalThis.fetch=previousFetch;}
});

test('identity changes stop remaining publication steps and never replay another actors receipt',async()=>{
 const h=await publicationHarness(),previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;
 let release;h.control.hold={path:'/api/v1/library/uploads',promise:new Promise(resolve=>release=resolve)};
 try{
  const pending=publish(h);while(!h.calls.some(x=>x.path.endsWith('/uploads')))await flush();
  h.control.actor='different-user';release();assert.equal(await pending,false);assert.equal(h.calls.some(x=>x.path.endsWith('/import')),false);
  h.control.hold=null;assert.equal(await h.s.publishCurrentResult(h.record.id,{title:'other actor',allowWorkspaceReuse:true,actor:'different-user'}),false);
  assert.match(h.s.getState().resultError,/另一账号/);
  h.control.actor='publisher';assert.equal((await publish(h)).id,'official-receipt');
  h.control.actor='different-user';assert.equal(await h.s.publishCurrentResult(h.record.id,{title:'other actor',allowWorkspaceReuse:true,actor:'different-user'}),false);
 }finally{globalThis.fetch=previousFetch;}
});

test('official success survives local receipt-write failure and a reload resumes a previously saved publication intent',async()=>{
 const previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;
 try{
  const failedSave=await publicationHarness({failReceiptWrite:true});assert.equal((await publish(failedSave)).id,'official-receipt');
  assert.equal(failedSave.s.getState().currentResult.publication.officialReceipt.id,'official-receipt');assert.match(failedSave.s.getState().currentResult.publication.recoveryError,/已成功入库/);assert.equal(failedSave.s.getState().resultError,'');
  const h=await publicationHarness({failure:'publish'});assert.equal(await publish(h),false);
  const {s}=await isolatedStore(h.db);assert.equal(s.getState().currentResult,null);assert.equal(s.getState().previewUrl,'');
  h.control.failure='';s.configureStudio({api:h.api,session:()=>({actor:'publisher'}),csrf:()=> 'publication-csrf'});
  assert.equal((await s.publishCurrentResult(h.record.id,{title:'ignored replacement',allowWorkspaceReuse:true,actor:'publisher'})).id,'official-receipt');
  assert.equal(h.calls.filter(c=>c.path.endsWith('/uploads')).length,1);assert.equal(h.calls.filter(c=>c.path.endsWith('/import')).length,1);assert.equal(h.calls.filter(c=>c.path.endsWith('/publish')).length,2);
 }finally{globalThis.fetch=previousFetch;}
});

test('result actions keep the requested order, require explicit sharing, allow download while publishing and link the actual receipt',async()=>{
 const saved=structuredClone(store.getState()),previousFetch=globalThis.fetch,downloads=[],navigations=[];
 const clickOriginal=Element.prototype.click;Element.prototype.click=function(...args){if(this.tagName==='A'&&this.download){downloads.push({url:this.href,name:this.download});return;}return clickOriginal.apply(this,args);};
 globalThis.fetch=nativeFetch;const record=publicationRecord('ui-managed');
 const root=doc.createElement('main');doc.body.append(root);let writes=0,release;
 const pending=new Promise(resolve=>release=resolve);
 const uiCtx={...ctx,navigate:(...args)=>navigations.push(args),session:()=>({actor:'publisher',csrf:'csrf'}),api:async(path,opts={})=>{
  if(path.endsWith('/auth/status'))return {};
  if(path.endsWith('/capabilities'))return {can_publish:true};
  writes++;if(path.endsWith('/uploads')){await pending;return {staged_upload:'ui-upload'};}
  if(path.endsWith('/import'))return {entry_id:entryId,version_id:versionId};
  if(path.endsWith('/publish'))return {id:'ui-official',entry_id:entryId,library_version_id:versionId};
  throw new Error(path);
 }};
 const studio=createCharacterStudio(root,uiCtx);
 try{
  Object.assign(store.getState(),{currentResult:record,previewUrl:record.imageUrl,history:[record],resultError:'',isGenerating:false,publicationTask:null,hydrated:true});
  await studio.load();await flush();
  assert.deepEqual(root.querySelector('.cs-result-actions').querySelectorAll('button').map(n=>n.textContent),['删除','放入官方资产库','下载']);
  await click(root,'放入官方资产库');const dialog=doc.body.querySelector('.cs-publication');assert.ok(dialog.open);assert.equal(writes,0);
  const confirm=button(dialog,'确认入库'),checkbox=dialog.querySelectorAll('input').find(n=>n.type==='checkbox');assert.equal(checkbox.checked,false);assert.equal(confirm.disabled,true);
  checkbox.checked=true;checkbox.onchange();const publishing=confirm.onclick();await flush();
  assert.equal(root.querySelectorAll('button').find(n=>n.dataset.busyKey==='result-delete').disabled,true);
  assert.equal(root.querySelector('.cs-generate').disabled,true);await click(root,'下载');assert.equal(downloads.at(-1).url,record.imageUrl);assert.match(downloads.at(-1).name,/\.webp$/);
  release();await publishing;await flush();assert.equal(button(root,'已入官方资产库').disabled,true);
  const link=root.querySelector('.cs-result-official');await link.onclick({preventDefault(){}});assert.deepEqual(navigations.at(-1),['asset-center',{tab:'official',kind:'character',entry:entryId}]);
  assert.equal(writes,3);
 }finally{studio.suspend();root.remove();Object.assign(store.getState(),saved);Element.prototype.click=clickOriginal;globalThis.fetch=previousFetch;globalThis.indexedDB=mainDb.api;}
});

test('result delete cancellation and publication cancellation preserve bytes, while empty and generating states expose no usable actions',async()=>{
 const saved=structuredClone(store.getState()),previousConfirm=globalThis.confirm,record=publicationRecord('cancel-result'),requests=[];
 const root=doc.createElement('main');doc.body.append(root);
 const studio=createCharacterStudio(root,{...ctx,session:()=>({actor:'publisher',csrf:'csrf'}),api:async path=>{requests.push(path);return path.endsWith('/capabilities')?{can_publish:true}:{};}});
 try{
  Object.assign(store.getState(),{currentResult:record,previewUrl:record.imageUrl,history:[record],resultError:'',isGenerating:false,publicationTask:null,hydrated:true});
  await studio.load();await flush();let confirmText='';globalThis.confirm=text=>{confirmText=text;return false;};
  await click(root,'删除');assert.match(confirmText,/本地合成记录/);assert.match(confirmText,/不影响已发布的官方资产和项目引用/);assert.equal(store.getState().currentResult.id,record.id);
  button(root,'放入官方资产库').focus();await click(root,'放入官方资产库');const dialog=doc.body.querySelector('.cs-publication');assert.ok(dialog);await click(dialog,'取消');assert.equal(doc.body.querySelector('.cs-publication'),null);assert.equal(doc.activeElement,button(root,'放入官方资产库'));assert.equal(requests.some(path=>path.includes('/uploads')||path.includes('/import')||path.includes('/publish')),false);
  await click(root,'放入官方资产库');const escapeDialog=doc.body.querySelector('.cs-publication');let prevented=false;await escapeDialog.dispatch('cancel',{preventDefault(){prevented=true;}});assert.equal(prevented,false);escapeDialog.close();assert.equal(doc.activeElement,button(root,'放入官方资产库'));
  store.getState().isGenerating=true;store.setCustomPrompt('trigger render');await flush();assert.match(root.textContent,/上次生成结果/);assert.ok(root.querySelector('.cs-result-actions').querySelectorAll('button').every(n=>n.disabled));
  Object.assign(store.getState(),{currentResult:null,previewUrl:'',isGenerating:false});store.setCustomPrompt('empty render');await flush();assert.equal(root.querySelector('.cs-result-actions'),null);
 }finally{studio.suspend();root.remove();Object.assign(store.getState(),saved);if(previousConfirm===undefined)delete globalThis.confirm;else globalThis.confirm=previousConfirm;}
});

test('late publication errors stay with their original result and never replace a newer result feedback',async()=>{
 const h=await publicationHarness({failure:'publish'}),previousFetch=globalThis.fetch;globalThis.fetch=nativeFetch;let release;
 h.control.hold={path:'/api/v1/asset-center/official/publish',promise:new Promise(resolve=>release=resolve)};
 try{
  const pending=publish(h);while(!h.calls.some(c=>c.path.endsWith('/publish')))await flush();
  const newer=publicationRecord('newer-error-scope');h.s.getState().currentResult=newer;h.s.getState().resultError='newer feedback';h.s.getState().resultErrorId=newer.id;
  release();assert.equal(await pending,false);assert.equal(h.s.getState().currentResult.id,newer.id);assert.equal(h.s.getState().resultError,'newer feedback');assert.equal(h.s.getState().resultErrorId,newer.id);assert.match(h.s.getState().history.find(x=>x.id===h.record.id).publication.lastError,/官方发布响应丢失/);
 }finally{globalThis.fetch=previousFetch;}
});

test('a late permission response cannot open an entry dialog after the studio is left and reopened',async()=>{
 const saved=structuredClone(store.getState()),root=doc.createElement('main'),record=publicationRecord('late-permission');
 doc.body.append(root);let release;
 const studio=createCharacterStudio(root,{...ctx,session:()=>({actor:'publisher',csrf:'csrf'}),api:async path=>{
  if(path.endsWith('/auth/status'))return {};
  if(path.endsWith('/capabilities'))return new Promise(resolve=>{release=()=>resolve({can_publish:true});});
  throw Error('must not write '+path);
 }});
 try{
  Object.assign(store.getState(),{currentResult:record,previewUrl:record.imageUrl,history:[record],isGenerating:false,publicationTask:null,hydrated:true});
  await studio.load();await flush();
  const opening=button(root,'放入官方资产库').onclick();await flush();
  studio.suspend();await studio.load();
  release();await opening;await flush();
  assert.equal(doc.body.querySelector('.cs-publication'),null);
  assert.equal(store.getState().currentResult.id,record.id);
 }finally{studio.suspend();root.remove();Object.assign(store.getState(),saved);}
});

test('inline result bytes upload without a data URL fetch that the application CSP forbids',async()=>{
 const {generatedImageBlob}=await import('../../../src/vsc/interfaces/web/static/character-studio-publication.js');
 const previousFetch=globalThis.fetch;globalThis.fetch=async()=>{throw Error('CSP blocks connect-src data:');};
 try{
  const blob=await generatedImageBlob({imageUrl:'data:image/webp;base64,AAEC/w=='});
  assert.equal(blob.type,'image/webp');assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())],[0,1,2,255]);
  const plain=await generatedImageBlob({imageUrl:'data:image/png,ABC%00'});
  assert.deepEqual([...new Uint8Array(await plain.arrayBuffer())],[65,66,67,0]);
 }finally{globalThis.fetch=previousFetch;}
});
