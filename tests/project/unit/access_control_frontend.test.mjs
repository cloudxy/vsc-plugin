import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {createAccessControl} from '../../../src/vsc/interfaces/web/static/access-control.js';
const {Document,Element}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
Object.defineProperty(Element.prototype,'isConnected',{get(){for(let n=this;n;n=n.parentElement)if(n===this.ownerDocument.body)return true;return false;}});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=()=>new Promise(setImmediate);
const button=(h,text)=>h.root.querySelectorAll('button').find(node=>node.textContent===text);
const input=(h,label)=>h.root.querySelectorAll('input').find(node=>node.getAttribute('aria-label')===label);
const select=(h,label)=>h.root.querySelectorAll('select').find(node=>node.getAttribute('aria-label')===label);
const click=async(h,text)=>{const node=button(h,text);assert.ok(node,'missing button '+text+' in '+h.root.textContent);await node.onclick();};
const project=(id,workspace,name=id)=>({id,workspace_id:workspace,name,capabilities:['read','edit','manage','publish'],review_lanes:[]});
function setup({workspace='team-a',identity=true,hook}={}){
 const document=new Document(''),root=document.createElement('main');document.body.append(root);globalThis.document=document;globalThis.crypto??=webcrypto;globalThis.window={addEventListener(){},removeEventListener(){}};
 const memory=new Map();globalThis.sessionStorage={getItem:key=>memory.get(key)||null,setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)};
 globalThis.location={href:'http://fixture/?page=access',origin:'http://fixture'};globalThis.history={replaceState(){}};
 let current={actor:identity?'alice':null,workspaceId:workspace,csrf:'csrf'},switched=workspace;
 const calls=[],notices=[],sessions=[],navigations=[],data={identity:{id:'alice-id',actor:'alice',display_name:'Alice',preferences:{}},access_revision:8,credentials:[],workspaces:[{id:'personal',name:'Alice 的个人归属',kind:'personal',created_by:'alice-id',owner_name:'Alice',owner_actor:'alice',roles:['owner'],manageable:true,project_count:1},{id:'team-a',name:'甲团队',kind:'studio',roles:['owner'],manageable:true,project_count:1},{id:'team-b',name:'乙团队',kind:'studio',roles:['owner'],manageable:true,project_count:1},{id:'child-a',name:'甲团队下级',kind:'substudio',parent_id:'team-a',roles:['owner'],manageable:true,project_count:0}],projects:[project('p-a','team-a','甲项目'),project('p-b','team-b','乙项目'),project('p-personal','personal','个人项目')],members:[],invitations:[],shares:[]};
 const ctx={session:()=>current,notice:value=>notices.push(String(value)),onSession:async value=>{sessions.push(value);current={...current,...value};},navigate:(...args)=>navigations.push(args),api:async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):undefined,call={url,options,body};calls.push(call);const override=await hook?.(call,{data,current});if(override!==undefined)return override;
  if(url==='/api/v1/authentication/options')return {enabled:false,channels:[],providers:[]};
  if(url==='/api/v1/authentication/bindings')return {items:[]};
  if(url==='/api/v1/access'){if(!identity)throw Object.assign(Error('sign in'),{status:403});return structuredClone(data);}
  if(url==='/api/v1/access/switch-workspace'){switched=body.workspace_id;return {workspace_id:switched};}
  if(url==='/api/v1/session')return {...current,workspaceId:switched};
  if(url.includes('/resources?'))return {items:[],total:0,next_offset:null};
  if(url==='/api/v1/access/invitation-preview')return {scope:'project',scope_id:'p-b',target_name:'乙项目',role:'editor',expires_at:'2026-12-01T00:00:00Z',project_id:'p-b'};
  if(url==='/api/v1/access/join')return {...current,joined_project_id:'p-b',target_name:'乙项目',role:'editor'};
  if(url.includes('/member-removal-preview'))return {sha256:'remove-sha',plan:{workspace_id:'team-a',display_name:'Bob',effect:'Bob 将失去甲团队角色；以下项目直接授权保留。',retained_project_grants:[{project_id:'p-a',project_name:'甲项目',role:'editor',can_revoke:true}]}};
  if(url.includes('/access-migration-preview'))return {sha256:'move-sha',plan:{from_workspace_id:'team-a',to_workspace_id:body.workspace_id,effect:'项目内容与历史记录保持原样',access_changes:[{display_name:'Bob',before_roles:['editor'],after_roles:[],change:'lost'},{display_name:'Carol',before_roles:[],after_roles:['viewer'],change:'gained'}],retained_direct_grants:[{display_name:'Dana',role:'owner'}],shares:[{canvas_title:'甲画布',mode:'edit',expires_at:'2026-12-01T00:00:00Z'}]}};
  const canvases=url.match(/^\/api\/v1\/projects\/([^/]+)\/creative-canvases$/);if(canvases)return {items:[{id:'c-'+canvases[1],title:canvases[1]+'画布',current_version_id:'v-'+canvases[1]}]};
  const canvas=url.match(/^\/api\/v1\/projects\/([^/]+)\/creative-canvases\/([^/]+)$/);if(canvas)return {id:canvas[2],title:canvas[1]+'画布',version_id:'v-'+canvas[1],canvas_revision:3};
  if(url.endsWith('/commands/workspace'))data.workspaces.push({id:'team-new',name:body.payload.name,kind:'studio',roles:['owner'],manageable:true,project_count:0});
  if(url.includes('/commands/')){data.access_revision++;return {access_revision:data.access_revision,workspace_id:'team-new'};}
  throw Error('unexpected '+url);
 }};
 const panel=createAccessControl(root,ctx);return {root,panel,ctx,data,calls,notices,sessions,navigations,current:()=>current,posts:()=>calls.filter(call=>call.options.method==='POST')};
}

