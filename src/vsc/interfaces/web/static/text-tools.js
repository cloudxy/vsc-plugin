// Six tools keep manual drafts separate from fixed host results and original imports.
import {createRunScopeControls} from './run-scope-controls.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const clone=v=>JSON.parse(JSON.stringify(v));
const labels={source_text:'固定原文或转录',source_refs:'固定来源',notes:'工作备注',synopsis:'故事梗概',characters:'人物小传',outline:'分集大纲',scenes:'场景计划',body:'人工正文',qa_notes:'正文检查意见',chapter_start:'起始章',chapter_end:'结束章',target_episodes:'目标集数',target_language:'目标语言',style:'翻译风格',style_version_id:'固定风格版本',style_request:'此次提出翻译风格建议（不翻译正文）',check_ranges:'局部复检区间（空为整片）',base_report_version_id:'局部复检基线版本',terms:'术语、译名与别名',reference_version_ids:'精校参考集版本（每行一个）',proofread:'本集译文已人工精校',analysis:'分析意见',channel:'频道',card_start:'首卡起始集',card_end:'首卡结束集',criteria:'评分标准',scores:'评分结果',review_decision:'人工复核结论',review_reason:'人工复核理由',media_id:'源视频 ID',observations:'带时码观察',videos:'检查视频',subtitles:'字幕原文',matches:'显式字幕匹配',checks:'本地检查项',issues:'逐项检查结果',source_media_id:'源视频 ID',understanding:'内容理解',entities:'实体与本地化映射',groups:'视频分组与候选',segments:'组内镜头映射'};
const columns={rule:'规则',name:'名称',description:'描述',source:'源词',target:'译名',aliases:'别名',key:'稳定标识',label:'标准',max_score:'满分',weight:'权重',score:'得分',evidence:'依据',reason:'理由',start_ms:'开始毫秒',end_ms:'结束毫秒',kind:'观察类型',text:'正文',media_id:'媒体 ID',sha256:'固定摘要',filename:'字幕文件名',video_id:'视频 ID',subtitle_name:'字幕文件名',code:'检查项',severity:'级别',message:'问题',localized:'本地化内容',asset_id:'资产身份 ID',group:'所属组',source_start_ms:'源片起点毫秒',source_end_ms:'源片终点毫秒',candidate_media_id:'明确选择的候选视频 ID',candidate_in_ms:'候选起点毫秒',localized_text:'本地化镜头内容'};
const statuses={running:'运行中或等待回执',completed:'结果已保存，待比较',failed:'本次失败，原稿保留',submission_unknown:'结果未知，不自动重试'};
Object.assign(labels,{understanding_version_id:'改写所依据的已批准理解版本'});
Object.assign(columns,{kind:'实体类型',source_text:'源片人工观察（事实与不确定项）',entity_keys:'角色 UID（英文逗号分隔）',scene_key:'场景 UID',target_duration_ms:'目标生成时长毫秒（0沿用源时长）',target_start_ms:'目标组内起点毫秒',target_end_ms:'目标组内终点毫秒',shot_id:'原项目镜头 ID',prompt:'分组改写提示词',first_frame_media_id:'原首帧图片 ID'});
export function createTextTools(root,ctx){
  let epoch=0,scope=null,tool='novel',caps=null,list=[],current=null,dirty=false,options={episodes:[],assets:[],media:[]};
  const retained=new Map(),pending=new Map(),selected=new Set(),attemptKeys=new Map();let scoreFilter='all',scoreOrder='ordinal',runControls=[];const workspaceTabs=new Map();
  const session=()=>ctx.session(),base=p=>'/api/v1/projects/'+encodeURIComponent(p);
  const alive=(n,s)=>n===epoch&&s===scope;
  const formKey=()=>String(session().actor||'')+':'+scope.project+':'+tool+':'+(current?.id||'new');
  function notice(error){ctx.notice(error.message||String(error));}
  function button(title,fn,disabled=false){const b=el('button',title);b.type='button';b.disabled=disabled;b.addEventListener('click',async()=>{try{await fn();}catch(error){notice(error);}});return b;}
  function field(parent,title,input){const n=el('label',title);input.setAttribute('aria-label',title);n.append(input);parent.append(n);return input;}
  function exports(version,formats){const box=el('div',null,'tt-actions');for(const format of formats){const a=el('a','下载 '+format.toUpperCase());a.href=base(scope.project)+'/text-tools/exports/'+encodeURIComponent(version)+'?format='+encodeURIComponent(format);box.append(a);}return box;}
  async function write(path,payload,k=formKey()+':'+path){
    const s=scope,n=epoch;
    if(!session().actor||!session().writable)throw new Error('请先建立可写人工会话');
    const signature=JSON.stringify({path,payload});let op=pending.get(k);
    if(op&&op.signature!==signature)throw new Error('上次提交回执未确认，请先恢复原请求。当前输入已保留。');
    if(!op){op={path,payload:clone(payload),signature,key:crypto.randomUUID(),revision:session().revision};pending.set(k,op);}
    try{
      const result=await ctx.api(base(s.project)+'/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:op.payload,expected_revision:op.revision,idempotency_key:op.key})});
      pending.delete(k);ctx.setRevision(Math.max(result.revision||0,session().revision||0),s.project);return result;
    }catch(error){if(error.status>=400&&error.status<500)pending.delete(k);throw error;}
  }
  async function listing(){const s=scope,n=epoch;const value=await ctx.api(base(s.project)+'/text-tools?tool='+tool);if(!alive(n,s))return false;list=value.items;ctx.setRevision(value.revision,s.project);return true;}
  async function open(id){
    const n=++epoch,s=scope;current=null;dirty=false;root.replaceChildren(el('p','正在读取固定工作稿…'));
    try{
      const value=id?await ctx.api(base(s.project)+'/text-tools/units/'+encodeURIComponent(id)):null;
      if(!alive(n,s))return;if(value&&value.tool!==tool){tool=value.tool;await listing();if(!alive(n,s))return;}current=value;dirty=retained.has(formKey());if(value)ctx.setRevision(value.revision,s.project);render();
    }catch(error){if(alive(n,s)){root.replaceChildren(el('p',error.message),button('重新读取',()=>open(id)));}}
  }
  function render(){
    for(const controls of runControls)controls.dispose();runControls=[];
    const s=scope,n=++epoch,editTool=tool;root.replaceChildren();root.classList.add('text-tools');root.dataset.tool=tool;selected.clear();
    const heading=el('header');heading.className='tt-heading';heading.append(el('h1',caps.tools[tool].label));root.append(heading);
    const tabs=el('nav',null,'tt-tabs');
    for(const [id,item]of Object.entries(caps.tools)){const b=button(item.label,async()=>{epoch++;tool=id;current=null;root.replaceChildren(el('p','正在切换工具…'));if(await listing())await open(null);});b.setAttribute('aria-pressed',String(tool===id));tabs.append(b);}root.append(tabs);
    root.append(el('p',caps.host.available?'文本宿主已安装，尚未在线验证。每次运行均需明确点击。':'当前没有可用文本宿主；可保存人工稿、执行本地检查和导出。','hint'));
    if(tool==='breakdown')root.append(el('p','自动视频理解尚未接入。可播放原视频、录入带时码观察，再让文本宿主整理所录内容。','tt-limitation'));
    if(tool==='qc')root.append(el('p','本机检查覆盖元数据、字幕时码和可选完整解码，不给出虚构审美或风险评分。','tt-limitation'));
    if(tool==='overseas')root.append(el('p','理解稿来自人工观察与转录，未接自动视觉识别。角色/场景按稳定 UID 引用；供应商专有资产注册仍待适配，已有图片可用原图生视频。','tt-limitation'));
    const layout=el('div',null,'tt-layout'),nav=el('aside',null,'tt-list'),main=el('section',null,'tt-main');layout.append(nav,main);root.append(layout);
    nav.append(button('新建工作单元',()=>open(null)),button('刷新列表与回执',async()=>{await listing();await open(current?.id);}));
    if(tool==='scoring'){
      const filter=field(nav,'按人工复核筛选',el('select'));for(const [id,label]of [['all','全部'],['pending','待复核'],['keep','保留'],['exclude','筛出']])filter.append(new Option(label,id));filter.value=scoreFilter;filter.onchange=()=>{scoreFilter=filter.value;render();};
      const order=field(nav,'列表排序',el('select'));order.append(new Option('单元顺序','ordinal'),new Option('当前加权归一分从高到低','score'));order.value=scoreOrder;order.onchange=()=>{scoreOrder=order.value;render();};
      nav.append(el('small','归一分按当前显式标准与权重计算；非原站算法。'));
    }
    const visible=tool==='scoring'?list.filter(r=>scoreFilter==='all'||r.review_decision===scoreFilter):list;
    if(tool==='scoring'&&scoreOrder==='score')visible.sort((a,b)=>(b.weighted_score??-1)-(a.weighted_score??-1));
    for(const row of visible){const line=el('div',null,'tt-unit'),check=el('input');check.type='checkbox';check.setAttribute('aria-label','选择合并 '+row.title);check.addEventListener('change',()=>check.checked?selected.add(row.current_version_id):selected.delete(row.current_version_id));line.append(check,button(row.title,()=>open(row.id)),el('small',row.group_key+' · 顺序 '+row.ordinal+(row.locked?' · 已锁定':'')+(row.weighted_score!=null?' · 当前归一分 '+row.weighted_score:'')));nav.append(line);}
    const mergeTitle=field(nav,'合并导出标题',el('input'));mergeTitle.value=caps.tools[tool].label;
    const merged=el('div');nav.append(button('按勾选列表顺序重新合并',async()=>{if(!selected.size)throw new Error('先勾选要合并的明确版本');const ids=list.filter(row=>selected.has(row.current_version_id)).map(row=>row.current_version_id);const result=await write('text-tools/merge',{tool,version_ids:ids,title:mergeTitle.value},s.project+':merge:'+tool);if(alive(n,s)){merged.replaceChildren(el('p','已固定合并版本；人工稿保持原样。'),exports(result.id,caps.tools[tool].formats));}}),merged);
    if(['novel','translation','scoring'].includes(tool))nav.append(importForm(s,n));
    const retainedValue=retained.get(formKey());
    const meta=retainedValue?.meta||{tool,group_key:current?.group_key||'main',unit_key:current?.unit_key||crypto.randomUUID().slice(0,8),title:current?.title||'',ordinal:current?.ordinal??list.length,episode_id:current?.episode_id||null};
    const document=clone(retainedValue?.document||current?.document||{...caps.common,...caps.defaults[tool]});
    const thisKey=formKey();let captureKey=thisKey;
    const form=el('form');main.append(form);const controls={},rowEditors=[];
    const status=el('p',current?'稿次 '+current.version+(current.locked?' · 已锁定':dirty?' · 未保存修改':' · 已保存'):'新单元尚未保存','tt-status');status.setAttribute('role','status');form.append(status);
    for(const [key,title]of [['title','单元名称'],['group_key','工作组'],['ordinal','顺序']]){const input=field(form,title,el('input'));input.value=String(meta[key]);input.required=true;if(key==='ordinal'){input.type='number';input.min='0';}if(key==='group_key'&&current)input.disabled=true;controls['meta:'+key]=input;}
    const episode=field(form,'关联集',el('select'));episode.append(new Option('项目级单元',''));for(const row of options.episodes)episode.append(new Option(row.title||row.display_code,row.id));episode.value=meta.episode_id||'';episode.disabled=Boolean(current);controls['meta:episode_id']=episode;
    const mediaList=el('datalist');mediaList.id='tt-media-options';for(const row of options.media){const option=el('option');option.value=row.id;option.label=row.name;mediaList.append(option);}form.append(mediaList);
    const assets=el('datalist');assets.id='tt-asset-options';for(const row of options.assets){const option=el('option');option.value=row.id;option.label=row.title||row.display_code;assets.append(option);}form.append(assets);
    if(['qc','breakdown','overseas'].includes(tool)){const finder=field(form,'按名称搜索项目素材',el('input'));const refresh=button('搜索素材',async()=>{const value=await ctx.api(base(s.project)+'/media?modality=video&limit=200&query='+encodeURIComponent(finder.value));if(!alive(n,s))return;mediaList.replaceChildren();for(const row of value.items){const option=el('option');option.value=row.id;option.label=row.name;mediaList.append(option);}ctx.notice('已找到 '+value.total+' 项，输入框可选择前200项。');});form.append(refresh,button('批量导入新素材',()=>ctx.navigate('media-imports',meta.episode_id,s.project)));}

    if(tool==='qc'){
      const videoChoice=field(form,'批量选择项目视频',el('select'));videoChoice.multiple=true;videoChoice.size=5;for(const row of options.media)videoChoice.append(new Option(row.name,row.id));
      form.append(button('添加选中视频到检查列表',()=>{for(const option of videoChoice.selectedOptions)if(!document.videos.some(r=>r.media_id===option.value))document.videos.push({media_id:option.value,name:option.textContent,sha256:''});capture();render();}));
      const subtitleFiles=field(form,'批量读取SRT字幕',el('input'));subtitleFiles.type='file';subtitleFiles.accept='.srt';subtitleFiles.multiple=true;
      form.append(button('添加所选字幕原文',async()=>{const items=[...subtitleFiles.files];if(!items.length)throw new Error('请选择SRT文件');const loaded=[];for(const file of items){if(file.size>2_000_000)throw new Error('单个字幕超过2MB');loaded.push({filename:file.name,text:await file.text()});}if(!alive(n,s))return;for(const row of loaded){if(document.subtitles.some(r=>r.filename===row.filename))throw new Error('字幕文件名已存在：'+row.filename);}document.subtitles.push(...loaded);capture();render();}));
    }
    for(const [key,defaultValue]of Object.entries({...caps.common,...caps.defaults[tool]})){
      if(key==='source_refs'){const refs=el('details');refs.append(el('summary','固定来源版本'));for(const ref of document.source_refs||[])refs.append(el('p',ref.kind+' · '+ref.id+' · '+(ref.sha256||'')));form.append(refs);continue;}
      if(Array.isArray(defaultValue)&&caps.rows[key]){
        const block=el('details',null,'tt-table');block.open=['terms','criteria','videos','groups','observations'].includes(key);block.append(el('summary',labels[key]||key));
        const rows=el('div');block.append(rows);form.append(block);
        function paint(){
          rows.replaceChildren();
          for(const [index,row]of document[key].entries()){
            const item=el('fieldset');item.append(el('legend',(labels[key]||key)+' '+(index+1)));
            for(const [col,type]of Object.entries(caps.rows[key])){const input=field(item,columns[col]||col,el(type==='text'&&['text','source_text','prompt','description','message','evidence','localized_text','reason'].includes(col)?'textarea':'input'));input.value=String(row[col]??'');if(['media_id','candidate_media_id','video_id'].includes(col))input.setAttribute('list','tt-media-options');if(col==='asset_id')input.setAttribute('list','tt-asset-options');if(['positive','nonnegative','number'].includes(type)){input.type='number';input.step=type==='number'?'any':'1';input.min=type==='positive'?'1':'0';}if(col==='sha256'||tool==='overseas'&&col==='key'&&current?.document[key]?.some(r=>r.key===row.key))input.readOnly=true;input.addEventListener('input',()=>{row[col]=['positive','nonnegative','number'].includes(type)?Number(input.value):input.value;capture();});}
            item.append(button('上移此行',()=>{[document[key][index-1],document[key][index]]=[document[key][index],document[key][index-1]];capture();paint();},index===0),button('删除此行',()=>{document[key].splice(index,1);capture();paint();}));rows.append(item);
          }
        }
        block.append(button('添加'+(labels[key]||key),()=>{document[key].push(Object.fromEntries(Object.entries(caps.rows[key]).map(([col,type])=>[col,type==='positive'?1:['number','nonnegative'].includes(type)?0:type==='key'?crypto.randomUUID().slice(0,8):''])));capture();paint();}));paint();continue;
      }
      if(key==='checks'){const box=el('fieldset');box.append(el('legend',labels[key]));for(const [code,title]of [['metadata','元数据'],['subtitles','字幕时码'],['decode','完整解码']]){const input=el('input');input.type='checkbox';input.checked=document.checks.includes(code);field(box,title,input);input.addEventListener('change',()=>{document.checks=input.checked?[...new Set([...document.checks,code])]:document.checks.filter(v=>v!==code);capture();});}form.append(box);continue;}
      if(key==='style_version_id'){
        const chooser=field(form,labels[key],el('select'));chooser.append(new Option('不固定风格库版本（可编辑风格正文）',''));for(const item of options.styles||[])chooser.append(new Option(`${item.title} · v${item.version} · ${item.language}`,item.id));chooser.value=document[key]||'';controls[key]=chooser;
        chooser.addEventListener('change',()=>{const selected=(options.styles||[]).find(x=>x.id===chooser.value);if(selected){document.style=selected.content;controls.style.value=selected.content;}capture();});continue;
      }
      if(key==='understanding_version_id'){
        const chooser=field(form,labels[key],el('select'));chooser.append(new Option('先提交理解固定版并在原审阅中批准',''));for(const item of current?.overseas?.baselines||[])if(item.phase==='understanding'&&item.approved)chooser.append(new Option('理解 v'+item.version+' · '+item.id,item.id));chooser.value=document[key]||'';controls[key]=chooser;continue;
      }
      if(key==='reference_version_ids'){const input=field(form,labels[key],el('textarea'));input.rows=3;input.value=document[key].join('\n');controls[key]=input;continue;}
      if(key==='review_decision'){const input=field(form,labels[key],el('select'));for(const [code,title]of [['pending','待复核'],['keep','保留'],['exclude','筛出']])input.append(new Option(title,code));input.value=document[key];controls[key]=input;continue;}
      const input=field(form,labels[key]||key,el(typeof defaultValue==='string'&&!['target_language','channel','media_id','source_media_id'].includes(key)?'textarea':'input'));
      if(typeof defaultValue==='boolean'){input.type='checkbox';input.checked=document[key];}
      else{input.value=String(document[key]??'');if(typeof defaultValue==='number'){input.type='number';input.min='1';}else if(input.tagName==='TEXTAREA')input.rows=['source_text','body'].includes(key)?8:3;}
      if(['media_id','source_media_id'].includes(key))input.setAttribute('list','tt-media-options');
      controls[key]=input;
    }
    function capture(){
      if(!alive(n,s))return;
      for(const [key,input]of Object.entries(controls)){
        if(key.startsWith('meta:')){const k=key.slice(5);meta[k]=k==='ordinal'?Number(input.value):k==='episode_id'?(input.value||null):input.value;continue;}
        const def=caps.defaults[editTool][key]??caps.common[key];
        document[key]=key==='reference_version_ids'?input.value.split('\n').map(v=>v.trim()).filter(Boolean):typeof def==='boolean'?input.checked:typeof def==='number'?Number(input.value):input.value;
      }
      dirty=true;retained.set(captureKey,{meta:clone(meta),document:clone(document)});status.textContent='有未保存修改；请先保存再运行、导出或导入。';
    }
    form.addEventListener('input',capture);form.addEventListener('change',capture);
    if(tool==='translation'){
      const chooser=field(form,'当前项目精校参考版本',el('select'));chooser.append(new Option('选择明确精校过的集',''));
      ctx.api(base(s.project)+'/text-tools?tool=translation').then(value=>{if(!alive(n,s))return;for(const unit of value.items.filter(r=>r.proofread))chooser.append(new Option(unit.title+' · '+unit.current_version_id,unit.current_version_id));}).catch(notice);
      form.append(button('添加固定精校参考',()=>{if(chooser.value&&!document.reference_version_ids.includes(chooser.value)){document.reference_version_ids.push(chooser.value);controls.reference_version_ids.value=document.reference_version_ids.join('\n');capture();}}));
      const styles=el('fieldset');styles.append(el('legend','版本化翻译风格库'));
      const styleTitle=field(styles,'风格名称',el('input')),styleLanguage=field(styles,'风格语言',el('input'));styleLanguage.value=document.target_language||'中文';
      const saveStyle=async(update)=>{const chosen=(options.styles||[]).find(x=>x.id===controls.style_version_id.value);if(update&&!chosen)throw new Error('先选择需要修订的固定风格版本');const result=await write('text-tools/styles',{style_id:update?chosen.style_id:null,base_version_id:update?chosen.id:null,title:styleTitle.value||chosen?.title||'',language:styleLanguage.value,content:controls.style.value},thisKey+':style');if(!alive(n,s))return;const listing=await ctx.api(base(s.project)+'/text-tools/styles');if(!alive(n,s))return;options.styles=listing.items;document.style_version_id=result.id;controls.style_version_id.append(new Option((styleTitle.value||chosen?.title)+' · 新版本',result.id));controls.style_version_id.value=result.id;capture();ctx.notice('风格版本已保存；请保存当前译文稿以固定采用。');};
      styles.append(button('将当前风格另存到库',()=>saveStyle(false)),button('修订所选风格为新版本',()=>saveStyle(true)));form.append(styles);

    }
    const save=el('button','保存人工稿');save.type='submit';save.disabled=Boolean(current?.locked)||!session().writable;form.append(save);
    form.addEventListener('submit',async event=>{event.preventDefault();capture();save.disabled=true;const submitted=JSON.stringify(retained.get(thisKey));const payload={...meta,document:clone(document),unit_id:current?.id||null,base_version_id:current?.current_version_id||null};try{const result=await write('text-tools/units',payload,thisKey);const newer=retained.get(thisKey);retained.delete(thisKey);captureKey=thisKey.slice(0,thisKey.lastIndexOf(':')+1)+result.unit_id;if(newer&&JSON.stringify(newer)!==submitted)retained.set(thisKey.slice(0,thisKey.lastIndexOf(':')+1)+result.unit_id,newer);if(alive(n,s)){await listing();await open(result.unit_id);ctx.notice(newer&&JSON.stringify(newer)!==submitted?'提交时的稿已保存，后续输入仍待保存。':'人工稿已保存。');}}catch(error){if(alive(n,s)){notice(error);save.disabled=false;}}});
    main.append(button('恢复上次提交回执',async()=>{const recovered=[...pending.entries()].find(([key])=>key===thisKey||key.startsWith(thisKey+':'));const op=recovered?.[1];if(!op){ctx.notice('当前单元没有待恢复请求。');return;}const result=await write(op.path,op.payload,recovered[0]);if(alive(n,s)){if(result.unit_id&&op.path==='text-tools/units'){const newer=retained.get(thisKey);retained.delete(thisKey);captureKey=thisKey.slice(0,thisKey.lastIndexOf(':')+1)+result.unit_id;if(newer&&(!['tool','group_key','unit_key','title','ordinal','episode_id'].every(k=>newer.meta[k]===op.payload[k])||JSON.stringify(newer.document)!==JSON.stringify(op.payload.document)))retained.set(thisKey.slice(0,thisKey.lastIndexOf(':')+1)+result.unit_id,newer);await listing();await open(result.unit_id);}else await open(current?.id);}}));
    if(!current){arrangeWorkspace(form,main,nav,controls,status,save);return;}
    if(['novel','translation','scoring'].includes(tool))renderProjectCopy(main,s,n);
    if(tool==='overseas')renderOverseas(main,s,n);
    main.append(button(current.locked?'解锁此单元':'停止新调用并锁定人工稿',async()=>{const id=current.id,locked=!current.locked;const latest=await ctx.api(base(s.project)+'/text-tools/units/'+encodeURIComponent(id));if(!alive(n,s))return;ctx.setRevision(latest.revision,s.project);const value=await write('text-tools/lock',{unit_id:id,locked});if(alive(n,s)){await listing();await open(current.id);ctx.notice(value.message);}}));
    const runPanel=el('section',null,'tt-run');runPanel.append(el('h2','固定输入的单次任务'));
    for(const [action,title]of Object.entries(caps.tools[tool].actions))runPanel.append(button(tool==='translation'&&current.document.style_request?'提出可复用翻译风格建议':title,async()=>{
      if(dirty)throw new Error('请先保存人工稿。');const id=current.id,version=current.current_version_id;
      const result=await write('text-tools/run',{unit_id:id,input_version_id:version,action,new_attempt:true});
      if(alive(n,s)){ctx.notice(statuses[result.status]||result.status);await open(id);}
    },current.locked||(!caps.host.available&&action!=='check')));main.append(runPanel);
    const readback=el('section');readback.append(el('h2','固定版本导出'),exports(current.current_version_id,caps.tools[tool].formats));main.append(readback);
    if(current.matching){const box=el('section');box.append(el('h2','字幕匹配预览'));for(const row of current.matching)box.append(el('p',row.subtitle_name+' · '+({matched:'唯一匹配',conflict:'有歧义，请在显式匹配中选择',unmatched:'没有匹配视频'}[row.status])+' · '+row.video_ids.join(', ')));main.append(box);}
    if(current.mapping){const box=el('section');box.append(el('h2','源片与组内区间'));for(const row of current.mapping)box.append(el('p',row.key+'：源 '+row.source_start_ms+'–'+row.source_end_ms+' ms → 组 '+row.group+' 内 '+row.group_start_ms+'–'+row.group_end_ms+' ms'));main.append(box);}
    if(['breakdown','overseas'].includes(tool)){const mid=current.document.media_id||current.document.source_media_id;if(mid){const video=el('video');video.controls=true;video.preload='metadata';video.src=base(s.project)+'/media/'+encodeURIComponent(mid)+'/content';video.style.maxWidth='100%';main.append(video);}}
    if(tool==='qc'){
      const quality=el('section');quality.append(el('h2','局部复检与证据'));
      quality.append(button('以当前已保存报告为局部复检基线',()=>{controls.base_report_version_id.value=current.current_version_id;capture();ctx.notice('已固定基线；填写复检区间并勾选规则，保存后运行本地检查。');}));
      current.document.issues.forEach((issue,index)=>{const row=el('div');row.append(el('p',`${issue.rule||issue.code} · ${issue.start_ms}–${issue.end_ms} ms · ${issue.message}`));row.append(button('生成此问题实际证据帧',async()=>{if(dirty)throw new Error('请先保存质检稿');const result=await write('text-tools/evidence',{version_id:current.current_version_id,issue_index:index},thisKey+':evidence:'+index);if(!alive(n,s))return;const img=el('img');img.src=base(s.project)+'/media/'+result.media_id+'/content';img.style.maxWidth='100%';row.append(img,el('small','源帧 '+result.receipt.selected_time_ms+' ms · '+result.sha256));}));quality.append(row);});
      const dest=field(quality,'字幕回流目标集',el('select'));dest.append(new Option('请选择集',''));for(const item of options.episodes)dest.append(new Option(item.title||item.display_code,item.id));dest.value=current.episode_id||'';
      const clip=field(quality,'目标剪辑片段',el('select'));clip.append(new Option('先读取目标片段',''));
      quality.append(button('读取目标集片段',async()=>{const edit=await ctx.api(base(s.project)+'/edit-workspace?episode_id='+encodeURIComponent(dest.value));if(!alive(n,s))return;clip.replaceChildren();for(const item of edit.current?.document.clips||[])clip.append(new Option(item.id+' · '+item.media_id,item.id));ctx.setRevision(edit.project_revision,s.project);}));
      const sub=field(quality,'采用的已校正字幕',el('select'));for(const item of current.document.subtitles)sub.append(new Option(item.filename,item.filename));const diff=el('div');
      quality.append(button('预览字幕回流差异',async()=>{if(dirty)throw new Error('先保存字幕校正稿');const request={version_id:current.current_version_id,episode_id:dest.value,clip_id:clip.value,subtitle_filename:sub.value};const preview=await ctx.api(base(s.project)+'/text-tools/subtitles-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});if(!alive(n,s))return;ctx.setRevision(preview.revision,s.project);diff.replaceChildren(el('pre',JSON.stringify(preview.plan,null,2)),button('确认替换该片段区间字幕',async()=>{if(dirty)throw new Error('输入已修改，请重新保存并预览');await write('text-tools/subtitles-apply',{request,preview_sha256:preview.preview_sha256});if(alive(n,s))ctx.navigate('editing',dest.value,s.project);}));}),diff);main.append(quality);
    }
    if(tool==='novel'){
      const novel=el('section');novel.append(el('h2','导入原分集、剧本工作稿与资产需求'),el('p','新建或更新一集工作稿；保留批准版本。人物名称只形成未解析需求，需显式映射才能复用资产身份。'));
      const episode=field(novel,'小说回流目标',el('select'));episode.append(new Option('明确新建一集',''));for(const item of options.episodes)episode.append(new Option('更新 '+(item.title||item.display_code),item.id));episode.value=current.episode_id||'';
      const work=field(novel,'新集所属作品',el('select'));for(const item of options.works||[])work.append(new Option(item.title||item.display_code,item.id));
      const code=field(novel,'新分集编号',el('input')),title=field(novel,'新分集标题',el('input')),ordinal=field(novel,'新分集序号',el('input'));ordinal.type='number';ordinal.value=String(options.episodes.length);title.value=current.title;
      const scene=field(novel,'需求所属场次',el('select'));scene.append(new Option('明确新建工作场次',''));for(const item of options.scenes||[])scene.append(new Option(item.title||item.display_code,item.id));
      const sceneTitle=field(novel,'新场次标题',el('input'));sceneTitle.value=current.title+' · 待校对';const mapping={};
      current.document.characters.forEach((item,index)=>{const select=field(novel,item.name+' 的资产映射',el('select'));select.append(new Option('保留为未解析人物需求',''));for(const asset of options.assets)select.append(new Option(asset.title||asset.display_code,asset.id));mapping[String(index)]=select;});
      const diff=el('div');novel.append(button('预览分集和资产需求差异',async()=>{if(dirty)throw new Error('请先保存人工正文');const request={unit_id:current.id,version_id:current.current_version_id,episode_id:episode.value||null,new_episode:episode.value?null:{work_id:work.value,display_code:code.value,title:title.value,ordinal:Number(ordinal.value)},scene_id:scene.value||null,new_scene_title:sceneTitle.value,asset_mapping:Object.fromEntries(Object.entries(mapping).map(([key,input])=>[key,input.value||null]))};const preview=await ctx.api(base(s.project)+'/text-tools/novel-import-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});if(!alive(n,s))return;ctx.setRevision(preview.revision,s.project);diff.replaceChildren(el('pre',JSON.stringify(preview.plan,null,2)),button('确认该分集工作稿与需求差异',async()=>{if(dirty)throw new Error('输入已变，请重新保存预览');const result=await write('text-tools/novel-import',{request,preview_sha256:preview.preview_sha256});if(alive(n,s)){ctx.notice('已进入原分集剧本工作稿与资产需求；未自动批准。');ctx.navigate('script',result.episode_id,s.project);}}));}),diff);main.append(novel);
    }
    renderAttempts(main,s,n);
    const importBox=el('section');importBox.append(el('h2',tool==='overseas'?'送入原剪辑工作稿':'导入原来源工作区'));
    const importEpisode=field(importBox,'目标集（出海必填）',el('select'));importEpisode.append(new Option('请选择目标集',''));for(const row of options.episodes)importEpisode.append(new Option(row.title||row.display_code,row.id));importEpisode.value=current.episode_id||scope.object||'';
    const target=el('div');importBox.append(button('预览新建或更新差异',async()=>{
      if(dirty)throw new Error('请先保存人工稿');const request={unit_id:current.id,version_id:current.current_version_id,...(tool==='overseas'?{episode_id:importEpisode.value}:{})};
      const value=await ctx.api(base(s.project)+'/text-tools/import-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});
      if(!alive(n,s))return;ctx.setRevision(value.revision,s.project);target.replaceChildren(el('p',value.plan.change==='update'?'将建立更新版本；原版本保留。':'将新建对应原工作区记录。'),el('pre',JSON.stringify(value.plan,null,2)),button('确认按此差异导入',async()=>{if(dirty)throw new Error('输入已改变，请先保存并重新预览');const result=await write('text-tools/import',{request,preview_sha256:value.preview_sha256});if(alive(n,s)){ctx.notice('已导入固定版本。');await ctx.navigate(tool==='overseas'?'editing':'source',tool==='overseas'?importEpisode.value:current.episode_id,s.project);}}));}),target);main.append(importBox);
    arrangeWorkspace(form,main,nav,controls,status,save);
  }
  function arrangeWorkspace(form,main,nav,controls,status,save){
    const identify=node=>['DETAILS','FIELDSET'].includes(node.tagName)?node.querySelector('summary,legend')?.textContent||'':node.querySelector('[aria-label]')?.getAttribute('aria-label')||'';
    const top=el('div',null,'tt-document-head'),meta=el('details',null,'tt-document-meta');meta.append(el('summary','工作单元设置与来源'));
    controls['meta:title'].placeholder='未命名工作单元';top.append(controls['meta:title'].parentElement,status,save);
    const children=[...form.children].filter(node=>node!==top),metaLabels=['工作组','顺序','关联集','固定来源版本','工作备注'];
    const panes=el('div',null,'tt-document-panes'),source=el('section',null,'tt-source-pane'),result=el('section',null,'tt-result-pane');
    const titles={novel:['原文章节','改编工作稿'],translation:['原文','译文'],scoring:['评分设置','剧本与分析'],breakdown:['视频解析','解析结果'],qc:['视频质检','质检结果'],overseas:['源片理解','本地化改写']};
    const [sourceTitle,resultTitle]=titles[tool]||['输入','工作稿'];source.append(el('h2',sourceTitle));result.append(el('h2',resultTitle));panes.append(source,result);
    const resultLabels=new Set(['人工正文','分析意见','评分结果','人工复核结论','人工复核理由','逐项检查结果','带时码观察','故事梗概','人物小传','分集大纲','场景计划','正文检查意见','内容理解','实体与本地化映射','视频分组与候选','组内镜头映射']);
    for(const node of children){if(node===status||node===save||node===controls['meta:title'].parentElement)continue;const label=identify(node);if(metaLabels.includes(label)||(tool==='qc'&&['固定原文或转录','局部复检基线版本'].includes(label))||node.tagName==='DATALIST'){meta.append(node);continue;}(resultLabels.has(label)?result:source).append(node);}
    source.append(meta);form.replaceChildren(top,panes);
    const tabs=el('nav',null,'tt-document-tabs');tabs.setAttribute('aria-label','工作稿视图');
    const sections=[...result.children].filter(node=>node.tagName!=='H2');
    const tabModes=['novel','translation','scoring','overseas'];
    if(tabModes.includes(tool)&&sections.length>1){
      const friendly={'人工正文':tool==='translation'?'译文':'剧本','故事梗概':'梗概','人物小传':'人物','分集大纲':'分集','场景计划':'场景','正文检查意见':'检查','评分结果':'评分','分析意见':'分析','人工复核结论':'复核','人工复核理由':'复核理由','实体与本地化映射':'角色与场景','视频分组与候选':'视频组','组内镜头映射':'镜头','内容理解':'理解'};
      const initial=workspaceTabs.get(tool)||(['novel','translation','scoring'].includes(tool)?'人工正文':identify(sections[0]));
      const activate=label=>{workspaceTabs.set(tool,label);for(const node of sections){node.hidden=identify(node)!==label;if(!node.hidden&&node.tagName==='DETAILS')node.open=true;}for(const b of tabs.children)b.setAttribute('aria-selected',String(b.dataset.label===label));};
      for(const node of sections){const label=identify(node);if(!label)continue;const tab=button(friendly[label]||label,()=>activate(label));tab.dataset.label=label;tab.setAttribute('role','tab');tabs.append(tab);}tabs.setAttribute('role','tablist');result.insertBefore(tabs,result.children[1]||null);activate(sections.some(x=>identify(x)===initial)?initial:identify(sections[0]));
    }
    for(const node of [controls.source_text,controls.body])if(node){node.placeholder=node===controls.source_text?'粘贴原文，或从左侧导入文件':'工作稿将在这里编辑；保存后可比较建议和导出';node.parentElement.classList.add('tt-writing');}
    if(tool==='qc'||tool==='breakdown'){
      const primary=tool==='qc'?'逐项检查结果':'带时码观察';for(const block of result.querySelectorAll('details'))if(block.querySelector('summary')?.textContent===primary)block.open=true;
      result.classList.add('tt-tabular-result');
    }
    const transfers=el('details',null,'tt-delivery');transfers.append(el('summary','导出、导入与版本操作'));
    for(const node of [...main.children])if(node!==form){if(node.classList.contains('tt-run')){source.append(node);continue;}if(node.classList.contains('tt-attempts')){result.append(node);continue;}if(node.tagName==='VIDEO'){source.insertBefore(node,source.children[1]||null);continue;}transfers.append(node);}
    main.append(transfers);
    const bulk=el('details',null,'tt-list-bulk');bulk.append(el('summary','合并与导入'));
    let afterUnits=false;for(const node of [...nav.children]){if(node.tagName==='LABEL'&&node.querySelector('[aria-label="合并导出标题"]'))afterUnits=true;if(afterUnits)bulk.append(node);}nav.append(bulk);
    if(!nav.querySelector('.tt-unit')){const empty=el('p','暂无工作单元','tt-list-empty');nav.insertBefore(empty,bulk);}
  }
  function renderOverseas(main,s,n){
    const unit=current,info=unit.overseas,box=el('section',null,'tt-overseas');main.append(box);
    const saved=()=>{if(dirty)throw new Error('请先保存当前工作稿，再固定版本或预览影响');};
    const preview=async(path,payload)=>{const value=await ctx.api(base(s.project)+'/text-tools/overseas/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload})});if(alive(n,s))ctx.setRevision(value.revision,s.project);return value;};
    const review=id=>ctx.openArtifact?ctx.openArtifact(id):ctx.navigate('artifacts',id,s.project);
    box.append(el('h2','理解与改写的独立确认版本'),el('p','先保存并提交理解版，在原产物审阅中批准；再选择该理解版本进行改写。改写版独立批准后可准备各组原运行方案。修改工作稿不会改写旧确认内容。'));
    for(const [phase,title]of [['understanding','提交理解固定版供原审阅'],['localization','提交改写固定版供原审阅']])box.append(button(title,async()=>{saved();const value=await write('text-tools/overseas/baseline',{unit_id:unit.id,version_id:unit.current_version_id,phase});if(alive(n,s))await review(value.id);},unit.locked));
    for(const baseline of info.baselines){const item=el('details');item.append(el('summary',(baseline.phase==='understanding'?'理解':'改写')+' v'+baseline.version+' · '+(baseline.approved?'原人工批准有效':'等待原人工审阅')),el('pre',JSON.stringify(baseline.document,null,2)),button('查看此固定版与原决定',()=>review(baseline.id)));box.append(item);}
    const mergeBox=el('section');mergeBox.append(el('h3','角色或场景合并影响'));
    const source=field(mergeBox,'合并来源 UID',el('select')),target=field(mergeBox,'保留目标 UID',el('select'));
    for(const entity of unit.document.entities){const title=(entity.kind==='scene'?'场景':'角色')+' · '+entity.name+' · '+entity.key;source.append(new Option(title,entity.key));target.append(new Option(title,entity.key));}
    if(target.options.length>1)target.selectedIndex=1;const impact=el('div');
    mergeBox.append(button('预览引用迁移影响',async()=>{saved();const request={unit_id:unit.id,version_id:unit.current_version_id,source_key:source.value,target_key:target.value},value=await preview('merge-preview',request);if(!alive(n,s))return;impact.replaceChildren(el('pre',JSON.stringify(value.plan.impact,null,2)),button('确认合并并迁移这些引用',async()=>{saved();await write('text-tools/overseas/merge',{request,preview_sha256:value.preview_sha256});if(alive(n,s)){ctx.notice('合并已保存新稿；旧确认版保留，请重新确认理解。');await open(unit.id);}}));}),impact);box.append(mergeBox);
    box.append(el('h2','逐组准备、恢复与选择候选'),el('p','只准备原制作运行。报价、批准和执行沿原生产入口；未知提交需恢复原任务，禁止自动新发。每组成功候选独立保留。'));
    for(const group of unit.document.groups){
      const card=el('section',null,'tt-group');card.dataset.groupKey=group.key;card.append(el('h3','分组 '+group.key),el('p',`源片 ${group.source_start_ms}–${group.source_end_ms} ms · 目标 ${group.target_duration_ms||group.source_end_ms-group.source_start_ms} ms · 原镜头 ${group.shot_id||'待映射'}`));box.append(card);
      const localization=field(card,'本组固定改写版 '+group.key,el('select'));for(const row of info.baselines.filter(r=>r.phase==='localization'&&r.approved))localization.append(new Option('改写 v'+row.version,row.id));if(localization.options.length)localization.selectedIndex=localization.options.length-1;
      const configuration=el('div');card.append(button('读取本组原制作配置 '+group.key,async()=>{saved();if(!group.shot_id)throw new Error('先在工作稿把组映射到原镜头');const value=await ctx.api(base(s.project)+'/classic-production?shot_id='+encodeURIComponent(group.shot_id));if(!alive(n,s))return;ctx.setRevision(value.revision,s.project);configuration.replaceChildren();
        const model=field(configuration,'本组视频模型 '+group.key,el('select'));for(const row of value.models.filter(r=>r.modality==='video'))model.append(new Option(row.name+(row.enabled?'':'（未启用）'),row.id));
        const mode=field(configuration,'本组制作模式 '+group.key,el('select'));for(const id of ['single','first_last','multi'])mode.append(new Option(value.modes[id].label,id));
        const last=field(configuration,'本组尾帧图片 '+group.key,el('select'));last.append(new Option('未选尾帧',''));const refs=field(configuration,'本组补充参考图片 '+group.key,el('select'));refs.multiple=true;
        for(const media of value.media.filter(r=>r.modality==='image')){last.append(new Option(media.name,media.id));refs.append(new Option(media.name,media.id));}
        const count=field(configuration,'本组候选数 '+group.key,el('input'));count.type='number';count.min='1';count.max='8';count.value='1';
        const history=info.groups.filter(r=>r.group_key===group.key),newAttempt=history.length>0;
        configuration.append(button(newAttempt?'明确为此组准备新尝试':'准备此组原制作草稿',async()=>{saved();const references=group.first_frame_media_id?[{role:'first_frame',media_id:group.first_frame_media_id}]:[];if(mode.value==='first_last'&&last.value)references.push({role:'last_frame',media_id:last.value});if(mode.value==='multi')references.push(...[...refs.selectedOptions].map(r=>({role:'reference_image',media_id:r.value})));const key=formKey()+':prepare:'+group.key;if(!attemptKeys.has(key))attemptKeys.set(key,crypto.randomUUID());const request={unit_id:unit.id,version_id:unit.current_version_id,localization_version_id:localization.value,group_key:group.key,settings:{mode:mode.value,model_id:model.value,count:Number(count.value),references},base_classic_draft_id:value.drafts.find(r=>r.document.mode===mode.value)?.id||null,attempt_key:attemptKeys.get(key),new_attempt:newAttempt};await write('text-tools/overseas/prepare',request,key);attemptKeys.delete(key);if(alive(n,s))await open(unit.id);}));
      }),configuration);
      const policyBox=el('details');policyBox.open=true;policyBox.append(el('summary','此组运行时限与额度'));const due=field(policyBox,'本组首稿期限 '+group.key,el('input')),stop=field(policyBox,'本组停止新提交 '+group.key,el('input'));due.type=stop.type='datetime-local';const local=d=>new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);due.value=local(new Date(Date.now()+45*60000));stop.value=local(new Date(Date.now()+60*60000));const cap=field(policyBox,'本组同用途最多尝试 '+group.key,el('input'));cap.type='number';cap.min='1';cap.max='8';cap.value='2';const controls=createRunScopeControls(policyBox,{api:ctx.api,session,projectId:s.project});runControls.push(controls);card.append(policyBox);
      for(const fixed of info.groups.filter(r=>r.group_key===group.key)){
        const entry=el('details');entry.open=true;entry.append(el('summary','固定组制作稿 '+fixed.id),button('查看原经典制作稿',()=>review(fixed.classic_draft_id)));const result=el('div');entry.append(result);card.append(entry);
        if(!fixed.runs.length)entry.append(button('预览本组原报价与运行 '+group.key,async()=>{saved();const request=controls.apply({group_draft_id:fixed.id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(cap.value),max_repair_rounds:1}}),value=await preview('run-preview',request);if(!alive(n,s))return;result.replaceChildren(el('pre',JSON.stringify(value.ready?{generation_quote:value.generation_quote,commerce_quote:value.commerce_quote,document:value.artifact.document}:value.gaps,null,2)));if(value.ready)result.append(button('保存本组运行方案供原批准',async()=>{saved();const out=await write('text-tools/overseas/propose',{request,preview_sha256:value.preview_sha256});if(alive(n,s))await review(out.id);}));}));
        for(const run of fixed.runs){entry.append(button('查看原运行、批准与执行 '+run.id.slice(0,8),()=>review(run.id)),el('p',run.approved?'原批准有效；执行状态以原任务为准':'原运行待审阅；尚无生成授权'));for(const job of run.jobs){entry.append(el('p','原任务 '+job.id+' · '+job.status));for(const output of job.outputs){if(job.status!=='succeeded')continue;const video=el('video');video.controls=true;video.preload='metadata';video.src=base(s.project)+'/media/'+encodeURIComponent(output.media_id)+'/content';video.style.maxWidth='100%';const offset=field(entry,'候选剪入毫秒 '+output.media_id,el('input'));offset.type='number';offset.min='0';offset.value='0';entry.append(video,button('选择此组候选 '+output.media_id.slice(0,8),async()=>{saved();await write('text-tools/overseas/select',{unit_id:unit.id,version_id:unit.current_version_id,group_draft_id:fixed.id,job_id:job.id,media_id:output.media_id,candidate_in_ms:Number(offset.value)});if(alive(n,s))await open(unit.id);}));}}}
      }
    }
  }
  function renderAttempts(main,s,n){
    const box=el('section',null,'tt-attempts');box.hidden=!current.attempts.length;box.append(el('h2','逐次结果与人工稿比较'));
    for(const attempt of current.attempts){const item=el('details');item.append(el('summary',(caps.tools[tool].actions[attempt.action]||attempt.action)+' · '+(statuses[attempt.status]||attempt.status)));
      if(['running','submission_unknown'].includes(attempt.status))item.append(button('读取已返回结果或恢复原尝试',async()=>{const id=current.id;await write('text-tools/recover',{attempt_id:attempt.id});if(alive(n,s))await open(id);}));
      if(attempt.error_code)item.append(el('p','失败原因：'+attempt.error_code));
      if(attempt.result){const grid=el('div',null,'tt-compare');for(const [field,after]of Object.entries(attempt.result.patch)){const part=el('section');part.append(el('h3',labels[field]||field),el('p','当前人工稿'),el('pre',typeof current.document[field]==='string'?current.document[field]:JSON.stringify(current.document[field],null,2)),el('p','本次建议'),el('pre',typeof after==='string'?after:JSON.stringify(after,null,2)));grid.append(part);}item.append(grid,button('接受此固定结果为新稿',async()=>{if(dirty)throw new Error('请先处理未保存修改');const id=current.id;await write('text-tools/accept',{attempt_id:attempt.id,base_version_id:current.current_version_id});if(alive(n,s)){await listing();await open(id);}},current.locked||attempt.input_version_id!==current.current_version_id));}
      box.append(item);
    }main.append(box);
  }
  function importForm(s,n){
    const importTool=tool;
    const detail=el('details',null,'tt-import');detail.append(el('summary','从TXT、DOCX、PDF拆章或分集'));
    const file=field(detail,'原文文件',el('input'));file.type='file';file.accept='.txt,.md,.docx,.pdf';
    const group=field(detail,'登记工作组',el('input'));group.value='import-'+new Date().toISOString().slice(0,10);
    const result=el('div');let extraction=null,chosen=null,staged=null,source=null;
    detail.append(button('提取并预览范围',async()=>{
      chosen=file.files?.[0];if(!chosen)throw new Error('请选择原文文件');if(chosen.size>10*1024*1024)throw new Error('本地解析最多10MiB');
      const bytes=new Uint8Array(await chosen.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      extraction=await ctx.api(base(s.project)+'/text-tools/extract',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:{content_base64:btoa(binary),format:chosen.name.split('.').pop().toLowerCase(),split:importTool==='novel'?'chapters':'episodes'}})});
      if(!alive(n,s))return;result.replaceChildren(el('p',extraction.units.length+' 个识别单元；可勾选范围，原文将作为固定来源登记。'));
      const pick=new Set(extraction.units.map((_,i)=>i));
      extraction.units.forEach((unit,index)=>{const check=el('input');check.type='checkbox';check.checked=true;check.addEventListener('change',()=>check.checked?pick.add(index):pick.delete(index));field(result,unit.title,check);});
      const progress=el('p');result.append(button('登记所选单元',async()=>{
        if(!pick.size)throw new Error('请至少选择一个单元');if(!group.value.trim())throw new Error('请输入工作组');
        if(!staged){staged=await ctx.api(base(s.project)+'/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(chosen.name),'X-CSRF-Token':session().csrf},body:chosen});}
        if(!alive(n,s))return;
        if(!source){source=await write('source-workspace/sources',{title:chosen.name,intent:importTool==='novel'?'novel':'screenplay',filename:chosen.name,format:chosen.name.split('.').pop().toLowerCase(),staged_upload:staged.staged_upload},s.project+':source:'+extraction.text_sha256);}
        if(!alive(n,s))return;
        for(const index of [...pick]){
          const unit=extraction.units[index],doc={...clone(caps.common),...clone(caps.defaults[importTool]),source_text:unit.source_text,source_refs:[{kind:'source',id:source.source_id||source.id,sha256:source.sha256}]};
          await write('text-tools/units',{tool:importTool,group_key:group.value.trim(),unit_key:'source-'+(source.source_id||source.id)+'-'+index,title:unit.title,ordinal:index,episode_id:null,document:doc,base_version_id:null},s.project+':import:'+source.id+':'+index);pick.delete(index);if(alive(n,s))progress.textContent='已登记 '+(extraction.units.length-pick.size)+' 个；成功记录会保留。';else return;
        }
        if(alive(n,s)){await listing();await open(null);}
      }),progress);
    }),result);return detail;
  }
  function renderProjectCopy(main,s,n){
    const box=el('details');box.append(el('summary','将固定文字稿导入另一个项目'));
    const target=field(box,'目标项目',el('select'));target.append(new Option('请选择目标项目',''));
    ctx.api('/api/v1/projects').then(value=>{if(!alive(n,s))return;for(const row of value.items)if(row.id!==s.project&&row.storage_policy==='postgres-series-v1'&&!row.read_only&&row.profile!=='vsc.text-tools')target.append(new Option(row.name,row.id));}).catch(notice);
    const previewBox=el('div');box.append(button('预览导入目标',async()=>{
      if(dirty)throw new Error('请先保存需要导入的工作稿');if(!target.value)throw new Error('请选择目标项目');
      const project=target.value,request={source_project_id:s.project,source_unit_id:current.id,source_version_id:current.current_version_id,source_sha256:current.sha256};
      const preview=await ctx.api(base(project)+'/text-tools/copy-preview',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request})});
      if(!alive(n,s)||target.value!==project)return;
      previewBox.replaceChildren(el('p','建立独立文字工作稿，保留原稿与固定来源；不会自动替换剧本或批准。'+(preview.detached_references.length?'原项目来源/风格/精校引用保留在来源记录中，在目标项目重新选择。':'')));
      const key='text-copy:'+formKey()+':copy:'+project+':'+request.source_version_id;
      previewBox.append(button(preview.existing_unit_id?'打开已导入工作稿':'确认导入固定稿',async()=>{
        const payload={request,preview_sha256:preview.preview_sha256};let op=pending.get(key);
        if(!op){op={key:crypto.randomUUID(),payload,revision:preview.revision};pending.set(key,op);}
        let result;try{result=await ctx.api(base(project)+'/text-tools/copy',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:op.payload,expected_revision:op.revision,idempotency_key:op.key})});}catch(error){if(error.status>=400&&error.status<500)pending.delete(key);throw error;}
        pending.delete(key);if(!alive(n,s))return;ctx.notice('已导入固定文字工作稿，可在目标项目继续回流剧本。');await ctx.activateWorkspace(project,result.unit_id);
      }));
    }),previewBox);main.append(box);
  }
  async function load(value){
    const n=++epoch;scope={...value};const s=scope;current=null;root.replaceChildren(el('p','正在读取专业工具…'));
    if(!s.project){root.replaceChildren(el('h1','独立剧本与分析工具'),el('p','直接整理、翻译或评分文字。完成后可导入目标作品，无需先建立影视项目。'),button('打开我的独立工具工作区',async()=>{
      const result=await ctx.api('/api/v1/text-tools/workspace',{method:'POST',headers:{'X-CSRF-Token':session().csrf}});
      if(alive(n,s))await ctx.activateWorkspace(result.id);
    },!session().actor));return;}
    try{const values=await Promise.all([ctx.api(base(s.project)+'/text-tools/capabilities'),ctx.api(base(s.project)+'/text-tools/options')]);if(!alive(n,s))return;[caps,options]=values;if(value.tool&&caps.tools[value.tool])tool=value.tool;await listing();if(alive(n,s))await open(value.targetId||null);}
    catch(error){if(alive(n,s))root.replaceChildren(el('p',error.message),button('重新读取',()=>load(value)));}
  }
  return {load,suspend(){epoch++;for(const controls of runControls)controls.dispose();runControls=[];}};
}
