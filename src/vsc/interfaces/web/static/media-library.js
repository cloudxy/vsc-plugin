import {msg,joinMessages,setText,bindAttribute,option as localizedOption,translate,onLocaleChange} from './i18n.js';

// Global read-only media directory across readable PostgreSQL projects.
// Provenance categories, classic fixed-draft reuse and source links come from
// backend authorities; this module never creates shares, jobs or fake metadata.
const PAGE_LIMIT=20;
const CATEGORIES=['asset_image','shot_image','composite_video','canvas_image','canvas_audio','canvas_video'];
const CATEGORY_SET=new Set(CATEGORIES);
const SHORTCUTS=['today','yesterday','day_before','this_month','last_month'];
const key=name=>'media.library.'+name;
const label=(name,values)=>msg(key(name),values);
const node=(tag,text,className)=>{const value=document.createElement(tag);if(text!=null)setText(value,text);if(className)value.className=className;return value;};
const button=(text,run,className='')=>{const value=node('button',text,className);value.type='button';value.addEventListener('click',run);return value;};
function setInlineStyle(el,prop,val){
  if(!el)return;
  if(el.style&&typeof el.style==='object'){el.style[prop]=val;return;}
  const kebab=prop.replace(/[A-Z]/g,m=>'-'+m.toLowerCase());
  const raw=String(el.getAttribute?.('style')||'');
  const parts=raw.split(';').map(s=>s.trim()).filter(s=>s&&!s.startsWith(kebab+':'));
  if(val!==''&&val!==null&&val!==undefined)parts.push(`${kebab}:${val}`);
  el.setAttribute?.('style',parts.join(';'));
}
const identity=session=>JSON.stringify([session?.actor??null,session?.identityId??null,session?.workspaceId??null]);
const pad2=n=>String(n).padStart(2,'0');
const toYMD=d=>`${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`;
function parseYMD(value){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
  const [y,m,d]=value.split('-').map(Number),check=new Date(y,m-1,d);
  return check.getFullYear()===y&&check.getMonth()===m-1&&check.getDate()===d?{y,m,d}:null;
}
function localDayIso(ymd,addDays=0){const p=parseYMD(ymd);if(!p)return null;return new Date(p.y,p.m-1,p.d+addDays,0,0,0,0).toISOString();}
function shortcutDates(kind,base){
  const d=new Date(base.getFullYear(),base.getMonth(),base.getDate());
  if(kind==='today')return [toYMD(d),toYMD(d)];
  if(kind==='yesterday'){const v=new Date(d.getFullYear(),d.getMonth(),d.getDate()-1);return [toYMD(v),toYMD(v)];}
  if(kind==='day_before'){const v=new Date(d.getFullYear(),d.getMonth(),d.getDate()-2);return [toYMD(v),toYMD(v)];}
  if(kind==='this_month')return [toYMD(new Date(d.getFullYear(),d.getMonth(),1)),toYMD(d)];
  return [toYMD(new Date(d.getFullYear(),d.getMonth()-1,1)),toYMD(new Date(d.getFullYear(),d.getMonth(),0))];
}
function monthCells(year,month){
  const first=new Date(year,month,1),lead=first.getDay(),start=new Date(year,month,1-lead),cells=[];
  for(let i=0;i<42;i++){const cur=new Date(start.getFullYear(),start.getMonth(),start.getDate()+i);cells.push({ymd:toYMD(cur),day:cur.getDate(),inMonth:cur.getMonth()===month});}
  return cells;
}
const hasDimensions=row=>Number.isInteger(row?.width)&&row.width>0&&Number.isInteger(row?.height)&&row.height>0;
const formatDimensions=row=>hasDimensions(row)?`${row.width}×${row.height}`:null;
const hasDuration=ms=>typeof ms==='number'&&Number.isFinite(ms)&&ms>0;
function formatDuration(ms){
  if(!hasDuration(ms))return null;
  const total=Math.max(1,Math.round(ms/1000)),hrs=Math.floor(total/3600),mins=Math.floor((total%3600)/60),secs=total%60;
  return hrs>0?`${pad2(hrs)}:${pad2(mins)}:${pad2(secs)}`:`${pad2(mins)}:${pad2(secs)}`;
}
function formatCreated(iso,nowDate){
  if(typeof iso!=='string'||!iso)return null;
  const ts=Date.parse(iso);if(!Number.isFinite(ts))return null;
  const diffMs=Math.max(0,nowDate.getTime()-ts),mins=Math.floor(diffMs/60000),hours=Math.floor(diffMs/3600000),days=Math.floor(diffMs/86400000);
  if(mins<1)return msg('common.just_now');
  if(mins<60)return label('minutes_ago',{count:mins});
  if(hours<24)return label('hours_ago',{count:hours});
  if(days===1)return label('shortcut_yesterday');
  if(days===2)return label('shortcut_day_before');
  if(days<7)return label('days_ago',{count:days});
  if(days<30)return label('weeks_ago',{count:Math.max(1,Math.floor(days/7))});
  return toYMD(new Date(ts));
}
const canReuse=actions=>Boolean(actions?.reuse?.available===true&&actions.reuse.kind==='classic_fixed_draft'&&typeof actions.reuse.href==='string'&&actions.reuse.href);
const canSource=actions=>Boolean(actions?.source?.available===true&&typeof actions.source.href==='string'&&actions.source.href);
const canDownload=actions=>Boolean(actions?.download?.available===true&&typeof actions.download.href==='string'&&actions.download.href);
function cleanupMediaNode(el){
  if(!el)return;
  try{el.pause?.();}catch{}
  el.removeAttribute?.('src');
  if('src' in el)try{el.src='';}catch{}
  try{el.load?.();}catch{}
}
function cleanupMediaTree(container){
  if(!container?.querySelectorAll)return;
  for(const cls of ['.ml-cover-video','.ml-av-player'])for(const item of container.querySelectorAll(cls))cleanupMediaNode(item);
}
const isAbort=error=>Boolean(error&&(error.name==='AbortError'||error.code==='ABORT_ERR'));

