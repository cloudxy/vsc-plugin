export const PHOTOGRAPHY_CAMERAS = [
  'Sony Venice',
  'ARRI Alexa 35',
  'ARRI Alexa 65',
  'RED V-Raptor',
  'Panavision DXL2',
  'Arricam LT',
  'Arriflex 435',
  'IMAX Keighley',
  'Film Camera',
];

export const PHOTOGRAPHY_LENSES = [
  'Zeiss Ultra Prime',
  'Cooke S4/i',
  'ARRI Master Prime',
  'Panavision Primo',
  'Leica Summilux-C',
  'Atlas Orion Anamorphic',
  'Canon K-35',
  'Hawk V-Lite',
  'Helios 44-2',
];

export const PHOTOGRAPHY_FOCAL_LENGTHS = [8, 14, 24, 35, 50, 75, 125];
export const PHOTOGRAPHY_APERTURES = ['f1.4', 'f4', 'f11'];

export const IMAGE_ASPECT_RATIOS = ['16:9', '9:16', '21:9', '1:1', '4:5', '5:4', '4:3', '3:4', '3:2', '2:3', '2:1'];
export const CROP_RATIOS = [
  ['original', '原图', null],
  ['1:1', '1:1', 1],
  ['16:9', '16:9', 16 / 9],
  ['9:16', '9:16', 9 / 16],
  ['5:2', '5:2', 5 / 2],
  ['2:5', '2:5', 2 / 5],
  ['4:3', '4:3', 4 / 3],
  ['3:4', '3:4', 3 / 4],
];

export const PORTRAIT_TEXTURE_GROUPS = [
  { key: 'scene_blend', label: '人景关系', options: [['light', '轻度对齐'], ['natural', '自然融合'], ['deep', '深度融合']] },
  { key: 'light_match', label: '光影融合', options: [['soft', '柔和补光'], ['natural', '自然匹配'], ['dramatic', '氛围强化']] },
  { key: 'skin_polish', label: '皮肤修饰', options: [['clean', '清透修饰'], ['natural', '自然肤质'], ['micro', '真实肌理']] },
  { key: 'grain', label: '画面纹理', options: [['soft', '柔和'], ['natural', '自然'], ['film_grain', '颗粒']] },
  { key: 'sharpness', label: '清晰锐度', options: [['soft_focus', '柔焦'], ['standard', '标准清晰'], ['hd_sharp', '高清锐化']] },
];

export const DEFAULT_PORTRAIT_TEXTURE = {
  scene_blend: 'natural',
  light_match: 'natural',
  skin_polish: 'natural',
  grain: 'natural',
  sharpness: 'standard',
};

export const COLOR_FILTER_CATEGORIES = [
  ['all', '全部'],
  ['hot', '热门'],
  ['basic', '基础'],
  ['cinema', '电影'],
  ['film', '胶片'],
  ['jp', '日系'],
  ['bw', '黑白'],
  ['mood', '氛围'],
];

export const COLOR_FILTERS = [
  { id: 'original', label: '原图', cat: ['all', 'basic'], hue: 0, sat: 0, bri: 0, con: 0 },
  { id: 'natural_enhance', label: '自然增强', cat: ['all', 'hot', 'basic'], hue: 0, sat: 8, bri: 2, con: 5 },
  { id: 'vivid', label: '鲜艳', cat: ['all', 'hot', 'basic'], hue: 0, sat: 28, bri: 3, con: 10 },
  { id: 'anime_crisp', label: '漫画鲜明', cat: ['all', 'hot', 'basic'], hue: -4, sat: 22, bri: 5, con: 18 },
  { id: 'teal_orange', label: '青橙电影', cat: ['all', 'hot', 'cinema'], hue: -8, sat: 14, bri: -2, con: 16 },
  { id: 'cinema_dark', label: '电影暗调', cat: ['all', 'cinema'], hue: -6, sat: -14, bri: -14, con: 20 },
  { id: 'black_gold', label: '黑金', cat: ['all', 'hot', 'cinema'], hue: 12, sat: -18, bri: -10, con: 24 },
  { id: 'cyberpunk', label: '赛博朋克', cat: ['all', 'cinema', 'mood'], hue: -28, sat: 34, bri: 2, con: 22 },
  { id: 'warm_film', label: '暖调胶片', cat: ['all', 'hot', 'film'], hue: 10, sat: 10, bri: 4, con: 8 },
  { id: 'cyan_film', label: '青绿胶片', cat: ['all', 'film'], hue: -14, sat: -6, bri: 2, con: 10 },
  { id: 'vintage_fade', label: '复古褪色', cat: ['all', 'film'], hue: 8, sat: -22, bri: 6, con: -10 },
  { id: 'polaroid', label: '拍立得', cat: ['all', 'film'], hue: 6, sat: -8, bri: 8, con: 6 },
  { id: 'jp_fresh', label: '日系清新', cat: ['all', 'hot', 'jp'], hue: -4, sat: -10, bri: 12, con: -6 },
  { id: 'cream_sun', label: '奶油暖阳', cat: ['all', 'jp'], hue: 10, sat: -6, bri: 10, con: -4 },
  { id: 'cool_clear', label: '冷白透亮', cat: ['all', 'jp', 'basic'], hue: -10, sat: -8, bri: 12, con: 6 },
  { id: 'classic_bw', label: '经典黑白', cat: ['all', 'bw'], hue: 0, sat: -100, bri: 0, con: 12 },
  { id: 'high_contrast_bw', label: '高反差黑白', cat: ['all', 'bw'], hue: 0, sat: -100, bri: -4, con: 38 },
  { id: 'sepia_retro', label: '棕褐怀旧', cat: ['all', 'bw', 'film'], hue: 24, sat: -45, bri: 2, con: 10 },
  { id: 'night_blue', label: '夜景蓝调', cat: ['all', 'mood', 'cinema'], hue: -22, sat: 12, bri: -8, con: 14 },
  { id: 'forest', label: '森系', cat: ['all', 'mood'], hue: -12, sat: 10, bri: -2, con: 8 },
  { id: 'autumn_orange', label: '秋日暖橙', cat: ['all', 'mood', 'hot'], hue: 16, sat: 18, bri: 4, con: 10 },
];

export const GROUP_COLOR_PALETTE = [
  ['#292929', '炭灰'],
  ['#1f3a2e', '森绿'],
  ['#1e3246', '深海蓝'],
  ['#3d2b1f', '琥珀棕'],
  ['#38233c', '暗夜紫'],
  ['#3b3520', '暖金'],
  ['#3d2226', '绯红'],
];

