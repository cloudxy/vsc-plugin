import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

const cards = await loadModule('canvas-node-cards.js', {
  document: {createElementNS: () => ({setAttribute() {}, append() {}})},
  window: {addEventListener() {}, removeEventListener() {}},
  crypto,
});

const node = (id, type, extra = {}) => ({
  id, type, title: extra.title ?? id, x: extra.x ?? 0, y: extra.y ?? 0, text: extra.text ?? '',
  params: extra.params ? {...extra.params} : {}, media_id: extra.media_id ?? null,
  job_id: extra.job_id ?? null, group: extra.group ?? '',
});
const doc = (nodes, edges = []) => ({viewport: {x: 0, y: 0, zoom: 1}, nodes, edges});

const HEAD_TAIL = {
  operations: [{
    op_type: 'head_tail_video', node_type: 'video',
    input_ports: [
      {handle: 'prompt', accept: ['text'], max_count: 200},
      {handle: 'first_frame', accept: ['image'], max_count: 1},
      {handle: 'last_frame', accept: ['image'], max_count: 1},
    ],
  }],
};
const IMAGE_GEN = {
  operations: [{
    op_type: 'image_generate', node_type: 'image',
    input_ports: [
      {handle: 'prompt', accept: ['text'], max_count: 200},
      {handle: 'reference', accept: ['image'], max_count: 2},
    ],
  }],
};

test('connection checks use port compatibility, cardinality and the reference messages', () => {
  const text = node('t', 'text');
  const image = node('i', 'image');
  const audio = node('a', 'audio');
  const video = node('v', 'video', {params: {vsc_operation: 'head_tail_video'}});
  const base = doc([text, image, audio, video]);

  const self = cards.choosePort(base, text, text);
  assert.equal(self.reason, 'self');
  assert.equal(cards.explainRejection(self), '节点不能连接到自身。');

  const duplicateDoc = doc([text, image], [{id: 'e', source: 't', target: 'i', port: 'prompt'}]);
  const duplicate = cards.choosePort(duplicateDoc, text, image);
  assert.equal(duplicate.reason, 'duplicate');
  assert.equal(cards.explainRejection(duplicate), '这张素材已经连接到当前节点。');

  const cycleDoc = doc([text, image], [{id: 'e', source: 'i', target: 't', port: 'prompt'}]);
  const cycle = cards.choosePort(cycleDoc, text, image);
  assert.equal(cycle.reason, 'cycle');
  assert.equal(cards.explainRejection(cycle), '画布引用不能成环');

  const crowded = doc([text, image], Array.from({length: 800}, (_, index) => ({id: `e${index}`, source: 'x', target: 'y', port: 'prompt'})));
  const limited = cards.choosePort(crowded, text, image);
  assert.equal(limited.reason, 'max_edges');
  assert.equal(cards.explainRejection(limited), '单个画布最多 800 条连线');

  const closed = cards.choosePort(base, image, text);
  assert.equal(closed.reason, 'target_not_connectable');
  assert.equal(cards.explainRejection(closed), '当前目标节点不支持添加输入连接');

  const mismatch = cards.choosePort(base, image, audio);
  assert.equal(mismatch.reason, 'media_input_unsupported');
  assert.equal(cards.explainRejection(mismatch), '当前目标节点不支持连接图片节点');

  assert.equal(cards.choosePort(base, image, video, cards.DEFAULT_TYPES, HEAD_TAIL).port, 'first_frame');
  const fullTail = doc([video, node('p1', 'image'), node('p2', 'image'), node('p3', 'image')], [
    {id: 'f', source: 'p1', target: 'v', port: 'first_frame'},
    {id: 'l', source: 'p2', target: 'v', port: 'last_frame'},
  ]);
  const tail = cards.choosePort(fullTail, node('p3', 'image'), video, cards.DEFAULT_TYPES, HEAD_TAIL);
  assert.equal(tail.reason, 'head_tail_max');
  assert.equal(cards.explainRejection(tail), '首尾帧模式最多支持 2 张图片');

  const generated = node('g', 'image', {params: {vsc_operation: 'image_generate'}});
  const referenced = doc([generated, node('r1', 'image'), node('r2', 'image'), node('r3', 'image')], [
    {id: 'r1e', source: 'r1', target: 'g', port: 'reference'},
    {id: 'r2e', source: 'r2', target: 'g', port: 'reference'},
  ]);
  const reference = cards.choosePort(referenced, node('r3', 'image'), generated, cards.DEFAULT_TYPES, IMAGE_GEN);
  assert.equal(reference.reason, 'reference_max');
  assert.equal(reference.max, 2);
  assert.equal(cards.explainRejection(reference), '当前节点最多支持连接2个参考节点');

  const prompted = doc([audio, ...Array.from({length: 9}, (_, index) => node(`p${index}`, 'text'))],
    Array.from({length: 8}, (_, index) => ({id: `p${index}`, source: `p${index}`, target: 'a', port: 'prompt'})));
  const maxed = cards.choosePort(prompted, node('p8', 'text'), audio);
  assert.equal(maxed.reason, 'max_count');
  assert.equal(cards.explainRejection(maxed), '当前音频节点最多支持连接8个文本节点');

  const ignored = node('img', 'image', {params: {vsc_operation: 'head_tail_video'}});
  assert.equal(cards.choosePort(doc([text, ignored]), text, ignored, cards.DEFAULT_TYPES, HEAD_TAIL).port, 'prompt');
});

