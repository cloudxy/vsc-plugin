/* Node cards, port dragging and connection checks for the creative canvas.
   Document edges stay {id, source, target, port}. Persistence stays on change(). */
const COPY = Object.freeze({
  self: '节点不能连接到自身。',
  duplicate: '这张素材已经连接到当前节点。',
  targetNot: '当前目标节点不支持添加输入连接',
  mediaUnsupported: '当前目标节点不支持连接{source}节点',
  headTailMax: '首尾帧模式最多支持 2 张图片',
  referenceMax: '当前节点最多支持连接{max}个参考节点',
  maxCount: '当前{target}节点最多支持连接{max}个{source}节点',
  fixed: '固定引用连线不可删除',
  titleRequired: '节点标题不能为空',
  noSelected: '没有选中的内容',
  cycle: '画布引用不能成环',
  maxEdges: '单个画布最多 800 条连线',
  maxNodes: '画布最多200个节点',
  batchType: '仅支持迁移到同类型节点的出口',
  batchNone: '当前节点没有可迁移的出边',
  batchFixed: '连线包含三视图、全景图或其他不可迁移的固定关系',
  batchStale: '连线状态已变化，请重新操作',
  batchDuplicate: '新源节点与原下游已存在连线，原连线未修改',
  batchUnsupported: '新源节点不兼容全部下游，原连线未修改',
  batchFailed: '批量迁移失败，原连线未修改',
  try: '尝试：',
  imageToImage: '图生图',
  headTail: '首尾帧生成视频',
  firstFrame: '首帧生成视频',
  audioToVideo: '音频生视频',
  manual: '自己编写内容',
  manualPlaceholder: '请编写内容，开始你的创作。',
  textToVideo: '文生视频',
  textToVideoGroup: '预设 - 文生视频',
  textToVideoPrompt: '根据文字描述生成视频。',
  textToVideoText: '电影级人物镜头\n雨夜街头，霓虹灯反射在湿漉漉的地面，女主撑伞站在路灯下，表情克制而坚定，镜头环绕人物360度缓慢移动，浅景深，光影对比强烈，电影级调色，真实皮肤质感',
  textToAudio: '文字生音乐',
  textToAudioGroup: '预设 - 文字生音乐',
  textToAudioText: '生成一首现代品牌电子音乐（约 110 BPM），干净有力的低频贝斯，清晰电子鼓点，整体风格高级、未来感强。开场节奏型贝斯与简洁合成器音色建立律动。主段加入稳定鼓点，节奏清晰，保持克制的张力。强化段加入更丰富的音层，合成器音色提升，律动增强但不过度拥挤。结尾鼓点减弱，仅保留低频与氛围音渐出，干净利落收尾。',
  reverse: '图片反推提示词',
  reverseGroup: '预设 - 图片反推提示词',
  reverseText: '根据图片生成结构化中文提示词，包括主体描述、环境、光影、镜头语言、风格关键词。',
  reverseImage: '反推提示词图片',
  addNode: '添加节点',
  quickLeft: '在左侧引用生成',
  quickRight: '在右侧引用生成',
  batchConnect: '批量连接',
  collapse: '收起',
  expand: '展开',
  rename: '重命名',
  reassign: '迁移出边',
  operate: '操作',
  resize: '调整文本节点大小',
  zip: '打包下载',
  addMedia: '添加素材',
  uploadLocal: '本地上传',
  pickProject: '从项目素材选择',
  placeholderHit: '上传或选择素材',
  primaryImage: '设为主图',
  primaryVideo: '设为主视频',
  primaryAudio: '设为主音频',
  unknownMedia: '该结果不属于当前节点',
  unknownAction: '未知图片推荐动作',
});

export const DEFAULT_TYPES = Object.freeze({
  text: {label: '文本', ports: {}},
  image: {label: '图片', ports: {prompt: 'text', reference: 'image'}},
  video: {label: '视频', ports: {prompt: 'text', first_frame: 'image', last_frame: 'image', reference_image: 'image', reference_video: 'video', reference_audio: 'audio'}},
  audio: {label: '音频', ports: {prompt: 'text', reference_audio: 'audio'}},
  spatial: {label: '三维预演', ports: {prompt: 'text', reference: 'image'}},
  director: {label: '站位导演台', ports: {prompt: 'text', reference: 'image'}},
  'director-stage': {label: '导演台', ports: {panorama_image: 'image'}},
  '3d-preview': {label: '3D预演', ports: {}},
  edit: {label: '剪辑', ports: {visual: ['image', 'video'], sound: 'audio'}},
  music_mix: {label: '视频配乐', ports: {source_video: 'video', sound: 'audio', prompt: 'text'}},
  processing: {label: '视频加工', ports: {source_video: 'video', prompt: 'text'}},
});

const ADD_TYPES = [
  {type: 'text', label: '文本'},
  {type: 'image', label: '图片'},
  {type: 'video', label: '视频'},
  {type: 'edit', label: '视频剪辑'},
  {type: 'director-stage', label: '导演台', badge: 'NEW'},
  {type: '3d-preview', label: '3D预演', badge: 'NEW'},
  {type: 'audio', label: '音频'},
];

const MAX_EDGES = 800;
const MAX_NODES = 200;
const MIN_W = 160, MAX_W = 640, MIN_H = 80, MAX_H = 800;

const typeLabel = (types, type) => types?.[type]?.label || DEFAULT_TYPES[type]?.label || type || '';
const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ''));
const clone = value => JSON.parse(JSON.stringify(value));
const subkind = node => node?.type === 'text' ? (node.params?.canvas_subkind || '') : '';

export function fixedEdgeMessage() { return COPY.fixed; }

function listedFixedEdges(params) {
  const raw = params?.fixed_reference;
  if (raw == null || raw === '') return null;
  if (raw === '*') return '*';
  if (typeof raw !== 'string') return null;
  const text = raw.trim();
  if (!text) return null;
  if (text === '*') return '*';
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return new Set(parsed.map(String));
      if (parsed && Array.isArray(parsed.edge_ids)) return new Set(parsed.edge_ids.map(String));
      if (parsed && typeof parsed === 'object') return new Set(Object.keys(parsed).filter(key => parsed[key]));
    } catch { return null; }
  }
  return new Set(text.split(',').map(item => item.trim()).filter(Boolean));
}

