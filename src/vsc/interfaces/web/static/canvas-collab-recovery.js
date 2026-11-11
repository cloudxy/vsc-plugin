import {msg, setText, bindAttribute, translate} from './i18n.js';

const ckey = name => 'canvas.collab.' + name;
const clabel = (name, values) => msg(ckey(name), values);
const lkey = name => 'canvas.library.' + name;
const llabel = (name, values) => msg(lkey(name), values);

export const COLLAB_BACKOFF_MS = [1000, 2000, 5000, 10000];
export const COLLAB_CURSOR_TTL_MS = 1500;
export const COLLAB_PREVIEW_TTL_MS = 1300;
export const COLLAB_LOCK_TIMEOUT_MS = 8000;
export const COLLAB_LOCK_RENEW_MS = 8000;
export const COLLAB_FOCUS_RESYNC_MS = 45000;
export const COLLAB_BUFFER_CAP_BYTES = 262144;

export function sortLockKeys(nodeKeys) {
  return [...new Set((nodeKeys || []).map(v => String(v || '').trim()).filter(Boolean))]
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

export function resolveCanvasPermission(
  permission,
  {
    collaborationEnabled,
    isOfficialExample = false,
    readonlyReason = '',
    queryReadonly = false,
    isPersonalUser = null,
    isLoaded = true,
  } = {},
) {
  const collab = typeof collaborationEnabled === 'boolean'
    ? collaborationEnabled
    : permission?.collaboration_enabled !== false;
  const forcedReadonly = Boolean(
    isOfficialExample
    || readonlyReason
    || queryReadonly
    || !permission
    || permission.mode === 'forbidden'
    || (permission.can_edit === false && !permission.is_owner && !permission.is_studio_admin)
  );
  let resolvedMode;
  if (forcedReadonly) resolvedMode = 'view';
  else if (permission.is_owner || permission.is_studio_admin) resolvedMode = 'manage';
  else if (permission.mode === 'readonly' || permission.can_edit === false) resolvedMode = 'view';
  else resolvedMode = 'edit';

  const canManage = resolvedMode === 'manage';
  const canEdit = collab === false
    ? Boolean(permission?.is_owner === true && permission?.can_edit !== false && resolvedMode !== 'view')
    : Boolean(permission?.can_edit !== false && (resolvedMode === 'edit' || resolvedMode === 'manage'));
  const personal = typeof isPersonalUser === 'boolean'
    ? isPersonalUser
    : Boolean(permission?.is_personal_workspace);
  const showPermissionButton = Boolean(isLoaded && canManage && !personal);
  return {
    resolvedMode,
    canManage,
    canEdit,
    collaborationEnabled: collab,
    isPersonalUser: personal,
    showPermissionButton,
  };
}

const WORKER_SCRIPT = `
const DB_NAME = 'canvas-async-recovery';
const DB_VERSION = 1;
let dbPromise = null;
function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('records')) {
        const store = db.createObjectStore('records', { keyPath: ['canvas_id', 'client_op_id'] });
        store.createIndex('by_canvas', 'canvas_id', { unique: false });
      }
      if (!db.objectStoreNames.contains('snapshots')) {
        db.createObjectStore('snapshots', { keyPath: 'canvas_id' });
      }
      if (!db.objectStoreNames.contains('migrations')) {
        db.createObjectStore('migrations', { keyPath: 'version' });
      }
    };
    req.onsuccess = () => {
      const db = req.result;
      const tx = db.transaction('migrations', 'readwrite');
      tx.objectStore('migrations').put({ version: 1, applied_at: Date.now() });
      resolve(db);
    };
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}
self.onmessage = async (event) => {
  const { id, op, payload } = event.data || {};
  try {
    const db = await openDb();
    let result = null;
    if (op === 'putRecord') {
      await new Promise((res, rej) => {
        const tx = db.transaction('records', 'readwrite');
        tx.objectStore('records').put(payload);
        tx.oncomplete = () => res(true);
        tx.onerror = () => rej(tx.error);
      });
      result = true;
    } else if (op === 'listRecords') {
      result = await new Promise((res, rej) => {
        const tx = db.transaction('records', 'readonly');
        const idx = tx.objectStore('records').index('by_canvas');
        const req = idx.getAll(payload.canvasId);
        req.onsuccess = () => res((req.result || []).sort((a, b) => (a.created_at || 0) - (b.created_at || 0)));
        req.onerror = () => rej(req.error);
      });
    } else if (op === 'deleteRecords') {
      await new Promise((res, rej) => {
        const tx = db.transaction('records', 'readwrite');
        const store = tx.objectStore('records');
        for (const opId of payload.clientOpIds || []) store.delete([payload.canvasId, opId]);
        tx.oncomplete = () => res(true);
        tx.onerror = () => rej(tx.error);
      });
      result = true;
    } else if (op === 'clearCanvas') {
      const rows = await new Promise((res, rej) => {
        const tx = db.transaction('records', 'readonly');
        const req = tx.objectStore('records').index('by_canvas').getAllKeys(payload.canvasId);
        req.onsuccess = () => res(req.result || []);
        req.onerror = () => rej(req.error);
      });
      await new Promise((res, rej) => {
        const tx = db.transaction('records', 'readwrite');
        const store = tx.objectStore('records');
        for (const key of rows) store.delete(key);
        tx.oncomplete = () => res(true);
        tx.onerror = () => rej(tx.error);
      });
      result = true;
    } else if (op === 'saveSnapshot') {
      await new Promise((res, rej) => {
        const tx = db.transaction('snapshots', 'readwrite');
        tx.objectStore('snapshots').put({ canvas_id: payload.canvasId, ...payload.snapshot, updated_at: Date.now() });
        tx.oncomplete = () => res(true);
        tx.onerror = () => rej(tx.error);
      });
      result = true;
    } else if (op === 'getSnapshot') {
      result = await new Promise((res, rej) => {
        const tx = db.transaction('snapshots', 'readonly');
        const req = tx.objectStore('snapshots').get(payload.canvasId);
        req.onsuccess = () => res(req.result || null);
        req.onerror = () => rej(req.error);
      });
    } else if (op === 'getMigrations') {
      result = await new Promise((res, rej) => {
        const tx = db.transaction('migrations', 'readonly');
        const req = tx.objectStore('migrations').getAll();
        req.onsuccess = () => res(req.result || []);
        req.onerror = () => rej(req.error);
      });
    }
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({ id, ok: false, error: err?.message || String(err) });
  }
};
`;

const memoryStores = {
  records: new Map(),
  snapshots: new Map(),
  migrations: new Map([[1, {version: 1, applied_at: Date.now()}]]),
};

export function createCollabRecoveryStore({dbName = 'canvas-async-recovery'} = {}) {
  let worker = null;
  let workerBroken = false;
  let directDbPromise = null;
  let reqSeq = 0;
  const pending = new Map();

  function ensureWorker() {
    if (workerBroken || typeof indexedDB === 'undefined' || typeof Worker === 'undefined' || typeof Blob === 'undefined' || typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
      return null;
    }
    if (worker) return worker;
    try {
      const url = URL.createObjectURL(new Blob([WORKER_SCRIPT], {type: 'text/javascript'}));
      worker = new Worker(url);
      worker.onmessage = event => {
        const {id, ok, result, error} = event.data || {};
        const waiter = pending.get(id);
        if (!waiter) return;
        pending.delete(id);
        if (ok) waiter.resolve(result);
        else waiter.reject(new Error(error || 'recovery worker error'));
      };
      worker.onerror = () => {
        workerBroken = true;
        for (const [, waiter] of pending) waiter.reject(new Error('recovery worker unavailable'));
        pending.clear();
        try { worker.terminate(); } catch {}
        worker = null;
      };
      return worker;
    } catch {
      workerBroken = true;
      return null;
    }
  }

  function openDirectDb() {
    if (typeof indexedDB === 'undefined') return Promise.resolve(null);
    if (directDbPromise) return directDbPromise;
    directDbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(dbName, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('records')) {
          const store = db.createObjectStore('records', {keyPath: ['canvas_id', 'client_op_id']});
          store.createIndex('by_canvas', 'canvas_id', {unique: false});
        }
        if (!db.objectStoreNames.contains('snapshots')) db.createObjectStore('snapshots', {keyPath: 'canvas_id'});
        if (!db.objectStoreNames.contains('migrations')) db.createObjectStore('migrations', {keyPath: 'version'});
      };
      req.onsuccess = () => {
        const db = req.result;
        try {
          const tx = db.transaction('migrations', 'readwrite');
          tx.objectStore('migrations').put({version: 1, applied_at: Date.now()});
        } catch {}
        resolve(db);
      };
      req.onerror = () => reject(req.error);
    });
    return directDbPromise;
  }

  async function call(op, payload) {
    const w = ensureWorker();
    if (w) {
      try {
        return await new Promise((resolve, reject) => {
          const id = ++reqSeq;
          pending.set(id, {resolve, reject});
          w.postMessage({id, op, payload});
        });
      } catch {
        workerBroken = true;
      }
    }
    const db = await openDirectDb().catch(() => null);
    if (db) {
      if (op === 'putRecord') {
        return new Promise((res, rej) => {
          const tx = db.transaction('records', 'readwrite');
          tx.objectStore('records').put(payload);
          tx.oncomplete = () => res(true);
          tx.onerror = () => rej(tx.error);
        });
      }
      if (op === 'listRecords') {
        return new Promise((res, rej) => {
          const tx = db.transaction('records', 'readonly');
          const req = tx.objectStore('records').index('by_canvas').getAll(payload.canvasId);
          req.onsuccess = () => res((req.result || []).sort((a, b) => (a.created_at || 0) - (b.created_at || 0)));
          req.onerror = () => rej(req.error);
        });
      }
      if (op === 'deleteRecords') {
        return new Promise((res, rej) => {
          const tx = db.transaction('records', 'readwrite');
          const store = tx.objectStore('records');
          for (const id of payload.clientOpIds || []) store.delete([payload.canvasId, id]);
          tx.oncomplete = () => res(true);
          tx.onerror = () => rej(tx.error);
        });
      }
      if (op === 'clearCanvas') {
        const keys = await new Promise((res, rej) => {
          const tx = db.transaction('records', 'readonly');
          const req = tx.objectStore('records').index('by_canvas').getAllKeys(payload.canvasId);
          req.onsuccess = () => res(req.result || []);
          req.onerror = () => rej(req.error);
        });
        return new Promise((res, rej) => {
          const tx = db.transaction('records', 'readwrite');
          const store = tx.objectStore('records');
          for (const key of keys) store.delete(key);
          tx.oncomplete = () => res(true);
          tx.onerror = () => rej(tx.error);
        });
      }
      if (op === 'saveSnapshot') {
        return new Promise((res, rej) => {
          const tx = db.transaction('snapshots', 'readwrite');
          tx.objectStore('snapshots').put({canvas_id: payload.canvasId, ...payload.snapshot, updated_at: Date.now()});
          tx.oncomplete = () => res(true);
          tx.onerror = () => rej(tx.error);
        });
      }
      if (op === 'getSnapshot') {
        return new Promise((res, rej) => {
          const tx = db.transaction('snapshots', 'readonly');
          const req = tx.objectStore('snapshots').get(payload.canvasId);
          req.onsuccess = () => res(req.result || null);
          req.onerror = () => rej(req.error);
        });
      }
      if (op === 'getMigrations') {
        return new Promise((res, rej) => {
          const tx = db.transaction('migrations', 'readonly');
          const req = tx.objectStore('migrations').getAll();
          req.onsuccess = () => res(req.result || []);
          req.onerror = () => rej(req.error);
        });
      }
    }
    if (op === 'putRecord') {
      memoryStores.records.set(`${payload.canvas_id}:${payload.client_op_id}`, {...payload});
      return true;
    }
    if (op === 'listRecords') {
      return [...memoryStores.records.values()]
        .filter(r => r.canvas_id === payload.canvasId)
        .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
    }
    if (op === 'deleteRecords') {
      for (const id of payload.clientOpIds || []) memoryStores.records.delete(`${payload.canvasId}:${id}`);
      return true;
    }
    if (op === 'clearCanvas') {
      for (const key of [...memoryStores.records.keys()]) {
        if (key.startsWith(`${payload.canvasId}:`)) memoryStores.records.delete(key);
      }
      return true;
    }
    if (op === 'saveSnapshot') {
      memoryStores.snapshots.set(payload.canvasId, {canvas_id: payload.canvasId, ...payload.snapshot, updated_at: Date.now()});
      return true;
    }
    if (op === 'getSnapshot') return memoryStores.snapshots.get(payload.canvasId) || null;
    if (op === 'getMigrations') return [...memoryStores.migrations.values()];
    return null;
  }

  return {
    dbName,
    putRecord: record => call('putRecord', {...record, created_at: record.created_at || Date.now()}),
    listRecords: canvasId => call('listRecords', {canvasId}),
    deleteRecords: (canvasId, clientOpIds) => call('deleteRecords', {canvasId, clientOpIds}),
    clearCanvas: canvasId => call('clearCanvas', {canvasId}),
    saveSnapshot: (canvasId, snapshot) => call('saveSnapshot', {canvasId, snapshot}),
    getSnapshot: canvasId => call('getSnapshot', {canvasId}),
    getMigrations: () => call('getMigrations', {}),
    dispose() {
      if (worker) {
        try { worker.terminate(); } catch {}
        worker = null;
      }
      pending.clear();
    },
  };
}