export function createMediaLibrary(root,ctx){
  let epoch=0,active=null;
  const session=()=>ctx.session?.()||{};
  const now=()=>ctx.now?new Date(ctx.now()):new Date();
  const live=s=>active===s&&s.epoch===epoch&&s.identity===identity(session());
  const report=(s,error)=>{if(live(s)&&!isAbort(error)){const text=error?.message||String(error);setText(s.status,text);ctx.notice?.(text);}};
  function makeController(s,slot){
    if(s[slot]){s[slot].abort();s.controllers.delete(s[slot]);}
    const controller=new AbortController();
    s[slot]=controller;s.controllers.add(controller);
    return controller;
  }
  function releaseController(s,slot,controller){
    s.controllers.delete(controller);
    if(s[slot]===controller)s[slot]=null;
  }
  function listen(s,target,type,handler,options){
    if(!target?.addEventListener)return ()=>{};
    target.addEventListener(type,handler,options);
    const off=()=>{target.removeEventListener?.(type,handler,options);s.cleanups.delete(off);};
    s.cleanups.add(off);
    return off;
  }
  function validatePage(value,start){
    if(!value||!Array.isArray(value.items)||!Number.isInteger(value.total)||value.total<0||
      !(value.next_offset===null||Number.isInteger(value.next_offset)&&value.next_offset>start)||
      value.items.some(row=>!row||typeof row.id!=='string'||!row.id||typeof row.project_id!=='string'||!row.project_id||
        typeof row.name!=='string'||typeof row.modality!=='string'||typeof row.content_url!=='string'))
      throw new Error(translate(label('invalid_response')));
  }
  function validateDetail(value,row){
    if(!value||value.id!==row.id||value.project_id!==row.project_id||typeof value.content_url!=='string')
      throw new Error(translate(label('invalid_response')));
  }
  async function followHref(s,href,projectId){
    if(!live(s)||s.navigating)return;
    const parsed=new URL(href,'http://vsc.local'),page=parsed.searchParams.get('page'),project=parsed.searchParams.get('project')||projectId;
    if(!page||!project)throw new Error(translate(label('invalid_response')));
    const scope=parsed.searchParams.get('scope')||null,options={};
    for(const [k,v] of parsed.searchParams.entries())if(!['page','project','scope'].includes(k))options[k]=v;
    closeDatePopover(s,false);closeViewer(s,false);
    s.navigating=true;
    try{await ctx.navigate(page,scope,project,options);}
    catch(error){report(s,error);}
    finally{if(live(s))s.navigating=false;}
  }
  function renderActionBar(s,row,actionsObj,className){
    const bar=node('div',null,className);
    if(canReuse(actionsObj)){
      const btn=button(label('reuse_config'),event=>{event.stopPropagation?.();followHref(s,actionsObj.reuse.href,row.project_id);},'ml-action-reuse');
      btn.dataset.action='reuse';bar.append(btn);
    }
    if(canSource(actionsObj)){
      const btn=button(label('open_source'),event=>{event.stopPropagation?.();followHref(s,actionsObj.source.href,row.project_id);},'ml-action-source');
      btn.dataset.action='source';bar.append(btn);
    }
    if(canDownload(actionsObj)){
      const link=node('a',label('download'),'ml-action-download');
      link.href=actionsObj.download.href;link.setAttribute('download',row.name||'');
      link.dataset.action='download';
      link.addEventListener('click',event=>event.stopPropagation?.());
      bar.append(link);
    }
    return bar;
  }
  function renderDateTrigger(s){
    const activeRange=Boolean(s.filters.startDate&&s.filters.endDate);
    setText(s.dateStartText,activeRange?s.filters.startDate:label('start_time'));
    setText(s.dateEndText,activeRange?s.filters.endDate:label('end_time'));
    s.dateTrigger.classList.toggle('ml-date-has-value',activeRange);
    s.dateTrigger.setAttribute('aria-expanded',String(s.dateOpen));
    s.dateClear.hidden=!activeRange;
  }
  function paintDatePopover(s){
    if(!s.dateOpen||!live(s))return;
    s.datePanels.replaceChildren();
    const todayYmd=toYMD(now()),selStart=s.draftStart||s.filters.startDate,selEnd=s.draftStart?s.draftStart:s.filters.endDate;
    for(let offset=0;offset<2;offset++){
      const panelDate=new Date(s.viewYear,s.viewMonth+offset,1),py=panelDate.getFullYear(),pm=panelDate.getMonth();
      const panel=node('div',null,'ml-month-panel'),head=node('div',null,'ml-month-header');
      if(offset===0){
        const pyBtn=button('«',()=>{s.viewYear-=1;paintDatePopover(s);},'ml-prev-year');bindAttribute(pyBtn,'aria-label',label('prev_year'));
        const pmBtn=button('‹',()=>{const d=new Date(s.viewYear,s.viewMonth-1,1);s.viewYear=d.getFullYear();s.viewMonth=d.getMonth();paintDatePopover(s);},'ml-prev-month');bindAttribute(pmBtn,'aria-label',label('prev_month'));
        const leftNav=node('div',null,'ml-month-nav');leftNav.append(pyBtn,pmBtn);head.append(leftNav);
      }else head.append(node('div',null,'ml-month-nav'));
      head.append(node('strong',label('month_heading',{year:py,month:pm+1}),'ml-month-title'));
      if(offset===1){
        const nmBtn=button('›',()=>{const d=new Date(s.viewYear,s.viewMonth+1,1);s.viewYear=d.getFullYear();s.viewMonth=d.getMonth();paintDatePopover(s);},'ml-next-month');bindAttribute(nmBtn,'aria-label',label('next_month'));
        const nyBtn=button('»',()=>{s.viewYear+=1;paintDatePopover(s);},'ml-next-year');bindAttribute(nyBtn,'aria-label',label('next_year'));
        const rightNav=node('div',null,'ml-month-nav');rightNav.append(nmBtn,nyBtn);head.append(rightNav);
      }else head.append(node('div',null,'ml-month-nav'));
      const week=node('div',null,'ml-weekdays');
      for(let w=0;w<7;w++)week.append(node('span',label('weekday_'+w)));
      const days=node('div',null,'ml-days');
      for(const cell of monthCells(py,pm)){
        const dayBtn=button(String(cell.day),()=>pickCalendarDay(s,cell.ymd),'ml-day');
        dayBtn.dataset.date=cell.ymd;
        if(!cell.inMonth)dayBtn.classList.add('ml-day-outside');
        if(cell.ymd===todayYmd)dayBtn.classList.add('ml-day-today');
        if(selStart&&selEnd&&cell.ymd>=selStart&&cell.ymd<=selEnd)dayBtn.classList.add('ml-day-in-range');
        if(cell.ymd===selStart||cell.ymd===selEnd)dayBtn.classList.add('ml-day-selected');
        days.append(dayBtn);
      }
      panel.append(head,week,days);s.datePanels.append(panel);
    }
  }
  function openDatePopover(s){
    if(!live(s)||s.dateOpen)return;
    s.dateOpen=true;s.draftStart=null;
    const anchor=parseYMD(s.filters.startDate),base=anchor?new Date(anchor.y,anchor.m-1,1):now();
    s.viewYear=base.getFullYear();s.viewMonth=base.getMonth();
    s.datePopover.hidden=false;renderDateTrigger(s);paintDatePopover(s);
    if(typeof document!=='undefined'&&document.addEventListener){
      s.dateOutsideOff?.();
      s.dateOutsideOff=listen(s,document,'mousedown',event=>{
        const t=event.target;
        if(t&&!containsNode(s.dateWrap,t))closeDatePopover(s,false);
      });
    }
    if(typeof window!=='undefined') {
      s.dateKeyOff?.();
      s.dateKeyOff=listen(s,window,'keydown',event=>{if(event.key==='Escape'&&s.dateOpen){event.preventDefault?.();closeDatePopover(s,true);}});
    }
  }
  function closeDatePopover(s,restoreFocus=true){
    if(!s.dateOpen)return;
    s.dateOpen=false;s.draftStart=null;s.datePopover.hidden=true;
    s.dateOutsideOff?.();s.dateOutsideOff=null;
    s.dateKeyOff?.();s.dateKeyOff=null;
    renderDateTrigger(s);
    if(restoreFocus&&live(s))s.dateTrigger.focus?.();
  }
  function pickCalendarDay(s,ymd){
    if(!live(s))return;
    if(!s.draftStart){s.draftStart=ymd;paintDatePopover(s);return;}
    const [startDate,endDate]=s.draftStart<=ymd?[s.draftStart,ymd]:[ymd,s.draftStart];
    s.filters.startDate=startDate;s.filters.endDate=endDate;
    closeDatePopover(s,true);readList(s);
  }
  function applyShortcut(s,kind){
    if(!live(s))return;
    const [startDate,endDate]=shortcutDates(kind,now());
    s.filters.startDate=startDate;s.filters.endDate=endDate;
    closeDatePopover(s,true);readList(s);
  }
  function clearDateRange(s,event){
    event?.stopPropagation?.();
    if(!live(s))return;
    s.filters.startDate='';s.filters.endDate='';
    closeDatePopover(s,false);renderDateTrigger(s);readList(s);
  }
  async function readList(s,append=false){
    if(!live(s)||append&&(s.loading||s.loadingMore||s.next===null))return false;
    const start=append?s.next:0,ticket=++s.listTicket,controller=makeController(s,'listController'),filters={...s.filters};
    if(!append){s.rows=[];s.total=0;s.next=null;s.loading=true;s.listError=null;setText(s.status,'');paint(s);}
    else{s.loadingMore=true;s.listError=null;paintFooter(s);}
    const params=new URLSearchParams({offset:String(start),limit:String(PAGE_LIMIT)});
    if(filters.project_id)params.set('project_id',filters.project_id);
    if(filters.project_id&&filters.episode_id)params.set('episode_id',filters.episode_id);
    if(filters.category)params.set('category',filters.category);
    if(filters.startDate&&filters.endDate){
      params.set('created_after',localDayIso(filters.startDate,0));
      params.set('created_before',localDayIso(filters.endDate,1));
    }
    try{
      const value=await ctx.api('/api/v1/project-media?'+params,{signal:controller.signal});
      if(!live(s)||ticket!==s.listTicket)return false;
      validatePage(value,start);
      const seen=new Set(append?s.rows.map(r=>r.project_id+':'+r.id):[]);
      const merged=append?[...s.rows]:[];
      for(const row of value.items){const rowKey=row.project_id+':'+row.id;if(!seen.has(rowKey)){merged.push(row);seen.add(rowKey);}}
      s.rows=merged;s.total=value.total;s.next=value.next_offset;s.listError=null;s.loaded=true;
      paint(s);syncOpenImageSequence(s);
      return true;
    }catch(error){
      if(live(s)&&ticket===s.listTicket&&!isAbort(error)){
        if(!append){s.rows=[];s.total=0;s.next=null;}
        s.listError={error,append,start};paint(s);
      }
      return false;
    }finally{
      releaseController(s,'listController',controller);
      if(live(s)&&ticket===s.listTicket){s.loading=false;s.loadingMore=false;s.grid.removeAttribute('aria-busy');paintFooter(s);}
    }
  }
  function paintFooter(s){
    if(!live(s))return;
    s.footer.replaceChildren();
    if(s.loading||s.loadingMore)s.footer.append(node('p',msg('ui.loading'),'ml-loading'));
    else if(s.listError){s.footer.append(node('p',s.listError.error.message||String(s.listError.error),'ml-error'),button(msg('ui.reload'),()=>readList(s,s.listError.append),'ml-retry'));}
    else if(s.next!==null)s.footer.append(button(label('load_more'),()=>readList(s,true),'ml-load-more'));
    else if(s.loaded&&s.rows.length)s.footer.append(node('p',label('no_more'),'ml-no-more'));
  }
  function renderCoverVisual(row,openBtn){
    const src=row.preview_url||row.content_url;
    if(row.modality==='image'){
      const backdrop=node('img',null,'ml-cover-backdrop');backdrop.src=src;backdrop.loading='lazy';backdrop.setAttribute('aria-hidden','true');bindAttribute(backdrop,'alt','');
      const img=node('img',null,'ml-cover-img');img.src=src;img.loading='lazy';bindAttribute(img,'alt','');
      img.addEventListener('error',()=>{backdrop.remove();img.remove();openBtn.append(node('span',msg('ui.preview_is_currently_unavailable'),'ml-preview-failed'));});
      openBtn.append(backdrop,img);
      return;
    }
    if(row.modality==='video'){
      if(row.poster_url){
        const backdrop=node('img',null,'ml-cover-backdrop');backdrop.src=row.poster_url;backdrop.loading='lazy';backdrop.setAttribute('aria-hidden','true');bindAttribute(backdrop,'alt','');
        const img=node('img',null,'ml-cover-img');img.src=row.poster_url;img.loading='lazy';bindAttribute(img,'alt','');
        img.addEventListener('error',()=>{backdrop.remove();img.remove();openBtn.append(node('span',msg('ui.preview_is_currently_unavailable'),'ml-preview-failed'));});
        openBtn.append(backdrop,img);
      }else{
        const video=node('video',null,'ml-cover-video');video.src=src;video.muted=true;video.preload='metadata';video.setAttribute('playsinline','');
        video.addEventListener('error',()=>{cleanupMediaNode(video);video.remove();openBtn.append(node('span',msg('ui.preview_is_currently_unavailable'),'ml-preview-failed'));});
        openBtn.append(video);
      }
      return;
    }
    const audioBox=node('div',null,'ml-audio-cover'),wave=node('span',null,'ml-audio-icon');
    wave.setAttribute('aria-hidden','true');
    wave.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 10v4"/></svg>';
    audioBox.append(wave);
    if(row.poster_url){const wf=node('img',null,'ml-audio-waveform');wf.src=row.poster_url;wf.loading='lazy';bindAttribute(wf,'alt','');wf.addEventListener('error',()=>wf.remove());audioBox.append(wf);}
    openBtn.append(audioBox);
  }
  function paint(s){
    if(!live(s))return;
    cleanupMediaTree(s.grid);
    s.grid.replaceChildren();
    setText(s.totalLabel,label('total',{count:s.total}));
    s.grid.setAttribute('aria-busy',String(s.loading||s.loadingMore));
    const nowDate=now();
    for(const row of s.rows){
      const tile=node('article',null,'ml-card');
      tile.dataset.mediaId=row.id;tile.dataset.projectId=row.project_id;tile.dataset.modality=row.modality;
      const cover=node('div',null,'ml-cover');
      const openBtn=button(null,()=>openMediaItem(s,row,openBtn),'ml-open');
      bindAttribute(openBtn,'aria-label',msg('ui.open_value0',{value0:row.name}));
      renderCoverVisual(row,openBtn);
      cover.append(openBtn);
      const durationText=formatDuration(row.duration_ms);
      if(durationText&&(row.modality==='video'||row.modality==='audio')){
        const dur=node('span',null,'ml-duration'),playIcon=node('span','▶','ml-duration-icon');
        playIcon.setAttribute('aria-hidden','true');
        dur.append(playIcon,node('span',durationText,'ml-duration-text'));
        cover.append(dur);
      }
      const overlayActions=renderActionBar(s,row,row.actions,'ml-card-actions');
      if(overlayActions.childElementCount)cover.append(overlayActions);
      const title=node('h3',row.name,'ml-title');bindAttribute(title,'title',row.name);
      const meta=node('div',null,'ml-meta');
      const createdLabel=formatCreated(row.created_at,nowDate);
      if(createdLabel!=null){const timeEl=node('span',createdLabel,'ml-time');if(row.created_at)bindAttribute(timeEl,'title',row.created_at);meta.append(timeEl);}
      if(CATEGORY_SET.has(row.category))meta.append(node('span',label('category_'+row.category),'ml-badge'));
      const scopeParts=[row.project_name,row.episode_name].filter(Boolean);
      if(scopeParts.length)meta.append(node('span',scopeParts.join(' · '),'ml-scope'));
      const dims=formatDimensions(row);
      if(dims)meta.append(node('span',dims,'ml-dimensions'));
      tile.append(cover,title,meta);s.grid.append(tile);
    }
    if(s.loaded&&!s.loading&&!s.rows.length&&!s.listError)s.grid.append(node('p',label('empty'),'ml-empty'));
    paintFooter(s);
  }
  async function loadProjects(s){
    const ticket=++s.projectsTicket,controller=makeController(s,'projectsController');
    try{
      const value=await ctx.projects({isCurrent:()=>live(s)&&ticket===s.projectsTicket,signal:controller.signal});
      if(!live(s)||ticket!==s.projectsTicket)return;
      const rows=Array.isArray(value)?value:value?.items;
      if(!Array.isArray(rows))throw new Error(translate(label('invalid_response')));
      s.projects=rows;
      s.project.replaceChildren(localizedOption('',msg('novel-parser.all_projects')));
      for(const row of rows)s.project.append(localizedOption(row.id,row.name));
      s.project.value=rows.some(r=>r.id===s.filters.project_id)?s.filters.project_id:'';
      s.projectRetry.hidden=true;
    }catch(error){
      if(live(s)&&ticket===s.projectsTicket&&!isAbort(error)){report(s,error);s.projectRetry.hidden=false;}
    }finally{releaseController(s,'projectsController',controller);}
  }
  async function loadEpisodes(s,projectId,selected=''){
    s.episode.disabled=true;s.episode.replaceChildren(localizedOption('',msg('replica.all_episodes')));
    if(!projectId){if(s.episodeController){s.episodeController.abort();s.controllers.delete(s.episodeController);s.episodeController=null;}return;}
    const ticket=++s.episodeTicket,controller=makeController(s,'episodeController');
    try{
      const value=await ctx.episodes(projectId,{isCurrent:()=>live(s)&&ticket===s.episodeTicket&&s.filters.project_id===projectId,signal:controller.signal});
      if(!live(s)||ticket!==s.episodeTicket||s.filters.project_id!==projectId)return;
      const rows=Array.isArray(value)?value:value?.items;
      if(!Array.isArray(rows))throw new Error(translate(label('invalid_response')));
      for(const row of rows)s.episode.append(localizedOption(row.id,row.title||row.name||row.display_code||row.id));
      const matched=rows.some(r=>r.id===selected)?selected:'';
      s.episode.value=matched;s.filters.episode_id=matched;s.episode.disabled=false;s.episodeRetry.hidden=true;
    }catch(error){
      if(live(s)&&ticket===s.episodeTicket&&s.filters.project_id===projectId&&!isAbort(error)){report(s,error);s.episodeRetry.hidden=false;}
    }finally{releaseController(s,'episodeController',controller);}
  }
  function changeProject(s){
    if(!live(s))return;
    s.filters.project_id=s.project.value;s.filters.episode_id='';s.episode.value='';s.episodeRetry.hidden=true;
    readList(s);loadEpisodes(s,s.filters.project_id,'');
  }
  function closeViewer(s,restoreFocus=true){
    if(!s.viewer)return;
    const current=s.viewer;s.viewer=null;
    if(s.detailController){s.detailController.abort();s.controllers.delete(s.detailController);s.detailController=null;}
    current.keyOff?.();current.visOff?.();
    cleanupMediaTree(current.dialog);
    if(current.dialog.open)current.dialog.close?.();
    current.dialog.remove?.();
    if(restoreFocus&&live(s))current.opener?.focus?.();
  }
  async function loadDetailInto(s,row,hostNodes){
    const ticket=++s.detailTicket,controller=makeController(s,'detailController');
    const {body,actionsSlot}=hostNodes;
    body.replaceChildren(node('p',msg('ui.loading'),'ml-detail-loading'));
    actionsSlot.replaceChildren(renderActionBar(s,row,row.actions,'ml-detail-action-row'));
    try{
      const detail=await ctx.api(`/api/v1/projects/${encodeURIComponent(row.project_id)}/media/${encodeURIComponent(row.id)}/catalog-detail`,{signal:controller.signal});
      if(!live(s)||ticket!==s.detailTicket||!s.viewer)return;
      validateDetail(detail,row);
      body.replaceChildren();
      if(typeof detail.prompt==='string'&&detail.prompt.trim()){
        const section=node('section',null,'ml-detail-section');
        section.append(node('h4',label('prompt'),'ml-detail-heading'),node('p',detail.prompt,'ml-detail-prompt'));
        body.append(section);
      }
      const tags=node('div',null,'ml-detail-tags');
      if(CATEGORY_SET.has(detail.category))tags.append(node('span',label('category_'+detail.category),'ml-detail-tag'));
      if(detail.model?.name)tags.append(node('span',detail.model.version?`${detail.model.name} (${detail.model.version})`:detail.model.name,'ml-detail-tag'));
      if(typeof detail.aspect_ratio==='string'&&detail.aspect_ratio)tags.append(node('span',detail.aspect_ratio,'ml-detail-tag'));
      if(typeof detail.resolution_label==='string'&&detail.resolution_label)tags.append(node('span',detail.resolution_label,'ml-detail-tag'));
      const dims=formatDimensions(detail)||formatDimensions(row);
      if(dims)tags.append(node('span',dims,'ml-detail-tag'));
      const dur=formatDuration(detail.duration_ms??row.duration_ms);
      if(dur)tags.append(node('span',dur,'ml-detail-tag'));
      if(tags.childElementCount)body.append(tags);
      actionsSlot.replaceChildren(renderActionBar(s,row,detail.actions||row.actions,'ml-detail-action-row'));
    }catch(error){
      if(live(s)&&ticket===s.detailTicket&&s.viewer&&!isAbort(error)){
        body.replaceChildren(node('p',error.message||label('detail_failed'),'ml-detail-error'),button(msg('ui.reload'),()=>loadDetailInto(s,row,hostNodes),'ml-detail-retry'));
      }
    }finally{releaseController(s,'detailController',controller);}
  }
  const imageSequence=s=>s.rows.filter(r=>r.modality==='image');
  function syncOpenImageSequence(s){
    if(s.viewer?.kind!=='image')return;
    const seq=imageSequence(s),idx=seq.findIndex(r=>r.project_id===s.viewer.row.project_id&&r.id===s.viewer.row.id);
    if(idx<0)return;
    s.viewer.index=idx;
    setText(s.viewer.counter,`${idx+1} / ${seq.length}`);
    s.viewer.prevBtn.hidden=s.viewer.prevBtn.disabled=idx<=0;
    s.viewer.nextBtn.hidden=s.viewer.nextBtn.disabled=idx>=seq.length-1;
  }
  function openImageViewer(s,initialRow,opener){
    closeDatePopover(s,false);closeViewer(s,false);
    const seq=imageSequence(s),startIndex=seq.findIndex(r=>r.project_id===initialRow.project_id&&r.id===initialRow.id);
    if(startIndex<0)return;
    const dialog=node('dialog',null,'ml-image-viewer');bindAttribute(dialog,'aria-label',label('image_viewer'));
    const layout=node('div',null,'ml-viewer-layout'),stage=node('div',null,'ml-viewer-stage');
    const closeBtn=button('×',()=>closeViewer(s,true),'ml-viewer-close');bindAttribute(closeBtn,'aria-label',msg('common.close'));
    let sidebarOpen=true;
    const sidebar=node('aside',null,'ml-viewer-sidebar');
    const foldBtn=button('▤',()=>{sidebarOpen=!sidebarOpen;sidebar.hidden=!sidebarOpen;foldBtn.setAttribute('aria-expanded',String(sidebarOpen));if(viewerZoom.getScale()===1)viewerZoom.reset();},'ml-viewer-fold');
    bindAttribute(foldBtn,'aria-label',label('toggle_sidebar'));foldBtn.setAttribute('aria-expanded','true');
    const prevBtn=button('‹',()=>stepImage(-1),'ml-viewer-prev');bindAttribute(prevBtn,'aria-label',label('prev_image'));
    const nextBtn=button('›',()=>stepImage(1),'ml-viewer-next');bindAttribute(nextBtn,'aria-label',label('next_image'));
    const counter=node('span',null,'ml-viewer-counter');
    const frame=node('div',null,'ml-viewer-frame');
    if(typeof frame.scrollLeft!=='number')frame.scrollLeft=0;
    if(typeof frame.scrollTop!=='number')frame.scrollTop=0;
    const zoomBar=node('div',null,'ml-viewer-zoom-bar');
    const zoomOutBtn=button('−',()=>viewerZoom.zoomOut(),'ml-viewer-zoom-btn ml-viewer-zoom-out');bindAttribute(zoomOutBtn,'aria-label','缩小图片');bindAttribute(zoomOutBtn,'title','缩小 (-)');
    const zoomLevel=node('span','100%','ml-viewer-zoom-level');zoomLevel.setAttribute('aria-live','polite');
    const zoomInBtn=button('＋',()=>viewerZoom.zoomIn(),'ml-viewer-zoom-btn ml-viewer-zoom-in');bindAttribute(zoomInBtn,'aria-label','放大图片');bindAttribute(zoomInBtn,'title','放大 (+)');
    const zoomFitBtn=button('适应窗口',()=>viewerZoom.reset(),'ml-viewer-zoom-btn ml-viewer-zoom-fit');bindAttribute(zoomFitBtn,'aria-label','适应窗口大小');
    const zoomActualBtn=button('1:1',()=>viewerZoom.zoomNatural(),'ml-viewer-zoom-btn ml-viewer-zoom-actual');bindAttribute(zoomActualBtn,'aria-label','原始像素大小');bindAttribute(zoomActualBtn,'title','原始大小 (1:1)');
    zoomBar.append(zoomOutBtn,zoomLevel,zoomInBtn,zoomFitBtn,zoomActualBtn);
    stage.append(closeBtn,foldBtn,prevBtn,nextBtn,counter,zoomBar,frame);
    let currentImg=null,scale=1,fitW=0,fitH=0,initialW=0,initialH=0,drag=null;
    const MIN_SCALE=0.25,MAX_SCALE=4,ZOOM_STEP=0.25;
    function syncZoomBar(){
      setText(zoomLevel,`${Math.round(scale*100)}%`);
      zoomOutBtn.disabled=scale<=MIN_SCALE+1e-6;
      zoomInBtn.disabled=scale>=MAX_SCALE-1e-6;
    }
    function measureFit(){
      const availW=Math.max(200,(Number(frame.clientWidth)||880)-24);
      const availH=Math.max(200,(Number(frame.clientHeight)||600)-24);
      const natW=Math.max(1,Number(currentImg?.naturalWidth)||Number(initialW)||720);
      const natH=Math.max(1,Number(currentImg?.naturalHeight)||Number(initialH)||720);
      let ratio=Math.min(availW/natW,availH/natH,1);
      const minDisplay=Math.min(360,availW,availH);
      if(natW*ratio<minDisplay&&natH*ratio<minDisplay)ratio=Math.min(availW/natW,availH/natH,minDisplay/Math.max(natW,natH));
      fitW=Math.max(48,Math.round(natW*ratio));
      fitH=Math.max(48,Math.round(natH*ratio));
    }
    function applyScale(nextScale,focusX=null,focusY=null){
      if(!currentImg)return scale;
      if(!fitW||!fitH)measureFit();
      const clamped=Math.min(MAX_SCALE,Math.max(MIN_SCALE,Math.round(Number(nextScale)*100)/100));
      const prev=scale;
      scale=clamped;
      const targetW=Math.max(24,Math.round(fitW*scale));
      const targetH=Math.max(24,Math.round(fitH*scale));
      setInlineStyle(currentImg,'width',`${targetW}px`);
      setInlineStyle(currentImg,'height',`${targetH}px`);
      setInlineStyle(currentImg,'maxWidth','none');
      setInlineStyle(currentImg,'maxHeight','none');
      if(currentImg.dataset)currentImg.dataset.zoomScale=String(scale);
      currentImg.setAttribute?.('data-zoom-scale',String(scale));
      if(prev>0&&prev!==scale){
        const r=scale/prev;
        const cx=focusX??((Number(frame.clientWidth)||880)/2);
        const cy=focusY??((Number(frame.clientHeight)||600)/2);
        frame.scrollLeft=Math.max(0,Math.round(((Number(frame.scrollLeft)||0)+cx)*r-cx));
        frame.scrollTop=Math.max(0,Math.round(((Number(frame.scrollTop)||0)+cy)*r-cy));
      }
      syncZoomBar();
      return scale;
    }
    const viewerZoom={
      getScale:()=>scale,
      zoomIn:()=>applyScale(scale+ZOOM_STEP),
      zoomOut:()=>applyScale(scale-ZOOM_STEP),
      reset:()=>{
        if(!currentImg)return 1;
        measureFit();
        scale=1;
        setInlineStyle(currentImg,'width',`${fitW}px`);
        setInlineStyle(currentImg,'height',`${fitH}px`);
        setInlineStyle(currentImg,'maxWidth','none');
        setInlineStyle(currentImg,'maxHeight','none');
        if(currentImg.dataset)currentImg.dataset.zoomScale='1';
        currentImg.setAttribute?.('data-zoom-scale','1');
        frame.scrollLeft=0;frame.scrollTop=0;
        syncZoomBar();
        return scale;
      },
      zoomNatural:()=>{
        if(!currentImg)return 1;
        measureFit();
        const natW=Math.max(1,Number(currentImg.naturalWidth)||Number(initialW)||fitW);
        return applyScale(natW/Math.max(1,fitW));
      },
      bindImage:(imgEl,w,h)=>{
        currentImg=imgEl;initialW=Number(w)||0;initialH=Number(h)||0;fitW=0;fitH=0;scale=1;
        if(imgEl){
          imgEl.draggable=false;imgEl.setAttribute?.('draggable','false');
          imgEl.addEventListener('load',()=>{if(currentImg!==imgEl)return;if(scale===1)viewerZoom.reset();else{measureFit();applyScale(scale);}});
          imgEl.addEventListener('dblclick',ev=>{ev?.preventDefault?.();applyScale(scale>1.05?1:2,ev?.offsetX??null,ev?.offsetY??null);});
        }
        viewerZoom.reset();
      },
    };
    frame.addEventListener('wheel',ev=>{
      if(ev?.ctrlKey||ev?.metaKey){
        ev.preventDefault?.();
        applyScale(scale+(Number(ev.deltaY)<0?ZOOM_STEP:-ZOOM_STEP),ev.offsetX??null,ev.offsetY??null);
      }
    },{passive:false});
    frame.addEventListener('pointerdown',ev=>{
      if(ev?.button!=null&&ev.button!==0)return;
      drag={pointerId:ev?.pointerId,startX:Number(ev?.clientX)||0,startY:Number(ev?.clientY)||0,startLeft:Number(frame.scrollLeft)||0,startTop:Number(frame.scrollTop)||0,moved:false};
      frame.classList?.add?.('is-dragging');
      try{frame.setPointerCapture?.(ev?.pointerId);}catch{}
    });
    frame.addEventListener('pointermove',ev=>{
      if(!drag)return;
      if(drag.pointerId!==undefined&&ev?.pointerId!==undefined&&ev.pointerId!==drag.pointerId)return;
      const dx=(Number(ev?.clientX)||0)-drag.startX,dy=(Number(ev?.clientY)||0)-drag.startY;
      if(Math.abs(dx)>3||Math.abs(dy)>3)drag.moved=true;
      frame.scrollLeft=Math.max(0,drag.startLeft-dx);
      frame.scrollTop=Math.max(0,drag.startTop-dy);
      if(drag.moved)ev?.preventDefault?.();
    });
    const finishDrag=ev=>{
      if(!drag)return;
      if(ev?.pointerId!==undefined){try{frame.releasePointerCapture?.(ev.pointerId);}catch{}}
      drag=null;frame.classList?.remove?.('is-dragging');
    };
    frame.addEventListener('pointerup',finishDrag);
    frame.addEventListener('pointercancel',finishDrag);
    const sideScroll=node('div',null,'ml-detail-scroll'),title=node('h2',null,'ml-detail-title'),sub=node('p',null,'ml-detail-sub'),detailBody=node('div',null,'ml-detail-body'),detailActions=node('footer',null,'ml-detail-actions');
    sideScroll.append(title,sub,detailBody);sidebar.append(sideScroll,detailActions);
    layout.append(stage,sidebar);dialog.append(layout);document.body.append(dialog);
    const viewerState={kind:'image',dialog,opener,row:initialRow,index:startIndex,counter,prevBtn,nextBtn,keyOff:null,zoom:viewerZoom};
    s.viewer=viewerState;
    function showAt(nextIndex){
      const currentSeq=imageSequence(s);
      if(nextIndex<0||nextIndex>=currentSeq.length)return;
      const item=currentSeq[nextIndex];
      viewerState.row=item;viewerState.index=nextIndex;
      setText(counter,`${nextIndex+1} / ${currentSeq.length}`);
      prevBtn.hidden=prevBtn.disabled=nextIndex<=0;
      nextBtn.hidden=nextBtn.disabled=nextIndex>=currentSeq.length-1;
      frame.replaceChildren();
      const picture=node('img',null,'ml-viewer-img');picture.src=item.content_url;bindAttribute(picture,'alt',item.name);
      picture.addEventListener('error',()=>{currentImg=null;picture.remove();frame.append(node('span',msg('ui.preview_is_currently_unavailable'),'ml-preview-failed'));});
      frame.append(picture);
      viewerZoom.bindImage(picture,item.width,item.height);
      setText(title,item.name);
      const subParts=[item.project_name,item.episode_name,item.created_at?toYMD(new Date(Date.parse(item.created_at))):null].filter(Boolean);
      setText(sub,subParts.join(' · '));
      loadDetailInto(s,item,{body:detailBody,actionsSlot:detailActions});
    }
    function stepImage(delta){if(s.viewer===viewerState)showAt(viewerState.index+delta);}
    if(typeof window!=='undefined'){
      viewerState.keyOff=listen(s,window,'keydown',event=>{
        if(s.viewer!==viewerState)return;
        if(event.key==='ArrowLeft')stepImage(-1);
        else if(event.key==='ArrowRight')stepImage(1);
        else if(event.key==='+'||event.key==='='){event.preventDefault?.();viewerZoom.zoomIn();}
        else if(event.key==='-'||event.key==='_'){event.preventDefault?.();viewerZoom.zoomOut();}
        else if(event.key==='0'){event.preventDefault?.();viewerZoom.reset();}
        else if(event.key==='Escape'){event.preventDefault?.();closeViewer(s,true);}
      });
    }
    dialog.addEventListener('close',()=>{if(s.viewer===viewerState)closeViewer(s,true);});
    dialog.addEventListener('click',event=>{if(event.target===dialog)closeViewer(s,true);});
    dialog.showModal?.();showAt(startIndex);closeBtn.focus?.();
  }
  function openAvViewer(s,row,opener){
    closeDatePopover(s,false);closeViewer(s,false);
    const dialog=node('dialog',null,'ml-av-dialog');bindAttribute(dialog,'aria-label',label('av_viewer'));
    const layout=node('div',null,'ml-viewer-layout'),stage=node('div',null,'ml-viewer-stage');
    const closeBtn=button('×',()=>closeViewer(s,true),'ml-viewer-close');bindAttribute(closeBtn,'aria-label',msg('common.close'));
    let sidebarOpen=true;
    const sidebar=node('aside',null,'ml-viewer-sidebar');
    const foldBtn=button('▤',()=>{sidebarOpen=!sidebarOpen;sidebar.hidden=!sidebarOpen;foldBtn.setAttribute('aria-expanded',String(sidebarOpen));},'ml-viewer-fold');
    bindAttribute(foldBtn,'aria-label',label('toggle_sidebar'));foldBtn.setAttribute('aria-expanded','true');
    const frame=node('div',null,'ml-viewer-frame');
    let player=null;
    if(row.modality==='video'||row.modality==='audio'){
      player=node(row.modality==='video'?'video':'audio',null,'ml-av-player');
      player.controls=true;player.preload='metadata';player.src=row.content_url;
      if(row.modality==='video'&&row.poster_url)player.poster=row.poster_url;
      frame.append(player);
    }
    stage.append(closeBtn,foldBtn,frame);
    const sideScroll=node('div',null,'ml-detail-scroll'),title=node('h2',row.name,'ml-detail-title');
    const subParts=[row.project_name,row.episode_name,row.created_at?toYMD(new Date(Date.parse(row.created_at))):null].filter(Boolean);
    const sub=node('p',subParts.join(' · '),'ml-detail-sub');
    const detailBody=node('div',null,'ml-detail-body'),detailActions=node('footer',null,'ml-detail-actions');
    sideScroll.append(title,sub,detailBody);sidebar.append(sideScroll,detailActions);
    layout.append(stage,sidebar);dialog.append(layout);document.body.append(dialog);
    const viewerState={kind:'av',dialog,opener,row,keyOff:null,visOff:null};
    s.viewer=viewerState;
    if(typeof window!=='undefined'){
      viewerState.keyOff=listen(s,window,'keydown',event=>{if(s.viewer===viewerState&&event.key==='Escape'){event.preventDefault?.();closeViewer(s,true);}});
    }
    if(typeof document!=='undefined'&&player){
      viewerState.visOff=listen(s,document,'visibilitychange',()=>{if(s.viewer===viewerState&&document.hidden)try{player.pause?.();}catch{}});
    }
    dialog.addEventListener('close',()=>{if(s.viewer===viewerState)closeViewer(s,true);});
    dialog.addEventListener('click',event=>{if(event.target===dialog)closeViewer(s,true);});
    dialog.showModal?.();loadDetailInto(s,row,{body:detailBody,actionsSlot:detailActions});closeBtn.focus?.();
  }
  function openMediaItem(s,row,opener){
    if(!live(s))return;
    if(row.modality==='image')openImageViewer(s,row,opener);
    else openAvViewer(s,row,opener);
  }
  async function load({projectId=null,episodeId=null,category=''}={}){
    suspend();
    const s={
      epoch,identity:identity(session()),
      filters:{project_id:projectId||'',episode_id:projectId&&episodeId||'',category:CATEGORY_SET.has(category)?category:'',startDate:'',endDate:''},
      rows:[],projects:[],next:null,total:0,loaded:false,loading:false,loadingMore:false,listError:null,
      listTicket:0,projectsTicket:0,episodeTicket:0,detailTicket:0,
      listController:null,projectsController:null,episodeController:null,detailController:null,
      controllers:new Set(),cleanups:new Set(),
      dateOpen:false,draftStart:null,viewYear:2026,viewMonth:0,dateOutsideOff:null,dateKeyOff:null,
      viewer:null,navigating:false,
    };
    active=s;
    root.classList.add('ml-library');root.replaceChildren();
    s.totalLabel=node('span',null,'ml-total');
    if(ctx.toolbarSlot){ctx.toolbarSlot.replaceChildren(s.totalLabel);}
    else{const toolbar=node('div',null,'ml-toolbar');toolbar.append(s.totalLabel);root.append(toolbar);}
    const filters=node('div',null,'ml-filters');
    s.project=node('select',null,'ml-filter-project');bindAttribute(s.project,'aria-label',msg('replica.media_project'));
    s.project.append(localizedOption('',msg('novel-parser.all_projects')));
    s.episode=node('select',null,'ml-filter-episode');bindAttribute(s.episode,'aria-label',msg('replica.media_episode'));
    s.episode.append(localizedOption('',msg('replica.all_episodes')));s.episode.disabled=true;
    s.category=node('select',null,'ml-filter-category');bindAttribute(s.category,'aria-label',msg('replica.media_type'));
    s.category.append(localizedOption('',label('all_types')));
    for(const cat of CATEGORIES)s.category.append(localizedOption(cat,label('category_'+cat)));
    s.category.value=s.filters.category;
    s.dateWrap=node('div',null,'ml-date-wrap');
    s.dateTrigger=button(null,()=>s.dateOpen?closeDatePopover(s,true):openDatePopover(s),'ml-date-trigger');
    bindAttribute(s.dateTrigger,'aria-label',label('date_range'));s.dateTrigger.setAttribute('aria-haspopup','dialog');
    s.dateStartText=node('span',null,'ml-date-value');
    const sep=node('span',label('to'),'ml-date-sep');
    s.dateEndText=node('span',null,'ml-date-value');
    const calIcon=node('span',null,'ml-date-icon');calIcon.setAttribute('aria-hidden','true');
    calIcon.innerHTML='<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2.5" y="3.5" width="13" height="12" rx="2"/><path d="M6 2v3M12 2v3M2.5 7.5h13"/></svg>';
    s.dateTrigger.append(s.dateStartText,sep,s.dateEndText,calIcon);
    s.dateClear=button('×',event=>clearDateRange(s,event),'ml-date-clear');bindAttribute(s.dateClear,'aria-label',label('clear_date'));
    s.datePopover=node('div',null,'ml-date-popover');s.datePopover.setAttribute('role','dialog');bindAttribute(s.datePopover,'aria-label',label('date_range'));s.datePopover.hidden=true;
    const shortcuts=node('div',null,'ml-date-shortcuts');
    for(const kind of SHORTCUTS){const btn=button(label('shortcut_'+kind),()=>applyShortcut(s,kind),'ml-shortcut');btn.dataset.shortcut=kind;shortcuts.append(btn);}
    s.datePanels=node('div',null,'ml-date-panels');
    s.datePopover.append(shortcuts,s.datePanels);
    s.dateWrap.append(s.dateTrigger,s.dateClear,s.datePopover);
    renderDateTrigger(s);
    filters.append(s.project,s.episode,s.category,s.dateWrap);
    s.status=node('p',null,'ml-status');s.status.setAttribute('role','status');
    s.projectRetry=button(msg('ui.reload'),()=>{s.projectRetry.hidden=true;return loadProjects(s);},'ml-project-retry');s.projectRetry.hidden=true;
    s.episodeRetry=button(msg('ui.reload'),()=>{s.episodeRetry.hidden=true;return loadEpisodes(s,s.filters.project_id,s.filters.episode_id);},'ml-episode-retry');s.episodeRetry.hidden=true;
    s.grid=node('div',null,'ml-grid');s.footer=node('div',null,'ml-footer');
    root.append(filters,s.status,s.projectRetry,s.episodeRetry,s.grid,s.footer);
    s.project.addEventListener('change',()=>changeProject(s));
    s.episode.addEventListener('change',()=>{if(!live(s))return;s.filters.episode_id=s.episode.value;readList(s);});
    s.category.addEventListener('change',()=>{if(!live(s))return;s.filters.category=s.category.value;readList(s);});
    s.cleanups.add(onLocaleChange(()=>{if(live(s)){renderDateTrigger(s);if(s.dateOpen)paintDatePopover(s);}}));
    if(typeof IntersectionObserver!=='undefined'){
      s.observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&live(s)&&!s.listError)readList(s,true);},{rootMargin:'160px'});
      s.observer.observe(s.footer);
    }
    await Promise.all([loadProjects(s),readList(s),projectId?loadEpisodes(s,projectId,episodeId||''):Promise.resolve()]);
    return live(s);
  }
  function suspend(){
    if(active){
      const s=active;active=null;
      s.observer?.disconnect?.();
      closeDatePopover(s,false);
      closeViewer(s,false);
      for(const c of [...s.controllers])c.abort();
      s.controllers.clear();
      for(const fn of [...s.cleanups])fn();
      s.cleanups.clear();
      cleanupMediaTree(root);
      s.totalLabel?.remove?.();
    }
    epoch++;
  }
  return {
    load,
    reload:()=>active?readList(active,false):Promise.resolve(false),
    loadMore:()=>active?readList(active,true):Promise.resolve(false),
    suspend,
  };
}
function containsNode(parent,target){
  for(let cur=target;cur;cur=cur.parentElement)if(cur===parent)return true;
  return false;
}
