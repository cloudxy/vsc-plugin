import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {test} from 'node:test';
globalThis.crypto ??= webcrypto;
class Node {
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.attrs={};this.dataset={};this.className='';this.listeners={};this.value='';this.open=false;}
 append(...items){for(const n of items){if(!(n instanceof Node))continue;n.remove();n.parentElement=this;this.children.push(n);}}
 replaceChildren(...items){for(const n of this.children)n.parentElement=null;this.children=[];this.append(...items);}
 setAttribute(k,v){this.attrs[k]=String(v);} removeAttribute(k){delete this.attrs[k];}
 remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}}
 querySelectorAll(sel){return this.walk().filter(n=>sel==='dialog[open]'?n.tagName==='DIALOG'&&n.open:sel==='dialog'?n.tagName==='DIALOG':sel[0]==='.'&&n.className.split(' ').includes(sel.slice(1)));}
 querySelector(sel){return this.querySelectorAll(sel)[0]||null;} walk(){return this.children.flatMap(n=>[n,...n.walk()]);}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);} showModal(){this.open=true;} close(){this.open=false;this.onclose?.();}get options(){return this.children.filter(n=>n.tagName==='OPTION');}
 get textContent(){return this._text??this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=String(v);}
}
const document={documentElement:{},createElement(tag){return new Node(tag,this);},createTextNode(text){let n=new Node('#text',this);n.textContent=text;return n;}};globalThis.document=document;
const {createProjectManagement,restoreTargetUrl,computeRecycleDaysLeft}=await import(new URL('../../../src/vsc/interfaces/web/static/project-management.js', import.meta.url));
const make=({failFirst=false,refreshFail=false,failStatus=422}={})=>{let state='trashed',rev=8,failed=false,posts=[];const notices=[],scopes=[],root=new Node('main',document),row={id:'p1',name:'测试项目',state:'trashed',changed_at:'2026-10-28T10:00:00Z'};
 const ctx={session:()=>({actor:'test',csrf:'t'}),notice:m=>notices.push(String(m)),setRevision(){},onScope:(p)=>scopes.push(p),onProjectsChanged:async()=>{if(refreshFail)throw Error('刷新失败');},api:async(url,opts)=>{if(opts?.method==='POST'){posts.push(JSON.parse(opts.body));if(failFirst&&!failed){failed=true;const error=Error('暂时不可用');error.status=failStatus;throw error;}state='active';return {revision:++rev,status:'restored'};}if(url==='/api/v1/projects')return {items:state==='active'?[{id:'p1',name:row.name}]:[]};if(url==='/api/v1/project-management/recycled')return {items:state==='trashed'?[row]:[]};if(url.startsWith('/api/v1/project-management/recycle-items?')){const kind=new URL(url,'http://fixture').searchParams.get('kind');return {items:state==='trashed'&&['all','project'].includes(kind)?[{project_id:'p1',target_id:'p1',target_type:'project',kind:'project',title:row.name,revision:rev,can_restore:true,days_remaining:25}]:[],next_cursor:null};}if(url.startsWith('/api/v1/projects/p1/management?'))return {project:{id:'p1',name:row.name},state,revision:rev,folders:[],items:[],total:0,next_offset:null};throw Error(url);}};
 return {root,panel:createProjectManagement(root,ctx),notices,scopes,posts};};
const find=(root,tag,text)=>root.walk().find(n=>n.tagName===tag&&n.textContent===text);

test('category availability across all 9 tabs, rejected restore keeps input and refresh failure only reads back',async()=>{
 const x=make({failFirst:true,refreshFail:true});await x.panel.load({project:null});assert.match(x.root.textContent,/删除的项目和媒资会在这里保留 30 天，恢复后可继续创作/);assert.match(x.root.textContent,/本页 1 项/);assert.match(x.root.textContent,/剩余 25 天/);assert.doesNotMatch(x.root.textContent,/彻底删除|清空回收站/);
 await find(x.root,'BUTTON','分镜图').onclick();assert.doesNotMatch(x.root.textContent,/该分类暂未接入/);assert.match(x.root.textContent,/暂无数据/);
 await find(x.root,'BUTTON','项目').onclick();assert.match(x.root.textContent,/本页 1 项/);await find(x.root,'BUTTON','恢复').onclick();let dialog=x.root.querySelector('dialog');assert.ok(dialog);const form=dialog.walk().find(n=>n.tagName==='FORM'),input=dialog.walk().find(n=>n.tagName==='INPUT');input.value='测试恢复';for(const onInput of input.listeners.input||[])onInput({target:input});await form.onsubmit({preventDefault(){}});assert.equal(x.root.querySelector('dialog'),dialog);assert.equal(input.value,'测试恢复');assert.match(x.notices.at(-1),/暂时不可用/);await form.onsubmit({preventDefault(){}});assert.equal(x.posts.length,2);assert.equal(x.posts[1].payload.operation,'restore');assert.equal(x.posts[1].payload.target_id,'p1');assert.equal(x.posts[1].payload.reason,'测试恢复');assert.equal(x.posts[1].expected_revision,8);assert.deepEqual(x.scopes,['p1',null]);assert.match(x.root.textContent,/暂无数据/);assert.ok(x.notices.some(n=>n.includes('操作已保存，但项目列表刷新失败')));
 await x.panel.load({project:null});assert.equal(x.posts.length,2,'readback retry must not submit restore again');
});

