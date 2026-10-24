const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs'), path = require('node:path');
const {Document, Element} = require('../../support/fixtures/frontend/panel_dom.cjs');

const source = fs.readFileSync(path.join(process.env.VSC_TEST_ROOT || path.resolve(__dirname, '../../..'),
  'src/vsc/interfaces/web/static/script-workspace.js'), 'utf8');
let environmentId = 0;
const environments = globalThis.__scriptWorkspaceTestEnvironments = new Map();
const tick = () => new Promise(resolve => setImmediate(resolve));
const copy = value => JSON.parse(JSON.stringify(value));
const context = () => ({artifact_type: 'vsc.screenplay', dependency_ids: ['approved-plan', 'approved-beats'],
  dependencies: [{id: 'approved-plan', artifact_type: 'vsc.adaptation_plan', artifact_key: 'plan', version: 2, sha256: 'a'.repeat(64)},
    {id: 'approved-beats', artifact_type: 'vsc.episode_beats', artifact_key: 'beats', version: 3, sha256: 'b'.repeat(64)}],
  missing_dependency_types: []});
function draft(revision = 1, scenes = [{id: 'SC1', estimated_duration_ms: 3000,
  actions: [{id: 'A1', text: '他停下', narrative_refs: ['N1']}],
  dialogue: [{id: 'L1', speaker: 'char', text: '明天再来', narrative_refs: ['N1']}],
  silence: [{id: 'S1', text: '长静默', narrative_refs: ['N1'], duration_ms: 800, purpose: 'breath'}]}]) {
  return {exists: true, scope_key: '', draft_revision: revision, content: {format: 'vsc.screenplay/v1',
    project_id: 'A', scope: 'project', body: '正式剧本正文', adaptation_refs: [{id: 'approved-plan', sha256: 'a'.repeat(64)}], scenes},
  phase: 'editing', notes: [], suggestions: [], submitted: null, submission_context: context(),
  updated_at: '2026-10-18T10:00:00+08:00', updated_by: 'alice'};
}

async function fixture(options = {}) {
  const document = new Document(''), container = document.createElement('section'); document.body.append(container);
  // Shared fixture omits tree insertion/sibling access; exercise these browser operations locally.
  for (const [name, getter] of Object.entries({parentNode() { return this.parentElement; },
    previousElementSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) - 1] || null; },
    nextElementSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1] || null; }})) {
    if (!Object.getOwnPropertyDescriptor(Element.prototype, name)) Object.defineProperty(Element.prototype, name, {get: getter});
  }
  if (!Element.prototype.insertBefore) Element.prototype.insertBefore = function (node, before) {
    node.remove(); const index = this.children.indexOf(before); node.parentElement = this;
    this.children.splice(index < 0 ? this.children.length : index, 0, node); return node;
  };
  const requests = [], pending = [], notices = [], revisions = [], timers = new Map();
  const pageListeners = new Map();
  const storage=options.storage || new Map();
  const browserWindow = {
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    addEventListener(type, callback) {
      if (!pageListeners.has(type)) pageListeners.set(type, new Set());
      pageListeners.get(type).add(callback);
    },
    removeEventListener(type, callback) { pageListeners.get(type)?.delete(callback); },
  };
  let project = '/api/v1/projects/A', timerId = 0, uuid = 0;
  const ctx = {api: (url, options) => {
    const request = {url: String(url), options}; requests.push(request);
    return new Promise((resolve, reject) => pending.push({...request, resolve, reject}));
  }, baseUrl: () => project, onNotice: message => notices.push(message),
  session: () => ({actor: 'alice', csrf: 'c', writable: true, revision: 7}), setRevision: value => revisions.push(value)};
  const environment = {document, window: options.browserWindow ? browserWindow : undefined,
    crypto: {randomUUID: () => `id-${++uuid}`}, confirm: () => true, prompt: () => '批注内容',
    setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, {fn, ms}); return id; }, clearTimeout: id => timers.delete(id)};
  const id = ++environmentId; environments.set(id, environment);
  // Import the unmodified source as a real ES module: strict semantics catch accidental globals.
  const prefix = `const {document,window,crypto,confirm,prompt,setTimeout,clearTimeout}=globalThis.__scriptWorkspaceTestEnvironments.get(${id});\n`;
  const module = await import('data:text/javascript;base64,' + Buffer.from(prefix + source).toString('base64'));
  environments.delete(id);
  const ws = module.createScriptWorkspace(container, ctx);
  function respond(data, match = null, failure = false) {
    const index = match == null ? 0 : pending.findIndex(row => typeof match === 'function' ? match(row) : row.url.includes(match));
    assert.ok(index >= 0 && pending[index], `Missing pending request: ${match}; have ${pending.map(row => row.url)}`);
    const request = pending.splice(index, 1)[0];
    failure ? request.reject(new Error(data.message || '保存失败')) : request.resolve(copy(data));
    return request;
  }
  function takeTimer() {
    const entry = timers.entries().next().value;
    assert.ok(entry, 'Expected a scheduled timer'); timers.delete(entry[0]); return entry[1].fn;
  }
  async function boot(value = draft()) {
    const loading = ws.load(); respond({sections: {children: {items: []}}}); await tick(); respond(value); await loading;
  }
  const autosaves = () => requests.filter(row => row.url.includes('/script-draft/autosave'));
  const payload = request => JSON.parse(request.options.body).payload;
  const button = label => container.querySelectorAll('button').find(row => row.textContent === label);
  async function input(selector, value) {
    const node = typeof selector === 'string' ? container.querySelector(selector) : selector;
    assert.ok(node, `Missing input ${selector}`); node.value = value; await node.dispatch('input'); return node;
  }
  async function save(revision = 2) {
    const saving = takeTimer()(); respond({draft_revision: revision}, '/autosave'); await saving; return payload(autosaves().at(-1));
  }
  async function switchProject(id, value = draft()) {
    project = '/api/v1/projects/' + id;
    const loading = ws.load(); respond({sections: {children: {items: []}}}, `/${id}/workbench`); await tick();
    respond(value, row => row.url.includes(`/${id}/script-draft?`) && !row.options); await loading;
  }
  function unload() {
    const event = {defaultPrevented: false, returnValue: undefined, preventDefault() { this.defaultPrevented = true; }};
    for (const callback of pageListeners.get('beforeunload') || []) callback(event);
    return event;
  }
  function note(body='批注内容') {
    container.querySelector('.line-note').click();
    const form=container.querySelector('.script-note-composer'),input=form.querySelector('textarea');
    input.value=body;input.dispatch('input');return form.dispatch('submit');
  }
  return {ws, container, requests, pending, notices, revisions, timers, boot, respond, takeTimer, input, button, save,
    payload, autosaves, switchProject, pageListeners, unload, note, storage, setProject: id => { project = '/api/v1/projects/' + id; }};
}

