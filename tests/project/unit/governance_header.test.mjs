import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';

class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase();
    this._text = text;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.dataset = {};
    this.className = '';
    this.parentElement = null;
  }
  set textContent(v) {
    this._text = String(v ?? '');
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map(c => c.textContent).join('');
  }
  append(...nodes) {
    for (const node of nodes) {
      if (!node) continue;
      node.parentElement = this;
      this.children.push(node);
    }
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
  }
  getAttribute(k) {
    return this.attrs[k] ?? null;
  }
  addEventListener(k, fn) {
    (this.listeners[k] ??= []).push(fn);
  }
  async fire(type, props = {}) {
    let prevented = false;
    const ev = {target: this, preventDefault() { prevented = true; }, ...props};
    for (const fn of this.listeners[type] || []) await fn(ev);
    return prevented;
  }
}

const document = {
  createElement: tag => new Element(tag),
  createTextNode: text => new Element('#text', text),
};

test('isSafeReturnSearch enforces SEC-05 open-redirect and protocol guards', async () => {
  const mod = await loadModule('governance-header.js', {document});
  assert.equal(mod.isSafeReturnSearch('?project=proj-1&page=studio&episode=ep-2'), true);
  assert.equal(mod.isSafeReturnSearch(''), false);
  assert.equal(mod.isSafeReturnSearch('/home'), false);
  assert.equal(mod.isSafeReturnSearch('?next=//evil.example'), false);
  assert.equal(mod.isSafeReturnSearch('?url=javascript:alert(1)'), false);
  assert.equal(mod.isSafeReturnSearch('?url=https://evil.example'), false);
  assert.equal(mod.isSafeReturnSearch('?url=data:text/html,hi'), false);
  assert.equal(mod.isSafeReturnSearch('?bad=a\\b'), false);
  assert.equal(mod.isSafeReturnSearch('?bad=a\u0000b'), false);
  assert.equal(mod.returnContextStorageKey('id-42'), 'vsc.admin.returnContext.id-42');
  assert.equal(mod.formatReturnContextLabel({projectId: 'p1', projectTitle: '星辰S1', episodeLabel: '第2集'}), '← 返回《星辰S1》· 第2集');
  assert.equal(mod.formatReturnContextLabel({origin: 'character-studio', search: '?page=character-studio'}), '← 返回 AI 角色合成台');
  assert.equal(mod.formatReturnContextLabel(null), '← 返回工作台首页');
  assert.deepEqual(
    mod.GOVERNANCE_ITEMS.map(item => [item.id, item.label]),
    [
      ['access', '账户与团队'],
      ['commerce', '会员与钱包'],
      ['service-operations', '服务与开放接口'],
    ]
  );
});

test('createGovernanceNav and createReturnPill enforce persistent 3-state return pill and retire settings triage banners', async () => {
  const mod = await loadModule('governance-header.js', {document});
  const switched = [];
  let returnedCtx = 'unset';

  // State 1: Valid project returnContext -> ← 返回《项目名》· 第3集
  const nav = mod.createGovernanceNav({
    active: 'commerce',
    returnContext: () => ({projectId: 'proj-9', projectTitle: '古风S2', episodeId: '3', search: '?project=proj-9&page=workbench'}),
    onSwitch: (id, href) => switched.push([id, href]),
    onReturn: ctx => { returnedCtx = ctx; },
    doc: document,
  });

  const pill = nav.children.find(c => c.className === 'gov-return-pill');
  assert.ok(pill);
  assert.equal(pill.textContent, '← 返回《古风S2》· 第3集');
  assert.equal(pill.getAttribute('data-return-project'), 'proj-9');
  await pill.fire('click');
  assert.equal(returnedCtx.projectId, 'proj-9');

  const tabs = nav.children.find(c => c.className === 'gov-module-tabs');
  assert.equal(tabs.children.length, 3);
  const activeTab = tabs.children.find(c => c.dataset.govTarget === 'commerce');
  assert.equal(activeTab.getAttribute('aria-current'), 'page');
  const opsTab = tabs.children.find(c => c.dataset.govTarget === 'service-operations');
  assert.equal(opsTab.textContent, '服务与开放接口');
  await opsTab.fire('click', {metaKey: true});
  assert.equal(switched.length, 0);
  await opsTab.fire('click');
  assert.deepEqual(switched, [['service-operations', '?page=service-operations']]);

  // State 2: Standalone character-studio origin -> ← 返回 AI 角色合成台
  let studioReturned = null;
  const studioPill = mod.createReturnPill(
    () => ({origin: 'character-studio', search: '?page=character-studio'}),
    ctx => { studioReturned = ctx; },
    {doc: document}
  );
  assert.equal(studioPill.textContent, '← 返回 AI 角色合成台');
  assert.equal(studioPill.getAttribute('data-return-origin'), 'character-studio');
  await studioPill.fire('click');
  assert.equal(studioReturned.origin, 'character-studio');

  // State 3a: Unsafe returnContext search -> falls back to ← 返回工作台首页 and passes null to onReturn (SEC-05)
  let fallbackArg = 'not-called';
  const unsafeNav = mod.createGovernanceNav({
    active: 'access',
    returnContext: {projectId: 'proj-9', search: '?next=//evil.example'},
    onReturn: ctx => { fallbackArg = ctx; },
    doc: document,
  });
  const unsafePill = unsafeNav.children.find(c => c.className === 'gov-return-pill');
  assert.ok(unsafePill);
  assert.equal(unsafePill.textContent, '← 返回工作台首页');
  assert.equal(unsafePill.getAttribute('data-return-fallback'), 'home');
  await unsafePill.fire('click');
  assert.equal(fallbackArg, null);

  // State 3b: Missing or recycled/unavailable project -> ← 返回工作台首页
  const recycledPill = mod.createReturnPill(
    {projectId: 'proj-deleted', projectTitle: '已删除剧目', unavailable: true, search: '?project=proj-deleted&page=workbench'},
    null,
    {doc: document}
  );
  assert.equal(recycledPill.textContent, '← 返回工作台首页');
  assert.equal(recycledPill.getAttribute('data-return-fallback'), 'home');

  // Retired cross-nav / triage banner helpers return null cleanly (zero .gov-settings-guide clutter)
  assert.equal(mod.createSettingsCrossNav({active: 'api-settings', doc: document}), null);
  assert.equal(mod.createSettingsTriageBanner({active: 'engine', doc: document}), null);
});

