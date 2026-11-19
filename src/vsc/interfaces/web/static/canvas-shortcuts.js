// Canvas shell shortcuts and the reference layout profile.
// The profile numbers are the capabilities.json layout contract, not the
// downloaded elk arrange path and not the local 4-column grid.
import {msg} from './i18n.js';

export const REFERENCE_LAYOUT = Object.freeze({
  profileId: 'agent-stage-assets@1',
  horizontalGap: 320,
  verticalGap: 120,
  columns: 6,
  cardGap: 40,
  rowGap: 60,
  padding: 40,
  groupGap: 120,
  kinds: Object.freeze(['character', 'scene', 'prop', 'blocking', 'audio']),
  strategies: Object.freeze(['vertical', 'asset_region', 'explicit']),
  defaultStrategy: 'asset_region',
});

const PORT_ACCEPT = Object.freeze({
  text: Object.freeze({}),
  image: Object.freeze({prompt: 'text', reference: 'image'}),
  video: Object.freeze({prompt: 'text', first_frame: 'image', last_frame: 'image', reference_image: 'image', reference_video: 'video', reference_audio: 'audio'}),
  audio: Object.freeze({prompt: 'text', reference_audio: 'audio'}),
  spatial: Object.freeze({prompt: 'text', reference: 'image'}),
  director: Object.freeze({prompt: 'text', reference: 'image'}),
  edit: Object.freeze({visual: Object.freeze(['image', 'video']), sound: 'audio'}),
  music_mix: Object.freeze({source_video: 'video', sound: 'audio', prompt: 'text'}),
  processing: Object.freeze({source_video: 'video', prompt: 'text'}),
});

export const SHORTCUT_CATALOG = Object.freeze([
  Object.freeze({
    groupKey: 'canvas.shortcuts.group_create',
    items: Object.freeze([
      item('canvas.shortcuts.group', 'G'),
      item('canvas.shortcuts.merge_storyboard', '⌥G'),
      item('canvas.shortcuts.ungroup', '⇧G'),
      item('canvas.shortcuts.connect', 'L'),
      item('canvas.shortcuts.duplicate', 'D'),
      item('canvas.shortcuts.generate', 'Enter'),
      item('canvas.shortcuts.add', 'Tab'),
      item('canvas.shortcuts.drag_copy', 'Option+拖动'),
      item('canvas.shortcuts.drag_duplicate', 'Option+拖动'),
    ]),
  }),
  Object.freeze({
    groupKey: 'canvas.shortcuts.group_zoom',
    items: Object.freeze([
      item('canvas.shell.zoom_in', '＋'),
      item('canvas.shell.zoom_out', '−'),
      item('canvas.shortcuts.fit_view', '0'),
      item('canvas.shortcuts.pinch', '⌃捏合'),
      item('canvas.shortcuts.scroll_zoom', '⌃滚轮'),
    ]),
  }),
  Object.freeze({
    groupKey: 'canvas.shortcuts.group_pan',
    items: Object.freeze([
      item('canvas.shortcuts.space_pan', 'Space'),
      item('canvas.shortcuts.mouse_pan', '中键'),
    ]),
  }),
  Object.freeze({
    groupKey: 'canvas.shortcuts.group_move',
    items: Object.freeze([
      item('canvas.shortcuts.select', 'V'),
      item('canvas.shortcuts.pan', 'H'),
      item('canvas.shortcuts.organize', '⌥⇧F'),
    ]),
  }),
  Object.freeze({
    groupKey: 'canvas.shortcuts.group_other',
    items: Object.freeze([
      item('canvas.shortcuts.undo', '⌘Z / Ctrl+Z'),
      item('canvas.shortcuts.redo', '⌘⇧Z / Ctrl+Shift+Z'),
      item('canvas.shortcuts.search', 'F'),
      item('canvas.shortcuts.delete', 'Delete / Backspace'),
    ]),
  }),
]);

function item(labelKey, chord) {
  return Object.freeze({labelKey, chord});
}

function shortcutKeys(parts) {
  return Object.freeze(parts.map(part => Object.freeze({...part})));
}

function shortcutEntry(id, label, keys) {
  return Object.freeze({id, label, keys: shortcutKeys(keys)});
}

