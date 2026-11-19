import {getLocale, setText, bindAttribute} from './i18n.js';

const COPY = {
  'zh-cn': {
    'pref.title': '偏好设置',
    'pref.subtitle': '当前用户 · 全局持久生效',
    'pref.font': '提示词字号',
    'pref.default': '默认（14px）',
    'pref.small': '小（12px）',
    'pref.large': '大（16px）',
    'pref.custom': '自定义',
    'pref.range': '请输入10–24之间的整数（px）',
    'pref.collab': '新建画布默认开启协作',
    'pref.collab_hint': '只影响之后新建的画布',
    'pref.watermark': '去AI水印设置',
    'pref.visible': '明水印',
    'pref.hidden': '暗水印',
    'pref.reset': '恢复默认设置',
    'pref.save': '保存设置',
    'pref.saving': '正在保存…',
    'pref.load_failed': '偏好加载失败，请重试',
    'pref.save_failed': '保存未生效，请重试',
    'pref.unconfirmed': '保存结果未确认，请重新读取后核实',
    'pref.saved': '偏好设置已保存',
    'pref.retry': '重试',
    'task.empty': '暂无创作记录',
    'task.need_project': '请先选择项目',
    'task.center': '查看完整任务中心',
    'task.view': '查看',
    'task.id': '任务ID',
    'task.type': '任务类型',
    'task.status': '状态',
    'task.action': '操作',
    'conflict.keep': '保留我的修改',
    'conflict.take': '采用远端版本',
    'conflict.settle': '结算所选',
    'conflict.need_choice': '请为每个冲突节点选择保留我的修改或采用远端版本',
    'conflict.locked': '节点正被其他人编辑，请等待锁释放后重试',
    'conflict.need_remote': '请先刷新远端版本',
    'conflict.receipt': '结算回执',
    'conflict.stage_request': '确认已发送请求',
    'conflict.stage_apply': '回填画布内容',
    'conflict.stage_storage': '结算本地草稿',
    'conflict.stage_sync': '同步服务端状态',
    'conflict.close': '关闭',
    'readonly.takeover': '当前账号已在其他端接管编辑，本页面仅可查看画布',
    'readonly.takeover_action': '在此窗口接管编辑',
    'readonly.offline': '离线只读',
    'readonly.permission': '当前没有编辑权限，仅可查看画布',
    'readonly.collab_off': '协作已关闭，当前仅可查看画布',
    'readonly.refresh': '协作权限已变更，当前仅可查看画布',
    'history.restore': '恢复当时上游拓扑',
    'history.none': '该历史记录不包含拓扑恢复数据',
    'history.restored': '已恢复当时上游拓扑',
    'history.bad_version': '不支持恢复图版本 {version}',
    'history.bad': '历史恢复数据无效',
    'history.dup_node': '历史恢复图存在重复节点 ID',
    'history.dup_edge': '历史恢复图存在重复连线 ID',
    'history.edge_id': '历史恢复连线 ID 为空',
    'history.node_id': '历史节点 ID 为空',
    'history.edge_missing': '历史恢复连线源节点 {key} 不存在',
    'history.not_upstream': '历史恢复连线不属于当前一层拓扑',
    'history.ref_missing': '生成引用节点 {nodeId} 不在一层上游快照中',
    'history.ref_id': '生成引用缺少 nodeId',
    'history.refs': '历史生成引用不是数组',
    'history.type': '{nodeId} 节点类型不支持恢复',
    'history.media': '{nodeId} 引用的媒体不存在',
    'history.limit': '画布最多200个节点',
    'zip.unsafe': '压缩包包含不安全路径',
    'zip.dup': '压缩包包含重复文件名',
    'zip.encrypted': '不支持加密压缩包',
    'zip.descriptor': '暂不支持数据描述符压缩包',
    'zip.method': '不支持的压缩方法',
    'zip.truncated': '压缩包数据被截断',
    'zip.header': '压缩包头不完整',
    'zip.size': '单个文件超过 20MB',
    'zip.total': '压缩包解压后超过 64MB',
    'zip.count': '压缩包文件超过 128 个',
    'zip.crc': '条目校验失败',
    'zip.ratio': '压缩条目超出安全比例',
    'zip.inflate': '解压大小与声明不一致',
    'zip.stored': '存储条目大小不一致',
    'zip.empty': '压缩包里没有可导入的图片、视频、音频或文本',
    'zip.encoding': '文本编码无效',
    'zip.done': '已导入 {count} 个节点',
    'zip.upload': '上传未返回媒体',
    'detail.invalid': 'Detail JSON 架构无效',
    'detail.collab': '协作开启时不能导入 Detail JSON',
    'detail.readonly': '只读画布不能导入 Detail JSON',
    'detail.project': '不能导入其他项目的画布快照',
    'detail.missing': 'Detail JSON 缺少节点或连线',
    'detail.node': '节点 ID 无效',
    'detail.node_dup': '存在重复节点 ID',
    'detail.type': '节点类型无效',
    'detail.edge': '连线 ID 无效',
    'detail.edge_dup': '存在重复连线 ID',
    'detail.dangling': '连线引用了不存在的节点',
    'detail.confirm': '导入将覆盖当前画布：节点 {fromNodes} → {toNodes}，连线 {fromConnections} → {toConnections}。确认覆盖？',
    'detail.exported': '已导出 Detail JSON',
    'detail.imported': '已导入 Detail JSON',
    'detail.save': '请先恢复当前画布保存',
    'menu.preferences': '偏好设置',
    'menu.export': '导出 Detail JSON',
    'menu.import': '导入 Detail JSON',
    'menu.zip': '导入 ZIP',
    'clip.group': '暂不支持复制或粘贴分组节点',
    'clip.busy': '生成或上传中的节点暂不支持复制',
    'clip.corrupt': '剪贴板中的节点数据已损坏',
    'clip.hint': '剪贴板中的节点内容已失效，请重新复制',
    'clip.version': '剪贴板中的节点版本暂不支持',
    'clip.project': '跨项目媒体须先通过共享素材入口导入；本次未粘贴',
    'clip.empty': '剪贴板中没有画布节点',
    'clip.read': '无法读取系统剪贴板',
    'clip.unavailable': '当前浏览器不支持读取系统剪贴板',
    'replace.title': '替换节点媒体',
    'replace.history': '本节点历史',
    'replace.canvas': '本画布媒体',
    'replace.local': '本地上传',
    'replace.confirm': '确认替换',
    'replace.close': '关闭',
    'replace.none_history': '本节点暂无历史媒体',
    'replace.none_canvas': '当前项目暂无可替换的同类型其他素材。',
    'replace.pick': '选择本地文件后确认替换',
    'replace.need': '请选择要替换的媒体',
    'replace.file': '请选择本地文件',
  },
  en: {
    'pref.title': 'Preferences',
    'pref.subtitle': 'Current user · saved for every canvas',
    'pref.font': 'Prompt font size',
    'pref.default': 'Default (14px)',
    'pref.small': 'Small (12px)',
    'pref.large': 'Large (16px)',
    'pref.custom': 'Custom',
    'pref.range': 'Enter an integer from 10 to 24 (px)',
    'pref.collab': 'Enable collaboration on new canvases',
    'pref.collab_hint': 'Applies only to canvases created later',
    'pref.watermark': 'AI watermark',
    'pref.visible': 'Visible watermark',
    'pref.hidden': 'Hidden watermark',
    'pref.reset': 'Restore defaults',
    'pref.save': 'Save settings',
    'pref.saving': 'Saving…',
    'pref.load_failed': 'Could not load preferences. Try again.',
    'pref.save_failed': 'Save did not apply. Try again.',
    'pref.unconfirmed': 'Save was not confirmed. Read the settings again.',
    'pref.saved': 'Preferences saved',
    'pref.retry': 'Retry',
    'task.empty': 'No creation records',
    'task.need_project': 'Open a project first',
    'task.center': 'Open the full task center',
    'task.view': 'View',
    'task.id': 'Task ID',
    'task.type': 'Task type',
    'task.status': 'Status',
    'task.action': 'Action',
    'conflict.keep': 'Keep my edit',
    'conflict.take': 'Use the remote version',
    'conflict.settle': 'Settle selection',
    'conflict.need_choice': 'Choose keep or remote for every conflict',
    'conflict.locked': 'This node is being edited by someone else',
    'conflict.need_remote': 'Refresh the remote version first',
    'conflict.receipt': 'Settlement receipt',
    'conflict.stage_request': 'Request confirmed',
    'conflict.stage_apply': 'Canvas content applied',
    'conflict.stage_storage': 'Local draft settled',
    'conflict.stage_sync': 'Server state synced',
    'conflict.close': 'Close',
    'readonly.takeover': 'This account is editing in another window. This page is view only.',
    'readonly.takeover_action': 'Take over editing in this window',
    'readonly.offline': 'Offline read-only',
    'readonly.permission': 'You can view this canvas but not edit it',
    'readonly.collab_off': 'Collaboration is off. This canvas is view only.',
    'readonly.refresh': 'Collaboration permission changed. This canvas is view only.',
    'history.restore': 'Restore the upstream topology',
    'history.none': 'This history record has no topology to restore',
    'history.restored': 'Upstream topology restored',
    'history.bad_version': 'Unsupported restore graph version {version}',
    'history.bad': 'Restore data is invalid',
    'history.dup_node': 'Duplicate node id in the restore graph',
    'history.dup_edge': 'Duplicate edge id in the restore graph',
    'history.edge_id': 'Restore edge id is empty',
    'history.node_id': 'Restore node id is empty',
    'history.edge_missing': 'Restore edge endpoint {key} is missing',
    'history.not_upstream': 'Restore edge is outside the one-level topology',
    'history.ref_missing': 'Reference {nodeId} is not in the one-level upstream snapshot',
    'history.ref_id': 'Generator reference is missing nodeId',
    'history.refs': 'Generator references are not an array',
    'history.type': 'Node {nodeId} cannot be restored',
    'history.media': 'Media for {nodeId} is missing',
    'history.limit': 'A canvas can hold at most 200 nodes',
    'zip.unsafe': 'The archive contains an unsafe path',
    'zip.dup': 'The archive contains a duplicate file name',
    'zip.encrypted': 'Encrypted archives are not supported',
    'zip.descriptor': 'Data-descriptor archives are not supported',
    'zip.method': 'Unsupported compression method',
    'zip.truncated': 'The archive is truncated',
    'zip.header': 'The archive header is incomplete',
    'zip.size': 'A file exceeds 20MB',
    'zip.total': 'Uncompressed size exceeds 64MB',
    'zip.count': 'The archive has more than 128 files',
    'zip.crc': 'Checksum failed',
    'zip.ratio': 'Compression ratio is not safe',
    'zip.inflate': 'Inflated size does not match the header',
    'zip.stored': 'Stored entry size does not match the header',
    'zip.empty': 'The archive has no image, video, audio, or text to import',
    'zip.encoding': 'Text encoding is invalid',
    'zip.done': 'Imported {count} nodes',
    'zip.upload': 'Upload did not return media',
    'detail.invalid': 'Detail JSON schema is invalid',
    'detail.collab': 'Detail JSON cannot be imported while collaboration is on',
    'detail.readonly': 'A read-only canvas cannot import Detail JSON',
    'detail.project': 'Cannot import a snapshot from another project',
    'detail.missing': 'Detail JSON is missing nodes or connections',
    'detail.node': 'Node id is invalid',
    'detail.node_dup': 'Duplicate node id',
    'detail.type': 'Node type is invalid',
    'detail.edge': 'Connection id is invalid',
    'detail.edge_dup': 'Duplicate connection id',
    'detail.dangling': 'A connection points at a missing node',
    'detail.confirm': 'Import overwrites this canvas: nodes {fromNodes} → {toNodes}, connections {fromConnections} → {toConnections}. Continue?',
    'detail.exported': 'Detail JSON exported',
    'detail.imported': 'Detail JSON imported',
    'detail.save': 'Save the canvas before importing',
    'menu.preferences': 'Preferences',
    'menu.export': 'Export Detail JSON',
    'menu.import': 'Import Detail JSON',
    'menu.zip': 'Import ZIP',
    'clip.group': 'Group frames cannot be copied',
    'clip.busy': 'A node that is uploading or generating cannot be copied',
    'clip.corrupt': 'Clipboard node data is damaged',
    'clip.hint': 'Clipboard contents are not canvas nodes',
    'clip.version': 'This clipboard node version is not supported',
    'clip.project': 'Cross-project media must be imported through shared assets',
    'clip.empty': 'The clipboard has no canvas nodes',
    'clip.read': 'Could not read the system clipboard',
    'clip.unavailable': 'This browser cannot read the system clipboard',
    'replace.title': 'Replace node media',
    'replace.history': 'Node history',
    'replace.canvas': 'Canvas media',
    'replace.local': 'Upload',
    'replace.confirm': 'Confirm replace',
    'replace.close': 'Close',
    'replace.none_history': 'This node has no media history',
    'replace.none_canvas': 'No other media of this type is in the project.',
    'replace.pick': 'Choose a local file, then confirm',
    'replace.need': 'Choose media to use',
    'replace.file': 'Choose a local file',
  },
};

