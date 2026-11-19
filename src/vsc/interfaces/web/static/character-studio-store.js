// Shared character-studio state: recipe, provider configuration, CLI/OAuth auth status,
// history and active generation. Lives at module scope so switching pages keeps progress.
import {buildRecipePrompt,durableImage,durableRecipe,generateCharacterImage,PROVIDER_META,PROVIDER_ORDER,VIDEO_PROVIDER_META,VIDEO_PROVIDER_ORDER,
 stitchRecipeCanvas,referenceImageUrl,localCostumeImageUrl,poseThumbPath,sanitizeCostumeItem,setCsrfProvider,fetchAuthStatus,verifyAuthProvider,triggerAuthLogin,
 PIXAI_BASE_URL,PIXAI_FLASH_MODEL,PIXAI_ASPECT_RATIOS,resumePixAiTask} from './character-studio-ai.js';
import {generatedImageBlob,imageExtension,newPublication,publicationPayload} from './character-studio-publication.js';

const CFG_KEY='pose_atlas_api_config_v3',RECIPE_KEY='pose_atlas_recipe_v3',HISTORY_KEY='pose_atlas_history_v3',SAFE_KEY='pose_atlas_safe_mode_v1',PIXAI_TASK_KEY='pose_atlas_pixai_task_v1';
const DB_NAME='pose_atlas_studio_db',STORE_NAME='kv_store';
export const NSFW_POSE_SYSTEMS=new Set(['全身单人・性感系','双人缠绵']);
export const NSFW_COSTUME_CATEGORIES=new Set(['内衣・睡衣','性感穿搭']);
export const isNsfwCostume=item=>Boolean(item?.敏感)||NSFW_COSTUME_CATEGORIES.has(item?.分类);
export const isNsfwPose=item=>NSFW_POSE_SYSTEMS.has(item?.体系);
const proxyDefault=provider=>provider==='grok'||provider==='qwen'||provider==='doubao'||provider==='kling'||provider==='pixai';
const videoProxyDefault=provider=>provider==='grok_video'||provider==='qwen_video'||provider==='doubao_video'||provider==='kling_video';
const clone=v=>JSON.parse(JSON.stringify(v));

function defaultConfig(){
 const provider=id=>({
  baseUrl:PROVIDER_META[id].defaultBaseUrl,
  ...(PROVIDER_META[id].supportsDualAuth?{authMode:'aksk',accessKey:'',secretKey:''}:{}),
  apiKey:'',
  model:PROVIDER_META[id].models[0].value,
  customModel:'',
 });
 const videoProvider=id=>({
  baseUrl:VIDEO_PROVIDER_META[id].defaultBaseUrl,
  ...(VIDEO_PROVIDER_META[id].supportsDualAuth?{authMode:'aksk',accessKey:'',secretKey:''}:{}),
  apiKey:'',
  model:VIDEO_PROVIDER_META[id].models[0].value,
  customModel:'',
 });
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
  pixaiParams:{aspectRatio:'3:4',size:'1k',mode:'default',negativePrompt:''},
  klingParams:{aspectRatio:'3:4',resolution:'2k',imageReference:'subject',imageFidelity:0.5,humanFidelity:0.45,negativePrompt:''},
 };
}
function mergePixAiParams(raw,model){
 const base=defaultConfig().pixaiParams;
 const next={...base,...(raw&&typeof raw==='object'?raw:{})};
 if(!PIXAI_ASPECT_RATIOS.includes(next.aspectRatio))next.aspectRatio=base.aspectRatio;
 if(!['1k','1.5k'].includes(next.size))next.size=base.size;
 next.negativePrompt=String(next.negativePrompt||'').slice(0,4096);
 next.mode=model!==PIXAI_FLASH_MODEL&&['default','pro','ultra'].includes(next.mode)?next.mode:'default';
 if(next.seed===undefined||next.seed===null||next.seed==='')delete next.seed;
 else if(!Number.isSafeInteger(Number(next.seed)))delete next.seed;
 else next.seed=Number(next.seed);
 return next;
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
  if(id==='pixai'){merged.baseUrl=PIXAI_BASE_URL;merged.customModel='';}
  if(PROVIDER_META[id].supportsDualAuth){
   merged.authMode=merged.authMode==='apikey'?'apikey':'aksk';
   merged.accessKey=String(merged.accessKey||'');
   merged.secretKey=String(merged.secretKey||'');
  }
  providers[id]=merged;
 }
 const videoProviders={};
 for(const id of VIDEO_PROVIDER_ORDER){
  const merged={...base.videoProviders[id],...raw.videoProviders?.[id]};
  if(!VIDEO_PROVIDER_META[id].models.some(m=>m.value===merged.model))merged.model=VIDEO_PROVIDER_META[id].models[0].value;
  if(VIDEO_PROVIDER_META[id].supportsDualAuth){
   merged.authMode=merged.authMode==='apikey'?'apikey':'aksk';
   merged.accessKey=String(merged.accessKey||'');
   merged.secretKey=String(merged.secretKey||'');
  }
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
  pixaiParams:mergePixAiParams(raw.pixaiParams,providers.pixai?.model),
  klingParams:{...base.klingParams,...raw.klingParams},
 };
}

