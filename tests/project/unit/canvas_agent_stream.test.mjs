import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

const ROOT = new URL('../../../', import.meta.url);

class Element {
  constructor(tag) {
    this.tagName = String(tag || 'div').toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this._text = '';
    this._value = '';
    this.parentElement = null;
    this.className = '';
    this.checked = false;
    this.disabled = false;
    this.dataset = {};
    this.style = {};
    this.classList = {
      add: (...values) => { this.className = [...new Set(`${this.className} ${values.join(' ')}`.split(' ').filter(Boolean))].join(' '); },
      contains: value => this.className.split(' ').includes(value),
      remove: (...values) => { this.className = this.className.split(' ').filter(value => !values.includes(value)).join(' '); },
    };
  }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set value(value) { this._value = String(value ?? ''); }
  get value() {
    if (this.tagName === 'SELECT') {
      const selected = this.children.find(child => child.selected) || this.children[0];
      return this._value || selected?.value || '';
    }
    return this._value;
  }
  set name(value) { this.setAttribute('name', value); }
  get name() { return this.getAttribute('name'); }
  set type(value) { this.setAttribute('type', value); }
  get type() { return this.getAttribute('type'); }
  append(...nodes) { for (const node of nodes) { if (node) { node.remove?.(); node.parentElement = this; this.children.push(node); } } }
  prepend(...nodes) { this.children.unshift(...nodes.map(node => { node.remove?.(); node.parentElement = this; return node; })); }
  remove() { this.parentElement && (this.parentElement.children = this.parentElement.children.filter(child => child !== this)); this.parentElement = null; }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this._text = ''; this.append(...nodes); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  matchOne(selector) {
    let rest = selector.trim();
    if (!rest || rest === '*') return true;
    const checked = rest.endsWith(':checked');
    if (checked) rest = rest.slice(0, -8);
    if (checked && !this.checked) return false;
    for (const token of rest.match(/\[[^\]]+\]/g) || []) {
      rest = rest.replace(token, '');
      const body = token.slice(1, -1);
      const match = body.match(/^([^=]+)="([\s\S]*)"$/);
      if (!match) { if (this.getAttribute(body) == null) return false; continue; }
      if (this.getAttribute(match[1]) !== match[2].replace(/\\:/g, ':')) return false;
    }
    const classes = [];
    rest = rest.replace(/\.([A-Za-z0-9_-]+)/g, (_, name) => { classes.push(name); return ''; });
    if (rest.trim() && this.tagName !== rest.trim().toUpperCase()) return false;
    return classes.every(name => this.classList.contains(name));
  }
  matches(selector) { return selector.split(',').some(part => this.matchOne(part)); }
  querySelectorAll(selector) {
    if (selector.startsWith(':scope > ')) return this.children.filter(child => child.matchOne(selector.slice(9)));
    const found = [];
    const walk = node => { for (const child of node.children || []) { found.push(child); walk(child); } };
    walk(this);
    return selector === '*' ? found : found.filter(child => child.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (node.matches?.(selector)) return node; return null; }
  async fire(type) { for (const fn of this.listeners[type] || []) await fn({target: this, preventDefault() {}, stopPropagation() {}}); }
}

function browser() {
  const store = new Map();
  const document = {
    documentElement: {lang: 'zh-CN'},
    createElement: tag => { const node = new Element(tag); node.ownerDocument = document; return node; },
  };
  return {
    document,
    sessionStorage: {getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)},
    fetch: async () => ({ok: true, body: null}),
    CSS: {escape: value => String(value).replace(/:/g, '\\:')},
  };
}

function future() { return new Date(Date.now() + 3600_000).toISOString(); }

