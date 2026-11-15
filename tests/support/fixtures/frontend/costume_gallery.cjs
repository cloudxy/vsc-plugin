// Standalone reference libraries (服装穿搭库 / 动作姿势库 / 人像颜值库) and official catalog separation
// against the real asset-center module and character-studio store. Fake HTTP; no browser layout claim.
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
doc.head = doc.createElement('head');
doc.documentElement.append(doc.head, doc.body);
globalThis.document = doc;
globalThis.history = {
  pushState(_state, _title, url) { globalThis.location.search = String(url || ''); },
  replaceState(_state, _title, url) { globalThis.location.search = String(url || ''); },
};
globalThis.location = {search: '?page=asset-center&tab=official', href: '/?page=asset-center&tab=official'};
const flush = () => new Promise(resolve => setTimeout(resolve, 10));
const costume = (id, extra = {}) => ({id, source: 'gia', 一级分类: '现实', 分类: '春季穿搭', 服装名称: '象牙白针织衫 ' + id, 标签: ['象牙白'], 关键词: 'ivory knit',
  缩略图: `thumbs/costume/${id}.webp`, 预览图: `img/costume/${id}.webp`, 原图: `img/costume/${id}.webp`, 来源: 'ギア · 写实服装', 敏感: false, ...extra});
const shisei = costume('shisei-C001', {source: 'shisei', 分类: '中国历代', 服装名称: '商 · 上衣下裳', 来源: 'Shisei · 中国历代', selectedView: 'front',
  views: [{id: 'front', label: '正面', 缩略图: 'thumbs/costumes/shisei/costume_C001_front.webp', 预览图: 'img/costumes/shisei/costume_C001_front.webp', 原图: 'img/costumes/shisei/costume_C001_front.webp'},
    {id: 'side', label: '侧面', 缩略图: 'thumbs/costumes/shisei/costume_C001_side.webp', 预览图: 'img/costumes/shisei/costume_C001_side.webp', 原图: 'img/costumes/shisei/costume_C001_side.webp'}]});
const anime = costume('charadb-O001', {source: 'charadb', 一级分类: '二次元', 缩略图: 'https://charadb-2fi.pages.dev/thumb/O001.webp', 来源: 'たき AI · CharaDB'});
const costumeFacets = {tops: [{name: '现实', count: 3}, {name: '二次元', count: 1}], sources: [{id: 'gia', label: 'ギア · 写实服装', count: 2, notice: 'ギア AI 服装参考。', url: 'https://ai-costume-gallery.pages.dev/'}, {id: 'shisei', label: 'Shisei · 中国历代', count: 1, notice: 'CC0', url: 'https://github.com/wquguru/shisei'}],
  categories: [{name: '春季穿搭', count: 2}, {name: '中国历代', count: 1}], tags: [{name: '象牙白', count: 2}], hidden_sensitive_count: 2, dataset_mode: 'pose-gallery'};
