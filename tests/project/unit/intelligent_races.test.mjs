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

async function fixture({interleaved=false,emptyWorkflow=false,delayPreview=false,withWarnings=false,historical=false,legacyAsset=false,initialTarget='w',initialEpisode='e',autoLoad=true,configure,intercept}={}){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);
 const memory=new Map(),requests=[],opened=[],revisions=[],pending={prepare:[],quote:[],save:[],preview:[]};
 const sessionStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k),get length(){return memory.size;},key:i=>[...memory.keys()][i]};
 const stages=['source','assets','blocking','template','script','video','preview'].map(key=>({key,title:key}));
 const unit=(key,kind='shot')=>({unit_key:key,kind,title:key,description:'提示词 '+key,duration_ms:7000,segments:[],skip_reason:'',lineart_purpose:'none',shot_id:key,professional:{narrative_purpose:'目的',entry_state:'入',exit_state:'出',bridge:'桥',sound_route:'native'}});
 const workflow={workflow:{id:'w',episode_id:'e',title:'流程'},version:{id:'v',version:1},history:[{id:'v',version:1}],definition:{stages},state:{route:'creation',document:{script_text:'剧本',notes:'',template_key:'cinematic',template_text:'模板'},assets:[],units:interleaved?[unit('s1'),unit('b','blocking'),unit('s2')]:[unit('s1'),unit('s2'),unit('b','blocking')],media:[],dependencies:[],blocking_mode:'2d'},episode_assets:[],tasks:[],runs:[],asset_runs:[],batches:[],working_selections:[],revision:1};
 if(emptyWorkflow)workflow.state.units=[];if(historical)workflow.history=[{id:'v-current',version:2},...workflow.history];if(legacyAsset)workflow.episode_assets=[{id:'legacy',asset_key:'asset:legacy',asset_kind:'object',name:'旧物件',revision:1,forms:[{form_key:'master',name:'默认',current_version_id:'form-v1',media_id:null}]}];
 const options={definition:{stages},routes:{creation:'智能创作'},templates:{cinematic:{title:'电影叙事',text:'电影模板'}},nodes:[{id:'e',kind:'episode',title:'第1集'}],models:[{id:'model-a',modality:'video',enabled:true,adapter_available:true,name:'A'},{id:'model-b',modality:'video',enabled:true,adapter_available:true,name:'B'}],media:[],host_available:false,revision:1};
 configure?.({workflow,options,memory});
 const api=async(path,init={})=>{
  requests.push({path,init});
  const override=intercept?.(path,init,{workflow,options});if(override!==undefined)return override;
  if(path.endsWith('/intelligent-change-preview')){if(delayPreview)return new Promise(resolve=>pending.preview.push(resolve));return {sha256:'impact',changes:[],warnings:withWarnings?[{message:'需要审阅'}]:[],retained_selected_media:[],retained_runs:[],revision:1};}
  if(path.endsWith('/intelligent-workflows/w')&&init.method==='PUT')return new Promise((resolve,reject)=>pending.save.push({resolve,reject}));
  if(path.endsWith('/intelligent-drafts'))return new Promise((resolve,reject)=>pending.prepare.push({resolve,reject}));
  if(path.endsWith('/classic-production/quote'))return new Promise((resolve,reject)=>pending.quote.push({resolve,reject}));
  if(path.endsWith('/intelligent-options'))return structuredClone(options);
  if(path.endsWith('/intelligent-workflows/w'))return structuredClone(workflow);
  if(/\/intelligent-workflows(?:\?|$)/.test(path))return {items:[{id:'w',title:'流程',episode_id:'e'}],revision:1};
  if(path.includes('/execution-authorizations'))return {items:[]};
  if(path.includes('/working-candidates'))return {items:[],total:0,next_offset:null,revision:1};
  if(path.includes('/working-selections?'))return {items:[],revision:1};
  throw new Error('Unexpected '+path);
 };
 const {createIntelligentProductionPanel}=await loadModule('intelligent-production.js',{document,window:{addEventListener(){}},sessionStorage,crypto:webcrypto,URLSearchParams,setTimeout,clearTimeout,queueMicrotask});
 const panel=createIntelligentProductionPanel({api,session:()=>({csrf:'csrf',revision:1,actor:'actor',writable:true}),setRevision:(value,project)=>revisions.push({value,project}),opened:(...args)=>opened.push(args)});
 if(autoLoad)await panel.load(root,'p',initialEpisode,'creation',initialTarget);
 const stage=key=>root.querySelector('.ip-stages').querySelectorAll('button').find(button=>button.dataset.stage===key);
 return {root,panel,requests,pending,stage,memory,opened,revisions,workflow};
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
  const save=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');assert.ok(save);
  const script=root.querySelector('.ip-script-stage').querySelector('textarea');script.value='修改后的剧本';await script.dispatch('input');
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