test('reopening a rejected restore preserves the typed reason within its project',async()=>{
 const x=make({failFirst:true});await x.panel.load({project:null});await find(x.root,'BUTTON','恢复').onclick();let dialog=x.root.querySelector('dialog');const form=dialog.walk().find(n=>n.tagName==='FORM'),input=dialog.walk().find(n=>n.tagName==='INPUT');input.value='保留的理由';for(const onInput of input.listeners.input||[])onInput({target:input});await form.onsubmit({preventDefault(){}});dialog.close();await find(x.root,'BUTTON','恢复此项目').onclick();dialog=x.root.querySelector('dialog');assert.equal(dialog.walk().find(n=>n.tagName==='INPUT').value,'保留的理由');assert.equal(x.posts.length,1);
});

test('old project load does not open a dialog after scope changes',async()=>{
 let release;const deferred=new Promise(resolve=>release=resolve),root=new Node('main',document),row={id:'p1',name:'测试项目',state:'trashed'};const ctx={session:()=>({actor:'test'}),notice(){},onScope(){},api:async url=>{if(url==='/api/v1/projects')return {items:[]};if(url==='/api/v1/project-management/recycled')return {items:[row]};if(url.startsWith('/api/v1/project-management/recycle-items?'))return {items:[{project_id:'p1',target_id:'p1',target_type:'project',kind:'project',title:row.name,revision:1,can_restore:true}],next_cursor:null};if(url.startsWith('/api/v1/projects/p1/management?'))return deferred;throw Error(url);}};
 const panel=createProjectManagement(root,ctx);await panel.load({project:null});const click=find(root,'BUTTON','恢复').onclick();await new Promise(r=>setImmediate(r));await panel.load({project:null});release({project:{id:'p1',name:'测试项目'},state:'trashed',revision:1,folders:[],items:[],total:0,next_offset:null});await click;assert.equal(root.querySelector('dialog'),null);assert.match(root.textContent,/本页 1 项/);
});

test('unknown restore receipt replays the original operation identity and payload',async()=>{
 const x=make({failFirst:true,failStatus:500});await x.panel.load({project:null});await find(x.root,'BUTTON','恢复').onclick();const dialog=x.root.querySelector('dialog'),form=dialog.walk().find(n=>n.tagName==='FORM'),input=dialog.walk().find(n=>n.tagName==='INPUT');input.value='请求回执测试';await form.onsubmit({preventDefault(){}});dialog.close();const retry=find(x.root,'BUTTON','恢复原操作回执');assert.ok(retry);await retry.onclick();assert.equal(x.posts.length,2);assert.equal(x.posts[0].idempotency_key,x.posts[1].idempotency_key);assert.deepEqual(x.posts[0].payload,x.posts[1].payload);assert.equal(x.posts[0].expected_revision,x.posts[1].expected_revision);
});

const recycleItem=(id,kind,extra={})=>({project_id:'p1',target_id:id,target_type:kind==='project'?'project':'object',kind,title:id,revision:8,can_restore:true,blocked_by_project:false,blocked_by_ancestor:false,...extra});

