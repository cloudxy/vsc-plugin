import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import {
  resolveCanvasPermission,
  sortLockKeys,
  createCollabRecoveryStore,
} from '../../../src/vsc/interfaces/web/static/canvas-collab-recovery.js';
import {createCanvasLibrary} from '../../../src/vsc/interfaces/web/static/canvas-library.js';

const {Document, Element: PanelElement} = createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
PanelElement.prototype.showModal = function () { this.open = true; };
PanelElement.prototype.close = function () { this.open = false; return this.dispatch('close'); };

test('OE permission resolver enforces asymmetric Studio Admin rule and personal workspace button gate', () => {
  // Studio Admin on another member's private canvas (collaboration_enabled=false):
  // canManage=true, showPermissionButton=true, BUT canEdit=false!
  const studioAdminPrivate = resolveCanvasPermission(
    {
      mode: 'manage',
      can_edit: false,
      is_owner: false,
      is_studio_admin: true,
      is_personal_workspace: false,
      collaboration_enabled: false,
    },
    {collaborationEnabled: false},
  );
  assert.equal(studioAdminPrivate.resolvedMode, 'manage');
  assert.equal(studioAdminPrivate.canManage, true);
  assert.equal(studioAdminPrivate.canEdit, false);
  assert.equal(studioAdminPrivate.showPermissionButton, true);

  // Once collaboration_enabled=true, Studio Admin gets canEdit=true
  const studioAdminEnabled = resolveCanvasPermission(
    {
      mode: 'manage',
      can_edit: true,
      is_owner: false,
      is_studio_admin: true,
      is_personal_workspace: false,
      collaboration_enabled: true,
    },
    {collaborationEnabled: true},
  );
  assert.equal(studioAdminEnabled.canEdit, true);
  assert.equal(studioAdminEnabled.showPermissionButton, true);

  // Personal workspace owner: canEdit=true, canManage=true, BUT showPermissionButton=false!
  const personalOwner = resolveCanvasPermission(
    {
      mode: 'manage',
      can_edit: true,
      is_owner: true,
      is_studio_admin: false,
      is_personal_workspace: true,
      collaboration_enabled: false,
    },
    {collaborationEnabled: false},
  );
  assert.equal(personalOwner.canEdit, true);
  assert.equal(personalOwner.canManage, true);
  assert.equal(personalOwner.showPermissionButton, false);

  // URL ?readonly=1 forces view mode
  const forcedView = resolveCanvasPermission(
    {mode: 'manage', can_edit: true, is_owner: true, is_studio_admin: true, is_personal_workspace: false},
    {collaborationEnabled: true, queryReadonly: true},
  );
  assert.equal(forcedView.resolvedMode, 'view');
  assert.equal(forcedView.canEdit, false);
});

test('sortLockKeys deduplicates and sorts node keys lexicographically to prevent deadlocks', () => {
  assert.deepEqual(sortLockKeys(['node-10', 'node-2', 'node-a', 'node-2', '']), ['node-10', 'node-2', 'node-a']);
});

test('recovery store persists records, snapshots and schema migrations', async () => {
  const store = createCollabRecoveryStore();
  const migrations = await store.getMigrations();
  assert.ok(migrations.some(m => m.version === 1));
  await store.putRecord({canvas_id: 'c-rec', client_op_id: 'op-1', base_version: 2, operations: [{op: 'upsert_node'}]});
  await store.putRecord({canvas_id: 'c-rec', client_op_id: 'op-2', base_version: 2, operations: [{op: 'delete_node'}]});
  await store.saveSnapshot('c-rec', {version: 2, title: 'Offline Draft', document: {nodes: [], edges: []}});
  assert.equal((await store.listRecords('c-rec')).length, 2);
  assert.equal((await store.getSnapshot('c-rec')).title, 'Offline Draft');
  await store.deleteRecords('c-rec', ['op-1']);
  assert.equal((await store.listRecords('c-rec')).length, 1);
  await store.clearCanvas('c-rec');
  assert.equal((await store.listRecords('c-rec')).length, 0);
  store.dispose();
});