function snapshot(extra = {}) {
  return {
    revision: 3,
    canvas_id: 'c1',
    current_session_id: 's1',
    sessions: [
      {id: 's1', title: '雨夜会话', archived: false, auto_approve: false, is_current: true, has_active_turn: false},
      {id: 's2', title: '第二会话', archived: false, auto_approve: false, is_current: false, has_active_turn: false},
    ],
    prefs: {chat_model: 'grok', reasoning_effort: 'medium', selected_skill: 'vsc-script', preferred_model_ids: [], tier_seen: true},
    auto_approve: false,
    messages: [{id: 'm1', role: 'assistant', text: '已读画布', feedback: null}],
    has_older: true,
    older_cursor: 'm0',
    tools: [{id: 'tool-1', category: 'write_canvas', name: 'create', nodes_created: 2, edges_created: 1}],
    question_batch: {id: 'batch-1', status: 'pending', version: 1, payload: {items: [{id: 'look', prompt: '选光线', required: true, kind: 'single', max_length: 20, options: [{id: 'neon', label: '霓虹'}]}]}},
    tickets: [
      {id: 'paid-1', status: 'pending', payload: {ticket_type: 'paid', operation: '生图', model: 'seedream', unit_price: 2, quantity: 1, total_credits: 2, canvas_version: 1, expires_at: future()}},
      {id: 'paid-2', status: 'pending', payload: {ticket_type: 'paid', operation: '生图', model: 'seedream', unit_price: 3, quantity: 1, total_credits: 3, canvas_version: 1, expires_at: future()}},
      {id: 'del-1', status: 'pending', payload: {ticket_type: 'delete', canvas_version: 1, node_count: 1, node_list: [{id: 'n1', title: '雨夜节点'}], cascade_edge_count: 1, edges: [{id: 'e1'}], expires_at: future()}},
    ],
    pending_batch: [],
    queue: [],
    active_turn: null,
    cursor: 4,
    ...extra,
  };
}

async function mounted(initial, {dirty = false, save = async () => true} = {}) {
  const env = browser();
  const mod = await loadModule('canvas-agent-stream.js', env);
  let current = structuredClone(initial);
  const writes = [];
  const panel = env.document.createElement('section');
  panel.className = 'cc-agent';
  const state = {
    id: 'c1', project: 'p1', version: 1, revision: 3, dirty, pending: false,
    selected: new Set(), document: {nodes: [{id: 'n1', type: 'image', title: '雨夜', x: 10, y: 10, text: '', params: {}}], edges: [{id: 'e1', source: 'n1', target: 'n2'}]},
    agentPanel: panel, agentAttachments: [],
  };
  const focused = [];
  const bridge = {
    api: async path => path.includes('/agent/events') ? {events: [], cursor: current.cursor} : structuredClone(current),
    url: () => '/api/v1/projects/p1/creative-canvases/c1',
    headers: () => ({'X-CSRF-Token': 'csrf'}),
    save,
    focusNode: (_state, node) => focused.push(node.id),
    revision() {},
    change(_state, fn) { fn(); },
    auxiliaryWrite: async (_state, _key, _path, payload) => {
      writes.push(payload);
      if (payload.action === 'rename_session' && payload.title === '失败') throw new Error('TimeoutError');
      if (payload.action === 'select_session') current.current_session_id = payload.session_id;
      if (payload.action === 'rename_session') current.sessions.find(item => item.id === payload.session_id).title = payload.title;
      if (payload.action === 'create_session') current.sessions.push({id: 's3', title: '未命名会话', has_active_turn: false});
      if (payload.action === 'delete_session') current.sessions = current.sessions.filter(item => item.id !== payload.session_id);
      if (payload.action === 'feedback') current.messages.find(item => item.id === payload.message_id).feedback = payload.verdict;
      if (payload.action === 'answer' && !payload.skip) current.question_batch = {status: 'answered'};
      if (payload.action === 'answer' && payload.skip) current.question_batch = {status: payload.cancel ? 'canceled' : 'skipped'};
      if (payload.action === 'authorize_batch') current.tickets = current.tickets.filter(item => item.payload.ticket_type === 'delete');
      if (payload.action === 'authorize' && payload.approve) {
        const ticket = current.tickets.find(item => item.id === payload.authorization_id);
        current.tickets = current.tickets.filter(item => item.id !== payload.authorization_id);
        return {status: 'approved', ticket_type: ticket.payload.ticket_type, node_ids: (ticket.payload.node_list || []).map(node => node.id), provider_submitted: false};
      }
      if (payload.action === 'set_prefs') current.prefs = {...current.prefs, ...payload, tier_seen: payload.tier_seen ?? current.prefs.tier_seen};
      if (payload.action === 'send') current.messages.push({id: 'm-new', role: 'user', text: payload.message || '请理解所引用的素材。'});
      if (payload.action === 'stop') current.active_turn = null;
      if (payload.action === 'steer') current.queue = [];
      return {revision: 4, provider_submitted: false};
    },
    openEditor: async () => true,
  };
  await mod.mountCanvasAgentStream(state, bridge);
  return {mod, env, panel, state, writes, focused, bridge, read: () => current};
}

