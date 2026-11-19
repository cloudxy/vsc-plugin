import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import {
  CANVAS_SHORTCUT_DEFINITIONS,
  applyHiddenIds,
  buildZip,
  historyDownloadPlan,
  historyNodeFromRecord,
  historyRecordsFromJobs,
  nextDrawerWidth,
  readDrawerWidth,
  resolveShortcutDefinitions,
  toggleHistorySelection,
  zipEntryNames,
} from '../../../src/vsc/interfaces/web/static/canvas-left-drawer.js';

test('drawer width keeps 431 and steps by 24 inside 360–720', () => {
  assert.equal(readDrawerWidth(null), 431);
  assert.equal(readDrawerWidth('431'), 431);
  assert.equal(readDrawerWidth('100'), 360);
  assert.equal(readDrawerWidth('900'), 720);
  assert.equal(nextDrawerWidth(431, 0), 431);
  assert.equal(nextDrawerWidth(431, 20), 455);
  assert.equal(nextDrawerWidth(431, -100), 360);
  assert.equal(nextDrawerWidth(700, 40), 720);
});

test('history records become canvas nodes and batch selection stops at 100', () => {
  const records = historyRecordsFromJobs([
    {id: 'job1', modality: 'image', status: 'succeeded', purpose: '雨夜主画面', outputs: [{id: 'out1', media_id: 'media-h1'}]},
    {id: 'job2', modality: 'video', status: 'succeeded', purpose: '街道推进', outputs: [{media: {id: 'media-h2'}}]},
    {id: 'job3', modality: 'audio', status: 'failed', purpose: '空结果', outputs: []},
  ]);
  assert.equal(records.length, 3);
  assert.equal(records[1].mediaId, 'media-h2');
  const node = historyNodeFromRecord(records[0], {x: 48, y: 64}, 'node-h1');
  assert.deepEqual(node, {
    id: 'node-h1', type: 'image', title: '雨夜主画面', x: 48, y: 64, text: '',
    params: {source: 'canvas_history', job_id: 'job1', output_id: 'out1'},
    media_id: 'media-h1', job_id: 'job1', group: '',
  });
  let selected = new Set();
  for (let i = 0; i < 100; i++) selected = toggleHistorySelection(selected, 'id-' + i, true).selected;
  const limited = toggleHistorySelection(selected, 'overflow', true);
  assert.equal(limited.limited, true);
  assert.equal(limited.selected.size, 100);
  assert.equal(limited.selected.has('overflow'), false);
  const visible = applyHiddenIds(records, new Set([records[0].id]));
  assert.deepEqual(visible.map(item => item.id), [records[1].id, records[2].id]);
  const plan = historyDownloadPlan(records, new Set([records[0].id, records[2].id]));
  assert.equal(plan.files.length, 1);
  assert.equal(plan.files[0].mediaId, 'media-h1');
  assert.equal(plan.missing, 1);
});

test('zip archive lists canvas-history entries without a new store', () => {
  const bytes = buildZip([
    {name: 'canvas-history/雨夜-1.png', data: new TextEncoder().encode('one')},
    {name: 'canvas-history/街道-2.mp4', data: new Uint8Array([1, 2, 3])},
  ]);
  assert.deepEqual(zipEntryNames(bytes), ['canvas-history/雨夜-1.png', 'canvas-history/街道-2.mp4']);
});

test('shortcut definitions stay replaceable until A3 exports them', () => {
  assert.deepEqual(CANVAS_SHORTCUT_DEFINITIONS.map(group => group.title), ['创作', '缩放', '移动画布', '其他']);
  assert.equal(CANVAS_SHORTCUT_DEFINITIONS[0].items.find(item => item.id === 'mergeStoryboardGroup').label, '合并分镜组');
  const custom = [{id: 'custom', title: '自定义快捷', items: [{id: 'x', label: '测试项', keys: [{text: 'Q'}]}]}];
  assert.equal(resolveShortcutDefinitions(custom)[0].title, '自定义快捷');
  globalThis.VSC_CANVAS_SHORTCUTS = custom;
  try {
    assert.equal(resolveShortcutDefinitions()[0].title, '自定义快捷');
  } finally {
    delete globalThis.VSC_CANVAS_SHORTCUTS;
  }
});

