import crypto from 'node:crypto';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {catalogueFor} from '../../support/fixtures/frontend/canvas_capabilities.cjs';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

const ROOT = new URL('../../../', import.meta.url);

test('arrange profile, shortcut dispatch and leave reasons use the reference contract', async () => {
  const shortcuts = await loadModule('canvas-shortcuts.js');
  const css = fs.readFileSync(new URL('./src/vsc/interfaces/web/static/canvas-shell-chrome.css', ROOT), 'utf8');
  const html = fs.readFileSync(new URL('./src/vsc/interfaces/web/templates/index.html', ROOT), 'utf8');
  assert.match(html, /\/static\/canvas-shell-chrome\.css/);
  assert.match(css, /\.production-context\.cc-shell-selectors select\{[^}]*appearance:\s*none/);
  assert.match(css, /stroke='%23a1a0a3'/);
  assert.match(css, /\.cc-shell-save-hidden\{display:\s*none\s*!important\}/);
  assert.match(css, /\.cc-editor \.cc-toolbar\{justify-content:\s*flex-end\}/);
  assert.match(css, /\.cc-editor \.cc-shell-overlay\{[^}]*position:\s*static/);
  assert.doesNotMatch(css, /\.cc-editor \.cc-shell-overlay\{[^}]*position:\s*absolute/);
  assert.match(css, /\.cc-shell-overlay \.cc-shell-share\{[^}]*background:\s*#1d1d1d[^}]*border-radius:\s*8px[^}]*height:\s*32px/);
  assert.match(css, /\.cc-shell-overlay \.cc-agent-toggle\{[^}]*background:\s*#fdfbfc/);

  const groups = globalThis.VSC_CANVAS_SHORTCUTS;
  assert.equal(groups, shortcuts.VSC_CANVAS_SHORTCUTS);
  assert.equal(Array.isArray(groups) && groups.length, 4);
  assert.deepEqual(groups.map(group => group.id), ['creation', 'zoom', 'pan', 'other']);
  for (const group of groups) {
    assert.equal(typeof group.title, 'string');
    assert.ok(group.title);
    assert.ok(group.items.length);
    for (const entry of group.items) {
      assert.equal(typeof entry.id, 'string');
      assert.equal(typeof entry.label, 'string');
      assert.ok(entry.keys.length);
    }
  }
  const caps = id => groups.flatMap(group => group.items).find(entry => entry.id === id).keys;
  assert.deepEqual(caps('group'), [{text: 'G'}]);
  assert.deepEqual(caps('connect'), [{text: 'L'}]);
  assert.deepEqual(caps('duplicate'), [{text: 'D'}]);
  assert.deepEqual(caps('add'), [{text: 'Tab'}]);
  assert.deepEqual(caps('fit'), [{text: '0'}]);
  assert.deepEqual(caps('select'), [{text: 'V'}]);
  assert.deepEqual(caps('hand'), [{text: 'H'}]);
  assert.deepEqual(caps('undo'), [{mod: true}, {text: 'Z'}]);
  assert.deepEqual(caps('search'), [{text: 'F'}]);
  assert.equal(shortcuts.SHORTCUT_CATALOG.length > 0, true);

  const vertical = shortcuts.arrangeNodes([
    {id: 'a', x: 9, y: 9, params: {}},
    {id: 'e', x: 77, y: 88, params: {layout: 'explicit'}},
    {id: 'b', x: 3, y: 4, params: {}},
  ], 'vertical');
  assert.deepEqual(vertical.positions, [
    {id: 'a', x: 40, y: 40},
    {id: 'e', x: 77, y: 88},
    {id: 'b', x: 40, y: 160},
  ]);

  const regions = shortcuts.arrangeNodes([
    {id: 'c0', type: 'image', x: 12, y: 18, params: {asset_kind: 'character'}},
    {id: 'c1', type: 'image', x: 500, y: 18, params: {asset_kind: 'character'}},
    {id: 's', type: 'image', x: 12, y: 400, params: {asset_kind: 'scene'}},
    {id: 'o', type: 'text', x: 800, y: 18, text: '', params: {}},
    {id: 'e', type: 'image', x: 77, y: 88, params: {layout_strategy: 'explicit'}},
  ], 'asset_region');
  assert.equal(regions.strategy, 'asset_region');
  assert.deepEqual(regions.positions, [
    {id: 'c0', x: 40, y: 40},
    {id: 'c1', x: 360, y: 40},
    {id: 's', x: 40, y: 260},
    {id: 'o', x: 40, y: 480},
    {id: 'e', x: 77, y: 88},
  ]);

  const wrapped = shortcuts.arrangeNodes(
    Array.from({length: 7}, (_, index) => ({id: 'c' + index, type: 'image', x: 1, y: 1, params: {asset_kind: 'character'}})),
    'asset_region',
  );
  assert.deepEqual(wrapped.positions[6], {id: 'c6', x: 40, y: 140});

  const locked = shortcuts.arrangeNodes([
    {id: 'g', type: 'text', x: 9, y: 11, params: {canvas_subkind: 'group_frame', group_locked: true}},
    {id: 'c', type: 'image', x: 1, y: 1, params: {asset_kind: 'character'}},
  ], 'asset_region');
  assert.deepEqual(locked.positions, [
    {id: 'g', x: 9, y: 11},
    {id: 'c', x: 40, y: 40},
  ]);

  const unlockedFrame = shortcuts.arrangeNodes([
    {id: 'c', type: 'image', x: 1, y: 1, params: {asset_kind: 'character'}},
    {id: 'g', type: 'text', x: 9, y: 11, params: {canvas_subkind: 'group_frame', group_locked: false}},
  ], 'asset_region');
  assert.deepEqual(unlockedFrame.positions, [
    {id: 'c', x: 40, y: 40},
    {id: 'g', x: 40, y: 260},
  ]);

  const mac = {platform: 'mac'};
  const other = {platform: 'other'};
  const key = (extra) => ({key: '', code: '', ...extra});
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ'}), mac), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ'}), other), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'g', code: 'KeyG', target: {tagName: 'INPUT'}}), mac), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'Enter', target: {tagName: 'TEXTAREA'}}), mac), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'Delete', target: {tagName: 'SELECT'}}), other), null);
  assert.equal(shortcuts.isTypingTarget({tagName: 'DIV', isContentEditable: true}), true);
  assert.equal(shortcuts.shortcutAction(key({key: 'g', code: 'KeyG'}), mac), 'group');
  assert.equal(shortcuts.shortcutAction(key({key: 'g', code: 'KeyG', altKey: true}), mac), 'merge-storyboard');
  assert.equal(shortcuts.shortcutAction(key({key: 'g', code: 'KeyG', shiftKey: true}), mac), 'ungroup');
  assert.equal(shortcuts.shortcutAction(key({key: 'l', code: 'KeyL'}), mac), 'connect');
  assert.equal(shortcuts.shortcutAction(key({key: 'd', code: 'KeyD'}), mac), 'duplicate');
  assert.equal(shortcuts.shortcutAction(key({key: 'd', code: 'KeyD', metaKey: true}), mac), 'duplicate');
  assert.equal(shortcuts.shortcutAction(key({key: 'd', code: 'KeyD', ctrlKey: true}), other), 'duplicate');
  assert.equal(shortcuts.shortcutAction(key({key: 'Enter'}), mac), 'generate');
  assert.equal(shortcuts.shortcutAction(key({key: 'Tab'}), mac), 'add-node');
  assert.equal(shortcuts.shortcutAction(key({key: '0', code: 'Digit0'}), mac), 'fit');
  assert.equal(shortcuts.shortcutAction(key({key: '0', code: 'Digit0', metaKey: true}), mac), 'fit');
  assert.equal(shortcuts.shortcutAction(key({key: '0', code: 'Digit0', ctrlKey: true}), other), 'fit');
  assert.equal(shortcuts.shortcutAction(key({key: 'v', code: 'KeyV'}), mac), 'move');
  assert.equal(shortcuts.shortcutAction(key({key: 'h', code: 'KeyH'}), mac), 'hand');
  assert.equal(shortcuts.shortcutAction(key({key: 'f', code: 'KeyF', altKey: true, shiftKey: true}), mac), 'arrange');
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', metaKey: true}), mac), 'undo');
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', metaKey: true, shiftKey: true}), mac), 'redo');
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', ctrlKey: true}), other), 'undo');
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', ctrlKey: true, shiftKey: true}), other), 'redo');
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', ctrlKey: true}), mac), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'z', code: 'KeyZ', metaKey: true}), other), null);
  assert.equal(shortcuts.shortcutAction(key({key: 'f', code: 'KeyF'}), mac), 'search');
  assert.equal(shortcuts.shortcutAction(key({key: 'Delete'}), mac), 'delete');
  assert.equal(shortcuts.shortcutAction(key({key: 'Backspace'}), mac), 'delete');
  assert.equal(shortcuts.shortcutAction(key({key: ' ', code: 'Space'}), mac), 'space');

  assert.equal(shortcuts.uploadsIncomplete([{current: {items: [{status: 'awaiting_upload'}]}}]), true);
  assert.equal(shortcuts.uploadsIncomplete([{current: {items: [{status: 'complete'}]}}]), false);
  assert.equal(shortcuts.leaveReason({uploadIncomplete: true, dirty: true}), 'upload');
  assert.equal(shortcuts.leaveReason({syncBlocked: true}), 'unprotected');
  assert.equal(shortcuts.leaveReason({arrangePending: true}), 'draft');
  assert.equal(shortcuts.leaveReason({dirty: true}), 'draft');
  assert.equal(shortcuts.leaveReason({}), '');

  const connected = {nodes: [
    {id: 'o', type: 'text', x: 1, y: 1, text: '', params: {}, group: ''},
    {id: 'e', type: 'image', x: 2, y: 2, text: '', params: {}, group: ''},
  ], edges: []};
  const link = shortcuts.connectSelection(connected, new Set(['o', 'e']), () => 'edge-1');
  assert.equal(link.ok, true);
  assert.equal(link.port, 'prompt');
  assert.deepEqual(connected.edges, [{id: 'edge-1', source: 'o', target: 'e', port: 'prompt'}]);
});