export function isFixedReferenceEdge(edge, document) {
  if (!edge) return false;
  if (edge.port === 'derived_from') return true;
  const target = document?.nodes?.find(node => node.id === edge.target);
  if (target?.params?.fixed_reference_of && target.params.fixed_reference_of === edge.source) return true;
  const targetList = listedFixedEdges(target?.params);
  if (targetList === '*' || targetList?.has?.(edge.id)) return true;
  const source = document?.nodes?.find(node => node.id === edge.source);
  const sourceList = listedFixedEdges(source?.params);
  return Boolean(sourceList && sourceList !== '*' && sourceList.has?.(edge.id));
}

function reaches(document, fromId, toId, skipEdgeId = null) {
  const next = new Map();
  for (const edge of document?.edges || []) {
    if (edge.id === skipEdgeId) continue;
    if (!next.has(edge.source)) next.set(edge.source, []);
    next.get(edge.source).push(edge.target);
  }
  const seen = new Set();
  const stack = [fromId];
  while (stack.length) {
    const id = stack.pop();
    if (id === toId) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const child of next.get(id) || []) stack.push(child);
  }
  return false;
}

export function slotsFor(node, types = DEFAULT_TYPES, capabilities = null) {
  const operation = node?.params?.vsc_operation;
  if (operation && Array.isArray(capabilities?.operations)) {
    const found = capabilities.operations.find(row => row.op_type === operation && row.node_type === node.type);
    if (found) {
      return (found.input_ports || []).map(slot => ({
        handle: slot.handle,
        accept: slot.accept || [slot.media_type].filter(Boolean),
        max: Number(slot.max_count) > 0 ? Number(slot.max_count) : (slot.handle === 'first_frame' || slot.handle === 'last_frame' ? 1 : 8),
      }));
    }
  }
  return Object.entries(types?.[node?.type]?.ports || {}).map(([handle, accept]) => ({
    handle,
    accept: Array.isArray(accept) ? accept : [accept],
    max: handle === 'first_frame' || handle === 'last_frame' ? 1 : 8,
  }));
}

export function choosePort(document, source, target, types = DEFAULT_TYPES, capabilities = null) {
  if (!source || !target) return {ok: false, reason: 'missing'};
  if (source.id === target.id) return {ok: false, reason: 'self'};
  if ((document?.edges || []).length >= MAX_EDGES) return {ok: false, reason: 'max_edges'};
  if (reaches(document, target.id, source.id)) return {ok: false, reason: 'cycle'};
  if ((document?.edges || []).some(edge => edge.source === source.id && edge.target === target.id)) return {ok: false, reason: 'duplicate'};
  const slots = slotsFor(target, types, capabilities);
  if (!slots.length) return {ok: false, reason: 'target_not_connectable'};
  const compatible = slots.filter(slot => slot.accept.includes(source.type));
  if (!compatible.length) return {ok: false, reason: 'media_input_unsupported', sourceType: source.type};
  const counts = {};
  for (const edge of document?.edges || []) if (edge.target === target.id) counts[edge.port] = (counts[edge.port] || 0) + 1;
  for (const slot of compatible) if ((counts[slot.handle] || 0) < slot.max) return {ok: true, port: slot.handle};
  if (target.params?.vsc_operation === 'head_tail_video' && source.type === 'image') {
    const used = compatible.filter(slot => slot.accept.includes('image')).reduce((sum, slot) => sum + (counts[slot.handle] || 0), 0);
    if (used >= 2) return {ok: false, reason: 'head_tail_max', max: 2};
  }
  const blocked = compatible[0];
  if (blocked.handle === 'reference' || blocked.handle.startsWith('reference')) return {ok: false, reason: 'reference_max', max: blocked.max};
  return {ok: false, reason: 'max_count', max: blocked.max, sourceType: source.type, targetType: target.type};
}

export function explainRejection(result, types = DEFAULT_TYPES) {
  if (!result || result.ok) return '';
  if (result.reason === 'self') return COPY.self;
  if (result.reason === 'duplicate') return COPY.duplicate;
  if (result.reason === 'target_not_connectable') return COPY.targetNot;
  if (result.reason === 'media_input_unsupported') return fill(COPY.mediaUnsupported, {source: typeLabel(types, result.sourceType)});
  if (result.reason === 'head_tail_max') return COPY.headTailMax;
  if (result.reason === 'reference_max') return fill(COPY.referenceMax, {max: result.max});
  if (result.reason === 'max_count') return fill(COPY.maxCount, {target: typeLabel(types, result.targetType), max: result.max, source: typeLabel(types, result.sourceType)});
  if (result.reason === 'cycle') return COPY.cycle;
  if (result.reason === 'max_edges') return COPY.maxEdges;
  return '无法连接';
}

export function planConnection(document, source, target, types = DEFAULT_TYPES, capabilities = null) {
  const decision = choosePort(document, source, target, types, capabilities);
  return decision.ok ? decision : {...decision, message: explainRejection(decision, types)};
}

export function connectNodes(document, sourceId, targetId, types = DEFAULT_TYPES, capabilities = null, idFactory = () => crypto.randomUUID()) {
  const source = document.nodes.find(node => node.id === sourceId);
  const target = document.nodes.find(node => node.id === targetId);
  const decision = planConnection(document, source, target, types, capabilities);
  if (!decision.ok) return {ok: false, message: decision.message, reason: decision.reason, document};
  const edge = {id: idFactory(), source: sourceId, target: targetId, port: decision.port};
  return {ok: true, edge, document: {...document, edges: [...document.edges, edge]}};
}

