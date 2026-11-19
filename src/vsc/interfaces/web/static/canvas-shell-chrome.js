// Canvas detail chrome: plain selectors, sync/share/agent overlay, bottom toolbar, arrange confirm, shortcuts.
import {msg, setText, bindAttribute, joinMessages} from './i18n.js';
import {
  REFERENCE_LAYOUT,
  SHORTCUT_CATALOG,
  VSC_CANVAS_SHORTCUTS,
  arrangeNodes,
  createCanvasShortcuts,
  activateControl,
  uploadsIncomplete,
  leaveReason,
} from './canvas-shortcuts.js';

const SYNC_LABELS = {
  synced: 'canvas.collab.synced',
  syncing: 'canvas.collab.syncing',
  reconnecting: 'canvas.collab.reconnecting',
  offline: 'canvas.collab.offline',
  readonly: 'canvas.collab.readonly',
  failed: 'canvas.collab.failed',
};
const SYNC_TITLES = {
  synced: 'canvas.collab.sync_tooltip_synced',
  syncing: 'canvas.collab.sync_tooltip_syncing',
  reconnecting: 'canvas.collab.sync_tooltip_reconnecting',
  offline: 'canvas.collab.sync_tooltip_offline',
  readonly: 'canvas.collab.sync_tooltip_readonly',
  failed: 'canvas.collab.sync_tooltip_failed',
};
const SYNC_PREFIX = {synced: '● ', syncing: '↻ ', reconnecting: '● ', offline: '● ', readonly: '🔒 ', failed: '● '};
const LEAVE_KEYS = {
  upload: 'canvas.shell.upload_incomplete_leave_message',
  draft: 'canvas.shell.draft_leave_message',
  unprotected: 'canvas.shell.unprotected_leave',
};
const ZOOM_STEPS = [0.5, 1, 2, 4, 8];

function listen(target, type, fn, options) {
  if (!target || typeof target.addEventListener !== 'function') return () => {};
  target.addEventListener(type, fn, options);
  return () => {
    if (typeof target.removeEventListener === 'function') target.removeEventListener(type, fn, options);
  };
}

function emit(node, type) {
  if (!node) return;
  if (typeof node.dispatchEvent === 'function' && typeof MouseEvent === 'function') {
    node.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true}));
    return;
  }
  const event = {target: node, preventDefault() {}, stopPropagation() {}};
  for (const fn of node.listeners?.[type] || []) fn(event);
}

function byLabel(nodes, label) {
  return [...nodes].find(node => node.getAttribute?.('aria-label') === label) || null;
}

function svgIcon(path, size = '16') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const shape = document.createElementNS(svg.namespaceURI, 'path');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  shape.setAttribute('d', path);
  shape.setAttribute('fill', 'none');
  shape.setAttribute('stroke', 'currentColor');
  shape.setAttribute('stroke-width', '1.6');
  shape.setAttribute('stroke-linecap', 'round');
  shape.setAttribute('stroke-linejoin', 'round');
  svg.append(shape);
  return svg;
}

function icon(button, path) {
  button.replaceChildren(svgIcon(path));
}

function pageOrigin() {
  if (location?.origin && location.origin !== 'null') return location.origin;
  if (location?.protocol && location?.host) return `${location.protocol}//${location.host}`;
  try { return new URL(location.href).origin; } catch { return ''; }
}

const SHARE_ICON = 'M14 5h5v5M19 5l-9 9M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4';
const COPY_ICON = 'M8 8h11v11H8zM5 16H4a1 1 0 0 1-1-1V4h11v1';

function paintSync(pill, stateName) {
  const name = SYNC_LABELS[stateName] ? stateName : 'synced';
  pill.dataset.state = name;
  pill.setAttribute('data-state', name);
  setText(pill, '');
  const dot = document.createElement('span');
  dot.className = 'cc-collab-dot';
  setText(dot, SYNC_PREFIX[name]);
  const label = document.createElement('span');
  setText(label, msg(SYNC_LABELS[name]));
  pill.append(dot, label);
  bindAttribute(pill, 'title', msg(SYNC_TITLES[name]));
}

