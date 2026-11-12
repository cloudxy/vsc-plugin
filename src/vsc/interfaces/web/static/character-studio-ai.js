// Character studio generation engine, ported from ai-pose-gallery aiGenerator.ts.
// Provider keys come from the browser-local configuration only; requests go either
// directly to the provider or through the same-origin /api/proxy and /comfy relays.
import {applyWorkflowOverrides,getWorkflowImages,validateReferenceCombinations,workflowIdentity,parseComfyWorkflowNodes} from './character-studio-workflows.js';

export const MEDIA_BASE='/api/v1/asset-center/pose-gallery/media/';
let csrfProvider=()=>'';
export function setCsrfProvider(fn){csrfProvider=typeof fn==='function'?fn:()=>'';}

export function referenceImageUrl(src){
 const value=String(src||'');
 if(/^(data:|blob:|https?:\/\/|\/)/i.test(value))return value;
 const clean=value.replace(/^\/+/,'');
 if(clean.startsWith('thumbs/')||clean.startsWith('img/'))return MEDIA_BASE+clean;
 return '/'+clean;
}
const stripMedia=raw=>String(raw||'').startsWith(MEDIA_BASE)?String(raw).slice(MEDIA_BASE.length):String(raw||'');
export function poseThumbPath(pose,useDepth=Boolean(pose?.useDepth)){
 const raw=pose?.缩略图||'';
 if(pose?.source==='upload'||!useDepth||/^(data:|blob:|https?:\/\/)/i.test(raw))return raw;
 const clean=stripMedia(raw).replace(/^\/+/,'');
 if(clean.startsWith('thumbs/depth/'))return raw;
 if(clean.startsWith('thumbs/'))return `thumbs/depth/${clean.slice(7).replace(/\.(jpe?g|png)$/i,'.webp')}`;
 return raw;
}
export function poseImagePath(pose,useDepth=Boolean(pose?.useDepth)){
 const raw=pose?.原图||pose?.缩略图||'';
 if(pose?.source==='upload'||!useDepth||/^(data:|blob:|https?:\/\/)/i.test(raw))return raw;
 const clean=stripMedia(raw).replace(/^\/+/,'');
 if(clean.startsWith('img/depth/'))return raw;
 if(clean.startsWith('img/'))return `img/depth/${clean.slice(4).replace(/\.(png|jpe?g)$/i,'.webp')}`;
 return raw;
}
export function selectCostumeView(item,id=item?.selectedView||'front'){
 const view=item?.views?.find(v=>v.id===id)||item?.views?.find(v=>v.id==='front')||item?.views?.[0];
 return view?{...item,selectedView:view.id,缩略图:view.缩略图,预览图:view.预览图,原图:view.原图}:item;
}
export function uploadedReferences(name,url,width=0,height=0,bytes=0){
 const base={id:(crypto.randomUUID?.()||String(Date.now())),source:'upload',原图:url,缩略图:url,检索:name};
 return {
  portrait:{...base,分区:'上传',发长:'',发型名称:name,标题:name,宽:width,高:height,字节数:bytes,精选:false,热门:false},
  costume:{...base,分类:'上传',服装名称:name,标签:[],关键词:'',预览图:url},
  pose:{...base,体系:'上传',姿势编号:'',分类:'上传',姿势名称:name,角度:''},
 };
}

export function isLocalDevHost(){return typeof window!=='undefined'&&['localhost','127.0.0.1','[::1]'].includes(window.location?.hostname);}
export function defaultComfyBaseUrl(){return '/comfy';}
export function comfyCandidateUrls(current=''){
 return Array.from(new Set([String(current).trim(),'/comfy','http://127.0.0.1:8000','http://127.0.0.1:8188'].map(x=>x.replace(/\/+$/,'')).filter(Boolean)));
}

export const PROVIDER_ORDER=['gemini','gpt','qwen','doubao','comfyui'];
export const PROVIDER_META={
 gemini:{id:'gemini',name:'Google Gemini',shortName:'Gemini',defaultBaseUrl:'https://generativelanguage.googleapis.com',docUrl:'https://ai.google.dev/gemini-api/docs/image-generation',
  models:[['gemini-3.1-flash-image-preview'],['gemini-3-pro-image-preview'],['gemini-2.5-flash-image'],['gemini-2.5-flash-image-preview'],['custom','自定义模型 ID']]},
 gpt:{id:'gpt',name:'OpenAI GPT Image',shortName:'GPT',defaultBaseUrl:'https://api.openai.com/v1',docUrl:'https://platform.openai.com/docs/guides/image-generation',
  models:[['gpt-image-2.5'],['gpt-image-2.5-sunburst'],['gpt-image-2.5-flare'],['gpt-image-2'],['gpt-image-1.5'],['gpt-image-1'],['custom','自定义模型 ID']]},
 qwen:{id:'qwen',name:'阿里云百炼 Qwen',shortName:'Qwen',defaultBaseUrl:'https://dashscope.aliyuncs.com',docUrl:'https://help.aliyun.com/zh/model-studio/qwen-image-edit-api',
  models:[['qwen-image-3.0-pro'],['qwen-image-2.1-pro'],['qwen-image-2.1-turbo'],['qwen-image-2.0-pro'],['qwen-image-edit-plus'],['custom','自定义模型 ID']]},
 doubao:{id:'doubao',name:'字节火山方舟 Doubao',shortName:'Doubao',defaultBaseUrl:'https://ark.cn-beijing.volces.com',docUrl:'https://www.volcengine.com/docs/82379/1541523',
  models:[['doubao-seedream-5-0'],['doubao-seedream-5-0-lite'],['doubao-seedream-4-5-251128'],['doubao-seedream-4-0-250828'],['doubao-seededit-3-0-i2i-250628'],['custom','自定义模型 ID / Endpoint']]},
 comfyui:{id:'comfyui',name:'本地 ComfyUI',shortName:'ComfyUI',defaultBaseUrl:'/comfy',docUrl:'https://docs.comfy.org/essentials/comfyui_server',
  models:[['qwen_image_edit_2509','qwen_image_edit_2509（由工作流决定）'],['custom','自定义名称（仅用于记录显示）']]},
};
for(const meta of Object.values(PROVIDER_META))meta.models=meta.models.map(([value,label])=>({value,label:label||value}));

export const STYLE_PRESETS={
 none:{label:'无预设（跟随参考图）',prompt:''},
 realistic:{label:'写实人像写真',prompt:'写实商业摄影级质感，85mm 人像镜头，自然柔和光影，真实肌肤纹理与织物细节，8k 高清画质。'},
 fashion:{label:'日韩杂志画报',prompt:'日韩时尚穿搭杂志画报风格，干净极简摄影棚背景，高级色调，突出人物颜值与服装剪裁。'},
 film:{label:'复古胶片写真',prompt:'35mm 富士胶片摄影质感，轻微胶片颗粒，柔和复古暖调，自然街拍光影与电影呼吸感。'},
 semi_real:{label:'2.5D 游戏原画立绘',prompt:'2.5D 半写实高精度游戏角色原画，唯美厚涂光影，精致五官与华丽布料金属质感。'},
 anime:{label:'日系二次元插画',prompt:'日系精致二次元插画风格，细腻赛璐璐与厚涂光影过渡，动漫角色立绘质感，色彩通透干净。'},
 cel_anime:{label:'新海诚感动画电影',prompt:'动画电影级画面质感，清澈高饱和光影，细腻体积光与发丝高光，干净唯美的动漫色彩。'},
 manga:{label:'日式黑白漫画网点',prompt:'日本黑白漫画原稿风格，利落精准的G笔线稿，细腻漫画网点纸阴影与层次对比。'},
 render3d:{label:'3D 次世代角色渲染',prompt:'Unreal Engine 5 / Octane Render 次世代 3D 角色渲染，细腻次表面散射肌肤材质，电影级布光。'},
 chibi_box:{label:'3D 潮玩手办质感',prompt:'高品质 PVC 涂装完成品手办质感，柔和摄影棚柔光箱布光，精致材质高光与微距景深。'},
 cyberpunk:{label:'赛博朋克霓虹',prompt:'赛博朋克科幻视觉风格，雨夜霓虹冷暖双色轮廓光，未来感材质反光与电影级氛围。'},
 concept_sheet:{label:'角色设定集立绘（纯白底）',prompt:'标准角色设定集全身立绘，纯白干净无杂物背景，均匀漫反射布光，清晰展示全身服装结构与配饰细节。'},
};
const PHOTO_STYLES=new Set(['realistic','fashion','film']);

