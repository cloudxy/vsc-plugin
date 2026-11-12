// AI 角色合成台 and API 接口配置 views (OAuth login bridges for AGY & Grok + Cloud API keys).
import {openAssetImageViewer} from './asset-center.js';
import {PROVIDER_META,PROVIDER_ORDER,SETTINGS_GROUPS,SETTINGS_MODALITIES,VIDEO_PROVIDER_META,VIDEO_SETTINGS_GROUPS,
 STYLE_PRESETS,isAuthProvider,groupForProvider,isVideoAuthProvider,groupForVideoProvider,VIDEO_IMAGE_KEY_PEERS,IMAGE_VIDEO_KEY_PEERS,
 referenceImageUrl,localCostumeImageUrl,poseThumbPath,poseImagePath,selectCostumeView,uploadedReferences,fileToDataUrl,comparisonReferences,recipeImageList} from './character-studio-ai.js';
import * as store from './character-studio-store.js';

const SLOT_LABEL={portrait:'人像',costume:'服装',pose:'姿势'};
const SLOT_GALLERY={portrait:'portrait',costume:'costume',pose:'pose'};
const GALLERY_NAME={portrait:'人像颜值库',costume:'服装穿搭库',pose:'动作姿势库'};

function el(tag,cls='',text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=String(text);return n;}
function option(value,label,selected){const o=el('option','',label);o.value=value;if(selected)o.selected=true;return o;}
function select(options,value,onChange,{label='',key=''}={}){
 const s=el('select');if(label)s.setAttribute('aria-label',label);if(key)s.dataset.focusKey=key;
 for(const [v,l]of options)s.append(option(v,l,String(v)===String(value)));
 s.value=String(value??'');s.onchange=()=>onChange(s.value);return s;
}
function field(label,control,hint){
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
 }else{
  svg.append(make('rect',{x:'3',y:'4',width:'18',height:'16',rx:'2.5'}),make('circle',{cx:'8.5',cy:'9.5',r:'1.5'}),make('path',{d:'m21 15-4.5-4.5L7 20'}));
 }
 return svg;
}