function button(root, text) {
  return root.querySelectorAll('button').find(node => node.textContent === text);
}

test('protocol helpers keep Chinese reasons, questions, tickets and SSE parsing', async () => {
  const mod = await loadModule('canvas-agent-stream.js', browser());
  assert.equal(mod.classifyAgentError('rate_limited').message, '请求较多，请稍后重试');
  assert.equal(mod.classifyAgentError('quota_exhausted').message, '模型服务额度暂不可用，请稍后再试');
  assert.equal(mod.classifyAgentError('provider_unavailable').message, '模型服务暂不可用，请稍后重试');
  assert.equal(mod.classifyAgentError('content_rejected').message, '内容被模型拒绝，请调整后重试');
  assert.equal(mod.classifyAgentError('provider_timeout').message, '模型响应超时，请稍后重试');
  assert.equal(mod.classifyAgentError('provider_connection_error').message, '模型服务连接中断，请稍后重试');
  assert.equal(mod.classifyAgentError('turn_timeout').message, '本轮处理超时，已停止；发送新消息可以继续');
  assert.equal(mod.classifyAgentError('canvas_agent_host_unavailable').code, 'provider_unavailable');
  assert.equal(mod.classifyAgentError('canvas_agent_submission_unknown').code, 'provider_timeout');
  assert.equal(mod.classifyAgentError('TimeoutError').message, '回合执行失败');
  assert.equal(mod.classifyAgentError('invalid_canvas_plan').message, '回合执行失败');
  assert.equal(mod.referenceOnlyPrompt('  ', {nodes: ['n1']}), '请理解所引用的素材。');
  assert.equal(mod.referenceOnlyPrompt('', {attachments: []}), '');
  const invalid = mod.validateQuestionBatch({items: [{id: 'look', required: true, kind: 'single', options: [{id: 'a'}]}]}, []);
  assert.equal(invalid.message, '请回答所有必答问题');
  const long = mod.validateQuestionBatch({items: [{id: 'note', required: false, kind: 'text', max_length: 2}]}, [{question_id: 'note', custom_text: '太长啊'}]);
  assert.equal(long.message, '自定义回答最多 2 字');
  assert.equal(mod.validateQuestionBatch({items: []}, [], true).skipped, true);
  const blocked = mod.ticketBlockers({ticket_type: 'paid', operation: '生图', model: '', unit_price: 1, quantity: 1, total_credits: 1, canvas_version: 1, expires_at: future()});
  assert.match(blocked.message, /授权票据缺少关键字段（操作与模型）/);
  assert.equal(mod.ticketBlockers({ticket_type: 'delete', canvas_version: 1, node_count: 2, node_list: [{id: 'n1'}], cascade_edge_count: 0, expires_at: future()}).message, '节点清单与数量不一致');
  assert.equal(mod.ticketBlockers({ticket_type: 'paid', operation: '生图', model: 'm', unit_price: 1, quantity: 1, total_credits: 1, canvas_version: 1, expires_at: '2000-01-01T00:00:00Z'}).message, '票据已过期，批准会被服务端拒绝，请让助手重新发起。');
  assert.equal(mod.reconnectDelay(6).message, '连接中断，请重新打开对话');
  assert.equal(mod.reconnectDelay(1).ms, 1000);
  assert.equal(mod.reconnectDelay(3).ms, 4000);
  const parsed = mod.parseSseChunk('', 'id: 4\nevent: assistant_delta\ndata: {"text":"雨"}\n\n');
  assert.equal(parsed.events[0].event, 'assistant_delta');
  assert.equal(parsed.events[0].data.text, '雨');
  const summary = mod.batchAuthSummary([
    {status: 'pending', ticket_type: 'paid', operation: '生图', total_credits: 2, model: 'm', unit_price: 2, quantity: 1, canvas_version: 1, expires_at: future()},
    {status: 'pending', ticket_type: 'delete', operation: '删除', total_credits: 9, canvas_version: 1, node_count: 1, node_list: [{id: 'n'}], cascade_edge_count: 0, expires_at: future()},
  ]);
  assert.equal(summary.count, 1);
  assert.equal(summary.title, '待审批批次 · 1 项');
  const html = fs.readFileSync(new URL('./src/vsc/interfaces/web/templates/index.html', ROOT), 'utf8');
  const css = fs.readFileSync(new URL('./src/vsc/interfaces/web/static/canvas-agent-stream.css', ROOT), 'utf8');
  assert.match(html, /\/static\/canvas-agent-stream\.css/);
  assert.match(css, /\.cc-agent-stream-batch/);
});