export const BUILTIN_CAMERA_MOTIONS = [
  { id: 'push_in', title: '推进镜头 Push In', motion_key: 'push_in', params: { dolly: 0.6, pan: 0, tilt: 0, zoom: 0.2 } },
  { id: 'pull_out', title: '拉远镜头 Pull Out', motion_key: 'pull_out', params: { dolly: -0.6, pan: 0, tilt: 0, zoom: -0.2 } },
  { id: 'pan_left', title: '平稳左摇 Pan Left', motion_key: 'pan_left', params: { dolly: 0, pan: -0.5, tilt: 0, zoom: 0 } },
  { id: 'pan_right', title: '平稳右摇 Pan Right', motion_key: 'pan_right', params: { dolly: 0, pan: 0.5, tilt: 0, zoom: 0 } },
  { id: 'tilt_up', title: '仰摇升格 Tilt Up', motion_key: 'tilt_up', params: { dolly: 0, pan: 0, tilt: 0.45, zoom: 0 } },
  { id: 'orbit_360', title: '环绕运镜 Orbit 360°', motion_key: 'orbit_360', params: { dolly: 0.1, pan: 1.0, tilt: 0.1, zoom: 0 } },
  { id: 'dolly_zoom', title: '希区柯克变焦 Dolly Zoom', motion_key: 'dolly_zoom', params: { dolly: 0.7, pan: 0, tilt: 0, zoom: -0.65 } },
  { id: 'handheld', title: '手持呼吸跟随 Handheld', motion_key: 'handheld', params: { dolly: 0.2, pan: 0.12, tilt: 0.08, zoom: 0.05 } },
];

export const GENERATE_IMAGE_PRESETS = [
  ['three_view', '角色三视图'],
  ['headshot', '生成大头照'],
  ['face_views', '角色脸部三视图'],
  ['multi_camera_grid_2k', '多机位九宫格2K'],
  ['multi_camera_grid_4k', '多机位九宫格4K'],
  ['story_four_grid', '剧情推进四格'],
  ['cinematic_lighting', '电影级光影校正'],
  ['frame_predict_3s_after', '画面推演3s后'],
  ['frame_predict_5s_before', '画面推演5s前'],
];

export function computeColorCssFilter({ filterId = 'original', strength = 100, hue = 0, saturation = 0, brightness = 0, contrast = 0 } = {}) {
  const preset = COLOR_FILTERS.find(item => item.id === filterId) || COLOR_FILTERS[0];
  const ratio = Math.max(0, Math.min(100, Number(strength ?? 100))) / 100;
  const h = Math.round((preset.hue * ratio) + Number(hue || 0));
  const s = Math.max(0, 100 + Math.round((preset.sat * ratio) + Number(saturation || 0)));
  const b = Math.max(10, 100 + Math.round((preset.bri * ratio) + Number(brightness || 0)));
  const c = Math.max(10, 100 + Math.round((preset.con * ratio) + Number(contrast || 0)));
  if (h === 0 && s === 100 && b === 100 && c === 100) return 'none';
  return `hue-rotate(${h}deg) saturate(${s}%) brightness(${b}%) contrast(${c}%)`;
}

export function isColorStateIdentity(state = {}) {
  const filterId = state.filterId || 'original';
  return (
    filterId === 'original' &&
    Number(state.hue || 0) === 0 &&
    Number(state.saturation || 0) === 0 &&
    Number(state.brightness || 0) === 0 &&
    Number(state.contrast || 0) === 0
  );
}

export function roundClipTime(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n * 100) / 100;
}

export function parseLrcTimeline(rawText = '') {
  const lines = String(rawText || '').split(/\r?\n/);
  const parsed = [];
  const tagRe = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const matches = [...trimmed.matchAll(tagRe)];
    const lyric = trimmed.replace(tagRe, '').trim();
    if (matches.length) {
      for (const m of matches) {
        const min = Number(m[1] || 0);
        const sec = Number(m[2] || 0);
        const fracRaw = m[3] || '0';
        const frac = Number(fracRaw) / (fracRaw.length === 3 ? 1000 : fracRaw.length === 2 ? 100 : 10);
        parsed.push({
          startSec: roundClipTime(min * 60 + sec + frac),
          lyric: lyric || '（器乐间奏）',
          visualPrompt: lyric ? `${lyric} · 节奏画面` : '器乐律动空镜',
          singerNodeId: '',
        });
      }
    } else if (!trimmed.startsWith('[')) {
      const idx = parsed.length;
      parsed.push({
        startSec: roundClipTime(idx * 4),
        lyric: trimmed,
        visualPrompt: `${trimmed} · 情绪特写`,
        singerNodeId: '',
      });
    }
  }
  parsed.sort((a, b) => a.startSec - b.startSec);
  for (let i = 0; i < parsed.length; i += 1) {
    parsed[i].endSec = i + 1 < parsed.length ? Math.max(roundClipTime(parsed[i].startSec + 0.5), parsed[i + 1].startSec) : roundClipTime(parsed[i].startSec + 4);
  }
  return parsed;
}

export function formatLrcTimestamp(sec) {
  const safe = Math.max(0, Number(sec || 0));
  const mins = Math.floor(safe / 60);
  const rem = safe - mins * 60;
  const whole = Math.floor(rem);
  const cs = Math.round((rem - whole) * 100);
  return `[${String(mins).padStart(2, '0')}:${String(whole).padStart(2, '0')}.${String(Math.min(99, cs)).padStart(2, '0')}]`;
}

export function serializeLrcTimeline(rows = []) {
  return rows.map(row => `${formatLrcTimestamp(row.startSec)} ${String(row.lyric || '').trim()}`).join('\n');
}

export function buildDeterministicPeaks(seedKey = '', count = 42) {
  const seed = String(seedKey || 'audio');
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const bars = [];
  for (let i = 0; i < count; i += 1) {
    h ^= i + 17;
    h = Math.imul(h, 16777619);
    const norm = ((h >>> 0) % 1000) / 1000;
    bars.push(0.18 + norm * 0.76);
  }
  return bars;
}

export function drawAudioWaveformCanvas(canvasEl, seedKey, clipStartRatio = 0, clipEndRatio = 1, progressRatio = 0) {
  if (!canvasEl || typeof canvasEl.getContext !== 'function') return;
  const ctx2d = canvasEl.getContext('2d');
  if (!ctx2d || typeof ctx2d.clearRect !== 'function' || typeof ctx2d.fillRect !== 'function') return;
  const w = canvasEl.width || 240;
  const h = canvasEl.height || 44;
  ctx2d.clearRect(0, 0, w, h);
  const peaks = buildDeterministicPeaks(seedKey, 48);
  const barGap = w / peaks.length;
  const barW = Math.max(2, barGap * 0.56);
  for (let i = 0; i < peaks.length; i += 1) {
    const ratio = i / peaks.length;
    const inClip = ratio >= clipStartRatio && ratio <= clipEndRatio;
    const played = ratio <= progressRatio && inClip;
    ctx2d.fillStyle = !inClip ? '#3a3a3c' : played ? '#30d158' : '#7c7c80';
    const bh = Math.max(4, Math.round(peaks[i] * (h - 8)));
    const x = Math.round(i * barGap + (barGap - barW) / 2);
    const y = Math.round((h - bh) / 2);
    ctx2d.fillRect(x, y, barW, bh);
  }
}

function makeEl(tag, text = null, cls = '') {
  const n = document.createElement(tag);
  if (text !== null && text !== undefined) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}

