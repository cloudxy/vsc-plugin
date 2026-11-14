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
globalThis.CSS={escape:value=>String(value)};
const matches=Element.prototype.matches;
Element.prototype.matches=function(selector){
 const focusSelector=selector.match(/^\[data-focus-key="([^"]+)"\]$/);
 return focusSelector?this.dataset.focusKey===focusSelector[1]:matches.call(this,selector);
};
const ai=await import('../../../src/vsc/interfaces/web/static/character-studio-ai.js');
const store=await import('../../../src/vsc/interfaces/web/static/character-studio-store.js');
const {createCharacterStudio}=await import('../../../src/vsc/interfaces/web/static/character-studio.js');
const flush=()=>new Promise(resolve=>setTimeout(resolve,15));
const texts=(root,tag)=>root.querySelectorAll(tag).map(n=>n.textContent);

test('ComfyUI is completely removed and AGY/Grok auth + Grok/Gemini API + Video modality providers are registered',()=>{
 assert.equal(existsSync(new URL('../../../src/vsc/interfaces/web/static/character-studio-workflows.js',import.meta.url)),false);
 assert.deepEqual(ai.PROVIDER_ORDER,['agy_auth','grok_auth','codex_auth','gemini','grok','gpt','qwen','doubao']);
 assert.equal(ai.PROVIDER_META.comfyui,undefined);
 assert.deepEqual(ai.SETTINGS_GROUPS.map(g=>g.id),['google','xai','gpt','qwen','doubao']);
 assert.deepEqual(ai.SETTINGS_GROUPS[0].modes,['agy_auth','gemini']);
 assert.deepEqual(ai.SETTINGS_GROUPS[1].modes,['grok_auth','grok']);
 assert.equal(ai.isAuthProvider('agy_auth'),true);
 assert.equal(ai.isAuthProvider('grok_auth'),true);
 assert.equal(ai.isAuthProvider('grok'),false);
 assert.equal(ai.isAuthProvider('gemini'),false);

 assert.deepEqual(ai.SETTINGS_MODALITIES.map(m=>[m.id,m.label]),[['image','图'],['video','视频']]);
 assert.deepEqual(ai.VIDEO_PROVIDER_ORDER,['grok_video_auth','grok_video','doubao_video','gemini_video','qwen_video','openai_video']);
 assert.deepEqual(ai.VIDEO_SETTINGS_GROUPS.map(g=>g.id),['xai_video','doubao_video','google_video','qwen_video','openai_video']);
 assert.deepEqual(ai.VIDEO_SETTINGS_GROUPS[0].modes,['grok_video_auth','grok_video']);
 assert.equal(ai.isVideoAuthProvider('grok_video_auth'),true);
 assert.equal(ai.isVideoAuthProvider('grok_video'),false);
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

 const grokVid=ai.buildGrokVideoApiRequest({
  baseUrl:'https://api.x.ai/v1',apiKey:'xai-vid-1',model:'grok-imagine-video-1.5',
  prompt:'雨夜转身回眸',firstFrame:'https://example.com/f1.png',lastFrame:'https://example.com/f2.png',
  videoDefaults:{aspectRatio:'9:16',resolution:'1080p',durationSec:'15',generateAudio:false},
 });
 assert.equal(grokVid.url,'https://api.x.ai/v1/videos/generations');
 assert.equal(grokVid.headers.Authorization,'Bearer xai-vid-1');
 const vidBody=JSON.parse(grokVid.body);
 assert.equal(vidBody.duration,15);
 assert.equal(vidBody.aspect_ratio,'9:16');
 assert.equal(vidBody.resolution,'1080p');
 assert.equal(vidBody.image.url,'https://example.com/f1.png');
 assert.equal(vidBody.last_frame.url,'https://example.com/f2.png');
 assert.equal(vidBody.generate_audio,false);

 assert.throws(()=>ai.buildGrokVideoApiRequest({
  baseUrl:'https://api.x.ai/v1',apiKey:'xai-vid-1',model:'grok-imagine-video',
  prompt:'经典模型尾帧校验',lastFrame:'https://example.com/f2.png',
  videoDefaults:{aspectRatio:'16:9',resolution:'720p',durationSec:'5'},
 }),/grok-imagine-video-1\.5/);
});