test('active session renders questions, tickets, paging, feedback and batch authorize', async () => {
  const view = await mounted(snapshot());
  const stream = view.panel.querySelector('.cc-agent-stream');
  assert.equal(stream.querySelector('h2').textContent, 'Agent');
  assert.equal(button(stream, '加载更早消息').textContent, '加载更早消息');
  assert.match(stream.textContent, /新增 2 个节点/);
  assert.match(stream.textContent, /新增 1 条连线/);
  assert.match(stream.textContent, /请补充信息/);
  assert.match(stream.textContent, /必答/);
  assert.match(stream.textContent, /删除确认票据/);
  assert.match(stream.textContent, /雨夜节点/);
  assert.match(stream.textContent, /待审批批次 · 2 项/);
  await button(stream, '提交回答').fire('click');
  assert.match(stream.textContent, /请回答所有必答问题/);
  stream.querySelector('input').checked = true;
  await button(stream, '提交回答').fire('click');
  assert.equal(view.writes.at(-1).action, 'answer');
  assert.deepEqual(view.writes.at(-1).answers[0].selected_option_ids, ['neon']);
  const again = await mounted(snapshot());
  await button(again.panel, '忽略本组问题').fire('click');
  assert.equal(again.writes.at(-1).skip, true);
  const canceled = await mounted(snapshot());
  await button(canceled.panel, '取消本组问题').fire('click');
  assert.equal(canceled.writes.at(-1).cancel, true);
  await button(again.panel, '点赞').fire('click');
  assert.equal(again.writes.find(item => item.action === 'feedback').verdict, 'up');
  await button(again.panel, '全部授权').fire('click');
  assert.equal(again.writes.at(-1).action, 'authorize_batch');
  await button(again.panel, '批准并执行').fire('click');
  const approved = again.writes.find(item => item.action === 'authorize' && item.approve);
  assert.equal(approved.authorization_id, 'del-1');
  assert.deepEqual(again.state.document.nodes.map(node => node.id), []);
  await button(again.panel, '加载更早消息').fire('click');
  assert.match(again.panel.textContent, /正在加载更早消息|加载更早消息/);
  const skill = again.panel.querySelector('[aria-label="会话技能"]');
  skill.value = 'vsc-direct';
  await skill.fire('change');
  assert.equal(again.writes.at(-1).selected_skill, 'vsc-direct');
});

