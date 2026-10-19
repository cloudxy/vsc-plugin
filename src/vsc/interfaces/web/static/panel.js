import {artifactTitle, renderArtifactContent} from './artifact-reader.js';
const $ = (id) => document.getElementById(id);
const state = {project: null, object: null, offset: 0, limit: 36, total: 0, revision: 0, csrf: null, actor: null, writable: false, comparisons: new Map(),projectRows:new Map(), previewCapabilities: {}, expandedNodes: new Set(), treeNodes: [],treeMode:'legacy', treeRequest: 0, resourceRequest: 0, artifactRequest: 0, mediaRequest: 0, documentRequest: 0, selectedArtifact:null,compareRequest:0, view: 'workbench'};
const names = {work: '部', episode: '集', scene: '场', sequence: '镜组', shot: '镜', asset: '资产身份', take: '候选',
  image: '图片', video: '视频', audio: '音频', text: '文本', document: '文档', approved: '已批准', draft: '草稿', rejected: '已拒绝', retired: '已退役', selected: '已选',
  verified: '摘要一致', unverified: '摘要未核验', mismatch: '摘要变化', missing: '字节缺失', blocked: '读取受阻', owned: '自有', licensed: '已授权', unknown: '权利未登记'};
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; }
function notice(message) { $('notice').textContent = message || ''; $('notice').hidden = !message; }
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options});
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.message || value.detail || `请求失败 (${response.status})`);
  return value;
}
const base = () => `/api/v1/projects/${encodeURIComponent(state.project)}`;
const mediaUrl = (id) => `${base()}/media/${encodeURIComponent(id)}/content`;
const previewUrl = (id,purpose) => `${base()}/media/${encodeURIComponent(id)}/preview?purpose=${encodeURIComponent(purpose)}`;
const hasRendition = (media,purpose) => (media.renditions || []).some(row=>row.purpose===purpose);
function guard(fn) { return async (...args) => { try { notice(''); await fn(...args); } catch(error) { notice(error.message); } }; }
function badge(text, severity='') { return el('span', `badge ${severity}`, names[text] || text); }
function pretty(value) { return JSON.stringify(value, null, 2); }
function facts(title, value) { const panel = el('section', 'detail-panel'); panel.append(el('h3', '', title));if(value?.truncated)panel.append(el('p','hint','当前关系超过本次读取上限，仅显示部分结果。'));panel.append(el('pre', 'structured', pretty(value))); return panel; }
function lineagePanel(media,lineage) {
  const panel=el('section','detail-panel');panel.append(el('h3','','来源与加工'));
  if(lineage.truncated)panel.append(el('p','hint','来源图超过本次读取深度或数量上限，仅显示部分关系。'));
  for(const input of lineage.inputs || []){const row=el('div','lineage-input');const id=input.media_id || input.parent_id;const open=el('button','',`输入 ${input.role || input.relation || ''} · 层 ${input.layer_order ?? '—'} · ${id}`);open.addEventListener('click',guard(()=>openMedia(id)));row.append(open,el('pre','structured',pretty({transform:input.transform,mask_input_id:input.mask_input_id,opacity:input.opacity,parameters:input.parameters})));panel.append(row);}
  const details=el('details');details.append(el('summary','','完整配方与来源证据'),el('pre','structured',pretty({...lineage,sources:media.sources || lineage.sources || []})));panel.append(details);return panel;
}
function size(bytes) { if (bytes == null) return '未知大小'; return bytes > 1048576 ? `${(bytes/1048576).toFixed(1)} MB` : `${(bytes/1024).toFixed(1)} KB`; }

