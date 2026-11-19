import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {catalogueFor} from '../../support/fixtures/frontend/canvas_capabilities.cjs';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

class FakeElement {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.value = '';
    this.disabled = false;
    this.style = { removeProperty(k) { delete this[k]; } };
    this.offsetWidth = 220;
    this.offsetHeight = 260;
    this.clientWidth = 1280;
    this.clientHeight = 820;
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
  prepend(...nodes) { for (const node of [...nodes].reverse()) { node.remove(); node.parentElement = this; this.children.unshift(node); } }
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
      if (!match) return false;
      const attrName = match[1];
      const val = attrName.startsWith('data-')
        ? (this.dataset[attrName.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] ?? this.attrs[attrName])
        : this.attrs[attrName];
      return match[2] == null ? val != null : String(val) === match[2];
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
}

const TEST_MODELS = [
  {
    id: 'model-gpt-26',
    name: 'GImage 2.6 Pro',
    model_key: 'gpt-image-2.6-pro_sr',
    model_version: 'v1',
    modality: 'image',
    supplier: 'openai',
    enabled: true,
    adapter_available: true,
    capabilities: { purposes: ['first_frame', 'image_edit'], reference_media: true, max_reference_images: 8 },
    default_params: {},
  },
  {
    id: 'model-seedream-55',
    name: '火山 Seedream 5.5',
    model_key: 'doubao-seedream-5-5-261028',
    model_version: 'v1',
    modality: 'image',
    supplier: 'volcengine',
    enabled: true,
    adapter_available: true,
    capabilities: { purposes: ['first_frame', 'image_edit'], reference_media: true, max_reference_images: 10 },
    default_params: {},
  },
];

