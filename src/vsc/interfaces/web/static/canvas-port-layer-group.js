/* Port dragging extras, local layer tools, group layout, asset save and agent views.
   Persistence stays on the host callbacks. Edges remain {id, source, target, port}. */
import {batchReassign, connectNodes, isFixedReferenceEdge, nodeEdgePath, nodeSize, planConnection} from './canvas-node-cards.js';

export const API_ERRORS = Object.freeze({
  untitled_canvas: '未命名画布',
  collaboration_credential_invalid: '协作连接凭据无效',
  empty_response: '接口返回数据为空',
  run_record_missing: '运行记录不存在',
  fixed_reference_edge_not_deletable: '固定引用连线不可删除',
  video_format_not_supported: '仅支持上传 MP4、MOV 格式视频',
  lrc_empty: 'LRC 文件内容为空',
  lrc_invalid: '未找到有效的歌词时间标签',
});

export const CONTEXT_MENU_ITEMS = Object.freeze(['撤销', '重做', '复制', '创建副本', '粘贴', '删除', '聚焦视口', '从此参考生成']);
export const ASSET_TYPE_OPTIONS = Object.freeze([
  {label: '人设', kind: 'character'},
  {label: '场景', kind: 'location'},
  {label: '道具', kind: 'prop'},
  {label: '站位', kind: 'blocking'},
]);
export const UPLOAD_MAX_COUNT = 20;
export const MAX_LAYER_SELECTIONS = 16;
export const SIDEBAR_WIDTH_KEY = 'sidebarWidth';
export const SAVE_ASSET_SUCCESS = '已保存到资产库';

export function canvasApiErrorText(code) {
  return API_ERRORS[code] || '';
}

export function readApiError(error) {
  const code = error?.code || error?.body?.code || error?.detail?.code;
  const mapped = canvasApiErrorText(code);
  if (mapped) return mapped;
  if (!error || error.message == null || error.message === '') return API_ERRORS.empty_response;
  return String(error.message);
}

export function submitChord(event) {
  return Boolean(event && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key === 'Enter');
}

export function validateVideoFile(file) {
  const name = String(file?.name || '').toLowerCase();
  const type = String(file?.type || '').toLowerCase();
  const looksVideo = type.startsWith('video/') || ['.mp4', '.mov', '.webm', '.mkv', '.avi'].some(ext => name.endsWith(ext));
  if (!looksVideo) return {ok: true};
  const ok = name.endsWith('.mp4') || name.endsWith('.mov') || type === 'video/mp4' || type === 'video/quicktime';
  return ok ? {ok: true} : {ok: false, code: 'video_format_not_supported', message: API_ERRORS.video_format_not_supported};
}

export function validateLrcText(text) {
  const body = String(text ?? '');
  if (!body.trim()) return {ok: false, code: 'lrc_empty', message: API_ERRORS.lrc_empty};
  if (!/\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]/.test(body)) return {ok: false, code: 'lrc_invalid', message: API_ERRORS.lrc_invalid};
  return {ok: true};
}

export function limitUploadFiles(files, max = UPLOAD_MAX_COUNT) {
  const list = [...(files || [])];
  if (list.length <= max) return {files: list, truncated: false, message: ''};
  return {files: list.slice(0, max), truncated: true, message: `单次最多上传 ${max} 个文件，已仅处理前 ${max} 个`};
}

export async function prepareCanvasUploadFiles(files, notice) {
  const limited = limitUploadFiles(files);
  if (limited.truncated) notice?.(limited.message);
  const accepted = [];
  for (const file of limited.files) {
    const video = validateVideoFile(file);
    if (!video.ok) { notice?.(video.message); continue; }
    if (String(file?.name || '').toLowerCase().endsWith('.lrc')) {
      const text = typeof file.text === 'function' ? await file.text() : '';
      const lrc = validateLrcText(text);
      if (!lrc.ok) { notice?.(lrc.message); continue; }
    }
    accepted.push(file);
  }
  return accepted.length ? accepted : null;
}

