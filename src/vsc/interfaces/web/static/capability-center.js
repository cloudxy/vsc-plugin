import {msg,setText,bindAttribute,translate} from './i18n.js';
import {scopedProjects} from './project-scope.js';

// Discovery is read-only. Original consumers retain project and execution authority.
export const STAGES=[['adapt','创意与改编'],['script','剧本'],['direct','分镜与运镜'],['assets','资产与连续性'],['produce','图像/视频/声音生成'],['post','剪辑与交付']];
export const KINDS=[['canvas_skill','画布 Skill'],['builtin_tool','内置工具'],['external_method','外部方法'],['tutorial','教程']];
const kinds=Object.fromEntries(KINDS);
const statuses={entry_available:'可进入原工具',dependency_required:'需先处理依赖',reference:'方法参考',unknown:'状态未确认'};
const stageName=id=>STAGES.find(row=>row[0]===id)?.[1]||id;
const kindName=id=>kinds[id]||id;
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const button=(label,action,cls='')=>{const b=el('button',label,cls);b.type='button';b.addEventListener('click',action);return b;};
const copy=(key,values)=>msg('capability.'+key,values);
const joined=values=>values?.length?values.join('；'):translate(copy('not_provided'));
const identity=s=>JSON.stringify([s.actor||'',s.identityId||'',s.workspaceId||'']);

export function filterCapabilities(items,query='',stage='',kind=''){
 const term=query.trim().toLocaleLowerCase();
 return items.filter(row=>(!stage||row.stages.includes(stage))&&(!kind||row.kind===kind)&&[row.name,row.task,kindName(row.kind),...(row.inputs||[]),...(row.outputs||[]),...row.stages.map(stageName)].join(' ').toLocaleLowerCase().includes(term));
}

export function compatibleProject(row,target){
 if(!row||row.unavailable||row.read_only||row.storage_policy!=='postgres-series-v1')return false;
 const profile=row.profile_id||row.profile||row.profile_snapshot?.profile_id;
 const kind=row.profile_snapshot?.workspace_kind;
 const text=profile==='vsc.text-tools'||kind==='text-tools',creative=profile==='vsc.creative-tools'||kind==='creative-tools';
 if(target?.page==='text-tools')return text;
 if(target?.page==='creative-tools')return !text;
 return !text&&!creative;
}

export function capabilityHref(row,project){
 const action=row?.action,target=action?.target,params=target?.params||{};
 if(!project||action?.type!=='navigate'||!action.requires_project||!target)return null;
 const plain=['intelligent-creation','marketing-studio','editing','delivery'];
 let valid=false;
 if(row.kind==='canvas_skill')valid=target.page==='creative-canvas'&&Object.keys(params).length===1&&typeof params.skill==='string'&&/^[a-z0-9_-]+$/.test(params.skill);
 if(row.kind==='builtin_tool'){
  valid=(plain.includes(target.page)&&Object.keys(params).length===0)||
   (target.page==='text-tools'&&Object.keys(params).length===1&&['novel','translation','scoring','breakdown','qc','overseas'].includes(params.tool))||
   (target.page==='creative-tools'&&Object.keys(params).length===1&&['segment_remake','breakdown'].includes(params.tool))||
   (target.page==='classic-production'&&Object.keys(params).length===1&&['image','video'].includes(params.kind));
 }
 return valid?'/?'+new URLSearchParams({page:target.page,project,...params}):null;
}

