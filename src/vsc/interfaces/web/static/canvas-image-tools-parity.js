/* C1 image-tool parity. Copy follows the reference canvas locale literally.
   Pixel tools stay on the local transform API; generation tools only serialize settings. */
const round4 = (value) => Math.round(Number(value) * 10000) / 10000;
const clamp = (value, low, high) => Math.max(low, Math.min(high, Number(value)));

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  node.addEventListener('click', (event) => event.stopPropagation());
  return node;
}

function button(label, action, cls) {
  const node = el('button', label, cls);
  node.type = 'button';
  node.addEventListener('click', async (event) => {
    event.stopPropagation();
    await action(event);
  });
  return node;
}

export const CROP_RATIO_PRESETS = [
  { id: 'free', label: '自由比例', ratio: null },
  { id: 'original', label: '原图比例', ratio: 'original' },
  { id: '1:1', label: '1:1', ratio: 1 },
  { id: '16:9', label: '16:9', ratio: 16 / 9 },
  { id: '9:16', label: '9:16', ratio: 9 / 16 },
  { id: '4:3', label: '4:3', ratio: 4 / 3 },
  { id: '3:4', label: '3:4', ratio: 3 / 4 },
  { id: '21:9', label: '21:9', ratio: 21 / 9 },
  { id: '5:2', label: '5:2', ratio: 5 / 2 },
  { id: '2:5', label: '2:5', ratio: 2 / 5 },
];

const CROP_HANDLE_LABELS = {
  nw: '左上调整', n: '顶部调整', ne: '右上调整', e: '右侧调整',
  se: '右下调整', s: '底部调整', sw: '左下调整', w: '左侧调整',
};

export function resizeCropRect(rect, handle, dx, dy, ratio, imageAspect) {
  const minSize = 0.05;
  const touchesW = handle === 'nw' || handle === 'w' || handle === 'sw';
  const touchesE = handle === 'ne' || handle === 'e' || handle === 'se';
  const touchesN = handle === 'nw' || handle === 'n' || handle === 'ne';
  const touchesS = handle === 'sw' || handle === 's' || handle === 'se';
  let left = rect.x;
  let top = rect.y;
  let right = rect.x + rect.w;
  let bottom = rect.y + rect.h;
  if (touchesW) left += dx;
  if (touchesE) right += dx;
  if (touchesN) top += dy;
  if (touchesS) bottom += dy;
  let width = right - left;
  let height = bottom - top;
  const lock = Number(ratio);
  const aspect = Number(imageAspect);
  const locked = Number.isFinite(lock) && lock > 0 && Number.isFinite(aspect) && aspect > 0;
  if (locked) {
    const target = lock / aspect;
    const horizontal = ((touchesW || touchesE) && !(touchesN || touchesS)) || (Math.abs(dx) >= Math.abs(dy) && (touchesW || touchesE));
    if (horizontal) height = width / target;
    else width = height * target;
  }
  if (width < minSize) width = minSize;
  if (height < minSize) height = minSize;
  if (locked) {
    const target = lock / aspect;
    if (width / height > target) width = height * target;
    else height = width / target;
    if (width < minSize) { width = minSize; height = width / target; }
    if (height < minSize) { height = minSize; width = height * target; }
  }
  if (touchesW && !touchesE) left = right - width;
  else if (touchesE && !touchesW) right = left + width;
  else { const center = rect.x + rect.w / 2; left = center - width / 2; right = center + width / 2; }
  if (touchesN && !touchesS) top = bottom - height;
  else if (touchesS && !touchesN) bottom = top + height;
  else { const center = rect.y + rect.h / 2; top = center - height / 2; bottom = center + height / 2; }
  if (left < 0) { right -= left; left = 0; }
  if (top < 0) { bottom -= top; top = 0; }
  if (right > 1) { left -= right - 1; right = 1; }
  if (bottom > 1) { top -= bottom - 1; bottom = 1; }
  left = Math.max(0, left);
  top = Math.max(0, top);
  right = Math.min(1, right);
  bottom = Math.min(1, bottom);
  if (right - left < minSize) right = Math.min(1, left + minSize);
  if (bottom - top < minSize) bottom = Math.min(1, top + minSize);
  return { x: round4(left), y: round4(top), w: round4(Math.max(minSize, right - left)), h: round4(Math.max(minSize, bottom - top)) };
}

export function fitCropRatio(rect, ratio, imageAspect) {
  if (ratio == null) return { x: round4(rect.x), y: round4(rect.y), w: round4(rect.w), h: round4(rect.h) };
  const aspect = Number(imageAspect) > 0 ? Number(imageAspect) : 1;
  const target = ratio === 'original' ? 1 : Number(ratio) / aspect;
  let width = rect.w;
  let height = width / target;
  if (height > 1) { height = 1; width = height * target; }
  if (width > 1) { width = 1; height = width / target; }
  let x = rect.x + (rect.w - width) / 2;
  let y = rect.y + (rect.h - height) / 2;
  x = clamp(x, 0, 1 - width);
  y = clamp(y, 0, 1 - height);
  return { x: round4(x), y: round4(y), w: round4(width), h: round4(height) };
}

