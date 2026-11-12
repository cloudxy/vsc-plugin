const BATCH_ENTITY_LIMIT = 256;
const SLICE_BUDGET_MS = 4;

const nowMs = () => (typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now());
const yieldSlice = () => new Promise(resolve => setTimeout(resolve, 0));

export async function buildCanvasEntitySnapshot(canvasId, title, version, document, ledger = [], onSliceYield = null) {
  const entities = Object.create(null);
  const cid = String(canvasId || 'draft');
  const doc = document && typeof document === 'object' ? document : { viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [] };
  entities[`canvas:${cid}`] = JSON.stringify({
    title: String(title || ''),
    version: Number(version || 0),
    viewport: doc.viewport || { x: 0, y: 0, zoom: 1 },
    nodeCount: Array.isArray(doc.nodes) ? doc.nodes.length : 0,
    edgeCount: Array.isArray(doc.edges) ? doc.edges.length : 0,
  });

  let processed = 1;
  let sliceStart = nowMs();
  const maybeYield = async () => {
    if (processed >= BATCH_ENTITY_LIMIT || nowMs() - sliceStart >= SLICE_BUDGET_MS) {
      processed = 0;
      if (typeof onSliceYield === 'function') onSliceYield();
      await yieldSlice();
      sliceStart = nowMs();
    }
  };

  for (const node of Array.isArray(doc.nodes) ? doc.nodes : []) {
    if (!node || !node.id) continue;
    entities[`node:${node.id}`] = JSON.stringify(node);
    processed += 1;
    await maybeYield();
  }
  for (const edge of Array.isArray(doc.edges) ? doc.edges : []) {
    if (!edge || !edge.id) continue;
    entities[`edge:${edge.id}`] = JSON.stringify(edge);
    processed += 1;
    await maybeYield();
  }
  for (const entry of Array.isArray(ledger) ? ledger : []) {
    if (!entry) continue;
    const lid = String(entry.id || entry.op_id || entry.request_id || processed);
    entities[`ledger:${lid}`] = JSON.stringify(entry);
    processed += 1;
    await maybeYield();
  }
  return entities;
}

export async function diffCanvasEntitySnapshots(previous = {}, next = {}) {
  const changed = [];
  const removed = [];
  let processed = 0;
  let sliceStart = nowMs();
  const keys = new Set([...Object.keys(previous || {}), ...Object.keys(next || {})]);
  for (const key of keys) {
    if (!(key in next)) removed.push(key);
    else if (previous[key] !== next[key]) changed.push([key, next[key]]);
    processed += 1;
    if (processed >= BATCH_ENTITY_LIMIT || nowMs() - sliceStart >= SLICE_BUDGET_MS) {
      processed = 0;
      await yieldSlice();
      sliceStart = nowMs();
    }
  }
  return { changed, removed, dirtyCount: changed.length + removed.length };
}

const isDedicatedWorkerScope =
  typeof self !== 'undefined' &&
  typeof window === 'undefined' &&
  typeof self.postMessage === 'function' &&
  typeof WorkerGlobalScope !== 'undefined' &&
  self instanceof WorkerGlobalScope;

if (isDedicatedWorkerScope) {
  const snapshots = new Map();
  self.onmessage = async event => {
    const msg = event?.data || {};
    const reqId = msg.requestId;
    const canvasId = String(msg.canvasId || 'default');
    try {
      if (msg.type === 'snapshot') {
        let yields = 0;
        const next = await buildCanvasEntitySnapshot(
          canvasId,
          msg.title,
          msg.version,
          msg.document,
          msg.ledger,
          () => { yields += 1; }
        );
        const prev = snapshots.get(canvasId) || {};
        const diff = await diffCanvasEntitySnapshots(prev, next);
        snapshots.set(canvasId, next);
        self.postMessage({
          requestId: reqId,
          ok: true,
          canvasId,
          yields,
          dirtyCount: diff.dirtyCount,
          changedKeys: diff.changed.map(([k]) => k),
          removedKeys: diff.removed,
          serialized: JSON.stringify({
            canvasId,
            title: msg.title,
            version: msg.version,
            updatedAtMs: Date.now(),
            entities: next,
          }),
        });
      } else if (msg.type === 'clear') {
        snapshots.delete(canvasId);
        self.postMessage({ requestId: reqId, ok: true, canvasId, dirtyCount: 0 });
      }
    } catch (error) {
      self.postMessage({ requestId: reqId, ok: false, canvasId, error: String(error?.message || error) });
    }
  };
}