function shortcutGroup(id, title, items) {
  return Object.freeze({id, title, items: Object.freeze(items)});
}

// Shared with the left-drawer shortcut panel. Keycaps match shortcutAction,
// not the reference site's extra command modifiers.
export const VSC_CANVAS_SHORTCUTS = Object.freeze([
  shortcutGroup('creation', '创作', [
    shortcutEntry('group', '成组', [{text: 'G'}]),
    shortcutEntry('merge-storyboard', '合并分镜组', [{text: '⌥'}, {text: 'G'}]),
    shortcutEntry('ungroup', '解组', [{text: '⇧'}, {text: 'G'}]),
    shortcutEntry('connect', '连线', [{text: 'L'}]),
    shortcutEntry('duplicate', '复制节点和连线', [{text: 'D'}]),
    shortcutEntry('generate', '生成', [{text: 'Enter'}]),
    shortcutEntry('add', '新建节点', [{text: 'Tab'}]),
    shortcutEntry('drag-copy', '节点复制', [{text: '⌥'}, {symbol: 'drag'}]),
    shortcutEntry('drag-duplicate', '创建副本', [{mod: true}, {text: '⌥'}, {symbol: 'drag'}]),
  ]),
  shortcutGroup('zoom', '缩放', [
    shortcutEntry('fit', '适应画布', [{text: '0'}]),
    shortcutEntry('scroll-zoom', '滚动鼠标滚轮', [{mod: true}, {symbol: 'wheel'}]),
  ]),
  shortcutGroup('pan', '移动画布', [
    shortcutEntry('space-pan', '按住鼠标左键拖动', [{text: 'Space'}]),
    shortcutEntry('mouse-pan', '按住鼠标中键拖动', [{symbol: 'middle'}]),
    shortcutEntry('select', '移动', [{text: 'V'}]),
    shortcutEntry('hand', '抓手工具', [{text: 'H'}]),
    shortcutEntry('arrange', '整理画布', [{text: '⌥'}, {text: '⇧'}, {text: 'F'}]),
  ]),
  shortcutGroup('other', '其他', [
    shortcutEntry('undo', '撤销', [{mod: true}, {text: 'Z'}]),
    shortcutEntry('redo', '重做', [{mod: true}, {text: '⇧'}, {text: 'Z'}]),
    shortcutEntry('search', '画布节点搜索', [{text: 'F'}]),
    shortcutEntry('delete', '删除', [{symbol: 'backspace'}]),
  ]),
]);

globalThis.VSC_CANVAS_SHORTCUTS = VSC_CANVAS_SHORTCUTS;

export function detectPlatform() {
  const nav = globalThis.navigator;
  const probe = String(nav?.platform || nav?.userAgent || '').toLowerCase();
  if (probe.includes('mac') || probe.includes('iphone') || probe.includes('ipad')) return 'mac';
  return 'other';
}

export function isTypingTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  if (typeof target.closest === 'function' && target.closest('input,textarea,select,[contenteditable="true"]')) return true;
  return false;
}

function letterOf(event) {
  const code = String(event.code || '');
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  const key = String(event.key || '').toLowerCase();
  return key.length === 1 && key >= 'a' && key <= 'z' ? key : '';
}

function isZero(event) {
  return event.code === 'Digit0' || event.key === '0';
}

function platformMod(event, platform) {
  return platform === 'mac' ? Boolean(event.metaKey) : Boolean(event.ctrlKey);
}

export function shortcutAction(event, {platform = detectPlatform()} = {}) {
  if (!event || event.isComposing || isTypingTarget(event.target)) return null;
  const letter = letterOf(event);
  const alt = Boolean(event.altKey);
  const shift = Boolean(event.shiftKey);
  const meta = Boolean(event.metaKey);
  const ctrl = Boolean(event.ctrlKey);
  const mod = platformMod(event, platform);
  if (alt && shift && !meta && !ctrl && letter === 'f') return 'arrange';
  if (mod && letter === 'z') return shift ? 'redo' : 'undo';
  if (mod && letter === 'd') return 'duplicate';
  if (mod && isZero(event)) return 'fit';
  if (meta || ctrl) return null;
  if (alt && !shift && letter === 'g') return 'merge-storyboard';
  if (shift && !alt && letter === 'g') return 'ungroup';
  if (alt || shift) return null;
  if (letter === 'g') return 'group';
  if (letter === 'l') return 'connect';
  if (letter === 'd') return 'duplicate';
  if (event.key === 'Enter') return 'generate';
  if (event.key === 'Tab') return 'add-node';
  if (isZero(event)) return 'fit';
  if (letter === 'v') return 'move';
  if (letter === 'h') return 'hand';
  if (letter === 'f') return 'search';
  if (event.key === 'Delete' || event.key === 'Backspace') return 'delete';
  if (event.key === ' ' || event.code === 'Space') return 'space';
  return null;
}

