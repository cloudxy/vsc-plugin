// Offline unit tests for Module 10 (/agent) workflow modes, reset impact preview,
// @mention asset/blocking binding, and fullscreen prompt editor.
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

async function createFixture({emptyList=false,configure}={}){
 const document=new Document(''),root=document.createElement('section');document.body.append(root);
 const memory=new Map(),requests=[],navigations=[];
 const sessionStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k),get length(){return memory.size;},key:i=>[...memory.keys()][i]};
 const stages=['source','assets','blocking','template','script','video','preview'].map(key=>({key,title:key}));
 const workflow={
  workflow:{id:'w',episode_id:'e',title:'第1集智能流程'},
  version:{id:'v1',version:1},
  history:[{id:'v1',version:1}],
  definition:{stages},
  state:{
   route:'storyboard',
   blocking_mode:'2d',
   document:{script_text:'第一场 夜 走廊',notes:'',template_key:'cinematic',template_text:'电影模板',skip_blocking_reason:''},
   assets:[{asset_key:'asset-role_form-1',asset_id:'a-1',spec_id:'sp-1',episode_asset_form_version_id:'fv-1'}],
   units:[
    {unit_key:'b1',kind:'blocking',title:'走廊站位',description:'双人对峙',duration_ms:4000,segments:[],skip_reason:'',lineart_purpose:'none',shot_id:'shot-b1'},
    {unit_key:'s1',kind:'shot',title:'镜头1',description:'推近特写',duration_ms:5000,segments:[],skip_reason:'',lineart_purpose:'none',shot_id:'shot-1',asset_keys:[],professional:{narrative_purpose:'',entry_state:'',exit_state:'',bridge:'',sound_route:'native'}}
   ],
   media:[{unit_key:'b1',purpose:'blocking',media_id:'m-block'}],
   dependencies:[],
   template_artifact_id:'tpl-1'
  },
  episode_assets:[
   {id:'ea-1',asset_key:'asset-role',asset_kind:'character',name:'苏念',revision:1,forms:[{form_key:'form-1',name:'夜行装',current_version_id:'fv-1',media_id:'m-role',source_asset_id:'a-1',spec_id:'sp-1'}]}
  ],
  tasks:[],runs:[],asset_runs:[],batches:[],working_selections:[],revision:1
 };
 const options={
  definition:{stages},
  routes:{storyboard:'智能分镜',creation:'智能创作'},
  templates:{cinematic:{title:'电影叙事',text:'电影模板'}},
  nodes:[{id:'e',kind:'episode',title:'第1集'},{id:'shot-1',kind:'shot',parent_id:'e',title:'镜头1'}],
  models:[{id:'model-v',modality:'video',enabled:true,adapter_available:true,name:'Seedance 2.5'}],
  media:[{id:'m-role',modality:'image',name:'苏念立绘'},{id:'m-block',modality:'image',name:'走廊站位图'}],
  host_available:false,
  revision:1
 };
 configure?.({workflow,options,memory});
 const api=async(path,init={})=>{
  requests.push({path,init});
  if(path.endsWith('/intelligent-options'))return structuredClone(options);
  if(path.endsWith('/intelligent-workflows')&&init.method==='POST')return {id:'w',revision:2};
  if(/\/intelligent-workflows(?:\?|$)/.test(path))return {items:emptyList?[]:[{id:'w',title:'第1集智能流程',episode_id:'e'}],revision:1};
  if(path.endsWith('/intelligent-workflows/w'))return structuredClone(workflow);
  if(path.includes('/execution-authorizations'))return {items:[]};
  if(path.includes('/working-candidates'))return {items:[],total:0,next_offset:null,revision:1};
  if(path.includes('/working-selections?'))return {items:[],revision:1};
  throw new Error('Unexpected '+path);
 };
 const mod=await loadModule('intelligent-production.js',{document,window:{addEventListener(){}},sessionStorage,crypto:webcrypto,URLSearchParams,setTimeout,clearTimeout,queueMicrotask});
 const panel=mod.createIntelligentProductionPanel({
  api,
  session:()=>({csrf:'csrf',revision:1,actor:'actor',writable:true}),
  navigate:async(page,episode,project,extra)=>navigations.push({page,episode,project,extra})
 });
 return {mod,panel,root,memory,requests,navigations,workflow};
}