test('prompt builder numbers references and stored config migrates legacy comfyui and isolates video config',async()=>{
 const recipe={portrait:{id:'p',分区:'正脸参考',发长:'短发',发型名称:'波浪',标题:'短发・波浪',缩略图:'thumbs/portrait/p.webp',原图:'img/portrait/p.webp'},
  costume:{id:'c',分类:'春季穿搭',服装名称:'象牙白针织衫',缩略图:'thumbs/costume/c.webp',预览图:'img/costume/c.webp',原图:'img/costume/c.webp'},
  pose:{id:'x',体系:'全身单人・标准系',姿势名称:'自然站立',角度:'正面',缩略图:'thumbs/x.jpg',原图:'img/x.png',useDepth:true},extraImages:[{id:'e',name:'耳环',url:'data:image/png;base64,AA=='}]};
 const prompt=ai.buildRecipePrompt(recipe,'realistic');
 assert.match(prompt,/提供的 4 张参考图/);assert.match(prompt,/图1中的人物.*短发・波浪/);assert.match(prompt,/图2.*象牙白针织衫/);
 assert.match(prompt,/图3中人体模型.*自然站立，正面/);assert.match(prompt,/图4（耳环）/);assert.match(prompt,/没有任何文字/);

 const migrated=store.mergeStoredConfig({activeProvider:'comfyui',providers:{comfyui:{baseUrl:'/comfy'},grok:{apiKey:'xai-local'}},videoProviders:{grok_video:{apiKey:'xai-vid-secret'}}});
 assert.equal(migrated.activeProvider,'agy_auth');
 assert.equal(migrated.activeVideoProvider,'grok_video_auth');
 assert.equal(migrated.providers.comfyui,undefined);
 assert.equal(migrated.comfyuiParams,undefined);
 assert.equal(migrated.providers.grok.apiKey,'xai-local');
 assert.equal(migrated.videoProviders.grok_video.apiKey,'xai-vid-secret');

 const snap=await store.snapshotGeneration({portrait:null,costume:null,pose:null,extraImages:[]},migrated,'测试快照');
 assert.equal(snap.settings.providers,undefined);
 assert.equal(snap.settings.videoProviders,undefined);
 assert.equal(JSON.stringify(snap).includes('xai-local'),false);
 assert.equal(JSON.stringify(snap).includes('xai-vid-secret'),false);

 const grokCfg=store.mergeStoredConfig({activeProvider:'grok',activeVideoProvider:'doubao_video',providers:{grok:{apiKey:'xai-local'}}});
 assert.equal(grokCfg.useProxy,true);
 assert.equal(grokCfg.videoUseProxy,true);
 assert.equal(Object.keys(ai.STYLE_PRESETS).length,12);
});

