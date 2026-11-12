import {msg,setText,bindAttribute,isMessage,joinMessages,option as localizedOption} from './i18n.js';
/* Scene versions and export jobs are authoritative server records. Drafts and
   unknown write receipts stay with their owning project/tab until resolved. */
const clone=v=>JSON.parse(JSON.stringify(v));
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const field=(label,value='',type='text')=>{const n=el(type==='textarea'?'textarea':'input');bindAttribute(n,'aria-label',label);if(type!=='textarea')n.type=type;n.value=value;return n;};
const read=k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null');}catch{return null;}};
const persist=(k,v)=>{try{if(v===null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,JSON.stringify(v));return true;}catch{return false;}};
const names={box:'方体',sphere:'球体',actor:'人物',light:'灯光',reference:'参考图',mesh:'导入网格'};
const defaultPoses=[['stand','站立'],['walk','行走'],['run','奔跑'],['sit','坐姿'],['crouch','蹲姿'],['kneel_single','单膝跪'],['kneel_double','双膝跪'],['combat','格斗架势'],['arms_crossed','抱臂'],['hands_on_hips','叉腰'],['wave','挥手'],['reach','伸手抓取'],['lean','倚靠'],['look_phone','低头看手机'],['think','托腮思考'],['bow','鞠躬'],['push','推搡'],['kick','踢腿'],['throw','投掷'],['t_pose','T-Pose 校准'],['arms_up','举手']];
const defaultBodyPresets=[{id:'male_basic',label:'标准男性',color:'#7fb2ff',scale:[1,1,1]},{id:'female_low_poly',label:'标准女性',color:'#ff8fb5',scale:[0.92,0.95,0.92]},{id:'generous',label:'魁梧丰满',color:'#f0a35c',scale:[1.22,1.02,1.18]},{id:'robust',label:'健壮肌肉',color:'#f25f5c',scale:[1.16,1.06,1.12]},{id:'slender',label:'修长纤细',color:'#72d6c9',scale:[0.86,1.08,0.86]},{id:'young',label:'少年体态',color:'#8dd36f',scale:[0.85,0.88,0.85]},{id:'children',label:'儿童体态',color:'#ffd166',scale:[0.72,0.68,0.72]},{id:'two_heads_tall',label:'二头身 Q 版',color:'#b28dff',scale:[0.78,0.56,0.78]}];
const defaultJointGroups=[{group:'head',label:'头部',axes:[['head_nod','俯仰'],['head_tilt','侧倾'],['head_turn','转向']]},{group:'torso',label:'躯干',axes:[['torso_pitch','前倾'],['torso_roll','侧弯'],['torso_yaw','扭转']]},{group:'left_shoulder',label:'左肩',axes:[['left_shoulder_pitch','抬臂'],['left_shoulder_roll','外展'],['left_shoulder_yaw','旋臂']]},{group:'right_shoulder',label:'右肩',axes:[['right_shoulder_pitch','抬臂'],['right_shoulder_roll','外展'],['right_shoulder_yaw','旋臂']]},{group:'elbows',label:'双肘',axes:[['left_elbow','左肘弯曲'],['right_elbow','右肘弯曲']]},{group:'hips',label:'双胯',axes:[['left_hip_pitch','左腿抬起'],['left_hip_roll','左腿外展'],['left_hip_yaw','左腿旋转'],['right_hip_pitch','右腿抬起'],['right_hip_roll','右腿外展'],['right_hip_yaw','右腿旋转']]},{group:'knees',label:'双膝',axes:[['left_knee','左膝弯曲'],['right_knee','右膝弯曲']]}];