export function renderPhotographySettings(host, params = {}, onChange) {
  const wrap = makeEl('div', null, 'cc-photo-settings');
  const head = makeEl('div', null, 'cc-photo-settings-head');
  const toggleLabel = makeEl('label', '摄影机参数 ', 'cc-photo-toggle');
  const toggle = makeEl('input');
  toggle.type = 'checkbox';
  toggle.setAttribute('aria-label', '启用摄影机参数');
  toggle.checked = Boolean(params.photography_enabled);
  toggleLabel.append(toggle);
  const summary = makeEl(
    'small',
    toggle.checked
      ? `${params.camera_model || PHOTOGRAPHY_CAMERAS[0]} · ${params.lens_model || PHOTOGRAPHY_LENSES[0]} · ${params.focal_length_mm || 8}mm · ${params.aperture || 'f1.4'}`
      : '默认关闭（启用后固定相机/镜头/焦距/光圈）',
    'cc-photo-summary'
  );
  head.append(toggleLabel, summary);
  const body = makeEl('div', null, 'cc-photo-settings-grid');
  body.hidden = !toggle.checked;

  const buildSelect = (labelText, items, currentValue, key) => {
    const label = makeEl('label', labelText);
    const sel = makeEl('select');
    sel.setAttribute('aria-label', labelText);
    for (const item of items) {
      const opt = makeEl('option', String(item).endsWith('mm') || typeof item !== 'number' ? String(item) : `${item}mm`);
      opt.value = String(item);
      sel.append(opt);
    }
    sel.value = String(currentValue);
    sel.onchange = () => {
      onChange({ [key]: key === 'focal_length_mm' ? Number(sel.value) : sel.value });
    };
    label.append(sel);
    return label;
  };

  body.append(
    buildSelect('摄影机型号', PHOTOGRAPHY_CAMERAS, params.camera_model || PHOTOGRAPHY_CAMERAS[0], 'camera_model'),
    buildSelect('镜头系列', PHOTOGRAPHY_LENSES, params.lens_model || PHOTOGRAPHY_LENSES[0], 'lens_model'),
    buildSelect('焦距(mm)', PHOTOGRAPHY_FOCAL_LENGTHS, params.focal_length_mm || PHOTOGRAPHY_FOCAL_LENGTHS[0], 'focal_length_mm'),
    buildSelect('光圈', PHOTOGRAPHY_APERTURES, params.aperture || PHOTOGRAPHY_APERTURES[0], 'aperture')
  );

  toggle.onchange = () => {
    body.hidden = !toggle.checked;
    const patch = { photography_enabled: toggle.checked };
    if (toggle.checked) {
      patch.camera_model = params.camera_model || PHOTOGRAPHY_CAMERAS[0];
      patch.lens_model = params.lens_model || PHOTOGRAPHY_LENSES[0];
      patch.focal_length_mm = Number(params.focal_length_mm || PHOTOGRAPHY_FOCAL_LENGTHS[0]);
      patch.aperture = params.aperture || PHOTOGRAPHY_APERTURES[0];
    }
    onChange(patch);
  };

  wrap.append(head, body);
  host.append(wrap);
  return wrap;
}

export function openPortraitTexturePopover(host, initialSettings = {}, { onApply, onClose }) {
  const state = { ...DEFAULT_PORTRAIT_TEXTURE, ...(initialSettings || {}) };
  const panel = makeEl('div', null, 'cc-floating-editor cc-portrait-texture-popover');
  panel.onclick = ev => ev.stopPropagation?.();
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '人像质感调节参数');
  panel.append(makeEl('h4', '人像质感调节 · 五维质感矩阵'));
  for (const group of PORTRAIT_TEXTURE_GROUPS) {
    const row = makeEl('div', null, 'cc-texture-row');
    row.append(makeEl('span', group.label, 'cc-texture-row-label'));
    const seg = makeEl('div', null, 'cc-texture-seg');
    for (const [val, text] of group.options) {
      const b = makeEl('button', text, state[group.key] === val ? 'is-active' : '');
      b.type = 'button';
      b.onclick = () => {
        state[group.key] = val;
        for (const sibling of seg.querySelectorAll('button')) sibling.classList.remove('is-active');
        b.classList.add('is-active');
      };
      seg.append(b);
    }
    row.append(seg);
    panel.append(row);
  }
  const foot = makeEl('div', null, 'cc-editor-actions');
  const resetBtn = makeEl('button', '重置');
  resetBtn.type = 'button';
  resetBtn.onclick = () => {
    Object.assign(state, DEFAULT_PORTRAIT_TEXTURE);
    panel.remove();
    openPortraitTexturePopover(host, state, { onApply, onClose });
  };
  const closeBtn = makeEl('button', '关闭');
  closeBtn.type = 'button';
  closeBtn.onclick = () => { panel.remove(); onClose?.(); };
  const applyBtn = makeEl('button', '应用参数', 'cc-primary-btn');
  applyBtn.type = 'button';
  applyBtn.onclick = () => { onApply?.({ ...state }); panel.remove(); };
  foot.append(resetBtn, closeBtn, applyBtn);
  panel.append(foot);
  host.append(panel);
  return () => panel.remove();
}

