import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {Document} = require('../../support/fixtures/frontend/panel_dom.cjs');
const {loadModule} = require('../../support/fixtures/frontend/modules.cjs');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
};
const tags = [{id: 0, label: '全部'}, {id: 1, label: '分类甲'}, {id: 2, label: '分类乙'}];
const feed = (name, extra = {}) => ({ready: true, tags, items: [{name}], total: 1, hasMore: false, ...extra});

async function setup(t, api, {browser, autoLoad = true} = {}) {
  const document = new Document('');
  const createElement = document.createElement.bind(document);
  document.createElement = tag => {
    const node = createElement(tag);
    node.style = {};
    node.getBoundingClientRect = () => ({width: 1000, height: 700});
    node.removeEventListener = (type, callback) => node.listeners.set(type, (node.listeners.get(type) || []).filter(listener => listener !== callback));
    const dispatch = node.dispatch.bind(node);
    node.dispatch = (type, properties = {}) => dispatch(type, {stopPropagation() {}, ...properties});
    if (['video', 'audio'].includes(tag)) {
      node.paused = true;
      node.pause = () => { node.paused = true; node.pauseCount = (node.pauseCount || 0) + 1; };
      node.play = async () => { node.paused = false; };
      node.load = () => {};
    }
    return node;
  };
  document.createElementNS = (_, tag) => document.createElement(tag);
  document.removeEventListener = (type, callback) => document.body.listeners.set(type, (document.body.listeners.get(type) || []).filter(listener => listener !== callback));
  document.head = document.createElement('head');
  const root = document.createElement('main');
  document.body.append(root);
  const timers = new Map(), observers = [], calls = [], notices = [];
  const clipboard = {values: [], error: null};
  let timerId = 0;
  class Observer {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() { this.disconnected = true; }
    trigger() { this.callback([{isIntersecting: true}]); }
  }
  const {createFeaturedShowcase} = await loadModule('featured-showcase.js', {
    document, IntersectionObserver: Observer,
    ...(browser ? {window: browser} : {}),
    navigator: {clipboard: {writeText: async value => { if (clipboard.error) throw clipboard.error; clipboard.values.push(value); }}},
    requestAnimationFrame: callback => setImmediate(callback),
    setTimeout: callback => { const id = ++timerId; timers.set(id, callback); return id; },
    clearTimeout: id => timers.delete(id),
  });
  const app = createFeaturedShowcase(root, {
    api: url => {
      const params = new URL(url, 'http://local').searchParams;
      calls.push({url, tag: params.get('tag_id'), query: params.get('q') || '', offset: Number(params.get('offset'))});
      return Promise.resolve(api(calls.at(-1)));
    }, notice: message => notices.push(message),
  });
  t.after(() => app.suspend());
  if (autoLoad) await app.load();
  return {app, root, document, calls, notices, timers, observers, clipboard, browser,
    tab: name => root.querySelectorAll('button').find(node => node.getAttribute('role') === 'tab' && node.textContent === name),
    selected: () => root.querySelectorAll('button').filter(node => node.getAttribute('aria-selected') === 'true').map(node => node.textContent),
    titles: () => root.querySelectorAll('h2').map(node => node.textContent),
    search: async value => { const input = root.querySelector('input'); input.value = value; await input.dispatch('input'); },
    runSearch: async () => { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } await flush(); },
  };
}

test('rapid categories request the final choice and ignore a late earlier response', async t => {
  const a = deferred(), b = deferred();
  const f = await setup(t, request => request.tag === '1' ? a.promise : request.tag === '2' ? b.promise : feed('初始作品'));
  await f.tab('分类甲').click();
  await f.tab('分类乙').click();
  assert.deepEqual(f.calls.map(call => call.tag), ['0', '1', '2']);
  b.resolve(feed('分类乙作品'));
  await flush();
  a.resolve(feed('分类甲作品'));
  await flush();
  assert.deepEqual(f.selected(), ['分类乙']);
  assert.deepEqual(f.titles(), ['分类乙作品']);
});