export function label(key, values) {
  const locale = String(getLocale() || '').toLowerCase().startsWith('zh') ? 'zh-cn' : 'en';
  let text = COPY[locale][key] || COPY['zh-cn'][key] || key;
  if (values) for (const [name, value] of Object.entries(values)) text = text.replaceAll('{' + name + '}', String(value));
  return text;
}

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) setText(node, text);
  if (tag === 'button') node.type = 'button';
  return node;
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export function normalizeUserPreferences(raw) {
  const src = raw && typeof raw === 'object' && raw.preferences && typeof raw.preferences === 'object' ? raw.preferences : {};
  const collab = src.collaboration && typeof src.collaboration === 'object' ? src.collaboration : {};
  const ui = src.ui && typeof src.ui === 'object' ? src.ui : {};
  const font = ui.font_size;
  const mark = src.ai_watermark && typeof src.ai_watermark === 'object' ? src.ai_watermark : {};
  return {
    collaboration: {enabled_on_new_canvas: collab.enabled_on_new_canvas === true},
    ui: {font_size: Number.isInteger(font) && font >= 10 && font <= 24 ? font : 14},
    ai_watermark: {visible: mark.visible === false ? false : true},
  };
}

export function preferencesPatch(prefs) {
  return {preferences: {
    collaboration: {enabled_on_new_canvas: prefs.collaboration.enabled_on_new_canvas === true},
    ui: {font_size: prefs.ui.font_size},
    ai_watermark: {visible: prefs.ai_watermark.visible !== false},
  }};
}