async function createComposerFixture({
  nodes = [],
  edges = [],
  models = TEST_MODELS,
  promptAssist = { available: false, unavailable_reason: '本机未安装或未接通文本翻译宿主（grok CLI），翻译不可用' },
  localStorageData = {},
  quoteHandler = null,
  translateHandler = null,
  jobs = {},
  steps = [],
} = {}) {
  const sessionMap = new Map();
  const localMap = new Map(Object.entries(localStorageData));
  const apiCalls = [];
  const timers = new Map();
  let nextTimerId = 1;
  const clipboardWrites = [];

  const document = {
    createElement: tag => {
      const n = new FakeElement(tag);
      n.ownerDocument = document;
      if (tag === 'canvas') {
        n.getContext = () => ({ clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, drawImage() {}, getImageData: () => ({ data: new Uint8ClampedArray(32) }) });
      }
      return n;
    },
    createElementNS: (ns, tag) => { const n = document.createElement(tag); n.namespaceURI = ns; return n; },
    createTextNode: text => { const n = new FakeElement('#text', text); n.ownerDocument = document; return n; },
    documentElement: {},
  };

  const winListeners = new Map();
  const window = {
    localStorage: {
      getItem: k => localMap.get(k) ?? null,
      setItem: (k, v) => localMap.set(k, String(v)),
      removeItem: k => localMap.delete(k),
    },
    addEventListener(type, fn) { (winListeners.get(type) || winListeners.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { winListeners.get(type)?.delete(fn); },
    fire(type, event = {}) { for (const fn of [...(winListeners.get(type) || [])]) fn(event); },
  };

  const setTimeoutFn = (fn, delay = 0) => {
    const id = nextTimerId++;
    timers.set(id, { id, fn, delay });
    return id;
  };
  const clearTimeoutFn = id => { timers.delete(id); };

  async function flushTimers(predicate = () => true) {
    const matching = [...timers.values()].filter(predicate);
    for (const item of matching) {
      if (!timers.has(item.id)) continue;
      timers.delete(item.id);
      await item.fn();
    }
    await new Promise(r => setTimeout(r, 0));
  }

  let savedDoc = { viewport: { x: 0, y: 0, zoom: 1 }, nodes: structuredClone(nodes), edges: structuredClone(edges) };
  let currentJobs = structuredClone(jobs);
  let currentSteps = structuredClone(steps);
  let canvasRev = 1;
  let projectRev = 2;

  const catalogue = catalogueFor(models);
  const mod = await loadModule('creative-canvas.js', {
    document,
    window,
    navigator: {
      clipboard: {
        writeText: async text => { clipboardWrites.push(text); },
      },
    },
    location: { search: '', href: 'http://127.0.0.1:8765/?page=creative-canvas', assign() {} },
    sessionStorage: {
      getItem: k => sessionMap.get(k) ?? null,
      setItem: (k, v) => sessionMap.set(k, String(v)),
      removeItem: k => sessionMap.delete(k),
    },
    crypto,
    console,
    Image: class {},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
    setTimeout: setTimeoutFn,
    clearTimeout: clearTimeoutFn,
  });

  const root = document.createElement('main');
  const session = { actor: 'tester', csrf: 'csrf-tok', revision: projectRev, writable: true };

  const api = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    apiCalls.push({ path, method: options.method || 'GET', body });

    if (path.endsWith('/creative-canvas-settings-models')) {
      return { models: [] };
    }
    if (path.endsWith('/creative-canvas-run-options')) {
      return {
        ...structuredClone(catalogue),
        models: structuredClone(models),
        nodes: [],
        revision: projectRev,
        image_tools: {},
        prompt_assist: structuredClone(promptAssist),
      };
    }
    if (path.endsWith('/creative-canvases')) {
      return { items: [{ id: 'c1', title: '测试画布', version: canvasRev }] };
    }
    if (path.endsWith('/creative-canvases/c1') && (!options.method || options.method === 'GET')) {
      return {
        id: 'c1',
        title: '测试画布',
        canvas_revision: canvasRev,
        version_id: 'v' + canvasRev,
        revision: projectRev,
        document: structuredClone(savedDoc),
        jobs: structuredClone(currentJobs),
        runs: [],
        execution_steps: structuredClone(currentSteps),
      };
    }
    if (path.endsWith('/creative-canvases/c1') && options.method === 'PUT') {
      savedDoc = structuredClone(body.payload.document);
      canvasRev += 1;
      projectRev += 1;
      return { id: 'c1', canvas_revision: canvasRev, version_id: 'v' + canvasRev, revision: projectRev };
    }
    if (path.endsWith('/work-quote')) {
      if (quoteHandler) return await quoteHandler(body.payload);
      if (body.payload.draft_version_id) {
        return {
          revision: projectRev,
          ready: true,
          preview_sha256: 'a'.repeat(64),
          generation_quote: { jobs: [{ operation: 'op:0', native_units: { images: 1 } }] },
          commerce_quote: { enabled: false },
        };
      }
      const c = body.payload.count || 1;
      return {
        project_id: 'p1',
        revision: projectRev,
        ready: true,
        read_only: true,
        total_price: c * 2,
        price_basis: 'commerce_credits',
        gaps: [],
      };
    }
    if (path.endsWith('/work-input')) {
      projectRev += 1;
      return { revision: projectRev, draft_version_id: 'draft-1', node_id: body.payload.node_id };
    }
    if (path.endsWith('/generate')) {
      projectRev += 1;
      const jobId = 'job-task-99';
      currentSteps = [{ id: 'step-1', node_key: body.payload.node_id, jobs: [{ id: jobId, status: 'queued' }] }];
      return { revision: projectRev, node_id: body.payload.node_id, step_id: 'step-1', run_version_id: 'run-1', jobs: [jobId] };
    }
    if (path.endsWith('/prompt-translate')) {
      if (translateHandler) return await translateHandler(body.payload);
      return { text: 'A lone traveler walking in a snowy night', target_language: 'en' };
    }
    return { revision: projectRev, items: [] };
  };

  const panel = mod.createCreativeCanvasPanel({
    api,
    session: () => session,
    setRevision: r => { session.revision = r; },
  });
  await panel.load(root, 'p1', null, 'c1');
  await new Promise(r => setTimeout(r, 0));

  return {
    root,
    panel,
    apiCalls,
    timers,
    flushTimers,
    clipboardWrites,
    getSavedDoc: () => structuredClone(savedDoc),
    setJobs: next => { currentJobs = structuredClone(next); },
    setSteps: next => { currentSteps = structuredClone(next); },
  };
}

async function selectNodeById(f, id) {
  const card = f.root.querySelectorAll('.cc-node').find(n => n.dataset.nodeId === id);
  assert.ok(card, `missing node card ${id}`);
  await card.querySelector('.cc-node-head').fire('click');
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
}

test('inline generator composer renders 1:1 controls, camera wheel, style slot and advanced drawer on selected image node', async () => {
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 120, y: 120, text: '', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({ nodes: [imgNode] });
  await selectNodeById(f, 'n1');

  const inspector = f.root.querySelector('.cc-inspector');
  assert.equal(inspector.hidden, false);
  assert.equal(inspector.classList.contains('cgc-active'), true);

  // Top bar: +参考 | 聚焦 | 放大/退出放大
  const refBtn = inspector.querySelector('.cgc-ref-btn');
  const focusBtn = inspector.querySelector('.cgc-focus-btn');
  const expandBtn = inspector.querySelector('.cgc-expand-btn');
  assert.equal(refBtn.textContent, '参考');
  assert.equal(focusBtn.textContent, '聚焦');
  assert.equal(expandBtn.getAttribute('aria-label'), '放大');

  await expandBtn.fire('click');
  assert.equal(inspector.classList.contains('cgc-expanded'), true);
  assert.equal(inspector.querySelector('.cgc-expand-btn').getAttribute('aria-label'), '退出放大');

  // Prompt placeholder matches reference verbatim
  const prompt = inspector.querySelector('.cgc-prompt-input');
  assert.equal(
    prompt.getAttribute('placeholder'),
    '可直接文字生图，或上传图片输入文字指令对图片进行编辑，如：将背景改为雪夜',
  );

  // Bottom bar left-to-right controls
  assert.equal(inspector.querySelector('.cgc-model-trigger').textContent, 'GImage 2.6 Pro');
  assert.equal(inspector.querySelector('.cgc-format-trigger').textContent, 'PNG');
  assert.equal(inspector.querySelector('.cgc-specs-trigger').textContent, '9:16 · 标准 · 2K · 1张');
  assert.ok(inspector.querySelector('.cgc-camera-trigger'));
  assert.equal(inspector.querySelector('.cgc-style-trigger').textContent, '风格');
  assert.ok(inspector.querySelector('.cgc-translate-btn'));
  assert.ok(inspector.querySelector('.cgc-advanced-btn'));

  // Camera hover preview & 4-column wheel panel
  assert.match(inspector.querySelector('.cgc-camera-hover').textContent, /Sony Venice \| Zeiss Ultra Prime \/ 8mm \/ f\/1\.4.*已关闭/);
  await inspector.querySelector('.cgc-camera-trigger').fire('click');
  const camPanel = inspector.querySelector('.cgc-camera-panel');
  assert.ok(camPanel);
  assert.equal(camPanel.querySelectorAll('.cgc-camera-col').length, 4);
  const alexaBtn = camPanel.querySelector('[data-camera-value="arri_alexa_35"]');
  await alexaBtn.fire('click');
  assert.equal(inspector.querySelector('.cgc-camera-trigger').classList.contains('is-enabled'), true);

  // Style entry with tabs & slot (#11)
  await inspector.querySelector('.cgc-style-trigger').fire('click');
  const stylePop = inspector.querySelector('.cgc-style-popover');
  assert.ok(stylePop);
  assert.deepEqual(
    stylePop.querySelectorAll('.cgc-style-tab').map(b => b.textContent),
    ['官方', '我的', '3D', '真人', '2D'],
  );
  assert.ok(stylePop.querySelector('[data-style-id="none"]'));

  // Advanced settings drawer with 智能引用 switch
  await inspector.querySelector('.cgc-advanced-btn').fire('click');
  const advDrawer = inspector.querySelector('.cgc-advanced-drawer');
  assert.ok(advDrawer);
  const smartSwitch = advDrawer.querySelector('[aria-label="智能引用"]');
  assert.equal(smartSwitch.getAttribute('aria-checked'), 'true');
  await smartSwitch.fire('click');
  assert.equal(inspector.querySelector('[aria-label="智能引用"]').getAttribute('aria-checked'), 'false');

  f.panel.suspend();
});

test('switching models converges format, resolution, background and aspect ratio options from backend model_params', async () => {
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 80, y: 80, text: '雪夜街道', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({ nodes: [imgNode] });
  await selectNodeById(f, 'n1');
  const inspector = f.root.querySelector('.cc-inspector');

  // On GImage 2.6 Pro: choose 4K, transparent background, and 4:5 ratio
  await inspector.querySelector('.cgc-specs-trigger').fire('click');
  let specsPop = inspector.querySelector('.cgc-specs-popover');
  assert.deepEqual(specsPop.querySelectorAll('[data-resolution]').map(b => b.textContent), ['1K', '2K', '4K']);
  await specsPop.querySelector('[data-resolution="4K"]').fire('click');
  specsPop = inspector.querySelector('.cgc-specs-popover');
  await specsPop.querySelector('[data-background="transparent"]').fire('click');
  specsPop = inspector.querySelector('.cgc-specs-popover');
  await specsPop.querySelector('[data-ratio="4:5"]').fire('click');
  assert.equal(inspector.querySelector('.cgc-specs-trigger').textContent, '4:5 · 标准 · 4K · 1张');

  // Switch model to Seedream 5.5 (supports 1.5K/2K only, auto/opaque only, no 4:5 ratio)
  await inspector.querySelector('.cgc-model-trigger').fire('click');
  const seedreamOpt = inspector.querySelector('[data-model-id="model-seedream-55"]');
  assert.ok(seedreamOpt);
  await seedreamOpt.fire('click');

  assert.equal(inspector.querySelector('.cgc-model-trigger').textContent, 'Seedream 5.5');
  assert.equal(inspector.querySelector('.cgc-specs-trigger').textContent, '9:16 · 标准 · 2K · 1张');

  await inspector.querySelector('.cgc-specs-trigger').fire('click');
  specsPop = inspector.querySelector('.cgc-specs-popover');
  assert.deepEqual(specsPop.querySelectorAll('[data-resolution]').map(b => b.textContent), ['1.5K', '2K']);
  assert.deepEqual(specsPop.querySelectorAll('[data-background]').map(b => b.textContent), ['自动', '保留背景']);
  assert.equal(specsPop.querySelector('[data-ratio="4:5"]'), null);

  f.panel.suspend();
});

test('browser-only Cloud API Key models from API settings are listed with explicit disabled reason and never leak keys', async () => {
  const storedApiCfg = {
    activeProvider: 'gpt',
    providers: {
      gpt: { baseUrl: 'https://api.openai.com/v1', apiKey: 'sk-secret-browser-only-key', model: 'gpt-image-2.5', customModel: '' },
      gemini: { baseUrl: 'https://generativelanguage.googleapis.com', apiKey: '', model: 'gemini-3.1-flash-image-preview', customModel: '' },
    },
  };
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 80, y: 80, text: '测试', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({
    nodes: [imgNode],
    localStorageData: { pose_atlas_api_config_v3: JSON.stringify(storedApiCfg) },
  });
  await selectNodeById(f, 'n1');
  const inspector = f.root.querySelector('.cc-inspector');

  await inspector.querySelector('.cgc-model-trigger').fire('click');
  const browserModelOpt = inspector.querySelector('[data-model-key="gpt-image-2.5"]');
  assert.ok(browserModelOpt, 'browser API-key model must be visible in dropdown');
  assert.equal(browserModelOpt.getAttribute('aria-disabled'), 'true');
  assert.match(browserModelOpt.textContent, /画布服务端任务队列不读取浏览器密钥/);
  assert.equal(JSON.stringify(f.apiCalls).includes('sk-secret-browser-only-key'), false);

  f.panel.suspend();
});

test('real-time quote debounces parameter changes and supports failure retry without manual quote click', async () => {
  let failNext = false;
  const quotePayloads = [];
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 80, y: 80, text: '霓虹夜景', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({
    nodes: [imgNode],
    quoteHandler: async payload => {
      quotePayloads.push(payload);
      if (failNext) throw new Error('网络繁忙');
      return { project_id: 'p1', revision: 2, ready: true, read_only: true, total_price: payload.count * 8, price_basis: 'commerce_credits', gaps: [] };
    },
  });
  await selectNodeById(f, 'n1');
  await f.flushTimers(t => t.delay === 300);

  const inspector = f.root.querySelector('.cc-inspector');
  assert.equal(inspector.querySelector('.cgc-quote-amount').textContent, '8');
  assert.equal(quotePayloads.length, 1);

  // Rapidly change count 1 -> 2 -> 4; debounce coalesces into a single work-quote call
  await inspector.querySelector('.cgc-specs-trigger').fire('click');
  await inspector.querySelector('[data-count="2"]').fire('click');
  await inspector.querySelector('[data-count="4"]').fire('click');
  assert.equal(quotePayloads.length, 1, 'must debounce before 300ms');

  await f.flushTimers(t => t.delay === 300);
  assert.equal(quotePayloads.length, 2);
  assert.equal(quotePayloads.at(-1).count, 4);
  assert.equal(f.root.querySelector('.cgc-quote-amount').textContent, '32');

  // Failure displays reference copy + retry button
  failNext = true;
  await f.root.querySelector('[data-count="1"]').fire('click');
  await f.flushTimers(t => t.delay === 300);
  assert.match(f.root.querySelector('.cgc-quote-box').textContent, /获取积分报价失败，请刷新页面后重试。.*重试/);

  failNext = false;
  await f.root.querySelector('.cgc-quote-retry').fire('click');
  await new Promise(r => setTimeout(r, 0));
  assert.equal(f.root.querySelector('.cgc-quote-amount').textContent, '8');

  f.panel.suspend();
});

test('5-second countdown allows cancelling with zero tasks created, and submits + copies TaskID on completion', async () => {
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 80, y: 80, text: '赛博城市', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({ nodes: [imgNode] });
  await selectNodeById(f, 'n1');
  await f.flushTimers(t => t.delay === 300);

  // 1. Trigger send -> 5s countdown starts; cancel at 3s -> zero /work-input or /generate calls
  await f.root.querySelector('.cgc-send-btn').fire('click');
  assert.match(f.root.querySelector('.cgc-countdown-pill').textContent, /5s 后提交.*撤回任务/);
  assert.match(f.root.querySelector('.cgc-node-runbar').textContent, /待提交 · 5s 后提交/);

  await f.flushTimers(t => t.delay === 1000);
  await f.flushTimers(t => t.delay === 1000);
  assert.match(f.root.querySelector('.cgc-countdown-pill').textContent, /3s 后提交/);

  await f.root.querySelector('.cgc-cancel-submit-btn').fire('click');
  await f.flushTimers();
  assert.equal(f.apiCalls.some(c => c.path.endsWith('/work-input')), false);
  assert.equal(f.apiCalls.some(c => c.path.endsWith('/generate')), false);
  assert.match(f.root.querySelector('.cgc-node-runbar').textContent, /已取消/);

  // 2. Trigger send again and let all 5 seconds complete -> submits and displays status + copyable TaskID
  await f.root.querySelector('.cgc-send-btn').fire('click');
  for (let i = 0; i < 5; i++) {
    await f.flushTimers(t => t.delay === 1000);
  }
  // Allow save timer or async chain to finish
  await f.flushTimers();
  await new Promise(r => setTimeout(r, 10));

  assert.equal(f.apiCalls.some(c => c.path.endsWith('/work-input')), true);
  assert.equal(f.apiCalls.some(c => c.path.endsWith('/generate')), true);

  const runbar = f.root.querySelector('.cgc-node-runbar');
  assert.match(runbar.textContent, /排队中/);
  const copyBtn = runbar.querySelector('.cgc-copy-taskid');
  assert.ok(copyBtn);
  assert.equal(copyBtn.dataset.taskId, 'job-task-99');
  await copyBtn.fire('click');
  assert.deepEqual(f.clipboardWrites, ['job-task-99']);

  f.panel.suspend();
});

test('translate button disables with reason when host unavailable and translates prompt when available', async () => {
  const imgNode = { id: 'n1', type: 'image', title: '图片生成', x: 80, y: 80, text: '雪夜旅人', params: {}, media_id: null, job_id: null, group: '' };

  const disabledFixture = await createComposerFixture({
    nodes: [imgNode],
    promptAssist: { available: false, unavailable_reason: '本机未安装 grok CLI' },
  });
  await selectNodeById(disabledFixture, 'n1');
  const disabledBtn = disabledFixture.root.querySelector('.cgc-translate-btn');
  assert.equal(disabledBtn.disabled, true);
  assert.equal(disabledBtn.title, '本机未安装 grok CLI');
  disabledFixture.panel.suspend();

  const enabledFixture = await createComposerFixture({
    nodes: [imgNode],
    promptAssist: { available: true, unavailable_reason: '' },
  });
  await selectNodeById(enabledFixture, 'n1');
  const enabledBtn = enabledFixture.root.querySelector('.cgc-translate-btn');
  assert.equal(enabledBtn.disabled, false);
  await enabledBtn.fire('click');
  await new Promise(r => setTimeout(r, 10));
  assert.equal(
    enabledFixture.root.querySelector('.cgc-prompt-input').value,
    'A lone traveler walking in a snowy night',
  );
  enabledFixture.panel.suspend();
});

test('generator parameters persist with canvas save and restore on node re-selection and canvas reload', async () => {
  const nodeA = { id: 'a', type: 'image', title: '镜头A', x: 80, y: 80, text: '雨夜巷口', params: {}, media_id: null, job_id: null, group: '' };
  const nodeB = { id: 'b', type: 'image', title: '镜头B', x: 380, y: 80, text: '清晨天台', params: {}, media_id: null, job_id: null, group: '' };
  const f = await createComposerFixture({ nodes: [nodeA, nodeB] });

  await selectNodeById(f, 'a');
  const inspector = f.root.querySelector('.cc-inspector');

  // Switch model -> Seedream 5.5, format -> WEBP, quality -> high, resolution -> 1.5K, ratio -> 16:9, count -> 2
  await inspector.querySelector('.cgc-model-trigger').fire('click');
  await inspector.querySelector('[data-model-id="model-seedream-55"]').fire('click');

  await inspector.querySelector('.cgc-format-trigger').fire('click');
  await inspector.querySelector('[data-format="webp"]').fire('click');

  await inspector.querySelector('.cgc-specs-trigger').fire('click');
  await inspector.querySelector('[data-quality="high"]').fire('click');
  await inspector.querySelector('[data-resolution="1.5K"]').fire('click');
  await inspector.querySelector('[data-ratio="16:9"]').fire('click');
  await inspector.querySelector('[data-count="2"]').fire('click');

  assert.equal(inspector.querySelector('.cgc-specs-trigger').textContent, '16:9 · 高 · 1.5K · 2张');

  // Flush 1000ms auto-save timer so canvas PUT persists node.params
  await f.flushTimers(t => t.delay === 1000);
  const persisted = f.getSavedDoc().nodes.find(n => n.id === 'a');
  assert.equal(persisted.params.vsc_gen_model_id, 'model-seedream-55');
  assert.equal(persisted.params.vsc_gen_output_format, 'webp');
  assert.equal(persisted.params.vsc_gen_quality, 'high');
  assert.equal(persisted.params.vsc_gen_resolution, '1.5K');
  assert.equal(persisted.params.vsc_gen_ratio, '16:9');
  assert.equal(persisted.params.vsc_gen_count, 2);

  // Switch to node B (defaults), then switch back to node A
  await selectNodeById(f, 'b');
  assert.equal(f.root.querySelector('.cgc-model-trigger').textContent, 'GImage 2.6 Pro');
  assert.equal(f.root.querySelector('.cgc-specs-trigger').textContent, '9:16 · 标准 · 2K · 1张');

  await selectNodeById(f, 'a');
  assert.equal(f.root.querySelector('.cgc-model-trigger').textContent, 'Seedream 5.5');
  assert.equal(f.root.querySelector('.cgc-format-trigger').textContent, 'WEBP');
  assert.equal(f.root.querySelector('.cgc-specs-trigger').textContent, '16:9 · 高 · 1.5K · 2张');
  f.panel.suspend();

  // Reload fresh canvas instance from saved document
  const reloaded = await createComposerFixture({ nodes: f.getSavedDoc().nodes });
  await selectNodeById(reloaded, 'a');
  assert.equal(reloaded.root.querySelector('.cgc-model-trigger').textContent, 'Seedream 5.5');
  assert.equal(reloaded.root.querySelector('.cgc-format-trigger').textContent, 'WEBP');
  assert.equal(reloaded.root.querySelector('.cgc-specs-trigger').textContent, '16:9 · 高 · 1.5K · 2张');
  reloaded.panel.suspend();
});