export function openPortraitEmotionPanel(host, initialSettings = {}, { onCreateNode, onClose }) {
  const state = {
    valence: Number(initialSettings.valence ?? 0),
    arousal: Number(initialSettings.arousal ?? 0),
    brow: Number(initialSettings.brow ?? 0),
    eye: Number(initialSettings.eye ?? 0),
    mouth: Number(initialSettings.mouth ?? 0),
    head_tilt: Number(initialSettings.head_tilt ?? 0),
    skin_polish: initialSettings.skin_polish || 'natural',
  };
  const panel = makeEl('div', null, 'cc-floating-editor cc-portrait-emotion-panel');
  panel.onclick = ev => ev.stopPropagation?.();
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '人像情绪与五官精控');
  panel.append(makeEl('h4', '情绪调节 · 2D 情绪触控板'));

  const padWrap = makeEl('div', null, 'cc-emotion-pad-wrap');
  const pad = makeEl('div', null, 'canvas-portrait-emotion-pad');
  pad.setAttribute('aria-label', '2D XY 情绪触控板');
  pad.tabIndex = 0;
  const axisTop = makeEl('span', '激动 +Y', 'cc-pad-label cc-pad-top');
  const axisBottom = makeEl('span', '平静 -Y', 'cc-pad-label cc-pad-bottom');
  const axisLeft = makeEl('span', '悲伤 -X', 'cc-pad-label cc-pad-left');
  const axisRight = makeEl('span', '喜悦 +X', 'cc-pad-label cc-pad-right');
  const dot = makeEl('div', null, 'cc-emotion-pad-dot');
  const readout = makeEl('small', '', 'cc-emotion-readout');

  const syncDot = () => {
    const px = ((state.valence + 1) / 2) * 100;
    const py = ((1 - state.arousal) / 2) * 100;
    dot.style.left = `${Math.max(4, Math.min(96, px))}%`;
    dot.style.top = `${Math.max(4, Math.min(96, py))}%`;
    readout.textContent = `喜悦度 X: ${state.valence.toFixed(2)} · 唤醒度 Y: ${state.arousal.toFixed(2)}`;
  };
  syncDot();

  const updateFromPointer = ev => {
    const rect = pad.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const nx = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
    const ny = Math.max(0, Math.min(1, (ev.clientY - rect.top) / rect.height));
    state.valence = Math.round((nx * 2 - 1) * 100) / 100;
    state.arousal = Math.round((1 - ny * 2) * 100) / 100;
    syncDot();
  };
  let dragging = false;
  pad.onpointerdown = ev => { dragging = true; updateFromPointer(ev); };
  pad.onpointermove = ev => { if (dragging) updateFromPointer(ev); };
  pad.onpointerup = () => { dragging = false; };
  pad.append(axisTop, axisBottom, axisLeft, axisRight, dot);
  padWrap.append(pad, readout);
  panel.append(padWrap);

  const sliders = makeEl('div', null, 'cc-emotion-sliders');
  const sliderPairs = [];
  for (const [key, title] of [['brow', '眉头舒展'], ['eye', '眼神开合'], ['mouth', '嘴角弧度'], ['head_tilt', '头部微倾']]) {
    const label = makeEl('label', `${title} `);
    const range = makeEl('input');
    range.type = 'range';
    range.min = '-100';
    range.max = '100';
    range.value = String(state[key]);
    range.setAttribute('aria-label', title);
    const valSpan = makeEl('span', String(state[key]), 'cc-range-val');
    range.oninput = () => { state[key] = Number(range.value); valSpan.textContent = range.value; };
    label.append(range, valSpan);
    sliders.append(label);
    sliderPairs.push([range, valSpan]);
  }
  panel.append(sliders);

  const foot = makeEl('div', null, 'cc-editor-actions');
  const resetBtn = makeEl('button', '重置');
  resetBtn.type = 'button';
  resetBtn.onclick = () => {
    state.valence = 0; state.arousal = 0; state.brow = 0; state.eye = 0; state.mouth = 0; state.head_tilt = 0;
    syncDot();
    for (const [r, valSpan] of sliderPairs) {
      r.value = '0';
      valSpan.textContent = '0';
    }
  };
  const closeBtn = makeEl('button', '关闭');
  closeBtn.type = 'button';
  closeBtn.onclick = () => { panel.remove(); onClose?.(); };
  const applyBtn = makeEl('button', '创建情绪调节节点', 'cc-primary-btn');
  applyBtn.type = 'button';
  applyBtn.onclick = () => { onCreateNode?.({ ...state }); panel.remove(); };
  foot.append(resetBtn, closeBtn, applyBtn);
  panel.append(foot);
  host.append(panel);
  return () => panel.remove();
}

export function openColorAdjustEditor(host, nodeCard, { onSubmit, onClose }) {
  const img = nodeCard?.querySelector('img');
  const prevFilter = img ? img.style.filter : '';
  const state = { filterId: 'original', category: 'all', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0 };

  const panel = makeEl('div', null, 'cc-floating-editor cc-color-adjust-panel');
  panel.onclick = ev => ev.stopPropagation?.();
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '调色与滤镜面板');
  panel.append(makeEl('h4', '调色（支持21款电影/胶片滤镜）'));

  const catBar = makeEl('div', null, 'cc-filter-cat-bar');
  const filterStrip = makeEl('div', null, 'cc-filter-strip');
  let confirmBtn = null;

  const applyPreview = (showOriginal = false) => {
    if (img) img.style.filter = showOriginal ? 'none' : computeColorCssFilter(state);
    if (confirmBtn) confirmBtn.disabled = isColorStateIdentity(state);
  };

  let contrastRange = null, contrastVal = null;
  const renderFilters = () => {
    filterStrip.replaceChildren();
    for (const f of COLOR_FILTERS.filter(item => item.cat.includes(state.category))) {
      const chip = makeEl('button', f.label, state.filterId === f.id ? 'cc-filter-chip is-active' : 'cc-filter-chip');
      chip.type = 'button';
      chip.onclick = () => {
        state.filterId = f.id;
        if (f.id === 'natural_enhance' && state.contrast === 0) {
          state.contrast = 5;
          if (contrastRange) contrastRange.value = '5';
          if (contrastVal) contrastVal.textContent = '5';
        }
        renderFilters();
        applyPreview(false);
      };
      filterStrip.append(chip);
    }
  };

  for (const [catId, catLabel] of COLOR_FILTER_CATEGORIES) {
    const tab = makeEl('button', catLabel, state.category === catId ? 'is-active' : '');
    tab.type = 'button';
    tab.onclick = () => {
      state.category = catId;
      for (const b of catBar.querySelectorAll('button')) b.classList.remove('is-active');
      tab.classList.add('is-active');
      renderFilters();
    };
    catBar.append(tab);
  }
  renderFilters();
  panel.append(catBar, filterStrip);

  const controls = makeEl('div', null, 'cc-color-sliders');
  const addSlider = (labelText, key, min, max) => {
    const row = makeEl('label', labelText);
    const input = makeEl('input');
    input.type = 'range';
    input.min = String(min);
    input.max = String(max);
    input.value = String(state[key]);
    input.setAttribute('aria-label', labelText);
    const out = makeEl('span', String(state[key]), 'cc-range-val');
    input.oninput = () => {
      state[key] = Number(input.value);
      out.textContent = input.value;
      applyPreview(false);
    };
    row.append(input, out);
    controls.append(row);
    return [input, out];
  };
  const [strengthRange, strengthVal] = addSlider('滤镜强度', 'strength', 0, 100);
  const [hueRange, hueVal] = addSlider('色相', 'hue', -180, 180);
  const [satRange, satVal] = addSlider('饱和度', 'saturation', -100, 100);
  const [briRange, briVal] = addSlider('明度', 'brightness', -100, 100);
  [contrastRange, contrastVal] = addSlider('对比度', 'contrast', -100, 100);
  panel.append(controls);

  const foot = makeEl('div', null, 'cc-editor-actions');
  const resetBtn = makeEl('button', '重置');
  resetBtn.type = 'button';
  resetBtn.onclick = () => {
    Object.assign(state, { filterId: 'original', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0 });
    strengthRange.value = '100'; strengthVal.textContent = '100';
    hueRange.value = '0'; hueVal.textContent = '0';
    satRange.value = '0'; satVal.textContent = '0';
    briRange.value = '0'; briVal.textContent = '0';
    contrastRange.value = '0'; contrastVal.textContent = '0';
    renderFilters();
    applyPreview(false);
  };
  const compareBtn = makeEl('button', '按住看原图');
  compareBtn.type = 'button';
  compareBtn.onpointerdown = () => applyPreview(true);
  compareBtn.onpointerup = () => applyPreview(false);
  compareBtn.onpointerleave = () => applyPreview(false);
  const closeBtn = makeEl('button', '关闭');
  closeBtn.type = 'button';
  const cleanup = () => {
    if (img) img.style.filter = prevFilter;
    panel.remove();
  };
  closeBtn.onclick = () => { cleanup(); onClose?.(); };
  confirmBtn = makeEl('button', '确认', 'cc-primary-btn');
  confirmBtn.type = 'button';
  confirmBtn.disabled = true;
  confirmBtn.onclick = async () => {
    confirmBtn.disabled = true;
    try {
      await onSubmit?.({ ...state });
      cleanup();
    } catch (err) {
      confirmBtn.disabled = isColorStateIdentity(state);
      throw err;
    }
  };
  foot.append(resetBtn, compareBtn, closeBtn, confirmBtn);
  panel.append(foot);
  host.append(panel);
  return cleanup;
}

