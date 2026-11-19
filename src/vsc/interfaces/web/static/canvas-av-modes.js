/* Video/audio generator modes, camera-motion picker, and local FFmpeg derive actions. */

export const VIDEO_GENERATION_MODES = [
  {id: 'text_video', label: '文生视频', hint: '文生视频仅支持文本输入'},
  {id: 'head_tail_video', label: '首尾帧', hint: '使用 2 张图片作为首尾帧参考'},
  {id: 'seedance_omni_video', label: '全能参考', hint: '全能参考'},
  {id: 'multi_pic_video', label: '多图参考', hint: '连接至少 2 张图片后可用'},
  {id: 'audio_to_video', label: '音频生视频', hint: '请先上传或生成音频'},
  {id: 'video_edit', label: '视频编辑', hint: '视频编辑模式仅支持 1 个视频节点'},
];

export const AUDIO_GENERATION_MODES = [
  {id: 'description', label: '描述生成'},
  {id: 'lyrics', label: '歌词生成'},
  {id: 'soundtrack', label: '视觉参考配乐'},
];

export const AUDIO_DURATIONS = [15, 30, 60];

export const MUSIC_STYLES = ['流行', '古风', '摇滚', '电子', '爵士', '民谣', '嘻哈', '氛围', '史诗', '轻音乐'];

export const AUDIO_VOICES = [
  {id: 'zh_female_vv_uranus_bigtts', label: 'Vivi · 预置女声'},
  {id: 'zh_male_m191_uranus_bigtts', label: '云舟 · 预置男声'},
  {id: 'zh_female_xiaohe_uranus_bigtts', label: '小何 · 预置女声'},
];

export const SEED_SAMPLE_RATES = [8000, 16000, 24000, 48000];
export const SEED_FORMATS = ['mp3', 'wav'];

export const BUILTIN_CAMERA_MOTIONS = [
  {id: 'builtin-push-in', name: '推进镜头 Push In', prompt_fragment: '摄影机平稳缓慢向前推进，聚焦主体细节'},
  {id: 'builtin-pull-out', name: '拉远镜头 Pull Out', prompt_fragment: '摄影机平稳向后拉远，逐渐展现完整环境空间'},
  {id: 'builtin-truck-left', name: '左移镜头 Truck Left', prompt_fragment: '摄影机沿水平轨道向左平移跟拍'},
  {id: 'builtin-truck-right', name: '右移镜头 Truck Right', prompt_fragment: '摄影机沿水平轨道向右平移跟拍'},
  {id: 'builtin-tilt-up', name: '上摇镜头 Tilt Up', prompt_fragment: '摄影机由低向高缓慢仰摇，凸显空间纵深与气势'},
  {id: 'builtin-tilt-down', name: '下摇镜头 Tilt Down', prompt_fragment: '摄影机由高处俯摇下降，自然落幅至人物主体'},
  {id: 'builtin-orbit', name: '环绕运镜 Orbit', prompt_fragment: '摄影机围绕主体呈圆弧轨迹平滑环绕拍摄'},
  {id: 'builtin-handheld', name: '手持呼吸跟拍 Handheld', prompt_fragment: '电影感手持摄影机轻微呼吸晃动，贴近角色跟拍'},
];

const CAMERA_TABS = [
  {id: 'square', label: '运镜广场'},
  {id: 'mine', label: '我的运镜'},
  {id: 'favorites', label: '我的收藏'},
];

const KLING_AUDIO_MESSAGE = '可灵 O3 有参考视频时不支持生成音频';
const SOUNDTRACK_HINT = '图片或视频参考仅支持描述配乐，不支持歌词和自定义人声';

export function activeVideoMode(node) {
  const id = node?.params?.vsc_operation;
  return VIDEO_GENERATION_MODES.some(mode => mode.id === id) ? id : '';
}

export function effectiveAudioMode(node) {
  const mode = node?.params?.vsc_audio_mode;
  return AUDIO_GENERATION_MODES.some(item => item.id === mode) ? mode : 'description';
}

export function lyricsEnabled(mode) {
  return mode !== 'soundtrack';
}

