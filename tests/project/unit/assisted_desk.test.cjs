const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {Document}=require('../../support/fixtures/frontend/panel_dom.cjs');
const root=process.env.VSC_TEST_ROOT||path.resolve(__dirname,'../../..');
const folder=path.join(root,'src/vsc/interfaces/web/static');
const deferred=()=>{let resolve,reject;return {promise:new Promise((a,b)=>{resolve=a;reject=b;}),resolve,reject};};
const button=(root,text)=>root.querySelectorAll('button').find(b=>b.textContent===text);
let serial=0;
async function fixture(handler,session={actor:'human',csrf:'csrf',writable:true}){
  const document=new Document(''),container=document.createElement('section'),calls=[],notices=[];
  const environment={document,crypto:{randomUUID:()=>`operation-${++serial}`}};
  globalThis.__deskTests ||= new Map();const key=++serial;globalThis.__deskTests.set(key,environment);
  const prefix=`const {document,crypto}=globalThis.__deskTests.get(${key});\n`;
  const data=source=>'data:text/javascript;base64,'+Buffer.from(prefix+source).toString('base64');
  let source=fs.readFileSync(path.join(folder,'assisted-desk.js'),'utf8');
  for(const name of ['artifact-reader','review'])source=source.replace(`'./${name}.js'`,JSON.stringify(data(fs.readFileSync(path.join(folder,name+'.js'),'utf8'))));
  const module=await import(data(source));
  const ctx={api:async(url,options)=>{calls.push({url,options});return handler(url,options);},
    session:()=>session,notice:text=>notices.push(text),player:async()=>document.createElement('video'),
    projects:()=>[],projectName:()=> '合成作品',route:()=>{},revision:()=>{},specialist:()=>{},navigate:()=>{},login:()=>{},media:()=>{},artifact:()=>{}};
  return {document,container,calls,notices,ctx,session,module,desk:module.createAssistedDesk(container,ctx)};
}
const rows=[{id:'artifact:a',kind:'artifact',title:'固定剧本',status_label:'等待审阅',ref:{kind:'artifact',id:'a',version_id:'a'}},
  {id:'artifact:b',kind:'artifact',title:'另一份剧本',status_label:'等待审阅',ref:{kind:'artifact',id:'b',version_id:'b'}}];
const page=(items=rows)=>({revision:5,items,total:items.length,counts:{review:items.length,progress:0,results:0},next_offset:null,ancestors:[]});
const target={artifact_id:'a',artifact_sha256:'a'.repeat(64),category:'subtitle',render_id:'render',render_output_id:'output',media_sha256:'b'.repeat(64)};
const artifact=id=>({id,title:'正文 '+id,version:2,document:{正文:'可读作品 '+id},review_history:{items:[]},
  review_targets:[{label:'所见字幕',target:{...target,artifact_id:id}}]});
const capability={available:true,target,cues:[{id:'cue',text:'这一句',start_frame:30,end_frame:60}]};
const basic=async url=>url.includes('assisted-desk?')?page():url.includes('edit-preview-capability')?capability:
  url.includes('review-history?')?{items:[]}:url.includes('/artifacts/')?artifact(url.split('/').at(-1)):null;

test('first result opens real reader, with separate list, work and feedback panes and fixed deep link',async()=>{
  const f=await fixture(basic);await f.desk.load({projectId:'p'});
  assert.ok(f.container.querySelector('.desk-content').textContent.includes('可读作品 a'));
  assert.ok(f.container.querySelector('.desk-feedback').querySelector('textarea'));
  assert.equal(f.container.querySelector('.desk-queue').querySelector('a').getAttribute('aria-current'),'true');
  assert.deepEqual(f.module.parseDeskLocation(f.module.deskLink({project:'p',scope:'s',object:'artifact:a',version:'a',bucket:'results'})),
    {page:'desk',project:'p',scope:'s',object:'artifact:a',version:'a',bucket:'results'});
});

test('explicit earlier fixed version opens outside the new review queue and a missing target never falls back',async()=>{
  const f=await fixture(async(url,options)=>{
    if(url.includes('/artifacts/missing'))throw new Error('固定版本不存在或不属于此项目');
    return basic(url,options);
  });
  await f.desk.load({projectId:'p',ref:'artifact:old-fixed',version:'old-fixed'});
  assert.ok(f.container.querySelector('.desk-content').textContent.includes('可读作品 old-fixed'));
  assert.equal(f.calls.some(row=>row.url.endsWith('/artifacts/a')),false);
  await f.desk.load({projectId:'p',ref:'artifact:missing',version:'missing'});
  assert.ok(f.container.querySelector('.desk-content').textContent.includes('固定版本不存在或不属于此项目'));
  assert.equal(f.container.querySelector('.desk-content').textContent.includes('可读作品 a'),false);
});