export function fontTier(size) {
  if (size === 12) return 'small';
  if (size === 16) return 'large';
  if (size === 14) return 'default';
  return 'custom';
}

export function applyUserAppearance(prefs, root = globalThis.document?.documentElement) {
  if (!root?.dataset || !prefs?.ui) return;
  const size = prefs.ui.font_size;
  root.dataset.vscFontSize = String(size);
  root.style?.setProperty?.('--vsc-prompt-font-size', size + 'px');
  root.dataset.aiWatermark = prefs.ai_watermark?.visible === false ? 'hidden' : 'visible';
}

function samePreferences(left, right) {
  return left.ui.font_size === right.ui.font_size
    && left.ai_watermark.visible === right.ai_watermark.visible
    && left.collaboration.enabled_on_new_canvas === right.collaboration.enabled_on_new_canvas;
}

function readPreferenceForm(dialog) {
  const tier = [...dialog.querySelectorAll('.cpi-font-tier')].find(node => node.getAttribute('aria-pressed') === 'true');
  const which = tier?.dataset?.tier || 'default';
  let font = which === 'small' ? 12 : which === 'large' ? 16 : 14;
  if (which === 'custom') {
    const custom = Number(dialog.querySelector('.cpi-font-custom')?.value);
    if (!Number.isInteger(custom) || custom < 10 || custom > 24) return {error: label('pref.range')};
    font = custom;
  }
  const visible = [...dialog.querySelectorAll('.cpi-mark')].find(node => node.getAttribute('aria-pressed') === 'true')?.dataset?.mark !== 'hidden';
  return {prefs: normalizeUserPreferences({preferences: {
    collaboration: {enabled_on_new_canvas: Boolean(dialog.querySelector('.cpi-collab')?.checked)},
    ui: {font_size: font},
    ai_watermark: {visible},
  }})};
}

function paintPreferenceForm(dialog, prefs) {
  const tier = fontTier(prefs.ui.font_size);
  for (const button of dialog.querySelectorAll('.cpi-font-tier')) button.setAttribute('aria-pressed', String(button.dataset.tier === tier));
  const custom = dialog.querySelector('.cpi-font-custom');
  if (custom) custom.value = String(prefs.ui.font_size);
  const collab = dialog.querySelector('.cpi-collab');
  if (collab) collab.checked = prefs.collaboration.enabled_on_new_canvas;
  for (const button of dialog.querySelectorAll('.cpi-mark')) button.setAttribute('aria-pressed', String(button.dataset.mark === (prefs.ai_watermark.visible ? 'visible' : 'hidden')));
}

export async function openPreferencesDialog({api, root, onSaved} = {}) {
  const dialog = el('dialog', null, 'cpi-preferences');
  bindAttribute(dialog, 'aria-label', label('pref.title'));
  const status = el('p', '', 'cpi-pref-status');
  const body = el('div', null, 'cpi-pref-body');
  dialog.append(el('h2', label('pref.title')), el('p', label('pref.subtitle'), 'cpi-pref-sub'), status, body);
  const host = root || document.body;
  host.append(dialog);
  dialog.showModal?.();
  const load = async () => {
    setText(status, '');
    try {
      const prefs = normalizeUserPreferences(await api('/api/v1/user-preferences'));
      paintPreferences(body, prefs, status, api, onSaved, dialog);
    } catch {
      body.replaceChildren();
      setText(status, label('pref.load_failed'));
      const retry = el('button', label('pref.retry'), 'cpi-pref-retry');
      retry.addEventListener('click', () => load());
      body.append(retry);
    }
  };
  dialog.addEventListener('close', () => dialog.remove());
  await load();
  return dialog;
}

function paintPreferences(body, prefs, status, api, onSaved, dialog) {
  body.replaceChildren();
  const fontField = el('fieldset', null, 'cpi-field');
  fontField.append(el('legend', label('pref.font')));
  const tiers = el('div', null, 'cpi-font-tiers');
  for (const [tier, key] of [['default', 'pref.default'], ['small', 'pref.small'], ['large', 'pref.large'], ['custom', 'pref.custom']]) {
    const button = el('button', label(key), 'cpi-font-tier');
    button.dataset.tier = tier;
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      for (const peer of tiers.querySelectorAll('.cpi-font-tier')) peer.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
    });
    tiers.append(button);
  }
  const custom = document.createElement('input');
  custom.type = 'number';
  custom.min = '10';
  custom.max = '24';
  custom.step = '1';
  custom.className = 'cpi-font-custom';
  bindAttribute(custom, 'aria-label', label('pref.custom'));
  fontField.append(tiers, custom, el('small', label('pref.range')));
  const collabField = el('label', null, 'cpi-field');
  const collab = document.createElement('input');
  collab.type = 'checkbox';
  collab.className = 'cpi-collab';
  const collabText = el('span', label('pref.collab'));
  collabField.append(collab, collabText, el('small', label('pref.collab_hint')));
  const markField = el('fieldset', null, 'cpi-field');
  markField.append(el('legend', label('pref.watermark')));
  const marks = el('div', null, 'cpi-watermark-options');
  for (const [mark, key] of [['visible', 'pref.visible'], ['hidden', 'pref.hidden']]) {
    const button = el('button', label(key), 'cpi-mark');
    button.dataset.mark = mark;
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      for (const peer of marks.querySelectorAll('.cpi-mark')) peer.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
    });
    marks.append(button);
  }
  markField.append(marks);
  const actions = el('div', null, 'cpi-pref-actions');
  const reset = el('button', label('pref.reset'), 'cpi-pref-reset');
  const save = el('button', label('pref.save'), 'cpi-pref-save');
  reset.addEventListener('click', () => paintPreferenceForm(body, normalizeUserPreferences({preferences: {
    collaboration: {enabled_on_new_canvas: false}, ui: {font_size: 14}, ai_watermark: {visible: true},
  }})));
  save.addEventListener('click', async () => {
    const read = readPreferenceForm(body);
    if (read.error) { setText(status, read.error); return; }
    setText(status, label('pref.saving'));
    save.disabled = true;
    try {
      await api('/api/v1/user-preferences', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(preferencesPatch(read.prefs))});
      const again = normalizeUserPreferences(await api('/api/v1/user-preferences'));
      if (!samePreferences(again, read.prefs)) { setText(status, label('pref.unconfirmed')); return; }
      applyUserAppearance(again);
      onSaved?.(again);
      setText(status, label('pref.saved'));
    } catch {
      setText(status, label('pref.save_failed'));
    } finally {
      save.disabled = false;
    }
  });
  actions.append(reset, save);
  body.append(fontField, collabField, markField, actions);
  paintPreferenceForm(body, prefs);
  void dialog;
}

export function normalizeTaskRows(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items.map(item => ({
    id: String(item?.id ?? ''),
    type: item?.presentation?.origin_label || item?.kind || '',
    status: item?.presentation?.state_label || item?.status || '',
    href: item?.href || '',
    title: item?.title || '',
  }));
}

