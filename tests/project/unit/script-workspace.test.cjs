const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {Document}=require('../../support/fixtures/frontend/panel_dom.cjs');

function fixture(){
  const document=new Document(''),container=document.createElement('section');document.body.append(container);
  const requests=[],pending=[],notices=[],timers=[];
  let project='/api/v1/projects/A';
  const ctx={api:(url,options)=>{requests.push({url:String(url),options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},
    baseUrl:()=>project, onNotice:m=>notices.push(String(m)),
    session:()=>({actor:'alice',csrf:'c',writable:true,revision:7}), setRevision:()=>{}};
  const ctxObj=vm.createContext({document,URLSearchParams,console,setTimeout:(fn,ms)=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},confirm:()=>true,prompt:()=>'批注内容',
    fetch:(u,o)=>ctx.api(u,o), crypto:{randomUUID:()=>'k'}});
  vm.runInContext(fs.readFileSync(path.join(process.env.VSC_TEST_ROOT,'src/vsc/interfaces/web/static/script-workspace.js'),'utf8').replace('export function createScriptWorkspace','function createScriptWorkspace'),ctxObj);
  const ws=ctxObj.createScriptWorkspace(container,ctx);
  const respond=(data,ok=true)=>{assert.ok(pending.length);const p=pending.shift();ok?p.resolve(data):p.reject(new Error(data.message||'保存失败'));};
  const tick=()=>new Promise(r=>setTimeout(r,0));
  const boot=async data=>{const p=ws.load();respond({sections:{children:{items:[]}}});await tick();respond(data);await p;};
  return {ws,container,requests,pending,timers,notices,boot,tick,setProject:id=>{project='/api/v1/projects/'+id;},respond,
    draft:(revision=1,scenes=[{id:'SC1',estimated_duration_ms:3000,actions:[{id:'A1',text:'他停下',narrative_refs:['N1']}],dialogue:[{id:'L1',speaker:'char',text:'明天再来'}],silence:[{id:'S1',text:'长静默',duration_ms:800,purpose:'breath'}]}])=>
      ({exists:true,scope_key:'',draft_revision:revision,content:{format:'vsc.screenplay/v1',body:'',adaptation_refs:[],scenes},phase:'editing',notes:[],updated_at:'2026-10-18T10:00:00+08:00',updated_by:'a'})};
}
const flush=async t=>{while(t.timers.length){const fn=t.timers.shift();const p=fn();if(p&&p.then)await p;await t.tick();}};

test('F01: switching projects discards stale timers and late autosave responses',async()=>{
  const t=fixture();await t.boot(t.draft());
  const f01line=t.container.querySelector('.line-text');
  f01line.value='今晚我等你';
  await f01line.dispatch('input');
  assert.equal(t.timers.length,1);                      // 定时器已排队
  t.setProject('B');const p=t.ws.load();                 // 切换项目：GET B
  t.respond({sections:{children:{items:[]}}});await t.tick();
  t.respond({exists:false,draft_revision:0,content:null,phase:'empty',notes:[]});await p;
  t.timers.shift()();await new Promise(r=>setTimeout(r,0));  // 旧定时器触发：会话已换、dirty=false → 不得发请求
  assert.ok(!t.requests.some(r=>r.url.includes('autosave')));
  const save=t.timers.shift();assert.ok(!save);          // 无新定时器残留
  });

test('F02: serial queue keeps the last edit and failed save blocks submit',async()=>{
  const t=fixture();await t.boot(t.draft());
  const line=t.container.querySelector('.line-text');
  line.value='第一句';await line.dispatch('input');
  const held=t.timers.shift();const saving=held();       // 第一次保存挂起
  line.value='最后一句';await line.dispatch('input');    // 保存中继续输入
  t.respond({scope_key:'',draft_revision:2,created:false});
  await saving;                                           // 第一次保存完成
  const again=t.timers.shift();assert.ok(again);          // 队列自动续存保存期间的新输入
  const saving2=again();t.respond({scope_key:'',draft_revision:3,created:false});await saving2;
  await t.tick();
  const autosaves=t.requests.filter(r=>r.url.includes('script-draft/autosave'));
  assert.equal(autosaves.length,2);
  assert.ok(autosaves[1].options.body.includes('最后一句'));
  assert.equal(JSON.parse(autosaves[1].options.body).payload.base_draft_revision,2);
  // 保存失败 → 提交被屏障拦截
  line.value='再改';await line.dispatch('input');
  const second=t.timers.shift()();t.respond({message:'HTTP 500'},false);await second;await t.tick();
  const submit=t.container.querySelector('.script-submit-button').click();
  await new Promise(r=>setTimeout(r,20));
  assert.ok(!t.requests.some(r=>r.url.includes('script-submit')));
  assert.ok(t.notices.some(m=>m.includes('保存')));
});

test('F03: editing merges by stable identity and preserves references and silence semantics',async()=>{
  const t=fixture();await t.boot(t.draft());
  const inputs=t.container.querySelectorAll('.line-text');
  const dialogue=inputs[inputs.length-2];                 // 对白行（最后一个是静默）
  dialogue.value='今晚我等你';                            // 只改对白文本
  await dialogue.dispatch('input');
  const saving=t.timers.shift()();
  t.respond({scope_key:'',draft_revision:2,created:false});await saving;
  const payload=JSON.parse(t.requests.find(r=>r.url.includes('autosave')).options.body).payload.content;
  assert.equal(payload.scenes[0].actions[0].narrative_refs.join(),'N1');      // 行动引用保留
  assert.equal(payload.scenes[0].silence[0].duration_ms,800);                 // 静默时长保留
  assert.equal(payload.scenes[0].silence[0].purpose,'breath');                // 静默用途保留
  assert.equal(payload.scenes[0].dialogue[0].text,'今晚我等你');
  assert.equal(payload.scenes[0].dialogue[0].speaker,'char');
});