export function buildRecipePrompt(recipe,stylePreset='realistic',workflowImages=[]){
 const styleInfo=STYLE_PRESETS[stylePreset]??STYLE_PRESETS.realistic,isPhoto=PHOTO_STYLES.has(stylePreset);
 const sheet=workflowImages.some(i=>i.role==='character_sheet');
 const faceless=!recipe.portrait&&!sheet&&Boolean(recipe.costume&&recipe.pose);
 const clauses=[];let idx=1,costumeIdx=0;
 workflowImages.filter(i=>i.role==='character_sheet').forEach(()=>{clauses.push('• 角色设定参考：提供的设定集展示同一角色的多个视角与细节，不是多个不同人物。保持角色的脸型、五官、发型、发色、肤色及服装配饰一致；只把它作为角色参考，成品布局遵循当前工作流的输出设置。');idx++;});
 if(recipe.portrait){
  const p=recipe.portrait,hair=p.发型名称&&p.发型名称!=='标准基础款'?p.标题:p.发长;
  const skin='人物的肤色必须与图一人物一致，所有裸露皮肤（包括服装镂空处露出的皮肤）必须与脸部肤色统一，统一后的肤色与质感按风格要求呈现。';
  const outfit=recipe.costume?'':'保留图1人物原有可见服装与配饰，不复制姿势参考图的服装或白模外观。';
  clauses.push(p.source==='upload'?`• 人物：图${idx}中的人物，保持其脸型、五官、发型和发色一致。${skin}${outfit}`:`• 人物：图${idx}中的人物，保持其脸型、五官、发型（${hair}）和发色一致。${skin}${outfit}`);idx++;
 }
 if(recipe.costume){
  costumeIdx=idx;
  clauses.push(recipe.costume.source==='upload'?`• 服装：让人物穿上图${idx}中展示的整套服装和配饰，每件单品的颜色、款式、面料与配饰都以图${idx}为准。`:`• 服装：让人物穿上图${idx}中展示的整套服装和配饰（参考名称：${recipe.costume.服装名称}），每件单品的颜色、款式、面料与配饰都以图${idx}为准，名称仅作辅助说明。`);idx++;
 }
 if(recipe.pose){
  const wear=costumeIdx?`，穿着图${costumeIdx}的服装`:'';
  const body=isPhoto?`最终画面中的人物是真人，皮肤真实自然${wear}`:`人物的肤色与质感按风格要求呈现${wear}`;
  clauses.push(recipe.pose.source==='upload'?`• 姿势：按照图${idx}中的人物动作和镜头角度摆姿势；仅参考姿势与构图，不复制图${idx}人物的外观与服装，${body}。`:`• 姿势：按照图${idx}中人体模型的动作和镜头角度摆姿势（${recipe.pose.姿势名称}，${recipe.pose.角度}）；图${idx}只是动作示意，${body}。`);idx++;
 }
 if(faceless)clauses.push('• 无脸展示：生成一位穿着参考服装的成年展示人物，脸部保持无五官的自然肤色表面，不添加眼睛、鼻子、嘴巴或具体人物身份；全身裸露皮肤的颜色统一，不照搬服装图或姿势图的灰白人台材质。');
 for(const ref of workflowImages.filter(i=>i.role!=='character_sheet')){clauses.push(`• 工作流参考：参考图${idx}（${ref.name||'补充参考'}）中的相关元素，具体用途以工作流要求为准。`);idx++;}
 for(const extra of recipe.extraImages||[]){clauses.push(`• 附加参考：融合图${idx}（${extra.name||'补充元素'}）中的元素、配饰、背景或光影细节。`);idx++;}
 if(!clauses.length)return '请先选择人像/服装/姿势或上传附加参考图。';
 const lines=[`请根据${sheet?'提供的角色设定参考':`提供的 ${idx-1} 张参考图`}，生成一张完整的${faceless?'人物穿搭展示图':isPhoto?'真实人物照片':'人物图像'}：`,...clauses];
 if(styleInfo.prompt)lines.push(`• 风格：${styleInfo.prompt} ${faceless?'人物比例协调，手部自然，脸部无五官，光影统一。':'人物比例协调，手部与五官自然，光影统一。'}`);
 lines.push('画面中没有任何文字、标志或水印。');
 return lines.join('\n');
}

export function fileToDataUrl(file){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onerror=()=>reject(new Error('读取文件失败'));
  reader.onload=()=>{
   const img=new Image();
   img.onload=()=>{const scale=Math.min(1,1024/Math.max(img.width,img.height)),c=document.createElement('canvas');c.width=Math.round(img.width*scale);c.height=Math.round(img.height*scale);c.getContext('2d').drawImage(img,0,0,c.width,c.height);resolve({url:c.toDataURL('image/png'),width:img.width,height:img.height});};
   img.onerror=()=>reject(new Error('解析图片失败'));
   img.src=reader.result;
  };
  reader.readAsDataURL(file);
 });
}
function loadImage(src){
 return new Promise((resolve,reject)=>{
  const img=new Image();img.crossOrigin='anonymous';
  img.onload=()=>resolve(img);img.onerror=()=>reject(new Error(`加载图片失败: ${String(src).slice(0,80)}`));
  img.src=referenceImageUrl(src);
 });
}

export function recipeImageList(recipe){
 const list=[];let idx=1;
 if(recipe.portrait)list.push({tag:`图${idx++} · 人像`,sub:recipe.portrait.标题||recipe.portrait.发型名称||'',src:recipe.portrait.原图||recipe.portrait.缩略图});
 if(recipe.costume)list.push({tag:`图${idx++} · 服装`,sub:`${recipe.costume.分类} · ${recipe.costume.服装名称}`,src:recipe.costume.预览图||recipe.costume.原图||recipe.costume.缩略图});
 if(recipe.pose)list.push({tag:`图${idx++} · 姿势`,sub:`${recipe.pose.姿势名称}（${recipe.pose.角度}${recipe.pose.useDepth?' · 深度图':''}）`,src:poseImagePath(recipe.pose)});
 for(const extra of recipe.extraImages||[])list.push({tag:`图${idx++} · 附加`,sub:extra.name||'自定义参考图',src:extra.url});
 return list;
}