test('switching immediately invalidates old timers while the next project is still loading', async () => {
  const t = await fixture(); await t.boot();
  await t.input('.line-text', 'A 的未保存内容'); const alreadyQueued = t.takeTimer();
  t.setProject('B'); const loading = t.ws.load();
  await alreadyQueued(); assert.equal(t.autosaves().length, 0);
  assert.equal(t.container.querySelector('.line-text'), null);
  t.respond({sections: {children: {items: []}}}); await tick(); t.respond(draft()); await loading;
  assert.equal(t.autosaves().length, 0);
});

test('late B load cannot overwrite C, including the episode selector', async () => {
  const t = await fixture(); await t.boot();
  t.setProject('B'); const b = t.ws.load();
  t.respond({sections: {children: {items: []}}}); await tick();
  t.setProject('C'); const c = t.ws.load();
  t.respond({sections: {children: {items: []}}}, '/C/workbench'); await tick();
  const cd = draft(); cd.content.body = 'C 正文'; t.respond(cd, '/C/script-draft'); await c;
  const bd = draft(); bd.content.body = 'B 正文'; t.respond(bd, '/B/script-draft'); await b;
  assert.equal(t.container.querySelector('.script-body').value, 'C 正文');
  assert.equal(t.container.querySelector('.script-scope').dataset.projectId, '/api/v1/projects/C');
});

test('an old A save completion cannot unlock the new project B saving queue', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', 'old A');
  const oldSave = t.takeTimer()(); const oldRequest = t.pending.find(row => row.url.includes('/autosave'));
  t.setProject('B'); const b = t.ws.load(); t.respond({sections: {children: {items: []}}}, '/B/workbench'); await tick();
  t.respond(draft(), '/B/script-draft'); await b;
  await t.input('.line-text', 'new B'); const newSave = t.takeTimer()();
  t.respond({draft_revision: 99}, row => row.resolve === oldRequest.resolve); await oldSave;
  await t.input('.line-text', 'last B'); await t.takeTimer()();
  assert.equal(t.autosaves().length, 2, 'old finally must leave the new request in flight');
  t.respond({draft_revision: 9}, '/autosave'); await newSave;
  const queued = t.takeTimer()();
  assert.equal(t.payload(t.autosaves().at(-1)).base_draft_revision, 9);
  assert.equal(t.payload(t.autosaves().at(-1)).content.scenes[0].actions[0].text, 'last B');
  t.respond({draft_revision: 10}, '/autosave'); await queued;
});