test('next step without edits navigates once and does not create a new version',async()=>{
 const {root,panel,requests}=await fixture();
 try{
  const next=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');
  await next.click();assert.equal(root.dataset.stage,'assets');
  assert.equal(requests.some(row=>row.path.endsWith('/intelligent-change-preview')||row.init.method==='PUT'),false);
 }finally{panel.suspend();}
});


test('initial screenplay edit advances with a single action after safe impact preview',async()=>{
 const {root,panel,requests,pending}=await fixture({emptyWorkflow:true});
 try{
  const script=root.querySelector('.ip-script-stage').querySelector('textarea');script.value='新增剧本';await script.dispatch('input');
  const next=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');const saving=next.click();
  await waitFor(()=>pending.save.length===1);assert.equal(requests.filter(row=>row.path.endsWith('/intelligent-change-preview')).length,1);
  pending.save[0].resolve({id:'w',revision:2});await saving;assert.equal(root.dataset.stage,'assets');
 }finally{panel.suspend();}
});


for(const change of ['draft','stage'])test(`initial quick save does not submit when ${change} changes during preview`,async()=>{
 const {root,panel,requests,pending,stage}=await fixture({emptyWorkflow:true,delayPreview:true});
 try{
  const script=root.querySelector('.ip-script-stage').querySelector('textarea');script.value='初稿';await script.dispatch('input');
  const next=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');const waiting=next.click();await waitFor(()=>pending.preview.length===1);
  if(change==='draft'){script.value='修改中';await script.dispatch('input');}else await stage('template').click();
  pending.preview[0]({sha256:'impact',changes:[],warnings:[],retained_selected_media:[],retained_runs:[],revision:1});await waiting;
  assert.equal(requests.some(row=>row.init.method==='PUT'),false);
 }finally{panel.suspend();}
});


test('quick save keeps the review step when a warning exists',async()=>{
 const {root,panel,requests}=await fixture({emptyWorkflow:true,withWarnings:true});
 try{
  const script=root.querySelector('.ip-script-stage').querySelector('textarea');script.value='初稿';await script.dispatch('input');
  const next=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');await next.click();
  assert.equal(requests.some(row=>row.init.method==='PUT'),false);assert.match(root.querySelector('.ip-impact').textContent,/需要审阅/);
 }finally{panel.suspend();}
});

test('historical versions remain read-only',async()=>{
 const {root,panel,requests}=await fixture({historical:true});
 try{
  const next=root.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='下一步');assert.equal(next.disabled,true);
  assert.equal(requests.some(row=>row.init.method==='PUT'),false);
 }finally{panel.suspend();}
});


test('explicit review discards a stale preview after an edit',async()=>{
 const {root,panel,requests,pending}=await fixture({delayPreview:true});
 try{
  const script=root.querySelector('.ip-script-stage').querySelector('textarea');script.value='初稿';await script.dispatch('input');
  const review=root.querySelectorAll('button').find(button=>button.textContent.includes('查看修改影响'));assert.ok(review);const waiting=review.click();await waitFor(()=>pending.preview.length===1);
  script.value='修改中';await script.dispatch('input');pending.preview[0]({sha256:'old',changes:[],warnings:[],retained_selected_media:[],retained_runs:[],revision:1});await waiting;
  assert.equal(root.querySelector('.ip-impact'),null);assert.equal(requests.some(row=>row.init.method==='PUT'),false);
 }finally{panel.suspend();}
});

test('legacy object appears in episode prop column while retaining its type',async()=>{
 const {root,panel,stage}=await fixture({legacyAsset:true});
 try{
  await stage('assets').click();const columns=root.querySelectorAll('.ip-asset-column');assert.equal(columns.length,3);
  const card=columns[2].querySelector('.ip-asset-card');assert.ok(card);assert.match(card.textContent,/旧物件/);assert.equal(card.querySelector('select').value,'object');assert.equal(root.querySelector('.ip-other-assets').hidden,true);
 }finally{panel.suspend();}
});

