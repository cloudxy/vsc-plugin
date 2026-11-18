import {msg,joinMessages,setText,bindAttribute,option as localizedOption} from './i18n.js';
import {createGovernanceNav} from './governance-header.js';
// Commercial credits and invoices never substitute for original native usage.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const setComp=(node,name)=>{node.dataset.component=name;node.setAttribute('data-component',name);return node;};
const isDomNode=v=>Boolean(v&&typeof v==='object'&&typeof v.tagName==='string');
const clipWrite=async text=>{const nav=typeof navigator!=='undefined'?navigator:globalThis.navigator;await nav?.clipboard?.writeText?.(text);};
const labels={created:'待创建收银台',checkout_unknown:'收银台结果待核对',pending:'待处理',paid:'已支付',expired:'已过期',cancelled:'已取消',refund_unknown:'退款结果待核对',refunded:'已退款',unconfigured:'服务未配置，申请已保留',submission_unknown:'申请结果待核对',issued:'已开具',failed:'处理失败',reserved:'已预留',settled:'已结算',released:'已释放',credit:'通用信用',bonus:'赠送额度',check_in:'签到额度',special:'专项额度'};
const INVOICE_TYPES=[
  ['enterprise_normal','企业增值税普通发票'],
  ['enterprise_special','企业增值税专用发票'],
  ['personal','个人 / 非企业单位']
];
const RATE_UNITS=[
  ['remote_jobs','远程任务 (remote_jobs)'],
  ['images','图像张数 (images)'],
  ['video_seconds','视频秒数 (video_seconds)'],
  ['audio_jobs','音频任务 (audio_jobs)'],
  ['speech_chars','语音字数 (speech_chars)'],
  ['vision_jobs','视觉分析 (vision_jobs)']
];
const BUCKET_KINDS=[
  ['credit','通用信用 (credit)'],
  ['special','专项额度 (special)']
];
const REFUND_POLICIES=[
  ['unused_order_only','仅未动用订单全额可退 (unused_order_only)'],
  ['none','不支持自助退款 (none)']
];
const RENEWAL_POLICIES=[
  ['manual_from_payment','人工续购自支付起算 (manual_from_payment)'],
  ['none','不开放续购 (none)']
];
const CAMPAIGN_KINDS=[
  ['bonus','活动赠送额度 (bonus)'],
  ['check_in','每日签到额度 (check_in)'],
  ['special','专项定向额度 (special)']
];

export function normalizeCommerceSubview(raw){
  const v=String(raw||'wallet').trim().toLowerCase();
  if(v==='invoice'||v==='invoice-overview')return 'invoice-overview';
  if(['invoice-apply','apply'].includes(v))return 'invoice-apply';
  if(['invoice-orders','orders'].includes(v))return 'invoice-orders';
  if(['invoice-history','history'].includes(v))return 'invoice-history';
  if(['invoice-titles','titles'].includes(v))return 'invoice-titles';
  if(['studio-quota','quota'].includes(v))return 'studio-quota';
  return 'wallet';
}

export function validateInvoiceTaxId(taxId,invoiceType='enterprise_normal'){
  if(invoiceType==='personal'){
    const raw=String(taxId||'').trim();
    return {valid:true,standard18:false,normalized:raw||'PERSONAL',hint:'个人或非企业抬头无需填写统一社会信用代码（系统按个人抬头登记）。'};
  }
  const normalized=String(taxId||'').trim().toUpperCase();
  if(!normalized||normalized==='PERSONAL')return {valid:false,standard18:false,normalized:'',hint:'请输入 18 位统一社会信用代码（或 15–32 位有效纳税人识别号）。'};
  const standard18=/^[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}$/.test(normalized);
  const valid=standard18||/^[A-Z0-9]{15,32}$/.test(normalized)||/^[A-Z0-9-]{4,32}$/.test(normalized);
  return {
    valid,
    standard18,
    normalized,
    hint:standard18?'统一社会信用代码（18 位）格式校验通过。':valid?'已录入自定义纳税识别号，请核对与营业执照一致。':'税号格式异常：请填写 18 位统一社会信用代码或字母数字税号。'
  };
}

export function formatMinorAmount(amountMinor,currency='CNY'){
  const n=Number(amountMinor||0);
  if(!Number.isFinite(n))return `${amountMinor} ${currency}`;
  const major=(n/100).toFixed(2);
  const sym=currency==='CNY'?'¥':currency==='USD'?'$':'';
  return sym?`${sym}${major} (${n} ${currency})`:`${major} ${currency}`;
}

function defaultPlanDraft(plans=[],providerModels=[]){
  const first=plans[0]?.document||null;
  const fallbackModel=providerModels[0]?.id||'model-default';
  return {
    base_version_id:plans[0]?.id||'',
    metering_enabled:true,
    plan_key:first?.plan_key||'pro_monthly',
    title:first?.title||'专业版月度套餐',
    currency:first?.currency||'CNY',
    amount_minor:String(first?.amount_minor??9900),
    credits:String(first?.credits??1000),
    bucket_kind:first?.bucket_kind||'credit',
    validity_days:String(first?.validity_days??30),
    checkout_minutes:String(first?.checkout_minutes??30),
    purposes:Array.isArray(first?.purposes)&&first.purposes.length?first.purposes.join(','):'*',
    max_concurrent_jobs:String(first?.max_concurrent_jobs??8),
    seat_limit:String(first?.seat_limit??20),
    invoice_enabled:first?.invoice_enabled!==false,
    watermark_required:Boolean(first?.watermark_required),
    refund_policy:first?.refund_policy||'unused_order_only',
    renewal_policy:first?.renewal_policy||'manual_from_payment',
    rates:Array.isArray(first?.rates)&&first.rates.length
      ?first.rates.map(r=>({model_id:String(r.model_id||''),unit:r.unit||'video_seconds',credits_per_unit:String(r.credits_per_unit??10)}))
      :[{model_id:fallbackModel,unit:'video_seconds',credits_per_unit:'10'}]
  };
}

function defaultCampaignDraft(){
  return {
    code:'SPRING2026',
    title:'春季创作激励活动',
    credits:'200',
    kind:'bonus',
    purposes:'*',
    starts_at:'2026-11-15T00:00:00Z',
    ends_at:'2026-12-31T23:59:59Z',
    credit_expires_at:'2027-01-31T23:59:59Z',
    daily:false
  };
}

function parsePurposes(raw){
  const list=String(raw||'').split(',').map(s=>s.trim()).filter(Boolean);
  return [...new Set(list)];
}

function buildCanonicalPlanDocument(draft){
  return {
    plan_key:String(draft.plan_key||'').trim(),
    title:String(draft.title||'').trim(),
    currency:String(draft.currency||'CNY').trim().toUpperCase(),
    amount_minor:Number(draft.amount_minor),
    credits:Number(draft.credits),
    bucket_kind:String(draft.bucket_kind||'credit'),
    validity_days:Number(draft.validity_days),
    checkout_minutes:Number(draft.checkout_minutes),
    purposes:parsePurposes(draft.purposes),
    max_concurrent_jobs:Number(draft.max_concurrent_jobs),
    seat_limit:Number(draft.seat_limit),
    invoice_enabled:Boolean(draft.invoice_enabled),
    watermark_required:Boolean(draft.watermark_required),
    refund_policy:String(draft.refund_policy||'unused_order_only'),
    renewal_policy:String(draft.renewal_policy||'manual_from_payment'),
    rates:(draft.rates||[]).map(r=>({
      model_id:String(r.model_id||'').trim(),
      unit:String(r.unit||'video_seconds'),
      credits_per_unit:Number(r.credits_per_unit)
    }))
  };
}

function validatePlanDraftClient(doc){
  if(!/^[a-zA-Z0-9_-]{1,80}$/.test(doc.plan_key))return '套餐唯一标识 (plan_key) 需为 1–80 位字母、数字、下划线或连字符';
  if(!doc.title||doc.title.length>200)return '套餐标题长度需在 1–200 字之间';
  if(!/^[A-Z]{3}$/.test(doc.currency))return '结算币种需为 3 位大写字母（如 CNY、USD）';
  for(const [k,label,min,max]of [
    ['amount_minor','实付金额分值',1,1000000000000],
    ['credits','发放商业信用',1,1000000000000],
    ['validity_days','有效天数',1,3650],
    ['checkout_minutes','收银台有效分钟',1,1440],
    ['max_concurrent_jobs','最大并发任务数',1,100],
    ['seat_limit','席位上限',1,10000]
  ]){
    const n=doc[k];
    if(!Number.isInteger(n)||n<min||n>max)return `${label} 需为 ${min}–${max} 之间的整数`;
  }
  if(!doc.purposes.length||doc.purposes.some(p=>!/^(\*|[a-z][a-z0-9_]{0,63})$/.test(p)))return '允许用途列表非空，且每项须为 * 或小写标识码';
  if(!Array.isArray(doc.rates)||doc.rates.length<1||doc.rates.length>200)return '费率矩阵行数须在 1–200 行之间';
  const seen=new Set();
  for(let i=0;i<doc.rates.length;i++){
    const r=doc.rates[i];
    if(!r.model_id)return `第 ${i+1} 行费率缺少模型标识 (model_id)`;
    if(!RATE_UNITS.some(([u])=>u===r.unit))return `第 ${i+1} 行计量单位非法`;
    if(!Number.isInteger(r.credits_per_unit)||r.credits_per_unit<1)return `第 ${i+1} 行每单位信用单价须为正整数`;
    const pair=`${r.model_id}::${r.unit}`;
    if(seen.has(pair))return `费率矩阵存在重复的 (模型, 计量单位) 组合：${r.model_id} × ${r.unit}`;
    seen.add(pair);
  }
  return null;
}

function buildCanonicalCampaignDocument(draft){
  return {
    code:String(draft.code||'').trim(),
    title:String(draft.title||'').trim(),
    credits:Number(draft.credits),
    kind:String(draft.kind||'bonus'),
    purposes:parsePurposes(draft.purposes),
    starts_at:String(draft.starts_at||'').trim(),
    ends_at:String(draft.ends_at||'').trim(),
    credit_expires_at:String(draft.credit_expires_at||'').trim(),
    daily:Boolean(draft.daily)
  };
}

function validateCampaignDraftClient(doc){
  if(!doc.code||doc.code.length<6||doc.code.length>100)return '活动兑换码长度须在 6–100 字符之间';
  if(!doc.title||doc.title.length>200)return '活动标题长度须在 1–200 字符之间';
  if(!Number.isInteger(doc.credits)||doc.credits<1)return '赠送信用数须为正整数';
  if(!CAMPAIGN_KINDS.some(([k])=>k===doc.kind))return '额度类型不合法';
  if(!doc.purposes.length)return '活动允许用途不能为空';
  if(!doc.starts_at||!doc.ends_at||!doc.credit_expires_at)return '请完整填写生效、截止与额度过期 UTC 时间';
  return null;
}

