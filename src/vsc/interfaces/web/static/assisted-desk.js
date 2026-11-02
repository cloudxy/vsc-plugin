import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
import {artifactTitle, renderArtifactContent} from './artifact-reader.js';
import {renderReviewHistory, createArtifactReviewForm, previewContentUrl} from './review.js';

const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) setText(node,text);
  if (className) node.className = className;
  return node;
};
const labels = {review:msg("shell.review_queue"), progress:msg("ui.production_progress"), results:msg("ui.result_available")};
const kindLabels = {artifact:msg("ui.document"), candidate:msg("ui.candidate"), media:msg("ui.media"), job:msg("shell.tasks"), preview:msg("ui.revision_preview")};
export function deskLink({page='desk', project='', scope='', object='', version='', bucket='review'}) {
  const params = new URLSearchParams({page, bucket});
  for (const [key,value] of Object.entries({project,scope,object,version})) if(value)params.set(key,value);
  return `?${params}`;
}
export function parseDeskLocation(search) {
  const p = new URLSearchParams(search);
  return {page:['desk','projects','project','collection','trash'].includes(p.get('page'))?p.get('page'):'projects',
    project:p.get('project')||null, scope:p.get('scope')||null, object:p.get('object')||null,
    version:p.get('version')||null, bucket:labels[p.get('bucket')]?p.get('bucket'):'review'};
}

