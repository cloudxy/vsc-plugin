import {createMediaUpload} from './media-upload.js';
import {createRunScopeControls} from './run-scope-controls.js';

// One explicit intent prepares a canvas and starts its original Agent turn.
// Recovery follows the fixed prepare/start receipts and never sends a new turn.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const option=(value,title)=>{const n=el('option',title);n.value=value;return n;};
const copy=value=>JSON.parse(JSON.stringify(value));
const endpoint=(p,path)=>`/api/v1/projects/${encodeURIComponent(p)}/${path}`;
const genericHint='上传创作素材或引用项目素材，描述你想创作的广告内容、核心卖点或创意想法…';
const length=value=>Array.from(value).length;
export async function marketingStartKey(prepareKey){return 'marketing-start:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(prepareKey))),n=>n.toString(16).padStart(2,'0')).join('');}

export function createMarketingStudio(root,ctx){
  let state=null,sequence=0;
  const memory=new Map();
  const auth=()=>ctx.session();
  const key=(kind,actor,project='')=>'vsc-marketing:'+kind+':'+JSON.stringify([actor,project]);
  const recall=name=>{try{return JSON.parse(sessionStorage.getItem(name)||'null')??memory.get(name);}catch{return memory.get(name);}};
  const remember=(name,value)=>{if(value==null)memory.delete(name);else memory.set(name,copy(value));try{if(value==null)sessionStorage.removeItem(name);else sessionStorage.setItem(name,JSON.stringify(value));}catch{}};
  const live=s=>state===s&&!s.disposed&&(auth().actor||'')===s.actor;
  const project=s=>ctx.projects().find(p=>p.id===s.project);
  const writable=s=>Boolean(live(s)&&s.actor&&auth().writeAvailable&&project(s)?.storage_policy==='postgres-series-v1'&&!project(s)?.read_only&&!project(s)?.unavailable);
  const draftKey=s=>key('draft',s.actor,s.project),requestKey=s=>key('request',s.actor,s.project);
  function save(s){if(live(s))remember(draftKey(s),s.draft);}
  function revision(s,value){if(live(s)&&value!=null){s.revision=value;ctx.setRevision(value,s.project);}}
  function note(s,text){if(live(s)&&s.status)s.status.textContent=text;}
  function button(s,title,fn,cls=''){
    const n=el('button',title,cls);n.type='button';
    n.onclick=async()=>{if(!live(s))return;try{await fn();}catch(error){if(live(s))note(s,error.message);}};
    return n;
  }
  function labelled(title,input){const label=el('label');input.setAttribute('aria-label',title);label.append(el('span',title,'marketing-sr-only'),input);return label;}
  function update(s){
    if(!live(s))return;
    const locked=Boolean(s.pending||s.busy),validPrompt=Boolean(s.draft.prompt.trim())&&length(s.draft.prompt)<=2000;
    for(const n of s.editables||[])n.disabled=locked||!s.options;
    if(s.runFieldset)s.runFieldset.disabled=locked||!s.options;
    s.prompt.disabled=locked;
    s.projectSelect.disabled=s.busy; // A pending receipt may be left and restored in its own project.
    s.submit.disabled=s.busy||!s.options||!writable(s)||(!s.pending&&!validPrompt);
    s.submit.textContent=s.busy?'正在开始…':s.pending?(s.pending.startResult?'继续原规划':s.pending.result?'继续开始创作':'恢复上次创作'):'开始创作';
    if(s.newCreation){s.newCreation.hidden=!s.pending?.result;s.newCreation.disabled=s.busy;}
    s.counter.textContent=`${length(s.draft.prompt)} / 2000`;
    s.counter.className='marketing-count'+(length(s.draft.prompt)>2000?' marketing-invalid':'');
    s.prompt.setAttribute('aria-invalid',String(length(s.draft.prompt)>2000));
    for(const [id,b]of s.methodButtons)b.setAttribute('aria-pressed',String(s.draft.method_id===id));
    const selected=s.options?.methods?.find(m=>m.id===s.draft.method_id);
    s.prompt.placeholder=selected?.input_hint||genericHint;
    s.methodSummary.textContent=selected?selected.description||selected.name:'';
    s.materials.replaceChildren();
    for(const item of s.draft.media){
      const chip=el('span',null,'marketing-material-chip');chip.append(el('span',item.name||item.id));
      const remove=button(s,'×',()=>{s.draft.media=s.draft.media.filter(m=>m.id!==item.id);save(s);update(s);});remove.disabled=locked;remove.setAttribute('aria-label','移除素材 '+(item.name||item.id));chip.append(remove);s.materials.append(chip);
    }
    s.mediaCount.textContent=`已选 ${s.draft.media.length} / 15`;
    if(s.modelOrder)s.modelOrder.textContent=s.draft.model_ids.map((id,i)=>`${i+1}. ${s.options?.models?.find(m=>m.id===id)?.model_key||id}`).join(' → ')||'由 Agent 先确认需求';
    if(s.autoLimits)s.autoLimits.hidden=s.draft.mode!=='auto_media';
    if(s.autoMediaCheck){s.autoMediaCheck.checked=s.draft.mode==='auto_media';s.autoMediaCheck.disabled=locked||s.draft.mode==='manual';}
    if(s.runFieldset)s.runFieldset.hidden=Boolean(s.pending)||s.draft.mode==='manual';
    if(s.frozenIntent){const intent=s.pending?.intent;s.frozenIntent.hidden=!intent;if(intent){const settings=intent.execution_settings,limits=settings.auto_media,policy=settings.execution_policy,authorization=policy?.authorization;s.frozenIntent.textContent=['本次固定范围：'+(limits?'有界自动媒体':intent.mode==='manual'?'手动规划':'自动编排'),s.modelOrder.textContent,limits?`最多${limits.max_jobs}个任务、${limits.max_images}张图片、${limits.max_video_ms/1000}秒视频；商业额度上限${limits.max_credits}`:'',policy?'停止新增任务：'+policy.stop_submitting_at:'',authorization?.mode==='new_batch'?'新批次原因：'+authorization.reason:authorization?.mode==='continue'?'继续原批次：'+authorization.run_version_id:''].filter(Boolean).join('；');}}
  }
  function draw(s){
    if(!live(s))return;
    s.upload?.suspend();s.upload=null;
    s.runScope?.dispose();s.runScope=null;
    root.replaceChildren();root.classList.add('marketing-studio');
    const heading=el('header',null,'marketing-heading');heading.append(el('h1','和营销 Agent 聊创意，助你轻松打造好广告'));root.append(heading);
    s.editables=[];s.methodButtons=new Map();
    const methods=el('nav',null,'marketing-methods');methods.setAttribute('aria-label','营销热门技能');
    for(const item of [{id:'',name:'全部'},...(s.options?.methods||[])]){
      const b=button(s,item.name,()=>{s.draft.method_id=s.draft.method_id===item.id?'':item.id;save(s);update(s);},'marketing-method');b.dataset.methodId=item.id;
      if(item.description)b.title=item.description;methods.append(b);s.methodButtons.set(item.id,b);s.editables.push(b);
    }
    const form=el('form',null,'marketing-composer'),body=el('div',null,'marketing-input-row');
    const add=button(s,'',()=>{s.materialPanel.hidden=!s.materialPanel.hidden;},'marketing-add');add.append(el('span','+','marketing-add-icon'),el('span','添加创作素材'),el('small','商品/参考图片、视频等'));s.editables.push(add);
    s.prompt=el('textarea',null,'marketing-prompt');s.prompt.value=s.draft.prompt;s.prompt.rows=4;s.prompt.setAttribute('aria-label','广告创作需求');
    s.prompt.oninput=()=>{if(!live(s)||s.pending)return;s.draft.prompt=s.prompt.value;save(s);update(s);};
    s.prompt.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();submit(s);}};
    s.editables.push(s.prompt);body.append(add,s.prompt);form.append(body);
    s.materials=el('div',null,'marketing-materials');form.append(s.materials);
    const footer=el('div',null,'marketing-toolbar'),tools=el('div',null,'marketing-tools');
    const ref=button(s,'@',()=>{s.materialPanel.hidden=!s.materialPanel.hidden;},'marketing-icon');ref.title='引用素材';ref.setAttribute('aria-label','引用素材');
    const models=button(s,'◇',()=>{s.executionPanel.hidden=!s.executionPanel.hidden;},'marketing-icon');models.title='选择模型';models.setAttribute('aria-label','选择模型');tools.append(ref,models);s.editables.push(ref,models);
    const mode=el('select',null,'marketing-mode');mode.setAttribute('aria-label','创作模式');mode.append(option('manual','手动模式'),option('auto_drafts','自动模式'));mode.value=s.draft.mode==='manual'?'manual':'auto_drafts';mode.onchange=()=>{if(!live(s)||s.pending)return;s.draft.mode=mode.value;save(s);update(s);if(mode.value!=='manual')s.executionPanel.hidden=false;};tools.append(mode);s.editables.push(mode);
    s.counter=el('small',null,'marketing-count');tools.append(s.counter);
    const scope=el('div',null,'marketing-scope');s.projectSelect=el('select');s.projectSelect.append(option('','请选择归属项目'));
    for(const p of ctx.projects())s.projectSelect.append(option(p.id,p.name+(p.read_only?' · 只读':'')));
    s.projectSelect.value=s.project||'';s.projectSelect.onchange=()=>{if(live(s)){save(s);return load({project:s.projectSelect.value,...(!s.project?{seed:s.draft}:{})});}};
    s.episodeSelect=el('select');s.episodeSelect.append(option('','不指定剧集'));
    for(const e of s.options?.episodes||[])s.episodeSelect.append(option(e.id,e.title||e.display_code||e.name||e.id));
    s.episodeSelect.value=s.draft.episode_id||'';s.episodeSelect.onchange=()=>{if(live(s)&&!s.pending){s.draft.episode_id=s.episodeSelect.value;save(s);}};s.editables.push(s.episodeSelect);
    s.submit=el('button','开始创作','marketing-submit');s.submit.type='submit';scope.append(labelled('归属项目',s.projectSelect),labelled('归属剧集',s.episodeSelect),s.submit);footer.append(tools,scope);form.append(footer);
    form.onsubmit=e=>{e.preventDefault();return submit(s);};root.append(form);
    s.methodSummary=el('p',null,'marketing-method-summary');root.append(s.methodSummary);
    executionControls(s);
    s.status=el('p',null,'marketing-status');s.status.setAttribute('role','status');root.append(s.status);
    const explanation=el('p','开始后进入画布，查看 Agent 的补问或创作计划。手动模式先规划；自动媒体须填写本轮模型、额度和截止时间。','marketing-continuation');root.append(explanation);
    s.newCreation=button(s,'开始新创作',()=>{if(s.busy||!s.pending?.result)return;s.pending=null;remember(requestKey(s),null);save(s);draw(s);note(s,'可以修改需求并开始一次新的创作。');});root.append(s.newCreation);
    const methodsHeading=el('div',null,'marketing-methods-heading');methodsHeading.append(el('p','引用热门技能，让 Agent 按专业方法创作'),methods.firstElementChild);root.append(methodsHeading,methods);
    s.materialPanel=el('section',null,'marketing-material-panel');s.materialPanel.hidden=true;s.materialPanel.setAttribute('aria-label','创作素材');
    const materialHeading=el('div',null,'marketing-material-heading');s.mediaCount=el('span');materialHeading.append(el('h2','创作素材'),s.mediaCount,button(s,'收起',()=>{s.materialPanel.hidden=true;}));s.materialPanel.append(materialHeading);
    if(s.project&&s.options){
      const tabs=el('div',null,'marketing-material-tabs');s.mediaType='image';s.mediaOffset=0;s.mediaQuery='';
      for(const [type,title]of [['image','项目图片'],['video','项目视频']])tabs.append(button(s,title,()=>{s.mediaType=type;s.mediaOffset=0;return readMedia(s);}));
      const query=el('input');query.type='search';query.placeholder='搜索项目素材';query.setAttribute('aria-label','搜索项目素材');tabs.append(query,button(s,'搜索',()=>{s.mediaQuery=query.value.trim();s.mediaOffset=0;return readMedia(s);}));s.materialPanel.append(tabs);
      s.mediaList=el('div',null,'marketing-media-grid');s.mediaPager=el('div',null,'marketing-media-pager');s.materialPanel.append(s.mediaList,s.mediaPager);
      const uploadDetails=el('details',null,'marketing-upload'),uploadRoot=el('div');uploadDetails.append(el('summary','上传本机图片或视频'),uploadRoot);s.materialPanel.append(uploadDetails);
      // Read the original import manifests only when requested; callbacks remain
      // bound to this actor and project even when the host switches elsewhere.
      uploadDetails.ontoggle=async()=>{
        if(!uploadDetails.open||s.upload||!live(s))return;
        const upload=createMediaUpload({root:uploadRoot,project:s.project,episodeId:s.draft.episode_id||null,title:'上传营销素材',accept:'image/*,video/*',
          session:()=>({...auth(),writable:writable(s)&&!s.pending&&!s.busy}),
          api:async(...args)=>{if(!live(s))throw Error('页面范围已切换');const r=await ctx.api(...args);if(!live(s)){upload.suspend();throw Error('页面范围已切换');}return r;},
          onRevision:v=>revision(s,v),onComplete:async({mediaId,item})=>{
            if(!live(s)||s.pending||s.busy)return;
            const media=await ctx.api(endpoint(s.project,'media/'+encodeURIComponent(mediaId)));if(!live(s))return;
            if(!['image','video'].includes(media.modality))throw Error('营销素材只支持图片或视频');
            addMedia(s,{id:mediaId,name:media.name||item.filename,modality:media.modality});
          }});s.upload=upload;
        try{await upload.load();if(!live(s))upload.suspend();}catch(error){if(live(s))note(s,error.message);}
      };
      readMedia(s);
    }else s.materialPanel.append(el('p','先选择项目，再引用素材或上传文件。'));
    root.append(s.materialPanel);
    const ideas=el('section',null,'marketing-ideas');ideas.append(el('h2','全部创意'),el('p','创意案例暂未接入。可直接描述创意，或选择上方技能继续。','marketing-ideas-empty'));root.append(ideas);
    if(!ctx.projects().length)root.append(button(s,'查看或新建项目',()=>ctx.navigate('projects',null,null)));
    update(s);
    if(s.error)note(s,s.error);
    else if(s.pending)note(s,s.pending.startResult?'原规划已建立；继续只查询并打开同一规划。':s.pending.result?'准备画布已保留；继续将沿原请求开始创作。':'上次操作回执待确认。需求与素材已保留，恢复时使用原请求。');
    else if(s.project&&!writable(s))note(s,'当前项目不可写，请选择可写项目或建立操作会话。');
  }
  function executionControls(s){
    const panel=el('section',null,'marketing-execution-panel');panel.hidden=true;s.executionPanel=panel;panel.setAttribute('aria-label','模型与创作范围');
    panel.append(el('h2','选择模型'),el('p','最多8个，按选择顺序使用；不选模型也可先让 Agent 补问。'));
    const models=el('div',null,'marketing-models');for(const [modality,title]of [['image','图片'],['video','视频']]){const group=el('div',null,'marketing-model-group');group.append(el('h3',title));for(const model of (s.options?.models||[]).filter(m=>m.enabled&&m.modality===modality)){
      const check=el('input');check.type='checkbox';check.checked=s.draft.model_ids.includes(model.id);check.setAttribute('aria-label','优先模型 '+(model.model_key||model.id));s.editables.push(check);
      check.onchange=()=>{if(!live(s)||s.pending)return;if(check.checked&&!s.draft.model_ids.includes(model.id)){if(s.draft.model_ids.length>=8){check.checked=false;note(s,'最多选择8个模型');return;}s.draft.model_ids.push(model.id);}else if(!check.checked)s.draft.model_ids=s.draft.model_ids.filter(id=>id!==model.id);save(s);update(s);};
      const label=el('label');label.append(check,el('span',model.model_key||model.id));group.append(label);
    }models.append(group);}panel.append(models);s.modelOrder=el('p',null,'marketing-model-order');s.frozenIntent=el('p',null,'marketing-frozen-intent');panel.append(s.modelOrder,s.frozenIntent);
    const fields=el('fieldset');s.runFieldset=fields;fields.append(el('legend','本轮执行范围'));
    const field=(title,name,type='number',parent=fields)=>{const control=el('input');control.type=type;control.value=s.draft.execution[name];control.setAttribute('aria-label',title);if(type==='number'){control.min='0';control.step='1';}control.oninput=()=>{if(live(s)&&!s.pending){s.draft.execution[name]=control.value;save(s);}};const label=el('label');label.append(el('span',title),control);parent.append(label);return control;};
    field('视频时长（秒）','duration');field('首版目标时间','first_due','datetime-local');field('停止新增任务时间','stop_at','datetime-local');
    const scopeRoot=el('div',null,'marketing-run-scope');fields.append(scopeRoot);
    if(s.project&&s.options)s.runScope=createRunScopeControls(scopeRoot,{projectId:s.project,session:ctx.session,api:ctx.api});
    const automatic=el('label',null,'marketing-auto-media');s.autoMediaCheck=el('input');s.autoMediaCheck.type='checkbox';s.autoMediaCheck.setAttribute('aria-label','自动生成图片和视频（有界）');s.autoMediaCheck.onchange=()=>{if(!live(s)||s.pending||s.draft.mode==='manual')return;s.draft.mode=s.autoMediaCheck.checked?'auto_media':'auto_drafts';save(s);update(s);};automatic.append(s.autoMediaCheck,el('span','自动生成图片和视频（按本轮模型、额度和截止时间）'));fields.append(el('p','自动模式默认只编排文字与节点；生成媒体须明确下列范围。'),automatic);
    s.autoLimits=el('div',null,'marketing-auto-limits');
    field('本轮最多任务','max_jobs','number',s.autoLimits);field('本轮最多图片','max_images','number',s.autoLimits);field('本轮视频总秒数','max_video_seconds','number',s.autoLimits);field('本轮商业额度上限','max_credits','number',s.autoLimits);fields.append(s.autoLimits);
    panel.append(fields,button(s,'收起设置',()=>panel.hidden=true));root.append(panel);
  }
  function freezeIntent(s){
    const e=s.draft.execution,integer=(value,title,min=0)=>{const n=Number(value);if(value===''||!Number.isSafeInteger(n)||n<min)throw Error(title+'须填写有效整数');return n;};
    if(!['manual','auto_drafts','auto_media'].includes(s.draft.mode))throw Error('请选择有效的创作模式');
    const ids=[...s.draft.model_ids];if(ids.length>8||new Set(ids).size!==ids.length)throw Error('最多选择8个不重复模型');
    if(s.draft.mode==='manual')return {model_ids:ids,mode:'manual',execution_settings:{}};
    const first=new Date(e.first_due),stop=new Date(e.stop_at);if(!Number.isFinite(first.getTime())||!Number.isFinite(stop.getTime())||stop<=new Date()||first>stop)throw Error('请填写有效的首版目标和停止时间');
    const settings=s.runScope?.apply({duration_ms:integer(e.duration,'视频时长',1)*1000,execution_policy:{version:'bounded-v1',first_draft_due_at:first.toISOString(),stop_submitting_at:stop.toISOString(),max_attempts_per_purpose:1,max_repair_rounds:0}})||{};
    if(s.draft.mode==='auto_media'){
      if(!ids.length)throw Error('自动媒体须先选择本轮模型');
      settings.auto_media={max_jobs:integer(e.max_jobs,'任务上限',1),max_images:integer(e.max_images,'图片上限'),max_video_ms:integer(e.max_video_seconds,'视频秒数上限')*1000,max_credits:integer(e.max_credits,'商业额度上限'),stop_submitting_at:stop.toISOString()};
    }
    return {model_ids:ids,mode:s.draft.mode==='manual'?'manual':'auto_drafts',execution_settings:settings};
  }
  function addMedia(s,item){
    if(!live(s)||s.pending||s.busy)return;
    if(s.draft.media.some(m=>m.id===item.id))return;
    if(s.draft.media.length>=15)throw Error('最多选择15项图片或视频素材');
    s.draft.media.push({id:item.id,name:item.name||item.id,modality:item.modality});save(s);update(s);note(s,'已添加素材：'+(item.name||item.id));
  }
  async function readMedia(s){
    if(!live(s)||!s.mediaList)return;const token=++s.mediaSequence;
    const params=new URLSearchParams({modality:s.mediaType,offset:String(s.mediaOffset),limit:'24',query:s.mediaQuery});
    s.mediaList.replaceChildren(el('p','正在读取项目素材…'));s.mediaPager.replaceChildren();
    try{
      const data=await ctx.api(endpoint(s.project,'media?'+params));if(!live(s)||token!==s.mediaSequence)return;
      s.mediaList.replaceChildren();for(const item of data.items||[]){
        if(!['image','video'].includes(item.modality))continue;
        const card=el('article',null,'marketing-media-card'),preview=el(item.modality==='image'?'img':'video');preview.src=endpoint(s.project,'media/'+encodeURIComponent(item.id)+'/content');
        if(item.modality==='image'){preview.alt=item.name||'';preview.loading='lazy';}else{preview.controls=true;preview.preload='metadata';}
        card.append(preview,el('p',item.name||item.id),button(s,'引用素材',()=>addMedia(s,item)));s.mediaList.append(card);
      }
      if(!s.mediaList.children.length)s.mediaList.append(el('p','暂无可引用的'+(s.mediaType==='image'?'图片':'视频')));
      const next=data.next_offset??(data.total>s.mediaOffset+24?s.mediaOffset+24:null);
      if(s.mediaOffset||next!=null){const prev=button(s,'上一页',()=>{s.mediaOffset=Math.max(0,s.mediaOffset-24);return readMedia(s);});prev.disabled=s.mediaOffset===0;const more=button(s,'下一页',()=>{s.mediaOffset=next;return readMedia(s);});more.disabled=next==null;s.mediaPager.append(prev,more);}
    }catch(error){if(live(s)&&token===s.mediaSequence)s.mediaList.replaceChildren(el('p',error.message),button(s,'重试读取素材',()=>readMedia(s)));}
  }
  async function submit(s){
    if(!live(s)||s.busy)return;
    let uncertainBefore=false;
    try{
      if(!writable(s)||!s.options)throw Error('先选择可写项目并建立操作会话');
      if(!s.pending){
        const prompt=s.draft.prompt,method=s.options.methods.find(m=>m.id===s.draft.method_id);
        if(!prompt.trim()||length(prompt)>2000)throw Error('请输入1至2000字的广告创作需求');
        if(s.draft.media.length>15)throw Error('最多选择15项素材');
        if(s.draft.method_id&&!method)throw Error('所选技能已变化，请重新选择');
        const payload={prompt,episode_id:s.draft.episode_id||null,method_id:method?.id||null,...(method?{method_version:method.version,method_sha256:method.sha256}:{}),media_ids:s.draft.media.map(m=>m.id)};
        s.pending={actor:s.actor,project:s.project,intent:freezeIntent(s),request:{payload,expected_revision:s.revision,idempotency_key:crypto.randomUUID()}};remember(requestKey(s),s.pending);
      }
      // Upgrading a confirmed preparation still requires this explicit click.
      // Its new start intent is frozen once, without changing the original R.
      if(!s.pending.intent){s.pending.intent=freezeIntent(s);remember(requestKey(s),s.pending);}
      s.busy=true;update(s);note(s,s.pending.startResult?'正在查询原规划…':'正在开始营销创作…');
      // The body is fixed before the first write, including its revision and
      // idempotency key. A missing response always retries that same intent.
      const pending=s.pending;
      if(!pending.result){
        uncertainBefore=pending.uncertain===true;pending.uncertain=true;remember(requestKey(s),pending);
        const result=await ctx.api(endpoint(s.project,'marketing-canvases'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth().csrf},body:JSON.stringify(pending.request)});
        pending.result=result;remember(requestKey(s),pending); // Receipt belongs to the original actor/project.
        if(!live(s))return;revision(s,result.revision);
      }
      const result=pending.result,id=result.canvas_id||result.id;if(!id)throw Error('画布回执缺少标识，请恢复上次创作');
      if(!pending.startRequest){
        const canvas=await ctx.api(endpoint(s.project,'creative-canvases/'+encodeURIComponent(id)+'?version='+encodeURIComponent(result.canvas_revision)));if(!live(s))return;
        if(canvas.id!==id&&canvas.canvas?.id!==id)throw Error('画布读回标识不一致，请重试打开');
        if(canvas.canvas_revision!==result.canvas_revision||canvas.sha256!==result.sha256||!result.sha256)throw Error('准备画布固定版本或摘要不一致，原画布已保留');
        const startKey=await marketingStartKey(pending.request.idempotency_key);if(!live(s))return;
        pending.startRequest={payload:{prepare_key:pending.request.idempotency_key,canvas_revision:result.canvas_revision,canvas_sha256:result.sha256,...copy(pending.intent)},expected_revision:canvas.revision,idempotency_key:startKey};remember(requestKey(s),pending);revision(s,canvas.revision);
      }
      if(!live(s))return;
      if(!pending.startResult){
        const start=await ctx.api(endpoint(s.project,'marketing-canvases/'+encodeURIComponent(id)+'/start'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth().csrf},body:JSON.stringify(pending.startRequest)});
        pending.startResult=start;remember(requestKey(s),pending);if(!live(s))return;revision(s,start.revision);
      }
      const start=pending.startResult;
      if(start.project_id!==s.project||start.canvas_id!==id||start.prepare_key!==pending.request.idempotency_key||start.start_key!==pending.startRequest.idempotency_key||start.canvas_revision!==result.canvas_revision||start.canvas_sha256!==result.sha256||!start.turn_id||!start.session_id)throw Error('原规划回执归属不一致，请保留原请求并重读');
      let turn=await readTurn(s,pending);if(!live(s))return;
      if(['queued','result_ready'].includes(turn.status)){
        pending.executeAttempted=true;remember(requestKey(s),pending);
        await ctx.api(endpoint(s.project,'creative-canvas-agent-turns/'+encodeURIComponent(start.turn_id)+'/execute'),{method:'POST',headers:{'X-CSRF-Token':auth().csrf}});if(!live(s))return;
        turn=await readTurn(s,pending);if(!live(s))return;
      }
      pending.turn_status=turn.status;remember(requestKey(s),pending);
      await ctx.navigate('creative-canvas',null,s.project,{task_target:id,...(start.episode_id?{episode:start.episode_id}:{}),marketing:'1',agent_turn:start.turn_id});
      // Navigation can show its own recoverable error without rejecting. Keep
      // R/S/T until the user explicitly starts a different creation.
      if(live(s))note(s,turn.status==='submission_unknown'?'原规划状态待查；仅打开原记录，不重新发送。':'原规划已打开。返回后可继续同一规划，或开始新创作。');
    }catch(error){
      if(!live(s))return;
      if(!s.pending?.result&&!uncertainBefore&&error.status>=400&&error.status<500){s.pending=null;remember(requestKey(s),null);s.options=null;note(s,error.message+'；输入已保留，请重新读取项目后继续。');
        s.status.append(button(s,'重新读取项目',()=>load({project:s.project})));}
      else {note(s,error.message+(s.pending?.startResult?'；重试将查询同一规划，不再次发送首句。':s.pending?.result?'；原准备画布和请求已保留，继续恢复原操作。':s.pending?'；需求已保留，重试将恢复同一操作。':''));
        if(s.pending?.result&&!s.pending.startResult)s.status.append(button(s,'打开已准备的画布',()=>ctx.navigate('creative-canvas',null,s.project,{task_target:s.pending.result.canvas_id||s.pending.result.id,...(s.pending.result.episode_id?{episode:s.pending.result.episode_id}:{}),marketing:'1',skill:s.pending.result.agent_handoff?.skill_id||'vsc-assets'})));}
    }finally{if(live(s)){s.busy=false;update(s);}}
  }
  async function readTurn(s,pending){
    const start=pending.startResult,turn=await ctx.api(endpoint(s.project,'creative-canvas-agent-turns/'+encodeURIComponent(start.turn_id)));if(!live(s))return null;
    if(turn.id!==start.turn_id||turn.project_id!==s.project||turn.canvas_id!==start.canvas_id||turn.canvas_revision!==start.canvas_revision||turn.session_id!==start.session_id||(turn.episode_id||null)!==(start.episode_id||null))throw Error('原规划读回归属不一致，请重读原规划');
    revision(s,turn.revision);return turn;
  }
  function suspend(){if(!state)return;save(state);state.disposed=true;state.upload?.suspend();state.runScope?.dispose();}
  async function load(scope={}){
    suspend();const actor=auth().actor||'',choice=recall(key('project',actor));
    const p=scope.project!==undefined?scope.project:(choice?.project||null),s={actor,project:p||null,disposed:false,sequence:++sequence,revision:null,options:null,busy:false,mediaSequence:0};state=s;
    const draft=recall(draftKey(s))||scope.seed,date=mins=>{const now=new Date(Date.now()+mins*60000);return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);};s.draft={prompt:draft?.prompt||'',method_id:draft?.method_id||'',episode_id:scope.episode??draft?.episode_id??'',media:Array.isArray(draft?.media)?draft.media:[],model_ids:draft?.model_ids||[],mode:draft?.mode||'manual',execution:{duration:'5',first_due:date(60),stop_at:date(120),max_jobs:'2',max_images:'2',max_video_seconds:'10',max_credits:'0',...draft?.execution}};
    s.pending=recall(requestKey(s))||null;
    if(s.pending?.actor!==actor||s.pending?.project!==s.project)s.pending=null;
    if(s.pending&&!s.pending.result&&s.pending.uncertain===undefined){s.pending.uncertain=true;remember(requestKey(s),s.pending);}
    if(s.pending){const payload=s.pending.request.payload;s.draft={...s.draft,prompt:payload.prompt,method_id:payload.method_id||'',episode_id:payload.episode_id||'',media:payload.media_ids.map(id=>s.draft.media.find(m=>m.id===id)||{id,name:id})};}
    if(s.pending?.intent){s.draft.model_ids=[...s.pending.intent.model_ids];s.draft.mode=s.pending.intent.execution_settings.auto_media?'auto_media':s.pending.intent.mode;}
    remember(key('project',actor),{project:s.project});draw(s);
    if(!s.project){note(s,'请选择归属项目后继续。');return;}
    note(s,'正在读取营销技能与项目…');
    try{
      const options=await ctx.api(endpoint(s.project,'marketing-options'));if(!live(s))return;
      s.options=options;revision(s,options.revision);
      if(!s.pending){if(!options.methods.some(m=>m.id===s.draft.method_id))s.draft.method_id='';if(!options.episodes.some(e=>e.id===s.draft.episode_id))s.draft.episode_id='';s.draft.model_ids=s.draft.model_ids.filter(id=>options.models.some(m=>m.id===id&&m.enabled));save(s);}
      draw(s);
    }catch(error){if(live(s)){s.error=error.message;draw(s);s.status.append(button(s,'重试读取项目',()=>load({project:s.project})));}}
  }
  return {load,suspend};
}
