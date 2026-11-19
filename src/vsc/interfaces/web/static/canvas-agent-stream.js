/** Canvas Agent incremental stream: one active session, SSE, tickets and action bridge. */

const COPY = {
  "zh-CN": {
    canvas_save_incomplete: "画布保存尚未完成，请处理保存状态后重试发送",
    reference_only_prompt: "请理解所引用的素材。",
    connection_lost_reopen: "连接中断，请重新打开对话",
    steer_confirm_title: "插队执行",
    steer_confirm_message: "当前回复会停止，但已经开始的生成任务或画布修改可能保留。确定让这条消息插队执行吗？",
    steer_confirm_button: "确认插队",
    new_session: "新会话",
    rename: "重命名",
    rename_invalid: "标题不能为空，且不能超过 30 个字符",
    delete: "删除",
    delete_confirm: "确定删除会话「{title}」？删除后无法在历史中恢复",
    busy_delete: "正在执行中的会话不可删除",
    cancel: "取消",
    confirm: "确定",
    load_older: "加载更早消息",
    loading_older: "正在加载更早消息",
    empty_session: "开始一个新会话，描述你想在画布上完成的任务。",
    input_placeholder: "描述你想在画布上完成的任务",
    send: "发送",
    stop: "停止",
    chat_model: "对话模型",
    chat_model_hint: "用于下一条消息",
    skill: "加载 Skill",
    perm_ask: "需授权",
    perm_bypass: "免授权",
    perm_ask_tip: "付费操作逐笔弹卡确认。点击切换为本会话免授权",
    perm_bypass_tip: "本会话付费生成免确认直接执行（删除类仍需逐笔确认）。点击恢复需授权",
    tier_title: "权限档位",
    like: "点赞",
    dislike: "点踩",
    question_title: "请补充信息",
    required: "必答",
    optional: "选答",
    custom: "自定义回答",
    submit: "提交回答",
    skip: "忽略本组问题",
    question_cancel: "取消本组问题",
    required_missing: "请回答所有必答问题",
    paid_title: "付费执行授权",
    delete_title: "删除确认票据",
    approve: "批准并执行",
    reject: "拒绝",
    batch: "待审批批次 · {count} 项",
    batch_many: "「{name}」等节点配置已生成，确认后按配置批量执行（预计消耗 {credit} 积分）",
    batch_one: "「{name}」节点配置已生成，确认后按配置执行（预计消耗 {credit} 积分）",
    batch_go: "全部授权",
    collapse: "收起步骤",
    expand: "展开步骤",
    read_canvas: "读取画布",
    search_assets: "搜索素材",
    tool: "执行工具",
    write_canvas: "修改画布",
    created: "新增 {count} 个节点",
    edges_created: "新增 {count} 条连线",
    turn_failed: "回合执行失败",
    rate_limited: "请求较多，请稍后重试",
    quota_exhausted: "模型服务额度暂不可用，请稍后再试",
    provider_unavailable: "模型服务暂不可用，请稍后重试",
    content_rejected: "内容被模型拒绝，请调整后重试",
    provider_timeout: "模型响应超时，请稍后重试",
    provider_connection_error: "模型服务连接中断，请稍后重试",
    turn_timeout: "本轮处理超时，已停止；发送新消息可以继续",
    missing_fields: "授权票据缺少关键字段（{fields}），无法确认本次操作的影响范围，已禁用批准。请拒绝并让助手重新发起。",
    ticket_expired: "票据已过期，批准会被服务端拒绝，请让助手重新发起。",
    node_mismatch: "节点清单与数量不一致",
    owner_only: "仅发起人可批准或拒绝此请求",
    select_editor: "请先选择要打开编辑器的节点",
    select_operate: "请先选择要操作的节点",
    select_delete: "请先选择要删除的节点",
    select_two: "请至少选择 2 个节点",
    prompt_required: "请补充要写入生成器的提示词",
    video_prompt: "Agent 未返回视频 prompt",
    unsupported: "前端暂不支持动作：{actionId}",
    switch_session: "切换会话",
  },
  en: {},
};
COPY.en = {...COPY["zh-CN"]};

const FAILURES = {
  rate_limited: "rate_limited",
  quota_exhausted: "quota_exhausted",
  provider_unavailable: "provider_unavailable",
  content_rejected: "content_rejected",
  provider_timeout: "provider_timeout",
  provider_connection_error: "provider_connection_error",
  turn_timeout: "turn_timeout",
  turn_failed: "turn_failed",
};
const FAILURE_ALIASES = {
  canvas_agent_host_unavailable: "provider_unavailable",
  canvas_agent_host_failed: "turn_failed",
  canvas_agent_skill_changed: "turn_failed",
  invalid_canvas_plan: "turn_failed",
  canvas_agent_submission_unknown: "provider_timeout",
};

function locale() {
  try {
    const lang = String(globalThis.document?.documentElement?.lang || "zh-CN").toLowerCase();
    return lang.startsWith("en") ? "en" : "zh-CN";
  } catch {
    return "zh-CN";
  }
}

export function agentText(key, vars) {
  let text = (COPY[locale()] || COPY["zh-CN"])[key] || COPY["zh-CN"][key] || key;
  if (vars) for (const [name, value] of Object.entries(vars)) text = text.replaceAll("{" + name + "}", String(value));
  return text;
}

export function classifyAgentError(value) {
  const raw = typeof value === "string" ? value : (value?.reason || value?.code || value?.error || "");
  const mapped = FAILURE_ALIASES[raw] || raw;
  const code = FAILURES[mapped] ? mapped : "turn_failed";
  return {code, message: agentText(code)};
}

export function referenceOnlyPrompt(message, references) {
  const text = typeof message === "string" ? message.trim() : "";
  if (text) return text;
  const nodes = references?.nodes || references?.node_ids || [];
  const attachments = references?.attachments || references?.attachment_media_ids || [];
  if (nodes.length || attachments.length) return agentText("reference_only_prompt");
  return "";
}

