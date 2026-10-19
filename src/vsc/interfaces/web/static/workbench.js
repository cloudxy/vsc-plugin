/* Creative reading workspace. Its views never own project facts or approvals. */
const SECTIONS = {
  overview: '创作概览', shots: '镜头', lines: '剧本与台词', assets: '资产',
  instances: '使用与状态', cues: '声音', performances: '动作与特效',
  bindings: '采用与候选', materials: '相关素材', states:'场镜状态',voices:'人物声线',jobs:'制作任务',versions: '文案版本',
  script_status: '剧本确认', job_attempts: '任务尝试对照',
};
const RELATION_SECTIONS = {job_attempts:'任务尝试对照',quality_observations:'质量记录',method_evaluations:'方法评测',timeline_media:'实际用料区间',candidates:'用途候选',coverage:'镜头覆盖',states:'场镜状态',voices:'人物与声线',interactions:'参与和接触',dispositions:'省略与处理依据',cue_shots:'声音覆盖镜头',cue_slots:'声音用途',cue_timeline_items:'声音时间区间',execution_shots:'动作覆盖镜头',execution_participants:'动作参与者',execution_materials:'动作参考与素材',execution_slots:'动作制作用途'};
const LABELS = {
  work: '部', episode: '集', scene: '场', sequence: '镜组', shot: '镜头', asset: '资产',
  character: '人物', location: '地点', prop: '道具', costume: '服装', voice: '声线', style: '风格',
  dialogue: '对白', narration: '旁白', action: '行动', ambience: '环境声', music: '音乐',
  foley: '拟音', sfx: '音效', silence: '静默', combat: '武术', dance: '舞蹈', vfx: '视觉特效',
  approved: '已批准', draft: '草稿', rejected: '已拒绝', retired: '已退役', selected: '当前采用',
  current: '当前版本', historical: '历史版本', candidate: '候选', missing: '资料缺失',
  pending: '待处理', pass: '通过', fail: '未通过', unknown: '尚未确定', unselected:'尚未采用',unassociated:'待关联',unverified:'尚未验证',instance:'使用实例',
  editing: '编辑中', pending_confirmation: '待人工确认', script_draft: '剧本工作副本',
  job_attempt: '制作尝试',
  job_attempts: '任务尝试对照',
  identity_face: '身份正脸', location_master: '场景母版', composition: '构图参考',
  first_frame: '首帧', last_frame: '尾帧', video_take: '镜头视频', dialogue_dry: '对白干声',
  voice_sample: '声音参考', style_reference: '风格参考',
  queued:'排队中',claimed:'准备提交',submitted:'已提交',succeeded:'已完成',failed:'失败',submission_unknown:'提交结果未知',usable:'可用于声明用途',video_clip:'镜头视频',speech:'配音',
  image:'图片',video:'视频',audio:'音频',preparation:'预备',initiation:'发动',contact:'接触',reaction:'反应',recovery:'收势',generation:'生成',live:'实拍','2d':'二维','3d':'三维',composite:'合成',attacker:'攻击方',defender:'防守方',caster:'施放者',target:'目标',screenplay:'剧本','shot-plan':'镜头计划','creative-relations':'创作关系',
};
const FIELDS = {
  purpose: '表达／用途', intention: '表达意图', objective: '行动目标', function: '场镜功能',
  description: '说明', action: '行动', emotion: '情绪变化', emotion_curve: '情绪进程',
  blocking: '场面调度', camera: '摄影与运镜', movement: '运动', entry: '进入状态', exit: '离开状态',
  entry_state: '进入状态', exit_state: '离开状态', state: '当时状态', placement: '位置',
  position: '位置', orientation: '朝向', hand: '持物手', quantity: '数量', variant_key: '外观／状态版本',
  instance_key: '使用实例', asset_kind: '资产类型', kind: '类型', line_kind: '内容类型',
  cue_kind: '声音类型', performance_kind: '表演类型', role: '用途', slot_key: '槽位',
  speaker_name: '说话人物', speaker_title: '说话人物', speaker: '说话人物', voice_name: '声线',
  diction: '发音', delivery: '语言表演', performance: '表演', post_chain: '声音处理',
  tempo: '速度', bpm: '每分钟拍数', meter: '拍号', beats: '节拍', phases: '动作分段',
  path: '路径', contact: '接触关系', reaction: '反馈', layers: '效果层', constraints: '必要要求',
  criteria: '验收依据', limitations: '限制', missing: '资料缺口', status: '状态',
  version: '版本', stage: '阶段', artifact_type: '文案类型', type: '类型',
  start_ms: '开始（毫秒）', end_ms: '结束（毫秒）', duration_ms: '实际时长（毫秒）',
  start_frame: '开始帧', end_frame: '结束帧', offset_frame: '成片起点帧', duration_frames: '帧数',
  source_in_frame: '源素材入点帧', source_out_frame: '源素材出点帧',
  start_char: '文字起点', end_char: '文字终点', track_key: '音轨', strategy: '衔接策略',
  shot_title: '镜头', asset_title: '资产身份', scene_title: '场次', evidence: '依据',
  parameters:'制作要求',domain:'专业领域',participant_count:'参与者数',shot_count:'覆盖镜头数',
  slot_count:'用途数',timeline_count:'时间线用料数',coverage_count:'覆盖关系数',use_count:'使用实例数',
  version_count:'规格版本数',selected_count:'已采用用途数',candidate_count:'候选数',
  subject_title:'动作发起者',object_title:'交互对象',instance_title:'使用实例',media_title:'素材',
  cue_title:'声音提示',execution_title:'表演／效果',line_title:'台词',capability_status:'方法验证状态',
  participants:'参与者',target:'目标',trigger:'触发',trajectory:'轨迹',range:'范围',
  occlusion:'遮挡',lighting:'光影',aftermath:'余波',contacts:'接触与反馈',
  start_pose:'起始姿态',end_pose:'结束姿态',formation:'队形',rhythm:'节奏',
  voice_identity:'声线身份',performance_intent:'表演意图',pronunciation:'发音',breath:'气息',
  screenplay:'剧本',shot_plan:'镜头计划',asset_bible:'资产设定',sound_plan:'声音计划',
  version_status:'文案状态',owner_version:'所属文案版本',current:'当前采用文案',
  condition:'完好状态',output_count:'输出数',unreviewed_output_count:'待审输出数',defect_code:'缺陷类别',
  effort_seconds:'主动工时（秒）',wait_seconds:'等待时长（秒）',cost_basis:'费用依据',cost_amount:'费用数值',cost_unit:'费用单位',model_version:'模型版本',fps_num:'帧率分子',fps_den:'帧率分母',
  missing_character_ranges:'尚未覆盖文字区间',coverage_status:'覆盖情况',disposition:'处理方式',
  candidate_no:'候选编号',attempt:'提交尝试次数',event_count:'事件数',plan_params:'固定制作参数',
  performance_coverage:'表演参数与有效请求对照',configured:'配置值',actual:'请求值',expected:'要求值',consumed:'已进入请求',model_default:'模型控制字段',field:'表演要求',fields_without_model_control:'未支持的专业控制',payload_note:'核验范围',
  uncovered_ranges:'尚未覆盖文字区间',current_coverage_count:'当前批准覆盖数',approved_dispositions:'已批准处理依据',reason:'理由',
  phase:'动作阶段',actor_role:'执行方',counterpart_role:'交互方',distance:'距离',direction:'方向',attack_defense:'攻防关系',support_foot:'支撑脚',force:'受力',after_state:'后续状态',acceptance:'验收判据',fallback:'替代方案',route:'制作路线',phrase:'乐句',synchronization:'同步要求',retiming:'重定时',seconds:'时间（秒）',pose:'关键姿态',world_rule:'世界规则',light_response:'光线反馈',environment_response:'环境反馈',aftereffects:'余波',sound:'效果声音',requires_plate:'需要底板',requires_mask:'需要遮罩',requires_depth:'需要深度',accent:'口音',rate:'语速',overlap:'重叠',processing:'声音处理',intelligibility:'可懂度',sync_criterion:'同步判据',target_seconds:'目标时长（秒）',controls:'控制要求',
};
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
};
const label = value => LABELS[value] || String(value ?? '');
function prose(value, depth = 0) {
  if (value == null) return '';
  if (typeof value === 'boolean')return value?'是':'否';
  if (typeof value !== 'object') return label(value);
  if (Array.isArray(value) && value.every(item=>item==null||typeof item!=='object')) return value.map(item=>label(item)).join('；');
  if (depth > 3) return '展开制作证据查看完整内容';
  if (Array.isArray(value)) return value.map(item => prose(item, depth + 1)).filter(Boolean).join('；');
  return Object.entries(value).filter(([key]) => !/(^id$|_id$|sha256|uri|url|path$)/.test(key) || key in FIELDS)
    .map(([key, item]) => `${FIELDS[key] || key}：${prose(item, depth + 1)}`).join('；');
}
function title(row) {
  return row.title || row.name || row.label || row.display_code || row.line_key || row.cue_key ||
    row.instance_key || row.performance_key || row.artifact_key || row.role || row.id || '已登记资料';
}
function sectionValue(data, key) {
  const value = data.sections?.[key] || {};
  return Array.isArray(value) ? {items: value, total: value.length} : {...value, items: value.items || []};
}

