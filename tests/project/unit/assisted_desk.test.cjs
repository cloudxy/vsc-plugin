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