test('explicit task area renders only its controls and retains accessible navigation',async()=>{
 const h=setup();await h.panel.load({area:'account'});assert.equal(h.root.querySelector('h1').textContent,'账户设置');assert.ok(input(h,'显示名称'));assert.equal(input(h,'新团队名称'),undefined);assert.equal(h.calls.some(c=>c.url.includes('/resources?')||c.url.includes('creative-canvases')),false);
 assert.equal(h.root.querySelector('nav').getAttribute('aria-label'),'账户与团队分区');await click(h,'团队与项目归属');assert.equal(h.root.querySelector('h1').textContent,'团队与项目归属');assert.ok(input(h,'新团队名称'));assert.equal(select(h,'当前空间'),undefined);assert.match(h.root.textContent,/个人 · Alice/);assert.match(h.root.textContent,/账户注销后，项目归属及历史记录继续保留/);assert.doesNotMatch(h.root.textContent,/当前空间|未归属/);h.panel.suspend();
});

test('personal workspace hides new workspace invitations but project invitations stay available',async()=>{
 const h=setup({workspace:'personal'});h.data.members=[{workspace_id:'personal',identity_id:'legacy',display_name:'历史成员',scope_name:'个人空间',role:'viewer',active:true}];await h.panel.load({area:'members',team:'personal'});assert.equal(button(h,'创建一次邀请'),undefined);assert.match(h.root.textContent,/已有成员记录保留/);assert.match(h.root.textContent,/历史成员/);
 await h.panel.load({area:'members',project:'p-personal'});assert.deepEqual(select(h,'成员所属范围').options.map(o=>o.value),['project:p-personal']);await click(h,'创建一次邀请');const call=h.posts().find(c=>c.url.endsWith('/commands/invitation'));assert.equal(call.body.payload.scope,'project');assert.equal(call.body.payload.scope_id,'p-personal');assert.equal(call.body.payload.role,'editor');h.panel.suspend();
});

