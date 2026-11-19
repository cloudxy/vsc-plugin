/** Canvas video, sample-upgrade, breakdown and script nodes. Local processing only. */
const TTL_CHANGE = Date.parse('2026-10-28T02:00:00Z');

export const COPY = {
  media: {
    asset_voice_name: '{name}音色',
    audio_decode_unsupported: '当前浏览器不支持音频解码',
    audio_not_playable: '音频资源不可播放',
    audio_playback_failed: '音频播放失败',
    audio_resource_read_failed: '音频资源读取失败',
    capture_area_init_failed: '截图区域初始化失败',
    capture_generate_failed: '截图生成失败',
    crop_session_expired: '裁剪会话已失效',
    role_voice: '角色音色',
    video_frame_capture_failed: '视频帧截图失败',
    video_frame_read_failed: '视频帧读取失败',
    video_size_read_failed: '视频尺寸读取失败',
  },
  mediaEdit: {
    canvas_version_changed: '画布版本已变化，请返回画布刷新后重试',
    export: '导出',
    no_exportable_clips: '当前轨道中没有可导出的视频片段',
    source_video_required: '画布视频剪辑需要有效的来源视频节点',
    video_export_failed: '视频合成导出失败',
  },
  image: {
    title: '高清放大',
    hint: '生成式超清会补充细节，文字与局部图案可能变化。支持单张 JPEG/PNG，最大 4.7MB、4096×4096，宽高比为 1:3 至 3:1。',
    types: [['general', '通用'], ['low_resolution', '低清修复'], ['3d_animation', '3D 动画'], ['high_fidelity', '高保真'], ['text_optimization', '文字优化']],
    generate: '生成',
  },
  video: {title: '视频高清', resolutions: ['1080p', '2K', '4K'], interpolate: '补帧', slow: '慢放', factors: [1, 2, 3, 5]},
  remake: {
    title: '片段重拍',
    overlap: '重拍片段之间不能重叠',
    duration: '每个片段至少 4 秒，且不能超出视频时长',
    limit: '最多支持 5 个重拍片段',
    source: '仅支持不短于 4 秒的视频',
    tags: '提示词中的时间标签与重拍片段不一致',
    resolutions: ['480P', '720P', '1080P', '2K', '4K'],
  },
  erase: {title: '智能去字幕', smart: '智能擦除', region: '框选擦除', undo: '撤销', redo: '重做', reset: '重置', limit: '最多框选 10 个擦除区域', generate: '开始智能去字幕'},
  depth: {title: '深度动作捕捉', p480: '480P 最长支持 3 分钟', p720: '720P 最长支持 30 秒', confirm: '确认提取'},
  sample: {badge: '样片 · 480P', expired: '原样片任务已过有效期，保留原480p结果，无法再升级'},
  lyrics: {
    empty: '歌词内容不能为空',
    unsaved: '请先保存或取消歌词编辑后再关闭',
    lineCount: count => `共 ${count} 行`,
    duration: value => `时长 ${value}`,
    lrc: 'LRC 导入',
    ai: 'AI 音频对齐',
    edit: '编辑歌词',
    expand: '放大歌词时间线',
    save: '保存',
    cancel: '取消',
  },
  storyboard: {invalid: '歌词分镜格式异常', instrumental: '纯音乐段', shot: index => `镜头 ${index}`, count: count => `共 ${count} 个镜头`, fanout: '铺开视频生成器'},
  script: {
    title: '脚本生成器',
    starters: [['script', '剧本生成分镜脚本'], ['characters', '角色生成分镜脚本'], ['video', '视频参考生成分镜脚本']],
    creative: '创意视图',
    script: '脚本视图',
    show: '全部显示',
    hide: '全部隐藏',
    parsing: '解析中…',
    failed: '脚本解析失败，请重试',
    empty: '暂无脚本镜头',
  },
  scriptDocument: {
    view: '查看剧本资料',
    authority: '这里显示当前保存的完整剧本资料；节点预览可能是创建时版本，在画布上修改文字不会改写剧本资料。',
    hint: '这里显示已保存的完整剧本资料。修改画布节点不会修改这份资料。',
    excerpt: '节点预览节选',
    isolated: '画布上的文字编辑不会改写剧本资料',
    failed: '剧本资料加载失败，请重试。',
  },
  mv: {music: '请先接入一段音乐', images: '参考图最多 4 张', save: '保存 Brief'},
  breakdown: {title: '智能拉片', storyboard: '分镜', video: '视频', audio: '音频', start: '开始拉片'},
  menu: ['区间剪辑', '多视频合成剪辑', '深度动作捕捉', '智能去字幕', '片段重拍', '视频高清', '智能拉片', '视频故事解析', '提取带时码剧本', '角色音色命名'],
};