test('session switch, rename, delete, steer, stop, save guard and reference prompt', async () => {
  const view = await mounted(snapshot());
  const picker = view.panel.querySelector('[aria-label="切换会话"]');
  picker.value = 's2';
  await picker.fire('change');
  assert.equal(view.writes.at(-1).action, 'select_session');
  assert.equal(view.writes.at(-1).session_id, 's2');
  await button(view.panel, '重命名').fire('click');
  const rename = view.panel.querySelector('.cc-agent-stream-renamebox').querySelector('input');
  assert.equal(rename.maxLength, 30);
  rename.value = '';
  await button(view.panel.querySelector('.cc-agent-stream-renamebox'), '确定').fire('click');
  assert.match(view.panel.textContent, /标题不能为空，且不能超过 30 个字符/);
  rename.value = '雨夜定稿';
  await button(view.panel.querySelector('.cc-agent-stream-renamebox'), '确定').fire('click');
  assert.equal(view.writes.at(-1).title, '雨夜定稿');
  await button(view.panel, '新会话').fire('click');
  assert.equal(view.writes.at(-1).action, 'create_session');
  await button(view.panel, '删除').fire('click');
  assert.match(view.panel.textContent, /确定删除会话「/);
  await button(view.panel, '确定').fire('click');
  assert.equal(view.writes.at(-1).action, 'delete_session');
  const broken = await mounted(snapshot());
  await button(broken.panel, '重命名').fire('click');
  broken.panel.querySelector('.cc-agent-stream-renamebox').querySelector('input').value = '失败';
  await button(broken.panel.querySelector('.cc-agent-stream-renamebox'), '确定').fire('click');
  assert.match(broken.panel.textContent, /回合执行失败/);
  assert.doesNotMatch(broken.panel.textContent, /TimeoutError/);

  const busy = await mounted(snapshot({active_turn: {id: 'turn-1', status: 'running'}, queue: [{id: 'q1', message: '近景', status: 'queued'}]}));
  await button(busy.panel, '确认插队').fire('click');
  assert.match(busy.panel.textContent, /当前回复会停止，但已经开始的生成任务或画布修改可能保留。确定让这条消息插队执行吗？/);
  assert.notEqual(busy.writes.at(-1)?.action, 'steer');
  await busy.panel.querySelector('.cc-agent-stream-steer-ok').fire('click');
  assert.equal(busy.writes.at(-1).action, 'steer');
  assert.equal(busy.writes.at(-1).expected_active_turn_id, 'turn-1');
  assert.equal(busy.writes.at(-1).queue_item_id, 'q1');
  await button(busy.panel, '删除').fire('click');
  assert.match(busy.panel.textContent, /正在执行中的会话不可删除/);
  await button(busy.panel, '停止').fire('click');
  assert.equal(busy.writes.at(-1).action, 'stop');

  const unsaved = await mounted(snapshot({question_batch: null, tickets: [], has_older: false}), {dirty: true, save: async () => false});
  const input = unsaved.panel.querySelector('.cc-agent-stream-input');
  input.value = '发送前应保存';
  await button(unsaved.panel, '发送').fire('click');
  assert.match(unsaved.panel.textContent, /画布保存尚未完成，请处理保存状态后重试发送/);
  assert.equal(unsaved.writes.some(item => item.action === 'send'), false);

  const cited = await mounted(snapshot({question_batch: null, tickets: [], has_older: false}));
  cited.state.selected = new Set(['n1']);
  const citedInput = cited.panel.querySelector('.cc-agent-stream-input');
  citedInput.value = '   ';
  await button(cited.panel, '发送').fire('click');
  const sent = cited.writes.find(item => item.action === 'send');
  assert.equal(sent.message, '');
  assert.deepEqual(sent.node_ids, ['n1']);
});

