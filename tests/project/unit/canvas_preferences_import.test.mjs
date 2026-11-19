import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {
  applyUserAppearance,
  augmentConflictDialog,
  buildDetailSnapshot,
  buildNodeClipboard,
  classifyReadonlyReason,
  commitDetailImport,
  importDetailSnapshot,
  importZipEntries,
  installCanvasPreferencesImport,
  normalizeTaskRows,
  normalizeUserPreferences,
  openCanvasReplaceMediaDialog,
  openCreationRecordPopover,
  openPreferencesDialog,
  paintReadonlyBanner,
  planTopologyRestore,
  preferencesPatch,
  readZipEntries,
  resolvePastePayload,
  settleConflictChoices,
  validateDetailImport,
  validateHistoryRestore,
  validateNodeClipboard,
} from '../../../src/vsc/interfaces/web/static/canvas-preferences-import.js';

const {Document} = createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
const document = new Document('<main id="root"></main>');
globalThis.document = document;

function storedZip(files) {
  const encoder = new TextEncoder();
  const parts = [];
  for (const file of files) {
    const name = encoder.encode(file.name);
    const data = file.data;
    const local = new Uint8Array(30 + name.length + data.length);
    const view = new DataView(local.buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(8, 0, true);
    view.setUint32(18, data.length, true);
    view.setUint32(22, data.length, true);
    view.setUint16(26, name.length, true);
    local.set(name, 30);
    local.set(data, 30 + name.length);
    parts.push(local);
  }
  const all = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    all.set(part, at);
    at += part.length;
  }
  return all;
}

test('preferences normalize, persist and apply font plus watermark', async () => {
  assert.deepEqual(normalizeUserPreferences({items: [], revision: 2}), {
    collaboration: {enabled_on_new_canvas: false},
    ui: {font_size: 14},
    ai_watermark: {visible: true},
  });
  const stored = normalizeUserPreferences({preferences: {
    collaboration: {enabled_on_new_canvas: true},
    ui: {font_size: 18},
    ai_watermark: {visible: false},
  }});
  assert.equal(stored.ui.font_size, 18);
  assert.equal(stored.ai_watermark.visible, false);
  assert.deepEqual(preferencesPatch(stored), {preferences: {
    collaboration: {enabled_on_new_canvas: true},
    ui: {font_size: 18},
    ai_watermark: {visible: false},
  }});
  applyUserAppearance(stored, {});
  const appearance = document.createElement('div');
  applyUserAppearance(stored, appearance);
  assert.equal(appearance.dataset.vscFontSize, '18');
  assert.equal(appearance.dataset.aiWatermark, 'hidden');

  const calls = [];
  let saved = null;
  const api = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({url, method: options.method || 'GET', body});
    if (options.method === 'PUT') {
      saved = body.preferences;
      return {preferences: saved};
    }
    return {preferences: saved || {collaboration: {enabled_on_new_canvas: false}, ui: {font_size: 14}, ai_watermark: {visible: true}}};
  };
  const dialog = await openPreferencesDialog({api, root: document.body});
  const large = [...dialog.querySelectorAll('.cpi-font-tier')].find(node => node.dataset.tier === 'large');
  await large.click();
  dialog.querySelector('.cpi-collab').checked = true;
  await [...dialog.querySelectorAll('.cpi-mark')].find(node => node.dataset.mark === 'hidden').click();
  await dialog.querySelector('.cpi-pref-save').click();
  assert.deepEqual(calls.find(call => call.method === 'PUT').body, {preferences: {
    collaboration: {enabled_on_new_canvas: true},
    ui: {font_size: 16},
    ai_watermark: {visible: false},
  }});
  assert.match(dialog.querySelector('.cpi-pref-status').textContent, /偏好设置已保存/);
  dialog.close();

  const mismatch = await openPreferencesDialog({
    api: async (url, options = {}) => {
      if (options.method === 'PUT') return {preferences: {collaboration: {enabled_on_new_canvas: true}, ui: {font_size: 16}, ai_watermark: {visible: true}}};
      return {preferences: {collaboration: {enabled_on_new_canvas: false}, ui: {font_size: 14}, ai_watermark: {visible: true}}};
    },
    root: document.body,
  });
  await [...mismatch.querySelectorAll('.cpi-font-tier')].find(node => node.dataset.tier === 'large').click();
  await mismatch.querySelector('.cpi-pref-save').click();
  assert.match(mismatch.querySelector('.cpi-pref-status').textContent, /保存结果未确认，请重新读取后核实/);
  mismatch.close();
});