test('connect, rename, primary media, reassignment and zip mutate a copy of the document', () => {
  const text = node('t', 'text', {title: '原文'});
  const image = node('i', 'image');
  const original = doc([text, image], []);
  const linked = cards.connectNodes(original, 't', 'i', cards.DEFAULT_TYPES, null, () => 'edge-1');
  assert.equal(linked.ok, true);
  assert.deepEqual(linked.edge, {id: 'edge-1', source: 't', target: 'i', port: 'prompt'});
  assert.equal(original.edges.length, 0);
  assert.notEqual(linked.document, original);
  const refused = cards.connectNodes(original, 't', 't');
  assert.equal(refused.ok, false);
  assert.equal(refused.document, original);

  const many = cards.connectMany(doc([text, node('a', 'audio'), image]), ['t', 'a', 'i'], 'i', cards.DEFAULT_TYPES, null, () => 'edge-2');
  assert.equal(many.edges.length, 1);
  assert.equal(many.edges[0].port, 'prompt');
  assert.equal(many.message, '当前目标节点不支持连接音频节点');

  const renamed = cards.renameNode(original, 't', '  新标题  ');
  assert.equal(renamed.ok, true);
  assert.equal(renamed.document.nodes[0].title, '新标题');
  assert.equal(original.nodes[0].title, '原文');
  assert.equal(cards.renameNode(original, 't', '   ').message, '节点标题不能为空');
  assert.equal(cards.renameNode(original, 't', '名'.repeat(201)).message, '节点标题最长 200 字');
  assert.equal(cards.renameNode(original, 't', '名'.repeat(200)).ok, true);

  const outputs = [{media_id: 'm1'}, {media_id: 'm2'}];
  const hosted = doc([node('i', 'image', {media_id: 'm1', job_id: 'j1'})]);
  const primary = cards.setPrimaryMedia(hosted, 'i', 'm2', outputs);
  assert.equal(primary.ok, true);
  assert.equal(primary.document.nodes[0].media_id, 'm2');
  assert.equal(primary.document.nodes[0].params.primary_media_id, 'm2');
  assert.equal(hosted.nodes[0].media_id, 'm1');
  assert.equal(cards.setPrimaryMedia(hosted, 'i', 'missing', outputs).message, '该结果不属于当前节点');

  const down = node('d', 'image', {title: '下游'});
  const other = node('o', 'image', {title: '新源'});
  const from = node('s', 'image', {title: '旧源'});
  const edge = {id: 'keep', source: 's', target: 'd', port: 'reference'};
  const moved = cards.batchReassign(doc([from, other, down], [edge]), 's', 'o', ['keep']);
  assert.equal(moved.ok, true);
  assert.equal(edge.source, 's');
  assert.deepEqual(moved.document.edges[0], {id: 'keep', source: 'o', target: 'd', port: 'reference'});
  assert.equal(cards.batchReassign(doc([from, node('x', 'text'), down], [edge]), 's', 'x').message, '仅支持迁移到同类型节点的出口');
  assert.equal(cards.batchReassign(doc([from, other]), 's', 'o').message, '当前节点没有可迁移的出边');
  const fixed = {id: 'fix', source: 's', target: 'd', port: 'derived_from'};
  assert.equal(cards.batchReassign(doc([from, other, down], [fixed]), 's', 'o', ['fix']).message, '连线包含三视图、全景图或其他不可迁移的固定关系');
  assert.equal(cards.batchReassign(doc([from, other, down], [edge]), 's', 'o', ['stale']).message, '连线状态已变化，请重新操作');
  const occupied = doc([from, other, down], [edge, {id: 'already', source: 'o', target: 'd', port: 'prompt'}]);
  assert.equal(cards.batchReassign(occupied, 's', 'o', ['keep']).message, '新源节点与原下游已存在连线，原连线未修改');
  assert.equal(cards.isFixedReferenceEdge(fixed, doc([down])), true);
  assert.equal(cards.isFixedReferenceEdge({id: 'p', source: 's', target: 'd', port: 'reference'}, doc([node('d', 'image', {params: {fixed_reference_of: 's'}})])), true);
  assert.equal(cards.removeEdge(doc([from, down], [fixed]), 'fix').message, '固定引用连线不可删除');

  const when = new Date(2026, 10, 18, 9, 8, 7);
  assert.equal(cards.zipFileName(when), '画布节点_20261118090807.zip');
  const bytes = cards.buildStoredZip([{name: 'image/a.txt', text: '原标题\nimage\n正文\n'}], when);
  assert.deepEqual([...bytes.slice(0, 4)], [0x50, 0x4b, 0x03, 0x04]);
  assert.equal(bytes[6], 0x00);
  assert.equal(bytes[7], 0x08);
  const decoded = new TextDecoder().decode(bytes);
  assert.equal(decoded.includes('image_a.txt'), true);
  assert.equal(decoded.includes('原标题'), true);
  assert.equal(decoded.includes('PK\u0001\u0002'), true);
  assert.equal(decoded.includes('PK\u0005\u0006'), true);

  const empty = node('img', 'image', {x: 10, y: 20});
  assert.deepEqual(cards.nodeSize(empty), {w: 220, h: 300});
  assert.deepEqual(cards.nodeSize(node('media', 'image', {media_id: 'm'})), {w: 240, h: 134});
  assert.deepEqual(cards.nodeSize(node('box', 'text', {params: {collapsed: true, card_w: 280}})), {w: 280, h: 36});
  const fromNode = node('from', 'text', {x: 0, y: 0});
  const toNode = node('to', 'image', {x: 300, y: 0, media_id: 'm'});
  assert.equal(cards.nodeEdgePath(fromNode, toNode), 'M 240 67 C 280 67, 260 67, 300 67');

  assert.deepEqual(cards.recommendationsFor(empty).map(item => item.label), ['图生图']);
  assert.deepEqual(cards.recommendationsFor(node('vid', 'video')).map(item => item.id), ['head-tail', 'first-frame']);
  assert.equal(cards.recommendationsFor(node('gone', 'image', {params: {collapsed: true}})).length, 0);
  let seq = 0;
  const derived = cards.applyRecommendation(doc([empty]), 'img', 'image-to-image', () => `n${++seq}`);
  assert.equal(derived.ok, true);
  assert.equal(doc([empty]).nodes.length, 1);
  assert.equal(derived.document.nodes[1].params.vsc_operation, 'image_generate');
  assert.deepEqual(derived.document.edges[0], {id: 'n2', source: 'img', target: 'n1', port: 'reference'});
  const preset = '电影级人物镜头\n雨夜街头，霓虹灯反射在湿漉漉的地面，女主撑伞站在路灯下，表情克制而坚定，镜头环绕人物360度缓慢移动，浅景深，光影对比强烈，电影级调色，真实皮肤质感';
  const videoPlan = cards.applyRecommendation(doc([node('txt', 'text')]), 'txt', 'text-to-video', () => `v${++seq}`);
  assert.equal(videoPlan.document.nodes[0].text, preset);
  assert.equal(videoPlan.document.nodes[1].text, '根据文字描述生成视频。');
  assert.equal(videoPlan.document.nodes[1].group, '预设 - 文生视频');
  assert.equal(videoPlan.document.edges[0].port, 'prompt');
  const full = doc(Array.from({length: 200}, (_, index) => node(`n${index}`, 'image')));
  assert.equal(cards.applyRecommendation(full, 'n0', 'image-to-image').message, '画布最多200个节点');
  assert.equal(full.nodes.length, 200);
});