export function nodeLayoutKind(node, kinds = REFERENCE_LAYOUT.kinds) {
  const params = node?.params || {};
  if (kinds.includes(params.asset_kind)) return params.asset_kind;
  if (kinds.includes(params.canvas_subkind)) return params.canvas_subkind;
  if (node?.type === 'audio') return 'audio';
  return 'other';
}

export function isExplicitNode(node) {
  const params = node?.params || {};
  return params.layout_strategy === 'explicit' || params.layout === 'explicit';
}

export function isGroupFrame(node) {
  return node?.type === 'text' && node?.params?.canvas_subkind === 'group_frame';
}

function isPinned(node) {
  return isExplicitNode(node) || (isGroupFrame(node) && Boolean(node.params?.group_locked));
}

export function arrangeNodes(nodes, strategy = REFERENCE_LAYOUT.defaultStrategy, profile = REFERENCE_LAYOUT) {
  const strategyName = profile.strategies.includes(strategy) ? strategy : profile.defaultStrategy;
  const positions = nodes.map(node => ({id: node.id, x: node.x, y: node.y}));
  const byId = new Map(positions.map(place => [place.id, place]));
  if (strategyName === 'vertical') {
    let slot = 0;
    for (const node of nodes) {
      if (isPinned(node)) continue;
      const place = byId.get(node.id);
      place.x = profile.padding;
      place.y = profile.padding + slot * profile.verticalGap;
      slot += 1;
    }
  } else if (strategyName === 'asset_region') {
    const groups = new Map(profile.kinds.map(kind => [kind, []]));
    const other = [];
    for (const node of nodes) {
      if (isPinned(node)) continue;
      const kind = nodeLayoutKind(node, profile.kinds);
      if (groups.has(kind)) groups.get(kind).push(node);
      else other.push(node);
    }
    const pitch = profile.rowGap + profile.cardGap;
    let groupTop = profile.padding;
    const placeGroup = members => {
      if (!members.length) return;
      members.forEach((node, index) => {
        const place = byId.get(node.id);
        place.x = profile.padding + (index % profile.columns) * profile.horizontalGap;
        place.y = groupTop + Math.floor(index / profile.columns) * pitch;
      });
      groupTop += Math.ceil(members.length / profile.columns) * pitch + profile.groupGap;
    };
    for (const kind of profile.kinds) placeGroup(groups.get(kind));
    placeGroup(other);
  }
  const moved = positions.some((place, index) => place.x !== nodes[index].x || place.y !== nodes[index].y);
  return {strategy: strategyName, profileId: profile.profileId, positions, moved};
}

function nextGroupName(document, prefix) {
  const used = new Set(document.nodes.map(node => node.group).filter(Boolean));
  let index = 1;
  while (used.has(`${prefix} ${index}`)) index += 1;
  return `${prefix} ${index}`;
}

export function groupSelection(document, selectedIds, idFactory) {
  const members = document.nodes.filter(node => selectedIds.has(node.id) && !isGroupFrame(node));
  if (!members.length || document.nodes.length >= 200) return null;
  const name = nextGroupName(document, '分组');
  for (const node of members) node.group = name;
  const frame = {
    id: idFactory(),
    type: 'text',
    title: name,
    x: Math.min(...members.map(node => node.x)),
    y: Math.min(...members.map(node => node.y)),
    text: '',
    params: {canvas_subkind: 'group_frame', group_color: '#292929', group_locked: false},
    media_id: null,
    job_id: null,
    group: name,
  };
  document.nodes.push(frame);
  return {group: name, frame};
}