export function openCropOverlay(nodeCard, { naturalWidth = 1024, naturalHeight = 1024, onSubmit, onClose }) {
  const overlay = makeEl('div', null, 'cc-crop-overlay');
  overlay.setAttribute('aria-label', '图片裁剪框');
  const box = makeEl('div', null, 'cc-crop-box');
  for (let i = 0; i < 4; i += 1) box.append(makeEl('i', null, `cc-crop-third cc-crop-third-${i}`));
  for (const h of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
    const handle = makeEl('span', null, `cc-crop-handle cc-crop-handle-${h}`);
    handle.dataset.handle = h;
    box.append(handle);
  }
  overlay.append(box);

  const state = { ratioKey: 'original', x: 0, y: 0, w: 1, h: 1 };
  const syncBox = () => {
    box.style.left = `${(state.x * 100).toFixed(2)}%`;
    box.style.top = `${(state.y * 100).toFixed(2)}%`;
    box.style.width = `${(state.w * 100).toFixed(2)}%`;
    box.style.height = `${(state.h * 100).toFixed(2)}%`;
  };
  const applyRatio = (ratioKey, targetAspect) => {
    state.ratioKey = ratioKey;
    if (!targetAspect) {
      Object.assign(state, { x: 0, y: 0, w: 1, h: 1 });
    } else {
      const imgAspect = Math.max(0.05, Number(naturalWidth || 1) / Math.max(1, Number(naturalHeight || 1)));
      if (imgAspect > targetAspect) {
        state.h = 1;
        state.w = Math.min(1, targetAspect / imgAspect);
        state.x = (1 - state.w) / 2;
        state.y = 0;
      } else {
        state.w = 1;
        state.h = Math.min(1, imgAspect / targetAspect);
        state.x = 0;
        state.y = (1 - state.h) / 2;
      }
    }
    syncBox();
  };
  syncBox();

  const bar = makeEl('div', null, 'cc-crop-bar');
  const closeBtn = makeEl('button', '关闭');
  closeBtn.type = 'button';
  const cleanup = () => { overlay.remove(); bar.remove(); };
  closeBtn.onclick = () => { cleanup(); onClose?.(); };
  bar.append(closeBtn);
  for (const [key, label, aspect] of CROP_RATIOS) {
    const b = makeEl('button', label, key === 'original' ? 'is-active' : '');
    b.type = 'button';
    b.onclick = () => {
      for (const sib of bar.querySelectorAll('.cc-crop-ratio-btn')) sib.classList.remove('is-active');
      b.classList.add('is-active');
      applyRatio(key, aspect);
    };
    b.classList.add('cc-crop-ratio-btn');
    bar.append(b);
  }
  const submitBtn = makeEl('button', '确认裁剪', 'cc-primary-btn');
  submitBtn.type = 'button';
  submitBtn.onclick = async () => {
    submitBtn.disabled = true;
    try {
      await onSubmit?.({ ...state });
      cleanup();
    } finally {
      if (submitBtn.isConnected) submitBtn.disabled = false;
    }
  };
  bar.append(submitBtn);
  nodeCard.append(overlay, bar);
  return cleanup;
}

export function openRotateOverlay(nodeCard, { onSubmit, onClose }) {
  const img = nodeCard.querySelector('img');
  const prevTransform = img ? img.style.transform : '';
  const state = { degrees: 0, flipX: false, flipY: false };
  const bar = makeEl('div', null, 'cc-rotate-bar');
  bar.setAttribute('role', 'dialog');
  bar.setAttribute('aria-label', '图片旋转与翻转');
  const syncPreview = () => {
    if (!img) return;
    const sx = state.flipX ? -1 : 1;
    const sy = state.flipY ? -1 : 1;
    img.style.transform = `rotate(${state.degrees}deg) scale(${sx}, ${sy})`;
  };
  const range = makeEl('input');
  range.type = 'range'; range.min = '-180'; range.max = '180'; range.value = '0';
  range.setAttribute('aria-label', '旋转角度');
  const degLabel = makeEl('span', '0°', 'cc-range-val');
  range.oninput = () => { state.degrees = Number(range.value); degLabel.textContent = `${state.degrees}°`; syncPreview(); };
  const rotLeft = makeEl('button', '-90°'); rotLeft.type = 'button';
  rotLeft.onclick = () => { state.degrees = ((state.degrees - 90 + 540) % 360) - 180; range.value = String(state.degrees); degLabel.textContent = `${state.degrees}°`; syncPreview(); };
  const rotRight = makeEl('button', '+90°'); rotRight.type = 'button';
  rotRight.onclick = () => { state.degrees = ((state.degrees + 90 + 540) % 360) - 180; range.value = String(state.degrees); degLabel.textContent = `${state.degrees}°`; syncPreview(); };
  const flipH = makeEl('button', '水平翻转'); flipH.type = 'button';
  flipH.onclick = () => { state.flipX = !state.flipX; syncPreview(); };
  const flipV = makeEl('button', '垂直翻转'); flipV.type = 'button';
  flipV.onclick = () => { state.flipY = !state.flipY; syncPreview(); };
  const cleanup = () => { if (img) img.style.transform = prevTransform; bar.remove(); };
  const closeBtn = makeEl('button', '关闭'); closeBtn.type = 'button';
  closeBtn.onclick = () => { cleanup(); onClose?.(); };
  const okBtn = makeEl('button', '确认旋转', 'cc-primary-btn'); okBtn.type = 'button';
  okBtn.onclick = async () => {
    okBtn.disabled = true;
    try {
      await onSubmit?.({ ...state });
      cleanup();
    } finally {
      if (okBtn.isConnected) okBtn.disabled = false;
    }
  };
  bar.append(rotLeft, range, degLabel, rotRight, flipH, flipV, closeBtn, okBtn);
  nodeCard.append(bar);
  return cleanup;
}