test('embedded design uses a readable target label while retaining its original fixed review anchor',async()=>{
  const f=await fixture(url=>url.endsWith('/artifact-review-notes')?{revision:6}:url.includes('edit-preview-capability')?{available:false}:url.endsWith('/artifacts/a')?{...artifact('a'),review_targets:[{label:'machine-design-key',target:{...target,design_unit_id:'fixed-unit'}}]}:basic(url));
  await f.desk.load({projectId:'p',ref:'artifact:a',embedded:true,designArtifactId:'a',targetAnchor:{design_unit_id:'fixed-unit'},targetLabel:'当前分镜构图'});
  const form=f.container.querySelector('.artifact-review-form');assert.equal(form.querySelector('option').textContent,'当前分镜构图');form.querySelector('textarea').value='保持原锚点';await form.querySelector('textarea').dispatch('input');
  assert.ok(!form.textContent.includes('machine-design-key'));
  await form.dispatch('submit');assert.equal(JSON.parse(f.calls.find(call=>call.url.endsWith('/artifact-review-notes')).options.body).payload.design_unit_id,'fixed-unit');
});

test('one toolbar keeps identity with scope and the tools and refresh share an action group',async()=>{
  const f=await fixture(url=>url.includes('assisted-desk?')?{...page(),scope:{title:'第二集'}}:basic(url),
    {actor:'human',writable:false});
  await f.desk.load({projectId:'p',objectId:'episode'});
  const header=f.container.querySelector('.desk-heading'),identity=header.querySelector('.desk-identity'),actions=header.querySelector('.desk-actions');
  assert.equal(identity.querySelector('h1').textContent,'工作台');
  assert.ok(identity.textContent.includes('合成作品'));
  assert.ok(identity.textContent.includes('第二集'));
  assert.ok(identity.textContent.includes('此项目只读'));
  assert.equal(header.querySelector('.desk-tools').parentElement,actions);
  assert.equal(button(f.container,'刷新').parentElement,actions);
  assert.equal(f.container.children.filter(node=>node.classList.contains('desk-scope')).length,0);
  await button(f.container,'刷新').pressKey('Enter');
  assert.equal(f.calls.filter(call=>call.url.includes('assisted-desk?')).length,2);
});

test('professional tools follow the creative sequence and retain keyboard return from their menu',async()=>{
  const f=await fixture(basic),opened=[];f.ctx.specialist=view=>opened.push(view);
  await f.desk.load({projectId:'p'});
  const groups=f.container.querySelectorAll('.desk-tool-group'),tools=f.container.querySelector('.desk-tools');
  assert.deepEqual(groups.map(group=>group.querySelector('h2').textContent),['创作','查阅']);
  assert.deepEqual(groups[0].querySelectorAll('button').map(item=>item.textContent),
    ['创意与原稿','剧本编辑','场镜设计','候选比较','剪辑交付']);
  assert.deepEqual(groups[1].querySelectorAll('button').map(item=>item.textContent),['场镜关系','文案版本','关系画布']);
  tools.open=true;await tools.dispatch('keydown',{key:'Escape'});
  assert.equal(tools.open,false);assert.equal(f.document.activeElement,tools.querySelector('summary'));
  tools.open=true;await button(tools,'场镜设计').pressKey('Enter');
  assert.equal(tools.open,false);assert.deepEqual(opened,['designs']);
});

test('successful execution without outputs reports the missing result and keeps a read recovery action',async()=>{
  const job={id:'job:job',kind:'job',title:'制作任务',status:'succeeded',status_label:'请回看结果',ref:{kind:'job',id:'job'}};
  const f=await fixture(url=>url.includes('assisted-desk?')?page([job]):{sections:{job_attempts:{items:[{status:'succeeded',outputs:[]}]}}});
  await f.desk.load({projectId:'p',bucket:'progress'});
  const content=f.container.querySelector('.desk-content');
  assert.ok(content.textContent.includes('执行：已结束'));
  assert.ok(content.textContent.includes('尚无已登记结果'));
  assert.equal(button(content,'查看本次结果'),undefined);
  assert.ok(button(content,'重新读取任务'));
  assert.ok(f.container.querySelector('.desk-queue').querySelector('.desk-runtime'));
  assert.equal(f.container.querySelector('.desk-heading').querySelector('.desk-runtime'),null);
  await button(content,'重新读取任务').click();
  assert.equal(f.calls.filter(call=>call.url.includes('job_attempts')).length,2);
});