class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.value = '';
    this.style = {removeProperty(k) { delete this[k]; }};
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
      add: (...v) => { this.className = [...new Set([...this.className.split(' '), ...v])].filter(Boolean).join(' '); },
      contains: v => this.className.split(' ').includes(v),
      remove: (...v) => { this.className = this.className.split(' ').filter(x => !v.includes(x)).join(' '); },
    };
  }
  set textContent(v) { this._text = String(v ?? ''); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentElement = this; this.children.push(node); } }
  prepend(...nodes) { for (const node of nodes.reverse()) { node.remove(); node.parentElement = this; this.children.unshift(node); } }
  remove() { if (this.parentElement) { this.parentElement.children = this.parentElement.children.filter(x => x !== this); this.parentElement = null; } }
  replaceChildren(...nodes) { for (const c of [...this.children]) c.remove(); this._text = ''; this.append(...nodes); }
  insertBefore(node, before) { node.remove(); node.parentElement = this; const i = this.children.indexOf(before); this.children.splice(i < 0 ? this.children.length : i, 0, node); }
  removeAttribute(k) { delete this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  matches(selector) {
    if (selector[0] === '.') return this.classList.contains(selector.slice(1));
    if (selector[0] === '[') {
      const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return match && (match[2] == null ? this.attrs[match[1]] != null : this.attrs[match[1]] === match[2]);
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    if (selector.startsWith(':scope > ')) return this.children.filter(c => c.matches(selector.slice(9)));
    const values = this.children.flatMap(c => [c, ...c.querySelectorAll('*')]);
    if (selector === '*') return values;
    return values.filter(c => selector.split(',').some(x => c.matches(x.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (selector.split(',').some(part => node.matches(part.trim()))) return node;
    }
    return null;
  }
  getBoundingClientRect() { return {left: 0, top: 0, width: 400, height: 300}; }
  addEventListener(k, v) { (this.listeners[k] ??= []).push(v); }
  get options() { return this.children.filter(x => x.tagName === 'OPTION'); }
  get isConnected() { return this.parentElement !== null; }
  async fire(type, properties = {}) {
    const event = {target: this, preventDefault() {}, stopPropagation() {}, ...properties};
    if (this['on' + type]) await this['on' + type](event);
    for (const f of this.listeners[type] || []) await f(event);
    if (['input', 'change'].includes(type) && this.parentElement) await this.parentElement.fire(type, {...properties, target: event.target});
  }
  focus() { this.ownerDocument.activeElement = this; }
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; return this.fire('close'); }
  get selectedOptions() { return this.options.filter(node => node.selected || (node.value === this.value && !this.multiple)); }
}

function node(id, type, x, y, params = {}, text = '') {
  return {id, type, title: id, x, y, text, params, media_id: null, job_id: null, group: ''};
}

async function createCanvasFixture({nodes = [], edges = [], episode = null} = {}) {
  const store = new Map();
  const canvasCalls = [];
  const document = {
    createElement: t => {
      const n = new Element(t);
      n.ownerDocument = document;
      if (t === 'canvas') n.getContext = () => ({clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, drawImage() {}, getImageData() { return {data: new Uint8ClampedArray(32)}; }});
      return n;
    },
    createElementNS: (ns, t) => { const n = document.createElement(t); n.namespaceURI = ns; return n; },
    createTextNode: text => { const n = new Element('#text', text); n.ownerDocument = document; return n; },
    documentElement: {},
  };
  const production = document.createElement('div');
  document.getElementById = id => id === 'production-context' ? production : null;
  const sessionStorage = {getItem: k => store.get(k) || null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)};
  const winListeners = new Map();
  const window = {
    addEventListener(type, fn) { (winListeners.get(type) || winListeners.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { winListeners.get(type)?.delete(fn); },
    fire(type, event = {}) { for (const fn of [...(winListeners.get(type) || [])]) fn(event); },
  };
  const timeouts = [];
  const mod = await loadModule('creative-canvas.js', {
    document, window, sessionStorage, crypto, console,
    location: {search: '', href: 'http://127.0.0.1:8765/canvas', assign() {}},
    Image: class FakeImage {},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
    fetch: async () => ({ok: true, text: async () => ''}),
    setTimeout: (fn, delay) => { if (delay === 0) return setTimeout(fn, 0); timeouts.push({fn, delay}); return timeouts.length; },
    clearTimeout: () => {},
  });
  const root = document.createElement('main');
  let dbVersion = 1;
  let dbDoc = structuredClone({viewport: {x: 0, y: 0, zoom: 1}, nodes, edges});
  const accessCalls = [];
  const ctx = {
    session: () => ({actor: 'test', csrf: 'csrf-1', revision: 1, writable: true}),
    setRevision() {},
    opened() {},
    navigateAccess(value) { accessCalls.push(value); },
    api: async (path, options) => {
      canvasCalls.push({path, method: options?.method || 'GET', body: options?.body ? JSON.parse(options.body) : null});
      if (path === '/api/v1/projects/p1/creative-canvases/c1') {
        if (options?.method === 'PUT') {
          const body = JSON.parse(options.body);
          dbDoc = structuredClone(body.payload.document);
          dbVersion += 1;
          return {revision: dbVersion, canvas_revision: dbVersion, title: body.payload.title};
        }
        return {revision: dbVersion, canvas_revision: dbVersion, title: 'Canvas Shell', episode_id: episode, document: structuredClone(dbDoc), jobs: {}, runs: [], execution_steps: []};
      }
      if (path.endsWith('/creative-canvas-run-options')) {
        return {...catalogueFor([{id: 'img-m1', enabled: true, modality: 'image', model_key: 'seedream', model_version: '4.0', capabilities: {purposes: ['image_edit']}}]), revision: dbVersion, nodes: [], models: [], image_tools: {}};
      }
      if (path.endsWith('/history')) return {revision: dbVersion, items: []};
      if (path.endsWith('/creative-canvas-agent-options')) return {revision: dbVersion, host_available: false, skills: [], models: [], nodes: []};
      return {items: [], revision: dbVersion};
    },
  };
  const panel = mod.createCreativeCanvasPanel(ctx);
  await panel.load(root, 'p1', null, 'c1');
  return {root, panel, store, canvasCalls, timeouts, window, production, accessCalls, getDoc: () => dbDoc};
}

function draftDocument(store) {
  const key = [...store.keys()].find(item => String(item).startsWith('vsc-creative-canvas:v2:'));
  return key ? JSON.parse(store.get(key)).document : null;
}

function latestPut(calls) {
  return [...calls].reverse().find(call => call.method === 'PUT' && call.path === '/api/v1/projects/p1/creative-canvases/c1');
}

async function flushSaves(timeouts) {
  for (let round = 0; round < 6; round += 1) {
    const batch = timeouts.splice(0, timeouts.length);
    if (!batch.length) {
      await new Promise(resolve => setImmediate(resolve));
      if (!timeouts.length) return;
      continue;
    }
    for (const item of batch) item.fn();
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
  }
}

function card(root, id) {
  return [...root.querySelectorAll('.cc-node')].find(item => item.dataset.nodeId === id);
}

function press(root, props) {
  return root.querySelector('.cc-stage').fire('keydown', props);
}

function placed(root, id) {
  const item = card(root, id);
  return {left: item.style.left, top: item.style.top};
}

test('shell chrome, shortcuts, arrange confirm and autosave paths', async () => {
  const nodes = [
    node('c0', 'image', 12, 18, {asset_kind: 'character'}),
    node('c1', 'image', 500, 18, {asset_kind: 'character'}),
    node('s', 'image', 12, 400, {asset_kind: 'scene'}),
    node('o', 'text', 800, 18, {}, '旧提示'),
    node('e', 'image', 77, 88, {layout_strategy: 'explicit'}),
  ];
  const f = await createCanvasFixture({nodes, edges: []});
  try {
    assert.equal(f.production.classList.contains('cc-shell-selectors'), true);
    const empty = f.root.querySelector('.cc-empty');
    assert.equal(empty.querySelector('p').textContent, '可通过右键菜单、上传或拖入文件开始。');
    assert.equal(empty.querySelector('strong').textContent, '双击空白处新建节点');

    const zoom = f.root.querySelector('.cc-zoom');
    const barLabels = [...zoom.children]
      .filter(item => !item.classList.contains('cc-edit-menu') && !item.classList.contains('cc-shell-zoom-menu'))
      .map(item => item.getAttribute('aria-label'));
    assert.deepEqual(barLabels, ['画布小地图', '网格吸附', '隐藏连线', '缩小', '打开缩放菜单', '放大', '整理画布']);
    assert.equal([...zoom.querySelectorAll('button')].some(item => item.getAttribute('aria-label') === '撤销'), false);
    assert.equal(f.root.querySelector('.cc-more-menu').querySelector('[aria-label="撤销"]') != null, true);
    const version = f.root.querySelector('.cc-shell-version');
    assert.equal(version.parentElement.classList.contains('cc-more-menu'), true);
    assert.equal(version.textContent, '已存版本 1');
    assert.equal(f.root.querySelector('.cc-toolbar').querySelectorAll(':scope > .cc-shell-version').length, 0);
    const save = f.root.querySelector('.cc-save');
    assert.equal(save.classList.contains('cc-shell-save-hidden'), true);
    assert.equal(save.textContent, '保存画布');
    assert.equal(save.parentElement.classList.contains('cc-more-menu'), true);

    const overlay = f.root.querySelector('.cc-shell-overlay');
    assert.equal(overlay.parentElement.classList.contains('cc-toolbar'), true);
    assert.deepEqual([...overlay.children].map(item => item.className.split(' ')[0]), ['cc-collab-sync-pill', 'cc-shell-share', 'cc-agent-toggle', 'cc-more']);
    const pill = overlay.querySelector('.cc-shell-sync-fallback');
    assert.equal(pill.getAttribute('title'), '协作画布会实时同步，无需手动全量保存');
    assert.match(pill.textContent, /● 已同步/);
    const shareButton = overlay.querySelector('.cc-shell-share');
    assert.equal(shareButton.textContent, '分享');
    assert.equal(shareButton.getAttribute('aria-label'), '分享');
    assert.equal(overlay.querySelector('.cc-agent-toggle').textContent, 'Agent');
    assert.equal(overlay.querySelector('.cc-more') != null, true);
    assert.equal(f.root.querySelector('.cc-shell-new-canvas').textContent, '新建画布');
    assert.equal(f.root.querySelector('.cc-shell-rename-canvas').textContent, '重命名画布');
    await f.root.querySelector('.cc-shell-rename-canvas').fire('click');
    const rename = f.root.querySelector('.cc-selector-inline-rename');
    assert.ok(rename);
    await rename.fire('blur');
    assert.equal(f.root.querySelector('.cc-selector-inline-rename'), null);

    const snap = f.root.querySelector('.cc-snap-toggle');
    assert.equal(snap.getAttribute('aria-pressed'), 'true');
    assert.equal(snap.getAttribute('title'), '网格吸附');
    const edges = f.root.querySelector('.cc-edge-toggle');
    assert.equal(edges.getAttribute('aria-pressed'), 'false');
    assert.equal(edges.getAttribute('title'), '点击可显示/隐藏画布上的连线');
    await edges.fire('click');
    assert.equal(edges.getAttribute('aria-pressed'), 'true');
    assert.equal(edges.getAttribute('aria-label'), '显示连线');

    assert.equal(draftDocument(f.store), null);
    assert.equal(f.getDoc().nodes.find(item => item.id === 'c0').x, 12);
    await f.root.querySelector('.cc-autolayout-btn').fire('click');
    assert.deepEqual(placed(f.root, 'c0'), {left: '120px', top: '88px'});
    assert.deepEqual(placed(f.root, 'c1'), {left: '440px', top: '88px'});
    assert.deepEqual(placed(f.root, 's'), {left: '120px', top: '308px'});
    assert.deepEqual(placed(f.root, 'o'), {left: '120px', top: '528px'});
    assert.deepEqual(placed(f.root, 'e'), {left: '157px', top: '136px'});
    assert.equal(f.root.querySelector('.cc-shell-arrange-dialog').textContent.includes('是否保留此次整理结果？'), true);
    assert.equal(draftDocument(f.store), null);
    assert.equal(f.getDoc().nodes.find(item => item.id === 'c0').x, 12);
    await f.root.querySelector('.cc-shell-arrange-revert').fire('click');
    assert.deepEqual(placed(f.root, 'c0'), {left: '92px', top: '66px'});
    assert.deepEqual(placed(f.root, 'e'), {left: '157px', top: '136px'});
    assert.equal(f.getDoc().nodes.find(item => item.id === 'o').x, 800);

    await press(f.root, {key: 'f', code: 'KeyF', altKey: true, shiftKey: true});
    await f.root.querySelector('.cc-shell-arrange-keep').fire('click');
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c0').x, 40);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c1').y, 40);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 's').y, 260);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'o').y, 480);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'e').x, 77);
    assert.match(f.root.querySelector('.cc-shell-sync-fallback').textContent, /同步中/);
    await flushSaves(f.timeouts);
    const arranged = latestPut(f.canvasCalls).body.payload.document.nodes;
    assert.deepEqual(arranged.map(item => ({id: item.id, x: item.x, y: item.y})), [
      {id: 'c0', x: 40, y: 40},
      {id: 'c1', x: 360, y: 40},
      {id: 's', x: 40, y: 260},
      {id: 'o', x: 40, y: 480},
      {id: 'e', x: 77, y: 88},
    ]);
    assert.equal(f.getDoc().nodes.find(item => item.id === 's').y, 260);
    assert.equal(draftDocument(f.store), null);
    assert.match(f.root.querySelector('.cc-shell-sync-fallback').textContent, /● 已同步/);

    await card(f.root, 'o').fire('click', {target: card(f.root, 'o')});
    const prompt = f.root.querySelector('[aria-label="文本或提示词"]');
    prompt.value = '雨夜新提示';
    await prompt.fire('change');
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'o').text, '雨夜新提示');
    const leaving = {preventDefault() {}, returnValue: ''};
    f.window.fire('beforeunload', leaving);
    assert.equal(leaving.returnValue, '还有内容未保存，离开后将丢失。确定离开吗？');
    await flushSaves(f.timeouts);
    assert.equal(latestPut(f.canvasCalls).body.payload.document.nodes.find(item => item.id === 'o').text, '雨夜新提示');
    assert.equal(f.getDoc().nodes.find(item => item.id === 'o').text, '雨夜新提示');
    const stayed = {preventDefault() {}, returnValue: ''};
    f.window.fire('beforeunload', stayed);
    assert.equal(stayed.returnValue, '');

    await card(f.root, 'o').fire('click', {target: card(f.root, 'o')});
    await card(f.root, 'e').fire('click', {target: card(f.root, 'e'), shiftKey: true});
    await press(f.root, {key: 'l', code: 'KeyL'});
    assert.equal(draftDocument(f.store).edges.some(edge => edge.source === 'o' && edge.target === 'e' && edge.port === 'prompt'), true);
    await flushSaves(f.timeouts);
    assert.equal(latestPut(f.canvasCalls).body.payload.document.edges.some(edge => edge.source === 'o' && edge.target === 'e' && edge.port === 'prompt'), true);

    const beforeAdd = f.getDoc().nodes.length;
    await press(f.root, {key: 'Tab', code: 'Tab'});
    const added = draftDocument(f.store).nodes.find(item => !nodes.some(original => original.id === item.id));
    assert.equal(added.type, 'text');
    assert.equal(added.title, '文本');
    await flushSaves(f.timeouts);
    assert.equal(f.getDoc().nodes.length, beforeAdd + 1);
    await press(f.root, {key: 'Delete', code: 'Delete'});
    await flushSaves(f.timeouts);
    assert.equal(f.getDoc().nodes.some(item => item.id === added.id), false);

    const head = card(f.root, 'c0').querySelector('.cc-node-head');
    await head.fire('pointerdown', {button: 0, clientX: 100, clientY: 100});
    f.window.fire('pointermove', {button: 0, clientX: 136, clientY: 100});
    f.window.fire('pointerup', {button: 0, clientX: 136, clientY: 100});
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c0').x, 80);
    await flushSaves(f.timeouts);
    assert.equal(latestPut(f.canvasCalls).body.payload.document.nodes.find(item => item.id === 'c0').x, 80);
    assert.equal(f.getDoc().nodes.find(item => item.id === 'c0').x, 80);

    await card(f.root, 'c0').fire('click', {target: card(f.root, 'c0')});
    await card(f.root, 'c1').fire('click', {target: card(f.root, 'c1'), shiftKey: true});
    await press(f.root, {key: 'g', code: 'KeyG'});
    const grouped = draftDocument(f.store);
    assert.equal(grouped.nodes.find(item => item.id === 'c0').group, '分组 1');
    assert.equal(grouped.nodes.some(item => item.params?.canvas_subkind === 'group_frame'), true);
    await press(f.root, {key: 'g', code: 'KeyG', shiftKey: true});
    const ungrouped = draftDocument(f.store);
    assert.equal(ungrouped.nodes.find(item => item.id === 'c0').group, '');
    assert.equal(ungrouped.nodes.some(item => item.params?.canvas_subkind === 'group_frame'), false);
    await flushSaves(f.timeouts);

    await card(f.root, 'c0').fire('click', {target: card(f.root, 'c0')});
    await card(f.root, 'c1').fire('click', {target: card(f.root, 'c1'), shiftKey: true});
    await press(f.root, {key: 'g', code: 'KeyG', altKey: true});
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c1').group, '分镜组 1');

    await card(f.root, 'e').fire('click', {target: card(f.root, 'e')});
    await press(f.root, {key: 'd', code: 'KeyD'});
    const duplicated = draftDocument(f.store);
    const copy = duplicated.nodes.find(item => !['c0', 'c1', 's', 'o', 'e'].includes(item.id) && item.type === 'image');
    assert.ok(duplicated.edges.some(edge => edge.source === 'o' && edge.target === copy.id && edge.port === 'prompt'));
    await press(f.root, {key: 'z', code: 'KeyZ'});
    assert.equal(draftDocument(f.store).nodes.some(item => item.id === copy.id), true);
    await press(f.root, {key: 'z', code: 'KeyZ', metaKey: true});
    assert.equal(draftDocument(f.store).nodes.some(item => item.id === copy.id), false);
    await press(f.root, {key: 'z', code: 'KeyZ', metaKey: true, shiftKey: true});
    assert.equal(draftDocument(f.store).nodes.some(item => item.id === copy.id), true);
    await press(f.root, {key: 'z', code: 'KeyZ', ctrlKey: true});
    assert.equal(draftDocument(f.store).nodes.some(item => item.id === copy.id), false);

    const typing = f.root.ownerDocument.createElement('input');
    f.root.append(typing);
    await press(f.root, {key: 'g', code: 'KeyG', target: typing});
    assert.equal(draftDocument(f.store).nodes.some(item => item.params?.canvas_subkind === 'group_frame'), false);
    await card(f.root, 'o').fire('click', {target: card(f.root, 'o')});
    await press(f.root, {key: 'Backspace', target: typing});
    assert.equal(draftDocument(f.store).nodes.some(item => item.id === 'o'), true);

    let generated = 0;
    const seen = [];
    const send = f.root.ownerDocument.createElement('button');
    send.className = 'cc-generator-send';
    send.addEventListener('click', () => { generated += 1; });
    f.root.append(send);
    f.root.dispatchEvent = event => { seen.push(event.type); return true; };
    await press(f.root, {key: 'Enter', code: 'Enter'});
    assert.deepEqual(seen, ['vsc-canvas-generate']);
    assert.equal(generated, 1);
    await press(f.root, {key: 'Enter', code: 'Enter', target: typing});
    assert.equal(generated, 1);

    const preset = f.root.querySelector('.cc-zoom-preset');
    preset.value = '8';
    await preset.fire('change');
    assert.equal(f.root.querySelector('.cc-zoom').querySelector('output').textContent, '800%');
    await press(f.root, {key: '0', code: 'Digit0'});
    assert.notEqual(f.root.querySelector('.cc-zoom').querySelector('output').textContent, '800%');
    preset.value = '8';
    await preset.fire('change');
    await press(f.root, {key: '0', code: 'Digit0', metaKey: true});
    assert.notEqual(f.root.querySelector('.cc-zoom').querySelector('output').textContent, '800%');

    await press(f.root, {key: 'h', code: 'KeyH'});
    assert.equal(f.root.querySelector('.cc-stage').style.cursor, 'grab');
    await press(f.root, {key: 'v', code: 'KeyV'});
    assert.equal(f.root.querySelector('.cc-stage').style.cursor, '');
    await press(f.root, {key: 'f', code: 'KeyF'});
    assert.equal(f.root.querySelector('.cc-node-search').open, true);
    assert.equal(f.root.querySelector('.cc-node-search-input').getAttribute('aria-label'), '画布节点搜索');

    const stage = f.root.querySelector('.cc-stage');
    stage.scrollLeft = 0;
    await press(f.root, {key: ' ', code: 'Space'});
    await stage.fire('pointerdown', {button: 0, clientX: 200, clientY: 80, target: stage});
    f.window.fire('pointermove', {button: 0, clientX: 150, clientY: 80});
    f.window.fire('pointerup', {button: 0, clientX: 150, clientY: 80});
    assert.equal(stage.scrollLeft, 50);
    f.window.fire('keyup', {key: ' ', code: 'Space'});
    stage.scrollLeft = 0;
    await stage.fire('pointerdown', {button: 0, clientX: 200, clientY: 80, target: stage});
    f.window.fire('pointermove', {button: 0, clientX: 140, clientY: 80});
    f.window.fire('pointerup', {button: 0});
    assert.equal(stage.scrollLeft, 0);
    await stage.fire('pointerdown', {button: 1, clientX: 200, clientY: 80, target: stage});
    f.window.fire('pointermove', {button: 1, clientX: 120, clientY: 80});
    f.window.fire('pointerup', {button: 1});
    assert.equal(stage.scrollLeft, 80);

    const beforeClone = draftDocument(f.store)?.nodes.length || f.getDoc().nodes.length;
    const dragHead = card(f.root, 'c1').querySelector('.cc-node-head');
    await dragHead.fire('pointerdown', {button: 0, clientX: 10, clientY: 10, altKey: true});
    f.window.fire('pointermove', {button: 0, clientX: 50, clientY: 10, altKey: true});
    f.window.fire('pointerup', {button: 0, clientX: 50, clientY: 10});
    assert.equal(draftDocument(f.store).nodes.length, beforeClone + 1);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c1').x, 400);
    await press(f.root, {key: 'z', code: 'KeyZ'});
    assert.equal(draftDocument(f.store).nodes.length, beforeClone + 1);
    await press(f.root, {key: 'z', code: 'KeyZ', metaKey: true});
    assert.equal(draftDocument(f.store).nodes.filter(item => item.id === 'c1').length, 1);
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'c1').x, 360);

    await press(f.root, {key: 'a', code: 'KeyA', metaKey: true});
    const selectedCards = [...f.root.querySelectorAll('.cc-node')].filter(item => item.classList.contains('selected'));
    assert.equal(selectedCards.length, f.root.querySelectorAll('.cc-node').length);
    assert.ok(selectedCards.length >= 5);
    await f.root.querySelector('.cc-shell-shortcuts-open').fire('click');
    const help = f.root.querySelector('.cc-shell-shortcuts');
    assert.match(help.textContent, /成组/);
    assert.match(help.textContent, /⌥⇧F/);
    assert.match(help.textContent, /⌘Z \/ Ctrl\+Z/);

    await card(f.root, 'o').fire('click', {target: card(f.root, 'o')});
    const promptAgain = f.root.querySelector('[aria-label="文本或提示词"]');
    promptAgain.value = '按钮仍能保存';
    await promptAgain.fire('change');
    await f.root.querySelector('.cc-save').fire('click');
    assert.equal(latestPut(f.canvasCalls).body.payload.document.nodes.find(item => item.id === 'o').text, '按钮仍能保存');
    await flushSaves(f.timeouts);
  } finally {
    f.panel.suspend();
  }
});