test('creating a team displays its details without changing the session or repeating the command',async()=>{
 const waiting=deferred();const h=setup({hook:async c=>{if(c.url.endsWith('/commands/workspace'))return waiting.promise;}});await h.panel.load({area:'workspace'});const name=input(h,'新团队名称');name.value='新团队';name.oninput();const b=button(h,'创建团队'),first=b.onclick();await settle();await b.onclick();assert.equal(h.posts().filter(c=>c.url.endsWith('/commands/workspace')).length,1);h.data.workspaces.push({id:'team-new',name:'新团队',kind:'studio',roles:['owner'],manageable:true,project_count:0});waiting.resolve({workspace_id:'team-new',access_revision:9});await first;assert.equal(h.current().workspaceId,'team-a');assert.equal(h.sessions.length,0);assert.equal(h.calls.some(c=>c.url.includes('switch-workspace')),false);assert.equal(select(h,'要管理的团队').value,'team-new');assert.match(h.root.textContent,/团队 · 新团队/);h.panel.suspend();
});

test('successful team creation survives detail read failure without creating another team',async()=>{
 let committed=false,fail=true;const h=setup({hook:async c=>{if(c.url.endsWith('/commands/workspace'))committed=true;if(c.url==='/api/v1/access'&&committed&&fail){fail=false;throw Error('detail offline');}}});await h.panel.load({area:'workspace'});const name=input(h,'新团队名称');name.value='保留团队';name.oninput();await click(h,'创建团队');assert.ok(h.notices.includes('detail offline'));await click(h,'创建团队');assert.equal(h.posts().filter(c=>c.url.endsWith('/commands/workspace')).length,1);assert.equal(h.current().workspaceId,'team-a');assert.equal(h.sessions.length,0);assert.equal(select(h,'要管理的团队').value,'team-new');h.panel.suspend();
});

test('invitation preview defaults to current identity and joins the named project',async()=>{
 const h=setup();await h.panel.load({area:'workspace',invite:'invite-one'});await settle();assert.match(h.root.textContent,/项目 · 乙项目/);assert.match(h.root.textContent,/加入角色：编辑成员/);assert.equal(select(h,'加入时使用的账户').value,'current');assert.equal(input(h,'新账户显示名称').parentElement.hidden,true);await click(h,'确认接受此邀请');const call=h.posts().find(c=>c.url.endsWith('/join'));assert.equal(call.body.use_current_identity,true);assert.equal(call.body.display_name,'Alice');assert.equal(h.root.querySelector('h1').textContent,'项目协作者');assert.deepEqual(select(h,'成员所属范围').options.map(o=>o.value),['project:p-b']);assert.equal(h.navigations.length,0);h.panel.suspend();
});

test('changed invitation credentials invalidate approval and late preview cannot re-enable join',async()=>{
 const old=deferred();const h=setup({hook:async c=>{if(c.url.endsWith('/invitation-preview'))return old.promise;}});await h.panel.load({invite:'old'});const token=input(h,'邀请链接中的凭据');token.value='new';token.oninput();old.resolve({scope:'project',target_name:'旧项目',role:'owner'});await settle();assert.equal(button(h,'确认接受此邀请').disabled,true);assert.doesNotMatch(h.root.textContent,/旧项目/);await click(h,'确认接受此邀请');assert.equal(h.posts().some(c=>c.url.endsWith('/join')),false);h.panel.suspend();
});

test('expired invitation keeps the user at preview and creates no identity',async()=>{
 const h=setup({hook:async c=>{if(c.url.endsWith('/invitation-preview'))throw Object.assign(Error('邀请已过期'),{status:410});}});await h.panel.load({invite:'expired'});await settle();assert.match(h.root.textContent,/邀请已过期/);assert.equal(button(h,'确认接受此邀请').disabled,true);assert.equal(h.posts().some(c=>c.url.endsWith('/join')),false);h.panel.suspend();
});

