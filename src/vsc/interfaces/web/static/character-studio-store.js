// Shared character-studio state: recipe, provider configuration, history and the
// active generation.  It lives at module scope so switching pages never interrupts
// a running generation, matching the upstream studio behaviour.
import {buildRecipePrompt,durableImage,durableRecipe,generateCharacterImage,resumeComfyTask,ComfyTaskError,ComfySubmissionRejectedError,
 PROVIDER_META,stitchRecipeCanvas,referenceImageUrl,poseThumbPath,setCsrfProvider,normalizeComfyBase,comfyFetch} from './character-studio-ai.js';
import {COMFYUI_WORKFLOW_TEMPLATES,DEFAULT_COMFY_PRESET,parseParameterWorkflow,workflowIdentity} from './character-studio-workflows.js';

const CFG_KEY='pose_atlas_api_config_v3',RECIPE_KEY='pose_atlas_recipe_v3',HISTORY_KEY='pose_atlas_history_v3',TASK_KEY='pose_atlas_active_task_v1',SAFE_KEY='pose_atlas_safe_mode_v1';
const COMFY_CONFIG_VERSION=3,DB_NAME='pose_atlas_studio_db',STORE_NAME='kv_store';
export const NSFW_POSE_SYSTEMS=new Set(['全身单人・性感系','双人缠绵']);
export const NSFW_COSTUME_CATEGORIES=new Set(['内衣・睡衣','性感穿搭']);
export const isNsfwCostume=item=>Boolean(item?.敏感)||NSFW_COSTUME_CATEGORIES.has(item?.分类);
export const isNsfwPose=item=>NSFW_POSE_SYSTEMS.has(item?.体系);
const proxyDefault=provider=>provider==='qwen'||provider==='doubao';
const clone=v=>JSON.parse(JSON.stringify(v));

function defaultConfig(){
 const provider=id=>({baseUrl:PROVIDER_META[id].defaultBaseUrl,apiKey:'',model:PROVIDER_META[id].models[0].value,customModel:''});
 return {
  activeProvider:'gemini',imagePassMode:'url',useProxy:false,stylePreset:'realistic',sendStitchedSheet:false,
  providers:{gemini:provider('gemini'),gpt:provider('gpt'),qwen:provider('qwen'),doubao:provider('doubao'),comfyui:provider('comfyui')},
  gptParams:{endpointMode:'images_edits_json',size:'1024x1536',quality:'high',inputFidelity:'high',background:'auto',outputFormat:'png',moderation:'auto'},
  geminiParams:{endpointMode:'native',aspectRatio:'3:4',imageSize:'2K'},
  qwenParams:{size:'1024*1536',promptExtend:true,watermark:false,negativePrompt:'',n:1},
  doubaoParams:{size:'2K',sequentialImageGeneration:'disabled',watermark:false,responseFormat:'b64_json'},
  comfyuiParams:{workflowPreset:DEFAULT_COMFY_PRESET,workflowJson:JSON.stringify(COMFYUI_WORKFLOW_TEMPLATES[DEFAULT_COMFY_PRESET].workflow,null,2),
   ...COMFYUI_WORKFLOW_TEMPLATES[DEFAULT_COMFY_PRESET].defaults,randomizeSeed:true,timeoutSec:600,configVersion:COMFY_CONFIG_VERSION},
 };
}
export const DEFAULT_API_CONFIG=defaultConfig();

