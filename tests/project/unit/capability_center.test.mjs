import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import {createCapabilityCenter,filterCapabilities,compatibleProject,capabilityHref} from '../../../src/vsc/interfaces/web/static/capability-center.js';
import {mountDiscovery} from '../../../src/vsc/interfaces/web/static/discovery.js';

const {Document,Element,createPanel}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;this.querySelector('button')?.focus();};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const repoRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const tick=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tool=(id='canvas',target={page:'creative-canvas',params:{skill:'asset-extraction'}},extra={})=>({id,source:'canvas',path:id,name:'剧本资产提取 '+id,kind:'canvas_skill',stages:['assets'],origin_stages:['assets'],task:'从 SCRIPT 整理人物',inputs:['剧本文字'],outputs:['资产清单'],suitable:['已有剧本'],unsuitable:['自动批准'],dependencies:[],installation:{state:'unknown',document:'present'},status:'entry_available',status_reason:'仅入口已登记',version:null,action:{type:'navigate',requires_project:true,target,label:'选择项目并打开画布'},related_documents:[],...extra});
const guide=(id='guide',source='tutorial')=>tool(id,null,{source,kind:source==='tutorial'?'tutorial':'external_method',name:'原文 '+id,status:'reference',action:{type:'read',requires_project:false,target:null,document_id:'doc_'+id,label:'阅读原文'}});
const envelope=(items=[],sources=null)=>({schema_version:1,status:'ok',items,sources:sources||[...new Set(items.map(i=>i.source))].map(id=>({id,status:'ok'}))});
const project=(id='p',extra={})=>({id,name:'软件测试项目 '+id,storage_policy:'postgres-series-v1',profile:'vsc.light-short',...extra});
const buttons=(root,label)=>root.querySelectorAll('button').filter(n=>n.textContent===label);
const find=(root,label)=>buttons(root,label)[0];

function setup({items=[tool(),guide()],api,storage=new Map(),projects=[project()],permissions=[{id:'p',capabilities:['read','edit']}],isCurrent=()=>true}={}){
 const document=new Document(''),root=document.createElement('main');document.body.append(root);globalThis.document=document;
 const listeners=new Map();globalThis.window={scrollY:77,scrollTo(_x,y){this.scrollY=y;},addEventListener:(k,v)=>listeners.set(k,v),removeEventListener:k=>listeners.delete(k)};
 Object.defineProperty(globalThis,'navigator',{value:{onLine:true},configurable:true});
 globalThis.sessionStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
 const session={actor:'test',identityId:'identity',workspaceId:'workspace',csrf:'csrf'},calls=[],routes=[];
 const ctx={session:()=>session,api:async(path,options)=>{calls.push({path,options});const value=await api?.(path,options);if(value!==undefined)return value;if(path.startsWith('/api/v1/discovery/capabilities'))return envelope(items);if(path==='/api/v1/discovery')return {projects:permissions};if(path==='/api/v1/projects')return {items:projects};const id=decodeURIComponent(path.split('/').at(-1));return {id,title:id,source:'tutorial',path:'registered.md',format:'text/plain',content:'# 实际正文 '+id};}};
 const center=createCapabilityCenter(root,ctx,{isCurrent,navigate:href=>routes.push(href)});
 const search=async value=>{const input=root.querySelector('#search');input.value=value;await input.dispatch('input');};
 const open=async id=>{await root.querySelectorAll('button').find(n=>n.dataset.capabilityId===id).click();return root.querySelector('#detail');};
 return {root,document,session,calls,routes,center,storage,listeners,search,open};
}