test('a new search intent rejects stale successes and errors before the debounce expires', async t => {
  for (const fail of [false, true]) {
    const old = deferred(), latest = deferred();
    const f = await setup(t, request => request.query === '旧' ? old.promise : request.query === '新' ? latest.promise : feed('初始作品'));
    await f.search('旧');
    await f.runSearch();
    await f.search('新');
    if (fail) old.reject(new Error('旧搜索失败'));
    else old.resolve(feed('旧搜索作品'));
    await flush();
    assert.equal(f.titles().includes('旧搜索作品'), false);
    assert.equal(f.root.querySelector('input').value, '新');
    assert.deepEqual(f.notices, []);
    await f.runSearch();
    latest.resolve(feed('新搜索作品'));
    await flush();
    assert.deepEqual(f.titles(), ['新搜索作品']);
    f.app.suspend();
  }
});

test('late old completion cannot unlock an active new-category page request', async t => {
  const old = deferred(), page = deferred();
  const f = await setup(t, request => request.tag === '1' ? old.promise : request.offset ? page.promise : feed(request.tag === '2' ? '分类乙首项' : '初始作品', {hasMore: request.tag === '2', total: 2}));
  await f.tab('分类甲').click();
  await f.tab('分类乙').click();
  await flush();
  const observer = f.observers.at(-1);
  assert.ok(observer);
  observer.trigger();
  old.resolve(feed('分类甲晚到'));
  await flush();
  observer.trigger();
  assert.equal(f.calls.filter(call => call.tag === '2' && call.offset === 1).length, 1);
  page.resolve(feed('分类乙次项', {total: 2}));
  await flush();
  assert.deepEqual(f.titles(), ['分类乙首项', '分类乙次项']);
});

test('a late page and a queued old observer cannot append into a new category', async t => {
  const page = deferred();
  const f = await setup(t, request => request.offset ? page.promise : feed(request.tag === '2' ? '分类乙作品' : '初始作品', {hasMore: request.tag === '0', total: 2}));
  const observer = f.observers.at(-1);
  observer.trigger();
  await f.tab('分类乙').click();
  await flush();
  page.resolve(feed('旧分类翻页'));
  await flush();
  const count = f.calls.length;
  observer.trigger();
  await flush();
  assert.equal(f.calls.length, count);
  assert.deepEqual(f.selected(), ['分类乙']);
  assert.deepEqual(f.titles(), ['分类乙作品']);
});

test('suspending cancels a queued search and discards pending list and process results', async t => {
  for (const fail of [false, true]) {
    const old = deferred(), process = deferred();
    const f = await setup(t, request => request.url.includes('template') ? process.promise : request.tag === '1' ? old.promise : feed('初始作品', {
      items: [{name: '初始作品', templateUuid: 'template', processAvailable: true, processReady: true}],
    }));
    await f.root.querySelectorAll('button').find(node => node.getAttribute('aria-label') === '查看制作过程').click({stopPropagation() {}});
    await f.tab('分类甲').click();
    f.app.suspend();
    old.resolve(feed('离开后的旧作品'));
    if (fail) process.reject(new Error('旧画布错误'));
    else process.resolve({process: {nodes: [], edges: []}});
    await flush();
    assert.equal(f.titles().includes('离开后的旧作品'), false);
    assert.equal(f.document.body.querySelector('.fs-process-layer'), null);
    assert.deepEqual(f.notices, []);
    await f.search('取消搜索');
    f.app.suspend();
    assert.equal(f.timers.size, 0);
  }
});

test('current errors are still reported and the next category can recover', async t => {
  const f = await setup(t, request => request.tag === '1' ? Promise.reject(new Error('当前分类读取失败')) : feed(request.tag === '2' ? '恢复后的作品' : '初始作品'));
  await f.tab('分类甲').click();
  await flush();
  assert.deepEqual(f.notices, ['当前分类读取失败']);
  await f.tab('分类乙').click();
  await flush();
  assert.deepEqual(f.titles(), ['恢复后的作品']);
});

