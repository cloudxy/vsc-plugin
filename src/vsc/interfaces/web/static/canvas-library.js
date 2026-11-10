import {msg,joinMessages,setText,bindAttribute,option as localizedOption,translate} from './i18n.js';

// Shared full-page/embedded catalogue. Existing canvas versions and project
// commands remain authoritative; this module never manufactures capabilities.
const key=name=>'canvas.library.'+name;
const label=(name,values)=>msg(key(name),values);
const node=(tag,text,className)=>{const value=document.createElement(tag);if(text!=null)setText(value,text);if(className)value.className=className;return value;};
const button=(text,run,className='')=>{const value=node('button',text,className);value.type='button';value.addEventListener('click',run);return value;};
const path=(project,suffix)=>'/api/v1/projects/'+encodeURIComponent(project)+'/'+suffix;
const identity=session=>JSON.stringify([session.actor??null,session.identityId??null,session.workspaceId??null]);
const pendingKey=session=>'vsc-canvas-library:v1:'+identity(session);
const readStorage=key=>{const raw=sessionStorage.getItem(key);return raw?JSON.parse(raw):null;};
export function readCanvasLibraryPending(session,project){const record=readStorage(pendingKey(session));return record?.identity===identity(session)&&record.project===project?record:null;}
const copy=value=>JSON.parse(JSON.stringify(value));
const editable=project=>project.permissions?.can_edit===true;
const cleanDocument=value=>({viewport:value.viewport,nodes:value.nodes.map(({preview_url,...item})=>item),edges:value.edges});
const ICONS={rename:'<path d="m3 12 9-9 3 3-9 9-4 1Z M10 5l3 3"/>',copy:'<path d="M6 3h7l3 3v10H6Z M10 3v4h6 M3 6v12h10"/>',cross:'<rect x="2" y="2" width="10" height="10" rx="1"/><rect x="6" y="6" width="10" height="10" rx="1"/><path d="M8 11h6 M11 8v6"/>',trash:'<path d="M2 4h14 M6 4V2h6v2 M4 4l1 12h8l1-12 M7 7v6 M11 7v6"/>'};
function iconButton(name,title,run){const value=button(null,run,'cl-icon-action');bindAttribute(value,'aria-label',title);bindAttribute(value,'title',title);value.innerHTML='<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">'+ICONS[name]+'</svg>';return value;}

/** ctx.projects({isCurrent}): [{id,name,permissions:{can_edit}}] or {items,creators};
 * ctx.episodes(projectId,{isCurrent}): [{id,title}] or {items,revision}.
 * ctx.session(): actor, identityId, workspaceId, csrf, writeAvailable.
 * navigate(page,null,project,{episode,task_target}) resolves after opening.
 * No collaboration/direct-copy request is sent before a later real contract.
 */