test('studio and API settings views split into 图 and 视频 tabs with independent state and key reuse',async()=>{
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
  if(path==='/api/v1/character-studio/auth/verify'){
   const reqBody=opts?.body?JSON.parse(opts.body):{};
   if(reqBody.provider==='grok')return {provider:'grok_auth',ready:true,verified:true,status:'authorized',model_count:4,message:'Grok CLI 在线验证通过'};
   return {provider:'agy_auth',ready:true,verified:true,status:'authorized',model_count:6,message:'AGY 在线验证通过'};
  }
  return {};
 };
 const studio=createCharacterStudio(root,{api:mockApi,notice:m=>notices.push(m),session:()=>({actor:'a',csrf:'c'}),navigate:(page,options)=>navigations.push([page,options])});
 await studio.load({mode:'studio'});await flush();
 const headings=texts(root,'h2');
 for(const title of ['1. 参考图组合','2. 生图引擎与参数','3. 提示词 (Prompt)','本次生成结果'])assert.ok(headings.includes(title),title);
 assert.ok(texts(root,'button').includes('AI角色合成库 (0)'));
 const providerSelect=root.querySelectorAll('select').find(s=>s.options.some(o=>o.value==='agy_auth'));
 assert.deepEqual(providerSelect.options.map(o=>o.value),['agy_auth','grok_auth','codex_auth','gemini','grok','gpt','qwen','doubao']);
 assert.equal(providerSelect.options.some(o=>/comfy/i.test(o.value+o.textContent)),false);
 assert.ok(root.querySelector('.cs-conn'));

 // Switch to Grok API in studio -> shows missing API key hint
 providerSelect.value='grok';await providerSelect.onchange();await flush();
 assert.match(root.querySelector('.cs-warn').textContent,/xAI Grok \(API 接口\)/);

 // Switch to settings view -> renders two top-level modality tabs: 图 (selected) and 视频
 await studio.load({mode:'settings'});await flush();
 assert.ok(texts(root,'h1').includes('API 接口配置'));
 const modTabs=root.querySelectorAll('.cs-modality-tab');
 assert.equal(modTabs.length,2);
 const imgModTab=root.querySelector('#cs-modality-tab-image');
 const vidModTab=root.querySelector('#cs-modality-tab-video');
 assert.match(imgModTab.textContent,/图/);
 assert.match(vidModTab.textContent,/视频/);
 assert.equal(imgModTab.getAttribute('aria-selected'),'true');
 assert.equal(vidModTab.getAttribute('aria-selected'),'false');

 const tabs=root.querySelectorAll('.cs-provider-tab');
 assert.equal(tabs.length,5);
 assert.equal(tabs.some(t=>/ComfyUI/i.test(t.textContent)),false);

 // Currently on xAI · Grok group (`grok` API mode) -> save a Grok image key, then switch to `grok_auth` OAuth login mode
 store.updateProviderConfig('grok',{apiKey:'xai-img-123'});await flush();
 const modeBtns=root.querySelectorAll('.cs-mode-btn');
 assert.equal(modeBtns.length,2);
 const grokAuthBtn=modeBtns.find(b=>b.dataset.modeId==='grok_auth');
 await grokAuthBtn.onclick();await flush();
 assert.ok(root.querySelector('.cs-auth-card'));
 assert.match(root.querySelector('.cs-cmd-box').textContent,/grok login --oauth/);
 assert.deepEqual(ai.PROVIDER_META.grok_auth.models.map(m=>m.value),['image_edit','grok-imagine-image-2.0','grok-imagine-image','custom']);
 const grokVerifyBtn=root.querySelectorAll('button').find(b=>b.textContent.includes('在线验证授权 (grok models)'));
 assert.ok(grokVerifyBtn);
 await grokVerifyBtn.onclick();await flush();
 assert.ok(notices.some(m=>m.includes('Grok CLI 在线验证通过')));

 // Switch to Google · AGY / Gemini tab -> verify AGY auth mode & Gemini API mode switch
 const googleTab=root.querySelectorAll('.cs-provider-tab').find(b=>b.dataset.groupId==='google');
 await googleTab.onclick();await flush();
 assert.match(root.querySelector('.cs-cmd-box').textContent,/\$ agy/);
 const verifyBtn=root.querySelectorAll('button').find(b=>b.textContent.includes('在线验证授权'));
 await verifyBtn.onclick();await flush();
 assert.ok(notices.some(m=>m.includes('AGY 在线验证通过')));

 const geminiApiBtn=root.querySelectorAll('.cs-mode-btn').find(b=>b.dataset.modeId==='gemini');
 await geminiApiBtn.onclick();await flush();
 assert.ok(root.querySelectorAll('input').find(i=>i.type==='password'));

 // Click 视频 tab -> shows Video configuration without disturbing 图 tab state
 await vidModTab.onclick();await flush();
 assert.equal(root.querySelector('#cs-modality-tab-video').getAttribute('aria-selected'),'true');
 assert.equal(root.querySelector('#cs-modality-tab-image').getAttribute('aria-selected'),'false');
 const videoTabs=root.querySelectorAll('.cs-provider-tab');
 assert.deepEqual(videoTabs.map(t=>t.dataset.groupId),['xai_video','doubao_video','google_video','qwen_video','openai_video']);
 assert.ok(texts(root,'h2').some(t=>t.includes('xAI · Grok Video · 视频接入配置')));
 assert.ok(texts(root,'h2').includes('视频默认参数与请求选项'));
 assert.ok(root.querySelector('.cs-auth-card'));
 assert.ok(root.querySelectorAll('select').some(s=>s.options.some(o=>o.value==='grok-imagine-video-1.5')));

 // Switch Grok Video to API mode -> auto-enables videoUseProxy & offers 1-click key reuse from 图 tab
 const grokVidApiBtn=root.querySelectorAll('.cs-mode-btn').find(b=>b.dataset.modeId==='grok_video');
 await grokVidApiBtn.onclick();await flush();
 assert.equal(store.getState().apiConfig.videoUseProxy,true);
 const reuseBtn=root.querySelectorAll('button').find(b=>b.textContent.includes('复用「图」同厂商 Key'));
 assert.ok(reuseBtn);
 await reuseBtn.onclick();await flush();
 assert.equal(store.getState().apiConfig.videoProviders.grok_video.apiKey,'xai-img-123');

 // Switch to 字节火山方舟 Seedance tab & update default video aspect ratio to 9:16
 const seedanceTab=root.querySelectorAll('.cs-provider-tab').find(b=>b.dataset.groupId==='doubao_video');
 await seedanceTab.onclick();await flush();
 assert.ok(root.querySelectorAll('select').some(s=>s.options.some(o=>o.value==='doubao-seedance-2-5-260628')));
 const aspectSelect=root.querySelectorAll('select').find(s=>s.getAttribute('aria-label')==='默认视频画幅');
 assert.ok(aspectSelect);
 aspectSelect.value='9:16';await aspectSelect.onchange();await flush();
 assert.equal(store.getState().apiConfig.videoDefaults.aspectRatio,'9:16');

 // Switch back to 图 tab -> still on Google · AGY / Gemini (`gemini`)
 await root.querySelector('#cs-modality-tab-image').onclick();await flush();
 assert.equal(root.querySelector('#cs-modality-tab-image').getAttribute('aria-selected'),'true');
 assert.equal(store.getState().apiConfig.activeProvider,'gemini');
 assert.ok(texts(root,'h2').some(t=>t.includes('Google · AGY / Gemini · 生图接入配置')));

 // Direct load with `{mode:'settings', tab:'video'}` opens directly on 视频 tab
 await studio.load({mode:'settings',tab:'video'});await flush();
 assert.equal(root.querySelector('#cs-modality-tab-video').getAttribute('aria-selected'),'true');

 const back=root.querySelectorAll('button').find(b=>b.textContent==='返回 AI 角色合成台');
 await back.onclick();assert.equal(navigations.at(-1)[0],'character-studio');
 store.updateProviderConfig('grok',{apiKey:''});
 store.updateVideoProviderConfig('grok_video',{apiKey:''});
 store.updateApiConfig({activeProvider:'agy_auth',activeVideoProvider:'grok_video_auth'});
 studio.suspend();
});

