import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
import * as studio from './character-studio-store.js';
import {createCharacterHistory} from './character-studio-history.js';
import {referenceImageUrl,localCostumeImageUrl,poseThumbPath,poseImagePath,selectCostumeView} from './character-studio-ai.js';
/* Catalog metadata and personal selections reference the original library. */
const el=(tag,text='',cls='')=>{const n=document.createElement(tag);if(text!==null&&text!==undefined)setText(n,text);if(cls)n.className=cls;return n;};
const kinds=[
 ['character',msg('gallery.character')],
 ['location',msg('gallery.location')],
 ['prop',msg('gallery.prop')],
 ['blocking',msg('gallery.blocking')],
 ['voice',msg('gallery.voice')],
 ['creature','生物/异兽'],
 ['other',msg('gallery.other')],
];
const officialWorkbenchKinds=[
 ['','全部'],
 ['character','人设'],
 ['location','场景'],
 ['prop','道具'],
 ['voice','音频'],
 ['costume','服装穿搭库'],
 ['pose','动作姿势库'],
 ['portrait','人像颜值库'],
 ['composite','AI角色合成库'],
];
const officialSelectKinds=[
 ['character','人设'],
 ['location',msg('asset.scene')],
 ['prop',msg('asset.prop')],
 ['voice','音频'],
 ['costume','服装穿搭库'],
 ['pose','动作姿势库'],
 ['portrait','人像颜值库'],
];
const roles={character:'identity_face',location:'location_master',prop:'prop',voice:'voice_sample',creature:'prop'};
const MAX_CART_ITEMS=200;

function setStyle(node,prop,val){
 if(!node)return;
 if(node.style&&typeof node.style==='object'){
  node.style[prop]=val;
  return;
 }
 const kebab=prop.replace(/[A-Z]/g,m=>'-'+m.toLowerCase());
 const raw=String(node.attributes?.style||node.getAttribute?.('style')||'');
 const parts=raw.split(';').map(s=>s.trim()).filter(s=>s&&!s.startsWith(kebab+':'));
 if(val!==''&&val!==null&&val!==undefined)parts.push(`${kebab}:${val}`);
 node.setAttribute?.('style',parts.join(';'));
}

export function attachImageZoomPan(viewport,img,{
 minScale=0.25,
 maxScale=4,
 step=0.25,
 initialWidth=0,
 initialHeight=0,
 onScaleChange=null,
}={}){
 let scale=1,fitW=0,fitH=0,drag=null,movedRecently=false;
 if(img){
  img.draggable=false;
  img.setAttribute?.('draggable','false');
 }
 if(viewport){
  if(typeof viewport.scrollLeft!=='number')viewport.scrollLeft=0;
  if(typeof viewport.scrollTop!=='number')viewport.scrollTop=0;
 }
 function measureFit(){
  const availW=Math.max(200,(Number(viewport?.clientWidth)||880)-24);
  const availH=Math.max(200,(Number(viewport?.clientHeight)||600)-24);
  const natW=Math.max(1,Number(img?.naturalWidth)||Number(initialWidth)||720);
  const natH=Math.max(1,Number(img?.naturalHeight)||Number(initialHeight)||720);
  let ratio=Math.min(availW/natW,availH/natH,1);
  const minDisplay=Math.min(360,availW,availH);
  if(natW*ratio<minDisplay&&natH*ratio<minDisplay){
   ratio=Math.min(availW/natW,availH/natH,minDisplay/Math.max(natW,natH));
  }
  fitW=Math.max(48,Math.round(natW*ratio));
  fitH=Math.max(48,Math.round(natH*ratio));
 }
 function emit(targetW,targetH){
  onScaleChange?.({
   scale,
   percent:Math.round(scale*100),
   width:targetW,
   height:targetH,
   canZoomIn:scale<maxScale-1e-6,
   canZoomOut:scale>minScale+1e-6,
  });
 }
 function applyScale(nextScale,focusX=null,focusY=null){
  if(!fitW||!fitH)measureFit();
  const clamped=Math.min(maxScale,Math.max(minScale,Math.round(Number(nextScale)*100)/100));
  const prev=scale;
  scale=clamped;
  const targetW=Math.max(24,Math.round(fitW*scale));
  const targetH=Math.max(24,Math.round(fitH*scale));
  setStyle(img,'width',`${targetW}px`);
  setStyle(img,'height',`${targetH}px`);
  setStyle(img,'maxWidth','none');
  setStyle(img,'maxHeight','none');
  if(img?.dataset)img.dataset.zoomScale=String(scale);
  img?.setAttribute?.('data-zoom-scale',String(scale));
  if(viewport&&prev>0&&prev!==scale){
   const ratio=scale/prev;
   const cx=focusX??((Number(viewport.clientWidth)||880)/2);
   const cy=focusY??((Number(viewport.clientHeight)||600)/2);
   viewport.scrollLeft=Math.max(0,Math.round(((Number(viewport.scrollLeft)||0)+cx)*ratio-cx));
   viewport.scrollTop=Math.max(0,Math.round(((Number(viewport.scrollTop)||0)+cy)*ratio-cy));
  }
  emit(targetW,targetH);
  return scale;
 }
 function reset(){
  measureFit();
  scale=1;
  setStyle(img,'width',`${fitW}px`);
  setStyle(img,'height',`${fitH}px`);
  setStyle(img,'maxWidth','none');
  setStyle(img,'maxHeight','none');
  if(img?.dataset)img.dataset.zoomScale='1';
  img?.setAttribute?.('data-zoom-scale','1');
  if(viewport){
   viewport.scrollLeft=0;
   viewport.scrollTop=0;
  }
  emit(fitW,fitH);
  return scale;
 }
 function zoomNatural(){
  measureFit();
  const natW=Math.max(1,Number(img?.naturalWidth)||Number(initialWidth)||fitW);
  return applyScale(natW/Math.max(1,fitW));
 }
 img?.addEventListener?.('load',()=>{
  if(scale===1)reset();
  else{measureFit();applyScale(scale);}
 });
 img?.addEventListener?.('dblclick',event=>{
  event?.preventDefault?.();
  applyScale(scale>1.05?1:2,event?.offsetX??null,event?.offsetY??null);
 });
 viewport?.addEventListener?.('wheel',event=>{
  if(event?.ctrlKey||event?.metaKey){
   event.preventDefault?.();
   applyScale(scale+(Number(event.deltaY)<0?step:-step),event.offsetX??null,event.offsetY??null);
  }
  // Normal wheel/trackpad scroll intentionally does NOT call preventDefault(),
  // allowing vertical & horizontal scrolling when the image overflows.
 },{passive:false});
 viewport?.addEventListener?.('pointerdown',event=>{
  if(event?.button!=null&&event.button!==0)return;
  drag={
   pointerId:event?.pointerId,
   startX:Number(event?.clientX)||0,
   startY:Number(event?.clientY)||0,
   startLeft:Number(viewport.scrollLeft)||0,
   startTop:Number(viewport.scrollTop)||0,
   moved:false,
  };
  movedRecently=false;
  viewport.className=String(viewport.className||'').replace(/\bis-dragging\b/g,'').trim()+' is-dragging';
  try{viewport.setPointerCapture?.(event?.pointerId);}catch{}
 });
 viewport?.addEventListener?.('pointermove',event=>{
  if(!drag)return;
  if(drag.pointerId!==undefined&&event?.pointerId!==undefined&&event.pointerId!==drag.pointerId)return;
  const dx=(Number(event?.clientX)||0)-drag.startX;
  const dy=(Number(event?.clientY)||0)-drag.startY;
  if(Math.abs(dx)>3||Math.abs(dy)>3)drag.moved=true;
  viewport.scrollLeft=Math.max(0,drag.startLeft-dx);
  viewport.scrollTop=Math.max(0,drag.startTop-dy);
  if(drag.moved)event?.preventDefault?.();
 });
 const finishDrag=event=>{
  if(!drag)return;
  movedRecently=drag.moved;
  if(event?.pointerId!==undefined){
   try{viewport.releasePointerCapture?.(event.pointerId);}catch{}
  }
  drag=null;
  viewport.className=String(viewport.className||'').replace(/\bis-dragging\b/g,'').trim();
 };
 viewport?.addEventListener?.('pointerup',finishDrag);
 viewport?.addEventListener?.('pointercancel',finishDrag);
 reset();
 return {
  zoomIn:()=>applyScale(scale+step),
  zoomOut:()=>applyScale(scale-step),
  reset,
  zoomNatural,
  setScale:s=>applyScale(s),
  getScale:()=>scale,
  consumeMoved:()=>{const m=movedRecently;movedRecently=false;return m;},
 };
}

export function openAssetImageViewer({title='',src='',member=null,host=null,imgNode=null}={}){
 const dialog=el('dialog','','center-zoom');
 bindAttribute(dialog,'aria-label',(title||'资产图片')+' 预览');
 const head=el('div','','center-zoom-head');
 const titleEl=el('h3',title||'查看图片','center-zoom-title');
 const hintEl=el('span','滚轮或按住上下拖动查看全图 · 双击快速缩放','center-zoom-hint');
 const closeTop=el('button','×','center-zoom-close');
 closeTop.type='button';
 bindAttribute(closeTop,'aria-label','关闭预览');
 closeTop.onclick=()=>dialog.close();
 head.append(titleEl,hintEl,closeTop);

 const viewport=el('div','','center-zoom-viewport');
 const img=imgNode||el('img');
 if(!imgNode){
  img.src=src||member?.preview_url||'';
  bindAttribute(img,'alt',title||msg('ui.fixed_shared_media_version'));
 }
 viewport.append(img);

 const bar=el('div','','center-zoom-bar');
 const outBtn=el('button','缩小');outBtn.type='button';
 const levelEl=el('span','100%','center-zoom-level');
 levelEl.setAttribute('role','status');
 const fitBtn=el('button','适应窗口');fitBtn.type='button';
 const inBtn=el('button','放大');inBtn.type='button';
 const rawBtn=el('button','原始大小');rawBtn.type='button';
 const closeBtn=el('button','关闭');closeBtn.type='button';

 const ctrl=attachImageZoomPan(viewport,img,{
  initialWidth:member?.width||0,
  initialHeight:member?.height||0,
  onScaleChange:({percent,canZoomIn,canZoomOut})=>{
   setText(levelEl,`${percent}%`);
   inBtn.disabled=!canZoomIn;
   outBtn.disabled=!canZoomOut;
  },
 });
 outBtn.onclick=()=>ctrl.zoomOut();
 fitBtn.onclick=()=>ctrl.reset();
 inBtn.onclick=()=>ctrl.zoomIn();
 rawBtn.onclick=()=>ctrl.zoomNatural();
 closeBtn.onclick=()=>dialog.close();
 bar.append(outBtn,levelEl,fitBtn,inBtn,rawBtn,closeBtn);

 dialog.append(head,viewport,bar);
 dialog.addEventListener('keydown',event=>{
  if(event.key==='+'||event.key==='='){event.preventDefault?.();ctrl.zoomIn();}
  else if(event.key==='-'){event.preventDefault?.();ctrl.zoomOut();}
  else if(event.key==='0'){event.preventDefault?.();ctrl.reset();}
  else if(event.key==='ArrowDown'){event.preventDefault?.();viewport.scrollTop=(Number(viewport.scrollTop)||0)+80;}
  else if(event.key==='ArrowUp'){event.preventDefault?.();viewport.scrollTop=Math.max(0,(Number(viewport.scrollTop)||0)-80);}
 });
 dialog.addEventListener('click',event=>{
  if(ctrl.consumeMoved())return;
  if(event.target===dialog)dialog.close();
 });
 dialog.addEventListener('close',()=>dialog.remove());
 (host||document.body||document.documentElement).append(dialog);
 dialog.showModal?.();
 requestAnimationFrame?.(()=>ctrl.reset());
 return {dialog,viewport,img,ctrl};
}

const CRC_TABLE=(()=>{
 const table=new Uint32Array(256);
 for(let i=0;i<256;i++){
  let c=i;
  for(let k=0;k<8;k++)c=(c&1)?(0xedb88320^(c>>>1)):(c>>>1);
  table[i]=c>>>0;
 }
 return table;
})();

function crc32(bytes){
 let c=0xffffffff;
 for(let i=0;i<bytes.length;i++)c=CRC_TABLE[(c^bytes[i])&0xff]^(c>>>8);
 return (c^0xffffffff)>>>0;
}

export function buildStoreZip(entries){
 const encoder=new TextEncoder();
 const normalized=(entries||[]).map((entry,idx)=>{
  const rawName=String(entry?.name||`asset-${idx+1}.bin`).replace(/[\\/]+/g,'_');
  const nameBytes=encoder.encode(rawName);
  let data=entry?.bytes||new Uint8Array(0);
  if(typeof data==='string')data=encoder.encode(data);
  else if(data instanceof ArrayBuffer)data=new Uint8Array(data);
  else if(!(data instanceof Uint8Array))data=new Uint8Array(data);
  return {nameBytes,data,crc:crc32(data)};
 });
 let localSize=0,centralSize=0;
 for(const item of normalized){
  localSize+=30+item.nameBytes.length+item.data.length;
  centralSize+=46+item.nameBytes.length;
 }
 const out=new Uint8Array(localSize+centralSize+22);
 const view=new DataView(out.buffer);
 let offset=0;
 const offsets=[];
 for(const item of normalized){
  offsets.push(offset);
  view.setUint32(offset,0x04034b50,true);
  view.setUint16(offset+4,20,true);
  view.setUint16(offset+6,0x0800,true);
  view.setUint16(offset+8,0,true);
  view.setUint16(offset+10,0,true);
  view.setUint16(offset+12,0x21,true);
  view.setUint32(offset+14,item.crc,true);
  view.setUint32(offset+18,item.data.length,true);
  view.setUint32(offset+22,item.data.length,true);
  view.setUint16(offset+26,item.nameBytes.length,true);
  view.setUint16(offset+28,0,true);
  out.set(item.nameBytes,offset+30);
  out.set(item.data,offset+30+item.nameBytes.length);
  offset+=30+item.nameBytes.length+item.data.length;
 }
 const centralStart=offset;
 for(let i=0;i<normalized.length;i++){
  const item=normalized[i];
  view.setUint32(offset,0x02014b50,true);
  view.setUint16(offset+4,20,true);
  view.setUint16(offset+6,20,true);
  view.setUint16(offset+8,0x0800,true);
  view.setUint16(offset+10,0,true);
  view.setUint16(offset+12,0,true);
  view.setUint16(offset+14,0x21,true);
  view.setUint32(offset+16,item.crc,true);
  view.setUint32(offset+20,item.data.length,true);
  view.setUint32(offset+24,item.data.length,true);
  view.setUint16(offset+28,item.nameBytes.length,true);
  view.setUint16(offset+30,0,true);
  view.setUint16(offset+32,0,true);
  view.setUint16(offset+34,0,true);
  view.setUint16(offset+36,0,true);
  view.setUint32(offset+38,0,true);
  view.setUint32(offset+42,offsets[i],true);
  out.set(item.nameBytes,offset+46);
  offset+=46+item.nameBytes.length;
 }
 view.setUint32(offset,0x06054b50,true);
 view.setUint16(offset+4,0,true);
 view.setUint16(offset+6,0,true);
 view.setUint16(offset+8,normalized.length,true);
 view.setUint16(offset+10,normalized.length,true);
 view.setUint32(offset+12,centralSize,true);
 view.setUint32(offset+16,centralStart,true);
 view.setUint16(offset+20,0,true);
 return out;
}

function flyBetween(sourceNode,targetNode,durationMs=820){
 if(!sourceNode?.getBoundingClientRect||!targetNode?.getBoundingClientRect||typeof document==='undefined'||!document.body?.append)return;
 const s=sourceNode.getBoundingClientRect(),t=targetNode.getBoundingClientRect();
 if(!s.width&&!t.width)return;
 const ghost=el('div','','center-fly-ghost');
 setStyle(ghost,'cssText',`position:fixed;left:${s.left}px;top:${s.top}px;width:${Math.max(48,Math.min(120,s.width||72))}px;height:${Math.max(48,Math.min(120,s.height||72))}px;z-index:9999;pointer-events:none;border-radius:12px;border:2px solid #9eff00;background:#1b1b20;opacity:0.92;transition:transform ${durationMs}ms cubic-bezier(0.22,1,0.36,1),opacity ${durationMs}ms ease;`);
 document.body.append(ghost);
 const dx=(t.left+t.width/2)-(s.left+s.width/2),dy=(t.top+t.height/2)-(s.top+s.height/2);
 setTimeout(()=>{
  setStyle(ghost,'transform',`translate(${dx}px,${dy}px) scale(0.22)`);
  setStyle(ghost,'opacity','0.18');
 },16);
 setTimeout(()=>{
  ghost.remove();
  targetNode.setAttribute?.('data-pulse','1');
  setTimeout(()=>targetNode.removeAttribute?.('data-pulse'),320);
 },durationMs+30);
}