export async function openCreationRecordPopover({anchor, projectId, api, root, onView, onOpenCenter} = {}) {
  const host = root || anchor?.ownerDocument?.body || document.body;
  const existing = host.querySelector?.('.cpi-creation-record');
  if (existing) { existing.remove(); return null; }
  const popover = el('div', null, 'cpi-creation-record');
  popover.setAttribute('role', 'dialog');
  bindAttribute(popover, 'aria-label', label('task.center'));
  const table = document.createElement('table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const key of ['task.id', 'task.type', 'task.status', 'task.action']) headRow.append(el('th', label(key)));
  head.append(headRow);
  const body = document.createElement('tbody');
  table.append(head, body);
  const foot = el('div', null, 'cpi-creation-foot');
  const center = el('button', label('task.center'), 'cpi-task-center');
  center.addEventListener('click', () => { popover.remove(); onOpenCenter?.(); });
  foot.append(center);
  popover.append(table, foot);
  const rect = anchor?.getBoundingClientRect?.();
  if (rect && popover.style) popover.style.top = `${Math.round(rect.bottom + 8)}px`;
  host.append(popover);
  if (!projectId) {
    body.append(messageRow(label('task.need_project')));
    return popover;
  }
  try {
    const payload = await api(`/api/v1/projects/${encodeURIComponent(projectId)}/task-center?limit=8&offset=0`);
    const rows = normalizeTaskRows(payload);
    if (!rows.length) body.append(messageRow(label('task.empty')));
    for (const row of rows) {
      const tr = document.createElement('tr');
      tr.className = 'cpi-task-row';
      tr.append(el('td', row.id), el('td', row.type), el('td', row.status));
      const action = document.createElement('td');
      const view = el('button', label('task.view'), 'cpi-task-view');
      view.addEventListener('click', () => { popover.remove(); onView?.(row); });
      action.append(view);
      tr.append(action);
      body.append(tr);
    }
  } catch (error) {
    body.append(messageRow(error.message || label('task.empty')));
  }
  return popover;
}

function messageRow(text) {
  const tr = document.createElement('tr');
  const td = el('td', text);
  td.colSpan = 4;
  tr.append(td);
  return tr;
}

export function classifyReadonlyReason({kicked = false, kickedReason = '', syncState = 'synced', canEdit = true, collaborationEnabled, permissionReason = ''} = {}) {
  if (kicked || kickedReason === 'same_user_takeover') {
    return {kind: 'takeover', message: label('readonly.takeover'), action: label('readonly.takeover_action')};
  }
  if (syncState === 'offline') return {kind: 'offline', message: label('readonly.offline')};
  if (!canEdit) {
    if (collaborationEnabled === false || permissionReason === 'collaboration_disabled') return {kind: 'permission', message: label('readonly.collab_off')};
    if (permissionReason === 'permission_refresh' || permissionReason === 'permission_refresh_required') return {kind: 'permission', message: label('readonly.refresh')};
    return {kind: 'permission', message: label('readonly.permission')};
  }
  return null;
}

export function paintReadonlyBanner(root, info, onTakeover) {
  if (!root?.querySelector) return null;
  const reason = classifyReadonlyReason(info || {});
  let banner = root.querySelector('.cpi-readonly-banner');
  if (!reason) { banner?.remove(); return null; }
  if (!banner) {
    banner = el('div', null, 'cpi-readonly-banner');
    root.append(banner);
  }
  banner.dataset.kind = reason.kind;
  banner.replaceChildren(el('p', reason.message));
  if (reason.kind === 'takeover') {
    const button = el('button', reason.action, 'cpi-takeover');
    button.addEventListener('click', () => onTakeover?.());
    banner.append(button);
  }
  return banner;
}

export function settleConflictChoices({conflicts, choices, localDocument, remoteDocument} = {}) {
  if (!Array.isArray(conflicts) || !conflicts.length) return {ok: false, message: label('conflict.need_choice')};
  if (!Array.isArray(choices) || choices.length !== conflicts.length || choices.some(choice => choice !== 'mine' && choice !== 'remote')) {
    return {ok: false, message: label('conflict.need_choice')};
  }
  if (!remoteDocument || typeof remoteDocument !== 'object') return {ok: false, message: label('conflict.need_remote')};
  const remote = clone(remoteDocument);
  remote.nodes = Array.isArray(remote.nodes) ? remote.nodes : [];
  remote.edges = Array.isArray(remote.edges) ? remote.edges : [];
  const local = localDocument || {nodes: [], edges: []};
  const receipt = [];
  for (let index = 0; index < conflicts.length; index += 1) {
    const item = conflicts[index] || {};
    const nodeKey = item.node_id ?? item.node_key;
    const choice = choices[index];
    if (item.locked_by_other && choice === 'mine') return {ok: false, message: label('conflict.locked')};
    if (nodeKey === '__canvas__') {
      if (choice === 'mine') {
        receipt.push({node_id: nodeKey, choice, action: 'replace_document', note: '保留我的整张画布'});
        return {ok: true, document: clone(local), title: local.title, receipt};
      }
      receipt.push({node_id: nodeKey, choice, action: 'kept_remote', note: '采用远端版本'});
      continue;
    }
    if (nodeKey === '__canvas_title__') {
      if (choice === 'mine') remote.title = item.local_draft?.title || local.title || remote.title;
      receipt.push({node_id: nodeKey, choice, action: choice === 'mine' ? 'title' : 'kept_remote', note: choice === 'mine' ? '保留本地标题' : '采用远端版本'});
      continue;
    }
    const drafted = item.local_draft && item.local_draft.id === nodeKey ? item.local_draft : null;
    const localNode = (local.nodes || []).find(node => node.id === nodeKey) || drafted;
    const remoteIndex = remote.nodes.findIndex(node => node.id === nodeKey);
    if (choice === 'remote') {
      receipt.push({node_id: nodeKey, choice, action: 'kept_remote', note: '采用远端版本'});
      continue;
    }
    if (!localNode) {
      if (remoteIndex >= 0) remote.nodes.splice(remoteIndex, 1);
      remote.edges = remote.edges.filter(edge => edge.source !== nodeKey && edge.target !== nodeKey);
      receipt.push({node_id: nodeKey, choice, action: 'deleted_local', note: '保留我的删除'});
      continue;
    }
    if (remoteIndex < 0) {
      remote.nodes.push(clone(localNode));
      receipt.push({node_id: nodeKey, choice, action: 'recreated', note: '该节点已被远端删除，继续将恢复该节点并应用你的本地修改，旧连线不会恢复。'});
    } else {
      remote.nodes[remoteIndex] = clone(localNode);
      receipt.push({node_id: nodeKey, choice, action: 'replaced', note: '已用我的修改替换该节点'});
    }
  }
  return {ok: true, document: remote, title: remote.title, receipt};
}

function showReceipt(root, receipt) {
  const dialog = el('dialog', null, 'cpi-receipt-dialog');
  bindAttribute(dialog, 'aria-label', label('conflict.receipt'));
  dialog.append(el('h2', label('conflict.receipt')));
  const stages = document.createElement('ol');
  for (const key of ['conflict.stage_request', 'conflict.stage_apply', 'conflict.stage_storage', 'conflict.stage_sync']) {
    const item = el('li', label(key), 'cpi-stage');
    stages.append(item);
  }
  const notes = document.createElement('ul');
  for (const row of receipt || []) notes.append(el('li', `${row.node_id} · ${row.note}`, 'cpi-receipt-note'));
  const close = el('button', label('conflict.close'), 'cpi-receipt-close');
  close.addEventListener('click', () => dialog.close());
  dialog.append(stages, notes, close);
  dialog.addEventListener('close', () => dialog.remove());
  (root || document.body).append(dialog);
  dialog.showModal?.();
  return dialog;
}

export function augmentConflictDialog(dialog, host = {}) {
  if (!dialog?.querySelectorAll) return dialog;
  const conflicts = host.conflicts || [];
  const choices = new Map();
  const cards = dialog.querySelectorAll('.cc-conflict-item');
  cards.forEach((card, index) => {
    const item = conflicts[index];
    if (!item || card.querySelector('.cpi-keep')) return;
    const locked = Boolean(host.isLocked?.(item));
    const keep = el('button', label('conflict.keep'), 'cpi-keep');
    const take = el('button', label('conflict.take'), 'cpi-take');
    keep.disabled = locked;
    const choose = (value, active, other) => {
      choices.set(index, value);
      card.dataset.choice = value;
      active.setAttribute('aria-pressed', 'true');
      other.setAttribute('aria-pressed', 'false');
    };
    keep.addEventListener('click', () => { if (!keep.disabled) choose('mine', keep, take); });
    take.addEventListener('click', () => choose('remote', take, keep));
    card.append(keep, take);
  });
  const foot = dialog.querySelector('.cc-conflict-footer');
  if (foot && !foot.querySelector('.cpi-settle')) {
    const settle = el('button', label('conflict.settle'), 'cpi-settle');
    settle.addEventListener('click', async () => {
      try {
        const chosen = conflicts.map((_, index) => choices.get(index));
        let remote = host.remoteDocument;
        if (!remote && host.loadRemote) {
          const loaded = await host.loadRemote();
          remote = loaded?.document || loaded;
        }
        const enriched = conflicts.map(item => ({...item, locked_by_other: Boolean(host.isLocked?.(item))}));
        const result = settleConflictChoices({conflicts: enriched, choices: chosen, localDocument: host.localDocument, remoteDocument: remote});
        if (!result.ok) { host.notice?.(result.message); return; }
        const applied = await host.applyMerged?.(result);
        if (applied === false) return;
        showReceipt(host.root, result.receipt);
      } catch (error) {
        host.notice?.(error.message);
      }
    });
    foot.append(settle);
  }
  return dialog;
}

const RESTORABLE = new Set(['text', 'image', 'video', 'audio']);

export function validateHistoryRestore(graph, {knownMediaIds} = {}) {
  if (!graph || typeof graph !== 'object') return {ok: false, message: label('history.none')};
  const version = graph.version ?? graph.graph_version;
  if (version !== 1) return {ok: false, message: label('history.bad_version', {version: version ?? ''})};
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges || graph.connections)) return {ok: false, message: label('history.bad')};
  const edges = graph.edges || graph.connections;
  const ids = new Set();
  for (const node of graph.nodes) {
    if (!node || typeof node !== 'object' || !node.id) return {ok: false, message: label('history.node_id')};
    if (ids.has(node.id)) return {ok: false, message: label('history.dup_node')};
    ids.add(node.id);
    if (!RESTORABLE.has(node.type)) return {ok: false, message: label('history.type', {nodeId: node.id})};
  }
  const generator = graph.nodes.find(node => node.role === 'generator') || graph.nodes.find(node => node.id === graph.generator_id) || graph.nodes[graph.nodes.length - 1];
  if (!generator) return {ok: false, message: label('history.none')};
  const edgeIds = new Set();
  const upstream = new Set();
  for (const edge of edges) {
    if (!edge?.id) return {ok: false, message: label('history.edge_id')};
    if (edgeIds.has(edge.id)) return {ok: false, message: label('history.dup_edge')};
    edgeIds.add(edge.id);
    if (!ids.has(edge.source)) return {ok: false, message: label('history.edge_missing', {key: edge.source})};
    if (!ids.has(edge.target)) return {ok: false, message: label('history.edge_missing', {key: edge.target})};
    if (edge.target !== generator.id || edge.source === generator.id) return {ok: false, message: label('history.not_upstream')};
    upstream.add(edge.source);
  }
  const refs = generator.references || generator.reference_ids || [];
  if (!Array.isArray(refs)) return {ok: false, message: label('history.refs')};
  for (const ref of refs) {
    const nodeId = typeof ref === 'string' ? ref : ref?.nodeId || ref?.node_id;
    if (!nodeId) return {ok: false, message: label('history.ref_id')};
    if (!upstream.has(nodeId)) return {ok: false, message: label('history.ref_missing', {nodeId})};
  }
  if (knownMediaIds) {
    for (const node of graph.nodes) {
      if (node.media_id && !knownMediaIds.has(node.media_id)) return {ok: false, message: label('history.media', {nodeId: node.id})};
    }
  }
  return {ok: true, generatorId: generator.id};
}

