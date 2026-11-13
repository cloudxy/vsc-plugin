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
function setup(){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);globalThis.document=document;
 if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
 const storage=new Map();globalThis.sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
 const session={actor:'me',ownerships:[{id:'team-space',name:'协作团队',kind:'studio',roles:['editor']}],csrf:'csrf',writeAvailable:true,writable:true};
 const routes=[],calls=[],notices=[];
 const ctx={session:()=>session,projects:()=>rows,notice:value=>notices.push(String(value)),navigate:async(...args)=>routes.push(args),refreshProjects:async()=>{},setRevision(){},api:async(path,options={})=>{calls.push({path,options});throw new Error('Synthetic read stopped');}};
 return {root,session,routes,calls,notices,platform:createProductionPlatform(root,ctx)};
}
const ids=h=>h.root.querySelectorAll('.project-tile').filter(row=>row.dataset.projectId).map(row=>row.dataset.projectId);
test('three visible tabs partition every authorized project by owner, independent of creator',async()=>{
 const h=setup();await h.platform.load({page:'projects'});assert.deepEqual(h.notices,[]);assert.deepEqual(ids(h),['personal','history']);
 const tabs=h.root.querySelectorAll('a').filter(node=>node.getAttribute('role')==='tab');assert.deepEqual(tabs.map(node=>node.textContent),['个人项目','参与项目','团队项目']);assert.equal(tabs[0].getAttribute('aria-selected'),'true');assert.equal(h.root.querySelectorAll('select').length,0);
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