test('creation record popover lists task id, type, status and view', async () => {
  let viewed = null;
  let opened = 0;
  const popover = await openCreationRecordPopover({
    projectId: 'project-1',
    root: document.body,
    api: async () => ({items: [{
      id: 'task-9',
      kind: 'generation',
      status: 'succeeded',
      href: '/?page=creative-canvas&task_id=task-9',
      presentation: {origin_label: '媒体生成', state_label: '已完成'},
    }]}),
    onView: row => { viewed = row; },
    onOpenCenter: () => { opened += 1; },
  });
  assert.deepEqual(normalizeTaskRows({items: [{id: 'task-9', presentation: {origin_label: '媒体生成', state_label: '已完成'}}]}), [
    {id: 'task-9', type: '媒体生成', status: '已完成', href: '', title: ''},
  ]);
  const headers = [...popover.querySelectorAll('th')].map(node => node.textContent);
  assert.deepEqual(headers, ['任务ID', '任务类型', '状态', '操作']);
  assert.match(popover.textContent, /task-9/);
  assert.match(popover.textContent, /媒体生成/);
  assert.match(popover.textContent, /已完成/);
  await popover.querySelector('.cpi-task-view').click();
  assert.equal(viewed.id, 'task-9');
  assert.equal(viewed.href, '/?page=creative-canvas&task_id=task-9');
  const again = await openCreationRecordPopover({projectId: 'project-1', root: document.body, api: async () => ({items: []}), onOpenCenter: () => { opened += 1; }});
  await again.querySelector('.cpi-task-center').click();
  assert.equal(opened, 1);
});

test('conflict choices settle per node and show a receipt', async () => {
  const kept = settleConflictChoices({
    conflicts: [{node_id: 'n1'}],
    choices: ['mine'],
    localDocument: {title: '本地', nodes: [{id: 'n1', type: 'text', text: '本地句'}], edges: []},
    remoteDocument: {title: '远端', nodes: [{id: 'n1', type: 'text', text: '远端句'}], edges: [{id: 'e1', source: 'n1', target: 'n1'}]},
  });
  assert.equal(kept.document.nodes[0].text, '本地句');
  assert.equal(kept.document.edges[0].id, 'e1');
  assert.equal(kept.receipt[0].note, '已用我的修改替换该节点');

  const remoteChoice = settleConflictChoices({
    conflicts: [{node_id: 'n2'}],
    choices: ['remote'],
    localDocument: {nodes: [{id: 'n2', type: 'text', text: '本地'}], edges: []},
    remoteDocument: {nodes: [], edges: []},
  });
  assert.equal(remoteChoice.document.nodes.length, 0);
  assert.equal(remoteChoice.receipt[0].note, '采用远端版本');

  const recreated = settleConflictChoices({
    conflicts: [{node_id: 'n2'}],
    choices: ['mine'],
    localDocument: {nodes: [{id: 'n2', type: 'image', title: '参考'}], edges: [{id: 'old', source: 'n2', target: 'n1'}]},
    remoteDocument: {nodes: [], edges: []},
  });
  assert.equal(recreated.document.nodes[0].id, 'n2');
  assert.equal(recreated.document.edges.length, 0);
  assert.match(recreated.receipt[0].note, /旧连线不会恢复/);

  const locked = settleConflictChoices({
    conflicts: [{node_id: 'n1', locked_by_other: true}],
    choices: ['mine'],
    localDocument: {nodes: [{id: 'n1', type: 'text', text: '本地'}], edges: []},
    remoteDocument: {nodes: [{id: 'n1', type: 'text', text: '远端'}], edges: []},
  });
  assert.equal(locked.ok, false);
  assert.match(locked.message, /节点正被其他人编辑/);

  const dialog = document.createElement('dialog');
  dialog.className = 'canvas-conflict-dialog';
  const card = document.createElement('article');
  card.className = 'cc-conflict-item';
  const foot = document.createElement('footer');
  foot.className = 'cc-conflict-footer';
  dialog.append(card, foot);
  document.body.append(dialog);
  let applied = null;
  augmentConflictDialog(dialog, {
    conflicts: [{node_id: 'n1'}],
    localDocument: {nodes: [{id: 'n1', type: 'text', text: '本地句'}], edges: []},
    remoteDocument: {nodes: [{id: 'n1', type: 'text', text: '远端句'}], edges: []},
    root: document.body,
    isLocked: () => false,
    applyMerged: async result => { applied = result; return true; },
  });
  await dialog.querySelector('.cpi-keep').click();
  await dialog.querySelector('.cpi-settle').click();
  assert.equal(applied.document.nodes[0].text, '本地句');
  assert.match(document.body.textContent, /结算回执/);
  assert.match(document.body.textContent, /确认已发送请求/);
  assert.match(document.body.textContent, /同步服务端状态/);
});

