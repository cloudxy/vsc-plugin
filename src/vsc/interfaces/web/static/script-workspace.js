/* 剧本工作区：可变工作副本 + 串行自动保存 + 批注 + 差异 + 提交人工确认。
   本模块只消费后端事实（draft / artifact 决定），不拥有批准权威。
   F01/F02：保存会话绑定 project+scope，串行保存队列，过期响应与切换后定时器不写当前会话；
   F03：readEditor 按稳定身份合并编辑字段，保留未编辑的引用与静默语义；
   F04：待确认审阅展示被冻结 artifact 的正文摘要与 SHA；F07：分集导航按项目重建。 */

export function createScriptWorkspace(container, ctx) {
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; };
  const notice = message => ctx.onNotice(message);
  const blank = () => ({format: 'vsc.screenplay/v1', body: '', adaptation_refs: [], scenes: []});
  let draft = null, scopeKey = '', scopeSelect = null, statusChip = null;
  let session = null;            // {project, scopeKey}：当前编辑会话，请求与响应都按它判定归属
  let saveTimer = null, saving = false, dirty = false, lastError = null;

  const sameSession = target => session && target && target.project === session.project
    && target.scopeKey === session.scopeKey;

  function headers() { return {'Content-Type': 'application/json', 'X-CSRF-Token': ctx.session().csrf}; }
  function requireSession() {
    const value = ctx.session();
    if (!value.actor) throw new Error('请先在顶栏建立操作会话；未登录时剧本页只读。');
    return value;
  }
  async function write(action, payload, confirmed = false) {
    const value = requireSession();
    const result = await ctx.api(`${ctx.baseUrl()}/${action}`, {method: 'POST', headers: headers(),
      body: JSON.stringify({payload, confirmed, expected_revision: value.revision, idempotency_key: crypto.randomUUID()})});
    ctx.setRevision(result.revision ?? value.revision);
    return result;
  }

  async function loadEpisodes() {
    const episodes = [];
    try {
      const works = await ctx.api(`${ctx.baseUrl()}/workbench?section=children&limit=100`);
      for (const work of (works.sections?.children?.items || []).filter(node => node.kind === 'work')) {
        const children = await ctx.api(`${ctx.baseUrl()}/workbench?section=children&limit=100&object_id=${encodeURIComponent(work.id)}`);
        for (const node of (children.sections?.children?.items || []).filter(row => row.kind === 'episode')) {
          episodes.push({id: node.id, label: `${work.title || work.display_code || ''} · ${node.title || node.display_code || node.id}`});
        }
      }
    } catch { /* 旧项目或无分集：仅全项目剧本 */ }
    return episodes;
  }

  async function ensureScopeSelect(projectId) {
    if (scopeSelect && scopeSelect.dataset.projectId === projectId) return;
    scopeSelect = el('select', 'script-scope');
    scopeSelect.dataset.projectId = projectId;
    scopeSelect.setAttribute('aria-label', '剧本范围');
    const all = el('option', '', '全项目剧本'); all.value = ''; scopeSelect.append(all);
    for (const episode of await loadEpisodes()) {
      const option = el('option', '', `分集剧本：${episode.label}`);
      option.value = episode.id; scopeSelect.append(option);
    }
    scopeSelect.value = scopeKey;
    scopeSelect.addEventListener('change', async () => { scopeKey = scopeSelect.value; await load(); });
  }

  async function load() {
    const projectId = ctx.session ? null : null; // project 由 baseUrl 隐含；会话标识用 scope+baseUrl
    try {
      const target = {project: ctx.baseUrl(), scopeKey};
      await ensureScopeSelect(ctx.baseUrl());
      draft = await ctx.api(`${ctx.baseUrl()}/script-draft?scope_key=${encodeURIComponent(scopeKey)}`);
      session = target;                     // F01：切换后旧定时器/响应因会话不符被丢弃
      clearTimeout(saveTimer); saveTimer = null; saving = false; dirty = false; lastError = null;
      render();
    } catch (error) { notice(error.message); }
  }

  function setStatus(text) { if (statusChip) statusChip.textContent = text; }
  function scheduleSave() {
    if (!sameSession({project: ctx.baseUrl(), scopeKey})) return;
    dirty = true; lastError = null;
    setStatus('待保存');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 900);
  }
  async function flushSave() {
    if (!session || saving || !dirty) return;      // F02：串行队列——保存中不丢新输入，返回后继续
    const target = {...session};
    const content = readEditor();
    saving = true; setStatus('保存中…');
    try {
      requireSession();
      const result = await ctx.api(`${ctx.baseUrl()}/script-draft/autosave`, {method: 'POST', headers: headers(),
        body: JSON.stringify({payload: {scope_key: target.scopeKey, base_draft_revision: draft.draft_revision, content}})});
      if (!sameSession(target)) return;            // F01：过期响应不写当前会话
      draft.draft_revision = result.draft_revision; draft.exists = true;
      dirty = false;
      setStatus(`已保存 r${result.draft_revision}`);
      renderConflict(null);
    } catch (error) {
      if (!sameSession(target)) return;
      if (/已被他人/.test(error.message)) { setStatus('冲突：他人已更新'); renderConflict(error.message); }
      else { setStatus('保存失败，可继续编辑后重试'); lastError = error.message; notice(error.message); }
    } finally {
      saving = false;
      if (dirty && sameSession(target)) flushSave();  // 保存期间又有输入 → 继续队列
    }
  }
  async function waitForSave() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    if (dirty || saving) await flushSave();
    while (saving) await new Promise(resolve => setTimeout(resolve, 120));
    return !lastError && !dirty;
  }

  function readEditor() {
    // F03：以服务器稿为底，按稳定场／行身份只更新被编辑的字段，保留引用、静默时长等语义。
    const content = draft.exists && draft.content ? JSON.parse(JSON.stringify(draft.content)) : blank();
    const original = content.scenes || [];
    const scenes = [];
    for (const card of container.querySelectorAll('.script-scene')) {
      const sceneId = card.dataset.sceneId;
      const scene = original.find(row => row.id === sceneId)
        || {id: sceneId, estimated_duration_ms: 0, actions: [], dialogue: [], silence: []};
      scene.id = sceneId;
      const duration = Number(card.querySelector('.scene-duration')?.value || 0);
      if (duration || card.querySelector('.scene-duration')) scene.estimated_duration_ms = duration;
      for (const [field, kind, editor] of [['actions', 'action', null], ['dialogue', 'dialogue', '.line-speaker'], ['silence', 'silence', null]]) {
        const source = scene[field] || [];
        const rows = [];
        for (const row of card.querySelectorAll(`.scene-${field} .script-line`)) {
          const lineId = row.dataset.lineId;
          const saved = source.find(item => item.id === lineId) || {};
          const merged = {...saved, id: lineId, text: row.querySelector('.line-text').value};
          if (editor) merged.speaker = row.querySelector(editor)?.value || '';
          rows.push(merged);
        }
        scene[field] = rows;
      }
      scenes.push(scene);
    }
    content.scenes = scenes;
    return content;
  }

  function renderConflict(message) {
    const banner = container.querySelector('.script-conflict');
    if (!message) { banner.hidden = true; return; }
    banner.hidden = false;
    banner.replaceChildren(el('p', '', message + '。本地编辑仍在页面中；加载最新会以服务器内容替换当前编辑。'));
    const loadLatest = el('button', '', '加载最新并替换本地');
    loadLatest.addEventListener('click', async () => { if (!confirm('确定放弃本地未保存修改、加载服务器最新内容？')) return; dirty = false; await load(); });
    const keep = el('button', '', '保留本地暂不处理');
    keep.addEventListener('click', () => { banner.hidden = true; notice('已保留本地编辑；解决冲突前自动保存暂停。'); });
    banner.append(loadLatest, keep);
  }

  const phaseText = {empty: '未建立', editing: '编辑中', pending: '待人工确认', approved: '已批准基线', rejected: '已退回修改'};
  function render() {
    container.replaceChildren();
    const header = el('header', 'script-header');
    header.append(el('h2', '', '剧本'));
    statusChip = el('span', 'badge', '—');
    const phase = el('span', `badge ${draft.phase === 'pending' ? 'danger' : ''}`, phaseText[draft.phase] || draft.phase);
    const saved = el('span', 'hint', draft.exists ? `r${draft.draft_revision} · 更新 ${String(draft.updated_at || '').slice(0, 19)} · ${draft.updated_by || ''}` : '尚无工作副本');
    header.append(statusChip, phase, saved, scopeSelect || el('span'));
    container.append(header);
    const conflictBox = el('div', 'script-conflict'); conflictBox.hidden = true; container.append(conflictBox);
    if (draft.phase === 'pending' && draft.submitted) container.append(renderPending());
    container.append(draft.exists ? renderEditor() : renderBootstrap());
    container.append(renderNotes());
    setStatus(dirty ? '待保存' : '—');
  }

  async function refreshMeta() {
    // F02：批注等操作后只刷新元数据（批注/状态），不覆盖编辑器中的未保存内容。
    try {
      const fresh = await ctx.api(`${ctx.baseUrl()}/script-draft?scope_key=${encodeURIComponent(scopeKey)}`);
      if (!sameSession({project: ctx.baseUrl(), scopeKey})) return;
      draft.notes = fresh.notes; draft.phase = fresh.phase; draft.submitted = fresh.submitted; draft.base = fresh.base;
      render();
    } catch (error) { notice(error.message); }
  }

  function renderPending() {
    const box = el('section', 'script-pending');
    const submitted = draft.submitted;
    box.append(el('h3', '', '待人工确认'), el('p', 'hint',
      `冻结版本 ${submitted.artifact_key || ''} v${submitted.version} · SHA ${String(submitted.sha256 || '').slice(0, 12)}；批准前不能进入正式设计与资产生产。以下审阅的是被冻结的提交正文，不是当前编辑稿。`));
    const frozen = el('div', 'frozen-body hint');
    frozen.textContent = '正在读取被冻结的提交正文…';
    ctx.api(`${ctx.baseUrl()}/artifacts/${encodeURIComponent(submitted.id)}`).then(artifact => {
      const content = typeof artifact.content === 'string' ? artifact.content : JSON.stringify(artifact.content ?? '');
      let parsed = null;
      try { parsed = JSON.parse(content); } catch {}
      const scenes = parsed?.scenes || [];
      frozen.replaceChildren(el('p', '', `范围：${parsed?.scope || '全项目'} · 场次 ${scenes.length}`));
      for (const scene of scenes) {
        const block = el('div', 'frozen-scene');
        block.append(el('strong', '', `${scene.id}（约 ${scene.estimated_duration_ms || 0} ms）`));
        for (const row of scene.actions || []) block.append(el('div', '', `行动：${row.text}`));
        for (const row of scene.dialogue || []) block.append(el('div', '', `${row.speaker || ''}：${row.text}`));
        for (const row of scene.silence || []) block.append(el('div', '', `静默：${row.text}（${row.duration_ms || '?'} ms）`));
        frozen.append(block);
      }
      if (String(artifact.sha256 || submitted.sha256 || '') !== String(submitted.sha256 || '')) {
        frozen.append(el('p', 'badge danger', '冻结正文摘要与提交时不一致，请暂停并核对。'));
      }
    }).catch(error => { frozen.textContent = '读取冻结正文失败：' + error.message; });
    const reason = el('input'); reason.placeholder = '批准或退回的说明（必填）';
    const approve = el('button', '', '批准此版本');
    approve.addEventListener('click', async () => {
      if (!reason.value.trim()) return notice('请填写决定说明。');
      if (!confirm('确认批准当前提交的剧本版本？下游设计与制作将以该固定版本为基线。')) return;
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'approve', reason: reason.value}, true);
        notice('剧本已批准；下游设计可以开始。'); await load();
      } catch (error) { notice(error.message); }
    });
    const reject = el('button', '', '退回修改');
    reject.addEventListener('click', async () => {
      if (!reason.value.trim()) return notice('请填写退回说明。');
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'reject', reason: reason.value}, true);
        notice('已退回；工作副本回到编辑状态。'); await load();
      } catch (error) { notice(error.message); }
    });
    box.append(frozen, reason, approve, reject);
    return box;
  }

  function renderBootstrap() {
    const box = el('section', 'script-bootstrap');
    box.append(el('p', 'empty', '当前范围还没有剧本工作副本。点击开始后建立空白剧本；同一工作副本持续自动保存，提交确认才冻结正式版本。'));
    const blankButton = el('button', '', '从空白剧本开始');
    blankButton.addEventListener('click', async () => {
      requireSession();
      draft = {exists: false, draft_revision: 0, content: blank(), phase: 'editing', notes: draft.notes || []};
      dirty = true;
      await flushSave(); await load();
    });
    box.append(blankButton);
    return box;
  }

  function lineRow(sceneId, kind, row) {
    const item = el('div', 'script-line');
    item.dataset.lineId = row.id || `L${Math.random().toString(36).slice(2, 8)}`;
    if (kind === 'dialogue') {
      const speaker = el('input', 'line-speaker'); speaker.value = row.speaker || ''; speaker.placeholder = '人物';
      speaker.addEventListener('input', scheduleSave);
      item.append(speaker);
    }
    const text = el('input', 'line-text'); text.value = row.text || '';
    text.placeholder = kind === 'dialogue' ? '台词' : kind === 'action' ? '行动描述（可含 narrative_refs，编辑不会清除）' : '静默说明（时长/用途字段保留）';
    text.addEventListener('input', scheduleSave);
    const note = el('button', 'line-note', '批注');
    note.addEventListener('click', async () => {
      const body = prompt(`对 ${sceneId} / ${item.dataset.lineId} 的批注：`);
      if (!body) return;
      try { await write('script-notes', {scene_id: sceneId, line_id: item.dataset.lineId, body}); notice('批注已添加。'); await refreshMeta(); } catch (error) { notice(error.message); }
    });
    const remove = el('button', 'line-remove', '删除');
    remove.addEventListener('click', () => { item.remove(); scheduleSave(); });
    item.append(text, note, remove);
    return item;
  }

  function sceneCard(scene, index) {
    const card = el('section', 'script-scene');
    card.dataset.sceneId = scene.id || `SC${index + 1}`;
    const header = el('header', 'scene-header');
    const id = el('input', 'scene-id'); id.value = scene.id || ''; id.placeholder = '场次 ID（如 SC1）';
    id.addEventListener('change', () => { card.dataset.sceneId = id.value; scheduleSave(); });
    const duration = el('input', 'scene-duration'); duration.type = 'number'; duration.value = scene.estimated_duration_ms ?? 0; duration.title = '预估时长（毫秒）';
    duration.addEventListener('input', scheduleSave);
    const up = el('button', '', '上移');
    up.addEventListener('click', () => { if (card.previousElementSibling?.classList.contains('script-scene')) { card.parentNode.insertBefore(card, card.previousElementSibling); scheduleSave(); } });
    const down = el('button', '', '下移');
    down.addEventListener('click', () => { if (card.nextElementSibling?.classList.contains('script-scene')) { card.parentNode.insertBefore(card.nextElementSibling, card); scheduleSave(); } });
    const drop = el('button', '', '删除场次');
    drop.addEventListener('click', () => { if (confirm(`删除场次 ${card.dataset.sceneId}？`)) { card.remove(); scheduleSave(); } });
    header.append(id, el('span', 'hint', '时长(ms)'), duration, up, down, drop);
    card.append(header);
    for (const [className, label, field, kind] of [['scene-actions', '行动', 'actions', 'action'],
                                                   ['scene-dialogue', '对白', 'dialogue', 'dialogue'],
                                                   ['scene-silence', '静默', 'silence', 'silence']]) {
      const group = el('div', className);
      group.append(el('h4', '', label));
      const rows = el('div', 'scene-lines');
      for (const row of scene[field] || []) rows.append(lineRow(card.dataset.sceneId, kind, row));
      const add = el('button', 'line-add', `添加${label}`);
      add.addEventListener('click', () => { rows.append(lineRow(card.dataset.sceneId, kind,
        {id: `L${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`, text: ''})); scheduleSave(); });
      group.append(rows, add);
      card.append(group);
    }
    return card;
  }

  function renderEditor() {
    const wrap = el('div', 'script-editor');
    const toolbar = el('div', 'script-toolbar');
    const addScene = el('button', '', '添加场次');
    addScene.addEventListener('click', () => {
      draft.content = readEditor();
      draft.content.scenes.push({id: `SC${draft.content.scenes.length + 1}`, estimated_duration_ms: 0, actions: [], dialogue: [], silence: []});
      dirty = true; render(); scheduleSave();
    });
    const compare = el('button', '', '与已批准基线比较');
    compare.addEventListener('click', async () => {
      const saved = await waitForSave();
      if (!saved) return notice('存在未保存修改，先解决保存问题再比较。');
      try { renderCompare(await ctx.api(`${ctx.baseUrl()}/script-draft/compare?scope_key=${encodeURIComponent(scopeKey)}`)); }
      catch (error) { notice(error.message); }
    });
    const submit = el('button', 'script-submit-button', '提交人工确认');
    submit.addEventListener('click', async () => {
      const saved = await waitForSave();
      if (!saved || dirty || saving) return notice('保存未完成或失败，不得提交；请先成功保存当前内容。');  // F02/F04：提交屏障
      if (!confirm('提交后当前内容冻结为待确认版本，等待人工批准；批准前不能进入正式设计与资产生产。')) return;
      try {
        const result = await write('script-submit', {scope_key: scopeKey, base_draft_revision: draft.draft_revision,
          artifact_type: 'vsc.screenplay', stage: 'script'});
        notice(`已提交待确认：版本 ${result.artifact.version}。`); await load();
      } catch (error) { notice(error.message); }
    });
    toolbar.append(addScene, compare, submit, el('span', 'hint', '编辑自动保存到工作副本（只更新被改字段，引用与静默语义保留）；提交才形成正式待确认版本。'));
    wrap.append(toolbar);
    const board = el('div', 'script-board');
    const content = draft.exists && draft.content ? draft.content : blank();
    for (const [index, scene] of (content.scenes || []).entries()) board.append(sceneCard(scene, index));
    if (!(content.scenes || []).length) board.append(el('p', 'empty', '还没有场次；点击“添加场次”开始写剧本。'));
    wrap.append(board);
    return wrap;
  }

  function renderCompare(result) {
    let panel = container.querySelector('.script-compare');
    if (!panel) { panel = el('section', 'script-compare'); container.insertBefore(panel, container.querySelector('.script-notes')); }
    panel.replaceChildren(el('h3', '', '与已批准基线的差异'));
    const changes = result.changes || {};
    if (!changes.changed) { panel.append(el('p', 'hint', result.base ? '与基线一致，没有结构差异。' : '尚无该范围的已批准基线；提交并获得批准后才会形成比较基线。')); return; }
    const scenes = changes.scenes || {};
    const summary = [];
    if (scenes.added?.length) summary.push(`新增场次 ${scenes.added.join('、')}`);
    if (scenes.removed?.length) summary.push(`删除场次 ${scenes.removed.join('、')}`);
    if (scenes.moved?.length) summary.push(`移动场次 ${scenes.moved.join('、')}`);
    if (summary.length) panel.append(el('p', '', summary.join('；')));
    const list = el('ul', 'compare-list');
    for (const change of changes.lines || []) {
      const item = el('li', '', `${change.scene_id || ''} ${change.line_id || ''} ${change.field || ''}（${change.change}）`);
      if (change.before != null) item.append(el('s', '', JSON.stringify(change.before)));
      if (change.after != null) item.append(el('b', '', JSON.stringify(change.after)));
      list.append(item);
    }
    panel.append(list);
  }

  function renderNotes() {
    const panel = el('section', 'script-notes');
    const notes = draft.notes || [];
    panel.append(el('h3', '', `批注（${notes.filter(row => row.status === 'open').length} 待处理 / 共 ${notes.length}）`));
    const list = el('ul', 'notes-list');
    for (const note of notes) {
      const item = el('li', `note-${note.status}`);
      item.append(el('span', 'note-anchor', `${note.scene_id}${note.line_id ? ' / ' + note.line_id : ''}`),
        el('span', '', note.body),
        el('small', '', `${note.author} · ${String(note.created_at || '').slice(0, 19)} · ${{open: '待处理', resolved: '已解决', dismissed: '已忽略'}[note.status]}`));
      if (note.status === 'open') {
        const resolve = el('button', '', '解决');
        resolve.addEventListener('click', async () => {
          const reason = prompt('解决说明：'); if (!reason) return;
          try { await write('script-note-decisions', {note_id: note.id, outcome: 'resolve', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        const dismiss = el('button', '', '忽略');
        dismiss.addEventListener('click', async () => {
          const reason = prompt('忽略说明：'); if (!reason) return;
          try { await write('script-note-decisions', {note_id: note.id, outcome: 'dismiss', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        item.append(resolve, dismiss);
      }
      list.append(item);
    }
    if (!notes.length) list.append(el('li', 'hint', '还没有批注；在台词或行动行点“批注”。'));
    panel.append(list, el('p', 'hint', '批注只锚定场次／行身份，不进入剧本正文；解决批注不等于批准剧本。'));
    return panel;
  }

  return {load, reload: load};
}