test('a missing media result renders its actual gap and never mounts a player',async()=>{
  const media={id:'media:m',kind:'media',title:'登记结果',ref:{kind:'media',id:'m'}};
  const f=await fixture(url=>url.includes('assisted-desk?')?page([media]):
    {id:'m',result_availability:{status:'unavailable',message:'固定媒体副本缺失'},review_history:{items:[]}});
  await f.desk.load({projectId:'p'});
  const content=f.container.querySelector('.desk-content');
  assert.equal(content.querySelector('video'),null);
  assert.ok(content.textContent.includes('固定媒体副本缺失'));
  assert.ok(button(content,'重新读取素材'));
  assert.ok(button(content,'用途、来源与候选决定'));
});

test('current job shows fixed estimate, reported native use and unknown bill without scanning project budgets',async()=>{
  for(const quoted of [false,true]){
    const f=await fixture(url=>url.includes('/generation-jobs/')?{quote:{status:quoted?'estimate':'unknown',amount:quoted?'2.50':null,currency:quoted?'CNY':null,native_units:{video_seconds:6},reason:'固定报价依据'},reconciliation:{actual_units_reported:true,actual_units:{video_seconds:7},native_delta:{video_seconds:1},threshold_exceeded:true,actual_amount:null}}:url.includes('job_attempts')?{sections:{job_attempts:{items:[{id:'fixed-job',status:'succeeded',outputs:[]}]}}}:basic(url));
    await f.desk.load({projectId:'p',ref:'job:fixed-job',embedded:true});const quote=f.container.querySelector('.job-quote');
    assert.ok(quote.textContent.includes(quoted?'估算金额：2.50 CNY':'金额尚未核实'));
    assert.ok(quote.textContent.includes('已上报实际用量：视频秒数 7'));assert.ok(quote.textContent.includes('实际费用尚未核实'));assert.ok(quote.textContent.includes('偏差超过'));
    assert.equal(f.calls.filter(call=>call.url.endsWith('/generation-jobs/fixed-job/quote')).length,1);assert.equal(f.calls.some(call=>call.url.includes('/budget')),false);
  }
});

test('a late quote cannot replace another fixed object and a quote failure preserves the original job receipt',async()=>{
  const quote=deferred();const f=await fixture(url=>url.includes('/generation-jobs/')?quote.promise:url.includes('job_attempts')?{sections:{job_attempts:{items:[{status:'succeeded',outputs:[]}]}}}:basic(url));
  const old=f.desk.load({projectId:'p',ref:'job:old-job',embedded:true});await new Promise(setImmediate);await f.desk.load({projectId:'p',ref:'artifact:new',embedded:true});quote.resolve({quote:{status:'estimate',amount:'999',currency:'CNY'}});await old;
  assert.ok(f.container.querySelector('.desk-content').textContent.includes('可读作品 new'));assert.equal(f.container.querySelector('.job-quote'),null);
  const failed=await fixture(url=>{if(url.includes('/generation-jobs/'))throw new Error('合成网络中断');return {sections:{job_attempts:{items:[{status:'succeeded',outputs:[]}]}}};});await failed.desk.load({projectId:'p',ref:'job:unread',embedded:true});assert.ok(failed.container.querySelector('.desk-content').textContent.includes('执行已结束，但尚无已登记结果'));assert.ok(failed.container.querySelector('.job-quote').textContent.includes('读取受阻'));
});

