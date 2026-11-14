import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {createTaskNotifications} from '../../../src/vsc/interfaces/web/static/task-notifications.js';
const require=createRequire(import.meta.url),{Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;};
const nativeSetTimeout=globalThis.setTimeout,nativeClearTimeout=globalThis.clearTimeout;
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const item=(id='notice-one',extra={})=>({id,sequence:1,title:'原任务结果',kind:'text',observed_status:'completed',current_status:'completed',is_current_event:true,created_at:'2026-11-14T01:00:00Z',unread:true,task_href:'/?page=tasks&project=p&task_id=original',href:'/?page=text-tools&project=p&task_target=unit',...extra});
const feed=(items=[item()],extra={})=>({items,unread_count:items.filter(x=>x.unread).length,through_sequence:Math.max(0,...items.map(x=>x.sequence)),next_cursor:null,...extra});
function setup(t,{api,projects=[{id:'p',name:'测试项目'},{id:'other',name:'另一项目'}]}={}){
 const document=new Document('');globalThis.document=document;const root=document.createElement('div');document.body.append(root);
 const timers=new Map();let timerId=0;const originalSet=nativeSetTimeout,originalClear=nativeClearTimeout;
 globalThis.setTimeout=fn=>{timers.set(++timerId,fn);return timerId;};globalThis.clearTimeout=id=>timers.delete(id);
 t.after(()=>{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;});
 const session={actor:'human',identityId:'identity',csrf:'csrf'},calls=[];
 const notifications=createTaskNotifications(root,{session:()=>session,projects:()=>projects,projectName:id=>projects.find(p=>p.id===id)?.name,
  api:async(url,options={})=>{const call={url,options,body:options.body?JSON.parse(options.body):null};calls.push(call);return api?api(call):feed();}});
 const dialog=()=>document.body.querySelector('dialog');
 const button=text=>dialog()?.querySelectorAll('button').find(n=>n.textContent===text||n.textContent.includes(text));
 const projectSelect=()=>dialog().querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='通知项目');
 const rows=()=>dialog()?.querySelectorAll('article')||[];
 const timer=async()=>{assert.equal(timers.size,1);const [id,fn]=[...timers][0];timers.delete(id);await fn();};
 return {notifications,root,document,session,calls,timers,timer,dialog,button,projectSelect,rows};
}

test('home exposes explicit project selection, task meaning, and the original task links',async t=>{
 const h=setup(t);await h.notifications.load({project:null});assert.equal(h.calls.length,0);assert.equal(h.root.querySelector('button').disabled,false);
 await h.notifications.open();assert.ok(h.dialog().textContent.includes('已读仅表示看过'));assert.ok(h.dialog().textContent.includes('进行中的任务'));
 h.projectSelect().value='p';await h.projectSelect().dispatch('change');
 assert.equal(h.rows().length,1);assert.ok(h.calls.at(-1).url.startsWith('/api/v1/projects/p/task-notifications?'));
 assert.equal(h.dialog().querySelectorAll('a').find(a=>a.textContent==='查看全部任务').href,'/?page=tasks&project=p');
 assert.deepEqual(h.rows()[0].querySelectorAll('a').map(a=>a.href),[item().task_href,item().href]);h.notifications.suspend();assert.equal(h.timers.size,0);
});

test('automatic polling refreshes the open list and keeps focus on the same action',async t=>{
 let result=feed();const h=setup(t,{api:()=>structuredClone(result)});await h.notifications.load({project:'p'});await h.notifications.open();
 h.button('刷新通知').focus();result=feed([item('new',{sequence:2,title:'新完成结果'}),item()]);await h.timer();
 assert.equal(h.rows().length,2);assert.ok(h.dialog().textContent.includes('新完成结果'));assert.equal(h.document.activeElement.dataset.notificationFocus,'refresh');assert.ok(h.root.textContent.includes('2'));
 await h.button('关闭任务通知').click();assert.equal(h.dialog(),null);assert.equal(h.timers.size,1);h.notifications.suspend();
});

test('a late badge request cannot resurrect unread state after marking read',async t=>{
 const badge=deferred();let pending=false,read=false;
 const h=setup(t,{api:call=>{
  if(call.options.method==='POST'){read=true;return {marked_count:1};}
  if(call.url.endsWith('?limit=1')&&pending)return badge.promise;
  return feed([item('notice-one',{unread:!read})]);
 }});
 await h.notifications.load({project:'p'});pending=true;const polling=h.timer();await h.notifications.open();await h.button('标为已读').click();badge.resolve(feed([item()],{unread_count:99}));await polling;
 assert.equal(h.root.textContent,'任务通知');assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);assert.equal(h.rows()[0].classList.contains('unread'),false);h.notifications.suspend();
});

