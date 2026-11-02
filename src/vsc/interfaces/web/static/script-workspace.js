import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* 剧本工作区：可变工作副本 + 串行自动保存 + 批注 + 差异 + 提交人工确认。
   本模块只消费后端事实（draft / artifact 决定），不拥有批准权威。
   F01/F02：保存会话绑定 project+scope，串行保存队列，过期响应与切换后定时器不写当前会话；
   F03：readEditor 按稳定身份合并编辑字段，保留未编辑的引用与静默语义；
   冻结版本审阅读取完整正文和真实范围；分集导航分页并按项目重建。 */

export function createScriptWorkspace(container, ctx) {
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) setText(node,text); return node; };
  const notice = message => { if (message) ctx.onNotice(message); };
  const blank = () => ({format: 'vsc.screenplay/v1', body: '', adaptation_refs: [], scenes: []});
  let draft = null, scopeKey = '', scopeSelect = null, statusChip = null;
  let session = null, generation = 0, metadataGeneration = 0;
  let saveTimer = null, saving = false, lastError = null, editSeq = 0, savedSeq = 0, conflict = false;
  let conflictMessage = null;
  const recoveries = new Map(); // 仅当前工作区实例内存；不写本地存储或项目事实。
  const suggestionAttempts = new Map();
  const noteDrafts = new Map();
  let noteTarget = null, noteOffset = 0, suggestionOffset = 0;
  const recoveryKey = target => JSON.stringify([target.project, target.scopeKey]);
  const storage = typeof window !== 'undefined' ? window.sessionStorage : null;
  const stash = (key, value) => {try {if(value == null)storage?.removeItem(key);else storage?.setItem(key,JSON.stringify(value));}catch {}};
  const unstash = key => {try {return JSON.parse(storage?.getItem(key)||'null');}catch {return null;}};
  const draftUrl = target => `${target.project}/script-draft?scope_key=${encodeURIComponent(target.scopeKey)}&note_offset=${noteOffset}&suggestion_offset=${suggestionOffset}&limit=50`;

  const sameSession = target => session && target && target.generation === session.generation
    && target.project === session.project && target.project === ctx.baseUrl()
    && target.scopeKey === session.scopeKey && target.scopeKey === scopeKey;
  const stale = () => new Error('');
  const uniqueId = prefix => `${prefix}-${crypto.randomUUID()}`;

  function rememberLocal() {
    if (!session || !draft) return;
    const key = recoveryKey(session);
    if (editSeq <= savedSeq && !saving && !conflict) { recoveries.delete(key); stash('vsc-script:'+key,null); return; }
    const value = {generation: session.generation, content: readEditor(), draft_revision: draft.draft_revision,
      editSeq, savedSeq, inFlight: saving, conflict, conflictMessage, lastError};
    recoveries.set(key, value); stash('vsc-script:'+key,value);
  }

  function restoreLocal(target, fresh) {
    const cached = recoveries.get(recoveryKey(target)) || unstash('vsc-script:'+recoveryKey(target));
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
      stash('vsc-script:'+key,cached);
      return;
    }
    cached.draft_revision = result.draft_revision;
    cached.savedSeq = Math.max(cached.savedSeq, seq); cached.lastError = null;
    if (cached.editSeq <= cached.savedSeq && !cached.conflict) {recoveries.delete(key);stash('vsc-script:'+key,null);}
    else stash('vsc-script:'+key,cached);
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
  async function write(action, payload, confirmed = false, target = session, commandKey = null) {
    if (!sameSession(target)) throw stale();
    const value = requireSession();
    let result;
    try {
      result = await ctx.api(`${target.project}/${action}`, {method: 'POST', headers: headers(),
        body: JSON.stringify({payload, confirmed, expected_revision: value.revision, idempotency_key: commandKey || crypto.randomUUID()})});
    } catch (error) { if (!sameSession(target)) throw stale(); throw error; }
    if (!sameSession(target)) throw stale();
    ctx.setRevision(result.revision ?? value.revision);
    return result;
  }

  async function ensureScopeSelect(target) {
    if (scopeSelect && scopeSelect.dataset.projectId === target.project) {
      if(!Array.from(scopeSelect.options || scopeSelect.children).some(row=>row.value===target.scopeKey)){
        const option=el('option','',target.scopeLabel||msg("ui.current_episode"));option.value=target.scopeKey;scopeSelect.append(option);
      }
      scopeSelect.value=target.scopeKey;return;
    }
    const select = el('select', 'script-scope');
    select.dataset.projectId = target.project;
    bindAttribute(select,'aria-label',msg("ui.script_scope"));
    const all = el('option', '', msg("ui.whole_project_script")); all.value = ''; select.append(all);
    // Authority probe is bounded; the complete directory lives in the project
    // navigator instead of downloading every episode into this select.
    if(!target.scopeKey)await ctx.api(`${target.project}/workbench?section=children&limit=1`);
    if (target.scopeKey) {
      const option = el('option', '', msg("ui.current_episode_value0",{value0:target.scopeLabel || msg("ui.selected_episode")}));
      option.value = target.scopeKey; select.append(option);
    }
    if (!sameSession(target)) return;
    select.value = target.scopeKey;
    select.addEventListener('change', async () => {
      if (select !== scopeSelect || target.project !== ctx.baseUrl()) return;
      scopeKey = select.value; ctx.onScope?.(scopeKey); await load();
    });
    scopeSelect = select;
  }

  async function load(options = {}) {
    const loadRequest = ++generation;
    if (options.discardLocal === true) {
      if (session) {recoveries.delete(recoveryKey(session));stash('vsc-script:'+recoveryKey(session),null);}
    } else rememberLocal();
    const project = ctx.baseUrl();
    if (session && session.project !== project) { scopeKey = ''; scopeSelect = null; }
    if (Object.prototype.hasOwnProperty.call(options,'objectId')) {
      const object = options.objectId;
      scopeKey = '';
      if (object) {
        const relation = await ctx.api(`${project}/workbench?section=children&object_id=${encodeURIComponent(object)}&limit=1`);
        if (project !== ctx.baseUrl() || loadRequest !== generation) return;
        const objects = [...(relation.ancestors || []), relation.scope].filter(Boolean);
        const episode = objects.find(row=>row.kind==='episode');
        if (!episode) throw new Error('所选对象没有已登记的分集关系，请从项目目录选择有效的一集。');
        scopeKey = episode.id; options.scopeLabel = episode.title || episode.display_code;
        options.sceneId ||= objects.find(row=>row.kind==='scene')?.id;
      }
    }
    if (session?.scopeKey !== scopeKey) {noteOffset=0;suggestionOffset=0;noteTarget=null;}
    const target = {project, scopeKey, generation: loadRequest};
    target.scopeLabel=options.scopeLabel;
    session = target;
    clearTimeout(saveTimer); saveTimer = null; saving = false; lastError = null; conflict = false; conflictMessage = null; editSeq = 0; savedSeq = 0;
    draft = null;
    container.replaceChildren(el('p', 'hint', msg("ui.loading_script_working_copy")));
    try {
      await ensureScopeSelect(target);
      if (!sameSession(target)) return;
      const fresh = await ctx.api(draftUrl(target));
      if (!sameSession(target)) return;
      draft = fresh;
      restoreLocal(target, fresh);
      render();
      const anchor = options.lineId ? Array.from(container.querySelectorAll('.script-line')).find(row=>row.dataset.lineId===options.lineId) :
        options.sceneId ? Array.from(container.querySelectorAll('.script-scene')).find(row=>row.dataset.sceneId===options.sceneId) : null;
      anchor?.scrollIntoView?.({block:'center'});
      if (!conflict && editSeq > savedSeq) saveTimer = setTimeout(() => sameSession(target) && flushSave(), 900);
    } catch (error) { if (sameSession(target)) notice(error.message); }
  }

  function setStatus(text) { if (statusChip) setText(statusChip,text); }
  function scheduleSave() {
    if (!sameSession(session) || !draft) return;
    editSeq++;                                     // F02：编辑序号与保存进度分离
    rememberLocal();
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
      if (editSeq <= savedSeq) {recoveries.delete(recoveryKey(target));stash('vsc-script:'+recoveryKey(target),null);}
      updatePhase();
      const saved = container.querySelector('.script-saved-version');
      if (saved) setText(saved,msg("ui.working_copy_r_value0",{value0:draft.draft_revision}));
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
        if (kind === 'dialogue') {
          merged.speaker = row.querySelector('.line-speaker')?.value || '';
          if (content.structured_source) merged.speaker_label = draft.character_choices?.find(choice=>choice.id===merged.speaker)?.label || saved.speaker_label || '';
        }
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
    banner.replaceChildren(el('p', '', msg("ui.value0_local_edits_remain_on_this_page_loading_the",{value0:message})));
    const loadLatest = el('button', '', msg("ui.load_latest_and_replace_local_copy"));
    const target = session;
    loadLatest.addEventListener('click', async () => {
      if (!sameSession(target) || !confirm('确定放弃本地未保存修改、加载服务器最新内容？')) return;
      await load({discardLocal: true});
    });
    const keep = el('button', '', msg("ui.keep_local_copy_for_now"));
    keep.addEventListener('click', () => { banner.hidden = true; notice(msg("ui.local_edits_preserved_autosave_paused_until_conflict_resolution")); });
    banner.append(loadLatest, keep);
  }

  const phaseText = {empty: '未建立', editing: '编辑中', pending: '待人工确认', approved: '已批准基线', rejected: '已退回修改', revoked: '批准已撤销'};
  function updatePhase() {
    const chip = container.querySelector('.script-phase');
    if (chip) setText(chip,phaseText[editSeq > savedSeq ? 'editing' : draft.phase] || draft.phase);
  }
  function render() {
    container.replaceChildren();
    const header = el('header', 'script-header');
    if(ctx.onBack){const back=el('button','',msg("ui.back_to_contents"));back.type='button';back.addEventListener('click',()=>ctx.onBack());header.append(back);}
    header.append(el('h2', '', msg("nav.script")));
    statusChip = el('span', 'badge', '—');
    const phase = el('span', `badge script-phase ${draft.phase === 'pending' ? 'danger' : ''}`, phaseText[draft.phase] || draft.phase);
    const saved = el('span', 'hint script-saved-version', draft.exists ? joinMessages(["r",draft.draft_revision,""]) : msg("ui.no_working_copy"));
    saved.title=`更新 ${String(draft.updated_at||'').slice(0,19)} · ${draft.updated_by||''}`;
    header.append(statusChip, phase, saved, scopeSelect || el('span'));
    container.append(header);
    const conflictBox = el('div', 'script-conflict'); conflictBox.hidden = true; container.append(conflictBox);
    if (draft.submitted) container.append(renderPending());
    const panels=el('div','script-panels'),stage=el('main','script-main'),inspector=el('aside','script-inspector');
    bindAttribute(stage,'aria-label',msg("ui.script_body"));bindAttribute(inspector,'aria-label',msg("ui.changes_and_comments"));
    const mobile=el('nav','script-panel-nav');bindAttribute(mobile,'aria-label',msg("ui.script_panel"));
    for(const [key,label]of [['work',msg("ui.work")],['modify',msg("ui.changes_and_comments")]]){const b=el('button','',label);b.type='button';b.addEventListener('click',()=>{container.dataset.panel=key;for(const control of mobile.children)control.setAttribute('aria-pressed',String(control===b));(key==='work'?stage:inspector).focus?.();});b.setAttribute('aria-pressed',String((container.dataset.panel||'work')===key));mobile.append(b);}
    stage.tabIndex=-1;inspector.tabIndex=-1;container.append(mobile);
    stage.append(draft.exists ? renderEditor() : renderBootstrap());
    inspector.append(renderNoteComposer());
    for(const selector of ['.script-edit-tools','.script-source-evidence']){const tools=stage.querySelector(selector);if(tools)inspector.append(tools);}
    inspector.append(renderSuggestions(),renderNotes());
    panels.append(stage,inspector);container.append(panels);
    if (draft.submitted?.state === 'pending') renderImpact();
    updatePhase();
    if (conflict) renderConflict(conflictMessage || '本地内容待核对，自动保存暂停');
    setStatus(conflict ? '本地修改已保留，冲突待核对' : editSeq > savedSeq ? '待保存' : '—');
  }

  async function refreshMeta() {
    const target = session;
    const request = ++metadataGeneration;
    try {
      const fresh = await ctx.api(draftUrl(target));
      if (!sameSession(target) || request !== metadataGeneration) return;
      draft.notes = fresh.notes; draft.phase = fresh.phase; draft.submitted = fresh.submitted; draft.base = fresh.base;
      draft.suggestions = fresh.suggestions;
      draft.suggestion_runs = fresh.suggestion_runs;
      draft.notes_page=fresh.notes_page;draft.suggestions_page=fresh.suggestions_page;
      // 批注决策不拥有正文或 draft_revision；保留本地编辑与保存队列的原始基准。
      for (const [selector, panel] of [['.script-notes', renderNotes()], ['.script-suggestions', renderSuggestions()]]) {
        const previous = container.querySelector(selector);
        if (previous) previous.replaceChildren(...Array.from(panel.children));
      }
      const previous = container.querySelector('.script-pending');
      const stamp = draft.submitted ? `${draft.submitted.id}:${draft.submitted.state}` : '';
      if (draft.submitted && previous?.dataset.submissionStamp !== stamp) {
        previous?.remove();
        container.insertBefore(renderPending(), container.querySelector('.script-panel-nav'));
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
    box.append(el('h3', '', pending ? msg("ui.frozen_version_awaiting_human_confirmation") : msg("ui.frozen_version_value0",{value0:phaseText[submitted.state] || submitted.state})), el('p', 'hint',
      msg("ui.frozen_version_value0_v_value1_sha_value2_you_are",{value0:submitted.artifact_key || '',value1:submitted.version,value2:String(submitted.sha256 || '').slice(0, 12),value3:pending ? msg("ui.decision_applies_only_to_this_fixed_version") : ''})));
    if (submitted.matches_draft === false) box.append(el('p', 'hint', msg("ui.the_server_confirmed_that_the_working_copy_differs_from")));
    const frozen = el('div', 'frozen-body hint');
    setText(frozen,msg("ui.loading_the_frozen_submitted_body"));
    let reviewed = false;
    const reason = el('input', 'script-decision-reason'); bindAttribute(reason,"placeholder",msg("ui.approval_or_return_explanation_required"));
    const approve = el('button', 'script-approve-button', msg("ui.approve_this_version")); approve.disabled = true;
    const reject = el('button', 'script-reject-button', msg("novel-parser.reject")); reject.disabled = true;
    ctx.api(`${target.project}/artifacts/${encodeURIComponent(submitted.id)}`).then(artifact => {
      if (!sameSession(target) || draft.submitted?.id !== submitted.id) return;
      const content = typeof artifact.content === 'string' ? artifact.content : JSON.stringify(artifact.content ?? '');
      let parsed = null;
      try { parsed = JSON.parse(content); } catch {}
      if (!parsed || !Array.isArray(parsed.scenes) || artifact.id !== submitted.id || !submitted.sha256 || artifact.sha256 !== submitted.sha256) {
        setText(frozen,msg("ui.the_frozen_body_or_checksum_does_not_match_its")); return;
      }
      const scenes = parsed?.scenes || [];
      frozen.replaceChildren(el('p', '', msg("ui.scope_value0_scenes_value1",{value0:artifact.project_wide ? msg("ui.whole_project") : (artifact.object_ids || []).join('、'),value1:scenes.length})),
        el('p', 'frozen-screenplay-body', parsed.body || ''), el('p', '', msg("ui.adaptation_source_value0",{value0:JSON.stringify(parsed.adaptation_refs || [])})));
      for (const scene of scenes) {
        const block = el('div', 'frozen-scene');
        block.append(el('strong', '', msg("ui.value0_about_value1_ms",{value0:scene.id,value1:scene.estimated_duration_ms || 0})));
        for (const row of scene.actions || []) block.append(el('div', '', msg("ui.action_value0_narrative_source_value1",{value0:row.text,value1:(row.narrative_refs || []).join('、')})));
        for (const row of scene.dialogue || []) block.append(el('div', '', msg("ui.value0_value1_narrative_source_value2",{value0:row.speaker || '',value1:row.text,value2:(row.narrative_refs || []).join('、')})));
        for (const row of scene.silence || []) block.append(el('div', '', msg("ui.silence_value0_value1_ms_value2_narrative_source_value3",{value0:row.text,value1:row.duration_ms || '?',value2:row.purpose || '',value3:(row.narrative_refs || []).join('、')})));
        frozen.append(block);
      }
      frozen.append(el('p', '', msg("ui.fixed_prerequisite_version_value0",{value0:(artifact.dependency_ids || artifact.dependencies?.map(row => row.id) || []).join('、')})));
      reviewed = true; approve.disabled = !pending; reject.disabled = !pending;
    }).catch(error => { if (sameSession(target)) setText(frozen,msg("ui.frozen_text_could_not_be_loaded_value0",{value0:error.message})); });
    approve.addEventListener('click', async () => {
      if (!reviewed || !pending || !sameSession(target)) return;
      if (!reason.value.trim()) return notice(msg("ui.enter_the_decision_explanation"));
      if (!confirm('确认批准当前提交的剧本版本？下游设计与制作将以该固定版本为基线。')) return;
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'approve', reason: reason.value}, true, target);
        notice(msg("ui.frozen_script_version_approved")); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    reject.addEventListener('click', async () => {
      if (!reviewed || !pending || !sameSession(target)) return;
      if (!reason.value.trim()) return notice(msg("ui.enter_the_reason_for_returning_it"));
      try {
        await write('artifact-decisions', {artifact_id: submitted.id, outcome: 'reject', reason: reason.value}, true, target);
        notice(msg("ui.frozen_version_returned_for_revision")); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    box.append(frozen);
    if (pending) box.append(reason, approve, reject);
    return box;
  }

  function renderBootstrap() {
    const box = el('section', 'script-bootstrap');
    box.append(el('p', 'empty', msg("ui.this_scope_has_no_script_working_copy_start_with")));
    const blankButton = el('button', '', msg("ui.start_a_blank_script"));
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
      const structured = draft.content?.structured_source;
      const speaker = el(structured ? 'select' : 'input', 'line-speaker');
      if (structured) {
        bindAttribute(speaker,'aria-label',msg("ui.speaker"));
        const choices = [...(draft.character_choices || [])];
        if (!choices.some(choice=>choice.id===row.speaker)) choices.unshift({id:row.speaker || '',label:row.speaker_label || '请选择人物'});
        for (const choice of choices) {const option=el('option','',choice.label);option.value=choice.id;speaker.append(option);}
      } else bindAttribute(speaker,"placeholder",msg("ui.character"));
      speaker.value = row.speaker || '';
      speaker.addEventListener(structured ? 'change' : 'input', scheduleSave);
      item.append(speaker);
      if(structured)item.append(choicePicker('character',choice=>{if(!draft.character_choices.some(row=>row.id===choice.id))draft.character_choices.push({id:choice.id,label:choice.title||choice.display_code});const option=el('option','',choice.title||choice.display_code);option.value=choice.id;speaker.append(option);speaker.value=choice.id;scheduleSave();}));
    }
    const text = el('textarea', 'line-text'); text.rows=2;text.value = row.text || '';
    bindAttribute(text,'aria-label',kind==='dialogue'?msg("ui.dialogue"):kind==='silence'?msg("ui.silence_description"):msg("ui.action_description"));
    bindAttribute(text,"placeholder",kind === 'dialogue' ? msg("ui.dialogue") : kind === 'action' ? msg("ui.action_description") : msg("ui.silence_description"));
    text.addEventListener('input', scheduleSave);
    const note = el('button', 'line-note', msg("ui.annotation"));
    note.addEventListener('click', async () => {
      noteTarget={scene_id:sceneId,line_id:item.dataset.lineId,kind,excerpt:text.value};
      const previous=container.querySelector('.script-note-composer');previous.parentNode.insertBefore(renderNoteComposer(),previous);previous.remove();
      container.dataset.panel='modify';container.querySelector('.script-note-composer textarea')?.focus();
    });
    const remove = el('button', 'line-remove', msg("script-studio.delete_5"));
    remove.addEventListener('click', () => { item.remove(); scheduleSave(); });
    item.append(text, note, remove);
    const refs = el('input', 'line-refs'); refs.value = (row.narrative_refs || []).join(', ');
    bindAttribute(refs,"placeholder",msg("ui.narrative_source_ids_comma_separated")); bindAttribute(refs,'aria-label',msg("ui.narrative_source_id"));
    refs.addEventListener('input', scheduleSave);
    const choices = draft.narrative_choices?.[sceneId] || [];
    if (choices.length) {
      const mapped = el('div', 'line-narrative-choices');
      mapped.append(el('span', 'hint', msg("ui.adaptation_unit")));
      for (const choice of choices) {
        const label = el('label'); const check = el('input'); check.type = 'checkbox';
        check.checked = (row.narrative_refs || []).includes(choice.id); check.dataset.refId = choice.id;
        check.addEventListener('change', () => {
          const selected = new Set(refs.value.split(',').map(value => value.trim()).filter(Boolean));
          check.checked ? selected.add(choice.id) : selected.delete(choice.id);
          refs.value = Array.from(selected).join(', '); scheduleSave();
        });
        label.append(check, el('span', '', choice.label)); mapped.append(label);
      }
      const evidence = el('details'); evidence.append(el('summary', '', msg("ui.source_number")), refs);
      item.append(mapped, evidence);
    } else {const evidence=el('details','line-evidence');evidence.append(el('summary','',msg("ui.source_verification")),refs);item.append(evidence);}
    if (kind === 'silence') {
      const duration = el('input', 'line-duration'); duration.type = 'number'; duration.min = '1';
      duration.value = row.duration_ms ?? ''; bindAttribute(duration,"placeholder",msg("ui.silence_duration_ms")); bindAttribute(duration,'aria-label',msg("ui.silence_duration_milliseconds"));
      const purpose = el('input', 'line-purpose'); purpose.value = row.purpose || ''; bindAttribute(purpose,"placeholder",msg("ui.purpose_of_silence")); bindAttribute(purpose,'aria-label',msg("ui.purpose_of_silence"));
      duration.addEventListener('input', scheduleSave); purpose.addEventListener('input', scheduleSave);
      item.append(duration, purpose);
    }
    return item;
  }

  function choicePicker(kind,onChoose){
    const details=el('details','script-choice-picker');details.append(el('summary','',kind==='character'?msg("ui.find_another_character"):msg("ui.find_another_scene")));
    const form=el('form'),input=el('input'),submit=el('button','',msg("ui.find")),results=el('div');input.type='search';bindAttribute(input,'aria-label',kind==='character'?msg("ui.character_name"):msg("ui.scene_name"));bindAttribute(input,"placeholder",msg("ui.enter_a_name"));submit.type='submit';form.append(input,submit);details.append(form,results);let request=0;
    const read=async(offset=0)=>{const target=session,ticket=++request;setText(results,msg("ui.loading"));try{const data=await ctx.api(`${target.project}/script-draft/choices?`+new URLSearchParams({scope_key:target.scopeKey,kind,query:input.value,offset:String(offset)}));if(!sameSession(target)||ticket!==request)return;results.replaceChildren();for(const row of data.items||[]){const b=el('button','',row.title||row.display_code);b.type='button';b.addEventListener('click',()=>{if(!sameSession(target))return;onChoose(row);details.open=false;});results.append(b);}if(!data.items?.length)results.append(el('p','hint',msg("ui.no_registered_content_matches")));if(offset>0){const prev=el('button','',msg("common.previous_page"));prev.type='button';prev.addEventListener('click',()=>read(Math.max(0,offset-50)));results.append(prev);}if(data.next_offset!=null){const next=el('button','',msg("common.next_page"));next.type='button';next.addEventListener('click',()=>read(data.next_offset));results.append(next);}}catch(error){if(sameSession(target)&&ticket===request)setText(results,error.message);}};
    form.addEventListener('submit',event=>{event.preventDefault();return read();});details.addEventListener('toggle',()=>{if(details.open&&!results.children.length&&!results.textContent)read();});return details;
  }

  function sceneCard(scene) {
    const card = el('section', 'script-scene');
    card.dataset.sceneId = scene.id || uniqueId('SC');
    const header = el('header', 'scene-header');
    const id = el('input', 'scene-id'); id.value = card.dataset.sceneId; id.readOnly = true;
    bindAttribute(id,"title",msg("ui.fixed_scene_identity_moving_a_scene_does_not_change")); bindAttribute(id,'aria-label',msg("ui.fixed_scene_id"));
    const duration = el('input', 'scene-duration'); duration.type = 'number'; duration.value = scene.estimated_duration_ms ?? 0; bindAttribute(duration,"title",msg("ui.estimated_duration_milliseconds"));
    duration.addEventListener('input', scheduleSave);
    const up = el('button', '', msg("agent.overseas_remake_move_up"));
    up.addEventListener('click', () => { if (card.previousElementSibling?.classList.contains('script-scene')) { card.parentNode.insertBefore(card, card.previousElementSibling); scheduleSave(); } });
    const down = el('button', '', msg("agent.overseas_remake_move_down"));
    down.addEventListener('click', () => { if (card.nextElementSibling?.classList.contains('script-scene')) { card.parentNode.insertBefore(card.nextElementSibling, card); scheduleSave(); } });
    const drop = el('button', '', msg("ui.delete_scene"));
    drop.addEventListener('click', () => { if (confirm(`删除场次 ${card.dataset.sceneId}？`)) { card.remove(); scheduleSave(); } });
    if (draft.content?.structured_source) {
      id.type = 'hidden';
      header.append(el('strong', '', draft.scene_choices?.find(choice=>choice.id===scene.id)?.label || scene.source_label || msg("ui.import_scenes")));
    }
    if(!draft.content?.structured_source)header.append(el('strong','',draft.scene_choices?.find(choice=>choice.id===scene.id)?.label||scene.source_label||msg("ui.scene")));
    const tools=el('details','scene-tools');tools.append(el('summary','',msg("ui.scene_actions")),id,el('span','hint',msg("ui.duration_ms")),duration,up,down,drop);header.append(tools);
    card.append(header);
    for (const [className, label, field, kind] of [['scene-actions', msg("ui.action"), 'actions', 'action'],
                                                   ['scene-dialogue', msg("agent.overseas_remake_dialogue"), 'dialogue', 'dialogue'],
                                                   ['scene-silence', msg("ui.silence"), 'silence', 'silence']]) {
      const group = el('div', className);
      group.append(el('h4', '', label));
      const rows = el('div', 'scene-lines');
      for (const row of scene[field] || []) rows.append(lineRow(card.dataset.sceneId, kind, row));
      const add = el('button', 'line-add', msg("ui.add_value0",{value0:label}));
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
    const addScene = el('button', '', msg("ui.add_scene"));
    const sceneChoice = el('select', 'script-scene-choice'); bindAttribute(sceneChoice,'aria-label',msg("ui.choose_an_existing_scene"));
    for (const choice of draft.scene_choices || []) {
      const option = el('option', '', choice.label); option.value = choice.id; sceneChoice.append(option);
    }
    addScene.addEventListener('click', () => {
      try {
        draft.content = readEditor();
        const selected = sceneChoice.value || draft.scene_choices?.[0]?.id;
        if (selected && draft.content.scenes.some(scene => scene.id === selected)) return notice(msg("ui.this_scene_is_already_in_the_current_draft"));
        draft.content.scenes.push({id: selected || uniqueId('SC'), estimated_duration_ms: 0, actions: [], dialogue: [], silence: []});
        render(); scheduleSave();
      } catch (error) { notice(error.message); }
    });
    const compare = el('button', '', msg("ui.compare_with_approved_baseline"));
    compare.addEventListener('click', async () => {
      const target = session;
      const saved = await waitForSave();
      if (!saved) return notice(msg("ui.unsaved_changes_exist_resolve_saving_before_comparing"));
      try {
        const result = await ctx.api(`${target.project}/script-draft/compare?scope_key=${encodeURIComponent(target.scopeKey)}`);
        if (sameSession(target)) renderCompare(result);
      } catch (error) { if (sameSession(target)) notice(error.message); }
    });
    const submit = el('button', 'script-submit-button', msg("ui.submit_for_human_confirmation"));
    submit.addEventListener('click', async () => {
      const target = session;
      const saved = await waitForSave();
      if (!saved) return notice(msg("ui.saving_is_incomplete_failed_or_conflicted_submission_is_unavailable"));  // F02/F04：提交屏障
      if (!confirm('提交后当前内容冻结为待确认版本，等待人工批准；批准前不能进入正式设计与资产生产。')) return;
      try {
        const context = draft.submission_context;
        if (!context) return notice(msg("ui.submission_prerequisite_facts_are_missing_for_this_scope_reload"));
        if (context.missing_dependency_types?.length) return notice(msg("ui.approved_prerequisite_version_missing_value0",{value0:context.missing_dependency_types.join('、')}));
        const result = await write('script-submit', {scope_key: target.scopeKey, base_draft_revision: draft.draft_revision,
          artifact_type: context.artifact_type, dependency_ids: [...(context.dependency_ids || [])]}, false, target);
        notice(msg("ui.submitted_for_confirmation_version_value0",{value0:result.artifact.version})); await refreshMeta();
      } catch (error) { notice(error.message); }
    });
    if (draft.scene_choices?.length) toolbar.append(sceneChoice);
    toolbar.append(choicePicker('scene',choice=>{if(!draft.scene_choices)draft.scene_choices=[];if(!draft.scene_choices.some(row=>row.id===choice.id))draft.scene_choices.push({id:choice.id,label:choice.title||choice.display_code});const option=el('option','',choice.title||choice.display_code);option.value=choice.id;sceneChoice.append(option);sceneChoice.value=choice.id;}));
    toolbar.append(addScene, compare, submit, el('span', 'hint', msg("ui.edits_save_automatically_to_the_working_copy_updating_only")));
    const tools=el('details','script-edit-tools');tools.append(el('summary','',msg("ui.scene_and_version_actions")),toolbar);wrap.append(tools);
    const board = el('div', 'script-board');
    const content = draft.content || blank();
    const fields = el('section', 'script-document-fields');
    const bodyLabel = el('label', '', msg("ui.script_body"));
    const body = el('textarea', 'script-body'); body.value = content.body || ''; body.rows = 6;
    if (content.structured_source) {
      body.readOnly = true;
      bindAttribute(body,'aria-label',msg("ui.continuous_text_generated_from_scenes_and_dialogue"));
      bodyLabel.append(el('p','hint',msg("ui.continuous_text_is_generated_from_the_scenes_and_dialogue")));
    } else body.addEventListener('input', scheduleSave);
    bodyLabel.append(body); fields.append(bodyLabel);
    fields.append(el('h4', '', msg("ui.fixed_adaptation_source")));
    const refs = el('div', 'script-adaptation-refs');
    function addRef(ref = {}) {
      const row = el('div', 'script-adaptation-ref'); row.dataset.refId = ref.id || '';
      const id = el('input', 'adaptation-id'); id.value = ref.id || ''; bindAttribute(id,"placeholder",msg("ui.source_version_id")); bindAttribute(id,'aria-label',msg("ui.adaptation_source_version_id"));
      const sha = el('input', 'adaptation-sha'); sha.value = ref.sha256 || ''; bindAttribute(sha,"placeholder",msg("ui.source_sha_256")); bindAttribute(sha,'aria-label',msg("ui.adaptation_source_sha_256"));
      const remove = el('button', '', msg("ui.remove_source")); remove.addEventListener('click', () => { row.remove(); scheduleSave(); });
      const pin = draft.submission_context?.dependencies?.find(item => item.id === ref.id);
      row.append(el('span', '', pin ? joinMessages(["",pin.artifact_key || msg("ui.approved_adaptation")," · v",pin.version,""]) : msg("ui.registered_sources")));
      const advanced = el('details'); advanced.append(el('summary', '', msg("ui.version_evidence")), id, sha);
      id.addEventListener('input', scheduleSave); sha.addEventListener('input', scheduleSave); row.append(advanced, remove); refs.append(row);
    }
    for (const ref of content.adaptation_refs || []) addRef(ref);
    const addRefButton = el('button', 'script-add-adaptation', msg("ui.add_adaptation_source"));
    addRefButton.addEventListener('click', () => {
      const pin = draft.submission_context?.dependencies?.find(item => item.artifact_type === 'vsc.adaptation_plan');
      if (pin && Array.from(refs.querySelectorAll('.adaptation-id')).some(input => input.value === pin.id)) return notice(msg("ui.this_approved_version_is_already_included"));
      addRef(pin || {}); scheduleSave();
    });
    const dependencies = draft.submission_context;
    fields.append(refs, addRefButton, el('p', 'script-dependencies hint', dependencies
      ? msg("ui.fixed_submission_prerequisites_value0_value1",{value0:(dependencies.dependencies || []).map(row => `${row.artifact_key || row.artifact_type || row.id} v${row.version} · ${row.sha256}`).join('；') || msg("ui.current_profile_has_no_prerequisites"),value1:dependencies.missing_dependency_types?.length ? msg("ui.approved_versions_missing_value0",{value0:dependencies.missing_dependency_types.join('、')}) : ''})
      : msg("ui.waiting_for_submission_prerequisite_facts_for_this_scope")));
    const evidence=el('details','script-source-evidence');evidence.append(el('summary','',msg("ui.source_structure_and_submission_checks")),fields);wrap.append(evidence);
    for (const scene of content.scenes || []) board.append(sceneCard(scene));
    if (!(content.scenes || []).length) board.append(el('p', 'empty', msg("ui.no_scenes_yet_select_add_scene_to_start_writing")));
    wrap.append(board);
    return wrap;
  }

  function renderCompare(result) {
    let panel = container.querySelector('.script-compare');
    if (!panel) { panel = el('section', 'script-compare'); container.querySelector('.script-main').prepend(panel); }
    panel.replaceChildren(el('h3', '', msg("ui.differences_from_approved_baseline")));
    const changes = result.changes || {};
    if (!changes.changed) { panel.append(el('p', 'hint', result.base ? msg("ui.matches_the_baseline_no_structural_differences") : msg("ui.no_approved_baseline_exists_for_this_scope_submission_and"))); return; }
    const scenes = changes.scenes || {};
    const summary = [];
    if (scenes.added?.length) summary.push(`新增场次 ${scenes.added.join('、')}`);
    if (scenes.removed?.length) summary.push(`删除场次 ${scenes.removed.join('、')}`);
    if (scenes.moved?.length) summary.push(`移动场次 ${scenes.moved.join('、')}`);
    if (summary.length) panel.append(el('p', '', summary.join('；')));
    const list = el('ul', 'compare-list');
    for (const change of changes.lines || []) {
      const item = el('li', '', joinMessages(["",change.scene_id || ''," ",change.line_id || ''," ",change.field || '',"（",change.change,"）"]));
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
    panel.append(el('h3', '', msg("ui.revision_suggestions_value0_pending_value1_total",{value0:pending.length,value1:suggestions.length})));
    const goal = el('input', 'script-ai-goal'); bindAttribute(goal,"placeholder",msg("ui.describe_the_desired_improvement_such_as_more_natural_dialogue"));
    goal.maxLength = 2000;
    const generate = el('button', 'script-ai-generate', msg("ui.generate_ai_suggestions"));
    generate.addEventListener('click', async () => {
      const target = session, objective = goal.value.trim();
      if (!objective) return notice(msg("ui.enter_the_goal_for_this_suggestion_round_first"));
      generate.disabled = true;
      try {
        if (!await waitForSave() || !sameSession(target)) return;
        const seq = editSeq;
        const fresh = await ctx.api(`${target.project}/script-draft?scope_key=${encodeURIComponent(target.scopeKey)}`);
        if (!sameSession(target)) return;
        if (editSeq !== seq || saving || conflict || fresh.draft_revision !== draft.draft_revision) {
          return notice(msg("ui.text_changed_while_preparing_suggestions_save_and_generate_again"));
        }
        const fingerprint = JSON.stringify([fresh.draft_revision, fresh.content_sha256, objective]);
        const key = recoveryKey(target), previous = suggestionAttempts.get(key);
        const attempt = previous?.fingerprint === fingerprint ? previous : {fingerprint,commandKey:crypto.randomUUID(),newAttempt:previous?.requestNew===true};
        suggestionAttempts.set(key,attempt);
        const result = await write('script-draft/generate-suggestions', {scope_key: target.scopeKey,
          base_draft_revision: fresh.draft_revision, base_content_sha256: fresh.content_sha256, goal: objective,
          new_attempt:attempt.newAttempt===true}, false, target, attempt.commandKey);
        if (!sameSession(target)) return;
        notice(result.status === 'completed' ? msg("ui.suggestions_generated_review_and_accept_each_change") :
          result.status === 'stale' ? msg("ui.script_changed_during_generation_the_result_is_isolated_generate") :
          msg("ui.generation_did_not_complete_call_record_preserved_no_automatic"));
        await refreshMeta();
      } catch (error) { if (sameSession(target)) notice(error.message); }
      finally { if (sameSession(target)) generate.disabled = false; }
    });
    const newRound = el('button', '', msg("ui.start_another_suggestion_round"));
    newRound.addEventListener('click', () => {
      if (!confirm('新增一轮会使用新的宿主调用额度；旧的未知调用仍不会重试。继续？')) return;
      suggestionAttempts.set(recoveryKey(session),{requestNew:true}); notice(msg("ui.new_round_selected_enter_a_goal_then_select_generate"));
    });
    panel.append(goal, generate, newRound, el('p', 'hint', msg("ui.generate_local_suggestions_through_your_grok_build_sign_in")));
    for (const run of draft.suggestion_runs || []) {
      const attempt = el('div', 'hint', msg("ui.value0_based_on_r_value1_value2",{value0:run.goal,value1:run.base_draft_revision,value2:run.status}));
      if (run.status === 'running') {
        attempt.append(el('span', '', run.result_available ? msg("ui.host_result_exists_and_registration_can_be_recovered") : msg("ui.call_status_is_unconfirmed_no_automatic_resubmission")));
        if (run.result_available) {
          const resume = el('button', '', msg("ui.recover_existing_suggestion_result")), target=session;
          resume.addEventListener('click', async()=>{try{await write(`script-suggestion-runs/${run.id}/resume`,{},false,target);await refreshMeta();}catch(error){if(sameSession(target))notice(error.message);}});
          attempt.append(resume);
        }
      }
      panel.append(attempt);
    }
    const list = el('ul', 'notes-list');
    for (const row of suggestions) {
      const item = el('li', `note-${row.status}`);
      const label = `${row.scene_id}${row.line_id ? ' / ' + row.line_id : ''} · ${row.kind}.${row.field}`;
      item.append(el('span', 'note-anchor', label), el('s', '', String(row.before_value ?? '')),
        el('b', '', String(row.after_value)), el('small', '', joinMessages(["",row.origin," · r",row.base_draft_revision," · ",row.reason,""])));
      const compare=el('button','',msg("ui.compare_this_change_in_the_work_area"));compare.addEventListener('click',()=>{
        let panel=container.querySelector('.script-line-comparison');if(!panel){panel=el('section','script-line-comparison');container.querySelector('.script-main').prepend(panel);}
        panel.replaceChildren(el('h3','',msg("ui.changes_in_this_round")),el('p','',msg("script-studio.text_082")),el('del','',String(row.before_value??'')),el('p','',msg("ui.suggestion")),el('ins','',String(row.after_value)),el('p','hint',row.reason));
        const back=el('button','',msg("ui.return_to_original_position"));back.addEventListener('click',()=>{panel.remove();Array.from(container.querySelectorAll('.script-line')).find(node=>node.dataset.lineId===row.line_id)?.querySelector('.line-text')?.focus();});panel.append(back);container.dataset.panel='work';panel.scrollIntoView?.({block:'start'});
      });item.append(compare);
      if (row.status === 'pending') {
        const accept = el('button', '', msg("ui.accept_this_change"));
        accept.addEventListener('click', async () => {
          const target = session, seq = editSeq;
          if (editSeq > savedSeq || saving) return notice(msg("ui.unsaved_edits_exist_save_successfully_before_accepting_suggestions"));
          const reason = '在原处比较后接受这一处建议';
          try {
            await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
              outcome: 'accept', reason}, false, target);
            notice(msg("ui.suggestions_applied_to_the_working_copy_editor_refreshed_to"));
            await refreshChangedDraft(target, seq);
          } catch (error) { notice(error.message); }
        });
        const reject = el('button', '', msg("ui.reject"));
        reject.addEventListener('click', async () => {
          const reason = '保留原文，拒绝这一处建议';
          try { await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
            outcome: 'reject', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        item.append(accept, reject);
      } else if (row.status === 'accepted') {
        const undo = el('button', '', msg("ui.undo_acceptance"));
        undo.addEventListener('click', async () => {
          const target = session, seq = editSeq;
          if (editSeq > savedSeq || saving) return notice(msg("ui.unsaved_edits_exist_save_successfully_before_undoing"));
          const reason = '撤销本处接受，恢复原文';
          try {
            await write('script-suggestion-decisions', {scope_key: scopeKey, suggestion_id: row.id,
              outcome: 'undo_accept', reason}, false, target);
            notice(msg("ui.acceptance_undone_original_values_restored"));
            await refreshChangedDraft(target, seq);
          } catch (error) { notice(error.message); }
        });
        item.append(undo);
      }
      list.append(item);
    }
    if (!suggestions.length) list.append(el('li', 'hint', msg("ui.no_suggestions_yet_enter_a_goal_generate_suggestions_then")));
    panel.append(list);
    panel.append(pagination('suggestions',draft.suggestions_page));
    return panel;
  }

  async function renderImpact() {
    const target = session;
    let panel = container.querySelector('.script-impact');
    if (!panel) { panel = el('section', 'script-impact'); const before=container.querySelector('.script-suggestions');before.parentNode.insertBefore(panel,before); }
    panel.replaceChildren(el('h3', '', msg("ui.revision_impact_relative_to_approved_baseline")), el('p', 'hint', msg("ui.loading_extra_218")));
    try {
      const impact = await ctx.api(`${target.project}/script-draft/impact?scope_key=${encodeURIComponent(target.scopeKey)}`);
      if (!sameSession(target)) return;
      panel.replaceChildren(el('h3', '', msg("ui.revision_impact_relative_to_approved_baseline")));
      if (!impact.changed_lines.length && !impact.shots.length && !impact.cues.length) {
        panel.append(el('p', 'hint', impact.baseline_artifact_id ? msg("ui.no_line_level_changes_affecting_downstream_work_were_found") : msg("ui.this_scope_has_no_approved_baseline_for_impact_comparison")));
        return;
      }
      const lines = el('ul', 'compare-list');
      for (const change of impact.changed_lines) {
        const item = el('li', '', joinMessages(["",change.scene_id || ''," ",change.line_id || ''," ",change.field || '',"（",change.change,"）"]));
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
      panel.append(el('p', 'hint', msg("ui.the_impact_list_comes_from_actual_coverage_sound_cue")));
    } catch (error) { if (sameSession(target)) panel.append(el('p', 'hint', msg("ui.impact_could_not_be_loaded_value0",{value0:error.message}))); }
  }

  async function refreshChangedDraft(target, seq) {
    const fresh = await ctx.api(draftUrl(target));
    if (!sameSession(target)) return;
    if (editSeq !== seq || saving) {
      conflict = true; clearTimeout(saveTimer); saveTimer = null;
      renderConflict('建议决策期间出现本地编辑，服务器已更新；请保留本地内容并核对最新版本');
      return;
    }
    draft = fresh; editSeq = 0; savedSeq = 0; render();
  }

  function pagination(kind,page) {
    const bar=el('nav','script-pagination');bindAttribute(bar,'aria-label',kind==='notes'?msg("ui.annotation_pagination"):msg("ui.suggestion_pagination"));
    if(!page)return bar;
    for(const [label,offset]of [[msg("common.previous_page"),page.offset>0?Math.max(0,page.offset-50):null],[msg("common.next_page"),page.next_offset]]){
      const b=el('button','',label);b.disabled=offset==null;b.addEventListener('click',async()=>{if(kind==='notes')noteOffset=offset;else suggestionOffset=offset;await refreshMeta();});bar.append(b);
    }
    bar.append(el('span','hint',msg("ui.starting_at_item_value0_up_to_50_per_page",{value0:page.offset+1})));return bar;
  }

  function renderNoteComposer() {
    const form=el('form','script-note-composer');form.append(el('h3','',msg("ui.edit_this_part")));
    const key=recoveryKey(session),stored=noteDrafts.get(key)||unstash('vsc-script-note:'+key);
    if(!noteTarget&&stored?.target)noteTarget=stored.target;
    if(!noteTarget){form.append(el('p','hint',msg("ui.select_annotation_beside_a_line_and_describe_what_to")));return form;}
    const anchor={...noteTarget},target=session;
    form.append(el('p','script-note-anchor',msg("ui.selected_value0_value1",{value0:anchor.kind==='dialogue'?msg("agent.overseas_remake_dialogue"):anchor.kind==='silence'?msg("ui.silence"):msg("ui.action"),value1:anchor.excerpt})));
    const input=el('textarea','script-note-body');input.rows=4;input.maxLength=4000;input.required=true;bindAttribute(input,'aria-label',msg("ui.revision_comment_for_this_line"));
    bindAttribute(input,"placeholder",msg("ui.for_example_shorten_this_line_while_retaining_its_action"));input.value=stored?.target?.line_id===anchor.line_id?stored.body:'';
    const remember=()=>{const value={target:anchor,body:input.value};noteDrafts.set(key,value);stash('vsc-script-note:'+key,value);};input.addEventListener('input',remember);
    const save=el('button','',msg("ui.save_original_comment")),process=el('button','',msg("ui.save_and_propose_a_local_revision")),status=el('p','hint');status.setAttribute('role','status');
    save.type='submit';process.type='button';let commandKey=null,recorded=null;
    input.addEventListener('input',()=>{commandKey=null;recorded=null;});
    const submit=async(execute)=>{
      if(save.disabled||!sameSession(target))return;
      if(!input.value.trim())return input.focus();remember();save.disabled=process.disabled=true;
      try{
        if(!await waitForSave()||!sameSession(target)){setText(status,msg("ui.the_body_has_not_finished_saving_your_comment_remains"));return;}
        commandKey ||= crypto.randomUUID();
        recorded ||= await write('script-notes',{scope_key:target.scopeKey,scene_id:anchor.scene_id,line_id:anchor.line_id,
          body:input.value,base_draft_revision:draft.draft_revision},false,target,commandKey);
        if(execute){const noteId=recorded.id || recorded.note?.id;if(!noteId)throw new Error('原意见已保存，但回执没有批注身份；请从下方已保存意见继续。');await write('review-process',{script_note_id:noteId},false,target,'review:'+commandKey);}
        if(sameSession(target)){setText(status,execute?msg("ui.original_comment_is_fixed_review_its_status_and_suggestions"):msg("ui.original_comment_fixed_to_the_displayed_draft"));noteDrafts.delete(key);stash('vsc-script-note:'+key,null);input.value='';await refreshMeta();}
      }catch(error){if(sameSession(target))setText(status,msg("ui.value0_comment_text_is_preserved_continue_here",{value0:error.message}));}
      finally{if(sameSession(target))save.disabled=process.disabled=false;}
    };
    form.addEventListener('submit',event=>{event.preventDefault();return submit(false);});process.addEventListener('click',()=>submit(true));
    const retry=el('button','',msg("ui.retry_saving_text"));retry.type='button';retry.addEventListener('click',async()=>{lastError=null;await flushSave();setText(status,lastError?msg("ui.text_is_still_unsaved_the_comment_is_preserved"):msg("ui.text_saved_you_can_continue_submitting_the_comment"));});
    form.append(input,save,process,retry,status);return form;
  }

  function renderNotes() {
    const panel = el('section', 'script-notes');
    const notes = draft.notes || [];
    panel.append(el('h3', '', msg("ui.annotations_value0_pending_value1_total",{value0:notes.filter(row => row.status === 'open').length,value1:notes.length})));
    const list = el('ul', 'notes-list');
    for (const note of notes) {
      const item = el('li', `note-${note.status}`);
      const baseline = note.base_draft_revision != null && note.base_content_sha256
        ? `基准 r${note.base_draft_revision} · SHA ${note.base_content_sha256}${note.base_artifact_id ? ' · 冻结版本 ' + note.base_artifact_id : ''}`
        : '基准未知（历史批注未记录所见版本）';
      item.append(el('span', 'note-anchor', joinMessages(["",note.scope_key == null ? msg("ui.unassigned_history") : '',"",note.scene_id,"",note.line_id ? joinMessages([" / ",note.line_id]) : '',""])),
        el('span', '', note.body),
        el('small', 'note-baseline', baseline),
        el('small', '', joinMessages(["",note.author," · ",String(note.created_at || '').slice(0, 19)," · ",{open: '待处理', resolved: '已解决', dismissed: '已忽略'}[note.status],""])));
      if (note.status === 'open') {
        if(note.line_id && note.base_draft_revision!=null){
          const action=(label,newAttempt=false)=>{const propose=el('button','',label),target=session,key=crypto.randomUUID();propose.addEventListener('click',async()=>{if(!sameSession(target))return;propose.disabled=true;try{if(!await waitForSave())return notice(msg("ui.text_is_unsaved_original_comment_preserved_save_successfully_before"));if(!sameSession(target))return;await write('review-process',{script_note_id:note.id,...(newAttempt?{new_attempt:true}:{})},false,target,key);if(sameSession(target))await refreshMeta();}catch(error){if(sameSession(target))notice(error.message);}finally{if(sameSession(target))propose.disabled=false;}});return propose;};
          item.append(action('按此意见提出局部修改'));if(note.review_history?.responses?.length)item.append(action('明确新一轮局部修改',true));
        }
        const resolve = el('button', '', msg("ui.resolve"));
        resolve.addEventListener('click', async () => {
          const reason = prompt('解决说明：'); if (!reason) return;
          try { await write('script-note-decisions', {note_id: note.id, outcome: 'resolve', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        const dismiss = el('button', '', msg("ui.dismiss"));
        dismiss.addEventListener('click', async () => {
          const reason = prompt('忽略说明：'); if (!reason) return;
          try { await write('script-note-decisions', {note_id: note.id, outcome: 'dismiss', reason}); await refreshMeta(); } catch (error) { notice(error.message); }
        });
        item.append(resolve, dismiss);
      }
      if(note.review_history){const history=el('div','note-results');for(const response of note.review_history.responses || []){history.append(el('p','',response.explanation),el('p','hint',response.limitations));for(const run of response.runs || []){history.append(el('p','',({completed:'已有局部建议，请在差异区决定',submission_unknown:'提交结果待核实，不会自动重发',failed:'此次处理失败，原意见保留',stale:'稿次已变化，请重新定位'})[run.status] || msg("ui.still_processing_refresh_to_review")));for(const suggestion of run.suggestions || [])history.append(el('s','',suggestion.before_value),el('b','',suggestion.after_value));}}item.append(history);}
      const history=el('details','note-history'),body=el('div');history.append(el('summary','',msg("ui.view_processing_history_for_this_item")),body);let loaded=false;
      history.addEventListener('toggle',async()=>{if(!history.open||loaded)return;const target=session;try{const data=await ctx.api(`${target.project}/review-history?script_note_id=${encodeURIComponent(note.id)}&limit=10`);if(!sameSession(target))return;const {renderReviewHistory}=await import('./review.js');if(!sameSession(target))return;body.replaceChildren(renderReviewHistory(data,{historyPage:async(filters,page)=>{const data=await ctx.api(`${target.project}/review-history?`+new URLSearchParams({...filters,...page}));if(sameSession(target))return data;},onError:error=>notice(error.message)}));loaded=true;}catch(error){if(sameSession(target))setText(body,error.message);}});item.append(history);
      list.append(item);
    }
    if (!notes.length) list.append(el('li', 'hint', msg("ui.no_annotations_yet_select_annotation_on_a_dialogue_or")));
    panel.append(list,pagination('notes',draft.notes_page), el('p', 'hint', msg("ui.new_annotations_bind_to_the_saved_draft_content_digest")));
    return panel;
  }

  function destroy() {
    clearTimeout(saveTimer); saveTimer = null; session = null; generation++;
    pageWindow?.removeEventListener('beforeunload', beforeUnload);
    recoveries.clear();
  }

  return {load, reload: load, destroy};
}
