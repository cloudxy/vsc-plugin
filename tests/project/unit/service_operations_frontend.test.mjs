import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';

class Element {
  constructor(tag,text=''){
    this.tagName=tag.toUpperCase();this._text=text;this.children=[];this.attrs={};this.listeners={};
    this.value='';this.checked=false;this.style={};this.dataset={};this.parentElement=null;this.className='';
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
  showModal(){this.open=true;}
  close(){this.open=false;return this.fire('close');}
  focus(){}
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

async function opsFixture(){
  const view=document.createElement('main'),requests=[],notices=[],navigations=[];
  let revision=4,clipboardText='';
  const state={
    project_id:'proj-ops',
    revision,
    identity_id:'id-1',
    actor:'studio-lead',
    manage:true,
    capabilities:['read','execute','manage'],
    configuration:{id:'cfg-1',version:1,document:{support_text:'技术支持 7×12',terms_url:'https://example.com/terms',privacy_url:'https://example.com/privacy',api_documentation:'Bearer 鉴权文档'}},
    announcements:[{id:'ann-1',announcement_key:'v1',title:'天工引擎升级公告',body:'开放接口速率边界上线',status:'published'}],
    requests:[
      {id:'req-fb-1',kind:'feedback',title:'字幕导出建议',body:'建议增加 8 列质检报告入口',channel:'/script/qc',status:'received',mine:true,events:[{id:'ev-1',status:'received',reason:'已保存',created_at:'2026-11-10T10:00:00Z'}]},
      {id:'req-fb-2',kind:'feedback',title:'画布快捷键',body:'已联系产品确认快捷键方案',channel:'/canvas',status:'local_approved',mine:true,events:[{id:'ev-2',status:'local_approved',reason:'已联系',created_at:'2026-11-10T11:00:00Z'}]}
    ],
    api_keys:[],
    api_calls:[{call_id:'call-1',operation:'jobs',phase:'finished',status_code:200,created_at:'2026-11-10T12:00:00Z'}],
    api_catalog:{version:'vsc.service-api/v1',authentication:'Bearer',operations:[{operation:'jobs',method:'GET',path:'/api/v1/service-api/projects/proj-ops/jobs',capability:'read'}]},
    engine_overview:{
      credit_balance:1850,
      total_consumed_credits:420,
      ledger_records:[{created_at:'2026-11-10T12:00:00Z',kind:'reserve',delta:-120,actor:'studio-lead',reservation_id:'res-1'}],
      recharge_orders:[{id:'ord-101',status:'paid',amount_minor:29900,currency:'CNY',credits:3000,created_at:'2026-11-09T09:00:00Z',paid_at:'2026-11-09T09:05:00Z'}],
      reservations:[{job_id:'job-1',account_actor:'studio-lead',bound:120,actual:100,status:'settled',created_at:'2026-11-10T12:00:00Z'}],
      recent_jobs:[{id:'job-1',modality:'video',purpose:'shot_take',model_version:'seedance-2.0',status:'succeeded',updated_at:'2026-11-10T12:05:00Z'}],
      member_usage:[{actor:'studio-lead',reservation_count:3,credits_used:420}]
    }
  };

  const api=async(path,init={})=>{
    requests.push({path,init});
    if(path.includes('/network-diagnostic/ping')){
      const probe=new URL(path,'http://fixture').searchParams.get('probe');
      return {ok:true,probe_key:probe,project_id:'proj-ops',revision,database:'connected',storage:'configured'};
    }
    if(path.endsWith('/seedance-verify')){
      const payload=JSON.parse(init.body).payload;
      return {
        project_id:'proj-ops',
        task_id:payload.task_id,
        is_seedance_hex16:/^[0-9a-f]{16}$/.test(payload.task_id),
        read_only:true,
        credits_consumed:0,
        co_brand:'天工工作台 × 火山引擎',
        verified:payload.task_id==='8f3a19c04b2e7d11',
        job:payload.task_id==='8f3a19c04b2e7d11'?{id:'job-1',status:'succeeded',model_version:'seedance-2.0'}:null,
        tos_signature:payload.tos_url?{status:'valid',message:'签名链接仍在有效期内（剩余 1800 秒）。'}:null,
        message:'已核对本地原始生成任务回执；本次操作仅查询，未重新生成且未消耗积分。'
      };
    }
    if(path.endsWith('/account-close/preview')){
      return {ready:true,sha256:'preview-sha',plan:{effect:'停用本地登录与 API 凭据，保留历史审计记录',blockers:[]}};
    }
    if(init.method==='POST'){
      const body=JSON.parse(init.body);
      revision++;state.revision=revision;
      if(path.endsWith('/api-keys')){
        state.api_keys.unshift({id:'key-1',name:body.payload.name,prefix:body.payload.secret.slice(0,8),capabilities:body.payload.capabilities,expires_at:body.payload.expires_at,ip_allowlist:body.payload.ip_allowlist,requests_per_minute:body.payload.requests_per_minute,revoked:false});
        return {id:'key-1',prefix:body.payload.secret.slice(0,8),revision};
      }
      if(path.endsWith('/requests')){
        const req={id:`req-${state.requests.length+1}`,...body.payload,status:body.payload.kind==='studio'?'awaiting_configuration':'received',mine:true,events:[{id:`ev-${revision}`,status:'received',reason:'已保存',created_at:'2026-11-11T10:00:00Z'}]};
        state.requests.unshift(req);
        return {id:req.id,status:req.status,revision};
      }
      if(path.endsWith('/exports/build')){
        const target=state.requests.find(r=>r.id===body.payload.request_id);
        if(target){target.status='export_ready';target.export={id:'exp-1',sha256:'abc'};}
        return {id:'exp-1',request_id:body.payload.request_id,status:'export_ready',revision};
      }
      if(path.endsWith('/account-close/execute')){
        return {closed:true,revision};
      }
      return {ok:true,revision};
    }
    if(path.includes('/media?'))return {items:[]};
    if(path.endsWith('/artifacts'))return {items:[]};
    if(path.endsWith('/service-operations'))return structuredClone(state);
    throw new Error('Unexpected path '+path);
  };

  const navigator={clipboard:{writeText:async t=>{clipboardText=t;}}};
  const module=await loadModule('service-operations.js',{document,crypto,console,setTimeout,clearTimeout,URL,URLSearchParams,navigator,btoa});
  const instance=module.createServiceOperations(view,{
    session:()=>({actor:'studio-lead',writable:true,csrf:'csrf-ops',revision}),
    setRevision:r=>{revision=r;},
    notice:m=>notices.push(String(m)),
    navigate:(...args)=>navigations.push(args),
    api
  });
  const button=text=>view.querySelectorAll('button').find(n=>n.textContent===text);
  const input=label=>view.querySelectorAll('input,textarea,select').find(n=>n.getAttribute('aria-label')===label);
  return {view,instance,module,requests,notices,navigations,button,input,getClipboard:()=>clipboardText};
}

test('pure validators verify 16-hex Seedance task IDs, TOS signed URLs, and 5-tab feedback buckets',async()=>{
  const {module}=await opsFixture();
  assert.equal(module.validateSeedanceTaskId('8F3A19C04B2E7D11').isHex16,true);
  assert.equal(module.validateSeedanceTaskId('short').valid,false);
  const tos=module.parseTosSignedUrl('https://tos.volces.com/a.mp4?X-Tos-Date=20261111T100000Z&X-Tos-Expires=3600',Date.UTC(2026,10,11,10,30,0));
  assert.equal(tos.signed,true);
  assert.equal(tos.expired,false);
  assert.equal(tos.remainingSeconds,1800);
  assert.equal(module.feedbackDisplayStatus('local_approved').label,'已联系');
  assert.equal(module.feedbackDisplayStatus('withdrawn').bucket,'closed');
});

test('engine API subview enforces SPV compliance gate, issues one-time secret, and switches consumption/recharge CSV views',async()=>{
  const f=await opsFixture();
  await f.instance.load({project:'proj-ops',subview:'engine'});
  assert.equal(f.view.dataset.subview,'engine');
  assert.ok(f.view.textContent.includes('1850 信用'));
  f.input('API 凭据名称').value='生产管线密钥';
  await f.input('API 凭据名称').fire('input');
  await f.button('生成并登记 API 凭据').fire('click');
  assert.ok(f.notices.some(m=>m.includes('SPV 企业合规协议')));
  assert.equal(f.requests.some(r=>r.path.endsWith('/api-keys')),false);

  const spv=f.input('确认天工引擎开放接口与SPV合规协议');
  spv.checked=true;await spv.fire('change');
  await f.button('生成并登记 API 凭据').fire('click');
  assert.ok(f.requests.some(r=>r.path.endsWith('/api-keys')));
  assert.ok(f.input('本次新 API 凭据（仅此页面可见）').value.length>20);

  await f.button('充值记录').fire('click');
  assert.ok(f.view.textContent.includes('ord-101'));
  await f.button('导出全部 (CSV)').fire('click');
  assert.ok(f.notices.some(m=>m.includes('CSV')));
  f.instance.suspend();
});

test('data-records personal/studio modes, Seedance read-only verification, and 5-tab feedback records work end-to-end',async()=>{
  const f=await opsFixture();
  await f.instance.load({project:'proj-ops',subview:'data-records'});
  assert.ok(f.view.textContent.includes('API 账户 · 天工引擎'));
  await f.button('工作室团队成本核算').fire('click');
  assert.ok(f.view.textContent.includes('团队成员消耗与项目单集成本核算表'));
  assert.ok(f.view.textContent.includes('420'));

  await f.button('Seedance 视频验真').fire('click');
  assert.equal(f.view.dataset.subview,'seedance-verify');
  assert.ok(f.view.textContent.includes('不会重新生成视频，也不消耗任何积分'));
  f.input('Seedance 任务编号').value='8f3a19c04b2e7d11';
  await f.input('Seedance 任务编号').fire('input');
  f.input('TOS 签名链接（可选，检查有效期）').value='https://tos.volces.com/v.mp4?X-Tos-Date=20261111T100000Z&X-Tos-Expires=3600';
  await f.input('TOS 签名链接（可选，检查有效期）').fire('input');
  await f.button('立即核验任务回执').fire('click');
  assert.ok(f.view.textContent.includes('核验通过：已匹配原始生成任务回执'));
  assert.ok(f.view.textContent.includes('seedance-2.0'));

  await f.button('我的意见反馈').fire('click');
  assert.equal(f.view.dataset.subview,'feedback-records');
  await f.button('已联系').fire('click');
  assert.ok(f.view.textContent.includes('画布快捷键'));
  assert.equal(f.view.textContent.includes('字幕导出建议'),false);
  await f.button('⊕ 提交新反馈').fire('click');
  f.input('反馈标题').value='导出体验优化';await f.input('反馈标题').fire('input');
  f.input('问题与建议详情').value='希望支持一键复制报告链接';await f.input('问题与建议详情').fire('input');
  await f.button('提交反馈记录').fire('click');
  assert.ok(f.requests.some(r=>r.path.endsWith('/requests')&&JSON.parse(r.init.body).payload.kind==='feedback'));
  f.instance.suspend();
});

test('Kunlun AI drama base onboarding, 10-probe light network diagnostics, personal export, and account close execute cleanly',async()=>{
  const f=await opsFixture();
  await f.instance.load({project:'proj-ops',subview:'ai-drama-base'});
  assert.ok(f.view.textContent.includes('入驻昆仑万维AI短剧基地，一站式生产直达全球出海'));
  assert.ok(f.view.textContent.includes('5% 入驻奖励'));
  assert.ok(f.view.textContent.includes('500万 算力补贴 + 20% 充值福利'));
  assert.ok(f.view.textContent.includes('4x 流量加权'));
  assert.equal(f.view.querySelectorAll('.so-showcase-card').length,6);
  await f.button('立即申请线上入驻').fire('click');
  f.input('工作室 / 公司名称').value='山海短剧工坊';await f.input('工作室 / 公司名称').fire('input');
  f.input('代表作品、团队规模与月产能说明').value='月产 8 部精品出海短剧';await f.input('代表作品、团队规模与月产能说明').fire('input');
  await f.button('提交基地入驻申请').fire('click');
  assert.ok(f.requests.some(r=>r.path.endsWith('/requests')&&JSON.parse(r.init.body).payload.kind==='studio'));

  await f.button('网络诊断').fire('click');
  assert.equal(f.view.dataset.subview,'network-diagnostic');
  assert.ok(f.view.querySelector('.so-network-light'));
  await f.button('开始 10 项全链路诊断').fire('click');
  assert.ok(f.view.textContent.includes('诊断进度：10 / 10'));
  await f.button('复制诊断报告 (JSON)').fire('click');
  assert.equal(JSON.parse(f.getClipboard()).succeeded,10);

  await f.button('个人信息导出').fire('click');
  await f.button('提交个人信息导出申请').fire('click');
  await f.button('生成本地个人资料文件').fire('click');
  assert.ok(f.view.textContent.includes('本地导出文件已生成'));

  await f.button('账户注销').fire('click');
  await f.button('1. 提交注销核验申请').fire('click');
  await f.button('预览本人账户停用影响').fire('click');
  f.input('输入当前操作身份确认').value='studio-lead';
  await f.input('输入当前操作身份确认').fire('input');
  await f.button('停用本人本地账户').fire('click');
  assert.ok(f.view.textContent.includes('本地账户已停用'));
  f.instance.suspend();
});

test('standalone subviews stay focused without multi-tab admin clutter, support task_id prefill, and guide empty feedback state',async()=>{
  const f=await opsFixture();
  await f.instance.load({project:'proj-ops',subview:'overview'});
  assert.ok(f.view.querySelector('.so-subnav'));

  await f.instance.load({project:'proj-ops',subview:'seedance-verify',targetId:'8f3a19c04b2e7d11'});
  assert.equal(f.view.querySelector('.so-subnav'),null);
  assert.equal(f.input('Seedance 任务编号').value,'8f3a19c04b2e7d11');

  await f.instance.load({project:'proj-ops',subview:'engine'});
  assert.equal(f.view.querySelector('.so-subnav'),null);
  await f.button('充值').fire('click');
  assert.deepEqual(f.navigations.at(-1),['commerce','wallet','proj-ops']);

  await f.instance.load({project:'proj-ops',subview:'feedback-records'});
  await f.button('处理中').fire('click');
  assert.ok(f.view.querySelector('.so-empty-state'));
  await f.button('提交第一条反馈').fire('click');
  assert.ok(f.view.querySelector('.so-feedback-drawer'));

  await f.instance.load({project:'proj-ops',subview:'activity'});
  assert.ok(f.view.textContent.includes('充值解锁 DramaWave 承制权益'));
  await f.instance.load({project:'proj-ops',subview:'pc-only-notice'});
  assert.ok(f.view.textContent.includes('建议使用桌面端浏览器访问'));
  await f.instance.load({project:'proj-ops',subview:'icon'});
  assert.ok(f.view.textContent.includes('canvas-infinite'));
  f.input('搜索图标名称或场景').value='seedance';await f.input('搜索图标名称或场景').fire('input');
  assert.ok(f.view.textContent.includes('seedance-shield'));
  assert.equal(f.view.textContent.includes('canvas-infinite'),false);
  await f.instance.load({project:'proj-ops',subview:'404'});
  assert.equal(f.view.dataset.subview,'not-found');
  assert.ok(f.view.textContent.includes('404 · 页面不存在或已移动'));
  f.instance.suspend();
});
