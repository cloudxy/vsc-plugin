import {createMediaUpload} from './media-upload.js';

// Marketing preparation writes the original canvas authority. Generation and
// model selection continue in that canvas's Agent after the user's decision.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const option=(value,title)=>{const n=el('option',title);n.value=value;return n;};
const copy=value=>JSON.parse(JSON.stringify(value));
const endpoint=(p,path)=>`/api/v1/projects/${encodeURIComponent(p)}/${path}`;
const genericHint='上传创作素材或引用项目素材，描述你想创作的广告内容、核心卖点或创意想法…';
const length=value=>Array.from(value).length;

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
    s.prompt.disabled=locked;
    s.projectSelect.disabled=s.busy; // A pending receipt may be left and restored in its own project.
    s.submit.disabled=s.busy||!s.options||!writable(s)||(!s.pending&&!validPrompt);
    s.submit.textContent=s.busy?'正在准备…':s.pending?(s.pending.result?'继续打开画布':'恢复上次创作'):'进入画布继续';
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
  }
  function draw(s){
    if(!live(s))return;
    s.upload?.suspend();s.upload=null;
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
    const models=button(s,'◇',()=>{s.modelNote.hidden=!s.modelNote.hidden;},'marketing-icon');models.title='选择模型';models.setAttribute('aria-label','选择模型');tools.append(ref,models);s.editables.push(ref);
    s.counter=el('small',null,'marketing-count');tools.append(s.counter);
    const scope=el('div',null,'marketing-scope');s.projectSelect=el('select');s.projectSelect.append(option('','请选择归属项目'));
    for(const p of ctx.projects())s.projectSelect.append(option(p.id,p.name+(p.read_only?' · 只读':'')));
    s.projectSelect.value=s.project||'';s.projectSelect.onchange=()=>{if(live(s)){save(s);return load({project:s.projectSelect.value,...(!s.project?{seed:s.draft}:{})});}};
    s.episodeSelect=el('select');s.episodeSelect.append(option('','不指定剧集'));
    for(const e of s.options?.episodes||[])s.episodeSelect.append(option(e.id,e.title||e.display_code||e.name||e.id));
    s.episodeSelect.value=s.draft.episode_id||'';s.episodeSelect.onchange=()=>{if(live(s)&&!s.pending){s.draft.episode_id=s.episodeSelect.value;save(s);}};s.editables.push(s.episodeSelect);
    s.submit=el('button','进入画布继续','marketing-submit');s.submit.type='submit';scope.append(labelled('归属项目',s.projectSelect),labelled('归属剧集',s.episodeSelect),s.submit);footer.append(tools,scope);form.append(footer);
    form.onsubmit=e=>{e.preventDefault();return submit(s);};root.append(form);
    s.methodSummary=el('p',null,'marketing-method-summary');root.append(s.methodSummary);
    s.modelNote=el('p','在画布 Agent 中选择图片、视频模型并确认后继续创作。','marketing-model-note');s.modelNote.hidden=true;root.append(s.modelNote);
    s.status=el('p',null,'marketing-status');s.status.setAttribute('role','status');root.append(s.status);
    const explanation=el('p','将需求、技能和所选素材放入新画布，交给 Agent 继续确认。本步不启动付费生成。','marketing-continuation');root.append(explanation);
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
    else if(s.pending)note(s,s.pending.result?'画布已创建；继续将读回并打开同一画布。':'上次操作回执待确认。需求与素材已保留，恢复时使用原请求。');
    else if(s.project&&!writable(s))note(s,'当前项目不可写，请选择可写项目或建立操作会话。');
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
        s.pending={actor:s.actor,project:s.project,request:{payload,expected_revision:s.revision,idempotency_key:crypto.randomUUID()}};remember(requestKey(s),s.pending);
      }
      s.busy=true;update(s);note(s,s.pending.result?'正在打开已创建的画布…':'正在准备营销画布…');
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
      if(!pending.readback){
        const canvas=await ctx.api(endpoint(s.project,'creative-canvases/'+encodeURIComponent(id)));if(!live(s))return;
        if(canvas.id!==id&&canvas.canvas?.id!==id)throw Error('画布读回标识不一致，请重试打开');
        pending.readback=true;remember(requestKey(s),pending);revision(s,canvas.revision);
      }
      if(!live(s))return;
      await ctx.navigate('creative-canvas',null,s.project,{task_target:id,...(result.episode_id||pending.request.payload.episode_id?{episode:result.episode_id||pending.request.payload.episode_id}:{}),marketing:'1',skill:result.agent_handoff?.skill_id||'vsc-assets'});
      // The canvas may render its own recoverable load error without rejecting
      // navigation. Keep the confirmed receipt until an explicit new creation.
      if(live(s))note(s,'营销画布已打开。返回后可继续同一画布，或开始新创作。');
    }catch(error){
      if(!live(s))return;
      if(!s.pending?.result&&!uncertainBefore&&error.status>=400&&error.status<500){s.pending=null;remember(requestKey(s),null);s.options=null;note(s,error.message+'；输入已保留，请重新读取项目后继续。');
        s.status.append(button(s,'重新读取项目',()=>load({project:s.project})));}
      else note(s,error.message+(s.pending?.result?'；画布已创建，重试只会继续打开原画布。':s.pending?'；需求已保留，重试将恢复同一操作。':''));
    }finally{if(live(s)){s.busy=false;update(s);}}
  }
  function suspend(){if(!state)return;save(state);state.disposed=true;state.upload?.suspend();}
  async function load(scope={}){
    suspend();const actor=auth().actor||'',choice=recall(key('project',actor));
    const p=scope.project!==undefined?scope.project:(choice?.project||null),s={actor,project:p||null,disposed:false,sequence:++sequence,revision:null,options:null,busy:false,mediaSequence:0};state=s;
    const draft=recall(draftKey(s))||scope.seed;s.draft={prompt:draft?.prompt||'',method_id:draft?.method_id||'',episode_id:scope.episode??draft?.episode_id??'',media:Array.isArray(draft?.media)?draft.media:[]};
    s.pending=recall(requestKey(s))||null;
    if(s.pending?.actor!==actor||s.pending?.project!==s.project)s.pending=null;
    if(s.pending&&!s.pending.result&&s.pending.uncertain===undefined){s.pending.uncertain=true;remember(requestKey(s),s.pending);}
    if(s.pending){const payload=s.pending.request.payload;s.draft={...s.draft,prompt:payload.prompt,method_id:payload.method_id||'',episode_id:payload.episode_id||'',media:payload.media_ids.map(id=>s.draft.media.find(m=>m.id===id)||{id,name:id})};}
    remember(key('project',actor),{project:s.project});draw(s);
    if(!s.project){note(s,'请选择归属项目后继续。');return;}
    note(s,'正在读取营销技能与项目…');
    try{
      const options=await ctx.api(endpoint(s.project,'marketing-options'));if(!live(s))return;
      s.options=options;revision(s,options.revision);
      if(!s.pending){if(!options.methods.some(m=>m.id===s.draft.method_id))s.draft.method_id='';if(!options.episodes.some(e=>e.id===s.draft.episode_id))s.draft.episode_id='';save(s);}
      draw(s);
    }catch(error){if(live(s)){s.error=error.message;draw(s);s.status.append(button(s,'重试读取项目',()=>load({project:s.project})));}}
  }
  return {load,suspend};
}
