import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;for(const fn of this.listeners.get('close')||[])fn();};
const doc=new Document('');doc.documentElement=doc.createElement('html');
doc.addEventListener=()=>{};doc.removeEventListener=()=>{};
globalThis.document=doc;
const ai=await import('../../../src/vsc/interfaces/web/static/character-studio-ai.js');
const store=await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createCharacterStudio}=await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const flush=()=>new Promise(resolve=>setTimeout(resolve,15));
const texts=(root,tag)=>root.querySelectorAll(tag).map(n=>n.textContent);

test('ComfyUI is completely removed and AGY/Grok auth + Grok/Gemini API providers are registered',()=>{
 assert.equal(existsSync(new URL('../../../src/vsc/interfaces/web/static/character-studio-workflows.js',import.meta.url)),false);
 assert.deepEqual(ai.PROVIDER_ORDER,['agy_auth','grok_auth','gemini','grok','gpt','qwen','doubao']);
 assert.equal(ai.PROVIDER_META.comfyui,undefined);
 assert.deepEqual(ai.SETTINGS_GROUPS.map(g=>g.id),['google','xai','gpt','qwen','doubao']);
 assert.deepEqual(ai.SETTINGS_GROUPS[0].modes,['agy_auth','gemini']);
 assert.deepEqual(ai.SETTINGS_GROUPS[1].modes,['grok_auth','grok']);
 assert.equal(ai.isAuthProvider('agy_auth'),true);
 assert.equal(ai.isAuthProvider('grok_auth'),true);
 assert.equal(ai.isAuthProvider('grok'),false);
 assert.equal(ai.isAuthProvider('gemini'),false);
});

test('Grok and Gemini API request builders follow official endpoint schemas',()=>{
 const single=ai.buildGrokApiRequest({
  baseUrl:'https://api.x.ai/v1',apiKey:'xai-key-1',model:'grok-imagine-image-2.0',
  prompt:'生成角色图',refs:['data:image/png;base64,AA=='],
  grokParams:{endpointMode:'auto',aspectRatio:'3:4',resolution:'2k',responseFormat:'auto'},
 });
 assert.equal(single.url,'https://api.x.ai/v1/images/edits');
 assert.equal(single.headers.Authorization,'Bearer xai-key-1');
 const singleBody=JSON.parse(single.body);
 assert.equal(singleBody.image.url,'data:image/png;base64,AA==');
 assert.equal(singleBody.images,undefined);
 assert.equal(singleBody.aspect_ratio,'3:4');
 assert.equal(singleBody.resolution,'2k');

 const multi=ai.buildGrokApiRequest({
  baseUrl:'https://api.x.ai',apiKey:'xai-key-1',model:'grok-imagine-image-2.0',
  prompt:'多图合成',refs:['data:image/png;base64,AA==','data:image/png;base64,BB=='],
  grokParams:{endpointMode:'auto',aspectRatio:'9:16',resolution:'1.5k',responseFormat:'b64_json'},
 });
 assert.equal(multi.url,'https://api.x.ai/v1/images/edits');
 const multiBody=JSON.parse(multi.body);
 assert.equal(multiBody.images.length,2);
 assert.equal(multiBody.response_format,'b64_json');

 assert.throws(()=>ai.buildGrokApiRequest({
  baseUrl:'https://api.x.ai/v1',apiKey:'xai-key-1',model:'grok-imagine-image-2.0',
  prompt:'超限',refs:['1','2','3','4','5','6'],grokParams:{endpointMode:'auto'},
 }),/最多支持 5 张/);

 const genOnly=ai.buildGrokApiRequest({
  baseUrl:'https://api.x.ai/v1',apiKey:'xai-key-1',model:'grok-2-image-1212',
  prompt:'文生图',refs:['data:image/png;base64,AA=='],grokParams:{endpointMode:'auto',responseFormat:'b64_json'},
 });
 assert.equal(genOnly.url,'https://api.x.ai/v1/images/generations');

 const geminiNative=ai.buildGeminiApiRequest({
  baseUrl:'https://generativelanguage.googleapis.com',apiKey:'AIza-test',
  model:'gemini-3.1-flash-image-preview',prompt:'生成角色',refs:['data:image/png;base64,QUJD'],
  geminiParams:{endpointMode:'native',aspectRatio:'3:4',imageSize:'2K'},
 });
 assert.equal(geminiNative.url,'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent');
 assert.equal(geminiNative.headers['x-goog-api-key'],'AIza-test');
 const gmBody=JSON.parse(geminiNative.body);
 assert.equal(gmBody.contents[0].parts[0].inlineData.data,'QUJD');
 assert.deepEqual(gmBody.generationConfig.imageConfig,{aspectRatio:'3:4',imageSize:'2K'});
});

