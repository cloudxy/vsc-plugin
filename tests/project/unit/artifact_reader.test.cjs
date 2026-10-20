const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createPanel} = require('../../support/fixtures/frontend/panel_dom.cjs');
const root = process.env.VSC_TEST_ROOT;
const deferred = () => { let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject}; };
const project = (id, extra={}) => ({project:{id,name:id,storage_policy:'legacy-json',read_only:true},revision:5,
  nodes:[{id:'scene',kind:'scene',title:'场次',parent_id:null}],artifacts:[],artifactDetails:{},...extra});
const item = (app,id) => app.document.getElementById('artifacts').querySelectorAll('.artifact-item').find(row=>row.dataset.id===id);
const reader = app => app.document.getElementById('document');
const actions = app => app.document.getElementById('artifact-actions');
async function start(projects,options={}) {
  const app=createPanel(root,projects,null,options);app.panel.state.view='artifacts';await app.panel.selectProject('A');return app;
}
const button = (node,text) => node.querySelectorAll('button').find(control=>control.textContent===text);

test('real panel lists PG and legacy friendly names without fetching each document, then reads every JSON value safely',async()=>{
  const deep={};let tail=deep;for(let i=0;i<12;i++){tail.next={};tail=tail.next;}tail.last='最深处仍完整';
  const data=project('A',{artifacts:[
    {id:'pg',artifact_type:'shot-plan',artifact_key:'shot-plan',version:3,current:true,approved:false},
    {id:'legacy',type:'vsc.screenplay',name:'长篇剧本-v2.json',status:'approved'},
    {id:'english',artifact_type:'new-kind',artifact_key:'dialogue_draft'},
  ],artifactDetails:{pg:{id:'pg',title:'镜头与动作',artifact_type:'shot-plan',version:3,approved:false,
    document:JSON.stringify({title:'镜头计划',description:'<script>untrusted()</script>',enabled:false,count:0,missing:null,
      empty:'',empty_list:[],empty_object:{},unknown_field:{nested_array:[false,0,null,{final:'最后字段'}]},deep,
      shots:Array.from({length:81},(_,i)=>({text:`完整镜头 ${i}`}))})}}});
  const app=await start(new Map([['A',data]]));
  assert.equal(item(app,'pg').querySelector('.artifact-title').textContent,'镜头计划');
  assert.match(item(app,'pg').textContent,/v3 · 待决定 · 当前版本/);
  assert.equal(item(app,'legacy').querySelector('.artifact-title').textContent,'长篇剧本 v2');
  assert.equal(item(app,'english').querySelector('.artifact-title').textContent,'dialogue draft');
  assert.equal(app.requests.filter(url=>/\/artifacts\//.test(url)).length,0);
  await item(app,'pg').pressKey('Enter');
  assert.equal(item(app,'pg').getAttribute('aria-current'),'true');
  assert.equal(item(app,'pg').getAttribute('aria-pressed'),'true');
  assert.equal(item(app,'pg').getAttribute('aria-controls'),'document');
  assert.equal(reader(app).getAttribute('aria-labelledby'),item(app,'pg').id);
  assert.equal(item(app,'pg').querySelector('.artifact-title').textContent,'镜头与动作');
  for(const text of ['否（false）','0','未填写（null）','空文本（""）','空列表（[]）','空对象（{}）','unknown_field','最后字段','最深处仍完整','完整镜头 80','<script>untrusted()</script>'])assert.ok(reader(app).textContent.includes(text),text);
  assert.equal(reader(app).querySelector('header'),null);
  assert.equal(reader(app).querySelector('pre'),null);
  assert.equal(reader(app).querySelector('script'),null);
  assert.equal(reader(app).children[0].className,'document-content');
  assert.equal(reader(app).querySelector('details').querySelector('summary').textContent,'版本与核验');
});

test('plain text and primitive JSON are readable without dropping zero, false or null',async()=>{
  const data=project('A',{artifacts:[{id:'literal',type:'vsc.screenplay'}],artifactDetails:{literal:{id:'literal',content:'第一行\n\n第二行 <img src=x>'}}});
  const app=await start(new Map([['A',data]]));
  await item(app,'literal').click();assert.ok(reader(app).querySelector('.readable').textContent.includes('第一行\n\n第二行 <img src=x>'));
  for(const [content,text] of [[0,'0'],[false,'否（false）'],[null,'未填写（null）'],['null','未填写（null）']]){
    data.artifactDetails.literal.content=content;await app.panel.openArtifact('literal');
    assert.equal(reader(app).querySelector('.document-value').textContent,text);
  }
});

test('large plain and structured text read in explicit chunks without losing the final characters',async()=>{
  const text='可读长文\n'.repeat(10000)+'末尾验收文字';
  const data=project('A',{artifactDetails:{long:{id:'long',content:text}}});
  const app=await start(new Map([['A',data]]));
  for(const content of [text,JSON.stringify({正文:text})]){
    data.artifactDetails.long.content=content;await app.panel.openArtifact('long');
    assert.ok(reader(app).textContent.length<20000);
    assert.ok(!reader(app).textContent.includes('末尾验收文字'));
    while(reader(app).querySelector('.document-more'))await reader(app).querySelector('.document-more').pressKey('Enter');
    const chunks=reader(app).querySelectorAll(typeof content==='string'&&content===text?'.readable':'.document-value');
    assert.equal(chunks.map(row=>row.textContent).join(''),text);
  }
});

test('media artifacts never render decoded binary bytes as document text',async()=>{
  const data=project('A',{artifactDetails:{clip:{id:'clip',content:'\0\0ftypisom undecodable media',mime_type:'video/mp4'}}});
  const app=await start(new Map([['A',data]]));await app.panel.openArtifact('clip');
  assert.ok(reader(app).textContent.includes('这份资料是视频'));
  assert.ok(!reader(app).textContent.includes('ftypisom'));
  assert.ok(button(reader(app),'查看项目素材'));
});

test('server read-only overrides a writable project while valid sessions retain project restrictions',async()=>{
  const editable=project('A',{project:{id:'A',name:'A',storage_policy:'postgres-series-v1',read_only:false}});
  const app=await start(new Map([['A',editable],['B',project('B')]]));
  await app.panel.loadProjects();
  app.panel.applySession({actor:null,csrf_token:null,write_available:false});
  await app.panel.selectProject('A');
  assert.equal(app.panel.state.writable,false);
  assert.equal(app.document.getElementById('session-label').textContent,'只读浏览');
  assert.equal(app.document.getElementById('session-open').disabled,true);
  app.panel.applySession({actor:'human',csrf_token:'csrf',write_available:true});
  assert.equal(app.panel.state.writable,true);
  assert.equal(app.document.getElementById('session-open').disabled,false);
  assert.equal(app.document.getElementById('upload-open').disabled,false);
  await app.panel.selectProject('B');assert.equal(app.panel.state.writable,false);
  await app.panel.selectProject('A');assert.equal(app.panel.state.writable,true);
});

test('a document title takes precedence over an internal artifact key',async()=>{
  const data=project('A',{artifacts:[{id:'named',artifact_key:'reader-0'}],artifactDetails:{named:{id:'named',artifact_type:'screenplay',
    artifact_key:'reader-0',content:{title:'可读剧本标题',scenes:[]}}}});
  const app=await start(new Map([['A',data]]));
  await app.panel.openArtifact('named');
  assert.equal(item(app,'named').querySelector('.artifact-title').textContent,'可读剧本标题');
});

test('technical keys use known type titles and unapproved new drafts never appear as historical',async()=>{
  const rows=[
    {id:'brief',artifact_key:'vsc.creative_brief',artifact_type:'vsc.creative_brief'},
    {id:'contract',artifact_key:'02153212-1234-4321-9999-123456789abc',artifact_type:'vsc.adaptation_contract'},
    {id:'bible',artifact_key:'a'.repeat(64),artifact_type:'vsc.story_bible'},
    {id:'quality',artifact_key:'ART-0003',artifact_type:'vsc.quality_plan'},
    {id:'title-uuid',title:'02153212-1234-4321-9999-123456789abc',artifact_type:'vsc.screenplay'},
    {id:'key-uuid',artifact_key:'artifact-02153212-1234-4321-9999-123456789abc',artifact_type:'vsc.screenplay'},
    {id:'draft',artifact_key:'draft',artifact_type:'vsc.screenplay',version:4,current:false,approved:false},
    {id:'history',artifact_type:'vsc.screenplay',version:3,current:false,approved:true},
  ];
  const app=await start(new Map([['A',project('A',{artifacts:rows})]]));
  for(const [id,title] of [['brief','创作委托'],['contract','改编约定'],['bible','故事设定'],['quality','质量计划'],['title-uuid','剧本'],['key-uuid','剧本']])assert.equal(item(app,id).querySelector('.artifact-title').textContent,title);
  assert.ok(!item(app,'draft').textContent.includes('历史版本'));assert.ok(item(app,'history').textContent.includes('历史版本'));
});

test('legacy unloaded envelopes differ from actual JSON null, with missing warnings retained',async()=>{
  const data=project('A',{artifactDetails:{large:{id:'large',content:null,availability:'available',size_bytes:16*1024*1024+1},
    absent:{id:'absent',content:null,availability:'missing',size_bytes:null},
    literal:{id:'literal',content:'null',availability:'available',size_bytes:4}}});
  const app=await start(new Map([['A',data]]));await app.panel.openArtifact('large');
  assert.match(reader(app).textContent,/正文超过内置阅读限额/);assert.ok(!reader(app).textContent.includes('未填写（null）'));
  await app.panel.openArtifact('absent');assert.match(reader(app).textContent,/内容缺失/);assert.match(reader(app).textContent,/正文未载入/);
  assert.ok(!reader(app).textContent.includes('未填写（null）'));
  await app.panel.openArtifact('literal');assert.equal(reader(app).querySelector('.document-value').textContent,'未填写（null）');
});

test('a failed initial artifact list displays a local retry and late list failures cannot overwrite a new project',async()=>{
  let attempts=0;
  const projects=new Map([['A',project('A')],['B',project('B',{artifacts:[{id:'right',artifact_type:'vsc.screenplay'}]})]]);
  const app=createPanel(root,projects,null,{handleRequest:url=>{
    if(url.endsWith('/A/artifacts')){attempts++;if(attempts===1)throw new Error('临时断开');return {items:[{id:'retried',artifact_type:'vsc.creative_brief'}]};}
  }});
  await app.panel.selectProject('A');await app.document.getElementById('tab-artifacts').click();
  const list=app.document.getElementById('artifacts');assert.match(list.textContent,/文案版本读取失败：临时断开/);
  assert.ok(!list.textContent.includes('正在读取'));assert.equal(list.getAttribute('aria-busy'),'false');
  await button(list,'重新读取文案版本').click();assert.equal(attempts,2);assert.ok(item(app,'retried'));
  assert.equal(list.getAttribute('aria-busy'),'false');assert.equal(app.document.getElementById('notice').textContent,'');
  const pending=deferred();let delay=false;
  const late=await start(projects,{handleRequest:url=>delay&&url.endsWith('/A/artifacts')?pending.promise:undefined});
  delay=true;const loading=late.panel.loadArtifacts();await late.panel.selectProject('B');pending.reject(new Error('旧项目迟到错误'));await loading;
  assert.ok(item(late,'right'));assert.ok(!late.document.getElementById('artifacts').textContent.includes('旧项目'));
  assert.equal(late.document.getElementById('notice').textContent,'');
  assert.equal(late.document.getElementById('artifacts').getAttribute('aria-busy'),'false');
});

test('creative brief template fields use Chinese reading labels while their values stay literal',async()=>{
  const brief=require('node:fs').readFileSync(root+'/templates/creative-brief.json','utf8');
  const app=await start(new Map([['A',project('A',{artifactDetails:{brief:{id:'brief',content:brief}}})]]));
  await app.panel.openArtifact('brief');
  const labels=reader(app).querySelectorAll('dt').map(row=>row.textContent);
  for(const text of ['期望体验','决策负责人','冲突处理','创作目标','不可更改要求','目标','达成依据'])assert.ok(labels.includes(text),text);
  assert.ok(reader(app).textContent.includes('牺牲高优先目标前交由 decision_owner 决定'));
});

test('keyboard activation focuses a loaded reader; mouse activation and delayed requests do not steal focus',async()=>{
  const pending=deferred();const rows=Array.from({length:45},(_,i)=>({id:'doc-'+i,artifact_type:'vsc.screenplay'}));
  const data=project('A',{artifacts:rows,artifactDetails:{'doc-0':{id:'doc-0',content:'正文'}}});
  const app=await start(new Map([['A',data]]),{handleRequest:url=>url.endsWith('/artifacts/doc-1')?pending.promise:undefined});
  await item(app,'doc-0').click();assert.equal(app.document.activeElement,item(app,'doc-0'));
  await item(app,'doc-0').pressKey('Enter');assert.equal(app.document.activeElement,reader(app));
  const late=item(app,'doc-1').pressKey('Enter');await Promise.resolve();app.document.getElementById('projects').focus();
  pending.resolve({id:'doc-1',content:'迟到正文'});await late;assert.equal(app.document.activeElement.id,'projects');
  const stale=deferred();const second=await start(new Map([['A',data],['B',project('B')]]),{handleRequest:url=>url.endsWith('/artifacts/doc-1')?stale.promise:undefined});
  const opening=item(second,'doc-1').pressKey('Enter');await Promise.resolve();await second.panel.selectProject('B');second.document.getElementById('projects').focus();
  stale.resolve({id:'doc-1',content:'错误项目正文'});await opening;
  assert.equal(second.document.activeElement.id,'projects');assert.ok(!reader(second).textContent.includes('错误项目正文'));
});

test('large JSON arrays render beyond the JavaScript argument limit without dropping the last item',async()=>{
  const values=Array(130001).fill(0);values[130000]='大数组最后一项';
  const data=project('A',{artifactDetails:{large:{id:'large',document:JSON.stringify(values)}}});
  const app=await start(new Map([['A',data]]));await app.panel.openArtifact('large');
  const list=reader(app).children[0].children[0];assert.equal(list.children.length,130001);
  assert.equal(list.children[130000].children[0].textContent,'大数组最后一项');
});

test('scope changes invalidate pending detail and list responses through actual panel consumers',async()=>{
  const detail=deferred(),list=deferred();let delayList=false;
  const data=project('A',{artifacts:[{id:'old',type:'vsc.screenplay'}]});
  const app=await start(new Map([['A',data]]),{handleRequest:async url=>{
    if(url.endsWith('/artifacts/old'))return detail.promise;
    if(url.endsWith('/artifacts')&&delayList)return list.promise;
    if(url.endsWith('/artifacts?object_id=scene'))return {items:[{id:'new',artifact_key:'new_document'}]};
  }});
  const opening=item(app,'old').click();delayList=true;const listing=app.panel.loadArtifacts();
  await app.panel.selectObject('scene');
  detail.resolve({id:'old',content:'错误范围正文'});list.resolve({items:[{id:'wrong',type:'wrong'}]});await Promise.all([opening,listing]);
  assert.equal(app.panel.state.selectedArtifact,null);
  assert.equal(reader(app).getAttribute('aria-busy'),'false');
  assert.equal(reader(app).getAttribute('aria-labelledby'),null);
  assert.ok(!reader(app).textContent.includes('错误范围正文'));
  assert.equal(item(app,'wrong'),undefined);assert.ok(item(app,'new'));
  assert.equal(app.document.getElementById('artifacts').getAttribute('aria-busy'),'false');
});

test('switching scope immediately removes controls belonging to the prior scope while the new list loads',async()=>{
  const next=deferred();const data=project('A',{artifacts:[{id:'old'}]});
  const app=await start(new Map([['A',data]]),{handleRequest:url=>url.endsWith('/artifacts?object_id=scene')?next.promise:undefined});
  const changing=app.panel.selectObject('scene');assert.equal(item(app,'old'),undefined);
  assert.ok(app.document.getElementById('artifacts').textContent.includes('正在读取'));
  next.resolve({items:[]});await changing;
  assert.ok(app.document.getElementById('artifacts').textContent.includes('此范围未建立'));
});

test('latest document and project selection win, including a late request failure',async()=>{
  const old=deferred();const data=project('A',{artifacts:[{id:'old'},{id:'new'}],artifactDetails:{new:{id:'new',content:'最新正文'}}});
  const app=await start(new Map([['A',data],['B',project('B')]]),{handleRequest:url=>url.endsWith('/artifacts/old')?old.promise:undefined});
  const opening=item(app,'old').click();await item(app,'new').click();old.reject(new Error('过期失败'));await opening;
  assert.ok(reader(app).textContent.includes('最新正文'));assert.equal(app.document.getElementById('notice').textContent,'');
  assert.equal(item(app,'old').getAttribute('aria-pressed'),'false');assert.equal(item(app,'new').getAttribute('aria-pressed'),'true');
  const other=deferred();const second=await start(new Map([['A',data],['B',project('B')]]),{handleRequest:url=>url.endsWith('/artifacts/old')?other.promise:undefined});
  const late=second.panel.openArtifact('old');await second.panel.selectProject('B');other.resolve({id:'old',content:'旧项目正文'});await late;
  assert.equal(second.panel.state.project,'B');assert.ok(!reader(second).textContent.includes('旧项目正文'));
  assert.equal(reader(second).getAttribute('data-artifact-id'),null);
});

test('version decisions retain session, confirmation, fixed revision and stale-control checks',async()=>{
  const data=project('A',{artifactDetails:{fixed:{id:'fixed',content:'所见文案',revision:37,approved:false}}});
  const app=await start(new Map([['A',data]]));Object.assign(app.panel.state,{writeAvailable:true,writable:true});await app.panel.openArtifact('fixed');
  let approve=button(actions(app),'批准所见版本');
  assert.equal(approve.disabled,true);await approve.click();assert.equal(app.writes.length,0);
  assert.match(actions(app).textContent,/登录实际操作人/);
  app.panel.state.actor='human';app.panel.state.csrf='csrf';app.panel.state.revision=999;
  await app.panel.openArtifact('fixed');approve=button(actions(app),'批准所见版本');actions(app).querySelector('input').value='已阅读所见版本';
  await approve.click();assert.equal(app.writes.length,1);
  const write=app.writes[0];assert.equal(write.url,'/api/v1/projects/A/artifact-decisions');
  assert.deepEqual(write.body.payload,{artifact_id:'fixed',outcome:'approve',reason:'已阅读所见版本'});
  assert.equal(write.body.expected_revision,37);assert.equal(write.headers['X-CSRF-Token'],'csrf');
  assert.equal(write.body.confirmed,true);assert.ok(write.body.idempotency_key);
  assert.ok(app.confirmations.length>=1);
  const reject=button(actions(app),'退回此版本');actions(app).querySelector('input').value='调整对白';
  await reject.click();assert.equal(app.writes[1].body.payload.outcome,'reject');
  assert.match(app.document.getElementById('notice').textContent,/退回决定已记录/);
  const stale=button(actions(app),'批准所见版本');actions(app).querySelector('input').value='过时决定';
  await app.panel.selectObject('scene');await stale.click();assert.equal(app.writes.length,2);
  assert.match(app.document.getElementById('notice').textContent,/范围或所见版本已切换/);
});

test('a pending decision cannot reopen an old document after another version is selected',async()=>{
  const write=deferred();const data=project('A',{artifactDetails:{fixed:{id:'fixed',content:'旧正文',revision:37},next:{id:'next',content:'现在阅读'}}});
  const app=await start(new Map([['A',data]]),{handleRequest:(url,options)=>options.method==='POST'?write.promise:undefined});
  Object.assign(app.panel.state,{writeAvailable:true,writable:true,actor:'human',csrf:'csrf'});await app.panel.openArtifact('fixed');
  actions(app).querySelector('input').value='本人决定';const approve=button(actions(app),'批准所见版本');const pending=approve.click();
  assert.equal(approve.disabled,true);await approve.click();
  await app.panel.openArtifact('next');write.resolve({revision:38});await pending;
  assert.equal(app.writes.length,1);assert.ok(reader(app).textContent.includes('现在阅读'));
  assert.equal(app.requests.filter(url=>url.endsWith('/artifacts/fixed')).length,1);
});

test('after approving a fixed version, the selected list entry reflects its new detail status',async()=>{
  const data=project('A',{artifacts:[{id:'fixed',artifact_key:'vsc.screenplay',version:2,current:false,approved:false}],
    artifactDetails:{fixed:{id:'fixed',artifact_key:'vsc.screenplay',version:2,current:false,approved:false,revision:37,document:'正文'}}});
  const app=await start(new Map([['A',data]]),{handleRequest:(_url,options)=>{
    if(options.method==='POST'){data.artifactDetails.fixed.approved=true;data.artifactDetails.fixed.current=true;return {revision:38};}
  }});
  Object.assign(app.panel.state,{writeAvailable:true,writable:true,actor:'human',csrf:'csrf'});await item(app,'fixed').click();
  actions(app).querySelector('input').value='本人确认';await button(actions(app),'批准所见版本').click();
  assert.match(item(app,'fixed').textContent,/v2 · 已批准 · 当前版本/);
  assert.equal(button(actions(app),'批准所见版本'),undefined);
  assert.equal(item(app,'fixed').getAttribute('aria-current'),'true');
});

test('approved local plans retain exact-version enqueue and visible integrity warnings',async()=>{
  const data=project('A',{artifactDetails:{plan:{id:'plan',document:JSON.stringify({local_action:'redo_sound',targets:[{id:'shot'}]}),revision:72,approved:true,integrity:'mismatch',availability:'missing'}}});
  const app=await start(new Map([['A',data]]));Object.assign(app.panel.state,{writeAvailable:true,writable:true,actor:'human',csrf:'csrf'});await app.panel.openArtifact('plan');
  assert.match(reader(app).textContent,/文件摘要变化/);assert.match(reader(app).textContent,/内容缺失/);
  assert.equal(actions(app).querySelector('input'),null);
  assert.equal(button(actions(app),'将已批准的局部方案入队').disabled,true);
  await button(actions(app),'将已批准的局部方案入队').click();assert.equal(app.writes.length,0);
  data.artifactDetails.plan.integrity='verified';data.artifactDetails.plan.availability='available';
  await app.panel.openArtifact('plan');
  await button(actions(app),'将已批准的局部方案入队').click();
  assert.equal(app.writes[0].url,'/api/v1/projects/A/local-production-enqueue');
  assert.deepEqual(app.writes[0].body.payload,{artifact_id:'plan'});assert.equal(app.writes[0].body.expected_revision,72);
  const denied=await start(new Map([['A',data]]),{confirm:()=>false});Object.assign(denied.panel.state,{writeAvailable:true,writable:true,actor:'human'});
  await denied.panel.openArtifact('plan');await button(actions(denied),'将已批准的局部方案入队').click();assert.equal(denied.writes.length,0);
});

test('version inspection exposes the latest persisted decision and its reason',async()=>{
  const data=project('A',{artifactDetails:{fixed:{id:'fixed',content:'文案',version:2,revision:7,
    decisions:[{outcome:'approve',reason:'旧意见'},{outcome:'reject',reason:'需要调整末尾对白'}]}}});
  const app=await start(new Map([['A',data]]));await app.panel.openArtifact('fixed');
  await button(actions(app),'核对版本').click();
  const evidence=reader(app).querySelector('.artifact-evidence');
  assert.match(evidence.textContent,/最近决定：退回。理由：需要调整末尾对白/);
  assert.ok(!evidence.textContent.includes('旧意见'));
});

test('read-only artifacts retain visible review actions, an explicit reason and usable version inspection',async()=>{
  const data=project('A',{artifactDetails:{fixed:{id:'fixed',content:'长正文'.repeat(2000),revision:37,version:2,sha256:'a'.repeat(64)}}});
  const app=await start(new Map([['A',data]]));await app.panel.openArtifact('fixed');
  const bar=actions(app);
  assert.equal(bar.hidden,false);assert.equal(reader(app).querySelector('.artifact-decisions'),null);
  assert.equal(button(bar,'批准所见版本').className,'artifact-approve');
  assert.equal(button(bar,'退回此版本').className,'artifact-reject');
  assert.equal(button(bar,'核对版本').className,'artifact-inspect');
  assert.match(bar.textContent,/只读模式/);
  for(const label of ['批准所见版本','退回此版本']){
    assert.equal(button(bar,label).disabled,true);await button(bar,label).click();
  }
  assert.equal(app.writes.length,0);
  await button(bar,'核对版本').pressKey('Enter');
  const evidence=reader(app).querySelector('.artifact-evidence');
  assert.equal(evidence.open,true);assert.equal(app.document.activeElement,evidence.querySelector('summary'));
  assert.match(evidence.textContent,/v2/);assert.ok(evidence.textContent.includes('a'.repeat(64)));
  await app.panel.selectObject('scene');assert.equal(bar.hidden,true);assert.equal(bar.childElementCount,0);
});

test('changing or failing to load a version removes all stale fixed action controls',async()=>{
  const late=deferred();
  const data=project('A',{artifactDetails:{old:{id:'old',content:'旧稿',revision:37}}});
  const app=await start(new Map([['A',data]]),{handleRequest:url=>url.endsWith('/artifacts/broken')?late.promise:undefined});
  Object.assign(app.panel.state,{writeAvailable:true,writable:true,actor:'human',csrf:'csrf'});
  await app.panel.openArtifact('old');actions(app).querySelector('input').value='旧决定';
  const old=button(actions(app),'批准所见版本');
  const pending=app.panel.openArtifact('broken');
  assert.equal(actions(app).hidden,true);assert.equal(actions(app).childElementCount,0);
  await old.click();assert.equal(app.writes.length,0);
  late.reject(new Error('读取失败'));await assert.rejects(pending,/读取失败/);
  assert.equal(actions(app).hidden,true);
});

test('logging in from the version reader enables review of that same selected version',async()=>{
  const data=project('A',{project:{id:'A',name:'A',storage_policy:'postgres-series-v1'},
    artifacts:[{id:'fixed'}],artifactDetails:{fixed:{id:'fixed',content:'当前稿',revision:37}}});
  const app=await start(new Map([['A',data]]),{handleRequest:(url,options)=>
    url==='/api/v1/session'&&options.method==='POST'?{actor:'human',csrf_token:'new-csrf',write_available:true}:undefined});
  await app.panel.loadProjects();
  app.panel.applySession({actor:null,write_available:true});await app.panel.openArtifact('fixed');
  await button(actions(app),'登录后审核').click();
  assert.equal(app.document.getElementById('session-dialog').open,true);
  app.document.getElementById('session-token').value='synthetic-test-token';
  await app.document.getElementById('session-form').dispatch('submit');
  assert.equal(app.document.getElementById('session-dialog').open,false);
  assert.equal(app.panel.state.selectedArtifact,'fixed');
  assert.equal(button(actions(app),'批准所见版本').disabled,false);
  assert.ok(actions(app).querySelector('input'));
  assert.equal(app.writes.length,1);assert.equal(app.writes[0].url,'/api/v1/session');
});
