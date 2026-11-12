import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const require = createRequire(import.meta.url);
const {Document, Element, createPanel} = require('../../support/fixtures/frontend/panel_dom.cjs');

function setupDom() {
  const doc = new Document('');
  globalThis.document = doc;
  globalThis.Option = function(label, value) {
    const n = doc.createElement('option');
    n.textContent = label;
    n.value = value;
    return n;
  };
  Object.defineProperty(Element.prototype, 'isConnected', {
    configurable: true,
    get() { return !!this.parentElement; },
  });
  Object.defineProperty(Element.prototype, 'style', {
    configurable: true,
    get() { return (this._style ||= {}); },
  });
  Element.prototype.showModal = function() { this.open = true; };
  Element.prototype.close = function() { this.open = false; this.dispatch('close'); };
  Element.prototype.pause = function() { this.paused = true; };
  Element.prototype.play = async function() { this.paused = false; };
  Element.prototype.load = function() {};
  Element.prototype.contains = function(node) {
    while (node) {
      if (node === this) return true;
      node = node.parentElement;
    }
    return false;
  };
  Element.prototype.getContext = function() {
    return {
      clearRect() {},
      drawImage() {},
      fillRect() {},
      beginPath() {},
      moveTo() {},
      lineTo() {},
      stroke() {},
      arc() {},
      fill() {},
      save() {},
      restore() {},
    };
  };
  Element.prototype.getBoundingClientRect = function() {
    return {left: 0, top: 0, width: 512, height: 512};
  };
  const storage = new Map();
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, val) => storage.set(key, String(val)),
    removeItem: key => storage.delete(key),
  };
  globalThis.localStorage = {
    getItem: key => storage.get('ls:' + key) ?? null,
    setItem: (key, val) => storage.set('ls:' + key, String(val)),
    removeItem: key => storage.delete('ls:' + key),
  };
  return doc;
}

test('validateStoryboardBatchFilename and klingWeightedLength enforce 1:1 SkyProduction rules', async () => {
  setupDom();
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-subpages.js'));
  const ok1 = mod.validateStoryboardBatchFilename('1.png');
  assert.equal(ok1.valid, true);
  assert.equal(ok1.ordinal, 1);
  const ok2 = mod.validateStoryboardBatchFilename('12.JPEG');
  assert.equal(ok2.valid, true);
  assert.equal(ok2.ordinal, 12);

  const bad = mod.validateStoryboardBatchFilename('scene_01.png');
  assert.equal(bad.valid, false);
  assert.equal(bad.error, '文件名格式不正确：scene_01.png。文件名必须为数字.png/jpg/jpeg 格式，如 1.png、2.jpg、3.JPEG 等');

  assert.equal(mod.klingWeightedLength('中'.repeat(11000)), 11000);
  assert.ok(Math.abs(mod.klingWeightedLength('a'.repeat(26000)) - 11000) < 1e-6);
  assert.ok(mod.klingWeightedLength('a'.repeat(26001)) > 11000);
});

test('openPromptRecommendationDialog filters tags and inserts into prompt', async () => {
  const doc = setupDom();
  const root = doc.createElement('section');
  doc.body.append(root);
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-subpages.js'));
  const picked = [];
  const ctx = {
    api: async () => ({
      categories: [
        {id: 'shot_size', label: '景别', items: ['大特写镜头', '远景定场镜头']},
        {id: 'lighting', label: '光影', items: ['赛博霓虹冷暖对比光']},
      ],
    }),
  };
  const dialog = await mod.openPromptRecommendationDialog(root, ctx, 'proj-1', tag => picked.push(tag));
  const chips = dialog.querySelectorAll('.classic-recommend-chip');
  assert.equal(chips.length, 2);
  await chips[0].click();
  assert.deepEqual(picked, ['大特写镜头']);
  const search = dialog.querySelector('input');
  search.value = '霓虹';
  await search.dispatch('input');
  const filtered = dialog.querySelectorAll('.classic-recommend-chip');
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].textContent, '赛博霓虹冷暖对比光');
});