export function joinStyles(selected) {
  const chosen = new Set(selected || []);
  return MUSIC_STYLES.filter(style => chosen.has(style)).join(',');
}

export function splitStyles(value) {
  const chosen = new Set(String(value || '').split(',').map(item => item.trim()).filter(Boolean));
  return MUSIC_STYLES.filter(style => chosen.has(style));
}

export function speedInRange(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0.1 && number <= 4;
}

export function klingAudioBlocked(node, edges, modelKey) {
  const key = String(modelKey || node?.params?.vsc_gen_model_id || '');
  return /kling/i.test(key) && (edges || []).some(edge => edge.target === node?.id && edge.port === 'reference_video');
}

export function voiceOptions(eff) {
  const extra = eff?.activeModel?.capabilities?.preset_voices || eff?.spec?.preset_voices || [];
  const rows = [...AUDIO_VOICES];
  for (const item of extra) {
    const id = typeof item === 'string' ? item : item?.id;
    const label = typeof item === 'string' ? item : (item?.label || item?.name || id);
    if (id && !rows.some(row => row.id === id)) rows.push({id, label});
  }
  return rows;
}

export function choiceList(primary, fallback) {
  if (Array.isArray(primary) && primary.length) return primary;
  if (Array.isArray(fallback) && fallback.length) return fallback;
  return [];
}

export function avQuoteFields(node) {
  if (!node?.params) return {};
  const params = node.params;
  const fields = {};
  if (node.type === 'video') {
    if (activeVideoMode(node)) fields.op_type = params.vsc_operation;
    const duration = Number(params.vsc_gen_duration);
    if (Number.isInteger(duration) && duration > 0) fields.duration = duration;
    if (params.vsc_gen_resolution) fields.resolution = params.vsc_gen_resolution;
    if (params.vsc_gen_ratio) fields.ratio = params.vsc_gen_ratio;
    if (typeof params.vsc_gen_generate_audio === 'boolean') fields.generate_audio = params.vsc_gen_generate_audio;
    if (params.vsc_camera_motion_id) fields.camera_motion_id = String(params.vsc_camera_motion_id).slice(0, 80);
  }
  if (node.type === 'audio') {
    const mode = effectiveAudioMode(node);
    fields.op_type = 'audio_generate';
    fields.audio_mode = mode;
    const duration = AUDIO_DURATIONS.includes(Number(params.vsc_gen_duration)) ? Number(params.vsc_gen_duration) : 30;
    fields.duration = duration;
    if (params.vsc_audio_voice) fields.voice_id = String(params.vsc_audio_voice).slice(0, 64);
    if (params.vsc_audio_style) fields.music_style = String(params.vsc_audio_style).slice(0, 200);
    if (mode === 'lyrics') {
      const chars = String(params.vsc_audio_lyrics || '').length + String(params.vsc_audio_lyrics_b || '').length;
      fields.lyrics_chars = Math.min(2000, chars);
    }
    if (SEED_SAMPLE_RATES.includes(Number(params.vsc_seed_sample_rate))) fields.seed_sample_rate = Number(params.vsc_seed_sample_rate);
    if (SEED_FORMATS.includes(params.vsc_seed_format)) fields.seed_format = params.vsc_seed_format;
    const speed = Number(params.vsc_seed_speed);
    if (Number.isFinite(speed) && speed >= 0.5 && speed <= 2) fields.seed_speed = speed;
    const pitch = Number(params.vsc_seed_pitch);
    if (Number.isInteger(pitch) && pitch >= -12 && pitch <= 12) fields.seed_pitch = pitch;
    const volume = Number(params.vsc_seed_volume);
    if (Number.isFinite(volume) && volume >= 0.5 && volume <= 2) fields.seed_volume = volume;
  }
  return fields;
}