const processCard = (templateUuid, extra = {}) => ({name: templateUuid, templateUuid, processAvailable: true, processReady: true, finalOutput: `/featured-showcase-media/${templateUuid}.mp4`, ...extra});
const processNode = (id, type = 'video', extra = {}) => ({id, name: id, type, x: 0, y: 0, width: 240, height: 160, ...extra});
const control = (f, label, scope = f.document.body) => scope.querySelectorAll('button').find(node => node.textContent === label || node.getAttribute('aria-label') === label);
const openProcess = async (f, index = 0) => {
  await f.root.querySelectorAll('.fs-process')[index].click();
  await flush();
};
const layerOf = f => f.document.body.querySelector('.fs-process-layer');

test('same-page process requests only display the latest canvas, including stale errors', async t => {
  for (const fail of [false, true]) {
    const a = deferred(), b = deferred();
    const f = await setup(t, request => request.url.endsWith('/A') ? a.promise : request.url.endsWith('/B') ? b.promise : feed('unused', {items: [processCard('A'), processCard('B')]}));
    await openProcess(f, 0);
    assert.equal(layerOf(f).dataset.view, 'process-loading');
    await openProcess(f, 1);
    b.resolve({name: 'B画布', process: {nodes: [processNode('B节点')], edges: []}});
    await flush();
    if (fail) a.reject(new Error('A的迟到错误'));
    else a.resolve({name: 'A画布', process: {nodes: [processNode('A节点')], edges: []}});
    await flush();
    assert.equal(layerOf(f).querySelector('.fs-process-name').textContent, 'B画布');
    assert.deepEqual(layerOf(f).querySelectorAll('.fs-node').map(node => node.getAttribute('aria-label')), ['B节点']);
    assert.deepEqual(f.notices, []);
    assert.equal((f.document.body.listeners.get('keydown') || []).length, 1);
  }
});

test('closing a pending canvas prevents reopening, restores its card focus, and keeps the list', async t => {
  const pending = deferred();
  const f = await setup(t, request => request.url.endsWith('/A') ? pending.promise : feed('A', {items: [processCard('A')]}));
  const card = f.root.querySelector('.fs-card'), opener = f.root.querySelector('.fs-process');
  f.root.scrollTop = 248;
  await openProcess(f);
  await control(f, '关闭').click();
  assert.equal(f.document.activeElement, opener);
  assert.equal((f.document.body.listeners.get('keydown') || []).length, 0);
  pending.resolve({process: {nodes: [processNode('迟到')], edges: []}});
  await flush();
  assert.equal(layerOf(f), null);
  assert.equal(f.root.querySelector('.fs-card'), card);
  assert.equal(f.root.scrollTop, 248);
  assert.equal(f.calls.filter(call => call.tag === '0').length, 1);
});

test('playback has a permanent process entry, inline retry, and returns to the same video', async t => {
  let attempts = 0;
  const f = await setup(t, request => request.url.endsWith('/A') ? ++attempts === 1 ? Promise.reject(new Error('暂时读取失败')) : {process: {nodes: [processNode('镜头')], edges: []}} : feed('A', {items: [processCard('A')]}));
  await f.root.querySelector('.fs-play-cover').click();
  const playback = layerOf(f).querySelector('video');
  playback.currentTime = 42;
  await control(f, '查看制作过程', layerOf(f)).click();
  await flush();
  assert.equal(layerOf(f).dataset.view, 'process-error');
  assert.match(layerOf(f).textContent, /暂时读取失败/);
  await control(f, '重试').click();
  await flush();
  assert.equal(layerOf(f).dataset.view, 'process');
  await layerOf(f).querySelector('.fs-node').click();
  await control(f, '−').click();
  const canvas = layerOf(f).querySelector('.fs-world');
  const transform = canvas.style.transform;
  await control(f, '返回成片').click();
  assert.equal(layerOf(f).dataset.view, 'playback');
  assert.equal(layerOf(f).querySelector('video'), playback);
  assert.equal(playback.currentTime, 42);
  assert.equal(f.document.activeElement.textContent, '查看制作过程');
  await control(f, '查看制作过程', layerOf(f)).click();
  assert.equal(layerOf(f).querySelector('.fs-world'), canvas);
  assert.equal(canvas.style.transform, transform);
  assert.equal(layerOf(f).querySelector('.fs-inspector').querySelector('h3').textContent, '镜头');
  assert.equal(attempts, 2);
  await control(f, '返回成片').click();
  await f.document.body.dispatch('keydown', {key: 'Escape'});
  assert.equal(layerOf(f), null);
  assert.equal((f.document.body.listeners.get('keydown') || []).length, 0);
  assert.equal(f.calls.filter(call => call.tag === '0').length, 1);
});