test('a successful read survives refresh failure and a second refresh performs no new write',async t=>{
 let read=false,fail=false;const h=setup(t,{api:call=>{
  if(call.options.method==='POST'){read=true;fail=true;return {marked_count:1};}
  if(fail)throw new Error('offline');return feed([item('notice-one',{unread:!read})]);
 }});
 await h.notifications.load({project:'p'});await h.notifications.open();await h.button('标为已读').click();
 assert.ok(h.dialog().textContent.includes('已读状态已保存'));assert.equal(h.rows()[0].classList.contains('unread'),false);assert.equal(h.root.textContent,'任务通知');
 fail=false;await h.button('刷新通知').click();assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);assert.equal(h.dialog().textContent.includes('offline'),false);h.notifications.suspend();
});

test('old project responses and errors cannot paint or schedule over the new project',async t=>{
 for(const failure of [false,true]){
  const old=deferred();let delay=false;const h=setup(t,{api:call=>call.url.includes('/p/')&&delay?old.promise:feed([item('other-result',{title:'另一项目结果'})])});
  await h.notifications.load({project:'p'});delay=true;const opening=h.notifications.open();await h.notifications.load({project:'other'});await h.notifications.open();
  if(failure)old.reject(new Error('旧项目失败'));else old.resolve(feed([item('stale',{title:'旧项目结果'})]));await opening;
  assert.ok(h.dialog().textContent.includes('另一项目结果'));assert.equal(h.dialog().textContent.includes('旧项目'),false);assert.equal(h.timers.size,1);h.notifications.suspend();
 }
});

test('an identity change invalidates a response even before the outer panel reloads',async t=>{
 const old=deferred();const h=setup(t,{api:()=>old.promise});const pending=h.notifications.load({project:'p'});h.session.identityId='different-identity';old.resolve(feed());await pending;
 assert.equal(h.root.textContent,'任务通知');assert.equal(h.timers.size,0);h.notifications.suspend();
});

test('pagination stays on its snapshot when new notifications arrive; explicit refresh returns to the newest',async t=>{
 let latest=false;const h=setup(t,{api:call=>{
  if(call.url.includes('cursor='))return feed([item('older',{sequence:1,title:'较早任务'})],{through_sequence:2});
  if(call.url.endsWith('?limit=1'))return feed([item('new',{sequence:3})],{through_sequence:3});
  return latest?feed([item('new',{sequence:3,title:'最新任务'})]):feed([item('first',{sequence:2})],{next_cursor:'fixed-snapshot'});
 }});
 await h.notifications.load({project:'p'});await h.notifications.open();await h.button('读取更早通知').click();assert.equal(h.rows().length,2);
 await h.timer();assert.equal(h.rows().length,2);assert.ok(h.dialog().textContent.includes('较早任务'));assert.ok(h.button('有新的任务变化'));
 latest=true;await h.button('有新的任务变化').click();assert.equal(h.rows().length,1);assert.ok(h.dialog().textContent.includes('最新任务'));h.notifications.suspend();
});

test('notification failures do not fail project loading and retain an accessible retry',async t=>{
 let fail=true;const h=setup(t,{api:()=>{if(fail)throw new Error('temporarily unavailable');return feed();}});
 await assert.doesNotReject(h.notifications.load({project:'p'}));await h.notifications.open();assert.ok(h.dialog().textContent.includes('temporarily unavailable'));
 fail=false;await h.button('刷新通知').click();assert.equal(h.rows().length,1);assert.equal(h.dialog().textContent.includes('temporarily unavailable'),false);h.notifications.suspend();
});

test('a historical event does not borrow the current batch outcome or error',async t=>{
 const h=setup(t,{api:()=>feed([item('history',{kind:'text_batch',observed_status:'running',current_status:'stopped',is_current_event:false,current_error:'当前问题'})])});
 await h.notifications.load({project:'p'});await h.notifications.open();assert.ok(h.dialog().textContent.includes('执行中'));assert.ok(h.dialog().textContent.includes('原任务当前状态'));assert.ok(h.dialog().textContent.includes('任务当前问题：当前问题'));h.notifications.suspend();
});