function el(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function cavUi(state) {
  if (!state) return {open: '', cameraTab: 'square', cameraQuery: ''};
  state._cav = state._cav || {open: '', cameraTab: 'square', cameraQuery: ''};
  return state._cav;
}

function edgesOf(state, node) {
  return (state?.document?.edges || []).filter(edge => edge.target === node?.id);
}

function commit(host, state, fn) {
  if (typeof host?.change === 'function') host.change(state, fn);
  else fn();
}

function findAncestor(node, className) {
  let current = node;
  while (current) {
    if (String(current.className || '').split(' ').includes(className)) return current;
    current = current.parentElement;
  }
  return null;
}

function findPrompt(slot) {
  let current = slot;
  while (current) {
    const found = current.querySelector?.('[aria-label="文本或提示词"]');
    if (found && found !== slot) return found;
    current = current.parentElement;
  }
  return null;
}

function removeBoards(slot) {
  const bar = findAncestor(slot, 'cgc-bottom-bar');
  const parent = bar?.parentElement;
  if (!parent?.querySelectorAll) return;
  for (const board of [...parent.querySelectorAll('.cav-audio-board')]) board.remove();
}

function placeBoard(slot, board) {
  const bar = findAncestor(slot, 'cgc-bottom-bar');
  if (bar?.parentElement) bar.parentElement.insertBefore(board, bar);
  else slot.append(board);
}

function fillSelect(doc, select, values, current, labelOf) {
  for (const value of values) {
    const option = el(doc, 'option', '', labelOf(value));
    option.value = String(value);
    select.append(option);
  }
  if (current != null && values.map(String).includes(String(current))) select.value = String(current);
  else if (values.length) select.value = String(values[0]);
}

function videoHint(mode, edges) {
  const row = VIDEO_GENERATION_MODES.find(item => item.id === mode);
  if (!row) return '';
  if (mode === 'head_tail_video') {
    const images = edges.filter(edge => edge.port === 'first_frame' || edge.port === 'last_frame').length;
    if (images < 2) return '首尾帧最多 2 张图片，请连接首帧和尾帧';
  }
  if (mode === 'multi_pic_video' && edges.filter(edge => edge.port === 'reference_image').length < 2) return row.hint;
  if (mode === 'audio_to_video' && !edges.some(edge => edge.port === 'reference_audio')) return '请先上传或生成音频';
  if (mode === 'video_edit') {
    const videos = edges.filter(edge => edge.port === 'reference_video').length;
    if (videos !== 1) return videos > 1 ? '视频编辑模式仅支持 1 个视频节点' : '请先连接 1 个视频';
  }
  return row.hint;
}

function applyKlingLock(root, node, state, eff) {
  const toggle = root.querySelector?.('.cgc-audio-toggle');
  if (!toggle) return;
  const modelKey = eff?.activeModel?.modelKey || eff?.spec?.model_key || node.params?.vsc_gen_model_id || '';
  if (klingAudioBlocked(node, state?.document?.edges, modelKey)) {
    toggle.disabled = true;
    toggle.title = KLING_AUDIO_MESSAGE;
    toggle.setAttribute('aria-label', KLING_AUDIO_MESSAGE);
  }
}

function clampUnsupportedAudio(node, state, host, eff) {
  if (node.type !== 'video' || eff?.spec?.generate_audio !== false || node.params?.vsc_gen_generate_audio !== true) return;
  queueMicrotask(() => {
    if (node.params?.vsc_gen_generate_audio !== true || typeof host?.change !== 'function') return;
    node.params.vsc_gen_generate_audio = false;
    host.change(state, () => { node.params.vsc_gen_generate_audio = false; });
  });
}

export function mountAvGeneratorModes({root, node, operation, eff, state, host} = {}) {
  if (!root || !node || (node.type !== 'video' && node.type !== 'audio')) return;
  const doc = root.ownerDocument;
  if (!doc?.createElement) return;
  node.params = node.params || {};
  applyKlingLock(root, node, state, eff);
  clampUnsupportedAudio(node, state, host, eff);
  const wrap = el(doc, 'div', 'cav-root');
  wrap.dataset.modality = node.type;
  if (node.type === 'video') mountVideoControls(doc, wrap, node, eff, state, host);
  else mountAudioControls(doc, wrap, root, node, eff, state, host);
  root.append(wrap);
}

function mountVideoControls(doc, wrap, node, eff, state, host) {
  const edges = edgesOf(state, node);
  const modes = el(doc, 'div', 'cav-mode-switch');
  modes.setAttribute('role', 'group');
  modes.setAttribute('aria-label', '视频生成模式');
  const current = activeVideoMode(node);
  for (const mode of VIDEO_GENERATION_MODES) {
    const button = el(doc, 'button', 'cav-mode-btn' + (mode.id === current ? ' is-selected' : ''), mode.label);
    button.type = 'button';
    button.dataset.mode = mode.id;
    button.setAttribute('aria-pressed', String(mode.id === current));
    button.addEventListener('click', event => {
      event.stopPropagation?.();
      commit(host, state, () => { node.params.vsc_operation = mode.id; });
    });
    modes.append(button);
  }
  wrap.append(modes);
  const durations = choiceList(eff?.durations, eff?.spec?.durations);
  const resolutions = choiceList(eff?.resolutions, eff?.spec?.resolutions);
  const ratios = choiceList(eff?.ratios, eff?.spec?.aspect_ratios);
  wrap.append(labeledSelect(doc, '视频时长', durations, eff?.duration ?? node.params.vsc_gen_duration, value => `${value} 秒`, value => {
    commit(host, state, () => { node.params.vsc_gen_duration = Number(value); });
  }));
  wrap.append(labeledSelect(doc, '分辨率', resolutions, eff?.resolution ?? node.params.vsc_gen_resolution, value => value, value => {
    commit(host, state, () => { node.params.vsc_gen_resolution = value; });
  }));
  wrap.append(labeledSelect(doc, '比例', ratios, eff?.ratio ?? node.params.vsc_gen_ratio, value => value === 'adaptive' ? '自适应' : value, value => {
    commit(host, state, () => { node.params.vsc_gen_ratio = value; });
  }));
  wrap.append(cameraControl(doc, node, state, host));
  const hint = el(doc, 'p', 'cav-hint', videoHint(current, edges));
  hint.dataset.role = 'mode-hint';
  wrap.append(hint);
}

function labeledSelect(doc, label, values, current, labelOf, onChange) {
  const field = el(doc, 'label', 'cav-field');
  field.append(el(doc, 'span', 'cav-field-label', label));
  const select = el(doc, 'select', 'cav-select');
  select.setAttribute('aria-label', label);
  select.disabled = !values.length;
  fillSelect(doc, select, values, current, labelOf);
  select.addEventListener('change', event => {
    event.stopPropagation?.();
    onChange(select.value);
  });
  field.append(select);
  return field;
}

function cameraItems(ui) {
  const builtin = ui.builtin || BUILTIN_CAMERA_MOTIONS;
  const custom = ui.custom || [];
  const tab = ui.cameraTab || 'square';
  let rows = builtin;
  if (tab === 'mine') rows = custom;
  if (tab === 'favorites') rows = custom.filter(item => item.favorite);
  const query = String(ui.cameraQuery || '').trim().toLowerCase();
  if (!query) return rows;
  return rows.filter(item => String(item.name || '').toLowerCase().includes(query));
}

function renderCameraList(doc, list, node, state, host, ui) {
  list.replaceChildren();
  const rows = cameraItems(ui);
  if (!rows.length) {
    list.append(el(doc, 'p', 'cav-empty', '暂无运镜模板'));
    return;
  }
  for (const item of rows) {
    const button = el(doc, 'button', 'cav-camera-item' + (node.params.vsc_camera_motion_id === item.id ? ' is-selected' : ''), item.name);
    button.type = 'button';
    button.dataset.motionId = item.id;
    button.addEventListener('click', event => {
      event.stopPropagation?.();
      commit(host, state, () => {
        node.params.vsc_camera_motion_id = String(item.id).slice(0, 80);
        node.params.vsc_camera_motion_name = String(item.name || '').slice(0, 120);
        node.params.vsc_camera_motion_prompt = String(item.prompt_fragment || '').slice(0, 500);
      });
    });
    list.append(button);
  }
}

function cameraControl(doc, node, state, host) {
  const ui = cavUi(state);
  const anchor = el(doc, 'div', 'cav-popover-anchor');
  const button = el(doc, 'button', 'cav-bar-btn' + (ui.open === 'camera' ? ' is-open' : ''), node.params.vsc_camera_motion_name || '运镜');
  button.type = 'button';
  button.setAttribute('aria-label', '运镜');
  button.setAttribute('aria-expanded', String(ui.open === 'camera'));
  button.addEventListener('click', event => {
    event.stopPropagation?.();
    ui.open = ui.open === 'camera' ? '' : 'camera';
    if (ui.open === 'camera' && !ui.cameraLoading && typeof host?.api === 'function' && typeof host.projectBase === 'function') {
      ui.cameraLoading = true;
      Promise.resolve(host.api(host.projectBase() + '/camera-motion-templates')).then(data => {
        ui.builtin = data?.builtin?.length ? data.builtin : BUILTIN_CAMERA_MOTIONS;
        ui.custom = data?.custom || [];
      }).catch(() => {
        ui.builtin = BUILTIN_CAMERA_MOTIONS;
        ui.custom = [];
      }).finally(() => {
        ui.cameraLoading = false;
        ui.cameraLoaded = true;
        host.draw?.(state);
      });
    }
    host?.draw?.(state);
  });
  anchor.append(button);
  if (ui.open === 'camera') {
    const panel = el(doc, 'div', 'cav-popover cav-camera-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', '运镜库');
    panel.append(el(doc, 'div', 'cav-popover-title', '运镜库'));
    const tabs = el(doc, 'div', 'cav-tabs');
    tabs.setAttribute('role', 'tablist');
    for (const tab of CAMERA_TABS) {
      const tabBtn = el(doc, 'button', 'cav-tab' + ((ui.cameraTab || 'square') === tab.id ? ' is-selected' : ''), tab.label);
      tabBtn.type = 'button';
      tabBtn.dataset.cameraTab = tab.id;
      tabBtn.addEventListener('click', event => {
        event.stopPropagation?.();
        ui.cameraTab = tab.id;
        host?.draw?.(state);
      });
      tabs.append(tabBtn);
    }
    const search = el(doc, 'input', 'cav-search');
    search.type = 'search';
    search.value = ui.cameraQuery || '';
    search.placeholder = '搜索运镜名称';
    search.setAttribute('aria-label', '搜索运镜名称');
    const list = el(doc, 'div', 'cav-camera-list');
    search.addEventListener('input', () => {
      ui.cameraQuery = search.value;
      renderCameraList(doc, list, node, state, host, ui);
    });
    renderCameraList(doc, list, node, state, host, ui);
    panel.append(tabs, search, list);
    anchor.append(panel);
  }
  return anchor;
}

function mountAudioControls(doc, wrap, slot, node, eff, state, host) {
  const ui = cavUi(state);
  const mode = effectiveAudioMode(node);
  const modes = el(doc, 'div', 'cav-mode-switch');
  modes.setAttribute('role', 'group');
  modes.setAttribute('aria-label', '音频生成模式');
  for (const item of AUDIO_GENERATION_MODES) {
    const button = el(doc, 'button', 'cav-mode-btn' + (item.id === mode ? ' is-selected' : ''), item.label);
    button.type = 'button';
    button.dataset.mode = item.id;
    button.disabled = Boolean(state?.readOnly);
    button.setAttribute('aria-pressed', String(item.id === mode));
    button.addEventListener('click', event => {
      event.stopPropagation?.();
      commit(host, state, () => {
        node.params.vsc_audio_mode = item.id;
        node.params.vsc_operation = 'audio_generate';
        if (item.id === 'soundtrack') {
          delete node.params.vsc_audio_lyrics;
          delete node.params.vsc_audio_lyrics_b;
        }
      });
    });
    modes.append(button);
  }
  wrap.append(modes);
  const voices = voiceOptions(eff);
  const voice = labeledSelect(doc, '音色', voices.map(item => item.id), node.params.vsc_audio_voice || voices[0]?.id, value => voices.find(item => item.id === value)?.label || value, value => {
    commit(host, state, () => { node.params.vsc_audio_voice = value; });
  });
  const voiceSelect = voice.querySelector('select');
  if (voiceSelect) voiceSelect.disabled = mode === 'soundtrack' || Boolean(state?.readOnly);
  wrap.append(voice);
  wrap.append(labeledSelect(doc, '时长', AUDIO_DURATIONS, AUDIO_DURATIONS.includes(Number(node.params.vsc_gen_duration)) ? Number(node.params.vsc_gen_duration) : 30, value => `${value} 秒`, value => {
    commit(host, state, () => { node.params.vsc_gen_duration = Number(value); });
  }));
  wrap.append(seedControl(doc, node, state, host, ui));
  const prompt = findPrompt(slot);
  if (prompt) {
    prompt.placeholder = mode === 'soundtrack' ? '描述想要的配乐风格（可选）' : '描述您想要的音乐';
  }
  removeBoards(slot);
  placeBoard(slot, audioBoard(doc, node, state, host, mode));
}

function audioBoard(doc, node, state, host, mode) {
  const board = el(doc, 'div', 'cav-audio-board');
  board.dataset.mode = mode;
  const styles = el(doc, 'div', 'cav-style-row');
  styles.setAttribute('aria-label', '音乐风格');
  const selected = new Set(splitStyles(node.params.vsc_audio_style));
  for (const style of MUSIC_STYLES) {
    const button = el(doc, 'button', 'cav-style-tag' + (selected.has(style) ? ' is-selected' : ''), style);
    button.type = 'button';
    button.dataset.style = style;
    button.setAttribute('aria-pressed', String(selected.has(style)));
    button.addEventListener('click', event => {
      event.stopPropagation?.();
      commit(host, state, () => {
        const next = new Set(splitStyles(node.params.vsc_audio_style));
        if (next.has(style)) next.delete(style);
        else next.add(style);
        const joined = joinStyles(next);
        if (joined) node.params.vsc_audio_style = joined;
        else delete node.params.vsc_audio_style;
      });
    });
    styles.append(button);
  }
  board.append(styles);
  if (mode === 'soundtrack') {
    board.append(el(doc, 'p', 'cav-hint', SOUNDTRACK_HINT));
    return board;
  }
  if (mode === 'lyrics') {
    const columns = el(doc, 'div', 'cav-lyrics-board');
    columns.append(lyricField(doc, node, state, host, 'vsc_audio_lyrics', '请输入歌词', '请输入歌词'));
    columns.append(lyricField(doc, node, state, host, 'vsc_audio_lyrics_b', '副歌', '请输入副歌'));
    board.append(columns);
  }
  return board;
}

function lyricField(doc, node, state, host, key, aria, placeholder) {
  const field = el(doc, 'label', 'cav-lyric-field');
  field.append(el(doc, 'span', 'cav-field-label', aria));
  const area = el(doc, 'textarea', 'cav-lyric');
  area.value = String(node.params[key] || '');
  area.maxLength = 2000;
  area.placeholder = placeholder;
  area.setAttribute('aria-label', aria);
  area.addEventListener('input', () => {
    node.params[key] = area.value.slice(0, 2000);
    host?.markEdited?.(state);
  });
  area.addEventListener('change', () => {
    commit(host, state, () => { node.params[key] = area.value.slice(0, 2000); });
  });
  field.append(area);
  return field;
}

function seedControl(doc, node, state, host, ui) {
  const anchor = el(doc, 'div', 'cav-popover-anchor');
  const button = el(doc, 'button', 'cav-bar-btn' + (ui.open === 'seed' ? ' is-open' : ''), '高级设置');
  button.type = 'button';
  button.setAttribute('aria-label', '高级设置');
  button.setAttribute('aria-expanded', String(ui.open === 'seed'));
  button.addEventListener('click', event => {
    event.stopPropagation?.();
    ui.open = ui.open === 'seed' ? '' : 'seed';
    host?.draw?.(state);
  });
  anchor.append(button);
  if (ui.open === 'seed') anchor.append(seedPanel(doc, node, state, host));
  return anchor;
}

function seedValue(params, key, fallback, allowed) {
  const value = params[key];
  if (allowed) return allowed.includes(value) || allowed.map(Number).includes(Number(value)) ? value : fallback;
  return value == null || value === '' ? fallback : value;
}

function seedPanel(doc, node, state, host) {
  const panel = el(doc, 'div', 'cav-popover cav-seed-panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '高级设置');
  panel.append(el(doc, 'div', 'cav-popover-title', '高级设置'));
  const params = node.params;
  const rate = seedValue(params, 'vsc_seed_sample_rate', 24000, SEED_SAMPLE_RATES);
  const format = seedValue(params, 'vsc_seed_format', 'mp3', SEED_FORMATS);
  panel.append(labeledSelect(doc, '采样率', SEED_SAMPLE_RATES, rate, value => String(value), value => {
    commit(host, state, () => { node.params.vsc_seed_sample_rate = Number(value); });
  }));
  panel.append(labeledSelect(doc, '格式', SEED_FORMATS, format, value => value, value => {
    commit(host, state, () => { node.params.vsc_seed_format = value; });
  }));
  panel.append(numberField(doc, '语速', 'vsc_seed_speed', params.vsc_seed_speed ?? 1, 0.5, 2, 0.1, node, state, host));
  panel.append(numberField(doc, '声调', 'vsc_seed_pitch', params.vsc_seed_pitch ?? 0, -12, 12, 1, node, state, host, true));
  panel.append(numberField(doc, '音量', 'vsc_seed_volume', params.vsc_seed_volume ?? 1, 0.5, 2, 0.1, node, state, host));
  const reset = el(doc, 'button', 'cav-text-btn', '恢复默认');
  reset.type = 'button';
  reset.addEventListener('click', event => {
    event.stopPropagation?.();
    commit(host, state, () => {
      node.params.vsc_seed_sample_rate = 24000;
      node.params.vsc_seed_format = 'mp3';
      node.params.vsc_seed_speed = 1;
      node.params.vsc_seed_pitch = 0;
      node.params.vsc_seed_volume = 1;
    });
  });
  panel.append(reset);
  return panel;
}

function numberField(doc, label, key, value, min, max, step, node, state, host, integer) {
  const field = el(doc, 'label', 'cav-field');
  field.append(el(doc, 'span', 'cav-field-label', label));
  const input = el(doc, 'input', 'cav-number');
  input.type = 'number';
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.setAttribute('aria-label', label);
  input.addEventListener('change', event => {
    event.stopPropagation?.();
    const number = Number(input.value);
    if (!Number.isFinite(number) || number < min || number > max) {
      host?.notice?.(state, `${label}须在 ${min}–${max} 之间`);
      input.value = String(value);
      return;
    }
    commit(host, state, () => { node.params[key] = integer ? Math.round(number) : number; });
  });
  field.append(input);
  return field;
}

async function runChecked(state, host, fn) {
  try {
    await fn();
  } catch (error) {
    host?.notice?.(state, error?.message || '处理失败');
  }
}

export async function runAvDerive(state, host, {slot, path, payload, done}) {
  if (!host?.live?.(state) || state.readOnly || state.shared) return null;
  if (!await host.save(state) || !host.live(state)) return null;
  const result = await host.auxiliaryWrite(state, slot, host.url(state) + path, payload);
  if (!host.live(state)) return null;
  const fixed = await host.api(host.url(state) + '?version=' + result.canvas_revision);
  if (!host.live(state)) return null;
  const doc = host.cleanDocument(fixed.document);
  host.checkpoint(state);
  for (const nid of result.node_ids || []) {
    const added = doc.nodes.find(item => item.id === nid);
    if (added && !state.document.nodes.some(item => item.id === nid)) state.document.nodes.push(added);
    for (const edge of doc.edges.filter(item => item.source === payload.node_id && item.target === nid && item.port === 'derived_from')) {
      if (!state.document.edges.some(item => item.id === edge.id)) state.document.edges.push(edge);
    }
  }
  state.version = result.canvas_revision;
  host.revision(state, Math.max(state.revision || 0, result.revision || 0, fixed.revision || 0));
  state.selected = new Set(result.node_ids?.length ? result.node_ids : [payload.node_id]);
  state.dirty = false;
  host.remember(state);
  host.setVersion?.(state.version);
  host.draw(state);
  host.notice(state, done);
  return result;
}

export function mountAvAudioTools(state, node, card, host) {
  if (!card?.ownerDocument || !node || node.type !== 'audio') return;
  if (state?.readOnly || state?.shared) return;
  const doc = card.ownerDocument;
  const panel = el(doc, 'div', 'cav-audio-tools');
  panel.setAttribute('aria-label', '音频处理');
  const start = el(doc, 'input', 'cav-number');
  start.type = 'number';
  start.min = '0';
  start.step = '0.1';
  start.value = '0';
  start.setAttribute('aria-label', '开始时间（秒）');
  const end = el(doc, 'input', 'cav-number');
  end.type = 'number';
  end.min = '0';
  end.step = '0.1';
  end.value = '1';
  end.setAttribute('aria-label', '结束时间（秒）');
  const clip = el(doc, 'button', 'cav-text-btn', '生成截取音频');
  clip.type = 'button';
  clip.addEventListener('click', event => {
    event.stopPropagation?.();
    const startSeconds = Number(start.value);
    const endSeconds = Number(end.value);
    if (!Number.isFinite(startSeconds) || startSeconds < 0 || !Number.isFinite(endSeconds) || endSeconds <= startSeconds) {
      host?.notice?.(state, '结束时间须大于开始时间');
      return;
    }
    runChecked(state, host, () => runAvDerive(state, host, {
      slot: `audio-clip:${node.id}:${state.version}:${startSeconds}:${endSeconds}`,
      path: '/process-audio',
      payload: {canvas_revision: state.version, node_id: node.id, operation: 'clip', start_seconds: startSeconds, end_seconds: endSeconds},
      done: '已生成截取音频并创建新音频节点。',
    }));
  });
  const speed = el(doc, 'input', 'cav-number');
  speed.type = 'number';
  speed.min = '0.1';
  speed.max = '4';
  speed.step = '0.1';
  speed.value = '1';
  speed.setAttribute('aria-label', '输入变速倍率');
  const applySpeed = el(doc, 'button', 'cav-text-btn', '确认变速');
  applySpeed.type = 'button';
  applySpeed.addEventListener('click', event => {
    event.stopPropagation?.();
    const rate = Number(speed.value);
    if (!speedInRange(rate)) {
      host?.notice?.(state, '变速倍率须在 0.1x–4.0x');
      return;
    }
    runChecked(state, host, () => runAvDerive(state, host, {
      slot: `audio-speed:${node.id}:${state.version}:${rate}`,
      path: '/process-audio',
      payload: {canvas_revision: state.version, node_id: node.id, operation: 'speed', speed: rate},
      done: `已生成变速音频 ${rate}x 并创建新音频节点。`,
    }));
  });
  panel.append(
    el(doc, 'span', 'cav-field-label', '截取'), start, end, clip,
    el(doc, 'span', 'cav-field-label', '变速'), speed, applySpeed,
  );
  card.append(panel);
}

export function mountAvVideoFrameTools(state, node, tools, host) {
  if (!tools?.ownerDocument || !node || node.type !== 'video') return;
  if (state?.readOnly || state?.shared) return;
  const doc = tools.ownerDocument;
  const frames = [
    ['first', '截取首帧'],
    ['current', '截取当前帧'],
    ['last', '截取尾帧'],
  ];
  for (const [frame, label] of frames) {
    const button = el(doc, 'button', 'cav-frame-btn', label);
    button.type = 'button';
    button.dataset.frame = frame;
    button.addEventListener('click', event => {
      event.stopPropagation?.();
      let timeSeconds;
      if (frame === 'current') {
        const video = tools.closest?.('article, .cc-node, .cc-node-card')?.querySelector('video') || tools.parentElement?.querySelector('video');
        if (!video || !Number.isFinite(Number(video.currentTime))) {
          host?.notice?.(state, '请先播放或定位视频后再截取当前帧');
          return;
        }
        timeSeconds = Number(video.currentTime);
      }
      const payload = {canvas_revision: state.version, node_id: node.id, frame};
      if (frame === 'current') payload.time_seconds = timeSeconds;
      runChecked(state, host, () => runAvDerive(state, host, {
        slot: `frame:${node.id}:${state.version}:${frame}:${timeSeconds ?? ''}`,
        path: '/capture-frame',
        payload,
        done: `已${label}并创建新图片节点。`,
      }));
    });
    tools.append(button);
  }
}