test('costume image helpers enforce local-only media paths and block external URLs',()=>{
 assert.equal(ai.localizeCostumePath('thumbs/costume/SPR-0001.webp'),'thumbs/costume/SPR-0001.webp');
 assert.equal(ai.localizeCostumePath('https://ai-costume-anime-gallery.pages.dev/thumbs/SPR-0001.webp'),'thumbs/costumes/gia-anime/SPR-0001.webp');
 assert.equal(ai.localizeCostumePath('https://ai-costume-anime-gallery.pages.dev/png/SPR-0001.png'),'img/costumes/gia-anime/SPR-0001.webp');
 assert.equal(ai.localizeCostumePath('https://charadb-2fi.pages.dev/thumb/O001.webp'),'thumbs/costumes/charadb/O001.webp');
 assert.equal(ai.localizeCostumePath('https://charadb-2fi.pages.dev/img/O001.jpg'),'img/costumes/charadb/O001.jpg');
 assert.equal(ai.localizeCostumePath('https://evil.example.com/costume.webp'),'');
 assert.equal(ai.localCostumeImageUrl('https://charadb-2fi.pages.dev/thumb/O001.webp'),'/api/v1/asset-center/pose-gallery/media/thumbs/costumes/charadb/O001.webp');
 assert.equal(ai.localCostumeImageUrl('https://evil.example.com/costume.webp'),'');
 assert.equal(ai.referenceImageUrl('https://ai-costume-anime-gallery.pages.dev/img/SPR-0002.webp'),'/api/v1/asset-center/pose-gallery/media/img/costumes/gia-anime/SPR-0002.webp');
 assert.equal(ai.sanitizeCostumeItem({id:'bad',缩略图:'https://evil.example.com/a.webp',原图:'https://evil.example.com/b.webp'}),null);
 store.setSlot('costume',{id:'gia-anime-SPR-0001',source:'gia-anime',服装名称:'动漫春装',
  缩略图:'https://ai-costume-anime-gallery.pages.dev/thumbs/SPR-0001.webp',
  预览图:'https://ai-costume-anime-gallery.pages.dev/img/SPR-0001.webp',
  原图:'https://ai-costume-anime-gallery.pages.dev/png/SPR-0001.png'});
 assert.equal(store.getState().recipe.costume.缩略图,'thumbs/costumes/gia-anime/SPR-0001.webp');
 assert.equal(store.getState().recipe.costume.原图,'img/costumes/gia-anime/SPR-0001.webp');
 store.setSlot('costume',null);
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

test('OpenAI subscription mode activates Codex while keeping API configuration independent',async()=>{
 const root=doc.createElement('section');doc.body.append(root);
 const notices=[],copied=[],calls=[];let authorized=true;
 const originalNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator');
 Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>copied.push(text)}}});
 const api=async(path,options={})=>{
  const body=options.body?JSON.parse(options.body):null;calls.push({path,body});
  if(path.endsWith('/auth/status'))return {codex:{ready:authorized,status:authorized?'authorized':'unauthorized',login_command:'codex login'}};
  assert.equal(body.provider,'codex');
  if(path.endsWith('/auth/verify'))return {ready:true,status:'authorized',message:'Codex checked'};
  return {started:false,command:'codex login'};
 };
 const previous=structuredClone(store.getState().apiConfig);
 const saved={apiKey:'existing-openai-key',baseUrl:'https://api.openai.com/v1',model:'custom',customModel:'retained-image-model'};
 store.updateApiConfig({activeProvider:'gpt'});store.updateProviderConfig('gpt',saved);
 const studio=createCharacterStudio(root,{api,notice:m=>notices.push(m),session:()=>({csrf:'csrf'}),navigate(){}});
 const mode=id=>root.querySelectorAll('.cs-mode-btn').find(node=>node.dataset.modeId===id);
 const control=key=>root.querySelectorAll('button').find(node=>node.dataset.busyKey===key);
 try{
  await studio.load({mode:'settings',tab:'image'});await flush();
  assert.deepEqual(root.querySelectorAll('.cs-mode-btn').map(node=>node.dataset.modeId),['codex_auth','gpt']);
  mode('codex_auth').focus();await mode('codex_auth').onclick();await flush();
  assert.ok(doc.activeElement===mode('codex_auth'));
  assert.equal(store.getState().apiConfig.activeProvider,'codex_auth');
  assert.ok(root.querySelector('.cs-auth-panel'));
  assert.equal(root.querySelector('.cs-apikey-panel'),null);
  assert.match(root.querySelector('.cs-auth-panel').textContent,/无需 API Key/);
  assert.match(root.querySelector('.cs-cmd-box').textContent,/codex login/);
  const tab=root.querySelectorAll('.cs-provider-tab').find(node=>node.dataset.groupId==='gpt');
  assert.ok(tab.querySelector('.cs-dot').classList.contains('is-ok'));
  await control('auth-verify-codex').onclick();await flush();
  assert.ok(notices.includes('Codex checked'));
  await control('auth-copy-codex').onclick();assert.deepEqual(copied,['codex login']);
  navigator.clipboard.writeText=async()=>{throw new Error('denied');};
  await control('auth-copy-codex').onclick();assert.ok(notices.includes('复制失败，请手动复制下方命令'));
  authorized=false;await control('auth-refresh-codex').onclick();await flush();
  assert.match(root.querySelector('.cs-conn-badge').textContent,/未登录/);
  await control('auth-login-codex').onclick();assert.equal(store.getState().authPolling,null);
  await mode('gpt').onclick();await flush();
  assert.equal(store.getState().apiConfig.activeProvider,'gpt');
  for(const [key,value]of Object.entries(saved))assert.equal(store.getState().apiConfig.providers.gpt[key],value);
  await mode('codex_auth').onclick();await flush();
  await studio.load({mode:'studio'});await flush();
  assert.equal(root.querySelector('.cs-warn'),null);
  assert.ok(root.querySelectorAll('select').some(node=>node.value==='codex_auth'));
 }finally{
  studio.suspend();doc.activeElement=doc.body;root.remove();store.updateApiConfig(previous);
  if(originalNavigator)Object.defineProperty(globalThis,'navigator',originalNavigator);else delete globalThis.navigator;
 }
});

