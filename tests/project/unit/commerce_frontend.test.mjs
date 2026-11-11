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

async function commerceFixture(){
  const view=document.createElement('main'),requests=[],notices=[];
  let revision=3,clipboardText='';
  const state={
    project_id:'proj-1',
    revision,
    credit_balance:260,
    policy:{id:'plan-v1',version:1,document:{title:'短剧工作室版'}},
    capabilities:{pricing:true,payment:true,invoice:true,manage:true},
    native_budget:{limits:{video_seconds:120},used:{video_seconds:30},remaining:{video_seconds:90}},
    buckets:[
      {id:'b-credit',kind:'credit',owner_actor:'member-1',available:200,expires_at:null,frozen:false,expired:false},
      {id:'b-bonus',kind:'bonus',owner_actor:'member-1',available:40,expires_at:null,frozen:false,expired:false},
      {id:'b-checkin',kind:'check_in',owner_actor:'member-1',available:20,expires_at:null,frozen:false,expired:false}
    ],
    plans:[{id:'plan-v1',version:1,document:{title:'短剧工作室版',amount_minor:9900,currency:'CNY',credits:1000,validity_days:30,max_concurrent_jobs:8,seat_limit:20,renewal_policy:'manual_from_payment',watermark_required:false}}],
    orders:[
      {id:'ord-paid-billable',status:'paid',amount_minor:9900,currency:'CNY',credits:1000,paid_at:'2026-11-10T08:00:00Z'},
      {id:'ord-paid-invoiced',status:'paid',amount_minor:19900,currency:'CNY',credits:2200,paid_at:'2026-11-09T08:00:00Z'}
    ],
    invoices:[
      {id:'inv-1',order_id:'ord-paid-invoiced',title:'昆仑短剧文化传媒有限公司',status:'issued',created_at:'2026-11-09T09:00:00Z'}
    ],
    invoice_summary:{paid_order_count:2,billable_order_count:1,invoiced_order_count:1,issued_count:1,pending_count:0,support_email:'support@skyproduction.cn',service_hours:'周一至周五 10:00-19:00（法定节假日除外）'},
    ledger:[{created_at:'2026-11-10T08:00:00Z',kind:'grant',delta:200,reservation_id:null}],
    reservations:[],
    workspace:{
      workspace_id:'ws-studio',
      workspace_name:'星辰短剧工作室',
      projects:[{id:'proj-1',name:'第一季',workspace_name:'星辰短剧工作室',revision:3},{id:'proj-2',name:'第二季',workspace_name:'星辰短剧工作室',revision:5}],
      members:[{actor:'director-2',display_name:'王导演'}],
      transfers:[]
    }
  };
  const titles=[{title:'昆仑短剧文化传媒有限公司',tax_id:'91110105MA01XXXX88',email:'finance@kunlun.example',workspace_id:'ws-studio',invoice_type:'enterprise_normal'}];

  const api=async(path,init={})=>{
    requests.push({path,init});
    if(init.method==='POST'){
      const body=JSON.parse(init.body);
      revision++;
      state.revision=revision;
      if(path.endsWith('/commerce/invoices')){
        const created={id:`inv-${state.invoices.length+1}`,order_id:body.payload.order_id,title:body.payload.title,status:'issued',created_at:'2026-11-11T10:00:00Z'};
        state.invoices.unshift(created);
        titles.unshift({title:body.payload.title,tax_id:body.payload.tax_id,email:body.payload.email,workspace_id:body.payload.workspace_id||null,invoice_type:body.payload.tax_id==='PERSONAL'?'personal':'enterprise_normal'});
        return {id:created.id,status:'issued',revision};
      }
      if(path.endsWith('/commerce/redeem'))return {id:'red-1',bucket_id:'b-bonus',already_redeemed:false,revision};
      if(path.endsWith('/commerce/allocations'))return {id:'alloc-1',credits:body.payload.credits,revision};
      if(path.endsWith('/commerce/workspace-transfers'))return {id:'tr-1',target_revision:6,revision};
      return {ok:true,revision};
    }
    if(path.includes('/commerce/invoice-titles'))return {project_id:'proj-1',revision,items:structuredClone(titles)};
    if(path.endsWith('/commerce'))return structuredClone(state);
    throw new Error('Unexpected path '+path);
  };

  const navigator={clipboard:{writeText:async t=>{clipboardText=t;}}};
  const module=await loadModule('commerce.js',{document,crypto,console,setTimeout,clearTimeout,URL,navigator});
  const navigations=[];
  const instance=module.createCommerce(view,{
    session:()=>({actor:'member-1',writable:true,csrf:'csrf-tok',revision}),
    setRevision:r=>{revision=r;},
    notice:m=>notices.push(String(m)),
    navigate:(...args)=>navigations.push(args),
    api
  });
  const button=text=>view.querySelectorAll('button').find(n=>n.textContent===text);
  const input=label=>view.querySelectorAll('input,textarea,select').find(n=>n.getAttribute('aria-label')===label);
  return {view,instance,module,requests,notices,navigations,state,button,input,getClipboard:()=>clipboardText};
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

test('wallet formats minor currency for humans, links to Tiangong Engine billing, and guides empty invoice-apply back to wallet',async()=>{
  const f=await commerceFixture();
  assert.equal(f.module.formatMinorAmount(9900,'CNY'),'¥99.00 (9900 CNY)');
  await f.instance.load({project:'proj-1'});
  assert.ok(f.view.textContent.includes('本人 (member-1)'));
  await f.button('天工引擎 API 账单 →').fire('click');
  assert.deepEqual(f.navigations.at(-1),['service-operations','engine','proj-1']);

  f.state.orders=[];
  await f.instance.load({project:'proj-1',subview:'invoice-apply'});
  assert.ok(f.view.querySelector('.commerce-empty-guide'));
  await f.button('前往我的钱包查看套餐').fire('click');
  assert.equal(f.view.dataset.subview,'wallet');
  f.instance.suspend();
});