export function planTopologyRestore(graph, {nodeCount = 0, newId, knownMediaIds} = {}) {
  const check = validateHistoryRestore(graph, {knownMediaIds});
  if (!check.ok) return check;
  if (nodeCount + graph.nodes.length > 200) return {ok: false, message: label('history.limit')};
  const idOf = newId || (() => crypto.randomUUID());
  const map = new Map();
  const nodes = graph.nodes.map((node, index) => {
    const id = idOf();
    map.set(node.id, id);
    return {
      id, type: node.type, title: node.title || node.type,
      x: Number.isFinite(node.x) ? node.x : 80 + index * 40,
      y: Number.isFinite(node.y) ? node.y : 80,
      text: typeof node.text === 'string' ? node.text : '',
      params: node.params && typeof node.params === 'object' ? {...node.params} : {},
      media_id: node.media_id || null, job_id: null, group: '',
    };
  });
  const edges = (graph.edges || graph.connections).map(edge => ({
    id: idOf(), source: map.get(edge.source), target: map.get(edge.target), port: edge.port || edge.handle || 'prompt',
  }));
  return {ok: true, nodes, edges, generatorId: map.get(check.generatorId)};
}

export function appendHistoryTopologyActions(panel, jobs, host = {}) {
  if (!panel?.querySelectorAll) return;
  const rows = panel.querySelectorAll('article');
  (jobs || []).forEach((job, index) => {
    const row = rows[index];
    if (!row || row.querySelector('.cpi-restore-topology')) return;
    const button = el('button', label('history.restore'), 'cpi-restore-topology');
    button.addEventListener('click', () => {
      const graph = job?.restore_graph || job?.request_payload?.restore_graph || job?.logical_request?.restore_graph || job?.request_payload?.logical_request?.restore_graph;
      if (!graph) { host.notice?.(label('history.none')); return; }
      const plan = planTopologyRestore(graph, {nodeCount: host.nodeCount?.() ?? 0, newId: host.newId, knownMediaIds: host.knownMediaIds});
      if (!plan.ok) { host.notice?.(plan.message); return; }
      host.change?.(() => host.addNodes?.(plan.nodes, plan.edges));
      host.notice?.(label('history.restored'));
    });
    row.append(button);
  });
}

const ZIP_LOCAL = 0x04034b50;
const ZIP_MAX_ENTRIES = 128;
const ZIP_MAX_FILE = 20 * 1024 * 1024;
const ZIP_MAX_TOTAL = 64 * 1024 * 1024;
const ZIP_EXT = {
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', bmp: 'image',
  mp4: 'video', webm: 'video', mov: 'video', m4v: 'video',
  mp3: 'audio', wav: 'audio', m4a: 'audio', aac: 'audio', ogg: 'audio', flac: 'audio',
  txt: 'text', md: 'text', csv: 'text', srt: 'text', lrc: 'text', json: 'text',
};

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc ^= bytes[i];
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (~crc) >>> 0;
}

