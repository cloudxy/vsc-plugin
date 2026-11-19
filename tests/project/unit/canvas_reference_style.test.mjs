import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  BUILTIN_STYLES,
  applyCanvasReferencePick,
  applyMention,
  applyStyleToNode,
  attachCanvasReferenceStyle,
  canDirectlyGenerate,
  clearGeneratorStyle,
  collectInputIssues,
  commitFocusCapture,
  createStyleStore,
  cropRectPixels,
  generationBlockReason,
  handleCanvasReferenceKey,
  listStyles,
  markCanvasNodeKind,
  mentionAtCaret,
  mentionCandidates,
  mentionKeyAction,
  mixedBindingState,
  moveMentionIndex,
  openInputPreflight,
  optimizeButtonState,
  referencePortFor,
  rememberMediaMetrics,
  removeFocusNode,
  replaceEdgeWithCropCopy,
  resolveNodeKind,
  selectionNormFromPointers,
  smartCropNorm,
  spawnImageToImage,
  styleLabelFor,
} from '../../../src/vsc/interfaces/web/static/canvas-reference-style.js';

class FakeElement {
  constructor(tag) {
    this.tagName = String(tag || 'div').toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.className = '';
    this.value = '';
    this.disabled = false;
    this.hidden = false;
    this.parentElement = null;
    this.classList = {
      add: (...values) => { this.className = [...new Set([...this.className.split(' '), ...values])].filter(Boolean).join(' '); },
      remove: (...values) => { this.className = this.className.split(' ').filter(item => !values.includes(item)).join(' '); },
      contains: value => this.className.split(' ').includes(value),
    };
  }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return (this._text || '') + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { for (const node of nodes) { node.remove?.(); node.parentElement = this; this.children.push(node); } }
  prepend(...nodes) {
    const prepared = [];
    for (const node of nodes) { node.remove?.(); node.parentElement = this; prepared.push(node); }
    this.children.unshift(...prepared);
  }
  remove() { this.parentElement?.children && (this.parentElement.children = this.parentElement.children.filter(child => child !== this)); this.parentElement = null; }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this._text = ''; this.append(...nodes); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('[')) {
      const match = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      if (!match) return false;
      const name = match[1];
      const value = name.startsWith('data-')
        ? (this.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] ?? this.attrs[name])
        : this.attrs[name];
      return match[2] == null ? value != null : String(value) === match[2];
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const values = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return values;
    return values.filter(node => selector.split(',').some(part => node.matches(part.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  async fire(type, properties = {}) {
    const event = {target: this, clientX: 0, clientY: 0, preventDefault() {}, stopPropagation() {}, ...properties};
    for (const fn of this.listeners[type] || []) await fn(event);
  }
  focus() { this.ownerDocument.activeElement = this; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  getBoundingClientRect() { return {left: 0, top: 0, width: 200, height: 100}; }
}

function documentStub() {
  const document = {activeElement: null};
  document.createElement = tag => {
    const node = new FakeElement(tag);
    node.ownerDocument = document;
    return node;
  };
  document.addEventListener = (type, fn) => { (document.listeners ??= {})[type] = fn; };
  return document;
}

function session() {
  const doc = documentStub();
  const root = doc.createElement('main');
  const inspector = doc.createElement('section');
  root.append(inspector);
  return {
    doc,
    root,
    s: {
      root,
      inspector,
      readOnly: false,
      document: {nodes: [], edges: []},
      selected: new Set(),
      mediaMetrics: {},
      world: {querySelectorAll: () => []},
      composerRunOptions: null,
      doc,
    },
  };
}

test('source nodes cannot generate, generators can, and legacy canvases stay compatible', () => {
  const legacy = {id: 'old', type: 'image', media_id: 'm', params: {}, job_id: 'job-1'};
  assert.equal(resolveNodeKind(legacy), 'legacy');
  assert.equal(canDirectlyGenerate(legacy), true);
  assert.equal(generationBlockReason(legacy), '');
  const source = markCanvasNodeKind({id: 's', type: 'image', params: {}}, 'source');
  assert.equal(source.params.vsc_node_kind, 'source');
  assert.equal(Object.hasOwn(source, 'node_kind'), false);
  assert.equal(canDirectlyGenerate(source), false);
  assert.equal(generationBlockReason(source), '素材节点不能发起生成');
  const generator = markCanvasNodeKind({id: 'g', type: 'image', params: {}}, 'generator');
  assert.equal(canDirectlyGenerate(generator), true);
  const document = {nodes: [source], edges: []};
  let n = 0;
  const created = spawnImageToImage(document, source, () => `n${++n}`);
  assert.equal(created.params.vsc_node_kind, 'generator');
  assert.equal(created.params.vsc_operation, 'image_generate');
  assert.equal(document.edges[0].port, 'reference');
  assert.equal(document.edges[0].source, 's');
});

test('@ mention inserts the node name and creates the reference edge', () => {
  const target = {id: 'g', type: 'image', title: '图片生成', text: '夜色 @雪', params: {}};
  const snow = {id: 'a', type: 'image', title: '雪夜', params: {}};
  const document = {nodes: [target, snow, {id: 'b', type: 'audio', title: '雨声', params: {}}], edges: []};
  const at = mentionAtCaret(target.text, target.text.length);
  assert.equal(at.query, '雪');
  assert.deepEqual(mentionCandidates(document, target, '雪').map(node => node.id), ['a']);
  assert.equal(mentionKeyAction({key: 'ArrowDown', isComposing: true}, {open: true}), 'ignore');
  assert.equal(mentionKeyAction({key: 'Enter'}, {open: true}), 'select');
  assert.equal(moveMentionIndex(0, 2, -1), 1);
  const applied = applyMention(document, target, snow, at, () => 'edge-1');
  assert.equal(applied.text, '夜色 @雪夜');
  assert.equal(document.edges[0].source, 'a');
  assert.equal(document.edges[0].port, 'reference');
  assert.equal(target.params.vsc_mixed_sig, undefined);
});

test('mention menu selects a candidate from the keyboard', async () => {
  const {s, root} = session();
  const node = {id: 'g', type: 'image', title: '图片生成', text: '@', params: {}};
  const snow = {id: 'a', type: 'image', title: '雪夜', params: {}};
  s.document.nodes = [node, snow];
  const textarea = s.doc.createElement('textarea');
  textarea.value = '@';
  textarea.selectionStart = 1;
  textarea.setAttribute('aria-label', '文本或提示词');
  s.inspector.append(textarea);
  const helpers = {change(_s, fn) { fn(); }, notice() {}, draw() {}, live: () => true};
  attachCanvasReferenceStyle(helpers);
  helpers.bindPromptMentions(textarea, {s, node, doc: s.doc});
  await textarea.fire('input');
  assert.equal(root.querySelector('.crs-mention-menu').getAttribute('aria-label'), '素材引用');
  assert.match(root.textContent, /雪夜/);
  await textarea.fire('keydown', {key: 'Enter'});
  assert.equal(node.text, '@雪夜');
  assert.equal(s.document.edges[0].port, 'reference');
  assert.equal(textarea.selectionStart, '@雪夜'.length);
});

test('canvas pick creates an edge and rejects self, duplicate and incompatible nodes', () => {
  const generator = {id: 'g', type: 'image', title: '图片生成', params: {}};
  const video = {id: 'v', type: 'video', title: '视频', params: {vsc_operation: 'head_tail_video'}};
  const image = {id: 'a', type: 'image', title: '雪夜', params: {}};
  const audio = {id: 'b', type: 'audio', title: '雨声', params: {}};
  const s = {document: {nodes: [generator, video, image, audio], edges: []}, selected: new Set(), referencePick: {targetId: 'g'}};
  const notices = [];
  const hooks = {change(_s, fn) { fn(); }, notice(_s, message) { notices.push(message); }, draw() {}, idFactory: () => 'e1'};
  assert.equal(referencePortFor({edges: []}, video, image), 'first_frame');
  assert.equal(applyCanvasReferencePick(s, image, hooks), true);
  assert.equal(s.document.edges[0].port, 'reference');
  assert.equal(s.referencePick, null);
  s.referencePick = {targetId: 'g'};
  applyCanvasReferencePick(s, image, {...hooks, idFactory: () => 'e2'});
  assert.equal(notices.at(-1), '已引用');
  assert.equal(s.document.edges.length, 1);
  s.referencePick = {targetId: 'g'};
  applyCanvasReferencePick(s, generator, hooks);
  assert.equal(notices.at(-1), '节点不能连接到自身。');
  s.referencePick = {targetId: 'g'};
  applyCanvasReferencePick(s, audio, hooks);
  assert.equal(notices.at(-1), '该节点不能作为参考');
  assert.equal(s.referencePick.targetId, 'g');
  s.referencePick = {targetId: 'missing'};
  applyCanvasReferencePick(s, image, hooks);
  assert.equal(notices.at(-1), '已退出参考选择');
  assert.equal(handleCanvasReferenceKey({referencePick: {targetId: 'g'}, _crs: {}}, {key: 'Escape'}, {notice(_s, message) { notices.push(message); }, draw() {}}), true);
});

test('mixed binding stays confirmed until the prompt or assets change', () => {
  const node = {id: 'g', type: 'video', text: '@雪夜', params: {}};
  const document = {
    nodes: [node, {id: 'a', title: '雪夜', type: 'image'}],
    edges: [{id: 'e', source: 'a', target: 'g', port: 'first_frame'}, {id: 'o', source: 'a', target: 'g', port: 'reference_image'}],
  };
  const first = mixedBindingState(node, document);
  assert.equal(first.pending, true);
  assert.equal(first.conflict, true);
  node.params.vsc_mixed_sig = first.signature;
  assert.equal(mixedBindingState(node, document).pending, false);
  node.text = '@雪夜 改';
  const changed = mixedBindingState(node, document);
  assert.equal(changed.changed, true);
  assert.equal(changed.pending, true);
  assert.match(changed.signature, /雪夜/);
});

test('focus capture crops a region, uploads it and can replace or delete the capture', async () => {
  const {s} = session();
  const generator = {id: 'g', type: 'image', title: '图片生成', x: 10, y: 10, text: '', params: {}, media_id: null};
  const source = {id: 'a', type: 'image', title: '原图', x: 0, y: 0, text: '', params: {}, media_id: 'm1'};
  s.document.nodes = [generator, source];
  let uploads = 0;
  const created = await commitFocusCapture(s, {
    generator,
    source,
    norm: {x: 0.1, y: 0.2, w: 0.3, h: 0.4},
    width: 200,
    height: 100,
    helpers: {change(_s, fn) { fn(); }, notice() {}},
    rasterize: async () => new Blob(['png']),
    uploadImageBlob: async () => `focus-${++uploads}`,
    idFactory: (() => { let n = 0; return () => `f${++n}`; })(),
  });
  assert.equal(created.params.vsc_focus_capture, '1');
  assert.equal(created.params.vsc_node_kind, 'source');
  assert.equal(created.title, '聚焦截图');
  assert.equal(s.document.edges[0].target, 'g');
  assert.equal(s.selected.has('g'), true);
  const replaced = await commitFocusCapture(s, {
    generator, source, norm: {x: 0, y: 0, w: 1, h: 1}, width: 20, height: 20, replace: true,
    helpers: {change(_s, fn) { fn(); }, notice() {}},
    rasterize: async () => new Blob(['png']),
    uploadImageBlob: async () => 'focus-2',
    idFactory: (() => { let n = 10; return () => `f${++n}`; })(),
  });
  assert.equal(s.document.nodes.some(node => node.id === created.id), false);
  assert.equal(replaced.media_id, 'focus-2');
  assert.equal(removeFocusNode(s.document, replaced.id), true);
  assert.equal(s.document.edges.length, 0);
});

test('focus overlay binds the boxed region back to the generator', async () => {
  const {s, root} = session();
  const generator = {id: 'g', type: 'image', title: '图片生成', x: 0, y: 0, text: '', params: {}};
  const source = {id: 'a', type: 'image', title: '原图', x: 0, y: 0, text: '', params: {}, media_id: 'm1'};
  s.document.nodes = [generator, source];
  const helpers = {
    change(_s, fn) { fn(); },
    notice() {},
    draw() {},
    live: () => true,
    mediaContentUrl: () => '/media/m1/content',
  };
  let seq = 0;
  attachCanvasReferenceStyle(helpers, {
    rasterize: async () => new Blob(['png']),
    uploadImageBlob: async () => 'focus-media',
    idFactory: () => `id-${++seq}`,
  });
  helpers.openFocusCapture(s, generator);
  const image = root.querySelector('.crs-focus-image');
  image.naturalWidth = 400;
  image.naturalHeight = 200;
  const stage = root.querySelector('.crs-focus-stage');
  await stage.fire('pointerdown', {clientX: 10, clientY: 10});
  await stage.fire('pointerup', {clientX: 120, clientY: 70});
  assert.ok(stage.dataset.norm);
  await [...root.querySelectorAll('button')].find(button => button.textContent === '聚焦截图').fire('click');
  const capture = s.document.nodes.find(node => node.params.vsc_focus_capture === '1');
  assert.equal(capture.media_id, 'focus-media');
  assert.equal(s.document.edges[0].source, capture.id);
});

test('custom styles persist and selected styles enter the prompt', () => {
  const storage = new Map();
  const bag = {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)};
  const store = createStyleStore(bag);
  const saved = store.saveCustom({name: '夜戏', prompt: '霓虹湿地面'});
  const restored = createStyleStore(bag);
  assert.equal(restored.list('custom', '夜').length, 1);
  assert.equal(restored.list('mine', '').some(style => style.id === saved.id), true);
  assert.equal(listStyles('official', '电影', {custom: [], mine: []}).some(style => style.name === '电影感'), true);
  assert.equal(BUILTIN_STYLES.some(style => style.tab === '3d' && style.name === '黏土定格'), true);
  const node = {text: '雨夜', params: {}};
  applyStyleToNode(node, saved);
  assert.match(node.text, /风格：霓虹湿地面/);
  assert.equal(styleLabelFor(saved.id, node), '夜戏');
  clearGeneratorStyle(node);
  node.params.vsc_gen_style_id = 'none';
  assert.equal(node.text, '雨夜');
  assert.equal(styleLabelFor('none', node), '风格');
  assert.throws(() => restored.saveCustom({name: '', prompt: 'x'}), /风格名称/);
});

test('style slot adds a custom tab without taking the built-in tab class', () => {
  const {s, doc} = session();
  const helpers = {change(_s, fn) { fn(); }, notice() {}, draw() {}, live: () => true};
  attachCanvasReferenceStyle(helpers, {storage: {getItem: () => null, setItem() {}, removeItem() {}}});
  const tabs = doc.createElement('div');
  for (const label of ['官方', '我的', '3D', '真人', '2D']) {
    const button = doc.createElement('button');
    button.className = 'cgc-style-tab';
    button.textContent = label;
    tabs.append(button);
  }
  const root = doc.createElement('div');
  const node = {id: 'g', type: 'image', text: '', params: {}};
  helpers.mountStyleLibrarySlot({root, tabs, tab: 'official', query: '', selectedStyleId: 'none', node, s, ui: {}, doc});
  assert.deepEqual(tabs.querySelectorAll('.cgc-style-tab').map(button => button.textContent), ['官方', '我的', '3D', '真人', '2D']);
  assert.equal(tabs.querySelector('.crs-style-tab').textContent, '自定义');
  assert.match(root.textContent, /电影感/);
});

test('prompt tools expose optimize, cases and image-to-image for source nodes', async () => {
  const {s, root} = session();
  const node = markCanvasNodeKind({id: 's', type: 'image', title: '原图', x: 0, y: 0, text: '雪', params: {}}, 'source');
  s.document.nodes = [node];
  s.composerRunOptions = {prompt_assist: {optimize_available: false, optimize_unavailable_reason: '本机未安装或未接通文本工具宿主（grok CLI），提示词优化不可用'}};
  const helpers = {change(_s, fn) { fn(); }, notice() {}, draw() {}, live: () => true, api: async () => ({text: '优化后的雪夜'})};
  attachCanvasReferenceStyle(helpers);
  const tools = s.doc.createElement('div');
  root.append(tools);
  helpers.mountPromptTools({root: tools, node, promptInput: {value: ''}, s, doc: s.doc});
  const optimize = tools.querySelector('.crs-optimize');
  assert.equal(optimize.disabled, true);
  assert.match(optimize.title, /提示词优化不可用/);
  assert.equal(optimizeButtonState({available: true, count: 10}).title, '提示词优化次数已达上限（最多10次）');
  await tools.querySelector('.crs-cases').fire('click');
  assert.match(root.textContent, /推荐提示词案例/);
  assert.match(root.textContent, /雪夜改景/);
  await tools.querySelector('.crs-i2i').fire('click');
  assert.equal(s.document.nodes.some(item => item.title === '图生图' && item.params.vsc_node_kind === 'generator'), true);
});

test('smart crop math and preflight replace the offending edge with a local copy', async () => {
  assert.deepEqual(smartCropNorm(1000, 500, 1.5), {x: 0.125, y: 0, w: 0.75, h: 1});
  assert.deepEqual(cropRectPixels(1000, 500, smartCropNorm(1000, 500, 1.5)), {x: 125, y: 0, w: 750, h: 500});
  assert.equal(selectionNormFromPointers({left: 0, top: 0, width: 100, height: 50}, 0, 0, 1, 1), null);
  const wide = {edgeId: 'e1', type: 'image', width: 1000, height: 500, mediaId: 'm1', nodeId: 'a'};
  const rules = {image_aspect_max: 1.5, image_aspect_min: 0.4, max_reference_images: 1, image_short_edge_min: 300};
  const issues = collectInputIssues({rules, references: [wide, {edgeId: 'e2', type: 'image', mediaId: 'm2'}]});
  assert.equal(issues[0].message, '最多支持1张参考图');
  assert.match(issues.find(issue => issue.repair === 'smart_crop').message, /参考图1宽高比不能大于1\.5，请裁剪/);
  assert.equal(collectInputIssues({rules: {video_duration_max: 15}, references: [{type: 'video', width: 100, height: 100}]}).length, 0);
  const {s} = session();
  const generator = {id: 'g', type: 'image', title: '图片生成', text: '', params: {vsc_gen_model_id: 'kling'}};
  const source = {id: 'a', type: 'image', title: '宽图', x: 0, y: 0, text: '', params: {}, media_id: 'm1'};
  s.document = {nodes: [generator, source], edges: [{id: 'e1', source: 'a', target: 'g', port: 'reference'}]};
  rememberMediaMetrics(s, 'm1', 1000, 500);
  const helpers = {change(_s, fn) { fn(); }, notice() {}, live: () => true};
  let seq = 0;
  const pending = openInputPreflight(s, generator, helpers, rules, {
    rasterize: async () => new Blob(['png']),
    uploadImageBlob: async () => 'crop-media',
    idFactory: () => `c${++seq}`,
  });
  assert.match(s.root.textContent, /输入问题/);
  assert.match(s.root.textContent, /常见视频\/图片比例示例（从窄到宽）/);
  await s.root.querySelector('.crs-crop-copy').fire('click');
  assert.equal(await pending, true);
  assert.equal(s.document.edges[0].source, 'c1');
  const copy = s.document.nodes.find(node => node.id === 'c1');
  assert.equal(copy.params.vsc_node_kind, 'source');
  assert.match(copy.title, /裁剪副本/);
  assert.equal(copy.media_id, 'crop-media');
});