test('canvas library enables collaboration switch, confirms before turning off, and preloads user preference on create', async () => {
  const doc = new Document('');
  const root = doc.createElement('section');
  doc.body.append(root);
  globalThis.document = doc;
  const storage = new Map();
  globalThis.sessionStorage = {
    getItem: k => storage.get(k) || null,
    setItem: (k, v) => storage.set(k, v),
    removeItem: k => storage.delete(k),
  };
  let collabState = false;
  const calls = [];
  const rows = () => [
    {
      id: 'canvas-1',
      project_id: 'p1',
      project_name: '项目一',
      episode_id: 'ep1',
      episode_name: '第一集',
      title: '团队画布',
      canvas_revision: 1,
      version_id: 'v1',
      updated_at: '2026-11-11T00:00:00Z',
      creator_id: 'human',
      creator_name: '创建者',
      collaboration_enabled: collabState,
      permissions: {can_read: true, can_edit: true, can_rename: true, can_copy: true, can_delete: true, can_manage_collaboration: true},
    },
    {
      id: 'canvas-ro',
      project_id: 'p1',
      project_name: '项目一',
      episode_id: 'ep1',
      episode_name: '第一集',
      title: '他人私有画布',
      canvas_revision: 1,
      version_id: 'v2',
      updated_at: '2026-11-11T00:00:00Z',
      creator_id: 'other',
      creator_name: '其他成员',
      collaboration_enabled: false,
      permissions: {can_read: true, can_edit: false, can_rename: false, can_copy: true, can_delete: false, can_manage_collaboration: false},
    },
  ];
  const ctx = {
    session: () => ({actor: 'human', identityId: 'id-1', workspaceId: 'ws-1', csrf: 'csrf', writeAvailable: true}),
    projects: async () => ({items: [{id: 'p1', name: '项目一', permissions: {can_edit: true}}], creators: []}),
    episodes: async () => ({items: [{id: 'ep1', title: '第一集'}], revision: 4}),
    notice: () => {},
    setRevision: () => {},
    navigate: async () => {},
    api: async (url, options = {}) => {
      const body = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
      calls.push({url, options, body});
      if (url.startsWith('/api/v1/canvas-library?')) {
        return {items: rows(), total: 2, next_offset: null, capabilities: {collaboration: true, cross_episode_copy: true}};
      }
      if (url === '/api/v1/user-preferences' && !options.method) {
        return {preferences: {collaboration: {enabled_on_new_canvas: true}}};
      }
      if (url === '/api/v1/user-preferences' && options.method === 'PUT') {
        assert.deepEqual(body, {preferences: {collaboration: {enabled_on_new_canvas: false}}});
        return {preferences: body.preferences};
      }
      if (url.endsWith('/collaboration') && options.method === 'POST') {
        collabState = body.payload.collaboration_enabled;
        return {id: 'canvas-1', canvas_id: 'canvas-1', collaboration_enabled: collabState, revision: 5};
      }
      if (url.endsWith('/creative-canvases/canvas-1') && !options.method) {
        return {id: 'canvas-1', project_id: 'p1', episode_id: 'ep1', revision: 4, canvas_revision: 1, title: '团队画布', document: {nodes: [], edges: []}};
      }
      if (url.includes('creative-canvases?')) return {items: [], revision: 5};
      if (url.endsWith('/creative-canvases') && options.method === 'POST') {
        return {id: 'new-canvas', revision: 6, canvas_revision: 1, title: body.payload.title};
      }
      throw new Error('unexpected ' + url);
    },
  };

  const lib = createCanvasLibrary(root, ctx);
  await lib.load();
  // View-only card shows readonly badge
  assert.equal(root.querySelectorAll('.cl-readonly-badge').length, 1);

  // Switch is enabled and turning false -> true posts immediately without confirm dialog
  const sw = root.querySelector('.cl-collaboration-switch');
  assert.equal(sw.disabled, false);
  await sw.click();
  assert.equal(collabState, true);
  assert.equal(root.querySelector('dialog'), null);

  // Turning true -> false opens secondary confirmation dialog first!
  await root.querySelector('.cl-collaboration-switch').click();
  const confirmDialog = root.querySelector('dialog');
  assert.ok(confirmDialog);
  assert.equal(collabState, true);
  await confirmDialog.querySelector('form').dispatch('submit');
  assert.equal(collabState, false);

  // Create modal reads /api/v1/user-preferences ({preferences: ...}) and writes {preferences: ...}
  await lib.openCreate();
  await new Promise(r => setTimeout(r, 10));
  const createDialog = root.querySelector('dialog');
  const defaultBtn = createDialog.querySelector('.cl-collab-default-btn');
  assert.equal(defaultBtn.getAttribute('aria-pressed'), 'true');
  await defaultBtn.click();
  assert.equal(defaultBtn.getAttribute('aria-pressed'), 'false');
  const toggleBox = createDialog.querySelectorAll('input').find(i => i.type === 'checkbox');
  toggleBox.checked = true;
  await toggleBox.dispatch('change');
  const [projSel, epSel] = createDialog.querySelectorAll('select');
  projSel.value = 'p1';
  await projSel.dispatch('change');
  epSel.value = 'ep1';
  await epSel.dispatch('change');
  const nameInput = createDialog.querySelectorAll('input').find(i => i.type !== 'checkbox');
  nameInput.value = '默认协作新画布';
  await nameInput.dispatch('input');
  await createDialog.querySelector('form').dispatch('submit');
  const createCall = calls.find(c => c.url === '/api/v1/projects/p1/creative-canvases' && c.options.method === 'POST');
  assert.equal(createCall.body.payload.collaboration_enabled, true);
  lib.suspend();
});