test('empty canvas shows the reference guide and a clean page can leave', async () => {
  const f = await createCanvasFixture({nodes: [], edges: []});
  try {
    const empty = f.root.querySelector('.cc-empty');
    assert.equal(empty.hidden, false);
    assert.equal(empty.querySelector('strong').textContent, '双击空白处新建节点');
    assert.equal(empty.querySelector('p').textContent, '可通过右键菜单、上传或拖入文件开始。');
    const event = {preventDefault() {}, returnValue: ''};
    f.window.fire('beforeunload', event);
    assert.equal(event.returnValue, '');
    assert.equal(f.root.querySelector('.cc-minimap') != null, true);
  } finally {
    f.panel.suspend();
  }
});

test('share dialog saves first, shows the read-only link, and copies it', async () => {
  const f = await createCanvasFixture({nodes: [node('o', 'text', 10, 10, {}, '旧文案')], edges: [], episode: 'ep 9'});
  const copied = [];
  const nav = globalThis.navigator;
  const prior = Object.getOwnPropertyDescriptor(nav, 'clipboard');
  Object.defineProperty(nav, 'clipboard', {
    configurable: true,
    writable: true,
    value: {writeText: async text => { copied.push(text); }},
  });
  try {
    await card(f.root, 'o').fire('click', {target: card(f.root, 'o')});
    const prompt = f.root.querySelector('[aria-label="文本或提示词"]');
    prompt.value = '分享前先保存';
    await prompt.fire('change');
    assert.equal(draftDocument(f.store).nodes.find(item => item.id === 'o').text, '分享前先保存');
    await f.root.querySelector('.cc-shell-share').fire('click');
    assert.equal(latestPut(f.canvasCalls).body.payload.document.nodes.find(item => item.id === 'o').text, '分享前先保存');
    assert.deepEqual(f.accessCalls, []);
    const dialog = f.root.querySelector('.cc-shell-share-dialog');
    assert.equal(dialog.open, true);
    assert.equal(dialog.querySelector('h2').textContent, '分享画布');
    const field = dialog.querySelector('.cc-shell-share-link');
    assert.notEqual(field.getAttribute('readonly'), null);
    assert.equal(field.value, 'http://127.0.0.1:8765/canvas/share/c1?project_id=p1&canvas_id=c1&episode_id=ep%209');
    await dialog.querySelector('.cc-shell-share-copy').fire('click');
    assert.deepEqual(copied, [field.value]);
    assert.equal(f.root.querySelector('.cc-status').textContent, '已复制');
    await dialog.querySelector('.cc-shell-share-access').fire('click');
    assert.equal(f.root.querySelector('.cc-shell-share-dialog'), null);
    assert.deepEqual(f.accessCalls, [{area: 'share', project: 'p1', canvas: 'c1'}]);
  } finally {
    if (prior) Object.defineProperty(nav, 'clipboard', prior);
    else delete nav.clipboard;
    f.panel.suspend();
  }
});