export async function stitchRecipeCanvas(recipe){
 const list=recipeImageList(recipe);
 if(!list.length)throw new Error('请至少选择或上传 1 张参考图');
 const imgs=await Promise.all(list.map(x=>loadImage(x.src)));
 const cardW=480,cardH=640,pad=20,headH=62,canvas=document.createElement('canvas');
 canvas.width=list.length*cardW+(list.length+1)*pad;canvas.height=cardH+headH+pad*2;
 const ctx=canvas.getContext('2d');
 ctx.fillStyle='#111318';ctx.fillRect(0,0,canvas.width,canvas.height);
 imgs.forEach((img,i)=>{
  const x=pad+i*(cardW+pad),y=pad;
  ctx.fillStyle='#1e222b';ctx.fillRect(x,y,cardW,cardH+headH);
  ctx.fillStyle='#f4f5f7';ctx.fillRect(x,y+headH,cardW,cardH);
  const scale=Math.min(cardW/img.width,cardH/img.height),dw=img.width*scale,dh=img.height*scale;
  ctx.drawImage(img,x+(cardW-dw)/2,y+headH+(cardH-dh)/2,dw,dh);
  ctx.fillStyle='#a1a1aa';ctx.font='600 12px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';ctx.fillText(list[i].tag,x+14,y+23);
  ctx.fillStyle='#ffffff';ctx.font='700 15px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';ctx.fillText(String(list[i].sub).slice(0,26),x+14,y+46);
 });
 return canvas.toDataURL('image/jpeg',0.92);
}

// Local relative paths map to the public gallery CDNs so cloud providers can fetch them.
export function toPublicHttpsUrl(src){
 if(/^https?:\/\//i.test(src)||String(src).startsWith('data:'))return src;
 const clean=stripMedia(src).replace(/^\/+/,'');
 if(typeof window!=='undefined'&&window.location?.protocol==='https:'&&!['localhost','127.0.0.1'].includes(window.location.hostname))return `${window.location.origin}${MEDIA_BASE}${clean}`;
 if(clean.startsWith('img/portrait/'))return `https://ai-portrait-gallery.pages.dev/img/${clean.slice(13).replace(/\.webp$/i,'.png')}`;
 if(clean.startsWith('thumbs/portrait/'))return `https://ai-portrait-gallery.pages.dev/thumbs/${clean.slice(16)}`;
 if(clean.startsWith('img/costume/')||clean.startsWith('thumbs/costume/'))return `https://ai-costume-gallery.pages.dev/${clean}`;
 if(clean.startsWith('img/depth/'))return `https://ai-pose-depth-gallery.pages.dev/img/${clean.slice(10).replace(/\.webp$/i,'.png')}`;
 if(clean.startsWith('thumbs/depth/'))return `https://ai-pose-depth-gallery.pages.dev/thumbs/${clean.slice(13).replace(/\.webp$/i,'.jpg')}`;
 return `https://ai-pose-gallery.pages.dev/${clean}`;
}
async function srcToPngDataUrl(src){
 if(String(src).startsWith('data:image/'))return src;
 const img=await loadImage(src),scale=Math.min(1,1024/Math.max(img.width,img.height)),c=document.createElement('canvas');
 c.width=Math.round(img.width*scale);c.height=Math.round(img.height*scale);c.getContext('2d').drawImage(img,0,0,c.width,c.height);
 return c.toDataURL('image/png');
}
function dataUrlToBlob(dataUrl){
 const [head,b64]=dataUrl.split(','),mime=head.match(/:(.*?);/)?.[1]||'image/png',bin=atob(b64),arr=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
 return new Blob([arr],{type:mime});
}
export async function durableImage(url){
 if(String(url).startsWith('data:image/'))return url;
 const response=await fetch(referenceImageUrl(url),{credentials:'same-origin'});
 if(!response.ok)throw new Error('图片下载失败');
 const blob=await response.blob();
 if(!blob.type.startsWith('image/'))throw new Error('引用不是图片');
 return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result));r.onerror=()=>reject(new Error('图片读取失败'));r.readAsDataURL(blob);});
}
export async function durableRecipe(recipe){
 const next=JSON.parse(JSON.stringify(recipe));
 for(const item of [next.portrait,next.costume,next.pose]){
  if(item?.source==='upload'){item.原图=await durableImage(item.原图);item.缩略图=item.原图;if('预览图' in item)item.预览图=item.原图;}
 }
 for(const image of [...(next.extraImages||[]),...Object.values(next.workflowImages||{})])image.url=await durableImage(image.url);
 return next;
}

async function smartFetch(targetUrl,init,useProxy){
 if(!useProxy)return fetch(targetUrl,init);
 const headers=new Headers(init.headers);
 headers.set('x-target-url',targetUrl);
 const csrf=csrfProvider();if(csrf)headers.set('X-CSRF-Token',csrf);
 return fetch('/api/proxy',{method:init.method||'POST',headers,body:init.body,credentials:'same-origin'});
}

function extractUniversalImage(json){
 if(json?.data?.[0]?.b64_json)return `data:image/png;base64,${json.data[0].b64_json}`;
 if(json?.data?.[0]?.url)return json.data[0].url;
 if(Array.isArray(json?.output))for(const item of json.output)if(item?.type==='image_generation_call'&&item?.result)return `data:image/png;base64,${item.result}`;
 const dash=json?.output?.choices?.[0]?.message?.content;
 if(Array.isArray(dash))for(const part of dash)if(part?.image)return part.image;
 if(json?.output?.results?.[0]?.url)return json.output.results[0].url;
 for(const p of json?.candidates?.[0]?.content?.parts||[]){
  if(p.inlineData?.data)return `data:${p.inlineData.mimeType||'image/png'};base64,${p.inlineData.data}`;
  if(p.inline_data?.data)return `data:${p.inline_data.mime_type||'image/png'};base64,${p.inline_data.data}`;
 }
 const msg=json?.choices?.[0]?.message;
 if(Array.isArray(msg?.images)&&msg.images[0]?.image_url?.url)return msg.images[0].image_url.url;
 if(Array.isArray(msg?.content))for(const part of msg.content){
  if(part.type==='image_url'&&part.image_url?.url)return part.image_url.url;
  if(part.inlineData?.data)return `data:${part.inlineData.mimeType||'image/png'};base64,${part.inlineData.data}`;
 }
 const text=typeof msg?.content==='string'?msg.content:'';
 const md=text.match(/!\[.*?\]\((data:image\/[^)]+|https?:\/\/[^\s)]+)\)/);if(md)return md[1];
 const url=text.match(/(https?:\/\/[^\s"'<>]+\.(?:png|jpg|jpeg|webp)[^\s"'<>]*)/i);if(url)return url[1];
 return null;
}

// --------------------------------------------------------------------------- ComfyUI
export function normalizeComfyBase(baseUrl){return (String(baseUrl||'').trim()||defaultComfyBaseUrl()).replace(/\/+$/,'');}
function describeComfyNetworkError(baseUrl,timedOut){
 if(timedOut)return `[ComfyUI] 请求 ${baseUrl} 超时：ComfyUI 可能正忙或无响应，请查看 ComfyUI 终端日志。`;
 if(baseUrl.startsWith('/'))return `[ComfyUI] 本机代理 ${baseUrl} 无法连通 ComfyUI：请确认 ComfyUI 已启动，且端口与服务启动时的 COMFYUI_URL 一致（默认依次尝试 http://127.0.0.1:8000 与 8188）。`;
 const origin=typeof window!=='undefined'?window.location.origin:'';
 return `[ComfyUI] 无法连接 ${baseUrl}。可能原因：\n① ComfyUI 未启动，或地址/端口不对（Desktop 版默认 8000，便携版默认 8188）\n② 跨域 (CORS) 被拦截：ComfyUI 启动参数需包含 --enable-cors-header "${origin}"，或改用 /comfy 本机代理`;
}
function comfyHeaders(baseUrl,init,apiKey){
 const headers=new Headers(init?.headers);
 if(String(apiKey||'').trim())headers.set('Authorization',`Bearer ${String(apiKey).trim()}`);
 if(baseUrl.startsWith('/')){const csrf=csrfProvider();if(csrf)headers.set('X-CSRF-Token',csrf);}
 return headers;
}
export async function comfyFetch(baseUrl,path,init={},apiKey='',timeoutMs=30000){
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),timeoutMs);
 if(init.signal){if(init.signal.aborted)ctrl.abort();else init.signal.addEventListener('abort',()=>ctrl.abort(),{once:true});}
 let res;
 try{res=await fetch(`${baseUrl}${path}`,{...init,headers:comfyHeaders(baseUrl,init,apiKey),signal:ctrl.signal,credentials:'same-origin'});}
 catch(e){throw new Error(describeComfyNetworkError(baseUrl,e?.name==='AbortError'));}
 finally{clearTimeout(timer);}
 if(baseUrl.startsWith('/')&&res.status===502){
  let message=describeComfyNetworkError(baseUrl,false);
  try{const body=await res.clone().json();if(body?.message)message=`[ComfyUI] ${body.message}`;}catch{}
  throw new Error(message);
 }
 return res;
}
async function readJsonSafe(res){const text=await res.text();try{return JSON.parse(text);}catch{return {_raw:text.slice(0,300)};}}