class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.value = '';
    this.style = {removeProperty(key) { delete this[key]; }};
    this.offsetWidth = 190;
    this.offsetHeight = 250;
    this.clientWidth = 1200;
    this.clientHeight = 800;
    this.scrollLeft = 0;
    this.scrollTop = 0;
    this.dataset = {};
    this.parentElement = null;
    this.className = '';
    this.classList = {
      add: (...values) => { this.className = [...new Set([...this.className.split(' '), ...values])].filter(Boolean).join(' '); },
      contains: value => this.className.split(' ').includes(value),
      remove: (...values) => { this.className = this.className.split(' ').filter(value => !values.includes(value)).join(' '); },
    };
  }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { for (const item of nodes) { item.remove(); item.parentElement = this; this.children.push(item); } }
  prepend(...nodes) { for (const item of nodes.reverse()) { item.remove(); item.parentElement = this; this.children.unshift(item); } }
  remove() { if (this.parentElement) { this.parentElement.children = this.parentElement.children.filter(item => item !== this); this.parentElement = null; } }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this._text = ''; this.append(...nodes); }
  insertBefore(item, before) { item.remove(); item.parentElement = this; const index = this.children.indexOf(before); this.children.splice(index < 0 ? this.children.length : index, 0, item); }
  removeAttribute(key) { delete this.attrs[key]; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  matches(selector) {
    if (selector[0] === '.') return this.classList.contains(selector.slice(1));
    if (selector[0] === '[') {
      const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return match && (match[2] == null ? this.attrs[match[1]] != null : this.attrs[match[1]] === match[2]);
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const values = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return values;
    return values.filter(child => selector.split(',').some(part => child.matches(part.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let current = this; current; current = current.parentElement) {
      if (selector.split(',').some(part => current.matches(part.trim()))) return current;
    }
    return null;
  }
  getBoundingClientRect() { return {left: 0, top: 0, width: 400, height: 300}; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  get isConnected() { return this.parentElement !== null; }
  async fire(type, properties = {}) {
    const event = {target: this, preventDefault() {}, stopPropagation() {}, ...properties};
    for (const fn of this.listeners[type] || []) await fn(event);
  }
  focus() { this.ownerDocument.activeElement = this; }
  pause() {}
  close() {}
}

async function openCanvas({nodes = [], edges = [], jobs = {}} = {}) {
  const store = new Map();
  const canvasCalls = [];
  const document = {
    createElement: tag => {
      const created = new Element(tag);
      created.ownerDocument = document;
      return created;
    },
    createElementNS: (namespace, tag) => {
      const created = document.createElement(tag);
      created.namespaceURI = namespace;
      return created;
    },
    createTextNode: text => {
      const created = new Element('#text', text);
      created.ownerDocument = document;
      return created;
    },
    documentElement: {},
  };
  const listeners = new Map();
  const window = {
    addEventListener(type, fn) { (listeners.get(type) || listeners.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { listeners.get(type)?.delete(fn); },
    async fire(type, event = {}) { for (const fn of [...(listeners.get(type) || [])]) await fn(event); },
  };
  const timeouts = [];
  const mod = await loadModule('creative-canvas.js', {
    document, window, crypto, console,
    location: {search: '', href: 'http://127.0.0.1:8765/canvas', assign() {}},
    sessionStorage: {getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)},
    requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},
    fetch: async () => ({ok: true, text: async () => ''}),
    setTimeout: (fn, delay) => { if (delay === 0) return setTimeout(fn, 0); timeouts.push({fn, delay}); return timeouts.length; },
    clearTimeout: () => {},
    Image: class FakeImage {},
  });
  const root = document.createElement('main');
  let version = 1;
  const panel = mod.createCreativeCanvasPanel({
    session: () => ({actor: 'test', csrf: 'csrf-1', revision: 1, writable: true}),
    setRevision() {}, opened() {},
    api: async (path, options) => {
      const body = options?.body ? JSON.parse(options.body) : null;
      canvasCalls.push({path, method: options?.method || 'GET', body});
      if (path === '/api/v1/projects/p1/creative-canvases/c1' && options?.method === 'PUT') {
        version += 1;
        return {revision: version, canvas_revision: version, title: body.payload.title};
      }
      if (path === '/api/v1/projects/p1/creative-canvases/c1') {
        return {revision: version, canvas_revision: version, title: '节点卡片', episode_id: null, document: {viewport: {x: 0, y: 0, zoom: 1}, nodes, edges}, jobs, runs: [], execution_steps: []};
      }
      if (String(path).endsWith('/creative-canvas-run-options')) return {revision: version, models: [], operations: [], nodes: []};
      if (String(path).endsWith('/creative-canvas-settings-models')) return {models: [], revision: version};
      return {items: [], revision: version};
    },
  });
  await panel.load(root, 'p1', null, 'c1');
  return {root, panel, store, canvasCalls, timeouts, window};
}

function draft(store) {
  const key = [...store.keys()].find(item => item.startsWith('vsc-creative-canvas:v2:'));
  return key ? JSON.parse(store.get(key)).document : null;
}
const cardOf = (root, id) => root.querySelectorAll('.cc-node').find(card => card.dataset.nodeId === id);
const statusOf = root => root.querySelector('.cc-status').textContent;

async function dragPort(window, port, target, client) {
  await port.fire('pointerdown', {button: 0, clientX: 12, clientY: 24});
  await window.fire('pointermove', {clientX: 40, clientY: 24, target: port, button: 0});
  await window.fire('pointerup', {clientX: client?.x ?? 180, clientY: client?.y ?? 200, target, button: 0});
}

test('empty cards show the reference placeholder, try capsules and keep 操作 without the old focus buttons', async () => {
  const f = await openCanvas({nodes: [
    node('img', 'image', {x: 40, y: 40}),
    node('vid', 'video', {x: 300, y: 40}),
    node('aud', 'audio', {x: 560, y: 40}),
    node('txt', 'text', {x: 40, y: 380}),
  ]});
  const image = cardOf(f.root, 'img');
  await image.fire('click', {target: image});
  const selected = cardOf(f.root, 'img');
  assert.equal(selected.classList.contains('selected'), true);
  assert.equal(selected.classList.contains('a1-card'), true);
  assert.equal(selected.classList.contains('a1-portrait'), true);
  assert.ok(selected.querySelector('.a1-placeholder').querySelector('svg'));
  assert.equal(selected.textContent.includes('尝试：'), true);
  assert.equal(selected.querySelectorAll('button').some(button => button.textContent === '图生图'), true);
  assert.equal(selected.querySelectorAll('button').some(button => button.textContent === '操作'), true);
  assert.equal(selected.querySelectorAll('button').some(button => button.textContent === '聚焦'), false);
  assert.equal(selected.querySelectorAll('button').some(button => button.textContent === '＋参考'), false);
  assert.equal(cardOf(f.root, 'vid').textContent.includes('首尾帧生成视频'), true);
  assert.equal(cardOf(f.root, 'vid').textContent.includes('首帧生成视频'), true);
  assert.equal(cardOf(f.root, 'aud').textContent.includes('音频生视频'), true);
  for (const label of ['自己编写内容', '文生视频', '图片反推提示词', '文字生音乐']) {
    assert.equal(cardOf(f.root, 'txt').textContent.includes(label), true, label);
  }
  await cardOf(f.root, 'img').querySelector('[aria-label="在左侧引用生成"]').fire('click');
  const menu = f.root.querySelector('.a1-menu');
  assert.equal(menu.querySelector('h3').textContent, '添加节点');
  const videoChoice = menu.querySelectorAll('button').find(button => button.textContent === '视频');
  assert.equal(videoChoice.disabled, true);
  assert.equal(videoChoice.getAttribute('title'), '当前目标节点不支持连接视频节点');
  assert.equal(Boolean(menu.querySelectorAll('button').find(button => button.textContent === '文本').disabled), false);
  await cardOf(f.root, 'vid').querySelectorAll('button').find(button => button.textContent === '首尾帧生成视频').fire('click');
  assert.equal(draft(f.store).nodes.find(item => item.id === 'vid').params.vsc_operation, 'head_tail_video');
  await cardOf(f.root, 'img').querySelectorAll('button').find(button => button.textContent === '图生图').fire('click');
  const saved = draft(f.store);
  assert.equal(saved.nodes.length, 5);
  assert.equal(saved.edges.length, 1);
  assert.equal(saved.edges[0].source, 'img');
  assert.equal(saved.edges[0].port, 'reference');
  assert.equal(saved.nodes.find(item => item.id === saved.edges[0].target).params.vsc_operation, 'image_generate');
  const textCard = cardOf(f.root, 'txt');
  await textCard.querySelector('[aria-label="调整文本节点大小"]').fire('pointerdown', {button: 0, clientX: 10, clientY: 10});
  await f.window.fire('pointermove', {clientX: 50, clientY: 40, button: 0});
  await f.window.fire('pointerup', {clientX: 50, clientY: 40, button: 0});
  assert.equal(draft(f.store).nodes.find(item => item.id === 'txt').params.card_w, 280);
  assert.equal(draft(f.store).nodes.find(item => item.id === 'txt').params.card_h, 164);
  await cardOf(f.root, 'txt').querySelectorAll('button').find(button => button.textContent === '收起').fire('click');
  assert.equal(cardOf(f.root, 'txt').classList.contains('a1-collapsed'), true);
  assert.equal(draft(f.store).nodes.find(item => item.id === 'txt').params.collapsed, true);
  f.panel.suspend();
});

test('dragging a port creates a persisted edge and a blank drop adds the chosen node', async () => {
  const f = await openCanvas({nodes: [node('t', 'text', {x: 80, y: 60, text: '提示'}), node('i', 'image', {x: 420, y: 60, media_id: 'm1'})]});
  const textCard = cardOf(f.root, 't');
  const port = textCard.querySelector('[aria-label="在右侧引用生成"]');
  await port.fire('pointerdown', {button: 0, clientX: 12, clientY: 24});
  await f.window.fire('pointermove', {clientX: 48, clientY: 30, target: port, button: 0});
  assert.equal(f.root.querySelector('.a1-preview').getAttribute('stroke'), '#3ddc97');
  const before = f.timeouts.length;
  await f.window.fire('pointerup', {clientX: 200, clientY: 80, target: cardOf(f.root, 'i'), button: 0});
  const saved = draft(f.store);
  assert.equal(saved.edges.length, 1);
  assert.deepEqual(Object.keys(saved.edges[0]).sort(), ['id', 'port', 'source', 'target']);
  assert.equal(saved.edges[0].source, 't');
  assert.equal(saved.edges[0].target, 'i');
  assert.equal(saved.edges[0].port, 'prompt');
  const timer = f.timeouts.slice(before).find(item => item.delay === 1000);
  assert.ok(timer);
  timer.fn();
  await new Promise(resolve => setTimeout(resolve, 50));
  const put = f.canvasCalls.filter(call => call.method === 'PUT').at(-1);
  assert.equal(put.body.payload.document.edges[0].source, 't');
  assert.equal(put.body.payload.document.edges[0].target, 'i');
  assert.equal(put.body.payload.document.edges[0].port, 'prompt');
  f.panel.suspend();

  const blank = await openCanvas({nodes: [node('t', 'text', {x: 100, y: 40, text: '从这里长出图片'})]});
  const drop = blank.root.ownerDocument.createElement('div');
  blank.root.append(drop);
  await dragPort(blank.window, cardOf(blank.root, 't').querySelector('[aria-label="在右侧引用生成"]'), drop, {x: 180, y: 200});
  const menu = blank.root.querySelector('.a1-menu');
  assert.equal(menu.querySelector('h3').textContent, '添加节点');
  assert.equal(menu.style.left, '180px');
  await menu.querySelectorAll('button').find(button => button.textContent === '图片').fire('click');
  const created = draft(blank.store);
  assert.equal(created.nodes.length, 2);
  const added = created.nodes.find(item => item.id !== 't');
  assert.equal(added.type, 'image');
  assert.equal(added.title, '图片');
  assert.equal(added.x, 100);
  assert.equal(added.y, 152);
  assert.equal(created.edges[0].source, 't');
  assert.equal(created.edges[0].target, added.id);
  assert.equal(created.edges[0].port, 'prompt');
  blank.panel.suspend();
});

test('an incompatible drop names the reference rejection and does not save an edge', async () => {
  const f = await openCanvas({nodes: [node('img', 'image', {x: 40, y: 40}), node('txt', 'text', {x: 400, y: 40, text: '不能接图片'})]});
  await dragPort(f.window, cardOf(f.root, 'img').querySelector('[aria-label="在右侧引用生成"]'), cardOf(f.root, 'txt'));
  assert.equal(statusOf(f.root), '当前目标节点不支持添加输入连接');
  assert.equal(draft(f.store), null);
  assert.equal(f.root.querySelectorAll('.cc-connections path').length, 0);
  f.panel.suspend();
});

test('double clicking a title renames through the existing draft and rejects an empty title', async () => {
  const f = await openCanvas({nodes: [node('t', 'text', {title: '原标题', text: '已有正文', x: 80, y: 40})]});
  let head = cardOf(f.root, 't').querySelector('.cc-node-head');
  await head.fire('click');
  head = cardOf(f.root, 't').querySelector('.cc-node-head');
  await head.fire('click');
  const field = f.root.querySelector('.a1-rename');
  assert.equal(field.value, '原标题');
  field.value = '新标题';
  await field.fire('keydown', {key: 'Enter'});
  assert.equal(draft(f.store).nodes[0].title, '新标题');
  head = cardOf(f.root, 't').querySelector('.cc-node-head');
  await head.fire('click');
  head = cardOf(f.root, 't').querySelector('.cc-node-head');
  await head.fire('click');
  const again = f.root.querySelector('.a1-rename');
  again.value = '   ';
  await again.fire('keydown', {key: 'Enter'});
  assert.equal(statusOf(f.root), '节点标题不能为空');
  assert.equal(draft(f.store).nodes[0].title, '新标题');
  f.panel.suspend();
});

test('result paging keeps the job and set-as-primary records the shown media', async () => {
  const f = await openCanvas({
    nodes: [node('img', 'image', {title: '原结果', media_id: 'm1', job_id: 'j1'})],
    jobs: {img: {id: 'j1', outputs: [{media_id: 'm1'}, {media_id: 'm2'}, {media_id: 'm3'}]}},
  });
  const card = cardOf(f.root, 'img');
  assert.equal(card.querySelectorAll('button').some(button => button.textContent === '上一结果'), true);
  assert.equal(card.querySelectorAll('button').some(button => button.textContent === '下一结果'), true);
  assert.equal(card.textContent.includes('1/3'), true);
  assert.equal(card.textContent.includes('3张'), true);
  await card.querySelectorAll('button').find(button => button.textContent === '下一结果').fire('click');
  assert.equal(draft(f.store).nodes[0].media_id, 'm2');
  assert.equal(draft(f.store).nodes[0].job_id, 'j1');
  assert.equal(cardOf(f.root, 'img').textContent.includes('2/3'), true);
  await cardOf(f.root, 'img').querySelectorAll('button').find(button => button.textContent === '设为主图').fire('click');
  const saved = draft(f.store).nodes[0];
  assert.equal(saved.media_id, 'm2');
  assert.equal(saved.params.primary_media_id, 'm2');
  assert.equal(saved.job_id, 'j1');
  assert.equal(f.canvasCalls.some(call => call.path.endsWith('/generate')), false);
  f.panel.suspend();
});

test('a fixed reference edge stays and an ordinary edge can still be removed', async () => {
  const f = await openCanvas({
    nodes: [node('t', 'text', {text: '来源'}), node('i', 'image', {x: 360, media_id: 'm1'})],
    edges: [
      {id: 'e-ok', source: 't', target: 'i', port: 'prompt'},
      {id: 'e-fixed', source: 't', target: 'i', port: 'derived_from'},
    ],
  });
  const path = id => f.root.querySelectorAll('path').find(item => item.getAttribute('data-edge-id') === id);
  await path('e-ok').fire('click');
  assert.deepEqual(draft(f.store).edges.map(edge => edge.id), ['e-fixed']);
  await path('e-fixed').fire('click');
  assert.equal(statusOf(f.root), '固定引用连线不可删除');
  assert.deepEqual(draft(f.store).edges.map(edge => edge.id), ['e-fixed']);
  f.panel.suspend();
});

test('a selection drag connects only compatible nodes and outgoing edges can move to the same type', async () => {
  const f = await openCanvas({nodes: [
    node('t', 'text', {x: 40, y: 40, text: '文本'}),
    node('a', 'audio', {x: 40, y: 360}),
    node('i', 'image', {x: 460, y: 180, media_id: 'm1'}),
  ]});
  await cardOf(f.root, 't').querySelector('.cc-node-head').fire('click');
  await cardOf(f.root, 'a').querySelector('.cc-node-head').fire('click', {shiftKey: true});
  const batch = f.root.querySelector('[aria-label="批量连接"]');
  assert.equal(batch.textContent, '＋');
  assert.equal(f.root.querySelectorAll('button').some(button => button.textContent === '打包下载'), true);
  await dragPort(f.window, batch, cardOf(f.root, 'i'));
  const saved = draft(f.store);
  assert.equal(saved.edges.length, 1);
  assert.equal(saved.edges[0].source, 't');
  assert.equal(saved.edges[0].target, 'i');
  assert.equal(saved.edges[0].port, 'prompt');
  assert.equal(statusOf(f.root), '当前目标节点不支持连接音频节点');
  f.panel.suspend();

  const move = await openCanvas({
    nodes: [node('s', 'image', {title: '旧源', media_id: 's1'}), node('o', 'image', {title: '新源', x: 280, media_id: 's2'}), node('d', 'image', {title: '下游', x: 560, media_id: 's3'})],
    edges: [{id: 'keep', source: 's', target: 'd', port: 'reference'}],
  });
  await cardOf(move.root, 's').querySelectorAll('button').find(button => button.textContent === '迁移出边').fire('click');
  assert.equal(move.root.querySelector('.a1-menu').querySelector('h3').textContent, '迁移出边');
  await move.root.querySelector('.a1-menu').querySelectorAll('button').find(button => button.textContent === '新源').fire('click');
  assert.deepEqual(draft(move.store).edges[0], {id: 'keep', source: 'o', target: 'd', port: 'reference'});
  move.panel.suspend();
});

function includesBytes(haystack, needle) {
  const limit = haystack.length - needle.length;
  for (let index = 0; index <= limit; index += 1) {
    let matched = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[index + offset] !== needle[offset]) { matched = false; break; }
    }
    if (matched) return true;
  }
  return false;
}

test('a multi-selection zip stores fetched media bytes and falls back to text', async () => {
  const png = Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0xa1, 0x01);
  const jpeg = Uint8Array.of(0xff, 0xd8, 0xff, 0xe0, 0xa1, 0x02);
  const webp = Uint8Array.of(0x52, 0x49, 0x46, 0x46, 0xa1, 0x03, 0x57, 0x45, 0x42, 0x50);
  const mp4 = Uint8Array.of(0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0xa1, 0x04);
  const mp3 = Uint8Array.of(0x49, 0x44, 0x33, 0xa1, 0x05);
  const wav = Uint8Array.of(0x52, 0x49, 0x46, 0x46, 0xa1, 0x06, 0x57, 0x41, 0x56, 0x45);
  const files = new Map([
    ['/api/v1/projects/p1/media/pic/content', ['image/png', png]],
    ['/api/v1/projects/p1/media/still/content', ['image/jpeg', jpeg]],
    ['/api/v1/projects/p1/media/frame/content', ['image/webp', webp]],
    ['/api/v1/projects/p1/media/clip/content', ['video/mp4', mp4]],
    ['/api/v1/projects/p1/media/song/content', ['audio/mpeg', mp3]],
    ['/api/v1/projects/p1/media/voice/content', ['audio/wav; charset=binary', wav]],
  ]);
  const seen = [];
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    seen.push({url: String(url), credentials: options?.credentials || ''});
    const row = files.get(String(url));
    if (!row) return {ok: false, status: 404, headers: {get() { return null; }}, arrayBuffer: async () => new ArrayBuffer(0)};
    const bytes = row[1];
    return {
      ok: true,
      headers: {get(name) { return String(name).toLowerCase() === 'content-type' ? row[0] : null; }},
      arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    };
  };
  const blobs = [];
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = blob => { blobs.push(blob); return 'blob:a1-zip'; };
  URL.revokeObjectURL = () => {};
  const f = await openCanvas({nodes: [
    node('shot', 'image', {title: '街景', media_id: 'pic'}),
    node('still', 'image', {title: '静帧', x: 280, media_id: 'still'}),
    node('frame', 'image', {title: '网页图', x: 560, media_id: 'frame'}),
    node('clip', 'video', {title: '镜头', x: 840, media_id: 'clip'}),
    node('song', 'audio', {title: '歌曲', y: 200, media_id: 'song'}),
    node('voice', 'audio', {title: '人声', x: 280, y: 200, media_id: 'voice'}),
    node('line', 'text', {title: '旁白', x: 560, y: 200, text: '一句台词'}),
    node('gone', 'image', {title: '失效图', x: 840, y: 200, media_id: 'gone-id'}),
    node('blank', 'image', {title: '空图', y: 420}),
  ]});
  try {
    const ids = ['shot', 'still', 'frame', 'clip', 'song', 'voice', 'line', 'gone', 'blank'];
    for (let index = 0; index < ids.length; index += 1) {
      await cardOf(f.root, ids[index]).querySelector('.cc-node-head').fire('click', {shiftKey: index > 0});
    }
    await f.root.querySelectorAll('button').find(button => button.textContent === '打包下载').fire('click');
    assert.deepEqual(seen.map(call => call.url), [
      '/api/v1/projects/p1/media/pic/content',
      '/api/v1/projects/p1/media/still/content',
      '/api/v1/projects/p1/media/frame/content',
      '/api/v1/projects/p1/media/clip/content',
      '/api/v1/projects/p1/media/song/content',
      '/api/v1/projects/p1/media/voice/content',
      '/api/v1/projects/p1/media/gone-id/content',
    ]);
    assert.equal(seen.every(call => call.credentials === 'same-origin'), true);
    assert.equal(f.canvasCalls.some(call => String(call.path).includes('/generate')), false);
    assert.equal(blobs.length, 1);
    const raw = new Uint8Array(await blobs[0].arrayBuffer());
    for (const [name, bytes] of [
      ['image-shot.png', png],
      ['image-still.jpg', jpeg],
      ['image-frame.webp', webp],
      ['video-clip.mp4', mp4],
      ['audio-song.mp3', mp3],
      ['audio-voice.wav', wav],
    ]) {
      assert.equal(includesBytes(raw, new TextEncoder().encode(name)), true, name);
      assert.equal(includesBytes(raw, bytes), true, name);
    }
    assert.equal(includesBytes(raw, new TextEncoder().encode('image-shot.txt')), false);
    const text = new TextDecoder().decode(raw);
    assert.equal(text.includes('text-line.txt'), true);
    assert.equal(text.includes('旁白\ntext\n一句台词\n'), true);
    assert.equal(text.includes('image-gone.txt'), true);
    assert.equal(text.includes('失效图\nimage\n\n'), true);
    assert.equal(text.includes('image-blank.txt'), true);
    assert.equal(text.includes('空图\nimage\n\n'), true);
    assert.equal(includesBytes(raw, png) && text.includes('PK\u0005\u0006'), true);
  } finally {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    globalThis.fetch = previousFetch;
    f.panel.suspend();
  }
});

