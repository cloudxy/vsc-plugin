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
  const closeDialogs=()=>{for(const dialog of root.querySelectorAll('dialog'))dialog.close();};
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
    runScope?.dispose();referenceEditor?.suspend();closeDialogs();root.replaceChildren();root.classList.add('classic-production');
    const imageMode=definition.modality==='image',noun=imageMode?'分镜':'视频';
    const heading=el('header',null,'classic-heading');
    heading.append(el('h1','所有'+noun));
    const headingActions=el('div',null,'classic-heading-actions');headingActions.append(button('视频剪辑',()=>ctx.navigate('editing',s.episodeId)),button('合成视频',()=>ctx.navigate('editing',s.episodeId)),button(imageMode?'批量上传分镜':'上传视频',()=>ctx.navigate('media',s.shotId)));heading.append(headingActions);root.append(heading);
    const shotRail=el('nav',null,'classic-shot-rail');shotRail.setAttribute('aria-label','所有'+noun);heading.append(shotRail);
    for(const [index,shot]of s.shots.entries()){const b=button('',()=>load({...s,objectId:shot.id,shotId:shot.id}));b.className='classic-shot';b.title=shot.title||shot.display_code||shot.id;b.setAttribute('aria-label','打开'+noun+' '+(index+1));b.setAttribute('aria-current',shot.id===s.shotId?'true':'false');b.append(el('span',String(index+1),'classic-shot-number'),el('span',shot.title||shot.display_code||noun+(index+1),'classic-shot-title'));shotRail.append(b);}
    const shotTools=el('details',null,'classic-shot-tools');shotTools.append(el('summary','镜头管理'));heading.append(shotTools);
    const pick=el('select');pick.setAttribute('aria-label','制作镜头');
    for(const shot of s.shots)pick.append(new Option(shot.title||shot.display_code||shot.id,shot.id));
    pick.value=s.shotId;pick.addEventListener('change',()=>load({...s,objectId:pick.value,shotId:pick.value}));shotTools.append(pick);
    const shotName=el('input');shotName.placeholder='新增镜号名称…';shotName.setAttribute('aria-label','新增镜号名称');shotTools.append(shotName,button('在当前镜组新增镜号',async()=>{const value=await write('shots',{action:'create',parent_id:options.shot.parent_id,title:shotName.value},s,n,m);if(alive(n,s))await load({...s,shotId:value.id,objectId:value.id,shots:null});}));
    const addShot=button('',()=>{shotTools.open=true;shotName.focus();});addShot.className='classic-shot classic-add-shot';addShot.append(el('span','＋'),el('span','新增'+noun));shotRail.append(addShot);
    for(const[delta,title]of [[-1,'镜号上移'],[1,'镜号下移']])shotTools.append(button(title,async()=>{const rows=options.sibling_shots||[],ids=rows.map(r=>r.id),index=ids.indexOf(s.shotId),target=index+delta;if(target<0||target>=ids.length)return;[ids[index],ids[target]]=[ids[target],ids[index]];await write('shots',{action:'reorder',parent_id:options.shot.parent_id,shot_ids:ids},s,n,m);if(alive(n,s))await load({...s,shots:null});}));
    const tabs=el('nav',null,'classic-modes');tabs.setAttribute('aria-label','制作模式');
    const modes=Object.entries(options.modes).filter(([,item])=>item.modality===definition.modality&&(!imageMode||Boolean(item.image_tool)===Boolean(definition.image_tool))),order=['omni','first_last','multi','single','text','digital_human','motion'];modes.sort((a,b)=>(order.indexOf(a[0])<0?99:order.indexOf(a[0]))-(order.indexOf(b[0])<0?99:order.indexOf(b[0])));
    for(const [id,item]of modes){const b=button(item.label,()=>{mode=id;render();});b.setAttribute('aria-pressed',String(id===m));tabs.append(b);}
    const body=el('div',null,'classic-layout'),form=el('form',null,'classic-form'),aside=el('aside',null,'classic-results');body.append(form,aside);root.append(body);
    const message=el('p',e.saved?'草稿版本 '+e.saved.version+' · '+(e.dirty?'有未保存修改':'已保存'):'尚未保存当前模式','classic-status');message.setAttribute('role','status');form.append(el('h2','生成'+noun+'方式'));if(modes.length>1)form.append(tabs);
    if(definition.tool_unavailable)form.append(el('p',definition.tool_unavailable,'classic-blocker'));
    if(definition.unsupported)form.append(el('p',definition.unsupported,'classic-blocker'));
    const modelSection=el('div',null,'classic-model');form.append(modelSection);
    const model=field(modelSection,'模型',el('select')),models=options.models.filter(row=>row.modality===definition.modality);model.setAttribute('aria-label','模型与配置版本');
    model.append(new Option('选择实际模型',''));
    for(const row of models)model.append(new Option((row.name||row.model_key)+' · '+row.model_version+(!row.enabled?' · 已停用':!row.adapter_available?' · 未接通':''),row.id));
    if(!e.saved&&!doc.model_id)doc.model_id=models.find(row=>row.enabled&&row.adapter_available)?.id||'';
    if(doc.model_id&&!models.some(row=>row.id===doc.model_id))model.append(new Option('草稿中的旧模型版本（需重新选择）',doc.model_id));model.value=doc.model_id;
    const advanced=el('details',null,'classic-advanced');advanced.append(el('summary','高级设置'));
    const purpose=field(advanced,'生成用途',el('select')),capabilities=el('div',null,'classic-capabilities');advanced.append(capabilities);
    const promptSection=el('div',null,'classic-prompt');form.append(promptSection);
    const prompt=field(promptSection,'提示词',el('textarea'));prompt.setAttribute('aria-label','当前模式提示词');prompt.placeholder='输入 @ 符号引用资源，描述画面和动作…';prompt.rows=7;prompt.maxLength=50000;prompt.value=doc.prompt;
    const numeric=el('div',null,'classic-numbers'),numbers={};form.append(numeric);
    const dimensions=definition.modality==='image'?[['width','图像宽度',1],['height','图像高度',1],['count','候选数量',1]]:[['duration_ms','时长（秒）',1000],['count','候选数量',1]];
    for(const [id,title,scale]of dimensions){const input=el('input');input.type='number';input.min=id==='duration_ms'?'0.001':'1';input.step=id==='duration_ms'?'0.001':'1';if(id==='count')input.max='8';input.value=String(doc[id]/scale);field(numeric,title,input);numbers[id]={input,scale};}
    const params=field(advanced,'模型参数（JSON；以当前模型声明为准）',el('textarea'));params.rows=3;params.value=e.rawParams||JSON.stringify(doc.params,null,2);
    const modelFields=el('div',null,'classic-model-fields');advanced.append(modelFields);
    const syncCapabilities=()=>{
      const row=models.find(item=>item.id===model.value),caps=row?.capabilities||{};
      purpose.replaceChildren(new Option('选择用途',''));for(const p of caps.purposes||[])purpose.append(new Option(purposeNames[p]||p,p));const preferred=definition.image_tool?'image_edit':imageMode?'first_frame':m==='text'?'text_to_video':'image_to_video';if(!doc.purpose&&caps.purposes?.includes(preferred))doc.purpose=preferred;purpose.value=doc.purpose;
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
    const toolFields=el('section');advanced.append(toolFields);
    if(definition.image_tool){doc.tool_settings||=clone(definition.tool_defaults);toolFields.append(el('h3','固定图像工具参数'));for(const[key,value]of Object.entries(definition.tool_defaults)){
      const choices=key==='preset'?['custom','fisheye','tilt','front_high','front_low','top','back']:key==='direction'?['front','back','left','right','top','bottom']:key==='view'?['front','perspective']:key==='target'?['4k','8k']:null;
      const input=el(choices?'select':'input');if(choices){for(const v of choices)input.append(new Option(v,v));input.value=doc.tool_settings[key];}else{input.type=typeof value==='boolean'?'checkbox':typeof value==='number'?'number':key==='color'?'color':'text';if(input.type==='checkbox')input.checked=doc.tool_settings[key];else input.value=doc.tool_settings[key];if(typeof value==='number')input.step='any';}
      field(toolFields,({layout:'视图布局',framing:'取景',strength:'调整程度',expression:'表情',preset:'角度预设',yaw:'水平环绕角度',pitch:'垂直俯仰角度',roll:'倾斜角度',zoom:'景别缩放',include_instructions:'把角度说明加入模型提示词',view:'光源视图',direction:'主光方向',intensity:'光源亮度',color:'光源颜色',cone:'光锥角度',rim:'开启轮廓光',mask_media_id:'已登记遮罩媒体ID',mask_sha256:'固定遮罩摘要（保存时核验）',projection:'全景投影',target:'超分规格',rights_confirmed:'确认有权处理此来源'})[key]||key,input);
      input.addEventListener('input',()=>{doc.tool_settings[key]=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;mark();});
    }toolFields.append(button('重置当前工具参数',()=>{doc.tool_settings=clone(definition.tool_defaults);mark();render();}));if(definition.image_tool==='angle'){for(const[axis,amount,label]of [['yaw',-15,'向左15°'],['yaw',15,'向右15°'],['pitch',15,'向上15°'],['pitch',-15,'向下15°']])toolFields.append(button(label,()=>{doc.tool_settings[axis]=Math.max(axis==='yaw'?-180:-90,Math.min(axis==='yaw'?180:90,doc.tool_settings[axis]+amount));mark();render();}));}}
    const references=el('section' ,null,'classic-references');form.append(references);references.dataset.mode=m;
    const report=el('div',null,'classic-report');
    const propose=button('保存待审运行方案',async()=>{
      if(!preview||e.dirty)throw new Error('请先保存并预览当前草稿');
      const request=preview.request,sha=preview.value.preview_sha256;propose.disabled=true;
      try{const result=await write('run-proposals',{request,preview_sha256:sha},s,n,m);if(alive(n,s)){ctx.notice('运行方案已保存，尚未批准和执行。');await ctx.openArtifact(result.id);}}
      finally{if(alive(n,s))propose.disabled=!preview||e.dirty;}
    },true);
    const mark=()=>{e.dirty=true;editNo++;preview=null;propose.disabled=true;report.replaceChildren();message.textContent='有未保存修改；各模式输入分别保留。';};
    function openUpload(role,type){
      const owner=session().identityId||session().actor||'',uploadKey=owner+':'+role;e.uploads||=new Map();
      if(!e.uploads.has(uploadKey))e.uploads.set(uploadKey,{file:null,source:'',purposes:role,staged:null,request:null,registered:null,busy:false});
      const buffer=e.uploads.get(uploadKey),dialog=el('dialog',null,'classic-upload-dialog'),form=el('form'),title=el('header'),status=el('p',null,'classic-upload-status');status.setAttribute('role','status');dialog.setAttribute('aria-label','上传'+roles[role]);
      const current=()=>alive(n,s)&&(session().identityId||session().actor||'')===owner&&dialog.open&&dialog.isConnected;
      title.append(el('h2','上传'+roles[role]),button('关闭',()=>dialog.close()));dialog.append(title,form);root.append(dialog);
      const file=field(form,'选择本地文件',el('input'));file.type='file';file.accept=type+'/*';const selected=el('p',buffer.file?.name||'尚未选择文件','hint');form.append(selected);
      const source=field(form,'来源及证据说明',el('textarea'));source.rows=3;source.value=buffer.source;source.placeholder='谁提供或制作、原始出处…';
      const purposes=field(form,'适用用途',el('input'));purposes.value=buffer.purposes;
      form.append(el('p','以“权利待确认”登记；加入参考不代表批准使用。','hint'),status);
      const controls=el('div',null,'classic-upload-actions'),submit=el('button',buffer.registered?'恢复素材读回':buffer.request?'恢复上传登记':'上传并加入参考');submit.type='submit';submit.className='classic-primary';controls.append(button('取消',()=>dialog.close()),submit);form.append(controls);
      const capture=()=>{buffer.source=source.value;buffer.purposes=purposes.value;};source.addEventListener('input',capture);purposes.addEventListener('input',capture);
      file.addEventListener('change',()=>{if(buffer.request||buffer.registered)return;if(file.files?.[0]){buffer.file=file.files[0];buffer.staged=null;selected.textContent=buffer.file.name;}});
      function lock(){const fixed=buffer.busy||Boolean(buffer.request||buffer.registered);file.disabled=source.disabled=purposes.disabled=fixed;submit.disabled=buffer.busy||!session().actor||!session().writable;}
      buffer.listeners||=new Set();buffer.listeners.add(lock);lock();dialog.addEventListener('close',()=>{capture();buffer.listeners.delete(lock);dialog.remove();});
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(buffer.busy)return;capture();
        if(!session().actor||!session().writable){status.textContent='当前会话只读，请先取得项目编辑权限。';return;}
        if(!buffer.file){status.textContent='请选择本地文件。';return;}if(!buffer.source.trim()){status.textContent='请填写来源及证据说明。';source.focus();return;}
        buffer.busy=true;lock();status.textContent=buffer.registered?'正在恢复素材读回…':'正在上传并登记…';
        try{
          if(!buffer.staged)buffer.staged=await ctx.api(base(s.projectId)+'/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(buffer.file.name),'X-CSRF-Token':session().csrf},body:buffer.file});
          if(!current())return;
          if(!buffer.registered){
            if(!buffer.request)buffer.request={payload:{staged_upload:buffer.staged.staged_upload,name:buffer.file.name,rights:'unknown',rights_scope:{purposes:buffer.purposes.split(',').map(v=>v.trim()).filter(Boolean)},source:{kind:'user_upload',content:buffer.source}},expected_revision:session().revision,idempotency_key:crypto.randomUUID()};
            try{buffer.registered=await ctx.api(base(s.projectId)+'/media',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(buffer.request)});buffer.request=null;}
            catch(error){if(error.status>=400&&error.status<500)buffer.request=null;throw error;}
          }
          if(!current())return;
          // Registration and readback are separate: retrying a failed read never registers twice.
          const [media,latest]=await Promise.all([ctx.api(base(s.projectId)+'/media/'+encodeURIComponent(buffer.registered.id)),ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId))]);
          if(!current())return;ctx.setRevision(latest.revision,s.projectId);
          if(media.modality!==type)throw new Error('已登记文件不是此参考槽需要的'+({image:'图片',video:'视频',audio:'音频'})[type]+'；请在素材库检查后重新选择。');
          if(!options.media.some(row=>row.id===media.id))options.media.push(media);
          if(!['reference_image','reference_video','reference_audio'].includes(role))doc.references=doc.references.filter(ref=>ref.role!==role);
          if(!doc.references.some(ref=>ref.role===role&&ref.media_id===media.id))doc.references.push({role,media_id:media.id,sha256:media.sha256||buffer.registered.sha256});
          mark();renderReferences();e.uploads.delete(uploadKey);dialog.close();ctx.notice('素材已登记并加入当前参考，权利仍待确认。');
        }catch(error){if(current()){status.textContent=error.message+'；文件与输入已保留，可恢复同一操作。';submit.textContent=buffer.registered?'恢复素材读回':buffer.request?'恢复上传登记':'重试上传并加入参考';}}
        finally{buffer.busy=false;for(const update of buffer.listeners)update();}
      });dialog.showModal();
    }
    function renderReferences(){
      references.replaceChildren();advanced.querySelector('.classic-reference-manual')?.remove();
      if(!Object.keys(definition.slots).length)return;
      if(m!=='first_last')references.append(el('h3',imageMode?'参考图':'参考'));
      const slots=el('div',null,'classic-reference-slots');references.append(slots);
      for(const [role,type]of Object.entries(definition.slots)){
        const box=el('div',null,'classic-reference-slot');
        for(const [index,ref]of doc.references.entries()){if(ref.role!==role)continue;const media=options.media.find(row=>row.id===ref.media_id),thumb=el('figure',null,'classic-reference-thumb');
          const visual=el(type==='image'?'img':type==='video'?'video':'audio');visual.src=base(s.projectId)+'/media/'+encodeURIComponent(ref.media_id)+'/content';if(type==='image')visual.alt=media?.name||roles[role];else{visual.controls=true;visual.preload='metadata';}thumb.append(visual,el('figcaption',media?.name||roles[role]));
          const remove=button('×',()=>{const removed=doc.references.splice(index,1);if(media?.modality==='video'){removed.push(...doc.references.filter(r=>r.annotation_source_id===ref.media_id));doc.references=doc.references.filter(r=>r.annotation_source_id!==ref.media_id);}for(const item of removed){if(item.prompt_mention)doc.prompt=doc.prompt.split(item.prompt_mention).join('');doc.prompt=doc.prompt.split('[[ref:'+item.media_id+']]').join('');}doc.prompt=doc.prompt.trim();prompt.value=doc.prompt;mark();renderReferences();});remove.setAttribute('aria-label','移除'+(roles[role]||'此引用'));thumb.append(remove);box.append(thumb);}
        const chooser=el('details',null,'classic-reference-chooser'),toggle=el('summary');toggle.append(el('span','＋','classic-plus'),el('span',m==='first_last'?'添加'+roles[role]+'图':role==='reference_image'?'添加':roles[role]));chooser.append(toggle);
        const menu=el('div',null,'classic-reference-menu');menu.append(button('本地上传',()=>{chooser.open=false;openUpload(role,type);}),el('strong','导入资产'));chooser.append(menu);
        const select=el('select');select.setAttribute('aria-label',roles[role]||role);select.append(new Option('选择已登记的'+type,''));
        for(const media of options.media.filter(row=>row.modality===type))select.append(new Option(media.name||media.id,media.id));
        menu.append(select,button('添加'+(roles[role]||role),()=>{
          if(!select.value)return;const media=options.media.find(row=>row.id===select.value);
          if(doc.references.some(ref=>ref.role===role&&ref.media_id===media.id))return;
          if(!['reference_image','reference_video','reference_audio'].includes(role))doc.references=doc.references.filter(ref=>ref.role!==role);
          doc.references.push({role,media_id:media.id,sha256:media.sha256});mark();renderReferences();
        }));box.append(chooser);slots.append(box);
      }
      if(m==='omni'){
        const boxes=[...slots.children],menu=boxes[0]?.querySelector('.classic-reference-menu');
        for(const [index,box]of boxes.entries()){if(!index)continue;const chooser=box.querySelector('.classic-reference-chooser'),other=chooser?.querySelector('.classic-reference-menu');if(other&&menu){menu.append(el('strong',roles[Object.keys(definition.slots)[index]]));for(const child of [...other.children])if(child.tagName==='SELECT'||child.tagName==='BUTTON')menu.append(child);chooser.remove();if(!box.children.length)box.remove();}}
      }
      if(m==='first_last')references.append(button('交换首尾帧',()=>{for(const ref of doc.references)ref.role=ref.role==='first_frame'?'last_frame':'first_frame';mark();renderReferences();}));
      if(options.media_total>options.media.length)references.append(el('p','当前列出前 '+options.media.length+' 项素材；更早素材可从原素材库按 ID 定位。','hint'));
      if(Object.keys(definition.slots).length){
        const manual=el('input');manual.placeholder='已登记媒体 ID';manual.setAttribute('aria-label','更多固定媒体 ID');
        const role=el('select');for(const r of Object.keys(definition.slots))role.append(new Option(roles[r]||r,r));
        const manualDetails=el('details',null,'classic-reference-manual');manualDetails.append(el('summary','按素材编号添加'),manual,role,button('按 ID 添加引用',()=>{if(!manual.value.trim())return;doc.references.push({role:role.value,media_id:manual.value.trim()});mark();renderReferences();}));advanced.append(manualDetails);
      }
    }renderReferences();
    const editorHost=el('section');editorHost.hidden=true;form.append(editorHost);e.referenceBuffers||=new Map();
    async function openEditor(media,saved=null,fresh=false){referenceEditor?.suspend();const bufferKey=fresh?media.id+':'+crypto.randomUUID():saved?.document.edit.id||media.id;let buffer=e.referenceBuffers.get(bufferKey);if(!buffer){buffer={document:saved?clone(saved.document.edit):null,saved:saved||null,dirty:!saved};e.referenceBuffers.set(bufferKey,buffer);}editorHost.hidden=false;const module=await import('./reference-editor.js');if(!alive(n,s))return;referenceEditor=await module.createReferenceEditor(editorHost,{api:ctx.api,session:ctx.session,project:s.projectId,shot:s.shotId,mode:m,media,buffer,onNew:()=>openEditor(media,null,true),notice:ctx.notice,setRevision:ctx.setRevision,onAdd:item=>{if(!alive(n,s))return;const role=definition.slots.reference_image?'reference_image':Object.entries(definition.slots).find(([,kind])=>kind==='image')?.[0];if(!role)return ctx.notice('当前模式无图像参考，请切到图像或全能参考模式');if(!['reference_image'].includes(role))doc.references=doc.references.filter(r=>r.role!==role);if(!doc.references.some(r=>r.media_id===item.media_id)){const mention='[[ref:'+item.media_id+']] '+(item.source_modality==='video'?item.time_ms+'ms 视频帧标注':'图像标注')+'：'+buffer.document.description;doc.references.push({role,media_id:item.media_id,sha256:item.sha256,annotation_id:item.annotation_id,annotation_source_id:item.annotation_source_id,prompt_mention:mention});if(item.source_modality==='video'&&definition.slots.reference_video&&!doc.references.some(r=>r.media_id===item.annotation_source_id)){const source=options.media.find(r=>r.id===item.annotation_source_id);doc.references.push({role:'reference_video',media_id:source.id,sha256:source.sha256});}doc.prompt+=(doc.prompt?'\n':'')+mention;prompt.value=doc.prompt;options.media.push({id:item.media_id,sha256:item.sha256,modality:'image',name:'固定标注图'});mark();renderReferences();}}});}
    const editSource=el('select');editSource.setAttribute('aria-label','图像或视频标注来源');editSource.append(new Option('选择明确源媒体',''));for(const media of options.media.filter(r=>['image','video'].includes(r.modality)))editSource.append(new Option(media.name||media.id,media.id));advanced.append(editSource,button('打开图像或视频帧编辑',()=>{const source=options.media.find(r=>r.id===editSource.value);if(!source)throw new Error('先选择固定源媒体');return openEditor(source);}));
    for(const saved of options.reference_edits||[]){if(saved.document.mode!==m)continue;const source=options.media.find(r=>r.id===saved.document.edit.source_media_id)||{id:saved.document.edit.source_media_id};advanced.append(button('继续标注 '+saved.document.edit.time_ms+'ms · v'+saved.version,()=>openEditor(source,saved)));}

    function capture(){
      doc.model_id=model.value;doc.purpose=purpose.value;doc.prompt=prompt.value;
      for(const [id,{input,scale}]of Object.entries(numbers))doc[id]=Math.round(Number(input.value)*scale);
      try{doc.params=JSON.parse(params.value);e.paramsError=null;}catch{e.paramsError='模型参数不是有效 JSON，当前文本已保留。';}e.rawParams=params.value;
    }
    form.addEventListener('input',event=>{if(event.target===model||bounds.contains(event.target)||references.contains(event.target))return;capture();mark();});
    model.addEventListener('change',()=>{doc.model_id=model.value;doc.purpose='';syncCapabilities();capture();mark();});purpose.addEventListener('change',()=>{capture();mark();});
    const save=el('button','保存当前模式');save.type='submit';save.disabled=!session().writable||!session().actor;
    async function saveDraft(){
      capture();if(e.paramsError)throw new Error(e.paramsError);
      const submitted=clone(doc),version=editNo;save.disabled=true;
      try{
        const result=await write('drafts',{document:submitted,base_draft_id:e.saved?.id||null},s,n,m);
        e.saved={...result,document:submitted};if(version===editNo)e.dirty=false;
        if(alive(n,s))message.textContent=e.dirty?'草稿已保存，仍有后续未保存修改':'当前模式已保存';
      }catch(error){throw new Error(error.message+'；输入已保留。');}
      finally{if(alive(n,s))save.disabled=false;}
    }
    form.addEventListener('submit',async event=>{event.preventDefault();try{await saveDraft();}catch(error){if(alive(n,s))ctx.notice(error.message);}});
    const due=el('input'),stop=el('input'),attempts=el('input');due.type=stop.type='datetime-local';attempts.type='number';attempts.min='1';attempts.max='20';attempts.value='2';
    const date=minutes=>{const d=new Date(Date.now()+minutes*60000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};due.value=date(45);stop.value=date(60);
    const bounds=el('details');bounds.append(el('summary','本次执行范围与时限'));field(bounds,'首版目标时间',due);field(bounds,'停止新增任务时间',stop);field(bounds,'同用途最多尝试',attempts);advanced.append(bounds);
    runScope=createRunScopeControls(bounds,{api:ctx.api,session:ctx.session,projectId:s.projectId,onChange:()=>{editNo++;preview=null;propose.disabled=true;}});
    for(const input of [due,stop,attempts])input.addEventListener('input',()=>{editNo++;preview=null;propose.disabled=true;});
    const check=button('预览固定输入与用量',async()=>{
      if(e.dirty||!e.saved)await saveDraft();if(!alive(n,s))return;if(e.dirty)throw new Error('保存期间有新修改，请重新预览。');
      const version=editNo,request=runScope.apply({draft_version_id:e.saved.id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(attempts.value),max_repair_rounds:1}});check.disabled=true;
      try{
        const value=await ctx.api(base(s.projectId)+'/classic-production/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:request})});
        if(!alive(n,s)||version!==editNo)return;ctx.setRevision(value.revision,s.projectId);
        report.replaceChildren(el('h3',value.ready?'固定输入可制定运行方案':'需要处理的缺口'));
        for(const gap of value.gaps||[])report.append(el('p',gap.message||gapNames[gap.code]||gap.code));
        if(value.ready){preview={request,value};report.append(el('p','原生用量：'+JSON.stringify(value.generation_quote.native_units)),el('p',value.generation_quote.all_prices_known?'估算金额：'+JSON.stringify(value.generation_quote.known_subtotals):'金额未知；不表示免费。'));if(value.commerce_quote?.enabled){const charge=value.commerce_quote.commerce_charge;report.append(el('p',`商业额度上限 ${Object.values(charge.max_credits_by_operation).reduce((a,b)=>a+b,0)} · ${charge.account_actor||'项目共享额度'}`));}propose.disabled=false;}
      }catch(error){if(alive(n,s))ctx.notice(error.message);}
      finally{if(alive(n,s))check.disabled=false;}
    },!session().writable||!session().actor);
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
    advanced.append(save,recover,refresh,message);
    const parameters=el('details',null,'classic-parameters');parameters.append(el('summary','⚙ '+(imageMode?doc.width+' × '+doc.height:doc.duration_ms/1000+'s')+' · '+doc.count+' 个候选'),numeric);
    const actions=el('div',null,'classic-actions');check.className='classic-primary';check.textContent='预览生成';check.setAttribute('aria-label','预览固定输入与用量');propose.className='classic-propose';
    actions.append(parameters,check);form.append(advanced,actions,propose,report);
    // Keep visual order close to the source UI while preserving the original save/preview boundary.
    if(m==='first_last')form.prepend(references);else modelSection.append(references);
    const resultHeader=el('header',null,'classic-result-header'),count=el('span','共 0 条结果','hint');resultHeader.append(el('h2','生成结果'),count,button('候选与审阅',()=>ctx.navigate('candidates',s.shotId)));aside.append(resultHeader);
    const candidateGrid=el('div',null,'classic-candidate-grid'),addMedia=button('',()=>ctx.navigate('media',s.shotId));addMedia.className='classic-result-add';addMedia.append(el('span','＋'),el('span',imageMode?'添加':'上传视频'));candidateGrid.append(addMedia);aside.append(candidateGrid);
    ctx.api(base(s.projectId)+'/workbench?section=candidates&object_id='+encodeURIComponent(s.shotId)+'&limit=24').then(value=>{
      if(!alive(n,s))return;
      const rows=value.sections?.candidates?.items||[];count.textContent='共 '+rows.length+' 条结果';
      for(const row of rows){const box=el('article',null,'classic-candidate'),visual=el(imageMode?'img':'video');visual.src=base(s.projectId)+'/media/'+encodeURIComponent(row.media_id)+'/content';if(imageMode)visual.alt=row.title||row.name||'分镜候选';else{visual.controls=true;visual.preload='metadata';}box.append(visual,el('p',row.title||row.name||purposeNames[row.purpose]||'镜头候选'),button('查看与使用素材',()=>ctx.media(row.media_id)),button('复用此候选原配置',async()=>{const value=await ctx.api(base(s.projectId)+'/classic-production/candidate-configuration?shot_id='+s.shotId+'&media_id='+row.media_id);if(!alive(n,s))return;if(!value.available)throw new Error(value.reason);const target=entry(value.document.mode);target.document=clone(value.document);target.dirty=true;mode=value.document.mode;editNo++;render();}));candidateGrid.append(box);}
    }).catch(error=>{if(alive(n,s))aside.append(el('p','候选读取未完成：'+error.message));});
  }
  function renderEmpty(s,n){
    root.classList.add('classic-production');const noun=s.productionKind==='image'?'分镜':'视频',heading=el('header',null,'classic-heading'),rail=el('nav',null,'classic-shot-rail'),body=el('div',null,'classic-layout'),left=el('section',null,'classic-form'),right=el('aside',null,'classic-results');
    heading.append(el('h1','所有'+noun),rail);left.append(el('h2','生成'+noun+'方式'));const model=field(left,'模型',el('select'));model.append(new Option('新增'+noun+'后选择模型',''));model.disabled=true;const prompt=field(left,'提示词',el('textarea'));prompt.placeholder='新增'+noun+'后开始创作…';prompt.disabled=true;prompt.rows=10;
    const add=button('',()=>s.episodeId?createFirstShot():ctx.navigate('project',null));add.className='classic-shot classic-add-shot';add.append(el('span','＋'),el('span',s.episodeId?'新增'+noun:'选择剧集'));rail.append(add);left.append(el('p',s.episodeId?'先新增一个'+noun+'，开始添加参考和提示词。':'请先选择要制作的剧集。','classic-empty-message'));right.append(el('h2','生成结果'),el('p','暂无生成结果','classic-empty-message'));body.append(left,right);root.replaceChildren(heading,body);
    function createFirstShot(){
      const owner=session().identityId||session().actor||'',bufferKey=[s.projectId,s.episodeId,owner,'first-shot'].join(':'),storageKey='vsc.classic-first-shot:'+bufferKey;let stored=null;try{stored=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{}
      const buffer=drafts.get(bufferKey)||{names:stored?.names||{scene:'场景1',sequence:'镜组1',shot:noun+'1'},items:Array.isArray(stored?.items)?stored.items:[],busy:false,listeners:new Set()};drafts.set(bufferKey,buffer);
      const retain=()=>{try{sessionStorage.setItem(storageKey,JSON.stringify({names:buffer.names,items:buffer.items}));}catch{throw new Error('浏览器无法保存创建回执，请恢复本机存储后继续。');}};
      const dialog=el('dialog',null,'classic-upload-dialog'),form=el('form'),header=el('header'),status=el('p',null,'classic-upload-status');dialog.setAttribute('aria-label','新增'+noun);status.setAttribute('role','status');header.append(el('h2','新增'+noun),button('关闭',()=>dialog.close()));dialog.append(header,form);root.append(dialog);
      const current=()=>alive(n,s)&&(session().identityId||session().actor||'')===owner&&dialog.open&&dialog.isConnected,fields={};
      for(const [kind,label]of [['scene','场景名称'],['sequence','镜组名称'],['shot','镜头名称']]){const input=field(form,label,el('input'));input.value=buffer.names[kind];input.required=true;input.addEventListener('input',()=>buffer.names[kind]=input.value);fields[kind]=input;}
      const submit=el('button',buffer.items.length?'继续创建':'创建并开始制作');submit.type='submit';submit.className='classic-primary';form.append(status,submit);
      const lock=()=>{for(const input of Object.values(fields))input.disabled=buffer.busy||buffer.items.length>0;submit.disabled=buffer.busy||!session().actor||!session().writable;};buffer.listeners.add(lock);lock();dialog.addEventListener('close',()=>{buffer.listeners.delete(lock);dialog.remove();});
      form.addEventListener('submit',async event=>{
        event.preventDefault();if(buffer.busy)return;if(!session().actor||!session().writable){status.textContent='当前会话只读。';return;}if(Object.values(buffer.names).some(value=>!value.trim())){status.textContent='请填写场景、镜组和镜头名称。';return;}
        buffer.busy=true;lock();status.textContent='正在创建镜头…';
        try{
          const tree=await ctx.api(base(s.projectId)+'/tree');if(!current())return;if(!tree.nodes.some(row=>row.id===s.episodeId&&row.kind==='episode'))throw new Error('当前剧集不可用，请重新选择剧集。');ctx.setRevision(tree.revision,s.projectId);
          if(!buffer.items.length){const ids={scene:crypto.randomUUID(),sequence:crypto.randomUUID(),shot:crypto.randomUUID()},ordinal=Math.max(0,...tree.nodes.filter(row=>row.kind==='scene'&&row.parent_id===s.episodeId).map(row=>Number(row.ordinal)||0))+1;for(const kind of ['scene','sequence','shot'])buffer.items.push({payload:{id:ids[kind],kind,parent_id:kind==='scene'?s.episodeId:kind==='sequence'?ids.scene:ids.sequence,display_code:({scene:'SC',sequence:'SQ',shot:'SH'})[kind]+'-'+ids[kind].slice(0,8),title:buffer.names[kind].trim(),ordinal:kind==='scene'?ordinal:1},key:crypto.randomUUID(),request:null,result:null});}
          retain();for(const item of buffer.items){if(!current())return;if(item.result)continue;item.request||={payload:item.payload,expected_revision:session().revision,idempotency_key:item.key};retain();try{item.result=await ctx.api(base(s.projectId)+'/objects',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(item.request)});}catch(error){if(error.status>=400&&error.status<500){item.request=null;retain();}throw error;}retain();if(current())ctx.setRevision(item.result.revision,s.projectId);}
          if(!current())return;dialog.close();if(await load({...s,objectId:buffer.items[2].payload.id,shotId:buffer.items[2].payload.id,shots:null})){sessionStorage.removeItem(storageKey);drafts.delete(bufferKey);}
        }catch(error){if(current()){status.textContent=error.message+'；已创建对象与输入保留，继续时不会重复创建。';submit.textContent='继续创建';}}
        finally{buffer.busy=false;for(const update of buffer.listeners)update();}
      });dialog.showModal();
    }
  }
  async function load(value){
    const n=++epoch;preview=null;scope={...value};const s=scope;
    closeDialogs();root.replaceChildren(el('p','正在读取经典制作…'));
    try{
      const query=new URLSearchParams({section:'shots',limit:'100',...(value.objectId?{object_id:value.objectId}:value.episodeId?{object_id:value.episodeId}:{})});
      const listing=await ctx.api(base(s.projectId)+'/workbench?'+query);
      if(!alive(n,s))return;
      const page=listing.sections.shots;
      s.episodeId=value.episodeId||(listing.scope.kind==='episode'?listing.scope.id:listing.ancestors.find(row=>row.kind==='episode')?.id)||null;
      s.shots=value.shots?.length?value.shots:page.items;
      s.shotId=value.shotId||(listing.scope.kind==='shot'?listing.scope.id:page.items[0]?.id);
      if(!s.shotId){renderEmpty(s,n);return;}
      const data=await ctx.api(base(s.projectId)+'/classic-production?shot_id='+encodeURIComponent(s.shotId));
      if(!alive(n,s))return;
      options=data;const kind=value.productionKind||'video';if(value.mode&&data.modes[value.mode])mode=value.mode;else if(!data.modes[mode]||data.modes[mode].modality!==kind)mode=Object.keys(data.modes).find(k=>data.modes[k].modality===kind)||Object.keys(data.modes)[0];if(data.sibling_shots?.length)s.shots=data.sibling_shots;ctx.setRevision(data.revision,s.projectId);ctx.onShot?.(s.shotId,s.episodeId);render();
      if(page.next_offset!=null||page.truncated)root.append(el('p','当前显示前 100 镜；其余镜头可从原场镜工作台定位后进入。','hint'));
      return true;
    }catch(error){if(alive(n,s))root.replaceChildren(el('h1','经典制作读取未完成'),el('p',error.message),button('重新读取',()=>load(value)));}
  }
  return {load,suspend(){runScope?.dispose();referenceEditor?.suspend();epoch++;preview=null;closeDialogs();}};
}
