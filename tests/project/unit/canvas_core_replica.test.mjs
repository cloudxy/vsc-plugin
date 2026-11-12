import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.value = '';
    this.style = { removeProperty(k) { delete this[k]; } };
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
  getBoundingClientRect() { return { left: 0, top: 0, width: 400, height: 300 }; }
  addEventListener(k, v) { (this.listeners[k] ??= []).push(v); }
  get options() { return this.children.filter(x => x.tagName === 'OPTION'); }
  get isConnected() { return this.parentElement !== null; }
  async fire(type, properties = {}) {
    const event = { target: this, preventDefault() {}, stopPropagation() {}, ...properties };
    if (this['on' + type]) await this['on' + type](event);
    for (const f of this.listeners[type] || []) await f(event);
    if (['input', 'change'].includes(type) && this.parentElement) {
      await this.parentElement.fire(type, { ...properties, target: event.target });
    }
  }
  pause() {}
  focus() { this.ownerDocument.activeElement = this; }
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; return this.fire('close'); }
  get selectedOptions() { return this.options.filter(node => node.selected || (node.value === this.value && !this.multiple)); }
}

async function createCanvasFixture({ nodes = [], edges = [], viewport = { x: 0, y: 0, zoom: 1 }, search = '', apiOverride = null, runOptions = null } = {}) {
  const store = new Map();
  const canvasCalls = [];
  const document = {
    createElement: t => {
      const n = new Element(t);
      n.ownerDocument = document;
      if (t === 'canvas') {
        n.getContext = () => ({
          clearRect() {},
          fillRect() {},
          beginPath() {},
          moveTo() {},
          lineTo() {},
          stroke() {},
          drawImage() {},
          getImageData() { return { data: new Uint8ClampedArray(32) }; },
        });
      }
      return n;
    },
    createElementNS: (ns, t) => { const n = document.createElement(t); n.namespaceURI = ns; return n; },
    createTextNode: text => { const n = new Element('#text', text); n.ownerDocument = document; return n; },
    documentElement: {},
  };
  class FakeImage {}
  const sessionStorage = {
    getItem: k => store.get(k) || null,
    setItem: (k, v) => store.set(k, v),
    removeItem: k => store.delete(k),
  };
  const winListeners = new Map();
  const window = {
    addEventListener(type, fn) { (winListeners.get(type) || winListeners.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { winListeners.get(type)?.delete(fn); },
    fire(type, event = {}) { for (const fn of [...(winListeners.get(type) || [])]) fn(event); },
  };
  const location = { search, href: 'http://127.0.0.1:8765/canvas' + search, assign() {} };
  const timeouts = [];
  const mod = await loadModule('creative-canvas.js', {
    document,
    window,
    location,
    sessionStorage,
    crypto,
    console,
    Image: FakeImage,
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
    fetch: async () => ({ ok: true, text: async () => '[00:00.00] 合成歌词\n' }),
    setTimeout: (fn, delay) => {
      if (delay === 0) return setTimeout(fn, 0);
      timeouts.push({ fn, delay });
      return timeouts.length;
    },
    clearTimeout: () => {},
  });
  const root = document.createElement('main');
  const session = { actor: 'test', csrf: 'csrf-1', revision: 1, writable: true };
  let dbVersion = 1;
  let dbDoc = structuredClone({ viewport, nodes, edges });
  const ctx = {
    session: () => session,
    setRevision() {},
    opened() {},
    api: async (path, options) => {
      canvasCalls.push({ path, method: options?.method || 'GET', body: options?.body ? JSON.parse(options.body) : null });
      if (apiOverride) {
        const custom = await apiOverride(path, options, { getDoc: () => dbDoc, setDoc: d => { dbDoc = d; }, nextVer: () => ++dbVersion, getVer: () => dbVersion });
        if (custom !== undefined) return custom;
      }
      if (path === '/api/v1/projects/p1/creative-canvases/c1') {
        if (options?.method === 'PUT') {
          const body = JSON.parse(options.body);
          dbDoc = structuredClone(body.payload.document);
          dbVersion += 1;
          return { revision: dbVersion, canvas_revision: dbVersion, title: body.payload.title };
        }
        return { revision: dbVersion, canvas_revision: dbVersion, title: 'Canvas Core Test', episode_id: null, document: structuredClone(dbDoc), jobs: {}, runs: [], execution_steps: [] };
      }
      if (path.endsWith('/creative-canvas-run-options')) {
        return runOptions || {
          revision: dbVersion,
          nodes: [],
          models: [{ id: 'img-m1', enabled: true, modality: 'image', model_key: 'seedream', model_version: '4.0', capabilities: { purposes: ['image_edit'] } }],
          image_tools: {
            angle: { preset: 'custom', yaw: 0, pitch: 0, roll: 0, zoom: 1, include_instructions: true },
            lighting: { view: 'perspective', direction: 'front', intensity: 0.5, color: '#ffffff', cone: 45, rim: false },
            three_view: { layout: 'front_side_back' },
            headshot: { framing: 'head_and_shoulders' },
            face_views: { layout: 'front_three_quarter_side' },
            story_four_grid: { layout: 'story_four_grid' },
            panorama: { equirectangular: true, aspect: '2:1' },
            upscale: { resolution: '4k' },
            inpaint: { brush_size: 40, mask_data_url: '' },
            outpaint: { aspect_ratio: '16:9', scale: 1.5 },
            watermark: { mode: 'auto' },
            matting: { subject: 'foreground' },
          },
        };
      }
      if (path.endsWith('/history')) {
        return { revision: dbVersion, items: [{ version: 1, title: '初始版本' }] };
      }
      if (path.endsWith('/creative-canvas-agent-options')) {
        return { revision: dbVersion, host_available: true, skills: [{ id: 'vsc-script', name: 'Script', description: '剧本规划' }], models: [], nodes: [] };
      }
      return { items: [], revision: dbVersion };
    },
  };
  const panel = mod.createCreativeCanvasPanel(ctx);
  await panel.load(root, 'p1', null, 'c1');
  return { root, panel, store, canvasCalls, timeouts, window, getDoc: () => dbDoc };
}

function latestDraftDoc(store) {
  const key = [...store.keys()].find(k => k.startsWith('vsc-creative-canvas:v2:'));
  return key ? JSON.parse(store.get(key)).document : null;
}

test('09A shell: 800% zoom, fit view ⌘0, snap toggle, NEW badges, 431px 2-tab drawer, ⌘D upstream-edge duplicate, and share focus_node_key', async () => {
  const nodes = [
    { id: 'txt1', type: 'text', title: '提示词源', x: 100, y: 120, text: '赛博雨夜', params: {}, media_id: null, job_id: null, group: '' },
    { id: 'img1', type: 'image', title: '主画面', x: 420, y: 120, text: '', params: {}, media_id: 'm1', job_id: null, group: '' },
  ];
  const edges = [{ id: 'e1', source: 'txt1', target: 'img1', port: 'prompt' }];
  const f = await createCanvasFixture({ nodes, edges });

  // NEW badges on create menu items
  const newBadgeButtons = f.root.querySelector('.cc-create-menu').querySelectorAll('.cc-has-new-badge');
  assert.equal(newBadgeButtons.length, 5);

  // Zoom preset to 800% and fit view
  const preset = f.root.querySelector('.cc-zoom-preset');
  preset.value = '8';
  await preset.fire('change');
  assert.equal(f.root.querySelector('.cc-zoom').querySelector('output').textContent, '800%');
  await f.root.querySelector('.cc-stage').fire('keydown', { metaKey: true, key: '0' });
  assert.notEqual(f.root.querySelector('.cc-zoom').querySelector('output').textContent, '800%');

  // Snap toggle switches aria-pressed
  const snapBtn = f.root.querySelector('.cc-snap-toggle');
  assert.equal(snapBtn.getAttribute('aria-pressed'), 'true');
  await snapBtn.fire('click');
  assert.equal(snapBtn.getAttribute('aria-pressed'), 'false');

  // ⌘D duplicates selected downstream node and preserves incoming prompt edge from txt1
  const imgCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  await imgCard.fire('click', { target: imgCard.querySelector('img') });
  await f.root.querySelector('.cc-stage').fire('keydown', { metaKey: true, key: 'd' });
  const draft = latestDraftDoc(f.store);
  assert.equal(draft.nodes.length, 3);
  const copiedImg = draft.nodes.find(n => n.id !== 'txt1' && n.id !== 'img1');
  assert.ok(draft.edges.some(e => e.source === 'txt1' && e.target === copiedImg.id && e.port === 'prompt'));

  // 431px 2-tab drawer switches between 画布元素 and 历史版本
  await f.root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '画布元素').fire('click');
  const drawer = f.root.querySelector('.cc-elements');
  assert.equal(drawer.style.width, '431px');
  assert.equal(drawer.querySelectorAll('.cc-element-card').length, 3);
  await drawer.querySelector('.cc-drawer-tabs').querySelectorAll('button')[1].fire('click');
  assert.match(drawer.textContent, /初始版本/);

  // Share mode floating home link and focus_node_key selection + scroll centering
  await f.panel.loadShared(f.root, {
    project_id: 'p1',
    canvas_id: 'c1',
    mode: 'view',
    focus_node_key: 'img1',
    project_revision: 1,
    version: 1,
    title: '分享画布',
    media_ids: ['m1'],
    document: { viewport: { x: 0, y: 0, zoom: 1 }, nodes, edges },
  });
  const homeBtn = f.root.querySelector('.cc-share-home-btn');
  assert.ok(homeBtn);
  assert.equal(homeBtn.href, '/home');
  const focusedCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  assert.ok(focusedCard.classList.contains('selected'));
  assert.ok(f.root.querySelector('.cc-stage').scrollLeft > 0);
  f.panel.suspend();
});

test('09B & 09C image ops: portrait texture, emotion XY pad, color filter identity guard, crop/rotate/doodle transform, panorama capture, grid storyboard group, and photography settings', async () => {
  const source = { id: 'img1', type: 'image', title: '人物原图', x: 100, y: 100, text: '', params: {}, media_id: 'm1', job_id: null, group: '' };
  const transformRequests = [];
  const panoramaRequests = [];
  const splitRequests = [];
  const f = await createCanvasFixture({
    nodes: [source],
    apiOverride: async (path, options, helpers) => {
      if (path.endsWith('/transform-image')) {
        const body = JSON.parse(options.body);
        transformRequests.push(body.payload);
        const ver = helpers.nextVer();
        const nextNode = { id: 'transform-1', type: 'image', title: '人物原图 · 调色滤镜', x: 400, y: 100, text: '', params: {}, media_id: 'm-trans', job_id: null, group: '' };
        const nextEdge = { id: 'derive-1', source: 'img1', target: 'transform-1', port: 'derived_from' };
        const doc = helpers.getDoc();
        doc.nodes.push(nextNode);
        doc.edges.push(nextEdge);
        return { revision: ver, canvas_revision: ver, node_ids: ['transform-1'], media_ids: ['m-trans'] };
      }
      if (path.endsWith('/capture-panorama')) {
        const body = JSON.parse(options.body);
        panoramaRequests.push(body.payload);
        const ver = helpers.nextVer();
        const panoNodes = [1, 2, 3, 4].map(i => ({ id: `pano-${i}`, type: 'image', title: `视角${i}`, x: 420 + i * 100, y: 100, text: '', params: {}, media_id: `mp-${i}`, job_id: null, group: '' }));
        const panoEdges = panoNodes.map((n, i) => ({ id: `pe-${i}`, source: 'img1', target: n.id, port: 'derived_from' }));
        const doc = helpers.getDoc();
        doc.nodes.push(...panoNodes);
        doc.edges.push(...panoEdges);
        return { revision: ver, canvas_revision: ver, node_ids: panoNodes.map(n => n.id), media_ids: panoNodes.map(n => n.media_id) };
      }
      if (path.endsWith('/split-image')) {
        const body = JSON.parse(options.body);
        splitRequests.push(body.payload);
        const err = new Error('stop split after payload check');
        err.status = 422;
        throw err;
      }
      if (path.includes('?version=')) {
        return { revision: helpers.getVer(), document: structuredClone(helpers.getDoc()) };
      }
    },
  });

  // Select image card and test dynamic preset unlock on <details> toggle
  let card = f.root.querySelector('.cc-node');
  await card.fire('click', { target: card.querySelector('img') });
  card = f.root.querySelector('.cc-node');
  const presetsDetails = card.querySelectorAll('.cc-image-generate').find(d => d.querySelector('summary')?.textContent === '生成');
  const fourGridBtn = presetsDetails.querySelectorAll('button').find(b => b.textContent === '剧情推进四格');
  assert.equal(fourGridBtn.disabled, true);
  presetsDetails.open = true;
  await presetsDetails.fire('toggle');
  assert.equal(fourGridBtn.disabled, false);

  // Color adjust panel: confirm disabled on original identity, enabled after selecting 青橙电影 filter
  await card.querySelectorAll('button').find(b => b.textContent === '调色').fire('click');
  const colorPanel = card.querySelector('.cc-color-adjust-panel');
  assert.ok(colorPanel);
  const confirmColor = colorPanel.querySelectorAll('button').find(b => b.textContent === '确认');
  assert.equal(confirmColor.disabled, true);
  await colorPanel.querySelectorAll('.cc-filter-chip').find(b => b.textContent === '青橙电影').fire('click');
  assert.equal(confirmColor.disabled, false);
  await confirmColor.fire('click');
  assert.equal(transformRequests.length, 1);
  assert.equal(transformRequests[0].operation, 'color_adjust');
  assert.equal(transformRequests[0].settings.filterId, 'teal_orange');
  assert.ok(f.root.querySelectorAll('.cc-node').some(c => c.dataset.nodeId === 'transform-1'));

  // Re-select source image and capture 4 panorama views
  card = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  await card.fire('click', { target: card.querySelector('img') });
  await f.root.querySelectorAll('button').find(b => b.textContent === '进入全景').fire('click');
  card = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  const captureFour = card.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '4大视角截图');
  assert.equal(captureFour.disabled, false);
  await captureFour.fire('click');
  assert.equal(panoramaRequests.length, 1);
  assert.equal(panoramaRequests[0].mode, 'four');
  assert.ok(f.root.querySelectorAll('.cc-node').some(c => c.dataset.nodeId === 'pano-4'));

  // Grid split 创建分镜组 sends group_name
  card = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  await card.fire('click', { target: card.querySelector('img') });
  await f.root.querySelectorAll('button').find(b => b.textContent === '4宫格（2×2）').fire('click');
  await f.root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '宫格 1行1列').fire('click');
  const storyGroupBtn = f.root.querySelector('.cc-grid-storyboard');
  assert.equal(storyGroupBtn.disabled, false);
  await storyGroupBtn.fire('click');
  assert.equal(splitRequests.length, 1);
  assert.equal(splitRequests[0].group_name, '人物原图 · 分镜组');

  // Exit grid, open Emotion 2D XY pad -> creates expression node and mounts photography settings in runForm
  await f.root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '退出宫格切分').fire('click');
  card = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'img1');
  await card.querySelectorAll('button').find(b => b.textContent === '情绪调节').fire('click');
  const emotionPanel = card.querySelector('.cc-portrait-emotion-panel');
  assert.ok(emotionPanel);
  const pad = emotionPanel.querySelector('.canvas-portrait-emotion-pad');
  await pad.fire('pointerdown', { clientX: 300, clientY: 60 });
  await pad.fire('pointerup');
  await emotionPanel.querySelectorAll('button').find(b => b.textContent === '创建情绪调节节点').fire('click');
  const exprNode = latestDraftDoc(f.store).nodes.find(n => n.params?.vsc_image_tool === 'expression');
  assert.ok(exprNode);
  const exprSettings = JSON.parse(exprNode.params.vsc_image_tool_settings);
  assert.deepEqual(Object.keys(exprSettings).sort(), ['arousal', 'brow', 'eye', 'head_tilt', 'mouth', 'valence']);
  const runForm = f.root.querySelector('.cc-run-form');
  assert.ok(runForm);
  const photoToggle = runForm.querySelectorAll('input').find(i => i.getAttribute('aria-label') === '启用摄影机参数');
  assert.ok(photoToggle);
  photoToggle.checked = true;
  await photoToggle.fire('change');
  assert.equal(runForm.querySelector('.cc-photo-settings-grid').hidden, false);
  f.panel.suspend();
});

