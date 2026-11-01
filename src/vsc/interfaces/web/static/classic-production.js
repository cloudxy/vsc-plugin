// Each mode persists an original artifact version; preview never submits a provider.
import {createRunScopeControls} from './run-scope-controls.js';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const roles={first_frame:'首帧',last_frame:'尾帧',reference_image:'参考图片',reference_video:'参考视频',reference_audio:'参考音频',portrait:'人物形象',speech:'驱动音频',character:'角色图片',motion_video:'动作视频'};
const gapNames={shot_spec_missing:'缺少已确认镜头方案',state_missing:'缺少本场状态依据',first_frame_missing:'尚未选择可用首帧'};
const purposeNames={image_to_video:'图生视频',video_clip:'镜头视频',text_to_video:'文生视频',first_frame:'首帧图像',last_frame:'尾帧图像',image_edit:'图像编辑',identity_ref:'身份参考'};
const connectionNames={not_loaded:'当前进程未加载凭证',loaded_unverified:'凭证已加载，尚未在线验证',not_connected:'执行路线未接通',runtime_unavailable:'本机运行组件未就绪',invalid_configuration:'配置需要修正'};
const parameterNames={resolution:'分辨率',generate_audio:'同时生成声音',seed:'随机种子',quality:'质量'};
const clone=value=>JSON.parse(JSON.stringify(value));
export function createClassicProduction(root,ctx){
  let epoch=0,scope=null,options=null,mode='single',preview=null,editNo=0,runScope=null,referenceEditor=null;
  const drafts=new Map(),pending=new Map();
  const base=p=>'/api/v1/projects/'+encodeURIComponent(p);
  const session=()=>ctx.session();
  const alive=(n,s)=>n===epoch&&scope===s;
  const key=(s,m)=>s.projectId+':'+s.shotId+':'+m;
  function button(title,fn,disabled=false){const n=el('button',title);n.type='button';n.disabled=disabled;n.addEventListener('click',async()=>{try{await fn();}catch(error){ctx.notice(error.message);}});return n;}
  function field(form,title,input){const label=el('label',title);input.setAttribute('aria-label',title);label.append(input);form.append(label);return input;}
  function newDraft(s,m){return {shot_id:s.shotId,mode:m,model_id:'',purpose:'',prompt:'',duration_ms:5000,width:1080,height:1920,count:1,params:{},references:[],...(options?.modes[m]?.image_tool?{purpose:'image_edit',tool_settings:clone(options.modes[m].tool_defaults)}:{})};}
  function entry(m=mode){const k=key(scope,m);if(!drafts.has(k)){const stored=options.drafts.find(row=>row.document.mode===m);drafts.set(k,{document:stored?clone(stored.document):newDraft(scope,m),saved:stored||null,dirty:false});}return drafts.get(k);}
  async function write(action,payload,s,n,m){
    if(!session().actor||!session().writable)throw new Error('请先建立可写人工会话');
    const k=key(s,m),signature=JSON.stringify({action,payload});let operation=pending.get(k);
    if(operation&&operation.signature!==signature)throw new Error('上次写入回执未确认，请先恢复上次请求；当前编辑已保留。');
    if(!operation){operation={signature,action,payload:clone(payload),key:crypto.randomUUID(),revision:session().revision};pending.set(k,operation);}
    try{
      const result=await ctx.api(base(s.projectId)+'/classic-production/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:operation.payload,expected_revision:operation.revision,idempotency_key:operation.key})});
      pending.delete(k);if(alive(n,s))ctx.setRevision(result.revision,s.projectId);return result;
    }catch(error){if(error.status>=400&&error.status<500)pending.delete(k);throw error;}
  }
  function render(){
    const s=scope,n=++epoch,m=mode,e=entry(),doc=e.document,definition=options.modes[m];preview=null;
    runScope?.dispose();referenceEditor?.suspend();root.replaceChildren();
    const heading=el('header',null,'classic-heading');
    heading.append(el('p','VSC · 经典制作','hint'),el('h1',options.shot.title||options.shot.display_code||'镜头制作'),el('p','各模式分别保留输入。保存与预览完成后，运行方案进入原批准与任务流程。','hint'));
    heading.append(button('返回本集',()=>ctx.navigate('production',s.episodeId)),button('候选与输入',()=>ctx.navigate('candidates',s.shotId)),button('打开原素材工具',()=>ctx.navigate('media',s.shotId)));root.append(heading);
    const pick=el('select');pick.setAttribute('aria-label','制作镜头');
    for(const shot of s.shots)pick.append(new Option(shot.title||shot.display_code||shot.id,shot.id));
    pick.value=s.shotId;pick.addEventListener('change',()=>load({...s,objectId:pick.value,shotId:pick.value}));root.append(pick);
    const shotName=el('input');shotName.placeholder='新增镜号名称';shotName.setAttribute('aria-label','新增镜号名称');root.append(shotName,button('在当前镜组新增镜号',async()=>{const value=await write('shots',{action:'create',parent_id:options.shot.parent_id,title:shotName.value},s,n,m);if(alive(n,s))await load({...s,shotId:value.id,objectId:value.id,shots:null});}));
    for(const[delta,title]of [[-1,'镜号上移'],[1,'镜号下移']])root.append(button(title,async()=>{const rows=options.sibling_shots||[],ids=rows.map(r=>r.id),index=ids.indexOf(s.shotId),target=index+delta;if(target<0||target>=ids.length)return;[ids[index],ids[target]]=[ids[target],ids[index]];await write('shots',{action:'reorder',parent_id:options.shot.parent_id,shot_ids:ids},s,n,m);if(alive(n,s))await load({...s,shots:null});}));
    const tabs=el('nav',null,'classic-modes');tabs.setAttribute('aria-label','制作模式');
    for(const [id,item]of Object.entries(options.modes)){const b=button(item.label,()=>{mode=id;render();});b.setAttribute('aria-pressed',String(id===m));tabs.append(b);}root.append(tabs);
    const body=el('div',null,'classic-layout'),form=el('form',null,'classic-form'),aside=el('aside',null,'classic-results');body.append(form,aside);root.append(body);
    const message=el('p',e.saved?'草稿版本 '+e.saved.version+' · '+(e.dirty?'有未保存修改':'已保存'):'尚未保存当前模式','classic-status');message.setAttribute('role','status');form.append(el('h2',definition.label),message);
    if(definition.tool_unavailable)form.append(el('p',definition.tool_unavailable,'classic-blocker'));
    if(definition.unsupported)form.append(el('p',definition.unsupported,'classic-blocker'));
    const model=field(form,'模型与配置版本',el('select')),models=options.models.filter(row=>row.modality===definition.modality);
    model.append(new Option('选择实际模型',''));
    for(const row of models)model.append(new Option((row.name||row.model_key)+' · '+row.model_version+(!row.enabled?' · 已停用':!row.adapter_available?' · 未接通':''),row.id));
    if(doc.model_id&&!models.some(row=>row.id===doc.model_id))model.append(new Option('草稿中的旧模型版本（需重新选择）',doc.model_id));model.value=doc.model_id;
    const purpose=field(form,'生成用途',el('select')),capabilities=el('div',null,'classic-capabilities');form.append(capabilities);
    const prompt=field(form,'当前模式提示词',el('textarea'));prompt.rows=7;prompt.maxLength=50000;prompt.value=doc.prompt;
    const numeric=el('div',null,'classic-numbers'),numbers={};form.append(numeric);
    const dimensions=definition.modality==='image'?[['width','图像宽度',1],['height','图像高度',1],['count','候选数量',1]]:[['duration_ms','时长（秒）',1000],['count','候选数量',1]];
    for(const [id,title,scale]of dimensions){const input=el('input');input.type='number';input.min=id==='duration_ms'?'0.001':'1';input.step=id==='duration_ms'?'0.001':'1';if(id==='count')input.max='8';input.value=String(doc[id]/scale);field(numeric,title,input);numbers[id]={input,scale};}
    const params=field(form,'模型参数（JSON；以当前模型声明为准）',el('textarea'));params.rows=3;params.value=e.rawParams||JSON.stringify(doc.params,null,2);
    const modelFields=el('div',null,'classic-model-fields');form.append(modelFields);
    const syncCapabilities=()=>{
      const row=models.find(item=>item.id===model.value),caps=row?.capabilities||{};
      purpose.replaceChildren(new Option('选择用途',''));for(const p of caps.purposes||[])purpose.append(new Option(purposeNames[p]||p,p));if(definition.image_tool&&caps.purposes?.includes('image_edit')&&!doc.purpose)doc.purpose='image_edit';purpose.value=doc.purpose;
      capabilities.replaceChildren(el('p',row?(row.enabled&&row.adapter_available?'执行路线已接通':'仅可保存草稿')+' · '+(connectionNames[row.connection_status]||row.connection_status||'凭证状态未知'):'尚未选择实际模型','hint'));
      const limits=[];for(const [k,title]of [['max_duration_ms','最长视频毫秒'],['max_reference_images','最多参考图片'],['max_width','最大宽度'],['max_height','最大高度']])if(caps[k]!=null)limits.push(title+' '+caps[k]);
      capabilities.append(el('p',limits.join(' · ')||'模型未声明额外数值上限；提交前仍由原能力校验。','hint'));
      if(numbers.duration_ms)numbers.duration_ms.input.max=caps.max_duration_ms?String(caps.max_duration_ms/1000):'';
      if(numbers.width)numbers.width.input.max=caps.max_width||'';if(numbers.height)numbers.height.input.max=caps.max_height||'';
      const d=el('details');d.append(el('summary','当前模型能力与默认参数'),el('pre',JSON.stringify({capabilities:caps,default_params:row?.default_params||{}},null,2)));capabilities.append(d);
      modelFields.replaceChildren();
      for(const [name,value]of Object.entries(row?.default_params||{})){
        if(!['string','number','boolean'].includes(typeof value))continue;
        const declared=caps.parameters?.[name],choices=Array.isArray(declared?.enum)?declared.enum:null;
        const input=el(choices?'select':'input');
        if(choices){for(const choice of choices)input.append(new Option(String(choice),String(choice)));input.value=String(doc.params[name]??value);}
        else if(typeof value==='boolean'){input.type='checkbox';input.checked=doc.params[name]??value;}
        else{input.type=typeof value==='number'?'number':'text';input.value=String(doc.params[name]??value);if(typeof value==='number')input.step='any';}
        field(modelFields,'模型参数 · '+(parameterNames[name]||name),input);
        input.addEventListener('input',()=>{try{const current=JSON.parse(params.value);current[name]=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;params.value=JSON.stringify(current,null,2);capture();mark();}catch{ctx.notice('请先修正模型参数 JSON；当前输入已保留。');}});
      }
    };syncCapabilities();
    const toolFields=el('section');form.append(toolFields);
    if(definition.image_tool){doc.tool_settings||=clone(definition.tool_defaults);toolFields.append(el('h3','固定图像工具参数'));for(const[key,value]of Object.entries(definition.tool_defaults)){
      const choices=key==='preset'?['custom','fisheye','tilt','front_high','front_low','top','back']:key==='direction'?['front','back','left','right','top','bottom']:key==='view'?['front','perspective']:key==='target'?['4k','8k']:null;
      const input=el(choices?'select':'input');if(choices){for(const v of choices)input.append(new Option(v,v));input.value=doc.tool_settings[key];}else{input.type=typeof value==='boolean'?'checkbox':typeof value==='number'?'number':key==='color'?'color':'text';if(input.type==='checkbox')input.checked=doc.tool_settings[key];else input.value=doc.tool_settings[key];if(typeof value==='number')input.step='any';}
      field(toolFields,({layout:'视图布局',framing:'取景',strength:'调整程度',expression:'表情',preset:'角度预设',yaw:'水平环绕角度',pitch:'垂直俯仰角度',roll:'倾斜角度',zoom:'景别缩放',include_instructions:'把角度说明加入模型提示词',view:'光源视图',direction:'主光方向',intensity:'光源亮度',color:'光源颜色',cone:'光锥角度',rim:'开启轮廓光',mask_media_id:'已登记遮罩媒体ID',mask_sha256:'固定遮罩摘要（保存时核验）',projection:'全景投影',target:'超分规格',rights_confirmed:'确认有权处理此来源'})[key]||key,input);
      input.addEventListener('input',()=>{doc.tool_settings[key]=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;mark();});
    }toolFields.append(button('重置当前工具参数',()=>{doc.tool_settings=clone(definition.tool_defaults);mark();render();}));if(definition.image_tool==='angle'){for(const[axis,amount,label]of [['yaw',-15,'向左15°'],['yaw',15,'向右15°'],['pitch',15,'向上15°'],['pitch',-15,'向下15°']])toolFields.append(button(label,()=>{doc.tool_settings[axis]=Math.max(axis==='yaw'?-180:-90,Math.min(axis==='yaw'?180:90,doc.tool_settings[axis]+amount));mark();render();}));}}
    const references=el('section' ,null,'classic-references');form.append(references);
    const report=el('div',null,'classic-report');
    const propose=button('保存待审运行方案',async()=>{
      if(!preview||e.dirty)throw new Error('请先保存并预览当前草稿');
      const request=preview.request,sha=preview.value.preview_sha256;propose.disabled=true;
      try{const result=await write('run-proposals',{request,preview_sha256:sha},s,n,m);if(alive(n,s)){ctx.notice('运行方案已保存，尚未批准和执行。');await ctx.openArtifact(result.id);}}
      finally{if(alive(n,s))propose.disabled=!preview||e.dirty;}
    },true);
    const mark=()=>{e.dirty=true;editNo++;preview=null;propose.disabled=true;report.replaceChildren();message.textContent='有未保存修改；各模式输入分别保留。';};
    function renderReferences(){
      references.replaceChildren(el('h3','固定参考素材'));
      if(!Object.keys(definition.slots).length)references.append(el('p','此模式不携带图片参考。其他模式的图片继续保留在各自草稿。','hint'));
      for(const [role,type]of Object.entries(definition.slots)){
        const box=el('div',null,'classic-reference-slot');box.append(el('h4',roles[role]||role));
        for(const [index,ref]of doc.references.entries()){if(ref.role!==role)continue;const media=options.media.find(row=>row.id===ref.media_id);box.append(el('p',(media?.name||ref.media_id)+' · '+(ref.sha256?.slice(0,12)||'保存时固定摘要')),button('移除此引用',()=>{const removed=doc.references.splice(index,1);if(media?.modality==='video'){removed.push(...doc.references.filter(r=>r.annotation_source_id===ref.media_id));doc.references=doc.references.filter(r=>r.annotation_source_id!==ref.media_id);}for(const item of removed){if(item.prompt_mention)doc.prompt=doc.prompt.split(item.prompt_mention).join('');doc.prompt=doc.prompt.split('[[ref:'+item.media_id+']]').join('');}doc.prompt=doc.prompt.trim();prompt.value=doc.prompt;mark();renderReferences();}));}
        const select=el('select');select.setAttribute('aria-label',roles[role]||role);select.append(new Option('选择已登记的'+type,''));
        for(const media of options.media.filter(row=>row.modality===type))select.append(new Option(media.name||media.id,media.id));
        box.append(select,button('添加'+(roles[role]||role),()=>{
          if(!select.value)return;const media=options.media.find(row=>row.id===select.value);
          if(doc.references.some(ref=>ref.role===role&&ref.media_id===media.id))return;
          if(!['reference_image','reference_video','reference_audio'].includes(role))doc.references=doc.references.filter(ref=>ref.role!==role);
          doc.references.push({role,media_id:media.id,sha256:media.sha256});mark();renderReferences();
        }));references.append(box);
      }
      if(m==='first_last')references.append(button('交换首尾帧',()=>{for(const ref of doc.references)ref.role=ref.role==='first_frame'?'last_frame':'first_frame';mark();renderReferences();}));
      references.append(el('p','只有在本镜头选为可用用途的固定素材才能进入运行方案。','hint'));
      if(options.media_total>options.media.length)references.append(el('p','当前列出前 '+options.media.length+' 项素材；更早素材可从原素材库按 ID 定位。','hint'));
      if(Object.keys(definition.slots).length){
        const manual=el('input');manual.placeholder='已登记媒体 ID';manual.setAttribute('aria-label','更多固定媒体 ID');
        const role=el('select');for(const r of Object.keys(definition.slots))role.append(new Option(roles[r]||r,r));
        references.append(manual,role,button('按 ID 添加引用',()=>{if(!manual.value.trim())return;doc.references.push({role:role.value,media_id:manual.value.trim()});mark();renderReferences();}));
      }
    }renderReferences();
    const editorHost=el('section');editorHost.hidden=true;form.append(editorHost);e.referenceBuffers||=new Map();
    async function openEditor(media,saved=null,fresh=false){referenceEditor?.suspend();const bufferKey=fresh?media.id+':'+crypto.randomUUID():saved?.document.edit.id||media.id;let buffer=e.referenceBuffers.get(bufferKey);if(!buffer){buffer={document:saved?clone(saved.document.edit):null,saved:saved||null,dirty:!saved};e.referenceBuffers.set(bufferKey,buffer);}editorHost.hidden=false;const module=await import('./reference-editor.js');if(!alive(n,s))return;referenceEditor=await module.createReferenceEditor(editorHost,{api:ctx.api,session:ctx.session,project:s.projectId,shot:s.shotId,mode:m,media,buffer,onNew:()=>openEditor(media,null,true),notice:ctx.notice,setRevision:ctx.setRevision,onAdd:item=>{if(!alive(n,s))return;const role=definition.slots.reference_image?'reference_image':Object.entries(definition.slots).find(([,kind])=>kind==='image')?.[0];if(!role)return ctx.notice('当前模式无图像参考，请切到图像或全能参考模式');if(!['reference_image'].includes(role))doc.references=doc.references.filter(r=>r.role!==role);if(!doc.references.some(r=>r.media_id===item.media_id)){const mention='[[ref:'+item.media_id+']] '+(item.source_modality==='video'?item.time_ms+'ms 视频帧标注':'图像标注')+'：'+buffer.document.description;doc.references.push({role,media_id:item.media_id,sha256:item.sha256,annotation_id:item.annotation_id,annotation_source_id:item.annotation_source_id,prompt_mention:mention});if(item.source_modality==='video'&&definition.slots.reference_video&&!doc.references.some(r=>r.media_id===item.annotation_source_id)){const source=options.media.find(r=>r.id===item.annotation_source_id);doc.references.push({role:'reference_video',media_id:source.id,sha256:source.sha256});}doc.prompt+=(doc.prompt?'\n':'')+mention;prompt.value=doc.prompt;options.media.push({id:item.media_id,sha256:item.sha256,modality:'image',name:'固定标注图'});mark();renderReferences();}}});}
    const editSource=el('select');editSource.setAttribute('aria-label','图像或视频标注来源');editSource.append(new Option('选择明确源媒体',''));for(const media of options.media.filter(r=>['image','video'].includes(r.modality)))editSource.append(new Option(media.name||media.id,media.id));form.append(editSource,button('打开图像或视频帧编辑',()=>{const source=options.media.find(r=>r.id===editSource.value);if(!source)throw new Error('先选择固定源媒体');return openEditor(source);}));
    for(const saved of options.reference_edits||[]){if(saved.document.mode!==m)continue;const source=options.media.find(r=>r.id===saved.document.edit.source_media_id)||{id:saved.document.edit.source_media_id};form.append(button('继续标注 '+saved.document.edit.time_ms+'ms · v'+saved.version,()=>openEditor(source,saved)));}

    function capture(){
      doc.model_id=model.value;doc.purpose=purpose.value;doc.prompt=prompt.value;
      for(const [id,{input,scale}]of Object.entries(numbers))doc[id]=Math.round(Number(input.value)*scale);
      try{doc.params=JSON.parse(params.value);e.paramsError=null;}catch{e.paramsError='模型参数不是有效 JSON，当前文本已保留。';}e.rawParams=params.value;
    }
    form.addEventListener('input',event=>{if(event.target===model||bounds.contains(event.target)||references.contains(event.target))return;capture();mark();});
    model.addEventListener('change',()=>{doc.model_id=model.value;doc.purpose='';syncCapabilities();capture();mark();});purpose.addEventListener('change',()=>{capture();mark();});
    const save=el('button','保存当前模式');save.type='submit';save.disabled=!session().writable||!session().actor;
    form.addEventListener('submit',async event=>{
      event.preventDefault();capture();if(e.paramsError){ctx.notice(e.paramsError);return;}
      const submitted=clone(doc),version=editNo;save.disabled=true;
      try{
        const result=await write('drafts',{document:submitted,base_draft_id:e.saved?.id||null},s,n,m);
        e.saved={...result,document:submitted};if(version===editNo)e.dirty=false;
        if(alive(n,s)){message.textContent=e.dirty?'草稿已保存，仍有后续未保存修改':'当前模式已保存';check.disabled=e.dirty;}
      }catch(error){if(alive(n,s))ctx.notice(error.message+'；输入已保留。');}
      finally{if(alive(n,s))save.disabled=false;}
    });
    const due=el('input'),stop=el('input'),attempts=el('input');due.type=stop.type='datetime-local';attempts.type='number';attempts.min='1';attempts.max='20';attempts.value='2';
    const date=minutes=>{const d=new Date(Date.now()+minutes*60000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};due.value=date(45);stop.value=date(60);
    const bounds=el('details');bounds.open=true;bounds.append(el('summary','本次执行范围与时限'));field(bounds,'首版目标时间',due);field(bounds,'停止新增任务时间',stop);field(bounds,'同用途最多尝试',attempts);form.append(bounds);
    runScope=createRunScopeControls(bounds,{api:ctx.api,session:ctx.session,projectId:s.projectId,onChange:()=>{editNo++;preview=null;propose.disabled=true;}});
    for(const input of [due,stop,attempts])input.addEventListener('input',()=>{editNo++;preview=null;propose.disabled=true;});
    const check=button('预览固定输入与用量',async()=>{
      if(e.dirty||!e.saved)throw new Error('请先保存当前模式');
      const version=editNo,request=runScope.apply({draft_version_id:e.saved.id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(attempts.value),max_repair_rounds:1}});check.disabled=true;
      try{
        const value=await ctx.api(base(s.projectId)+'/classic-production/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});
        if(!alive(n,s)||version!==editNo)return;ctx.setRevision(value.revision,s.projectId);
        report.replaceChildren(el('h3',value.ready?'固定输入可制定运行方案':'需要处理的缺口'));
        for(const gap of value.gaps||[])report.append(el('p',gap.message||gapNames[gap.code]||gap.code));
        if(value.ready){preview={request,value};report.append(el('p','原生用量：'+JSON.stringify(value.generation_quote.native_units)),el('p',value.generation_quote.all_prices_known?'估算金额：'+JSON.stringify(value.generation_quote.known_subtotals):'金额未知；不表示免费。'));if(value.commerce_quote?.enabled){const charge=value.commerce_quote.commerce_charge;report.append(el('p',`商业额度上限 ${Object.values(charge.max_credits_by_operation).reduce((a,b)=>a+b,0)} · ${charge.account_actor||'项目共享额度'}`));}propose.disabled=false;}
      }catch(error){if(alive(n,s))ctx.notice(error.message);}
      finally{if(alive(n,s))check.disabled=e.dirty||!e.saved;}
    },!e.saved||e.dirty);
    const recover=button('恢复上次请求',async()=>{
      const operation=pending.get(key(s,m));if(!operation){ctx.notice('当前模式没有待恢复请求。');return;}
      const result=await write(operation.action,operation.payload,s,n,m);
      if(operation.action==='drafts'){e.saved={...result,document:operation.payload.document};e.dirty=JSON.stringify(e.document)!==JSON.stringify(operation.payload.document);}
      if(alive(n,s)){if(operation.action==='run-proposals')await ctx.openArtifact(result.id);else render();}
    });
    const refresh=button('重新读取版本并保留输入',async()=>{
      const value=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId));if(!alive(n,s))return;
      options=value;ctx.setRevision(value.revision,s.projectId);
      for(const item of value.drafts){const retained=drafts.get(key(s,item.document.mode));if(retained){retained.saved=item;retained.dirty=JSON.stringify(retained.document)!==JSON.stringify(item.document);}}render();
    });
    const actions=el('div',null,'classic-actions');actions.append(save,check,propose,recover,refresh);form.append(actions,report);
    aside.append(el('h2','同镜头候选'),el('p','共享原候选、用途选择、下载、收藏、加工与剪辑入口。','hint'),button('打开候选与审阅',()=>ctx.navigate('candidates',s.shotId)),button('打开剪辑工作区',()=>ctx.navigate('editing',s.episodeId)));
    ctx.api(base(s.projectId)+'/workbench?section=candidates&object_id='+encodeURIComponent(s.shotId)+'&limit=24').then(value=>{
      if(!alive(n,s))return;
      for(const row of value.sections?.candidates?.items||[]){const box=el('article',null,'classic-candidate');box.append(el('p',row.title||row.name||row.purpose||row.media_id),el('p',row.status||'候选','hint'),button('查看与使用素材',()=>ctx.media(row.media_id)),button('复用此候选原配置',async()=>{const value=await ctx.api(base(s.projectId)+'/classic-production/candidate-configuration?shot_id='+s.shotId+'&media_id='+row.media_id);if(!alive(n,s))return;if(!value.available)throw new Error(value.reason);const target=entry(value.document.mode);target.document=clone(value.document);target.dirty=true;mode=value.document.mode;editNo++;render();}));aside.append(box);}
    }).catch(error=>{if(alive(n,s))aside.append(el('p','候选读取未完成：'+error.message));});
  }
  async function load(value){
    const n=++epoch;preview=null;scope={...value};const s=scope;
    root.replaceChildren(el('p','正在读取经典制作…'));
    try{
      const query=new URLSearchParams({section:'shots',limit:'100',...(value.objectId?{object_id:value.objectId}:value.episodeId?{object_id:value.episodeId}:{})});
      const listing=await ctx.api(base(s.projectId)+'/workbench?'+query);
      if(!alive(n,s))return;
      const page=listing.sections.shots;
      s.episodeId=value.episodeId||(listing.scope.kind==='episode'?listing.scope.id:listing.ancestors.find(row=>row.kind==='episode')?.id)||null;
      s.shots=value.shots?.length?value.shots:page.items;
      s.shotId=value.shotId||(listing.scope.kind==='shot'?listing.scope.id:page.items[0]?.id);
      if(!s.shotId){root.replaceChildren(el('h1','经典制作'),el('p','当前范围尚无镜头。请先在制作方案与场镜设计建立镜头。'),button('打开场镜设计',()=>ctx.navigate('designs',value.objectId)));return;}
      const data=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId));
      if(!alive(n,s))return;
      options=data;if(data.sibling_shots?.length)s.shots=data.sibling_shots;ctx.setRevision(data.revision,s.projectId);ctx.onShot?.(s.shotId);render();
      if(page.next_offset!=null||page.truncated)root.append(el('p','当前显示前 100 镜；其余镜头可从原场镜工作台定位后进入。','hint'));
    }catch(error){if(alive(n,s))root.replaceChildren(el('h1','经典制作读取未完成'),el('p',error.message),button('重新读取',()=>load(value)));}
  }
  return {load,suspend(){runScope?.dispose();referenceEditor?.suspend();epoch++;preview=null;}};
}