export function createAssetCenter(root,ctx,{source='global',embedded=false,canvas=false,workbench=false,onReference=null,onDragReference=null}={}){
 if(source==='global')return createGlobalAssetLibrary(root,ctx);
 const official=source==='official';
 const browseKinds=canvas?officialWorkbenchKinds.filter(([kind])=>kind!=='composite'):officialWorkbenchKinds;
 const facetCache=new Map(),officialPageCache=new Map(),costumePageCache=new Map();
 const REF_KINDS=new Set(['costume','pose','portrait']);
 const refState={costume:{top:'',source:'',category:'',tag:'',q:''},pose:{view:'group',system:'',category:'',angle:'',q:''},portrait:{section:'',hair:'',style:'',hot:false,q:''}};
 const refSummary={},refPageCache=new Map(),refInitialBatch={costume:60,pose:60,portrait:60};
 let refDock=null,refPickers=[],refFocus='',refSafe=null,refDepth=null,refreshRefDepth=null,characterHistory=null;
 let disposed=false,generation=0,identity=null,offset=0,filters={},tab='gallery',cart=[],cartOpen=false,selection=new Set(),workspaces=[],officialDrawerRow=null,officialDetailSeq=0,searchTimer=null,officialSearchFocus=false,officialSearchCaret=null;
 let costumeCat='',costumeQuery='',costumeTimer=0,costumeFocus=false,costumeObserver=null,costumeScrollCleanup=null;
 if(official&&!canvas&&typeof location!=='undefined'){const k=new URLSearchParams(location.search||'').get('kind');if(k&&officialWorkbenchKinds.some(([v])=>v&&v===k))filters.asset_kind=k;}
 if(official){
  studio.configureStudio({notice:m=>ctx.notice?.(m),api:ctx.api,csrf:()=>ctx.session?.()?.csrf||''});
  studio.subscribe(s=>{
   if(disposed||!REF_KINDS.has(filters.asset_kind||'')||tab!=='gallery')return;
   const changed=refSafe!==null&&s.safeMode!==refSafe;
   const depthChanged=refDepth!==null&&filters.asset_kind==='pose'&&s.poseDepthMode!==refDepth;
   refSafe=s.safeMode;refDepth=s.poseDepthMode;
   if(changed){load();return;}
   if(depthChanged)refreshRefDepth?.();
   for(const fn of refPickers)fn();
  });
 }
 function stopCostumeObserver(){
  if(costumeObserver){costumeObserver.disconnect();costumeObserver=null;}
  if(costumeScrollCleanup){costumeScrollCleanup();costumeScrollCleanup=null;}
 }
 function findScrollContainer(node){
  for(let cur=node?.parentElement;cur;cur=cur.parentElement){
   if(typeof getComputedStyle==='function'){
    const oy=getComputedStyle(cur).overflowY;
    if(oy==='auto'||oy==='scroll'||oy==='overlay')return cur;
   }else if(cur.id==='production-platform'||cur.classList?.contains?.('workspace')){
    return cur;
   }
  }
  return null;
 }
 const session=()=>ctx.session(),headers=()=>({'Content-Type':'application/json','X-CSRF-Token':session().csrf});
 const get=path=>ctx.api(path,{headers:{'X-CSRF-Token':session().csrf}});
 const post=(path,payload)=>ctx.api(path,{method:'POST',headers:headers(),body:JSON.stringify(payload===undefined?{}:{payload})});
 const field=(parent,title,type='input',value='')=>{const label=el('label',title),input=el(type);bindAttribute(input,'aria-label',title);input.value=value;label.append(input);parent.append(label);return input;};
 function button(title,fn,cls=''){const n=el('button',title,cls);n.type='button';let busy=false;n.onclick=async()=>{if(n.disabled||busy)return;busy=true;n.setAttribute('aria-busy','true');try{await fn();}catch(e){if(!disposed)ctx.notice(e.message);}finally{busy=false;n.removeAttribute('aria-busy');}};return n;}
 const active=g=>!disposed&&g===generation&&identity===session().actor;
 function closeCardMenus(event){
  for(const menu of root.querySelectorAll('.center-card-menu'))if(menu.open&&(!event||event.key==='Escape'||!menu.contains(event.target))){menu.open=false;const trigger=menu.querySelector('summary');trigger?.setAttribute('aria-expanded','false');if(event?.key==='Escape'){event.preventDefault();trigger?.focus?.();}}
 }
 function cardMenu(title,items){
  const menu=el('details','','center-card-menu'),summary=el('summary','⋯'),panel=el('div','','center-card-menu-panel');bindAttribute(summary,'aria-label',title+'的更多操作');summary.setAttribute('aria-expanded','false');
  summary.onclick=event=>{event.preventDefault();const open=menu.open;closeCardMenus();menu.open=!open;summary.setAttribute('aria-expanded',String(!open));summary.focus?.();};
  for(const [label,run]of items)panel.append(button(label,()=>{menu.open=false;summary.setAttribute('aria-expanded','false');summary.focus?.({preventScroll:true});return run();}));
  menu.append(summary,panel);return menu;
 }
 function revealActiveKind(tabs){if(workbench&&!canvas)[...tabs.children].find(n=>n.getAttribute('aria-pressed')==='true')?.scrollIntoView?.({block:'nearest',inline:'nearest'});}

 const readKey=key=>{try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}};
 const keepKey=(key,value)=>{try{value?sessionStorage.setItem(key,JSON.stringify(value)):sessionStorage.removeItem(key);}catch{}};
 const singleKey=()=>`vsc-center-single:${session().actor}`;
 const assetKind=row=>row.official?.asset_kind||row.catalog?.display_kind||row.catalog?.asset_kind||'other';
 const visibleMembers=row=>(row.members||[]).filter(m=>['image','video','audio'].includes(m.modality));
 function picture(member){
  const n=el(member.modality==='image'?'img':member.modality==='audio'?'audio':'video');
  n.src=member.preview_url;n.loading='lazy';n.preload='metadata';
  if(member.modality==='image')bindAttribute(n,'alt',msg('ui.fixed_shared_media_version'));
  else{n.controls=true;n.playsInline=true;}
  n.addEventListener('error',()=>{if(n.parentElement&&!n.parentElement.querySelector('.center-media-error')){const hint=el('p',msg('gallery.preview_unavailable'),'center-media-error');n.parentElement.append(hint);}},{once:true});
  return n;
 }
 function zoom(row,member){
  return openAssetImageViewer({
   title:row?.title||'',
   member,
   imgNode:picture(member),
   host:document.body||root,
  });
 }
 function shell(){
  document.removeEventListener?.('pointerdown',closeCardMenus,true);document.removeEventListener?.('keydown',closeCardMenus,true);
  unmountRefs();
  stopCostumeObserver();
  root.querySelectorAll('dialog').forEach(d=>d.close());
  root.replaceChildren();
  root.className='asset-center'+(official?' center-official':' center-platform')+(embedded?' center-embedded':'')+(canvas?' center-canvas':'')+(workbench?' center-workbench-official':'');
  if(!embedded)root.append(el('h1',official?'官方资产':msg('nav.asset_library')),...(official?[]:[el('p',msg('gallery.intro'))]));
  const nav=el('nav','','center-tabs');
  for(const [value,title]of [...(!embedded?[['gallery',msg('gallery.media')],...(!official?[['catalog',msg('gallery.spec_catalog')]]:[])]:[]),['cart',msg('ui.selection_list')],['downloads',msg('ui.download_request_history')]]){
   const n=button(title,async()=>{tab=value;offset=0;await load();});
   n.setAttribute('aria-pressed',String(tab===value));nav.append(n);
  }
  if(embedded&&tab!=='gallery')nav.prepend(button('返回官方资产',async()=>{tab='gallery';offset=0;await load();}));
  if(!canvas&&!workbench)root.append(nav);
  pendingBanner();
 }
 function pendingBanner(){
  const key=singleKey(),pending=readKey(key),existing=root.querySelector('.center-recover');
  if(!pending){existing?.remove();return;}
  if(existing)return;
  const recover=button(msg('gallery.recover'),()=>{const value=readKey(key);if(value)return value.action==='multi-add'?quickAddProjects(value.row,value.member):quickAdd(value.row,value.member,value.action);},'center-recover');
  root.append(recover);
 }
 async function metadata(row){
  const g=generation,dialog=el('dialog','','center-dialog center-review-modal'),prior=row.catalog||{asset_kind:'other',form_name:'',tags:[],review_status:'draft',notes:'',revision:0};
  bindAttribute(dialog,'aria-label',msg('ui.media_catalog_editing'));
  const layout=el('div','','center-review-grid'),leftCol=el('div','','center-review-media'),rightCol=el('form','','center-review-form');
  const members=visibleMembers(row);
  if(members.length){
   const primary=members.find(m=>m.modality==='image')||members[0];
   const stage=el('div','','center-review-stage center-zoom-viewport');
   const mediaNode=picture(primary);
   stage.append(mediaNode);
   if(primary.modality==='image'){
    const zbar=el('div','','center-review-zoom center-zoom-bar');
    const level=el('span','100%','center-zoom-level');
    const ctrl=attachImageZoomPan(stage,mediaNode,{
     initialWidth:primary.width||0,
     initialHeight:primary.height||0,
     onScaleChange:({percent})=>setText(level,`${percent}%`),
    });
    zbar.append(
     button('缩小',()=>ctrl.zoomOut()),
     level,
     button('适应窗口',()=>ctrl.reset()),
     button('放大',()=>ctrl.zoomIn())
    );
    leftCol.append(stage,zbar);
   }else leftCol.append(stage);
  }else leftCol.append(el('p',msg('gallery.spec_empty'),'center-review-empty'));
  const head=el('div','','center-review-head');
  head.append(
   el('h2',msg('ui.organize_value0',{value0:row.title})),
   el('span','🔥 '+String(row.download_count||0),'center-heat-pill'),
   el('span',prior.review_status==='confirmed'?'已入库':prior.review_status==='returned'?'需补充':'待确认','center-status-pill status-'+(prior.review_status||'draft'))
  );
  rightCol.append(head);
  const kind=field(rightCol,msg('ui.asset_category'),'select');
  for(const [code,title]of kinds)kind.append(localizedOption(code,title));
  kind.value=prior.display_kind||prior.asset_kind||'other';
  const shape=field(rightCol,msg('agent.manifestation_edit_label'),'input',prior.form_name||'');
  const initialTags=(prior.tags||[]).filter(t=>t!=='生物/异兽');
  const tags=field(rightCol,msg('ui.tags_comma_separated'),'input',initialTags.join(', '));
  const tagChips=el('div','','center-tag-chips');
  rightCol.append(tagChips);
  const workspace=field(rightCol,msg('ui.owning_studio'),'select');
  workspace.append(localizedOption('',msg('ui.unspecified')));
  for(const w of workspaces)workspace.append(localizedOption(w.id,w.name));
  workspace.value=prior.workspace_id||'';
  const review=field(rightCol,msg('ui.catalog_confirmation'),'select');
  for(const [code,title]of [['draft',msg('agent.overseas_remake_workflow_status_2')],['confirmed',msg('novel-parser.status_approved')],['returned',msg('ui.needs_additional_input')]])review.append(localizedOption(code,title));
  review.value=prior.review_status||'draft';
  const notes=field(rightCol,msg('ui.organization_and_confirmation_notes'),'textarea',prior.notes||'');
  const progressWrap=el('div','','center-completeness'),progressText=el('span',''),progressBar=el('progress');
  progressBar.max=100;progressWrap.append(progressText,progressBar);rightCol.append(progressWrap);
  function renderTagPreview(){
   tagChips.replaceChildren();
   const parsed=tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean);
   for(const t of parsed){
    const chip=el('span',t,review.value==='draft'?'center-tag-chip tag-unverified':'center-tag-chip');
    if(review.value==='draft')bindAttribute(chip,'title','表格预导入待人工核验标签');
    tagChips.append(chip);
   }
   let score=20;
   if(kind.value&&kind.value!=='other')score+=20;
   if(shape.value.trim())score+=20;
   if(parsed.length)score+=20;
   if(workspace.value||notes.value.trim())score+=20;
   progressBar.value=score;
   setText(progressText,`标签完整度 ${score}%`+(review.value==='draft'&&parsed.length?' · 紫色边框为待核验标签':''));
  }
  for(const ctrl of [kind,shape,tags,workspace,review,notes])ctrl.addEventListener('input',renderTagPreview);
  renderTagPreview();
  rightCol.append(el('p',msg('ui.this_confirms_only_catalog_information_for_fixed_shared_media')));
  const status=el('p');status.setAttribute('role','status');
  const footer=el('div','','center-review-actions'),save=el('button',msg('ui.save_catalog'),'center-primary-cta');save.type='submit';
  footer.append(save,button(msg('common.close'),()=>dialog.close()));
  rightCol.append(footer,status);
  layout.append(leftCol,rightCol);dialog.append(layout);
  root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  let intent=null;
  rightCol.onsubmit=async e=>{
   e.preventDefault();if(save.disabled)return;save.disabled=true;
   const payload={entry_id:row.id,library_version_id:row.version_id,expected_revision:prior.revision||0,asset_kind:kind.value,form_name:shape.value,workspace_id:workspace.value||null,review_status:review.value,notes:notes.value,tags:tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean)};
   const signature=JSON.stringify(payload);
   if(intent?.signature!==signature)intent={signature,key:crypto.randomUUID()};
   try{await post('/api/v1/asset-center/catalog',{...payload,command_key:intent.key});if(!active(g))return;dialog.close();await load();}
   catch(error){setText(status,msg('ui.value0_entered_content_is_preserved',{value0:error.message}));}
   finally{save.disabled=false;}
  };
 }
 function modal(title,extraCls=''){
  const dialog=el('dialog','','center-dialog'+(extraCls?' '+extraCls:''));
  bindAttribute(dialog,'aria-label',title);dialog.append(el('h2',title));
  root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  return dialog;
 }
 const reference=(row,member)=>onReference?onReference({row,member}):quickAdd(row,member,'reference');
 function draggable(node,row,member){if(!onDragReference)return;node.draggable=true;node.addEventListener('dragstart',event=>onDragReference(event,{row,member}));}
 async function addCartItem(row,member,g,cardNode=null,fabNode=null){
  if(cart.length>=MAX_CART_ITEMS&&!cart.some(c=>c.library_version_id===row.version_id&&c.member_key===member.member_key)){
   throw new Error(`已选清单最多容纳 ${MAX_CART_ITEMS} 个资产`);
  }
  const res=await post('/api/v1/asset-center/cart',{library_version_id:row.version_id,member_key:member.member_key,active:true});
  if(!active(g))return;
  if(!cart.some(c=>c.id===res.id)){
   cart.push({id:res.id,library_version_id:row.version_id,member_key:member.member_key,title:row.title,asset_kind:assetKind(row),preview_url:member.preview_url});
  }
  if(cardNode&&fabNode)flyBetween(cardNode,fabNode,820);
  ctx.notice(msg('ui.fixed_media_added_import_it_into_a_project_from'));
 }
 function mediaActions(parent,row,member,g,cardNode=null,fabNode=null){
  const actions=el('div','','center-actions');
  actions.append(button(msg('gallery.add_project'),()=>addToProjects(row,member)));
  if(onReference||member.modality==='image')actions.append(button(onReference?msg('ui.send_to_canvas'):msg('gallery.create_reference'),()=>reference(row,member)));
  actions.append(button(msg('ui.add_to_selection_list'),()=>addCartItem(row,member,g,cardNode,fabNode)));
  const key=crypto.randomUUID();
  actions.append(button(msg('common.download'),async()=>{
   const result=await post('/api/v1/asset-center/downloads',{library_version_id:row.version_id,member_key:member.member_key,command_key:key});
   if(!active(g)||!parent.isConnected)return;
   const a=el('a',msg('ui.continue_download'));a.href=result.url;a.download=row.title;a.target='_blank';a.rel='noopener';actions.append(a);a.click();
  }));
  parent.append(actions);
 }
 function openOfficialDrawer(row,g){
  officialDrawerRow=row;
  root.querySelector('.official-detail-drawer')?.remove();
  const returnFocus=document.activeElement,drawer=el('aside','','official-detail-drawer');
  bindAttribute(drawer,'aria-label',row.title+' 详情预览');
  const head=el('div','','official-drawer-head');
  const close=button('×',()=>{officialDrawerRow=null;++officialDetailSeq;drawer.remove();if(returnFocus?.isConnected)returnFocus.focus?.();},'official-drawer-close');bindAttribute(close,'aria-label','关闭资产详情');
  head.append(el('h3',row.title),close);
  drawer.append(head);
  const members=(row.gallery||visibleMembers(row)).filter(m=>['image','video','audio'].includes(m.modality));
  if(!members.length)drawer.append(el('p','暂无可用媒体，可到回收站恢复。'));
  const memberSections=[],thumbButtons=[],thumbs=el('div','','official-drawer-thumbs');thumbs.setAttribute('aria-label','选择主图或备份媒体');
  const choose=index=>{memberSections.forEach((n,i)=>{n.hidden=i!==index;});thumbButtons.forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));};
  for(const [index,member]of members.entries()){
   const section=el('section','','official-drawer-member'),label=index===0?'主图':`备份图-${index}`,stage=el('div','','official-drawer-stage');
   section.append(el('h4',label));
   if(member.modality==='image'){
    const preview=button('',()=>zoom(row,member),'official-drawer-preview');bindAttribute(preview,'aria-label',`查看${label}大图`);preview.append(picture(member));stage.append(preview);
   }else stage.append(picture(member));
   const fixed={...row,version_id:member.library_version_id||row.version_id};
   const actions=el('div','','official-drawer-ctas');actions.append(button('引用生成',()=>reference(fixed,member),'center-primary-cta'),button(msg('gallery.add_project'),()=>addToProjects(fixed,member)));
   section.append(stage,actions);
   if(row.can_manage_media){const remove=button('移入回收站',()=>deleteOfficialMedia(row,member,label,g),'official-drawer-delete');bindAttribute(remove,'aria-label',`删除${label}`);section.append(remove);}
   section.hidden=index!==0;memberSections.push(section);drawer.append(section);
   const thumb=button('',()=>choose(index),'official-drawer-thumb');thumb.setAttribute('aria-pressed',String(index===0));bindAttribute(thumb,'aria-label',`选择${label}`);
   if(member.modality==='image')thumb.append(picture(member));thumb.append(el('span',label));thumbButtons.push(thumb);thumbs.append(thumb);
  }
  if(members.length>1)drawer.append(thumbs);
  drawer.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();close.onclick();}};
  const meta=el('div','','official-drawer-meta');
  const labels={lead:'主角',supporting:'配角',extra:'群演'},bands={'child|male':'幼年男','child|female':'幼年女','teen|male':'少年男','teen|female':'少年女','young_adult|male':'青年男','young_adult|female':'青年女','middle_aged|male':'中年男','middle_aged|female':'中年女','senior|male':'老年男','senior|female':'老年女'};
  if(row.official){
   for(const tag of [labels[row.official.role_level],bands[row.official.age_band+'|'+row.official.gender],row.official.role_tag].filter(Boolean)){
    meta.append(el('span',tag,'official-drawer-tag'));
   }
  }
  for(const tag of row.catalog?.tags||[])meta.append(el('span',tag,'official-drawer-tag'));
  meta.append(el('span','🔥 '+String(row.download_count||0),'official-drawer-heat'));
  drawer.append(meta);
  if(row.description)drawer.append(el('p',row.description,'official-drawer-desc'));
  root.append(drawer);close.focus?.({preventScroll:true});
 }
 function deleteOfficialMedia(row,member,label,g){
  const dialog=modal('删除'+label),request={library_version_id:member.library_version_id||row.version_id,member_key:member.member_key,operation:'trash',expected_revision:member.revision||0,reason:'从官方资产详情删除'+label,command_key:crypto.randomUUID()};
  dialog.append(el('p',`${row.title} · ${label}将移入回收站，可恢复。`));
  dialog.append(button('移入回收站',async()=>{
   await ctx.api('/api/v1/asset-center/official/media-actions',{method:'POST',headers:headers(),body:JSON.stringify({confirmed:true,payload:request})});
   dialog.close();officialPageCache.clear();
   if(active(g)){ctx.notice('已移入回收站');await load();}
  }),button('取消',()=>dialog.close()));
 }
 async function detail(row,g){
  if(official&&!canvas){
   const seq=++officialDetailSeq;officialDrawerRow=row;
   const fresh=await get('/api/v1/asset-center/official/entries/'+encodeURIComponent(row.id));
   if(active(g)&&seq===officialDetailSeq&&officialDrawerRow?.id===row.id)openOfficialDrawer(fresh,g);
   return;
  }
  if(canvas){
   const dialog=modal(row.title,'cc-asset-preview');dialog.replaceChildren();
   const members=visibleMembers(row);
   for(const member of members){const section=el('section','','cc-asset-preview-media');const visual=picture(member);draggable(visual,row,member);section.append(visual);dialog.append(section);}
   const footer=el('footer');footer.append(el('strong',row.title),el('small',row.source==='official'?'官方资产':msg('shell.shared_library')));dialog.append(footer);
   for(const member of members)mediaActions(dialog,row,member,g);
   const close=button('×',()=>dialog.close(),'cc-asset-preview-close');bindAttribute(close,'aria-label',msg('common.close'));dialog.append(close);return;
  }
  const dialog=modal(row.title,'center-preview-dialog'),summary=el('p',msg('gallery.fixed_version',{version:row.version}),'center-version');
  dialog.append(summary,el('p',row.description||''),el('p',(row.catalog?.tags||[]).join(' · ')));
  const members=visibleMembers(row);if(!members.length)dialog.append(el('p',msg('gallery.spec_empty')));
  for(const [index,member]of members.entries()){
   const section=el('section','','center-member');
   const mediaNode=picture(member);
   if(member.modality==='image')mediaNode.addEventListener('click',()=>zoom(row,member));
   section.append(el('h3',msg('gallery.member',{number:index+1,type:msg('gallery.'+member.modality)})),mediaNode);
   const facts=[];if(member.width&&member.height)facts.push(`${member.width} × ${member.height}`);if(member.duration_ms!=null)facts.push(msg('gallery.seconds',{seconds:(member.duration_ms/1000).toFixed(1)}));
   if(facts.length)section.append(el('p',joinMessages(facts,' · ')));
   mediaActions(section,row,member,g);dialog.append(section);
  }
  const license=el('details');license.append(el('summary',msg('gallery.license')),el('p',row.license?.name||row.license?.evidence||''));
  if(row.license?.attribution)license.append(el('p',row.license.attribution));
  if(row.expires_at)license.append(el('p',msg('gallery.expires',{date:new Date(row.expires_at).toLocaleString()})));
  dialog.append(license);
  if(row.can_edit_catalog)dialog.append(button(msg('ui.edit_tags_and_confirmation'),()=>{dialog.close();return metadata(row);}));
  dialog.append(button(msg('common.close'),()=>dialog.close()));
 }
 async function downloadCartZip(g){
  if(!cart.length)throw new Error('请先将资产加入清单');
  if(cart.length===1){
   const item=cart[0];
   const res=await post('/api/v1/asset-center/downloads',{library_version_id:item.library_version_id,member_key:item.member_key,command_key:crypto.randomUUID()});
   if(!active(g))return;
   const a=el('a','下载');a.href=res.url;a.download=item.title||'asset';a.click();
   return;
  }
  const entries=[];
  for(const [idx,item]of cart.entries()){
   const res=await post('/api/v1/asset-center/downloads',{library_version_id:item.library_version_id,member_key:item.member_key,command_key:crypto.randomUUID()});
   if(!active(g))return;
   let bytes=new Uint8Array(0);
   if(typeof fetch==='function'){
    try{const r=await fetch(res.url,{credentials:'same-origin'});if(r.ok)bytes=new Uint8Array(await r.arrayBuffer());}catch{}
   }
   entries.push({name:`${String(idx+1).padStart(3,'0')}-${(item.title||'asset').slice(0,40)}-${item.member_key}.bin`,bytes});
  }
  const zipBytes=buildStoreZip(entries);
  if(typeof Blob!=='undefined'&&typeof URL?.createObjectURL==='function'){
   const blob=new Blob([zipBytes],{type:'application/zip'}),url=URL.createObjectURL(blob),a=el('a');
   a.href=url;a.download=`asset-center-${Date.now()}.zip`;a.click();
   setTimeout(()=>URL.revokeObjectURL(url),1500);
  }
  ctx.notice(`已打包下载 ${entries.length} 个资产`);
 }
 function openPlatformBatchImportDialog(g){
  if(!cart.length)throw new Error('已选清单为空，请先勾选资产');
  const dialog=modal('保存已选资产到项目','center-batch-import-dialog');
  const projects=ctx.projects().filter(p=>!p.read_only&&!p.unavailable&&!['vsc.text-tools','vsc.creative-tools'].includes(p.profile_id||p.profile));
  const projectSelect=field(dialog,msg('gallery.target_project'),'select');
  for(const p of projects)projectSelect.append(localizedOption(p.id,p.name));
  if(ctx.projectId?.())projectSelect.value=ctx.projectId();
  const kindSelect=field(dialog,msg('ui.asset_type_to_create_after_import'),'select');
  for(const [code,title]of kinds.filter(([code])=>roles[code]))kindSelect.append(localizedOption(code,title));
  const status=el('p');status.setAttribute('role','status');
  const confirmBtn=button('开始导入 ('+cart.length+')',async()=>{
   if(!projectSelect.value)throw new Error('请选择目标项目');
   let done=0;
   for(const item of cart){
    const tree=await get(`/api/v1/projects/${encodeURIComponent(projectSelect.value)}/tree`);
    if(!active(g))return;
    const chosenKind=roles[item.asset_kind]?item.asset_kind:kindSelect.value;
    await ctx.api(`/api/v1/projects/${encodeURIComponent(projectSelect.value)}/asset-center/import`,{
     method:'POST',headers:headers(),
     body:JSON.stringify({payload:{cart_id:item.id,asset_kind:chosenKind==='creature'?'creature':chosenKind,role:roles[chosenKind]||'prop'},expected_revision:tree.revision,idempotency_key:crypto.randomUUID()})
    });
    done++;setText(status,`已同步 ${done} / ${cart.length} 个资产`);
   }
   dialog.close();ctx.notice(`已将 ${done} 个资产导入目标项目`);
  },'center-primary-cta');
  dialog.append(confirmBtn,button(msg('common.cancel'),()=>dialog.close()),status);
 }
 async function catalog(g){
  const gallery=tab==='gallery';if(official){await officialCatalog(g);return;}
  const headerBar=el('div','','center-platform-bar');
  const modeSeg=el('div','','center-mode-seg');
  for(const [val,label]of [['','全部状态'],['confirmed','已入库'],['draft','待审核/待打标']]){
   const b=button(label,async()=>{filters.review_status=val;offset=0;await load();});
   b.setAttribute('aria-pressed',String((filters.review_status||'')===val));
   modeSeg.append(b);
  }
  const statsWrap=el('div','','center-stat-pills'),statTotal=el('span','总资产 0','center-stat-pill'),statCurrent=el('span','当前结果 0','center-stat-pill'),statSelected=el('span',`已选资产 ${cart.length}`,'center-stat-pill');
  statsWrap.append(statTotal,statCurrent,statSelected,button('刷新',()=>load(),'center-refresh-btn'));
  headerBar.append(modeSeg,statsWrap);
  root.append(headerBar);

  const form=el('form','','center-search');
  const q=field(form,msg('gallery.search'),'input',filters.query||'');q.type='search';
  q.oninput=()=>{filters.query=q.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;load();},300);};
  const find=el('button',msg('ui.search'));find.type='submit';form.append(find);root.append(form);

  const pills=el('nav','','center-kinds');bindAttribute(pills,'aria-label',msg('ui.asset_category'));
  for(const [code,title]of [['',msg('ui.all_categories')],...kinds]){
   const n=button(title,async()=>{filters.asset_kind=code;offset=0;await load();});
   n.setAttribute('aria-pressed',String((filters.asset_kind||'')===code));pills.append(n);
  }
  root.append(pills);

  const advanced=el('details','','center-filters');advanced.append(el('summary',msg('gallery.more_filters')));
  const fields=el('div','','center-filter-fields');
  const tag=field(fields,msg('ui.tags'),'input',filters.tag||''),shape=field(fields,msg('ui.form'),'input',filters.form_name||'');
  const workspace=field(fields,msg('user.workbench_studios'),'select');workspace.append(localizedOption('',msg('ui.all_studios')));
  for(const w of workspaces)workspace.append(localizedOption(w.id,w.name));workspace.value=filters.workspace_id||'';
  const review=field(fields,msg('ui.confirmation_status'),'select');
  for(const [value,title]of [['',msg('asset.all_status')],['draft',msg('agent.overseas_remake_workflow_status_2')],['confirmed',msg('novel-parser.status_approved')],['returned',msg('ui.needs_additional_input')]])review.append(localizedOption(value,title));
  review.value=filters.review_status||'';
  const orderSelect=field(fields,'排序方式','select');
  for(const [value,title]of [['','默认排序'],['heat','最热下载'],['latest','最新入库']])orderSelect.append(localizedOption(value,title));
  orderSelect.value=filters.order_by||'';
  for(const [name,input]of [['tag',tag],['form_name',shape],['workspace_id',workspace],['review_status',review],['order_by',orderSelect]]){
   input.addEventListener('input',()=>{if(input.value)filters[name]=input.value;else delete filters[name];});
  }
  fields.append(
   button(msg('asset.filter'),async()=>{offset=0;await load();}),
   button('重置筛选',async()=>{filters={};offset=0;await load();})
  );
  advanced.append(fields);root.append(advanced);
  form.onsubmit=e=>{e.preventDefault();clearTimeout(searchTimer);offset=0;load();};

  const queryParams={...filters,media_only:String(gallery),offset,limit:24};
  if(!queryParams.order_by)delete queryParams.order_by;
  const value=await get('/api/v1/asset-center?'+new URLSearchParams(queryParams));
  if(!active(g))return;
  setText(statTotal,`总资产 ${value.total}`);
  setText(statCurrent,`当前结果 ${value.items.length}`);
  setText(statSelected,`已选资产 ${cart.length}`);

  const count=el('p',msg(gallery?'gallery.count':'gallery.catalog_count',{count:value.total}),'center-count');
  count.setAttribute('role','status');root.append(count);
  const grid=el('div','',gallery?'center-grid':'center-spec-grid');

  const fab=button(`🛒 ${cart.length}`,async()=>{
   cartOpen=!cartOpen;
   if(cartOpen){const res=await get('/api/v1/asset-center/cart');if(!active(g))return;cart=res.items||[];}
   renderCartTray();
  },'asset-cart-fab');
  bindAttribute(fab,'aria-label','打开已选资产购物车');

  for(const row of value.items){
   const card=el('article','','center-card'),members=visibleMembers(row),cover=el('div','','center-cover');
   if(members.length){
    const member=members.find(m=>m.modality==='image')||members[0];
    if(member.modality==='image'){
     const open=button('',()=>zoom(row,member),'center-preview');
     bindAttribute(open,'aria-label','放大查看 '+row.title);open.append(picture(member));cover.append(open);
    }else cover.append(picture(member));
    const quickCart=button('＋清单',async()=>{
     await addCartItem(row,member,g,cover,fab);
     setText(fab,`🛒 ${cart.length}`);
     setText(statSelected,`已选资产 ${cart.length}`);
     if(cartOpen)renderCartTray();
    },'center-cart-quick');
    bindAttribute(quickCart,'title','加入资产购物车 (最多200项)');
    cover.append(quickCart);
    card.append(cover);
   }else card.append(el('p',msg('gallery.spec_empty')));
   const kindCode=assetKind(row),type=kinds.find(k=>k[0]===kindCode)?.[1]||msg('gallery.other'),badge=el('span',type,'center-kind-badge');
   cover.append(badge);
   if(row.download_count)cover.append(el('span','🔥 '+row.download_count,'center-heat-badge'));
   const title=el('h2'),open=button(row.title,()=>row.can_edit_catalog?metadata(row):detail(row,g));
   bindAttribute(open,'title',row.title);title.append(open);
   card.append(title,el('p',row.catalog.form_name||msg('asset.default_manifestation')));
   if(row.catalog.tags.length)card.append(el('p',row.catalog.tags.join(' · ')));
   if(!gallery&&row.description)card.append(el('p',row.description));
   if(members.length){
    const actions=el('div','','center-actions');
    actions.append(button(msg('gallery.add_project'),()=>members.length===1?addToProjects(row,members[0]):detail(row,g)));
    if(members.length===1&&(onReference||members[0].modality==='image'))actions.append(button(onReference?msg('ui.send_to_canvas'):msg('gallery.create_reference'),()=>reference(row,members[0])));
    if(members.length>1)actions.append(button(msg('gallery.members',{count:members.length}),()=>detail(row,g)));
    if(row.can_edit_catalog)actions.append(button('打标审核',()=>metadata(row)));
    card.append(actions);
   }else if(row.can_edit_catalog)card.append(button(msg('ui.edit_tags_and_confirmation'),()=>metadata(row)));
   grid.append(card);
  }
  if(!value.items.length){
   const empty=el('section','','center-empty');
   empty.append(el('h2',msg(gallery?'gallery.no_media':'gallery.no_specs')),el('p',msg('gallery.empty_help')));
   grid.append(empty);
  }
  root.append(grid);
  paging(value.total,value.next_offset,g);

  const trayHost=el('div','','asset-cart-tray-host');
  root.append(fab,trayHost);
  function renderCartTray(){
   trayHost.replaceChildren();
   setText(fab,`🛒 ${cart.length}`);
   setText(statSelected,`已选资产 ${cart.length}`);
   if(!cartOpen)return;
   const tray=el('section','','asset-cart-tray');
   const head=el('div','','asset-cart-tray-head');
   head.append(
    el('strong',`已选资产清单 (${cart.length} / ${MAX_CART_ITEMS})`),
    button('保存到项目',()=>openPlatformBatchImportDialog(g),'center-primary-cta'),
    button('打包下载 ZIP',()=>downloadCartZip(g)),
    button('清空选择',async()=>{await post('/api/v1/asset-center/cart/clear');if(!active(g))return;cart=[];renderCartTray();}),
    button('收起',()=>{cartOpen=false;renderCartTray();})
   );
   const itemsBox=el('div','','asset-cart-tray-items');
   for(const item of cart){
    const pill=el('div','','asset-cart-pill');
    pill.append(
     el('span',item.title||item.member_key,'asset-cart-pill-title'),
     button('×',async()=>{
      await post('/api/v1/asset-center/cart',{library_version_id:item.library_version_id,member_key:item.member_key,active:false});
      if(!active(g))return;
      cart=cart.filter(c=>c.id!==item.id);
      renderCartTray();
     },'asset-cart-pill-remove')
    );
    itemsBox.append(pill);
   }
   if(!cart.length)itemsBox.append(el('p','暂未选择资产，点击卡片右上角“＋清单”飞入购物车'));
   tray.append(head,itemsBox);
   trayHost.append(tray);
  }
 }
 function paging(total,next,g){
  const nav=el('nav','','center-pagination');
  const previous=button(msg('common.previous_page'),async()=>{offset=Math.max(0,offset-24);await load();});
  previous.disabled=offset===0;nav.append(previous,el('span',msg('ui.value0_items',{value0:total})));
  const forward=button(msg('common.next_page'),async()=>{if(!active(g)||next==null)return;offset=next;await load();});
  forward.disabled=next==null;nav.append(forward);root.append(nav);
 }

 function queryAllDialogs(){
  if(typeof document!=='undefined'&&typeof document.querySelectorAll==='function')return [...document.querySelectorAll('dialog')];
  return [...root.querySelectorAll('dialog')];
 }
 function closeCostumeDialogs(){
  for(const dialog of queryAllDialogs()){
   const cls=String(dialog.className||'');
   if(cls.includes('costume-modal')||cls.includes('costume-note'))dialog.close();
  }
 }
 function costumeNote(title,body){
  const open=queryAllDialogs().find(dialog=>String(dialog.className||'').includes('costume-note')&&dialog.dataset?.note===title);
  if(open){open.close();return;}
  closeCostumeDialogs();
  const dialog=el('dialog','','costume-note');
  if(dialog.dataset)dialog.dataset.note=title;
  dialog.append(el('h2',title),el('p',body),button('关闭',()=>dialog.close()));
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener('close',()=>dialog.remove());
  (document.body||root).append(dialog);
  dialog.showModal();
 }
  // ------------------------------------------------------------------ reference libraries
  // 服装穿搭库 / 动作姿势库 / 人像颜值库 share Row 1 (kind tabs) and Row 2 (44px
  // filter row) with the other official tabs, so switching tabs never shifts layout.
  async function referenceBrowser(g,kind){
   const LIMIT=String(refInitialBatch[kind]);
   stopCostumeObserver();closeCostumeDialogs();
   root.className=String(root.className||'').replace(/\b(costume-library|ref-library|ref-costume|ref-pose|ref-portrait)\b/g,'').replace(/\s+/g,' ').trim()+' costume-library ref-library ref-'+kind;
   const scrollRoot=findScrollContainer(root),st=refState[kind],slot=kind;
   const reload=(initial=60)=>{refInitialBatch[kind]=initial;clearTimeout(costumeTimer);if(scrollRoot)scrollRoot.scrollTop=0;return load();};
   const studioState=studio.getState();
   const form=el('div','','center-official-filters ref-filters'),tabs=el('div','','center-official-kinds');
   for(const [value,title]of browseKinds){
    const t=button(title,()=>switchKind(value));
    t.setAttribute('aria-pressed',String((filters.asset_kind||'')===value));tabs.append(t);
   }
   const row=el('div','','center-official-filter-row ref-filter-row');
   form.append(tabs,row);root.append(form);revealActiveKind(tabs);
   const summary=refSummary[kind]||null;
   const selects={};
   const pickSelect=(key,label,choices,onPick)=>{
    const s=field(row,label,'select');fillSelect(s,label,choices,st[key]);
    s.onchange=()=>{st[key]=s.value;onPick?.();refFocus='';return reload();};
    selects[key]=s;return s;
   };
   const search=()=>{
    const input=field(row,'搜索','input',st.q||'');input.type='search';
    bindAttribute(input,'placeholder',kind==='costume'?'名称、颜色、单品或编号':kind==='pose'?'姿势名称、编号或分类':'发型名称或编号');
    input.oninput=()=>{st.q=input.value;refInitialBatch[kind]=60;refFocus='search';clearTimeout(costumeTimer);costumeTimer=setTimeout(()=>{costumeTimer=0;if(!disposed)load();},200);};
    input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault?.();clearTimeout(costumeTimer);load();}});
    return input;
   };
   const safeButton=()=>{
    const b=button(studioState.safeMode?'安全模式':'18+ 已解锁',()=>studio.toggleSafeMode(),'center-clear-filters ref-safe');
    b.setAttribute('aria-pressed',String(!studioState.safeMode));bindAttribute(b,'title',studioState.safeMode?'已隐藏 18+ 敏感分类，点击确认年龄后解锁':'点击恢复安全模式');return b;
   };
   let input;
   if(kind==='costume'){
    pickSelect('top','全部类型',(summary?.tops||[{name:'现实'},{name:'二次元'}]).map(t=>[t.name,t.count!=null?`${t.name} ${t.count}`:t.name]),()=>{st.source='';st.category='';st.tag='';});
    pickSelect('source','全部来源',(summary?.sources||[]).map(s=>[s.id,`${s.label} ${s.count}`]),()=>{st.category='';st.tag='';});
    pickSelect('tag','全部标签',(summary?.tags||[]).map(t=>[t.name,`${t.name} ${t.count}`]));
    input=search();
   }else if(kind==='pose'){
    pickSelect('system','全部体系',(summary?.systems||[]).map(s=>[s.name,`${s.name} ${s.count}`]),()=>{st.category='';});
    pickSelect('angle','全部角度',(summary?.angles||['正面','斜侧','侧面','背面','俯视','仰视']).map(a=>[a,a]));
    const view=field(row,'视图','select');for(const [v,l]of [['group','分组'],['single','单张']])view.append(localizedOption(v,l));view.value=st.view;
    view.onchange=()=>{st.view=view.value;return reload(view.value==='single'?96:60);};
    const depth=field(row,'素体','select');for(const [v,l]of [['white','素体白模'],['depth','深度图 (Depth)']])depth.append(localizedOption(v,l));depth.value=studioState.poseDepthMode?'depth':'white';
    depth.onchange=()=>studio.setPoseDepthMode(depth.value==='depth');selects.depth=depth;
    input=search();
   }else{
    pickSelect('section','全部分区',(summary?.sections||[]).map(s=>[s.name,`${s.name} ${s.count}`]),()=>{st.style='';});
    pickSelect('style','全部发型',(summary?.hair_styles||[]).map(s=>[s.name,`${s.name} ${s.count}`]));
    input=search();
   }
   row.prepend(input.parentElement);
   const count=el('span','加载中…','center-count');count.setAttribute('role','status');row.append(count);
   if(kind==='portrait'){
    const hot=button(st.hot?'Top10 热门 ✓':'Top10 热门',()=>{st.hot=!st.hot;return reload();},'center-clear-filters ref-hot');hot.setAttribute('aria-pressed',String(Boolean(st.hot)));row.append(hot);
   }else row.append(safeButton());
   if(kind==='costume')row.append(button('来源说明',()=>costumeNote('来源与使用说明',(refSummary.costume?.sources||[]).map(s=>`${s.label}：${s.notice}（${s.url}）`).join('\n\n')||'加载中，请稍后再试。'),'center-clear-filters'));
   if(refFocus==='search'){input.focus?.();}
   // Row 3 pills: costume/pose categories, portrait hair lengths.
   const pills=el('div','','costume-tabs ref-pills');pills.setAttribute('role','tablist');
   const pillKey=kind==='portrait'?'hair':'category';
   const syncPills=data=>{
    const list=kind==='costume'?(data?.categories||[]).map(c=>[c.name,`${c.name} ${Number(c.count).toLocaleString('zh-CN')}`])
     :kind==='pose'?(data?.categories||[]).map(c=>[c,c]):(data?.hair_lengths||[]).map(h=>[h.name,`${h.name} ${h.count}`]);
    const totalLabel=kind==='costume'&&data?`全部 ${Number(data.categories.reduce((a,c)=>a+c.count,0)).toLocaleString('zh-CN')}`:'全部';
    const entries=[['',totalLabel],...list];
    const existing=[...pills.children];
    if(existing.length===entries.length&&existing.every((n,i)=>n.dataset?.value===entries[i][0])){
     for(const [i,[val,label]]of entries.entries()){setText(existing[i],label);existing[i].setAttribute('aria-pressed',String((st[pillKey]||'')===val));}
     return;
    }
    pills.replaceChildren();
    for(const [val,label]of entries){
     const t=button(label,()=>{st[pillKey]=val;if(kind==='costume')st.tag='';return reload();});
     if(t.dataset)t.dataset.value=val;t.setAttribute('role','tab');t.setAttribute('aria-pressed',String((st[pillKey]||'')===val));pills.append(t);
    }
   };
   syncPills(summary);root.append(pills);
   const pageItems=[],grid=el('div','','costume-grid ref-grid'),pickers=[],depthPickers=[];
   let refreshModal=null;
   refreshRefDepth=()=>{
    if(selects.depth)selects.depth.value=studio.getState().poseDepthMode?'depth':'white';
    for(const draw of depthPickers)draw();
    refreshModal?.();
   };
   let next=null,moreBtn=null,pagingBusy=false,total=0,pageError=null;
   const params=(offset,limit=LIMIT)=>{
    const q=new URLSearchParams();
    for(const [k,v]of Object.entries(st))if(v!==''&&v!==false&&v!=null)q.set(k,String(v));
    if(kind!=='portrait')q.set('safe',String(studio.getState().safeMode));
    q.set('offset',String(offset));q.set('limit',String(limit));return q;
   };
   const endpoint='/api/v1/asset-center/pose-gallery/'+(kind==='costume'?'costumes':kind==='pose'?'poses':'portraits');
   const cacheKey=kind+'\0'+String(params(0));
   const cached=refPageCache.get(cacheKey);
   const pickItem=entry=>kind==='pose'?(entry.group?entry.group.items[entry.active]||entry.group.items[0]:entry.item):kind==='costume'?(entry.item.views?.length?selectCostumeView(entry.item,entry.view||entry.item.selectedView||'front'):entry.item):entry.item;
   const picked=entry=>{
    const recipe=studio.getState().recipe;
    if(kind==='pose'&&entry.group)return entry.group.items.some(i=>i.id===recipe.pose?.id);
    return recipe[slot]?.id===(entry.item?.id);
   };
   const thumbOf=entry=>{
    const item=pickItem(entry);
    if(kind==='pose')return referenceImageUrl(poseThumbPath(item,studio.getState().poseDepthMode));
    if(kind==='costume')return localCostumeImageUrl(item.缩略图||item.预览图||item.原图);
    return referenceImageUrl(item.缩略图||item.预览图||item.原图);
   };
   const titleOf=entry=>{const item=pickItem(entry);return kind==='costume'?item.服装名称:kind==='pose'?(entry.group?entry.group.name:item.姿势名称):item.标题||item.发型名称;};
   const metaOf=entry=>{
    const item=pickItem(entry);
    if(kind==='costume')return [item.来源,item.分类].filter(Boolean).join(' · ');
    if(kind==='pose')return entry.group?[entry.group.system,entry.group.category,`${entry.group.items.length} 个角度`].filter(Boolean).join(' · '):[item.体系,item.分类,item.角度].filter(Boolean).join(' · ');
    return [item.分区,item.发长].filter(Boolean).join(' · ');
   };
   const updatePick=(btn,entry)=>{const on=picked(entry);setText(btn,on?'✓ 已选':'加入配方');btn.setAttribute('aria-pressed',String(on));};
   const togglePick=entry=>{
    const item=pickItem(entry);
    if(kind==='pose'&&entry.group&&picked(entry)&&studio.getState().recipe.pose?.id!==item.id){studio.setSlot('pose',{...item,useDepth:studio.getState().poseDepthMode});ctx.notice?.(`已选姿势：${item.姿势名称}（${item.角度}）`);return;}
    studio.toggleSlot(slot,item);
   };
   const cardFor=(entry,index)=>{
    const card=el('article','','costume-card ref-card');let angleStrip=null;const shot=el('div','','costume-shot'),open=button('',()=>refModal(index),'costume-open');
    bindAttribute(open,'aria-label','查看 '+titleOf(entry));
    const img=el('img');img.src=thumbOf(entry);img.loading=index<8?'eager':'lazy';img.decoding='async';bindAttribute(img,'alt',titleOf(entry)||'');
    if(kind==='pose')depthPickers.push(()=>{img.src=thumbOf(entry);});
    open.append(img);shot.append(open);
    const item=pickItem(entry);
    if(kind==='costume'&&item.敏感)shot.append(el('span','18+','ref-badge ref-badge-warn'));
    if(kind==='portrait'&&item.热门)shot.append(el('span','热门','ref-badge'));
    if(kind==='costume'&&item.views?.length)shot.append(el('span',`${item.views.length} 视角`,'ref-badge ref-badge-right'));
    const pick=button('加入配方',()=>togglePick(entry),'ref-pick');updatePick(pick,entry);pickers.push(()=>updatePick(pick,entry));const cardActions=el('div','','ref-card-actions');cardActions.append(pick);
    card.append(shot);
    if(kind==='pose'&&entry.group&&entry.group.items.length>1){
     const strip=el('div','','ref-angle-strip');
     for(const [i,angleItem]of entry.group.items.entries()){
      const b=button(angleItem.角度||String(i+1),()=>{entry.active=i;img.src=thumbOf(entry);for(const c of strip.children)c.setAttribute('aria-pressed',String(c===b));});
      b.setAttribute('aria-pressed',String(i===entry.active));
      const thumb=el('img');const drawThumb=()=>{thumb.src=referenceImageUrl(poseThumbPath(angleItem,studio.getState().poseDepthMode));};drawThumb();thumb.loading='lazy';bindAttribute(thumb,'alt','');depthPickers.push(drawThumb);b.replaceChildren(thumb,el('span',angleItem.角度||String(i+1)));
      b.addEventListener('mouseenter',()=>{img.src=referenceImageUrl(poseThumbPath(angleItem,studio.getState().poseDepthMode));});
      b.addEventListener('mouseleave',()=>{img.src=thumbOf(entry);});
      strip.append(b);
     }
     angleStrip=strip;
    }
    card.append(el('h3',titleOf(entry)||''),el('p',metaOf(entry),'costume-keys'));if(angleStrip)card.append(angleStrip);card.append(cardActions);
    return card;
   };
   const appendEntries=items=>{
    for(const raw of items||[]){
     const entry=kind==='pose'&&raw.items?{group:raw,active:0}:{item:raw};
     pageItems.push(entry);grid.append(cardFor(entry,pageItems.length-1));
    }
   };
   const sig=list=>(list||[]).map(x=>x.key||x.id).join('|');
   const unit=kind==='pose'&&st.view==='group'?'组':kind==='costume'?'套':'张';
   const moreText=()=>`加载更多（剩余 ${Math.max(0,total-pageItems.length).toLocaleString('zh-CN')} ${unit}）`;
   async function pull(){
    if(pagingBusy||next==null||!active(g)||!grid.isConnected)return;
    pagingBusy=true;const cursor=next;pageError?.remove();pageError=null;
    if(moreBtn){moreBtn.disabled=true;setText(moreBtn,'加载中…');}grid.setAttribute('aria-busy','true');
    try{
     const more=await get(endpoint+'?'+params(cursor,60));
     if(!active(g)||!grid.isConnected)return;
     if(!Array.isArray(more.items)||more.next_offset!=null&&(!Number.isInteger(more.next_offset)||more.next_offset<=cursor))throw new Error('参考图分页数据无效');
     appendEntries(more.items);next=more.next_offset??null;total=Number(more.total??total);
     setText(count,total.toLocaleString('zh-CN')+' '+unit);
     if(next==null){moreBtn?.remove();showRefComplete();}else if(moreBtn)setText(moreBtn,moreText());
    }catch(error){
     if(!active(g))return;
     pageError=el('p','加载失败，已显示的参考图仍可用。请重试。','center-load-error');pageError.setAttribute('role','status');root.append(pageError);
     if(moreBtn)setText(moreBtn,'重试加载');ctx.notice?.(error.message);
    }finally{pagingBusy=false;if(active(g)){grid.setAttribute('aria-busy','false');if(moreBtn)moreBtn.disabled=false;}}
   }
   function refModal(index){
    let cursor=index;if(!pageItems[cursor])return;
    closeCostumeDialogs();
    const dialog=el('dialog','','costume-modal ref-modal'),viewport=el('div','','center-zoom-viewport'),img=el('img');viewport.append(img);
    const caption=el('p'),down=el('a','下载原图'),original=el('a','新窗口原图'),levelEl=el('span','100%','center-zoom-level'),extra=el('div','','ref-modal-switch'),details=el('section','','ref-modal-details');
    down.target='_blank';down.rel='noopener';
    original.target='_blank';original.rel='noopener';
    const copy=(label,value,message)=>button(label,async()=>{
     if(!navigator.clipboard?.writeText)throw new Error('无法访问剪贴板，请手动选择并复制');
     await navigator.clipboard.writeText(value);ctx.notice?.(message);
    });
    const detailFields=rows=>{
     const list=el('dl');
     for(const [label,value]of rows)if(value){list.append(el('dt',label),el('dd',value));}
     details.append(list);
    };
    const zoomCtrl=attachImageZoomPan(viewport,img,{onScaleChange:({percent})=>setText(levelEl,`${percent}%`)});
    const pick=button('加入配方',()=>{togglePick(pageItems[cursor]);updatePick(pick,pageItems[cursor]);},'ref-pick-modal');
    const fullOf=entry=>{const item=pickItem(entry);if(kind==='pose')return poseImagePath(item,studio.getState().poseDepthMode);if(kind==='costume')return item.预览图||item.原图||item.缩略图;return item.原图||item.缩略图;};
    const resolveModalUrl=raw=>kind==='costume'?localCostumeImageUrl(raw):referenceImageUrl(raw);
    const show=()=>{
     const entry=pageItems[cursor];if(!entry)return;const item=pickItem(entry);
     img.src=resolveModalUrl(fullOf(entry));bindAttribute(img,'alt',titleOf(entry)||'');
     setText(caption,[item.id,titleOf(entry),metaOf(entry)].filter(Boolean).join(' · '));
     down.href=resolveModalUrl(kind==='pose'?fullOf(entry):item.原图||fullOf(entry));original.href=down.href;
     const suffix=kind==='pose'?(studio.getState().poseDepthMode?'_depth.webp':'.png'):String(item.原图||'').match(/\.[a-z0-9]+$/i)?.[0]||'.webp';
     down.setAttribute('download',String(item.id||'reference')+suffix);
     details.replaceChildren();
     const identity=el('div','','ref-modal-identity'),label=kind==='pose'?'姿势':kind==='portrait'?'人像':'服装';
     identity.append(el('code',item.id),copy(`复制${label} ID`,String(item.id),`已复制${label} ID`));details.append(identity);
     if(kind==='costume'){
      detailFields([['来源',item.来源],['分类',item.分类],['中文单品与色彩标签',(item.标签||[]).join(' · ')]]);
      const prompt=el('div','','ref-modal-prompt');prompt.append(el('strong','英文 Prompt 词条'),copy('复制英文服装 Prompt',item.关键词||'','已复制英文服装 Prompt'),el('pre',item.关键词||''));details.append(prompt);
      if(item.source==='shisei'){
       details.append(el('p','Shisei / wquguru · CC0 · AI 生成服装参考，并非专业复原。'));
       const base='https://github.com/wquguru/shisei',revision='8f61ceab10e45f8d3afd254900903733a0ba76ee';
       for(const [label,url]of [['原仓库',base],['条目目录（固定版本）',`${base}/blob/${revision}/data/costumes.json`],['图片许可证（CC0）',`${base}/blob/${revision}/LICENSE-images`]]){
        const link=el('a',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';details.append(link);
       }
      }
      if(item.source==='charadb')details.append(el('p','图片仅作参考，禁止真人、未成年人及再分发；请查看原作者条件。'));
      if(item.来源地址){const source=el('a','查看来源与使用说明');source.href=item.来源地址;source.target='_blank';source.rel='noopener noreferrer';details.append(source);}
     }else if(kind==='pose'){
      detailFields([['所属体系',item.体系],['动作分类',item.分类],['当前角度',item.角度],['当前模式',studio.getState().poseDepthMode?'深度图 (Depth Map)':'3D 素体白模'],['原图尺寸','900 × 1200 '+(studio.getState().poseDepthMode?'WebP':'PNG')]]);
     }else detailFields([['分区',item.分区],['发长',item.发长],['发型款式',item.发型名称],['原图尺寸',item.宽&&item.高?`${item.宽} × ${item.高}`:''],['授权协议','CC0 1.0（来源标注）']]);
     extra.replaceChildren();
     if(kind==='costume'&&entry.item.views?.length){
      for(const view of entry.item.views){const b=button(view.label,()=>{entry.view=view.id;show();});b.setAttribute('aria-pressed',String((entry.view||entry.item.selectedView||'front')===view.id));extra.append(b);}
     }
     if(kind==='pose'){
      for(const [depth,label]of [[false,'白模'],[true,'Depth']]){const b=button(label,()=>{studio.setPoseDepthMode(depth);show();});b.setAttribute('aria-pressed',String(studio.getState().poseDepthMode===depth));extra.append(b);}
      if(entry.group)for(const [i,angleItem]of entry.group.items.entries()){const b=button(angleItem.角度||String(i+1),()=>{entry.active=i;show();});b.setAttribute('aria-pressed',String(entry.active===i));extra.append(b);}
     }
     updatePick(pick,entry);zoomCtrl.reset();
    };
    const stepItem=async delta=>{const target=cursor+delta;if(target>=pageItems.length&&delta>0)await pull();if(!dialog.isConnected||target<0||target>=pageItems.length)return;cursor=target;show();};
    const bar=el('div','','costume-modal-bar');
    bar.append(button('缩小',()=>zoomCtrl.zoomOut()),levelEl,button('适应窗口',()=>zoomCtrl.reset()),button('放大',()=>zoomCtrl.zoomIn()),button('上一张',()=>stepItem(-1)),button('下一张',()=>stepItem(1)),pick,down,original,button('关闭',()=>dialog.close()));
    dialog.append(viewport,extra,caption,details,bar);
    dialog.addEventListener('keydown',event=>{
     if(event.key==='ArrowRight'){event.preventDefault?.();stepItem(1);}else if(event.key==='ArrowLeft'){event.preventDefault?.();stepItem(-1);}
     else if(event.key==='+'||event.key==='='){event.preventDefault?.();zoomCtrl.zoomIn();}else if(event.key==='-'){event.preventDefault?.();zoomCtrl.zoomOut();}else if(event.key==='0'){event.preventDefault?.();zoomCtrl.reset();}
    });
    dialog.addEventListener('click',event=>{if(zoomCtrl.consumeMoved())return;if(event.target===dialog)dialog.close();});
    refreshModal=show;
    dialog.addEventListener('close',()=>{if(refreshModal===show)refreshModal=null;dialog.remove();});
    (document.body||root).append(dialog);dialog.showModal();show();
   }
   const showRefComplete=()=>{if(pageItems.length&&!root.querySelector('.ref-load-complete')){const complete=el('p',`已显示全部 ${pageItems.length.toLocaleString('zh-CN')} ${unit}`,'center-load-status ref-load-complete');complete.setAttribute('role','status');root.append(complete);}};
   if(cached){appendEntries(cached.items);if(!pageItems.length)grid.append(el('p','没有符合条件的参考图','costume-empty'));next=cached.next_offset??null;setText(count,Number(cached.total||0).toLocaleString('zh-CN')+' '+unit);}
   root.append(grid);
   grid.setAttribute('aria-busy','true');
   refPickers=pickers;
   mountDock();
   const data=await get(endpoint+'?'+params(0));
   if(!active(g))return;
   grid.setAttribute('aria-busy','false');
   refSummary[kind]=data;refPageCache.set(cacheKey,data);
   if(kind==='costume'){
    fillSelect(selects.top,'全部类型',(data.tops||[]).map(t=>[t.name,`${t.name} ${t.count}`]),st.top);
    fillSelect(selects.source,'全部来源',(data.sources||[]).map(s=>[s.id,`${s.label} ${s.count}`]),st.source);
    fillSelect(selects.tag,'全部标签',(data.tags||[]).map(t=>[t.name,`${t.name} ${t.count}`]),st.tag);
   }else if(kind==='pose'){
    fillSelect(selects.system,'全部体系',(data.systems||[]).map(s=>[s.name,`${s.name} ${s.count}`]),st.system);
    fillSelect(selects.angle,'全部角度',(data.angles||[]).map(a=>[a,a]),st.angle);
   }else{
    fillSelect(selects.section,'全部分区',(data.sections||[]).map(s=>[s.name,`${s.name} ${s.count}`]),st.section);
    fillSelect(selects.style,'全部发型',(data.hair_styles||[]).map(s=>[s.name,`${s.name} ${s.count}`]),st.style);
   }
   syncPills(data);
   total=Number(data.total||0);
   setText(count,total.toLocaleString('zh-CN')+' '+unit+(data.hidden_sensitive_count&&studio.getState().safeMode?` · 已隐藏 ${data.hidden_sensitive_count} 项 18+`:''));
   if(!cached||sig(data.items)!==sig(pageItems.map(e=>e.group||e.item))){
    pageItems.length=0;pickers.length=0;depthPickers.length=0;grid.replaceChildren();appendEntries(data.items);
    if(!pageItems.length)grid.append(el('p','没有符合条件的参考图','costume-empty'));
   }
   next=data.next_offset??null;
   moreBtn=button(moreText(),pull,'costume-more');
   if(next!=null)root.append(moreBtn);else showRefComplete();

  }
  function fillSelect(select,allLabel,choices,value){
   if(!select)return;
   const wanted=[['',allLabel],...choices];
   const current=[...(select.options||select.children||[])].map(o=>o.value);
   if(current.length===wanted.length&&current.every((v,i)=>v===wanted[i][0])){
    for(const [i,[,label]]of wanted.entries()){const o=(select.options||select.children)[i];if(o)setText(o,label);}
   }else{
    select.replaceChildren();for(const [v,l]of wanted)select.append(localizedOption(v,l));
   }
   select.value=value&&wanted.some(([v])=>v===value)?value:'';
  }
  function switchKind(value){
   clearTimeout(costumeTimer);stopCostumeObserver();closeCostumeDialogs();
   if(value)filters.asset_kind=value;else delete filters.asset_kind;
   if(value&&value!=='character'){delete filters.role_level;delete filters.age_band;delete filters.gender;delete filters.role_tag;}
   refFocus='';offset=0;syncKindRoute();
   return load();
  }
  function syncKindRoute(){
   if(!official||canvas||typeof window==='undefined'||typeof location==='undefined'||!location?.search?.includes('page=asset-center'))return;
   const route=new URLSearchParams(location.search);
   if(filters.asset_kind)route.set('kind',filters.asset_kind);else route.delete('kind');
   const nextSearch='?'+route;if(location.search!==nextSearch)history.replaceState?.(null,'',nextSearch);
  }
  function composeNavigate(){
   if(ctx.navigate)return ctx.navigate('character-studio');
   if(typeof location!=='undefined')location.href='/?page=character-studio';
  }
  function mountDock(){
   if(canvas||refDock)return;
   refDock=studio.mountRecipeDock(root,{onCompose:composeNavigate,force:REF_KINDS.has(filters.asset_kind||'')});
  }
  function unmountRefs(){
   characterHistory?.suspend();characterHistory=null;
   refDock?.destroy();refDock=null;refPickers=[];refreshRefDepth=null;
  }

 async function officialCatalog(g){
  if(!canvas&&filters.asset_kind==='composite'){
   const form=el('div','','center-official-filters'),tabs=el('div','','center-official-kinds');
   for(const [value,title]of browseKinds){
    const n=button(title,()=>switchKind(value));n.setAttribute('aria-pressed',String(value==='composite'));tabs.append(n);
   }
   form.append(tabs);root.append(form);revealActiveKind(tabs);
   const host=el('div');root.append(host);
   characterHistory=createCharacterHistory(host,ctx,{onCompose:composeNavigate,onZoom:(src,title)=>openAssetImageViewer({src,title,host:document.body||root})});
   characterHistory.load();return;
  }
  if(REF_KINDS.has(filters.asset_kind||'')){refSafe=studio.getState().safeMode;refDepth=studio.getState().poseDepthMode;return referenceBrowser(g,filters.asset_kind);}
  if(workbench&&!canvas){document.addEventListener?.('pointerdown',closeCardMenus,true);document.addEventListener?.('keydown',closeCardMenus,true);}
  const form=el('form','','center-official-filters');
  const filterHost=workbench?el('div','','center-official-filter-row'):form;
  const selectFilter=(key,label,choices)=>{
   const select=field(filterHost,label,'select');select.append(localizedOption('',label));
   for(const [value,title]of choices)select.append(localizedOption(value,title));
   select.value=filters[key]||'';
   select.onchange=()=>{if(select.value)filters[key]=select.value;else delete filters[key];offset=0;return load();};
   return select;
  };
  let count;
  if(workbench){
   const tabs=el('div','','center-official-kinds');
   for(const [value,title]of browseKinds){
    const n=button(title,()=>switchKind(value));
    n.setAttribute('aria-pressed',String((filters.asset_kind||'')===value));
    tabs.append(n);
   }
   count=el('span','加载中…','center-count');count.setAttribute('role','status');
   form.append(tabs,filterHost);
  }else{
   selectFilter('asset_kind',msg('asset.asset_type'),officialSelectKinds);
  }
  const currentKind=filters.asset_kind||'';
  let roleTagSelect=null;
  if(!currentKind||currentKind==='character'){
   selectFilter('role_level','角色级别',[['lead','主角'],['supporting','配角'],['extra','群演']]);
   const bands=[['child|male','幼年男'],['child|female','幼年女'],['teen|male','少年男'],['teen|female','少年女'],['young_adult|male','青年男'],['young_adult|female','青年女'],['middle_aged|male','中年男'],['middle_aged|female','中年女'],['senior|male','老年男'],['senior|female','老年女']];
   const band=field(filterHost,'人物档','select');band.append(localizedOption('','人物档'));
   for(const [value,title]of bands)band.append(localizedOption(value,title));
   const currentBand=filters.age_band&&filters.gender?filters.age_band+'|'+filters.gender:'';
   band.value=bands.some(([value])=>value===currentBand)?currentBand:'';
   band.onchange=()=>{const [age,gender]=(band.value||'|').split('|');if(age)filters.age_band=age;else delete filters.age_band;if(gender)filters.gender=gender;else delete filters.gender;delete filters.role_tag;offset=0;return load();};
   const cachedTags=facetCache.get(currentKind||'all')||[];
   if(cachedTags.length||workbench)roleTagSelect=selectFilter('role_tag','风格/角色标签',cachedTags.map(t=>[t,t]));
  }
  const search=field(filterHost,msg('gallery.search'),'input',filters.query||'');search.type='search';bindAttribute(search,'placeholder','搜索名称或标签');
  search.oninput=()=>{filters.query=search.value;officialSearchFocus=true;officialSearchCaret=search.selectionStart;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;load();},300);};
  if(workbench){filterHost.prepend(search.parentElement);filterHost.append(count);}
  const submit=el('button',msg('ui.search'));submit.type='submit';form.append(submit);
  const hasClearable=workbench
   ?['query','role_level','age_band','gender','role_tag','tag','form_name'].some(k=>filters[k])
   :Object.keys(filters).some(k=>filters[k]);
  if(hasClearable){
   filterHost.append(button('清空筛选',()=>{
    const keepKind=workbench?filters.asset_kind:'';
    filters=keepKind?{asset_kind:keepKind}:{};
    offset=0;return load();
   },'center-clear-filters'));
  }
  form.onsubmit=e=>{e.preventDefault();clearTimeout(searchTimer);offset=0;load();};
  root.append(form);if(workbench)revealActiveKind(form.querySelector('.center-official-kinds'));if(officialSearchFocus){search.focus?.({preventScroll:true});if(officialSearchCaret!=null)search.setSelectionRange?.(officialSearchCaret,officialSearchCaret);officialSearchFocus=false;}

  const reqFilters={...filters,order_by:filters.order_by||'latest',source:'official',media_only:'true',offset,limit:24};
  for(const k of Object.keys(reqFilters))if(reqFilters[k]===''||reqFilters[k]==null)delete reqFilters[k];
  const queryStr=String(new URLSearchParams(reqFilters));
  const officialSig=list=>(list||[]).map(r=>`${r.id}:${r.version_id}:${r.title}:${r.download_count||0}`).join('|');
  const renderOfficialCard=(row,index=24)=>{
   const card=el('article','','center-card');const members=visibleMembers(row),member=members.find(m=>m.modality==='image')||members[0],cover=el('div','','center-cover');
   if(member){
    if(member.modality==='image'){
     const open=button('',()=>detail(row,g),'center-preview'),imgNode=picture(member);
     if(workbench){imgNode.loading=index<12?'eager':'lazy';imgNode.decoding='async';}
     bindAttribute(open,'aria-label','查看资产详情 '+row.title);open.append(imgNode);draggable(open,row,member);cover.append(open);
    }else{const media=picture(member);draggable(media,row,member);cover.append(media);}
   }
   const badge=el('span',assetKind(row)==='character'?'人设':kinds.find(k=>k[0]===assetKind(row))?.[1]||msg('gallery.other'),'center-kind-badge');
   cover.append(badge);
   if(row.source==='official'&&row.official)cover.append(el('span','官方','center-official-badge'));
   card.append(cover);
   const heading=el('h2'),open=button(row.title,()=>detail(row,g));bindAttribute(open,'title',row.title);heading.append(open);card.append(heading);
   if(workbench&&row.official){
    const labels={lead:'主角',supporting:'配角',extra:'群演'},bands={'child|male':'幼年男','child|female':'幼年女','teen|male':'少年男','teen|female':'少年女','young_adult|male':'青年男','young_adult|female':'青年女','middle_aged|male':'中年男','middle_aged|female':'中年女','senior|male':'老年男','senior|female':'老年女'},tags=el('div','','center-official-tags');
    const band=bands[row.official.age_band+'|'+row.official.gender];
    for(const value of [labels[row.official.role_level],band])if(value)tags.append(el('span',value));
    card.append(tags);
   }
   if(member){
    const actions=el('div','','center-actions');
    const refLabel=onReference?msg('ui.send_to_canvas'):msg('gallery.create_reference'),ref=button(refLabel,()=>members.length===1&&(onReference||member.modality==='image')?reference(row,member):detail(row,g)),add=button(msg('gallery.add_project'),()=>members.length===1?addToProjects(row,member):detail(row,g));
    if(workbench&&!canvas){setText(ref,'引用生成');bindAttribute(ref,'aria-label','引用生成');actions.className='center-actions center-card-tools';actions.append(ref,cardMenu(row.title,[['查看详情',()=>detail(row,g)],[msg('gallery.add_project'),()=>members.length===1?addToProjects(row,member):detail(row,g)]]));card.append(actions);}
    else{actions.append(ref,add);card.append(actions);}
   }
   return card;
  };
  const grid=el('div','','center-grid');
  const cached=workbench?officialPageCache.get(queryStr):null;
  if(workbench){
   if(cached){
    if(cached.facets?.role_tag?.length&&roleTagSelect&&roleTagSelect.options.length<=1){
     for(const t of cached.facets.role_tag)roleTagSelect.append(localizedOption(t,t));
     roleTagSelect.value=filters.role_tag||'';
    }
    setText(count,cached.total+' 个资产');
    for(const [idx,row]of (cached.items||[]).entries())grid.append(renderOfficialCard(row,idx));
    if(!(cached.items||[]).length){const empty=el('section','','center-empty');empty.append(el('p','暂无资产'));grid.append(empty);}
   }
   root.append(grid);
   grid.setAttribute('aria-busy','true');
  }
  const data=await get('/api/v1/asset-center?'+queryStr);
  if(!active(g))return;
  grid.setAttribute('aria-busy','false');
  if(workbench)officialPageCache.set(queryStr,data);
  if(data.facets?.role_tag?.length){
   facetCache.set(currentKind||'all',data.facets.role_tag);
   if(roleTagSelect&&roleTagSelect.options.length<=1){
    for(const t of data.facets.role_tag)roleTagSelect.append(localizedOption(t,t));
    roleTagSelect.value=filters.role_tag||'';
   }
  }
  if(workbench){
   setText(count,data.total+' 个资产');
   if(!cached||officialSig(data.items)!==officialSig(cached.items)){
    grid.replaceChildren();
    for(const [idx,row]of data.items.entries())grid.append(renderOfficialCard(row,idx));
    if(!data.items.length){const empty=el('section','','center-empty');empty.append(el('p','暂无资产'));grid.append(empty);}
   }
  }else{
   count=el('p','共'+data.total+'个资产','center-count');count.setAttribute('role','status');root.append(count);
   for(const [idx,row]of data.items.entries())grid.append(renderOfficialCard(row,idx));
   if(!data.items.length){const empty=el('section','','center-empty');empty.append(el('p','暂无资产'));grid.append(empty);}
   root.append(grid);
  }
  if(officialDrawerRow&&data.items.some(r=>r.id===officialDrawerRow.id))await detail(officialDrawerRow,g);
  if(workbench&&!canvas){
   const footer=el('div','','center-continuous'),status=el('span','','center-load-status'),more=button('加载更多',()=>{failed=false;return pullOfficial();},'center-load-more'),sentinel=el('div','','center-load-sentinel');
   status.setAttribute('role','status');status.setAttribute('aria-live','polite');footer.append(status,more,sentinel);root.append(footer);
   let next=data.next_offset??null,total=Number(data.total||0),loaded=data.items.length,busy=false,failed=false,visible=false;
   const seen=new Set(data.items.map(r=>r.id));
   const observerAvailable=typeof IntersectionObserver==='function';
   const update=()=>{setText(status,failed?'加载失败，已显示的资产仍可用。':busy?'正在加载更多资产…':next==null?`已显示全部 ${loaded} 个资产`:`已显示 ${loaded} / ${total} 个资产`);setText(more,failed?'重试加载':'加载更多');more.disabled=busy;more.hidden=next==null||observerAvailable&&!failed;grid.setAttribute('aria-busy',String(busy));};
   async function pullOfficial(){
    if(busy||failed||next==null||!active(g)||!grid.isConnected)return;
    busy=true;const cursor=next;update();
    try{
     const q=new URLSearchParams(reqFilters);q.set('offset',String(cursor));
     const page=await get('/api/v1/asset-center?'+q);
     if(!active(g)||!grid.isConnected)return;
     if(!Array.isArray(page.items)||page.next_offset!=null&&(!Number.isInteger(page.next_offset)||page.next_offset<=cursor))throw new Error('资产分页数据无效');
     for(const row of page.items)if(!seen.has(row.id)){seen.add(row.id);grid.append(renderOfficialCard(row,loaded++));}
     next=page.next_offset??null;total=Number(page.total??total);
    }catch(error){if(active(g)){failed=true;ctx.notice?.(error.message);}}
    finally{
     busy=false;
     if(active(g)){
      update();if(next==null)stopCostumeObserver();
      else if(!failed&&visible&&costumeObserver&&typeof costumeObserver.unobserve==='function'&&typeof requestAnimationFrame==='function')requestAnimationFrame(()=>{if(active(g)&&costumeObserver){costumeObserver.unobserve(sentinel);costumeObserver.observe(sentinel);}});
     }
    }
   }
   update();
   if(next!=null&&observerAvailable){
    costumeObserver=new IntersectionObserver(entries=>{for(const entry of entries)visible=Boolean(entry.isIntersecting);if(visible)pullOfficial();},{root:findScrollContainer(root)||null,rootMargin:'0px 0px 480px 0px'});
    costumeObserver.observe(sentinel);
   }
  }else if(data.total>24)paging(data.total,data.next_offset,g);
 }
 function addToProjects(row,member){return official?quickAddProjects(row,member):quickAdd(row,member,'add');}
 async function quickAddProjects(row,member){
  const g=generation,actor=session().actor,key=singleKey();let intent=readKey(key);
  if(intent&&(intent.action!=='multi-add'||intent.row.version_id!==row.version_id||intent.member.member_key!==member.member_key)){ctx.notice(msg('gallery.finish_pending'));return;}
  const dialog=modal(msg('gallery.add_project'),'center-project-picker'),valid=()=>active(g)&&dialog.isConnected&&session().actor===actor,projects=ctx.projects().filter(p=>!p.read_only&&!p.unavailable&&!['vsc.text-tools','vsc.creative-tools'].includes(p.profile_id||p.profile));
  dialog.append(el('p',row.title));
  const search=field(dialog,'搜索项目','input','');search.type='search';bindAttribute(search,'placeholder','搜索项目…');
  const list=el('div','','center-project-list');const choices=[];
  for(const p of projects){
   const label=el('label',p.name),check=el('input');check.type='checkbox';
   check.checked=intent?intent.projects.some(i=>i.project===p.id):ctx.projectId?.()===p.id;
   check.onchange=()=>updateCount();label.prepend(check);list.append(label);choices.push({project:p.id,check,label,name:p.name});
  }
  search.oninput=()=>{for(const item of choices)item.label.hidden=!item.name.toLowerCase().includes(search.value.toLowerCase());};
  dialog.append(list);
  const role=roles[assetKind(row)],allowed=role&&(row.allowed_purposes.includes('*')||row.allowed_purposes.includes(role))&&(member.modality==='image'&&assetKind(row)!=='voice'||member.modality==='audio'&&assetKind(row)==='voice'),status=el('p'),receipts=el('div'),count=el('p');
  status.setAttribute('role','status');dialog.append(count,status,receipts);let busy=false;
  function updateCount(){setText(count,'已选 '+choices.filter(i=>i.check.checked).length+' 个项目');}updateCount();
  const save=()=>{keepKey(key,intent);if(active(g))pendingBanner();},lock=()=>{for(const i of choices)i.check.disabled=busy||!!intent;},show=()=>{receipts.replaceChildren();for(const item of intent?.projects||[]){const line=el('p',(projects.find(p=>p.id===item.project)?.name||'目标项目')+'：'+(item.result?'已添加':item.error||'等待'));if(item.result){const link=el('a',msg('ui.view_project_assets'));link.href='/?'+new URLSearchParams({page:'assets',project:item.project});line.append(link);}receipts.append(line);}};
  const rebase=button(msg('gallery.refresh_rejected'),()=>{for(const item of intent?.projects||[])if(item.rejected){delete item.request;delete item.rejected;}save();rebase.hidden=true;setText(status,msg('gallery.recheck_ready'));});
  rebase.hidden=!intent?.projects.some(i=>i.rejected);dialog.append(rebase);
  const confirm=button(intent?msg('gallery.continue_request'):msg('gallery.add_project'),async()=>{
   if(!allowed)throw new Error(String(msg('gallery.no_usage')));
   busy=true;lock();
   try{
    if(!intent){const selected=choices.filter(i=>i.check.checked);if(!selected.length)throw new Error('请至少选择一个项目');intent={row,member,action:'multi-add',kind:assetKind(row),role,projects:selected.map(i=>({project:i.project}))};save();lock();}
    if(!intent.cart){const result=await post('/api/v1/asset-center/cart',{library_version_id:row.version_id,member_key:member.member_key,active:true});intent.cart=result.id;save();}
    if(!valid())return;
    for(const item of intent.projects){
     if(item.result)continue;if(!valid())return;
     try{
      if(!item.request){const tree=await get(`/api/v1/projects/${item.project}/tree`);if(!valid())return;item.request={payload:{cart_id:intent.cart,asset_kind:intent.kind,role:intent.role},expected_revision:tree.revision,idempotency_key:crypto.randomUUID()};save();}
      item.result=await ctx.api(`/api/v1/projects/${item.project}/asset-center/import`,{method:'POST',headers:headers(),body:JSON.stringify(item.request)});
      delete item.error;delete item.rejected;save();if(!valid())return;ctx.setRevision?.(item.result.revision,item.project);
     }catch(e){item.error=e.message;if(e.status===409&&e.code==='revision_conflict')item.rejected=true;save();}
     if(!valid())return;show();
    }
    if(intent.projects.every(i=>i.result)){keepKey(key,null);pendingBanner();setText(confirm,msg('gallery.completed'));confirm.disabled=true;setText(status,msg('gallery.added'));}
    else{setText(confirm,msg('gallery.continue_request'));setText(status,'部分项目尚未完成，可继续原请求。');rebase.hidden=!intent.projects.some(i=>i.rejected);}
   }catch(e){if(valid()){setText(status,msg('gallery.failed_retained',{error:e.message}));setText(confirm,msg('gallery.continue_request'));}}
   finally{busy=false;lock();}
  });
  dialog.append(confirm,button(msg('common.cancel'),()=>dialog.close()));
  confirm.disabled=!projects.length||!allowed;
  if(!projects.length)setText(status,msg('gallery.no_projects'));else if(!allowed)setText(status,msg('gallery.no_usage'));
  lock();show();
 }

 async function quickAdd(row,member,action){
  const g=generation,actor=session().actor,key=singleKey();let intent=readKey(key);
  if(intent&&(intent.row.version_id!==row.version_id||intent.member.member_key!==member.member_key||intent.action!==action)){ctx.notice(msg('gallery.finish_pending'));return;}
  const retained=!!intent,dialog=modal(msg(action==='reference'?'gallery.create_reference':'gallery.add_project')),valid=()=>active(g)&&dialog.isConnected&&session().actor===actor;
  dialog.append(el('p',row.title),picture(member),el('p',msg(action==='reference'?'gallery.reference_help':'gallery.import_help')));
  const projects=ctx.projects().filter(p=>!p.read_only&&!p.unavailable&&!['vsc.text-tools','vsc.creative-tools'].includes(p.profile_id||p.profile)),project=field(dialog,msg('gallery.target_project'),'select');
  project.append(localizedOption('',msg('gallery.choose_project')));for(const p of projects)project.append(localizedOption(p.id,p.name));project.value=intent?.project||ctx.projectId?.()||'';
  const allowed=role=>row.allowed_purposes.includes('*')||row.allowed_purposes.includes(role),newKinds=kinds.filter(([code])=>roles[code]&&code!=='creature'&&allowed(roles[code])&&(member.modality==='audio'?code==='voice':member.modality==='image'&&code!=='voice'));
  const kind=field(dialog,msg('gallery.destination'),'select');for(const [code,title]of newKinds)kind.append(localizedOption(code,msg('gallery.new_asset',{type:title})));
  const shotRoles=member.modality==='video'?['video_take']:member.modality==='audio'?['reference_audio']:['first_frame','last_frame','composition','storyboard','prop'];
  const availableRoles=shotRoles.filter(allowed);if(availableRoles.length)kind.append(localizedOption('shot',msg('gallery.existing_shot')));
  kind.value=intent?.kind||(newKinds.some(([k])=>k===assetKind(row))?assetKind(row):newKinds[0]?.[0]||(availableRoles.length?'shot':''));
  const shot=field(dialog,msg('gallery.target_shot'),'select'),purpose=field(dialog,msg('gallery.usage'),'select');
  for(const role of availableRoles)purpose.append(localizedOption(role,msg('gallery.role_'+role)));
  purpose.value=intent?.role||availableRoles[0]||'';
  const status=el('p');status.setAttribute('role','status');const receipt=el('div');dialog.append(status,receipt);
  let targetSerial=0,busy=false,stage=null;
  const save=()=>{keepKey(key,intent);if(active(g))pendingBanner();};
  const refreshTargets=async()=>{
   const t=++targetSerial;shot.replaceChildren(localizedOption('',msg('gallery.choose_shot')));
   shot.parentElement.hidden=purpose.parentElement.hidden=kind.value!=='shot';
   if(kind.value!=='shot'||!project.value)return;
   const p=project.value;
   try{
    const tree=await get(`/api/v1/projects/${p}/tree`);if(!valid()||t!==targetSerial||p!==project.value)return;
    for(const n of tree.nodes.filter(n=>n.kind==='shot'))shot.append(localizedOption(n.id,n.title||n.display_code));
    shot.value=intent?.target_object_id||'';
    if(!shot.options.length||shot.options.length===1)setText(status,msg('gallery.no_shots'));
   }catch(e){if(valid()&&t===targetSerial)setText(status,e.message);}
  };
  const controls=[project,kind,shot,purpose],lock=()=>controls.forEach(n=>{n.disabled=!!intent||busy;});
  project.onchange=()=>refreshTargets();kind.onchange=()=>refreshTargets();
  function showResult(){
   receipt.replaceChildren();if(!intent?.result)return;
   const a=el('a',msg(intent.kind==='shot'?'gallery.view_shot':'ui.view_project_assets'));
   a.href='/?'+new URLSearchParams({page:intent.kind==='shot'?'classic-production':'assets',project:intent.project,...(intent.kind==='shot'?{scope:intent.target_object_id,modality:member.modality==='video'?'video':'image'}:{})});
   receipt.append(a);
   if(intent.canvas){const link=el('a',msg('gallery.open_canvas'));link.href='/?'+new URLSearchParams({page:'creative-canvas',project:intent.project,task_target:intent.canvas.id});receipt.append(link);}
   setText(status,msg(intent.canvas?'gallery.reference_ready':'gallery.added'));
  }
  const rebase=button(msg('gallery.refresh_rejected'),async()=>{if(!intent?.rejected)return;const which=intent.rejected;delete intent[which==='import'?'request':'canvas_request'];delete intent.rejected;save();rebase.hidden=true;setText(status,msg('gallery.recheck_ready'));});
  rebase.hidden=!intent?.rejected;dialog.append(rebase);
  const submit=button(retained?msg('gallery.continue_request'):msg(action==='reference'?'gallery.create_reference':'gallery.add_project'),async()=>{
   busy=true;stage=null;lock();
   try{
    if(!intent){if(!project.value||!kind.value||(kind.value==='shot'&&!shot.value))throw new Error(String(msg('gallery.choose_destination')));intent={row,member,action,project:project.value,kind:kind.value,role:kind.value==='shot'?purpose.value:roles[kind.value],target_object_id:kind.value==='shot'?shot.value:null};save();lock();}
    if(!intent.cart){const result=await post('/api/v1/asset-center/cart',{library_version_id:row.version_id,member_key:member.member_key,active:true});intent.cart=result.id;save();}
    if(!valid())return;
    if(!intent.result){
     if(!intent.request){const tree=await get(`/api/v1/projects/${intent.project}/tree`);if(!valid())return;intent.request={payload:{cart_id:intent.cart,role:intent.role,...(intent.kind==='shot'?{target_object_id:intent.target_object_id}:{asset_kind:intent.kind})},expected_revision:tree.revision,idempotency_key:crypto.randomUUID()};save();}
     stage='import';intent.result=await ctx.api(`/api/v1/projects/${intent.project}/asset-center/import`,{method:'POST',headers:headers(),body:JSON.stringify(itemRequest(intent.request))});stage=null;delete intent.rejected;save();if(!valid())return;ctx.setRevision?.(intent.result.revision,intent.project);showResult();
    }
    if(action==='reference'&&!intent.canvas){
     if(!intent.canvas_request){const tree=await get(`/api/v1/projects/${intent.project}/tree`);if(!valid())return;intent.canvas_request={payload:{episode_id:null,title:row.title,document:{nodes:[{id:'reference',type:'image',title:row.title,media_id:intent.result.media_id,x:80,y:120},{id:'output',type:'image',title:row.title,text:'',x:440,y:120}],edges:[{id:'reference-edge',source:'reference',target:'output',port:'reference'}]}},expected_revision:tree.revision,idempotency_key:crypto.randomUUID()};save();}
     stage='canvas';intent.canvas=await ctx.api(`/api/v1/projects/${intent.project}/creative-canvases`,{method:'POST',headers:headers(),body:JSON.stringify(intent.canvas_request)});stage=null;delete intent.rejected;save();if(!valid())return;ctx.setRevision?.(intent.canvas.revision,intent.project);
    }
    if(!valid())return;showResult();keepKey(key,null);pendingBanner();submit.disabled=true;setText(submit,msg('gallery.completed'));
   }catch(e){
    if(stage&&e.status===409&&e.code==='revision_conflict'){intent.rejected=stage;save();}
    if(valid()){rebase.hidden=!intent?.rejected;setText(status,msg('gallery.failed_retained',{error:e.message}));setText(submit,msg('gallery.continue_request'));}
   }finally{busy=false;lock();if(intent?.result&&(action!=='reference'||intent.canvas))submit.disabled=true;}
  });
  dialog.append(submit,button(msg('common.close'),()=>dialog.close()));
  if(!projects.length)setText(status,msg('gallery.no_projects'));else if(!kind.value)setText(status,msg('gallery.no_usage'));
  submit.disabled=!projects.length||!kind.value;lock();await refreshTargets();if(valid())showResult();
 }
 function itemRequest(req){return req;}
 async function selectionList(g){
  const result=await get('/api/v1/asset-center/cart');if(!active(g))return;cart=result.items;
  const key='vsc-center-batch:'+session().actor,read=()=>{try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}},keep=batch=>{try{batch?sessionStorage.setItem(key,JSON.stringify(batch)):sessionStorage.removeItem(key);}catch{}};
  const retained=read(),form=el('form'),targets=el('fieldset'),picks=[];targets.append(el('legend',msg('ui.target_projects_for_import_multiple_allowed')));
  for(const p of ctx.projects().filter(p=>!p.read_only&&!p.unavailable)){
   const label=el('label',p.name),check=el('input');check.type='checkbox';
   bindAttribute(check,'aria-label',msg('ui.import_into_value0',{value0:p.name}));
   check.checked=retained?retained.items.some(i=>i.project===p.id):ctx.projectId?.()===p.id;
   check.disabled=!!retained;label.prepend(check);targets.append(label);picks.push({project:p.id,check});
  }
  form.append(targets);
  const kind=field(form,msg('ui.asset_type_to_create_after_import'),'select');
  for(const [code,title]of kinds.filter(([code])=>roles[code]))kind.append(localizedOption(code,title));
  if(retained){kind.value=retained.kind;kind.disabled=true;}
  root.append(form);
  const status=el('p');status.setAttribute('role','status');const receipts=el('div');
  for(const row of cart){
   const card=el('article'),label=el('label',row.title),check=el('input');check.type='checkbox';
   check.checked=retained?retained.items.some(i=>i.cart===row.id):selection.has(row.id);
   check.disabled=!!retained;bindAttribute(check,'aria-label',msg('ui.select_value0',{value0:row.title}));
   check.onchange=()=>check.checked?selection.add(row.id):selection.delete(row.id);
   label.prepend(check);
   card.append(label,button(msg('ui.remove_from_list'),async()=>{
    if(read())throw new Error('先继续原导入批次，逐项读回结果。');
    await post('/api/v1/asset-center/cart',{library_version_id:row.library_version_id,member_key:row.member_key,active:false});
    selection.delete(row.id);await load();
   }));
   root.append(card);
  }
  const show=batch=>{
   receipts.replaceChildren();
   for(const item of batch.items){
    const project=ctx.projects().find(p=>p.id===item.project),row=cart.find(r=>r.id===item.cart),line=el('p',joinMessages([project?.name||msg('common.project'),' · ',row?.title||msg('ui.fixed_media'),'：',item.result?msg('ui.asset_card_added'):item.error||msg('ui.waiting')]));
    if(item.result){const a=el('a',msg('ui.view_project_assets'));a.href='/?'+new URLSearchParams({page:'assets',project:item.project});line.append(a);}
    receipts.append(line);
   }
  };
  if(retained)show(retained);
  const actionsBar=el('div','','center-cart-actions');
  actionsBar.append(
   button(retained?msg('ui.continue_original_multi_project_import'):msg('ui.import_selected_media'),async()=>{
    let batch=read();
    if(!batch){
     const projects=picks.filter(p=>p.check.checked);
     if(!projects.length||!selection.size)throw new Error('先选择目标项目与素材。');
     batch={kind:kind.value,items:projects.flatMap(p=>cart.filter(r=>selection.has(r.id)).map(r=>({project:p.project,cart:r.id})))};
     keep(batch);
    }
    for(const item of batch.items){
     if(!active(g))break;if(item.result)continue;
     try{
      if(!item.request){const tree=await get(`/api/v1/projects/${item.project}/tree`);if(!active(g))return;item.request={payload:{cart_id:item.cart,asset_kind:batch.kind,role:roles[batch.kind]},expected_revision:tree.revision,idempotency_key:crypto.randomUUID()};keep(batch);}
      item.result=await ctx.api(`/api/v1/projects/${item.project}/asset-center/import`,{method:'POST',headers:headers(),body:JSON.stringify(item.request)});
      item.error=null;ctx.setRevision?.(item.result.revision,item.project);
     }catch(e){item.error=e.message;if(e.status===422||e.status===409&&e.code==='revision_conflict')item.request=null;}
     keep(batch);if(!active(g))return;show(batch);
    }
    if(active(g)){
     const success=batch.items.filter(i=>i.result).length;
     setText(status,msg('ui.added_value0_items_value1_need_recovery',{value0:success,value1:batch.items.length-success}));
     if(success===batch.items.length){keep(null);selection.clear();}
    }
   }),
   button('打包下载 ZIP',()=>downloadCartZip(g)),
   button('清空清单',async()=>{if(read())throw new Error('请先完成进行中的批量导入');await post('/api/v1/asset-center/cart/clear');selection.clear();await load();})
  );
  root.append(actionsBar,status,receipts);
  if(!cart.length)root.append(el('p',msg('ui.the_selection_list_is_empty_add_fixed_media_from')));
 }
 async function downloads(g){
  const value=await get('/api/v1/asset-center/downloads?offset='+offset+'&limit=24');if(!active(g))return;
  root.append(el('p',msg('ui.download_history_records_requests_not_proof_that_the_browser')));
  for(const row of value.items)root.append(el('p',joinMessages([new Date(row.created_at).toLocaleString(),' · ',row.member_key,' · ',row.library_version_id.slice(0,8)])));
  paging(value.total,offset+value.items.length<value.total?offset+24:null,g);
 }
 async function load(){
  disposed=false;const g=++generation;
  if(identity!==session().actor)selection.clear();
  identity=session().actor;shell();
  try{
   if(!session().actor){root.append(el('p',msg('ui.establish_an_operation_session_first')));return;}
   if(!official&&ctx.workspaces)workspaces=await ctx.workspaces();
   if(!active(g))return;
   if(tab==='cart')await selectionList(g);else if(tab==='downloads')await downloads(g);else await catalog(g);
  }catch(e){if(active(g)){
   if(official&&workbench){const count=root.querySelector('.center-count');if(count)setText(count,'加载失败');for(const grid of [...root.querySelectorAll('.center-grid'),...root.querySelectorAll('.ref-grid')])grid.setAttribute('aria-busy','false');}
   const error=el('p',e.message,'center-load-error');error.setAttribute('role','status');root.append(error,button(msg('ui.reload'),load));
  }}
 }
 return {load,suspend(){disposed=true;generation++;document.removeEventListener?.('pointerdown',closeCardMenus,true);document.removeEventListener?.('keydown',closeCardMenus,true);clearTimeout(searchTimer);clearTimeout(costumeTimer);stopCostumeObserver();closeCostumeDialogs();unmountRefs();root.querySelectorAll('dialog').forEach(d=>d.close());}};
}