test('createStoryboardRepaint guards missing params and exports dual-canvas mask edits', async () => {
  const doc = setupDom();
  const root = doc.createElement('section');
  doc.body.append(root);
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-subpages.js'));
  const notices = [], navigated = [], posts = [];
  let rev = 3;
  const ctx = {
    api: async (url, opts) => {
      if (opts?.method === 'POST') {
        const body = JSON.parse(opts.body);
        posts.push({url, body});
        if (url.endsWith('/reference-edits')) return {id: 'edit-v1', revision: ++rev};
        if (url.endsWith('/reference-exports')) {
          return {id: 'exp-1', revision: ++rev, outputs: [{role: 'inpaint-mask', media_id: 'm-mask', sha256: 'c'.repeat(64)}]};
        }
        if (url.endsWith('/drafts')) return {id: `draft-${posts.filter(p => p.url.endsWith('/drafts')).length}`, version: 1, revision: ++rev};
      }
      if (url.includes('/media/m1')) return {id: 'm1', sha256: 'b'.repeat(64), modality: 'image', width: 512, height: 512, name: '分镜1'};
      if (url.includes('/working-candidates')) return {items: []};
      return {revision: rev, drafts: [], models: [], media: [], modes: {image_inpaint: {tool_defaults: {}}}};
    },
    session: () => ({actor: 'human', csrf: 'csrf-1', writable: true, revision: rev}),
    setRevision: v => { rev = v; },
    notice: m => notices.push(m),
    navigate: (...args) => navigated.push(args),
  };

  const repaint = mod.createStoryboardRepaint(root, ctx);
  await repaint.load({projectId: 'p1', shotId: '', mediaId: ''});
  assert.ok(root.textContent.includes('缺少有效的重绘任务参数，请从分镜页面重新进入。'));

  await repaint.load({projectId: 'p1', episodeId: 'ep1', shotId: 'sh1', mediaId: 'm1'});
  const maskCanvas = root.querySelector('.classic-repaint-mask');
  assert.ok(maskCanvas);
  maskCanvas.onpointerdown({clientX: 100, clientY: 100, pointerId: 1, preventDefault() {}});
  maskCanvas.onpointermove({clientX: 200, clientY: 200});
  maskCanvas.onpointerup();
  const promptInput = root.querySelector('textarea');
  promptInput.value = '换成古风斗笠';
  const form = root.querySelector('form');
  await form.dispatch('submit');
  assert.equal(posts.length, 3);
  assert.equal(posts[0].body.payload.document.operations.length, 1);
  assert.equal(posts[0].body.payload.document.operations[0].tool, 'mask');
  assert.equal(posts[2].body.payload.document.mode, 'image_inpaint');
  assert.equal(posts[2].body.payload.base_draft_id, null);

  await form.dispatch('submit');
  assert.equal(posts.length, 6);
  assert.equal(posts[5].body.payload.base_draft_id, 'draft-1');
  repaint.suspend();
});