test('returning to playback while the process is loading discards its late response', async t => {
  const pending = deferred();
  const f = await setup(t, request => request.url.endsWith('/A') ? pending.promise : feed('A', {items: [processCard('A')]}));
  await f.root.querySelector('.fs-play-cover').click();
  const opening = control(f, '查看制作过程', layerOf(f)).click();
  await flush();
  await control(f, '返回成片').click();
  pending.resolve({process: {nodes: [processNode('迟到')], edges: []}});
  await opening;
  await flush();
  assert.equal(layerOf(f).dataset.view, 'playback');
  assert.equal(layerOf(f).querySelectorAll('.fs-node').length, 0);
});

test('all structural media nodes remain in storyboard and project assets without creating players', async t => {
  const nodes = [processNode('group', 'group', {childIds: ['v2', 'v1']})];
  for (let i = 1; i <= 30; i++) nodes.push(processNode(`g${i}`, 'group'));
  for (let i = 0; i < 12; i++) nodes.push(processNode(`a${i}`, 'audio', {mediaStatus: 'missing'}));
  for (let i = 0; i < 178; i++) nodes.push(processNode(`i${i}`, 'image', {mediaStatus: 'missing'}));
  for (let i = 0; i < 187; i++) nodes.push(processNode(`v${i}`, 'video', {mediaStatus: 'missing'}));
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes, edges: [], coverage: {mediaNodes: 377, localMediaNodes: 0, missingMediaNodes: 377}}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  assert.equal(layerOf(f).querySelectorAll('.fs-node').length, 408);
  assert.match(layerOf(f).querySelector('.fs-coverage').textContent, /音频 12 · 图片 178 · 视频 187/);
  assert.equal(layerOf(f).querySelectorAll('video').length, 0);
  assert.equal(layerOf(f).querySelectorAll('audio').length, 0);
  await control(f, '故事板').click();
  assert.equal(layerOf(f).querySelectorAll('.fs-media-tile').length, 187);
  assert.deepEqual(layerOf(f).querySelectorAll('.fs-media-tile').slice(0, 2).map(node => node.dataset.nodeId), ['v2', 'v1']);
  assert.match(layerOf(f).querySelector('.fs-board').textContent, /待缓存/);
  assert.doesNotMatch(layerOf(f).querySelector('.fs-board').textContent, /没有视频节点/);
  await control(f, '项目素材').click();
  assert.ok(control(f, '音频（12）'));
  assert.ok(control(f, '图片（178）'));
  assert.ok(control(f, '视频（187）'));
  await control(f, '音频（12）').click();
  assert.equal(layerOf(f).querySelectorAll('.fs-media-tile').length, 12);
  assert.match(layerOf(f).querySelector('.fs-assets').textContent, /♫/);
  await control(f, '图片（178）').click();
  assert.equal(layerOf(f).querySelectorAll('.fs-media-tile').length, 178);
  assert.equal(layerOf(f).querySelectorAll('video').length, 0);
  assert.equal(layerOf(f).querySelectorAll('audio').length, 0);
});