test('default episode entry resumes its only workflow with server route, definition and local step',async()=>{
 const {root,panel,requests,opened}=await fixture({initialTarget:null,configure({workflow,options,memory}){
  workflow.state.route='storyboard';options.routes.storyboard='智能分镜';
  workflow.definition.stages=workflow.definition.stages.filter(stage=>['source','template','preview'].includes(stage.key));
  memory.set('vsc-intelligent-draft:p:w:stage',JSON.stringify('template'));
 }});
 try{
  assert.deepEqual(opened,[['w','p','e']]);assert.equal(root.dataset.stage,'template');
  assert.deepEqual(root.querySelector('.ip-stages').querySelectorAll('button').map(button=>button.dataset.stage),['source','template','preview']);
  assert.equal(JSON.parse(root.querySelector('.ip-advanced').querySelector('textarea').value).route,'storyboard');
  assert.equal(root.querySelector('.ip-create'),null);assert.equal(root.querySelector('.ip-list'),null);
  assert.ok(requests.some(row=>row.path.endsWith('/intelligent-workflows?episode_id=e')));
  assert.equal(requests.some(row=>row.init.method),false);
 }finally{panel.suspend();}
});

test('explicit target opens directly without choosing from the episode list',async()=>{
 const {root,panel,requests,opened}=await fixture();
 try{
  assert.deepEqual(opened,[['w','p','e']]);assert.equal(root.dataset.stage,'source');
  assert.equal(requests.some(row=>/\/intelligent-workflows(?:\?|$)/.test(row.path)),false);
 }finally{panel.suspend();}
});

test('empty episode shows the creation first step only after a successful empty list',async()=>{
 let resolveList;const {root,panel,requests,opened,workflow}=await fixture({autoLoad:false,intercept(path,init){
  if(path.endsWith('/intelligent-workflows?episode_id=e'))return new Promise(resolve=>{resolveList=resolve;});
  if(path.endsWith('/intelligent-workflows')&&init.method==='POST')return {id:'w',revision:2};
 }});
 try{
  const loading=panel.load(root,'p','e');await waitFor(()=>resolveList);
  assert.equal(root.querySelector('.ip-create'),null);assert.equal(root.querySelector('.ip-stages'),null);
  resolveList({items:[],revision:1});await loading;
  const form=root.querySelector('.ip-create');assert.ok(form);
  assert.equal(root.querySelector('.ip-stages').querySelector('button').getAttribute('aria-current'),'step');
  assert.equal(requests.some(row=>row.init.method),false);
  const script=form.querySelector('textarea');script.value='新的整集剧本';
  await form.querySelector('button').click();
  const writes=requests.filter(row=>row.init.method==='POST');assert.equal(writes.length,1);
  const payload=JSON.parse(writes[0].init.body).payload;
  assert.equal(payload.episode_id,'e');assert.equal(payload.route,'creation');assert.equal(payload.script_text,'新的整集剧本');
  assert.deepEqual(opened,[['w','p','e']]);assert.equal(workflow.state.document.script_text,'剧本');
 }finally{panel.suspend();}
});

for(const failure of ['list','detail'])test(`${failure} failure offers read retry without creation or fallback`,async()=>{
 let attempts=0;const {root,panel,requests,opened}=await fixture({initialTarget:null,configure({workflow,memory}){
  const state=structuredClone(workflow.state);state.document.script_text='失败重试前的未保存稿';
  memory.set('vsc-intelligent-draft:p:w',JSON.stringify({version:'v',state,stage:'source'}));
 },intercept(path){
  const matches=failure==='list'?path.endsWith('/intelligent-workflows?episode_id=e'):path.endsWith('/intelligent-workflows/w');
  if(matches&&attempts++===0)throw new Error('连接暂时失败');
 }});
 try{
  assert.match(root.textContent,/连接暂时失败/);assert.equal(root.querySelector('.ip-create'),null);
  assert.equal(root.querySelector('.ip-list'),null);assert.equal(opened.length,0);
  await root.querySelector('button').click();assert.deepEqual(opened,[['w','p','e']]);
  assert.equal(root.querySelector('.ip-script-stage').querySelector('textarea').value,'失败重试前的未保存稿');
  assert.equal(requests.some(row=>row.init.method),false);
 }finally{panel.suspend();}
});