test('09A/09B share route & doodle resilience: subview=canvas-share enters sharedEditor with focus_node_key, doodle width slider & error recovery re-enables button', async () => {
  const nodes = [
    { id: 'txt1', type: 'text', title: '起点', x: 80, y: 80, text: 'hello', params: {}, media_id: null, job_id: null, group: '' },
    { id: 'imgTarget', type: 'image', title: '聚焦目标图', x: 760, y: 480, text: '', params: {}, media_id: 'm1', job_id: null, group: '' },
  ];
  const shareFix = await createCanvasFixture({ nodes, edges: [], search: '?page=creative-canvas&subview=canvas-share&project=p1&task_target=c1&focus_node_key=imgTarget' });
  assert.ok(shareFix.root.querySelector('.cc-share-home-btn'));
  assert.ok(shareFix.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'imgTarget')?.classList.contains('selected'));
  assert.ok(shareFix.root.querySelector('.cc-stage').scrollLeft > 0);
  shareFix.panel.suspend();

  const miniDoc = shareFix.root.ownerDocument;
  const edMod = await loadModule('canvas-media-editors.js', { document: miniDoc, window: {}, console });
  const dummyCard = miniDoc.createElement('div');
  let failOnce = true;
  edMod.openDoodleOverlay(dummyCard, {
    onSubmit: async () => {
      if (failOnce) {
        failOnce = false;
        throw new Error('empty doodle');
      }
    },
  });
  const widthInput = dummyCard.querySelectorAll('input').find(i => i.getAttribute('aria-label') === '涂鸦笔宽');
  assert.ok(widthInput);
  assert.equal(widthInput.max, '64');
  const saveDoodleBtn = dummyCard.querySelectorAll('button').find(b => b.textContent === '保存涂鸦');
  await assert.rejects(() => saveDoodleBtn.fire('click'), /empty doodle/);
  assert.equal(saveDoodleBtn.disabled, false);
});

