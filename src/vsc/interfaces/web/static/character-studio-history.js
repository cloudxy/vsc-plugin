// Saved character generations: one browser history, consumed by the official-assets library.
import * as store from './character-studio-store.js';
import {PROVIDER_META,comparisonReferences} from './character-studio-ai.js';

const el=(tag,cls='',text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=String(text);return n;};
function select(options,value,onChange,{label=''}={}){
 const s=el('select');if(label)s.setAttribute('aria-label',label);
 for(const [v,l]of options){const o=el('option','',l);o.value=v;s.append(o);}
 s.value=String(value??'');s.onchange=()=>onChange(s.value);return s;
}
function download(url,name){const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();}

export function createCharacterHistory(root,ctx,{onZoom,onCompose}={}){
 let disposed=false,unsub=null,grid=null,count=null,clear=null,search=null,note=null,query='',lastHistory=null,lastHydrated=null,lastError=null;
 const notice=message=>ctx.notice?.(message),dialogs=new Set();
 const recordTitle=h=>{
  const d=new Date(h.createdAt),pad=v=>String(v).padStart(2,'0');
  return Number.isNaN(d.getTime())?'合成角色':`合成角色 · ${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
 };
 const engine=h=>PROVIDER_META[h.provider]?.shortName||h.provider||'AI生成';
 function closeMenus(keep=null,restoreFocus=false){
  let trigger=null;
  for(const menu of root.querySelectorAll('.cs-history-menu')){
   if(menu===keep||!menu.open)continue;
   menu.open=false;trigger=menu.querySelector('summary');trigger?.setAttribute('aria-expanded','false');
  }
  if(restoreFocus)trigger?.focus?.({preventScroll:true});
  return Boolean(trigger);
 }
 function dismissOutside(event){
  for(const menu of root.querySelectorAll('.cs-history-menu'))if(menu.open&&!menu.contains(event.target)){
   menu.open=false;menu.querySelector('summary')?.setAttribute('aria-expanded','false');
  }
 }
 function dismissEscape(event){if(event.key==='Escape'&&closeMenus(null,true))event.preventDefault();}
 function menuListeners(listen){
  const method=listen?'addEventListener':'removeEventListener';
  for(const type of ['pointerdown','click','focusin'])document[method](type,dismissOutside,true);
  document[method]('keydown',dismissEscape,true);
 }
 function action(text,fn,cls=''){
  const b=el('button',cls,text);b.type='button';
  b.onclick=async()=>{if(b.disabled||disposed)return;b.disabled=true;b.setAttribute('aria-busy','true');
   try{await fn();}catch(error){if(!disposed)notice(error?.message||String(error));}
   finally{b.disabled=b===clear&&(!store.getState().history.length||!store.getState().hydrated);b.removeAttribute('aria-busy');}
  };return b;
 }
 function moreMenu(label,items){
  const menu=el('details','cs-history-menu'),summary=el('summary','','⋯'),panel=el('div','cs-history-menu-panel');summary.setAttribute('aria-label',label);summary.setAttribute('aria-expanded','false');summary.title=label;
  const buttons=items.map(([label,fn,cls])=>{const b=action(label,()=>{menu.open=false;summary.setAttribute('aria-expanded','false');summary.focus({preventScroll:true});return fn();},cls);panel.append(b);return b;});
  summary.onclick=event=>{event.preventDefault();closeMenus(menu);menu.open=!menu.open;summary.setAttribute('aria-expanded',String(menu.open));summary.focus({preventScroll:true});};
  menu.append(summary,panel);menu.onkeydown=dismissEscape;
  menu.addEventListener('toggle',()=>{summary.setAttribute('aria-expanded',String(menu.open));if(menu.open)closeMenus(menu);});
  return {node:menu,buttons};
 }
 function reuse(h){store.setCustomPrompt(h.prompt);notice('已恢复该图提示词');return onCompose?.();}
 function detail(h){
  const returnFocus=document.activeElement,dialog=el('dialog','cs-dialog cs-history-detail');dialog.setAttribute('aria-label','合成记录详情');
  const head=el('header','cs-dialog-head'),close=action('×',()=>dialog.close(),'cs-icon-btn');close.setAttribute('aria-label','关闭合成记录详情');head.append(el('h2','',recordTitle(h)),close);
  const meta=el('dl','cs-history-detail-meta');
  for(const [label,value]of [['生成引擎',engine(h)],['模型',h.model||'未记录'],['生成时间',new Date(h.createdAt).toLocaleString()],['参考快照',h.snapshot?`${store.recipeCount(h.snapshot.recipe||{})} 张参考图`:'旧记录未保存快照']])meta.append(el('dt','',label),el('dd','',value));
  const recipe=el('section','cs-history-detail-section');recipe.append(el('h3','','完整配方'),el('p','',h.recipeSummary||'自定义合成'));
  const prompt=el('section','cs-history-detail-section');prompt.append(el('h3','','提示词'),el('pre','',h.prompt||'该记录未保存提示词。'));
  const tools=el('div','cs-row-actions');tools.append(action('复制提示词',async()=>{if(!navigator.clipboard?.writeText)throw new Error('无法复制，请手动选中提示词复制');await navigator.clipboard.writeText(h.prompt||'');notice('已复制提示词');}),action('复用提示词',()=>{dialog.close();return reuse(h);}));
  dialog.append(head,meta,recipe,prompt,tools);dialogs.add(dialog);
  dialog.addEventListener('close',()=>{dialogs.delete(dialog);dialog.remove();if(returnFocus?.isConnected)returnFocus.focus?.();});
  document.body.append(dialog);dialog.showModal?.();
 }
 function updateNote(){if(note)note.textContent=(navigator.onLine===false?'当前离线，已保存的记录仍可查看。 ':'')+'记录仅保存在当前浏览器，含本次生成的参考快照。';}
 function clearSearch(){query='';search.value='';render(true);search.focus();}
 function status(title,text,control){
  const box=el('section','cs-history-state');box.setAttribute('role','status');box.append(el('h3','',title),el('p','',text));if(control)box.append(control);grid.append(box);
 }
 function render(force=false){
  if(disposed||!grid)return;
  const s=store.getState();
  if(!force&&s.history===lastHistory&&s.hydrated===lastHydrated&&s.generationError===lastError)return;
  lastHistory=s.history;lastHydrated=s.hydrated;lastError=s.generationError;
  const focused=root.contains?.(document.activeElement)?document.activeElement:null;
  const restoreFocus=()=>{if(focused&&!focused.isConnected)search.focus?.({preventScroll:true});};
  const key=query.trim().toLocaleLowerCase();
  const items=[...s.history].sort((a,b)=>b.createdAt-a.createdAt).filter(h=>!key||[h.recipeSummary,h.prompt,h.model,engine(h),h.provider].some(v=>String(v||'').toLocaleLowerCase().includes(key)));
  count.textContent=!s.hydrated?'正在读取…':key?`${items.length} / ${s.history.length} 条记录`:`${s.history.length} 条记录`;
  clear.disabled=!s.history.length||!s.hydrated;grid.setAttribute('aria-busy',String(!s.hydrated&&!s.generationError));grid.replaceChildren();updateNote();
  if(!s.hydrated){
   if(s.generationError)status('暂时无法读取合成记录','请确认当前浏览器允许本地存储，再重试。',action('重试读取',()=>window.location.reload()));
   else{for(let i=0;i<2;i++){const skel=el('div','cs-history-skeleton');skel.setAttribute('aria-hidden','true');grid.append(skel);}status('正在读取合成记录…','');}
   restoreFocus();return;
  }
  if(!items.length){
   if(key)status('没有找到合成记录','试试其他关键词，或清除搜索查看全部记录。',action('清除搜索',clearSearch));
   else status('还没有合成记录','生成完成后，图片和本次参考快照会保存在这里。');
   restoreFocus();return;
  }
  for(const h of items){
   const title=recordTitle(h),card=el('article','cs-history-item official-list-card'),preview=action('',()=>onZoom?.(h.imageUrl,h.recipeSummary||title),'cs-history-img official-list-media');
   preview.setAttribute('aria-label',`查看生成记录：${h.recipeSummary||title}`);
   const img=el('img');img.src=h.imageUrl;img.alt=h.recipeSummary||title;img.loading='lazy';img.decoding='async';
   img.onerror=()=>{img.hidden=true;if(!preview.querySelector('.cs-history-image-error'))preview.append(el('span','cs-history-image-error','图片暂时无法显示 · 仍可查看记录详情'));};preview.append(img);
   const meta=el('div','cs-history-meta official-list-info'),heading=el('h3','official-list-title',title);heading.title=title;meta.append(heading,el('small','official-list-meta',`${engine(h)} · ${new Date(h.createdAt).toLocaleString()}`));
   const tools=el('div','cs-row-actions official-list-actions'),more=moreMenu(title+'的更多操作',[
    ['查看详情',()=>detail(h)],['对比参考',()=>compareDialog(h)],['下载图片',()=>download(h.imageUrl,`character-${h.createdAt}.png`)],
    ['删除记录',()=>{if(confirm('删除这条合成记录及参考快照？此操作无法撤销，已下载的图片不受影响。'))return store.removeHistoryItem(h.id);},'cs-history-delete'],
   ]);
   tools.append(action('复用提示词',()=>reuse(h)),more.node);card.append(preview,meta,tools);grid.append(card);
  }
  restoreFocus();
 }
 function compareDialog(result){
  const refs=comparisonReferences(result);
  const returnFocus=document.activeElement,natural=new Map();
  let ref=refs[0],cmpMode='side',view={zoom:1,x:0,y:0},split=50,surfaces=[],images=[],observers=[],resetGestures=[];
  const dialog=el('dialog','cs-dialog cs-compare');dialog.setAttribute('aria-label','对比参考');
  const head=el('header','cs-dialog-head'),close=action('×',()=>dialog.close(),'cs-icon-btn');close.setAttribute('aria-label','关闭参考对比');head.append(el('h2','','对比参考'),close);
  const description=el('p','cs-compare-hint','参考来自这次生成保存的提交快照。两图共同缩放与移动，按原比例显示。');
  const bar=el('div','cs-compare-bar'),stage=el('div','cs-compare-stage'),slider=el('label','cs-compare-slider'),range=el('input'),ratioLabel=el('span');
  range.type='range';range.min='0';range.max='100';range.value=String(split);range.setAttribute('aria-label','参考图显示比例');
  slider.append(el('span','','参考占比'),range,ratioLabel);
  const control=(label,fn)=>{const b=el('button','',label);b.type='button';b.onclick=()=>{if(!b.disabled)fn();};return b;};
  const level=el('span','cs-compare-level'),zoomOut=control('−',()=>zoomAt(view.zoom/1.25)),zoomIn=control('＋',()=>zoomAt(view.zoom*1.25)),reset=control('复位',()=>update({zoom:1,x:0,y:0}));
  zoomOut.setAttribute('aria-label','共同缩小');zoomIn.setAttribute('aria-label','共同放大');level.setAttribute('aria-live','polite');
  const controls=el('div','cs-compare-controls');controls.setAttribute('aria-label','共同缩放控制');controls.append(zoomOut,level,zoomIn,reset);
  const disconnect=()=>{for(const observer of observers)observer.disconnect();observers=[];for(const clear of resetGestures)clear();resetGestures=[];};
  const clamp=next=>{
   const zoom=Math.max(1,Math.min(8,next.zoom)),bounds=[];
   for(const {node,urls}of surfaces){
    const box=node.getBoundingClientRect?.(),width=box?.width||node.clientWidth,height=box?.height||node.clientHeight;
    for(const url of urls){
     const size=natural.get(url);if(!size||!width||!height)continue;
     const fit=Math.min(width/size.width,height/size.height);
     bounds.push({x:Math.max(0,(size.width*fit*zoom/width-1)/2),y:Math.max(0,(size.height*fit*zoom/height-1)/2)});
    }
   }
   const maxX=bounds.length?Math.min(...bounds.map(b=>b.x)):0,maxY=bounds.length?Math.min(...bounds.map(b=>b.y)):0;
   return {zoom,x:Math.max(-maxX,Math.min(maxX,next.x)),y:Math.max(-maxY,Math.min(maxY,next.y))};
  };
  const update=next=>{
   view=clamp(next);
   for(const img of images)img.style.transform=`translate(${view.x*100}%, ${view.y*100}%) scale(${view.zoom})`;
   for(const {node}of surfaces)node.style.cursor=view.zoom>1?'grab':'default';
   level.textContent=`${Math.round(view.zoom*100)}%`;zoomOut.disabled=view.zoom<=1;zoomIn.disabled=view.zoom>=8;
  };
  const zoomAt=(zoom,x=0,y=0)=>{
   const nextZoom=Math.max(1,Math.min(8,zoom)),ratio=nextZoom/view.zoom;
   update({zoom:nextZoom,x:x-(x-view.x)*ratio,y:y-(y-view.y)*ratio});
  };
  const surface=(label,urls,cls='')=>{
   const node=el('div','cs-compare-viewport '+cls);node.tabIndex=0;node.setAttribute('role','region');node.setAttribute('aria-label',`${label}；共同缩放和移动`);
   const pointers=new Map();let previous=null;
   const point=(x,y)=>{const box=node.getBoundingClientRect?.()||{};return {x:(x-(box.left||0))/(box.width||node.clientWidth||1)-0.5,y:(y-(box.top||0))/(box.height||node.clientHeight||1)-0.5};};
   const gesture=()=>{const p=[...pointers.values()];if(!p.length)return null;return p.length===1?{...p[0],distance:0}:{x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2,distance:Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)};};
   const clear=()=>{pointers.clear();previous=null;};resetGestures.push(clear);
   node.addEventListener('wheel',event=>{event.preventDefault();const p=point(event.clientX,event.clientY);zoomAt(view.zoom*Math.exp(-event.deltaY*0.002),p.x,p.y);},{passive:false});
   node.onkeydown=event=>{
    const delta={ArrowLeft:[0.05,0],ArrowRight:[-0.05,0],ArrowUp:[0,0.05],ArrowDown:[0,-0.05]};
    if(event.key==='+'||event.key==='='){event.preventDefault();zoomAt(view.zoom*1.25);}
    else if(event.key==='-'){event.preventDefault();zoomAt(view.zoom/1.25);}
    else if(event.key==='0'||event.key==='Home'){event.preventDefault();update({zoom:1,x:0,y:0});}
    else if(delta[event.key]){event.preventDefault();const [x,y]=delta[event.key];update({...view,x:view.x+x,y:view.y+y});}
   };
   node.onpointerdown=event=>{if(event.button!==0)return;node.focus();node.setPointerCapture?.(event.pointerId);pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});previous=gesture();};
   node.onpointermove=event=>{
    if(!pointers.has(event.pointerId))return;
    pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});const next=gesture(),old=previous;
    if(next&&old){
     const p=point(next.x,next.y),before=point(old.x,old.y),zoom=next.distance&&old.distance?Math.max(1,Math.min(8,view.zoom*next.distance/old.distance)):view.zoom,ratio=zoom/view.zoom;
     update({zoom,x:p.x-(before.x-view.x)*ratio,y:p.y-(before.y-view.y)*ratio});
    }
    previous=next;
   };
   const release=event=>{pointers.delete(event.pointerId);previous=gesture();};
   node.onpointerup=release;node.onpointercancel=release;node.onlostpointercapture=release;
   surfaces.push({node,urls});
   if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{clear();update(view);});observer.observe(node);observers.push(observer);}
   return node;
  };
  const image=(url,label,container)=>{
   const img=el('img'),status=el('div','cs-compare-image-status','图片加载中…');status.setAttribute('role','status');img.src=url;img.alt=label;img.draggable=false;
   img.onload=()=>{if(img.naturalWidth&&img.naturalHeight)natural.set(url,{width:img.naturalWidth,height:img.naturalHeight});status.hidden=true;update(view);};
   img.onerror=()=>{img.hidden=true;status.hidden=false;status.textContent=`${label}加载失败，可选择其他参考或稍后重试。`;};
   images.push(img);container.append(img,status);return img;
  };
  const draw=()=>{
   disconnect();surfaces=[];images=[];bar.replaceChildren();
   if(ref){
    bar.append(select(refs.map(r=>[r.id,r.label]),ref.id,v=>{ref=refs.find(r=>r.id===v)||refs[0];view={zoom:1,x:0,y:0};draw();},{label:'选择本次生成的参考'}));
    const seg=el('div','cs-seg');for(const [v,l]of [['side','并排'],['slider','滑杆']]){const b=action(l,()=>{cmpMode=v;draw();});b.setAttribute('aria-pressed',String(cmpMode===v));seg.append(b);}bar.append(seg);
   }else bar.append(el('p','cs-compare-hint',result.snapshot?'这条提交快照没有可用的参考图。仍可查看生成结果。':'这条旧记录没有生成快照，无法确定当时的参考图。仍可查看生成结果。'));
   stage.replaceChildren();stage.dataset.mode=cmpMode;
   slider.hidden=cmpMode!=='slider'||!ref;
   if(ref&&cmpMode==='slider'){
    const box=surface('滑杆对比',[ref.url,result.imageUrl],'cs-compare-overlay'),over=el('div','cs-compare-top');
    image(result.imageUrl,'生成结果',box);image(ref.url,ref.label,over);box.append(over);stage.append(box);
    const applySplit=()=>{split=Number(range.value);over.style.clipPath=`inset(0 ${100-split}% 0 0)`;ratioLabel.textContent=`${split}%`;range.setAttribute('aria-valuetext',`${split}% 参考图`);};
    range.oninput=applySplit;applySplit();
   }else{
    const entries=ref?[[ref.url,ref.label],[result.imageUrl,'生成结果']]:[[result.imageUrl,'生成结果']];
    stage.dataset.single=String(!ref);
    for(const [url,label]of entries){const pane=el('figure','cs-compare-pane'),vp=surface(label,[url]);image(url,label,vp);pane.append(vp,el('figcaption','',label));stage.append(pane);}
   }
   update(view);
  };
  dialog.append(head,description,bar,controls,stage,slider,el('p','cs-compare-hint','滚轮或双指共同缩放 · 放大后拖动 · 加减键缩放、方向键移动、0 键复位'));
  dialog.addEventListener('close',()=>{disconnect();dialogs.delete(dialog);dialog.remove();if(returnFocus?.isConnected)returnFocus.focus?.();});
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialogs.add(dialog);document.body.append(dialog);dialog.showModal?.();draw();
 }

 return {
  load(){
   disposed=false;unsub?.();menuListeners(false);closeMenus();root.replaceChildren();root.className='character-studio cs-history-library';
   root.append(el('h2','cs-history-heading','AI角色合成库'));
   const toolbar=el('div','cs-history-toolbar');
   search=el('input');search.type='search';search.placeholder='搜索提示词、配方或生成引擎';search.setAttribute('aria-label','搜索合成记录');search.value=query;search.oninput=()=>{query=search.value;render(true);};
   count=el('span','cs-history-count');count.setAttribute('role','status');count.setAttribute('aria-live','polite');
   const actions=el('div','cs-row-actions cs-history-toolbar-actions'),more=moreMenu('合成库更多操作',[
    ['清空全部记录',()=>{if(confirm('确定清空当前浏览器中的全部合成记录及参考快照？此操作无法撤销。'))return store.clearHistory();},'cs-history-delete'],
   ]);clear=more.buttons[0];
   actions.append(action('生成角色图',()=>onCompose?.(),'cs-primary'),more.node);toolbar.append(search,count,actions);
   grid=el('div','cs-history official-list-grid');note=el('p','cs-history-note');root.append(toolbar,grid,note);
   window.addEventListener?.('online',updateNote);window.addEventListener?.('offline',updateNote);menuListeners(true);unsub=store.subscribe(()=>render());render(true);
  },
  suspend(){disposed=true;unsub?.();unsub=null;menuListeners(false);closeMenus();window.removeEventListener?.('online',updateNote);window.removeEventListener?.('offline',updateNote);for(const dialog of dialogs)dialog.close?.();},
 };
}
