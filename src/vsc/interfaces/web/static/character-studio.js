// AI 角色合成台 and API 接口配置 (全项目唯一模型配置中枢: 订阅授权 | API 配置 + 内联生产路由 + 快手可灵双鉴权).
import {openAssetImageViewer} from './asset-center.js';
import {PROVIDER_META,PROVIDER_ORDER,SETTINGS_GROUPS,SETTINGS_MODALITIES,VIDEO_PROVIDER_META,VIDEO_SETTINGS_GROUPS,
 STYLE_PRESETS,isAuthProvider,groupForProvider,isVideoAuthProvider,groupForVideoProvider,VIDEO_IMAGE_KEY_PEERS,IMAGE_VIDEO_KEY_PEERS,
 isGrokDirectImagineModel,describePlannedGeneration,resolveRecordProvenance,getGptInputFidelity,PIXAI_FLASH_MODEL,PIXAI_ASPECT_RATIOS,
 referenceImageUrl,localCostumeImageUrl,poseThumbPath,poseImagePath,selectCostumeView,uploadedReferences,fileToDataUrl,recipeImageList} from './character-studio-ai.js';
import * as store from './character-studio-store.js';
import {imageExtension,officialResultRoute,openCharacterPublication} from './character-studio-publication.js';
import {createReturnPill,isSafeReturnSearch,returnContextStorageKey} from './governance-header.js';
import {mountResourceSettingsPanel} from './resource-settings.js';

const SLOT_LABEL={portrait:'人像',costume:'服装',pose:'姿势'};
const SLOT_GALLERY={portrait:'portrait',costume:'costume',pose:'pose'};
const GALLERY_NAME={portrait:'人像颜值库',costume:'服装穿搭库',pose:'动作姿势库'};
const API_SUBVIEWS=[
 {id:'image',label:'图像 API',subtitle:'生图直连与双鉴权'},
 {id:'video',label:'视频 API',subtitle:'视频直连与参数'},
 {id:'routes',label:'音频与生产模型路由',subtitle:'PostgreSQL 环境变量注册表'},
];