export function mountCanvasShellChrome(s, api) {
  const unlisten = [];
  let disposed = false;
  s.root.classList.add('cc-shell-chrome');
  const production = typeof document.getElementById === 'function' ? document.getElementById('production-context') : null;
  production?.classList.add('cc-shell-selectors');

  const zoom = s.root.querySelector('.cc-zoom');
  zoom?.classList.add('cc-shell-toolbar');
  const more = s.root.querySelector('.cc-more-menu');
  const toolbar = s.root.querySelector('.cc-toolbar');
  const zoomButtons = zoom ? [...zoom.querySelectorAll('button')] : [];
  const minimapBtn = byLabel(zoomButtons, String(msg('ui.canvas_minimap')));
  const zoomOut = byLabel(zoomButtons, '缩小画布');
  const zoomIn = byLabel(zoomButtons, '放大画布');
  const undoBtn = byLabel(zoomButtons, '撤销');
  const redoBtn = byLabel(zoomButtons, '重做');
  const snapBtn = zoom?.querySelector('.cc-snap-toggle');
  const edgeBtn = zoom?.querySelector('.cc-edge-toggle');
  const arrangeBtn = zoom?.querySelector('.cc-autolayout-btn');
  const preset = s.root.querySelector('.cc-zoom-preset');
  const output = zoom?.querySelector('output');
  const editMenu = zoom?.querySelector('.cc-edit-menu');

  if (minimapBtn) {
    minimapBtn.classList.add('cc-shell-minimap');
    bindAttribute(minimapBtn, 'aria-label', msg('canvas.shell.minimap'));
    bindAttribute(minimapBtn, 'title', msg('canvas.shell.minimap'));
    icon(minimapBtn, 'M4 5h16v14H4zM8 9h4v4H8z');
    minimapBtn.setAttribute('aria-pressed', String(s.minimap ? !s.minimap.hidden : false));
    unlisten.push(listen(minimapBtn, 'click', () => {
      minimapBtn.setAttribute('aria-pressed', String(s.minimap ? !s.minimap.hidden : false));
    }));
  }
  if (snapBtn) {
    bindAttribute(snapBtn, 'aria-label', msg('canvas.shell.snap_to_grid'));
    bindAttribute(snapBtn, 'title', msg('canvas.shell.snap_to_grid'));
    icon(snapBtn, 'M4 8h16M4 16h16M8 4v16M16 4v16');
  }
  if (edgeBtn) {
    bindAttribute(edgeBtn, 'aria-label', msg('canvas.shell.hide_edges'));
    bindAttribute(edgeBtn, 'title', msg('canvas.shell.hide_edges_guide'));
    icon(edgeBtn, 'M5 12h14M7 8c2 2 8 2 10 0M7 16c2-2 8-2 10 0');
    edgeBtn.setAttribute('aria-pressed', String(Boolean(s.hideEdges)));
    unlisten.push(listen(edgeBtn, 'click', () => {
      edgeBtn.setAttribute('aria-pressed', String(Boolean(s.hideEdges)));
      bindAttribute(edgeBtn, 'aria-label', msg(s.hideEdges ? 'canvas.shell.show_edges' : 'canvas.shell.hide_edges'));
    }));
  }
  if (zoomOut) {
    bindAttribute(zoomOut, 'aria-label', msg('canvas.shell.zoom_out'));
    bindAttribute(zoomOut, 'title', msg('canvas.shell.zoom_out'));
  }
  if (zoomIn) {
    bindAttribute(zoomIn, 'aria-label', msg('canvas.shell.zoom_in'));
    bindAttribute(zoomIn, 'title', msg('canvas.shell.zoom_in'));
  }
  if (arrangeBtn) {
    arrangeBtn.classList.add('cc-shell-arrange');
    bindAttribute(arrangeBtn, 'aria-label', msg('canvas.shell.arrange_canvas'));
    bindAttribute(arrangeBtn, 'title', msg('canvas.shell.arrange_canvas'));
    icon(arrangeBtn, 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z');
  }
  if (output) {
    output.classList.add('cc-shell-zoom-readout');
    bindAttribute(output, 'aria-label', msg('canvas.shell.open_zoom_menu'));
    bindAttribute(output, 'title', msg('canvas.shell.open_zoom_menu'));
  }

  const zoomMenu = document.createElement('div');
  zoomMenu.className = 'cc-shell-zoom-menu';
  zoomMenu.hidden = true;
  if (preset) zoomMenu.append(preset);
  for (const step of ZOOM_STEPS) {
    const choice = document.createElement('button');
    choice.type = 'button';
    choice.className = 'cc-shell-zoom-step';
    setText(choice, msg('canvas.shell.zoom_to', {percent: String(Math.round(step * 100))}));
    choice.addEventListener('click', () => {
      setZoom(step);
      zoomMenu.hidden = true;
    });
    zoomMenu.append(choice);
  }
  const fitChoice = document.createElement('button');
  fitChoice.type = 'button';
  fitChoice.className = 'cc-shell-zoom-fit';
  setText(fitChoice, msg('canvas.shell.fit_view'));
  fitChoice.addEventListener('click', () => {
    api.fit();
    zoomMenu.hidden = true;
  });
  zoomMenu.append(fitChoice);
  if (zoom) {
    for (const node of [minimapBtn, snapBtn, edgeBtn, zoomOut, output, zoomIn, arrangeBtn]) if (node) zoom.append(node);
    zoom.append(zoomMenu);
  }
  if (output) {
    unlisten.push(listen(output, 'click', () => {
      zoomMenu.hidden = !zoomMenu.hidden;
    }));
  }
  if (more) {
    for (const node of [undoBtn, redoBtn, editMenu]) if (node) more.append(node);
    if (s.versionLabel) {
      s.versionLabel.classList.add('cc-shell-version');
      more.append(s.versionLabel);
    }
    if (s.saveButton) {
      s.saveButton.classList.add('cc-shell-save-hidden');
      more.append(s.saveButton);
    }
    const returnBtn = document.createElement('button');
    returnBtn.type = 'button';
    returnBtn.className = 'cc-shell-return-node';
    setText(returnBtn, msg('canvas.shell.return_to_node'));
    returnBtn.addEventListener('click', () => returnToNode());
    const shortcutBtn = document.createElement('button');
    shortcutBtn.type = 'button';
    shortcutBtn.className = 'cc-shell-shortcuts-open';
    setText(shortcutBtn, msg('canvas.shell.shortcuts'));
    shortcutBtn.addEventListener('click', () => openShortcutPanel());
    more.append(returnBtn, shortcutBtn);
  }

  for (const legacy of [...s.root.querySelectorAll('button')]) {
    if (legacy.textContent.trim() === '分享此画布' && !legacy.classList.contains('cc-share-home-btn')) legacy.remove();
  }
  const cluster = document.createElement('div');
  cluster.className = 'cc-shell-overlay';
  const bar = s.root.querySelector('.cc-collab-bar');
  const pill = s.root.querySelector('.cc-collab-sync-pill') || createFallbackPill();
  const agent = s.root.querySelector('.cc-agent-toggle');
  const moreDetails = s.root.querySelector('.cc-more');
  const share = createShareButton();
  cluster.append(...[bar, pill, share, agent, moreDetails].filter(Boolean));
  (toolbar || s.root).append(cluster);
  globalThis.VSC_CANVAS_SHORTCUTS = VSC_CANVAS_SHORTCUTS;

  const empty = s.root.querySelector('.cc-empty');
  if (empty && !empty.classList.contains('cc-mv-guide')) {
    const description = empty.querySelector('p');
    if (description) setText(description, msg('canvas.shell.empty_canvas_description'));
  }
  mountCanvasMenu();

  function rangeInput() {
    return [...s.root.querySelectorAll('input')].find(node => node.type === 'range') || null;
  }
  function setZoom(next) {
    const clamped = Math.max(.1, Math.min(8, Math.round(Number(next) * 10) / 10));
    s.document.viewport.zoom = clamped;
    const range = rangeInput();
    if (range) range.value = String(clamped);
    if (s.zoomOutput) setText(s.zoomOutput, joinMessages([Math.round(clamped * 100), '%']));
    api.edited();
    api.drawWorld();
  }
  function createFallbackPill() {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cc-collab-sync-pill cc-shell-sync-fallback';
    paintSync(button, s.readOnly ? 'readonly' : 'synced');
    return button;
  }
  function shareHref() {
    const id = encodeURIComponent(s.id);
    const project = encodeURIComponent(s.project);
    const episode = s.episode ? '&episode_id=' + encodeURIComponent(s.episode) : '';
    return `${pageOrigin()}/canvas/share/${id}?project_id=${project}&canvas_id=${id}${episode}`;
  }
  function labeledControl(tag, className, labelKey, path) {
    const node = document.createElement(tag);
    if (tag === 'button') node.type = 'button';
    node.className = className;
    const label = document.createElement('span');
    setText(label, msg(labelKey));
    if (path) node.append(svgIcon(path, '14'), label);
    else node.append(label);
    return node;
  }
  async function writeClipboard(value, field) {
    try {
      const write = navigator.clipboard?.writeText;
      if (typeof write === 'function') {
        await write.call(navigator.clipboard, value);
        return true;
      }
    } catch { /* fall through to the selection copy path */ }
    try {
      field?.focus?.();
      field?.select?.();
      if (typeof document.execCommand === 'function' && document.execCommand('copy')) return true;
    } catch { /* try an offscreen field next */ }
    try {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      s.root.append(area);
      area.focus?.();
      area.select?.();
      const copied = typeof document.execCommand === 'function' && document.execCommand('copy');
      area.remove();
      if (copied) return true;
    } catch { /* the notice below reports the failure */ }
    return false;
  }
  function openShareDialog() {
    let dialog = s.root.querySelector('.cc-shell-share-dialog');
    if (dialog) {
      if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
      return dialog;
    }
    const href = shareHref();
    dialog = document.createElement('dialog');
    dialog.className = 'cc-shell-share-dialog';
    bindAttribute(dialog, 'aria-label', msg('canvas.shell.share_canvas'));
    const head = document.createElement('div');
    head.className = 'cc-shell-share-head';
    const heading = document.createElement('h2');
    setText(heading, msg('canvas.shell.share_canvas'));
    const close = labeledControl('button', 'cc-shell-share-close', 'canvas.shell.close');
    setText(close, '×');
    bindAttribute(close, 'aria-label', msg('canvas.shell.close'));
    close.addEventListener('click', () => dialog.close());
    head.append(heading, close);
    const row = document.createElement('div');
    row.className = 'cc-shell-share-row';
    const field = document.createElement('input');
    field.type = 'text';
    field.className = 'cc-shell-share-link';
    field.readOnly = true;
    field.setAttribute('readonly', '');
    field.value = href;
    bindAttribute(field, 'aria-label', msg('canvas.shell.share_link'));
    const copy = labeledControl('button', 'cc-shell-share-copy', 'canvas.shell.copy_link', COPY_ICON);
    copy.addEventListener('click', async () => {
      const copied = await writeClipboard(field.value, field);
      api.notice(msg(copied ? 'canvas.shell.share_copied' : 'canvas.shell.share_copy_failed'));
    });
    row.append(field, copy);
    dialog.append(head, row);
    if (typeof api.navigateAccess === 'function') {
      const access = labeledControl('button', 'cc-shell-share-access', 'canvas.shell.share_permissions');
      access.addEventListener('click', () => {
        if (typeof dialog.close === 'function') dialog.close();
        else dialog.remove();
        api.navigateAccess({area: 'share', project: s.project, canvas: s.id});
      });
      dialog.append(access);
    }
    dialog.addEventListener('close', () => dialog.remove());
    s.root.append(dialog);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    return dialog;
  }
  function createShareButton() {
    const button = labeledControl('button', 'cc-shell-share', 'canvas.shell.share', SHARE_ICON);
    bindAttribute(button, 'aria-label', msg('canvas.shell.share'));
    button.addEventListener('click', async () => {
      try {
        if ((s.dirty || s.pending) && !await api.save?.()) return;
        openShareDialog();
      } catch (error) {
        api.notice(error?.message || String(error));
      }
    });
    return button;
  }
  function noteEdit() {
    const fallback = s.root.querySelector('.cc-shell-sync-fallback');
    if (!fallback || s.readOnly) return;
    paintSync(fallback, 'syncing');
  }
  function noteSaved() {
    const fallback = s.root.querySelector('.cc-shell-sync-fallback');
    if (!fallback) return;
    const name = s.readOnly ? 'readonly' : s.syncBlocked ? 'failed' : s.dirty ? 'syncing' : 'synced';
    paintSync(fallback, name);
  }
  function snapshotPositions() {
    return s.document.nodes.map(node => ({id: node.id, x: node.x, y: node.y}));
  }
  function applyPositions(records) {
    const byId = new Map(records.map(record => [record.id, record]));
    for (const node of s.document.nodes) {
      const next = byId.get(node.id);
      if (!next) continue;
      node.x = next.x;
      node.y = next.y;
    }
  }
  function closeArrangeDialog() {
    const dialog = s.shellArrangeDialog;
    s.shellArrangeDialog = null;
    if (dialog && typeof dialog.close === 'function' && dialog.open !== false) dialog.close();
    else dialog?.remove?.();
  }
  function finishArrange(keep) {
    const snapshot = s.shellArrangeSnapshot;
    const arranged = snapshotPositions();
    if (!keep) {
      if (snapshot) applyPositions(snapshot);
      s.shellArrange = false;
      s.shellArrangeSnapshot = null;
      closeArrangeDialog();
      api.draw();
      return;
    }
    if (snapshot) applyPositions(snapshot);
    api.checkpoint();
    applyPositions(arranged);
    s.shellArrange = false;
    s.shellArrangeSnapshot = null;
    closeArrangeDialog();
    api.edited();
    api.draw();
  }
  function arrange() {
    if (s.readOnly) return false;
    if (s.shellArrange) return true;
    const snapshot = snapshotPositions();
    const result = arrangeNodes(s.document.nodes, REFERENCE_LAYOUT.defaultStrategy);
    applyPositions(result.positions);
    s.shellArrange = true;
    s.shellArrangeSnapshot = snapshot;
    api.drawWorld();
    const dialog = document.createElement('dialog');
    dialog.className = 'cc-shell-arrange-dialog';
    const copy = document.createElement('p');
    setText(copy, msg('canvas.shell.arrange_keep_confirm'));
    const revert = document.createElement('button');
    revert.type = 'button';
    revert.className = 'cc-shell-arrange-revert';
    setText(revert, msg('canvas.shell.arrange_revert'));
    const keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'cc-shell-arrange-keep';
    setText(keep, msg('canvas.shell.arrange_keep'));
    revert.addEventListener('click', () => finishArrange(false));
    keep.addEventListener('click', () => finishArrange(true));
    dialog.append(copy, revert, keep);
    dialog.addEventListener('close', () => dialog.remove());
    s.root.append(dialog);
    s.shellArrangeDialog = dialog;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    return true;
  }
  function returnToNode() {
    const node = s.document.nodes.find(item => s.selected.has(item.id)) || s.document.nodes[0];
    if (!node) return false;
    api.focusNode(node);
    return true;
  }
  function openShortcutPanel() {
    const existing = s.root.querySelector('.cc-shell-shortcuts');
    if (existing) {
      if (typeof existing.showModal === 'function' && !existing.open) existing.showModal();
      return existing;
    }
    const dialog = document.createElement('dialog');
    dialog.className = 'cc-shell-shortcuts';
    bindAttribute(dialog, 'aria-label', msg('canvas.shell.shortcuts'));
    const heading = document.createElement('h2');
    setText(heading, msg('canvas.shell.shortcuts'));
    const close = document.createElement('button');
    close.type = 'button';
    setText(close, msg('common.cancel'));
    close.addEventListener('click', () => dialog.close());
    dialog.append(heading, close);
    for (const group of SHORTCUT_CATALOG) {
      const section = document.createElement('section');
      const title = document.createElement('h3');
      setText(title, msg(group.groupKey));
      section.append(title);
      for (const entry of group.items) {
        const row = document.createElement('p');
        const name = document.createElement('span');
        setText(name, msg(entry.labelKey));
        const chord = document.createElement('kbd');
        setText(chord, entry.chord);
        row.append(name, chord);
        section.append(row);
      }
      dialog.append(section);
    }
    dialog.addEventListener('close', () => dialog.remove());
    s.root.append(dialog);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    return dialog;
  }
  function openSearch() {
    let dialog = s.root.querySelector('.cc-node-search');
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'cc-node-search';
      const field = document.createElement('input');
      field.type = 'search';
      field.className = 'cc-node-search-input';
      bindAttribute(field, 'aria-label', msg('canvas.shortcuts.search'));
      bindAttribute(field, 'placeholder', msg('canvas.shortcuts.search'));
      const list = document.createElement('div');
      list.className = 'cc-node-search-list';
      const paint = () => {
        const query = field.value.trim().toLocaleLowerCase();
        list.replaceChildren();
        const matches = s.document.nodes.filter(node => !query || String(node.title || '').toLocaleLowerCase().includes(query) || String(node.text || '').toLocaleLowerCase().includes(query));
        for (const node of matches) {
          const choice = document.createElement('button');
          choice.type = 'button';
          setText(choice, node.title || node.type);
          choice.addEventListener('click', () => {
            api.focusNode(node);
            dialog.close();
          });
          list.append(choice);
        }
      };
      field.addEventListener('input', paint);
      field.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          event.preventDefault();
          dialog.close();
        }
      });
      dialog.append(field, list);
      dialog.addEventListener('close', () => dialog.remove());
      s.root.append(dialog);
      paint();
    }
    if (typeof dialog.showModal === 'function') dialog.showModal();
    dialog.querySelector('input')?.focus?.();
  }
  function mountCanvasMenu() {
    const selector = s.selector;
    const menu = selector?.querySelector('.cc-selector-menu');
    if (!menu || menu.querySelector('.cc-shell-canvas-actions')) return;
    selector.classList.add('cc-shell-selector');
    const actions = document.createElement('div');
    actions.className = 'cc-shell-canvas-actions';
    const create = document.createElement('button');
    create.type = 'button';
    create.className = 'cc-shell-new-canvas';
    setText(create, msg('canvas.shell.create_canvas'));
    const rename = document.createElement('button');
    rename.type = 'button';
    rename.className = 'cc-shell-rename-canvas';
    setText(rename, msg('canvas.shell.rename_canvas'));
    const summary = selector.querySelector('summary');
    const add = byLabel(selector.querySelectorAll('button'), String(msg('ui.new_canvas')));
    create.addEventListener('click', () => {
      selector.open = false;
      activateControl(add);
    });
    rename.addEventListener('click', () => {
      selector.open = false;
      emit(summary, 'dblclick');
    });
    actions.append(create, rename);
    menu.append(actions);
  }
  function leaveMessage() {
    const reason = leaveReason({
      uploadIncomplete: uploadsIncomplete(s.uploads),
      arrangePending: Boolean(s.shellArrange),
      dirty: Boolean(s.dirty),
      pending: Boolean(s.pending),
      syncBlocked: Boolean(s.syncBlocked),
    });
    return reason ? String(msg(LEAVE_KEYS[reason])) : '';
  }
  function onWindowKey(event) {
    if (event.vscShellHandled) return;
    if (s.shellShortcuts?.handle(event)) event.vscShellHandled = true;
  }
  function onWindowKeyUp(event) {
    if (event.key === ' ' || event.code === 'Space') s.spaceHeld = false;
  }
  function onWheel(event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    event.preventDefault?.();
    const current = Number(s.document.viewport.zoom) || 1;
    setZoom(current + (event.deltaY > 0 ? -0.1 : 0.1));
  }
  function onDocumentClick(event) {
    const link = event.target?.closest?.('a');
    if (!link || link.target === '_blank') return;
    const message = leaveMessage();
    if (!message || typeof window.confirm !== 'function') return;
    if (!window.confirm(message)) event.preventDefault?.();
  }
  function onBeforeUnload(event) {
    const message = leaveMessage();
    if (!message) return;
    event.preventDefault?.();
    event.returnValue = message;
  }

  const shortcuts = createCanvasShortcuts(s, {
    checkpoint: api.checkpoint,
    edited: api.edited,
    draw: api.draw,
    duplicate: api.duplicate,
    undo: api.undo,
    fit: api.fit,
    arrange,
    setMode(next) {
      s.pointerMode = next;
      if (s.stage) s.stage.style.cursor = next === 'pan' ? 'grab' : '';
      const mouseMenu = s.root.querySelector('.cc-mouse-menu');
      if (mouseMenu) mouseMenu.hidden = true;
    },
    openSearch,
    notice: api.notice,
    newId: api.newId,
  });
  const controller = {
    arrange,
    leaveMessage,
    noteEdit,
    noteSaved,
    openSearch,
    returnToNode,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (s.shellArrange) finishArrange(false);
      for (const stop of unlisten) stop();
      production?.classList.remove('cc-shell-selectors');
      s.root.classList.remove('cc-shell-chrome');
      if (s.shellShortcuts === shortcuts) s.shellShortcuts = null;
      if (s.shellChrome === controller) s.shellChrome = null;
    },
  };
  s.shellShortcuts = shortcuts;
  s.shellChrome = controller;
  unlisten.push(listen(window, 'keydown', onWindowKey));
  unlisten.push(listen(window, 'keyup', onWindowKeyUp));
  unlisten.push(listen(window, 'beforeunload', onBeforeUnload));
  unlisten.push(listen(s.stage, 'wheel', onWheel, {passive: false}));
  unlisten.push(listen(document, 'click', onDocumentClick));
  return controller;
}
