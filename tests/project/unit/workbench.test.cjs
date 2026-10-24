const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {Document}=require('../../support/fixtures/frontend/panel_dom.cjs');
function fixture(callbacks={}){
  const document=new Document(''),container=document.createElement('section');document.body.append(container);
  const memory=new Map(),requests=[],pending=[],opened=[],errors=[];
  const context=vm.createContext({document,URLSearchParams,AbortController,console,localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},fetch:(url,options)=>{requests.push({url,options});return new Promise(resolve=>pending.push(resolve));}});
  vm.runInContext(fs.readFileSync(path.join(process.env.VSC_TEST_ROOT,'src/vsc/interfaces/web/static/workbench.js'),'utf8').replace('export function createCreativeWorkbench','function createCreativeWorkbench'),context);
  const bench=context.createCreativeWorkbench(container,{onObject:id=>opened.push(['object',id]),onMedia:id=>opened.push(['media',id]),onArtifact:id=>opened.push(['artifact',id]),onGraph:id=>opened.push(['graph',id]),onError:error=>errors.push(error.message),...callbacks});
  const respond=(data,ok=true)=>{assert.ok(pending.length);pending.shift()({ok,json:async()=>data});};
  return {bench,container,memory,requests,pending,opened,errors,respond,find:text=>container.querySelectorAll('button').find(b=>b.textContent===text)};
}
function doc(project,section='lines',items=[],extra={}){return {project_id:project,revision:4,scope:{id:'shot-1',kind:'shot',title:'镜头一'},ancestors:[],summary:{[section]:items.length},sections:{[section]:{items,total:items.length,scope_total:items.length,next_offset:null}},gaps:[],warnings:[],read_only:true,...extra};}
test('professional stage keeps scope, catalogue browsing does not force a different take, and late old selection cannot route',async()=>{
  const calls=[],routed=[];const a=fixture({createReviewer:async(root,binding)=>{calls.push(binding);return {suspend(){}};},onStageRef:ref=>routed.push(ref)});
  let loading=a.bench.load({projectId:'p',objectId:'shot-1',task:'candidates'});a.respond(doc('p','bindings',[{id:'slot',object_id:'shot-1',kind:'video_take',purpose:'video_take',media_id:'original',status:'selected'}]));await loading;
  assert.equal(calls[0].ref,'media:original');assert.equal(calls[0].objectId,'shot-1');assert.equal(calls[0].targetObjectId,'shot-1');
  await a.find('返回资料与镜头').click();assert.equal(a.container.querySelector('.workbench-catalog').open,true);
  loading=a.find('相关素材').click();a.respond(doc('p','materials',[{id:'alternate',media_id:'alternate',title:'备选',kind:'video',status:'selected'}]));await loading;
  assert.equal(calls.length,1,'reading the catalogue must not silently switch the work stage');
  await a.find('预览素材').click();assert.equal(calls[1].ref,'media:alternate');
  const previous=calls[1];loading=a.bench.load({projectId:'other',objectId:'shot-2',task:'candidates'});a.respond(doc('other','bindings',[],{scope:{id:'shot-2',kind:'shot'}}));await loading;
  previous.onRef({kind:'media',id:'late'});assert.equal(routed.length,0);
});