test('createVideoReview enforces pause-gated review textarea and mark-read / clip download', async () => {
  const doc = setupDom();
  const root = doc.createElement('section');
  doc.body.append(root);
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-subpages.js'));
  const posts = [], notices = [];
  let rev = 2;
  let clipReviews = [];
  const ctx = {
    api: async (url, opts) => {
      if (opts?.method === 'POST') {
        posts.push({url, body: JSON.parse(opts.body)});
        return {revision: ++rev, updated_count: 1};
      }
      if (url.includes('/video-review')) {
        return {
          episode_id: 'ep1',
          episode_title: '第1集',
          clips: [{
            shot_id: 'sh1',
            shot_title: '镜头1',
            candidate_id: 'cand-1',
            media_id: 'vid-1',
            duration_ms: 4000,
            latest_outcome: clipReviews.length ? 'needs_changes' : 'unreviewed',
            reviews: clipReviews,
          }],
        };
      }
      return {items: []};
    },
    session: () => ({actor: 'human', csrf: 'csrf', writable: true, revision: rev}),
    setRevision: v => { rev = v; },
    notice: m => notices.push(m),
    navigate() {},
  };

  const review = mod.createVideoReview(root, ctx);
  await review.load({projectId: 'p1', episodeId: 'ep1'});
  const video = root.querySelector('video');
  const textarea = root.querySelector('textarea');
  assert.equal(textarea.getAttribute('placeholder'), '第1段视频 审核意见（视频播放暂停才能填写）');

  await video.dispatch('play');
  assert.equal(textarea.disabled, true);

  await video.dispatch('pause');
  assert.equal(textarea.disabled, false);

  const unreviewedMarkReadBtn = root.querySelectorAll('button').find(b => b.textContent === '标记已阅');
  assert.equal(unreviewedMarkReadBtn.disabled, true);

  clipReviews = [{id: 'rv-1', outcome: 'needs_changes', reason: '调整节奏', reviewer: 'reviewer', created_at: '2026-11-12T00:00:00Z'}];
  await review.load({projectId: 'p1', episodeId: 'ep1'});
  const markReadBtn = root.querySelectorAll('button').find(b => b.textContent === '标记已阅');
  assert.equal(markReadBtn.disabled, false);
  await markReadBtn.click();
  assert.ok(posts.some(p => p.url.endsWith('/team-review/mark-read') && p.body.payload.candidate_id === 'cand-1' && p.body.payload.shot_id === 'sh1'));
  review.suspend();
});

test('createFcpPortal bridges postMessage auth and navigation', async () => {
  const doc = setupDom();
  const root = doc.createElement('section');
  doc.body.append(root);
  const listeners = new Map();
  globalThis.window = {
    location: {origin: 'http://127.0.0.1:8765'},
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      listeners.set(type, (listeners.get(type) || []).filter(item => item !== fn));
    },
  };
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/classic-subpages.js'));
  const navigated = [], sent = [];
  const portal = mod.createFcpPortal(root, {
    session: () => ({actor: 'human', identityId: 'u-1'}),
    navigate: (page, target) => navigated.push([page, target]),
    notice() {},
  });
  await portal.load({locale: 'ja', projectId: 'p-fcp'});
  const iframe = root.querySelector('iframe');
  assert.equal(iframe.src, '/api/v1/fcp-embed/ja');
  const fakeWin = {postMessage: (msg, origin) => sent.push({msg, origin})};
  Object.defineProperty(iframe, 'contentWindow', {value: fakeWin});
  for (const fn of listeners.get('message') || []) {
    fn({origin: 'https://evil.example', source: fakeWin, data: {type: 'fcp-navigate-home'}});
    fn({origin: '', source: fakeWin, data: {type: 'fcp-navigate-home'}});
    fn({origin: 'http://127.0.0.1:8765', source: null, data: {type: 'fcp-navigate-home'}});
    fn({origin: 'http://127.0.0.1:8765', source: {}, data: {type: 'fcp-navigate-home'}});
    fn({origin: 'http://127.0.0.1:8765', source: fakeWin, data: {type: 'fcp-request-auth'}});
    fn({origin: 'http://127.0.0.1:8765', source: fakeWin, data: {type: 'fcp-navigate-home'}});
  }
  assert.equal(sent.length, 1);
  assert.equal(sent[0].origin, 'http://127.0.0.1:8765');
  assert.equal(sent[0].msg.type, 'fcp-auth-state');
  assert.equal(sent[0].msg.locale, 'ja');
  assert.deepEqual(navigated, [['home', null]]);
  portal.suspend();
});