test('readonly reasons distinguish takeover, offline and permission', async () => {
  assert.equal(classifyReadonlyReason({kicked: true, syncState: 'offline', canEdit: false}).kind, 'takeover');
  assert.equal(classifyReadonlyReason({kicked: true}).action, '在此窗口接管编辑');
  assert.equal(classifyReadonlyReason({syncState: 'offline', canEdit: true}).message, '离线只读');
  assert.equal(classifyReadonlyReason({canEdit: false, collaborationEnabled: false}).message, '协作已关闭，当前仅可查看画布');
  assert.equal(classifyReadonlyReason({canEdit: false, permissionReason: 'permission_revoked'}).message, '当前没有编辑权限，仅可查看画布');
  assert.equal(classifyReadonlyReason({canEdit: true, syncState: 'synced'}), null);
  const root = document.createElement('section');
  let took = 0;
  paintReadonlyBanner(root, {kicked: true, syncState: 'offline', canEdit: false}, () => { took += 1; });
  assert.equal(root.querySelector('.cpi-readonly-banner').dataset.kind, 'takeover');
  await root.querySelector('.cpi-takeover').click();
  assert.equal(took, 1);
  paintReadonlyBanner(root, {canEdit: true, syncState: 'synced'});
  assert.equal(root.querySelector('.cpi-readonly-banner'), null);
});

