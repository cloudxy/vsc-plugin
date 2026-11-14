import {createMediaUpload} from './media-upload.js';
import {createRunScopeControls} from './run-scope-controls.js';
import {onLocaleChange} from './i18n.js';

// One explicit intent prepares a canvas and starts its original Agent turn.
// Recovery follows the fixed prepare/start receipts and never sends a new turn.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const option=(value,title)=>{const n=el('option',title);n.value=value;return n;};
const copy=value=>JSON.parse(JSON.stringify(value));
const endpoint=(p,path)=>`/api/v1/projects/${encodeURIComponent(p)}/${path}`;
const genericHint='上传创作素材或引用项目素材，描述你想创作的广告内容、核心卖点或创意想法…';
const length=value=>Array.from(value).length;
const CASE_FIELDS=['schema','id','version','sha256','source_origin','template_key','group_key','category_name','category_label','group_name','group_description','video_name','cover_url','video_url','width','height','evidence_id','evidence_body_sha256'];
const casePin=spec=>({id:spec.id,version:spec.version,sha256:spec.sha256});
const samePin=(a,b)=>Boolean(a&&b&&a.id===b.id&&a.version===b.version&&a.sha256===b.sha256);
const stable=value=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(k=>[k,item[k]])):item);
// Display bytes always come from the local mirror; case source URLs remain immutable provenance.
const caseMediaURL=(spec,kind)=>'/api/v1/marketing-assets/cases/'+encodeURIComponent(spec.template_key)+'/'+kind;
const METHOD_COVERS=Object.freeze(Object.fromEntries([
  'short-drama-commerce','product-poster','commercial-tvc','viral-video-clone','ugc-commerce',
  'video-localization','viral-creative-variation','product-visual-materials'
].map(id=>[id,'/api/v1/marketing-assets/methods/'+id])));
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
  const caseScope=s=>JSON.stringify([s.actor,s.project,auth().account_id??auth().identityId??null,document.documentElement?.lang||'',globalThis.location?.search||'']);
  const caseViews=s=>[s.cases,s.picker?.view].filter(Boolean);
  const caseViewLive=(s,c)=>live(s)&&Boolean(c)&&(c===s.cases||s.picker?.open&&c===s.picker.view);
  const caseLive=(s,c,seq,stamp)=>caseViewLive(s,c)&&c.requestSeq===seq&&caseScope(s)===stamp;
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
    if(s.skillButton){s.skillButton.disabled=locked||!s.options;s.skillButton.setAttribute('aria-pressed',String(Boolean(s.draft.method_id)));}if(s.allMethods)s.allMethods.disabled=locked||!s.options;
    if(locked)closeMethodPicker(s);else if(s.methodPicker?.open)syncMethodSelection(s);
    s.methodChip.replaceChildren();if(s.draft.method_id){const chip=el('span',null,'marketing-selected-method'),remove=methodButton(s,'×',()=>selectMethod(s,'','chip'),'',()=>s.methodChip.contains(remove));remove.disabled=locked||!s.options;remove.setAttribute('aria-label','删除已选技能');chip.append(el('span',selected?.name||'已选技能'),remove);s.methodChip.append(chip);}
    s.materials.replaceChildren();
    for(const item of s.draft.media){
      const chip=el('span',null,'marketing-material-chip');chip.append(el('span',item.name||item.id));
      const remove=button(s,'×',()=>{s.draft.media=s.draft.media.filter(m=>m.id!==item.id);save(s);update(s);});remove.disabled=locked;remove.setAttribute('aria-label','移除素材 '+(item.name||item.id));chip.append(remove);s.materials.append(chip);
    }
    if(s.caseChip){s.caseChip.replaceChildren();const pin=s.pending?.request.payload.case_ref||s.draft.case&&casePin(s.draft.case);if(pin){const spec=s.pending?.case_display||s.draft.case,chip=el('span',null,'marketing-selected-case');chip.append(button(s,spec?.group_name||'已选创意',()=>{if(spec)openCase(s,spec,{historical:true});},'marketing-case-chip-open'));const remove=button(s,'×',()=>{if(s.pending||s.busy)return;s.draft.case=null;save(s);update(s);});remove.disabled=locked;remove.setAttribute('aria-label','删除已选创意');chip.append(remove);s.caseChip.append(chip);}}
    s.mediaCount.textContent=`已选 ${s.draft.media.length} / 15`;
    if(s.modelOrder)s.modelOrder.textContent=s.draft.model_ids.map((id,i)=>`${i+1}. ${s.options?.models?.find(m=>m.id===id)?.model_key||id}`).join(' → ')||'由 Agent 先确认需求';
    if(s.autoLimits)s.autoLimits.hidden=s.draft.mode!=='auto_media';
    if(s.autoMediaCheck){s.autoMediaCheck.checked=s.draft.mode==='auto_media';s.autoMediaCheck.disabled=locked||s.draft.mode==='manual';}
    if(s.runFieldset)s.runFieldset.hidden=Boolean(s.pending)||s.draft.mode==='manual';
    if(s.frozenIntent){const intent=s.pending?.intent;s.frozenIntent.hidden=!intent;if(intent){const settings=intent.execution_settings,limits=settings.auto_media,policy=settings.execution_policy,authorization=policy?.authorization;s.frozenIntent.textContent=['本次固定范围：'+(limits?'有界自动媒体':intent.mode==='manual'?'手动规划':'自动编排'),s.modelOrder.textContent,limits?`最多${limits.max_jobs}个任务、${limits.max_images}张图片、${limits.max_video_ms/1000}秒视频；商业额度上限${limits.max_credits}`:'',policy?'停止新增任务：'+policy.stop_submitting_at:'',authorization?.mode==='new_batch'?'新批次原因：'+authorization.reason:authorization?.mode==='continue'?'继续原批次：'+authorization.run_version_id:''].filter(Boolean).join('；');}}
    if(s.creativeButton){s.creativeButton.disabled=locked;s.creativeButton.setAttribute('aria-pressed',String(Boolean(s.pending?.request.payload.case_ref||s.draft.case)));}
    if(locked&&s.picker?.open)closePicker(s,false);
    for(const c of caseViews(s))if(caseViewLive(s,c)){syncCaseSelection(s,c);for(const n of c.selectButtons||[])n.disabled=locked||n.caseReady===false;if(c.pager)renderCasePager(s,c);}
  }
  function draw(s){
    if(!live(s))return;
    s.upload?.suspend();s.upload=null;
    closeMethodPicker(s);s.methodScope=caseScope(s);
    closePicker(s,false);
    stopPreview(s.cases);closeCase(s,false);
    s.runScope?.dispose();s.runScope=null;
    root.replaceChildren();root.classList.add('marketing-studio');
    const heading=el('header',null,'marketing-heading');heading.append(el('h1','和营销 Agent 聊创意，助你轻松打造好广告'));root.append(heading);
    s.editables=[];s.methodButtons=new Map();
    const methods=el('nav',null,'marketing-methods');methods.setAttribute('aria-label','营销热门技能');
    for(const item of s.options?.methods||[]){
      const b=methodButton(s,'',()=>selectMethod(s,item.id,'popular',b),'marketing-method',()=>s.methodButtons.get(item.id)===b);b.dataset.methodId=item.id;b.setAttribute('aria-label',item.name);b.append(methodCover(item,()=>s.methodButtons.get(item.id)===b&&methodAvailable(s)),el('span',item.name));
      if(item.description)b.title=item.description;methods.append(b);s.methodButtons.set(item.id,b);s.editables.push(b);
    }
    const form=el('form',null,'marketing-composer'),body=el('div',null,'marketing-input-row');
    const add=button(s,'',()=>toggleSurface(s,'material'),'marketing-add');add.append(el('span','+','marketing-add-icon'),el('span','添加创作素材'),el('small','商品/参考图片、视频等'));s.editables.push(add);
    s.prompt=el('textarea',null,'marketing-prompt');s.prompt.value=s.draft.prompt;s.prompt.rows=4;s.prompt.setAttribute('aria-label','广告创作需求');
    s.prompt.oninput=()=>{if(!live(s)||s.pending)return;s.draft.prompt=s.prompt.value;save(s);update(s);};
    for(const event of ['select','keyup','pointerup','blur'])s.prompt.addEventListener(event,()=>rememberPromptRange(s));
    s.prompt.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();submit(s);}};
    s.editables.push(s.prompt);body.append(add,s.prompt);form.append(body);
    s.materials=el('div',null,'marketing-materials');s.caseChip=el('div',null,'marketing-case-chip');s.methodChip=el('div',null,'marketing-method-chip');form.append(s.methodChip,s.caseChip,s.materials);
    const footer=el('div',null,'marketing-toolbar'),tools=el('div',null,'marketing-tools');
    const ref=button(s,'@',()=>toggleSurface(s,'material'),'marketing-icon');ref.title='引用素材';ref.setAttribute('aria-label','引用素材');
    const skill=methodButton(s,'▤',()=>openMethodPicker(s,skill,true),'marketing-icon marketing-skill-trigger',()=>s.skillButton===skill);s.skillButton=skill;skill.title='技能';skill.setAttribute('aria-label','技能');skill.setAttribute('aria-haspopup','dialog');skill.setAttribute('aria-expanded','false');
    s.creativeButton=button(s,'✧',()=>togglePicker(s),'marketing-icon marketing-creative-trigger');s.creativeButton.title='创意';s.creativeButton.setAttribute('aria-label','创意');s.creativeButton.setAttribute('aria-haspopup','dialog');s.creativeButton.setAttribute('aria-expanded','false');
    const models=button(s,'◇',()=>toggleSurface(s,'model'),'marketing-icon');models.title='选择模型';models.setAttribute('aria-label','选择模型');tools.append(ref,s.skillButton,s.creativeButton,models);s.editables.push(ref,models);
    const mode=el('select',null,'marketing-mode');mode.setAttribute('aria-label','创作模式');mode.append(option('manual','手动模式'),option('auto_drafts','自动模式'));mode.value=s.draft.mode==='manual'?'manual':'auto_drafts';mode.onchange=()=>{if(!live(s)||s.pending)return;s.draft.mode=mode.value;save(s);update(s);if(mode.value!=='manual'){prepareSurface(s,'model');s.executionPanel.hidden=false;}};tools.append(mode);s.editables.push(mode);
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
    const all=methodButton(s,'全部',()=>openMethodPicker(s,all),'marketing-methods-all',()=>s.allMethods===all);s.allMethods=all;all.setAttribute('aria-label','全部技能');all.setAttribute('aria-haspopup','dialog');all.setAttribute('aria-expanded','false');const methodsHeading=el('div',null,'marketing-methods-heading');methodsHeading.append(el('p','引用热门技能，让 Agent 按专业方法创作'),all);root.append(methodsHeading,methods);
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
    mountCases(s);
    if(!ctx.projects().length)root.append(button(s,'查看或新建项目',()=>ctx.navigate('projects',null,null)));
    update(s);
    if(s.error)note(s,s.error);
    else if(s.pending)note(s,s.pending.startResult?'原规划已建立；继续只查询并打开同一规划。':s.pending.result?'准备画布已保留；继续将沿原请求开始创作。':'上次操作回执待确认。需求与素材已保留，恢复时使用原请求。');
    else if(s.project&&!writable(s))note(s,'当前项目不可写，请选择可写项目或建立操作会话。');
  }
  function stopPreview(c){if(!c?.preview)return;const p=c.preview;c.preview=null;p.video.pause?.();p.video.hidden=true;if(p.poster)p.poster.hidden=false;if(p.button)p.button.textContent='播放预览';if(p.container)p.container.hidden=true;}
  function clearCasePreviews(c){stopPreview(c);for(const box of c?.previewBoxes||[])box.remove();if(c)c.previewBoxes=[];}
  function stopCaseObserver(c){if(!c)return;c.observerEpoch=(c.observerEpoch||0)+1;c.moreObserver?.disconnect();c.moreObserver=null;c.sentinel=null;}
  function closeCase(s,focus=true,c=s?.cases){if(!c)return;c.detailSeq++;stopPreview(c);if(c.dialog){const d=c.dialog;c.dialog=null;d.close?.();d.remove?.();}c.detailChoice=null;if(focus&&c.trigger?.isConnected)c.trigger.focus?.();c.trigger=null;if(focus&&caseViewLive(s,c)&&c.pager)renderCasePager(s,c);}
  function caseButton(s,title,fn,cls=''){const b=button(s,title,fn,cls),handler=b.onclick;b.onclick=e=>{e?.stopPropagation?.();return handler();};return b;}
  function rememberPromptRange(s){if(live(s)&&Number.isInteger(s.prompt?.selectionStart))s.promptRange={start:s.prompt.selectionStart,end:s.prompt.selectionEnd,direction:s.prompt.selectionDirection||'none'};}
  function focusPrompt(s){if(!live(s)||s.prompt.disabled)return;const range=s.promptRange;s.prompt.focus?.({preventScroll:true});if(range)s.prompt.setSelectionRange?.(Math.min(range.start,s.prompt.value.length),Math.min(range.end,s.prompt.value.length),range.direction);}
  const methodAvailable=(s,scope=s.methodScope)=>live(s)&&Boolean(s.options)&&!s.pending&&!s.busy&&caseScope(s)===scope;
  function methodButton(s,title,fn,cls='',current=()=>true){const b=button(s,title,fn,cls),handler=b.onclick;b.onclick=e=>{if(!current())return;if(!methodAvailable(s)){closeMethodPicker(s);return;}return handler(e);};return b;}
  function methodCover(item,current){
    const box=el('span',null,'marketing-method-thumb');box.setAttribute('aria-hidden','true');const url=METHOD_COVERS[item.source_slug||item.id];if(!url){box.classList.add('is-fallback');return box;}
    const image=el('img');image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';image.src=url;image.onerror=()=>{if(current()){image.hidden=true;box.classList.add('is-fallback');}};box.append(image);return box;
  }
  function prepareSurface(s,kind){
    if(kind!=='method')closeMethodPicker(s);if(kind!=='case')closePicker(s,false);
    for(const c of caseViews(s)){stopPreview(c);if(kind!=='case'){closeCase(s,false,c);if(caseViewLive(s,c)&&c.pager)renderCasePager(s,c);}}
    if(kind!=='model'&&s.executionPanel)s.executionPanel.hidden=true;if(kind!=='material'&&s.materialPanel)s.materialPanel.hidden=true;
  }
  function toggleSurface(s,kind){const panel=kind==='model'?s.executionPanel:s.materialPanel;if(!panel)return;const open=panel.hidden;if(open)prepareSurface(s,kind);panel.hidden=!open;}
  function closeMethodPicker(s,focus='none'){
    const p=s?.methodPicker;if(!p?.open)return;const opener=p.opener,scope=p.scope;p.open=false;p.epoch++;p.cleanup?.();p.cleanup=null;p.element?.remove();p.element=null;
    s.skillButton?.setAttribute('aria-expanded','false');s.allMethods?.setAttribute('aria-expanded','false');
    if(!methodAvailable(s,scope))return;if(focus==='opener'&&opener?.isConnected)opener.focus?.({preventScroll:true});else if(focus==='prompt')focusPrompt(s);
  }
  function selectMethod(s,id,origin,node=null){
    if(!methodAvailable(s)||id&&!s.options.methods.some(item=>item.id===id))return;rememberPromptRange(s);
    const cancel=origin==='popular'&&s.draft.method_id===id;s.draft.method_id=cancel?'':id;save(s);closeMethodPicker(s);update(s);
    if(cancel)node?.focus?.({preventScroll:true});else focusPrompt(s);
  }
  function syncMethodSelection(s){const p=s.methodPicker;if(!p?.active?.())return;for(const row of p.rows||[]){const selected=row.id===s.draft.method_id;row.button.setAttribute('aria-pressed',String(selected));row.check.hidden=!selected;}}
  function renderMethodRows(s,p){
    const active=p.active;if(!active())return;const render=++p.renderSeq,query=p.query.trim().toLocaleLowerCase();p.list.replaceChildren();p.rows=[];
    for(const item of s.options.methods.filter(item=>[item.name,item.description,item.displayName].some(value=>String(value||'').toLocaleLowerCase().includes(query)))){
      const current=()=>active()&&p.renderSeq===render,row=methodButton(s,'',()=>selectMethod(s,item.id,'directory'),'marketing-method-option',current);row.dataset.methodId=item.id;row.setAttribute('aria-label','选择技能 '+item.name);
      const text=el('span',null,'marketing-method-option-copy');text.append(el('span',item.name,'marketing-method-option-name'),el('span',item.description||'','marketing-method-option-description'));const check=el('span','✓','marketing-method-option-check');check.setAttribute('aria-hidden','true');row.append(methodCover(item,current),text,check);p.list.append(row);p.rows.push({id:item.id,button:row,check});
    }
    if(!p.rows.length)p.list.append(el('p','没有匹配的技能','marketing-method-empty'));syncMethodSelection(s);p.position?.();
  }
  function openMethodPicker(s,opener,toggle=false){
    if(!methodAvailable(s)){closeMethodPicker(s);return;}const p=s.methodPicker||(s.methodPicker={query:'',epoch:0,renderSeq:0});
    if(p.open){if(!p.active())return;if(toggle){closeMethodPicker(s);return;}p.opener=opener;return;}
    rememberPromptRange(s);prepareSurface(s,'method');p.open=true;p.opener=opener;p.scope=caseScope(s);const epoch=++p.epoch,element=el('section',null,'marketing-method-picker');p.element=element;element.setAttribute('role','dialog');element.setAttribute('aria-label','选择技能');
    const owns=()=>s.methodPicker===p&&p.epoch===epoch&&p.element===element;p.active=()=>{if(!owns()||!p.open)return false;if(!methodAvailable(s,p.scope)){closeMethodPicker(s);return false;}return true;};const active=p.active;
    const query=el('input',null,'marketing-method-search');p.search=query;query.type='search';query.placeholder='搜索技能';query.value=p.query;query.setAttribute('aria-label','搜索技能');query.oninput=()=>{if(active()&&p.search===query){p.query=query.value;renderMethodRows(s,p);}};
    p.list=el('div',null,'marketing-method-options');element.append(query,p.list);root.append(element);s.skillButton.setAttribute('aria-expanded','true');s.allMethods.setAttribute('aria-expanded','true');
    const position=()=>{if(!active())return;const box=s.skillButton.getBoundingClientRect(),width=globalThis.window?.innerWidth||globalThis.innerWidth||document.documentElement?.clientWidth||1024,height=globalThis.window?.innerHeight||globalThis.innerHeight||768,size=Math.min(407,Math.max(0,width-24)),limit=Math.max(0,Math.min(height*.7,height-24)),desired=Math.min(element.offsetHeight||432,limit),below=box.bottom+8,above=height-below-12<desired&&box.top-20>height-below-12;const top=Math.max(12,Math.min(height-12,above?box.top-desired-8:below));element.style.width=size+'px';element.style.left=Math.max(12,Math.min(box.left,width-size-12))+'px';element.style.top=top+'px';element.style.maxHeight=Math.max(0,Math.min(limit,above?box.top-20:height-top-12))+'px';};p.position=position;
    const outside=e=>{if(active()&&!element.contains(e.target)&&!s.skillButton.contains(e.target)&&!s.allMethods.contains(e.target))closeMethodPicker(s);},escape=e=>{if(active()&&e.key==='Escape'){e.preventDefault();closeMethodPicker(s,'opener');}};
    document.addEventListener?.('pointerdown',outside,true);document.addEventListener?.('keydown',escape);root.addEventListener?.('scroll',position,true);globalThis.window?.addEventListener?.('resize',position);p.cleanup=()=>{document.removeEventListener?.('pointerdown',outside,true);document.removeEventListener?.('keydown',escape);root.removeEventListener?.('scroll',position,true);globalThis.window?.removeEventListener?.('resize',position);};renderMethodRows(s,p);
  }
  function closePicker(s,focus=true){const p=s?.picker;if(!p?.open)return;p.open=false;p.view.requestSeq++;p.view.activeRead=null;p.view.loading=false;clearTimeout(p.view.debounce);stopCaseObserver(p.view);for(const c of caseViews(s))stopPreview(c);clearCasePreviews(p.view);closeCase(s,false,p.view);p.view.masonry?.disconnect();p.cleanup?.();p.element?.remove();s.creativeButton?.setAttribute('aria-expanded','false');if(focus)focusPrompt(s);}
  function togglePicker(s){
    if(!live(s)||s.pending||s.busy)return;if(s.picker?.open){closePicker(s);return;}rememberPromptRange(s);prepareSurface(s,'case');for(const c of caseViews(s)){stopPreview(c);closeCase(s,false,c);}
    const p=s.picker||(s.picker={view:newCaseView(s,true)});p.open=true;const element=el('section',null,'marketing-creative-picker');p.element=element;element.setAttribute('role','dialog');element.setAttribute('aria-label','选择创意');
    root.append(element);s.creativeButton.setAttribute('aria-expanded','true');
    const active=()=>caseViewLive(s,p.view)&&p.element===element;
    const position=()=>{if(!active())return;const box=s.creativeButton.getBoundingClientRect(),width=globalThis.window?.innerWidth||globalThis.innerWidth||document.documentElement?.clientWidth||1024,height=globalThis.window?.innerHeight||globalThis.innerHeight||768,size=Math.min(407,Math.max(0,width-24)),below=box.bottom+8;const top=below+220>height&&box.top>height-box.bottom?Math.max(12,box.top-Math.min(432,height*.7,box.top-24)):Math.max(12,below);element.style.width=size+'px';element.style.left=Math.max(12,Math.min(box.left,width-size-12))+'px';element.style.top=top+'px';element.style.maxHeight=Math.max(0,Math.min(432,height*.7,height-top-12))+'px';};
    const outside=e=>{if(active()&&!element.contains(e.target)&&!s.creativeButton.contains(e.target))closePicker(s,false);},escape=e=>{if(active()&&e.key==='Escape'){e.preventDefault();closePicker(s);}};
    document.addEventListener?.('pointerdown',outside,true);document.addEventListener?.('keydown',escape);root.addEventListener?.('scroll',position,true);globalThis.window?.addEventListener?.('resize',position);p.cleanup=()=>{document.removeEventListener?.('pointerdown',outside,true);document.removeEventListener?.('keydown',escape);root.removeEventListener?.('scroll',position,true);globalThis.window?.removeEventListener?.('resize',position);};
    mountCases(s,{view:p.view,compact:true,host:element});position();p.view.query.focus?.();
  }
  function syncCaseSelection(s,c){
    const pin=s.pending?.request.payload.case_ref||s.draft.case;
    if(!c.compact&&c.displayed&&c.items.some(group=>(group.examples.find(item=>samePin(item,pin))||group.examples[0])?.template_key!==c.displayed.get(group.group_key))){renderCases(s,c);return;}
    for(const entry of c.choices||[]){const selected=entry.group?entry.group.examples.some(item=>samePin(item,pin)):samePin(entry.spec,pin);entry.node.classList[selected?'add':'remove']('is-selected');entry.button.setAttribute('aria-pressed',String(selected));if(entry.label)entry.button.textContent=selected?'已选':entry.label;if(entry.check)entry.check.hidden=!selected;}
    if(c.detailChoice)c.detailChoice.button.textContent=samePin(c.detailChoice.spec,pin)?'已选':'选择此创意';
  }
  function selectCase(s,spec){
    if(!live(s)||s.pending||s.busy)return;
    rememberPromptRange(s);if(!samePin(s.draft.case,spec)){s.draft.case=copy(spec);save(s);update(s);}for(const c of caseViews(s))closeCase(s,false,c);closePicker(s,false);for(const c of caseViews(s))if(caseViewLive(s,c)&&c.pager)renderCasePager(s,c);focusPrompt(s);note(s,'已选择创意参考：'+spec.group_name);
  }
  function newCaseView(s,compact=false){const pref=recall(key(compact?'case-browser-compact':'case-browser',s.actor,s.project));return {compact,requestSeq:0,detailSeq:0,renderSeq:0,category:pref?.category||'',keyword:pref?.keyword||'',input:pref?.keyword||'',H:null,items:[],categories:[],next:1,total:0,loading:false,loaded:false,examples:new Map(),selectButtons:[]};}
  function mountCases(s,{view=null,compact=false,host=root}={}){
    const c=view||(s.cases||(s.cases=newCaseView(s)));c.selectButtons=[];const section=el('section',null,'marketing-ideas'+(compact?' marketing-ideas--compact':'')),head=el('div',null,'marketing-cases-heading');c.filters=el('nav',null,'marketing-case-categories');c.filters.setAttribute('aria-label',compact?'紧凑创意分类':'创意分类');
    const query=c.query=el('input',null,'marketing-case-search');query.type='search';query.value=c.input;query.placeholder='搜索名称、描述或分类';query.setAttribute('aria-label',compact?'搜索紧凑创意':'搜索营销创意');
    query.oninput=()=>{if(!caseViewLive(s,c))return;const stamp=caseScope(s);clearTimeout(c.debounce);c.input=query.value;c.requestSeq++;stopCaseObserver(c);stopPreview(c);closeCase(s,false,c);c.debounce=setTimeout(()=>{if(!caseViewLive(s,c)||caseScope(s)!==stamp)return;c.keyword=c.input.trim();remember(key(compact?'case-browser-compact':'case-browser',s.actor,s.project),{category:c.category,keyword:c.keyword});readCases(s,1,true,false,c);},300);};
    head.append(c.filters,query);c.summary=compact?null:el('p',null,'marketing-case-count');c.grid=el('div',null,compact?'marketing-case-options':'marketing-case-grid');c.feedback=el('div',null,'marketing-case-feedback');c.feedback.setAttribute('role','status');c.pager=el('div',null,'marketing-case-pager');const results=el('div',null,compact?'marketing-picker-results':'marketing-case-results');if(c.summary)results.append(c.summary);results.append(c.grid,c.feedback,c.pager);c.scrollRoot=compact?results:root;section.append(head,results);host.append(section);
    const changed=c.input.trim()!==c.keyword;if(changed){c.keyword=c.input.trim();remember(key(compact?'case-browser-compact':'case-browser',s.actor,s.project),{category:c.category,keyword:c.keyword});}renderCaseFilters(s,c);renderCases(s,c);if(changed||!c.loaded&&!c.loading)readCases(s,1,true,false,c);
  }
  function renderCaseFilters(s,c=s.cases){if(!caseViewLive(s,c)||!c.filters)return;const scrollLeft=c.filters.scrollLeft||0;c.filters.replaceChildren();for(const category of [{category_name:'',category_label:'全部创意'},...c.categories]){const b=caseButton(s,category.category_label,()=>{if(!caseViewLive(s,c))return;clearTimeout(c.debounce);c.category=category.category_name;c.keyword=c.input.trim();remember(key(c.compact?'case-browser-compact':'case-browser',s.actor,s.project),{category:c.category,keyword:c.keyword});return readCases(s,1,true,false,c);},'marketing-case-category');b.setAttribute('aria-pressed',String(c.category===category.category_name));b.dataset.category=category.category_name;if(!c.compact&&category.available_group_count!=null)b.append(el('small',String(category.available_group_count)));c.filters.append(b);}c.filters.scrollLeft=scrollLeft;}
  function rebindCaseLocale(s){
    closeMethodPicker(s);if(live(s))s.methodScope=caseScope(s);
    closePicker(s,false);
    if(!live(s)||!s.cases)return;const c=s.cases,reading=c.activeRead,keyword=c.input.trim(),changed=keyword!==c.keyword;
    clearTimeout(c.debounce);c.requestSeq++;c.activeRead=null;c.loading=false;stopCaseObserver(c);stopPreview(c);closeCase(s,false);
    if(changed){c.keyword=keyword;remember(key('case-browser',s.actor,s.project),{category:c.category,keyword});}
    // Rebind only the catalogue. Rebuilding the composer would lose values in
    // the original run-scope controls or disturb an in-flight R/S/T intent.
    renderCaseFilters(s);
    if(changed||!c.loaded)readCases(s,1,true,reading?.fresh===true);
    else if(reading)readCases(s,reading.page,reading.reset,reading.fresh);
    else renderCases(s);
  }
  async function readCases(s,page,reset=false,fresh=false,c=s.cases){
    if(!caseViewLive(s,c))return;const seq=++c.requestSeq,stamp=caseScope(s),pageScroll=c.compact?null:root.scrollTop;clearTimeout(c.debounce);stopCaseObserver(c);closeCase(s,false,c);stopPreview(c);if(fresh)c.H=null;
    // A reset must not paint an empty grid before the response. Load-more still rebinds the cards already on screen, then puts the page scroll back in that same turn.
    if(reset){c.items=[];c.loaded=false;c.next=1;c.total=0;}c.activeRead={page,reset,fresh};c.loading=true;c.failed=false;if(!reset){renderCases(s,c);if(pageScroll!=null)root.scrollTop=pageScroll;}c.feedback.replaceChildren(el('p','正在读取创意…'));renderCasePager(s,c);
    const params=new URLSearchParams({page:String(page),page_size:'20'});if(c.H)params.set('catalog_sha256',c.H);if(c.category)params.set('category_name',c.category);if(c.keyword)params.set('keyword',c.keyword);
    try{
      const data=await ctx.api('/api/v1/marketing-cases?'+params);if(!caseLive(s,c,seq,stamp))return;
      if(!data.catalog_sha256||c.H&&c.H!==data.catalog_sha256||data.page!==page||data.page_size!==20)throw Object.assign(Error('创意目录版本或分页不一致，请重新载入目录'),{code:'marketing_catalog_changed'});
      const merged=new Map(c.items.map(item=>[item.group_key,item]));for(const group of data.items){const prior=merged.get(group.group_key);if(prior&&stable(prior)!==stable(group))throw Object.assign(Error('创意目录出现不一致内容，请重新载入目录'),{code:'marketing_catalog_changed'});if(!prior)merged.set(group.group_key,group);}
      c.H=data.catalog_sha256;c.categories=data.categories;c.items=[...merged.values()];c.next=data.next_page;c.total=data.total_available;c.lastPageCount=data.items.length;c.loaded=true;c.feedback.replaceChildren();renderCaseFilters(s,c);renderCases(s,c);if(pageScroll!=null)root.scrollTop=pageScroll;
    }catch(error){if(caseLive(s,c,seq,stamp)){c.failed=true;c.feedback.replaceChildren(el('p',error.message));const changed=error.code==='marketing_catalog_changed'||error.status===409;c.feedback.append(caseButton(s,changed?'重新载入目录':'重试读取创意',()=>readCases(s,changed?1:page,changed||reset,changed,c)));}}
    finally{if(caseLive(s,c,seq,stamp)){c.loading=false;c.activeRead=null;if(pageScroll!=null)root.scrollTop=pageScroll;renderCasePager(s,c);}}
  }
  function renderCasePager(s,c=s.cases){
    if(!caseViewLive(s,c)||!c.pager)return;stopCaseObserver(c);c.pager.replaceChildren();if(c.summary)c.summary.textContent=c.loaded?`已显示 ${c.items.length} / ${c.total} 个创意`:'';
    if(!c.loaded||c.next==null||!c.lastPageCount||c.items.length>=c.total)return;
    const page=c.next,H=c.H,seq=c.requestSeq,render=c.renderSeq,stamp=caseScope(s),epoch=c.observerEpoch;
    const current=()=>caseLive(s,c,seq,stamp)&&c.renderSeq===render&&c.next===page&&c.H===H&&c.observerEpoch===epoch;
    const loadNext=()=>{if(current()&&!c.loading&&!s.busy&&!c.layoutPending)return readCases(s,page,false,false,c);};
    const b=caseButton(s,'加载更多创意',loadNext);b.disabled=c.loading||s.busy||c.layoutPending;c.pager.append(b);
    // Keep the keyboard/manual path even where observation is unsupported.
    if(c.loading||s.busy||c.failed||c.layoutPending||c.dialog||document.hidden||document.visibilityState==='hidden'||!globalThis.IntersectionObserver)return;
    const sentinel=el('div',null,'marketing-case-sentinel');sentinel.setAttribute('aria-hidden','true');c.sentinel=sentinel;c.pager.append(sentinel);
    const observer=new IntersectionObserver(entries=>{
      if(c.moreObserver!==observer||c.sentinel!==sentinel)return;
      if(!current()){stopCaseObserver(c);return;}
      if(!document.hidden&&entries.some(entry=>entry.target===sentinel&&entry.isIntersecting))return loadNext();
    },{root:c.scrollRoot||root,rootMargin:'160px',threshold:0});c.moreObserver=observer;observer.observe(sentinel);
  }
  function preview(s,video,poster,b,c,stamp,render,explicit=false,container=null){
    if(!caseViewLive(s,c)||document.hidden||document.visibilityState==='hidden'||caseScope(s)!==stamp||c.renderSeq!==render||!video.src||b.disabled)return;
    if(c.preview?.video===video){if(explicit)stopPreview(c);return;}
    for(const view of caseViews(s))stopPreview(view);video.hidden=false;if(poster)poster.hidden=true;if(container)container.hidden=false;b.textContent='暂停预览';c.preview={video,poster,button:b,container};
    try{Promise.resolve(video.play?.()).then(()=>{if(!live(s)||caseScope(s)!==stamp||c.renderSeq!==render||c.preview?.video!==video)video.pause?.();}).catch(()=>{if(c.preview?.video===video){stopPreview(c);b.textContent='预览暂不可用';}});}catch{stopPreview(c);b.textContent='预览暂不可用';}
  }
  function visual(s,spec,c,render,stamp){
    const requestSeq=c.requestSeq;
    const cover=el('div',null,'marketing-case-cover'),image=el('img'),url=caseMediaURL(spec,'cover');image.alt=spec.video_name||spec.group_name;image.loading='lazy';image.referrerPolicy='no-referrer';image.crossOrigin='anonymous';if(url)image.src=url;else image.hidden=true;cover.append(image);
    cover.style.aspectRatio=`${spec.width} / ${spec.height}`;const video=el('video'),play=caseButton(s,'播放预览',()=>{if(c.requestSeq===requestSeq)preview(s,video,image,play,c,stamp,render,true);},'marketing-case-play');video.muted=true;video.loop=true;video.playsInline=true;video.preload='none';video.crossOrigin='anonymous';video.hidden=true;
    const source=caseMediaURL(spec,'video');if(source)video.src=source;else play.disabled=true;video.onerror=()=>{if(caseViewLive(s,c)&&c.renderSeq===render&&caseScope(s)===stamp){if(c.preview?.video===video)stopPreview(c);play.textContent='预览暂不可用';}};image.onerror=()=>{if(caseViewLive(s,c)&&c.renderSeq===render&&caseScope(s)===stamp){image.hidden=true;cover.append(el('span','封面暂不可用','marketing-case-unavailable'));}};cover.append(video,play);return {cover,video,image,play};
  }
  function renderCases(s,c=s.cases){
    if(!caseViewLive(s,c)||!c.grid)return;stopCaseObserver(c);clearCasePreviews(c);c.masonry?.disconnect();c.layoutPending=true;const render=++c.renderSeq,requestSeq=c.requestSeq,stamp=caseScope(s),pin=s.pending?.request.payload.case_ref||s.draft.case;c.grid.replaceChildren();c.selectButtons=[];c.choices=[];c.displayed=new Map();
    for(const group of c.items){
      const spec=c.compact?group.examples[0]:group.examples.find(item=>samePin(item,pin))||group.examples[0];if(!spec)continue;c.displayed.set(group.group_key,spec.template_key);
      if(c.compact){
        const current=()=>caseViewLive(s,c)&&c.requestSeq===requestSeq&&c.renderSeq===render&&caseScope(s)===stamp,option=caseButton(s,'',()=>{if(current())selectCase(s,spec);},'marketing-case-option');option.setAttribute('aria-label','选择创意 '+group.group_name);option.dataset.groupKey=group.group_key;option.dataset.caseId=spec.id;
        const image=el('img');image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';image.crossOrigin='anonymous';const url=caseMediaURL(spec,'cover');if(url)image.src=url;const text=el('span',null,'marketing-case-option-copy');text.append(el('span',group.group_name,'marketing-case-option-name'),el('span',group.group_description,'marketing-case-option-description'));const check=el('span','✓','marketing-case-option-check');check.setAttribute('aria-hidden','true');option.append(image,text,check);option.disabled=Boolean(s.pending||s.busy);c.grid.append(option);c.selectButtons.push(option);c.choices.push({node:option,button:option,group,check});
        let previewBox=null,media=null;const show=()=>{if(!current()||!caseMediaURL(spec,'video')||globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;if(!previewBox){previewBox=el('div',null,'marketing-picker-preview');media=visual(s,spec,c,render,stamp);previewBox.append(media.cover);previewBox.hidden=true;root.append(previewBox);c.previewBoxes.push(previewBox);}const box=option.getBoundingClientRect(),width=globalThis.window?.innerWidth||globalThis.innerWidth||1024,height=globalThis.window?.innerHeight||globalThis.innerHeight||768;previewBox.style.left=Math.max(12,Math.min(box.right+8,width-262))+'px';previewBox.style.top=Math.max(12,Math.min(box.top,height-460))+'px';preview(s,media.video,media.image,media.play,c,stamp,render,false,previewBox);};option.onpointerenter=e=>{if(e.pointerType==='mouse'&&globalThis.matchMedia?.('(hover: hover) and (pointer: fine)').matches)show();};option.onpointerleave=()=>stopPreview(c);option.onfocus=show;option.onblur=()=>stopPreview(c);continue;
      }
      const card=el('article',null,'marketing-case-card');card.dataset.groupKey=group.group_key;card.dataset.caseId=spec.id;card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label','查看 '+group.group_name+' 的创意详情');
      const v=visual(s,spec,c,render,stamp);card.append(v.cover,el('h3',group.group_name),el('p',group.group_description,'marketing-case-description'));
      const current=()=>caseViewLive(s,c)&&c.requestSeq===requestSeq&&c.renderSeq===render&&caseScope(s)===stamp;card.onclick=()=>{if(current())return openCase(s,spec,{trigger:card,group,view:c});};card.onkeydown=e=>{if(current()&&e.target===card&&['Enter',' '].includes(e.key)){e.preventDefault();return openCase(s,spec,{trigger:card,group,view:c});}};
      const choose=caseButton(s,'复刻',()=>{if(current())selectCase(s,spec);},'marketing-case-select');choose.disabled=Boolean(s.pending||s.busy);c.selectButtons.push(choose);card.append(choose);
      c.choices.push({node:card,button:choose,spec,label:'复刻'});
      if(group.examples.length>1){const select=el('select');select.setAttribute('aria-label','切换 '+group.group_name+' 的案例');for(const item of group.examples)select.append(option(item.template_key,item.video_name));select.value=spec.template_key;select.disabled=Boolean(s.pending||s.busy);c.selectButtons.push(select);select.onclick=e=>e.stopPropagation();select.onchange=e=>{e?.stopPropagation?.();if(!current()||s.pending||s.busy){select.value=spec.template_key;return;}const selected=group.examples.find(item=>item.template_key===select.value);if(selected)selectCase(s,selected);};card.append(select);}
      card.onpointerenter=e=>{if(current()&&(!e.pointerType||e.pointerType==='mouse')&&globalThis.matchMedia?.('(hover: hover) and (pointer: fine)').matches&&!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches)preview(s,v.video,v.image,v.play,c,stamp,render);};card.onpointerleave=()=>{if(c.preview?.video===v.video)stopPreview(c);};c.grid.append(card);
    }
    syncCaseSelection(s,c);if(c.compact){c.layoutPending=false;if(c.loaded&&!c.items.length)c.grid.append(el('p','暂无匹配创意，请调整分类或关键词。','marketing-ideas-empty'));renderCasePager(s,c);return;}
    if(c.loaded&&!c.items.length)c.grid.append(el('p','暂无匹配创意，请调整分类或关键词。','marketing-ideas-empty'));
    const fit=(refresh=true)=>{if(!caseViewLive(s,c)||c.renderSeq!==render||caseScope(s)!==stamp)return;const cards=[...c.grid.children].filter(n=>n.className.split(' ').includes('marketing-case-card')),heights=cards.map(n=>n.offsetHeight||0);c.layoutPending=Boolean(cards.length)&&(!c.grid.clientWidth||heights.some(h=>h<=0));if(!c.layoutPending)cards.forEach((n,i)=>n.style.gridRowEnd='span '+Math.ceil((heights[i]+18)/8));if(refresh)renderCasePager(s,c);};fit(false);if(globalThis.ResizeObserver){c.masonry=new ResizeObserver(()=>fit());c.masonry.observe(c.grid);for(const card of c.grid.children)c.masonry.observe(card);}renderCasePager(s,c);
  }
  async function openCase(s,spec,{trigger=null,group=null,historical=false,view=s.cases}={}){
    const c=view;if(!caseViewLive(s,c))return;prepareSurface(s,'case');if(!c.compact)closePicker(s,false);for(const owner of caseViews(s))stopPreview(owner);stopCaseObserver(c);closeCase(s,false,c);rememberPromptRange(s);const seq=++c.detailSeq,requestSeq=c.requestSeq,stamp=caseScope(s),H=c.H,render=c.renderSeq;c.trigger=trigger;
    const dialog=el('dialog',null,'marketing-case-dialog');c.dialog=dialog;dialog.setAttribute('aria-label',spec.group_name);const close=caseButton(s,'×',()=>closeCase(s,true,c),'marketing-case-dialog-close');close.setAttribute('aria-label','关闭创意详情');dialog.append(close,el('h2',spec.group_name));
    const v=visual(s,spec,c,render,stamp);dialog.append(v.cover,el('p',spec.group_description,'marketing-case-full-description'),el('p','仅选择创意参考，不会导入案例视频。','marketing-case-basis'));
    if(group?.examples.length>1){const select=el('select');select.setAttribute('aria-label','切换详情案例');for(const item of group.examples)select.append(option(item.template_key,item.video_name));select.value=spec.template_key;select.onchange=()=>{const selected=group.examples.find(item=>item.template_key===select.value);return openCase(s,selected,{trigger,group,view:c});};dialog.append(select);}
    let resolved=historical?spec:null;const feedback=el('p',historical?'已保留所选创意内容。':'正在读取创意详情…','marketing-case-detail-status');dialog.append(feedback);const choose=caseButton(s,'选择此创意',()=>{if(resolved&&choose.caseReady&&c.dialog===dialog&&c.detailSeq===seq&&c.requestSeq===requestSeq&&caseScope(s)===stamp)selectCase(s,resolved);},'marketing-case-detail-select');choose.caseReady=historical;choose.disabled=!choose.caseReady||Boolean(s.pending||s.busy);c.detailChoice={button:choose,spec};c.selectButtons.push(choose);dialog.append(choose);dialog.oncancel=e=>{e.preventDefault();closeCase(s,true,c);};dialog.onclose=()=>{if(c.dialog===dialog)closeCase(s,true,c);};root.append(dialog);dialog.showModal();syncCaseSelection(s,c);
    if(historical)return;
    try{const data=await ctx.api('/api/v1/marketing-cases/'+encodeURIComponent(spec.id)+'?'+new URLSearchParams({version:String(spec.version),sha256:spec.sha256}));if(!caseViewLive(s,c)||c.dialog!==dialog||c.detailSeq!==seq||c.requestSeq!==requestSeq||caseScope(s)!==stamp||c.H!==H)return;
      if(data.catalog_sha256!==H||stable(data.case)!==stable(spec))throw Error('创意目录已变化，当前选择内容已保留，请重新载入目录后再选。');resolved=data.case;choose.caseReady=true;choose.disabled=Boolean(s.pending||s.busy);feedback.textContent='';
    }catch(error){if(caseViewLive(s,c)&&c.dialog===dialog&&c.detailSeq===seq&&c.requestSeq===requestSeq&&caseScope(s)===stamp){resolved=null;choose.caseReady=false;feedback.textContent=error.message;choose.disabled=true;}}
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
        const payload={prompt,episode_id:s.draft.episode_id||null,method_id:method?.id||null,...(method?{method_version:method.version,method_sha256:method.sha256}:{}),media_ids:s.draft.media.map(m=>m.id),...(s.draft.case?{case_ref:casePin(s.draft.case)}:{})};
        s.pending={actor:s.actor,project:s.project,intent:freezeIntent(s),...(s.draft.case?{case_display:copy(s.draft.case)}:{}),request:{payload,expected_revision:s.revision,idempotency_key:crypto.randomUUID()}};remember(requestKey(s),s.pending);
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
        restoreCaseDisplay(s,pending,canvas);
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
  function restoreCaseDisplay(s,pending,canvas){
    if(!pending.request.payload.case_ref||pending.case_display)return;
    const params=canvas.document?.nodes?.find(n=>n.id==='marketing-brief')?.params;if(!params||!CASE_FIELDS.every(k=>Object.hasOwn(params,'marketing_case_'+k)))return;
    const spec=Object.fromEntries(CASE_FIELDS.map(k=>[k,params['marketing_case_'+k]]));if(!samePin(spec,pending.request.payload.case_ref))return;
    pending.case_display=spec;s.draft.case=copy(spec);remember(requestKey(s),pending);save(s);update(s);
  }
  function suspend(){if(!state)return;save(state);closeMethodPicker(state);closePicker(state,false);for(const c of caseViews(state)){stopCaseObserver(c);clearCasePreviews(c);closeCase(state,false,c);clearTimeout(c.debounce);c.masonry?.disconnect();c.requestSeq++;}state.caseCleanup?.();state.disposed=true;state.upload?.suspend();state.runScope?.dispose();}
  async function load(scope={}){
    suspend();const actor=auth().actor||'',choice=recall(key('project',actor));
    const p=scope.project!==undefined?scope.project:(choice?.project||null),s={actor,project:p||null,disposed:false,sequence:++sequence,revision:null,options:null,busy:false,mediaSequence:0};state=s;
    const draft=recall(draftKey(s))||scope.seed,date=mins=>{const now=new Date(Date.now()+mins*60000);return new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);};s.draft={prompt:draft?.prompt||'',method_id:draft?.method_id||'',episode_id:scope.episode??draft?.episode_id??'',media:Array.isArray(draft?.media)?draft.media:[],case:draft?.case||null,model_ids:draft?.model_ids||[],mode:draft?.mode||'manual',execution:{duration:'5',first_due:date(60),stop_at:date(120),max_jobs:'2',max_images:'2',max_video_seconds:'10',max_credits:'0',...draft?.execution}};
    s.pending=recall(requestKey(s))||null;
    if(s.pending?.actor!==actor||s.pending?.project!==s.project)s.pending=null;
    if(s.pending&&!s.pending.result&&s.pending.uncertain===undefined){s.pending.uncertain=true;remember(requestKey(s),s.pending);}
    if(s.pending){const payload=s.pending.request.payload,fixedCase=s.pending.case_display||s.draft.case;s.draft={...s.draft,prompt:payload.prompt,method_id:payload.method_id||'',episode_id:payload.episode_id||'',media:payload.media_ids.map(id=>s.draft.media.find(m=>m.id===id)||{id,name:id}),case:samePin(fixedCase,payload.case_ref)?fixedCase:null};}
    if(s.pending?.intent){s.draft.model_ids=[...s.pending.intent.model_ids];s.draft.mode=s.pending.intent.execution_settings.auto_media?'auto_media':s.pending.intent.mode;}
    remember(key('project',actor),{project:s.project});draw(s);
    const hidden=()=>{for(const c of caseViews(s))if(document.hidden||document.visibilityState==='hidden'){stopCaseObserver(c);stopPreview(c);}else if(caseViewLive(s,c))renderCasePager(s,c);};const leaving=()=>{closeMethodPicker(s);closePicker(s,false);for(const c of caseViews(s)){stopCaseObserver(c);stopPreview(c);closeCase(s,false,c);}},offLocale=onLocaleChange(()=>{rebindCaseLocale(s);update(s);});document.addEventListener?.('visibilitychange',hidden);globalThis.window?.addEventListener?.('pagehide',leaving);globalThis.window?.addEventListener?.('popstate',leaving);s.caseCleanup=()=>{offLocale();document.removeEventListener?.('visibilitychange',hidden);globalThis.window?.removeEventListener?.('pagehide',leaving);globalThis.window?.removeEventListener?.('popstate',leaving);};
    if(!s.project){note(s,'请选择归属项目后继续。');return;}
    note(s,'正在读取营销技能与项目…');
    try{
      const options=await ctx.api(endpoint(s.project,'marketing-options'));if(!live(s))return;
      s.options=options;revision(s,options.revision);
      if(!s.pending){if(!options.methods.some(m=>m.id===s.draft.method_id))s.draft.method_id='';if(!options.episodes.some(e=>e.id===s.draft.episode_id))s.draft.episode_id='';s.draft.model_ids=s.draft.model_ids.filter(id=>options.models.some(m=>m.id===id&&m.enabled));save(s);}
      draw(s);
      if(s.pending?.request.payload.case_ref&&!s.pending.case_display&&s.pending.result){const pending=s.pending,result=pending.result,canvas=await ctx.api(endpoint(s.project,'creative-canvases/'+encodeURIComponent(result.canvas_id||result.id)+'?version='+encodeURIComponent(result.canvas_revision)));if(!live(s)||s.pending!==pending)return;if(canvas.canvas_revision===result.canvas_revision&&canvas.sha256===result.sha256)restoreCaseDisplay(s,pending,canvas);}
    }catch(error){if(live(s)){s.error=error.message;draw(s);s.status.append(button(s,'重试读取项目',()=>load({project:s.project})));}}
  }
  return {load,suspend};
}