test('node details retain all outputs, boolean parameters and repeated ordered references with lazy playback', async t => {
  const nodes = [
    processNode('镜头', 'video', {poster: '/featured-showcase-media/poster.jpg', mediaStatus: 'missing', params: {enableSound: false, advancedSettings: {cameraControl: ['pan', 'tilt']}}, outputs: [
      {index: 0, url: '', status: 'missing', metadata: {width: 1280, height: 720}},
      {index: 1, url: '/featured-showcase-media/video.mp4', status: 'local', metadata: {width: 1920, height: 1080, duration: 3.75}},
    ], refs: [
      {nodeId: '参考', label: '重复第二次', kind: 'image', index: 1, order: 2},
      {nodeId: '参考', label: '重复第一次', kind: 'image', index: 0, order: 0},
      {nodeId: '不存在', label: '缺失引用', kind: 'audio', index: 0, order: 1},
    ]}),
    processNode('参考', 'image', {url: '/featured-showcase-media/image.jpg'}),
  ];
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes, edges: []}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  assert.ok(layerOf(f).querySelectorAll('img').some(image => image.src.endsWith('/poster.jpg')));
  assert.equal(layerOf(f).querySelectorAll('video').length, 0);
  await layerOf(f).querySelectorAll('.fs-node').find(node => node.dataset.nodeId === '镜头').click();
  const details = layerOf(f).querySelector('.fs-inspector');
  assert.equal(details.querySelectorAll('.fs-output').length, 2);
  assert.match(details.textContent, /"enableSound": false/);
  assert.match(details.textContent, /1920 × 1080 · 时长 3.75/);
  assert.deepEqual(details.querySelector('.fs-refs').querySelectorAll('button').map(node => node.textContent), ['重复第一次 · image · 位置 0', '缺失引用 · audio · 位置 0', '重复第二次 · image · 位置 1']);
  assert.equal(details.querySelectorAll('video').length, 0);
  await control(f, '播放视频', details).click();
  const player = details.querySelector('video');
  assert.equal(player.src, '/featured-showcase-media/video.mp4');
  assert.equal(player.preload, 'none');
  assert.equal(layerOf(f).querySelectorAll('video').length, 1);
  const transform = layerOf(f).querySelector('.fs-world').style.transform;
  await control(f, '关闭详情').click();
  assert.equal(layerOf(f).querySelector('.fs-inspector'), null);
  assert.ok(player.paused);
  assert.equal(layerOf(f).querySelector('.fs-world').style.transform, transform);
  assert.equal(f.document.activeElement.dataset.nodeId, '镜头');
  await layerOf(f).querySelectorAll('.fs-node').find(node => node.dataset.nodeId === '镜头').click();
  await control(f, '重复第一次 · image · 位置 0').click();
  assert.equal(layerOf(f).querySelector('.fs-inspector').querySelector('h3').textContent, '参考');
});

test('unknown node types expose metadata and directory, zoom and Escape controls remain usable', async t => {
  const nodes = [processNode('脚本', 'screenplay', {params: {draft: false}, content: '只读剧本文本'})];
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes, edges: [], issues: [{kind: 'unsupported'}]}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  assert.ok(control(f, '适应画布'));
  assert.equal(control(f, '切换小地图'), undefined);
  const original = layerOf(f).querySelector('.fs-zoom').textContent;
  await control(f, '−').click();
  assert.notEqual(layerOf(f).querySelector('.fs-zoom').textContent, original);
  await control(f, '+').click();
  assert.equal(layerOf(f).querySelector('.fs-zoom').textContent, original);
  await control(f, '目录').click();
  assert.ok(layerOf(f).querySelector('.fs-outline'));
  await control(f, '脚本', layerOf(f).querySelector('.fs-outline')).click();
  assert.equal(layerOf(f).querySelector('.fs-outline'), null);
  assert.match(layerOf(f).querySelector('.fs-inspector').textContent, /暂不支持专用预览/);
  assert.match(layerOf(f).querySelector('.fs-inspector').textContent, /只读剧本文本/);
  assert.equal(f.document.activeElement.textContent, '关闭详情');
  await f.document.body.dispatch('keydown', {key: 'Escape'});
  assert.equal(layerOf(f).querySelector('.fs-inspector'), null);
  assert.equal(f.document.activeElement.dataset.nodeId, '脚本');
  await control(f, '目录').click();
  await f.document.body.dispatch('keydown', {key: 'Escape'});
  assert.equal(layerOf(f).querySelector('.fs-outline'), null);
  assert.equal(f.document.activeElement.textContent, '目录');
  await f.document.body.dispatch('keydown', {key: 'Escape'});
  assert.equal(layerOf(f), null);
});

