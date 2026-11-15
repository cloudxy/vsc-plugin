import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';

class Element {
  constructor(tag,text=''){
    this.tagName=tag.toUpperCase();this._text=text;this.children=[];this.attrs={};this.listeners={};
    this.value='';this.style={};this.dataset={};this.parentElement=null;this.className='';
    this.classList={
      add:(...v)=>{this.className=[...new Set([...this.className.split(' '),...v])].filter(Boolean).join(' ');},
      contains:v=>this.className.split(' ').includes(v)
    };
  }
  set textContent(v){this._text=v;this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  append(...nodes){for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
  prepend(...nodes){for(const node of [...nodes].reverse()){node.remove();node.parentElement=this;this.children.unshift(node);}}
  remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;}}
  replaceChildren(...nodes){for(const c of [...this.children])c.remove();this._text='';this.append(...nodes);}
  removeAttribute(k){delete this.attrs[k];}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k]??null;}
  matches(selector){
    if(selector[0]==='.')return this.classList.contains(selector.slice(1));
    if(selector[0]==='['){
      const match=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return match&&(match[2]==null?this.attrs[match[1]]!=null:this.attrs[match[1]]===match[2]);
    }
    return this.tagName===selector.toUpperCase();
  }
  querySelectorAll(selector){
    const values=this.children.flatMap(c=>[c,...c.querySelectorAll('*')]);
    if(selector==='*')return values;
    return values.filter(c=>selector.split(',').some(x=>c.matches(x.trim())));
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
  get options(){return this.children.filter(x=>x.tagName==='OPTION');}
  async fire(type,properties={}){
    const event={target:this,preventDefault(){},...properties};
    if(this['on'+type])await this['on'+type](event);
    for(const f of this.listeners[type]||[])await f(event);
    if(['input','change'].includes(type)&&this.parentElement)await this.parentElement.fire(type,{...properties,target:event.target});
  }
}

const document={
  createElement:t=>{const n=new Element(t);n.ownerDocument=document;return n;},
  createTextNode:text=>{const n=new Element('#text',text);n.ownerDocument=document;return n;}
};

