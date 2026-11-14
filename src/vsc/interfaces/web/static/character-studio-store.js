// Shared character-studio state: recipe, provider configuration, CLI/OAuth auth status,
// history and active generation. Lives at module scope so switching pages keeps progress.
import {buildRecipePrompt,durableImage,durableRecipe,generateCharacterImage,PROVIDER_META,PROVIDER_ORDER,VIDEO_PROVIDER_META,VIDEO_PROVIDER_ORDER,
 stitchRecipeCanvas,referenceImageUrl,localCostumeImageUrl,poseThumbPath,sanitizeCostumeItem,setCsrfProvider,fetchAuthStatus,verifyAuthProvider,triggerAuthLogin} from './character-studio-ai.js';
import {generatedImageBlob,imageExtension,newPublication,publicationPayload} from './character-studio-publication.js';

const CFG_KEY='pose_atlas_api_config_v3',RECIPE_KEY='pose_atlas_recipe_v3',HISTORY_KEY='pose_atlas_history_v3',SAFE_KEY='pose_atlas_safe_mode_v1';
const DB_NAME='pose_atlas_studio_db',STORE_NAME='kv_store';
export const NSFW_POSE_SYSTEMS=new Set(['全身单人・性感系','双人缠绵']);
export const NSFW_COSTUME_CATEGORIES=new Set(['内衣・睡衣','性感穿搭']);
export const isNsfwCostume=item=>Boolean(item?.敏感)||NSFW_COSTUME_CATEGORIES.has(item?.分类);
export const isNsfwPose=item=>NSFW_POSE_SYSTEMS.has(item?.体系);
const proxyDefault=provider=>provider==='grok'||provider==='qwen'||provider==='doubao';
const videoProxyDefault=provider=>provider==='grok_video'||provider==='qwen_video'||provider==='doubao_video';
const clone=v=>JSON.parse(JSON.stringify(v));

function defaultConfig(){
 const provider=id=>({baseUrl:PROVIDER_META[id].defaultBaseUrl,apiKey:'',model:PROVIDER_META[id].models[0].value,customModel:''});
 const videoProvider=id=>({baseUrl:VIDEO_PROVIDER_META[id].defaultBaseUrl,apiKey:'',model:VIDEO_PROVIDER_META[id].models[0].value,customModel:''});
 const providers={};for(const id of PROVIDER_ORDER)providers[id]=provider(id);
 const videoProviders={};for(const id of VIDEO_PROVIDER_ORDER)videoProviders[id]=videoProvider(id);
 return {
  activeProvider:'agy_auth',imagePassMode:'url',useProxy:false,stylePreset:'realistic',sendStitchedSheet:false,
  activeVideoProvider:'grok_video_auth',videoUseProxy:false,
  providers,
  videoProviders,
  videoDefaults:{mode:'image_to_video',aspectRatio:'16:9',resolution:'720p',durationSec:'5',generateAudio:true},
  agyParams:{aspectRatio:'3:4'},
  codexParams:{aspectRatio:'3:4'},
  grokParams:{endpointMode:'auto',aspectRatio:'3:4',resolution:'2k',responseFormat:'auto'},
  gptParams:{endpointMode:'images_edits_json',size:'1024x1536',quality:'high',inputFidelity:'high',background:'auto',outputFormat:'png',moderation:'auto'},
  geminiParams:{endpointMode:'native',aspectRatio:'3:4',imageSize:'2K'},
  qwenParams:{size:'1024*1536',promptExtend:true,watermark:false,negativePrompt:'',n:1},
  doubaoParams:{size:'2K',sequentialImageGeneration:'disabled',watermark:false,responseFormat:'b64_json'},
 };
}
export const DEFAULT_API_CONFIG=defaultConfig();

