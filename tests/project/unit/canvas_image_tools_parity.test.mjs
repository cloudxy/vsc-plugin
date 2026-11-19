import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this._text = '';
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.style = {};
    this.dataset = {};
    this.parentElement = null;
    this.className = '';
    this.value = '';
    this.disabled = false;
    this.hidden = false;
    this.title = '';
    this.type = '';
    this.placeholder = '';
    this.width = 0;
    this.height = 0;
    const self = this;
    this.classList = {
      add(...names) { self.className = [...new Set([...self.className.split(' '), ...names])].filter(Boolean).join(' '); },
      remove(...names) { self.className = self.className.split(' ').filter(name => !names.includes(name)).join(' '); },
      contains(name) { return self.className.split(' ').includes(name); },
    };
  }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      node.remove();
      node.parentElement = this;
      this.children.push(node);
    }
  }
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  replaceChildren(...nodes) {
    for (const child of [...this.children]) child.remove();
    this._text = '';
    this.append(...nodes);
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('[')) {
      const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      if (!match) return false;
      return match[2] == null ? this.attrs[match[1]] != null : this.attrs[match[1]] === match[2];
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    const walk = node => { for (const child of node.children) { found.push(child); walk(child); } };
    walk(this);
    return selector === '*' ? found : found.filter(node => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  getBoundingClientRect() { return {left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300}; }
  getContext() { return {clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, strokeRect() {}, fillText() {}}; }
  async fire(type, properties = {}) {
    const event = {target: this, button: 0, preventDefault() {}, stopPropagation() {}, ...properties};
    for (const fn of [...(this.listeners[type] || [])]) await fn(event);
  }
}

const windowListeners = {};
const window = {
  addEventListener(type, fn) { (windowListeners[type] ??= []).push(fn); },
  removeEventListener(type, fn) { windowListeners[type] = (windowListeners[type] || []).filter(item => item !== fn); },
};
const document = {createElement(tag) { return new Element(tag); }};
const parity = await loadModule('canvas-image-tools-parity.js', {document, window});

function descendants(root) {
  const found = [];
  const walk = node => { for (const child of node.children || []) { found.push(child); walk(child); } };
  walk(root);
  return found;
}
function byText(root, text) {
  return descendants(root).find(node => node.tagName === 'BUTTON' && node.textContent === text);
}
async function emitWindow(type, properties = {}) {
  const event = {button: 0, preventDefault() {}, stopPropagation() {}, ...properties};
  for (const fn of [...(windowListeners[type] || [])]) await fn(event);
}

const FILTER_IDS = ['autumn', 'black_gold', 'bw', 'bw_hard', 'comic', 'cool_white', 'cream', 'cyber', 'faded', 'forest', 'green_film', 'instant', 'jp_fresh', 'moody', 'natural', 'night', 'none', 'sepia', 'teal_orange', 'vivid', 'warm_film'];

test('crop math, eight handles and ratio confirm', async () => {
  const base = {x: 0.2, y: 0.2, w: 0.4, h: 0.4};
  assert.deepEqual(parity.resizeCropRect(base, 'e', 0.1, 0, null, 1), {x: 0.2, y: 0.2, w: 0.5, h: 0.4});
  assert.deepEqual(parity.resizeCropRect(base, 'w', 0.1, 0, null, 1), {x: 0.3, y: 0.2, w: 0.3, h: 0.4});
  assert.deepEqual(parity.resizeCropRect(base, 'e', -1, 0, null, 1), {x: 0.2, y: 0.2, w: 0.05, h: 0.4});
  assert.deepEqual(parity.resizeCropRect(base, 'e', 0.2, 0, 1, 1), {x: 0.2, y: 0.1, w: 0.6, h: 0.6});
  assert.deepEqual(parity.CROP_RATIO_PRESETS.map(item => item.label), ['自由比例', '原图比例', '1:1', '16:9', '9:16', '4:3', '3:4', '21:9', '5:2', '2:5']);
  const host = document.createElement('div');
  const submitted = [];
  parity.openParityCropOverlay(host, {naturalWidth: 1000, naturalHeight: 1000, onSubmit: async state => submitted.push(state)});
  for (const label of ['左上调整', '顶部调整', '右上调整', '右侧调整', '右下调整', '底部调整', '左下调整', '左侧调整']) {
    assert.ok(descendants(host).some(node => node.getAttribute('aria-label') === label));
  }
  const east = descendants(host).find(node => node.getAttribute('aria-label') === '右侧调整');
  await east.fire('pointerdown', {button: 0, clientX: 0, clientY: 0});
  await emitWindow('pointermove', {clientX: 40, clientY: 0});
  await emitWindow('pointerup', {});
  await byText(host, '确认').fire('click');
  assert.deepEqual(submitted[0], {x: 0.1, y: 0.1, w: 0.9, h: 0.8, ratio: 'free'});
});

test('rotate exit keeps a clean close and asks before discarding a turn', async () => {
  assert.equal(parity.rotateDegreesFromPointer(0, 0, 1, 0), 0);
  assert.equal(parity.rotateDegreesFromPointer(0, 0, 0, 1), 90);
  assert.equal(parity.rotateDegreesFromPointer(0, 0, -1, 0), -180);
  assert.equal(parity.rotateIsDirty({degrees: 0, flipX: false, flipY: false}), false);
  assert.equal(parity.rotateIsDirty({degrees: 90}), true);
  assert.equal(parity.rotateIsDirty({degrees: 0, flipX: true}), true);
  const image = document.createElement('img');
  const clean = document.createElement('div');
  let closed = 0;
  parity.openParityRotateOverlay(clean, {image, onClose: () => { closed += 1; }});
  await byText(clean, '退出').fire('click');
  assert.equal(closed, 1);
  assert.equal(clean.children.length, 0);
  const host = document.createElement('div');
  let saved = null;
  parity.openParityRotateOverlay(host, {image, onSubmit: async state => { saved = state; }, onClose: () => { closed += 1; }});
  await byText(host, '+90°').fire('click');
  assert.equal(image.style.transform, 'rotate(90deg) scale(1, 1)');
  await byText(host, '水平镜像').fire('click');
  assert.equal(image.style.transform, 'rotate(90deg) scale(-1, 1)');
  await byText(host, '退出').fire('click');
  const dialog = descendants(host).find(node => node.getAttribute('aria-label') === '退出旋转');
  assert.equal(dialog.hidden, false);
  assert.match(host.textContent, /退出旋转/);
  assert.match(host.textContent, /您对图像做了旋转或镜像调整，退出前是否保存？/);
  assert.equal(closed, 1);
  await byText(host, '保存').fire('click');
  assert.equal(saved.degrees, 90);
  assert.equal(saved.flipX, true);
  assert.equal(saved.flip_x, true);
  assert.equal(saved.flipY, false);
});

test('color panel exposes 21 filters, categories, strength and teal-orange export', async () => {
  assert.deepEqual(parity.PARITY_FILTERS.map(item => item.id).sort(), [...FILTER_IDS].sort());
  assert.deepEqual(parity.PARITY_FILTER_CATEGORIES.map(item => item[1]), ['全部', '热门', '基础', '电影', '胶片', '日系', '黑白', '氛围']);
  assert.equal(parity.computeParityColorCss({filterId: 'none', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0}), 'none');
  assert.equal(parity.isParityColorIdentity({filterId: 'none', strength: 40}), true);
  assert.equal(parity.computeParityColorCss({filterId: 'teal_orange', strength: 100, hue: 0, saturation: 0, brightness: 0, contrast: 0}), 'hue-rotate(-8deg) saturate(114%) brightness(98%) contrast(116%)');
  const image = document.createElement('img');
  const host = document.createElement('div');
  const submitted = [];
  parity.openParityColorAdjust(host, {image, onSubmit: async state => submitted.push(state)});
  const panel = descendants(host).find(node => node.classList.contains('cc-color-adjust-panel'));
  assert.ok(panel);
  const confirm = byText(host, '确认');
  assert.equal(confirm.getAttribute('aria-label'), '确认调色');
  assert.equal(confirm.disabled, true);
  await byText(host, '黑白').fire('click');
  assert.ok(byText(host, '经典黑白'));
  assert.equal(byText(host, '青橙电影'), undefined);
  await byText(host, '全部').fire('click');
  await byText(host, '青橙电影').fire('click');
  assert.equal(confirm.disabled, false);
  assert.equal(image.style.filter, 'hue-rotate(-8deg) saturate(114%) brightness(98%) contrast(116%)');
  const hue = descendants(host).find(node => node.getAttribute('aria-label') === '色相');
  hue.value = '12';
  await hue.fire('input');
  assert.equal(image.style.filter, 'hue-rotate(4deg) saturate(114%) brightness(98%) contrast(116%)');
  await confirm.fire('click');
  assert.equal(submitted[0].filterId, 'teal_orange');
  assert.equal(submitted[0].hue, 12);
  assert.equal(submitted[0].strength, 100);
});

test('grid select-all, invert and shift range stay inside 8 by 8', async () => {
  assert.equal(parity.gridSelectAll(8, 8).length, 64);
  assert.equal(parity.gridInvert(2, 2, [{row: 1, column: 1}]).length, 3);
  assert.equal(parity.selectGridRange({row: 1, column: 1}, {row: 2, column: 2}, [], false).length, 4);
  const added = parity.selectGridRange({row: 1, column: 1}, {row: 1, column: 2}, [{row: 2, column: 2}], true);
  assert.deepEqual(added, [{row: 2, column: 2}, {row: 1, column: 1}, {row: 1, column: 2}]);
  const tools = document.createElement('div');
  const grid = {rows: 8, columns: 8, cells: [{row: 1, column: 1}], refresh() {}};
  parity.mountGridParityActions(tools, grid);
  await byText(tools, '全选').fire('click');
  assert.equal(grid.cells.length, 64);
  await byText(tools, '反选').fire('click');
  assert.equal(grid.cells.length, 0);
});

test('doodle history supports brush, arrow, text, undo and redo', async () => {
  const history = parity.createDoodleHistory();
  assert.equal(history.canUndo(), false);
  history.push([{tool: 'brush', color: '#ff3b30', width: 6, points: [[0, 0], [1, 1]]}]);
  assert.equal(history.canUndo(), true);
  assert.deepEqual(history.undo(), []);
  assert.equal(history.canRedo(), true);
  assert.equal(history.redo()[0].tool, 'brush');
  assert.equal(parity.normalizeDoodleStroke({tool: 'arrow', color: '#00ff00', width: 4, points: [[0.2, 0.2]]}), null);
  assert.equal(parity.normalizeDoodleStroke({tool: 'text', color: '#00ff00', width: 4, points: [[0.2, 0.2]], text: ''}), null);
  const host = document.createElement('div');
  const submitted = [];
  parity.openParityDoodleOverlay(host, {onSubmit: async payload => submitted.push(payload)});
  assert.ok(descendants(host).some(node => node.getAttribute('aria-label') === '涂鸦笔宽'));
  const canvas = descendants(host).find(node => node.tagName === 'CANVAS');
  await canvas.fire('pointerdown', {button: 0, clientX: 10, clientY: 10});
  await canvas.fire('pointermove', {clientX: 120, clientY: 80});
  await canvas.fire('pointerup', {});
  await byText(host, '撤销').fire('click');
  await byText(host, '重做').fire('click');
  await byText(host, '箭头').fire('click');
  await canvas.fire('pointerdown', {button: 0, clientX: 20, clientY: 30});
  await canvas.fire('pointermove', {clientX: 180, clientY: 50});
  await canvas.fire('pointerup', {});
  await byText(host, '框选').fire('click');
  await canvas.fire('pointerdown', {button: 0, clientX: 40, clientY: 40});
  await canvas.fire('pointermove', {clientX: 160, clientY: 140});
  await canvas.fire('pointerup', {});
  await byText(host, '文本').fire('click');
  const text = descendants(host).find(node => node.getAttribute('aria-label') === '文本');
  text.value = '标注';
  await canvas.fire('pointerdown', {button: 0, clientX: 50, clientY: 60});
  await canvas.fire('pointerup', {});
  await byText(host, '保存涂鸦').fire('click');
  assert.deepEqual(submitted[0].strokes.map(stroke => stroke.tool), ['brush', 'arrow', 'rect', 'text']);
  assert.equal(submitted[0].strokes[3].text, '标注');
});

test('inpaint requires a prompt and mask, outpaint stores the outward frame', async () => {
  assert.throws(() => parity.inpaintExportPayload({prompt: '', strokes: [[{tool: 'brush'}]]}), /请输入局部重绘提示词/);
  assert.throws(() => parity.inpaintExportPayload({prompt: '改成黄昏', strokes: []}), /请先涂抹需要重绘的区域/);
  assert.deepEqual(parity.outpaintFrameForRatio(1, '16:9'), {x: -0.3889, y: 0, w: 1.7778, h: 1, ratio: '16:9'});
  const inpaintHost = document.createElement('div');
  const inpaint = {tool: 'inpaint', settings: {prompt: ''}, prompt: '', promptEnabled: false};
  const seen = [];
  parity.mountNodeImageEditor(inpaintHost, inpaint, {
    mountImageControls() { throw new Error('局部重绘不应挂载旧轨道控件'); },
    transformImage: async (operation, settings) => { seen.push([operation, settings.strokes.length]); return {media_ids: ['mask-1']}; },
    onSubmit: async () => { seen.push(['submit', inpaint.settings.mask_media_id, inpaint.prompt]); },
  });
  await assert.rejects(() => byText(inpaintHost, '保存').fire('click'), /请输入局部重绘提示词/);
  descendants(inpaintHost).find(node => node.tagName === 'TEXTAREA').value = '把天空改成黄昏';
  await assert.rejects(() => byText(inpaintHost, '保存').fire('click'), /请先涂抹需要重绘的区域/);
  const canvas = descendants(inpaintHost).find(node => node.tagName === 'CANVAS');
  await canvas.fire('pointerdown', {button: 0, clientX: 10, clientY: 12});
  await canvas.fire('pointermove', {clientX: 90, clientY: 40});
  await canvas.fire('pointerup', {});
  await byText(inpaintHost, '保存').fire('click');
  assert.deepEqual(seen, [['mask', 1], ['submit', 'mask-1', '把天空改成黄昏']]);
  assert.equal(inpaint.promptEnabled, true);
  const outHost = document.createElement('div');
  const outpaint = {tool: 'outpaint', settings: {ratio: '16:9'}, promptEnabled: true};
  let submitted = false;
  parity.mountNodeImageEditor(outHost, outpaint, {
    mountImageControls() { throw new Error('扩图不应挂载旧轨道控件'); },
    naturalWidth: 1000,
    naturalHeight: 1000,
    onSubmit: async () => { submitted = true; },
  });
  assert.equal(descendants(outHost).filter(node => (node.getAttribute('aria-label') || '').endsWith('调整')).length, 8);
  await byText(outHost, '确认').fire('click');
  assert.equal(submitted, true);
  assert.equal(outpaint.promptEnabled, false);
  assert.equal(outpaint.settings.ratio, '16:9');
  assert.equal(outpaint.settings.rect_x, -0.3889);
  assert.equal(outpaint.settings.rect_y, 0);
  assert.equal(outpaint.settings.rect_w, 1.7778);
  assert.equal(outpaint.settings.rect_h, 1);
  assert.equal(outpaint.settings.padding, 0.3889);
  assert.equal(outpaint.settings.source_width, 1000);
  assert.equal(outpaint.settings.source_height, 1000);
});

test('lighting, multi-angle, texture and 25 emotions serialize reference fields', async () => {
  assert.equal(parity.LIGHTING_SNAPS.length, 27);
  const snap = parity.LIGHTING_SNAPS.find(item => item.id === 'left_top_front');
  assert.equal(snap.label, '前左上');
  assert.deepEqual({x: snap.x, y: snap.y, z: snap.z}, {x: -1, y: 1, z: 1});
  assert.equal(parity.LIGHTING_SNAPS.find(item => item.id === 'center_middle_center').label, '中');
  const lighting = {tool: 'lighting', settings: {intensity: 0.5, direction: 'front', color: '#ffffff', rim: true}, defaults: {intensity: 1}};
  parity.primeImageToolSettings(lighting);
  assert.equal(lighting.settings.brightness, 0.5);
  const kept = {tool: 'lighting', settings: {intensity: 0.5, brightness: 2}, defaults: {}};
  parity.primeImageToolSettings(kept);
  assert.equal(kept.settings.brightness, 2);
  const lightHost = document.createElement('div');
  parity.mountParityToolExtras(lightHost, lighting);
  assert.equal(descendants(lightHost).filter(node => node.getAttribute('data-itp-light')).length, 27);
  await descendants(lightHost).find(node => node.getAttribute('data-itp-light') === 'left_top_front').fire('click');
  assert.deepEqual(parity.serializeLighting(lighting.settings), {
    brightness: 0.5,
    color: '#ffffff',
    description: '',
    direction: {x: -1, y: 1, z: 1},
    rimLightDirection: {x: 0, y: 0, z: -1},
  });
  const angle = {tool: 'angle', settings: {preset: 'custom', yaw: 0, pitch: 0, roll: 0, zoom: 1, include_instructions: true}, defaults: {}, prompt: '', promptEnabled: false};
  parity.primeImageToolSettings(angle);
  const angleHost = document.createElement('div');
  parity.mountParityToolExtras(angleHost, angle);
  await byText(angleHost, '全景俯拍').fire('click');
  assert.equal(angle.settings.pitch, 60);
  assert.equal(angle.settings.scale, 'wide');
  await byText(angleHost, '特写').fire('click');
  const note = descendants(angleHost).find(node => node.getAttribute('aria-label') === '补充需要保留或调整的画面描述');
  note.value = '保留服装';
  await note.fire('input');
  assert.deepEqual(parity.serializeMultiAngle(angle.settings), {preset: 'wideTop', yaw: 0, pitch: 60, scale: 'close', description: '保留服装'});
  assert.equal(angle.promptEnabled, true);
  const textureHost = document.createElement('div');
  let texture = null;
  parity.openParityPortraitTexture(textureHost, {}, {onApply: async state => { texture = state; }});
  const warning = descendants(textureHost).find(node => node.classList.contains('cc-itp-texture-warning'));
  assert.equal(warning.hidden, true);
  assert.match(warning.textContent, /高强度调节可能影响人物一致性/);
  await byText(textureHost, '深度融合').fire('click');
  assert.equal(warning.hidden, false);
  await byText(textureHost, '应用参数').fire('click');
  assert.equal(texture.scene_blend, 'deep');
  assert.equal(texture.quality, 'medium');
  assert.equal(parity.PORTRAIT_EMOTIONS.length, 25);
  assert.equal(parity.PORTRAIT_EMOTIONS[0].label, '欣然愉悦');
  assert.equal(parity.PORTRAIT_EMOTIONS[24].label, '疏离冷淡');
  const emotion = parity.serializePortraitEmotion({valence: 0.5, arousal: 0.6, strength: 0.5, brow: 0, eye: 0, mouth: 0, head_tilt: 0, quality: 'standard', face_rect: ''});
  assert.equal(emotion.emotion, 'e02_04');
  assert.equal(emotion.expression, '强忍悲戚');
  assert.equal(emotion.emotion_x, 70);
  assert.equal(emotion.emotion_y, 74);
  const emotionHost = document.createElement('div');
  let created = null;
  parity.openParityPortraitEmotion(emotionHost, {}, {onCreateNode: async state => { created = state; }});
  assert.equal(descendants(emotionHost).filter(node => node.tagName === 'BUTTON' && parity.PORTRAIT_EMOTIONS.some(item => item.label === node.textContent)).length, 25);
  const pad = descendants(emotionHost).find(node => node.classList.contains('canvas-portrait-emotion-pad'));
  await pad.fire('pointerdown', {clientX: 300, clientY: 60, button: 0});
  await byText(emotionHost, '创建情绪调节节点').fire('click');
  assert.equal(created.valence, 0.5);
  assert.equal(created.arousal, 0.6);
  assert.equal(created.emotion, 'e02_04');
  assert.equal(created.quality, 'standard');
  assert.deepEqual(Object.keys(created).sort(), ['arousal', 'brow', 'emotion', 'emotion_x', 'emotion_y', 'expression', 'eye', 'face_rect', 'head_tilt', 'mouth', 'quality', 'strength', 'valence']);
});

test('image action credits stay outside the button text', () => {
  assert.equal(parity.creditForLabel('裁剪'), '免费');
  assert.equal(parity.creditForLabel('局部重绘'), '✦ 8');
  assert.equal(parity.creditForLabel('高清 4K'), '✦ 12');
  assert.equal(parity.creditForLabel('多机位九宫格 4K'), '✦ 12');
  assert.equal(parity.creditForLabel('去水印'), '✦ 6');
  assert.equal(parity.creditForLabel('抠图'), '✦ 4');
  assert.equal(parity.creditForLabel('720°全景'), '✦ 10');
  assert.equal(parity.creditForLabel('4宫格（2×2）'), '免费');
  assert.equal(parity.creditForLabel('自定义 3×5'), '免费');
  assert.equal(parity.creditForLabel('×'), '');
  const root = document.createElement('div');
  const crop = document.createElement('button');
  crop.textContent = '裁剪';
  const repaint = document.createElement('button');
  repaint.textContent = '局部重绘';
  repaint.title = '展开以同步画布生成工具';
  const glyph = document.createElement('button');
  glyph.textContent = '×';
  root.append(crop, repaint, glyph);
  parity.stampImageToolCredits(root);
  assert.equal(crop.getAttribute('data-itp-credit'), '免费');
  assert.equal(crop.textContent, '裁剪');
  assert.equal(crop.title, '免费');
  assert.equal(repaint.getAttribute('data-itp-credit'), '✦ 8');
  assert.equal(repaint.textContent, '局部重绘');
  assert.equal(repaint.title, '展开以同步画布生成工具');
  assert.equal(glyph.getAttribute('data-itp-credit'), null);
});