export function isProviderCredentialReady(id,pCfg){
 const meta=PROVIDER_META[id]||VIDEO_PROVIDER_META[id];
 const cfg=pCfg||(PROVIDER_META[id]?state.apiConfig.providers?.[id]:state.apiConfig.videoProviders?.[id])||{};
 if(meta?.supportsDualAuth||id==='kling'||id==='kling_video'){
  const mode=(cfg.authMode||'aksk')==='apikey'?'apikey':'aksk';
  if(mode==='aksk')return Boolean(String(cfg.accessKey||'').trim()&&String(cfg.secretKey||'').trim());
  return Boolean(String(cfg.apiKey||'').trim());
 }
 return Boolean(String(cfg.apiKey||'').trim());
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
async function idbDelete(key){
 const db=await openDb();
 try{await new Promise((resolve,reject)=>{const tx=db.transaction(STORE_NAME,'readwrite');tx.objectStore(STORE_NAME).delete(key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
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
 history:[],
 historyTotal:0,
 historyOverallTotal:0,
 historyFacets:[],
 historyQuery:{q:'',filterKey:'',offset:0,limit:20},
 historyLoading:false,
 historyLoaded:false,
 historyError:'',
 safeMode:ls.get(SAFE_KEY)===null?true:ls.get(SAFE_KEY)!=='false',
 poseDepthMode:Boolean(storedRecipe?.pose?.useDepth),
 customPrompt:null,previewUrl:'',currentResult:null,publicationTask:null,resultError:'',resultErrorId:null,isGenerating:false,generatingModel:'',generationProgress:null,generationError:'',pixaiTask:null,
 hydrated:false,
};
// The result belongs to this page session. Saved history lives in PostgreSQL + assets/ai-generate-image/.
const listeners=new Set();
let host={notice:()=>{},api:null,csrf:()=>'',session:()=>({})};
let activeController=null,hydration=null,legacyDrain=null,historyEpoch=0,authPollTimer=null,authEpoch=0;

async function recordsRequest(path,options={}){
 const headers={'Content-Type':'application/json',...(options.headers||{})};
 const csrf=host.csrf?.()||'';
 if(csrf&&!headers['X-CSRF-Token'])headers['X-CSRF-Token']=csrf;
 if(typeof host.api==='function')return host.api(path,{...options,headers});
 const res=await fetch(path,{...options,headers,credentials:'same-origin'});
 const data=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error(data?.detail||data?.message||`请求失败 (HTTP ${res.status})`);
 return data;
}

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

async function drainLegacyLocalHistory(legacyItems){
 if(!Array.isArray(legacyItems)||!legacyItems.length)return;
 if(legacyDrain)return legacyDrain;
 legacyDrain=(async()=>{
  try{
   const ordered=[...legacyItems].sort((a,b)=>(a?.createdAt||0)-(b?.createdAt||0));
   for(const item of ordered){
    if(!item?.imageUrl)continue;
    await recordsRequest('/api/v1/character-studio/records',{
     method:'POST',
     body:JSON.stringify({
      id:item.id||'',
      createdAt:item.createdAt||Date.now(),
      image_url:item.imageUrl,
      provider:item.provider||'',
      model:item.model||'',
      upstream_model:item.upstreamModel||'',
      method:item.method||'',
      method_label:item.methodLabel||'',
      endpoint:item.endpoint||'',
      prompt:item.prompt||'',
      recipe_summary:item.recipeSummary||'',
      snapshot:item.snapshot||null,
      publication:item.publication||null,
     }),
    });
   }
   await idbDelete(HISTORY_KEY).catch(()=>{});
   ls.remove(HISTORY_KEY);
  }catch{
   // Keep legacy browser copy intact if offline or backend not ready; retry next session.
  }finally{legacyDrain=null;}
 })();
 return legacyDrain;
}

function hydrate(){
 if(hydration)return hydration;
 hydration=(async()=>{
  try{
   const recipe=await idbRead(RECIPE_KEY);
   if(recipe){
    if(recipe.pose?.useDepth!==undefined)state.poseDepthMode=Boolean(recipe.pose.useDepth);
    state.recipe={portrait:recipe.portrait??null,costume:sanitizeCostumeItem(recipe.costume)??null,pose:recipe.pose??null,extraImages:Array.isArray(recipe.extraImages)?recipe.extraImages:[]};
   }
  }catch{
   // IndexedDB is optional for recipe drafts; generation history is backed by PostgreSQL API.
  }
  try{
   const task=await idbRead(PIXAI_TASK_KEY).catch(()=>null)??readJson(PIXAI_TASK_KEY,null);
   if(task?.provider==='pixai')state.pixaiTask=task;
  }catch{}
  state.hydrated=true;emit();
  try{
   const legacy=await idbRead(HISTORY_KEY).catch(()=>null)??readJson(HISTORY_KEY,null);
   if(Array.isArray(legacy)&&legacy.length)await drainLegacyLocalHistory(legacy);
  }catch{}
 })();
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
export function updateProviderConfig(provider,patch){
 const nextProvider={...state.apiConfig.providers[provider],...patch};
 const next={...state.apiConfig,providers:{...state.apiConfig.providers,[provider]:nextProvider}};
 if(provider==='pixai'){
  nextProvider.baseUrl=PIXAI_BASE_URL;
  nextProvider.customModel='';
  if(nextProvider.model===PIXAI_FLASH_MODEL)next.pixaiParams={...next.pixaiParams,mode:'default'};
 }
 state.apiConfig=next;saveConfig();
}
export function updateVideoProviderConfig(provider,patch){state.apiConfig={...state.apiConfig,videoProviders:{...state.apiConfig.videoProviders,[provider]:{...state.apiConfig.videoProviders[provider],...patch}}};saveConfig();}
export function updateVideoDefaults(patch){state.apiConfig={...state.apiConfig,videoDefaults:{...state.apiConfig.videoDefaults,...patch}};saveConfig();}
export function updateParams(group,patch){state.apiConfig={...state.apiConfig,[group]:{...state.apiConfig[group],...patch}};saveConfig();}
export function setCustomPrompt(value){state.customPrompt=value;emit();}
export function currentPrompt(){
 const recipe=state.apiConfig.activeProvider==='pixai'?{...state.recipe,extraImages:[]}:state.recipe;
 return state.customPrompt??buildRecipePrompt(recipe,state.apiConfig.stylePreset);
}

// ------------------------------------------------------------------ database history & generation
export async function fetchHistoryPage({q='',filterKey='',offset=0,limit=20}={}){
 const epoch=++historyEpoch;
 const query={q:String(q||''),filterKey:String(filterKey||''),offset:Math.max(0,Number(offset)||0),limit:Math.max(1,Number(limit)||20)};
 state.historyQuery=query;state.historyLoading=true;state.historyError='';emit();
 const params=new URLSearchParams({offset:String(query.offset),limit:String(query.limit)});
 if(query.q.trim())params.set('q',query.q.trim());
 if(query.filterKey)params.set('filter_key',query.filterKey);
 try{
  if(legacyDrain)await legacyDrain;
  const data=await recordsRequest(`/api/v1/character-studio/records?${params}`,{method:'GET'});
  if(epoch!==historyEpoch)return data;
  state.history=Array.isArray(data?.items)?data.items:[];
  state.historyTotal=Number(data?.total??state.history.length);
  state.historyOverallTotal=Number(data?.overall_total??state.historyTotal);
  state.historyFacets=Array.isArray(data?.facets)?data.facets:[];
  state.historyLoaded=true;state.historyLoading=false;state.historyError='';
  emit();
  return data;
 }catch(error){
  if(epoch===historyEpoch){
   state.historyLoading=false;
   state.historyError=error?.message||'无法从数据库读取合成记录';
   emit();
  }
  return null;
 }
}
export function refreshHistoryCount(){
 if(!state.historyLoaded&&!state.historyLoading)return fetchHistoryPage(state.historyQuery);
 return Promise.resolve(null);
}

function clearLinkedResult(id){if(id&&state.currentResult?.id===id){state.currentResult=null;state.previewUrl='';state.resultError='';emit();}}
export async function removeHistoryItem(id){
 if(state.publicationTask?.resultId===id){toast('正在放入官方资产库，请完成后再删除');return false;}
 try{
  await recordsRequest(`/api/v1/character-studio/records/${encodeURIComponent(id)}`,{method:'DELETE'});
  state.history=state.history.filter(x=>x.id!==id);
  state.historyTotal=Math.max(0,state.historyTotal-1);
  state.historyOverallTotal=Math.max(0,state.historyOverallTotal-1);
  clearLinkedResult(id);
  emit();
  fetchHistoryPage(state.historyQuery);
  toast('已删除该条记录及对应本地文件');
  return true;
 }catch(error){
  toast(error?.message||'删除记录失败，请检查数据库服务状态');
  return false;
 }
}
export async function clearHistory(){
 if(state.publicationTask){toast('正在放入官方资产库，请完成后再清空');return false;}
 const currentId=state.currentResult?.id;
 try{
  await recordsRequest('/api/v1/character-studio/records',{method:'DELETE'});
  state.history=[];state.historyTotal=0;state.historyOverallTotal=0;state.historyFacets=[];
  if(currentId)clearLinkedResult(currentId);
  emit();
  toast('已清空全部合成记录');
  return true;
 }catch(error){
  toast(error?.message||'清空记录失败，请检查数据库服务状态');
  return false;
 }
}
export async function deleteCurrentResult(id){
 if(state.isGenerating||state.publicationTask||state.currentResult?.id!==id)return false;
 const ok=await removeHistoryItem(id);
 if(!ok&&state.currentResult?.id===id){state.resultError='删除失败，当前图片与数据库记录已保留，请重试';state.resultErrorId=id;emit();}
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
 if(receipt?.can_publish===false)throw new Error('当前账号没有发布官方资产的权限；图片与合成库记录保持原状，可继续下载');
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
 result.publication=publication;
 if(state.currentResult?.id===result.id)state.currentResult={...state.currentResult,publication};
 state.history=state.history.map(x=>x.id===result.id?{...x,publication}:x);
 emit();
 const resp=await recordsRequest(`/api/v1/character-studio/records/${encodeURIComponent(result.id)}/publication`,{
  method:'PATCH',
  body:JSON.stringify({publication}),
 });
 const persisted=resp?.record;
 if(persisted){
  result.publication=persisted.publication||publication;
  if(state.currentResult?.id===result.id)state.currentResult=persisted;
  state.history=state.history.map(x=>x.id===result.id?persisted:x);
  emit();
 }
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
  catch{publication.recoveryError='已成功入库，但数据库未能更新回执；请查看官方资产，并保留当前页面中的回执';result.publication=publication;if(state.currentResult?.id===id){state.currentResult={...state.currentResult,publication};emit();}toast(publication.recoveryError);}
  return receipt;
 }catch(error){
  const message=(error?.message||'入库失败，请重试')+'；本次图片已保留';
  if(publication){
   publication={...publication,lastError:message};
   result.publication=publication;
   if(state.currentResult?.id===id)state.currentResult={...state.currentResult,publication};
   state.history=state.history.map(x=>x.id===id?{...x,publication}:x);
   if(sessionActor()===actor)recordsRequest(`/api/v1/character-studio/records/${encodeURIComponent(id)}/publication`,{method:'PATCH',body:JSON.stringify({publication})}).catch(()=>{});
  }
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
 if(result.persistedRecord?.id&&result.persistedRecord?.imageUrl){
  const saved=result.persistedRecord;
  state.currentResult=saved;state.previewUrl=saved.imageUrl;state.resultError='';
  state.history=[saved,...state.history.filter(x=>x.id!==saved.id)];
  state.historyOverallTotal+=1;state.historyTotal+=1;
  emit();
  if(state.historyLoaded)fetchHistoryPage(state.historyQuery);
  toast('角色图已生成并存入数据库');
  return;
 }
 const tempId=crypto.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
 const previewEntry={
  id:tempId,
  createdAt:Date.now(),
  imageUrl:result.imageUrl,
  provider:result.providerUsed,
  model:result.modelUsed,
  method:result.methodUsed||'',
  methodLabel:result.methodLabel||'',
  endpoint:result.endpointUsed||'',
  ...(result.upstreamModel?{upstreamModel:result.upstreamModel}:{}),
  prompt:record.prompt,
  recipeSummary:record.summary,
  snapshot:record.snapshot,
 };
 state.currentResult=previewEntry;state.previewUrl=result.imageUrl;state.resultError='';emit();
 let uploadImageUrl=result.imageUrl;
 if(!String(uploadImageUrl||'').startsWith('data:image/')){
  try{uploadImageUrl=await durableImage(result.imageUrl);}
  catch{state.previewUrl=result.imageUrl;throw new Error('图已生成，但图片转存失败，请先下载当前图片并检查网络连接');}
 }
 throwIfAborted(signal);
 let saved;
 try{
  const resp=await recordsRequest('/api/v1/character-studio/records',{
   method:'POST',
   body:JSON.stringify({
    id:tempId,
    image_url:uploadImageUrl,
    provider:result.providerUsed,
    model:result.modelUsed,
    upstream_model:result.upstreamModel||'',
    method:result.methodUsed||'',
    method_label:result.methodLabel||'',
    endpoint:result.endpointUsed||'',
    prompt:record.prompt,
    recipe_summary:record.summary,
    snapshot:record.snapshot,
   }),
  });
  saved=resp?.record;
  if(!saved?.id||!saved?.imageUrl)throw new Error('服务端未返回数据库记录');
 }catch{
  state.previewUrl=uploadImageUrl;
  throw new Error('图已生成，但生成记录写入数据库失败，请先下载当前图片并检查数据库服务');
 }
 throwIfAborted(signal);
 if(state.currentResult?.id===tempId){state.currentResult=saved;state.previewUrl=saved.imageUrl;}
 state.history=[saved,...state.history.filter(x=>x.id!==saved.id)];
 state.historyOverallTotal+=1;state.historyTotal+=1;
 emit();
 if(state.historyLoaded)fetchHistoryPage(state.historyQuery);
 toast('角色图已生成并存入数据库');
}
async function writePixAiTask(task){
 state.pixaiTask=task;emit();
 try{await idbWrite(PIXAI_TASK_KEY,task);return;}catch{}
 let persisted=false;
 try{
  const box=storage();
  if(!box)throw new Error('localStorage unavailable');
  box.setItem(PIXAI_TASK_KEY,JSON.stringify(task));
  persisted=true;
 }catch{}
 if(persisted)return;
 const id=task?.task?.taskId;
 if(id)throw new Error(`[PixAI] 任务已创建但记录保存失败。任务编号：${id}；请保留编号并恢复，勿重复提交。`);
 throw new Error('[PixAI] 提交前记录保存失败，未创建任务。');
}
async function clearPixAiTask(){
 state.pixaiTask=null;emit();
 try{await idbDelete(PIXAI_TASK_KEY);}catch{}
 ls.remove(PIXAI_TASK_KEY);
}
export function cancelGeneration(){
 activeController?.abort();
}
export async function pausePixAiTracking(){
 activeController?.abort();
 if(state.pixaiTask){try{await writePixAiTask({...state.pixaiTask,paused:true});}catch{}}
 toast('已暂停本地跟踪，任务记录已保留；服务器任务继续执行');
}
export async function abandonPixAiTask(){
 if(state.isGenerating)return;
 await clearPixAiTask();
 toast('已放弃本地记录；服务器任务可能仍在执行');
}
export async function resumePixAiTracking(){
 const record=state.pixaiTask;
 if(!record?.task?.taskId||state.isGenerating||state.publicationTask)return;
 if(!state.hydrated){toast('正在初始化合成台，请稍后再试');return;}
 state.isGenerating=true;state.generatingModel='pixai';state.generationError='';state.generationProgress=null;emit();
 const controller=new AbortController();activeController=controller;
 const kept={prompt:record.prompt||'',summary:record.summary||'',snapshot:record.snapshot||null};
 try{
  await writePixAiTask({...record,paused:false});
  const result=await resumePixAiTask({
   task:record.task,apiKey:state.apiConfig.providers.pixai?.apiKey,signal:controller.signal,
   onProgress:p=>{state.generationProgress=p;emit();},
  });
  controller.signal.throwIfAborted();
  await completeGeneration(result,kept,controller.signal);
  await clearPixAiTask();
 }catch(error){
  if(!controller.signal.aborted){
   if(error?.pixaiOutcome==='rejected'||error?.pixaiOutcome==='terminal')await clearPixAiTask();
   const message=error?.message||'无法确认任务状态，记录已保留';
   state.generationError=message;toast(message.split('\n')[0]);
  }else if(state.pixaiTask){await writePixAiTask({...state.pixaiTask,paused:true}).catch(()=>{});}
 }finally{if(activeController===controller)activeController=null;state.isGenerating=false;emit();}
}
export async function recoverPixAiTask(taskId){
 const id=String(taskId||'').trim();
 if(!/^[a-zA-Z0-9_-]+$/.test(id)){toast('任务编号格式无效');return;}
 const record=state.pixaiTask;
 if(!record||record.task||state.isGenerating)return;
 await writePixAiTask({
  ...record,unknown:false,
  task:{provider:'pixai',taskId:id,baseUrl:PIXAI_BASE_URL,model:state.apiConfig.providers.pixai?.model,submittedAt:Date.now(),useProxy:Boolean(state.apiConfig.useProxy)},
 });
 await resumePixAiTracking();
}
export async function startGeneration(overridePrompt){
 if(state.isGenerating||state.publicationTask)return;
 if(!state.hydrated){toast(state.generationError||'正在初始化合成台，请稍后再试');return;}
 if(state.apiConfig.activeProvider==='pixai'&&state.pixaiTask){toast('存在待确认的 PixAI 任务，请先恢复跟踪或放弃记录');return;}
 const recipe=state.recipe,config=state.apiConfig,prompt=overridePrompt??currentPrompt();
 const record={prompt,summary:[recipe.portrait?.发型名称,recipe.costume?.服装名称,recipe.pose?.姿势名称].filter(Boolean).join(' + ')||'自定义合成'};
 state.isGenerating=true;state.generatingModel=config.activeProvider;state.generationError='';state.generationProgress=null;emit();
 const controller=new AbortController();activeController=controller;
 try{
  record.snapshot=await snapshotGeneration(recipe,config,prompt);
  throwIfAborted(controller.signal);
  const pixai=config.activeProvider==='pixai';
  const result=await generateCharacterImage({
   recipe,prompt,config,recipeSummary:record.summary,snapshot:record.snapshot,signal:controller.signal,
   onProgress:p=>{state.generationProgress=p;emit();},
   onSubmitting:pixai?async()=>{
    throwIfAborted(controller.signal);
    await writePixAiTask({provider:'pixai',unknown:true,paused:false,prompt:record.prompt,summary:record.summary,snapshot:record.snapshot,baseUrl:PIXAI_BASE_URL,task:null});
   }:undefined,
   onSubmitted:pixai?async task=>{
    await writePixAiTask({provider:'pixai',unknown:false,paused:controller.signal.aborted,prompt:record.prompt,summary:record.summary,snapshot:record.snapshot,baseUrl:task.baseUrl,task});
   }:undefined,
  });
  throwIfAborted(controller.signal);
  await completeGeneration(result,record,controller.signal);
  if(pixai)await clearPixAiTask();
 }catch(error){
  if(controller.signal.aborted){
   if(state.pixaiTask)await writePixAiTask({...state.pixaiTask,paused:true}).catch(()=>{});
   return;
  }
  if(error?.pixaiOutcome==='rejected'||error?.pixaiOutcome==='terminal')await clearPixAiTask();
  const message=error?.message||'调用失败';
  state.generationError=message;toast(message.split('\n')[0]);
 }finally{if(activeController===controller)activeController=null;state.isGenerating=false;emit();}
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
