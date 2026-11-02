import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption,mountLocalePicker,getLocale,getLocaleRevision,setLocale} from './i18n.js';
import {createTaskNotifications} from './task-notifications.js';
import {artifactTitle, renderArtifactContent} from './artifact-reader.js';
const $ = (id) => document.getElementById(id);
const entry = new URLSearchParams(typeof window === 'undefined' ? '' : window.location.search);
const currentEntry=()=>new URLSearchParams(typeof window==='undefined'?'':window.location.search);
const platformViews=['home','projects','project','production','tasks','assets','settings','maintenance'];
const mainViews = ['desk','collection','trash'];
const customViews=['project-management','creative-canvas','editing','classic-production','blocking','previs','creative-tools','text-tools','media-imports','access','access-share','team-review','commerce','asset-center','service-operations','community','intelligent-creation','intelligent-storyboard'];
const navViews = ['home','community','asset-center','project-management','intelligent-creation','intelligent-storyboard','projects','tasks','assets','settings','desk','collection','trash'];
const specialistViews=['source','script','designs','library','candidates','delivery','workbench','media','artifacts','canvas'];
const initialView = [...mainViews,...platformViews,...customViews,...specialistViews].includes(entry.get('page')) ? entry.get('page') : 'home';
const state = {project: entry.get('project'), object: entry.get('scope'), offset: 0, limit: 36, total: 0, revision: 0, csrf: null, actor: null, writeAvailable: false, writable: false, comparisons: new Map(),projectRows:new Map(), previewCapabilities: {}, expandedNodes: new Set(), treeNodes: [],treeMode:'legacy', treeRequest: 0, resourceRequest: 0, artifactRequest: 0, mediaRequest: 0, documentRequest: 0, selectedArtifact:null,compareRequest:0, primary:mainViews.includes(initialView)?initialView:'project', view: typeof window === 'undefined' ? 'workbench' : initialView};
const names = {work: '部', episode: '集', scene: '场', sequence: '镜组', shot: '镜', asset: '资产身份', take: '候选',
  image: '图片', video: '视频', audio: '音频', text: '文本', document: '文档', approved: '已批准', draft: '草稿', rejected: '已拒绝', retired: '已退役', selected: '已选',
  verified: '摘要一致', unverified: '摘要未核验', mismatch: '摘要变化', missing: '字节缺失', blocked: '读取受阻', owned: '自有', licensed: '已授权', unknown: '权利未登记',video_take:'镜头视频',vfx_overlay:'透明特效叠层',first_frame:'镜头首帧',last_frame:'镜头尾帧',dialogue_dry:'对白干声',identity_face:'人物正脸',composition:'构图参考',voice_sample:'声音参考',music:'配乐',ambience:'环境声',sfx:'音效'};
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text != null) setText(node,text); return node; }
function notice(message) { setText($('notice'),message || ''); $('notice').hidden = !message; }
function applySession(session) {
  const previousIdentity=state.identityId||state.actor;
  if((state.identityId||state.actor)!==(session.identity_id||session.actor))editWorkspace?.suspend?.();
  state.actor=session.actor;state.csrf=session.csrf_token;state.writeAvailable=session.write_available===true;state.identityId=session.identity_id;state.shareId=session.share_id;state.workspaceId=session.workspace_id;
  if(previousIdentity!==(state.identityId||state.actor))readAccountLocale();
  const project=state.projectRows.get(state.project);
  state.writable=state.writeAvailable && project?.storage_policy==='postgres-series-v1' && !project.read_only;
  setText($('session-label'),!state.writeAvailable?msg("ui.read_only_browsing"):state.actor?msg("ui.actor_value0",{value0:state.actor}):msg("ui.browsing"));
  $('session-open').disabled=false;
  $('upload-open').disabled=!(state.writable && state.actor);
}
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options});
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {const error=new Error(value.message || value.detail || `请求失败 (${response.status})`);error.status=response.status;error.code=value.error;throw error;}
  return value;
}
const base = () => `/api/v1/projects/${encodeURIComponent(state.project)}`;
const mediaUrl = (id) => `${base()}/media/${encodeURIComponent(id)}/content`;
function reviewContext(project,alive,reload){
  const write=async(action,payload,key)=>{if(!alive())throw new Error('所见项目或版本已切换，请重新读取。');if(!state.actor)throw new Error('请先建立人工操作会话');const result=await api(`/api/v1/projects/${encodeURIComponent(project)}/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,expected_revision:state.revision,idempotency_key:key})});if(!alive())return;state.revision=result.revision ?? state.revision;await reload();return result;};
  return {historyPage:async(filters,page)=>{const value=await api(`/api/v1/projects/${encodeURIComponent(project)}/review-history?`+new URLSearchParams({...filters,...page}));if(alive())return value;},artifact:async id=>{if(alive()){$('media-dialog').close();await switchView('artifacts');await openArtifact(id);}},media:id=>alive()&&openMedia(id),local:(action,row)=>alive()&&openLocalProduction(action,{...row,onReviewProposed:async()=>{if(alive())await reload();}}),onError:error=>notice(error.message),process:state.actor && state.writable?(payload,key)=>write('review-process',payload,key):null,save:(payload,key)=>write('artifact-review-notes',payload,key)};
}
const previewUrl = (id,purpose) => `${base()}/media/${encodeURIComponent(id)}/preview?purpose=${encodeURIComponent(purpose)}`;
const hasRendition = (media,purpose) => (media.renditions || []).some(row=>row.purpose===purpose);
function guard(fn) { return async (...args) => { try { notice(''); await fn(...args); } catch(error) { notice(error.message); } }; }
function badge(text, severity='') { return el('span', `badge ${severity}`, names[text] || text); }
function pretty(value) { return JSON.stringify(value, null, 2); }
function facts(title, value) { const panel = el('section', 'detail-panel'); panel.append(el('h3', '', title));if(value?.truncated)panel.append(el('p','hint',msg("ui.only_part_of_the_relationships_is_shown_because_this")));panel.append(el('pre', 'structured', pretty(value))); return panel; }
function lineagePanel(media,lineage) {
  const panel=el('section','detail-panel');panel.append(el('h3','',msg("ui.sources_and_processing")));
  if(lineage.truncated)panel.append(el('p','hint',msg("ui.only_part_of_the_source_graph_is_shown_because")));
  for(const input of lineage.inputs || []){const row=el('div','lineage-input');const id=input.media_id || input.parent_id;const open=el('button','',msg("ui.input_value0_layer_value1_value2",{value0:input.role || input.relation || '',value1:input.layer_order ?? '—',value2:id}));open.addEventListener('click',guard(()=>openMedia(id)));row.append(open,el('pre','structured',pretty({transform:input.transform,mask_input_id:input.mask_input_id,opacity:input.opacity,parameters:input.parameters})));panel.append(row);}
  const details=el('details');details.append(el('summary','',msg("ui.full_recipe_and_source_evidence")),el('pre','structured',pretty({...lineage,sources:media.sources || lineage.sources || []})));panel.append(details);return panel;
}
function size(bytes) { if (bytes == null) return '未知大小'; return bytes > 1048576 ? `${(bytes/1048576).toFixed(1)} MB` : `${(bytes/1024).toFixed(1)} KB`; }

let roleMemory = null;
let resourceCanvas = null, resourceSettings = null, creativeWorkbench = null, scriptWorkspace = null;
let sourceIntake = null, designWorkspace = null, resourceLibrary = null;
let localProduction = null;
let assistedDesk = null;
let productionPlatform=null,creativeCanvasPanel=null,editWorkspace=null,classicProduction=null,spatialScenePanel=null,creativeTools=null,textTools=null,mediaImports=null,accessControl=null,teamReview=null,commerce=null,assetCenter=null,serviceOperations=null,intelligentProduction=null,projectManagement=null,community=null;
let accessControlLoading=null;
async function ensureAccessControl(){if(accessControl)return accessControl;if(!accessControlLoading)accessControlLoading=(async()=>{const {createAccessControl}=await import('./access-control.js');accessControl=createAccessControl($('access-control-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf,workspaceId:state.workspaceId}),onSession:async value=>{applySession(value);if(value.share_id&&!value.identity_id){state.view='access-share';await switchView('access-share');}else await loadProjects();},navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}}); return accessControl;})();try{return await accessControlLoading;}finally{accessControlLoading=null;}}
async function readAccountLocale(){const actor=state.actor,languageRevision=getLocaleRevision();if(!actor)return;try{const value=await api('/api/v1/access');if(state.actor===actor&&getLocaleRevision()===languageRevision&&value.identity?.preferences?.language)setLocale(value.identity.preferences.language);}catch{/* A read-only or shared session keeps its local interface preference. */}}
let taskNotifications=null,taskNotificationKey=null;
async function loadTaskNotifications(){
  const project=state.projectRows.get(state.project)?.storage_policy==='postgres-series-v1'&&state.identityId&&state.view!=='access-share'?state.project:null;
  const key=project?state.identityId+':'+project:null;
  $('task-notifications').hidden=!key;if(key===taskNotificationKey)return;taskNotificationKey=key;
  if(!taskNotifications&&key)taskNotifications=createTaskNotifications($('task-notifications'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf})});
  if(key)await taskNotifications.load({project});else taskNotifications?.suspend();
}
let pendingInvite=null;
let episodeScope=entry.get('episode')||null;
let customViewRequest=0;
function setEntryOptions(page,project,scope,options={}){
  if(typeof window==='undefined')return;
  const query=new URLSearchParams({page,...(project?{project}:{}),...(scope?{scope}:{}),...options});
  window.history.pushState(null,'','?'+query);
}
function openedCreativeTarget(id,project,episode){
  if(project!==state.project||typeof window==='undefined')return;
  episodeScope=episode||null;const route=currentEntry();if(id)route.set('task_target',id);else route.delete('task_target');if(episode)route.set('episode',episode);else route.delete('episode');window.history.replaceState(null,'','?'+route);updateShell(state.view);
}
function updateShell(view){
  const full=['creative-canvas','classic-production','intelligent-creation','intelligent-storyboard','editing','blocking','previs','library','assets','access-share'].includes(view);
  document.body?.classList.toggle('production-shell',full);
  document.querySelectorAll('.workspace').forEach(n=>n.classList.toggle('full-workspace',full));
  const nav=$('production-navigation');if(!nav)return;nav.hidden=!full||view==='access-share';
  const context=$('production-context');if(context){context.hidden=!full||view==='access-share'||!state.project;if(!context.hidden)renderProductionContext();}
  for(const a of nav.querySelectorAll('a')){const page=a.dataset.productionPage,kind=a.dataset.kind;const q=new URLSearchParams({page,...(state.project?{project:state.project}:{}),...(episodeScope?{episode:episodeScope}:{}),...(state.object?{scope:state.object}:{}),...(kind?{kind}:{})});a.href='?'+q;if(page===view&&(!kind||kind===(currentEntry().get('kind')||'video')))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
}
let contextTicket=0,contextBusy=false,episodePage=null;
const contextRoutes=new Map(),projectEpisodes=new Map();
const contextKey=(project,episode,page=state.view,kind=currentEntry().get('kind')||'')=>[state.actor||'reader',page,kind,project,episode||''].join('|');
async function beforeContextSwitch(){
  const module=state.view==='creative-canvas'?creativeCanvasPanel:state.view==='classic-production'?classicProduction:state.view==='editing'?editWorkspace:['intelligent-creation','intelligent-storyboard'].includes(state.view)?intelligentProduction:null;
  const result=await module?.beforeContextSwitch?.();if(result?.ready===false){notice(result.message||msg("ui.current_inputs_cannot_be_retained_yet_save_first"));return false;}return true;
}
function renderProductionContext(){
  const project=$('production-project'),episode=$('production-episode');if(!project||!episode)return;
  project.replaceChildren();for(const row of state.projectRows.values())if(!['vsc.text-tools','vsc.creative-tools'].includes(row.profile_id||row.profile))project.append(localizedOption(row.id,row.name));project.value=state.project||'';project.title=project.selectedOptions[0]?.text||'制作项目';project.disabled=contextBusy;
  if(episodePage?.project!==state.project){episodePage={project:state.project,items:[],next:null,loading:false};loadProductionEpisodes(false);}
  episode.replaceChildren(localizedOption('',msg("ui.project_scope")));for(const row of episodePage?.items||[])episode.append(localizedOption(row.id,row.title||row.display_code||msg("novel-parser.untitled_episode")));if(episodeScope&&!Array.from(episode.options).some(o=>o.value===episodeScope))episode.append(localizedOption(episodeScope,msg("ui.current_episode_loading")));episode.value=episodeScope||'';episode.title=episode.selectedOptions[0]?.text||'当前分集';episode.disabled=contextBusy||episodePage?.loading;const more=$('production-episodes-more');more.hidden=episodePage?.next==null;more.disabled=contextBusy||episodePage?.loading;
}
async function loadProductionEpisodes(append=false){
  const p=state.project,page=episodePage,t=++contextTicket,identity=state.actor;if(!p||page?.project!==p||page.loading)return;page.loading=true;
  try{const offset=append?page.next:0;if(offset==null)return;const query=new URLSearchParams({offset:String(offset),limit:'100'});if(!append&&episodeScope)query.set('episode_id',episodeScope);const data=await api(`/api/v1/projects/${encodeURIComponent(p)}/production-platform?${query}`);if(t!==contextTicket||state.project!==p||identity!==state.actor||page!==episodePage)return;page.items=append?[...page.items,...data.episodes.items]:data.episodes.items;if(data.episode&&!page.items.some(r=>r.id===data.episode.id))page.items.push(data.episode);page.next=data.episodes.next_offset;
  }catch(error){if(t===contextTicket&&state.project===p)notice(msg("ui.episode_list_could_not_be_loaded_value0",{value0:error.message}));}finally{if(t===contextTicket&&page===episodePage){page.loading=false;renderProductionContext();}}
}
async function changeProductionContext(project,episode,options={}){
  if(contextBusy)return;contextBusy=true;renderProductionContext();const previous=currentEntry(),oldProject=state.project,oldEpisode=episodeScope,oldView=state.view,oldObject=state.object,identity=state.actor;
  try{if(!await beforeContextSwitch())return;if(state.project!==oldProject||state.view!==oldView||state.actor!==identity)return;contextRoutes.set(contextKey(oldProject,oldEpisode),previous.toString());projectEpisodes.set(oldProject,oldEpisode);const page=options.page||oldView,kind=options.kind??previous.get('kind');if(episode===undefined)episode=projectEpisodes.get(project)||null;const remembered=contextRoutes.get(contextKey(project,episode,page,kind||'')),route=remembered?new URLSearchParams(remembered):new URLSearchParams({page,project,...(episode?{episode}:{}),...(kind?{kind}:{})});route.set('page',page);if(kind)route.set('kind',kind);window.history.pushState(null,'','?'+route);episodeScope=episode||null;state.view=page;await selectProject(project,{scope:route.get('scope')});
  }catch(error){window.history.replaceState(null,'','?'+previous);state.project=oldProject;state.object=oldObject;episodeScope=oldEpisode;state.view=oldView;try{await selectProject(oldProject,{scope:oldObject});}catch{}notice(msg("ui.switch_incomplete_inputs_in_the_original_scope_are_preserved",{value0:error.message}));}finally{contextBusy=false;renderProductionContext();}
}
let recentRequest=0;
function renderRecentProjects(rows){
  const recent=$('recent-projects');if(!recent)return;const ticket=++recentRequest;recent.replaceChildren(el('p','hint',msg("ui.loading_recent_creations")));const actor=state.actor;
  if(!actor){recent.replaceChildren(el('p','hint',msg("ui.start_a_session_to_see_recent_creations")));return;}
  api('/api/v1/discovery',{headers:{'X-CSRF-Token':state.csrf}}).then(data=>{
    if(state.actor!==actor||ticket!==recentRequest)return;recent.replaceChildren();
    for(const row of data.recent.slice(0,8)){const a=el('a','recent-project');a.href=row.href;a.title=[row.project_name,row.episode_name,row.title].filter(Boolean).join(' · ');if(row.cover?.modality==='image'){const image=el('img');image.src=row.cover.content_url;bindAttribute(image,"alt",'');image.loading='lazy';a.append(image);}const copy=el('span','recent-project-copy');copy.append(el('strong','',row.title||row.kind_label),el('small','',[row.project_name,row.episode_name].filter(Boolean).join(' · ')));const minutes=Math.max(0,Math.floor((Date.now()-new Date(row.created_at))/60000)),time=minutes<1?'刚刚':minutes<60?minutes+' 分钟前':minutes<1440?Math.floor(minutes/60)+' 小时前':Math.floor(minutes/1440)+' 天前';copy.append(el('small','',joinMessages(["",row.kind_label||msg("home.agent_create")," · ",time,""])));a.append(copy);recent.append(a);}if(!data.recent.length)recent.append(el('p','hint',msg("ui.no_saved_creations_yet")));
  }).catch(()=>{if(ticket===recentRequest)recent.replaceChildren(el('p','hint',msg("ui.recent_creations_could_not_be_loaded")));});
}

async function loadProductionPlatform(){
  if(state.view==='production'&&!episodeScope)episodeScope=state.object;
  if(!productionPlatform){const {createProductionPlatform}=await import('./production-platform.js');productionPlatform=createProductionPlatform($('production-platform'),{api,notice,projects:()=>[...state.projectRows.values()],projectName:()=>state.projectRows.get(state.project)?.name,refreshProjects:async()=>{const listing=await api('/api/v1/projects');state.projectRows=new Map(listing.items.map(r=>[r.id,r]));renderRecentProjects(listing.items);},session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable,writeAvailable:state.writeAvailable}),setRevision:(value,project)=>{if(project===state.project&&value!=null)state.revision=value;},navigate:async(page,scope=state.object,project=state.project,options={})=>{setEntryOptions(page,project,scope,options);if(options.episode)episodeScope=options.episode;if(['text-tools','creative-tools'].includes(page)&&!project){state.project=null;state.object=null;episodeScope=null;state.view=page;await loadProjects();return;}if(page==='production')episodeScope=scope;if(page==='project')episodeScope=null;state.view=page;await selectProject(project,{scope});},created:async(id,page='project')=>{state.project=id;state.object=null;state.view=page;await loadProjects();},media:openMedia,artifact:async id=>{await switchView('artifacts');await openArtifact(id);},settings:openResourceSettings,memory:openRoleMemory,account:()=>$('session-dialog').showModal()});}
  await productionPlatform.load({page:state.view,project:state.project,object:state.object,tab:currentEntry().get('tab'),create:currentEntry().get('create'),taskId:currentEntry().get('task_id'),taskKind:currentEntry().get('task_kind')});
}
async function loadCustomView(view){
  const project=state.project,object=state.object,ticket=++customViewRequest;
  if(view==='project-management'){
    if(!projectManagement){const {createProjectManagement}=await import('./project-management.js');projectManagement=createProjectManagement($('project-management-view'),{api,notice,onScope:(p,row)=>{state.project=p;state.object=null;episodeScope=null;$('tree').replaceChildren();state.treeNodes=[];if(p&&!state.projectRows.has(p))$('projects').append(localizedOption(p,msg("ui.value0_in_trash",{value0:row?.name||msg("common.project")})));if(p)$('projects').value=p;else{$('projects').prepend(localizedOption('',msg("ui.select_a_project_extra_2")));$('projects').value='';}syncRoute();},session:()=>({actor:state.actor,identityId:state.identityId,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,p)=>{if(p===state.project)state.revision=value;},onProjectsChanged:async()=>{const listing=await api('/api/v1/projects');state.projectRows=new Map(listing.items.map(r=>[r.id,r]));$('projects').replaceChildren();for(const row of listing.items){const option=localizedOption(row.id,row.name);$('projects').append(option);}if(state.projectRows.has(state.project))$('projects').value=state.project;else if(state.project){$('projects').append(localizedOption(state.project,msg("ui.current_project_is_recycled")));$('projects').value=state.project;}},navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});},media:openMedia});}
    if(ticket===customViewRequest&&view===state.view)await projectManagement.load({project});
  }else if(view==='creative-canvas'){
    if(!creativeCanvasPanel){const {createCreativeCanvasPanel}=await import('./creative-canvas.js');creativeCanvasPanel=createCreativeCanvasPanel({opened:openedCreativeTarget,api,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,projectId:state.project,writable:state.writable}),setRevision:(value,id)=>{if(id===state.project)state.revision=value;},notice,projectId:()=>state.project,openArtifact:async id=>{await switchView('artifacts');await openArtifact(id);}});}
    if(ticket===customViewRequest&&view===state.view)await creativeCanvasPanel.load($('creative-canvas-view'),project,episodeScope||(state.treeNodes.find(r=>r.id===object)?.kind==='episode'?object:null),currentEntry().get('task_target'));
  }else if(view==='blocking'||view==='previs'){
    if(!spatialScenePanel){const {createSpatialScenePanel}=await import('./spatial-scene.js');spatialScenePanel=createSpatialScenePanel({api,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,projectId:state.project,writable:state.writable}),setRevision:(value,id)=>{if(!id||id===state.project)state.revision=value;},notice,projectId:()=>state.project,openArtifact:async id=>{await switchView('artifacts');await openArtifact(id);}});}
    if(ticket===customViewRequest&&view===state.view)await spatialScenePanel.load($('spatial-scene-view'),project,view==='blocking'?'blocking':'previs',currentEntry().get('task_target'));
  }else if(view==='creative-tools'){
    if(!creativeTools){const {createCreativeTools}=await import('./creative-tools.js');creativeTools=createCreativeTools($('creative-tools-view'),{api,projects:()=>[...state.projectRows.values()],activateWorkspace:async(p,episode)=>{state.project=p;state.object=null;episodeScope=episode;state.view='creative-tools';setEntryOptions('creative-tools',p,null,{...(currentEntry().get('tool')?{tool:currentEntry().get('tool')}:{}),...(episode?{episode}:{})});await loadProjects();},session:()=>({actor:state.actor,identityId:state.identityId,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,id)=>{if(!id||id===state.project)state.revision=value;},notice,navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}});}
    if(ticket===customViewRequest&&view===state.view)await creativeTools.load({project,object:object||episodeScope,tool:currentEntry().get('tool')});
  }else if(view==='text-tools'){
    if(!textTools){const {createTextTools}=await import('./text-tools.js');textTools=createTextTools($('text-tools-view'),{api,activateWorkspace:async(p,unitId=null)=>{state.project=p;state.object=null;episodeScope=null;state.view='text-tools';const url=new URL(location.href);if(unitId)url.searchParams.set('task_target',unitId);else url.searchParams.delete('task_target');url.searchParams.set('project',p);url.searchParams.set('page','text-tools');history.replaceState(null,'',url);await loadProjects();},openArtifact:async id=>{await switchView('artifacts');await openArtifact(id);},session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,id)=>{if(id===state.project)state.revision=value;},notice,navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}});}
    if(ticket===customViewRequest&&view===state.view)await textTools.load({project,object:episodeScope||object,targetId:currentEntry().get('task_target'),tool:currentEntry().get('tool')});
  }else if(view==='media-imports'){
    const {createMediaImports}=await import('./media-imports.js');if(ticket!==customViewRequest||view!==state.view)return;
    mediaImports?.suspend();mediaImports=createMediaImports({root:$('media-imports-view'),api,project,initialBatchId:currentEntry().get('task_target'),episodeId:episodeScope||(state.treeNodes.find(r=>r.id===object)?.kind==='episode'?object:null),session:()=>({actor:state.actor,csrf:state.csrf,writable:state.writable}),onChange:value=>{if(project===state.project&&value.revision!=null)state.revision=value.revision;}});await mediaImports.load();
  }else if(view==='access'||view==='access-share'){
    await ensureAccessControl();
    if(ticket===customViewRequest&&view===state.view)await accessControl.load({project,object,page:view,invite:pendingInvite});
  }else if(view==='team-review'){
    if(!teamReview){const {createTeamReview}=await import('./team-review.js');teamReview=createTeamReview($('team-review-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf}),setRevision:(value,p)=>{if(p===state.project)state.revision=value;},media:openMedia,navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}});}
    if(ticket===customViewRequest&&view===state.view)await teamReview.load({project,object});
  }else if(view==='commerce'){
    if(!commerce){const {createCommerce}=await import('./commerce.js');commerce=createCommerce($('commerce-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,p)=>{if(p===state.project)state.revision=value;},navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}});}
    if(ticket===customViewRequest&&view===state.view)await commerce.load({project,object});
  }else if(view==='community'){
    if(!community){const {createCommunity}=await import('./community.js');community=createCommunity($('community-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf,projectId:state.project,revision:state.revision,writable:state.writable}),setRevision:(value,p)=>{if(p===state.project&&value!=null)state.revision=value;}});}
    if(ticket===customViewRequest&&view===state.view)await community.load({projectId:project});
  }else if(view==='service-operations'){
    if(!serviceOperations){const {createServiceOperations}=await import('./service-operations.js');serviceOperations=createServiceOperations($('service-operations-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,p)=>{if(p===state.project)state.revision=value;},navigate:async(page,id,p=state.project)=>{state.view=page;await selectProject(p,{scope:id});}});}
    if(ticket===customViewRequest&&view===state.view)await serviceOperations.load({project,object});
  }else if(view==='asset-center'){
    if(!assetCenter){const {createAssetCenter}=await import('./asset-center.js');assetCenter=createAssetCenter($('asset-center-view'),{api,notice,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),projects:()=>[...state.projectRows.values()],projectId:()=>state.project,setRevision:(value,p)=>{if(!p||p===state.project)state.revision=value;},workspaces:async()=>(await api('/api/v1/access')).workspaces});}
    if(ticket===customViewRequest&&view===state.view)await assetCenter.load();
  }else if(['intelligent-creation','intelligent-storyboard'].includes(view)){
    if(!intelligentProduction){const {createIntelligentProductionPanel}=await import('./intelligent-production.js');intelligentProduction=createIntelligentProductionPanel({opened:openedCreativeTarget,api,notice,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,projectId:state.project,writable:state.writable}),setRevision:(value,p)=>{if(p===state.project)state.revision=value;},projectId:()=>state.project,openArtifact:async id=>{await switchView('artifacts');await openArtifact(id);}});}
    if(ticket===customViewRequest&&view===state.view)await intelligentProduction.load($('intelligent-production-view'),project,episodeScope||(state.treeNodes.find(r=>r.id===object)?.kind==='episode'?object:null),view==='intelligent-storyboard'?'storyboard':'creation',currentEntry().get('task_target'));
  }else if(view==='classic-production'){
    if(!classicProduction){const {createClassicProduction}=await import('./classic-production.js');classicProduction=createClassicProduction($('classic-production-view'),{api,notice,nodes:()=>state.treeNodes,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),setRevision:(value,id)=>{if(id===state.project)state.revision=value;},navigate:async(page,id)=>{state.object=id;await switchView(page);},onShot:(id,episode)=>{state.object=id;if(episode)episodeScope=episode;syncRoute();updateShell(state.view);},media:openMedia,openArtifact:async id=>{await switchView('artifacts');await openArtifact(id);}});}
    if(ticket===customViewRequest&&view===state.view)await classicProduction.load({projectId:project,objectId:object,episodeId:episodeScope,productionKind:currentEntry().get('kind')||'video',mode:currentEntry().get('mode')||undefined});
  }else if(view==='editing'){
    const {createEditWorkspace}=await import('./edit-workspace.js');if(ticket!==customViewRequest||view!==state.view)return;
    editWorkspace=createEditWorkspace({root:$('edit-workspace-view'),api,project,episodeId:episodeScope||object,session:()=>({actor:state.actor,identityId:state.identityId,csrf:state.csrf,revision:state.revision,writable:state.writable}),onArtifact:async id=>{await switchView('artifacts');await openArtifact(id);},onChange:()=>notice(msg("ui.edit_draft_updated"))});await editWorkspace.load?.();
  }
}
const objectReviewers=new WeakMap();
async function loadObjectReviewer(host,options){
  let entry=objectReviewers.get(host);
  if(!entry){entry={binding:options,request:0};objectReviewers.set(host,entry);entry.promise=import('./assisted-desk.js').then(({createAssistedDesk})=>createAssistedDesk(host,{
    api,player,notice,local:openLocalProduction,media:openMedia,artifact:async id=>{await switchView('artifacts');await openArtifact(id);},
    specialist:switchView,navigate:switchView,locateObject:async id=>{state.object=id;await switchView('workbench');},login:()=>$('session-dialog').showModal(),
    session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:entry.binding.projectId===state.project&&state.writable,writeAvailable:state.writeAvailable}),
    revision:value=>{if(entry.binding.projectId===state.project)state.revision=value;},
    projectName:()=>state.projectRows.get(entry.binding.projectId)?.name,
    selectedRef:ref=>{if(entry.binding.projectId!==state.project)return;entry.binding.onRef?.(ref);},
    mediaActions:async(media,alive,reload)=>{
      const binding=entry.binding,project=binding.projectId,wrapper=el('section','stage-candidate-actions');
      const current=()=>alive()&&entry.binding===binding&&project===state.project;
      async function read(offset=0){
        const params=new URLSearchParams({section:'candidates',entity_id:media.id,limit:'24',offset:String(offset)});
        if(binding.targetObjectId||binding.objectId)params.set('object_id',binding.targetObjectId||binding.objectId);
        const data=await api(`/api/v1/projects/${encodeURIComponent(project)}/workbench?${params}`);if(!current())return;
        const page=data.sections?.candidates||{items:[],total:0};wrapper.replaceChildren();
        const candidates=page.items.map(row=>({...row,role:row.purpose,selected:row.status==='selected'}));
        if(!candidates.length&&media.review_targets?.some(row=>row.target?.render_id))return;
        wrapper.append(reviewForm({...media,candidates},{alive:current,onChanged:reload}));
        if(page.total>24){const nav=el('nav','pagination');bindAttribute(nav,'aria-label',msg("ui.pagination_for_current_media_use_candidates"));for(const [label,next]of [[msg("common.previous_page"),offset?Math.max(0,offset-24):null],[msg("common.next_page"),page.next_offset]]){const button=el('button','',label);button.type='button';button.disabled=next==null;button.addEventListener('click',guard(()=>current()&&read(next)));nav.append(button);}wrapper.append(nav);}
      }
      await read();return current()?wrapper:null;
    },
  }));}
  entry.binding=options;const request=++entry.request,desk=await entry.promise;if(request!==entry.request)return null;
  await desk.load({...options,page:'desk',bucket:'results',embedded:true});return request===entry.request?desk:null;
}
function stageRef(ref){
  if(typeof window==='undefined')return;const route=currentEntry();route.set('object',`${ref.kind}:${ref.id}`);if(ref.version_id)route.set('version',ref.version_id);else route.delete('version');if(ref.render_id)route.set('render',ref.render_id);else route.delete('render');const link='?'+route;if(window.location.search!==link)window.history.pushState(null,'',link);
}
let sharedLibrary = null;
async function libraryController(){
  if(!sharedLibrary){const {createSharedLibrary}=await import('./shared-library.js');sharedLibrary=createSharedLibrary({api,session:()=>({actor:state.actor,csrf:state.csrf,revision:state.revision,writable:state.writable}),projects:()=>[...state.projectRows.values()],canWrite:project=>state.writeAvailable&&state.projectRows.get(project)?.storage_policy==='postgres-series-v1'&&!state.projectRows.get(project)?.read_only,setRevision:(value,project)=>{if(!project||project===state.project)state.revision=value;},notice});}
  return sharedLibrary;
}
async function openLibraryTarget(target){return (await libraryController()).choose({...target,projectId:state.project});}
let pendingDeskRef = entry.get('object'), pendingDeskVersion = entry.get('version');
let pendingDeskBucket = entry.get('bucket');
let deskRouteReady=false,restoringDeskRoute=false;
async function loadAssistedDesk() {
  if(state.view==='collection'){assistedDesk?.suspend();await (await libraryController()).load($('assisted-desk'));return;}
  if(!assistedDesk){
    const {createAssistedDesk,deskLink}=await import('./assisted-desk.js');
    if(!assistedDesk)assistedDesk=createAssistedDesk($('assisted-desk'),{
      api,player,notice,local:openLocalProduction,media:openMedia,
      artifact:async id=>{await switchView('artifacts');await openArtifact(id);},
      specialist:switchView,navigate:switchView,library:openLibraryTarget,locateObject:async id=>{state.object=id;await switchView('workbench');},login:()=>$('session-dialog').showModal(),
      session:()=>({actor:state.actor,csrf:state.csrf,writable:state.writable,writeAvailable:state.writeAvailable}),
      revision:value=>{state.revision=value;},
      projects:()=>[...state.projectRows.values()],projectName:()=>state.projectRows.get(state.project)?.name,
      chooseProject:async(id,page,scope=null)=>{state.view=page;await selectProject(id,{scope});},
      created:async id=>{state.project=id;state.object=null;state.view='projects';await loadProjects();await switchView('source');},
      route:route=>{if(typeof window!=='undefined'&&mainViews.includes(state.view)){
        const link=deskLink(route);if(window.location.search!==link){
          const method=!deskRouteReady||restoringDeskRoute?'replaceState':'pushState';window.history[method](null,'',link);
        }deskRouteReady=true;
      }},
    });
  }
  const ref=pendingDeskRef,version=pendingDeskVersion;pendingDeskRef=null;pendingDeskVersion=null;
  const bucket=pendingDeskBucket;pendingDeskBucket=null;
  await assistedDesk.load({projectId:state.project,objectId:state.object,page:state.view,
    bucket:bucket||undefined,ref,version});
}
async function openLocalProduction(action, row) {
  if (!localProduction) {
    const {createLocalProduction} = await import('./local-production.js');
    localProduction = createLocalProduction($('local-production-dialog'), {api, project:()=>state.project,
      session:()=>({actor:state.actor,csrf:state.csrf}),revision:value=>{state.revision=value;},
      onArtifact:async id=>{$('media-dialog').close();await switchView('artifacts');await openArtifact(id);}});
  }
  await localProduction.open(action,row);
}
async function loadWorkbench() {
  if (!state.project || !['workbench','candidates','delivery'].includes(state.view)) return;
  if (!creativeWorkbench) {
    const {createCreativeWorkbench} = await import('./workbench.js');
    if (!creativeWorkbench) creativeWorkbench = createCreativeWorkbench($('creative-workbench'), {
      onObject: async id => { await selectObject(id); },
      onMedia: openMedia,
      onCompare: async id=>{if(state.comparisons.has(id))return;if(state.comparisons.size>=4)throw new Error('最多并排比较4个候选。');const project=state.project,media=await api(`${base()}/media/${encodeURIComponent(id)}`);if(project!==state.project)throw new Error('项目已切换，请重新选择候选。');state.comparisons.set(id,media);updateCompare();},
      onArtifact: async id => { await switchView('artifacts'); await openArtifact(id); },
      onGraph: focus => switchView('canvas', focus), onError: error => notice(error.message),
      onLocalAction: openLocalProduction,
      onLibrary:openLibraryTarget,
      createReviewer:loadObjectReviewer,onStageRef:stageRef,
    });
  }
  if (['workbench','candidates','delivery'].includes(state.view)) {
    const view=state.view,project=state.project;
    await creativeWorkbench.load({projectId: project, objectId: state.object, userId: state.actor || 'reader', task:view,fixedRef:currentEntry().get('object'),fixedRenderId:currentEntry().get('render')});
  }
}
function productionContext() {
  return {api,session:()=>({actor:state.actor,csrf:state.csrf,writable:state.writable,revision:state.revision}),setRevision:value=>{state.revision=value;},onNotice:notice,createReviewer:loadObjectReviewer,onStageRef:stageRef,
    onMedia:openMedia,onArtifact:async id=>{await switchView('artifacts');await openArtifact(id);},
    onObject:async id=>{state.view='workbench';await selectObject(id);},
    onReference:()=>{$('upload-dialog').showModal();},onLocalAction:openLocalProduction,
    onScript:async scope=>{const project=state.project;if(scope){const relation=await api(`${base()}/workbench?section=children&object_id=${encodeURIComponent(scope)}&limit=1`);if(project!==state.project)return;for(const ancestor of relation.ancestors || [])state.expandedNodes.add(ancestor.id);}state.object=scope || null;await selectProject(project);if(project!==state.project)return;await switchView('script');const select=$('script-view').querySelector('.script-scope');if(select && select.value!==(scope || '')){select.value=scope || '';select.dispatchEvent(new Event('change',{bubbles:true}));}}};
}
async function loadSourceIntake() {
  if(!state.project || state.view!=='source')return;
  if(!sourceIntake){const {createSourceIntake}=await import('./source-intake.js');if(!sourceIntake)sourceIntake=createSourceIntake($('source-view'),productionContext());}
  if(state.view==='source')await sourceIntake.load({projectId:state.project,objectId:state.object,fixedRef:currentEntry().get('object')});
}
async function loadResourceModel(mode) {
  if(!state.project || state.view!==mode)return;
  if(mode==='designs'&&!designWorkspace){const {createResourceModel}=await import('./resource-model.js');if(!designWorkspace)designWorkspace=createResourceModel($('design-view'),productionContext(),{mode:'designs'});}
  if(mode==='library'&&!resourceLibrary){const {createResourceModel}=await import('./resource-model.js');if(!resourceLibrary)resourceLibrary=createResourceModel($('asset-library-view'),productionContext());}
  if(state.view===mode)await(mode==='designs'?designWorkspace:resourceLibrary).load({projectId:state.project,objectId:state.object,fixedRef:currentEntry().get('object')});
}
async function loadScriptWorkspace() {
  if (!state.project || state.view !== 'script') return;
  if(state.projectRows.get(state.project)?.storage_policy!=='postgres-series-v1'){
    const button=el('button','',msg("ui.read_existing_screenplay_versions"));button.addEventListener('click',guard(()=>switchView('artifacts')));
    $('script-view').replaceChildren(el('p','hint',msg("ui.this_project_is_read_only_under_its_original_storage")),button);return;
  }
  if (!scriptWorkspace) {
    const {createScriptWorkspace} = await import('./script-workspace.js');
    scriptWorkspace = createScriptWorkspace($('script-view'), {
      api, baseUrl: base, onNotice: notice,
      session: () => ({actor: state.actor, csrf: state.csrf, writable: state.writable, revision: state.revision}),
      setRevision: value => { state.revision = value; },
      onScope:value=>{state.object=value || null;syncRoute();},
      onBack:()=>switchView('project'),
    });
  }
  if (state.view === 'script') await scriptWorkspace.load({projectId: state.project,objectId:state.object,lineId:entry.get('line')});
}
async function selectObject(id) {
  if (state.object !== id) resetArtifactReader();
  state.object = id; state.offset = 0;
  const lookup = new Map(state.treeNodes.map(row => [row.id, row]));
  if(state.view==='editing'){let node=lookup.get(id);const seen=new Set();while(node&&node.kind!=='episode'&&!seen.has(node.id)){seen.add(node.id);node=lookup.get(node.parent_id);}episodeScope=node?.kind==='episode'?node.id:null;}
  let parent = lookup.get(id)?.parent_id; const visited = new Set();
  while (parent && !visited.has(parent)) { visited.add(parent); state.expandedNodes.add(parent); parent = lookup.get(parent)?.parent_id; }
  if(state.treeMode==='paged')$('tree').querySelectorAll('.tree-item').forEach(control=>{const selected=control.dataset.id===id;control.classList.toggle('active',selected);if(selected)control.setAttribute('aria-current','true');else control.removeAttribute('aria-current');});
  else renderTree(state.treeNodes);
  await switchView(state.view);
}
async function loadCanvas(focus = null) {
  if (!state.project || state.view !== 'canvas') return;
  if (!resourceCanvas) {
    const {createResourceCanvas} = await import('./canvas.js');
    if (!resourceCanvas) resourceCanvas = createResourceCanvas($('resource-canvas'), {
      onSelect: guard(async node => {
        if (node.kind === 'media') await openMedia(node.entity_id);
        else if (['artifact','artifact_version'].includes(node.kind)) { await switchView('artifacts'); await openArtifact(node.entity_id); }
        else if (node.kind === 'object') { state.view = 'workbench'; await selectObject(node.entity_id); }
      }),onScope:id=>{if(state.object!==id)resetArtifactReader();state.object=id;state.offset=0;$('tree').querySelectorAll('.tree-item').forEach(b=>{const chosen=b.dataset.id===id;b.classList.toggle('active',chosen);if(chosen)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');});},
      onCollection:guard(async section=>{await switchView('workbench');await creativeWorkbench.focus(section);}),onError: error => notice(error.message || String(error)),
    });
  }
  if (state.view === 'canvas') await resourceCanvas.load({projectId: state.project, objectId: state.object, userId: state.actor || 'reader', focus,overview:!state.object&&!focus});
}
async function switchView(view, focus = null) {
  if(view==='production'){const node=state.treeNodes.find(r=>r.id===state.object);if(episodeScope&&node?.kind!=='episode')state.object=episodeScope;else if(node?.kind==='episode')episodeScope=node.id;}
  if(!platformViews.includes(view))productionPlatform?.suspend();
  if(view!=='creative-canvas'){creativeCanvasPanel?.suspend();customViewRequest++;}
  editWorkspace?.suspend?.();
  if(view!=='classic-production')classicProduction?.suspend();
  if(!['intelligent-creation','intelligent-storyboard'].includes(view))intelligentProduction?.suspend();
  if(!['blocking','previs'].includes(view))spatialScenePanel?.suspend();
  if(view!=='creative-tools')creativeTools?.suspend();
  if(view!=='text-tools')textTools?.suspend();
  if(view!=='media-imports')mediaImports?.suspend();
  if(!['access','access-share'].includes(view))accessControl?.suspend();
  if(view!=='team-review')teamReview?.suspend();
  if(view!=='commerce')commerce?.suspend();
  if(view!=='service-operations')serviceOperations?.suspend();
  if(view!=='community')community?.suspend();
  if(view!=='project-management')projectManagement?.suspend();
  if(view!=='asset-center')assetCenter?.suspend();
  const platform=platformViews.includes(view),custom=customViews.includes(view);
  const skip=document.querySelectorAll('.skip-link')[0];if(skip)skip.href=platform?'#production-platform':'#assisted-desk';
  $('project-management-view').hidden=view!=='project-management';$('community-view').hidden=view!=='community';
  $('production-platform').hidden=!platform;$('creative-canvas-view').hidden=view!=='creative-canvas';$('edit-workspace-view').hidden=view!=='editing';$('classic-production-view').hidden=view!=='classic-production';$('intelligent-production-view').hidden=!['intelligent-creation','intelligent-storyboard'].includes(view);
  $('spatial-scene-view').hidden=!['blocking','previs'].includes(view);$('creative-tools-view').hidden=view!=='creative-tools';$('text-tools-view').hidden=view!=='text-tools';$('media-imports-view').hidden=view!=='media-imports';$('access-control-view').hidden=!['access','access-share'].includes(view);$('team-review-view').hidden=view!=='team-review';$('commerce-view').hidden=view!=='commerce';$('service-operations-view').hidden=view!=='service-operations';$('asset-center-view').hidden=view!=='asset-center';
  document.querySelectorAll('.layout').forEach(n=>n.classList.toggle('platform-mode',platform));
  if(!['workbench','candidates','delivery'].includes(view))creativeWorkbench?.suspend?.();
  state.view = view;
  updateShell(view);
  loadTaskNotifications().catch(error=>notice(error.message));
  if(view!=='collection')sharedLibrary?.suspend();
  const assisted=mainViews.includes(view);
  if(assisted||platform||['intelligent-creation','intelligent-storyboard','asset-center','project-management','community'].includes(view))state.primary=view;else assistedDesk?.suspend();
  $('assisted-desk').hidden=!assisted;
  $('specialist-tabs').hidden=assisted||platform||custom;$('specialist-heading').hidden=assisted||platform||custom;
  document.querySelectorAll('.workspace').forEach(node=>node.classList.toggle('assisted-mode',assisted||platform||custom));
  document.querySelectorAll('.workspace').forEach(node=>node.classList.toggle('object-production',['workbench','candidates','delivery','designs','library'].includes(view)));
  if($('specialist-tools'))$('specialist-tools').open=false;
  for(const key of navViews){const link=$(`nav-${key}`);if(!link)continue;link.href='?'+new URLSearchParams({page:key,...(!['home','projects','asset-center','project-management'].includes(key)&&state.project?{project:state.project}:{}),...(!['home','projects','asset-center','project-management'].includes(key)&&state.object?{scope:state.object}:{})});if(key===state.primary || key==='projects'&&['project','production'].includes(state.primary))link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  if(!assisted)syncRoute();
  if(view!=='source')sourceIntake?.suspend();if(view!=='designs')designWorkspace?.suspend();if(view!=='library')resourceLibrary?.suspend();
  document.querySelectorAll('.workspace').forEach(node=>{node.classList.toggle('reading-artifacts',view==='artifacts');node.classList.toggle('reading-production',['source','designs','library'].includes(view));});
  const views=[['source','source-view'],['script','script-view'],['designs','design-view'],['library','asset-library-view'],['candidates','creative-workbench'],['delivery','creative-workbench'],['workbench','creative-workbench'],['media','media-view'],['artifacts','artifact-view'],['canvas','resource-canvas']];
  const active=views.find(([tab])=>tab===view)?.[1];
  for(const target of new Set(views.map(([,target])=>target)))$(target).hidden=target!==active;
  for(const [tab,target]of views){$(`tab-${tab}`).setAttribute('aria-selected',String(tab===view));$(`tab-${tab}`).setAttribute('aria-controls',target);}
  if(platform)await loadProductionPlatform();
  else if(custom)await loadCustomView(view);
  else if (assisted) await loadAssistedDesk();
  else if (view === 'canvas') await loadCanvas(focus);
  else if (['workbench','candidates','delivery'].includes(view)) await loadWorkbench();
  else if(view==='source')await loadSourceIntake();
  else if(view==='designs'||view==='library')await loadResourceModel(view);
  else if (view === 'script') await loadScriptWorkspace();
  else if (view === 'media') await loadResources();
  else if (view === 'artifacts') await loadArtifacts();
}
function syncRoute(){
  if(typeof window==='undefined'||restoringDeskRoute)return;
  const previous=currentEntry(),route=new URLSearchParams({page:state.view});if(state.project)route.set('project',state.project);if(state.object)route.set('scope',state.object);if(episodeScope)route.set('episode',episodeScope);
  if(previous.get('page')===state.view&&(previous.get('project')||null)===(state.project||null)){for(const key of ['task_target','tool','kind','create','tab','mode','canvas_origin','task_id','task_kind','auth_result','auth_status'])if(previous.get(key))route.set(key,previous.get(key));if((previous.get('scope')||null)===(state.object||null))for(const key of ['object','version','render','line'])if(previous.get(key))route.set(key,previous.get(key));}
  const link='?'+route;if(window.location.search!==link)window.history[deskRouteReady?'pushState':'replaceState'](null,'',link);deskRouteReady=true;
}
async function openResourceSettings() {
  if (!resourceSettings) {
    const {createResourceSettings} = await import('./resource-settings.js');
    resourceSettings = createResourceSettings($('resource-settings-dialog'), {api, session:()=>({actor:state.actor,csrf:state.csrf}), onNotice:notice});
  }
  await resourceSettings.open();
}
async function openRoleMemory() {
  if (!roleMemory) {
    const {createRoleMemory} = await import('./role-memory.js');
    roleMemory = createRoleMemory($('role-memory-dialog'), {api,session:()=>({actor:state.actor,csrf:state.csrf}),
      project:()=>state.project,onRevision:value=>{state.revision=value;},onOpenArtifact:id=>guard(()=>openArtifact(id))()});
  }
  await roleMemory.open();
}
async function loadScope() {
  await switchView(state.view);
}

async function loadProjects() {
  const data = await api('/api/v1/projects');
  state.projectRows=new Map(data.items.map(row=>[row.id,row]));
  renderRecentProjects(data.items);
  $('projects').replaceChildren();
  for (const project of data.items) {
    const option = el('option', '', project.name + (project.unavailable ? ' · 权威不可用' : ''));
    option.value = project.id; $('projects').append(option);
  }
  if (!data.items.length) { state.project=null;state.writable=false;$('projects').append(el('option', '', msg("ui.no_registered_projects"))); await switchView(['home','projects','collection','access','access-share','asset-center','project-management','text-tools','creative-tools'].includes(state.view)?state.view:'projects');return; }
  if (state.project && data.items.some(row => row.id === state.project)) $('projects').value = state.project;
  if(['text-tools','creative-tools'].includes(state.view)&&!state.project){$('projects').prepend(localizedOption('',msg("ui.standalone_tools_no_film_project_selected")));$('projects').value='';await switchView(state.view);syncRoute();return;}
  if(['home','projects','collection','project-management','asset-center'].includes(state.view)){await switchView(state.view);syncRoute();return;}
  await selectProject($('projects').value);
}
async function selectProject(id,{scope}={}) {
  editWorkspace?.suspend?.();
  if(!id){state.project=null;state.object=null;await switchView(state.view);return;}
  if (state.project !== id) {
    productionPlatform?.suspend();creativeCanvasPanel?.suspend();classicProduction?.suspend();spatialScenePanel?.suspend();creativeTools?.suspend();textTools?.suspend();mediaImports?.suspend();accessControl?.suspend();teamReview?.suspend();commerce?.suspend();assetCenter?.suspend();serviceOperations?.suspend();community?.suspend();intelligentProduction?.suspend();projectManagement?.suspend();episodeScope=currentEntry().get('project')===id?currentEntry().get('episode'):null;
    assistedDesk?.suspend();
    sourceIntake?.suspend();designWorkspace?.suspend();resourceLibrary?.suspend();
    state.expandedNodes.clear(); state.object = null; resourceCanvas?.load({projectId:null,userId:state.actor || 'reader'}); creativeWorkbench?.load({projectId:null,userId:state.actor || 'reader'});
    state.mediaRequest++;resetArtifactReader();state.compareRequest++;$('media-dialog').close();$('compare-dialog').close();
  }
  if(scope!==undefined)state.object=scope;
  state.project = id; state.offset = 0; state.resourceRequest++; state.artifactRequest++; state.comparisons.clear(); updateCompare();
  const request = ++state.treeRequest;
  const paged=state.projectRows.get(id)?.storage_policy==='postgres-series-v1';
  const data = await api(paged?`${base()}/workbench?section=children&limit=60`:`${base()}/tree`);
  if (request !== state.treeRequest || state.project !== id) return;
  const project = (paged?state.projectRows.get(id):data.project) || {}; document.querySelector('.structure').hidden=project.profile==='vsc.creative-tools'||project.profile_id==='vsc.creative-tools'||project.profile_snapshot?.workspace_kind==='creative-tools'; state.revision = data.revision ?? project.revision ?? 0;
  state.writable=state.writeAvailable && project.storage_policy==='postgres-series-v1' && !project.read_only; $('upload-open').disabled=!(state.writable && state.actor);
  $('project-meta').replaceChildren(el('p', 'hint', !state.writeAvailable ? msg("ui.this_service_is_read_only_you_can_review_existing") : project.read_only ? msg("ui.this_project_is_read_only_you_can_review_existing") : msg("ui.project_content_is_shared_decisions_retain_records")));
  const selected = (data.nodes || []).find(node => node.id === state.object);
  if (!paged && !selected) { if(state.object!==null)resetArtifactReader();state.object = null; state.offset = 0; }
  state.treeMode=paged?'paged':'legacy';state.treeNodes = data.nodes || [];
  if(paged)renderPagedTree(data,id,request);else renderTree(state.treeNodes);
  if (data.gaps?.length) notice(data.gaps.join('\n'));
  await loadScope();
}
function renderPagedTree(data,projectId,treeTicket){
  const nav=$('tree');nav.replaceChildren();const root=el('ul','tree-roots');nav.append(root);
  const alive=()=>state.project===projectId&&state.treeRequest===treeTicket;
  function appendPage(page,container,parentId=null){
    const value=page.sections?.children || {items:[]};
    for(const node of value.items){
      if(!state.treeNodes.some(row=>row.id===node.id))state.treeNodes.push(node);
      const item=el('li','tree-node'),row=el('div','tree-row'),b=el('button','tree-item');b.type='button';b.dataset.id=node.id;
      b.classList.toggle('active',state.object===node.id);if(state.object===node.id)b.setAttribute('aria-current','true');
      b.append(el('span','tree-kind',names[node.kind]||node.kind),el('span','',node.title||node.display_code||node.id));
      b.addEventListener('click',guard(()=>selectObject(node.id)));row.append(b);item.append(row);container.append(item);
      if(['work','episode','scene','sequence'].includes(node.kind)){
        const toggle=el('button','tree-toggle','▸'),group=el('ul','tree-children');toggle.type='button';group.id='tree-children-'+encodeURIComponent(node.id);group.hidden=true;
        toggle.setAttribute('aria-controls',group.id);toggle.setAttribute('aria-expanded','false');bindAttribute(toggle,'aria-label',msg("ui.expand_value0",{value0:node.title||node.id}));
        row.replaceChildren(toggle,b);item.append(group);let loaded=false,loading=false;
        const expand=async expanded=>{group.hidden=!expanded;setText(toggle,expanded?'▾':'▸');toggle.setAttribute('aria-expanded',String(expanded));bindAttribute(toggle,'aria-label',(expanded?'收拢 ':'展开 ')+(node.title||node.id));if(expanded)state.expandedNodes.add(node.id);else state.expandedNodes.delete(node.id);if(expanded&&!loaded&&!loading){loading=true;group.replaceChildren(el('li','hint',msg("ui.loading_child_items")));try{const value=await api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?`+new URLSearchParams({section:'children',object_id:node.id,limit:'60'}));if(!alive())return;group.replaceChildren();appendPage(value,group,node.id);loaded=true;}catch(error){if(alive())group.replaceChildren(el('li','hint',msg("ui.value0_collapse_and_expand_again_to_retry",{value0:error.message})));}finally{loading=false;}}};
        toggle.addEventListener('click',guard(()=>expand(group.hidden)));toggle.addEventListener('keydown',guard(async event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();await expand(event.key==='ArrowRight');}}));
        if(state.expandedNodes.has(node.id))expand(true);
      }else row.replaceChildren(el('span','tree-toggle-spacer'),b);
    }
    if(value.next_offset!=null){const li=el('li','tree-more'),more=el('button','',msg("ui.show_more_value0_value1_loaded",{value0:value.next_offset,value1:value.total}));more.type='button';more.addEventListener('click',guard(async()=>{more.disabled=true;try{const params=new URLSearchParams({section:'children',limit:'60',offset:String(value.next_offset),revision:String(page.revision)});if(parentId)params.set('object_id',parentId);const next=await api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?${params}`);if(!alive())return;li.remove();appendPage(next,container,parentId);}finally{more.disabled=false;}}));li.append(more);container.append(li);}
    if(!value.items.length)container.append(el('li','hint',msg("ui.no_child_items_are_registered_in_this_scope")));
  }
  appendPage(data,root);
}
function renderTree(nodes) {
  $('tree').replaceChildren();
  const lookup = new Map(nodes.map(node => [node.id, node]));
  const sorted = [...nodes].sort((a,b) => (a.ordinal || 0) - (b.ordinal || 0));
  const children = new Map();
  for (const node of sorted) {
    if (!children.has(node.parent_id)) children.set(node.parent_id, []);
    children.get(node.parent_id).push(node);
  }
  for (const id of state.expandedNodes) if (!lookup.has(id) || !children.has(id)) state.expandedNodes.delete(id);
  const visited = new Set();
  const roots = el('ul', 'tree-roots');
  function add(node, container) {
    if (visited.has(node.id)) return; visited.add(node.id);
    const item = el('li', 'tree-node');
    const row = el('div', 'tree-row');
    const branch = children.get(node.id) || [];
    const button = el('button', 'tree-item'); button.type = 'button'; button.dataset.id = node.id;
    button.classList.toggle('active', state.object === node.id);
    if (state.object === node.id) button.setAttribute('aria-current', 'true');
    button.setAttribute('aria-controls', 'creative-workbench resources artifacts');
    button.append(el('span', 'tree-kind', names[node.kind] || node.kind), el('span', '', node.title || node.display_code || node.id));
    button.addEventListener('click', guard(async () => {
      await selectObject(node.id);
    }));
    item.append(row);
    if (branch.length) {
      const group = el('ul', 'tree-children'); group.id = `tree-children-${encodeURIComponent(node.id)}`;
      const toggle = el('button', 'tree-toggle'); toggle.type = 'button'; toggle.dataset.id = node.id;
      toggle.setAttribute('aria-controls', group.id);
      let rendered = 0, moreItem = null;
      const renderMore = () => {
        if (moreItem) moreItem.remove();
        const end = Math.min(branch.length, rendered + 60);
        while (rendered < end) add(branch[rendered++], group);
        if (rendered < branch.length) { moreItem=el('li','tree-more');const moreButton=el('button','',msg("ui.show_value0_more_value1_remaining",{value0:Math.min(60,branch.length-rendered),value1:branch.length-rendered}));moreButton.type='button';moreButton.addEventListener('click',renderMore);moreItem.append(moreButton);group.append(moreItem); }
      };
      const setExpanded = (expanded) => {
        if (expanded) state.expandedNodes.add(node.id); else state.expandedNodes.delete(node.id);
        group.hidden = !expanded;
        toggle.setAttribute('aria-expanded', String(expanded));
        bindAttribute(toggle,'aria-label',joinMessages(["",expanded ? msg("ui.collapse") : msg("common.expand")," ",node.title || node.display_code || node.id,""]));
        setText(toggle,expanded ? '▾' : '▸');
        if (expanded && !rendered) renderMore();
      };
      setExpanded(state.expandedNodes.has(node.id));
      toggle.addEventListener('click', () => setExpanded(!state.expandedNodes.has(node.id)));
      toggle.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
          event.preventDefault(); setExpanded(event.key === 'ArrowRight');
        }
      });
      row.append(toggle, button); item.append(group);
    } else {
      const spacer = el('span', 'tree-toggle-spacer'); spacer.setAttribute('aria-hidden', 'true');
      row.append(spacer, button);
    }
    container.append(item);
  }
  const rootNodes=sorted.filter(row=>!row.parent_id||!lookup.has(row.parent_id));let rootCount=0,moreRoots=null;
  const addRoots=()=>{if(moreRoots)moreRoots.remove();const end=Math.min(rootNodes.length,rootCount+60);while(rootCount<end)add(rootNodes[rootCount++],roots);if(rootCount<rootNodes.length){moreRoots=el('li','tree-more');const moreButton=el('button','',msg("ui.more_top_level_scopes_value0_remaining",{value0:rootNodes.length-rootCount}));moreButton.addEventListener('click',addRoots);moreRoots.append(moreButton);roots.append(moreRoots);}};
  addRoots();
  if (nodes.length) $('tree').append(roots);
  else $('tree').append(el('p', 'hint', msg("ui.no_work_episode_scene_sequence_or_shot_hierarchy_exists")));
}
async function loadResources() {
  const request=++state.resourceRequest, project=state.project, object=state.object;
  const params = new URLSearchParams({offset: state.offset, limit: state.limit});
  for (const key of ['modality','registration','query','role','status']) if ($(key).value) params.set(key, $(key).value);
  if (state.object) params.set('object_id', state.object);
  const data = await api(`${base()}/media?${params}`); if(request!==state.resourceRequest || project!==state.project || object!==state.object)return; state.total = data.total; state.revision = data.revision ?? state.revision;
  $('resources').replaceChildren();
  for (const media of data.items) $('resources').append(resourceCard(media));
  if (!data.items.length) $('resources').append(el('p', 'empty', msg("ui.no_media_is_linked_to_this_scope_select_all")));
  setText($('resource-summary'),msg("ui.value0_items_value1_on_this_page_unregistered_files_are",{value0:data.total,value1:data.items.length}));
  setText($('page-info'),joinMessages(["",data.total ? state.offset+1 : 0,"–",Math.min(state.offset+state.limit,data.total)," / ",data.total,""]));
  $('previous').disabled = state.offset === 0; $('next').disabled = state.offset+state.limit >= data.total;
}
function resourceCard(media) {
  const card = el('article', 'resource-card'); const thumb = el('button', 'thumbnail'); bindAttribute(thumb,'aria-label',msg("ui.view_value0",{value0:media.name || media.id}));
  const thumbnailPurpose={image:'thumbnail',video:'poster',audio:'waveform',document:'document_pages'}[media.modality];
  if (hasRendition(media,thumbnailPurpose) && media.availability !== 'missing' && media.integrity !== 'mismatch') { const image = el('img'); image.loading = 'lazy'; bindAttribute(image,"alt",media.name || media.id); image.src = hasRendition(media,thumbnailPurpose)?previewUrl(media.id,thumbnailPurpose):mediaUrl(media.id); thumb.append(image); }
  else setText(thumb,({video: '▶', audio: '♪', text: '文', document: '▤'})[media.modality] || '▧');
  thumb.addEventListener('click', guard(() => openMedia(media.id)));
  const body = el('div', 'card-body'); body.append(el('div', 'card-name', media.name || media.id));
  const badges = el('div', 'badges'); badges.append(badge(media.modality), badge(media.registered === false ? '未登记' : '已登记', media.registered === false ? 'warning' : ''));
  if (media.availability && media.availability !== 'available') badges.append(badge(media.availability, 'danger'));
  if (media.integrity === 'mismatch') badges.append(badge('mismatch', 'danger'));
  if (media.deprecated) badges.append(badge('已停用', 'danger'));
  body.append(badges, el('div', 'hint', size(media.size_bytes)));
  const graphButton=el('button','card-graph',msg("ui.view_on_canvas"));graphButton.type='button';graphButton.addEventListener('click',guard(()=>switchView('canvas',`media:${media.id}`)));body.append(graphButton);
  const actions = el('div', 'card-actions'); const label = el('label'); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = state.comparisons.has(media.id);
  checkbox.addEventListener('change', () => { if (checkbox.checked) { if (state.comparisons.size >= 4) { checkbox.checked = false; notice(msg("ui.compare_up_to_four_candidates_side_by_side")); return; } state.comparisons.set(media.id,media); } else state.comparisons.delete(media.id); updateCompare(); });
  label.append(checkbox,document.createTextNode('比较')); const detail = el('button', '', msg("ui.details")); detail.addEventListener('click', guard(() => openMedia(media.id))); actions.append(label,detail); body.append(actions); card.append(thumb,body); return card;
}
async function player(media) {
  const wrapper = el('div'); const source = mediaUrl(media.id);
  if (['missing','blocked','unavailable'].includes(media.availability) || media.integrity === 'mismatch') { wrapper.append(el('p','empty',msg("ui.preview_unavailable_missing_bytes_changed_checksum_missing_storage_configuration"))); return wrapper; }
  if (['image','audio','video'].includes(media.modality)) {
    const node = el(media.modality === 'image' ? 'img' : media.modality, 'media-player'); node.src = source;
    if(media.modality==='video' && hasRendition(media,'poster'))node.poster=previewUrl(media.id,'poster');
    if(media.modality==='video' && hasRendition(media,'proxy_video'))node.src=previewUrl(media.id,'proxy_video');
    if (media.modality === 'image') { bindAttribute(node,"alt",media.name || media.id); node.classList.add('zoomable'); node.addEventListener('click', () => node.classList.toggle('zoomed')); }
    else { node.controls = true; node.preload = 'metadata'; }
    wrapper.append(node);
    if (media.modality === 'audio') {
      if(hasRendition(media,'waveform')){const image=el('img','media-player');bindAttribute(image,"alt",msg("ui.stored_audio_waveform_preview"));image.src=previewUrl(media.id,'waveform');wrapper.append(image);}
      const button = el('button','',msg("ui.show_audio_waveform")); button.addEventListener('click', guard(async () => { button.disabled = true; const response = await fetch(source); if (!response.ok) throw new Error('读取音频失败'); const bytes = await response.arrayBuffer(); const context = new AudioContext(); try { const audio = await context.decodeAudioData(bytes); const canvas = el('canvas','waveform'); canvas.width=900; canvas.height=90; const ctx=canvas.getContext('2d'); const samples=audio.getChannelData(0); const step=Math.ceil(samples.length/canvas.width); ctx.strokeStyle='#17625a'; for(let x=0;x<canvas.width;x++){let peak=0;for(let j=x*step;j<Math.min((x+1)*step,samples.length);j++)peak=Math.max(peak,Math.abs(samples[j]));ctx.beginPath();ctx.moveTo(x,45-peak*42);ctx.lineTo(x,45+peak*42);ctx.stroke();}wrapper.append(canvas,el('p','hint',msg("ui.the_browser_draws_this_waveform_from_the_current_bytes"))); } finally { await context.close(); button.disabled=false; }})); wrapper.append(button);
    }
  } else if (media.modality === 'text') { const response=await fetch(source,{headers:{Range:'bytes=0-1048575'}}); if(!response.ok) throw new Error('读取文本失败'); const content=await response.text(); const range=response.headers.get('content-range'); const truncated=range && Number(range.split('/')[1])>1048576; wrapper.append(el('pre','readable',content+(truncated?'\n［正文过长，当前仅展示前 1 MiB，可下载完整文件。］':''))); }
  else if(hasRendition(media,'document_pages')){const image=el('img','media-player');bindAttribute(image,"alt",msg("ui.stored_first_page_document_preview"));image.src=previewUrl(media.id,'document_pages');wrapper.append(image);}
  else wrapper.append(el('p','hint',msg("ui.no_preview_is_available_for_this_format_download_the")));
  return wrapper;
}
async function openMedia(id) {
  const project=state.project, request=++state.mediaRequest, root=base();
  const [media,lineage,usage] = await Promise.all([api(`${root}/media/${encodeURIComponent(id)}`),api(`${root}/media/${encodeURIComponent(id)}/lineage`),api(`${root}/media/${encodeURIComponent(id)}/usage`)]);
  if(project!==state.project || request!==state.mediaRequest)return;
  if(usage.candidates)media.candidates=(media.candidates || []).map(candidate=>({...candidate,...usage.candidates.find(row=>row.id===candidate.id)}));
  media.trial_sources=usage.trial_sources || [];
  if(media.trial_sources.length){const versions=await api(`${root}/artifacts`);if(project!==state.project || request!==state.mediaRequest)return;media.trial_animatics=(versions.items || versions || []).filter(row=>['animatic','vsc.animatic'].includes(row.type || row.artifact_type) && (row.approved===true || row.status==='approved'));}
  state.revision=media.revision ?? state.revision;
  const playback=await player(media); if(project!==state.project || request!==state.mediaRequest)return;
  setText($('media-title'),media.name || media.id); $('media-detail').replaceChildren(playback);
  if(media.review_history){const {renderReviewHistory,createArtifactReviewForm}=await import('./review.js');if(project!==state.project || request!==state.mediaRequest)return;const alive=()=>project===state.project && request===state.mediaRequest,context=reviewContext(project,alive,async()=>{$('media-dialog').close();await openMedia(media.id);});context.currentTime=()=>$('media-detail').querySelector('video,audio')?.currentTime || 0;$('media-detail').append(renderReviewHistory(media.review_history,context));if(state.actor && media.review_targets?.length)$('media-detail').append(createArtifactReviewForm(media.review_targets,context));}
  if(state.actor && state.writable && media.registered!==false)$('media-detail').append(reviewForm(media));
  if(state.actor && state.writable && media.registered!==false){const publish=el('details','media-library-publish');publish.append(el('summary','',msg("ui.publish_to_shared_library")));const body=el('div');publish.append(body);let ready=false;publish.addEventListener('toggle',guard(async()=>{if(publish.open&&!ready){ready=true;(await libraryController()).publish(body,media,project);}}));$('media-detail').append(publish);}
  const evidence=el('details','media-evidence');evidence.append(el('summary','',msg("ui.media_specifications_sources_and_checks")));
  const download=el('a','',msg("ui.download_original"));download.href=mediaUrl(id)+'?download=true';evidence.append(download);
  const panels=el('div','detail-grid');panels.append(facts('规格与可用性',{id:media.id,modality:media.modality,sha256:media.sha256,size_bytes:media.size_bytes,width:media.width,height:media.height,duration_ms:media.duration_ms,sample_rate:media.sample_rate,availability:media.availability,integrity:media.integrity,rights:media.rights,deprecated:media.deprecated}),lineagePanel(media,lineage),facts('用途与下游引用',usage),facts('审查与决定',{checks:media.checks || [],reviews:media.reviews || [],decisions:media.decisions || [],bindings:media.bindings || []}));evidence.append(panels);
  if(state.actor && state.writable && media.registered!==false)evidence.append(previewForm(media),bindingForm(media),mediaAuditForm(media));
  let previewLoaded=false,previewLoading=false;evidence.addEventListener('toggle',guard(async()=>{if(!evidence.open||previewLoaded||previewLoading||!state.writable||project!==state.project||request!==state.mediaRequest)return;previewLoading=true;try{const jobs=await api(`${root}/preview-jobs?media_id=${encodeURIComponent(media.id)}`);if(project!==state.project||request!==state.mediaRequest)return;const panel=facts('持久预览任务',jobs);if(state.actor)for(const job of jobs.items || [])if(job.status==='failed'){const button=el('button','',msg("ui.explicitly_retry_value0",{value0:job.purpose}));button.addEventListener('click',guard(async()=>{if(project!==state.project||request!==state.mediaRequest)return;const result=await api(`${root}/preview-retries`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{job_id:job.id},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});if(project!==state.project||request!==state.mediaRequest)return;state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);}));panel.append(button);}evidence.append(panel);previewLoaded=true;}finally{previewLoading=false;}}));
  $('media-detail').append(evidence);
  $('media-dialog').showModal();
}
function reviewForm(media,{alive=()=>true,onChanged=null}={}) {
  const project=state.project,root=base(),current=()=>alive()&&project===state.project;
  const form=el('form','review-form'); const field=el('fieldset'); field.append(el('legend','',msg("ui.human_review_and_use_decisions")));
  const candidate=el('select');bindAttribute(candidate,'aria-label',msg("ui.use_candidates_for_current_media"));const candidates=media.candidates || media.bindings || []; for(const item of candidates){const option=el('option','',joinMessages(["",names[item.role] || item.role || msg("ui.candidate"),"",item.target_title?joinMessages([" · ",item.target_title]):'',"",item.selected?msg("ui.currently_selected"):'',""]));option.value=item.candidate_id || item.id;candidate.append(option);}
  if(!candidates.length){field.append(el('p','hint',msg("ui.this_media_has_no_proposed_use_yet_propose_a")));form.append(field);return form;}
  const action=el('select'); for(const [value,label] of [['reviews',msg("ui.record_review_opinion")],['binding-decisions',msg("ui.select_this_candidate")],['binding-rejections',msg("ui.reject_this_candidate")],['binding-retirements',msg("ui.retire_current_role")]]){const option=el('option','',label);option.value=value;action.append(option);}
  const outcome=el('select'); for(const [value,label] of [['pass',msg("common.passed")],['needs_changes',msg("ui.changes_needed")],['fail',msg("ui.not_passed")]]){const option=el('option','',label);option.value=value;outcome.append(option);}
  bindAttribute(action,'aria-label',msg("ui.use_decision"));bindAttribute(outcome,'aria-label',msg("ui.review_outcome"));
  const reason=el('textarea');bindAttribute(reason,"placeholder",media.trial_sources?.length?msg("ui.explain_why_the_sample_suits_the_formal_purpose_or"):msg("ui.explain_purpose_continuity_reading_or_decision_evidence"));reason.required=true;
  bindAttribute(reason,'aria-label',msg("ui.use_decision_and_review_explanation"));
  const adoption=el('div');adoption.hidden=true;const animatic=el('select');bindAttribute(animatic,'aria-label',msg("ui.animatic_version_for_formal_trial_adoption"));const empty=el('option','',msg("ui.select_an_approved_animatic_required_only_for_formal_adoption"));empty.value='';animatic.append(empty);for(const row of media.trial_animatics || []){const opt=el('option','',joinMessages(["",row.name || row.artifact_key || msg("ui.previs")," · ",row.id,""]));opt.value=row.id;animatic.append(opt);}if(media.trial_sources?.length){adoption.append(el('p','hint',msg("ui.this_media_derives_from_a_trial_for_formal_editing")),animatic);action.addEventListener('change',()=>{adoption.hidden=action.value!=='binding-decisions';});}
  const label=el('label');const check=el('input');check.type='checkbox';label.append(check,document.createTextNode('我确认这是本人对当前用途作出的决定'));
  const button=el('button','',msg("common.submit"));button.type='submit';field.append(candidate,action,outcome,reason,adoption,label,button);form.append(field);
  let command=null;form.addEventListener('input',()=>{command=null;});form.addEventListener('change',()=>{command=null;});
  form.addEventListener('submit',guard(async event=>{event.preventDefault();if(!current())throw new Error('所见对象已切换，请返回原处继续。');const choice=candidates.find(row=>(row.candidate_id || row.id)===candidate.value);let payload={candidate_id:candidate.value,reason:reason.value};if(action.value==='binding-decisions' && animatic.value)payload.trial_adoption={reason:reason.value,animatic_version_id:animatic.value};if(action.value==='reviews')payload={...payload,outcome:outcome.value,reviewer_type:'human',criteria_version:'panel-human-v1'};if(action.value==='binding-retirements')payload={slot_id:choice.slot_id,reason:reason.value};command ||= crypto.randomUUID();button.disabled=true;try{const result=await api(`${root}/${action.value}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,confirmed:check.checked,expected_revision:state.revision,idempotency_key:command})});if(!current())return;state.revision=result.revision ?? state.revision;if(onChanged)await onChanged();else{$('media-dialog').close();await loadResources();}notice(msg("ui.action_recorded_version_and_decision_history_preserved"));}finally{if(current())button.disabled=false;}}));
  return form;
}
function bindingForm(media) {
  const form=el('form','review-form'); const field=el('fieldset');field.append(el('legend','',msg("ui.propose_a_use")));
  const target=el('input');bindAttribute(target,"placeholder",msg("ui.target_object_id_from_structure_navigation"));target.value=state.object || '';target.required=true;
  const role=el('select');for(const value of ['identity_face','costume','location_master','location_view','composition','first_frame','last_frame','prop','video_take','vfx_overlay','dialogue_dry','voice_sample','ambience','music','sfx','style_reference']){if(value==='vfx_overlay'&&media.modality!=='image')continue;const option=el('option','',names[value]||value);option.value=value;role.append(option);}
  const slot=el('input');slot.value='main';bindAttribute(slot,"placeholder",msg("ui.use_slot_key"));slot.required=true;
  const reason=el('textarea');bindAttribute(reason,"placeholder",msg("ui.explain_the_target_specification_and_basis_for_this_proposal"));reason.required=true;
  const button=el('button','',msg("ui.submit_proposed_use"));button.type='submit';field.append(target,role,slot,reason,button);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const result=await api(`${base()}/binding-candidates`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{media_id:media.id,target_object_id:target.value,role:role.value,slot_key:slot.value,reason:reason.value},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);}));return form;
}
function mediaAuditForm(media) {
  const form=el('form','review-form');const field=el('fieldset');field.append(el('legend','',msg("ui.media_checks_and_project_deactivation")));
  const action=el('select');for(const [value,label] of [['media-checks',msg("ui.record_evidence_of_checks_you_completed")],['media-lifecycle-decisions',msg("ui.disable_media_preserve_history_and_bytes")]]){const option=el('option','',label);option.value=value;action.append(option);}
  const outcome=el('select');for(const [value,label] of [['pass',msg("ui.check_passed")],['fail',msg("ui.check_failed")],['unknown',msg("ui.not_yet_determined")]]){const option=el('option','',label);option.value=value;outcome.append(option);}
  const reason=el('textarea');bindAttribute(reason,"placeholder",msg("ui.describe_the_actual_checks_observations_and_evidence_explain_the"));reason.required=true;
  const label=el('label');const confirm=el('input');confirm.type='checkbox';confirm.required=true;label.append(confirm,document.createTextNode('我确认本人已完成上述检查，或决定将此素材停止用于新的选择'));
  const submit=el('button','',msg("ui.record"));submit.type='submit';field.append(action,outcome,reason,label,submit);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const payload=action.value==='media-checks'?{media_id:media.id,blob_sha256:media.sha256,checker:`human:${state.actor}`,criteria_version:'panel-manual-v1',outcome:outcome.value,report:{reason:reason.value,method:'human_manual'}}:{media_id:media.id,reason:reason.value};const result=await api(`${base()}/${action.value}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,confirmed:confirm.checked,expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);notice(msg("ui.check_evidence_or_deactivation_decision_recorded_historical_references_preserved"));}));return form;
}
function previewForm(media) {
  const form=el('form','review-form');const field=el('fieldset');field.append(el('legend','',msg("ui.stored_preview_copy")));
  const available={image:['thumbnail'],video:['poster','proxy_video'],audio:['waveform'],document:media.mime_type==='application/pdf'?['document_pages']:[]}[media.modality] || [];
  const labels={thumbnail:'图片缩略图',poster:'视频首帧海报',proxy_video:'通用 H.264 代理视频',waveform:'音频波形',document_pages:'PDF 第一页'};
  const select=el('select');for(const purpose of available){const option=el('option','',labels[purpose]+(!state.previewCapabilities[purpose]?' · 转换器未安装':''));option.value=purpose;option.disabled=!state.previewCapabilities[purpose];select.append(option);}
  if(!available.some(purpose=>state.previewCapabilities[purpose])){field.append(el('p','hint',msg("ui.no_preview_converter_is_installed_for_this_format_metadata")));form.append(field);return form;}
  const button=el('button','',msg("ui.queue_preview"));button.type='submit';const refresh=el('button','',msg("ui.refresh_preview_status"));refresh.type='button';refresh.addEventListener('click',guard(async()=>{$('media-dialog').close();await openMedia(media.id);}));
  field.append(select,button,refresh,el('p','hint',msg("ui.a_persistent_local_worker_performs_resumable_conversion_preview_copies")));form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const result=await api(`${base()}/preview-jobs`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{media_id:media.id,purpose:select.value,recipe_version:state.previewCapabilities.recipe_version},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;notice(result.status==='failed'?msg("ui.this_preview_task_previously_failed_review_the_error_and"):result.status==='succeeded'?msg("ui.this_recipe_already_has_a_completed_preview_copy_refresh"):msg("ui.preview_task_durably_queued_waiting_for_the_local_worker"));}));return form;
}
function markArtifactSelection() {
  let selected = null;
  $('artifacts').querySelectorAll('.artifact-item').forEach(button=>{
    const active=button.dataset.id===state.selectedArtifact;
    button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    if(active){button.setAttribute('aria-current','true');selected=button;}else button.removeAttribute('aria-current');
  });
  if(selected)$('document').setAttribute('aria-labelledby',selected.id);
  else $('document').removeAttribute('aria-labelledby');
}
function resetArtifactReader() {
  state.documentRequest++;state.selectedArtifact=null;
  $('artifact-actions').replaceChildren();$('artifact-actions').hidden=true;
  $('artifacts').replaceChildren();
  $('artifacts').setAttribute('aria-busy','false');
  $('document').replaceChildren(el('p','empty',msg("ui.select_a_document_or_fixed_version_to_read")));
  bindAttribute($('document'),'aria-label',msg("ui.document_body"));$('document').setAttribute('aria-busy','false');
  $('document').removeAttribute('data-artifact-id');markArtifactSelection();
}
function artifactVersionLabel(artifact) {
  const status=artifact.status ? names[artifact.status] || artifact.status : artifact.approved===true ? '已批准' : '待决定';
  const version=artifact.version != null ? `v${artifact.version}` : '固定版本';
  const current=artifact.current===true ? ' · 当前版本' : artifact.current===false && (artifact.approved===true || artifact.status==='approved') ? ' · 历史版本' : '';
  return `${version} · ${status}${current}`;
}
async function loadArtifacts() {
  const request=++state.artifactRequest, project=state.project, object=state.object;
  const alive=()=>request===state.artifactRequest && project===state.project && object===state.object;
  $('artifacts').setAttribute('aria-busy','true');
  if(!$('artifacts').childElementCount)$('artifacts').append(el('p','empty',msg("ui.loading_document_versions")));
  try {
    const data=await api(`${base()}/artifacts${object ? '?object_id='+encodeURIComponent(object) : ''}`);
    if(!alive())return;
    const rows=Array.isArray(data) ? data : data.items || []; $('artifacts').replaceChildren();
    for(const artifact of [...rows].reverse()){
      const button=el('button','artifact-item'),title=el('span','artifact-title',artifactTitle(artifact));
      button.type='button';button.dataset.id=artifact.id;button.id='artifact-'+encodeURIComponent(artifact.id);
      button.setAttribute('aria-controls','document');button.append(title);
      button.append(el('small','artifact-state',artifactVersionLabel(artifact)));
      if(artifact.integrity==='mismatch' || artifact.availability==='missing')button.append(badge(artifact.integrity==='mismatch'?'mismatch':'missing','danger'));
      button.addEventListener('click',guard(event=>openArtifact(artifact.id,{focusFrom:event.detail===0?button:null})));$('artifacts').append(button);
    }
    if(!rows.length)$('artifacts').append(el('p','empty',msg("ui.no_document_versions_are_linked_to_this_scope")));
    markArtifactSelection();
  } catch(error) {
    if(!alive())return;
    const failure=el('section','artifact-list-error'),retry=el('button','',msg("ui.reload_document_versions"));
    retry.type='button';failure.setAttribute('role','status');
    failure.append(el('p','empty',msg("ui.document_version_could_not_be_loaded_value0",{value0:error.message})),retry);
    retry.addEventListener('click',guard(async()=>{if(!alive())return;retry.disabled=true;setText(retry,msg("ui.retrying"));await loadArtifacts();}));
    $('artifacts').replaceChildren(failure);markArtifactSelection();throw error;
  }
  finally { if(alive())$('artifacts').setAttribute('aria-busy','false'); }
}
async function openArtifact(id,{focusFrom=null}={}) {
  const project=state.project, object=state.object, request=++state.documentRequest;
  const alive=()=>project===state.project && object===state.object && request===state.documentRequest;
  state.selectedArtifact=id;markArtifactSelection();
  $('artifact-actions').replaceChildren();$('artifact-actions').hidden=true;
  $('document').replaceChildren(el('p','empty',msg("ui.loading_document")));
  $('document').setAttribute('aria-busy','true');$('document').removeAttribute('data-artifact-id');
  let artifact;
  try { artifact=await api(`${base()}/artifacts/${encodeURIComponent(id)}`); }
  catch(error) { if(alive()){$('document').replaceChildren(el('p','empty',msg("ui.the_document_could_not_be_loaded_select_this_version")));throw error;}return; }
  finally { if(alive())$('document').setAttribute('aria-busy','false'); }
  if(!alive())return;
  const content=artifact.content === null && artifact.document !== undefined ? artifact.document : artifact.content !== undefined ? artifact.content : artifact.document !== undefined ? artifact.document : '';
  // Legacy envelopes use null for unread file bytes; a JSON null document arrives as the string "null".
  const unavailable=content===null && artifact.availability != null;
  const {body,value:fixed,mediaKind}=unavailable ? {body:el('p','empty',artifact.size_bytes>16*1024*1024 ? msg("ui.the_text_exceeds_the_built_in_reader_limit_read") : msg("ui.text_was_not_loaded_check_that_the_source_file"))} : renderArtifactContent(content,{mimeType:artifact.mime_type});
  $('document').replaceChildren(body);bindAttribute($('document'),'aria-label',artifactTitle(artifact));
  if(mediaKind){const browse=el('button','',msg("ui.view_project_media"));browse.addEventListener('click',guard(()=>switchView('media')));$('document').append(browse);}
  $('document').setAttribute('data-artifact-id',id);$('document').scrollTop=0;
  const selected=[...$('artifacts').querySelectorAll('.artifact-item')].find(button=>button.dataset.id===id);
  if(selected){setText(selected.querySelector('.artifact-title'),artifactTitle(artifact));setText(selected.querySelector('.artifact-state'),artifactVersionLabel(artifact));}
  const actions=$('artifact-actions');
  bindAttribute(actions,'aria-label',msg("ui.value0_review_and_verification",{value0:artifactTitle(artifact)}));actions.hidden=false;
  const blocked=unavailable || artifact.integrity==='mismatch' || artifact.availability==='missing';
  const restriction=blocked ? '当前版本内容缺失或无法核验，请恢复固定内容后再审核。' :
    !state.writeAvailable ? '当前工作台为只读模式，审核尚未启用。可先核对版本内容。' :
    !state.writable || artifact.revision == null ? '此项目或版本只支持查阅，暂不能在工作台记录审核决定。' :
    !state.actor ? '登录实际操作人后，即可审核当前版本。' : '';
  if (restriction) actions.append(el('p','hint',restriction));
  if (state.writeAvailable && state.writable && !state.actor && !blocked) {
    const login=el('button','',msg("ui.sign_in_to_review"));
    login.addEventListener('click',()=>{if(alive())$('session-dialog').showModal();});actions.append(login);
  }
  if (!artifact.approved || ['resample','redo_sound'].includes(fixed?.local_action)) {
    const controls=el('section','artifact-decisions'),reason=el('input');bindAttribute(reason,"placeholder",msg("ui.review_reason"));bindAttribute(reason,'aria-label',msg("ui.version_decision_reason"));reason.name='artifact_decision_reason';reason.autocomplete='off';
    const execute=async(action,payload,key)=>{
      if(!alive())throw new Error('项目、范围或所见版本已切换，请重新读取');
      if(!state.writable)throw new Error('当前项目不允许写入审核决定');
      if(!state.actor)throw new Error('请先建立人工操作会话');
      const result=await api(`/api/v1/projects/${encodeURIComponent(project)}/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,expected_revision:artifact.revision,idempotency_key:key,confirmed:true})});
      if(project===state.project)state.revision=result.revision;
      if(alive()){
        if(action==='artifact-decisions')notice(joinMessages(["",artifactTitle(artifact),"",artifact.version != null ? joinMessages([" v",artifact.version]) : '',"：",payload.outcome==='reject'?msg("ui.return_decision_recorded"):msg("ui.approval_decision_recorded"),"。"]));
        await openArtifact(id);
      }return result;
    };
    if(!artifact.approved){
      if(!restriction)controls.append(reason);
      for(const [outcome,text] of [['approve',msg("ui.approve_displayed_version")],['reject',msg("ui.return_this_version")]]){
        const button=el('button',outcome==='approve'?'artifact-approve':'artifact-reject',text),key=crypto.randomUUID();
        button.disabled=!!restriction;
        button.addEventListener('click',guard(async()=>{if(!reason.value.trim())throw new Error('请填写决定理由');if(!confirm(`${text}？决定仅针对当前固定内容与范围。`))return;button.disabled=true;try{await execute('artifact-decisions',{artifact_id:id,outcome,reason:reason.value},key);}finally{button.disabled=false;}}));controls.append(button);
      }
    }else if(['resample','redo_sound'].includes(fixed?.local_action)){
      const button=el('button','',msg("ui.queue_the_approved_local_plan")),key=crypto.randomUUID();
      button.disabled=!!restriction;
      button.addEventListener('click',guard(async()=>{if(!confirm('仅将这个已批准方案的目标入队？实际调用仍由生成worker执行。'))return;button.disabled=true;try{const result=await execute('local-production-enqueue',{artifact_id:id},key);notice(msg("ui.registered_value0_fixed_tasks",{value0:result.jobs.length}));}finally{button.disabled=false;}}));controls.append(button);
    }
    actions.append(controls);
  }else actions.append(el('span','hint',msg("ui.this_fixed_version_is_approved")));
  const evidence=el('details','artifact-evidence');evidence.append(el('summary','',msg("ui.versions_and_verification")));
  evidence.append(el('p','hint',joinMessages(["",artifact.id," · ",artifact.version != null ? joinMessages(["v",artifact.version," · "]) : '',"",names[artifact.status] || artifact.status || (artifact.approved ? msg("ui.approved") : msg("ui.awaiting_decision"))," · ",names[artifact.integrity] || msg("ui.fixed_content"),""])));
  if(artifact.sha256)evidence.append(el('p','hint',msg("ui.content_digest_value0",{value0:artifact.sha256})));
  const lastDecision=artifact.decisions?.at(-1);
  if(lastDecision)evidence.append(el('p','hint',msg("ui.latest_decision_value0_reason_value1",{value0:lastDecision.outcome==='reject'?msg("ui.return"):lastDecision.outcome==='approve'?msg("ui.approve"):lastDecision.outcome,value1:lastDecision.reason || msg("ui.not_entered")})));
  $('document').append(evidence);
  const inspect=el('button','artifact-inspect',msg("ui.verify_version"));inspect.type='button';inspect.setAttribute('aria-controls','artifact-evidence');
  evidence.id='artifact-evidence';
  inspect.addEventListener('click',()=>{if(!alive())return;evidence.open=true;evidence.scrollIntoView?.({block:'nearest'});evidence.querySelector('summary').focus();});actions.append(inspect);
  if(artifact.review_history){const {renderReviewHistory,createArtifactReviewForm}=await import('./review.js');if(!alive())return;const context=reviewContext(project,alive,()=>openArtifact(id));$('document').append(renderReviewHistory(artifact.review_history,context));if(state.actor && artifact.review_targets?.length)$('document').append(createArtifactReviewForm(artifact.review_targets,context));}
  if(artifact.integrity==='mismatch')$('document').prepend(el('p','badge danger',msg("ui.this_version_s_checksum_has_changed_it_is_available")));
  if(artifact.availability==='missing')$('document').prepend(el('p','badge danger',msg("ui.the_fixed_version_is_missing_content_check_its_source")));
  if(focusFrom && document.activeElement===focusFrom && state.view==='artifacts' && alive())$('document').focus();
}
function updateCompare(){setText($('compare-count'),state.comparisons.size);}
$('compare-open').addEventListener('click',guard(async()=>{const project=state.project,ticket=++state.compareRequest,sections=[];for(const media of state.comparisons.values()){const section=el('section');section.append(el('h3','',media.name||media.id),await player(media),facts('用途与来源',{bindings:media.bindings||[],rights:media.rights,sha256:media.sha256}));if(project!==state.project||ticket!==state.compareRequest)return;sections.push(section);}if(project!==state.project||ticket!==state.compareRequest)return;$('compare-grid').replaceChildren(...sections);if(!sections.length)$('compare-grid').append(el('p','empty',msg("ui.first_select_candidates_to_compare_from_their_media_cards")));$('compare-dialog').showModal();}));
$('projects').addEventListener('change',guard(()=>changeProductionContext($('projects').value,undefined)));
$('production-project')?.addEventListener('change',guard(()=>changeProductionContext($('production-project').value,undefined)));
$('production-episode')?.addEventListener('change',guard(()=>changeProductionContext(state.project,$('production-episode').value||null)));
$('production-episodes-more')?.addEventListener('click',guard(()=>loadProductionEpisodes(true)));
$('production-navigation')?.addEventListener('click',guard(async event=>{const link=event.target.closest('a[data-production-page]');if(!link||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();await changeProductionContext(state.project,episodeScope,{page:link.dataset.productionPage,kind:link.dataset.kind||null});}));
$('all-objects').addEventListener('click',guard(()=>selectObject(null)));
$('filters').addEventListener('submit',guard(async event=>{event.preventDefault();state.offset=0;await loadResources();}));
$('previous').addEventListener('click',guard(async()=>{state.offset=Math.max(0,state.offset-state.limit);await loadResources();}));
$('next').addEventListener('click',guard(async()=>{state.offset+=state.limit;await loadResources();}));
$('refresh').addEventListener('click',guard(loadProjects));
for(const key of navViews)$(`nav-${key}`)?.addEventListener('click',guard(async event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();if(['home','projects','asset-center','project-management'].includes(key)){state.project=null;state.object=null;episodeScope=null;}await switchView(key);}));
$('back-to-desk').addEventListener('click',guard(()=>switchView(episodeScope?'production':state.primary)));
if($('specialist-tools'))$('specialist-tools').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();$('specialist-tools').open=false;$('specialist-tools').querySelector('summary').focus();}});
for(const tab of ['source','script','designs','library','candidates','delivery','workbench','media','artifacts','canvas'])$(`tab-${tab}`).addEventListener('click',guard(()=>switchView(tab)));
$('resource-settings-open').addEventListener('click',guard(openResourceSettings));
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>{dialog.querySelectorAll('video,audio').forEach(node=>node.pause());}));
$('role-memory-open').addEventListener('click',guard(openRoleMemory));
$('session-open').addEventListener('click',()=>switchView('access'));
$('access-open').addEventListener('click',guard(()=>switchView('access')));
$('asset-center-open').addEventListener('click',guard(()=>switchView('asset-center')));
$('commerce-open').addEventListener('click',guard(()=>switchView('commerce')));
$('project-management-open').addEventListener('click',guard(()=>switchView('project-management')));
$('service-operations-open').addEventListener('click',guard(()=>switchView('service-operations')));
$('team-review-open').addEventListener('click',guard(()=>switchView('team-review')));
$('new-canvas-project')?.addEventListener('click',guard(async()=>{setEntryOptions('home',null,null,{create:'canvas'});state.project=null;state.object=null;await switchView('home');}));
$('session-form').addEventListener('submit',guard(async event=>{event.preventDefault();const session=await api('/api/v1/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('session-token').value})});$('session-token').value='';applySession(session);$('session-dialog').close();const selectedArtifact=state.selectedArtifact;await loadProjects();if(state.view==='artifacts'&&selectedArtifact)await openArtifact(selectedArtifact);}));
$('upload-open').addEventListener('click',()=>$('upload-dialog').showModal());
$('upload-form').addEventListener('submit',guard(async event=>{event.preventDefault();const file=$('upload-file').files[0];if(!file)throw new Error('请选择文件');const rights=$('upload-rights').value;const scope=$('upload-scope').value.split(',').map(value=>value.trim()).filter(Boolean);if(rights!=='unknown' && !scope.length)throw new Error('请明确填写权利适用的用途');const button=event.target.querySelector('button[type=submit]');button.disabled=true;try{const receipt=await api(`${base()}/uploads`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),'X-CSRF-Token':state.csrf},body:file});const result=await api(`${base()}/media`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{staged_upload:receipt.staged_upload,name:file.name,rights,rights_scope:{purposes:scope},source:{kind:'user_upload',content:$('upload-source').value}},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('upload-dialog').close();event.target.reset();await loadResources();notice(msg("ui.media_copied_and_registered_no_role_is_bound_or"));}finally{button.disabled=false;}}));
if(typeof window!=='undefined'){
  window.addEventListener('beforeunload',event=>{if(assistedDesk?.hasDrafts()){event.preventDefault();event.returnValue='';}});
  window.addEventListener('popstate',guard(async()=>{const route=currentEntry();state.view=[...mainViews,...platformViews,...customViews,...specialistViews].includes(route.get('page'))?route.get('page'):'home';pendingDeskRef=route.get('object');pendingDeskVersion=route.get('version');pendingDeskBucket=route.get('bucket');episodeScope=route.get('episode');restoringDeskRoute=true;try{await selectProject(route.get('project')||state.project,{scope:route.get('scope')});}finally{restoringDeskRoute=false;}}));
}
// Explicit shell labels only. Icons, controls and user text are never traversed for translation.
for(const [selector,key] of [['.brand > span:last-child','shell.workbench'],['#nav-home > span','common.route_home'],['#nav-projects > span','nav.my_projects'],['#nav-asset-center > span','nav.asset_center'],['#nav-community > span','shell.community'],['#nav-project-management > span','nav.recycle_bin'],['.recent-projects > h2','home.recent_creations'],['.project-context > summary','shell.project_context'],['#nav-intelligent-creation','nav.agent_workflow'],['#nav-intelligent-storyboard','shell.intelligent_storyboard'],['#nav-tasks','shell.tasks'],['#nav-assets','shell.project_assets'],['#nav-settings','shell.settings'],['#nav-desk','shell.review_queue'],['#nav-collection','shell.shared_library'],['#nav-trash','shell.media_recycle'],['.topbar-projects','nav.my_projects'],['#access-open','shell.account_team'],['#team-review-open','shell.project_review'],['#commerce-open','shell.billing'],['#project-management-open','shell.project_directory'],['#service-operations-open','shell.services'],['#asset-center-open','nav.asset_center'],['#role-memory-open','ui.role_memory'],['#resource-settings-open','ui.resource_configuration'],['#session-open','shell.account']]){const label=document.querySelector(selector);if(label)setText(label,msg(key));}
for(const [selector,key]of [['#new-canvas-project','shell.new_canvas'],['.sidebar-footer a[href="?page=service-operations"]','shell.help'],['.sidebar-footer a[href="?page=settings"]','shell.settings']]){const host=document.querySelector(selector);if(host){const original=[...host.childNodes].find(node=>node.nodeType===3&&node.nodeValue.trim());if(original){const label=document.createElement('span');host.replaceChild(label,original);setText(label,msg(key));}}}
const localeMenu=document.createElement('details');localeMenu.className='account-tools';const localeTitle=document.createElement('summary');setText(localeTitle,msg('user.language'));const localeBody=document.createElement('div');localeMenu.append(localeTitle,localeBody);document.querySelector('.topbar .session')?.prepend(localeMenu);mountLocalePicker(localeBody,{onSelect:async code=>(await ensureAccessControl()).saveLanguage(code),onError:error=>notice(msg('shell.locale_pending',{error:error.message}))});
guard(async()=>{
  let session;
  if(typeof window!=='undefined'){
    const fragment=new URLSearchParams(window.location.hash.slice(1)),token=fragment.get('setup'),share=fragment.get('share');
    pendingInvite=fragment.get('invite');if(pendingInvite){state.view='access';fragment.delete('invite');window.history.replaceState(null,'',window.location.pathname+window.location.search+(fragment.size?'#'+fragment:''));}
    if(share){fragment.delete('share');window.history.replaceState(null,'',window.location.pathname+window.location.search+(fragment.size?'#'+fragment:''));session=await api('/api/v1/access/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:share})});state.view='access-share';}

    if(token){
      fragment.delete('setup');window.history.replaceState(null,'',window.location.pathname+window.location.search+(fragment.size?'#'+fragment:''));
      try{session=await api('/api/v1/session/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});}
      catch(error){notice(msg("ui.sign_in_guidance_could_not_be_completed_value0_continue",{value0:error.message}));}
    }
  }
  session ||= await api('/api/v1/session');applySession(session);if(state.view==='access-share'||session.share_id&&!session.identity_id){state.project=null;state.view='access-share';await switchView('access-share');return;}state.previewCapabilities=await api('/api/v1/preview-capabilities');await loadProjects();
})();