export function openParityCropOverlay(host, { naturalWidth = 1024, naturalHeight = 1024, onSubmit, onClose } = {}) {
  const aspect = naturalWidth > 0 && naturalHeight > 0 ? naturalWidth / naturalHeight : 1;
  const state = { x: 0.1, y: 0.1, w: 0.8, h: 0.8, ratioId: 'free' };
  const overlay = el('div', null, 'cc-crop-overlay cc-itp-crop');
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-label', '图片裁剪框');
  const box = el('div', null, 'cc-crop-box');
  for (let index = 0; index < 4; index += 1) box.append(el('i', null, `cc-crop-third cc-crop-third-${index}`));
  const paint = () => {
    box.style.left = `${state.x * 100}%`;
    box.style.top = `${state.y * 100}%`;
    box.style.width = `${state.w * 100}%`;
    box.style.height = `${state.h * 100}%`;
  };
  for (const handle of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
    const knob = el('i', null, `cc-crop-handle cc-crop-handle-${handle}`);
    knob.setAttribute('aria-label', CROP_HANDLE_LABELS[handle]);
    knob.addEventListener('pointerdown', (event) => {
      if (event.button != null && event.button !== 0) return;
      event.preventDefault?.();
      event.stopPropagation();
      const frame = overlay.getBoundingClientRect();
      const start = { x: event.clientX, y: event.clientY, rect: { ...state } };
      const preset = CROP_RATIO_PRESETS.find((item) => item.id === state.ratioId);
      const ratio = !preset || preset.ratio == null ? null : preset.ratio === 'original' ? aspect : preset.ratio;
      const move = (ev) => {
        const dx = (ev.clientX - start.x) / Math.max(1, frame.width);
        const dy = (ev.clientY - start.y) / Math.max(1, frame.height);
        Object.assign(state, resizeCropRect(start.rect, handle, dx, dy, ratio, aspect));
        paint();
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    box.append(knob);
  }
  overlay.append(box);
  const bar = el('div', null, 'cc-crop-bar cc-itp-crop-bar');
  bar.append(el('span', '选择比例'));
  for (const preset of CROP_RATIO_PRESETS) {
    const choice = button(preset.label, () => {
      state.ratioId = preset.id;
      if (preset.ratio != null) Object.assign(state, fitCropRatio(state, preset.ratio, aspect));
      for (const node of bar.querySelectorAll('button')) node.classList.remove('is-active');
      choice.classList.add('is-active');
      paint();
    }, preset.id === 'free' ? 'is-active' : '');
    choice.setAttribute('data-itp-ratio', preset.id);
    bar.append(choice);
  }
  const confirm = button('确认', async () => {
    confirm.disabled = true;
    try {
      await onSubmit?.({ x: state.x, y: state.y, w: state.w, h: state.h, ratio: state.ratioId });
      cleanup();
    } finally {
      confirm.disabled = false;
    }
  }, 'cc-primary-btn');
  confirm.setAttribute('aria-label', '确认裁剪');
  const cancel = button('取消', () => { cleanup(); onClose?.(); });
  bar.append(confirm, cancel);
  host.append(overlay, bar);
  paint();
  const cleanup = () => { overlay.remove(); bar.remove(); };
  return cleanup;
}

export function rotateDegreesFromPointer(cx, cy, px, py) {
  const degrees = Math.atan2(py - cy, px - cx) * 180 / Math.PI;
  return Math.round(((degrees + 180) % 360 + 360) % 360 - 180);
}

export function rotateIsDirty(state = {}) {
  return Math.abs(Number(state.degrees) || 0) > 0.01 || Boolean(state.flipX) || Boolean(state.flipY);
}

export function openParityRotateOverlay(host, { image, onSubmit, onClose } = {}) {
  const state = { degrees: 0, flipX: false, flipY: false };
  const overlay = el('div', null, 'cc-itp-rotate');
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-label', '旋转与镜像');
  const frame = el('div', null, 'cc-itp-rotate-frame');
  const paint = () => {
    const transform = `rotate(${state.degrees}deg) scale(${state.flipX ? -1 : 1}, ${state.flipY ? -1 : 1})`;
    if (image) image.style.transform = transform;
    frame.style.transform = transform;
    readout.textContent = `${state.degrees}°`;
  };
  for (const [handle, label] of [['nw', '左上'], ['ne', '右上'], ['se', '右下'], ['sw', '左下']]) {
    const knob = el('i', null, `cc-itp-rotate-handle cc-itp-rotate-handle-${handle}`);
    knob.setAttribute('aria-label', `拖拽旋转${label}`);
    knob.addEventListener('pointerdown', (event) => {
      if (event.button != null && event.button !== 0) return;
      event.preventDefault?.();
      event.stopPropagation();
      const box = frame.getBoundingClientRect();
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      const startPointer = rotateDegreesFromPointer(cx, cy, event.clientX, event.clientY);
      const start = state.degrees;
      const move = (ev) => {
        let delta = rotateDegreesFromPointer(cx, cy, ev.clientX, ev.clientY) - startPointer;
        if (delta > 180) delta -= 360;
        if (delta < -180) delta += 360;
        state.degrees = Math.round(clamp(start + delta, -180, 180));
        paint();
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    frame.append(knob);
  }
  const bar = el('div', null, 'cc-rotate-bar cc-itp-rotate-bar');
  const readout = el('span', '0°', 'cc-itp-rotate-readout');
  readout.setAttribute('aria-label', '旋转角度');
  const turn = (delta) => { state.degrees = Math.round(clamp(state.degrees + delta, -180, 180)); paint(); };
  const ccw = button('−90°', () => turn(-90));
  ccw.setAttribute('aria-label', '逆时针旋转 90°');
  const cw = button('+90°', () => turn(90));
  cw.setAttribute('aria-label', '顺时针旋转 90°');
  cw.title = '顺时针旋转 90°';
  const flipH = button('水平镜像', () => { state.flipX = !state.flipX; paint(); });
  const flipV = button('垂直镜像', () => { state.flipY = !state.flipY; paint(); });
  const dialog = el('div', null, 'cc-itp-rotate-exit');
  dialog.hidden = true;
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-label', '退出旋转');
  dialog.append(el('h4', '退出旋转'), el('p', '您对图像做了旋转或镜像调整，退出前是否保存？'));
  const save = button('保存', async () => {
    await onSubmit?.({ degrees: state.degrees, flipX: state.flipX, flipY: state.flipY, flip_x: state.flipX, flip_y: state.flipY });
    cleanup();
  }, 'cc-primary-btn');
  const discard = button('不保存', () => { dialog.hidden = true; cleanup(); onClose?.(); });
  dialog.append(save, discard);
  const requestClose = () => {
    if (!rotateIsDirty(state)) { cleanup(); onClose?.(); return; }
    dialog.hidden = false;
  };
  const exit = button('退出', requestClose);
  exit.setAttribute('aria-label', '退出旋转与镜像');
  bar.append(ccw, cw, flipH, flipV, readout, exit, dialog);
  overlay.append(frame);
  host.append(overlay, bar);
  const previous = image ? image.style.transform : '';
  const cleanup = () => {
    if (image) image.style.transform = previous;
    overlay.remove();
    bar.remove();
  };
  return cleanup;
}

export const PARITY_FILTER_CATEGORIES = [
  ['all', '全部'], ['popular', '热门'], ['basic', '基础'], ['cinema', '电影'],
  ['film', '胶片'], ['japanese', '日系'], ['monochrome', '黑白'], ['mood', '氛围'],
];

export const PARITY_FILTERS = [
  { id: 'none', label: '原图', cat: ['all', 'basic'], hue: 0, sat: 0, bri: 0, con: 0 },
  { id: 'natural', label: '自然增强', cat: ['all', 'popular', 'basic'], hue: 0, sat: 8, bri: 2, con: 5 },
  { id: 'vivid', label: '鲜艳', cat: ['all', 'popular', 'basic'], hue: 0, sat: 28, bri: 3, con: 10 },
  { id: 'comic', label: '漫画鲜明', cat: ['all', 'popular'], hue: -4, sat: 22, bri: 5, con: 18 },
  { id: 'teal_orange', label: '青橙电影', cat: ['all', 'popular', 'cinema'], hue: -8, sat: 14, bri: -2, con: 16 },
  { id: 'moody', label: '电影暗调', cat: ['all', 'cinema', 'mood'], hue: -6, sat: -14, bri: -14, con: 20 },
  { id: 'black_gold', label: '黑金', cat: ['all', 'popular', 'cinema'], hue: 12, sat: -18, bri: -10, con: 24 },
  { id: 'cyber', label: '赛博朋克', cat: ['all', 'cinema', 'mood'], hue: -28, sat: 34, bri: 2, con: 22 },
  { id: 'warm_film', label: '暖调胶片', cat: ['all', 'popular', 'film'], hue: 10, sat: 10, bri: 4, con: 8 },
  { id: 'green_film', label: '青绿胶片', cat: ['all', 'film'], hue: -14, sat: -6, bri: 2, con: 10 },
  { id: 'faded', label: '复古褪色', cat: ['all', 'film'], hue: 8, sat: -22, bri: 6, con: -10 },
  { id: 'instant', label: '拍立得', cat: ['all', 'film'], hue: 6, sat: -8, bri: 8, con: 6 },
  { id: 'jp_fresh', label: '日系清新', cat: ['all', 'popular', 'japanese'], hue: -4, sat: -10, bri: 12, con: -6 },
  { id: 'cream', label: '奶油暖阳', cat: ['all', 'japanese', 'film'], hue: 10, sat: -6, bri: 10, con: -4 },
  { id: 'cool_white', label: '冷白透亮', cat: ['all', 'japanese', 'basic'], hue: -10, sat: -8, bri: 12, con: 6 },
  { id: 'bw', label: '经典黑白', cat: ['all', 'monochrome'], hue: 0, sat: -100, bri: 0, con: 12 },
  { id: 'bw_hard', label: '高反差黑白', cat: ['all', 'monochrome'], hue: 0, sat: -100, bri: -4, con: 38 },
  { id: 'sepia', label: '棕褐怀旧', cat: ['all', 'monochrome', 'film'], hue: 24, sat: -45, bri: 2, con: 10 },
  { id: 'night', label: '夜景蓝调', cat: ['all', 'mood', 'cinema'], hue: -22, sat: 12, bri: -8, con: 14 },
  { id: 'forest', label: '森系', cat: ['all', 'mood'], hue: -12, sat: 10, bri: -2, con: 8 },
  { id: 'autumn', label: '秋日暖橙', cat: ['all', 'mood', 'popular'], hue: 16, sat: 18, bri: 4, con: 10 },
];

function filterPreset(filterId) {
  const id = filterId === 'original' ? 'none' : filterId;
  return PARITY_FILTERS.find((item) => item.id === id) || PARITY_FILTERS[0];
}

export function computeParityColorCss(state = {}) {
  const preset = filterPreset(state.filterId);
  const ratio = clamp(state.strength ?? 100, 0, 100) / 100;
  const hue = Math.round(preset.hue * ratio + Number(state.hue || 0));
  const saturation = Math.max(0, 100 + Math.round(preset.sat * ratio + Number(state.saturation || 0)));
  const brightness = Math.max(10, 100 + Math.round(preset.bri * ratio + Number(state.brightness || 0)));
  const contrast = Math.max(10, 100 + Math.round(preset.con * ratio + Number(state.contrast || 0)));
  if (hue === 0 && saturation === 100 && brightness === 100 && contrast === 100) return 'none';
  return `hue-rotate(${hue}deg) saturate(${saturation}%) brightness(${brightness}%) contrast(${contrast}%)`;
}

export function isParityColorIdentity(state = {}) {
  const filterId = state.filterId || 'none';
  return (filterId === 'none' || filterId === 'original')
    && Number(state.hue || 0) === 0
    && Number(state.saturation || 0) === 0
    && Number(state.brightness || 0) === 0
    && Number(state.contrast || 0) === 0;
}

export function openParityColorAdjust(host, { image, onSubmit, onClose } = {}) {
  const state = { filterId: 'none', category: 'all', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0 };
  const previous = image ? image.style.filter : '';
  const panel = el('div', null, 'cc-floating-editor cc-color-adjust-panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '调色');
  panel.append(el('h4', '调色'));
  const categories = el('div', null, 'cc-filter-cat-bar');
  const strip = el('div', null, 'cc-filter-strip');
  let confirm = null;
  const preview = (original = false) => {
    if (image) image.style.filter = original ? 'none' : computeParityColorCss(state);
    if (confirm) confirm.disabled = isParityColorIdentity(state);
  };
  const renderFilters = () => {
    strip.replaceChildren();
    for (const filter of PARITY_FILTERS.filter((item) => item.cat.includes(state.category))) {
      const chip = button(filter.label, () => {
        state.filterId = filter.id;
        renderFilters();
        preview(false);
      }, state.filterId === filter.id ? 'cc-filter-chip is-active' : 'cc-filter-chip');
      strip.append(chip);
    }
  };
  for (const [id, label] of PARITY_FILTER_CATEGORIES) {
    const tab = button(label, () => {
      state.category = id;
      for (const node of categories.querySelectorAll('button')) node.classList.remove('is-active');
      tab.classList.add('is-active');
      renderFilters();
    }, id === 'all' ? 'is-active' : '');
    tab.setAttribute('data-itp-filter-cat', id);
    categories.append(tab);
  }
  renderFilters();
  const controls = el('div', null, 'cc-color-sliders');
  const sliders = {};
  const addSlider = (label, key, min, max) => {
    const row = el('label', label);
    const input = el('input');
    input.type = 'range';
    input.min = String(min);
    input.max = String(max);
    input.value = String(state[key]);
    input.setAttribute('aria-label', key === 'strength' ? '滤镜强度' : label);
    const value = el('span', String(state[key]), 'cc-range-val');
    input.addEventListener('input', () => {
      state[key] = Number(input.value);
      value.textContent = input.value;
      preview(false);
    });
    row.append(input, value);
    controls.append(row);
    sliders[key] = [input, value];
  };
  addSlider('强度', 'strength', 0, 100);
  addSlider('色相', 'hue', -180, 180);
  addSlider('饱和度', 'saturation', -100, 100);
  addSlider('明度', 'brightness', -100, 100);
  addSlider('对比度', 'contrast', -100, 100);
  const foot = el('div', null, 'cc-editor-actions');
  const reset = button('重置', () => {
    Object.assign(state, { filterId: 'none', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0 });
    for (const [key, [input, value]] of Object.entries(sliders)) {
      input.value = String(state[key]);
      value.textContent = String(state[key]);
    }
    renderFilters();
    preview(false);
  });
  reset.setAttribute('aria-label', '重置参数');
  const compare = button('按住看原图', () => {});
  compare.addEventListener('pointerdown', () => preview(true));
  compare.addEventListener('pointerup', () => preview(false));
  compare.addEventListener('pointerleave', () => preview(false));
  const close = button('关闭', () => { cleanup(); onClose?.(); });
  confirm = button('确认', async () => {
    confirm.disabled = true;
    try {
      await onSubmit?.({
        filterId: state.filterId,
        strength: state.strength,
        hue: state.hue,
        saturation: state.saturation,
        brightness: state.brightness,
        contrast: state.contrast,
      });
      cleanup();
    } catch (error) {
      confirm.disabled = isParityColorIdentity(state);
      throw error;
    }
  }, 'cc-primary-btn');
  confirm.setAttribute('aria-label', '确认调色');
  confirm.disabled = true;
  foot.append(reset, compare, close, confirm);
  panel.append(categories, strip, el('h5', '参数'), controls, foot);
  host.append(panel);
  const cleanup = () => {
    if (image) image.style.filter = previous;
    panel.remove();
  };
  return cleanup;
}

export function gridSelectAll(rows, columns) {
  const cells = [];
  for (let row = 1; row <= rows; row += 1) {
    for (let column = 1; column <= columns; column += 1) cells.push({ row, column });
  }
  return cells;
}

export function gridInvert(rows, columns, cells = []) {
  const selected = new Set(cells.map((cell) => `${cell.row}:${cell.column}`));
  const next = [];
  for (let row = 1; row <= rows; row += 1) {
    for (let column = 1; column <= columns; column += 1) {
      if (!selected.has(`${row}:${column}`)) next.push({ row, column });
    }
  }
  return next;
}

export function selectGridRange(anchor, focus, existing = [], additive = false) {
  const cells = [];
  for (let row = Math.min(anchor.row, focus.row); row <= Math.max(anchor.row, focus.row); row += 1) {
    for (let column = Math.min(anchor.column, focus.column); column <= Math.max(anchor.column, focus.column); column += 1) {
      cells.push({ row, column });
    }
  }
  if (!additive) return cells;
  const merged = existing.map((cell) => ({ row: cell.row, column: cell.column }));
  for (const cell of cells) {
    if (!merged.some((item) => item.row === cell.row && item.column === cell.column)) merged.push(cell);
  }
  return merged;
}

export function mountGridParityActions(tools, grid) {
  const all = button('全选', () => {
    grid.cells = gridSelectAll(grid.rows, grid.columns);
    grid.refresh?.();
  });
  const invert = button('反选', () => {
    grid.cells = gridInvert(grid.rows, grid.columns, grid.cells || []);
    grid.refresh?.();
  });
  tools.append(all, invert);
}

const DOODLE_COLORS = ['#ff3b30', '#ffcc00', '#34c759', '#0a84ff', '#ffffff', '#000000'];

export function normalizeDoodleStroke(stroke) {
  if (!stroke || typeof stroke !== 'object') return null;
  const tool = ['brush', 'arrow', 'rect', 'text', 'eraser'].includes(stroke.tool) ? stroke.tool : 'brush';
  const color = /^#[0-9a-fA-F]{6}$/.test(stroke.color || '') ? stroke.color : '#ff3b30';
  let width = Number(stroke.width ?? 6);
  if (!Number.isFinite(width)) width = 6;
  width = Math.max(1, Math.min(64, Math.round(width)));
  const points = [];
  for (const point of stroke.points || []) {
    if (!Array.isArray(point) || point.length < 2) continue;
    const x = Number(point[0]);
    const y = Number(point[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    points.push([clamp(x, 0, 1), clamp(y, 0, 1)]);
    if (points.length >= 2000) break;
  }
  if (!points.length) return null;
  if ((tool === 'arrow' || tool === 'rect') && points.length < 2) return null;
  const normalized = { tool, color, width, points };
  if (tool === 'text') {
    const text = String(stroke.text || '').slice(0, 80);
    if (!text) return null;
    normalized.text = text;
  }
  return normalized;
}

export function createDoodleHistory() {
  const past = [[]];
  const future = [];
  const copy = (strokes) => strokes.map((stroke) => ({ ...stroke, points: stroke.points.map((point) => [...point]) }));
  return {
    push(strokes) { past.push(copy(strokes)); future.length = 0; },
    undo() { if (past.length > 1) future.push(past.pop()); return this.strokes(); },
    redo() { if (future.length) past.push(future.pop()); return this.strokes(); },
    strokes() { return copy(past[past.length - 1]); },
    canUndo() { return past.length > 1; },
    canRedo() { return future.length > 0; },
  };
}

export function openParityDoodleOverlay(host, { onSubmit, onClose } = {}) {
  const history = createDoodleHistory();
  const draft = { tool: 'brush', color: '#ff3b30', width: 6, points: [] };
  const canvas = el('canvas', null, 'cc-doodle-canvas cc-itp-doodle-canvas');
  canvas.width = 480;
  canvas.height = 320;
  const ctx = canvas.getContext?.('2d');
  const redraw = () => {
    if (!ctx) return;
    ctx.clearRect?.(0, 0, canvas.width, canvas.height);
    for (const stroke of history.strokes()) {
      ctx.strokeStyle = stroke.color;
      ctx.fillStyle = stroke.color;
      ctx.lineWidth = stroke.width;
      const points = stroke.points.map((point) => [point[0] * canvas.width, point[1] * canvas.height]);
      if (stroke.tool === 'rect' && points.length >= 2) {
        const xs = points.map((point) => point[0]);
        const ys = points.map((point) => point[1]);
        ctx.strokeRect?.(Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
      } else if (stroke.tool === 'text') {
        ctx.fillText?.(stroke.text, points[0][0], points[0][1]);
      } else if (points.length) {
        ctx.beginPath?.();
        ctx.moveTo?.(points[0][0], points[0][1]);
        for (const point of points.slice(1)) ctx.lineTo?.(point[0], point[1]);
        ctx.stroke?.();
      }
    }
  };
  const pointOf = (event) => {
    const box = canvas.getBoundingClientRect();
    return [clamp((event.clientX - box.left) / Math.max(1, box.width), 0, 1), clamp((event.clientY - box.top) / Math.max(1, box.height), 0, 1)];
  };
  canvas.addEventListener('pointerdown', (event) => {
    if (event.button != null && event.button !== 0) return;
    draft.points = [pointOf(event)];
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!draft.points.length) return;
    draft.points.push(pointOf(event));
  });
  canvas.addEventListener('pointerup', () => {
    const text = textInput.value.trim();
    const stroke = normalizeDoodleStroke({
      tool: draft.tool,
      color: draft.color,
      width: Number(widthInput.value),
      points: draft.points,
      text,
    });
    draft.points = [];
    if (!stroke) return;
    history.push([...history.strokes(), stroke]);
    redraw();
  });
  const bar = el('div', null, 'cc-doodle-bar cc-itp-doodle-bar');
  bar.setAttribute('aria-label', '涂鸦');
  const tools = [['brush', '画笔'], ['arrow', '箭头'], ['rect', '框选'], ['text', '文本'], ['eraser', '橡皮擦']];
  for (const [tool, label] of tools) {
    const node = button(label, () => {
      draft.tool = tool;
      for (const item of bar.querySelectorAll('[data-itp-doodle-tool]')) item.classList.remove('is-active');
      node.classList.add('is-active');
      textInput.hidden = tool !== 'text';
    }, tool === 'brush' ? 'is-active' : '');
    node.setAttribute('data-itp-doodle-tool', tool);
    bar.append(node);
  }
  for (const color of DOODLE_COLORS) {
    const swatch = button('', () => { draft.color = color; }, 'cc-swatch');
    swatch.style.background = color;
    swatch.setAttribute('aria-label', `颜色 ${color}`);
    bar.append(swatch);
  }
  const widthInput = el('input');
  widthInput.type = 'range';
  widthInput.min = '1';
  widthInput.max = '64';
  widthInput.value = '6';
  widthInput.setAttribute('aria-label', '涂鸦笔宽');
  const textInput = el('input');
  textInput.type = 'text';
  textInput.hidden = true;
  textInput.maxLength = 80;
  textInput.placeholder = '输入文字后在画面上点按';
  textInput.setAttribute('aria-label', '文本');
  const undo = button('撤销', () => { history.undo(); redraw(); });
  const redo = button('重做', () => { history.redo(); redraw(); });
  const save = button('保存涂鸦', async () => {
    const strokes = history.strokes().map(normalizeDoodleStroke).filter(Boolean);
    if (!strokes.length) throw new Error('涂鸦至少需要一笔有效笔触');
    await onSubmit?.({ strokes });
    cleanup();
  }, 'cc-primary-btn');
  const close = button('关闭', () => { cleanup(); onClose?.(); });
  close.setAttribute('aria-label', '关闭涂鸦编辑器');
  bar.append(widthInput, textInput, undo, redo, save, close);
  host.append(canvas, bar);
  const cleanup = () => { canvas.remove(); bar.remove(); };
  return cleanup;
}

export function inpaintExportPayload({ prompt, strokes } = {}) {
  const text = String(prompt || '').trim();
  if (!text) throw new Error('请输入局部重绘提示词');
  const normalized = (strokes || []).map(normalizeDoodleStroke).filter(Boolean);
  if (!normalized.length) throw new Error('请先涂抹需要重绘的区域');
  return { prompt: text.slice(0, 200), strokes: normalized };
}

export function outpaintFrameForRatio(imageAspect, ratioKey) {
  const table = { '1:1': 1, '16:9': 16 / 9, '9:16': 9 / 16, '4:3': 4 / 3, '3:4': 3 / 4, '21:9': 21 / 9, '5:2': 5 / 2, '2:5': 2 / 5 };
  const aspect = Number(imageAspect) > 0 ? Number(imageAspect) : 1;
  const ratio = table[ratioKey];
  if (!ratio) return { x: -0.1, y: -0.1, w: 1.2, h: 1.2, ratio: ratioKey || 'free' };
  const norm = ratio / aspect;
  let width = norm >= 1 ? norm : 1;
  let height = norm >= 1 ? 1 : 1 / norm;
  if (width <= 1.001 && height <= 1.001) {
    width *= 1.25;
    height = width / norm;
  }
  return { x: round4((1 - width) / 2), y: round4((1 - height) / 2), w: round4(width), h: round4(height), ratio: ratioKey };
}

export function resizeOutpaintRect(rect, handle, dx, dy) {
  const minSize = 0.05;
  const touchesW = handle === 'nw' || handle === 'w' || handle === 'sw';
  const touchesE = handle === 'ne' || handle === 'e' || handle === 'se';
  const touchesN = handle === 'nw' || handle === 'n' || handle === 'ne';
  const touchesS = handle === 'sw' || handle === 's' || handle === 'se';
  let left = rect.x + (touchesW ? dx : 0);
  let right = rect.x + rect.w + (touchesE ? dx : 0);
  let top = rect.y + (touchesN ? dy : 0);
  let bottom = rect.y + rect.h + (touchesS ? dy : 0);
  let width = Math.max(minSize, right - left);
  let height = Math.max(minSize, bottom - top);
  width = Math.min(8, width);
  height = Math.min(8, height);
  if (touchesW && !touchesE) left = right - width;
  else if (touchesE) left = rect.x;
  if (touchesN && !touchesS) top = bottom - height;
  else if (touchesS) top = rect.y;
  return { x: round4(clamp(left, -4, 4)), y: round4(clamp(top, -4, 4)), w: round4(width), h: round4(height) };
}

export function outpaintNodeSettings(frame, sourceWidth = 0, sourceHeight = 0) {
  const x = clamp(frame.x, -4, 4);
  const y = clamp(frame.y, -4, 4);
  const w = clamp(frame.w, 0.05, 8);
  const h = clamp(frame.h, 0.05, 8);
  const overhang = Math.max(0, -x, -y, x + w - 1, y + h - 1);
  const padding = Math.min(2, Math.max(0.05, overhang || 0.05));
  const width = Number(sourceWidth) > 0 ? Math.round(Number(sourceWidth)) : 0;
  const height = Number(sourceHeight) > 0 ? Math.round(Number(sourceHeight)) : 0;
  return {
    ratio: String(frame.ratio || 'free').slice(0, 20),
    padding: round4(padding),
    source_width: width,
    source_height: height,
    rect_x: round4(x),
    rect_y: round4(y),
    rect_w: round4(w),
    rect_h: round4(h),
  };
}

function pointerPainter(surface, onStroke) {
  let points = [];
  const pointOf = (event) => {
    const box = surface.getBoundingClientRect();
    return [clamp((event.clientX - box.left) / Math.max(1, box.width), 0, 1), clamp((event.clientY - box.top) / Math.max(1, box.height), 0, 1)];
  };
  surface.addEventListener('pointerdown', (event) => {
    if (event.button != null && event.button !== 0) return;
    points = [pointOf(event)];
  });
  surface.addEventListener('pointermove', (event) => { if (points.length) points.push(pointOf(event)); });
  surface.addEventListener('pointerup', () => {
    const stroke = points.slice();
    points = [];
    if (stroke.length) onStroke(stroke);
  });
}

export function mountParityRegionTool(host, editor, ctx) {
  if (editor.tool === 'inpaint') {
    const panel = el('div', null, 'cc-itp-repaint');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', '局部重绘');
    panel.append(el('h4', '局部重绘'));
    const canvas = el('canvas', null, 'cc-itp-mask-canvas');
    canvas.width = 480;
    canvas.height = 320;
    const strokes = [];
    let mode = 'brush';
    pointerPainter(canvas, (points) => {
      const stroke = normalizeDoodleStroke({ tool: mode === 'eraser' ? 'eraser' : 'brush', color: '#ffffff', width: 24, points });
      if (stroke) strokes.push(stroke);
    });
    const prompt = el('textarea');
    prompt.placeholder = '请输入局部重绘提示词';
    prompt.setAttribute('aria-label', '提示词');
    const brushBtn = button('画笔', () => { mode = 'brush'; });
    const eraserBtn = button('橡皮擦', () => { mode = 'eraser'; });
    const save = button('保存', async () => {
      const payload = inpaintExportPayload({ prompt: prompt.value, strokes });
      const result = await ctx.transformImage?.('mask', { strokes: payload.strokes });
      const mediaId = result?.media_ids?.[0];
      if (!mediaId) return;
      editor.settings = { ...editor.settings, mask_media_id: mediaId, prompt: payload.prompt };
      editor.promptEnabled = true;
      editor.prompt = payload.prompt;
      await ctx.onSubmit?.();
    }, 'cc-primary-btn');
    const close = button('关闭', () => ctx.onClose?.());
    close.setAttribute('aria-label', '关闭局部重绘编辑器');
    panel.append(canvas, brushBtn, eraserBtn, prompt, save, close);
    host.append(panel);
    return () => panel.remove();
  }
  const aspect = (ctx.naturalWidth || 1024) / (ctx.naturalHeight || 1024);
  const state = outpaintFrameForRatio(aspect, editor.settings?.ratio || '16:9');
  const panel = el('div', null, 'cc-itp-outpaint');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '扩图');
  panel.append(el('h4', '扩图'));
  const frame = el('div', null, 'cc-itp-outpaint-frame');
  const paint = () => {
    frame.style.left = `${state.x * 100}%`;
    frame.style.top = `${state.y * 100}%`;
    frame.style.width = `${state.w * 100}%`;
    frame.style.height = `${state.h * 100}%`;
  };
  for (const handle of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
    const knob = el('i', null, `cc-itp-outpaint-handle cc-itp-outpaint-handle-${handle}`);
    knob.setAttribute('aria-label', CROP_HANDLE_LABELS[handle]);
    knob.addEventListener('pointerdown', (event) => {
      const box = panel.getBoundingClientRect();
      const start = { x: event.clientX, y: event.clientY, rect: { ...state } };
      const move = (ev) => {
        const dx = (ev.clientX - start.x) / Math.max(1, box.width);
        const dy = (ev.clientY - start.y) / Math.max(1, box.height);
        Object.assign(state, resizeOutpaintRect(start.rect, handle, dx, dy), { ratio: 'free' });
        paint();
      };
      const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    frame.append(knob);
  }
  const ratios = el('div', null, 'cc-itp-outpaint-ratios');
  for (const [id, label] of [['free', '自由比例'], ['1:1', '1:1'], ['16:9', '16:9'], ['9:16', '9:16'], ['4:3', '4:3'], ['3:4', '3:4'], ['21:9', '21:9']]) {
    ratios.append(button(label, () => { Object.assign(state, outpaintFrameForRatio(aspect, id)); paint(); }));
  }
  const confirm = button('确认', async () => {
    Object.assign(editor.settings, outpaintNodeSettings(state, ctx.naturalWidth, ctx.naturalHeight));
    editor.promptEnabled = false;
    await ctx.onSubmit?.();
  }, 'cc-primary-btn');
  panel.append(frame, ratios, confirm, button('关闭', () => ctx.onClose?.()));
  host.append(panel);
  paint();
  return () => panel.remove();
}

const SNAP_X = { left: -1, center: 0, right: 1 };
const SNAP_Y = { bottom: -1, middle: 0, top: 1 };
const SNAP_Z = { back: -1, center: 0, front: 1 };
const SNAP_LABELS = {
  center_bottom_center: '下', center_bottom_front: '前下', center_middle_front: '前',
  center_top_center: '上', center_top_front: '前上', left_bottom_center: '左下',
  left_bottom_front: '前左下', left_middle_center: '左', left_middle_front: '前左',
  left_top_center: '左上', left_top_front: '前左上', right_bottom_center: '右下',
  right_bottom_front: '前右下', right_middle_center: '右', right_middle_front: '前右',
  right_top_center: '右上', right_top_front: '前右上',
};

function snapFallback(horizontal, vertical, depth) {
  const front = depth === 'front' ? '前' : depth === 'back' ? '后' : '';
  const side = horizontal === 'left' ? '左' : horizontal === 'right' ? '右' : '';
  const rise = vertical === 'top' ? '上' : vertical === 'bottom' ? '下' : '';
  return `${front}${side}${rise}` || '中';
}

export const LIGHTING_SNAPS = [];
for (const horizontal of ['left', 'center', 'right']) {
  for (const vertical of ['bottom', 'middle', 'top']) {
    for (const depth of ['back', 'center', 'front']) {
      const id = `${horizontal}_${vertical}_${depth}`;
      LIGHTING_SNAPS.push({
        id,
        label: SNAP_LABELS[id] || snapFallback(horizontal, vertical, depth),
        x: SNAP_X[horizontal],
        y: SNAP_Y[vertical],
        z: SNAP_Z[depth],
      });
    }
  }
}

export function serializeLighting(settings = {}) {
  const snap = LIGHTING_SNAPS.find((item) => item.id === settings.direction);
  const direction = snap
    ? { x: snap.x, y: snap.y, z: snap.z }
    : {
      x: Number(settings.direction_x || 0),
      y: Number(settings.direction_y || 0),
      z: Number(settings.direction_z ?? 1),
    };
  const payload = {
    brightness: Number(settings.brightness ?? settings.intensity ?? 1),
    color: settings.color || '#ffffff',
    description: settings.description || '',
    direction,
  };
  if (settings.rim) payload.rimLightDirection = { x: 0, y: 0, z: -1 };
  return payload;
}

export const MULTI_ANGLE_PRESETS = [
  { id: 'custom', label: '自定义' },
  { id: 'fisheye', label: '鱼眼视角', yaw: 0, pitch: 0, roll: 0, zoom: 0.5, scale: 'wide' },
  { id: 'tilt', label: '倾斜视角', yaw: 0, pitch: 0, roll: 20, zoom: 1, scale: 'medium' },
  { id: 'frontBottom', label: '正面仰拍', yaw: 0, pitch: -30, roll: 0, zoom: 1, scale: 'medium' },
  { id: 'frontTop', label: '正面俯拍', yaw: 0, pitch: 30, roll: 0, zoom: 1, scale: 'medium' },
  { id: 'wideTop', label: '全景俯拍', yaw: 0, pitch: 60, roll: 0, zoom: 0.5, scale: 'wide' },
  { id: 'back', label: '背面视角', yaw: 180, pitch: 0, roll: 0, zoom: 1, scale: 'medium' },
];

export const SHOT_SCALES = [
  { id: 'close', label: '特写', zoom: 2 },
  { id: 'medium', label: '中景', zoom: 1 },
  { id: 'wide', label: '全景', zoom: 0.5 },
];

export function serializeMultiAngle(settings = {}) {
  const zoom = Number(settings.zoom ?? 1);
  const scale = settings.scale || (zoom <= 0.6 ? 'wide' : zoom >= 1.5 ? 'close' : 'medium');
  return {
    preset: settings.preset || 'custom',
    yaw: Number(settings.yaw || 0),
    pitch: Number(settings.pitch || 0),
    scale,
    description: settings.description || '',
  };
}

const TOOL_EXTRAS = {
  angle: { scale: 'medium', description: '' },
  lighting: { brightness: 1, direction_x: 0, direction_y: 0, direction_z: 1, description: '' },
  texture: { prompt: '', quality: 'medium' },
  expression: { emotion: '', emotion_x: 50, emotion_y: 50, quality: 'standard', face_rect: '' },
  inpaint: { prompt: '' },
  outpaint: { source_width: 0, source_height: 0, rect_x: 0, rect_y: 0, rect_w: 1, rect_h: 1 },
};

export function primeImageToolSettings(editor) {
  const extra = TOOL_EXTRAS[editor?.tool] || {};
  const incoming = editor.settings || {};
  const hadBrightness = Object.prototype.hasOwnProperty.call(incoming, 'brightness');
  editor.settings = { ...extra, ...incoming };
  editor.defaults = { ...extra, ...(editor.defaults || {}) };
  if (editor.tool === 'lighting' && !hadBrightness) editor.settings.brightness = incoming.intensity ?? editor.settings.intensity ?? extra.brightness;
  return editor;
}

export function mountParityToolExtras(host, editor) {
  const box = el('div', null, `cc-itp-extras cc-itp-extras--${editor.tool}`);
  if (editor.tool === 'lighting') {
    box.append(el('h4', '主光源'));
    const grid = el('div', null, 'cc-itp-light-grid');
    for (const snap of LIGHTING_SNAPS) {
      const node = button(snap.label, () => {
        Object.assign(editor.settings, { direction: snap.id, direction_x: snap.x, direction_y: snap.y, direction_z: snap.z });
      });
      node.title = snap.label;
      node.setAttribute('data-itp-light', snap.id);
      grid.append(node);
    }
    const brightness = el('input');
    brightness.type = 'range';
    brightness.min = '0';
    brightness.max = '5';
    brightness.step = '0.1';
    brightness.value = String(editor.settings.brightness ?? editor.settings.intensity ?? 1);
    brightness.setAttribute('aria-label', '亮度');
    brightness.addEventListener('input', () => {
      const value = Number(brightness.value);
      editor.settings.brightness = value;
      editor.settings.intensity = value;
    });
    const description = el('input');
    description.placeholder = '补充打光说明';
    description.setAttribute('aria-label', '说明');
    description.addEventListener('input', () => { editor.settings.description = description.value.slice(0, 200); });
    box.append(grid, el('label', '亮度'), brightness, description);
  } else if (editor.tool === 'angle') {
    box.append(el('h4', '多角度编辑器'), el('p', '水平环绕'), el('p', '垂直俯仰'), el('p', '景别缩放'));
    const presets = el('div', null, 'cc-itp-angle-presets');
    for (const preset of MULTI_ANGLE_PRESETS) {
      presets.append(button(preset.label, () => {
        Object.assign(editor.settings, {
          preset: preset.id,
          yaw: preset.yaw ?? editor.settings.yaw,
          pitch: preset.pitch ?? editor.settings.pitch,
          roll: preset.roll ?? editor.settings.roll,
          zoom: preset.zoom ?? editor.settings.zoom,
          scale: preset.scale || editor.settings.scale || 'medium',
        });
      }));
    }
    const scales = el('div', null, 'cc-itp-shot-scales');
    for (const scale of SHOT_SCALES) {
      scales.append(button(scale.label, () => {
        editor.settings.scale = scale.id;
        editor.settings.zoom = scale.zoom;
      }));
    }
    const description = el('textarea');
    description.placeholder = '补充需要保留或调整的画面描述';
    description.setAttribute('aria-label', '补充需要保留或调整的画面描述');
    description.addEventListener('input', () => {
      editor.settings.description = description.value.slice(0, 200);
      editor.prompt = editor.settings.description;
      editor.promptEnabled = Boolean(editor.settings.description);
    });
    box.append(presets, scales, description);
  }
  if (box.children.length) host.append(box);
  return () => box.remove();
}

export function mountNodeImageEditor(host, editor, ctx) {
  if (editor.tool === 'inpaint' || editor.tool === 'outpaint') return mountParityRegionTool(host, editor, ctx);
  primeImageToolSettings(editor);
  ctx.mountImageControls(host, {
    tool: editor.tool,
    settings: editor.settings,
    defaults: editor.defaults,
    imageUrl: ctx.imageUrl,
    canvas: true,
    promptState: editor,
    onChange: () => {},
    isCurrent: ctx.isCurrent,
    onClose: ctx.onClose,
    onSubmit: ctx.onSubmit,
    onError: ctx.onError,
  });
  return mountParityToolExtras(host, editor);
}

export const PORTRAIT_TEXTURE_DIMENSIONS = [
  { key: 'scene_blend', label: '人景融合', options: [['light', '轻度对齐'], ['natural', '自然融合'], ['deep', '深度融合']] },
  { key: 'light_match', label: '光影融合', options: [['soft', '柔和补光'], ['natural', '自然匹配'], ['dramatic', '氛围强化']] },
  { key: 'skin_polish', label: '皮肤', options: [['clean', '清透修饰'], ['natural', '自然肤质'], ['micro', '真实肌理']] },
  { key: 'grain', label: '纹理', options: [['soft', '柔和纹理'], ['natural', '自然纹理'], ['film_grain', '颗粒质感']] },
  { key: 'sharpness', label: '锐度', options: [['soft_focus', '柔焦'], ['standard', '标准清晰'], ['hd_sharp', '高清锐化']] },
];

const STRONG_TEXTURE = new Set(['deep', 'dramatic', 'micro', 'film_grain', 'hd_sharp']);

export function openParityPortraitTexture(host, initial = {}, { onApply, onClose } = {}) {
  const state = {
    strength: 0.5,
    scene_blend: 'natural',
    light_match: 'natural',
    skin_polish: 'natural',
    grain: 'natural',
    sharpness: 'standard',
    prompt: '',
    quality: 'medium',
    ...initial,
  };
  const panel = el('div', null, 'cc-floating-editor cc-portrait-texture-popover cc-itp-texture');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '人像质感调节');
  panel.append(el('h4', '人像质感调节'));
  const warning = el('p', '高强度调节可能影响人物一致性', 'cc-itp-texture-warning');
  const syncWarning = () => { warning.hidden = !PORTRAIT_TEXTURE_DIMENSIONS.some((group) => STRONG_TEXTURE.has(state[group.key])); };
  for (const group of PORTRAIT_TEXTURE_DIMENSIONS) {
    const row = el('div', null, 'cc-texture-row');
    row.append(el('span', group.label));
    const seg = el('div', null, 'cc-texture-seg');
    for (const [value, label] of group.options) {
      const node = button(label, () => {
        state[group.key] = value;
        for (const sibling of seg.querySelectorAll('button')) sibling.classList.remove('is-active');
        node.classList.add('is-active');
        syncWarning();
      }, state[group.key] === value ? 'is-active' : '');
      seg.append(node);
    }
    row.append(seg);
    panel.append(row);
  }
  const qualities = el('div', null, 'cc-itp-quality');
  qualities.append(el('span', '画质'));
  for (const [value, label] of [['standard', '低画质'], ['medium', '标准画质'], ['high', '高画质']]) {
    qualities.append(button(label, () => { state.quality = value; }, state.quality === value ? 'is-active' : ''));
  }
  const prompt = el('textarea');
  prompt.placeholder = '上传图片或输入描述，选择质感强度，让人物更自然、更真实';
  prompt.setAttribute('aria-label', '提示词');
  prompt.value = state.prompt;
  prompt.addEventListener('input', () => { state.prompt = prompt.value.slice(0, 200); });
  syncWarning();
  const apply = button('应用参数', async () => { await onApply?.({ ...state }); panel.remove(); }, 'cc-primary-btn');
  panel.append(warning, qualities, prompt, apply, button('关闭', () => { panel.remove(); onClose?.(); }));
  host.append(panel);
  return () => panel.remove();
}

const EMOTION_LABELS = {
  e01_01: '欣然愉悦', e01_02: '骤然错愕', e01_03: '惊魂未定', e01_04: '心跳骤停', e01_05: '暴怒沉怒',
  e02_01: '浅然莞尔', e02_02: '难以置信', e02_03: '受惊后退', e02_04: '强忍悲戚', e02_05: '隐忍愠怒',
  e03_01: '含情凝望', e03_02: '欲言又止', e03_03: '淡然自若', e03_04: '警觉审视', e03_05: '眉宇凝霜',
  e04_01: '满眼宠溺', e04_02: '万般无奈', e04_03: '触景伤情', e04_04: '隐忍心伤', e04_05: '冷眼漠然',
  e05_01: '积郁憋闷', e05_02: '默然垂泪', e05_03: '疲惫失神', e05_04: '哀悼压抑', e05_05: '疏离冷淡',
};
const EMOTION_X = [10, 30, 50, 70, 90];
const EMOTION_Y = [90, 70, 50, 30, 10];
export const PORTRAIT_EMOTIONS = [];
for (let row = 1; row <= 5; row += 1) {
  for (let column = 1; column <= 5; column += 1) {
    const id = `e0${row}_0${column}`;
    PORTRAIT_EMOTIONS.push({ id, label: EMOTION_LABELS[id], x: EMOTION_X[column - 1], y: EMOTION_Y[row - 1] });
  }
}

function nearestEmotion(x, y) {
  return PORTRAIT_EMOTIONS.slice().sort((a, b) => Math.abs(a.x - x) + Math.abs(a.y - y) - (Math.abs(b.x - x) + Math.abs(b.y - y)))[0];
}

export function serializePortraitEmotion(state = {}) {
  const valence = Number(state.valence || 0);
  const arousal = Number(state.arousal || 0);
  const emotionX = clamp(state.emotion_x ?? 50 + valence * 40, 0, 100);
  const emotionY = clamp(state.emotion_y ?? 50 + arousal * 40, 0, 100);
  const preset = state.emotion ? PORTRAIT_EMOTIONS.find((item) => item.id === state.emotion) : nearestEmotion(emotionX, emotionY);
  return {
    expression: state.expression || preset?.label || '自然',
    strength: Number(state.strength ?? 0.5),
    valence,
    arousal,
    brow: Number(state.brow || 0),
    eye: Number(state.eye || 0),
    mouth: Number(state.mouth || 0),
    head_tilt: Number(state.head_tilt || 0),
    emotion: preset?.id || '',
    emotion_x: Math.round(emotionX),
    emotion_y: Math.round(emotionY),
    quality: state.quality || 'standard',
    face_rect: state.face_rect || '',
  };
}

export function openParityPortraitEmotion(host, initial = {}, { onCreateNode, onClose } = {}) {
  const preset = PORTRAIT_EMOTIONS.find((item) => item.id === 'e03_03');
  const state = {
    valence: 0, arousal: 0, brow: 0, eye: 0, mouth: 0, head_tilt: 0,
    emotion: preset.id, emotion_x: preset.x, emotion_y: preset.y, expression: preset.label,
    strength: 0.5, quality: 'standard', face_rect: '', ...initial,
  };
  const panel = el('div', null, 'cc-floating-editor cc-portrait-emotion-panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', '情绪调节');
  panel.append(el('h4', '情绪调节'), el('p', '最多添加 1 个角色'));
  const grid = el('div', null, 'cc-itp-emotion-grid');
  grid.setAttribute('aria-label', '情绪定位');
  const pad = el('div', null, 'canvas-portrait-emotion-pad');
  pad.setAttribute('aria-label', '2D XY 情绪触控板');
  const dot = el('div', null, 'cc-emotion-pad-dot');
  const readout = el('small', '', 'cc-emotion-readout');
  const placeDot = () => {
    dot.style.left = `${clamp((state.valence + 1) / 2 * 100, 4, 96)}%`;
    dot.style.top = `${clamp((1 - state.arousal) / 2 * 100, 4, 96)}%`;
    readout.textContent = `亲近 ${state.valence.toFixed(2)} · 激动 ${state.arousal.toFixed(2)} · ${state.expression}`;
  };
  const applyPreset = (item) => {
    state.emotion = item.id;
    state.expression = item.label;
    state.emotion_x = item.x;
    state.emotion_y = item.y;
    state.valence = round4((item.x - 50) / 40);
    state.arousal = round4((item.y - 50) / 40);
    placeDot();
  };
  for (const item of PORTRAIT_EMOTIONS) grid.append(button(item.label, () => applyPreset(item)));
  pad.append(el('span', '激动', 'cc-pad-label cc-pad-top'), el('span', '平静', 'cc-pad-label cc-pad-bottom'), el('span', '疏离', 'cc-pad-label cc-pad-left'), el('span', '亲近', 'cc-pad-label cc-pad-right'), dot);
  const updateFromPointer = (event) => {
    const box = pad.getBoundingClientRect();
    const nx = clamp((event.clientX - box.left) / Math.max(1, box.width), 0, 1);
    const ny = clamp((event.clientY - box.top) / Math.max(1, box.height), 0, 1);
    state.valence = Math.round((nx * 2 - 1) * 100) / 100;
    state.arousal = Math.round((1 - ny * 2) * 100) / 100;
    state.emotion_x = Math.round(clamp(50 + state.valence * 40, 0, 100));
    state.emotion_y = Math.round(clamp(50 + state.arousal * 40, 0, 100));
    const near = nearestEmotion(state.emotion_x, state.emotion_y);
    state.emotion = near.id;
    state.expression = near.label;
    placeDot();
  };
  pad.addEventListener('pointerdown', updateFromPointer);
  pad.addEventListener('pointermove', (event) => { if (event.buttons) updateFromPointer(event); });
  const face = el('div', null, 'cc-itp-face-box');
  face.setAttribute('aria-label', '手动框选');
  let faceStart = null;
  face.addEventListener('pointerdown', (event) => {
    const box = face.getBoundingClientRect();
    faceStart = [clamp((event.clientX - box.left) / box.width, 0, 1), clamp((event.clientY - box.top) / box.height, 0, 1)];
  });
  face.addEventListener('pointerup', (event) => {
    if (!faceStart) return;
    const box = face.getBoundingClientRect();
    const end = [clamp((event.clientX - box.left) / box.width, 0, 1), clamp((event.clientY - box.top) / box.height, 0, 1)];
    const x = Math.min(faceStart[0], end[0]);
    const y = Math.min(faceStart[1], end[1]);
    state.face_rect = [x, y, Math.abs(end[0] - faceStart[0]), Math.abs(end[1] - faceStart[1])].map((value) => value.toFixed(4)).join(',');
    faceStart = null;
  });
  const sliders = el('div', null, 'cc-emotion-sliders');
  for (const [key, label] of [['brow', '眉头舒展'], ['eye', '眼神开合'], ['mouth', '嘴角弧度'], ['head_tilt', '头部微倾']]) {
    const row = el('label', label);
    const input = el('input');
    input.type = 'range';
    input.min = '-100';
    input.max = '100';
    input.value = String(state[key]);
    input.setAttribute('aria-label', label);
    input.addEventListener('input', () => { state[key] = Number(input.value); });
    row.append(input);
    sliders.append(row);
  }
  placeDot();
  const create = button('创建情绪调节节点', async () => {
    await onCreateNode?.(serializePortraitEmotion(state));
    panel.remove();
  }, 'cc-primary-btn');
  create.setAttribute('aria-label', '提交情绪调节');
  panel.append(grid, pad, readout, face, sliders, create, button('关闭', () => { panel.remove(); onClose?.(); }));
  host.append(panel);
  return () => panel.remove();
}

export const IMAGE_ACTION_CREDITS = {
  '裁剪': '免费', '旋转': '免费', '调色': '免费', '涂鸦': '免费', '生成图片': '免费',
  '创建分镜组': '免费', '全选': '免费', '反选': '免费', '进入全景': '免费',
  '人像质感': '✦ 8', '情绪调节': '✦ 8', '多角度': '✦ 8', '打光': '✦ 8',
  '角色三视图': '✦ 8', '生成大头照': '✦ 8', '角色脸部三视图': '✦ 8', '多机位九宫格 2K': '✦ 8',
  '剧情推进四格': '✦ 8', '电影级光影校正': '✦ 8', '画面推演-3s后': '✦ 8', '画面推演-5s前': '✦ 8',
  '局部重绘': '✦ 8', '扩图': '✦ 8',
  '720°全景': '✦ 10', '高清 4K': '✦ 12', '多机位九宫格 4K': '✦ 12', '去水印': '✦ 6', '抠图': '✦ 4',
};

export function creditForLabel(label) {
  const text = String(label || '').trim();
  if (!text || text.length <= 1) return '';
  if (IMAGE_ACTION_CREDITS[text]) return IMAGE_ACTION_CREDITS[text];
  if (text.includes('宫格（') || text.startsWith('自定义')) return '免费';
  return '';
}

export function stampImageToolCredits(root) {
  if (!root?.querySelectorAll) return;
  for (const node of root.querySelectorAll('button')) {
    const credit = creditForLabel(node.textContent);
    if (!credit) continue;
    node.setAttribute('data-itp-credit', credit);
    if (!node.title) node.title = credit;
  }
}
