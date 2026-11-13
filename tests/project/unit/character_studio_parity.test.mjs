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
globalThis.indexedDB=database().api;
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
async function gallery(kind){
 globalThis.location={search:'?kind='+kind};
 const root=doc.createElement('main');doc.body.append(root);
 const center=createAssetCenter(root,ctx,{source:'official',workbench:true});await center.load();await flush();
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

async function comparison(result){
 store.getState().history=[result];
 const root=doc.createElement('main');doc.body.append(root);
 const studio=createCharacterStudio(root,ctx);await studio.load();await flush();
 const trigger=button(root,'对比参考');trigger.focus();await trigger.onclick();
 return {root,studio,trigger,dialog:doc.body.querySelector('.cs-compare')};
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