for(const revoke of [false,true])test(`team removal shows named retained grants and sends explicit revoke=${revoke}`,async()=>{
 const h=setup();h.data.members=[{workspace_id:'team-a',identity_id:'bob',display_name:'Bob',scope_name:'甲团队',role:'editor',active:true},{workspace_id:'team-b',identity_id:'outside',display_name:'Outside',scope_name:'乙团队',role:'viewer',active:true}];await h.panel.load({area:'members'});assert.doesNotMatch(h.root.textContent,/Outside/);await click(h,'移除此成员前预览');assert.equal(h.posts().some(c=>c.url.endsWith('/commands/member')),false);assert.match(h.root.textContent,/甲项目 · 保留 编辑成员/);const checkbox=input(h,'同时撤销以上可撤销的项目直接授权');assert.equal(checkbox.checked,false);checkbox.checked=revoke;await click(h,'确认移除此团队成员');const call=h.posts().find(c=>c.url.endsWith('/commands/member'));assert.deepEqual(call.body.payload,{scope:'workspace',scope_id:'team-a',identity_id:'bob',role:'editor',active:false,preview_sha256:'remove-sha',revoke_project_access:revoke});h.panel.suspend();
});

test('migration renders actual named access and links, and target changes discard its confirmation',async()=>{
 const h=setup();await h.panel.load({area:'workspace'});const destination=select(h,'目标归属');destination.value='team-b';await click(h,'预览归属变化');assert.match(h.root.textContent,/Bob · 失去访问/);assert.match(h.root.textContent,/Carol · 新增访问/);assert.match(h.root.textContent,/保留项目直接授权：Dana/);assert.match(h.root.textContent,/甲画布 · 实时画布协作/);destination.value='personal';destination.onchange();assert.equal(button(h,'确认按此预览迁移'),undefined);assert.equal(h.posts().some(c=>c.url.endsWith('/commands/assign-project')),false);h.panel.suspend();
});

test('sharing is scoped to the requested canvas and explains fixed versus later editable content',async()=>{
 const h=setup();h.data.shares=[{id:'old-link',project_id:'p-a',canvas_id:'c-p-a',canvas_version_id:'v-old',canvas_title:'甲画布旧版',mode:'edit',expires_at:'2026-12-01'},{id:'outside-link',project_id:'p-b',canvas_id:'c-p-b',canvas_title:'不可混入的乙画布',mode:'view',expires_at:'2026-12-01'}];await h.panel.load({area:'share',project:'p-a',canvas:'c-p-a'});await settle();assert.deepEqual(select(h,'分享项目').options.map(o=>o.value),['p-a']);assert.match(h.root.textContent,/甲画布旧版 · 实时画布协作/);assert.doesNotMatch(h.root.textContent,/不可混入的乙画布/);assert.match(h.root.textContent,/不包含此画布后续修改或新增内容/);const mode=select(h,'分享方式');mode.value='edit';mode.onchange();assert.match(h.root.textContent,/包含此画布后续新增的文字与媒体/);assert.match(h.root.textContent,/关闭项目成员协作不会撤销此链接/);await click(h,'创建分享链接');const call=h.posts().find(c=>c.url.endsWith('/commands/share'));assert.equal(call.body.payload.project_id,'p-a');assert.equal(call.body.payload.canvas_version_id,'v-p-a');assert.equal(call.body.payload.mode,'edit');h.panel.suspend();
});

test('late canvas load cannot populate a newer task scope',async()=>{
 const old=deferred();const h=setup({hook:async c=>{if(c.url==='/api/v1/projects/p-a/creative-canvases')return old.promise;}});await h.panel.load({area:'share',project:'p-a'});await h.panel.load({area:'members',project:'p-b'});old.resolve({items:[{id:'stale',title:'旧画布'}]});await settle();assert.equal(h.root.querySelector('h1').textContent,'项目协作者');assert.equal(select(h,'要分享的画布'),undefined);assert.equal(h.calls.some(c=>c.url.endsWith('/creative-canvases/stale')),false);h.panel.suspend();
});

test('unknown mutation outcome recovers the original request and retains later unsaved inputs',async()=>{
 let failed=false;const h=setup({hook:async c=>{if(c.url.endsWith('/commands/invitation')&&!failed){failed=true;throw Error('response lost');}}});await h.panel.load({area:'members',project:'p-a'});const expiry=input(h,'邀请有效期（含时区）');await click(h,'创建一次邀请');const first=h.posts().find(c=>c.url.endsWith('/commands/invitation'));expiry.value='2027-01-01T00:00:00Z';expiry.oninput();await click(h,'恢复未确认请求');const posts=h.posts().filter(c=>c.url.endsWith('/commands/invitation'));assert.equal(posts.length,2);assert.deepEqual(posts[1].body,first.body);assert.equal(input(h,'邀请有效期（含时区）').value,'2027-01-01T00:00:00Z');assert.match(h.root.textContent,/已恢复原请求/);assert.ok(h.root.querySelectorAll('textarea').some(node=>node.value.includes('#invite=')));h.panel.suspend();
});