async function commerceFixture(options={}){
  const view=document.createElement('main'),requests=[],notices=[];
  let revision=3,clipboardText='',simulateConflictOnce=Boolean(options.simulateConflictOnce);
  const state={
    project_id:'proj-1',
    revision,
    credit_balance:260,
    policy:{id:'plan-v1',version:1,document:{title:'短剧工作室版'}},
    capabilities:{pricing:true,payment:true,invoice:true,manage:true,platform_admin:Boolean(options.platformAdmin)},
    native_budget:{limits:{video_seconds:120},used:{video_seconds:30},remaining:{video_seconds:90}},
    buckets:[
      {id:'b-credit',kind:'credit',owner_actor:'member-1',available:200,expires_at:null,frozen:false,expired:false},
      {id:'b-bonus',kind:'bonus',owner_actor:'member-1',available:40,expires_at:null,frozen:false,expired:false},
      {id:'b-checkin',kind:'check_in',owner_actor:'member-1',available:20,expires_at:null,frozen:false,expired:false}
    ],
    plans:[{id:'plan-v1',version:1,document:{plan_key:'studio_v1',title:'短剧工作室版',amount_minor:9900,currency:'CNY',credits:1000,bucket_kind:'credit',validity_days:30,checkout_minutes:30,purposes:['*'],max_concurrent_jobs:8,seat_limit:20,invoice_enabled:true,refund_policy:'unused_order_only',renewal_policy:'manual_from_payment',watermark_required:false,rates:[{model_id:'seedance-2.0',unit:'video_seconds',credits_per_unit:12}]}}],
    provider_models:[{id:'seedance-2.0',name:'Seedance 2.0'},{id:'flux-pro',name:'Flux Pro'}],
    orders:[
      {id:'ord-paid-billable',status:'paid',amount_minor:9900,currency:'CNY',credits:1000,paid_at:'2026-11-10T08:00:00Z'},
      {id:'ord-paid-invoiced',status:'paid',amount_minor:19900,currency:'CNY',credits:2200,paid_at:'2026-11-09T08:00:00Z'}
    ],
    invoices:[
      {id:'inv-1',order_id:'ord-paid-invoiced',title:'昆仑短剧文化传媒有限公司',status:'issued',created_at:'2026-11-09T09:00:00Z'}
    ],
    invoice_summary:{paid_order_count:2,billable_order_count:1,invoiced_order_count:1,issued_count:1,pending_count:0,support_email:'support@skyproduction.cn',service_hours:'周一至周五 10:00-19:00（法定节假日除外）'},
    ledger:[
      {created_at:'2026-11-10T08:00:00Z',kind:'grant',delta:200,reservation_id:null,supplier_bill_status:'unrecorded',supplier_amount_minor:0,funding_scope_label:'项目账本 · 第一季',attribution_project_name:'第一季',job_id:'job-unrec'},
      {created_at:'2026-11-10T09:00:00Z',kind:'consume',delta:-30,reservation_id:'res-1',supplier_bill_status:'recorded',supplier_amount_minor:450,supplier_currency:'CNY',funding_scope_label:'项目账本 · 第一季',attribution_project_name:'第一季',job_id:'job-rec'}
    ],
    reservations:[],
    workspace:{
      workspace_id:'ws-studio',
      workspace_name:'星辰短剧工作室',
      projects:[{id:'proj-1',name:'第一季',workspace_name:'星辰短剧工作室',revision:3},{id:'proj-2',name:'第二季',workspace_name:'星辰短剧工作室',revision:5}],
      members:[{actor:'director-2',display_name:'王导演'}],
      transfers:[]
    }
  };
  const accountState={
    scope_kind:'identity',
    revision:7,
    credit_balance:520,
    policy:null,
    capabilities:{pricing:true,payment:true,invoice:true,manage:true,platform_admin:true},
    buckets:[{id:'b-self',kind:'credit',owner_actor:'member-1',available:520,expires_at:null,frozen:false,expired:false}],
    plans:structuredClone(state.plans),
    provider_models:structuredClone(state.provider_models),
    orders:[{id:'ord-self-1',status:'paid',amount_minor:4900,currency:'CNY',credits:500,paid_at:'2026-11-12T08:00:00Z'}],
    invoices:[],
    invoice_summary:{paid_order_count:1,billable_order_count:1,invoiced_order_count:0,issued_count:0,pending_count:0,support_email:'billing-ops@custom.example',service_hours:'7×12 09:00-21:00'},
    ledger:[{created_at:'2026-11-12T10:00:00Z',kind:'consume',delta:-15,funding_scope_label:'个人钱包 · member-1',attribution_project_name:'第一季',job_id:'job-self-1',supplier_bill_status:'unrecorded',supplier_amount_minor:0,reservation_id:'res-self-1'}],
    reservations:[]
  };
  const workspaceState={
    scope_kind:'workspace',
    workspace_id:'ws-studio',
    revision:9,
    credit_balance:1800,
    policy:state.policy,
    capabilities:{pricing:true,payment:true,invoice:true,manage:true},
    buckets:[{id:'b-ws-1',kind:'credit',owner_actor:'',available:1800,expires_at:null,frozen:false,expired:false}],
    plans:structuredClone(state.plans),
    orders:[],
    invoices:[],
    invoice_summary:structuredClone(state.invoice_summary),
    ledger:[],
    reservations:[],
    workspace:structuredClone(state.workspace)
  };
  const platformState={
    revision:12,
    plans:structuredClone(state.plans),
    provider_models:structuredClone(state.provider_models)
  };
  const titles=[{id:'tpl-1',title:'昆仑短剧文化传媒有限公司',tax_id:'91110105MA01XXXX88',email:'finance@kunlun.example',workspace_id:'ws-studio',invoice_type:'enterprise_normal',is_default:false}];

  const api=async(path,init={})=>{
    requests.push({path,init});
    if(options.customApi){
      const custom=await options.customApi(path,init);
      if(custom!==undefined)return custom;
    }
    if(init.method==='DELETE'&&path.includes('/commerce/invoice-titles/')){
      revision++;
      state.revision=revision;
      const targetId=decodeURIComponent(path.split('/commerce/invoice-titles/')[1]||'');
      const idx=titles.findIndex(t=>t.id===targetId||`${t.title}::${t.tax_id}`===targetId);
      if(idx>=0)titles.splice(idx,1);
      return {deleted:true,revision};
    }
    if(init.method==='POST'){
      const body=JSON.parse(init.body);
      if(path.endsWith('/commerce/plans/preview-diff')){
        return {
          base_version_id:body.payload.base_version_id,
          next_version_number:2,
          current_revision:path.startsWith('/api/v1/platform/')?platformState.revision:revision,
          diff_sha256:'sha256-plan-diff-001',
          field_diffs:[
            {field:'title',label:'套餐标题',before:'短剧工作室版',after:body.payload.document.title},
            {field:'credits',label:'发放商业信用',before:1000,after:body.payload.document.credits}
          ],
          rate_diffs:{
            added:body.payload.document.rates.slice(1),
            changed:[{model_id:body.payload.document.rates[0].model_id,unit:body.payload.document.rates[0].unit,before_credits_per_unit:12,credits_per_unit:body.payload.document.rates[0].credits_per_unit}],
            removed:[]
          }
        };
      }
      if(path.endsWith('/commerce/campaigns/preview-diff')){
        return {
          current_revision:path.startsWith('/api/v1/platform/')?platformState.revision:revision,
          diff_sha256:'sha256-camp-diff-001',
          field_diffs:[
            {field:'code',label:'活动兑换码',before:null,after:body.payload.code},
            {field:'credits',label:'赠送信用数',before:null,after:body.payload.credits}
          ]
        };
      }
      if(path.endsWith('/commerce/plans')){
        if(simulateConflictOnce){
          simulateConflictOnce=false;
          platformState.revision++;
          revision++;
          throw Object.assign(new Error('基线套餐已被其他管理员并发更新'),{
            status:409,
            code:'commerce_plan_conflict',
            details:{current_revision:path.startsWith('/api/v1/platform/')?platformState.revision:revision,latest_version_id:'plan-v2'}
          });
        }
        revision++;
        platformState.revision++;
        state.revision=revision;
        return {id:'plan-v3',version:2,revision:path.startsWith('/api/v1/platform/')?platformState.revision:revision};
      }
      if(path.endsWith('/commerce/campaigns')){
        revision++;
        platformState.revision++;
        return {id:'camp-1',revision:path.startsWith('/api/v1/platform/')?platformState.revision:revision};
      }
      revision++;
      state.revision=revision;
      if(path.endsWith('/commerce/invoice-titles')){
        const saved={id:body.payload.id||`tpl-${titles.length+1}`,...body.payload};
        if(saved.is_default)for(const item of titles)item.is_default=false;
        const idx=titles.findIndex(item=>item.id===saved.id||(item.title===saved.title&&item.tax_id===saved.tax_id));
        if(idx>=0)titles[idx]=saved;
        else titles.unshift(saved);
        return {item:structuredClone(saved),revision};
      }
      if(path.endsWith('/commerce/invoices')){
        const created={id:`inv-${state.invoices.length+1}`,order_id:body.payload.order_id,title:body.payload.title,status:'issued',created_at:'2026-11-11T10:00:00Z'};
        state.invoices.unshift(created);
        accountState.invoices.unshift(created);
        return {id:created.id,status:'issued',revision};
      }
      if(path.endsWith('/commerce/redeem'))return {id:'red-1',bucket_id:'b-bonus',already_redeemed:false,revision};
      if(path.endsWith('/commerce/allocations'))return {id:'alloc-1',credits:body.payload.credits,revision};
      if(path.endsWith('/commerce/workspace-transfers'))return {id:'tr-1',target_revision:6,revision};
      return {ok:true,revision};
    }
    if(path.includes('/commerce/invoice-titles'))return {revision,items:structuredClone(titles)};
    if(path==='/api/v1/platform/commerce')return structuredClone(platformState);
    if(path==='/api/v1/account/commerce')return structuredClone(accountState);
    if(path.startsWith('/api/v1/workspaces/')&&path.endsWith('/commerce'))return structuredClone(workspaceState);
    if(path.endsWith('/commerce'))return structuredClone(state);
    throw new Error('Unexpected path '+path);
  };

  const navigator={clipboard:{writeText:async t=>{clipboardText=t;}}};
  const module=await loadModule('commerce.js',{document,crypto,console,setTimeout,clearTimeout,URL,navigator,AbortController});
  const navigations=[],govSwitches=[];
  let returnCalled=0;
  const instance=module.createCommerce(view,{
    session:()=>({actor:'member-1',writable:true,csrf:'csrf-tok',revision}),
    setRevision:r=>{revision=r;},
    notice:m=>notices.push(String(m)),
    navigate:(...args)=>navigations.push(args),
    workspaces:()=>[{id:'ws-studio',name:'星辰短剧工作室'}],
    projects:()=>[{id:'proj-1',name:'第一季',storage_policy:'postgres-series-v1'}],
    returnContext:()=>options.returnContext||null,
    onGovernanceNavigate:t=>govSwitches.push(t),
    onReturnContext:()=>{returnCalled++;},
    api
  });
  const button=text=>view.querySelectorAll('button').find(n=>n.textContent===text);
  const input=label=>view.querySelectorAll('input,textarea,select').find(n=>n.getAttribute('aria-label')===label);
  return {view,instance,module,requests,notices,navigations,govSwitches,getReturnCalled:()=>returnCalled,state,accountState,workspaceState,platformState,titles,button,input,getClipboard:()=>clipboardText};
}