test('a late background failure cannot replace a successful foreground refresh with a stale error',async t=>{
 const badge=deferred();let pending=false;const h=setup(t,{api:call=>call.url.endsWith('?limit=1')&&pending?badge.promise:feed()});
 await h.notifications.load({project:'p'});pending=true;const polling=h.timer();await h.notifications.open();badge.reject(new Error('stale background error'));await polling;
 assert.equal(h.dialog().textContent.includes('stale background error'),false);assert.equal(h.rows().length,1);h.notifications.suspend();
});

test('cached notifications disappear immediately when an unrefreshed identity tries to reopen them',async t=>{
 const h=setup(t);await h.notifications.load({project:'p'});await h.notifications.open();assert.equal(h.rows().length,1);
 h.session.identityId='different-identity';await h.notifications.open();assert.equal(h.dialog(),null);assert.equal(h.root.textContent,'任务通知');assert.equal(h.root.querySelector('button').disabled,true);assert.equal(h.timers.size,0);
 await h.notifications.load({project:'other'});await h.notifications.open();assert.equal(h.projectSelect().value,'other');h.notifications.suspend();
});

test('marking a historical snapshot keeps a newer unread badge when readback fails',async t=>{
 let saved=false;const h=setup(t,{api:call=>{
  if(call.options.method==='POST'){assert.equal(call.body.payload.through_sequence,2);saved=true;return {marked_count:2};}
  if(saved)throw new Error('readback offline');
  if(call.url.includes('cursor='))return feed([item('older',{sequence:1})],{through_sequence:2,unread_count:2});
  if(call.url.endsWith('?limit=1'))return feed([item('new',{sequence:3})],{through_sequence:3,unread_count:3});
  return feed([item('first',{sequence:2})],{through_sequence:2,unread_count:2,next_cursor:'snapshot'});
 }});
 await h.notifications.load({project:'p'});await h.notifications.open();await h.button('读取更早通知').click();await h.timer();assert.ok(h.root.textContent.includes('3'));
 await h.button('全部标为已读').click();assert.ok(h.root.textContent.includes('1'));assert.ok(h.dialog().textContent.includes('已读状态已保存'));assert.equal(h.button('全部标为已读').disabled,true);assert.ok(h.button('有新的任务变化'));h.notifications.suspend();
});

test('the actual panel invalidates notification identity synchronously and changes scope before workbench returns',async t=>{
 setup(t);
 const {createPanel}=require('../../support/fixtures/frontend/panel_dom.cjs');
 const projects=new Map(['p','other'].map(id=>[id,{project:{id,name:id,storage_policy:'postgres-series-v1',revision:0},revision:0,nodes:[]}])) ;
 const blocked=deferred();let delaying=false;
 const h=createPanel(new URL('../../..',import.meta.url).pathname,projects,null,{handleRequest:async url=>{
  if(url.includes('/task-notifications'))return feed([item(url.includes('/other/')?'other-notice':'p-notice')]);
  if(delaying&&url.includes('/other/workbench'))return blocked.promise;
 }});
 Object.assign(h.panel.state,{actor:'human',identityId:'identity',workspaceId:'workspace',shareId:null,writeAvailable:true,view:'media',projectRows:new Map([...projects].map(([id,value])=>[id,value.project]))});
 await h.panel.selectProject('p');const trigger=h.document.getElementById('task-notifications').querySelector('button');assert.ok(trigger);
 await trigger.click();assert.ok(h.document.body.querySelector('.task-notification-dialog').textContent.includes('原任务结果'));
 delaying=true;const switching=h.panel.selectProject('other');assert.equal(h.document.body.querySelector('.task-notification-dialog'),null);
 assert.ok(trigger.getAttribute('title').includes('other'));assert.ok(h.requests.some(url=>url.includes('/other/task-notifications')));
 blocked.reject(new Error('workbench unavailable'));await assert.rejects(switching,/workbench unavailable/);
 await trigger.click();const notificationDialog=h.document.body.querySelector('.task-notification-dialog');assert.equal(notificationDialog.querySelector('article').dataset.notificationId,'other-notice');
 h.panel.applySession({actor:'other-human',identity_id:'other-identity',workspace_id:'workspace',share_id:null,write_available:true});
 assert.equal(h.document.body.querySelector('.task-notification-dialog'),null);assert.equal(h.document.getElementById('task-notifications').hidden,true);assert.equal(trigger.disabled,true);
});