export function connectMany(document, sourceIds, targetId, types = DEFAULT_TYPES, capabilities = null, idFactory = () => crypto.randomUUID()) {
  let current = document;
  const edges = [];
  let message = null;
  for (const sourceId of sourceIds || []) {
    if (sourceId === targetId) continue;
    const result = connectNodes(current, sourceId, targetId, types, capabilities, idFactory);
    if (result.ok) { current = result.document; edges.push(result.edge); }
    else if (!message) message = result.message;
  }
  return {document: current, edges, message};
}

export function removeEdge(document, edgeId) {
  const edge = document.edges.find(item => item.id === edgeId);
  if (!edge) return {ok: false, message: '连线不存在', document};
  if (isFixedReferenceEdge(edge, document)) return {ok: false, message: COPY.fixed, document};
  return {ok: true, document: {...document, edges: document.edges.filter(item => item.id !== edgeId)}};
}

export function renameNode(document, nodeId, title) {
  const next = String(title ?? '').trim();
  if (!document.nodes.some(node => node.id === nodeId)) return {ok: false, message: '节点不存在', document};
  if (!next) return {ok: false, message: COPY.titleRequired, document};
  if (next.length > 200) return {ok: false, message: '节点标题最长 200 字', document};
  return {ok: true, title: next, document: {...document, nodes: document.nodes.map(node => node.id === nodeId ? {...node, title: next} : node)}};
}

export function setPrimaryMedia(document, nodeId, mediaId, outputs = []) {
  if (!outputs.some(item => item.media_id === mediaId)) return {ok: false, message: COPY.unknownMedia, document};
  if (!document.nodes.some(node => node.id === nodeId)) return {ok: false, message: '节点不存在', document};
  const nodes = document.nodes.map(node => node.id === nodeId ? {...node, media_id: mediaId, params: {...(node.params || {}), primary_media_id: mediaId}} : node);
  return {ok: true, document: {...document, nodes}};
}

export function batchReassign(document, fromId, toId, edgeIds = null, types = DEFAULT_TYPES, capabilities = null) {
  const from = document.nodes.find(node => node.id === fromId);
  const to = document.nodes.find(node => node.id === toId);
  if (!from || !to) return {ok: false, message: COPY.batchFailed, document};
  if (from.type !== to.type) return {ok: false, message: COPY.batchType, document};
  const outgoing = document.edges.filter(edge => edge.source === fromId);
  if (!outgoing.length) return {ok: false, message: COPY.batchNone, document};
  if (edgeIds && (edgeIds.length !== outgoing.length || outgoing.some(edge => !edgeIds.includes(edge.id)))) return {ok: false, message: COPY.batchStale, document};
  if (outgoing.some(edge => isFixedReferenceEdge(edge, document))) return {ok: false, message: COPY.batchFixed, document};
  for (const edge of outgoing) {
    const downstream = document.nodes.find(node => node.id === edge.target);
    if (!downstream || edge.target === toId) return {ok: false, message: COPY.batchUnsupported, document};
    const slot = slotsFor(downstream, types, capabilities).find(item => item.handle === edge.port);
    if (!slot || !slot.accept.includes(to.type)) return {ok: false, message: COPY.batchUnsupported, document};
    if (document.edges.some(item => item.id !== edge.id && item.source === toId && item.target === edge.target)) return {ok: false, message: COPY.batchDuplicate, document};
    if (reaches(document, edge.target, toId, edge.id)) return {ok: false, message: COPY.batchFailed, document};
  }
  return {ok: true, document: {...document, edges: document.edges.map(edge => edge.source === fromId ? {...edge, source: toId} : edge)}};
}

export function isEmptyPortrait(node) {
  return Boolean(node && ['image', 'video', 'audio'].includes(node.type) && !node.media_id && !subkind(node));
}

export function recommendationsFor(node) {
  if (!node || subkind(node) || node.params?.collapsed === true) return [];
  if (node.type === 'image' && !node.media_id) return [{id: 'image-to-image', label: COPY.imageToImage}];
  if (node.type === 'video' && !node.media_id) return [{id: 'head-tail', label: COPY.headTail}, {id: 'first-frame', label: COPY.firstFrame}];
  if (node.type === 'audio') return [{id: 'audio-to-video', label: COPY.audioToVideo}];
  if (node.type === 'text' && !String(node.text || '').trim()) return [
    {id: 'manual', label: COPY.manual},
    {id: 'text-to-video', label: COPY.textToVideo},
    {id: 'image-reverse-prompt', label: COPY.reverse},
    {id: 'text-to-audio', label: COPY.textToAudio},
  ];
  return [];
}

function blankNode(id, type, title, x, y, extra = {}) {
  return {id, type, title, x, y, text: extra.text || '', params: extra.params || {}, media_id: null, job_id: null, group: extra.group || ''};
}

