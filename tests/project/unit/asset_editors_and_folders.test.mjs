import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');

Object.defineProperty(Element.prototype,'isConnected',{
 get(){
  for(let n=this;n;n=n.parentElement)if(n===this.ownerDocument.body)return true;
  return false;
 }
});
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){
 this.open=false;
 for(const fn of this.listeners.get('close')||[])fn();
};

const sessionMap=new Map();
globalThis.sessionStorage={
 getItem:k=>sessionMap.has(k)?sessionMap.get(k):null,
 setItem:(k,v)=>sessionMap.set(String(k),String(v)),
 removeItem:k=>sessionMap.delete(k),
 clear:()=>sessionMap.clear(),
 get length(){return sessionMap.size;},
 key:i=>Array.from(sessionMap.keys())[i]||null,
};
globalThis.localStorage={getItem:()=>null,setItem(){}};
globalThis.location={search:'',href:'',pathname:'/'};
globalThis.history={pushState(_a,_b,u){location.search=u;},replaceState(_a,_b,u){location.search=u;}};

const doc=new Document('');
doc.documentElement=doc.createElement('html');
doc.head=doc.createElement('head');
doc.body.append(doc.head);
globalThis.document=doc;

const {
 attachImageZoomPan,
 buildStoreZip,
 createAssetCenter,
 openAssetImageViewer,
 openAssetLibraryModal,
}=await import('../../../src/vsc/interfaces/web/static/asset-center.js');

const {
 editorCapabilitiesForType,
 encodePcm16Wav,
 createEditorDraftStore,
 mountAssetCards,
 mountAssetEditor,
}=await import('../../../src/vsc/interfaces/web/static/asset-cards.js');

const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(n=12){for(let i=0;i<n;i++)await tick();}
const findBtn=(container,label)=>container.querySelectorAll('button').find(b=>b.textContent.includes(label));

test('editorCapabilitiesForType enforces strict SkyProduction 1..5 feature matrix',()=>{
 const c1=editorCapabilitiesForType(1);
 assert.equal(c1.supportsVoiceBinding,true);
 assert.equal(c1.supportsMultiView,true);
 assert.equal(c1.supportsHeadshot,true);
 assert.equal(c1.isAudio,false);

 const c2=editorCapabilitiesForType(2);
 assert.equal(c2.supportsVoiceBinding,false);
 assert.equal(c2.supportsMultiView,false);
 assert.equal(c2.supportsHeadshot,false);
 assert.equal(c2.isAudio,false);

 const c3=editorCapabilitiesForType(3);
 assert.equal(c3.supportsVoiceBinding,false);
 assert.equal(c3.supportsMultiView,true);
 assert.equal(c3.supportsHeadshot,false);
 assert.equal(c3.isAudio,false);

 const c4=editorCapabilitiesForType(4);
 assert.equal(c4.supportsVoiceBinding,false);
 assert.equal(c4.supportsMultiView,false);
 assert.equal(c4.supportsHeadshot,false);
 assert.equal(c4.isAudio,false);

 const c5=editorCapabilitiesForType(5);
 assert.equal(c5.supportsVoiceBinding,false);
 assert.equal(c5.supportsMultiView,false);
 assert.equal(c5.supportsHeadshot,false);
 assert.equal(c5.isAudio,true);
});

test('encodePcm16Wav trims >5s audio to exact 5.0s PCM16 RIFF WAVE bytes',()=>{
 const rate=8000;
 const sevenSec=new Float32Array(rate*7).fill(0.5);
 const wav=encodePcm16Wav([sevenSec,sevenSec],rate,5);
 const view=new DataView(wav.buffer);
 const ascii=(off,len)=>String.fromCharCode(...wav.slice(off,off+len));
 assert.equal(ascii(0,4),'RIFF');
 assert.equal(ascii(8,4),'WAVE');
 assert.equal(ascii(12,4),'fmt ');
 assert.equal(ascii(36,4),'data');
 const expectedDataBytes=rate*5*2*2;
 assert.equal(view.getUint32(40,true),expectedDataBytes);
 assert.equal(wav.byteLength,44+expectedDataBytes);
});