test('OpenAI configuration light follows Codex authorization and API configuration',async()=>{
 const root=doc.createElement('section');doc.body.append(root);
 const previous=structuredClone(store.getState().apiConfig);let codex={ready:false,status:'idle'};
 const studio=createCharacterStudio(root,{api:async()=>({grok:{ready:false,status:'unauthorized'},agy:{ready:false,status:'unauthorized'},codex}),notice(){},session:()=>({csrf:'csrf'}),navigate(){}});
 for(const id of ai.PROVIDER_ORDER)store.updateProviderConfig(id,{apiKey:''});
 store.updateApiConfig({activeProvider:'codex_auth'});
 try{
  await studio.load({mode:'settings',tab:'image'});await flush();
  for(const sample of [
   {status:'idle',ready:false,key:'',tone:'',count:0},
   {status:'authorized',ready:true,key:'',tone:'is-ok',count:1},
   {status:'expired',ready:false,key:'',tone:'',count:0},
   {status:'unauthorized',ready:false,key:'test-key',tone:'is-set',count:1},
   {status:'authorized',ready:true,key:'test-key',tone:'is-ok',count:1},
   {status:'check_failed',ready:false,key:'',tone:'',count:0},
   {status:'api_key_only',ready:false,key:'',tone:'',count:0},
  ]){
   codex={ready:sample.ready,status:sample.status};store.updateProviderConfig('gpt',{apiKey:sample.key});
   await store.refreshAuthStatus();await flush();
   const tab=root.querySelectorAll('.cs-provider-tab').find(node=>node.dataset.groupId==='gpt');
   assert.equal(tab.querySelector('.cs-dot').className,sample.tone?'cs-dot '+sample.tone:'cs-dot',sample.status);
   assert.match(root.querySelector('.cs-conn-badge').textContent,new RegExp(store.AUTH_STATUS_LABELS[sample.status]));
   assert.match(root.querySelector('#cs-modality-tab-image').textContent,new RegExp(`${sample.count}/5`));
  }
 }finally{studio.suspend();store.updateApiConfig(previous);root.remove();}
});

