// Inputs stay with their project/episode/tool; execution uses original run and edit consumers.
import {createRunScopeControls} from './run-scope-controls.js';
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
export function createCreativeTools(root,ctx){
  let ticket=0,scope=null,data=null,mode='mv',busy=false,preview=null,runScope=null,standaloneModeInitialized=false;
  const drafts=new Map(),pending=new Map();
  const identity=()=>ctx.session().identityId||ctx.session().actor||'';
  const pendingKey='vsc.creative-tool-requests:v1';
  try{for(const [key,value]of JSON.parse(sessionStorage.getItem(pendingKey)||'[]'))pending.set(key,value);}catch{}
  const persistPending=()=>{sessionStorage.setItem(pendingKey,JSON.stringify([...pending]));};
  const endpoint=(p,path='')=>`/api/v1/projects/${encodeURIComponent(p)}/creative-tools${path}`;
  const active=(t,s)=>ticket===t&&scope===s&&s?.identity===identity();
  const writable=()=>ctx.session().actor&&ctx.session().writable;
  const key=()=>`${ctx.session().actor||''}:${scope.project}:${data.episode.id}:${mode}`;
  function button(label,action,disabled=false){const b=el('button',label);b.type='button';b.disabled=disabled;b.addEventListener('click',async()=>{const t=ticket,s=scope;try{await action();}catch(e){if(active(t,s))ctx.notice(e.message+'；当前输入保留。');}});return b;}
  function field(parent,label,node){const box=el('label',label,'creative-tool-field');node.setAttribute('aria-label',label);box.append(node);parent.append(box);return node;}
  function select(parent,label,items,value,change){const node=el('select');for(const [id,title]of items)node.append(new Option(title,id));node.value=value||'';node.addEventListener('change',()=>change(node.value));field(parent,label,node);return node;}
  function input(parent,label,value,change,type='text'){const node=el('input');node.type=type;node.value=value??'';node.addEventListener('input',()=>change(type==='number'?Number(node.value):node.value));field(parent,label,node);return node;}
  function area(parent,label,value,change,rows=4){const node=el('textarea');node.rows=rows;node.value=value||'';node.addEventListener('input',()=>change(node.value));field(parent,label,node);return node;}
  function current(){const k=key();if(!drafts.has(k)){const old=data.drafts.find(d=>d.document.input.tool===mode);drafts.set(k,{value:old?structuredClone(old.document.input):{tool:mode,episode_id:data.episode.id,title:'',prompt:'',lyrics:'',lrc:'',style:'',model_id:'',shot_id:'',source_media_id:'',audio_media_id:'',visual_media_ids:[],ranges:[],segments:[],params:{},keep_original:false,music_start_ms:0,music_end_ms:0,audio_in_ms:0,duration_ms:5000,dimensions:[],script_line_ids:[],voice_media_id:''},base:old?.id||null,dirty:false,raw:{}});}return drafts.get(k);}
  const change=(row,name,value)=>{row.value[name]=value;row.dirty=true;preview=null;};
  function jsonField(parent,label,row,name){const node=area(parent,label,row.raw[name]??JSON.stringify(row.value[name],null,2),v=>{row.raw[name]=v;row.dirty=true;preview=null;},4);return node;}
  function document(row){const value=structuredClone(row.value);for(const [name,raw]of Object.entries(row.raw)){if(name==='visual_segments')continue;try{value[name]=JSON.parse(raw);}catch{throw new Error(name+' 需要有效 JSON，输入没有丢失');}}if(row.raw.visual_segments!=null){try{value.params.visual_segments=JSON.parse(row.raw.visual_segments);}catch{throw new Error('逐段画面需要有效JSON，输入已保留');}}return value;}
  async function targetPost(project,path,payload,revision){const who=identity(),tag=JSON.stringify([who,project,path,payload]),request=pending.get(tag)||{key:crypto.randomUUID(),revision};pending.set(tag,request);persistPending();
    try{const result=await ctx.api(endpoint(project,path),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},body:JSON.stringify({payload,expected_revision:request.revision,idempotency_key:request.key})});pending.delete(tag);persistPending();return result;}catch(e){if(e.status>=400&&e.status<500){pending.delete(tag);persistPending();}throw e;}}
  async function post(path,payload,mutation=true){const s=scope,t=ticket;if(!active(t,s))throw new Error('身份或范围已改变，请重新读取');if(mutation&&!writable())throw new Error('当前会话只读');if(busy)throw new Error('上一操作仍在处理中');busy=true;
    try{const result=mutation?await targetPost(s.project,path,payload,ctx.session().revision):await ctx.api(endpoint(s.project,path),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},body:JSON.stringify({payload})});if(active(t,s)&&result.revision!=null)ctx.setRevision(result.revision,s.project);return result;}finally{if(active(t,s))busy=false;}}

  function uploadForm(t,s){const box=el('details');box.append(el('summary','上传图片、音频或视频'));
    const file=el('input');file.type='file';file.accept='image/*,audio/*,video/*';field(box,'选择本机文件',file);
    const rights=select(box,'文件权利状态',[['unknown','待确认'],['owned','我拥有权利'],['licensed','已获授权']],'unknown',()=>{});
    const evidence=area(box,'来源或授权说明','',()=>{},2),purposes=input(box,'允许用途（逗号分隔）','video_take,music,composition',()=>{});
    box.append(button('上传并登记素材',async()=>{if(!file.files[0])throw new Error('请选择本机文件');const selected=file.files[0];if(!evidence.value.trim())throw new Error('请填写来源或授权说明');const allowed=purposes.value.split(',').map(x=>x.trim()).filter(Boolean);if(rights.value!=='unknown'&&!allowed.length)throw new Error('请明确允许用途');
      const staged=await ctx.api(`/api/v1/projects/${s.project}/uploads`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(selected.name),'X-CSRF-Token':ctx.session().csrf},body:selected});if(!active(t,s))return;
      const payload={staged_upload:staged.staged_upload,name:selected.name,rights:rights.value,rights_scope:{purposes:allowed},source:{kind:'user-upload',content:evidence.value}};
      const tag=JSON.stringify([identity(),s.project,'@media',payload]),request=pending.get(tag)||{key:crypto.randomUUID(),revision:ctx.session().revision};pending.set(tag,request);persistPending();
      try{const result=await ctx.api(`/api/v1/projects/${s.project}/media`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},body:JSON.stringify({payload,expected_revision:request.revision,idempotency_key:request.key})});pending.delete(tag);persistPending();if(active(t,s)){ctx.setRevision(result.revision,s.project);await load(s);ctx.notice('素材已登记，可直接选择本机加工工具。');}}catch(e){if(e.status>=400&&e.status<500){pending.delete(tag);persistPending();}throw e;}
    },!writable()));return box;
  }

  function transferForm(section,output,item,t,s){const box=el('details');box.append(el('summary','导入到目标作品'));
    const destinations=(ctx.projects?.()||[]).filter(row=>row.id!==s.project&&!row.read_only&&!['vsc.text-tools','vsc.creative-tools'].includes(row.profile)&&!['vsc.text-tools','vsc.creative-tools'].includes(row.profile_id));
    let version=0,selectedPreview=null;
    const project=select(box,'目标作品',[['','请选择作品'],...destinations.map(row=>[row.id,row.name])],'',async value=>{const n=++version;selectedPreview=null;out.replaceChildren();episode.replaceChildren(new Option('请选择一集',''));if(!value)return;try{const tree=await ctx.api(`/api/v1/projects/${value}/tree`);if(!active(t,s)||n!==version)return;for(const row of tree.nodes.filter(r=>r.kind==='episode'))episode.append(new Option(row.title||row.display_code,row.id));}catch(e){if(active(t,s))ctx.notice(e.message);}});
    const episode=select(box,'目标集',[['','请选择一集']],'',()=>{version++;selectedPreview=null;out.replaceChildren();});
    const purpose=select(box,'目标音轨用途',[['music','音乐'],['ambience','环境'],['sfx','音效'],['dialogue_dry','对白（原混合音轨，需人工核对）']],'music',()=>{version++;selectedPreview=null;out.replaceChildren();});purpose.parentElement.hidden=item.modality!=='audio';
    const out=el('div');box.append(button('预览固定输出导入',async()=>{if(!project.value||!episode.value)throw new Error('选择目标作品及实际一集');const n=version,request={source_project_id:s.project,source_artifact_id:output.id,source_media_id:item.id,sha256:item.sha256,episode_id:episode.value,audio_purpose:purpose.value};
      const preview=await ctx.api(endpoint(project.value,'/import-preview'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},body:JSON.stringify({payload:request})});if(!active(t,s)||n!==version)return;selectedPreview={request,preview,project:project.value};out.replaceChildren(el('p',`${preview.source_name} · ${preview.sha256.slice(0,12)} · ${preview.action}`),button('确认导入到此集工作稿',async()=>{const fixed=selectedPreview;if(!fixed||n!==version)throw new Error('目标已改变，请重新预览');const result=await targetPost(fixed.project,'/import-output',{request:fixed.request,preview_sha256:fixed.preview.preview_sha256},fixed.preview.revision);if(!active(t,s)||n!==version)return;out.replaceChildren(el('p',result.already_imported?'已恢复原导入，未重复添加。':'已导入原剪辑工作稿，权利仍待确认。'),button('打开目标集剪辑',()=>ctx.navigate('editing',fixed.request.episode_id,fixed.project)));},!writable()));
    },!writable()),out);section.append(box);
  }
  async function save(row){const t=ticket,s=scope,value=document(row),sent=JSON.stringify(value);const result=await post('/drafts',{document:value,base_draft_id:row.base});row.base=result.id;let unchanged=false;try{unchanged=JSON.stringify(document(row))===sent;}catch{}if(unchanged){row.value=value;row.raw={};row.dirty=false;}if(active(t,s))ctx.notice(unchanged?'工具输入已保存，可刷新读回。':'先前输入已保存，保存期间的新修改仍保留，请继续保存。');return result;}
  async function saved(row){if(row.dirty||!row.base)await save(row);if(row.dirty)throw new Error('保存期间输入有新修改，请先保存当前内容');return row.base;}
  function resultHost(){const box=root.querySelector('.creative-tool-records')||root;box.querySelector('.creative-tool-results-empty')?.remove();return box;}
  function render(){root.replaceChildren();root.classList.add('creative-tools');root.append(el('h1','音乐与视频工具'),el('p',data.standalone?'个人工具：上传后直接加工，无需创建影视项目。输出可明确导入目标作品。':'生成、输入草稿、MV 镜头计划与原剪辑共享项目中的素材和任务。','hint'));
    const top=el('div',null,'creative-tool-actions');top.append(button('重新读取（保留未存输入）',()=>load(scope)),button('恢复服务端当前稿',()=>{if(data?.episode){drafts.delete(key());preview=null;render();}},!data?.episode));root.append(top);
    top.append(button('恢复未确认操作',async()=>{const t=ticket,s=scope,who=identity();let recovered=0;for(const [tag,intent]of [...pending]){const [owner,project,path,payload]=JSON.parse(tag);if(owner!==who)continue;if(path==='/import-output'?payload.request?.source_project_id!==s.project:project!==s.project)continue;const route=path==='@media'?`/api/v1/projects/${project}/media`:endpoint(project,path);const result=await ctx.api(route,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf},body:JSON.stringify({payload,expected_revision:intent.revision,idempotency_key:intent.key})});pending.delete(tag);persistPending();recovered++;if(!active(t,s))return;if(project===s.project)ctx.setRevision(result.revision,project);}if(active(t,s)){await load(s);ctx.notice(recovered?'已恢复原请求回执，未创建重复加工或导入。':'当前身份没有待恢复的操作。');}},!writable()));root.append(uploadForm(ticket,scope));
    if(!data.standalone)select(root,'当前集',[['','请选择一集'],...data.episodes.map(x=>[x.id,x.title||x.display_code])],data.episode?.id,v=>ctx.navigate('creative-tools',v||null,scope.project));if(!data.episode)return;
    select(root,'工具',data.tools.map(x=>[x.id,x.label+(x.mode==='draft_only'?' · 输入草稿':'')]),mode,v=>{mode=v;scope.tool=v;ticket++;busy=false;preview=null;render();});
    const capability=data.tools.find(x=>x.id===mode),row=current(),value=row.value,t=ticket,s=scope;root.dataset.tool=mode;
    root.append(el('p',capability.reason|| (mode==='mv'?'根据明确时码编译镜头；结果可编辑、保存并导入本集。':mode==='music_mix'?'完整音频保留，使用区间送入原剪辑合成。':'先保存输入，再预览固定用量及制作方案。'),'creative-tool-capability'));
    const form=el('div',null,'creative-tool-form');root.append(form);
    input(form,'方案名称',value.title,v=>change(row,'title',v));
    area(form,mode==='speech'?'配音原文（必须对应已确认台词）':'提示词 / 视觉要求',value.prompt,v=>change(row,'prompt',v));
    if(['music_description','music_lyrics','instrumental','music_mix','mv'].includes(mode))area(form,'音乐 / 视觉风格',value.style,v=>change(row,'style',v),2);
    const media=(types)=>[['','请选择素材'],...data.media.filter(x=>types.includes(x.modality)).map(x=>[x.id,`${x.name} · ${x.duration_ms==null?'时长待核验':(x.duration_ms/1000)+' 秒'}`])];
    if(!['music_description','ambience','music_lyrics','instrumental','lyrics','speech','voice','sfx','mv'].includes(mode))select(form,'源视频',media(['video']),value.source_media_id,v=>change(row,'source_media_id',v));
    if(['mv','music_mix'].includes(mode))select(form,'完整音乐音频',media(['audio']),value.audio_media_id,v=>change(row,'audio_media_id',v));
    if(['lyrics','music_lyrics','mv'].includes(mode))area(form,'歌词正文',value.lyrics,v=>change(row,'lyrics',v));
    if(mode==='lyrics'){
      area(form,'歌词风格要求',value.style,v=>change(row,'style',v),2);
      const fresh=el('input');fresh.type='checkbox';field(form,'明确发起新的歌词尝试（已有未知调用先查询，不重发）',fresh);
      form.append(button('保存并请求歌词建议',async()=>{const id=await saved(row);if(!active(t,s))return;const result=await post('/lyrics',{draft_version_id:id,new_attempt:fresh.checked});if(active(t,s)){ctx.notice(result.status==='completed'?'歌词建议已返回，尚未覆盖人工稿。':result.status==='submission_unknown'?'原歌词调用结果未知，保留原请求，不重复调用。':'歌词调用状态：'+result.status);await load(s);}},!writable()||capability.mode!=='text_host'));
    }
    if(mode==='mv'){
      area(form,'LRC（有时码的歌词；没有时码请编辑段落）',value.lrc,v=>change(row,'lrc',v));
      const refs=el('fieldset');refs.append(el('legend','视觉参考'));for(const item of data.media.filter(x=>['image','video'].includes(x.modality))){const box=el('input');box.type='checkbox';box.checked=value.visual_media_ids.includes(item.id);box.addEventListener('change',()=>change(row,'visual_media_ids',box.checked?[...row.value.visual_media_ids,item.id]:row.value.visual_media_ids.filter(v=>v!==item.id)));field(refs,item.name,box);}form.append(refs);
      jsonField(form,'可编辑段落 [{start_ms,end_ms,title,lyrics,prompt}]',row,'segments');
      const beats=input(form,'每段观测起音数（2–32）',8,()=>{},'number');
      form.append(button('保存并提取本机起音与段落建议',async()=>{const id=await saved(row);if(!active(t,s))return;const result=await post('/analyze-music',{draft_version_id:id,beats_per_segment:Number(beats.value)});if(active(t,s)){ctx.notice(result.already_analyzed?'已读回原音频分析，未重复解码。':'技术起音建议已保存；请比较并接受后再编辑段落。');await load(s);}},!writable()));
      form.append(el('p','节拍分析限10分钟：以20ms音量变化检测起音，BPM可能倍速/半速；段落不是主歌/副歌识别，也不对齐普通歌词。','hint'));
      const visuals=el('details');visuals.append(el('summary','每段实际画面与MV剪辑'));
      area(visuals,'逐段画面 [{media_id,in_ms}]（顺序与段落一致）',row.raw.visual_segments??JSON.stringify(value.params.visual_segments||[],null,2),raw=>{row.raw.visual_segments=raw;row.dirty=true;preview=null;});
      const diff=el('div');visuals.append(button('预览段落与音乐回本集剪辑',async()=>{const id=await saved(row);if(!active(t,s))return;const request={draft_version_id:id},out=await post('/mv-edit-preview',request,false);if(!active(t,s))return;diff.replaceChildren(el('pre',JSON.stringify(out.plan,null,2)),button('确认写入MV剪辑工作稿',async()=>{if(row.dirty||row.base!==id)throw new Error('输入已改变，请重新保存并预览');await post('/mv-edit',{request,preview_sha256:out.preview_sha256});if(active(t,s))ctx.navigate('editing',data.episode.id,s.project);},!writable()));}),diff);form.append(visuals);
      form.append(button('编译镜头计划',async()=>{const result=await post('/compile-mv',{document:document(row)},false);if(!active(t,s))return;change(row,'segments',result.plan.shots.map(({start_ms,end_ms,title,lyrics,prompt})=>({start_ms,end_ms,title,lyrics,prompt})));delete row.raw.segments;render();const table=el('table');const heading=el('tr');for(const title of ['段落','开始–结束（秒）','歌词','视觉要求'])heading.append(el('th',title));table.append(heading);for(const shot of result.plan.shots){const tr=el('tr');for(const text of [shot.title,`${shot.start_ms/1000}–${shot.end_ms/1000}`,shot.lyrics,shot.prompt])tr.append(el('td',text));table.append(tr);}resultHost().append(table);}),button('保存并导入本集镜头计划',async()=>{const id=await saved(row);if(!active(t,s))return;const result=await post('/import-mv',{draft_version_id:id});if(active(t,s))ctx.notice(`已导入 ${result.shot_ids.length} 个镜头；镜头计划仍待确认，未生成视频。`);},!writable()));
    }
    if(mode==='music_mix'){
      for(const [name,label]of [['music_start_ms','配乐在视频开始（毫秒）'],['music_end_ms','配乐在视频结束（毫秒）'],['audio_in_ms','完整音频裁入点（毫秒）']])input(form,label,value[name],v=>change(row,name,v),'number');
      const keep=el('input');keep.type='checkbox';keep.checked=value.keep_original;keep.addEventListener('change',()=>change(row,'keep_original',keep.checked));field(form,'保留原视频声音（原声 100%，配乐 70%；关闭时配乐 100%）',keep);
      form.append(el('p','下方操作以本源片和配乐替换本集剪辑布局，原剪辑版本可恢复；不会重新生成画面。','hint'),button('保存并写为本集新剪辑版本',async()=>{const id=await saved(row);if(!active(t,s))return;const edit=await ctx.api(`/api/v1/projects/${encodeURIComponent(s.project)}/edit-workspace?episode_id=${encodeURIComponent(data.episode.id)}`);if(!active(t,s))return;ctx.setRevision(edit.project_revision,s.project);await post('/apply-music',{draft_version_id:id,edit_revision:edit.workspace?.revision||0});if(active(t,s))ctx.navigate('editing',data.episode.id,s.project);},!writable()));
    }
    if(['speech','music_description','ambience','sfx','video_edit','video_extend'].includes(mode)){
      select(form,'归属镜头',[['','请选择镜头'],...data.shots.map(x=>[x.id,x.title||x.display_code])],value.shot_id,v=>change(row,'shot_id',v));
      select(form,'实际模型',[['','请选择模型'],...data.models.filter(x=>x.modality===capability.modality).map(x=>[x.id,x.name+(!x.enabled?' · 未启用':!x.adapter_available?' · 待接入':'')])],value.model_id,v=>change(row,'model_id',v));
      if(mode==='video_edit')form.append(el('p','编辑作用于完整源片，长度跟随源片；已有替换视频可用“已有片段区间替换”处理指定区间。','hint'));
      if(['music_description','ambience','sfx'].includes(mode))form.append(el('p','Seed-Audio 生成完整声音候选。用途为制作意图，不保证仅有音乐或音效，也不保证提示中的精确时长。MediaKit 服务权限与实际效果待验证。','hint'));
      if(mode==='video_extend')input(form,'新增时长（毫秒，2–10 整秒）',value.duration_ms,v=>change(row,'duration_ms',v),'number');
      if(mode==='speech'){jsonField(form,'固定台词编号',row,'script_line_ids');select(form,'已选音色参考（可选）',media(['audio']),value.voice_media_id,v=>change(row,'voice_media_id',v));}
      const local=minutes=>{const d=new Date(Date.now()+minutes*60000);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,16);};
      runScope?.dispose();runScope=createRunScopeControls(form,{api:ctx.api,session:ctx.session,projectId:scope.project,onChange:()=>{preview=null;}});
      const due=input(form,'首版目标时间',local(45),()=>{preview=null;},'datetime-local'),stop=input(form,'停止新增提交时间',local(60),()=>{preview=null;},'datetime-local'),attempts=input(form,'同用途最大尝试次数',2,()=>{preview=null;},'number');
      form.append(button('保存并预览用量',async()=>{const id=await saved(row);if(!active(t,s))return;const request=runScope.apply({draft_version_id:id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(attempts.value),max_repair_rounds:1}});const result=await post('/preview',request,false);if(!active(t,s))return;preview={request,...result};const out=el('pre',JSON.stringify(result.ready?{generation:result.generation_quote,commerce:result.commerce_quote}:result.gaps,null,2));const detail=el('details');detail.append(el('summary','输入与用量明细'),out);resultHost().append(el('p',result.ready?'输入已就绪，可以保存制作方案。':'请处理输入检查提示。'),detail);if(result.ready)resultHost().append(button('保存待确认制作方案',async()=>{if(!preview||row.dirty)throw new Error('输入已改变，请重新预览');await post('/run-proposals',{request:preview.request,preview_sha256:preview.preview_sha256});if(active(t,s))ctx.notice('制作方案已保存；沿原确认、预算和任务入口继续。');},!writable()));},!writable()));
    }
    if(['extract_frame','separate_audio','remove_subtitles','remove_watermark','segment_remake'].includes(mode)){
      form.append(el('p','实际本机加工：单次限10分钟/1600万像素，源片保持不变。成功结果刷新可回读；重试同一保存稿不重复处理。','hint'));
      const param=(name,v)=>{change(row,'params',{...row.value.params,[name]:v});delete row.raw.params;};
      if(mode==='segment_remake'){
        select(form,'已存在的替换视频',media(['video']),value.replacement_media_id,v=>change(row,'replacement_media_id',v));
        input(form,'替换片剪入点（毫秒）',value.params.replacement_in_ms||0,v=>param('replacement_in_ms',v),'number');
        select(form,'替换时的音轨规则',[['keep_source','默认保留整条原音轨'],['replace','仅替换区间使用替换片音轨（无音轨则静音）']],value.params.audio_mode||'keep_source',v=>param('audio_mode',v));
        form.append(el('p','下方填写1–5个不重叠源区间，须对齐源帧边界。替换片从剪入点连续取用，不拉伸或静默循环；总时长不变。区间外保留内容，输出重新编码；此操作不生成新画面。','hint'));
      }
      if(mode==='extract_frame'){
        select(form,'提取帧',[['first','首帧'],['last','尾帧'],['current','当前时码']],value.params.frame_mode||'first',v=>param('frame_mode',v));
        input(form,'当前时码（毫秒）',value.params.time_ms||0,v=>param('time_ms',v),'number');
      }
      if(['remove_subtitles','remove_watermark'].includes(mode)){
        form.append(el('p','填写源画面像素矩形及明确时间区间；边界插值不等于恢复原画。区间外画面内容保留，视频会重新编码。','hint'));
        for(const [name,label]of [['x','区域左侧像素'],['y','区域顶部像素'],['width','区域宽度像素'],['height','区域高度像素']])input(form,label,value.params.rectangle?.[name]??(name==='width'||name==='height'?20:10),v=>param('rectangle',{x:10,y:10,width:20,height:20,...row.value.params.rectangle,[name]:v}),'number');
        const a=input(form,'处理开始（毫秒）',value.ranges[0]?.start_ms??0,()=>{},'number'),b=input(form,'处理结束（毫秒）',value.ranges[0]?.end_ms??1000,()=>{},'number');
        const range=()=>{change(row,'ranges',[{start_ms:Number(a.value),end_ms:Number(b.value)}]);delete row.raw.ranges;};a.oninput=range;b.oninput=range;
        if(!value.params.rectangle){value.params.rectangle={x:10,y:10,width:20,height:20};row.dirty=true;}if(!value.ranges.length){value.ranges=[{start_ms:0,end_ms:1000}];row.dirty=true;}
      }
      form.append(button('保存并执行本机加工',async()=>{const id=await saved(row);if(!active(t,s))return;const result=await post('/process-local',{draft_version_id:id});if(!active(t,s))return;ctx.notice(result.already_processed?'已恢复原加工结果，未重复处理。':'实际输出已登记素材库；可继续送入镜头、画布或剪辑。');await load(s);},!writable()));
    }
    const more=el('details');more.append(el('summary','加工范围与扩展输入'));
    if(mode==='breakdown')for(const [id,label]of [['storyboard','分镜'],['video','视频'],['audio','音频']]){const box=el('input');box.type='checkbox';box.checked=value.dimensions.includes(id);box.addEventListener('change',()=>change(row,'dimensions',box.checked?[...value.dimensions,id]:value.dimensions.filter(x=>x!==id)));field(more,label,box);}
    jsonField(more,'处理区间 [{start_ms,end_ms}]',row,'ranges');jsonField(more,'工具参数 / 区域 / 遮罩（素材编号）',row,'params');form.append(more);
    form.append(button('保存工具输入',async()=>{await save(row);if(active(t,s))render();},!writable()),el('p',row.base?'已有固定草稿版本，可刷新或切换工具后继续。':'尚未保存。','hint'));
    if(data.media_total>data.media.length)form.append(el('p',`当前显示前 ${data.media.length} 个素材；更多素材请先从素材库整理。`,'hint'));
    for(const result of (data.music_results||[]).filter(r=>mode==='lyrics'?r.kind==='lyrics':mode==='mv'&&r.kind==='beats')){
      const section=el('section',null,'creative-tool-suggestion');section.append(el('h2',result.kind==='lyrics'?'歌词单次建议':'实际起音与段落建议'),el('p','状态：'+result.status));
      const suggestion=result.kind==='lyrics'?result.result?.suggestion:result.analysis;section.append(el('pre',JSON.stringify(suggestion||result.result||{request_id:result.id,status:result.status},null,2)));
      if(result.kind==='lyrics')section.append(button('查询此原歌词请求',async()=>{const out=await ctx.api(endpoint(s.project,'/lyrics/'+result.id));if(active(t,s)){ctx.setRevision(out.revision,s.project);ctx.notice('原请求状态：'+out.status+'；没有重新调用。');await load(s);}}));
      if(result.status==='completed')section.append(button(result.kind==='lyrics'?'接受歌词为新人工稿':'接受技术段落为新稿',async()=>{if(row.dirty)throw new Error('请先处理人工修改，避免覆盖');const before=JSON.stringify(document(row));const out=await post('/accept-music-result',{result_version_id:result.result_version_id,base_draft_id:row.base});if(!active(t,s))return;if(JSON.stringify(document(row))===before)drafts.delete(key());else{row.base=out.id;row.dirty=true;}ctx.notice('已接受为新工作稿，仍可编辑；没有自动批准或生成音频。');await load(s);},!writable()||result.draft_version_id!==row.base));root.append(section);
    }
    for(const output of (data.local_outputs||[]).filter(x=>x.tool===mode)){
      const section=el('section',null,'creative-tool-output');section.append(el('h2','本机输出'),el('p',JSON.stringify(output.receipt)),el('small','派生媒体权利保持待确认；发送至工作稿或候选不等于采用。'));
      for(const item of output.outputs){
        section.append(el('h3',item.name));const previewMedia=el(item.modality==='image'?'img':item.modality);previewMedia.src=`/api/v1/projects/${encodeURIComponent(s.project)}/media/${encodeURIComponent(item.id)}/content`;previewMedia.style.maxWidth='100%';if(item.modality!=='image')previewMedia.controls=true;section.append(previewMedia);const download=el('a','下载固定输出');download.href=previewMedia.src+'?download=true';section.append(download);transferForm(section,output,item,t,s);if(data.standalone)continue;
        const chooseShot=select(section,'输出候选归属镜头',[['','请选择镜头'],...data.shots.map(x=>[x.id,x.title||x.display_code])],value.shot_id,()=>{});
        const chooseCanvas=select(section,'输出目标画布',[['','请选择已有画布'],...(data.canvases||[]).map(x=>[x.id,x.title])],'',()=>{});
        const purpose=select(section,'分离音轨用途',[['music','音乐'],['ambience','环境'],['sfx','音效'],['dialogue_dry','对白（原混合音轨，需人工核对）']],'music',()=>{});purpose.parentElement.hidden=item.modality!=='audio';
        const send=async(target,extra={})=>{await post('/use-output',{output_version_id:output.id,media_id:item.id,target,audio_purpose:purpose.value,...extra});if(active(t,s)){ctx.notice('已写入原工作区；原版本保留。');await load(s);}};
        section.append(button('登记镜头候选',()=>send('candidate',{shot_id:chooseShot.value}),!writable()),button('加入所选画布',()=>{const selected=(data.canvases||[]).find(x=>x.id===chooseCanvas.value);if(!selected)throw new Error('先选择画布');return send('canvas',{canvas_id:selected.id,canvas_revision:selected.version});},!writable()),button(item.modality==='audio'?'从本集起点加入音轨':'追加到本集剪辑末尾',async()=>{const edit=await ctx.api(`/api/v1/projects/${encodeURIComponent(s.project)}/edit-workspace?episode_id=${encodeURIComponent(data.episode.id)}`);if(!active(t,s))return;ctx.setRevision(edit.project_revision,s.project);await send('editing',{edit_revision:edit.workspace?.revision||0});},!writable()));
      }root.append(section);
    }
    const links=el('div',null,'creative-tool-actions');for(const [page,label]of [['candidates','原任务与候选'],['editing','本集剪辑'],['designs','本集场镜设计'],['media','素材库']])if(!data.standalone)links.append(button(label,()=>ctx.navigate(page,data.episode.id,scope.project)));root.append(links);arrangeWorkspace(form,top,capability,value,t,s);
  }
  function arrangeWorkspace(form,top,capability,value,t,s){
    const title=root.querySelector('h1'),intro=root.querySelector(':scope > .hint'),heading=el('header',null,'creative-tool-heading');title.textContent=capability.label;heading.append(title);
    const utilities=el('details',null,'creative-tool-utilities');utilities.append(el('summary','草稿与恢复'),top);heading.append(utilities);
    const toolSelect=root.querySelector('[aria-label="工具"]'),navigation=el('nav',null,'creative-tool-tabs');navigation.setAttribute('aria-label','音乐与视频工具');
    for(const item of data.tools){const b=button(item.label,()=>{toolSelect.value=item.id;toolSelect.dispatchEvent(new Event('change'));});b.setAttribute('aria-pressed',String(item.id===mode));navigation.append(b);}toolSelect.parentElement.hidden=true;utilities.append(toolSelect.parentElement);
    const layout=el('div',null,'creative-tool-layout'),inputPanel=el('section',null,'creative-tool-input'),outputPanel=el('section',null,'creative-tool-results');layout.append(inputPanel,outputPanel);
    inputPanel.append(el('h2','输入设置'));outputPanel.append(el('h2','处理结果'));
    const previewBox=el('div',null,'creative-tool-preview'),previewStatus=el('p',null,'creative-tool-preview-status');
    const paintPreview=()=>{previewBox.replaceChildren();const selected=data.media.find(x=>x.id===value.source_media_id||x.id===value.audio_media_id);if(selected){const media=el(selected.modality==='image'?'img':selected.modality);media.src=`/api/v1/projects/${encodeURIComponent(s.project)}/media/${encodeURIComponent(selected.id)}/content`;if(selected.modality!=='image'){media.controls=true;media.preload='metadata';}else media.alt=selected.name;previewBox.append(media);previewStatus.textContent=selected.name;}else{const empty=el('div',null,'creative-tool-preview-empty');empty.append(el('span','＋'),el('strong','添加媒体开始创作'),el('p','上传文件或选择已有素材'));previewBox.append(empty);previewStatus.textContent='';}};paintPreview();
    const upload=[...root.children].find(node=>node.tagName==='DETAILS'&&node.querySelector('summary')?.textContent==='上传图片、音频或视频');
    if(upload){upload.classList.add('creative-tool-upload');inputPanel.append(upload);}
    inputPanel.append(form);
    const advanced=el('details',null,'creative-tool-advanced');advanced.append(el('summary','更多创作输入'));
    const local=['extract_frame','separate_audio','remove_subtitles','remove_watermark','segment_remake'].includes(mode);
    if(local)for(const control of [...form.querySelectorAll(':scope > label')]){if(['方案名称','提示词 / 视觉要求'].includes(control.querySelector('[aria-label]')?.getAttribute('aria-label')))advanced.append(control);}
    if(advanced.children.length>1)form.append(advanced);
    form.addEventListener('change',paintPreview);form.addEventListener('input',event=>{if(event.target.getAttribute('aria-label')==='源视频')paintPreview();});
    outputPanel.append(previewBox,previewStatus);
    const records=el('div',null,'creative-tool-records');outputPanel.append(records);
    for(const node of [...root.children]){if(node===heading||node===layout||node===navigation||node===title||node===intro)continue;if(node.classList.contains('creative-tool-output')||node.classList.contains('creative-tool-suggestion'))records.append(node);else if(node.classList.contains('creative-tool-capability'))inputPanel.append(node);else if(node.classList.contains('creative-tool-actions'))utilities.append(node);else if(node.tagName==='LABEL')inputPanel.prepend(node);}
    if(!records.children.length)records.append(el('p','暂无处理结果，保存输入后开始。','creative-tool-results-empty'));
    if(intro)utilities.append(intro);root.replaceChildren(heading,navigation,layout);
    for(const receipt of records.querySelectorAll('.creative-tool-output > p')){const details=el('details');details.append(el('summary','加工回执'));receipt.replaceWith(details);details.append(receipt);}
  }
  async function load(value){scope={...value,identity:identity()};const s=scope,t=++ticket;busy=false;preview=null;root.replaceChildren(el('p','正在读取音乐与视频工具…'));if(!s.project){root.replaceChildren(el('h1','独立音乐与视频工具'),el('p','上传文件后即可使用已支持的本机加工；不需要先建影视项目或分集。'),button('打开我的音乐与视频工具',async()=>{const result=await ctx.api('/api/v1/creative-tools/workspace',{method:'POST',headers:{'X-CSRF-Token':ctx.session().csrf}});if(active(t,s))await ctx.activateWorkspace(result.id,result.episode_id);},!ctx.session().actor));return;}try{const result=await ctx.api(endpoint(s.project,s.object?'?'+new URLSearchParams({object_id:s.object}):''));if(!active(t,s))return;data=result;if(s.tool&&data.tools.some(x=>x.id===s.tool)){mode=s.tool;standaloneModeInitialized=true;}else if(data.standalone&&!standaloneModeInitialized){mode='extract_frame';standaloneModeInitialized=true;}ctx.setRevision(result.revision,s.project);render();}catch(e){if(active(t,s))root.replaceChildren(el('p',e.message),button('重新读取',()=>load(s)));}}
  return {load,suspend(){runScope?.dispose();ticket++;scope=null;busy=false;preview=null;}};
}
