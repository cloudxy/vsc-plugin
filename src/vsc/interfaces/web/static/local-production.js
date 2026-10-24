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
    const preview = node('button', '预览目标与影响'), propose = node('button', '提交待审方案');
    const authorize=node('button','按所见范围重做声音'),resume=node('button','继续已授权的制作');authorize.className='primary';
    propose.disabled = authorize.disabled = true;
    const receiptStore=ctx.receiptStore || (typeof sessionStorage==='undefined'?null:sessionStorage);
    const receiptKey=`vsc.local-authorized:${ctx.session().actor||'reader'}:${project}:${action}:${entity}`;
    let receipt=null;
    try{receipt=JSON.parse(receiptStore?.getItem(receiptKey)||'null');}catch{}
    resume.hidden=!receipt;
    const persist=()=>{try{
      if(receipt){const {keys,preview_sha256,proposal,revision}=receipt;
        receiptStore?.setItem(receiptKey,JSON.stringify({keys,preview_sha256,proposal,revision}));}
      else receiptStore?.removeItem(receiptKey);
    }catch{}};
    let fixed = null, parameters = null, previewTicket = 0, proposalKey = null;
    const invalidate = () => {previewTicket++;fixed=null;proposalKey=null;propose.disabled=authorize.disabled=true;details.replaceChildren();};
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
        for (const target of result.targets) {
          const label=({dialogue_dry:'对白干声',dialogue:'对白',tts:'配音',ambience:'环境声',music:'配乐',sfx:'音效',sound_effect:'音效'})[target.purpose]||target.purpose||'制作目标';
          details.append(node('p',target.label || `${label} · 候选 ${target.candidate_no ?? ''}`));
          if(action==='redo_sound'&&target.after_prompt)details.append(node('p',`本次固定内容：${target.after_prompt}`));
        }
        const quote=result.artifact?.document?.generation_quote;
        if(quote){
          const pricing=node('section');pricing.className='generation-quote';pricing.append(node('h3','授权前用量与费用估算'));
          for(const [currency,amount] of Object.entries(quote.known_subtotals||{}))pricing.append(node('p',`已知部分估算：${amount} ${currency}；实际账单另核。`));
          if(quote.unknown_jobs)pricing.append(node('p',`${quote.unknown_jobs} 项金额尚不确定，不表示免费；原生用量上限仍沿原预算。`));
          for(const item of quote.jobs||[]){const source=item.source;if(source?.source_date)pricing.append(node('p',`价格依据日期：${source.source_date}；${item.reason}`));}
          details.append(pricing);
        }
        const evidence=node('details');evidence.append(node('summary','固定输入、版本及参数差异'),node('pre',JSON.stringify({sources:result.sources,targets:result.targets},null,2)));details.append(evidence);
        if(result.review)details.prepend(node('blockquote',result.review.body));
        if(action==='redo_sound'){
          const usage=node('section');usage.append(node('h3','本次用量'));
          const operations=Object.values(result.artifact?.document?.operations||{});
          for(const unit of operations)usage.append(node('p',Object.entries(unit).map(([k,v])=>`${({remote_jobs:'远端任务数',audio_jobs:'声音任务数',speech_chars:'语音字符数',images:'图片数',video_seconds:'视频秒数',vision_jobs:'视觉任务数',audio_seconds:'音频秒数',duration_seconds:'时长（秒）',characters:'字符数',calls:'调用次数',tokens:'Token',unit:'单位',quantity:'数量',amount:'数量',basis:'计量依据'})[k]||k}：${typeof v==='object'?JSON.stringify(v):v}`).join('；')));
          if(!operations.length)usage.append(node('p','当前方案未提供可核实的原生用量；费用由原预算与服务回执核对。'));
          details.append(usage);
          status.textContent='沿所见固定台词、声线和参数新增声音候选，保留原视频。一次授权会依次登记方案、批准所见版本并入队；原预算、权限和执行前检查仍生效。';
        }else status.textContent='确认预览后只建立待审版本；批准后才能入队。';
        propose.disabled=authorize.disabled=!!receipt;
        if(receipt)status.textContent+=' 已有未完成的操作回执，请先接续原来的制作。';
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
    async function continueAuthorized(){
      if(!receipt||!active())return;
      resume.disabled=authorize.disabled=propose.disabled=preview.disabled=true;
      try{
        const session=ctx.session();if(!session.actor)throw new Error('请先登录，再接续已授权制作');
        const readReceipt=async key=>{
          const value=await ctx.api(`${base}/operation-receipts/${encodeURIComponent(key)}`,{headers:{'X-CSRF-Token':session.csrf}});
          return value.found?value.response:null;
        };
        const post=async(endpoint,payload,key,revision)=>ctx.api(`${base}/${endpoint}`,{method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},
          body:JSON.stringify({payload,expected_revision:revision,idempotency_key:key,confirmed:true})});
        const proposed=await readReceipt(receipt.keys.propose);
        if(proposed){receipt.proposal=proposed.artifact.id;receipt.revision=proposed.revision;persist();}
        if(!receipt.proposal){
          status.textContent='正在登记所见声音方案…';
          if(!receipt.payload){
            if(!fixed||fixed.preview_sha256!==receipt.preview_sha256)throw new Error('原固定方案尚未登记，请重新读取相同输入；范围或版本变化时须重新决定');
            receipt.payload={...fixed.payload,preview_sha256:fixed.preview_sha256};
          }
          const result=await post('local-production-proposals',receipt.payload,receipt.keys.propose,receipt.revision);
          receipt.proposal=result.artifact.id;receipt.revision=result.revision;persist();if(active())ctx.revision(result.revision);
        }
        const approved=await readReceipt(receipt.keys.approve);
        if(approved){receipt.approved=true;receipt.revision=approved.revision;persist();}
        if(!receipt.approved){
          status.textContent='正在记录本次固定版本的批准…';
          const result=await post('artifact-decisions',{artifact_id:receipt.proposal,outcome:'approve',reason:'用户在所见声音范围与用量预览中明确授权重做'},receipt.keys.approve,receipt.revision);
          receipt.approved=true;receipt.revision=result.revision;persist();if(active())ctx.revision(result.revision);
        }
        const enqueued=await readReceipt(receipt.keys.enqueue);
        if(enqueued){receipt.enqueued=true;receipt.revision=enqueued.revision;receipt.jobs=enqueued.jobs;}
        if(!receipt.enqueued){
          status.textContent='正在将已批准声音方案入队…';
          const result=await post('local-production-enqueue',{artifact_id:receipt.proposal},receipt.keys.enqueue,receipt.revision);
          receipt.enqueued=true;receipt.revision=result.revision;receipt.jobs=result.jobs;persist();if(active())ctx.revision(result.revision);
        }
        const artifactId=receipt.proposal;receipt=null;fixed=null;persist();if(!active())return;
        resume.hidden=true;status.textContent='声音任务已入队，等待执行器产生新候选；尚未替换原声音。';
        const open=node('button','回看本次声音方案');open.addEventListener('click',()=>ctx.onArtifact(artifactId));details.append(open);
        if(row.media_review_id&&typeof row.onReviewProposed==='function')await row.onReviewProposed({artifact:{id:artifactId}});
      }catch(error){if(active()){status.textContent=`${error.message}。已完成步骤保留，可继续接续。`;resume.hidden=false;}}
      finally{if(active()){resume.disabled=preview.disabled=false;authorize.disabled=!!receipt||!fixed;propose.disabled=!!receipt||!fixed;}}
    }
    authorize.addEventListener('click',async()=>{
      if(!fixed||!active()||authorize.disabled)return;
      if(!ctx.session().actor){status.textContent='请先登录，再授权制作。';return;}
      receipt={payload:{...fixed.payload,preview_sha256:fixed.preview_sha256},preview_sha256:fixed.preview_sha256,revision:fixed.revision,
        keys:{propose:crypto.randomUUID(),approve:crypto.randomUUID(),enqueue:crypto.randomUUID()}};
      persist();await continueAuthorized();
    });
    resume.addEventListener('click',continueAuthorized);
    dialog.append(heading,close,form,preview,details,status,propose);
    if(action==='redo_sound')dialog.append(authorize,resume);
    dialog.showModal();
  }};
}