test('createEditorDraftStore enforces 30-entry LRU and 24h TTL expiry',()=>{
 const backing=new Map();
 const storage={getItem:k=>backing.get(k)||null,setItem:(k,v)=>backing.set(k,v)};
 let clock=1_000_000;
 const store=createEditorDraftStore(storage,'ai-tools-web:character-create-drafts:v1',{
  maxEntries:30,
  ttlMs:86_400_000,
  now:()=>clock,
 });
 for(let i=1;i<=35;i++){
  clock+=10;
  store.put(`k${i}`,{idx:i});
 }
 assert.equal(store.listKeys().length,30);
 assert.equal(store.get('k1'),null);
 assert.deepEqual(store.get('k6'),{idx:6});
 // Accessing k6 promoted it to MRU; adding k36 evicts k7 instead of k6
 clock+=10;
 store.put('k36',{idx:36});
 assert.deepEqual(store.get('k6'),{idx:6});
 assert.equal(store.get('k7'),null);
 // Advance past 24h TTL
 clock+=86_400_100;
 assert.equal(store.listKeys().length,0);
});

test('buildStoreZip produces valid STORE zip with IEEE 802.3 CRC-32',()=>{
 const bytes=buildStoreZip([{name:'hello.txt',bytes:'hello'}]);
 const view=new DataView(bytes.buffer);
 assert.equal(view.getUint32(0,true),0x04034b50);
 assert.equal(view.getUint32(14,true),0x3610a686); // CRC-32("hello")
 const eocdOffset=bytes.byteLength-22;
 assert.equal(view.getUint32(eocdOffset,true),0x06054b50);
 assert.equal(view.getUint16(eocdOffset+8,true),1);
});

test('05A folder cards, breadcrumb drill-down, cross-project drag block & cross-page select-all guard',async()=>{
 sessionMap.clear();
 const notices=[],calls=[];
 let scanFlip=false;
 const root=doc.createElement('section');
 doc.body.append(root);
 const api=async(url,opts={})=>{
  calls.push({url,opts});
  if(url.endsWith('/asset-card-options')){
   return {
    nodes:[],media:[],voices:[],revision:3,
    folders:[{id:'f-hero',title:'主角团',asset_count:2,cover_media_id:null,cover_media_ids:[]}],
   };
  }
  if(url.includes('/asset-cards?')){
   const q=new URLSearchParams(url.split('?')[1]);
   if(q.get('limit')==='100'){
    if(q.get('offset')==='0')return {items:[{id:'a1',name:'主角A',record_kind:'asset',asset_kind:'character',forms:[]}],total:120,next_offset:100,revision:3};
    return {items:[],total:scanFlip?121:120,next_offset:null,revision:3};
   }
   if(q.get('folder_id')==='f-hero'){
    return {
     items:[{id:'a1',name:'主角A',record_kind:'asset',asset_kind:'character',forms:[]}],
     folders:[{id:'f-hero',title:'主角团',asset_count:2,cover_media_id:null,cover_media_ids:[]}],
     current_folder:{id:'f-hero',title:'主角团',asset_count:2},
     total:1,next_offset:null,revision:3,
    };
   }
   return {
    items:[{id:'a1',name:'主角A',record_kind:'asset',asset_kind:'character',forms:[]}],
    folders:[{id:'f-hero',title:'主角团',asset_count:2,cover_media_id:null,cover_media_ids:[]}],
    current_folder:null,
    total:1,next_offset:null,revision:3,
   };
  }
  throw new Error('unexpected '+url);
 };
 const ctx={
  api,
  session:()=>({actor:'u1',csrf:'c1',revision:3}),
  projects:()=>[{id:'p1',name:'测试短剧'}],
  notice:m=>notices.push(String(m)),
  setRevision(){},
  navigate(){},
 };
 const panel=await mountAssetCards(root,ctx,{projectId:'p1'});
 assert.equal(root.querySelectorAll('.asset-folder-card').length,1);
 assert.equal(root.querySelectorAll('.asset-card').length,1);

 // Cross-project drag onto folder must block without API call
 const folderEl=root.querySelector('.asset-folder-card');
 for(const fn of folderEl.listeners.get('drop')||[]){
  await fn({
   preventDefault(){},
   dataTransfer:{getData:()=>JSON.stringify({project_id:'other-project',asset_ids:['a9']})},
  });
 }
 assert.ok(notices.includes('跨项目不支持拖拽移动'));
 assert.equal(calls.some(c=>c.url.endsWith('/folders/move')),false);

 // Drill into folder and verify breadcrumb
 await findBtn(folderEl,'主角团').onclick();
 await settle();
 assert.ok(root.querySelector('.asset-folder-breadcrumb'));
 assert.ok(root.querySelector('.asset-folder-breadcrumb').textContent.includes('主角团'));

 // Return to root, open batch mode, test cross-page total mutation guard
 await findBtn(root,'测试短剧').onclick();
 await settle();
 await findBtn(root,'批量操作').onclick();
 await settle();
 scanFlip=true;
 await findBtn(root,'全选所有页').onclick();
 await settle();
 assert.ok(notices.some(m=>m.includes('列表在扫描期间已变更')));
 panel.suspend();
 root.remove();
});

