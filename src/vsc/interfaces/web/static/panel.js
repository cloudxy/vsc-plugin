const $ = (id) => document.getElementById(id);
const state = {project: null, object: null, offset: 0, limit: 36, total: 0, revision: 0, csrf: null, actor: null, writable: false, comparisons: new Map(), previewCapabilities: {}};
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

async function loadProjects() {
  const data = await api('/api/v1/projects');
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
  state.project = id; state.object = null; state.offset = 0; state.comparisons.clear(); updateCompare();
  const data = await api(`${base()}/tree`);
  const project = data.project || {}; state.revision = data.revision ?? project.revision ?? 0;
  state.writable=project.storage_policy==='postgres-series-v1' && !project.read_only; $('upload-open').disabled=!(state.writable && state.actor);
  $('heading').textContent = project.name || project.title || '项目资源';
  $('project-meta').replaceChildren(el('p', 'hint', `${project.storage_policy || '关系库'} · r${state.revision} · ${project.read_only ? '只读' : '共享服务'}`));
  $('scope-label').textContent = '全部项目内容'; renderTree(data.nodes || []);
  if (data.gaps?.length) notice(data.gaps.join('\n'));
  await Promise.all([loadResources(), loadArtifacts()]);
}
function renderTree(nodes) {
  $('tree').replaceChildren();
  const lookup = new Map(nodes.map(node => [node.id, node]));
  const sorted = [...nodes].sort((a,b) => (a.ordinal || 0) - (b.ordinal || 0));
  const visited = new Set();
  function add(node, depth) {
    if (visited.has(node.id)) return; visited.add(node.id);
    const button = el('button', `tree-item tree-depth-${Math.min(depth,5)}`); button.dataset.id = node.id;
    button.append(el('span', 'tree-kind', names[node.kind] || node.kind), el('span', '', node.title || node.display_code || node.id));
    button.addEventListener('click', guard(async () => { state.object = node.id; state.offset = 0; $('scope-label').textContent = `${names[node.kind] || node.kind} · ${node.title || node.id}`; $('tree').querySelectorAll('.tree-item').forEach(row => row.classList.toggle('active', row.dataset.id === node.id)); await Promise.all([loadResources(), loadArtifacts()]); }));
    $('tree').append(button);
    for (const child of sorted.filter(row => row.parent_id === node.id)) add(child, depth+1);
  }
  for (const node of sorted.filter(row => !row.parent_id || !lookup.has(row.parent_id))) add(node,0);
  for (const node of sorted) if (!visited.has(node.id)) add(node,0);
  if (!nodes.length) $('tree').append(el('p', 'hint', '未建立部、集、场、镜组或镜头关系。'));
}
async function loadResources() {
  const params = new URLSearchParams({offset: state.offset, limit: state.limit});
  for (const key of ['modality','registration','query','role','status']) if ($(key).value) params.set(key, $(key).value);
  if (state.object) params.set('object_id', state.object);
  const data = await api(`${base()}/media?${params}`); state.total = data.total; state.revision = data.revision ?? state.revision;
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
  if ((media.modality === 'image' || hasRendition(media,thumbnailPurpose)) && media.availability !== 'missing' && media.integrity !== 'mismatch') { const image = el('img'); image.loading = 'lazy'; image.alt = media.name || media.id; image.src = hasRendition(media,thumbnailPurpose)?previewUrl(media.id,thumbnailPurpose):mediaUrl(media.id); thumb.append(image); }
  else thumb.textContent = ({video: '▶', audio: '♪', text: '文', document: '▤'})[media.modality] || '▧';
  thumb.addEventListener('click', guard(() => openMedia(media.id)));
  const body = el('div', 'card-body'); body.append(el('div', 'card-name', media.name || media.id));
  const badges = el('div', 'badges'); badges.append(badge(media.modality), badge(media.registered === false ? '未登记' : '已登记', media.registered === false ? 'warning' : ''));
  if (media.availability && media.availability !== 'available') badges.append(badge(media.availability, 'danger'));
  if (media.integrity === 'mismatch') badges.append(badge('mismatch', 'danger'));
  if (media.deprecated) badges.append(badge('已停用', 'danger'));
  body.append(badges, el('div', 'hint', size(media.size_bytes)));
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
  const [media,lineage,usage] = await Promise.all([api(`${base()}/media/${encodeURIComponent(id)}`),api(`${base()}/media/${encodeURIComponent(id)}/lineage`),api(`${base()}/media/${encodeURIComponent(id)}/usage`)]);
  if(usage.candidates)media.candidates=(media.candidates || []).map(candidate=>({...candidate,...usage.candidates.find(row=>row.id===candidate.id)}));
  state.revision=media.revision ?? state.revision;
  $('media-title').textContent = media.name || media.id; $('media-detail').replaceChildren(await player(media));
  const download=el('a','','下载原文件'); download.href=mediaUrl(id)+'?download=true'; $('media-detail').append(download);
  const panels=el('div','detail-grid'); panels.append(facts('规格与可用性',{id:media.id,modality:media.modality,sha256:media.sha256,size_bytes:media.size_bytes,width:media.width,height:media.height,duration_ms:media.duration_ms,sample_rate:media.sample_rate,availability:media.availability,integrity:media.integrity,rights:media.rights,deprecated:media.deprecated}),lineagePanel(media,lineage),facts('用途与下游引用',usage),facts('审查与决定',{checks:media.checks || [],reviews:media.reviews || [],decisions:media.decisions || [],bindings:media.bindings || []})); $('media-detail').append(panels);
  if(state.writable){const jobs=await api(`${base()}/preview-jobs?media_id=${encodeURIComponent(media.id)}`);const panel=facts('持久预览任务',jobs);if(state.actor)for(const job of jobs.items || [])if(job.status==='failed'){const button=el('button','',`明确重试 ${job.purpose}`);button.addEventListener('click',guard(async()=>{const result=await api(`${base()}/preview-retries`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{job_id:job.id},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await openMedia(media.id);notice('失败任务已重新排队，等待本机预览执行器。');}));panel.append(button);}$('media-detail').append(panel);}
  if (state.actor && state.writable && media.registered !== false) $('media-detail').append(previewForm(media),bindingForm(media),reviewForm(media),mediaAuditForm(media));
  $('media-dialog').showModal();
}
function reviewForm(media) {
  const form=el('form','review-form'); const field=el('fieldset'); field.append(el('legend','','人工审查与用途决定'));
  const candidate=el('select'); const candidates=media.candidates || media.bindings || []; for(const item of candidates){const option=el('option','',`${item.role || item.slot_id || '候选'} · ${item.id}`);option.value=item.candidate_id || item.id;candidate.append(option);}
  if(!candidates.length){field.append(el('p','hint','该素材尚无用途候选；先在对应镜头提出用途绑定。'));form.append(field);return form;}
  const action=el('select'); for(const [value,label] of [['reviews','记录审查意见'],['binding-decisions','选择此候选'],['binding-rejections','拒绝此候选'],['binding-retirements','退役当前用途']]){const option=el('option','',label);option.value=value;action.append(option);}
  const outcome=el('select'); for(const [value,label] of [['pass','通过'],['needs_changes','需要修改'],['fail','不通过']]){const option=el('option','',label);option.value=value;outcome.append(option);}
  const reason=el('textarea');reason.placeholder='说明用途、连续性、读法或决定依据';reason.required=true;
  const label=el('label');const check=el('input');check.type='checkbox';label.append(check,document.createTextNode('我确认这是本人对当前用途作出的决定'));
  const button=el('button','','提交');button.type='submit';field.append(candidate,action,outcome,reason,label,button);form.append(field);
  form.addEventListener('submit',guard(async event=>{event.preventDefault();const choice=candidates.find(row=>(row.candidate_id || row.id)===candidate.value);let payload={candidate_id:candidate.value,reason:reason.value};if(action.value==='reviews')payload={...payload,outcome:outcome.value,reviewer_type:'human',criteria_version:'panel-human-v1'};if(action.value==='binding-retirements')payload={slot_id:choice.slot_id,reason:reason.value};const result=await api(`${base()}/${action.value}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload,confirmed:check.checked,expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('media-dialog').close();await loadResources();notice('操作已记录；历史版本与决定保留。');}));
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
async function loadArtifacts() {
  const data=await api(`${base()}/artifacts${state.object ? '?object_id='+encodeURIComponent(state.object) : ''}`);
  const rows=Array.isArray(data) ? data : data.items || []; $('artifacts').replaceChildren();
  for(const artifact of [...rows].reverse()){const button=el('button','artifact-item',artifact.type || artifact.name || artifact.id);button.append(el('small','',`${artifact.id} · ${names[artifact.status] || artifact.status || '固定版本'}`));if(artifact.integrity==='mismatch' || artifact.availability==='missing')button.append(badge(artifact.integrity==='mismatch'?'mismatch':'missing','danger'));button.addEventListener('click',guard(()=>openArtifact(artifact.id)));$('artifacts').append(button);}
  if(!rows.length)$('artifacts').append(el('p','empty','此范围未建立文案版本关系。'));
}
async function openArtifact(id) {
  const artifact=await api(`${base()}/artifacts/${encodeURIComponent(id)}`);const header=el('header');header.append(el('h2','',artifact.type || artifact.name || artifact.id),el('p','hint',`${artifact.id} · ${names[artifact.status] || artifact.status || ''} · ${names[artifact.integrity] || '固定内容'}`));
  let content=artifact.content ?? artifact.document ?? '';if(typeof content !== 'string')content=pretty(content);
  let structured=false;try{const value=JSON.parse(content);content=pretty(value);structured=true;}catch{}
  $('document').replaceChildren(header,el('pre',structured?'structured':'readable',content || '内容缺失或超过内置阅读限额。'));
  if(artifact.integrity==='mismatch')$('document').prepend(el('p','badge danger','该固定版本的文件摘要变化，当前仅供诊断浏览，不能正式消费。'));
}
function updateCompare(){$('compare-count').textContent=state.comparisons.size;}
$('compare-open').addEventListener('click',guard(async()=>{$('compare-grid').replaceChildren();for(const media of state.comparisons.values()){const section=el('section');section.append(el('h3','',media.name || media.id),await player(media),facts('用途与来源',{bindings:media.bindings || [],rights:media.rights,sha256:media.sha256}));$('compare-grid').append(section);}if(!state.comparisons.size)$('compare-grid').append(el('p','empty','先在素材卡中勾选需要比较的候选。'));$('compare-dialog').showModal();}));
$('projects').addEventListener('change',guard(()=>selectProject($('projects').value)));
$('all-objects').addEventListener('click',guard(async()=>{state.object=null;state.offset=0;$('scope-label').textContent='全部项目内容';$('tree').querySelectorAll('.active').forEach(row=>row.classList.remove('active'));await Promise.all([loadResources(),loadArtifacts()]);}));
$('filters').addEventListener('submit',guard(async event=>{event.preventDefault();state.offset=0;await loadResources();}));
$('previous').addEventListener('click',guard(async()=>{state.offset=Math.max(0,state.offset-state.limit);await loadResources();}));
$('next').addEventListener('click',guard(async()=>{state.offset+=state.limit;await loadResources();}));
$('refresh').addEventListener('click',guard(loadProjects));
for(const tab of ['media','artifacts'])$(`tab-${tab}`).addEventListener('click',()=>{$('media-view').hidden=tab!=='media';$('artifact-view').hidden=tab!=='artifacts';$('tab-media').setAttribute('aria-selected',String(tab==='media'));$('tab-artifacts').setAttribute('aria-selected',String(tab==='artifacts'));});
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>{dialog.querySelectorAll('video,audio').forEach(node=>node.pause());}));
$('session-open').addEventListener('click',()=>$('session-dialog').showModal());
$('session-form').addEventListener('submit',guard(async event=>{event.preventDefault();const session=await api('/api/v1/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('session-token').value})});$('session-token').value='';state.actor=session.actor;state.csrf=session.csrf_token;$('session-label').textContent=`操作人：${state.actor}`;$('upload-open').disabled=!state.writable;$('session-dialog').close();}));
$('upload-open').addEventListener('click',()=>$('upload-dialog').showModal());
$('upload-form').addEventListener('submit',guard(async event=>{event.preventDefault();const file=$('upload-file').files[0];if(!file)throw new Error('请选择文件');const rights=$('upload-rights').value;const scope=$('upload-scope').value.split(',').map(value=>value.trim()).filter(Boolean);if(rights!=='unknown' && !scope.length)throw new Error('请明确填写权利适用的用途');const button=event.target.querySelector('button[type=submit]');button.disabled=true;try{const receipt=await api(`${base()}/uploads`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),'X-CSRF-Token':state.csrf},body:file});const result=await api(`${base()}/media`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify({payload:{staged_upload:receipt.staged_upload,name:file.name,rights,rights_scope:{purposes:scope},source:{kind:'user_upload',content:$('upload-source').value}},expected_revision:state.revision,idempotency_key:crypto.randomUUID()})});state.revision=result.revision ?? state.revision;$('upload-dialog').close();event.target.reset();await loadResources();notice('素材已转存并登记，尚未绑定或批准用途。');}finally{button.disabled=false;}}));
guard(async()=>{const session=await api('/api/v1/session');state.actor=session.actor;state.csrf=session.csrf_token;if(session.actor)$('session-label').textContent=`操作人：${session.actor}`;state.previewCapabilities=await api('/api/v1/preview-capabilities');await loadProjects();})();