test('serial saves keep edits made in flight; a failed save preserves the editor and blocks submit', async () => {
  const t = await fixture(); await t.boot();
  await t.input('.line-text', '第一句'); const first = t.takeTimer()();
  await t.input('.line-text', '最后一句'); t.respond({draft_revision: 2}, '/autosave'); await first;
  await t.save(3);
  assert.equal(t.payload(t.autosaves()[1]).base_draft_revision, 2);
  assert.equal(t.payload(t.autosaves()[1]).content.scenes[0].actions[0].text, '最后一句');
  await t.input('.line-text', '失败也保留'); const failed = t.takeTimer()();
  t.respond({message: 'HTTP 500'}, '/autosave', true); await failed;
  await t.button('提交人工确认').click();
  assert.equal(t.container.querySelector('.line-text').value, '失败也保留');
  assert.equal(t.requests.filter(row => row.url.endsWith('/script-submit')).length, 0);
  assert.ok(t.notices.some(message => message.includes('保存')));
});

test('two scenes round trip independently and preserve every untouched field', async () => {
  const t = await fixture(), original = draft();
  original.content.scenes.push({id: 'SC2', estimated_duration_ms: 1000, extra: 'keep scene metadata',
    actions: [{id: 'A2', text: '第二场', narrative_refs: ['N2'], extra: true}], dialogue: [], silence: []});
  await t.boot(original); await t.input('.line-text', '只改第一场'); const saved = (await t.save()).content;
  const expected = copy(original.content); expected.scenes[0].actions[0].text = '只改第一场';
  assert.deepEqual(saved, expected);
  assert.equal(t.container.querySelector('.scene-id').readOnly, true);
});

for (const operation of ['添加批注', '解决', '忽略', '拒绝']) {
  test(`${operation} refreshes metadata without replacing dirty editor content or its revision`, async () => {
    const t = await fixture(), initial = draft();
    initial.notes = [{id: 'note-1', scene_id: 'SC1', line_id: 'A1', body: '批注', scope_key: '', status: 'open'}];
    initial.suggestions = [{id: 'suggestion-1', scene_id: 'SC1', line_id: 'A1', status: 'pending', kind: 'action', field: 'text'}];
    await t.boot(initial); const line = await t.input('.line-text', '未保存一');
    const action = operation === '添加批注' ? t.note() : t.button(operation).click();
    if (operation === '添加批注') {
      assert.equal(t.requests.some(row => row.url.endsWith('/script-notes')), false);
      assert.equal(t.payload(t.autosaves().at(-1)).content.scenes[0].actions[0].text, '未保存一');
      t.respond({draft_revision: 2}, '/autosave'); await tick();
      const request = t.requests.find(row => row.url.endsWith('/script-notes'));
      assert.equal(t.payload(request).base_draft_revision, 2);
    }
    t.respond({revision: 8}); await tick();
    await t.input(line, '请求期间继续写');
    const fresh = copy(initial); fresh.draft_revision = 97; fresh.content.scenes[0].actions[0].text = '服务器旧正文';
    fresh.notes[0].status = 'resolved'; t.respond(fresh, '/script-draft?'); await action;
    assert.equal(t.container.querySelector('.line-text'), line, 'preserve focused editor nodes');
    assert.equal(line.value, '请求期间继续写');
    assert.ok(t.container.querySelector('.script-notes').textContent.includes('已解决'));
    const saved = await t.save(3); assert.equal(saved.base_draft_revision, operation === '添加批注' ? 2 : 1);
    assert.equal(saved.content.scenes[0].actions[0].text, '请求期间继续写');
  });
}

test('late note metadata from an old project neither changes the new editor nor its notes', async () => {
  const t = await fixture(); await t.boot(); const note = t.note();
  await tick(); t.respond({revision: 8}); await tick(); t.setProject('B'); const b = t.ws.load();
  t.respond({sections: {children: {items: []}}}, '/B/workbench'); await tick(); t.respond(draft(5), '/B/script-draft'); await b;
  const stale = draft(99); stale.notes = [{id: 'old', body: 'A 批注', status: 'open'}];
  t.respond(stale, '/A/script-draft'); await note;
  assert.equal(t.container.querySelector('.script-notes').textContent.includes('A 批注'), false);
});

test('strict ES module conflict recovery reloads latest and permits another save', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', 'local'); const failed = t.takeTimer()();
  t.respond({message: '工作副本已被他人更新'}, '/autosave', true); await failed;
  const reload = t.button('加载最新并替换本地').click();
  await tick();
  t.respond(draft(7), '/script-draft?'); await reload;
  await t.input('.line-text', '合并后'); const saved = await t.save(8);
  assert.equal(saved.base_draft_revision, 7); assert.equal(saved.content.scenes[0].actions[0].text, '合并后');
});