test('stage, kind and trimmed case-insensitive keyword intersect without truncating the directory',async()=>{
 const rows=Array.from({length:81},(_,i)=>tool('id'+i,undefined,{stages:i%2?['script']:['assets'],kind:i%3===0?'builtin_tool':'canvas_skill'}));
 assert.equal(filterCapabilities(rows,'  script  ','assets').length,41);
 assert.equal(filterCapabilities(rows,'  script  ','assets','builtin_tool').length,14);
 const h=setup({items:rows});await h.center.load();assert.equal(h.root.querySelectorAll('.capability-card').length,81);
 await h.search('  SCRIPT ');await find(h.root.querySelector('#stages'),'资产与连续性').click();assert.equal(h.root.querySelectorAll('.capability-card').length,41);assert.ok(h.root.querySelector('#count').textContent.includes('41 项能力'));
 await find(h.root.querySelector('#kinds'),'内置工具').click();assert.equal(h.root.querySelectorAll('.capability-card').length,14);
 await h.search('不存在');assert.ok(h.root.textContent.includes('未找到匹配能力'));await h.root.querySelector('#clear').click();assert.equal(h.root.querySelectorAll('.capability-card').length,81);
});

test('homepage discovery removes skills and tutorials while keeping recent creations and team templates',async()=>{
 const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;
 await mountDiscovery(root,{
  session:()=>({csrf:'csrf'}),
  api:async()=>({
   recent:[{id:'r1',title:'第一幕试拍',project_name:'雨夜剧场',href:'?page=creative-canvas&project=p1'}],
   templates:[{id:'t1',title:'竖屏悬疑模板',kind_label:'模板',href:'?page=projects'}],
   skills:[{id:'s1',name:'旧版首页技能'}],
   tutorials:[{id:'canvas',title:'旧版首页教程'}],
  }),
 });
 assert.ok(root.textContent.includes('最近创作'));
 assert.ok(root.textContent.includes('团队模板'));
 assert.ok(!root.textContent.includes('Skill 与教程'));
 assert.ok(!root.textContent.includes('旧版首页技能'));
 assert.ok(!root.textContent.includes('旧版首页教程'));
});