test('Codex subscription generation sends references without an API key and keeps API mode separate',async()=>{
 const originalFetch=globalThis.fetch,calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({url,options,body:JSON.parse(options.body)});return {ok:true,json:async()=>({image_url:'data:image/png;base64,AA==',model:'gpt-image-2',provider:'codex_auth'})};};
 const config=store.mergeStoredConfig({activeProvider:'codex_auth',codexParams:{aspectRatio:'1:1'},providers:{gpt:{apiKey:'',model:'gpt-image-2'}}});
 try{
  const result=await ai.generateCharacterImage({recipe:{extraImages:[{url:'data:image/png;base64,AA=='}]},prompt:'reference test',config});
  assert.equal(result.providerUsed,'codex_auth');assert.equal(result.modelUsed,'gpt-image-2');
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/v1/character-studio/generate');
  assert.equal(calls[0].body.provider,'codex_auth');assert.equal(calls[0].body.aspect_ratio,'1:1');
  assert.equal(calls[0].body.model,'image-generation');assert.equal(calls[0].body.references.length,1);
  assert.equal(calls[0].body.apiKey,undefined);assert.equal(calls[0].options.headers.Authorization,undefined);
  await assert.rejects(ai.generateCharacterImage({recipe:{extraImages:[{url:'data:image/png;base64,AA=='}]},prompt:'test',config:{...config,activeProvider:'gpt'}}),/API Key/);
  assert.equal(calls.length,1);
 }finally{globalThis.fetch=originalFetch;}
});