test('blank workspace exposes every screenplay field and submits the fixed approved upstream IDs', async () => {
  const t = await fixture(); await t.boot({...draft(0), exists: false, content: null, phase: 'empty'});
  const start = t.button('从空白剧本开始').click(); t.respond({draft_revision: 1}, '/autosave'); await start;
  await t.input('.script-body', '空白新稿写成的正式正文');
  await t.button('添加改编来源').click(); await t.input('.adaptation-id', 'approved-plan'); await t.input('.adaptation-sha', 'a'.repeat(64));
  await t.button('添加场次').click(); await t.input('.scene-duration', 3000);
  await t.button('添加行动').click(); await t.input('.line-text', '角色停下'); await t.input('.line-refs', 'N1, N2');
  await t.button('添加对白').click(); await t.input('.line-speaker', '角色');
  const dialogue = t.container.querySelector('.scene-dialogue'); await t.input(dialogue.querySelector('.line-text'), '等等');
  await t.input(dialogue.querySelector('.line-refs'), 'N2');
  await t.button('添加静默').click(); const silence = t.container.querySelector('.scene-silence');
  await t.input(silence.querySelector('.line-text'), '停顿'); await t.input(silence.querySelector('.line-refs'), 'N3');
  await t.input('.line-duration', 800); await t.input('.line-purpose', '等待回应');
  const content = (await t.save(2)).content;
  assert.equal(content.body, '空白新稿写成的正式正文');
  assert.deepEqual(content.adaptation_refs, [{id: 'approved-plan', sha256: 'a'.repeat(64)}]);
  assert.deepEqual(content.scenes[0].actions[0].narrative_refs, ['N1', 'N2']);
  assert.deepEqual(content.scenes[0].dialogue[0].narrative_refs, ['N2']);
  assert.equal(content.scenes[0].silence[0].duration_ms, 800); assert.equal(content.scenes[0].silence[0].purpose, '等待回应');
  const submit = t.button('提交人工确认').click(); await tick();
  const request = t.requests.find(row => row.url.endsWith('/script-submit'));
  assert.deepEqual(t.payload(request).dependency_ids, ['approved-plan', 'approved-beats']);
  assert.equal(t.payload(request).artifact_type, 'vsc.screenplay');
  assert.equal(Object.hasOwn(t.payload(request), 'stage'), false);
  t.respond({revision: 9, artifact: {version: 1}}, '/script-submit'); await tick();
  t.respond({...draft(2), content}, '/script-draft?'); await submit;
});

test('missing approved prerequisites explicitly block submission', async () => {
  const t = await fixture(), initial = draft(); initial.submission_context.missing_dependency_types = ['vsc.episode_beats'];
  await t.boot(initial); await t.button('提交人工确认').click();
  assert.equal(t.requests.some(row => row.url.endsWith('/script-submit')), false);
  assert.ok(t.notices.some(message => message.includes('vsc.episode_beats')));
});

test('new and deleted scene IDs never reuse a previous note anchor', async () => {
  const t = await fixture(); await t.boot(); await t.button('添加场次').click();
  const cards = t.container.querySelectorAll('.script-scene'), newId = cards[1].dataset.sceneId;
  await cards[1].querySelectorAll('button').find(button => button.textContent === '删除场次').click();
  await t.button('添加场次').click();
  const saved = (await t.save()).content; assert.notEqual(saved.scenes[1].id, newId);
  assert.equal(saved.scenes[0].id, 'SC1');
});

test('explicit episode ancestor wins and the script reader does not download the episode catalogue', async () => {
  const t = await fixture(); const loading = t.ws.load({objectId:'shot62'});
  assert.ok(t.pending[0].url.includes('object_id=shot62'));
  t.respond({ancestors:[{id:'W',kind:'work'},{id:'EP62',kind:'episode',title:'第62集'},{id:'SC62',kind:'scene'}],scope:{id:'shot62',kind:'shot'}});await tick();
  assert.equal(t.pending.length,1);assert.ok(t.pending[0].url.includes('scope_key=EP62'));
  t.respond(draft());await loading;
  const select=t.container.querySelector('.script-scope');assert.equal(select.children.length,2);assert.equal(select.value,'EP62');
  t.setProject('B'); const b = t.ws.load(); t.respond({sections: {children: {items: []}}}, '/B/workbench'); await tick();
  assert.equal(new URL(t.pending[0].url,'http://local').searchParams.get('scope_key'),''); t.respond(draft(), '/B/script-draft'); await b;
  assert.equal(t.container.querySelector('.script-scope').value, '');
});

for (const mode of ['slow', 'failed', 'mismatch', 'valid']) {
  test(`frozen review ${mode}: approval requires the exact loaded artifact and displays its full body`, async () => {
    const t = await fixture(), initial = draft(); initial.phase = 'editing';
    initial.submitted = {id: 'frozen-A', artifact_key: 'screenplay:project', version: 1, sha256: 'c'.repeat(64), state: 'pending', matches_draft: false};
    await t.boot(initial);
    const approve = t.container.querySelector('.script-approve-button'); await t.input('.script-decision-reason', '已完整阅读');
    if (mode === 'failed') t.respond({message: '离线'}, '/artifacts/', true);
    if (mode === 'mismatch' || mode === 'valid') t.respond({id: 'frozen-A', sha256: (mode === 'valid' ? 'c' : 'd').repeat(64),
      content: initial.content, project_wide: false, object_ids: ['real-episode'], dependency_ids: ['approved-plan']}, '/artifacts/');
    await tick();
    const deciding = approve.click(); await tick();
    const decisions = t.requests.filter(row => row.url.endsWith('/artifact-decisions'));
    assert.equal(decisions.length, mode === 'valid' ? 1 : 0);
    assert.equal(approve.disabled, mode !== 'valid');
    if (mode === 'valid') {
      const text = t.container.querySelector('.frozen-body').textContent;
      assert.ok(text.includes('正式剧本正文')); assert.ok(text.includes('real-episode')); assert.ok(text.includes('breath'));
      assert.ok(text.includes('N1')); assert.ok(text.includes('approved-plan'));
      t.respond({revision: 9}, '/artifact-decisions'); await tick();
      t.respond(draft(), '/script-draft?'); await deciding;
    } else await deciding;
  });
}

