import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
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
test('history commits before success, restores on reload, and keeps old history on failed save/delete/clear',async()=>{
 const db=database(),{s,notes}=await isolatedStore(db);let requests=0;
 s.setSlot('portrait',{...portrait,source:'upload',原图:image,缩略图:image});await flush();
 globalThis.fetch=async()=>{requests++;return {ok:true,json:async()=>({image_url:image,model:'synthetic'})};};
 await s.startGeneration();assert.equal(requests,1);assert.equal(db.values.get('pose_atlas_history_v3').length,1);assert.equal(notes.at(-1),'角色图已完成并保存');
 assert.equal((await isolatedStore(db)).s.getState().history.length,1);
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
   await click(root,'下载 PNG');assert.equal(downloads.at(-1),result);
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