export async function testComfyConnection(baseUrl,apiKey=''){
 const clean=normalizeComfyBase(baseUrl);
 const res=await comfyFetch(clean,'/system_stats',{},apiKey,8000);
 if(res.status===401||res.status===403)throw new Error(`[ComfyUI] ${clean} 拒绝访问 (HTTP ${res.status})，请检查 API Key / 鉴权设置`);
 if(!res.ok)throw new Error(`[ComfyUI] ${clean}/system_stats 返回 HTTP ${res.status}，该地址可能不是 ComfyUI`);
 const data=await readJsonSafe(res);
 if(!data?.system)throw new Error(`[ComfyUI] ${clean} 的响应不是 ComfyUI 格式，请检查地址`);
 const ver=typeof data.system.comfyui_version==='string'&&/^[\d.a-zA-Z_-]{1,40}$/.test(data.system.comfyui_version)?data.system.comfyui_version:'未知版本';
 const dev=data.devices?.[0];
 const gpu=dev?.name?String(dev.name).replace(/^cuda:\d+\s*/,'').replace(/\s*:\s*\w+$/,''):'本地设备';
 const vram=dev?.vram_total?` · 显存 ${(dev.vram_total/1024**3).toFixed(1)} GB`:'';
 return `ComfyUI ${ver} · ${gpu}${vram}`;
}
export async function detectComfyUi(current='',apiKey=''){
 for(const url of comfyCandidateUrls(current)){try{return {baseUrl:url,info:await testComfyConnection(url,apiKey)};}catch{}}
 return null;
}
function comboOptions(spec){
 if(!Array.isArray(spec))return null;
 if(Array.isArray(spec[0]))return spec[0].map(String);
 if(spec[0]==='COMBO'&&Array.isArray(spec[1]?.options))return spec[1].options.map(String);
 return null;
}
const baseName=s=>String(s).split(/[\\/]/).pop().toLowerCase();
export async function fetchComfyObjectInfo(baseUrl,apiKey,workflowJson){
 const parsed=parseComfyWorkflowNodes(workflowJson);
 if(!parsed.valid)throw new Error(parsed.error||'工作流 JSON 无效');
 const workflow=JSON.parse(workflowJson),base=normalizeComfyBase(baseUrl);
 const classes=Array.from(new Set(Object.values(workflow).map(n=>n?.class_type).filter(Boolean)));
 const entries=await Promise.all(classes.map(async cls=>{
  const res=await comfyFetch(base,`/object_info/${encodeURIComponent(cls)}`,{},apiKey,15000);
  if(!res.ok)throw new Error(`[ComfyUI] 无法读取节点「${cls}」的定义（HTTP ${res.status}），请检查连接地址、访问令牌和网关接口权限。`);
  const json=await readJsonSafe(res);return [cls,json?.[cls]];
 }));
 return Object.fromEntries(entries.filter(([,d])=>d));
}
export async function checkComfyWorkflow(baseUrl,apiKey,workflowJson,mappedImageNodeIds=[],objectInfo){
 const parsedInfo=parseComfyWorkflowNodes(workflowJson);
 if(!parsedInfo.valid)return {ok:false,errors:[parsedInfo.error||'工作流 JSON 无效'],warnings:[],fixes:[]};
 const wf=JSON.parse(workflowJson),info=objectInfo??await fetchComfyObjectInfo(baseUrl,apiKey,workflowJson);
 const errors=[],warnings=[],fixes=[],mapped=new Set(mappedImageNodeIds.filter(x=>x&&x!=='none'));
 const loaders=new Set(getWorkflowImages(workflowJson,[],info).map(n=>n.nodeId));
 for(const [id,node]of Object.entries(wf)){
  if(!node?.class_type)continue;
  const title=node._meta?.title||node.class_type,def=info[node.class_type];
  if(!def){errors.push(`缺少节点「${node.class_type}」（节点 ${id}：${title}）。请在 ComfyUI Manager 安装对应的自定义节点，或升级 ComfyUI。`);continue;}
  const required=def.input?.required||{},optional=def.input?.optional||{},inputs=node.inputs||{};
  for(const [name,spec]of Object.entries(required)){
   if(spec?.[0]==='COMFY_AUTOGROW_V3'){
    const template=spec[1]?.template;
    if(template?.input?.required)for(let i=0;i<(template.min??0);i++){const child=template.names?.[i]??`${template.prefix}${i}`;if(!(`${name}.${child}` in inputs))errors.push(`节点 ${id}「${title}」缺少必填输入 ${name}.${child}`);}
    continue;
   }
   if(!(name in inputs))errors.push(`节点 ${id}「${title}」缺少必填输入 ${name}`);
  }
  for(const [name,value]of Object.entries(inputs)){
   if(Array.isArray(value))continue;
   const options=comboOptions(required[name]??optional[name]);
   if(!options||typeof value!=='string')continue;
   if(name==='image'&&mapped.has(id)&&loaders.has(id))continue;
   if(node.class_type==='LoadImage'&&name==='image'){if(!mapped.has(id)&&!options.includes(value))warnings.push(`节点 ${id}「${title}」引用的图片 ${value} 不在 ComfyUI input 目录中，且未映射到人像/服装/姿势槽位`);continue;}
   if(options.includes(value))continue;
   const same=options.find(o=>baseName(o)===baseName(value));
   if(same){inputs[name]=same;fixes.push(`节点 ${id}「${title}」${name}：${value} → ${same}（自动修正路径）`);continue;}
   errors.push(`节点 ${id}「${title}」的 ${name} = ${value} 在本机不存在（通常是模型文件未安装或路径不同）。本机可选：${options.slice(0,12).join('、')||'（空）'}${options.length>12?' …':''}`);
  }
 }
 return {ok:!errors.length,errors,warnings,fixes,fixedJson:fixes.length?JSON.stringify(wf,null,2):undefined};
}
function translateNodeError(er){
 const detail=er?.details?`（${er.details}）`:'';
 switch(er?.type){
  case 'value_not_in_list':return `${er.extra_info?.input_name??'输入'} 的值不在本机可选列表中${detail}——通常是模型文件不存在或路径不同`;
  case 'required_input_missing':return `缺少必填输入 ${er.extra_info?.input_name??''}`;
  case 'invalid_input_type':case 'return_type_mismatch':return `节点连线类型不匹配${detail}`;
  case 'value_bigger_than_max':case 'value_smaller_than_min':return `参数超出范围${detail}`;
  default:return `${er?.message||'校验失败'}${detail}`;
 }
}
function formatComfyPromptError(json,wf,status){
 const parts=[],e=json?.error;
 if(e){
  if(e.type==='missing_node_type'||/does not exist|not found/i.test(String(e.message)))parts.push(`缺少节点类型：${e.details||e.message}。请在 ComfyUI Manager 安装缺失的自定义节点或升级 ComfyUI`);
  else if(e.type==='prompt_no_outputs')parts.push('工作流没有输出节点（SaveImage / PreviewImage）');
  else if(e.type!=='prompt_outputs_failed_validation')parts.push(`${e.message||e.type}${e.details?`：${e.details}`:''}`);
 }
 for(const [id,ne]of Object.entries(json?.node_errors||{})){const title=wf[id]?._meta?.title||ne?.class_type||id;for(const er of ne?.errors||[])parts.push(`节点 ${id}「${title}」：${translateNodeError(er)}`);}
 if(!parts.length)parts.push(json?._raw||`HTTP ${status}`);
 return `[ComfyUI] 提交工作流失败：\n${parts.join('\n')}`;
}
function formatExecutionError(messages,wf){
 const err=(messages||[]).find(m=>m?.[0]==='execution_error')?.[1];
 if(err){
  const title=wf[err.node_id]?._meta?.title||err.node_type||err.node_id,raw=`${err.exception_type||''} ${err.exception_message||''}`;
  if(/out of memory|OutOfMemory|CUDA error: out of memory|allocat/i.test(raw))return `[ComfyUI] 显存不足（节点 ${err.node_id}「${title}」）。\n建议：关闭其他占用显卡的程序；在工作流中把「按姿势图比例确定输出尺寸」节点的 megapixels 从 1.0 调低到 0.6；然后重试。`;
  return `[ComfyUI] 执行出错（节点 ${err.node_id}「${title}」）：${String(err.exception_message||raw).trim().slice(0,400)}`;
 }
 if((messages||[]).some(m=>m?.[0]==='execution_interrupted'))return '[ComfyUI] 任务已被中断（可能在 ComfyUI 界面中点击了取消）';
 return `[ComfyUI] 工作流执行出错：${JSON.stringify(messages||'').slice(0,300)}`;
}
function blobToDataUrl(blob){return new Promise((resolve,reject)=>{const r=new FileReader();r.onerror=()=>reject(new Error('读取生成结果失败'));r.onload=()=>resolve(r.result);r.readAsDataURL(blob);});}
async function uploadImageToComfy(baseUrl,src,prefix,apiKey){
 let dataUrl;
 try{dataUrl=await srcToPngDataUrl(src);}catch{throw new Error(`读取参考图失败：${String(src).slice(0,80)}`);}
 const form=new FormData();
 form.append('image',dataUrlToBlob(dataUrl),`${prefix}_${Date.now()}.png`);form.append('subfolder','pose_studio');form.append('overwrite','true');
 const res=await comfyFetch(baseUrl,'/upload/image',{method:'POST',body:form},apiKey,60000);
 if(!res.ok)throw new Error(`[ComfyUI] 上传参考图失败 (HTTP ${res.status})：${(await res.text()).slice(0,200)}`);
 const json=await res.json();return json.subfolder?`${json.subfolder}/${json.name}`:json.name;
}

