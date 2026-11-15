import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
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
});

test('createGovernanceNav and createSettingsTriageBanner render active states and dispatch callbacks safely', async () => {
  const mod = await loadModule('governance-header.js', {document});
  const switched = [];
  let returnedCtx = null;

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
  await pill.fire('click');
  assert.equal(returnedCtx.projectId, 'proj-9');

  const tabs = nav.children.find(c => c.className === 'gov-module-tabs');
  assert.equal(tabs.children.length, 3);
  const activeTab = tabs.children.find(c => c.dataset.govTarget === 'commerce');
  assert.equal(activeTab.getAttribute('aria-current'), 'page');
  const opsTab = tabs.children.find(c => c.dataset.govTarget === 'service-operations');
  // Modifier click passes through without calling onSwitch
  await opsTab.fire('click', {metaKey: true});
  assert.equal(switched.length, 0);
  await opsTab.fire('click');
  assert.deepEqual(switched, [['service-operations', '?page=service-operations']]);

  // Unsafe returnContext search must omit the return pill
  const unsafeNav = mod.createGovernanceNav({
    active: 'access',
    returnContext: {projectId: 'proj-9', search: '?next=//evil.example'},
    doc: document,
  });
  assert.equal(unsafeNav.children.find(c => c.className === 'gov-return-pill'), undefined);

  const settingsNavigated = [];
  const triage = mod.createSettingsTriageBanner({
    active: 'engine',
    onNavigate: (id, href) => settingsNavigated.push([id, href]),
    doc: document,
  });
  const currentChip = triage.children.find(c => c.dataset?.settingsSurface === 'engine');
  assert.equal(currentChip.tagName, 'SPAN');
  assert.equal(currentChip.getAttribute('aria-current'), 'true');
  const apiChip = triage.children.find(c => c.dataset?.settingsSurface === 'api-settings');
  await apiChip.fire('click');
  assert.deepEqual(settingsNavigated, [['api-settings', '?page=api-settings']]);
});