export function buildProjectAssetPayload({name, kind, mediaId, assetId = null, baseRevision = 0, formVersionId = null}) {
  const payload = {
    name: String(name || '').trim(),
    asset_kind: kind,
    base_revision: assetId ? baseRevision : 0,
    forms: [{form_key: 'master', name: '默认', base_version_id: formVersionId || null, media_id: mediaId}],
  };
  if (assetId) payload.asset_id = assetId;
  return payload;
}

export function buildBlockingPayload({sceneId, episodeId = null, mediaId, document}) {
  if (!sceneId) return {ok: false, message: 'BU 站位单元须属于真实场次'};
  return {ok: true, payload: {mode: 'blocking', scene_id: sceneId, episode_id: episodeId || null, document: {...(document || {}), panorama_media_id: mediaId}}};
}

export function referenceTargetType(node) {
  if (!node) return 'image';
  if (node.type === 'text' || node.type === 'image') return 'image';
  if (node.type === 'audio' || node.type === 'video') return 'video';
  return 'image';
}

export function referencePortFor(source, targetType) {
  if (source?.type === 'text') return 'prompt';
  if (source?.type === 'video') return targetType === 'video' ? 'reference_video' : 'first_frame';
  if (source?.type === 'audio') return 'reference_audio';
  return 'reference';
}

export function ungroupDocument(document, frameId) {
  const frame = document?.nodes?.find(node => node.id === frameId);
  if (!frame) return {ok: false, message: '分组不存在', document};
  const name = frame.group || '';
  const nodes = document.nodes.filter(node => node.id !== frameId).map(node => name && node.group === name ? {...node, group: ''} : node);
  const edges = (document.edges || []).filter(edge => edge.source !== frameId && edge.target !== frameId);
  return {ok: true, document: {...document, nodes, edges}};
}

export function groupMembers(document, frame) {
  if (!frame?.group) return [];
  return (document?.nodes || []).filter(node => node.id !== frame.id && node.group === frame.group);
}

export function arrangeMembers(members, axis, origin, gap = 48) {
  const ordered = [...(members || [])].sort((a, b) => axis === 'vertical' ? (a.y - b.y) || (a.x - b.x) : (a.x - b.x) || (a.y - b.y));
  return ordered.map((node, index) => axis === 'vertical'
    ? {...node, x: origin.x, y: origin.y + index * (180 + gap)}
    : {...node, x: origin.x + index * (260 + gap), y: origin.y});
}

export function beautifyMembers(members, origin) {
  return arrangeMembers(members, 'horizontal', origin, 36).map(node => ({...node, x: Math.round(node.x / 20) * 20, y: Math.round(node.y / 20) * 20}));
}

export function projectWorkflows(steps, canceledIds = []) {
  const canceled = new Set(canceledIds || []);
  const rows = steps || [];
  return rows.map((step, index) => {
    const jobs = step.jobs || [];
    let status = 'running';
    if (canceled.has(step.id)) status = 'canceled';
    else if (jobs.some(job => job.status === 'failed')) status = 'failed';
    else if (jobs.length && jobs.every(job => ['succeeded', 'cancelled'].includes(job.status))) status = 'succeeded';
    else if (!jobs.length) status = 'waiting_dependency';
    else if (step.needs_approval || jobs.some(job => job.status === 'created')) status = 'waiting_auth';
    const active = jobs.find(job => !['succeeded', 'failed', 'cancelled'].includes(job.status));
    return {
      id: step.id,
      status,
      current_step: index + 1,
      total_steps: rows.length,
      job_id: active?.id || jobs[0]?.id || null,
      label: {running: '运行中', waiting_auth: '等待授权', waiting_dependency: '等待依赖', succeeded: '已完成', failed: '失败', canceled: '已取消'}[status] || status,
    };
  }).filter(row => ['running', 'waiting_auth', 'waiting_dependency'].includes(row.status));
}