test('09D, 09E & 11-MV: group_frame color/lock, video_story fan-out, edit multi-clip 500ms autosave + export, audio waveform + LRC storyboard spawn, and camera motion dialog', async () => {
  const nodes = [
    { id: 'grp1', type: 'text', title: '分组框', x: 60, y: 60, text: '', params: { canvas_subkind: 'group_frame', group_color: '#292929', group_locked: true }, media_id: null, job_id: null, group: '第一场' },
    { id: 'vid1', type: 'video', title: '镜头A', x: 100, y: 120, text: '', params: {}, media_id: 'mv1', job_id: null, group: '第一场' },
    { id: 'aud1', type: 'audio', title: '主题曲', x: 100, y: 360, text: '[00:00.00] 霓虹亮起\n[00:04.50] 奔向海岸', params: {}, media_id: 'ma1', job_id: null, group: '' },
    { id: 'imgSinger', type: 'image', title: '主唱定妆照', x: 100, y: 560, text: '', params: {}, media_id: 'mi1', job_id: null, group: '' },
    { id: 'edEmpty', type: 'edit', title: '空剪辑器', x: 440, y: 360, text: '', params: {}, media_id: null, job_id: null, domain_object_id: 'do1', domain_version_id: 'dv1', group: '' },
    { id: 'edConnected', type: 'edit', title: '成片剪辑台', x: 440, y: 120, text: '', params: {}, media_id: null, job_id: null, domain_object_id: 'do2', domain_version_id: 'dv2', group: '' },
  ];
  const edges = [
    { id: 'ev1', source: 'vid1', target: 'edConnected', port: 'visual' },
    { id: 'ea1', source: 'aud1', target: 'edConnected', port: 'sound' },
  ];
  const motionWrites = [];
  const f = await createCanvasFixture({
    nodes,
    edges,
    apiOverride: async (path, options) => {
      if (path.endsWith('/camera-motion-templates')) {
        if (options?.method === 'POST') {
          motionWrites.push(JSON.parse(options.body).payload);
          return { revision: 3, item: { id: 'cm-custom-1', name: '环绕升格', favorite: false } };
        }
        return {
          revision: 2,
          builtin: [{ id: 'builtin-push-in', name: '推进镜头 Push In', prompt_fragment: '平稳推进', horizontal_pan: 0, vertical_tilt: 0, zoom_delta: 50, roll_deg: 0, speed_preset: 'normal' }],
          custom: [{ id: 'cm-1', name: '专属手持跟拍', prompt_fragment: '轻微呼吸感跟拍', favorite: false }],
        };
      }
    },
  });

  // Locked group blocks member drag until unlocked
  let vidCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'vid1');
  await vidCard.querySelector('.cc-node-head').fire('pointerdown', { button: 0, clientX: 100, clientY: 120 });
  assert.match(f.root.querySelector('.cc-status').textContent, /已锁定/);
  const grpCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'grp1');
  await grpCard.querySelector('.cc-group-lock-btn').fire('click');
  assert.equal(latestDraftDoc(f.store).nodes.find(n => n.id === 'grp1').params.group_locked, false);

  // Empty edit node shows required empty-state message
  const emptyEditCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'edEmpty');
  assert.match(emptyEditCard.textContent, /视频剪辑功能需要连接视频节点后使用/);

  // Connected edit node opens multi-clip editor, schedules 500ms autosave, and exports downstream video node at x+320
  const editCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'edConnected');
  await editCard.querySelectorAll('button').find(b => b.textContent === '打开多视频剪辑器').fire('click');
  const multiDlg = f.root.querySelector('.canvas-multi-video-edit-dialog');
  assert.ok(multiDlg);
  const startIn = multiDlg.querySelectorAll('input').find(i => i.getAttribute('aria-label') === '镜头A 入点');
  startIn.value = '1.256';
  await startIn.fire('input');
  assert.ok(f.timeouts.some(t => t.delay === 500));
  await multiDlg.querySelectorAll('button').find(b => b.textContent === '导出成片至右侧节点').fire('click');
  let doc = latestDraftDoc(f.store);
  const exportedVideo = doc.nodes.find(n => n.title === '成片剪辑台 · 剪辑成片');
  assert.ok(exportedVideo);
  assert.equal(exportedVideo.x, 760);
  assert.ok(doc.edges.some(e => e.source === 'edConnected' && e.target === exportedVideo.id && e.port === 'derived_from'));

  // Audio node renders waveform canvas and spawns MV storyboard video nodes from LRC timeline with singer first_frame
  let audCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'aud1');
  assert.ok(audCard.querySelector('.cc-audio-waveform'));
  await audCard.querySelector('.cc-node-head').fire('click');
  audCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'aud1');
  await audCard.querySelectorAll('button').find(b => b.textContent === 'LRC时间轴').fire('click');
  const lrcDlg = f.root.querySelector('.canvas-lyrics-timeline-dialog');
  assert.ok(lrcDlg);
  await lrcDlg.querySelectorAll('button').find(b => b.textContent === '歌词分镜映射').fire('click');
  const singerSel = lrcDlg.querySelectorAll('select').find(s => s.getAttribute('aria-label') === '第1句歌手参考图');
  singerSel.value = 'imgSinger';
  await singerSel.fire('change');
  await lrcDlg.querySelectorAll('button').find(b => b.textContent === '一键派生 MV 分镜视频节点').fire('click');
  doc = latestDraftDoc(f.store);
  const mvNodes = doc.nodes.filter(n => n.title.startsWith('MV分镜 '));
  assert.equal(mvNodes.length, 2);
  assert.ok(doc.edges.some(e => e.source === 'aud1' && e.target === mvNodes[0].id && e.port === 'reference_audio'));
  assert.ok(doc.edges.some(e => e.source === 'imgSinger' && e.target === mvNodes[0].id && e.port === 'first_frame'));

  // Video node camera motion library creates custom motion template and applies motion
  vidCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'vid1');
  await vidCard.querySelector('.cc-node-head').fire('click');
  vidCard = f.root.querySelectorAll('.cc-node').find(c => c.dataset.nodeId === 'vid1');
  await vidCard.querySelectorAll('button').find(b => b.textContent === '相机运镜库').fire('click');
  const motionDlg = f.root.querySelector('.canvas-video-camera-motion-dialog');
  assert.ok(motionDlg);
  const motionName = motionDlg.querySelectorAll('input').find(i => i.getAttribute('aria-label') === '自定义运镜名称');
  motionName.value = '环绕推进高潮';
  await motionDlg.querySelectorAll('button').find(b => b.textContent === '保存为自定义模板').fire('click');
  assert.equal(motionWrites.length, 1);
  assert.equal(motionWrites[0].action, 'create');
  assert.equal(motionWrites[0].name, '环绕推进高潮');
  f.panel.suspend();
});