test('polling a completed preview without bytes stops at the gap and does not promise a returned result',async()=>{
  let finished=false;
  const job={status:'succeeded',explanation:'新预览已返回',
    output:{content_url:'/api/v1/projects/p/edit-previews/j/content'},
    result_availability:{status:'unavailable',message:'预览文件缺失，请恢复固定输出'}};
  const f=await fixture((url,options)=>{
    if(url.endsWith('edit-preview-requests'))return {revision:6,note_id:'n'};
    if(url.includes('edit-previews?')){finished=true;return {items:[job]};}
    if(url.includes('review-history?'))return {items:[{body:'字幕上移',source:{artifact_note_id:'n'},
      edit_previews:[finished?job:{status:'queued'}]}]};
    return basic(url,options);
  });
  await f.desk.load({projectId:'p'});const input=f.container.querySelector('textarea');input.value='字幕上移';await input.dispatch('input');
  await f.container.querySelector('.desk-opinion').dispatch('submit');
  // The existing form starts a background read after the durable history reload.
  await new Promise(resolve=>setImmediate(resolve));
  const feedback=f.container.querySelector('.desk-feedback');
  assert.equal(feedback.querySelector('video'),null);
  assert.ok(feedback.textContent.includes('预览文件缺失'));
  assert.ok(feedback.textContent.includes('执行：已结束'));
  assert.ok(!feedback.textContent.includes('执行：等待执行器'));
  assert.equal(feedback.querySelectorAll('.edit-preview-result').length,1);
  assert.ok(!feedback.textContent.includes('新预览已返回'));
  assert.ok(button(feedback,'重新读取本次结果'));
  f.desk.suspend();
});

test('late success and error from another project cannot replace current content',async()=>{
  const old=deferred();let fail=false;
  const f=await fixture(async(url,options)=>url.includes('/old/assisted-desk')?old.promise:basic(url,options));
  const pending=f.desk.load({projectId:'old'});await f.desk.load({projectId:'new'});old.resolve(page([{...rows[0],title:'旧内容'}]));await pending;
  assert.ok(!f.container.textContent.includes('旧内容'));
  const late=deferred(),g=await fixture((url,options)=>url.includes('/old/assisted-desk')?late.promise:basic(url,options));
  const rejected=g.desk.load({projectId:'old'});await g.desk.load({projectId:'new'});late.reject(new Error('旧错误'));await rejected;
  assert.ok(!g.container.textContent.includes('旧错误'));
});

test('draft survives switching objects and an uncertain retry keeps the exact request identity',async()=>{
  const writes=[];let first=true;
  const f=await fixture(async(url,options)=>{
    if(url.endsWith('edit-preview-requests')){writes.push(JSON.parse(options.body));if(first){first=false;throw new Error('连接中断');}return {revision:6,note_id:'note',status:'queued',explanation:'已登记'};}
    if(url.includes('edit-previews?'))return {items:[{status:'failed',error:'执行器未就绪'}]};
    return basic(url,options);
  });
  await f.desk.load({projectId:'p'});
  let input=f.container.querySelector('textarea');input.value='把这条字幕上移';await input.dispatch('input');
  await f.container.querySelector('.desk-queue').querySelectorAll('a')[1].click();
  await f.container.querySelector('.desk-queue').querySelectorAll('a')[0].click();
  input=f.container.querySelector('textarea');assert.equal(input.value,'把这条字幕上移');assert.equal(f.desk.hasDrafts(),true);
  let form=f.container.querySelector('.desk-opinion');await form.dispatch('submit');await form.dispatch('submit');
  assert.equal(writes.length,2);assert.equal(writes[0].idempotency_key,writes[1].idempotency_key);
  assert.deepEqual(writes[1].payload.target,{...target,start_frame:30,end_frame:60});
  assert.equal(writes[1].payload.caption_id,'cue');assert.equal(f.desk.hasDrafts(),false);
});

test('a newer opinion typed during an in-flight request is never cleared by its old success',async()=>{
  const pending=deferred();
  const f=await fixture((url,options)=>url.endsWith('edit-preview-requests')?pending.promise:basic(url,options));
  await f.desk.load({projectId:'p'});const input=f.container.querySelector('textarea');input.value='旧意见';await input.dispatch('input');
  const send=f.container.querySelector('.desk-opinion').dispatch('submit');input.value='继续编辑的新意见';await input.dispatch('input');
  pending.resolve({revision:6,explanation:'已保存旧意见'});await send;
  assert.equal(input.value,'继续编辑的新意见');assert.equal(f.desk.hasDrafts(),true);
});

test('read-only content offers no write form and untrusted markup remains text',async()=>{
  const f=await fixture(async(url,options)=>{const value=await basic(url,options);if(url.includes('/artifacts/'))value.document={正文:'<img src=x onerror=boom()>'};return value;},
    {actor:'human',writable:false});
  await f.desk.load({projectId:'p'});assert.equal(f.container.querySelector('textarea'),null);
  assert.ok(f.container.textContent.includes('此项目只读'));assert.equal(f.container.querySelectorAll('img').length,0);
});

