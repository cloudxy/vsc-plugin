import {msg,joinMessages,setText,bindAttribute,option as localizedOption} from './i18n.js';
// Local requests and scoped API consumers use the original operation session.
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const isDomNode=v=>Boolean(v&&typeof v==='object'&&typeof v.tagName==='string');
const clipWrite=async text=>{const nav=typeof navigator!=='undefined'?navigator:globalThis.navigator;await nav?.clipboard?.writeText?.(text);};
const perfNow=()=>typeof performance!=='undefined'&&performance?.now?performance.now():Date.now();
const names={feedback:'意见反馈',support:'支持申请',fcp:'FCP合作申请',studio:'短剧基地申请',production_service:'承制服务申请',distribution:'站外分发申请',account_close:'账户注销申请',personal_export:'个人信息导出'};
const statuses={received:'已收到本地申请',under_review:'本地处理中',awaiting_configuration:'外部服务待配置',local_approved:'本地审核通过，外部操作尚未完成',rejected:'已退回',withdrawn:'已撤回',export_ready:'本地导出文件已生成',error:'处理失败，申请保留',account_closed:'本地账户已停用，原审计记录保留'};

const NETWORK_PROBES=[
  ['session_gateway','1. 可信会话与网关鉴权'],
  ['postgres_revision','2. PostgreSQL 主库读写修订'],
  ['controlled_storage','3. 本地受控对象存储状态'],
  ['service_api_catalog','4. 天工引擎开放接口目录'],
  ['commerce_ledger','5. 商业账本与票据路由'],
  ['discovery_index','6. 创作目录与模板索引'],
  ['static_baseline','7. 静态资源与时延基线'],
  ['idempotency_channel','8. 幂等请求与回执通道'],
  ['media_chunk_gateway','9. 媒体分片上传网关'],
  ['roundtrip_confirm','10. 端到端综合往返确认']
];

const DRAMA_WAVE_SHOWCASE=[
  {title:'《Reborn Heiress: Crown of Ashes》',region:'北美 / 英语区',genre:'女频逆袭爽剧',tag:'全流程 AI 分镜 + 多语精校'},
  {title:'《El Alfa Oculto de Medianoche》',region:'拉美 / 墨西哥西语',genre:'豪门悬疑情感',tag:'海外重制 + 口型对齐'},
  {title:'《灰烬王座：第99次重启》',region:'日韩 / 繁体华语',genre:'无限流高燃男频',tag:'Seedance 连续性动作生成'},
  {title:'《Contract Bride of the Tech Titan》',region:'欧美 / 东南亚',genre:'都市契约甜宠',tag:'4x DramaWave 流量加权'},
  {title:'《Mahkota Terlarang》',region:'印尼 / 泰语市场',genre:'本土化家庭伦理',tag:'多语种字幕质检零返工'},
  {title:'《Shattered Starlight》',region:'全球同步首发',genre:'科幻微短剧精品',tag:'昆仑短剧基地算力扶持标杆'}
];

export function normalizeOperationsSubview(raw){
  const v=String(raw||'overview').trim().toLowerCase();
  if(['engine','api','tiangong-engine'].includes(v))return 'engine';
  if(['data-records','records','usage-records'].includes(v))return 'data-records';
  if(['seedance-verify','seedance','verify','video_check'].includes(v))return 'seedance-verify';
  if(['feedback-records','feedback'].includes(v))return 'feedback-records';
  if(['ai-drama-base','drama-base','studio-base'].includes(v))return 'ai-drama-base';
  if(['network-diagnostic','diagnostic','network'].includes(v))return 'network-diagnostic';
  if(['account-close','close-account'].includes(v))return 'account-close';
  if(['personal-info-export','personal-export'].includes(v))return 'personal-info-export';
  if(['terms','agreement-terms'].includes(v))return 'terms';
  if(['privacy','agreement-privacy'].includes(v))return 'privacy';
  if(['activity','campaign'].includes(v))return 'activity';
  if(['pc-only-notice','pc-only'].includes(v))return 'pc-only-notice';
  if(['icon','icons','icon-preview'].includes(v))return 'icon';
  if(['forbidden','403'].includes(v))return 'forbidden';
  if(['not-found','404'].includes(v))return 'not-found';
  return 'overview';
}

export function validateSeedanceTaskId(raw){
  const v=String(raw||'').trim();
  if(!v)return {valid:false,isHex16:false,isUuid:false,normalized:'',message:'请输入 16 位十六进制 Seedance 任务编号（如 8f3a19c04b2e7d11）。'};
  if(/^[0-9a-fA-F]{16}$/.test(v)){
    return {valid:true,isHex16:true,isUuid:false,normalized:v.toLowerCase(),message:'16 位十六进制 Seedance Task ID 格式校验通过。'};
  }
  if(/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(v)){
    return {valid:true,isHex16:false,isUuid:true,normalized:v.toLowerCase(),message:'本地生成任务 UUID 格式校验通过。'};
  }
  return {valid:false,isHex16:false,isUuid:false,normalized:v,message:'格式不合法：Seedance 任务编号须为严格 16 位十六进制字符（0-9, a-f）。'};
}

export function parseTosSignedUrl(rawUrl,nowMs=Date.now()){
  const text=String(rawUrl||'').trim();
  if(!text)return null;
  let parsed;
  try{parsed=new URL(text);}catch{return {valid:false,signed:false,expired:false,message:'链接格式无效，请输入完整 HTTPS 地址。'};}
  const lower=new Map([...parsed.searchParams.entries()].map(([k,v])=>[k.toLowerCase(),v]));
  const tosDate=lower.get('x-tos-date')||lower.get('x-amz-date')||'';
  const tosExpires=lower.get('x-tos-expires')||lower.get('x-amz-expires')||'';
  if(!tosDate||!tosExpires)return {valid:true,signed:false,expired:false,host:parsed.hostname,message:'未检测到 X-Tos-Date / X-Tos-Expires 签名参数。'};
  const m=tosDate.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  const ttl=Number(tosExpires);
  if(!m||!Number.isFinite(ttl)||ttl<0)return {valid:false,signed:true,expired:false,message:'X-Tos-Date 或 X-Tos-Expires 参数格式异常。'};
  const issuedMs=Date.UTC(Number(m[1]),Number(m[2])-1,Number(m[3]),Number(m[4]),Number(m[5]),Number(m[6]));
  const expiresMs=issuedMs+ttl*1000;
  const remainingSeconds=Math.max(0,Math.floor((expiresMs-nowMs)/1000));
  const expired=nowMs>=expiresMs;
  return {
    valid:true,
    signed:true,
    host:parsed.hostname,
    issuedAt:new Date(issuedMs).toISOString(),
    expiresAt:new Date(expiresMs).toISOString(),
    expiresSeconds:ttl,
    remainingSeconds,
    expired,
    message:expired?'该火山引擎 TOS 签名链接已过期，请回原任务重新获取访问链接。':`TOS 签名有效期内（剩余 ${remainingSeconds} 秒）。`
  };
}

export function feedbackDisplayStatus(status){
  if(status==='received')return {bucket:'received',label:'已收到'};
  if(['under_review','awaiting_configuration'].includes(status))return {bucket:'processing',label:'处理中'};
  if(status==='local_approved')return {bucket:'contacted',label:'已联系'};
  if(['rejected','withdrawn','account_closed','export_ready'].includes(status))return {bucket:'closed',label:'已关闭'};
  return {bucket:'processing',label:statuses[status]||status};
}