export class ComfyTaskError extends Error{constructor(message,task,reason='tracking'){super(message);this.task=task;this.reason=reason;this.name='ComfyTaskError';}}
export class ComfySubmissionRejectedError extends Error{constructor(message,status){super(message);this.status=status;this.name='ComfySubmissionRejectedError';}}
export class ComfySubmissionUnknownError extends Error{constructor(){super('[ComfyUI] 提交结果未知：服务端可能已接受任务，请先检查队列与历史记录，勿直接重复提交。');this.name='ComfySubmissionUnknownError';}}
const abortError=msg=>{const e=new Error(msg);e.name='AbortError';return e;};
function checkSignal(signal){if(signal?.aborted)throw abortError('已停止跟踪，后台任务继续执行');}

function openComfySocket(task,apiKey){
 let socket,stopped=false,failures=0,reconnectTimer,handshakeTimer;
 const session={connection:'connecting',onMessage(){},onConnection(){},close(){stopped=true;clearTimeout(reconnectTimer);disconnect();}};
 const set=state=>{session.connection=state;session.onConnection(state);};
 const disconnect=()=>{clearTimeout(handshakeTimer);if(socket){socket.onopen=socket.onclose=socket.onerror=socket.onmessage=null;try{socket.close();}catch{}socket=undefined;}};
 const reconnect=()=>{disconnect();if(stopped)return;failures++;set(failures>=3?'degraded':'reconnecting');reconnectTimer=setTimeout(connect,Math.min(30000,1000*2**Math.min(failures-1,5)));};
 const connect=()=>{
  if(stopped)return;set(failures?'reconnecting':'connecting');
  try{
   const u=new URL(task.baseUrl,window.location.href);
   u.protocol=u.protocol==='https:'?'wss:':'ws:';u.pathname=`${u.pathname.replace(/\/+$/,'')}/ws`;u.search=new URLSearchParams({clientId:task.clientId}).toString();u.hash='';
   socket=String(apiKey||'').trim()?new WebSocket(u.toString(),['comfyui',`comfyui-auth.${String(apiKey).trim()}`]):new WebSocket(u.toString());
   handshakeTimer=setTimeout(reconnect,8000);
   socket.onopen=()=>{clearTimeout(handshakeTimer);failures=0;set('connected');};
   socket.onclose=reconnect;socket.onerror=reconnect;
   socket.onmessage=e=>{if(typeof e.data!=='string')return;let msg;try{msg=JSON.parse(e.data);}catch{return;}session.onMessage(msg);};
  }catch{reconnect();}
 };
 connect();return session;
}

export function resumeComfyTask(params){return trackComfyTask(params);}