test('consumePendingAgentWorkflow matches scope once and maps agentType 4/2/5',async()=>{
 const {mod}=await createFixture({emptyList:true});
 const storeMap=new Map();
 const storage={get:k=>storeMap.get(k)||null,put:(k,v)=>{if(v===null)storeMap.delete(k);else storeMap.set(k,v);}};
 storage.put('ai_tools_pending_agent_workflow',{projectId:'p-other',episodeId:'e-1',agentType:4});
 assert.equal(mod.consumePendingAgentWorkflow(storage,'p-1','e-1'),null);
 assert.ok(storeMap.has('ai_tools_pending_agent_workflow'));

 const storyboard=mod.consumePendingAgentWorkflow(storage,'p-other','e-1');
 assert.equal(storyboard.key,'storyboard');
 assert.equal(storyboard.route,'storyboard');
 assert.equal(storeMap.has('ai_tools_pending_agent_workflow'),false);

 storage.put('ai_tools_pending_agent_workflow',{projectId:'p-1',episodeId:'e-1',agentType:2});
 const creation=mod.consumePendingAgentWorkflow(storage,'p-1','e-1');
 assert.equal(creation.key,'creation');
 assert.equal(creation.blocking_mode,'skip');

 storage.put('ai_tools_pending_agent_workflow',{projectId:'p-1',episodeId:'e-1',agentType:5});
 const overseas=mod.consumePendingAgentWorkflow(storage,'p-1','e-1');
 assert.equal(overseas.key,'overseas_remake');
});

test('createForm 3-card workflow selector switches between Seedance2.5 modes and overseas remake handoff',async()=>{
 const {panel,root,memory,requests,navigations}=await createFixture({
  emptyList:true,
  configure({memory}){
   memory.set('ai_tools_pending_agent_workflow',JSON.stringify({projectId:'p',episodeId:'e',agentType:4}));
  }
 });
 try{
  await panel.load(root,'p','e','creation',null);
  const cards=root.querySelectorAll('.ip-mode-card');
  assert.equal(cards.length,3);
  assert.equal(cards[0].classList.contains('is-selected'),true);
  assert.match(cards[0].textContent,/Seedance2\.5 智能分镜模式/);
  assert.match(cards[1].textContent,/Seedance2\.5 智能创作模式/);
  assert.match(cards[2].textContent,/短剧出海转绘/);

  // Selecting overseas remake navigates to text-tools overseas without creating workflow
  const overseasRadio=cards[2].querySelector('input');
  overseasRadio.checked=true;await overseasRadio.dispatch('change');
  const submitBtn=root.querySelector('.ip-create').querySelector('button');
  await submitBtn.click();
  assert.equal(navigations.length,1);
  assert.equal(navigations[0].page,'text-tools');
  assert.equal(navigations[0].extra.tool,'overseas');
  assert.equal(requests.some(r=>r.init.method==='POST'),false);

  // Selecting Seedance2.5 storyboard mode posts route='storyboard'
  const storyboardRadio=cards[0].querySelector('input');
  storyboardRadio.checked=true;await storyboardRadio.dispatch('change');
  root.querySelector('.ip-create').querySelector('textarea').value='第一集完整剧本';
  await submitBtn.click();
  const post=requests.find(r=>r.init.method==='POST'&&r.path.endsWith('/intelligent-workflows'));
  assert.ok(post);
  assert.equal(JSON.parse(post.init.body).payload.route,'storyboard');
 }finally{panel.suspend();}
});

