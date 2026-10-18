/* 剧本工作区：可变工作副本 + 串行自动保存 + 批注 + 差异 + 提交人工确认。
   本模块只消费后端事实（draft / artifact 决定），不拥有批准权威。
   F01/F02：保存会话绑定 project+scope，串行保存队列，过期响应与切换后定时器不写当前会话；
   F03：readEditor 按稳定身份合并编辑字段，保留未编辑的引用与静默语义；
   冻结版本审阅读取完整正文和真实范围；分集导航分页并按项目重建。 */

export function createScriptWorkspace(container, ctx) {
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; };
  const notice = message => { if (message) ctx.onNotice(message); };
  const blank = () => ({format: 'vsc.screenplay/v1', body: '', adaptation_refs: [], scenes: []});
  let draft = null, scopeKey = '', scopeSelect = null, statusChip = null;
  let session = null, generation = 0, metadataGeneration = 0;
  let saveTimer = null, saving = false, lastError = null, editSeq = 0, savedSeq = 0, conflict = false;
  let conflictMessage = null;
  const recoveries = new Map(); // 仅当前工作区实例内存；不写本地存储或项目事实。
  const recoveryKey = target => JSON.stringify([target.project, target.scopeKey]);

  const sameSession = target => session && target && target.generation === session.generation
    && target.project === session.project && target.project === ctx.baseUrl()
    && target.scopeKey === session.scopeKey && target.scopeKey === scopeKey;
  const stale = () => new Error('');
  const uniqueId = prefix => `${prefix}-${crypto.randomUUID()}`;

  function rememberLocal() {
    if (!session || !draft) return;
    const key = recoveryKey(session);
    if (editSeq <= savedSeq && !saving && !conflict) { recoveries.delete(key); return; }
    recoveries.set(key, {generation: session.generation, content: readEditor(), draft_revision: draft.draft_revision,
      editSeq, savedSeq, inFlight: saving, conflict, conflictMessage, lastError});
  }

  function restoreLocal(target, fresh) {
    const cached = recoveries.get(recoveryKey(target));
    if (!cached) return;
    draft = {...fresh, exists: true, content: cached.content, draft_revision: cached.draft_revision, phase: 'editing'};
    editSeq = cached.editSeq; savedSeq = cached.savedSeq;
    conflict = cached.conflict || cached.inFlight || fresh.draft_revision !== cached.draft_revision;
    if (conflict) {
      conflictMessage = cached.conflictMessage || (cached.inFlight
        ? '已恢复本地编辑，但离开时的保存请求尚未确认；自动保存暂停，请核对服务器最新版本'
        : `已恢复本地编辑，其基准 r${cached.draft_revision} 与服务器 r${fresh.draft_revision} 不同；自动保存暂停，请人工核对`);
    } else {
      // 失败保存已结束且服务器基准未变，允许原内容按原稿次重试。
      lastError = null;
    }
  }

  function recordDepartedSave(target, seq, result, error) {
    const key = recoveryKey(target), cached = recoveries.get(key);
    if (!cached || cached.generation !== target.generation) return;
    cached.inFlight = false;
    if (error) {
      cached.lastError = error.message;
      if (/已被他人/.test(error.message)) { cached.conflict = true; cached.conflictMessage = error.message; }
      return;
    }
    cached.draft_revision = result.draft_revision;
    cached.savedSeq = Math.max(cached.savedSeq, seq); cached.lastError = null;
    if (cached.editSeq <= cached.savedSeq && !cached.conflict) recoveries.delete(key);
  }

  const pageWindow = typeof window !== 'undefined' ? window : null;
  const beforeUnload = event => {
    if (editSeq <= savedSeq && !saving && !conflict && recoveries.size === 0) return;
    event.preventDefault(); event.returnValue = '';
  };
  pageWindow?.addEventListener('beforeunload', beforeUnload);

  function headers() { return {'Content-Type': 'application/json', 'X-CSRF-Token': ctx.session().csrf}; }
  function requireSession() {
    const value = ctx.session();
    if (!value.actor) throw new Error('请先在顶栏建立操作会话；未登录时剧本页只读。');
    return value;
  }
  async function write(action, payload, confirmed = false, target = session) {
    if (!sameSession(target)) throw stale();
    const value = requireSession();
    let result;
    try {
      result = await ctx.api(`${target.project}/${action}`, {method: 'POST', headers: headers(),
        body: JSON.stringify({payload, confirmed, expected_revision: value.revision, idempotency_key: crypto.randomUUID()})});
    } catch (error) { if (!sameSession(target)) throw stale(); throw error; }
    if (!sameSession(target)) throw stale();
    ctx.setRevision(result.revision ?? value.revision);
    return result;
  }

  async function loadEpisodes(target) {
    const episodes = [];
    async function children(objectId) {
      const rows = [], seen = new Set();
      let offset = 0;
      do {
        if (!sameSession(target)) return [];
        const result = await ctx.api(`${target.project}/workbench?section=children&limit=100&offset=${offset}${objectId ? '&object_id=' + encodeURIComponent(objectId) : ''}`);
        if (!sameSession(target)) return [];
        const page = result.sections?.children || {};
        rows.push(...(page.items || []));
        seen.add(offset);
        offset = page.next_offset;
      } while (offset != null && !seen.has(offset));
      return rows;
    }
    try {
      for (const work of (await children()).filter(node => node.kind === 'work')) {
        for (const node of (await children(work.id)).filter(row => row.kind === 'episode')) {
          episodes.push({id: node.id, label: `${work.title || work.display_code || ''} · ${node.title || node.display_code || node.id}`});
        }
      }
    } catch { /* 旧项目或无分集：仅全项目剧本 */ }
    return episodes;
  }

  async function ensureScopeSelect(target) {
    if (scopeSelect && scopeSelect.dataset.projectId === target.project) return;
    const select = el('select', 'script-scope');
    select.dataset.projectId = target.project;
    select.setAttribute('aria-label', '剧本范围');
    const all = el('option', '', '全项目剧本'); all.value = ''; select.append(all);
    for (const episode of await loadEpisodes(target)) {
      const option = el('option', '', `分集剧本：${episode.label}`);
      option.value = episode.id; select.append(option);
    }
    if (!sameSession(target)) return;
    select.value = target.scopeKey;
    select.addEventListener('change', async () => {
      if (select !== scopeSelect || target.project !== ctx.baseUrl()) return;
      scopeKey = select.value; await load();
    });
    scopeSelect = select;
  }

  async function load(options = {}) {
    if (options.discardLocal === true) {
      if (session) recoveries.delete(recoveryKey(session));
    } else rememberLocal();
    const project = ctx.baseUrl();
    if (session && session.project !== project) { scopeKey = ''; scopeSelect = null; }
    const target = {project, scopeKey, generation: ++generation};
    session = target;
    clearTimeout(saveTimer); saveTimer = null; saving = false; lastError = null; conflict = false; conflictMessage = null; editSeq = 0; savedSeq = 0;
    draft = null;
    container.replaceChildren(el('p', 'hint', '正在读取剧本工作副本…'));
    try {
      await ensureScopeSelect(target);
      if (!sameSession(target)) return;
      const fresh = await ctx.api(`${target.project}/script-draft?scope_key=${encodeURIComponent(target.scopeKey)}`);
      if (!sameSession(target)) return;
      draft = fresh;
      restoreLocal(target, fresh);
      render();
      if (!conflict && editSeq > savedSeq) saveTimer = setTimeout(() => sameSession(target) && flushSave(), 900);
    } catch (error) { if (sameSession(target)) notice(error.message); }
  }

  function setStatus(text) { if (statusChip) statusChip.textContent = text; }
  function scheduleSave() {
    if (!sameSession(session) || !draft) return;
    editSeq++;                                     // F02：编辑序号与保存进度分离
    setStatus(conflict ? '本地修改已保留，冲突待核对' : '待保存');
    updatePhase();
    if (conflict) return;
    clearTimeout(saveTimer);
    const target = session;
    saveTimer = setTimeout(() => sameSession(target) && flushSave(), 900);
  }
  async function flushSave() {
    if (!sameSession(session) || !draft || saving || conflict || editSeq <= savedSeq) return;
    const target = {...session};
    const seqAtSend = editSeq;
    saving = true; setStatus('保存中…');
    try {
      requireSession();
      const content = readEditor();
      const result = await ctx.api(`${target.project}/script-draft/autosave`, {method: 'POST', headers: headers(),
        body: JSON.stringify({payload: {scope_key: target.scopeKey, base_draft_revision: draft.draft_revision, content}})});
      if (!sameSession(target)) { recordDepartedSave(target, seqAtSend, result); return; }
      draft.draft_revision = result.draft_revision; draft.exists = true; draft.content = content;
      draft.phase = result.phase || 'editing';
      savedSeq = Math.max(savedSeq, seqAtSend);
      if (editSeq <= savedSeq) recoveries.delete(recoveryKey(target));
      updatePhase();
      const saved = container.querySelector('.script-saved-version');
      if (saved) saved.textContent = `工作副本 r${draft.draft_revision}`;
      lastError = null; renderConflict(null);
    } catch (error) {
      if (!sameSession(target)) { recordDepartedSave(target, seqAtSend, null, error); return; }
      if (/已被他人/.test(error.message)) { conflict = true; setStatus('冲突：他人已更新'); renderConflict(error.message); }
      else { setStatus('保存失败，可继续编辑后重试'); lastError = error.message; notice(error.message); }
    } finally {
      if (sameSession(target)) {
        saving = false;
        if (!conflict && !lastError && editSeq > savedSeq) saveTimer = setTimeout(() => sameSession(target) && flushSave(), 0);
        else if (!lastError && !conflict && editSeq <= savedSeq) setStatus(`已保存 r${draft.draft_revision}`);
      }
    }
  }
  async function waitForSave() {
    const target = session;
    clearTimeout(saveTimer); saveTimer = null;
    if (!saving && !lastError && editSeq > savedSeq && !conflict) await flushSave();
    while (sameSession(target) && saving) await new Promise(resolve => setTimeout(resolve, 50));
    return sameSession(target) && !lastError && !conflict && editSeq <= savedSeq;
  }

  function readEditor() {
    // F03：以服务器稿为底，按稳定场／行身份只更新被编辑的字段，保留引用、静默时长等语义。
    const content = draft.content ? JSON.parse(JSON.stringify(draft.content)) : blank();
    const body = container.querySelector('.script-body');
    if (body) content.body = body.value;
    content.adaptation_refs = Array.from(container.querySelectorAll('.script-adaptation-ref'), row => ({
      ...((content.adaptation_refs || []).find(ref => ref.id === row.dataset.refId) || {}),
      id: row.querySelector('.adaptation-id').value.trim(), sha256: row.querySelector('.adaptation-sha').value.trim(),
    }));
    const original = content.scenes || [];
    const scenes = [];
    for (const card of container.querySelectorAll('.script-scene')) {
      const sceneId = card.dataset.sceneId;
      const scene = original.find(row => row.id === sceneId)
        || {id: sceneId, estimated_duration_ms: 0, actions: [], dialogue: [], silence: []};
      scene.id = sceneId;
      const duration = card.querySelector('.scene-duration');
      if (duration) scene.estimated_duration_ms = Number(duration.value || 0);
      const byGroup = {action: [], dialogue: [], silence: []};
      for (const row of card.querySelectorAll('.script-line')) {
        const kind = row.dataset.group || 'action';
        const lineId = row.dataset.lineId;
        const source = (scene[{action: 'actions', dialogue: 'dialogue', silence: 'silence'}[kind]] || []);
        const saved = source.find(item => item.id === lineId) || {};
        const merged = {...saved, id: lineId, text: row.querySelector('.line-text').value};
        merged.narrative_refs = (row.querySelector('.line-refs')?.value || '').split(/[\s,，]+/).filter(Boolean);
        if (kind === 'dialogue') merged.speaker = row.querySelector('.line-speaker')?.value || '';
        if (kind === 'silence') {
          merged.duration_ms = Number(row.querySelector('.line-duration')?.value || 0);
          merged.purpose = row.querySelector('.line-purpose')?.value || '';
        }
        byGroup[kind].push(merged);
      }
      scene.actions = byGroup.action;
      scene.dialogue = byGroup.dialogue;
      scene.silence = byGroup.silence;
      scenes.push(scene);
    }
    content.scenes = scenes;
    return content;
  }

  function renderConflict(message) {
    const banner = container.querySelector('.script-conflict');
    conflictMessage = message;
    if (!message) { banner.hidden = true; return; }
    banner.hidden = false;
    banner.replaceChildren(el('p', '', message + '。本地编辑仍在页面中；加载最新会以服务器内容替换当前编辑。'));
    const loadLatest = el('button', '', '加载最新并替换本地');
    const target = session;
    loadLatest.addEventListener('click', async () => {
      if (!sameSession(target) || !confirm('确定放弃本地未保存修改、加载服务器最新内容？')) return;
      await load({discardLocal: true});
    });
    const keep = el('button', '', '保留本地暂不处理');
    keep.addEventListener('click', () => { banner.hidden = true; notice('已保留本地编辑；解决冲突前自动保存暂停。'); });
    banner.append(loadLatest, keep);
  }

  const phaseText = {empty: '未建立', editing: '编辑中', pending: '待人工确认', approved: '已批准基线', rejected: '已退回修改', revoked: '批准已撤销'};
  function updatePhase() {
    const chip = container.querySelector('.script-phase');
    if (chip) chip.textContent = phaseText[editSeq > savedSeq ? 'editing' : draft.phase] || draft.phase;
  }
  function render() {
    container.replaceChildren();
    const header = el('header', 'script-header');
    header.append(el('h2', '', '剧本'));
    statusChip = el('span', 'badge', '—');
    const phase = el('span', `badge script-phase ${draft.phase === 'pending' ? 'danger' : ''}`, phaseText[draft.phase] || draft.phase);
    const saved = el('span', 'hint script-saved-version', draft.exists ? `r${draft.draft_revision} · 更新 ${String(draft.updated_at || '').slice(0, 19)} · ${draft.updated_by || ''}` : '尚无工作副本');
    header.append(statusChip, phase, saved, scopeSelect || el('span'));
    container.append(header);
    const conflictBox = el('div', 'script-conflict'); conflictBox.hidden = true; container.append(conflictBox);
    if (draft.submitted) container.append(renderPending());
    container.append(draft.exists ? renderEditor() : renderBootstrap());
    container.append(renderSuggestions());
    if (draft.submitted?.state === 'pending') renderImpact();
    container.append(renderNotes());
    updatePhase();
    if (conflict) renderConflict(conflictMessage || '本地内容待核对，自动保存暂停');
    setStatus(conflict ? '本地修改已保留，冲突待核对' : editSeq > savedSeq ? '待保存' : '—');
  }

  async function refreshMeta() {
    const target = session;
    const request = ++metadataGeneration;
    try {
      const fresh = await ctx.api(`${target.project}/script-draft?scope_key=${encodeURIComponent(target.scopeKey)}`);
      if (!sameSession(target) || request !== metadataGeneration) return;
      draft.notes = fresh.notes; draft.phase = fresh.phase; draft.submitted = fresh.submitted; draft.base = fresh.base;
      draft.suggestions = fresh.suggestions;
      // 批注决策不拥有正文或 draft_revision；保留本地编辑与保存队列的原始基准。
      for (const [selector, panel] of [['.script-notes', renderNotes()], ['.script-suggestions', renderSuggestions()]]) {
        const previous = container.querySelector(selector);
        if (previous) previous.replaceChildren(...Array.from(panel.children));
      }
      const previous = container.querySelector('.script-pending');
      const stamp = draft.submitted ? `${draft.submitted.id}:${draft.submitted.state}` : '';
      if (draft.submitted && previous?.dataset.submissionStamp !== stamp) {
        previous?.remove();
        container.insertBefore(renderPending(), container.querySelector('.script-editor') || container.querySelector('.script-bootstrap'));
      } else if (!draft.submitted) previous?.remove();
      if (draft.submitted?.state === 'pending') renderImpact();
      else container.querySelector('.script-impact')?.remove();
      updatePhase();
    } catch (error) { if (sameSession(target)) notice(error.message); }
  }

  function renderPending() {
    const box = el('section', 'script-pending');
    const submitted = draft.submitted;
    box.dataset.submissionStamp = `${submitted.id}:${submitted.state}`;
    const target = session;
    const pending = submitted.state === 'pending';
    box.append(el('h3', '', pending ? '冻结版本待人工确认' : `冻结版本：${phaseText[submitted.state] || submitted.state}`), el('p', 'hint',
      `冻结版本 ${submitted.artifact_key || ''} v${submitted.version} · SHA ${String(submitted.sha256 || '').slice(0, 12)}。以下审阅的是被冻结的提交正文。${pending ? '决定只对该固定版本生效。' : ''}`));
    if (submitted.matches_draft === false) box.append(el('p', 'hint', '服务器确认当前工作副本与此冻结版本不同；工作副本继续编辑，冻结版本保留自己的决定。'));
    const frozen = el('div', 'frozen-body hint');
    frozen.textContent = '正在读取被冻结的提交正文…';
    let reviewed = false;
    const reason = el('input', 'script-decision-reason'); reason.placeholder = '批准或退回的说明（必填）';
    const approve = el('button', 'script-approve-button', '批准此版本'); approve.disabled = true;
    const reject = el('button', 'script-reject-button', '退回修改'); reject.disabled = true;
    ctx.api(`${target.project}/artifacts/${encodeURIComponent(submitted.id)}`).then(artifact => {
      if (!sameSession(target) || draft.submitted?.id !== submitted.id) return;
      const content = typeof artifact.content === 'string' ? artifact.content : JSON.stringify(artifact.content ?? '');
      let parsed = null;
      try { parsed = JSON.parse(content); } catch {}
      if (!parsed || !Array.isArray(parsed.scenes) || artifact.id !== submitted.id || !submitted.sha256 || artifact.sha256 !== submitted.sha256) {
        frozen.textContent = '冻结正文或摘要与提交记录不一致，请重新加载并核对。'; return;
      }
      const scenes = parsed?.scenes || [];
      frozen.replaceChildren(el('p', '', `范围：${artifact.project_wide ? '全项目' : (artifact.object_ids || []).join('、')} · 场次 ${scenes.length}`),
        el('p', 'frozen-screenplay-body', parsed.body || ''), el('p', '', `改编来源：${JSON.stringify(parsed.adaptation_refs || [])}`));
      for (const scene of scenes) {
        const block = el('div', 'frozen-scene');
        block.append(el('strong', '', `${scene.id}（约 ${scene.estimated_duration_ms || 0} ms）`));
        for (const row of scene.actions || []) block.append(el('div', '', `行动：${row.text} · 叙事来源 ${(row.narrative_refs || []).join('、')}`));
        for (const row of scene.dialogue || []) block.append(el('div', '', `${row.speaker || ''}：${row.text} · 叙事来源 ${(row.narrative_refs || []).join('、')}`));
        for (const row of scene.silence || []) block.append(el('div', '', `静默：${row.text}（${row.duration_ms || '?'} ms；${row.purpose || ''}） · 叙事来源 ${(row.narrative_refs || []).join('、')}`));
        frozen.append(block);
      }
      frozen.append(el('p', '', `固定前置版本：${(artifact.dependency_ids || artifact.dependencies?.map(row => row.id) || []).join('、')}`));
      reviewed = true; approve.disabled = !pending; reject.disabled = !pending;
    }).catch(error => { if (sameSession(target)) frozen.textContent = '读取冻结正文失败：' + error.message; });
    approve.addEventListener('click', async () => {
      if (!reviewed || !pending || !sameSession(target)) return;
      if (!reason.value.trim()) return notice('请填写决定说明。');
      if (!confirm('确认批准当前提交的剧本版本？下游设计与制作将以该固定版本为基线。')) return;
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'approve', reason: reason.value}, true, target);
        notice('冻结剧本版本已批准。'); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    reject.addEventListener('click', async () => {
      if (!reviewed || !pending || !sameSession(target)) return;
      if (!reason.value.trim()) return notice('请填写退回说明。');
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'reject', reason: reason.value}, true, target);
        notice('冻结版本已退回修改。'); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    box.append(frozen);
    if (pending) box.append(reason, approve, reject);
    return box;
  }

  function renderBootstrap() {
    const box = el('section', 'script-bootstrap');
    box.append(el('p', 'empty', '当前范围还没有剧本工作副本。点击开始后建立空白剧本；同一工作副本持续自动保存，提交确认才冻结正式版本。'));
    const blankButton = el('button', '', '从空白剧本开始');
    blankButton.addEventListener('click', async () => {
      requireSession();
      draft = {...draft, exists: true, draft_revision: 0, content: draft.template_content || blank(), phase: 'editing'};
      editSeq = 1; savedSeq = 0;
      render(); await flushSave();
    });
    box.append(blankButton);
    return box;
  }

  function lineRow(sceneId, kind, row) {
    const item = el('div', 'script-line');
    item.dataset.lineId = row.id || uniqueId('L');
    item.dataset.group = kind;
    if (kind === 'dialogue') {
      const speaker = el('input', 'line-speaker'); speaker.value = row.speaker || ''; speaker.placeholder = '人物';
      speaker.addEventListener('input', scheduleSave);
      item.append(speaker);
    }
    const text = el('input', 'line-text'); text.value = row.text || '';
    text.placeholder = kind === 'dialogue' ? '台词' : kind === 'action' ? '行动描述' : '静默说明';
    text.addEventListener('input', scheduleSave);
    const note = el('button', 'line-note', '批注');
    note.addEventListener('click', async () => {
      const target = session;
      const body = prompt(`对 ${sceneId} / ${item.dataset.lineId} 的批注：`);
      if (!body) return;
      const saved = await waitForSave();
      if (!sameSession(target)) return;
      if (!saved) return notice('当前正文尚未成功保存，不能绑定批注；本地编辑已保留，请先解决保存问题。');
      const revision = draft.draft_revision;
      try {
        await write('script-notes', {scope_key: target.scopeKey, scene_id: sceneId, line_id: item.dataset.lineId,
          body, base_draft_revision: revision}, false, target);
        notice(`批注已添加，绑定工作副本 r${revision}。`); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    const remove = el('button', 'line-remove', '删除');
    remove.addEventListener('click', () => { item.remove(); scheduleSave(); });
    item.append(text, note, remove);
    const refs = el('input', 'line-refs'); refs.value = (row.narrative_refs || []).join(', ');
    refs.placeholder = '叙事来源 ID（逗号分隔）'; refs.setAttribute('aria-label', '叙事来源 ID');
    refs.addEventListener('input', scheduleSave); item.append(refs);
    if (kind === 'silence') {
      const duration = el('input', 'line-duration'); duration.type = 'number'; duration.min = '1';
      duration.value = row.duration_ms ?? ''; duration.placeholder = '静默时长(ms)'; duration.setAttribute('aria-label', '静默时长（毫秒）');
      const purpose = el('input', 'line-purpose'); purpose.value = row.purpose || ''; purpose.placeholder = '静默用途'; purpose.setAttribute('aria-label', '静默用途');
      duration.addEventListener('input', scheduleSave); purpose.addEventListener('input', scheduleSave);
      item.append(duration, purpose);
    }
    return item;
  }

  function sceneCard(scene) {
    const card = el('section', 'script-scene');
    card.dataset.sceneId = scene.id || uniqueId('SC');
    const header = el('header', 'scene-header');
    const id = el('input', 'scene-id'); id.value = card.dataset.sceneId; id.readOnly = true;
    id.title = '固定场次身份；移动场次不会改变批注锚点'; id.setAttribute('aria-label', '固定场次 ID');
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
        {id: uniqueId('L'), text: '', narrative_refs: []})); scheduleSave(); });
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
      try {
        draft.content = readEditor();
        draft.content.scenes.push({id: uniqueId('SC'), estimated_duration_ms: 0, actions: [], dialogue: [], silence: []});
        render(); scheduleSave();
      } catch (error) { notice(error.message); }
    });
    const compare = el('button', '', '与已批准基线比较');
    compare.addEventListener('click', async () => {
      const target = session;
      const saved = await waitForSave();
      if (!saved) return notice('存在未保存修改，先解决保存问题再比较。');
      try {
        const result = await ctx.api(`${target.project}/script-draft/compare?scope_key=${encodeURIComponent(target.scopeKey)}`);
        if (sameSession(target)) renderCompare(result);
      } catch (error) { if (sameSession(target)) notice(error.message); }
    });
    const submit = el('button', 'script-submit-button', '提交人工确认');
    submit.addEventListener('click', async () => {
      const target = session;
      const saved = await waitForSave();
      if (!saved) return notice('保存未完成、失败或存在冲突，不得提交；请先成功保存当前内容。');  // F02/F04：提交屏障
      if (!confirm('提交后当前内容冻结为待确认版本，等待人工批准；批准前不能进入正式设计与资产生产。')) return;
      try {
        const context = draft.submission_context;
        if (!context) return notice('缺少当前范围的提交前置事实，请重新加载后再提交。');
        if (context.missing_dependency_types?.length) return notice(`缺少已批准前置版本：${context.missing_dependency_types.join('、')}`);
        const result = await write('script-submit', {scope_key: target.scopeKey, base_draft_revision: draft.draft_revision,
          artifact_type: context.artifact_type, dependency_ids: [...(context.dependency_ids || [])]}, false, target);
        notice(`已提交待确认：版本 ${result.artifact.version}。`); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    toolbar.append(addScene, compare, submit, el('span', 'hint', '编辑自动保存到工作副本（只更新被改字段，引用与静默语义保留）；提交才形成正式待确认版本。'));
    wrap.append(toolbar);
    const board = el('div', 'script-board');
    const content = draft.content || blank();
    const fields = el('section', 'script-document-fields');
    const bodyLabel = el('label', '', '剧本正文');
    const body = el('textarea', 'script-body'); body.value = content.body || ''; body.rows = 6;
    body.addEventListener('input', scheduleSave); bodyLabel.append(body); fields.append(bodyLabel);
    fields.append(el('h4', '', '改编来源（固定版本 ID 与 SHA）'));
    const refs = el('div', 'script-adaptation-refs');
    function addRef(ref = {}) {
      const row = el('div', 'script-adaptation-ref'); row.dataset.refId = ref.id || '';
      const id = el('input', 'adaptation-id'); id.value = ref.id || ''; id.placeholder = '来源版本 ID'; id.setAttribute('aria-label', '改编来源版本 ID');
      const sha = el('input', 'adaptation-sha'); sha.value = ref.sha256 || ''; sha.placeholder = '来源 SHA-256'; sha.setAttribute('aria-label', '改编来源 SHA-256');
      const remove = el('button', '', '移除来源'); remove.addEventListener('click', () => { row.remove(); scheduleSave(); });
      id.addEventListener('input', scheduleSave); sha.addEventListener('input', scheduleSave); row.append(id, sha, remove); refs.append(row);
    }
    for (const ref of content.adaptation_refs || []) addRef(ref);
    const addRefButton = el('button', 'script-add-adaptation', '添加改编来源');
    addRefButton.addEventListener('click', () => { addRef(); scheduleSave(); });
    const dependencies = draft.submission_context;
    fields.append(refs, addRefButton, el('p', 'script-dependencies hint', dependencies
      ? `提交固定前置：${(dependencies.dependencies || []).map(row => `${row.artifact_key || row.artifact_type || row.id} v${row.version} · ${row.sha256}`).join('；') || '当前 Profile 无前置要求'}${dependencies.missing_dependency_types?.length ? '；缺少已批准版本：' + dependencies.missing_dependency_types.join('、') : ''}`
      : '正在等待当前范围的提交前置事实。'));
    wrap.append(fields);
    for (const scene of content.scenes || []) board.append(sceneCard(scene));
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

  function renderSuggestions() {
    const panel = el('section', 'script-suggestions');
    const suggestions = draft.suggestions || [];
    const pending = suggestions.filter(row => row.status === 'pending');
    panel.append(el('h3', '', `修改建议（${pending.length} 待处理 / 共 ${suggestions.length}）`));
    const list = el('ul', 'notes-list');
    for (const row of suggestions) {
      const item = el('li', `note-${row.status}`);
      const label = `${row.scene_id}${row.line_id ? ' / ' + row.line_id : ''} · ${row.kind}.${row.field}`;
      item.append(el('span', 'note-anchor', label), el('s', '', String(row.before_value ?? '')),
        el('b', '', String(row.after_value)), el('small', '', `${row.origin} · r${row.base_draft_revision} · ${row.reason}`));
      if (row.status === 'pending') {
        const accept = el('button', '', '接受这一处');
        accept.addEventListener('click', async () => {
          const target = session, seq = editSeq;
          if (editSeq > savedSeq || saving) return notice('有未保存编辑；先成功保存再接受建议。');
          const reason = prompt('接受说明：'); if (!reason) return;
          try {
            await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
              outcome: 'accept', reason}, false, target);
            notice('建议已应用到工作副本；编辑器已刷新为新稿。');
            await refreshChangedDraft(target, seq);
          } catch (error) { notice(error.message); }
        });
        const reject = el('button', '', '拒绝');
        reject.addEventListener('click', async () => {
          const reason = prompt('拒绝说明：'); if (!reason) return;
          try { await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
            outcome: 'reject', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        item.append(accept, reject);
      } else if (row.status === 'accepted') {
        const undo = el('button', '', '撤销接受');
        undo.addEventListener('click', async () => {
          const target = session, seq = editSeq;
          if (editSeq > savedSeq || saving) return notice('有未保存编辑；先成功保存再撤销。');
          const reason = prompt('撤销说明：'); if (!reason) return;
          try {
            await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
              outcome: 'undo_accept', reason}, false, target);
            notice('已撤销并改回原值。');
            await refreshChangedDraft(target, seq);
          } catch (error) { notice(error.message); }
        });
        item.append(undo);
      }
      list.append(item);
    }
    if (!suggestions.length) list.append(el('li', 'hint', '还没有修改建议；建议经 API 以稳定行身份提出（origin=ai 时标注来源），逐处接受，不整稿覆盖。'));
    panel.append(list);
    return panel;
  }

  async function renderImpact() {
    const target = session;
    let panel = container.querySelector('.script-impact');
    if (!panel) { panel = el('section', 'script-impact'); container.insertBefore(panel, container.querySelector('.script-suggestions')); }
    panel.replaceChildren(el('h3', '', '修订影响（相对已批准基线）'), el('p', 'hint', '读取中…'));
    try {
      const impact = await ctx.api(`${target.project}/script-draft/impact?scope_key=${encodeURIComponent(target.scopeKey)}`);
      if (!sameSession(target)) return;
      panel.replaceChildren(el('h3', '', '修订影响（相对已批准基线）'));
      if (!impact.changed_lines.length && !impact.shots.length && !impact.cues.length) {
        panel.append(el('p', 'hint', impact.baseline_artifact_id ? '没有检出会影响下游的行级变化。' : '该范围尚无已批准基线，无从比对影响。'));
        return;
      }
      const lines = el('ul', 'compare-list');
      for (const change of impact.changed_lines) {
        const item = el('li', '', `${change.scene_id || ''} ${change.line_id || ''} ${change.field || ''}（${change.change}）`);
        if (change.before != null) item.append(el('s', '', JSON.stringify(change.before)));
        if (change.after != null) item.append(el('b', '', JSON.stringify(change.after)));
        lines.append(item);
      }
      panel.append(lines);
      const meta = [];
      if (impact.shots.length) meta.push(`覆盖镜头 ${impact.shots.map(s => s.display_code || s.title || s.id).join('、')}`);
      if (impact.cues.length) meta.push(`声音Cue ${impact.cues.map(c => c.label || c.cue_key || c.id).join('、')}${impact.cues.some(c => c.timeline_items) ? `（含时间线用料 ${impact.cues.reduce((n, c) => n + (c.timeline_items || 0), 0)} 处）` : ''}`);
      if (impact.unresolved?.length) meta.push(`待核实 ${impact.unresolved.length} 项（基线缺行或场级变化）`);
      for (const line of meta) panel.append(el('p', '', line));
      panel.append(el('p', 'hint', '影响清单来自真实覆盖／声音Cue／时间线关系；未列出的关系不代表不存在，标注为待核实。'));
    } catch (error) { if (sameSession(target)) panel.append(el('p', 'hint', '影响读取失败：' + error.message)); }
  }

  async function refreshChangedDraft(target, seq) {
    const fresh = await ctx.api(`${target.project}/script-draft?scope_key=${encodeURIComponent(target.scopeKey)}`);
    if (!sameSession(target)) return;
    if (editSeq !== seq || saving) {
      conflict = true; clearTimeout(saveTimer); saveTimer = null;
      renderConflict('建议决策期间出现本地编辑，服务器已更新；请保留本地内容并核对最新版本');
      return;
    }
    draft = fresh; editSeq = 0; savedSeq = 0; render();
  }

  function renderNotes() {
    const panel = el('section', 'script-notes');
    const notes = draft.notes || [];
    panel.append(el('h3', '', `批注（${notes.filter(row => row.status === 'open').length} 待处理 / 共 ${notes.length}）`));
    const list = el('ul', 'notes-list');
    for (const note of notes) {
      const item = el('li', `note-${note.status}`);
      const baseline = note.base_draft_revision != null && note.base_content_sha256
        ? `基准 r${note.base_draft_revision} · SHA ${note.base_content_sha256}${note.base_artifact_id ? ' · 冻结版本 ' + note.base_artifact_id : ''}`
        : '基准未知（历史批注未记录所见版本）';
      item.append(el('span', 'note-anchor', `${note.scope_key == null ? '未归属历史 · ' : ''}${note.scene_id}${note.line_id ? ' / ' + note.line_id : ''}`),
        el('span', '', note.body),
        el('small', 'note-baseline', baseline),
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
    panel.append(list, el('p', 'hint', '新批注绑定已保存的所见稿次、内容摘要与场次／行身份，不进入剧本正文；解决批注不等于批准剧本。'));
    return panel;
  }

  function destroy() {
    clearTimeout(saveTimer); saveTimer = null; session = null; generation++;
    pageWindow?.removeEventListener('beforeunload', beforeUnload);
    recoveries.clear();
  }

  return {load, reload: load, destroy};
}
