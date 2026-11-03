// Bounded DOM and API fixtures exercise the real panel without media providers.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import {Document,Element} from '../../support/fixtures/frontend/panel_dom.cjs';

Object.defineProperty(Element.prototype,'isConnected',{get(){for(let n=this;n;n=n.parentElement)if(n===this.ownerDocument.body)return true;return false;}});
Element.prototype.load=function(){};
Element.prototype.pause=function(){this.paused=true;};
Element.prototype.play=async function(){this.paused=false;};
Element.prototype.scrollIntoView=function(){};

async function fixture({interleaved=false}={}){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);
 const memory=new Map(),requests=[],pending={prepare:[],quote:[],save:[]};
 const sessionStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k),get length(){return memory.size;},key:i=>[...memory.keys()][i]};
 const stages=['source','assets','blocking','template','script','video','preview'].map(key=>({key,title:key}));
 const unit=(key,kind='shot')=>({unit_key:key,kind,title:key,description:'提示词 '+key,duration_ms:7000,segments:[],skip_reason:'',lineart_purpose:'none',shot_id:key,professional:{narrative_purpose:'目的',entry_state:'入',exit_state:'出',bridge:'桥',sound_route:'native'}});
 const workflow={workflow:{id:'w',episode_id:'e',title:'流程'},version:{id:'v',version:1},history:[{id:'v',version:1}],definition:{stages},state:{route:'creation',document:{script_text:'剧本',notes:'',template_key:'cinematic',template_text:'模板'},assets:[],units:interleaved?[unit('s1'),unit('b','blocking'),unit('s2')]:[unit('s1'),unit('s2'),unit('b','blocking')],media:[],dependencies:[],blocking_mode:'2d'},episode_assets:[],tasks:[],runs:[],asset_runs:[],batches:[],working_selections:[],revision:1};
 const options={definition:{stages},routes:{creation:'智能创作'},templates:{cinematic:{title:'电影叙事',text:'电影模板'}},nodes:[{id:'e',kind:'episode',title:'第1集'}],models:[{id:'model-a',modality:'video',enabled:true,adapter_available:true,name:'A'},{id:'model-b',modality:'video',enabled:true,adapter_available:true,name:'B'}],media:[],host_available:false,revision:1};
 const api=async(path,init={})=>{
  requests.push({path,init});
  if(path.endsWith('/intelligent-change-preview'))return {sha256:'impact',changes:[],warnings:[],retained_selected_media:[],retained_runs:[],revision:1};
  if(path.endsWith('/intelligent-workflows/w')&&init.method==='PUT')return new Promise((resolve,reject)=>pending.save.push({resolve,reject}));
  if(path.endsWith('/intelligent-drafts'))return new Promise((resolve,reject)=>pending.prepare.push({resolve,reject}));
  if(path.endsWith('/classic-production/quote'))return new Promise((resolve,reject)=>pending.quote.push({resolve,reject}));
  if(path.endsWith('/intelligent-options'))return structuredClone(options);
  if(path.endsWith('/intelligent-workflows/w'))return structuredClone(workflow);
  if(path.includes('/execution-authorizations'))return {items:[]};
  if(path.includes('/working-candidates'))return {items:[],total:0,next_offset:null,revision:1};
  if(path.includes('/working-selections?'))return {items:[],revision:1};
  throw new Error('Unexpected '+path);
 };
 const {createIntelligentProductionPanel}=await loadModule('intelligent-production.js',{document,window:{addEventListener(){}},sessionStorage,crypto:webcrypto,URLSearchParams,setTimeout,clearTimeout,queueMicrotask});
 const panel=createIntelligentProductionPanel({api,session:()=>({csrf:'csrf',revision:1,actor:'actor',writable:true}),setRevision(){}});
 await panel.load(root,'p','e','creation','w');
 const stage=key=>root.querySelector('.ip-stages').querySelectorAll('button').find(button=>button.dataset.stage===key);
 return {root,panel,requests,pending,stage};
}
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(setImmediate);}throw new Error('timed out waiting for controlled request');}
const quoteResult={revision:1,ready:true,generation_quote:{native_units:{},all_prices_known:true,known_subtotals:{}}};

for(const delayed of ['prepare','quote'])test(`changing model invalidates a delayed ${delayed} response`,async()=>{
 const {root,panel,requests,pending,stage}=await fixture();
 try{
  await stage('video').click();const card=root.querySelector('.ip-video-unit'),model=card.querySelector('.ip-unit-generation').querySelector('select');
  const check=card.querySelectorAll('button').find(button=>button.textContent.includes('核对本单元'));
  const confirm=card.querySelectorAll('button').find(button=>button.textContent.includes('确认报价'));
  assert.ok(check&&confirm);model.value='model-a';const first=check.click();await waitFor(()=>pending.prepare.length===1);
  if(delayed==='quote'){pending.prepare[0].resolve({items:[{gaps:[],draft_artifact_id:'draft-a'}],revision:1});await waitFor(()=>pending.quote.length===1);}
  model.value='model-b';await model.dispatch('change');
  if(delayed==='prepare')pending.prepare[0].resolve({items:[{gaps:[],draft_artifact_id:'draft-a'}],revision:1});
  else pending.quote[0].resolve(quoteResult);
  await first;assert.equal(confirm.disabled,true);assert.ok(card.textContent.includes('模型已更改'));
  if(delayed==='prepare')assert.equal(pending.quote.length,0);
  const second=check.click();await waitFor(()=>pending.prepare.length===2);
  const preparations=requests.filter(row=>row.path.endsWith('/intelligent-drafts'));
  assert.equal(JSON.parse(preparations[1].init.body).payload.model_id,'model-b');
  pending.prepare[1].resolve({items:[{gaps:[],draft_artifact_id:'draft-b'}],revision:1});await waitFor(()=>pending.quote.length===(delayed==='quote'?2:1));
  pending.quote.at(-1).resolve(quoteResult);await second;assert.equal(confirm.disabled,false);
  assert.equal(requests.some(row=>row.path.endsWith('/classic-production/generate')),false);
 }finally{panel.suspend();}
});

test('save response keeps the stage selected while the request was in flight',async()=>{
 const {root,panel,pending,stage}=await fixture();
 try{
  assert.ok(root.querySelector('.ip-word-count').textContent.includes('2/50000'));
  const save=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='确认影响并保存全部');assert.ok(save);
  await save.click();const saving=save.click();await waitFor(()=>pending.save.length===1);
  await stage('template').click();assert.equal(root.dataset.stage,'template');
  pending.save[0].resolve({id:'w',revision:2});await saving;assert.equal(root.dataset.stage,'template');
 }finally{panel.suspend();}
});

test('move controls reorder only matching unit types even when their data are interleaved',async()=>{
 const {root,panel,stage}=await fixture({interleaved:true});
 try{
  await stage('script').click();let cards=root.querySelectorAll('.ip-unit');assert.deepEqual(cards.map(card=>card.dataset.unitKey),['s1','s2']);
  const down=cards[0].querySelectorAll('button').find(button=>button.textContent==='下移');assert.ok(down);await down.click();
  cards=root.querySelectorAll('.ip-unit');assert.deepEqual(cards.map(card=>card.dataset.unitKey),['s2','s1']);
  assert.equal(cards[1].querySelectorAll('button').find(button=>button.textContent==='下移').disabled,true);
  await stage('blocking').click();assert.deepEqual(root.querySelectorAll('.ip-unit').map(card=>card.dataset.unitKey),['b']);
 }finally{panel.suspend();}
});
