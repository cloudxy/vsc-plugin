// Shared governance header navigation, return-context capsule, and 3-way settings cross-link banner.
export const GOVERNANCE_ITEMS = Object.freeze([
  Object.freeze({id: 'access', label: '账户与团队', href: '?page=access'}),
  Object.freeze({id: 'commerce', label: '会员与钱包', href: '?page=commerce'}),
  Object.freeze({id: 'service-operations', label: '开放接口与运维', href: '?page=service-operations'}),
]);

export const SETTINGS_SURFACES = Object.freeze([
  Object.freeze({
    id: 'api-settings',
    badge: '①',
    label: '角色合成台浏览器/CLI 订阅凭据',
    hint: 'localStorage Key 与 AGY / Grok / Codex 本机登录',
    href: '?page=api-settings',
  }),
  Object.freeze({
    id: 'settings',
    badge: '②',
    label: '项目生产模型与环境变量注册表',
    hint: 'PostgreSQL 权威路由（仅存 ARK_AGENT_PLAN_API_KEY 等变量引用名）',
    href: '?page=settings',
  }),
  Object.freeze({
    id: 'engine',
    badge: '③',
    label: '外部调用 vsc-engine OpenAPI Key',
    hint: '第三方调用 VSC 工作台的受限 Bearer Key',
    href: '?page=service-operations&subview=engine',
  }),
]);

export function returnContextStorageKey(actor) {
  const key = String(actor || '').trim();
  return key ? `vsc.admin.returnContext.${key}` : '';
}

export function isSafeReturnSearch(search) {
  if (typeof search !== 'string' || !search.startsWith('?') || search.length > 2048) return false;
  if (/[\u0000-\u001f\u007f\\]/.test(search)) return false;
  if (search.includes('//')) return false;
  if (/^\?\s*[a-z][a-z0-9+.-]*:/i.test(search)) return false;
  if (/(?:[?&][^=]*=)\s*(?:javascript|data|vbscript|file|https?|ftp):/i.test(search)) return false;
  return true;
}

export function formatReturnContextLabel(ctx) {
  if (!ctx || typeof ctx !== 'object') return '';
  const rawTitle = String(ctx.projectTitle || ctx.projectId || '原项目').trim() || '原项目';
  const epRaw = String(ctx.episodeLabel || '').trim()
    || (ctx.episodeId ? `第${String(ctx.episodeId).trim()}集` : '');
  return epRaw ? `← 返回《${rawTitle}》· ${epRaw}` : `← 返回《${rawTitle}》`;
}

export function createGovernanceNav({active = '', returnContext = null, onSwitch = null, onReturn = null, doc = globalThis.document} = {}) {
  const d = doc || globalThis.document;
  const wrap = d.createElement('div');
  wrap.className = 'gov-header-tools';
  wrap.setAttribute('role', 'region');
  wrap.setAttribute('aria-label', '平台治理切换');

  const resolvedCtx = typeof returnContext === 'function' ? returnContext() : returnContext;
  if (resolvedCtx && resolvedCtx.projectId && isSafeReturnSearch(resolvedCtx.search)) {
    const back = d.createElement('button');
    back.type = 'button';
    back.className = 'gov-return-pill';
    back.dataset.returnProject = String(resolvedCtx.projectId);
    const labelText = formatReturnContextLabel(resolvedCtx);
    back.textContent = labelText;
    back.setAttribute('aria-label', labelText);
    back.setAttribute('title', labelText);
    back.addEventListener('click', () => {
      if (onReturn) return onReturn(resolvedCtx);
    });
    wrap.append(back);
  }

  const tabs = d.createElement('div');
  tabs.className = 'gov-module-tabs';
  tabs.setAttribute('role', 'group');
  tabs.setAttribute('aria-label', '治理模块切换');
  for (const item of GOVERNANCE_ITEMS) {
    const link = d.createElement('a');
    link.className = item.id === active ? 'gov-module-tab active' : 'gov-module-tab';
    link.href = item.href;
    link.dataset.govTarget = item.id;
    link.textContent = item.label;
    if (item.id === active) link.setAttribute('aria-current', 'page');
    link.addEventListener('click', event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (onSwitch) {
        event.preventDefault?.();
        return onSwitch(item.id, item.href);
      }
    });
    tabs.append(link);
  }
  wrap.append(tabs);
  return wrap;
}

export function createSettingsCrossNav({active = '', onNavigate = null, doc = globalThis.document} = {}) {
  const d = doc || globalThis.document;
  const bar = d.createElement('div');
  bar.className = 'gov-settings-guide';
  bar.setAttribute('role', 'note');
  bar.setAttribute('aria-label', '三套设置与接口职责边界导流');

  const prefix = d.createElement('span');
  prefix.className = 'gov-settings-guide-label';
  prefix.textContent = '配置边界导流：';
  bar.append(prefix);

  for (const item of SETTINGS_SURFACES) {
    const isCurrent = item.id === active;
    if (isCurrent) {
      const current = d.createElement('span');
      current.className = 'gov-settings-chip active';
      current.dataset.settingsSurface = item.id;
      current.setAttribute('aria-current', 'true');
      current.setAttribute('title', item.hint);
      current.textContent = `${item.badge} ${item.label}（当前）`;
      bar.append(current);
    } else {
      const link = d.createElement('a');
      link.className = 'gov-settings-chip';
      link.href = item.href;
      link.dataset.settingsSurface = item.id;
      link.setAttribute('title', item.hint);
      link.textContent = `${item.badge} ${item.label} →`;
      link.addEventListener('click', event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (onNavigate) {
          event.preventDefault?.();
          return onNavigate(item.id, item.href);
        }
      });
      bar.append(link);
    }
  }
  return bar;
}

export const createSettingsTriageBanner = createSettingsCrossNav;
