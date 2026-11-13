// Character studio generation engine: local CLI/OAuth bridges (AGY, Grok subscription)
// and browser-local API key providers (Gemini, Grok API, OpenAI GPT, Qwen, Doubao).
export const MEDIA_BASE='/api/v1/asset-center/pose-gallery/media/';
let csrfProvider=()=>'';
export function setCsrfProvider(fn){csrfProvider=typeof fn==='function'?fn:()=>'';}

const LEGACY_COSTUME_MEDIA_PREFIX='/api/v1/asset-center/costumes/';
const REMOTE_COSTUME_PREFIXES=[
 ['https://ai-costume-gallery.pages.dev/thumbs/costume/','thumbs/costume/'],
 ['https://ai-costume-gallery.pages.dev/img/costume/','img/costume/'],
 ['https://ai-costume-gallery.pages.dev/thumbs/','thumbs/costume/'],
 ['https://ai-costume-gallery.pages.dev/img/','img/costume/'],
 ['https://ai-costume-anime-gallery.pages.dev/thumbs/','thumbs/costumes/gia-anime/'],
 ['https://ai-costume-anime-gallery.pages.dev/img/','img/costumes/gia-anime/'],
 ['https://charadb-2fi.pages.dev/thumb/','thumbs/costumes/charadb/'],
 ['https://charadb-2fi.pages.dev/img/','img/costumes/charadb/'],
];
export function localizeCostumePath(src){
 const raw=String(src||'').trim();
 if(!raw)return '';
 if(raw.startsWith(LEGACY_COSTUME_MEDIA_PREFIX))return raw;
 if(raw.startsWith(MEDIA_BASE))return raw.slice(MEDIA_BASE.length);
 if(raw.startsWith('https://ai-costume-anime-gallery.pages.dev/png/')){
  const tail=raw.slice('https://ai-costume-anime-gallery.pages.dev/png/'.length);
  const stem=tail.replace(/\.[^./]+$/,'');
  return stem?`img/costumes/gia-anime/${stem}.webp`:'';
 }
 for(const [remote,local]of REMOTE_COSTUME_PREFIXES){
  if(raw.startsWith(remote))return local+raw.slice(remote.length);
 }
 if(/^(https?:\/\/|\/\/|data:|blob:)/i.test(raw))return '';
 const clean=raw.replace(/^\/+/,'');
 return (clean.startsWith('thumbs/')||clean.startsWith('img/'))?clean:'';
}
export function localCostumeImageUrl(src){
 const norm=localizeCostumePath(src);
 if(!norm)return '';
 return norm.startsWith('/')?norm:MEDIA_BASE+norm;
}
export function sanitizeCostumeItem(item){
 if(!item||typeof item!=='object'||item.source==='upload')return item;
 const next={...item};
 if(Array.isArray(next.views)){
  next.views=next.views.map(v=>{
   const vt=localizeCostumePath(v?.缩略图),vp=localizeCostumePath(v?.预览图),vo=localizeCostumePath(v?.原图);
   const thumb=vt||vp||vo,orig=vo||vp||vt,prev=vp||orig||thumb;
   return thumb&&orig?{...v,缩略图:thumb,预览图:prev,原图:orig}:null;
  }).filter(Boolean);
 }
 const lt=localizeCostumePath(next.缩略图),lp=localizeCostumePath(next.预览图),lo=localizeCostumePath(next.原图);
 const thumb=lt||lp||lo||next.views?.[0]?.缩略图||'',orig=lo||lp||lt||next.views?.[0]?.原图||'',prev=lp||orig||thumb;
 if(!thumb||!orig)return null;
 next.缩略图=thumb;next.预览图=prev;next.原图=orig;
 return next;
}