export function summarizeAgentProgress({assets = [], artifacts = [], episodes = []} = {}) {
  const unified = (assets || []).filter(item => item && item.asset_kind && item.asset_kind !== 'blocking' && item.record_kind !== 'blocking').length;
  const published = (artifacts || []).filter(item => item?.approved || item?.published).length;
  const episodeTotal = (episodes || []).filter(item => !item.kind || item.kind === 'episode').length;
  const saved = (artifacts || []).filter(item => /episode|candidate|分集/.test(String(item.artifact_type || item.artifact_key || item.title || ''))).length;
  const total = episodeTotal || saved;
  return {unified, completed: Math.min(saved, total), total, published, lines: [`统一资产 ${unified}`, `分集候选已保存 ${Math.min(saved, total)}/${total}`, `已发布资产 ${published}`]};
}

export function fixedReferenceProtected(edge, document) {
  return isFixedReferenceEdge(edge, document);
}

function clearHighlight(s) {
  s.world?.querySelectorAll?.('.cc-plg-port-legal, .cc-plg-port-illegal')?.forEach(node => node.classList.remove('cc-plg-port-legal', 'cc-plg-port-illegal'));
}

export function highlightLegalPorts(s, api, spec) {
  clearHighlight(s);
  if (!spec?.node || spec.side === 'batch') return;
  for (const card of s.world?.querySelectorAll?.('.cc-node') || []) {
    const node = s.document.nodes.find(item => item.id === card.dataset.nodeId);
    if (!node) continue;
    const source = spec.side === 'out' ? spec.node : node;
    const target = spec.side === 'out' ? node : spec.node;
    const decision = planConnection(s.document, source, target, api.TYPES, s.a1Caps || null);
    const ports = card.querySelectorAll(spec.side === 'out' ? '.a1-port-left' : '.a1-port-right');
    for (const port of ports) port.classList.add(decision.ok ? 'cc-plg-port-legal' : 'cc-plg-port-illegal');
  }
}

export function clearPortHighlight(s) { clearHighlight(s); }

export async function reassignOutgoing(s, api, from, to) {
  if (!from || !to) return;
  const result = batchReassign(s.document, from.id, to.id, null, api.TYPES, s.a1Caps || null);
  if (!result.ok) { api.notice(s, result.message); return; }
  api.change(s, () => { s.document.edges = result.document.edges; });
  api.notice(s, '出边已批量迁移');
}

function paintShotIndexes(s) {
  s.world?.querySelectorAll?.('.cc-plg-shot-index')?.forEach(node => node.remove());
  const frames = (s.document?.nodes || []).filter(node => node.params?.canvas_subkind === 'group_frame' && node.params?.shot_index_visible);
  for (const frame of frames) {
    groupMembers(s.document, frame).sort((a, b) => a.x - b.x || a.y - b.y).forEach((member, index) => {
      const card = [...(s.world?.querySelectorAll?.('.cc-node') || [])].find(item => item.dataset.nodeId === member.id);
      if (!card) return;
      const badge = document.createElement('span');
      badge.className = 'cc-plg-shot-index';
      badge.textContent = String(index + 1);
      card.append(badge);
    });
  }
}

