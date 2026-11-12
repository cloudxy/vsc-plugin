import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
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
 ['blocking','站位'],
 ['voice','音频'],
 ['costume','服饰'],
];
const officialSelectKinds=[
 ['character','人设'],
 ['location',msg('asset.scene')],
 ['prop',msg('asset.prop')],
 ['blocking','站位'],
 ['voice','音频'],
 ['costume','服饰'],
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
 const facetCache=new Map(),officialPageCache=new Map(),costumePageCache=new Map();
 const DEFAULT_COSTUME_CATEGORIES=['春','夏','秋','冬','内衣','派对','泳装','性感'];
 let costumeSummaryCache=null;
 let disposed=false,generation=0,identity=null,offset=0,filters={},tab='gallery',cart=[],cartOpen=false,selection=new Set(),workspaces=[],officialDrawerRow=null,searchTimer=null;
 let costumeCat='',costumeQuery='',costumeTimer=0,costumeFocus=false,costumeObserver=null,costumeScrollCleanup=null;
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
  const drawer=el('aside','','official-detail-drawer');
  bindAttribute(drawer,'aria-label',row.title+' 详情预览');
  const head=el('div','','official-drawer-head');
  head.append(el('h3',row.title),button('×',()=>{officialDrawerRow=null;drawer.remove();},'official-drawer-close'));
  drawer.append(head);
  const members=visibleMembers(row),primary=members.find(m=>m.modality==='image')||members[0];
  const stage=el('div','','official-drawer-stage');
  if(primary){
   const previewNode=picture(primary);
   if(primary.modality==='image')previewNode.addEventListener('click',()=>zoom(row,primary));
   stage.append(previewNode);
   if(primary.modality==='image')stage.append(button('查看大图',()=>zoom(row,primary),'official-drawer-zoom'));
  }
  drawer.append(stage);
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
  if(primary){
   const ctas=el('div','','official-drawer-ctas');
   const refBtn=button('引用生成',()=>reference(row,primary),'center-primary-cta');
   const addBtn=button(msg('gallery.add_project'),()=>addToProjects(row,primary));
   ctas.append(refBtn,addBtn);
   drawer.append(ctas);
  }
  root.append(drawer);
 }
 function detail(row,g){
  if(official&&!canvas){openOfficialDrawer(row,g);return;}
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
 async function costumeBrowser(g){
  const COSTUME_LIMIT='24';
  stopCostumeObserver();
  closeCostumeDialogs();
  root.className=String(root.className||'').replace(/\bcostume-library\b/g,'').trim()+' costume-library';
  const scrollRoot=findScrollContainer(root);
  const leave=value=>{
   clearTimeout(costumeTimer);stopCostumeObserver();closeCostumeDialogs();
   if(value)filters.asset_kind=value;else delete filters.asset_kind;
   offset=0;
   if(value!=='costume'){costumeCat='';costumeQuery='';costumeFocus=false;}
   return load();
  };
  const kindBar=el('div','','center-official-filters costume-kind-bar'),tabs=el('div','','center-official-kinds');
  for(const [value,title]of officialWorkbenchKinds){
   const t=button(title,()=>leave(value));
   t.setAttribute('aria-pressed',String((filters.asset_kind||'')===value));
   tabs.append(t);
  }
  kindBar.append(tabs);root.append(kindBar);
  const seasons=el('div','','costume-tabs');seasons.setAttribute('role','tablist');bindAttribute(seasons,'aria-label','服饰分类');
  const pick=name=>{costumeCat=name;clearTimeout(costumeTimer);if(scrollRoot)scrollRoot.scrollTop=0;return load();};
  const syncSeasonTabs=summary=>{
   const entries=summary
    ?[['','全部 '+Number(summary.total_all||0).toLocaleString('zh-CN')],...(summary.categories||[]).map(cat=>[cat.name,cat.name+' '+Number(cat.count||0).toLocaleString('zh-CN')])]
    :[['','全部'],...DEFAULT_COSTUME_CATEGORIES.map(name=>[name,name])];
   const existing=[...seasons.children];
   if(existing.length===entries.length){
    for(const [idx,[val,label]]of entries.entries()){
     setText(existing[idx],label);
     existing[idx].setAttribute('aria-pressed',String((costumeCat||'')===val));
    }
    return;
   }
   seasons.replaceChildren();
   for(const [val,label]of entries){
    const t=button(label,()=>pick(val));
    t.setAttribute('role','tab');t.setAttribute('aria-pressed',String((costumeCat||'')===val));seasons.append(t);
   }
  };
  syncSeasonTabs(costumeSummaryCache);
  root.append(seasons);
  const cacheKey=costumeCat+'\0'+costumeQuery,cached=costumePageCache.get(cacheKey);
  const searchRow=el('div','','costume-search'),input=el('input');
  input.type='search';input.value=costumeQuery;
  bindAttribute(input,'placeholder','ID、颜色或单品，例如 denim、白');
  bindAttribute(input,'aria-label','搜索服饰');
  input.oninput=()=>{costumeQuery=input.value;costumeFocus=true;clearTimeout(costumeTimer);costumeTimer=setTimeout(()=>{costumeTimer=0;if(!disposed)load();},150);};
  input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault?.();clearTimeout(costumeTimer);load();}});
  const count=el('span',cached?Number(cached.total||0).toLocaleString('zh-CN')+' 张':'加载中…','costume-count');
  count.setAttribute('role','status');
  const tools=el('div','','costume-tools');
  tools.append(
   button('使用说明',()=>costumeNote('使用说明','点分类，或用编号、颜色、单品搜索，例如 denim、白。点卡片看大图，左右方向键可以换一张。下载得到的是本库生成的原图。')),
   button('使用注意',()=>costumeNote('使用注意','画面里只有服装，供创作时作服装参考。这些图不是在售商品，也不能当作真人的肖像或身材。请逐张取用。'))
  );
  searchRow.append(input,count,tools);root.append(searchRow);
  if(costumeFocus){input.focus?.();costumeFocus=false;}
  const pageItems=[],grid=el('div','','costume-grid');
  let next=null,moreBtn=null,pagingBusy=false,sentinel=null,sentinelVisible=false;
  const words=item=>{const text=String(item.keywords||'');return (text.startsWith(item.title+' ')?text.slice(item.title.length).trim():text).split(/\s+/).filter(Boolean).join(' · ');};
  const costumeSig=list=>(list||[]).map(x=>`${x.id}:${x.image}:${x.keywords||''}`).join('|');
  const cardFor=(item,index=24)=>{
   const card=el('article','','costume-card'),shot=el('div','','costume-shot'),open=button('',()=>costumeModal(item.id),'costume-open');
   bindAttribute(open,'aria-label','查看 '+item.id);
   const img=el('img');img.src=item.image;img.loading=index<8?'eager':'lazy';img.decoding='async';bindAttribute(img,'alt',item.id+' '+words(item));
   open.append(img);shot.append(open);
   const keys=el('p',words(item)||item.category||'','costume-keys');
   card.append(shot,el('h3',item.id),el('p',item.label||item.category||'服饰'),keys);
   return card;
  };
  async function pull(){
   if(pagingBusy||next==null||!active(g)||!grid.isConnected)return;
   pagingBusy=true;const cursor=next;
   try{
    const more=await get('/api/v1/asset-center/costumes?'+new URLSearchParams({category:costumeCat,q:costumeQuery,offset:String(cursor),limit:COSTUME_LIMIT}));
    if(!active(g)||!grid.isConnected)return;
    for(const item of more.items||[]){pageItems.push(item);grid.append(cardFor(item,pageItems.length-1));}
    next=more.next_offset??null;
    setText(count,Number(more.total||pageItems.length).toLocaleString('zh-CN')+' 张');
    if(next==null){moreBtn?.remove();sentinel?.remove();stopCostumeObserver();}
   }finally{
    pagingBusy=false;
    if(next!=null&&sentinelVisible&&sentinel?.isConnected&&costumeObserver&&typeof costumeObserver.unobserve==='function'){
     const recheck=()=>{
      if(!active(g)||next==null||!sentinel?.isConnected||!costumeObserver)return;
      costumeObserver.unobserve(sentinel);
      costumeObserver.observe(sentinel);
     };
     if(typeof requestAnimationFrame==='function')requestAnimationFrame(recheck);
    }
   }
  }
  function costumeModal(itemId){
   let cursor=pageItems.findIndex(item=>item.id===itemId);
   if(cursor<0)return;
   closeCostumeDialogs();
   const dialog=el('dialog','','costume-modal');
   const viewport=el('div','','center-zoom-viewport');
   const img=el('img');
   viewport.append(img);
   const caption=el('p');
   const down=el('a','下载');
   const levelEl=el('span','100%','center-zoom-level');
   const zoomCtrl=attachImageZoomPan(viewport,img,{
    onScaleChange:({percent})=>setText(levelEl,`${percent}%`),
   });
   const show=()=>{
    const item=pageItems[cursor];if(!item)return;
    img.src=item.image;bindAttribute(img,'alt',item.id);
    setText(caption,item.id+' · '+(item.label||'')+' · '+words(item));
    down.href=item.image;down.setAttribute('download',item.id+'.png');
    zoomCtrl.reset();
   };
   const stepItem=async delta=>{
    const target=cursor+delta;
    if(target>=pageItems.length&&delta>0)await pull();
    if(!dialog.isConnected)return;
    if(target<0||target>=pageItems.length)return;
    cursor=target;show();
   };
   show();
   const bar=el('div','','costume-modal-bar');
   bar.append(
    button('缩小',()=>zoomCtrl.zoomOut()),
    levelEl,
    button('适应窗口',()=>zoomCtrl.reset()),
    button('放大',()=>zoomCtrl.zoomIn()),
    button('上一张',()=>stepItem(-1)),
    button('下一张',()=>stepItem(1)),
    down,
    button('关闭',()=>dialog.close())
   );
   dialog.append(viewport,caption,bar);
   dialog.addEventListener('keydown',event=>{
    if(event.key==='ArrowRight'){event.preventDefault?.();stepItem(1);}
    else if(event.key==='ArrowLeft'){event.preventDefault?.();stepItem(-1);}
    else if(event.key==='+'||event.key==='='){event.preventDefault?.();zoomCtrl.zoomIn();}
    else if(event.key==='-'){event.preventDefault?.();zoomCtrl.zoomOut();}
    else if(event.key==='0'){event.preventDefault?.();zoomCtrl.reset();}
   });
   dialog.addEventListener('click',event=>{
    if(zoomCtrl.consumeMoved())return;
    if(event.target===dialog)dialog.close();
   });
   let startX=null;
   dialog.addEventListener('pointerdown',event=>{if(zoomCtrl.getScale()<=1)startX=event.clientX;else startX=null;});
   dialog.addEventListener('pointerup',event=>{
    if(startX==null||zoomCtrl.getScale()>1)return;
    const dx=event.clientX-startX;startX=null;
    if(Math.abs(dx)>48)stepItem(dx<0?1:-1);
   });
   dialog.addEventListener('close',()=>dialog.remove());
   (document.body||root).append(dialog);
   dialog.showModal();
  }
  if(cached){
   for(const [idx,item]of (cached.items||[]).entries()){pageItems.push(item);grid.append(cardFor(item,idx));}
   if(!pageItems.length)grid.append(el('p','没有符合条件的服饰','costume-empty'));
   next=cached.next_offset??null;
  }
  root.append(grid);
  const params=new URLSearchParams({category:costumeCat,q:costumeQuery,offset:'0',limit:COSTUME_LIMIT});
  const data=await get('/api/v1/asset-center/costumes?'+params);
  if(!active(g))return;
  costumeSummaryCache={total_all:data.total_all||0,categories:data.categories||[]};
  costumePageCache.set(cacheKey,data);
  syncSeasonTabs(costumeSummaryCache);
  setText(count,Number(data.total||0).toLocaleString('zh-CN')+' 张');
  if(!cached||costumeSig(data.items)!==costumeSig(pageItems)){
   pageItems.length=0;
   grid.replaceChildren();
   for(const [idx,item]of (data.items||[]).entries()){pageItems.push(item);grid.append(cardFor(item,idx));}
   if(!pageItems.length)grid.append(el('p','没有符合条件的服饰','costume-empty'));
  }
  next=data.next_offset??null;
  moreBtn=button('更多',pull,'costume-more');
  if(next!=null)root.append(moreBtn);
  if(next!=null){
   if(typeof IntersectionObserver==='function'){
    sentinel=el('div','','costume-sentinel');
    costumeObserver=new IntersectionObserver(entries=>{
     for(const entry of entries)sentinelVisible=Boolean(entry.isIntersecting);
     if(sentinelVisible)pull();
    },{root:scrollRoot||null,rootMargin:'0px 0px 480px 0px'});
    costumeObserver.observe(sentinel);root.append(sentinel);
   }
   const scrollTarget=scrollRoot||(typeof window!=='undefined'?window:null);
   if(scrollTarget?.addEventListener){
    const onScroll=()=>{
     if(pagingBusy||next==null||!active(g))return;
     const box=scrollRoot||document?.scrollingElement||document?.documentElement;
     if(box&&box.scrollHeight-box.scrollTop-box.clientHeight<=480)pull();
    };
    scrollTarget.addEventListener('scroll',onScroll,{passive:true});
    costumeScrollCleanup=()=>scrollTarget.removeEventListener?.('scroll',onScroll);
   }
  }
 }

 async function officialCatalog(g){
  if(filters.asset_kind==='costume')return costumeBrowser(g);
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
   for(const [value,title]of officialWorkbenchKinds){
    const n=button(title,()=>{
     clearTimeout(costumeTimer);stopCostumeObserver();closeCostumeDialogs();
     if(value)filters.asset_kind=value;else delete filters.asset_kind;
     if(value&&value!=='character'){delete filters.role_level;delete filters.age_band;delete filters.gender;delete filters.role_tag;}
     offset=0;return load();
    });
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
  search.oninput=()=>{filters.query=search.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;load();},300);};
  if(workbench)filterHost.append(count);
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
  root.append(form);

  const reqFilters={...filters,order_by:filters.order_by||'latest',source:'official',media_only:'true',offset,limit:24};
  for(const k of Object.keys(reqFilters))if(reqFilters[k]===''||reqFilters[k]==null)delete reqFilters[k];
  const queryStr=String(new URLSearchParams(reqFilters));
  const officialSig=list=>(list||[]).map(r=>`${r.id}:${r.version_id}:${r.title}:${r.download_count||0}`).join('|');
  const renderOfficialCard=(row,index=24)=>{
   const card=el('article','','center-card');const members=visibleMembers(row),member=members.find(m=>m.modality==='image')||members[0],cover=el('div','','center-cover');
   if(member){
    if(member.modality==='image'){
     const open=button('',()=>zoom(row,member),'center-preview'),imgNode=picture(member);
     if(workbench){imgNode.loading=index<12?'eager':'lazy';imgNode.decoding='async';}
     bindAttribute(open,'aria-label','放大查看 '+row.title);open.append(imgNode);draggable(open,row,member);cover.append(open);
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
    if(workbench){bindAttribute(ref,'aria-label',refLabel);bindAttribute(ref,'title',refLabel);bindAttribute(add,'aria-label',msg('gallery.add_project'));bindAttribute(add,'title',msg('gallery.add_project'));setText(ref,'✎');setText(add,'＋');actions.append(ref,add);cover.append(actions);}
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
  }
  const data=await get('/api/v1/asset-center?'+queryStr);
  if(!active(g))return;
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
  if(officialDrawerRow&&data.items.some(r=>r.id===officialDrawerRow.id))openOfficialDrawer(officialDrawerRow,g);
  if(data.total>24)paging(data.total,data.next_offset,g);
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
  }catch(e){if(active(g))root.append(el('p',e.message),button(msg('ui.reload'),load));}
 }
 return {load,suspend(){disposed=true;generation++;clearTimeout(searchTimer);clearTimeout(costumeTimer);stopCostumeObserver();closeCostumeDialogs();root.querySelectorAll('dialog').forEach(d=>d.close());}};
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
 let disposed=false,generation=0,actor=null,tab=routeTab(),project='',kind='',query='',child=null,controller=null;
 const current=g=>!disposed&&g===generation&&actor===ctx.session().actor;
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
  controller?.abort();controller=new AbortController();const signal=controller.signal;disposed=false;const g=++generation;actor=ctx.session().actor;tab=routeTab();closeChildren();root.replaceChildren();root.className='global-asset-library';
  if(!document.querySelector('link[data-asset-cards]')){const css=document.createElement('link');css.rel='stylesheet';css.href='/static/asset-cards.css';css.dataset.assetCards='';document.head.append(css);}
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
  const toolbar=element('div',null,'global-asset-toolbar'),select=element('select');select.setAttribute('aria-label','选择项目');
  select.append(localizedOption('','所有项目'));for(const p of projects())select.append(localizedOption(p.id,p.name));
  if(project&&!projects().some(p=>p.id===project))project='';
  select.value=project;select.onchange=()=>{project=select.value;load();};toolbar.append(select);
  const categories=element('nav',null,'global-asset-categories');
  for(const [value,title]of [['','全部'],['character','人设'],['location','场景'],['prop','道具'],['blocking','站位'],['voice','音频']]){
   const b=btn(categories,title,()=>{kind=value;return load();});b.setAttribute('aria-pressed',String(kind===value));
  }
  toolbar.append(categories);
  const count=element('span','加载中…','global-asset-count');count.setAttribute('role','status');toolbar.append(count);
  const search=element('input');search.type='search';search.value=query;search.placeholder='搜索资产…';search.setAttribute('aria-label','搜索资产');
  search.onkeydown=e=>{if(e.key==='Enter'){query=search.value;load();}};search.onsearch=()=>{query=search.value;load();};
  toolbar.append(search);btn(toolbar,'批量操作',()=>pickProject(null));btn(toolbar,'批量导入',()=>pickProject('import'));root.append(toolbar);
  const grid=element('div',null,'global-asset-grid');root.append(grid);
  const create=btn(grid,'',()=>pickProject('create'));create.className='global-asset-create';create.append(element('span','＋'),element('strong','新建资产'),element('small','选择类型'));
  const selected=projects().filter(p=>!project||p.id===project),states=selected.map(p=>({p,offset:0,revision:null,status:'ready',error:null})),queue=[...states],size=24,limit=72,concurrency=3,readQuery=query,readKind=kind;
  const controls=element('div',null,'global-asset-progress'),failureBox=element('div',null,'global-asset-failures');failureBox.setAttribute('role','alert');root.append(controls,failureBox);let inFlight=0,shown=0,loaded=0;
  function paint(){
   if(!current(g))return;
   const failures=states.filter(s=>s.status==='failed'),waiting=queue.length>0,loading=inFlight>0;
   setText(count,(loading||waiting||failures.length?'已加载 ':'共')+loaded+'个资产'+(loading?' · 正在加载':waiting?' · 尚有未加载资产':failures.length?' · 部分读取失败':''));
   controls.replaceChildren();failureBox.replaceChildren();failureBox.hidden=!failures.length;
   if(waiting&&shown>0&&shown+(inFlight+1)*size>limit){btn(controls,'继续浏览',()=>{grid.replaceChildren(create);shown=0;pump();});controls.append(element('span','本页已展示 '+shown+' 个，继续浏览其余资产。'));}
   if(!waiting&&!loading&&loaded>shown)btn(controls,'从头查看',load);
   if(failures.length){
    failureBox.append(element('p','部分项目未能完整读取：'+failures.map(s=>s.p.name+'（'+s.error.message+'）').join('；')));
    const retryable=failures.filter(s=>!s.changed);
    if(retryable.length)btn(failureBox,'重试失败项目',()=>{for(const s of retryable){s.status='ready';s.error=null;queue.push(s);}pump();});
    if(failures.some(s=>s.changed))btn(failureBox,'从头重新读取',load);
   }
   if(!waiting&&!loading&&!failures.length&&!loaded&&!grid.querySelector('.global-asset-empty'))grid.append(element('p',selected.length?'暂无资产':'暂无可访问的项目','global-asset-empty'));
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
     state.revision=data.revision;for(const row of data.items)card(row,state.p,grid);shown+=data.items.length;loaded+=data.items.length;
     if(data.next_offset==null)state.status='done';else{state.offset=data.next_offset;state.status='ready';queue.push(state);}
    }).catch(error=>{if(current(g)){state.status='failed';state.error=error;}}).finally(()=>{if(current(g)){inFlight--;pump();}});
   }
   paint();
  }
  pump();
 }
 return {load,suspend(){disposed=true;generation++;controller?.abort();closeChildren();}};
}