test('09G agent panel: session rename, auto-approve, archive filter, and queue enqueue/steer/take_for_edit/cancel', async () => {
  const stateWrites = [];
  const queueWrites = [];
  let sessionState = { title: '第一幕分镜规划', archived: false, auto_approve: false };
  let queueItems = [];
  const f = await createCanvasFixture({
    apiOverride: async (path, options) => {
      if (path.includes('/agent-sessions') && (!options?.method || options.method === 'GET')) {
        const showArchived = path.includes('include_archived=true');
        const items = sessionState.archived && !showArchived ? [] : [{
          id: 'sess-1',
          title: sessionState.title,
          archived: sessionState.archived,
          auto_approve: sessionState.auto_approve,
          queue: structuredClone(queueItems),
          turns: [{ id: 'turn-1', message: '帮我规划雨夜追逐镜头', canvas_revision: 1, skill_id: 'vsc-script', status: 'applied' }],
        }];
        return { revision: 2, items };
      }
      if (path.endsWith('/agent-sessions/sess-1/state')) {
        const payload = JSON.parse(options.body).payload;
        stateWrites.push(payload);
        Object.assign(sessionState, payload);
        return { revision: 3, ...sessionState };
      }
      if (path.endsWith('/agent-sessions/sess-1/queue')) {
        const payload = JSON.parse(options.body).payload;
        queueWrites.push(payload);
        if (payload.action === 'enqueue') {
          queueItems.push({ id: 'q-1', message: payload.message, status: 'queued', skill_id: payload.skill_id, mode: payload.mode });
        } else if (payload.action === 'steer') {
          queueItems = queueItems.map(q => q.id === payload.queue_item_id ? { ...q, status: 'steered' } : q);
        } else if (payload.action === 'take_for_edit') {
          queueItems = queueItems.map(q => q.id === payload.queue_item_id ? { ...q, status: 'editing' } : q);
        } else if (payload.action === 'cancel') {
          queueItems = queueItems.filter(q => q.id !== payload.queue_item_id);
        }
        return { revision: 4, action: payload.action };
      }
    },
  });

  await f.root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '画布 Agent').fire('click');
  const agent = f.root.querySelector('.cc-agent');
  assert.ok(agent);

  // Select session, enqueue message, steer, take back for edit, and cancel
  await agent.querySelectorAll('button').find(b => b.textContent === '继续此会话').fire('click');
  const composerInput = agent.querySelector('.cc-agent-composer').querySelector('textarea');
  composerInput.value = '补充主角特写与霓虹反射细节';
  await composerInput.fire('input');
  await agent.querySelector('.cc-agent-enqueue').fire('click');
  assert.equal(queueWrites.length, 1);
  assert.equal(queueWrites[0].action, 'enqueue');
  assert.equal(composerInput.value, '');
  assert.ok(agent.querySelector('.cc-agent-queue-item'));

  await agent.querySelector('.cc-agent-queue-item').querySelectorAll('button').find(b => b.textContent === '优先插队').fire('click');
  assert.equal(queueWrites.at(-1).action, 'steer');
  assert.match(agent.querySelector('.cc-agent-queue-item').textContent, /优先插队/);

  await agent.querySelector('.cc-agent-queue-item').querySelectorAll('button').find(b => b.textContent === '取回编辑').fire('click');
  assert.equal(queueWrites.at(-1).action, 'take_for_edit');
  assert.equal(composerInput.value, '补充主角特写与霓虹反射细节');

  await agent.querySelector('.cc-agent-queue-item').querySelectorAll('button').find(b => b.textContent === '取消排队').fire('click');
  assert.equal(queueWrites.at(-1).action, 'cancel');
  assert.equal(agent.querySelector('.cc-agent-queue-item'), null);

  // Toggle auto-approve, rename session, and archive/show-archived
  await agent.querySelectorAll('button').find(b => b.getAttribute('aria-label') === '免确认自动执行').fire('click');
  assert.equal(stateWrites.at(-1).auto_approve, true);

  await agent.querySelectorAll('button').find(b => b.textContent === '重命名会话').fire('click');
  const renameIn = agent.querySelector('.cc-agent-rename-inline').querySelector('input');
  assert.equal(renameIn.maxLength, 200);
  renameIn.value = '雨夜决战定稿会话';
  await agent.querySelector('.cc-agent-rename-inline').querySelectorAll('button').find(b => b.textContent === '保存名称').fire('click');
  assert.equal(stateWrites.at(-1).title, '雨夜决战定稿会话');

  await agent.querySelectorAll('button').find(b => b.textContent === '归档会话').fire('click');
  assert.equal(agent.querySelectorAll('.cc-agent-session').length, 0);
  await agent.querySelector('.cc-agent-archive-toggle').fire('click');
  assert.equal(agent.querySelectorAll('.cc-agent-session').length, 1);
  assert.match(agent.querySelector('.cc-agent-session').textContent, /已归档/);
  f.panel.suspend();
});

test('canvas-persistence-worker fallback client stores, diffs and clears snapshots cleanly', async () => {
  const mod = await loadModule('canvas-persistence-worker.js', { window: {}, console });
  const client = mod.createCanvasPersistenceClient({});
  const syncRes = await client.syncSnapshot({ canvasId: 'c-snap', title: '离线快照', version: 3, document: { nodes: [{ id: 'n1', type: 'text' }], edges: [] } });
  assert.equal(syncRes.ok, true);
  assert.equal(syncRes.dirtyCount, 2);
  const loaded = await client.readSnapshot('c-snap');
  assert.equal(loaded.snapshot.title, '离线快照');
  assert.equal(loaded.snapshot.version, 3);
  await client.clearSnapshot('c-snap');
  const cleared = await client.readSnapshot('c-snap');
  assert.equal(cleared.snapshot, null);
  client.dispose();
});
