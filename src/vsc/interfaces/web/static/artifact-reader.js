/* Full document reading, independent of storage-specific artifact envelopes. */
const TYPES = {
  creative_brief:'创作委托', source_map:'来源映射', adaptation_plan:'改编方案',
  adaptation_contract:'改编约定', story_bible:'故事设定', story_plan:'故事方案',
  quality_plan:'质量计划', coverage_plan:'覆盖计划', visual_bible:'视觉设定',
  episode_beats:'分集节拍', screenplay:'剧本', shot_plan:'镜头计划', asset_bible:'资产设定',
  sound_plan:'声音计划', scene_state:'场镜状态', sequence_links:'镜组衔接',
  generation_record:'生成记录', selected_takes:'采用候选', timeline:'剪辑时间线',
  delivery:'交付说明', delivery_manifest:'交付清单', local_production:'局部制作方案',
  animatic:'分镜预演', mix:'混音', production_run:'制作运行', sample_review:'试片审阅',
  media_qa:'媒体质量检查', claims_map:'主张依据', material_scope:'素材范围',
};
const FIELDS = {
  title:'标题', name:'名称', description:'说明', content:'正文', text:'文字', document:'文案',
  body:'正文', desired_experience:'期望体验', decision_owner:'决策负责人',
  conflict_policy:'冲突处理', objectives:'创作目标', nonnegotiables:'不可更改要求',
  goal:'目标', success_evidence:'达成依据',
  summary:'摘要', format:'文档格式', version:'版本', status:'状态', stage:'阶段',
  type:'类型', kind:'类型', artifact_type:'文案类型', artifact_key:'文案名称',
  objective:'目标', purpose:'用途', intention:'表达意图', function:'场镜功能',
  story:'故事', premise:'故事前提', logline:'一句话故事', genre:'类型', tone:'基调',
  audience:'观众', duration:'时长', duration_seconds:'时长（秒）', target_seconds:'目标时长（秒）',
  characters:'人物', character:'人物', locations:'地点', location:'地点', props:'道具',
  episodes:'分集', episode:'集', scenes:'场次', scene:'场次', sequences:'镜组', shots:'镜头',
  beats:'节拍', action:'行动', dialogue:'对白', lines:'台词', speaker:'说话人物',
  emotion:'情绪', emotion_curve:'情绪进程', blocking:'场面调度', camera:'摄影与运镜',
  movement:'运动', composition:'构图', lighting:'光线', sound:'声音', music:'音乐',
  ambience:'环境声', sfx:'音效', cues:'声音提示', entry_state:'进入状态', exit_state:'离开状态',
  participants:'参与者', constraints:'必要要求', criteria:'验收依据', limitations:'限制',
  evidence:'依据', sources:'来源', references:'参考', dependencies:'依赖', notes:'备注',
  reason:'理由', decisions:'决定', approved:'已批准', current:'当前版本',
  local_action:'局部制作操作', targets:'目标', parameters:'制作要求', tasks:'任务',
  start_ms:'开始（毫秒）', end_ms:'结束（毫秒）', start_frame:'开始帧', end_frame:'结束帧',
  duration_frames:'帧数', fps:'帧率', path:'路径', url:'链接', sha256:'内容摘要', id:'编号',
};
const node = (tag, cls, text) => {
  const value = document.createElement(tag);
  if (cls) value.className = cls;
  if (text != null) value.textContent = String(text);
  return value;
};
const words = value => String(value).replace(/([a-z\d])([A-Z])/g,'$1 $2').replace(/[_-]+/g,' ').trim();
function typeTitle(value) {
  const key = String(value).replace(/^vsc\./,'').replace(/-/g,'_');
  return TYPES[key] || words(String(value).replace(/^vsc\./,''));
}

function readableTitle(raw) {
  if(raw==null)return '';
  const filename=String(raw).trim().split(/[\\/]/).pop().replace(/\.(json|md|txt|ya?ml)$/i,'');
  const key=filename.replace(/^vsc\./,'').replace(/-/g,'_');
  if(TYPES[key])return TYPES[key];
  const technical=/^vsc\./i.test(filename) ||
    /[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/i.test(filename) ||
    /(?:^|[-_.:])[0-9a-f]{16,}(?:$|[-_.:])/i.test(filename) ||
    /^(?:artifact|art|document|doc|version|plan|spec)[_.:-]?[a-f0-9\d]{4,}$/i.test(filename) ||
    /^[A-Z]{1,8}[-_]?\d+(?:[-_]v?\d+)?$/.test(filename);
  return technical ? '' : words(filename);
}
export function artifactTitle(artifact) {
  for(const candidate of [artifact.title,artifact.name,artifact.artifact_key]){
    const title=readableTitle(candidate);if(title)return title;
  }
  return typeTitle(artifact.artifact_type || artifact.type || '') || '文案';
}

export function renderArtifactContent(content) {
  let value = content, structured = typeof content !== 'string';
  if (!structured) {
    try { value = JSON.parse(content); structured = true; } catch { /* Plain text stays literal. */ }
  }
  const body = node('div', 'document-content');
  if (!structured) {
    body.append(node('div', 'readable', content || '内容缺失或超过内置阅读限额。'));
    return {body, value: undefined};
  }
  // An explicit stack keeps every field and array item, even in deeply nested documents.
  const pending = [{value, parent:body}];
  while (pending.length) {
    const item = pending.pop(), data = item.value;
    if (data === null || typeof data !== 'object') {
      const text = data === null ? '未填写（null）' : typeof data === 'boolean' ? (data ? '是（true）' : '否（false）') : data === '' ? '空文本（""）' : String(data);
      item.parent.append(node('p', 'document-value', text));
    } else if (Array.isArray(data)) {
      if (!data.length) { item.parent.append(node('p','document-empty','空列表（[]）')); continue; }
      const list = node('ol','document-array'); item.parent.append(list);
      const children = data.map((value,index) => {
        const li = node('li','document-array-item'); li.setAttribute('aria-label',`第 ${index + 1} 项`); list.append(li);
        return {value,parent:li};
      });
      for(let i=children.length-1;i>=0;i--)pending.push(children[i]);
    } else {
      const entries = Object.entries(data);
      if (!entries.length) { item.parent.append(node('p','document-empty','空对象（{}）')); continue; }
      const fields = node('dl','document-fields'); item.parent.append(fields);
      const children = entries.map(([key,value]) => {
        const term = node('dt','document-field-name',FIELDS[key] || words(key) || key);
        if (!FIELDS[key] && words(key) !== key) term.append(node('small','document-field-key',key));
        const definition = node('dd','document-field-value'); fields.append(term,definition);
        return {value,parent:definition};
      });
      for(let i=children.length-1;i>=0;i--)pending.push(children[i]);
    }
  }
  return {body,value};
}