test('commerce subview normalizer and tax-id validator handle enterprise and personal rules',async()=>{
  const {module}=await commerceFixture();
  assert.equal(module.normalizeCommerceSubview('invoice'),'invoice-overview');
  assert.equal(module.normalizeCommerceSubview('apply'),'invoice-apply');
  assert.equal(module.normalizeCommerceSubview('unknown'),'wallet');
  const std=module.validateInvoiceTaxId('91110105MA0012345X','enterprise_normal');
  assert.equal(std.valid,true);
  assert.equal(std.standard18,true);
  const personal=module.validateInvoiceTaxId('','personal');
  assert.equal(personal.valid,true);
  assert.equal(personal.normalized,'PERSONAL');
  assert.equal(module.validateInvoiceTaxId('','enterprise_special').valid,false);
});

test('wallet overview renders credit buckets, redeem bar, and navigates into 4-card electronic invoice portal',async()=>{
  const f=await commerceFixture();
  await f.instance.load({project:'proj-1'});
  assert.equal(f.view.dataset.subview,'wallet');
  assert.ok(f.view.textContent.includes('260'));
  assert.ok(f.view.textContent.includes('通用 200 · 赠送 40'));
  f.input('活动兑换码').value='SKY2026';
  await f.input('活动兑换码').fire('input');
  await f.button('兑换 / 签到').fire('click');
  assert.ok(f.requests.some(r=>r.path.endsWith('/commerce/redeem')&&JSON.parse(r.init.body).payload.code==='SKY2026'));

  await f.button('进入电子发票中心 →').fire('click');
  assert.equal(f.view.dataset.subview,'invoice-overview');
  assert.equal(f.view.querySelectorAll('.commerce-portal-card').length,4);
  assert.ok(f.view.textContent.includes('我的钱包 / 电子发票'));
  assert.ok(f.view.textContent.includes('support@skyproduction.cn'));
  assert.ok(f.view.textContent.includes('10:00-19:00'));
  await f.button('复制客服邮箱').fire('click');
  assert.equal(f.getClipboard(),'support@skyproduction.cn');
  f.instance.suspend();
});