export function validateQuestionBatch(batch, answers, skip=false) {
  const items = batch?.items || [];
  if (skip) return {ok: true, skipped: true, answers: []};
  if (!Array.isArray(answers)) return {ok: false, code: "required_missing", message: agentText("required_missing")};
  const byId = new Map(answers.filter(row => row && typeof row === "object").map(row => [row.question_id, row]));
  const normalized = [];
  for (const item of items) {
    const answer = byId.get(item.id) || {};
    const custom = typeof answer.custom_text === "string" ? answer.custom_text : "";
    const selected = Array.isArray(answer.selected_option_ids) ? answer.selected_option_ids : [];
    if (Number.isInteger(item.max_length) && custom.length > item.max_length) {
      return {ok: false, code: "answer_too_long", message: "自定义回答最多 " + item.max_length + " 字"};
    }
    if ((item.kind || "text") === "single" && selected.length > 1) return {ok: false, code: "required_missing", message: agentText("required_missing")};
    const filled = custom.trim().length > 0 || selected.length > 0;
    if (item.required && !filled) return {ok: false, code: "required_missing", message: agentText("required_missing")};
    normalized.push({question_id: item.id, selected_option_ids: selected, custom_text: custom});
  }
  return {ok: true, skipped: false, answers: normalized};
}

function expiryMs(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ticketBlockers(ticket, now) {
  const item = ticket || {};
  const moment = now instanceof Date ? now.getTime() : Date.parse(now || new Date().toISOString());
  const kind = item.ticket_type || item.kind || "paid";
  const fields = kind === "delete"
    ? [["canvas_version", "画布版本"], ["node_count", "节点数量"], ["node_list", "节点清单"], ["cascade_edge_count", "级联连线"], ["expires_at", "过期时间"]]
    : [["operation", "操作与模型"], ["model", "操作与模型"], ["unit_price", "计费明细"], ["quantity", "计费明细"], ["total_credits", "金额"], ["canvas_version", "画布版本"], ["expires_at", "过期时间"]];
  const missing = [];
  for (const [key, label] of fields) {
    const value = item[key];
    if ((value == null || value === "" || (Array.isArray(value) && !value.length)) && !missing.includes(label)) missing.push(label);
  }
  if (kind === "delete" && item.node_count != null && Array.isArray(item.node_list) && item.node_list.length !== item.node_count) {
    return {ok: false, approve_disabled: true, code: "missing_node_list_count_mismatch", message: agentText("node_mismatch")};
  }
  if (missing.length) return {ok: false, approve_disabled: true, code: "missing_fields", message: agentText("missing_fields", {fields: missing.join("、")})};
  const expires = expiryMs(item.expires_at);
  if (expires == null || expires <= moment) return {ok: false, approve_disabled: true, code: "ticket_expired", message: agentText("ticket_expired")};
  return {ok: true, approve_disabled: false, code: null, message: ""};
}

export function reconnectDelay(attempt) {
  const count = Number(attempt) || 0;
  if (count > 5) return {ms: 15000, exhausted: true, message: agentText("connection_lost_reopen")};
  return {ms: Math.min(15000, 1000 * (2 ** Math.max(0, count - 1))), exhausted: false, message: null};
}

export function parseSseChunk(buffer, chunk) {
  const text = String(buffer || "") + String(chunk || "");
  const parts = text.split("\n\n");
  const rest = parts.pop() ?? "";
  const events = [];
  for (const block of parts) {
    if (!block.trim() || block.trimStart().startsWith(":")) continue;
    let id = null, event = "message", data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("id:")) id = line.slice(3).trim();
      else if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    let payload = null;
    if (data) { try { payload = JSON.parse(data); } catch { payload = {raw: data}; } }
    events.push({id, event, data: payload});
  }
  return {events, rest};
}

export function summarizeToolStep(step) {
  const source = step?.payload || step || {};
  const bits = [];
  if (source.nodes_created) bits.push(agentText("created", {count: source.nodes_created}));
  if (source.edges_created) bits.push(agentText("edges_created", {count: source.edges_created}));
  if (source.nodes_updated) bits.push("更新 " + source.nodes_updated + " 个节点");
  if (source.matched) bits.push("找到 " + source.matched + " 项");
  return bits;
}

export function batchAuthSummary(tickets, now) {
  const pending = (tickets || []).filter(ticket => {
    const kind = ticket.ticket_type || ticket.kind || ticket.payload?.ticket_type;
    const status = ticket.status || "pending";
    const body = ticket.payload || ticket;
    return kind !== "delete" && status === "pending" && !ticketBlockers(body, now).approve_disabled;
  });
  const credit = pending.reduce((sum, ticket) => sum + Number((ticket.payload || ticket).total_credits || 0), 0);
  const name = (pending[0]?.payload || pending[0])?.operation || "节点";
  return {
    count: pending.length,
    credit,
    title: agentText("batch", {count: pending.length}),
    detail: pending.length > 1 ? agentText("batch_many", {name, credit}) : agentText("batch_one", {name, credit}),
  };
}

export function applyStreamEvent(state, event) {
  const next = {
    ...state,
    messages: [...(state?.messages || [])],
    tools: [...(state?.tools || [])],
    tickets: [...(state?.tickets || [])],
  };
  const kind = event?.kind || event?.event;
  const payload = event?.payload || event?.data || {};
  if (kind === "user_message" || kind === "assistant_message") {
    next.messages.push({id: event.id || payload.message_id, role: payload.role || (kind === "assistant_message" ? "assistant" : "user"), text: payload.text || "", error_text: payload.error_text || null});
  } else if (kind === "assistant_delta") {
    const id = payload.turn_id || payload.message_id || "assistant";
    let row = next.messages.find(item => item.id === id && item.role === "assistant");
    if (!row) { row = {id, role: "assistant", text: ""}; next.messages.push(row); }
    row.text += payload.message || payload.text || "";
  } else if (kind === "tool_step") next.tools.push({...payload, id: event.id, kind});
  else if (kind === "turn_status") next.active_turn = {id: payload.turn_id || payload.successor_turn_id, status: payload.status};
  else if (kind === "question_required") next.question_batch = {id: payload.batch_id, status: "pending", payload};
  else if (kind === "authorization_required") next.tickets.push({id: payload.authorization_id, status: "pending", payload});
  else if (kind === "message_feedback") {
    const message = next.messages.find(item => item.id === payload.message_id);
    if (message) message.feedback = payload.verdict;
  }
  if (event?.seq != null) next.cursor = event.seq;
  else if (event?.id != null && /^\d+$/.test(String(event.id))) next.cursor = Number(event.id);
  return next;
}