export function applyRecommendation(document, nodeId, action, idFactory = () => crypto.randomUUID()) {
  const source = document.nodes.find(node => node.id === nodeId);
  if (!source) return {ok: false, message: '节点不存在', document};
  if (!recommendationsFor(source).some(item => item.id === action)) return {ok: false, message: COPY.unknownAction, document};
  const next = clone(document);
  const node = next.nodes.find(item => item.id === nodeId);
  const place = (type, title, x, extra) => {
    if (next.nodes.length >= MAX_NODES) return null;
    const created = blankNode(idFactory(), type, title, x, node.y, extra);
    next.nodes.push(created);
    return created;
  };
  const link = (fromId, toId, port) => next.edges.push({id: idFactory(), source: fromId, target: toId, port});
  if (action === 'manual') {
    node.params = {...(node.params || {}), recommendation: 'manual'};
    return {ok: true, document: next, selected: [nodeId]};
  }
  if (action === 'head-tail' || action === 'first-frame') {
    node.params = {...(node.params || {}), vsc_operation: action === 'head-tail' ? 'head_tail_video' : 'single_image_video'};
    return {ok: true, document: next, selected: [nodeId]};
  }
  if (action === 'image-to-image') {
    const created = place('image', '图片', node.x + 300, {params: {vsc_operation: 'image_generate'}});
    if (!created) return {ok: false, message: COPY.maxNodes, document};
    link(node.id, created.id, 'reference');
    return {ok: true, document: next, selected: [created.id]};
  }
  if (action === 'text-to-video') {
    node.text = COPY.textToVideoText;
    const created = place('video', '视频', node.x + 300, {text: COPY.textToVideoPrompt, params: {vsc_operation: 'text_video'}, group: COPY.textToVideoGroup});
    if (!created) return {ok: false, message: COPY.maxNodes, document};
    link(node.id, created.id, 'prompt');
    return {ok: true, document: next, selected: [created.id]};
  }
  if (action === 'text-to-audio') {
    node.text = COPY.textToAudioText;
    const created = place('audio', '音频', node.x + 300, {params: {vsc_operation: 'audio_generate'}, group: COPY.textToAudioGroup});
    if (!created) return {ok: false, message: COPY.maxNodes, document};
    link(node.id, created.id, 'prompt');
    return {ok: true, document: next, selected: [created.id]};
  }
  if (action === 'image-reverse-prompt') {
    node.text = COPY.reverseText;
    node.group = COPY.reverseGroup;
    node.params = {...(node.params || {}), vsc_operation: 'image_reverse_prompt'};
    const created = place('image', COPY.reverseImage, node.x - 300, {});
    if (!created) return {ok: false, message: COPY.maxNodes, document};
    return {ok: true, document: next, selected: [nodeId]};
  }
  if (action === 'audio-to-video') {
    const created = place('video', '视频', node.x + 300, {params: {vsc_operation: 'seedance_omni_video'}});
    if (!created) return {ok: false, message: COPY.maxNodes, document};
    link(node.id, created.id, 'reference_audio');
    return {ok: true, document: next, selected: [created.id]};
  }
  return {ok: false, message: COPY.unknownAction, document};
}

function clampSize(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.max(min, Math.min(max, Math.round(number)));
}

export function nodeSize(node) {
  const width = clampSize(node?.params?.card_w, MIN_W, MAX_W);
  const height = clampSize(node?.params?.card_h, MIN_H, MAX_H);
  if (node?.params?.collapsed === true) return {w: width || 220, h: 36};
  if (isEmptyPortrait(node)) return {w: width || 220, h: height || 300};
  return {w: width || 240, h: height || 134};
}