export function ungroupSelection(document, selectedIds) {
  const groups = new Set();
  for (const node of document.nodes) {
    if (selectedIds.has(node.id) && node.group) groups.add(node.group);
  }
  if (!groups.size) return false;
  for (const node of document.nodes) {
    if (!isGroupFrame(node) && groups.has(node.group)) node.group = '';
  }
  document.nodes = document.nodes.filter(node => !(isGroupFrame(node) && groups.has(node.group)));
  return true;
}

export function mergeStoryboardSelection(document, selectedIds) {
  const selected = document.nodes.filter(node => selectedIds.has(node.id) && !isGroupFrame(node));
  if (selected.length < 2) return null;
  const name = selected.map(node => node.group).find(Boolean) || nextGroupName(document, '分镜组');
  for (const node of selected) node.group = name;
  return name;
}

export function compatiblePort(sourceType, targetType) {
  const ports = PORT_ACCEPT[targetType] || {};
  for (const [port, accept] of Object.entries(ports)) {
    const kinds = Array.isArray(accept) ? accept : [accept];
    if (kinds.includes(sourceType)) return port;
  }
  return null;
}

export function planConnection(document, selectedIds) {
  const selected = document.nodes.filter(node => selectedIds.has(node.id));
  if (selected.length === 1) return {ok: false, reason: 'arm'};
  if (selected.length < 2) return {ok: false, reason: 'empty'};
  const source = selected[0];
  const target = selected[selected.length - 1];
  const port = compatiblePort(source.type, target.type);
  if (!port) return {ok: false, reason: 'incompatible'};
  if (document.edges.some(edge => edge.source === source.id && edge.target === target.id && edge.port === port)) return {ok: false, reason: 'duplicate'};
  if (document.edges.length >= 800) return {ok: false, reason: 'limit'};
  return {ok: true, source, target, port};
}

export function connectSelection(document, selectedIds, idFactory) {
  const plan = planConnection(document, selectedIds);
  if (!plan.ok) return plan;
  const edge = {id: idFactory(), source: plan.source.id, target: plan.target.id, port: plan.port};
  document.edges.push(edge);
  return {...plan, edge};
}

export function deleteSelection(document, selectedIds) {
  const beforeNodes = document.nodes.length;
  const beforeEdges = document.edges.length;
  document.nodes = document.nodes.filter(node => !selectedIds.has(node.id));
  document.edges = document.edges.filter(edge => !selectedIds.has(edge.source) && !selectedIds.has(edge.target));
  return document.nodes.length !== beforeNodes || document.edges.length !== beforeEdges;
}

export function cloneNodeRecord(document, node, idFactory, {withEdges = false} = {}) {
  if (!document || !node || isGroupFrame(node) || document.nodes.length >= 200) return null;
  const copy = JSON.parse(JSON.stringify(node));
  copy.id = idFactory();
  copy.job_id = null;
  document.nodes.push(copy);
  if (withEdges) {
    const additions = [];
    for (const edge of document.edges) {
      if (document.edges.length + additions.length >= 800) break;
      if (edge.target !== node.id || edge.port === 'derived_from') continue;
      if (['first_frame', 'last_frame'].includes(edge.port) && additions.some(item => item.port === edge.port)) continue;
      additions.push({...JSON.parse(JSON.stringify(edge)), id: idFactory(), target: copy.id});
    }
    document.edges.push(...additions);
  }
  return copy;
}

export function activateControl(node) {
  if (!node) return false;
  if (typeof node.click === 'function') {
    node.click();
    return true;
  }
  const listeners = node.listeners?.click || [];
  const event = {target: node, preventDefault() {}, stopPropagation() {}};
  for (const listener of listeners) listener(event);
  return listeners.length > 0;
}

export function uploadsIncomplete(uploads) {
  for (const upload of uploads || []) {
    const items = upload?.current?.items || [];
    if (items.some(item => item && (item.status === 'awaiting_upload' || item.status === 'uploaded'))) return true;
  }
  return false;
}

export function leaveReason(flags = {}) {
  if (flags.uploadIncomplete) return 'upload';
  if (flags.syncBlocked) return 'unprotected';
  if (flags.arrangePending || flags.dirty || flags.pending) return 'draft';
  return '';
}

