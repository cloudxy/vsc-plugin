import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
// Explicit detection is an original quoted generation request, never a side effect of choosing an image.
const node=(tag,text)=>{const el=document.createElement(tag);if(text!=null)setText(el,text);return el;};
const copy=value=>JSON.parse(JSON.stringify(value));
export function mountSubjectSelector(host,ctx){
  let active=true,timer=null,quote=null;const source=ctx.source,state=ctx.state;
  const current=()=>active&&ctx.isCurrent()&&ctx.sourceIsCurrent(source);
  function button(text,action){const el=node('button',text);el.type='button';el.disabled=!ctx.writable;el.onclick=async()=>{if(!current())return;el.disabled=true;try{await action();}catch(error){if(current())ctx.notice(error.message);}finally{if(current()&&el.isConnected)el.disabled=!ctx.writable;}};return el;}
  host.append(node('h3',msg("ui.2_choose_the_speaking_subject")),node('p',msg("ui.the_person_in_the_white_region_speaks_request_a")));
  if(!source){host.append(node('p',msg("ui.choose_a_digital_human_image_before_detecting_or_drawing")));return {dispose(){active=false;}};}
  const models=ctx.models.filter(row=>row.enabled&&row.adapter_available&&row.capabilities?.image_operations?.includes('subject_detect'));
  const label=node('label',msg("ui.subject_detection_model")),model=node('select');bindAttribute(model,'aria-label',msg("ui.subject_detection_model"));model.append(localizedOption('',msg("ui.choose_an_enabled_detection_model")));
  for(const row of models)model.append(localizedOption(row.id,row.name||row.model_key));model.value=state.subjectModel||models[0]?.id||'';label.append(model);host.append(label);
  model.onchange=()=>{state.subjectModel=model.value;quote=null;details.replaceChildren();ctx.remember();};
  const actions=node('div'),details=node('section'),status=node('p');status.setAttribute('role','status');host.append(actions,details,status);
  actions.append(button(msg("ui.preview_usage_for_one_subject_detection"),async()=>{
    if(!model.value)throw new Error('请选择已启用的SAM3主体识别模型，或使用手绘。');
    const latest=await ctx.readOptions();if(!current())return;
    const prior=latest.drafts.find(row=>row.document.mode==='image_subject_detect');
    const document={shot_id:ctx.shotId,mode:'image_subject_detect',purpose:'image_edit',model_id:model.value,prompt:'person',count:1,params:{max_masks:6},references:[{role:'operation_source',media_id:source.media_id,sha256:source.sha256}]};
    const saved=await ctx.write('drafts',{document,base_draft_id:prior?.id||null});if(!current())return;
    const request=ctx.policy(saved.id);const value=await ctx.quote(request);if(!current())return;
    details.replaceChildren();quote=null;
    for(const gap of value.gaps||[])details.append(node('p',gap.message||gap.code));
    if(value.ready){quote={request,value,modelId:model.value};details.append(node('p',msg("ui.one_subject_detection_value0",{value0:JSON.stringify(value.generation_quote.native_units)})),node('p',value.generation_quote.all_prices_known?msg("ui.estimated_amount_value0",{value0:JSON.stringify(value.generation_quote.known_subtotals)}):msg("ui.amount_unknown_this_does_not_mean_free_more_335")),button(msg("ui.confirm_quote_and_detect_subjects"),async()=>{
      if(!quote||quote.modelId!==model.value)throw new Error('请重新预览当前识别报价。');
      const submitted=quote;const result=await ctx.write('generate',{request:submitted.request,preview_sha256:submitted.value.preview_sha256});
      state.subjectRun={jobs:result.jobs,source_media_id:source.media_id,source_sha256:source.sha256};ctx.remember();quote=null;
      if(current()){details.replaceChildren();await poll();}
    }));}
  }),button(msg("ui.draw_another_speaking_subject"),()=>ctx.onDraw()),button(msg("ui.recover_subject_detection_request"),async()=>{
    const result=await ctx.recover();if(!result)return ctx.notice(msg("ui.no_unconfirmed_subject_detection_request"));
    if(result.action==='generate'){state.subjectRun={jobs:result.value.jobs,source_media_id:result.source.media_id,source_sha256:result.source.sha256};ctx.remember();if(current())await poll();}
    else ctx.notice(msg("ui.original_detection_draft_receipt_recovered_preview_the_quote_again"));
  }),button(msg("ui.refresh_subject_candidates"),async()=>{await ctx.readOptions();if(current())ctx.onRefresh();}));
  const choices=ctx.candidates.filter(row=>row.source_media_id===source.media_id&&row.source_sha256===source.sha256);
  const selected=ctx.selection;
  if(selected?.origin==='manual')host.append(node('p',msg("ui.using_a_hand_drawn_subject_region_saving_and_refreshing")));
  const gallery=node('div');gallery.className='classic-reference-slots';host.append(gallery);
  for(const [index,choice]of choices.entries()){
    const item=node('figure'),image=node('img');image.src=ctx.mediaUrl(choice.mask_media_id);bindAttribute(image,"alt",msg("ui.person_candidate_value0_white_region_mask",{value0:index+1}));image.style.maxWidth='160px';
    const choose=button(msg("ui.choose_person_value0",{value0:index+1}),()=>ctx.onSelect(copy(choice)));choose.setAttribute('aria-pressed',String(selected?.mask_media_id===choice.mask_media_id));
    item.append(image,choose);gallery.append(item);
  }
  if(!choices.length)gallery.append(node('p',msg("ui.no_detection_candidates_for_this_source_image_hand_drawn")));
  async function poll(){
    clearTimeout(timer);const run=state.subjectRun;
    if(!current()||!run?.jobs?.length||run.source_media_id!==source.media_id||run.source_sha256!==source.sha256)return;
    try{
      const jobs=await ctx.readJobs(run.jobs);if(!current())return;
      const noSubject=jobs.some(job=>job.events?.some(row=>row.evidence?.error_code==='subject_not_found'));
      setText(status,noSubject?msg("ui.no_people_detected_draw_a_subject_or_explicitly_start"):msg("ui.subject_detection_value0",{value0:jobs.map(job=>({created:'待执行',submitted:'已提交',running:'识别中',succeeded:'已完成',failed:'未成功',submission_unknown:'提交回执未知，请保留原任务',cancelled:'已取消'})[job.status]||job.status).join('、')}));
      if(jobs.every(job=>job.status==='succeeded')){
        const latest=await ctx.readOptions();if(!current())return;
        state.subjectRun=null;ctx.remember();
        const first=latest.subject_candidates.find(row=>row.job_id===jobs[0].id&&row.source_media_id===source.media_id&&row.source_sha256===source.sha256);
        if(!ctx.hasSelection()&&first)ctx.onSelect(copy(first));else ctx.onRefresh();
      }else if(jobs.some(job=>['created','submitted','running'].includes(job.status)))timer=setTimeout(poll,3000);
    }catch(error){if(current())setText(status,msg("ui.detection_status_could_not_be_loaded_value0_refresh_candidates",{value0:error.message}));}
  }
  poll();return {dispose(){active=false;clearTimeout(timer);}};
}
