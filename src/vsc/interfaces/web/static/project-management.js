import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const names={work:'部',episode:'集',scene:'场',sequence:'镜组',shot:'镜头',asset:'资产',image:'图片',video:'视频',audio:'音频',active:'可用',trashed:'已回收',parent_trashed:'父级已回收'};
export function createProjectManagement(root,ctx){
  let ticket=0,project=null,data=null,busy=false,identity=null,recycleCategory='all',recycleSeq=0,recycleState=null,recycleOpening=null,filters={folder:'',kind:'',q:'',offset:0};
  const drafts=new Map(),pending=new Map(),inFlight=new Set(),recycleOrigins=new Map();
  const endpoint=p=>`/api/v1/projects/${encodeURIComponent(p)}/management`;
  const session=()=>ctx.session();
  const actorKey=()=>session().identityId||session().actor||'reader';
  const scopeKey=()=>actorKey()+'|'+project;
  const same=(t,p)=>ticket===t&&project===p&&identity===actorKey();
  function button(label,fn,disabled=false){const b=el('button',label);b.type='button';b.disabled=disabled;b.onclick=async()=>{if(b.disabled)return;const t=ticket,p=project;try{await fn();}catch(e){if(same(t,p))ctx.notice(e.message);}};return b;}
  function field(parent,title,input,key,initial=''){const label=el('label',title,'field');bindAttribute(input,'aria-label',title);if(key){input.value=drafts.get(scopeKey()+':'+key)??initial;input.addEventListener('input',()=>drafts.set(scopeKey()+':'+key,input.value));}label.append(input);parent.append(label);return input;}
  function form(title){const n=el('form',null,'management-form');n.append(el('h3',title));return n;}
  function selector(withRoot=true){const s=el('select');if(withRoot)s.append(localizedOption('',msg("ui.unclassified_root_directory")));for(const f of data.folders)s.append(localizedOption(f.id,folderLabel(f.id)));return s;}
  function folderLabel(id){const seen=new Set(),parts=[];while(id&&!seen.has(id)){seen.add(id);const f=data.folders.find(x=>x.id===id);if(!f)break;parts.unshift(f.title);id=f.parent_id;}return parts.join(' / ');}
  function submit(form,label,build){const b=el('button',label);b.type='submit';b.disabled=!session().actor||busy;form.append(b);form.onsubmit=async e=>{e.preventDefault();const t=ticket,p=project;try{await write(build());}catch(error){if(same(t,p))ctx.notice(error.message);}};}
  async function write(payload,resume=false){
    if(!session().actor)throw new Error('请先建立操作会话');
    const p=project,t=ticket,key=scopeKey();
    if(busy||inFlight.has(key))throw new Error('当前操作尚未完成');
    if(pending.has(key)&&!resume)throw new Error('上次操作回执未知，请先恢复原请求');
    let request=pending.get(key);if(!request){request=payload.target_type==='media'&&payload.operation==='restore'?{payload:{media_ids:[payload.target_id],action:'restore',reason:payload.reason},expected_revision:data.revision,idempotency_key:crypto.randomUUID(),confirmed:true}:{payload,expected_revision:data.revision,idempotency_key:crypto.randomUUID()};pending.set(key,request);}
    busy=true;inFlight.add(key);render();
    try{const result=await ctx.api(request.confirmed?`/api/v1/projects/${encodeURIComponent(p)}/recycle-actions`:endpoint(p),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request)});pending.delete(key);
      if(!same(t,p))return;ctx.setRevision?.(result.revision,p);
      if(result.status==='protected')ctx.notice(msg("ui.action_not_executed_value0",{value0:result.reasons.map(r=>r.message+'（'+r.table+'）').join('；')}));
      else ctx.notice(result.unchanged?msg("ui.state_already_matches"):msg("ui.saved_original_identity_and_fixed_audit_retained"));
      try{await ctx.onProjectsChanged?.();}catch(error){if(same(t,p))ctx.notice('操作已保存，但项目列表刷新失败：'+error.message);}if(!same(t,p))return;await load({project:p,keepFilters:true});return result;
    }catch(error){if(error.status>=400&&error.status<500)pending.delete(key);if(same(t,p)){busy=false;render();}throw error;}
    finally{inFlight.delete(key);if(same(t,p)){busy=false;render();}}
  }
  function lifecycle(target,operation,onSuccess=null,onStart=null){
    const dialog=el('dialog'),f=form(operation==='purge'?'永久停用（保留审计）':operation==='trash'?'移入回收':'恢复原关系');
    f.append(el('p',target.title));if(operation==='purge')f.append(el('p',msg("ui.this_action_cannot_be_undone_fixed_identities_evidence_and")));
    const reason=field(f,msg("ui.reason_for_this_action"),el('input'),'reason:'+target.id+operation);reason.required=true;reason.maxLength=2000;
    const confirm=operation==='purge'?field(f,msg("ui.enter_the_complete_target_name"),el('input'),null):null;if(confirm)confirm.required=true;
    const save=el('button',operation==='purge'?msg("ui.confirm_permanent_deactivation"):operation==='trash'?msg("ui.confirm_recycling"):msg("ui.confirm_restore"));save.type='submit';f.append(save,button(msg("common.cancel"),()=>dialog.close()));
    const p=project,t=ticket,key=scopeKey();f.onsubmit=async e=>{e.preventDefault();if(save.disabled)return;if(!same(t,p)){dialog.close();return;}save.disabled=true;try{onStart?.();const result=await write({operation,target_type:target.type,target_id:target.id,reason:reason.value,...(confirm?{confirm_name:confirm.value}:{})});dialog.close();if(result&&result.status!=='protected'&&onSuccess&&project===p&&identity===actorKey())await onSuccess();}catch(error){if(same(t,p)){ctx.notice(error.status===409?error.message+'；输入已保留，请关闭窗口并刷新当前项目后重试。':error.message);save.disabled=false;}}};
    dialog.append(f);root.append(dialog);dialog.onclose=()=>{dialog.remove();if(!pending.has(key)&&recycleOrigins.get(key)?.target_id===target.id)recycleOrigins.delete(key);if(same(t,p))render();};dialog.showModal();
  }
  async function returnToRecycle(){ctx.onScope?.(null);await load({project:null});}
  async function recoverPending(){const key=scopeKey(),request=pending.get(key),origin=recycleOrigins.get(key),result=await write(null,true);if(!result)return;const original=request?.payload.operation==='restore'&&request.payload.target_id===origin?.target_id||request?.confirmed&&request.payload.action==='restore'&&request.payload.media_ids?.length===1&&request.payload.media_ids[0]===origin?.target_id;if(result.status!=='protected'&&origin&&original&&project===origin.project_id&&identity===actorKey()){recycleOrigins.delete(key);await returnToRecycle();}}
  async function restoreFromList(row){
    if(recycleOpening||!row.can_restore||!session().actor)return;const opening={};recycleOpening=opening;
    try{const p=row.project_id,owner=actorKey(),known=data?.projects?.find(item=>item.id===p);ctx.onScope?.(p,known||{id:p,name:row.title});const loaded=await load({project:p});
      if(!loaded||project!==p||identity!==owner||identity!==actorKey()||(row.target_type==='project'?data?.state!=='trashed':data?.state!=='active'))return;
      const target={type:row.target_type,id:row.target_id,title:row.title};
      lifecycle(target,'restore',async()=>{recycleOrigins.delete(scopeKey());await returnToRecycle();},()=>{const key=scopeKey();if(!pending.has(key))recycleOrigins.set(key,{project_id:p,target_id:row.target_id});});
    }finally{if(recycleOpening===opening)recycleOpening=null;}
  }
  const supportedRecycle=category=>['all','project','episode','asset','video'].includes(category);
  async function readRecycle(cursor=null,stack=[]){
    const t=ticket,category=recycleCategory,seq=++recycleSeq;if(!same(t,null))return;
    if(!supportedRecycle(category)){recycleState={status:'unsupported',cursor:null,stack:[]};render();return;}
    if(!session().actor){recycleState={status:'error',error:'请先建立操作会话后查看回收站。',cursor,stack};render();return;}
    recycleState={status:'loading',cursor,stack};render();
    try{const query=new URLSearchParams({kind:category,limit:'24'});if(cursor)query.set('cursor',cursor);const page=await ctx.api('/api/v1/project-management/recycle-items?'+query,{headers:{'X-CSRF-Token':session().csrf||''}});
      if(!same(t,null)||seq!==recycleSeq||category!==recycleCategory)return;
      if(!Array.isArray(page.items))throw new Error('回收列表响应不完整');recycleState={status:'ready',items:page.items,next_cursor:page.next_cursor||null,cursor,stack};render();
    }catch(error){if(same(t,null)&&seq===recycleSeq&&category===recycleCategory){recycleState={status:'error',error:error.message,cursor,stack};render();}}
  }
  function render(force=false){
    if(!data||!force&&root.querySelector('dialog[open]'))return;root.replaceChildren();const head=el('header');head.append(el('h1',project?msg("ui.project_management"):msg("common.route_recycle_bin")),el('p',project?msg("ui.manage_project_names_folders_and_retention_settings"):'查看已回收的项目、剧集、资产和视频，恢复后可继续创作','hint'));root.append(head);
    const choices=el('select');bindAttribute(choices,'aria-label',msg("ui.manage_project"));choices.append(localizedOption('',msg("ui.select_a_project_extra_2")));for(const r of data.projects)choices.append(localizedOption(r.id,r.name+(r.state==='trashed'?' · 已回收':'')));choices.value=project||'';choices.onchange=()=>{const next=choices.value||null;ctx.onScope?.(next,data.projects.find(r=>r.id===next));filters={folder:'',kind:'',q:'',offset:0};load({project:next});};
    if(!project||!data.project){
      const state=recycleState||{status:'loading',stack:[]},supported=supportedRecycle(recycleCategory),bar=el('div',null,'management-recycle-toolbar'),categories=el('nav',null,'management-recycle-categories');categories.setAttribute('role','tablist');categories.setAttribute('aria-label','回收站分类');
      for(const [value,label]of [['all','全部'],['project','项目'],['episode','剧集'],['storyboard-group','分镜镜号'],['video-group','视频镜号'],['storyboard-image','分镜图'],['asset','资产'],['video','视频'],['canvas','画布']]){const b=button(label,()=>{if(recycleCategory!==value){recycleCategory=value;return readRecycle();}});b.setAttribute('role','tab');b.setAttribute('aria-selected',String(recycleCategory===value));if(!supportedRecycle(value))b.title='该分类尚未接入';categories.append(b);}
      const count=el('span',state.status==='ready'?'本页 '+state.items.length+' 项':state.status==='loading'?'正在加载':supported?'':'暂未接入','management-recycle-count');count.setAttribute('role','status');bar.append(categories,count);root.append(bar);
      const grid=el('div',null,'management-recycled');
      if(state.status==='ready')for(const row of state.items){const card=el('article',null,'management-recycled-card'),cover=el('div','▤','management-cover'),info=el('div',null,'management-recycle-info'),actions=el('div',null,'management-recycle-actions');card.dataset.targetId=row.target_id;card.dataset.projectId=row.project_id;info.append(el('h3',row.title||row.target_id),el('p',({project:'项目',episode:'剧集',asset:'资产',video:'视频'})[row.kind]||row.kind,'hint'));if(row.target_type==='object'||row.target_type==='media'){const owner=data.projects.find(item=>item.id===row.project_id);info.append(el('p',owner?'项目：'+owner.name:'项目 '+row.project_id,'hint'));}
        if(row.changed_at){const time=new Date(row.changed_at);info.append(el('p','回收于 '+(Number.isNaN(time.getTime())?row.changed_at:time.toLocaleString()),'hint'));}if(row.reason)info.append(el('p',row.reason,'management-recycle-reason'));
        if(!row.can_restore){const explanation=row.blocked_by_project?'请先恢复所属项目':row.blocked_by_ancestor?'请先恢复上级对象':'当前账号无法恢复此项';info.append(el('p',explanation,'management-recycle-blocked'));}
        actions.append(button('恢复',()=>restoreFromList(row),!row.can_restore||!session().actor),button(msg("ui.project_management"),async()=>{const known=data.projects.find(item=>item.id===row.project_id);ctx.onScope?.(row.project_id,known||{id:row.project_id,name:row.title});await load({project:row.project_id});}));info.append(actions);card.append(cover,info);grid.append(card);}
      if(state.status==='ready'&&!state.items.length||state.status==='unsupported'){const empty=el('div',null,'management-empty'),art=el('div',null,'management-empty-illustration');art.setAttribute('aria-hidden','true');empty.append(art,el('p',state.status==='unsupported'?'该分类暂未接入':'暂无数据'));grid.append(empty);}
      if(state.status==='error'){const failure=el('div',null,'management-recycle-error');failure.setAttribute('role','alert');failure.append(el('p','回收列表读取失败：'+state.error),button(msg('ui.reload'),()=>readRecycle(state.cursor,state.stack)));grid.append(failure);}root.append(grid);
      if(supported&&(state.stack?.length||state.status==='ready'&&state.next_cursor)){const pager=el('nav',null,'management-recycle-pager');pager.append(button(msg('common.previous_page'),()=>{const stack=state.stack.slice(),cursor=stack.pop();return readRecycle(cursor,stack);},!state.stack.length||state.status==='loading'),button(msg('common.next_page'),()=>readRecycle(state.next_cursor,[...state.stack,state.cursor]),state.status!=='ready'||!state.next_cursor));root.append(pager);}
      const other=el('details',null,'management-project-picker');other.append(el('summary','管理其他项目'),choices,button(msg("ui.refresh_management_status"),()=>load({project,keepFilters:true})));root.append(other);return;
    }
    root.append(choices,button(msg("ui.refresh_management_status"),()=>load({project,keepFilters:true})));
    const pendingRequest=pending.get(scopeKey());if(pendingRequest){const recovery=el('aside',null,'management-recovery');recovery.append(el('p',busy?msg("ui.submitting_fixed_action"):msg("ui.previous_receipt_is_unknown_original_inputs_and_request_identity")),button(msg("ui.recover_original_operation_receipt"),recoverPending,busy||inFlight.has(scopeKey())));root.append(recovery);}
    const summary=el('section',null,'management-card');summary.append(el('h2',data.project.name),el('p',data.state==='active'?msg("ui.project_available"):data.state==='trashed'?msg("ui.project_is_in_trash_fixed_history_remains_readable_restore"):msg("ui.project_permanently_deactivated_audit_history_preserved")));
    const target={type:'project',id:project,title:data.project.name};if(data.state==='active')summary.append(button(msg("ui.recycle_this_project"),()=>lifecycle(target,'trash'),busy));else if(data.state==='trashed')summary.append(button(msg("ui.restore_this_project"),()=>lifecycle(target,'restore'),busy),button(msg("ui.permanently_deactivate_this_project"),()=>lifecycle(target,'purge'),busy));root.append(summary);
    const layout=el('div',null,'management-grid'),settings=el('details',null,'management-settings');settings.append(el('summary',msg("ui.project_name_folders_and_retention")),layout);root.append(settings);
    if(data.state==='active'){
      const rename=form('项目名称'),title=field(rename,msg("novel-parser.project_name"),el('input'),'project-name',data.project.name);title.required=true;title.maxLength=200;if(title.value!==data.project.name)rename.append(el('p',msg("ui.the_name_has_unsaved_changes"),'hint'));submit(rename,'保存项目名称',()=>({operation:'rename',title:title.value}));layout.append(rename);
      const create=form('新建文件夹'),folderTitle=field(create,msg("asset.folder_name"),el('input'),'new-folder');folderTitle.required=true;folderTitle.maxLength=200;const parent=field(create,msg("ui.parent_folder"),selector(),'new-parent');submit(create,'创建文件夹',()=>({operation:'folder_create',title:folderTitle.value,parent_id:parent.value||null}));layout.append(create);
    }
    const retention=form('显式留存'),days=field(retention,msg("ui.retention_days_leave_empty_for_no_deadline"),el('input'),'retention',data.retention_days??'');days.type='number';days.min='1';days.max='36500';retention.append(el('p',msg("ui.shows_an_expiry_date_only_nothing_is_deleted_automatically"),'hint'));submit(retention,'保存留存设置',()=>({operation:'retention',days:days.value===''?null:Number(days.value)}));layout.append(retention);
    if(data.state==='active'){
      const folders=el('section',null,'management-card');folders.append(el('h2',msg("ui.project_folders")));
      for(const f of data.folders){const row=el('div',null,'management-folder');row.append(el('strong',folderLabel(f.id)));const title=el('input');bindAttribute(title,'aria-label',msg("ui.directory_name_value0",{value0:f.title}));title.value=drafts.get(scopeKey()+':folder-title:'+f.id)??f.title;title.oninput=()=>drafts.set(scopeKey()+':folder-title:'+f.id,title.value);const parent=selector();bindAttribute(parent,'aria-label',msg("ui.directory_parent_value0",{value0:f.title}));parent.value=f.parent_id||'';const siblings=data.folders.filter(x=>x.parent_id===f.parent_id).sort((a,b)=>a.ordinal-b.ordinal),at=siblings.findIndex(x=>x.id===f.id);
        row.append(title,button(msg("ui.rename"),()=>write({operation:'folder_update',folder_id:f.id,title:title.value}),busy),parent,button(msg("ui.move_folder"),()=>write({operation:'folder_move',folder_id:f.id,parent_id:parent.value||null}),busy),button(msg("agent.overseas_remake_move_up"),()=>{const ids=siblings.map(x=>x.id);[ids[at-1],ids[at]]=[ids[at],ids[at-1]];return write({operation:'folder_order',parent_id:f.parent_id,folder_ids:ids});},busy||at===0),button(msg("ui.delete_empty_folder"),()=>write({operation:'folder_remove',folder_id:f.id}),busy));folders.append(row);}
      root.append(folders);
    }
    const query=form('内容筛选'),folder=field(query,msg("ui.current_folder"),selector());setText(folder.options[0],msg("ui.all_folders"));folder.append(localizedOption('unfiled',msg("ui.unclassified_only")));folder.value=filters.folder;const kind=field(query,msg("ui.content_type"),el('select'));for(const [v,l]of [['','可用对象与媒资'],['object','可用对象'],['media','可用媒资'],['trashed','回收对象']])kind.append(localizedOption(v,l));kind.value=filters.kind;const search=field(query,msg("ui.name_or_identifier"),el('input'));search.value=filters.q;const filter=el('button',msg("asset.filter"));filter.type='submit';query.append(filter);query.onsubmit=e=>{e.preventDefault();filters={folder:folder.value,kind:kind.value,q:search.value,offset:0};load({project,keepFilters:true});};root.append(query);
    const list=el('div',null,'management-items');for(const row of data.items){const card=el('article',null,'management-card');card.append(el('h3',row.title||row.id),el('p',joinMessages([names[row.kind]||row.kind," · ",names[row.state]||row.state," · ",row.folder_id?folderLabel(row.folder_id):msg("ui.uncategorized")]),'hint'));
      if(row.changed_at)card.append(el('p',msg("ui.trashed_at_value0_value1",{value0:row.changed_at,value1:row.due_at?msg("ui.expires_value0_value1",{value0:row.due_at,value1:row.expired?msg("ui.waiting_for_an_explicit_action"):''}):''}),'hint'));
      if(row.state==='active'&&data.state==='active'){const dest=selector();dest.value=row.folder_id||'';bindAttribute(dest,'aria-label',msg("ui.move_value0",{value0:row.title}));card.append(dest,button(msg("ui.move_and_classify"),()=>write({operation:'move',target_type:row.type,target_id:row.id,folder_id:dest.value||null}),busy));
        if(row.type==='object')card.append(button(msg("ui.recycle_object"),()=>lifecycle(row,'trash'),busy),button(msg("ui.open_object"),()=>ctx.navigate('project',row.id,project)));
        else card.append(button(msg("ui.open_media"),()=>ctx.media?.(row.id)),button(msg("ui.media_recycle_entry"),()=>ctx.navigate('trash',null,project)));
      }else if(row.state==='trashed')card.append(button(msg("ui.restore_object"),()=>lifecycle(row,'restore'),busy),button(msg("ui.permanently_deactivate_object"),()=>lifecycle(row,'purge'),busy));else if(row.state==='parent_trashed')card.append(el('p',msg("ui.restore_the_parent_first_original_classification_relationships_are_retained")));
      list.append(card);}
    if(!data.items.length)list.append(el('p',msg("ui.no_content_matches_this_filter")));root.append(list);
    const pager=el('nav');pager.append(button(msg("common.previous_page"),()=>{filters.offset=Math.max(0,filters.offset-100);return load({project,keepFilters:true});},!filters.offset),el('span',msg("ui.value0_items_in_total",{value0:data.total})),button(msg("common.next_page"),()=>{filters.offset=data.next_offset;return load({project,keepFilters:true});},data.next_offset==null));root.append(pager);
  }
  async function load(options={}){
    const p=options.project||null,t=++ticket;recycleSeq++;project=p;identity=actorKey();busy=false;if(!p)recycleOpening=null;if(!options.keepFilters)filters={folder:'',kind:'',q:'',offset:0};root.replaceChildren(el('p',msg("ui.loading_directory_and_recycle_status")));
    try{const headers={'X-CSRF-Token':session().csrf||''};const [active,recycled]=await Promise.all([ctx.api('/api/v1/projects'),session().actor?ctx.api('/api/v1/project-management/recycled',{headers}):Promise.resolve({items:[]})]);if(!same(t,p))return;const projects=[...active.items,...recycled.items];
      const query=new URLSearchParams({offset:String(filters.offset),limit:'100'});if(filters.folder)query.set('folder_id',filters.folder);if(filters.kind)query.set('kind',filters.kind);if(filters.q)query.set('q',filters.q);
      const value=p?await ctx.api(endpoint(p)+'?'+query):{};if(!same(t,p))return;data={...value,projects};if(value.revision!=null)ctx.setRevision?.(value.revision,p);if(p)render(true);else{recycleState={status:'loading',cursor:null,stack:[]};render(true);await readRecycle();}return true;
    }catch(error){if(same(t,p)){root.replaceChildren(el('p',error.message),button(msg("ui.reload"),()=>load({project:p,keepFilters:true})));}}
  }
  return {load,suspend(){ticket++;recycleSeq++;busy=false;recycleOpening=null;}};
}
