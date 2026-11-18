// Shared Personal Center governance header navigation and persistent 3-state return capsule.
export const GOVERNANCE_ITEMS = Object.freeze([
  Object.freeze({id: 'access', label: '账户与团队', href: '?page=access'}),
  Object.freeze({id: 'commerce', label: '会员与钱包', href: '?page=commerce'}),
  Object.freeze({id: 'service-operations', label: '服务与开放接口', href: '?page=service-operations'}),
]);

export const SETTINGS_SURFACES = Object.freeze([]);

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
  if (!ctx || typeof ctx !== 'object') return '← 返回工作台首页';
  if (ctx.origin === 'character-studio' && !ctx.projectId) {
    return '← 返回 AI 角色合成台';
  }
  if (!ctx.projectId) return '← 返回工作台首页';
  const rawTitle = String(ctx.projectTitle || ctx.projectId || '原项目').trim() || '原项目';
  const epRaw = String(ctx.episodeLabel || '').trim()
    || (ctx.episodeId ? `第${String(ctx.episodeId).trim()}集` : '');
  return epRaw ? `← 返回《${rawTitle}》· ${epRaw}` : `← 返回《${rawTitle}》`;
}

export function resolveReturnPillState(returnContext) {
  const ctx = typeof returnContext === 'function' ? returnContext() : returnContext;
  if (ctx && typeof ctx === 'object') {
    if (ctx.projectId && !ctx.unavailable && isSafeReturnSearch(ctx.search)) {
      return {
        state: 'project',
        label: formatReturnContextLabel(ctx),
        projectId: String(ctx.projectId),
        href: ctx.search,
        context: ctx,
      };
    }
    if (ctx.origin === 'character-studio' && !ctx.projectId && (!ctx.search || isSafeReturnSearch(ctx.search))) {
      const search = ctx.search && isSafeReturnSearch(ctx.search) ? ctx.search : '?page=character-studio';
      return {
        state: 'character-studio',
        label: '← 返回 AI 角色合成台',
        origin: 'character-studio',
        href: search,
        context: {...ctx, origin: 'character-studio', projectId: null, search},
      };
    }
  }
  return {
    state: 'home',
    label: '← 返回工作台首页',
    fallback: 'home',
    href: '?page=home',
    context: null,
  };
}

export function createReturnPill(returnContextOrOptions = null, onReturnArg = null, {doc = globalThis.document} = {}) {
  let returnContext = returnContextOrOptions;
  let onReturn = onReturnArg;
  let d = doc || globalThis.document;
  if (
    returnContextOrOptions
    && typeof returnContextOrOptions === 'object'
    && ('returnContext' in returnContextOrOptions || 'onReturn' in returnContextOrOptions || 'doc' in returnContextOrOptions)
    && onReturnArg === null
  ) {
    returnContext = returnContextOrOptions.returnContext ?? null;
    onReturn = returnContextOrOptions.onReturn ?? null;
    d = returnContextOrOptions.doc || d;
  }

  const resolved = resolveReturnPillState(returnContext);
  const back = d.createElement('button');
  back.type = 'button';
  back.className = 'gov-return-pill';
  back.dataset.component = 'context-return-pill';
  back.setAttribute('data-component', 'context-return-pill');
  if (resolved.state === 'project') {
    back.dataset.returnProject = resolved.projectId;
    back.setAttribute('data-return-project', resolved.projectId);
  } else if (resolved.state === 'character-studio') {
    back.dataset.returnOrigin = 'character-studio';
    back.setAttribute('data-return-origin', 'character-studio');
  } else {
    back.dataset.returnFallback = 'home';
    back.setAttribute('data-return-fallback', 'home');
  }
  back.textContent = resolved.label;
  back.setAttribute('aria-label', resolved.label);
  back.setAttribute('title', resolved.label);
  back.addEventListener('click', () => {
    if (onReturn) return onReturn(resolved.context, resolved);
    if (typeof globalThis.location !== 'undefined' && globalThis.location) {
      globalThis.location.search = resolved.href;
    }
  });
  return back;
}

export function createGovernanceNav({active = '', returnContext = null, onSwitch = null, onReturn = null, doc = globalThis.document} = {}) {
  const d = doc || globalThis.document;
  const wrap = d.createElement('div');
  wrap.className = 'gov-header-tools';
  wrap.setAttribute('role', 'region');
  wrap.setAttribute('aria-label', '个人中心模块切换');

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
  wrap.append(tabs, createReturnPill(returnContext, onReturn, {doc: d}));
  return wrap;
}

// Retired 3-way settings triage banner (FR-01 / GWT-01.4); kept as safe null-returning exports for backward compatibility.
export function createSettingsCrossNav() {
  return null;
}

export const createSettingsTriageBanner = createSettingsCrossNav;