class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase(); this._text = text; this.children = []; this.attrs = {}; this.listeners = {};
    this.value = ''; this.style = {removeProperty(key) { delete this[key]; }};
    this.offsetWidth = 190; this.offsetHeight = 250; this.clientWidth = 1200; this.clientHeight = 800;
    this.scrollLeft = 0; this.scrollTop = 0; this.dataset = {}; this.parentElement = null; this.className = '';
    this.classList = {
      add: (...values) => { this.className = [...new Set([...this.className.split(' '), ...values])].filter(Boolean).join(' '); },
      contains: value => this.className.split(' ').includes(value),
      toggle: (value, force) => { const on = force ?? !this.classList.contains(value); if (on) this.classList.add(value); else this.classList.remove(value); return on; },
      remove: (...values) => { this.className = this.className.split(' ').filter(item => !values.includes(item)).join(' '); },
    };
  }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentElement = this; this.children.push(node); } }
  prepend(...nodes) { for (const node of nodes.reverse()) { node.remove(); node.parentElement = this; this.children.unshift(node); } }
  remove() { if (this.parentElement) { this.parentElement.children = this.parentElement.children.filter(item => item !== this); this.parentElement = null; } }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this._text = ''; this.append(...nodes); }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; }
  matches(selector) {
    if (selector[0] === '.') return this.classList.contains(selector.slice(1));
    if (selector[0] === '[') { const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/); return match && (match[2] == null ? this.attrs[match[1]] != null : this.attrs[match[1]] === match[2]); }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const values = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return values;
    return values.filter(child => selector.split(',').some(part => child.matches(part.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (selector.split(',').some(part => node.matches(part.trim()))) return node; return null; }
  getBoundingClientRect() { return {left: 0, top: 0, width: 1200, height: 800}; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  get options() { return this.children.filter(child => child.tagName === 'OPTION'); }
  get isConnected() { return this.parentElement !== null; }
  async fire(type, properties = {}) {
    const event = {target: this, preventDefault() {}, ...properties};
    for (const fn of this.listeners[type] || []) await fn(event);
    if (['input', 'change'].includes(type) && this.parentElement) await this.parentElement.fire(type, {...properties, target: event.target});
  }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; return this.fire('close'); }
}

async function fixture({apiOverride, projects, fetchImpl} = {}) {
  const document = {
    createElement: tag => { const node = new Element(tag); node.ownerDocument = document; return node; },
    createElementNS: (namespace, tag) => { const node = document.createElement(tag); node.namespaceURI = namespace; return node; },
    createTextNode: text => { const node = new Element('#text', text); node.ownerDocument = document; return node; },
    documentElement: {},
  };
  const listeners = new Map();
  const window = {
    addEventListener(type, fn) { (listeners.get(type) || listeners.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { listeners.get(type)?.delete(fn); },
    fire(type, event = {}) { for (const fn of [...listeners.get(type) || []]) fn(event); },
    open(url, target) { window.opened = {url, target}; },
  };
  const store = new Map();
  const sessionStorage = {getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)};
  const memory = new Map();
  const localStorage = {getItem: key => memory.has(key) ? memory.get(key) : null, setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key)};
  const calls = [];
  const module = await loadModule('creative-canvas.js', {
    document, window, location: {search: ''}, sessionStorage, localStorage, crypto, console,
    requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},
    fetch: fetchImpl || (async () => ({ok: true, text: async () => ''})),
    setTimeout: (fn, delay) => { if (delay === 0) return setTimeout(fn, 0); return 1; },
    clearTimeout: () => {},
  });
  const root = document.createElement('main');
  const ctx = {
    session: () => ({actor: 'test', csrf: 'test', revision: 1, writable: true}),
    setRevision() {}, opened() {},
    ...(projects ? {projects: () => projects} : {}),
    api: async (path, options) => {
      calls.push(path);
      if (apiOverride) { const value = await apiOverride(path, options); if (value !== undefined) return value; }
      if (path.endsWith('/creative-canvases/c1')) return {revision: 1, canvas_revision: 1, title: 'Test', episode_id: 'episode-1', document: {viewport: {x: 0, y: 0, zoom: 1}, nodes: [{id: 'n1', type: 'image', title: '主画面', x: 10, y: 20, text: '', params: {}, media_id: 'm1', job_id: null, group: ''}], edges: []}, jobs: {}, runs: [], execution_steps: []};
      return {items: [], revision: 1};
    },
  };
  const canvas = module.createCreativeCanvasPanel(ctx);
  await canvas.load(root, 'p1', 'episode-1', 'c1');
  return {root, canvas, calls, window, localStorage, memory, store};
}

