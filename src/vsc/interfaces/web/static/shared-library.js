import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Global shared library: a fixed library version is used through the original
   target-project transaction. This module never reads a source project's media. */
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)setText(node,text);if(cls)node.className=cls;return node;};
export function createSharedLibrary(ctx){
  let ticket=0,offset=0,query='',category='',dialog=null;
  const button=(text,action)=>{const node=el('button',text);node.type='button';node.addEventListener('click',async()=>{if(node.disabled)return;try{await action();}catch(error){ctx.notice(error.message);}});return node;};
  const headers=()=>({'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf});
  const purposes=[['first_frame','镜头首帧'],['composition','构图参考'],['identity_face','人物正脸'],['location_master','场景母版'],['vfx_overlay','透明特效叠层'],['voice_sample','声音参考'],['ambience','环境声'],['music','配乐'],['sfx','音效']];
  function entryForm(root,{media=null,projectId=null,onDone}={}){
    const formTicket=ticket;
    const form=el('form',null,'library-entry-form');form.append(el('h2',media?msg("ui.publish_current_media_to_the_shared_library"):msg("ui.import_shared_media")));
    const field=(text,kind='input')=>{const label=el('label',text),input=el(kind);input.name=text;input.autocomplete='off';bindAttribute(input,'aria-label',text);label.append(input);form.append(label);return input;};
    const title=field('共享名称');title.required=true;title.value=media?.name||'';
    const description=field('公开说明','textarea');description.required=true;description.rows=3;
    const category=field('类别','select');for(const [value,text]of [['image',msg("agent.media_image")],['audio',msg("agent.audio")],['video',msg("common.route_video")],['specification',msg("ui.specification_only")]]){const option=el('option',text);option.value=value;category.append(option);}category.value=media?.modality||'image';
    const specification=field('规格或使用说明（纯规格导入必填）','textarea');specification.rows=3;
    let file=null;if(!media){file=field('原文件（纯规格可留空）');file.type='file';}
    const rights=field('来源许可','select');for(const [value,text]of [['owned',msg("ui.i_own_shareable_rights")],['licensed',msg("ui.authorized_for_workspace_reuse")]]){const option=el('option',text);option.value=value;rights.append(option);}
    const evidence=field('许可依据（仅公开可分享的说明）','textarea');evidence.required=true;evidence.rows=3;
    const allowed=el('fieldset');allowed.append(el('legend',msg("ui.allowed_purposes")));const checks=[];for(const [value,text]of purposes){const label=el('label',text),check=el('input');check.type='checkbox';check.value=value;label.prepend(check);allowed.append(label);checks.push(check);}form.append(allowed);
    const consent=el('label',msg("ui.i_confirm_this_fixed_content_may_be_reused_across")),check=el('input');check.type='checkbox';check.required=true;consent.prepend(check);form.append(consent);
    const submit=el('button',media?msg("ui.confirm_publication_of_fixed_media"):msg("ui.confirm_shared_media_import"));submit.type='submit';const status=el('p');status.setAttribute('role','status');form.append(submit,status);root.append(form);
    let identity=null,staged=null;
    form.addEventListener('input',()=>{identity=null;});file?.addEventListener('change',()=>{staged=null;});
    form.addEventListener('submit',async event=>{event.preventDefault();if(submit.disabled)return;const allowed_purposes=checks.filter(c=>c.checked).map(c=>c.value);if(!allowed_purposes.length){setText(status,msg("ui.select_explicit_allowed_purposes"));return;}if(!media&&!file.files?.length&&!specification.value.trim()){setText(status,msg("ui.select_an_original_file_or_enter_an_independent_specification"));return;}
      if(!ctx.session().actor){setText(status,msg("ui.establish_an_operation_session_before_importing_shared_content"));return;}submit.disabled=true;identity ||= crypto.randomUUID();
      try{if(formTicket!==ticket)throw new Error('所见页面已切换，请回到原处继续。');const payload={library_key:'shared-'+identity,title:title.value,category:category.value,description:description.value,specification:specification.value.trim()?{description:specification.value}:{},allowed_purposes,license:{outcome:rights.value,allow_workspace_reuse:check.checked,evidence:evidence.value},members:[]};
        let url;if(media){url=`/api/v1/projects/${encodeURIComponent(projectId)}/library/publish`;payload.members=[{media_id:media.id,member_key:'reference',role:allowed_purposes[0]}];}
        else{url='/api/v1/library/import';payload.import_key=identity;if(file.files?.length){staged ||= await ctx.api('/api/v1/library/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.files[0].name),'X-CSRF-Token':ctx.session().csrf},body:file.files[0]});payload.members=[{staged_upload:staged.staged_upload,member_key:'reference',role:allowed_purposes[0]}];}}
        if(formTicket!==ticket)return;const result=await ctx.api(url,{method:'POST',headers:headers(),body:JSON.stringify({payload,confirmed:true,expected_revision:ctx.session().revision,idempotency_key:identity})});if(formTicket!==ticket)return;if(result.revision!=null)ctx.setRevision(result.revision);setText(status,msg("ui.fixed_shared_version_registered"));onDone?.(result);
      }catch(error){setText(status,msg("ui.value0_inputs_are_preserved_correct_them_to_continue",{value0:error.message}));}finally{submit.disabled=false;}
    });return form;
  }
  function preview(member){
    if(!member.preview_url)return el('p',msg("ui.no_readable_preview_exists_for_this_fixed_version"),'hint');
    const media=el(member.modality==='image'?'img':member.modality==='audio'?'audio':member.modality==='video'?'video':'a');
    if(media.tagName==='A'){media.href=member.preview_url;setText(media,msg("ui.read_fixed_media"));}
    else{media.src=member.preview_url;if(member.modality==='image'){bindAttribute(media,"alt",msg("ui.shared_media_preview"));media.width=320;media.height=240;media.loading='lazy';}else{media.controls=true;media.preload='metadata';}}
    media.addEventListener('error',()=>{const message=el('p',msg("ui.preview_loading_is_blocked_read_it_again_the_original"),'hint');media.replaceWith(message);},{once:true});return media;
  }
  async function render(root,target=null){
    const current=++ticket;root.className='shared-library';root.replaceChildren();
    const header=el('header',null,'library-header');header.append(el('h1',target?msg("ui.choose_shared_media_for_the_current_object"):msg("shell.shared_library")));
    if(target)header.append(el('p',msg("ui.use_for_value0_in_the_current_object_return_to",{value0:target.role}),'hint'));
    root.append(header);
    root.append(el('p',msg("ui.the_legacy_library_remains_under_its_original_records_and"),'hint'));
    if(!target&&ctx.session().actor){const add=el('details',null,'library-import');add.append(el('summary',msg("ui.import_shared_media_no_project_required")));const body=el('div');add.append(body);entryForm(body,{onDone:()=>render(root,target)});root.append(add);}
    const form=el('form',null,'library-search'),search=el('input');search.type='search';search.name='library_query';search.value=query;bindAttribute(search,"placeholder",msg("ui.search_shared_media"));bindAttribute(search,'aria-label',msg("ui.search_shared_media_extra_157"));
    const filter=el('input');filter.name='library_category';filter.value=category;bindAttribute(filter,"placeholder",msg("ui.category_optional"));bindAttribute(filter,'aria-label',msg("ui.shared_media_category"));
    const submit=el('button',msg("ui.find"));submit.type='submit';form.append(search,filter,submit);root.append(form);
    form.addEventListener('submit',event=>{event.preventDefault();query=search.value;category=filter.value;offset=0;render(root,target);});
    const content=el('section',null,'library-results'),status=el('p',msg("ui.loading_shared_media"),'hint');status.setAttribute('role','status');content.append(status);root.append(content);
    try{
      const data=await ctx.api('/api/v1/library?'+new URLSearchParams({query,category,offset:String(offset),limit:'24'}));if(current!==ticket)return;
      content.replaceChildren();
      for(const row of data.items||[]){const card=el('article',null,'library-card');card.append(el('h2',row.title),el('p',row.description||msg("ui.fixed_version_value0",{value0:row.version||''}),'hint'));
        const member=row.members?.[0];if(member)card.append(preview(member));
        card.append(button(msg("ui.view_fixed_version"),()=>detail(root,row.current_version_id||row.version_id,target)));content.append(card);}
      if(!data.items?.length)content.append(el('p',msg("ui.no_matching_shared_media_project_media_enters_the_shared"),'empty'));
      const paging=el('nav',null,'library-pagination');for(const [label,next]of [[msg("common.previous_page"),offset>0?Math.max(0,offset-24):null],[msg("common.next_page"),offset+(data.items?.length||0)<data.total?offset+24:null]]){const b=button(label,()=>{offset=next;return render(root,target);});b.disabled=next==null;paging.append(b);}root.append(paging);
    }catch(error){if(current===ticket)content.replaceChildren(el('p',msg("ui.shared_library_could_not_be_loaded_value0",{value0:error.message})),button(msg("ui.reload"),()=>render(root,target)));}
  }
  async function detail(root,versionId,target){
    const current=++ticket;root.replaceChildren(el('p',msg("ui.loading_fixed_version"),'hint'));
    try{
      const row=await ctx.api(`/api/v1/library/versions/${encodeURIComponent(versionId)}`);if(current!==ticket)return;
      root.replaceChildren(button(msg("ui.back_to_media_list"),()=>render(root,target)),el('h1',row.title),el('p',row.description||''));
      if(row.specification&&Object.keys(row.specification).length){const section=el('section',null,'library-specification');section.append(el('h2',row.members?.length?msg("ui.specification_and_usage_notes"):msg("ui.specification_content_only")));
        const {renderArtifactContent}=await import('./artifact-reader.js');if(current!==ticket)return;section.append(renderArtifactContent(row.specification,{mimeType:'application/json'}).body);root.append(section);
      }
      if(!row.members?.length)root.append(el('p',msg("ui.this_entry_contains_specifications_only_without_image_video_or"),'hint'));
      for(const member of row.members||[]){const card=el('article',null,'library-member');card.append(el('h2',member.member_key),preview(member));
        if(target){const use=button(msg("ui.check_and_use_here"),async()=>{
          if(!ctx.session().actor||!(ctx.canWrite?.(target.projectId)??ctx.session().writable))throw new Error('请建立当前目标项目的操作会话后再使用。');
          use.disabled=true;const status=el('p',msg("ui.checking_the_current_target_and_purpose"));status.setAttribute('role','status');card.append(status);
          const payload={library_version_id:versionId,member_key:member.member_key,target_object_id:target.target_object_id,role:target.role,select:true};
          try{const base=`/api/v1/projects/${encodeURIComponent(target.projectId)}/library`,headers={'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf};
            const check=await ctx.api(`${base}/preview-use`,{method:'POST',headers,body:JSON.stringify({payload})});
            if(current!==ticket)return;
            if(!check.available){setText(status,(check.gaps||[]).map(g=>g.message).join('；')||msg("ui.the_current_target_does_not_meet_usage_requirements"));return;}
            if(!confirm('确认将此固定共享版本用于当前对象和用途？目标项目将保留独立的来源、权利与采用记录。'))return;
            // Retain this intent across a failed response; clicking again restores
            // the same original receipt rather than creating another candidate.
            const keyName=JSON.stringify([target.projectId,versionId,member.member_key,target.target_object_id,target.role]);
            let key;try{key=sessionStorage.getItem('vsc-library-use:'+keyName);if(!key){key=crypto.randomUUID();sessionStorage.setItem('vsc-library-use:'+keyName,key);}}catch{key=crypto.randomUUID();}
            const result=await ctx.api(`${base}/use`,{method:'POST',headers,body:JSON.stringify({payload,expected_revision:check.revision,idempotency_key:key,confirmed:true})});
            if(current!==ticket)return;ctx.setRevision(result.revision,target.projectId);setText(status,result.selected?msg("ui.used_here_the_selection_record_is_saved"):msg("ui.candidate_registered_but_not_selected"));
            if(dialog?.open){dialog.addEventListener('close',()=>target.onUsed?.(result),{once:true});dialog.close('used');}else target.onUsed?.(result);
          }finally{if(current===ticket)use.disabled=false;}
        });card.append(use);}else card.append(button(msg("ui.use_in_a_project_shot"),()=>targetPicker(root,row,member)));root.append(card);}
      root.append(el('p',msg("ui.applicable_purpose_value0",{value0:(row.allowed_purposes||[]).join('、')||msg("ui.subject_to_target_project_checks")}),'hint'));
      if(!target&&ctx.session().actor){const lifecycle=el('details',null,'library-lifecycle');lifecycle.append(el('summary',msg("ui.stop_recommending_or_withdraw_shared_rights")));const label=el('label',msg("ui.reason")),reason=el('textarea'),status=el('p');bindAttribute(reason,'aria-label',msg("ui.reason_for_disabling_or_revoking_access"));status.setAttribute('role','status');label.append(reason);lifecycle.append(label);for(const [outcome,text]of [['retire',msg("ui.stop_recommending_this_item")],['revoke_rights',msg("ui.withdraw_sharing_rights")]])lifecycle.append(button(text,async()=>{if(!reason.value.trim()){setText(status,msg("ui.enter_a_specific_reason"));return;}if(!confirm(outcome==='retire'?'停止新推荐，合法历史引用仍可保留。确认？':'撤回共享权利会影响后续正式使用，确认？'))return;try{await ctx.api(`/api/v1/library/entries/${encodeURIComponent(row.id)}/retire`,{method:'POST',headers:headers(),body:JSON.stringify({payload:{outcome,reason:reason.value},confirmed:true,idempotency_key:crypto.randomUUID()})});await render(root,target);}catch(error){setText(status,error.message);}}));lifecycle.append(status);root.append(lifecycle);}
    }catch(error){if(current===ticket)root.replaceChildren(el('p',error.message),button(msg("ui.back_to_media_list"),()=>render(root,target)));}
  }
  async function targetPicker(root,version,member,resume={}){
    const current=++ticket,section=el('section',null,'library-target-picker');root.replaceChildren(section);
    section.append(button(msg("ui.back_to_fixed_media_details"),()=>detail(root,version.library_version_id||version.version_id,null)),el('h2',msg("ui.choose_one_target_project_shot_and_purpose")));
    const projectLabel=el('label',msg("ui.target_project")),project=el('select'),roleLabel=el('label',msg("ui.use_for")),role=el('select'),results=el('div');bindAttribute(project,'aria-label',msg("ui.target_project"));bindAttribute(role,'aria-label',msg("ui.media_purpose"));projectLabel.append(project);roleLabel.append(role);section.append(projectLabel,roleLabel,results);
    const empty=el('option',msg("ui.select_a_project"));empty.value='';project.append(empty);
    for(const row of ctx.projects?.()||[]){const option=el('option',row.name);option.value=row.id;option.disabled=ctx.canWrite?.(row.id)===false;project.append(option);}
    if(resume.projectId)project.value=resume.projectId;
    const allowed=version.allowed_purposes?.includes('*')?purposes.map(([value])=>value):version.allowed_purposes||[];
    for(const value of allowed){const option=el('option',purposes.find(([key])=>key===value)?.[1]||value);option.value=value;role.append(option);}
    if(resume.role)role.value=resume.role;
    let request=0;
    const read=async(scope=null,offset=0)=>{const projectId=project.value;if(!projectId){setText(results,msg("ui.select_a_target_project_then_locate_a_shot_in"));return;}const call=++request;setText(results,msg("ui.loading_target_directory"));try{const params=new URLSearchParams({section:'children',limit:'24',offset:String(offset)});if(scope)params.set('object_id',scope);const data=await ctx.api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?${params}`);if(current!==ticket||call!==request||projectId!==project.value)return;results.replaceChildren();const trail=el('nav');bindAttribute(trail,'aria-label',msg("ui.target_directory"));trail.append(button(msg("ui.project_directory"),()=>read()));for(const ancestor of data.ancestors||[])trail.append(button(ancestor.title||ancestor.display_code,()=>read(ancestor.id)));results.append(trail);
        if(data.scope)results.append(el('h3',data.scope.title||data.scope.display_code));
        if(data.scope?.kind==='shot')results.append(button(msg("ui.confirm_use_in_this_shot"),()=>choose({projectId,target_object_id:data.scope.id,role:role.value,
          onCancel:()=>targetPicker(root,version,member,{projectId,objectId:data.scope.id,role:role.value}),
          onUsed:()=>{ctx.notice(msg("ui.fixed_shared_media_used_in_the_selected_project_and"));return detail(root,version.library_version_id||version.version_id,null);}},version.library_version_id||version.version_id)));
        for(const row of data.sections?.children?.items||[])if(['work','episode','scene','sequence','shot'].includes(row.kind))results.append(button(row.title||row.display_code,()=>read(row.id)));
        const next=data.sections?.children?.next_offset;if(offset)results.append(button(msg("common.previous_page"),()=>read(scope,Math.max(0,offset-24))));if(next!=null)results.append(button(msg("common.next_page"),()=>read(scope,next)));
        if(!data.sections?.children?.items?.length&&data.scope?.kind!=='shot')results.append(el('p',msg("ui.this_directory_has_no_shots_yet_continue_building_content"),'hint'));
      }catch(error){if(current===ticket&&call===request)setText(results,error.message);}};
    project.addEventListener('change',()=>read());await read(resume.objectId||null);
  }
  async function choose(target,versionId=null){
    if(!target.projectId||!target.target_object_id||!target.role)throw new Error('请先定位具体对象和用途，再从此处选择共享素材。');
    if(!dialog){dialog=el('dialog',null,'library-dialog');bindAttribute(dialog,'aria-label',msg("ui.choose_shared_media_for_the_current_object"));document.body.append(dialog);dialog.addEventListener('close',()=>{ticket++;dialog.querySelectorAll('audio,video').forEach(node=>node.pause());});}
    const prior=document.activeElement;dialog.replaceChildren();dialog.returnValue='';const close=button(msg("ui.cancel_and_return"),()=>dialog.close('cancel')),body=el('div');dialog.append(close,body);dialog.addEventListener('close',()=>{prior?.focus?.();if(dialog.returnValue!=='used')target.onCancel?.();},{once:true});dialog.showModal();if(versionId)await detail(body,versionId,target);else await render(body,target);
  }
  return {load:root=>render(root),choose,suspend:()=>{ticket++;},publish:(root,media,projectId)=>entryForm(root,{media,projectId,onDone:()=>ctx.notice(msg("ui.current_fixed_media_published_to_the_shared_library_view"))})};
}