test('multiple episode workflows require a choice and preserve the explicit creation entry',async()=>{
 const {root,panel,requests,opened}=await fixture({initialTarget:null,intercept(path,init,{workflow}){
  if(path.endsWith('/intelligent-workflows?episode_id=e'))return {items:[{id:'w',title:'最近创建'},{id:'older',title:'明确选择'}],revision:1};
  if(path.endsWith('/intelligent-workflows/older'))return {...structuredClone(workflow),workflow:{id:'older',title:'明确选择',episode_id:'e'}};
 }});
 try{
  assert.equal(opened.length,0);assert.equal(root.querySelector('.ip-create'),null);assert.equal(root.querySelector('.ip-stages'),null);
  const list=root.querySelector('.ip-list');assert.equal(list.querySelectorAll('article').length,2);
  const create=root.children.find(node=>node.tagName==='BUTTON');assert.ok(create);await create.click();
  assert.ok(root.querySelector('.ip-create'));assert.equal(requests.some(row=>row.init.method),false);
  await root.children.find(node=>node.tagName==='BUTTON').click();
  await root.querySelector('.ip-list').querySelectorAll('button')[1].click();
  assert.deepEqual(opened,[['older','p','e']]);assert.equal(root.querySelector('h1').textContent,'明确选择');
 }finally{panel.suspend();}
});

test('back to workflow list does not automatically reopen its only row',async()=>{
 const {root,panel,opened}=await fixture({initialTarget:null});
 try{
  const back=root.querySelectorAll('button').find(button=>button.textContent.includes('返回流程列表'));assert.ok(back);await back.click();
  assert.ok(root.querySelector('.ip-list'));assert.equal(root.querySelector('.ip-create'),null);assert.equal(opened.length,1);
  await root.children.find(node=>node.tagName==='BUTTON').click();assert.ok(root.querySelector('.ip-create'));
 }finally{panel.suspend();}
});

test('project-wide entry does not infer an episode from a single workflow',async()=>{
 const {root,panel,opened}=await fixture({initialTarget:null,initialEpisode:null});
 try{assert.ok(root.querySelector('.ip-list'));assert.equal(opened.length,0);assert.equal(root.querySelector('.ip-create'),null);}
 finally{panel.suspend();}
});

for(const phase of ['options','list','detail'])for(const outcome of ['success','failure'])test(`late ${phase} ${outcome} cannot replace another project entry`,async()=>{
 let delayed;const {root,panel,opened,revisions}=await fixture({autoLoad:false,intercept(path,init,{workflow,options}){
  if(path.startsWith('/api/v1/projects/new/')&&path.endsWith('/intelligent-workflows/w'))return {...structuredClone(workflow),workflow:{id:'w',episode_id:'new-e',title:'当前流程'},revision:9};
  const matches=phase==='options'?path.endsWith('/intelligent-options'):phase==='list'?path.endsWith('/intelligent-workflows?episode_id=e'):path.endsWith('/intelligent-workflows/w');
  if(path.startsWith('/api/v1/projects/p/')&&matches)return new Promise((resolve,reject)=>{delayed={resolve,reject,value:phase==='options'?structuredClone(options):phase==='list'?{items:[{id:'w'}],revision:1}:structuredClone(workflow)};});
 }});
 try{
  const previous=panel.load(root,'p','e');await waitFor(()=>delayed);
  await panel.load(root,'new','new-e','creation','w');const current=root.textContent,revisionCount=revisions.length;
  if(outcome==='failure')delayed.reject(new Error('旧范围读取失败'));else delayed.resolve(delayed.value);
  await previous;assert.equal(root.textContent,current);assert.equal(revisions.length,revisionCount);
  assert.deepEqual(opened,[['w','new','new-e']]);assert.equal(root.querySelector('.ip-create'),null);
 }finally{panel.suspend();}
});

test('resuming preserves the local draft while rejecting an obsolete cached step',async()=>{
 const {root,panel,requests}=await fixture({initialTarget:null,configure({workflow,memory}){
  const state=structuredClone(workflow.state);state.document.script_text='尚未保存的剧本';
  memory.set('vsc-intelligent-draft:p:w',JSON.stringify({version:'v',state,stage:'removed-step'}));
  memory.set('vsc-intelligent-draft:p:w:stage',JSON.stringify('removed-step'));
 }});
 try{
  assert.equal(root.dataset.stage,'source');assert.equal(root.querySelector('.ip-script-stage').querySelector('textarea').value,'尚未保存的剧本');
  assert.match(root.querySelector('.ip-status').textContent,/本机草稿/);assert.equal(requests.some(row=>row.init.method),false);
 }finally{panel.suspend();}
});