test('read-only service does not promise login or creation, including an empty project list',async()=>{
  const f=await fixture(basic,{actor:null,writable:false,writeAvailable:false});
  await f.desk.load({projectId:'p'});
  assert.ok(f.container.textContent.includes('本次服务只读'));
  assert.equal(button(f.container,'登录后可提意见'),undefined);
  await f.desk.load({projectId:null,page:'projects'});
  assert.equal(button(f.container,'建立项目'),undefined);
  assert.equal(button(f.container,'先登录'),undefined);
  assert.ok(f.container.textContent.includes('还没有可浏览的项目'));
});

test('a fixed link to an old media document leads to results without rendering binary text',async()=>{
  const f=await fixture(async(url,options)=>{
    const value=await basic(url,options);
    if(url.includes('/artifacts/'))return {...value,mime_type:'video/mp4',content:'\0ftypisom binary'};
    return value;
  });
  await f.desk.load({projectId:'p'});
  assert.ok(!f.container.textContent.includes('ftypisom'));
  assert.ok(button(f.container,'打开已有结果'));
  await button(f.container,'打开已有结果').click();
  assert.ok(f.calls.some(call=>call.url.includes('bucket=results')));
});

test('empty projects provide creation and trash never claims freed bytes',async()=>{
  const f=await fixture(async url=>url.includes('/recycle?')?{revision:1,items:[],total:0}:basic(url));
  await f.desk.load({projectId:null,page:'projects'});assert.ok(button(f.container,'建立项目'));
  await f.desk.load({projectId:'p',page:'trash'});assert.ok(f.container.textContent.includes('0 字节'));assert.ok(f.container.textContent.includes('回收站是空的'));
});

test('project and trash navigation preserve their own reloadable URL without the previous work selection',async()=>{
  const routes=[];
  const f=await fixture(async(url,options)=>url.includes('/recycle?')?{revision:1,items:[],total:0}:basic(url,options));
  f.ctx.route=route=>routes.push(f.module.parseDeskLocation(f.module.deskLink(route)));
  await f.desk.load({projectId:'p'});
  assert.equal(routes.at(-1).object,'artifact:a');
  await f.desk.load({projectId:'p',page:'projects'});
  assert.equal(routes.at(-1).page,'projects');assert.equal(routes.at(-1).object,null);
  await f.desk.load({projectId:'p',page:'trash'});
  assert.equal(routes.at(-1).page,'trash');assert.equal(routes.at(-1).object,null);
});

test('durable returned preview is playable after reopening the original opinion',async()=>{
  const f=await fixture(async(url,options)=>{const value=await basic(url,options);if(url.includes('/artifacts/'))value.review_history={items:[{body:'上移字幕',source:{artifact_note_id:'n'},edit_previews:[{status:'succeeded',explanation:'请回看',output:{content_url:'/api/v1/projects/p/edit-previews/job/content'}}]}]};return value;});
  await f.desk.load({projectId:'p'});const videos=f.container.querySelector('.desk-feedback').querySelectorAll('video');
  assert.equal(videos.length,1);assert.equal(videos[0].src,'/api/v1/projects/p/edit-previews/job/content');
});

test('phone pane switches keep the exact player instance, position and unsent opinion',async()=>{
  const media={id:'clip',kind:'media',title:'合成片段',ref:{kind:'media',id:'clip'}};
  const f=await fixture(async(url,options)=>url.includes('assisted-desk?')?page([media]):url.includes('/media/clip')?{...artifact('clip'),modality:'video'}:basic(url,options));
  await f.desk.load({projectId:'p'});const player=f.container.querySelector('.desk-content').querySelector('video');
  player.currentTime=7;const input=f.container.querySelector('textarea');input.value='未提交意见';await input.dispatch('input');
  await button(f.container,'意见与结果').click();assert.equal(f.container.dataset.mobilePanel,'feedback');
  await button(f.container,'返回列表').click();assert.equal(f.container.dataset.mobilePanel,'list');
  await button(f.container,'作品').click();assert.equal(f.container.dataset.mobilePanel,'content');
  assert.equal(f.container.querySelector('.desk-content').querySelector('video'),player);
  assert.equal(player.currentTime,7);assert.equal(f.container.querySelector('textarea').value,'未提交意见');
});