const poseItem = (id, angle) => ({id, 体系: '全身单人・标准系', 姿势编号: 'P001', 分类: '站姿', 姿势名称: '自然站立', 角度: angle, 缩略图: `thumbs/${id}.jpg`, 原图: `img/${id}.png`});
const group = {key: '全身单人・标准系|P001', system: '全身单人・标准系', number: 'P001', name: '自然站立', category: '站姿', items: [poseItem('full_std_P001_front', '正面'), poseItem('full_std_P001_side', '侧面')]};
const portrait = {id: 'f71f980dde3', 分区: '正脸参考', 发长: '短发', 发型名称: '标准基础款', 标题: '短发・标准款', 热门: true, 缩略图: 'thumbs/portrait/f71f980dde3.webp', 原图: 'img/portrait/f71f980dde3.webp'};
const requests = [];
let deferred = null;
const navigations = [];
const api = async (url) => {
  requests.push(url);
  if (deferred && url.includes('/pose-gallery/')) { const held = deferred; deferred = null; return held; }
  const query = new URL(url, 'http://local').searchParams;
  if (url.startsWith('/api/v1/asset-center/pose-gallery/costumes?')) {
    assert.equal(query.get('limit'), '60');
    assert.equal(query.get('safe'), 'true');
    const offset = Number(query.get('offset'));
    if (query.get('q')) return {...costumeFacets, total: 1, total_all: 3, offset, limit: 60, next_offset: null, items: [costume('SPR-0001')]};
    if (query.get('category') === '中国历代') return {...costumeFacets, total: 1, total_all: 3, offset, limit: 60, next_offset: null, items: [shisei]};
    if (offset >= 120) return {...costumeFacets, total: 3, total_all: 3, offset, limit: 60, next_offset: null, items: [anime]};
    if (offset >= 60) return {...costumeFacets, total: 3, total_all: 3, offset, limit: 60, next_offset: 120, items: [shisei]};
    return {...costumeFacets, total: 3, total_all: 3, offset: 0, limit: 60, next_offset: 60, items: [costume('SPR-0001')]};
  }
  if (url.startsWith('/api/v1/asset-center/pose-gallery/poses?')) {
    assert.equal(query.get('safe'), 'true');
    const view = query.get('view');
    return {view, total: 1, total_groups: 1, total_poses: 2, hidden_sensitive_count: 674, offset: 0, limit: 60, next_offset: null,
      systems: [{name: '全身单人・标准系', count: 2}], categories: ['站姿'], angles: ['正面', '俯视', '仰视', '侧面', '斜侧'], items: view === 'single' ? group.items : [group]};
  }
  if (url.startsWith('/api/v1/asset-center/pose-gallery/portraits?')) {
    return {total: 1, total_all: 1, offset: 0, limit: 60, next_offset: null, sections: [{name: '正脸参考', count: 1}], hair_lengths: [{name: '短发', count: 1}],
      hair_styles: [{name: '标准基础款', count: 1}], hot_count: 1, items: [portrait]};
  }
  if (url.startsWith('/api/v1/asset-center?')) return {items: [], total: 0, next_offset: null};
  throw new Error('unexpected request ' + url);
};
const workspace = doc.createElement('div');
workspace.className = 'workspace';
doc.body.append(workspace);
const platform = doc.createElement('section');
platform.id = 'production-platform';
platform.scrollTop = 0;
workspace.append(platform);
const root = doc.createElement('main');
platform.append(root);
const all = (container, selector) => container.querySelectorAll(selector);
const find = (container, text) => [...all(container, 'button')].find(node => node.textContent === text);
const click = async (container, text) => { const node = find(container, text); assert.ok(node, 'missing button ' + text); await node.onclick(); await flush(); };
const ctx = {
  api, notice: () => {}, navigate: (page, options) => navigations.push([page, options]),
  session: () => ({actor: 'actor-fixed', csrf: 'csrf'}), projects: () => [], workspaces: async () => [],
};
(async () => {
  const {createAssetCenter} = await import(pathToFileURL(path.resolve(__dirname, '../../../../src/vsc/interfaces/web/static/asset-center.js')));
  const studio = await import(pathToFileURL(path.resolve(__dirname, '../../../../src/vsc/interfaces/web/static/character-studio-store.js')));

  // 1. Official catalog excludes standalone reference libraries from category tabs.
  const officialCenter = createAssetCenter(root, ctx, {source: 'official', embedded: true, workbench: true});
  await officialCenter.load();
  const tabs = [...root.querySelector('.center-official-kinds').querySelectorAll('button')].map(n => n.textContent);
  assert.deepEqual(tabs, ['人设', '场景', '道具', '音频']);
  for (const label of ['服装穿搭库', '动作姿势库', '人像颜值库', '站位', '服饰']) {
    assert.equal(tabs.includes(label), false);
  }
  officialCenter.suspend();

  // 2. Standalone 服装穿搭库: Frame-0 header/pills/search-panel mount before HTTP resolves.
  globalThis.location.search = '?page=asset-center&tab=official&kind=costume';
  const costumeCenter = createAssetCenter(root, ctx, {source: 'official', embedded: true, workbench: true});
  let release;
  deferred = new Promise(resolve => { release = resolve; });
  const loadingCostume = costumeCenter.load();
  const filtersBox = root.querySelector('.ref-filters');
  assert.ok(filtersBox && filtersBox.classList.contains('center-official-filters'));
  assert.equal(root.querySelector('.center-official-kinds'), null);
  assert.equal(root.querySelector('.ref-page-title').textContent, '服装穿搭库');
  assert.ok(root.querySelector('.ref-type-row'));
  assert.ok(root.querySelector('.ref-pills'));
  assert.ok(root.querySelector('.ref-search-panel'));
  assert.ok(root.querySelector('.ref-search-panel').querySelector('.center-count'));
  assert.ok(root.querySelector('.costume-grid'));
  release({...costumeFacets, total: 3, total_all: 3, offset: 0, limit: 60, next_offset: 60, items: [costume('SPR-0001')]});
  await loadingCostume; await flush();
  assert.ok(requests.at(-1).startsWith('/api/v1/asset-center/pose-gallery/costumes?'));
  assert.ok(requests.at(-1).includes('offset=0&limit=60'));
  assert.ok(find(root, '全部穿搭 3'));
  assert.ok(root.querySelector('.center-count').textContent.includes('已隐藏 2 项 18+'));
  const firstImg = root.querySelector('.costume-open').querySelector('img');
  assert.equal(firstImg.src, '/api/v1/asset-center/pose-gallery/media/thumbs/costume/SPR-0001.webp');
  assert.equal(firstImg.loading, 'eager');

  // 60-per-batch paging via 加载更多 button.
  await click(root, '加载更多（剩余 2 套）');
  assert.ok(requests.at(-1).includes('offset=60&limit=60'));
  await click(root, '加载更多（剩余 1 套）');
  assert.ok(requests.at(-1).includes('offset=120&limit=60'));
  assert.equal(all(root, '.costume-card').length, 3);
  const srcs = [...all(root, '.costume-open')].map(n => n.querySelector('img').src);
  assert.equal(srcs.some(src => /^https?:\/\//i.test(src)), false);
  assert.equal(srcs[2], '/api/v1/asset-center/pose-gallery/media/thumbs/costumes/charadb/O001.webp');
  assert.equal(root.querySelector('.costume-more'), null);

  // Category pills and search.
  platform.scrollTop = 300;
  await click(root, '中国历代 1');
  assert.equal(platform.scrollTop, 0);
  assert.ok(requests.at(-1).includes('category=%E4%B8%AD%E5%9B%BD%E5%8E%86%E4%BB%A3'));
  assert.ok(all(root, '.ref-badge').some(n => n.textContent === '2 视角'));

  // Shisei lightbox offers view switching and the recipe toggle.
  await root.querySelector('.costume-open').onclick();
  const modal = [...doc.querySelectorAll('dialog')].find(n => n.classList.contains('ref-modal'));
  assert.ok(modal && modal.open);
  assert.ok(find(modal, '正面') && find(modal, '侧面'));
  await find(modal, '侧面').onclick();
  assert.ok(modal.querySelector('img').src.endsWith('costume_C001_side.webp'));
  await find(modal, '+ 加入配方').onclick(); await flush();
  assert.equal(studio.getState().recipe.costume.id, 'shisei-C001');
  assert.equal(studio.getState().recipe.costume.selectedView, 'side');
  modal.close();

  // The floating recipe dock reflects the recipe and opens the studio.
  const dock = root.querySelector('.cs-recipe-dock');
  assert.ok(dock && !dock.hidden);
  assert.ok(find(dock, '合成 (1)'));
  await find(dock, '合成 (1)').onclick();
  assert.deepEqual(navigations.at(-1), ['character-studio', undefined]);

  // Card toggle shows 已选 state without a reload.
  const pick = root.querySelector('.ref-pick');
  assert.equal(pick.textContent, '✓ 已选');
  const searchBox = root.querySelector('input');
  searchBox.value = 'ivory'; searchBox.oninput(); await new Promise(resolve => setTimeout(resolve, 260));
  assert.ok(requests.at(-1).includes('q=ivory'));
  assert.equal(doc.activeElement, root.querySelector('input'));
  costumeCenter.suspend();

  // 3. Standalone 动作姿势库: grouped multi-angle cards, white/depth thumbs.
  globalThis.location.search = '?page=asset-center&tab=official&kind=pose';
  const poseCenter = createAssetCenter(root, ctx, {source: 'official', embedded: true, workbench: true});
  await poseCenter.load(); await flush();
  assert.equal(root.querySelector('.ref-page-title').textContent, '动作姿势库');
  assert.ok(requests.at(-1).startsWith('/api/v1/asset-center/pose-gallery/poses?'));
  assert.ok(requests.at(-1).includes('view=group'));
  const strip = root.querySelector('.ref-angle-strip');
  const angleButtons = strip.children.filter(n => n.tagName === 'BUTTON');
  assert.deepEqual(angleButtons.map(n => n.textContent), ['正面', '侧面']);
  await angleButtons[1].onclick();
  assert.equal(root.querySelector('.costume-open').querySelector('img').src, '/api/v1/asset-center/pose-gallery/media/thumbs/full_std_P001_side.jpg');
  await root.querySelector('.ref-pick').onclick(); await flush();
  assert.equal(studio.getState().recipe.pose.id, 'full_std_P001_side');
  const beforeDepthRequests = requests.length;
  studio.setPoseDepthMode(true); await flush(); await flush();
  assert.equal(root.querySelector('.costume-open').querySelector('img').src, '/api/v1/asset-center/pose-gallery/media/thumbs/depth/full_std_P001_side.webp');
  assert.equal(requests.length, beforeDepthRequests);
  assert.equal(studio.getState().recipe.pose.useDepth, true);
  studio.setPoseDepthMode(false); await flush(); await flush();
  poseCenter.suspend();

  // 4. Standalone 人像颜值库: Top10 hot filter & Frame-0 cache reuse on reload.
  globalThis.location.search = '?page=asset-center&tab=official&kind=portrait';
  const portraitCenter = createAssetCenter(root, ctx, {source: 'official', embedded: true, workbench: true});
  await portraitCenter.load(); await flush();
  assert.equal(root.querySelector('.ref-page-title').textContent, '人像颜值库');
  assert.ok(requests.at(-1).startsWith('/api/v1/asset-center/pose-gallery/portraits?'));
  assert.ok(find(root, '短发 1'));
  await click(root, 'Top10 热门');
  assert.ok(requests.at(-1).includes('hot=true'));
  assert.ok(all(root, '.ref-badge').some(n => n.textContent === 'Top10'));
  deferred = new Promise(resolve => { release = resolve; });
  const revisit = portraitCenter.load();
  assert.equal(all(root, '.costume-card').length, 1);
  const cachedImg = root.querySelector('.costume-open').querySelector('img');
  release({total: 1, total_all: 1, offset: 0, limit: 60, next_offset: null, sections: [{name: '正脸参考', count: 1}], hair_lengths: [{name: '短发', count: 1}], hair_styles: [{name: '标准基础款', count: 1}], hot_count: 1, items: [portrait]});
  await revisit; await flush();
  assert.equal(root.querySelector('.costume-open').querySelector('img'), cachedImg);
  portraitCenter.suspend();
  assert.equal(root.querySelector('.cs-recipe-dock'), null);

  console.log('costume gallery DOM PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