export function mediaDiagnostic(code, name) {
  const template = COPY.media[code];
  if (!template) return '';
  return template.replace('{name}', name || '');
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(label, action) {
  const node = el('button', label);
  node.type = 'button';
  node.addEventListener('click', async event => {
    event?.preventDefault?.();
    await action(event);
  });
  return node;
}

export function validateImageSpec({count = 1, mime = '', bytes = 0, width = 0, height = 0} = {}) {
  if (count !== 1 || !['image/jpeg', 'image/png'].includes(mime)) return {ok: false, message: '仅支持单张 JPEG 或 PNG'};
  if (bytes > 4.7 * 1024 * 1024) return {ok: false, message: '图片不能超过 4.7MB'};
  if (width > 4096 || height > 4096) return {ok: false, message: '图片宽高不能超过 4096'};
  if (!(width > 0 && height > 0) || width / height < 1 / 3 || width / height > 3) return {ok: false, message: '宽高比须在 1:3 至 3:1 之间'};
  return {ok: true, message: ''};
}

function tagPairs(prompt) {
  return [...String(prompt || '').matchAll(/\[(\d{2}):(\d{2})\.(\d{3})-(\d{2}):(\d{2})\.(\d{3})\]/g)].map(match => {
    const to = parts => Number(parts[0]) * 60 + Number(parts[1]) + Number(parts[2]) / 1000;
    return [to(match.slice(1, 4)), to(match.slice(4, 7))];
  });
}

export function validateRemake({duration = 0, segments = [], prompt = ''} = {}) {
  if (!(duration >= 4)) return {ok: false, message: COPY.remake.source};
  if (!Array.isArray(segments) || !segments.length) return {ok: false, message: '请至少选择 1 个重拍片段'};
  if (segments.length > 5) return {ok: false, message: COPY.remake.limit};
  const ordered = segments.map(item => [Number(item.start), Number(item.end)]).sort((a, b) => a[0] - b[0]);
  if (ordered.some(([start, end]) => !(end - start >= 4) || start < 0 || end > duration + 0.05)) return {ok: false, message: COPY.remake.duration};
  for (let index = 1; index < ordered.length; index += 1) if (ordered[index][0] < ordered[index - 1][1] - 0.001) return {ok: false, message: COPY.remake.overlap};
  const tags = tagPairs(prompt);
  const mismatch = tags.length !== ordered.length || tags.some((tag, index) => Math.abs(tag[0] - ordered[index][0]) > 0.001 || Math.abs(tag[1] - ordered[index][1]) > 0.001);
  if (mismatch) return {ok: false, message: COPY.remake.tags};
  return {ok: true, message: '', segments: ordered.map(([start, end]) => ({start, end}))};
}

export function createEraseSession() {
  let boxes = [];
  const undoStack = [];
  const redoStack = [];
  const snap = () => boxes.map(item => ({...item}));
  return {
    mode: 'smart',
    get boxes() { return snap(); },
    push(box) {
      if (boxes.length >= 10) throw new Error(COPY.erase.limit);
      undoStack.push(snap());
      redoStack.length = 0;
      boxes = [...boxes, {...box}];
    },
    undo() { if (!undoStack.length) return false; redoStack.push(snap()); boxes = undoStack.pop(); return true; },
    redo() { if (!redoStack.length) return false; undoStack.push(snap()); boxes = redoStack.pop(); return true; },
    reset() { undoStack.push(snap()); redoStack.length = 0; boxes = []; },
  };
}

export function validateDepth({clarity = '480p', duration = 0} = {}) {
  const key = String(clarity).toLowerCase();
  if (key === '480p' && duration > 180) return {ok: false, message: COPY.depth.p480};
  if (key === '720p' && duration > 30) return {ok: false, message: COPY.depth.p720};
  if (!['480p', '720p'].includes(key)) return {ok: false, message: '清晰度须为 480p 或 720p'};
  return {ok: true, message: ''};
}

export function isSampleVideo(params) {
  if (!params || typeof params !== 'object') return false;
  const resolution = String(params.resolution || '').toLowerCase();
  if (['1080p', '1080', '2k', '4k'].includes(resolution)) return false;
  if (params.sample === true) return true;
  if (resolution === '480p' || resolution === '480') return true;
  return typeof params.draft_task_id === 'string' && params.draft_task_id.trim() && ['', '480p', '480'].includes(resolution);
}

function formatUtc(ms) {
  const date = new Date(ms);
  const pad = value => String(value).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

export function sampleDeadline(createdAt) {
  const created = Date.parse(createdAt);
  if (!Number.isFinite(created)) return null;
  const days = created >= TTL_CHANGE ? 14 : 7;
  return {created, deadline: created + days * 86400000, days};
}

export function sampleTooltip(params, now = new Date()) {
  const windowInfo = sampleDeadline(params?.created_at || params?.task_created_at);
  if (!windowInfo) return COPY.sample.badge;
  const lines = [COPY.sample.badge, `· 样片任务创建时间：${formatUtc(windowInfo.created)}`, `· 正片生成截止时间：${formatUtc(windowInfo.deadline)}（任务开始起${windowInfo.days}天）`];
  if (now.getTime() >= windowInfo.deadline) lines.push('· 逾期需重新生成样片。');
  return lines.join('\n');
}

export function upgradeButtonLabel(units) {
  return `生成 1080P · ✦ ${units}`;
}

export function validateLyrics(text) {
  if (typeof text !== 'string' || !text.trim() || text.split('\n').some(line => !line.trim())) return {ok: false, message: COPY.lyrics.empty};
  return {ok: true, lines: text.split('\n'), message: ''};
}

export function lyricsSourceBadge(source) {
  if (source === 'lrc') return COPY.lyrics.lrc;
  if (source === 'ai_align') return COPY.lyrics.ai;
  return '歌词时间线';
}

export function validateStoryboard(value) {
  const shots = Array.isArray(value) ? value : value?.shots;
  if (!Array.isArray(shots) || !shots.length) return {ok: false, message: COPY.storyboard.invalid};
  const normal = [];
  for (const [offset, shot] of shots.entries()) {
    if (!shot || typeof shot !== 'object' || typeof shot.index === 'boolean') return {ok: false, message: COPY.storyboard.invalid};
    const index = shot.index ?? offset + 1;
    if (!Number.isInteger(index) || index < 1) return {ok: false, message: COPY.storyboard.invalid};
    const instrumental = Boolean(shot.instrumental || shot.pure_music);
    const text = String(shot.text || shot.lyric || '');
    if (!instrumental && !text.trim()) return {ok: false, message: COPY.storyboard.invalid};
    normal.push({index, text: instrumental ? '' : text.trim(), instrumental});
  }
  return {ok: true, shots: normal, message: ''};
}

export function validateMvBrief(brief = {}) {
  if (!brief.has_music && !String(brief.music_node_id || '').trim()) return {ok: false, message: COPY.mv.music};
  const images = brief.image_node_ids || [];
  if (!Array.isArray(images) || images.length > 4) return {ok: false, message: COPY.mv.images};
  const mvType = brief.mv_type || 'mixed';
  const aspect = brief.aspect_ratio || '16:9';
  if (!['narrative', 'emotional', 'performance', 'mixed'].includes(mvType)) return {ok: false, message: 'MV 类型无效'};
  if (!['16:9', '9:16', '1:1', 'custom'].includes(aspect)) return {ok: false, message: '画幅无效'};
  if (typeof (brief.visual_style || '') !== 'string' || (brief.visual_style || '').length > 2000) return {ok: false, message: '视觉风格须为 2000 字以内的文本'};
  return {ok: true, message: '', brief: {...brief, mv_type: mvType, aspect_ratio: aspect, visual_style: brief.visual_style || ''}};
}

export const STORY_COLUMNS = [
  ['shot', '镜号'], ['range', '起止'], ['shot_size', '景别'], ['angle', '机位'], ['movement', '运动'],
  ['focus', '焦距景深'], ['light', '光线'], ['narrative', '叙事'], ['description', '画面描述'],
  ['image_prompt', '图像提示词'], ['motion_prompt', '运动提示词'], ['voice', '人声/音效'], ['music', '背景音乐'], ['keyframe', '关键帧缩略图'],
];

export function columnText(rows, key) {
  return (rows || []).map(row => row?.[key] ?? '').join('\n');
}

export function parseStory(text) {
  try {
    const value = JSON.parse(text || '{}');
    return Array.isArray(value?.rows) ? value.rows : [];
  } catch {
    return [];
  }
}

function panel(host, title, className) {
  const dialog = el('div', null, `cvst-panel ${className || ''}`);
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-label', title);
  dialog.append(el('h3', title));
  (host.root || document.body).append(dialog);
  return dialog;
}
function notice(host, error) {
  host.notice?.(error?.message || String(error || ''));
}
function subkind(node) {
  return node?.params?.canvas_subkind || '';
}

export function mountVideoScriptMenu(tools, host, node, card) {
  if (!tools || !node) return;
  const items = [
    ['区间剪辑', () => host.openClip?.(node)],
    ['多视频合成剪辑', () => host.openMulti?.(node)],
    ['深度动作捕捉', () => openDepth(host, node)],
    ['智能去字幕', () => openErase(host, node)],
    ['片段重拍', () => openRemake(host, node)],
    ['视频高清', () => openVideoUpscale(host, node)],
    ['智能拉片', () => openBreakdown(host, node)],
    ['视频故事解析', () => run(host, node, 'video_story', {})],
    ['提取带时码剧本', () => run(host, node, 'video_script_extract', {})],
    ['角色音色命名', () => openRoleVoice(host, node)],
  ];
  for (const [label, action] of items) tools.append(button(label, () => Promise.resolve().then(action).catch(error => notice(host, error))));
  const code = node.params?.media_diagnostic;
  if (code && COPY.media[code]) card?.append?.(el('p', mediaDiagnostic(code, node.params?.role_voice_name), 'cvst-media-diagnostic'));
  const video = card?.querySelector?.('video');
  video?.addEventListener?.('error', () => card.append(el('p', COPY.media.video_frame_read_failed, 'cvst-media-diagnostic')));
}

async function run(host, node, operation, settings) {
  if (!host.apply) throw new Error('当前画布不能提交本机处理');
  return host.apply(operation, settings, node.id);
}

function openRoleVoice(host, node) {
  const dialog = panel(host, COPY.media.role_voice, 'cvst-role-voice');
  const input = el('input');
  input.value = node.params?.role_voice_name || '';
  input.setAttribute('aria-label', '角色音色名称');
  dialog.append(input, button('确定', () => {
    const name = input.value.trim();
    if (!name) return;
    host.change?.(() => { node.params = {...(node.params || {}), role_voice_name: name}; });
    dialog.remove();
    host.notice?.(mediaDiagnostic('asset_voice_name', name));
  }));
}

function openVideoUpscale(host, node) {
  const dialog = panel(host, COPY.video.title, 'cvst-video-upscale');
  const state = {resolution: '1080p', interpolate: false, slow: false, factor: 2};
  const row = el('div', null, 'cvst-choices');
  for (const label of COPY.video.resolutions) row.append(button(label, () => { state.resolution = label.toLowerCase(); }));
  const interpolate = el('input'); interpolate.type = 'checkbox'; interpolate.setAttribute('aria-label', COPY.video.interpolate);
  interpolate.addEventListener('change', () => { state.interpolate = interpolate.checked; });
  const slow = el('input'); slow.type = 'checkbox'; slow.setAttribute('aria-label', COPY.video.slow);
  const factors = el('div', null, 'cvst-slow-factors');
  factors.hidden = true;
  for (const factor of COPY.video.factors) factors.append(button(`${factor}x`, () => { state.factor = factor; }));
  slow.addEventListener('change', () => { state.slow = slow.checked; factors.hidden = !slow.checked; });
  dialog.append(row, el('label', COPY.video.interpolate), interpolate, el('label', COPY.video.slow), slow, factors, button(COPY.image.generate, () => run(host, node, 'video_upscale', {resolution: state.resolution, interpolate: state.interpolate, slow: state.slow, slow_factor: state.factor}).then(() => dialog.remove())));
}

export function mountImageUpscaleButton(parent, host, node) {
  parent?.append?.(button('高清放大', () => Promise.resolve().then(() => openImageUpscale(host, node)).catch(error => notice(host, error))));
}

function openImageUpscale(host, node) {
  const dialog = panel(host, COPY.image.title, 'cvst-image-upscale');
  dialog.append(el('p', COPY.image.hint, 'cvst-hint'));
  const state = {model_type: 'general', scale: 2};
  const types = el('div', null, 'cvst-choices');
  for (const [value, label] of COPY.image.types) types.append(button(label, () => { state.model_type = value; }));
  const scales = el('div', null, 'cvst-choices');
  for (const scale of [2, 4, 6]) scales.append(button(`${scale}x`, () => { state.scale = scale; }));
  const report = el('p', '', 'cvst-report');
  dialog.append(types, scales, report, button(COPY.image.generate, async () => {
    const spec = node.params?.image_spec;
    if (spec) {
      const check = validateImageSpec(spec);
      if (!check.ok) { report.textContent = check.message; return; }
    }
    await run(host, node, 'image_upscale', {model_type: state.model_type, scale: state.scale});
    dialog.remove();
  }));
  return dialog;
}

function openRemake(host, node) {
  const dialog = panel(host, COPY.remake.title, 'cvst-remake');
  const state = {segments: [], resolution: '720P', prompt: ''};
  const list = el('div', null, 'cvst-segments');
  const prompt = el('textarea');
  prompt.setAttribute('aria-label', '重拍提示词');
  prompt.addEventListener('input', () => { state.prompt = prompt.value; });
  const resolutions = el('div', null, 'cvst-choices');
  for (const label of COPY.remake.resolutions) resolutions.append(button(label, () => { state.resolution = label; }));
  const report = el('p', '', 'cvst-report');
  dialog.append(list, button('添加 4 秒片段', () => {
    const start = state.segments.reduce((end, item) => Math.max(end, item.end), 0);
    state.segments.push({start, end: start + 4});
    list.append(el('span', `[${state.segments.length}] ${start}-${start + 4}`));
  }), prompt, resolutions, report, button('提交生成', async () => {
    const duration = Number(node.params?.duration_seconds || node.params?.duration || 0);
    const check = validateRemake({duration, segments: state.segments, prompt: state.prompt});
    if (!check.ok) { report.textContent = check.message; return; }
    await run(host, node, 'video_segment_remake', {segments: state.segments, prompt: state.prompt, resolution: state.resolution});
    dialog.remove();
  }));
}

function openErase(host, node) {
  const dialog = panel(host, COPY.erase.title, 'cvst-erase');
  const session = createEraseSession();
  const stage = el('div', null, 'cvst-erase-stage');
  stage.setAttribute('aria-label', '擦除画面');
  const paint = () => { stage.replaceChildren(...session.boxes.map((box, index) => el('span', String(index + 1), 'cvst-erase-box'))); };
  dialog.append(
    button(COPY.erase.smart, () => { session.mode = 'smart'; }),
    button(COPY.erase.region, () => { session.mode = 'region'; }),
    stage,
    button(COPY.erase.undo, () => { session.undo(); paint(); }),
    button(COPY.erase.redo, () => { session.redo(); paint(); }),
    button(COPY.erase.reset, () => { session.reset(); paint(); }),
    button('框选', () => { try { session.push({x: 0.1, y: 0.7, w: 0.3, h: 0.15}); paint(); } catch (error) { notice(host, error); } }),
    button(COPY.erase.generate, () => run(host, node, 'video_dewatermark', {mode: session.mode, regions: session.boxes}).then(() => dialog.remove())),
  );
  dialog.eraseSession = session;
}

function openDepth(host, node) {
  const dialog = panel(host, COPY.depth.title, 'canvas-video-depth-panel');
  const state = {clarity: '480p'};
  const report = el('p', '', 'cvst-report');
  dialog.append(
    button('480p', () => { state.clarity = '480p'; }),
    button('720p', () => { state.clarity = '720p'; }),
    report,
    button(COPY.depth.confirm, async () => {
      const check = validateDepth({clarity: state.clarity, duration: Number(node.params?.duration_seconds || 0)});
      if (!check.ok) { report.textContent = check.message; return; }
      await run(host, node, 'video_depth_map', {clarity: state.clarity, duration_seconds: Number(node.params?.duration_seconds || 0)});
      dialog.remove();
    }),
  );
}

function openBreakdown(host, node) {
  const dialog = panel(host, COPY.breakdown.title, 'cvst-breakdown');
  const picked = {storyboard: true, video: true, audio: true};
  for (const [key, label] of [['storyboard', COPY.breakdown.storyboard], ['video', COPY.breakdown.video], ['audio', COPY.breakdown.audio]]) {
    const input = el('input');
    input.type = 'checkbox';
    input.checked = true;
    input.setAttribute('aria-label', label);
    input.addEventListener('change', () => { picked[key] = input.checked; });
    const labelNode = el('label', label);
    labelNode.append(input);
    dialog.append(labelNode);
  }
  dialog.append(button(COPY.breakdown.start, async () => {
    const dimensions = Object.entries(picked).filter(([, on]) => on).map(([key]) => key);
    if (!dimensions.length) throw new Error('请至少选择一个拉片维度');
    await run(host, node, 'video_breakdown', {dimensions});
    dialog.remove();
  }));
}

export function mountSampleBadge(card, host, node) {
  if (!card || node?.type !== 'video' || !isSampleVideo(node.params)) return false;
  const badge = el('div', null, 'cvst-sample-badge');
  const tipText = sampleTooltip(node.params);
  badge.append(el('strong', COPY.sample.badge), el('p', tipText === COPY.sample.badge ? '可一键升级 1080P 高清正片' : tipText, 'cvst-sample-tip'));
  const action = button('生成 1080P · ✦ …', async () => {
    const quote = await host.quote?.('sample_upgrade', {
      duration_seconds: Number(node.params?.duration_seconds || 1),
      created_at: node.params?.created_at || node.params?.task_created_at,
      draft_task_id: node.params?.draft_task_id || '',
    });
    if (!quote?.ready) throw new Error(quote?.message || COPY.sample.expired);
    action.textContent = upgradeButtonLabel(quote.total_price);
    await run(host, node, 'sample_upgrade', {
      draft_task_id: node.params?.draft_task_id || node.id,
      created_at: node.params?.created_at || node.params?.task_created_at,
      duration_seconds: Number(node.params?.duration_seconds || quote.total_price || 1),
      resolution: '1080P',
    });
  });
  Promise.resolve(host.quote?.('sample_upgrade', {
    duration_seconds: Number(node.params?.duration_seconds || 1),
    created_at: node.params?.created_at || node.params?.task_created_at,
    draft_task_id: node.params?.draft_task_id || '',
  })).then(quote => {
    if (quote?.ready && action.isConnected) action.textContent = upgradeButtonLabel(quote.total_price);
  }).catch(() => {});
  action.className = 'cvst-upgrade';
  badge.append(action);
  card.append(badge);
  return true;
}

export function mountEditCanvasExport(row, host, node, context = {}) {
  if (!row) return;
  row.append(button(COPY.mediaEdit.export, async () => {
    let saved = [];
    try { saved = JSON.parse(node.params?.segments_json || '[]'); } catch { saved = []; }
    const segments = Array.isArray(saved) && saved.length ? saved.map(item => ({
      source_node_id: item.source_node_id || item.node_id,
      start_seconds: Number(item.start_seconds ?? item.start_time ?? 0),
      end_seconds: item.end_seconds ?? item.end_time ?? null,
    })).filter(item => item.source_node_id) : (context.videos || []).map(video => ({
      source_node_id: video.id,
      start_seconds: Number(video.params?.leftClipTime || 0),
      end_seconds: video.params?.rightClipTime ?? null,
    }));
    if (!segments.length) throw new Error(COPY.mediaEdit.no_exportable_clips);
    const audios = context.audios || [];
    if (audios.length > 1) throw new Error('最多只能接入 1 条背景或参考音轨');
    await run(host, node, 'multi_video_edit', {segments, background_audio_node_id: audios[0]?.id || null});
    host.notice?.('已在画布内合成导出视频');
  }));
}

export function mountAiMvBrief(empty, host) {
  if (!empty) return;
  const form = el('form', null, 'cvst-mv-brief');
  form.setAttribute('aria-label', '导演 Brief');
  const music = el('input');
  music.setAttribute('aria-label', '音乐');
  music.placeholder = '音乐节点';
  const images = el('input');
  images.setAttribute('aria-label', '参考图');
  images.placeholder = '参考图节点，最多 4 张';
  const type = el('select');
  for (const [value, label] of [['narrative', '剧情叙事'], ['emotional', '情绪表达'], ['performance', '歌手表演'], ['mixed', '混合']]) {
    const option = el('option', label); option.value = value; type.append(option);
  }
  type.value = 'mixed';
  type.setAttribute('aria-label', 'MV 类型');
  const aspect = el('select');
  for (const [value, label] of [['16:9', '16:9'], ['9:16', '9:16'], ['1:1', '1:1'], ['custom', '用户指定']]) {
    const option = el('option', label); option.value = value; aspect.append(option);
  }
  aspect.value = '16:9';
  aspect.setAttribute('aria-label', '画幅');
  const style = el('textarea');
  style.setAttribute('aria-label', '视觉风格');
  const report = el('p', '', 'cvst-report');
  form.append(el('label', '音乐'), music, el('label', '参考图 ≤4'), images, type, aspect, style, report, button(COPY.mv.save, () => {
    const imageIds = images.value.split(',').map(item => item.trim()).filter(Boolean);
    const brief = {has_music: Boolean(music.value.trim()), music_node_id: music.value.trim(), image_node_ids: imageIds, mv_type: type.value, aspect_ratio: aspect.value, visual_style: style.value};
    const check = validateMvBrief(brief);
    if (!check.ok) { report.textContent = check.message; return; }
    host.change?.(() => {
      const id = host.newId?.() || `mv-${Date.now()}`;
      host.document?.nodes?.push?.({id, type: 'text', title: 'AI MV 导演 Brief', x: 120, y: 120, text: JSON.stringify(brief), params: {canvas_subkind: 'mv_brief', mv_type: brief.mv_type, aspect_ratio: brief.aspect_ratio}, media_id: null, job_id: null, group: ''});
      form.hidden = true;
    });
    host.apply?.('mv_brief', brief, host.document?.nodes?.at?.(-1)?.id);
  }));
  form.addEventListener('submit', event => event.preventDefault());
  const container = empty.classList?.contains?.('cc-mv-guide') && host?.root ? host.root : empty;
  container.querySelector?.('.cvst-mv-brief')?.remove?.();
  form.hidden = Boolean(host?.document?.nodes?.length);
  container.append(form);
}

function owned(node) {
  const kind = subkind(node);
  const schema = node?.params?.schema;
  return ['video_story', 'video_breakdown', 'lyrics_timeline', 'lyrics_storyboard', 'script_generator', 'script_document', 'mv_brief'].includes(kind)
    || ['video_story_node/v1', 'lyrics_timeline/v1', 'lyrics_storyboard_result'].includes(schema)
    || Boolean(node?.params?.smartVideoBreakdownResult);
}

export function mountVideoScriptCard(card, host, node) {
  if (!owned(node)) return false;
  const kind = subkind(node) || (node.params?.schema === 'video_story_node/v1' ? 'video_story' : '') || (node.params?.smartVideoBreakdownResult ? 'video_breakdown' : '') || (node.params?.schema === 'lyrics_timeline/v1' ? 'lyrics_timeline' : '') || (node.params?.schema === 'lyrics_storyboard_result' ? 'lyrics_storyboard' : '');
  if (kind === 'video_story' || node.params?.schema === 'video_story_node/v1') mountStory(card, host, node);
  else if (kind === 'video_breakdown' || node.params?.smartVideoBreakdownResult) mountBreakdownResult(card, node);
  else if (kind === 'lyrics_timeline' || node.params?.schema === 'lyrics_timeline/v1') mountLyrics(card, host, node);
  else if (kind === 'lyrics_storyboard' || node.params?.schema === 'lyrics_storyboard_result') mountStoryboard(card, host, node);
  else if (kind === 'script_generator') mountScript(card, host, node);
  else if (kind === 'script_document') mountScriptDocument(card, host, node);
  else if (kind === 'mv_brief') card.append(el('pre', node.text || '', 'cvst-mv-brief-result'));
  return true;
}

function mountBreakdownResult(card, node) {
  const box = el('div', null, 'cvst-breakdown-result');
  box.dataset.smartVideoBreakdownResult = node.params?.smartVideoBreakdownResult || '';
  box.append(el('p', node.text || '', 'cvst-breakdown-text'));
  card.append(box);
}

function mountStory(card, host, node) {
  const rows = parseStory(node.text);
  const locked = node.params?.schema === 'video_story_node/v1' || node.params?.locked === true;
  const box = el('div', null, 'cvst-story');
  const table = storyTable(rows);
  box.append(table);
  if (!locked) box.append(button('重新解析', () => run(host, node, 'video_story', {})));
  box.append(button('全屏查看', () => {
    const dialog = panel(host, '全屏查看视频故事', 'cvst-story-fullscreen');
    dialog.append(storyTable(rows), button('关闭全屏', () => dialog.remove()));
  }));
  for (const [key, label] of STORY_COLUMNS) {
    box.append(button(`复制${label}`, async () => {
      try { await host.copyText?.(columnText(rows, key)); host.notice?.('复制成功'); }
      catch (error) { host.notice?.('复制失败，请重试'); }
    }));
  }
  box.append(button('派生镜头节点', () => host.change?.(() => {
    rows.forEach((row, index) => {
      const id = host.newId?.() || `shot-${index}`;
      host.document.nodes.push({id, type: 'video', title: `镜头 ${row.shot || index + 1}`, x: node.x + 320, y: node.y + index * 180, text: row.description || '', params: {}, media_id: null, job_id: null, group: node.group || ''});
      host.document.edges.push({id: host.newId?.() || `edge-${index}`, source: node.id, target: id, port: 'derived_from'});
    });
  })));
  card.append(box);
}

function storyTable(rows) {
  const table = el('table', null, 'cvst-story-table');
  const head = el('tr');
  for (const [, label] of STORY_COLUMNS) head.append(el('th', label));
  table.append(head);
  for (const row of rows) {
    const line = el('tr');
    for (const [key] of STORY_COLUMNS) {
      const cell = el('td');
      const value = row?.[key] ?? '';
      if (key === 'keyframe' && String(value).startsWith('data:image')) {
        const image = el('img');
        image.setAttribute('src', value);
        image.setAttribute('alt', '关键帧缩略图');
        cell.append(image);
      } else cell.textContent = String(value);
      line.append(cell);
    }
    table.append(line);
  }
  return table;
}

function mountLyrics(card, host, node) {
  const lines = String(node.text || '').split('\n').filter(line => line.trim());
  const box = el('div', null, 'cvst-lyrics');
  box.append(
    el('p', COPY.lyrics.lineCount(node.params?.line_count || lines.length)),
    el('p', COPY.lyrics.duration(node.params?.duration_seconds ?? '')),
    el('span', lyricsSourceBadge(node.params?.source), 'cvst-source-badge'),
  );
  const editor = el('textarea');
  editor.value = node.text || '';
  editor.hidden = true;
  let saved = editor.value;
  box.append(editor, button(COPY.lyrics.edit, () => { editor.hidden = false; }), button(COPY.lyrics.expand, () => openLyricsDialog(host, node, editor, () => { saved = editor.value; })), button(COPY.lyrics.save, () => saveLyrics(host, node, editor)));
  card.append(box);
  card.dataset.lyricsSaved = saved;
}

function saveLyrics(host, node, editor) {
  const check = validateLyrics(editor.value);
  if (!check.ok) throw new Error(check.message);
  host.change?.(() => {
    node.text = editor.value;
    node.params = {...(node.params || {}), schema: 'lyrics_timeline/v1', canvas_subkind: 'lyrics_timeline', line_count: check.lines.length};
  });
}

function openLyricsDialog(host, node, editor, onSaved) {
  const dialog = panel(host, COPY.lyrics.expand, 'cvst-lyrics-dialog');
  const area = el('textarea');
  area.value = editor.value;
  let dirty = false;
  area.addEventListener('input', () => { dirty = area.value !== editor.value; });
  const close = () => {
    if (!dirty) { dialog.remove(); return; }
    if (dialog.querySelector('.cvst-unsaved')) return;
    const confirm = el('div', COPY.lyrics.unsaved, 'cvst-unsaved');
    confirm.append(button(COPY.lyrics.save, () => {
      editor.value = area.value;
      saveLyrics(host, node, editor);
      onSaved?.();
      dialog.remove();
    }), button(COPY.lyrics.cancel, () => dialog.remove()));
    dialog.append(confirm);
  };
  dialog.append(area, button('关闭', close));
}

function mountStoryboard(card, host, node) {
  const box = el('div', null, 'canvas-lyrics-storyboard-content');
  const parsed = validateStoryboard(safeJson(node.text));
  if (!parsed.ok) {
    box.append(el('p', COPY.storyboard.invalid, 'cvst-error'));
    card.append(box);
    return;
  }
  box.append(el('p', COPY.storyboard.count(parsed.shots.length)));
  parsed.shots.forEach(shot => box.append(el('p', `${COPY.storyboard.shot(shot.index)} ${shot.instrumental ? COPY.storyboard.instrumental : shot.text}`)));
  box.append(button(COPY.storyboard.fanout, () => host.change?.(() => {
    parsed.shots.forEach((shot, index) => {
      const id = host.newId?.() || `mvshot-${index}`;
      host.document.nodes.push({id, type: 'video', title: COPY.storyboard.shot(shot.index), x: (node.x || 0) + 320, y: (node.y || 0) + index * 180, text: shot.instrumental ? COPY.storyboard.instrumental : shot.text, params: {lyrics_storyboard_index: shot.index}, media_id: null, job_id: null, group: ''});
    });
  })));
  card.append(box);
}

function safeJson(text) {
  try { return JSON.parse(text || ''); } catch { return text; }
}

function mountScript(card, host, node) {
  const box = el('div', null, 'cvst-script');
  const state = {starter: 'script', view: 'creative', fields: true, text: node.text || ''};
  const status = el('p', node.text ? '' : COPY.script.empty, 'cvst-script-status');
  const field = el('textarea');
  field.value = state.text;
  field.setAttribute('aria-label', '脚本正文');
  field.addEventListener('input', () => { state.text = field.value; });
  const shots = el('div', null, 'cvst-script-shots');
  const paint = list => {
    shots.replaceChildren();
    box.classList.toggle('cvst-view-creative', state.view === 'creative');
    box.classList.toggle('cvst-view-script', state.view === 'script');
    field.hidden = !state.fields;
    if (!list?.length) return;
    for (const shot of list) shots.append(el('article', `${shot.index}. ${shot.visual || shot.dialogue || ''}`, 'cvst-shot'));
  };
  for (const [value, label] of COPY.script.starters) box.append(button(label, async () => {
    state.starter = value;
    status.textContent = COPY.script.parsing;
    try {
      const list = localScript(state);
      if (!list.length) { status.textContent = COPY.script.empty; paint([]); return; }
      const video = value === 'video' ? host.document?.nodes?.find(item => item.type === 'video' && item.id !== node.id) : null;
      if (host.apply) await host.apply('script_generator', {starter: value, text: state.text, names: state.text.split(/[、,\s]+/).filter(Boolean), ...(video ? {video_node_id: video.id} : {})}, node.id);
      status.textContent = '';
      paint(list);
    } catch {
      status.textContent = COPY.script.failed;
    }
  }));
  box.append(
    button(COPY.script.creative, () => { state.view = 'creative'; paint(localScript(state)); }),
    button(COPY.script.script, () => { state.view = 'script'; paint(localScript(state)); }),
    button(COPY.script.show, () => { state.fields = true; field.hidden = false; }),
    button(COPY.script.hide, () => { state.fields = false; field.hidden = true; }),
    field, status, shots,
  );
  card.append(box);
}

function localScript(state) {
  if (state.starter === 'script') return state.text.split('\n').map(line => line.trim()).filter(Boolean).map((visual, index) => ({index: index + 1, visual}));
  if (state.starter === 'characters') return state.text.split(/[、,\n]/).map(line => line.trim()).filter(Boolean).map((name, index) => ({index: index + 1, visual: `${name} 的镜头`, dialogue: name}));
  return state.text.split('\n').map(line => line.trim()).filter(Boolean).map((visual, index) => ({index: index + 1, visual: `参考视频镜头 ${index + 1} ${visual}`}));
}

function mountScriptDocument(card, host, node) {
  const box = el('div', null, 'cvst-script-document');
  box.append(el('p', node.text || COPY.scriptDocument.excerpt, 'cvst-excerpt'));
  const editor = el('textarea');
  editor.value = node.text || '';
  editor.setAttribute('aria-label', '画布剧本预览');
  editor.addEventListener('change', () => host.change?.(() => { node.text = editor.value; }));
  box.append(editor, el('small', COPY.scriptDocument.isolated), button(COPY.scriptDocument.view, async () => {
    const dialog = panel(host, COPY.scriptDocument.view, 'cvst-script-dialog');
    dialog.append(el('p', COPY.scriptDocument.authority), el('p', COPY.scriptDocument.hint));
    try {
      const draft = await host.scriptDraft?.(node.params?.scope_key || '');
      const full = draft?.content ? JSON.stringify(draft.content, null, 2) : COPY.scriptDocument.failed;
      dialog.append(el('pre', full, 'cvst-script-full'));
    } catch {
      dialog.append(el('p', COPY.scriptDocument.failed));
    }
    dialog.append(button('关闭', () => dialog.remove()));
  }));
  card.append(box);
}

const ACTIONS = {
  video_breakdown: (host, node) => openBreakdown(host, node),
  video_script_extract: (host, node) => run(host, node, 'video_script_extract', {}),
  video_story: (host, node) => run(host, node, 'video_story', {}),
  script_generator: (host, node) => host.change?.(() => { node.params = {...(node.params || {}), canvas_subkind: 'script_generator'}; }),
  mv_brief: (host, node) => mountAiMvBrief(panel(host, 'AI MV', 'cvst-mv-host'), host),
  video_dewatermark: (host, node) => openErase(host, node),
  video_depth: (host, node) => openDepth(host, node),
  video_segment_remake: (host, node) => openRemake(host, node),
  video_upscale: (host, node) => openVideoUpscale(host, node),
};

export function routeVideoScriptAction(op, host, node, panelNode) {
  const action = ACTIONS[op?.action];
  if (!action) return false;
  panelNode?.remove?.();
  Promise.resolve().then(() => action(host, node)).catch(error => notice(host, error));
  return true;
}