function unsafeZipName(name) {
  if (!name || /[\u0000-\u001f]/.test(name) || name.includes('\\') || name.includes(':')) return true;
  if (name.startsWith('/') || name.startsWith('\\')) return true;
  return name.split('/').some(part => part === '..' || part === '.');
}

async function inflateRaw(bytes) {
  if (typeof DecompressionStream === 'function') {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const {inflateRawSync} = await import('node:zlib');
  return new Uint8Array(inflateRawSync(bytes));
}

export async function readZipEntries(input) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input || []);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const entries = [];
  const names = new Set();
  let offset = 0;
  let total = 0;
  while (offset + 30 <= bytes.length) {
    if (view.getUint32(offset, true) !== ZIP_LOCAL) break;
    const flags = view.getUint16(offset + 6, true);
    const method = view.getUint16(offset + 8, true);
    const crc = view.getUint32(offset + 14, true);
    const compSize = view.getUint32(offset + 18, true);
    const uncompSize = view.getUint32(offset + 22, true);
    const nameLen = view.getUint16(offset + 26, true);
    const extraLen = view.getUint16(offset + 28, true);
    const nameStart = offset + 30;
    if (nameStart + nameLen + extraLen > bytes.length) return {ok: false, message: label('zip.header')};
    const name = new TextDecoder().decode(bytes.subarray(nameStart, nameStart + nameLen));
    const dataStart = nameStart + nameLen + extraLen;
    if (flags & 1) return {ok: false, message: label('zip.encrypted')};
    if (flags & 8) return {ok: false, message: label('zip.descriptor')};
    if (name.endsWith('/')) { offset = dataStart; continue; }
    if (unsafeZipName(name)) return {ok: false, message: label('zip.unsafe')};
    const key = name.toLowerCase();
    if (names.has(key)) return {ok: false, message: label('zip.dup')};
    names.add(key);
    if (method !== 0 && method !== 8) return {ok: false, message: label('zip.method')};
    if (compSize > ZIP_MAX_FILE || uncompSize > ZIP_MAX_FILE) return {ok: false, message: label('zip.size')};
    if (dataStart + compSize > bytes.length) return {ok: false, message: label('zip.truncated')};
    const compressed = bytes.subarray(dataStart, dataStart + compSize);
    let data;
    if (method === 0) {
      if (uncompSize !== compSize) return {ok: false, message: label('zip.stored')};
      data = compressed.slice();
    } else {
      data = await inflateRaw(compressed);
      if (data.length > compressed.length * 20 && data.length > 1024 * 1024) return {ok: false, message: label('zip.ratio')};
      if (uncompSize && data.length !== uncompSize) return {ok: false, message: label('zip.inflate')};
    }
    if (crc && crc32(data) !== crc) return {ok: false, message: label('zip.crc')};
    if (data.length > ZIP_MAX_FILE) return {ok: false, message: label('zip.size')};
    total += data.length;
    if (total > ZIP_MAX_TOTAL) return {ok: false, message: label('zip.total')};
    entries.push({name, bytes: data});
    if (entries.length > ZIP_MAX_ENTRIES) return {ok: false, message: label('zip.count')};
    offset = dataStart + compSize;
  }
  return {ok: true, entries};
}

export function mediaKindForName(name) {
  const base = String(name || '').split('/').pop() || '';
  const ext = base.includes('.') ? base.split('.').pop().toLowerCase() : '';
  return ZIP_EXT[ext] || '';
}

export function planZipImport(entries, {existingCount = 0} = {}) {
  const items = [];
  const rejected = [];
  for (const entry of entries || []) {
    const kind = mediaKindForName(entry.name);
    if (!kind) { rejected.push({name: entry.name, reason: 'unsupported'}); continue; }
    items.push({name: entry.name, bytes: entry.bytes, kind});
  }
  if (!items.length) return {ok: false, message: label('zip.empty'), rejected};
  if (existingCount + items.length > 200) return {ok: false, message: label('history.limit'), rejected};
  return {ok: true, items, rejected};
}

export function placeZipPlan(items, {newId, originCount = 0} = {}) {
  const idOf = newId || (() => crypto.randomUUID());
  const nodes = [];
  const pendingMedia = [];
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    const id = idOf();
    const x = 100 + ((originCount + index) % 4) * 280;
    const y = 140 + Math.floor((originCount + index) / 4) * 230;
    if (item.kind === 'text') {
      let text = '';
      try { text = new TextDecoder('utf-8', {fatal: true}).decode(item.bytes); }
      catch { return {ok: false, message: label('zip.encoding')}; }
      nodes.push({id, type: 'text', title: item.name, x, y, text, params: {}, media_id: null, job_id: null, group: ''});
    } else {
      nodes.push({id, type: item.kind, title: item.name, x, y, text: '', params: {}, media_id: null, job_id: null, group: ''});
      pendingMedia.push({nodeId: id, name: item.name, kind: item.kind, bytes: item.bytes});
    }
  }
  return {ok: true, nodes, pendingMedia};
}

function mimeFor(kind, name) {
  const ext = mediaKindForName(name) && String(name).split('.').pop().toLowerCase();
  if (kind === 'image') return `image/${ext === 'jpg' ? 'jpeg' : ext || 'png'}`;
  if (kind === 'video') return `video/${ext || 'mp4'}`;
  if (kind === 'audio') return `audio/${ext || 'mpeg'}`;
  return 'application/octet-stream';
}

export async function importZipEntries(entries, host = {}) {
  const plan = planZipImport(entries, {existingCount: host.nodeCount?.() || 0});
  if (!plan.ok) return plan;
  const placed = placeZipPlan(plan.items, {newId: host.newId, originCount: host.nodeCount?.() || 0});
  if (!placed.ok) return placed;
  for (const media of placed.pendingMedia) {
    const file = new File([media.bytes], media.name.split('/').pop(), {type: mimeFor(media.kind, media.name)});
    const mediaId = await host.uploadMedia?.(file, media);
    if (!mediaId) return {ok: false, message: label('zip.upload')};
    const node = placed.nodes.find(item => item.id === media.nodeId);
    if (node) node.media_id = mediaId;
  }
  host.change?.(() => host.addNodes?.(placed.nodes, []));
  return {ok: true, count: placed.nodes.length, nodes: placed.nodes, rejected: plan.rejected};
}

export function buildDetailSnapshot(state = {}) {
  const doc = state.document || {viewport: {x: 0, y: 0, zoom: 1}, nodes: [], edges: []};
  return {
    schema: 'vsc.canvas.detail',
    schema_version: 1,
    project_id: state.projectId || state.project || null,
    canvas_id: state.canvasId || state.id || null,
    title: state.title || '',
    viewport: doc.viewport ? {...doc.viewport} : {x: 0, y: 0, zoom: 1},
    nodes: (doc.nodes || []).map(node => ({...node})),
    connections: (doc.edges || []).map(edge => ({...edge})),
  };
}