const buttonByLabel = (root, label) => root.querySelectorAll('button').find(button => button.getAttribute('aria-label') === label);

test('left rail, add menu and shortcut panel follow the reference order', async () => {
  const view = await fixture();
  const labels = view.root.querySelector('.cc-rail').querySelectorAll('button').map(button => button.getAttribute('aria-label'));
  assert.deepEqual(labels, ['添加节点', '画布元素', '历史记录', '资产库', '快捷键', '创作指引', '指针/抓手']);
  assert.equal(view.root.querySelector('.cc-rail').querySelectorAll('button').some(button => button.getAttribute('aria-label') === '浏览固定画布模板'), false);
  assert.match(view.root.querySelector('.cc-more-menu').textContent, /浏览固定画布模板/);
  const add = buttonByLabel(view.root, '添加节点');
  await add.fire('click');
  const menu = view.root.querySelector('.cc-create-menu');
  assert.equal(menu.hidden, false);
  assert.equal(add.getAttribute('aria-pressed'), 'true');
  const menuText = menu.querySelectorAll('button').map(button => button.textContent.replace(/NEW$/, ''));
  for (const label of ['文本', '图片', '视频', '视频剪辑', '导演台', '3D预演', '音频', '上传', '从资产库导入', '从历史记录选择']) assert.ok(menuText.includes(label), label);
  assert.match(menu.textContent, /添加节点/);
  assert.match(menu.textContent, /添加资源/);
  await buttonByLabel(view.root, '创作指引').fire('click');
  assert.deepEqual(view.window.opened, {url: '/guide', target: '_blank'});
  await buttonByLabel(view.root, '快捷键').fire('click');
  const panel = view.root.querySelector('.cld-shortcuts');
  assert.equal(panel.dataset.canvasShortcutPanel, 'true');
  assert.match(panel.textContent, /合并分镜组/);
  assert.match(panel.textContent, /整理画布/);
  assert.ok(panel.textContent.includes('⌘'));
  view.canvas.suspend();
});

test('history tab restores one record, hides a batch, and downloads a zip', async () => {
  const fetched = [];
  const blobs = [];
  const previousCreate = globalThis.URL.createObjectURL;
  const previousRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:history'; };
  globalThis.URL.revokeObjectURL = () => {};
  const fetchImpl = async url => { fetched.push(String(url)); return {ok: true, arrayBuffer: async () => new TextEncoder().encode('img-' + url).buffer}; };
  const jobs = {
    items: [
      {id: 'job1', modality: 'image', status: 'succeeded', purpose: '雨夜主画面', outputs: [{id: 'out1', media_id: 'media-h1'}]},
      {id: 'job2', modality: 'image', status: 'succeeded', purpose: '街道推进', outputs: [{id: 'out2', media_id: 'media-h2'}]},
    ],
    total: 2,
    revision: 1,
  };
  try {
    const view = await fixture({
      apiOverride: async path => path.includes('/creative-canvas-jobs') ? jobs : undefined,
      fetchImpl,
    });
    await buttonByLabel(view.root, '历史记录').fire('click');
    const drawer = view.root.querySelector('.cc-elements');
    assert.match(drawer.textContent, /雨夜主画面/);
    assert.match(drawer.textContent, /批量选择/);
    const place = drawer.querySelectorAll('button').find(button => button.textContent === '导入画布');
    await place.fire('click');
    const saved = JSON.parse([...view.store.values()].find(value => String(value).includes('media-h1')));
    const node = saved.document.nodes.find(item => item.media_id === 'media-h1');
    assert.equal(node.type, 'image');
    assert.equal(node.job_id, 'job1');
    assert.deepEqual(node.params, {source: 'canvas_history', job_id: 'job1', output_id: 'out1'});
    const before = saved.document.nodes.length;
    await drawer.querySelectorAll('button').find(button => button.textContent === '批量选择').fire('click');
    const boxes = view.root.querySelectorAll('input').filter(input => input.className === 'cld-history-check');
    assert.equal(boxes.length, 2);
    boxes[0].checked = true; await boxes[0].fire('change');
    boxes[1].checked = true; await boxes[1].fire('change');
    await drawer.querySelector('.cld-history-batch').querySelectorAll('button').find(button => button.textContent === '下载 ZIP').fire('click');
    assert.equal(fetched.length, 2);
    assert.equal(blobs.length, 1);
    const names = zipEntryNames(new Uint8Array(await blobs[0].arrayBuffer()));
    assert.equal(names.length, 2);
    assert.ok(names.every(name => name.startsWith('canvas-history/')));
    await drawer.querySelector('.cld-history-batch').querySelectorAll('button').find(button => button.textContent === '隐藏').fire('click');
    const confirm = view.root.querySelector('.cld-confirm');
    assert.match(confirm.textContent, /不会删除画布节点和资源文件/);
    await confirm.querySelectorAll('button').find(button => button.textContent === '隐藏').fire('click');
    assert.match(view.root.querySelector('.cc-elements').textContent, /暂无生成记录/);
    const after = JSON.parse([...view.store.values()].find(value => String(value).includes('canvas_history'))).document.nodes.length;
    assert.equal(after, before);
    assert.equal(view.calls.some(path => path.includes('DELETE')), false);
    view.canvas.suspend();
  } finally {
    globalThis.URL.createObjectURL = previousCreate;
    globalThis.URL.revokeObjectURL = previousRevoke;
  }
});

