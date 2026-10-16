const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createPanel} = require('../../support/fixtures/frontend/panel_dom.cjs');

const root = process.env.VSC_TEST_ROOT;
const chain = ['work', 'episode', 'scene', 'sequence', 'shot'].map((kind, index, kinds) => ({
  id: kind, kind, display_code: kind.toUpperCase(), title: kind,
  parent_id: index ? kinds[index - 1] : null, ordinal: 0,
}));
const nodes = [...chain, {id: 'asset', kind: 'asset', title: 'reference', parent_id: null, ordinal: 1}];
const project = (id, data = nodes) => ({project: {id, name: id, storage_policy: 'legacy-json', read_only: true}, nodes: data, revision: 1});
const control = (app, type, id) => app.document.getElementById('tree').querySelectorAll('.' + type).find(node => node.dataset.id === id);
const visible = app => app.document.getElementById('tree').querySelectorAll('.tree-item').filter(node => node.visible()).map(node => node.dataset.id);

test('branches start collapsed and expand one level at a time', async () => {
  const app = createPanel(root, new Map([['A', project('A')]]));
  await app.panel.selectProject('A');
  assert.deepEqual(visible(app), ['work', 'asset']);
  for (const toggle of app.document.getElementById('tree').querySelectorAll('.tree-toggle')) {
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(app.document.getElementById(toggle.getAttribute('aria-controls')).hidden, true);
  }
  assert.equal(control(app, 'tree-toggle', 'shot'), undefined);
  await control(app, 'tree-toggle', 'work').click();
  assert.deepEqual(visible(app), ['work', 'episode', 'asset']);
  assert.equal(control(app, 'tree-toggle', 'episode').getAttribute('aria-expanded'), 'false');
  await control(app, 'tree-toggle', 'episode').click();
  assert.deepEqual(visible(app), ['work', 'episode', 'scene', 'asset']);
  await control(app, 'tree-toggle', 'work').click();
  assert.deepEqual(visible(app), ['work', 'asset']);
  await control(app, 'tree-toggle', 'work').click();
  assert.deepEqual(visible(app), ['work', 'episode', 'scene', 'asset']);
});

test('selection filters content without expanding; disclosure never changes selection', async () => {
  const app = createPanel(root, new Map([['A', project('A')]]));
  await app.panel.selectProject('A');
  await control(app, 'tree-item', 'work').click();
  assert.equal(app.panel.state.object, 'work');
  assert.equal(control(app, 'tree-toggle', 'work').getAttribute('aria-expanded'), 'false');
  assert.ok(app.requests.some(url => url.includes('/media?') && url.includes('object_id=work')));
  const count = app.requests.length;
  await control(app, 'tree-toggle', 'work').click();
  assert.equal(app.panel.state.object, 'work');
  assert.equal(app.requests.length, count);
  await control(app, 'tree-item', 'episode').click();
  assert.equal(app.panel.state.object, 'episode');
  assert.equal(control(app, 'tree-item', 'episode').getAttribute('aria-current'), 'true');
  assert.equal(control(app, 'tree-item', 'work').getAttribute('aria-current'), null);
  assert.equal(control(app, 'tree-toggle', 'episode').getAttribute('aria-expanded'), 'false');
});

test('keyboard disclosure keeps aria state and target visibility synchronized', async () => {
  const app = createPanel(root, new Map([['A', project('A')]]));
  await app.panel.selectProject('A');
  const toggle = control(app, 'tree-toggle', 'work');
  assert.equal(toggle.tagName, 'BUTTON');
  assert.equal(toggle.type, 'button');
  toggle.focus();
  assert.equal((await toggle.pressKey('ArrowRight')).defaultPrevented, true);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(app.document.activeElement, toggle);
  assert.equal(app.document.getElementById(toggle.getAttribute('aria-controls')).hidden, false);
  await toggle.pressKey('ArrowLeft');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  await toggle.pressKey('Enter');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  await toggle.pressKey(' ');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  await control(app, 'tree-item', 'asset').pressKey('Enter');
  assert.equal(app.panel.state.object, 'asset');
});

