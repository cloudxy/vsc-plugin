import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;for(const fn of this.listeners.get('close')||[])fn();};
const doc=new Document('');doc.documentElement=doc.createElement('html');
doc.addEventListener=()=>{};doc.removeEventListener=()=>{};
globalThis.document=doc;
const ai=await import('../../../src/vsc/interfaces/web/static/character-studio-ai.js');
const wf=await import('../../../src/vsc/interfaces/web/static/character-studio-workflows.js');
const store=await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createCharacterStudio}=await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const flush=()=>new Promise(resolve=>setTimeout(resolve,10));
const texts=(root,tag)=>root.querySelectorAll(tag).map(n=>n.textContent);

test('ComfyUI presets parse, auto-map and keep a stable identity',()=>{
 assert.deepEqual(Object.keys(wf.COMFYUI_WORKFLOW_TEMPLATES),['qwen2509_3img','qwen2509_2img','qwen21_3img','qwen21_2img']);
 const json=JSON.stringify(wf.COMFYUI_WORKFLOW_TEMPLATES.qwen2509_3img.workflow);
 const parsed=wf.parseComfyWorkflowNodes(json);
 assert.equal(parsed.valid,true);
 assert.deepEqual(wf.autoDetectComfyMappings(json),{promptNodeId:'12',portraitNodeId:'1',costumeNodeId:'2',poseNodeId:'3',stitchedNodeId:'none'});
 assert.equal(wf.workflowIdentity(json),wf.workflowIdentity(JSON.stringify(JSON.parse(json),null,2)));
 assert.equal(wf.parseComfyWorkflowNodes(JSON.stringify({nodes:[],links:[]})).isUiFormat,true);
 const two=wf.COMFYUI_WORKFLOW_TEMPLATES.qwen2509_2img.workflow;assert.equal(two['2'],undefined);assert.deepEqual(two['12'].inputs.image2,['3',0]);
 const schemas={LoadImage:{input:{required:{image:[['a.png'],{image_upload:true}]}},output:['IMAGE']},KSampler:{input:{required:{steps:['INT',{min:1,max:100}],seed:['INT',{min:0}]}}}};
 const tiny=JSON.stringify({'1':{class_type:'KSampler',inputs:{steps:20,seed:1}},'2':{class_type:'LoadImage',inputs:{image:'a.png'}}});
 const controls=wf.getWorkflowControls(tiny,schemas);
 assert.deepEqual(controls.map(c=>c.key).sort(),['1.seed','1.steps']);
 const applied=JSON.parse(wf.applyWorkflowOverrides(tiny,{workflowId:wf.workflowIdentity(tiny),values:{'1':{steps:30,seed:-5}}},schemas));
 assert.equal(applied['1'].inputs.steps,30);assert.equal(applied['1'].inputs.seed,1,'invalid override ignored');
 assert.deepEqual(wf.getWorkflowImages(tiny,[],schemas).map(i=>i.nodeId),['2']);
});

test('prompt builder numbers references and media paths resolve locally',()=>{
 const recipe={portrait:{id:'p',分区:'正脸参考',发长:'短发',发型名称:'波浪',标题:'短发・波浪',缩略图:'thumbs/portrait/p.webp',原图:'img/portrait/p.webp'},
  costume:{id:'c',分类:'春季穿搭',服装名称:'象牙白针织衫',缩略图:'thumbs/costume/c.webp',预览图:'img/costume/c.webp',原图:'img/costume/c.webp'},
  pose:{id:'x',体系:'全身单人・标准系',姿势名称:'自然站立',角度:'正面',缩略图:'thumbs/x.jpg',原图:'img/x.png',useDepth:true},extraImages:[{id:'e',name:'耳环',url:'data:image/png;base64,AA=='}]};
 const prompt=ai.buildRecipePrompt(recipe,'realistic');
 assert.match(prompt,/提供的 4 张参考图/);assert.match(prompt,/图1中的人物.*短发・波浪/);assert.match(prompt,/图2.*象牙白针织衫/);
 assert.match(prompt,/图3中人体模型.*自然站立，正面/);assert.match(prompt,/图4（耳环）/);assert.match(prompt,/没有任何文字/);
 assert.equal(ai.buildRecipePrompt({portrait:null,costume:null,pose:null}),'请先选择人像/服装/姿势或上传附加参考图。');
 assert.equal(ai.referenceImageUrl('thumbs/costume/c.webp'),'/api/v1/asset-center/pose-gallery/media/thumbs/costume/c.webp');
 assert.equal(ai.referenceImageUrl('https://charadb-2fi.pages.dev/thumb/O001.webp'),'https://charadb-2fi.pages.dev/thumb/O001.webp');
 assert.equal(ai.referenceImageUrl('data:image/png;base64,AA=='),'data:image/png;base64,AA==');
 assert.equal(ai.poseThumbPath(recipe.pose),'thumbs/depth/x.webp');
 assert.equal(ai.poseImagePath(recipe.pose),'img/depth/x.webp');
 assert.equal(ai.poseThumbPath({...recipe.pose,缩略图:'/api/v1/asset-center/pose-gallery/media/thumbs/x.jpg'}),'thumbs/depth/x.webp');
 assert.equal(ai.poseThumbPath({...recipe.pose,useDepth:false}),'thumbs/x.jpg');
 assert.equal(ai.toPublicHttpsUrl('img/costume/c.webp'),'https://ai-costume-gallery.pages.dev/img/costume/c.webp');
 const view=ai.selectCostumeView({id:'s',views:[{id:'front',缩略图:'a',预览图:'a',原图:'a'},{id:'side',缩略图:'b',预览图:'b',原图:'b'}]},'side');
 assert.equal(view.原图,'b');assert.equal(view.selectedView,'side');
});