test('invoice orders, saved title templates, one-click autofill, and personal/enterprise invoice submission work end-to-end',async()=>{
  const f=await commerceFixture();
  await f.instance.load({project:'proj-1',subview:'invoice-titles'});
  assert.equal(f.view.dataset.subview,'invoice-titles');
  assert.ok(f.view.textContent.includes('昆仑短剧文化传媒有限公司'));
  f.input('常用抬头名称').value='星辰出海影业有限公司';
  await f.input('常用抬头名称').fire('input');
  f.input('常用税号 / 信用代码').value='91310115MA1K99998A';
  await f.input('常用税号 / 信用代码').fire('input');
  f.input('默认接收邮箱').value='billing@star.example';
  await f.input('默认接收邮箱').fire('input');
  await f.button('＋ 保存常用抬头').fire('click');
  assert.ok(f.view.textContent.includes('星辰出海影业有限公司'));

  await f.button('可开票订单').fire('click');
  assert.equal(f.view.dataset.subview,'invoice-orders');
  await f.button('待开票').fire('click');
  assert.ok(f.view.textContent.includes('ord-paid-billable'));
  assert.equal(f.view.textContent.includes('ord-paid-invoiced'),false);
  await f.button('去开发票').fire('click');
  assert.equal(f.view.dataset.subview,'invoice-apply');

  await f.button('星辰出海影业有限公司（默认）').fire('click');
  assert.equal(f.input('发票抬头').value,'星辰出海影业有限公司');
  assert.equal(f.input('税号').value,'91310115MA1K99998A');
  assert.equal(f.input('接收邮箱').value,'billing@star.example');
  await f.button('保存发票申请').fire('click');
  const post=f.requests.find(r=>r.init.method==='POST'&&r.path.endsWith('/commerce/invoices'));
  assert.ok(post);
  const payload=JSON.parse(post.init.body).payload;
  assert.equal(payload.order_id,'ord-paid-billable');
  assert.equal(payload.title,'星辰出海影业有限公司');
  assert.equal(payload.tax_id,'91310115MA1K99998A');
  assert.equal(JSON.parse(post.init.body).actor,undefined);
  f.instance.suspend();
});

