import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {webcrypto} from 'node:crypto';
import {createProductionPlatform} from '../../../src/vsc/interfaces/web/static/production-platform.js';
const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
Element.prototype.replaceWith=function(node){const parent=this.parentElement;if(!parent)return;const index=parent.children.indexOf(this);parent.children[index]=node;node.parentElement=parent;this.parentElement=null;};
const rows=[
 {id:'personal',name:'个人片段',owner_kind:'personal',owner_actor:'me',owner_name:'owner_hidden',workspace_id:'personal-space',workspace_name:'space_hidden',created_by:'creator_hidden',access_capabilities:['read','edit','manage'],storage_policy:'postgres-series-v1'},
 {id:'team',name:'团队短片',owner_kind:'team',owner_name:'team_owner_hidden',workspace_id:'team-space',workspace_name:'team_space_hidden',created_by:'me',access_capabilities:['read','edit'],storage_policy:'postgres-series-v1'},
 {id:'history',name:'历史片段',owner_kind:'personal',owner_actor:'me',owner_name:'owner_hidden',workspace_id:'personal-space',created_by:null,access_capabilities:['read','edit','manage'],storage_policy:'postgres-series-v1'},
 {id:'guest',name:'受邀短片',owner_kind:'personal',owner_actor:'other',owner_name:'other_owner_hidden',created_by:'me',read_only:true,access_capabilities:['read'],storage_policy:'postgres-series-v1'}];