export function createCreativeWorkbench(container, {onObject, onMedia, onArtifact, onGraph, onCompare, onLocalAction, onError = () => {}} = {}) {
  let context = null, data = null, section = 'overview', offset = 0, ticket = 0, controller = null;
  let query = '', globalSearch = false, disposed = false, revision = null, entity = null;
  const host = el('div', null, 'creative-workbench');
  const heading = el('header', null, 'workbench-heading');
  const trail = el('nav', null, 'workbench-trail'); trail.setAttribute('aria-label', '当前创作范围');
  heading.append(trail);
  const form = el('form', null, 'workbench-search');
  const search = el('input'); search.type = 'search'; search.placeholder = '检索镜头、台词、资产与制作资料';
  search.setAttribute('aria-label', '检索创作资料'); search.maxLength = 200;
  const whole = el('input'); whole.type = 'checkbox';
  const wholeLabel = el('label'); wholeLabel.append(whole, document.createTextNode('全项目检索'));
  const submit = el('button', '检索'); submit.type = 'submit';
  const clear = el('button', '清除'); clear.type = 'button';
  form.append(search, wholeLabel, submit, clear);
  const filters = el('div', null, 'workbench-filters');
  const statusFilter=el('select');statusFilter.setAttribute('aria-label','资料版本与采用状态');
  for(const [value,name] of [['','全部版本与状态'],['current','当前文案版本'],['approved','已批准'],['draft','草稿'],['selected','当前采用素材'],['candidate','素材候选'],['unassociated','待关联素材']]){const o=el('option',name);o.value=value;statusFilter.append(o);}
  const kindFilter=el('select');kindFilter.setAttribute('aria-label','资料类型');
  for(const [value,name] of [['','全部资料类型'],...['character','location','prop','costume','voice','style','dialogue','narration','action','ambience','music','foley','sfx','silence','combat','dance','vfx','image','video','audio'].map(value=>[value,label(value)])]){const o=el('option',name);o.value=value;kindFilter.append(o);}
  const purposeFilter=el('select');purposeFilter.setAttribute('aria-label','制作用途');
  for(const [value,name] of [['','全部制作用途'],...['identity_face','location_master','composition','first_frame','last_frame','video_take','dialogue_dry','voice_sample','ambience','music','sfx','style_reference'].map(value=>[value,label(value)])]){const o=el('option',name);o.value=value;purposeFilter.append(o);}
  const associationFilter=el('select');associationFilter.setAttribute('aria-label','关联状态');
  for(const [value,name] of [['','全部关联状态'],['associated','已有关系'],['unassociated','待关联']]){const o=el('option',name);o.value=value;associationFilter.append(o);}
  filters.append(statusFilter,kindFilter,purposeFilter,associationFilter);form.append(filters);
  const navigation = el('nav', null, 'workbench-navigation'); navigation.setAttribute('aria-label', '创作资料类型');
  const counters = el('div', null, 'workbench-counters');
  const status = el('p', '', 'workbench-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const gaps = el('div', null, 'workbench-gaps');
  const body = el('div', null, 'workbench-content');
  const pagination = el('div', null, 'pagination');
  const prev = el('button', '上一页'), pageInfo = el('span'), next = el('button', '下一页');
  prev.type = next.type = 'button'; pagination.append(prev, pageInfo, next);
  host.append(heading, form, counters, navigation, status, gaps, body, pagination); container.replaceChildren(host);

  function prefKey() { return 'vsc.workbench.v1:' + JSON.stringify([context?.userId || 'reader', context?.projectId]); }
  function savePreference() {
    try { localStorage.setItem(prefKey(), JSON.stringify({section})); } catch { /* Optional view preference. */ }
  }
  function restorePreference() {
    try { const saved = JSON.parse(localStorage.getItem(prefKey()) || 'null'); section = saved?.section in SECTIONS ? saved.section : 'overview'; }
    catch { section = 'overview'; }
  }
  async function act(callback, ...args) {
    try { await callback?.(...args); } catch (error) { status.textContent = error.message; onError(error); }
  }
  function button(text, callback, cls) {
    const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', () => act(callback)); return b;
  }
  function objectButton(row, prefix = '') {
    return button(prefix + (row.title || row.label || row.display_code || row.id), () => onObject?.(row.id), 'workbench-object-link');
  }
  function drawNavigation() {
    navigation.replaceChildren();
    for (const [key, name] of Object.entries(SECTIONS)) {
      const b = button(name, async () => { section = key; entity = null; offset = 0; savePreference(); drawNavigation(); await request(); });
      b.setAttribute('aria-current', key === section ? 'page' : 'false'); b.dataset.section = key;
      navigation.append(b);
    }
    const more=el('details',null,'workbench-more');more.append(el('summary','质量与方法'));
    for(const key of ['quality_observations','method_evaluations'])more.append(button(RELATION_SECTIONS[key],()=>{section=key;entity=null;offset=0;return request();}));navigation.append(more);
  }
  function drawHeading() {
    trail.replaceChildren(button('全部项目', () => onObject?.(null)));
    for (const row of data.ancestors || []) trail.append(el('span', '›'), objectButton(row));
    const scope = data.scope;
    const current = el('strong', scope?.id ? title(scope) : '项目创作概览', 'workbench-current-scope');
    current.setAttribute('aria-current', 'location');
    trail.append(el('span', '›'), current);
    counters.replaceChildren();
    for (const key of Object.keys(SECTIONS).filter(key => key !== 'overview')) {
      const count = data.summary?.[key];
      if (count == null) continue;
      const n = typeof count === 'number' ? count : count.scope_total ?? count.total;
      if (n != null) counters.append(button(`${SECTIONS[key]} ${n}`, async () => { section = key; entity = null; offset = 0; drawNavigation(); await request(); }));
    }
  }
  function drawGaps() {
    gaps.replaceChildren();
    const messages = [...(data.gaps || []), ...(data.warnings || [])];
    if (!messages.length) return;
    const group = el('details', null, 'workbench-gap-list');
    group.append(el('summary', `资料缺口与查阅说明 · ${messages.length}`));
    const ul = el('ul');
    messages.forEach(value => ul.append(el('li', typeof value === 'string' ? value : value.message || value.description || value.code)));
    group.append(ul); gaps.append(group);
  }
  function appendFacts(target, row, skip = new Set()) {
    const fps=Number(row.fps_num)/Number(row.fps_den),time=value=>(value/fps).toFixed(3)+' 秒';
    if(fps>0&&Number.isFinite(fps)&&row.offset_frame!=null&&row.duration_frames!=null)target.append(el('p',`成片区间 ${time(row.offset_frame)} → ${time(row.offset_frame+row.duration_frames)} · ${fps.toFixed(3)} 帧／秒`,'hint'));
    if(fps>0&&Number.isFinite(fps)&&row.source_in_frame!=null&&row.source_out_frame!=null)target.append(el('p',`源素材区间 ${time(row.source_in_frame)} → ${time(row.source_out_frame)}`,'hint'));
    const dl = el('dl', null, 'workbench-facts');
    for (const [key, value] of Object.entries(row)) {
      if (skip.has(key) || !(key in FIELDS) || value == null || value === '' || (Array.isArray(value) && !value.length)) continue;
      if(key==='current'&&!row.artifact_id&&!row.owner_version)continue;
      const text = prose(value);
      if (!text) continue;
      dl.append(el('dt', FIELDS[key]), el('dd', text));
    }
    if (dl.childElementCount) target.append(dl);
  }
  function references(target, row, key) {
    const links = el('div', null, 'workbench-links');
    if (onLocalAction) {
      if (key === 'instances') links.append(button('替换这个实例版本', () => onLocalAction('replace_instance', row)));
      if (key === 'shots') links.append(button('只重做本镜声音', () => onLocalAction('redo_sound', row)));
      if (key === 'jobs' || key === 'job_attempts') links.append(button('新增一次抽样', () => onLocalAction('resample', row)));
    }
    const seen = new Set();
    const link = (kind, id, name) => {
      if (!id || seen.has(kind + ':' + id)) return;
      seen.add(kind + ':' + id);
      const fn = kind === 'media' ? onMedia : kind === 'artifact' ? onArtifact : onObject;
      links.append(button(name, () => fn?.(id)));
    };
    if (key === 'shots' || row.kind === 'shot' || key === 'assets') link('object', row.object_id || row.id, key === 'assets' ? '查看资产用途' : '进入镜头');
    if (key === 'shots' && row.id) links.append(button('查看覆盖剧本行', () => {section='coverage';entity=row.id;offset=0;revision=null;return request();}));
    if (key === 'jobs' && row.id) links.append(button('尝试与参数对照', () => {section='job_attempts';entity=row.id;offset=0;revision=null;return request();}));
    for (const [field, name] of [['shot_id', '定位镜头'], ['asset_id', '定位资产'], ['speaker_id', '定位人物'], ['voice_id','定位声线身份'],['scene_id', '定位场次'], ['target_object_id', '定位用途对象']]) link('object', row[field], name);
    for (const field of ['artifact_id', 'script_version_id', 'coverage_version_id', 'evidence_version_id', 'scope_version_id','method_artifact_id','criteria_artifact_id','trial_run_id','subtitle_version_id','lipsync_version_id']) link('artifact', row[field], '阅读固定文案');
    for (const field of ['media_id', 'reference_media_id', 'selected_media_id']) link('media', row[field], field === 'selected_media_id' ? '播放当前采用' : '预览素材');
    if (key === 'versions') link('artifact', row.artifact_id || row.id, '阅读此版本');
    const drill=(name,next,id)=>{if(id)links.append(button(name,()=>{section=next;entity=id;offset=0;revision=null;return request();}));};
    if(key==='lines'){drill('查看覆盖镜头','coverage',row.id);drill('查看声音','cues',row.id);drill('省略与处理','dispositions',row.id);}
    if(key==='assets')drill('查看使用实例','instances',row.id);
    if(key==='bindings')drill('查看此用途全部候选','candidates',row.id);
    if(key==='instances')drill('查看持物与接触','interactions',row.id);
    if(key==='cues'){drill('覆盖镜头','cue_shots',row.id);drill('配音与声音用途','cue_slots',row.id);drill('时间线区间','cue_timeline_items',row.id);}
    if(key==='performances'){drill('动作镜头','execution_shots',row.id);drill('参与者','execution_participants',row.id);drill('参考与素材','execution_materials',row.id);drill('制作用途','execution_slots',row.id);}
    if(key==='cue_timeline_items')drill('查看实际源区间','timeline_media',row.item_id);
    if(row.line_id)drill('对应台词','lines',row.line_id);
    if(onCompare&&row.media_id)links.append(button('加入候选比较',async()=>{await onCompare(row.media_id);status.textContent='已加入候选比较，可从上方比较入口并排查看。';}));
    for (const field of ['shots', 'assets', 'media', 'references', 'coverage','current_coverage', 'participants', 'participants_refs', 'shot_refs', 'media_refs']) {
      for (const ref of Array.isArray(row[field]) ? row[field] : []) {
        if (typeof ref === 'string') continue;
        if (ref.media_id) link('media', ref.media_id, ref.name || ref.title || '参考素材');
        else if (ref.shot_id || (field === 'shots' && ref.id)) link('object', ref.shot_id || ref.id, ref.title || ref.display_code || '关联镜头');
        else if (ref.asset_id || ref.object_id) link('object', ref.asset_id || ref.object_id, ref.title || ref.role || '关联资产');
      }
    }
    if (onGraph && row.id) {
      const graphKinds = {shots: 'object', assets: 'object', lines: 'line', instances: 'instance', cues: 'cue', performances: 'performance', bindings: 'slot', materials:'media',states:'state',voices:'voice', versions: 'artifact'};
      if (graphKinds[key]) links.append(button('关系与影响', () => onGraph(graphKinds[key] + ':' + (key==='voices'?row.voice_spec_id:row.id))));
    }
    if (links.childElementCount) target.append(links);
  }
  function mediaPreview(row) {
    const id = row.media_id || row.selected_media_id || row.id;
    const preview = row.preview || row.rendition || row.preview_purpose || (row.renditions || []).find(r=>['thumbnail','poster','waveform'].includes(r.purpose));
    if (!id || !preview) return null;
    const purpose = typeof preview === 'string' ? preview : preview.purpose;
    if (!['thumbnail', 'poster', 'waveform'].includes(purpose)) return null;
    const open = button('预览', () => onMedia?.(id), 'workbench-thumbnail');
    const img = el('img'); img.loading = 'lazy'; img.alt = row.name || title(row);
    img.src = `/api/v1/projects/${encodeURIComponent(context.projectId)}/media/${encodeURIComponent(id)}/preview?purpose=${encodeURIComponent(purpose)}`;
    img.addEventListener('error', () => { img.remove(); open.textContent = '查看素材详情'; }, {once: true});
    open.replaceChildren(img); return open;
  }
  function rowCard(row, key) {
    const card = el('article', null, 'workbench-card'); card.dataset.entityId = row.id || '';
    const header = el('header', null, 'workbench-card-heading');
    header.append(el('h3', title(row)));
    const statusValue = row.status || row.version_status || (row.current ? 'current' : (row.selected ? 'selected' : null));
    if (statusValue) header.append(el('span', label(statusValue), 'badge' + (['unknown', 'draft', 'rejected', 'missing'].includes(statusValue) ? ' warning' : '')));
    card.append(header);
    if (row.display_code && row.display_code !== title(row)) card.append(el('p', row.display_code, 'hint'));
    const thumb = mediaPreview(row); if (thumb) card.append(thumb);
    const text = row.text || row.excerpt || row.content_excerpt || row.summary_text || row.observation;
    if (text) card.append(el('p', text, 'workbench-excerpt'));
    if(key==='lines'&&row.coverage_truncated)card.append(el('p','覆盖摘要已截断，完整覆盖情况尚未确定。','badge warning'));
    else if(key==='lines'&&Array.isArray(row.uncovered_ranges))card.append(el('p',row.uncovered_ranges.length?'当前批准覆盖仍有文字缺口；请检查覆盖或已有省略依据。':'当前批准覆盖已涵盖此行全文。',row.uncovered_ranges.length?'hint':'badge'));
    appendFacts(card, row);
    if(key==='job_attempts') {
      const timeline=el('section',null,'workbench-attempt-events');timeline.append(el('h4','实际任务事件与输出'));
      for(const event of row.events||[]) timeline.append(el('p',`${event.at||''} · ${label(event.event)} · ${prose(event.evidence)||'未记录额外用量或错误'}`));
      if(!(row.events||[]).length)timeline.append(el('p','尚无任务事件，不能推断已提交或已有用量。','hint'));
      for(const output of row.outputs||[])timeline.append(button('预览本次输出',()=>onMedia?.(output.media_id)));
      card.append(timeline);
    }
    references(card, row, key);
    // Candidate sets and old versions stay discoverable without filling a shot's first screen.
    for (const [field, name] of [['candidates', '候选'], ['versions', '规格版本'], ['uses', '使用位置'], ['current', '当前采用'], ['selected', '当前采用']]) {
      if (!row[field] || typeof row[field] !== 'object') continue;
      const values = Array.isArray(row[field]) ? row[field] : [row[field]];
      if (!values.length) continue;
      const group = el('details', null, 'workbench-candidates'); group.append(el('summary', `${name} · ${row[field + '_total'] ?? values.length}`));
      for (const value of values) {
        const item = el('div', null, 'workbench-candidate'); item.append(el('p', title(value)));
        appendFacts(item, value); references(item, value, ''); group.append(item);
      }
      card.append(group);
    }
    if (row.candidate_count > (row.candidates || []).length) card.append(el('p', `共 ${row.candidate_count} 个候选；在素材列表按用途对象继续检索或比较。`, 'hint'));
    const evidence = el('details', null, 'workbench-evidence'); evidence.append(el('summary', '固定引用与制作证据'));
    evidence.append(el('pre', JSON.stringify(row, null, 2), 'structured')); card.append(evidence);
    return card;
  }
  function drawSection(key, compact = false) {
    const value = sectionValue(data, key), panel = el('section', null, 'workbench-section');
    const h = el('header', null, 'workbench-section-heading');
    h.append(el('h2', SECTIONS[key] || RELATION_SECTIONS[key] || key));
    const total = value.filtered_total ?? value.total ?? value.items.length;
    h.append(el('span', `${value.items.length} 项已加载 / ${total} 项命中${value.scope_total != null ? ' · 范围共 ' + value.scope_total + ' 项' : ''}`, 'hint'));
    if (compact) h.append(button('查看全部', async () => { section = key; entity = null; offset = 0; drawNavigation(); await request(); }));
    if(entity)h.append(button('显示此类型全部资料',async()=>{entity=null;offset=0;await request();}));
    panel.append(h);
    if (!value.items.length) panel.append(el('p',value.unsupported_filters?'此权威尚未提供所选筛选，匹配数量未知。可从素材入口使用已支持的检索。':value.load_on_demand?`已登记 ${total} 项，进入此类型按需查阅。`:(query?'此范围没有匹配资料。':'此范围尚未登记此类资料；可从固定文案和已有素材继续整理。'),'workbench-empty'));
    const grid = el('div', null, key === 'lines' || key === 'cues' ? 'workbench-grid workbench-grid-wide' : 'workbench-grid');
    value.items.forEach(row => grid.append(rowCard(row, key))); panel.append(grid);
    if (value.truncated || value.next_offset != null) panel.append(el('p', '当前为有界查询，更多资料可进入该类型继续分页。', 'hint'));
    return panel;
  }
  function render() {
    drawHeading(); drawNavigation(); drawGaps(); body.replaceChildren();
    if (section === 'overview') {
      const children = sectionValue(data, 'children');
      if (children.items.length) {
        const group = el('section', null, 'workbench-children'); group.append(el('h2', '进入创作范围'));
        for (const row of children.items) group.append(objectButton(row, label(row.kind) + ' · '));
        if (children.truncated || children.next_offset != null) group.append(el('p', '子级较多，可沿结构导航逐层展开，或直接检索目标。', 'hint'));
        body.append(group);
      }
      const keys = Object.keys(SECTIONS).filter(key => key !== 'overview' && (sectionValue(data,key).items.length || (sectionValue(data,key).load_on_demand && sectionValue(data,key).total>0)));
      if (!keys.length) body.append(el('p', '当前范围尚未登记创作资料。已有文件可从素材、文案与版本入口查阅；文件位置不会被自动当作创作关系。', 'empty'));
      keys.forEach(key => body.append(drawSection(key, true))); pagination.hidden = true;
    } else {
      body.append(drawSection(section)); const value = sectionValue(data, section);
      const total = value.filtered_total ?? value.total ?? value.items.length;
      pageInfo.textContent = `${value.items.length ? offset + 1 : 0}–${offset + value.items.length} / ${total}`;
      prev.disabled = offset === 0; next.disabled = value.next_offset == null; pagination.hidden = false;
    }
    status.textContent = (query ? `检索“${query}” · ${globalSearch ? '全项目' : '当前创作范围'} · ` : '') + `资料快照 r${data.revision}。`;
    host.removeAttribute('aria-busy');
  }
  async function request() {
    if (!context?.projectId || disposed) return;
    controller?.abort(); controller = new AbortController(); const seq = ++ticket;
    const snapshot = {...context}, params = new URLSearchParams({section, limit: '24', offset: String(offset)});
    if (snapshot.objectId && !(globalSearch && query)) params.set('object_id', snapshot.objectId);
    if (query) params.set('query', query);
    if (entity) params.set('entity_id',entity);
    for(const [key,input] of [['status',statusFilter],['kind',kindFilter],['purpose',purposeFilter],['association',associationFilter]])if(input.value)params.set(key,input.value.trim());
    if (revision != null && offset > 0) params.set('revision', String(revision));
    status.textContent = '正在读取当前范围的创作资料…'; host.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(`/api/v1/projects/${encodeURIComponent(snapshot.projectId)}/workbench?${params}`, {credentials: 'same-origin', signal: controller.signal});
      const value = await response.json();
      if (seq !== ticket || disposed) return;
      if (!response.ok) throw new Error(value.message || value.detail || '创作资料读取失败');
      if (value.project_id !== snapshot.projectId) throw new Error('资料响应与当前项目不一致');
      data = value; revision = data.revision; render();
    } catch (error) {
      if (seq !== ticket || disposed || error.name === 'AbortError') return;
      body.replaceChildren(el('p', error.message, 'workbench-empty'), button('重新读取当前范围', async () => { offset = 0; revision = null; await request(); }));
      status.textContent = '本次资料未能读取；其他已登记内容仍可从原入口查阅。';
      pagination.hidden = true; host.removeAttribute('aria-busy'); onError(error);
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); query = search.value.trim(); globalSearch = whole.checked; offset = 0; revision = null; return request(); });
  clear.addEventListener('click', () => { query = ''; search.value = ''; statusFilter.value='';kindFilter.value='';purposeFilter.value='';associationFilter.value='';entity=null;offset = 0; revision = null; return request(); });
  prev.addEventListener('click', () => { offset = Math.max(0, offset - 24); return request(); });
  next.addEventListener('click', () => { const value = sectionValue(data || {}, section); if (value.next_offset != null) { offset = value.next_offset; return request(); } });
  return {
    async load(nextContext) {
      controller?.abort(); ticket++; const changed = context?.projectId !== nextContext.projectId;
      context = {...nextContext}; offset = 0; revision = null; data = null; entity=null;
      if (changed) { restorePreference(); query = ''; search.value = ''; globalSearch = false; whole.checked = false;statusFilter.value='';kindFilter.value='';purposeFilter.value='';associationFilter.value=''; }
      body.replaceChildren(); gaps.replaceChildren(); counters.replaceChildren(); trail.replaceChildren(); drawNavigation();
      if (!context.projectId) { status.textContent = '选择项目后查阅创作资料。'; return; }
      return request();
    },
    async focus(nextSection) { if (nextSection in SECTIONS || nextSection in RELATION_SECTIONS) { section = nextSection; offset = 0; savePreference(); return request(); } },
    refresh: () => { offset = 0; revision = null; return request(); },
    destroy() { disposed = true; controller?.abort(); ticket++; container.replaceChildren(); },
  };
}