async function trackComfyTask(params,workflow={},existingSocket){
 const {task,apiKey,signal}=params,ctrl=new AbortController(),abort=()=>ctrl.abort();
 signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
 const deadline=setTimeout(abort,Math.max(1,params.timeoutSec||600)*1000);
 let progress={stage:'queue',message:'正在确认 ComfyUI 任务状态…',connection:'connecting'};
 const report=next=>{progress={...progress,...next};params.onProgress?.(progress);};
 let socket=existingSocket,nextHistoryAt=0,nextQueueAt=0,queueRequested=true,terminalRetries=0,terminalFailure,wakePending=false,wakeWait;
 const wake=()=>{wakePending=true;wakeWait?.();};
 const reconcile=()=>{nextHistoryAt=0;queueRequested=true;wake();};
 const activate=()=>{if(document.visibilityState==='visible')reconcile();};
 const interval=()=>socket?.connection==='connected'?30000:3000;
 const wait=ms=>{
  if(wakePending){wakePending=false;return Promise.resolve();}
  return new Promise((resolve,reject)=>{
   const done=()=>{clearTimeout(timer);ctrl.signal.removeEventListener('abort',stop);wakeWait=undefined;};
   const finish=()=>{done();wakePending=false;resolve();};
   const stop=()=>{done();reject(abortError('已停止跟踪'));};
   const timer=setTimeout(finish,Math.max(0,ms));wakeWait=finish;
   ctrl.signal.addEventListener('abort',stop,{once:true});if(ctrl.signal.aborted)stop();
  });
 };
 async function read(path,image=false){
  const request=new AbortController(),stop=()=>request.abort();
  ctrl.signal.addEventListener('abort',stop,{once:true});if(ctrl.signal.aborted)stop();
  const timer=setTimeout(stop,image?60000:15000);
  try{
   const res=await fetch(`${task.baseUrl}${path}`,{headers:comfyHeaders(task.baseUrl,{},apiKey),signal:request.signal,credentials:'same-origin'});
   if(res.status===401||res.status===403)throw new ComfyTaskError(`[ComfyUI] 访问被拒绝 (HTTP ${res.status})，请检查凭据和来源后恢复任务。`,task,'auth');
   if(!res.ok)throw new Error(`HTTP ${res.status}`);
   return image?await res.blob():await res.json();
  }finally{clearTimeout(timer);ctrl.signal.removeEventListener('abort',stop);}
 }
 try{
  checkSignal(ctrl.signal);
  socket??=openComfySocket(task,apiKey);
  socket.onMessage=msg=>{
   const d=msg?.data;
   if(msg?.type==='status'){queueRequested=true;wake();return;}
   if(!d||d.prompt_id!==task.promptId)return;
   if(msg.type==='executing'&&d.node){const title=workflow[d.node]?._meta?.title||workflow[d.node]?.class_type||d.node;report({stage:'running',message:`正在执行：${title}`,percent:undefined});}
   else if(msg.type==='progress'&&d.max>0)report({stage:'running',message:`当前节点（${d.value}/${d.max}）`,percent:Math.round(d.value/d.max*100)});
   else if(['execution_start','execution_cached','executed'].includes(msg.type))report({stage:'running',message:msg.type==='execution_cached'?'正在复用已缓存节点…':msg.type==='executed'?'节点已完成，继续执行工作流…':'ComfyUI 开始执行任务…',percent:undefined});
   if(['execution_success','execution_error','execution_interrupted'].includes(msg.type)||(msg.type==='executing'&&d.node===null)){
    if(msg.type==='execution_error'||msg.type==='execution_interrupted')terminalFailure=[[msg.type,d]];
    terminalRetries=6;reconcile();
   }
  };
  socket.onConnection=connection=>{const was=progress.connection==='connected';report({connection});if(connection==='connected'||was)reconcile();else{nextHistoryAt=Math.min(nextHistoryAt,Date.now()+3000);wake();}};
  report({connection:socket.connection});
  window.addEventListener('online',reconcile);document.addEventListener('visibilitychange',activate);
  for(;;){
   checkSignal(ctrl.signal);
   if(Date.now()>=nextHistoryAt){
    nextHistoryAt=Date.now()+interval();
    let item;
    try{item=(await read(`/history/${encodeURIComponent(task.promptId)}`))?.[task.promptId];}
    catch(error){if(error instanceof ComfyTaskError)throw error;checkSignal(ctrl.signal);report({message:'任务状态查询暂时失败，正在重试…'});nextHistoryAt=Math.min(nextHistoryAt,Date.now()+3000);}
    if(item?.status?.status_str==='error')throw new ComfyTaskError(formatExecutionError(item.status.messages,workflow),task,'failed');
    if(!item||(item.status&&item.status.completed===false&&item.status.status_str!=='success')){
     if(terminalRetries>0){terminalRetries--;nextHistoryAt=Math.min(nextHistoryAt,Date.now()+500);}
     else if(terminalFailure)throw new ComfyTaskError(formatExecutionError(terminalFailure,workflow),task,'failed');
     queueRequested=true;
    }else{
     let out;
     for(const nodeOut of Object.values(item.outputs||{}))for(const im of nodeOut?.images||[])if(im?.filename&&(!out||(im.type==='output'&&out.type!=='output')))out=im;
     if(!out){if(item.status?.completed)throw new ComfyTaskError('[ComfyUI] 工作流完成但没有输出图片，请检查 SaveImage 节点。',task,'failed');nextHistoryAt=Math.min(nextHistoryAt,Date.now()+3000);}
     else{
      report({stage:'download',message:'正在获取生成结果…',percent:undefined});
      const qs=new URLSearchParams({filename:out.filename,subfolder:out.subfolder||'',type:out.type||'output'});
      let blob;
      try{blob=await read(`/view?${qs}`,true);}catch(error){if(error instanceof ComfyTaskError)throw error;checkSignal(ctrl.signal);report({message:'图片下载暂时失败，正在重试…'});nextHistoryAt=Math.min(nextHistoryAt,Date.now()+3000);}
      if(blob){
       if(!blob.size||!blob.type.startsWith('image/'))throw new ComfyTaskError('[ComfyUI] 生成结果不是有效图片，可恢复后重新下载。',task);
       const imageUrl=await blobToDataUrl(blob);checkSignal(ctrl.signal);
       return {imageUrl,modelUsed:'ComfyUI 工作流',providerUsed:'comfyui'};
      }
     }
    }
   }
   if(queueRequested&&Date.now()>=nextQueueAt){
    queueRequested=false;nextQueueAt=Date.now()+3000;
    try{
     const q=await read('/queue'),pending=(q?.queue_pending||[]).findIndex(x=>x?.[1]===task.promptId);
     if(pending>=0)report({stage:'queue',message:`排队中，前方还有 ${pending+(q.queue_running?.length||0)} 个任务`,percent:undefined});
     else if((q?.queue_running||[]).some(x=>x?.[1]===task.promptId)){if(progress.stage!=='running')report({stage:'running',message:'ComfyUI 正在执行任务…',percent:undefined});}
     else report({message:'暂未在队列或历史中找到任务，继续确认…',percent:undefined});
    }catch(error){if(error instanceof ComfyTaskError)throw error;checkSignal(ctrl.signal);report({message:'队列查询暂时失败，正在等待任务状态…'});}
   }
   await wait(Math.min(nextHistoryAt,queueRequested?nextQueueAt:Infinity)-Date.now());
  }
 }catch(error){
  if(error instanceof ComfyTaskError)throw error;
  const message=ctrl.signal.aborted?signal?.aborted?'[ComfyUI] 已停止跟踪，后台任务继续执行，可恢复查看。':'[ComfyUI] 等待结果超时，后台任务继续执行，可恢复查看。':error instanceof Error?error.message:'[ComfyUI] 跟踪任务失败，可恢复查看。';
  throw new ComfyTaskError(message,task,ctrl.signal.aborted&&!signal?.aborted?'timeout':'tracking');
 }finally{
  socket?.close();clearTimeout(deadline);signal?.removeEventListener('abort',abort);
  window.removeEventListener('online',reconcile);document.removeEventListener('visibilitychange',activate);
 }
}

