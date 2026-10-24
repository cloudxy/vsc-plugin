/* Opinions remain on their original object; all progress is read from durable links. */
const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;return node;};
const executionLabels={created:'等待执行',queued:'等待执行器',running:'正在执行',submitted:'已提交服务',
  polling:'正在等待服务',succeeded:'已结束',failed:'执行受阻',blocked:'前置未满足',cancelled:'已停止',
  stale:'已返回旧基线结果',submission_unknown:'提交结果待核实'};
export function previewContentUrl(preview){
  if(preview.result_availability?.status==='unavailable')return null;
  const url=preview.output?.content_url;
  return typeof url==='string'&&url.startsWith('/api/v1/projects/')?url:null;
}
export function renderEditPreviewResult(preview,ctx={}){
  const result=el('section'),url=previewContentUrl(preview);result.className='edit-preview-result';
  result.append(el('p',`执行：${executionLabels[preview.status]||'状态待核实'}`));
  const resultStatus=el('p',url?(preview.status==='stale'?'结果：已登记旧基线预览，请核对当前版本。':'结果：预览已登记，请回看修改效果。'):
    preview.result_availability?.message||(preview.status==='succeeded'?'结果：执行已结束，尚无可回看的预览。':'结果：尚无可回看的预览。'));
  result.append(resultStatus);
  if(url&&preview.result_availability?.status==='unverified'&&preview.result_availability.message)result.append(el('p',preview.result_availability.message));
  if(preview.error)result.append(el('p',preview.error));
  else if(preview.explanation&&preview.status!=='succeeded')result.append(el('p',preview.explanation));
  if(!url&&ctx.reload&&['succeeded','blocked','stale'].includes(preview.status)){
    const reload=el('button','重新读取本次结果');reload.type='button';
    reload.addEventListener('click',async()=>{try{await ctx.reload();}catch(error){ctx.onError?.(error);}});
    result.append(reload);
  }
  if(preview.status==='failed'&&ctx.retry){
    const retry=el('button','重试这次预览');retry.type='button';
    retry.addEventListener('click',async()=>{if(retry.disabled)return;retry.disabled=true;try{await ctx.retry();}catch(error){ctx.onError?.(error);}finally{retry.disabled=false;}});
    result.append(retry);
  }
  if(url){
    const video=el('video');video.className='media-player';video.controls=true;video.preload='metadata';video.src=url;
    result.append(video,el('p','审阅与采用：局部草稿预览，正式采用仍需审阅固定版本。'));
    video.addEventListener('loadedmetadata',()=>{resultStatus.textContent=preview.status==='stale'?'结果：旧基线预览已载入，请核对当前版本。':'结果：预览已载入，修改效果待审。';});
    video.addEventListener('error',()=>{
      resultStatus.textContent='结果：预览播放受阻，尚不能回看。';
      if(result.querySelector('.preview-playback-error'))return;
      const error=el('p','预览播放受阻，请重新读取本次结果；执行回执和原意见仍保留。');
      error.className='preview-playback-error';error.setAttribute('role','status');result.append(error);
      if(ctx.reload){const retry=el('button','重新读取本次结果');retry.type='button';retry.addEventListener('click',async()=>{try{await ctx.reload();}catch(error){ctx.onError?.(error);}});result.append(retry);}
    });
  }
  return result;
}
export function renderReviewHistory(history,ctx={}) {
  const root=el('section');root.className='review-history detail-panel';
  let pageRequest=0;
  const replace=value=>{const next=renderReviewHistory(value,ctx);root.parentNode?.insertBefore(next,root);root.remove();};
  const paging=(page,filters,response=false,item=null)=>{
    const nav=el('nav');nav.className='review-history-pagination';nav.setAttribute('aria-label',response?'本条处理历史分页':'原意见分页');
    if(!page||(page.previous_offset==null&&page.next_offset==null))return nav;
    nav.append(el('small',`${response?'处理记录':'原意见'}：共 ${page.total} 条，每页 ${page.limit} 条`));
    for(const [label,offset]of [['较新一页',page.previous_offset],['较早一页',page.next_offset]]){const b=el('button',label);b.type='button';b.disabled=offset==null||!ctx.historyPage;b.addEventListener('click',async()=>{const request=++pageRequest;b.disabled=true;try{const value=await ctx.historyPage(filters,response?{response_offset:offset,response_limit:page.limit}:{offset,limit:page.limit});if(!value||request!==pageRequest)return;if(response){const items=(history.items||[]).map(row=>row===item?value.items[0]:row);replace({...history,items});}else replace(value);}catch(error){if(request===pageRequest)ctx.onError?.(error);}finally{if(request===pageRequest)b.disabled=false;}});nav.append(b);}
    return nav;
  };
  if(ctx.heading!==false)root.append(el('h3','意见与本轮结果'));
  for(const item of history?.items || []){
    const block=el('article');block.append(el('blockquote',item.body));
    for(const preview of item.edit_previews || []){
      const key=crypto.randomUUID();
      block.append(renderEditPreviewResult(preview,{onError:ctx.onError,reload:ctx.reload,
        ...(ctx.retryPreview?{retry:()=>ctx.retryPreview(preview,item,key)}:{})}));
    }
    if(item.note?.range_seconds)block.append(el('p',`所见片段 ${item.note.range_seconds.start.toFixed(2)}–${item.note.range_seconds.end.toFixed(2)} 秒`));
    if(item.note?.anchor?.excerpt)block.append(el('p',`所见原文：${item.note.anchor.excerpt}`));
    if(ctx.process && item.source.artifact_note_id){const action=(label,newAttempt=false)=>{const process=el('button',label),key=crypto.randomUUID();process.type='button';process.addEventListener('click',async()=>{process.disabled=true;try{await ctx.process({...item.source,...(newAttempt?{new_attempt:true}:{})},key);}catch(error){ctx.onError?.(error);}finally{process.disabled=false;}});return process;};block.append(action('交专业角色处理'));if(item.responses?.some(row=>row.dispatches?.length))block.append(action('明确新一轮专业处理',true));}
    for(const job of item.source_jobs || [])if(job.modality==='audio' && job.shot_id && ctx.local){const button=el('button','按原参数重做本镜声音');button.type='button';button.addEventListener('click',()=>ctx.local('redo_sound',{...job,media_review_id:item.source.media_review_id}));block.append(button);}
    for(const [index,response] of (item.responses || []).entries()){
      const resultBlock=el('section');if(index<item.responses.length-1){const earlier=el('details');earlier.append(el('summary','较早处理记录'),resultBlock);block.append(earlier);}else block.append(resultBlock);
      if(response.explanation)resultBlock.append(el('p',`本轮处理：${response.explanation}`));
      const returned=response.dispatches?.some(dispatch=>dispatch.returns?.some(result=>result.artifacts?.length));
      if(!(returned && response.limitations?.startsWith('已派给原专业角色')))resultBlock.append(el('p',response.limitations));
      if(response.preserve)resultBlock.append(el('p',`保留项：${response.preserve}`));
      for(const run of response.runs || []){
        resultBlock.append(el('p',(run.status==='completed'&&!run.suggestions?.length)?'执行已结束，尚无可回看的修改建议。':
          ({running:'仍在处理；刷新回看，不重复提交',completed:'已有局部建议，请在原差异区接受或拒绝',failed:'此次建议失败，原意见保留',stale:'所见内容已变化，原意见保留',submission_unknown:'提交结果待核实；不会自动重新调用'})[run.status] || '待回看'));
        for(const suggestion of run.suggestions || []){resultBlock.append(el('del',suggestion.before_value),el('ins',suggestion.after_value));const decision=suggestion.decisions?.at(-1);if(decision)resultBlock.append(el('p',({accept:'用户已接受此条建议',reject:'用户已拒绝此条建议',undo_accept:'用户已撤销接受'})[decision.outcome] || '等待用户决定'));}
      }
      const open=(kind,id,label)=>{const button=el('button',label);button.type='button';button.addEventListener('click',()=>ctx[kind]?.(id));resultBlock.append(button);};
      for(const proposal of response.proposals || []){
        open('artifact',proposal.id,proposal.approved?'回看已批准局部方案':'回看待审局部方案');
        if(!proposal.jobs?.length)resultBlock.append(el('p','尚未执行；没有新媒体结果。'));
        for(const job of proposal.jobs||[]){
          const outputs=(job.outputs||[]).filter(output=>output.media_id);
          resultBlock.append(el('p',`执行：${executionLabels[job.status]||'状态待核实'}`),
            el('p',outputs.length?'结果：已登记新媒体，请打开试听或预览；是否采用仍待决定。':
              job.status==='succeeded'?'结果：执行已结束，尚无已登记的新媒体。':'结果：尚无已登记的新媒体，原意见保留。'));
          for(const output of outputs)open('media',output.media_id,'试听／预览新结果');
        }
      }
      for(const dispatch of response.dispatches || []){resultBlock.append(el('p',dispatch.message));for(const result of dispatch.returns || []){if(result.summary)resultBlock.append(el('p',result.summary));if(!result.artifacts?.length)resultBlock.append(el('p','已收到处理记录，尚无可回看的专业成果；原意见保留。'));for(const artifact of result.artifacts || []){open('artifact',artifact.id,'回看专业修改结果');for(const preview of artifact.previews || [])if(preview.media_id)open('media',preview.media_id,'预览专业修改结果');if(['subtitle','edit'].includes(item.note?.category) && !artifact.previews?.some(p=>p.media_id) && !item.edit_previews?.some(previewContentUrl))resultBlock.append(el('p','新预览尚未登记，请由专业流程继续制作后回看。'));}}}
    }
    if(!item.responses?.length&&!item.edit_previews?.length)block.append(el('p',item.note?.outcome==='pass'?'用途审查已记录。':'原意见已保存，尚无处理结果。'));
    if(item.source.media_review_id && item.note?.outcome==='pass' && !item.responses?.length){const earlier=el('details');earlier.append(el('summary','已通过的用途审查'),block);root.append(earlier);}else root.append(block);
    block.append(paging(item.response_page,item.source,true,item));
  }
  if(!history?.items?.length)root.append(el('p','尚无原意见。'));
  root.append(paging(history?.page,history?.page?.filter));
  return root;
}