export function createCanvasPersistenceClient({ onFlushBeforeLeave = null } = {}) {
  let worker = null;
  let seq = 0;
  let disposed = false;
  const pending = new Map();
  const localSnapshots = new Map();

  if (typeof Worker === 'function' && typeof window !== 'undefined') {
    try {
      worker = new Worker(new URL('./canvas-persistence-worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = event => {
        const payload = event?.data || {};
        const waiter = pending.get(payload.requestId);
        if (!waiter) return;
        pending.delete(payload.requestId);
        if (payload.ok) waiter.resolve(payload);
        else waiter.reject(new Error(payload.error || 'worker persistence error'));
      };
      worker.onerror = () => {
        for (const waiter of pending.values()) waiter.reject(new Error('worker unavailable'));
        pending.clear();
        try { worker.terminate(); } catch {}
        worker = null;
      };
    } catch {
      worker = null;
    }
  }

  const handleVisibility = () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden' && typeof onFlushBeforeLeave === 'function') {
      onFlushBeforeLeave('visibilitychange');
    }
  };
  const handlePageHide = () => {
    if (typeof onFlushBeforeLeave === 'function') onFlushBeforeLeave('pagehide');
  };
  const handleBeforeUnload = event => {
    if (typeof onFlushBeforeLeave !== 'function') return;
    const state = onFlushBeforeLeave('beforeunload');
    if (state && state.blockUnload) {
      event.preventDefault();
      event.returnValue = '';
    }
  };

  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener('beforeunload', handleBeforeUnload);
  }
  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('visibilitychange', handleVisibility);
  }

  return {
    async syncSnapshot({ canvasId, title, version, document, ledger = [] }) {
      if (disposed) return null;
      const cid = String(canvasId || 'default');
      if (worker) {
        const requestId = ++seq;
        return await new Promise((resolve, reject) => {
          pending.set(requestId, { resolve, reject });
          worker.postMessage({ type: 'snapshot', requestId, canvasId: cid, title, version, document, ledger });
        });
      }
      let yields = 0;
      const next = await buildCanvasEntitySnapshot(cid, title, version, document, ledger, () => { yields += 1; });
      const prev = localSnapshots.get(cid) || {};
      const diff = await diffCanvasEntitySnapshots(prev, next);
      localSnapshots.set(cid, next);
      return {
        ok: true,
        canvasId: cid,
        yields,
        dirtyCount: diff.dirtyCount,
        changedKeys: diff.changed.map(([k]) => k),
        removedKeys: diff.removed,
        serialized: JSON.stringify({ canvasId: cid, title, version, updatedAtMs: Date.now(), entities: next }),
      };
    },
    async readSnapshot(canvasId) {
      const cid = String(canvasId || 'default');
      const entities = localSnapshots.get(cid);
      if (!entities) return { ok: true, canvasId: cid, snapshot: null };
      const meta = entities[`canvas:${cid}`] ? JSON.parse(entities[`canvas:${cid}`]) : null;
      return { ok: true, canvasId: cid, snapshot: meta, entities };
    },
    async clearSnapshot(canvasId) {
      const cid = String(canvasId || 'default');
      localSnapshots.delete(cid);
      if (worker && !disposed) {
        const requestId = ++seq;
        return await new Promise((resolve, reject) => {
          pending.set(requestId, { resolve, reject });
          worker.postMessage({ type: 'clear', requestId, canvasId: cid });
        });
      }
      return { ok: true, canvasId: cid, dirtyCount: 0 };
    },
    dispose() {
      disposed = true;
      for (const waiter of pending.values()) waiter.resolve(null);
      pending.clear();
      localSnapshots.clear();
      if (worker) {
        try { worker.terminate(); } catch {}
        worker = null;
      }
      if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {
        window.removeEventListener('pagehide', handlePageHide);
        window.removeEventListener('beforeunload', handleBeforeUnload);
      }
      if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
        document.removeEventListener('visibilitychange', handleVisibility);
      }
    },
  };
}