export function mergeStoredConfig(raw){
 const base=defaultConfig();
 if(!raw||typeof raw!=='object')return base;
 const activeProvider=PROVIDER_META[raw.activeProvider]?raw.activeProvider:base.activeProvider;
 const useProxy=raw.useProxy===undefined?proxyDefault(activeProvider):Boolean(raw.useProxy);
 const activeVideoProvider=VIDEO_PROVIDER_META[raw.activeVideoProvider]?raw.activeVideoProvider:base.activeVideoProvider;
 const videoUseProxy=raw.videoUseProxy===undefined?videoProxyDefault(activeVideoProvider):Boolean(raw.videoUseProxy);
 const providers={};
 for(const id of PROVIDER_ORDER){
  const merged={...base.providers[id],...raw.providers?.[id]};
  if(!PROVIDER_META[id].models.some(m=>m.value===merged.model))merged.model=PROVIDER_META[id].models[0].value;
  providers[id]=merged;
 }
 const videoProviders={};
 for(const id of VIDEO_PROVIDER_ORDER){
  const merged={...base.videoProviders[id],...raw.videoProviders?.[id]};
  if(!VIDEO_PROVIDER_META[id].models.some(m=>m.value===merged.model))merged.model=VIDEO_PROVIDER_META[id].models[0].value;
  videoProviders[id]=merged;
 }
 return {
  activeProvider,
  imagePassMode:raw.imagePassMode==='base64'?'base64':'url',
  useProxy,
  stylePreset:raw.stylePreset||base.stylePreset,
  sendStitchedSheet:Boolean(raw.sendStitchedSheet),
  activeVideoProvider,
  videoUseProxy,
  providers,
  videoProviders,
  videoDefaults:{...base.videoDefaults,...raw.videoDefaults},
  agyParams:{...base.agyParams,...raw.agyParams},
  codexParams:{...base.codexParams,...raw.codexParams},
  grokParams:{...base.grokParams,...raw.grokParams},
  gptParams:{...base.gptParams,...raw.gptParams},
  geminiParams:{...base.geminiParams,...raw.geminiParams},
  qwenParams:{...base.qwenParams,...raw.qwenParams},
  doubaoParams:{...base.doubaoParams,...raw.doubaoParams},
 };
}