const ACTION_LABELS = {
  arrange_selected: "整理选中节点布局",
  organize_canvas: "整理全画布",
  group_selection: "分组选中节点",
  ungroup_node: "取消分组",
  duplicate_node_with_upstream: "复制节点和上游",
  create_generator_from_selection: "基于选中节点创建生成器",
  create_video_generator_and_run: "基于选中节点生成视频并执行",
  update_generator_prompt: "更新选中生成器提示词",
  run_selected_node: "运行选中节点",
  retry_selected_node: "重试选中节点",
  cancel_selected_node: "取消选中节点运行",
  delete_selection: "删除选中节点",
  image_crop_dialog: "打开图片裁剪",
  image_doodle_dialog: "打开涂鸦编辑",
  image_grid_split_dialog: "打开宫格切分",
  image_inpaint_dialog: "打开局部重绘",
  audio_clip_dialog: "打开音频裁剪",
};

function cloneDocument(state) {
  return {nodes: (state.nodes || []).map(node => ({...node})), edges: (state.edges || []).map(edge => ({...edge}))};
}

function selectedNodes(state) {
  const ids = new Set(state.selected || []);
  return (state.nodes || []).filter(node => ids.has(node.id));
}

export function executeCanvasAction(state, request) {
  const action = request?.action_id || request?.action;
  const label = ACTION_LABELS[action];
  if (!action || !label) return {ok: false, code: "frontend_action_not_supported", message: agentText("unsupported", {actionId: action || ""}), focus_ids: []};
  const selected = selectedNodes(state);
  const document = cloneDocument(state);
  const fail = (code, message) => ({ok: false, code, message, focus_ids: [], action_id: action});
  const editors = new Set(["image_crop_dialog", "image_doodle_dialog", "image_grid_split_dialog", "image_inpaint_dialog", "audio_clip_dialog"]);
  if (!selected.length && ["arrange_selected", "group_selection", "ungroup_node", "duplicate_node_with_upstream", "create_generator_from_selection", "create_video_generator_and_run", "update_generator_prompt", "run_selected_node", "retry_selected_node", "cancel_selected_node", "delete_selection", ...editors].includes(action)) {
    if (editors.has(action)) return fail("select_node_to_open_editor", agentText("select_editor"));
    if (action === "delete_selection") return fail("select_nodes_to_delete", agentText("select_delete"));
    return fail("select_node_to_operate", agentText("select_operate"));
  }
  if (editors.has(action)) {
    const node = selected[0];
    const image = action.startsWith("image_");
    if (image && node.type !== "image") return fail("action_not_supported_in_context", "当前上下文不支持动作：" + action);
    if (action === "audio_clip_dialog" && node.type !== "audio") return fail("action_not_supported_in_context", "当前上下文不支持动作：" + action);
    return {ok: true, action_id: action, dialog: action, focus_ids: [node.id], message: label, nodes: document.nodes, edges: document.edges};
  }
  if (action === "group_selection" && selected.length < 2) return fail("select_min_two_nodes", agentText("select_two"));
  if (action === "update_generator_prompt" && !String(request.prompt || "").trim()) return fail("prompt_required_for_generator", agentText("prompt_required"));
  if (action === "create_video_generator_and_run" && !String(request.prompt || request.text || "").trim()) return fail("missing_video_prompt", agentText("video_prompt"));
  if (action === "delete_selection") {
    const ids = new Set(selected.map(node => node.id));
    const edges = document.edges.filter(edge => ids.has(edge.source) || ids.has(edge.target));
    return {
      ok: false, needs_ticket: true, action_id: action, focus_ids: [...ids],
      message: agentText("delete_title"),
      ticket: {
        ticket_type: "delete", node_count: ids.size,
        node_list: selected.map(node => ({id: node.id, title: node.title || node.id})),
        cascade_edge_count: edges.length, edges,
      },
    };
  }
  const place = (node, index) => { node.x = 40 + (index % 4) * 280; node.y = 50 + Math.floor(index / 4) * 230; };
  if (action === "arrange_selected" || action === "organize_canvas") {
    const targets = action === "organize_canvas" ? document.nodes : document.nodes.filter(node => selected.some(item => item.id === node.id));
    targets.forEach(place);
    const focus = targets.map(node => node.id);
    return {ok: true, action_id: action, message: label, focus_ids: focus, nodes: document.nodes, edges: document.edges};
  }
  if (action === "group_selection") {
    const group = "group-" + selected[0].id;
    for (const node of document.nodes) if (selected.some(item => item.id === node.id)) node.group = group;
    return {ok: true, action_id: action, message: label, focus_ids: selected.map(node => node.id), nodes: document.nodes, edges: document.edges, group};
  }
  if (action === "ungroup_node") {
    for (const node of document.nodes) if (selected.some(item => item.id === node.id)) node.group = "";
    return {ok: true, action_id: action, message: label, focus_ids: [selected[0].id], nodes: document.nodes, edges: document.edges};
  }
  if (action === "duplicate_node_with_upstream") {
    const wanted = new Set(selected.map(node => node.id));
    let grew = true;
    while (grew) {
      grew = false;
      for (const edge of document.edges) if (wanted.has(edge.target) && !wanted.has(edge.source)) { wanted.add(edge.source); grew = true; }
    }
    const created = [];
    const map = new Map();
    document.nodes.filter(node => wanted.has(node.id)).forEach((node, index) => {
      const id = "agent-copy-" + node.id + "-" + (document.nodes.length + index);
      map.set(node.id, id);
      const copy = {...node, id, x: (node.x || 0) + 48, y: (node.y || 0) + 48, title: (node.title || node.id) + " 副本"};
      document.nodes.push(copy);
      created.push(id);
    });
    for (const edge of [...document.edges]) if (map.has(edge.source) && map.has(edge.target)) {
      document.edges.push({...edge, id: "agent-edge-" + map.get(edge.source), source: map.get(edge.source), target: map.get(edge.target)});
    }
    return {ok: true, action_id: action, message: label, focus_ids: created, created_ids: created, nodes: document.nodes, edges: document.edges};
  }
  if (action === "create_generator_from_selection" || action === "create_video_generator_and_run") {
    const id = "agent-" + action + "-" + document.nodes.length;
    const node = {id, type: action === "create_video_generator_and_run" ? "video" : "image", title: label, x: 40 + document.nodes.length * 24, y: 80, text: String(request.prompt || request.text || ""), params: {}, media_id: null, job_id: null, group: ""};
    document.nodes.push(node);
    for (const source of selected) document.edges.push({id: "agent-edge-" + source.id + "-" + id, source: source.id, target: id, port: "prompt"});
    return {ok: true, action_id: action, message: label, focus_ids: [id], created_ids: [id], nodes: document.nodes, edges: document.edges, run: action === "create_video_generator_and_run"};
  }
  if (action === "update_generator_prompt") {
    const target = document.nodes.find(node => node.id === selected[0].id);
    target.text = String(request.prompt).trim();
    return {ok: true, action_id: action, message: label, focus_ids: [target.id], nodes: document.nodes, edges: document.edges};
  }
  if (action === "run_selected_node" || action === "retry_selected_node" || action === "cancel_selected_node") {
    const target = document.nodes.find(node => node.id === selected[0].id);
    target.params = {...(target.params || {}), agent_run: action};
    return {ok: true, action_id: action, message: label, focus_ids: [target.id], nodes: document.nodes, edges: document.edges};
  }
  return fail("frontend_action_not_supported", agentText("unsupported", {actionId: action}));
}