async function generateWithComfyUi({recipe,prompt,config,baseUrl,apiKey,onProgress,onSubmitting,onSubmitted,signal}){
 const report=onProgress??(()=>{}),cp=config.comfyuiParams,timeoutSec=Math.max(60,cp.timeoutSec||600);
 const parsedInfo=parseComfyWorkflowNodes(cp.workflowJson);
 if(!parsedInfo.valid)throw new Error(`[ComfyUI] ${parsedInfo.error||'工作流 JSON 无效'}`);
 report({stage:'check',message:'正在检查 ComfyUI 服务与模型…'});
 await testComfyConnection(baseUrl,apiKey);
 const schemas=await fetchComfyObjectInfo(baseUrl,apiKey,cp.workflowJson);
 const extraNodes=getWorkflowImages(cp.workflowJson,[cp.portraitNodeId,cp.costumeNodeId,cp.poseNodeId,cp.stitchedNodeId],schemas);
 const extraImages=recipe.workflowImagesIdentity===workflowIdentity(cp.workflowJson)?recipe.workflowImages||{}:{};
 const selectedJson=applyWorkflowOverrides(cp.workflowJson,cp.parameterOverrides,schemas);
 const check=await checkComfyWorkflow(baseUrl,apiKey,selectedJson,[cp.portraitNodeId,cp.costumeNodeId,cp.poseNodeId,cp.stitchedNodeId,
  ...extraNodes.filter(n=>extraImages[n.nodeId]?.url||(n.optional&&n.role==='character_sheet')).map(n=>n.nodeId)],schemas);
 if(!check.ok)throw new Error(`[ComfyUI] 工作流与本机不匹配：\n${check.errors.join('\n')}`);
 const workflow=JSON.parse(check.fixedJson??selectedJson);
 const slots=[
  {nodeId:cp.portraitNodeId,src:recipe.portrait?recipe.portrait.原图||recipe.portrait.缩略图:null,prefix:'studio_portrait',label:'人像'},
  {nodeId:cp.costumeNodeId,src:recipe.costume?recipe.costume.预览图||recipe.costume.原图||recipe.costume.缩略图:null,prefix:'studio_costume',label:'服装'},
  {nodeId:cp.poseNodeId,src:recipe.pose?poseImagePath(recipe.pose):null,prefix:'studio_pose',label:'姿势'},
 ];
 const combo=validateReferenceCombinations(cp.workflowJson,[...slots.filter(s=>s.src&&s.nodeId&&s.nodeId!=='none').map(s=>s.nodeId),...extraNodes.filter(n=>extraImages[n.nodeId]?.url).map(n=>n.nodeId)]);
 if(combo)throw new Error(`[ComfyUI] ${combo}`);
 const invalid=slots.filter(s=>s.nodeId&&s.nodeId!=='none'&&!parsedInfo.imageNodes.some(n=>n.id===s.nodeId));
 if(invalid.length)throw new Error(`[ComfyUI] ${invalid.map(s=>s.label).join('、')}节点映射已失效，请重新识别或选择节点`);
 const missing=slots.filter(s=>s.nodeId&&s.nodeId!=='none'&&!s.src&&parsedInfo.imageNodes.find(n=>n.id===s.nodeId)?.emptyValue===undefined);
 if(missing.length)throw new Error(`[ComfyUI] 请先选择或上传：${missing.map(s=>s.label).join('、')}`);
 for(const slot of slots){
  if(!slot.nodeId||slot.nodeId==='none'||!workflow[slot.nodeId]?.inputs)continue;
  if(!slot.src){const empty=parsedInfo.imageNodes.find(n=>n.id===slot.nodeId)?.emptyValue;if(empty!==undefined){workflow[slot.nodeId].inputs.image=empty;continue;}throw new Error(`当前工作流需要「${slot.label}」参考图（节点 ${slot.nodeId}），请先在图库中选择`);}
  report({stage:'upload',message:`正在上传${slot.label}参考图…`});
  workflow[slot.nodeId].inputs.image=await uploadImageToComfy(baseUrl,slot.src,slot.prefix,apiKey);
 }
 for(const node of extraNodes){
  const image=extraImages[node.nodeId];
  if(!image?.url){if(node.optional&&node.role==='character_sheet')workflow[node.nodeId].inputs.image='无';continue;}
  report({stage:'upload',message:`正在上传${node.label}…`});
  workflow[node.nodeId].inputs.image=await uploadImageToComfy(baseUrl,image.url,'studio_reference',apiKey);
 }
 if(cp.stitchedNodeId&&cp.stitchedNodeId!=='none'&&workflow[cp.stitchedNodeId]?.inputs){
  report({stage:'upload',message:'正在上传参考拼图…'});
  workflow[cp.stitchedNodeId].inputs.image=await uploadImageToComfy(baseUrl,await stitchRecipeCanvas(recipe),'studio_stitched',apiKey);
 }
 if(cp.promptNodeId&&cp.promptNodeId!=='none'&&workflow[cp.promptNodeId]?.inputs){
  const inputs=workflow[cp.promptNodeId].inputs;
  for(const field of ['prompt','text','string','positive'])if(typeof inputs[field]==='string'){inputs[field]=prompt;break;}
 }
 if(cp.randomizeSeed){
  const seed=Math.floor(Math.random()*90000000000000)+1000000;
  for(const node of Object.values(workflow)){if(!node?.inputs)continue;if(typeof node.inputs.seed==='number')node.inputs.seed=seed;if(typeof node.inputs.noise_seed==='number')node.inputs.noise_seed=seed;}
 }
 checkSignal(signal);
 await onSubmitting?.({workflow:JSON.parse(JSON.stringify(workflow))});
 checkSignal(signal);
 const clientId=`pose_studio_${crypto.randomUUID()}`,submittedAt=Date.now();
 report({stage:'queue',message:'正在提交工作流…'});
 const socket=openComfySocket({baseUrl,clientId},apiKey);
 try{
  let promptRes,promptJson;
  const submission=new AbortController(),abortSubmission=()=>submission.abort();
  signal?.addEventListener('abort',abortSubmission,{once:true});if(signal?.aborted)abortSubmission();
  const timer=setTimeout(abortSubmission,60000);
  try{
   const headers=comfyHeaders(baseUrl,{headers:{'Content-Type':'application/json'}},apiKey);
   promptRes=await fetch(`${baseUrl}/prompt`,{method:'POST',headers,body:JSON.stringify({prompt:workflow,client_id:clientId}),signal:submission.signal,credentials:'same-origin'});
   promptJson=await readJsonSafe(promptRes);
  }catch{throw new ComfySubmissionUnknownError();}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abortSubmission);}
  if(!promptRes.ok){if(promptRes.status>=500)throw new ComfySubmissionUnknownError();throw new ComfySubmissionRejectedError(formatComfyPromptError(promptJson,workflow,promptRes.status),promptRes.status);}
  if(typeof promptJson?.prompt_id!=='string'||!promptJson.prompt_id)throw new ComfySubmissionUnknownError();
  const task={promptId:promptJson.prompt_id,clientId,baseUrl,submittedAt};
  try{await onSubmitted?.(task);}catch{throw new ComfyTaskError('[ComfyUI] 任务已提交，但保存恢复记录失败。请保留任务编号后恢复，勿重复提交。',task,'storage');}
  return await trackComfyTask({task,apiKey,timeoutSec,onProgress,signal},workflow,socket);
 }finally{socket.close();}
}