// ------------------------------------------------------------------ storage helpers
const storage=()=>{try{return typeof window!=='undefined'&&window.localStorage?window.localStorage:null;}catch{return null;}};
const ls={get(key){try{return storage()?.getItem(key)??null;}catch{return null;}},set(key,value){try{storage()?.setItem(key,value);}catch{}},remove(key){try{storage()?.removeItem(key);}catch{}}};
function openDb(){
 return new Promise((resolve,reject)=>{
  if(typeof indexedDB==='undefined'){reject(new Error('IndexedDB unavailable'));return;}
  const req=indexedDB.open(DB_NAME,1);
  req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains(STORE_NAME))db.createObjectStore(STORE_NAME);};
  req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
 });
}
async function idbRead(key){
 const db=await openDb();
 try{return await new Promise((resolve,reject)=>{const tx=db.transaction(STORE_NAME,'readonly'),r=tx.objectStore(STORE_NAME).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
 finally{db.close();}
}
async function idbWrite(key,value){
 const db=await openDb();
 try{await new Promise((resolve,reject)=>{const tx=db.transaction(STORE_NAME,'readwrite');tx.objectStore(STORE_NAME).put(value,key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
 finally{db.close();}
}
const readJson=(key,fallback)=>{try{const raw=ls.get(key);return raw?JSON.parse(raw):fallback;}catch{return fallback;}};
const emptyRecipe=()=>({portrait:null,costume:null,pose:null,extraImages:[]});
const recipeBackup=r=>({portrait:r.portrait?.source==='upload'?null:r.portrait,costume:r.costume?.source==='upload'?null:r.costume,pose:r.pose?.source==='upload'?null:r.pose,extraImages:[]});

const defaultAuthState=()=>({
 codex:{provider:'codex',cli_installed:false,ready:false,status:'idle',account:null,message:'尚未检测本机 Codex 订阅授权',login_command:'codex login'},
 grok:{provider:'grok_auth',cli_installed:false,ready:false,status:'idle',account:null,message:'尚未检测本机 Grok 订阅授权状态',login_command:'grok login --oauth'},
 agy:{provider:'agy_auth',cli_installed:false,ready:false,status:'idle',account:null,message:'尚未检测本机 AGY 授权状态',login_command:'agy'},
});

// ------------------------------------------------------------------ state
const storedRecipe=readJson(RECIPE_KEY,null);
const state={
 recipe:storedRecipe?{...emptyRecipe(),portrait:storedRecipe.portrait??null,costume:sanitizeCostumeItem(storedRecipe.costume)??null,pose:storedRecipe.pose??null}:emptyRecipe(),
 apiConfig:mergeStoredConfig(readJson(CFG_KEY,null)),
 authStatus:defaultAuthState(),
 authPolling:null,
 history:readJson(HISTORY_KEY,[]),
 safeMode:ls.get(SAFE_KEY)===null?true:ls.get(SAFE_KEY)!=='false',
 poseDepthMode:Boolean(storedRecipe?.pose?.useDepth),
 customPrompt:null,previewUrl:'',currentResult:null,publicationTask:null,resultError:'',resultErrorId:null,isGenerating:false,generatingModel:'',generationProgress:null,generationError:'',
 hydrated:false,
};
// The result belongs to this page session. Saved history is opened explicitly.
const listeners=new Set();
let host={notice:()=>{},api:null,csrf:()=>'',session:()=>({})};
let activeController=null,historyWrites=Promise.resolve(),hydration=null,authPollTimer=null,authEpoch=0;

export function configureStudio(options={}){
 host={...host,...options};
 setCsrfProvider(()=>host.csrf?.()||'');
 hydrate();
}
export const getState=()=>state;
export function subscribe(fn){listeners.add(fn);return ()=>listeners.delete(fn);}
let emitQueued=false;
function emit(){
 if(emitQueued)return;emitQueued=true;
 const run=()=>{emitQueued=false;for(const fn of [...listeners]){try{fn(state);}catch(error){console.error(error);}}};
 if(typeof queueMicrotask==='function')queueMicrotask(run);else Promise.resolve().then(run);
}
const toast=(message,options)=>host.notice?.(message,options);

function persistRecipe(){
 if(!state.hydrated)return;
 idbWrite(RECIPE_KEY,state.recipe).catch(()=>toast('配方保存失败，请检查浏览器存储空间'));
 ls.set(RECIPE_KEY,JSON.stringify(recipeBackup(state.recipe)));
}
function setRecipe(next){
 state.recipe={...next,costume:next?.costume?sanitizeCostumeItem(next.costume):null};
 persistRecipe();emit();
}
function saveConfig(){ls.set(CFG_KEY,JSON.stringify(state.apiConfig));emit();}

function hydrate(){
 if(hydration)return hydration;
 hydration=Promise.all([idbRead(RECIPE_KEY),idbRead(HISTORY_KEY)]).then(([recipe,history])=>{
  if(recipe){
   if(recipe.pose?.useDepth!==undefined)state.poseDepthMode=Boolean(recipe.pose.useDepth);
   state.recipe={portrait:recipe.portrait??null,costume:sanitizeCostumeItem(recipe.costume)??null,pose:recipe.pose??null,extraImages:Array.isArray(recipe.extraImages)?recipe.extraImages:[]};
  }
  if(Array.isArray(history))state.history=history;
  state.hydrated=true;emit();
 }).catch(()=>{
  state.generationError='无法读取浏览器存储，已暂停生成；请恢复存储后刷新';
  toast(state.generationError);emit();
 });
 return hydration;
}

// ------------------------------------------------------------------ auth status & OAuth login bridge
export function stopAuthPolling(){
 if(authPollTimer){clearTimeout(authPollTimer);authPollTimer=null;}
 if(state.authPolling){state.authPolling=null;emit();}
}
export async function refreshAuthStatus(){
 const epoch=++authEpoch;
 try{
  const data=await fetchAuthStatus(host.api);
  if(epoch!==authEpoch||!data||typeof data!=='object')return state.authStatus;
  if(data.grok)state.authStatus={...state.authStatus,grok:{...state.authStatus.grok,...data.grok}};
  if(data.agy)state.authStatus={...state.authStatus,agy:{...state.authStatus.agy,...data.agy}};
  if(data.codex)state.authStatus={...state.authStatus,codex:{...state.authStatus.codex,...data.codex}};
  emit();
 }catch{}
 return state.authStatus;
}
function authVendor(vendor){
 const key={grok:'grok',grok_auth:'grok',grok_video_auth:'grok',agy:'agy',agy_auth:'agy',codex:'codex',codex_auth:'codex'}[vendor];
 if(!key)throw new Error('不支持的授权类型');return key;
}
export async function verifyAuth(vendor){
 const key=authVendor(vendor);
 const data=await verifyAuthProvider(key,host.api);
 if(data&&typeof data==='object'){
  state.authStatus={...state.authStatus,[key]:{...state.authStatus[key],...data}};
  emit();
  if(data.message)toast(data.message);
 }
 return data;
}
export async function startAuthLogin(vendor){
 const key=authVendor(vendor);
 stopAuthPolling();
 const res=await triggerAuthLogin(key,host.api);
 if(res?.message)toast(res.message);
 if(res?.started===false)return res;
 state.authPolling=key;emit();
 let attempts=0;
 const poll=async()=>{
  attempts++;
  const latest=await refreshAuthStatus();
  if(latest?.[key]?.ready){
   stopAuthPolling();
   toast({grok:'Grok 订阅授权已生效',agy:'AGY 授权登录已就绪',codex:'Codex 订阅授权已就绪'}[key]);
   return;
  }
  if(attempts<36&&state.authPolling===key){authPollTimer=setTimeout(poll,2500);}
  else stopAuthPolling();
 };
 authPollTimer=setTimeout(poll,2500);
 return res;
}
export const AUTH_STATUS_LABELS={
 idle:'未检测',
 authorized:'已授权',
 expired:'登录已过期',
 unauthorized:'未登录',
 cli_missing:'未安装 CLI',
 api_key_only:'API Key 登录',
 check_failed:'检查未完成',
};

// ------------------------------------------------------------------ safe mode
export function requestUnlockNsfw(onUnlocked){
 if(!state.safeMode){onUnlocked?.();return;}
 if(typeof document==='undefined')return;
 const dialog=document.createElement('dialog');dialog.className='cs-age-gate';
 dialog.setAttribute('aria-label','年龄确认与免责声明');
 const title=document.createElement('h2');title.textContent='🔞 年龄确认与免责声明（NSFW 18+）';
 const body=document.createElement('div');body.className='cs-age-gate-body';
 for(const text of ['关闭「安全模式 (SFW)」后，图库将显示包含成人向艺术参考的敏感分类：',
  '• 动作姿势库：全身单人・性感系、双人缠绵\n• 服装穿搭库：内衣・睡衣、性感穿搭及来源标注为敏感的服装',
  '1. 年龄限制：未满 18 周岁的未成年人严禁关闭安全模式或浏览上述敏感分类。\n2. 来源说明：图鉴素材来自 ギア（@giaaibusi）；二次元服装来自 たき AI · CharaDB，适用独立来源条件，禁止真人、未成年人用途及图片再分发。\n3. 合法使用：本工具与素材仅供 AI 绘画学习与合法艺术创作使用，严禁用于违法违规、色情传播或侵害他人肖像权等用途，使用者须自行承担法律责任。']){
  const p=document.createElement('p');p.textContent=text;body.append(p);
 }
 const actions=document.createElement('div');actions.className='cs-age-gate-actions';
 const keep=document.createElement('button');keep.type='button';keep.textContent='保持安全模式';keep.onclick=()=>dialog.close();
 const ok=document.createElement('button');ok.type='button';ok.className='cs-primary';ok.textContent='我已年满 18 周岁，确认解锁';
 ok.onclick=()=>{dialog.close();state.safeMode=false;ls.set(SAFE_KEY,'false');toast('已解锁 18+ 完整图库模式');emit();onUnlocked?.();};
 actions.append(keep,ok);dialog.append(title,body,actions);
 dialog.addEventListener('close',()=>dialog.remove());
 document.body.append(dialog);dialog.showModal?.();
}
export function toggleSafeMode(){
 if(state.safeMode)requestUnlockNsfw();
 else{state.safeMode=true;ls.set(SAFE_KEY,'true');toast('已开启安全模式（已隐藏 18+ 敏感分类）');emit();}
}

// ------------------------------------------------------------------ recipe actions
export function setPoseDepthMode(value){
 state.poseDepthMode=Boolean(value);
 const pose=state.recipe.pose;
 if(pose&&pose.source!=='upload'&&Boolean(pose.useDepth)!==state.poseDepthMode)setRecipe({...state.recipe,pose:{...pose,useDepth:state.poseDepthMode}});
 else emit();
}
export function toggleRecipePoseDepth(){const next=!(state.recipe.pose?.useDepth??state.poseDepthMode);setPoseDepthMode(next);toast(next?'已切换姿势图为：深度图 (Depth)':'已切换姿势图为：素体白模');}
export const setSlot=(slot,item)=>setRecipe({...state.recipe,[slot]:item});
export function isSelected(slot,item){
 const current=state.recipe[slot];if(!current||!item||current.id!==item.id)return false;
 if(slot==='costume')return (current.selectedView||'front')===(item.selectedView||'front')||!item.views;
 return true;
}
export function toggleSlot(slot,item){
 if(slot==='pose'){
  const useDepth=item.source==='upload'?false:(item.useDepth??state.poseDepthMode);
  const remove=state.recipe.pose?.id===item.id&&Boolean(state.recipe?.pose?.useDepth)===useDepth;
  setRecipe({...state.recipe,pose:remove?null:{...item,useDepth}});
  toast(remove?'已移除姿势':`已选姿势：${item.姿势名称}（${item.角度}${useDepth?' · 深度图':''}）`);return !remove;
 }
 const remove=slot==='costume'?state.recipe.costume?.id===item.id&&(state.recipe.costume.selectedView||'front')===(item.selectedView||'front'):state.recipe[slot]?.id===item.id;
 setRecipe({...state.recipe,[slot]:remove?null:item});
 toast(remove?`已移除${slot==='portrait'?'人像':'服装'}`:slot==='portrait'?`已选人像：${item.发型名称||item.标题}`:`已选服装：${item.服装名称}`);
 return !remove;
}
export function addExtraImage({name,url}){
 setRecipe({...state.recipe,extraImages:[...(state.recipe.extraImages||[]),{id:`${Date.now()}-${Math.random().toString(36).slice(2,6)}`,name:name||'附加参考',url}]});
 toast('已添加附加参考图');
}
export const removeExtraImage=id=>setRecipe({...state.recipe,extraImages:(state.recipe.extraImages||[]).filter(x=>x.id!==id)});
export const updateExtraImageName=(id,name)=>{state.recipe={...state.recipe,extraImages:(state.recipe.extraImages||[]).map(x=>x.id===id?{...x,name}:x)};persistRecipe();};
export function clearRecipe(){setRecipe(emptyRecipe());toast('已清空配方');}

async function postRandom(payload){
 if(!host.api)throw new Error('合成台尚未连接资产服务');
 return host.api('/api/v1/asset-center/pose-gallery/random',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':host.csrf?.()||''},body:JSON.stringify({...payload,safe:state.safeMode})});
}
export async function randomizeAll(){
 const data=await postRandom({slot:'recipe'});
 setRecipe({...state.recipe,portrait:data.portrait||state.recipe.portrait,costume:data.costume||state.recipe.costume,pose:data.pose?{...data.pose,useDepth:state.poseDepthMode}:state.recipe.pose});
 toast(state.safeMode?'已随机抽取一套角色配方（安全模式）':'已随机抽取一套角色配方',{duration:3000});
}
export async function randomizeSlot(slot,scope){
 const current=state.recipe[slot],expected=current?.id??null;
 if(scope==='similar'&&current?.source==='upload'){toast('上传的参考图没有同类素材，可切到“全部”再试');return;}
 const data=await postRandom({slot,scope,current_id:current?.source==='upload'?'':(expected||'')});
 if((state.recipe[slot]?.id??null)!==expected){toast('参考已更改，本次换样已取消');return;}
 if(!data.item){toast(scope==='similar'?'没有其他同类素材，可切到“全部”再试':'没有其他可用素材');return;}
 setRecipe({...state.recipe,[slot]:slot==='pose'?{...data.item,useDepth:state.poseDepthMode}:data.item});
 toast(`已更换${{portrait:'人像',costume:'服装',pose:'姿势'}[slot]}，其他参考保持不变`);
}

// ------------------------------------------------------------------ config actions
export function updateApiConfig(patch){
 const next={...state.apiConfig,...patch};
 if(patch.activeProvider&&patch.useProxy===undefined)next.useProxy=proxyDefault(patch.activeProvider);
 if(patch.activeVideoProvider&&patch.videoUseProxy===undefined)next.videoUseProxy=videoProxyDefault(patch.activeVideoProvider);
 state.apiConfig=next;saveConfig();
}
export function updateProviderConfig(provider,patch){state.apiConfig={...state.apiConfig,providers:{...state.apiConfig.providers,[provider]:{...state.apiConfig.providers[provider],...patch}}};saveConfig();}
export function updateVideoProviderConfig(provider,patch){state.apiConfig={...state.apiConfig,videoProviders:{...state.apiConfig.videoProviders,[provider]:{...state.apiConfig.videoProviders[provider],...patch}}};saveConfig();}
export function updateVideoDefaults(patch){state.apiConfig={...state.apiConfig,videoDefaults:{...state.apiConfig.videoDefaults,...patch}};saveConfig();}
export function updateParams(group,patch){state.apiConfig={...state.apiConfig,[group]:{...state.apiConfig[group],...patch}};saveConfig();}
export function setCustomPrompt(value){state.customPrompt=value;emit();}
export function currentPrompt(){return state.customPrompt??buildRecipePrompt(state.recipe,state.apiConfig.stylePreset);}

// ------------------------------------------------------------------ history & generation
function persistHistory(update){
 const write=historyWrites.catch(()=>{}).then(async()=>{const next=update(state.history);await idbWrite(HISTORY_KEY,next);ls.remove(HISTORY_KEY);state.history=next;emit();});
 historyWrites=write;return write;
}
function clearLinkedResult(id){if(id&&state.currentResult?.id===id){state.currentResult=null;state.previewUrl='';state.resultError='';emit();}}
export async function removeHistoryItem(id){
 if(state.publicationTask?.resultId===id){toast('正在放入官方资产库，请完成后再删除');return false;}
 try{await persistHistory(c=>c.filter(x=>x.id!==id));clearLinkedResult(id);toast('已删除该条记录');return true;}
 catch{toast('删除失败，请检查浏览器存储空间');return false;}
}
export async function clearHistory(){
 if(state.publicationTask){toast('正在放入官方资产库，请完成后再清空');return false;}
 const ids=new Set(state.history.map(x=>x.id)),currentId=state.currentResult?.id;
 try{await persistHistory(c=>c.filter(x=>!ids.has(x.id)));if(ids.has(currentId))clearLinkedResult(currentId);toast('已清空记录');return true;}
 catch{toast('清空记录失败，请检查浏览器存储空间');return false;}
}
export async function deleteCurrentResult(id){
 if(state.isGenerating||state.publicationTask||state.currentResult?.id!==id)return false;
 const ok=await removeHistoryItem(id);
 if(!ok&&state.currentResult?.id===id){state.resultError='删除失败，当前图片与本地记录已保留，请恢复浏览器存储后重试';state.resultErrorId=id;emit();}
 return ok;
}
export function setPreviewUrl(url){state.previewUrl=url;state.currentResult=null;emit();}

const sessionActor=()=>String(host.session?.()?.actor||'');
function assertActor(actor){if(!actor||sessionActor()!==actor)throw new Error('登录身份已更改，本次入库已停止；请使用原账号继续');}
function resultFor(id){return state.currentResult?.id===id?state.currentResult:state.history.find(x=>x.id===id);}
async function officialCapability(actor){
 assertActor(actor);if(!host.api)throw new Error('合成台尚未连接资产服务');
 const receipt=await host.api('/api/v1/asset-center/official/capabilities',{headers:{'X-CSRF-Token':host.csrf?.()||''}});
 assertActor(actor);
 if(receipt?.can_publish===false)throw new Error('当前账号没有发布官方资产的权限；图片与本地记录保持原状，可继续下载');
 if(receipt?.can_publish!==true)throw new Error('无法读取官方资产发布权限，请重试');
}
export async function checkOfficialPublication(id){
 if(state.isGenerating||state.publicationTask||!resultFor(id))return false;
 const actor=sessionActor(),task={resultId:id,actor,phase:'checking'};state.publicationTask=task;state.resultError='';state.resultErrorId=id;emit();
 try{await officialCapability(actor);return resultFor(id)?{actor}:false;}
 catch(error){const message=error?.message||'无法检查官方资产发布权限，请重试';if(!state.currentResult||state.currentResult.id===id){state.resultError=message;state.resultErrorId=id;}toast(message);emit();return false;}
 finally{if(state.publicationTask===task){state.publicationTask=null;emit();}}
}
async function checkpointResult(result,publication){
 // Keep an actual server receipt in memory even when browser persistence fails.
 result.publication=publication;
 if(state.currentResult?.id===result.id){state.currentResult={...state.currentResult,publication};emit();}
 await persistHistory(c=>[{...result,publication},...c.filter(x=>x.id!==result.id)]);
}
export async function publishCurrentResult(id,{title,allowWorkspaceReuse=false,actor:confirmedActor}={}){
 if(state.isGenerating||state.publicationTask)return false;
 const result=resultFor(id);if(!result)return false;
 const actor=sessionActor(),task={resultId:id,actor,phase:'checking'};
 if(confirmedActor&&confirmedActor!==actor){state.resultError='登录身份已更改，请重新确认入库';state.resultErrorId=id;emit();return false;}
 if(!allowWorkspaceReuse){state.resultError='请明确确认有权在工作区共享与复用这张图片';state.resultErrorId=id;emit();return false;}
 if(result.publication?.officialReceipt&&result.publication.actor===actor){return result.publication.officialReceipt;}
 state.publicationTask=task;state.resultError='';state.resultErrorId=id;emit();let publication=result.publication;
 const setPhase=phase=>{task.phase=phase;emit();};
 const post=async(path,payload)=>{assertActor(actor);const response=await host.api(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':host.csrf?.()||''},body:JSON.stringify(payload)});assertActor(actor);return response;};
 try{
  await officialCapability(actor);
  if(publication&&publication.actor!==actor)throw new Error('这次入库由另一账号发起，请切回原账号继续，不能复用另一身份的回执');
  if(!publication){const name=String(title||'').trim();if(!name||name.length>200)throw new Error('请输入 1–200 字的资产名称');publication=await newPublication(result,actor,name);}
  assertActor(actor);await checkpointResult(result,publication);assertActor(actor);
  if(!publication.uploadReceipt){
   setPhase('uploading');const blob=await generatedImageBlob(result);assertActor(actor);
   const response=await host.api('/api/v1/library/uploads',{method:'POST',headers:{'Content-Type':blob.type,'X-Filename':encodeURIComponent(`character-${result.id}.${imageExtension(result.imageUrl,blob.type)}`),'X-CSRF-Token':host.csrf?.()||''},body:blob});
   assertActor(actor);if(!response?.staged_upload)throw new Error('上传未返回图片回执，请重试');
   publication={...publication,phase:'uploaded',uploadReceipt:response,importPayload:{...publication.importPayload,members:[{member_key:'front',staged_upload:response.staged_upload}]}};
   await checkpointResult(result,publication);assertActor(actor);
  }
  if(!publication.importReceipt){
   setPhase('importing');const receipt=await post('/api/v1/library/import',{confirmed:true,payload:publication.importPayload});
   if(!receipt?.entry_id||!(receipt.library_version_id||receipt.version_id))throw new Error('共享库未返回固定版本回执，请重试');
   publication={...publication,phase:'imported',importReceipt:receipt};
   await checkpointResult(result,publication);assertActor(actor);
  }
  setPhase('publishing');
  publication={...publication,publishPayload:publication.publishPayload||publicationPayload(publication)};
  await checkpointResult(result,publication);assertActor(actor);
  const receipt=await post('/api/v1/asset-center/official/publish',{payload:publication.publishPayload});
  if(!receipt?.id||receipt.entry_id!==publication.publishPayload.entry_id||receipt.library_version_id!==publication.publishPayload.library_version_id)throw new Error('官方资产未返回有效发布回执，请重试以恢复结果');
  publication={...publication,phase:'published',officialReceipt:receipt};
  try{await checkpointResult(result,publication);toast('已放入官方资产库 · 人设');}
  catch{publication.recoveryError='已成功入库，但浏览器未能保存回执；请查看官方资产，并保留当前页面中的回执';result.publication=publication;if(state.currentResult?.id===id){state.currentResult={...state.currentResult,publication};emit();}toast(publication.recoveryError);}
  return receipt;
 }catch(error){
  const message=(error?.message||'入库失败，请重试')+'；本次图片已保留';
  if(publication){publication.lastError=message;result.publication=publication;if(state.currentResult?.id===id)state.currentResult={...state.currentResult,publication};}
  if(sessionActor()===actor&&(!state.currentResult||state.currentResult.id===id)){state.resultError=message;state.resultErrorId=id;}
  emit();
  return false;
 }finally{if(state.publicationTask===task){state.publicationTask=null;emit();}}
}
export async function refreshStitchPreview(){
 try{const url=await stitchRecipeCanvas(state.recipe);toast('已合成参考拼图');return url;}
 catch(error){toast(error?.message||'拼图失败');return '';}
}
export async function snapshotGeneration(recipe,config,prompt){
 const {providers,videoProviders,...settings}=clone(config);
 const models=Object.fromEntries(Object.entries(providers).map(([key,value])=>[key,{model:value.model,customModel:value.customModel}]));
 const videoModels=Object.fromEntries(Object.entries(videoProviders||{}).map(([key,value])=>[key,{model:value.model,customModel:value.customModel}]));
 return {recipe:await durableRecipe(recipe),prompt,settings,models,videoModels};
}
const throwIfAborted=signal=>{if(signal.aborted){const e=new Error('已停止');e.name='AbortError';throw e;}};
async function completeGeneration(result,record,signal){
 throwIfAborted(signal);
 const id=crypto.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
 const entry={id,createdAt:Date.now(),imageUrl:result.imageUrl,provider:result.providerUsed,model:result.modelUsed,prompt:record.prompt,recipeSummary:record.summary,snapshot:record.snapshot};
 state.currentResult=entry;state.previewUrl=entry.imageUrl;state.resultError='';emit();
 let imageUrl;
 try{imageUrl=await durableImage(result.imageUrl);}
 catch{state.previewUrl=result.imageUrl;throw new Error('图已生成，但图片转存失败，请先下载当前图片并检查网络与浏览器存储');}
 throwIfAborted(signal);
 entry.imageUrl=imageUrl;
 if(state.currentResult?.id===id){state.currentResult=entry;state.previewUrl=imageUrl;emit();}
 try{await persistHistory(c=>[entry,...c.filter(x=>x.id!==id)]);}
 catch{throw new Error('图已生成，但生成记录保存失败，请先下载当前图片并检查浏览器存储空间');}
 toast('角色图已完成并保存');
}
export function cancelGeneration(){
 activeController?.abort();
}
export async function startGeneration(overridePrompt){
 if(state.isGenerating||state.publicationTask)return;
 if(!state.hydrated){toast(state.generationError||'正在读取浏览器存储，请稍后再生成');return;}
 const recipe=state.recipe,config=state.apiConfig,prompt=overridePrompt??currentPrompt();
 const record={prompt,summary:[recipe.portrait?.发型名称,recipe.costume?.服装名称,recipe.pose?.姿势名称].filter(Boolean).join(' + ')||'自定义合成'};
 state.isGenerating=true;state.generatingModel=config.activeProvider;state.generationError='';state.generationProgress=null;emit();
 const controller=new AbortController();activeController=controller;
 try{
  record.snapshot=await snapshotGeneration(recipe,config,prompt);
  throwIfAborted(controller.signal);
  const result=await generateCharacterImage({recipe,prompt,config,signal:controller.signal,onProgress:p=>{state.generationProgress=p;emit();}});
  throwIfAborted(controller.signal);
  await completeGeneration(result,record,controller.signal);
 }catch(error){
  if(!controller.signal.aborted){
   const message=error?.message||'调用失败';
   state.generationError=message;toast(message.split('\n')[0]);
  }
 }finally{activeController=null;state.isGenerating=false;emit();}
}

// ------------------------------------------------------------------ recipe dock
export function recipeCount(recipe=state.recipe){return [recipe.portrait,recipe.costume,recipe.pose].filter(Boolean).length+(recipe.extraImages?.length||0);}
export function slotThumb(slot,item){
 if(!item)return '';
 if(slot==='pose')return referenceImageUrl(poseThumbPath(item));
 if(slot==='costume'&&item.source!=='upload')return localCostumeImageUrl(item.缩略图||item.预览图||item.原图);
 return referenceImageUrl(item.缩略图||item.预览图||item.原图);
}
export function mountRecipeDock(container,{onCompose,force=false}={}){
 const dock=document.createElement('aside');dock.className='cs-recipe-dock';dock.setAttribute('aria-label','当前角色配方');
 container.append(dock);
 const labels={portrait:'人像',costume:'服装',pose:'姿势'};
 const button=(text,fn,cls='')=>{const b=document.createElement('button');b.type='button';b.textContent=text;if(cls)b.className=cls;b.onclick=async()=>{if(b.disabled)return;b.disabled=true;try{await fn();}catch(error){toast(error?.message||String(error));}finally{b.disabled=false;}};return b;};
 const render=()=>{
  const recipe=state.recipe,count=recipeCount(recipe);
  dock.hidden=!force&&!count;
  dock.replaceChildren();
  const slots=document.createElement('div');slots.className='cs-dock-slots';
  for(const slot of ['portrait','costume','pose']){
   const item=recipe[slot],cell=document.createElement('div');cell.className='cs-dock-slot'+(item?' is-filled':'');
   cell.title=item?`${labels[slot]}：${slot==='portrait'?item.标题||item.发型名称:slot==='costume'?item.服装名称:item.姿势名称}`:`${labels[slot]}：未选择`;
   if(item){const img=document.createElement('img');img.src=slotThumb(slot,item);img.alt=labels[slot];img.loading='lazy';cell.append(img);}
   else{const span=document.createElement('span');span.textContent=labels[slot];cell.append(span);}
   slots.append(cell);
  }
  const extra=recipe.extraImages?.length;if(extra){const badge=document.createElement('span');badge.className='cs-dock-extra';badge.textContent=`+${extra}`;slots.append(badge);}
  const actions=document.createElement('div');actions.className='cs-dock-actions';
  const clear=button('×',()=>clearRecipe(),'cs-dock-clear');clear.setAttribute('aria-label','清空配方');clear.title='清空配方';
  actions.append(
   button('随机',randomizeAll),
   button('复制词',async()=>{await navigator.clipboard?.writeText(currentPrompt());toast('已复制提示词');}),
   button(`合成 (${count})`,()=>onCompose?.(),'cs-primary'),
   clear,
  );
  dock.append(slots,actions);
 };
 render();
 const off=subscribe(render);
 return {update:render,destroy(){off();dock.remove();}};
}