export function createAgentTransport(options) {
  let closed = false;
  let attempt = 0;
  const schedule = options.schedule || ((fn, ms) => setTimeout(fn, ms));
  async function read(reader) {
    let buffer = "";
    const decoder = typeof TextDecoder === "function" ? new TextDecoder() : null;
    while (!closed) {
      const step = await reader.read();
      if (step.done) break;
      const chunk = typeof step.value === "string" ? step.value : decoder.decode(step.value, {stream: true});
      const parsed = parseSseChunk(buffer, chunk);
      buffer = parsed.rest;
      for (const event of parsed.events) options.onEvent?.(event);
    }
  }
  async function sse() {
    const response = await options.fetchImpl(options.url, {headers: {...(options.headers || {}), Accept: "text/event-stream"}, credentials: "same-origin"});
    const reader = response?.body?.getReader?.();
    if (!reader) { await poll(); return "poll"; }
    options.onMode?.("sse");
    await read(reader);
    if (closed) return "sse";
    attempt += 1;
    const delay = reconnectDelay(attempt);
    if (delay.exhausted) { options.onLost?.(delay.message); return "lost"; }
    schedule(() => { if (!closed) sse().catch(error => options.onLost?.(error?.message || agentText("connection_lost_reopen"))); }, delay.ms);
    return "sse";
  }
  async function poll() {
    options.onMode?.("poll");
    if (options.api) {
      const body = await options.api(options.pollUrl || options.url, {headers: {...(options.headers || {}), Accept: "application/json"}});
      options.onSnapshot?.(body);
      return "poll";
    }
    const response = await options.fetchImpl(options.pollUrl || options.url, {headers: {...(options.headers || {}), Accept: "application/json"}, credentials: "same-origin"});
    const body = typeof response.json === "function" ? await response.json() : response;
    options.onSnapshot?.(body);
    return "poll";
  }
  const started = options.forcePoll || !options.fetchImpl ? poll() : sse();
  return {close() { closed = true; }, started};
}