test('same-project refresh keeps manual branches and selection; project switch resets them', async () => {
  const projects = new Map([['A', project('A')], ['B', project('B')]]);
  const app = createPanel(root, projects);
  await app.panel.selectProject('A');
  await control(app, 'tree-toggle', 'work').click();
  await control(app, 'tree-toggle', 'episode').click();
  await control(app, 'tree-item', 'scene').click();
  const fresh = [{id: 'new-episode', kind: 'episode', title: 'new episode', parent_id: 'work', ordinal: 1},
    {id: 'new-scene', kind: 'scene', title: 'new scene', parent_id: 'new-episode', ordinal: 0}];
  projects.set('A', project('A', [...nodes, ...fresh]));
  await app.panel.loadProjects();
  assert.equal(control(app, 'tree-toggle', 'work').getAttribute('aria-expanded'), 'true');
  assert.equal(control(app, 'tree-toggle', 'episode').getAttribute('aria-expanded'), 'true');
  assert.equal(control(app, 'tree-toggle', 'new-episode').getAttribute('aria-expanded'), 'false');
  assert.equal(app.panel.state.object, 'scene');
  assert.equal(control(app, 'tree-item', 'scene').getAttribute('aria-current'), 'true');
  projects.set('A', project('A', [nodes[0], ...fresh]));
  await app.panel.loadProjects();
  assert.equal(app.panel.state.object, null);
  assert.equal(app.panel.state.expandedNodes.has('episode'), false);
  assert.equal(app.panel.state.expandedNodes.has('work'), true);
  await app.panel.selectProject('B');
  assert.deepEqual(visible(app), ['work', 'asset']);
  assert.equal(app.panel.state.expandedNodes.size, 0);
  await app.panel.selectProject('A');
  assert.deepEqual(visible(app), ['work']);
});

test('late responses from another project cannot restore its navigation state', async () => {
  let finish;
  const waiting = new Promise(resolve => { finish = resolve; });
  const projects = new Map([['A', project('A')], ['B', project('B')]]);
  const app = createPanel(root, projects, id => id === 'A' ? waiting : projects.get(id));
  const first = app.panel.selectProject('A');
  await app.panel.selectProject('B');
  finish(project('A', [{id: 'wrong', kind: 'work', parent_id: null}]));
  await first;
  assert.equal(app.panel.state.project, 'B');
  assert.deepEqual(visible(app), ['work', 'asset']);
  assert.equal(app.panel.state.revision, projects.get('B').revision);
  assert.equal(app.document.getElementById('heading'), null);
  assert.equal(app.document.getElementById('scope-label'), null);
});


test('trial adoption accompanies one normal selection without extra approval requests', async () => {
  const app=createPanel(root,new Map([['A',project('A')]]));
  await app.panel.selectProject('A');
  app.panel.state.actor='synthetic-human';app.panel.state.csrf='synthetic-csrf';
  const form=app.panel.reviewForm({candidates:[{id:'candidate',role:'video_take',slot_id:'slot'}],
    trial_sources:[{id:'trial-run'}],trial_animatics:[{id:'animatic',name:'approved preview'}]});
  const selects=form.querySelectorAll('select'), action=selects[1], animatic=selects[3];
  assert.equal(animatic.parentElement.hidden,true);
  action.value='binding-decisions';await action.dispatch('change');
  assert.equal(animatic.parentElement.hidden,false);
  animatic.value='animatic';form.querySelectorAll('textarea')[0].value='trial meets the final shot';
  form.querySelectorAll('input')[0].checked=true;
  await form.dispatch('submit');
  assert.equal(app.writes.length,1);
  assert.equal(app.writes[0].url,'/api/v1/projects/A/binding-decisions');
  assert.deepEqual(app.writes[0].body.payload.trial_adoption,{reason:'trial meets the final shot',animatic_version_id:'animatic'});
  assert.equal(app.writes[0].body.confirmed,true);
});
