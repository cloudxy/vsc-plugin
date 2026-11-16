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

async function setup(t, api) {
  const document = new Document('');
  document.head = document.createElement('head');
  const root = document.createElement('main');
  document.body.append(root);
  const timers = new Map(), observers = [], calls = [], notices = [];
  let timerId = 0;
  class Observer {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() { this.disconnected = true; }
    trigger() { this.callback([{isIntersecting: true}]); }
  }
  const {createFeaturedShowcase} = await loadModule('featured-showcase.js', {
    document, IntersectionObserver: Observer,
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
  await app.load();
  return {app, root, document, calls, notices, timers, observers,
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
    await f.root.querySelectorAll('button').find(node => node.getAttribute('aria-label') === '查看创作过程').click({stopPropagation() {}});
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
