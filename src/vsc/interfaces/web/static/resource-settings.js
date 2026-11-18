import {msg,joinMessages,setText,bindAttribute} from './i18n.js';
// Resource configuration uses the existing local human session; secrets never enter this form.
const labels = {
  identity_ref: msg("ui.identity_reference"),
  image_edit: msg("ui.image_editing_maps_57"),
  first_frame: msg("ui.shot_first_frame"),
  last_frame: msg("ui.shot_last_frame"),
  image_to_video: msg("ui.image_to_video"),
  dialogue_dry: msg("ui.voiceover"),
  sfx: msg("agent.overseas_remake_dialogue_type_sound_effect"),
  bgm: msg("ui.music_scoring"),
};
const connectionLabels = {
  not_configured: msg("ui.not_configured"),
  not_loaded: msg("ui.not_loaded_in_this_process"),
  loaded: msg("ui.loaded_not_verified_online"),
  loaded_unverified: msg("ui.loaded_not_verified_online"),
  not_connected: msg("ui.not_connected"),
  runtime_unavailable: msg("ui.official_sdk_missing_or_incompatible"),
  invalid_configuration: msg("ui.configuration_needs_correction"),
  unverified: msg("ui.not_verified_online"),
  host_managed: msg("ui.managed_by_host"),
  unsupported: msg("ui.not_connected"),
  ready: msg("ui.configuration_available_generation_quality_requires_testing"),
};
const ENV_REF_RE = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
const SENSITIVE_KEY_RE = /(secret|api[_-]?key|token|password|authorization)/i;
const KLING_FALLBACK_PRESET = {
  id: 'kling-image',
  supplier: 'kling',
  product: 'kling',
  plan: 'api',
  region: 'cn-beijing',
  execution: 'api',
  modality: 'image',
  model_key: 'kling-v2-1',
  model_version: 'v2-1',
  base_url: 'https://api-beijing.klingai.com',
  auth_ref: 'KLING_ACCESS_KEY',
  capabilities: {purposes: ['identity_ref', 'image_edit', 'first_frame', 'last_frame'], reference_media: true},
  default_params: {resolution: '2k'},
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) setText(n, text);
  return n;
}
function option(value, label) {
  const n = el('option', '', label);
  n.value = value;
  return n;
}
function hasSensitiveParamKey(value) {
  if (!value || typeof value !== 'object') return false;
  if (Array.isArray(value)) return value.some(hasSensitiveParamKey);
  for (const [k, v] of Object.entries(value)) {
    if (SENSITIVE_KEY_RE.test(k)) return true;
    if (hasSensitiveParamKey(v)) return true;
  }
  return false;
}

export function compatibleConfigurations(rows, purpose) {
  return rows.filter(row => row.enabled && row.adapter_available !== false && (row.capabilities?.purposes || []).includes(purpose));
}