test('approved frozen A is presented independently while draft B remains editing', async () => {
  const t = await fixture(), initial = draft(4); initial.content.body = 'B 正在编辑';
  initial.submitted = {id: 'frozen-A', artifact_key: 'screenplay:project', version: 1, sha256: 'c'.repeat(64), state: 'approved', matches_draft: false};
  await t.boot(initial); t.respond({id: 'frozen-A', sha256: 'c'.repeat(64), content: {...initial.content, body: '已批准 A'}, project_wide: true}, '/artifacts/'); await tick();
  assert.equal(t.container.querySelector('.script-phase').textContent, '编辑中');
  assert.equal(t.container.querySelector('.script-body').value, 'B 正在编辑');
  assert.ok(t.container.querySelector('.frozen-body').textContent.includes('已批准 A'));
  assert.equal(t.container.querySelector('.script-approve-button'), null);
});

test('typing while submit freezes A preserves B and its autosave instead of reloading A', async () => {
  const t = await fixture(); await t.boot();
  const submitting = t.button('提交人工确认').click(); await tick();
  const line = await t.input('.line-text', '提交期间写的 B');
  t.respond({revision: 9, artifact: {version: 1}}, '/script-submit'); await tick();
  const frozen = draft(); frozen.phase = 'pending'; frozen.submitted = {id: 'frozen-A', version: 1, state: 'pending', sha256: 'c'.repeat(64)};
  t.respond(frozen, '/script-draft?'); await submitting;
  assert.equal(t.container.querySelector('.line-text'), line);
  assert.equal(line.value, '提交期间写的 B'); assert.equal(t.container.querySelector('.script-phase').textContent, '编辑中');
  assert.equal((await t.save()).content.scenes[0].actions[0].text, '提交期间写的 B');
});

test('notes wait for an in-flight save and their later metadata cannot rewind the saved revision', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '保存一');
  const saving = t.takeTimer()(); const noting = t.note();
  assert.equal(t.requests.some(row => row.url.endsWith('/script-notes')), false);
  t.respond({draft_revision: 2}, '/autosave'); await saving;
  await t.takeTimer()(); await tick();
  const request = t.requests.find(row => row.url.endsWith('/script-notes'));
  assert.equal(t.payload(request).base_draft_revision, 2);
  t.respond({revision: 8}, '/script-notes'); await tick();
  await t.input('.line-text', '保存二'); t.respond(draft(), '/script-draft?'); await noting;
  const second = await t.save(3); assert.equal(second.base_draft_revision, 2);
  assert.equal(second.content.scenes[0].actions[0].text, '保存二');
});

test('accepting a suggestion cannot replace edits typed while its request is pending', async () => {
  const t = await fixture(), initial = draft();
  initial.suggestions = [{id: 'suggestion-1', scene_id: 'SC1', line_id: 'A1', status: 'pending', kind: 'action', field: 'text'}];
  await t.boot(initial); const accepting = t.button('接受这一处').click();
  await t.input('.line-text', '决定期间本地继续写');
  t.respond({revision: 8}, '/script-suggestion-decisions'); await tick();
  const accepted = draft(2); accepted.content.scenes[0].actions[0].text = '服务器接受建议后的文字';
  t.respond(accepted, '/script-draft?'); await accepting;
  assert.equal(t.container.querySelector('.line-text').value, '决定期间本地继续写');
  assert.equal(t.timers.size, 0); assert.equal(t.container.querySelector('.script-conflict').hidden, false);
  await t.button('提交人工确认').click();
  assert.equal(t.requests.some(row => row.url.endsWith('/script-submit')), false);
});

test('failed autosave prevents a new note from binding the old server draft and retains local text', async () => {
  const t = await fixture(); await t.boot(); const line = await t.input('.line-text', '只在本地的新正文');
  const noting = t.note();
  assert.equal(t.payload(t.autosaves().at(-1)).content.scenes[0].actions[0].text, '只在本地的新正文');
  t.respond({message: 'HTTP 500'}, '/autosave', true); await noting;
  assert.equal(t.requests.some(row => row.url.endsWith('/script-notes')), false);
  assert.equal(t.container.querySelector('.line-text'), line); assert.equal(line.value, '只在本地的新正文');
  assert.ok(t.container.querySelector('.script-note-composer').textContent.includes('意见仍保留'));
  assert.equal(t.container.querySelector('.script-note-body').value,'批注内容');
  assert.equal(t.requests.some(row=>row.url.endsWith('/review-process')),false);
});