export function createCanvasLibrary(root,ctx){
  let epoch=0,active=null;
  const session=()=>ctx.session();
  const live=s=>active===s&&s.epoch===epoch&&s.identity===identity(session());
  const store=(key,value)=>{try{if(value==null)sessionStorage.removeItem(key);else sessionStorage.setItem(key,JSON.stringify(value));}catch{throw new Error(translate(label('storage_error')));}};
  const ownsPending=(s,record)=>{const current=readStorage(s.pendingKey),requestKey=record.request?.body?.idempotency_key;return Boolean(current&&requestKey&&current.identity===record.identity&&current.project===record.project&&current.owner===record.owner&&current.request?.body?.idempotency_key===requestKey);};
  const updatePending=(s,record,value)=>{if(!ownsPending(s,record))return false;store(s.pendingKey,value);return true;};
  const canWrite=s=>live(s)&&Boolean(session().actor)&&session().writeAvailable===true&&!s.storageError;
  const report=(s,error)=>{if(live(s)){setText(s.status,error?.message??error);ctx.notice?.(error?.message??String(error));}};
  function pending(s){try{return readStorage(s.pendingKey);}catch{if(live(s)){s.storageError=true;setText(s.status,label('storage_error'));}return null;}}
  function guard(s){if(!live(s))throw new Error(translate(label('scope_changed')));}
  function validatePage(value,start){
    if(!value||!Array.isArray(value.items)||!Number.isInteger(value.total)||value.total<0||
      !(value.next_offset===null||Number.isInteger(value.next_offset)&&value.next_offset>start)||
      value.items.some(row=>!row.id||!row.project_id||typeof row.title!=='string'||row.permissions?.can_read!==true))throw new Error(translate(label('invalid_response')));
  }
  function refreshRecovery(s){if(!live(s))return;const record=pending(s);s.recovery.replaceChildren();if(record){const restore=button(msg('ui.recover_original_operation_receipt'),()=>perform(s,null,()=>live(s)).catch(error=>report(s,error)),'cl-recovery-button');restore.disabled=s.mutating;s.recovery.append(node('span',record.title||record.row?.title||''),restore);}s.create.disabled=!canWrite(s)||s.mutating||Boolean(record)||!s.projects.some(editable);}
  async function readList(s,append=false){
    if(!live(s)||append&&(s.loading||s.loadingMore||s.next===null))return false;
    const start=append?s.next:0,ticket=++s.listTicket,filters={...s.filters};
    if(!append){s.rows=[];s.total=0;s.next=null;s.loading=true;s.listError=null;paint(s);}else{s.loadingMore=true;s.listError=null;paintFooter(s);}
    const params=new URLSearchParams({creator_filter:filters.creator_filter,permission:filters.permission,order:filters.order,query:filters.query,offset:String(start),limit:'30'});
    for(const name of ['project_id','episode_id','creator_id'])if(filters[name])params.set(name,filters[name]);
    try{const value=await ctx.api('/api/v1/canvas-library?'+params);if(!live(s)||ticket!==s.listTicket)return false;validatePage(value,start);
      const seen=new Set(append?s.rows.map(row=>row.project_id+':'+row.id):[]);s.rows=append?[...s.rows]:[];for(const row of value.items){const id=row.project_id+':'+row.id;if(!seen.has(id)){s.rows.push(row);seen.add(id);}}
      s.total=value.total;s.next=value.next_offset;s.capabilities=value.capabilities||{};s.listError=null;s.loaded=true;paint(s);return true;
    }catch(error){if(live(s)&&ticket===s.listTicket){if(!append){s.rows=[];s.total=0;s.next=null;}s.listError={error,append,start};paint(s);}return false;}
    finally{if(live(s)&&ticket===s.listTicket){s.loading=false;s.loadingMore=false;s.grid.removeAttribute('aria-busy');paint(s);}}
  }
  function paintCreators(s){const value=s.creator.value;s.creator.replaceChildren(localizedOption('mine',msg('replica.created_by_me')),localizedOption('all',label('all_creators')));for(const person of s.creators)s.creator.append(localizedOption('member:'+person.id,person.name));s.creator.value=value||'mine';}
  function paintFooter(s){if(!live(s))return;s.footer.replaceChildren();if(s.loading||s.loadingMore)s.footer.append(node('p',msg('ui.loading')));
    else if(s.listError){s.footer.append(node('p',s.listError.error.message,'cl-error'),button(msg('ui.reload'),()=>readList(s,s.listError.append),'cl-retry'));}
    else if(s.next!==null)s.footer.append(button(label('load_more'),()=>readList(s,true),'cl-load-more'));
    else if(s.loaded&&s.rows.length)s.footer.append(node('p',label('no_more')));
  }
  function paint(s){if(!live(s))return;s.grid.replaceChildren();setText(s.totalLabel,label('total',{count:s.total}));s.grid.setAttribute('aria-busy',String(s.loading||s.loadingMore));
    for(const row of s.rows){
      const tile=node('article',null,'cl-card');tile.dataset.canvasId=row.id;tile.dataset.projectId=row.project_id;
      const cover=node('div',null,'cl-cover'),open=button(null,async()=>{if(s.opening||s.mutating||!live(s))return;s.opening=true;open.disabled=true;try{await ctx.navigate('creative-canvas',null,row.project_id,{task_target:row.id,...(row.episode_id?{episode:row.episode_id}:{})});if(live(s))await ctx.onOpened?.(row);}catch(error){report(s,error);}finally{if(live(s)){s.opening=false;open.disabled=false;}}},'cl-open');bindAttribute(open,'aria-label',msg('ui.open_value0',{value0:row.title}));
      if(row.cover_url){const image=node('img');image.src=row.cover_url;image.loading='lazy';bindAttribute(image,'alt','');image.addEventListener('error',()=>{image.remove();open.append(node('span',msg('ui.preview_is_currently_unavailable'),'cl-preview-failed'));});open.append(image);}else{const placeholder=node('span','▣','cl-placeholder');placeholder.setAttribute('aria-hidden','true');open.append(placeholder);}cover.append(open);
      if(row.permissions.can_manage_collaboration&&typeof row.collaboration_enabled==='boolean'){const toggle=button(null,()=>{},'cl-collaboration-switch');toggle.setAttribute('role','switch');toggle.setAttribute('aria-checked',String(row.collaboration_enabled===true));toggle.disabled=true;bindAttribute(toggle,'aria-label',label('collaboration'));bindAttribute(toggle,'title',label('collaboration_unavailable'));cover.append(toggle);}
      const actions=node('div',null,'cl-card-actions');for(const [action,permission,title] of [['rename','can_rename',msg('common.rename')],['copy','can_copy',msg('replica.create_canvas_copy')],['cross','can_copy',msg('ui.copy_to_other_episodes')],['trash','can_delete',msg('ui.delete')]]){
        if(!row.permissions[permission])continue;const control=iconButton(action,title,()=>openAction(s,action,row));control.disabled=action==='cross'||s.mutating||!canWrite(s)||Boolean(pending(s));if(action==='cross')bindAttribute(control,'title',label('cross_copy_unavailable'));actions.append(control);
      }cover.append(actions);const title=node('h3',row.title);bindAttribute(title,'title',[row.title,row.project_name,row.episode_name,row.creator_name].filter(Boolean).join(' / '));tile.append(cover,title,node('p',row.creator_name||'','cl-creator'));s.grid.append(tile);
    }
    if(s.loaded&&!s.loading&&!s.rows.length&&!s.listError)s.grid.append(node('p',msg('replica.no_matching_canvases'),'cl-empty'));paintFooter(s);refreshRecovery(s);
  }
  async function loadProjects(s){const ticket=++s.projectsTicket;try{const value=await ctx.projects({isCurrent:()=>live(s)&&ticket===s.projectsTicket});if(!live(s)||ticket!==s.projectsTicket)return;const rows=Array.isArray(value)?value:value?.items;if(!Array.isArray(rows))throw new Error(translate(label('invalid_response')));s.projects=rows;if(Array.isArray(value.creators)){s.creators=value.creators;paintCreators(s);}
      s.project.replaceChildren(localizedOption('',msg('novel-parser.all_projects')));for(const row of rows)s.project.append(localizedOption(row.id,row.name));s.project.value=s.filters.project_id;refreshRecovery(s);
    }catch(error){if(live(s)&&ticket===s.projectsTicket){report(s,error);s.projectRetry.hidden=false;}}}
  async function loadEpisodes(s,select,projectId,selected='',scopeCurrent=()=>live(s)){
    select.disabled=true;select.replaceChildren(localizedOption('',msg('replica.all_episodes')));if(!projectId)return [];
    const value=await ctx.episodes(projectId,{isCurrent:scopeCurrent});if(!scopeCurrent())return null;const rows=Array.isArray(value)?value:value?.items;if(!Array.isArray(rows))throw new Error(translate(label('invalid_response')));for(const row of rows)select.append(localizedOption(row.id,row.title||row.name||row.display_code));select.value=rows.some(row=>row.id===selected)?selected:'';select.disabled=false;return rows;
  }
  function applyFilters(s){clearTimeout(s.searchTimer);s.filters.query=s.search.value.trim();return readList(s);}
  async function changeProject(s){if(!live(s))return;s.filters.project_id=s.project.value;s.filters.episode_id='';s.episode.value='';clearTimeout(s.searchTimer);const ticket=++s.episodeTicket,p=s.filters.project_id;s.episodeRetry.hidden=true;applyFilters(s);
    try{await loadEpisodes(s,s.episode,p,'',()=>live(s)&&ticket===s.episodeTicket&&p===s.filters.project_id);}catch(error){if(live(s)&&ticket===s.episodeTicket){report(s,error);s.episodeRetry.hidden=false;}}
  }
  function dialog(s,title){const d=node('dialog',null,'cl-action-dialog'),form=node('form'),head=node('header'),heading=node('h2',title),close=button('×',()=>d.close(),'cl-close');bindAttribute(d,'aria-label',title);bindAttribute(close,'aria-label',msg('common.close'));head.append(heading,close);form.append(head);d.append(form);root.append(d);s.dialogs.add(d);const opener=document.activeElement;let closed=false;d.addEventListener('close',()=>{closed=true;s.dialogs.delete(d);d.remove();if(live(s))opener?.focus();});return {d,form,current:()=>live(s)&&!closed};}
  function field(parent,title,input){const wrap=node('label',null,'cl-field');wrap.append(node('span',title),input);bindAttribute(input,'aria-label',title);parent.append(wrap);return wrap;}
  function actionFooter(form){const status=node('p',null,'cl-form-status');status.setAttribute('role','status');const footer=node('footer'),cancel=button(msg('common.cancel'),()=>form.parentElement.close()),save=node('button',msg('common.confirm'),'cl-confirm');save.type='submit';footer.append(cancel,save);form.append(status,footer);return {status,save,cancel};}
  async function openCreate(){const s=active;if(!s||!canWrite(s)||s.mutating)return;if(pending(s)){refreshRecovery(s);return;}
    const view=dialog(s,label('create')),body=node('div',null,'cl-form-body'),project=node('select'),episode=node('select'),name=node('input');view.form.append(body);project.append(localizedOption('',label('select_project')));for(const row of s.projects.filter(editable))project.append(localizedOption(row.id,row.name));episode.append(localizedOption('',label('select_episode')));episode.disabled=true;name.maxLength=100;name.required=true;const draftKey=s.pendingKey+':create-draft';let draft=null;try{draft=readStorage(draftKey);}catch{}
    project.value=draft?.project_id||s.filters.project_id||'';if(!s.projects.some(row=>row.id===project.value&&editable(row)))project.value='';name.value=draft?.title||'';
    field(body,msg('replica.media_project'),project);field(body,msg('replica.media_episode'),episode);const nameField=field(body,msg('ui.canvas_name'),name),counter=node('span',null,'cl-name-count');nameField.append(counter);
    const collaboration=node('div',null,'cl-collaboration'),toggle=node('input');toggle.type='checkbox';toggle.disabled=true;bindAttribute(toggle,'aria-label',label('collaboration'));collaboration.append(node('span',label('collaboration')),toggle,node('p',label('collaboration_unavailable')));body.append(collaboration);
    const {status,save}=actionFooter(view.form);let reading=false,submitting=false,episodeTicket=0,episodes=[],episodeError=false;
    const lock=()=>{if(!view.current())return;const record=pending(s),fixed=Boolean(record)||submitting;project.disabled=name.disabled=fixed;episode.disabled=fixed||reading||!project.value;save.disabled=fixed||reading||!project.value||!episode.value||!episodes.some(row=>row.id===episode.value)||!name.value.trim()||[...name.value.trim()].length>100;setText(counter,`${[...name.value].length} / 100`);};
    const retain=()=>{if(view.current()&&!pending(s))try{store(draftKey,{project_id:project.value,episode_id:episode.value,title:name.value});}catch(error){setText(status,error.message);}};
    async function readEpisodes(selected=''){const ticket=++episodeTicket,p=project.value;reading=true;episodeError=false;episodes=[];episode.value='';lock();try{const result=await loadEpisodes(s,episode,p,selected,()=>view.current()&&ticket===episodeTicket&&project.value===p);if(result){episodes=result;setText(status,'');}}catch(error){if(view.current()&&ticket===episodeTicket){episodeError=true;setText(status,error.message);status.append(button(msg('ui.reload'),()=>readEpisodes(selected),'cl-episode-retry'));}}finally{if(view.current()&&ticket===episodeTicket){reading=false;lock();}}}
    project.addEventListener('change',()=>{retain();return readEpisodes();});for(const control of [name,episode])control.addEventListener('input',()=>{retain();lock();});episode.addEventListener('change',()=>{retain();lock();});
    view.form.addEventListener('submit',async event=>{event.preventDefault();if(submitting||reading||episodeError||!view.current())return;submitting=true;lock();try{const p=project.value,e=episode.value,title=name.value.trim();if(!s.projects.some(row=>row.id===p&&editable(row)))throw new Error(translate(label('no_create_permission')));if(!e||!episodes.some(row=>row.id===e))throw new Error(translate(label('choose_target')));if(!title||[...title].length>100)throw new Error(translate(msg('replica.canvas_name_limit')));
        const completed=await perform(s,async()=>{const baseline=await ctx.api(path(p,'creative-canvases?episode_id='+encodeURIComponent(e)));if(!Array.isArray(baseline.items)||!Number.isInteger(baseline.revision))throw new Error(translate(label('invalid_response')));return {action:'create',project:p,title,draftKey,request:{path:path(p,'creative-canvases'),method:'POST',body:{payload:{title,episode_id:e,document:{nodes:[],edges:[]}},expected_revision:baseline.revision,idempotency_key:crypto.randomUUID()}}};},view.current);
        if(completed&&view.current())view.d.close();
      }catch(error){if(view.current())setText(status,joinMessages([error.message,' ',pending(s)?.result?label('readback_pending'):pending(s)?msg('ui.the_previous_receipt_is_unconfirmed_retrying_will_recover_the'):'']));}
      finally{if(view.current()){submitting=false;lock();if(pending(s)){save.disabled=false;}}}
    });
    // A retained request is recovered via the catalogue banner; closing never discards it.
    view.d.addEventListener('close',retain);view.d.showModal();lock();await readEpisodes(draft?.episode_id||s.filters.episode_id||'');if(view.current())name.focus();return view.d;
  }
  async function openAction(s,action,row){if(!live(s)||s.mutating||!canWrite(s)||action==='cross')return;if(pending(s)){refreshRecovery(s);return;}const titles={rename:msg('common.rename'),copy:msg('replica.create_canvas_copy'),trash:msg('ui.delete')};const view=dialog(s,titles[action]),name=action==='rename'?node('input'):null;
    if(name){name.value=row.title;name.maxLength=100;name.required=true;field(view.form,msg('ui.canvas_name'),name);}else view.form.append(node('p',label(action==='copy'?'copy_confirm':'trash_confirm',{name:row.title})));
    const {status,save}=actionFooter(view.form);let submitting=false;
    view.form.addEventListener('submit',async event=>{event.preventDefault();if(submitting||!view.current())return;submitting=true;save.disabled=true;if(name)name.disabled=true;try{const title=name?.value.trim();if(name&&(!title||[...title].length>100))throw new Error(translate(msg('replica.canvas_name_limit')));
        const completed=await perform(s,async()=>{const fixed=await ctx.api(path(row.project_id,'creative-canvases/'+encodeURIComponent(row.id)));if(fixed.id!==row.id||fixed.project_id&&fixed.project_id!==row.project_id||fixed.episode_id!==undefined&&fixed.episode_id!==row.episode_id||!Number.isInteger(fixed.revision)||!Number.isInteger(fixed.canvas_revision))throw new Error(translate(label('invalid_response')));
          let endpoint=path(row.project_id,'creative-canvases/'+encodeURIComponent(row.id)),method='POST',payload;
          if(action==='rename'){if(!fixed.document||!Array.isArray(fixed.document.nodes)||!Array.isArray(fixed.document.edges))throw new Error(translate(label('invalid_response')));method='PUT';payload={canvas_revision:fixed.canvas_revision,title,document:cleanDocument(fixed.document)};}
          else if(action==='copy'){endpoint+='/copy';payload={canvas_revision:fixed.canvas_revision,title:[...fixed.title].slice(0,95).join('')+' Copy'};}
          else{endpoint=path(row.project_id,'management');payload={operation:'trash',target_type:'canvas',target_id:row.id,reason:translate(label('trash_confirm',{name:fixed.title}))};}
          return {action,row,project:row.project_id,title:title||row.title,request:{path:endpoint,method,body:{payload,expected_revision:fixed.revision,idempotency_key:crypto.randomUUID()}}};},view.current);
        if(completed&&view.current())view.d.close();
      }catch(error){if(view.current())setText(status,joinMessages([error.message,' ',pending(s)?.result?label('readback_pending'):pending(s)?msg('ui.the_previous_receipt_is_unconfirmed_retrying_will_recover_the'):'']));}
      finally{if(view.current()){submitting=false;save.disabled=false;if(name)name.disabled=Boolean(pending(s));}}
    });view.d.showModal();name?.focus();return view.d;
  }
  function checkedResult(record,result){if(!result||!Number.isInteger(result.revision)||result.project_id&&result.project_id!==record.project||record.action!=='trash'&&!result.id)throw new Error(translate(label('invalid_response')));return result;}
  async function perform(s,build,isCurrent){
    if(!canWrite(s)||s.mutating)return;s.mutating=true;refreshRecovery(s);let record=pending(s),retrying=Boolean(record);
    try{if(!record){if(!build)return;record=await build();if(!isCurrent())return;if(readStorage(s.pendingKey))throw new Error(translate(msg('replica.resume_canvas_first')));record.identity=s.identity;record.owner=crypto.randomUUID();store(s.pendingKey,record);}
      else{if(record.identity!==s.identity)throw new Error(translate(label('scope_changed')));const claimed={...record,owner:crypto.randomUUID()};if(!updatePending(s,record,claimed))return;record=claimed;}
      // Each recovery claims this request without changing its idempotency key.
      // An older mount may retain its own late result only while it still owns it.
      if(!record.result){if(retrying){const receipt=await ctx.api(path(record.project,'operation-receipts/'+encodeURIComponent(record.request.body.idempotency_key)));if(!ownsPending(s,record))return;if(receipt.found===true){record.result=checkedResult(record,receipt.response);if(!updatePending(s,record,record))return;}else if(receipt.found!==false)throw new Error(translate(label('invalid_response')));if(!isCurrent())return;}
        if(!record.result){let result;try{result=await ctx.api(record.request.path,{method:record.request.method,headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(record.request.body)});}catch(error){if(!retrying&&[400,404,409,422].includes(error.status))updatePending(s,record,null);throw error;}
          if(!ownsPending(s,record))return;record.result=checkedResult(record,result);if(!updatePending(s,record,record)||!isCurrent())return;}
      }
      if(!ownsPending(s,record))return;checkedResult(record,record.result);
      if(record.result.status==='protected'){if(!updatePending(s,record,null))return;throw new Error((record.result.reasons||[]).map(item=>item.message).join('；'));}
      if(!isCurrent())return;ctx.setRevision?.(record.result.revision,record.project);if(!await readList(s))throw new Error(translate(label('readback_pending')));if(!isCurrent()||!updatePending(s,record,null))return;
      if(record.draftKey)store(record.draftKey,null);ctx.notice?.(translate(label(record.action==='trash'?'trashed':'saved')));return true;
    }finally{if(live(s)){s.mutating=false;paint(s);}}
  }
  async function load({embedded=false,projectId=null,episodeId=null}={}){
    suspend();const s={epoch,identity:identity(session()),filters:{project_id:projectId||'',episode_id:projectId&&episodeId||'',creator_filter:'mine',creator_id:'',permission:'all',order:'updated_desc',query:''},rows:[],projects:[],creators:[],next:null,total:0,loaded:false,loading:false,loadingMore:false,listTicket:0,episodeTicket:0,projectsTicket:0,dialogs:new Set(),mutating:false,opening:false,pendingKey:pendingKey(session()),capabilities:{}};active=s;
    root.classList.add('cl-library');root.classList.toggle('cl-embedded',embedded);root.replaceChildren();
    const toolbar=node('div',null,'cl-toolbar');s.totalLabel=node('span',null,'cl-total');s.search=node('input');s.search.type='search';bindAttribute(s.search,'aria-label',label('search'));bindAttribute(s.search,'placeholder',label('search'));s.create=button(joinMessages(['＋ ',label('create')]),openCreate,'cl-create');toolbar.append(s.totalLabel,s.search,s.create);
    const filters=node('div',null,'cl-filters');s.project=node('select');s.episode=node('select');s.creator=node('select');s.permission=node('select');s.order=node('select');for(const [control,title] of [[s.project,msg('replica.media_project')],[s.episode,msg('replica.media_episode')],[s.creator,label('creators')],[s.permission,label('permissions')],[s.order,msg('ui.canvas_order')]])bindAttribute(control,'aria-label',title);
    s.project.append(localizedOption('',msg('novel-parser.all_projects')));s.episode.append(localizedOption('',msg('replica.all_episodes')));s.episode.disabled=true;paintCreators(s);for(const value of ['all','edit','view'])s.permission.append(localizedOption(value,label('permission_'+value)));for(const value of ['updated_desc','updated_asc'])s.order.append(localizedOption(value,label(value)));filters.append(s.project,s.episode,s.creator,s.permission,s.order);
    s.status=node('p',null,'cl-status');s.status.setAttribute('role','status');s.recovery=node('div',null,'cl-recovery');s.grid=node('div',null,'cl-grid');s.footer=node('div',null,'cl-footer');s.projectRetry=button(msg('ui.reload'),async()=>{s.projectRetry.hidden=true;await loadProjects(s);});s.episodeRetry=button(msg('ui.reload'),()=>{s.episodeRetry.hidden=true;return changeProject(s);});s.projectRetry.hidden=s.episodeRetry.hidden=true;root.append(toolbar,filters,s.status,s.projectRetry,s.episodeRetry,s.recovery,s.grid,s.footer);
    s.search.addEventListener('input',()=>{clearTimeout(s.searchTimer);s.searchTimer=setTimeout(()=>{if(live(s)){s.filters.query=s.search.value.trim();readList(s);}},300);});s.project.addEventListener('change',()=>changeProject(s));s.episode.addEventListener('change',()=>{s.filters.episode_id=s.episode.value;applyFilters(s);});s.creator.addEventListener('change',()=>{const value=s.creator.value;s.filters.creator_filter=value.startsWith('member:')?'member':value;s.filters.creator_id=value.startsWith('member:')?value.slice(7):'';applyFilters(s);});s.permission.addEventListener('change',()=>{s.filters.permission=s.permission.value;applyFilters(s);});s.order.addEventListener('change',()=>{s.filters.order=s.order.value;applyFilters(s);});
    if(typeof IntersectionObserver!=='undefined'){s.observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)&&live(s)&&!s.listError)readList(s,true);},{root:embedded?root:null,rootMargin:'160px'});s.observer.observe(s.footer);}
    const initialEpisode=async()=>{if(!projectId)return;const ticket=++s.episodeTicket;try{await loadEpisodes(s,s.episode,projectId,episodeId||'',()=>live(s)&&ticket===s.episodeTicket);}catch(error){if(live(s)){report(s,error);s.episodeRetry.hidden=false;}}};
    await Promise.all([loadProjects(s),readList(s),initialEpisode()]);return live(s);
  }
  function suspend(){if(active){clearTimeout(active.searchTimer);active.observer?.disconnect();for(const d of [...active.dialogs])d.close();}epoch++;active=null;}
  return {load,reload:()=>active?readList(active):Promise.resolve(false),loadMore:()=>active?readList(active,true):Promise.resolve(false),openCreate,suspend};
}

export async function openCanvasLibraryDialog(ctx,{projectId=null,episodeId=null,opener=document.activeElement}={}){
  const dialog=node('dialog',null,'cl-management-dialog'),header=node('header'),close=button('×',()=>dialog.close(),'cl-close'),content=node('div');bindAttribute(dialog,'aria-label',msg('replica.canvas_management'));bindAttribute(close,'aria-label',msg('common.close'));header.append(node('h2',msg('replica.canvas_management')),close);dialog.append(header,content);document.body.append(dialog);
  const library=createCanvasLibrary(content,{...ctx,onOpened:async row=>{await ctx.onOpened?.(row);dialog.close();}});let closed=false,resolveClosed;const whenClosed=new Promise(resolve=>{resolveClosed=resolve;}),handle={library,close:()=>{if(!closed)dialog.close();},whenClosed};
  dialog.addEventListener('close',()=>{if(closed)return;closed=true;library.suspend();dialog.remove();opener?.focus();resolveClosed();});dialog.showModal();try{ctx.onDialogReady?.(handle);if(!closed)await library.load({embedded:true,projectId,episodeId});return handle;}catch(error){handle.close();throw error;}
}