test('official gallery numbers backup media and retries the original delete request',async()=>{
 const root=doc.createElement('main');doc.body.append(root);const requests=[],notices=[];
 const row={id:'official-gallery',version_id:'primary-version',version:1,title:'Synthetic gallery',source:'official',allowed_purposes:['*'],
  official:{asset_kind:'character'},can_manage_media:true,members:[{member_key:'main',modality:'image',preview_url:'/main.png'}]};
 let gallery=[{...row.members[0],library_version_id:'primary-version',revision:0},
  {member_key:'old',library_version_id:'backup-version-1',modality:'image',preview_url:'/old.png',revision:2},
  {member_key:'older',library_version_id:'backup-version-2',modality:'image',preview_url:'/older.png',revision:0}];
 const ctx={session:()=>({actor:'u1',csrf:'c1'}),notice:m=>notices.push(m),projects:()=>[],api:async(url,init)=>{
  if(url.includes('/official/entries/'))return {...row,gallery};
  if(url.endsWith('/official/media-actions')){const body=JSON.parse(init.body);requests.push(body);if(requests.length===1)throw new Error('temporary connection error');gallery=gallery.filter(m=>m.member_key!==body.payload.member_key);return {revision:3};}
  return {items:[row],total:1,facets:{},next_offset:null};
 }};
 const center=createAssetCenter(root,ctx,{source:'official',embedded:true,workbench:true});await center.load();
 await root.querySelector('.center-preview').onclick();
 let drawer=root.querySelector('.official-detail-drawer');assert.deepEqual(drawer.querySelectorAll('h4').map(n=>n.textContent),['主图','备份图-1','备份图-2']);
 await drawer.querySelectorAll('button').find(b=>b.getAttribute('aria-label')==='删除备份图-1').onclick();
 let confirm=root.querySelector('dialog');await findBtn(confirm,'移入回收站').onclick();assert.ok(notices.includes('temporary connection error'));
 await findBtn(confirm,'移入回收站').onclick();
 assert.equal(requests.length,2);assert.equal(requests[0].payload.command_key,requests[1].payload.command_key);
 assert.equal(requests[1].payload.library_version_id,'backup-version-1');assert.equal(requests[1].payload.expected_revision,2);assert.equal(requests[1].confirmed,true);
 drawer=root.querySelector('.official-detail-drawer');assert.deepEqual(drawer.querySelectorAll('h4').map(n=>n.textContent),['主图','备份图-1']);center.suspend();
});