export function openDoodleOverlay(nodeCard, { onSubmit, onClose }) {
  const canvas = makeEl('canvas', null, 'cc-doodle-canvas');
  canvas.width = 480; canvas.height = 320;
  canvas.setAttribute('aria-label', '图片涂鸦画布');
  const strokes = [];
  let current = null;
  let color = '#ff3b30';
  let brushWidth = 6;
  const redraw = () => {
    const ctx2d = canvas.getContext?.('2d');
    if (!ctx2d) return;
    ctx2d.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of strokes) {
      if (!s.points.length) continue;
      if (s.points.length === 1) {
        if (typeof ctx2d.arc === 'function' && typeof ctx2d.fill === 'function') {
          ctx2d.fillStyle = s.color;
          ctx2d.beginPath();
          ctx2d.arc(s.points[0][0] * canvas.width, s.points[0][1] * canvas.height, Math.max(1, s.width / 2), 0, Math.PI * 2);
          ctx2d.fill();
        }
        continue;
      }
      ctx2d.strokeStyle = s.color;
      ctx2d.lineWidth = s.width;
      ctx2d.lineCap = 'round';
      ctx2d.lineJoin = 'round';
      ctx2d.beginPath();
      s.points.forEach(([x, y], idx) => {
        if (idx === 0) ctx2d.moveTo(x * canvas.width, y * canvas.height);
        else ctx2d.lineTo(x * canvas.width, y * canvas.height);
      });
      ctx2d.stroke();
    }
  };
  const pt = ev => {
    const r = canvas.getBoundingClientRect();
    if (!r.width || !r.height) return [0.5, 0.5];
    return [Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height))];
  };
  canvas.onpointerdown = ev => {
    ev.stopPropagation();
    current = { color, width: brushWidth, points: [pt(ev)] };
    strokes.push(current);
    redraw();
  };
  canvas.onpointermove = ev => {
    if (!current) return;
    ev.stopPropagation();
    current.points.push(pt(ev));
    redraw();
  };
  canvas.onpointerup = () => { current = null; };

  const bar = makeEl('div', null, 'cc-doodle-bar');
  for (const hex of ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#0a84ff', '#ffffff']) {
    const sw = makeEl('button', '', color === hex ? 'cc-swatch is-active' : 'cc-swatch');
    sw.type = 'button';
    sw.dataset.color = hex;
    sw.style.backgroundColor = hex;
    sw.onclick = () => { color = hex; for (const b of bar.querySelectorAll('.cc-swatch')) b.classList.remove('is-active'); sw.classList.add('is-active'); };
    bar.append(sw);
  }
  const widthRange = makeEl('input');
  widthRange.type = 'range'; widthRange.min = '1'; widthRange.max = '64'; widthRange.value = String(brushWidth);
  widthRange.setAttribute('aria-label', '涂鸦笔宽');
  const widthBadge = makeEl('span', `${brushWidth}px`, 'cc-range-val');
  widthRange.oninput = () => {
    brushWidth = Math.max(1, Math.min(64, Number(widthRange.value) || 6));
    widthBadge.textContent = `${brushWidth}px`;
  };
  const undoBtn = makeEl('button', '撤销笔触'); undoBtn.type = 'button';
  undoBtn.onclick = () => { strokes.pop(); redraw(); };
  const clearBtn = makeEl('button', '清空'); clearBtn.type = 'button';
  clearBtn.onclick = () => { strokes.length = 0; redraw(); };
  const cleanup = () => { canvas.remove(); bar.remove(); };
  const closeBtn = makeEl('button', '关闭'); closeBtn.type = 'button';
  closeBtn.onclick = () => { cleanup(); onClose?.(); };
  const okBtn = makeEl('button', '保存涂鸦', 'cc-primary-btn'); okBtn.type = 'button';
  okBtn.onclick = async () => {
    okBtn.disabled = true;
    try {
      await onSubmit?.({ strokes: strokes.map(s => ({ ...s })) });
      cleanup();
    } finally {
      if (okBtn.isConnected) okBtn.disabled = false;
    }
  };
  bar.append(widthRange, widthBadge, undoBtn, clearBtn, closeBtn, okBtn);
  nodeCard.append(canvas, bar);
  return cleanup;
}

export function openSingleVideoClipDialog(host, videoNode, { onSave, onClose }) {
  const dlg = makeEl('dialog', null, 'cc-modal-dialog canvas-single-video-clip-dialog');
  dlg.setAttribute('aria-label', '单视频片段截取');
  let start = roundClipTime(videoNode.params?.leftClipTime ?? 0);
  let end = roundClipTime(videoNode.params?.rightClipTime ?? 5);
  if (end <= start) end = roundClipTime(start + 3);

  dlg.append(makeEl('h3', `单视频区间截取 · ${videoNode.title}`));
  const form = makeEl('div', null, 'cc-clip-range-fields');
  const startLabel = makeEl('label', '入点秒数 (leftClipTime)');
  const startInput = makeEl('input');
  startInput.type = 'number'; startInput.step = '0.01'; startInput.min = '0'; startInput.value = start.toFixed(2);
  startInput.setAttribute('aria-label', '入点秒数');
  startLabel.append(startInput);
  const endLabel = makeEl('label', '出点秒数 (rightClipTime)');
  const endInput = makeEl('input');
  endInput.type = 'number'; endInput.step = '0.01'; endInput.min = '0.05'; endInput.value = end.toFixed(2);
  endInput.setAttribute('aria-label', '出点秒数');
  endLabel.append(endInput);
  const errMsg = makeEl('p', '', 'cc-inline-error');
  errMsg.hidden = true;
  form.append(startLabel, endLabel, errMsg);
  dlg.append(form);

  const foot = makeEl('div', null, 'cc-editor-actions');
  const close = () => { try { dlg.close?.(); } catch {} dlg.remove(); onClose?.(); };
  const cancelBtn = makeEl('button', '取消'); cancelBtn.type = 'button'; cancelBtn.onclick = close;
  const saveBtn = makeEl('button', '保存截取区间', 'cc-primary-btn'); saveBtn.type = 'button';
  saveBtn.onclick = async () => {
    const sVal = roundClipTime(startInput.value);
    const eVal = roundClipTime(endInput.value);
    if (!(sVal < eVal)) {
      errMsg.hidden = false;
      errMsg.textContent = '入点时间必须小于出点时间（保留两位小数）';
      return;
    }
    errMsg.hidden = true;
    await onSave?.({ leftClipTime: sVal, rightClipTime: eVal });
    close();
  };
  foot.append(cancelBtn, saveBtn);
  dlg.append(foot);
  host.append(dlg);
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  return close;
}

