// Official 服饰 browser against the real asset-center module. No browser claim.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Document, Element} = require('./panel_dom.cjs');
Object.defineProperty(Element.prototype, 'isConnected', {get() {
  for (let node = this; node; node = node.parentElement) if (node === this.ownerDocument.body) return true;
  return false;
}});
Element.prototype.showModal = function() { this.open = true; };
Element.prototype.close = function() { this.open = false; for (const fn of this.listeners.get('close') || []) fn(); };
const doc = new Document('');
doc.documentElement = doc.createElement('html');
globalThis.document = doc;
const cats = [{name: '春', count: 1}, {name: '夏', count: 1}, {name: '秋', count: 0}, {name: '冬', count: 0}, {name: '内衣', count: 0}, {name: '派对', count: 0}, {name: '泳装', count: 0}, {name: '性感', count: 0}];
const first = {id: 'SPR-0001', title: 'SPR-0001', category: '春', label: '春', keywords: 'SPR-0001 ivory white denim', image: '/api/v1/asset-center/costumes/SPR-0001/content'};
const second = {id: 'SUM-0001', title: 'SUM-0001', category: '夏', label: '夏', keywords: 'SUM-0001 white shirt', image: '/api/v1/asset-center/costumes/SUM-0001/content'};
const requests = [];
const api = async url => {
  requests.push(url);
  if (url.startsWith('/api/v1/asset-center/costumes?')) {
    const query = new URL(url, 'http://local').searchParams;
    const offset = Number(query.get('offset') || 0);
    if (query.get('category') === '春') return {categories: cats, total_all: 2, total: 1, offset, limit: 120, next_offset: null, items: [first]};
    if (query.get('q')) return {categories: cats, total_all: 2, total: 1, offset, limit: 120, next_offset: null, items: [first]};
    if (offset > 0) return {categories: cats, total_all: 2, total: 2, offset, limit: 120, next_offset: null, items: [second]};
    return {categories: cats, total_all: 2, total: 2, offset: 0, limit: 120, next_offset: 120, items: [first]};
  }
  if (url.startsWith('/api/v1/asset-center?')) return {items: [], total: 0, next_offset: null};
  throw new Error('unexpected request ' + url);
};
const root = doc.createElement('main');
doc.body.append(root);
const find = (container, text) => [...container.querySelectorAll('button')].find(node => node.textContent === text);
const click = async (container, text) => {
  const node = find(container, text);
  assert.ok(node, 'missing button ' + text);
  await node.onclick();
};
(async () => {
  const {createAssetCenter} = await import(pathToFileURL(path.resolve(__dirname, '../../../../src/vsc/interfaces/web/static/asset-center.js')));
  const center = createAssetCenter(root, {
    api,
    notice: () => {},
    session: () => ({actor: 'actor-fixed', csrf: 'csrf'}),
    projects: () => [],
  }, {source: 'official', embedded: true, workbench: true});
  await center.load();
  assert.ok(requests[0].includes('source=official'));
  assert.equal(find(root, '服饰').getAttribute('aria-pressed'), 'false');
  await click(root, '服饰');
  assert.ok(requests.at(-1).includes('/api/v1/asset-center/costumes?'));
  assert.equal(find(root, '服饰').getAttribute('aria-pressed'), 'true');
  assert.equal(find(root, '全部 2').getAttribute('aria-pressed'), 'true');
  assert.ok(root.textContent.includes('只有服装、没有人物的竖图'));
  assert.equal(root.querySelector('.costume-open').querySelector('img').src, first.image);
  assert.ok(root.textContent.includes('ivory'));
  assert.ok(!root.textContent.includes('SPR-0001 ivory'));
  await click(root, '更多');
  assert.ok(requests.at(-1).includes('offset=120'));
  assert.equal(root.querySelectorAll('.costume-card').length, 2);
  assert.equal(find(root, '更多'), undefined);
  const before = requests.length;
  await click(root, '春 1');
  assert.ok(requests.at(-1).includes('category=%E6%98%A5'));
  assert.equal(find(root, '春 1').getAttribute('aria-pressed'), 'true');
  const input = root.querySelector('input');
  input.value = 'white';
  input.oninput();
  await new Promise(resolve => setTimeout(resolve, 220));
  const focused = root.querySelector('input');
  assert.ok(requests.length > before);
  assert.ok(requests.at(-1).includes('q=white'));
  assert.equal(focused.value, 'white');
  assert.equal(doc.activeElement, focused);
  await click(root, '使用说明');
  const note = [...doc.querySelectorAll('dialog')].find(node => node.classList.contains('costume-note'));
  assert.ok(note.textContent.includes('下载得到的是本库生成的原图'));
  await click(root, '使用说明');
  assert.equal(note.isConnected, false);
  const opener = root.querySelector('.costume-open');
  await opener.onclick();
  const modal = [...doc.querySelectorAll('dialog')].find(node => node.classList.contains('costume-modal'));
  assert.equal(modal.querySelector('a').getAttribute('download'), 'SPR-0001.png');
  await modal.dispatch('keydown', {key: 'ArrowRight'});
  await click(root, '人设');
  assert.ok(requests.at(-1).includes('asset_kind=character'));
  assert.equal(root.querySelector('.costume-grid'), null);
  console.log('costume gallery DOM PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