test('action bridge applies layout, focuses the new node and keeps delete behind a ticket', async () => {
  const mod = await loadModule('canvas-agent-stream.js', browser());
  const nodes = [{id: 'a', type: 'image', title: '甲', x: 9, y: 9, text: '', params: {}}, {id: 'b', type: 'text', title: '乙', x: 3, y: 4, text: '词', params: {}}];
  const arranged = mod.executeCanvasAction({nodes, edges: [], selected: ['a']}, {action_id: 'arrange_selected'});
  assert.equal(arranged.ok, true);
  assert.deepEqual(arranged.focus_ids, ['a']);
  assert.equal(arranged.nodes.find(node => node.id === 'a').x, 40);
  assert.equal(arranged.nodes.find(node => node.id === 'a').y, 50);
  assert.equal(arranged.nodes.find(node => node.id === 'b').x, 3);
  const missing = mod.executeCanvasAction({nodes, edges: [], selected: []}, {action_id: 'image_crop_dialog'});
  assert.equal(missing.message, '请先选择要打开编辑器的节点');
  const wrong = mod.executeCanvasAction({nodes, edges: [], selected: ['b']}, {action_id: 'image_crop_dialog'});
  assert.equal(wrong.message, '当前上下文不支持动作：image_crop_dialog');
  const ticket = mod.executeCanvasAction({nodes, edges: [{id: 'e', source: 'a', target: 'b'}], selected: ['a']}, {action_id: 'delete_selection'});
  assert.equal(ticket.needs_ticket, true);
  assert.equal(ticket.ticket.node_count, 1);
  assert.equal(ticket.ticket.cascade_edge_count, 1);
  assert.equal(nodes.length, 2);
  const unsupported = mod.executeCanvasAction({nodes, edges: [], selected: ['a']}, {action_id: 'explode'});
  assert.equal(unsupported.message, '前端暂不支持动作：explode');
  const state = {document: {nodes: nodes.map(node => ({...node})), edges: []}, selected: new Set(['a', 'b']), agentStreamSession: 's1'};
  const focused = [];
  const opened = [];
  const bridge = {
    url: () => '/agent',
    auxiliaryWrite: async (_state, _key, _path, payload) => payload,
    change(_state, fn) { fn(); },
    focusNode(_state, node) { focused.push(node.id); },
    openEditor: async (_state, dialog, id) => opened.push([dialog, id]),
  };
  const created = await mod.runCanvasAction(state, bridge, {action_id: 'create_generator_from_selection', session_id: 's1'});
  assert.equal(created.result.ok, true);
  assert.equal(focused[0], created.result.focus_ids[0]);
  assert.equal(state.document.nodes.some(node => node.id === focused[0]), true);
  const editor = await mod.runCanvasAction({...state, selected: new Set(['a'])}, bridge, {action_id: 'image_crop_dialog', session_id: 's1'});
  assert.deepEqual(opened, [['image_crop_dialog', 'a']]);
  assert.equal(editor.result.dialog, 'image_crop_dialog');
});

test('SSE reader applies incremental events and a reader-less fetch falls back to one poll', async () => {
  const mod = await loadModule('canvas-agent-stream.js', browser());
  const seen = [];
  const scheduled = [];
  let reads = 0;
  const reader = {async read() { reads += 1; if (reads > 1) return {done: true}; return {done: false, value: 'id: 8\nevent: turn_status\ndata: {"status":"running","turn_id":"t1"}\n\n'}; }};
  const transport = mod.createAgentTransport({
    url: '/events',
    headers: {},
    fetchImpl: async () => ({body: {getReader: () => reader}}),
    schedule: (fn, ms) => scheduled.push(ms),
    onEvent: event => seen.push(event),
  });
  assert.equal(await transport.started, 'sse');
  assert.equal(seen[0].event, 'turn_status');
  assert.equal(seen[0].data.turn_id, 't1');
  assert.equal(scheduled[0] >= 1000, true);
  const polled = [];
  const fallback = mod.createAgentTransport({
    url: '/events',
    pollUrl: '/events',
    headers: {},
    api: async () => ({events: [{kind: 'assistant_message', seq: 2, payload: {role: 'assistant', text: '回合执行失败', error_text: '回合执行失败'}}], cursor: 2}),
    fetchImpl: async () => ({body: {}}),
    onSnapshot: body => polled.push(body),
    onMode: mode => polled.push(mode),
  });
  assert.equal(await fallback.started, 'poll');
  assert.equal(polled[0], 'poll');
  assert.equal(polled[1].events[0].payload.error_text, '回合执行失败');
  const state = mod.applyStreamEvent({messages: [], tools: [], tickets: [], cursor: 0}, polled[1].events[0]);
  assert.equal(state.messages[0].text, '回合执行失败');
  assert.equal(state.cursor, 2);
});