test('05B official right drawer, 05C review modal .tag-unverified chips & openAssetLibraryModal dblclick',async()=>{
 sessionMap.clear();
 const root=doc.createElement('main');
 doc.body.append(root);
 const api=async url=>{
  if(url.startsWith('/api/v1/asset-center/official/entries/'))return (await api('/api/v1/asset-center?source=official')).items[0];
  if(url.includes('source=official')){
   return {
    items:[{
     id:'off-1',version_id:'ver-off-1',version:1,title:'冷面剑客',source:'official',download_count:18,
     official:{asset_kind:'character',role_level:'lead',age_band:'young_adult',gender:'male',role_tag:'古风侠客'},
     catalog:{asset_kind:'character',form_name:'默认',tags:['剑客'],review_status:'confirmed'},
     allowed_purposes:['*'],
     members:[{member_key:'m1',modality:'image',preview_url:'/sword.png'}],
    }],
    facets:{role_tag:['古风侠客','都市总裁']},
    total:1,next_offset:null,
   };
  }
  if(url.startsWith('/api/v1/asset-center?')){
   return {
    items:[{
     id:'ent-1',version_id:'ver-ent-1',version:1,title:'上古异兽白泽',download_count:42,can_edit_catalog:true,
     catalog:{asset_kind:'other',display_kind:'creature',form_name:'成年体',tags:['异兽','瑞兽'],review_status:'draft',revision:1},
     allowed_purposes:['*'],
     members:[{member_key:'m1',modality:'image',preview_url:'/beast.png'}],
    }],
    total:1,next_offset:null,
   };
  }
  return {items:[],total:0,next_offset:null};
 };
 const ctx={
  api,
  session:()=>({actor:'u1',csrf:'c1',revision:1}),
  projects:()=>[{id:'p1',name:'项目一'}],
  projectId:()=> 'p1',
  notice(){},
  setRevision(){},
 };

 // 05B Official Drawer
 const offCenter=createAssetCenter(root,ctx,{source:'official',embedded:true,workbench:true});
 await offCenter.load();
 await findBtn(root,'冷面剑客').onclick();
 const drawer=root.querySelector('.official-detail-drawer');
 assert.ok(drawer);
 assert.ok(findBtn(drawer,'引用生成'));
 offCenter.suspend();

 // 05C Enterprise Center + Review Modal .tag-unverified
 const entCenter=createAssetCenter(root,ctx,{source:'shared'});
 await entCenter.load();
 assert.ok(root.querySelector('.center-mode-seg'));
 assert.ok(root.querySelector('.asset-cart-fab'));
 await findBtn(root,'打标审核').onclick();
 const modal=root.querySelector('.center-review-modal');
 assert.ok(modal);
 assert.equal(modal.querySelectorAll('.tag-unverified').length,2);
 entCenter.suspend();

 // AssetLibraryModal dblclick immediate resolve
 const modalHost=doc.createElement('div');
 doc.body.append(modalHost);
 const pickPromise=openAssetLibraryModal(ctx,{host:modalHost,projectId:'p1',multiple:false});
 await settle();
 // Switch to official tab and double-click card
 await findBtn(modalHost,'官方资产').onclick();
 await settle();
 const cardNode=modalHost.querySelector('.asset-library-card');
 assert.ok(cardNode);
 cardNode.ondblclick();
 const picked=await pickPromise;
 assert.equal(picked.title,'冷面剑客');
 modalHost.remove();
 root.remove();
});