test('team invitation opens target members without a current-space switch',async()=>{
 const h=setup({hook:async c=>{if(c.url.endsWith('/join'))return {actor:'alice',csrf:'new-csrf',workspaceId:'personal',joined_workspace_id:'team-b',joined_project_id:null,target_name:'乙团队'};}});await h.panel.load({invite:'team-invite'});await settle();await click(h,'确认接受此邀请');assert.equal(select(h,'成员所属范围').value,'workspace:team-b');assert.equal(h.calls.some(c=>c.url.includes('switch-workspace')),false);assert.equal(h.navigations.length,0);h.panel.suspend();
});

test('uncertain invitation acceptance retries the same credential and blocks changing account',async()=>{
 let fail=true;const h=setup({hook:async c=>{if(c.url.endsWith('/join')&&fail){fail=false;throw Error('join response lost');}}});await h.panel.load({invite:'join-uncertain'});await settle();await click(h,'确认接受此邀请');const choice=select(h,'加入时使用的账户');choice.value='new';choice.onchange();await click(h,'确认接受此邀请');assert.equal(h.posts().filter(c=>c.url.endsWith('/join')).length,1);choice.value='current';choice.onchange();await click(h,'确认接受此邀请');const calls=h.posts().filter(c=>c.url.endsWith('/join'));assert.equal(calls.length,2);assert.deepEqual(calls[0].body,calls[1].body);h.panel.suspend();
});

test('late migration preview does not restore confirmation after target changes',async()=>{
 const preview=deferred();const h=setup({hook:async c=>{if(c.url.endsWith('/access-migration-preview'))return preview.promise;}});await h.panel.load({area:'workspace'});const destination=select(h,'目标归属');destination.value='team-b';const loading=click(h,'预览归属变化');await settle();destination.value='personal';destination.onchange();preview.resolve({sha256:'stale',plan:{from_workspace_id:'team-a',to_workspace_id:'team-b',effect:'旧影响'}});await loading;assert.doesNotMatch(h.root.textContent,/旧影响/);assert.equal(button(h,'确认按此预览迁移'),undefined);h.panel.suspend();
});

test('completed share keeps its receipt when the selected mode changes during submission',async()=>{
 const saved=deferred();let first=true;const h=setup({hook:async c=>{if(c.url.endsWith('/commands/share')&&first){first=false;return saved.promise;}}});await h.panel.load({area:'share',project:'p-a',canvas:'c-p-a'});await settle();const creating=click(h,'创建分享链接');await settle();const mode=select(h,'分享方式');mode.value='edit';mode.onchange();saved.resolve({access_revision:9});await creating;assert.equal(h.root.querySelectorAll('textarea').length,0);await click(h,'恢复未确认请求');await settle();assert.ok(h.root.querySelectorAll('textarea').some(node=>node.value.includes('#share=')));await click(h,'创建分享链接');const calls=h.posts().filter(c=>c.url.endsWith('/commands/share'));assert.equal(calls.length,2);assert.notEqual(calls[0].body.payload.secret,calls[1].body.payload.secret);assert.equal(calls[1].body.payload.mode,'edit');h.panel.suspend();
});

test('team management selection only changes its view and shares still include every authorized project',async()=>{
 const h=setup(),switches=[];h.ctx.switchWorkspace=async id=>switches.push(id);await h.panel.load({area:'workspace'});const team=select(h,'要管理的团队');team.value='team-b';await team.onchange();assert.equal(select(h,'要管理的团队').value,'team-b');assert.match(h.root.textContent,/团队 · 乙团队/);assert.deepEqual(switches,[]);assert.equal(h.sessions.length,0);assert.equal(h.posts().length,0);assert.equal(h.current().workspaceId,'team-a');await h.panel.load({area:'share',team:'team-b'});await settle();assert.deepEqual(select(h,'分享项目').options.map(o=>o.value),['p-a','p-b','p-personal']);h.panel.suspend();
});