export function createCommerce(root,ctx){
  // Strictly zero implicit session workspace state (D-NO-CURRENT-SPACE) and zero in-memory localTitles.
  let ticket=0,scope=null,data=null,platformData=null,busy=false,subview='wallet',serverTitles=[],orderFilter='all',historyFilter='all';
  let loadController=null,diffDialogState=null,stageHost=null;
  const resolveStage=parent=>(!parent||parent===root)&&stageHost?.parentElement===root?stageHost:(parent||root);
  const drafts=new Map(),pending=new Map(),scopeRevisions=new Map();

  const session=()=>ctx.session();
  const writable=()=>{
    const s=session();
    if(!s.actor)return false;
    if(scope?.scopeKind==='project')return Boolean(s.writable);
    return Boolean(s.writable??s.writeAvailable??true);
  };
  const same=(t,s)=>ticket===t&&scope===s;

  function normalizeScope(raw={}){
    let scopeKind=raw.scopeKind||'';
    let workspaceId=raw.workspaceId||'';
    let project=raw.project||'';
    if(scopeKind==='workspace'&&workspaceId){
      return {...raw,scopeKind:'workspace',workspaceId,project:''};
    }
    if(scopeKind==='identity'){
      return {...raw,scopeKind:'identity',workspaceId:'',project:''};
    }
    if(scopeKind==='project'||(!scopeKind&&project)){
      return {...raw,scopeKind:'project',workspaceId:'',project};
    }
    return {...raw,scopeKind:'identity',workspaceId:'',project:''};
  }

  function scopeToken(s=scope){
    if(!s)return 'identity:self';
    if(s.scopeKind==='workspace'&&s.workspaceId)return `workspace:${s.workspaceId}`;
    if(s.scopeKind==='project'&&s.project)return `project:${s.project}`;
    return 'identity:self';
  }

  function commerceUrl(s=scope,suffix=''){
    if(s?.scopeKind==='workspace'&&s.workspaceId)return `/api/v1/workspaces/${encodeURIComponent(s.workspaceId)}/commerce${suffix}`;
    if(s?.scopeKind==='project'&&s.project)return `/api/v1/projects/${encodeURIComponent(s.project)}/commerce${suffix}`;
    return `/api/v1/account/commerce${suffix}`;
  }

  function adminCommerceUrl(s=scope,suffix=''){
    if(s?.scopeKind==='project'&&s.project)return `/api/v1/projects/${encodeURIComponent(s.project)}/commerce${suffix}`;
    return `/api/v1/platform/commerce${suffix}`;
  }

  function currentRevision(s=scope){
    const tok=scopeToken(s);
    if(scopeRevisions.has(tok))return scopeRevisions.get(tok);
    if(data?.revision!=null)return data.revision;
    return session().revision??0;
  }

  function recordRevision(rev,s=scope){
    if(rev==null)return;
    scopeRevisions.set(scopeToken(s),rev);
    if(s?.scopeKind==='project'&&s.project)ctx.setRevision?.(rev,s.project);
    else ctx.setRevision?.(rev,null);
  }

  function currentAdminRevision(s=scope){
    if(s?.scopeKind==='project'&&s.project)return currentRevision(s);
    if(platformData?.revision!=null)return platformData.revision;
    if(scopeRevisions.has('platform:commerce'))return scopeRevisions.get('platform:commerce');
    return currentRevision(s);
  }

  const draftKey=key=>`${scopeToken()}:${session().actor||''}:${key}`;
  const getDraft=(key,fallback='')=>drafts.has(draftKey(key))?drafts.get(draftKey(key)):fallback;
  const setDraft=(key,val)=>{drafts.set(draftKey(key),val);return val;};
  const adminDraftKey=key=>`admin:${scope?.scopeKind==='project'?scope.project:'platform'}:${session().actor||''}:${key}`;
  const getAdminDraft=(key,fallbackFn)=>{
    const k=adminDraftKey(key);
    if(!drafts.has(k))drafts.set(k,fallbackFn());
    return drafts.get(k);
  };
  const setAdminDraft=(key,val)=>{drafts.set(adminDraftKey(key),val);return val;};

  const actorLabel=actor=>{
    if(!actor){
      if(scope?.scopeKind==='identity')return `个人钱包 (${session().actor||'本人'})`;
      if(scope?.scopeKind==='workspace')return '团队公共资金池';
      return '项目公共池';
    }
    if(actor===session().actor)return `本人 (${actor})`;
    const found=(data?.workspace?.members||[]).find(m=>m.actor===actor);
    return found?`${found.display_name} (${actor})`:actor;
  };

  function mergedTitles(){
    const source=serverTitles.length?serverTitles:(Array.isArray(data?.invoice_titles)?data.invoice_titles:[]);
    const out=[],seen=new Set();
    for(const item of source){
      const key=item.id||`${item.title}::${item.tax_id}`;
      if(seen.has(key))continue;
      seen.add(key);
      out.push(item);
    }
    return out;
  }

  function button(title,fn,disabled=false,cls=''){
    const b=el('button',title,cls);b.type='button';b.disabled=disabled;
    b.addEventListener('click',async()=>{
      const t=ticket,s=scope;
      try{await fn();}catch(e){if(same(t,s))ctx.notice(msg("ui.value0_inputs_and_original_order_preserved",{value0:e.message||String(e)}));}
    });
    return b;
  }
  function field(parent,title,node){bindAttribute(node,'aria-label',title);const label=el('label',title,'commerce-field');label.append(node);parent.append(label);return node;}
  function input(parent,title,key,type='text',fallback=''){
    const n=el('input');n.type=type;
    n.value=getDraft(key,fallback);
    n.addEventListener('input',()=>setDraft(key,n.value));
    return field(parent,title,n);
  }
  function box(title,parent=root,cls='commerce-card',comp=null){
    const n=el('section',null,cls);
    if(comp)setComp(n,comp);
    n.append(el('h2',title));
    resolveStage(parent).append(n);
    return n;
  }
  function summaryGrid(parent,items){
    const grid=el('dl',null,'commerce-summary-grid');
    for(const [dt,dd,sub]of items){
      const cell=el('div',null,'commerce-summary-cell');
      cell.append(el('dt',dt),el('dd',String(dd)));
      if(sub)cell.append(el('small',sub));
      grid.append(cell);
    }
    resolveStage(parent).append(grid);
    return grid;
  }
  function table(parent,head,rows){
    const t=el('table'),h=el('tr');
    for(const value of head)h.append(el('th',value));
    t.append(h);
    for(const row of rows){
      const tr=el('tr');
      for(const value of row){
        const td=el('td');
        if(isDomNode(value))td.append(value);
        else setText(td,value??'—');
        tr.append(td);
      }
      t.append(tr);
    }
    if(!rows.length){
      const tr=el('tr'),td=el('td','暂无记录');
      td.colSpan=head.length;tr.append(td);t.append(tr);
    }
    const frame=el('div',null,'commerce-table');frame.append(t);parent.append(frame);
    return frame;
  }

  function attachGovNav(headerEl){
    headerEl.append(createGovernanceNav({
      active:'commerce',
      returnContext:ctx.returnContext||null,
      onSwitch:target=>ctx.onGovernanceNavigate?ctx.onGovernanceNavigate(target):ctx.navigate?.(target,null,scope?.project||null),
      onReturn:ctx.onReturnContext||null,
      doc:document
    }));
  }

  function availableWorkspaces(){
    const list=[];
    const seen=new Set();
    for(const w of ctx.workspaces?.()||[]){
      const id=w.id||w.workspace_id;
      if(!id||seen.has(id))continue;
      seen.add(id);
      list.push({id,name:w.name||w.workspace_name||id});
    }
    if(data?.workspace?.workspace_id&&!seen.has(data.workspace.workspace_id)){
      list.push({id:data.workspace.workspace_id,name:data.workspace.workspace_name||data.workspace.workspace_id});
    }
    return list;
  }

  function availableProjects(){
    const list=[];
    const seen=new Set();
    for(const p of ctx.projects?.()||[]){
      if(!p?.id||p.unavailable||p.recycled_at||(p.storage_policy&&p.storage_policy!=='postgres-series-v1'))continue;
      seen.add(p.id);
      list.push({id:p.id,name:p.name||p.title||p.id});
    }
    if(scope?.project&&!seen.has(scope.project)){
      list.push({id:scope.project,name:scope.project});
    }
    return list;
  }

  function currentPoolLabel(s=scope){
    if(s?.scopeKind==='workspace'&&s.workspaceId){
      const ws=availableWorkspaces().find(w=>w.id===s.workspaceId);
      return `团队资金池 · ${ws?.name||s.workspaceId}`;
    }
    if(s?.scopeKind==='project'&&s.project){
      const pr=availableProjects().find(p=>p.id===s.project);
      return `项目账本 · ${pr?.name||s.project}`;
    }
    return `个人钱包 · ${session().actor||'当前账号'}`;
  }

  function renderFundingPoolBar(){
    const bar=el('section',null,'commerce-pool-bar');
    setComp(bar,'commerce-funding-pool-bar');
    const info=el('div',null,'commerce-pool-copy');
    info.append(
      el('strong',`当前显式资金池：${currentPoolLabel()}`),
      el('span','资金池切换仅改变本页查看与充值的目标账本，绝不隐式修改新建项目默认归属（D-NO-CURRENT-SPACE）。','hint')
    );
    const controls=el('div',null,'commerce-actions');
    const poolSelect=el('select');
    bindAttribute(poolSelect,'aria-label','显式资金池选择');
    poolSelect.append(localizedOption('identity:',`个人钱包（${session().actor||'本人'}）`));
    for(const ws of availableWorkspaces()){
      poolSelect.append(localizedOption(`workspace:${ws.id}`,`团队资金池 · ${ws.name}`));
    }
    for(const pr of availableProjects()){
      poolSelect.append(localizedOption(`project:${pr.id}`,`项目账本 · ${pr.name}`));
    }
    const activeVal=scope?.scopeKind==='workspace'&&scope.workspaceId
      ?`workspace:${scope.workspaceId}`
      :scope?.scopeKind==='project'&&scope.project
        ?`project:${scope.project}`
        :'identity:';
    poolSelect.value=activeVal;
    poolSelect.addEventListener('change',()=>{
      const [kind,id]=poolSelect.value.split(':');
      if(kind==='workspace'&&id)return load({subview,scopeKind:'workspace',workspaceId:id,project:''});
      if(kind==='project'&&id)return load({subview,scopeKind:'project',workspaceId:'',project:id});
      return load({subview,scopeKind:'identity',workspaceId:'',project:''});
    });
    controls.append(poolSelect,button(msg("ui.reload_ledger"),()=>load({...scope,subview})));
    bar.append(info,controls);
    resolveStage(root).append(bar);
  }

  async function loadServerTitles(query='',signal=undefined){
    const t=ticket,s=scope;
    try{
      const q=query?`?q=${encodeURIComponent(query)}`:'';
      const init={headers:{'X-CSRF-Token':session().csrf},...(signal?{signal}:{})};
      const res=await ctx.api(commerceUrl(s,`/invoice-titles${q}`),init);
      if(same(t,s)&&Array.isArray(res?.items)){
        serverTitles=res.items;
        if(res.revision!=null)recordRevision(res.revision,s);
      }
    }catch(err){
      if(err?.name==='AbortError')return;
      if(same(t,s)&&Array.isArray(data?.invoice_titles))serverTitles=data.invoice_titles;
    }
  }

  async function loadPlatformCatalog(signal=undefined){
    const t=ticket,s=scope;
    if(s?.scopeKind==='project')return;
    if(!data?.capabilities?.platform_admin)return;
    try{
      const res=await ctx.api('/api/v1/platform/commerce',{headers:{'X-CSRF-Token':session().csrf},...(signal?{signal}:{})});
      if(same(t,s)&&res&&typeof res==='object'){
        platformData=res;
        if(res.revision!=null)scopeRevisions.set('platform:commerce',res.revision);
      }
    }catch{
      // Non-platform test fixtures without /api/v1/platform/commerce remain cleanly functional.
    }
  }

  function switchSubview(next,extra={}){
    subview=normalizeCommerceSubview(next);
    if(extra.orderId)setDraft('invoice-order-id',extra.orderId);
    if(extra.titleObj){
      setDraft('invoice-title',extra.titleObj.title||'');
      setDraft('invoice-tax',extra.titleObj.tax_id||'');
      if(extra.titleObj.email)setDraft('invoice-email',extra.titleObj.email);
      const tType=extra.titleObj.invoice_type||extra.titleObj.title_type||'enterprise_normal';
      setDraft('invoice-type',tType==='personal'?'personal':tType);
    }
    if(scope)scope.subview=subview;
    ctx.onSubviewChange?.(subview,extra.orderId||null);
    render();
  }

  async function write(path,payload,{reload=true}={}){
    const t=ticket,s=scope;
    if(!writable())throw new Error('当前会话只读');
    if(busy)throw new Error('上一操作仍在处理中');
    busy=true;
    const targetUrl=commerceUrl(s,path);
    const tag=targetUrl+JSON.stringify(payload);
    const identity=pending.get(tag)||{key:crypto.randomUUID(),revision:currentRevision(s)};
    pending.set(tag,identity);
    try{
      const result=await ctx.api(targetUrl,{
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
        body:JSON.stringify({payload,expected_revision:identity.revision,idempotency_key:identity.key})
      });
      pending.delete(tag);
      if(same(t,s)){
        if(result?.revision!=null)recordRevision(result.revision,s);
        if(reload)await load({...s,subview});
      }
      return result;
    }catch(e){
      if(e.status===409)pending.delete(tag);
      throw e;
    }finally{
      if(same(t,s))busy=false;
    }
  }

  async function savePersistentInvoiceTitle(titlePayload,{silent=false}={}){
    const t=ticket,s=scope;
    if(!writable())throw new Error('当前会话只读');
    const targetUrl=commerceUrl(s,'/invoice-titles');
    const res=await ctx.api(targetUrl,{
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
      body:JSON.stringify({
        payload:titlePayload,
        expected_revision:currentRevision(s),
        idempotency_key:crypto.randomUUID()
      })
    });
    if(!same(t,s))return res;
    if(res?.revision!=null)recordRevision(res.revision,s);
    await loadServerTitles();
    if(!same(t,s))return res;
    const savedItem=res?.item||{id:res?.id||`tpl-${Date.now()}`,...titlePayload};
    if(!serverTitles.some(x=>(savedItem.id&&x.id===savedItem.id)||(x.title===savedItem.title&&x.tax_id===savedItem.tax_id))){
      if(savedItem.is_default)serverTitles=serverTitles.map(x=>({...x,is_default:false}));
      serverTitles=[savedItem,...serverTitles];
    }else if(savedItem.is_default){
      serverTitles=serverTitles.map(x=>({
        ...x,
        is_default:(savedItem.id&&x.id===savedItem.id)||(x.title===savedItem.title&&x.tax_id===savedItem.tax_id)
      }));
    }
    if(!silent){
      ctx.notice('已保存常用发票抬头');
      render();
    }
    return res;
  }

  async function deletePersistentInvoiceTitle(item){
    const t=ticket,s=scope;
    if(!writable())throw new Error('当前会话只读');
    const titleId=item.id||`${item.title}::${item.tax_id}`;
    const targetUrl=commerceUrl(s,`/invoice-titles/${encodeURIComponent(titleId)}`);
    const res=await ctx.api(targetUrl,{
      method:'DELETE',
      headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
      body:JSON.stringify({
        expected_revision:currentRevision(s),
        idempotency_key:crypto.randomUUID()
      })
    });
    if(!same(t,s))return res;
    if(res?.revision!=null)recordRevision(res.revision,s);
    serverTitles=serverTitles.filter(x=>item.id?x.id!==item.id:!(x.title===item.title&&x.tax_id===item.tax_id));
    await loadServerTitles();
    if(same(t,s)){
      ctx.notice('已删除常用发票抬头');
      render();
    }
    return res;
  }

  function renderSupportBanner(parent){
    const info=data?.invoice_summary||{};
    const email=String(info.support_email||data?.support_email||'').trim();
    const hours=String(info.service_hours||data?.service_hours||'').trim();
    const banner=el('footer',null,'commerce-support-banner');
    const copy=el('div',null,'commerce-support-copy');
    copy.append(
      el('strong','联系客服'),
      el('p',`反馈邮箱：${email||'未配置支持邮箱（请在平台运维配置中设置）'}`),
      el('p',`客服时间：${hours||'以平台公告服务时间为准'}`),
      el('p','支付异常、退款后开票、专票信息补录等情况，可通过官方支持渠道联系处理。')
    );
    banner.append(
      copy,
      button('复制客服邮箱',async()=>{
        if(!email)return;
        await clipWrite(email);
        ctx.notice(`已复制客服邮箱：${email}`);
      },!email)
    );
    resolveStage(parent).append(banner);
  }

  function renderInvoiceSegmentCard(){
    const card=el('section',null,'commerce-card commerce-invoice-segment-card');
    const head=el('div',null,'commerce-invoice-segment-head');
    const copy=el('div');
    const isPortal=subview==='invoice-overview';
    copy.append(
      el('span','我的钱包 / 电子发票','commerce-crumb-path'),
      el('h2',isPortal?'电子发票中心 · 申请开票':'电子发票中心'),
      el('p',isPortal?'请选择需要办理的开票服务，或切换下方五向分段办理具体事项。':'管理可开票订单、历史发票与常用发票抬头','hint')
    );
    const backBtn=button('← 返回我的钱包',()=>switchSubview('wallet'),false,'commerce-back-btn');
    bindAttribute(backBtn,'aria-label','返回我的钱包');
    head.append(copy,backBtn);
    const seg=el('div',null,'commerce-invoice-segments');
    seg.setAttribute('role','tablist');
    bindAttribute(seg,'aria-label','电子发票导航');
    const segItems=[
      ['invoice-overview','发票总览'],
      ['invoice-apply','申请开票'],
      ['invoice-orders','可开票订单'],
      ['invoice-history','开票历史'],
      ['invoice-titles','常用发票抬头']
    ];
    const segButtons=[];
    for(const [id,label]of segItems){
      const active=subview===id;
      const b=button(label,()=>switchSubview(id));
      b.dataset.subview=id;
      b.setAttribute('role','tab');
      b.setAttribute('aria-selected',String(active));
      b.setAttribute('aria-pressed',String(active));
      segButtons.push(b);
      seg.append(b);
    }
    segButtons.forEach((btnNode,idx)=>btnNode.addEventListener('keydown',event=>{
      if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
        event.preventDefault?.();
        const nextIdx=(idx+(event.key==='ArrowRight'?1:segButtons.length-1))%segButtons.length;
        switchSubview(segItems[nextIdx][0]);
        root.querySelector?.(`.commerce-invoice-segments [data-subview="${segItems[nextIdx][0]}"]`)?.focus?.();
      }
    }));
    card.append(head,seg);
    resolveStage(root).append(card);
  }

  async function downloadInvoicePdf(row,t,s){
    const response=await fetch(commerceUrl(s,`/invoices/${encodeURIComponent(row.id)}/content`),{credentials:'same-origin',headers:{'X-CSRF-Token':session().csrf}});
    if(!response.ok)throw new Error('发票暂不可下载');
    const blob=await response.blob();
    if(!same(t,s))return;
    const href=URL.createObjectURL(blob),a=el('a');
    a.href=href;a.download='invoice.pdf';a.click();
    const timer=setTimeout(()=>URL.revokeObjectURL(href),1000);
    timer?.unref?.();
  }

  function invoiceStatusForOrder(orderId){
    return (data?.invoices||[]).find(inv=>inv.order_id===orderId&&inv.status!=='void')||null;
  }

  function renderInvoiceOverview(){
    renderInvoiceSegmentCard();
    const ordersList=data.orders||[];
    const invoicesList=data.invoices||[];
    const paidOrders=ordersList.filter(o=>o.status==='paid');
    const billableOrders=paidOrders.filter(o=>!invoiceStatusForOrder(o.id));
    const issuedCount=invoicesList.filter(i=>i.status==='issued').length;
    const titles=mergedTitles();
    const supportEmail=String(data.invoice_summary?.support_email||data.support_email||'').trim();
    const grid=el('section',null,'commerce-portal-grid');
    setComp(grid,'commerce-invoice-center');
    const cards=[
      {
        glyph:'＋',
        title:'开发票',
        badge:`待开票 ${billableOrders.length} 笔`,
        desc:'选择可开票充值订单，填写发票信息后提交申请。',
        cta:'立即去开票',
        primary:true,
        onClick:()=>switchSubview('invoice-apply',{orderId:billableOrders[0]?.id||''})
      },
      {
        glyph:'↺',
        title:'历史发票',
        badge:`记录 ${invoicesList.length} 条`,
        desc:'查看开票记录，支持核对状态与下载 PDF 电子发票文件。',
        cta:'查看开票历史',
        onClick:()=>switchSubview('invoice-history')
      },
      {
        glyph:'▤',
        title:'常用发票抬头',
        badge:`抬头 ${titles.length} 组`,
        desc:'维护企业、个人等持久化常用抬头并设置默认项，开票一键带入。',
        cta:'管理发票抬头',
        onClick:()=>switchSubview('invoice-titles')
      },
      {
        glyph:'☏',
        title:'联系客服',
        badge:'专属财务支持',
        desc:'支付异常、退款后开票、专票信息补录可联系处理。',
        cta:'复制客服邮箱',
        onClick:async()=>{
          if(!supportEmail){ctx.notice('当前尚未配置官方支持邮箱');return;}
          await clipWrite(supportEmail);
          ctx.notice(`请联系官方财务客服：${supportEmail}`);
        }
      }
    ];
    for(const item of cards){
      const card=el('article',null,'commerce-portal-card');
      const head=el('div',null,'commerce-portal-head');
      head.append(el('span',item.glyph,'commerce-portal-glyph'),el('span',item.badge,'commerce-badge'));
      card.append(head,el('h2',item.title),el('p',item.desc),button(item.cta,item.onClick,false,item.primary?'commerce-btn-primary':''));
      grid.append(card);
    }
    resolveStage(root).append(grid);
    renderSupportBanner(root);
    summaryGrid(root,[
      ['待开票订单',`${billableOrders.length} 笔`,'已支付且尚未提交有效开票申请'],
      ['历史开票申请',`${invoicesList.length} 条`,`已开具 ${issuedCount} 张`],
      ['常用发票抬头',`${titles.length} 组`,'服务端持久化存储 · 一键带入'],
      ['开票服务状态',data.capabilities?.invoice?'电子发票通道已连接':'本地登记保留模式','独立于原生任务用量']
    ]);
    if(billableOrders.length||paidOrders.length){
      const quick=box('待开票订单快捷列表');
      table(quick,['订单编号','实付金额','购买额度','状态','操作'],billableOrders.slice(0,5).map(o=>[
        o.id,
        formatMinorAmount(o.amount_minor,o.currency),
        `${o.credits}`,
        labels[o.status]||o.status,
        button('去开发票',()=>switchSubview('invoice-apply',{orderId:o.id}),!writable(),'commerce-btn-primary')
      ]));
      if(paidOrders.length>billableOrders.length){
        quick.append(button('查看全部已支付订单',()=>switchSubview('invoice-orders')));
      }
    }
  }

  function renderInvoiceApply(t,s){
    renderInvoiceSegmentCard();
    const applyBox=box('申请开具电子发票',root,'commerce-card','commerce-invoice-center');
    applyBox.append(el('p',msg("ui.invoices_come_from_an_invoicing_service_and_are_separate"),'hint'));
    const paidOrders=(data.orders||[]).filter(o=>o.status==='paid');
    if(!paidOrders.length){
      const empty=el('div',null,'commerce-empty-guide');
      empty.append(
        el('strong','当前暂无已支付的可开票订单'),
        el('p','完成套餐订阅或信用充值支付后，即可返回此处申请开具电子发票。'),
        button('前往我的钱包查看套餐',()=>switchSubview('wallet'),false,'commerce-btn-primary')
      );
      applyBox.append(empty);
    }
    const currentType=getDraft('invoice-type','enterprise_normal');
    const typeBar=el('div',null,'commerce-actions');
    for(const [code,label]of INVOICE_TYPES){
      const b=button(label,()=>{
        setDraft('invoice-type',code);
        if(code==='personal'&&!getDraft('invoice-tax'))setDraft('invoice-tax','PERSONAL');
        if(code!=='personal'&&getDraft('invoice-tax')==='PERSONAL')setDraft('invoice-tax','');
        render();
      });
      b.setAttribute('aria-pressed',String(currentType===code));
      typeBar.append(b);
    }
    applyBox.append(typeBar);

    const searchRow=el('div',null,'commerce-actions');
    const searchInput=input(searchRow,'搜索已存抬头或税号','title-search','search');
    searchRow.append(button('检索抬头',async()=>{await loadServerTitles(searchInput.value);if(same(t,s))render();}));
    applyBox.append(searchRow);
    const titles=mergedTitles().filter(item=>{
      const q=searchInput.value.trim().toLowerCase();
      return !q||String(item.title||'').toLowerCase().includes(q)||String(item.tax_id||'').toLowerCase().includes(q);
    });
    if(titles.length){
      const chips=el('div',null,'commerce-actions');
      chips.append(el('small','一键带入常用抬头：'));
      for(const item of titles.slice(0,6)){
        chips.append(button(`${item.title}${item.is_default?'（默认）':''}`,()=>switchSubview('invoice-apply',{titleObj:item})));
      }
      applyBox.append(chips);
    }

    const form=el('div');
    const orderSelect=el('select');
    orderSelect.append(localizedOption('',msg("ui.select_a_paid_order")));
    for(const order of paidOrders){
      const existing=invoiceStatusForOrder(order.id);
      const suffix=existing?`（已提交：${labels[existing.status]||existing.status}）`:'（待开票）';
      orderSelect.append(localizedOption(order.id,`${order.id} · ${formatMinorAmount(order.amount_minor,order.currency)} ${suffix}`));
    }
    orderSelect.value=getDraft('invoice-order-id',paidOrders.find(o=>!invoiceStatusForOrder(o.id))?.id||'');
    orderSelect.addEventListener('change',()=>setDraft('invoice-order-id',orderSelect.value));
    field(form,msg("ui.order_for_this_invoice"),orderSelect);

    const title=input(form,'发票抬头','invoice-title');
    const tax=input(form,'税号','invoice-tax','text',currentType==='personal'?'PERSONAL':'');
    const taxHint=el('p',null,'hint commerce-tax-hint');
    const updateTaxHint=()=>{
      const check=validateInvoiceTaxId(tax.value,currentType);
      setText(taxHint,check.hint);
      taxHint.dataset.valid=String(check.valid);
    };
    tax.addEventListener('input',updateTaxHint);
    updateTaxHint();
    if(currentType==='personal')tax.readOnly=true;
    form.append(taxHint);

    const email=input(form,'接收邮箱','invoice-email','email');
    const invoiceScope=el('select');
    invoiceScope.append(localizedOption('',msg("ui.my_orders")));
    if(data.workspace?.workspace_id)invoiceScope.append(localizedOption(data.workspace.workspace_id,data.workspace.workspace_name));
    invoiceScope.value=getDraft('invoice-scope','');
    invoiceScope.addEventListener('change',()=>setDraft('invoice-scope',invoiceScope.value));
    field(form,msg("ui.invoice_ownership"),invoiceScope);

    const saveAsTemplate=el('input');saveAsTemplate.type='checkbox';saveAsTemplate.checked=getDraft('save-title-template',false)===true;
    saveAsTemplate.addEventListener('change',()=>setDraft('save-title-template',saveAsTemplate.checked));
    field(form,'同时保存至常用发票抬头',saveAsTemplate);

    form.append(button(msg("ui.save_invoice_request"),async()=>{
      const normalizedTax=currentType==='personal'?'PERSONAL':tax.value.trim().toUpperCase();
      if(saveAsTemplate.checked&&title.value.trim()&&normalizedTax){
        await savePersistentInvoiceTitle({
          id:null,
          invoice_type:currentType,
          title:title.value.trim(),
          tax_id:normalizedTax,
          email:email.value.trim()||null,
          bank_name:null,
          bank_account:null,
          address_phone:null,
          is_default:mergedTitles().length===0
        },{silent:true});
      }
      await write('/invoices',{
        order_id:orderSelect.value,
        title:title.value,
        tax_id:normalizedTax,
        email:email.value,
        ...(invoiceScope.value?{workspace_id:invoiceScope.value}:{})
      });
    },!writable(),'commerce-btn-primary'));
    applyBox.append(form);
    renderSupportBanner(root);
  }

  function renderInvoiceOrders(){
    renderInvoiceSegmentCard();
    const ordersBox=box('可开票与已支付订单');
    const filterBar=el('div',null,'commerce-actions');
    for(const [code,label]of [['all','全部已付订单'],['billable','待开票'],['pending','开票处理中'],['issued','已开具']]){
      const b=button(label,()=>{orderFilter=code;render();});
      b.setAttribute('aria-pressed',String(orderFilter===code));
      filterBar.append(b);
    }
    ordersBox.append(filterBar);
    const paidOrders=(data.orders||[]).filter(o=>o.status==='paid').filter(o=>{
      const inv=invoiceStatusForOrder(o.id);
      if(orderFilter==='billable')return !inv;
      if(orderFilter==='issued')return inv?.status==='issued';
      if(orderFilter==='pending')return Boolean(inv&&inv.status!=='issued');
      return true;
    });
    table(ordersBox,['订单编号','金额','购买信用额度','支付时间','开票状态','操作'],paidOrders.map(o=>{
      const inv=invoiceStatusForOrder(o.id);
      const statusText=inv?(labels[inv.status]||inv.status):'待开票';
      const actionNode=inv
        ?button('查看发票记录',()=>switchSubview('invoice-history'))
        :button('去开发票',()=>switchSubview('invoice-apply',{orderId:o.id}),!writable(),'commerce-btn-primary');
      return [o.id,formatMinorAmount(o.amount_minor,o.currency),String(o.credits),o.paid_at?new Date(o.paid_at).toLocaleString():'—',statusText,actionNode];
    }));
    renderSupportBanner(root);
  }

  function renderInvoiceHistory(t,s){
    renderInvoiceSegmentCard();
    const histBox=box('历史发票记录');
    const filterBar=el('div',null,'commerce-actions');
    for(const [code,label]of [['all','全部状态'],['issued','已开具'],['pending','待处理 / 待核对'],['unconfigured','服务未配置'],['failed','处理失败']]){
      const b=button(label,()=>{historyFilter=code;render();});
      b.setAttribute('aria-pressed',String(historyFilter===code));
      filterBar.append(b);
    }
    histBox.append(filterBar);
    const filtered=(data.invoices||[]).filter(inv=>{
      if(historyFilter==='all')return true;
      if(historyFilter==='pending')return ['created','pending','submission_unknown'].includes(inv.status);
      return inv.status===historyFilter;
    });
    table(histBox,['发票申请编号','关联订单','发票抬头','状态','申请时间','操作'],filtered.map(row=>{
      const actions=el('div',null,'commerce-actions');
      actions.append(button(msg("ui.check_original_request"),()=>write('/invoices/refresh',{invoice_id:row.id}),!data.capabilities?.invoice||!writable()));
      if(row.status==='issued'){
        actions.append(button(msg("ui.download_issued_invoice"),()=>downloadInvoicePdf(row,t,s)));
      }
      return [row.id,row.order_id,row.title,labels[row.status]||row.status,row.created_at?new Date(row.created_at).toLocaleString():'—',actions];
    }));
    renderSupportBanner(root);
  }

  function renderInvoiceTitles(){
    renderInvoiceSegmentCard();
    const titleBox=box('常用发票抬头管理',root,'commerce-card','commerce-invoice-titles-card');
    const form=el('div',null,'commerce-title-form');
    const typeSelect=el('select');
    for(const [code,label]of INVOICE_TYPES)typeSelect.append(localizedOption(code,label));
    typeSelect.value=getDraft('tpl-type','enterprise_normal');
    typeSelect.addEventListener('change',()=>{
      setDraft('tpl-type',typeSelect.value);
      if(typeSelect.value==='personal')setDraft('tpl-tax','PERSONAL');
      else if(getDraft('tpl-tax')==='PERSONAL')setDraft('tpl-tax','');
      render();
    });
    field(form,'抬头类型',typeSelect);
    const nameInput=input(form,'常用抬头名称','tpl-title');
    const taxInput=input(form,'常用税号 / 信用代码','tpl-tax','text',typeSelect.value==='personal'?'PERSONAL':'');
    if(typeSelect.value==='personal')taxInput.readOnly=true;
    const emailInput=input(form,'默认接收邮箱','tpl-email','email');
    const bankInput=input(form,'开户行（专票选填）','tpl-bank');
    const bankAccInput=input(form,'银行账号脱敏摘要（选填）','tpl-bank-acc');
    const addrPhoneInput=input(form,'注册地址与电话（选填）','tpl-addr-phone');
    const defCheck=el('input');defCheck.type='checkbox';defCheck.checked=getDraft('tpl-default',true)!==false;
    defCheck.addEventListener('change',()=>setDraft('tpl-default',defCheck.checked));
    field(form,'设为默认发票抬头',defCheck);
    form.append(button('＋ 保存常用抬头',async()=>{
      const titleVal=nameInput.value.trim();
      const taxVal=typeSelect.value==='personal'?'PERSONAL':taxInput.value.trim().toUpperCase();
      if(!titleVal)throw new Error('请填写常用抬头名称');
      const check=validateInvoiceTaxId(taxVal,typeSelect.value);
      if(!check.valid)throw new Error(check.hint);
      await savePersistentInvoiceTitle({
        id:null,
        invoice_type:typeSelect.value,
        title:titleVal,
        tax_id:check.normalized,
        email:emailInput.value.trim()||null,
        bank_name:bankInput.value.trim()||null,
        bank_account:bankAccInput.value.trim()||null,
        address_phone:addrPhoneInput.value.trim()||null,
        is_default:defCheck.checked||mergedTitles().length===0
      });
      setDraft('tpl-title','');
      setDraft('tpl-tax',typeSelect.value==='personal'?'PERSONAL':'');
      setDraft('tpl-bank','');
      setDraft('tpl-bank-acc','');
      setDraft('tpl-addr-phone','');
      render();
    },!writable(),'commerce-btn-primary'));
    titleBox.append(form);

    const rows=mergedTitles();
    table(titleBox,['发票抬头','税号 / 社会信用代码','抬头类型','接收邮箱','默认','操作'],rows.map(item=>{
      const itemType=item.invoice_type||item.title_type||(item.tax_id==='PERSONAL'?'personal':'enterprise_normal');
      const actions=el('div',null,'commerce-actions');
      actions.append(button('带入去开票',()=>switchSubview('invoice-apply',{titleObj:{...item,invoice_type:itemType}})));
      if(!item.is_default){
        actions.append(button('设为默认',()=>savePersistentInvoiceTitle({
          id:item.id||null,
          invoice_type:itemType,
          title:item.title,
          tax_id:item.tax_id,
          email:item.email||null,
          bank_name:item.bank_name||null,
          bank_account:item.bank_account||item.bank_account_masked||null,
          address_phone:item.address_phone||item.billing_address_phone||null,
          is_default:true
        }),!writable()));
      }
      actions.append(button('移除',()=>deletePersistentInvoiceTitle(item),!writable()));
      const typeLabel=INVOICE_TYPES.find(([k])=>k===itemType)?.[1]||(itemType==='personal'?'个人 / 非企业单位':'企业抬头');
      return [item.title,item.tax_id,typeLabel,item.email||'—',item.is_default?'默认抬头':'—',actions];
    }));
    renderSupportBanner(root);
  }

  function renderOrganizationQuota(s){
    const caps=data.capabilities||{};
    if(!caps.manage){
      if(subview==='studio-quota'){
        const guardCard=box('工作室与子工作室额度调配（需管理员权限）',root,'commerce-card','commerce-studio-quota-card');
        guardCard.append(
          el('p','当前账号在所选空间为成员角色，工作室与子工作室额度划拨仅对工作室管理员开放。','hint'),
          button('返回我的钱包',()=>switchSubview('wallet'),false,'commerce-btn-primary')
        );
      }
      return;
    }
    if(data.workspace?.workspace_id&&(data.workspace.projects||[]).length&&s.scopeKind==='project'){
      const organization=box(data.workspace.workspace_name+' · 组织额度分配',root,'commerce-card','commerce-studio-quota-card');
      const orgLinks=el('div',null,'commerce-actions');
      orgLinks.append(button('工作室成员与角色管理 →',()=>ctx.navigate?.('access',null,s.project)));
      organization.append(orgLinks);
      const source=el('select'),destination=el('select');
      for(const row of (data.buckets||[]).filter(row=>row.available>0))source.append(localizedOption(row.id,msg("ui.value0_available_value1",{value0:labels[row.kind]||row.kind,value1:row.available})));
      for(const row of (data.workspace.projects||[]).filter(row=>row.id!==s.project))destination.append(localizedOption(row.id,joinMessages([row.workspace_name," / ",row.name])));
      if(source.options.length)source.value=source.options[0].value;
      if(destination.options.length)destination.value=destination.options[0].value;
      field(organization,msg("ui.allocate_source_credits"),source);
      field(organization,msg("ui.target_studio_project"),destination);
      const amount=input(organization,'分配信用数','workspace-credits','number');
      organization.append(button(msg("ui.allocate_to_target_project_pool"),()=>{
        const project=data.workspace.projects.find(row=>row.id===destination.value);
        if(!project)throw new Error('请选择目标项目');
        return write('/workspace-transfers',{bucket_id:source.value,target_project_id:project.id,target_revision:project.revision,credits:Number(amount.value)});
      },!writable()||!destination.options.length));
      table(organization,['时间','来源项目','目标项目','信用','动作'],(data.workspace.transfers||[]).map(row=>[new Date(row.created_at).toLocaleString(),row.source_project_name,row.target_project_name,row.credits,row.reclaim_of_id?'退回未用额度':'分配']));
      for(const row of (data.workspace.transfers||[]).filter(row=>row.target_project_id===s.project&&!row.reclaim_of_id)){
        const bucket=(data.buckets||[]).find(item=>item.id===row.target_bucket_id),project=(data.workspace.projects||[]).find(item=>item.id===row.project_id);
        if(!bucket||bucket.available<=0||!project)continue;
        const line=el('div'),reclaimAmount=input(line,'退回 '+row.source_project_name+' 的未用额度','reclaim:'+row.id,'number');
        reclaimAmount.max=bucket.available;
        line.append(button(msg("ui.return_to_the_original_project_s_credit_bucket"),()=>write('/workspace-transfers',{bucket_id:bucket.id,target_project_id:project.id,target_revision:project.revision,credits:Number(reclaimAmount.value),reclaim_transfer_id:row.id}),!writable()));
        organization.append(line);
      }
    }
    const memberBox=box('工作室成员额度分配与回收',root,'commerce-card',s.scopeKind!=='project'?'commerce-studio-quota-card':null);
    const bucket=el('select');
    bucket.append(localizedOption('',msg("ui.select_an_available_allowance_bucket")));
    for(const b of (data.buckets||[]).filter(b=>b.available>0))bucket.append(localizedOption(b.id,joinMessages(["",labels[b.kind]||b.kind," · ",b.owner_actor||msg("ui.project_pool")," · ",b.available,""])));
    field(memberBox,msg("ui.source_credit_bucket"),bucket);
    const target=el('select');
    target.append(localizedOption('',msg("ui.project_pool")));
    for(const member of data.workspace?.members||[])target.append(localizedOption(member.actor,member.display_name));
    field(memberBox,msg("ui.target_member"),target);
    const amount=input(memberBox,'分配 / 回收信用数','allocation-amount','number');
    const actions=el('div',null,'commerce-actions');
    actions.append(
      button(msg("ui.allocate_unused_allowance"),()=>write('/allocations',{bucket_id:bucket.value,target_actor:target.value||null,credits:Number(amount.value),reclaim:false}),!writable()),
      button(msg("ui.return_a_member_s_unused_allowance_to_the_project"),()=>write('/allocations',{bucket_id:bucket.value,target_actor:null,credits:Number(amount.value),reclaim:true}),!writable())
    );
    memberBox.append(actions);
  }

  function closeDiffDialog(){
    if(!diffDialogState)return;
    const old=diffDialogState;
    diffDialogState=null;
    old.dialog.close?.();
    old.dialog.remove();
  }

  async function openDryRunDiffDialog({kind,draft,onConflictKeepDraft}){
    const t=ticket,s=scope;
    if(!writable())throw new Error('当前会话只读');
    const isPlan=kind==='plan';
    const doc=isPlan?buildCanonicalPlanDocument(draft):buildCanonicalCampaignDocument(draft);
    const clientErr=isPlan?validatePlanDraftClient(doc):validateCampaignDraftClient(doc);
    if(clientErr)throw new Error(clientErr);

    const previewPath=isPlan?'/plans/preview-diff':'/campaigns/preview-diff';
    const commitPath=isPlan?'/plans':'/campaigns';
    const previewBody=isPlan
      ?{payload:{base_version_id:draft.base_version_id||null,metering_enabled:Boolean(draft.metering_enabled),document:doc}}
      :{payload:doc};

    let preview;
    try{
      preview=await ctx.api(adminCommerceUrl(s,previewPath),{
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
        body:JSON.stringify(previewBody)
      });
    }catch(err){
      if(err.status===409||err.code==='commerce_plan_conflict'||err.code==='revision_conflict'){
        if(err.details?.current_revision!=null){
          if(s.scopeKind==='project')recordRevision(err.details.current_revision,s);
          else scopeRevisions.set('platform:commerce',err.details.current_revision);
        }
        if(isPlan&&err.details?.latest_version_id)draft.base_version_id=err.details.latest_version_id;
        onConflictKeepDraft?.(err);
      }
      throw err;
    }
    if(!same(t,s))return;

    closeDiffDialog();
    const dialog=el('dialog',null,'commerce-diff-dialog');
    setComp(dialog,'commerce-dry-run-diff-dialog');
    bindAttribute(dialog,'aria-label',isPlan?'套餐变更差异预检确认':'营销活动变更差异预检确认');

    const head=el('header',null,'commerce-diff-head');
    head.append(
      el('h2',isPlan?`套餐变更差异预检 · ${doc.title} (${doc.plan_key})`:`活动发布预检 · ${doc.title} (${doc.code})`),
      button('关闭预检',closeDiffDialog)
    );
    dialog.append(head);

    const meta=el('p',isPlan
      ?`基线版本：${preview?.base_version_id||'新建首版'} → 目标版本 v${preview?.next_version_number??1} · Diff 摘要：${preview?.diff_sha256||'—'}`
      :`活动代码：${doc.code} · 赠送信用：${doc.credits} · Diff 摘要：${preview?.diff_sha256||'—'}`,'hint');
    dialog.append(meta);

    const fieldDiffs=Array.isArray(preview?.field_diffs)?preview.field_diffs:[];
    const fieldSection=el('section',null,'commerce-diff-section');
    fieldSection.append(el('h3',`字段变更明细（${fieldDiffs.length} 项）`));
    table(fieldSection,['字段','变更前','变更后'],fieldDiffs.map(d=>[
      d.label?`${d.label} (${d.field})`:d.field,
      d.before===undefined||d.before===null?'—':JSON.stringify(d.before),
      d.after===undefined||d.after===null?'—':JSON.stringify(d.after)
    ]));
    dialog.append(fieldSection);

    if(isPlan){
      const rDiff=preview?.rate_diffs||{};
      const rateRows=[
        ...(rDiff.added||[]).map(r=>['新增 (added)',r.model_name||r.model_id,r.unit,'—',String(r.credits_per_unit)]),
        ...(rDiff.changed||[]).map(r=>['修改 (changed)',r.model_name||r.model_id,r.unit,String(r.before_credits_per_unit??r.before??'—'),String(r.credits_per_unit??r.after??'—')]),
        ...(rDiff.removed||[]).map(r=>['删除 (removed)',r.model_name||r.model_id,r.unit,String(r.credits_per_unit??'—'),'已移除'])
      ];
      const rateSection=el('section',null,'commerce-diff-section');
      rateSection.append(el('h3',`费率矩阵变更明细（新增 ${(rDiff.added||[]).length} · 修改 ${(rDiff.changed||[]).length} · 删除 ${(rDiff.removed||[]).length}）`));
      table(rateSection,['变更类型','模型','计量单位','原单价','新单价'],rateRows);
      dialog.append(rateSection);
    }

    const confirmWrap=el('label',null,'commerce-diff-confirm');
    const confirmCheck=el('input');confirmCheck.type='checkbox';
    bindAttribute(confirmCheck,'aria-label','我已逐项核对计费与封存影响');
    confirmWrap.append(confirmCheck,el('span','我已逐项核对上述计费影响，知晓发布后由数据库触发器永久不可变封存'));
    dialog.append(confirmWrap);

    const statusMsg=el('p',null,'commerce-diff-error');statusMsg.hidden=true;
    dialog.append(statusMsg);

    let commitIdempotencyKey=crypto.randomUUID();
    const actions=el('div',null,'commerce-actions');
    const commitBtn=button(isPlan?'确认封存发布新套餐版本':'确认封存发布营销活动',async()=>{
      if(!confirmCheck.checked){
        setText(statusMsg,'必须先勾选人工确认框（confirmed = true）才允许正式发布');
        statusMsg.hidden=false;
        return;
      }
      statusMsg.hidden=true;
      const expectedRev=preview?.current_revision??currentAdminRevision(s);
      const commitPayload=isPlan
        ?{
          document:doc,
          base_version_id:preview?.base_version_id!==undefined?preview.base_version_id:(draft.base_version_id||null),
          metering_enabled:Boolean(draft.metering_enabled),
          diff_sha256:preview?.diff_sha256||'',
          confirmed:true
        }
        :{
          ...doc,
          diff_sha256:preview?.diff_sha256||'',
          confirmed:true
        };
      try{
        const res=await ctx.api(adminCommerceUrl(s,commitPath),{
          method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},
          body:JSON.stringify({
            payload:commitPayload,
            expected_revision:expectedRev,
            idempotency_key:commitIdempotencyKey
          })
        });
        if(!same(t,s))return;
        if(res?.revision!=null){
          if(s.scopeKind==='project')recordRevision(res.revision,s);
          else scopeRevisions.set('platform:commerce',res.revision);
        }
        closeDiffDialog();
        ctx.notice(isPlan?`套餐新版本 v${res?.version??preview?.next_version_number??''} 已封存发布`:'营销活动已封存发布');
        await load({...s,subview});
      }catch(err){
        if(err.status===409||err.code==='commerce_plan_conflict'||err.code==='revision_conflict'){
          commitIdempotencyKey=crypto.randomUUID();
          if(err.details?.current_revision!=null){
            if(s.scopeKind==='project')recordRevision(err.details.current_revision,s);
            else scopeRevisions.set('platform:commerce',err.details.current_revision);
          }
          if(isPlan&&err.details?.latest_version_id)draft.base_version_id=err.details.latest_version_id;
          setText(statusMsg,`并发冲突（409 ${err.code||'conflict'}）：${err.message}。您填写的全部 16 项字段与费率矩阵草稿已 100% 保留，请点击“保留草稿并重新预检基线”。`);
          statusMsg.hidden=false;
          onConflictKeepDraft?.(err);
          return;
        }
        setText(statusMsg,err.message||String(err));
        statusMsg.hidden=false;
      }
    },!writable(),'commerce-btn-primary');

    const retryPreviewBtn=button('保留草稿并重新预检基线',async()=>openDryRunDiffDialog({kind,draft,onConflictKeepDraft}));
    actions.append(commitBtn,retryPreviewBtn,button('返回继续修改草稿',closeDiffDialog));
    dialog.append(actions);

    root.append(dialog);
    diffDialogState={dialog};
    if(dialog.showModal)dialog.showModal();
    else dialog.setAttribute('open','');
  }

  function renderAdminGovernanceSection(){
    const catalogPlans=platformData?.plans?.length?platformData.plans:(data.plans||[]);
    const providerModels=platformData?.provider_models||data.provider_models||[];
    const admin=box('管理员显式业务配置（结构化契约与 Dry-Run 封存发布）');
    const details=el('details');
    details.open=getDraft('admin-details-open',false)===true;
    details.addEventListener('toggle',()=>{setDraft('admin-details-open',details.open);});
    details.append(el('summary',msg("ui.price_versions_campaigns_and_credit_allocation")));

    // 1. 16-field Structured Plan Editor + 1..200 Rate Matrix (ZERO editable raw JSON textarea)
    const planCard=el('section',null,'commerce-admin-subcard');
    setComp(planCard,'commerce-admin-plan-editor');
    planCard.append(
      el('h3','套餐与模型费率矩阵编辑器（16 字段强类型 + Dry-Run 对比）'),
      el('p','已禁用手写裸 JSON 文本框：所有套餐版本经 Dry-Run 差异核对并勾选确认后，由 PostgreSQL 触发器不可变封存。','hint')
    );

    const planDraft=getAdminDraft('plan-struct',()=>defaultPlanDraft(catalogPlans,providerModels));
    const conflictBanner=el('p',null,'commerce-diff-error');
    conflictBanner.hidden=!planDraft._conflictMessage;
    if(planDraft._conflictMessage)setText(conflictBanner,planDraft._conflictMessage);
    planCard.append(conflictBanner);

    const jsonPreview=el('pre',null,'commerce-readonly-json');
    const refreshPlanPreview=()=>{
      setText(jsonPreview,JSON.stringify(buildCanonicalPlanDocument(planDraft),null,2));
    };

    const baseRow=el('div',null,'commerce-plan-grid');
    const baseSelect=el('select');
    baseSelect.append(localizedOption('',msg("ui.new_plan_version_no_previous_version")));
    for(const p of catalogPlans)baseSelect.append(localizedOption(p.id,joinMessages([p.document.title," v",p.version])));
    baseSelect.value=planDraft.base_version_id||'';
    baseSelect.addEventListener('change',()=>{planDraft.base_version_id=baseSelect.value;});
    field(baseRow,msg("ui.price_version_being_replaced"),baseSelect);

    const loadBaseBtn=button('载入所选基线字段',()=>{
      const picked=catalogPlans.find(p=>p.id===baseSelect.value);
      if(!picked?.document)return;
      const next=defaultPlanDraft([picked],providerModels);
      Object.assign(planDraft,next,{base_version_id:picked.id,_conflictMessage:''});
      setAdminDraft('plan-struct',planDraft);
      setDraft('admin-details-open',true);
      render();
    });
    const meteringCheck=el('input');meteringCheck.type='checkbox';meteringCheck.checked=Boolean(planDraft.metering_enabled);
    meteringCheck.addEventListener('change',()=>{planDraft.metering_enabled=meteringCheck.checked;});
    field(baseRow,msg("ui.enable_commercial_metering_later_runs_require_a_fixed_credit"),meteringCheck);
    baseRow.append(loadBaseBtn);
    planCard.append(baseRow);

    const grid16=el('div',null,'commerce-plan-grid');
    const bindText=(label,prop,type='text')=>{
      const inp=el('input');inp.type=type;inp.value=String(planDraft[prop]??'');
      inp.addEventListener('input',()=>{planDraft[prop]=inp.value;refreshPlanPreview();});
      return field(grid16,label,inp);
    };
    const bindSelect=(label,prop,opts)=>{
      const sel=el('select');
      for(const [val,txt]of opts)sel.append(localizedOption(val,txt));
      sel.value=String(planDraft[prop]??opts[0][0]);
      sel.addEventListener('change',()=>{planDraft[prop]=sel.value;refreshPlanPreview();});
      return field(grid16,label,sel);
    };
    const bindBool=(label,prop)=>{
      const chk=el('input');chk.type='checkbox';chk.checked=Boolean(planDraft[prop]);
      chk.addEventListener('change',()=>{planDraft[prop]=chk.checked;refreshPlanPreview();});
      return field(grid16,label,chk);
    };

    bindText('套餐唯一标识 (plan_key)','plan_key');
    bindText('套餐标题 (title)','title');
    bindSelect('结算币种 (currency)','currency',[['CNY','CNY (人民币)'],['USD','USD (美元)']]);
    bindText('实付金额分值 (amount_minor)','amount_minor','number');
    bindText('发放商业信用 (credits)','credits','number');
    bindSelect('入账桶类型 (bucket_kind)','bucket_kind',BUCKET_KINDS);
    bindText('有效天数 (validity_days)','validity_days','number');
    bindText('收银台有效分钟 (checkout_minutes)','checkout_minutes','number');
    bindText('允许用途列表 (purposes)','purposes');
    bindText('最大并发任务数 (max_concurrent_jobs)','max_concurrent_jobs','number');
    bindText('席位上限 (seat_limit)','seat_limit','number');
    bindSelect('退款策略 (refund_policy)','refund_policy',REFUND_POLICIES);
    bindSelect('续期策略 (renewal_policy)','renewal_policy',RENEWAL_POLICIES);
    bindBool('允许开具电子发票 (invoice_enabled)','invoice_enabled');
    bindBool('成片强制附加水印 (watermark_required)','watermark_required');
    planCard.append(grid16);

    // 16th field: rates matrix (1..200 rows)
    const matrixWrap=el('div',null,'commerce-rate-matrix');
    setComp(matrixWrap,'commerce-rate-matrix-table');
    const renderMatrix=()=>{
      matrixWrap.replaceChildren();
      const headBar=el('div',null,'commerce-actions');
      headBar.append(
        el('strong',`模型费率矩阵（当前 ${planDraft.rates.length} / 200 行，字段 #16 rates）`),
        button('＋ 新增费率行',()=>{
          if(planDraft.rates.length>=200)throw new Error('费率矩阵最多支持 200 行');
          planDraft.rates.push({model_id:providerModels[0]?.id||'',unit:'video_seconds',credits_per_unit:'10'});
          renderMatrix();
          refreshPlanPreview();
        },!writable()||planDraft.rates.length>=200)
      );
      matrixWrap.append(headBar);

      const rows=planDraft.rates.map((rateRow,idx)=>{
        const rowNum=idx+1;
        const modelCell=el('div',null,'commerce-rate-model-cell');
        const modelInp=el('input');modelInp.type='text';modelInp.value=rateRow.model_id||'';
        bindAttribute(modelInp,'aria-label',`费率模型标识 ${rowNum}`);
        modelInp.addEventListener('input',()=>{rateRow.model_id=modelInp.value;refreshPlanPreview();});
        if(providerModels.length){
          const preset=el('select');
          bindAttribute(preset,'aria-label',`已登记模型选择 ${rowNum}`);
          preset.append(localizedOption('','选择已登记模型…'));
          for(const pm of providerModels)preset.append(localizedOption(pm.id,`${pm.name||pm.model_key||pm.id} (${pm.id})`));
          if(providerModels.some(pm=>pm.id===rateRow.model_id))preset.value=rateRow.model_id;
          preset.addEventListener('change',()=>{
            if(preset.value){
              rateRow.model_id=preset.value;
              modelInp.value=preset.value;
              refreshPlanPreview();
            }
          });
          modelCell.append(preset);
        }
        modelCell.append(modelInp);

        const unitSel=el('select');
        bindAttribute(unitSel,'aria-label',`费率计量单位 ${rowNum}`);
        for(const [uVal,uText]of RATE_UNITS)unitSel.append(localizedOption(uVal,uText));
        unitSel.value=rateRow.unit||'video_seconds';
        unitSel.addEventListener('change',()=>{rateRow.unit=unitSel.value;refreshPlanPreview();});

        const priceInp=el('input');priceInp.type='number';priceInp.min='1';priceInp.step='1';priceInp.value=String(rateRow.credits_per_unit??'1');
        bindAttribute(priceInp,'aria-label',`费率信用单价 ${rowNum}`);
        priceInp.addEventListener('input',()=>{rateRow.credits_per_unit=priceInp.value;refreshPlanPreview();});

        const delBtn=button('删除行',()=>{
          if(planDraft.rates.length<=1)return;
          planDraft.rates.splice(idx,1);
          renderMatrix();
          refreshPlanPreview();
        },!writable()||planDraft.rates.length<=1);

        return [String(rowNum),modelCell,unitSel,priceInp,delBtn];
      });
      table(matrixWrap,['#','模型标识 (model_id)','计量单位 (unit)','信用单价 (credits_per_unit)','操作'],rows);
    };
    renderMatrix();
    planCard.append(matrixWrap);

    const previewDetails=el('details',null,'commerce-canonical-preview');
    previewDetails.append(el('summary','查看只读规范化套餐契约 JSON'),jsonPreview);
    refreshPlanPreview();
    planCard.append(previewDetails);

    const planActions=el('div',null,'commerce-actions');
    planActions.append(
      button('预览套餐变更差异 (Dry-Run)',()=>openDryRunDiffDialog({
        kind:'plan',
        draft:planDraft,
        onConflictKeepDraft:err=>{
          planDraft._conflictMessage=`并发版本冲突（409）：${err.message}。全部 16 项字段与 ${planDraft.rates.length} 行费率矩阵草稿已完整保留。`;
          setText(conflictBanner,planDraft._conflictMessage);
          conflictBanner.hidden=false;
        }
      }),!writable(),'commerce-btn-primary')
    );
    planCard.append(planActions);
    details.append(planCard);

    // 2. 9-field Structured Campaign Editor + Dry-Run Diff (ZERO editable raw JSON textarea)
    const campCard=el('section',null,'commerce-admin-subcard');
    setComp(campCard,'commerce-admin-campaign-editor');
    campCard.append(
      el('h3','营销与签到活动编辑器（9 字段强类型 + Dry-Run 对比）'),
      el('p','活动兑换码落库仅存 SHA-256 摘要；勾选每日活动时按 UTC 自然日核算，每日 08:00（北京时间 / 00:00 UTC）刷新。','hint')
    );
    const campDraft=getAdminDraft('campaign-struct',defaultCampaignDraft);
    const campJsonPreview=el('pre',null,'commerce-readonly-json');
    const refreshCampPreview=()=>{
      setText(campJsonPreview,JSON.stringify(buildCanonicalCampaignDocument(campDraft),null,2));
    };
    const grid9=el('div',null,'commerce-plan-grid');
    const bindCampText=(label,prop,type='text')=>{
      const inp=el('input');inp.type=type;inp.value=String(campDraft[prop]??'');
      inp.addEventListener('input',()=>{campDraft[prop]=inp.value;refreshCampPreview();});
      return field(grid9,label,inp);
    };
    bindCampText('活动兑换码 (code)','code');
    bindCampText('活动标题 (title)','title');
    bindCampText('赠送信用数 (credits)','credits','number');
    const campKindSel=el('select');
    for(const [kVal,kTxt]of CAMPAIGN_KINDS)campKindSel.append(localizedOption(kVal,kTxt));
    campKindSel.value=campDraft.kind||'bonus';
    campKindSel.addEventListener('change',()=>{campDraft.kind=campKindSel.value;refreshCampPreview();});
    field(grid9,'额度类型 (kind)',campKindSel);
    bindCampText('活动允许用途 (purposes)','purposes');
    bindCampText('生效时间 UTC (starts_at)','starts_at');
    bindCampText('截止时间 UTC (ends_at)','ends_at');
    bindCampText('入账额度过期时间 UTC (credit_expires_at)','credit_expires_at');
    const dailyCheck=el('input');dailyCheck.type='checkbox';dailyCheck.checked=Boolean(campDraft.daily);
    dailyCheck.addEventListener('change',()=>{campDraft.daily=dailyCheck.checked;refreshCampPreview();});
    field(grid9,'按日重复领取（每日 08:00（北京时间 / 00:00 UTC）刷新）',dailyCheck);
    campCard.append(grid9);

    const campPreviewDetails=el('details',null,'commerce-canonical-preview');
    campPreviewDetails.append(el('summary','查看只读规范化活动契约 JSON'),campJsonPreview);
    refreshCampPreview();
    campCard.append(campPreviewDetails);

    const campActions=el('div',null,'commerce-actions');
    campActions.append(
      button('预览活动变更差异 (Dry-Run)',()=>openDryRunDiffDialog({kind:'campaign',draft:campDraft}),!writable(),'commerce-btn-primary')
    );
    campCard.append(campActions);
    details.append(campCard);

    admin.append(details);
  }

  function render(){
    closeDiffDialog();
    root.replaceChildren();
    root.classList.add('commerce');
    root.dataset.subview=subview;
    setComp(root,'commercial-shell-container');
    const t=ticket,s=scope,caps=data.capabilities||{};

    const topBar=el('header',null,'commerce-topbar');
    setComp(topBar,'commercial-shell-header');
    const titleWrap=el('div');
    titleWrap.append(
      el('h1','会员与钱包'),
      el('p',msg("ui.commercial_credits_use_a_fixed_price_version_task_counts"),'hint')
    );
    topBar.append(titleWrap);
    attachGovNav(topBar);
    root.append(topBar);

    const subnav=el('nav',null,'commerce-subnav');
    setComp(subnav,'commercial-shell-subnav');
    subnav.setAttribute('role','tablist');
    bindAttribute(subnav,'aria-label','会员与钱包二级常驻导航');
    const primaryTabs=[
      ['wallet','我的钱包'],
      ['invoice-overview','电子发票中心'],
      ['studio-quota','工作室额度调配']
    ];
    const subnavButtons=[];
    for(const [id,label]of primaryTabs){
      const active=id==='invoice-overview'?subview.startsWith('invoice-'):subview===id;
      const b=button(label,()=>switchSubview(id));
      b.dataset.subview=id;
      b.setAttribute('role','tab');
      b.setAttribute('aria-selected',String(active));
      b.setAttribute('aria-pressed',String(active));
      subnavButtons.push(b);
      subnav.append(b);
    }
    subnavButtons.forEach((tabBtn,idx)=>tabBtn.addEventListener('keydown',event=>{
      if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
        event.preventDefault?.();
        const nextIdx=(idx+(event.key==='ArrowRight'?1:subnavButtons.length-1))%subnavButtons.length;
        switchSubview(primaryTabs[nextIdx][0]);
        root.querySelector?.(`.commerce-subnav [data-subview="${primaryTabs[nextIdx][0]}"]`)?.focus?.();
      }
    }));
    root.append(subnav);

    stageHost=el('div',null,'commerce-stage');
    setComp(stageHost,'commercial-shell-stage');
    root.append(stageHost);

    renderFundingPoolBar();

    if(subview==='invoice-overview'){renderInvoiceOverview();return;}
    if(subview==='invoice-apply'){renderInvoiceApply(t,s);return;}
    if(subview==='invoice-orders'){renderInvoiceOrders();return;}
    if(subview==='invoice-history'){renderInvoiceHistory(t,s);return;}
    if(subview==='invoice-titles'){renderInvoiceTitles();return;}
    if(subview==='studio-quota'){renderOrganizationQuota(s);return;}

    const bucketsList=data.buckets||[];
    const ordersList=data.orders||[];
    const invoicesList=data.invoices||[];
    const byKind={credit:0,bonus:0,check_in:0,special:0};
    for(const b of bucketsList)byKind[b.kind]=(byKind[b.kind]||0)+(b.available||0);
    const billableCount=ordersList.filter(o=>o.status==='paid'&&!invoiceStatusForOrder(o.id)).length;
    const overviewGrid=summaryGrid(root,[
      ['当前可用积分',data.credit_balance??0,`通用 ${byKind.credit} · 赠送 ${byKind.bonus}`],
      ['签到与专项额度',byKind.check_in+byKind.special,`签到 ${byKind.check_in} · 专项 ${byKind.special}`],
      ['待开票订单',`${billableCount} 笔`,`已开具 ${invoicesList.filter(i=>i.status==='issued').length} 张`],
      ['计费策略状态',data.policy?'固定价格计费已启用':(s.scopeKind==='project'?'未启用商业扣减':'显式资金池独立计费'),caps.payment?'支付收银台已连接':'本地未配置支付通道']
    ]);
    setComp(overviewGrid,'commerce-wallet-overview');

    const status=box('服务状态');
    status.append(el('p',msg("ui.pricing_value0_payment_value1_invoice_value2_commercial_metering_value3",{value0:caps.pricing?msg("ui.configuration_exists"):msg("ui.not_configured"),value1:caps.payment?msg("ui.adapter_connected"):msg("ui.not_configured"),value2:caps.invoice?msg("ui.adapter_connected"):msg("ui.not_configured"),value3:data.policy?msg("ui.enable"):msg("ui.not_enabled")})));
    if(!caps.payment)status.append(el('p',msg("ui.no_default_prices_or_payment_channels_are_installed_locally"),'hint'));
    const portalBar=el('div',null,'commerce-actions');
    portalBar.append(
      button('进入电子发票中心 →',()=>switchSubview('invoice-overview'),false,'commerce-btn-primary'),
      button('vsc-engine API 账单 →',()=>ctx.navigate?.('service-operations','engine',s.project||null))
    );
    if(billableCount>0)portalBar.append(button(`立即开票（${billableCount} 笔待开票）`,()=>switchSubview('invoice-apply')));
    status.append(portalBar);

    const credit=box('商业信用',root,'commerce-card','commerce-redeem-card');
    credit.append(el('p',msg("ui.available_credit_shown_value0_personal_and_project_pools_are",{value0:data.credit_balance??0})));
    table(credit,['类型','归属','可用','到期','状态'],bucketsList.map(b=>[labels[b.kind]||b.kind,actorLabel(b.owner_actor),b.available,b.expires_at?new Date(b.expires_at).toLocaleString():'无到期限制',b.frozen?'订单冻结':b.expired?'已到期':'可用']));
    const redeem=el('div',null,'commerce-actions'),code=input(redeem,'活动兑换码','redeem-code');
    redeem.append(button(msg("ui.redeem_check_in"),()=>write('/redeem',{code:code.value}),!writable()));
    credit.append(redeem);

    if(caps.manage&&(data.workspace?.workspace_id||s.scopeKind==='workspace'))renderOrganizationQuota(s);

    const native=box('原生用量');
    if(data.native_budget?.limits){
      table(native,['单位','已占用','上限','剩余'],Object.keys(data.native_budget.limits).map(unit=>[unit,data.native_budget.used?.[unit]||0,data.native_budget.limits[unit],data.native_budget.remaining?.[unit]]));
      if(!Object.keys(data.native_budget.limits).length)native.append(el('p',msg("ui.no_native_unit_project_limits_are_configured_yet"),'hint'));
    }else{
      native.append(el('p','项目原生单位配额按单项目独立核算（不跨项目混加）；切换到具体项目账本或制作任务中心可查看单项目原生预算。','hint'));
    }

    const plans=box('套餐与版本',root,'commerce-card','commerce-plans-checkout-card');
    for(const plan of data.plans||[]){
      const d=plan.document,p=el('article',null,'commerce-plan');
      p.append(
        el('h3',joinMessages(["",d.title," · v",plan.version,""])),
        el('p',msg("ui.value0_minor_currency_units_value1_value2_credits_value3_days",{value0:d.amount_minor,value1:d.currency,value2:d.credits,value3:d.validity_days})),
        el('p',msg("ui.submission_concurrency_cap_value0_project_seats_value1_renewal_value2",{value0:d.max_concurrent_jobs,value1:d.seat_limit,value2:d.renewal_policy==='manual_from_payment'?msg("ui.purchase_renewal_manually_starts_at_payment"):msg("common.close")})),
        button(msg("ui.create_an_order_for_this_version"),()=>write('/orders',{plan_id:plan.id}),!writable()||!caps.payment)
      );
      if(d.watermark_required)p.append(el('p',msg("ui.attach_a_vsc_watermark_when_downloading_composed_videos_covers"),'hint'));
      plans.append(p);
    }
    if(!(data.plans||[]).length)plans.append(el('p',msg("ui.no_plans_are_configured_historical_website_prices_are_not"),'hint'));

    const orders=box('订单与恢复');
    for(const order of ordersList){
      const card=el('article',null,'commerce-order');
      card.append(el('strong',order.id),el('p',msg("ui.value0_value1_minor_currency_units_value2",{value0:labels[order.status]||order.status,value1:order.amount_minor,value2:order.currency})));
      if(order.renewal_of_order_id)card.append(el('p',msg("ui.renewal_source_value0",{value0:order.renewal_of_order_id})));
      if(order.checkout_url&&order.status==='pending'){const link=el('a',msg("ui.open_configured_checkout"));link.href=order.checkout_url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
      const actions=el('div',null,'commerce-actions');
      actions.append(button(msg("ui.query_original_order"),()=>write('/orders/refresh',{order_id:order.id}),!caps.payment||!writable()));
      if(['created','pending','checkout_unknown'].includes(order.status))actions.append(button(msg("ui.cancel_original_order"),()=>write('/orders/cancel',{order_id:order.id}),!caps.payment||!writable()));
      if(order.status==='paid'){
        actions.append(button(msg("ui.renew_manually_with_the_original_plan_version"),()=>write('/orders/renew',{order_id:order.id}),!caps.payment||!writable()),button(msg("ui.request_a_full_refund_only_when_completely_unused"),()=>write('/orders/refund',{order_id:order.id}),!caps.payment||!writable()));
        if(!invoiceStatusForOrder(order.id))actions.append(button('去开发票',()=>switchSubview('invoice-apply',{orderId:order.id}),!writable()));
      }
      card.append(actions);orders.append(card);
    }
    if(!ordersList.length)orders.append(el('p',msg("ui.no_orders_are_visible_to_this_identity"),'hint'));

    const invoices=box('发票申请与快捷入口');
    invoices.append(el('p',msg("ui.invoices_come_from_an_invoicing_service_and_are_separate"),'hint'));
    const quickNav=el('div',null,'commerce-actions');
    quickNav.append(
      button('电子发票总览',()=>switchSubview('invoice-overview')),
      button('可开票订单',()=>switchSubview('invoice-orders')),
      button('常用发票抬头',()=>switchSubview('invoice-titles'))
    );
    invoices.append(quickNav);
    for(const row of invoicesList){
      const line=el('div',null,'commerce-actions');
      line.append(el('span',joinMessages(["",row.title," · ",labels[row.status]||row.status,""])),button(msg("ui.check_original_request"),()=>write('/invoices/refresh',{invoice_id:row.id}),!caps.invoice||!writable()));
      if(row.status==='issued')line.append(button(msg("ui.download_issued_invoice"),()=>downloadInvoicePdf(row,t,s)));
      invoices.append(line);
    }

    const ledger=box('信用流水与任务对账',root,'commerce-card','usage-commercial-ledger-card');
    const ledgerTools=el('div',null,'commerce-actions');
    const csvLink=el('a','导出对账 CSV（防公式注入）','commerce-csv-link');
    csvLink.href=commerceUrl(s,'/ledger.csv');
    csvLink.setAttribute('download','');
    ledgerTools.append(csvLink);
    ledger.append(ledgerTools);

    table(ledger,['时间','出资资金池','动作','信用变化','消耗归因项目 / 任务','供应商账单状态','任务预留编号'],(data.ledger||[]).map(r=>{
      const billStatus=r.supplier_bill_status==='recorded'&&r.supplier_amount_minor!=null
        ?formatMinorAmount(r.supplier_amount_minor,r.supplier_currency||'CNY')
        :'账单未登记 / 报价未知';
      const attrParts=[r.attribution_project_name||r.attribution_project_id,r.job_id].filter(Boolean);
      return [
        r.created_at?new Date(r.created_at).toLocaleString():'—',
        r.funding_scope_label||r.funding_scope_kind||currentPoolLabel(s),
        r.kind,
        r.delta,
        attrParts.length?attrParts.join(' · '):'—',
        billStatus,
        r.reservation_id||'—'
      ];
    }));
    table(ledger,['原任务','尝试','预留信用','结算信用','状态'],(data.reservations||[]).map(r=>[
      r.job_id,
      r.attempt??1,
      r.bound,
      r.actual??'待供应商用量证据',
      labels[r.status]||r.status
    ]));

    if(caps.platform_admin){
      renderAdminGovernanceSection();
    }
  }

  async function load(value={}){
    loadController?.abort?.();
    const controller=typeof AbortController!=='undefined'?new AbortController():null;
    loadController=controller;
    const signal=controller?.signal;

    scope=normalizeScope(value||{});
    subview=normalizeCommerceSubview(value?.subview);
    if(value?.targetId)setDraft('invoice-order-id',value.targetId);
    const s=scope,t=++ticket;busy=false;platformData=null;serverTitles=[];
    root.replaceChildren(el('p',msg("ui.loading_ledger")));
    if(!session().actor){root.replaceChildren(el('p',msg("ui.sign_in_for_this_operation_financial_and_invoice_information")));return;}
    try{
      const result=await ctx.api(commerceUrl(s),{headers:{'X-CSRF-Token':session().csrf},...(signal?{signal}:{})});
      if(!same(t,s)||signal?.aborted)return;
      data=result;
      if(Array.isArray(result?.invoice_titles))serverTitles=result.invoice_titles;
      if(result?.revision!=null)recordRevision(result.revision,s);
      await Promise.all([
        loadServerTitles('',signal),
        loadPlatformCatalog(signal)
      ]);
      if(!same(t,s)||signal?.aborted)return;
      render();
    }catch(e){
      if(e?.name==='AbortError'||signal?.aborted)return;
      if(same(t,s))root.replaceChildren(el('p',e.message),button(msg("ui.reload"),()=>load(s)));
    }
  }

  return {load,suspend(){loadController?.abort?.();loadController=null;closeDiffDialog();ticket++;scope=null;busy=false;}};
}