test('server cursors page forward and backward, show blocked reasons and retain failed-page retry',async()=>{
 const root=new Node('main',document),requests=[];let failSecond=false;
 const pages=[recycleItem('p1','project'),recycleItem('e1','episode',{can_restore:false,blocked_by_ancestor:true}),recycleItem('a1','asset',{can_restore:false,blocked_by_project:true})];
 const context={session:()=>({actor:'test',csrf:'token'}),notice(){},api:async(url,options)=>{
  if(url==='/api/v1/projects'||url==='/api/v1/project-management/recycled')return {items:[]};
  if(url.startsWith('/api/v1/project-management/recycle-items?')){
   const query=new URL(url,'http://fixture').searchParams,cursor=query.get('cursor');requests.push({kind:query.get('kind'),cursor,limit:query.get('limit'),csrf:options.headers['X-CSRF-Token']});
   if(failSecond&&cursor==='page-2')throw Error('分页读取失败');
   const index=cursor==='page-2'?1:cursor==='page-3'?2:0;
   return {items:[pages[index]],next_cursor:index<2?'page-'+(index+2):null};
  }throw Error(url);
 }};
 const panel=createProjectManagement(root,context);await panel.load({project:null});
 assert.ok(find(root,'H3','p1'));assert.deepEqual(requests[0],{kind:'all',cursor:null,limit:'24',csrf:'token'});
 failSecond=true;await find(root,'BUTTON','下一页').onclick();assert.match(root.textContent,/回收列表读取失败.*分页读取失败/);assert.doesNotMatch(root.textContent,/暂无数据/);
 failSecond=false;await find(root,'BUTTON','重新读取').onclick();assert.ok(find(root,'H3','e1'));assert.match(root.textContent,/请先恢复上级对象/);assert.equal(find(root,'BUTTON','恢复').disabled,true);
 await find(root,'BUTTON','下一页').onclick();assert.ok(find(root,'H3','a1'));assert.match(root.textContent,/请先恢复所属项目/);assert.equal(find(root,'BUTTON','恢复').disabled,true);
 await find(root,'BUTTON','上一页').onclick();assert.ok(find(root,'H3','e1'));await find(root,'BUTTON','上一页').onclick();assert.ok(find(root,'H3','p1'));
 assert.deepEqual(requests.map(row=>row.cursor),[null,'page-2','page-2','page-3','page-2',null]);panel.suspend();
});

test('late category response cannot replace a newer category or its error state',async()=>{
 let resolveEpisode,rejectProject;const episode=new Promise(resolve=>resolveEpisode=resolve),project=new Promise((_,reject)=>rejectProject=reject),root=new Node('main',document);
 const context={session:()=>({actor:'test',csrf:'token'}),notice(){},api:async url=>{
  if(url==='/api/v1/projects'||url==='/api/v1/project-management/recycled')return {items:[]};
  if(url.startsWith('/api/v1/project-management/recycle-items?')){const kind=new URL(url,'http://fixture').searchParams.get('kind');if(kind==='episode')return episode;if(kind==='project')return project;if(kind==='asset')return {items:[recycleItem('latest-asset','asset')],next_cursor:null};return {items:[],next_cursor:null};}throw Error(url);
 }};
 const panel=createProjectManagement(root,context);await panel.load({project:null});
 const oldSuccess=find(root,'BUTTON','剧集').onclick();await new Promise(setImmediate);const oldFailure=find(root,'BUTTON','项目').onclick();await new Promise(setImmediate);
 await find(root,'BUTTON','资产').onclick();assert.ok(find(root,'H3','latest-asset'));
 resolveEpisode({items:[recycleItem('stale-episode','episode')],next_cursor:null});rejectProject(Error('旧分类错误'));await Promise.all([oldSuccess,oldFailure]);
 assert.ok(find(root,'H3','latest-asset'));assert.equal(find(root,'H3','stale-episode'),undefined);assert.doesNotMatch(root.textContent,/旧分类错误/);panel.suspend();
});

test('restore confirmation and repeated submit create only one pending operation',async()=>{
 let complete,posts=0,opens=0;const waiting=new Promise(resolve=>complete=resolve),root=new Node('main',document),row=recycleItem('asset2','asset');
 const context={session:()=>({actor:'test',csrf:'token'}),notice(){},onScope(){},onProjectsChanged(){},api:async(url,options)=>{
  if(options?.method==='POST'){posts++;return waiting;}if(url==='/api/v1/projects')return {items:[{id:'p1',name:'项目'}]};if(url==='/api/v1/project-management/recycled')return {items:[]};
  if(url.startsWith('/api/v1/project-management/recycle-items?'))return {items:[row],next_cursor:null};
  if(url.startsWith('/api/v1/projects/p1/management?')){opens++;return {project:{id:'p1',name:'项目'},state:'active',revision:8,folders:[],items:[],total:0,next_offset:null};}throw Error(url);
 }};
 const panel=createProjectManagement(root,context);await panel.load({project:null});
 const restore=find(root,'BUTTON','恢复'),firstOpen=restore.onclick(),secondOpen=restore.onclick();await Promise.all([firstOpen,secondOpen]);assert.equal(opens,1);
 const dialog=root.querySelector('dialog'),form=dialog.walk().find(node=>node.tagName==='FORM');dialog.walk().find(node=>node.tagName==='INPUT').value='一次';
 const first=form.onsubmit({preventDefault(){}});await new Promise(setImmediate);await form.onsubmit({preventDefault(){}});assert.equal(posts,1);
 complete({revision:9,status:'restored'});await first;assert.equal(posts,1);panel.suspend();
});