test('studio quota subview allocates member credits and transfers cross-project studio credits',async()=>{
  const f=await commerceFixture();
  await f.instance.load({project:'proj-1',subview:'studio-quota'});
  assert.equal(f.view.dataset.subview,'studio-quota');
  f.input('分配信用数').value='50';
  await f.input('分配信用数').fire('input');
  await f.button('分配到目标项目池').fire('click');
  assert.ok(f.requests.some(r=>r.path.endsWith('/commerce/workspace-transfers')&&JSON.parse(r.init.body).payload.credits===50));
  f.instance.suspend();
});

test('wallet formats minor currency for humans, links to vsc-engine billing, and guides empty invoice-apply back to wallet',async()=>{
  const f=await commerceFixture();
  assert.equal(f.module.formatMinorAmount(9900,'CNY'),'¥99.00 (9900 CNY)');
  await f.instance.load({project:'proj-1'});
  assert.ok(f.view.textContent.includes('本人 (member-1)'));
  await f.button('vsc-engine API 账单 →').fire('click');
  assert.deepEqual(f.navigations.at(-1),['service-operations','engine','proj-1']);

  f.state.orders=[];
  await f.instance.load({project:'proj-1',subview:'invoice-apply'});
  assert.ok(f.view.querySelector('.commerce-empty-guide'));
  await f.button('前往我的钱包查看套餐').fire('click');
  assert.equal(f.view.dataset.subview,'wallet');
  f.instance.suspend();
});

test('0-project personal wallet loads directly, switches explicit funding pools with AbortController, and mounts governance nav',async()=>{
  let pendingResolve=null,abortedSignals=0;
  const f=await commerceFixture({
    returnContext:{projectId:'proj-1',projectTitle:'第一季',episodeLabel:'第1集',search:'?project=proj-1&page=studio'},
    customApi:async(path,init)=>{
      if(path==='/api/v1/workspaces/ws-studio/commerce'&&!pendingResolve){
        init.signal?.addEventListener('abort',()=>{abortedSignals++;});
        return new Promise(resolve=>{pendingResolve=resolve;});
      }
      return undefined;
    }
  });
  await f.instance.load({});
  assert.ok(f.requests.some(r=>r.path==='/api/v1/account/commerce'));
  assert.ok(f.view.textContent.includes('520'));
  assert.ok(f.view.textContent.includes('当前显式资金池：个人钱包'));
  assert.ok(f.view.textContent.includes('D-NO-CURRENT-SPACE'));
  assert.ok(f.view.querySelector('.gov-module-tabs'));
  assert.ok(f.view.querySelector('.gov-return-pill'));
  await f.view.querySelector('.gov-return-pill').fire('click');
  assert.equal(f.getReturnCalled(),1);

  const poolSel=f.input('显式资金池选择');
  poolSel.value='workspace:ws-studio';
  const slowSwitch=poolSel.fire('change');
  // Immediately switch to project pool before workspace load resolves -> must abort previous in-flight request
  await f.instance.load({scopeKind:'project',project:'proj-1'});
  assert.equal(abortedSignals,1);
  pendingResolve(f.workspaceState);
  await slowSwitch;
  assert.ok(f.view.textContent.includes('项目账本 · 第一季'));
  assert.ok(f.view.textContent.includes('260'));
  f.instance.suspend();
});