test('Personal Center #account-menu HTML, F-001 panel.js bindings, zero inline styles, and zero-jump shell CSS hold', () => {
  const webRoot = path.resolve(import.meta.dirname, '../../../src/vsc/interfaces/web');
  const html = fs.readFileSync(path.join(webRoot, 'templates/index.html'), 'utf8');
  const panelJs = fs.readFileSync(path.join(webRoot, 'static/panel.js'), 'utf8');
  const shellCss = fs.readFileSync(path.join(webRoot, 'static/workbench-shell.css'), 'utf8');

  // ZERO inline style="..." attributes in templates/index.html
  assert.equal(/\sstyle\s*=\s*["']/.test(html), false, 'templates/index.html must contain zero inline style attributes');

  // #account-menu Personal Center label + 3 unified entries + retired #resource-settings-open removed
  assert.match(html, /id="account-menu"[\s\S]*?<span class="account-menu-label">个人中心<\/span>/);
  assert.match(html, /id="access-open"[^>]*>账户与团队<\/button>/);
  assert.match(html, /id="invoice-open"[^>]*>会员与钱包<\/button>/);
  assert.match(html, /id="service-operations-open"[^>]*>服务与开放接口<\/button>/);
  assert.equal(html.includes('id="resource-settings-open"'), false);
  assert.match(html, /id="api-settings-open"[^>]*aria-label="API 接口配置"/);
  assert.match(html, /<dialog id="resource-settings-dialog"(?![^>]*\bopen\b)[^>]*>/);

  // F-001 fixed in panel.js: #invoice-open opens wallet, #access-open is not overwritten by workspace.account, hub in syncRoute, /guide preserved
  assert.match(panelJs, /\$\('access-open'\)\?\.addEventListener\('click',guard\(\(\)=>openAccess\(\{area:'workspace'\}\)\)\)/);
  assert.match(panelJs, /\$\('invoice-open'\)\?\.addEventListener\('click',guard\(\(\)=>navigateModule\('commerce','wallet',null\)\)\)/);
  assert.match(panelJs, /\$\('service-operations-open'\)\?\.addEventListener\('click',guard\(\(\)=>navigateModule\('service-operations','overview',null\)\)\)/);
  assert.equal(panelJs.includes("['#access-open','workspace.account']"), false);
  assert.equal(panelJs.includes("['#resource-settings-open','ui.resource_configuration']"), false);
  assert.match(panelJs, /function syncRoute\(\)[\s\S]*?'hub','tab','provider','section'/);
  assert.match(panelJs, /window\.open\('\/guide','_blank'\)/);

  // Unified 1200px / 88px / 44px / zero-jump commercial shell CSS rules + 999px return pill capsule (QA-2)
  assert.match(shellCss, /max-width:1200px;min-width:0;margin:0 auto;padding:20px 24px 48px/);
  assert.match(shellCss, /height:88px;min-height:88px;max-height:88px;overflow:hidden;margin:0 0 12px;padding:0 20px/);
  assert.match(shellCss, /height:44px;min-height:44px;max-height:44px;margin:0 0 20px/);
  assert.match(shellCss, /\.gov-return-pill\{[^}]*border-radius:var\(--vsc-radius-pill,999px\)/);
});