test('asset tabs load project, official and storyboard material onto the canvas', async () => {
  const view = await fixture({
    projects: [{id: 'p1', name: '当前项目'}, {id: 'p2', name: '来源项目'}],
    apiOverride: async path => {
      if (path.includes('/asset-cards?')) return {revision: 1, items: [{id: 'asset1', record_kind: 'asset', asset_kind: 'character', name: '角色甲', project_id: 'p1', forms: [{form_key: 'master', name: '默认', version_id: 'form1', media_id: 'asset-media'}]}], next_offset: null};
      if (path.includes('/asset-center?')) return {items: [{version_id: 'lib1', title: '官方角色', allowed_purposes: ['reference_image'], members: [{member_key: 'face', modality: 'image', preview_url: '/preview.png'}]}]};
      if (path.includes('/storyboard-references')) return {items: [{shot_id: 'shot1', title: '雨夜推门', display_code: 'S01', images: [{media_id: 'sb-media', name: '雨夜推门', selected: true}]}], revision: 1};
    },
  });
  await buttonByLabel(view.root, '资产库').fire('click');
  const drawer = view.root.querySelector('.cc-assets');
  assert.match(drawer.textContent, /项目资产/);
  assert.match(drawer.textContent, /官方资产/);
  assert.match(drawer.textContent, /分镜/);
  assert.match(drawer.textContent, /批量导入画布/);
  const projectPick = drawer.querySelectorAll('select').find(node => node.getAttribute('aria-label') === '资产项目');
  assert.equal(projectPick.value, '*');
  assert.ok(view.calls.some(path => path.includes('/api/v1/projects/p1/asset-cards?') && path.includes('include_blocking=true')));
  await drawer.querySelector('.cc-asset-send').fire('click');
  const projectNode = JSON.parse([...view.store.values()].find(value => String(value).includes('asset-media'))).document.nodes.find(node => node.media_id === 'asset-media');
  assert.equal(projectNode.type, 'image');
  assert.equal(projectNode.title.includes('角色甲'), true);
  const transfer = {value: '', types: ['application/x-vsc-canvas-asset'], setData(_type, value) { this.value = value; }, getData() { return this.value; }};
  await drawer.querySelectorAll('button').find(button => button.textContent === '官方资产').fire('click');
  await view.root.querySelector('.cc-asset-open').fire('dragstart', {dataTransfer: transfer});
  assert.deepEqual(JSON.parse(transfer.value), {kind: 'library', library_version_id: 'lib1', member_key: 'face', role: 'reference_image'});
  await view.root.querySelectorAll('button').find(button => button.textContent === '分镜').fire('click');
  await view.root.querySelector('.cc-asset-send').fire('click');
  const storyNode = JSON.parse([...view.store.values()].find(value => String(value).includes('sb-media'))).document.nodes.find(node => node.media_id === 'sb-media');
  assert.equal(storyNode.type, 'image');
  assert.match(storyNode.title, /S01/);
  const resizer = view.root.querySelector('.cc-drawer-resizer');
  await resizer.fire('pointerdown', {clientX: 100, preventDefault() {}});
  view.window.fire('pointermove', {clientX: 124});
  view.window.fire('pointerup', {});
  assert.equal(view.root.querySelector('.cc-assets').style.width, '455px');
  assert.equal(view.memory.get('vsc-canvas-left-drawer-width'), '455');
  view.canvas.suspend();
});
