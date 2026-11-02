import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Persistent personal reading receipts; original task pages own recovery. */
const el=(tag,text='')=>{const node=document.createElement(tag);setText(node,text);return node;};
const states={succeeded:msg("common.completed"),completed:msg("common.completed"),failed:msg("task.failed"),submission_unknown:msg("ui.receipt_unknown_check_original_task"),needs_input:msg("ui.awaiting_additional_input"),result_ready:msg("ui.result_awaiting_confirmation"),planned:msg("ui.plan_awaiting_confirmation"),applied:msg("script-studio.smart_status_applied"),rejected:msg("ui.rejected"),stopped:msg("script-studio.text_057"),cancelled:msg("common.cancelled"),awaiting_upload:msg("ui.waiting_for_upload_resume"),uploaded:msg("ui.waiting_for_registration"),running:msg("ui.running"),queued:msg("ui.waiting_to_be_claimed"),partial:msg("ui.batch_partly_failed_or_blocked_action_needed")};
const kinds={generation:msg("ui.media_generation"),editing:msg("ui.local_rendering"),spatial:msg("ui.spatial_export"),spatial_plan:msg("ui.spatial_planning"),lyrics:msg("ui.lyric_writing"),import:msg("ui.media_import"),text:msg("ui.text_tools"),text_batch:msg("ui.text_tool_batch"),canvas:msg("ui.canvas_assistant"),intelligent:msg("ui.intelligent_production")};