export function createCharacterStudio(root,ctx){
 let mode='studio',disposed=false,renderSig='',settingsModality='image',settingsProvider=null,settingsVideoProvider=null,showKey=false,showVideoKey=false,busy=new Set(),scopes={portrait:'similar',costume:'similar',pose:'similar'},unsub=null,pasteHandler=null,progressNode=null,errorNode=null;
 store.configureStudio({notice:ctx.notice,api:ctx.api,csrf:()=>ctx.session().csrf});
 const notice=message=>ctx.notice(message);
 const state=()=>store.getState();

 function action(text,fn,cls='',key=''){
  const b=el('button',cls,text);b.type='button';if(key)b.dataset.busyKey=key;
  if(key&&busy.has(key)){b.disabled=true;b.setAttribute('aria-busy','true');}
  b.onclick=async event=>{
   if(b.disabled)return;
   if(key){busy.add(key);}b.disabled=true;b.setAttribute('aria-busy','true');
   try{await fn(event);}catch(error){if(!disposed)notice(error?.message||String(error));}
   finally{if(key)busy.delete(key);b.disabled=false;b.removeAttribute('aria-busy');if(key&&!disposed)render(true);}
  };return b;
 }
 function zoom(src,title){if(src)openAssetImageViewer({title,src:referenceImageUrl(src),host:document.body});}

 function providerStatusText(id){
  const s=state(),meta=PROVIDER_META[id];
  if(isAuthProvider(id)){
   const info=s.authStatus[meta.authVendor]||{};
   return store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录');
  }
  return s.apiConfig.providers[id]?.apiKey?.trim()?'已配置 Key':'未配置 Key';
 }
 function videoProviderStatusText(id){
  const s=state(),meta=VIDEO_PROVIDER_META[id];
  if(isVideoAuthProvider(id)){
   const info=s.authStatus[meta.authVendor]||{};
   return store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录');
  }
  return s.apiConfig.videoProviders?.[id]?.apiKey?.trim()?'已配置 Key':'未配置 Key';
 }
 function groupSummary(group){
  const s=state();
  if(group.modes.length===1){
   const id=group.modes[0],ok=Boolean(s.apiConfig.providers[id]?.apiKey?.trim());
   return {label:ok?'已配置 Key':'未配置 Key',tone:ok?'is-set':''};
  }
  const [oauthId,apiId]=group.modes,vendor=PROVIDER_META[oauthId].authVendor;
  const authReady=Boolean(s.authStatus[vendor]?.ready),keyReady=Boolean(s.apiConfig.providers[apiId]?.apiKey?.trim());
  if(authReady&&keyReady)return {label:'授权已就绪 · Key 已配',tone:'is-ok'};
  if(authReady)return {label:`${PROVIDER_META[oauthId].shortName}已就绪`,tone:'is-ok'};
  if(keyReady)return {label:`${PROVIDER_META[apiId].shortName}已配置`,tone:'is-set'};
  return {label:'待授权或配 Key',tone:''};
 }
 function videoGroupSummary(group){
  const s=state();
  if(group.modes.length===1){
   const id=group.modes[0],ok=Boolean(s.apiConfig.videoProviders?.[id]?.apiKey?.trim());
   return {label:ok?'已配置 Key':'未配置 Key',tone:ok?'is-set':''};
  }
  const [oauthId,apiId]=group.modes,vendor=VIDEO_PROVIDER_META[oauthId].authVendor;
  const authReady=Boolean(s.authStatus[vendor]?.ready),keyReady=Boolean(s.apiConfig.videoProviders?.[apiId]?.apiKey?.trim());
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
  wrap.append(el('h3','',`附加参考图 (${list.length})`));
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
  if(p==='agy_auth'){
   const a=cfg.agyParams;
   box.append(field('画幅比例',select(['3:4','1:1','4:3','9:16','16:9'].map(v=>[v,v]),a.aspectRatio,up('agyParams','aspectRatio'))),
    field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')));
   return box;
  }
  if(p==='grok_auth'){
   const gr=cfg.grokParams,usesImagineApi=String(cfg.providers.grok_auth?.model||'').startsWith('grok-imagine-');
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
   const g=cfg.gptParams;
   box.append(field('接口模式',select([['images_edits_json','/v1/images/edits JSON（URL 直传）'],['images_edits','/v1/images/edits multipart'],['responses','/v1/responses'],['chat','Chat Completions 中转']],g.endpointMode,up('gptParams','endpointMode'))),
    field('输出尺寸 (size)',select([['1024x1536','1024x1536'],['1024x1024','1024x1024'],['1536x1024','1536x1024'],['auto','auto']],g.size,up('gptParams','size'))),
    field('渲染质量 (quality)',select(['high','xhigh','max','medium','low','auto'].map(v=>[v,v]),g.quality,up('gptParams','quality'))),
    field('参考还原度 (input_fidelity)',select([['high','high'],['low','low']],g.inputFidelity,up('gptParams','inputFidelity'))),
    field('背景模式 (background)',select(['auto','transparent','opaque'].map(v=>[v,v]),g.background,up('gptParams','background'))),
    field('图片格式 (output_format)',select(['png','webp','jpeg'].map(v=>[v,v]),g.outputFormat,up('gptParams','outputFormat'))));
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
  }
  box.append(field('图片传参方式',select([['url','URL'],['base64','Base64']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))),
   field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')),
   field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用':'浏览器直连')));
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
  acts.append(action('在线验证',()=>store.verifyAuth(vendor),'',`verify-inline-${vendor}`));
  acts.append(action('刷新状态',()=>store.refreshAuthStatus(),'',`refresh-${vendor}`));
  bar.append(acts);
  return bar;
 }

 function engineSection(){
  const cfg=state().apiConfig,p=cfg.activeProvider,meta=PROVIDER_META[p],pc=cfg.providers[p];
  const cfgBtn=action(isAuthProvider(p)?'授权配置':'配置 Key',()=>{settingsModality='image';settingsProvider=p;ctx.navigate?.('api-settings',{tab:'image'});},'cs-ghost');
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
  if(isAuthProvider(p))sec.body.append(authInlineBanner(p));
  else if(!pc.apiKey.trim())sec.body.append(el('p','cs-warn',`尚未配置 ${meta.name} 的 API Key，请点击右上角「配置 Key」。`));
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
  const gen=action(s.isGenerating?'生成中…':`生成角色图${count?` (${count} 张参考)`:''}`,()=>store.startGeneration(),'cs-primary cs-generate');
  gen.disabled=s.isGenerating||!s.hydrated;
  sec.body.append(gen);
  return sec.node;
 }

 function resultSection(){
  const s=state(),sec=section('生成结果');
  progressNode=el('div','cs-progress');updateProgress();
  sec.body.append(progressNode);
  errorNode=el('pre','cs-error-box');errorNode.hidden=!s.generationError;errorNode.textContent=s.generationError||'';sec.body.append(errorNode);
  const stage=el('div','cs-result');
  if(s.previewUrl){
   const btn=el('button','cs-result-img');btn.type='button';btn.setAttribute('aria-label','放大生成结果');
   const img=el('img');img.src=s.previewUrl;img.alt='生成结果';btn.append(img);btn.onclick=()=>zoom(s.previewUrl,'生成结果');
   stage.append(btn);
   const acts=el('div','cs-row-actions');acts.append(action('下载 PNG',()=>download(s.previewUrl,`character-${Date.now()}.png`)));stage.append(acts);
  }else stage.append(el('p','cs-empty','选好参考图后点击「生成角色图」，结果会显示在这里。'));
  sec.body.append(stage);
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
 function historySection(){
  const s=state(),acts=el('div','cs-row-actions');
  if(s.history.length)acts.append(action('清空记录',()=>{if(confirm('确定清空全部生成记录？'))store.clearHistory();}));
  const sec=section(`生成记录 (${s.history.length})`,{actions:acts});
  if(!s.history.length){sec.body.append(el('p','cs-empty','暂无生成记录。'));return sec.node;}
  const grid=el('div','cs-history');
  for(const h of s.history){
   const card=el('article','cs-history-item'),btn=el('button','cs-history-img');btn.type='button';btn.setAttribute('aria-label',`查看生成记录：${h.recipeSummary}`);
   const img=el('img');img.src=h.imageUrl;img.alt=h.recipeSummary;img.loading='lazy';btn.append(img);btn.onclick=()=>zoom(h.imageUrl,h.recipeSummary);
   const meta=el('div','cs-history-meta');meta.append(el('strong','',h.recipeSummary),el('small','',`${PROVIDER_META[h.provider]?.shortName||h.provider} · ${new Date(h.createdAt).toLocaleString()}`));
   const tools=el('div','cs-row-actions');
   tools.append(action('复用词',()=>{store.setCustomPrompt(h.prompt);notice('已恢复该图提示词');}),action('对比参考',()=>compareDialog(h)),action('下载',()=>download(h.imageUrl,`character-${h.createdAt}.png`)));
   const del=action('删除',()=>store.removeHistoryItem(h.id));del.title='删除此记录';tools.append(del);
   card.append(btn,meta,tools);grid.append(card);
  }
  sec.body.append(grid);return sec.node;
 }

 function compareDialog(result){
  const refs=comparisonReferences(result);
  if(!refs.length){notice('这条记录没有可对比的参考图快照');return;}
  let ref=refs[0],cmpMode='side',scale=1,split=50;
  const dialog=el('dialog','cs-dialog cs-compare');dialog.setAttribute('aria-label','对比参考');
  const head=el('header','cs-dialog-head');head.append(el('h2','','对比参考'),action('×',()=>dialog.close(),'cs-icon-btn'));
  const bar=el('div','cs-compare-bar'),stage=el('div','cs-compare-stage');
  const draw=()=>{
   bar.replaceChildren(select(refs.map(r=>[r.id,r.label]),ref.id,v=>{ref=refs.find(r=>r.id===v)||refs[0];draw();},{label:'参考图'}));
   const seg=el('div','cs-seg');for(const [v,l]of [['side','并排'],['slider','滑杆']]){const b=el('button','',l);b.type='button';b.setAttribute('aria-pressed',String(cmpMode===v));b.onclick=()=>{cmpMode=v;draw();};seg.append(b);}
   const zoomOut=el('button','','−'),zoomIn=el('button','','＋'),reset=el('button','','适应');for(const b of [zoomOut,zoomIn,reset])b.type='button';
   zoomOut.onclick=()=>{scale=Math.max(0.5,scale-0.25);apply();};zoomIn.onclick=()=>{scale=Math.min(4,scale+0.25);apply();};reset.onclick=()=>{scale=1;apply();};
   bar.append(seg,zoomOut,zoomIn,reset);
   stage.replaceChildren();stage.dataset.mode=cmpMode;
   const a=el('img'),b=el('img');a.src=ref.url;a.alt=ref.label;b.src=result.imageUrl;b.alt='生成结果';
   if(cmpMode==='side'){
    for(const [img,label]of [[a,ref.label],[b,'生成结果']]){const pane=el('figure','cs-compare-pane');const vp=el('div','cs-compare-viewport');vp.append(img);pane.append(vp,el('figcaption','',label));stage.append(pane);}
    const vps=[...stage.querySelectorAll('.cs-compare-viewport')];
    for(const vp of vps)vp.addEventListener('scroll',()=>{for(const other of vps)if(other!==vp){other.scrollLeft=vp.scrollLeft;other.scrollTop=vp.scrollTop;}});
   }else{
    const box=el('div','cs-compare-overlay');const over=el('div','cs-compare-top');over.append(b);box.append(a,over);
    const range=el('input');range.type='range';range.min='0';range.max='100';range.value=String(split);range.setAttribute('aria-label','对比分割位置');
    range.oninput=()=>{split=Number(range.value);over.style.clipPath=`inset(0 0 0 ${split}%)`;};
    over.style.clipPath=`inset(0 0 0 ${split}%)`;
    stage.append(box,range);
   }
   apply();
  };
  const apply=()=>{for(const img of stage.querySelectorAll('img')){img.style.transform=`scale(${scale})`;}};
  dialog.append(head,bar,stage);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal?.();draw();
 }

 function studioView(){
  const s=state(),page=el('div','cs-page');
  const head=el('header','cs-page-head');
  const title=el('div','cs-title');title.append(el('h1','','AI 角色合成台'),el('p','','从人像颜值库、服装穿搭库、动作姿势库挑选参考，通过 AGY / Grok 授权登录或主流云端 API 组合生成角色图。'));
  const acts=el('div','cs-row-actions');
  acts.append(action('随机',()=>store.randomizeAll(),'','random-all'),action('清空',()=>store.clearRecipe()),
   action(s.safeMode?'安全模式 · 开':'安全模式 · 关',()=>store.toggleSafeMode(),s.safeMode?'':'cs-danger'),
   action('API 接口配置',()=>ctx.navigate?.('api-settings'),'cs-ghost'));
  head.append(title,acts);page.append(head);
  const cols=el('div','cs-columns'),left=el('div','cs-col'),right=el('div','cs-col');
  const refs=section('1. 参考图组合',{actions:action('查看拼图',async()=>{const url=await store.refreshStitchPreview();if(url)stitchDialog(url);},'','stitch')});
  const slots=el('div','cs-slots');for(const slot of ['portrait','costume','pose'])slots.append(slotCard(slot));
  refs.body.append(slots,extraImages());
  left.append(refs.node,engineSection(),promptSection());
  right.append(resultSection(),historySection());
  cols.append(left,right);page.append(cols);
  return page;
 }

 // ------------------------------------------------------------------ settings (图 / 视频双 Tab)
 function syncSettingsTabRoute(tab){
  if(typeof window==='undefined'||typeof location==='undefined')return;
  const onSettings=location.pathname==='/api-settings'||String(location.search||'').includes('page=api-settings');
  if(!onSettings)return;
  const route=new URLSearchParams(location.search);
  if(location.pathname!=='/api-settings')route.set('page','api-settings');
  route.set('tab',tab);
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
   const head=el('div','cs-mode-btn-head');
   head.append(el('strong','',m.modeLabel),el('span','cs-mode-pill '+(isAuthFn(mid)?'is-oauth':'is-apikey'),statusFn(mid)));
   btn.append(head,el('small','',m.modeHint));
   btn.onclick=()=>onPick(mid);
   wrap.append(btn);
  }
  return wrap;
 }

 function authSettingsBody(pid,{isVideo=false}={}){
  const s=state(),meta=(isVideo?VIDEO_PROVIDER_META:PROVIDER_META)[pid];
  const pc=(isVideo?s.apiConfig.videoProviders:s.apiConfig.providers)[pid];
  const updateFn=isVideo?store.updateVideoProviderConfig:store.updateProviderConfig;
  const vendor=meta.authVendor,info=s.authStatus[vendor]||{};
  const wrap=el('div','cs-auth-panel');
  const card=el('div','cs-auth-card '+(info.ready?'is-ok':info.status==='expired'||info.status==='cli_missing'?'is-error':''));
  const statusHead=el('div','cs-auth-head');
  statusHead.append(el('span','cs-conn-badge',store.AUTH_STATUS_LABELS[info.status]||(info.ready?'已授权':'未登录')));
  if(info.account)statusHead.append(el('span','cs-auth-account',`账号 ${info.account}`));
  if(s.authPolling===vendor)statusHead.append(el('span','cs-auth-polling','等待授权完成并自动刷新…'));
  card.append(statusHead,el('p','cs-auth-msg',info.message||''));
  const acts=el('div','cs-row-actions');
  acts.append(action(vendor==='grok'?'调起浏览器授权登录':'打开终端完成 AGY 授权',()=>store.startAuthLogin(vendor),'cs-primary',`auth-login-${vendor}`));
  acts.append(action(vendor==='grok'?'在线验证授权 (grok models)':'在线验证授权 (agy models)',()=>store.verifyAuth(vendor),'',`auth-verify-${vendor}`));
  acts.append(action('刷新授权状态',()=>store.refreshAuthStatus(),'',`auth-refresh-${vendor}`));
  const cmdText=info.login_command||(vendor==='grok'?'grok login --oauth':'agy');
  acts.append(action(`复制命令：${cmdText}`,async()=>{await navigator.clipboard?.writeText(cmdText);notice(`已复制终端命令：${cmdText}`);}));
  card.append(acts);
  const cmdRow=el('div','cs-cmd-box');cmdRow.append(el('span','cs-cmd-label','终端授权命令'),el('code','',`$ ${cmdText}`));
  card.append(cmdRow);
  wrap.append(card);

  wrap.append(field(isVideo?'默认视频模型':'默认模型 / 引擎',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>updateFn(pid,{model:v}))));
  if(pc.model==='custom'){
   const custom=el('input');custom.value=pc.customModel;custom.placeholder=isVideo?'输入视频模型 ID':'输入协调模型 ID（留空则使用默认模型）';custom.dataset.focusKey=isVideo?'set-video-custom':'set-custom';
   custom.onchange=()=>updateFn(pid,{customModel:custom.value});
   wrap.append(field('自定义模型 ID',custom));
  }
  const note=vendor==='grok'
   ?(isVideo
     ?'凭证边界：本模式复用本机 ~/.grok/auth.json 中的 Grok CLI 订阅登录态调用 Imagine 视频接口（服务端不回显、不落盘任何密钥），与「Grok API 接口」按量计费 Key 严格分开识别，不自动混用或回退。'
     :'凭证边界：本模式复用本机 ~/.grok/auth.json 中的 grok CLI 登录态，支持调用终端 grok 内置 image_edit 或直连 Imagine 订阅接口（服务端不回显、不落盘任何密钥，子进程严格剥离 XAI_API_KEY），与「Grok API 接口」按量计费 Key 严格分开识别，不自动混用或回退。')
   :'凭证边界：本模式复用本机 Antigravity CLI (~/.gemini/antigravity-cli) 登录态，通过内置 image-generator 子智能体生成角色图；服务端不读取或传输任何令牌明文。';
  wrap.append(el('p','cs-field-hint',note));
  return wrap;
 }

 function apiKeySettingsBody(pid,{isVideo=false}={}){
  const cfg=state().apiConfig,meta=(isVideo?VIDEO_PROVIDER_META:PROVIDER_META)[pid];
  const pc=(isVideo?cfg.videoProviders:cfg.providers)[pid];
  const updateFn=isVideo?store.updateVideoProviderConfig:store.updateProviderConfig;
  const visible=isVideo?showVideoKey:showKey;
  const wrap=el('div','cs-apikey-panel');
  const base=el('input');base.type='url';base.value=pc.baseUrl;base.placeholder=meta.defaultBaseUrl;base.dataset.focusKey=isVideo?'set-video-base':'set-base';
  base.onchange=()=>updateFn(pid,{baseUrl:base.value});
  const baseHint=(pid==='grok'||pid==='grok_video')
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

 function imageSettingsPanel(panel){
  const cfg=state().apiConfig;
  const pid=PROVIDER_META[settingsProvider]?settingsProvider:cfg.activeProvider;
  const group=groupForProvider(pid),meta=PROVIDER_META[pid];

  const tabs=el('div','cs-provider-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','生图服务商');
  for(const g of SETTINGS_GROUPS){
   const selected=g.id===group.id,summary=groupSummary(g);
   const b=el('button','cs-provider-tab');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(selected));
   b.dataset.groupId=g.id;
   const text=el('span','cs-provider-text');text.append(el('strong','',g.name),el('small','',summary.label));
   const dot=el('span','cs-dot'+(summary.tone?' '+summary.tone:''));dot.title=summary.label;
   b.append(text,dot);
   b.onclick=()=>{
    const nextPid=g.modes.includes(cfg.activeProvider)?cfg.activeProvider:g.modes[0];
    settingsProvider=nextPid;store.updateApiConfig({activeProvider:nextPid});
    if(isAuthProvider(nextPid))store.refreshAuthStatus();
   };
   tabs.append(b);
  }
  panel.append(tabs);

  const acts=el('div','cs-row-actions');
  const doc=el('a','cs-link','文档');doc.href=meta.docUrl;doc.target='_blank';doc.rel='noreferrer';acts.append(doc);
  if(!isAuthProvider(pid)){
   const peerVid=IMAGE_VIDEO_KEY_PEERS[pid],peerKey=peerVid?cfg.videoProviders?.[peerVid]?.apiKey?.trim():'';
   if(peerKey&&peerKey!==cfg.providers[pid]?.apiKey?.trim()){
    acts.append(action('复用「视频」同厂商 Key',()=>{store.updateProviderConfig(pid,{apiKey:peerKey});notice(`已从视频配置复用 ${meta.shortName} Key`);}));
   }
   acts.append(action('恢复默认',()=>{store.updateProviderConfig(pid,{baseUrl:meta.defaultBaseUrl,model:meta.models[0].value});notice('已恢复生图默认端点与模型');}));
  }
  const sec=section(`${group.name} · 生图接入配置`,{actions:acts});
  const modeBar=modeSwitchBar(group,pid,{
   metaMap:PROVIDER_META,isAuthFn:isAuthProvider,statusFn:providerStatusText,
   onPick:mid=>{settingsProvider=mid;store.updateApiConfig({activeProvider:mid});if(isAuthProvider(mid))store.refreshAuthStatus();},
  });
  if(modeBar)sec.body.append(modeBar);
  sec.body.append(isAuthProvider(pid)?authSettingsBody(pid,{isVideo:false}):apiKeySettingsBody(pid,{isVideo:false}));
  panel.append(sec.node);

  if(!isAuthProvider(pid)){
   const g=section('生图全局请求选项');
   g.body.append(
    field('参考图传参方式',select([['url','传递图片 URL（免上传文件，Gemini 原生与 Grok 编辑自动转 Base64）'],['base64','统一转 Base64 编码传输']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))),
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用（解决跨域限制）':'已关闭（浏览器直连）'),'切换到 Grok API、阿里云百炼 (Qwen) 或火山方舟 (Doubao) 时会自动启用；仅转发白名单 HTTPS 官方域名。'),
   );
   panel.append(g.node);
  }
  const foot=el('div','cs-row-actions cs-end');
  foot.append(action('保存配置',()=>{const active=document.activeElement;active?.dispatchEvent?.(new Event('change'));notice('生图接口配置已保存');},'cs-primary'));
  panel.append(foot);
 }

 function videoSettingsPanel(panel){
  const cfg=state().apiConfig;
  const pid=VIDEO_PROVIDER_META[settingsVideoProvider]?settingsVideoProvider:cfg.activeVideoProvider;
  const group=groupForVideoProvider(pid),meta=VIDEO_PROVIDER_META[pid];
  const vd=cfg.videoDefaults||{mode:'image_to_video',aspectRatio:'16:9',resolution:'720p',durationSec:'5',generateAudio:true};

  const tabs=el('div','cs-provider-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','视频服务商');
  for(const g of VIDEO_SETTINGS_GROUPS){
   const selected=g.id===group.id,summary=videoGroupSummary(g);
   const b=el('button','cs-provider-tab');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(selected));
   b.dataset.groupId=g.id;
   const text=el('span','cs-provider-text');text.append(el('strong','',g.name),el('small','',summary.label));
   const dot=el('span','cs-dot'+(summary.tone?' '+summary.tone:''));dot.title=summary.label;
   b.append(text,dot);
   b.onclick=()=>{
    const nextPid=g.modes.includes(cfg.activeVideoProvider)?cfg.activeVideoProvider:g.modes[0];
    settingsVideoProvider=nextPid;store.updateApiConfig({activeVideoProvider:nextPid});
    if(isVideoAuthProvider(nextPid))store.refreshAuthStatus();
   };
   tabs.append(b);
  }
  panel.append(tabs);

  const acts=el('div','cs-row-actions');
  const doc=el('a','cs-link','文档');doc.href=meta.docUrl;doc.target='_blank';doc.rel='noreferrer';acts.append(doc);
  if(!isVideoAuthProvider(pid)){
   const peerImg=VIDEO_IMAGE_KEY_PEERS[pid],peerKey=peerImg?cfg.providers?.[peerImg]?.apiKey?.trim():'';
   if(peerKey&&peerKey!==cfg.videoProviders?.[pid]?.apiKey?.trim()){
    acts.append(action('复用「图」同厂商 Key',()=>{store.updateVideoProviderConfig(pid,{apiKey:peerKey});notice(`已从生图配置复用 ${meta.shortName} Key`);}));
   }
   acts.append(action('恢复默认',()=>{store.updateVideoProviderConfig(pid,{baseUrl:meta.defaultBaseUrl,model:meta.models[0].value});notice('已恢复视频默认端点与模型');}));
  }
  const sec=section(`${group.name} · 视频接入配置`,{actions:acts});
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
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.videoUseProxy,v=>store.updateApiConfig({videoUseProxy:v}),cfg.videoUseProxy?'已启用（支持异步任务提交与轮询代理）':'已关闭（浏览器直连）'),'切换到 Grok API、通义万相 (Wan) 或火山 Seedance 时自动启用；仅转发白名单 HTTPS 官方域名。'),
   );
  }
  panel.append(g.node);

  const foot=el('div','cs-row-actions cs-end');
  foot.append(action('保存配置',()=>{const active=document.activeElement;active?.dispatchEvent?.(new Event('change'));notice('视频接口配置已保存');},'cs-primary'));
  panel.append(foot);
 }

 function settingsView(){
  const page=el('div','cs-page cs-settings');
  const head=el('header','cs-page-head');
  const title=el('div','cs-title');
  title.append(el('h1','','API 接口配置'),el('p','','按「图」与「视频」分栏管理授权登录及云端 API Key 接口配置。API Key 仅保存在当前浏览器。'));
  head.append(title,action('返回 AI 角色合成台',()=>ctx.navigate?.('character-studio'),'cs-primary'));
  page.append(head);

  const modalityBar=el('div','cs-modality-tabs');
  modalityBar.setAttribute('role','tablist');
  modalityBar.setAttribute('aria-label','接口模态分类');
  const switchModality=nextModality=>{
   if(nextModality!=='image'&&nextModality!=='video')return;
   settingsModality=nextModality;
   syncSettingsTabRoute(nextModality);
   render(true);
  };
  for(const mod of SETTINGS_MODALITIES){
   const active=settingsModality===mod.id;
   const readyCount=modalityReadyCount(mod.id),totalCount=mod.id==='image'?SETTINGS_GROUPS.length:VIDEO_SETTINGS_GROUPS.length;
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
   const badge=el('span','cs-modality-badge'+(readyCount>0?' is-ready':''),readyCount>0?`已就绪 ${readyCount}/${totalCount}`:`0/${totalCount} 已配`);
   tabBtn.append(svgIcon(mod.id),copy,badge);
   tabBtn.onclick=()=>switchModality(mod.id);
   tabBtn.addEventListener('keydown',event=>{
    if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
     event.preventDefault?.();
     const targetMod=mod.id==='image'?'video':'image';
     switchModality(targetMod);
     root.querySelector(`#cs-modality-tab-${targetMod}`)?.focus?.();
    }
   });
   modalityBar.append(tabBtn);
  }
  page.append(modalityBar);

  const panel=el('div','cs-modality-panel');
  panel.id='cs-modality-panel';
  panel.setAttribute('role','tabpanel');
  panel.setAttribute('aria-labelledby',`cs-modality-tab-${settingsModality}`);
  if(settingsModality==='video')videoSettingsPanel(panel);
  else imageSettingsPanel(panel);
  page.append(panel);
  return page;
 }

 // ------------------------------------------------------------------ render loop
 function signature(){
  const s=state();
  return JSON.stringify([mode,settingsModality,settingsProvider,settingsVideoProvider,showKey,showVideoKey,[...busy],s.recipe,s.apiConfig,s.authStatus,s.authPolling,s.history.map(h=>h.id),s.safeMode,s.poseDepthMode,s.customPrompt,s.previewUrl,s.isGenerating,s.generationError,s.hydrated]);
 }
 function render(force=false){
  if(disposed)return;
  const sig=signature();
  if(!force&&sig===renderSig){updateProgress();return;}
  renderSig=sig;
  const active=document.activeElement,focusKey=root.contains?.(active)?active?.dataset?.focusKey:null;
  const selStart=focusKey&&typeof active.selectionStart==='number'?active.selectionStart:null,selEnd=focusKey&&typeof active.selectionEnd==='number'?active.selectionEnd:null;
  const scrollTop=root.scrollTop,openDetails=[...root.querySelectorAll('details[open]')].map(d=>d.className);
  root.className='character-studio';
  root.replaceChildren(mode==='settings'?settingsView():studioView());
  for(const d of root.querySelectorAll('details'))if(openDetails.includes(d.className))d.open=true;
  root.scrollTop=scrollTop;
  if(focusKey){const next=root.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`);if(next){next.focus({preventScroll:true});if(selStart!=null)try{next.setSelectionRange(selStart,selEnd);}catch{}}}
 }

 return {
  async load({mode:nextMode='studio',tab}={}){
   disposed=false;mode=nextMode==='settings'?'settings':'studio';
   if(mode==='settings'){
    if(tab==='video'||tab==='image')settingsModality=tab;
    else if(typeof location!=='undefined'){
     const urlTab=new URLSearchParams(location.search||'').get('tab');
     if(urlTab==='video'||urlTab==='image')settingsModality=urlTab;
    }
    settingsProvider=state().apiConfig.activeProvider;
    settingsVideoProvider=state().apiConfig.activeVideoProvider;
   }
   unsub?.();unsub=store.subscribe(()=>render());
   if(!pasteHandler){
    pasteHandler=async event=>{
     if(disposed||mode!=='studio'||root.hidden)return;
     const target=event.target;if(target&&(target.tagName==='TEXTAREA'||target.tagName==='INPUT'))return;
     const files=[...(event.clipboardData?.files||[])].filter(f=>f.type.startsWith('image/'));
     if(!files.length)return;event.preventDefault();
     for(const f of files){try{const {url}=await fileToDataUrl(f);store.addExtraImage({name:'粘贴图片',url});}catch(error){notice(error.message);}}
    };
    document.addEventListener('paste',pasteHandler);
   }
   store.refreshAuthStatus();
   render(true);
  },
  suspend(){
   disposed=true;unsub?.();unsub=null;store.stopAuthPolling();
   if(pasteHandler){document.removeEventListener('paste',pasteHandler);pasteHandler=null;}
   for(const d of document.querySelectorAll('dialog.cs-dialog'))d.close?.();
  },
  stitchList:()=>recipeImageList(state().recipe),
 };
}