test('batch preflight limits decisions to visible selected versions and preserves partial outcomes',async()=>{
  const writes=[],batchRows=rows.map(r=>({...r,status:'draft'}));
  const f=await fixture(async(url,options)=>{
    if(url.includes('assisted-desk?'))return page(batchRows);
    if(url.endsWith('/artifact-decisions')){const body=JSON.parse(options.body);writes.push(body);if(body.payload.artifact_id==='b')throw new Error('上游尚未批准');return {revision:6};}
    return basic(url,options);
  });
  await f.desk.load({projectId:'p'});
  for(const label of f.container.querySelectorAll('.desk-review-select')){const check=label.querySelector('input');check.checked=true;await check.dispatch('change');}
  await button(f.container,'审阅本页所选版本').click();assert.equal(f.container.dataset.mobilePanel,'feedback');
  const feedback=f.container.querySelector('.desk-feedback');feedback.querySelector('textarea').value='逐项核对所见版本';
  await button(feedback,'批准核对后的 2 个版本').click();
  assert.deepEqual(writes.map(w=>w.payload.artifact_id),['a','b']);
  assert.equal(writes[0].expected_revision,5);assert.equal(writes[1].expected_revision,6);
  assert.ok(feedback.textContent.includes('已批准此固定版本'));assert.ok(feedback.textContent.includes('上游尚未批准'));
  await button(feedback,'重试尚未完成的决定').click();
  assert.deepEqual(writes.map(w=>w.payload.artifact_id),['a','b','b']);assert.equal(writes[1].idempotency_key,writes[2].idempotency_key);
});

test('voice authorization reads durable receipts and resumes only the missing enqueue after reconnection',async()=>{
  const f=await fixture(basic),memory=new Map(),receipts=new Map(),writes=[];
  const key=++serial;globalThis.__deskTests.set(key,{document:f.document,crypto:{randomUUID:()=>`voice-${++serial}`}});
  const module=await import('data:text/javascript;base64,'+Buffer.from(`const {document,crypto}=globalThis.__deskTests.get(${key});\n`+fs.readFileSync(path.join(folder,'local-production.js'),'utf8')).toString('base64'));
  let fail=true;const api=async(url,options)=>{
    if(url.includes('options?'))return {purposes:['dialogue_dry']};
    if(url.endsWith('/preview'))return {revision:5,preview_sha256:'f'.repeat(64),targets:[{purpose:'dialogue_dry'}],
      artifact:{document:{operations:{one:{characters:8}}}},sources:[]};
    if(url.includes('/operation-receipts/')){const r=receipts.get(url.split('/').at(-1));return r?{found:true,response:r}:{found:false};}
    const body=JSON.parse(options.body);writes.push({url,body});
    const response=url.endsWith('local-production-proposals')?{revision:6,artifact:{id:'voice-plan'}}:
      url.endsWith('artifact-decisions')?{revision:7}:{revision:8,jobs:[{id:'voice-job'}]};
    receipts.set(body.idempotency_key,response);
    if(url.endsWith('artifact-decisions')&&fail){fail=false;throw new Error('响应丢失');}
    return response;
  };
  const ctx={api,project:()=> 'p',session:()=>({actor:'human',csrf:'secret'}),revision:()=>{},onArtifact:()=>{},
    receiptStore:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}};
  const dialog=f.document.createElement('dialog');dialog.showModal=()=>{};dialog.close=()=>{};await module.createLocalProduction(dialog,ctx).open('redo_sound',{shot_id:'shot'});
  await button(dialog,'预览目标与影响').click();await button(dialog,'按所见范围重做声音').click();
  const saved=JSON.parse([...memory.values()][0]);assert.equal(saved.payload,undefined);assert.ok(!JSON.stringify(saved).includes('secret'));assert.equal(writes.length,2);
  const recovered=f.document.createElement('dialog');recovered.showModal=()=>{};recovered.close=()=>{};await module.createLocalProduction(recovered,ctx).open('redo_sound',{shot_id:'shot'});
  await button(recovered,'继续已授权的制作').click();
  assert.equal(writes.length,3);assert.ok(writes[2].url.endsWith('local-production-enqueue'));
  assert.equal(writes[2].body.payload.artifact_id,'voice-plan');assert.equal(writes[2].body.expected_revision,7);
  assert.equal(memory.size,0);assert.ok(recovered.textContent.includes('已入队'));
});