test('a large uncached workflow opens at a readable node and overview can return to readable details', async t => {
  const nodes = [processNode('起始参考', 'image', {x: -2400, y: -1400, mediaStatus: 'missing'}),
    processNode('后续镜头', 'video', {x: 18000, y: 16000, mediaStatus: 'missing'})];
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes,
    edges: [{id: 'e', source: '起始参考', target: '后续镜头'}]}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  await flush();
  assert.equal(layerOf(f).querySelector('.fs-zoom').textContent, '75%');
  assert.equal(layerOf(f).querySelectorAll('.fs-node').length, 2);
  assert.match(layerOf(f).querySelector('.fs-world').style.transform, /translate\(2210px, 1340px\) scale\(0.75\)/);
  await control(f, '适应画布').click();
  assert.equal(layerOf(f).querySelector('.fs-zoom').textContent, '4%');
  await control(f, '阅读节点').click();
  assert.equal(layerOf(f).querySelector('.fs-zoom').textContent, '75%');
  assert.equal(layerOf(f).querySelector('.fs-inspector').querySelector('h3').textContent, '起始参考');
  await control(f, '关闭详情').click();
  await control(f, '故事板').click();
  await layerOf(f).querySelector('.fs-media-tile').click();
  await control(f, '定位到画布').click();
  assert.ok(layerOf(f).querySelector('.fs-stage'));
  assert.equal(layerOf(f).querySelector('.fs-zoom').textContent, '75%');
  assert.equal(layerOf(f).querySelector('.fs-inspector').querySelector('h3').textContent, '后续镜头');
});

test('copy prompts includes every prompt and reports the actual clipboard result', async t => {
  const nodes = Array.from({length: 45}, (_, index) => processNode(`n${index}`, 'image', {prompt: `完整提示词${index}`}));
  const f = await setup(t, request => request.url.endsWith('/A') ? {name: '完整提示词作品', process: {nodes, edges: []}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  assert.equal(control(f, '复制项目'), undefined);
  await control(f, '复制提示词').click();
  assert.equal(f.clipboard.values.length, 1);
  assert.match(f.clipboard.values[0], /完整提示词44/);
  assert.equal(f.notices.at(-1), '已复制 45 条提示词。');
  f.clipboard.error = new Error('denied');
  await control(f, '复制提示词').click();
  assert.equal(f.clipboard.values.length, 1);
  assert.equal(f.notices.at(-1), '复制失败，请检查浏览器剪贴板权限后重试。');
});

test('empty source nodes do not report a cache gap after all real outputs are local', async t => {
  const nodes=[processNode('已保存','image',{mediaStatus:'local',url:'/featured-showcase-media/saved.png'}),
    processNode('原本无输出','image',{mediaStatus:'empty',outputs:[]})];
  const f=await setup(t,request=>request.url.endsWith('/A')?{process:{nodes,edges:[],
    coverage:{mediaNodes:2,localMediaNodes:1,missingMediaNodes:0,status:'complete'}}}:feed('A',{items:[processCard('A')]}));
  await openProcess(f);
  assert.equal(Boolean(layerOf(f).querySelector('.fs-coverage-warning')),false);
  assert.match(layerOf(f).querySelector('.fs-coverage').textContent,/已缓存 1\/1 个有输出媒体节点/);
  assert.match(layerOf(f).querySelector('.fs-coverage').textContent,/1 个节点没有输出/);
});

test('unpublished, missing and invalid snapshots keep a visible explanation without inventing a canvas', async t => {
  for (const [structureStatus, expected] of [['unpublished', '未公开'], ['missing', '尚未保存'], ['invalid', '快照损坏']]) {
    const f = await setup(t, () => feed('A', {items: [processCard('A', {structureStatus})]}));
    const entry = f.root.querySelector('.fs-process');
    assert.equal(entry.textContent, '查看制作过程');
    await openProcess(f);
    assert.equal(layerOf(f).dataset.view, 'process-unavailable');
    assert.match(layerOf(f).textContent, new RegExp(expected));
    assert.equal(f.calls.length, 1);
    await control(f, '关闭').click();
    assert.equal(f.document.activeElement, entry);
  }
});

test('audio plays on demand and empty outputs stay distinct from missing local media', async t => {
  const nodes = [
    processNode('配乐', 'audio', {mediaStatus: 'local', outputs: [{index: 0, url: '/featured-showcase-media/audio.mp3', status: 'local', metadata: {durationMs: 12000}}]}),
    processNode('无输出', 'image', {mediaStatus: 'empty', outputs: []}),
    processNode('未缓存', 'video', {mediaStatus: 'missing', outputs: [{index: 0, url: 'https://outside.invalid/video.mp4', status: 'missing'}]}),
  ];
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes, edges: []}} : feed('A', {items: [processCard('A')]}));
  await openProcess(f);
  await layerOf(f).querySelectorAll('.fs-node').find(node => node.dataset.nodeId === '配乐').click();
  assert.match(layerOf(f).querySelector('.fs-inspector').textContent, /时长 12000 ms/);
  assert.equal(layerOf(f).querySelectorAll('audio').length, 0);
  await control(f, '播放音频').click();
  const audio = layerOf(f).querySelector('audio');
  assert.equal(audio.src, '/featured-showcase-media/audio.mp3');
  assert.equal(audio.paused, false);
  await control(f, '关闭详情').click();
  assert.equal(audio.paused, true);
  await layerOf(f).querySelectorAll('.fs-node').find(node => node.dataset.nodeId === '无输出').click();
  assert.match(layerOf(f).querySelector('.fs-inspector').textContent, /这个节点没有输出/);
  await control(f, '关闭详情').click();
  await layerOf(f).querySelectorAll('.fs-node').find(node => node.dataset.nodeId === '未缓存').click();
  assert.match(layerOf(f).querySelector('.fs-inspector').textContent, /待缓存/);
  assert.equal(control(f, '播放视频'), undefined);
  assert.equal(layerOf(f).querySelectorAll('video').length, 0);
});