let roleMemory = null;
let resourceCanvas = null, resourceSettings = null, creativeWorkbench = null, scriptWorkspace = null;
let sourceIntake = null, designWorkspace = null, resourceLibrary = null;
let localProduction = null;
async function openLocalProduction(action, row) {
  if (!localProduction) {
    const {createLocalProduction} = await import('./local-production.js');
    localProduction = createLocalProduction($('local-production-dialog'), {api, project:()=>state.project,
      session:()=>({actor:state.actor,csrf:state.csrf}),revision:value=>{state.revision=value;},
      onArtifact:async id=>{await switchView('artifacts');await openArtifact(id);}});
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
    });
  }
  if (['workbench','candidates','delivery'].includes(state.view)) {
    const view=state.view,project=state.project;
    await creativeWorkbench.load({projectId: project, objectId: state.object, userId: state.actor || 'reader'});
    if(view===state.view && project===state.project && view!=='workbench')await creativeWorkbench.focus(view==='candidates'?'bindings':'timeline_media');
  }
}
function productionContext() {
  return {api,session:()=>({actor:state.actor,csrf:state.csrf,writable:state.writable,revision:state.revision}),setRevision:value=>{state.revision=value;},onNotice:notice,
    onMedia:openMedia,onArtifact:async id=>{await switchView('artifacts');await openArtifact(id);},
    onObject:async id=>{state.view='workbench';await selectObject(id);},
    onReference:()=>{$('upload-dialog').showModal();},onLocalAction:openLocalProduction,
    onScript:async scope=>{const project=state.project;if(scope){const relation=await api(`${base()}/workbench?section=children&object_id=${encodeURIComponent(scope)}&limit=1`);if(project!==state.project)return;for(const ancestor of relation.ancestors || [])state.expandedNodes.add(ancestor.id);}state.object=scope || null;await selectProject(project);if(project!==state.project)return;await switchView('script');const select=$('script-view').querySelector('.script-scope');if(select && select.value!==(scope || '')){select.value=scope || '';select.dispatchEvent(new Event('change',{bubbles:true}));}}};
}
async function loadSourceIntake() {
  if(!state.project || state.view!=='source')return;
  if(!sourceIntake){const {createSourceIntake}=await import('./source-intake.js');if(!sourceIntake)sourceIntake=createSourceIntake($('source-view'),productionContext());}
  if(state.view==='source')await sourceIntake.load({projectId:state.project,objectId:state.object});
}
async function loadResourceModel(mode) {
  if(!state.project || state.view!==mode)return;
  if(mode==='designs'&&!designWorkspace){const {createResourceModel}=await import('./resource-model.js');if(!designWorkspace)designWorkspace=createResourceModel($('design-view'),productionContext(),{mode:'designs'});}
  if(mode==='library'&&!resourceLibrary){const {createResourceModel}=await import('./resource-model.js');if(!resourceLibrary)resourceLibrary=createResourceModel($('asset-library-view'),productionContext());}
  if(state.view===mode)await(mode==='designs'?designWorkspace:resourceLibrary).load({projectId:state.project,objectId:state.object});
}
async function loadScriptWorkspace() {
  if (!state.project || state.view !== 'script') return;
  if (!scriptWorkspace) {
    const {createScriptWorkspace} = await import('./script-workspace.js');
    scriptWorkspace = createScriptWorkspace($('script-view'), {
      api, baseUrl: base, onNotice: notice,
      session: () => ({actor: state.actor, csrf: state.csrf, writable: state.writable, revision: state.revision}),
      setRevision: value => { state.revision = value; },
    });
  }
  if (state.view === 'script') await scriptWorkspace.load({projectId: state.project});
}
async function selectObject(id) {
  if (state.object !== id) resetArtifactReader();
  state.object = id; state.offset = 0;
  const lookup = new Map(state.treeNodes.map(row => [row.id, row]));
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
  state.view = view;
  if(view!=='source')sourceIntake?.suspend();if(view!=='designs')designWorkspace?.suspend();if(view!=='library')resourceLibrary?.suspend();
  document.querySelectorAll('.workspace').forEach(node=>{node.classList.toggle('reading-artifacts',view==='artifacts');node.classList.toggle('reading-production',['source','designs','library'].includes(view));});
  const views=[['source','source-view'],['script','script-view'],['designs','design-view'],['library','asset-library-view'],['candidates','creative-workbench'],['delivery','creative-workbench'],['workbench','creative-workbench'],['media','media-view'],['artifacts','artifact-view'],['canvas','resource-canvas']];
  const active=views.find(([tab])=>tab===view)?.[1];
  for(const target of new Set(views.map(([,target])=>target)))$(target).hidden=target!==active;
  for(const [tab,target]of views){$(`tab-${tab}`).setAttribute('aria-selected',String(tab===view));$(`tab-${tab}`).setAttribute('aria-controls',target);}
  if (view === 'canvas') await loadCanvas(focus);
  else if (['workbench','candidates','delivery'].includes(view)) await loadWorkbench();
  else if(view==='source')await loadSourceIntake();
  else if(view==='designs'||view==='library')await loadResourceModel(view);
  else if (view === 'script') await loadScriptWorkspace();
  else if (view === 'media') await loadResources();
  else if (view === 'artifacts') await loadArtifacts();
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
  $('projects').replaceChildren();
  for (const project of data.items) {
    const option = el('option', '', project.name + (project.unavailable ? ' · 权威不可用' : ''));
    option.value = project.id; $('projects').append(option);
  }
  if (!data.items.length) { $('projects').append(el('option', '', '没有已登记项目')); $('resources').replaceChildren(el('p', 'empty', '在配置的 projects 目录中建立项目后即可浏览。')); return; }
  if (state.project && data.items.some(row => row.id === state.project)) $('projects').value = state.project;
  await selectProject($('projects').value);
}
async function selectProject(id) {
  if (state.project !== id) {
    sourceIntake?.suspend();designWorkspace?.suspend();resourceLibrary?.suspend();
    state.expandedNodes.clear(); state.object = null; resourceCanvas?.load({projectId:null,userId:state.actor || 'reader'}); creativeWorkbench?.load({projectId:null,userId:state.actor || 'reader'});
    state.mediaRequest++;resetArtifactReader();state.compareRequest++;$('media-dialog').close();$('compare-dialog').close();
  }
  state.project = id; state.offset = 0; state.resourceRequest++; state.artifactRequest++; state.comparisons.clear(); updateCompare();
  const request = ++state.treeRequest;
  const paged=state.projectRows.get(id)?.storage_policy==='postgres-series-v1';
  const data = await api(paged?`${base()}/workbench?section=children&limit=60`:`${base()}/tree`);
  if (request !== state.treeRequest || state.project !== id) return;
  const project = (paged?state.projectRows.get(id):data.project) || {}; state.revision = data.revision ?? project.revision ?? 0;
  state.writable=project.storage_policy==='postgres-series-v1' && !project.read_only; $('upload-open').disabled=!(state.writable && state.actor);
  $('project-meta').replaceChildren(el('p', 'hint', `${project.storage_policy || '关系库'} · r${state.revision} · ${project.read_only ? '只读' : '共享服务'}`));
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
        toggle.setAttribute('aria-controls',group.id);toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','展开 '+(node.title||node.id));
        row.replaceChildren(toggle,b);item.append(group);let loaded=false,loading=false;
        const expand=async expanded=>{group.hidden=!expanded;toggle.textContent=expanded?'▾':'▸';toggle.setAttribute('aria-expanded',String(expanded));toggle.setAttribute('aria-label',(expanded?'收拢 ':'展开 ')+(node.title||node.id));if(expanded)state.expandedNodes.add(node.id);else state.expandedNodes.delete(node.id);if(expanded&&!loaded&&!loading){loading=true;group.replaceChildren(el('li','hint','正在读取子级…'));try{const value=await api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?`+new URLSearchParams({section:'children',object_id:node.id,limit:'60'}));if(!alive())return;group.replaceChildren();appendPage(value,group,node.id);loaded=true;}catch(error){if(alive())group.replaceChildren(el('li','hint',error.message+'；收拢后再次展开可重试。'));}finally{loading=false;}}};
        toggle.addEventListener('click',guard(()=>expand(group.hidden)));toggle.addEventListener('keydown',guard(async event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();await expand(event.key==='ArrowRight');}}));
        if(state.expandedNodes.has(node.id))expand(true);
      }else row.replaceChildren(el('span','tree-toggle-spacer'),b);
    }
    if(value.next_offset!=null){const li=el('li','tree-more'),more=el('button','',`继续显示 · 已加载 ${value.next_offset} / ${value.total}`);more.type='button';more.addEventListener('click',guard(async()=>{more.disabled=true;try{const params=new URLSearchParams({section:'children',limit:'60',offset:String(value.next_offset),revision:String(page.revision)});if(parentId)params.set('object_id',parentId);const next=await api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?${params}`);if(!alive())return;li.remove();appendPage(next,container,parentId);}finally{more.disabled=false;}}));li.append(more);container.append(li);}
    if(!value.items.length)container.append(el('li','hint','此范围尚无登记的子级。'));
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
        if (rendered < branch.length) { moreItem=el('li','tree-more');const moreButton=el('button','',`继续显示 ${Math.min(60,branch.length-rendered)} 项 · 还有 ${branch.length-rendered} 项`);moreButton.type='button';moreButton.addEventListener('click',renderMore);moreItem.append(moreButton);group.append(moreItem); }
      };
      const setExpanded = (expanded) => {
        if (expanded) state.expandedNodes.add(node.id); else state.expandedNodes.delete(node.id);
        group.hidden = !expanded;
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-label', `${expanded ? '收拢' : '展开'} ${node.title || node.display_code || node.id}`);
        toggle.textContent = expanded ? '▾' : '▸';
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
  const addRoots=()=>{if(moreRoots)moreRoots.remove();const end=Math.min(rootNodes.length,rootCount+60);while(rootCount<end)add(rootNodes[rootCount++],roots);if(rootCount<rootNodes.length){moreRoots=el('li','tree-more');const moreButton=el('button','',`更多顶层范围 · 还有 ${rootNodes.length-rootCount} 项`);moreButton.addEventListener('click',addRoots);moreRoots.append(moreButton);roots.append(moreRoots);}};
  addRoots();
  if (nodes.length) $('tree').append(roots);
  else $('tree').append(el('p', 'hint', '未建立部、集、场、镜组或镜头关系。'));
}
async function loadResources() {
  const request=++state.resourceRequest, project=state.project, object=state.object;
  const params = new URLSearchParams({offset: state.offset, limit: state.limit});
  for (const key of ['modality','registration','query','role','status']) if ($(key).value) params.set(key, $(key).value);
  if (state.object) params.set('object_id', state.object);
  const data = await api(`${base()}/media?${params}`); if(request!==state.resourceRequest || project!==state.project || object!==state.object)return; state.total = data.total; state.revision = data.revision ?? state.revision;
  $('resources').replaceChildren();
  for (const media of data.items) $('resources').append(resourceCard(media));
  if (!data.items.length) $('resources').append(el('p', 'empty', '此范围没有已关联素材。可切换至“全部项目内容”查看未登记文件。'));
  $('resource-summary').textContent = `共 ${data.total} 项 · 本页 ${data.items.length} 项。未登记文件仅供浏览，正式用途尚未确定。`;
  $('page-info').textContent = `${data.total ? state.offset+1 : 0}–${Math.min(state.offset+state.limit,data.total)} / ${data.total}`;
  $('previous').disabled = state.offset === 0; $('next').disabled = state.offset+state.limit >= data.total;
}
function resourceCard(media) {
  const card = el('article', 'resource-card'); const thumb = el('button', 'thumbnail'); thumb.setAttribute('aria-label', `查看 ${media.name || media.id}`);
  const thumbnailPurpose={image:'thumbnail',video:'poster',audio:'waveform',document:'document_pages'}[media.modality];
  if (hasRendition(media,thumbnailPurpose) && media.availability !== 'missing' && media.integrity !== 'mismatch') { const image = el('img'); image.loading = 'lazy'; image.alt = media.name || media.id; image.src = hasRendition(media,thumbnailPurpose)?previewUrl(media.id,thumbnailPurpose):mediaUrl(media.id); thumb.append(image); }
  else thumb.textContent = ({video: '▶', audio: '♪', text: '文', document: '▤'})[media.modality] || '▧';
  thumb.addEventListener('click', guard(() => openMedia(media.id)));
  const body = el('div', 'card-body'); body.append(el('div', 'card-name', media.name || media.id));
  const badges = el('div', 'badges'); badges.append(badge(media.modality), badge(media.registered === false ? '未登记' : '已登记', media.registered === false ? 'warning' : ''));
  if (media.availability && media.availability !== 'available') badges.append(badge(media.availability, 'danger'));
  if (media.integrity === 'mismatch') badges.append(badge('mismatch', 'danger'));
  if (media.deprecated) badges.append(badge('已停用', 'danger'));
  body.append(badges, el('div', 'hint', size(media.size_bytes)));
  const graphButton=el('button','card-graph','在画布中查看');graphButton.type='button';graphButton.addEventListener('click',guard(()=>switchView('canvas',`media:${media.id}`)));body.append(graphButton);
  const actions = el('div', 'card-actions'); const label = el('label'); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = state.comparisons.has(media.id);
  checkbox.addEventListener('change', () => { if (checkbox.checked) { if (state.comparisons.size >= 4) { checkbox.checked = false; notice('最多并排比较 4 个候选。'); return; } state.comparisons.set(media.id,media); } else state.comparisons.delete(media.id); updateCompare(); });
  label.append(checkbox,document.createTextNode('比较')); const detail = el('button', '', '详情'); detail.addEventListener('click', guard(() => openMedia(media.id))); actions.append(label,detail); body.append(actions); card.append(thumb,body); return card;
}
async function player(media) {
  const wrapper = el('div'); const source = mediaUrl(media.id);
  if (['missing','blocked','unavailable'].includes(media.availability) || media.integrity === 'mismatch') { wrapper.append(el('p','empty','字节缺失、摘要变化、存储未配置或路径受阻，无法预览。')); return wrapper; }
  if (['image','audio','video'].includes(media.modality)) {
    const node = el(media.modality === 'image' ? 'img' : media.modality, 'media-player'); node.src = source;
    if(media.modality==='video' && hasRendition(media,'poster'))node.poster=previewUrl(media.id,'poster');
    if(media.modality==='video' && hasRendition(media,'proxy_video'))node.src=previewUrl(media.id,'proxy_video');
    if (media.modality === 'image') { node.alt = media.name || media.id; node.classList.add('zoomable'); node.addEventListener('click', () => node.classList.toggle('zoomed')); }
    else { node.controls = true; node.preload = 'metadata'; }
    wrapper.append(node);
    if (media.modality === 'audio') {
      if(hasRendition(media,'waveform')){const image=el('img','media-player');image.alt='受控音频波形预览';image.src=previewUrl(media.id,'waveform');wrapper.append(image);}
      const button = el('button','','显示音频波形'); button.addEventListener('click', guard(async () => { button.disabled = true; const response = await fetch(source); if (!response.ok) throw new Error('读取音频失败'); const bytes = await response.arrayBuffer(); const context = new AudioContext(); try { const audio = await context.decodeAudioData(bytes); const canvas = el('canvas','waveform'); canvas.width=900; canvas.height=90; const ctx=canvas.getContext('2d'); const samples=audio.getChannelData(0); const step=Math.ceil(samples.length/canvas.width); ctx.strokeStyle='#17625a'; for(let x=0;x<canvas.width;x++){let peak=0;for(let j=x*step;j<Math.min((x+1)*step,samples.length);j++)peak=Math.max(peak,Math.abs(samples[j]));ctx.beginPath();ctx.moveTo(x,45-peak*42);ctx.lineTo(x,45+peak*42);ctx.stroke();}wrapper.append(canvas,el('p','hint','浏览器按当前字节临时绘制；波形未作为正式检查或台词对齐证据。')); } finally { await context.close(); button.disabled=false; }})); wrapper.append(button);
    }
  } else if (media.modality === 'text') { const response=await fetch(source,{headers:{Range:'bytes=0-1048575'}}); if(!response.ok) throw new Error('读取文本失败'); const content=await response.text(); const range=response.headers.get('content-range'); const truncated=range && Number(range.split('/')[1])>1048576; wrapper.append(el('pre','readable',content+(truncated?'\n［正文过长，当前仅展示前 1 MiB，可下载完整文件。］':''))); }
  else if(hasRendition(media,'document_pages')){const image=el('img','media-player');image.alt='文档第一页受控预览';image.src=previewUrl(media.id,'document_pages');wrapper.append(image);}
  else wrapper.append(el('p','hint','此格式尚无可用预览副本，可下载原文件查看。'));
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
  $('media-title').textContent = media.name || media.id; $('media-detail').replaceChildren(playback);
  const download=el('a','','下载原文件'); download.href=mediaUrl(id)+'?download=true'; $('media-detail').append(download);
  const panels=el('div','detail-grid'); panels.append(facts('规格与可用性',{id:media.id,modality:media.modality,sha256:media.sha256,size_bytes:media.size_bytes,width:media.width,height:media.height,duration_ms:media.duration_ms,sample_rate:media.sample_rate,availability:media.availability,integrity:media.integrity,rights:media.rights,deprecated:media.deprecated}),lineagePanel(media,lineage),facts('用途与下游引用',usage),facts('审查与决定',{checks:media.checks || [],reviews:media.reviews || [],decisions:media.decisions || [],bindings:media.bindings || []})); $('media-detail').append(panels);
  if(state.writable){const jobs=await api(`${root}/preview-jobs?media_id=${encodeURIComponent(media.id)}`);if(project!==state.project || request!==state.mediaRequest)return;const panel=facts('持久预览任务',jobs);if(state.actor)for(const job of jobs.items || [])if(job.status==='failed'){const button=el('button','',`明确重试 ${job.purpose}`);button.addEventListener('click',guard(async()=>{const result=await api(`${base()}/preview-retries`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{job_id:job.id},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);notice('失败任务已重新排队，等待本机预览执行器。');}));panel.append(button);}$('media-detail').append(panel);}
  if (state.actor && state.writable && media.registered !== false) $('media-detail').append(previewForm(media),bindingForm(media),reviewForm(media),mediaAuditForm(media));
  $('media-dialog').showModal();
}
function reviewForm(media) {
  const form=el('form','review-form'); const field=el('fieldset'); field.append(el('legend','','人工审查与用途决定'));
  const candidate=el('select'); const candidates=media.candidates || media.bindings || []; for(const item of candidates){const option=el('option','',`${item.role || item.slot_id || '候选'} · ${item.id}`);option.value=item.candidate_id || item.id;candidate.append(option);}
  if(!candidates.length){field.append(el('p','hint','该素材尚无用途候选；先在对应镜头提出用途绑定。'));form.append(field);return form;}
  const action=el('select'); for(const [value,label] of [['reviews','记录审查意见'],['binding-decisions','选择此候选'],['binding-rejections','拒绝此候选'],['binding-retirements','退役当前用途']]){const option=el('option','',label);option.value=value;action.append(option);}
  const outcome=el('select'); for(const [value,label] of [['pass','通过'],['needs_changes','需要修改'],['fail','不通过']]){const option=el('option','',label);option.value=value;outcome.append(option);}
  const reason=el('textarea');reason.placeholder=media.trial_sources?.length?'说明试片符合正式用途的依据，或本次审查／参考用途的理由':'说明用途、连续性、读法或决定依据';reason.required=true;
  const adoption=el('div');adoption.hidden=true;const animatic=el('select');animatic.setAttribute('aria-label','试片正式采用的预演版本');const empty=el('option','','请选择已批准预演（仅正式采用需要）');empty.value='';animatic.append(empty);for(const row of media.trial_animatics || []){const opt=el('option','',`${row.name || row.artifact_key || '预演'} · ${row.id}`);opt.value=row.id;animatic.append(opt);}if(media.trial_sources?.length){adoption.append(el('p','hint','此素材含试片来源。用于正式剪辑时选择已批准预演，并在决定理由中说明采用依据；参考用途可继续试用。'),animatic);action.addEventListener('change',()=>{adoption.hidden=action.value!=='binding-decisions';});}
  const label=el('label');const check=el('input');check.type='checkbox';label.append(check,document.createTextNode('我确认这是本人对当前用途作出的决定'));
  const button=el('button','','提交');button.type='submit';field.append(candidate,action,outcome,reason,adoption,label,button);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const choice=candidates.find(row=>(row.candidate_id || row.id)===candidate.value);let payload={candidate_id:candidate.value,reason:reason.value};if(action.value==='binding-decisions' && animatic.value)payload.trial_adoption={reason:reason.value,animatic_version_id:animatic.value};if(action.value==='reviews')payload={...payload,outcome:outcome.value,reviewer_type:'human',criteria_version:'panel-human-v1'};if(action.value==='binding-retirements')payload={slot_id:choice.slot_id,reason:reason.value};const result=await api(`${base()}/${action.value}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,confirmed:check.checked,expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await loadResources();notice('操作已记录；历史版本与决定保留。');}));
  return form;
}
function bindingForm(media) {
  const form=el('form','review-form'); const field=el('fieldset');field.append(el('legend','','提出用途候选'));
  const target=el('input');target.placeholder='目标对象 ID（从结构导航读取）';target.value=state.object || '';target.required=true;
  const role=el('select');for(const value of ['identity_face','costume','location_master','location_view','composition','first_frame','last_frame','prop','video_take','dialogue_dry','voice_sample','ambience','music','sfx','style_reference']){const option=el('option','',value);option.value=value;role.append(option);}
  const slot=el('input');slot.value='main';slot.placeholder='用途槽位 key';slot.required=true;
  const reason=el('textarea');reason.placeholder='说明目标规格与提出依据';reason.required=true;
  const button=el('button','','提交用途候选');button.type='submit';field.append(target,role,slot,reason,button);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const result=await api(`${base()}/binding-candidates`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{media_id:media.id,target_object_id:target.value,role:role.value,slot_key:slot.value,reason:reason.value},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);}));return form;
}
function mediaAuditForm(media) {
  const form=el('form','review-form');const field=el('fieldset');field.append(el('legend','','素材检查与项目内停用'));
  const action=el('select');for(const [value,label] of [['media-checks','记录本人完成的检查证据'],['media-lifecycle-decisions','停用素材（保留历史与字节）']]){const option=el('option','',label);option.value=value;action.append(option);}
  const outcome=el('select');for(const [value,label] of [['pass','检查通过'],['fail','检查不通过'],['unknown','尚不能确定']]){const option=el('option','',label);option.value=value;outcome.append(option);}
  const reason=el('textarea');reason.placeholder='填写实际检查的方法、观察和证据；停用时说明原因及影响';reason.required=true;
  const label=el('label');const confirm=el('input');confirm.type='checkbox';confirm.required=true;label.append(confirm,document.createTextNode('我确认本人已完成上述检查，或决定将此素材停止用于新的选择'));
  const submit=el('button','','记录');submit.type='submit';field.append(action,outcome,reason,label,submit);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const payload=action.value==='media-checks'?{media_id:media.id,blob_sha256:media.sha256,checker:`human:${state.actor}`,criteria_version:'panel-manual-v1',outcome:outcome.value,report:{reason:reason.value,method:'human_manual'}}:{media_id:media.id,reason:reason.value};const result=await api(`${base()}/${action.value}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,confirmed:confirm.checked,expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);notice('检查证据或停用决定已记录；原有历史引用保留。');}));return form;
}
function previewForm(media) {
  const form=el('form','review-form');const field=el('fieldset');field.append(el('legend','','受控预览副本'));
  const available={image:['thumbnail'],video:['poster','proxy_video'],audio:['waveform'],document:media.mime_type==='application/pdf'?['document_pages']:[]}[media.modality] || [];
  const labels={thumbnail:'图片缩略图',poster:'视频首帧海报',proxy_video:'通用 H.264 代理视频',waveform:'音频波形',document_pages:'PDF 第一页'};
  const select=el('select');for(const purpose of available){const option=el('option','',labels[purpose]+(!state.previewCapabilities[purpose]?' · 转换器未安装':''));option.value=purpose;option.disabled=!state.previewCapabilities[purpose];select.append(option);}
  if(!available.some(purpose=>state.previewCapabilities[purpose])){field.append(el('p','hint','当前格式没有已安装的预览转换器，仍可查看元数据并下载。'));form.append(field);return form;}
  const button=el('button','','排入预览队列');button.type='submit';const refresh=el('button','','刷新预览状态');refresh.type='button';refresh.addEventListener('click',guard(async()=>{$('media-dialog').close();await openMedia(media.id);}));
  field.append(select,button,refresh,el('p','hint','转换由本机持久执行器处理，可续接；预览副本与原素材、正式用途选择分别保存。'));form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const result=await api(`${base()}/preview-jobs`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{media_id:media.id,purpose:select.value,recipe_version:state.previewCapabilities.recipe_version},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;notice(result.status==='failed'?'该预览任务此前失败，请查看错误并明确请求重试。':result.status==='succeeded'?'此配方已有完成的预览副本，刷新状态即可查看。':'预览任务已持久入队，等待本机执行器。完成后刷新状态即可查看。');}));return form;
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
  $('artifacts').replaceChildren();
  $('artifacts').setAttribute('aria-busy','false');
  $('document').replaceChildren(el('p','empty','选择文案或固定版本阅读。'));
  $('document').setAttribute('aria-label','文案正文');$('document').setAttribute('aria-busy','false');
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
  if(!$('artifacts').childElementCount)$('artifacts').append(el('p','empty','正在读取文案版本…'));
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
    if(!rows.length)$('artifacts').append(el('p','empty','此范围未建立文案版本关系。'));
    markArtifactSelection();
  } catch(error) {
    if(!alive())return;
    const failure=el('section','artifact-list-error'),retry=el('button','','重新读取文案版本');
    retry.type='button';failure.setAttribute('role','status');
    failure.append(el('p','empty',`文案版本读取失败：${error.message}`),retry);
    retry.addEventListener('click',guard(async()=>{if(!alive())return;retry.disabled=true;retry.textContent='正在重试…';await loadArtifacts();}));
    $('artifacts').replaceChildren(failure);markArtifactSelection();throw error;
  }
  finally { if(alive())$('artifacts').setAttribute('aria-busy','false'); }
}
async function openArtifact(id,{focusFrom=null}={}) {
  const project=state.project, object=state.object, request=++state.documentRequest;
  const alive=()=>project===state.project && object===state.object && request===state.documentRequest;
  state.selectedArtifact=id;markArtifactSelection();
  $('document').replaceChildren(el('p','empty','正在读取文案…'));
  $('document').setAttribute('aria-busy','true');$('document').removeAttribute('data-artifact-id');
  let artifact;
  try { artifact=await api(`${base()}/artifacts/${encodeURIComponent(id)}`); }
  catch(error) { if(alive()){$('document').replaceChildren(el('p','empty','文案读取失败，请再次选择该版本重试。'));throw error;}return; }
  finally { if(alive())$('document').setAttribute('aria-busy','false'); }
  if(!alive())return;
  const content=artifact.content === null && artifact.document !== undefined ? artifact.document : artifact.content !== undefined ? artifact.content : artifact.document !== undefined ? artifact.document : '';
  // Legacy envelopes use null for unread file bytes; a JSON null document arrives as the string "null".
  const unavailable=content===null && artifact.availability != null;
  const {body,value:fixed}=unavailable ? {body:el('p','empty',artifact.size_bytes>16*1024*1024 ? '正文超过内置阅读限额，请在原文件中阅读完整内容。' : '正文未载入，请核对来源文件是否可读。')} : renderArtifactContent(content);
  $('document').replaceChildren(body);$('document').setAttribute('aria-label',artifactTitle(artifact));
  $('document').setAttribute('data-artifact-id',id);$('document').scrollTop=0;
  const selected=[...$('artifacts').querySelectorAll('.artifact-item')].find(button=>button.dataset.id===id);
  if(selected){selected.querySelector('.artifact-title').textContent=artifactTitle(artifact);selected.querySelector('.artifact-state').textContent=artifactVersionLabel(artifact);}
  if (artifact.revision != null && state.writable) {
    const controls=el('section','detail-panel artifact-decisions'),reason=el('input');reason.placeholder='批准或退回所见版本的理由';reason.setAttribute('aria-label','版本决定理由');
    const execute=async(action,payload,key)=>{
      if(!alive())throw new Error('项目、范围或所见版本已切换，请重新读取');
      if(!state.actor)throw new Error('请先建立人工操作会话');
      const result=await api(`/api/v1/projects/${encodeURIComponent(project)}/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,expected_revision:artifact.revision,idempotency_key:key,confirmed:true})});
      if(project===state.project)state.revision=result.revision;
      if(alive())await openArtifact(id);return result;
    };
    if(!artifact.approved){
      controls.append(reason);
      for(const [outcome,text] of [['approve','批准所见版本'],['reject','退回此版本']]){
        const button=el('button','',text),key=crypto.randomUUID();
        button.addEventListener('click',guard(async()=>{if(!reason.value.trim())throw new Error('请填写决定理由');if(!confirm(`${text}？决定仅针对当前固定内容与范围。`))return;button.disabled=true;try{await execute('artifact-decisions',{artifact_id:id,outcome,reason:reason.value},key);}finally{button.disabled=false;}}));controls.append(button);
      }
    }else if(['resample','redo_sound'].includes(fixed?.local_action)){
      const button=el('button','','将已批准的局部方案入队'),key=crypto.randomUUID();
      button.addEventListener('click',guard(async()=>{if(!confirm('仅将这个已批准方案的目标入队？实际调用仍由生成worker执行。'))return;button.disabled=true;try{const result=await execute('local-production-enqueue',{artifact_id:id},key);notice(`已登记 ${result.jobs.length} 个固定任务。`);}finally{button.disabled=false;}}));controls.append(button);
    }
    if(controls.childElementCount)$('document').append(controls);
  }
  const evidence=el('details','artifact-evidence');evidence.append(el('summary','','版本与核验'));
  evidence.append(el('p','hint',`${artifact.id} · ${artifact.version != null ? 'v'+artifact.version+' · ' : ''}${names[artifact.status] || artifact.status || (artifact.approved ? '已批准' : '待决定')} · ${names[artifact.integrity] || '固定内容'}`));
  if(artifact.sha256)evidence.append(el('p','hint',`内容摘要：${artifact.sha256}`));
  $('document').append(evidence);
  if(artifact.integrity==='mismatch')$('document').prepend(el('p','badge danger','该固定版本的文件摘要变化，当前仅供诊断浏览，不能正式消费。'));
  if(artifact.availability==='missing')$('document').prepend(el('p','badge danger','该固定版本的内容缺失，请核对来源文件。'));
  if(focusFrom && document.activeElement===focusFrom && state.view==='artifacts' && alive())$('document').focus();
}
function updateCompare(){$('compare-count').textContent=state.comparisons.size;}
$('compare-open').addEventListener('click',guard(async()=>{const project=state.project,ticket=++state.compareRequest,sections=[];for(const media of state.comparisons.values()){const section=el('section');section.append(el('h3','',media.name||media.id),await player(media),facts('用途与来源',{bindings:media.bindings||[],rights:media.rights,sha256:media.sha256}));if(project!==state.project||ticket!==state.compareRequest)return;sections.push(section);}if(project!==state.project||ticket!==state.compareRequest)return;$('compare-grid').replaceChildren(...sections);if(!sections.length)$('compare-grid').append(el('p','empty','先在素材卡或工作台中选择需要比较的候选。'));$('compare-dialog').showModal();}));
$('projects').addEventListener('change',guard(()=>selectProject($('projects').value)));
$('all-objects').addEventListener('click',guard(()=>selectObject(null)));
$('filters').addEventListener('submit',guard(async event=>{event.preventDefault();state.offset=0;await loadResources();}));
$('previous').addEventListener('click',guard(async()=>{state.offset=Math.max(0,state.offset-state.limit);await loadResources();}));
$('next').addEventListener('click',guard(async()=>{state.offset+=state.limit;await loadResources();}));
$('refresh').addEventListener('click',guard(loadProjects));
for(const tab of ['source','script','designs','library','candidates','delivery','workbench','media','artifacts','canvas'])$(`tab-${tab}`).addEventListener('click',guard(()=>switchView(tab)));
$('resource-settings-open').addEventListener('click',guard(openResourceSettings));
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>{dialog.querySelectorAll('video,audio').forEach(node=>node.pause());}));
$('role-memory-open').addEventListener('click',guard(openRoleMemory));
$('session-open').addEventListener('click',()=>$('session-dialog').showModal());
$('session-form').addEventListener('submit',guard(async event=>{event.preventDefault();const session=await api('/api/v1/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('session-token').value})});$('session-token').value='';state.actor=session.actor;state.csrf=session.csrf_token;$('session-label').textContent=`操作人：${state.actor}`;$('upload-open').disabled=!state.writable;$('session-dialog').close();}));
$('upload-open').addEventListener('click',()=>$('upload-dialog').showModal());
$('upload-form').addEventListener('submit',guard(async event=>{event.preventDefault();const file=$('upload-file').files[0];if(!file)throw new Error('请选择文件');const rights=$('upload-rights').value;const scope=$('upload-scope').value.split(',').map(value=>value.trim()).filter(Boolean);if(rights!=='unknown' && !scope.length)throw new Error('请明确填写权利适用的用途');const button=event.target.querySelector('button[type=submit]');button.disabled=true;try{const receipt=await api(`${base()}/uploads`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),'X-CSRF-Token':state.csrf},body:file});const result=await api(`${base()}/media`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{staged_upload:receipt.staged_upload,name:file.name,rights,rights_scope:{purposes:scope},source:{kind:'user_upload',content:$('upload-source').value}},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('upload-dialog').close();event.target.reset();await loadResources();notice('素材已转存并登记，尚未绑定或批准用途。');}finally{button.disabled=false;}}));
guard(async()=>{const session=await api('/api/v1/session');state.actor=session.actor;state.csrf=session.csrf_token;if(session.actor)$('session-label').textContent=`操作人：${session.actor}`;state.previewCapabilities=await api('/api/v1/preview-capabilities');await loadProjects();})();
