import './classic-controls-messages.js';
import {mountPromptAssist} from './prompt-assist.js';
import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
// Each mode fixes a draft; explicit quote confirmation creates the original generation jobs.
import {createRunScopeControls} from './run-scope-controls.js';
import {mountImageControls} from './image-controls.js';
import {mountSubjectSelector} from './subject-selector.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const modeNames={"audio_speech":msg("mode.audio_speech"),"audio_song":msg("mode.audio_song"),"audio":msg("mode.audio"),"image":msg("mode.image"),"text":msg("mode.text"),"single":msg("mode.single"),"first_last":msg("mode.first_last"),"multi":msg("mode.multi"),"omni":msg("mode.omni"),"digital_human":msg("mode.digital_human"),"motion":msg("mode.motion"),"image_angle":msg("mode.image_angle"),"image_lighting":msg("mode.image_lighting"),"image_inpaint":msg("mode.image_inpaint"),"image_watermark":msg("mode.image_watermark"),"image_panorama":msg("mode.image_panorama"),"image_upscale":msg("mode.image_upscale"),"video_depth":msg("mode.video_depth"),"video_upgrade":msg("mode.video_upgrade"),"image_three_view":msg("mode.image_three_view"),"image_face_views":msg("mode.image_face_views"),"image_headshot":msg("mode.image_headshot"),"image_texture":msg("mode.image_texture"),"image_expression":msg("mode.image_expression")};
const roles={operation_source:msg("ui.fixed_source_media"),operation_mask:msg("ui.fixed_edit_mask"),subject_mask:msg("ui.speaking_subject_region"),first_frame:msg("ui.first_frame"),last_frame:msg("ui.last_frame"),reference_image:msg("home.canvas_port_reference_images"),reference_video:msg("home.canvas_port_reference_videos"),reference_audio:msg("home.canvas_port_reference_audios"),portrait:msg("ui.portrait"),speech:msg("ui.driving_audio"),character:msg("ui.character_image"),motion_video:msg("ui.motion_video")};
const gapNames={shot_spec_missing:msg("ui.confirmed_shot_plan_missing"),state_missing:msg("ui.scene_state_evidence_missing"),first_frame_missing:msg("ui.no_usable_first_frame_selected")};
const purposeNames={video_upgrade:msg("ui.upgrade_sample_to_1080p"),image_to_video:msg("ui.image_to_video"),video_clip:msg("ui.shot_video"),text_to_video:msg("ui.text_to_video"),first_frame:msg("ui.first_frame_image"),last_frame:msg("ui.last_frame_image"),image_edit:msg("ui.image_editing"),identity_ref:msg("ui.identity_reference")};
const connectionNames={not_loaded:msg("ui.credentials_not_loaded_in_this_process"),loaded_unverified:msg("ui.credentials_loaded_not_verified_online"),not_connected:msg("ui.execution_route_not_connected"),runtime_unavailable:msg("ui.local_runtime_is_not_ready"),invalid_configuration:msg("ui.configuration_needs_correction")};
const parameterNames={resolution:msg("agent.resolution"),generate_audio:msg("ui.generate_audio_too"),seed:msg("ui.random_seed"),quality:msg("agent.seedance_storyboard_image_quality")};
const clone=value=>JSON.parse(JSON.stringify(value));
const retained={get:k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null');}catch{return null;}},put:(k,v)=>{try{if(v==null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,JSON.stringify(v));}catch{}}};
export function createClassicProduction(root,ctx){
  let epoch=0,scope=null,options=null,mode='single',preview=null,editNo=0,runScope=null,referenceEditor=null,subjectSelector=null;
  const drafts=new Map(),pending=new Map();
  const base=p=>'/api/v1/projects/'+encodeURIComponent(p);
  const session=()=>ctx.session();
  const identity=()=>session().identityId||session().actor||'';
  const alive=(n,s)=>n===epoch&&scope===s&&s.ownerIdentity===identity();
  const key=(s,m)=>[s.ownerIdentity??identity(),s.projectId,s.shotId,m].join(':');
  function remember(e,s=scope,m=mode){retained.put('vsc-classic-draft:'+key(s,m),{document:e.document,saved:e.saved,dirty:e.dirty,rawParams:e.rawParams,lastGeneration:e.lastGeneration,subjectRun:e.subjectRun,subjectModel:e.subjectModel,assist:e.assist,assistSmart:e.assistSmart,assistLanguage:e.assistLanguage});}
  const closeDialogs=()=>{for(const dialog of root.querySelectorAll('dialog'))dialog.close();};
  function button(title,fn,disabled=false){const n=el('button',title);n.type='button';n.disabled=disabled;n.addEventListener('click',async()=>{if(n.disabled)return;n.disabled=true;try{await fn();}catch(error){if(n.isConnected!==false)ctx.notice(error.message);}finally{n.disabled=false;}});return n;}
  function field(form,title,input){const label=el('label',title);bindAttribute(input,'aria-label',title);label.append(input);form.append(label);return input;}
  function newDraft(s,m){return {shot_id:s.shotId,mode:m,model_id:'',purpose:'',prompt:'',duration_ms:5000,width:['image_inpaint','image_watermark'].includes(m)?1024:1080,height:['image_inpaint','image_watermark'].includes(m)?1024:1920,count:1,params:{},references:[],...(options?.modes[m]?.image_tool?{purpose:'image_edit',tool_settings:clone(options.modes[m].tool_defaults)}:{})};}
  function entry(m=mode){const k=key(scope,m);if(!drafts.has(k)){const stored=options.drafts.find(row=>row.document.mode===m);const restored=retained.get('vsc-classic-draft:'+k);drafts.set(k,restored?.document?restored:{document:stored?clone(stored.document):newDraft(scope,m),saved:stored||null,dirty:false});}return drafts.get(k);}
  async function write(action,payload,s,n,m){
    if(!session().actor||(!session().writable&&action!=='favorite'))throw new Error('请先建立可写人工会话');
    const k=key(s,m),signature=JSON.stringify({action,payload});let operation=pending.get(k)||retained.get('vsc-classic-request:'+k);
    if(operation&&operation.signature!==signature)throw new Error('上次写入回执未确认，请先恢复上次请求；当前编辑已保留。');
    if(!operation){operation={signature,action,payload:clone(payload),key:crypto.randomUUID(),revision:session().revision};pending.set(k,operation);retained.put('vsc-classic-request:'+k,operation);}
    try{
      const result=await ctx.api(base(s.projectId)+(action.startsWith('/')?action:'/classic-production/'+action),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:operation.payload,expected_revision:operation.revision,idempotency_key:operation.key,...(action==='generate'?{confirmed:true}:{})})});
      pending.delete(k);retained.put('vsc-classic-request:'+k,null);if(alive(n,s)&&result.revision!=null)ctx.setRevision(result.revision,s.projectId);return result;
    }catch(error){if(error.status>=400&&error.status<500){pending.delete(k);retained.put('vsc-classic-request:'+k,null);}throw error;}
  }
  function render(){
    const s=scope,n=++epoch,m=mode,e=entry(),doc=e.document,definition=options.modes[m];preview=null;
    if(['inpaint','watermark'].includes(definition.image_tool)&&doc.references.some(ref=>ref.role==='reference_image')){doc.references=doc.references.map(ref=>ref.role==='reference_image'?{...ref,role:'operation_source'}:ref);doc.tool_settings=clone(definition.tool_defaults);e.dirty=true;remember(e,s,m);}
    clearTimeout(s.poll);if(globalThis.location?.href){const route=new URL(location.href);route.searchParams.set('kind',definition.modality);route.searchParams.set('mode',m);history.replaceState(null,'',route);}runScope?.dispose();referenceEditor?.suspend();closeDialogs();root.replaceChildren();root.classList.add('classic-production');
    if(m==='video_upgrade')doc.prompt='将固定的原生480p样片升级为1080p，沿用原任务内容。';
    const imageMode=definition.modality==='image',noun=imageMode?'分镜':'视频',nounLabel=msg(imageMode?'classic.storyboard_noun':'classic.video_noun');
    const heading=el('header',null,'classic-heading');
    heading.append(el('h1',msg("ui.all_value0",{value0:nounLabel})));
    const headingActions=el('div',null,'classic-heading-actions');headingActions.append(button(msg("common.route_video_multi_clip"),()=>ctx.navigate('editing',s.episodeId)),button(msg("common.composite_video"),()=>ctx.navigate('editing',s.episodeId)),button(imageMode?msg("pic.batch_upload_storyboard"):msg("common.upload_video"),()=>ctx.navigate('media',s.shotId)));heading.append(headingActions);root.append(heading);
    const shotRail=el('nav',null,'classic-shot-rail');bindAttribute(shotRail,'aria-label',msg("ui.all_value0",{value0:nounLabel}));heading.append(shotRail);
    for(const [index,shot]of s.shots.entries()){const b=button('',()=>load({...s,objectId:shot.id,shotId:shot.id}));b.className='classic-shot';b.title=shot.title||shot.display_code||shot.id;bindAttribute(b,'aria-label',msg("ui.open_value0_value1",{value0:nounLabel,value1:index+1}));b.setAttribute('aria-current',shot.id===s.shotId?'true':'false');b.append(el('span',String(index+1),'classic-shot-number'),el('span',shot.title||shot.display_code||noun+(index+1),'classic-shot-title'));shotRail.append(b);}
    const shotTools=el('details',null,'classic-shot-tools');shotTools.append(el('summary',msg("ui.shot_management")));heading.append(shotTools);
    const pick=el('select');bindAttribute(pick,'aria-label',msg("ui.production_shot"));
    for(const shot of s.shots)pick.append(localizedOption(shot.id,shot.title||shot.display_code||shot.id));
    pick.value=s.shotId;pick.addEventListener('change',()=>load({...s,objectId:pick.value,shotId:pick.value}));shotTools.append(pick);
    const shotName=el('input');bindAttribute(shotName,"placeholder",msg("ui.new_shot_name"));bindAttribute(shotName,'aria-label',msg("ui.new_shot_name_extra_249"));shotTools.append(shotName,button(msg("ui.add_shot_to_current_sequence"),async()=>{const value=await write('shots',{action:'create',parent_id:options.shot.parent_id,title:shotName.value},s,n,m);if(alive(n,s))await load({...s,shotId:value.id,objectId:value.id,shots:null});}));
    const addShot=button('',()=>{shotTools.open=true;shotName.focus();});addShot.className='classic-shot classic-add-shot';addShot.append(el('span','＋'),el('span',msg("ui.add_value0_dynamic_339",{value0:nounLabel})));shotRail.append(addShot);
    for(const[delta,title]of [[-1,msg("ui.move_shot_up")],[1,msg("ui.move_shot_down")]])shotTools.append(button(title,async()=>{const rows=options.sibling_shots||[],ids=rows.map(r=>r.id),index=ids.indexOf(s.shotId),target=index+delta;if(target<0||target>=ids.length)return;[ids[index],ids[target]]=[ids[target],ids[index]];await write('shots',{action:'reorder',parent_id:options.shot.parent_id,shot_ids:ids},s,n,m);if(alive(n,s))await load({...s,shots:null});}));
    const tabs=el('nav',null,'classic-modes');bindAttribute(tabs,'aria-label',msg("ui.production_mode"));
    const modes=Object.entries(options.modes).filter(([,item])=>!item.internal&&item.modality===definition.modality&&(!imageMode||Boolean(item.image_tool)===Boolean(definition.image_tool))),order=['omni','first_last','multi','single','text','digital_human','motion'];modes.sort((a,b)=>(order.indexOf(a[0])<0?99:order.indexOf(a[0]))-(order.indexOf(b[0])<0?99:order.indexOf(b[0])));
    for(const [id,item]of modes){const b=button(modeNames[id]||item.label,()=>{mode=id;render();});b.setAttribute('aria-pressed',String(id===m));tabs.append(b);}
    const body=el('div',null,'classic-layout'),form=el('form',null,'classic-form'),aside=el('aside',null,'classic-results');body.append(form,aside);root.append(body);
    const message=el('p',e.saved?msg("ui.draft_version_value0_value1",{value0:e.saved.version,value1:e.dirty?msg("ui.unsaved_changes"):msg("script-studio.save_4")}):msg("ui.current_mode_is_not_saved"),'classic-status');message.setAttribute('role','status');form.append(el('h2',msg("ui.how_to_generate_value0",{value0:nounLabel})));if(modes.length>1)form.append(tabs);
    if(definition.tool_unavailable)form.append(el('p',definition.tool_unavailable,'classic-blocker'));
    if(definition.unsupported)form.append(el('p',definition.unsupported,'classic-blocker'));
    const modelSection=el('div',null,'classic-model');form.append(modelSection);
    const nativeOperation=['inpaint','watermark'].includes(definition.image_tool)?'inpaint':['panorama','upscale'].includes(definition.image_tool)?definition.image_tool:m==='video_depth'?'depth':m==='video_upgrade'?'draft_upgrade':null;const model=field(modelSection,msg("common.model"),el('select')),models=options.models.filter(row=>row.modality===definition.modality&&(m==='digital_human'?row.capabilities?.subject_mask===true:nativeOperation?(row.capabilities?.[imageMode?'image_operations':'video_operations']||[]).includes(nativeOperation):!(row.capabilities?.image_operations?.length||row.capabilities?.video_operations?.length)));bindAttribute(model,'aria-label',msg("classic_controls.model"));
    model.append(localizedOption('',msg("ui.choose_an_available_model")));
    const modelTitle=row=>row.model_key?.replace(/^grok-imagine-image-/,'Grok Imagine Image ').replace(/^grok-imagine-video-/,'Grok Imagine Video ').replace(/^doubao-seedream-/,'Seedream ').replace(/^doubao-seedance-/,'Seedance ')||msg("ui.no_actual_model_selected");
    for(const row of models){const siblings=models.filter(other=>other.model_key===row.model_key),position=siblings.indexOf(row)+1;model.append(localizedOption(row.id,joinMessages([modelTitle(row),siblings.length>1?joinMessages([' · ',msg('classic_controls.config_choice',{value:position})]):'',!row.enabled?msg("ui.disabled_nested_88"):!row.adapter_available?msg("ui.not_connected_nested_89"):''])));}

    if(!e.saved&&!doc.model_id)doc.model_id=models.find(row=>row.enabled&&row.adapter_available)?.id||'';
    if(doc.model_id&&!models.some(row=>row.id===doc.model_id))model.append(localizedOption(doc.model_id,msg("ui.old_model_version_in_draft_select_again")));model.value=doc.model_id;
    const advanced=el('details',null,'classic-advanced');advanced.append(el('summary',msg("ui.advanced_settings")));
    const purpose=field(advanced,msg("ui.generation_purpose"),el('select')),capabilities=el('div',null,'classic-capabilities');advanced.append(capabilities);
    const promptSection=el('div',null,'classic-prompt');form.append(promptSection);
    const prompt=field(promptSection,m==='digital_human'?msg("ui.character_performance_prompt_up_to_300_characters"):msg("common.prompt"),el('textarea'));bindAttribute(prompt,'aria-label',m==='digital_human'?msg("ui.character_performance_prompt"):msg("ui.current_mode_prompt"));bindAttribute(prompt,"placeholder",m==='digital_human'?msg("ui.describe_the_selected_person_s_expressions_actions_and_performance"):msg("ui.type_to_reference_resources_and_describe_the_picture_and"));prompt.rows=7;prompt.maxLength=m==='digital_human'?300:50000;prompt.value=m==='digital_human'?(doc.performance_prompt||''):doc.prompt;if(m==='video_upgrade'){prompt.readOnly=true;promptSection.append(el('p',msg("ui.keep_the_selected_native_sample_s_content_and_duration"),'hint'));}
    const numeric=el('div',null,'classic-numbers'),numbers={},parameterSummary=el('summary');form.append(numeric);
    const dimensions=definition.modality==='image'?[['width',msg('classic_controls.width'),1],['height',msg('classic_controls.height'),1],['count',msg('classic_controls.count'),1]]:[['duration_ms',msg('classic_controls.duration'),1000],['count',msg('classic_controls.count'),1]];
    for(const [id,title,scale]of dimensions){const input=el('input');input.type='number';input.min=id==='duration_ms'?'0.001':'1';input.step=id==='duration_ms'?'0.001':'1';if(id==='count')input.max='8';input.value=String(doc[id]/scale);field(['width','height'].includes(id)?advanced:numeric,title,input);numbers[id]={input,scale};if(m==='video_upgrade'&&id==='duration_ms')input.readOnly=true;}
    const params=field(advanced,msg("ui.model_parameters_json_follow_the_model_s_declared_schema"),el('textarea'));params.rows=3;params.value=e.rawParams||JSON.stringify(doc.params,null,2);
    const modelFields=el('div',null,'classic-model-fields'),advancedModelFields=el('div');numeric.prepend(modelFields);advanced.append(advancedModelFields);
    const ratio=el('select');field(numeric,msg('classic_controls.ratio'),ratio);
    const updateSummary=()=>{const gcd=(a,b)=>b?gcd(b,a%b):a,factor=gcd(doc.width||1,doc.height||1),row=models.find(r=>r.id===doc.model_id),resolution=doc.params.resolution||row?.default_params?.resolution;setText(parameterSummary,joinMessages([...(imageMode?[resolution||doc.width+' × '+doc.height]:[doc.duration_ms/1000+'s',resolution||'']),doc.width/factor+':'+doc.height/factor,String(doc.count)].filter(Boolean),' · '));};
    ratio.addEventListener('change',()=>{const [w,h]=ratio.value.split('x').map(Number);if(numbers.width){numbers.width.input.value=w;numbers.height.input.value=h;}doc.width=w;doc.height=h;capture();mark();});
    const syncCapabilities=()=>{
      const row=models.find(item=>item.id===model.value),caps=row?.capabilities||{};
      const sizes=Object.keys(row?.default_params?.ratio_map||row?.default_params?.size_map||{}),current=doc.width+'x'+doc.height;if(!sizes.includes(current))sizes.unshift(current);ratio.replaceChildren(...sizes.map(size=>{const [w,h]=size.split('x').map(Number),gcd=(a,b)=>b?gcd(b,a%b):a,d=gcd(w||1,h||1);return localizedOption(size,w/d+':'+h/d+' · '+w+' × '+h);}));ratio.value=current;
      purpose.replaceChildren(localizedOption('',msg("ui.choose_purpose")));for(const p of caps.purposes||[])purpose.append(localizedOption(p,purposeNames[p]||p));const preferred=definition.purpose||(definition.image_tool?'image_edit':imageMode?['first_frame','keyframe','ref'].find(p=>caps.purposes?.includes(p)):m==='text'?['text_to_video','video_clip'].find(p=>caps.purposes?.includes(p)):m==='multi'?['reference_to_video','image_to_video'].find(p=>caps.purposes?.includes(p)):'image_to_video');if(!doc.purpose&&caps.purposes?.includes(preferred))doc.purpose=preferred;purpose.value=doc.purpose;
      capabilities.replaceChildren(el('p',row?joinMessages([row.enabled&&row.adapter_available?msg("ui.execution_route_connected"):msg("ui.draft_saving_only")," · ",connectionNames[row.connection_status]||row.connection_status||msg("ui.credential_status_unknown")]):msg("ui.no_actual_model_selected"),'hint'));
      const limits=[];for(const [k,title]of [['max_duration_ms',msg("ui.maximum_video_milliseconds")],['max_reference_images',msg("ui.maximum_reference_images")],['max_width',msg("ui.maximum_width")],['max_height',msg("ui.maximum_height")]])if(caps[k]!=null)limits.push(title+' '+caps[k]);
      capabilities.append(el('p',limits.join(' · ')||msg("ui.the_model_declares_no_additional_numeric_limit_the_original"),'hint'));
      if(numbers.duration_ms)numbers.duration_ms.input.max=caps.max_duration_ms?String(caps.max_duration_ms/1000):'';
      if(numbers.width)numbers.width.input.max=caps.max_width||'';if(numbers.height)numbers.height.input.max=caps.max_height||'';
      const d=el('details');d.append(el('summary',msg("classic_controls.config")),el('pre',JSON.stringify({configuration:row?.name,version:row?.model_version,model:row?.model_key,capabilities:caps,default_params:row?.default_params||{}},null,2)));capabilities.append(d);
      modelFields.replaceChildren();advancedModelFields.replaceChildren();
      for(const [name,value]of Object.entries(m==='video_upgrade'?{}:row?.default_params||{})){
        if(!['string','number','boolean'].includes(typeof value))continue;
        const declared=caps.parameters?.[name],choices=Array.isArray(declared?.enum)?declared.enum:null;
        const input=el(choices?'select':'input');
        if(choices){for(const choice of choices)input.append(localizedOption(String(choice),String(choice)));input.value=String(doc.params[name]??value);}
        else if(typeof value==='boolean'){input.type='checkbox';input.checked=doc.params[name]??value;}
        else{input.type=typeof value==='number'?'number':'text';input.value=String(doc.params[name]??value);if(typeof value==='number')input.step='any';}
        field(parameterNames[name]?modelFields:advancedModelFields,parameterNames[name]||msg("ui.model_parameter_value0",{value0:name}),input);
        input.addEventListener('input',()=>{try{const current=JSON.parse(params.value);current[name]=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;params.value=JSON.stringify(current,null,2);capture();mark();}catch{ctx.notice(msg("ui.correct_the_model_parameter_json_first_current_inputs_are"));}});
      }
      updateSummary();
    };syncCapabilities();
    const toolFields=el('section');advanced.append(toolFields);
    if(definition.image_tool){doc.tool_settings||=clone(definition.tool_defaults);toolFields.append(el('h3',msg("ui.fixed_image_tool_parameters")));if(['angle','lighting'].includes(definition.image_tool)){const controls=el('section');promptSection.append(controls);mountImageControls(controls,{tool:definition.image_tool,settings:doc.tool_settings,defaults:definition.tool_defaults,onChange:()=>mark(),isCurrent:()=>alive(n,s)});}for(const[key,value]of Object.entries(definition.tool_defaults)){
      if(['angle','lighting','inpaint','watermark'].includes(definition.image_tool))continue;
      const choices=key==='preset'?['custom','fisheye','tilt','front_high','front_low','top','back']:key==='direction'?['front','back','left','right','top','bottom']:key==='view'?['front','perspective']:key==='target'?['4k','8k']:null;
      const input=el(choices?'select':'input');if(choices){for(const v of choices)input.append(localizedOption(v,v));input.value=doc.tool_settings[key];}else{input.type=typeof value==='boolean'?'checkbox':typeof value==='number'?'number':key==='color'?'color':'text';if(input.type==='checkbox')input.checked=doc.tool_settings[key];else input.value=doc.tool_settings[key];if(typeof value==='number')input.step='any';}
      field(toolFields,({layout:'视图布局',framing:'取景',strength:'调整程度',expression:'表情',preset:'角度预设',yaw:'水平环绕角度',pitch:'垂直俯仰角度',roll:'倾斜角度',zoom:'景别缩放',include_instructions:'把角度说明加入模型提示词',view:'光源视图',direction:'主光方向',intensity:'光源亮度',color:'光源颜色',cone:'光锥角度',rim:'开启轮廓光',mask_media_id:'已登记遮罩媒体ID',mask_sha256:'固定遮罩摘要（保存时核验）',projection:'全景投影',target:'超分规格',rights_confirmed:'确认有权处理此来源'})[key]||key,input);
      input.addEventListener('input',()=>{doc.tool_settings[key]=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;mark();});
    }if(!['angle','lighting','inpaint','watermark'].includes(definition.image_tool))toolFields.append(button(msg("ui.reset_tool_parameters"),()=>{doc.tool_settings=clone(definition.tool_defaults);mark();render();}));if(['inpaint','watermark'].includes(definition.image_tool))toolFields.append(el('p',msg("ui.open_the_source_image_in_the_mask_editor_paint")));}
    if(definition.image_tool==='watermark'){const rights=el('input');rights.type='checkbox';rights.checked=doc.tool_settings.rights_confirmed;field(promptSection,msg("ui.i_have_the_right_to_remove_this_source_watermark"),rights);rights.addEventListener('change',()=>{doc.tool_settings.rights_confirmed=rights.checked;mark();});}
    if(definition.image_tool==='panorama')promptSection.append(el('p',msg("ui.native_panoramas_use_a_vsc_2_1_equirectangular_preview"),'hint'));
    if(definition.image_tool==='upscale')promptSection.append(el('p',msg("ui.native_ai_upscaling_4k_8k_means_a_long_edge"),'hint'));
    const references=el('section' ,null,'classic-references');form.append(references);references.dataset.mode=m;
    const report=el('div',null,'classic-report');
    const propose=button(msg("ui.confirm_quote_and_generate"),async()=>{
      if(!preview||e.dirty)throw new Error('请先保存并预览当前草稿');
      const request=preview.request,sha=preview.value.preview_sha256;propose.disabled=true;
      try{const result=await write('generate',{request,preview_sha256:sha},s,n,m);if(alive(n,s)){e.lastGeneration=result;remember(e,s,m);preview=null;report.replaceChildren(el('p',msg("ui.generation_task_registered_results_will_appear_in_this_shot")));await loadCandidates();}}
      finally{if(alive(n,s))propose.disabled=!preview||e.dirty;}
    },true);
    const mark=()=>{e.dirty=true;editNo++;preview=null;propose.disabled=true;report.replaceChildren();setText(message,msg("ui.you_have_unsaved_changes_refresh_can_restore_the_current"));remember(e,s,m);};
    if(!imageMode&&!nativeOperation&&m!=='digital_human'){const sample=el('input');sample.type='checkbox';sample.checked=doc.draft===true;const selected=models.find(row=>row.id===model.value);sample.disabled=!sample.checked&&!(selected?.capabilities?.video_draft===true&&selected?.default_params?.resolution==='480p');field(promptSection,msg("ui.generate_a_native_480p_sample_first"),sample);promptSection.append(el('p',msg("ui.upgrade_the_original_task_to_1080p_within_its_validity"),'hint'));sample.addEventListener('change',()=>{doc.draft=sample.checked;mark();});model.addEventListener('change',()=>{const chosen=models.find(row=>row.id===model.value);sample.disabled=!sample.checked&&!(chosen?.capabilities?.video_draft===true&&chosen?.default_params?.resolution==='480p');});}
    if(m==='digital_human'){
      doc.count=1;numbers.count.input.value='1';numbers.count.input.readOnly=true;numbers.duration_ms.input.readOnly=true;
      const resolution=field(promptSection,msg("ui.digital_human_resolution"),el('select'));for(const value of ['720p','1080p'])resolution.append(localizedOption(value,value));resolution.value=doc.params.resolution||'1080p';
      const turbo=field(promptSection,msg("ui.accelerated_generation_may_affect_quality"),el('input'));turbo.type='checkbox';turbo.checked=doc.params.turbo_mode===true;
      const update=()=>{doc.params={resolution:resolution.value,turbo_mode:turbo.checked};params.value=JSON.stringify(doc.params,null,2);mark();};resolution.addEventListener('change',update);turbo.addEventListener('change',update);
      promptSection.append(el('p',msg("ui.audio_must_be_shorter_than_30_seconds_for_1080p"),'hint'));
    }
    function clearSubject(){if(m!=='digital_human')return;doc.subject_selection=null;doc.references=doc.references.filter(r=>r.role!=='subject_mask');subjectSelector?.dispose();e.activeEditor=null;referenceEditor?.suspend();}
    function chooseSubject(value){const portrait=doc.references.find(r=>r.role==='portrait');if(!portrait||portrait.media_id!==value.source_media_id||portrait.sha256!==value.source_sha256)throw new Error('原图已经改变，请重新选择当前图像的主体。');doc.subject_selection=clone(value);doc.references=doc.references.filter(r=>r.role!=='subject_mask');doc.references.push({role:'subject_mask',media_id:value.mask_media_id,sha256:value.mask_sha256});mark();renderReferences();}
    function openUpload(role,type){
      const owner=session().identityId||session().actor||'',uploadKey=owner+':'+role;e.uploads||=new Map();
      if(!e.uploads.has(uploadKey))e.uploads.set(uploadKey,{file:null,source:'',purposes:role,staged:null,request:null,registered:null,busy:false});
      const buffer=e.uploads.get(uploadKey),dialog=el('dialog',null,'classic-upload-dialog'),form=el('form'),title=el('header'),status=el('p',null,'classic-upload-status');status.setAttribute('role','status');bindAttribute(dialog,'aria-label',msg("ui.upload_value0",{value0:roles[role]}));
      const current=()=>alive(n,s)&&(session().identityId||session().actor||'')===owner&&dialog.open&&dialog.isConnected;
      title.append(el('h2',msg("ui.upload_value0",{value0:roles[role]})),button(msg("common.close"),()=>dialog.close()));dialog.append(title,form);root.append(dialog);
      const file=field(form,msg("ui.choose_local_file"),el('input'));file.type='file';file.accept=type+'/*';const selected=el('p',buffer.file?.name||msg("ui.no_file_selected"),'hint');form.append(selected);
      const source=field(form,msg("ui.source_and_evidence_description"),el('textarea'));source.rows=3;source.value=buffer.source;bindAttribute(source,"placeholder",msg("ui.who_supplied_or_created_it_original_source"));
      const purposes=field(form,msg("ui.applicable_purposes"),el('input'));purposes.value=buffer.purposes;
      form.append(el('p',msg("ui.registered_with_rights_pending_confirmation_adding_a_reference_does"),'hint'),status);
      const controls=el('div',null,'classic-upload-actions'),submit=el('button',buffer.registered?msg("ui.recover_media_readback"):buffer.request?msg("ui.recover_upload_registration"):msg("ui.upload_and_add_reference"));submit.type='submit';submit.className='classic-primary';controls.append(button(msg("common.cancel"),()=>dialog.close()),submit);form.append(controls);
      const capture=()=>{buffer.source=source.value;buffer.purposes=purposes.value;};source.addEventListener('input',capture);purposes.addEventListener('input',capture);
      file.addEventListener('change',()=>{if(buffer.request||buffer.registered)return;if(file.files?.[0]){buffer.file=file.files[0];buffer.staged=null;setText(selected,buffer.file.name);}});
      function lock(){const fixed=buffer.busy||Boolean(buffer.request||buffer.registered);file.disabled=source.disabled=purposes.disabled=fixed;submit.disabled=buffer.busy||!session().actor||!session().writable;}
      buffer.listeners||=new Set();buffer.listeners.add(lock);lock();dialog.addEventListener('close',()=>{capture();buffer.listeners.delete(lock);dialog.remove();});
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(buffer.busy)return;capture();
        if(!session().actor||!session().writable){setText(status,msg("ui.this_session_is_read_only_obtain_project_editing_access"));return;}
        if(!buffer.file){setText(status,msg("ui.choose_a_local_file"));return;}if(!buffer.source.trim()){setText(status,msg("ui.enter_the_source_and_evidence_description"));source.focus();return;}
        buffer.busy=true;lock();setText(status,buffer.registered?msg("ui.recovering_media_readback"):msg("ui.uploading_and_registering"));
        try{
          if(!buffer.staged)buffer.staged=await ctx.api(base(s.projectId)+'/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(buffer.file.name),'X-CSRF-Token':session().csrf},body:buffer.file});
          if(!current())return;
          if(!buffer.registered){
            if(!buffer.request)buffer.request={payload:{staged_upload:buffer.staged.staged_upload,name:buffer.file.name,rights:'unknown',rights_scope:{purposes:buffer.purposes.split(',').map(v=>v.trim()).filter(Boolean)},source:{kind:'user_upload',content:buffer.source}},expected_revision:session().revision,idempotency_key:crypto.randomUUID()};
            try{buffer.registered=await ctx.api(base(s.projectId)+'/media',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(buffer.request)});buffer.request=null;}
            catch(error){if(error.status>=400&&error.status<500)buffer.request=null;throw error;}
          }
          if(!current())return;
          // Registration and readback are separate: retrying a failed read never registers twice.
          const [media,latest]=await Promise.all([ctx.api(base(s.projectId)+'/media/'+encodeURIComponent(buffer.registered.id)),ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId))]);
          if(!current())return;ctx.setRevision(latest.revision,s.projectId);
          if(media.modality!==type)throw new Error('已登记文件不是此参考槽需要的'+({image:'图片',video:'视频',audio:'音频'})[type]+'；请在素材库检查后重新选择。');
          if(!options.media.some(row=>row.id===media.id))options.media.push(media);
          if(role==='portrait')clearSubject();
          if(['inpaint','watermark'].includes(definition.image_tool)){doc.references=[];doc.tool_settings=clone(definition.tool_defaults);}
          if(!['reference_image','reference_video','reference_audio'].includes(role))doc.references=doc.references.filter(ref=>ref.role!==role);
          if(!doc.references.some(ref=>ref.role===role&&ref.media_id===media.id))doc.references.push({role,media_id:media.id,sha256:media.sha256||buffer.registered.sha256});
          mark();renderReferences();e.uploads.delete(uploadKey);dialog.close();ctx.notice(msg("ui.media_registered_and_added_to_current_references_rights_remain"));
        }catch(error){if(current()){setText(status,msg("ui.value0_file_and_inputs_preserved_recover_the_same_operation",{value0:error.message}));setText(submit,buffer.registered?msg("ui.recover_media_readback"):buffer.request?msg("ui.recover_upload_registration"):msg("ui.retry_upload_and_add_reference"));}}
        finally{buffer.busy=false;for(const update of buffer.listeners)update();}
      });dialog.showModal();
    }
    function renderReferences(){
      subjectSelector?.dispose();
      references.replaceChildren();advanced.querySelector('.classic-reference-manual')?.remove();if(m==='digital_human'){const speech=doc.references.find(r=>r.role==='speech'),audio=options.media.find(row=>row.id===speech?.media_id);if(audio?.duration_ms){doc.duration_ms=audio.duration_ms;numbers.duration_ms.input.value=String(audio.duration_ms/1000);}}
      if(!Object.keys(definition.slots).length)return;
      if(['inpaint','watermark'].includes(definition.image_tool))references.append(el('p',doc.tool_settings.mask_export_id?msg("ui.source_image_and_separate_edit_mask_are_fixed_draw"):msg("ui.choose_a_source_image_then_paint_the_modification_area")));
      if(m!=='first_last')references.append(el('h3',imageMode?msg("asset.reference"):msg("ui.reference")));
      const slots=el('div',null,'classic-reference-slots');references.append(slots);
      for(const [role,type]of Object.entries(definition.slots)){
        const box=el('div',null,'classic-reference-slot');
        if(m==='digital_human'&&role==='portrait')box.append(el('h3',msg("ui.1_choose_a_digital_human_image")));
        if(m==='digital_human'&&role==='speech')box.append(el('h3',msg("ui.3_add_driving_audio")));
        if(role==='subject_mask'){
          const source=doc.references.find(r=>r.role==='portrait');
          const readOptions=async()=>{const value=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+s.shotId);if(alive(n,s)){options=value;ctx.setRevision(value.revision,s.projectId);}return value;};
          subjectSelector=mountSubjectSelector(box,{source,shotId:s.shotId,state:e,selection:doc.subject_selection,candidates:options.subject_candidates||[],models:options.models,writable:session().writable&&Boolean(session().actor),isCurrent:()=>alive(n,s),sourceIsCurrent:original=>{const now=doc.references.find(r=>r.role==='portrait');return now?.media_id===original?.media_id&&now?.sha256===original?.sha256;},hasSelection:()=>Boolean(doc.subject_selection),remember:()=>remember(e,s,m),notice:ctx.notice,mediaUrl:id=>base(s.projectId)+'/media/'+id+'/content',onDraw:()=>openEditor(options.media.find(row=>row.id===source.media_id)||{id:source.media_id}),onSelect:chooseSubject,onRefresh:renderReferences,readOptions,write:(action,payload)=>write(action,payload,s,n,'image_subject_detect'),policy:id=>runScope.apply({draft_version_id:id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:1,max_repair_rounds:0}}),quote:request=>ctx.api(base(s.projectId)+'/classic-production/quote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})}),readJobs:jobs=>Promise.all(jobs.map(job=>ctx.api(base(s.projectId)+'/production-platform/jobs/'+job.id))),recover:async()=>{const k=key(s,'image_subject_detect'),op=pending.get(k)||retained.get('vsc-classic-request:'+k);if(!op)return null;let original=op.payload.document?.references?.[0];if(op.action==='generate'){const draft=await ctx.api(base(s.projectId)+'/artifacts/'+op.payload.request.draft_version_id);const document=typeof draft.document==='string'?JSON.parse(draft.document):draft.document;original=document.references[0];}const value=await write(op.action,op.payload,s,n,'image_subject_detect');return {action:op.action,value,source:original};}});
          if(doc.subject_selection){const selected=el('img');selected.src=base(s.projectId)+'/media/'+doc.subject_selection.mask_media_id+'/content';bindAttribute(selected,"alt",msg("ui.current_speaking_region"));selected.style.maxWidth='160px';box.append(selected,button(msg("ui.clear_subject_selection"),()=>{clearSubject();mark();renderReferences();}));}slots.append(box);continue;
        }
        for(const [index,ref]of doc.references.entries()){if(ref.role!==role)continue;const media=options.media.find(row=>row.id===ref.media_id),thumb=el('figure',null,'classic-reference-thumb');
          const visual=el(type==='image'?'img':type==='video'?'video':'audio');visual.src=base(s.projectId)+'/media/'+encodeURIComponent(ref.media_id)+'/content';if(type==='image')bindAttribute(visual,"alt",media?.name||roles[role]);else{visual.controls=true;visual.preload='metadata';}thumb.append(visual,el('figcaption',media?.name||roles[role]));
          const remove=button('×',()=>{const removed=doc.references.splice(index,1);if(role==='portrait')clearSubject();if(['inpaint','watermark'].includes(definition.image_tool)){doc.references=doc.references.filter(r=>r.role!=='operation_mask');doc.tool_settings=clone(definition.tool_defaults);}if(media?.modality==='video'){removed.push(...doc.references.filter(r=>r.annotation_source_id===ref.media_id));doc.references=doc.references.filter(r=>r.annotation_source_id!==ref.media_id);}for(const item of removed){if(item.prompt_mention)doc.prompt=doc.prompt.split(item.prompt_mention).join('');doc.prompt=doc.prompt.split('[[ref:'+item.media_id+']]').join('');}doc.prompt=doc.prompt.trim();if(m!=='digital_human')prompt.value=doc.prompt;mark();renderReferences();});bindAttribute(remove,'aria-label',msg("ui.remove_value0",{value0:roles[role]||msg("ui.this_reference")}));thumb.append(remove);if(role==='operation_source'&&imageMode)thumb.append(button(msg("ui.paint_modification_area"),()=>openEditor(media||{id:ref.media_id})));box.append(thumb);}
        if(role==='operation_mask'){slots.append(box);continue;}
        const chooser=el('details',null,'classic-reference-chooser'),toggle=el('summary');toggle.append(el('span','＋','classic-plus'),el('span',m==='first_last'?msg("ui.add_value0_image",{value0:roles[role]}):role==='reference_image'?msg("common.reference_media_add"):roles[role]));chooser.append(toggle);
        const menu=el('div',null,'classic-reference-menu');menu.append(button(msg("common.local_upload"),()=>{chooser.open=false;openUpload(role,type);}),el('strong',msg("agent.import_asset")));chooser.append(menu);
        const select=el('select');bindAttribute(select,'aria-label',roles[role]||role);select.append(localizedOption('',msg("ui.choose_registered_value0",{value0:type})));
        for(const media of options.media.filter(row=>row.modality===type))select.append(localizedOption(media.id,media.name||media.id));
        menu.append(select,button(msg("ui.add_value0",{value0:roles[role]||role}),()=>{
          if(!select.value)return;const media=options.media.find(row=>row.id===select.value);
          if(doc.references.some(ref=>ref.role===role&&ref.media_id===media.id))return;
          if(role==='portrait')clearSubject();
          if(!['reference_image','reference_video','reference_audio'].includes(role))doc.references=doc.references.filter(ref=>ref.role!==role);
          if(['inpaint','watermark'].includes(definition.image_tool)){doc.references=[];doc.tool_settings=clone(definition.tool_defaults);}
          doc.references.push({role,media_id:media.id,sha256:media.sha256});mark();renderReferences();
        }));box.append(chooser);slots.append(box);
      }
      if(m==='omni'){
        const boxes=[...slots.children],menu=boxes[0]?.querySelector('.classic-reference-menu');
        for(const [index,box]of boxes.entries()){if(!index)continue;const chooser=box.querySelector('.classic-reference-chooser'),other=chooser?.querySelector('.classic-reference-menu');if(other&&menu){menu.append(el('strong',roles[Object.keys(definition.slots)[index]]));for(const child of [...other.children])if(child.tagName==='SELECT'||child.tagName==='BUTTON')menu.append(child);chooser.remove();if(!box.children.length)box.remove();}}
      }
      if(m==='first_last')references.append(button(msg("ui.swap_first_and_last_frames"),()=>{if(!doc.references.some(r=>r.role==='first_frame')||!doc.references.some(r=>r.role==='last_frame'))throw new Error('交换前请添加首帧和尾帧');for(const ref of doc.references)ref.role=ref.role==='first_frame'?'last_frame':'first_frame';mark();renderReferences();}));
      if(options.media_total>options.media.length)references.append(el('p',msg("ui.showing_the_first_value0_media_items_locate_earlier_media",{value0:options.media.length}),'hint'));
      if(Object.keys(definition.slots).length&&!['inpaint','watermark'].includes(definition.image_tool)&&m!=='digital_human'){
        const manual=el('input');bindAttribute(manual,"placeholder",msg("ui.registered_media_id"));bindAttribute(manual,'aria-label',msg("ui.more_fixed_media_ids"));
        const role=el('select');for(const r of Object.keys(definition.slots))role.append(localizedOption(r,roles[r]||r));
        const manualDetails=el('details',null,'classic-reference-manual');manualDetails.append(el('summary',msg("ui.add_by_media_number")),manual,role,button(msg("ui.add_reference_by_id"),()=>{if(!manual.value.trim())return;doc.references.push({role:role.value,media_id:manual.value.trim()});mark();renderReferences();}));advanced.append(manualDetails);
      }
    }renderReferences();
    const editorHost=el('section');editorHost.hidden=true;form.append(editorHost);e.referenceBuffers||=new Map();
    async function openEditor(media,saved=null,fresh=false){const editorToken={};e.activeEditor=editorToken;referenceEditor?.suspend();const bufferKey=fresh?media.id+':'+crypto.randomUUID():saved?.document.edit.id||media.id;let buffer=e.referenceBuffers.get(bufferKey);if(!buffer){buffer={document:saved?clone(saved.document.edit):null,saved:saved||null,dirty:!saved};e.referenceBuffers.set(bufferKey,buffer);}editorHost.hidden=false;const module=await import('./reference-editor.js');if(!alive(n,s)||e.activeEditor!==editorToken)return;const editor=await module.createReferenceEditor(editorHost,{api:ctx.api,session:ctx.session,project:s.projectId,shot:s.shotId,mode:m,media,buffer,onNew:()=>openEditor(media,null,true),notice:ctx.notice,setRevision:ctx.setRevision,isCurrent:()=>alive(n,s)&&e.activeEditor===editorToken,onSubject:m==='digital_human'?item=>{if(!alive(n,s)||e.activeEditor!==editorToken)return;chooseSubject({origin:'manual',source_media_id:item.source_media_id,source_sha256:item.source_sha256,mask_media_id:item.media_id,mask_sha256:item.sha256,export_id:item.export_id});editorHost.hidden=true;ctx.notice(msg("ui.hand_drawn_speaking_subject_fixed_for_the_current_source"));}:null,onMask:['inpaint','watermark'].includes(definition.image_tool)?item=>{if(!alive(n,s))return;doc.references=[{role:'operation_source',media_id:item.source_media_id,sha256:item.source_sha256},{role:'operation_mask',media_id:item.media_id,sha256:item.sha256}];doc.tool_settings={...doc.tool_settings,mask_media_id:item.media_id,mask_sha256:item.sha256,mask_export_id:item.export_id};if(buffer.document.description){doc.prompt=buffer.document.description;prompt.value=doc.prompt;}mark();renderReferences();editorHost.hidden=true;ctx.notice(msg("ui.source_image_and_modification_area_fixed_enter_instructions_then"));}:null,onAdd:item=>{if(!alive(n,s))return;const role=definition.slots.reference_image?'reference_image':Object.entries(definition.slots).find(([,kind])=>kind==='image')?.[0];if(!role)return ctx.notice(msg("ui.current_mode_has_no_image_references_switch_to_image"));if(!['reference_image'].includes(role))doc.references=doc.references.filter(r=>r.role!==role);if(!doc.references.some(r=>r.media_id===item.media_id)){const mention='[[ref:'+item.media_id+']] '+(item.source_modality==='video'?item.time_ms+'ms 视频帧标注':'图像标注')+'：'+buffer.document.description;doc.references.push({role,media_id:item.media_id,sha256:item.sha256,annotation_id:item.annotation_id,annotation_source_id:item.annotation_source_id,prompt_mention:mention});if(item.source_modality==='video'&&definition.slots.reference_video&&!doc.references.some(r=>r.media_id===item.annotation_source_id)){const source=options.media.find(r=>r.id===item.annotation_source_id);doc.references.push({role:'reference_video',media_id:source.id,sha256:source.sha256});}doc.prompt+=(doc.prompt?'\n':'')+mention;prompt.value=doc.prompt;options.media.push({id:item.media_id,sha256:item.sha256,modality:'image',name:'固定标注图'});mark();renderReferences();}}});if(alive(n,s)&&e.activeEditor===editorToken)referenceEditor=editor;else editor.suspend();}
    const editSource=el('select');bindAttribute(editSource,'aria-label',msg("ui.image_or_video_annotation_source"));editSource.append(localizedOption('',msg("ui.choose_an_explicit_source_media_item")));for(const media of options.media.filter(r=>['image','video'].includes(r.modality)))editSource.append(localizedOption(media.id,media.name||media.id));advanced.append(editSource,button(msg("ui.open_image_or_video_frame_editor"),()=>{const source=options.media.find(r=>r.id===editSource.value);if(!source)throw new Error('先选择固定源媒体');return openEditor(source);}));
    for(const saved of options.reference_edits||[]){if(saved.document.mode!==m)continue;const source=options.media.find(r=>r.id===saved.document.edit.source_media_id)||{id:saved.document.edit.source_media_id};advanced.append(button(msg("ui.continue_annotation_at_value0_ms_v_value1",{value0:saved.document.edit.time_ms,value1:saved.version}),()=>openEditor(source,saved)));}

    function capture(){
      doc.model_id=model.value;doc.purpose=purpose.value;if(m==='digital_human')doc.performance_prompt=prompt.value;else doc.prompt=prompt.value;
      for(const [id,{input,scale}]of Object.entries(numbers))doc[id]=Math.round(Number(input.value)*scale);
      try{doc.params=JSON.parse(params.value);e.paramsError=null;}catch{e.paramsError='模型参数不是有效 JSON，当前文本已保留。';}e.rawParams=params.value;updateSummary();assistController?.refresh();
    }
    let assistController=null;
    form.addEventListener('input',event=>{if(event.target===model||bounds.contains(event.target)||references.contains(event.target)||promptSection.querySelector('.classic-prompt-tools')?.contains(event.target))return;capture();mark();});
    model.addEventListener('change',()=>{doc.model_id=model.value;doc.purpose='';syncCapabilities();capture();mark();});purpose.addEventListener('change',()=>{capture();mark();});
    const save=el('button',msg("ui.save_current_mode"));save.type='submit';save.disabled=!session().writable||!session().actor;
    async function saveDraft(){
      capture();if(e.paramsError)throw new Error(e.paramsError);
      const submitted=clone(doc),version=editNo;save.disabled=true;
      try{
        const result=await write('drafts',{document:submitted,base_draft_id:e.saved?.id||null},s,n,m);
        e.saved={...result,document:submitted};if(version===editNo)e.dirty=false;remember(e,s,m);
        if(alive(n,s))setText(message,e.dirty?msg("ui.draft_saved_later_edits_are_still_unsaved"):msg("ui.current_mode_saved"));
      }catch(error){throw new Error(error.message+'；输入已保留。');}
      finally{if(alive(n,s))save.disabled=false;}
    }
    if(m!=='video_upgrade')assistController=mountPromptAssist(promptSection,{state:e,saveDraft,getDraft:()=>e,write:request=>write('prompt-assist',request,s,n,m),read:id=>ctx.api(base(s.projectId)+'/classic-production/prompt-assist/'+encodeURIComponent(id)),isCurrent:()=>alive(n,s),remember:()=>remember(e,s,m),onApply:text=>{if(text.length>prompt.maxLength)throw new Error('建议超过当前模式允许的提示词长度');prompt.value=text;capture();mark();},writable:session().writable&&Boolean(session().actor),notice:ctx.notice});
    form.addEventListener('submit',async event=>{event.preventDefault();try{await saveDraft();}catch(error){if(alive(n,s))ctx.notice(error.message);}});
    const due=el('input'),stop=el('input'),attempts=el('input');due.type=stop.type='datetime-local';attempts.type='number';attempts.min='1';attempts.max='20';attempts.value='2';
    const date=minutes=>{const d=new Date(Date.now()+minutes*60000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};due.value=date(45);stop.value=date(60);
    const bounds=el('details');bounds.append(el('summary',msg("ui.execution_scope_and_deadline")));field(bounds,msg("ui.first_draft_target_time"),due);field(bounds,msg("ui.stop_adding_tasks_at"),stop);field(bounds,msg("ui.maximum_attempts_for_this_purpose"),attempts);advanced.append(bounds);
    runScope=createRunScopeControls(bounds,{api:ctx.api,session:ctx.session,projectId:s.projectId,onChange:()=>{editNo++;preview=null;propose.disabled=true;}});
    for(const input of [due,stop,attempts])input.addEventListener('input',()=>{editNo++;preview=null;propose.disabled=true;});
    const check=button(msg("ui.preview_fixed_inputs_and_usage"),async()=>{
      if(e.dirty||!e.saved)await saveDraft();if(!alive(n,s))return;if(e.dirty)throw new Error('保存期间有新修改，请重新预览。');
      const version=editNo,request=runScope.apply({draft_version_id:e.saved.id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(attempts.value),max_repair_rounds:1}});check.disabled=true;
      try{
        const value=await ctx.api(base(s.projectId)+'/classic-production/quote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});
        if(!alive(n,s)||version!==editNo)return;ctx.setRevision(value.revision,s.projectId);
        report.replaceChildren(el('h3',value.ready?msg("ui.confirm_generation_inputs_and_quote"):msg("ui.gaps_to_resolve")));
        for(const gap of value.gaps||[])report.append(el('p',gap.message||gapNames[gap.code]||gap.code));
        if(value.ready){preview={request,value};report.append(el('p',msg("ui.native_usage_value0",{value0:JSON.stringify(value.generation_quote.native_units)})),el('p',value.generation_quote.all_prices_known?msg("ui.estimated_amount_value0",{value0:JSON.stringify(value.generation_quote.known_subtotals)}):msg("ui.amount_unknown_this_does_not_mean_free_more_335")));if(value.commerce_quote?.enabled){const charge=value.commerce_quote.commerce_charge;report.append(el('p',msg("ui.commercial_allowance_cap_value0_value1",{value0:Object.values(charge.max_credits_by_operation).reduce((a,b)=>a+b,0),value1:charge.account_actor||msg("ui.shared_project_budget")})));}propose.disabled=false;}
      }catch(error){if(alive(n,s))ctx.notice(error.message);}
      finally{if(alive(n,s))check.disabled=false;}
    },!session().writable||!session().actor);
    const recover=button(msg("ui.recover_previous_request"),async()=>{
      const operation=pending.get(key(s,m))||retained.get('vsc-classic-request:'+key(s,m));if(!operation){ctx.notice(msg("ui.no_request_needs_recovery_in_the_current_mode"));return;}
      const result=await write(operation.action,operation.payload,s,n,m);
      if(operation.action==='prompt-assist'&&e.assist){e.assist.value=result;remember(e,s,m);}
      if(operation.action==='drafts'){e.saved={...result,document:operation.payload.document};e.dirty=JSON.stringify(e.document)!==JSON.stringify(operation.payload.document);}
      if(alive(n,s)){if(operation.action==='generate'){e.lastGeneration=result;remember(e,s,m);}render();}
    });
    const refresh=button(msg("ui.reload_version_and_preserve_inputs"),async()=>{
      const value=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId));if(!alive(n,s))return;
      options=value;ctx.setRevision(value.revision,s.projectId);
      for(const item of value.drafts){const retained=drafts.get(key(s,item.document.mode));if(retained){retained.saved=item;retained.dirty=JSON.stringify(retained.document)!==JSON.stringify(item.document);}}render();
    });
    advanced.append(save,recover,refresh,message);
    const parameters=el('details',null,'classic-parameters');parameters.append(parameterSummary,numeric);bindAttribute(parameterSummary,'aria-label',msg('classic_controls.parameters'));
    const actions=el('div',null,'classic-actions');check.className='classic-primary';setText(check,msg('classic_controls.generate'));bindAttribute(check,'aria-label',msg('classic_controls.generate'));bindAttribute(check,'title',msg('classic_controls.quote_hint'));propose.className='classic-propose';
    actions.append(parameters,check);form.append(advanced,actions,propose,report);
    // Keep visual order close to the source UI while preserving the original save/preview boundary.
    if(m==='first_last')form.prepend(references);else modelSection.append(references);
    const resultHeader=el('header',null,'classic-result-header'),count=el('span',msg("ui.0_results"),'hint');resultHeader.append(el('h2',msg("common.generate_results")),count,button(msg("ui.candidates_and_review"),()=>ctx.navigate('candidates',s.shotId)));aside.append(resultHeader);
    const candidateGrid=el('div',null,'classic-candidate-grid'),paging=el('div',null,'classic-candidate-paging');aside.append(candidateGrid,paging);let offset=0,candidateRequest=0,filterKind='all';
    const filters=el('nav',null,'classic-result-filters');bindAttribute(filters,'aria-label',msg('classic_controls.result_filter'));for(const kind of ['all','favorites','local']){const b=button(msg('classic_controls.'+kind),()=>{filterKind=kind;offset=0;for(const item of filters.children)item.setAttribute('aria-pressed',String(item===b));return loadCandidates();});b.setAttribute('aria-pressed',String(kind==='all'));if(kind==='local')bindAttribute(b,'title',msg('classic_controls.local_hint'));filters.append(b);}aside.replaceChildren(resultHeader,filters,candidateGrid,paging);
    async function loadCandidates(){
      clearTimeout(s.poll);const requestNo=++candidateRequest;
      try{const value=await ctx.api(base(s.projectId)+'/working-candidates?'+new URLSearchParams({shot_id:s.shotId,output_kind:definition.modality,offset:String(offset),limit:'24',filter_kind:filterKind}));if(!alive(n,s)||requestNo!==candidateRequest)return;
        if(value.revision!=null)ctx.setRevision(value.revision,s.projectId);candidateGrid.replaceChildren();setText(count,msg("ui.value0_results",{value0:value.total}));
        for(const row of value.items||[]){const box=el('article',null,'classic-candidate'),visual=el(imageMode?'img':'video');visual.src=base(s.projectId)+'/media/'+encodeURIComponent(row.media_id)+'/content';if(imageMode)bindAttribute(visual,"alt",row.name||msg("ui.storyboard_candidates"));else{visual.controls=true;visual.preload='metadata';}box.append(visual,el('p',(row.selected?'已选取 · ':'')+(row.name||'镜头候选')));
          async function choose(clear=false,trim=null){let candidate=row.candidate_id;if(!clear&&!candidate){const created=await write('/binding-candidates',{target_object_id:s.shotId,media_id:row.media_id,role:imageMode?'first_frame':'video_take',slot_key:'workbench'},s,n,m);candidate=created.candidate_id||created.id;row.candidate_id=candidate;}
            await write('/working-selections',{shot_id:s.shotId,output_kind:definition.modality,candidate_id:clear?null:candidate,base_version_id:row.selection_version_id||null,...(trim||{})},s,n,m);if(alive(n,s))await loadCandidates();}
          box.append(button(row.selected?msg("common.unselect_action"):msg("ui.select_this_result"),()=>choose(row.selected)),button(msg("ui.view_media"),()=>ctx.media(row.media_id)));
          const favorite=button(msg('classic_controls.'+(row.favorite?'unfavorite':'favorite')),async()=>{await write('favorite',{media_id:row.media_id,active:!row.favorite,base_version:row.favorite_version},s,n,m);if(alive(n,s))await loadCandidates();},!row.can_favorite);favorite.setAttribute('aria-pressed',String(row.favorite));box.append(favorite);
          if(!imageMode&&row.native_sample){const expiry=row.native_sample.expires_at,expired=expiry&&Date.parse(expiry)<=Date.now();box.append(el('p',row.native_sample.unavailable||(msg("ui.native_480p_sample_value0",{value0:expired?msg("ui.upgrade_expired"):msg("ui.upgradeable_until_value0",{value0:new Date(expiry).toLocaleString()})})),'hint'),button(msg("ui.upgrade_this_sample_to_1080p"),async()=>{const config=await ctx.api(base(s.projectId)+'/classic-production/candidate-configuration?shot_id='+s.shotId+'&media_id='+row.media_id);if(!alive(n,s)||requestNo!==candidateRequest)return;if(!config.sample_upgrade)throw new Error('原样片固定来源不完整，无法升级');const upgrade=config.sample_upgrade;if(Date.parse(upgrade.expires_at)<=Date.now())throw new Error('原样片升级已过有效期');const target=entry('video_upgrade');target.document=clone(upgrade.document);target.dirty=true;remember(target,s,'video_upgrade');mode='video_upgrade';editNo++;render();if(!upgrade.model_ids.length)ctx.notice(msg("ui.add_a_1080p_upgrade_model_configuration_and_quote_under"));},Boolean(expired||row.native_sample.unavailable)));}
          if(!imageMode&&row.selected){const trim=el('details');trim.append(el('summary',msg("ui.trim_selected_video")));const start=field(trim,msg("ui.trim_start_seconds"),el('input')),end=field(trim,msg("ui.trim_end_seconds"),el('input'));for(const input of [start,end]){input.type='number';input.min='0';input.step='.001';}start.value=(row.trim_in_ms||0)/1000;end.value=(row.trim_out_ms??row.duration_ms)/1000;trim.append(button(msg("ui.save_working_trim"),()=>choose(false,{event_kind:'trim',trim_in_ms:Math.round(Number(start.value)*1000),trim_out_ms:Math.round(Number(end.value)*1000)})));box.append(trim);}
          if(imageMode&&m==='image_panorama')box.append(button(msg("ui.open_panorama_viewer"),async()=>{const config=await ctx.api(base(s.projectId)+'/classic-production/candidate-configuration?shot_id='+s.shotId+'&media_id='+row.media_id);if(!alive(n,s))return;if(!config.available||config.source_operation!=='panorama'||config.document?.mode!=='image_panorama')throw new Error('此结果不是原生全景任务输出');const dialog=el('dialog'),host=el('section');dialog.append(button(msg("common.close"),()=>{dialog.close();dialog.remove();}),host);root.append(dialog);dialog.showModal();const viewer=await import('./panorama-viewer.js');if(!alive(n,s)||!dialog.open)return;viewer.mountPanorama(host,visual.src,{isCurrent:()=>alive(n,s)&&dialog.open});}));
          if(imageMode)box.append(button(msg("ui.use_as_video_first_frame"),()=>{const target=entry('single');target.document.prompt||=doc.prompt;target.document.references=target.document.references.filter(r=>r.role!=='first_frame');target.document.references.push({role:'first_frame',media_id:row.media_id,sha256:row.sha256});target.dirty=true;remember(target,s,'single');mode='single';render();}));
          box.append(button(msg("ui.reuse_this_candidate_s_configuration"),async()=>{const config=await ctx.api(base(s.projectId)+'/classic-production/candidate-configuration?shot_id='+s.shotId+'&media_id='+row.media_id);if(!alive(n,s))return;if(!config.available)throw new Error(config.reason);const target=entry(config.document.mode);target.document=clone(config.document);target.dirty=true;remember(target,s,config.document.mode);mode=config.document.mode;editNo++;render();}));candidateGrid.append(box);
        }
        if(!value.items?.length)candidateGrid.append(el('p',msg("ui.no_results_of_this_type_in_the_current_shot")));
        if(e.lastGeneration?.jobs?.length){const jobs=await Promise.all(e.lastGeneration.jobs.map(job=>ctx.api(base(s.projectId)+'/production-platform/jobs/'+job.id)));if(!alive(n,s)||requestNo!==candidateRequest)return;report.replaceChildren(el('p',msg("ui.tasks_in_this_request_value0",{value0:jobs.map(j=>({created:'排队中',queued:'排队中',submitted:'已提交',claimed:'等待执行',running:'生成中',succeeded:'已完成',failed:'失败',submission_unknown:'提交状态待恢复',blocked:'等待补齐条件',cancelled:'已取消'})[j.status]||j.status).join('、')})));if(jobs.some(j=>['created','queued','claimed','submitted','running'].includes(j.status)))s.poll=setTimeout(()=>{if(alive(n,s))loadCandidates();},3000);}
        paging.replaceChildren(button(msg("common.previous_page"),()=>{offset=Math.max(0,offset-24);return loadCandidates();},offset===0),el('span',msg("ui.page_value0",{value0:String(Math.floor(offset/24)+1)})),button(msg("common.next_page"),()=>{offset=value.next_offset;return loadCandidates();},value.next_offset==null),button(msg("ui.refresh_outputs"),loadCandidates));
      }catch(error){if(alive(n,s)&&requestNo===candidateRequest){setText(count,msg("ui.results_could_not_be_loaded"));paging.replaceChildren(el('p',error.message),button(msg("ui.retry_loading_outputs"),loadCandidates));}}
    }
    loadCandidates();

  }
  function renderEmpty(s,n){
    root.classList.add('classic-production');const noun=s.productionKind==='image'?'分镜':'视频',nounLabel=msg(s.productionKind==='image'?'classic.storyboard_noun':'classic.video_noun'),heading=el('header',null,'classic-heading'),rail=el('nav',null,'classic-shot-rail'),body=el('div',null,'classic-layout'),left=el('section',null,'classic-form'),right=el('aside',null,'classic-results');
    heading.append(el('h1',msg("ui.all_value0",{value0:nounLabel})),rail);left.append(el('h2',msg("ui.how_to_generate_value0",{value0:nounLabel})));const model=field(left,msg("common.model"),el('select'));model.append(localizedOption('',msg("ui.add_value0_then_choose_a_model",{value0:nounLabel})));model.disabled=true;const prompt=field(left,msg("common.prompt"),el('textarea'));bindAttribute(prompt,"placeholder",msg("ui.add_value0_to_start_creating",{value0:nounLabel}));prompt.disabled=true;prompt.rows=10;
    const add=button('',()=>s.episodeId?createFirstShot():ctx.navigate('project',null));add.className='classic-shot classic-add-shot';add.append(el('span','＋'),el('span',s.episodeId?msg("ui.add_value0_dynamic_339",{value0:nounLabel}):msg("script-studio.select_episode_2")));rail.append(add);left.append(el('p',s.episodeId?msg("ui.add_a_value0_first_then_add_references_and_a",{value0:nounLabel}):msg("ui.select_the_episode_to_produce_first"),'classic-empty-message'));right.append(el('h2',msg("common.generate_results")),el('p',msg("asset.audio_generate_empty_title"),'classic-empty-message'));body.append(left,right);root.replaceChildren(heading,body);
    function createFirstShot(){
      const owner=session().identityId||session().actor||'',bufferKey=[s.projectId,s.episodeId,owner,'first-shot'].join(':'),storageKey='vsc.classic-first-shot:'+bufferKey;let stored=null;try{stored=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{}
      const buffer=drafts.get(bufferKey)||{names:stored?.names||{scene:'场景1',sequence:'镜组1',shot:noun+'1'},items:Array.isArray(stored?.items)?stored.items:[],busy:false,listeners:new Set()};drafts.set(bufferKey,buffer);
      const retain=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify({names:buffer.names,items:buffer.items}));}catch{throw new Error('浏览器无法保存创建回执，请恢复本机存储后继续。');}};
      const dialog=el('dialog',null,'classic-upload-dialog'),form=el('form'),header=el('header'),status=el('p',null,'classic-upload-status');bindAttribute(dialog,'aria-label',msg("ui.add_value0_dynamic_339",{value0:nounLabel}));status.setAttribute('role','status');header.append(el('h2',msg("ui.add_value0_dynamic_339",{value0:nounLabel})),button(msg("common.close"),()=>dialog.close()));dialog.append(header,form);root.append(dialog);
      const current=()=>alive(n,s)&&(session().identityId||session().actor||'')===owner&&dialog.open&&dialog.isConnected,fields={};
      for(const [kind,label]of [['scene',msg("asset.scene_name")],['sequence',msg("ui.sequence_name")],['shot',msg("ui.shot_name")]]){const input=field(form,label,el('input'));input.value=buffer.names[kind];input.required=true;input.addEventListener('input',()=>buffer.names[kind]=input.value);fields[kind]=input;}
      const submit=el('button',buffer.items.length?msg("ui.continue_creating"):msg("ui.create_and_start_production"));submit.type='submit';submit.className='classic-primary';form.append(status,submit);
      const lock=()=>{for(const input of Object.values(fields))input.disabled=buffer.busy||buffer.items.length>0;submit.disabled=buffer.busy||!session().actor||!session().writable;};buffer.listeners.add(lock);lock();dialog.addEventListener('close',()=>{buffer.listeners.delete(lock);dialog.remove();});
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(buffer.busy)return;if(!session().actor||!session().writable){setText(status,msg("ui.this_session_is_read_only"));return;}if(Object.values(buffer.names).some(value=>!value.trim())){setText(status,msg("ui.enter_scene_sequence_and_shot_names"));return;}
        buffer.busy=true;lock();setText(status,msg("ui.creating_shot"));
        try{
          const tree=await ctx.api(base(s.projectId)+'/tree');if(!current())return;if(!tree.nodes.some(row=>row.id===s.episodeId&&row.kind==='episode'))throw new Error('当前剧集不可用，请重新选择剧集。');ctx.setRevision(tree.revision,s.projectId);
          if(!buffer.items.length){const ids={scene:crypto.randomUUID(),sequence:crypto.randomUUID(),shot:crypto.randomUUID()},ordinal=Math.max(0,...tree.nodes.filter(row=>row.kind==='scene'&&row.parent_id===s.episodeId).map(row=>Number(row.ordinal)||0))+1;for(const kind of ['scene','sequence','shot'])buffer.items.push({payload:{id:ids[kind],kind,parent_id:kind==='scene'?s.episodeId:kind==='sequence'?ids.scene:ids.sequence,display_code:({scene:'SC',sequence:'SQ',shot:'SH'})[kind]+'-'+ids[kind].slice(0,8),title:buffer.names[kind].trim(),ordinal:kind==='scene'?ordinal:1},key:crypto.randomUUID(),request:null,result:null});}
          retain();for(const item of buffer.items){if(!current())return;if(item.result)continue;item.request||={payload:item.payload,expected_revision:session().revision,idempotency_key:item.key};retain();try{item.result=await ctx.api(base(s.projectId)+'/objects',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(item.request)});}catch(error){if(error.status>=400&&error.status<500){item.request=null;retain();}throw error;}retain();if(current())ctx.setRevision(item.result.revision,s.projectId);}
          if(!current())return;dialog.close();if(await load({...s,objectId:buffer.items[2].payload.id,shotId:buffer.items[2].payload.id,shots:null})){sessionStorage.removeItem(storageKey);drafts.delete(bufferKey);}
        }catch(error){if(current()){setText(status,msg("ui.value0_created_objects_and_inputs_preserved_continuing_will_not",{value0:error.message}));setText(submit,msg("ui.continue_creating"));}}
        finally{buffer.busy=false;for(const update of buffer.listeners)update();}
      });dialog.showModal();
    }
  }
  async function load(value){
    const n=++epoch;preview=null;scope={...value,ownerIdentity:identity()};const s=scope;
    closeDialogs();root.replaceChildren(el('p',msg("ui.loading_classic_production")));
    try{
      const query=new URLSearchParams({section:'shots',limit:'100',...(value.objectId?{object_id:value.objectId}:value.episodeId?{object_id:value.episodeId}:{})});
      const listing=await ctx.api(base(s.projectId)+'/workbench?'+query);
      if(!alive(n,s))return;
      const page=listing.sections.shots;
      s.episodeId=value.episodeId||(listing.scope.kind==='episode'?listing.scope.id:listing.ancestors.find(row=>row.kind==='episode')?.id)||null;
      s.shots=value.shots?.length?value.shots:page.items;
      s.shotId=value.shotId||(listing.scope.kind==='shot'?listing.scope.id:page.items[0]?.id);
      if(!s.shotId){renderEmpty(s,n);return;}
      const data=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId));
      if(!alive(n,s))return;
      options=data;const kind=value.productionKind||'video';if(value.mode&&data.modes[value.mode])mode=value.mode;else if(!data.modes[mode]||data.modes[mode].modality!==kind)mode=Object.keys(data.modes).find(k=>data.modes[k].modality===kind)||Object.keys(data.modes)[0];if(data.sibling_shots?.length)s.shots=data.sibling_shots;ctx.setRevision(data.revision,s.projectId);ctx.onShot?.(s.shotId,s.episodeId);render();
      if(page.next_offset!=null||page.truncated)root.append(el('p',msg("ui.showing_the_first_100_shots_locate_other_shots_in"),'hint'));
      return true;
    }catch(error){if(alive(n,s))root.replaceChildren(el('h1',msg("ui.classic_production_could_not_be_loaded")),el('p',error.message),button(msg("ui.reload"),()=>load(value)));}
  }
  return {load,beforeContextSwitch(){for(const [id,e]of drafts){if(!e.document||!e.dirty)continue;const value={document:e.document,saved:e.saved,dirty:e.dirty,rawParams:e.rawParams,lastGeneration:e.lastGeneration,assist:e.assist,assistSmart:e.assistSmart,assistLanguage:e.assistLanguage};retained.put('vsc-classic-draft:'+id,value);if(JSON.stringify(retained.get('vsc-classic-draft:'+id))!==JSON.stringify(value))return {ready:false,message:'浏览器无法保留当前制作输入，请先保存后切换。'};}return {ready:true};},suspend(){clearTimeout(scope?.poll);runScope?.dispose();referenceEditor?.suspend();epoch++;preview=null;closeDialogs();}};
}