export function createAssistedDesk(root, ctx) {
  const state = {project:null, scope:null, page:'desk', bucket:'review', offset:0, ticket:0, objectTicket:0,
    revision:0, selected:null, data:null, mobilePanel:'content', embedded:false, drafts:new Map(), selections:new Map()};
  let queue, content, feedback, scopeLabel, timer;
  const base = () => `/api/v1/projects/${encodeURIComponent(state.project)}`;
  const button = (label, action, className) => {
    const b=el('button',label,className);b.type='button';
    b.addEventListener('click',async()=>{if(b.disabled)return;try{await action(b);}catch(error){ctx.notice(error.message);}});
    return b;
  };
  const writable = () => !!ctx.session().actor && !!ctx.session().writable;
  const draftKey = () => `${state.project}:${state.selected?.ref.kind}:${state.selected?.ref.id}`;
  const aliveAt = () => {const p=state.project,t=state.ticket,o=state.objectTicket;return()=>p===state.project&&t===state.ticket&&o===state.objectTicket;};
  const updateLink = () => !state.embedded&&ctx.route?.({page:state.page,project:state.project,scope:state.scope,
    bucket:state.bucket,object:state.selected?`${state.selected.ref.kind}:${state.selected.ref.id}`:'',
    version:state.selected?.ref.version_id||''});
  function pauseMedia() {root.querySelectorAll('video,audio').forEach(node=>node.pause?.());}
  function setMobilePanel(panel){
    state.mobilePanel=panel;root.dataset.mobilePanel=panel;
    for(const b of root.querySelectorAll('.desk-panel-switch'))b.setAttribute('aria-pressed',String(b.dataset.panel===panel));
  }
  function suspend() {state.ticket++;state.objectTicket++;clearTimeout(timer);pauseMedia();}
  function shell(title) {
    pauseMedia();root.replaceChildren();root.className=state.embedded?'assisted-desk object-stage':'assisted-desk';
    const bar=el('header',null,'desk-heading'),identity=el('div',null,'desk-identity');
    identity.append(el('h1',title));
    const actions=el('div',null,'desk-actions'),tools=el('details',null,'desk-tools'),summary=el('summary',msg("ui.professional_tools"));
    tools.append(summary);
    const links=el('div',null,'desk-tool-links');
    const groups=state.page==='collection'?[['素材查阅',[['library','分类资产'],['media','全部素材'],['canvas','关系画布']]]]:
      [['创作',[['source','创意与原稿'],['script','剧本编辑'],['designs','场镜设计'],['candidates','候选比较'],['delivery','剪辑交付']]],
        ['查阅',[['workbench','场镜关系'],['artifacts','文案版本'],['canvas','关系画布']]]];
    for(const [label,entries] of groups){
      const group=el('section',null,'desk-tool-group');group.append(el('h2',label));
      for(const [view,name] of entries)group.append(button(name,()=>{tools.open=false;return ctx.specialist(view);}));
      links.append(group);
    }
    tools.addEventListener('keydown',event=>{if(event.key==='Escape'&&tools.open){event.preventDefault();tools.open=false;summary.focus();}});
    tools.append(links);actions.append(tools);bar.append(identity,actions);root.append(bar);
    return {identity,actions};
  }
  function scaffold() {
    const {identity,actions}=shell(state.embedded?'当前作品':state.page==='collection'?'素材库':'工作台');
    root.classList.toggle('embedded-reviewer',state.embedded);
    if(state.embedded)root.querySelector('.desk-heading').hidden=true;
    root.classList.add('desk-with-panes');
    const bar=el('div',null,'desk-scope');
    const project=ctx.projectName?.()||'当前项目';
    scopeLabel=el('span',state.scope?msg("ui.current_selected_scope"):msg("ui.all_project_content"),'desk-scope-label');
    bar.append(el('span',project,'desk-project-name'),scopeLabel);
    if(!ctx.session().writable)bar.append(el('span',ctx.session().writeAvailable===false?msg("ui.this_service_is_read_only"):msg("ui.this_project_is_read_only"),'badge'));
    else if(!ctx.session().actor)bar.append(button(msg("ui.sign_in_to_comment"),()=>ctx.login()));
    identity.append(bar);
    actions.append(button(msg("common.refresh"),()=>load({...current(),refresh:true}),'desk-refresh'));
    const mobile=el('nav',null,'desk-mobile-navigation');bindAttribute(mobile,'aria-label',msg("ui.narrow_screen_workspace_switcher"));
    for(const [panel,label] of (state.embedded?[['content','作品'],['feedback','修改与意见']]:[['list','返回列表'],['content','作品'],['feedback','意见与结果']])){
      const b=button(label,()=>setMobilePanel(panel),'desk-panel-switch');b.dataset.panel=panel;mobile.append(b);
    }
    root.append(mobile);setMobilePanel(state.mobilePanel);
    const panes=el('div',null,'desk-panes');
    queue=el('nav',null,'desk-queue');bindAttribute(queue,'aria-label',msg("ui.review_and_results_list"));
    content=el('article',null,'desk-content');content.tabIndex=0;bindAttribute(content,'aria-label',msg("ui.work_content_and_playback"));
    feedback=el('aside',null,'desk-feedback');bindAttribute(feedback,'aria-label',msg("ui.comments_and_this_round_s_results"));
    const filters=el('div',null,'desk-buckets');bindAttribute(filters,'aria-label',msg("ui.work_status"));
    for(const [key,label] of Object.entries(state.page==='collection'?{results:'项目素材'}:labels)){
      const b=button(label,async()=>{state.bucket=key;state.offset=0;state.selected=null;await load(current());});
      b.dataset.bucket=key;b.setAttribute('aria-pressed',String(state.bucket===key));filters.append(b);
    }
    queue.append(filters,el('p',msg("ui.loading"),'empty'));
    content.append(el('p',msg("ui.select_an_item_to_read_or_play"),'empty'));
    feedback.append(el('h2',msg("ui.comments_and_this_round_s_results")),el('p',msg("ui.comments_bind_to_the_displayed_version"),'hint'));
    if(state.embedded)panes.append(content,feedback);else panes.append(queue,content,feedback);root.append(panes);
  }
  const current=()=>({projectId:state.project,objectId:state.scope,page:state.page,bucket:state.bucket});
  function runtimeControls(){
    const detail=el('details',null,'desk-runtime'),body=el('div');
    detail.append(el('summary',msg("ui.background_execution_status")),body);
    const ticket=state.ticket;
    const read=async(action=null)=>{
      body.replaceChildren(el('p',msg("ui.loading_background_status"),'hint'));
      try{
        const value=await ctx.api('/api/v1/execution',action?{method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},
          body:JSON.stringify({action})}:undefined);
        if(ticket!==state.ticket)return;
        body.replaceChildren(el('p',value.message,'hint'),
          el('p',value.generation?.available?msg("ui.production_worker_can_continue_tasks"):msg("ui.production_worker_is_not_running"),'hint'),
          el('p',value.edit_preview?.running?msg("ui.subtitle_preview_worker_can_continue_tasks"):msg("ui.subtitle_preview_worker_is_not_running"),'hint'));
        if(value.enabled&&ctx.session().actor){
          const paused=!value.generation?.accepting_submissions&&!value.edit_preview?.running;
          body.append(button(paused?msg("ui.resume_new_tasks_for_this_service"):msg("ui.pause_new_tasks_for_this_service"),()=>read(paused?'resume':'pause')));
          body.append(el('p',msg("ui.applies_to_all_projects_in_this_service_restart_restores"),'hint'));
        }
      }catch(error){if(ticket===state.ticket)body.replaceChildren(el('p',error.message),button(msg("ui.retry_background_status"),()=>read()));}
    };
    detail.addEventListener('toggle',()=>{if(detail.open)read();});
    return detail;
  }
  async function write(action,payload,key) {
    const alive=aliveAt(),project=state.project;
    if(!writable())throw new Error(ctx.session().actor?'此项目只读。':'请先登录，再提交意见。');
    const result=await ctx.api(`${base()}/${action}`,{method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},
      body:JSON.stringify({payload,expected_revision:state.revision,idempotency_key:key,confirmed:true})});
    if(project===state.project){state.revision=result.revision??state.revision;ctx.revision?.(state.revision);}
    return {result,alive:alive()};
  }
  async function load(options) {
    const previous=`${state.project}:${state.scope}:${state.page}:${state.bucket}`;
    state.project=options.projectId;state.scope=options.objectId||null;state.page=options.page||'desk';
    state.embedded=options.embedded===true;
    state.targetAnchor=options.targetAnchor||null;state.targetLabel=options.targetLabel||null;state.projection=options.projection||null;
    state.renderId=options.renderId||null;
    state.designArtifactId=options.designArtifactId||null;state.references=options.references||[];
    state.bucket=options.bucket|| (state.page==='collection'?'results':state.bucket);
    const identity=`${state.project}:${state.scope}:${state.page}:${state.bucket}`;
    if(previous!==identity){state.offset=0;state.selected=null;}
    const ticket=++state.ticket;state.objectTicket++;clearTimeout(timer);
    if(state.page==='projects'||!state.project){state.page='projects';await projects();updateLink();return;}
    if(state.page==='project'){await projectDirectory(ticket);updateLink();return;}
    if(state.page==='trash'){await recycle(options.recycleView||'trash');updateLink();return;}
    scaffold();
    const alive=()=>ticket===state.ticket;
    root.setAttribute('aria-busy','true');
    try {
      const params=new URLSearchParams({bucket:state.bucket,limit:'24',offset:String(state.offset)});
      if(state.scope)params.set('object_id',state.scope);
      let data;
      if(state.embedded&&options.ref){
        data={revision:ctx.session().revision,items:[],counts:{},ancestors:[],scope:options.scopeLabel?{title:options.scopeLabel}:null};
      }else if(state.page==='collection'){
        params.delete('bucket');
        const media=await ctx.api(`${base()}/media?${params}`);
        data={...media,ancestors:[],scope:null,counts:{results:media.total},next_offset:state.offset+media.items.length<media.total?state.offset+media.items.length:null,
          items:media.items.map(m=>({id:'media:'+m.id,kind:'media',title:m.name||m.title||'未命名素材',
            status_label:m.deprecated?'已停用':'已登记素材',ref:{kind:'media',id:m.id}}))};
      }else data=await ctx.api(`${base()}/assisted-desk?${params}`);
      if(!alive())return;
      state.data=data;state.revision=data.revision;ctx.revision?.(data.revision);
      if(data.scope)setText(scopeLabel,data.scope.title||data.scope.display_code||msg("ui.current_selected_scope"));
      if(!state.embedded)renderQueue(data);
      const desired=options.ref || state.selections.get(identity);
      const matched=desired&&data.items.find(r=>`${r.ref.kind}:${r.ref.id}`===desired&&(!options.version||r.ref.version_id===options.version));
      if(options.ref){
        const [kind,...rest]=options.ref.split(':'),identifier=rest.join(':');
        if(!['artifact','media','job'].includes(kind)||!identifier)throw new Error('固定内容链接无效，请返回目录选择内容。');
        // A fixed deep link may point to an earlier reviewed version outside
        // the current queue/page. Never silently replace it with a new draft.
        await select(matched||{title:'固定版本',ref:{kind,id:kind==='artifact'&&options.version?options.version:identifier,version_id:options.version}});
      }
      else if(matched||data.items[0])await select(matched||data.items[0]);
      else{
        content.replaceChildren(el('h2',state.bucket==='review'?msg("ui.nothing_awaiting_review"):state.bucket==='progress'?msg("ui.no_tasks_in_progress"):msg("ui.no_results_yet")));
        content.append(el('p',data.message||msg("ui.continue_viewing_and_editing_source_text_and_scripts_inside"),'hint'),button(msg("ui.open_project"),()=>ctx.navigate('projects')));
      }
      updateLink();
    } catch(error) {
      if(!alive())return;
      queue.replaceChildren(el('p',msg("ui.loading_blocked_value0",{value0:error.message}),'empty'),button(msg("ui.reload"),()=>load(current())));
    } finally {if(alive())root.setAttribute('aria-busy','false');}
  }
  function renderQueue(data) {
    const filters=queue.firstElementChild || queue.children[0];queue.replaceChildren(filters);
    if(state.bucket==='progress')queue.append(runtimeControls());
    const selectedForReview=new Map();
    for(const b of filters.querySelectorAll('button')){const n=data.counts?.[b.dataset.bucket];setText(b,(state.page==='collection'?'项目素材':labels[b.dataset.bucket])+(n==null?'':` ${n}`));}
    if(data.message)queue.append(el('p',data.message,'hint'));
    for(const row of data.items){
      const link=el('a',null,'desk-item');link.href=deskLink({page:state.page,project:state.project,scope:state.scope,bucket:state.bucket,
        object:`${row.ref.kind}:${row.ref.id}`,version:row.ref.version_id});
      link.dataset.ref=`${row.ref.kind}:${row.ref.id}`;
      const title=row.kind==='artifact'?artifactTitle({artifact_type:row.content_kind,title:row.title}):row.title;
      link.append(el('span',title||msg("ui.untitled_content"),'desk-item-title'),el('small',joinMessages(["",kindLabels[row.kind]||msg("ui.content")," · ",row.status_label||msg("ui.available_for_review"),""])));
      link.addEventListener('click',async event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();await select(row);});queue.append(link);
      if(writable()&&row.kind==='artifact'&&row.status==='draft'){
        const label=el('label',msg("ui.include_in_this_review"),'desk-review-select'),check=el('input');check.type='checkbox';
        check.addEventListener('change',()=>check.checked?selectedForReview.set(row.id,row):selectedForReview.delete(row.id));
        label.prepend(check);queue.append(label);
      }
    }
    if(!data.items.length)queue.append(el('p',msg("ui.no_items_in_this_category"),'empty'));
    const pager=el('div',null,'desk-pagination'),prev=button(msg("common.previous_page"),async()=>{state.offset=Math.max(0,state.offset-24);await load(current());}),
      next=button(msg("common.next_page"),async()=>{state.offset=data.next_offset;await load(current());});
    prev.disabled=state.offset===0;next.disabled=data.next_offset==null;
    pager.append(prev,el('span',msg("ui.value0_items",{value0:data.total})),next);queue.append(pager);
    if(data.items.some(r=>r.kind==='artifact'&&r.status==='draft')&&writable())
      queue.append(button(msg("ui.review_selected_versions_on_this_page"),()=>batchReview([...selectedForReview.values()])));
  }
  async function batchReview(rows){
    if(!rows.length)throw new Error('先勾选本页已经呈现的文案版本。');
    state.objectTicket++;const alive=aliveAt();
    setMobilePanel('feedback');
    feedback.replaceChildren(el('h2',msg("ui.versions_selected_for_this_review")),el('p',msg("ui.record_decisions_only_for_the_fixed_versions_below_unchecked"),'hint'));
    const results=el('div'),ready=[];feedback.append(results);
    for(const row of rows){
      const line=el('p',msg("ui.value0_checking",{value0:row.title}));results.append(line);
      try{
        const value=await ctx.api(`${base()}/artifacts/${encodeURIComponent(row.ref.id)}`);
        if(!alive())return;
        if(value.integrity==='mismatch'||value.availability==='missing'||(row.ref.sha256&&row.ref.sha256!==value.sha256))throw new Error('固定内容已变化或缺失，请单独回看');
        if(value.approved)throw new Error('此版本已经批准，本次保留现有决定');
        ready.push({row,value,line,key:crypto.randomUUID()});setText(line,msg("ui.value0_version_value1_awaiting_decision",{value0:artifactTitle(value),value1:value.version||1}));
      }catch(error){if(!alive())return;setText(line,joinMessages(["",row.title,"：",error.message,""]));}
    }
    const reason=el('textarea');reason.rows=3;reason.name='batch_reason';bindAttribute(reason,'aria-label',msg("ui.decision_reason_for_this_version"));bindAttribute(reason,"placeholder",msg("ui.explain_your_decision_about_the_selected_fixed_versions"));
    let fixedReason=null;
    const approve=button(msg("ui.approve_value0_checked_versions",{value0:ready.length}),async b=>{
      if(!reason.value.trim())throw new Error('请填写本次决定理由。');
      fixedReason ||= reason.value;b.disabled=true;reason.disabled=true;
      for(const item of ready){
        if(!alive())return;if(item.done)continue;
        try{
          const {alive:current}=await write('artifact-decisions',{artifact_id:item.row.ref.id,outcome:'approve',reason:fixedReason},item.key);
          item.done=true;if(!current)return;setText(item.line,msg("ui.value0_this_fixed_version_is_approved",{value0:artifactTitle(item.value)}));
        }catch(error){if(!alive())return;setText(item.line,msg("ui.value0_not_approved_value1",{value0:artifactTitle(item.value),value1:error.message}));}
      }
      if(alive()){b.disabled=ready.every(r=>r.done);setText(b,b.disabled?msg("ui.selected_version_decisions_recorded"):msg("ui.retry_incomplete_decisions"));}
    });
    approve.disabled=!ready.length;feedback.append(reason,approve);
  }
  async function select(row) {
    pauseMedia();state.selected=row;state.objectTicket++;
    setMobilePanel('content');
    const alive=aliveAt(),project=state.project,ref=row.ref;
    state.selections.set(`${state.project}:${state.scope}:${state.page}:${state.bucket}`,`${ref.kind}:${ref.id}`);
    if(state.embedded)ctx.selectedRef?.({...ref,render_id:state.renderId});
    for(const link of queue.querySelectorAll('a')){const selected=link.dataset.ref===`${ref.kind}:${ref.id}`;if(selected)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');}
    updateLink();content.replaceChildren(el('p',msg("ui.loading_the_displayed_content"),'empty'));feedback.replaceChildren();
    try {
      const endpoint=ref.kind==='artifact'?`artifacts/${encodeURIComponent(ref.id)}`:ref.kind==='media'?`media/${encodeURIComponent(ref.id)}`:
        `workbench?section=job_attempts&entity_id=${encodeURIComponent(ref.id)}&limit=1`;
      const value=await ctx.api(`${base()}/${endpoint}`);if(!alive())return;
      const title=ref.kind==='artifact'?artifactTitle(value):value.name||row.title||'制作任务';
      const header=el('header',null,'desk-object-heading');header.append(el('h2',title));
      const context=el('p',null,'hint');
      const path=[...(state.data?.ancestors||[]),state.data?.scope].filter(Boolean).map(r=>r.title||r.display_code).join(' / ');
      setText(context,joinMessages(["",ctx.projectName?.()||msg("ui.current_project"),"",path?joinMessages([" / ",path]):'',"",value.version!=null?msg("ui.version_value0_nested_112",{value0:value.version}):'',""]));
      header.append(context);
      content.replaceChildren(header);content.scrollTop=0;
      if(row.blocked_reason)content.append(el('p',row.blocked_reason,'desk-blocked'));
      if(ref.kind==='artifact'){
        const fixed=value.content!==undefined?value.content:value.document;
        if(fixed==null||value.availability==='missing')content.append(
          el('p',msg("ui.text_is_temporarily_unreadable_check_this_fixed_version_s"),'desk-blocked'),
          button(msg("ui.view_version_and_source"),()=>ctx.artifact(ref.id)));
        else {
          const rendered=renderArtifactContent(state.embedded&&state.projection&&ref.id===state.designArtifactId?state.projection:fixed,{mimeType:value.mime_type});
          content.append(rendered.body);
          if(rendered.mediaKind)content.append(button(msg("ui.open_existing_result"),async()=>{
            state.bucket='results';state.offset=0;state.selected=null;await load(current());
          }));
        }
        if(value.integrity==='mismatch')content.prepend(el('p',msg("ui.the_displayed_file_digest_changed_use_it_only_for"),'desk-blocked'));
      }else if(ref.kind==='media'){
        if(value.result_availability?.status==='unavailable'){
          content.append(el('p',value.result_availability.message||msg("ui.current_media_is_unreadable_check_its_source"),'desk-blocked'),
            button(msg("ui.reload_media"),()=>select(row)));
        }else{
          if(value.result_availability?.status==='unverified'&&value.result_availability.message)content.append(el('p',value.result_availability.message,'hint'));
          const node=await ctx.player(value);if(!alive())return;content.append(node);
        }
        content.append(button(msg("ui.purpose_source_and_candidate_decisions"),()=>ctx.media(ref.id)));
        const renders=[...new Map((value.review_targets||[]).filter(row=>row.target?.render_id).map(row=>[row.target.render_id,row])).values()];
        if(renders.length)renderPositionControls(value,renders,alive);
      }else{
        const job=value.sections?.job_attempts?.items?.[0];
        const outputs=(job?.outputs||[]).filter(output=>output.media_id);
        content.append(el('p',msg("ui.execution_value0",{value0:({succeeded:'已结束',failed:'执行受阻',submission_unknown:'提交结果待核实',
          created:'等待执行',queued:'等待执行',running:'正在执行',submitted:'已提交服务',polling:'正在等待服务',
          cancelled:'已停止'})[job?.status]||row.status_label||msg("ui.status_needs_verification")})));
        content.append(el('p',outputs.length?msg("ui.result_value0_items_registered_open_them_for_review",{value0:outputs.length}):
          job?.status==='succeeded'?msg("ui.execution_finished_but_no_result_is_registered_yet_refresh"):msg("ui.no_registered_result_yet_existing_works_and_comments_remain"),
          outputs.length?'hint':'desk-blocked'));
        for(const output of outputs)content.append(button(msg("ui.view_this_result"),()=>select({title:'制作结果',ref:{kind:'media',id:output.media_id}})));
        if(outputs.length)content.append(el('p',msg("ui.review_and_selection_follow_the_result_s_corresponding_role"),'hint'));
        else content.append(button(msg("ui.reload_task"),()=>select(row)));
        const details=el('details');details.append(el('summary',msg("ui.execution_record")),el('pre',JSON.stringify(job||{},null,2),'structured'));content.append(details);
        const quote=el('section',null,'job-quote');content.append(quote);await renderJobQuote(ref.id,quote,alive);if(!alive())return;
      }
      const evidence=el('details',null,'desk-evidence');evidence.append(el('summary',msg("ui.versions_and_verification")),el('p',joinMessages(["",ref.id,"",value.sha256?joinMessages([" · ",value.sha256]):'',""]),'hint'));content.append(evidence);
      await renderFeedback(value,ref,alive);
      if(!alive())return;
      if(ref.kind==='artifact'&&ctx.session().writable)content.append(button(msg("ui.review_this_fixed_version"),()=>ctx.artifact(ref.id)));
      if(ref.kind==='job')feedback.append(el('p',msg("ui.registered_tasks_and_execution_receipts_appear_here_waiting_does"),'hint'));
      if(project!==state.project)return;
    }catch(error){
      if(!alive())return;content.replaceChildren(el('p',msg("ui.content_loading_blocked_value0",{value0:error.message}),'empty'),button(msg("ui.retry_current_content"),()=>select(row)));
    }
  }
  async function renderJobQuote(jobId,host,alive){
    host.replaceChildren(el('h3',msg("ui.usage_and_estimate_for_this_task")),el('p',msg("ui.checking_this_task_s_fixed_records"),'hint'));
    try{
      const value=await ctx.api(`${base()}/generation-jobs/${encodeURIComponent(jobId)}/quote`);if(!alive())return;
      const quote=value?.quote,actual=value?.reconciliation;
      host.replaceChildren(el('h3',msg("ui.usage_and_estimate_for_this_task")));
      if(!quote){host.append(el('p',msg("ui.this_task_has_no_fixed_quote_snapshot_its_amount"),'hint'));return;}
      const units=value=>Object.entries(value||{}).map(([key,n])=>`${({remote_jobs:'服务任务',images:'图片张数',video_seconds:'视频秒数',audio_jobs:'声音任务',speech_chars:'语音字数',vision_jobs:'视觉任务'})[key]||key} ${n}`).join('；');
      if(units(quote.native_units))host.append(el('p',msg("ui.estimated_usage_value0",{value0:units(quote.native_units)})));
      host.append(el('p',quote.status==='estimate'&&quote.amount!=null?msg("ui.estimated_amount_value0_value1_actual_bill_is_unverified",{value0:quote.amount,value1:quote.currency||''}):msg("ui.amount_is_unverified_unknown_does_not_mean_free")));
      if(quote.reason)host.append(el('p',quote.reason,'hint'));
      host.append(el('p',actual?.actual_units_reported?msg("ui.reported_actual_usage_value0",{value0:units(actual.actual_units)}):msg("ui.actual_usage_has_not_been_reported"),'hint'));
      if(actual?.actual_units_reported&&units(actual.native_delta))host.append(el('p',msg("ui.difference_from_estimated_usage_value0",{value0:units(actual.native_delta)}),'hint'));
      if(actual?.threshold_exceeded===true)host.append(el('p',msg("ui.actual_usage_deviation_exceeds_the_configured_threshold_check_the"),'desk-blocked'));
      if(actual?.actual_amount!=null)host.append(el('p',msg("ui.recorded_bill_value0_value1",{value0:actual.actual_amount,value1:actual.actual_currency||actual.currency||''})));
      else host.append(el('p',msg("ui.actual_cost_is_unverified_usage_and_estimates_above_are"),'hint'));
      if(quote.source){const source=el('details');source.append(el('summary',msg("ui.estimate_basis")),el('p',[quote.source.source_date,quote.source.source_url].filter(Boolean).join(' · '),'hint'));host.append(source);}
    }catch(error){if(alive())host.replaceChildren(el('h3',msg("ui.usage_and_estimate_for_this_task")),el('p',msg("ui.loading_blocked_value0_the_original_execution_receipt_remains_reload",{value0:error.message}),'hint'));}
  }
  async function renderFeedback(value,ref,alive) {
    feedback.replaceChildren(el('h2',msg("ui.comments_and_this_round_s_results")));
    if(state.references.length){const references=el('section',null,'object-reference-strip');references.append(el('h3',msg("ui.references_for_this_shot")));for(const row of state.references.slice(0,8)){const b=button(row.label||msg("ui.view_storyboard_reference"),()=>select({title:row.label||'分镜参考',ref:{kind:'media',id:row.media_id}}));const image=el('img');image.src=`${base()}/media/${encodeURIComponent(row.media_id)}/content`;bindAttribute(image,"alt",row.label||msg("ui.fixed_storyboard_reference"));image.width=96;image.height=72;image.loading='lazy';image.addEventListener('error',()=>{image.remove();setText(b,msg("ui.reference_loading_blocked_select_to_check"));},{once:true});b.prepend(image);references.append(b);}if(state.designArtifactId&&ref.id!==state.designArtifactId)references.append(button(msg("ui.return_to_this_design"),()=>select({title:'本镜设计',ref:{kind:'artifact',id:state.designArtifactId,version_id:state.designArtifactId}})));feedback.append(references);}
    const reloadHistory=async()=>{
      if(!alive())return;
      const data=await ctx.api(`${base()}/review-history?${ref.kind==='media'?'media_id':'artifact_id'}=${encodeURIComponent(ref.id)}`);
      if(alive()){state.revision=Math.max(state.revision||0,data.revision||0);ctx.revision?.(state.revision);history.replaceChildren(renderReviewHistory(data,reviewCtx));}
    };
    const reviewCtx={heading:false,reload:reloadHistory,artifact:id=>select({title:'修改结果',ref:{kind:'artifact',id,version_id:id}}),
      historyPage:async(filters,page)=>{const data=await ctx.api(`${base()}/review-history?`+new URLSearchParams({...filters,...page}));if(alive())return data;},
      media:id=>select({title:'修改结果',ref:{kind:'media',id}}),
      ...(writable()?{process:async(payload,key)=>{if(!alive())return;await write('review-process',payload,key);if(alive())await reloadHistory();}}:{}),
      ...(writable()?{retryPreview:async(preview,item,key)=>{
        if(!alive())return;
        await write(`edit-previews/${encodeURIComponent(preview.id)}/retry`,{},key);
        if(!alive())return;await reloadHistory();
        const status=el('p',msg("ui.recovering_this_preview"),'hint');status.setAttribute('role','status');feedback.append(status);
        pollPreview(item.source.artifact_note_id,alive,status,reloadHistory);
      }}:{}),
      local:(action,row)=>ctx.local(action,{...row,onReviewProposed:async()=>{if(alive())await reloadHistory();}}),onError:error=>ctx.notice(error.message)};
    const history=el('div',null,'desk-history');
    if(ref.kind==='media'&&writable()&&ctx.mediaActions){const actions=await ctx.mediaActions(value,alive,()=>select(state.selected));if(!alive())return;if(actions)feedback.append(actions);}
    if(!writable())feedback.append(el('p',ctx.session().writable?msg("ui.sign_in_to_record_comments_reading_is_available_now"):msg("ui.this_project_is_read_only_view_existing_comments_and"),'hint'));
    const reviewTargets=(value.review_targets||[]).filter(row=>(!state.targetAnchor||ref.id!==state.designArtifactId||Object.entries(state.targetAnchor).every(([key,id])=>row.target?.[key]===id))&&(!state.renderId||row.target?.render_id===state.renderId)).map(row=>state.targetLabel&&state.targetAnchor&&ref.id===state.designArtifactId?{...row,label:state.targetLabel}:row);
    if(writable() && reviewTargets?.length){
      let capability;
      try{capability=await ctx.api(`${base()}/edit-preview-capability?${ref.kind==='media'?'media_id':'artifact_id'}=${encodeURIComponent(ref.id)}`);}
      catch(error){capability={available:false,reason:`局部预览暂不可用：${error.message}`};}
      if(!alive())return;
      if(capability.available&&state.renderId&&capability.target?.render_id!==state.renderId)capability={available:false,reason:'当前可执行字幕预览不对应所见固定成片，原意见仍可记录；请核对固定版本。'};
      if(capability.available)feedback.append(editForm(capability,alive,reloadHistory));
      else{
        const key=draftKey();let saved=state.drafts.get(key);try{saved ||= JSON.parse(sessionStorage.getItem('vsc-opinion:'+key)||'null');}catch{}
        const form=createArtifactReviewForm(reviewTargets,{currentTime:()=>content.querySelector('video')?.currentTime||0,
          save:async(payload,idempotency)=>{if(!alive())throw new Error('所见对象已切换，请返回原对象继续。');const result=await write('artifact-review-notes',payload,idempotency);if(result.alive){if(state.drafts.get(key)?.body===payload.body){state.drafts.delete(key);try{sessionStorage.removeItem('vsc-opinion:'+key);}catch{}form.querySelector('textarea').value='';}await reloadHistory();}}});
        const input=form.querySelector('textarea'),target=form.querySelector('select'),ranges=form.querySelectorAll('input');
        if(saved){input.value=saved.body;if(saved.target!=null)target.value=saved.target;for(const [index,range]of ranges.entries())if(saved.ranges?.[index]!=null)range.value=saved.ranges[index];}
        const remember=()=>{const value={body:input.value,target:target.value,ranges:[...ranges].map(r=>r.value)};if(input.value.trim())state.drafts.set(key,value);else state.drafts.delete(key);try{if(input.value.trim())sessionStorage.setItem('vsc-opinion:'+key,JSON.stringify(value));else sessionStorage.removeItem('vsc-opinion:'+key);}catch{}};
        input.addEventListener('input',remember);target.addEventListener('change',remember);for(const range of ranges)range.addEventListener('input',remember);
        feedback.append(form);
        if(capability.reason)feedback.append(el('p',capability.reason,'hint'));
      }
    }
    history.append(renderReviewHistory(value.review_history,reviewCtx));feedback.append(history);
  }
  function renderPositionControls(media,renders,alive){
    const box=el('section',null,'render-position'),label=el('label',msg("ui.final_output_timecode_seconds")),time=el('input'),result=el('div'),render=el('select');
    time.type='number';time.min='0';time.step='0.001';time.value='0';label.append(time);bindAttribute(render,'aria-label',msg("ui.fixed_final_output_version"));
    for(const [i,row]of renders.entries()){const option=el('option',msg("ui.fixed_final_output_value0",{value0:i+1}));option.value=row.target.render_id;render.append(option);}
    if(state.renderId&&renders.some(row=>row.target.render_id===state.renderId))render.value=state.renderId;
    else if(renders.length>1){const choose=el('option',msg("ui.choose_the_fixed_final_output_to_locate"));choose.value='';render.prepend(choose);render.value='';}
    let request=0;
    const locate=async()=>{if(!alive())return;const id=render.value;if(!id){setText(result,msg("ui.select_a_fixed_final_output_version_first"));return;}const ticket=++request;setText(result,msg("ui.loading_fixed_timeline_position"));try{const data=await ctx.api(`${base()}/renders/${encodeURIComponent(id)}/position?time_ms=${Math.round(Number(time.value)*1000)}`);if(!alive()||ticket!==request)return;result.replaceChildren(el('p',msg("ui.timeline_frame_value0",{value0:data.frame}),'hint'));for(const row of data.items||[])if(row.shot_id)result.append(button(row.title||row.display_code||msg("ui.locate_shot"),()=>ctx.locateObject?.(row.shot_id)));for(const row of data.lines||[]){result.append(el('p',row.text||row.display_text||''));if(row.script_version_id)result.append(button(msg("ui.read_the_fixed_dialogue_version_used"),()=>ctx.artifact(row.script_version_id)));}if(data.line_message)result.append(el('p',data.line_message,'hint'));if(data.truncated)result.append(el('p',msg("ui.materials_at_this_frame_exceed_this_page_s_limit"),'hint'));}catch(error){if(alive()&&ticket===request)setText(result,error.message);}};
    box.append(label,render,button(msg("ui.use_current_playback_timecode_and_locate"),()=>{time.value=String(content.querySelector('video')?.currentTime||0);return locate();}),button(msg("ui.locate_entered_timecode"),locate),result);
    const download=el('a',msg("ui.download_current_fixed_output"));download.href=`${base()}/media/${encodeURIComponent(media.id)}/content?download=true`;box.append(download,el('p',msg("ui.formal_delivery_still_follows_the_original_checks_downloading_adds"),'hint'));content.append(box);
  }
  function editForm(capability,alive,reloadHistory) {
    const form=el('form',null,'desk-opinion review-form'),key=draftKey();let saved=state.drafts.get(key);try{saved ||= JSON.parse(sessionStorage.getItem('vsc-opinion:'+key)||'null');}catch{}saved ||= {};
    const cue=el('select'),label=el('label',msg("ui.which_subtitle_to_edit")),body=el('textarea'),status=el('p',null,'hint');
    cue.name='caption';bindAttribute(cue,'aria-label',msg("ui.choose_subtitle"));label.append(cue);
    for(const c of capability.cues){const option=el('option',c.text||msg("ui.empty_subtitle"));option.value=c.id;cue.append(option);}
    if(saved.caption_id)cue.value=saved.caption_id;
    body.name='opinion';body.rows=4;body.maxLength=4000;body.required=true;body.value=saved.body||'';
    bindAttribute(body,"placeholder",msg("ui.for_example_move_this_subtitle_upward"));bindAttribute(body,'aria-label',msg("ui.revision_comment"));
    const record=el('button',msg("ui.record_comment")),submit=el('button',msg("ui.show_me_the_revision"),'primary');record.type=submit.type='submit';record.value='record';submit.value='modify';
    status.setAttribute('role','status');
    form.append(label,body,el('p',msg("ui.adjust_only_the_selected_subtitle_s_position_and_preserve"),'hint'),record,submit,status);
    let operationKey=saved.key||null,lastAction=saved.action||null;
    const remember=()=>{operationKey=null;const value={body:body.value,caption_id:cue.value};state.drafts.set(key,value);try{sessionStorage.setItem('vsc-opinion:'+key,JSON.stringify(value));}catch{}};
    body.addEventListener('input',remember);cue.addEventListener('change',remember);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(submit.disabled||!alive())return;
      const caption=capability.cues.find(c=>c.id===cue.value);if(!caption){setText(status,msg("ui.select_the_subtitle_again"));return;}
      const target={...capability.target,start_frame:caption.start_frame,end_frame:caption.end_frame};
      const action=event.submitter?.value==='record'?'artifact-review-notes':'edit-preview-requests';
      if(lastAction!==action)operationKey=null;lastAction=action;
      operationKey ||= crypto.randomUUID();const submittedBody=body.value,submittedKey=operationKey;
      state.drafts.set(key,{body:submittedBody,caption_id:cue.value,key:operationKey,action});
      try{sessionStorage.setItem('vsc-opinion:'+key,JSON.stringify(state.drafts.get(key)));}catch{}
      record.disabled=submit.disabled=true;setText(status,msg("ui.saving_comment"));
      try{
        const {result,alive:stillHere}=await write(action,action==='artifact-review-notes'?{...target,body:body.value}:{target,body:body.value,caption_id:caption.id},operationKey);
        const unchanged=state.drafts.get(key)?.key===submittedKey&&state.drafts.get(key)?.body===submittedBody;
        if(unchanged){state.drafts.delete(key);try{sessionStorage.removeItem('vsc-opinion:'+key);}catch{}}
        if(!stillHere)return;if(unchanged){body.value='';operationKey=null;}setText(status,result.explanation||msg("ui.original_comment_saved"));
        await reloadHistory();
        if(result.note_id)pollPreview(result.note_id,alive,status,reloadHistory);
      }catch(error){if(alive())setText(status,msg("ui.value0_the_original_comment_remains_in_the_input",{value0:error.message}));}
      finally{if(alive())record.disabled=submit.disabled=false;}
    });
    return form;
  }
  async function pollPreview(note,alive,status,reloadHistory) {
    clearTimeout(timer);
    if(!alive())return;
    try{
      const value=await ctx.api(`${base()}/edit-previews?artifact_note_id=${encodeURIComponent(note)}`);
      if(!alive())return;const job=value.items?.at(-1);
      if(job&&(previewContentUrl(job)||['succeeded','failed','blocked','cancelled','stale'].includes(job.status))){
        // Refresh the original opinion instead of appending a second copy that
        // leaves its earlier queued state visible beside the finished result.
        await reloadHistory();
        if(!alive())return;
        setText(status,previewContentUrl(job)?msg("ui.preview_registered_revision_awaits_review"):
          job.result_availability?.message||job.error||(job.status==='succeeded'?msg("ui.execution_finished_but_no_preview_is_available_for_review"):msg("ui.preview_is_incomplete_the_original_comment_remains")));return;
      }
      setText(status,job?.error||job?.explanation||msg("ui.registered_waiting_for_a_worker"));
      if(job && ['failed','blocked','cancelled','stale'].includes(job.status))return;
      timer=setTimeout(()=>pollPreview(note,alive,status,reloadHistory),2500);
    }catch(error){if(alive()){setText(status,msg("ui.progress_loading_blocked_value0",{value0:error.message}));feedback.append(button(msg("ui.reload_progress"),()=>pollPreview(note,alive,status,reloadHistory)));}}
  }
  async function projects() {
    shell('项目');
    const list=el('div',null,'desk-projects');root.append(list);
    for(const project of ctx.projects()){
      const card=el('article',null,'desk-project');
      card.append(el('h2',project.name),el('p',ctx.session().writeAvailable===false?msg("ui.existing_content_is_available_for_review"):project.read_only?msg("ui.read_only_project"):msg("ui.continue_creating_more_672"),'hint'),
        button(msg("ui.open_episode"),()=>ctx.chooseProject(project.id,'project')),
        button(msg("ui.ideas_and_source_text"),async()=>{await ctx.chooseProject(project.id,'projects');await ctx.specialist('source');}));
      list.append(card);
    }
    if(!ctx.projects().length)list.append(el('p',ctx.session().writeAvailable===false?msg("ui.no_projects_available_to_browse"):msg("ui.no_projects_yet_create_one_then_add_an_idea"),'empty'));
    if(ctx.session().writeAvailable===false){root.append(el('p',msg("ui.this_service_is_read_only_existing_works_are_available"),'hint'));return;}
    const form=el('form',null,'desk-create'),name=el('input'),label=el('label',msg("ui.new_project_name")),submit=el('button',msg("ui.create_project_more_679")),status=el('p');
    name.name='project_name';name.required=true;name.maxLength=120;name.autocomplete='off';label.append(name);
    submit.type='submit';status.setAttribute('role','status');form.append(label,submit,status);root.append(form);
    if(!ctx.session().actor){submit.disabled=true;form.append(button(msg("ui.sign_in_first"),()=>ctx.login()));}
    let createKey=null;name.addEventListener('input',()=>{createKey=null;});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(submit.disabled)return;submit.disabled=true;createKey ||= crypto.randomUUID();
      try{const result=await ctx.api('/api/v1/projects',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},
        body:JSON.stringify({payload:{name:name.value,profile:'vsc.series-pg'},idempotency_key:createKey})});await ctx.created(result.id);}
      catch(error){setText(status,error.message);}finally{submit.disabled=false;}
    });
  }
  async function projectDirectory(ticket) {
    shell(ctx.projectName?.() || '项目');
    const body=el('section',null,'project-directory');root.append(body);
    body.append(el('p',msg("ui.loading_registered_directory"),'hint'));
    try{
      const params=new URLSearchParams({section:'children',limit:'24',offset:String(state.offset)});if(state.scope)params.set('object_id',state.scope);
      const data=await ctx.api(`${base()}/workbench?${params}`);if(ticket!==state.ticket)return;
      state.revision=data.revision;ctx.revision?.(data.revision);body.replaceChildren();
      const trail=el('nav',null,'project-breadcrumb');bindAttribute(trail,'aria-label',msg("ui.project_location"));
      const link=(row,label)=>{const a=el('a',label||row.title||row.display_code);a.href=deskLink({page:'project',project:state.project,scope:row.id});a.addEventListener('click',event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();ctx.chooseProject(state.project,'project',row.id);});return a;};
      trail.append(link({id:null},ctx.projectName?.()||'项目'));
      for(const ancestor of data.ancestors||[])trail.append(el('span',' / '),link(ancestor));
      if(data.scope)trail.append(el('span',' / '),el('strong',data.scope.title||data.scope.display_code));body.append(trail);
      const actions=el('div',null,'project-object-actions');
      if(data.scope&&['episode','scene','sequence','shot'].includes(data.scope.kind))actions.append(button(msg("ui.read_script"),()=>ctx.specialist('script')),button(msg("ui.scenes_shots_and_candidates"),()=>ctx.specialist('workbench')),button(msg("shell.review_queue"),()=>ctx.navigate('desk')));
      if(data.scope?.kind==='shot')actions.append(button(msg("ui.choose_reference_media_for_this_shot"),()=>ctx.library({target_object_id:data.scope.id,role:'first_frame'})));
      if(!data.scope)actions.append(button(msg("ui.ideas_and_source_text"),()=>ctx.specialist('source')),button(msg("shell.project_assets"),()=>ctx.specialist('library')));
      body.append(actions);
      const items=data.sections?.children||{},grid=el('div',null,'project-object-grid');
      for(const row of items.items||[]){const card=el('article',null,'project-object-card');card.append(el('p',({work:'部',episode:'集',scene:'场',sequence:'镜组',shot:'镜头',asset:'资产'})[row.kind]||msg("ui.content"),'hint'),link(row));grid.append(card);}body.append(grid);
      if(!items.items?.length)body.append(el('p',data.scope?.kind==='shot'?msg("ui.shot_located_use_the_entries_above_for_candidates_references"):msg("ui.no_registered_children_in_this_directory_continue_through_ideas"),'empty'));
      const paging=el('nav',null,'desk-pagination');for(const [label,offset]of [[msg("common.previous_page"),state.offset>0?Math.max(0,state.offset-24):null],[msg("common.next_page"),items.next_offset]]){const b=button(label,async()=>{state.offset=offset;await projectDirectory(++state.ticket);});b.disabled=offset==null;paging.append(b);}body.append(paging);
    }catch(error){if(ticket===state.ticket)body.replaceChildren(el('p',msg("ui.directory_loading_blocked_value0",{value0:error.message})),button(msg("novel-parser.back_to_projects"),()=>ctx.navigate('projects')));}
  }
  async function recycle(view) {
    state.ticket++;state.objectTicket++;clearTimeout(timer);
    shell(view==='duplicates'?'整理重复内容':'回收站');
    root.append(el('p',msg("ui.trashing_is_reversible_and_preserves_source_files_and_history"),'hint'),
      button(view==='duplicates'?msg("ui.view_trash"):msg("ui.organize_duplicate_content"),()=>recycle(view==='duplicates'?'trash':'duplicates')));
    const list=el('div',null,'desk-recycle-list');root.append(list);
    const ticket=state.ticket,alive=()=>ticket===state.ticket;
    try{
      const data=await ctx.api(`${base()}/recycle?view=${view}&limit=24&offset=${state.offset}`);
      if(!alive())return;state.revision=data.revision;
      const selected=new Set();
      for(const row of data.items){
        const group=el('article',null,'desk-recycle-item');
        for(const item of view==='duplicates'?row.items:[row]){
          const line=el('div',null,'desk-recycle-row');line.append(el('strong',item.name||msg("ui.unnamed_media")));
          if(item.recycled)line.append(el('span',msg("ui.already_in_trash"),'hint'));
          if(item.reasons?.length)line.append(el('p',item.reasons.map(r=>r.label).join('；'),'hint'));
          if(view==='trash'&&writable())line.append(button(msg("common.restore"),async b=>{b.disabled=true;try{await write('recycle-actions',{media_ids:[item.id],action:'restore',reason:'用户在回收站恢复'},crypto.randomUUID());if(alive())await recycle(view);}finally{b.disabled=false;}}));
          else if(writable()){
            const label=el('label',msg("ui.select_for_trash")),check=el('input');check.type='checkbox';check.disabled=!!item.protected||!!item.recycled;
            check.addEventListener('change',()=>check.checked?selected.add(item.id):selected.delete(item.id));label.prepend(check);line.append(label);
          }
          line.append(button(msg("ui.view_media"),()=>ctx.media(item.id)));group.append(line);
        }
        list.append(group);
      }
      if(!data.items.length)list.append(el('p',view==='trash'?msg("ui.trash_is_empty"):msg("ui.no_duplicate_registrations_with_identical_bytes_were_found"),'empty'));
      if(view==='duplicates'&&writable())root.append(button(msg("ui.preview_selected_trash_impact"),async()=>{
        if(!selected.size)throw new Error('先选择需要回收的重复内容。');
        const requestedIds=[...selected],actionKey=crypto.randomUUID();
        const preview=await ctx.api(`${base()}/recycle-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_ids:requestedIds})});
        if(!alive())return;
        state.revision=preview.revision??state.revision;
        const panel=el('section',null,'desk-recycle-preview');panel.append(el('h2',msg("ui.impact_of_this_trash_operation")));
        for(const item of preview.items||[])panel.append(el('p',joinMessages(["",item.name||msg("ui.selected_media"),"：",item.protected?msg("ui.keep_value0",{value0:(item.reasons||[]).map(r=>r.label).join('；')}):msg("ui.can_move_to_trash"),""])));
        panel.append(button(msg("ui.move_to_recycle_bin"),async b=>{b.disabled=true;try{const {result}=await write('recycle-actions',{media_ids:requestedIds,action:'trash',reason:'用户核对重复内容后回收'},actionKey);if(alive()){await recycle(view);ctx.notice((result.results||result.items||[]).map(r=>({trashed:'已回收',protected:'受保护，已保留',unchanged:'状态未变'})[r.status]||r.status).join('；'));}}finally{b.disabled=false;}}));root.append(panel);
      }));
      const pager=el('div',null,'desk-pagination'),prev=button(msg("common.previous_page"),async()=>{state.offset=Math.max(0,state.offset-24);await recycle(view);}),
        next=button(msg("common.next_page"),async()=>{state.offset+=24;await recycle(view);});
      prev.disabled=state.offset===0;next.disabled=state.offset+data.items.length>=data.total;pager.append(prev,el('span',msg("ui.value0_items",{value0:data.total})),next);root.append(pager);
    }catch(error){if(alive())list.append(el('p',msg("ui.loading_blocked_value0",{value0:error.message})),button(msg("ui.reload"),()=>recycle(view)));}
  }
  return {load,suspend,hasDrafts:()=>[...state.drafts.values()].some(v=>v.body?.trim())};
}