export function createServiceOperations(root,ctx){
  let scope=null,ticket=0,data=null,busy=false,subview='overview';
  let engineTab='consumption',recordsMode='personal',recordsTab='jobs',feedbackFilter='all',feedbackDrawerOpen=false;
  let seedanceResult=null,diagnosticState={running:false,completed:0,items:[],lastReport:null};
  const drafts=new Map(),pending=new Map(),keyAttempts=new Map(),secrets=new Map();

  const url=(p,path='')=>`/api/v1/projects/${encodeURIComponent(p)}/service-operations${path}`;
  const session=()=>ctx.session();
  const same=(t,s)=>t===ticket&&s===scope&&session().actor===s.actor;
  const writable=()=>!!session().actor&&session().actor===scope?.actor&&data?.capabilities.includes('read');
  const identity=s=>s.actor+':'+s.project;
  const getDraft=(key,fallback='')=>{const k=identity(scope)+':'+key;return drafts.has(k)?drafts.get(k):fallback;};
  const setDraft=(key,val)=>{drafts.set(identity(scope)+':'+key,val);return val;};

  function button(label,fn,disabled=false,cls=''){
    const b=node('button',label,cls);b.type='button';b.disabled=disabled;
    b.addEventListener('click',async()=>{
      const t=ticket,s=scope;
      try{await fn();}catch(e){if(same(t,s))ctx.notice(msg("ui.value0_current_inputs_and_original_application_preserved",{value0:e.message||String(e)}));}
    });
    return b;
  }
  function box(title,parent=root,cls='service-operations-card'){const s=node('section',null,cls);s.append(node('h2',title));parent.append(s);return s;}
  function field(parent,title,key,type='text',fallback=''){
    const input=node(type==='textarea'?'textarea':'input');
    if(type!=='textarea')input.type=type;else input.rows=4;
    bindAttribute(input,'aria-label',title);
    input.value=getDraft(key,fallback);
    input.addEventListener('input',()=>setDraft(key,input.value));
    const label=node('label',title,'service-operations-field');label.append(input);parent.append(label);
    return input;
  }
  function select(parent,title,entries,key,fallback=''){
    const n=node('select'),label=node('label',title,'service-operations-field');
    bindAttribute(n,'aria-label',title);
    for(const [value,text]of entries)n.append(localizedOption(value,text));
    n.value=getDraft(key,fallback||entries[0]?.[0]||'');
    n.addEventListener('change',()=>setDraft(key,n.value));
    label.append(n);parent.append(label);
    return n;
  }
  function summaryGrid(parent,items){
    const grid=node('dl',null,'so-summary-grid');
    for(const [dt,dd,sub]of items){
      const cell=node('div',null,'so-summary-cell');
      cell.append(node('dt',dt),node('dd',String(dd)));
      if(sub)cell.append(node('small',sub));
      grid.append(cell);
    }
    parent.append(grid);
    return grid;
  }
  function table(parent,headers,rows){
    const frame=node('div',null,'service-operations-table'),t=node('table'),head=node('tr');
    headers.forEach(h=>head.append(node('th',h)));t.append(head);
    for(const row of rows){
      const tr=node('tr');
      row.forEach(value=>{
        const td=node('td');
        if(isDomNode(value))td.append(value);
        else setText(td,value??'—');
        tr.append(td);
      });
      t.append(tr);
    }
    if(!rows.length){
      const tr=node('tr'),td=node('td','暂无记录');
      td.colSpan=headers.length;tr.append(td);t.append(tr);
    }
    frame.append(t);parent.append(frame);
    return frame;
  }
  function openModal(title,contentBuilder){
    const dialog=node('dialog',null,'so-dialog');
    bindAttribute(dialog,'aria-label',title);
    const head=node('header',null,'so-dialog-head');
    head.append(node('h2',title),button('关闭',()=>dialog.close()));
    const body=node('div',null,'so-dialog-body');
    contentBuilder(body,dialog);
    dialog.append(head,body);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    root.append(dialog);
    dialog.showModal();
    return dialog;
  }

  function resetScroll(focusRoot=false){
    root.scrollTop=0;
    if(root.parentElement)root.parentElement.scrollTop=0;
    if(focusRoot){
      if(root.getAttribute?.('tabindex')==null)root.setAttribute?.('tabindex','-1');
      root.focus?.({preventScroll:true});
    }
  }

  function switchSubview(next){
    subview=normalizeOperationsSubview(next);
    if(scope)scope.subview=subview;
    ctx.onSubviewChange?.(subview);
    resetScroll();
    render();
    resetScroll(true);
  }

  async function write(path,payload,onSuccess){
    if(!writable())throw new Error('当前会话没有写入权限');
    if(busy)throw new Error('上一操作仍在处理中');
    busy=true;
    const s=scope,t=ticket,key=identity(s)+path+JSON.stringify(payload);
    const attempt=pending.get(key)||{key:crypto.randomUUID(),revision:session().revision};
    pending.set(key,attempt);
    try{
      const result=await ctx.api(url(s.project,path),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload,expected_revision:attempt.revision,idempotency_key:attempt.key})});
      pending.delete(key);
      if(same(t,s)){
        const reload=onSuccess?await onSuccess(result):true;
        ctx.setRevision(result.revision,s.project);
        if(reload!==false)await load({...s,subview});
      }
      return result;
    }catch(e){
      if(e.status===409)pending.delete(key);
      throw e;
    }finally{
      if(same(t,s))busy=false;
    }
  }

  async function closeAccount(row){
    const s=scope,t=ticket,result=await ctx.api(url(s.project,'/account-close/preview'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({request_id:row.id})});
    if(!same(t,s))return;
    const dialog=node('dialog',null,'so-dialog');
    bindAttribute(dialog,'aria-label',msg("ui.account_deactivation_impact"));
    dialog.append(node('h2',msg("ui.account_deactivation_impact")),node('p',result.plan.effect));
    for(const item of result.plan.blockers)dialog.append(node('p',(item.title?item.title+'：':'')+item.message));
    const confirm=field(dialog,msg("ui.enter_the_current_operation_identity_to_confirm"),'close-confirm','text','');
    dialog.append(node('p',msg("ui.current_identity_value0",{value0:s.actor})));
    dialog.append(button(msg("ui.deactivate_my_local_account"),async()=>{
      if(confirm.value!==s.actor)throw new Error('请准确输入当前操作身份');
      await write('/account-close/execute',{request_id:row.id,preview_sha256:result.sha256,confirm_actor:confirm.value},async()=>{
        dialog.close();secrets.delete(identity(s));keyAttempts.delete(identity(s));
        root.replaceChildren(node('h1',msg("ui.local_account_deactivated")),node('p',msg("ui.login_and_api_credentials_have_been_revoked_works_billing")));
        return false;
      });
    },!result.ready),button(msg("common.close"),()=>dialog.close()));
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    root.append(dialog);dialog.showModal();
  }

  function renderApiKeyBlock(parent,s,{requireCompliance=false}={}){
    parent.append(node('p',msg("ui.for_the_dedicated_api_below_only_cannot_sign_in"),'hint'));
    const keyName=field(parent,msg("ui.api_credential_name"),'key-name');
    const cap=select(parent,'API 能力',[['read','只读任务与用量'],...(data.capabilities.includes('execute')?[['execute','读取及执行已批准运行']]:[])],'key-cap');
    const expiry=field(parent,msg("ui.api_expiry_time_with_timezone"),'key-expiry','text',new Date(Date.now()+30*86400000).toISOString());
    const networks=field(parent,msg("ui.allowed_ips_or_cidrs_one_per_line_empty_means"),'key-networks','textarea');
    const rate=field(parent,msg("ui.requests_per_minute_0_means_unrestricted"),'key-rate','number','60');
    rate.min='0';rate.max='10000';
    let spvCheck=null;
    if(requireCompliance){
      spvCheck=node('input');spvCheck.type='checkbox';
      spvCheck.checked=Boolean(getDraft('spv-compliance',false));
      spvCheck.addEventListener('change',()=>setDraft('spv-compliance',spvCheck.checked));
      bindAttribute(spvCheck,'aria-label','确认天工引擎开放接口与SPV合规协议');
      const line=node('label','我已阅读并确认《天工引擎开放接口与 SPV 企业合规协议》（禁止将密钥嵌入公开客户端或超范围转售）','so-checkbox-line');
      line.prepend(spvCheck);
      parent.append(line);
    }
    parent.append(button(msg("ui.create_and_register_api_credential"),async()=>{
      if(requireCompliance&&!spvCheck?.checked)throw new Error('请先勾选确认《天工引擎开放接口与 SPV 企业合规协议》');
      const selected={name:keyName.value,capabilities:cap.value==='execute'?['read','execute']:['read'],expires_at:expiry.value,ip_allowlist:networks.value.split(/[\n,]/).map(v=>v.trim()).filter(Boolean),requests_per_minute:Number(rate.value)};
      const signature=JSON.stringify(selected);
      let attempt=keyAttempts.get(identity(s));
      if(!attempt||attempt.signature!==signature){
        const bytes=crypto.getRandomValues(new Uint8Array(32));
        const secret=btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
        attempt={signature,payload:{...selected,secret}};
        keyAttempts.set(identity(s),attempt);
      }
      await write('/api-keys',attempt.payload,()=>{secrets.set(identity(s),attempt.payload.secret);keyAttempts.delete(identity(s));});
    },!writable()));
    if(secrets.has(identity(s))){
      const secret=node('input');secret.readOnly=true;secret.value=secrets.get(identity(s));
      bindAttribute(secret,'aria-label',msg("ui.new_api_credential_visible_on_this_page_only"));
      parent.append(node('p',msg("ui.save_this_credential_yourself_the_server_stores_only_its")),secret,button('复制新凭据',async()=>{await clipWrite(secret.value);ctx.notice('已复制新生成的 API 凭据');}),button(msg("ui.hide_this_credential"),()=>{secrets.delete(identity(s));render();}));
    }
    for(const key of data.api_keys){
      const row=node('div',null,'service-operations-actions');
      row.append(node('span',msg("ui.value0_value1_value2_value3_ip_value4_value5_requests_minute",{value0:key.name,value1:key.prefix,value2:key.capabilities.join('/'),value3:key.revoked?msg("ui.revoked"):new Date(key.expires_at).toLocaleString(),value4:key.ip_allowlist?.join(', ')||msg("ui.unlimited"),value5:key.requests_per_minute||msg("ui.unlimited")})));
      if(!key.revoked)row.append(button(msg("ui.revoke_api_credential_value0",{value0:key.name}),()=>write('/api-keys/revoke',{key_id:key.id}),!writable()));
      parent.append(row);
    }
  }

  function renderQuickSwitch(s){
    const menu=node('details',null,'so-quick-switch');
    menu.append(node('summary','切换服务 ▾'));
    const panel=node('div',null,'so-quick-switch-menu');
    bindAttribute(panel,'aria-label','平台服务快速切换');
    for(const [id,label]of [
      ['overview','综合服务总览'],
      ['engine','天工引擎 API'],
      ['data-records','数据与消耗记录'],
      ['seedance-verify','Seedance 视频验真'],
      ['feedback-records','我的意见反馈'],
      ['ai-drama-base','昆仑 AI 短剧基地'],
      ['network-diagnostic','网络诊断'],
      ['personal-info-export','个人信息导出'],
      ['account-close','账户注销']
    ]){
      const b=button(label,()=>{menu.open=false;switchSubview(id);});
      b.dataset.subview=id;
      b.setAttribute('aria-pressed',String(subview===id));
      panel.append(b);
    }
    panel.append(button(msg("ui.reload_service_records"),()=>{menu.open=false;return load({...scope,subview});}));
    menu.append(panel);
    return menu;
  }

  function renderEngine(s){
    const overview=data.engine_overview||{credit_balance:0,total_consumed_credits:0,ledger_records:[],recharge_orders:[],reservations:[],recent_jobs:[],member_usage:[]};
    const head=node('header',null,'so-hero-bar so-standalone-head');
    const titleWrap=node('div');
    titleWrap.append(node('h1','天工引擎'),node('p','通过 API 接入天工工作台的 Agent 能力，将智能创作流程集成到你的产品与业务中。','hint'));
    const actions=node('div',null,'service-operations-actions');
    let keysDrawer=null;
    actions.append(
      button('管理 API Key',()=>{
        if(keysDrawer)keysDrawer.open=true;
        const target=root.querySelector('.so-engine-keys input');
        target?.focus?.();
      },false,'so-btn-primary'),
      button('API 文档',()=>openModal('天工引擎开放接口文档',(body)=>{
        const examples=node('pre');
        setText(examples,msg("ui.get_api_v1_service_api_projects_value0_jobs_get",{value0:s.project,value1:s.project,value2:s.project,value3:s.project}));
        body.append(examples,button(msg("ui.copy_api_example"),()=>clipWrite(examples.textContent)));
        for(const op of data.api_catalog?.operations||[]){
          body.append(node('p',`${op.method} ${op.path} · 权限：${op.capability}${op.constraint?' · '+op.constraint:''}`));
        }
        if(data.configuration?.document?.api_documentation)body.append(node('p',data.configuration.document.api_documentation));
      })),
      button('设置',()=>openModal('API 账户安全与低余额预警',(body,dlg)=>{
        field(body,'低余额预警阈值（商业信用）','engine-low-balance','number','500');
        field(body,'默认允许 IP / CIDR 网段备注','engine-ip-note','textarea','');
        body.append(button('保存本地预警偏好',()=>{ctx.notice('已更新本地低余额预警与安全备注');dlg.close();},false,'so-btn-primary'));
      })),
      renderQuickSwitch(s)
    );
    head.append(titleWrap,actions);
    root.append(head);

    const acctCard=node('section',null,'service-operations-card so-engine-overview-card');
    const acctHead=node('div',null,'so-hero-bar');
    const acctRight=node('div',null,'service-operations-actions');
    acctRight.append(
      node('span','金额单位：CNY','hint'),
      button('充值',()=>ctx.navigate?.('commerce','wallet',s.project),false,'so-btn-primary')
    );
    acctHead.append(node('h2','账户概览'),acctRight);
    acctCard.append(acctHead);
    summaryGrid(acctCard,[
      ['账户余额',`${(Number(overview.credit_balance||0)/100).toFixed(2)} CNY`,`当前可用额度 · ${overview.credit_balance} 信用 · 已激活凭据 ${data.api_keys.filter(k=>!k.revoked).length} 枚`],
      ['累计消耗',`${(Number(overview.total_consumed_credits||0)/100).toFixed(2)} CNY`,`账户累计实际费用 · ${overview.total_consumed_credits} 信用 · 接口调用 ${data.api_calls.length} 次`]
    ]);
    root.append(acctCard);

    keysDrawer=node('details',null,'service-operations-card so-engine-keys');
    if(secrets.has(identity(s))||keyAttempts.has(identity(s)))keysDrawer.open=true;
    keysDrawer.append(node('summary',`API Key 凭据签发与吊销（有效凭据 ${data.api_keys.filter(k=>!k.revoked).length} 枚 · 点击展开管理）`));
    renderApiKeyBlock(keysDrawer,s,{requireCompliance:true});
    root.append(keysDrawer);

    const billBox=box('消费明细');
    const capsule=node('div',null,'so-segmented');
    for(const [id,label]of [['consumption','消费明细'],['recharge','充值记录']]){
      const b=button(label,()=>{engineTab=id;render();});
      b.setAttribute('aria-pressed',String(engineTab===id));
      capsule.append(b);
    }
    billBox.append(capsule);

    const filterRow=node('div',null,'so-filter-bar');
    const startInput=field(filterRow,'开始日期','engine-date-start','date','');
    const endInput=field(filterRow,'结束日期','engine-date-end','date','');
    const keyFilter=select(filterRow,'API Key 筛选',[['','全部 API Key'],...data.api_keys.map(k=>[k.id,`${k.name} (${k.prefix})`])],'engine-filter-key','');
    const statusFilter=select(filterRow,'状态筛选',engineTab==='consumption'
      ?[['','全部状态'],['reserve','预留 (reserve)'],['settle','结算 (settle)'],['grant','发放 (grant)'],['200','HTTP 200']]
      :[['','全部状态'],['paid','已支付 (paid)'],['pending','待处理 (pending)'],['refunded','已退款 (refunded)']],'engine-filter-status','');
    const qInput=field(filterRow,'筛选关键词（操作 / 状态 / 订单号）','engine-filter-q','search','');
    const filterActions=node('div',null,'service-operations-actions');
    const inDateRange=iso=>{
      if(!iso)return !startInput.value&&!endInput.value;
      const day=String(iso).slice(0,10);
      if(startInput.value&&day<startInput.value)return false;
      if(endInput.value&&day>endInput.value)return false;
      return true;
    };
    const applyBtn=button('查询',()=>render(),false,'so-btn-primary');
    const resetBtn=button('重置',()=>{
      for(const k of ['engine-date-start','engine-date-end','engine-filter-key','engine-filter-status','engine-filter-q'])setDraft(k,'');
      render();
    });
    const exportCsvBtn=button('导出全部 (CSV)',()=>{
      const q=qInput.value.trim().toLowerCase(),st=statusFilter.value;
      const lines=engineTab==='consumption'
        ?[['时间','类型','额度变动','关联预留/调用'],...overview.ledger_records.filter(r=>inDateRange(r.created_at)&&(!st||r.kind===st)&&(!q||`${r.kind} ${r.reservation_id||''}`.toLowerCase().includes(q))).map(r=>[r.created_at,r.kind,r.delta,r.reservation_id||''])]
        :[['创建时间','订单编号','状态','金额(分)','币种','信用额度'],...overview.recharge_orders.filter(r=>inDateRange(r.created_at)&&(!st||r.status===st)&&(!q||`${r.id} ${r.status}`.toLowerCase().includes(q))).map(r=>[r.created_at,r.id,r.status,r.amount_minor,r.currency,r.credits])];
      const csv=lines.map(r=>r.map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(',')).join('\n');
      setDraft('last-exported-csv',csv);
      ctx.notice(`已生成 ${lines.length-1} 条 ${engineTab==='consumption'?'消费明细':'充值记录'} CSV 导出内容`);
    });
    filterActions.append(applyBtn,resetBtn,exportCsvBtn);
    filterRow.append(filterActions);
    billBox.append(filterRow);

    const q=qInput.value.trim().toLowerCase(),st=statusFilter.value,kf=keyFilter.value;
    if(engineTab==='consumption'){
      const ledgerRows=overview.ledger_records.filter(r=>inDateRange(r.created_at)&&(!st||st==='200'||r.kind===st)&&(!q||`${r.kind} ${r.reservation_id||''} ${r.actor||''}`.toLowerCase().includes(q)));
      table(billBox,['记录时间','账本动作','额度变动','操作身份','关联任务预留'],ledgerRows.map(r=>[
        r.created_at?new Date(r.created_at).toLocaleString():'—',
        r.kind,
        String(r.delta),
        r.actor||'—',
        r.reservation_id||'—'
      ]));
      table(billBox,['API 调用编号','开放操作','阶段','HTTP 状态码','记录时间'],data.api_calls.filter(c=>inDateRange(c.created_at)&&(!kf||c.key_id===kf)&&(!st||String(c.status_code)===st||!['200'].includes(st))&&(!q||`${c.call_id} ${c.operation} ${c.status_code}`.toLowerCase().includes(q))).map(c=>[
        c.call_id,c.operation,c.phase,String(c.status_code),new Date(c.created_at).toLocaleString()
      ]));
    }else{
      const orders=overview.recharge_orders.filter(r=>inDateRange(r.created_at)&&(!st||r.status===st)&&(!q||`${r.id} ${r.status} ${r.currency}`.toLowerCase().includes(q)));
      table(billBox,['订单编号','状态','金额','购买信用额度','支付时间','操作'],orders.map(o=>[
        o.id,
        o.status,
        `${o.amount_minor} ${o.currency}`,
        String(o.credits),
        o.paid_at?new Date(o.paid_at).toLocaleString():'未支付',
        button('前往钱包/开票',()=>ctx.navigate?.('commerce','invoice-orders',s.project))
      ]));
    }
  }

  function renderDataRecords(s){
    const overview=data.engine_overview||{credit_balance:0,total_consumed_credits:0,ledger_records:[],recharge_orders:[],reservations:[],recent_jobs:[],member_usage:[]};
    const banner=node('section',null,'so-engine-banner'),bannerActions=node('div',null,'service-operations-actions');
    bannerActions.append(
      button('账户余额',()=>switchSubview('engine')),
      button('账单明细 →',()=>{engineTab='consumption';switchSubview('engine');}),
      button('密钥管理 →',()=>switchSubview('engine')),
      button('电子发票 →',()=>ctx.navigate?.('commerce','invoice-overview',s.project)),
      renderQuickSwitch(s)
    );
    const bannerInfo=node('div',null,'so-engine-banner-title');
    const bannerKicker=node('div',null,'so-engine-banner-kicker');
    bannerKicker.append(node('span','API 账户','so-api-pill'),node('span',' · ','so-sr-sep'),node('strong','天工引擎'));
    bannerInfo.append(
      bannerKicker,
      node('span',`查看额度、消费与充值记录，管理 API Key · 当前可用额度：${overview.credit_balance} 信用 · 累计结算消耗：${overview.total_consumed_credits} 信用`)
    );
    banner.append(bannerInfo,bannerActions);
    root.append(banner);

    const modeBar=node('div',null,'so-segmented');
    const modes=[['personal','个人创作记录'],...(data.manage?[['studio','工作室团队成本核算']]:[])];
    for(const [id,label]of modes){
      const b=button(label,()=>{recordsMode=id;render();});
      b.setAttribute('aria-pressed',String(recordsMode===id));
      modeBar.append(b);
    }
    root.append(modeBar);

    if(recordsMode==='studio'&&data.manage){
      const studioBox=box('团队成员消耗与项目单集成本核算表');
      summaryGrid(studioBox,[
        ['活跃消耗成员数',`${overview.member_usage.length} 人`,'按真实预留/结算账户汇总'],
        ['项目累计消耗',`${overview.total_consumed_credits} 信用`,'含已结算与在途预留额度'],
        ['生成任务总数',`${overview.recent_jobs.length} 项`,'覆盖图像 / 视频 / 音频候选'],
        ['预算透支保护','数据库强约束','禁止负余额与超上限扣减']
      ]);
      table(studioBox,['成员身份 / 账户池','预留任务笔数','累计消耗信用','操作'],overview.member_usage.map(m=>[
        m.actor,
        String(m.reservation_count),
        String(m.credits_used),
        button('查看任务明细',()=>openModal(`${m.actor} · 消耗明细`,(body)=>{
          const mine=overview.reservations.filter(r=>(r.account_actor||'项目公共池')===m.actor);
          table(body,['任务编号','预留信用','实际结算','状态','时间'],mine.map(r=>[
            r.job_id,String(r.bound),String(r.actual??'待结算'),r.status,r.created_at?new Date(r.created_at).toLocaleString():'—'
          ]));
        }))
      ]));
      return;
    }

    const split=node('div',null,'so-records-split');
    const side=node('aside',null,'service-operations-card so-records-nav');
    side.append(node('span','账户记录','so-records-kicker'),node('h2','个人用户'));
    for(const [id,label]of [['jobs','最近创作'],['requests','我的收藏与服务记录'],['ledger','账户流水']]){
      const b=button(label,()=>{recordsTab=id;render();},false,'so-records-tab');
      b.prepend(node('span','● ','so-records-dot'));
      b.setAttribute('aria-pressed',String(recordsTab===id));
      side.append(b);
    }
    const contentBox=node('section',null,'service-operations-card so-records-main');
    const tabTitle={jobs:'最近创作',requests:'我的收藏与服务记录',ledger:'账户流水'}[recordsTab]||'个人数据记录';
    contentBox.append(node('h2',tabTitle));
    if(recordsTab==='jobs'){
      table(contentBox,['任务编号','模态','用途','模型版本','状态','更新时间'],overview.recent_jobs.map(j=>[
        j.id,j.modality,j.purpose,j.model_version,j.status,j.updated_at?new Date(j.updated_at).toLocaleString():'—'
      ]));
    }else if(recordsTab==='requests'){
      table(contentBox,['记录编号','类型','标题','当前状态','提交时间'],data.requests.map(r=>[
        r.id,names[r.kind]||r.kind,r.title,statuses[r.status]||r.status,r.events?.[0]?.created_at?new Date(r.events[0].created_at).toLocaleString():'—'
      ]));
    }else{
      table(contentBox,['记录时间','动作类型','额度变动','关联任务预留'],overview.ledger_records.map(r=>[
        r.created_at?new Date(r.created_at).toLocaleString():'—',r.kind,String(r.delta),r.reservation_id||'—'
      ]));
    }
    split.append(side,contentBox);
    root.append(split);
  }

  function renderSeedanceVerify(t,s){
    const topBar=node('header',null,'so-hero-bar so-standalone-head');
    const brandBar=node('div',null,'service-operations-actions');
    brandBar.append(
      button('← 天工工作台',()=>ctx.navigate?.('home'),'','so-cobrand-pill'),
      node('span','天工工作台 × 火山引擎','so-cobrand-pill')
    );
    topBar.append(brandBar,renderQuickSwitch(s));
    root.append(topBar);

    const sourceBanner=node('section',null,'service-operations-card so-verify-source');
    sourceBanner.append(
      node('span','🛡','so-verify-shield'),
      node('strong','数据来源：火山方舟官方任务查询接口'),
      node('span','官方数据 · 实时查询','so-verify-live-pill')
    );
    root.append(sourceBanner);

    const shell=node('div',null,'so-verify-shell-wrap');
    shell.append(node('h1','Seedance 任务核验','so-verify-heading'));

    const card=node('section',null,'service-operations-card so-verify-shell');
    card.append(node('p','输入任务 ID，查看这次生成实际调用的是哪个模型','so-verify-subtitle'));

    const queryTaskId=typeof location!=='undefined'&&location?.search?new URLSearchParams(location.search).get('task_id')||'':'';
    const inputRow=node('div',null,'so-verify-input-row');
    const taskInput=field(inputRow,'Seedance 任务编号','seedance-task-id','text',s.targetId||queryTaskId||'');
    bindAttribute(taskInput,'placeholder','请输入任务 ID（如 8f3a19c04b2e7d11）');
    inputRow.append(button('立即核验任务回执',async()=>{
      const check=validateSeedanceTaskId(taskInput.value);
      if(!check.valid)throw new Error(check.message);
      if(!s.project||!session().actor){
        const tos=tosInput.value.trim()?parseTosSignedUrl(tosInput.value.trim()):null;
        seedanceResult={verified:false,task_id:check.normalized,is_seedance_hex16:check.isHex16,credits_consumed:0,co_brand:'天工工作台 × 火山引擎',job:null,tos_signature:tos,message:'任务编号格式校验通过；当前为未登录浏览态，登录并关联项目后可查询原始生成回执（零积分消耗）。'};
        render();
        return;
      }
      const res=await ctx.api(url(s.project,'/seedance-verify'),{
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
        body:JSON.stringify({payload:{task_id:check.normalized,...(tosInput.value.trim()?{tos_url:tosInput.value.trim()}:{})}})
      });
      if(!same(t,s))return;
      seedanceResult=res;
      render();
    },false,'so-btn-primary'));
    card.append(inputRow);

    card.append(node('div','✓ 仅查询，不会重新生成视频，也不消耗任何积分。','so-trust-badge'));
    const idHint=node('p',null,'hint');
    const tosCollapse=node('details',null,'so-tos-collapse');
    tosCollapse.append(node('summary','附加核验：火山引擎 TOS 签名链接时效检查（可选）'));
    const tosInput=field(tosCollapse,'TOS 签名链接（可选，检查有效期）','seedance-tos-url','text','');
    bindAttribute(tosInput,'placeholder','粘贴包含 X-Tos-Date 与 X-Tos-Expires 的受控视频链接');
    const tosHint=node('p',null,'hint');
    tosCollapse.append(tosHint);

    const syncHints=()=>{
      const check=validateSeedanceTaskId(taskInput.value);
      setText(idHint,check.message);
      idHint.dataset.valid=String(check.valid);
      const tos=parseTosSignedUrl(tosInput.value);
      setText(tosHint,tos?tos.message:'填写火山引擎 TOS 签名链接可即时核对过期时间。');
    };
    taskInput.addEventListener('input',syncHints);
    tosInput.addEventListener('input',syncHints);
    syncHints();
    card.append(idHint,tosCollapse);
    shell.append(card);

    const stageCard=node('section',null,'service-operations-card so-verify-stage');
    if(seedanceResult){
      const resBox=node('div',null,'so-verify-result');
      resBox.append(
        node('h3',seedanceResult.verified?'核验通过：已匹配原始生成任务回执':'未检索到匹配任务回执（只读核验已完成）'),
        node('p',seedanceResult.message)
      );
      summaryGrid(resBox,[
        ['核验品牌',seedanceResult.co_brand||'天工工作台 × 火山引擎','官方溯源通道'],
        ['查询任务号',seedanceResult.task_id,seedanceResult.is_seedance_hex16?'标准 16 位十六进制':'本地任务 UUID'],
        ['本次消耗积分',String(seedanceResult.credits_consumed??0),'只读查询零扣费'],
        ['实际调用模型 / 本地状态',seedanceResult.job?`${seedanceResult.job.model_version||'seedance'} · ${seedanceResult.job.status}`:'未命中本地记录','未触发任何远端生成']
      ]);
      if(seedanceResult.tos_signature){
        resBox.append(node('p',`TOS 签名解析：${seedanceResult.tos_signature.message}`));
      }
      stageCard.append(resBox);
    }else{
      const empty=node('div',null,'so-verify-empty');
      empty.append(
        node('div','🔍','so-verify-lens'),
        node('h3','输入任务 ID 后点击「立即核验任务回执」'),
        node('p','将从官方任务查询接口与本地原始回执获取任务记录，确认实际调用的模型版本')
      );
      stageCard.append(empty);
    }
    shell.append(stageCard);
    shell.append(node('footer','ⓘ 说明：本页任务数据由官方任务查询回执返回。其中「实际调用模型」为本次生成调用的模型版本。','so-verify-footnote'));
    root.append(shell);
  }

  function renderFeedbackRecords(t,s){
    const head=node('header',null,'so-hero-bar so-standalone-head');
    const titleWrap=node('div');
    titleWrap.append(node('h1','我的意见反馈'),node('p','查看反馈处理进度，或提交新的问题和建议。','hint'));
    const headActions=node('div',null,'service-operations-actions');
    headActions.append(
      button(feedbackDrawerOpen?'收起反馈表单':'⊕ 提交新反馈',()=>{feedbackDrawerOpen=!feedbackDrawerOpen;render();},!writable(),'so-btn-primary'),
      renderQuickSwitch(s)
    );
    head.append(titleWrap,headActions);
    root.append(head);

    if(feedbackDrawerOpen){
      const drawer=box('提交新意见反馈',root,'service-operations-card so-feedback-drawer');
      const defaultPage=typeof location!=='undefined'&&location?.pathname?location.pathname:'/feedback/records';
      const pageChannel=field(drawer,'提交页面 / 功能模块','fb-channel','text',getDraft('fb-channel',defaultPage));
      select(drawer,'反馈分类',[['feature','功能建议'],['quality','生成效果与模型'],['billing','账单与电子发票'],['ux','界面与操作体验'],['bug','异常报错']],'fb-category','feature');
      const fbTitle=field(drawer,'反馈标题','fb-title','text','');
      const fbBody=field(drawer,'问题与建议详情','fb-body','textarea','');
      const fbContact=field(drawer,'联系邮箱或飞书/手机号（选填）','fb-contact','text','');
      const drawerActions=node('div',null,'service-operations-actions');
      drawerActions.append(
        button('提交反馈记录',async()=>{
          await write('/requests',{
            kind:'feedback',
            title:fbTitle.value,
            body:fbBody.value,
            contact:fbContact.value,
            channel:pageChannel.value||'/feedback/records',
            artifact_id:null,
            media_id:null,
            requested_fields:[]
          },()=>{
            feedbackDrawerOpen=false;
            setDraft('fb-title','');setDraft('fb-body','');
          });
        },!writable(),'so-btn-primary'),
        button('取消',()=>{feedbackDrawerOpen=false;render();})
      );
      drawer.append(drawerActions);
    }

    const listBox=node('section',null,'service-operations-card');
    const toolbarRow=node('div',null,'so-filter-bar');
    const searchInput=field(toolbarRow,'搜索反馈编号或内容','fb-search','search','');
    bindAttribute(searchInput,'placeholder','搜索反馈编号、摘要或内容');
    searchInput.addEventListener('input',()=>paintTable());
    toolbarRow.append(button('刷新',()=>load({...scope,subview})));
    listBox.append(toolbarRow);

    const allFeedback=data.requests.filter(r=>r.kind==='feedback');
    const tabBar=node('div',null,'so-underline-tabs');
    for(const [code,label]of [['all','全部'],['received','已收到'],['processing','处理中'],['contacted','已联系'],['closed','已关闭']]){
      const b=button(label,()=>{feedbackFilter=code;render();});
      b.setAttribute('aria-pressed',String(feedbackFilter===code));
      tabBar.append(b);
    }
    listBox.append(tabBar);
    const tableHost=node('div');
    listBox.append(tableHost);
    root.append(listBox);

    function paintTable(){
      tableHost.replaceChildren();
      const q=searchInput.value.trim().toLowerCase();
      const feedbackRows=allFeedback.filter(r=>{
        const mapped=feedbackDisplayStatus(r.status);
        if(feedbackFilter!=='all'&&mapped.bucket!==feedbackFilter)return false;
        if(q&&!`${r.id} ${r.title} ${r.body} ${r.channel||''}`.toLowerCase().includes(q))return false;
        return true;
      });
      if(!feedbackRows.length){
        const headFrame=node('div',null,'service-operations-table'),tHead=node('table'),tr=node('tr');
        ['反馈编号','反馈内容','状态','提交页面','操作'].forEach(h=>tr.append(node('th',h)));
        tHead.append(tr);headFrame.append(tHead);tableHost.append(headFrame);
        const empty=node('div',null,'so-empty-state');
        empty.append(
          node('div','📦','so-empty-glyph'),
          node('h3',q||feedbackFilter!=='all'?'当前筛选下暂无反馈记录':'暂无反馈记录'),
          node('p','您的每一条反馈都会帮助我们持续改进短剧创作体验。'),
          button('提交第一条反馈',()=>{feedbackDrawerOpen=true;render();},!writable(),'so-btn-primary')
        );
        tableHost.append(empty);
        return;
      }
      table(tableHost,['反馈编号','反馈内容','状态','提交页面','操作'],feedbackRows.map(row=>{
        const mapped=feedbackDisplayStatus(row.status);
        const actions=node('div',null,'service-operations-actions');
        actions.append(button('查看详情',()=>openModal(`反馈详情 · ${row.title}`,(body)=>{
          body.append(node('p',`编号：${row.id}`),node('p',`提交页面：${row.channel||'工作台'}`),node('p',row.body));
          for(const ev of row.events||[]){
            body.append(node('p',`${new Date(ev.created_at).toLocaleString()} · ${statuses[ev.status]||ev.status} · ${ev.reason}`));
          }
        })));
        const last=row.events?.at(-1);
        const terminal=['withdrawn','rejected','export_ready','account_closed'].includes(row.status);
        if(row.mine&&!terminal&&last){
          actions.append(button('撤回',()=>write('/requests/withdraw',{request_id:row.id,base_event_id:last.id,reason:'用户主动撤回反馈'}),!writable()));
        }
        return [row.id,`${row.title}：${row.body.slice(0,60)}`,mapped.label,row.channel||'工作台默认页',actions];
      }));
    }
    paintTable();
  }

  function renderAiDramaBase(s){
    const openOnboarding=()=>openModal('申请入驻昆仑万维 AI 短剧基地',(body,dlg)=>{
      const team=field(body,'工作室 / 公司名称','studio-team-name','text','');
      const capacity=field(body,'代表作品、团队规模与月产能说明','studio-capacity','textarea','');
      const contact=field(body,'商务负责人及联系方式','studio-contact','text','');
      const market=field(body,'主攻出海市场（如欧美 / 拉美 / 日韩 / 东南亚）','studio-market','text','北美与拉美');
      body.append(button('提交基地入驻申请',async()=>{
        await write('/requests',{
          kind:'studio',
          title:team.value,
          body:capacity.value,
          contact:contact.value,
          channel:market.value||'DramaWave 全球出海',
          artifact_id:null,
          media_id:null,
          requested_fields:[]
        },()=>{dlg.close();ctx.notice('基地入驻申请已保存至本地运营记录');});
      },!writable(),'so-btn-primary'));
    });

    const anchorNav=node('header',null,'so-drama-topbar');
    const brand=button('天工工作台',()=>ctx.navigate?.('home'),'','so-drama-brand');
    const links=node('nav',null,'service-operations-actions so-drama-nav');
    for(const [label,selector]of [['线上入驻','.so-drama-hero'],['基地建设','.so-drama-policy'],['出海战绩','.so-drama-showcase']]){
      links.append(button(label,()=>{
        root.querySelector(selector)?.scrollIntoView?.({behavior:'smooth',block:'start'});
        ctx.notice(`已定位至：${label}`);
      }));
    }
    const rightBar=node('div',null,'service-operations-actions');
    rightBar.append(button('入驻申请',openOnboarding,!writable(),'so-btn-light'),renderQuickSwitch(s));
    anchorNav.append(brand,links,rightBar);
    root.append(anchorNav);

    const hero=node('section',null,'service-operations-card so-drama-hero');
    const heroLeft=node('div',null,'so-drama-hero-copy');
    const heroActions=node('div',null,'service-operations-actions');
    heroActions.append(
      button('立即申请线上入驻',openOnboarding,!writable(),'so-btn-primary'),
      button('了解基地建设 →',()=>root.querySelector('.so-drama-policy')?.scrollIntoView?.({behavior:'smooth',block:'start'}),false,'so-btn-light'),
      button('前往钱包兑换基地算力码',()=>ctx.navigate?.('commerce','wallet',s.project))
    );
    const heroHeading=node('h1');
    heroHeading.append(node('span','入驻'),node('span','昆仑万维AI短剧基地','so-lime-accent'),node('span','，一站式生产直达全球出海'));
    heroLeft.append(
      node('span','✦ 昆仑万维 AI 短剧基地 - 线上专区 · 入驻招募中','so-drama-kicker'),
      heroHeading,
      node('p','入驻即享 5% 入驻奖励、500万算力补贴 + 20% 充值奖励、DramaWave 短剧承制 + 4x 流量扶持 与 基地全周期扶持。依托 天工工作台 SkyProduction 工业化制片工作台与 DramaWave 全球发行网络，让 AI 短剧「造得出、卖得掉」。'),
      heroActions
    );
    const posterGrid=node('div',null,'so-showcase-grid so-drama-showcase');
    for(const item of DRAMA_WAVE_SHOWCASE){
      const card=node('article',null,'so-showcase-card');
      card.append(node('span',item.region,'so-drama-kicker'),node('h3',item.title),node('p',item.genre),node('small',item.tag));
      posterGrid.append(card);
    }
    hero.append(heroLeft,posterGrid);
    root.append(hero);

    const policyWrap=node('section',null,'so-drama-policy');
    summaryGrid(policyWrap,[
      ['5% 入驻奖励','认证即享算力返还','通过基地资质审核后按季度结算奖励额度'],
      ['500万 算力补贴 + 20% 充值福利','精品短剧专项扶持','重点签约项目享受天工全模态算力包直补'],
      ['4x 流量加权','直通 DramaWave 出海','全球超百个国家与地区冷启动曝光加权']
    ]);
    root.append(policyWrap);

    const myStudio=data.requests.filter(r=>r.kind==='studio');
    const statusBox=box('本项目的短剧基地入驻申请记录');
    table(statusBox,['申请编号','工作室/项目名称','主攻市场','当前状态'],myStudio.map(r=>[
      r.id,r.title,r.channel||'—',statuses[r.status]||r.status
    ]));
  }

  async function runNetworkDiagnostics(t,s){
    if(diagnosticState.running)return;
    diagnosticState={running:true,completed:0,items:[],lastReport:null};
    render();
    const results=[];
    for(const [key,title]of NETWORK_PROBES){
      const started=perfNow();
      try{
        const endpoint=s.project&&session().actor?url(s.project,`/network-diagnostic/ping?probe=${encodeURIComponent(key)}`):`/api/v1/session?probe=${encodeURIComponent(key)}`;
        const res=await ctx.api(endpoint,session().csrf?{headers:{'X-CSRF-Token':session().csrf}}:{});
        const latencyMs=Math.max(1,Math.round(perfNow()-started));
        let timingDetail='HTTP 200 · same-origin fetch';
        if(typeof performance!=='undefined'&&performance?.getEntriesByType){
          const entry=[...performance.getEntriesByType('resource')].reverse().find(e=>String(e.name||'').includes(`probe=${key}`));
          if(entry){
            const dns=Math.round((entry.domainLookupEnd||0)-(entry.domainLookupStart||0));
            const tcp=Math.round((entry.connectEnd||0)-(entry.connectStart||0));
            const ttfb=Math.round((entry.responseStart||0)-(entry.requestStart||0));
            timingDetail=`HTTP 200 · DNS ${Math.max(0,dns)}ms · TCP ${Math.max(0,tcp)}ms · TTFB ${Math.max(0,ttfb)}ms`;
          }
        }
        results.push({key,title,ok:true,latencyMs,detail:`DB:${res.database||'connected'} · Storage:${res.storage||'configured'} · ${timingDetail}`});
      }catch(err){
        const latencyMs=Math.max(1,Math.round(perfNow()-started));
        results.push({key,title,ok:false,latencyMs,detail:err.message||String(err)});
      }
      if(!same(t,s))return;
      diagnosticState.completed=results.length;
      diagnosticState.items=[...results];
      render();
    }
    const okCount=results.filter(r=>r.ok).length;
    const avgMs=results.length?Math.round(results.reduce((a,b)=>a+b.latencyMs,0)/results.length):0;
    diagnosticState.running=false;
    diagnosticState.lastReport={
      generated_at:new Date().toISOString(),
      project_id:s.project,
      actor:s.actor,
      total:results.length,
      succeeded:okCount,
      failed:results.length-okCount,
      average_ms:avgMs,
      quality:okCount===results.length?(avgMs<120?'优秀':'良好'):(okCount>=7?'波动':'异常'),
      probes:results
    };
    render();
  }

  function renderNetworkDiagnostic(t,s){
    const wrap=node('section',null,'so-network-light');
    const head=node('header',null,'so-hero-bar'),headActions=node('div',null,'service-operations-actions');
    const nav=typeof navigator!=='undefined'?navigator:globalThis.navigator;
    const connType=nav?.connection?.effectiveType||'4g';
    headActions.append(
      button('复制诊断报告 (JSON)',async()=>{
        const payload=JSON.stringify(diagnosticState.lastReport||{probes:diagnosticState.items},null,2);
        await clipWrite(payload);
        ctx.notice('已复制 JSON 网络诊断报告');
      },!diagnosticState.items.length,'so-diag-copy'),
      button(diagnosticState.items.length?'重新诊断':'开始 10 项全链路诊断',()=>runNetworkDiagnostics(t,s),diagnosticState.running,'so-diag-primary'),
      renderQuickSwitch(s)
    );
    const titleWrap=node('div');
    titleWrap.append(
      node('h1','网络诊断'),
      node('p',`接口、图片、视频、上传 · ${diagnosticState.running?'诊断中':diagnosticState.items.length?'诊断完成':'待诊断'}`,'hint')
    );
    head.append(titleWrap,headActions);
    wrap.append(head);

    const items=diagnosticState.items;
    const okCount=items.filter(r=>r.ok).length;
    const failCount=items.filter(r=>!r.ok).length;
    const avgMs=items.length?Math.round(items.reduce((a,b)=>a+b.latencyMs,0)/items.length):0;
    const quality=!items.length?`估算质量 ${connType}`:failCount===0?(avgMs<120?'优秀':`估算质量 ${connType}`):(okCount>=7?'波动':'异常');
    summaryGrid(wrap,[
      ['成功项',`${okCount}`,''],
      ['异常项',`${failCount}`,failCount?'请复制报告联系支持人员':''],
      ['平均耗时',items.length?`${avgMs}ms`:'-',''],
      ['网络质量',quality,'']
    ]);

    const pct=Math.round((diagnosticState.completed/NETWORK_PROBES.length)*100);
    const progressRow=node('div',null,'so-diag-progress-row');
    const barWrap=node('div',null,'so-diag-bar-wrap'),barFill=node('div',null,'so-diag-bar-fill');
    barFill.style.width=`${pct}%`;
    barWrap.append(barFill);
    const progress=node('span',`诊断进度：${diagnosticState.completed} / ${NETWORK_PROBES.length}`,'so-diag-progress');
    progressRow.append(barWrap,progress);
    wrap.append(progressRow);

    const rows=NETWORK_PROBES.map(([key,title],idx)=>{
      const found=items[idx]||null;
      const runningNow=diagnosticState.running&&idx===items.length;
      const targetCell=node('div',null,'so-diag-target');
      const targetCopy=node('div',null,'so-diag-target-copy');
      targetCopy.append(node('strong',title),node('small',`GET /network-diagnostic/ping?probe=${key}`));
      targetCell.append(node('span','∿','so-diag-icon'),targetCopy);
      const pill=node('span',found?(found.ok?'✓ 正常':'✕ 异常'):runningNow?'↻ 检测中':'○ 等待',`so-diag-pill ${found?(found.ok?'ok':'err'):runningNow?'run':'wait'}`);
      return [
        targetCell,
        pill,
        found?`${found.latencyMs}ms`:'-',
        found?found.detail:'等待执行同源连通性探测'
      ];
    });
    table(wrap,['目标','状态','耗时','传输'],rows);
    root.append(wrap);
  }

  function renderPersonalExport(t,s){
    const head=node('header',null,'so-hero-bar so-standalone-head');
    head.append(node('h1','个人信息查询与本地打包导出'),renderQuickSwitch(s));
    root.append(head);

    const exportBox=box('申请导出当前项目个人信息快照');
    exportBox.append(node('p','仅导出本人在当前项目范围内的固定身份资料、权限、申请记录与订单元数据快照（ZIP 压缩包，24 小时内有效）。','hint'));
    const exportTitle=field(exportBox,'导出申请说明','pe-title','text','本人申请导出当前项目个人信息快照');
    const exportBody=field(exportBox,'用途备注','pe-body','textarea','合规存档与个人记录核对');
    const fieldsSet=node('fieldset');
    fieldsSet.append(node('legend',msg("ui.personal_export_scope_only_your_information_in_this_project")));
    const checks=[];
    for(const [key,label]of [['profile',msg("ui.my_profile")],['memberships',msg("ui.current_project_permissions")],['requests',msg("ui.my_applications")],['orders',msg("ui.my_order_metadata")]]){
      const input=node('input');input.type='checkbox';
      input.checked=getDraft('pe-scope:'+key,true)!==false;
      input.addEventListener('change',()=>setDraft('pe-scope:'+key,input.checked));
      input.value=key;
      const line=node('label',label);line.prepend(input);fieldsSet.append(line);checks.push(input);
    }
    exportBox.append(fieldsSet,button('提交个人信息导出申请',()=>write('/requests',{
      kind:'personal_export',
      title:exportTitle.value,
      body:exportBody.value,
      contact:'',
      channel:'/personal-info-export',
      artifact_id:null,
      media_id:null,
      requested_fields:checks.filter(c=>c.checked).map(c=>c.value)
    }),!writable(),'so-btn-primary'));

    const historyBox=box('我的个人数据导出记录');
    const rows=data.requests.filter(r=>r.kind==='personal_export');
    table(historyBox,['申请编号','导出字段范围','当前状态','操作'],rows.map(row=>{
      const actions=node('div',null,'service-operations-actions');
      if(row.mine&&!['withdrawn','rejected'].includes(row.status)){
        actions.append(button(msg("ui.create_local_personal_data_file"),()=>write('/exports/build',{request_id:row.id}),!writable()));
      }
      if(row.export){
        actions.append(button(msg("ui.download_my_personal_data_zip"),async()=>{
          const response=await fetch(url(s.project,`/exports/${encodeURIComponent(row.export.id)}/content`),{credentials:'same-origin',headers:{'X-CSRF-Token':session().csrf}});
          if(!response.ok)throw new Error('文件不可下载，请核对有效期与当前权限');
          const blob=await response.blob();
          if(!same(t,s))return;
          const href=URL.createObjectURL(blob),a=node('a');a.href=href;a.download='personal-data.zip';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
        }));
      }
      return [row.id,(row.requested_fields||[]).join(', '),statuses[row.status]||row.status,actions];
    }));
  }

  function renderAccountClose(s){
    const head=node('header',null,'so-hero-bar so-standalone-head');
    head.append(node('h1','账户停用与注销核验'),renderQuickSwitch(s));
    root.append(head);

    const closeBox=box('申请核验账户停用条件');
    closeBox.append(node('p',msg("ui.deactivating_your_local_account_revokes_login_and_access_credentials"),'hint'));
    const closeTitle=field(closeBox,'注销申请标题','ac-title','text','申请停用本人本地操作账户');
    const closeBody=field(closeBox,'注销原因说明','ac-body','textarea','已完成当前工作区交接，申请核验停用条件');
    closeBox.append(button('1. 提交注销核验申请',()=>write('/requests',{
      kind:'account_close',
      title:closeTitle.value,
      body:closeBody.value,
      contact:'',
      channel:'/account-close',
      artifact_id:null,
      media_id:null,
      requested_fields:[]
    }),!writable(),'so-btn-primary'));

    const listBox=box('注销核验与正式执行');
    const rows=data.requests.filter(r=>r.kind==='account_close');
    table(listBox,['申请编号','标题','当前状态','下一步操作'],rows.map(row=>{
      const actions=node('div',null,'service-operations-actions');
      const terminal=['withdrawn','rejected','account_closed'].includes(row.status);
      if(row.mine&&!terminal){
        actions.append(button(msg("ui.preview_account_deactivation_impact"),()=>closeAccount(row),!writable()));
        const last=row.events?.at(-1);
        if(last)actions.append(button(msg("ui.withdraw_this_request"),()=>write('/requests/withdraw',{request_id:row.id,base_event_id:last.id,reason:'本人取消注销申请'}),!writable()));
      }
      return [row.id,row.title,statuses[row.status]||row.status,actions];
    }));
  }

  function renderOverview(t,s){
    const support=box('公告与支持');
    const diagnosis=node('p',null,'hint');
    support.append(button(msg("ui.check_local_connection"),async()=>{
      const started=perfNow();
      await ctx.api(url(s.project),{headers:{'X-CSRF-Token':session().csrf}});
      if(same(t,s))setText(diagnosis,msg("ui.local_request_succeeded_in_value0_ms_this_does_not",{value0:Math.round(perfNow()-started)}));
    }),button('打开 10 项网络诊断 →',()=>switchSubview('network-diagnostic')),diagnosis);
    for(const row of data.announcements.filter(a=>a.status==='published')){
      const article=node('article');article.append(node('h3',row.title),node('p',row.body));support.append(article);
    }
    const config=data.configuration?.document;
    if(config){
      support.append(node('p',config.support_text||msg("ui.support_information_is_not_filled_in")));
      for(const [key,label]of [['terms_url',msg("ui.terms_of_service")],['privacy_url',msg("ui.privacy_information")]]){
        if(config[key]){const a=node('a',label);a.href=config[key];a.target='_blank';a.rel='noopener noreferrer';support.append(a);}
      }
    }else support.append(node('p',msg("ui.service_descriptions_and_terms_links_are_not_configured"),'hint'));

    const form=box('提交申请');
    const kind=select(form,'申请类型',Object.entries(names),'kind');
    const title=field(form,msg("ui.request_title"),'title');
    const body=field(form,msg("ui.request_description_error_taskid"),'body','textarea');
    const contact=field(form,msg("ui.contact_information_optional"),'contact');
    const channel=field(form,msg("ui.target_platform_partner_channel_optional"),'channel');
    const artifact=select(form,'固定内容版本（分发必选）',[['','不关联内容版本']],'artifact');
    const media=select(form,'关联素材',[['','不关联素材']],'media');
    const mediaSearch=field(form,msg("ui.search_media_by_name"),'media-search');
    const loadMedia=async()=>{
      const result=await ctx.api('/api/v1/projects/'+s.project+'/media?'+new URLSearchParams({limit:'100',query:mediaSearch.value}));
      if(!same(t,s))return;
      media.replaceChildren(localizedOption('',msg("ui.no_linked_media")));
      for(const row of result.items||[])media.append(localizedOption(row.id,row.name));
    };
    form.append(button(msg("ui.search_media"),loadMedia));
    loadMedia().catch(()=>{});
    ctx.api('/api/v1/projects/'+s.project+'/artifacts').then(result=>{
      if(!same(t,s))return;
      for(const row of result.items||[])artifact.append(localizedOption(row.id,joinMessages([row.artifact_key||row.artifact_type," · v",row.version])));
    }).catch(()=>{});
    const fieldsSet=node('fieldset');
    fieldsSet.append(node('legend',msg("ui.personal_export_scope_only_your_information_in_this_project")));
    const checks=[];
    for(const [key,label]of [['profile',msg("ui.my_profile")],['memberships',msg("ui.current_project_permissions")],['requests',msg("ui.my_applications")],['orders',msg("ui.my_order_metadata")]]){
      const input=node('input');input.type='checkbox';
      input.checked=getDraft('export:'+key,true)!==false;
      input.addEventListener('change',()=>setDraft('export:'+key,input.checked));
      input.value=key;
      const line=node('label',label);line.prepend(input);fieldsSet.append(line);checks.push(input);
    }
    fieldsSet.hidden=kind.value!=='personal_export';
    kind.addEventListener('change',()=>{fieldsSet.hidden=kind.value!=='personal_export';});
    form.append(fieldsSet,button(msg("ui.save_local_request"),()=>write('/requests',{kind:kind.value,title:title.value,body:body.value,contact:contact.value,channel:channel.value,artifact_id:artifact.value||null,media_id:media.value||null,requested_fields:kind.value==='personal_export'?checks.filter(c=>c.checked).map(c=>c.value):[]}),!writable()));

    const requests=box('申请与处理记录');
    for(const row of data.requests){
      const card=node('article',null,'service-operations-request');
      card.append(node('h3',joinMessages(["",names[row.kind]," · ",row.title,""])),node('p',statuses[row.status]||row.status),node('p',row.body),node('small',row.id));
      if(row.kind==='account_close')card.append(node('p',msg("ui.deactivating_your_local_account_revokes_login_and_access_credentials"),'hint'));
      if(['distribution','fcp','studio','production_service'].includes(row.kind))card.append(node('p',msg("ui.no_external_service_is_configured_local_review_does_not"),'hint'));
      const actions=node('div',null,'service-operations-actions'),last=row.events.at(-1),terminal=['withdrawn','rejected','export_ready','account_closed'].includes(row.status);
      if(row.mine&&!terminal)actions.append(button(msg("ui.withdraw_this_request"),()=>write('/requests/withdraw',{request_id:row.id,base_event_id:last.id,reason:'本人从原申请撤回'}),!writable()));
      if(row.mine&&row.kind==='account_close'&&!terminal)actions.append(button(msg("ui.preview_account_deactivation_impact"),()=>closeAccount(row),!writable()));
      if(row.mine&&row.kind==='personal_export'&&!['withdrawn','rejected'].includes(row.status))actions.append(button(msg("ui.create_local_personal_data_file"),()=>write('/exports/build',{request_id:row.id}),!writable()));
      if(row.export)actions.append(button(msg("ui.download_my_personal_data_zip"),async()=>{
        const response=await fetch(url(s.project,`/exports/${encodeURIComponent(row.export.id)}/content`),{credentials:'same-origin',headers:{'X-CSRF-Token':session().csrf}});
        if(!response.ok)throw new Error('文件不可下载，请核对有效期与当前权限');
        const blob=await response.blob();if(!same(t,s))return;
        const href=URL.createObjectURL(blob),a=node('a');a.href=href;a.download='personal-data.zip';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
      }));
      if(data.manage&&!terminal&&row.kind!=='personal_export'){
        const processing=select(card,'本地处理状态 '+row.id,[['under_review','本地处理中'],['awaiting_configuration','外部服务待配置'],['local_approved','本地审核通过（未执行外部操作）'],['rejected','退回']],'status:'+row.id);
        const reason=field(card,msg("ui.handling_notes_value0",{value0:row.id}),'reason:'+row.id);
        actions.append(button(msg("ui.record_handling_of_this_request"),()=>write('/requests/process',{request_id:row.id,base_event_id:last.id,status:processing.value,reason:reason.value}),!writable()));
      }
      card.append(actions);
      const history=node('details');history.append(node('summary',msg("ui.view_processing_history")));
      for(const event of row.events)history.append(node('p',joinMessages(["",new Date(event.created_at).toLocaleString()," · ",statuses[event.status]||event.status," · ",event.reason,""])));
      card.append(history);requests.append(card);
    }
    if(!data.requests.length)requests.append(node('p',msg("ui.no_requests_visible_to_you"),'hint'));

    const api=box('固定项目 API 凭据');
    renderApiKeyBlock(api,s,{requireCompliance:false});
    const examples=node('pre');
    setText(examples,msg("ui.get_api_v1_service_api_projects_value0_jobs_get",{value0:s.project,value1:s.project,value2:s.project,value3:s.project}));
    api.append(examples,button(msg("ui.copy_api_example"),()=>clipWrite(examples.textContent)));
    if(data.api_catalog){
      const catalog=node('details');catalog.append(node('summary',msg("ui.view_available_api_capabilities")));
      for(const operation of data.api_catalog.operations)catalog.append(node('p',joinMessages([operation.method," ",operation.path," · ",operation.capability,operation.constraint?joinMessages([" · ",operation.constraint]):''])));
      api.append(catalog);
    }
    if(config?.api_documentation)api.append(node('p',config.api_documentation));
    table(api,['调用编号','操作','阶段','状态码','记录时间'],data.api_calls.map(c=>[c.call_id,c.operation,c.phase,c.status_code,new Date(c.created_at).toLocaleString()]));

    if(data.manage){
      const admin=box('管理员运营配置'),details=node('details');
      details.append(node('summary',msg("ui.edit_descriptions_terms_and_announcements")));
      const supportText=field(details,msg("ui.support_information"),'support','textarea',config?.support_text||'');
      const terms=field(details,msg("ui.terms_of_service_https_url"),'terms','text',config?.terms_url||'');
      const privacy=field(details,msg("ui.privacy_information_https_url"),'privacy','text',config?.privacy_url||'');
      const docs=field(details,msg("ui.api_documentation_notes"),'docs','textarea',config?.api_documentation||'');
      details.append(button(msg("ui.save_service_configuration_version"),()=>write('/configuration',{base_version_id:data.configuration?.id||null,document:{support_text:supportText.value,terms_url:terms.value,privacy_url:privacy.value,api_documentation:docs.value}}),!writable()));
      const announcementKey=field(details,msg("ui.announcement_code"),'announcement-key');
      const announcementTitle=field(details,msg("ui.announcement_title"),'announcement-title');
      const announcementBody=field(details,msg("ui.announcement_body"),'announcement-body','textarea');
      details.append(button(msg("ui.publish_project_announcement"),()=>write('/announcements',{announcement_key:announcementKey.value,base_version_id:data.announcements.find(a=>a.announcement_key===announcementKey.value)?.id||null,title:announcementTitle.value,body:announcementBody.value,status:'published'}),!writable()));
      for(const row of data.announcements.filter(a=>a.status==='published')){
        details.append(button(msg("ui.withdraw_announcement_value0",{value0:row.title}),()=>write('/announcements',{announcement_key:row.announcement_key,base_version_id:row.id,title:row.title,body:row.body,status:'withdrawn'}),!writable()));
      }
      admin.append(details);
    }
  }

  function render(){
    const scrollHost=root.parentElement||root;
    const prevScroll=scrollHost.scrollTop||0;
    if(root.getAttribute?.('tabindex')==null)root.setAttribute?.('tabindex','-1');
    root.replaceChildren();
    root.classList.add('service-operations');
    root.dataset.subview=subview;
    const s=scope,t=ticket;
    try{
      if(subview==='engine'){renderEngine(s);return;}
      if(subview==='data-records'){renderDataRecords(s);return;}
      if(subview==='seedance-verify'){renderSeedanceVerify(t,s);return;}
      if(subview==='feedback-records'){renderFeedbackRecords(t,s);return;}
      if(subview==='ai-drama-base'){renderAiDramaBase(s);return;}
      if(subview==='network-diagnostic'){renderNetworkDiagnostic(t,s);return;}
      if(subview==='personal-info-export'){renderPersonalExport(t,s);return;}
      if(subview==='account-close'){renderAccountClose(s);return;}
      if(subview==='activity'){
        const head=node('header',null,'so-hero-bar so-standalone-head');
        head.append(node('h1','天工工作台 · 运营专题活动'),renderQuickSwitch(s));
        root.append(head);
        summaryGrid(root,[
          ['充值解锁 DramaWave 承制权益','单部短剧保底出海分发','前往会员与钱包解锁承制合作名额'],
          ['投稿享 4x 流量分发加权','昆仑 AI 短剧基地联合扶持','支持多语种精校与海外渠道直发'],
          ['全模态创作算力活动','Seedance / 图像 / 剧本工具联动','所有消耗明细均记录在项目商业账本']
        ]);
        const actCard=box('当期活动与项目公告');
        const published=(data.announcements||[]).filter(a=>a.status==='published');
        if(published.length){
          for(const item of published){
            const row=node('article',null,'service-operations-request');
            row.append(node('h3',item.title),node('p',item.body));
            actCard.append(row);
          }
        }else{
          actCard.append(node('p','当前暂无额外项目内公告，可通过下方入口直达对应权益页面。','hint'));
        }
        const actions=node('div',null,'service-operations-actions');
        actions.append(
          button('前往会员与钱包 →',()=>ctx.navigate?.('commerce','wallet',s.project),false,'so-btn-primary'),
          button('了解 AI 短剧基地 →',()=>switchSubview('ai-drama-base'),false,'so-btn-ghost')
        );
        actCard.append(actions);
        return;
      }
      if(subview==='pc-only-notice'){
        const head=node('header',null,'so-hero-bar so-standalone-head');
        head.append(node('h1','建议使用桌面端浏览器访问'),renderQuickSwitch(s));
        root.append(head);
        const card=box('天工工作台核心画布与剪辑器面向桌面端大屏设计');
        card.append(node('p','无限画布多节点编排、多分镜轨道审片及批量字幕质检需要桌面端键鼠交互。请复制当前工作台地址并在电脑端 Chrome / Edge 打开。','hint'));
        const currentHref=globalThis.location?.href||'https://www.skyproduction.cn/';
        const actions=node('div',null,'service-operations-actions');
        actions.append(
          button('复制当前链接',async()=>{await clipWrite(currentHref);ctx.notice('已复制工作台链接，请在桌面浏览器粘贴打开');},false,'so-btn-primary'),
          button('返回工作台首页',()=>ctx.navigate?.('home'),false,'so-btn-ghost')
        );
        card.append(actions);
        return;
      }
      if(subview==='icon'){
        const head=node('header',null,'so-hero-bar so-standalone-head');
        head.append(node('h1','天工工作台 · 图标资产预览表'),renderQuickSwitch(s));
        root.append(head);
        const iconCatalog=[
          ['canvas-infinite','◈','无限画布与节点编排'],['script-studio','▤','剧本工作室与多语精校'],
          ['marketing-agent','✧','营销工作室与爆款创意'],['asset-library','❖','角色/场景/道具资产中心'],
          ['seedance-shield','🛡','Seedance 官方任务验真'],['tiangong-engine','⚡','天工引擎开放 API'],
          ['wallet-credits','✦','商业积分与电子发票'],['network-probe','✓','10 项全链路网络诊断']
        ];
        const card=box('内置语义图标检索（点击复制图标标识）');
        const searchInput=field(card,'搜索图标名称或场景','icon-filter','text','');
        searchInput.placeholder='输入关键词筛选图标…';
        const grid=node('div',null,'so-summary-grid');
        const paintIcons=()=>{
          const kw=searchInput.value.trim().toLowerCase();
          grid.replaceChildren();
          for(const [id,glyph,desc]of iconCatalog){
            if(kw&&!`${id} ${desc}`.toLowerCase().includes(kw))continue;
            const cell=node('article',null,'so-summary-card');
            cell.append(node('span',`${glyph} ${id}`,'so-summary-label'),node('strong',desc,'so-summary-value'),button('复制 ID',async()=>{await clipWrite(id);ctx.notice(`已复制图标标识 ${id}`);},false,'so-btn-ghost'));
            grid.append(cell);
          }
        };
        searchInput.addEventListener('input',paintIcons);
        paintIcons();
        card.append(grid);
        return;
      }
      if(subview==='terms'||subview==='privacy'||subview==='forbidden'||subview==='not-found'){
        const head=node('header',null,'so-hero-bar so-standalone-head');
        const title=subview==='terms'?'用户服务协议':subview==='privacy'?'隐私保护政策':subview==='not-found'?'404 · 页面不存在或已移动':'403 · 当前账号无访问权限';
        head.append(node('h1',title),renderQuickSwitch(s));
        root.append(head);
        const card=box(title);
        const cfg=data.configuration?.document||{};
        if(subview==='forbidden'){
          card.append(node('p','该页面仅面向企业工作室主管理员或具备对应项目角色权限的成员开放。请切换工作空间身份，或联系工作室管理员授权。','hint'));
        }else if(subview==='not-found'){
          card.append(node('p','未找到所请求的工作台路径，请核对链接地址或返回首页重新进入对应模块。','hint'));
        }else{
          const linkUrl=subview==='terms'?cfg.terms_url:cfg.privacy_url;
          card.append(node('p',cfg.support_text||'天工工作台遵循严格的数据隔离、审计追溯与生成合成内容标识规范。'));
          if(linkUrl){const a=node('a',linkUrl);a.href=linkUrl;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}
        }
        card.append(button('返回工作台首页',()=>ctx.navigate?.('home'),false,'so-btn-primary'));
        return;
      }

      const top=node('header',null,'so-topbar');
      const titleWrap=node('div');
      titleWrap.append(node('h1',msg("ui.services_public_api_and_personal_information")),node('p',msg("ui.local_requests_retain_processing_records_partnerships_sms_and_distribution"),'hint'));
      top.append(titleWrap,button(msg("ui.reload_service_records"),()=>load({...scope,subview})));
      root.append(top);

      const nav=node('nav',null,'so-subnav');
      bindAttribute(nav,'aria-label','平台服务与运营导航');
      for(const [id,label]of [
        ['overview','综合服务总览'],
        ['engine','天工引擎 API'],
        ['data-records','数据与消耗记录'],
        ['seedance-verify','Seedance 视频验真'],
        ['feedback-records','我的意见反馈'],
        ['ai-drama-base','昆仑 AI 短剧基地'],
        ['network-diagnostic','网络诊断'],
        ['personal-info-export','个人信息导出'],
        ['account-close','账户注销']
      ]){
        const b=button(label,()=>switchSubview(id));
        b.dataset.subview=id;
        b.setAttribute('aria-pressed',String(subview===id));
        nav.append(b);
      }
      root.append(nav);
      renderOverview(t,s);
    }finally{
      if(prevScroll>0)scrollHost.scrollTop=prevScroll;
    }
  }

  async function load(value){
    if(scope&&(scope.project!==value.project||scope.actor!==session().actor)){
      secrets.delete(identity(scope));
      if(scope.actor!==session().actor)keyAttempts.clear();
    }
    scope={...value,actor:session().actor};
    subview=normalizeOperationsSubview(value?.subview);
    const s=scope,t=++ticket;busy=false;
    resetScroll();
    root.replaceChildren(node('p',msg("ui.loading_service_records")));
    if((!s.project||!session().actor)&&['terms','privacy','pc-only-notice','icon','forbidden','not-found','activity','network-diagnostic','ai-drama-base','seedance-verify','engine'].includes(subview)){
      data={configuration:{document:{}},announcements:[],requests:[],api_keys:[],api_calls:[],api_catalog:null,engine_overview:{credit_balance:0,total_consumed_credits:0,ledger_records:[],recharge_orders:[],reservations:[],recent_jobs:[],member_usage:[]}};
      render();
      resetScroll(true);
      return;
    }
    if(!s.project){root.replaceChildren(node('p',msg("ui.select_a_project_first")));return;}
    if(!session().actor){root.replaceChildren(node('p',msg("ui.sign_in_to_perform_this_action")));return;}
    try{
      const result=await ctx.api(url(s.project),{headers:{'X-CSRF-Token':session().csrf}});
      if(!same(t,s))return;
      data=result;
      ctx.setRevision(result.revision,s.project);
      render();
      resetScroll(true);
    }catch(e){
      if(same(t,s))root.replaceChildren(node('p',e.message),button(msg("ui.retry_loading"),()=>load(s)));
    }
  }

  return {load,suspend(){if(scope)secrets.delete(identity(scope));ticket++;scope=null;busy=false;}};
}