export function createCapabilityCenter(root,ctx,{isCurrent=()=>true,navigate=href=>location.assign(href)}={}){
 const initial=identity(ctx.session()),key='vsc-capability-center:v1:'+['actor','identityId','workspaceId'].map(k=>ctx.session()[k]||'').join(':');
 let disposed=false,items=[],sources=new Map(),requests=new Map(),requestSerial=0,controllers=new Set(),loaded=false,error=null,loading=false;
 let query='',stage='',kind='',selectedId=null,detailWanted=false,restoreScroll=0,documentEpoch=0,pickerEpoch=0,documentSession=null,pickerSession=null;
 const current=()=>!disposed&&isCurrent()&&identity(ctx.session())===initial;
 const readScroll=()=>Number(root?.scrollTop)||(typeof window==='undefined'?0:Number(window.scrollY)||0);
 const writeScroll=y=>{if(root)root.scrollTop=y;if(typeof window!=='undefined')window.scrollTo?.(0,y);};
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved){query=typeof saved.query==='string'?saved.query:'';stage=STAGES.some(([id])=>id===saved.stage)?saved.stage:'';kind=KINDS.some(([id])=>id===saved.kind)?saved.kind:'';selectedId=typeof saved.selectedId==='string'?saved.selectedId:null;detailWanted=Boolean(saved.detailOpen);restoreScroll=Number.isFinite(saved.scrollY)?saved.scrollY:0;}}catch{}
 const save=()=>{if(!current())return;try{sessionStorage.setItem(key,JSON.stringify({query,stage,kind,selectedId,detailOpen:detail.open||detailWanted,scrollY:readScroll()}));}catch{}};
 async function get(path){const controller=new AbortController();controllers.add(controller);try{return await ctx.api(path,{signal:controller.signal,headers:{'X-CSRF-Token':ctx.session().csrf}});}finally{controllers.delete(controller);}}
 const center=el('section',null,'capability-center');center.dataset.component='capability-center';center.setAttribute('aria-labelledby','center-title');
 const heading=el('div',null,'cc-heading'),intro=el('div'),title=el('h1',copy('title'));title.id='center-title';intro.append(title,el('p',copy('subtitle'),'cc-muted'));
 const all=button(copy('all_tutorials'),()=>openAllDocs(),'cc-quiet cc-all-docs');all.id='all-docs';heading.append(intro,all);
 const toolbar=el('div',null,'cc-toolbar');
 const searchLabel=el('label',null,'cc-search'),search=el('input');search.id='search';search.type='search';search.value=query;bindAttribute(search,'aria-label',copy('search'));bindAttribute(search,'placeholder',copy('search'));searchLabel.append(search);
 const kindNav=el('nav',null,'cc-kinds');kindNav.id='kinds';bindAttribute(kindNav,'aria-label',copy('kind_filter'));
 toolbar.append(searchLabel,kindNav);
 const stages=el('nav',null,'cc-stages');stages.id='stages';bindAttribute(stages,'aria-label',copy('stage_filter'));
 const result=el('div',null,'cc-result'),count=el('span');count.id='count';count.setAttribute('role','status');count.setAttribute('aria-live','polite');const clear=button(copy('clear'),reset,'cc-link');clear.id='clear';result.append(count,clear);
 const notice=el('div',null,'cc-notice');notice.id='source-notice';notice.setAttribute('role','status');
 const cards=el('div',null,'cc-grid');cards.id='cards';cards.dataset.component='capability-grid';const state=el('div');state.id='list-state';state.setAttribute('role','status');
 center.append(heading,toolbar,stages,result,notice,cards,state);root.append(center);
 const dialogs=[];
 const focus=node=>{if(!current())return;if(node&&root.contains(node))node.focus();else search.focus();};
 const cardTrigger=id=>Array.from(cards.querySelectorAll('button')).find(node=>node.dataset.capabilityId===id);
 const detail=dialog('detail',()=>{detailWanted=false;documentEpoch++;pickerEpoch++;close(documentDialog,false);close(project,false);save();focus(cardTrigger(selectedId));});
 const documentDialog=dialog('document',()=>{documentEpoch++;const session=documentSession;documentSession=null;focus(session?.returnFocus?.()||all);});
 const project=dialog('project',()=>{pickerEpoch++;pickerSession=null;focus(detail.querySelector('.cc-primary'));});
 function dialog(id,onClose){const d=el('dialog',null,'capability-center cc-modal');d.id=id;d.setAttribute('aria-labelledby',id+'-title');dialogs.push(d);root.append(d);d.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation?.();requestClose(d);});d.addEventListener('close',()=>{if(!d.ccClosing){d.ccClosing=true;onClose();d.ccClosing=false;}});return d;}
 function requestClose(d){if(d===documentDialog&&documentSession?.fromList)openAllDocs(documentSession.doc.id);else close(d);}
 function close(d,restore=true){if(!d.open)return;if(!restore)d.ccClosing=true;d.close();if(!restore)d.ccClosing=false;}
 function frame(d,label){const h=el('header',null,'cc-modal-head'),title=el('h2',label);title.id=d.id+'-title';const x=button('×',()=>requestClose(d),'cc-close');bindAttribute(x,'aria-label',copy('close_title',{title:translate(label)}));h.append(title,x);const body=el('div',null,'cc-modal-body'),foot=el('footer',null,'cc-modal-foot');d.replaceChildren(h,body,foot);return {body,foot};}
 function show(d){if(!d.open)d.showModal();}
 function panel(title,description,action){const n=el('div',null,'cc-state');n.append(el('h3',title));if(description)n.append(el('p',description,'cc-muted'));if(action)n.append(action);return n;}
 function reset(){const active=search.ownerDocument?.activeElement;const fromClear=active===clear||Boolean(active&&state.contains(active));query='';stage='';kind='';search.value='';render();if(fromClear)search.focus();save();}
 function offline(){return typeof navigator!=='undefined'&&navigator.onLine===false;}
 function syncChips(nav,entries,selected,assign){
  const key=entries.map(([id])=>id).join('\u0000');
  if(nav.dataset.chipKey===key&&nav.children.length===entries.length){
   entries.forEach(([id,label],index)=>{const node=nav.children[index];if(node.textContent!==label)setText(node,label);node.setAttribute('aria-pressed',String(selected===id));});
   return;
  }
  nav.replaceChildren();nav.dataset.chipKey=key;
  for(const [id,label] of entries){const node=button(label,()=>{assign(id);render();save();});node.setAttribute('aria-pressed',String(selected===id));nav.append(node);}
 }
 function render(){
  if(!current())return;
  const available=new Set(items.flatMap(row=>row.stages)),availableKinds=new Set(items.map(row=>row.kind));
  syncChips(stages,[['', '全部'],...STAGES.filter(([id])=>available.has(id)||stage===id)],stage,id=>{stage=id;});
  syncChips(kindNav,[['',copy('all_kinds')],...KINDS.filter(([id])=>availableKinds.has(id)||kind===id)],kind,id=>{kind=id;});
  clear.hidden=!query&&!stage&&!kind;notice.replaceChildren();notice.hidden=true;
  if(offline()){notice.hidden=false;notice.append(el('p',copy('offline')),button(copy('retry_catalog'),()=>load()));}
  for(const source of sources.values())if(source.status==='error'){notice.hidden=false;notice.append(el('p',copy('source_error',{source:source.id})),button(copy('retry_source'),()=>load(source.id)));}
  cards.replaceChildren();state.replaceChildren();state.hidden=true;
  if(!loaded){setText(count,copy('pending_count'));state.hidden=false;state.append(panel(error?(error.status===403?copy('catalog_forbidden'):copy('catalog_error')):copy('catalog_loading'),error?copy('catalog_retry_hint'):copy('catalog_wait'),error?button(copy('retry_catalog'),()=>load()):null));center.setAttribute('aria-busy',String(loading));return;}
  center.removeAttribute('aria-busy');const rows=filterCapabilities(items,query,stage,kind);
  const scopeLabel=(stage?stageName(stage):'全部阶段')+(kind?' · '+kindName(kind):'');
  setText(count,copy('count',{count:rows.length,stage:scopeLabel,query:query.trim()?' · “'+query.trim()+'”':''}));
  if(loading||error){notice.hidden=false;notice.append(el('p',error?copy('refresh_error'):copy('refreshing')),error?button(copy('retry_catalog'),()=>load()):el('span'));}
  if(!rows.length){state.hidden=false;state.append(items.length?panel(copy('no_results'),copy('no_results_hint'),button(copy('clear'),reset)):panel(copy('empty'),copy('empty_hint')));}
  for(const row of rows){const card=el('article',null,'capability-card');card.dataset.kind=row.kind;const meta=el('div',null,'cc-meta');meta.append(el('span',kindName(row.kind),'cc-kind cc-kind-'+row.kind),el('span',statuses[row.status]||statuses.unknown,'cc-status cc-'+row.status));
   const io=el('dl',null,'cc-io');for(const [name,value]of [['输入',row.inputs],['产出',row.outputs]]){const pair=el('div');pair.append(el('dt',name),el('dd',joined(value)));io.append(pair);}
   const foot=el('div',null,'cc-card-foot'),open=button(copy('view'),()=>openDetail(row.id),'cc-quiet');open.dataset.capabilityId=row.id;foot.append(el('span',row.stages.map(stageName).join(' / '),'cc-muted'),open);
   card.append(meta,el('h3',row.name),el('p',row.task||copy('not_provided'),'cc-task'),io,foot);cards.append(card);
  }
 }
 async function load(source=null){
  if(!current())return;const turn=++requestSerial;requests.set(source||'*',turn);
  const latest=()=>source?requests.get(source)===turn&&(requests.get('*')||0)<=turn:requests.get('*')===turn;
  if(!source){loading=true;error=null;}render();
  try{const data=await get('/api/v1/discovery/capabilities'+(source?'?'+new URLSearchParams({source}):''));if(!current())return;
   if(data.schema_version!==1||!Array.isArray(data.items)||!Array.isArray(data.sources))throw new Error('Invalid capability response');
   for(const status of data.sources){if(!latest()||(!source&&(requests.get(status.id)||0)>turn))continue;sources.set(status.id,status);items=items.filter(row=>row.source!==status.id).concat(data.items.filter(row=>row.source===status.id));}
   loaded=Array.from(sources.values()).some(row=>row.status==='ok');if(!loaded)error=new Error('Capability sources unavailable');
  }catch(e){if(!current()||e.name==='AbortError')return;if(source){if(latest())sources.set(source,{id:source,status:'error'});}else if(latest())error=e;}
  finally{if(current()&&latest()){if(!source)loading=false;render();
    if(detailWanted&&loaded&&!detail.open){openDetail(selectedId);writeScroll(restoreScroll);}
    else if(!source&&loaded&&restoreScroll)writeScroll(restoreScroll);
   }}
 }
 function section(body,label,value){const n=el('section');n.append(el('h3',label),el('p',value,'cc-muted'));body.append(n);return n;}
 function openDetail(id){
  if(!current())return;selectedId=id;detailWanted=true;const row=items.find(item=>item.id===id),{body,foot}=frame(detail,row?.name||copy('removed'));
  foot.append(button(copy('back_list'),()=>close(detail),'cc-quiet'));
  if(!row){body.append(panel(copy('removed'),copy('removed_hint')));show(detail);save();return;}
  body.append(el('p',row.task||copy('not_provided')));const meta=el('div',null,'cc-metadata');for(const value of [row.stages.map(stageName).join(' / '),kindName(row.kind),row.source,row.path,row.version||copy('version_missing')])meta.append(el('span',value));body.append(meta);
  const io=el('div',null,'cc-detail-io');section(io,'所需输入',joined(row.inputs));section(io,'预期产出',joined(row.outputs));body.append(io);
  for(const [name,value]of [['适用',row.suitable],['不适用',row.unsuitable],['依赖与权限',row.dependencies]])section(body,name,joined(value));
  if(row.action?.requires_project)section(body,'项目范围',copy('project_requirement'));
  if(row.installation?.document!=='not_applicable')section(body,'本机文档与安装',row.installation?.document==='present'?copy('document_present'):copy('document_missing'));
  section(body,'当前状态',(statuses[row.status]||statuses.unknown)+'；'+row.status_reason);
  const related=el('section');related.append(el('h3','相关教程 / 方法'));if(row.related_documents.length)for(const doc of row.related_documents){const b=button('阅读'+doc.title,()=>openDocument(doc,()=>Array.from(related.querySelectorAll('button')).find(n=>n.dataset.documentId===doc.id)),'cc-quiet');b.dataset.documentId=doc.id;related.append(b);}else related.append(el('p',copy('no_related'),'cc-muted'));
  related.append(button(copy('all_tutorials'),()=>openAllDocs(),'cc-link'));body.append(related);
  if(row.action?.type==='read'&&row.action.document_id){const doc={id:row.action.document_id,title:row.name,source:row.source,path:row.path};foot.append(button(row.action.label,()=>openDocument(doc,()=>detail.querySelector('.cc-primary')),'cc-primary'));}
  else if(capabilityHref(row,'check'))foot.append(button(row.action.label,()=>openProjects(row),'cc-primary'));
  show(detail);save();
 }
 function openAllDocs(focusId=null){
  if(!current())return;documentEpoch++;const returnFocus=documentSession?.returnFocus||(()=>detail.open?detail.querySelector('.cc-link'):all);documentSession={mode:'list',returnFocus};const {body,foot}=frame(documentDialog,copy('all_tutorials'));body.classList.add('cc-doc-list');
  for(const row of items.filter(item=>item.kind==='tutorial')){const doc={id:row.action?.document_id,title:row.name,source:row.source,path:row.path};if(!doc.id)continue;const b=button(row.name,()=>openDocument(doc,()=>docButton(doc.id),true),'cc-quiet');b.dataset.documentId=doc.id;b.append(el('small',row.path,'cc-muted'));body.append(b);}
  if(!body.childElementCount)body.append(el('p',copy('tutorials_unavailable')));foot.append(button(detail.open?copy('back_detail'):copy('back_list'),()=>close(documentDialog),'cc-quiet'));show(documentDialog);if(focusId)focus(docButton(focusId));
 }
 function docButton(id){return Array.from(documentDialog.querySelectorAll('button')).find(node=>node.dataset.documentId===id);}
 async function openDocument(doc,returnFocus,fromList=false){
  if(!current())return;const epoch=++documentEpoch,capability=selectedId,prior=documentSession;documentSession={doc,returnFocus:fromList?(prior?.returnFocus||(()=>all)):returnFocus,fromList};
  const valid=()=>current()&&epoch===documentEpoch&&capability===selectedId&&documentDialog.open;
  const {body,foot}=frame(documentDialog,doc.title);body.append(el('p',doc.source+' · '+doc.path,'cc-muted'),el('p',copy('document_loading')));foot.append(button(fromList?copy('back_tutorials'):detail.open?copy('back_detail'):copy('back_list'),()=>fromList?openAllDocs(doc.id):close(documentDialog),'cc-quiet'));show(documentDialog);
  try{const value=await get('/api/v1/discovery/documents/'+encodeURIComponent(doc.id));if(!valid())return;if(value.id!==doc.id||value.format!=='text/plain'||typeof value.content!=='string'||!value.content.trim())throw new Error('Invalid document response');body.replaceChildren(el('p',value.source+' · '+value.path,'cc-muted'),el('pre',value.content,'cc-document-text'));}
  catch(e){if(!valid()||e.name==='AbortError')return;body.replaceChildren(panel(e.status===403?copy('document_forbidden'):offline()?copy('document_offline'):copy('document_error'),copy('document_retry_hint'),button(copy('retry_document'),()=>openDocument(doc,returnFocus,fromList))));}
 }
 async function editable(row){
  const [permission,directory]=await Promise.all([get('/api/v1/discovery'),get('/api/v1/projects')]);
  if(!Array.isArray(permission.projects)||!Array.isArray(directory.items))throw new Error('Invalid project response');
  const visible=new Set(scopedProjects(directory.items,ctx.session()).map(p=>p.id));
  const byId=new Map(directory.items.filter(p=>visible.has(p.id)).map(p=>[p.id,p]));
  return permission.projects.filter(p=>p.capabilities?.includes('edit')&&byId.has(p.id)).map(p=>({...byId.get(p.id),...p})).filter(p=>compatibleProject(p,row.action.target));
 }
 async function openProjects(row){
  if(!current())return;const epoch=++pickerEpoch;pickerSession={row,epoch,selected:null,busy:false};const valid=()=>current()&&pickerSession?.epoch===epoch&&selectedId===row.id&&project.open;
  const {body,foot}=frame(project,copy('choose_project'));body.append(el('p','能力：'+row.name),el('p',copy('project_requirement'),'cc-muted'));const host=el('div');host.setAttribute('role','status');host.append(el('p',copy('projects_loading')));body.append(host);foot.append(button(copy('cancel'),()=>close(project),'cc-quiet'));show(project);
  const retry=()=>openProjects(row);
  try{const projects=await editable(row);if(!valid())return;host.replaceChildren();if(!projects.length){host.append(panel(copy('no_projects'),copy('no_projects_hint')));const manage=el('a',copy('project_management'),'cc-quiet');manage.href='/?page=project-management';manage.addEventListener('click',save);foot.append(manage);return;}
   const options=el('div',null,'cc-project-options');pickerSession.selected=projects[0].id;
   for(const p of projects){const label=el('label',null,'project-option'),input=el('input');input.type='radio';input.name='capability-project';input.value=p.id;input.checked=p.id===pickerSession.selected;input.addEventListener('change',()=>{if(valid())pickerSession.selected=p.id;});label.append(input,el('span',p.name));options.append(label);}host.append(options);
   const confirm=button(copy('open_selected'),async()=>{
    if(!valid()||pickerSession.busy||!pickerSession.selected)return;const picked=pickerSession.selected;pickerSession.busy=true;confirm.disabled=true;setText(confirm,copy('opening'));
    try{const fresh=await editable(row);if(!valid())return;if(!fresh.some(p=>p.id===picked)){host.replaceChildren(panel(copy('lost_edit'),copy('no_write')));foot.replaceChildren(button(copy('back_detail'),()=>close(project),'cc-quiet'));return;}const href=capabilityHref(row,picked);if(!href)throw new Error('尚无已确认的使用入口');save();await navigate(href);}
    catch(e){if(valid()){host.append(panel(offline()?copy('projects_offline'):copy('projects_error'),e.status===403?copy('lost_edit'):copy('projects_retry_hint')));}}
    finally{if(valid()){pickerSession.busy=false;confirm.disabled=false;setText(confirm,copy('open_selected'));}}
   },'cc-primary');foot.append(confirm);
  }catch(e){if(valid()&&e.name!=='AbortError')host.replaceChildren(panel(offline()?copy('projects_offline'):copy('projects_error'),copy('projects_retry_hint'),button(copy('retry_projects'),retry)));}
 }
 search.addEventListener('input',()=>{query=search.value;render();save();});
 const online=()=>{if(current())render();},pagehide=()=>save();
 if(typeof window!=='undefined'){window.addEventListener('online',online);window.addEventListener('offline',online);window.addEventListener('pagehide',pagehide);}
 render();
 function dispose(){if(disposed)return;save();disposed=true;documentEpoch++;pickerEpoch++;for(const controller of controllers)controller.abort();controllers.clear();for(const d of dialogs){close(d,false);d.remove();}if(typeof window!=='undefined'){window.removeEventListener('online',online);window.removeEventListener('offline',online);window.removeEventListener('pagehide',pagehide);}}
 return {load,suspend:dispose,dispose};
}
