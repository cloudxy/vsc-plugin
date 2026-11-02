// Actual asset-center module with controlled DOM and HTTP responses. No browser claim.
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
const {Document,Element}=require('./panel_dom.cjs');
Object.defineProperty(Element.prototype,'isConnected',{get(){for(let n=this;n;n=n.parentElement)if(n===this.ownerDocument.body)return true;return false;}});
Element.prototype.showModal=function(){this.open=true;};Element.prototype.close=function(){this.open=false;for(const fn of this.listeners.get('close')||[])fn();};
const store=new Map();globalThis.sessionStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};globalThis.localStorage={getItem:()=>null,setItem(){}};globalThis.crypto=require('node:crypto').webcrypto;
const doc=new Document('');doc.documentElement=doc.createElement('html');globalThis.document=doc;
const fixture={id:'entry-fixed',version_id:'version-fixed',version:1,title:'用户保存的司机',description:'原始中文说明',catalog:{asset_kind:'character',form_name:'青年',tags:['司机'],review_status:'draft'},allowed_purposes:['identity_face','reference_image'],license:{evidence:'synthetic'},members:[{member_key:'front',modality:'image',preview_url:'/fixed.png',width:2,height:2}]};
const clone=x=>JSON.parse(JSON.stringify(x)),requests=[],writes=[],notices=[];let importFailure='lost',canvasFailure=true,deferredCart=null,deferredSearch=null;
const api=async(url,options={})=>{requests.push(url);
 if(url.startsWith('/api/v1/asset-center?')){if(deferredSearch){const held=deferredSearch;deferredSearch=null;return held;}return {items:[clone(fixture)],total:1,next_offset:null};}
 if(url.endsWith('/tree'))return {revision:6,nodes:[{id:'shot-fixed',kind:'shot',title:'原镜头'}]};
 if(url==='/api/v1/asset-center/cart'){if(deferredCart){const held=deferredCart;deferredCart=null;return held;}return {id:'cart-fixed',active:true};}
 if(url.endsWith('/asset-center/import')){const body=JSON.parse(options.body);writes.push({type:'import',body});if(importFailure){const mode=importFailure;importFailure=null;const e=new Error(mode);if(mode==='auth'){e.status=401;e.code='authentication_required';}throw e;}return {media_id:'media-fixed',target_object_id:'asset-fixed',revision:7};}
 if(url.endsWith('/creative-canvases')){const body=JSON.parse(options.body);writes.push({type:'canvas',body});if(canvasFailure){canvasFailure=false;throw new Error('lost canvas receipt');}return {id:'canvas-fixed',revision:8};}
 throw new Error('unexpected request '+url);
};
const root=doc.createElement('main');doc.body.append(root);
const find=(container,text)=>container.querySelectorAll('button').find(n=>n.textContent===text&&!n.hidden);
const click=async(container,text)=>{const node=find(container,text);assert.ok(node,'missing button '+text);assert.ok(!node.disabled,'disabled button '+text);await node.onclick();};
const currentDialog=()=>root.querySelectorAll('dialog').at(-1);
const field=(dialog,label)=>dialog.querySelectorAll('select').find(n=>n.getAttribute('aria-label')===label);
(async()=>{
 const {createAssetCenter}=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/asset-center.js')));
 const i=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/i18n.js')));
 const center=createAssetCenter(root,{api,notice:m=>notices.push(String(m)),session:()=>({actor:'actor-fixed',csrf:'csrf'}),projects:()=>[{id:'project-fixed',name:'用户中文项目'},{id:'read-only',name:'只读',read_only:true}],projectId:()=> 'project-fixed',setRevision:()=>{}});
 await center.load();assert.ok(requests[0].includes('media_only=true'));assert.equal(root.querySelectorAll('article').length,1);assert.ok(root.textContent.includes('1 个媒体资产'));assert.equal(root.querySelector('img').src,'/fixed.png');
 await click(root,'添加到项目');let d=currentDialog();assert.deepEqual(field(d,'目标项目').options.map(n=>n.value),['','project-fixed']);await click(d,'添加到项目');const key='vsc-center-single:actor-fixed',first=JSON.parse(store.get(key));assert.equal(first.project,'project-fixed');assert.ok(first.request.idempotency_key);assert.ok(d.textContent.includes('lost'));
 const saved=store.get(key),projectControl=field(d,'目标项目'),kindControl=field(d,'添加位置');i.setLocale('en');assert.equal(projectControl.value,'project-fixed');assert.equal(kindControl.value,'character');assert.equal(store.get(key),saved);assert.ok(d.textContent.includes('用户保存的司机'));
 // A query/credential problem must not erase an unknown original write.
 importFailure='auth';await click(d,'Resume original request');assert.deepEqual(JSON.parse(store.get(key)).request,first.request);assert.deepEqual(writes[1].body,writes[0].body);
 d.close();await center.load();await click(root,'Resume unfinished import or reference creation');d=currentDialog();await click(d,'Resume original request');assert.deepEqual(writes[2].body,writes[0].body);assert.equal(store.has(key),false);assert.ok(d.querySelector('a').href.includes('project=project-fixed'));assert.ok(find(d,'Completed').disabled);d.close();
 i.setLocale('zh-cn');await center.load();await click(root,'参考新建');d=currentDialog();await click(d,'参考新建');const pendingCanvas=JSON.parse(store.get(key));assert.equal(pendingCanvas.result.media_id,'media-fixed');assert.equal(pendingCanvas.canvas_request.payload.document.nodes[0].media_id,'media-fixed');assert.equal(pendingCanvas.canvas_request.payload.document.nodes[1].text,'');const countImports=writes.filter(r=>r.type==='import').length;d.close();await center.load();await click(root,'继续未完成的添加或参考新建');d=currentDialog();await click(d,'继续原请求');assert.equal(writes.filter(r=>r.type==='import').length,countImports);const canvases=writes.filter(r=>r.type==='canvas');assert.deepEqual(canvases[0].body,canvases[1].body);assert.ok(d.querySelectorAll('a').some(a=>a.href.includes('task_target=canvas-fixed')));assert.equal(store.has(key),false);d.close();
 // Disposal while cart returns may retain its result but cannot issue another write.
 let release;deferredCart=new Promise(resolve=>{release=resolve;});await center.load();await click(root,'添加到项目');d=currentDialog();const countBefore=writes.length,running=find(d,'添加到项目').onclick();center.suspend();release({id:'cart-fixed',active:true});await running;assert.equal(writes.length,countBefore);assert.equal(JSON.parse(store.get(key)).cart,'cart-fixed');
 // Late gallery reads never replace a newer surface.
 let resolveSearch;deferredSearch=new Promise(resolve=>{resolveSearch=resolve;});const stale=center.load();await center.load();resolveSearch({items:[],total:99,next_offset:null});await stale;assert.ok(root.textContent.includes('1 个媒体资产'));assert.ok(!root.textContent.includes('99 个媒体资产'));
 console.log('asset gallery DOM PASS: media default, fixed import/canvas recovery, 401 retention, scope and locale');
})().catch(e=>{console.error(e);process.exitCode=1;});