function paintEdgeEndpoints(s, api) {
  const svg = s.world?.querySelector?.('.cc-connections');
  if (!svg || s.readOnly) return;
  svg.querySelectorAll('.cc-plg-edge-handle').forEach(node => node.remove());
  const ox = s.displayOffset?.x || 0, oy = s.displayOffset?.y || 0;
  for (const edge of s.document.edges || []) {
    const source = s.document.nodes.find(node => node.id === edge.source);
    if (!source) continue;
    const size = nodeSize(source);
    const handle = document.createElementNS(svg.namespaceURI || 'http://www.w3.org/2000/svg', 'circle');
    handle.setAttribute('cx', String(source.x + ox + size.w));
    handle.setAttribute('cy', String(source.y + oy + size.h / 2));
    handle.setAttribute('r', '7');
    handle.setAttribute('class', 'cc-plg-edge-handle');
    handle.dataset.edgeId = edge.id;
    handle.addEventListener('pointerdown', event => {
      event.preventDefault?.();
      event.stopPropagation?.();
      const move = next => next.preventDefault?.();
      const up = next => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        const card = next.target?.closest?.('.cc-node');
        const target = s.document.nodes.find(node => node.id === card?.dataset?.nodeId);
        if (target) return reassignOutgoing(s, api, source, target);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    svg.append(handle);
  }
}

export function decoratePortLayerGroup(s, api) {
  paintShotIndexes(s);
  paintEdgeEndpoints(s, api);
}

function menuButton(host, s, label, action) {
  const button = host.button(s, label, action);
  button.className = 'cc-plg-menu-item';
  return button;
}

export function installPortLayerGroup(s, host) {
  if (s.plgInstalled) return;
  s.plgInstalled = true;
  s.plgCanceledSteps = s.plgCanceledSteps || [];
  const stage = s.stage;
  stage?.addEventListener?.('contextmenu', event => {
    const card = event.target?.closest?.('.cc-node');
    if (!card || s.readOnly) return;
    event.preventDefault?.();
    event.stopPropagation?.();
    const node = s.document.nodes.find(item => item.id === card.dataset.nodeId);
    if (!node) return;
    s.root?.querySelector?.('.cc-plg-context')?.remove();
    const menu = host.el('div', null, 'cc-plg-context');
    menu.style.left = `${event.clientX || 0}px`;
    menu.style.top = `${event.clientY || 0}px`;
    const actions = {
      '撤销': () => host.undo(false),
      '重做': () => host.undo(true),
      '复制': () => host.copy(),
      '创建副本': () => host.duplicate(),
      '粘贴': () => host.paste(),
      '删除': () => host.deleteSelection(),
      '聚焦视口': () => host.focus(node),
      '从此参考生成': () => spawnReference(s, host, node),
    };
    for (const label of CONTEXT_MENU_ITEMS) menu.append(menuButton(host, s, label, () => { menu.remove(); return actions[label](); }));
    s.root.append(menu);
    const close = event2 => { if (!event2.target?.closest?.('.cc-plg-context')) { menu.remove(); window.removeEventListener('pointerdown', close); } };
    window.addEventListener('pointerdown', close);
  }, true);
  window.addEventListener('keydown', event => {
    if (!host.live?.() || !submitChord(event)) return;
    const send = s.root?.querySelector?.('.cc-generator-send');
    if (!send || send.disabled) return;
    event.preventDefault?.();
    send.click?.();
  });
}

function spawnReference(s, host, node) {
  const type = referenceTargetType(node);
  const id = host.newId();
  const created = {id, type, title: `${node.title} · 参考生成`.slice(0, 200), x: node.x + 320, y: node.y, text: node.type === 'text' ? node.text : '', params: {}, media_id: null, job_id: null, group: node.group || ''};
  host.change(() => {
    s.document.nodes.push(created);
    const linked = connectNodes(s.document, node.id, id, host.types || undefined);
    if (linked.ok) s.document.edges = linked.document.edges;
    else s.document.edges.push({id: host.newId(), source: node.id, target: id, port: referencePortFor(node, type)});
    s.selected = new Set([id]);
  });
}

function dialogShell(host, s, label) {
  const dialog = host.el('dialog', null, 'cc-plg-dialog');
  host.bindAttribute?.(dialog, 'aria-label', label);
  dialog.setAttribute?.('aria-label', label);
  const close = host.button(s, '关闭', () => dialog.close?.());
  close.className = 'cc-plg-close';
  s.root.append(dialog);
  dialog.addEventListener?.('close', () => dialog.remove(), {once: true});
  dialog.showModal?.();
  return {dialog, close};
}

export function mountImageLayerActions(menu, s, node, host) {
  menu.append(
    host.button(s, '图层分离', () => openLayerSeparation(s, node, host)),
    host.button(s, '图层合成', () => openLayerComposition(s, node, host)),
  );
}

export function openLayerOperation(s, node, action, host) {
  if (action === 'layer_separation') return openLayerSeparation(s, node, host);
  if (action === 'layer_composition') return openLayerComposition(s, node, host);
}

export function openLayerSeparation(s, node, host) {
  const {dialog, close} = dialogShell(host, s, '图层分离');
  const stage = host.el('div', null, 'cc-plg-stage');
  const image = host.el('img');
  image.src = `${host.base()}/media/${encodeURIComponent(node.media_id)}/content`;
  host.bindAttribute?.(image, 'alt', node.title);
  const overlay = host.el('div', null, 'cc-plg-overlay');
  stage.append(image, overlay);
  const list = host.el('div', null, 'cc-plg-selection-list');
  const selections = [];
  const paint = () => {
    overlay.replaceChildren();
    list.replaceChildren();
    selections.forEach((item, index) => {
      const box = host.el('div', null, 'cc-plg-box');
      box.style.left = `${item.bbox.x * 100}%`;
      box.style.top = `${item.bbox.y * 100}%`;
      box.style.width = `${item.bbox.w * 100}%`;
      box.style.height = `${item.bbox.h * 100}%`;
      overlay.append(box);
      const field = host.input(`区域 ${index + 1} 描述`, item.description);
      field.addEventListener('input', () => { item.description = field.value.slice(0, 200); });
      list.append(host.el('p', item.id), field);
    });
  };
  overlay.addEventListener('pointerdown', event => {
    if (selections.length >= MAX_LAYER_SELECTIONS) { host.notice('图层分离最多框选 16 个区域'); return; }
    const rect = overlay.getBoundingClientRect?.() || {left: 0, top: 0, width: 1, height: 1};
    const startX = (event.clientX - rect.left) / (rect.width || 1);
    const startY = (event.clientY - rect.top) / (rect.height || 1);
    const draft = host.el('div', null, 'cc-plg-box');
    overlay.append(draft);
    const move = next => {
      const x = (next.clientX - rect.left) / (rect.width || 1);
      const y = (next.clientY - rect.top) / (rect.height || 1);
      const left = Math.max(0, Math.min(startX, x));
      const top = Math.max(0, Math.min(startY, y));
      const width = Math.min(1 - left, Math.abs(x - startX));
      const height = Math.min(1 - top, Math.abs(y - startY));
      draft.style.left = `${left * 100}%`;
      draft.style.top = `${top * 100}%`;
      draft.style.width = `${width * 100}%`;
      draft.style.height = `${height * 100}%`;
      draft.dataset.box = JSON.stringify({x: left, y: top, w: width, h: height});
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const box = JSON.parse(draft.dataset.box || 'null');
      draft.remove();
      if (!box || box.w < 0.01 || box.h < 0.01) return;
      selections.push({id: `sel-${selections.length + 1}`, description: '', bbox: {x: round4(box.x), y: round4(box.y), w: round4(box.w), h: round4(box.h)}});
      paint();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
  const submit = host.button(s, '分离图层', async () => {
    if (!selections.length) { host.notice('请至少框选一个图层区域'); return; }
    try {
      if (host.save) await host.save();
      const result = await host.auxiliaryWrite(`layers:${node.id}:${s.version}:${selections.length}`, `${host.canvasUrl?.() || ''}/separate-layers`, {canvas_revision: s.version, node_id: node.id, selections});
      await host.adopt?.(result, node.id);
      host.notice('图层分离已生成透明前景和背景修补，不消耗积分。');
      dialog.close?.();
    } catch (error) { host.notice(readApiError(error)); }
  });
  dialog.append(host.el('h3', '图层分离'), host.el('p', '最多框选 16 个区域，并填写区域描述。本机抠取透明前景，背景用邻近像素填充。'), stage, list, submit, close);
  return dialog;
}

function round4(value) { return Math.round(value * 10000) / 10000; }

export function openLayerComposition(s, node, host) {
  const {dialog, close} = dialogShell(host, s, '图层合成');
  const images = s.document.nodes.filter(item => item.type === 'image' && item.media_id && (item.id === node.id || item.group === node.group));
  const layers = images.map((item, index) => ({node_id: item.id, title: item.title, x: index * 24, y: index * 24, scale: 1, z: index, visible: true}));
  const stage = host.el('div', null, 'cc-plg-compose');
  const controls = host.el('div', null, 'cc-plg-compose-controls');
  const paint = () => {
    stage.replaceChildren();
    controls.replaceChildren();
    [...layers].sort((a, b) => a.z - b.z).forEach(layer => {
      const chip = host.el('div', null, 'cc-plg-layer' + (layer.visible ? '' : ' is-hidden'));
      chip.style.left = `${layer.x}px`;
      chip.style.top = `${layer.y}px`;
      chip.style.transform = `scale(${layer.scale})`;
      chip.textContent = layer.title;
      chip.addEventListener('pointerdown', event => {
        event.preventDefault?.();
        const startX = event.clientX, startY = event.clientY, x = layer.x, y = layer.y;
        const move = next => { layer.x = Math.round(x + next.clientX - startX); layer.y = Math.round(y + next.clientY - startY); chip.style.left = `${layer.x}px`; chip.style.top = `${layer.y}px`; };
        const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
      });
      stage.append(chip);
      const line = host.el('div', null, 'cc-plg-layer-row');
      line.append(host.el('span', layer.title));
      line.append(host.button(s, '放大', () => { layer.scale = Math.min(8, Math.round((layer.scale + 0.1) * 100) / 100); paint(); }));
      line.append(host.button(s, '缩小', () => { layer.scale = Math.max(0.05, Math.round((layer.scale - 0.1) * 100) / 100); paint(); }));
      line.append(host.button(s, '上移', () => { layer.z += 1; paint(); }));
      line.append(host.button(s, '下移', () => { layer.z -= 1; paint(); }));
      line.append(host.button(s, layer.visible ? '隐藏' : '显示', () => { layer.visible = !layer.visible; paint(); }));
      controls.append(line);
    });
  };
  const submit = host.button(s, '免费合成', async () => {
    try {
      if (host.save) await host.save();
      const payload = {canvas_revision: s.version, layers: layers.map(({node_id, x, y, scale, z, visible}) => ({node_id, x, y, scale, z, visible}))};
      const result = await host.auxiliaryWrite(`compose:${node.id}:${s.version}`, `${host.canvasUrl?.() || ''}/compose-layers`, payload);
      await host.adopt?.(result, node.id);
      host.notice('免费合成已落回画布，不消耗积分/额度。');
      dialog.close?.();
    } catch (error) { host.notice(readApiError(error)); }
  });
  submit.className = 'cc-plg-free';
  dialog.append(host.el('h3', '图层合成'), host.el('p', '拖拽移动图层，可缩放、调整上下顺序和显隐。免费合成不消耗积分/额度。'), stage, controls, submit, close);
  paint();
  return dialog;
}

export function mountGroupLayoutTools(bar, s, node, host) {
  const members = () => groupMembers(s.document, node);
  const apply = placed => host.change(() => {
    for (const item of placed) {
      const live = s.document.nodes.find(row => row.id === item.id);
      if (live) { live.x = item.x; live.y = item.y; }
    }
  });
  bar.append(host.button(s, '解组', () => {
    const result = ungroupDocument(s.document, node.id);
    if (!result.ok) { host.notice(result.message); return; }
    host.change(() => { s.document.nodes = result.document.nodes; s.document.edges = result.document.edges; s.selected.delete(node.id); });
  }));
  bar.append(host.button(s, '拼成长图', () => stitchGroup(s, node, host, 'long')));
  bar.append(host.button(s, '拼成宫格', () => stitchGroup(s, node, host, 'grid')));
  bar.append(host.button(s, '美化排版', () => apply(beautifyMembers(members(), {x: node.x + 40, y: node.y + 80}))));
  const axis = node.params?.layout_axis === 'vertical' ? 'vertical' : 'horizontal';
  bar.append(host.button(s, axis === 'vertical' ? '改为横向' : '改为纵向', () => {
    const next = node.params?.layout_axis === 'vertical' ? 'horizontal' : 'vertical';
    apply(arrangeMembers(members(), next, {x: node.x + 40, y: node.y + 80}));
    host.change(() => { const live = s.document.nodes.find(row => row.id === node.id); if (live) live.params.layout_axis = next; });
  }));
  const shown = Boolean(node.params?.shot_index_visible);
  bar.append(host.button(s, shown ? '隐藏镜头序号' : '显示镜头序号', () => host.change(() => {
    const live = s.document.nodes.find(row => row.id === node.id);
    if (live) live.params.shot_index_visible = !shown;
  })));
}

async function stitchGroup(s, node, host, mode) {
  const ids = groupMembers(s.document, node).filter(item => item.type === 'image' && item.media_id).map(item => item.id);
  if (ids.length < 2) { host.notice('请选择 2 至 16 张图片拼合'); return; }
  try {
    if (host.save) await host.save();
    const result = await host.auxiliaryWrite(`stitch:${node.id}:${mode}:${s.version}`, `${host.canvasUrl?.() || ''}/stitch-images`, {canvas_revision: s.version, node_ids: ids.slice(0, 16), mode, group_name: node.group || ''});
    await host.adopt?.(result, ids[0]);
    host.notice(mode === 'long' ? '已拼合为长图' : '已拼合为宫格图');
  } catch (error) { host.notice(readApiError(error)); }
}

export function openSaveAssetDialog(s, node, host) {
  if (!node.media_id) { host.notice('请先固定节点媒体'); return; }
  if (!String(s.title || '').trim()) host.notice(API_ERRORS.untitled_canvas);
  const {dialog, close} = dialogShell(host, s, '保存到资产库');
  const kind = host.input('资产类型', 'character', 'select');
  for (const option of ASSET_TYPE_OPTIONS) {
    const row = host.el('option', option.label);
    row.value = option.kind;
    kind.append(row);
  }
  const name = host.input('资产名称', node.title || '');
  const submit = host.button(s, '保存到资产库', async () => {
    const label = name.value.trim();
    if (!label) { host.notice('请填写资产名称'); return; }
    try {
      if (kind.value === 'blocking') await saveBlocking(s, node, host, label);
      else await saveCard(s, node, host, label, kind.value);
      host.notice(SAVE_ASSET_SUCCESS);
      dialog.close?.();
    } catch (error) { host.notice(readApiError(error)); }
  });
  const advanced = host.button(s, '高级候选绑定', () => { dialog.close?.(); return host.toCandidate?.(node); });
  dialog.append(host.el('h3', '保存到资产库'), host.el('p', '选择人设、场景、道具或站位，并填写资产名称。'), kind, name, submit, advanced, close);
  return dialog;
}

async function postJson(host, s, path, payload) {
  const result = await host.api(path, {method: 'POST', headers: host.headers(), body: JSON.stringify({payload, expected_revision: s.revision, idempotency_key: host.newId()})});
  if (result?.revision != null) host.revision?.(result.revision);
  return result;
}

async function saveCard(s, node, host, name, kind) {
  const assetId = node.params?.saved_asset_id || null;
  const payload = buildProjectAssetPayload({
    name, kind, mediaId: node.media_id, assetId,
    baseRevision: Number(node.params?.saved_asset_revision || 0),
    formVersionId: node.params?.saved_form_version_id || null,
  });
  const result = await postJson(host, s, `${host.base()}/asset-cards`, payload);
  const form = result?.forms?.[0] || {};
  host.change(() => {
    node.params.saved_asset_id = result.id || assetId;
    node.params.saved_asset_revision = result.asset_revision ?? node.params.saved_asset_revision ?? 0;
    if (form.version_id) node.params.saved_form_version_id = form.version_id;
    node.params.saved_asset_kind = kind;
    node.params.saved_asset_name = name;
  });
}

async function saveBlocking(s, node, host, name) {
  const options = await host.api(`${host.base()}/creative-canvas-run-options`);
  const scene = (options.nodes || []).find(item => item.kind === 'scene');
  const spatial = await host.api(`${host.base()}/spatial-scene-options`);
  const built = buildBlockingPayload({sceneId: scene?.id, episodeId: scene?.parent_id, mediaId: node.media_id, document: spatial.default_document});
  if (!built.ok) throw new Error(built.message);
  built.payload.document = {...built.payload.document};
  const result = await postJson(host, s, `${host.base()}/spatial-scenes`, built.payload);
  host.change(() => { node.params.saved_blocking_id = result.id || ''; node.params.saved_asset_name = name; node.params.saved_asset_kind = 'blocking'; });
}

const STATUS_TEXT = {running: '运行中', waiting_auth: '等待授权', waiting_dependency: '等待依赖', canceled: '已取消'};

export function mountAgentWorkViews(panel, s, host) {
  if (!panel || panel.querySelector?.('.cc-plg-agent')) return;
  const root = host.el('section', null, 'cc-plg-agent');
  const bar = host.el('div', null, 'cc-plg-workflows');
  const toggle = host.button(s, 'Agent 文档 / 剧集进度', () => { docs.hidden = !docs.hidden; });
  const docs = host.el('div', null, 'cc-plg-docs');
  docs.hidden = true;
  root.append(host.el('h3', '活跃后台工作流（Active Workflows）'), bar, toggle, docs);
  const stream = panel.querySelector('.cc-agent-stream');
  if (stream) panel.insertBefore(root, stream);
  else panel.prepend(root);
  const paint = rows => {
    bar.replaceChildren();
    if (!rows.length) { bar.append(host.el('p', '当前没有活跃后台工作流')); return; }
    for (const row of rows) {
      const line = host.el('div', null, 'cc-plg-workflow');
      line.append(host.el('span', `${row.current_step}/${row.total_steps} · ${STATUS_TEXT[row.status] || row.label}`));
      const cancel = host.button(s, '取消', async () => {
        try {
          const result = await postJson(host, s, `${host.canvasUrl()}/workflow-cancel`, {canvas_id: s.id, step_id: row.id, ...(row.job_id ? {job_id: row.job_id} : {})});
          s.plgCanceledSteps = [...(s.plgCanceledSteps || []), row.id];
          host.notice(result?.persisted ? '已取消后台工作流' : '已在本机标记取消；该步骤没有可持久化的任务');
          await refresh();
        } catch (error) { host.notice(readApiError(error)); }
      });
      line.append(cancel);
      bar.append(line);
    }
  };
  async function refresh() {
    try {
      const detail = await host.api(host.canvasUrl());
      paint(projectWorkflows(detail.execution_steps || s.steps || [], s.plgCanceledSteps || []));
      const [artifacts, assets, options] = await Promise.all([
        host.api(`${host.base()}/artifacts`).catch(() => ({items: []})),
        host.api(`${host.base()}/asset-cards?limit=100`).catch(() => ({items: []})),
        host.api(`${host.base()}/creative-canvas-run-options`).catch(() => ({nodes: []})),
      ]);
      const summary = summarizeAgentProgress({assets: assets.items || [], artifacts: artifacts.items || [], episodes: (options.nodes || []).filter(item => item.kind === 'episode')});
      docs.replaceChildren(host.el('h4', 'Agent 文档 / 剧集进度'));
      const items = artifacts.items || [];
      if (!items.length) docs.append(host.el('p', '暂无 Agent 文档'));
      else for (const item of items.slice(0, 12)) docs.append(host.el('p', item.title || item.artifact_key || item.artifact_type || '文档'));
      for (const line of summary.lines) docs.append(host.el('p', line, 'cc-plg-stat'));
    } catch (error) { host.notice(readApiError(error)); }
  }
  root.refresh = refresh;
  void refresh();
  return root;
}

export function edgePreviewPath(from, to, ox = 0, oy = 0) {
  return nodeEdgePath(from, to, ox, oy);
}