function setup(extra={}){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;
 if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
 const storage=new Map();globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
 const session={actor:'me',ownerships:[{id:'team-space',name:'协作团队',kind:'studio',roles:['editor']}],csrf:'csrf',writeAvailable:true,writable:true};
 const routes=[],calls=[],notices=[];
 const ctx={session:()=>session,projects:()=>rows,notice:value=>notices.push(String(value)),navigate:async(...args)=>routes.push(args),refreshProjects:async()=>{},setRevision(){},api:async(path,options={})=>{calls.push({path,options});if(extra.api)return extra.api(path,options);throw new Error('Synthetic read stopped');}};
 return {root,session,routes,calls,notices,platform:createProductionPlatform(root,ctx)};
}
const ids=h=>h.root.querySelectorAll('.project-tile').filter(row=>row.dataset.projectId).map(row=>row.dataset.projectId);
test('three visible tabs partition every authorized project by owner, independent of creator',async()=>{
 const h=setup();await h.platform.load({page:'projects'});assert.deepEqual(h.notices,[]);assert.deepEqual(ids(h),['personal','history']);
 const tabs=h.root.querySelectorAll('a').filter(node=>node.getAttribute('role')==='tab');assert.deepEqual(tabs.map(node=>node.textContent),['个人项目','参与项目','团队项目','最近创作','团队模板']);assert.equal(tabs[0].getAttribute('aria-selected'),'true');assert.equal(h.root.querySelectorAll('select').length,0);
 await tabs[1].dispatch('click');assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'participating'}]);
 await tabs[1].dispatch('keydown',{key:'ArrowRight'});assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'team'}]);
 const partition=[];for(const category of ['personal','participating','team']){await h.platform.load({page:'projects',projectScope:category});partition.push(...ids(h));}
 assert.deepEqual(partition.sort(),rows.map(row=>row.id).sort());assert.equal(new Set(partition).size,rows.length);
 await h.platform.load({page:'projects',projectScope:'all'});assert.deepEqual(ids(h),['personal','history']);
 const dialogButton=h.root.querySelectorAll('button').find(row=>row.textContent.includes('新建项目'));await dialogButton.click();const dialog=h.root.querySelector('dialog');assert.ok(dialog.textContent.includes('项目归属'));const owner=dialog.querySelectorAll('select').find(row=>row.getAttribute('aria-label')==='项目归属');assert.equal(owner.value,'');assert.ok(owner.options.some(row=>row.value==='team-space'));
});
test('compact project cards omit owner and creator in visible and assistive content, with scoped search',async()=>{
 const h=setup();for(const category of ['personal','participating','team']){await h.platform.load({page:'projects',projectScope:category});const copy=h.root.textContent+' '+h.root.querySelectorAll('button').concat(h.root.querySelectorAll('a')).map(node=>[node.getAttribute('aria-label'),node.getAttribute('title')].join(' ')).join(' ');assert.ok(!copy.includes('_hidden'));assert.ok(!copy.includes('创建者未记录'));assert.ok(!copy.includes('项目始终归属于'));assert.ok(!h.root.querySelector('.project-cover-new'));}
 await h.platform.load({page:'projects'});const search=h.root.querySelector('input');search.value='历史';await search.dispatch('input');assert.deepEqual(ids(h),['history']);search.value='没有的片名';await search.dispatch('input');assert.equal(ids(h).length,0);assert.ok(h.root.textContent.includes('没有找到匹配项目'));await h.root.querySelectorAll('button').find(node=>node.textContent==='清空搜索').click();assert.deepEqual(ids(h),['personal','history']);
 await h.platform.load({page:'projects',projectScope:'participating'});assert.ok(h.root.textContent.includes('只读'));assert.ok(!h.root.querySelector('.project-card-actions'));
});
test('canvas and generated media directories send explicit ownership or relation to the authoritative list',async()=>{
 const h=setup();await h.platform.load({page:'projects',tab:'canvases',projectScope:'team'});
 assert.ok(h.calls.some(row=>row.path.startsWith('/api/v1/canvas-library?')&&new URL(row.path,'http://test').searchParams.get('project_category')==='team'));
 await h.platform.load({page:'projects',tab:'media',projectScope:'participating'});
 assert.ok(h.calls.some(row=>row.path.startsWith('/api/v1/project-media?')&&new URL(row.path,'http://test').searchParams.get('project_category')==='participating'));
 assert.ok(h.root.querySelectorAll('a').filter(a=>a.href?.includes('tab=canvases')).some(a=>a.href.includes('project_scope=participating')));
});
const tabsOf=h=>h.root.querySelectorAll('a').filter(node=>node.getAttribute('role')==='tab');
const workCard=()=>({href:'?page=creative-canvas&project=personal',project_id:'personal',project_name:'个人片段',episode_name:'第一集',title:'试拍',kind:'canvas',kind_label:'画布',created_at:new Date().toISOString()});
const hiddenCard=()=>({href:'?page=hidden',project_id:'secret',project_name:'不该出现',episode_name:'隐藏集',title:'隐藏作品',kind:'canvas',kind_label:'隐藏',created_at:new Date().toISOString()});
const discoveryOf=(recent)=>async path=>{if(path==='/api/v1/discovery')return {recent,projects:[],templates:[]};throw new Error('unexpected '+path);};
const noRecentScope=h=>h.calls.every(row=>!String(row.path).includes('project_scope=recent')&&!String(row.options?.body||'').includes('project_scope=recent'));
test('recent creation shows work cards for tab=recent and never sends project_scope=recent',async()=>{
 const h=setup({api:discoveryOf([workCard(),hiddenCard()])});
 await h.platform.load({page:'projects',projectScope:'team'});
 await tabsOf(h)[3].dispatch('click');
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'recent',project_scope:'team'}]);
 assert.notEqual(h.routes.at(-1)[3].project_scope,'recent');
 await h.platform.load({page:'projects',tab:'recent',projectScope:'team'});
 const tabs=tabsOf(h),recent=tabs.find(node=>node.id==='project-category-recent'),team=tabs.find(node=>node.id==='project-category-team');
 assert.equal(recent.getAttribute('aria-selected'),'true');assert.equal(team.getAttribute('aria-selected'),'false');
 assert.ok(recent.href.includes('tab=recent'));assert.ok(recent.href.includes('project_scope=team'));assert.ok(!recent.href.includes('project_scope=recent'));
 assert.ok(team.href.includes('project_scope=team'));assert.ok(!team.href.includes('tab=recent'));
 assert.equal(h.root.querySelectorAll('.project-tile').length,0);
 const cards=h.root.querySelectorAll('.recent-creation-card');assert.equal(cards.length,1);
 assert.ok(cards[0].href.includes('creative-canvas'));assert.ok(cards[0].textContent.includes('个人片段'));assert.ok(cards[0].textContent.includes('第一集'));assert.ok(cards[0].textContent.includes('试拍'));assert.ok(cards[0].textContent.includes('画布'));assert.ok(cards[0].textContent.includes('刚刚'));
 assert.ok(!h.root.textContent.includes('不该出现'));assert.ok(!h.root.textContent.includes('隐藏作品'));
 assert.ok(noRecentScope(h));assert.ok(!h.calls.some(row=>String(row.path).startsWith('/api/v1/projects')));
 await team.dispatch('click');assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'team'}]);
 await h.platform.load({page:'projects',tab:'canvases',projectScope:'team'});
 await tabsOf(h).find(node=>node.id==='project-category-recent').dispatch('click');
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'recent',project_scope:'team'}]);
 assert.ok(!String(h.routes.at(-1)[3].tab).includes('canvases'));
});
test('keyboard order wraps the category controls and keeps focus on the activated tab',async()=>{
 const h=setup({api:discoveryOf([workCard()])});
 await h.platform.load({page:'projects',projectScope:'team'});
 const team=()=>tabsOf(h).find(node=>node.id==='project-category-team');
 await team().dispatch('keydown',{key:'ArrowRight'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'recent',project_scope:'team'}]);
 assert.equal(globalThis.document.activeElement.id,'project-category-recent');
 await h.platform.load({page:'projects',tab:'recent',projectScope:'team'});
 const recent=tabsOf(h).find(node=>node.id==='project-category-recent');
 await recent.dispatch('keydown',{key:'ArrowRight'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'templates',project_scope:'team'}]);
 assert.equal(globalThis.document.activeElement.id,'project-category-templates');
 await recent.dispatch('keydown',{key:'ArrowLeft'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'team'}]);
 assert.equal(globalThis.document.activeElement.id,'project-category-team');
 await recent.dispatch('keydown',{key:'Home'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'personal'}]);
 assert.equal(globalThis.document.activeElement.id,'project-category-personal');
 await globalThis.document.activeElement.dispatch('keydown',{key:'End'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'templates',project_scope:'team'}]);
 assert.equal(globalThis.document.activeElement.id,'project-category-templates');
 await h.platform.load({page:'projects'});
 const fresh=tabsOf(h);
 await fresh[3].dispatch('keydown',{key:'ArrowRight'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'templates'}]);
 await fresh[0].dispatch('keydown',{key:'ArrowLeft'});
 assert.deepEqual(h.routes.at(-1),['projects',null,null,{tab:'templates'}]);
 assert.equal(h.routes.at(-1)[3].project_scope,undefined);
});
test('recent states keep loading, empty, logged-out and failure apart from project tiles',async()=>{
 let release;const pending=new Promise(resolve=>{release=resolve;});
 const loading=setup({api:()=>pending});const started=loading.platform.load({page:'projects',tab:'recent'});
 await Promise.resolve();await Promise.resolve();
 assert.ok(loading.root.textContent.includes('正在读取最近创作…'));
 assert.ok(!loading.root.textContent.includes('还没有最近创作'));
 assert.equal(loading.root.querySelectorAll('.recent-creation-card').length,0);
 assert.equal(loading.root.querySelectorAll('button').filter(node=>node.textContent==='重新读取'&&!node.disabled).length,0);
 release({recent:[],projects:[],templates:[]});await started;
 assert.ok(loading.root.textContent.includes('还没有最近创作。从首页的创作入口做出作品后，会出现在这里。'));
 assert.equal(loading.root.querySelectorAll('button').filter(node=>node.textContent==='重新读取').length,0);
 assert.equal(loading.root.querySelectorAll('.project-tile').length,0);
 const denied=setup({api:async()=>{throw Object.assign(new Error('need session'),{status:403});}});
 await denied.platform.load({page:'projects',tab:'recent'});
 assert.ok(denied.root.textContent.includes('建立会话后显示最近创作'));
 assert.ok(!denied.root.textContent.includes('need session'));
 assert.ok(!denied.root.textContent.includes('还没有最近创作。从首页的创作入口做出作品后，会出现在这里。'));
 assert.equal(denied.root.querySelectorAll('button').filter(node=>node.textContent==='重新读取').length,0);
 const offline=setup({api:async()=>{throw Object.assign(new TypeError('failed to fetch'),{offline:true});}});
 await offline.platform.load({page:'projects',tab:'recent'});
 assert.ok(offline.root.textContent.includes('连接中断，最近创作没有读完。'));
 assert.ok(!offline.root.textContent.includes('还没有最近创作。从首页的创作入口做出作品后'));
 let reads=0;const retry=setup({api:async path=>{if(path!=='/api/v1/discovery')throw new Error('unexpected '+path);reads+=1;if(reads===1)throw new Error('recent read failed');return {recent:[workCard()],projects:[],templates:[]};}});
 await retry.platform.load({page:'projects',tab:'recent'});
 assert.ok(retry.root.textContent.includes('recent read failed'));assert.ok(retry.root.textContent.includes('重新读取'));
 assert.ok(!retry.root.textContent.includes('还没有最近创作。从首页的创作入口做出作品后'));
 assert.ok(tabsOf(retry).length===5);
 const routes=retry.routes.length;await retry.root.querySelectorAll('button').find(node=>node.textContent==='重新读取').click();
 assert.equal(retry.routes.length,routes);assert.equal(retry.root.querySelectorAll('.recent-creation-card').length,1);
 assert.ok(!retry.root.textContent.includes('recent read failed'));assert.ok(noRecentScope(retry));
 const signedOut=setup({api:discoveryOf([workCard()])});signedOut.session.actor=null;
 await signedOut.platform.load({page:'projects',tab:'recent'});
 assert.ok(signedOut.root.textContent.includes('建立会话后显示最近创作'));
 assert.equal(signedOut.calls.filter(row=>row.path==='/api/v1/discovery').length,0);
 assert.equal(signedOut.root.querySelectorAll('.recent-creation-card').length,0);
});
test('a hand-typed project_scope=recent stays off the project list and off the work cards',async()=>{
 const h=setup();await h.platform.load({page:'projects',projectScope:'recent'});
 assert.deepEqual(ids(h),['personal','history']);
 assert.equal(h.root.querySelectorAll('.recent-creation-card').length,0);
 assert.deepEqual(tabsOf(h).map(node=>node.textContent),['个人项目','参与项目','团队项目','最近创作','团队模板']);
 assert.ok(tabsOf(h).every(node=>!String(node.href).includes('project_scope=recent')));
 assert.equal(h.calls.length,0);
 const both=setup({api:discoveryOf([workCard()])});
 await both.platform.load({page:'projects',tab:'recent',projectScope:'team'});
 assert.equal(both.root.querySelectorAll('.project-tile').length,0);
 assert.equal(both.root.querySelectorAll('.recent-creation-card').length,1);
 assert.ok(both.calls.every(row=>row.path==='/api/v1/discovery'));
 assert.ok(noRecentScope(both));
});
