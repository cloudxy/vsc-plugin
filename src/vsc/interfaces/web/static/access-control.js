import {msg,option as localizedOption,joinMessages,setText,bindAttribute,LOCALES,setLocale,getLocale} from './i18n.js';
import {createCreativeCanvasPanel} from './creative-canvas.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const roles={owner:msg('access.role_owner'),editor:msg('access.role_editor'),reviewer:msg('access.role_reviewer'),viewer:msg('access.role_viewer')};
const secret=()=>{const a=new Uint8Array(32);crypto.getRandomValues(a);return [...a].map(v=>v.toString(16).padStart(2,'0')).join('');};
const future=()=>new Date(Date.now()+7*86400000).toISOString();
export function createAccessControl(root,ctx){
 const sharedCanvas=createCreativeCanvasPanel(ctx);
 let authenticationOptions=null;const authDrafts=new Map();const graphicUrls=new Set();
 let epoch=0,scope={},snapshot=null,accessRevision=0,resourceOffset=0,resourceQuery='',activeArea='workspace',memberScope=null;const drafts=new Map(),pending=new Map(),joinDrafts=new Map(),secretReceipts=new Map(),createdTeams=new Map();
 const session=()=>ctx.session();
 const btn=(label,fn,disabled=false)=>{const b=el('button',label);b.type='button';b.disabled=disabled;b.onclick=async()=>{if(b.disabled)return;const n=epoch,actor=session().actor;b.disabled=true;try{await fn();}catch(e){if(n===epoch&&actor===session().actor)ctx.notice(e.message);}finally{if(n===epoch&&b.isConnected)b.disabled=disabled;}};return b;};
 function field(parent,title,value='',key=null,type='text'){const label=el('label',title),input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;bindAttribute(input,'aria-label',title);key=key?(session().actor||'anonymous')+':'+key:null;input.value=key&&drafts.has(key)?drafts.get(key):value;if(key)input.oninput=()=>drafts.set(key,input.value);label.append(input);parent.append(label);return input;}
 function select(parent,title,rows,value=''){const label=el('label',title),input=el('select');bindAttribute(input,'aria-label',title);for(const row of rows)input.append(localizedOption(row.value,row.label));input.value=rows.some(row=>row.value===value)?value:rows[0]?.value||'';label.append(input);parent.append(label);return input;}
 const post=(path,body)=>ctx.api(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(body)});
 async function command(action,payload,key=action){
  const actor=session().actor,localKey=key;key=(actor||'anonymous')+':'+key;const signature=JSON.stringify({action,payload});let op=pending.get(key);
  if(op&&op.signature!==signature)throw new Error('上一请求回执未确认，请先恢复原请求；当前输入保留。');
  if(!op){op={action,payload,signature,actor,localKey,key:crypto.randomUUID(),revision:accessRevision};pending.set(key,op);}
  try{const value=await post('/api/v1/access/commands/'+action,{payload:op.payload,expected_revision:op.revision,idempotency_key:op.key});pending.delete(key);if(op.payload.secret)secretReceipts.set(op.key,op);if(session().actor===actor)accessRevision=Math.max(accessRevision,value.access_revision);return value;}
  catch(e){if(e.status>=400&&e.status<500)pending.delete(key);throw e;}
 }
 async function refresh(applyLanguage=true){const n=epoch,data=await ctx.api('/api/v1/access');if(n!==epoch)return false;snapshot=data;accessRevision=data.access_revision;if(applyLanguage&&data.identity?.preferences?.language)setLocale(data.identity.preferences.language);return true;}
 function section(title,area=activeArea){const box=el('section');box.dataset.area=area;box.append(el('h2',title));if(area===activeArea)root.append(box);return box;}
 function copyValue(host,title,value){const input=field(host,title,value,null,'textarea');input.readOnly=true;host.append(btn(msg("ui.copy_value0",{value0:title}),async()=>{await navigator.clipboard.writeText(value);ctx.notice(msg("ui.copied_share_it_through_your_chosen_channel"));}));}
 async function applySession(value){await ctx.onSession(value);if(scope.page==='access-share')return;await load(scope);}
 function authenticationForm(host,purpose){
  const n=epoch,key=(session().actor||'anonymous')+':'+purpose;let draft=authDrafts.get(key);if(!draft){let restored=null;try{restored=JSON.parse(sessionStorage.getItem('vsc-authentication:'+key)||'null');}catch{}draft=restored||{channel:'email',recipient:'',graphic:null,answer:'',request:null,otp:null};authDrafts.set(key,draft);}
  const remember=()=>{try{sessionStorage.setItem('vsc-authentication:'+key,JSON.stringify(draft));}catch{}};
  const alive=()=>n===epoch&&host.isConnected,options=authenticationOptions||{channels:[],providers:[]};
  if(purpose==='bind'){host.append(el('p',msg("ui.bind_a_verified_email_phone_number_or_third_party")));const bound=el('div');host.append(bound);ctx.api('/api/v1/authentication/bindings').then(value=>{if(!alive())return;bound.replaceChildren(el('h3',msg("ui.bound_login_methods")));for(const row of value.items)bound.append(el('p',joinMessages([row.label," · ",row.subject_label])));if(!value.items.length)bound.append(el('p',msg("ui.no_verification_code_or_third_party_login_method_is")));}).catch(error=>{if(alive())bound.replaceChildren(el('p',error.message));});}
  const channel=select(host,msg('auth.channel'),options.channels.map(row=>({value:row.id,label:row.label+(row.enabled?'':' · 未启用')})),draft.channel),recipient=field(host,msg('auth.recipient'),draft.recipient),graphicBox=el('div'),answer=field(host,msg('auth.graphic'),draft.answer);answer.autocomplete='off';recipient.autocomplete=draft.channel==='sms'?'tel':'email';
  const message=el('p',draft.otp?.message||'', 'hint');message.setAttribute('role','status');host.append(graphicBox,message);let graphic=null;
  let graphicUrl=null;const drawGraphic=()=>{graphicBox.replaceChildren();if(!draft.graphic)return;if(graphicUrl){URL.revokeObjectURL(graphicUrl);graphicUrls.delete(graphicUrl);}const bytes=Uint8Array.from(atob(draft.graphic.image_base64),c=>c.charCodeAt(0));graphicUrl=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));graphicUrls.add(graphicUrl);graphic=el('img');graphic.src=graphicUrl;bindAttribute(graphic,"alt",msg("ui.enter_the_code_in_the_image_request_another_image"));graphic.width=210;graphic.height=72;graphicBox.append(graphic);};drawGraphic();
  channel.onchange=()=>{draft.channel=channel.value;remember();};recipient.oninput=()=>{draft.recipient=recipient.value;remember();};answer.oninput=()=>{draft.answer=answer.value;remember();};
  const enabled=()=>options.channels.some(row=>row.id===channel.value&&row.enabled);
  host.append(btn(msg('auth.change_graphic'),async()=>{if(!enabled())throw new Error('此登录方式尚未配置或启用。');const value=await post('/api/v1/authentication/graphic',{});if(!alive())return;draft.graphic=value;draft.answer='';answer.value='';remember();drawGraphic();},!options.enabled));
  const code=field(host,msg('auth.code'),'');code.inputMode='numeric';code.autocomplete='one-time-code';code.maxLength=6;
  host.append(btn(msg('auth.send'),async()=>{if(!enabled())throw new Error('此登录方式尚未配置或启用。');if(!draft.request){if(!draft.graphic)throw new Error('请先取得图片验证码。');draft.request={channel:channel.value,recipient:recipient.value,graphic_id:draft.graphic.id,graphic_answer:answer.value,purpose,request_key:crypto.randomUUID()};remember();}let value;try{value=await post('/api/v1/authentication/otp',draft.request);}catch(error){if(error.status>=400&&error.status<500&&error.status!==409){draft.request=null;remember();}throw error;}if(!alive())return;draft.otp=value;remember();setText(message,msg("ui.value0_recipient_value1",{value0:value.message,value1:value.recipient_label}));},!options.enabled),btn(purpose==='bind'?msg('auth.verify_bind'):msg('auth.verify_login'),async()=>{if(!draft.otp)throw new Error('请先恢复或取得原验证码请求。');const value=await post('/api/v1/authentication/otp/'+draft.otp.id+'/verify',{code:code.value});if(!alive())return;authDrafts.delete(key);try{sessionStorage.removeItem('vsc-authentication:'+key);}catch{}await applySession(value);},!options.enabled),btn(msg('auth.restart'),()=>{draft.request=null;draft.otp=null;draft.graphic=null;draft.answer='';answer.value='';code.value='';remember();drawGraphic();setText(message,msg("ui.request_another_image_challenge_then_explicitly_start_a_new"));},!options.enabled));
  if(!options.enabled)host.append(el('p',msg("ui.phone_email_and_third_party_login_are_not_enabled"),'hint'));
  for(const provider of options.providers)host.append(btn((purpose==='bind'?'绑定 ':'使用 ')+provider.label+(purpose==='bind'?'':' 登录'),async()=>{const result=await post('/api/v1/authentication/oidc/'+encodeURIComponent(provider.id)+'/start',{purpose});if(alive())location.assign(result.authorization_url);},!provider.enabled));
 }
 function navigateAccess(value){return ctx.navigateAccess?ctx.navigateAccess(value):load(value);}
 function ownershipLabel(workspace){
  if(!workspace)return '项目所有者';
  if(workspace.kind!=='personal')return '团队 · '+workspace.name;
  const owner=workspace.owner_name||(workspace.created_by===snapshot.identity.id?snapshot.identity.display_name:workspace.name),actor=workspace.owner_actor||(workspace.created_by===snapshot.identity.id?snapshot.identity.actor:'');
  return '个人 · '+owner+(actor&&actor!==owner?'（'+actor+'）':'');
 }
 async function showCreatedTeam(value,n){
  const actor=session().actor;createdTeams.set(actor,value);if(n!==epoch)return;
  if(!await refresh())return;createdTeams.delete(actor);try{await navigateAccess({...scope,area:'workspace',team:value.id,project:null,canvas:null});}catch(error){createdTeams.set(actor,value);throw error;}ctx.notice('团队“'+value.name+'”已创建。项目归属仍在创建项目时明确指定。');
 }
 function invitationForm(host){
  const n=epoch,actor=session().actor,token=field(host,'邀请链接中的凭据',scope.invite||'',null,'password'),preview=el('div',null,'access-impact');
  let serial=0,approved=null;const alive=()=>n===epoch&&actor===session().actor&&host.isConnected;
  const current=snapshot?.identity,choices=current?[{value:'current',label:'使用当前账户：'+current.display_name},{value:'new',label:'创建独立账户'}]:[{value:'new',label:'创建独立账户'}];
  const identity=select(host,'加入时使用的账户',choices,current?'current':'new'),name=field(host,'新账户显示名称','','join-name'),output=el('div');
  const reflectIdentity=()=>{name.parentElement.hidden=identity.value==='current';};identity.onchange=reflectIdentity;reflectIdentity();
  const accept=btn('确认接受此邀请',async()=>{
   if(!approved||approved.secret!==token.value)throw new Error('请先预览当前邀请的目标和角色。');
   const fixed=approved,usingCurrent=identity.value==='current';const joinKey=(actor||'anonymous')+':'+fixed.secret;let draft=joinDrafts.get(joinKey);
   if(draft&&draft.useCurrent!==usingCurrent)throw new Error('原加入请求回执未确认，请使用原账户选择恢复。');
   if(!draft){draft={secret:secret(),useCurrent:usingCurrent,name:usingCurrent?current.display_name:name.value};joinDrafts.set(joinKey,draft);}
   const value=await post('/api/v1/access/join',{invitation_secret:fixed.secret,credential_secret:draft.secret,display_name:draft.name,use_current_identity:draft.useCurrent});
   if(!alive())return;joinDrafts.delete(joinKey);scope={...scope,invite:null};await ctx.onSession(value);if(n!==epoch)return;
   const continueJoined=()=>navigateAccess({page:'access',area:'members',project:value.joined_project_id||null,team:value.joined_project_id?null:value.joined_workspace_id||fixed.workspace_id||fixed.scope_id,canvas:null});
   if(!usingCurrent){root.replaceChildren();const joined=section('已加入 '+(value.target_name||fixed.target_name));copyValue(joined,'请保存自己的登录凭据',draft.secret);joined.append(btn('继续前往'+(value.joined_project_id?'项目':'团队'),continueJoined));}
   else await continueJoined();
  });accept.disabled=true;const submit=accept.onclick;accept.onclick=async()=>{await submit();if(alive())accept.disabled=!approved||approved.secret!==token.value;};
  const inspect=async()=>{
   const id=++serial,invitationSecret=token.value;approved=null;accept.disabled=true;preview.replaceChildren(el('p','正在读取邀请…'));
   try{const value=await post('/api/v1/access/invitation-preview',{invitation_secret:invitationSecret});if(!alive()||id!==serial||token.value!==invitationSecret)return;
    approved={...value,secret:invitationSecret};preview.replaceChildren(el('h3',(value.scope==='project'?'项目 · ':'团队 · ')+value.target_name),el('p',joinMessages(['加入角色：',roles[value.role]||value.role])),el('p','有效期：'+value.expires_at));if(value.accepted)preview.append(el('p','此邀请已使用；只有原加入请求可恢复。'));accept.disabled=false;
   }catch(error){if(alive()&&id===serial)preview.replaceChildren(el('p',error.message));}
  };
  token.oninput=()=>{serial++;approved=null;accept.disabled=true;preview.replaceChildren(el('p','凭据已改变，请重新预览。'));};
  host.append(btn('预览邀请目标与角色',inspect),preview,accept,output);if(scope.invite)void inspect();
 }
 function login(){
  if(scope.invite){const invite=section('接受邀请');invitationForm(invite);}
  if(snapshot)return;
  const n=epoch;const outer=section(msg('auth.login_title'));authenticationForm(outer,'login');const advanced=el('details');advanced.append(el('summary',msg('auth.advanced')));const box=el('div');advanced.append(box);outer.append(advanced);
  const credential=field(box,msg("ui.member_login_credential"),'',null,'password');box.append(btn(msg("ui.sign_in_with_member_credential"),async()=>{const value=await post('/api/v1/access/login',{secret:credential.value});if(n===epoch)await applySession(value);}));
  if(!scope.invite){const invitation=section('接受团队或项目邀请');invitationForm(invitation);}
 }
 function areaProjects(capability){
  return snapshot.projects.filter(row=>(!capability||row.capabilities.includes(capability))&&(!scope.project||row.id===scope.project));
 }
 function permissionImpact(host,plan){
  if(plan.effect)host.append(el('p',plan.effect));
  const labels={gained:'新增访问',lost:'失去访问',changed:'权限改变',retained:'保留访问'};
  for(const row of plan.access_changes||[]){const before=(row.before_roles||[]).map(value=>String(roles[value]||value)).join('/')||'无',after=(row.after_roles||[]).map(value=>String(roles[value]||value)).join('/')||'无';host.append(el('p',`${row.display_name||row.actor} · ${labels[row.change]||row.change} · ${before} → ${after}`));}
  for(const row of plan.retained_direct_grants||[])host.append(el('p',joinMessages(['保留项目直接授权：',row.display_name,' · ',roles[row.role]||row.role])));
  const shares=plan.shares||[];host.append(el('h3','继续有效的画布链接'));if(!shares.length)host.append(el('p','无有效链接'));for(const row of shares)host.append(el('p',`${row.canvas_title||'画布'} · ${row.mode==='edit'?'实时画布协作':'固定版本预览'} · ${row.expires_at}`));
 }
 function renderAccount(n){
  const profile=section(msg("ui.current_identity_and_preferences")),display=field(profile,msg("ui.display_name"),snapshot.identity.display_name,'display-name'),language=select(profile,msg('user.language'),LOCALES.map(row=>({value:row.code,label:row.label})),getLocale());
  profile.append(el('p',msg("ui.audit_identity_value0",{value0:snapshot.identity.actor})),btn(msg("ui.save_profile_preferences"),async()=>{await command('profile',{display_name:display.value,preferences:{...snapshot.identity.preferences,language:language.value}});if(n!==epoch)return;setLocale(language.value);ctx.notice(msg("ui.profile_saved_historical_decisions_retain_their_identity_labels"));}),btn(msg('user.logout'),async()=>{const value=await post('/api/v1/session/logout',{});if(n===epoch)await applySession(value);}));
  const authentication=section(msg('auth.bind_title'));authenticationForm(authentication,'bind');
  const credentials=section(msg("ui.advanced_login_credentials"));let ownSecret=null;const ownOutput=el('div');credentials.append(btn(msg("ui.create_a_login_credential_for_yourself"),async()=>{ownSecret||=secret();await command('credential',{secret:ownSecret},'own-credential');if(n!==epoch)return;copyValue(ownOutput,'登录凭据',ownSecret);ownSecret=null;}),ownOutput);
  for(const row of snapshot.credentials)credentials.append(el('p',row.id+(row.revoked?' · 已撤销':'')),btn(msg("ui.revoke_credential_value0",{value0:row.id}),async()=>{await command('revoke-credential',{credential_id:row.id},row.id);if(n===epoch&&await refresh())render();},row.revoked));
 }
 function teamPath(team){
  const names=[team.name],seen=new Set([team.id]);let parent=team.parent_id;
  while(parent&&!seen.has(parent)){seen.add(parent);const row=snapshot.workspaces.find(row=>row.id===parent);if(!row)break;names.unshift(row.name);parent=row.parent_id;}
  return names.join(' / ');
 }
 function openDialog(title,build){
  const opener=document.activeElement,dialog=el('dialog',null,'access-dialog'),head=el('header',null,'access-dialog-head');bindAttribute(dialog,'aria-label',title);
  const finish=()=>{dialog.remove();if(opener?.isConnected)opener.focus();};
  const close=()=>dialog.close?dialog.close():finish();
  head.append(el('h2',title),btn('关闭',close));const body=el('div',null,'access-dialog-body');build(body,close);dialog.append(head,body);dialog.addEventListener('close',finish,{once:true});root.append(dialog);if(dialog.showModal)dialog.showModal();else dialog.open=true;
 }
 function createTeam(n){
  openDialog('新建团队',body=>{
   body.append(el('p','团队用于集中管理成员和团队项目。创建后不会改变现有项目归属。','access-description'));
   const name=field(body,'新团队名称','','workspace-name');name.maxLength=200;name.required=true;
   const parentKey=(session().actor||'anonymous')+':workspace-parent';
   const parent=select(body,'上级团队',[{value:'',label:'独立团队'},...snapshot.workspaces.filter(row=>row.kind!=='personal'&&row.manageable).map(row=>({value:row.id,label:teamPath(row)}))],drafts.get(parentKey)||'');parent.onchange=()=>drafts.set(parentKey,parent.value);
   body.append(el('p','选填。上级团队的所有者可管理下级团队；其他成员需要单独加入。','access-description'));
   const error=el('p',null,'access-error');error.setAttribute('role','alert');body.append(error);
   body.append(btn('创建团队',async()=>{
    if(!name.value.trim()){setText(error,'请填写团队名称。');name.focus();return;}
    const actor=session().actor,payload={name:name.value.trim(),parent_id:parent.value||null};let created=createdTeams.get(actor);
    if(!created){const value=await command('workspace',payload);created={id:value.workspace_id,name:payload.name};createdTeams.set(actor,created);}
    if(n!==epoch)return;drafts.delete((actor||'anonymous')+':workspace-name');drafts.delete(parentKey);await showCreatedTeam(created,n);
   }));
  });
 }
 function renderProjects(team=null){
  const content=section(team?'团队项目':'项目协作'),rows=snapshot.projects.filter(row=>(!scope.project||row.id===scope.project)&&(!team||row.workspace_id===team.id));
  content.classList.add('access-projects');
  if(!team)content.querySelector('h2')?.remove();
  if(!team){const ownership=el('details',null,'access-explanation');ownership.append(el('summary','个人项目和团队项目有什么区别？'));for(const owner of snapshot.workspaces.filter(row=>row.kind==='personal')){ownership.append(el('p',ownershipLabel(owner)+'：个人项目归属于该用户身份。账户注销后，项目归属及历史记录继续保留。'));if(owner.manageable&&snapshot.members.some(member=>member.workspace_id===owner.id&&member.identity_id!==owner.created_by))ownership.append(btn('管理个人归属的历史成员',()=>navigateAccess({page:'access',area:'members',team:owner.id,project:null,canvas:null})));}ownership.append(el('p','团队项目归属团队，成员按团队或项目授权访问；浏览团队不会改变新项目的默认归属。'));content.append(ownership);}
  content.append(el('p',team?'这里只显示你可以访问的直属项目，下级团队的项目请进入对应团队查看。':'个人项目与团队项目都在这里按各自归属显示。成员、分享和审核分别作用于所选项目。','access-description'));
  const search=field(content,'搜索项目','','project-query:'+(team?.id||'all'),'search'),list=el('div',null,'access-project-list');content.append(list);
  const draw=()=>{
   list.replaceChildren();const matches=rows.filter(row=>row.name.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
   for(const row of matches){
    const card=el('article',null,'access-project-row'),copy=el('div'),owner=snapshot.workspaces.find(owner=>owner.id===row.workspace_id);
    copy.append(el('h3',row.name),el('p',owner?ownershipLabel(owner):'项目归属：'+(row.workspace_name||'当前账户不可见'),'access-description'));
    const actions=el('div',null,'access-row-actions');actions.append(btn(msg('ui.open_project'),()=>ctx.navigate('project',null,row.id)));
    const more=el('details',null,'access-more');more.append(el('summary','项目操作'));const menu=el('div',null,'access-more-menu');
    menu.append(btn(msg('shell.project_assets'),()=>ctx.navigate('assets',null,row.id)));
    if(row.capabilities.includes('manage'))menu.append(btn('项目协作者',()=>navigateAccess({page:'access',area:'members',project:row.id,team:null,canvas:null})),btn('审核设置',()=>navigateAccess({page:'access',area:'review',project:row.id,team:null,canvas:null})),btn('转移项目归属',()=>navigateAccess({page:'access',area:'transfer',project:row.id,team:null,canvas:null})));
    if(row.capabilities.includes('publish'))menu.append(btn('画布分享',()=>navigateAccess({page:'access',area:'share',project:row.id,team:null,canvas:null})));
    more.append(menu);actions.append(more);card.append(copy,actions);list.append(card);
   }
   if(!matches.length)list.append(el('p',search.value?'没有匹配的项目，请调整搜索内容。':team?'此团队暂无你可以访问的直属项目。':'当前没有可协作的项目。','access-empty'));
  };search.oninput=()=>{drafts.set((session().actor||'anonymous')+':project-query:'+(team?.id||'all'),search.value);draw();};draw();
 }
 function renderWorkspace(n){
  const teams=snapshot.workspaces.filter(row=>row.kind!=='personal').sort((a,b)=>teamPath(a).localeCompare(teamPath(b),'zh-CN')),selected=teams.find(row=>row.id===scope.team);
  if(selected){
   const detail=section('团队概况');detail.classList.add('access-team-context');
   detail.append(el('p',`我的角色：${selected.roles.map(value=>String(roles[value]||value)).join('/')}；可访问的直属项目：${selected.project_count} 个。`));
   if(selected.parent_id)detail.append(el('p','上级团队：'+(selected.parent_name||snapshot.workspaces.find(row=>row.id===selected.parent_id)?.name||'当前账户不可见'),'access-description'));
   const children=teams.filter(row=>row.parent_id===selected.id);if(children.length){const list=el('div',null,'access-row-actions');list.append(el('span','下级团队'));for(const child of children)list.append(btn(child.name,()=>navigateAccess({page:'access',area:'workspace',team:child.id,project:null,canvas:null})));detail.append(list);}
   renderProjects(selected);return;
  }
  const content=section('我的团队');content.classList.add('access-team-list');
  if(!teams.length){const empty=el('div',null,'access-empty');empty.append(el('h3','你还没有创建或加入团队'),el('p','需要多人一起管理项目时，可以新建团队或接受邀请。个人项目请进入“项目协作”。'));content.append(empty);}
  const list=el('div',null,'access-team-grid');
  for(const team of teams){const card=el('article',null,'access-team-card');card.append(el('h3',team.name),el('p',team.parent_id?'上级团队：'+(team.parent_name||snapshot.workspaces.find(row=>row.id===team.parent_id)?.name||'当前账户不可见'):'独立团队','access-description'),el('p',`我的角色：${team.roles.map(value=>String(roles[value]||value)).join('/')} · 可访问的直属项目 ${team.project_count} 个`),btn('进入团队',()=>navigateAccess({page:'access',area:'workspace',team:team.id,project:null,canvas:null})));list.append(card);}content.append(list);
  const actions=el('div',null,'access-row-actions');actions.append(btn('接受邀请',()=>navigateAccess({page:'access',area:'join',project:null,team:null,canvas:null})));content.append(actions);
  const created=createdTeams.get(session().actor);if(created)content.append(el('p','团队“'+created.name+'”已创建，详情尚未读回。'),btn('读取已创建团队',()=>showCreatedTeam(created,n)));
 }
 function renderResources(n){
  const team=snapshot.workspaces.find(row=>row.id===scope.team),content=section('团队素材');
  if(!team||team.kind==='personal'){content.append(el('p','请先进入一个团队，再查看团队素材。'));return;}
  content.append(el('p','汇总你在此团队直属项目中有权限查看的素材；素材仍保存在原项目。','access-description'));
  const toolbar=el('form',null,'access-search'),search=field(toolbar,'搜索此团队媒体',resourceQuery,null,'search'),list=el('div',null,'access-resource-grid');
  const query=()=>{resourceQuery=search.value;resourceOffset=0;render();};toolbar.append(btn(msg('ui.search_media'),query));toolbar.onsubmit=event=>{event.preventDefault();query();};content.append(toolbar,list);
  const read=async()=>{
   list.replaceChildren(el('p','正在读取团队素材…','access-loading'));
   try{const value=await ctx.api('/api/v1/access/workspaces/'+team.id+'/resources?'+new URLSearchParams({offset:String(resourceOffset),limit:'24',query:resourceQuery}));if(n!==epoch)return;
    list.replaceChildren(el('p',`共 ${value.total} 项素材`));
    for(const row of value.items){const card=el('article');card.append(el('h3',row.name),el('p',row.project_name));const media=el(row.modality==='image'?'img':row.modality==='audio'?'audio':'video');media.src='/api/v1/projects/'+row.project_id+'/media/'+row.id+'/content';if(row.modality==='image'){bindAttribute(media,'alt',row.name);media.loading='lazy';}else{media.controls=true;media.preload='metadata';}card.append(media,btn(msg('ui.view_in_project'),()=>ctx.navigate('assets',null,row.project_id)));list.append(card);}
    if(!value.items.length)list.append(el('p',resourceQuery?'没有匹配的素材，请调整搜索内容。':'此团队暂无你可以查看的项目素材。','access-empty'));
    const pages=el('nav',null,'access-pagination');bindAttribute(pages,'aria-label','团队素材分页');pages.append(el('span',`第 ${Math.floor(resourceOffset/24)+1} 页`),btn(msg('common.previous_page'),()=>{resourceOffset=Math.max(0,resourceOffset-24);render();},resourceOffset===0),btn(msg('common.next_page'),()=>{resourceOffset=value.next_offset;render();},value.next_offset==null));content.append(pages);
   }catch(error){if(n===epoch)list.replaceChildren(el('p',error.message,'access-error'),btn('重新读取团队素材',read));}
  };void read();
 }
 function renderTransfer(n){
  const migration=section('项目归属转移'),sourceRows=areaProjects('manage'),project=select(migration,msg("ui.move_project"),sourceRows.map(row=>({value:row.id,label:row.name})),scope.project||sourceRows[0]?.id),destinations=snapshot.workspaces.filter(row=>row.manageable),destination=select(migration,'目标归属',destinations.map(row=>({value:row.id,label:ownershipLabel(row)})),destinations.find(row=>row.kind==='personal')?.id),difference=el('div',null,'access-impact');let previewSerial=0;
  const clear=()=>{previewSerial++;difference.replaceChildren();};project.onchange=clear;destination.onchange=clear;
  migration.append(btn(msg("ui.preview_ownership_change"),async()=>{const serial=++previewSerial,request={project_id:project.value,workspace_id:destination.value};if(!request.project_id||!request.workspace_id)throw new Error('请选择项目与目标归属。');const value=await post('/api/v1/projects/'+request.project_id+'/access-migration-preview',{workspace_id:request.workspace_id});if(n!==epoch||serial!==previewSerial||project.value!==request.project_id||destination.value!==request.workspace_id)return;difference.replaceChildren(el('p',ownershipLabel(snapshot.workspaces.find(row=>row.id===value.plan.from_workspace_id))+' → '+ownershipLabel(snapshot.workspaces.find(row=>row.id===value.plan.to_workspace_id))));permissionImpact(difference,value.plan);difference.append(btn(msg("ui.confirm_move_using_this_preview"),async()=>{if(serial!==previewSerial||project.value!==request.project_id||destination.value!==request.workspace_id)throw new Error('选择已改变，请重新预览。');await command('assign-project',{...request,preview_sha256:value.sha256});if(n===epoch&&await refresh())render();}));}),difference);
 }
 function renderMembers(n){
  const projects=areaProjects('manage'),teams=snapshot.workspaces.filter(row=>row.manageable&&(row.kind!=='personal'||snapshot.members.some(member=>member.workspace_id===row.id))).sort((a,b)=>Number(a.kind==='personal')-Number(b.kind==='personal')),rows=scope.project?projects.map(row=>({value:'project:'+row.id,label:'项目 · '+row.name})):teams.map(row=>({value:'workspace:'+row.id,label:row.kind==='personal'?'个人归属的历史成员 · '+ownershipLabel(row):'团队 · '+row.name}));
  const grants=section(scope.project?'项目协作者':'团队成员与邀请');
  if(scope.team&&!teams.some(row=>row.id===scope.team)){grants.append(el('p','你没有此团队的成员管理权限。请联系团队所有者；这里不会切换到其他团队。','access-empty'));return;}
  if(!rows.length){grants.append(el('p',scope.project?'你没有此项目的成员管理权限。':'请先创建或加入可管理的团队，再邀请团队成员。','access-empty'));return;}
  if(!rows.some(row=>row.value===memberScope))memberScope=scope.project?'project:'+scope.project:rows.some(row=>row.value==='workspace:'+scope.team)?'workspace:'+scope.team:rows[0].value;
  const target=scope.team||scope.project?null:select(grants,'成员所属范围',rows,memberScope);if(target)target.onchange=()=>{const [kind,id]=target.value.split(':');return navigateAccess({...scope,area:'members',project:kind==='project'?id:null,team:kind==='workspace'?id:null,canvas:null});};const [kind,id]=memberScope.split(':'),personal=kind==='workspace'&&snapshot.workspaces.find(row=>row.id===id)?.kind==='personal';
  grants.append(el('p',kind==='workspace'?'这里管理团队的直接成员。项目协作者单独授权；移除团队成员不一定撤销其项目权限。':'这里管理此项目的直接协作者。来自团队的权限和独立画布分享链接分别管理。','access-description'));
  if(personal)grants.append(el('p','个人归属不新增团队成员。请在具体项目中邀请协作者；已有成员记录保留。'));
  else{const form=el('details',null,'access-invite-form');form.append(el('summary','邀请新成员'));const invite=el('div');form.append(invite);grants.append(form);const role=select(invite,msg("ui.granted_role"),Object.entries(roles).filter(([key])=>key!=='owner').map(([value,label])=>({value,label}))),expiry=field(invite,msg("ui.invitation_expiry_with_timezone"),future(),memberScope+':invite-expiry');let inviteSecret=null;const link=el('div');invite.append(btn(msg("ui.create_one_invitation"),async()=>{inviteSecret||=secret();await command('invitation',{scope:kind,scope_id:id,role:role.value,secret:inviteSecret,expires_at:expiry.value},'invitation:'+memberScope);if(n!==epoch)return;copyValue(link,'邀请链接',location.origin+'/?page=access#invite='+inviteSecret);inviteSecret=null;try{if(await refresh(false))drawInvitations();}catch(error){if(n===epoch)ctx.notice('邀请已创建，邀请记录暂未刷新；链接已保留，可刷新后查看。');}}),link);}
  const matches=row=>kind==='workspace'?row.workspace_id===id:row.project_id===id;
  const help=el('details',null,'access-explanation');help.append(el('summary','成员角色有什么区别？'),el('p','所有者：管理成员、项目、审核和分享。编辑者：编辑与生成。审核者：查看并提交审核意见。查看者：只读。团队权限与项目直接授权会共同生效。'));grants.append(help);
  grants.append(el('h3','邀请记录'));const invitationList=el('div');grants.append(invitationList);
  function drawInvitations(){invitationList.replaceChildren();if(!snapshot.invitations.some(matches))invitationList.append(el('p','暂无邀请记录。','access-description'));
  for(const row of snapshot.invitations.filter(matches)){const record=el('div',null,'access-invitation-row'),expiry=row.expires_at?new Date(row.expires_at):null;const state=row.accepted_by?'已加入':row.revoked?'已撤销':expiry&&expiry.getTime()<=Date.now()?'已过期':'等待加入';record.append(el('p',joinMessages([row.scope_name,' · ',roles[row.role]||row.role||'角色未提供',' · ',state,' · 到期：',expiry?expiry.toLocaleString():'未提供'])),btn(msg('ui.revoke_invitation'),async()=>{await command('revoke-invitation',{invitation_id:row.id},row.id);if(n===epoch&&await refresh())render();},row.revoked||Boolean(row.accepted_by)));invitationList.append(record);}
  }drawInvitations();
  grants.append(el('h3','成员列表'));if(!snapshot.members.some(matches))grants.append(el('p','当前范围没有直接成员记录，继承权限仍按团队关系生效。','access-description'));
  for(const member of snapshot.members.filter(matches)){
   const card=el('article',null,'access-member-card');card.append(el('h3',member.display_name),el('p',joinMessages([member.scope_name,' · ',member.active?msg("ui.active"):msg("ui.removed")])));const choice=select(card,msg("ui.member_role_value0",{value0:member.display_name}),Object.entries(roles).map(([value,label])=>({value,label})),member.role),impact=el('div',null,'access-impact');choice.disabled=personal&&!member.active;
   const key='member:'+memberScope+':'+member.identity_id,payload={scope:kind,scope_id:id,identity_id:member.identity_id,role:member.role,active:!member.active};
   if(!personal||member.active)card.append(btn(msg("ui.save_this_member_s_role"),async()=>{await command('member',{...payload,role:choice.value,active:true},key);if(n===epoch&&await refresh())render();}));
   card.append(btn(member.active?'移除此成员前预览':msg("ui.restore_this_member"),async()=>{
    if(!member.active){await command('member',payload,key);if(n===epoch&&await refresh())render();return;}
    if(kind==='workspace'){
     const value=await post('/api/v1/access/workspaces/'+id+'/member-removal-preview',{identity_id:member.identity_id});if(n!==epoch)return;impact.replaceChildren(el('h3','移除 '+value.plan.display_name),el('p',value.plan.effect));const retained=value.plan.retained_project_grants||[];
     if(!retained.length)impact.append(el('p','没有保留的项目直接授权。'));for(const row of retained)impact.append(el('p',joinMessages([row.project_name,' · 保留 ',roles[row.role]||row.role,row.can_revoke?'':' · 当前账户不能撤销'])));
     const revoke=field(impact,'同时撤销以上可撤销的项目直接授权','',null,'checkbox');revoke.checked=false;revoke.disabled=!retained.some(row=>row.can_revoke);
     impact.append(el('p','已有内容、历史决定与分享链接保持原记录。'),btn(personal?'确认移除此历史成员':'确认移除此团队成员',async()=>{await command('member',{...payload,preview_sha256:value.sha256,revoke_project_access:revoke.checked},key);if(n===epoch&&await refresh())render();}));
    }else impact.replaceChildren(el('p','撤销 '+member.display_name+' 对此项目的直接授权。团队角色或独立画布链接仍按原权限生效。'),btn('确认移除此项目协作者',async()=>{await command('member',payload,key);if(n===epoch&&await refresh())render();}));
   },!member.active&&personal&&member.identity_id!==snapshot.workspaces.find(row=>row.id===id)?.created_by),impact);grants.append(card);
  }
 }
 function renderShare(n){
  const modeKey=(session().actor||'anonymous')+':share-mode:'+(scope.project||'all-projects');
  const share=section('画布分享'),projects=areaProjects('publish'),project=select(share,msg("ui.project_to_share"),projects.map(row=>({value:row.id,label:row.name})),scope.project||projects[0]?.id),canvas=select(share,'要分享的画布',[]),mode=select(share,'分享方式',[{value:'view',label:'固定版本预览'},{value:'edit',label:'实时画布协作'}],drafts.get(modeKey)||'view'),explanation=el('p',null,'access-share-explanation'),expiry=field(share,msg("ui.share_expiry_with_timezone"),future(),(scope.project||'all-projects')+':share-expiry'),output=el('div'),list=el('div');let serial=0,choices=[],shareSecret=null;
  const explain=()=>setText(explanation,mode.value==='edit'?'链接可查看和编辑所选画布，包含此画布后续新增的文字与媒体；不包含其他画布，不授予生成或审核权限。编辑链接独立管理，关闭项目成员协作不会撤销此链接。':'链接只展示创建分享时所选的已保存版本，不包含此画布后续修改或新增内容。');mode.onchange=()=>{drafts.set(modeKey,mode.value);explain();};explain();
  const showList=()=>{const selected=choices.find(choice=>choice.value===canvas.value),allowedCanvas=scope.canvas||selected?.canvas_id;list.replaceChildren(el('h3',allowedCanvas?'此画布的分享链接':'此项目的分享链接'));for(const row of snapshot.shares.filter(row=>row.project_id===project.value&&(!allowedCanvas||row.canvas_id===allowedCanvas||choices.find(choice=>choice.canvas_id===allowedCanvas)?.value===row.canvas_version_id))){const title=row.canvas_title||choices.find(choice=>choice.canvas_id===row.canvas_id||choice.value===row.canvas_version_id)?.label||'画布';list.append(el('p',`${title} · ${row.mode==='edit'?'实时画布协作':'固定版本预览'} · ${row.revoked?'已撤销':row.expires_at}`),btn('撤销此画布链接',async()=>{await command('revoke-share',{share_id:row.id},row.id);if(n===epoch&&await refresh())render();},row.revoked));}};
  const loadCanvases=async()=>{const id=++serial,projectId=project.value;choices=[];canvas.replaceChildren();showList();if(!projectId)return;try{const value=await ctx.api('/api/v1/projects/'+projectId+'/creative-canvases');if(n!==epoch||id!==serial||project.value!==projectId)return;const rows=scope.canvas?value.items.filter(row=>row.id===scope.canvas):value.items;for(const row of rows){const detail=await ctx.api('/api/v1/projects/'+projectId+'/creative-canvases/'+row.id);if(n!==epoch||id!==serial||project.value!==projectId)return;choices.push({value:detail.version?.id||detail.version_id||row.current_version_id,canvas_id:row.id,label:(detail.title||detail.version?.title||row.title||'画布')+' · 已保存版本 '+(detail.version?.version||detail.canvas_revision||'')});}canvas.replaceChildren(...choices.map(row=>localizedOption(row.value,row.label)));if(choices.length)canvas.value=choices[0].value;showList();}catch(error){if(n===epoch&&id===serial)output.replaceChildren(el('p',error.message),btn('重新读取画布',loadCanvases));}};
  project.onchange=()=>{output.replaceChildren();shareSecret=null;void loadCanvases();};canvas.onchange=()=>{shareSecret=null;output.replaceChildren();showList();};
  share.append(explanation,btn('重新读取画布',loadCanvases),btn(msg("ui.create_share_link"),async()=>{if(!canvas.value||!choices.some(row=>row.value===canvas.value))throw new Error('请先读取并选择已保存的画布。');const fixed={project_id:project.value,canvas_version_id:canvas.value,mode:mode.value,expires_at:expiry.value};const requestSerial=serial;shareSecret||=secret();const requestSecret=shareSecret;await command('share',{...fixed,secret:requestSecret},'share:'+fixed.project_id+':'+fixed.canvas_version_id);if(shareSecret===requestSecret)shareSecret=null;if(n!==epoch||requestSerial!==serial||project.value!==fixed.project_id||canvas.value!==fixed.canvas_version_id||mode.value!==fixed.mode){if(n===epoch)ctx.notice('原画布分享已创建，可通过“恢复未确认请求”读取原链接。');return;}copyValue(output,'分享链接',location.origin+'/?page=access-share#share='+requestSecret);if(await refresh())showList();}),output,el('p',msg("ui.links_work_only_while_this_deployment_address_is_reachable")),list);if(!projects.length)share.append(el('p','当前范围没有可分享的项目。'));void loadCanvases();
 }
 function renderReview(n){
  const review=section('项目审核设置'),projects=areaProjects('manage'),project=select(review,msg("ui.review_project"),projects.map(row=>({value:row.id,label:row.name})),scope.project||projects[0]?.id),checks=[];
  for(const [key,title]of [['character',msg("ui.character_design_reference")],['storyboard',msg("common.storyboard_image")],['video',msg("common.route_video")]]){const label=el('label',title),input=el('input');input.type='checkbox';input.value=key;label.append(input);review.append(label);checks.push(input);}
  const reflect=()=>{const lanes=snapshot.projects.find(row=>row.id===project.value)?.review_lanes||[];for(const input of checks)input.checked=lanes.includes(input.value);};project.onchange=reflect;reflect();
  review.append(btn(msg("ui.save_selected_review_workflows"),async()=>{if(!project.value)throw new Error('请选择项目。');await command('review-policy',{project_id:project.value,lanes:checks.filter(input=>input.checked).map(input=>input.value)});if(n===epoch)ctx.notice(msg("ui.workflows_updated_existing_approvals_remain_unchanged_no_reviews_are"));}),btn(msg("ui.open_project_review"),()=>ctx.navigate('team-review',null,project.value)));
 }
 function render(){
  for(const url of graphicUrls)URL.revokeObjectURL(url);graphicUrls.clear();const n=++epoch;
  const titles={account:'账户设置',workspace:'团队管理',members:scope.project?'项目协作者':'团队成员',share:'画布分享',review:'项目审核设置',projects:'项目协作',resources:'团队素材',transfer:'项目归属转移',join:'接受邀请'};
  root.replaceChildren();root.className='access-control';root.dataset.area=activeArea;
  const selected=snapshot?.workspaces.find(row=>row.id===scope.team),target=snapshot?.projects.find(row=>row.id===scope.project);
  const header=el('header',null,'access-page-head'),heading=el('div');
  heading.append(el('h1',scope.invite?'接受邀请':selected&&!scope.project&&['workspace','members','resources','projects'].includes(activeArea)?'团队 · '+selected.name:titles[activeArea]));
  heading.append(el('p',selected&&!scope.project?teamPath(selected):target?'项目：'+target.name+' · '+(snapshot.workspaces.find(row=>row.id===target.workspace_id)?ownershipLabel(snapshot.workspaces.find(row=>row.id===target.workspace_id)):target.workspace_name||'归属当前不可见'):activeArea==='workspace'?'先选择一个团队，再管理成员、项目和素材。个人项目请进入“项目协作”。':'操作只影响当前选定的对象。','access-description'));header.append(heading);root.append(header);
  if(!snapshot||scope.invite){login();if(!snapshot||scope.invite)return;}
  const nav=el('nav',null,'access-primary-nav');bindAttribute(nav,'aria-label',msg('ui.account_and_team_sections'));
  for(const [key,label]of [['workspace','团队管理'],['projects','项目协作'],['account','账户设置']]){const tab=btn(label,()=>navigateAccess({page:'access',area:key,project:null,team:null,canvas:null}));tab.setAttribute('aria-pressed',String(key==='workspace'?Boolean(scope.team)||activeArea==='workspace':key==='projects'?!scope.team&&(Boolean(scope.project)||activeArea==='projects'):activeArea==='account'));nav.append(tab);}root.append(nav);
  if(scope.team&&!selected){root.append(el('p','当前账户无法访问此团队，或团队已不存在。请返回团队列表重新选择。','access-empty'));return;}
  if(scope.project&&!target){root.append(el('p','当前账户无法访问此项目，或项目已不存在。请返回项目协作重新选择。','access-empty'));return;}
  if(scope.project&&['members','review','transfer','share'].includes(activeArea)&&!target.capabilities.includes(activeArea==='share'?'publish':'manage')){root.append(el('p','你没有此项目的'+(activeArea==='share'?'分享':'管理')+'权限，请联系项目所有者。','access-empty'));return;}
  if(selected&&!scope.project&&selected.kind!=='personal'){
   const nav=el('nav',null,'access-tabs');bindAttribute(nav,'aria-label','当前团队功能');
   for(const [key,label]of [['workspace','团队项目'],['members','团队成员'],['resources','团队素材']]){const tab=btn(label,()=>navigateAccess({page:'access',area:key,team:selected.id,project:null,canvas:null}));tab.setAttribute('aria-pressed',String(activeArea===key||key==='workspace'&&activeArea==='projects'));nav.append(tab);}root.append(nav);
  }
  if(target){const context=el('nav',null,'access-tabs');bindAttribute(context,'aria-label','当前项目协作功能');for(const [key,label,cap]of [['members','项目协作者','manage'],['share','画布分享','publish'],['review','审核设置','manage'],['transfer','项目归属转移','manage']]){if(!target.capabilities.includes(cap))continue;const tab=btn(label,()=>navigateAccess({page:'access',area:key,project:target.id,team:null,canvas:null}));tab.setAttribute('aria-pressed',String(activeArea===key));context.append(tab);}root.append(context);}
  if(activeArea==='workspace'&&!scope.team){const actions=el('div',null,'access-page-actions');actions.append(btn('新建团队',()=>createTeam(n)));header.append(actions);}
  const utilities=el('div',null,'access-utilities');utilities.append(btn(msg("ui.refresh_permissions_and_members"),async()=>{if(await refresh())render();}),btn(msg("ui.recover_unconfirmed_request"),async()=>{
   const actor=session().actor;for(const op of [...pending.values()].filter(row=>row.actor===actor)){
    if(n!==epoch||session().actor!==actor)return;const value=await command(op.action,op.payload,op.localKey);if(n!==epoch||session().actor!==actor)return;
    if(op.action==='workspace'&&value.workspace_id){await showCreatedTeam({id:value.workspace_id,name:op.payload.name},n);return;}
   }
   if(n!==epoch||!await refresh())return;render();ctx.notice(msg("ui.original_request_receipt_recovered_later_unsaved_inputs_remain"));
   for(const op of [...secretReceipts.values()].filter(row=>row.actor===actor)){const output=section(msg("ui.original_request_recovered"));copyValue(output,op.action==='credential'?'登录凭据':'链接',op.action==='credential'?op.payload.secret:location.origin+'/?page='+(op.action==='share'?'access-share#share=':'access#invite=')+op.payload.secret);}
  }));const tools=el('details',null,'access-tools');tools.append(el('summary','刷新与请求恢复'),utilities);root.append(tools);
  ({account:renderAccount,workspace:renderWorkspace,members:renderMembers,share:renderShare,review:renderReview,projects:()=>renderProjects(selected?.kind!=='personal'?selected:null),resources:renderResources,transfer:renderTransfer,join:()=>invitationForm(section('接受团队或项目邀请'))}[activeArea]||renderWorkspace)(n);
 }
 async function saveLanguage(code){
  const actor=session().actor;if(!actor)return;if(!snapshot||snapshot.identity.actor!==actor){if(!await refresh(false))return;}if(session().actor!==actor)return;
  const identity=snapshot.identity;await command('profile',{display_name:identity.display_name,preferences:{...identity.preferences,language:code}},'profile-language');if(session().actor===actor&&snapshot?.identity?.actor===actor)snapshot.identity.preferences={...snapshot.identity.preferences,language:code};
 }
 async function renderSharedView(n){
  const data=await ctx.api('/api/v1/access/share-view');if(n!==epoch)return;
  await sharedCanvas.loadShared(root,data);
 }
 async function load(value){sharedCanvas.suspend();if(scope.team!==value.team){resourceOffset=0;resourceQuery='';}scope={...value};if(['account','join'].includes(value.area))scope={...scope,team:null,project:null,canvas:null};else if(['share','review','transfer'].includes(value.area)||value.area==='members'&&value.project)scope.team=null;activeArea=['account','workspace','members','share','review','projects','resources','transfer','join'].includes(value.area)?value.area:'workspace';memberScope=null;const n=++epoch;root.replaceChildren(el('p',msg("ui.loading_identity_and_scope")));try{if(value.page==='access-share')return await renderSharedView(n);const options=await ctx.api('/api/v1/authentication/options');if(n!==epoch)return;authenticationOptions=options;const callback=new URL(location.href);if(callback.searchParams.get('auth_result')){const attempt=callback.searchParams.get('auth_result'),status=callback.searchParams.get('auth_status');callback.searchParams.delete('auth_result');callback.searchParams.delete('auth_status');history.replaceState(null,'',callback);if(status==='verified'){try{const result=await post('/api/v1/authentication/oidc/'+encodeURIComponent(attempt)+'/complete',{});if(n!==epoch)return;await ctx.onSession(result);}catch(error){ctx.notice(error.message);}}else ctx.notice(msg("ui.third_party_login_is_incomplete_or_its_receipt_is"));}try{if(!await refresh())return;}catch(error){if(n!==epoch)return;if(error.status!==403)throw error;snapshot=null;}if(n===epoch)render(); }catch(error){if(n===epoch){if(value.page==='access-share'){const card=el('section');card.className='access-share-guard-card';const badge=el('span','画布协作分享');badge.className='access-share-guard-badge';const title=el('h2','访问受限或分享链接无效'),desc=el('p',error.message),actions=el('div');actions.className='access-share-guard-actions';const home=el('a','返回工作台首页');home.href='/home';home.className='access-share-home-link';actions.append(btn(msg("ui.reload"),()=>load(value)),home);card.append(badge,title,desc,actions);root.replaceChildren(card);}else root.replaceChildren(el('p',error.message),btn(msg("ui.reload"),()=>load(value)));}}}
 return {load,saveLanguage,suspend(){epoch++;for(const url of graphicUrls)URL.revokeObjectURL(url);graphicUrls.clear();sharedCanvas.suspend();},workspaces:()=>snapshot?.workspaces||[]};
}
