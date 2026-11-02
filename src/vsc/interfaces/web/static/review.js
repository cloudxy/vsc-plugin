import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Opinions remain on their original object; all progress is read from durable links. */
const el=(tag,text)=>{const node=document.createElement(tag);if(text!=null)setText(node,text);return node;};
const executionLabels={created:msg("ui.waiting_to_execute"),queued:msg("ui.waiting_for_worker"),running:msg("ui.executing"),submitted:msg("ui.submitted_to_service"),
  polling:msg("ui.waiting_for_service"),succeeded:msg("ui.finished"),failed:msg("ui.execution_blocked"),blocked:msg("ui.prerequisites_unmet"),cancelled:msg("script-studio.text_057"),
  stale:msg("ui.old_baseline_result_returned"),submission_unknown:msg("ui.submission_result_needs_verification")};
export function previewContentUrl(preview){
  if(preview.result_availability?.status==='unavailable')return null;
  const url=preview.output?.content_url;
  return typeof url==='string'&&url.startsWith('/api/v1/projects/')?url:null;
}
export function renderEditPreviewResult(preview,ctx={}){
  const result=el('section'),url=previewContentUrl(preview);result.className='edit-preview-result';
  result.append(el('p',msg("ui.execution_value0",{value0:executionLabels[preview.status]||msg("ui.status_needs_verification")})));
  const resultStatus=el('p',url?(preview.status==='stale'?msg("ui.result_preview_registered_against_an_old_baseline_check_the"):msg("ui.result_preview_registered_review_the_revision")):
    preview.result_availability?.message||(preview.status==='succeeded'?msg("ui.result_execution_finished_but_no_preview_is_available_yet"):msg("ui.result_no_preview_available_yet")));
  result.append(resultStatus);
  if(url&&preview.result_availability?.status==='unverified'&&preview.result_availability.message)result.append(el('p',preview.result_availability.message));
  if(preview.error)result.append(el('p',preview.error));
  else if(preview.explanation&&preview.status!=='succeeded')result.append(el('p',preview.explanation));
  if(!url&&ctx.reload&&['succeeded','blocked','stale'].includes(preview.status)){
    const reload=el('button',msg("ui.reload_this_result"));reload.type='button';
    reload.addEventListener('click',async()=>{try{await ctx.reload();}catch(error){ctx.onError?.(error);}});
    result.append(reload);
  }
  if(preview.status==='failed'&&ctx.retry){
    const retry=el('button',msg("ui.retry_this_preview"));retry.type='button';
    retry.addEventListener('click',async()=>{if(retry.disabled)return;retry.disabled=true;try{await ctx.retry();}catch(error){ctx.onError?.(error);}finally{retry.disabled=false;}});
    result.append(retry);
  }
  if(url){
    const video=el('video');video.className='media-player';video.controls=true;video.preload='metadata';video.src=url;
    result.append(video,el('p',msg("ui.review_and_selection_this_is_a_local_draft_preview")));
    video.addEventListener('loadedmetadata',()=>{setText(resultStatus,preview.status==='stale'?msg("ui.result_old_baseline_preview_loaded_check_the_current_version"):msg("ui.result_preview_loaded_revision_awaits_review"));});
    video.addEventListener('error',()=>{
      setText(resultStatus,msg("ui.result_preview_playback_is_blocked_and_cannot_yet_be"));
      if(result.querySelector('.preview-playback-error'))return;
      const error=el('p',msg("ui.preview_playback_is_blocked_reload_this_result_the_execution"));
      error.className='preview-playback-error';error.setAttribute('role','status');result.append(error);
      if(ctx.reload){const retry=el('button',msg("ui.reload_this_result"));retry.type='button';retry.addEventListener('click',async()=>{try{await ctx.reload();}catch(error){ctx.onError?.(error);}});result.append(retry);}
    });
  }
  return result;
}
export function renderReviewHistory(history,ctx={}) {
  const root=el('section');root.className='review-history detail-panel';
  let pageRequest=0;
  const replace=value=>{const next=renderReviewHistory(value,ctx);root.parentNode?.insertBefore(next,root);root.remove();};
  const paging=(page,filters,response=false,item=null)=>{
    const nav=el('nav');nav.className='review-history-pagination';bindAttribute(nav,'aria-label',response?msg("ui.processing_history_pagination"):msg("ui.original_comment_pagination"));
    if(!page||(page.previous_offset==null&&page.next_offset==null))return nav;
    nav.append(el('small',msg("ui.value0_value1_records_value2_per_page",{value0:response?msg("ui.processing_record"):msg("ui.original_comment"),value1:page.total,value2:page.limit})));
    for(const [label,offset]of [[msg("ui.newer_page"),page.previous_offset],[msg("ui.older_page"),page.next_offset]]){const b=el('button',label);b.type='button';b.disabled=offset==null||!ctx.historyPage;b.addEventListener('click',async()=>{const request=++pageRequest;b.disabled=true;try{const value=await ctx.historyPage(filters,response?{response_offset:offset,response_limit:page.limit}:{offset,limit:page.limit});if(!value||request!==pageRequest)return;if(response){const items=(history.items||[]).map(row=>row===item?value.items[0]:row);replace({...history,items});}else replace(value);}catch(error){if(request===pageRequest)ctx.onError?.(error);}finally{if(request===pageRequest)b.disabled=false;}});nav.append(b);}
    return nav;
  };
  if(ctx.heading!==false)root.append(el('h3',msg("ui.comments_and_this_round_s_results")));
  for(const item of history?.items || []){
    const block=el('article');block.append(el('blockquote',item.body));
    for(const preview of item.edit_previews || []){
      const key=crypto.randomUUID();
      block.append(renderEditPreviewResult(preview,{onError:ctx.onError,reload:ctx.reload,
        ...(ctx.retryPreview?{retry:()=>ctx.retryPreview(preview,item,key)}:{})}));
    }
    if(item.note?.range_seconds)block.append(el('p',msg("ui.displayed_segment_value0_value1_seconds",{value0:item.note.range_seconds.start.toFixed(2),value1:item.note.range_seconds.end.toFixed(2)})));
    if(item.note?.anchor?.excerpt)block.append(el('p',msg("ui.displayed_source_text_value0",{value0:item.note.anchor.excerpt})));
    if(ctx.process && item.source.artifact_note_id){const action=(label,newAttempt=false)=>{const process=el('button',label),key=crypto.randomUUID();process.type='button';process.addEventListener('click',async()=>{process.disabled=true;try{await ctx.process({...item.source,...(newAttempt?{new_attempt:true}:{})},key);}catch(error){ctx.onError?.(error);}finally{process.disabled=false;}});return process;};block.append(action('交专业角色处理'));if(item.responses?.some(row=>row.dispatches?.length))block.append(action('明确新一轮专业处理',true));}
    for(const job of item.source_jobs || [])if(job.modality==='audio' && job.shot_id && ctx.local){const button=el('button',msg("ui.redo_this_shot_s_sound_with_original_parameters"));button.type='button';button.addEventListener('click',()=>ctx.local('redo_sound',{...job,media_review_id:item.source.media_review_id}));block.append(button);}
    for(const [index,response] of (item.responses || []).entries()){
      const resultBlock=el('section');if(index<item.responses.length-1){const earlier=el('details');earlier.append(el('summary',msg("ui.earlier_processing_records")),resultBlock);block.append(earlier);}else block.append(resultBlock);
      if(response.explanation)resultBlock.append(el('p',msg("ui.this_round_s_processing_value0",{value0:response.explanation})));
      const returned=response.dispatches?.some(dispatch=>dispatch.returns?.some(result=>result.artifacts?.length));
      if(!(returned && response.limitations?.startsWith('已派给原专业角色')))resultBlock.append(el('p',response.limitations));
      if(response.preserve)resultBlock.append(el('p',msg("ui.preserved_items_value0",{value0:response.preserve})));
      for(const run of response.runs || []){
        resultBlock.append(el('p',(run.status==='completed'&&!run.suggestions?.length)?msg("ui.execution_finished_but_no_revision_suggestion_is_available_for"):
          ({running:'仍在处理；刷新回看，不重复提交',completed:'已有局部建议，请在原差异区接受或拒绝',failed:'此次建议失败，原意见保留',stale:'所见内容已变化，原意见保留',submission_unknown:'提交结果待核实；不会自动重新调用'})[run.status] || msg("ui.awaiting_review")));
        for(const suggestion of run.suggestions || []){resultBlock.append(el('del',suggestion.before_value),el('ins',suggestion.after_value));const decision=suggestion.decisions?.at(-1);if(decision)resultBlock.append(el('p',({accept:'用户已接受此条建议',reject:'用户已拒绝此条建议',undo_accept:'用户已撤销接受'})[decision.outcome] || msg("ui.waiting_for_user_decision")));}
      }
      const open=(kind,id,label)=>{const button=el('button',label);button.type='button';button.addEventListener('click',()=>ctx[kind]?.(id));resultBlock.append(button);};
      for(const proposal of response.proposals || []){
        open('artifact',proposal.id,proposal.approved?'回看已批准局部方案':'回看待审局部方案');
        if(!proposal.jobs?.length)resultBlock.append(el('p',msg("ui.not_executed_yet_no_new_media_result")));
        for(const job of proposal.jobs||[]){
          const outputs=(job.outputs||[]).filter(output=>output.media_id);
          resultBlock.append(el('p',msg("ui.execution_value0",{value0:executionLabels[job.status]||msg("ui.status_needs_verification")})),
            el('p',outputs.length?msg("ui.result_new_media_registered_open_it_to_listen_or"):
              job.status==='succeeded'?msg("ui.result_execution_finished_but_no_new_media_is_registered"):msg("ui.result_no_new_media_registered_yet_the_original_comment")));
          for(const output of outputs)open('media',output.media_id,'试听／预览新结果');
        }
      }
      for(const dispatch of response.dispatches || []){resultBlock.append(el('p',dispatch.message));for(const result of dispatch.returns || []){if(result.summary)resultBlock.append(el('p',result.summary));if(!result.artifacts?.length)resultBlock.append(el('p',msg("ui.processing_record_received_but_no_specialist_result_is_available")));for(const artifact of result.artifacts || []){open('artifact',artifact.id,'回看专业修改结果');for(const preview of artifact.previews || [])if(preview.media_id)open('media',preview.media_id,'预览专业修改结果');if(['subtitle','edit'].includes(item.note?.category) && !artifact.previews?.some(p=>p.media_id) && !item.edit_previews?.some(previewContentUrl))resultBlock.append(el('p',msg("ui.new_preview_is_not_registered_yet_continue_production_through")));}}}
    }
    if(!item.responses?.length&&!item.edit_previews?.length)block.append(el('p',item.note?.outcome==='pass'?msg("ui.usage_review_recorded"):msg("ui.original_comment_saved_no_processing_result_yet")));
    if(item.source.media_review_id && item.note?.outcome==='pass' && !item.responses?.length){const earlier=el('details');earlier.append(el('summary',msg("ui.passed_usage_reviews")),block);root.append(earlier);}else root.append(block);
    block.append(paging(item.response_page,item.source,true,item));
  }
  if(!history?.items?.length)root.append(el('p',msg("ui.no_original_comment_yet")));
  root.append(paging(history?.page,history?.page?.filter));
  return root;
}