test('late explicit object ancestry cannot reopen an old episode or issue its draft read',async()=>{
  const t=await fixture();const old=t.ws.load({objectId:'old-shot'}),newer=t.ws.load({objectId:'new-shot'});
  t.respond({ancestors:[{id:'EP-new',kind:'episode',title:'新集'}],scope:{id:'new-shot',kind:'shot'}},'object_id=new-shot');await tick();
  t.respond(draft(), 'scope_key=EP-new');await newer;
  t.respond({ancestors:[{id:'EP-old',kind:'episode',title:'旧集'}],scope:{id:'old-shot',kind:'shot'}},'object_id=old-shot');await old;
  assert.equal(t.container.querySelector('.script-scope').value,'EP-new');assert.equal(t.requests.some(row=>row.url.includes('scope_key=EP-old')),false);
});

test('failed draft and opinion survive a page instance reload; explicit discard also clears browser recovery',async()=>{
  const t=await fixture({browserWindow:true});await t.boot();await t.input('.line-text','刷新前未保存正文');
  const noting=t.note('刷新前尚未提交的原意见');t.respond({message:'offline'},'/autosave',true);await noting;
  const next=await fixture({browserWindow:true,storage:t.storage});await next.boot();
  assert.equal(next.container.querySelector('.line-text').value,'刷新前未保存正文');
  assert.equal(next.container.querySelector('.script-note-body').value,'刷新前尚未提交的原意见');
  const discard=next.ws.load({discardLocal:true});await tick();next.respond(draft(),'/script-draft?');await discard;
  assert.equal(next.container.querySelector('.line-text').value,'他停下');
  assert.equal(Array.from(next.storage.keys()).some(key=>key.startsWith('vsc-script:')),false);
});

test('notes pagination reads the next bounded page without replacing dirty draft content',async()=>{
  const t=await fixture(),initial=draft();initial.notes_page={offset:0,next_offset:50};initial.suggestions_page={offset:0,next_offset:null};await t.boot(initial);
  const line=await t.input('.line-text','分页时未保存的正文');
  const next=t.container.querySelector('.script-notes').querySelector('.script-pagination').querySelectorAll('button').find(row=>row.textContent==='下一页');const loading=next.click();
  const request=t.pending.find(row=>row.url.includes('note_offset=50'));assert.ok(request);assert.ok(request.url.includes('limit=50'));
  const fresh=draft(99);fresh.notes_page={offset:50,next_offset:null};fresh.notes=[{id:'later',scope_key:'',body:'第二页意见',status:'resolved'}];t.respond(fresh,'note_offset=50');await loading;
  assert.equal(t.container.querySelector('.line-text'),line);assert.equal(line.value,'分页时未保存的正文');assert.ok(t.container.querySelector('.script-notes').textContent.includes('第二页意见'));
});

test('switching project while saving a note baseline cannot post that note to either project', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', 'A 所见正文');
  const noting = t.note();
  t.setProject('B'); const loading = t.ws.load();
  t.respond({sections: {children: {items: []}}}, '/B/workbench'); await tick();
  t.respond(draft(5), '/B/script-draft'); await loading;
  t.respond({draft_revision: 2}, '/A/script-draft/autosave'); await noting;
  assert.equal(t.requests.some(row => row.url.endsWith('/script-notes')), false);
});

test('note history displays recorded revision, exact content SHA and frozen artifact without inventing old baselines', async () => {
  const t = await fixture(), initial = draft(19), sha = 'e'.repeat(64);
  initial.notes = [
    {id: 'bound', scope_key: '', scene_id: 'SC1', line_id: 'A1', body: '有基准', status: 'resolved',
      base_draft_revision: 7, base_content_sha256: sha, base_artifact_id: 'frozen-r7'},
    {id: 'legacy', scope_key: null, scene_id: 'SC1', line_id: 'A1', body: '旧批注', status: 'resolved',
      base_draft_revision: null, base_content_sha256: null, base_artifact_id: null},
  ];
  await t.boot(initial); const baselines = t.container.querySelectorAll('.note-baseline');
  assert.ok(baselines[0].textContent.includes('r7')); assert.ok(baselines[0].textContent.includes(sha));
  assert.ok(baselines[0].textContent.includes('frozen-r7'));
  assert.equal(baselines[1].textContent, '基准未知（历史批注未记录所见版本）');
  assert.equal(baselines[1].textContent.includes('r19'), false);
});