export function openMultiVideoEditDialog(host, editNode, { upstreamVideos = [], upstreamAudios = [], onAutoSave, onExport, onClose }) {
  const dlg = makeEl('dialog', null, 'cc-modal-dialog canvas-multi-video-edit-dialog');
  dlg.setAttribute('aria-label', '画布多视频剪辑编辑器');
  let savedSegments = [];
  try { savedSegments = JSON.parse(editNode.params?.segments_json || '[]'); } catch { savedSegments = []; }
  const segments = upstreamVideos.map((vNode, idx) => {
    const existing = savedSegments.find(s => s.source_node_key === vNode.id) || {};
    return {
      seg_id: existing.seg_id || `seg-${idx + 1}`,
      source_node_key: vNode.id,
      source_media_id: vNode.media_id,
      name: existing.name || vNode.title,
      start_time: roundClipTime(existing.start_time ?? 0),
      end_time: roundClipTime(existing.end_time ?? 4),
      muted: Boolean(existing.muted),
    };
  });
  let savedAudio = null;
  try { savedAudio = JSON.parse(editNode.params?.audio_json || 'null'); } catch { savedAudio = null; }
  const audioTrack = upstreamAudios[0]
    ? {
        source_node_key: upstreamAudios[0].id,
        source_media_id: upstreamAudios[0].media_id,
        offset: roundClipTime(savedAudio?.offset ?? 0),
        volume: Number(savedAudio?.volume ?? 1),
      }
    : null;

  let debounceTimer = null;
  const statusSpan = makeEl('small', '已就绪（500ms 防抖自动保存）', 'cc-clip-autosave-status');
  const scheduleSave = () => {
    statusSpan.textContent = '保存草稿中…';
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      try {
        await onAutoSave?.({ segments, audio: audioTrack });
        statusSpan.textContent = '草稿已自动保存';
      } catch (e) {
        statusSpan.textContent = `自动保存失败：${e?.message || e}`;
      }
    }, 500);
  };

  const header = makeEl('header', null, 'cc-multi-clip-header');
  header.append(makeEl('strong', `视频剪辑工作台 · ${editNode.title}`), statusSpan);
  const closeBtn = makeEl('button', '关闭'); closeBtn.type = 'button';
  const cleanup = () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    try { dlg.close?.(); } catch {}
    dlg.remove();
    onClose?.();
  };
  closeBtn.onclick = cleanup;
  header.append(closeBtn);
  dlg.append(header);

  const trackWrap = makeEl('div', null, 'cc-multi-clip-body');
  if (upstreamAudios.length > 1) {
    trackWrap.append(makeEl('p', '提示：多视频剪辑仅允许 1 条参考音轨来源，请移除多余音频连线后再导出。', 'cc-inline-error'));
  }
  const list = makeEl('div', null, 'cc-multi-clip-segments');
  for (const seg of segments) {
    const row = makeEl('div', null, 'cc-multi-clip-row');
    row.append(makeEl('strong', `${seg.name} (${seg.source_node_key})`));
    const sIn = makeEl('input'); sIn.type = 'number'; sIn.step = '0.1'; sIn.min = '0'; sIn.value = seg.start_time.toFixed(2);
    sIn.setAttribute('aria-label', `${seg.name} 入点`);
    const eIn = makeEl('input'); eIn.type = 'number'; eIn.step = '0.1'; eIn.min = '0.1'; eIn.value = seg.end_time.toFixed(2);
    eIn.setAttribute('aria-label', `${seg.name} 出点`);
    const muteChk = makeEl('input'); muteChk.type = 'checkbox'; muteChk.checked = seg.muted;
    muteChk.setAttribute('aria-label', `${seg.name} 静音`);
    sIn.oninput = () => { seg.start_time = roundClipTime(sIn.value); scheduleSave(); };
    eIn.oninput = () => { seg.end_time = roundClipTime(eIn.value); scheduleSave(); };
    muteChk.onchange = () => { seg.muted = muteChk.checked; scheduleSave(); };
    const muteLabel = makeEl('label', '静音 '); muteLabel.append(muteChk);
    row.append(makeEl('span', '入点'), sIn, makeEl('span', '出点'), eIn, muteLabel);
    list.append(row);
  }
  trackWrap.append(list);

  if (audioTrack) {
    const aBox = makeEl('div', null, 'cc-multi-clip-audio');
    aBox.append(makeEl('strong', `背景音轨 · ${upstreamAudios[0].title}`));
    const offIn = makeEl('input'); offIn.type = 'number'; offIn.step = '0.1'; offIn.min = '0'; offIn.value = audioTrack.offset.toFixed(2);
    offIn.setAttribute('aria-label', '音轨起点偏移');
    offIn.oninput = () => { audioTrack.offset = roundClipTime(offIn.value); scheduleSave(); };
    aBox.append(makeEl('span', '起点偏移(s)'), offIn);
    trackWrap.append(aBox);
  }
  dlg.append(trackWrap);

  const foot = makeEl('footer', null, 'cc-editor-actions');
  const exportBtn = makeEl('button', '导出成片至右侧节点', 'cc-primary-btn');
  exportBtn.type = 'button';
  exportBtn.disabled = !segments.length || upstreamAudios.length > 1;
  exportBtn.onclick = async () => {
    exportBtn.disabled = true;
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
    try {
      await onAutoSave?.({ segments, audio: audioTrack });
      await onExport?.({ segments, audio: audioTrack });
      cleanup();
    } finally {
      if (exportBtn.isConnected && segments.length && upstreamAudios.length <= 1) exportBtn.disabled = false;
    }
  };
  foot.append(exportBtn);
  dlg.append(foot);
  host.append(dlg);
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  return cleanup;
}

export function openCameraMotionDialog(host, videoNode, { builtinTemplates = null, customTemplates = [], onSaveTemplate, onToggleFavorite, onDeleteTemplate, onApplyMotion, onClose }) {
  const dlg = makeEl('dialog', null, 'cc-modal-dialog canvas-video-camera-motion-dialog');
  dlg.setAttribute('aria-label', '相机运镜库');
  dlg.append(makeEl('h3', '相机运镜库 · 预设与自定义收藏'));
  const grid = makeEl('div', null, 'cc-motion-grid');
  const builtins = Array.isArray(builtinTemplates) && builtinTemplates.length
    ? builtinTemplates.map(m => ({ ...m, builtin: true, favorite: false }))
    : BUILTIN_CAMERA_MOTIONS.map(m => ({
        id: m.id,
        name: m.title,
        prompt_fragment: `${m.title}（推进 ${m.params.dolly} / 水平 ${m.params.pan} / 俯仰 ${m.params.tilt}）`,
        horizontal_pan: Math.round((m.params.pan || 0) * 100),
        vertical_tilt: Math.round((m.params.tilt || 0) * 100),
        zoom_delta: Math.round((m.params.dolly || 0) * 100),
        roll_deg: 0,
        speed_preset: 'normal',
        builtin: true,
        favorite: false,
      }));
  const allItems = [
    ...builtins,
    ...customTemplates.map(m => ({ ...m, builtin: false, favorite: Boolean(m.favorite ?? m.favorited) })),
  ];
  for (const item of allItems) {
    const label = item.name || item.title || '运镜模板';
    const card = makeEl('div', null, 'cc-motion-card');
    card.append(makeEl('strong', label));
    if (item.prompt_fragment) card.append(makeEl('small', item.prompt_fragment));
    const row = makeEl('div', null, 'cc-motion-card-actions');
    const useBtn = makeEl('button', '应用运镜', 'cc-primary-btn');
    useBtn.type = 'button';
    useBtn.onclick = async () => {
      await onApplyMotion?.(item);
      try { dlg.close?.(); } catch {}
      dlg.remove();
    };
    row.append(useBtn);
    if (!item.builtin) {
      const favBtn = makeEl('button', item.favorite ? '★ 已收藏' : '☆ 收藏');
      favBtn.type = 'button';
      favBtn.onclick = async () => {
        await onToggleFavorite?.(item);
        try { dlg.close?.(); } catch {}
        dlg.remove();
      };
      const delBtn = makeEl('button', '删除');
      delBtn.type = 'button';
      delBtn.onclick = async () => {
        await onDeleteTemplate?.(item);
        try { dlg.close?.(); } catch {}
        dlg.remove();
      };
      row.append(favBtn, delBtn);
    }
    card.append(row);
    grid.append(card);
  }
  dlg.append(grid);

  const customBox = makeEl('div', null, 'cc-motion-custom-create');
  const nameIn = makeEl('input'); nameIn.placeholder = '输入自定义运镜名称（如：环绕升格推进）';
  nameIn.setAttribute('aria-label', '自定义运镜名称');
  const keyIn = makeEl('select'); keyIn.setAttribute('aria-label', '运镜基底');
  for (const m of builtins) {
    const o = makeEl('option', m.name || m.title); o.value = m.id; keyIn.append(o);
  }
  const addBtn = makeEl('button', '保存为自定义模板'); addBtn.type = 'button';
  addBtn.onclick = async () => {
    const trimmed = nameIn.value.trim();
    if (!trimmed) return;
    const basePreset = builtins.find(m => m.id === keyIn.value) || builtins[0] || {};
    await onSaveTemplate?.({
      name: trimmed,
      prompt_fragment: `${trimmed} · ${basePreset.prompt_fragment || '平滑电影级运镜'}`,
      horizontal_pan: Number.isInteger(basePreset.horizontal_pan) ? basePreset.horizontal_pan : 0,
      vertical_tilt: Number.isInteger(basePreset.vertical_tilt) ? basePreset.vertical_tilt : 0,
      zoom_delta: Number.isInteger(basePreset.zoom_delta) ? basePreset.zoom_delta : 20,
      roll_deg: Number.isInteger(basePreset.roll_deg) ? basePreset.roll_deg : 0,
      speed_preset: basePreset.speed_preset || 'normal',
    });
    try { dlg.close?.(); } catch {}
    dlg.remove();
  };
  customBox.append(nameIn, keyIn, addBtn);
  dlg.append(customBox);

  const foot = makeEl('div', null, 'cc-editor-actions');
  const closeBtn = makeEl('button', '关闭'); closeBtn.type = 'button';
  closeBtn.onclick = () => { try { dlg.close?.(); } catch {} dlg.remove(); onClose?.(); };
  foot.append(closeBtn);
  dlg.append(foot);
  host.append(dlg);
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  return () => { try { dlg.close?.(); } catch {} dlg.remove(); };
}