test('persistent invoice titles CRUD, dynamic support email without hardcoded fallback, and unrecorded supplier bill status work cleanly',async()=>{
  const f=await commerceFixture();
  await f.instance.load({});
  // Unrecorded supplier bill renders '账单未登记 / 报价未知' and NEVER '¥0.00'
  const ledgerCard=f.view.querySelector('[data-component="usage-commercial-ledger-card"]');
  assert.ok(ledgerCard);
  assert.ok(ledgerCard.textContent.includes('账单未登记 / 报价未知'));
  assert.equal(ledgerCard.textContent.includes('¥0.00'),false);
  const csvLink=ledgerCard.querySelector('.commerce-csv-link');
  assert.equal(csvLink.href,'/api/v1/account/commerce/ledger.csv');

  // Dynamic support email in 0-project account mode reflects custom email, and empty email disables copy
  await f.instance.load({subview:'invoice-overview'});
  assert.ok(f.view.textContent.includes('billing-ops@custom.example'));
  assert.ok(f.view.textContent.includes('7×12 09:00-21:00'));

  f.accountState.invoice_summary.support_email='';
  await f.instance.load({subview:'invoice-titles'});
  assert.ok(f.view.textContent.includes('未配置支持邮箱'));
  assert.equal(f.view.textContent.includes('support@skyproduction.cn'),false);
  const copyBtn=f.view.querySelectorAll('button').find(b=>b.textContent==='复制客服邮箱');
  assert.equal(copyBtn.disabled,true);

  // Persistent CRUD: set default & delete via server API
  await f.button('设为默认').fire('click');
  assert.ok(f.requests.some(r=>r.init.method==='POST'&&r.path==='/api/v1/account/commerce/invoice-titles'));
  await f.button('移除').fire('click');
  assert.ok(f.requests.some(r=>r.init.method==='DELETE'&&r.path==='/api/v1/account/commerce/invoice-titles/tpl-1'));
  assert.equal(f.titles.length,0);
  f.instance.suspend();
});