// Project UI groups legacy objects with props without changing exact API filters.
export const projectAssetCategoryParams=kind=>({include_blocking:'true',...(kind==='prop'?{include_object:'true'}:{})});

export async function openAssetLibraryModal(ctx,{
 host=typeof document!=='undefined'?document.body:null,
 projectId='',
 multiple=false,
 maxSelect=50,
 excludeAudio=true,
 enableStoryboard=true,
 onConfirm=null,
}={}){
 const dialog=el('dialog','','asset-library-modal');
 bindAttribute(dialog,'aria-label','选择引用资产');
 let currentTab='project',selectedItems=[],clickTimer=null,closed=false,selectedProject=projectId||ctx.projectId?.()||(ctx.projects?.()?.[0]?.id||''),folderId='',kindFilter='',keyword='';
 const limitCount=Math.max(1,Math.min(50,Number(maxSelect)||50));
 const head=el('header','','asset-library-modal-head');
 const tabsNav=el('nav','','asset-library-modal-tabs');
 const tabDefs=[['project','项目资产'],['official','官方资产'],...(enableStoryboard?[['storyboard','分镜图']]:[])];
 for(const [val,label]of tabDefs){
  const b=el('button',label);b.type='button';
  b.onclick=()=>{currentTab=val;folderId='';renderBody();};
  tabsNav.append(b);
 }
 const closeBtn=el('button','×','asset-library-modal-close');closeBtn.type='button';closeBtn.onclick=()=>finish(null);
 head.append(tabsNav,closeBtn);
 const filterRow=el('div','','asset-library-modal-filters');
 const body=el('div','','asset-library-modal-body');
 const foot=el('footer','','asset-library-modal-foot');
 dialog.append(head,filterRow,body,foot);
 (host||document.body).append(dialog);
 dialog.showModal?.();

 let resolvePromise;
 const donePromise=new Promise(resolve=>{resolvePromise=resolve;});
 function finish(result){
  if(closed)return;closed=true;clearTimeout(clickTimer);
  dialog.close?.();dialog.remove?.();
  if(result&&onConfirm)onConfirm(result);
  resolvePromise(result);
 }
 dialog.addEventListener('close',()=>{if(!closed)finish(null);},{once:true});

 function togglePick(item,immediate=false){
  if(!multiple){
   selectedItems=[item];
   renderFooter();
   renderSelectionMarks();
   if(immediate)finish(item);
   return;
  }
  const idx=selectedItems.findIndex(x=>x.key===item.key);
  if(idx>=0)selectedItems.splice(idx,1);
  else if(selectedItems.length<limitCount)selectedItems.push(item);
  else ctx.notice?.(`单次最多选择 ${limitCount} 项`);
  renderFooter();
  renderSelectionMarks();
 }

 const cardMap=new Map();
 function renderSelectionMarks(){
  for(const [key,node]of cardMap.entries()){
   const chosen=selectedItems.some(x=>x.key===key);
   node.setAttribute('data-selected',chosen?'true':'false');
  }
 }
 function renderFooter(){
  foot.replaceChildren();
  foot.append(el('span',multiple?`已选 ${selectedItems.length} / ${limitCount} 项`:(selectedItems[0]?`已选：${selectedItems[0].title}（双击卡片可直接确认）`:'单击预览选中，双击卡片直接确认')));
  const actions=el('div','','asset-library-modal-actions');
  const cancel=el('button','取消');cancel.type='button';cancel.onclick=()=>finish(null);
  const ok=el('button','确定','center-primary-cta');ok.type='button';ok.disabled=!selectedItems.length;
  ok.onclick=()=>finish(multiple?[...selectedItems]:selectedItems[0]);
  actions.append(cancel,ok);foot.append(actions);
 }

 async function renderBody(){
  for(const [idx,[val]]of tabDefs.entries())tabsNav.children[idx]?.setAttribute('aria-pressed',String(currentTab===val));
  filterRow.replaceChildren();body.replaceChildren(el('p','加载中…','asset-library-loading'));cardMap.clear();renderFooter();
  const projects=(ctx.projects?.()||[]).filter(p=>!p.unavailable);
  if(currentTab==='project'||currentTab==='storyboard'){
   const pSelect=el('select');bindAttribute(pSelect,'aria-label','选择项目');
   for(const p of projects)pSelect.append(localizedOption(p.id,p.name));
   if(selectedProject)pSelect.value=selectedProject;
   pSelect.onchange=()=>{selectedProject=pSelect.value;folderId='';renderBody();};
   filterRow.append(pSelect);
  }
  if(currentTab==='project'){
   for(const [val,label]of [['','全部'],['character','人设'],['location','场景'],['prop','道具'],['blocking','站位'],...(excludeAudio?[]:[['voice','音频']])]){
    const b=el('button',label);b.type='button';b.setAttribute('aria-pressed',String(kindFilter===val));
    b.onclick=()=>{kindFilter=val;renderBody();};filterRow.append(b);
   }
  }else if(currentTab==='official'){
   for(const [val,label]of [['','全部'],['character','人设'],['location','场景'],['prop','道具']]){
    const b=el('button',label);b.type='button';b.setAttribute('aria-pressed',String(kindFilter===val));
    b.onclick=()=>{kindFilter=val;renderBody();};filterRow.append(b);
   }
  }
  const search=el('input');search.type='search';search.value=keyword;bindAttribute(search,'placeholder','搜索名称…');
  search.oninput=()=>{keyword=search.value;clearTimeout(clickTimer);clickTimer=setTimeout(()=>renderBody(),300);};
  filterRow.append(search);

  try{
   const items=[];
   if(currentTab==='project'&&selectedProject){
    const base='/api/v1/projects/'+encodeURIComponent(selectedProject);
    const data=await ctx.api(base+'/asset-cards?'+new URLSearchParams({query:keyword,asset_kind:kindFilter,...projectAssetCategoryParams(kindFilter),folder_id:folderId,offset:'0',limit:'48'}));
    if(folderId&&data.current_folder){
     const crumb=el('button',`← 返回根目录（当前：${data.current_folder.title}）`,'asset-library-crumb');crumb.type='button';
     crumb.onclick=()=>{folderId='';renderBody();};body.replaceChildren(crumb);
    }else body.replaceChildren();
    const grid=el('div','','asset-library-grid');
    if(!folderId){
     for(const f of data.folders||[]){
      const fc=el('button',`📁 ${f.title} (${f.asset_count||0})`,'asset-library-folder');fc.type='button';
      fc.onclick=()=>{folderId=f.id;renderBody();};grid.append(fc);
     }
    }
    for(const row of data.items||[]){
     if(excludeAudio&&row.asset_kind==='voice')continue;
     const mediaId=row.forms?.find(f=>f.media_id)?.media_id||row.preview?.media_id;
     if(!mediaId)continue;
     items.push({key:`project:${row.id}:${mediaId}`,source:'project',project_id:selectedProject,asset_id:row.id,media_id:mediaId,title:row.name,asset_kind:row.asset_kind,preview_url:`${base}/media/${encodeURIComponent(mediaId)}/content`});
    }
    appendPickerCards(grid,items);body.append(grid);
   }else if(currentTab==='official'){
    const q={source:'official',order_by:'latest',media_only:'true',offset:'0',limit:'48'};
    if(kindFilter)q.asset_kind=kindFilter;if(keyword)q.query=keyword;
    const data=await ctx.api('/api/v1/asset-center?'+new URLSearchParams(q));
    body.replaceChildren();const grid=el('div','','asset-library-grid');
    for(const row of data.items||[]){
     const m=(row.members||[]).find(x=>x.modality==='image')||row.members?.[0];
     if(!m||(excludeAudio&&m.modality==='audio'))continue;
     items.push({key:`official:${row.version_id}:${m.member_key}`,source:'official',library_version_id:row.version_id,member_key:m.member_key,title:row.title,asset_kind:row.official?.asset_kind||row.catalog?.asset_kind||'character',preview_url:m.preview_url});
    }
    appendPickerCards(grid,items);body.append(grid);
   }else if(currentTab==='storyboard'&&selectedProject){
    const base='/api/v1/projects/'+encodeURIComponent(selectedProject);
    const res=await ctx.api(base+'/resources?modality=image&limit=48');
    body.replaceChildren();const grid=el('div','','asset-library-grid');
    for(const m of res.items||[]){
     if(keyword&&!String(m.name||'').includes(keyword))continue;
     items.push({key:`storyboard:${m.id}`,source:'storyboard',project_id:selectedProject,media_id:m.id,title:m.name||'分镜画面',asset_kind:'storyboard',preview_url:`${base}/media/${encodeURIComponent(m.id)}/content`});
    }
    appendPickerCards(grid,items);body.append(grid);
   }else{
    body.replaceChildren(el('p','暂无可选项目资产'));
   }
  }catch(e){body.replaceChildren(el('p',e.message));}
 }

 function appendPickerCards(grid,items){
  if(!items.length){grid.append(el('p','暂无匹配资产','asset-library-empty'));return;}
  for(const item of items){
   const card=el('div','','asset-library-card');
   card.setAttribute('data-selected',selectedItems.some(x=>x.key===item.key)?'true':'false');
   const img=el('img');img.src=item.preview_url;bindAttribute(img,'alt',item.title);
   card.append(img,el('span',item.title,'asset-library-card-title'));
   card.onclick=()=>{
    if(multiple){togglePick(item,false);return;}
    clearTimeout(clickTimer);
    clickTimer=setTimeout(()=>togglePick(item,false),180);
   };
   card.ondblclick=()=>{
    clearTimeout(clickTimer);
    togglePick(item,true);
   };
   cardMap.set(item.key,card);
   grid.append(card);
  }
 }

 await renderBody();
 return donePromise;
}