test('history topology validates references and rebuilds new nodes', () => {
  assert.equal(validateHistoryRestore({version: 2, nodes: [], edges: []}).message, '不支持恢复图版本 2');
  assert.equal(validateHistoryRestore({
    version: 1,
    nodes: [{id: 'a', type: 'text'}, {id: 'a', type: 'image'}],
    edges: [],
  }).message, '历史恢复图存在重复节点 ID');
  assert.equal(validateHistoryRestore({
    version: 1,
    nodes: [{id: 'gen', type: 'image', role: 'generator'}],
    edges: [{id: 'e', source: 'missing', target: 'gen'}],
  }).message, '历史恢复连线源节点 missing 不存在');
  assert.equal(validateHistoryRestore({
    version: 1,
    nodes: [{id: 'ref', type: 'text'}, {id: 'gen', type: 'image', role: 'generator', references: ['ref']}],
    edges: [],
  }).message, '生成引用节点 ref 不在一层上游快照中');
  let seq = 0;
  const plan = planTopologyRestore({
    version: 1,
    nodes: [
      {id: 'ref', type: 'text', role: 'reference', title: '提示', x: 10, y: 20, text: '雨'},
      {id: 'gen', type: 'image', role: 'generator', title: '成图', x: 40, y: 20, text: '', references: ['ref']},
    ],
    edges: [{id: 'e', source: 'ref', target: 'gen', port: 'prompt'}],
  }, {nodeCount: 1, newId: () => `new-${seq++}`});
  assert.equal(plan.ok, true);
  assert.deepEqual(plan.nodes.map(node => node.id), ['new-0', 'new-1']);
  assert.equal(plan.nodes[0].x, 10);
  assert.equal(plan.nodes[0].text, '雨');
  assert.equal(plan.edges[0].source, 'new-0');
  assert.equal(plan.edges[0].target, 'new-1');
  assert.equal(plan.edges[0].port, 'prompt');
  assert.equal(plan.generatorId, 'new-1');
});

test('zip import extracts text and media and rejects unsafe names', async () => {
  const encoder = new TextEncoder();
  const unsafe = await readZipEntries(storedZip([{name: '../secret.png', data: new Uint8Array([1, 2, 3])}]));
  assert.equal(unsafe.ok, false);
  assert.match(unsafe.message, /不安全路径/);
  const duplicate = await readZipEntries(storedZip([
    {name: 'A.txt', data: encoder.encode('a')},
    {name: 'a.txt', data: encoder.encode('b')},
  ]));
  assert.equal(duplicate.ok, false);
  assert.match(duplicate.message, /重复文件名/);
  const huge = new Uint8Array(30 + 8);
  const hugeView = new DataView(huge.buffer);
  hugeView.setUint32(0, 0x04034b50, true);
  hugeView.setUint16(4, 20, true);
  hugeView.setUint32(18, 21 * 1024 * 1024, true);
  hugeView.setUint32(22, 21 * 1024 * 1024, true);
  hugeView.setUint16(26, 8, true);
  huge.set(encoder.encode('huge.png'), 30);
  const oversized = await readZipEntries(huge);
  assert.equal(oversized.ok, false);
  assert.match(oversized.message, /20MB/);

  const textZip = await readZipEntries(storedZip([
    {name: 'note.txt', data: encoder.encode('你好')},
    {name: 'shot.json', data: encoder.encode('{"schema":"vsc.canvas.detail"}')},
  ]));
  let added = [];
  const textImported = await importZipEntries(textZip.entries, {
    nodeCount: () => 0,
    newId: (() => { let n = 0; return () => `zip-${n++}`; })(),
    change: fn => fn(),
    addNodes: nodes => { added = nodes; },
  });
  assert.equal(textImported.ok, true);
  assert.equal(added[0].type, 'text');
  assert.equal(added[0].text, '你好');
  assert.equal(added[1].type, 'text');
  assert.equal(added[1].text, '{"schema":"vsc.canvas.detail"}');

  const mediaZip = await readZipEntries(storedZip([{name: 'photo.png', data: new Uint8Array([9, 8, 7, 6])}]));
  let uploaded = '';
  added = [];
  const mediaImported = await importZipEntries(mediaZip.entries, {
    nodeCount: () => 3,
    newId: () => 'media-1',
    uploadMedia: async file => { uploaded = file.name; return 'mid-1'; },
    change: fn => fn(),
    addNodes: nodes => { added = nodes; },
  });
  assert.equal(uploaded, 'photo.png');
  assert.equal(added[0].type, 'image');
  assert.equal(added[0].media_id, 'mid-1');
  assert.equal(added[0].x, 940);
});