function selectedMembers(state) {
  return state.document.nodes.filter(node => state.selected.has(node.id) && !isGroupFrame(node));
}

function commitMutation(state, api, mutate) {
  if (state.readOnly) return false;
  api.checkpoint();
  if (mutate() === false) {
    state.undo?.pop?.();
    return false;
  }
  api.edited();
  api.draw();
  return true;
}

export function createCanvasShortcuts(state, api) {
  const platform = api.platform || detectPlatform();
  function perform(action) {
    if (action === 'duplicate') {
      api.duplicate();
      return true;
    }
    if (action === 'undo' || action === 'redo') {
      api.undo(action === 'redo');
      return true;
    }
    if (action === 'fit') {
      api.fit();
      return true;
    }
    if (action === 'arrange') return Boolean(api.arrange());
    if (action === 'move' || action === 'hand') {
      api.setMode(action === 'hand' ? 'pan' : 'select');
      return true;
    }
    if (action === 'search') {
      api.openSearch();
      return true;
    }
    if (action === 'generate') {
      const root = state.root;
      let custom = null;
      if (typeof CustomEvent === 'function' && typeof root?.dispatchEvent === 'function') {
        custom = new CustomEvent('vsc-canvas-generate', {cancelable: true});
        root.dispatchEvent(custom);
      }
      state.onInlineGenerate?.(custom);
      if (!custom?.defaultPrevented) {
        const send = root?.querySelector?.('[data-canvas-send]') || root?.querySelector?.('.cc-generator-send');
        activateControl(send);
      }
      return true;
    }
    if (state.readOnly) return false;
    if (action === 'add-node') {
      if (state.document.nodes.length >= 200) return false;
      const point = state.createPoint || {x: 100 + state.document.nodes.length % 4 * 280, y: 140 + Math.floor(state.document.nodes.length / 4) * 230};
      state.createPoint = null;
      return commitMutation(state, api, () => {
        const id = api.newId();
        state.document.nodes.push({id, type: 'text', title: '文本', x: point.x, y: point.y, text: '', params: {}, media_id: null, job_id: null, group: ''});
        state.selected = new Set([id]);
      });
    }
    if (action === 'group') {
      if (!selectedMembers(state).length || state.document.nodes.length >= 200) return false;
      return commitMutation(state, api, () => groupSelection(state.document, state.selected, api.newId));
    }
    if (action === 'ungroup') {
      if (![...state.selected].some(id => state.document.nodes.some(node => node.id === id && node.group))) return false;
      return commitMutation(state, api, () => ungroupSelection(state.document, state.selected));
    }
    if (action === 'merge-storyboard') {
      if (selectedMembers(state).length < 2) return false;
      return commitMutation(state, api, () => mergeStoryboardSelection(state.document, state.selected));
    }
    if (action === 'connect') {
      const plan = planConnection(state.document, state.selected);
      if (plan.reason === 'arm') {
        state.connectArmed = true;
        api.notice(msg('canvas.shortcuts.connect_armed'));
        return true;
      }
      if (!plan.ok) return false;
      state.connectArmed = false;
      return commitMutation(state, api, () => connectSelection(state.document, state.selected, api.newId));
    }
    if (action === 'delete') {
      const hit = state.document.nodes.some(node => state.selected.has(node.id));
      if (!hit) return false;
      return commitMutation(state, api, () => {
        deleteSelection(state.document, state.selected);
        state.selected = new Set();
      });
    }
    return false;
  }
  return {
    handle(event) {
      const action = shortcutAction(event, {platform});
      if (!action) return false;
      if (action === 'space') {
        state.spaceHeld = true;
        event.preventDefault?.();
        return true;
      }
      if (event.repeat) {
        event.preventDefault?.();
        return true;
      }
      const done = perform(action);
      if (done) event.preventDefault?.();
      return Boolean(done);
    },
    cloneForAltDrag(node, flags = {}) {
      if (state.readOnly || !node || isGroupFrame(node) || state.document.nodes.length >= 200) return null;
      const withEdges = Boolean(flags.metaKey || flags.ctrlKey);
      api.checkpoint();
      return cloneNodeRecord(state.document, node, api.newId, {withEdges});
    },
  };
}