test('unsaved A text survives A→B→A before its timer fires and resumes against the unchanged draft', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '尚未触发保存的 A');
  await t.switchProject('B'); await t.switchProject('A');
  assert.equal(t.container.querySelector('.line-text').value, '尚未触发保存的 A');
  assert.equal(t.autosaves().length, 0);
  const saved = await t.save(); assert.equal(saved.base_draft_revision, 1);
  assert.equal(saved.content.scenes[0].actions[0].text, '尚未触发保存的 A');
  await t.switchProject('B'); await t.switchProject('A', draft(2));
  assert.equal(t.container.querySelector('.line-text').value, '他停下', 'a successful clean save clears the memory recovery');
  assert.equal(t.timers.size, 0);
});

test('unsaved per-episode drafts survive a scope switch without sharing their bodies', async () => {
  const t = await fixture(); await t.boot(); const select = t.container.querySelector('.script-scope');
  async function scope(id, value = draft()) {
    select.value = id; const loading = select.dispatch('change'); await tick();
    t.respond(value, 'scope_key=' + id); await loading;
  }
  await scope('EP1'); await t.input('.line-text', 'EP1 未保存内容');
  await scope('EP2'); await t.input('.line-text', 'EP2 未保存内容');
  await scope('EP1'); assert.equal(t.container.querySelector('.line-text').value, 'EP1 未保存内容');
  assert.equal((await t.save()).scope_key, 'EP1');
  await scope('EP2'); assert.equal(t.container.querySelector('.line-text').value, 'EP2 未保存内容');
});

test('a failed save remains recoverable after leaving and can retry the unchanged server base', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '失败后的正文'); const saving = t.takeTimer()();
  t.respond({message: 'HTTP 500'}, '/autosave', true); await saving;
  await t.switchProject('B'); await t.switchProject('A');
  assert.equal(t.container.querySelector('.line-text').value, '失败后的正文');
  const retried = await t.save(2); assert.equal(retried.base_draft_revision, 1);
  assert.equal(retried.content.scenes[0].actions[0].text, '失败后的正文');
});

test('returning while the old POST is uncertain keeps later local input and blocks any automatic overwrite', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '发出的第一稿'); const saving = t.takeTimer()();
  await t.input('.line-text', '请求后继续输入的正文');
  await t.switchProject('B'); await t.switchProject('A');
  assert.equal(t.container.querySelector('.line-text').value, '请求后继续输入的正文');
  assert.equal(t.container.querySelector('.script-conflict').hidden, false); assert.equal(t.timers.size, 0);
  await t.input('.line-text', '返回后继续保留的正文');
  t.respond({draft_revision: 2}, '/autosave'); await saving;
  assert.equal(t.container.querySelector('.line-text').value, '返回后继续保留的正文');
  assert.equal(t.autosaves().length, 1); assert.equal(t.timers.size, 0);
  await t.button('提交人工确认').click(); assert.equal(t.requests.some(row => row.url.endsWith('/script-submit')), false);
});

test('a confirmed old POST completion before return advances the base without losing post-send local input', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '发出的版本'); const saving = t.takeTimer()();
  await t.input('.line-text', '发出后继续写'); await t.switchProject('B');
  t.respond({draft_revision: 2}, '/autosave'); await saving;
  const server = draft(2); server.content.scenes[0].actions[0].text = '发出的版本';
  await t.switchProject('A', server);
  assert.equal(t.container.querySelector('.line-text').value, '发出后继续写');
  const saved = await t.save(3); assert.equal(saved.base_draft_revision, 2);
  assert.equal(saved.content.scenes[0].actions[0].text, '发出后继续写');
});

test('a changed server revision restores local text as a conflict with zero overwrite POSTs', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '本地待核对稿'); await t.switchProject('B');
  const remote = draft(7); remote.content.scenes[0].actions[0].text = '另一个人的 r7';
  await t.switchProject('A', remote);
  assert.equal(t.container.querySelector('.line-text').value, '本地待核对稿');
  assert.equal(t.container.querySelector('.script-conflict').hidden, false); assert.equal(t.timers.size, 0);
  await t.input('.line-text', '核对时仍可保留输入'); assert.equal(t.timers.size, 0);
  await t.button('提交人工确认').click(); assert.equal(t.autosaves().length, 0);
  await t.switchProject('B'); await t.switchProject('A', remote);
  assert.equal(t.container.querySelector('.line-text').value, '核对时仍可保留输入');
  assert.equal(t.timers.size, 0);
});

test('explicit replace discards recovery without immediately caching it again', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '待明确放弃的本地稿'); await t.switchProject('B');
  const remote = draft(7); remote.content.scenes[0].actions[0].text = '明确选择的服务器稿';
  await t.switchProject('A', remote);
  const replace = t.button('加载最新并替换本地').click(); await tick(); t.respond(remote, '/A/script-draft?'); await replace;
  assert.equal(t.container.querySelector('.line-text').value, '明确选择的服务器稿');
  await t.switchProject('B'); await t.switchProject('A', remote);
  assert.equal(t.container.querySelector('.line-text').value, '明确选择的服务器稿');
  assert.equal(t.container.querySelector('.script-conflict').hidden, true); assert.equal(t.timers.size, 0);
});