test('detail json validates schema and keeps the current viewport', async () => {
  const doc = {viewport: {x: 9, y: 4, zoom: 2}, nodes: [{id: 'old', type: 'text'}], edges: [{id: 'edge-old', source: 'old', target: 'old'}]};
  const snapshot = buildDetailSnapshot({projectId: 'p1', canvasId: 'c1', title: '画布', document: doc});
  assert.equal(snapshot.schema, 'vsc.canvas.detail');
  assert.equal(snapshot.schema_version, 1);
  assert.equal(validateDetailImport({schema: 'other', schema_version: 1, nodes: [], connections: []}).message, 'Detail JSON 架构无效');
  assert.equal(validateDetailImport(snapshot, {collaborationEnabled: true}).message, '协作开启时不能导入 Detail JSON');
  assert.equal(validateDetailImport(snapshot, {readOnly: true}).message, '只读画布不能导入 Detail JSON');
  assert.equal(validateDetailImport({...snapshot, nodes: [{id: 'n', type: 'text'}, {id: 'n', type: 'image'}]}).message, '存在重复节点 ID');
  assert.equal(validateDetailImport({...snapshot, nodes: [{id: 'n', type: 'text'}], connections: [{id: 'e', source: 'missing', target: 'n'}]}).message, '连线引用了不存在的节点');
  const incoming = {...snapshot, nodes: [{id: 'n', type: 'text', title: '新'}], connections: []};
  let seen = '';
  const imported = await importDetailSnapshot(incoming, {
    document: () => doc,
    projectId: () => 'p1',
    confirm: message => { seen = message; return true; },
    save: async () => true,
    change: fn => fn(),
  });
  assert.equal(imported.ok, true);
  assert.match(seen, /节点 1 → 1/);
  assert.match(seen, /连线 1 → 0/);
  assert.equal(doc.viewport.x, 9);
  assert.equal(doc.viewport.zoom, 2);
  assert.equal(doc.nodes[0].id, 'n');
  const committed = commitDetailImport({viewport: {x: 9, y: 4, zoom: 2}}, incoming);
  assert.deepEqual(committed.viewport, {x: 9, y: 4, zoom: 2});

  const menu = document.createElement('div');
  menu.className = 'cc-more-menu';
  const root = document.createElement('div');
  root.append(menu);
  const stage = document.createElement('div');
  const current = {viewport: {x: 3, y: 1, zoom: 1}, nodes: [{id: 'keep', type: 'text'}], edges: []};
  let asked = '';
  const originalCreate = document.createElement.bind(document);
  const inputs = [];
  document.createElement = function create(tag) {
    const node = originalCreate(tag);
    if (tag === 'input') inputs.push(node);
    return node;
  };
  try {
    installCanvasPreferencesImport({root, stage}, {
      document: () => current,
      projectId: () => 'p1',
      canvasId: () => 'c1',
      title: () => '画布',
      collaborationEnabled: () => false,
      readOnly: () => false,
      confirm: message => { asked = message; return false; },
      save: async () => true,
      change: fn => fn(),
      notice: () => {},
    });
    const pending = menu.querySelector('.cpi-detail-import').click();
    const fileInput = inputs.at(-1);
    fileInput.files = [{text: async () => JSON.stringify({...incoming, project_id: 'p1'})}];
    await fileInput.dispatch('change');
    await pending;
  } finally {
    document.createElement = originalCreate;
  }
  assert.match(asked, /节点 1 → 1/);
  assert.equal(current.nodes[0].id, 'keep');
});