export function referenceImageUrl(src){
 const value=String(src||'').trim();
 if(!value)return '';
 const mappedCostume= /^https:\/\//i.test(value)?localizeCostumePath(value):'';
 if(mappedCostume)return mappedCostume.startsWith('/')?mappedCostume:MEDIA_BASE+mappedCostume;
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

export const PROVIDER_ORDER=['agy_auth','grok_auth','codex_auth','gemini','grok','gpt','qwen','doubao'];
export const SETTINGS_GROUPS=[
 {id:'google',name:'Google · AGY / Gemini',modes:['agy_auth','gemini']},
 {id:'xai',name:'xAI · Grok',modes:['grok_auth','grok']},
 {id:'gpt',name:'OpenAI GPT Image',modes:['codex_auth','gpt']},
 {id:'qwen',name:'阿里云百炼 Qwen',modes:['qwen']},
 {id:'doubao',name:'字节火山方舟 Doubao',modes:['doubao']},
];
export const PROVIDER_META={
 agy_auth:{id:'agy_auth',name:'AGY 授权登录 (Google Antigravity)',shortName:'AGY 授权',modeLabel:'AGY 授权登录',modeHint:'本机 Antigravity OAuth · 免填 Key',
  authMode:'oauth',authVendor:'agy',defaultBaseUrl:'',docUrl:'https://ai.google.dev/gemini-api/docs/image-generation',
  models:[['image-generator','image-generator（AGY 内置生图智能体 · 推荐）'],['custom','指定协调模型 ID（高级）']]},
 grok_auth:{id:'grok_auth',name:'Grok 授权登录 (xAI 订阅 / CLI)',shortName:'Grok 授权',modeLabel:'Grok 授权登录',modeHint:'本机 grok CLI 登录态 · ~/.grok/auth.json',
  authMode:'oauth',authVendor:'grok',defaultBaseUrl:'https://api.x.ai/v1',docUrl:'https://docs.x.ai/docs/guides/image-generations',
  models:[['image_edit','image_edit（终端 grok CLI 内置生图 · 推荐）'],['grok-imagine-image-2.0','grok-imagine-image-2.0（Grok 订阅直连多图合成）'],['grok-imagine-image','grok-imagine-image（Grok 订阅直连）'],['custom','指定 grok CLI 协调模型 ID（高级）']]},
 codex_auth:{id:'codex_auth',name:'Codex 订阅授权 (OpenAI GPT Image)',shortName:'Codex 授权',modeLabel:'Codex 订阅授权',modeHint:'本机 ChatGPT 订阅登录 · 免填 API Key',
  authMode:'oauth',authVendor:'codex',defaultBaseUrl:'',docUrl:'https://learn.chatgpt.com/docs/image-generation',
  models:[['image-generation','Codex 内置生图（GPT Image 2）']]},
 gemini:{id:'gemini',name:'Google Gemini (API 接口)',shortName:'Gemini API',modeLabel:'Gemini API 接口',modeHint:'Google AI Studio API Key',
  authMode:'apikey',defaultBaseUrl:'https://generativelanguage.googleapis.com',docUrl:'https://ai.google.dev/gemini-api/docs/image-generation',
  keyPlaceholder:'输入 AIza... API Key（仅保存在本地浏览器）',
  models:[['gemini-3.1-flash-image-preview','gemini-3.1-flash-image-preview（Nano Banana 2 · 推荐）'],['gemini-3-pro-image-preview','gemini-3-pro-image-preview（Nano Banana Pro）'],['gemini-2.5-flash-image'],['gemini-2.5-flash-image-preview'],['custom','自定义模型 ID']]},
 grok:{id:'grok',name:'xAI Grok (API 接口)',shortName:'Grok API',modeLabel:'Grok API 接口',modeHint:'xAI 按量计费 API Key（与订阅登录隔离）',
  authMode:'apikey',defaultBaseUrl:'https://api.x.ai/v1',docUrl:'https://docs.x.ai/docs/guides/image-generations',
  keyPlaceholder:'输入 xai-... API Key（仅保存在本地浏览器）',
  models:[['grok-imagine-image-2.0','grok-imagine-image-2.0（多图编辑 ≤5 张 · 推荐）'],['grok-imagine-image'],['grok-2-image-1212','grok-2-image-1212（仅文生图）'],['custom','自定义模型 ID']]},
 gpt:{id:'gpt',name:'OpenAI GPT Image',shortName:'GPT',modeLabel:'GPT Image API 接口',modeHint:'使用 OpenAI API Key 生图',
  authMode:'apikey',defaultBaseUrl:'https://api.openai.com/v1',docUrl:'https://platform.openai.com/docs/guides/image-generation',
  keyPlaceholder:'输入 sk-... API Key（仅保存在本地浏览器）',
  models:[['gpt-image-2.5'],['gpt-image-2.5-sunburst'],['gpt-image-2.5-flare'],['gpt-image-2'],['gpt-image-1.5'],['gpt-image-1'],['custom','自定义模型 ID']]},
 qwen:{id:'qwen',name:'阿里云百炼 Qwen',shortName:'Qwen',modeLabel:'API 接口',modeHint:'DashScope API Key',
  authMode:'apikey',defaultBaseUrl:'https://dashscope.aliyuncs.com',docUrl:'https://help.aliyun.com/zh/model-studio/qwen-image-edit-api',
  keyPlaceholder:'输入 DashScope sk-... API Key（仅保存在本地浏览器）',
  models:[['qwen-image-3.0-pro'],['qwen-image-2.1-pro'],['qwen-image-2.1-turbo'],['qwen-image-2.0-pro'],['qwen-image-edit-plus'],['custom','自定义模型 ID']]},
 doubao:{id:'doubao',name:'字节火山方舟 Doubao',shortName:'Doubao',modeLabel:'API 接口',modeHint:'火山方舟 API Key',
  authMode:'apikey',defaultBaseUrl:'https://ark.cn-beijing.volces.com',docUrl:'https://www.volcengine.com/docs/82379/1541523',
  keyPlaceholder:'输入火山方舟 API Key（仅保存在本地浏览器）',
  models:[['doubao-seedream-5-0'],['doubao-seedream-5-0-lite'],['doubao-seedream-4-5-251128'],['doubao-seedream-4-0-250828'],['doubao-seededit-3-0-i2i-250628'],['custom','自定义模型 ID / Endpoint']]},
};
for(const meta of Object.values(PROVIDER_META))meta.models=meta.models.map(([value,label])=>({value,label:label||value}));
export const isAuthProvider=id=>PROVIDER_META[id]?.authMode==='oauth';
export const groupForProvider=id=>SETTINGS_GROUPS.find(g=>g.modes.includes(id))||SETTINGS_GROUPS[0];

export const SETTINGS_MODALITIES=[
 {id:'image',label:'图',subtitle:'生图接口与授权'},
 {id:'video',label:'视频',subtitle:'视频接口与授权'},
];
export const VIDEO_PROVIDER_ORDER=['grok_video_auth','grok_video','doubao_video','gemini_video','qwen_video','openai_video'];
export const VIDEO_SETTINGS_GROUPS=[
 {id:'xai_video',name:'xAI · Grok Video',modes:['grok_video_auth','grok_video']},
 {id:'doubao_video',name:'字节火山方舟 Seedance',modes:['doubao_video']},
 {id:'google_video',name:'Google · Veo (Gemini)',modes:['gemini_video']},
 {id:'qwen_video',name:'阿里云百炼 通义万相 Wan',modes:['qwen_video']},
 {id:'openai_video',name:'OpenAI Sora / 兼容网关',modes:['openai_video']},
];
export const VIDEO_PROVIDER_META={
 grok_video_auth:{id:'grok_video_auth',name:'Grok 视频授权登录 (xAI 订阅)',shortName:'Grok 授权',modeLabel:'Grok 授权登录',modeHint:'本机 grok CLI 订阅登录 · ~/.grok/auth.json',
  authMode:'oauth',authVendor:'grok',modality:'video',defaultBaseUrl:'https://api.x.ai/v1',docUrl:'https://docs.x.ai/docs/guides/video-generations',
  models:[['grok-imagine-video-1.5','grok-imagine-video-1.5（首尾帧/关键帧/14图参考 · 最高 15s 1080p · 推荐）'],['grok-imagine-video-1.5-lite','grok-imagine-video-1.5-lite（轻量快速 · 首帧/参考 · 最高 15s）'],['grok-imagine-video','grok-imagine-video（经典模型 · 视频编辑/续接）']]},
 grok_video:{id:'grok_video',name:'xAI Grok Video (API 接口)',shortName:'Grok API',modeLabel:'Grok API 接口',modeHint:'xAI 按量计费 API Key（与订阅登录隔离）',
  authMode:'apikey',modality:'video',defaultBaseUrl:'https://api.x.ai/v1',docUrl:'https://docs.x.ai/docs/guides/video-generations',
  keyPlaceholder:'输入 xai-... API Key（仅保存在本地浏览器）',
  models:[['grok-imagine-video-1.5','grok-imagine-video-1.5（首尾帧/关键帧/14图参考 · 最高 15s 1080p · 推荐）'],['grok-imagine-video-1.5-lite','grok-imagine-video-1.5-lite（轻量快速 · 首帧/参考 · 最高 15s）'],['grok-imagine-video','grok-imagine-video（经典模型 · 视频编辑/续接）'],['custom','自定义视频模型 ID']]},
 doubao_video:{id:'doubao_video',name:'字节火山方舟 Seedance',shortName:'Seedance',modeLabel:'API 接口',modeHint:'火山方舟 API Key / Agent Plan',
  authMode:'apikey',modality:'video',defaultBaseUrl:'https://ark.cn-beijing.volces.com',docUrl:'https://www.volcengine.com/docs/82379/1520757',
  keyPlaceholder:'输入火山方舟 API Key（仅保存在本地浏览器）',
  models:[['doubao-seedance-2-5-260628','doubao-seedance-2-5-260628（原生有声 · 图生/文生/多图参考 · 推荐）'],['doubao-seedance-2-0-pro','doubao-seedance-2-0-pro（高动态电影镜头 · 1080p）'],['doubao-seedance-1-5-pro','doubao-seedance-1-5-pro（首尾帧运镜控制）'],['doubao-seedance-1-0-lite-i2v','doubao-seedance-1-0-lite-i2v（轻量图生视频样片）'],['custom','自定义模型 ID / Endpoint']]},
 gemini_video:{id:'gemini_video',name:'Google Veo (Gemini API 接口)',shortName:'Veo API',modeLabel:'Gemini API 接口',modeHint:'Google AI Studio API Key',
  authMode:'apikey',modality:'video',defaultBaseUrl:'https://generativelanguage.googleapis.com',docUrl:'https://ai.google.dev/gemini-api/docs/video',
  keyPlaceholder:'输入 AIza... API Key（仅保存在本地浏览器）',
  models:[['veo-3.1-generate-preview','veo-3.1-generate-preview（原生音画同步 · 首尾帧/参考 · 推荐）'],['veo-3.1-fast-generate-preview','veo-3.1-fast-generate-preview（快速预演候选）'],['veo-3.0-generate-001','veo-3.0-generate-001（1080p 电影级生成）'],['veo-2.0-generate-001','veo-2.0-generate-001'],['custom','自定义视频模型 ID']]},
 qwen_video:{id:'qwen_video',name:'阿里云百炼 通义万相 Wan',shortName:'Wan',modeLabel:'API 接口',modeHint:'DashScope API Key',
  authMode:'apikey',modality:'video',defaultBaseUrl:'https://dashscope.aliyuncs.com',docUrl:'https://help.aliyun.com/zh/model-studio/image-to-video-api-reference',
  keyPlaceholder:'输入 DashScope sk-... API Key（仅保存在本地浏览器）',
  models:[['wan2.6-i2v-plus','wan2.6-i2v-plus（图生视频专业版 · 首尾帧/多参考 · 推荐）'],['wan2.6-t2v-plus','wan2.6-t2v-plus（文生视频专业版）'],['wan2.5-i2v-turbo','wan2.5-i2v-turbo（极速图生视频预演）'],['wan2.2-kf2v-plus','wan2.2-kf2v-plus（首尾帧关键帧过渡）'],['custom','自定义视频模型 ID']]},
 openai_video:{id:'openai_video',name:'OpenAI Sora / 兼容视频接口',shortName:'Sora',modeLabel:'API 接口',modeHint:'OpenAI API Key 或兼容视频网关',
  authMode:'apikey',modality:'video',defaultBaseUrl:'https://api.openai.com/v1',docUrl:'https://platform.openai.com/docs/guides/video-generation',
  keyPlaceholder:'输入 sk-... API Key（仅保存在本地浏览器）',
  models:[['sora-2','sora-2（图生/文生有声视频 · 推荐）'],['sora-2-pro','sora-2-pro（高保真镜头与物理连续性）'],['custom','自定义模型 ID（支持可灵 / Vidu 等兼容网关）']]},
};
for(const meta of Object.values(VIDEO_PROVIDER_META))meta.models=meta.models.map(([value,label])=>({value,label:label||value}));
export const isVideoAuthProvider=id=>VIDEO_PROVIDER_META[id]?.authMode==='oauth';
export const groupForVideoProvider=id=>VIDEO_SETTINGS_GROUPS.find(g=>g.modes.includes(id))||VIDEO_SETTINGS_GROUPS[0];
export const VIDEO_IMAGE_KEY_PEERS={grok_video:'grok',doubao_video:'doubao',gemini_video:'gemini',qwen_video:'qwen',openai_video:'gpt'};
export const IMAGE_VIDEO_KEY_PEERS={grok:'grok_video',doubao:'doubao_video',gemini:'gemini_video',qwen:'qwen_video',gpt:'openai_video'};

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

export function buildRecipePrompt(recipe,stylePreset='realistic'){
 const styleInfo=STYLE_PRESETS[stylePreset]??STYLE_PRESETS.realistic,isPhoto=PHOTO_STYLES.has(stylePreset);
 const faceless=!recipe.portrait&&Boolean(recipe.costume&&recipe.pose);
 const clauses=[];let idx=1,costumeIdx=0;
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
 for(const extra of recipe.extraImages||[]){clauses.push(`• 附加参考：融合图${idx}（${extra.name||'补充元素'}）中的元素、配饰、背景或光影细节。`);idx++;}
 if(!clauses.length)return '请先选择人像/服装/姿势或上传附加参考图。';
 const lines=[`请根据提供的 ${idx-1} 张参考图，生成一张完整的${faceless?'人物穿搭展示图':isPhoto?'真实人物照片':'人物图像'}：`,...clauses];
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

// Local relative paths map to the public gallery CDNs so cloud providers in URL mode can fetch them.
export function toPublicHttpsUrl(src){
 if(/^https?:\/\//i.test(src)||String(src).startsWith('data:'))return src;
 const clean=stripMedia(src).replace(/^\/+/,'');
 if(typeof window!=='undefined'&&window.location?.protocol==='https:'&&!['localhost','127.0.0.1'].includes(window.location.hostname))return `${window.location.origin}${MEDIA_BASE}${clean}`;
 if(clean.startsWith('img/portrait/'))return `https://ai-portrait-gallery.pages.dev/img/${clean.slice(13).replace(/\.webp$/i,'.png')}`;
 if(clean.startsWith('thumbs/portrait/'))return `https://ai-portrait-gallery.pages.dev/thumbs/${clean.slice(16)}`;
 if(clean.startsWith('img/costume/')||clean.startsWith('thumbs/costume/'))return `https://ai-costume-gallery.pages.dev/${clean}`;
 if(clean.startsWith('img/costumes/gia-anime/'))return `https://ai-costume-anime-gallery.pages.dev/img/${clean.slice(23)}`;
 if(clean.startsWith('thumbs/costumes/gia-anime/'))return `https://ai-costume-anime-gallery.pages.dev/thumbs/${clean.slice(26)}`;
 if(clean.startsWith('img/costumes/charadb/'))return `https://charadb-2fi.pages.dev/img/${clean.slice(21)}`;
 if(clean.startsWith('thumbs/costumes/charadb/'))return `https://charadb-2fi.pages.dev/thumb/${clean.slice(24)}`;
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
function blobToDataUrl(blob){
 return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result));r.onerror=()=>reject(new Error('图片读取失败'));r.readAsDataURL(blob);});
}
async function fetchImageViaProxy(url,signal){
 const headers=new Headers({'x-target-url':url,'x-target-method':'GET',Accept:'image/*,*/*;q=0.8'});
 const csrf=csrfProvider();if(csrf)headers.set('X-CSRF-Token',csrf);
 const response=await fetch('/api/proxy',{method:'POST',headers,credentials:'same-origin',signal});
 if(!response.ok)throw new Error('代理下载图片失败');
 const blob=await response.blob();
 if(!blob.type.startsWith('image/'))throw new Error('返回内容不是图片');
 return blobToDataUrl(blob);
}
export async function durableImage(url){
 if(String(url).startsWith('data:image/'))return url;
 const resolved=referenceImageUrl(url),external=/^https?:\/\//i.test(resolved);
 try{
  const response=await fetch(resolved,external?{}:{credentials:'same-origin'});
  if(!response.ok)throw new Error('图片下载失败');
  const blob=await response.blob();
  if(!blob.type.startsWith('image/'))throw new Error('引用不是图片');
  return await blobToDataUrl(blob);
 }catch(error){
  if(/^https:\/\//i.test(resolved))return fetchImageViaProxy(resolved);
  throw error;
 }
}
export async function durableRecipe(recipe){
 const next=JSON.parse(JSON.stringify(recipe));
 for(const item of [next.portrait,next.costume,next.pose]){
  if(item?.source==='upload'){item.原图=await durableImage(item.原图);item.缩略图=item.原图;if('预览图' in item)item.预览图=item.原图;}
 }
 for(const image of next.extraImages||[])image.url=await durableImage(image.url);
 return next;
}

async function smartFetch(targetUrl,init,useProxy){
 if(!useProxy)return fetch(targetUrl,init);
 const headers=new Headers(init.headers);
 headers.set('x-target-url',targetUrl);
 const csrf=csrfProvider();if(csrf)headers.set('X-CSRF-Token',csrf);
 return fetch('/api/proxy',{method:'POST',headers,body:init.body,signal:init.signal,credentials:'same-origin'});
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

// ------------------------------------------------------------------ Auth bridge API
async function callStudioApi(path,options={},api=null){
 const headers={'Content-Type':'application/json',...(options.headers||{})};
 const csrf=csrfProvider();if(csrf)headers['X-CSRF-Token']=csrf;
 if(typeof api==='function')return api(path,{...options,headers});
 const res=await fetch(path,{...options,headers,credentials:'same-origin'});
 const data=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error(data?.detail||data?.message||`请求失败 (HTTP ${res.status})`);
 return data;
}
export const fetchAuthStatus=api=>callStudioApi('/api/v1/character-studio/auth/status',{method:'GET'},api);
export const verifyAuthProvider=(provider,api)=>callStudioApi('/api/v1/character-studio/auth/verify',{method:'POST',body:JSON.stringify({provider})},api);
export const triggerAuthLogin=(provider,api)=>callStudioApi('/api/v1/character-studio/auth/login',{method:'POST',body:JSON.stringify({provider})},api);

// ------------------------------------------------------------------ Request compilers
export function buildGeminiApiRequest({baseUrl,apiKey,model,prompt,refs,geminiParams}){
 const gm=geminiParams||{endpointMode:'native',aspectRatio:'3:4',imageSize:'2K'};
 if(gm.endpointMode==='native'){
  const root=baseUrl.replace(/\/v1(?:beta)?$/,''),url=`${root}/v1beta/models/${encodeURIComponent(model)}:generateContent`;
  const parts=[...refs.map(du=>{
   const [head,b64]=String(du).split(','),mime=head?.match(/data:(.*?);/)?.[1]||'image/png';
   return {inlineData:{mimeType:mime,data:b64||''}};
  }),{text:prompt}];
  const imageConfig={aspectRatio:gm.aspectRatio||'3:4'};
  if(model.includes('gemini-3')&&gm.imageSize)imageConfig.imageSize=gm.imageSize;
  return {
   url,
   headers:{'Content-Type':'application/json','x-goog-api-key':apiKey},
   body:JSON.stringify({contents:[{role:'user',parts}],generationConfig:{responseModalities:['TEXT','IMAGE'],imageConfig}}),
  };
 }
 const v1=baseUrl.endsWith('/v1')?baseUrl:`${baseUrl}/v1`;
 return {
  url:`${v1}/chat/completions`,
  headers:{'Content-Type':'application/json',Authorization:`Bearer ${apiKey}`},
  body:JSON.stringify({
   model,
   messages:[{role:'user',content:[{type:'text',text:`${prompt}\n(Output aspect ratio: ${gm.aspectRatio||'3:4'}, resolution: ${gm.imageSize||'2K'})`},...refs.map(ref=>({type:'image_url',image_url:{url:ref}}))]}],
   modalities:['text','image'],
  }),
 };
}

export function buildGrokApiRequest({baseUrl,apiKey,model,prompt,refs,grokParams}){
 const gr=grokParams||{endpointMode:'auto',aspectRatio:'3:4',resolution:'2k',responseFormat:'auto'};
 const v1=baseUrl.endsWith('/v1')?baseUrl:`${baseUrl}/v1`;
 const headers={'Content-Type':'application/json',Authorization:`Bearer ${apiKey}`};
 const pureGeneration=gr.endpointMode==='generations'||model==='grok-2-image-1212'||!refs.length;
 if(pureGeneration){
  const payload={model,prompt,n:1};
  if(model!=='grok-2-image-1212'){
   payload.aspect_ratio=gr.aspectRatio||'3:4';
   payload.resolution=gr.resolution||'2k';
  }
  payload.response_format=gr.responseFormat==='b64_json'?'b64_json':'url';
  return {url:`${v1}/images/generations`,headers,body:JSON.stringify(payload)};
 }
 if(refs.length>5)throw new Error('[Grok API] Grok 图像编辑一次最多支持 5 张参考图（若开启附带合成拼图，请控制在 4 张以内）');
 const payload={model,prompt,aspect_ratio:gr.aspectRatio||'3:4',resolution:gr.resolution||'2k'};
 if(gr.responseFormat==='b64_json')payload.response_format='b64_json';
 if(refs.length===1)payload.image={url:refs[0],type:'image_url'};
 else payload.images=refs.map(url=>({url,type:'image_url'}));
 return {url:`${v1}/images/edits`,headers,body:JSON.stringify(payload)};
}

export function buildGrokVideoApiRequest({baseUrl,apiKey,model,prompt,firstFrame='',lastFrame='',references=[],videoDefaults}){
 const vd=videoDefaults||{aspectRatio:'16:9',resolution:'720p',durationSec:'5',generateAudio:true};
 const v1=String(baseUrl||'https://api.x.ai/v1').replace(/\/+$/,'');
 const root=v1.endsWith('/v1')?v1:`${v1}/v1`;
 const advanced=String(model||'').includes('1.5'),lite=String(model||'').includes('lite');
 const maxSec=advanced?15:10,duration=Number(vd.durationSec||5);
 if(!Number.isInteger(duration)||duration<1||duration>maxSec)throw new Error(`[Grok Video] 视频时长须为 1–${maxSec} 整秒`);
 if(!String(prompt||'').trim())throw new Error('[Grok Video] 视频请求需要非空提示词');
 const refs=(references||[]).filter(Boolean);
 if(refs.length>14)throw new Error('[Grok Video] 参考模式一次最多支持 14 张参考图');
 if((!advanced||lite)&&lastFrame)throw new Error('[Grok Video] 尾帧钉定需使用 grok-imagine-video-1.5 模型');
 if(!advanced&&firstFrame&&refs.length)throw new Error('[Grok Video] 经典 grok-imagine-video 不支持首帧与参考图同用');
 const resolution=vd.resolution||'720p';
 if(refs.length&&!['480p','720p'].includes(resolution))throw new Error('[Grok Video] 多参考图模式最高支持 720p 分辨率');
 const payload={model,prompt:String(prompt).trim(),duration,resolution};
 if(firstFrame)payload.image={url:firstFrame};
 if(lastFrame)payload.last_frame={url:lastFrame};
 if(refs.length)payload.reference_images=refs.map(url=>({url}));
 if(vd.aspectRatio)payload.aspect_ratio=vd.aspectRatio;
 if(vd.generateAudio===false)payload.generate_audio=false;
 return {
  url:`${root}/videos/generations`,
  headers:{'Content-Type':'application/json',Authorization:`Bearer ${apiKey}`},
  body:JSON.stringify(payload),
 };
}

// ------------------------------------------------------------------ Generation entry
export async function generateCharacterImage({recipe,prompt,config,onProgress,signal}){
 const provider=config.activeProvider,meta=PROVIDER_META[provider],pCfg=config.providers[provider]||{};
 if(!meta)throw new Error('未知的生图接口通道');
 const rawSources=[
  recipe.portrait&&(recipe.portrait.原图||recipe.portrait.缩略图),
  recipe.costume&&(recipe.costume.预览图||recipe.costume.原图||recipe.costume.缩略图),
  recipe.pose&&poseImagePath(recipe.pose),
  ...(recipe.extraImages||[]).map(x=>x.url),
 ].filter(Boolean);
 if(!rawSources.length)throw new Error('请先选择或上传至少 1 张参考图');
 const model=pCfg.model==='custom'?String(pCfg.customModel||'').trim():(pCfg.model||meta.models[0].value);
 if(!model)throw new Error('请选择或填写有效的模型名称');

 if(isAuthProvider(provider)){
  const localRefs=rawSources.map(referenceImageUrl);
  const allRefs=config.sendStitchedSheet?[...localRefs,await stitchRecipeCanvas(recipe)]:localRefs;
  if(provider==='grok_auth'&&allRefs.length>5)throw new Error('[Grok 授权] Grok 图像编辑一次最多支持 5 张参考图，请减少附加参考图或关闭附带合成拼图');
  if(provider==='codex_auth'&&allRefs.length>8)throw new Error('[Codex 授权] 单次最多支持 8 张参考图');
  const isGrokCli=provider==='grok_auth'&&(model==='image_edit'||!model.startsWith('grok-imagine-'));
  onProgress?.({stage:'running',message:provider==='codex_auth'?'正在通过本机 Codex 订阅生成角色图…':provider==='agy_auth'?'正在通过终端 AGY 内置 image-generator 生成角色图…':isGrokCli?'正在通过终端 grok CLI 内置 image_edit 生成角色图…':'正在通过 Grok 订阅授权通道生成角色图…'});
  const csrf=csrfProvider(),headers={'Content-Type':'application/json'};if(csrf)headers['X-CSRF-Token']=csrf;
  const payload={
   provider,model,prompt,references:allRefs,
   aspect_ratio:provider==='codex_auth'?(config.codexParams?.aspectRatio||'3:4'):provider==='grok_auth'?(config.grokParams?.aspectRatio||'3:4'):(config.agyParams?.aspectRatio||'3:4'),
   resolution:config.grokParams?.resolution||'2k',
  };
  const res=await fetch('/api/v1/character-studio/generate',{method:'POST',headers,body:JSON.stringify(payload),signal,credentials:'same-origin'});
  const json=await res.json().catch(()=>({}));
  if(!res.ok)throw new Error(json?.detail||json?.message||`[${meta.shortName}] 请求失败 (HTTP ${res.status})`);
  if(!json?.image_url)throw new Error(`[${meta.shortName}] 服务未返回图像数据`);
  return {imageUrl:json.image_url,modelUsed:json.model||model,providerUsed:provider};
 }

 const apiKey=String(pCfg.apiKey||'').trim();
 if(!apiKey)throw new Error(`请先配置 ${meta.name} 的 API Key`);
 const baseUrl=(String(pCfg.baseUrl||'').trim()||meta.defaultBaseUrl).replace(/\/+$/,'');
 const needBase64=config.imagePassMode==='base64'||config.sendStitchedSheet||(provider==='gemini'&&config.geminiParams.endpointMode==='native')||provider==='grok'||(provider==='gpt'&&config.gptParams.endpointMode==='images_edits');
 const imageRefs=needBase64?await Promise.all(rawSources.map(srcToPngDataUrl)):rawSources.map(toPublicHttpsUrl);
 const allRefs=config.sendStitchedSheet?[...imageRefs,await stitchRecipeCanvas(recipe)]:imageRefs;
 const json_=headers=>({'Content-Type':'application/json',...headers});
 onProgress?.({stage:'running',message:`正在请求 ${meta.shortName} (${model})…`});
 let res;
 if(provider==='gpt'){
  const g=config.gptParams,v1=baseUrl.endsWith('/v1')?baseUrl:`${baseUrl}/v1`,auth={Authorization:`Bearer ${apiKey}`};
  if(g.endpointMode==='images_edits_json'){
   const payload={model,prompt,images:allRefs.map(ref=>({image_url:ref}))};
   if(g.size!=='auto')payload.size=g.size;if(g.quality!=='auto')payload.quality=g.quality;if(g.inputFidelity)payload.input_fidelity=g.inputFidelity;
   if(g.background!=='auto')payload.background=g.background;if(g.outputFormat)payload.output_format=g.outputFormat;if(g.moderation!=='auto')payload.moderation=g.moderation;
   res=await smartFetch(`${v1}/images/edits`,{method:'POST',headers:json_(auth),body:JSON.stringify(payload),signal},config.useProxy);
  }else if(g.endpointMode==='images_edits'){
   const fd=new FormData();fd.append('model',model);fd.append('prompt',prompt);
   allRefs.forEach((du,i)=>fd.append('image[]',dataUrlToBlob(du),`ref_${i+1}.png`));
   if(g.size!=='auto')fd.append('size',g.size);if(g.quality!=='auto')fd.append('quality',g.quality);if(g.inputFidelity)fd.append('input_fidelity',g.inputFidelity);
   if(g.background!=='auto')fd.append('background',g.background);if(g.outputFormat)fd.append('output_format',g.outputFormat);if(g.moderation!=='auto')fd.append('moderation',g.moderation);
   res=await smartFetch(`${v1}/images/edits`,{method:'POST',headers:auth,body:fd,signal},config.useProxy);
  }else if(g.endpointMode==='responses'){
   const tool={type:'image_generation'};
   if(g.size!=='auto')tool.size=g.size;if(g.quality!=='auto')tool.quality=g.quality;if(g.background!=='auto')tool.background=g.background;if(g.inputFidelity)tool.input_fidelity=g.inputFidelity;if(g.outputFormat)tool.output_format=g.outputFormat;
   res=await smartFetch(`${v1}/responses`,{method:'POST',headers:json_(auth),body:JSON.stringify({model,input:[{role:'user',content:[...allRefs.map(ref=>({type:'input_image',image_url:ref})),{type:'input_text',text:prompt}]}],tools:[tool]}),signal},config.useProxy);
  }else{
   res=await smartFetch(`${v1}/chat/completions`,{method:'POST',headers:json_(auth),body:JSON.stringify({model,messages:[{role:'user',content:[{type:'text',text:prompt},...allRefs.map(ref=>({type:'image_url',image_url:{url:ref}}))]}],modalities:['text','image']}),signal},config.useProxy);
  }
 }else if(provider==='gemini'){
  const req=buildGeminiApiRequest({baseUrl,apiKey,model,prompt,refs:allRefs,geminiParams:config.geminiParams});
  res=await smartFetch(req.url,{method:'POST',headers:req.headers,body:req.body,signal},config.useProxy);
 }else if(provider==='grok'){
  const req=buildGrokApiRequest({baseUrl,apiKey,model,prompt,refs:allRefs,grokParams:config.grokParams});
  res=await smartFetch(req.url,{method:'POST',headers:req.headers,body:req.body,signal},config.useProxy);
 }else if(provider==='qwen'){
  const qw=config.qwenParams,endpoint=baseUrl.includes('/services/aigc/')?baseUrl:`${baseUrl.replace(/\/api\/v1$/,'')}/api/v1/services/aigc/multimodal-generation/generation`;
  res=await smartFetch(endpoint,{method:'POST',headers:json_({Authorization:`Bearer ${apiKey}`}),body:JSON.stringify({model,input:{messages:[{role:'user',content:[...imageRefs.map(ref=>({image:ref})),{text:prompt}]}]},
   parameters:{size:qw.size,n:qw.n||1,prompt_extend:qw.promptExtend,watermark:qw.watermark,...(String(qw.negativePrompt||'').trim()?{negative_prompt:qw.negativePrompt.trim()}:{})}}),signal},config.useProxy);
 }else{
  const db=config.doubaoParams;let endpoint=baseUrl;
  if(!endpoint.endsWith('/images/generations'))endpoint=endpoint.endsWith('/api/v3')||endpoint.endsWith('/v1')?`${endpoint}/images/generations`:`${endpoint}/api/v3/images/generations`;
  res=await smartFetch(endpoint,{method:'POST',headers:json_({Authorization:`Bearer ${apiKey}`}),body:JSON.stringify({model,prompt,image:allRefs,size:db.size,sequential_image_generation:db.sequentialImageGeneration,watermark:db.watermark,response_format:db.responseFormat}),signal},config.useProxy);
 }
 const json=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error(`[${meta.shortName}] ${json?.error?.message||json?.message||json?.code||`请求失败 (HTTP ${res.status})`}`);
 let imageUrl=extractUniversalImage(json);
 if(!imageUrl)throw new Error(`接口已响应但未解析到图片输出：${(json?.choices?.[0]?.message?.content||json?.output?.choices?.[0]?.message?.content?.[0]?.text||JSON.stringify(json)).slice(0,260)}`);
 if(/^https:\/\//i.test(imageUrl)&&config.useProxy){
  onProgress?.({stage:'download',message:'正在转存临时生成图片…'});
  imageUrl=await fetchImageViaProxy(imageUrl,signal).catch(()=>imageUrl);
 }
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