// The workbench library is a view over the authorized project card APIs.  It
// never treats a shared-library entry as a project or an official asset.
function createGlobalAssetLibrary(root,ctx){
 const routeTab=()=>{
  const params=new URLSearchParams(location.search);
  const value=params.get('tab')||params.get('source')||(typeof location!=='undefined'&&String(location.pathname||'').replace(/\/+$/,'')==='/asset-center'?'shared':'');
  return value==='shared'||value==='official'?value:'project';
 };
 let disposed=false,generation=0,actor=null,tab=routeTab(),project='',kind='',query='',child=null,controller=null,projectView=null,loadingTimer=null;
 const current=g=>!disposed&&g===generation&&actor===ctx.session().actor;
 const stopLoadingHint=()=>{clearTimeout(loadingTimer);loadingTimer=null;};
 const element=(tag,text,cls)=>{const n=el(tag,text);if(cls)n.className=cls;return n;};
 const btn=(parent,label,fn)=>{const n=element('button',label);n.type='button';n.onclick=async()=>{if(n.disabled)return;n.disabled=true;try{await fn();}catch(e){ctx.notice(e.message);}finally{n.disabled=false;}};parent.append(n);return n;};
 const projects=()=>ctx.projects().filter(p=>!p.unavailable&&!['vsc.text-tools','vsc.creative-tools'].includes(p.profile_id||p.profile));
 const base=p=>'/api/v1/projects/'+encodeURIComponent(p);
 function closeChildren(){child?.suspend();child=null;root.querySelectorAll('dialog').forEach(d=>d.close());}
 async function openProject(p,action=null,assetId=null){
  const g=generation,dialog=element('dialog',null,'global-asset-dialog'),header=element('header');header.append(element('h2',p.name+' · 项目资产'));btn(header,'关闭',()=>dialog.close());const host=element('section');dialog.append(header,host);root.append(dialog);dialog.showModal();let panel=null;
  dialog.addEventListener('close',()=>{panel?.suspend();dialog.remove();if(current(g))load();},{once:true});
  try{
   const tree=await ctx.api(base(p.id)+'/tree');if(!current(g)||!dialog.isConnected)return;let revision=tree.revision;const {mountAssetCards}=await import('./asset-cards.js');if(!current(g)||!dialog.isConnected)return;
   panel=await mountAssetCards(host,{...ctx,session:()=>({...ctx.session(),revision}),setRevision:(value,id)=>{if(!id||id===p.id)revision=value;ctx.setRevision?.(value,id);},navigate:ctx.navigate||((page,scope,id)=>{location.href='/?'+new URLSearchParams({page,project:id,...(scope?{scope}:{})});})},{projectId:p.id,isCurrent:()=>current(g)&&dialog.isConnected,initialAction:action,assetId});
   if(!current(g)||!dialog.isConnected)panel.suspend();
   else if(action&&action!=='editor'){const initial=host.querySelector('.asset-card-dialog');initial?.addEventListener('close',()=>{if(dialog.isConnected)dialog.close();},{once:true});}
  }catch(e){if(current(g)&&dialog.isConnected)host.append(element('p',e.message));}
 }
 function pickProject(action){
  const available=projects().filter(p=>!p.read_only);
  if(project){const p=available.find(p=>p.id===project);if(p)return openProject(p,action);}
  const dialog=element('dialog',null,'global-asset-picker');dialog.append(element('h2','选择项目'));btn(dialog,'关闭',()=>dialog.close());
  for(const p of available)btn(dialog,p.name,()=>{dialog.close();return openProject(p,action);});
  if(!available.length)dialog.append(element('p','暂无可编辑的项目'));
  root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
 }
 function card(row,p,grid){
  const blocking=row.record_kind==='blocking',box=element('article',null,'global-asset-card'),cover=element('div',null,'global-asset-cover');
  const open=btn(cover,'',()=>{
   if(!blocking)return openProject(p,'editor',row.id);
   const d=element('dialog',null,'global-asset-dialog global-blocking-preview');
   d.append(element('h2',row.name));
   if(row.preview?.media_id){
    const viewport=element('div',null,'center-zoom-viewport');
    const img=element('img');img.src=base(p.id)+'/media/'+encodeURIComponent(row.preview.media_id)+'/content';img.alt=row.name;
    viewport.append(img);
    const zbar=element('div',null,'center-zoom-bar');
    const level=element('span','100%','center-zoom-level');
    const ctrl=attachImageZoomPan(viewport,img,{onScaleChange:({percent})=>setText(level,`${percent}%`)});
    btn(zbar,'缩小',()=>ctrl.zoomOut());
    zbar.append(level);
    btn(zbar,'适应窗口',()=>ctrl.reset());
    btn(zbar,'放大',()=>ctrl.zoomIn());
    btn(zbar,'关闭',()=>d.close());
    d.append(viewport,zbar);
   }else{
    d.append(element('p','素材当前不可预览'));
    btn(d,'关闭',()=>d.close());
   }
   root.append(d);d.addEventListener('close',()=>d.remove(),{once:true});d.showModal();
  });
  open.className='global-asset-preview';open.setAttribute('aria-label','预览 '+row.name);
  const form=row.forms?.find(f=>f.media_id),mediaId=form?.media_id||row.preview?.media_id;
  if(mediaId&&row.asset_kind!=='voice'){
   const img=element('img');img.src=base(p.id)+'/media/'+encodeURIComponent(mediaId)+'/content';img.alt=row.name;
   if(!form&&!blocking)img.title='已选参考图，仅用于预览';img.loading='lazy';
   img.onerror=()=>{img.remove();open.append(element('span','预览不可用'));};
   open.append(img);
  }else open.append(element('span',row.asset_kind==='voice'?'音频':'暂无图片'));
  const labels={character:'人设',location:'场景',prop:'道具',object:'道具',blocking:'站位',voice:'音频',costume:'服装',creature:'生物',vehicle:'交通工具',plant:'植物',style:'风格'},badge=element('span',labels[row.asset_kind]||row.asset_kind,'global-asset-badge');
  cover.append(badge);
  if(!blocking){
   const actions=element('div',null,'global-asset-actions');
   if(!p.read_only)btn(actions,'编辑',()=>openProject(p,'editor',row.id));
   btn(actions,'复制到项目',()=>openProject(p,'copy',row.id));
   if(!p.read_only)btn(actions,'删除',()=>openProject(p,'recycle',row.id));
   cover.append(actions);
  }
  box.append(cover,element('h3',row.name),element('p',p.name));grid.append(box);
 }
 async function load(){
  const nextActor=ctx.session().actor,nextTab=routeTab();
  const reuseProject=projectView&&!disposed&&actor===nextActor&&tab==='project'&&nextTab==='project'&&root.querySelector('.global-asset-toolbar')===projectView.toolbar;
  if(actor!==null&&actor!==nextActor){project='';kind='';query='';}
  controller?.abort();stopLoadingHint();controller=new AbortController();const signal=controller.signal;disposed=false;const g=++generation;actor=nextActor;tab=nextTab;closeChildren();
  if(!reuseProject){root.replaceChildren();projectView=null;}root.className='global-asset-library';
  if(!document.querySelector('link[data-asset-cards]')){const css=document.createElement('link');css.rel='stylesheet';css.href='/static/asset-cards.css';css.dataset.assetCards='';document.head.append(css);}
  if(!reuseProject){
  const chooseTab=value=>{const route=new URLSearchParams(location.search);route.set('page','asset-center');route.delete('source');if(value==='project')route.delete('tab');else route.set('tab',value);history.pushState(null,'','?'+route);return load();};
  const tabs=element('nav',null,'global-asset-tabs');
  for(const [value,title]of [['project','项目资产'],['official','官方资产']]){
   const b=btn(tabs,title,()=>chooseTab(value));b.setAttribute('aria-pressed',String(tab===value));
   if(value==='official')b.append(element('small','NEW'));
  }
  const shared=element('a','公共素材库');shared.href='?page=asset-center&tab=shared';
  shared.onclick=e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();chooseTab('shared');};
  if(tab==='shared')shared.setAttribute('aria-current','page');
  tabs.append(shared);root.append(tabs);
  if(!actor){root.append(element('p','请先建立操作会话'));return;}
  if(tab==='official'||tab==='shared'){
   const host=element('section');root.append(host);
   child=createAssetCenter(host,ctx,tab==='official'?{source:'official',embedded:true,workbench:true}:{source:'shared'});
   await child.load();return;
  }
  }
  if(!projectView){
  const toolbar=element('div',null,'global-asset-toolbar'),select=element('select');select.setAttribute('aria-label','选择项目');
  select.onchange=()=>{project=select.value;query=projectView.search.value;return load();};toolbar.append(select);
  const categories=element('nav',null,'global-asset-categories');
  for(const [value,title]of [['','全部'],['character','人设'],['location','场景'],['prop','道具'],['blocking','站位'],['voice','音频']]){
   const b=element('button',title);b.type='button';b.dataset.kind=value;
   b.onclick=()=>{if(kind===value)return;kind=value;query=projectView.search.value;return load();};categories.append(b);
  }
  toolbar.append(categories);
  const tools=element('div',null,'global-asset-tools'),count=element('span','资产数待读取','global-asset-count');count.setAttribute('role','status');tools.append(count);
  const search=element('input');search.type='search';search.value=query;search.placeholder='搜索资产…';search.setAttribute('aria-label','搜索资产');
  search.onkeydown=e=>{if(e.key==='Enter'){query=search.value;load();}};search.onsearch=()=>{query=search.value;load();};
  const batch=element('div',null,'global-asset-batch');tools.append(search,batch);btn(batch,'批量操作',()=>pickProject(null));btn(batch,'批量导入',()=>pickProject('import'));toolbar.append(tools);root.append(toolbar);
  const status=element('p','','global-asset-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.setAttribute('aria-atomic','true');root.append(status);
  const grid=element('div',null,'global-asset-grid');root.append(grid);
  const create=btn(grid,'',()=>pickProject('create'));create.className='global-asset-create';create.append(element('span','＋'),element('strong','新建资产'),element('small','选择类型'));
  const controls=element('div',null,'global-asset-progress'),failureBox=element('div',null,'global-asset-failures');failureBox.setAttribute('role','alert');root.append(controls,failureBox);
  projectView={toolbar,select,categories,count,search,status,grid,create,controls,failureBox,projectsKey:null};
  }
  const {select,categories,count,status,grid,create,controls,failureBox}=projectView;
  const available=projects(),projectsKey=JSON.stringify(available.map(p=>[p.id,p.name]));
  if(projectView.projectsKey!==projectsKey){select.replaceChildren(localizedOption('','所有项目'));for(const p of available)select.append(localizedOption(p.id,p.name));projectView.projectsKey=projectsKey;}
  if(project&&!available.some(p=>p.id===project))project='';select.value=project;
  for(const b of categories.children)b.setAttribute('aria-pressed',String(kind===b.dataset.kind));
  const oldHeight=grid.getBoundingClientRect?.().height||0;
  if(grid.style)grid.style.minHeight=Math.max(240,Math.min(oldHeight,typeof window!=='undefined'?window.innerHeight||600:600))+'px';
  grid.replaceChildren(create);grid.setAttribute('aria-busy','true');setText(count,'资产数待读取');setText(status,'');controls.replaceChildren();failureBox.replaceChildren();failureBox.hidden=true;
  const selected=available.filter(p=>!project||p.id===project),states=selected.map(p=>({p,offset:0,revision:null,status:'ready',error:null})),queue=[...states],size=24,limit=72,concurrency=3,readQuery=query,readKind=kind;
  const kindName={character:'人设',location:'场景',prop:'道具',blocking:'站位',voice:'音频'}[readKind]||'全部';
  let inFlight=0,shown=0,loaded=0,loadingHint=false,received=false;
  const delayHint=()=>{stopLoadingHint();loadingHint=false;loadingTimer=setTimeout(()=>{if(current(g)){loadingTimer=null;loadingHint=true;paint();}},150);};
  delayHint();
  const text=(node,value)=>{if(node.textContent!==value)setText(node,value);};
  function paint(){
   if(!current(g))return;
   const failures=states.filter(s=>s.status==='failed'),waiting=queue.length>0,loading=inFlight>0;
   const complete=!loading&&!waiting&&!failures.length;
   const countText=loaded||complete||failures.length?(complete?'共':'已加载')+loaded+'个资产':'资产数待读取';
   text(count,countText);count.title=countText;count.setAttribute('aria-label',countText);
   text(status,failures.length?(loaded?'部分项目未能完整读取，已加载的资产仍可使用。':'当前分类读取失败，请查看下方原因并重试。'):loading?(loaded?`正在读取${kindName}资产，已加载 ${loaded} 个。`:loadingHint?`正在读取${kindName}资产…`:''):waiting?'尚有未加载资产，可继续浏览。':'');
   grid.setAttribute('aria-busy',String(loading));
   if(loaded||failures.length||!loading)stopLoadingHint();else if(!loadingTimer&&!loadingHint)delayHint();
   if((received||!loading)&&grid.style)grid.style.minHeight='';
   controls.replaceChildren();failureBox.replaceChildren();failureBox.hidden=!failures.length;
   if(waiting&&shown>0&&shown+(inFlight+1)*size>limit){btn(controls,'继续浏览',()=>{grid.replaceChildren(create);shown=0;pump();});controls.append(element('span','本页已展示 '+shown+' 个，继续浏览其余资产。'));}
   if(!waiting&&!loading&&loaded>shown)btn(controls,'从头查看',load);
   if(failures.length){
    failureBox.append(element('p','部分项目未能完整读取：'+failures.map(s=>s.p.name+'（'+s.error.message+'）').join('；')));
    const retryable=failures.filter(s=>!s.changed);
    if(retryable.length)btn(failureBox,'重试失败项目',()=>{loadingHint=false;for(const s of retryable){s.status='ready';s.error=null;queue.push(s);}pump();});
    if(failures.some(s=>s.changed))btn(failureBox,'从头重新读取',load);
   }
   if(!waiting&&!loading&&!failures.length&&!loaded&&!grid.querySelector('.global-asset-empty'))grid.append(element('p',!selected.length?'暂无可访问的项目':readQuery?'没有匹配的资产，可修改搜索条件。':'此分类还没有资产，可新建资产。','global-asset-empty'));
  }
  function pump(){
   if(!current(g))return;
   while(inFlight<concurrency&&queue.length&&shown+(inFlight+1)*size<=limit){
    const state=queue.shift(),offset=state.offset;state.status='loading';inFlight++;
    Promise.resolve().then(()=>ctx.api(base(state.p.id)+'/asset-cards?'+new URLSearchParams({query:readQuery,asset_kind:readKind,...projectAssetCategoryParams(readKind),offset:String(offset),limit:String(size),favorites:'false'}),{signal})).then(data=>{
     if(!current(g))return;
     if(!Array.isArray(data.items)||data.items.length>size)throw new Error('分页返回无效');
     if(state.revision!==null&&state.revision!==data.revision){state.changed=true;throw new Error('读取期间项目已变化，请从头重新读取');}
     if(data.next_offset!=null&&(!Number.isInteger(data.next_offset)||data.next_offset<=offset))throw new Error('分页游标无效');
     received=true;state.revision=data.revision;for(const row of data.items)card(row,state.p,grid);shown+=data.items.length;loaded+=data.items.length;
     if(data.next_offset==null)state.status='done';else{state.offset=data.next_offset;state.status='ready';queue.push(state);}
    }).catch(error=>{if(current(g)){received=true;state.status='failed';state.error=error;}}).finally(()=>{if(current(g)){inFlight--;pump();}});
   }
   paint();
  }
  pump();
 }
 return {load,suspend(){disposed=true;generation++;controller?.abort();stopLoadingHint();closeChildren();}};
}