export function createSpatialScenePanel(ctx){
  let active=null,epoch=0;
  const live=s=>active===s&&s.epoch===epoch;
  const base=s=>`/api/v1/projects/${encodeURIComponent(s.project)}`;
  const sceneUrl=s=>`${base(s)}/spatial-scenes${s.id?'/'+s.id:''}`;
  const key=s=>`vsc-spatial:${s.project}:${s.id||'new:'+s.mode}`;
  const header=()=>({'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf});
  const notice=(s,message)=>{if(live(s)&&s.status)setText(s.status,message);};
  const revision=(s,v)=>{s.revision=v;if(live(s))ctx.setRevision?.(v,s.project);};
  function button(s,label,fn){const b=el('button',label);b.type='button';b.addEventListener('click',async()=>{if(b.disabled)return;b.disabled=true;try{await fn();}catch(e){notice(s,e.message);}finally{b.disabled=false;}});return b;}
  function remember(s){if(!s.id)return;const old=read(key(s));if(!live(s)&&old?.owner!==s.owner)return;const value=s.dirty||s.pending?{owner:s.owner,document:s.document,title:s.title,description:s.description,version:s.version,pending:s.pending,revision:s.revision}:null;if(!persist(key(s),value))notice(s,msg("ui.draft_storage_is_unavailable_in_this_tab_keep_the"));}
  function changed(s){s.dirty=true;remember(s);notice(s,msg("ui.unsaved_scene_changes"));previewSoon(s);}
  function change(s,fn){if(!live(s))return;s.undo.push(clone({document:s.document,title:s.title,description:s.description}));if(s.undo.length>30)s.undo.shift();s.redo=[];fn();changed(s);drawEditor(s);}
  async function request(s,request){if(!ctx.session().actor)throw new Error('请先建立操作会话。');const result=await ctx.api(request.path,{method:request.method,headers:header(),body:JSON.stringify(request.body)});if(result.revision!=null)revision(s,result.revision);return result;}
  function mutation(s,path,payload,method='POST'){return {path,method,body:{payload,expected_revision:s.revision,idempotency_key:crypto.randomUUID()}};}
  async function durable(s,slot,path,payload,method='POST'){
    const cache=`${key(s)}:operation:${slot}`;let pending=read(cache)||mutation(s,path,payload,method);persist(cache,pending);
    try{const result=await request(s,pending);persist(cache,null);return result;}
    catch(e){const rejected=e.status>=400&&e.status<500;if(rejected)persist(cache,null);throw new Error(e.message+(rejected?'；请求未生效，请读取当前状态后重试。':'；原请求已保留，可再次操作读取回执。'));}
  }
  async function save(s){
    if(s.saving)return s.saving;if(!s.dirty&&!s.pending)return true;
    const pending=s.pending||mutation(s,sceneUrl(s),{scene_revision:s.version,title:s.title,description:s.description,document:clone(s.document)},'PUT');s.pending=pending;remember(s);notice(s,msg("ui.saving_scene"));
    s.saving=(async()=>{try{const data=await request(s,pending);s.version=data.scene_revision;s.pending=null;s.dirty=JSON.stringify(pending.body.payload.document)!==JSON.stringify(s.document)||pending.body.payload.title!==s.title||pending.body.payload.description!==s.description;remember(s);if(live(s)){setText(s.versionLabel,msg("ui.saved_version_value0",{value0:s.version}));notice(s,s.dirty?msg("ui.previous_version_confirmed_current_changes_still_need_saving"):msg("ui.scene_saved"));}return !s.dirty;}
      catch(e){if(e.status>=400&&e.status<500&&e.status!==409)s.pending=null;remember(s);notice(s,msg("ui.value0_local_draft_and_save_receipt_preserved_recover_the",{value0:e.message}));return false;}
      finally{s.saving=null;}})();return s.saving;
  }
  async function load(root,projectId,mode='previs',targetId=null){
    suspend();const s={root,project:projectId||ctx.projectId?.(),mode,epoch,revision:ctx.session().revision||0};active=s;root.classList.add('spatial-scene');root.classList.remove('ss-editor');root.replaceChildren(el('h1',mode==='blocking'?msg("ui.3d_director_bu_staging_unit"):msg("ui.standalone_3d_previs")));s.status=el('p',msg("ui.loading_scene"),'ss-status');s.status.setAttribute('role','status');root.append(s.status);if(!s.project){notice(s,msg("ui.select_a_project_first"));return;}
    try{const [listing,options]=await Promise.all([ctx.api(`${sceneUrl(s)}?mode=${mode}`),ctx.api(`${base(s)}/spatial-scene-options`)]);if(!live(s))return;revision(s,listing.revision);s.options=options;
      if(targetId){await open(s,targetId);return;}
      const form=el('form',null,'ss-bar'),title=field(msg("ui.new_scene_name"),mode==='blocking'?'站位单元':'独立预演'),scope=el('select');bindAttribute(scope,'aria-label',mode==='blocking'?msg("ui.owning_scene"):msg("ui.owning_episode"));scope.append(localizedOption('',mode==='blocking'?msg("ui.choose_an_existing_scene_spatialtail_0"):msg("ui.no_episode_binding")));
      for(const n of options.nodes||[])if(n.kind===(mode==='blocking'?'scene':'episode'))scope.append(localizedOption(n.id,n.title||n.display_code||n.id));
      const create=el('button',msg("asset.create_scene"));create.type='submit';form.append(title,scope,create);root.append(form);
      form.addEventListener('submit',async event=>{event.preventDefault();if(create.disabled)return;create.disabled=true;try{if(mode==='blocking'&&!scope.value)throw new Error('先选择所属场次。');const result=await durable(s,'create',sceneUrl(s),{mode,title:title.value,scene_id:mode==='blocking'?scope.value:null,episode_id:mode==='previs'?scope.value||null:null,document:options.default_document});if(live(s))await open(s,result.id);}catch(e){notice(s,e.message);}finally{if(live(s))create.disabled=false;}});
      const list=el('div',null,'ss-list');for(const row of listing.items||[]){const card=el('article');card.append(el('h2',row.title),el('p',msg("ui.version_value0_value1",{value0:row.version,value1:row.scene_id?msg("ui.scene_linked"):''})),button(s,msg("ui.open_scene"),()=>open(s,row.id)));list.append(card);}root.append(list);notice(s,listing.items?.length?msg("ui.choose_a_scene_to_continue_editing"):msg("ui.create_staging_and_camera_setups_then_save_before_exporting"));
    }catch(e){notice(s,e.message);root.append(button(s,msg("ui.reload_list"),()=>load(root,s.project,mode)));}
  }
  async function open(prior,id){
    if(!live(prior))return;remember(prior);cleanup(prior);epoch++;const s={root:prior.root,project:prior.project,mode:prior.mode,options:prior.options,id,epoch,owner:crypto.randomUUID(),revision:prior.revision,undo:[],redo:[],time:0,dirty:false,pending:null,urls:[],previewSeq:0};active=s;s.root.replaceChildren();s.status=el('p',msg("ui.loading_fixed_scene_version"),'ss-status');s.status.setAttribute('role','status');s.root.append(s.status);
    try{const data=await ctx.api(sceneUrl(s));if(!live(s))return;s.title=data.title;s.description=data.description;s.document=data.document;s.version=data.scene_revision;s.scope=data;s.modelCatalog=data.model_catalog||{};revision(s,data.revision);const saved=read(key(s));if(saved?.document){Object.assign(s,{document:saved.document,title:saved.title,description:saved.description,version:saved.version,pending:saved.pending,dirty:true});remember(s);}s.primary=s.document.cameras[0].id;s.secondary=s.document.cameras[1]?.id||s.primary;s.selected={kind:'object',id:s.document.objects[0]?.id};const generated=(data.plans||[]).find(t=>t.apply_mode==='direct'&&t.status==='applied'&&t.output_version_id===data.version_id);if(generated&&!saved)s.undo.push(clone({document:generated.document,title:s.title,description:s.description}));editor(s);notice(s,saved?msg("ui.scene_draft_recovered_from_this_tab_check_the_save"):msg("ui.project_scene_loaded_drag_the_main_camera_view_to"));await refreshExports(s);}
    catch(e){notice(s,e.message);}
  }
  function editor(s){
    s.root.replaceChildren();const bar=el('div',null,'ss-bar');bar.append(button(s,msg("ui.scene_list"),()=>load(s.root,s.project,s.mode)));const title=field(msg("asset.scene_name"),s.title);title.addEventListener('change',()=>{s.title=title.value;changed(s);});s.versionLabel=el('span',msg("ui.saved_version_value0",{value0:s.version}));bar.append(title,s.versionLabel,button(s,msg("ui.save_scene"),()=>save(s)),button(s,msg("ui.recover_save_request"),()=>save(s)),button(s,msg("ui.reload_and_preserve_draft"),()=>open(s,s.id)),button(s,msg("ui.save_scene_as_a_copy"),async()=>{const result=await durable(s,'copy',`${base(s)}/spatial-scenes`,{mode:s.mode,title:s.title+' · 副本',description:s.description,scene_id:s.scope.scene_id,episode_id:s.scope.episode_id,document:clone(s.document)});if(live(s))await open(s,result.id);}));s.root.append(bar);
    s.status=el('p','','ss-status');s.status.setAttribute('role','status');s.root.append(s.status);
    const recovery=el('details');recovery.append(el('summary',msg("ui.history_and_local_draft_recovery")),el('p',msg("ui.preserve_the_original_request_if_saving_fails_or_its")),button(s,msg("ui.discard_local_draft_and_load_server_version"),()=>{s.dirty=false;s.pending=null;persist(key(s),null);return open(s,s.id);}));
    for(const v of s.scope.history||[])recovery.append(button(s,msg("ui.load_historical_version_value0",{value0:v.version}),async()=>{if(s.pending)throw new Error('先恢复当前保存请求。');const doc=await ctx.api(sceneUrl(s)+'?version='+v.version);if(live(s))change(s,()=>{s.document=doc.document;s.modelCatalog=doc.model_catalog||{};s.title=doc.title;s.description=doc.description;});}));s.root.append(recovery);
    const desc=field(msg("ui.scene_description"),s.description,'textarea');desc.addEventListener('change',()=>{s.description=desc.value;changed(s);});s.root.append(desc);
    const controls=el('div',null,'ss-bar');for(const kind of ['box','sphere','actor','light'])controls.append(button(s,msg("ui.add_value0",{value0:names[kind]}),()=>change(s,()=>{const id=crypto.randomUUID();s.document.objects.push({id,name:names[kind],kind,position:kind==='light'?[5,8,4]:[0,0,0],rotation:[0,0,0],scale:[1,1,1],color:'#65a4c4',visible:true,locked:false,pose:'stand',joints:{},keyframes:[],media_id:null});s.selected={kind:'object',id};})));
    controls.append(
      button(s,'添加群众阵列',()=>change(s,()=>{
        const remain=Math.max(0,64-s.document.objects.length);
        if(!remain)throw new Error('场景对象已达 64 个上限');
        const presets=s.options?.body_presets||defaultBodyPresets;
        let created=0,lastId=null;
        for(let row=0;row<3&&created<remain;row++){
          for(let col=0;col<3&&created<remain;col++){
            const preset=presets[(row*3+col)%presets.length];
            const id=crypto.randomUUID();
            s.document.objects.push({id,name:`群众${created+1}`,kind:'actor',body_preset:preset.id,position:[(col-1)*1.4,0,-2.2-row*1.5],rotation:[0,0,0],scale:clone(preset.scale),color:preset.color,visible:true,locked:false,pose:'stand',joints:{},keyframes:[],media_id:null});
            lastId=id;created++;
          }
        }
        if(lastId)s.selected={kind:'object',id:lastId};
      })),
      button(s,msg("ui.add_camera"),()=>change(s,()=>{const camera=clone(s.document.cameras[0]);camera.id=crypto.randomUUID();camera.name='新机位';camera.keyframes=[];s.document.cameras.push(camera);s.selected={kind:'camera',id:camera.id};})),
      button(s,msg("ui.import_project_glb"),()=>mediaPicker(s,'model')),
      button(s,msg("video.add_reference_image"),()=>mediaPicker(s,'reference')),
      button(s,'全景天空背景',()=>mediaPicker(s,'panorama')),
      button(s,msg("common.undo"),()=>undo(s,false)),
      button(s,msg("common.redo"),()=>undo(s,true)),
    );s.root.append(controls);
    const workspace=el('div',null,'ss-workspace');s.tree=el('aside',null,'ss-tree');s.center=el('div',null,'ss-center');s.inspector=el('aside',null,'ss-inspector');workspace.append(s.tree,s.center,s.inspector);s.root.append(workspace);
    const viewBar=el('div',null,'ss-view-bar');
    s.viewMode=s.viewMode||'director';s.guideMode=s.guideMode||'none';
    const directorBtn=button(s,'导演视角',()=>{s.viewMode='director';s.primary=s.document.cameras[0].id;drawEditor(s);});
    const shotCamBtn=button(s,'机位视角',()=>{s.viewMode='camera';const alt=s.document.cameras[1]||s.document.cameras[0];s.primary=alt.id;drawEditor(s);});
    const guideSelect=el('select');bindAttribute(guideSelect,'aria-label','构图参考线');
    for(const [val,label]of [['none','无参考线'],['thirds','三分法九宫格'],['safe','安全框']])guideSelect.append(localizedOption(val,label));
    guideSelect.value=s.guideMode;
    guideSelect.addEventListener('change',()=>{s.guideMode=guideSelect.value;for(const v of s.views||[])v.guide.dataset.guide=s.guideMode;});
    viewBar.append(directorBtn,shotCamBtn,guideSelect);
    s.center.append(viewBar);
    const views=el('div',null,'ss-views');s.views=[];for(let i=0;i<2;i++){const card=el('div',null,'ss-view'),select=el('select');bindAttribute(select,'aria-label',i?msg("ui.comparison_camera"):msg("ui.main_camera"));select.addEventListener('change',()=>{s[i?'secondary':'primary']=select.value;previewSoon(s);});const image=el('img');bindAttribute(image,"alt",i?msg("ui.comparison_camera_preview"):msg("ui.main_camera_preview"));const guide=el('div',null,'ss-view-guide');guide.dataset.guide=s.guideMode;const caption=el('p');card.append(select,image,guide,caption);views.append(card);s.views.push({select,image,guide,caption});}s.center.append(views);orbit(s,s.views[0].image);
    const timeline=el('div',null,'ss-timeline');s.timeInput=field(msg("ui.current_time"),0,'range');s.timeInput.min=0;s.timeInput.step=.05;s.timeInput.max=s.document.duration;s.timeText=el('span','0.00 s');s.timeInput.addEventListener('input',()=>{s.time=Number(s.timeInput.value);setText(s.timeText,joinMessages([s.time.toFixed(2)," s"]));previewSoon(s);});s.capture=el('button',msg("ui.capture_current_view"));s.capture.type='button';s.capture.disabled=!s.document.objects.length;s.capture.addEventListener('click',async()=>{if(s.capture.disabled)return;s.capture.disabled=true;try{await captureView(s);}catch(e){notice(s,e.message);}finally{if(live(s))s.capture.disabled=!s.document.objects.length;}});
    const runBatchViews=async count=>{
      if(!s.document.objects.length)throw new Error('空场景不能生成多方位截图');
      if(!await save(s))return;
      const res=await durable(s,`batch-views:${count}:${s.version}:${s.time}`,`${sceneUrl(s)}/batch-views`,{count,camera_id:s.primary,time:s.time});
      if(!live(s))return;
      s.batchViews=res.items||[];
      drawBatchViews(s);
      notice(s,`已生成 ${s.batchViews.length} 张${count===4?'四':'十二'}方位截图并登记至项目媒体库`);
    };
    timeline.append(button(s,msg("ui.play_pause"),()=>{if(s.play){clearInterval(s.play);s.play=null;return;}s.play=setInterval(()=>{if(!live(s))return;s.time=Math.round((s.time+.25)*100)/100;if(s.time>s.document.duration)s.time=0;s.timeInput.value=s.time;setText(s.timeText,joinMessages([s.time.toFixed(2)," s"]));previewSoon(s,0);},250);}),s.timeInput,s.timeText,s.capture,button(s,'四方位截图',()=>runBatchViews(4)),button(s,'十二方位截图',()=>runBatchViews(12)),button(s,msg("ui.record_selected_keyframe_at_this_time"),()=>{const item=selected(s);if(!item||item.locked)throw new Error('选择未锁定的对象或机位。');change(s,()=>{item.keyframes=item.keyframes.filter(f=>Math.abs(f.time-s.time)>.001);item.keyframes.push({time:s.time,position:clone(item.position),...(s.selected.kind==='camera'?{target:clone(item.target)}:{rotation:clone(item.rotation)})});item.keyframes.sort((a,b)=>a.time-b.time);});}));s.center.append(timeline);
    const settings=el('div',null,'ss-bar');for(const [label,prop]of [[msg("ui.scene_duration"),'duration'],[msg("ui.frame_width"),'width'],[msg("ui.frame_height"),'height']]){const control=field(label,s.document[prop],'number');control.step=prop==='duration'?'.1':'2';control.addEventListener('change',()=>change(s,()=>{s.document[prop]=Number(control.value);s.time=Math.min(s.time,s.document.duration);s.timeInput.max=s.document.duration;}));settings.append(el('label',label),control);}const color=field(msg("ui.background_color"),s.document.background,'color');color.addEventListener('change',()=>change(s,()=>s.document.background=color.value));settings.append(color);
    if(s.document.panorama_media_id){
      const radiusField=field('天球半径',s.document.sphere_radius||45,'number');radiusField.min='10';radiusField.max='200';radiusField.step='1';
      radiusField.addEventListener('change',()=>change(s,()=>{s.document.sphere_radius=Math.max(10,Math.min(200,Number(radiusField.value)||45));}));
      settings.append(el('label','天球半径'),radiusField,button(s,'清除全景天空',()=>change(s,()=>{delete s.document.panorama_media_id;delete s.document.sphere_radius;})));
    }
    s.center.append(settings);
    s.batchHost=el('div',null,'ss-batch-views');drawBatchViews(s);s.center.append(s.batchHost);
    const output=el('section',null,'ss-output');output.append(el('h2',msg("ui.fixed_version_export")));const duration=field(msg("ui.video_export_duration"),Math.min(3,s.document.duration),'number');duration.step='.1';duration.min='.1';duration.max='15';const fps=el('select');bindAttribute(fps,'aria-label',msg("ui.video_frame_rate"));fps.append(localizedOption('12','12 fps'),localizedOption('24','24 fps'));output.append(el('label',msg("ui.video_seconds")),duration,fps);
    s.exportSizes=el('p');output.append(s.exportSizes);s.exportButtons=[];
    for(const format of ['png','glb','mp4']){const control=el('button',msg("ui.export_value0",{value0:format.toUpperCase()}));control.type='button';control.disabled=!s.document.objects.length;control.addEventListener('click',async()=>{if(control.disabled||!s.document.objects.length)return;control.disabled=true;try{if(!await save(s))return;const result=await durable(s,'export:'+format,sceneUrl(s)+'/exports',{scene_revision:s.version,camera_id:s.primary,time:s.time,format,duration:Number(duration.value),fps:Number(fps.value)});if(!live(s))return;notice(s,msg("ui.export_task_registered_recover_it_from_the_original_record"));await refreshExports(s);execute(s,result.id);}catch(e){notice(s,e.message);}finally{if(live(s))control.disabled=!s.document.objects.length;}});s.exportButtons.push(control);output.append(control);}
    s.exports=el('div');output.append(s.exports);s.root.append(output);
    const structured=el('details');structured.append(el('summary',msg("ui.structured_scene_input")));const json=field(msg("ui.scene_json"),JSON.stringify(s.document,null,2),'textarea');structured.append(json,button(s,msg("ui.load_structured_scene"),async()=>{const checked=await ctx.api(`${base(s)}/spatial-scene-validate`,{method:'POST',headers:header(),body:JSON.stringify({document:JSON.parse(json.value)})});const doc=checked.document;await fetchPreview(s,doc,doc.cameras[0].id,0);if(live(s))change(s,()=>{s.document=doc;s.modelCatalog=checked.model_catalog||{};s.primary=doc.cameras[0].id;s.secondary=doc.cameras[1]?.id||s.primary;s.time=0;});}));s.root.append(structured);sceneChat(s);
    s.root.append(el('p',msg("ui.bounded_3d_previs_supports_embedded_png_jpeg_textures_core"),'ss-limit'));arrangeEditor(s,bar,controls,recovery,desc,output,structured);drawEditor(s);
  }
  function arrangeEditor(s,bar,controls,recovery,desc,output,structured){
    s.root.classList.add('ss-editor');bar.classList.add('ss-document-bar');controls.classList.add('ss-object-toolbar');
    const more=el('details',null,'ss-more'),content=el('div');more.append(el('summary',msg("ui.version_and_settings")),content);
    for(const b of [...bar.querySelectorAll('button')])if(!['场景列表','保存场景'].includes(b.textContent))content.append(b);
    content.append(recovery,el('label',msg("ui.scene_description")),desc,structured,s.root.querySelector('.ss-limit'));bar.append(more);
    const exports=el('details',null,'ss-export-panel');exports.append(el('summary',msg("ui.export")),output);bar.append(exports);
    const chat=s.root.querySelector('.ss-chat'),drawer=el('details',null,'ss-agent-panel');drawer.append(el('summary','Agent'),chat);bar.append(drawer);
  }
  const stableScene=value=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
  function sceneChat(s){const section=el('section',null,'ss-chat');section.append(el('h2',msg("ui.modify_scene_through_chat")),el('p',msg("ui.describe_changes_to_generate_an_editable_scene_directly_original")));const message=field(msg("ui.scene_revision_request"),'','textarea'),mode=el('select');bindAttribute(mode,'aria-label',msg("ui.scene_generation_mode"));mode.append(localizedOption('direct',msg("ui.generate_and_save_directly")),localizedOption('review',msg("ui.review_plan_first")));section.append(message,mode,button(s,msg("ui.generate_modify_scene"),async()=>{if(!await save(s))return;const task=await durable(s,'plan:'+message.value+':'+mode.value,sceneUrl(s)+'/plans',{scene_revision:s.version,message:message.value,apply_mode:mode.value});if(!live(s))return;await ctx.api(`${base(s)}/spatial-plans/${task.id}/execute`,{method:'POST',headers:header()});if(live(s))await open(s,s.id);}));
    for(const task of s.scope.plans||[]){const card=el('article',null,'ss-plan');card.dataset.taskId=task.id;card.dataset.status=task.status;card.append(el('strong',task.message),el('p',({queued:'等待规划',running:'规划中',result_ready:'结果待登记',needs_input:'等待补充',planned:'待核对采纳',applied:'已保存新场景版本',rejected:'已拒绝',stopped:'已停止',failed:'规划失败',submission_unknown:'宿主结果未知'})[task.status]||task.status));if(task.error)card.append(el('p',task.error));if(task.plan){card.append(el('p',task.plan.message),...task.plan.questions.map(q=>el('p',msg("ui.needs_value0",{value0:q}))));const doc=field(msg("ui.scene_plan_structure_value0",{value0:task.id}),JSON.stringify(task.plan.document,null,2),'textarea');doc.rows=8;const changes=el('ul');for(const item of [...task.plan.document.objects,...task.plan.document.cameras]){const previous=[...task.document.objects,...task.document.cameras].find(x=>x.id===item.id);if(stableScene(previous)!==stableScene(item))changes.append(el('li',msg("ui.value0_value1_position_value2_value3",{value0:item.name||item.id,value1:previous?msg("script-studio.glossary_diff_updated"):msg("common.add"),value2:item.position.join(', '),value3:item.target?msg("spatial.facing",{value0:item.target.join(', ')}):''})));}for(const item of [...task.document.objects,...task.document.cameras])if(![...task.plan.document.objects,...task.plan.document.cameras].some(x=>x.id===item.id))changes.append(el('li',msg("ui.value0_delete",{value0:item.name||item.id})));if(!changes.children.length)changes.append(el('li',msg("ui.structure_matches_the_original_version_edit_and_preview_again")));card.append(changes);const advanced=el('details');advanced.append(el('summary',msg("ui.view_or_edit_complete_scene_structure")),doc);card.append(advanced);if(task.status==='planned'){let checked=null;const applyWay=el('select');bindAttribute(applyWay,'aria-label','AI 方案采纳方式');applyWay.append(localizedOption('replace','覆盖当前导演台'),localizedOption('insert','插入当前导演台'));card.append(applyWay,button(s,msg("ui.preview_scene_changes"),async()=>{const parsed=JSON.parse(doc.value),response=await ctx.api(`${base(s)}/spatial-scene-validate`,{method:'POST',headers:header(),body:JSON.stringify({document:parsed})});const blob=await fetchPreview(s,response.document,response.document.cameras[0].id,0);if(!live(s))return;checked=JSON.stringify(response.document);doc.value=JSON.stringify(response.document,null,2);const image=el('img');bindAttribute(image,"alt",msg("ui.scene_preview_awaiting_acceptance"));image.src=URL.createObjectURL(blob);s.urls.push(image.src);card.append(image,el('p',msg("ui.check_object_positions_cameras_and_timing_before_explicitly_accepting")));}),button(s,msg("ui.accept_as_a_new_scene_version"),async()=>{if(s.dirty||s.pending)throw new Error('本地场景有修改，先保稿；旧计划不会覆盖。');if(!checked||JSON.stringify(JSON.parse(doc.value))!==checked)throw new Error('请先预览当前可编辑计划');let finalDoc=JSON.parse(doc.value);if(applyWay.value==='insert'){const merged=clone(s.document);for(const obj of finalDoc.objects||[]){if(merged.objects.length>=64)break;const id=merged.objects.some(o=>o.id===obj.id)?crypto.randomUUID():obj.id;merged.objects.push({...obj,id});}finalDoc=merged;}await durable(s,'plan-confirm:'+task.id,`${base(s)}/spatial-plans/${task.id}/decisions`,{outcome:'confirm',reason:applyWay.value==='insert'?'用户核对后插入当前导演台':'用户核对场景预览后采纳',document:finalDoc});if(live(s))await open(s,s.id);}),button(s,msg("ui.reject_scene_plan"),async()=>{await durable(s,'plan-reject:'+task.id,`${base(s)}/spatial-plans/${task.id}/decisions`,{outcome:'reject',reason:'用户拒绝当前场景计划'});if(live(s))await open(s,s.id);}));}}
    if(['queued','running','result_ready','submission_unknown'].includes(task.status))card.append(button(s,msg("ui.query_recover_original_scene_plan"),async()=>{await ctx.api(`${base(s)}/spatial-plans/${task.id}/execute`,{method:'POST',headers:header()});if(live(s))await open(s,s.id);}));if(!['applied','rejected','stopped'].includes(task.status))card.append(button(s,msg("ui.stop_scene_planning"),async()=>{await durable(s,'plan-stop:'+task.id,`${base(s)}/spatial-plans/${task.id}/decisions`,{outcome:'stop',reason:'用户停止原规划任务'});if(live(s))await open(s,s.id);}));section.append(card);}s.root.append(section);}
  async function returnCanvas(s,job,origin){const current=await ctx.api(`${base(s)}/creative-canvases/${origin.target_canvas_id}`);if(!live(s))return;revision(s,current.revision);const result=await durable(s,'canvas:'+job.id+':'+origin.canvas_revision,`${base(s)}/spatial-exports/${job.id}/canvas`,{target_canvas_id:origin.target_canvas_id,canvas_revision:origin.canvas_revision,source_node_id:origin.source_node_id});if(!live(s))return;origin.canvas_revision=result.canvas_revision;persist(`vsc-spatial-origin:${s.project}:${s.id}`,origin);const target=new URL(origin.return_url,location.href);if(target.origin!==location.origin)throw new Error('返回地址不属于当前工作台');location.assign(target.href);}
  function selected(s){return (s.selected.kind==='camera'?s.document.cameras:s.document.objects).find(x=>x.id===s.selected.id);}
  async function captureView(s){
    if(!live(s)||!s.document.objects.length)throw new Error('空场景不能截取当前视窗');
    const response=await fetch(`${base(s)}/spatial-viewport`,{method:'POST',credentials:'same-origin',headers:header(),body:JSON.stringify({document:clone(s.document),camera_id:s.primary,time:s.time})});
    if(!response.ok){let error;try{error=await response.json();}catch{error=null;}throw new Error(error?.message||'当前视窗截取失败');}
    const blob=await response.blob();if(!live(s))return;
    const href=URL.createObjectURL(blob),link=el('a');link.href=href;link.download=`${s.title||'预演'}-${Date.now()}.png`;link.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
    notice(s,msg("ui.viewport_downloaded_not_on_canvas"));
  }
  function stillFrameSize(width,height){
    if(width===960&&height===540)return [1920,1080];
    if(width===540&&height===960)return [1080,1920];
    return [width,height];
  }
  function drawEditor(s){if(!live(s)||!s.tree)return;
    if(s.capture)s.capture.disabled=!s.document.objects.length;
    if(s.exportButtons)for(const control of s.exportButtons)control.disabled=!s.document.objects.length;
    if(s.exportSizes){const [stillWidth,stillHeight]=stillFrameSize(s.document.width,s.document.height);setText(s.exportSizes,msg("ui.previs_export_sizes",{value0:s.document.width,value1:s.document.height,value2:stillWidth,value3:stillHeight}));}
    s.tree.replaceChildren(el('h2',msg("ui.scene_objects")));for(const [kind,items] of [['object',s.document.objects],['camera',s.document.cameras]])for(const item of items){const b=button(s,joinMessages(["",s.selected.id===item.id?'● ':'',"",item.name,"",item.locked?msg("ui.locked_spatialtail_11"):'',"",item.visible===false?msg("ui.hidden"):'',""]),()=>{s.selected={kind,id:item.id};drawEditor(s);});b.className='ss-tree-item';s.tree.append(b);}
    s.views.forEach((view,i)=>{const value=s[i?'secondary':'primary'];view.select.replaceChildren(...s.document.cameras.map(c=>localizedOption(c.id,c.name)));view.select.value=value;});s.timeInput.max=s.document.duration;inspect(s);previewSoon(s);
  }
  function drawBatchViews(s){
    if(!s.batchHost)return;
    s.batchHost.replaceChildren();
    if(!s.batchViews?.length)return;
    s.batchHost.append(el('h3',`多方位截图 (${s.batchViews.length})`));
    const grid=el('div',null,'ss-batch-grid');
    for(const item of s.batchViews){
      const card=el('figure',null,'ss-batch-card');
      const img=el('img');img.src=`${base(s)}/media/${item.media_id}/content`;bindAttribute(img,'alt',item.name||item.label);
      const link=el('a',`${item.label} (${item.angle_deg}°)`);link.href=`${base(s)}/media/${item.media_id}/content?download=true`;link.download=item.name||`view-${item.angle_deg}.png`;
      card.append(img,link);grid.append(card);
    }
    s.batchHost.append(grid);
  }
  function inspect(s){s.inspector.replaceChildren(el('h2',msg("ui.object_properties")));const item=selected(s);if(!item)return;const camera=s.selected.kind==='camera';const controls=el('fieldset');controls.disabled=!!item.locked;s.inspector.append(controls);
    const name=field(msg("ui.object_name"),item.name);name.addEventListener('change',()=>change(s,()=>item.name=name.value));controls.append(name);
    for(const prop of camera?['position','target']:['position','rotation','scale']){const group=el('div',null,'ss-vector');group.append(el('label',{position:'位置',rotation:'旋转',scale:'缩放',target:'注视目标'}[prop]));item[prop].forEach((value,index)=>{const n=field(joinMessages(["",prop," ",'XYZ'[index],""]),value,'number');n.step='.1';n.addEventListener('change',()=>change(s,()=>item[prop][index]=Number(n.value)));group.append(n);});controls.append(group);}
    if(camera){
      const presets=s.options?.camera_presets||[];
      if(presets.length){
        const presetSel=el('select');bindAttribute(presetSel,'aria-label','机位预设');
        presetSel.append(localizedOption('','选择 14 种机位预设…'));
        for(const p of presets)presetSel.append(localizedOption(p.id,p.label));
        presetSel.addEventListener('change',()=>{
          const p=presets.find(x=>x.id===presetSel.value);if(!p)return;
          const focus=s.document.objects.find(o=>o.kind==='actor'&&o.visible!==false)||s.document.objects.find(o=>o.visible!==false&&o.kind!=='light')||{position:[0,0,0]};
          const basePos=focus.position||[0,0,0];
          change(s,()=>{
            item.position=[+(basePos[0]+p.offset[0]).toFixed(3),+(basePos[1]+p.offset[1]).toFixed(3),+(basePos[2]+p.offset[2]).toFixed(3)];
            item.target=[+(basePos[0]+p.target_offset[0]).toFixed(3),+(basePos[1]+p.target_offset[1]).toFixed(3),+(basePos[2]+p.target_offset[2]).toFixed(3)];
            item.fov=p.fov;
            if(p.roll)item.roll=p.roll;else delete item.roll;
          });
        });
        controls.append(el('label','机位预设'),presetSel);
      }
      const fov=field(msg("ui.field_of_view_fov"),item.fov,'number');fov.addEventListener('change',()=>change(s,()=>item.fov=Number(fov.value)));controls.append(el('label',msg("ui.field_of_view_fov")),fov);
      const roll=field('倾斜角 (Roll)',item.roll||0,'number');roll.min='-180';roll.max='180';roll.step='0.5';roll.addEventListener('change',()=>change(s,()=>{const v=Number(roll.value)||0;if(v)item.roll=v;else delete item.roll;}));controls.append(el('label','倾斜角 (Roll)'),roll);
      controls.append(button(s,'智能自动取景',async()=>{
        const targetActor=s.document.objects.find(o=>o.kind==='actor'&&o.visible!==false);
        const res=await ctx.api(`${base(s)}/spatial-auto-frame`,{method:'POST',headers:header(),body:JSON.stringify({payload:{document:clone(s.document),camera_id:item.id,...(targetActor?{target_object_id:targetActor.id}:{})}})});
        if(!live(s))return;
        change(s,()=>{item.position=res.camera.position;item.target=res.camera.target;if(res.camera.fov!=null)item.fov=res.camera.fov;});
        notice(s,res.warning||'已完成机位智能自动取景');
      }));
    }
    else{
      const color=field(msg("ui.object_color"),item.color,'color');color.addEventListener('change',()=>change(s,()=>item.color=color.value));controls.append(color);
      if(item.kind==='actor'){
        const bodyPresets=s.options?.body_presets||defaultBodyPresets;
        const bodySel=el('select');bindAttribute(bodySel,'aria-label','体型预设');
        bodySel.append(localizedOption('','自定义体型'));
        for(const bp of bodyPresets)bodySel.append(localizedOption(bp.id,bp.label));
        bodySel.value=item.body_preset||'';
        bodySel.addEventListener('change',()=>{
          const bp=bodyPresets.find(x=>x.id===bodySel.value);
          change(s,()=>{if(bp){item.body_preset=bp.id;item.scale=clone(bp.scale);item.color=bp.color;}else delete item.body_preset;});
        });
        controls.append(el('label','体型预设'),bodySel);
        const pose=el('select');bindAttribute(pose,'aria-label',msg("ui.character_pose"));
        const poseCatalog=s.options?.pose_catalog?.length?s.options.pose_catalog.map(p=>[p.id,p.label]):defaultPoses;
        for(const [value,label]of poseCatalog)pose.append(localizedOption(value,label));
        pose.value=item.pose;pose.addEventListener('change',()=>change(s,()=>item.pose=pose.value));controls.append(el('label',msg("ui.character_pose")),pose);
        const fkDetails=el('details');fkDetails.append(el('summary','骨骼关节 FK 细调 (7 组)'));
        const groups=s.options?.joint_groups?.length?s.options.joint_groups:defaultJointGroups;
        for(const grp of groups){
          const gBox=el('div',null,'ss-fk-group');gBox.append(el('strong',grp.label));
          for(const [axisKey,axisLabel]of grp.axes){
            const n=field(`${grp.label} ${axisLabel}`,item.joints[axisKey]||0,'number');n.min='-180';n.max='180';n.step='1';
            n.addEventListener('change',()=>change(s,()=>{const v=Number(n.value)||0;if(v)item.joints[axisKey]=v;else delete item.joints[axisKey];}));
            gBox.append(el('label',axisLabel),n);
          }
          fkDetails.append(gBox);
        }
        controls.append(fkDetails);
      }
    }
    if(item.geometry?.source_sha256){
      const sha=item.geometry.source_sha256,info=s.modelCatalog?.[sha];controls.append(el('h3',msg("ui.glb_animation")),el('p',msg("ui.source_retains_its_original_media_reference_the_timeline_samples")));
      if(!info||info.error){controls.append(el('p',info?.error||msg("ui.local_draft_model_has_not_been_loaded")),button(s,msg("ui.load_model_animation"),async()=>{const result=await ctx.api(`${base(s)}/spatial-model-import`,{method:'POST',headers:header(),body:JSON.stringify({media_id:item.media_id})});if(live(s)){Object.assign(s.modelCatalog,result.model_catalog||{});inspect(s);}}));}
      else{
        const scenes=el('select');bindAttribute(scenes,'aria-label',msg("ui.glb_scene"));for(const row of info.scenes||[])scenes.append(localizedOption(String(row.id),row.name));scenes.value=String(item.geometry.scene);scenes.addEventListener('change',()=>change(s,()=>item.geometry.scene=Number(scenes.value)));controls.append(scenes);
        const clips=el('select');bindAttribute(clips,'aria-label',msg("ui.glb_animation_clip"));clips.append(localizedOption('',msg("ui.original_static_pose")));for(const clip of info.clips||[])clips.append(localizedOption(String(clip.id),joinMessages(["",clip.name," · ",clip.duration.toFixed(2)," s"])));clips.value=item.animation.clip==null?'':String(item.animation.clip);clips.addEventListener('change',()=>change(s,()=>item.animation.clip=clips.value===''?null:Number(clips.value)));controls.append(clips);
        for(const [prop,title,min,max] of [['speed',msg("ui.animation_speed"),0,4],['offset',msg("ui.animation_offset_seconds"),-3600,3600]]){const input=field(title,item.animation[prop],'number');input.min=String(min);input.max=String(max);input.step='.1';input.addEventListener('change',()=>change(s,()=>item.animation[prop]=Number(input.value)));controls.append(el('label',title),input);}
        const loop=field(msg("ui.loop_glb_animation"),'','checkbox');loop.checked=item.animation.loop;loop.addEventListener('change',()=>change(s,()=>item.animation.loop=loop.checked));const label=el('label',msg("ui.loop_glb_animation"));label.append(loop);controls.append(label);
      }
    }
    controls.append(button(s,msg("ui.delete_selected"),()=>{if(camera&&s.document.cameras.length===1)throw new Error('至少保留一个机位。');change(s,()=>{const prop=camera?'cameras':'objects';s.document[prop]=s.document[prop].filter(n=>n!==item);if(camera){s.primary=s.document.cameras[0].id;s.secondary=s.document.cameras[1]?.id||s.primary;}s.selected={kind:'object',id:s.document.objects[0]?.id};});}));
    if(!camera){s.inspector.append(button(s,item.locked?msg("ui.unlock_object"):msg("ui.lock_object"),()=>change(s,()=>item.locked=!item.locked)),button(s,item.visible?msg("ui.hide_object"):msg("ui.show_object"),()=>change(s,()=>item.visible=!item.visible)));if(item.kind==='reference'&&item.media_id){const image=el('img');image.src=`${base(s)}/media/${item.media_id}/content`;bindAttribute(image,"alt",item.name);s.inspector.append(image);}}
    pathEditor(s,item,camera);
    s.inspector.append(el('p',msg("ui.value0_keyframes",{value0:item.keyframes?.length||0})));for(const frame of item.keyframes||[])s.inspector.append(button(s,msg("ui.delete_keyframe_at_value0_s",{value0:frame.time.toFixed(2)}),()=>{if(item.locked)throw new Error('先解锁对象。');change(s,()=>item.keyframes=item.keyframes.filter(f=>f!==frame));}));
  }
  function pathEditor(s,item,camera){
    const panel=el('section',null,'ss-path-editor');panel.append(el('h3',msg("ui.motion_path_xz_top_view")),el('p',msg("ui.drag_path_points_to_change_position_use_the_time")));s.inspector.append(panel);
    const frames=item.keyframes||[],extent=Math.max(5,...frames.flatMap(f=>[Math.abs(f.position[0]),Math.abs(f.position[2])]))+1,ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 240 200');bindAttribute(svg,'aria-label',msg("ui.editable_motion_path"));svg.classList.add('ss-path-map');panel.append(svg);const point=f=>[120+f.position[0]/extent*110,100+f.position[2]/extent*90];
    const line=document.createElementNS(ns,'polyline');line.setAttribute('points',frames.map(f=>point(f).join(',')).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','currentColor');svg.append(line);
    frames.forEach((frame,index)=>{const circle=document.createElementNS(ns,'circle'),[x,y]=point(frame);circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',6);circle.setAttribute('tabindex','0');circle.setAttribute('role','button');bindAttribute(circle,'aria-label',msg("ui.path_point_value0_value1_seconds",{value0:index+1,value1:frame.time}));const title=document.createElementNS(ns,'title');setText(title,joinMessages(["",frame.time,"s · ",frame.position.join(', '),""]));circle.append(title);svg.append(circle);
      circle.addEventListener('pointerdown',event=>{if(item.locked||event.button!==0)return;event.preventDefault();s.undo.push(clone({document:s.document,title:s.title,description:s.description}));s.redo=[];circle.setPointerCapture(event.pointerId);const move=e=>{if(!live(s))return;const rect=svg.getBoundingClientRect();frame.position[0]=Math.round(((e.clientX-rect.left)/rect.width*240-120)/110*extent*10)/10;frame.position[2]=Math.round(((e.clientY-rect.top)/rect.height*200-100)/90*extent*10)/10;const [px,py]=point(frame);circle.setAttribute('cx',px);circle.setAttribute('cy',py);line.setAttribute('points',frames.map(f=>point(f).join(',')).join(' '));changed(s);};const up=()=>{circle.removeEventListener('pointermove',move);circle.removeEventListener('pointerup',up);circle.removeEventListener('pointercancel',up);if(live(s))inspect(s);};circle.addEventListener('pointermove',move);circle.addEventListener('pointerup',up);circle.addEventListener('pointercancel',up);});
      const row=el('fieldset',null,'ss-path-key');row.disabled=Boolean(item.locked);row.append(el('legend',msg("ui.path_point_value0",{value0:index+1})));const time=field(msg("ui.path_point_value0_time",{value0:index+1}),frame.time,'range');time.min=0;time.max=s.document.duration;time.step=.01;row.append(time,el('output',joinMessages([frame.time," s"])));time.addEventListener('change',()=>{const at=Number(time.value);if(frames.some(f=>f!==frame&&f.time===at)){notice(s,msg("ui.two_path_points_cannot_share_the_same_time"));time.value=frame.time;return;}change(s,()=>{frame.time=at;frames.sort((a,b)=>a.time-b.time);});});
      for(const prop of camera?['position','target']:['position','rotation']){const values=frame[prop]||item[prop];const group=el('div',null,'ss-vector');group.append(el('span',prop==='position'?msg("ui.position"):prop==='target'?msg("ui.look_at_point"):msg("ui.rotation")));values.forEach((value,axis)=>{const control=field(msg("ui.path_point_value0_value1_value2",{value0:index+1,value1:prop,value2:'XYZ'[axis]}),value,'number');control.step=.1;control.addEventListener('change',()=>change(s,()=>{frame[prop]=clone(frame[prop]||item[prop]);frame[prop][axis]=Number(control.value);}));group.append(control);});row.append(group);}panel.append(row);
    });
  }
  function undo(s,redo){const from=redo?s.redo:s.undo,to=redo?s.undo:s.redo;if(!from.length)return;to.push(clone({document:s.document,title:s.title,description:s.description}));Object.assign(s,from.pop());changed(s);drawEditor(s);}
  function orbit(s,image){image.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();const start=[event.clientX,event.clientY],camera=s.document.cameras.find(c=>c.id===s.primary),item=event.shiftKey?selected(s):camera;if(!item||item.locked)return;const origin=clone(item.position),target=camera.target;let moved=false;image.setPointerCapture(event.pointerId);const move=e=>{if(!live(s))return;const dx=e.clientX-start[0],dy=e.clientY-start[1];if(!moved){s.undo.push(clone({document:s.document,title:s.title,description:s.description}));s.redo=[];moved=true;}if(event.shiftKey)item.position=[origin[0]+dx*.02,origin[1],origin[2]+dy*.02];else{const x=origin[0]-target[0],z=origin[2]-target[2],angle=dx*.01;item.position=[target[0]+x*Math.cos(angle)+z*Math.sin(angle),origin[1]+dy*.025,target[2]-x*Math.sin(angle)+z*Math.cos(angle)];}changed(s);};const up=()=>{image.removeEventListener('pointermove',move);image.removeEventListener('pointerup',up);image.removeEventListener('pointercancel',up);if(live(s)&&moved)inspect(s);};image.addEventListener('pointermove',move);image.addEventListener('pointerup',up);image.addEventListener('pointercancel',up);});}
  async function fetchPreview(s,document,camera,time,signal){const result=await fetch(`${base(s)}/spatial-preview`,{method:'POST',headers:header(),body:JSON.stringify({document,camera_id:camera,time}),signal});if(!result.ok){let error;try{error=await result.json();}catch{}throw new Error(error?.message||error?.detail||'场景预览失败');}return result.blob();}
  function previewSoon(s,delay=160){if(!live(s)||!s.views)return;clearTimeout(s.previewTimer);s.previewTimer=setTimeout(()=>preview(s),delay);}
  async function preview(s){const seq=++s.previewSeq;s.previewAbort?.abort();const abort=new AbortController();s.previewAbort=abort;const document=clone(s.document),time=s.time;try{const results=await Promise.all([s.primary,s.secondary].map(camera=>fetchPreview(s,document,camera,time,abort.signal)));if(!live(s)||seq!==s.previewSeq)return;for(const url of s.urls)URL.revokeObjectURL(url);s.urls=results.map(blob=>URL.createObjectURL(blob));s.views.forEach((view,i)=>{view.image.src=s.urls[i];setText(view.caption,joinMessages(["",time.toFixed(2)," s · ",s.dirty?msg("spatial.local_draft"):msg("spatial.saved_version",{value0:s.version}),""]));});}catch(e){if(e.name!=='AbortError')notice(s,msg("ui.value0_scene_draft_preserved",{value0:e.message}));}}
  async function mediaPicker(s,kind,offset=0){const isImage=kind==='reference'||kind==='panorama';const data=await ctx.api(`${base(s)}/media?limit=30&offset=${offset}${isImage?'&modality=image':''}`);if(!live(s))return;const picker=el('section',null,'ss-picker');picker.append(el('h3',kind==='panorama'?'选择 720° 全景天空图':kind==='reference'?msg("ui.choose_comparison_image"):msg("ui.choose_registered_glb")),el('p',msg("ui.upload_from_project_media_this_picker_consumes_the_original")));
    for(const media of data.items||[]){if(kind==='model'&&!/\.glb$|gltf|glb/i.test((media.name||'')+' '+(media.mime_type||'')))continue;picker.append(button(s,media.name||media.id,async()=>{if(kind==='panorama')change(s,()=>{s.document.panorama_media_id=media.id;s.document.sphere_radius=s.document.sphere_radius||45;editor(s);});else if(kind==='reference')change(s,()=>{const id=crypto.randomUUID();s.document.objects.push({id,kind:'reference',name:media.name,position:[0,0,0],rotation:[0,0,0],scale:[1,1,1],color:'#ffffff',visible:true,locked:false,pose:'stand',joints:{},keyframes:[],media_id:media.id});s.selected={kind:'object',id};});else{const imported=await ctx.api(`${base(s)}/spatial-model-import`,{method:'POST',headers:header(),body:JSON.stringify({media_id:media.id})});if(live(s))change(s,()=>{Object.assign(s.modelCatalog,imported.model_catalog||{});for(const item of imported.objects){const id=crypto.randomUUID();s.document.objects.push({...item,id});s.selected={kind:'object',id};}});}picker.remove();}));}if(data.total>offset+30)picker.append(button(s,msg("common.next_page"),()=>mediaPicker(s,kind,offset+30)));picker.append(button(s,msg("ui.close_picker"),()=>picker.remove()));s.root.append(picker);}
  async function refreshExports(s){const data=await ctx.api(sceneUrl(s));if(!live(s))return;revision(s,data.revision);s.jobs=data.exports||[];drawExports(s);clearTimeout(s.poll);if(s.jobs.some(j=>j.status==='running'||j.status==='queued'))s.poll=setTimeout(()=>refreshExports(s).catch(e=>notice(s,e.message)),900);}
  function drawExports(s){s.exports.replaceChildren();for(const job of s.jobs||[]){const card=el('article',null,'ss-export');card.dataset.exportId=job.id;card.append(el('p',msg("ui.value0_version_value1_value2_value3_s_value4_value5_value6",{value0:job.format.toUpperCase(),value1:job.scene_version,value2:job.camera_id,value3:Number(job.time).toFixed(2),value4:job.status,value5:job.progress_frames,value6:job.total_frames})));
      if(job.status==='succeeded'&&job.output){const link=el('a',msg("ui.open_original_media"));link.href=`${base(s)}/media/${job.output.media_id}/content`;link.target='_blank';link.rel='noopener';card.append(link);if(job.format!=='glb'){const origin=read(`vsc-spatial-origin:${s.project}:${s.id}`);if(origin?.kind==='canvas'){card.append(button(s,msg("ui.return_output_to_original_canvas_with_source_connection"),()=>returnCanvas(s,job,origin)),button(s,msg("ui.load_target_s_new_version_before_applying_again"),async()=>{const current=await ctx.api(`${base(s)}/creative-canvases/${origin.target_canvas_id}`);if(!live(s))return;revision(s,current.revision);origin.canvas_revision=current.canvas_revision;persist(`vsc-spatial-origin:${s.project}:${s.id}`,origin);notice(s,msg("ui.target_canvas_s_new_version_loaded_select_return_to"));}));}else if(origin?.kind==='intelligent'){card.append(button(s,msg("ui.use_this_staging_and_return_to_intelligent_production"),()=>{persist(`vsc-intelligent-spatial-return:${s.project}:${origin.workflow_id}:${origin.unit_key}`,{workflow_id:origin.workflow_id,unit_key:origin.unit_key,version_id:origin.version_id,spatial_version_id:job.version_id,spatial_export_id:job.id,media_id:job.output.media_id});const target=new URL(origin.return_url,location.href);if(target.origin!==location.origin)throw new Error('返回地址不属于当前工作台');location.assign(target.href);}));}else card.append(button(s,msg("ui.create_canvas_from_output_with_source_connection"),async()=>{const created=await durable(s,'canvas:'+job.id,`${base(s)}/spatial-exports/${job.id}/canvas`,{});notice(s,msg("ui.canvas_created_with_source_connection"));const target=new URL(location.href);target.search=new URLSearchParams({page:'creative-canvas',project:s.project,task_target:created.id});location.assign(target.href);}));}}
      else if(job.status!=='cancelled'){card.append(button(s,job.status==='running'?msg("ui.query_recover_original_task"):msg("ui.execute_retry_original_task"),()=>execute(s,job.id)),button(s,msg("ui.cancel_export"),async()=>{await refreshExports(s);await durable(s,'cancel:'+job.id,`${base(s)}/spatial-exports/${job.id}/cancel`,{});await refreshExports(s);}));if(job.error)card.append(el('p',job.error));}s.exports.append(card);}}
  async function execute(s,id){if(!live(s))return;notice(s,msg("ui.executing_registered_export_task"));s.poll=setTimeout(()=>refreshExports(s).catch(()=>{}),300);try{const result=await ctx.api(`${base(s)}/spatial-exports/${id}/execute`,{method:'POST',headers:header()});if(live(s))notice(s,result.status==='succeeded'?msg("ui.output_registered_in_original_project_media"):msg("ui.original_task_status_value0",{value0:result.status}));}catch(e){notice(s,msg("ui.value0_query_and_recover_this_original_task_without_creating",{value0:e.message}));}finally{if(live(s))await refreshExports(s);}}
  function cleanup(s){clearInterval(s.play);clearTimeout(s.previewTimer);clearTimeout(s.poll);s.previewAbort?.abort();for(const url of s.urls||[])URL.revokeObjectURL(url);}
  function suspend(){if(active){remember(active);cleanup(active);}active=null;epoch++;}
  return {load,suspend};
}