function h(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function snapshotOk(value) {
  return Boolean(value && Array.isArray(value.sessions));
}

export async function mountCanvasAgentStream(s, bridge) {
  try {
    const panel = s?.agentPanel;
    if (!panel || typeof document === "undefined") return;
    panel.classList.add("cc-agent-stream-on");
    let root = panel.querySelector(":scope > .cc-agent-stream") || panel.querySelector(".cc-agent-stream");
    if (!root) {
      root = h("section", null, "cc-agent-stream");
      panel.append(root);
    }
    const view = {snapshot: null};
    const paint = () => renderStream(root, s, bridge, view);
    s.agentStreamSync = () => { if (view.snapshot) paint(); };
    const headers = typeof bridge.headers === "function" ? bridge.headers() : {};
    const streamUrl = bridge.url(s) + "/agent/stream";
    let snap = null;
    try { snap = await bridge.api(streamUrl, {headers: {...headers, Accept: "application/json"}}); } catch { snap = null; }
    view.snapshot = snapshotOk(snap) ? snap : null;
    paint();
    if (!view.snapshot) return;
    const eventsUrl = bridge.url(s) + "/agent/events?after=" + encodeURIComponent(view.snapshot.cursor || 0);
    const transport = createAgentTransport({
      url: eventsUrl,
      pollUrl: eventsUrl,
      headers,
      api: bridge.api,
      fetchImpl: typeof fetch === "function" ? fetch : null,
      forcePoll: typeof fetch !== "function" || !fetch?.toString,
      onEvent(event) {
        if (!event || event.event === "heartbeat") return;
        view.snapshot = applyStreamEvent(view.snapshot, {kind: event.event, id: event.id, seq: event.id, payload: event.data, data: event.data});
        paint();
      },
      onSnapshot(body) {
        if (snapshotOk(body)) { view.snapshot = body; paint(); }
        else if (Array.isArray(body?.events)) {
          for (const event of body.events) view.snapshot = applyStreamEvent(view.snapshot, event);
          paint();
        }
      },
      onLost(message) {
        const line = root.querySelector(".cc-agent-stream-status");
        if (line) line.textContent = message || agentText("connection_lost_reopen");
      },
    });
    s.agentStreamClose = () => transport.close();
    transport.started.catch(() => {});
  } catch {
    /* Legacy agent controls stay usable when the stream panel cannot mount. */
  }
}

function renderStream(root, s, bridge, view) {
  const snap = view.snapshot;
  root.replaceChildren();
  const head = h("header", null, "cc-agent-stream-head");
  head.append(h("h2", "Agent", "cc-agent-stream-title"));
  if (!snap) {
    root.append(head, h("p", agentText("empty_session"), "cc-agent-stream-status"));
    return;
  }
  const picker = document.createElement("select");
  picker.className = "cc-agent-stream-sessions";
  picker.setAttribute("aria-label", agentText("switch_session"));
  for (const session of snap.sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = session.title || "未命名会话";
    if (session.id === snap.current_session_id) option.selected = true;
    picker.append(option);
  }
  picker.addEventListener("change", () => command(s, bridge, view, {action: "select_session", session_id: picker.value}));
  const create = h("button", agentText("new_session"), "cc-agent-stream-new");
  create.type = "button";
  create.addEventListener("click", () => command(s, bridge, view, {action: "create_session"}));
  const rename = h("button", agentText("rename"), "cc-agent-stream-rename");
  rename.type = "button";
  rename.addEventListener("click", () => renameSession(root, s, bridge, view));
  const remove = h("button", agentText("delete"), "cc-agent-stream-delete");
  remove.type = "button";
  remove.addEventListener("click", () => confirmDelete(root, s, bridge, view));
  head.append(picker, create, rename, remove);
  const tier = h("button", snap.auto_approve ? agentText("perm_bypass") : agentText("perm_ask"), "cc-agent-stream-tier");
  tier.type = "button";
  tier.title = snap.auto_approve ? agentText("perm_bypass_tip") : agentText("perm_ask_tip");
  tier.addEventListener("click", () => command(s, bridge, view, {action: "set_prefs", session_id: snap.current_session_id, auto_approve: !snap.auto_approve, tier_seen: true}));
  head.append(tier);
  root.append(head);
  if (snap.current_session_id && snap.prefs && snap.prefs.tier_seen === false && !readFlag("vsc-agent-tier-seen")) {
    root.append(tierDialog(s, bridge, view));
  }
  const log = h("div", null, "cc-agent-stream-log");
  if (snap.has_older) {
    const older = h("button", agentText("load_older"), "cc-agent-stream-older");
    older.type = "button";
    older.addEventListener("click", async () => {
      older.textContent = agentText("loading_older");
      const page = await bridge.api(bridge.url(s) + "/agent/stream?session_id=" + encodeURIComponent(snap.current_session_id) + "&before_id=" + encodeURIComponent(snap.older_cursor) + "&limit=30", {headers: {...bridge.headers(), Accept: "application/json"}});
      if (snapshotOk(page)) {
        view.snapshot = {...snap, messages: [...page.messages, ...snap.messages], has_older: page.has_older, older_cursor: page.older_cursor};
        renderStream(root, s, bridge, view);
      }
    });
    log.append(older);
  }
  for (const message of snap.messages || []) log.append(messageCard(s, bridge, view, message));
  log.append(toolCard(snap.tools || []));
  if (snap.question_batch?.status === "pending") log.append(questionCard(s, bridge, view, snap.question_batch));
  for (const ticket of snap.tickets || []) if (ticket.status === "pending") log.append(ticketCard(s, bridge, view, ticket));
  root.append(log);
  const batch = batchAuthSummary(snap.tickets || []);
  if (batch.count) {
    const bar = h("div", null, "cc-agent-stream-batch");
    bar.append(h("strong", batch.title), h("p", batch.detail));
    const go = h("button", agentText("batch_go"), "cc-agent-stream-batch-go");
    go.type = "button";
    go.addEventListener("click", () => command(s, bridge, view, {action: "authorize_batch", session_id: snap.current_session_id}));
    bar.append(go);
    root.append(bar);
  }
  root.append(composer(s, bridge, view, snap));
  const status = h("p", "", "cc-agent-stream-status");
  root.append(status);
}

function messageCard(s, bridge, view, message) {
  const card = h("article", null, "cc-agent-stream-message cc-agent-stream-" + (message.role || "user"));
  card.dataset.messageId = message.id || "";
  card.append(h("p", message.error_text || message.text || ""));
  if (message.role === "assistant") {
    const up = h("button", agentText("like"), "cc-agent-stream-like");
    const down = h("button", agentText("dislike"), "cc-agent-stream-dislike");
    up.type = down.type = "button";
    const send = verdict => command(s, bridge, view, {action: "feedback", session_id: view.snapshot.current_session_id, message_id: message.id, verdict: message.feedback === verdict ? "clear" : verdict});
    up.addEventListener("click", () => send("up"));
    down.addEventListener("click", () => send("down"));
    if (message.feedback === "up") up.setAttribute("aria-pressed", "true");
    if (message.feedback === "down") down.setAttribute("aria-pressed", "true");
    card.append(up, down);
  }
  return card;
}

function toolCard(tools) {
  const wrap = h("div", null, "cc-agent-stream-tools");
  const groups = new Map();
  for (const tool of tools) {
    const category = tool.category || tool.payload?.category || "tool";
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(tool);
  }
  for (const [category, steps] of groups) {
    const details = document.createElement("details");
    details.className = "cc-agent-stream-tool";
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = agentText(category === "skill" ? "skill" : category) || category;
    details.append(summary);
    const body = h("div", null, "cc-agent-stream-tool-body");
    for (const step of steps) body.append(h("p", summarizeToolStep(step).join(" · ") || (step.name || step.payload?.name || "")));
    const toggle = h("button", agentText("collapse"), "cc-agent-stream-tool-toggle");
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      details.open = !details.open;
      toggle.textContent = details.open ? agentText("collapse") : agentText("expand");
    });
    details.append(body, toggle);
    wrap.append(details);
  }
  return wrap;
}