class MiniElement {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.value = '';
    this.style = {removeProperty(k) { delete this[k]; }, setProperty(k, v) { this[k] = v; }};
    this.offsetWidth = 200;
    this.offsetHeight = 200;
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
      toggle: (v, f) => { if (f === undefined ? !this.classList.contains(v) : f) this.classList.add(v); else this.classList.remove(v); },
    };
  }
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...nodes) { for (const n of nodes) { n.remove(); n.parentElement = this; this.children.push(n); } }
  prepend(...nodes) { for (const n of nodes.reverse()) { n.remove(); n.parentElement = this; this.children.unshift(n); } }
  remove() { if (this.parentElement) { this.parentElement.children = this.parentElement.children.filter(x => x !== this); this.parentElement = null; } }
  replaceChildren(...nodes) { for (const c of [...this.children]) c.remove(); this._text = ''; this.append(...nodes); }
  insertBefore(node, before) { node.remove(); node.parentElement = this; const i = this.children.indexOf(before); this.children.splice(i < 0 ? this.children.length : i, 0, node); }
  removeAttribute(k) { delete this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  matches(selector) {
    if (selector[0] === '.') return this.classList.contains(selector.slice(1));
    if (selector[0] === '[') {
      const m = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return m && (m[2] == null ? (this.attrs[m[1]] != null || this.dataset?.[m[1].replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())] != null) : (this.attrs[m[1]] === m[2] || (m[1] === 'data-node-id' && this.dataset.nodeId === m[2])));
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    if (selector.startsWith(':scope > ')) return this.children.filter(c => c.matches(selector.slice(9)));
    const all = this.children.flatMap(c => [c, ...c.querySelectorAll('*')]);
    if (selector === '*') return all;
    return all.filter(c => selector.split(',').some(x => c.matches(x.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let n = this; n; n = n.parentElement) if (selector.split(',').some(p => n.matches(p.trim()))) return n; return null; }
  getBoundingClientRect() { return {left: 0, top: 0, width: 1200, height: 800}; }
  addEventListener(k, v) { (this.listeners[k] ??= []).push(v); }
  get options() { return this.children.filter(x => x.tagName === 'OPTION'); }
  get isConnected() { return this.parentElement !== null; }
  async fire(type, props = {}) {
    let prevented = false;
    const event = {target: this, preventDefault() { prevented = true; }, stopPropagation() {}, get defaultPrevented() { return prevented; }, ...props};
    for (const fn of this.listeners[type] || []) await fn(event);
    return event;
  }
  pause() {}
  focus() { this.ownerDocument.activeElement = this; }
  select() {}
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; return this.fire('close'); }
}

test('creative-canvas collaboration bar, WS sync_protocol=2, locks, live downgrade, 11103 conflict and 4009 kick dialog', async () => {
  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      this.bufferedAmount = 0;
      this.sent = [];
      this.listeners = {};
      sockets.push(this);
      setTimeout(() => this.emit('open', {}), 0);
    }
    addEventListener(k, fn) { (this.listeners[k] ??= []).push(fn); }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    close(code = 1000) { this.readyState = 3; this.emit('close', {code}); }
    emit(type, ev) { for (const fn of this.listeners[type] || []) fn(ev); }
    inbound(frame) { this.emit('message', {data: JSON.stringify(frame)}); }
  }

  const document = {
    visibilityState: 'visible',
    createElement: t => { const n = new MiniElement(t); n.ownerDocument = document; return n; },
    createElementNS: (ns, t) => { const n = document.createElement(t); n.namespaceURI = ns; return n; },
    createTextNode: text => { const n = new MiniElement('#text', text); n.ownerDocument = document; return n; },
    documentElement: {},
  };
  const store = new Map();
  const sessionStorage = {getItem: k => store.get(k) || null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)};
  const window = {addEventListener() {}, removeEventListener() {}};
  const location = {search: '', protocol: 'http:', host: '127.0.0.1:8765'};
  const mod = await loadModule('creative-canvas.js', {
    document,
    window,
    location,
    sessionStorage,
    crypto,
    console,
    WebSocket: FakeWebSocket,
    Image: class {},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => {},
    fetch: async () => ({ok: true, text: async () => ''}),
    setTimeout,
    clearTimeout,
  });

  const root = document.createElement('main');
  const canvasPanel = mod.createCreativeCanvasPanel({
    session: () => ({actor: 'editor-1', csrf: 'csrf', revision: 2, writable: true}),
    setRevision() {},
    opened() {},
    api: async (path, options = {}) => {
      if (path.endsWith('/creative-canvases/c1') && !options.method) {
        return {
          id: 'c1',
          canvas_id: 'c1',
          project_id: 'p1',
          episode_id: 'ep1',
          revision: 2,
          canvas_revision: 1,
          canvas_seq: 3,
          collaboration_enabled: true,
          title: '协作画布',
          permission: {
            mode: 'manage',
            can_edit: true,
            is_owner: true,
            is_studio_admin: true,
            can_manage_collaboration: true,
            is_personal_workspace: false,
            collaboration_enabled: true,
          },
          collaborators: [{id: 'u1', actor: 'editor-1', display_name: '主编', is_owner: true, access_label: '创建者'}],
          members: [],
          locks: [],
          document: {viewport: {x: 0, y: 0, zoom: 1}, nodes: [{id: 'n1', type: 'text', title: '镜头一', text: '初始文案', x: 100, y: 120, group: '', params: {}, media_id: null, job_id: null}], edges: []},
          jobs: {},
          runs: [],
          execution_steps: [],
        };
      }
      if (path.endsWith('/collab/ticket')) {
        return {ticket: 'tk_test_1', mode: 'edit', page_session_id: 'ps_1', expires_at_ms: Date.now() + 60000};
      }
      if (path.endsWith('/recovery/batch')) {
        const body = JSON.parse(options.body);
        if (body.expected_revision === 2) {
          const revErr = new Error('版本已变化');
          revErr.status = 409;
          revErr.code = 'revision_conflict';
          throw revErr;
        }
        if (!body.payload.force_overwrite) {
          const err = new Error('协作冲突');
          err.status = 409;
          err.code = 'canvas_conflict';
          err.error_code = 11103;
          err.conflicts = [{
            node_id: 'n1',
            node_title: '镜头一',
            conflict_type: 'concurrent_modify',
            local_summary: '本地修改',
            remote_summary: '远端修改',
            local_draft: {id: 'n1', type: 'text', title: '镜头一', text: '完整本地草稿内容'},
            locked_by: {node_key: 'n1', session_id: 'remote-s2', owner_user_id: 'other-user', owner_actor: 'other-actor', owner_name: '协作者乙', color: '#f97316'},
          }];
          throw err;
        }
        return {id: 'c1', version: 2, canvas_revision: 2, canvas_seq: 4, revision: 6, title: '协作画布', document: {viewport: {x: 0, y: 0, zoom: 1}, nodes: [], edges: []}};
      }
      return {items: [], revision: 2};
    },
  });

  await canvasPanel.load(root, 'p1', 'ep1', 'c1');
  await new Promise(r => setTimeout(r, 15));

  // Studio workspace shows permission button and collaboration bar
  const bar = root.querySelector('.canvas-collaboration-bar');
  assert.ok(bar);
  const permWrap = root.querySelector('.cc-collab-perm-wrap');
  assert.equal(permWrap.hidden, false);

  // WS connected with sync_protocol=2
  assert.equal(sockets.length, 1);
  assert.match(sockets[0].url, /sync_protocol=2/);
  sockets[0].inbound({type: 'session.ready', payload: {session_id: 'my-s1'}});
  sockets[0].inbound({
    type: 'canvas.sync.snapshot',
    payload: {
      protocol_version: 2,
      canvas_seq: 3,
      permission: {mode: 'manage', can_edit: true, is_owner: true, is_studio_admin: true, is_personal_workspace: false, collaboration_enabled: true},
      members: [
        {session_id: 'my-s1', user_id: 'editor-1', nickname: '主编', is_owner: true, mode: 'edit', color: '#22c55e'},
        {session_id: 'remote-s2', user_id: 'other-user', nickname: '协作者乙', is_owner: false, mode: 'edit', color: '#f97316'},
      ],
      locks: [],
    },
  });
  assert.equal(root.querySelector('.cc-collab-avatars').querySelectorAll('.cc-collab-avatar').length, 2);

  // Ping -> Pong
  sockets[0].inbound({type: 'ping', payload: {server_ts: 12345}});
  assert.equal(sockets[0].sent.at(-1).type, 'pong');

  // Remote lock decorates node with lock badge; unlocking another node keeps n1 locked, unlocking n1 clears badge!
  sockets[0].inbound({
    type: 'node.lock.rejected',
    payload: {reason: 'locked_by_other', node_keys: ['n1'], conflicts: [{node_key: 'n1', session_id: 'remote-s2', owner_user_id: 'other-user', owner_actor: 'other-actor', owner_name: '协作者乙', color: '#f97316', fencing_token: 7}]},
  });
  assert.ok(root.querySelector('.cc-node-lock-badge'));
  sockets[0].inbound({
    type: 'node.unlocked',
    payload: {
      unlocked: [{node_key: 'other-node', fencing_token: 6}],
      node_keys: ['other-node'],
      fencing_token: 6,
      locks: [{node_key: 'n1', session_id: 'remote-s2', owner_user_id: 'other-user', owner_actor: 'other-actor', owner_name: '协作者乙', color: '#f97316', fencing_token: 7}],
    },
  });
  assert.ok(root.querySelector('.cc-node-lock-badge'), 'active lock on n1 must remain when other-node unlocks');

  // Inbound 11103 conflict (backend wire shape: error_code + node_id + node_title) opens non-dismissable dialog with overwrite disabled
  sockets[0].inbound({
    type: 'canvas.ops.rejected',
    payload: {
      error_code: 11103,
      reason: 'version_conflict',
      conflicts: [{
        node_id: 'n1',
        node_title: '镜头一',
        conflict_type: 'concurrent_modify',
        local_summary: '我的提示词',
        remote_summary: '乙的提示词',
        local_draft: {id: 'n1', type: 'text', title: '镜头一', text: '完整草稿'},
        locked_by: {node_key: 'n1', session_id: 'remote-s2', owner_user_id: 'other-user', owner_actor: 'other-actor', owner_name: '协作者乙', color: '#f97316'},
      }],
    },
  });
  const conflictModal = root.querySelector('.canvas-conflict-dialog');
  assert.ok(conflictModal);
  assert.match(conflictModal.textContent, /镜头一/);
  const cancelEvent = await conflictModal.fire('cancel');
  assert.equal(cancelEvent.defaultPrevented, true);
  assert.equal(conflictModal.querySelector('.cc-conflict-overwrite').disabled, true);

  // Unlocking n1 clears the remote lock badge!
  sockets[0].inbound({
    type: 'node.unlocked',
    payload: {
      unlocked: [{node_key: 'n1', fencing_token: 7}],
      node_keys: ['n1'],
      fencing_token: 7,
      locks: [],
    },
  });
  assert.equal(root.querySelector('.cc-node-lock-badge'), null);

  // Live permission.changed downgrade switches pill to 只读
  sockets[0].inbound({
    type: 'permission.changed',
    payload: {
      collaboration_enabled: false,
      canvas_seq: 5,
      permission: {mode: 'readonly', can_edit: false, is_owner: false, is_studio_admin: false, is_personal_workspace: false, collaboration_enabled: false},
    },
  });
  assert.equal(root.querySelector('.cc-collab-sync-pill').dataset.state, 'readonly');

  // 4009 close opens canvas-session-kicked-dialog
  sockets[0].close(4009);
  assert.ok(root.querySelector('.canvas-session-kicked-dialog'));

  canvasPanel.suspend();
});