test('system clipboard keeps the canvas hint and rejects another project', async () => {
  const payload = buildNodeClipboard({
    projectId: 'p1',
    canvasId: 'c1',
    nodes: [{id: 'n', type: 'text', x: 1, y: 2, params: {}}],
    edges: [],
  });
  assert.equal(payload.canvas_node_clipboard_hint, 1);
  assert.equal(payload.version, 1);
  assert.equal(payload.project_id, 'p1');
  const other = {...payload, project_id: 'p2', project: 'p2'};
  assert.equal(validateNodeClipboard(other, {projectId: 'p1', requireHint: true}).reason, 'other_project');
  const legacy = {project: 'p1', nodes: [{id: 'n', type: 'text'}], edges: []};
  assert.equal(validateNodeClipboard(legacy, {projectId: 'p1', requireHint: false}).ok, true);
  assert.equal(validateNodeClipboard(legacy, {projectId: 'p1', requireHint: true}).reason, 'bad_hint');
  assert.equal(validateNodeClipboard({
    canvas_node_clipboard_hint: 1, version: 1, project_id: 'p1',
    nodes: [{id: 'g', params: {canvas_subkind: 'group_frame'}}],
  }, {projectId: 'p1', requireHint: true}).reason, 'group');
  let localReads = 0;
  await assert.rejects(
    () => resolvePastePayload('p1', () => { localReads += 1; return null; }, async () => JSON.stringify(other)),
    /跨项目媒体须先通过共享素材入口导入/,
  );
  assert.equal(localReads, 0);
  await assert.rejects(
    () => resolvePastePayload('p1', () => { throw new Error('local fallback'); }, async () => '{'),
    /剪贴板中的节点数据已损坏/,
  );
  const fallback = await resolvePastePayload('p1', () => legacy, async () => '   ');
  assert.equal(fallback.nodes[0].id, 'n');
});

test('replace node media dialog has history, canvas and local tabs', async () => {
  const node = {id: 'n1', type: 'image', title: '图', media_id: 'old', job_id: 'job-1'};
  let replaced = null;
  const dialog = await openCanvasReplaceMediaDialog({
    node,
    root: document.body,
    jobs: async () => ({items: [{id: 'job-1', purpose: '历史成图', node_id: 'n1', outputs: [{media_id: 'hist-1'}]}]}),
    media: async () => ({items: [{id: 'old', name: '当前'}, {id: 'lib-1', name: '画布库图'}]}),
    replace: async id => { replaced = id; return true; },
  });
  assert.match(dialog.textContent, /替换节点媒体/);
  assert.match(dialog.textContent, /本节点历史/);
  assert.match(dialog.textContent, /本画布媒体/);
  assert.match(dialog.textContent, /本地上传/);
  assert.match(dialog.textContent, /历史成图/);
  await dialog.querySelector('.cpi-choice').click();
  await dialog.querySelector('.cpi-replace-confirm').click();
  assert.equal(replaced, 'hist-1');

  const canvasDialog = await openCanvasReplaceMediaDialog({
    node,
    root: document.body,
    jobs: async () => ({items: []}),
    media: async () => ({items: [{id: 'old', name: '当前'}, {id: 'lib-1', name: '画布库图'}]}),
    replace: async () => true,
  });
  await canvasDialog.querySelector('.cpi-tab-canvas').click();
  assert.match(canvasDialog.textContent, /画布库图/);
  assert.doesNotMatch(canvasDialog.textContent, /当前/);
  canvasDialog.close();
});

test('page hooks expose preferences, creation record and the stylesheet', () => {
  const html = fs.readFileSync('src/vsc/interfaces/web/templates/index.html', 'utf8');
  const panel = fs.readFileSync('src/vsc/interfaces/web/static/panel.js', 'utf8');
  const canvas = fs.readFileSync('src/vsc/interfaces/web/static/creative-canvas.js', 'utf8');
  const collab = fs.readFileSync('src/vsc/interfaces/web/static/canvas-collab-recovery.js', 'utf8');
  assert.match(html, /\/static\/canvas-preferences-import\.css/);
  assert.match(html, /id="canvas-preferences-open">偏好设置/);
  assert.match(panel, /openCreationRecordPopover/);
  assert.match(panel, /state\.view==='creative-canvas'/);
  assert.match(canvas, /installCanvasPreferencesImport/);
  assert.match(canvas, /替换节点媒体/);
  assert.match(collab, /augmentConflictDialog/);
  assert.match(collab, /paintReadonlyBanner/);
});