export function mergeStoredConfig(raw){
 const base=defaultConfig();
 if(!raw||typeof raw!=='object')return base;
 const storedVer=raw.comfyuiParams?.configVersion??1;
 let comfyProvider={...base.providers.comfyui,...raw.providers?.comfyui},params={...base.comfyuiParams,configVersion:1,...raw.comfyuiParams};
 if((params.configVersion??1)<COMFY_CONFIG_VERSION){
  params={...params,configVersion:COMFY_CONFIG_VERSION};
  if(params.workflowPreset==='qwen21_3img'||params.workflowPreset==='qwen21_2img')Object.assign(params,{workflowPreset:DEFAULT_COMFY_PRESET,workflowJson:base.comfyuiParams.workflowJson,...COMFYUI_WORKFLOW_TEMPLATES[DEFAULT_COMFY_PRESET].defaults});
 }
 // The VSC host serves the same-origin /comfy relay; legacy direct URLs remain user choices.
 if(!String(comfyProvider.baseUrl||'').trim())comfyProvider.baseUrl='/comfy';
 if(!PROVIDER_META.comfyui.models.some(m=>m.value===comfyProvider.model))comfyProvider.model=PROVIDER_META.comfyui.models[0].value;
 const activeProvider=PROVIDER_META[raw.activeProvider]?raw.activeProvider:base.activeProvider;
 const useProxy=storedVer<3?proxyDefault(activeProvider):(raw.useProxy??proxyDefault(activeProvider));
 const providers={};for(const id of Object.keys(base.providers))providers[id]=id==='comfyui'?comfyProvider:{...base.providers[id],...raw.providers?.[id]};
 return {...base,...raw,activeProvider,useProxy,providers,
  gptParams:{...base.gptParams,...raw.gptParams},geminiParams:{...base.geminiParams,...raw.geminiParams},
  qwenParams:{...base.qwenParams,...raw.qwenParams},doubaoParams:{...base.doubaoParams,...raw.doubaoParams},comfyuiParams:params};
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
const emptyRecipe=()=>({portrait:null,costume:null,pose:null,extraImages:[],workflowImages:{}});
const recipeBackup=r=>({portrait:r.portrait?.source==='upload'?null:r.portrait,costume:r.costume?.source==='upload'?null:r.costume,pose:r.pose?.source==='upload'?null:r.pose,extraImages:[],workflowImages:{}});

// ------------------------------------------------------------------ state
const storedRecipe=readJson(RECIPE_KEY,null);
const state={
 recipe:storedRecipe?{...emptyRecipe(),portrait:storedRecipe.portrait??null,costume:storedRecipe.costume??null,pose:storedRecipe.pose??null}:emptyRecipe(),
 apiConfig:mergeStoredConfig(readJson(CFG_KEY,null)),
 history:readJson(HISTORY_KEY,[]),
 safeMode:ls.get(SAFE_KEY)===null?true:ls.get(SAFE_KEY)!=='false',
 poseDepthMode:Boolean(storedRecipe?.pose?.useDepth),
 customPrompt:null,previewUrl:'',isGenerating:false,generatingModel:'',generationProgress:null,generationError:'',
 activeTask:null,hydrated:false,comfyConnection:{status:'idle'},
};
state.previewUrl=state.history?.[0]?.imageUrl||'';
const listeners=new Set();
let host={notice:()=>{},api:null,csrf:()=>''};
let trackingController=null,historyWrites=Promise.resolve(),hydration=null;
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
const toast=message=>host.notice?.(message);

function persistRecipe(){
 if(!state.hydrated)return;
 idbWrite(RECIPE_KEY,state.recipe).catch(()=>toast('配方保存失败，请检查浏览器存储空间'));
 ls.set(RECIPE_KEY,JSON.stringify(recipeBackup(state.recipe)));
}
function setRecipe(next){state.recipe=next;persistRecipe();emit();}
function saveConfig(){ls.set(CFG_KEY,JSON.stringify(state.apiConfig));emit();}

function hydrate(){
 if(hydration)return hydration;
 hydration=Promise.all([idbRead(RECIPE_KEY),idbRead(HISTORY_KEY),idbRead(TASK_KEY)]).then(([recipe,history,task])=>{
  if(recipe){
   if(recipe.pose?.useDepth!==undefined)state.poseDepthMode=Boolean(recipe.pose.useDepth);
   state.recipe={portrait:recipe.portrait??null,costume:recipe.costume??null,pose:recipe.pose??null,workflowImages:recipe.workflowImages??{},workflowImagesIdentity:recipe.workflowImagesIdentity,extraImages:Array.isArray(recipe.extraImages)?recipe.extraImages:[]};
  }
  if(Array.isArray(history)){state.history=history;state.previewUrl=state.previewUrl||history[0]?.imageUrl||'';}
  state.activeTask=task||null;state.hydrated=true;emit();
  if(state.activeTask?.task)resumeGeneration();
 }).catch(()=>{state.hydrated=true;emit();});
 return hydration;
}

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
  const remove=state.recipe.pose?.id===item.id&&Boolean(state.recipe.pose?.useDepth)===useDepth;
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
export function setWorkflowImage(nodeId,image,identity){
 if(identity!==workflowIdentity(state.apiConfig.comfyuiParams.workflowJson))return;
 const images=state.recipe.workflowImagesIdentity===identity?{...state.recipe.workflowImages}:{};
 if(image)images[nodeId]=image;else delete images[nodeId];
 setRecipe({...state.recipe,workflowImages:images,workflowImagesIdentity:identity});
}
export function pruneWorkflowImages(){
 const cp=state.apiConfig.comfyuiParams,identity=workflowIdentity(cp.workflowJson),workflow=parseParameterWorkflow(cp.workflowJson);
 const mapped=[cp.portraitNodeId,cp.costumeNodeId,cp.poseNodeId,cp.stitchedNodeId];
 const ids=new Set(Object.entries(workflow||{}).filter(([id,node])=>!mapped.includes(id)&&typeof node.inputs.image==='string').map(([id])=>id));
 const entries=Object.entries(state.recipe.workflowImages||{}),kept=state.recipe.workflowImagesIdentity===identity?entries.filter(([id])=>ids.has(id)):[];
 if(entries.length===kept.length&&state.recipe.workflowImagesIdentity===identity)return;
 setRecipe({...state.recipe,workflowImages:Object.fromEntries(kept),workflowImagesIdentity:identity});
}
export function clearRecipe(){setRecipe(emptyRecipe());toast('已清空配方');}

async function postRandom(payload){
 if(!host.api)throw new Error('合成台尚未连接资产服务');
 return host.api('/api/v1/asset-center/pose-gallery/random',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':host.csrf?.()||''},body:JSON.stringify({...payload,safe:state.safeMode})});
}
export async function randomizeAll(){
 const data=await postRandom({slot:'recipe'});
 setRecipe({...state.recipe,portrait:data.portrait||state.recipe.portrait,costume:data.costume||state.recipe.costume,pose:data.pose?{...data.pose,useDepth:state.poseDepthMode}:state.recipe.pose});
 toast(state.safeMode?'已随机抽取一套角色配方（安全模式）':'已随机抽取一套角色配方');
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
 state.apiConfig=next;saveConfig();
}
export function updateProviderConfig(provider,patch){state.apiConfig={...state.apiConfig,providers:{...state.apiConfig.providers,[provider]:{...state.apiConfig.providers[provider],...patch}}};saveConfig();}
export function updateParams(group,patch){state.apiConfig={...state.apiConfig,[group]:{...state.apiConfig[group],...patch}};saveConfig();if(group==='comfyuiParams')pruneWorkflowImages();}
export function setCustomPrompt(value){state.customPrompt=value;emit();}
export function currentPrompt(){
 const cfg=state.apiConfig,recipe=state.recipe;
 return state.customPrompt??buildRecipePrompt(recipe,cfg.stylePreset,cfg.activeProvider==='comfyui'&&recipe.workflowImagesIdentity===workflowIdentity(cfg.comfyuiParams.workflowJson)?Object.values(recipe.workflowImages||{}):[]);
}

// ------------------------------------------------------------------ ComfyUI connection
let connectionEpoch=0;
export async function checkComfyConnection(){
 const cfg=state.apiConfig.providers.comfyui,epoch=++connectionEpoch;
 if(!String(cfg.baseUrl||'').trim()){state.comfyConnection={status:'notconfigured'};emit();return;}
 state.comfyConnection={...state.comfyConnection,status:'checking',error:undefined};emit();
 try{
  const res=await comfyFetch(normalizeComfyBase(cfg.baseUrl),'/system_stats',{},cfg.apiKey,8000);
  if(epoch!==connectionEpoch)return;
  if(!res.ok){state.comfyConnection={status:'error',checkedAt:Date.now(),error:res.status===401||res.status===403?`鉴权失败（HTTP ${res.status}），请检查 API Key / 鉴权设置`:`HTTP ${res.status}，请检查 ComfyUI 服务与代理`};emit();return;}
  const data=await res.json();
  const version=typeof data?.system?.comfyui_version==='string'&&/^[\d.a-zA-Z_-]{1,40}$/.test(data.system.comfyui_version)?data.system.comfyui_version:'未知版本';
  state.comfyConnection=data?.system?{status:'connected',checkedAt:Date.now(),info:`ComfyUI ${version}`}:{status:'error',checkedAt:Date.now(),error:'响应不是 ComfyUI system_stats 格式，请检查地址'};
 }catch(error){
  if(epoch!==connectionEpoch)return;
  state.comfyConnection={status:typeof navigator!=='undefined'&&navigator.onLine===false?'offline':'error',checkedAt:Date.now(),error:String(error?.message||'无法读取 ComfyUI 状态').split('\n')[0]};
 }
 emit();
}
export const COMFY_CONNECTION_LABELS={idle:'未检测',notconfigured:'未配置',checking:'检测中',connected:'HTTP 已连接',offline:'离线',error:'连接失败'};

// ------------------------------------------------------------------ history & generation
function persistHistory(update){
 const write=historyWrites.catch(()=>{}).then(async()=>{const next=update(state.history);await idbWrite(HISTORY_KEY,next).catch(()=>{});ls.remove(HISTORY_KEY);state.history=next;emit();});
 historyWrites=write;return write;
}
export function removeHistoryItem(id){persistHistory(c=>c.filter(x=>x.id!==id)).then(()=>toast('已删除该条记录'));}
export function clearHistory(){persistHistory(()=>[]).then(()=>toast('已清空记录'));}
export function setPreviewUrl(url){state.previewUrl=url;emit();}
export async function refreshStitchPreview(){
 try{state.previewUrl=await stitchRecipeCanvas(state.recipe);emit();toast('已合成参考拼图');return state.previewUrl;}
 catch(error){toast(error?.message||'拼图失败');return '';}
}
async function saveActive(value){await idbWrite(TASK_KEY,value).catch(()=>{});state.activeTask=value;emit();}
async function snapshotGeneration(recipe,config,prompt){
 const {providers,...settings}=clone(config);
 const models=Object.fromEntries(Object.entries(providers).map(([key,value])=>[key,{model:value.model,customModel:value.customModel}]));
 return {recipe:await durableRecipe(recipe),prompt,settings,models};
}
const throwIfAborted=signal=>{if(signal.aborted){const e=new Error('已停止');e.name='AbortError';throw e;}};
async function completeGeneration(result,record,signal){
 throwIfAborted(signal);
 const imageUrl=await durableImage(result.imageUrl).catch(()=>result.imageUrl);
 throwIfAborted(signal);
 state.previewUrl=imageUrl;
 const id=record.task?`comfy:${record.task.baseUrl}:${record.task.promptId}`:(crypto.randomUUID?.()||String(Date.now()));
 await persistHistory(c=>[{id,createdAt:Date.now(),imageUrl,provider:result.providerUsed,model:result.modelUsed,prompt:record.prompt,recipeSummary:record.summary,snapshot:record.snapshot},...c.filter(x=>x.id!==id)].slice(0,30));
 await saveActive(null);
 toast('角色图已完成并保存');
}
export async function resumeGeneration(){
 const record=state.activeTask;
 if(!record?.task||state.isGenerating)return;
 state.isGenerating=true;state.generationError='';emit();
 const controller=new AbortController();trackingController=controller;
 try{
  const result=await resumeComfyTask({task:record.task,apiKey:state.apiConfig.providers.comfyui.apiKey,timeoutSec:state.apiConfig.comfyuiParams.timeoutSec,onProgress:p=>{state.generationProgress=p;emit();},signal:controller.signal});
  await completeGeneration(result,record,controller.signal);
 }catch(error){
  if(error instanceof ComfySubmissionRejectedError||(error instanceof ComfyTaskError&&error.reason==='failed'))await saveActive(null);
  if(!controller.signal.aborted)state.generationError=error?.message||'无法确认任务状态，记录已保留';
 }finally{state.isGenerating=false;emit();}
}
export async function stopTracking(){
 trackingController?.abort();
 await saveActive(null);
 state.generationError='已停止跟踪；后端任务可能仍在执行，请先确认队列再提交新任务';emit();
}
export async function startGeneration(overridePrompt){
 if(state.isGenerating)return;
 if(state.activeTask){toast('存在待确认任务，请先恢复或明确停止跟踪');return;}
 const recipe=state.recipe,config=state.apiConfig,prompt=overridePrompt??currentPrompt();
 let record={prompt,summary:[recipe.portrait?.发型名称,recipe.costume?.服装名称,recipe.pose?.姿势名称].filter(Boolean).join(' + ')||'自定义合成'};
 state.isGenerating=true;state.generatingModel=config.activeProvider;state.generationError='';state.generationProgress=null;emit();
 const controller=new AbortController();trackingController=controller;
 try{
  record.snapshot=await snapshotGeneration(recipe,config,prompt);
  throwIfAborted(controller.signal);
  const result=await generateCharacterImage({recipe,prompt,config,signal:controller.signal,onProgress:p=>{state.generationProgress=p;emit();},
   onSubmitting:async prepared=>{throwIfAborted(controller.signal);if(record.snapshot&&prepared)record.snapshot.submittedWorkflowJson=JSON.stringify(prepared.workflow);await saveActive({...record,unknown:true});},
   onSubmitted:async task=>{if(controller.signal.aborted)return;record={...record,task};await saveActive(record);}});
  throwIfAborted(controller.signal);
  await completeGeneration(result,record,controller.signal);
 }catch(error){
  if(error instanceof ComfySubmissionRejectedError||(error instanceof ComfyTaskError&&error.reason==='failed'))await saveActive(null);
  const message=error?.message||'调用失败';
  state.generationError=message;toast(message.split('\n')[0]);
 }finally{state.isGenerating=false;emit();}
}

// ------------------------------------------------------------------ recipe dock
export function recipeCount(recipe=state.recipe){return [recipe.portrait,recipe.costume,recipe.pose].filter(Boolean).length+(recipe.extraImages?.length||0);}
export function slotThumb(slot,item){
 if(!item)return '';
 if(slot==='pose')return referenceImageUrl(poseThumbPath(item));
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