export function createArtifactReviewForm(targets,ctx){
  const root=el('form');root.className='artifact-review-form review-form';
  root.append(el('h3','对所见版本提意见'));
  const select=el('select'),body=el('textarea'),start=el('input'),end=el('input'),status=el('p'),submit=el('button','保存原意见'),capture=el('button','使用当前播放位置'),startLabel=el('label','开始（秒）'),endLabel=el('label','结束（秒）');
  capture.type='button';startLabel.append(start);endLabel.append(end);body.rows=3;body.placeholder='对所见结果提意见；保存后在下方处理与回看。';
  select.setAttribute('aria-label','意见位置');body.setAttribute('aria-label','原意见');body.required=true;body.maxLength=4000;
  for(const [index,row]of targets.entries()){const option=el('option',row.label);option.value=String(index);select.append(option);}
  for(const input of [start,end]){input.type='number';input.min='0';input.step='0.001';}
  start.setAttribute('aria-label','开始时间（秒）');end.setAttribute('aria-label','结束时间（秒）');
  const choose=()=>{const row=targets[Number(select.value) || 0],timed=!!row.fps_num;startLabel.hidden=endLabel.hidden=capture.hidden=!timed;if(timed){const fps=row.fps_num/row.fps_den,at=Math.min(Math.max(0,ctx.currentTime?.() || 0),Math.max(0,(row.duration_frames-1)/fps));start.value=String(at);end.value=String(Math.min(row.duration_frames/fps,at+1));}};
  select.addEventListener('change',choose);choose();let key=null;body.addEventListener('input',()=>{key=null;});select.addEventListener('change',()=>{key=null;});start.addEventListener('input',()=>{key=null;});end.addEventListener('input',()=>{key=null;});
  capture.addEventListener('click',()=>{choose();key=null;});root.append(select,capture,startLabel,endLabel,body,submit,status);
  root.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{const row=targets[Number(select.value)||0],payload={...row.target,body:body.value};if(row.fps_num){const fps=row.fps_num/row.fps_den;payload.start_frame=Math.floor(Number(start.value)*fps);payload.end_frame=Math.ceil(Number(end.value)*fps);if(!Number.isFinite(payload.start_frame)||!Number.isFinite(payload.end_frame)||payload.start_frame<0||payload.end_frame<=payload.start_frame||payload.end_frame>row.duration_frames)throw new Error('请选择所见成片内的有效时间区间。');}key ||= crypto.randomUUID();await ctx.save(payload,key);status.textContent='原意见已固定到所见版本；请在同一审阅区继续处理与回看。';}catch(error){status.textContent=error.message;}finally{submit.disabled=false;}});
  return root;
}