test('stored configuration migrates and keeps keys browser-local',()=>{
 const cfg=store.mergeStoredConfig({activeProvider:'qwen',providers:{qwen:{apiKey:'sk-1'}},comfyuiParams:{workflowPreset:'qwen21_3img',configVersion:1}});
 assert.equal(cfg.providers.qwen.apiKey,'sk-1');assert.equal(cfg.useProxy,true);
 assert.equal(cfg.comfyuiParams.workflowPreset,'qwen2509_3img');assert.equal(cfg.providers.comfyui.baseUrl,'/comfy');
 assert.deepEqual(ai.PROVIDER_ORDER,['gemini','gpt','qwen','doubao','comfyui']);
 assert.equal(Object.keys(ai.STYLE_PRESETS).length,12);
});

test('studio and API settings views render the migrated sections',async()=>{
 const root=doc.createElement('section');doc.body.append(root);const navigations=[],notices=[];
 const studio=createCharacterStudio(root,{api:async()=>({}),notice:m=>notices.push(m),session:()=>({actor:'a',csrf:'c'}),navigate:(page,options)=>navigations.push([page,options])});
 await studio.load({mode:'studio'});await flush();
 const headings=texts(root,'h2');
 for(const title of ['1. 参考图组合','2. 生图引擎与参数','3. 提示词 (Prompt)','生成结果','生成记录 (0)'])assert.ok(headings.includes(title),title);
 assert.equal(root.querySelectorAll('.cs-slot').length,3);
 assert.ok(root.querySelector('.cs-dropzone'));
 const provider=root.querySelectorAll('select').find(s=>s.options.some(o=>o.value==='comfyui'));
 assert.deepEqual(provider.options.map(o=>o.value),['gemini','gpt','qwen','doubao','comfyui']);
 const pick=root.querySelectorAll('button').find(b=>b.textContent==='去图库挑选');
 await pick.onclick();assert.deepEqual(navigations.at(-1),['asset-center',{tab:'official',kind:'portrait'}]);
 store.setSlot('costume',{id:'c',分类:'春季穿搭',服装名称:'象牙白针织衫',缩略图:'thumbs/costume/c.webp',预览图:'img/costume/c.webp',原图:'img/costume/c.webp'});await flush();
 assert.match(root.querySelector('.cs-prompt').value,/象牙白针织衫/);
 assert.equal(root.querySelector('.cs-slot').parentElement.querySelectorAll('.cs-slot').filter(n=>n.classList.contains('is-filled')).length,1);
 provider.value='comfyui';await provider.onchange();await flush();
 assert.ok(root.querySelector('.cs-comfy'));assert.ok(root.querySelector('.cs-conn'));
 const preset=root.querySelectorAll('select').find(s=>s.options.some(o=>o.value==='qwen2509_2img'));assert.ok(preset);
 await studio.load({mode:'settings'});await flush();
 assert.ok(texts(root,'h1').includes('API 接口配置'));
 assert.equal(root.querySelectorAll('.cs-provider-tab').length,5);
 const key=root.querySelectorAll('input').find(i=>i.type==='password');assert.ok(key);
 const back=root.querySelectorAll('button').find(b=>b.textContent==='返回 AI 角色合成台');await back.onclick();assert.equal(navigations.at(-1)[0],'character-studio');
 store.updateApiConfig({activeProvider:'gemini'});store.setSlot('costume',null);
 studio.suspend();
});

test('sidebar places the studio under 资产库 and the settings icon right after 帮助',()=>{
 const html=readFileSync(new URL('../../../src/vsc/interfaces/web/templates/index.html',import.meta.url),'utf8');
 assert.match(html,/id="nav-asset-center"[^]*?<\/a><a id="nav-character-studio" href="\?page=character-studio">/);
 assert.match(html,/<\/details><button type="button" id="api-settings-open" class="sidebar-settings-open" aria-label="API 接口配置"/);
 assert.match(html,/id="api-settings-open"[^>]*><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"/);
 assert.match(html,/<section id="character-studio-view"/);
 assert.match(html,/character-studio\.css/);
 assert.doesNotMatch(html,/style="/);
});