export async function generateCharacterImage({recipe,prompt,config,onProgress,onSubmitting,onSubmitted,signal}){
 const provider=config.activeProvider,pCfg=config.providers[provider],apiKey=String(pCfg.apiKey||'').trim();
 if(provider!=='comfyui'&&!apiKey)throw new Error(`请先配置 ${PROVIDER_META[provider].name} 的 API Key`);
 const rawSources=[
  recipe.portrait&&(recipe.portrait.原图||recipe.portrait.缩略图),
  recipe.costume&&(recipe.costume.预览图||recipe.costume.原图||recipe.costume.缩略图),
  recipe.pose&&poseImagePath(recipe.pose),
  ...(recipe.extraImages||[]).map(x=>x.url),
  ...(provider==='comfyui'&&recipe.workflowImagesIdentity===workflowIdentity(config.comfyuiParams.workflowJson)?Object.values(recipe.workflowImages||{}).map(i=>i.url):[]),
 ].filter(Boolean);
 if(!rawSources.length)throw new Error('请先选择或上传至少 1 张参考图');
 const model=pCfg.model==='custom'?String(pCfg.customModel||'').trim():pCfg.model;
 if(provider!=='comfyui'&&!model)throw new Error('请选择或填写有效的模型名称');
 const baseUrl=(String(pCfg.baseUrl||'').trim()||PROVIDER_META[provider].defaultBaseUrl).replace(/\/+$/,'');
 if(provider==='comfyui')return generateWithComfyUi({recipe,prompt,config,baseUrl,apiKey,onProgress,onSubmitting,onSubmitted,signal});
 const needBase64=config.imagePassMode==='base64'||config.sendStitchedSheet||(provider==='gemini'&&config.geminiParams.endpointMode==='native')||(provider==='gpt'&&config.gptParams.endpointMode==='images_edits');
 const imageRefs=needBase64?await Promise.all(rawSources.map(srcToPngDataUrl)):rawSources.map(toPublicHttpsUrl);
 const allRefs=config.sendStitchedSheet?[...imageRefs,await stitchRecipeCanvas(recipe)]:imageRefs;
 const json_=headers=>({'Content-Type':'application/json',...headers});
 let res;
 if(provider==='gpt'){
  const g=config.gptParams,v1=baseUrl.endsWith('/v1')?baseUrl:`${baseUrl}/v1`,auth={Authorization:`Bearer ${apiKey}`};
  if(g.endpointMode==='images_edits_json'){
   const payload={model,prompt,images:allRefs.map(ref=>({image_url:ref}))};
   if(g.size!=='auto')payload.size=g.size;if(g.quality!=='auto')payload.quality=g.quality;if(g.inputFidelity)payload.input_fidelity=g.inputFidelity;
   if(g.background!=='auto')payload.background=g.background;if(g.outputFormat)payload.output_format=g.outputFormat;if(g.moderation!=='auto')payload.moderation=g.moderation;
   res=await smartFetch(`${v1}/images/edits`,{method:'POST',headers:json_(auth),body:JSON.stringify(payload)},config.useProxy);
  }else if(g.endpointMode==='images_edits'){
   const fd=new FormData();fd.append('model',model);fd.append('prompt',prompt);
   allRefs.forEach((du,i)=>fd.append('image[]',dataUrlToBlob(du),`ref_${i+1}.png`));
   if(g.size!=='auto')fd.append('size',g.size);if(g.quality!=='auto')fd.append('quality',g.quality);if(g.inputFidelity)fd.append('input_fidelity',g.inputFidelity);
   if(g.background!=='auto')fd.append('background',g.background);if(g.outputFormat)fd.append('output_format',g.outputFormat);if(g.moderation!=='auto')fd.append('moderation',g.moderation);
   res=await smartFetch(`${v1}/images/edits`,{method:'POST',headers:auth,body:fd},config.useProxy);
  }else if(g.endpointMode==='responses'){
   const tool={type:'image_generation'};
   if(g.size!=='auto')tool.size=g.size;if(g.quality!=='auto')tool.quality=g.quality;if(g.background!=='auto')tool.background=g.background;if(g.inputFidelity)tool.input_fidelity=g.inputFidelity;if(g.outputFormat)tool.output_format=g.outputFormat;
   res=await smartFetch(`${v1}/responses`,{method:'POST',headers:json_(auth),body:JSON.stringify({model,input:[{role:'user',content:[...allRefs.map(ref=>({type:'input_image',image_url:ref})),{type:'input_text',text:prompt}]}],tools:[tool]})},config.useProxy);
  }else{
   res=await smartFetch(`${v1}/chat/completions`,{method:'POST',headers:json_(auth),body:JSON.stringify({model,messages:[{role:'user',content:[{type:'text',text:prompt},...allRefs.map(ref=>({type:'image_url',image_url:{url:ref}}))]}],modalities:['text','image']})},config.useProxy);
  }
 }else if(provider==='gemini'){
  const gm=config.geminiParams;
  if(gm.endpointMode==='native'){
   const root=baseUrl.replace(/\/v1(?:beta)?$/,''),url=`${root}/v1beta/models/${encodeURIComponent(model)}:generateContent`;
   const parts=[...allRefs.map(du=>({inlineData:{mimeType:'image/png',data:du.split(',')[1]}})),{text:prompt}];
   const imageConfig={aspectRatio:gm.aspectRatio};if(model.includes('gemini-3')&&gm.imageSize)imageConfig.imageSize=gm.imageSize;
   res=await smartFetch(url,{method:'POST',headers:json_({'x-goog-api-key':apiKey}),body:JSON.stringify({contents:[{role:'user',parts}],generationConfig:{responseModalities:['TEXT','IMAGE'],imageConfig}})},config.useProxy);
  }else{
   const v1=baseUrl.endsWith('/v1')?baseUrl:`${baseUrl}/v1`;
   res=await smartFetch(`${v1}/chat/completions`,{method:'POST',headers:json_({Authorization:`Bearer ${apiKey}`}),body:JSON.stringify({model,messages:[{role:'user',content:[{type:'text',text:`${prompt}\n(Output aspect ratio: ${gm.aspectRatio}, resolution: ${gm.imageSize})`},...allRefs.map(ref=>({type:'image_url',image_url:{url:ref}}))]}],modalities:['text','image']})},config.useProxy);
  }
 }else if(provider==='qwen'){
  const qw=config.qwenParams,endpoint=baseUrl.includes('/services/aigc/')?baseUrl:`${baseUrl.replace(/\/api\/v1$/,'')}/api/v1/services/aigc/multimodal-generation/generation`;
  res=await smartFetch(endpoint,{method:'POST',headers:json_({Authorization:`Bearer ${apiKey}`}),body:JSON.stringify({model,input:{messages:[{role:'user',content:[...imageRefs.map(ref=>({image:ref})),{text:prompt}]}]},
   parameters:{size:qw.size,n:qw.n||1,prompt_extend:qw.promptExtend,watermark:qw.watermark,...(String(qw.negativePrompt||'').trim()?{negative_prompt:qw.negativePrompt.trim()}:{})}})},config.useProxy);
 }else{
  const db=config.doubaoParams;let endpoint=baseUrl;
  if(!endpoint.endsWith('/images/generations'))endpoint=endpoint.endsWith('/api/v3')||endpoint.endsWith('/v1')?`${endpoint}/images/generations`:`${endpoint}/api/v3/images/generations`;
  res=await smartFetch(endpoint,{method:'POST',headers:json_({Authorization:`Bearer ${apiKey}`}),body:JSON.stringify({model,prompt,image:allRefs,size:db.size,sequential_image_generation:db.sequentialImageGeneration,watermark:db.watermark,response_format:db.responseFormat})},config.useProxy);
 }
 const json=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error(`[${PROVIDER_META[provider].shortName}] ${json?.error?.message||json?.message||json?.code||`请求失败 (HTTP ${res.status})`}`);
 const imageUrl=extractUniversalImage(json);
 if(!imageUrl)throw new Error(`接口已响应但未解析到图片输出：${(json?.choices?.[0]?.message?.content||json?.output?.choices?.[0]?.message?.content?.[0]?.text||JSON.stringify(json)).slice(0,260)}`);
 return {imageUrl,modelUsed:model,providerUsed:provider};
}

export function comparisonReferences(result){
 const snapshot=result?.snapshot;if(!snapshot?.recipe)return [];
 const {recipe}=snapshot,refs=[],add=(id,label,url)=>{if(url)refs.push({id,label,url:referenceImageUrl(url)});};
 if(recipe.portrait)add('portrait',`人像 · ${recipe.portrait.标题||recipe.portrait.发型名称||''}`,recipe.portrait.原图||recipe.portrait.缩略图);
 if(recipe.costume)add('costume',`服装 · ${recipe.costume.服装名称}`,recipe.costume.原图||recipe.costume.预览图||recipe.costume.缩略图);
 if(recipe.pose)add('pose',`姿势 · ${recipe.pose.姿势名称}${recipe.pose.useDepth?'（深度图）':''}`,poseImagePath(recipe.pose));
 recipe.extraImages?.forEach((image,i)=>add(`extra:${i}`,`附加参考 · ${image.name}`,image.url));
 return refs;
}