export function validateDetailImport(snapshot, options = {}) {
  if (!snapshot || typeof snapshot !== 'object' || snapshot.schema !== 'vsc.canvas.detail' || snapshot.schema_version !== 1) return {ok: false, message: label('detail.invalid')};
  if (options.collaborationEnabled) return {ok: false, message: label('detail.collab')};
  if (options.readOnly) return {ok: false, message: label('detail.readonly')};
  if (options.projectId && snapshot.project_id && snapshot.project_id !== options.projectId) return {ok: false, message: label('detail.project')};
  if (!Array.isArray(snapshot.nodes) || !Array.isArray(snapshot.connections)) return {ok: false, message: label('detail.missing')};
  if (snapshot.nodes.length > 200) return {ok: false, message: label('history.limit')};
  const ids = new Set();
  for (const node of snapshot.nodes) {
    if (!node || typeof node.id !== 'string' || !node.id) return {ok: false, message: label('detail.node')};
    if (ids.has(node.id)) return {ok: false, message: label('detail.node_dup')};
    ids.add(node.id);
    if (typeof node.type !== 'string' || !node.type) return {ok: false, message: label('detail.type')};
  }
  const edgeIds = new Set();
  for (const edge of snapshot.connections) {
    if (!edge || typeof edge.id !== 'string' || !edge.id) return {ok: false, message: label('detail.edge')};
    if (edgeIds.has(edge.id)) return {ok: false, message: label('detail.edge_dup')};
    edgeIds.add(edge.id);
    if (!ids.has(edge.source) || !ids.has(edge.target)) return {ok: false, message: label('detail.dangling')};
  }
  return {ok: true, confirm: {
    fromNodes: options.currentNodes ?? 0,
    toNodes: snapshot.nodes.length,
    fromConnections: options.currentConnections ?? 0,
    toConnections: snapshot.connections.length,
  }};
}

export function commitDetailImport(document, snapshot) {
  return {
    viewport: document?.viewport,
    nodes: snapshot.nodes.map(node => ({...node})),
    edges: snapshot.connections.map(edge => ({id: edge.id, source: edge.source, target: edge.target, port: edge.port || edge.handle || 'prompt'})),
  };
}

export function downloadJson(filename, data) {
  const json = JSON.stringify(data, null, 2);
  if (typeof document === 'undefined' || typeof URL === 'undefined' || !URL.createObjectURL) return json;
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([json], {type: 'application/json'}));
  link.href = url;
  link.download = filename;
  link.click?.();
  URL.revokeObjectURL?.(url);
  return json;
}

export async function importDetailSnapshot(snapshot, host = {}) {
  const doc = host.document?.() || {viewport: {x: 0, y: 0, zoom: 1}, nodes: [], edges: []};
  const check = validateDetailImport(snapshot, {
    collaborationEnabled: Boolean(host.collaborationEnabled?.()),
    readOnly: Boolean(host.readOnly?.()),
    projectId: host.projectId?.(),
    currentNodes: doc.nodes?.length || 0,
    currentConnections: doc.edges?.length || 0,
  });
  if (!check.ok) return check;
  const message = label('detail.confirm', check.confirm);
  const confirmed = host.confirm ? host.confirm(message) : true;
  if (!confirmed) return {ok: false, cancelled: true, message};
  if (host.save && await host.save() === false) return {ok: false, message: label('detail.save')};
  const next = commitDetailImport(doc, snapshot);
  try {
    host.change?.(() => { doc.nodes = next.nodes; doc.edges = next.edges; });
  } catch (error) {
    await host.reload?.();
    return {ok: false, message: error.message, rolledBack: true};
  }
  return {ok: true, viewport: doc.viewport};
}

export function buildNodeClipboard({projectId, canvasId, nodes, edges} = {}) {
  const cleanNodes = (nodes || []).filter(node => node && node.params?.canvas_subkind !== 'group_frame');
  const ids = new Set(cleanNodes.map(node => node.id));
  return {
    canvas_node_clipboard_hint: 1,
    version: 1,
    project_id: projectId,
    project: projectId,
    canvas_id: canvasId || null,
    nodes: cleanNodes,
    edges: (edges || []).filter(edge => ids.has(edge.source) && ids.has(edge.target)),
  };
}

export function validateNodeClipboard(payload, {projectId, requireHint = false} = {}) {
  if (!payload || typeof payload !== 'object' || !Array.isArray(payload.nodes)) return {ok: false, reason: 'corrupt', message: label('clip.corrupt')};
  if (requireHint && payload.canvas_node_clipboard_hint !== 1) return {ok: false, reason: 'bad_hint', message: label('clip.hint')};
  if (payload.version != null && payload.version !== 1) return {ok: false, reason: 'bad_version', message: label('clip.version')};
  const project = payload.project_id || payload.project;
  if (projectId && project && project !== projectId) return {ok: false, reason: 'other_project', message: label('clip.project')};
  if (payload.nodes.some(node => node?.params?.canvas_subkind === 'group_frame')) return {ok: false, reason: 'group', message: label('clip.group')};
  if (payload.nodes.some(node => node?.status === 'uploading' || node?.status === 'generating')) return {ok: false, reason: 'busy', message: label('clip.busy')};
  return {ok: true};
}

export async function writeNodeClipboard(payload, writeText) {
  const text = JSON.stringify(payload);
  try {
    if (writeText) { await writeText(text); return true; }
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* local session copy still stands */ }
  return false;
}

export async function readNodeClipboard({projectId, readText} = {}) {
  const reader = readText || (typeof navigator !== 'undefined' && navigator.clipboard?.readText ? () => navigator.clipboard.readText() : null);
  if (!reader) return {ok: false, reason: 'unavailable', message: label('clip.unavailable')};
  let raw;
  try { raw = await reader(); }
  catch { return {ok: false, reason: 'unavailable', message: label('clip.read')}; }
  if (raw == null || String(raw).trim() === '') return {ok: false, reason: 'empty'};
  let parsed;
  try { parsed = JSON.parse(raw); }
  catch { return {ok: false, reason: 'corrupt', message: label('clip.corrupt')}; }
  const check = validateNodeClipboard(parsed, {projectId, requireHint: true});
  if (!check.ok) return check;
  return {ok: true, payload: parsed};
}

const PASTE_HARD_FAIL = new Set(['corrupt', 'other_project', 'bad_hint', 'bad_version', 'unsupported', 'group', 'busy']);

export async function resolvePastePayload(projectId, localRead, readText) {
  const system = await readNodeClipboard({projectId, readText});
  if (PASTE_HARD_FAIL.has(system.reason)) throw new Error(system.message);
  const value = system.ok ? system.payload : localRead?.('vsc-canvas-clipboard');
  if (!value?.nodes?.length) throw new Error(label('clip.empty'));
  const check = validateNodeClipboard(value, {projectId, requireHint: value.canvas_node_clipboard_hint != null});
  if (!check.ok) throw new Error(check.message);
  return value;
}

function historyMedia(jobs, node) {
  const rows = [];
  const items = jobs?.items || jobs || [];
  for (const job of items) {
    const payload = job.request_payload || job.logical_request || {};
    const linked = job.node_id === node.id || job.target_node_id === node.id || payload.node_id === node.id || job.id === node.job_id;
    if (!linked) continue;
    for (const output of job.outputs || []) {
      if (output.media_id && output.media_id !== node.media_id) rows.push({id: output.media_id, name: job.purpose || output.media_id});
    }
  }
  return rows;
}