test('binding library selection consumes the real read model aliases for target and purpose',async()=>{
  const uses=[],a=fixture({onLibrary:target=>uses.push(target)});let loading=a.bench.load({projectId:'p',objectId:'shot-1',task:'candidates'});
  a.respond(doc('p','bindings',[{id:'slot',object_id:'shot-1',kind:'first_frame',purpose:'first_frame',status:'unselected'}]));await loading;
  await a.find('从公共库选择用于此处').click();assert.equal(uses[0].target_object_id,'shot-1');assert.equal(uses[0].role,'first_frame');
});
test('scope is identified once in the breadcrumb while section buttons show the selection',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',objectId:'shot-1',userId:'alice'});a.respond(doc('p'));await p;
  const heading=a.container.querySelector('.workbench-heading');
  assert.equal(heading.querySelectorAll('h1').length,0);
  assert.equal(heading.querySelectorAll('p').length,0);
  const current=heading.querySelector('strong');assert.equal(current.textContent,'镜头一');
  assert.equal(current.getAttribute('aria-current'),'location');
  const ancestors=heading.querySelector('.workbench-ancestry');ancestors.open=true;await ancestors.dispatch('keydown',{key:'Escape'});assert.equal(ancestors.open,false);assert.equal(a.container.ownerDocument.activeElement,ancestors.querySelector('summary'));
  assert.equal(heading.textContent.split('镜头一').length-1,1);
  p=a.find('剧本与镜头').click();assert.equal(new URL(a.requests.at(-1).url,'http://fixture').searchParams.get('section'),'shots');
  a.respond(doc('p','shots',[{id:'shot-1',title:'镜头一'}]));await p;
  const buttons=a.container.querySelector('.workbench-navigation').querySelectorAll('button');
  assert.equal(buttons.find(b=>b.textContent==='镜头').getAttribute('aria-current'),'page');
  assert.equal(buttons.find(b=>b.textContent==='创作概览').getAttribute('aria-pressed'),'false');
  p=a.bench.load({projectId:'p',userId:'alice'});a.respond(doc('p','shots',[],{scope:null}));await p;
  assert.equal(heading.querySelector('strong').textContent,'项目创作概览');a.bench.destroy();
});
test('navigation removes duplicated counters and only exposes the selected material group',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',userId:'alice'});
  a.respond(doc('p','assets',[],{summary:{assets:800,versions:515}}));await p;
  assert.equal(a.container.querySelector('.workbench-counters'),null);
  assert.equal(a.container.querySelector('.workbench-nav-groups').querySelectorAll('button').length,5);
  assert.equal(a.container.querySelector('.workbench-nav-sections'),null);
  assert.equal(a.find('人物声线'),undefined);
  p=a.find('资产与表演').pressKey('Enter');await new Promise(setImmediate);a.respond(doc('p','assets'));await p;
  assert.deepEqual(a.container.querySelector('.workbench-nav-sections').querySelectorAll('button').map(b=>b.textContent),
    ['资产','使用与状态','人物声线','声音','动作与特效']);
  assert.equal(a.container.ownerDocument.activeElement.textContent,'资产与表演');
  assert.equal(a.find('资产与表演').getAttribute('aria-pressed'),'true');
  p=a.find('人物声线').pressKey(' ');await new Promise(setImmediate);a.respond(doc('p','voices'));await p;
  assert.equal(a.find('人物声线').getAttribute('aria-current'),'page');
  assert.equal(a.container.ownerDocument.activeElement.textContent,'人物声线');
  assert.equal(a.find('制作任务'),undefined);
  assert.ok(a.requests.every(r=>!r.options.method));a.bench.destroy();
});
test('candidate and delivery task entry points have bounded groups and separate remembered selections',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',userId:'alice',task:'candidates'});
  assert.equal(a.requests.length,1);
  assert.equal(new URL(a.requests.at(-1).url,'http://fixture').searchParams.get('section'),'bindings');
  a.respond(doc('p','bindings'));await p;
  assert.deepEqual(a.container.querySelector('.workbench-nav-groups').querySelectorAll('button').map(b=>b.textContent),
    ['候选与素材','任务与尝试','质量与方法']);
  assert.equal(a.find('创作概览'),undefined);assert.equal(a.find('镜头'),undefined);
  p=a.find('任务与尝试').click();a.respond(doc('p','jobs'));await p;
  p=a.find('任务尝试对照').click();a.respond(doc('p','job_attempts'));await p;
  p=a.bench.load({projectId:'p',userId:'alice',task:'delivery'});
  assert.equal(new URL(a.requests.at(-1).url,'http://fixture').searchParams.get('section'),'renders');
  a.respond(doc('p','renders'));await p;
  assert.equal(a.find('成片固定版本').getAttribute('aria-current'),'page');assert.ok(a.find('实际用料区间'));
  assert.equal(a.find('任务与尝试'),undefined);
  p=a.bench.load({projectId:'p',userId:'alice',task:'candidates'});
  assert.equal(new URL(a.requests.at(-1).url,'http://fixture').searchParams.get('section'),'job_attempts');
  a.respond(doc('p','job_attempts'));await p;
  assert.equal(a.find('任务尝试对照').getAttribute('aria-current'),'page');
  const count=a.requests.length;await a.find('任务与尝试').click();
  assert.equal(a.requests.length,count);assert.equal(a.find('任务尝试对照').getAttribute('aria-current'),'page');a.bench.destroy();
});
test('quality and relation drill-downs keep their parent and current collection selected',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',userId:'alice'});a.respond(doc('p'));await p;
  p=a.find('质量与方法').click();a.respond(doc('p','quality_observations'));await p;
  p=a.find('方法评测').click();a.respond(doc('p','method_evaluations'));await p;
  assert.equal(a.find('质量与方法').getAttribute('aria-pressed'),'true');
  assert.equal(a.find('方法评测').getAttribute('aria-current'),'page');
  p=a.bench.focus('coverage');a.respond(doc('p','coverage'));await p;
  assert.equal(a.find('剧本与镜头').getAttribute('aria-pressed'),'true');
  assert.equal(a.find('镜头覆盖').getAttribute('aria-current'),'page');a.bench.destroy();
});
test('late workbench response cannot restore another project, abort and errors preserve read-only state',async()=>{
  const a=fixture();const old=a.bench.load({projectId:'old',objectId:'old-shot',userId:'alice'});a.container.querySelectorAll('select').find(e=>e.getAttribute('aria-label')==='资料类型').value='dialogue';const fresh=a.bench.load({projectId:'new',objectId:'shot-1',userId:'alice'});
  const first=a.pending.shift();a.respond(doc('new','lines',[{id:'new-line',title:'new-private',text:'新内容'}]));await fresh;
  first({ok:true,json:async()=>doc('old','lines',[{id:'old-line',title:'stale-old'}])});await old;
  assert.ok(a.container.textContent.includes('new-private'));assert.ok(!a.container.textContent.includes('stale-old'));assert.equal(a.requests[0].options.signal.aborted,true);
  assert.equal(new URL(a.requests[1].url,'http://fixture').searchParams.has('kind'),false);
  const reload=a.bench.refresh();a.respond({message:'快照冲突'},false);await reload;
  assert.ok(a.container.textContent.includes('快照冲突'));assert.ok(a.find('重新读取当前范围'));assert.ok(a.requests.every(r=>!r.options.method));a.bench.destroy();
});
test('project aggregates expose on-demand collections without claiming they are empty',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',userId:'alice'});a.respond(doc('p','materials',[],{scope:null,summary:{materials:50000},sections:{materials:{items:[],total:50000,scope_total:50000,load_on_demand:true,next_offset:0,truncated:true}}}));await p;
  assert.ok(!a.container.textContent.includes('当前范围尚未登记创作资料'));assert.ok(a.container.textContent.includes('已登记 50000 项'));
  p=a.find('查看全部').click();assert.equal(new URL(a.requests.at(-1).url,'http://fixture').searchParams.get('section'),'materials');a.respond(doc('p','materials',[{id:'media-1',title:'第一页'}]));await p;
  assert.ok(a.container.textContent.includes('第一页'));a.bench.destroy();
});
test('full-scope search and version-pinned pagination cross loaded-page boundary',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',objectId:'shot-1',userId:'alice'});a.respond(doc('p'));await p;
  p=a.bench.focus('lines');a.respond(doc('p','lines',[{id:'line',title:'台词'}],{sections:{lines:{items:[{id:'line',title:'台词'}],total:25,scope_total:40,next_offset:24}}}));await p;
  p=a.find('下一页').click();let params=new URL(a.requests.at(-1).url,'http://fixture').searchParams;assert.equal(params.get('offset'),'24');assert.equal(params.get('revision'),'4');
  a.respond(doc('p','lines',[{id:'line25',title:'最后一条'}]));await p;
  const input=a.container.querySelectorAll('input').find(n=>n.type==='search'),whole=a.container.querySelectorAll('input').find(n=>n.type==='checkbox');input.value='未加载资料';whole.checked=true;
  p=a.container.querySelectorAll('form')[0].dispatch('submit');params=new URL(a.requests.at(-1).url,'http://fixture').searchParams;assert.equal(params.get('query'),'未加载资料');assert.equal(params.has('object_id'),false);assert.equal(params.get('offset'),'0');
  a.respond(doc('p','lines',[{id:'outside',title:'全范围命中'}]));await p;assert.ok(a.container.textContent.includes('全范围命中'));assert.ok(a.container.textContent.includes('全项目'));
  a.bench.destroy();
});
test('line coverage and media references use typed identities while text remains plain',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',userId:'alice'});a.respond(doc('p','lines',[{id:'line-7',title:'旁白',text:'<script>private-text</script>',artifact_id:'fixed-script'}]));await p;
  assert.equal(a.container.querySelectorAll('script').length,0);assert.ok(a.container.textContent.includes('<script>private-text</script>'));
  await a.find('阅读固定文案').click();assert.deepEqual(a.opened[0],['artifact','fixed-script']);
  p=a.find('查看覆盖镜头').click();const params=new URL(a.requests.at(-1).url,'http://fixture').searchParams;assert.equal(params.get('section'),'coverage');assert.equal(params.get('entity_id'),'line-7');
  a.respond(doc('p','coverage',[{id:'coverage-1',title:'覆盖镜头二',shot_id:'shot-2',line_id:'line-7',start_char:0,end_char:6}]));await p;
  await a.find('定位镜头').click();assert.deepEqual(a.opened.at(-1),['object','shot-2']);assert.ok(a.container.textContent.includes('文字起点'));
  p=a.bench.focus('materials');a.respond(doc('p','materials',[{id:'media-1',media_id:'media-1',title:'声音候选',duration_ms:4200}]));await p;
  await a.find('预览素材').click();assert.deepEqual(a.opened.at(-1),['media','media-1']);
  assert.ok([...a.memory.values()].every(v=>!v.includes('private-text')&&!v.includes('声音候选')&&!v.includes('revision')));a.bench.destroy();
});
test('shot and job drill buttons request their actual entity and show parameter evidence',async()=>{
  const a=fixture();let p=a.bench.load({projectId:'p',objectId:'shot-1',userId:'alice'});
  a.respond(doc('p','shots',[{id:'shot-1',kind:'shot',title:'镜头一'}]));await p;
  p=a.find('查看覆盖剧本行').click();let params=new URL(a.requests.at(-1).url,'http://fixture').searchParams;
  assert.equal(params.get('section'),'coverage');assert.equal(params.get('entity_id'),'shot-1');a.respond(doc('p','coverage'));await p;
  p=a.bench.focus('jobs');a.respond(doc('p','jobs',[{id:'job-1',title:'本镜声音'}]));await p;
  p=a.find('尝试与参数对照').click();params=new URL(a.requests.at(-1).url,'http://fixture').searchParams;
  assert.equal(params.get('section'),'job_attempts');assert.equal(params.get('entity_id'),'job-1');
  a.respond(doc('p','job_attempts',[{id:'job-1',title:'本镜声音',plan_params:{prompt:'固定台词',params:{seed:7}},
    performance_coverage:[{controls:[{field:'delivery',expected:['轻声且克制'],actual:['克制轻声'],consumed:false}]}],
    events:[{event:'succeeded',at:'now',evidence:{raw_response:{usage:{characters:4}},error:'原始错误说明'}}],outputs:[{media_id:'output-1'}]}]));await p;
  assert.ok(a.container.textContent.includes('固定制作参数'));assert.ok(a.container.textContent.includes('固定台词'));
  assert.ok(a.container.textContent.includes('原始错误说明'));assert.ok(a.container.textContent.includes('characters'));
  assert.ok(a.container.textContent.includes('要求值：轻声且克制'));assert.ok(a.container.textContent.includes('请求值：克制轻声'));
  await a.find('预览本次输出').click();assert.deepEqual(a.opened.at(-1),['media','output-1']);a.bench.destroy();
});
