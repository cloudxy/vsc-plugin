/* Versioned local edits. The existing artifact decision remains the approval. */
const node = (tag, text) => { const value = document.createElement(tag); if (text != null) value.textContent = text; return value; };
export function createLocalProduction(dialog, ctx) {
  let ticket = 0;
  return {async open(action, row) {
    const current = ++ticket, project = ctx.project(), base = `/api/v1/projects/${encodeURIComponent(project)}`;
    const active = () => current === ticket && project === ctx.project();
    const entity = action === 'replace_instance' ? row.id : action === 'redo_sound' ? row.shot_id || row.id : row.id;
    const options = await ctx.api(`${base}/local-production/options?action=${encodeURIComponent(action)}&entity_id=${encodeURIComponent(entity)}`);
    if (!active()) return;
    dialog.replaceChildren();
    const title = {replace_instance:'替换这个使用实例的固定版本', redo_sound:'只重做本镜声音', resample:'明确新增一次抽样'}[action];
    const heading = node('h2', title), close = node('button', '关闭'); close.addEventListener('click', () => {ticket++;dialog.close();});
    const form = node('div'), select = node('select'), seed = node('input'), status = node('p'), details = node('section');
    select.setAttribute('aria-label', action === 'replace_instance' ? '替换规格版本' : '声音用途');
    if (action === 'replace_instance') for (const spec of options.specs || []) {
      const item = node('option', `${spec.title} · v${spec.artifact_version}${spec.current_for_instance ? '（本实例当前版本）' : ''}`); item.value = spec.id; select.append(item);
    }
    if (action === 'redo_sound') for (const purpose of options.purposes || []) {
      const names = {dialogue_dry:'对白干声',dialogue:'对白',tts:'配音',ambience:'环境声',music:'配乐',sfx:'音效',sound_effect:'音效'};
      const item = node('option', names[purpose] || purpose);item.value = purpose;select.append(item);
    }
    if(row.media_review_id && row.purpose){select.value=row.purpose;select.disabled=true;}
    seed.type = 'number'; seed.placeholder = '新 seed（选填；留空保留原参数）';seed.setAttribute('aria-label', '新抽样seed');
    if (action !== 'resample') form.append(select); if (action !== 'replace_instance') form.append(seed);
    const preview = node('button', '预览目标与影响'), propose = node('button', '提交待审方案'); propose.disabled = true;
    let fixed = null, parameters = null, previewTicket = 0, proposalKey = null;
    const invalidate = () => {previewTicket++;fixed=null;proposalKey=null;propose.disabled=true;details.replaceChildren();};
    select.addEventListener('change', invalidate);seed.addEventListener('input', invalidate);
    preview.addEventListener('click', async () => {
      const attempt = ++previewTicket;
      try {
        parameters = {action};
        if (action === 'replace_instance') parameters = {...parameters,instance_id:entity,replacement_spec_version_id:select.value};
        else if (action === 'redo_sound') parameters = {...parameters,shot_id:entity,purpose:select.value};
        else parameters.job_id = entity;
        if(row.media_review_id)parameters.media_review_id=row.media_review_id;
        if (seed.value !== '') {const value=Number(seed.value);if(!Number.isSafeInteger(value))throw new Error('seed须为整数');parameters.params={seed:value};}
        const result = await ctx.api(`${base}/local-production/preview`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:parameters})});
        if (!active() || attempt !== previewTicket) return;
        fixed={...result,payload:parameters};proposalKey=crypto.randomUUID();details.replaceChildren(node('h3', `本次只涉及 ${result.targets.length} 个目标`));
        for (const target of result.targets) details.append(node('p', target.label || `${target.purpose || ''} · 候选 ${target.candidate_no ?? ''}`));
        const evidence=node('details');evidence.append(node('summary','固定输入、版本及参数差异'),node('pre',JSON.stringify({sources:result.sources,targets:result.targets},null,2)));details.append(evidence);
        if(result.review)details.prepend(node('blockquote',result.review.body));
        status.textContent='确认预览后只建立待审版本；批准后才能入队。声音沿原参数新做一次；原意见中的声线、演法等额外要求须由声音负责人落实。';propose.disabled=false;
      } catch(error) {if(active())status.textContent=error.message;}
    });
    propose.addEventListener('click', async () => {
      if(!fixed || !active())return;propose.disabled=true;
      try {
        const session=ctx.session();if(!session.actor)throw new Error('请先建立人工操作会话');
        const result=await ctx.api(`${base}/local-production-proposals`, {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({payload:{...fixed.payload,preview_sha256:fixed.preview_sha256},expected_revision:fixed.revision,idempotency_key:proposalKey})});
        if(!active())return;ctx.revision(result.revision);dialog.close();
        if(row.media_review_id && typeof row.onReviewProposed==='function')await row.onReviewProposed(result);
        else await ctx.onArtifact(result.artifact.id);
      } catch(error) {if(active()){status.textContent=error.message;propose.disabled=false;}}
    });
    dialog.append(heading,close,form,preview,details,status,propose);dialog.showModal();
  }};
}