test('sidebar mounts 短剧能力中心 directly below 营销工作室 and standalone shell route works with zero projects',async()=>{
 const html=readFileSync(path.join(repoRoot,'src/vsc/interfaces/web/templates/index.html'),'utf8');
 assert.doesNotMatch(html,/style="/);
 assert.match(html,/href="\/static\/capability-center\.css"/);
 assert.match(html,/<div class="sidebar-marketing"><a id="nav-marketing-studio" href="\?page=marketing-studio">[\s\S]*?<span>营销工作室<\/span><small>NEW<\/small><\/a><a id="nav-capability-center" href="\?page=capability-center" title="短剧能力中心">[\s\S]*?<span>短剧能力中心<\/span><\/a><\/div>/);
 assert.match(html,/<section id="marketing-studio-view"[^>]*><\/section>\s*<section id="capability-center-view" tabindex="-1" aria-label="短剧能力中心" hidden><\/section>/);

 const location={pathname:'/capability-center',search:'',hash:''};
 const history={pushState(_a,_b,url){location.search=url;},replaceState(_a,_b,url){location.search=url;}};
 const win={location,history,scrollY:0,scrollTo(){},addEventListener(){},removeEventListener(){}};
 const fixture=createPanel(repoRoot,new Map(),null,{
  window:win,
  handleRequest:async url=>{
   if(url.startsWith('/api/v1/discovery/capabilities'))return envelope([tool('c1'),guide('g1')]);
  },
 });
 assert.equal(fixture.panel.resolvePathnameEntry('/capability-center','').get('page'),'capability-center');
 assert.equal(fixture.panel.resolvePathnameEntry('/capabilities','').get('page'),'capability-center');
 fixture.panel.applySession({actor:'creator',identity_id:'id-creator',workspace_id:'ws-1',csrf_token:'csrf',write_available:true});
 await fixture.panel.loadProjects();
 assert.equal(fixture.panel.state.view,'capability-center');
 assert.equal(fixture.panel.state.project,null);
 assert.equal(fixture.document.getElementById('capability-center-view').hidden,false);
 assert.equal(fixture.document.getElementById('nav-capability-center').getAttribute('aria-current'),'page');
 assert.equal(fixture.document.querySelector('.skip-link').href,'#capability-center-view');
 assert.ok(fixture.document.getElementById('capability-center-view').textContent.includes('短剧能力中心'));
 assert.equal(fixture.document.getElementById('capability-center-view').querySelectorAll('.capability-card').length,2);
 await fixture.panel.switchView('workbench');
 assert.equal(fixture.document.getElementById('capability-center-view').hidden,true);
 assert.equal(fixture.document.getElementById('capability-center-view').childElementCount,0);
});

test('loading, empty, forbidden, offline and source failures have distinct local states and retries',async()=>{
 const pause=deferred();let attempt=0;const h=setup({api:path=>path.includes('/capabilities')?(++attempt===1?pause.promise:envelope([], [{id:'canvas',status:'ok'}])):undefined});
 const pending=h.center.load();assert.ok(h.root.textContent.includes('正在读取能力目录'));assert.ok(!h.root.querySelector('#count').textContent.includes('0 项'));
 pause.reject(Object.assign(new Error('denied'),{status:403}));await pending;assert.ok(h.root.textContent.includes('查看权限'));await find(h.root,'重试读取目录').click();assert.ok(h.root.textContent.includes('当前没有已登记的短剧能力'));
 navigator.onLine=false;h.listeners.get('offline')();assert.ok(h.root.textContent.includes('网络连接已断开'));
});

test('source retry replaces only that source and a late full response cannot replace a newer source',async()=>{
 const full=deferred(),newest=tool('new'),kept=guide('kept');let fullCount=0;
 const h=setup({api:path=>path.includes('?source=canvas')?envelope([newest]):path.includes('/capabilities')?(++fullCount===1?envelope([tool('old'),kept],[{id:'canvas',status:'error'},{id:'tutorial',status:'ok'}]):full.promise):undefined});
 await h.center.load();const old=h.center.load();await h.center.load('canvas');full.resolve(envelope([tool('old'),kept]));await old;
 assert.equal(h.root.querySelectorAll('.capability-card').length,2);assert.ok(h.root.textContent.includes('new'));assert.ok(!h.root.textContent.includes('提取 old'));
 await h.center.load('canvas');assert.equal(h.root.querySelectorAll('.capability-card').length,2);
});

test('an older source failure cannot override a newer success and preserves current filters',async()=>{
 const slow=deferred();let n=0;const h=setup({api:path=>path.includes('?source=canvas')?(++n===1?slow.promise:envelope([tool('new')])):undefined});await h.center.load();const pending=h.center.load('canvas');await h.search('new');await h.center.load('canvas');slow.reject(new Error('old failure'));await pending;
 assert.equal(h.root.querySelectorAll('.capability-card').length,1);assert.equal(h.root.querySelector('#source-notice').hidden,true);assert.equal(h.root.querySelector('#search').value,'new');
});

for(const change of ['dispose','view','actor','identityId','workspaceId'])test(`late catalog results cannot write after ${change}`,async()=>{
 const pause=deferred();let active=true;const h=setup({api:path=>path.includes('/capabilities')?pause.promise:undefined,isCurrent:()=>active});const pending=h.center.load();
 if(change==='dispose')h.center.dispose();else if(change==='view')active=false;else h.session[change]='different';const before=h.root.textContent;pause.resolve(envelope([tool('late')]));await pending;assert.equal(h.root.textContent,before);assert.equal(h.routes.length,0);
});

test('external methods remain text-only and malicious source markup never creates elements',async()=>{
 const body='<img src=x onerror="globalThis.executed=true"><script>attack()</script>\n# 原文';const h=setup({items:[guide('external','vendor:inkos')],api:path=>path.includes('/documents/')?{id:'doc_external',format:'text/plain',content:body,source:'vendor:inkos',path:'method.md'}:undefined});await h.center.load();const detail=await h.open('external');
 assert.ok(detail.textContent.includes('方法参考'));assert.ok(!detail.textContent.includes('打开所选项目'));await detail.querySelector('.cc-primary').click();const doc=h.root.querySelector('#document');assert.equal(doc.querySelector('pre').textContent,body);assert.equal(doc.querySelector('img'),null);assert.equal(doc.querySelector('script'),null);assert.equal(h.routes.length,0);assert.ok(h.calls.every(c=>!c.options.method));
});

for(const fails of [false,true])test(`closed and replaced documents reject late ${fails?'failure':'success'} and restore focus`,async()=>{
 const pause=deferred(),h=setup({items:[guide('a'),guide('b')],api:path=>path.endsWith('/doc_a')?pause.promise:undefined});await h.center.load();let detail=await h.open('a');const pending=detail.querySelector('.cc-primary').click();await tick();await h.root.querySelector('#document').dispatch('cancel');await detail.dispatch('cancel');detail=await h.open('b');await detail.querySelector('.cc-primary').click();const before=h.root.querySelector('#document').textContent,focus=h.document.activeElement;
 if(fails)pause.reject(new Error('late'));else pause.resolve({id:'doc_a',format:'text/plain',content:'late a'});await pending;assert.equal(h.root.querySelector('#document').textContent,before);assert.equal(h.document.activeElement,focus);
 await h.root.querySelector('#document').dispatch('cancel');assert.equal(detail.open,true);assert.equal(h.document.activeElement,detail.querySelector('.cc-primary'));await detail.dispatch('cancel');assert.equal(h.document.activeElement.dataset.capabilityId,'b');
});

test('blank document is an error and retry keeps the same identity',async()=>{
 let read=0;const h=setup({items:[guide('a')],api:path=>path.includes('/documents/')?{id:'doc_a',format:'text/plain',content:++read===1?' ':'真实原文'}:undefined});await h.center.load();const detail=await h.open('a');await detail.querySelector('.cc-primary').click();assert.ok(h.root.querySelector('#document').textContent.includes('教程暂时无法读取'));await find(h.root.querySelector('#document'),'重试读取教程').click();assert.equal(h.root.querySelector('#document').querySelector('pre').textContent,'真实原文');
});

test('all guides article back and Escape restore rebuilt list and real trigger focus',async()=>{
 const h=setup({items:[guide('a'),guide('b'),guide('c')]});await h.center.load();await h.root.querySelector('#all-docs').click();let list=h.root.querySelector('#document');await list.querySelectorAll('button').find(n=>n.dataset.documentId==='doc_b').click();await list.dispatch('cancel');assert.equal(list.open,true);assert.equal(h.document.activeElement.dataset.documentId,'doc_b');assert.equal(list.querySelectorAll('button').filter(n=>n.dataset.documentId).length,3);await list.dispatch('cancel');assert.equal(list.open,false);assert.equal(h.document.activeElement.id,'all-docs');
});

test('only compatible current edit targets are selectable and loss of edit never navigates',async()=>{
 let reads=0;const h=setup({projects:[project(),project('readonly'),project('creative',{profile:'vsc.creative-tools'})],api:path=>path==='/api/v1/discovery'?{projects:++reads===1?[{id:'p',capabilities:['edit']},{id:'readonly',capabilities:['read']},{id:'creative',capabilities:['edit']}]:[{id:'p',capabilities:['read']}]}:undefined});
 await h.center.load();const detail=await h.open('canvas');await detail.querySelector('.cc-primary').click();const picker=h.root.querySelector('#project');assert.equal(picker.querySelectorAll('input').length,1);await picker.querySelector('.cc-primary').click();assert.ok(picker.textContent.includes('失去编辑权限'));assert.equal(h.routes.length,0);assert.ok(h.calls.every(c=>!c.options.method));
});

test('picker loading, failure and no compatible targets remain distinct; cancel survives pending confirmation',async()=>{
 const pendingPermissions=deferred();let permissionReads=0;const h=setup({api:path=>path==='/api/v1/discovery'&&++permissionReads===2?pendingPermissions.promise:undefined});await h.center.load();const detail=await h.open('canvas');await detail.querySelector('.cc-primary').click();const picker=h.root.querySelector('#project'),confirm=picker.querySelector('.cc-primary');const pending=confirm.click();await tick();assert.equal(confirm.disabled,true);await confirm.click();assert.equal(permissionReads,2);await picker.dispatch('cancel');assert.equal(h.document.activeElement,detail.querySelector('.cc-primary'));pendingPermissions.resolve({projects:[{id:'p',capabilities:['edit']}]});await pending;assert.equal(h.routes.length,0);assert.equal(picker.open,false);
 const empty=setup({projects:[project('text',{profile:'vsc.text-tools'})],permissions:[{id:'text',capabilities:['edit']}]});await empty.center.load();const d=await empty.open('canvas');await d.querySelector('.cc-primary').click();assert.ok(empty.root.querySelector('#project').textContent.includes('暂无可编辑项目'));assert.equal(empty.root.querySelector('#project').querySelector('a').href,'/?page=project-management');
 const fail=setup({api:path=>path==='/api/v1/discovery'?Promise.reject(new Error('unavailable')):undefined});await fail.center.load();await (await fail.open('canvas')).querySelector('.cc-primary').click();assert.ok(fail.root.querySelector('#project').textContent.includes('暂时无法读取'));assert.ok(!fail.root.querySelector('#project').textContent.includes('暂无可编辑项目'));
});

for(const reject of [false,true])test(`cancelled A picker cannot adopt late ${reject?'failure':'success'} in B`,async()=>{
 const pause=deferred();let reads=0;const h=setup({items:[tool('a'),tool('b')],api:path=>path==='/api/v1/discovery'&&++reads===1?pause.promise:undefined});await h.center.load();let detail=await h.open('a');const pending=detail.querySelector('.cc-primary').click();await tick();await h.root.querySelector('#project').dispatch('cancel');await detail.dispatch('cancel');detail=await h.open('b');await detail.querySelector('.cc-primary').click();const before=h.root.querySelector('#project').textContent,focus=h.document.activeElement;if(reject)pause.reject(new Error('late'));else pause.resolve({projects:[{id:'p',capabilities:['edit']}]});await pending;assert.equal(h.root.querySelector('#project').textContent,before);assert.equal(h.document.activeElement,focus);assert.equal(h.routes.length,0);
});

test('browser-return remount restores filters and detail but rechecks directory and never changes an absent identity',async()=>{
 const storage=new Map(),h=setup({storage});await h.center.load();await h.search(' SCRIPT ');await find(h.root.querySelector('#stages'),'资产与连续性').click();await h.open('canvas');h.center.dispose();const next=setup({storage});await next.center.load();assert.equal(next.root.querySelector('#search').value,' SCRIPT ');assert.equal(next.root.querySelector('#detail').open,true);assert.ok(next.root.querySelector('#detail').textContent.includes('canvas'));
 next.center.dispose();const missing=setup({storage,items:[tool('other')]});await missing.center.load();assert.ok(missing.root.querySelector('#detail').textContent.includes('此能力已不在当前目录'));assert.equal(missing.routes.length,0);
});

test('storage denial never blocks browsing and removed triggers fall back to search',async()=>{
 const h=setup();globalThis.sessionStorage={getItem(){throw new Error('denied');},setItem(){throw new Error('denied');}};await h.center.load();const d=await h.open('canvas');await h.search('no match');await d.dispatch('cancel');assert.equal(h.document.activeElement.id,'search');h.center.dispose();assert.equal(h.listeners.size,0);
});

test('all 14 native destinations and canvas identity survive actual shell route synchronization',async()=>{
 const targets=[...['novel','translation','scoring','breakdown','qc','overseas'].map(tool=>({page:'text-tools',params:{tool}})),...['image','video'].map(kind=>({page:'classic-production',params:{kind}})),{page:'intelligent-creation',params:{}},...['segment_remake','breakdown'].map(tool=>({page:'creative-tools',params:{tool}})),...['marketing-studio','editing','delivery'].map(page=>({page,params:{}}))];assert.equal(targets.length,14);
 targets.push({page:'creative-canvas',params:{skill:'asset-extraction'}});const source=readFileSync(new URL('../../../src/vsc/interfaces/web/static/panel.js',import.meta.url),'utf8'),sync=source.slice(source.indexOf('function syncRoute(){'),source.indexOf('async function openResourceSettings()'));
 for(const target of targets){const row=tool('native',target,{kind:target.page==='creative-canvas'?'canvas_skill':'builtin_tool'}),href=capabilityHref(row,'project & id');assert.ok(href);const location={search:href.slice(1)},state={view:target.page,project:'project & id',object:null};const history={pushState(_a,_b,url){location.search=url;},replaceState(_a,_b,url){location.search=url;}};const context={state,window:{location,history},URLSearchParams,currentEntry:()=>new URLSearchParams(location.search),episodeScope:null,restoringDeskRoute:false,deskRouteReady:true,updateShell(){}};vm.runInNewContext(sync+';globalThis.sync=syncRoute;',context);context.sync();const route=new URLSearchParams(location.search);assert.equal(route.get('project'),'project & id');for(const [key,value]of Object.entries(target.params))assert.equal(route.get(key),value);}
 assert.equal(capabilityHref(guide('external','vendor:inkos'),'p'),null);assert.equal(capabilityHref(tool('bad',{page:'https://evil',params:{}}),'p'),null);
});

test('real selection rechecks edit and emits one original-consumer navigation without POST',async()=>{
 const h=setup();await h.center.load();await (await h.open('canvas')).querySelector('.cc-primary').click();await h.root.querySelector('#project').querySelector('.cc-primary').click();assert.equal(h.routes.length,1);assert.deepEqual(Object.fromEntries(new URLSearchParams(h.routes[0].split('?')[1])),{page:'creative-canvas',project:'p',skill:'asset-extraction'});assert.equal(h.calls.filter(c=>c.path==='/api/v1/discovery').length,2);assert.ok(h.calls.every(c=>!c.options.method));
 assert.equal(compatibleProject(project('legacy',{storage_policy:'filesystem'}),{page:'text-tools'}),false);assert.equal(compatibleProject(project('text',{profile:'vsc.text-tools'}),{page:'text-tools'}),true);assert.equal(compatibleProject(project('creative',{profile:'vsc.creative-tools'}),{page:'text-tools'}),false);assert.equal(compatibleProject(project('text',{profile:'vsc.text-tools'}),{page:'editing'}),false);
});

test('text tools require an existing text workspace instead of an arbitrary production project',async()=>{
 assert.equal(compatibleProject(project(),{page:'text-tools'}),false);
 const row=tool('novel',{page:'text-tools',params:{tool:'novel'}},{kind:'builtin_tool'});
 const h=setup({items:[row],projects:[project(),project('text',{profile:'vsc.text-tools'})],permissions:[{id:'p',capabilities:['edit']},{id:'text',capabilities:['edit']}]});
 await h.center.load();await (await h.open('novel')).querySelector('.cc-primary').click();const picker=h.root.querySelector('#project');assert.equal(picker.querySelectorAll('input').length,1);assert.equal(picker.querySelector('input').value,'text');
 await picker.querySelector('.cc-primary').click();assert.equal(new URLSearchParams(h.routes[0].split('?')[1]).get('project'),'text');
});
