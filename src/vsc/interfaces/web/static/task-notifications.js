import {msg,joinMessages,setText,bindAttribute,option as localizedOption} from './i18n.js';
// Original tasks own execution and results. Notifications own personal reading only.
const el=(tag,text='')=>{const node=document.createElement(tag);setText(node,text);return node;};
const states={succeeded:msg('common.completed'),completed:msg('common.completed'),failed:msg('task.failed'),submission_unknown:msg('ui.receipt_unknown_check_original_task'),needs_input:msg('ui.awaiting_additional_input'),result_ready:msg('ui.result_awaiting_confirmation'),planned:msg('ui.plan_awaiting_confirmation'),applied:msg('script-studio.smart_status_applied'),rejected:msg('ui.rejected'),stopped:msg('script-studio.text_057'),cancelled:msg('common.cancelled'),awaiting_upload:msg('ui.waiting_for_upload_resume'),uploaded:msg('ui.waiting_for_registration'),running:msg('ui.running'),queued:msg('ui.waiting_to_be_claimed'),partial:msg('ui.batch_partly_failed_or_blocked_action_needed')};
const kinds={generation:msg('ui.media_generation'),editing:msg('ui.local_rendering'),spatial:msg('ui.spatial_export'),spatial_plan:msg('ui.spatial_planning'),lyrics:msg('ui.lyric_writing'),import:msg('ui.media_import'),text:msg('ui.text_tools'),text_batch:msg('ui.text_tool_batch'),canvas:msg('ui.canvas_assistant'),intelligent:msg('ui.intelligent_production')};