test('asset restore recovers the original receipt and refresh failure never repeats the write',async()=>{
 let rows=[recycleItem('a1','asset')],revision=8,failPost=true;const posts=[],notices=[],root=new Node('main',document),scopes=[];
 const context={session:()=>({actor:'test',csrf:'token'}),notice:value=>notices.push(String(value)),setRevision(){},onScope:value=>scopes.push(value),onProjectsChanged:async()=>{throw Error('刷新失败');},api:async(url,options)=>{
  if(options?.method==='POST'){posts.push(JSON.parse(options.body));if(failPost){failPost=false;const error=Error('回执未知');error.status=500;throw error;}rows=[];return {revision:++revision,status:'restored'};}
  if(url==='/api/v1/projects')return {items:[{id:'p1',name:'项目'}]};if(url==='/api/v1/project-management/recycled')return {items:[]};
  if(url.startsWith('/api/v1/project-management/recycle-items?'))return {items:rows,next_cursor:null};
  if(url.startsWith('/api/v1/projects/p1/management?'))return {project:{id:'p1',name:'项目'},state:'active',revision,folders:[],items:[],total:0,next_offset:null};throw Error(url);
 }};
 const panel=createProjectManagement(root,context);await panel.load({project:null});await find(root,'BUTTON','恢复').onclick();
 const dialog=root.querySelector('dialog'),form=dialog.walk().find(node=>node.tagName==='FORM'),input=dialog.walk().find(node=>node.tagName==='INPUT');input.value='恢复资产';
 await form.onsubmit({preventDefault(){}});assert.equal(posts.length,1);assert.equal(input.value,'恢复资产');dialog.close();
 await find(root,'BUTTON','恢复原操作回执').onclick();assert.equal(posts.length,2);assert.deepEqual(posts[1],posts[0]);
 assert.deepEqual(posts[0].payload,{operation:'restore',target_type:'object',target_id:'a1',reason:'恢复资产'});assert.equal(posts[0].expected_revision,8);
 assert.deepEqual(scopes,['p1',null]);assert.match(root.textContent,/暂无数据/);assert.ok(notices.some(value=>value.includes('操作已保存，但项目列表刷新失败')));
 await panel.load({project:null});assert.equal(posts.length,2);panel.suspend();
});

test('video restore uses the original media endpoint and recovers the same request',async()=>{
 let rows=[{...recycleItem('v1','video'),target_type:'media'}],revision=8,fail=true;const posts=[],root=new Node('main',document),scopes=[];
 const ctx={session:()=>({actor:'test',csrf:'token'}),notice(){},setRevision(){},onScope:p=>scopes.push(p),onProjectsChanged(){},api:async(url,options)=>{
  if(options?.method==='POST'){posts.push({url,body:JSON.parse(options.body)});if(fail){fail=false;const e=Error('回执未知');e.status=500;throw e;}rows=[];return {revision:++revision,items:[{id:'v1',status:'restored'}]};}
  if(url==='/api/v1/projects')return {items:[{id:'p1',name:'项目'}]};if(url==='/api/v1/project-management/recycled')return {items:[]};
  if(url.startsWith('/api/v1/project-management/recycle-items?'))return {items:rows,next_cursor:null};
  if(url.startsWith('/api/v1/projects/p1/management?'))return {project:{id:'p1',name:'项目'},state:'active',revision,folders:[],items:[],total:0,next_offset:null};throw Error(url);
 }};
 const panel=createProjectManagement(root,ctx);await panel.load({project:null});await find(root,'BUTTON','视频').onclick();await find(root,'BUTTON','恢复').onclick();
 const dialog=root.querySelector('dialog'),form=dialog.walk().find(n=>n.tagName==='FORM');dialog.walk().find(n=>n.tagName==='INPUT').value='恢复视频';await form.onsubmit({preventDefault(){}});dialog.close();
 await find(root,'BUTTON','恢复原操作回执').onclick();assert.equal(posts.length,2);assert.deepEqual(posts[1],posts[0]);
 assert.equal(posts[0].url,'/api/v1/projects/p1/recycle-actions');assert.equal(posts[0].body.confirmed,true);assert.deepEqual(posts[0].body.payload,{media_ids:['v1'],action:'restore',reason:'恢复视频'});
 assert.deepEqual(scopes,['p1',null]);assert.match(root.textContent,/暂无数据/);panel.suspend();
});

