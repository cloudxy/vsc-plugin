import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {Document, Element} = require('../../support/fixtures/frontend/panel_dom.cjs');
const originalMatches = Element.prototype.matches;
Element.prototype.matches = function (selector) {
  const attribute = selector.match(/^\[([^=\]]+)="([^"]*)"\]$/);
  if (attribute) return this.getAttribute(attribute[1]) === attribute[2];
  return originalMatches.call(this, selector);
};
Element.prototype.dispatchEvent = function (event) {
  return this.dispatch(event?.type || 'change');
};
if (!globalThis.Event) globalThis.Event = class Event { constructor(type) { this.type = type; } };

const document = new Document('');
globalThis.document = document;
document.documentElement = document.createElement('html');
const memory = new Map();
globalThis.sessionStorage = {getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key)};
globalThis.localStorage = {getItem: () => null, setItem() {}, removeItem() {}};
globalThis.location = {search: '', href: 'http://test/', origin: 'http://test'};

const {createCreativeTools} = await import('../../../src/vsc/interfaces/web/static/creative-tools.js');
const {setLocale} = await import('../../../src/vsc/interfaces/web/static/i18n.js');

const tools = [
  {id: 'mv', label: 'MV 镜头计划', mode: 'draft_only'},
  {id: 'extract_frame', label: '首尾/当前帧提取', mode: 'local'},
  {id: 'breakdown', label: '分镜/视频/音频拉片', mode: 'local'},
];

function payload() {
  return {
    standalone: false,
    revision: 3,
    episode: {id: 'episode-1', title: '第 1 集'},
    episodes: [{id: 'episode-1', title: '第 1 集'}],
    tools,
    drafts: [],
    media: [],
    media_total: 0,
    music_results: [],
    local_outputs: [],
    work_runs: [],
    shots: [],
    canvases: [],
    models: [],
  };
}

test('switching a tool keeps the tab-row and page scroll positions', async () => {
  setLocale('zh-cn', {persist: false});
  const workspace = document.createElement('div');
  workspace.className = 'workspace';
  const root = document.createElement('main');
  document.body.append(workspace);
  workspace.append(root);
  const toolsPanel = createCreativeTools(root, {
    api: async url => url.includes('/media-imports') ? {items: [], revision: 3} : payload(),
    session: () => ({actor: 'owner', identityId: 'identity-1', csrf: 'csrf', revision: 3, writable: true}),
    projects: () => [],
    notice() {},
    setRevision() {},
    onToolChange() {},
    navigate() {},
  });
  await toolsPanel.load({project: 'project-1', object: 'episode-1', tool: 'extract_frame'});
  const before = root.querySelector('.creative-tool-tabs');
  before.scrollLeft = 640;
  workspace.scrollTop = 180;
  const last = [...before.querySelectorAll('button')].at(-1);
  assert.equal(last.textContent, '分镜/视频/音频拉片');
  await last.click();
  const after = root.querySelector('.creative-tool-tabs');
  assert.notEqual(after, before);
  assert.equal(after.scrollLeft, 640);
  assert.equal(workspace.scrollTop, 180);
  const pressed = [...after.querySelectorAll('button')].find(node => node.getAttribute('aria-pressed') === 'true');
  assert.equal(pressed.textContent, '分镜/视频/音频拉片');
  toolsPanel.suspend();
});