test('a hidden workspace retains edits when baseUrl changes before its old timer can run', async () => {
  const t = await fixture(); await t.boot(); await t.input('.line-text', '隐藏页上的 A 草稿');
  const oldTimer = t.takeTimer(); t.setProject('B'); await oldTimer();
  assert.equal(t.autosaves().length, 0);
  const loading = t.ws.load(); t.respond({sections: {children: {items: []}}}, '/B/workbench'); await tick();
  t.respond(draft(), '/B/script-draft?'); await loading;
  await t.switchProject('A'); assert.equal(t.container.querySelector('.line-text').value, '隐藏页上的 A 草稿');
});

test('native page-leave warning covers both active and cached drafts and clears after a clean save', async () => {
  const t = await fixture({browserWindow: true}); await t.boot(); assert.equal(t.unload().defaultPrevented, false);
  await t.input('.line-text', '关闭页面前尚未保存');
  const active = t.unload(); assert.equal(active.defaultPrevented, true); assert.equal(active.returnValue, '');
  await t.switchProject('B'); assert.equal(t.unload().defaultPrevented, true, 'offscreen recovery still needs a leave warning');
  await t.switchProject('A'); await t.save(2); assert.equal(t.unload().defaultPrevented, false);
  await t.input('.line-text', '销毁前未保存'); assert.equal(t.timers.size, 1);
  t.ws.destroy(); assert.equal(t.pageListeners.get('beforeunload').size, 0);
  assert.equal(t.timers.size, 0); assert.equal(t.unload().defaultPrevented, false);
});

test('a confirmed offscreen save with no later edits clears its recovery and page-leave warning', async () => {
  const t = await fixture({browserWindow: true}); await t.boot(); await t.input('.line-text', '已发出而无后续输入');
  const saving = t.takeTimer()(); await t.switchProject('B'); assert.equal(t.unload().defaultPrevented, true);
  t.respond({draft_revision: 2}, '/A/script-draft/autosave'); await saving;
  assert.equal(t.unload().defaultPrevented, false);
  await t.switchProject('A', draft(2)); assert.equal(t.timers.size, 0);
  assert.equal(t.container.querySelector('.script-conflict').hidden, true);
});

test('editor chooses approved sources, real scene identity and labeled narrative refs without manual IDs', async () => {
  const t = await fixture();
  const value = {...draft(0), exists:false, content:null, phase:'empty',
    template_content:{format:'vsc.screenplay/v1',body:'',adaptation_refs:[{id:'approved-plan',sha256:'a'.repeat(64)}],scenes:[]},
    scene_choices:[{id:'fixed-scene',label:'批准改编对应的场次'}],
    narrative_choices:{'fixed-scene':[{id:'unit-1',label:'可见行动：停下脚步'}]}};
  await t.boot(value);const start=t.button('从空白剧本开始').click();t.respond({draft_revision:1},'/autosave');await start;
  await t.input('.script-body','正式新稿');await t.button('添加场次').click();await t.input('.scene-duration',3000);
  await t.button('添加行动').click();await t.input('.line-text','停下脚步');
  const check=t.container.querySelector('.line-narrative-choices').querySelector('input');check.checked=true;await check.dispatch('change');
  const content=(await t.save(2)).content;
  assert.equal(content.scenes[0].id,'fixed-scene');assert.deepEqual(content.scenes[0].actions[0].narrative_refs,['unit-1']);
  assert.deepEqual(content.adaptation_refs,[{id:'approved-plan',sha256:'a'.repeat(64)}]);
});

test('AI generation binds the saved digest, retries the same command and requires an explicit new round', async () => {
  const t=await fixture();await t.boot();const sha='f'.repeat(64);
  async function generate(){
    await t.input('.script-ai-goal','让行动更可拍');const working=t.button('生成 AI 建议').click();await tick();
    t.respond({...draft(),content_sha256:sha},'/script-draft?');await tick();
    const request=t.requests.findLast(row=>row.url.endsWith('/generate-suggestions'));
    assert.equal(t.payload(request).base_content_sha256,sha);assert.equal(t.payload(request).base_draft_revision,1);
    t.respond({status:'submission_unknown',revision:8},'/generate-suggestions');await tick();t.respond(draft(),'/script-draft?');await working;
    return JSON.parse(request.options.body);
  }
  const first=await generate(),recovered=await generate();
  assert.equal(first.idempotency_key,recovered.idempotency_key);assert.equal(first.payload.new_attempt,false);
  await t.button('明确新增一轮建议').click();const next=await generate();
  assert.notEqual(next.idempotency_key,first.idempotency_key);assert.equal(next.payload.new_attempt,true);
});