function browserAt(search) {
  const browser = {location: {pathname: '/', search, hash: '#kept'}, updates: []};
  browser.history = {
    state: {panel: 'keep'},
    replaceState(state, _title, href) {
      const next = new URL(href, 'http://local');
      Object.assign(browser.location, {pathname: next.pathname, search: next.search, hash: next.hash});
      browser.history.state = state;
      browser.updates.push(href);
    },
  };
  return browser;
}

const routeWork = browser => new URLSearchParams(browser.location.search).get('showcase_work');

test('card playback and process are sibling native buttons with separate pointer and keyboard actions', async t => {
  const browser = browserAt('?page=featured-showcase&kind=video');
  const f = await setup(t, request => request.url.endsWith('/A') ? {process: {nodes: [processNode('镜头')], edges: []}} : feed('A', {items: [processCard('A')]}), {browser});
  const cover = f.root.querySelector('.fs-cover');
  const play = cover.querySelector('.fs-play-cover'), process = cover.querySelector('.fs-process');
  assert.equal(cover.tagName, 'DIV');
  assert.equal(cover.getAttribute('role'), null);
  assert.equal((cover.listeners.get('click') || []).length, 0);
  assert.equal(play.tagName, 'BUTTON');
  assert.equal(process.tagName, 'BUTTON');
  assert.equal(play.parentElement, cover);
  assert.equal(process.parentElement, cover);
  assert.equal(play.getAttribute('aria-label'), '播放 A');
  assert.equal(process.getAttribute('aria-label'), '查看制作过程');
  assert.equal(play.querySelectorAll('button').length, 0);
  assert.equal(cover.querySelectorAll('button').length, 2);
  let stopped = 0;
  await process.click({stopPropagation() { stopped++; }});
  await flush();
  assert.equal(stopped, 1);
  assert.equal(layerOf(f).dataset.view, 'process');
  assert.equal(layerOf(f).querySelectorAll('video').length, 0);
  assert.equal(f.document.body.querySelectorAll('.fs-process-layer').length, 1);
  assert.equal(routeWork(browser), 'A');
  await control(f, '关闭').click();
  assert.equal(routeWork(browser), null);
  await play.pressKey('Enter');
  assert.equal(layerOf(f).dataset.view, 'playback');
  assert.equal(f.calls.filter(call => call.url.endsWith('/A')).length, 1);
  assert.equal(f.document.body.querySelectorAll('.fs-process-layer').length, 1);
  await control(f, '查看制作过程', layerOf(f)).click();
  assert.equal(routeWork(browser), 'A');
  await control(f, '返回成片').click();
  assert.equal(routeWork(browser), null);
  await control(f, '关闭').click();
  await process.pressKey(' ');
  await flush();
  assert.equal(layerOf(f).dataset.view, 'process');
  assert.equal(f.calls.filter(call => call.url.endsWith('/A')).length, 3);
  assert.equal(new URLSearchParams(browser.location.search).get('kind'), 'video');
  assert.equal(browser.location.hash, '#kept');
  assert.deepEqual(browser.history.state, {panel: 'keep'});
});