function el(tag,cls='',text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=String(text);return n;}
function option(value,label,selected){const o=el('option','',label);o.value=value;if(selected)o.selected=true;return o;}
function select(options,value,onChange,{label='',key='',disabled=false}={}){
 const s=el('select');if(label)s.setAttribute('aria-label',label);if(key)s.dataset.focusKey=key;
 for(const [v,l]of options)s.append(option(v,l,String(v)===String(value)));
 s.value=String(value??'');s.disabled=Boolean(disabled);s.onchange=()=>onChange(s.value);return s;
}
function field(label,control,hint){
 if(['SELECT','INPUT','TEXTAREA'].includes(control.tagName)){if(!control.dataset.focusKey)control.dataset.focusKey=label;if(!control.getAttribute('aria-label'))control.setAttribute('aria-label',label);}
 const wrap=el('label','cs-field');wrap.append(el('span','cs-field-label',label),control);
 if(hint)wrap.append(el('small','cs-field-hint',hint));return wrap;
}
function section(title,{actions=null,cls=''}={}){
 const s=el('section','cs-section'+(cls?' '+cls:''));const head=el('header','cs-section-head');head.append(el('h2','',title));
 if(actions)head.append(actions);s.append(head);const body=el('div','cs-section-body');s.append(body);return {node:s,body,head};
}
function toggle(checked,onChange,label){
 const wrap=el('label','cs-switch');const input=el('input');input.type='checkbox';input.checked=Boolean(checked);input.onchange=()=>onChange(input.checked);
 wrap.append(input,el('span','cs-switch-track'),el('span','cs-switch-label',label||''));return wrap;
}
function download(url,name){const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();}
function svgIcon(kind){
 const ns='http://www.w3.org/2000/svg';
 const make=(tag,attrs={})=>{const n=document.createElementNS?document.createElementNS(ns,tag):document.createElement(tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
 const svg=make('svg',{viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',class:'cs-modality-icon'});
 if(kind==='video'){
  svg.append(make('rect',{x:'3',y:'5',width:'13',height:'14',rx:'2.5'}),make('path',{d:'m16 10 5-3v10l-5-3Z'}));
 }else if(kind==='routes'){
  svg.append(make('rect',{x:'3',y:'4',width:'18',height:'6',rx:'1.5'}),make('rect',{x:'3',y:'14',width:'18',height:'6',rx:'1.5'}),make('circle',{cx:'7',cy:'7',r:'1'}),make('circle',{cx:'7',cy:'17',r:'1'}));
 }else{
  svg.append(make('rect',{x:'3',y:'4',width:'18',height:'16',rx:'2.5'}),make('circle',{cx:'8.5',cy:'9.5',r:'1.5'}),make('path',{d:'m21 15-4.5-4.5L7 20'}));
 }
 return svg;
}

export function createCharacterStudio(root,ctx){
 let mode='studio',disposed=false,renderSig='',settingsHub='subscription',settingsModality='image',settingsRoutesSection='models',settingsProvider=null,settingsVideoProvider=null,showKey=false,showVideoKey=false,busy=new Set(),scopes={portrait:'similar',costume:'similar',pose:'similar'},unsub=null,pasteHandler=null,progressNode=null,errorNode=null,routesPanelNode=null,routesPanelCtrl=null;
 store.configureStudio({notice:ctx.notice,api:ctx.api,csrf:()=>ctx.session?.()?.csrf||'',session:ctx.session});
 let viewEpoch=0;
 const notice=message=>ctx.notice?.(message);
 const state=()=>store.getState();

 function bindClick(node,handler){
  node.onclick=handler;
  node.addEventListener('click',event=>{
   if(typeof Event==='undefined'||!(event instanceof Event))return handler(event);
  });
 }
 function action(text,fn,cls='',key=''){
  const b=el('button',cls,text);b.type='button';if(key)b.dataset.busyKey=key;
  if(key&&busy.has(key)){b.disabled=true;b.setAttribute('aria-busy','true');}
  bindClick(b,async event=>{
   if(b.disabled)return;
   if(key){busy.add(key);}b.disabled=true;b.setAttribute('aria-busy','true');
   try{await fn(event);}catch(error){if(!disposed)notice(error?.message||String(error));}
   finally{if(key)busy.delete(key);b.disabled=false;b.removeAttribute('aria-busy');if(key&&!disposed)render(true);}
  });
  return b;
 }
 function zoom(src,title){if(src)openAssetImageViewer({title,src:referenceImageUrl(src),host:document.body});}

 function credentialStatusLabel(id,pCfg){
  const meta=PROVIDER_META[id]||VIDEO_PROVIDER_META[id];
  const dual=Boolean(meta?.supportsDualAuth)&&(pCfg?.authMode||'aksk')!=='apikey';
  const ok=store.isProviderCredentialReady(id,pCfg);
  if(dual)return {ok,label:ok?'已配置 AK/SK':'未配置 AK/SK'};
  return {ok,label:ok?'已配置 Key':'未配置 Key'};
 }
 function providerStatusText(id){
  const s=state(),meta=PROVIDER_META[id];
  if(isAuthProvider(id)){
   const info=s.authStatus[meta.authVendor]||{};
   return store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录');
  }
  return credentialStatusLabel(id,s.apiConfig.providers[id]).label;
 }
 function videoProviderStatusText(id){
  const s=state(),meta=VIDEO_PROVIDER_META[id];
  if(isVideoAuthProvider(id)){
   const info=s.authStatus[meta.authVendor]||{};
   return store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录');
  }
  return credentialStatusLabel(id,s.apiConfig.videoProviders?.[id]).label;
 }
 function groupSummary(group){
  const s=state();
  if(group.modes.length===1){
   const id=group.modes[0],st=credentialStatusLabel(id,s.apiConfig.providers[id]);
   return {label:st.label,tone:st.ok?'is-set':''};
  }
  const [oauthId,apiId]=group.modes,vendor=PROVIDER_META[oauthId].authVendor;
  const authReady=Boolean(s.authStatus[vendor]?.ready),keyReady=store.isProviderCredentialReady(apiId,s.apiConfig.providers[apiId]);
  if(authReady&&keyReady)return {label:'授权已就绪 · Key 已配',tone:'is-ok'};
  if(authReady)return {label:`${PROVIDER_META[oauthId].shortName}已就绪`,tone:'is-ok'};
  if(keyReady)return {label:`${PROVIDER_META[apiId].shortName}已配置`,tone:'is-set'};
  return {label:'待授权或配 Key',tone:''};
 }
 function videoGroupSummary(group){
  const s=state();
  if(group.modes.length===1){
   const id=group.modes[0],st=credentialStatusLabel(id,s.apiConfig.videoProviders?.[id]);
   return {label:st.label,tone:st.ok?'is-set':''};
  }
  const [oauthId,apiId]=group.modes,vendor=VIDEO_PROVIDER_META[oauthId].authVendor;
  const authReady=Boolean(s.authStatus[vendor]?.ready),keyReady=store.isProviderCredentialReady(apiId,s.apiConfig.videoProviders?.[apiId]);
  if(authReady&&keyReady)return {label:'授权已就绪 · Key 已配',tone:'is-ok'};
  if(authReady)return {label:`${VIDEO_PROVIDER_META[oauthId].shortName}已就绪`,tone:'is-ok'};
  if(keyReady)return {label:`${VIDEO_PROVIDER_META[apiId].shortName}已配置`,tone:'is-set'};
  return {label:'待授权或配 Key',tone:''};
 }
 function modalityReadyCount(kind){
  const groups=kind==='video'?VIDEO_SETTINGS_GROUPS:SETTINGS_GROUPS;
  const summarize=kind==='video'?videoGroupSummary:groupSummary;
  return groups.filter(g=>Boolean(summarize(g).tone)).length;
 }

 function recordStudioOriginIfLocal(){
  if(ctx.returnContext!==undefined)return;
  const key=returnContextStorageKey(ctx.session?.()?.actor);
  if(!key||typeof sessionStorage==='undefined')return;
  try{
   sessionStorage.setItem(key,JSON.stringify({
    origin:'character-studio',
    projectId:null,
    page:'character-studio',
    search:'?page=character-studio',
    capturedAt:new Date().toISOString(),
   }));
  }catch{}
 }
 function readHubReturnContext(){
  if(ctx.returnContext!==undefined)return typeof ctx.returnContext==='function'?ctx.returnContext():ctx.returnContext;
  const key=returnContextStorageKey(ctx.session?.()?.actor);
  if(!key||typeof sessionStorage==='undefined')return null;
  try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}
 }
 function handleHubReturn(record,resolved){
  const cb=ctx.onReturnContext||ctx.onReturn;
  if(cb)return cb(record,resolved);
  const key=returnContextStorageKey(ctx.session?.()?.actor);
  if(key&&typeof sessionStorage!=='undefined'){try{sessionStorage.removeItem(key);}catch{}}
  if(resolved?.state==='character-studio')return ctx.navigate?.('character-studio');
  if(resolved?.state==='project'&&record?.search&&isSafeReturnSearch(record.search)){
   const q=new URLSearchParams(record.search.slice(1));
   const page=q.get('page')||'project';
   const opts=Object.fromEntries([...q.entries()].filter(([k])=>k!=='page'));
   return ctx.navigate?.(page,opts);
  }
  return ctx.navigate?.('home');
 }

 // ------------------------------------------------------------------ studio
 function slotCard(slot){
  const s=state(),item=s.recipe[slot],card=el('article','cs-slot'+(item?' is-filled':''));
  card.dataset.slot=slot;
  const head=el('div','cs-slot-head');head.append(el('strong','',SLOT_LABEL[slot]));
  if(item){
   const clear=action('×',()=>store.setSlot(slot,null),'cs-icon-btn');clear.setAttribute('aria-label',`清除${SLOT_LABEL[slot]}参考图`);head.append(clear);
  }
  card.append(head);
  const body=el('div','cs-slot-body');
  const thumb=el('button','cs-slot-thumb');thumb.type='button';thumb.setAttribute('aria-label',item?`放大${SLOT_LABEL[slot]}参考图`:`去${GALLERY_NAME[slot]}挑选`);
  if(item){
   const costumeLocal=slot==='costume'&&item.source!=='upload';
   const img=el('img');img.src=slot==='pose'?referenceImageUrl(poseThumbPath(item)):costumeLocal?localCostumeImageUrl(item.缩略图||item.预览图||item.原图):referenceImageUrl(item.缩略图||item.预览图||item.原图);img.alt=SLOT_LABEL[slot];img.loading='lazy';thumb.append(img);
   thumb.onclick=()=>zoom(slot==='pose'?poseImagePath(item):costumeLocal?localCostumeImageUrl(item.预览图||item.原图||item.缩略图):slot==='costume'?item.预览图||item.原图||item.缩略图:item.原图||item.缩略图,SLOT_LABEL[slot]);
  }else{thumb.append(el('span','cs-slot-empty','＋'));thumb.onclick=()=>pick(slot);}
  body.append(thumb);
  const info=el('div','cs-slot-info');
  if(item){
   const name=slot==='portrait'?item.标题||item.发型名称:slot==='costume'?item.服装名称:item.姿势名称;
   info.append(el('div','cs-slot-name',name||''));
   const meta=slot==='portrait'?[item.分区,item.发长].filter(Boolean).join(' · '):slot==='costume'?[item.来源,item.分类].filter(Boolean).join(' · '):[item.体系,item.角度].filter(Boolean).join(' · ');
   if(meta)info.append(el('small','cs-slot-meta',meta));
   if(slot==='costume'&&item.views?.length){
    info.append(select(item.views.map(v=>[v.id,v.label]),item.selectedView||'front',v=>store.setSlot('costume',selectCostumeView(item,v)),{label:'已选服装视角'}));
   }
   if(slot==='pose'&&item.source!=='upload'){
    const seg=el('div','cs-seg');
    for(const [depth,label]of [[false,'白模'],[true,'深度']]){const b=action(label,()=>store.setPoseDepthMode(depth));b.setAttribute('aria-pressed',String(Boolean(item.useDepth)===depth));seg.append(b);}
    seg.setAttribute('aria-label','切换素体白模或深度图');info.append(seg);
   }
  }else info.append(el('small','cs-slot-meta','未选择，可从图库挑选或上传本地图片'));
  body.append(info);card.append(body);
  const tools=el('div','cs-slot-tools');
  tools.append(select([['similar','同类'],['all','全部']],scopes[slot],v=>{scopes[slot]=v;},{label:`${SLOT_LABEL[slot]}换样范围`}));
  tools.append(action('换一个',()=>store.randomizeSlot(slot,scopes[slot]),'',`random-${slot}`));
  tools.append(action('去图库挑选',()=>pick(slot)));
  const upload=el('label','cs-upload-btn');upload.textContent='上传';
  const file=el('input');file.type='file';file.accept='image/*';file.setAttribute('aria-label',`上传${SLOT_LABEL[slot]}参考图`);
  file.onchange=async()=>{const f=file.files?.[0];file.value='';if(!f)return;if(!f.type.startsWith('image/')){notice('请选择图片文件');return;}
   try{const {url,width,height}=await fileToDataUrl(f);store.setSlot(slot,uploadedReferences(f.name,url,width,height,f.size)[slot]);notice(`已上传${SLOT_LABEL[slot]}参考图`);}catch(error){notice(error.message);}};
  upload.append(file);tools.append(upload);card.append(tools);
  return card;
 }
 function pick(slot){ctx.navigate?.('asset-center',{tab:'official',kind:SLOT_GALLERY[slot]});}

 function extraImages(){
  const s=state(),list=s.recipe.extraImages||[],wrap=el('div','cs-extra');
  if(s.apiConfig.activeProvider==='pixai'){
   wrap.append(el('h3','','PixAI 三图'));
   wrap.append(el('p','cs-field-hint',list.length?'PixAI 只使用人像、服装、姿势各一张。请先移除附加参考图后再生成。':'PixAI 需要人像、服装、姿势各一张，按此顺序上传，不发送拼图和附加图。'));
   if(!list.length)return wrap;
  }else wrap.append(el('h3','',`附加参考图 (${list.length})`));
  if(s.apiConfig.activeProvider==='pixai'){
   const grid=el('div','cs-extra-grid');
   for(const image of list){
    const item=el('div','cs-extra-item'),img=el('img');img.src=referenceImageUrl(image.url);img.alt=image.name;
    const remove=action('×',()=>store.removeExtraImage(image.id),'cs-icon-btn');remove.setAttribute('aria-label','移除附加参考图');
    item.append(img,remove);grid.append(item);
   }
   wrap.append(grid);
   return wrap;
  }
  const drop=el('div','cs-dropzone');drop.tabIndex=0;drop.setAttribute('role','button');
  drop.textContent='点击上传、拖入图片，或在此页面按 ⌘/Ctrl + V 粘贴图片';
  const file=el('input');file.type='file';file.accept='image/*';file.multiple=true;file.hidden=true;
  const addFiles=async files=>{for(const f of files){if(!f.type?.startsWith('image/'))continue;try{const {url}=await fileToDataUrl(f);store.addExtraImage({name:f.name.replace(/\.[^.]+$/,'')||'附加参考',url});}catch(error){notice(error.message);}}};
  file.onchange=()=>{addFiles([...(file.files||[])]);file.value='';};
  drop.onclick=()=>file.click();drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();file.click();}};
  drop.ondragover=e=>{e.preventDefault();drop.classList.add('is-over');};
  drop.ondragleave=()=>drop.classList.remove('is-over');
  drop.ondrop=e=>{e.preventDefault();drop.classList.remove('is-over');addFiles([...(e.dataTransfer?.files||[])]);};
  wrap.append(drop,file);
  const urlRow=el('div','cs-url-row'),url=el('input');url.type='url';url.placeholder='粘贴 https://... 图片地址';url.dataset.focusKey='extra-url';
  urlRow.append(url,action('添加',()=>{const v=url.value.trim();if(!/^https?:\/\//i.test(v)){notice('请输入有效的 http(s):// 图片链接');return;}store.addExtraImage({name:'链接参考',url:v});url.value='';}));
  wrap.append(urlRow);
  if(list.length){
   const grid=el('div','cs-extra-grid');
   for(const image of list){
    const item=el('div','cs-extra-item'),img=el('img');img.src=referenceImageUrl(image.url);img.alt=image.name;img.onclick=()=>zoom(image.url,image.name);
    const note=el('input');note.value=image.name;note.placeholder='备注(如:配饰/背景)';note.dataset.focusKey='extra-note-'+image.id;note.oninput=()=>store.updateExtraImageName(image.id,note.value);
    const remove=action('×',()=>store.removeExtraImage(image.id),'cs-icon-btn');remove.setAttribute('aria-label','移除附加参考图');
    item.append(img,note,remove);grid.append(item);
   }
   wrap.append(grid);
  }
  return wrap;
 }

 function stitchDialog(url){
  const dialog=el('dialog','cs-dialog cs-stitch');dialog.setAttribute('aria-label','参考拼图预览');
  const head=el('header','cs-dialog-head');head.append(el('h2','','参考拼图预览'),action('×',()=>dialog.close(),'cs-icon-btn'));
  const img=el('img');img.src=url;img.alt='参考拼图';
  const foot=el('footer','cs-dialog-foot');foot.append(action('下载拼图',()=>download(url,`recipe-sheet-${Date.now()}.jpg`),'cs-primary'),action('关闭',()=>dialog.close()));
  dialog.append(head,img,foot);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal?.();
 }

 function providerParams(){
  const cfg=state().apiConfig,p=cfg.activeProvider,box=el('div','cs-grid2');
  const up=(group,key)=>v=>store.updateParams(group,{[key]:v});
  if(p==='agy_auth'||p==='codex_auth'){
   const params=p==='codex_auth'?'codexParams':'agyParams',a=cfg[params];
   box.append(field('画幅比例',select(['3:4','1:1','4:3','9:16','16:9'].map(v=>[v,v]),a.aspectRatio,up(params,'aspectRatio'))),
    field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')));
   return box;
  }
  if(p==='grok_auth'){
   const pc=cfg.providers.grok_auth||{},effectiveModel=pc.model==='custom'?pc.customModel:pc.model;
   const gr=cfg.grokParams,usesImagineApi=isGrokDirectImagineModel(effectiveModel);
   box.append(field('画幅比例 (aspect_ratio)',select(['3:4','1:1','4:3','9:16','16:9','2:3','3:2','auto'].map(v=>[v,v]),gr.aspectRatio,up('grokParams','aspectRatio'))));
   if(usesImagineApi)box.append(field('输出分辨率 (resolution)',select([['2k','2k（高清推荐）'],['1.5k','1.5k'],['1k','1k']],gr.resolution,up('grokParams','resolution'))));
   box.append(field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')));
   return box;
  }
  if(p==='grok'){
   const gr=cfg.grokParams;
   box.append(field('接口模式',select([['auto','自动（带参考走 /images/edits ≤5张）'],['generations','仅文生图 (/v1/images/generations)']],gr.endpointMode,up('grokParams','endpointMode'))),
    field('画幅比例 (aspect_ratio)',select(['3:4','1:1','4:3','9:16','16:9','2:3','3:2','auto'].map(v=>[v,v]),gr.aspectRatio,up('grokParams','aspectRatio'))),
    field('输出分辨率 (resolution)',select([['2k','2k（高清推荐）'],['1.5k','1.5k'],['1k','1k']],gr.resolution,up('grokParams','resolution'))),
    field('返回格式 (response_format)',select([['auto','auto（推荐，自动转存临时 URL）'],['b64_json','b64_json']],gr.responseFormat,up('grokParams','responseFormat'))));
  }else if(p==='gemini'){
   const g=cfg.geminiParams;
   box.append(field('接口模式',select([['native','原生 generateContent (x-goog-api-key)'],['openai_chat','OpenAI 兼容 Chat']],g.endpointMode,up('geminiParams','endpointMode'))),
    field('画幅比例',select(['3:4','1:1','4:3','9:16','16:9'].map(v=>[v,v]),g.aspectRatio,up('geminiParams','aspectRatio'))),
    field('分辨率 (Gemini 3)',select(['1K','2K','4K'].map(v=>[v,v]),g.imageSize,up('geminiParams','imageSize'))));
  }else if(p==='gpt'){
   const g=cfg.gptParams,pc=cfg.providers.gpt||{};
   const gptModel=pc.model==='custom'?String(pc.customModel||'').trim():pc.model;
   const supportsFidelity=Boolean(getGptInputFidelity(gptModel,'high')||getGptInputFidelity(gptModel,'low'));
   box.append(field('接口模式',select([['images_edits_json','/v1/images/edits JSON（URL 直传）'],['images_edits','/v1/images/edits multipart'],['responses','/v1/responses'],['chat','Chat Completions 中转']],g.endpointMode,up('gptParams','endpointMode'))),
    field('输出尺寸 (size)',select([['1024x1536','1024x1536'],['1024x1024','1024x1024'],['1536x1024','1536x1024'],['auto','auto']],g.size,up('gptParams','size'))),
    field('渲染质量 (quality)',select(['high','xhigh','max','medium','low','auto'].map(v=>[v,v]),g.quality,up('gptParams','quality'))),
    field('参考还原度 (input_fidelity)',select([['high','high'],['low','low']],g.inputFidelity,up('gptParams','inputFidelity'),{disabled:!supportsFidelity}),supportsFidelity?'':'当前模型使用默认参考还原度，无需设置此参数。'),
    field('背景模式 (background)',select(['auto','transparent','opaque'].map(v=>[v,v]),g.background,up('gptParams','background'))),
    field('图片格式 (output_format)',select(['png','webp','jpeg'].map(v=>[v,v]),g.outputFormat,up('gptParams','outputFormat'))));
  }else if(p==='pixai'){
   const px=cfg.pixaiParams||{},flash=(cfg.providers.pixai||{}).model===PIXAI_FLASH_MODEL;
   const neg=el('textarea');neg.value=px.negativePrompt||'';neg.placeholder='低分辨率，畸形手指';neg.disabled=flash;
   neg.dataset.focusKey='pixai-negative';neg.onchange=()=>store.updateParams('pixaiParams',{negativePrompt:neg.value});
   const seed=el('input');seed.type='number';seed.step='1';seed.value=px.seed??'';seed.placeholder='留空为随机';seed.dataset.focusKey='pixai-seed';
   seed.onchange=()=>store.updateParams('pixaiParams',{seed:seed.value===''?null:Number(seed.value)});
   box.append(
    field('输出比例',select(PIXAI_ASPECT_RATIOS.map(v=>[v,v]),px.aspectRatio||'3:4',up('pixaiParams','aspectRatio'))),
    field('分辨率',select([['1k','1k'],['1.5k','1.5k']],px.size||'1k',up('pixaiParams','size'))),
    field('生成模式',select((flash?['default']:['default','pro','ultra']).map(v=>[v,v==='default'?'模型默认':v]),flash?'default':(px.mode||'default'),up('pixaiParams','mode')),'可用模式取决于模型和账号'),
    field('负向提示词',neg,flash?'Flash 不使用负向提示词。':''),
    field('Seed',seed),
   );
  }else if(p==='qwen'){
   const q=cfg.qwenParams,neg=el('textarea');neg.value=q.negativePrompt;neg.placeholder='低分辨率，多余手指，扭曲';neg.dataset.focusKey='qwen-negative';neg.onchange=()=>store.updateParams('qwenParams',{negativePrompt:neg.value});
   box.append(field('输出尺寸 (size)',select(['1024*1536','928*1664','1328*1328','1664*928'].map(v=>[v,v]),q.size,up('qwenParams','size'))),
    field('提示词扩写 (prompt_extend)',toggle(q.promptExtend,up('qwenParams','promptExtend'),q.promptExtend?'开启':'关闭')),
    field('水印 (watermark)',toggle(q.watermark,up('qwenParams','watermark'),q.watermark?'开启':'关闭')),
    field('反向提示词 (negative_prompt)',neg));
  }else if(p==='doubao'){
   const d=cfg.doubaoParams;
   box.append(field('输出尺寸 (size)',select(['1728x2304','2K','4K','1K','1440x2560','2048x2048','2560x1440'].map(v=>[v,v]),d.size,up('doubaoParams','size'))),
    field('组图模式 (sequential)',select([['disabled','disabled (单张)'],['auto','auto (组图)']],d.sequentialImageGeneration,up('doubaoParams','sequentialImageGeneration'))),
    field('返回格式 (response_format)',select([['b64_json','b64_json'],['url','url']],d.responseFormat,up('doubaoParams','responseFormat'))),
    field('水印 (watermark)',toggle(d.watermark,up('doubaoParams','watermark'),d.watermark?'开启':'关闭')));
  }else if(p==='kling'){
   const kp=cfg.klingParams||{aspectRatio:'3:4',resolution:'2k',imageReference:'subject',negativePrompt:''};
   const pc=cfg.providers.kling||{};
   const neg=el('textarea');neg.value=kp.negativePrompt||'';neg.placeholder='低分辨率，畸形手指，杂乱文字';neg.dataset.focusKey='kling-negative';neg.onchange=()=>store.updateParams('klingParams',{negativePrompt:neg.value});
   box.append(
    field('画幅比例 (aspect_ratio)',select(['3:4','1:1','4:3','9:16','16:9','2:3','3:2','21:9'].map(v=>[v,v]),kp.aspectRatio||'3:4',up('klingParams','aspectRatio'))),
    field('输出分辨率 (resolution)',select([['2k','2k（高清推荐）'],['1k','1k']],kp.resolution||'2k',up('klingParams','resolution'))),
   );
   if(pc.model==='kling-v1-5'){
    box.append(field('参考图控制类型 (image_reference)',select([['subject','subject（角色主体外观特征）'],['face','face（人物面部身份特征）']],kp.imageReference||'subject',up('klingParams','imageReference'))));
   }
   box.append(field('反向提示词 (negative_prompt)',neg));
  }
  if(p!=='pixai')box.append(field('图片传参方式',select([['url','URL'],['base64','Base64']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))),
   field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')));
  box.append(field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用':'浏览器直连')));
  return box;
 }

 function authInlineBanner(providerId){
  const s=state(),meta=PROVIDER_META[providerId],vendor=meta.authVendor,info=s.authStatus[vendor]||{};
  const bar=el('div','cs-conn '+(info.ready?'is-connected':info.status==='expired'||info.status==='cli_missing'?'is-error':''));
  bar.setAttribute('role','status');
  bar.append(el('span','cs-conn-badge',`${meta.shortName} · ${store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录')}`));
  bar.append(el('span','cs-conn-msg',info.message||''));
  const acts=el('div','cs-row-actions');
  if(!info.ready)acts.append(action(vendor==='grok'?'调起授权登录':'打开终端授权',()=>store.startAuthLogin(vendor),'cs-primary',`login-${vendor}`));
  acts.append(action(vendor==='codex'?'检查本机授权':'在线验证',()=>store.verifyAuth(vendor),'',`verify-inline-${vendor}`));
  acts.append(action('刷新状态',()=>store.refreshAuthStatus(),'',`refresh-${vendor}`));
  bar.append(acts);
  return bar;
 }

 function engineSection(){
  const cfg=state().apiConfig,p=cfg.activeProvider,meta=PROVIDER_META[p],pc=cfg.providers[p];
  const cfgBtn=action(isAuthProvider(p)?'授权配置':'配置 Key',()=>{
   recordStudioOriginIfLocal();
   settingsHub=isAuthProvider(p)?'subscription':'api';
   settingsModality='image';
   settingsProvider=p;
   ctx.navigate?.('api-settings',isAuthProvider(p)?{hub:'subscription'}:{hub:'api',tab:'image'});
  },'cs-ghost');
  const sec=section('2. 生图引擎与参数',{actions:cfgBtn});
  const grid=el('div','cs-grid2');
  grid.append(field('接口协议',select(PROVIDER_ORDER.map(id=>[id,`${PROVIDER_META[id].name} · ${providerStatusText(id)}`]),p,v=>{store.updateApiConfig({activeProvider:v});if(isAuthProvider(v))store.refreshAuthStatus();},{label:'接口协议'})));
  grid.append(field('画风预设',select(Object.entries(STYLE_PRESETS).map(([k,v])=>[k,v.label]),cfg.stylePreset,v=>store.updateApiConfig({stylePreset:v}),{label:'画风预设'})));
  grid.append(field('模型 ID',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>store.updateProviderConfig(p,{model:v}),{label:'模型 ID'})));
  if(pc.model==='custom'){
   const input=el('input');input.value=pc.customModel;input.placeholder='输入模型 ID';input.dataset.focusKey='custom-model';
   input.onchange=()=>store.updateProviderConfig(p,{customModel:input.value});
   grid.append(field('自定义模型 ID',input));
  }
  sec.body.append(grid);
  const planned=describePlannedGeneration(cfg,state().recipe);
  const routeNote=el('p','cs-active-route');
  routeNote.append(el('span','','当前调用：'),el('code','cs-history-model',planned.model||'待填写自定义模型'),el('span','cs-history-method',planned.methodLabel||planned.providerShort));
  sec.body.append(routeNote);
  if(isAuthProvider(p))sec.body.append(authInlineBanner(p));
  else if(!store.isProviderCredentialReady(p,pc)){
   const warnText=meta.supportsDualAuth&&(pc.authMode||'aksk')!=='apikey'
    ?`尚未完整配置 ${meta.name} 的 Access Key 与 Secret Key，请点击右上角「配置 Key」。`
    :`尚未配置 ${meta.name} 的 API Key，请点击右上角「配置 Key」。`;
   sec.body.append(el('p','cs-warn',warnText));
  }
  const more=el('details','cs-more');more.append(el('summary','','更多参数'),providerParams());
  sec.body.append(more);
  return sec.node;
 }

 function promptSection(){
  const s=state(),prompt=store.currentPrompt();
  const sec=section('3. 提示词 (Prompt)',{actions:(()=>{const a=el('div','cs-row-actions');a.append(action('重置',()=>{store.setCustomPrompt(null);notice('已恢复自动组装的提示词');}),action('复制',async()=>{await navigator.clipboard?.writeText(store.currentPrompt());notice('已复制');}));return a;})()});
  const area=el('textarea','cs-prompt');area.value=prompt;area.dataset.focusKey='prompt';area.setAttribute('aria-label','提示词');
  area.oninput=()=>store.setCustomPrompt(area.value);
  sec.body.append(area);
  if(s.customPrompt!=null)sec.body.append(el('small','cs-field-hint','已手动修改提示词；更换参考图后可点「重置」重新组装。'));
  const count=store.recipeCount(s.recipe);
  const gen=action(s.isGenerating?'生成中…':`生成角色图${count?` (${count} 张参考)`:''}`,()=>{
   const cur=state().apiConfig,pid=cur.activeProvider,customInput=root.querySelector?.('[data-focus-key="custom-model"]');
   if(customInput&&cur.providers[pid]?.model==='custom'&&customInput.value!==cur.providers[pid]?.customModel){
    store.updateProviderConfig(pid,{customModel:customInput.value});
   }
   return store.startGeneration();
  },'cs-primary cs-generate');
  gen.disabled=s.isGenerating||Boolean(s.publicationTask)||!s.hydrated;
  sec.body.append(gen);
  return sec.node;
 }

 function resultSection(){
  const s=state(),totalCount=s.historyLoaded?s.historyOverallTotal:s.history.length;
  const sec=section('本次生成结果',{actions:action(`AI角色合成库 (${totalCount})`,()=>ctx.navigate?.('asset-center',{tab:'official',kind:'composite'}),'cs-ghost')});
  sec.body.append(el('small','cs-field-hint','生成图片与提示词按日期存于 assets/ai-generate-image/ 并写入数据库；入库位置：官方资产 · 人设。'));
  progressNode=el('div','cs-progress');updateProgress();
  sec.body.append(progressNode);
  errorNode=el('pre','cs-error-box');errorNode.hidden=!s.generationError;errorNode.textContent=s.generationError||'';sec.body.append(errorNode);
  const stage=el('div','cs-result');
  if(s.previewUrl){
   const result=s.currentResult,receipt=result?.publication?.officialReceipt;
   if(s.isGenerating)stage.append(el('p','cs-result-note','上次生成结果 · 正在生成新图片'));
   const btn=el('button','cs-result-img');btn.type='button';btn.setAttribute('aria-label','放大生成结果');
   const img=el('img');img.src=s.previewUrl;img.alt='生成结果';btn.append(img);btn.onclick=()=>zoom(s.previewUrl,'生成结果');
   stage.append(btn);
   if(result){
    const info=resolveRecordProvenance(result),prov=el('div','cs-result-provenance');
    prov.append(el('code','cs-history-model',info.model||'未记录模型'),el('span','cs-history-method',info.methodLabel||info.providerShort));
    stage.append(prov);
   }
   const acts=el('div','cs-row-actions cs-result-actions');acts.setAttribute('aria-label','生成结果操作');
   const remove=action('删除',async()=>{if(result&&confirm('从数据库删除本次生成结果及对应的本地图片与提示词文件？此操作无法撤销，不影响已发布的官方资产和项目引用。'))await store.deleteCurrentResult(result.id);},'cs-danger','result-delete');
   const phase=s.publicationTask&&s.publicationTask.resultId===result?.id?s.publicationTask.phase:'';
   const labels={checking:'检查权限中…',uploading:'上传图片中…',importing:'保存共享库中…',publishing:'发布官方资产中…'};
   const publish=action(receipt?'已入官方资产库':labels[phase]||'放入官方资产库',()=>{const epoch=viewEpoch;return result&&openCharacterPublication(result,ctx,store,{isActive:()=>!disposed&&mode==='studio'&&epoch===viewEpoch&&state().currentResult?.id===result.id,restoreFocus:()=>{if(!disposed&&epoch===viewEpoch)root.querySelector('[data-focus-key="result-publish"]')?.focus({preventScroll:true});}});},'cs-primary','result-publish');
   const save=action('下载',()=>download(result?.imageUrl||s.previewUrl,`character-${result?.id||Date.now()}.${imageExtension(result?.imageUrl||s.previewUrl)}`),'','result-download');
   remove.disabled=!result||s.isGenerating||Boolean(s.publicationTask)||busy.has('result-delete');
   publish.disabled=!result||s.isGenerating||Boolean(s.publicationTask)||Boolean(receipt)||busy.has('result-publish');
   if(phase)publish.setAttribute('aria-busy','true');
   save.disabled=s.isGenerating;
   remove.dataset.focusKey='result-delete';publish.dataset.focusKey='result-publish';save.dataset.focusKey='result-download';
   acts.append(remove,publish,save);stage.append(acts);
   if(receipt){const link=el('a','cs-link cs-result-official','查看官方资产');link.href='?page=asset-center&tab=official&kind=character&entry='+encodeURIComponent(receipt.entry_id);link.onclick=event=>{event.preventDefault();ctx.navigate?.('asset-center',officialResultRoute(receipt));};stage.append(link);}
   if(result?.publication?.recoveryError)stage.append(el('p','cs-warn',result.publication.recoveryError));
   if(s.resultError&&s.resultErrorId===result?.id){const feedback=el('p','cs-result-feedback',s.resultError);feedback.setAttribute('role','status');stage.append(feedback);}
  }else stage.append(el('p','cs-empty','生成后在此查看本次结果；历史图片请到「AI角色合成库」。'));
  sec.body.append(stage);
  return sec.node;
 }
 let pixaiRecoveryId='';
 function pixaiTaskSection(){
  const task=state().pixaiTask;
  if(!task)return null;
  const sec=section('待确认 PixAI 任务');
  const id=task.task?.taskId;
  sec.body.append(el('p','cs-field-hint',id?`任务 ${id}：刷新后只查询原任务，不重复提交。`:'提交结果未知或提交前被中断。请核对 PixAI 任务后再按编号恢复，不会自动重试提交。'));
  if(!id){
   const row=el('div','cs-url-row'),input=el('input');
   input.value=pixaiRecoveryId;input.placeholder='已确认的 PixAI 任务编号';input.setAttribute('aria-label','PixAI 任务编号');
   input.oninput=()=>{pixaiRecoveryId=input.value;};
   row.append(input,action('按编号恢复',()=>store.recoverPixAiTask(pixaiRecoveryId),'', 'pixai-recover'));
   sec.body.append(row);
  }
  const acts=el('div','cs-row-actions');
  const resume=action('恢复跟踪',()=>store.resumePixAiTracking(),'cs-primary','pixai-resume');
  const pause=action('暂停跟踪',()=>store.pausePixAiTracking(),'','pixai-pause');
  const drop=action('放弃记录',()=>{if(confirm('放弃本地恢复记录？这不会取消服务器任务，重新生成可能再次扣除额度。'))return store.abandonPixAiTask();},'','pixai-abandon');
  resume.disabled=state().isGenerating||!id;
  pause.disabled=!state().isGenerating;
  drop.disabled=state().isGenerating;
  acts.append(resume,pause,drop);sec.body.append(acts);
  return sec.node;
 }
 function updateProgress(){
  if(!progressNode)return;
  const s=state(),p=s.generationProgress;
  progressNode.hidden=!s.isGenerating;
  progressNode.replaceChildren();
  if(!s.isGenerating)return;
  progressNode.append(el('span','cs-progress-text',p?.message||`正在调用 ${PROVIDER_META[s.generatingModel]?.name||s.generatingModel||'接口'}…`));
  const bar=el('div','cs-bar is-indeterminate');bar.append(el('span'));
  progressNode.append(bar);
 }

 function studioView(){
  const s=state(),page=el('div','cs-page');
  const head=el('header','cs-page-head');
  const title=el('div','cs-title');title.append(el('h1','','AI 角色合成台'),el('p','','从人像颜值库、服装穿搭库、动作姿势库挑选参考，通过 AGY / Grok 授权登录或主流云端 API 组合生成角色图。'));
  const acts=el('div','cs-row-actions');
  acts.append(action('随机',()=>store.randomizeAll(),'','random-all'),action('清空',()=>store.clearRecipe()),
   action(s.safeMode?'安全模式 · 开':'安全模式 · 关',()=>store.toggleSafeMode(),s.safeMode?'':'cs-danger'),
   action('API 接口配置',()=>{recordStudioOriginIfLocal();ctx.navigate?.('api-settings');},'cs-ghost'));
  head.append(title,acts);page.append(head);
  const cols=el('div','cs-columns'),left=el('div','cs-col'),right=el('div','cs-col');
  const stitch=action('查看拼图',async()=>{const url=await store.refreshStitchPreview();if(url)stitchDialog(url);},'','stitch');
  if(s.apiConfig.activeProvider==='pixai')stitch.hidden=true;
  const refs=section('1. 参考图组合',{actions:stitch});
  const slots=el('div','cs-slots');for(const slot of ['portrait','costume','pose'])slots.append(slotCard(slot));
  refs.body.append(slots,extraImages());
  left.append(refs.node,engineSection(),promptSection());
  const pending=pixaiTaskSection();if(pending)right.append(pending);
  right.append(resultSection());
  cols.append(left,right);page.append(cols);
  return page;
 }

 // ------------------------------------------------------------------ Unified Model Hub (?page=api-settings)
 function syncSettingsRoute(){
  ctx.onHubTab?.(settingsHub,settingsModality,settingsRoutesSection);
  if(typeof window==='undefined'||typeof location==='undefined')return;
  const onSettings=location.pathname==='/api-settings'||String(location.search||'').includes('page=api-settings');
  if(!onSettings)return;
  const route=new URLSearchParams(location.search);
  if(location.pathname!=='/api-settings')route.set('page','api-settings');
  route.set('hub',settingsHub);
  if(settingsHub==='api'){
   route.set('tab',settingsModality);
   if(settingsModality==='routes'&&settingsRoutesSection!=='models')route.set('section',settingsRoutesSection);
   else route.delete('section');
  }else{
   route.delete('tab');
   route.delete('section');
  }
  const next=(location.pathname==='/api-settings'?'/api-settings?':'?')+route;
  const cur=(location.pathname==='/api-settings'?location.pathname:'')+location.search;
  if(cur!==next)window.history?.replaceState?.(null,'',next);
 }

 function modeSwitchBar(group,pid,{metaMap=PROVIDER_META,isAuthFn=isAuthProvider,statusFn=providerStatusText,onPick}={}){
  if(group.modes.length<2)return null;
  const wrap=el('div','cs-mode-switch');wrap.setAttribute('role','group');wrap.setAttribute('aria-label',`${group.name} 接入方式`);
  for(const mid of group.modes){
   const m=metaMap[mid],active=pid===mid;
   const btn=el('button','cs-mode-btn'+(active?' is-active':''));btn.type='button';btn.setAttribute('aria-pressed',String(active));
   btn.dataset.modeId=mid;
   btn.dataset.focusKey=`set-mode-${mid}`;
   const head=el('div','cs-mode-btn-head');
   head.append(el('strong','',m.modeLabel),el('span','cs-mode-pill '+(isAuthFn(mid)?'is-oauth':'is-apikey'),statusFn(mid)));
   btn.append(head,el('small','',m.modeHint));
   btn.onclick=()=>onPick(mid);
   wrap.append(btn);
  }
  return wrap;
 }

 function canVerifySubscription(){
  const sess=ctx.session?.()||{};
  const offline=typeof navigator!=='undefined'&&navigator.onLine===false;
  return !offline&&Boolean(sess.csrf||sess.actor);
 }

 function authSettingsCard(vendor,{loginLabel,verifyLabel,defaultCommand,fallbackMessage='',waitingMessage='等待授权完成并自动刷新…',keyPrefix=''}={}){
  const s=state(),info=s.authStatus[vendor]||{};
  const allowVerify=canVerifySubscription();
  const card=el('div','cs-auth-card '+(info.ready?'is-ok':['expired','cli_missing','check_failed'].includes(info.status)?'is-error':''));
  const statusHead=el('div','cs-auth-head');
  statusHead.append(el('span','cs-conn-badge',store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录')));
  if(info.account)statusHead.append(el('span','cs-auth-account',`账号 ${info.account}`));
  if(s.authPolling===vendor)statusHead.append(el('span','cs-auth-polling',waitingMessage));
  card.append(statusHead,el('p','cs-auth-msg',info.message||fallbackMessage));
  const acts=el('div','cs-row-actions');
  const loginBtn=action(loginLabel,()=>store.startAuthLogin(vendor),'cs-primary',`${keyPrefix}auth-login-${vendor}`);
  const verifyBtn=action(verifyLabel,()=>store.verifyAuth(vendor),'',`${keyPrefix}auth-verify-${vendor}`);
  const refreshBtn=action('刷新授权状态',()=>store.refreshAuthStatus(),'',`${keyPrefix}auth-refresh-${vendor}`);
  if(!allowVerify){loginBtn.disabled=true;verifyBtn.disabled=true;refreshBtn.disabled=true;}
  acts.append(loginBtn,verifyBtn,refreshBtn);
  const cmdText=info.login_command||defaultCommand;
  acts.append(action(`复制命令：${cmdText}`,async()=>{
   try{
    if(!globalThis.navigator?.clipboard?.writeText)throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(cmdText);notice(`已复制终端命令：${cmdText}`);
   }catch{notice('复制失败，请手动复制下方命令');}
  },'',`${keyPrefix}auth-copy-${vendor}`));
  card.append(acts);
  const cmdRow=el('div','cs-cmd-box');cmdRow.append(el('span','cs-cmd-label','终端授权命令'),el('code','',`$ ${cmdText}`));
  card.append(cmdRow);
  return card;
 }

 function authSettingsBody(pid,{isVideo=false}={}){
  const s=state(),meta=(isVideo?VIDEO_PROVIDER_META:PROVIDER_META)[pid];
  const pc=(isVideo?s.apiConfig.videoProviders:s.apiConfig.providers)[pid];
  const updateFn=isVideo?store.updateVideoProviderConfig:store.updateProviderConfig;
  const vendor=meta.authVendor,wrap=el('div','cs-auth-panel');
  wrap.append(authSettingsCard(vendor,{
   loginLabel:vendor==='codex'?'打开终端完成 Codex 授权':vendor==='grok'?'调起浏览器授权登录':'打开终端完成 AGY 授权',
   verifyLabel:vendor==='codex'?'检查本机授权':vendor==='grok'?'在线验证授权 (grok models)':'在线验证授权 (agy models)',
   defaultCommand:vendor==='codex'?'codex login':vendor==='grok'?'grok login --oauth':'agy',
  }));

  wrap.append(field(isVideo?'默认视频模型':'默认模型 / 引擎',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>updateFn(pid,{model:v}))));
  if(pc.model==='custom'){
   const custom=el('input');custom.value=pc.customModel;custom.placeholder=isVideo?'输入视频模型 ID':'输入协调模型 ID（留空则使用默认模型）';custom.dataset.focusKey=isVideo?'set-video-custom':'set-custom';
   custom.onchange=()=>updateFn(pid,{customModel:custom.value});
   wrap.append(field('自定义模型 ID',custom));
  }
  const note=vendor==='codex'
   ?'使用本机 Codex CLI 的 ChatGPT 订阅登录，通过内置生图工具生成图片并计入 Codex 订阅用量。无需 API Key，与「GPT Image API 接口」独立，不自动混用或回退。'
   :vendor==='grok'
   ?(isVideo
     ?'凭证边界：本模式复用本机 ~/.grok/auth.json 中的 Grok CLI 订阅登录态调用 Imagine 视频接口（服务端不回显、不落盘任何密钥），与「Grok API 接口」按量计费 Key 严格分开识别，不自动混用或回退。'
     :'凭证边界：本模式复用本机 ~/.grok/auth.json 中的 grok CLI 登录态，支持调用终端 grok 内置 image_edit 或直连 Imagine 订阅接口（服务端不回显、不落盘任何密钥，子进程严格剥离 XAI_API_KEY），与「Grok API 接口」按量计费 Key 严格分开识别，不自动混用或回退。')
   :'凭证边界：本模式复用本机 Antigravity CLI (~/.gemini/antigravity-cli) 登录态，通过内置 image-generator 子智能体生成角色图；服务端不读取或传输任何令牌明文。';
  wrap.append(el('p','cs-field-hint',note));
  return wrap;
 }

 function klingSettingsBody(pid,{isVideo=false}={}){
  const cfg=state().apiConfig,meta=(isVideo?VIDEO_PROVIDER_META:PROVIDER_META)[pid];
  const pc=(isVideo?cfg.videoProviders:cfg.providers)[pid]||{};
  const updateFn=isVideo?store.updateVideoProviderConfig:store.updateProviderConfig;
  const visible=isVideo?showVideoKey:showKey;
  const authMode=(pc.authMode||'aksk')==='apikey'?'apikey':'aksk';
  const ready=store.isProviderCredentialReady(pid,pc);
  const wrap=el('div','cs-apikey-panel cs-kling-panel');

  const modeRow=el('div','cs-kling-mode-row');
  const authSeg=el('div','cs-kling-auth-seg');
  authSeg.setAttribute('role','tablist');
  authSeg.setAttribute('aria-label','快手可灵鉴权模式');
  for(const [mId,mLabel] of [['aksk','官方 AK/SK 鉴权 (JWT)'],['apikey','兼容 API Key 鉴权']]){
   const active=authMode===mId;
   const b=el('button','cs-kling-auth-btn'+(active?' is-active':''),mLabel);
   b.type='button';
   b.dataset.klingAuth=mId;
   b.setAttribute('role','tab');
   b.setAttribute('aria-selected',String(active));
   bindClick(b,()=>updateFn(pid,{authMode:mId}));
   authSeg.append(b);
  }
  modeRow.append(authSeg,el('span','cs-security-pill','🔒 仅保存在当前浏览器 localStorage · 绝不上传 PostgreSQL 数据库'));
  wrap.append(modeRow);

  if(!ready&&!(authMode==='aksk'&&(pc.accessKey?.trim()||pc.secretKey?.trim()))){
   wrap.append(el('p','cs-field-hint','尚未配置快手可灵凭证。请选择「官方 AK/SK 鉴权 (JWT)」或「兼容 API Key 鉴权」，填入密钥并保存至当前浏览器。'));
  }

  if(authMode==='aksk'){
   const akWrap=el('div','cs-key'),ak=el('input');
   ak.type=visible?'text':'password';ak.name='kling_access_key';ak.value=pc.accessKey||'';ak.autocomplete='off';ak.spellcheck=false;
   ak.placeholder='输入可灵开放平台 Access Key (AK)…';
   ak.dataset.focusKey=isVideo?'set-video-ak':'set-ak';
   ak.onchange=()=>updateFn(pid,{accessKey:ak.value.trim()});
   const eyeAk=el('button','cs-icon-btn',visible?'隐藏':'显示');eyeAk.type='button';eyeAk.setAttribute('aria-label','显示或隐藏密钥内容');
   eyeAk.onclick=()=>{if(isVideo)showVideoKey=!showVideoKey;else showKey=!showKey;render(true);};
   akWrap.append(ak,eyeAk);
   wrap.append(field('Access Key (AK)',akWrap,'JWT iss 签发方标识；客户端使用原生 WebCrypto 内存签发短期 HS256 JWT，永不持久化 JWT。'));

   const skWrap=el('div','cs-key'),sk=el('input');
   sk.type=visible?'text':'password';sk.name='kling_secret_key';sk.value=pc.secretKey||'';sk.autocomplete='off';sk.spellcheck=false;
   sk.placeholder='输入可灵开放平台 Secret Key (SK)…';
   sk.dataset.focusKey=isVideo?'set-video-sk':'set-sk';
   sk.onchange=()=>updateFn(pid,{secretKey:sk.value.trim()});
   const eyeSk=el('button','cs-icon-btn',visible?'隐藏':'显示');eyeSk.type='button';eyeSk.setAttribute('aria-label','显示或隐藏密钥内容');
   eyeSk.onclick=()=>{if(isVideo)showVideoKey=!showVideoKey;else showKey=!showKey;render(true);};
   skWrap.append(sk,eyeSk);
   wrap.append(field('Secret Key (SK)',skWrap,'用于本地内存 HMAC-SHA256 签名，仅保存在当前浏览器 localStorage。'));

   if((pc.accessKey?.trim()&&!pc.secretKey?.trim())||(!pc.accessKey?.trim()&&pc.secretKey?.trim())){
    wrap.append(el('p','cs-field-error','官方 AK/SK 鉴权需同时填写 Access Key 与 Secret Key 才能签发 HS256 JWT。'));
   }
  }else{
   const keyWrap=el('div','cs-key'),key=el('input');
   key.type=visible?'text':'password';key.name='kling_api_key';key.value=pc.apiKey||'';key.autocomplete='off';key.spellcheck=false;
   key.placeholder=meta.keyPlaceholder||'输入兼容平台单令牌 API Key…';
   key.dataset.focusKey=isVideo?'set-video-key':'set-key';
   key.onchange=()=>updateFn(pid,{apiKey:key.value.trim()});
   const eye=el('button','cs-icon-btn',visible?'隐藏':'显示');eye.type='button';eye.setAttribute('aria-label','显示或隐藏密钥内容');
   eye.onclick=()=>{if(isVideo)showVideoKey=!showVideoKey;else showKey=!showKey;render(true);};
   keyWrap.append(key,eye);
   wrap.append(field('兼容单 API Key（Bearer 直传）',keyWrap,'仅保存在当前浏览器 localStorage；清除浏览器数据会一并删除。'));
  }

  const base=el('input');base.type='url';base.name='kling_base_url';base.value=pc.baseUrl||meta.defaultBaseUrl;base.placeholder=meta.defaultBaseUrl;
  base.dataset.focusKey=isVideo?'set-video-base':'set-base';
  base.onchange=()=>updateFn(pid,{baseUrl:base.value.trim()||meta.defaultBaseUrl});
  wrap.append(field('官方接口端点 (Base URL)',base,'默认北京区 https://api-beijing.klingai.com；国际区可选 https://api.klingai.com。'));

  wrap.append(field(isVideo?'默认可灵视频模型':'默认可灵生图模型',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>updateFn(pid,{model:v}))));
  if(pc.model==='custom'){
   const custom=el('input');custom.value=pc.customModel||'';custom.placeholder=isVideo?'输入自定义可灵视频模型 ID':'输入自定义可灵生图模型 ID';
   custom.dataset.focusKey=isVideo?'set-video-custom':'set-custom';
   custom.onchange=()=>updateFn(pid,{customModel:custom.value.trim()});
   wrap.append(field('自定义模型 ID',custom));
  }

  const provBar=el('div','cs-provenance-bar');
  const provCopy=el('span','');
  provCopy.append(el('span','','调用溯源预览：'),el('code','',isVideo?'Kling Video API · /v1/videos/image2video':'Kling API · /v1/images/generations'));
  provBar.append(provCopy,el('small','','已开启纯 Base64 自动净化与 /api/proxy 双层安全代理转发'));
  wrap.append(provBar);
  return wrap;
 }

 function apiKeySettingsBody(pid,{isVideo=false}={}){
  if(pid==='kling'||pid==='kling_video')return klingSettingsBody(pid,{isVideo});
  const cfg=state().apiConfig,meta=(isVideo?VIDEO_PROVIDER_META:PROVIDER_META)[pid];
  const pc=(isVideo?cfg.videoProviders:cfg.providers)[pid];
  const updateFn=isVideo?store.updateVideoProviderConfig:store.updateProviderConfig;
  const visible=isVideo?showVideoKey:showKey;
  const wrap=el('div','cs-apikey-panel');
  const base=el('input');base.type='url';base.value=pid==='pixai'?meta.defaultBaseUrl:pc.baseUrl;base.placeholder=meta.defaultBaseUrl;base.dataset.focusKey=isVideo?'set-video-base':'set-base';
  base.disabled=pid==='pixai';
  base.onchange=()=>{if(pid!=='pixai')updateFn(pid,{baseUrl:base.value});};
  const baseHint=pid==='pixai'
   ?'首版只使用官方地址 https://api.pixai.art。Key 会经本站代理发往 PixAI，请在可信部署上使用。'
   :(pid==='grok'||pid==='grok_video')
   ?'xAI 官方端点默认 https://api.x.ai/v1；建议开启下方服务端 CORS 代理避免跨域拦截。'
   :(pid==='gemini'||pid==='gemini_video')
   ?'Google AI Studio 官方端点默认 https://generativelanguage.googleapis.com。'
   :pid==='doubao_video'
   ?'火山方舟默认端点 https://ark.cn-beijing.volces.com（工作区自动化任务亦支持 ~/.zshenv 中的 ARK_AGENT_PLAN_API_KEY）。'
   :undefined;
  wrap.append(field('Base URL',base,baseHint));
  const keyWrap=el('div','cs-key'),key=el('input');key.type=visible?'text':'password';key.value=pc.apiKey;key.autocomplete='off';key.dataset.focusKey=isVideo?'set-video-key':'set-key';
  key.placeholder=meta.keyPlaceholder||'输入 API Key（仅保存在本地浏览器）';
  key.onchange=()=>updateFn(pid,{apiKey:key.value.trim()});
  const eye=el('button','cs-icon-btn',visible?'隐藏':'显示');eye.type='button';eye.setAttribute('aria-label',visible?'隐藏 API Key':'显示 API Key');
  eye.onclick=()=>{if(isVideo)showVideoKey=!showVideoKey;else showKey=!showKey;render(true);};
  keyWrap.append(key,eye);
  const keyHint=(pid==='grok'||pid==='grok_video')
   ?'保存于浏览器 localStorage，与本机 ~/.grok/auth.json 订阅登录严格隔离。'
   :'Key 仅保存在当前浏览器 localStorage；清除浏览器数据会一并删除，请勿在共享电脑上保存。';
  wrap.append(field('API Key',keyWrap,keyHint));
  wrap.append(field(isVideo?'默认视频模型 ID':'默认模型 ID',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>updateFn(pid,{model:v}))));
  if(pc.model==='custom'){
   const custom=el('input');custom.value=pc.customModel;custom.placeholder=(pid==='doubao'||pid==='doubao_video')?'ep-2026xxxx 或模型 ID':'输入模型 ID';custom.dataset.focusKey=isVideo?'set-video-custom':'set-custom';
   custom.onchange=()=>updateFn(pid,{customModel:custom.value});
   wrap.append(field('自定义模型 ID',custom));
  }
  return wrap;
 }

 function flushPanelInputs(container){
  for(const input of container.querySelectorAll('input')){
   if(typeof input.onchange==='function')input.onchange();
  }
 }

 function imageSettingsPanel(panel){
  const cfg=state().apiConfig;
  const pid=PROVIDER_META[settingsProvider]?settingsProvider:cfg.activeProvider;
  const group=groupForProvider(pid),meta=PROVIDER_META[pid],pc=cfg.providers[pid]||{};

  const tabs=el('div','cs-provider-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','生图服务商');
  for(const g of SETTINGS_GROUPS){
   const selected=g.id===group.id,summary=groupSummary(g);
   const b=el('button','cs-provider-tab');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(selected));
   b.dataset.groupId=g.id;
   const text=el('span','cs-provider-text');text.append(el('strong','',g.name),el('small','',summary.label));
   const dot=el('span','cs-dot'+(summary.tone?' '+summary.tone:''));dot.title=summary.label;
   b.append(text,dot);
   bindClick(b,()=>{
    const nextPid=g.modes.includes(cfg.activeProvider)?cfg.activeProvider:g.modes[0];
    settingsProvider=nextPid;
    store.updateApiConfig({activeProvider:nextPid});
    if(isAuthProvider(nextPid))store.refreshAuthStatus();
   });
   tabs.append(b);
  }
  panel.append(tabs);

  const acts=el('div','cs-row-actions');
  const doc=el('a','cs-link','文档');doc.href=meta.docUrl;doc.target='_blank';doc.rel='noreferrer';acts.append(doc);
  if(!isAuthProvider(pid)){
   const peerVid=IMAGE_VIDEO_KEY_PEERS[pid],peerCfg=peerVid?cfg.videoProviders?.[peerVid]:null;
   if(meta.supportsDualAuth){
    const readyNow=store.isProviderCredentialReady(pid,pc);
    const partialAk=(pc.authMode||'aksk')==='aksk'&&((pc.accessKey?.trim()&&!pc.secretKey?.trim())||(!pc.accessKey?.trim()&&pc.secretKey?.trim()));
    acts.append(el('span','cs-status-chip '+(readyNow?'is-ready':'is-warn'),readyNow?'✓ 已配置（存当前浏览器）':partialAk?'⚠ 待补全 Secret Key':'⚠ 待填写凭证'));
    const peerReady=Boolean(peerVid&&store.isProviderCredentialReady(peerVid,peerCfg));
    const reuseBtn=action('复用「视频」同厂商凭证',()=>{
     store.updateProviderConfig(pid,{
      authMode:peerCfg.authMode==='apikey'?'apikey':'aksk',
      accessKey:peerCfg.accessKey||'',
      secretKey:peerCfg.secretKey||'',
      apiKey:peerCfg.apiKey||'',
     });
     notice('已从视频配置复用可灵凭证');
    });
    reuseBtn.id='kling-reuse-btn';
    reuseBtn.disabled=!peerReady;
    if(!peerReady)reuseBtn.title='视频接口尚未保存快手可灵凭证，先在一侧保存后即可一键双向复用';
    acts.append(reuseBtn);
   }else{
    const peerKey=peerCfg?.apiKey?.trim()||'';
    if(peerKey&&peerKey!==pc.apiKey?.trim()){
     acts.append(action('复用「视频」同厂商 Key',()=>{store.updateProviderConfig(pid,{apiKey:peerKey});notice(`已从视频配置复用 ${meta.shortName} Key`);}));
    }
   }
   acts.append(action('恢复默认',()=>{store.updateProviderConfig(pid,{baseUrl:meta.defaultBaseUrl,model:meta.models[0].value});notice('已恢复生图默认端点与模型');}));
  }
  const sec=section(`${group.name} · 生图接入配置`,{actions:acts});
  if(pid==='kling'){sec.node.dataset.component='kling-provider-card';sec.node.setAttribute('data-component','kling-provider-card');}
  const modeBar=modeSwitchBar(group,pid,{
   metaMap:PROVIDER_META,isAuthFn:isAuthProvider,statusFn:providerStatusText,
   onPick:mid=>{settingsProvider=mid;store.updateApiConfig({activeProvider:mid});if(isAuthProvider(mid))store.refreshAuthStatus();},
  });
  if(modeBar)sec.body.append(modeBar);
  sec.body.append(isAuthProvider(pid)?authSettingsBody(pid,{isVideo:false}):apiKeySettingsBody(pid,{isVideo:false}));
  panel.append(sec.node);

  if(!isAuthProvider(pid)){
   const g=section('生图全局请求选项');
   if(pid==='pixai')g.body.append(el('p','cs-field-hint','PixAI 按人像、服装、姿势的原始图片上传，不使用 URL / Base64 传参，也不发送拼图。'));
   else g.body.append(field('参考图传参方式',select([['url','传递图片 URL（免上传文件，Gemini 原生、Grok 编辑与快手可灵自动净化 Base64）'],['base64','统一转 Base64 编码传输']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))));
   g.body.append(
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用（解决跨域限制）':'已关闭（浏览器直连）'),'切换到 Grok API、阿里云百炼 (Qwen)、火山方舟 (Doubao)、PixAI 或快手可灵 (Kling) 时会自动启用；仅转发白名单 HTTPS 官方域名。'),
   );
   panel.append(g.node);
  }
  const foot=el('div','cs-row-actions cs-end');
  if(pid==='kling'){
   foot.append(action('前往配置后台 ~/.zshenv 生产路由',()=>{settingsHub='api';settingsModality='routes';syncSettingsRoute();render(true);}));
  }
  foot.append(action('保存配置',()=>{flushPanelInputs(panel);notice('生图接口配置已保存');},'cs-primary'));
  panel.append(foot);
 }

 function videoSettingsPanel(panel){
  const cfg=state().apiConfig;
  const pid=VIDEO_PROVIDER_META[settingsVideoProvider]?settingsVideoProvider:cfg.activeVideoProvider;
  const group=groupForVideoProvider(pid),meta=VIDEO_PROVIDER_META[pid],pc=cfg.videoProviders?.[pid]||{};
  const vd=cfg.videoDefaults||{mode:'image_to_video',aspectRatio:'16:9',resolution:'720p',durationSec:'5',generateAudio:true};

  const tabs=el('div','cs-provider-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','视频服务商');
  for(const g of VIDEO_SETTINGS_GROUPS){
   const selected=g.id===group.id,summary=videoGroupSummary(g);
   const b=el('button','cs-provider-tab');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(selected));
   b.dataset.groupId=g.id;
   const text=el('span','cs-provider-text');text.append(el('strong','',g.name),el('small','',summary.label));
   const dot=el('span','cs-dot'+(summary.tone?' '+summary.tone:''));dot.title=summary.label;
   b.append(text,dot);
   bindClick(b,()=>{
    const nextPid=g.modes.includes(cfg.activeVideoProvider)?cfg.activeVideoProvider:g.modes[0];
    settingsVideoProvider=nextPid;store.updateApiConfig({activeVideoProvider:nextPid});
    if(isVideoAuthProvider(nextPid))store.refreshAuthStatus();
   });
   tabs.append(b);
  }
  panel.append(tabs);

  const acts=el('div','cs-row-actions');
  const doc=el('a','cs-link','文档');doc.href=meta.docUrl;doc.target='_blank';doc.rel='noreferrer';acts.append(doc);
  if(!isVideoAuthProvider(pid)){
   const peerImg=VIDEO_IMAGE_KEY_PEERS[pid],peerCfg=peerImg?cfg.providers?.[peerImg]:null;
   if(meta.supportsDualAuth){
    const readyNow=store.isProviderCredentialReady(pid,pc);
    const partialAk=(pc.authMode||'aksk')==='aksk'&&((pc.accessKey?.trim()&&!pc.secretKey?.trim())||(!pc.accessKey?.trim()&&pc.secretKey?.trim()));
    acts.append(el('span','cs-status-chip '+(readyNow?'is-ready':'is-warn'),readyNow?'✓ 已配置（存当前浏览器）':partialAk?'⚠ 待补全 Secret Key':'⚠ 待填写凭证'));
    const peerReady=Boolean(peerImg&&store.isProviderCredentialReady(peerImg,peerCfg));
    const reuseBtn=action('复用「图」同厂商凭证',()=>{
     store.updateVideoProviderConfig(pid,{
      authMode:peerCfg.authMode==='apikey'?'apikey':'aksk',
      accessKey:peerCfg.accessKey||'',
      secretKey:peerCfg.secretKey||'',
      apiKey:peerCfg.apiKey||'',
     });
     notice('已从生图配置复用可灵凭证');
    });
    reuseBtn.id='kling-reuse-btn';
    reuseBtn.disabled=!peerReady;
    if(!peerReady)reuseBtn.title='生图接口尚未保存快手可灵凭证，先在一侧保存后即可一键双向复用';
    acts.append(reuseBtn);
   }else{
    const peerKey=peerCfg?.apiKey?.trim()||'';
    if(peerKey&&peerKey!==pc.apiKey?.trim()){
     acts.append(action('复用「图」同厂商 Key',()=>{store.updateVideoProviderConfig(pid,{apiKey:peerKey});notice(`已从生图配置复用 ${meta.shortName} Key`);}));
    }
   }
   acts.append(action('恢复默认',()=>{store.updateVideoProviderConfig(pid,{baseUrl:meta.defaultBaseUrl,model:meta.models[0].value});notice('已恢复视频默认端点与模型');}));
  }
  const sec=section(`${group.name} · 视频接入配置`,{actions:acts});
  if(pid==='kling_video'){sec.node.dataset.component='kling-provider-card';sec.node.setAttribute('data-component','kling-provider-card');}
  const modeBar=modeSwitchBar(group,pid,{
   metaMap:VIDEO_PROVIDER_META,isAuthFn:isVideoAuthProvider,statusFn:videoProviderStatusText,
   onPick:mid=>{settingsVideoProvider=mid;store.updateApiConfig({activeVideoProvider:mid});if(isVideoAuthProvider(mid))store.refreshAuthStatus();},
  });
  if(modeBar)sec.body.append(modeBar);
  sec.body.append(isVideoAuthProvider(pid)?authSettingsBody(pid,{isVideo:true}):apiKeySettingsBody(pid,{isVideo:true}));
  panel.append(sec.node);

  const g=section('视频默认参数与请求选项');
  const grid=el('div','cs-grid2');
  grid.append(
   field('默认视频任务模式',select([
    ['image_to_video','图生视频（首帧驱动 · 推荐）'],
    ['first_last_frame','首尾帧过渡控制'],
    ['reference_to_video','多参考图角色一致生成'],
    ['text_to_video','纯文生视频'],
   ],vd.mode,v=>store.updateVideoDefaults({mode:v}),{label:'默认视频任务模式'})),
   field('默认视频画幅',select([
    ['16:9','16:9 横屏影视'],['9:16','9:16 竖屏短剧'],['1:1','1:1 方画幅'],['4:3','4:3'],['3:4','3:4'],['21:9','21:9 宽银幕'],
   ],vd.aspectRatio,v=>store.updateVideoDefaults({aspectRatio:v}),{label:'默认视频画幅'})),
   field('默认输出分辨率',select([
    ['720p','720p 高清（均衡速度与画质 · 推荐）'],['1080p','1080p 全高清成片'],['480p','480p 快速预演样片'],
   ],vd.resolution,v=>store.updateVideoDefaults({resolution:v}),{label:'默认输出分辨率'})),
   field('默认单镜头时长',select([
    ['5','5 秒'],['8','8 秒'],['10','10 秒'],['15','15 秒（Grok 1.5 / Seedance 支持）'],
   ],String(vd.durationSec||'5'),v=>store.updateVideoDefaults({durationSec:v}),{label:'默认单镜头时长'})),
  );
  g.body.append(
   grid,
   field('原生音轨生成',toggle(vd.generateAudio!==false,v=>store.updateVideoDefaults({generateAudio:v}),vd.generateAudio!==false?'开启（支持模型同步生成环境声/音效）':'关闭（仅输出静音画面）')),
  );
  if(!isVideoAuthProvider(pid)){
   g.body.append(
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.videoUseProxy,v=>store.updateApiConfig({videoUseProxy:v}),cfg.videoUseProxy?'已启用（支持异步任务提交与轮询代理）':'已关闭（浏览器直连）'),'切换到 Grok API、通义万相 (Wan)、火山 Seedance 或快手可灵 Video 时自动启用；仅转发白名单 HTTPS 官方域名。'),
   );
  }
  panel.append(g.node);

  const foot=el('div','cs-row-actions cs-end');
  if(pid==='kling_video'){
   foot.append(action('前往配置后台 ~/.zshenv 生产路由',()=>{settingsHub='api';settingsModality='routes';syncSettingsRoute();render(true);}));
  }
  foot.append(action('保存配置',()=>{flushPanelInputs(panel);notice('视频接口配置已保存');},'cs-primary'));
  panel.append(foot);
 }

 function subscriptionHubPanel(stage){
  const s=state(),cfg=s.apiConfig;
  const sess=ctx.session?.()||{};
  const isGuest=!sess.actor&&!sess.csrf;
  const isOffline=typeof navigator!=='undefined'&&navigator.onLine===false;

  if(isGuest){
   const bar=el('div','cs-hub-callout is-info');
   bar.append(el('span','','🔒 当前为只读浏览模式。请先在右上角「个人中心 → 本机操作凭据」验证身份后再执行在线授权校验。'));
   if(ctx.openSession||ctx.account){
    bar.append(action('建立本机操作会话',()=>(ctx.openSession||ctx.account)()));
   }
   stage.append(bar);
  }
  if(isOffline){
   const off=el('div','cs-hub-callout is-warn');
   off.append(el('span','','⚠ 当前网络或本机服务已断开：可查看本地已记忆的默认订阅模型，在线验证授权需恢复连接后执行。'));
   stage.append(off);
  }

  const readyCount=['agy','grok','codex'].filter(v=>Boolean(s.authStatus[v]?.ready)).length;
  const readyBadge=el('span','cs-status-chip '+(readyCount>0?'is-ready':'is-warn'),readyCount>0?`✓ ${readyCount}/3 通道已就绪`:'⚠ 0/3 已登录');
  const sec=section('本机 CLI 订阅授权通道（零明文落盘 · 画布与角色合成台共享）',{actions:readyBadge,cls:'cs-shell-card'});
  sec.node.dataset.component='subscription-auth-grid';
  sec.node.setAttribute('data-component','subscription-auth-grid');
  sec.body.append(el('p','cs-field-hint','直接复用本机终端已完成登录的订阅凭证；服务端仅探测可用状态与公开模型名，绝不向前端回传原始令牌，且与「API 配置」中的按量计费 API Key 严格分开识别、绝不静默回退扣费。'));

  const grid=el('div','cs-sub-grid');

  // 1. Google AGY
  const agyBox=el('article','cs-sub-card');
  agyBox.append(el('h3','','Google AGY 授权登录'),el('small','cs-sub-path','凭证位置：~/.gemini/antigravity-cli'));
  agyBox.append(authSettingsCard('agy',{
   loginLabel:'打开终端完成 AGY 授权',
   verifyLabel:'在线验证授权 (agy models)',
   defaultCommand:'agy',
   fallbackMessage:'复用本机 Antigravity CLI 登录态生成角色设定图，无需填写 API Key。',
   keyPrefix:'hub-',
  }));
  const agyCfg=cfg.providers.agy_auth;
  agyBox.append(field('默认生图订阅模型',select(PROVIDER_META.agy_auth.models.map(m=>[m.value,m.label]),agyCfg.model,v=>store.updateProviderConfig('agy_auth',{model:v}),{key:'hub-agy-model'})));
  if(agyCfg.model==='custom'){
   const c=el('input');c.value=agyCfg.customModel;c.placeholder='指定协调模型 ID';c.dataset.focusKey='hub-agy-custom';
   c.onchange=()=>store.updateProviderConfig('agy_auth',{customModel:c.value});
   agyBox.append(field('自定义协调模型 ID',c));
  }
  grid.append(agyBox);

  // 2. xAI Grok Subscription (Image + Video)
  const grokBox=el('article','cs-sub-card');
  grokBox.append(el('h3','','xAI Grok 订阅授权（生图 + 视频）'),el('small','cs-sub-path','凭证位置：~/.grok/auth.json（与按量 API Key 及 XAI_API_KEY 严格隔离）'));
  grokBox.append(authSettingsCard('grok',{
   loginLabel:'调起浏览器授权登录',
   verifyLabel:'在线验证授权 (grok models)',
   defaultCommand:'grok login --oauth',
   fallbackMessage:'复用本机 grok CLI 登录态调用生图与视频订阅接口；缺失时绝不回退按量 API Key。',
   keyPrefix:'hub-',
  }));
  const grokImgCfg=cfg.providers.grok_auth,grokVidCfg=cfg.videoProviders.grok_video_auth;
  grokBox.append(
   field('默认生图订阅模型',select(PROVIDER_META.grok_auth.models.map(m=>[m.value,m.label]),grokImgCfg.model,v=>store.updateProviderConfig('grok_auth',{model:v}),{key:'hub-grok-img-model'})),
   field('默认视频订阅模型',select(VIDEO_PROVIDER_META.grok_video_auth.models.map(m=>[m.value,m.label]),grokVidCfg.model,v=>store.updateVideoProviderConfig('grok_video_auth',{model:v}),{key:'hub-grok-vid-model'})),
  );
  grid.append(grokBox);

  // 3. OpenAI Codex Subscription
  const codexBox=el('article','cs-sub-card');
  codexBox.append(el('h3','','OpenAI Codex 订阅授权'),el('small','cs-sub-path','终端运行 codex login 绑定 ChatGPT 订阅（与 GPT 按量 API 独立）'));
  codexBox.append(authSettingsCard('codex',{
   loginLabel:'打开终端完成 Codex 授权',
   verifyLabel:'检查本机授权',
   defaultCommand:'codex login',
   fallbackMessage:'复用本机 Codex CLI 的 ChatGPT 订阅配额生图，无需填写 OpenAI API Key。',
   keyPrefix:'hub-',
  }));
  const codexCfg=cfg.providers.codex_auth;
  codexBox.append(field('默认生图订阅模型',select(PROVIDER_META.codex_auth.models.map(m=>[m.value,m.label]),codexCfg.model,v=>store.updateProviderConfig('codex_auth',{model:v}),{key:'hub-codex-model'})));
  grid.append(codexBox);

  sec.body.append(grid);
  stage.append(sec.node);
 }

 function ensureRoutesPanel(){
  if(!routesPanelNode){
   routesPanelNode=el('div','cs-routes-inline-host');
   routesPanelCtrl=mountResourceSettingsPanel(routesPanelNode,{
    api:ctx.api,
    session:ctx.session,
    onNotice:notice,
    openSession:ctx.openSession||ctx.account||(()=>ctx.navigate?.('access',{area:'account'})),
    initialSection:settingsRoutesSection,
    onSectionChange:sec=>{
     settingsRoutesSection=sec;
     syncSettingsRoute();
    },
   });
  }else{
   routesPanelCtrl?.setSection?.(settingsRoutesSection);
  }
  return routesPanelNode;
 }

 function apiHubPanel(stage){
  const toolbar=el('div','cs-api-toolbar');
  toolbar.dataset.component='api-modality-segmented';
  toolbar.setAttribute('data-component','api-modality-segmented');

  const modalityBar=el('div','cs-modality-tabs');
  modalityBar.setAttribute('role','tablist');
  modalityBar.setAttribute('aria-label','API 配置子视图切换');
  const switchModality=nextModality=>{
   if(!['image','video','routes'].includes(nextModality))return;
   settingsHub='api';
   settingsModality=nextModality;
   syncSettingsRoute();
   render(true);
  };
  API_SUBVIEWS.forEach((mod,idx)=>{
   const active=settingsModality===mod.id;
   const tabBtn=el('button','cs-modality-tab'+(active?' is-active':''));
   tabBtn.type='button';
   tabBtn.id=`cs-modality-tab-${mod.id}`;
   tabBtn.dataset.modality=mod.id;
   tabBtn.setAttribute('role','tab');
   tabBtn.setAttribute('aria-selected',String(active));
   tabBtn.setAttribute('aria-controls','cs-modality-panel');
   tabBtn.tabIndex=active?0:-1;
   const copy=el('span','cs-modality-copy');
   copy.append(el('strong','cs-modality-name',mod.label),el('small','cs-modality-desc',mod.subtitle));
   let badge;
   if(mod.id==='routes'){
    badge=el('span','cs-modality-badge is-ready','PostgreSQL');
   }else{
    const readyCount=modalityReadyCount(mod.id),totalCount=mod.id==='image'?SETTINGS_GROUPS.length:VIDEO_SETTINGS_GROUPS.length;
    badge=el('span','cs-modality-badge'+(readyCount>0?' is-ready':''),readyCount>0?`已就绪 ${readyCount}/${totalCount}`:`0/${totalCount} 已配`);
   }
   tabBtn.append(svgIcon(mod.id),copy,badge);
   bindClick(tabBtn,()=>switchModality(mod.id));
   tabBtn.addEventListener('keydown',event=>{
    if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
     event.preventDefault?.();
     const nextIdx=event.key==='ArrowRight'?(idx+1)%API_SUBVIEWS.length:(idx-1+API_SUBVIEWS.length)%API_SUBVIEWS.length;
     const targetMod=API_SUBVIEWS[nextIdx].id;
     switchModality(targetMod);
     root.querySelector(`#cs-modality-tab-${targetMod}`)?.focus?.();
    }
   });
   modalityBar.append(tabBtn);
  });

  const auxLinks=el('div','cs-gov-aux-links');
  auxLinks.setAttribute('aria-label','工作区治理辅助入口');
  auxLinks.append(
   action('角色记忆',()=>{if(ctx.openMemory)return ctx.openMemory();if(ctx.memory)return ctx.memory();document.getElementById?.('role-memory-open')?.click?.();},'cs-aux-btn'),
   action('本机管理凭据',()=>{if(ctx.openSession)return ctx.openSession();if(ctx.account)return ctx.account();const dlg=document.getElementById?.('session-dialog');if(dlg?.showModal)return dlg.showModal();return ctx.navigate?.('access',{area:'account'});},'cs-aux-btn'),
   action('运行与连接诊断',()=>ctx.navigate?.('maintenance'),'cs-aux-btn'),
   action('素材回收站',()=>ctx.navigate?.('trash'),'cs-aux-btn'),
  );
  toolbar.append(modalityBar,auxLinks);
  stage.append(toolbar);

  const panel=el('div','cs-modality-panel');
  panel.id='cs-modality-panel';
  panel.setAttribute('role','tabpanel');
  panel.setAttribute('aria-labelledby',`cs-modality-tab-${settingsModality}`);
  if(settingsModality==='routes'){
   panel.append(ensureRoutesPanel());
  }else if(settingsModality==='video'){
   videoSettingsPanel(panel);
  }else{
   imageSettingsPanel(panel);
  }
  stage.append(panel);
 }

 function settingsView(){
  const page=el('div','cs-page cs-settings');
  page.dataset.component='commercial-shell-container';
  page.setAttribute('data-component','commercial-shell-container');

  // Band 1: Fixed 88px Commercial Header Card
  const head=el('header','commercial-shell-header cs-shell-header');
  head.dataset.component='commercial-shell-header';
  head.setAttribute('data-component','commercial-shell-header');
  const title=el('div','shell-heading-copy');
  title.append(
   el('h1','','API 接口配置'),
   el('p','hint','全项目唯一模型配置中枢：统一管理本机订阅授权、浏览器直连 API（含快手可灵）与生产环境变量路由'),
  );
  const tools=el('div','gov-header-tools');
  const dualBadge=el('span','dual-track-badge','✓ 双轨凭证隔离 · 零明文入库');
  dualBadge.dataset.component='dual-track-security-badge';
  dualBadge.setAttribute('data-component','dual-track-security-badge');
  tools.append(dualBadge,createReturnPill(readHubReturnContext,handleHubReturn,{doc:document}));
  head.append(title,tools);
  page.append(head);

  // Band 2: Persistent 44px Secondary Tab Bar (订阅授权 | API 配置)
  const subnav=el('nav','commercial-shell-subnav cs-hub-subnav');
  subnav.dataset.component='commercial-shell-subnav';
  subnav.setAttribute('data-component','commercial-shell-subnav');
  subnav.setAttribute('role','tablist');
  subnav.setAttribute('aria-label','模型配置中枢主分区');
  const hubTabs=[
   ['subscription','订阅授权'],
   ['api','API 配置'],
  ];
  const switchHub=nextHub=>{
   if(nextHub!=='subscription'&&nextHub!=='api')return;
   settingsHub=nextHub;
   syncSettingsRoute();
   render(true);
  };
  hubTabs.forEach(([hId,hLabel],idx)=>{
   const active=settingsHub===hId;
   const b=el('button','subnav-tab cs-hub-tab'+(active?' is-active':''),hLabel);
   b.type='button';
   b.id=`cs-hub-tab-${hId}`;
   b.dataset.hub=hId;
   b.setAttribute('role','tab');
   b.setAttribute('aria-selected',String(active));
   b.tabIndex=active?0:-1;
   bindClick(b,()=>switchHub(hId));
   b.addEventListener('keydown',event=>{
    if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
     event.preventDefault?.();
     const nextIdx=event.key==='ArrowRight'?(idx+1)%hubTabs.length:(idx-1+hubTabs.length)%hubTabs.length;
     const nextId=hubTabs[nextIdx][0];
     switchHub(nextId);
     root.querySelector(`#cs-hub-tab-${nextId}`)?.focus?.();
    }
   });
   subnav.append(b);
  });
  page.append(subnav);

  // Band 3: Dynamic Zero-Jump Stage
  const stage=el('div','cs-shell-stage');
  stage.dataset.component='commercial-shell-stage';
  stage.setAttribute('data-component','commercial-shell-stage');
  if(settingsHub==='subscription')subscriptionHubPanel(stage);
  else apiHubPanel(stage);
  page.append(stage);
  return page;
 }

 // ------------------------------------------------------------------ render loop
 function signature(){
  const s=state();
  const pixaiTask=s.pixaiTask?`${s.pixaiTask.unknown?'1':'0'}|${s.pixaiTask.paused?'1':'0'}|${s.pixaiTask.task?.taskId||''}`:'';
  return JSON.stringify([mode,settingsHub,settingsModality,settingsRoutesSection,settingsProvider,settingsVideoProvider,showKey,showVideoKey,[...busy],s.recipe,s.apiConfig,s.authStatus,s.authPolling,s.historyOverallTotal,s.historyLoaded,s.history.map(h=>h.id),s.safeMode,s.poseDepthMode,s.customPrompt,s.previewUrl,s.currentResult?.id,s.currentResult?.publication,s.publicationTask,s.resultError,s.isGenerating,s.generationError,s.hydrated,pixaiTask]);
 }
 function render(force=false){
  if(disposed)return;
  const sig=signature();
  if(!force&&sig===renderSig){updateProgress();return;}
  renderSig=sig;
  // Preserve inline production-routes panel edits when unrelated store signals fire.
  if(!force&&mode==='settings'&&settingsHub==='api'&&settingsModality==='routes'&&routesPanelNode&&root.contains?.(routesPanelNode)){
   return;
  }
  const active=document.activeElement,focusKey=root.contains?.(active)?active?.dataset?.focusKey:null;
  const selStart=focusKey&&typeof active.selectionStart==='number'?active.selectionStart:null,selEnd=focusKey&&typeof active.selectionEnd==='number'?active.selectionEnd:null;
  // Removing the page can clamp an outer work area's scroll before the new content is laid out.
  const scrollPositions=[];for(let host=root;host;host=host.parentElement)scrollPositions.push([host,host.scrollTop||0,host.scrollLeft||0]);
  const openDetails=[...root.querySelectorAll('details[open]')].map(d=>d.className);
  root.className=mode==='settings'?'character-studio is-settings-hub':'character-studio';
  root.replaceChildren(mode==='settings'?settingsView():studioView());
  for(const d of root.querySelectorAll('details'))if(openDetails.includes(d.className))d.open=true;
  for(const [host,top,left]of scrollPositions){host.scrollTop=top;host.scrollLeft=left;}
  if(focusKey){const next=root.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`);if(next){next.focus({preventScroll:true});if(selStart!=null)try{next.setSelectionRange(selStart,selEnd);}catch{}}}
 }

 return {
  async load({mode:nextMode='studio',hub,tab,provider,section:routeSec}={}){
   viewEpoch++;
   disposed=false;mode=nextMode==='settings'?'settings':'studio';
   if(mode==='settings'){
    const urlParams=typeof location!=='undefined'?new URLSearchParams(location.search||''):new URLSearchParams();
    const effTab=tab||urlParams.get('tab')||'';
    const effHub=hub||urlParams.get('hub')||'';
    const effSec=routeSec||urlParams.get('section')||'';
    const effProvider=provider||urlParams.get('provider')||'';
    if(effSec&&['models','defaults','updates'].includes(effSec)){
     settingsRoutesSection=effSec;
    }
    if(effTab==='image'||effTab==='video'||effTab==='routes'){
     settingsModality=effTab;
     settingsHub=effHub==='subscription'?'subscription':'api';
    }else if(effHub==='api'||effHub==='subscription'){
     settingsHub=effHub;
    }else{
     settingsHub='subscription';
    }
    if(effProvider&&PROVIDER_META[effProvider]){
     settingsProvider=effProvider;
     store.updateApiConfig({activeProvider:effProvider});
    }else{
     settingsProvider=state().apiConfig.activeProvider;
    }
    if(effProvider&&VIDEO_PROVIDER_META[effProvider]){
     settingsVideoProvider=effProvider;
     store.updateApiConfig({activeVideoProvider:effProvider});
    }else{
     settingsVideoProvider=state().apiConfig.activeVideoProvider;
    }
    if(routesPanelCtrl&&settingsModality==='routes'){
     routesPanelCtrl.setSection(settingsRoutesSection);
    }
   }
   unsub?.();unsub=store.subscribe(()=>render());
   if(!pasteHandler){
    pasteHandler=async event=>{
     if(disposed||mode!=='studio'||root.hidden)return;
     const target=event.target;if(target&&(target.tagName==='TEXTAREA'||target.tagName==='INPUT'))return;
     const files=[...(event.clipboardData?.files||[])].filter(f=>f.type.startsWith('image/'));
     if(!files.length)return;event.preventDefault();
     if(state().apiConfig.activeProvider==='pixai'){notice('PixAI 仅支持三张独立参考图，请使用各槽位的上传按钮');return;}
     for(const f of files){try{const {url}=await fileToDataUrl(f);store.addExtraImage({name:'粘贴图片',url});}catch(error){notice(error.message);}}
    };
    document.addEventListener('paste',pasteHandler);
   }
   store.refreshAuthStatus();
   if(mode==='studio')store.refreshHistoryCount();
   render(true);
  },
  suspend(){
   viewEpoch++;
   disposed=true;unsub?.();unsub=null;store.stopAuthPolling();
   routesPanelCtrl?.destroy?.();routesPanelCtrl=null;routesPanelNode=null;
   if(pasteHandler){document.removeEventListener('paste',pasteHandler);pasteHandler=null;}
   for(const d of document.querySelectorAll('dialog.cs-dialog'))d.close?.();
  },
  stitchList:()=>recipeImageList(state().recipe),
 };
}