test('prompt builder numbers references and stored config migrates legacy comfyui cleanly',()=>{
 const recipe={portrait:{id:'p',分区:'正脸参考',发长:'短发',发型名称:'波浪',标题:'短发・波浪',缩略图:'thumbs/portrait/p.webp',原图:'img/portrait/p.webp'},
  costume:{id:'c',分类:'春季穿搭',服装名称:'象牙白针织衫',缩略图:'thumbs/costume/c.webp',预览图:'img/costume/c.webp',原图:'img/costume/c.webp'},
  pose:{id:'x',体系:'全身单人・标准系',姿势名称:'自然站立',角度:'正面',缩略图:'thumbs/x.jpg',原图:'img/x.png',useDepth:true},extraImages:[{id:'e',name:'耳环',url:'data:image/png;base64,AA=='}]};
 const prompt=ai.buildRecipePrompt(recipe,'realistic');
 assert.match(prompt,/提供的 4 张参考图/);assert.match(prompt,/图1中的人物.*短发・波浪/);assert.match(prompt,/图2.*象牙白针织衫/);
 assert.match(prompt,/图3中人体模型.*自然站立，正面/);assert.match(prompt,/图4（耳环）/);assert.match(prompt,/没有任何文字/);

 const migrated=store.mergeStoredConfig({activeProvider:'comfyui',providers:{comfyui:{baseUrl:'/comfy'},grok:{apiKey:'xai-local'}}});
 assert.equal(migrated.activeProvider,'agy_auth');
 assert.equal(migrated.providers.comfyui,undefined);
 assert.equal(migrated.comfyuiParams,undefined);
 assert.equal(migrated.providers.grok.apiKey,'xai-local');

 const grokCfg=store.mergeStoredConfig({activeProvider:'grok',providers:{grok:{apiKey:'xai-local'}}});
 assert.equal(grokCfg.useProxy,true);
 assert.equal(Object.keys(ai.STYLE_PRESETS).length,12);
});

test('studio and API settings views render AGY/Grok OAuth login and Grok/Gemini API modes without ComfyUI',async()=>{
 const root=doc.createElement('section');doc.body.append(root);const navigations=[],notices=[],apiCalls=[];
 const mockApi=async(path,opts)=>{
  apiCalls.push([path,opts?.method||'GET']);
  if(path==='/api/v1/character-studio/auth/status'){
   return {
    grok:{provider:'grok_auth',cli_installed:true,ready:true,status:'authorized',account:'xu***@x.ai',message:'Grok 订阅登录已就绪',login_command:'grok login --oauth'},
    agy:{provider:'agy_auth',cli_installed:true,ready:true,status:'authorized',account:null,message:'本机 AGY 授权已就绪',login_command:'agy'},
   };
  }
  if(path==='/api/v1/character-studio/auth/login')return {started:true,command:'grok login --oauth',message:'已调起授权登录'};
  if(path==='/api/v1/character-studio/auth/verify')return {provider:'agy_auth',ready:true,verified:true,status:'authorized',model_count:6,message:'AGY 在线验证通过'};
  return {};
 };
 const studio=createCharacterStudio(root,{api:mockApi,notice:m=>notices.push(m),session:()=>({actor:'a',csrf:'c'}),navigate:(page,options)=>navigations.push([page,options])});
 await studio.load({mode:'studio'});await flush();
 const headings=texts(root,'h2');
 for(const title of ['1. 参考图组合','2. 生图引擎与参数','3. 提示词 (Prompt)','生成结果','生成记录 (0)'])assert.ok(headings.includes(title),title);
 const providerSelect=root.querySelectorAll('select').find(s=>s.options.some(o=>o.value==='agy_auth'));
 assert.deepEqual(providerSelect.options.map(o=>o.value),['agy_auth','grok_auth','gemini','grok','gpt','qwen','doubao']);
 assert.equal(providerSelect.options.some(o=>/comfy/i.test(o.value+o.textContent)),false);
 assert.ok(root.querySelector('.cs-conn'));

 // Switch to Grok API in studio -> shows missing API key hint
 providerSelect.value='grok';await providerSelect.onchange();await flush();
 assert.match(root.querySelector('.cs-warn').textContent,/xAI Grok \(API 接口\)/);

 // Switch to settings view -> 5 vendor tabs, no ComfyUI
 await studio.load({mode:'settings'});await flush();
 assert.ok(texts(root,'h1').includes('API 接口配置'));
 const tabs=root.querySelectorAll('.cs-provider-tab');
 assert.equal(tabs.length,5);
 assert.equal(tabs.some(t=>/ComfyUI/i.test(t.textContent)),false);

 // Currently on xAI · Grok group (`grok` API mode) -> switch to `grok_auth` OAuth login mode
 const modeBtns=root.querySelectorAll('.cs-mode-btn');
 assert.equal(modeBtns.length,2);
 const grokAuthBtn=modeBtns.find(b=>b.dataset.modeId==='grok_auth');
 await grokAuthBtn.onclick();await flush();
 assert.ok(root.querySelector('.cs-auth-card'));
 assert.match(root.querySelector('.cs-cmd-box').textContent,/grok login --oauth/);

 // Switch to Google · AGY / Gemini tab -> verify AGY auth mode & Gemini API mode switch
 const googleTab=root.querySelectorAll('.cs-provider-tab').find(b=>b.dataset.groupId==='google');
 await googleTab.onclick();await flush();
 assert.match(root.querySelector('.cs-cmd-box').textContent,/\$ agy/);
 const verifyBtn=root.querySelectorAll('button').find(b=>b.textContent.includes('在线验证授权'));
 await verifyBtn.onclick();await flush();
 assert.ok(notices.some(m=>m.includes('AGY 在线验证通过')));

 const geminiApiBtn=root.querySelectorAll('.cs-mode-btn').find(b=>b.dataset.modeId==='gemini');
 await geminiApiBtn.onclick();await flush();
 const keyInput=root.querySelectorAll('input').find(i=>i.type==='password');
 assert.ok(keyInput);

 const back=root.querySelectorAll('button').find(b=>b.textContent==='返回 AI 角色合成台');
 await back.onclick();assert.equal(navigations.at(-1)[0],'character-studio');
 store.updateApiConfig({activeProvider:'agy_auth'});
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