test('workflow menu mode dialog and episode reset preview dialog guard state transitions',async()=>{
 const {panel,root}=await createFixture();
 try{
  await panel.load(root,'p','e','storyboard','w');
  // Switch mode via workflow menu dialog
  const switchBtn=root.querySelectorAll('button').find(b=>b.textContent==='切换制作流程模式');
  assert.ok(switchBtn);
  await switchBtn.click();
  const modeDialog=root.querySelector('.ip-mode-dialog');
  assert.ok(modeDialog);
  const creationRadio=modeDialog.querySelectorAll('.ip-mode-card')[1].querySelector('input');
  creationRadio.checked=true;await creationRadio.dispatch('change');
  await modeDialog.querySelector('.ip-mode-confirm').click();

  const draftAfterSwitch=JSON.parse(root.querySelector('.ip-advanced').querySelector('textarea').value);
  assert.equal(draftAfterSwitch.route,'creation');
  assert.equal(draftAfterSwitch.blocking_mode,'skip');
  assert.match(draftAfterSwitch.document.skip_blocking_reason,/跳过站位/);

  // Episode reset dialog shows impact counts, cancel preserves units, confirm clears draft units/assets/media
  const resetBtn=root.querySelector('.ip-source-settings').querySelectorAll('button').find(b=>b.textContent.includes('重置'));
  assert.ok(resetBtn);
  await resetBtn.click();
  let resetDialog=root.querySelector('.ip-reset-dialog');
  assert.ok(resetDialog);
  assert.match(resetDialog.textContent,/1 项固定资产关联/);
  assert.match(resetDialog.textContent,/2 个站位与分镜单元/);
  const cancelBtn=resetDialog.querySelectorAll('button').find(b=>b.textContent==='取消');
  await cancelBtn.click();
  assert.equal(JSON.parse(root.querySelector('.ip-advanced').querySelector('textarea').value).units.length,2);

  await resetBtn.click();
  resetDialog=root.querySelector('.ip-reset-dialog');
  const confirmReset=resetDialog.querySelectorAll('button').find(b=>b.textContent==='确认重置本集流程');
  await confirmReset.click();
  const cleared=JSON.parse(root.querySelector('.ip-advanced').querySelector('textarea').value);
  assert.equal(cleared.units.length,0);
  assert.equal(cleared.assets.length,0);
  assert.equal(cleared.media.length,0);
  assert.equal(cleared.document.script_text,'第一场 夜 走廊');
 }finally{panel.suspend();}
});

test('@mention chips bind episode assets/blocking references and fullscreen editor stays synchronized',async()=>{
 const {panel,root}=await createFixture();
 try{
  await panel.load(root,'p','e','storyboard','w');
  const videoTab=root.querySelector('.ip-stages').querySelectorAll('button').find(b=>b.dataset.stage==='video');
  await videoTab.click();
  const card=root.querySelector('.ip-video-unit');
  const chips=card.querySelectorAll('.ip-mention-chip');
  assert.equal(chips.length,2);
  assert.equal(chips[0].textContent,'@苏念');
  assert.equal(chips[1].textContent,'@走廊站位');

  await chips[0].click();
  await chips[1].click();
  const prompt=card.querySelector('.ip-prompt').querySelector('textarea');
  assert.match(prompt.value,/@苏念/);
  assert.match(prompt.value,/@走廊站位/);

  // Open fullscreen prompt editor and edit text
  const expandBtn=card.querySelector('.ip-prompt-expand');
  await expandBtn.click();
  const expandDialog=root.querySelector('.ip-expand-dialog');
  assert.ok(expandDialog);
  const expandArea=expandDialog.querySelector('.ip-expand-textarea');
  assert.equal(expandArea.value,prompt.value);
  expandArea.value=prompt.value+'电影级逆光雨夜';
  await expandArea.dispatch('input');
  assert.equal(prompt.value,expandArea.value);
  assert.equal(card.querySelector('.ip-prompt-count').textContent,expandArea.value.length+' 字');
  await expandDialog.querySelectorAll('button').find(b=>b.textContent==='完成编辑').click();

  const savedDraft=JSON.parse(root.querySelector('.ip-advanced').querySelector('textarea').value);
  const shotUnit=savedDraft.units.find(u=>u.unit_key==='s1');
  assert.ok(shotUnit.asset_keys.includes('asset-role_form-1'));
  assert.ok(savedDraft.media.some(m=>m.unit_key==='s1'&&m.purpose==='reference_image'&&m.media_id==='m-role'));
  assert.ok(savedDraft.dependencies.some(d=>d.unit_key==='s1'&&d.source_unit_key==='b1'));
 }finally{panel.suspend();}
});