function questionCard(s, bridge, view, batch) {
  const card = h("form", null, "cc-agent-stream-question");
  card.append(h("h3", agentText("question_title")));
  const items = batch.payload?.items || [];
  for (const item of items) {
    const block = h("fieldset", null, "cc-agent-stream-q");
    block.append(h("legend", (item.prompt || "") + " · " + agentText(item.required ? "required" : "optional")));
    if (item.kind === "text" || !item.options?.length) {
      const input = document.createElement("textarea");
      input.name = item.id;
      input.maxLength = item.max_length || 1000;
      input.placeholder = "请输入你的回答";
      block.append(input);
    } else {
      for (const option of item.options) {
        const label = h("label", option.label || option.id);
        const input = document.createElement("input");
        input.type = item.kind === "multi" ? "checkbox" : "radio";
        input.name = item.id;
        input.value = option.id;
        label.prepend(input);
        block.append(label);
      }
      const custom = document.createElement("input");
      custom.name = item.id + ":custom";
      custom.placeholder = agentText("custom");
      if (item.max_length) custom.maxLength = item.max_length;
      block.append(custom);
    }
    card.append(block);
  }
  const submit = h("button", agentText("submit"), "cc-agent-stream-answer");
  submit.type = "button";
  submit.addEventListener("click", () => {
    const answers = items.map(item => {
      const selected = [...card.querySelectorAll(`[name="${CSS.escape(item.id)}"]:checked`)].map(node => node.value);
      const customNode = card.querySelector(`[name="${CSS.escape(item.id + ":custom")}"]`);
      const textNode = card.querySelector(`[name="${CSS.escape(item.id)}"]`);
      const custom = customNode ? customNode.value : (textNode && textNode.type !== "radio" && textNode.type !== "checkbox" ? textNode.value : "");
      return {question_id: item.id, selected_option_ids: selected, custom_text: typeof custom === "string" ? custom : ""};
    });
    const check = validateQuestionBatch(batch.payload, answers, false);
    if (!check.ok) { status(card, check.message); return; }
    command(s, bridge, view, {action: "answer", batch_id: batch.id, version: batch.version, answers});
  });
  const skip = h("button", agentText("skip"), "cc-agent-stream-skip");
  skip.type = "button";
  skip.addEventListener("click", () => command(s, bridge, view, {action: "answer", batch_id: batch.id, version: batch.version, skip: true, answers: []}));
  const cancel = h("button", agentText("question_cancel"), "cc-agent-stream-qcancel");
  cancel.type = "button";
  cancel.addEventListener("click", () => command(s, bridge, view, {action: "answer", batch_id: batch.id, version: batch.version, skip: true, cancel: true, answers: []}));
  card.append(submit, skip, cancel);
  return card;
}

function ticketCard(s, bridge, view, ticket) {
  const body = ticket.payload || {};
  const kind = body.ticket_type || "paid";
  const card = h("article", null, "cc-agent-stream-ticket");
  card.append(h("h3", kind === "delete" ? agentText("delete_title") : agentText("paid_title")));
  if (kind === "delete") {
    card.append(h("p", "删除节点数 " + (body.node_count ?? "")));
    card.append(h("p", "级联删除连线 " + (body.cascade_edge_count ?? "")));
    for (const node of body.node_list || []) card.append(h("p", node.title || node.id, "cc-agent-stream-node"));
  } else {
    card.append(h("p", "操作 " + (body.operation || "")));
    card.append(h("p", "模型 " + (body.model || "")));
    card.append(h("p", "单价 × 数量 " + (body.unit_price ?? "") + " × " + (body.quantity ?? "")));
    card.append(h("p", "合计积分 " + (body.total_credits ?? "")));
  }
  card.append(h("p", "绑定画布版本 " + (body.canvas_version ?? "")));
  card.append(h("p", "票据有效期至 " + (body.expires_at || "")));
  const blockers = ticketBlockers(body);
  if (blockers.approve_disabled) card.append(h("p", blockers.message, "cc-agent-stream-ticket-lock"));
  const approve = h("button", agentText("approve"), "cc-agent-stream-approve");
  approve.type = "button";
  approve.disabled = blockers.approve_disabled;
  const remember = document.createElement("input");
  remember.type = "checkbox";
  remember.className = "cc-agent-stream-remember";
  if (kind !== "delete") {
    const rememberLabel = h("label", "本次会话不再询问同类付费操作");
    rememberLabel.prepend(remember);
    card.append(rememberLabel);
  }
  approve.addEventListener("click", () => command(s, bridge, view, {action: "authorize", authorization_id: ticket.id, approve: true, remember_session: Boolean(remember.checked) && kind !== "delete"}));
  const reject = h("button", agentText("reject"), "cc-agent-stream-reject");
  reject.type = "button";
  const reason = document.createElement("input");
  reason.placeholder = "拒绝理由（可选，会反馈给助手调整方案）";
  reason.className = "cc-agent-stream-reason";
  reject.addEventListener("click", () => command(s, bridge, view, {action: "authorize", authorization_id: ticket.id, approve: false, reason: reason.value}));
  card.append(reason, approve, reject);
  return card;
}