test('clicking an empty image placeholder selects the node and opens upload or project media', async () => {
  const f = await openCanvas({nodes: [
    node('img', 'image', {title: '空图', x: 40, y: 40}),
    node('txt', 'text', {title: '空文本', x: 400, y: 40}),
  ]});
  try {
    assert.equal(cardOf(f.root, 'txt').querySelector('.a1-placeholder-hit'), null);
    await cardOf(f.root, 'img').fire('click', {target: cardOf(f.root, 'img')});
    assert.equal(cardOf(f.root, 'img').classList.contains('selected'), true);
    assert.equal(f.root.querySelector('.a1-menu'), null);
    const hit = cardOf(f.root, 'img').querySelector('.a1-placeholder-hit');
    assert.equal(hit.getAttribute('aria-label'), '上传或选择素材');
    assert.ok(hit.querySelector('svg'));
    await hit.fire('click', {target: hit});
    assert.equal(cardOf(f.root, 'img').classList.contains('selected'), true);
    const menu = f.root.querySelector('.a1-menu');
    assert.equal(menu.querySelector('h3').textContent, '添加素材');
    const upload = menu.querySelectorAll('button').find(button => button.textContent === '本地上传');
    const pick = menu.querySelectorAll('button').find(button => button.textContent === '从项目素材选择');
    assert.ok(upload);
    assert.ok(pick);
    await pick.fire('click');
    assert.equal(f.canvasCalls.some(call => call.path === '/api/v1/projects/p1/media?modality=image&limit=24&offset=0'), true);
    assert.ok(f.root.querySelector('.cc-picker'));
    assert.equal(f.canvasCalls.some(call => String(call.path).includes('/generate')), false);
    await cardOf(f.root, 'img').querySelector('.a1-placeholder-hit').fire('click');
    await f.root.querySelector('.a1-menu').querySelectorAll('button').find(button => button.textContent === '本地上传').fire('click');
    assert.equal(f.root.querySelector('.cc-assets').querySelector('h2').textContent, '上传资源');
    const textCard = cardOf(f.root, 'txt');
    await textCard.fire('click', {target: textCard});
    assert.equal(cardOf(f.root, 'txt').classList.contains('selected'), true);
    assert.equal(cardOf(f.root, 'img').classList.contains('selected'), false);
  } finally {
    f.panel.suspend();
  }
});
