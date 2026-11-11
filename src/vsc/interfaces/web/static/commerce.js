import {msg,joinMessages,setText,bindAttribute,option as localizedOption} from './i18n.js';
// Commercial credits and invoices never substitute for original native usage.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const isDomNode=v=>Boolean(v&&typeof v==='object'&&typeof v.tagName==='string');
const clipWrite=async text=>{const nav=typeof navigator!=='undefined'?navigator:globalThis.navigator;await nav?.clipboard?.writeText?.(text);};
const labels={created:'待创建收银台',checkout_unknown:'收银台结果待核对',pending:'待处理',paid:'已支付',expired:'已过期',cancelled:'已取消',refund_unknown:'退款结果待核对',refunded:'已退款',unconfigured:'服务未配置，申请已保留',submission_unknown:'申请结果待核对',issued:'已开具',failed:'处理失败',reserved:'已预留',settled:'已结算',released:'已释放',credit:'通用信用',bonus:'赠送额度',check_in:'签到额度',special:'专项额度'};
const INVOICE_TYPES=[
  ['enterprise_normal','企业增值税普通发票'],
  ['enterprise_special','企业增值税专用发票'],
  ['personal','个人 / 非企业单位']
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
  if(!normalized)return {valid:false,standard18:false,normalized:'',hint:'请输入 18 位统一社会信用代码（或有效纳税人识别号）。'};
  const standard18=/^[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}$/.test(normalized);
  const valid=standard18||/^[A-Z0-9-]{4,32}$/.test(normalized);
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

export function createCommerce(root,ctx){
  let ticket=0,scope=null,data=null,busy=false,subview='wallet',serverTitles=[],orderFilter='all',historyFilter='all';
  const drafts=new Map(),pending=new Map(),localTitles=new Map();
  const url=(p,s='')=>`/api/v1/projects/${encodeURIComponent(p)}/commerce${s}`;
  const same=(t,s)=>ticket===t&&scope===s;
  const session=()=>ctx.session();
  const writable=()=>Boolean(session().actor&&session().writable);
  const draftKey=key=>`${scope.project}:${session().actor||''}:${key}`;
  const getDraft=(key,fallback='')=>drafts.has(draftKey(key))?drafts.get(draftKey(key)):fallback;
  const setDraft=(key,val)=>{drafts.set(draftKey(key),val);return val;};
  const titleStoreKey=()=>`${scope.project}:${session().actor||''}`;
  const getLocalTitles=()=>localTitles.get(titleStoreKey())||[];
  const setLocalTitles=items=>localTitles.set(titleStoreKey(),items);
  const actorLabel=actor=>{
    if(!actor)return '项目公共池';
    if(actor===session().actor)return `本人 (${actor})`;
    const found=(data?.workspace?.members||[]).find(m=>m.actor===actor);
    return found?`${found.display_name} (${actor})`:actor;
  };

  function mergedTitles(){
    const out=[],seen=new Set();
    for(const item of [...getLocalTitles(),...serverTitles]){
      const key=`${item.title}::${item.tax_id}`;
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
  function box(title,parent=root,cls='commerce-card'){const n=el('section',null,cls);n.append(el('h2',title));parent.append(n);return n;}
  function summaryGrid(parent,items){
    const grid=el('dl',null,'commerce-summary-grid');
    for(const [dt,dd,sub]of items){
      const cell=el('div',null,'commerce-summary-cell');
      cell.append(el('dt',dt),el('dd',String(dd)));
      if(sub)cell.append(el('small',sub));
      grid.append(cell);
    }
    parent.append(grid);
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

  async function loadServerTitles(query=''){
    const t=ticket,s=scope;
    try{
      const q=query?`?q=${encodeURIComponent(query)}`:'';
      const res=await ctx.api(url(s.project,`/invoice-titles${q}`),{headers:{'X-CSRF-Token':session().csrf}});
      if(same(t,s)&&Array.isArray(res?.items))serverTitles=res.items;
    }catch{
      // Older test fixtures without /invoice-titles remain seamlessly functional.
    }
  }

  function switchSubview(next,extra={}){
    subview=normalizeCommerceSubview(next);
    if(extra.orderId)setDraft('invoice-order-id',extra.orderId);
    if(extra.titleObj){
      setDraft('invoice-title',extra.titleObj.title||'');
      setDraft('invoice-tax',extra.titleObj.tax_id||'');
      if(extra.titleObj.email)setDraft('invoice-email',extra.titleObj.email);
      setDraft('invoice-type',extra.titleObj.invoice_type==='personal'?'personal':(extra.titleObj.invoice_type||'enterprise_normal'));
    }
    if(scope)scope.subview=subview;
    render();
  }

  async function write(path,payload){
    const t=ticket,s=scope;
    if(!writable())throw new Error('当前会话只读');
    if(busy)throw new Error('上一操作仍在处理中');
    busy=true;
    const tag=s.project+path+JSON.stringify(payload),identity=pending.get(tag)||{key:crypto.randomUUID(),revision:session().revision};
    pending.set(tag,identity);
    try{
      const result=await ctx.api(url(s.project,path),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload,expected_revision:identity.revision,idempotency_key:identity.key})});
      pending.delete(tag);
      if(same(t,s)){ctx.setRevision(result.revision,s.project);await load({...s,subview});}
      return result;
    }catch(e){
      if(e.status===409)pending.delete(tag);
      throw e;
    }finally{
      if(same(t,s))busy=false;
    }
  }

  function renderSupportBanner(parent){
    const info=data.invoice_summary||{};
    const email=info.support_email||'support@skyproduction.cn';
    const hours=info.service_hours||'周一至周五 10:00-19:00（法定节假日除外）';
    const banner=el('footer',null,'commerce-support-banner');
    const copy=el('div',null,'commerce-support-copy');
    copy.append(
      el('strong','联系客服'),
      el('p',`反馈邮箱：${email}`),
      el('p',`客服时间：${hours}`),
      el('p','支付异常、退款后开票、专票信息补录等情况，可通过邮箱联系客服。')
    );
    banner.append(
      copy,
      button('复制客服邮箱',async()=>{await clipWrite(email);ctx.notice(`已复制客服邮箱：${email}`);})
    );
    parent.append(banner);
  }

  function renderInvoiceSubnav(){
    const nav=el('nav',null,'commerce-subnav');
    bindAttribute(nav,'aria-label','电子发票导航');
    for(const [id,label]of [
      ['invoice-overview','发票总览'],
      ['invoice-apply','申请开票'],
      ['invoice-orders','可开票订单'],
      ['invoice-history','开票历史'],
      ['invoice-titles','常用发票抬头']
    ]){
      const b=button(label,()=>switchSubview(id));
      b.dataset.subview=id;
      b.setAttribute('aria-pressed',String(subview===id));
      nav.append(b);
    }
    root.append(nav);
  }

  function renderInvoiceHeader({showSubnav=true}={}){
    const hero=el('header',null,'commerce-invoice-hero');
    const left=el('div');
    const isPortal=subview==='invoice-overview';
    left.append(
      el('span','我的钱包 / 电子发票','commerce-crumb-path'),
      el('h1',isPortal?'申请开票':'电子发票'),
      el('p',isPortal?'请选择需要办理的开票服务。':'管理可开票订单、历史发票与常用发票抬头','hint')
    );
    const backBtn=button(isPortal?'返回':'← 返回我的钱包',()=>switchSubview('wallet'),'','commerce-back-btn');
    bindAttribute(backBtn,'aria-label','返回我的钱包');
    hero.append(left,backBtn);
    root.append(hero);
    if(showSubnav)renderInvoiceSubnav();
  }

  async function downloadInvoicePdf(row,t,s){
    const response=await fetch(url(s.project,`/invoices/${encodeURIComponent(row.id)}/content`),{credentials:'same-origin',headers:{'X-CSRF-Token':session().csrf}});
    if(!response.ok)throw new Error('发票暂不可下载');
    const blob=await response.blob();
    if(!same(t,s))return;
    const href=URL.createObjectURL(blob),a=el('a');
    a.href=href;a.download='invoice.pdf';a.click();
    setTimeout(()=>URL.revokeObjectURL(href),1000);
  }

  function invoiceStatusForOrder(orderId){
    return data.invoices.find(inv=>inv.order_id===orderId)||null;
  }

  function renderInvoiceOverview(){
    renderInvoiceHeader({showSubnav:false});
    const paidOrders=data.orders.filter(o=>o.status==='paid');
    const billableOrders=paidOrders.filter(o=>!invoiceStatusForOrder(o.id));
    const issuedCount=data.invoices.filter(i=>i.status==='issued').length;
    const titles=mergedTitles();
    const grid=el('section',null,'commerce-portal-grid');
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
        badge:`记录 ${data.invoices.length} 条`,
        desc:'查看开票记录，支持核对状态与下载 PDF 电子发票文件。',
        cta:'查看开票历史',
        onClick:()=>switchSubview('invoice-history')
      },
      {
        glyph:'▤',
        title:'常用发票抬头',
        badge:`抬头 ${titles.length} 组`,
        desc:'维护企业、个人等常用抬头并设置默认项，开票一键带入。',
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
          const email=data.invoice_summary?.support_email||'support@skyproduction.cn';
          await clipWrite(email);
          ctx.notice(`请联系官方财务客服：${email}`);
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
    root.append(grid);
    renderSupportBanner(root);
    renderInvoiceSubnav();
    summaryGrid(root,[
      ['待开票订单',`${billableOrders.length} 笔`,'已支付且尚未提交开票申请'],
      ['历史开票申请',`${data.invoices.length} 条`,`已开具 ${issuedCount} 张`],
      ['常用发票抬头',`${titles.length} 组`,'支持税号检索与一键带入'],
      ['开票服务状态',data.capabilities.invoice?'电子发票通道已连接':'本地登记保留模式','独立于原生任务用量']
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
    renderInvoiceHeader();
    const applyBox=box('申请开具电子发票');
    applyBox.append(el('p',msg("ui.invoices_come_from_an_invoicing_service_and_are_separate"),'hint'));
    const paidOrders=data.orders.filter(o=>o.status==='paid');
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
      return !q||item.title.toLowerCase().includes(q)||String(item.tax_id||'').toLowerCase().includes(q);
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

    const saveAsTemplate=el('input');saveAsTemplate.type='checkbox';saveAsTemplate.checked=getDraft('save-title-template',true)!==false;
    saveAsTemplate.addEventListener('change',()=>setDraft('save-title-template',saveAsTemplate.checked));
    field(form,'同时保存至常用发票抬头',saveAsTemplate);

    form.append(button(msg("ui.save_invoice_request"),async()=>{
      const normalizedTax=currentType==='personal'?(tax.value.trim()||'PERSONAL'):tax.value.trim().toUpperCase();
      if(saveAsTemplate.checked&&title.value.trim()&&normalizedTax){
        const cur=getLocalTitles().filter(x=>!(x.title===title.value.trim()&&x.tax_id===normalizedTax));
        cur.unshift({title:title.value.trim(),tax_id:normalizedTax,email:email.value.trim(),invoice_type:currentType,is_default:cur.length===0});
        setLocalTitles(cur);
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
    renderInvoiceHeader();
    const ordersBox=box('可开票与已支付订单');
    const filterBar=el('div',null,'commerce-actions');
    for(const [code,label]of [['all','全部已付订单'],['billable','待开票'],['pending','开票处理中'],['issued','已开具']]){
      const b=button(label,()=>{orderFilter=code;render();});
      b.setAttribute('aria-pressed',String(orderFilter===code));
      filterBar.append(b);
    }
    ordersBox.append(filterBar);
    const paidOrders=data.orders.filter(o=>o.status==='paid').filter(o=>{
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
    renderInvoiceHeader();
    const histBox=box('历史发票记录');
    const filterBar=el('div',null,'commerce-actions');
    for(const [code,label]of [['all','全部状态'],['issued','已开具'],['pending','待处理 / 待核对'],['unconfigured','服务未配置'],['failed','处理失败']]){
      const b=button(label,()=>{historyFilter=code;render();});
      b.setAttribute('aria-pressed',String(historyFilter===code));
      filterBar.append(b);
    }
    histBox.append(filterBar);
    const filtered=data.invoices.filter(inv=>{
      if(historyFilter==='all')return true;
      if(historyFilter==='pending')return ['created','pending','submission_unknown'].includes(inv.status);
      return inv.status===historyFilter;
    });
    table(histBox,['发票申请编号','关联订单','发票抬头','状态','申请时间','操作'],filtered.map(row=>{
      const actions=el('div',null,'commerce-actions');
      actions.append(button(msg("ui.check_original_request"),()=>write('/invoices/refresh',{invoice_id:row.id}),!data.capabilities.invoice||!writable()));
      if(row.status==='issued'){
        actions.append(button(msg("ui.download_issued_invoice"),()=>downloadInvoicePdf(row,t,s)));
      }
      return [row.id,row.order_id,row.title,labels[row.status]||row.status,row.created_at?new Date(row.created_at).toLocaleString():'—',actions];
    }));
    renderSupportBanner(root);
  }

  function renderInvoiceTitles(){
    renderInvoiceHeader();
    const titleBox=box('常用发票抬头管理');
    const form=el('div',null,'commerce-title-form');
    const typeSelect=el('select');
    for(const [code,label]of INVOICE_TYPES)typeSelect.append(localizedOption(code,label));
    typeSelect.value=getDraft('tpl-type','enterprise_normal');
    typeSelect.addEventListener('change',()=>setDraft('tpl-type',typeSelect.value));
    field(form,'抬头类型',typeSelect);
    const nameInput=input(form,'常用抬头名称','tpl-title');
    const taxInput=input(form,'常用税号 / 信用代码','tpl-tax');
    const emailInput=input(form,'默认接收邮箱','tpl-email','email');
    const defCheck=el('input');defCheck.type='checkbox';defCheck.checked=true;
    field(form,'设为默认发票抬头',defCheck);
    form.append(button('＋ 保存常用抬头',()=>{
      const titleVal=nameInput.value.trim();
      const taxVal=typeSelect.value==='personal'?(taxInput.value.trim()||'PERSONAL'):taxInput.value.trim().toUpperCase();
      if(!titleVal)throw new Error('请填写常用抬头名称');
      const check=validateInvoiceTaxId(taxVal,typeSelect.value);
      if(!check.valid)throw new Error(check.hint);
      const next=getLocalTitles().filter(x=>!(x.title===titleVal&&x.tax_id===check.normalized));
      if(defCheck.checked)for(const item of next)item.is_default=false;
      next.unshift({title:titleVal,tax_id:check.normalized,email:emailInput.value.trim(),invoice_type:typeSelect.value,is_default:defCheck.checked||next.length===0});
      setLocalTitles(next);
      setDraft('tpl-title','');setDraft('tpl-tax','');
      ctx.notice('已保存常用发票抬头');
      render();
    },!writable()));
    titleBox.append(form);

    const rows=mergedTitles();
    table(titleBox,['发票抬头','税号 / 社会信用代码','抬头类型','接收邮箱','默认','操作'],rows.map(item=>{
      const actions=el('div',null,'commerce-actions');
      actions.append(button('带入去开票',()=>switchSubview('invoice-apply',{titleObj:item})));
      if(!item.is_default){
        actions.append(button('设为默认',()=>{
          const cur=getLocalTitles().map(x=>({...x,is_default:false}));
          const found=cur.find(x=>x.title===item.title&&x.tax_id===item.tax_id);
          if(found)found.is_default=true;
          else cur.unshift({...item,is_default:true});
          setLocalTitles(cur);
          render();
        }));
      }
      if(getLocalTitles().some(x=>x.title===item.title&&x.tax_id===item.tax_id)){
        actions.append(button('移除',()=>{
          setLocalTitles(getLocalTitles().filter(x=>!(x.title===item.title&&x.tax_id===item.tax_id)));
          render();
        }));
      }
      const typeLabel=INVOICE_TYPES.find(([k])=>k===item.invoice_type)?.[1]||(item.invoice_type==='personal'?'个人 / 非企业单位':'企业抬头');
      return [item.title,item.tax_id,typeLabel,item.email||'—',item.is_default?'默认抬头':'—',actions];
    }));
    renderSupportBanner(root);
  }

  function renderOrganizationQuota(s){
    const caps=data.capabilities;
    if(!caps.manage){
      if(subview==='studio-quota'){
        const guardCard=box('工作室与子工作室额度调配（需管理员权限）');
        guardCard.append(
          el('p','当前账号在所选空间为成员角色，工作室与子工作室额度划拨仅对工作室管理员开放。','hint'),
          button('返回我的钱包',()=>switchSubview('wallet'),false,'commerce-btn-primary')
        );
      }
      return;
    }
    if(data.workspace?.workspace_id){
      const organization=box(data.workspace.workspace_name+' · 组织额度分配');
      const orgLinks=el('div',null,'commerce-actions');
      orgLinks.append(button('工作室成员与角色管理 →',()=>ctx.navigate?.('access',null,s.project)));
      organization.append(orgLinks);
      const source=el('select'),destination=el('select');
      for(const row of data.buckets.filter(row=>row.available>0))source.append(localizedOption(row.id,msg("ui.value0_available_value1",{value0:labels[row.kind]||row.kind,value1:row.available})));
      for(const row of data.workspace.projects.filter(row=>row.id!==s.project))destination.append(localizedOption(row.id,joinMessages([row.workspace_name," / ",row.name])));
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
      table(organization,['时间','来源项目','目标项目','信用','动作'],data.workspace.transfers.map(row=>[new Date(row.created_at).toLocaleString(),row.source_project_name,row.target_project_name,row.credits,row.reclaim_of_id?'退回未用额度':'分配']));
      for(const row of data.workspace.transfers.filter(row=>row.target_project_id===s.project&&!row.reclaim_of_id)){
        const bucket=data.buckets.find(item=>item.id===row.target_bucket_id),project=data.workspace.projects.find(item=>item.id===row.project_id);
        if(!bucket||bucket.available<=0||!project)continue;
        const line=el('div'),reclaimAmount=input(line,'退回 '+row.source_project_name+' 的未用额度','reclaim:'+row.id,'number');
        reclaimAmount.max=bucket.available;
        line.append(button(msg("ui.return_to_the_original_project_s_credit_bucket"),()=>write('/workspace-transfers',{bucket_id:bucket.id,target_project_id:project.id,target_revision:project.revision,credits:Number(reclaimAmount.value),reclaim_transfer_id:row.id}),!writable()));
        organization.append(line);
      }
    }
    const memberBox=box('工作室成员额度分配与回收');
    const bucket=el('select');
    bucket.append(localizedOption('',msg("ui.select_an_available_allowance_bucket")));
    for(const b of data.buckets.filter(b=>b.available>0))bucket.append(localizedOption(b.id,joinMessages(["",labels[b.kind]," · ",b.owner_actor||msg("ui.project_pool")," · ",b.available,""])));
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

  function render(){
    root.replaceChildren();
    root.classList.add('commerce');
    root.dataset.subview=subview;
    const t=ticket,s=scope,caps=data.capabilities;

    if(subview==='invoice-overview'){renderInvoiceOverview();return;}
    if(subview==='invoice-apply'){renderInvoiceApply(t,s);return;}
    if(subview==='invoice-orders'){renderInvoiceOrders();return;}
    if(subview==='invoice-history'){renderInvoiceHistory(t,s);return;}
    if(subview==='invoice-titles'){renderInvoiceTitles();return;}

    const topBar=el('header',null,'commerce-topbar');
    const titleWrap=el('div');
    titleWrap.append(el('h1',msg("ui.credits_orders_and_invoices")),el('p',msg("ui.commercial_credits_use_a_fixed_price_version_task_counts"),'hint'));
    const topActions=el('div',null,'commerce-actions');
    const tabs=[['wallet','我的钱包'],['invoice-overview','电子发票中心'],...(caps.manage?[['studio-quota','工作室额度调配']]:[])];
    for(const [id,label]of tabs){
      const active=id==='invoice-overview'?subview.startsWith('invoice-'):subview===id;
      const b=button(label,()=>switchSubview(id));
      b.setAttribute('aria-pressed',String(active));
      topActions.append(b);
    }
    topActions.append(button(msg("ui.reload_ledger"),()=>load({...scope,subview})));
    topBar.append(titleWrap,topActions);
    root.append(topBar);

    if(subview==='studio-quota'){renderOrganizationQuota(s);return;}

    const byKind={credit:0,bonus:0,check_in:0,special:0};
    for(const b of data.buckets)byKind[b.kind]=(byKind[b.kind]||0)+(b.available||0);
    const billableCount=data.orders.filter(o=>o.status==='paid'&&!invoiceStatusForOrder(o.id)).length;
    summaryGrid(root,[
      ['当前可用积分',data.credit_balance,`通用 ${byKind.credit} · 赠送 ${byKind.bonus}`],
      ['签到与专项额度',byKind.check_in+byKind.special,`签到 ${byKind.check_in} · 专项 ${byKind.special}`],
      ['待开票订单',`${billableCount} 笔`,`已开具 ${data.invoices.filter(i=>i.status==='issued').length} 张`],
      ['计费策略状态',data.policy?'固定价格计费已启用':'未启用商业扣减',caps.payment?'支付收银台已连接':'本地未配置支付通道']
    ]);

    const status=box('服务状态');
    status.append(el('p',msg("ui.pricing_value0_payment_value1_invoice_value2_commercial_metering_value3",{value0:caps.pricing?msg("ui.configuration_exists"):msg("ui.not_configured"),value1:caps.payment?msg("ui.adapter_connected"):msg("ui.not_configured"),value2:caps.invoice?msg("ui.adapter_connected"):msg("ui.not_configured"),value3:data.policy?msg("ui.enable"):msg("ui.not_enabled")})));
    if(!caps.payment)status.append(el('p',msg("ui.no_default_prices_or_payment_channels_are_installed_locally"),'hint'));
    const portalBar=el('div',null,'commerce-actions');
    portalBar.append(
      button('进入电子发票中心 →',()=>switchSubview('invoice-overview'),false,'commerce-btn-primary'),
      button('天工引擎 API 账单 →',()=>ctx.navigate?.('service-operations','engine',s.project))
    );
    if(billableCount>0)portalBar.append(button(`立即开票（${billableCount} 笔待开票）`,()=>switchSubview('invoice-apply')));
    status.append(portalBar);

    const credit=box('商业信用');
    credit.append(el('p',msg("ui.available_credit_shown_value0_personal_and_project_pools_are",{value0:data.credit_balance})));
    table(credit,['类型','归属','可用','到期','状态'],data.buckets.map(b=>[labels[b.kind]||b.kind,actorLabel(b.owner_actor),b.available,b.expires_at?new Date(b.expires_at).toLocaleString():'无到期限制',b.frozen?'订单冻结':b.expired?'已到期':'可用']));
    const redeem=el('div',null,'commerce-actions'),code=input(redeem,'活动兑换码','redeem-code');
    redeem.append(button(msg("ui.redeem_check_in"),()=>write('/redeem',{code:code.value}),!writable()));
    credit.append(redeem);

    if(caps.manage&&data.workspace?.workspace_id)renderOrganizationQuota(s);

    const native=box('原生用量');
    table(native,['单位','已占用','上限','剩余'],Object.keys(data.native_budget.limits).map(unit=>[unit,data.native_budget.used[unit]||0,data.native_budget.limits[unit],data.native_budget.remaining[unit]]));
    if(!Object.keys(data.native_budget.limits).length)native.append(el('p',msg("ui.no_native_unit_project_limits_are_configured_yet"),'hint'));

    const plans=box('套餐与版本');
    for(const plan of data.plans){
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
    if(!data.plans.length)plans.append(el('p',msg("ui.no_plans_are_configured_historical_website_prices_are_not"),'hint'));

    const orders=box('订单与恢复');
    for(const order of data.orders){
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
    if(!data.orders.length)orders.append(el('p',msg("ui.no_orders_are_visible_to_this_identity"),'hint'));

    const invoices=box('发票申请与快捷入口');
    invoices.append(el('p',msg("ui.invoices_come_from_an_invoicing_service_and_are_separate"),'hint'));
    const quickNav=el('div',null,'commerce-actions');
    quickNav.append(
      button('电子发票总览',()=>switchSubview('invoice-overview')),
      button('可开票订单',()=>switchSubview('invoice-orders')),
      button('常用发票抬头',()=>switchSubview('invoice-titles'))
    );
    invoices.append(quickNav);
    for(const row of data.invoices){
      const line=el('div',null,'commerce-actions');
      line.append(el('span',joinMessages(["",row.title," · ",labels[row.status]||row.status,""])),button(msg("ui.check_original_request"),()=>write('/invoices/refresh',{invoice_id:row.id}),!caps.invoice||!writable()));
      if(row.status==='issued')line.append(button(msg("ui.download_issued_invoice"),()=>downloadInvoicePdf(row,t,s)));
      invoices.append(line);
    }

    const ledger=box('信用流水与任务对账');
    table(ledger,['时间','动作','信用变化','任务预留编号'],data.ledger.map(r=>[new Date(r.created_at).toLocaleString(),r.kind,r.delta,r.reservation_id||'—']));
    table(ledger,['原任务','尝试','预留信用','结算信用','状态'],data.reservations.map(r=>[r.job_id,r.attempt,r.bound,r.actual??'待供应商用量证据',labels[r.status]||r.status]));

    if(caps.manage){
      const admin=box('管理员显式业务配置'),details=el('details');
      details.append(el('summary',msg("ui.price_versions_campaigns_and_credit_allocation")));
      const planText=el('textarea');planText.rows=8;planText.value=getDraft('plan','');bindAttribute(planText,"placeholder",msg("ui.enter_the_complete_agreed_pricing_contract_as_json_keep"));planText.addEventListener('input',()=>setDraft('plan',planText.value));field(details,msg("ui.pricing_contract_json"),planText);
      const base=el('select');base.append(localizedOption('',msg("ui.new_plan_version_no_previous_version")));for(const p of data.plans)base.append(localizedOption(p.id,joinMessages([p.document.title," v",p.version])));field(details,msg("ui.price_version_being_replaced"),base);
      const enabled=el('input');enabled.type='checkbox';field(details,msg("ui.enable_commercial_metering_later_runs_require_a_fixed_credit"),enabled);
      details.append(button(msg("ui.register_an_explicit_price_version"),()=>write('/plans',{document:JSON.parse(planText.value),base_version_id:base.value||null,metering_enabled:enabled.checked}),!writable()));
      const campaign=el('textarea');campaign.rows=5;campaign.value=getDraft('campaign','');campaign.addEventListener('input',()=>setDraft('campaign',campaign.value));field(details,msg("ui.campaign_contract_json"),campaign);
      details.append(button(msg("ui.register_promotion"),()=>write('/campaigns',JSON.parse(campaign.value)),!writable()));
      admin.append(details);
    }
  }

  async function load(value){
    scope={...value};
    subview=normalizeCommerceSubview(value?.subview);
    if(value?.targetId)setDraft('invoice-order-id',value.targetId);
    const s=scope,t=++ticket;busy=false;
    root.replaceChildren(el('p',msg("ui.loading_ledger")));
    if(!s.project){root.replaceChildren(el('p',msg("ui.select_a_project_first")));return;}
    if(!session().actor){root.replaceChildren(el('p',msg("ui.sign_in_for_this_operation_financial_and_invoice_information")));return;}
    try{
      const result=await ctx.api(url(s.project),{headers:{'X-CSRF-Token':session().csrf}});
      if(!same(t,s))return;
      data=result;
      ctx.setRevision(result.revision,s.project);
      await loadServerTitles();
      if(!same(t,s))return;
      render();
    }catch(e){
      if(same(t,s))root.replaceChildren(el('p',e.message),button(msg("ui.reload"),()=>load(s)));
    }
  }

  return {load,suspend(){ticket++;scope=null;busy=false;}};
}