export function mountResourceSettingsPanel(container, ctx = {}, options = {}) {
  const {api, session = () => ({}), onNotice, openSession, onSectionChange} = ctx;
  const initialSection = options.initialSection || ctx.initialSection || 'models';
  const autoLoad = options.autoLoad !== false;
  const showHeading = options.showHeading !== false;

  let data = {configurations: [], defaults: {}, presets: [], tools: []};
  let selected = null;
  let view = ['models', 'defaults', 'updates'].includes(initialSection) ? initialSection : 'models';
  let loading = 0;
  let isInitialLoading = false;
  let loadFailedMessage = '';
  let busy = false;
  let disposed = false;
  let pendingDraft = null;
  let authRefError = '';

  const wrap = el('section', 'resource-settings-panel cs-section');
  wrap.dataset.component = 'production-routes-panel';
  wrap.setAttribute('data-component', 'production-routes-panel');

  const topHead = el('div', 'rs-panel-header');
  if (showHeading) {
    const copy = el('div', 'rs-panel-copy');
    copy.append(
      el('h2', '', '项目生产模型注册表、默认用途与官方工具更新'),
      el('p', 'hint', '后台生产路由权威（PostgreSQL）：仅保存 ~/.zshenv 环境变量名称（如 ARK_AGENT_PLAN_API_KEY、KLING_ACCESS_KEY），严禁填入密钥明文。配置仅对新任务生效，已固定任务保留原配置。'),
    );
    topHead.append(copy);
  } else {
    topHead.append(el('p', 'hint', msg("ui.configurations_apply_to_new_tasks_fixed_tasks_retain_their")));
  }

  const tabs = el('div', 'settings-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', '生产模型路由子栏');
  const tabDefs = [
    ['models', msg("ui.models_and_connections")],
    ['defaults', msg("ui.default_purposes")],
    ['updates', msg("ui.official_updates")],
  ];
  const tabButtons = new Map();
  tabDefs.forEach(([id, label], idx) => {
    const b = el('button', 'rs-subtab-btn', label);
    b.type = 'button';
    b.dataset.routeSection = id;
    b.setAttribute('role', 'tab');
    const selectTab = () => {
      view = id;
      onSectionChange?.(id);
      render();
    };
    b.addEventListener('click', selectTab);
    b.addEventListener('keydown', event => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault?.();
        const nextIdx = event.key === 'ArrowRight'
          ? (idx + 1) % tabDefs.length
          : (idx - 1 + tabDefs.length) % tabDefs.length;
        const nextId = tabDefs[nextIdx][0];
        view = nextId;
        onSectionChange?.(nextId);
        render();
        tabButtons.get(nextId)?.focus?.();
      }
    });
    tabs.append(b);
    tabButtons.set(id, b);
  });
  topHead.append(tabs);

  const content = el('div', 'settings-content');
  const result = el('p', 'settings-result');
  result.setAttribute('role', 'status');

  wrap.append(topHead, content, result);
  container.replaceChildren(wrap);

  function report(message) {
    setText(result, message || '');
  }
  function canWrite() {
    const s = session?.() || {};
    return Boolean(s.actor && s.csrf);
  }
  async function write(path, body = {}) {
    if (!canWrite()) throw new Error('请先建立本机人工操作会话');
    return api('/api/v1/resource-settings' + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session().csrf},
      body: JSON.stringify(body),
    });
  }
  async function action(fn) {
    if (busy || disposed) return;
    busy = true;
    render();
    try {
      await fn();
    } catch (error) {
      if (!disposed) report(error?.message || String(error));
    } finally {
      busy = false;
      if (!disposed) render();
    }
  }
  async function reload() {
    if (!api || disposed) return;
    const request = ++loading;
    if (!data.configurations?.length) isInitialLoading = true;
    loadFailedMessage = '';
    render();
    try {
      const value = await api('/api/v1/resource-settings');
      if (request !== loading || disposed) return;
      isInitialLoading = false;
      data = value && typeof value === 'object' ? value : {configurations: [], defaults: {}, presets: [], tools: []};
      render();
    } catch (error) {
      if (request !== loading || disposed) return;
      isInitialLoading = false;
      loadFailedMessage = error?.message || '无法连接本机工作台服务（/api/v1/resource-settings）';
      report(loadFailedMessage);
      render();
      throw error;
    }
  }
  function button(text, fn, disabled = false, cls = '') {
    const b = el('button', cls, text);
    b.type = 'button';
    b.disabled = disabled || busy;
    b.addEventListener('click', () => action(fn));
    return b;
  }
  function statusText(row) {
    const raw = row.connection_status;
    return typeof raw === 'object'
      ? (raw.message || connectionLabels[raw.status] || raw.status)
      : connectionLabels[raw] || raw || '未检测';
  }
  function makeField(form, fieldMap, label, name, value = '', type = 'text') {
    const l = el('label', 'field', label);
    const input = el('input');
    input.name = name;
    input.type = type;
    input.value = value ?? '';
    input.autocomplete = 'off';
    fieldMap.set(name, input);
    l.append(input);
    form.append(l);
    return {label: l, input};
  }
  function makeSelect(form, fieldMap, label, name, values, current) {
    const l = el('label', 'field', label);
    const input = el('select');
    input.name = name;
    for (const [v, t] of values) input.append(option(v, t));
    input.value = current || values[0]?.[0] || '';
    fieldMap.set(name, input);
    l.append(input);
    form.append(l);
    return input;
  }

  function render() {
    if (disposed) return;
    for (const [id, b] of tabButtons) {
      const active = view === id;
      b.setAttribute('aria-selected', String(active));
      b.classList.toggle('is-active', active);
      b.tabIndex = active ? 0 : -1;
    }
    content.replaceChildren();
    if (!canWrite()) {
      const roBar = el('div', 'rs-callout rs-callout-info');
      roBar.append(el('span', '', '🔒 当前处于只读浏览状态：需在右上角「个人中心 → 本机操作凭据」建立人工操作会话后，方可新建配置、修改默认用途或执行官方更新。'));
      if (typeof openSession === 'function') {
        const loginBtn = el('button', 'rs-inline-btn', '建立本机操作会话');
        loginBtn.type = 'button';
        loginBtn.addEventListener('click', () => openSession());
        roBar.append(loginBtn);
      }
      content.append(roBar);
    }
    if (loadFailedMessage) {
      const offBar = el('div', 'rs-callout rs-callout-warn');
      offBar.append(
        el('span', '', `⚠ 无法连接本机工作台服务（/api/v1/resource-settings）：${loadFailedMessage}。当前表单草稿已保留在页面中。`),
        button('重新加载生产配置', () => reload().catch(() => {}), false, 'rs-inline-btn'),
      );
      content.append(offBar);
    }
    if (isInitialLoading) {
      const skel = el('div', 'rs-skeleton-wrap');
      skel.setAttribute('aria-busy', 'true');
      skel.append(el('p', 'hint', msg("ui.loading_resource_configuration")));
      content.append(skel);
      return;
    }
    if (view === 'models') renderModels();
    else if (view === 'defaults') renderDefaults();
    else renderUpdates();
  }

  function renderModels() {
    if (data.available === false) {
      const dbWarn = el('div', 'rs-callout rs-callout-err');
      dbWarn.append(el('span', '', data.message || data.reason || msg("ui.resource_configuration_database_is_disconnected_configure_postgresql_using_the")));
      content.append(dbWarn);
    }
    const grid = el('div', 'settings-grid');
    const list = el('aside', 'settings-list');
    const detail = el('section', 'settings-detail');
    grid.append(list, detail);
    content.append(grid);

    list.append(button(msg("ui.new_configuration"), () => {
      selected = null;
      pendingDraft = null;
      authRefError = '';
    }, !canWrite() || data.available === false));

    const configs = data.configurations || [];
    if (!configs.length && data.available !== false && !loadFailedMessage) {
      list.append(el('p', 'hint rs-empty-hint', '尚未登记项目生产模型路由。选择右侧「快手可灵」或「字节火山方舟」预设并绑定 ~/.zshenv 环境变量名，即可供后台批次任务调用。'));
    }
    for (const row of configs) {
      const b = button(row.name || row.model_key, () => {
        selected = row.id;
        pendingDraft = null;
        authRefError = '';
      });
      b.classList.toggle('selected', selected === row.id);
      b.append(el('small', '', joinMessages(["", row.supplier || row.provider_id, " · ", row.modality, " · ", row.auth_ref || row.default_params?.resolution || row.model_version, " · ", row.enabled ? msg("ui.enable") : msg("ui.disable"), ""])));
      list.append(b);
    }

    const savedRow = configs.find(r => r.id === selected) || {};
    const row = pendingDraft ? {...savedRow, ...pendingDraft} : savedRow;
    detail.append(el('h3', '', savedRow.id ? msg("ui.edit_configuration") : msg("ui.new_configuration_more_60")));

    const form = el('form', 'settings-form');
    const fieldMap = new Map();
    let reuseModelId = pendingDraft?.reuse_model_id || '';
    const accounts = configs.filter(r => r.modality === 'video' && r.capabilities?.video_draft === true);
    const account = !savedRow.id && accounts.length
      ? makeSelect(form, fieldMap, msg("ui.provider_account"), 'reuse_model_id', [['', msg("ui.create_independent_connection")], ...accounts.map(r => [r.id, `${r.name} · ${r.default_params?.resolution || r.model_version}`])], reuseModelId)
      : null;

    const presets = Array.isArray(data.presets) ? data.presets : Object.values(data.presets || {});
    if (presets.length) {
      const preset = el('select', 'settings-preset-select');
      bindAttribute(preset, 'aria-label', msg("ui.provider_preset"));
      preset.append(option('', msg("ui.choose_provider_preset")));
      for (const p of presets) preset.append(option(p.id || p.supplier, p.name || p.label || p.supplier));
      preset.disabled = !canWrite();
      preset.addEventListener('change', () => {
        const p = presets.find(x => (x.id || x.supplier) === preset.value);
        if (!p) return;
        authRefError = '';
        for (const name of ['name', 'supplier', 'product', 'plan', 'region', 'execution', 'base_url', 'auth_ref', 'tool_id', 'modality', 'model_key', 'model_version']) {
          const ctrl = fieldMap.get(name);
          if (ctrl && p[name] != null) ctrl.value = p[name];
        }
        check.checked = p.enabled === true;
        if (p.default_params) textarea.value = JSON.stringify(p.default_params, null, 2);
        if (p.capabilities) {
          capabilities.value = JSON.stringify(p.capabilities, null, 2);
          for (const c of purposeChecks) c.checked = (p.capabilities.purposes || []).includes(c.value);
        }
      });
      detail.append(preset);
    }

    makeField(form, fieldMap, msg("ui.configuration_name"), 'name', row.name).input.required = true;
    const supplier = makeSelect(form, fieldMap, msg("ui.provider"), 'supplier', [
      ['volcengine', msg("ui.volcengine_ark")],
      ['kling', '快手可灵 (Kling AI)'],
      ['alibaba', msg("ui.alibaba_cloud_model_studio")],
      ['xai', 'xAI'],
      ['openai', 'OpenAI'],
      ['mureka', 'Mureka'],
      ['fal', 'fal.ai'],
    ], row.supplier || 'volcengine');
    makeField(form, fieldMap, msg("ui.product"), 'product', row.product || (supplier.value === 'kling' ? 'kling' : 'ark')).input.required = true;
    makeField(form, fieldMap, msg("ui.plan"), 'plan', row.plan || (supplier.value === 'kling' ? 'api' : 'agent-plan')).input.required = true;
    makeSelect(form, fieldMap, msg("ui.invocation_method"), 'execution', [
      ['api', msg("ui.official_api")],
      ['official_sdk', msg("ui.official_python_sdk_fixed_environment")],
      ['official_skill', msg("ui.official_skill_method_reference")],
      ['official_cli', msg("ui.official_cli_interactive_reference")],
      ['host_tool', msg("ui.host_built_in_tool")],
    ], row.execution || 'api');
    makeSelect(form, fieldMap, msg("ui.media_type"), 'modality', [
      ['image', msg("agent.media_image")],
      ['video', msg("classic.video_noun")],
      ['audio', msg("asset.audio")],
    ], row.modality || 'image');
    makeField(form, fieldMap, msg("ui.model_identifier"), 'model_key', row.model_key).input.required = true;
    makeField(form, fieldMap, msg("ui.model_version"), 'model_version', row.model_version || '').input.required = true;

    const defaultAuthRef = row.auth_ref !== undefined
      ? row.auth_ref
      : (supplier.value === 'kling' ? 'KLING_ACCESS_KEY' : 'ARK_AGENT_PLAN_API_KEY');
    const authRefField = makeField(form, fieldMap, msg("ui.credential_environment_variable_name"), 'auth_ref', defaultAuthRef);
    const authHint = el('small', 'rs-field-hint', '仅填 ~/.zshenv 环境变量名：快手可灵填 KLING_ACCESS_KEY（自动配对同前缀 KLING_SECRET_KEY）或单密钥 KLING_API_KEY；火山方舟填 ARK_AGENT_PLAN_API_KEY。严禁粘贴密钥明文。');
    authRefField.label.append(authHint);
    if (authRefError) {
      authRefField.label.append(el('span', 'rs-field-error', authRefError));
    }

    const capabilities = el('textarea');
    capabilities.name = 'capabilities';
    capabilities.value = typeof row.raw_capabilities === 'string'
      ? row.raw_capabilities
      : JSON.stringify(row.capabilities || {}, null, 2);
    fieldMap.set('capabilities', capabilities);

    const purposeBox = el('fieldset', 'settings-purposes');
    purposeBox.append(el('legend', '', msg("ui.applicable_purposes")));
    const purposes = [...(data.purposes || Object.entries(labels).map(([id, label]) => ({id, label})))];
    for (const id of row.capabilities?.purposes || []) {
      if (!purposes.some(p => p.id === id)) purposes.push({id, label: id + '（已登记用途）'});
    }
    const purposeChecks = [];
    for (const item of purposes) {
      const code = item.id, label = item.label;
      const l = el('label'), c = el('input');
      c.type = 'checkbox';
      c.name = 'purpose';
      c.value = code;
      c.checked = (row.capabilities?.purposes || []).includes(code);
      purposeChecks.push(c);
      l.append(c, document.createTextNode(label));
      purposeBox.append(l);
    }
    form.append(purposeBox);

    const advanced = el('details', 'settings-advanced');
    advanced.append(el('summary', '', msg("ui.advanced_settings")));
    const advancedFields = el('div', 'settings-form');
    makeField(advancedFields, fieldMap, msg("ui.region"), 'region', row.region || 'cn-beijing').input.required = true;
    makeField(advancedFields, fieldMap, msg("ui.endpoint"), 'base_url', row.base_url || (supplier.value === 'kling' ? 'https://api-beijing.klingai.com' : 'https://ark.cn-beijing.volces.com/api/plan/v3'));
    makeField(advancedFields, fieldMap, msg("ui.official_tool_identifier_optional"), 'tool_id', row.tool_id || '');
    const parameters = el('label', 'field', msg("ui.default_parameters_json"));
    const textarea = el('textarea');
    textarea.name = 'default_params';
    textarea.value = typeof row.raw_default_params === 'string'
      ? row.raw_default_params
      : JSON.stringify(row.default_params || {}, null, 2);
    fieldMap.set('default_params', textarea);
    parameters.append(textarea);
    const capabilityLabel = el('label', 'field', msg("ui.verified_capability_parameters_json"));
    capabilityLabel.append(capabilities);
    advancedFields.append(parameters, capabilityLabel);
    advanced.append(advancedFields);
    form.append(advanced);

    const enabled = el('label', 'settings-inline');
    const check = el('input');
    check.type = 'checkbox';
    check.name = 'enabled';
    check.checked = row.enabled !== false;
    fieldMap.set('enabled', check);
    enabled.append(check, document.createTextNode('启用此配置'));
    form.append(enabled);

    const save = el('button', 'primary', msg("ui.save_configuration"));
    save.type = 'submit';
    save.disabled = !canWrite() || busy || data.available === false;
    form.append(save);

    if (!canWrite()) {
      for (const ctrl of fieldMap.values()) ctrl.disabled = true;
      for (const c of purposeChecks) c.disabled = true;
    }

    form.addEventListener('submit', event => {
      event.preventDefault?.();
      if (!canWrite()) {
        report('请先建立本机人工操作会话');
        return;
      }
      const payload = {};
      for (const name of ['name', 'supplier', 'product', 'plan', 'region', 'execution', 'modality', 'model_key', 'model_version', 'auth_ref', 'base_url', 'tool_id']) {
        payload[name] = String(fieldMap.get(name)?.value || '').trim();
      }
      payload.enabled = Boolean(check.checked);
      const checkedPurposes = purposeChecks.filter(c => c.checked).map(c => c.value);

      // Preserve user draft before validation or network request (GWT-03.2 / edge-states §2.2)
      pendingDraft = {
        ...payload,
        reuse_model_id: reuseModelId,
        raw_default_params: textarea.value,
        raw_capabilities: capabilities.value,
        capabilities: {purposes: checkedPurposes},
      };

      if (payload.auth_ref && !ENV_REF_RE.test(payload.auth_ref)) {
        authRefError = '✕ 凭据环境变量名格式无效：仅允许填写 ~/.zshenv 中的大写/下划线变量标识符（如 KLING_ACCESS_KEY 或 ARK_AGENT_PLAN_API_KEY），严禁直接粘贴 sk- 等密钥明文。';
        report(authRefError);
        render();
        return;
      }
      authRefError = '';

      let parsedCapabilities;
      try {
        parsedCapabilities = JSON.parse(capabilities.value || '{}');
      } catch {
        report(msg("ui.capability_parameters_require_valid_json"));
        return;
      }
      let parsedParams;
      try {
        parsedParams = JSON.parse(textarea.value || '{}');
      } catch {
        report(msg("ui.default_parameters_require_valid_json"));
        return;
      }
      if (hasSensitiveParamKey(parsedParams) || hasSensitiveParamKey(parsedCapabilities)) {
        const msgText = '✕ 默认参数 JSON 中禁止包含 secret、api_key、token 等敏感字段，请移除后再保存。';
        report(msgText);
        return;
      }

      payload.capabilities = {...parsedCapabilities, purposes: checkedPurposes};
      payload.default_params = parsedParams;
      if (savedRow.id) payload.id = savedRow.id;
      if (reuseModelId) payload.reuse_model_id = reuseModelId;
      if (!payload.tool_id) delete payload.tool_id;

      action(async () => {
        const saved = await write('/configurations', {payload});
        pendingDraft = null;
        selected = saved.id || saved.configuration?.id || null;
        await reload();
        report(msg("ui.configuration_saved_select_the_new_version_in_default_purposes"));
      });
    });

    supplier.addEventListener('change', () => {
      const preset = presets.find(p => p.supplier === supplier.value)
        || (supplier.value === 'kling' ? KLING_FALLBACK_PRESET : null);
      authRefError = '';
      for (const name of ['product', 'plan', 'region', 'base_url', 'auth_ref', 'tool_id', 'model_key', 'model_version']) {
        const ctrl = fieldMap.get(name);
        if (ctrl) ctrl.value = preset?.[name] || '';
      }
      if (preset?.modality && fieldMap.get('modality')) {
        fieldMap.get('modality').value = preset.modality;
      }
      check.checked = false;
      fieldMap.get('execution').value = preset?.execution || 'api';
      capabilities.value = JSON.stringify(preset?.capabilities || {}, null, 2);
      textarea.value = JSON.stringify(preset?.default_params || {}, null, 2);
      for (const c of purposeChecks) c.checked = (preset?.capabilities?.purposes || []).includes(c.value);
      report(msg("ui.provider_preset_changed_enter_the_actual_model_configuration_for"));
    });

    account?.addEventListener('change', () => {
      reuseModelId = account.value;
      const source = accounts.find(r => r.id === reuseModelId);
      const presetChoice = detail.querySelector('.settings-preset-select');
      if (presetChoice) presetChoice.disabled = Boolean(source);
      for (const name of ['name', 'supplier', 'product', 'plan', 'region', 'execution', 'base_url', 'auth_ref', 'tool_id', 'modality', 'model_key']) {
        const input = fieldMap.get(name);
        if (!input) continue;
        input.disabled = Boolean(source);
        if (source) input.value = source[name] ?? '';
      }
      if (!source) return;
      fieldMap.get('model_version').value = source.model_version + '-1080p';
      textarea.value = JSON.stringify({...source.default_params, resolution: '1080p'}, null, 2);
      capabilities.value = JSON.stringify({...source.capabilities, purposes: ['video_upgrade'], video_operations: ['draft_upgrade']}, null, 2);
      for (const c of purposeChecks) c.checked = c.value === 'video_upgrade';
      check.checked = false;
      report(msg("ui.reuse_the_same_provider_account_as_the_selected_configuration"));
    });

    detail.append(form);

    if (savedRow.id) {
      detail.append(el('p', 'hint rs-status-line', statusText(savedRow)));
      const controls = el('div', 'settings-actions');
      controls.append(
        button(msg("ui.check_configuration"), async () => {
          const value = await write(`/configurations/${encodeURIComponent(savedRow.id)}/check`);
          report(value.message || statusText(value));
          await reload();
        }, !canWrite()),
        button(msg("ui.view_registered_models"), async () => {
          const value = await write(`/configurations/${encodeURIComponent(savedRow.id)}/models`);
          report([value.message, `模型列表：${(value.models || []).map(m => typeof m === 'string' ? m : m.model_key || m.id || m.name).join('、') || '未返回可用模型'}`].filter(Boolean).join('\n'));
        }, !canWrite()),
        button(savedRow.enabled ? msg("ui.disable") : msg("ui.enable"), async () => {
          await write(`/configurations/${encodeURIComponent(savedRow.id)}/enabled`, {enabled: !savedRow.enabled});
          await reload();
          report(msg("ui.enabled_state_updated"));
        }, !canWrite()),
      );
      detail.append(controls);
    }

    detail.append(el('p', 'hint', msg("ui.save_only_credential_references_never_secret_values_configuration_checks")));
    detail.append(el('p', 'hint', msg("ui.the_server_fixes_the_official_sdk_version_and_environment")));
  }

  function renderDefaults() {
    const purposes = Array.isArray(data.purposes) ? data.purposes : Object.keys(data.purposes || labels);
    if (!purposes.length) {
      content.append(el('p', 'empty', msg("ui.no_configurable_purposes")));
      return;
    }
    for (const item of purposes) {
      const code = typeof item === 'string' ? item : item.id || item.purpose;
      const box = el('form', 'settings-default');
      const labelText = typeof item === 'string' ? (labels[code] || code) : item.label || labels[code] || code;
      box.append(el('label', '', labelText));
      const s = el('select');
      bindAttribute(s, 'aria-label', labels[code] || code);
      s.append(option('', msg("ui.no_default")));
      const current = data.defaults?.[code];
      const compat = compatibleConfigurations(data.configurations || [], code);
      for (const row of compat) {
        s.append(option(row.id, joinMessages(["", row.name, " · ", row.model_key, ""])));
      }
      s.value = typeof current === 'object' ? current.configuration_id : current || '';
      s.disabled = !canWrite() || busy || data.available === false;
      const b = el('button', 'primary', msg("common.save"));
      b.type = 'submit';
      b.disabled = !canWrite() || busy || data.available === false;
      box.append(s, b);
      box.addEventListener('submit', e => {
        e.preventDefault?.();
        const id = s.value;
        action(async () => {
          await write('/defaults', {purpose: code, configuration_id: id || null});
          await reload();
          report(msg("ui.default_purpose_saved_applies_only_to_new_tasks"));
        });
      });
      content.append(box);
    }
  }

  function renderUpdates() {
    content.append(button(msg("ui.check_official_updates"), async () => {
      const response = await write('/updates/check');
      data.tools = Array.isArray(response) ? response : response.tools || response.items || [];
      report(msg("ui.check_complete_choose_to_update_or_keep_the_current"));
    }, !canWrite(), 'primary'));
    if (!(data.tools || []).length) {
      content.append(el('p', 'hint', msg("ui.check_versions_of_registered_official_tools_a_failed_check")));
    }
    for (const tool of data.tools || []) {
      const box = el('article', 'settings-tool');
      box.append(
        el('h3', '', tool.name || tool.id),
        el('p', 'hint', msg("ui.current_value0_value1_value2", {
          value0: tool.current_revision || tool.current_version || msg("ui.not_installed"),
          value1: tool.official ? msg("ui.official_version") : msg("ui.source_version"),
          value2: tool.latest_revision || tool.latest_version || msg("ui.unverified"),
        })),
      );
      if (tool.message || tool.summary) box.append(el('p', '', tool.message || tool.summary));
      const updateAvailable = tool.can_update === true || tool.update_available === true || tool.status === 'update_available';
      if (updateAvailable) {
        const actions = el('div', 'settings-actions');
        actions.append(
          button(msg("ui.update"), async () => {
            try {
              const value = await write(`/updates/${encodeURIComponent(tool.id)}`, {expected_revision: tool.latest_revision || tool.latest_version});
              report(value.message || msg("ui.update_complete"));
              await reload();
            } catch (error) {
              if (error?.status === 409 || /409|conflict|revision/i.test(String(error?.message || ''))) {
                throw new Error('目标工具版本已发生变化（远端已推进至新修订号），本次未执行覆盖。请重新点击「检查官方更新」核对最新版本后再确认更新。');
              }
              throw error;
            }
          }, !canWrite(), 'primary'),
          button(msg("ui.keep_current_version"), () => {
            tool.can_update = false;
            tool.update_available = false;
            tool.status = 'kept';
            tool.message = '本次保留当前版本。';
          }),
        );
        box.append(actions);
      } else {
        box.append(el('p', 'hint', ['current', 'up_to_date'].includes(tool.status)
          ? msg("ui.already_up_to_date")
          : tool.status === 'host_managed'
            ? msg("ui.updates_managed_by_host")
            : tool.status === 'kept'
              ? msg("ui.keep_current_version_more_66")
              : tool.status === 'unavailable'
                ? msg("ui.cannot_check_for_updates_now")
                : msg("ui.view_status_explanation")));
      }
      content.append(box);
    }
  }

  render();
  if (autoLoad) {
    reload().catch(error => {
      onNotice?.(error?.message || String(error));
    });
  }

  return {
    reload,
    refresh: reload,
    report,
    getSection: () => view,
    setSection(nextSection) {
      if (['models', 'defaults', 'updates'].includes(nextSection) && nextSection !== view) {
        view = nextSection;
        render();
      }
    },
    destroy() {
      disposed = true;
      loading++;
    },
  };
}

export function createResourceSettings(dialog, {api, session, onNotice} = {}) {
  const title = el('div', 'dialog-header');
  title.append(el('h2', '', msg("ui.resource_configuration")));
  const close = el('button', '', msg("common.close"));
  close.type = 'button';
  close.addEventListener('click', () => dialog.close?.());
  title.append(close);
  const bodyHost = el('div', 'rs-dialog-body');
  dialog.replaceChildren(title, bodyHost);
  const panel = mountResourceSettingsPanel(bodyHost, {api, session, onNotice}, {autoLoad: false, showHeading: false});
  return {
    async open() {
      if (!dialog.open) dialog.showModal?.();
      panel.report(msg("ui.loading_resource_configuration"));
      try {
        await panel.reload();
        panel.report('');
      } catch (error) {
        panel.report(error.message);
        onNotice?.(error.message);
      }
    },
    refresh: panel.reload,
  };
}