export function createTaskNotifications(root,ctx){
 let epoch=0,project=null,timer=null,request=0,dialog=null,data=null,items=[],cursor=null,unreadOnly=false,busy=false;
 const session=()=>ctx.session(),alive=(e,p)=>e===epoch&&p===project,base=p=>'/api/v1/projects/'+encodeURIComponent(p)+'/task-notifications';
 root.classList.add('task-notifications');const trigger=el('button',msg("task.task_notification"));trigger.type='button';trigger.setAttribute('aria-haspopup','dialog');root.append(trigger);
 const notice=error=>ctx.notice?.(error.message||String(error));
 function count(value){setText(trigger,value?msg("ui.task_notifications_value0_unread",{value0:value}):msg("task.task_notification"));bindAttribute(trigger,'aria-label',value?msg("ui.task_notifications_value0_unread_dynamic_267",{value0:value}):msg("ui.task_notifications_none_unread"));}
 function close(){if(dialog){dialog.close();dialog.remove();dialog=null;}}
 function pause(){clearTimeout(timer);timer=null;}
 function schedule(){pause();if(project&&session().actor)timer=setTimeout(()=>poll().catch(notice),15000);}
 async function poll(){const e=epoch,p=project;if(!p||busy){schedule();return;}try{const value=await ctx.api(base(p)+'?limit=1');if(alive(e,p))count(value.unread_count);}finally{if(alive(e,p))schedule();}}
 async function fetchPage(next=null){
  const e=epoch,p=project,turn=++request;if(!p||!session().actor)return null;
  const params=new URLSearchParams({limit:'20',unread_only:String(unreadOnly)});if(next)params.set('cursor',next);
  const value=await ctx.api(base(p)+'?'+params);if(!alive(e,p)||turn!==request)return null;
  data=value;cursor=value.next_cursor;items=next?[...items,...value.items]:value.items;count(value.unread_count);return value;
 }
 async function refresh(){if(busy){schedule();return;}try{const value=await fetchPage();if(value&&dialog)paint();}finally{schedule();}}
 async function mark(payload){
  const e=epoch,p=project;if(!p)return;busy=true;
  try{await ctx.api(base(p)+'/read',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload})});if(!alive(e,p))return;await fetchPage();if(dialog)paint();}
  finally{if(alive(e,p)){busy=false;schedule();}}
 }
 function button(text,action){const node=el('button',text);node.type='button';node.onclick=async()=>{node.disabled=true;try{await action();}catch(error){notice(error);}finally{if(node.isConnected)node.disabled=false;}};return node;}
 function paint(){
  if(!dialog)return;dialog.replaceChildren();const head=el('header');head.append(el('h2',msg("task.task_notification")),button(msg("ui.close_task_notifications"),close));dialog.append(head);
  const controls=el('div'),filter=el('select');bindAttribute(filter,'aria-label',msg("ui.notification_scope"));filter.append(localizedOption('all',msg("ui.all_notifications")),localizedOption('unread',msg("ui.unread_only")));filter.value=unreadOnly?'unread':'all';filter.onchange=()=>{unreadOnly=filter.value==='unread';cursor=null;refresh().catch(notice);};controls.append(filter,button(msg("ui.refresh_notifications"),refresh),button(msg("ui.mark_all_as_read_through_this_fetch"),()=>mark({through_sequence:data.through_sequence})));dialog.append(controls,el('p',msg("ui.notifications_are_ordered_by_discovery_time_status_outputs_and")));
  if(!items.length)dialog.append(el('p',unreadOnly?msg("ui.no_unread_task_notifications"):msg("ui.no_task_results_need_attention")));
  for(const item of items){const row=el('article');row.dataset.notificationId=item.id;row.className=item.unread?'unread':'';const title=el('h3',item.title);row.append(title,el('p',joinMessages([kinds[item.kind]||item.kind," · ",item.kind==='text_batch'?(states[item.outcome]||states[item.observed_status]):states[item.observed_status],item.unread?msg("ui.unread"):''])),el('small',msg("ui.detected_at_value0",{value0:new Date(item.created_at).toLocaleString()})));
   if(item.current_status!==item.observed_status)row.append(el('p',msg("ui.original_task_s_current_status_value0",{value0:states[item.current_status]||item.current_status})));
   if(item.progress){const v=item.progress;row.append(el('p',msg("ui.succeeded_value0_value1_failed_value2_blocked_value3_skipped_value4",{value0:v.completed,value1:v.total,value2:v.failed,value3:v.blocked,value4:v.skipped,value5:v.pending+v.running})));}
   if(item.error)row.append(el('p',item.error));
   const link=el('a',msg("ui.locate_and_recover_original_task"));link.href=item.task_href;const source=el('a',msg("ui.open_owning_working_draft"));source.href=item.href;row.append(link,source);if(item.unread)row.append(button(msg("ui.mark_read_value0",{value0:item.title}),()=>mark({ids:[item.id]})));dialog.append(row);
  }
  if(cursor)dialog.append(button(msg("ui.load_earlier_notifications"),async()=>{const e=epoch,p=project;const value=await fetchPage(cursor);if(value&&alive(e,p))paint();}));
 }
 async function open(){if(!project||!session().actor)return;const e=epoch,p=project;pause();if(!dialog){dialog=el('dialog');dialog.className='task-notification-dialog';bindAttribute(dialog,'aria-label',msg("task.task_notification"));document.body.append(dialog);dialog.addEventListener('cancel',()=>{dialog.remove();dialog=null;schedule();});dialog.showModal();dialog.append(el('p',msg("ui.loading_notifications")));}const opened=dialog;try{const value=await fetchPage();if(value&&alive(e,p)&&dialog===opened)paint();}catch(error){if(alive(e,p)&&dialog===opened){dialog.replaceChildren(el('p',msg("ui.notifications_could_not_be_loaded_value0",{value0:error.message})),button(msg("ui.reload_notifications"),open),button(msg("ui.close_task_notifications"),close));notice(error);}}finally{if(alive(e,p))schedule();}}
 trigger.onclick=()=>open().catch(notice);
 return {open,refresh,async load(value){pause();close();epoch++;request++;project=value?.project||null;data=null;items=[];cursor=null;unreadOnly=false;busy=false;trigger.disabled=!project||!session().actor;count(0);if(!trigger.disabled)await refresh();},suspend(){pause();close();epoch++;request++;project=null;items=[];data=null;trigger.disabled=true;count(0);}};
}