export function createTaskNotifications(root,ctx){
 let epoch=0,project=null,owner=null,timer=null,request=0,dialog=null,data=null,items=[],cursor=null,unreadCount=0,unreadOnly=false,busy=false,loading=false,pages=1,error=null,pendingUpdates=false;
 const session=()=>ctx.session(),identity=()=>session().identityId||session().actor;
 const snapshot=()=>({epoch,project,identity:identity()}),alive=s=>s.epoch===epoch&&s.project===project&&s.identity===identity();
 const base=p=>'/api/v1/projects/'+encodeURIComponent(p)+'/task-notifications';
 root.classList.add('task-notifications');
 const trigger=el('button',msg('task.task_notification'));trigger.type='button';trigger.setAttribute('aria-haspopup','dialog');root.append(trigger);
 function count(value){
  unreadCount=value;
  setText(trigger,value?msg('ui.task_notifications_value0_unread',{value0:value}):msg('task.task_notification'));
  bindAttribute(trigger,'aria-label',!project?msg('notifications.choose_project'):value?msg('ui.task_notifications_value0_unread_dynamic_267',{value0:value}):msg('ui.task_notifications_none_unread'));
  bindAttribute(trigger,'title',project?msg('notifications.project_title',{name:ctx.projectName?.(project)||project}):msg('notifications.choose_project'));
 }
 function pause(){clearTimeout(timer);timer=null;}
 function schedule(){pause();if(project&&session().actor)timer=setTimeout(poll,15000);}
 function close(){const opened=dialog;dialog=null;request++;loading=false;if(opened){opened.close();opened.remove();}schedule();}
 function reset(){owner=identity();request++;data=null;items=[];cursor=null;pages=1;busy=false;loading=false;error=null;pendingUpdates=false;count(0);}
 function report(value,s){if(!alive(s))return;error=value.message||String(value);if(dialog)paint();}
 async function fetchPage(next=null){
  const s=snapshot(),turn=++request;if(!project||!session().actor)return null;
  const params=new URLSearchParams({limit:'20',unread_only:String(unreadOnly)});if(next)params.set('cursor',next);
  loading=true;
  try{
   const value=await ctx.api(base(s.project)+'?'+params);
   if(!alive(s)||turn!==request)return null;
   data=value;cursor=value.next_cursor;
   items=next?[...new Map([...items,...value.items].map(item=>[item.id,item])).values()]:value.items;
   pages=next?pages+1:1;error=null;pendingUpdates=false;count(value.unread_count);return value;
  }catch(value){if(!alive(s)||turn!==request)return null;throw value;}
  finally{if(alive(s)&&turn===request)loading=false;}
 }
 async function refresh(){
  if(owner!==identity()){suspend();return;}
  if(busy)return;const s=snapshot();
  try{const value=await fetchPage();if(value&&dialog)paint();}
  catch(value){report(value,s);}
  finally{if(alive(s))schedule();}
 }
 async function poll(){
  if(owner!==identity()){suspend();return;}
  const s=snapshot();if(!project||busy||loading){schedule();return;}
  let badgeTurn=null;
  try{
   if(dialog&&pages===1){const before=JSON.stringify({items,data,error});const value=await fetchPage();if(value&&dialog&&before!==JSON.stringify({items,data,error}))paint();}
   else{
    const turn=++request;badgeTurn=turn;
    const value=await ctx.api(base(project)+'?limit=1');if(!alive(s)||turn!==request)return;
    count(value.unread_count);
    const recovered=Boolean(error);error=null;
    if(dialog){pendingUpdates=value.through_sequence>data?.through_sequence||value.unread_count!==data?.unread_count;if(pendingUpdates||recovered)paint();}
   }
  }catch(value){if(badgeTurn===null||badgeTurn===request)report(value,s);}
  finally{if(alive(s))schedule();}
 }
 async function mark(payload){
  if(owner!==identity()){suspend();return;}
  if(!project||busy)return;const s=snapshot();busy=true;request++;loading=false;
  try{
   const value=await ctx.api(base(project)+'/read',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload})});
   if(!alive(s))return;
   // Keep a successful receipt even if the following GET fails. Never repeat the write to recover a refresh.
   items=items.map(item=>(payload.ids?.includes(item.id)||item.sequence<=payload.through_sequence)?{...item,unread:false}:item);
   if(unreadOnly)items=items.filter(item=>item.unread);
   if(data)data={...data,unread_count:Math.max(0,data.unread_count-value.marked_count)};
   count(Math.max(0,unreadCount-value.marked_count));
   try{await fetchPage();}catch(value){if(alive(s))error=String(msg('notifications.read_saved_refresh_failed',{error:value.message||String(value)}));}
  }catch(value){report(value,s);}
  finally{if(alive(s)){busy=false;if(dialog)paint();schedule();}}
 }
 function button(text,action,key,disabled=false){
  const node=el('button',text);node.type='button';node.disabled=disabled;if(key)node.dataset.notificationFocus=key;
  node.addEventListener('click',async()=>{const s=snapshot();node.disabled=true;try{await action();}catch(value){report(value,s);}finally{if(alive(s)&&node.parentElement)node.disabled=false;}});return node;
 }
 function link(text,href){const node=el('a',text);node.href=href;return node;}
 async function choose(value){pause();epoch++;project=value||null;reset();paint();if(project)await refresh();}
 function paint(){
  if(!dialog)return;
  const focus=document.activeElement?.dataset?.notificationFocus,scroll=dialog.scrollTop||0;
  dialog.replaceChildren();const head=el('header');head.append(el('h2',msg('task.task_notification')),button(msg('ui.close_task_notifications'),close,'close'));dialog.append(head);
  const scope=el('label',msg('notifications.project')),select=el('select');bindAttribute(select,'aria-label',msg('notifications.project'));select.dataset.notificationFocus='project';
  select.append(localizedOption('',msg('notifications.choose_project')));
  const choices=ctx.projects?.()||[];for(const p of choices)select.append(localizedOption(p.id,p.name||p.id));
  if(project&&!choices.some(p=>p.id===project))select.append(localizedOption(project,ctx.projectName?.(project)||project));
  select.value=project||'';select.disabled=busy;select.addEventListener('change',()=>choose(select.value));scope.append(select);dialog.append(scope,el('p',msg('notifications.explanation')));
  if(!project){dialog.append(el('p',choices.length?msg('notifications.choose_project'):msg('notifications.no_projects')));return;}
  const controls=el('div'),filter=el('select');bindAttribute(filter,'aria-label',msg('ui.notification_scope'));filter.dataset.notificationFocus='filter';
  filter.append(localizedOption('all',msg('ui.all_notifications')),localizedOption('unread',msg('ui.unread_only')));filter.value=unreadOnly?'unread':'all';filter.disabled=busy;
  filter.addEventListener('change',()=>{unreadOnly=filter.value==='unread';cursor=null;return refresh();});
  controls.append(filter,button(msg('ui.refresh_notifications'),refresh,'refresh',busy),button(msg('ui.mark_all_as_read_through_this_fetch'),()=>mark({through_sequence:data.through_sequence}),'read-all',busy||!data?.unread_count),link(msg('notifications.all_tasks'),'/?'+new URLSearchParams({page:'tasks',project})));
  dialog.append(controls);
  if(error){const status=el('p',msg('notifications.refresh_failed',{error}));status.setAttribute('role','status');dialog.append(status);}
  if(pendingUpdates)dialog.append(button(msg('notifications.new_updates'),refresh,'updates',busy));
  if(!data&&!error)dialog.append(el('p',msg('ui.loading_notifications')));
  else if(!items.length)dialog.append(el('p',unreadOnly?msg('ui.no_unread_task_notifications'):msg('ui.no_task_results_need_attention')));
  for(const item of items){
   const row=el('article');row.dataset.notificationId=item.id;row.className=item.unread?'unread':'';
   const observed=item.kind==='text_batch'?(item.outcome||item.observed_status):item.observed_status;
   row.append(el('h3',item.title),el('p',joinMessages([kinds[item.kind]||item.kind,' · ',states[observed]||observed,item.unread?msg('ui.unread'):''])),el('small',msg('ui.detected_at_value0',{value0:new Date(item.created_at).toLocaleString()})));
   if(item.is_current_event===false||item.current_status!==item.observed_status)row.append(el('p',msg('ui.original_task_s_current_status_value0',{value0:states[item.current_status]||item.current_status})));
   if(item.progress){const v=item.progress;row.append(el('p',msg('ui.succeeded_value0_value1_failed_value2_blocked_value3_skipped_value4',{value0:v.completed,value1:v.total,value2:v.failed,value3:v.blocked,value4:v.skipped,value5:v.pending+v.running})));}
   if(item.error)row.append(el('p',item.error));
   else if(item.is_current_event===false&&item.current_error)row.append(el('p',msg('notifications.current_error',{error:item.current_error})));
   row.append(link(msg('ui.locate_and_recover_original_task'),item.task_href),link(msg('notifications.open_result'),item.href));
   if(item.unread)row.append(button(msg('ui.mark_read_value0',{value0:item.title}),()=>mark({ids:[item.id]}),'read:'+item.id,busy));
   dialog.append(row);
  }
  if(cursor)dialog.append(button(msg('ui.load_earlier_notifications'),async()=>{const s=snapshot();try{const value=await fetchPage(cursor);if(value&&alive(s)&&dialog)paint();}finally{if(alive(s))schedule();}},'more',busy));
  dialog.scrollTop=scroll;
  if(focus){const controls=[...dialog.querySelectorAll('button'),...dialog.querySelectorAll('select')];(controls.find(node=>node.dataset.notificationFocus===focus)||controls.find(node=>node.dataset.notificationFocus==='refresh'))?.focus();}
 }
 async function open(){
  if(owner!==identity()){suspend();return;}
  if(!session().actor)return;
  pause();if(!dialog){dialog=el('dialog');dialog.className='task-notification-dialog';bindAttribute(dialog,'aria-label',msg('task.task_notification'));document.body.append(dialog);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.showModal();}
  paint();if(project)await refresh();
 }
 trigger.addEventListener('click',open);
 function suspend(){close();pause();epoch++;project=null;reset();trigger.disabled=true;}
 return {open,refresh,async load(value){close();pause();epoch++;project=value?.project||null;reset();trigger.disabled=!session().actor;if(!trigger.disabled&&project)await refresh();},suspend};
}