test('14 mountAssetEditor enforces 1..5 capabilities, headshot 2:1 lock, blur voice save, pic_type=2 block & audio guards',async()=>{
 sessionMap.clear();
 const notices=[],writes=[];
 const root=doc.createElement('section');
 doc.body.append(root);
 const api=async(url,opts={})=>{
  if(url.endsWith('/creative-canvas-run-options'))return {models:[],revision:5};
  if(url.endsWith('/run-scope-options'))return {workspaces:[],budgets:[],revision:5};
  if(opts.method==='POST'){
   const body=JSON.parse(opts.body);
   writes.push({url,body});
   if(url.endsWith('/asset-cards')){
    return {
     id:'char-1',name:body.payload.name,asset_kind:body.payload.asset_kind,revision:6,
     forms:body.payload.forms.map(f=>({...f,version_id:'ver-f1'})),
    };
   }
   if(url.endsWith('/manifestation-voice')){
    return {
     id:'char-1',name:'沈清秋',asset_kind:'character',revision:7,
     forms:[{form_key:'master',name:'默认形态',version_id:'ver-f2',voice_spec_id:'vs-1',voice_prompt:body.payload.voice_prompt}],
    };
   }
  }
  return {revision:5};
 };
 const ctx={
  api,
  session:()=>({actor:'u1',csrf:'c1',revision:5}),
  projects:()=>[{id:'p1',name:'仙侠剧'}],
  projectId:()=> 'p1',
  notice:m=>notices.push(String(m)),
  setRevision(){},
  navigate(){},
 };

 // Type 1: Character editor
 const ed1=await mountAssetEditor(root,ctx,{
  projectId:'p1',
  assetType:1,
  card:{
   id:'char-1',name:'沈清秋',asset_kind:'character',revision:5,
   forms:[{form_key:'master',name:'默认形态',version_id:'ver-f1',media_id:'m-local',description:'青衣剑修'}],
  }
 });
 assert.ok(root.querySelector('.reference-voice-section'));
 assert.ok(root.querySelector('.editor-left-scroll'));
 assert.ok(root.querySelector('.editor-quota-details'));
 assert.equal(root.textContent.includes('pic_type=2'),false);
 assert.ok(root.textContent.includes('多视图'));
 assert.ok(root.textContent.includes('大头照'));

 // Blur voice prompt auto-saves with manifestaion_id compatibility field
 const vp=root.querySelector('.editor-voice-prompt');
 vp.value='清冷公子音';
 vp.oninput();
 await vp.onblur();
 const voiceCall=writes.find(w=>w.url.endsWith('/manifestation-voice'));
 assert.ok(voiceCall);
 assert.equal(voiceCall.body.payload.manifestaion_id,'ver-f1');
 assert.equal(voiceCall.body.payload.voice_prompt,'清冷公子音');

 // Toggle headshot ON -> locks 2:1 & hides aspect select
 const checks=root.querySelectorAll('input').filter(i=>i.type==='checkbox');
 const headshotCheck=checks[1];
 headshotCheck.checked=true;
 headshotCheck.onchange();
 assert.ok(root.querySelector('.editor-locked-aspect'));
 assert.equal(root.querySelector('.editor-aspect-select').hidden,true);

 // Simulate local-upload candidate (pic_type=2) reuse block
 ed1.suspend();

 // Type 2 (Location): no voice, no multiview, no headshot
 const ed2=await mountAssetEditor(root,ctx,{projectId:'p1',assetType:2,initialName:'竹林小筑'});
 assert.equal(root.querySelector('.reference-voice-section'),null);
 assert.equal(root.textContent.includes('多视图'),false);
 assert.equal(root.textContent.includes('大头照'),false);
 ed2.suspend();

 // Type 3 (Prop): multiview YES, voice NO, headshot NO
 const ed3=await mountAssetEditor(root,ctx,{projectId:'p1',assetType:3,initialName:'修雅剑'});
 assert.equal(root.querySelector('.reference-voice-section'),null);
 assert.equal(root.textContent.includes('多视图'),true);
 assert.equal(root.textContent.includes('大头照'),false);
 // Add a pic_type=2 candidate via draft store and verify reuse block
 ed3.suspend();
 const draftStore=createEditorDraftStore(globalThis.sessionStorage);
 draftStore.put('p1:new:1',{
  assetId:null,baseRevision:0,name:'测试角色',assetKind:'character',activeFormKey:'master',
  modelId:'',aspect:'1024,1024',count:1,multiView:false,headshot:false,
  forms:[{form_key:'master',name:'默认形态',base_version_id:null,description:'',media_id:'m2',refs:[],candidates:[{id:'c-local',media_id:'m2',name:'本地图',pic_type:2}]}],
 });
 const edLocal=await mountAssetEditor(root,ctx,{projectId:'p1',assetType:1});
 await findBtn(root,'复用配置').onclick();
 assert.ok(notices.includes('本地上传图片无生成配置可复用'));
 edLocal.suspend();

 // Type 5 (Audio): minimum 1 group guard & selected audio non-deletable/non-unselectable
 const ed5=await mountAssetEditor(root,ctx,{
  projectId:'p1',
  assetType:5,
  card:{
   id:'aud-1',name:'主角独白',asset_kind:'voice',revision:5,
   forms:[{form_key:'master',name:'默认分组',version_id:'vf-a1',media_id:'m-aud-1',description:'旁白'}],
  }
 });
 assert.ok(root.querySelector('.asset-audio-generate-content'));
 const groupDel=root.querySelector('.editor-tag-del');
 assert.equal(groupDel.disabled,true);
 const selectedUseBtn=findBtn(root,'已选用');
 assert.equal(selectedUseBtn.disabled,true);
 const audioDelBtn=root.querySelector('.audio-delete-btn');
 assert.equal(audioDelBtn.disabled,true);
 ed5.suspend();
 root.remove();
});