test('direct process links resolve archived cards outside the first page and survive refresh', async t => {
  const api = request => request.url.endsWith('/archive') ? {card: processCard('archive', {name: '归档作品'}), process: {nodes: [processNode('归档镜头')], edges: []}} : feed('列表作品');
  const browser = browserAt('?page=featured-showcase&showcase_work=archive&kind=video');
  const f = await setup(t, api, {browser});
  await flush();
  assert.equal(layerOf(f).dataset.view, 'process');
  assert.equal(layerOf(f).getAttribute('aria-label'), '归档作品');
  assert.equal(layerOf(f).querySelector('.fs-process-name').textContent, '归档作品');
  assert.deepEqual(f.titles(), ['列表作品']);
  assert.equal(routeWork(browser), 'archive');
  assert.equal(f.calls.filter(call => call.url.endsWith('/archive')).length, 1);
  const refreshed = await setup(t, api, {browser: browserAt(browser.location.search)});
  await flush();
  assert.equal(layerOf(refreshed).getAttribute('aria-label'), '归档作品');
  await control(refreshed, '关闭').click();
  assert.equal(routeWork(refreshed.browser), null);
  assert.equal(refreshed.document.activeElement, refreshed.root);
  assert.equal(new URLSearchParams(refreshed.browser.location.search).get('page'), 'featured-showcase');
  assert.equal(new URLSearchParams(refreshed.browser.location.search).get('kind'), 'video');
  await refreshed.app.load();
  assert.equal(layerOf(refreshed), null);
  assert.equal(refreshed.calls.filter(call => call.url.endsWith('/archive')).length, 1);
});

test('suspend consumes a pending direct-link intent before the list or process resolves', async t => {
  const pendingList = deferred();
  const browser = browserAt('?page=featured-showcase&showcase_work=archive');
  const f = await setup(t, () => pendingList.promise, {browser, autoLoad: false});
  const loading = f.app.load();
  await flush();
  f.app.suspend();
  assert.equal(routeWork(browser), null);
  pendingList.resolve(feed('列表作品'));
  await loading;
  await flush();
  assert.equal(layerOf(f), null);
  assert.equal(f.calls.filter(call => call.url.endsWith('/archive')).length, 0);
  await f.app.load();
  assert.equal(layerOf(f), null);
  assert.equal(f.calls.filter(call => call.url.endsWith('/archive')).length, 0);

  for (const fail of [false, true]) {
    const pendingProcess = deferred();
    const g = await setup(t, request => request.url.endsWith('/archive') ? pendingProcess.promise : feed('列表作品'), {browser: browserAt('?page=featured-showcase&showcase_work=archive')});
    assert.equal(layerOf(g).dataset.view, 'process-loading');
    g.app.suspend();
    if (fail) pendingProcess.reject(new Error('迟到的直达失败'));
    else pendingProcess.resolve({card: processCard('archive'), process: {nodes: [processNode('迟到的直达')], edges: []}});
    await flush();
    assert.equal(layerOf(g), null);
    assert.equal(routeWork(g.browser), null);
    assert.deepEqual(g.notices, []);
    assert.equal((g.document.body.listeners.get('keydown') || []).length, 0);
  }
});