test('a late forbidden snapshot cannot erase a newer task snapshot',async()=>{
 const old=deferred();let reads=0;const h=setup({hook:async c=>{if(c.url==='/api/v1/access'&&++reads===1)return old.promise;}});const loading=h.panel.load({area:'account'});await settle();await h.panel.load({area:'members',project:'p-b'});old.reject(Object.assign(Error('old forbidden'),{status:403}));await loading;await click(h,'账户设置');assert.ok(input(h,'显示名称'));assert.doesNotMatch(h.root.textContent,/old forbidden/);h.panel.suspend();
});

test('share success with refresh failure recovers its link without resending the share command',async()=>{
 let committed=false,failRefresh=true;const h=setup({hook:async c=>{if(c.url.endsWith('/commands/share'))committed=true;if(c.url==='/api/v1/access'&&committed&&failRefresh){failRefresh=false;throw Error('readback offline');}}});await h.panel.load({area:'share',project:'p-a',canvas:'c-p-a'});await settle();await click(h,'创建分享链接');assert.ok(h.notices.includes('readback offline'));assert.ok(h.root.querySelectorAll('textarea').some(node=>node.value.includes('#share=')));await click(h,'恢复未确认请求');await settle();assert.equal(h.posts().filter(c=>c.url.endsWith('/commands/share')).length,1);assert.ok(h.root.querySelectorAll('textarea').some(node=>node.value.includes('#share=')));h.panel.suspend();
});

test('team members default to a team, while active legacy personal members retain explicit role management',async()=>{
 const h=setup({workspace:'personal'});h.data.members=[{workspace_id:'personal',identity_id:'legacy',display_name:'历史成员',scope_name:'个人归属',role:'viewer',active:true},{workspace_id:'personal',identity_id:'removed',display_name:'已移除成员',scope_name:'个人归属',role:'viewer',active:false}];await h.panel.load({area:'members'});assert.equal(select(h,'成员所属范围').value,'workspace:team-a');await h.panel.load({area:'members',team:'personal'});assert.equal(button(h,'创建一次邀请'),undefined);assert.equal(button(h,'恢复此成员').disabled,true);const role=h.root.querySelectorAll('select').find(node=>node.getAttribute('aria-label')?.includes('历史成员'));assert.equal(role.disabled,false);role.value='editor';await click(h,'保存此成员角色');const command=h.posts().find(c=>c.url.endsWith('/commands/member'));assert.equal(command.body.payload.scope,'workspace');assert.equal(command.body.payload.scope_id,'personal');assert.equal(command.body.payload.role,'editor');assert.equal(command.body.payload.active,true);h.panel.suspend();
});

test('personal ownership uses the durable owner identity rather than the viewing account',async()=>{
 const h=setup();h.data.workspaces[0].owner_name='xuyun';h.data.workspaces[0].owner_actor='xuyun';h.data.workspaces[0].owner_active=false;await h.panel.load({area:'workspace'});assert.match(h.root.textContent,/个人 · xuyun/);assert.match(h.root.textContent,/账户注销后，项目归属及历史记录继续保留/);assert.doesNotMatch(h.root.textContent,/当前空间|未归属/);assert.equal(h.posts().length,0);h.panel.suspend();
});

test('invitation landing delegates its explicit project collaborator destination to the shell',async()=>{
 const h=setup(),routes=[];h.ctx.navigateAccess=async value=>routes.push(value);await h.panel.load({invite:'project-target'});await settle();await click(h,'确认接受此邀请');assert.deepEqual(routes,[{page:'access',area:'members',project:'p-b',team:null,canvas:null}]);assert.equal(h.calls.some(c=>c.url.includes('switch-workspace')),false);h.panel.suspend();
});
