import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
const doc=new Document('');doc.documentElement=doc.createElement('html');doc.addEventListener=()=>{};doc.removeEventListener=()=>{};globalThis.document=doc;
globalThis.CSS={escape:value=>String(value)};globalThis.window={location:{protocol:'http:',hostname:'127.0.0.1'},localStorage:{getItem(){return null;},setItem(){},removeItem(){}}};
const matches=Element.prototype.matches;
Element.prototype.matches=function(selector){if(selector==='details[open]')return this.tagName==='DETAILS'&&this.open;const keyed=selector.match(/^\[data-focus-key="([^"]+)"\]$/);return keyed?this.dataset.focusKey===keyed[1]:matches.call(this,selector);};
Element.prototype.focus=function(options){doc.activeElement=this;this.focusOptions=options;};
const store=await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createCharacterStudio}=await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const flush=()=>new Promise(resolve=>setTimeout(resolve,10));

test('nested work area keeps its scroll, focus and expanded parameters through consecutive choices and auth updates',async()=>{
 let authResolve;const auth=new Promise(resolve=>{authResolve=resolve;});
 const workspace=doc.createElement('div'),root=doc.createElement('section');doc.body.append(workspace);workspace.append(root);
 const studio=createCharacterStudio(root,{api:async()=>auth,session:()=>({actor:'scroll-test',csrf:'test'}),notice(){}});
 const replace=root.replaceChildren.bind(root);
 // A real browser clamps an ancestor when replaceChildren temporarily removes its long content.
 root.replaceChildren=(...nodes)=>{replace(...nodes);workspace.scrollTop=0;workspace.scrollLeft=0;root.scrollTop=0;};
 try{
  await studio.load();await flush();workspace.scrollTop=512;workspace.scrollLeft=17;root.scrollTop=24;
  let select=root.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='接口协议');select.focus();select.value='gpt';select.onchange();await flush();
  assert.equal(store.getState().apiConfig.activeProvider,'gpt');assert.equal(workspace.scrollTop,512);assert.equal(workspace.scrollLeft,17);assert.equal(root.scrollTop,24);
  const current=()=>root.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='接口协议');assert.notEqual(doc.activeElement,select);assert.equal(doc.activeElement,current());assert.deepEqual(doc.activeElement.focusOptions,{preventScroll:true});
  root.querySelector('.cs-more').open=true;
  select=root.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='模型 ID');select.focus();select.value='custom';select.onchange();await flush();
  assert.equal(store.getState().apiConfig.providers.gpt.model,'custom');assert.equal(workspace.scrollTop,512);assert.equal(root.querySelector('.cs-more').open,true);
  select=root.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='渲染质量 (quality)');select.focus();select.value='medium';select.onchange();await flush();
  assert.equal(store.getState().apiConfig.gptParams.quality,'medium');assert.equal(workspace.scrollTop,512);assert.equal(doc.activeElement.getAttribute('aria-label'),'渲染质量 (quality)');
  authResolve({codex:{status:'unauthorized',ready:false,message:'synthetic status'},grok:{ready:false},agy:{ready:false}});await flush();
  assert.equal(workspace.scrollTop,512);assert.equal(root.querySelector('.cs-more').open,true);assert.equal(doc.activeElement.getAttribute('aria-label'),'渲染质量 (quality)');
 }finally{studio.suspend();workspace.remove();}
});

test('random recipe success opts into a three-second notice without timing unrelated errors',async()=>{
 const messages=[];store.configureStudio({notice:(...args)=>messages.push(args),csrf:()=>'',api:async url=>url.includes('pose-gallery/random')?{}:{}});
 await store.randomizeAll();const success=messages.find(([message])=>message.startsWith('已随机抽取一套角色配方'));
 assert.ok(success);assert.deepEqual(success[1],{duration:3000});
});