export function openLrcTimelineDialog(host, { initialLrcText = '', imageNodes = [], onSaveLrc, onSpawnStoryboard, onClose }) {
  const dlg = makeEl('dialog', null, 'cc-modal-dialog canvas-lyrics-timeline-dialog');
  dlg.setAttribute('aria-label', 'LRC 歌词时间轴与分镜映射');
  let activeTab = 'timeline';
  let rows = parseLrcTimeline(initialLrcText || '[00:00.00] 前奏霓虹初亮\n[00:04.20] 雨夜霓虹映入眼底\n[00:08.50] 副歌高潮奔向天际');

  const head = makeEl('div', null, 'cc-lrc-header');
  head.append(makeEl('h3', 'LRC 歌词时间轴对齐与 MV 分镜映射'));
  const tabBar = makeEl('div', null, 'cc-lrc-tabs');
  const tabTimeline = makeEl('button', '时间轴打点校准', 'is-active'); tabTimeline.type = 'button';
  const tabStory = makeEl('button', '歌词分镜映射'); tabStory.type = 'button';
  tabBar.append(tabTimeline, tabStory);
  head.append(tabBar);
  dlg.append(head);

  const body = makeEl('div', null, 'cc-lrc-body');
  dlg.append(body);

  const renderBody = () => {
    body.replaceChildren();
    if (activeTab === 'timeline') tabTimeline.classList.add('is-active');
    else tabTimeline.classList.remove('is-active');
    if (activeTab === 'storyboard') tabStory.classList.add('is-active');
    else tabStory.classList.remove('is-active');
    if (activeTab === 'timeline') {
      const box = makeEl('div', null, 'canvas-lyrics-timeline-content');
      const rawArea = makeEl('textarea', null, 'cc-lrc-raw');
      rawArea.setAttribute('aria-label', 'LRC 歌词原文');
      rawArea.value = serializeLrcTimeline(rows);
      const parseBtn = makeEl('button', '解析时间轴'); parseBtn.type = 'button';
      parseBtn.onclick = () => { rows = parseLrcTimeline(rawArea.value); renderBody(); };
      box.append(rawArea, parseBtn);
      const table = makeEl('div', null, 'cc-lrc-rows');
      rows.forEach((row, idx) => {
        const line = makeEl('div', null, 'cc-lrc-row');
        const tIn = makeEl('input'); tIn.type = 'number'; tIn.step = '0.1'; tIn.min = '0'; tIn.value = row.startSec.toFixed(2);
        tIn.setAttribute('aria-label', `第${idx + 1}句起始秒`);
        tIn.oninput = () => { row.startSec = roundClipTime(tIn.value); };
        const lIn = makeEl('input'); lIn.type = 'text'; lIn.value = row.lyric;
        lIn.setAttribute('aria-label', `第${idx + 1}句歌词`);
        lIn.oninput = () => { row.lyric = lIn.value; };
        line.append(makeEl('span', `#${idx + 1}`), tIn, lIn);
        table.append(line);
      });
      box.append(table);
      body.append(box);
    } else {
      const box = makeEl('div', null, 'canvas-lyrics-storyboard-content');
      rows.forEach((row, idx) => {
        const line = makeEl('div', null, 'cc-lrc-story-row');
        line.append(makeEl('strong', `${formatLrcTimestamp(row.startSec)} ${row.lyric}`));
        const pIn = makeEl('input'); pIn.type = 'text'; pIn.value = row.visualPrompt || '';
        pIn.placeholder = '输入此乐句视觉画面描述';
        pIn.setAttribute('aria-label', `第${idx + 1}句分镜画面`);
        pIn.oninput = () => { row.visualPrompt = pIn.value; };
        const refSel = makeEl('select');
        refSel.setAttribute('aria-label', `第${idx + 1}句歌手参考图`);
        const emptyOpt = makeEl('option', '不绑定歌手形象图');
        emptyOpt.value = '';
        refSel.append(emptyOpt);
        for (const imgNode of imageNodes) {
          const opt = makeEl('option', imgNode.title);
          opt.value = imgNode.id;
          refSel.append(opt);
        }
        refSel.value = row.singerNodeId || '';
        refSel.onchange = () => { row.singerNodeId = refSel.value; };
        line.append(pIn, refSel);
        box.append(line);
      });
      body.append(box);
    }
  };
  tabTimeline.onclick = () => { activeTab = 'timeline'; renderBody(); };
  tabStory.onclick = () => { activeTab = 'storyboard'; renderBody(); };
  renderBody();

  const foot = makeEl('div', null, 'cc-editor-actions');
  const close = () => { try { dlg.close?.(); } catch {} dlg.remove(); onClose?.(); };
  const closeBtn = makeEl('button', '关闭'); closeBtn.type = 'button'; closeBtn.onclick = close;
  const saveBtn = makeEl('button', '保存 LRC 时间轴'); saveBtn.type = 'button';
  saveBtn.onclick = async () => { await onSaveLrc?.(serializeLrcTimeline(rows), rows); close(); };
  const spawnBtn = makeEl('button', '一键派生 MV 分镜视频节点', 'cc-primary-btn'); spawnBtn.type = 'button';
  spawnBtn.onclick = async () => { await onSpawnStoryboard?.(rows, serializeLrcTimeline(rows)); close(); };
  foot.append(closeBtn, saveBtn, spawnBtn);
  dlg.append(foot);
  host.append(dlg);
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  return close;
}