function composer(s, bridge, view, snap) {
  const box = h("div", null, "cc-agent-stream-composer");
  const model = document.createElement("select");
  model.setAttribute("aria-label", agentText("chat_model"));
  for (const id of ["grok", "grok-fast"]) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = agentText("chat_model") + " · " + id;
    if (snap.prefs?.chat_model === id) option.selected = true;
    model.append(option);
  }
  const effort = document.createElement("select");
  effort.setAttribute("aria-label", "推理强度");
  for (const id of [["low", "低强度"], ["medium", "中强度"], ["high", "高强度"]]) {
    const option = document.createElement("option");
    option.value = id[0];
    option.textContent = id[1];
    if ((snap.prefs?.reasoning_effort || "medium") === id[0]) option.selected = true;
    effort.append(option);
  }
  const skill = document.createElement("select");
  skill.setAttribute("aria-label", "会话技能");
  const currentSkill = snap.prefs?.selected_skill || s.agentSkill?.value || "vsc-script";
  const skills = [
    ["vsc-script", "文字与分镜建议"],
    ["vsc-assets", "素材与图像创作"],
    ["vsc-direct", "镜头运行准备"],
  ];
  if (currentSkill && !skills.some(item => item[0] === currentSkill)) skills.unshift([currentSkill, currentSkill]);
  for (const [id, label] of skills) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = label;
    if (id === currentSkill) option.selected = true;
    skill.append(option);
  }
  const chosen = new Set(snap.prefs?.preferred_model_ids || []);
  const catalog = (typeof bridge.models === "function" ? bridge.models() : bridge.models) || [];
  const modelBox = h("div", null, "cc-agent-stream-models");
  modelBox.append(h("p", "生成模型偏好", "cc-agent-stream-hint"));
  for (const item of catalog.filter(row => row && row.enabled !== false).slice(0, 8)) {
    const label = h("label", item.model_key || item.id);
    const check = document.createElement("input");
    check.type = "checkbox";
    check.value = item.id;
    check.checked = chosen.has(item.id);
    check.addEventListener("change", () => {
      if (check.checked) chosen.add(item.id);
      else chosen.delete(item.id);
      if (chosen.size > 8) { chosen.delete(item.id); check.checked = false; status(rootFrom(box), "最多选择 8 个模型"); return; }
      command(s, bridge, view, {action: "set_prefs", session_id: snap.current_session_id, preferred_model_ids: [...chosen], chat_model: model.value, reasoning_effort: effort.value, selected_skill: skill.value});
    });
    label.prepend(check);
    modelBox.append(label);
  }
  const input = document.createElement("textarea");
  input.className = "cc-agent-stream-input";
  input.rows = 3;
  input.placeholder = agentText("input_placeholder");
  const send = h("button", agentText("send"), "cc-agent-stream-send");
  send.type = "button";
  send.addEventListener("click", () => sendStream(s, bridge, view, input, {chat_model: model.value, reasoning_effort: effort.value, selected_skill: skill.value, model_ids: [...chosen]}));
  const stop = h("button", agentText("stop"), "cc-agent-stream-stop");
  stop.type = "button";
  stop.disabled = !snap.active_turn;
  stop.addEventListener("click", () => command(s, bridge, view, {action: "stop", session_id: snap.current_session_id, turn_id: snap.active_turn?.id}));
  const steer = h("button", agentText("steer_confirm_button"), "cc-agent-stream-steer");
  steer.type = "button";
  steer.addEventListener("click", () => steerQueue(rootFrom(box), s, bridge, view));
  const savePrefs = () => command(s, bridge, view, {action: "set_prefs", session_id: snap.current_session_id, chat_model: model.value, reasoning_effort: effort.value, selected_skill: skill.value, preferred_model_ids: [...chosen]});
  model.addEventListener("change", savePrefs);
  effort.addEventListener("change", savePrefs);
  skill.addEventListener("change", savePrefs);
  box.append(h("p", agentText("chat_model_hint"), "cc-agent-stream-hint"), model, effort, skill, modelBox, input, send, stop, steer);
  return box;
}

function rootFrom(node) { return node.closest(".cc-agent-stream"); }

async function sendStream(s, bridge, view, input, prefs) {
  const snap = view.snapshot;
  if (!snap?.current_session_id) {
    await command(s, bridge, view, {action: "create_session"});
  }
  if (s.dirty || s.pending) {
    const saved = await bridge.save(s);
    if (!saved) { status(rootFrom(input), agentText("canvas_save_incomplete")); return; }
  }
  const nodeIds = [...(s.selected || [])];
  const text = referenceOnlyPrompt(input.value, {nodes: nodeIds, attachments: s.agentAttachments || []});
  if (!text) { status(rootFrom(input), "请输入新的消息。"); return; }
  await command(s, bridge, view, {
    action: "set_prefs", session_id: view.snapshot.current_session_id,
    chat_model: prefs.chat_model, reasoning_effort: prefs.reasoning_effort, selected_skill: prefs.selected_skill,
  });
  const result = await command(s, bridge, view, {
    action: "send", session_id: view.snapshot.current_session_id, canvas_revision: s.version,
    message: text === agentText("reference_only_prompt") && !input.value.trim() ? "" : input.value,
    node_ids: nodeIds, attachment_media_ids: (s.agentAttachments || []).map(item => item.id),
    skill_id: prefs.selected_skill, model_ids: prefs.model_ids || snap.prefs?.preferred_model_ids || [],
  });
  if (result) input.value = "";
}

function steerQueue(root, s, bridge, view) {
  const item = (view.snapshot.queue || [])[0];
  const active = view.snapshot.active_turn;
  if (!item || !active) { status(root, "当前没有可插队的消息"); return; }
  const go = () => command(s, bridge, view, {action: "steer", session_id: view.snapshot.current_session_id, queue_item_id: item.id, expected_active_turn_id: active.id});
  if (readFlag("vsc-agent-steer-ack")) { go(); return; }
  const dialog = h("div", null, "cc-agent-stream-dialog");
  dialog.append(h("h3", agentText("steer_confirm_title")), h("p", agentText("steer_confirm_message")));
  const ok = h("button", agentText("steer_confirm_button"), "cc-agent-stream-steer-ok");
  ok.type = "button";
  ok.addEventListener("click", () => { writeFlag("vsc-agent-steer-ack"); dialog.remove(); go(); });
  const cancel = h("button", agentText("cancel"));
  cancel.type = "button";
  cancel.addEventListener("click", () => dialog.remove());
  dialog.append(ok, cancel);
  root.append(dialog);
}