export function nodeEdgePath(from, to, ox = 0, oy = 0) {
  const start = nodeSize(from), end = nodeSize(to);
  const x1 = from.x + ox + start.w, y1 = from.y + oy + start.h / 2;
  const x2 = to.x + ox, y2 = to.y + oy + end.h / 2;
  const bend = Math.max(40, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

function crc32(bytes) {
  let value = ~0;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ (0xedb88320 & -(value & 1));
  }
  return ~value >>> 0;
}

const u16 = number => Uint8Array.of(number & 255, (number >> 8) & 255);
const u32 = number => Uint8Array.of(number & 255, (number >> 8) & 255, (number >> 16) & 255, (number >>> 24) & 255);
function concat(parts) {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { out.set(part, offset); offset += part.length; }
  return out;
}

export function zipTimestamp(date) {
  const pad = number => String(number).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

export function zipFileName(date = new Date()) {
  return `画布节点_${zipTimestamp(date)}.zip`;
}

const MEDIA_EXTENSION = Object.freeze({
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/jpg': '.jpg',
  'image/webp': '.webp',
  'image/gif': '.gif',
  'video/mp4': '.mp4',
  'audio/mpeg': '.mp3',
  'audio/mp3': '.mp3',
  'audio/wav': '.wav',
  'audio/wave': '.wav',
  'audio/x-wav': '.wav',
});

function textEntry(node) {
  return {name: `${node.type}-${node.id}.txt`, text: `${node.title}\n${node.type}\n${node.text || ''}\n`};
}

function mediaExtension(contentType) {
  const mime = String(contentType || '').split(';')[0].trim().toLowerCase();
  return MEDIA_EXTENSION[mime] || '';
}

function headerValue(headers, name) {
  if (!headers) return '';
  const titled = name.replace(/(^|-)([a-z])/g, (_, dash, letter) => dash + letter.toUpperCase());
  const names = [...new Set([name, name.toLowerCase(), titled])];
  if (typeof headers.get === 'function') {
    for (const item of names) {
      const value = headers.get(item);
      if (value) return value;
    }
    return '';
  }
  for (const item of names) if (headers[item]) return headers[item];
  return '';
}

async function selectionEntry(node, api) {
  const summary = textEntry(node);
  if (node?.type === 'text' || !node?.media_id || !['image', 'video', 'audio'].includes(node.type)) return summary;
  const root = typeof api?.base === 'function' ? api.base() : '';
  if (!root) return summary;
  try {
    // Already-stored project media. This does not call a generation API.
    const response = await globalThis.fetch(`${root}/media/${encodeURIComponent(node.media_id)}/content`, {credentials: 'same-origin'});
    if (!response?.ok) return summary;
    const extension = mediaExtension(headerValue(response.headers, 'content-type'));
    if (!extension) return summary;
    const data = new Uint8Array(await response.arrayBuffer());
    return {name: `${node.type}-${node.id}${extension}`, data};
  } catch {
    return summary;
  }
}

export function buildStoredZip(entries, date = new Date()) {
  const encoder = new TextEncoder();
  const files = Array.isArray(entries) ? entries : [];
  const now = date instanceof Date ? date : new Date();
  const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
  const dosDate = ((Math.max(now.getFullYear(), 1980) - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const file of files) {
    const name = encoder.encode(String(file.name).replace(/[\\/]/g, '_'));
    const data = typeof file.data === 'string' || file.data == null ? encoder.encode(file.text ?? file.data ?? '') : file.data;
    const crc = crc32(data);
    const local = concat([
      Uint8Array.of(0x50, 0x4b, 0x03, 0x04), u16(20), u16(0x0800), u16(0), u16(dosTime), u16(dosDate),
      u32(crc), u32(data.length), u32(data.length), u16(name.length), u16(0), name, data,
    ]);
    const central = concat([
      Uint8Array.of(0x50, 0x4b, 0x01, 0x02), u16(20), u16(20), u16(0x0800), u16(0), u16(dosTime), u16(dosDate),
      u32(crc), u32(data.length), u32(data.length), u16(name.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(offset), name,
    ]);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const centralDir = concat(centrals.length ? centrals : [new Uint8Array()]);
  const end = concat([
    Uint8Array.of(0x50, 0x4b, 0x05, 0x06), u16(0), u16(0), u16(centrals.length), u16(centrals.length),
    u32(centralDir.length), u32(offset), u16(0),
  ]);
  return concat([...locals, centralDir, end]);
}

function primaryLabel(type) {
  if (type === 'video') return COPY.primaryVideo;
  if (type === 'audio') return COPY.primaryAudio;
  return COPY.primaryImage;
}

function countLabel(type, count) {
  if (type === 'video') return `${count}个`;
  if (type === 'audio') return `${count}首`;
  return `${count}张`;
}

function svg(name, attrs, children = []) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  for (const child of children) node.append(child);
  return node;
}

function placeholderIcon(type) {
  const common = {fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round'};
  if (type === 'video') return svg('svg', {viewBox: '0 0 48 48', 'aria-hidden': 'true'}, [
    svg('rect', {...common, x: '8', y: '12', width: '32', height: '24', rx: '4'}),
    svg('path', {...common, d: 'M22 20l8 4-8 4z', fill: 'currentColor', stroke: 'none'}),
  ]);
  if (type === 'audio') return svg('svg', {viewBox: '0 0 48 48', 'aria-hidden': 'true'}, [
    svg('path', {...common, d: 'M20 30V16l14-3v14'}),
    svg('circle', {...common, cx: '16', cy: '30', r: '4'}),
    svg('circle', {...common, cx: '30', cy: '27', r: '4'}),
  ]);
  if (type === 'text') return svg('svg', {viewBox: '0 0 48 48', 'aria-hidden': 'true'}, [
    svg('path', {...common, d: 'M14 16h20M14 24h20M14 32h12'}),
  ]);
  return svg('svg', {viewBox: '0 0 48 48', 'aria-hidden': 'true'}, [
    svg('rect', {...common, x: '10', y: '12', width: '28', height: '24', rx: '4'}),
    svg('path', {...common, d: 'M24 18v12M18 24h12'}),
  ]);
}

function worldPoint(s, event) {
  const rect = s.stage?.getBoundingClientRect?.() || {left: 0, top: 0};
  const zoom = s.document.viewport?.zoom || 1;
  return {
    x: ((event.clientX || 0) - rect.left + (s.stage?.scrollLeft || 0)) / zoom,
    y: ((event.clientY || 0) - rect.top + (s.stage?.scrollTop || 0)) / zoom,
  };
}

function resolveNode(s, event) {
  const card = event?.target?.closest?.('.cc-node');
  const id = card?.dataset?.nodeId;
  return id ? s.document.nodes.find(node => node.id === id) || null : null;
}

async function capabilitiesFor(s, api) {
  if (s.a1Caps) return s.a1Caps;
  if (!api.loadRunOptions) return null;
  try {
    const options = await api.loadRunOptions(s);
    if (!api.live || api.live(s) !== false) s.a1Caps = options;
    return s.a1Caps || options;
  } catch { return null; }
}

async function finishOnNode(s, api, source, target) {
  const capabilities = await capabilitiesFor(s, api);
  if (api.live && api.live(s) === false) return;
  const result = connectNodes(s.document, source.id, target.id, api.TYPES, capabilities);
  if (!result.ok) { api.notice(s, result.message); return; }
  api.change(s, () => { s.document.edges = result.document.edges; });
}

async function finishBatch(s, api, target) {
  const capabilities = await capabilitiesFor(s, api);
  if (api.live && api.live(s) === false) return;
  const many = connectMany(s.document, [...s.selected], target.id, api.TYPES, capabilities);
  if (many.edges.length) api.change(s, () => { s.document.edges = many.document.edges; });
  if (many.message) api.notice(s, many.message);
}

function virtualNode(type) {
  return {id: '__a1_new__', type, title: type, x: 0, y: 0, text: '', params: {}, media_id: null, job_id: null, group: ''};
}

function menuRejection(s, api, spec, type) {
  const created = virtualNode(type);
  if (spec.side === 'batch') {
    let message = null;
    let ok = false;
    for (const id of s.selected || []) {
      const source = s.document.nodes.find(node => node.id === id);
      const decision = planConnection(s.document, source, created, api.TYPES, s.a1Caps || null);
      if (decision.ok) ok = true;
      else if (!message) message = decision.message;
    }
    return ok ? null : (message || COPY.targetNot);
  }
  const decision = spec.side === 'in'
    ? planConnection(s.document, created, spec.node, api.TYPES, s.a1Caps || null)
    : planConnection(s.document, spec.node, created, api.TYPES, s.a1Caps || null);
  return decision.ok ? null : decision.message;
}

function commitAdd(s, api, spec, type) {
  if (menuRejection(s, api, spec, type)) { api.notice(s, menuRejection(s, api, spec, type)); return; }
  if (s.document.nodes.length >= MAX_NODES) { api.notice(s, COPY.maxNodes); return; }
  const id = crypto.randomUUID();
  const point = spec.point || (spec.side === 'in' ? {x: spec.node.x - 300, y: spec.node.y} : {x: (spec.node?.x || 0) + 300, y: spec.node?.y || 0});
  const node = blankNode(id, type, api.TYPES[type]?.label || type, point.x, point.y);
  const draft = {...s.document, nodes: [...s.document.nodes, node]};
  if (spec.side === 'batch') {
    const many = connectMany(draft, [...s.selected], id, api.TYPES, s.a1Caps || null);
    if (!many.edges.length) { api.notice(s, many.message || '无法连接'); return; }
    api.change(s, () => { s.document.nodes.push(node); s.document.edges = many.document.edges; s.selected = new Set([id]); });
    if (many.message) api.notice(s, many.message);
    return;
  }
  const sourceId = spec.side === 'in' ? id : spec.node.id;
  const targetId = spec.side === 'in' ? spec.node.id : id;
  const result = connectNodes(draft, sourceId, targetId, api.TYPES, s.a1Caps || null);
  if (!result.ok) { api.notice(s, result.message); return; }
  api.change(s, () => { s.document.nodes.push(node); s.document.edges = result.document.edges; s.selected = new Set([id]); });
}

function openAddMenu(s, api, spec, event) {
  s.root?.querySelector('.a1-menu')?.remove();
  const menu = api.el('div', null, 'a1-menu');
  menu.append(api.el('h3', COPY.addNode));
  menu.style.left = `${Math.max(8, event?.clientX || 96)}px`;
  menu.style.top = `${Math.max(8, event?.clientY || 96)}px`;
  for (const item of ADD_TYPES) {
    const reason = menuRejection(s, api, spec, item.type);
    const button = api.button(s, item.label, () => { menu.remove(); commitAdd(s, api, spec, item.type); });
    button.classList.add('a1-add');
    button.dataset.nodeType = item.type;
    if (item.badge) button.append(api.el('span', item.badge, 'a1-badge'));
    if (reason) { button.disabled = true; api.bindAttribute(button, 'title', reason); }
    menu.append(button);
  }
  s.root.append(menu);
  ensureMenuCloser(s);
}

function ensureMenuCloser(s) {
  if (s.a1MenuCloser) return;
  s.a1MenuCloser = event => {
    if (!event.target?.closest?.('.a1-menu, .a1-port, .a1-batch-connect, .a1-placeholder-hit')) s.root?.querySelector('.a1-menu')?.remove();
  };
  window.addEventListener('pointerdown', s.a1MenuCloser);
}

function openMediaSourceMenu(s, api, node) {
  if (s.readOnly || s.shared || !isEmptyPortrait(node)) return;
  s.root?.querySelector('.a1-menu')?.remove();
  s.selected = new Set([node.id]);
  api.draw?.(s);
  const menu = api.el('div', null, 'a1-menu');
  menu.append(api.el('h3', COPY.addMedia));
  const card = [...(s.world?.querySelectorAll('.cc-node') || [])].find(item => item.dataset.nodeId === node.id);
  const rect = card?.getBoundingClientRect?.() || {left: 96, top: 96};
  menu.style.left = `${Math.max(8, (rect.left || 0) + 70)}px`;
  menu.style.top = `${Math.max(8, (rect.top || 0) + 120)}px`;
  menu.append(api.button(s, COPY.uploadLocal, () => { menu.remove(); return api.uploadResources?.(); }));
  menu.append(api.button(s, COPY.pickProject, () => { menu.remove(); return api.mediaPicker?.(node); }));
  s.root.append(menu);
  ensureMenuCloser(s);
}

function beginDrag(s, api, spec, event, dragged) {
  if (event.button != null && event.button !== 0) return;
  event.stopPropagation?.();
  event.preventDefault?.();
  const startX = event.clientX || 0, startY = event.clientY || 0;
  let dragging = false;
  let preview = null;
  const move = next => {
    if (!dragging && Math.abs((next.clientX || 0) - startX) + Math.abs((next.clientY || 0) - startY) < 5) return;
    dragging = true;
    const svg = s.world?.querySelector('.cc-connections');
    if (!svg) return;
    if (!preview) {
      preview = document.createElementNS(svg.namespaceURI || 'http://www.w3.org/2000/svg', 'path');
      preview.classList.add('a1-preview');
      preview.setAttribute('stroke', '#3ddc97');
      preview.setAttribute('fill', 'none');
      preview.setAttribute('stroke-width', '2');
      svg.append(preview);
    }
    const cursor = worldPoint(s, next);
    const ox = s.displayOffset?.x || 0, oy = s.displayOffset?.y || 0;
    let x1 = cursor.x, y1 = cursor.y;
    if (spec.node) {
      const size = nodeSize(spec.node);
      x1 = spec.side === 'in' ? spec.node.x + ox : spec.node.x + ox + size.w;
      y1 = spec.node.y + oy + size.h / 2;
    }
    preview.setAttribute('d', `M ${x1} ${y1} C ${(x1 + cursor.x) / 2} ${y1}, ${(x1 + cursor.x) / 2} ${cursor.y}, ${cursor.x} ${cursor.y}`);
    api.highlightPorts?.(s, spec, next);
  };
  const up = async next => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    api.clearPortHighlight?.(s);
    preview?.remove();
    if (!dragging) return;
    if (dragged) dragged.value = next.target === event.target || next.target?.closest?.('.a1-port') === event.target;
    const dropped = resolveNode(s, next);
    if (spec.side === 'batch') {
      if (dropped) await finishBatch(s, api, dropped);
      else openAddMenu(s, api, {side: 'batch', point: api.canvasPoint(s, next)}, next);
      return;
    }
    if (dropped && spec.side === 'out' && (event.altKey || event.shiftKey || next.altKey || next.shiftKey)) {
      await api.reassignOutgoing?.(s, spec.node, dropped);
      return;
    }
    if (dropped) {
      const source = spec.side === 'out' ? spec.node : dropped;
      const target = spec.side === 'out' ? dropped : spec.node;
      await finishOnNode(s, api, source, target);
    } else openAddMenu(s, api, {...spec, point: api.canvasPoint(s, next)}, next);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

export function beginRename(s, api, node) {
  if (s.readOnly) return;
  const card = [...(s.world?.querySelectorAll('.cc-node') || [])].find(item => item.dataset.nodeId === node.id);
  const head = card?.querySelector('.cc-node-head');
  if (!card || !head || card.querySelector('.a1-rename')) return;
  const field = api.input('节点标题', node.title);
  field.className = 'a1-rename';
  let done = false;
  const commit = () => {
    if (done) return;
    done = true;
    const result = renameNode(s.document, node.id, field.value);
    if (!result.ok) { api.notice(s, result.message); api.draw(s); return; }
    api.change(s, () => { const live = s.document.nodes.find(item => item.id === node.id); if (live) live.title = result.title; });
  };
  field.addEventListener('pointerdown', event => event.stopPropagation());
  field.addEventListener('click', event => event.stopPropagation());
  field.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); commit(); }
    if (event.key === 'Escape') { event.preventDefault(); done = true; api.draw(s); }
  });
  field.addEventListener('blur', commit);
  head.parentElement.insertBefore(field, head);
  head.remove();
  card.classList.add('a1-renaming');
  field.focus?.();
}

function bindPort(s, api, node, side) {
  const dragged = {value: false};
  const port = api.button(s, '＋', () => {
    if (dragged.value) { dragged.value = false; return; }
    const size = nodeSize(node);
    const point = side === 'in' ? {x: node.x - 300, y: node.y} : {x: node.x + size.w + 48, y: node.y};
    openAddMenu(s, api, {side, node, point}, {clientX: 120, clientY: 140});
  });
  port.className = `a1-port a1-port-${side === 'in' ? 'left' : 'right'}`;
  api.bindAttribute(port, 'aria-label', side === 'in' ? COPY.quickLeft : COPY.quickRight);
  port.addEventListener('pointerdown', event => beginDrag(s, api, {side, node}, event, dragged));
  return port;
}

async function downloadSelection(s, api) {
  const nodes = s.document.nodes.filter(node => s.selected?.has(node.id));
  if (!nodes.length) { api.notice(s, COPY.noSelected); return; }
  const entries = [];
  for (const node of nodes) entries.push(await selectionEntry(node, api));
  const now = new Date();
  const bytes = buildStoredZip(entries);
  const name = zipFileName(now);
  if (typeof URL === 'undefined' || !URL.createObjectURL) return {name, bytes};
  const blob = new Blob([bytes], {type: 'application/zip'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', name);
  link.className = 'a1-zip-link';
  s.root.append(link);
  link.click?.();
  link.remove();
  URL.revokeObjectURL?.(url);
  return {name, bytes};
}

function openReassign(s, api, node) {
  const outgoing = s.document.edges.filter(edge => edge.source === node.id);
  if (!outgoing.length) { api.notice(s, COPY.batchNone); return; }
  const menu = api.el('div', null, 'a1-menu');
  menu.append(api.el('h3', COPY.reassign));
  menu.style.left = '120px';
  menu.style.top = '160px';
  const candidates = s.document.nodes.filter(item => item.id !== node.id && item.type === node.type);
  if (!candidates.length) menu.append(api.el('p', COPY.batchType));
  for (const candidate of candidates) {
    menu.append(api.button(s, candidate.title, () => {
      menu.remove();
      const result = batchReassign(s.document, node.id, candidate.id, outgoing.map(edge => edge.id), api.TYPES, s.a1Caps || null);
      if (!result.ok) { api.notice(s, result.message); return; }
      api.change(s, () => { s.document.edges = result.document.edges; });
    }));
  }
  s.root.append(menu);
}

export function mountNodeCard(s, node, card, api) {
  const writable = !s.readOnly && !s.shared;
  const size = nodeSize(node);
  card.classList.add('a1-card', `a1-type-${node.type}`);
  if (node.params?.collapsed === true) card.classList.add('a1-collapsed');
  if (isEmptyPortrait(node)) card.classList.add('a1-portrait');
  card.style.width = `${size.w}px`;
  card.style.minHeight = `${size.h}px`;
  const emptyText = node.type === 'text' && !String(node.text || '').trim() && !subkind(node);
  const showPlaceholder = !node.params?.collapsed && (isEmptyPortrait(node) || (emptyText && !(s.selected?.size === 1 && s.selected.has(node.id))));
  if (showPlaceholder) {
    const holder = api.el('div', null, 'a1-placeholder');
    const icon = placeholderIcon(node.type);
    if (writable && isEmptyPortrait(node)) {
      const hit = api.button(s, '', () => openMediaSourceMenu(s, api, node));
      hit.className = 'a1-placeholder-hit';
      api.bindAttribute(hit, 'aria-label', COPY.placeholderHit);
      hit.addEventListener('pointerdown', event => event.stopPropagation());
      hit.addEventListener('click', event => event.stopPropagation());
      hit.append(icon);
      holder.append(hit);
    } else holder.append(icon);
    card.append(holder);
  }
  if (writable) card.append(bindPort(s, api, node, 'in'), bindPort(s, api, node, 'out'));
  const items = writable ? recommendationsFor(node) : [];
  if (items.length) {
    const row = api.el('div', null, 'a1-try');
    row.append(api.el('span', COPY.try, 'a1-try-label'));
    for (const item of items) {
      const chip = api.button(s, item.label, () => {
        const result = applyRecommendation(s.document, node.id, item.id);
        if (!result.ok) { api.notice(s, result.message); return; }
        api.change(s, () => {
          s.document.nodes = result.document.nodes;
          s.document.edges = result.document.edges;
          if (result.selected) s.selected = new Set(result.selected);
        });
      });
      chip.classList.add('a1-try-chip');
      chip.prepend(svg('svg', {viewBox: '0 0 12 12', 'aria-hidden': 'true', class: 'a1-try-icon'}, [svg('path', {d: 'M2 8l4-4 4 4', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4'})]));
      row.append(chip);
    }
    const inline = card.querySelector('.cc-text-inline-box');
    if (inline) card.insertBefore(row, inline);
    else card.append(row);
  }
  if (node.params?.recommendation === 'manual') {
    const area = card.querySelector('.cc-inline-textarea');
    if (area && !String(node.text || '').trim()) api.bindAttribute(area, 'placeholder', COPY.manualPlaceholder);
  }
  const outputs = (s.jobs?.[node.id]?.id === node.job_id ? s.jobs[node.id]?.outputs : []) || [];
  if (outputs.length > 1) {
    const index = Math.max(0, outputs.findIndex(item => item.media_id === node.media_id));
    const pager = api.el('div', null, 'a1-pager');
    const previous = api.button(s, '上一结果', () => api.change(s, () => { node.media_id = outputs[(index + outputs.length - 1) % outputs.length].media_id; }));
    const next = api.button(s, '下一结果', () => api.change(s, () => { node.media_id = outputs[(index + 1) % outputs.length].media_id; }));
    previous.disabled = next.disabled = Boolean(s.readOnly || s.shared);
    pager.append(previous, api.el('span', `${index + 1}/${outputs.length}`), api.el('span', countLabel(node.type, outputs.length), 'a1-count'), next);
    card.append(pager);
  }
  const more = api.el('details', null, 'a1-more');
  const summary = api.el('summary', '···');
  api.bindAttribute(summary, 'aria-label', '更多操作');
  more.append(summary);
  more.addEventListener('click', event => event.stopPropagation());
  more.addEventListener('pointerdown', event => event.stopPropagation());
  const menu = api.el('div', null, 'a1-more-menu');
  if (writable && !api.DOMAIN_TYPES.has(node.type)) menu.append(api.button(s, COPY.operate, () => api.operationPanel(s, node)));
  if (!s.readOnly) {
    menu.append(api.button(s, COPY.rename, () => beginRename(s, api, node)));
    menu.append(api.button(s, node.params?.collapsed === true ? COPY.expand : COPY.collapse, () => api.change(s, () => { node.params = {...(node.params || {}), collapsed: node.params?.collapsed !== true}; })));
    if (writable && s.document.edges.some(edge => edge.source === node.id)) menu.append(api.button(s, COPY.reassign, () => openReassign(s, api, node)));
  }
  if (outputs.length > 1 && !s.readOnly) {
    const current = outputs[Math.max(0, outputs.findIndex(item => item.media_id === node.media_id))];
    menu.append(api.button(s, primaryLabel(node.type), () => {
      const result = setPrimaryMedia(s.document, node.id, current.media_id, outputs);
      if (!result.ok) { api.notice(s, result.message); return; }
      api.change(s, () => { s.document.nodes = result.document.nodes; });
    }));
  }
  if (menu.childNodes?.length || menu.children?.length) { more.append(menu); card.append(more); }
  if (writable && node.type === 'text' && !subkind(node) && node.params?.collapsed !== true) {
    const handle = api.button(s, '', () => {});
    handle.className = 'a1-resize';
    api.bindAttribute(handle, 'aria-label', COPY.resize);
    handle.addEventListener('pointerdown', event => {
      if (event.button != null && event.button !== 0) return;
      event.stopPropagation();
      event.preventDefault?.();
      const startX = event.clientX || 0, startY = event.clientY || 0;
      const zoom = s.document.viewport?.zoom || 1;
      const origin = nodeSize(node);
      let width = origin.w, height = origin.h, moved = false;
      const move = next => {
        moved = true;
        width = Math.max(MIN_W, Math.min(MAX_W, Math.round(origin.w + ((next.clientX || 0) - startX) / zoom)));
        height = Math.max(MIN_H, Math.min(MAX_H, Math.round(origin.h + ((next.clientY || 0) - startY) / zoom)));
        card.style.width = `${width}px`;
        card.style.minHeight = `${height}px`;
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        if (!moved) return;
        api.change(s, () => { node.params = {...(node.params || {}), card_w: width, card_h: height}; });
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    card.append(handle);
  }
  const head = card.querySelector('.cc-node-head');
  head?.addEventListener('click', () => {
    const now = Date.now();
    const previous = s.a1TitleTap;
    if (previous && previous.id === node.id && now - previous.at < 450) { s.a1TitleTap = null; beginRename(s, api, node); }
    else s.a1TitleTap = {id: node.id, at: now};
  });
  card.addEventListener('dblclick', event => { if (event.target?.closest?.('.cc-node-head')) beginRename(s, api, node); });
}

export function mountSelectionConnect(s, api) {
  s.root?.querySelector('.a1-menu')?.remove();
  const svg = s.world?.querySelector('.cc-connections');
  if (svg && !s.readOnly) {
    for (const line of svg.querySelectorAll('path')) {
      const id = line.getAttribute('data-edge-id');
      if (!id || line.classList.contains('a1-preview')) continue;
      line.addEventListener('click', event => {
        event.stopPropagation();
        const edge = s.document.edges.find(item => item.id === id);
        if (!edge) return;
        const result = removeEdge(s.document, edge.id);
        if (!result.ok) { api.notice(s, result.message); return; }
        api.change(s, () => { s.document.edges = result.document.edges; });
      });
    }
  }
  if (s.readOnly || s.shared || (s.selected?.size || 0) < 2) return;
  const selected = s.document.nodes.filter(node => s.selected.has(node.id));
  if (!selected.length) return;
  let minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const ox = s.displayOffset?.x || 0, oy = s.displayOffset?.y || 0;
  for (const node of selected) {
    const size = nodeSize(node);
    minY = Math.min(minY, node.y);
    maxX = Math.max(maxX, node.x + size.w);
    maxY = Math.max(maxY, node.y + size.h);
  }
  const batch = api.button(s, '＋', () => {});
  batch.className = 'a1-batch-connect';
  api.bindAttribute(batch, 'aria-label', COPY.batchConnect);
  batch.style.left = `${maxX + ox + 16}px`;
  batch.style.top = `${(minY + maxY) / 2 + oy}px`;
  batch.addEventListener('pointerdown', event => { event.stopPropagation(); beginDrag(s, api, {side: 'batch'}, event, {value: false}); });
  const zip = api.button(s, COPY.zip, () => downloadSelection(s, api));
  zip.className = 'a1-zip';
  zip.style.left = `${maxX + ox + 16}px`;
  zip.style.top = `${(minY + maxY) / 2 + oy - 36}px`;
  s.world.append(batch, zip);
}