test('structured 16-field plan editor, rate matrix, 9-field campaign editor, dry-run diff confirmation, and 409 conflict draft preservation have zero raw JSON textareas',async()=>{
  const f=await commerceFixture({simulateConflictOnce:true,platformAdmin:true});
  await f.instance.load({});
  // Strictly zero raw JSON editable <textarea> anywhere in commerce DOM
  assert.equal(f.view.querySelectorAll('textarea').length,0);

  const planEditor=f.view.querySelector('[data-component="commerce-admin-plan-editor"]');
  const matrix=f.view.querySelector('[data-component="commerce-rate-matrix-table"]');
  const campEditor=f.view.querySelector('[data-component="commerce-admin-campaign-editor"]');
  assert.ok(planEditor);
  assert.ok(matrix);
  assert.ok(campEditor);
  assert.ok(campEditor.textContent.includes('每日 08:00（北京时间 / 00:00 UTC）刷新'));

  // Edit plan fields + add 2nd rate row
  f.input('套餐唯一标识 (plan_key)').value='studio_enterprise_2026';
  await f.input('套餐唯一标识 (plan_key)').fire('input');
  f.input('套餐标题 (title)').value='旗舰企业短剧套餐';
  await f.input('套餐标题 (title)').fire('input');
  f.input('发放商业信用 (credits)').value='2500';
  await f.input('发放商业信用 (credits)').fire('input');
  f.input('席位上限 (seat_limit)').value='50';
  await f.input('席位上限 (seat_limit)').fire('input');

  await f.button('＋ 新增费率行').fire('click');
  // Duplicate (model_id, unit) guard test first
  f.input('费率模型标识 2').value='seedance-2.0';
  await f.input('费率模型标识 2').fire('input');
  await f.button('预览套餐变更差异 (Dry-Run)').fire('click');
  assert.ok(f.notices.some(n=>n.includes('重复的 (模型, 计量单位) 组合')));
  assert.equal(f.view.querySelector('[data-component="commerce-dry-run-diff-dialog"]'),null);

  // Fix 2nd row to distinct model + unit & open Dry-Run Diff dialog
  f.input('费率模型标识 2').value='flux-pro';
  await f.input('费率模型标识 2').fire('input');
  f.input('费率计量单位 2').value='images';
  await f.input('费率计量单位 2').fire('change');
  f.input('费率信用单价 2').value='5';
  await f.input('费率信用单价 2').fire('input');

  await f.button('预览套餐变更差异 (Dry-Run)').fire('click');
  assert.ok(f.requests.some(r=>r.path==='/api/v1/platform/commerce/plans/preview-diff'));
  const dialog=f.view.querySelector('[data-component="commerce-dry-run-diff-dialog"]');
  assert.ok(dialog);
  assert.ok(dialog.textContent.includes('sha256-plan-diff-001'));
  assert.ok(dialog.textContent.includes('flux-pro'));

  // Commit blocked without checking confirmed=true
  await f.button('确认封存发布新套餐版本').fire('click');
  assert.equal(f.requests.filter(r=>r.path==='/api/v1/platform/commerce/plans').length,0);
  assert.ok(dialog.textContent.includes('confirmed = true'));

  // Check confirmation -> first attempt hits 409 commerce_plan_conflict -> dialog & all 16 fields + 2 matrix rows MUST stay intact!
  const confirmBox=f.input('我已逐项核对计费与封存影响');
  confirmBox.checked=true;
  await confirmBox.fire('change');
  await f.button('确认封存发布新套餐版本').fire('click');
  assert.ok(f.view.querySelector('[data-component="commerce-dry-run-diff-dialog"]'));
  assert.ok(dialog.textContent.includes('commerce_plan_conflict'));
  assert.equal(f.input('套餐唯一标识 (plan_key)').value,'studio_enterprise_2026');
  assert.equal(f.input('套餐标题 (title)').value,'旗舰企业短剧套餐');
  assert.equal(f.input('发放商业信用 (credits)').value,'2500');
  assert.equal(f.input('席位上限 (seat_limit)').value,'50');
  assert.equal(f.input('费率模型标识 2').value,'flux-pro');
  assert.equal(f.input('费率信用单价 2').value,'5');

  // Re-run preview against updated baseline and commit cleanly
  await f.button('保留草稿并重新预检基线').fire('click');
  const confirmBox2=f.input('我已逐项核对计费与封存影响');
  confirmBox2.checked=true;
  await confirmBox2.fire('change');
  await f.button('确认封存发布新套餐版本').fire('click');
  const planCommits=f.requests.filter(r=>r.path==='/api/v1/platform/commerce/plans');
  assert.equal(planCommits.length,2);
  const committedBody=JSON.parse(planCommits[1].init.body);
  assert.equal(committedBody.payload.confirmed,true);
  assert.equal(committedBody.payload.diff_sha256,'sha256-plan-diff-001');
  assert.equal(committedBody.payload.document.plan_key,'studio_enterprise_2026');
  assert.equal(committedBody.payload.document.rates.length,2);

  // Campaign Dry-Run + commit
  await f.button('预览活动变更差异 (Dry-Run)').fire('click');
  assert.ok(f.requests.some(r=>r.path==='/api/v1/platform/commerce/campaigns/preview-diff'));
  const campConfirm=f.input('我已逐项核对计费与封存影响');
  campConfirm.checked=true;
  await campConfirm.fire('change');
  await f.button('确认封存发布营销活动').fire('click');
  assert.ok(f.requests.some(r=>r.path==='/api/v1/platform/commerce/campaigns'&&JSON.parse(r.init.body).payload.confirmed===true));
  assert.equal(f.view.querySelectorAll('textarea').length,0);
  f.instance.suspend();
});