function renameSession(root, s, bridge, view) {
  const session = (view.snapshot.sessions || []).find(item => item.id === view.snapshot.current_session_id);
  const box = h("div", null, "cc-agent-stream-renamebox");
  const input = document.createElement("input");
  input.maxLength = 30;
  input.value = session?.title || "";
  input.setAttribute("aria-label", "输入会话标题");
  const ok = h("button", agentText("confirm"));
  ok.type = "button";
  ok.addEventListener("click", () => {
    const title = input.value.trim();
    if (!title || title.length > 30) { status(root, agentText("rename_invalid")); return; }
    command(s, bridge, view, {action: "rename_session", session_id: session.id, title});
  });
  box.append(input, ok);
  root.append(box);
}

function confirmDelete(root, s, bridge, view) {
  const session = (view.snapshot.sessions || []).find(item => item.id === view.snapshot.current_session_id);
  if (!session) return;
  if ((view.snapshot.sessions || []).find(item => item.id === session.id)?.has_active_turn || view.snapshot.active_turn) {
    status(root, agentText("busy_delete"));
    return;
  }
  const dialog = h("div", null, "cc-agent-stream-dialog");
  dialog.append(h("p", agentText("delete_confirm", {title: session.title || "未命名会话"})));
  const ok = h("button", agentText("confirm"), "cc-agent-stream-delete-ok");
  ok.type = "button";
  ok.addEventListener("click", () => command(s, bridge, view, {action: "delete_session", session_id: session.id}));
  dialog.append(ok);
  root.append(dialog);
}

function tierDialog(s, bridge, view) {
  const dialog = h("div", null, "cc-agent-stream-dialog cc-agent-stream-tier-dialog");
  dialog.append(h("h3", agentText("tier_title")), h("p", agentText("perm_ask_tip")), h("p", agentText("perm_bypass_tip")));
  const ask = h("button", agentText("perm_ask"));
  const bypass = h("button", agentText("perm_bypass"));
  ask.type = bypass.type = "button";
  const choose = auto => { writeFlag("vsc-agent-tier-seen"); command(s, bridge, view, {action: "set_prefs", session_id: view.snapshot.current_session_id, tier_seen: true, auto_approve: auto}); };
  ask.addEventListener("click", () => choose(false));
  bypass.addEventListener("click", () => choose(true));
  dialog.append(ask, bypass);
  return dialog;
}

function status(root, text) {
  if (!root) return;
  const line = root.querySelector(".cc-agent-stream-status");
  if (line) line.textContent = text;
  else root.append(h("p", text, "cc-agent-stream-status"));
}

async function command(s, bridge, view, payload) {
  try {
    const result = await bridge.auxiliaryWrite(s, "agent-stream:" + payload.action + ":" + Date.now(), bridge.url(s) + "/agent/stream", {canvas_id: s.id, ...payload});
    if (result?.revision != null) bridge.revision?.(s, result.revision);
    const snap = await bridge.api(bridge.url(s) + "/agent/stream", {headers: {...bridge.headers(), Accept: "application/json"}});
    if (snapshotOk(snap)) view.snapshot = snap;
    const root = s.agentPanel?.querySelector(".cc-agent-stream");
    if (root) renderStream(root, s, bridge, view);
    if (payload.action === "authorize" && result?.status === "approved" && result.ticket_type === "delete") applyDelete(s, bridge, result);
    return result;
  } catch (error) {
    const root = s.agentPanel?.querySelector(".cc-agent-stream");
    const readable = classifyAgentError(error?.code || error?.message || error).message;
    const message = error?.message && /[\u4e00-\u9fff]/.test(error.message) ? error.message : readable;
    status(root, message);
    return null;
  }
}

function applyDelete(s, bridge, result) {
  const ids = new Set(result.node_ids || []);
  if (!ids.size || typeof bridge.change !== "function") return;
  bridge.change(s, () => {
    s.document.nodes = s.document.nodes.filter(node => !ids.has(node.id));
    s.document.edges = s.document.edges.filter(edge => !ids.has(edge.source) && !ids.has(edge.target));
  });
}

export async function runCanvasAction(s, bridge, request) {
  const sessionId = s.agentStreamSession || request.session_id;
  const started = sessionId ? await bridge.auxiliaryWrite(s, "agent-action-start:" + (request.action_id || "") + ":" + Date.now(), bridge.url(s) + "/agent/stream", {
    action: "action_event", session_id: sessionId, event: "frontend_action_started", action_id: request.action_id || request.action, message: request.action_id || "",
  }).catch(() => null) : null;
  const result = executeCanvasAction({nodes: s.document?.nodes || [], edges: s.document?.edges || [], selected: [...(s.selected || [])]}, request);
  if (result.ok && result.nodes && typeof bridge.change === "function") {
    bridge.change(s, () => { s.document.nodes = result.nodes; s.document.edges = result.edges; });
  }
  const focusId = result.focus_ids?.[0];
  const node = focusId && s.document?.nodes?.find(item => item.id === focusId);
  if (node && typeof bridge.focusNode === "function") bridge.focusNode(s, node);
  if (result.dialog && typeof bridge.openEditor === "function" && node) await bridge.openEditor(s, result.dialog, node.id);
  if (sessionId) {
    await bridge.auxiliaryWrite(s, "agent-action-done:" + (request.action_id || "") + ":" + Date.now(), bridge.url(s) + "/agent/stream", {
      action: "action_event", session_id: sessionId,
      event: result.ok ? "frontend_action_completed" : "frontend_action_failed",
      action_id: request.action_id || request.action, message: result.message, focus_ids: result.focus_ids || [],
    }).catch(() => null);
  }
  return {result, started};
}

function readFlag(key) {
  try { return sessionStorage.getItem(key) === "1"; } catch { return false; }
}
function writeFlag(key) {
  try { sessionStorage.setItem(key, "1"); } catch { /* ignore private mode */ }
}