test('canvas category restores in-place without window.open while non-canvas opens workbench in new window',async()=>{
 const openedWindows=[];
 const prevWindow=globalThis.window;
 globalThis.window={open(url,target){const w={url,target,closed:false,location:{href:url},close(){this.closed=true;}};openedWindows.push(w);return w;}};
 try{
  assert.equal(restoreTargetUrl({kind:'canvas',project_id:'p1',target_id:'c1'}),null);
  assert.equal(restoreTargetUrl({kind:'asset',project_id:'p1',target_id:'a1'}),'/character?project_id=p1');
  assert.equal(restoreTargetUrl({kind:'storyboard-image',project_id:'p1',target_id:'img1'}),'/?page=storyboard&project=p1');
  assert.equal(computeRecycleDaysLeft({changed_at:'2026-10-20T00:00:00Z'},Date.parse('2026-10-30T00:00:00Z')),20);

  let rows=[{...recycleItem('c1','canvas'),target_type:'canvas'}],revision=8;const posts=[],root=new Node('main',document),scopes=[];
  const ctx={session:()=>({actor:'test',csrf:'t'}),notice(){},setRevision(){},onScope:p=>scopes.push(p),api:async(url,options)=>{
   if(options?.method==='POST'){posts.push({url,body:JSON.parse(options.body)});rows=[];return {revision:++revision,state:'active',target_type:'canvas',target_id:'c1'};}
   if(url==='/api/v1/projects')return {items:[{id:'p1',name:'项目'}]};if(url==='/api/v1/project-management/recycled')return {items:[]};
   if(url.startsWith('/api/v1/project-management/recycle-items?')){
    const kind=new URL(url,'http://fixture').searchParams.get('kind');
    if(kind==='storyboard-group')return {items:[{...recycleItem('seq1','storyboard-group'),target_type:'object'}],next_cursor:null};
    return {items:rows,next_cursor:null};
   }
   if(url.startsWith('/api/v1/projects/p1/management?'))return {project:{id:'p1',name:'项目'},state:'active',revision,folders:[],items:[],total:0,next_offset:null};throw Error(url);
  }};
  const panel=createProjectManagement(root,ctx);await panel.load({project:null});await find(root,'BUTTON','画布').onclick();assert.doesNotMatch(root.textContent,/暂未接入/);
  await find(root,'BUTTON','恢复').onclick();let dialog=root.querySelector('dialog'),form=dialog.walk().find(n=>n.tagName==='FORM');dialog.walk().find(n=>n.tagName==='INPUT').value='恢复原画布';await form.onsubmit({preventDefault(){}});
  assert.equal(posts.length,1);assert.equal(posts[0].url,'/api/v1/projects/p1/management');assert.deepEqual(posts[0].body.payload,{operation:'restore',target_type:'canvas',target_id:'c1',reason:'恢复原画布'});
  assert.equal(openedWindows.length,0,'canvas restore must stay in-place without opening a new window');
  assert.deepEqual(scopes,['p1',null]);assert.match(root.textContent,/暂无数据/);

  await find(root,'BUTTON','分镜镜号').onclick();assert.ok(find(root,'H3','seq1'));
  await find(root,'BUTTON','恢复').onclick();dialog=root.querySelector('dialog');form=dialog.walk().find(n=>n.tagName==='FORM');dialog.walk().find(n=>n.tagName==='INPUT').value='恢复镜组';await form.onsubmit({preventDefault(){}});
  assert.equal(openedWindows.length,1);assert.equal(openedWindows[0].location.href,'/?page=storyboard&project=p1');assert.equal(openedWindows[0].closed,false);
  panel.suspend();
 }finally{globalThis.window=prevWindow;}
});