export function formatRelativeCanvasTime(isoString) {
  if (!isoString) return '';
  const ts = new Date(isoString).getTime();
  if (!Number.isFinite(ts)) return '';
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return '刚刚';
  if (diffSec < 3600) return translate(msg('media.library.minutes_ago', {count: Math.floor(diffSec / 60)}));
  if (diffSec < 86400) return translate(msg('media.library.hours_ago', {count: Math.floor(diffSec / 3600)}));
  if (diffSec < 604800) return translate(msg('media.library.days_ago', {count: Math.floor(diffSec / 86400)}));
  return translate(msg('media.library.weeks_ago', {count: Math.floor(diffSec / 604800)}));
}

function makeEl(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) setText(node, text);
  if (cls) node.className = cls;
  return node;
}

async function copyTextToClipboard(text) {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {}
  }
  const area = document.createElement('textarea');
  area.value = text;
  document.body?.append?.(area);
  area.select?.();
  try { document.execCommand?.('copy'); } catch {}
  area.remove();
  return true;
}

export function createCanvasCollabController({
  state,
  ctx,
  url,
  headers,
  isLive,
  onPermissionApplied,
  onRemoteDocument,
  onJobUpdated,
  onBackToList,
  onRedrawWorld,
  notice,
  recoveryStore = createCollabRecoveryStore(),
}) {
  const pageSessionKey = `vsc-collab-page-session:${state.project}:${state.id}`;
  let pageSessionId = null;
  try {
    pageSessionId = sessionStorage.getItem(pageSessionKey);
    if (!pageSessionId) {
      pageSessionId = `ps_${crypto.randomUUID()}`;
      sessionStorage.setItem(pageSessionKey, pageSessionId);
    }
  } catch {
    pageSessionId = `ps_${crypto.randomUUID()}`;
  }

  let disposed = false;
  let ws = null;
  let sessionId = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let renewTimer = null;
  let cursorCleanupTimer = null;
  let previewTimer = null;
  let lastHiddenAt = 0;
  let kicked = false;
  let syncState = 'synced';
  let localSeq = Number(state.canvasSeq || 1);
  let permissionRaw = state.permission || null;
  let collabEnabled = Boolean(state.collaborationEnabled);
  let collaborators = Array.isArray(state.collaborators) ? [...state.collaborators] : [];
  let members = Array.isArray(state.members) ? [...state.members] : [];
  const remoteLocks = new Map();
  const heldLocks = new Map();
  const pendingLockWaiters = new Map();
  const remoteCursors = new Map();
  const remotePreviews = new Map();
  let conflicts = [];
  let lastPreviewSentAt = 0;
  let adaptiveIntervalMs = 60;
  let queuedPreviewNodes = null;
  let lastCursorSentAt = 0;

  for (const lock of state.initialLocks || []) {
    if (lock?.node_key) remoteLocks.set(lock.node_key, {...lock});
  }

  let barEl = null;
  let syncPill = null;
  let conflictPill = null;
  let avatarsWrap = null;
  let membersPopover = null;
  let permWrap = null;
  let permButton = null;
  let permPopover = null;
  let permSwitch = null;
  let permList = null;
  let overlayEl = null;
  let conflictDialog = null;
  let kickedDialog = null;

  function computePerm() {
    const queryReadonly = typeof location !== 'undefined' && new URLSearchParams(location.search || '').get('readonly') === '1';
    return resolveCanvasPermission(permissionRaw, {
      collaborationEnabled: collabEnabled,
      isOfficialExample: Boolean(state.isOfficialExample),
      readonlyReason: state.readonlyReason || '',
      queryReadonly,
      isLoaded: true,
    });
  }

  function syncLabelFor(kind) {
    if (kind === 'syncing') return clabel('syncing');
    if (kind === 'reconnecting') return clabel('reconnecting');
    if (kind === 'offline') return clabel('offline');
    if (kind === 'readonly') return clabel('readonly');
    if (kind === 'failed') return clabel('failed');
    return clabel('synced');
  }

  function setSyncState(next) {
    const perm = computePerm();
    syncState = !perm.canEdit ? 'readonly' : next;
    paintBar();
  }

  function isLockOwnedBySelf(lock) {
    if (!lock) return false;
    if (sessionId && lock.session_id) return lock.session_id === sessionId;
    const sess = ctx.session?.() || {};
    if (sess.identityId && lock.owner_user_id === sess.identityId) return true;
    if (sess.actor && (lock.owner_actor === sess.actor || lock.owner_user_id === sess.actor)) return true;
    return false;
  }

  function isNodeLockedByOther(nodeKey) {
    if (!nodeKey) return null;
    const lock = remoteLocks.get(nodeKey);
    if (!lock) return null;
    if (lock.expires_at) {
      const exp = new Date(lock.expires_at).getTime();
      if (Number.isFinite(exp) && exp <= Date.now()) {
        remoteLocks.delete(nodeKey);
        return null;
      }
    }
    if (isLockOwnedBySelf(lock)) return null;
    return lock;
  }

  function reconcileAuthoritativeLocks(locks) {
    if (!Array.isArray(locks)) return;
    remoteLocks.clear();
    const myActive = new Set();
    for (const l of locks) {
      if (!l?.node_key) continue;
      remoteLocks.set(l.node_key, l);
      if (sessionId && l.session_id === sessionId) {
        myActive.add(l.node_key);
        heldLocks.set(l.node_key, {fencing_token: l.fencing_token, expires_at: l.expires_at});
      }
    }
    if (sessionId) {
      for (const key of [...heldLocks.keys()]) {
        if (!myActive.has(key)) heldLocks.delete(key);
      }
    }
  }

  function normalizeConflictItem(item) {
    const nodeKey = item?.node_id ?? item?.node_key ?? '__canvas__';
    const nodeTitle = item?.node_title ?? item?.title ?? state.title;
    return {
      ...item,
      node_id: nodeKey,
      node_key: nodeKey,
      node_title: nodeTitle,
      title: nodeTitle,
    };
  }

  function syncPopoverAria() {
    if (permButton && permPopover) {
      permButton.setAttribute('aria-expanded', String(!permPopover.hidden));
    }
    if (avatarsWrap && membersPopover) {
      const expanded = String(!membersPopover.hidden);
      for (const btn of avatarsWrap.querySelectorAll?.('button') || []) {
        btn.setAttribute('aria-expanded', expanded);
      }
    }
  }

  function closePopovers(restoreTrigger = false) {
    const wasPermOpen = permPopover && !permPopover.hidden;
    const wasMembersOpen = membersPopover && !membersPopover.hidden;
    if (!wasPermOpen && !wasMembersOpen) return false;
    if (permPopover) permPopover.hidden = true;
    if (membersPopover) membersPopover.hidden = true;
    syncPopoverAria();
    if (restoreTrigger) {
      if (wasPermOpen) permButton?.focus?.();
      else if (wasMembersOpen) avatarsWrap?.querySelector?.('button')?.focus?.();
    }
    return true;
  }

  function getLockCredentials(nodeKeys = null) {
    const creds = {};
    const keys = nodeKeys || [...heldLocks.keys()];
    for (const key of keys) {
      const held = heldLocks.get(key);
      if (held && Number.isInteger(held.fencing_token)) creds[key] = held.fencing_token;
    }
    return creds;
  }

  function sendFrame(type, payload = {}, requestId = null) {
    if (!ws || ws.readyState !== 1) return false;
    const envelope = {
      type,
      event_id: `canvas_collab_evt_${crypto.randomUUID()}`,
      ...(requestId ? {request_id: requestId} : {}),
      ...(sessionId ? {session_id: sessionId} : {}),
      canvas_id: state.id,
      client_ts: Date.now(),
      payload,
    };
    ws.send(JSON.stringify(envelope));
    return true;
  }

  function paintBar() {
    if (!barEl || disposed || !isLive()) return;
    const perm = computePerm();
    const effectiveSync = !perm.canEdit ? 'readonly' : syncState;
    syncPill.dataset.state = effectiveSync;
    const prefix = effectiveSync === 'synced' ? '● '
      : effectiveSync === 'syncing' ? '↻ '
      : effectiveSync === 'readonly' ? '🔒 '
      : '● ';
    setText(syncPill, '');
    syncPill.append(makeEl('span', prefix, 'cc-collab-dot'), makeEl('span', syncLabelFor(effectiveSync)));
    if (effectiveSync === 'offline') bindAttribute(syncPill, 'title', clabel('offline_hint'));
    else if (effectiveSync === 'failed') bindAttribute(syncPill, 'title', clabel('retry_hint'));
    else syncPill.removeAttribute('title');

    conflictPill.hidden = conflicts.length === 0;
    if (conflicts.length > 0) {
      setText(conflictPill, `⇄ ${conflicts.length}`);
    }

    avatarsWrap.replaceChildren();
    const online = members.length ? members : [];
    const shown = online.slice(0, 3);
    for (const m of shown) {
      const badge = makeEl('button', (m.nickname || m.user_id || '?').slice(0, 1).toUpperCase(), 'cc-collab-avatar');
      badge.type = 'button';
      badge.style.borderColor = m.color || '#38bdf8';
      badge.title = m.nickname || m.user_id || '';
      badge.addEventListener('click', () => {
        membersPopover.hidden = !membersPopover.hidden;
        if (permPopover) permPopover.hidden = true;
        syncPopoverAria();
      });
      avatarsWrap.append(badge);
    }
    if (online.length > 3) {
      const extra = makeEl('button', `+${online.length - 3}`, 'cc-collab-avatar cc-collab-avatar-more');
      extra.type = 'button';
      extra.addEventListener('click', () => {
        membersPopover.hidden = !membersPopover.hidden;
        if (permPopover) permPopover.hidden = true;
        syncPopoverAria();
      });
      avatarsWrap.append(extra);
    }
    membersPopover.replaceChildren();
    membersPopover.append(makeEl('h4', clabel('collaborators_count', {count: online.length})));
    const memberList = makeEl('div', null, 'cc-collab-member-list');
    for (const m of online) {
      const row = makeEl('div', null, 'cc-collab-member-row');
      const dot = makeEl('span', (m.nickname || m.user_id || '?').slice(0, 1).toUpperCase(), 'cc-collab-avatar');
      dot.style.borderColor = m.color || '#38bdf8';
      const name = makeEl('span', m.nickname || m.user_id || '', 'cc-collab-member-name');
      const tags = makeEl('span', null, 'cc-collab-member-tags');
      if (m.session_id === sessionId || (!sessionId && m.user_id === ctx.session().actor)) {
        tags.append(makeEl('em', clabel('tag_me'), 'cc-collab-tag'));
      }
      if (m.is_owner) tags.append(makeEl('em', clabel('tag_owner'), 'cc-collab-tag'));
      tags.append(makeEl('em', clabel(m.mode === 'edit' ? 'tag_editing' : 'tag_viewing'), 'cc-collab-tag'));
      row.append(dot, name, tags);
      memberList.append(row);
    }
    membersPopover.append(memberList);
    if (!online.length) membersPopover.hidden = true;

    permWrap.hidden = !perm.showPermissionButton;
    if (!perm.showPermissionButton && permPopover) permPopover.hidden = true;
    if (permSwitch) {
      permSwitch.setAttribute('aria-checked', String(collabEnabled));
      permSwitch.disabled = !perm.canManage;
    }
    syncPopoverAria();
    if (permList) {
      permList.replaceChildren();
      for (const item of collaborators) {
        const row = makeEl('div', null, 'cc-collab-perm-row');
        const left = makeEl('span', item.display_name || item.nickname || item.actor || item.user_id || '', 'cc-collab-perm-name');
        const right = makeEl('span', null, 'cc-collab-member-tags');
        if (item.access_label) {
          right.append(makeEl('em', item.access_label, 'cc-collab-tag'));
        } else {
          if (item.is_owner) right.append(makeEl('em', clabel('tag_owner'), 'cc-collab-tag'));
          else if (item.is_studio_admin || item.role === 'owner' || item.role === 'admin') right.append(makeEl('em', clabel('tag_admin'), 'cc-collab-tag'));
          const itemEditable = item.is_owner || (collabEnabled && item.can_edit !== false && item.role !== 'viewer');
          right.append(makeEl('em', llabel(itemEditable ? 'permission_edit' : 'permission_view'), 'cc-collab-tag'));
        }
        row.append(left, right);
        permList.append(row);
      }
    }
  }

  function confirmDisableCollaboration(onConfirm) {
    const d = makeEl('dialog', null, 'cc-collab-confirm-dialog');
    bindAttribute(d, 'aria-label', llabel('collaboration_disable_title'));
    const head = makeEl('h3', llabel('collaboration_disable_title'));
    const body = makeEl('p', llabel('collaboration_disable_confirm'));
    const foot = makeEl('footer');
    const cancel = makeEl('button', msg('common.cancel'));
    cancel.type = 'button';
    cancel.addEventListener('click', () => d.close());
    const confirm = makeEl('button', msg('common.confirm'), 'cc-collab-danger-confirm');
    confirm.type = 'button';
    confirm.addEventListener('click', async () => {
      confirm.disabled = true;
      try {
        await onConfirm();
        d.close();
      } finally {
        confirm.disabled = false;
      }
    });
    foot.append(cancel, confirm);
    d.append(head, body, foot);
    d.addEventListener('close', () => d.remove(), {once: true});
    state.root.append(d);
    d.showModal();
    return d;
  }

  async function toggleCollaboration(targetEnabled) {
    const applyToggle = async () => {
      const res = await ctx.api(`${url()}/collaboration`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          payload: {collaboration_enabled: targetEnabled},
          expected_revision: state.revision,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!isLive() || disposed) return;
      if (Number.isInteger(res.revision)) {
        state.revision = res.revision;
        ctx.setRevision?.(res.revision, state.project);
      }
      collabEnabled = Boolean(res.collaboration_enabled);
      if (res.permission) permissionRaw = res.permission;
      if (Array.isArray(res.collaborators)) collaborators = res.collaborators;
      if (Array.isArray(res.members)) members = res.members;
      if (Number.isInteger(res.canvas_seq)) localSeq = res.canvas_seq;
      applyPermissionState(false);
      paintBar();
    };
    if (collabEnabled && !targetEnabled) {
      confirmDisableCollaboration(applyToggle);
      return;
    }
    await applyToggle();
  }

  function applyPermissionState(fromBroadcast = false) {
    const prevReadOnly = state.readOnly;
    const perm = computePerm();
    state.collaborationEnabled = collabEnabled;
    state.permission = permissionRaw;
    state.canManageCollaboration = perm.canManage;
    state.readOnly = !perm.canEdit;
    if (!perm.canEdit) {
      releaseAllHeldLocks();
      syncState = 'readonly';
    } else if (syncState === 'readonly') {
      syncState = 'synced';
    }
    onPermissionApplied?.(perm, {fromBroadcast, downgraded: !prevReadOnly && state.readOnly});
    if (fromBroadcast && !prevReadOnly && state.readOnly) {
      notice?.(clabel('downgraded_readonly'));
    }
    paintBar();
  }

  function mountBar(toolbar) {
    barEl = makeEl('div', null, 'canvas-collaboration-bar cc-collab-bar');
    barEl.dataset.testid = 'canvas-collaboration-bar';
    syncPill = makeEl('button', null, 'cc-collab-sync-pill');
    syncPill.type = 'button';
    syncPill.addEventListener('click', () => {
      if (syncState === 'failed' || syncState === 'offline') {
        flushRecoveryQueue().catch(err => notice?.(err.message));
        if (!ws || ws.readyState > 1) connectWs();
      }
    });

    conflictPill = makeEl('button', '', 'cc-collab-conflict-pill');
    conflictPill.type = 'button';
    conflictPill.hidden = true;
    conflictPill.addEventListener('click', () => openConflictDialog());

    const presenceWrap = makeEl('div', null, 'cc-collab-presence-wrap');
    avatarsWrap = makeEl('div', null, 'cc-collab-avatars');
    membersPopover = makeEl('section', null, 'cc-collab-members-popover');
    membersPopover.hidden = true;
    presenceWrap.append(avatarsWrap, membersPopover);

    permWrap = makeEl('div', null, 'cc-collab-perm-wrap');
    permButton = makeEl('button', clabel('permission_settings'), 'cc-collab-perm-btn');
    permButton.type = 'button';
    permButton.setAttribute('aria-haspopup', 'dialog');
    permButton.setAttribute('aria-expanded', 'false');
    permButton.addEventListener('click', () => {
      permPopover.hidden = !permPopover.hidden;
      if (membersPopover) membersPopover.hidden = true;
      syncPopoverAria();
    });
    permPopover = makeEl('section', null, 'canvas-collaboration-permission-popover cc-collab-perm-popover');
    permPopover.dataset.testid = 'canvas-collaboration-permission-popover';
    permPopover.hidden = true;
    const permHeader = makeEl('div', null, 'cc-collab-perm-head');
    permHeader.append(makeEl('strong', llabel('collaboration')));
    permSwitch = makeEl('button', '', 'cc-collab-switch');
    permSwitch.type = 'button';
    permSwitch.setAttribute('role', 'switch');
    bindAttribute(permSwitch, 'aria-label', llabel('collaboration'));
    permSwitch.addEventListener('click', () => {
      toggleCollaboration(!collabEnabled).catch(err => notice?.(err.message));
    });
    permHeader.append(permSwitch);
    permList = makeEl('div', null, 'cc-collab-perm-list');
    const banner = makeEl('p', clabel('permission_banner'), 'cc-collab-perm-banner');
    permPopover.append(permHeader, permList, banner);
    permWrap.append(permButton, permPopover);

    barEl.append(syncPill, conflictPill, presenceWrap, permWrap);
    const agentBtn = toolbar.querySelector('.cc-agent-toggle');
    if (agentBtn) toolbar.insertBefore(barEl, agentBtn);
    else toolbar.append(barEl);
    paintBar();
  }

  function paintCursors() {
    if (!overlayEl || !isLive() || disposed) return;
    const now = Date.now();
    overlayEl.replaceChildren();
    const ox = state.displayOffset?.x || 0;
    const oy = state.displayOffset?.y || 0;
    for (const [sid, cur] of [...remoteCursors.entries()]) {
      if (now - cur.updatedAt > COLLAB_CURSOR_TTL_MS) {
        remoteCursors.delete(sid);
        continue;
      }
      const marker = makeEl('div', null, 'cc-remote-cursor');
      marker.style.left = `${cur.x + ox}px`;
      marker.style.top = `${cur.y + oy}px`;
      marker.style.setProperty('--collab-color', cur.color || '#38bdf8');
      const arrow = makeEl('span', '➤', 'cc-remote-cursor-arrow');
      const tag = makeEl('span', cur.nickname || cur.user_id || '', 'cc-remote-cursor-name');
      marker.append(arrow, tag);
      overlayEl.append(marker);
    }
  }

  function decorateWorld(worldEl, nodes) {
    overlayEl = makeEl('div', null, 'cc-collab-overlay');
    worldEl.append(overlayEl);
    const now = Date.now();
    const ox = state.displayOffset?.x || 0;
    const oy = state.displayOffset?.y || 0;
    for (const [nodeKey, preview] of [...remotePreviews.entries()]) {
      if (now - preview.updatedAt > COLLAB_PREVIEW_TTL_MS) {
        remotePreviews.delete(nodeKey);
        continue;
      }
      const card = worldEl.querySelector(`[data-node-id="${nodeKey}"]`);
      if (card) {
        card.style.left = `${preview.x + ox}px`;
        card.style.top = `${preview.y + oy}px`;
      }
    }
    for (const node of nodes || []) {
      const lock = isNodeLockedByOther(node.id);
      if (!lock) continue;
      const card = worldEl.querySelector(`[data-node-id="${node.id}"]`);
      if (!card) continue;
      card.classList.add('cc-node-locked-remote');
      card.style.borderColor = lock.color || '#f97316';
      card.style.outlineColor = lock.color || '#f97316';
      const badge = makeEl('span', `🔒 ${lock.owner_name || lock.owner_user_id || ''}`, 'cc-node-lock-badge');
      badge.style.background = lock.color || '#f97316';
      card.append(badge);
    }
    paintCursors();
  }

  async function requestNodeLocks(nodeKeys, intent = 'edit') {
    const sorted = sortLockKeys(nodeKeys);
    if (!sorted.length) return true;
    if (!computePerm().canEdit) return false;
    for (const key of sorted) {
      const other = isNodeLockedByOther(key);
      if (other) {
        notice?.(clabel('node_locked_by', {name: other.owner_name || other.owner_user_id || ''}));
        return false;
      }
    }
    if (!ws || ws.readyState !== 1) return true;
    const needAcquire = sorted.filter(k => !heldLocks.has(k));
    if (!needAcquire.length) return true;
    const reqId = `lock_${crypto.randomUUID()}`;
    return new Promise(resolve => {
      const timer = setTimeout(() => {
        pendingLockWaiters.delete(reqId);
        resolve(false);
      }, COLLAB_LOCK_TIMEOUT_MS);
      pendingLockWaiters.set(reqId, ok => {
        clearTimeout(timer);
        pendingLockWaiters.delete(reqId);
        resolve(ok);
      });
      sendFrame('node.lock.acquire', {node_keys: needAcquire, intent}, reqId);
    });
  }

  function releaseNodeLocks(nodeKeys) {
    const sorted = sortLockKeys(nodeKeys);
    const locks = [];
    for (const key of sorted) {
      const held = heldLocks.get(key);
      if (held) {
        locks.push({node_key: key, fencing_token: held.fencing_token});
        heldLocks.delete(key);
        const existing = remoteLocks.get(key);
        if (existing && (!sessionId || existing.session_id === sessionId)) remoteLocks.delete(key);
      }
    }
    if (locks.length) sendFrame('node.lock.release', {locks});
  }

  function releaseAllHeldLocks() {
    if (!heldLocks.size) return;
    releaseNodeLocks([...heldLocks.keys()]);
  }

  function reportCursorMove(worldPoint) {
    if (!ws || ws.readyState !== 1 || !worldPoint) return;
    const now = Date.now();
    if (now - lastCursorSentAt < 60) return;
    lastCursorSentAt = now;
    sendFrame('cursor.move', {
      x: worldPoint.x,
      y: worldPoint.y,
      viewport_zoom: state.document?.viewport?.zoom || 1,
    });
  }

  function reportTransientNodeMove(updates) {
    if (!ws || ws.readyState !== 1 || !Array.isArray(updates) || !updates.length) return;
    if ((ws.bufferedAmount || 0) > COLLAB_BUFFER_CAP_BYTES) {
      adaptiveIntervalMs = Math.min(500, adaptiveIntervalMs * 2);
      return;
    }
    adaptiveIntervalMs = Math.max(50, Math.floor(adaptiveIntervalMs * 0.9));
    const enriched = updates.map(u => ({
      ...u,
      ...(heldLocks.get(u.node_key)?.fencing_token ? {fencing_token: heldLocks.get(u.node_key).fencing_token} : {}),
    }));
    const now = Date.now();
    const waitMs = adaptiveIntervalMs - (now - lastPreviewSentAt);
    if (waitMs <= 0) {
      lastPreviewSentAt = now;
      queuedPreviewNodes = null;
      sendFrame('node.state.update', {updates: enriched});
      return;
    }
    queuedPreviewNodes = enriched;
    if (!previewTimer) {
      previewTimer = setTimeout(() => {
        previewTimer = null;
        if (queuedPreviewNodes && ws?.readyState === 1 && (ws.bufferedAmount || 0) <= COLLAB_BUFFER_CAP_BYTES) {
          lastPreviewSentAt = Date.now();
          sendFrame('node.state.update', {updates: queuedPreviewNodes});
          queuedPreviewNodes = null;
        }
      }, Math.min(500, Math.max(50, waitMs)));
    }
  }

  async function queueLocalRecovery(operations, baseVersion, title, documentSnapshot) {
    const clientOpId = `op_${crypto.randomUUID()}`;
    await recoveryStore.putRecord({
      canvas_id: state.id,
      client_op_id: clientOpId,
      project_id: state.project,
      episode_id: state.episode || null,
      base_version: baseVersion,
      base_seq: localSeq,
      title,
      operations,
      created_at: Date.now(),
    });
    await recoveryStore.saveSnapshot(state.id, {
      version: baseVersion,
      title,
      document: documentSnapshot,
    });
    return clientOpId;
  }

  async function ensureDraftQueued(baseVersion, title, documentSnapshot) {
    const existing = await recoveryStore.listRecords(state.id);
    if (existing.length) return existing[0].client_op_id;
    return queueLocalRecovery(
      [{op: 'replace_document', title: title ?? state.title, document: documentSnapshot ?? state.document}],
      baseVersion ?? state.version,
      title ?? state.title,
      documentSnapshot ?? state.document,
    );
  }

  async function submitRealtimeOps(operations, {clientOpId = null, title = null, documentSnapshot = null} = {}) {
    const opId = clientOpId || await queueLocalRecovery(operations, state.version, title || state.title, documentSnapshot || state.document);
    if (!ws || ws.readyState !== 1) {
      setSyncState('offline');
      return {queued: true, clientOpId: opId};
    }
    setSyncState('syncing');
    sendFrame('canvas.ops.submit', {
      base_version: state.version,
      base_seq: localSeq,
      client_op_id: opId,
      lock_credentials: getLockCredentials(),
      ops: operations,
    }, opId);
    return {sent: true, clientOpId: opId};
  }

  async function flushRecoveryQueue({forceOverwrite = false} = {}) {
    if (disposed || !isLive() || !computePerm().canEdit) return false;
    const records = await recoveryStore.listRecords(state.id);
    if (!records.length && !forceOverwrite) return true;
    const snapshot = await recoveryStore.getSnapshot(state.id);
    const baseVersion = records[0]?.base_version || snapshot?.version || state.version;
    const operations = records.length
      ? records.flatMap(r => r.operations || [])
      : [{op: 'replace_document', title: state.title, document: state.document}];
    const payloadBody = {
      protocol_version: 1,
      canvas_id: state.id,
      project_id: state.project,
      episode_id: state.episode || null,
      base_version: baseVersion,
      operations,
      title: state.title,
      document: state.document,
      lock_credentials: getLockCredentials(),
      force_overwrite: Boolean(forceOverwrite),
    };
    const sendBatch = expectedRevision => ctx.api(`${url()}/recovery/batch`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        payload: payloadBody,
        expected_revision: expectedRevision,
        idempotency_key: crypto.randomUUID(),
      }),
    });
    setSyncState('syncing');
    try {
      let res;
      try {
        res = await sendBatch(state.revision);
      } catch (firstErr) {
        const errCode = firstErr?.error_code ?? firstErr?.details?.error_code ?? firstErr?.business_code;
        if (firstErr?.status === 409 && firstErr?.code === 'revision_conflict' && errCode !== 11103) {
          const latestMeta = await ctx.api(url());
          if (!isLive() || disposed) return false;
          if (Number.isInteger(latestMeta?.revision)) {
            state.revision = latestMeta.revision;
            ctx.setRevision?.(latestMeta.revision, state.project);
          }
          res = await sendBatch(state.revision);
        } else {
          throw firstErr;
        }
      }
      if (!isLive() || disposed) return false;
      if (Number.isInteger(res.revision)) {
        state.revision = res.revision;
        ctx.setRevision?.(res.revision, state.project);
      }
      if (Number.isInteger(res.canvas_seq)) localSeq = res.canvas_seq;
      await recoveryStore.clearCanvas(state.id);
      conflicts = [];
      closeConflictDialog();
      setSyncState('synced');
      if (res.document) {
        onRemoteDocument?.({
          document: res.document,
          title: res.title || state.title,
          version: res.version || res.canvas_revision || state.version,
          canvasSeq: localSeq,
          revision: res.revision,
          clearLocalDraft: true,
        });
      }
      return true;
    } catch (err) {
      const errCode = err?.error_code ?? err?.details?.error_code ?? err?.business_code;
      const rawConflicts = err?.conflicts ?? err?.details?.conflicts;
      const rawLocks = err?.locks ?? err?.details?.locks;
      if (Array.isArray(rawLocks)) reconcileAuthoritativeLocks(rawLocks);
      if (errCode === 11103 || err?.code === 'canvas_conflict' || err?.code === 'canvas_recovery_conflict' || Array.isArray(rawConflicts)) {
        conflicts = Array.isArray(rawConflicts) && rawConflicts.length
          ? rawConflicts.map(normalizeConflictItem)
          : [normalizeConflictItem({node_id: '__canvas__', node_title: state.title, local_summary: state.title, remote_summary: `v${err.version || err?.details?.version || state.version}`})];
        setSyncState('failed');
        openConflictDialog(err);
        return false;
      }
      setSyncState('failed');
      throw err;
    }
  }

  function closeConflictDialog() {
    if (conflictDialog) {
      const d = conflictDialog;
      conflictDialog = null;
      if (d.open) d.close();
      d.remove();
    }
    paintBar();
  }

  function openConflictDialog(meta = {}) {
    if (!conflicts.length || !isLive() || disposed) return;
    conflicts = conflicts.map(normalizeConflictItem);
    if (conflictDialog?.isConnected) conflictDialog.remove();
    const d = makeEl('dialog', null, 'canvas-conflict-dialog cc-conflict-dialog');
    d.dataset.testid = 'canvas-conflict-dialog';
    bindAttribute(d, 'aria-label', clabel('conflict_title'));
    d.addEventListener('cancel', event => {
      if (conflicts.length > 0) event.preventDefault();
    });
    d.addEventListener('click', event => {
      if (event.target === d && conflicts.length > 0) event.stopPropagation?.();
    });

    const head = makeEl('header', null, 'cc-conflict-head');
    head.append(makeEl('h2', clabel('conflict_title')));
    const list = makeEl('div', null, 'cc-conflict-list');
    let anyLockedByOther = false;
    for (const item of conflicts) {
      const nodeKey = item.node_id ?? item.node_key;
      const nodeTitle = item.node_title ?? item.title ?? state.title;
      const lockCandidate = item.locked_by || isNodeLockedByOther(nodeKey);
      const lock = lockCandidate && !isLockOwnedBySelf(lockCandidate) ? lockCandidate : null;
      if (lock) {
        anyLockedByOther = true;
      }
      const card = makeEl('article', null, 'cc-conflict-item');
      const itemHead = makeEl('div', null, 'cc-conflict-item-head');
      itemHead.append(makeEl('strong', nodeTitle));
      if (lock) {
        const lockNote = makeEl('span', clabel('node_locked_by', {name: lock.owner_name || lock.owner_actor || lock.owner_user_id || ''}), 'cc-conflict-lock-tag');
        itemHead.append(lockNote);
      }
      const copyBtn = makeEl('button', clabel('copy_local'), 'cc-conflict-copy');
      copyBtn.type = 'button';
      copyBtn.addEventListener('click', async () => {
        let draftText;
        if (nodeKey === '__canvas_title__') {
          draftText = item.local_draft?.title || state.title;
        } else {
          const localNode = state.document?.nodes?.find(n => n.id === nodeKey) || item.local_draft;
          draftText = localNode
            ? (typeof localNode.text === 'string' && localNode.text.length ? localNode.text : JSON.stringify(localNode))
            : (item.local_summary || JSON.stringify(state.document));
        }
        await copyTextToClipboard(draftText);
        notice?.(clabel('copied_local'));
      });
      itemHead.append(copyBtn);

      const cols = makeEl('div', null, 'cc-conflict-columns');
      const localBox = makeEl('div', null, 'cc-conflict-col');
      localBox.append(makeEl('small', clabel('conflict_local')), makeEl('p', item.local_summary || ''));
      const remoteBox = makeEl('div', null, 'cc-conflict-col');
      remoteBox.append(makeEl('small', clabel('conflict_remote')), makeEl('p', item.remote_summary || ''));
      cols.append(localBox, remoteBox);
      card.append(itemHead, cols);
      list.append(card);
    }

    const foot = makeEl('footer', null, 'cc-conflict-footer');
    const refreshBtn = makeEl('button', clabel('refresh_remote'));
    refreshBtn.type = 'button';
    refreshBtn.addEventListener('click', async () => {
      const latest = await ctx.api(url());
      if (!isLive() || disposed) return;
      if (Number.isInteger(latest?.revision)) {
        state.revision = latest.revision;
        ctx.setRevision?.(latest.revision, state.project);
      }
      if (Array.isArray(latest.locks)) reconcileAuthoritativeLocks(latest.locks);
      for (const item of conflicts) {
        const nodeKey = item.node_id ?? item.node_key;
        if (nodeKey === '__canvas_title__' && typeof latest.title === 'string') {
          item.remote_summary = latest.title;
        } else {
          const remoteNode = latest.document?.nodes?.find(n => n.id === nodeKey);
          if (remoteNode) item.remote_summary = `${remoteNode.type} · ${remoteNode.title} (${remoteNode.x}, ${remoteNode.y})`;
        }
        item.locked_by = isNodeLockedByOther(nodeKey);
      }
      openConflictDialog(meta);
    });

    const discardBtn = makeEl('button', clabel('discard_all'));
    discardBtn.type = 'button';
    discardBtn.addEventListener('click', async () => {
      discardBtn.disabled = true;
      try {
        const latest = await ctx.api(url());
        if (!isLive() || disposed) return;
        await recoveryStore.clearCanvas(state.id);
        conflicts = [];
        closeConflictDialog();
        localSeq = Number(latest.canvas_seq || localSeq);
        setSyncState('synced');
        onRemoteDocument?.({
          document: latest.document,
          title: latest.title,
          version: latest.canvas_revision,
          canvasSeq: localSeq,
          revision: latest.revision,
          clearLocalDraft: true,
        });
      } finally {
        discardBtn.disabled = false;
      }
    });

    const overwriteBtn = makeEl('button', clabel('overwrite_all'), 'cc-conflict-overwrite');
    overwriteBtn.type = 'button';
    overwriteBtn.disabled = anyLockedByOther || !computePerm().canEdit;
    overwriteBtn.addEventListener('click', async () => {
      overwriteBtn.disabled = true;
      try {
        await flushRecoveryQueue({forceOverwrite: true});
      } catch (err) {
        notice?.(err.message);
      } finally {
        if (conflictDialog?.isConnected) overwriteBtn.disabled = anyLockedByOther || !computePerm().canEdit;
      }
    });

    foot.append(refreshBtn, discardBtn, overwriteBtn);
    d.append(head, list, foot);
    conflictDialog = d;
    state.root.append(d);
    d.showModal();
    paintBar();
    return d;
  }

  function openKickedDialog() {
    kicked = true;
    clearTimeout(reconnectTimer);
    if (kickedDialog?.isConnected) return kickedDialog;
    const d = makeEl('dialog', null, 'canvas-session-kicked-dialog cc-kicked-dialog');
    d.dataset.testid = 'canvas-session-kicked-dialog';
    bindAttribute(d, 'aria-label', clabel('kicked_title'));
    d.addEventListener('cancel', e => e.preventDefault());
    const head = makeEl('h2', clabel('kicked_title'));
    const body = makeEl('p', clabel('kicked_message'));
    const foot = makeEl('footer');
    const backBtn = makeEl('button', clabel('back_to_list'));
    backBtn.type = 'button';
    backBtn.addEventListener('click', () => {
      kickedDialog = null;
      d.close();
      d.remove();
      onBackToList?.();
    });
    const reconnectBtn = makeEl('button', clabel('reconnect_here'), 'cc-kicked-reconnect');
    reconnectBtn.type = 'button';
    reconnectBtn.addEventListener('click', () => {
      kicked = false;
      reconnectAttempt = 0;
      kickedDialog = null;
      d.close();
      d.remove();
      connectWs();
    });
    foot.append(backBtn, reconnectBtn);
    d.append(head, body, foot);
    kickedDialog = d;
    state.root.append(d);
    d.showModal();
    return d;
  }

  function handleInboundFrame(frame) {
    if (disposed || !isLive() || !frame || typeof frame.type !== 'string') return;
    const type = frame.type;
    const payload = frame.payload || {};
    if (type === 'ping') {
      sendFrame('pong', {server_ts: payload.server_ts});
      return;
    }
    if (type === 'session.ready') {
      sessionId = payload.session_id || frame.session_id || sessionId;
      return;
    }
    if (type === 'canvas.sync.snapshot') {
      if (Number.isInteger(payload.canvas_seq)) localSeq = payload.canvas_seq;
      if (payload.permission) {
        permissionRaw = payload.permission;
        if (typeof payload.permission.collaboration_enabled === 'boolean') {
          collabEnabled = payload.permission.collaboration_enabled;
        }
      }
      if (Array.isArray(payload.members)) members = payload.members;
      if (Array.isArray(payload.locks)) {
        remoteLocks.clear();
        for (const l of payload.locks) remoteLocks.set(l.node_key, l);
      }
      applyPermissionState(false);
      if (payload.canvas_patch?.document && !state.dirty && !state.pending) {
        onRemoteDocument?.({
          document: payload.canvas_patch.document,
          title: payload.canvas_patch.title || state.title,
          version: payload.canvas_patch.version || state.version,
          canvasSeq: localSeq,
        });
      } else {
        onRedrawWorld?.();
      }
      flushRecoveryQueue().catch(() => {});
      return;
    }
    if (type === 'canvas.sync.required') {
      ctx.api(url()).then(latest => {
        if (!isLive() || disposed) return;
        localSeq = Number(latest.canvas_seq || localSeq);
        if (!state.dirty && !state.pending) {
          onRemoteDocument?.({
            document: latest.document,
            title: latest.title,
            version: latest.canvas_revision,
            canvasSeq: localSeq,
            revision: latest.revision,
          });
        }
      }).catch(() => {});
      return;
    }
    if (type === 'members.snapshot') {
      members = Array.isArray(payload.members) ? payload.members : [];
      if (Array.isArray(payload.locks)) {
        reconcileAuthoritativeLocks(payload.locks);
        onRedrawWorld?.();
      }
      paintBar();
      return;
    }
    if (type === 'member.joined') {
      const m = payload.member;
      if (m?.session_id) {
        members = [...members.filter(x => x.session_id !== m.session_id), m];
        paintBar();
      }
      return;
    }
    if (type === 'member.left') {
      const leftSid = payload.session_id;
      if (leftSid) {
        members = members.filter(x => x.session_id !== leftSid);
        remoteCursors.delete(leftSid);
        for (const [nk, prev] of [...remotePreviews.entries()]) {
          if (prev.session_id === leftSid) remotePreviews.delete(nk);
        }
        paintBar();
        onRedrawWorld?.();
      }
      return;
    }
    if (type === 'cursor.moved') {
      if (payload.session_id && payload.session_id !== sessionId) {
        remoteCursors.set(payload.session_id, {
          ...payload,
          updatedAt: Date.now(),
        });
        paintCursors();
      }
      return;
    }
    if (type === 'node.locked') {
      const locks = Array.isArray(payload.locks) ? payload.locks : [];
      for (const l of locks) {
        remoteLocks.set(l.node_key, l);
        if (sessionId && l.session_id === sessionId) {
          heldLocks.set(l.node_key, {fencing_token: l.fencing_token, expires_at: l.expires_at});
        }
      }
      if (frame.request_id && pendingLockWaiters.has(frame.request_id)) {
        pendingLockWaiters.get(frame.request_id)(true);
      }
      onRedrawWorld?.();
      return;
    }
    if (type === 'node.lock.rejected') {
      if (frame.request_id && pendingLockWaiters.has(frame.request_id)) {
        pendingLockWaiters.get(frame.request_id)(false);
      }
      if (Array.isArray(payload.node_keys) && ['lease_expired', 'readonly', 'session_inactive', 'access_denied'].includes(payload.reason)) {
        for (const key of payload.node_keys) {
          heldLocks.delete(key);
          const cur = remoteLocks.get(key);
          if (cur && isLockOwnedBySelf(cur)) remoteLocks.delete(key);
        }
      }
      const holder = payload.conflicts?.[0]?.locked_by || payload.conflicts?.[0];
      if (holder?.node_key) {
        remoteLocks.set(holder.node_key, holder);
        notice?.(clabel('node_locked_by', {name: holder.owner_name || holder.owner_actor || holder.owner_user_id || ''}));
      }
      onRedrawWorld?.();
      return;
    }
    if (type === 'node.unlocked') {
      for (const item of payload.unlocked || []) {
        if (!item?.node_key) continue;
        const cur = remoteLocks.get(item.node_key);
        if (!cur || !Number.isInteger(item.fencing_token) || item.fencing_token === 0 || item.fencing_token >= (cur.fencing_token || 0)) {
          remoteLocks.delete(item.node_key);
          heldLocks.delete(item.node_key);
        }
      }
      if (!payload.unlocked?.length && Array.isArray(payload.node_keys)) {
        for (const key of payload.node_keys) {
          const cur = remoteLocks.get(key);
          if (!cur || !Number.isInteger(payload.fencing_token) || payload.fencing_token === 0 || payload.fencing_token >= (cur.fencing_token || 0)) {
            remoteLocks.delete(key);
            heldLocks.delete(key);
          }
        }
      }
      if (Array.isArray(payload.locks) && (Array.isArray(payload.unlocked) || Array.isArray(payload.node_keys))) {
        reconcileAuthoritativeLocks(payload.locks);
      }
      onRedrawWorld?.();
      return;
    }
    if (type === 'node.state.updated') {
      if (payload.session_id && payload.session_id !== sessionId) {
        for (const u of payload.updates || []) {
          remotePreviews.set(u.node_key, {
            ...u,
            session_id: payload.session_id,
            updatedAt: Date.now(),
          });
        }
        onRedrawWorld?.();
      }
      return;
    }
    if (type === 'node.state.rejected') {
      onRedrawWorld?.();
      return;
    }
    if (type === 'canvas.ops.ack' || type === 'canvas.batch.confirmed') {
      if (Number.isInteger(payload.canvas_seq)) localSeq = payload.canvas_seq;
      if (Number.isInteger(payload.version)) state.version = payload.version;
      if (Number.isInteger(payload.revision)) {
        state.revision = payload.revision;
        ctx.setRevision?.(payload.revision, state.project);
      }
      if (payload.client_op_id) recoveryStore.deleteRecords(state.id, [payload.client_op_id]).catch(() => {});
      setSyncState('synced');
      return;
    }
    if (type === 'canvas.ops.applied') {
      const seq = Number(payload.canvas_seq || 0);
      if (seq > localSeq + 1) {
        sendFrame('canvas.sync.request', {client_last_seq: localSeq});
        return;
      }
      if (seq > localSeq) localSeq = seq;
      if (Number.isInteger(payload.revision)) {
        state.revision = payload.revision;
        ctx.setRevision?.(payload.revision, state.project);
      }
      if (payload.session_id && payload.session_id === sessionId) return;
      if (payload.document && !state.dirty && !state.pending) {
        onRemoteDocument?.({
          document: payload.document,
          title: payload.title || state.title,
          version: payload.version || state.version,
          canvasSeq: localSeq,
          revision: payload.revision,
        });
      }
      return;
    }
    if (type === 'canvas.ops.rejected' || type === 'canvas.batch.rejected') {
      const errCode = payload.error_code ?? payload.business_code;
      if (Array.isArray(payload.locks)) reconcileAuthoritativeLocks(payload.locks);
      if (errCode === 11103 || payload.reason === 'version_conflict' || Array.isArray(payload.conflicts)) {
        conflicts = payload.conflicts?.length
          ? payload.conflicts.map(normalizeConflictItem)
          : [normalizeConflictItem({node_id: '__canvas__', node_title: state.title, local_summary: state.title, remote_summary: `v${payload.version || state.version}`})];
        setSyncState('failed');
        openConflictDialog(payload);
      } else {
        setSyncState('failed');
        if (payload.message) notice?.(payload.message);
      }
      return;
    }
    if (type === 'permission.changed') {
      if (typeof payload.collaboration_enabled === 'boolean') collabEnabled = payload.collaboration_enabled;
      if (payload.permission) permissionRaw = payload.permission;
      if (Number.isInteger(payload.canvas_seq)) localSeq = payload.canvas_seq;
      applyPermissionState(true);
      return;
    }
    if (type === 'session.kicked') {
      openKickedDialog();
      return;
    }
    if (type === 'node.run.updated') {
      onJobUpdated?.(payload);
    }
  }

  function scheduleReconnect() {
    if (disposed || kicked || !isLive()) return;
    clearTimeout(reconnectTimer);
    const delay = COLLAB_BACKOFF_MS[Math.min(reconnectAttempt, COLLAB_BACKOFF_MS.length - 1)];
    reconnectAttempt += 1;
    setSyncState('reconnecting');
    reconnectTimer = setTimeout(() => {
      if (!disposed && !kicked && isLive()) connectWs();
    }, delay);
  }

  async function connectWs() {
    if (disposed || kicked || !isLive() || state.shared || !permissionRaw || typeof WebSocket !== 'function') return;
    clearTimeout(reconnectTimer);
    try {
      const perm = computePerm();
      const mode = perm.canEdit ? 'edit' : 'presence';
      const ticketRes = await ctx.api(`${url()}/collab/ticket`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          payload: {mode, page_session_id: pageSessionId, episode_id: state.episode || null},
        }),
      });
      if (disposed || kicked || !isLive() || !ticketRes?.ticket) return;
      const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = (typeof location !== 'undefined' && location.host) || '127.0.0.1:8765';
      const q = new URLSearchParams({
        project_id: state.project,
        canvas_id: state.id,
        mode: ticketRes.mode || mode,
        sync_protocol: '2',
        ticket: ticketRes.ticket,
        client_last_seq: String(localSeq),
        language: 'zh-CN',
      });
      if (state.episode) q.set('episode_id', state.episode);
      const socket = new WebSocket(`${proto}//${host}${url()}/collab/ws?${q}`);
      ws = socket;
      socket.addEventListener('open', () => {
        if (ws !== socket || disposed) return;
        reconnectAttempt = 0;
        setSyncState('synced');
      });
      socket.addEventListener('message', event => {
        if (ws !== socket || disposed) return;
        try {
          handleInboundFrame(JSON.parse(event.data));
        } catch {}
      });
      socket.addEventListener('close', event => {
        if (ws !== socket || disposed) return;
        ws = null;
        if (event?.code === 4009) {
          openKickedDialog();
          return;
        }
        scheduleReconnect();
      });
      socket.addEventListener('error', () => {
        if (ws !== socket || disposed) return;
        setSyncState('offline');
      });
    } catch {
      if (!disposed && !kicked && isLive()) scheduleReconnect();
    }
  }

  function onVisibilityOrFocus() {
    if (disposed || !isLive()) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      lastHiddenAt = Date.now();
      return;
    }
    if (lastHiddenAt && Date.now() - lastHiddenAt >= COLLAB_FOCUS_RESYNC_MS) {
      lastHiddenAt = 0;
      if (!ws || ws.readyState !== 1) connectWs();
      else sendFrame('canvas.sync.request', {client_last_seq: localSeq});
    }
  }

  function onDocumentKeyDown(event) {
    if (event?.key === 'Escape' && closePopovers(true)) {
      event.stopPropagation?.();
    }
  }

  function onDocumentPointerDown(event) {
    if (!barEl || !event?.target) return;
    if (!barEl.contains?.(event.target) && !event.target.closest?.('.canvas-collaboration-bar')) {
      closePopovers(false);
    }
  }

  function start() {
    applyPermissionState(false);
    if (!permissionRaw || state.shared) return;
    renewTimer = setInterval(() => {
      if (disposed || !ws || ws.readyState !== 1 || !heldLocks.size) return;
      const locks = [...heldLocks.entries()].map(([node_key, v]) => ({node_key, fencing_token: v.fencing_token}));
      sendFrame('node.lock.renew', {locks});
    }, COLLAB_LOCK_RENEW_MS);
    renewTimer?.unref?.();
    cursorCleanupTimer = setInterval(() => {
      if (disposed) return;
      const now = Date.now();
      let dirtyWorld = false;
      for (const [sid, cur] of [...remoteCursors.entries()]) {
        if (now - cur.updatedAt > COLLAB_CURSOR_TTL_MS) {
          remoteCursors.delete(sid);
          paintCursors();
        }
      }
      for (const [nk, prev] of [...remotePreviews.entries()]) {
        if (now - prev.updatedAt > COLLAB_PREVIEW_TTL_MS) {
          remotePreviews.delete(nk);
          dirtyWorld = true;
        }
      }
      if (dirtyWorld) onRedrawWorld?.();
    }, 400);
    cursorCleanupTimer?.unref?.();
    if (typeof window !== 'undefined') {
      window.addEventListener('focus', onVisibilityOrFocus);
      window.addEventListener('visibilitychange', onVisibilityOrFocus);
      window.addEventListener('keydown', onDocumentKeyDown);
      window.addEventListener('pointerdown', onDocumentPointerDown);
    }
    recoveryStore.listRecords(state.id).then(rows => {
      if (rows?.length && computePerm().canEdit) flushRecoveryQueue().catch(() => {});
    }).catch(() => {});
    connectWs();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    clearTimeout(reconnectTimer);
    clearTimeout(previewTimer);
    clearInterval(renewTimer);
    clearInterval(cursorCleanupTimer);
    if (typeof window !== 'undefined') {
      window.removeEventListener('focus', onVisibilityOrFocus);
      window.removeEventListener('visibilitychange', onVisibilityOrFocus);
      window.removeEventListener('keydown', onDocumentKeyDown);
      window.removeEventListener('pointerdown', onDocumentPointerDown);
    }
    releaseAllHeldLocks();
    if (ws) {
      try { ws.close(1000, 'dispose'); } catch {}
      ws = null;
    }
    recoveryStore.dispose();
  }

  return {
    mountBar,
    start,
    dispose,
    decorateWorld,
    computePerm,
    isNodeLockedByOther,
    getLockCredentials,
    requestNodeLocks,
    releaseNodeLocks,
    releaseAllHeldLocks,
    reportCursorMove,
    reportTransientNodeMove,
    ensureDraftQueued,
    queueLocalRecovery,
    submitRealtimeOps,
    flushRecoveryQueue,
    setSyncState,
    notifySaved(nextSeq) {
      if (Number.isInteger(nextSeq)) localSeq = nextSeq;
      recoveryStore.clearCanvas(state.id).catch(() => {});
      setSyncState('synced');
    },
    notifySavePending() {
      setSyncState(ws && ws.readyState === 1 ? 'syncing' : (permissionRaw && typeof WebSocket === 'function' ? 'offline' : 'syncing'));
    },
    notifySaveError() {
      setSyncState('failed');
    },
    handleInboundFrame,
    openConflictDialog,
    openKickedDialog,
    get pageSessionId() { return pageSessionId; },
    get conflicts() { return conflicts; },
  };
}