test('05B official asset image viewer fits viewport, zooms in/out below 100%, preserves wheel scroll & pans via vertical/horizontal drag',async()=>{
 const root=doc.createElement('section');
 doc.body.append(root);
 const api=async url=>{
  if(url.startsWith('/api/v1/asset-center/official/entries/'))return (await api('/api/v1/asset-center?source=official')).items[0];
  if(url.startsWith('/api/v1/asset-center?')&&url.includes('source=official')){
   return {
    items:[{
     id:'off-tall-1',version_id:'ver-tall-1',version:1,title:'竖幅全身侠女',source:'official',
     official:{asset_kind:'character',role_level:'lead',gender:'female',age_band:'young_adult'},
     catalog:{asset_kind:'character',form_name:'全身立绘',tags:['古风']},
     allowed_purposes:['*'],
     members:[{member_key:'full',modality:'image',preview_url:'/tall-heroine.png',width:1024,height:1820}],
    }],
    total:1,next_offset:null,
   };
  }
  return {items:[],total:0,next_offset:null};
 };
 const ctx={
  api,
  session:()=>({actor:'u1',csrf:'c1',revision:1}),
  projects:()=>[],
  notice(){},
  setRevision(){},
 };
 const offCenter=createAssetCenter(root,ctx,{source:'official',embedded:true,workbench:true});
 await offCenter.load();

 // Click cover preview button on ?page=asset-center&tab=official
 const previewBtn=root.querySelector('.center-preview');
 assert.ok(previewBtn,'official card should render .center-preview button');
 await previewBtn.onclick();
 assert.ok(root.querySelector('.official-detail-drawer'),'clicking official image opens its media details');
 await root.querySelector('.official-drawer-preview').onclick();

 const zoomDialog=[...doc.body.querySelectorAll('dialog')].find(d=>d.className.includes('center-zoom'));
 assert.ok(zoomDialog,'clicking official asset image opens dialog.center-zoom');
 const viewport=zoomDialog.querySelector('.center-zoom-viewport');
 const img=viewport.querySelector('img');
 const level=zoomDialog.querySelector('.center-zoom-level');
 assert.ok(viewport&&img&&level);

 // 1. Initial fit-to-screen size (1024x1820 tall portrait fits inside 856x576 stage without overflowing)
 assert.equal(level.textContent,'100%');
 const readDim=(node,prop)=>parseInt(node.style?.[prop]||node.getAttribute('style')?.match(new RegExp(`${prop}:(\\d+)px`))?.[1]||'0',10);
 const fitW=readDim(img,'width');
 const fitH=readDim(img,'height');
 assert.ok(fitH<=576&&fitH>=300,`expected initial fit height <= 576px, got ${fitH}`);
 assert.ok(fitW<fitH,`portrait ratio should be preserved (${fitW}x${fitH})`);
 assert.equal(img.draggable,false);

 // 2. Zoom in (+25% -> 125%, +25% -> 150%) increases real layout width/height
 await findBtn(zoomDialog,'放大').onclick();
 assert.equal(level.textContent,'125%');
 await findBtn(zoomDialog,'放大').onclick();
 assert.equal(level.textContent,'150%');
 const zoomedH=readDim(img,'height');
 assert.equal(zoomedH,Math.round(fitH*1.5));

 // 3. Zoom out works both back to 100% AND below 100% (75%)
 await findBtn(zoomDialog,'适应窗口').onclick();
 assert.equal(level.textContent,'100%');
 await findBtn(zoomDialog,'缩小').onclick();
 assert.equal(level.textContent,'75%');
 const shrunkH=readDim(img,'height');
 assert.equal(shrunkH,Math.round(fitH*0.75));

 // 4. Normal wheel event does NOT call preventDefault() (native vertical scroll works!), while Ctrl+wheel zooms
 let wheelPrevented=false;
 await viewport.dispatch('wheel',{deltaY:120,ctrlKey:false,metaKey:false,preventDefault(){wheelPrevented=true;}});
 assert.equal(wheelPrevented,false,'normal wheel scroll must not preventDefault');
 assert.equal(level.textContent,'75%');
 await viewport.dispatch('wheel',{deltaY:-120,ctrlKey:true,metaKey:false,preventDefault(){wheelPrevented=true;}});
 assert.equal(wheelPrevented,true,'Ctrl+wheel pinch zoom should preventDefault');
 assert.equal(level.textContent,'100%');

 // 5. Zoom in to 200% and drag up/down & left/right to view obscured top/bottom regions
 await findBtn(zoomDialog,'放大').onclick();
 await findBtn(zoomDialog,'放大').onclick();
 await findBtn(zoomDialog,'放大').onclick();
 await findBtn(zoomDialog,'放大').onclick();
 assert.equal(level.textContent,'200%');
 viewport.scrollTop=40;
 viewport.scrollLeft=20;
 await viewport.dispatch('pointerdown',{button:0,pointerId:1,clientX:300,clientY:400});
 assert.ok(viewport.className.includes('is-dragging'));
 // Drag pointer upward by 150px (clientY: 400 -> 250) -> pulls lower part of tall image into view (scrollTop increases by 150)
 await viewport.dispatch('pointermove',{pointerId:1,clientX:260,clientY:250,preventDefault(){}});
 assert.equal(viewport.scrollTop,190);
 assert.equal(viewport.scrollLeft,60);
 // Drag pointer downward by 110px (clientY: 400 -> 290, net dy=-110 -> scrollTop=150)
 await viewport.dispatch('pointermove',{pointerId:1,clientX:280,clientY:290,preventDefault(){}});
 assert.equal(viewport.scrollTop,150);
 assert.equal(viewport.scrollLeft,40);
 await viewport.dispatch('pointerup',{pointerId:1});
 assert.equal(viewport.className.includes('is-dragging'),false);

 findBtn(zoomDialog,'关闭').onclick();
 assert.equal(zoomDialog.isConnected,false);
 offCenter.suspend();
 root.remove();
});