async function uploadWithHost(file, host) {
  if (host.uploadMedia) return host.uploadMedia(file);
  const holder = document.createElement('div');
  holder.hidden = true;
  (host.root || document.body).append(holder);
  let mediaId = null;
  const upload = host.createUpload(holder, {onComplete: ({mediaId: id}) => { mediaId = id; }});
  try {
    await upload.load?.();
    await upload.uploadFiles([file]);
  } finally {
    upload.suspend?.();
    holder.remove();
  }
  return mediaId;
}

export async function openCanvasReplaceMediaDialog(host) {
  const node = host.node;
  if (!node) return null;
  let jobs = {items: []};
  let media = {items: []};
  try {
    [jobs, media] = await Promise.all([host.jobs?.() || {items: []}, host.media?.() || {items: []}]);
  } catch (error) {
    host.notice?.(error.message);
    return null;
  }
  if (host.live && !host.live()) return null;
  const dialog = el('dialog', null, 'cpi-replace-dialog cc-replace-media-dialog');
  bindAttribute(dialog, 'aria-label', label('replace.title'));
  dialog.append(el('h2', label('replace.title')));
  const tabs = el('div', null, 'cpi-tabs');
  const tabHistory = el('button', label('replace.history'), 'cpi-tab-history');
  const tabCanvas = el('button', label('replace.canvas'), 'cpi-tab-canvas');
  const tabLocal = el('button', label('replace.local'), 'cpi-tab-local');
  tabs.append(tabHistory, tabCanvas, tabLocal);
  const list = el('div', null, 'cpi-replace-list');
  const file = document.createElement('input');
  file.type = 'file';
  file.className = 'cpi-local-file';
  file.accept = node.type === 'video' ? 'video/*' : node.type === 'audio' ? 'audio/*' : 'image/*';
  file.hidden = true;
  let tab = 'history';
  let selected = null;
  const selectTab = next => {
    tab = next;
    selected = null;
    tabHistory.setAttribute('aria-pressed', String(next === 'history'));
    tabCanvas.setAttribute('aria-pressed', String(next === 'canvas'));
    tabLocal.setAttribute('aria-pressed', String(next === 'local'));
    file.hidden = next !== 'local';
    paintList();
  };
  function choiceButton(row) {
    const button = el('button', row.name, 'cpi-choice');
    button.addEventListener('click', () => {
      selected = {mediaId: row.id};
      for (const peer of list.querySelectorAll('.cpi-choice')) peer.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
    });
    return button;
  }
  function paintList() {
    list.replaceChildren();
    if (tab === 'history') {
      const rows = historyMedia(jobs, node);
      if (!rows.length) list.append(el('p', label('replace.none_history')));
      for (const row of rows) list.append(choiceButton(row));
    } else if (tab === 'canvas') {
      const rows = (media.items || []).filter(item => item.id !== node.media_id);
      if (!rows.length) list.append(el('p', label('replace.none_canvas')));
      for (const row of rows) list.append(choiceButton({id: row.id, name: row.name || row.id}));
    } else list.append(el('p', file.files?.[0]?.name || label('replace.pick')));
  }
  tabHistory.addEventListener('click', () => selectTab('history'));
  tabCanvas.addEventListener('click', () => selectTab('canvas'));
  tabLocal.addEventListener('click', () => selectTab('local'));
  file.addEventListener('change', () => { if (tab === 'local') paintList(); });
  const actions = el('div', null, 'cpi-replace-actions');
  const confirm = el('button', label('replace.confirm'), 'cpi-replace-confirm');
  const close = el('button', label('replace.close'), 'cpi-replace-close');
  confirm.addEventListener('click', async () => {
    try {
      let mediaId = selected?.mediaId || null;
      if (tab === 'local') {
        const picked = file.files?.[0];
        if (!picked) throw new Error(label('replace.file'));
        mediaId = await uploadWithHost(picked, host);
      }
      if (!mediaId) throw new Error(label('replace.need'));
      const ok = await host.replace?.(mediaId);
      if (ok !== false) dialog.close();
    } catch (error) {
      host.notice?.(error.message);
    }
  });
  close.addEventListener('click', () => dialog.close());
  actions.append(close, confirm);
  dialog.append(tabs, list, file, actions);
  dialog.addEventListener('close', () => dialog.remove());
  (host.root || document.body).append(dialog);
  selectTab('history');
  dialog.showModal?.();
  return dialog;
}

function pickFile(accept) {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.addEventListener('change', () => resolve(input.files?.[0] || null));
    input.click?.();
  });
}

export function installCanvasPreferencesImport(state, host = {}) {
  const menu = state?.root?.querySelector?.('.cc-more-menu');
  if (menu && !menu.querySelector('.cpi-pref-open')) {
    const preferences = el('button', label('menu.preferences'), 'cpi-pref-open');
    const exportJson = el('button', label('menu.export'), 'cpi-detail-export');
    const importJson = el('button', label('menu.import'), 'cpi-detail-import');
    const importZip = el('button', label('menu.zip'), 'cpi-zip-import');
    preferences.addEventListener('click', () => openPreferencesDialog({api: host.api, root: state.root, onSaved: applyUserAppearance}));
    exportJson.addEventListener('click', () => {
      downloadJson(`canvas-${host.canvasId?.() || 'detail'}.json`, buildDetailSnapshot({
        projectId: host.projectId?.(), canvasId: host.canvasId?.(), title: host.title?.(), document: host.document?.(),
      }));
      host.notice?.(label('detail.exported'));
    });
    importJson.addEventListener('click', async () => {
      try {
        const file = await pickFile('application/json,.json');
        if (!file) return;
        const snapshot = JSON.parse(await file.text());
        const ask = host.confirm || (message => (typeof globalThis.confirm === 'function' ? globalThis.confirm(message) : true));
        const result = await importDetailSnapshot(snapshot, {...host, confirm: ask});
        host.notice?.(result.ok ? label('detail.imported') : result.message);
      } catch (error) {
        host.notice?.(error.message || label('detail.invalid'));
      }
    });
    importZip.addEventListener('click', async () => {
      try {
        const file = await pickFile('.zip,application/zip');
        if (!file) return;
        const packed = await readZipEntries(new Uint8Array(await file.arrayBuffer()));
        if (!packed.ok) { host.notice?.(packed.message); return; }
        const result = await importZipEntries(packed.entries, host);
        host.notice?.(result.ok ? label('zip.done', {count: result.count}) : result.message);
      } catch (error) {
        host.notice?.(error.message);
      }
    });
    menu.append(preferences, exportJson, importJson, importZip);
  }
  const stage = state?.stage;
  if (stage?.addEventListener && !stage.dataset?.cpiClipboard) {
    if (stage.dataset) stage.dataset.cpiClipboard = '1';
    stage.addEventListener('keydown', event => {
      const target = event.target;
      if (target?.closest?.('input,textarea,select')) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = String(event.key || '').toLowerCase();
      if (key !== 'c' && key !== 'v') return;
      event.preventDefault();
      const run = key === 'c' ? host.copy : host.paste;
      Promise.resolve(run?.()).catch(error => host.notice?.(error.message));
    }, true);
  }
  if (host.api) {
    Promise.resolve(host.api('/api/v1/user-preferences')).then(raw => {
      applyUserAppearance(normalizeUserPreferences(raw));
    }).catch(() => {});
  }
}