test('edit-workspace enforces < 2 video multiClipGuard and supports mute & transitions', async () => {
  const doc = setupDom();
  const root = doc.createElement('section');
  doc.body.append(root);
  const mod = await import(pathToFileURL(process.cwd() + '/src/vsc/interfaces/web/static/edit-workspace.js'));
  const blockedMessages = [];
  let videoCount = 1;
  const api = async url => {
    if (url.includes('/edit-workspace')) {
      return {
        project_revision: 1,
        episode: {id: 'ep1', title: '第1集'},
        workspace: {id: 'ws1', revision: 0},
        current: videoCount >= 2 ? {
          id: 'ver1',
          document: {
            format: 'vsc.edit-workspace/v1',
            width: 720,
            height: 1280,
            fps: 24,
            clips: [
              {id: 'c1', shot_id: 'sh-1', media_id: 'med-1', in_frame: 0, out_frame: 72, volume: 1, muted: false},
              {id: 'c2', shot_id: 'sh-2', media_id: 'med-2', in_frame: 0, out_frame: 72, volume: 1, muted: false},
            ],
            audio: [],
            captions: [],
          },
        } : null,
        renders: [],
      };
    }
    if (url.includes('/edit-candidates')) {
      const items = Array.from({length: videoCount}, (_, idx) => ({
        id: 'med-' + (idx + 1),
        shot_id: 'sh-' + (idx + 1),
        shot_number: idx + 1,
        shot_title: '镜头' + (idx + 1),
        media_id: 'med-' + (idx + 1),
        duration_ms: 3000,
        trim_in_ms: 0,
        trim_out_ms: 3000,
        can_add: true,
        selected: true,
        content_url: '/api/v1/projects/p1/media/med-' + (idx + 1) + '/content',
      }));
      return {items, total: items.length, next_offset: null};
    }
    if (url.includes('/edit-seed')) return {document: {clips: [], audio: []}};
    if (url.includes('/media?')) {
      return {
        items: [
          {id: 'med-1', name: '片段1', modality: 'video', duration_ms: 3000},
          {id: 'med-2', name: '片段2', modality: 'video', duration_ms: 3000},
        ],
        total: 2,
      };
    }
    return {id: 'med-1', name: '片段1', modality: 'video', duration_ms: 3000};
  };

  const wsBlocked = mod.createEditWorkspace({
    root,
    api,
    project: 'p1',
    episodeId: 'ep1',
    session: () => ({actor: 'human', csrf: 'c', writable: true, revision: 1}),
    multiClipGuard: true,
    onMultiClipBlocked: msgText => blockedMessages.push(msgText),
  });
  await wsBlocked.load();
  assert.deepEqual(blockedMessages, ['至少需要 2 个可预览视频才能开启视频剪辑']);
  wsBlocked.dispose?.();

  videoCount = 2;
  const wsReady = mod.createEditWorkspace({
    root,
    api,
    project: 'p1',
    episodeId: 'ep1',
    session: () => ({actor: 'human', csrf: 'c', writable: true, revision: 1}),
    multiClipGuard: true,
  });
  await wsReady.load();
  const muteBtn = root.querySelectorAll('button').find(b => b.textContent === '静音视频轨');
  assert.ok(muteBtn);
  await muteBtn.click();
  assert.ok(root.querySelectorAll('button').some(b => b.textContent === '恢复视频轨声音'));
  wsReady.dispose?.();
});

test('panel.js resolvePathnameEntry maps Slice A4 clean SPA routes and /fcp/zh-CN -> /404', () => {
  const replaced = [];
  const env = createPanel(process.cwd(), new Map(), null, {
    window: {
      location: {pathname: '/fcp/zh-CN', search: ''},
      history: {replaceState: (...args) => replaced.push(args), pushState() {}},
      addEventListener() {},
    },
  });
  const resolve = env.panel.resolvePathnameEntry;
  assert.equal(resolve('/storyboard', '').get('page'), 'classic-production');
  assert.equal(resolve('/storyboard', '').get('kind'), 'image');
  assert.equal(resolve('/storyboard/repaint', '').get('page'), 'storyboard-repaint');
  assert.equal(resolve('/video', '').get('page'), 'classic-production');
  assert.equal(resolve('/video', '').get('kind'), 'video');
  assert.equal(resolve('/video/review', '').get('page'), 'video-review');
  assert.equal(resolve('/video/multi-clip', '').get('page'), 'editing');
  const enRoute = resolve('/fcp/en', '');
  assert.equal(enRoute.get('page'), 'fcp-portal');
  assert.equal(enRoute.get('locale'), 'en');
  const zhRoute = resolve('/fcp/zh-CN', '');
  assert.equal(zhRoute.get('page'), 'service-operations');
  assert.equal(zhRoute.get('subview'), 'not-found');
  assert.ok(replaced.some(r => r[2] === '/404'));
});
