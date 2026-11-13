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
 {id:'personal',name:'个人项目',owner_kind:'personal',owner_name:'me',workspace_id:'personal-space',workspace_name:'个人空间',created_by:'me',access_capabilities:['read','edit','manage'],storage_policy:'postgres-series-v1'},
 {id:'team',name:'团队项目',owner_kind:'team',owner_name:'协作团队',workspace_id:'team-space',workspace_name:'协作团队',created_by:'other',access_capabilities:['read','edit'],storage_policy:'postgres-series-v1'},
 {id:'history',name:'历史项目',owner_kind:'personal',owner_name:'me',workspace_id:'personal-space',created_by:null,access_capabilities:['read','edit','manage'],storage_policy:'postgres-series-v1'}];
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
test('project directory separates durable user/team ownership from participation without a current workspace',async()=>{
 const h=setup();await h.platform.load({page:'projects'});assert.deepEqual(h.notices,[]);assert.deepEqual(ids(h),['personal','team','history']);assert.ok(!h.root.textContent.includes('未归属'));assert.ok(!h.root.textContent.includes('当前空间'));
 const chooser=h.root.querySelectorAll('select').find(node=>node.getAttribute('aria-label')==='项目归属与参与');chooser.value='all';await chooser.dispatch('change');assert.deepEqual(h.routes.at(-1),['projects',null,null,{project_scope:'all'}]);
 await h.platform.load({page:'projects',projectScope:'all'});assert.deepEqual(ids(h),['personal','team','history']);assert.ok(h.root.textContent.includes('创建者未记录'));
 await h.platform.load({page:'projects',projectScope:'created'});assert.deepEqual(ids(h),['personal']);
 await h.platform.load({page:'projects',projectScope:'participating'});assert.deepEqual(ids(h),['team','history']);
 await h.platform.load({page:'projects',projectScope:'personal'});assert.deepEqual(ids(h),['personal','history']);
 await h.platform.load({page:'projects',projectScope:'team'});assert.deepEqual(ids(h),['team']);
 const dialogButton=h.root.querySelectorAll('button').find(row=>row.textContent.includes('新建项目'));await dialogButton.click();const dialog=h.root.querySelector('dialog');assert.ok(dialog.textContent.includes('项目归属'));const owner=dialog.querySelectorAll('select').find(row=>row.getAttribute('aria-label')==='项目归属');assert.equal(owner.value,'');assert.ok(owner.options.some(row=>row.value==='team-space'));
});
test('canvas and generated media directories send explicit ownership or relation to the authoritative list',async()=>{
 const h=setup();await h.platform.load({page:'projects',tab:'canvases',projectScope:'team'});
 assert.ok(h.calls.some(row=>row.path.startsWith('/api/v1/canvas-library?')&&new URL(row.path,'http://test').searchParams.get('owner_kind')==='team'));
 await h.platform.load({page:'projects',tab:'media',projectScope:'participating'});
 assert.ok(h.calls.some(row=>row.path.startsWith('/api/v1/project-media?')&&new URL(row.path,'http://test').searchParams.get('relation')==='participating'));
 assert.ok(h.root.querySelectorAll('a').filter(a=>a.href?.includes('tab=canvases')).some(a=>a.href.includes('project_scope=participating')));
});
