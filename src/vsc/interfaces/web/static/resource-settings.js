// Resource configuration uses the existing local human session; secrets never enter this form.
const labels = {identity_ref:'身份参考',image_edit:'图片编辑',first_frame:'镜头首帧',last_frame:'镜头尾帧',image_to_video:'图生视频',dialogue_dry:'配音',sfx:'音效',bgm:'配乐'};
const connectionLabels = {not_configured:'未配置',not_loaded:'当前进程未加载',loaded:'已加载 · 未在线验证',loaded_unverified:'已加载 · 未在线验证',not_connected:'尚未接通',invalid_configuration:'配置需要修正',unverified:'未在线验证',host_managed:'由宿主管理',unsupported:'尚未接通',ready:'配置可用 · 生成效果仍需实测'};
function el(tag, cls, text) { const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n; }
function option(value,label){const n=el('option','',label);n.value=value;return n;}
export function compatibleConfigurations(rows,purpose) {
  return rows.filter(row=>row.enabled && row.adapter_available !== false && (row.capabilities?.purposes || []).includes(purpose));
}
export function createResourceSettings(dialog,{api,session,onNotice}) {
  let data={configurations:[],defaults:{},presets:[],tools:[]},selected=null,view='models',loading=0,busy=false;
  const title=el('div','dialog-header');title.append(el('h2','','资源配置'));
  const close=el('button','','关闭');close.type='button';close.addEventListener('click',()=>dialog.close());title.append(close);
  const tabs=el('div','settings-tabs');const content=el('div','settings-content');const result=el('p','settings-result');result.setAttribute('role','status');
  const tabButtons=new Map();for(const [id,label] of [['models','模型与连接'],['defaults','默认用途'],['updates','官方更新']]){const b=el('button','',label);b.type='button';b.addEventListener('click',()=>{view=id;render()});tabs.append(b);tabButtons.set(id,b)}
  dialog.replaceChildren(title,el('p','hint','配置供后续新任务使用；已固定任务继续使用原模型与连接。'),tabs,content,result);
  function report(message){result.textContent=message;}
  function canWrite(){return Boolean(session().actor && session().csrf);}
  async function write(path,body={}){if(!canWrite())throw new Error('请先建立本机人工操作会话');return api('/api/v1/resource-settings'+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(body)});}
  async function action(fn){if(busy)return;busy=true;render();try{await fn()}catch(error){report(error.message)}finally{busy=false;render()}}
  async function reload(){const request=++loading;const value=await api('/api/v1/resource-settings');if(request!==loading)return;data=value;render();}
  function button(text,fn,disabled=false){const b=el('button','',text);b.type='button';b.disabled=disabled||busy;b.addEventListener('click',()=>action(fn));return b}
  function statusText(row){const raw=row.connection_status;return typeof raw==='object'?(raw.message||connectionLabels[raw.status]||raw.status):connectionLabels[raw]||raw||'未检测';}
  function field(form,label,name,value='',type='text'){const l=el('label','field',label),input=el('input');input.name=name;input.type=type;input.value=value??'';l.append(input);form.append(l);return input}
  function select(form,label,name,values,current){const l=el('label','field',label),input=el('select');input.name=name;for(const [v,t]of values)input.append(option(v,t));input.value=current||values[0]?.[0]||'';l.append(input);form.append(l);return input}
  function render(){
    for(const [id,b]of tabButtons)b.setAttribute('aria-selected',String(view===id));content.replaceChildren();
    if(!canWrite())content.append(el('p','hint','当前只读。建立顶栏“操作会话”后可保存配置或更新工具。'));
    if(view==='models')renderModels();else if(view==='defaults')renderDefaults();else renderUpdates();
  }
  function renderModels(){
    if(data.available===false)content.append(el('p','hint',data.message||data.reason||'未连接资源配置数据库，请按资源面板指南配置 PostgreSQL。'));
    const grid=el('div','settings-grid'),list=el('aside','settings-list'),detail=el('section','settings-detail');grid.append(list,detail);content.append(grid);
    list.append(button('＋ 新建配置',()=>{selected=null},!canWrite()||data.available===false));
    for(const row of data.configurations||[]){const b=button(row.name||row.model_key,()=>{selected=row.id});b.classList.toggle('selected',selected===row.id);b.append(el('small','',`${row.supplier||row.provider_id} · ${row.modality} · ${row.enabled?'启用':'停用'}`));list.append(b)}
    const row=(data.configurations||[]).find(r=>r.id===selected)||{};
    detail.append(el('h3','',row.id?'编辑配置':'新建配置'));
    const form=el('form','settings-form');
    const presets=Array.isArray(data.presets)?data.presets:Object.values(data.presets||{});
    if(presets.length){const preset=el('select');preset.setAttribute('aria-label','供应商预设');preset.append(option('','选择供应商预设'));for(const p of presets)preset.append(option(p.id||p.supplier,p.name||p.label||p.supplier));preset.addEventListener('change',()=>{const p=presets.find(x=>(x.id||x.supplier)===preset.value);if(!p)return;for(const name of ['name','supplier','product','plan','region','execution','base_url','auth_ref','tool_id','modality','model_key','model_version'])if(form.elements[name] && p[name]!=null)form.elements[name].value=p[name];if(form.elements.enabled)form.elements.enabled.checked=p.enabled===true;if(p.default_params)form.elements.default_params.value=JSON.stringify(p.default_params,null,2);if(p.capabilities){form.elements.capabilities.value=JSON.stringify(p.capabilities,null,2);for(const c of form.querySelectorAll('input'))if(c.name==='purpose')c.checked=(p.capabilities.purposes||[]).includes(c.value)}});detail.append(preset)}
    field(form,'配置名称','name',row.name).required=true;
    const supplier=select(form,'供应商','supplier',[['volcengine','火山方舟'],['alibaba','阿里云百炼'],['xai','xAI'],['openai','OpenAI']],row.supplier||'volcengine');
    field(form,'产品','product',row.product||'ark').required=true;field(form,'套餐','plan',row.plan||'agent-plan').required=true;
    select(form,'调用方式','execution',[['api','官方 API'],['official_skill','官方 Skill'],['official_cli','官方 CLI'],['host_tool','宿主内置工具']],row.execution||'api');
    select(form,'素材类型','modality',[['image','图片'],['video','视频'],['audio','音频']],row.modality||'image');
    field(form,'模型标识','model_key',row.model_key).required=true;field(form,'模型版本','model_version',row.model_version||'').required=true;
    field(form,'凭证环境变量名','auth_ref',row.auth_ref||'ARK_AGENT_PLAN_API_KEY');
    const capabilities=el('textarea');capabilities.name='capabilities';capabilities.value=JSON.stringify(row.capabilities||{},null,2);
    const purposeBox=el('fieldset','settings-purposes');purposeBox.append(el('legend','','适用用途'));
    const purposes=[...(data.purposes||Object.entries(labels).map(([id,label])=>({id,label})))];for(const id of row.capabilities?.purposes||[])if(!purposes.some(p=>p.id===id))purposes.push({id,label:id+'（已登记用途）'});
    for(const item of purposes){const code=item.id,label=item.label;const l=el('label'),c=el('input');c.type='checkbox';c.name='purpose';c.value=code;c.checked=(row.capabilities?.purposes||[]).includes(code);l.append(c,document.createTextNode(label));purposeBox.append(l)}form.append(purposeBox);
    const advanced=el('details','settings-advanced');advanced.append(el('summary','','高级设置'));const advancedFields=el('div','settings-form');
    field(advancedFields,'区域','region',row.region||'cn-beijing').required=true;field(advancedFields,'端点','base_url',row.base_url||'https://ark.cn-beijing.volces.com/api/plan/v3');field(advancedFields,'官方工具标识（可选）','tool_id',row.tool_id);
    const parameters=el('label','field','默认参数（JSON）'),textarea=el('textarea');textarea.name='default_params';textarea.value=JSON.stringify(row.default_params||{},null,2);parameters.append(textarea);const capabilityLabel=el('label','field','已核实的能力参数（JSON）');capabilityLabel.append(capabilities);advancedFields.append(parameters,capabilityLabel);advanced.append(advancedFields);form.append(advanced);
    const enabled=el('label','settings-inline'),check=el('input');check.type='checkbox';check.name='enabled';check.checked=row.enabled!==false;enabled.append(check,document.createTextNode('启用此配置'));form.append(enabled);
    const save=el('button','','保存配置');save.type='submit';save.disabled=!canWrite()||busy||data.available===false;form.append(save);
    form.addEventListener('submit',event=>{event.preventDefault();const fields=form.elements;const payload={};for(const name of ['name','supplier','product','plan','region','execution','modality','model_key','model_version','auth_ref','base_url','tool_id'])payload[name]=fields[name].value.trim();
      payload.enabled=check.checked;try{payload.capabilities=JSON.parse(capabilities.value||'{}')}catch{report('能力参数需要有效 JSON');return}payload.capabilities={...payload.capabilities,purposes:[...purposeBox.querySelectorAll('input')].filter(c=>c.checked).map(c=>c.value)};
      try{payload.default_params=JSON.parse(textarea.value||'{}')}catch{report('默认参数需要有效 JSON');return}if(row.id)payload.id=row.id;if(!payload.tool_id)delete payload.tool_id;
      action(async()=>{const saved=await write('/configurations',{payload});selected=saved.id||saved.configuration?.id||null;await reload();report('配置已保存；请在“默认用途”中指定新版本。已有任务保留原调用记录。')})});
    supplier.addEventListener('change',()=>{const preset=presets.find(p=>p.supplier===supplier.value);for(const name of ['product','plan','region','base_url','auth_ref','tool_id','model_key','model_version'])form.elements[name].value=preset?.[name]||'';check.checked=false;form.elements.execution.value=preset?.execution||'api';capabilities.value=JSON.stringify(preset?.capabilities||{},null,2);textarea.value=JSON.stringify(preset?.default_params||{},null,2);for(const c of purposeBox.querySelectorAll('input'))c.checked=(preset?.capabilities?.purposes||[]).includes(c.value);report('已切换供应商预设，请填写该产品与套餐的实际模型配置。尚未接通的路线只能保存为停用草稿。')});
    detail.append(form);
    if(row.id){detail.append(el('p','hint',statusText(row)));const controls=el('div','settings-actions');controls.append(button('检查配置',async()=>{const value=await write(`/configurations/${encodeURIComponent(row.id)}/check`);report(value.message||statusText(value));await reload()},!canWrite()),button('查看已登记模型',async()=>{const value=await write(`/configurations/${encodeURIComponent(row.id)}/models`);report([value.message,`模型列表：${(value.models||[]).map(m=>typeof m==='string'?m:m.model_key||m.id||m.name).join('、')||'未返回可用模型'}`].filter(Boolean).join('\n'))},!canWrite()),button(row.enabled?'停用':'启用',async()=>{await write(`/configurations/${encodeURIComponent(row.id)}/enabled`,{enabled:!row.enabled});await reload();report('启用状态已更新。')},!canWrite()));detail.append(controls)}
    detail.append(el('p','hint','仅保存凭证引用，不填写密钥值。配置检查和模型列表不代表生成质量通过；此页面不发送付费试生成。'));
  }
  function renderDefaults(){
    const purposes=Array.isArray(data.purposes)?data.purposes:Object.keys(data.purposes||labels);
    if(!purposes.length){content.append(el('p','empty','暂无可配置用途。'));return}
    for(const item of purposes){const code=typeof item==='string'?item:item.id||item.purpose;const box=el('form','settings-default');box.append(el('label','',typeof item==='string'?(labels[code]||code):item.label||labels[code]||code));const s=el('select');s.setAttribute('aria-label',labels[code]||code);s.append(option('','不设置默认'));const current=data.defaults?.[code];
      for(const row of compatibleConfigurations(data.configurations||[],code))s.append(option(row.id,`${row.name} · ${row.model_key}`));s.value=typeof current==='object'?current.configuration_id:current||'';
      const b=el('button','','保存');b.type='submit';b.disabled=!canWrite()||busy||data.available===false;box.append(s,b);box.addEventListener('submit',e=>{e.preventDefault();const id=s.value;action(async()=>{await write('/defaults',{purpose:code,configuration_id:id||null});await reload();report('默认用途已保存，仅用于新任务。')})});content.append(box)}
  }
  function renderUpdates(){
    content.append(button('检查官方更新',async()=>{const response=await write('/updates/check');data.tools=Array.isArray(response)?response:response.tools||response.items||[];report('检查完成，请选择更新或保留当前版本。')},!canWrite()));
    if(!(data.tools||[]).length)content.append(el('p','hint','检查已登记官方工具的版本。检查失败会显示原因，不能视为已经最新。'));
    for(const tool of data.tools||[]){const box=el('article','settings-tool');box.append(el('h3','',tool.name||tool.id),el('p','hint',`当前：${tool.current_revision||tool.current_version||'未安装'} · ${tool.official?'官方版本':'来源版本'}：${tool.latest_revision||tool.latest_version||'未核实'}`));if(tool.message||tool.summary)box.append(el('p','',tool.message||tool.summary));
      const updateAvailable=tool.can_update===true||tool.update_available===true||tool.status==='update_available';
      if(updateAvailable){const actions=el('div','settings-actions');actions.append(button('更新',async()=>{const value=await write(`/updates/${encodeURIComponent(tool.id)}`,{expected_revision:tool.latest_revision||tool.latest_version});report(value.message||'更新完成');await reload()},!canWrite()),button('不更新',()=>{tool.can_update=false;tool.update_available=false;tool.status='kept';tool.message='本次保留当前版本。'}));box.append(actions)}else box.append(el('p','hint',['current','up_to_date'].includes(tool.status)?'已是最新':tool.status==='host_managed'?'由宿主管理更新':tool.status==='kept'?'保留当前版本':tool.status==='unavailable'?'当前无法检查更新':'查看状态说明'));
      content.append(box)}
  }
  return {async open(){if(!dialog.open)dialog.showModal();report('正在读取资源配置…');try{await reload();report('')}catch(error){report(error.message);onNotice?.(error.message)}},refresh:reload};
}
