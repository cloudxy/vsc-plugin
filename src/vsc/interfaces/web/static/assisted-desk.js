import {artifactTitle, renderArtifactContent} from './artifact-reader.js';
import {renderReviewHistory, createArtifactReviewForm} from './review.js';

const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const labels = {review:'待我审阅', progress:'制作进度', results:'已有结果'};
const kindLabels = {artifact:'文案', candidate:'候选', media:'素材', job:'制作任务', preview:'修改预览'};
export function deskLink({page='desk', project='', scope='', object='', version='', bucket='review'}) {
  const params = new URLSearchParams({page, bucket});
  for (const [key,value] of Object.entries({project,scope,object,version})) if(value)params.set(key,value);
  return `?${params}`;
}
export function parseDeskLocation(search) {
  const p = new URLSearchParams(search);
  return {page:['desk','projects','collection','trash'].includes(p.get('page'))?p.get('page'):'desk',
    project:p.get('project')||null, scope:p.get('scope')||null, object:p.get('object')||null,
    version:p.get('version')||null, bucket:labels[p.get('bucket')]?p.get('bucket'):'review'};
}

export function createAssistedDesk(root, ctx) {
  const state = {project:null, scope:null, page:'desk', bucket:'review', offset:0, ticket:0, objectTicket:0,
    revision:0, selected:null, data:null, mobilePanel:'content', drafts:new Map(), selections:new Map()};
  let queue, content, feedback, heading, timer;
  const base = () => `/api/v1/projects/${encodeURIComponent(state.project)}`;
  const button = (label, action, className) => {
    const b=el('button',label,className);b.type='button';
    b.addEventListener('click',async()=>{if(b.disabled)return;try{await action(b);}catch(error){ctx.notice(error.message);}});
    return b;
  };
  const writable = () => !!ctx.session().actor && !!ctx.session().writable;
  const draftKey = () => `${state.project}:${state.selected?.ref.kind}:${state.selected?.ref.id}`;
  const aliveAt = () => {const p=state.project,t=state.ticket,o=state.objectTicket;return()=>p===state.project&&t===state.ticket&&o===state.objectTicket;};
  const updateLink = () => ctx.route?.({page:state.page,project:state.project,scope:state.scope,
    bucket:state.bucket,object:state.selected?`${state.selected.ref.kind}:${state.selected.ref.id}`:'',
    version:state.selected?.ref.version_id||''});
  function pauseMedia() {root.querySelectorAll('video,audio').forEach(node=>node.pause?.());}
  function setMobilePanel(panel){
    state.mobilePanel=panel;root.dataset.mobilePanel=panel;
    for(const b of root.querySelectorAll('.desk-panel-switch'))b.setAttribute('aria-pressed',String(b.dataset.panel===panel));
  }
  function suspend() {state.ticket++;state.objectTicket++;clearTimeout(timer);pauseMedia();}
  function shell(title) {
    pauseMedia();root.replaceChildren();root.className='assisted-desk';
    const bar=el('header',null,'desk-heading');heading=el('h1',title);
    const tools=el('details',null,'desk-tools');tools.append(el('summary','专业工具'));
    const links=el('div',null,'desk-tool-links');
    const entries=state.page==='collection'?[['library','分类资产'],['media','全部素材'],['canvas','关系画布']]:
      [['source','创意与原稿'],['script','剧本编辑'],['designs','场镜设计'],['candidates','候选比较'],['delivery','剪辑交付'],['workbench','场镜关系'],['artifacts','文案版本'],['canvas','关系画布']];
    for(const [view,label] of entries)links.append(button(label,()=>ctx.specialist(view)));
    tools.append(links);bar.append(heading,tools);root.append(bar);
  }
  function scaffold() {
    shell(state.page==='collection'?'素材库':'工作台');
    root.classList.add('desk-with-panes');
    const bar=el('div',null,'desk-scope');
    const project=ctx.projectName?.()||'当前项目';
    bar.append(el('span',project),el('span',state.scope?'当前选择范围':'全部项目内容','hint'));
    if(!ctx.session().writable)bar.append(el('span',ctx.session().writeAvailable===false?'本次服务只读':'此项目只读','badge'));
    else if(!ctx.session().actor)bar.append(button('登录后可提意见',()=>ctx.login()));
    bar.append(button('刷新',()=>load({...current(),refresh:true})));
    if(state.bucket==='progress')bar.append(runtimeControls());
    root.append(bar);
    const mobile=el('nav',null,'desk-mobile-navigation');mobile.setAttribute('aria-label','窄屏工作区切换');
    for(const [panel,label] of [['list','返回列表'],['content','作品'],['feedback','意见与结果']]){
      const b=button(label,()=>setMobilePanel(panel),'desk-panel-switch');b.dataset.panel=panel;mobile.append(b);
    }
    root.append(mobile);setMobilePanel(state.mobilePanel);
    const panes=el('div',null,'desk-panes');
    queue=el('nav',null,'desk-queue');queue.setAttribute('aria-label','待审与结果列表');
    content=el('article',null,'desk-content');content.tabIndex=0;content.setAttribute('aria-label','作品正文与播放');
    feedback=el('aside',null,'desk-feedback');feedback.setAttribute('aria-label','意见与本轮结果');
    const filters=el('div',null,'desk-buckets');filters.setAttribute('aria-label','工作状态');
    for(const [key,label] of Object.entries(state.page==='collection'?{results:'项目素材'}:labels)){
      const b=button(label,async()=>{state.bucket=key;state.offset=0;state.selected=null;await load(current());});
      b.dataset.bucket=key;b.setAttribute('aria-pressed',String(state.bucket===key));filters.append(b);
    }
    queue.append(filters,el('p','正在读取…','empty'));
    content.append(el('p','选择一项，开始阅读或播放。','empty'));
    feedback.append(el('h2','意见与本轮结果'),el('p','意见将固定到所见版本。','hint'));
    panes.append(queue,content,feedback);root.append(panes);
  }
  const current=()=>({projectId:state.project,objectId:state.scope,page:state.page,bucket:state.bucket});
  function runtimeControls(){
    const detail=el('details',null,'desk-runtime'),body=el('div');
    detail.append(el('summary','后台执行状态'),body);
    const ticket=state.ticket;
    const read=async(action=null)=>{
      body.replaceChildren(el('p','正在读取后台状态…','hint'));
      try{
        const value=await ctx.api('/api/v1/execution',action?{method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},
          body:JSON.stringify({action})}:undefined);
        if(ticket!==state.ticket)return;
        body.replaceChildren(el('p',value.message,'hint'),
          el('p',value.generation?.available?'制作执行器可接续任务':'制作执行器未启动','hint'),
          el('p',value.edit_preview?.running?'字幕预览执行器可接续任务':'字幕预览执行器未启动','hint'));
        if(value.enabled&&ctx.session().actor){
          const paused=!value.generation?.accepting_submissions&&!value.edit_preview?.running;
          body.append(button(paused?'继续本次服务的新任务':'暂停本次服务的新任务',()=>read(paused?'resume':'pause')));
          body.append(el('p','对本次服务的全部项目生效；重启后按启动配置恢复。已提交的远端任务继续查询结果。','hint'));
        }
      }catch(error){if(ticket===state.ticket)body.replaceChildren(el('p',error.message),button('重试后台状态',()=>read()));}
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
    state.bucket=options.bucket|| (state.page==='collection'?'results':state.bucket);
    const identity=`${state.project}:${state.scope}:${state.page}:${state.bucket}`;
    if(previous!==identity){state.offset=0;state.selected=null;}
    const ticket=++state.ticket;state.objectTicket++;clearTimeout(timer);
    if(state.page==='projects'||!state.project){state.page='projects';await projects();updateLink();return;}
    if(state.page==='trash'){await recycle(options.recycleView||'trash');updateLink();return;}
    scaffold();
    const alive=()=>ticket===state.ticket;
    root.setAttribute('aria-busy','true');
    try {
      const params=new URLSearchParams({bucket:state.bucket,limit:'24',offset:String(state.offset)});
      if(state.scope)params.set('object_id',state.scope);
      let data;
      if(state.page==='collection'){
        params.delete('bucket');
        const media=await ctx.api(`${base()}/media?${params}`);
        data={...media,ancestors:[],scope:null,counts:{results:media.total},next_offset:state.offset+media.items.length<media.total?state.offset+media.items.length:null,
          items:media.items.map(m=>({id:'media:'+m.id,kind:'media',title:m.name||m.title||'未命名素材',
            status_label:m.deprecated?'已停用':'已登记素材',ref:{kind:'media',id:m.id}}))};
      }else data=await ctx.api(`${base()}/assisted-desk?${params}`);
      if(!alive())return;
      state.data=data;state.revision=data.revision;ctx.revision?.(data.revision);
      renderQueue(data);
      const desired=options.ref || state.selections.get(identity);
      const chosen=(desired&&data.items.find(r=>`${r.ref.kind}:${r.ref.id}`===desired))||data.items[0];
      if(chosen)await select(chosen);
      else if(desired && options.ref){const [kind,...rest]=desired.split(':');if(['artifact','media','job'].includes(kind))await select({title:'固定版本',ref:{kind,id:rest.join(':'),version_id:options.version}});}
      else{
        content.replaceChildren(el('h2',state.bucket==='review'?'没有待审事项':state.bucket==='progress'?'没有正在进行的任务':'还没有结果'));
        content.append(el('p',data.message||'可以从项目里继续查看、编辑原稿与剧本。','hint'),button('打开项目',()=>ctx.navigate('projects')));
      }
      updateLink();
    } catch(error) {
      if(!alive())return;
      queue.replaceChildren(el('p',`读取受阻：${error.message}`,'empty'),button('重新读取',()=>load(current())));
    } finally {if(alive())root.setAttribute('aria-busy','false');}
  }
  function renderQueue(data) {
    const filters=queue.firstElementChild || queue.children[0];queue.replaceChildren(filters);
    const selectedForReview=new Map();
    for(const b of filters.querySelectorAll('button')){const n=data.counts?.[b.dataset.bucket];b.textContent=(state.page==='collection'?'项目素材':labels[b.dataset.bucket])+(n==null?'':` ${n}`);}
    if(data.message)queue.append(el('p',data.message,'hint'));
    for(const row of data.items){
      const link=el('a',null,'desk-item');link.href=deskLink({page:state.page,project:state.project,scope:state.scope,bucket:state.bucket,
        object:`${row.ref.kind}:${row.ref.id}`,version:row.ref.version_id});
      link.dataset.ref=`${row.ref.kind}:${row.ref.id}`;
      const title=row.kind==='artifact'?artifactTitle({artifact_type:row.content_kind,title:row.title}):row.title;
      link.append(el('span',title||'未命名内容','desk-item-title'),el('small',`${kindLabels[row.kind]||'内容'} · ${row.status_label||'可回看'}`));
      link.addEventListener('click',async event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();await select(row);});queue.append(link);
      if(writable()&&row.kind==='artifact'&&row.status==='draft'){
        const label=el('label','纳入本次审阅','desk-review-select'),check=el('input');check.type='checkbox';
        check.addEventListener('change',()=>check.checked?selectedForReview.set(row.id,row):selectedForReview.delete(row.id));
        label.prepend(check);queue.append(label);
      }
    }
    if(!data.items.length)queue.append(el('p','当前没有这一类事项。','empty'));
    const pager=el('div',null,'desk-pagination'),prev=button('上一页',async()=>{state.offset=Math.max(0,state.offset-24);await load(current());}),
      next=button('下一页',async()=>{state.offset=data.next_offset;await load(current());});
    prev.disabled=state.offset===0;next.disabled=data.next_offset==null;
    pager.append(prev,el('span',`${data.total} 项`),next);queue.append(pager);
    if(data.items.some(r=>r.kind==='artifact'&&r.status==='draft')&&writable())
      queue.append(button('审阅本页所选版本',()=>batchReview([...selectedForReview.values()])));
  }
  async function batchReview(rows){
    if(!rows.length)throw new Error('先勾选本页已经呈现的文案版本。');
    state.objectTicket++;const alive=aliveAt();
    setMobilePanel('feedback');
    feedback.replaceChildren(el('h2','本次所选版本'),el('p','只对下列固定版本记录决定。未勾选、其他页与候选用途不在本次范围。','hint'));
    const results=el('div'),ready=[];feedback.append(results);
    for(const row of rows){
      const line=el('p',`${row.title}：正在核对…`);results.append(line);
      try{
        const value=await ctx.api(`${base()}/artifacts/${encodeURIComponent(row.ref.id)}`);
        if(!alive())return;
        if(value.integrity==='mismatch'||value.availability==='missing'||(row.ref.sha256&&row.ref.sha256!==value.sha256))throw new Error('固定内容已变化或缺失，请单独回看');
        if(value.approved)throw new Error('此版本已经批准，本次保留现有决定');
        ready.push({row,value,line,key:crypto.randomUUID()});line.textContent=`${artifactTitle(value)}，第 ${value.version||1} 版：待决定`;
      }catch(error){if(!alive())return;line.textContent=`${row.title}：${error.message}`;}
    }
    const reason=el('textarea');reason.rows=3;reason.name='batch_reason';reason.setAttribute('aria-label','本次版本决定理由');reason.placeholder='写明对所选固定版本的决定理由…';
    let fixedReason=null;
    const approve=button(`批准核对后的 ${ready.length} 个版本`,async b=>{
      if(!reason.value.trim())throw new Error('请填写本次决定理由。');
      fixedReason ||= reason.value;b.disabled=true;reason.disabled=true;
      for(const item of ready){
        if(!alive())return;if(item.done)continue;
        try{
          const {alive:current}=await write('artifact-decisions',{artifact_id:item.row.ref.id,outcome:'approve',reason:fixedReason},item.key);
          item.done=true;if(!current)return;item.line.textContent=`${artifactTitle(item.value)}：已批准此固定版本`;
        }catch(error){if(!alive())return;item.line.textContent=`${artifactTitle(item.value)}：未批准，${error.message}`;}
      }
      if(alive()){b.disabled=ready.every(r=>r.done);b.textContent=b.disabled?'所选版本决定已记录':'重试尚未完成的决定';}
    });
    approve.disabled=!ready.length;feedback.append(reason,approve);
  }
  async function select(row) {
    pauseMedia();state.selected=row;state.objectTicket++;
    setMobilePanel('content');
    const alive=aliveAt(),project=state.project,ref=row.ref;
    state.selections.set(`${state.project}:${state.scope}:${state.page}:${state.bucket}`,`${ref.kind}:${ref.id}`);
    for(const link of queue.querySelectorAll('a')){const selected=link.dataset.ref===`${ref.kind}:${ref.id}`;if(selected)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');}
    updateLink();content.replaceChildren(el('p','正在读取所见内容…','empty'));feedback.replaceChildren();
    try {
      const endpoint=ref.kind==='artifact'?`artifacts/${encodeURIComponent(ref.id)}`:ref.kind==='media'?`media/${encodeURIComponent(ref.id)}`:
        `workbench?section=job_attempts&entity_id=${encodeURIComponent(ref.id)}&limit=1`;
      const value=await ctx.api(`${base()}/${endpoint}`);if(!alive())return;
      const title=ref.kind==='artifact'?artifactTitle(value):value.name||row.title||'制作任务';
      const header=el('header',null,'desk-object-heading');header.append(el('h2',title));
      const context=el('p',null,'hint');
      const path=[...(state.data?.ancestors||[]),state.data?.scope].filter(Boolean).map(r=>r.title||r.display_code).join(' / ');
      context.textContent=`${ctx.projectName?.()||'当前项目'}${path?' / '+path:''}${value.version!=null?' / 第 '+value.version+' 版':''}`;
      header.append(context);
      content.replaceChildren(header);content.scrollTop=0;
      if(row.blocked_reason)content.append(el('p',row.blocked_reason,'desk-blocked'));
      if(ref.kind==='artifact'){
        const fixed=value.content!==undefined?value.content:value.document;
        if(fixed==null)content.append(el('p','正文暂不可读，请在版本与核验中检查来源。','empty'));
        else {
          const rendered=renderArtifactContent(fixed,{mimeType:value.mime_type});
          content.append(rendered.body);
          if(rendered.mediaKind)content.append(button('打开已有结果',async()=>{
            state.bucket='results';state.offset=0;state.selected=null;await load(current());
          }));
        }
        if(value.integrity==='mismatch')content.prepend(el('p','所见文件摘要变化，当前仅供核对。','desk-blocked'));
      }else if(ref.kind==='media'){
        const node=await ctx.player(value);if(!alive())return;content.append(node);
        content.append(button('用途、来源与候选决定',()=>ctx.media(ref.id)));
      }else{
        const job=value.sections?.job_attempts?.items?.[0];
        content.append(el('p',row.status_label||'任务状态以执行回执为准'));
        for(const output of job?.outputs||[])content.append(button('查看本次结果',()=>select({title:'制作结果',ref:{kind:'media',id:output.media_id}})));
        const details=el('details');details.append(el('summary','执行记录'),el('pre',JSON.stringify(job||{},null,2),'structured'));content.append(details);
      }
      const evidence=el('details',null,'desk-evidence');evidence.append(el('summary','版本与核验'),el('p',`${ref.id}${value.sha256?' · '+value.sha256:''}`,'hint'));content.append(evidence);
      await renderFeedback(value,ref,alive);
      if(!alive())return;
      if(ref.kind==='artifact'&&ctx.session().writable)content.append(button('审阅此固定版本',()=>ctx.artifact(ref.id)));
      if(ref.kind==='job')feedback.append(el('p','这里显示已登记任务与执行回执。等待执行不表示执行器已启动。','hint'));
      if(project!==state.project)return;
    }catch(error){
      if(!alive())return;content.replaceChildren(el('p',`内容读取受阻：${error.message}`,'empty'),button('重试当前内容',()=>select(row)));
    }
  }
  async function renderFeedback(value,ref,alive) {
    feedback.replaceChildren(el('h2','意见与本轮结果'));
    const reloadHistory=async()=>{
      if(!alive())return;
      const data=await ctx.api(`${base()}/review-history?${ref.kind==='media'?'media_id':'artifact_id'}=${encodeURIComponent(ref.id)}`);
      if(alive())history.replaceChildren(renderReviewHistory(data,reviewCtx));
    };
    const reviewCtx={heading:false,artifact:id=>select({title:'修改结果',ref:{kind:'artifact',id,version_id:id}}),
      media:id=>select({title:'修改结果',ref:{kind:'media',id}}),
      ...(writable()?{retryPreview:async(preview,item,key)=>{
        if(!alive())return;
        await write(`edit-previews/${encodeURIComponent(preview.id)}/retry`,{},key);
        if(!alive())return;await reloadHistory();
        const status=el('p','正在恢复这次预览…','hint');status.setAttribute('role','status');feedback.append(status);
        pollPreview(item.source.artifact_note_id,alive,status);
      }}:{}),
      local:(action,row)=>ctx.local(action,{...row,onReviewProposed:async()=>{if(alive())await reloadHistory();}}),onError:error=>ctx.notice(error.message)};
    const history=el('div',null,'desk-history');
    if(!writable())feedback.append(el('p',ctx.session().writable?'登录后可以记录意见；当前可以阅读。':'此项目只读，可查看已有意见和结果。','hint'));
    if(writable() && value.review_targets?.length){
      let capability;
      try{capability=await ctx.api(`${base()}/edit-preview-capability?${ref.kind==='media'?'media_id':'artifact_id'}=${encodeURIComponent(ref.id)}`);}
      catch(error){capability={available:false,reason:`局部预览暂不可用：${error.message}`};}
      if(!alive())return;
      if(capability.available)feedback.append(editForm(capability,alive,reloadHistory));
      else{
        const key=draftKey(),saved=state.drafts.get(key);
        const form=createArtifactReviewForm(value.review_targets,{currentTime:()=>content.querySelector('video')?.currentTime||0,
          save:async(payload,idempotency)=>{if(!alive())throw new Error('所见对象已切换，请返回原对象继续。');const result=await write('artifact-review-notes',payload,idempotency);if(result.alive){if(state.drafts.get(key)?.body===payload.body){state.drafts.delete(key);form.querySelector('textarea').value='';}await reloadHistory();}}});
        const input=form.querySelector('textarea'),target=form.querySelector('select'),ranges=form.querySelectorAll('input');
        if(saved){input.value=saved.body;if(saved.target!=null)target.value=saved.target;for(const [index,range]of ranges.entries())if(saved.ranges?.[index]!=null)range.value=saved.ranges[index];}
        const remember=()=>{if(input.value.trim())state.drafts.set(key,{body:input.value,target:target.value,ranges:[...ranges].map(r=>r.value)});else state.drafts.delete(key);};
        input.addEventListener('input',remember);target.addEventListener('change',remember);for(const range of ranges)range.addEventListener('input',remember);
        feedback.append(form);
        if(capability.reason)feedback.append(el('p',capability.reason,'hint'));
      }
    }
    history.append(renderReviewHistory(value.review_history,reviewCtx));feedback.append(history);
  }
  function editForm(capability,alive,reloadHistory) {
    const form=el('form',null,'desk-opinion review-form'),key=draftKey(),saved=state.drafts.get(key)||{};
    const cue=el('select'),label=el('label','修改哪条字幕'),body=el('textarea'),status=el('p',null,'hint');
    cue.name='caption';cue.setAttribute('aria-label','选择字幕');label.append(cue);
    for(const c of capability.cues){const option=el('option',c.text||'空字幕');option.value=c.id;cue.append(option);}
    if(saved.caption_id)cue.value=saved.caption_id;
    body.name='opinion';body.rows=4;body.maxLength=4000;body.required=true;body.value=saved.body||'';
    body.placeholder='例如：把这条字幕向上移动…';body.setAttribute('aria-label','修改意见');
    const record=el('button','记录意见'),submit=el('button','修改后给我看','primary');record.type=submit.type='submit';record.value='record';submit.value='modify';
    status.setAttribute('role','status');
    form.append(label,body,el('p','只调整所选字幕的位置，保留视频与声音；新预览回来后再决定采用。','hint'),record,submit,status);
    let operationKey=saved.key||null,lastAction=saved.action||null;
    const remember=()=>{operationKey=null;state.drafts.set(key,{body:body.value,caption_id:cue.value});};
    body.addEventListener('input',remember);cue.addEventListener('change',remember);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(submit.disabled||!alive())return;
      const caption=capability.cues.find(c=>c.id===cue.value);if(!caption){status.textContent='请重新选择字幕。';return;}
      const target={...capability.target,start_frame:caption.start_frame,end_frame:caption.end_frame};
      const action=event.submitter?.value==='record'?'artifact-review-notes':'edit-preview-requests';
      if(lastAction!==action)operationKey=null;lastAction=action;
      operationKey ||= crypto.randomUUID();const submittedBody=body.value,submittedKey=operationKey;
      state.drafts.set(key,{body:submittedBody,caption_id:cue.value,key:operationKey,action});
      record.disabled=submit.disabled=true;status.textContent='正在保存意见…';
      try{
        const {result,alive:stillHere}=await write(action,action==='artifact-review-notes'?{...target,body:body.value}:{target,body:body.value,caption_id:caption.id},operationKey);
        const unchanged=state.drafts.get(key)?.key===submittedKey&&state.drafts.get(key)?.body===submittedBody;
        if(unchanged)state.drafts.delete(key);
        if(!stillHere)return;if(unchanged){body.value='';operationKey=null;}status.textContent=result.explanation||'原意见已保存。';
        await reloadHistory();
        if(result.note_id)pollPreview(result.note_id,alive,status);
      }catch(error){if(alive())status.textContent=`${error.message}；原意见仍保留在输入框。`;}
      finally{if(alive())record.disabled=submit.disabled=false;}
    });
    return form;
  }
  async function pollPreview(note,alive,status) {
    clearTimeout(timer);
    if(!alive())return;
    try{
      const value=await ctx.api(`${base()}/edit-previews?artifact_note_id=${encodeURIComponent(note)}`);
      if(!alive())return;const job=value.items?.at(-1);
      if(job?.output?.content_url){
        const panel=el('section',null,'desk-preview'),video=el('video',null,'media-player');video.controls=true;video.preload='metadata';video.src=job.output.content_url;
        panel.append(el('h3','新预览，请回看'),video,el('p','这是局部草稿预览。正式采用仍需审阅固定版本。','hint'));
        feedback.append(panel);status.textContent='新预览已返回。';return;
      }
      status.textContent=job?.error||job?.explanation||'已登记，等待执行器处理。';
      if(job && ['failed','blocked','cancelled','stale'].includes(job.status))return;
      timer=setTimeout(()=>pollPreview(note,alive,status),2500);
    }catch(error){if(alive()){status.textContent=`读取进度受阻：${error.message}`;feedback.append(button('重新读取进度',()=>pollPreview(note,alive,status)));}}
  }
  async function projects() {
    shell('项目');
    const list=el('div',null,'desk-projects');root.append(list);
    for(const project of ctx.projects()){
      const card=el('article',null,'desk-project');
      card.append(el('h2',project.name),el('p',ctx.session().writeAvailable===false?'可回看已有内容':project.read_only?'只读项目':'可继续创作','hint'),
        button('打开工作台',()=>ctx.chooseProject(project.id,'desk')),
        button('创意与原稿',async()=>{await ctx.chooseProject(project.id,'projects');await ctx.specialist('source');}));
      list.append(card);
    }
    if(!ctx.projects().length)list.append(el('p',ctx.session().writeAvailable===false?'还没有可浏览的项目。':'还没有项目。先建立一个项目，再加入创意或原稿。','empty'));
    if(ctx.session().writeAvailable===false){root.append(el('p','本次服务只读，可查看已有作品。','hint'));return;}
    const form=el('form',null,'desk-create'),name=el('input'),label=el('label','新项目名称'),submit=el('button','建立项目'),status=el('p');
    name.name='project_name';name.required=true;name.maxLength=120;name.autocomplete='off';label.append(name);
    submit.type='submit';status.setAttribute('role','status');form.append(label,submit,status);root.append(form);
    if(!ctx.session().actor){submit.disabled=true;form.append(button('先登录',()=>ctx.login()));}
    let createKey=null;name.addEventListener('input',()=>{createKey=null;});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(submit.disabled)return;submit.disabled=true;createKey ||= crypto.randomUUID();
      try{const result=await ctx.api('/api/v1/projects',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},
        body:JSON.stringify({payload:{name:name.value,profile:'vsc.series-pg'},idempotency_key:createKey})});await ctx.created(result.id);}
      catch(error){status.textContent=error.message;}finally{submit.disabled=false;}
    });
  }
  async function recycle(view) {
    state.ticket++;state.objectTicket++;clearTimeout(timer);
    shell(view==='duplicates'?'整理重复内容':'回收站');
    root.append(el('p','回收可恢复，保留原始文件与历史记录。释放磁盘空间：0 字节。','hint'),
      button(view==='duplicates'?'查看回收站':'整理重复内容',()=>recycle(view==='duplicates'?'trash':'duplicates')));
    const list=el('div',null,'desk-recycle-list');root.append(list);
    const ticket=state.ticket,alive=()=>ticket===state.ticket;
    try{
      const data=await ctx.api(`${base()}/recycle?view=${view}&limit=24&offset=${state.offset}`);
      if(!alive())return;state.revision=data.revision;
      const selected=new Set();
      for(const row of data.items){
        const group=el('article',null,'desk-recycle-item');
        for(const item of view==='duplicates'?row.items:[row]){
          const line=el('div',null,'desk-recycle-row');line.append(el('strong',item.name||'未命名素材'));
          if(item.recycled)line.append(el('span','已在回收站','hint'));
          if(item.reasons?.length)line.append(el('p',item.reasons.map(r=>r.label).join('；'),'hint'));
          if(view==='trash'&&writable())line.append(button('恢复',async b=>{b.disabled=true;try{await write('recycle-actions',{media_ids:[item.id],action:'restore',reason:'用户在回收站恢复'},crypto.randomUUID());if(alive())await recycle(view);}finally{b.disabled=false;}}));
          else if(writable()){
            const label=el('label','选择回收'),check=el('input');check.type='checkbox';check.disabled=!!item.protected||!!item.recycled;
            check.addEventListener('change',()=>check.checked?selected.add(item.id):selected.delete(item.id));label.prepend(check);line.append(label);
          }
          line.append(button('查看素材',()=>ctx.media(item.id)));group.append(line);
        }
        list.append(group);
      }
      if(!data.items.length)list.append(el('p',view==='trash'?'回收站是空的。':'没有找到同字节的重复登记。','empty'));
      if(view==='duplicates'&&writable())root.append(button('预览所选回收影响',async()=>{
        if(!selected.size)throw new Error('先选择需要回收的重复内容。');
        const requestedIds=[...selected],actionKey=crypto.randomUUID();
        const preview=await ctx.api(`${base()}/recycle-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_ids:requestedIds})});
        if(!alive())return;
        state.revision=preview.revision??state.revision;
        const panel=el('section',null,'desk-recycle-preview');panel.append(el('h2','本次回收影响'));
        for(const item of preview.items||[])panel.append(el('p',`${item.name||'所选素材'}：${item.protected?'保留（'+(item.reasons||[]).map(r=>r.label).join('；')+'）':'可回收'}`));
        panel.append(button('移入回收站',async b=>{b.disabled=true;try{const {result}=await write('recycle-actions',{media_ids:requestedIds,action:'trash',reason:'用户核对重复内容后回收'},actionKey);if(alive()){await recycle(view);ctx.notice((result.results||result.items||[]).map(r=>({trashed:'已回收',protected:'受保护，已保留',unchanged:'状态未变'})[r.status]||r.status).join('；'));}}finally{b.disabled=false;}}));root.append(panel);
      }));
      const pager=el('div',null,'desk-pagination'),prev=button('上一页',async()=>{state.offset=Math.max(0,state.offset-24);await recycle(view);}),
        next=button('下一页',async()=>{state.offset+=24;await recycle(view);});
      prev.disabled=state.offset===0;next.disabled=state.offset+data.items.length>=data.total;pager.append(prev,el('span',`${data.total} 项`),next);root.append(pager);
    }catch(error){if(alive())list.append(el('p',`读取受阻：${error.message}`),button('重新读取',()=>recycle(view)));}
  }
  return {load,suspend,hasDrafts:()=>[...state.drafts.values()].some(v=>v.body?.trim())};
}