export function createArtifactReviewForm(targets,ctx){
  const root=el('form');root.className='artifact-review-form review-form';
  root.append(el('h3',msg("ui.comment_on_the_displayed_version")));
  const select=el('select'),body=el('textarea'),start=el('input'),end=el('input'),status=el('p'),submit=el('button',msg("ui.save_original_comment")),capture=el('button',msg("ui.use_current_playback_position")),startLabel=el('label',msg("ui.start_seconds")),endLabel=el('label',msg("ui.end_seconds"));
  capture.type='button';startLabel.append(start);endLabel.append(end);body.rows=3;bindAttribute(body,"placeholder",msg("ui.comment_on_the_displayed_result_save_then_process_and"));
  bindAttribute(select,'aria-label',msg("ui.comment_location"));bindAttribute(body,'aria-label',msg("ui.original_comment"));body.required=true;body.maxLength=4000;
  for(const [index,row]of targets.entries()){const option=el('option',row.label);option.value=String(index);select.append(option);}
  for(const input of [start,end]){input.type='number';input.min='0';input.step='0.001';}
  bindAttribute(start,'aria-label',msg("agent.overseas_remake_start_seconds"));bindAttribute(end,'aria-label',msg("agent.overseas_remake_end_seconds"));
  const choose=()=>{const row=targets[Number(select.value) || 0],timed=!!row.fps_num;startLabel.hidden=endLabel.hidden=capture.hidden=!timed;if(timed){const fps=row.fps_num/row.fps_den,at=Math.min(Math.max(0,ctx.currentTime?.() || 0),Math.max(0,(row.duration_frames-1)/fps));start.value=String(at);end.value=String(Math.min(row.duration_frames/fps,at+1));}};
  select.addEventListener('change',choose);choose();let key=null;body.addEventListener('input',()=>{key=null;});select.addEventListener('change',()=>{key=null;});start.addEventListener('input',()=>{key=null;});end.addEventListener('input',()=>{key=null;});
  capture.addEventListener('click',()=>{choose();key=null;});root.append(select,capture,startLabel,endLabel,body,submit,status);
  root.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{const row=targets[Number(select.value)||0],payload={...row.target,body:body.value};if(row.fps_num){const fps=row.fps_num/row.fps_den;payload.start_frame=Math.floor(Number(start.value)*fps);payload.end_frame=Math.ceil(Number(end.value)*fps);if(!Number.isFinite(payload.start_frame)||!Number.isFinite(payload.end_frame)||payload.start_frame<0||payload.end_frame<=payload.start_frame||payload.end_frame>row.duration_frames)throw new Error('请选择所见成片内的有效时间区间。');}key ||= crypto.randomUUID();await ctx.save(payload,key);setText(status,msg("ui.original_comment_fixed_to_the_displayed_version_continue_processing"));}catch(error){setText(status,error.message);}finally{submit.disabled=false;}});
  return root;
}
