/* Reference binding, focus capture, style library, prompt tools and input preflight.
   Node kind and style live in params: normalize_document rejects unknown top-level fields.
   This module has no static imports so canvas tests can load it without a second upload graph. */

const STYLE_STORAGE_KEY='vsc-canvas-custom-styles';
const TYPE_LABEL={image:'图片',video:'视频',audio:'音频',text:'文本'};
const FRAME_OP=/head_tail|single_image|first_last/;

export const BUILTIN_STYLES=Object.freeze([
  {id:'official-cinematic',tab:'official',name:'电影感',prompt:'电影感构图，浅景深，戏剧化光影'},
  {id:'official-product',tab:'official',name:'官方商品',prompt:'干净商品主图，柔和棚拍光，主体居中'},
  {id:'3d-cinema',tab:'3d',name:'电影级三维',prompt:'电影级三维渲染，体积光，精细材质'},
  {id:'3d-clay',tab:'3d',name:'黏土定格',prompt:'黏土定格动画质感，柔和手工光影'},
  {id:'live-portrait',tab:'live_action',name:'真人写真',prompt:'真人写真，自然肤质，环境光'},
  {id:'live-neon',tab:'live_action',name:'夜戏霓虹',prompt:'夜戏霓虹，湿地面反光，电影夜景'},
  {id:'2d-anime',tab:'2d',name:'日系动画',prompt:'日系动画分镜，清晰线稿，明亮色块'},
  {id:'2d-ink',tab:'2d',name:'水墨国风',prompt:'水墨国风，留白，笔触晕染'},
]);

export const PROMPT_CASES=Object.freeze([
  {id:'snow',modality:'image',title:'雪夜改景',text:'将背景改为雪夜，保留人物身份、服装与姿态，冷月光，地面薄雪反光。'},
  {id:'portrait',modality:'image',title:'窗边肖像',text:'窗边半身肖像，柔和侧光，保留五官与服装细节，浅景深。'},
  {id:'robot',modality:'text',title:'屋顶看星星',text:'一个来自未来的机器人，在城市屋顶看星星。'},
  {id:'first-frame',modality:'video',title:'首帧生成视频',text:'以参考图为首帧，人物缓步向前，镜头稳定跟随，夜色霓虹逐渐亮起。'},
  {id:'alley',modality:'video',title:'巷道跟随',text:'雨夜窄巷跟随镜头，主角撑伞前行，霓虹倒映在地面薄水中。'},
  {id:'rain',modality:'audio',title:'雨夜环境声',text:'细雨打在屋檐和积水上，远处低频车流，无对白。'},
]);

export const RATIO_GUIDE=Object.freeze([
  {ratio:'9:21',label:'非常竖长'},
  {ratio:'9:16',label:'竖屏常见'},
  {ratio:'3:4',label:'竖长'},
  {ratio:'1:1',label:'正方形'},
  {ratio:'4:3',label:'横向'},
  {ratio:'16:9',label:'横屏常见'},
  {ratio:'21:9',label:'非常宽屏'},
]);

function newId(){return crypto.randomUUID();}

function el(doc,tag,text,className){
  const node=doc.createElement(tag);
  if(className)node.className=className;
  if(text!=null&&text!=='')node.textContent=String(text);
  return node;
}

function browserStorage(){
  try{
    if(typeof localStorage!=='undefined'&&localStorage&&typeof localStorage.getItem==='function')return localStorage;
  }catch{/* private mode or a test realm without storage */}
  return null;
}

function memoryStorage(){
  const map=new Map();
  return {getItem:key=>map.has(key)?map.get(key):null,setItem:(key,value)=>map.set(key,String(value)),removeItem:key=>map.delete(key)};
}

function validStyle(row){
  return Boolean(row&&typeof row.id==='string'&&typeof row.name==='string'&&typeof row.prompt==='string');
}

export function createStyleStore(storage){
  const bag=storage||browserStorage()||memoryStorage();
  function read(){
    try{
      const raw=JSON.parse(bag.getItem(STYLE_STORAGE_KEY)||'null');
      return {
        custom:Array.isArray(raw?.custom)?raw.custom.filter(validStyle):[],
        mine:Array.isArray(raw?.mine)?raw.mine.filter(id=>typeof id==='string'):[],
      };
    }catch{return {custom:[],mine:[]};}
  }
  function write(data){bag.setItem(STYLE_STORAGE_KEY,JSON.stringify({custom:data.custom,mine:data.mine}));}
  return {
    key:STYLE_STORAGE_KEY,
    read,
    list(tab,query){return listStyles(tab,query,read());},
    rememberMine(id){
      const data=read();
      if(id&&!data.mine.includes(id))data.mine.push(id);
      write(data);
      return data;
    },
    saveCustom(style){
      const data=read();
      if(data.custom.length>=100)throw new Error('个人风格已达 100 条上限');
      const name=String(style?.name||'').trim();
      const prompt=String(style?.prompt||'').trim();
      if(name.length<1||name.length>40)throw new Error('风格名称需为 1–40 字');
      if(prompt.length<1||prompt.length>800)throw new Error('风格描述需为 1–800 字');
      const row={id:style.id||`custom-${newId()}`,name,prompt,tab:'custom'};
      data.custom.push(row);
      if(!data.mine.includes(row.id))data.mine.push(row.id);
      write(data);
      return row;
    },
  };
}

export function listStyles(tab,query,data){
  const bag=data||{custom:[],mine:[]};
  const q=String(query||'').trim().toLowerCase();
  let rows=[];
  if(tab==='custom')rows=bag.custom.slice();
  else if(tab==='mine'){
    const ids=new Set(bag.mine||[]);
    rows=BUILTIN_STYLES.filter(style=>ids.has(style.id)).concat(bag.custom||[]);
  }else rows=BUILTIN_STYLES.filter(style=>style.tab===tab);
  if(!q)return rows;
  return rows.filter(style=>style.name.toLowerCase().includes(q)||style.prompt.toLowerCase().includes(q));
}

function stripStyleFragment(node){
  const prompt=node?.params?.vsc_gen_style_prompt;
  if(!prompt)return;
  const line=`风格：${prompt}`;
  node.text=String(node.text||'').split('\n').filter(row=>row!==line).join('\n');
}

export function applyStyleToNode(node,style){
  if(!node.params||typeof node.params!=='object')node.params={};
  stripStyleFragment(node);
  const prompt=String(style?.prompt||'').slice(0,800);
  const name=String(style?.name||'').slice(0,40);
  node.params.vsc_gen_style_id=String(style.id);
  node.params.vsc_gen_style_name=name;
  node.params.vsc_gen_style_prompt=prompt;
  const line=`风格：${prompt}`;
  const text=String(node.text||'').replace(/\s+$/,'');
  node.text=text?`${text}\n${line}`:line;
  return node;
}

export function clearGeneratorStyle(node){
  if(!node)return;
  stripStyleFragment(node);
  if(node.params){
    delete node.params.vsc_gen_style_name;
    delete node.params.vsc_gen_style_prompt;
  }
}

export function styleLabelFor(styleId,node,styles=[]){
  if(!styleId||styleId==='none')return '风格';
  if(node?.params?.vsc_gen_style_name)return String(node.params.vsc_gen_style_name);
  const found=styles.find(style=>style.id===styleId);
  return found?.name||'风格';
}

export function resolveNodeKind(node){
  const kind=node?.params?.vsc_node_kind;
  if(kind==='source'||kind==='generator')return kind;
  return 'legacy';
}

export function canDirectlyGenerate(node){return resolveNodeKind(node)!=='source';}

export function generationBlockReason(node){
  return resolveNodeKind(node)==='source'?'素材节点不能发起生成':'';
}

export function markCanvasNodeKind(node,kind){
  if(!node)return node;
  if(!node.params||typeof node.params!=='object')node.params={};
  if(kind==='source'||kind==='generator')node.params.vsc_node_kind=kind;
  return node;
}

export function spawnImageToImage(document,source,idFactory=newId){
  const id=idFactory();
  const node={
    id,type:'image',title:'图生图',x:(source?.x||0)+300,y:source?.y||0,text:'',
    params:{vsc_node_kind:'generator',vsc_operation:'image_generate'},
    media_id:null,job_id:null,group:source?.group||'',
  };
  document.nodes.push(node);
  document.edges.push({id:idFactory(),source:source.id,target:id,port:'reference'});
  return node;
}

export function referencePortFor(document,target,source){
  if(!target||!source||target.id===source.id)return null;
  if(source.type==='text')return 'prompt';
  if(target.type==='image')return source.type==='image'?'reference':null;
  if(target.type==='audio')return source.type==='audio'||source.type==='video'?'reference_audio':null;
  if(target.type!=='video')return null;
  if(source.type==='video')return 'reference_video';
  if(source.type==='audio')return 'reference_audio';
  if(source.type!=='image')return null;
  const edges=(document?.edges||[]).filter(edge=>edge.target===target.id&&edge.port!=='derived_from');
  const frameOp=FRAME_OP.test(String(target.params?.vsc_operation||''));
  const hasFrame=edges.some(edge=>edge.port==='first_frame'||edge.port==='last_frame');
  if(frameOp||hasFrame){
    if(!edges.some(edge=>edge.port==='first_frame'))return 'first_frame';
    if(!edges.some(edge=>edge.port==='last_frame'))return 'last_frame';
    return 'reference_image';
  }
  return 'reference_image';
}

export function mentionAtCaret(text,caret){
  const source=String(text||'');
  const at=Number.isInteger(caret)?caret:source.length;
  const upto=source.slice(0,Math.max(0,Math.min(at,source.length)));
  const match=upto.match(/(^|[\s\n])@([^\s@]*)$/);
  if(!match)return null;
  const query=match[2];
  return {start:at-query.length-1,caret:at,query};
}

export function mentionCandidates(document,target,query){
  const nodes=(document?.nodes||[]).filter(node=>node.id!==target?.id&&referencePortFor(document,target,node));
  const q=String(query||'').trim().toLowerCase();
  const filtered=q?nodes.filter(node=>String(node.title||'').toLowerCase().includes(q)):nodes;
  const connected=new Set((document?.edges||[]).filter(edge=>edge.target===target?.id).map(edge=>edge.source));
  const order={image:0,video:1,audio:2,text:3};
  return filtered.slice().sort((a,b)=>{
    const ca=connected.has(a.id)?0:1,cb=connected.has(b.id)?0:1;
    if(ca!==cb)return ca-cb;
    const ta=order[a.type]??9,tb=order[b.type]??9;
    if(ta!==tb)return ta-tb;
    return String(a.title||'').localeCompare(String(b.title||''),'zh');
  });
}

export function applyMention(document,target,candidate,caretState,idFactory=newId){
  const port=referencePortFor(document,target,candidate);
  if(!port||!caretState)return null;
  const text=String(target.text||'');
  const token=`@${candidate.title||''}`;
  const next=text.slice(0,caretState.start)+token+text.slice(caretState.caret);
  target.text=next;
  const already=document.edges.some(edge=>edge.source===candidate.id&&edge.target===target.id&&edge.port===port);
  if(!already){
    document.edges.push({id:idFactory(),source:candidate.id,target:target.id,port});
    if(target.params)delete target.params.vsc_mixed_sig;
  }
  return {text:next,caret:caretState.start+token.length,port,already};
}

export function moveMentionIndex(index,count,direction){
  if(!count)return 0;
  return (index+direction+count)%count;
}

export function mentionKeyAction(event,state){
  if(!state?.open||!event||event.isComposing||event.keyCode===229)return 'ignore';
  if(event.key==='ArrowDown')return 'next';
  if(event.key==='ArrowUp')return 'prev';
  if(event.key==='Enter'||event.key==='Tab')return 'select';
  if(event.key==='Escape')return 'close';
  return 'ignore';
}

function promptStamp(text){
  let hash=0;
  for(let i=0;i<text.length;i++)hash=(hash*31+text.charCodeAt(i))>>>0;
  return `${text.length}:${hash.toString(16)}:${text.slice(0,80)}`;
}

export function mixedSignature(node,document){
  const text=String(node?.text||'');
  const mentions=[...text.matchAll(/@([^\s@]+)/g)].map(match=>match[1]);
  const edges=(document?.edges||[]).filter(edge=>edge.target===node?.id&&edge.port!=='derived_from').map(edge=>`${edge.port}:${edge.source}`).sort();
  return JSON.stringify({prompt:promptStamp(text),mentions,edges}).slice(0,1800);
}

export function mixedBindingState(node,document){
  const edges=(document?.edges||[]).filter(edge=>edge.target===node?.id&&edge.port!=='derived_from');
  const hasFrame=edges.some(edge=>edge.port==='first_frame'||edge.port==='last_frame');
  const hasOmni=edges.some(edge=>['reference','reference_image','reference_video','reference_audio'].includes(edge.port));
  const mentions=[...String(node?.text||'').matchAll(/@([^\s@]+)/g)].map(match=>match[1]);
  const unbound=mentions.filter(name=>{
    const named=(document?.nodes||[]).filter(item=>item.title===name);
    return !named.some(item=>edges.some(edge=>edge.source===item.id));
  });
  const conflict=hasFrame&&hasOmni;
  const signature=mixedSignature(node,document);
  const stored=node?.params?.vsc_mixed_sig;
  const needs=unbound.length>0||conflict||mentions.length>0;
  const confirmed=stored===signature;
  return {
    pending:Boolean(needs&&!confirmed),
    changed:Boolean(stored&&stored!==signature),
    confirmed,
    unbound,
    conflict,
    signature,
    count:unbound.length,
  };
}

export function applyCanvasReferencePick(s,node,hooks={}){
  if(!s?.referencePick)return false;
  const target=(s.document?.nodes||[]).find(item=>item.id===s.referencePick.targetId);
  const notice=message=>{hooks.notice?.(s,message);};
  if(!target||node?.id===target.id){
    s.referencePick=null;
    notice(node?.id===target?.id?'节点不能连接到自身。':'已退出参考选择');
    hooks.draw?.(s);
    return true;
  }
  const port=referencePortFor(s.document,target,node);
  if(!port){
    notice('该节点不能作为参考');
    hooks.draw?.(s);
    return true;
  }
  const duplicate=(s.document.edges||[]).some(edge=>edge.source===node.id&&edge.target===target.id&&edge.port===port);
  if(duplicate){
    s.referencePick=null;
    notice('已引用');
    hooks.draw?.(s);
    return true;
  }
  const mutate=()=>{
    s.document.edges.push({id:(hooks.idFactory||newId)(),source:node.id,target:target.id,port});
    if(target.params)delete target.params.vsc_mixed_sig;
    s.referencePick=null;
    s.selected=new Set([target.id]);
  };
  if(typeof hooks.change==='function')hooks.change(s,mutate);
  else mutate();
  return true;
}

export function paintCanvasReferenceChrome(s){
  if(!s?.root?.querySelector||!s.world?.querySelectorAll)return;
  s.root.querySelector('.crs-pick-banner')?.remove();
  s.root.querySelector('.crs-return-node')?.remove();
  for(const card of s.world.querySelectorAll('.cc-node'))card.classList?.remove('crs-pick-target','crs-pick-candidate');
  if(s.referencePick){
    const target=(s.document?.nodes||[]).find(node=>node.id===s.referencePick.targetId);
    const doc=s.root.ownerDocument;
    const banner=el(doc,'div','从画布选择参考 · 按 ESC 退出','crs-pick-banner');
    banner.append(el(doc,'span','当前参考目标节点','crs-pick-target-label'));
    if(target)banner.append(el(doc,'strong',target.title||''));
    s.root.append(banner);
    for(const card of s.world.querySelectorAll('.cc-node')){
      if(card.dataset?.nodeId===s.referencePick.targetId)card.classList?.add('crs-pick-target');
      else card.classList?.add('crs-pick-candidate');
    }
  }
  if(s.referenceReturn?.generatorId){
    const doc=s.root.ownerDocument;
    const button=el(doc,'button','返回节点','crs-return-node');
    button.type='button';
    button.addEventListener('click',()=>{
      const id=s.referenceReturn?.generatorId;
      s.referenceReturn=null;
      if(id)s.selected=new Set([id]);
      s._crs?.helpers?.draw?.(s);
    });
    s.root.append(button);
  }
}

export function handleCanvasReferenceKey(s,event,helpers){
  if(!event||event.key!=='Escape'||event.isComposing)return false;
  if(s?._crs?.mentionOpen)return false;
  let handled=false;
  if(s?.referencePick){
    s.referencePick=null;
    helpers?.notice?.(s,'已退出参考选择');
    handled=true;
  }
  if(s?._crs?.focusOpen){
    s._crs.focusClose?.();
    helpers?.notice?.(s,'按ESC键可退出当前模式');
    handled=true;
  }
  if(handled)helpers?.draw?.(s);
  return handled;
}

export function ensureCanvasReferenceBindings(s,helpers){
  if(!s)return;
  s._crs=s._crs||{optimizeCounts:{}};
  s._crs.helpers=helpers;
  const doc=s.root?.ownerDocument;
  if(!doc||s._crsBound||typeof doc.addEventListener!=='function')return;
  s._crsBound=true;
  doc.addEventListener('keydown',event=>handleCanvasReferenceKey(s,event,helpers));
}

export function rememberMediaMetrics(s,mediaId,width,height,duration){
  if(!s||!mediaId)return;
  s.mediaMetrics=s.mediaMetrics||{};
  const prev=s.mediaMetrics[mediaId]||{};
  s.mediaMetrics[mediaId]={
    width:width||prev.width||0,
    height:height||prev.height||0,
    duration:typeof duration==='number'?duration:prev.duration,
  };
}

export function selectionNormFromPointers(bounds,x0,y0,x1,y1){
  if(!bounds?.width||!bounds?.height)return null;
  const left=Math.max(bounds.left,Math.min(x0,x1));
  const top=Math.max(bounds.top,Math.min(y0,y1));
  const right=Math.min(bounds.left+bounds.width,Math.max(x0,x1));
  const bottom=Math.min(bounds.top+bounds.height,Math.max(y0,y1));
  const w=right-left,h=bottom-top;
  if(w<2||h<2)return null;
  return {x:(left-bounds.left)/bounds.width,y:(top-bounds.top)/bounds.height,w:w/bounds.width,h:h/bounds.height};
}

export function cropRectPixels(w,h,norm){
  if(!(w>0)||!(h>0)||!norm)return null;
  const x=Math.round(norm.x*w),y=Math.round(norm.y*h);
  const cw=Math.round(norm.w*w),ch=Math.round(norm.h*h);
  if(cw<1||ch<1)return null;
  return {x,y,w:cw,h:ch};
}

export function smartCropNorm(w,h,targetRatio){
  if(!(w>0)||!(h>0)||!(targetRatio>0))return null;
  const current=w/h;
  if(Math.abs(current-targetRatio)<1e-4)return {x:0,y:0,w:1,h:1};
  if(current>targetRatio){
    const cropW=h*targetRatio;
    const x=(w-cropW)/2;
    return {x:x/w,y:0,w:cropW/w,h:1};
  }
  const cropH=w/targetRatio;
  const y=(h-cropH)/2;
  return {x:0,y:y/h,w:1,h:cropH/h};
}

export async function cropImageElement(image,norm,rasterize){
  const width=image?.naturalWidth||image?.width;
  const height=image?.naturalHeight||image?.height;
  const px=cropRectPixels(width,height,norm);
  if(!px)throw new Error('请先框选聚焦区域');
  if(typeof rasterize==='function')return rasterize(image,px,norm);
  const doc=image?.ownerDocument||globalThis.document;
  if(!doc?.createElement)throw new Error('当前浏览器不支持裁剪');
  const canvas=doc.createElement('canvas');
  canvas.width=px.w;
  canvas.height=px.h;
  const context=canvas.getContext?.('2d');
  if(!context)throw new Error('当前浏览器不支持裁剪');
  context.drawImage(image,px.x,px.y,px.w,px.h,0,0,px.w,px.h);
  const blob=await new Promise((resolve,reject)=>{
    if(typeof canvas.toBlob!=='function'){reject(new Error('当前浏览器不支持裁剪'));return;}
    canvas.toBlob(value=>value?resolve(value):reject(new Error('裁剪结果生成失败')),'image/png');
  });
  return blob;
}

export async function defaultUploadImageBlob(s,blob,filename,helpers){
  const specifier='./media-'+'upload.js';
  const module=await import(specifier);
  const doc=s.root.ownerDocument;
  const host=el(doc,'div','','crs-upload-host');
  host.hidden=true;
  s.root.append(host);
  try{
    let mediaId=null;
    const upload=module.createMediaUpload({
      root:host,
      api:(...args)=>helpers.api(...args),
      project:s.project,
      session:helpers.session,
      title:filename||'聚焦截图',
      accept:'image/png,image/jpeg,image/webp',
      multiple:false,
      onComplete:async({mediaId:id})=>{mediaId=id;},
    });
    const file=new File([blob],filename||'focus-capture.png',{type:blob.type||'image/png'});
    await upload.uploadFiles([file]);
    upload.suspend?.();
    if(!mediaId)throw new Error('裁剪结果上传或保存失败');
    return mediaId;
  }finally{host.remove();}
}

function placeNear(source){
  return {x:Math.min(100000,(source?.x||0)+36),y:Math.min(100000,(source?.y||0)+36)};
}

export function insertFocusNode(document,spec){
  const id=(spec.idFactory||newId)();
  const point=placeNear(spec.source);
  const rect=JSON.stringify(spec.norm||{}).slice(0,200);
  const node={
    id,type:'image',title:'聚焦截图',x:point.x,y:point.y,text:'',
    params:{vsc_node_kind:'source',vsc_focus_capture:'1',vsc_focus_source:spec.source?.id||'',vsc_focus_rect:rect},
    media_id:spec.mediaId,job_id:null,group:spec.source?.group||'',
  };
  document.nodes.push(node);
  const port=referencePortFor(document,spec.generator,node)||'reference';
  document.edges.push({id:(spec.idFactory||newId)(),source:id,target:spec.generator.id,port});
  return node;
}

export function removeFocusNode(document,focusId){
  const node=(document?.nodes||[]).find(item=>item.id===focusId);
  if(!node||node.params?.vsc_focus_capture!=='1')return false;
  document.nodes=document.nodes.filter(item=>item.id!==focusId);
  document.edges=document.edges.filter(edge=>edge.source!==focusId&&edge.target!==focusId);
  return true;
}

export function replaceEdgeWithCropCopy(document,spec){
  const edge=(document?.edges||[]).find(item=>item.id===spec.edgeId);
  if(!edge)return null;
  const source=(document.nodes||[]).find(item=>item.id===edge.source);
  const id=(spec.idFactory||newId)();
  const point=placeNear(source);
  const title=`${String(source?.title||'参考图').slice(0,180)} · 裁剪副本`.slice(0,200);
  const node={
    id,type:'image',title,x:point.x,y:point.y,text:'',
    params:{
      vsc_node_kind:'source',
      vsc_crop_copy:'1',
      vsc_focus_source:source?.id||'',
      vsc_focus_rect:JSON.stringify(spec.norm||{}).slice(0,200),
    },
    media_id:spec.mediaId,job_id:null,group:source?.group||'',
  };
  document.nodes.push(node);
  edge.source=node.id;
  return node;
}

export async function commitFocusCapture(s,spec){
  const helpers=spec.helpers||s._crs?.helpers||{};
  const norm=spec.norm;
  if(!norm)throw new Error('请先框选聚焦区域');
  const image=spec.image||{naturalWidth:spec.width,naturalHeight:spec.height,width:spec.width,height:spec.height};
  const blob=await cropImageElement(image,norm,spec.rasterize);
  const upload=spec.uploadImageBlob||(file=>defaultUploadImageBlob(s,file,spec.filename||'聚焦截图.png',helpers));
  const mediaId=await upload(blob,spec.filename||'聚焦截图.png');
  if(!mediaId)throw new Error('裁剪结果素材无效');
  let created=null;
  const mutate=()=>{
    if(spec.replace){
      const prev=(s.document.nodes||[]).find(node=>node.params?.vsc_focus_capture==='1'&&node.params?.vsc_focus_source===spec.source?.id&&(s.document.edges||[]).some(edge=>edge.source===node.id&&edge.target===spec.generator.id));
      if(prev)removeFocusNode(s.document,prev.id);
    }
    created=insertFocusNode(s.document,{generator:spec.generator,source:spec.source,mediaId,norm,idFactory:spec.idFactory});
    s.selected=new Set([spec.generator.id]);
    if(spec.generator.params)delete spec.generator.params.vsc_mixed_sig;
  };
  if(typeof helpers.change==='function')helpers.change(s,mutate);
  else mutate();
  helpers.notice?.(s,'已创建聚焦截图');
  return created;
}

function imageElementFor(s,mediaId){
  if(!s?.world?.querySelectorAll||!mediaId)return null;
  return [...s.world.querySelectorAll('img')].find(img=>String(img.src||'').includes(mediaId))||null;
}

export function referenceSnapshots(s,node){
  return (s.document?.edges||[]).filter(edge=>edge.target===node?.id&&edge.port!=='derived_from').map(edge=>{
    const src=(s.document.nodes||[]).find(item=>item.id===edge.source);
    const metrics=s.mediaMetrics?.[src?.media_id]||{};
    let width=metrics.width,height=metrics.height,duration=metrics.duration;
    const img=imageElementFor(s,src?.media_id);
    if(img?.naturalWidth&&img?.naturalHeight){width=img.naturalWidth;height=img.naturalHeight;}
    return {edgeId:edge.id,nodeId:src?.id,mediaId:src?.media_id,type:src?.type,title:src?.title,width,height,duration};
  });
}

function referenceLabel(type,index){
  if(type==='video')return `参考视频${index}`;
  if(type==='audio')return `参考音频${index}`;
  return `参考图${index}`;
}

export function inputRulesFor(runOptions,modelId){
  if(!runOptions||!modelId)return null;
  return runOptions.model_params?.[modelId]?.input_validation||null;
}

export function collectInputIssues({rules,references}={}){
  if(!rules)return [];
  const issues=[];
  const rows=references||[];
  const images=rows.filter(row=>(row.type||row.modality)==='image');
  const videos=rows.filter(row=>(row.type||row.modality)==='video');
  const audios=rows.filter(row=>(row.type||row.modality)==='audio');
  if(rules.max_reference_images&&images.length>rules.max_reference_images){
    issues.push({code:'image_count',message:`最多支持${rules.max_reference_images}张参考图`,repair:null});
  }
  if(rules.max_reference_videos&&videos.length>rules.max_reference_videos){
    issues.push({code:'video_count',message:`最多支持${rules.max_reference_videos}个参考视频`,repair:null});
  }
  if(rules.max_reference_audios&&audios.length>rules.max_reference_audios){
    issues.push({code:'audio_count',message:`最多支持${rules.max_reference_audios}个参考音频`,repair:null});
  }
  const checkAspect=(row,index,minKey,maxKey,kind)=>{
    if(!(row.width>0)||!(row.height>0))return;
    const ratio=row.width/row.height;
    const label=referenceLabel(row.type,index);
    if(rules[maxKey]&&ratio>rules[maxKey]+1e-6){
      issues.push({
        code:`${kind}_aspect_max`,message:kind==='image'?`${label}宽高比不能大于${rules[maxKey]}，请裁剪`:`${label}宽高比不能大于${rules[maxKey]}`,
        repair:kind==='image'?'smart_crop':null,mediaId:row.mediaId,edgeId:row.edgeId,nodeId:row.nodeId,
        targetRatio:rules[maxKey],width:row.width,height:row.height,
      });
    }
    if(rules[minKey]&&ratio+1e-6<rules[minKey]){
      issues.push({
        code:`${kind}_aspect_min`,message:kind==='image'?`${label}宽高比不能小于${rules[minKey]}，请调整`:`${label}宽高比不能小于${rules[minKey]}`,
        repair:kind==='image'?'smart_crop':null,mediaId:row.mediaId,edgeId:row.edgeId,nodeId:row.nodeId,
        targetRatio:rules[minKey],width:row.width,height:row.height,
      });
    }
  };
  images.forEach((row,index)=>{
    checkAspect(row,index+1,'image_aspect_min','image_aspect_max','image');
    if(!(row.width>0)||!(row.height>0))return;
    const short=Math.min(row.width,row.height);
    const label=referenceLabel('image',index+1);
    if(rules.image_short_edge_min&&short<rules.image_short_edge_min){
      issues.push({code:'short_edge_min',message:`${label}短边不能小于${rules.image_short_edge_min}像素`,repair:null,edgeId:row.edgeId});
    }
    if(rules.image_short_edge_max&&short>rules.image_short_edge_max){
      issues.push({code:'short_edge_max',message:`${label}短边不能超过${rules.image_short_edge_max}像素`,repair:null,edgeId:row.edgeId});
    }
  });
  videos.forEach((row,index)=>{
    checkAspect(row,index+1,'video_aspect_min','video_aspect_max','video');
    if(typeof row.duration!=='number')return;
    const label=referenceLabel('video',index+1);
    if(rules.video_duration_max&&row.duration>rules.video_duration_max){
      issues.push({code:'duration_max',message:`${label}时长不能大于${rules.video_duration_max}秒`,repair:null});
    }
    if(rules.video_duration_min&&row.duration<rules.video_duration_min){
      issues.push({code:'duration_min',message:`${label}时长不能小于${rules.video_duration_min}秒`,repair:null});
    }
  });
  return issues;
}

export function optimizeButtonState({available,reason,count,checking}={}){
  if(checking||available==null)return {disabled:true,title:'正在检测本地文本工具状态'};
  if(!available)return {disabled:true,title:reason||'本机未安装或未接通文本工具宿主（grok CLI），提示词优化不可用'};
  if((count||0)>=10)return {disabled:true,title:'提示词优化次数已达上限（最多10次）'};
  return {disabled:false,title:'提示词优化'};
}

function hostOf(s){return s?.root;}

function openOverlay(doc,host,{title,label,className}={}){
  const overlay=el(doc,'div','',className||'crs-overlay');
  overlay.setAttribute('role','dialog');
  overlay.setAttribute('aria-label',label||title||'');
  const panel=el(doc,'div','','crs-dialog');
  if(title)panel.append(el(doc,'h3',title,'crs-dialog-title'));
  overlay.append(panel);
  host.append(overlay);
  return {overlay,panel,close(){overlay.remove();}};
}

function bindPromptMentions(textarea,payload){
  const {s,node,helpers,doc}=payload;
  if(!textarea||typeof textarea.addEventListener!=='function'||textarea.dataset?.crsMentions==='1')return;
  if(textarea.dataset)textarea.dataset.crsMentions='1';
  const owner=textarea.parentElement||s.inspector||s.root;
  let menu=null,index=0,items=[];
  const close=()=>{menu?.remove();menu=null;if(s._crs)s._crs.mentionOpen=false;};
  const caretState=()=>mentionAtCaret(String(textarea.value??''),textarea.selectionStart??String(textarea.value??'').length);
  const choose=itemIndex=>{
    const at=caretState();
    const candidate=items[itemIndex];
    if(!at||!candidate)return;
    close();
    helpers.change(s,()=>{
      const applied=applyMention(s.document,node,candidate,at);
      if(applied)s._crs.pendingCaret={nodeId:node.id,caret:applied.caret};
    });
    const next=s.inspector?.querySelector?.('[aria-label="文本或提示词"]');
    const pending=s._crs?.pendingCaret;
    if(next&&pending?.nodeId===node.id&&typeof next.setSelectionRange==='function'){
      s._crs.pendingCaret=null;
      next.focus?.();
      next.setSelectionRange(pending.caret,pending.caret);
    }
  };
  const render=()=>{
    const at=caretState();
    if(!at){close();return;}
    items=mentionCandidates(s.document,node,at.query);
    index=Math.min(index,Math.max(0,items.length-1));
    close();
    menu=el(doc,'div','','crs-mention-menu');
    menu.dataset.crsMention='1';
    menu.setAttribute('role','listbox');
    menu.setAttribute('aria-label','素材引用');
    const connected=new Set((s.document.edges||[]).filter(edge=>edge.target===node.id).map(edge=>edge.source));
    if(!items.length)menu.append(el(doc,'p',at.query?'暂无匹配节点':'暂无匹配节点','crs-mention-empty'));
    else if(!items.some(item=>connected.has(item.id)))menu.append(el(doc,'p','暂无已引用素材','crs-mention-heading'));
    let headed=false;
    items.forEach((item,itemIndex)=>{
      if(connected.has(item.id)&&!headed){menu.append(el(doc,'p','已引用','crs-mention-heading'));headed=true;}
      const row=el(doc,'button','','crs-mention-item'+(itemIndex===index?' is-active':''));
      row.type='button';
      row.dataset.nodeId=item.id;
      row.setAttribute('role','option');
      row.append(el(doc,'span',TYPE_LABEL[item.type]||item.type,'crs-mention-type'),el(doc,'span',item.title||item.id,'crs-mention-title'));
      row.addEventListener('mousedown',event=>{event.preventDefault();choose(itemIndex);});
      menu.append(row);
    });
    const search=el(doc,'p',at.query?`搜索画布节点：${at.query}`:'搜索画布节点','crs-mention-search');
    menu.prepend(search);
    owner.append(menu);
    s._crs=s._crs||{optimizeCounts:{}};
    s._crs.mentionOpen=true;
  };
  textarea.addEventListener('input',render);
  textarea.addEventListener('keyup',render);
  textarea.addEventListener('keydown',event=>{
    const action=mentionKeyAction(event,{open:Boolean(menu)});
    if(action==='ignore')return;
    event.preventDefault();
    event.stopPropagation();
    if(action==='close'){close();return;}
    if(action==='next'||action==='prev'){
      index=moveMentionIndex(index,items.length,action==='next'?1:-1);
      render();
      return;
    }
    if(action==='select'&&items[index])choose(index);
  });
  if(s._crs?.pendingCaret?.nodeId===node.id&&typeof textarea.setSelectionRange==='function'){
    const pending=s._crs.pendingCaret;
    s._crs.pendingCaret=null;
    textarea.focus?.();
    textarea.setSelectionRange(pending.caret,pending.caret);
  }
}

function paintStyleCards(ctx){
  const {root,doc,tab,query,selectedStyleId,node,s,ui,helpers,store}=ctx;
  if(!root)return;
  for(const card of [...(root.querySelectorAll?.('[data-crs-style]')||[])])card.remove();
  const items=store.list(tab,query);
  if(!items.length){
    const empty=el(doc,'div','暂无风格','cgc-style-slot-placeholder');
    empty.dataset.crsStyle='empty';
    root.append(empty);
    return;
  }
  for(const style of items){
    const card=el(doc,'button','','cgc-style-card crs-style-card'+(selectedStyleId===style.id?' is-selected':''));
    card.type='button';
    card.dataset.crsStyle=style.id;
    card.dataset.styleId=style.id;
    card.setAttribute('aria-pressed',String(selectedStyleId===style.id));
    card.append(el(doc,'span',style.name,'cgc-style-card-name'),el(doc,'span',style.prompt,'crs-style-prompt'));
    card.addEventListener('click',event=>{
      event.stopPropagation();
      if(ui)ui.openPopover=null;
      helpers.change(s,()=>{
        applyStyleToNode(node,style);
        store.rememberMine(style.id);
      });
    });
    root.append(card);
  }
}

function ensureCustomTab(ctx){
  const {tabs,doc,tab,ui,s,helpers}=ctx;
  if(!tabs||tabs.querySelector?.('[data-style-tab="custom"]'))return;
  const button=el(doc,'button','自定义','crs-style-tab'+(tab==='custom'?' is-active':''));
  button.type='button';
  button.dataset.styleTab='custom';
  button.setAttribute('data-style-tab','custom');
  button.setAttribute('role','tab');
  button.setAttribute('aria-selected',String(tab==='custom'));
  button.addEventListener('click',event=>{
    event.stopPropagation();
    if(ui)ui.styleTab='custom';
    helpers.draw?.(s);
  });
  tabs.append(button);
}

async function runOptimize(s,node,helpers,promptInput){
  const text=String((promptInput&&typeof promptInput.value==='string'?promptInput.value:node.text)||'').trim();
  if(!text){helpers.notice(s,'提示词为空，请输入内容后点击');return null;}
  s._crs=s._crs||{optimizeCounts:{}};
  s._crs.optimizeCounts=s._crs.optimizeCounts||{};
  if((s._crs.optimizeCounts[node.id]||0)>=10){helpers.notice(s,'提示词优化次数已达上限（最多10次）');return null;}
  const res=await helpers.api(helpers.url(s)+'/prompt-optimize',{
    method:'POST',headers:helpers.headers(),
    body:JSON.stringify({payload:{node_id:node.id,text}}),
  });
  const optimized=typeof res?.text==='string'?res.text.trim():'';
  if(!optimized)throw new Error('提示词优化失败，请稍后重试');
  s._crs.optimizeCounts[node.id]=(s._crs.optimizeCounts[node.id]||0)+1;
  return optimized;
}

function openOptimizeDialog(s,node,helpers,promptInput,text){
  const doc=s.root.ownerDocument;
  let current=text;
  const dialog=openOverlay(doc,hostOf(s),{title:'优化后的提示词',label:'优化后的提示词'});
  const body=el(doc,'p',current,'crs-optimize-body');
  const copy=el(doc,'button','复制','crs-btn');
  copy.type='button';
  copy.addEventListener('click',async()=>{
    try{
      if(globalThis.navigator?.clipboard?.writeText){await navigator.clipboard.writeText(current);helpers.notice(s,'已复制');}
      else helpers.notice(s,'系统剪贴板不可用');
    }catch{helpers.notice(s,'系统剪贴板写入失败');}
  });
  const again=el(doc,'button','重新生成','crs-btn');
  again.type='button';
  again.addEventListener('click',async()=>{
    try{
      const next=await runOptimize(s,node,helpers,promptInput);
      if(!next)return;
      current=next;
      body.textContent=current;
    }catch(error){helpers.notice(s,error?.message||'提示词优化失败，请稍后重试');}
  });
  const fill=el(doc,'button','填充到输入框内','crs-btn');
  fill.type='button';
  fill.addEventListener('click',()=>{
    helpers.change(s,()=>{node.text=current;});
    dialog.close();
  });
  dialog.panel.append(body);
  const actions=el(doc,'div','','crs-dialog-actions');
  actions.append(copy,again,fill);
  dialog.panel.append(actions);
  return dialog;
}

function openPromptCases(s,node,helpers){
  const doc=s.root.ownerDocument;
  const dialog=openOverlay(doc,hostOf(s),{title:'推荐提示词案例',label:'推荐提示词案例'});
  const rows=PROMPT_CASES.filter(item=>item.modality===node.type);
  const list=el(doc,'div','','crs-case-list');
  for(const item of (rows.length?rows:PROMPT_CASES)){
    const button=el(doc,'button','','crs-case');
    button.type='button';
    button.append(el(doc,'strong',item.title),el(doc,'span',item.text,'crs-case-text'));
    button.addEventListener('click',()=>{
      helpers.change(s,()=>{node.text=item.text;});
      dialog.close();
    });
    list.append(button);
  }
  dialog.panel.append(list);
  const close=el(doc,'button','取消','crs-btn');
  close.type='button';
  close.addEventListener('click',()=>dialog.close());
  dialog.panel.append(close);
  return dialog;
}

function openCustomStyleDialog(s,node,helpers,store,ui){
  const doc=s.root.ownerDocument;
  const dialog=openOverlay(doc,hostOf(s),{title:'自定义风格',label:'自定义风格'});
  const name=el(doc,'input','','crs-field');
  name.setAttribute('aria-label','风格名称');
  name.placeholder='风格名称';
  const prompt=el(doc,'textarea','','crs-field');
  prompt.setAttribute('aria-label','风格描述');
  prompt.placeholder='风格描述';
  const save=el(doc,'button','保存并使用','crs-btn');
  save.type='button';
  save.addEventListener('click',()=>{
    try{
      const row=store.saveCustom({name:name.value,prompt:prompt.value});
      if(ui)ui.openPopover=null;
      helpers.change(s,()=>applyStyleToNode(node,row));
      dialog.close();
    }catch(error){helpers.notice(s,error.message);}
  });
  const cancel=el(doc,'button','取消','crs-btn');
  cancel.type='button';
  cancel.addEventListener('click',()=>dialog.close());
  dialog.panel.append(name,prompt);
  const actions=el(doc,'div','','crs-dialog-actions');
  actions.append(save,cancel);
  dialog.panel.append(actions);
  return dialog;
}

function confirmMixedBinding(s,state){
  const doc=s.root.ownerDocument;
  return new Promise(resolve=>{
    const dialog=openOverlay(doc,hostOf(s),{title:'确认引用对应关系',label:'确认引用对应关系',className:'crs-overlay crs-mixed-dialog'});
    dialog.panel.append(el(doc,'p','请核对序号与资产的对应关系。如有不符，请返回调整资产顺序。确认后引用将固定到对应资产。','crs-mixed-desc'));
    if(state.changed)dialog.panel.append(el(doc,'p','提示词或资产已变化，请重新核对后确认。','crs-mixed-changed'));
    if(state.count)dialog.panel.append(el(doc,'p',`有 ${state.count} 个序号待绑定`,'crs-mixed-pending'));
    state.unbound.forEach((name,index)=>{
      dialog.panel.append(el(doc,'p',`待绑定 #${index+1} @${name}`,'crs-mixed-item'));
    });
    if(state.conflict)dialog.panel.append(el(doc,'p','首尾帧与全能参考不能同时生效，确认后引用将固定到对应资产。','crs-mixed-conflict'));
    const ok=el(doc,'button','确认引用对应关系','crs-btn');
    ok.type='button';
    ok.addEventListener('click',()=>{dialog.close();resolve(true);});
    const back=el(doc,'button','返回','crs-btn');
    back.type='button';
    back.addEventListener('click',()=>{dialog.close();resolve(false);});
    const actions=el(doc,'div','','crs-dialog-actions');
    actions.append(ok,back);
    dialog.panel.append(actions);
  });
}

export function openInputPreflight(s,node,helpers,rules,deps={}){
  const doc=s.root.ownerDocument;
  return new Promise(resolve=>{
    const dialog=openOverlay(doc,hostOf(s),{title:'输入问题',label:'输入问题',className:'crs-overlay crs-preflight'});
    const list=el(doc,'div','','crs-issue-list');
    const guide=el(doc,'section','','crs-ratio-guide');
    guide.append(el(doc,'h4','常见视频/图片比例示例（从窄到宽）'));
    for(const item of RATIO_GUIDE)guide.append(el(doc,'p',`${item.ratio} ${item.label}`,'crs-ratio-row'));
    const crop=el(doc,'button','智能裁剪并创建副本','crs-btn crs-crop-copy');
    crop.type='button';
    crop.title='创建裁剪后的图片副本，并替换当前模型下目标节点的输入。原图片连线将自动断开。';
    const close=el(doc,'button','关闭输入问题','crs-btn');
    close.type='button';
    let issues=collectInputIssues({rules,references:referenceSnapshots(s,node)});
    const paint=()=>{
      list.replaceChildren?.();
      if(!list.replaceChildren){for(const child of [...(list.children||[])])child.remove();}
      if(!issues.length)list.append(el(doc,'p','没有待处理的输入问题'));
      for(const issue of issues)list.append(el(doc,'p',issue.message,'crs-issue'));
      const actionable=issues.some(issue=>issue.repair==='smart_crop');
      crop.disabled=!actionable;
    };
    paint();
    crop.addEventListener('click',async()=>{
      const issue=issues.find(item=>item.repair==='smart_crop');
      if(!issue)return;
      try{
        const norm=smartCropNorm(issue.width,issue.height,issue.targetRatio);
        const px=cropRectPixels(issue.width,issue.height,norm);
        if(!norm||!px)throw new Error('裁剪区域无效');
        const image=imageElementFor(s,issue.mediaId)||{naturalWidth:issue.width,naturalHeight:issue.height,width:issue.width,height:issue.height};
        const blob=await cropImageElement(image,norm,deps.rasterize);
        const upload=deps.uploadImageBlob||(file=>defaultUploadImageBlob(s,file,'裁剪副本.png',helpers));
        const mediaId=await upload(blob,'裁剪副本.png');
        if(!mediaId)throw new Error('裁剪结果素材无效');
        if(!(s.document?.edges||[]).some(edge=>edge.id===issue.edgeId))throw new Error('待替换连线已变化，请重新处理');
        let created=null;
        const mutate=()=>{created=replaceEdgeWithCropCopy(s.document,{edgeId:issue.edgeId,mediaId,norm,idFactory:deps.idFactory});};
        if(typeof helpers.change==='function')helpers.change(s,mutate);
        else mutate();
        if(!created)throw new Error('裁剪副本连线创建失败');
        rememberMediaMetrics(s,mediaId,px.w,px.h);
        issues=collectInputIssues({rules,references:referenceSnapshots(s,node)});
        if(!issues.length){dialog.close();resolve(true);return;}
        paint();
      }catch(error){helpers.notice?.(s,error?.message||'裁剪副本创建失败');}
    });
    close.addEventListener('click',()=>{dialog.close();resolve(false);});
    dialog.panel.append(list,guide);
    const actions=el(doc,'div','','crs-dialog-actions');
    actions.append(crop,close);
    dialog.panel.append(actions);
  });
}

function resolveFocusSource(s,node,extra){
  if(extra?.sourceId)return (s.document?.nodes||[]).find(item=>item.id===extra.sourceId)||null;
  const edges=(s.document?.edges||[]).filter(edge=>edge.target===node?.id&&edge.port!=='derived_from');
  for(const edge of edges){
    const src=(s.document.nodes||[]).find(item=>item.id===edge.source);
    if(src?.type==='image'&&src.media_id)return src;
  }
  if(node?.type==='image'&&node.media_id)return node;
  const images=(s.document?.nodes||[]).filter(item=>item.id!==node?.id&&item.type==='image'&&item.media_id);
  return images.length===1?images[0]:null;
}

function openFocusOverlay(s,generator,source,helpers,deps,extra){
  const doc=s.root.ownerDocument;
  const dialog=openOverlay(doc,hostOf(s),{title:'聚焦模式',label:'聚焦模式',className:'crs-overlay crs-focus-overlay'});
  dialog.panel.append(el(doc,'p','请在图片上框选聚焦区域','crs-focus-hint'));
  dialog.panel.append(el(doc,'p','按ESC键可退出当前模式','crs-focus-esc'));
  const stage=el(doc,'div','','crs-focus-stage');
  const image=el(doc,'img','','crs-focus-image');
  image.alt=source.title||'聚焦截图';
  const url=helpers.mediaContentUrl?.(s,source.media_id);
  if(url)image.src=url;
  image.naturalWidth=extra?.width||image.naturalWidth;
  image.naturalHeight=extra?.height||image.naturalHeight;
  stage.append(image);
  const box=el(doc,'div','','crs-focus-box');
  box.hidden=true;
  stage.append(box);
  let start=null,norm=null;
  const boundsOf=()=>stage.getBoundingClientRect?.()||{left:0,top:0,width:stage.clientWidth||1,height:stage.clientHeight||1};
  stage.addEventListener('pointerdown',event=>{start={x:event.clientX,y:event.clientY};norm=null;box.hidden=true;});
  stage.addEventListener('pointerup',event=>{
    if(!start)return;
    norm=selectionNormFromPointers(boundsOf(),start.x,start.y,event.clientX,event.clientY);
    start=null;
    box.hidden=!norm;
    if(norm){
      box.style.left=`${norm.x*100}%`;
      box.style.top=`${norm.y*100}%`;
      box.style.width=`${norm.w*100}%`;
      box.style.height=`${norm.h*100}%`;
    }
    stage.dataset.norm=norm?JSON.stringify(norm):'';
  });
  const confirm=el(doc,'button','聚焦截图','crs-btn');
  confirm.type='button';
  confirm.addEventListener('click',async()=>{
    if(!norm){helpers.notice(s,'请先框选聚焦区域');return;}
    if(!(image.naturalWidth||image.width)){helpers.notice(s,'图片加载失败');return;}
    try{
      await commitFocusCapture(s,{
        generator,source,norm,image,helpers,replace:Boolean(extra?.replace),
        rasterize:deps.rasterize,uploadImageBlob:deps.uploadImageBlob,idFactory:deps.idFactory,
        width:image.naturalWidth,height:image.naturalHeight,
      });
      dialog.close();
      if(s._crs)s._crs.focusOpen=false;
    }catch(error){helpers.notice(s,error?.message||'裁剪结果上传或保存失败');}
  });
  const exit=el(doc,'button','退出聚焦','crs-btn');
  exit.type='button';
  exit.addEventListener('click',()=>{dialog.close();if(s._crs)s._crs.focusOpen=false;});
  const actions=el(doc,'div','','crs-dialog-actions');
  actions.append(confirm,exit);
  dialog.panel.append(stage,actions);
  s._crs=s._crs||{};
  s._crs.focusOpen=true;
  s._crs.focusClose=()=>{dialog.close();s._crs.focusOpen=false;};
  return dialog;
}

function openFocusActions(s,generator,source,helpers){
  const doc=s.root.ownerDocument;
  const dialog=openOverlay(doc,hostOf(s),{title:'聚焦截图',label:'聚焦截图'});
  const replace=el(doc,'button','替换聚焦截图','crs-btn');
  replace.type='button';
  replace.addEventListener('click',()=>{
    dialog.close();
    const origin=(s.document.nodes||[]).find(node=>node.id===source.params?.vsc_focus_source)||source;
    openFocusOverlay(s,generator,origin,helpers,helpers._crsDeps||{},{replace:true});
  });
  const remove=el(doc,'button','删除聚焦截图','crs-btn');
  remove.type='button';
  remove.addEventListener('click',()=>{
    helpers.change(s,()=>{removeFocusNode(s.document,source.id);});
    helpers.notice(s,'删除成功');
    dialog.close();
  });
  const actions=el(doc,'div','','crs-dialog-actions');
  actions.append(replace,remove);
  dialog.panel.append(el(doc,'p','请在图片生成节点的提示词区域使用聚焦截图'),actions);
  return dialog;
}

export function attachCanvasReferenceStyle(helpers,options={}){
  if(!helpers||helpers._crsAttached)return helpers;
  helpers._crsAttached=true;
  const store=options.store||createStyleStore(options.storage);
  const deps={rasterize:options.rasterize,uploadImageBlob:options.uploadImageBlob,idFactory:options.idFactory};
  helpers._crsDeps=deps;
  let slotCtx=null;
  helpers.mountStyleLibrarySlot=payload=>{
    slotCtx={...payload,helpers,store,doc:payload.doc||payload.root?.ownerDocument};
    ensureCustomTab(slotCtx);
    paintStyleCards(slotCtx);
  };
  helpers.filterStyleLibrary=query=>{
    if(!slotCtx)return;
    slotCtx.query=query;
    if(slotCtx.ui)slotCtx.ui.styleQuery=query;
    paintStyleCards(slotCtx);
  };
  helpers.openCustomStyle=({s,node,ui}={})=>openCustomStyleDialog(s,node,helpers,store,ui);
  helpers.styleLabelFor=(styleId,node)=>styleLabelFor(styleId,node,[...BUILTIN_STYLES,...(store.read().custom||[])]);
  helpers.clearGeneratorStyle=node=>clearGeneratorStyle(node);
  helpers.beginReferencePick=(s,node)=>{
    if(s.readOnly){helpers.notice(s,'已退出参考选择');return;}
    s.referencePick={targetId:node.id};
    helpers.notice(s,'从画布选择参考');
    helpers.draw(s);
  };
  helpers.openFocusCapture=(s,node,extra={})=>{
    const source=resolveFocusSource(s,node,extra);
    if(!source||source.type!=='image'||!source.media_id){
      helpers.notice(s,'请选择一张图像进行「局部框选」操作');
      return null;
    }
    if(source.params?.vsc_focus_capture==='1'&&!extra.force)return openFocusActions(s,node,source,helpers);
    return openFocusOverlay(s,node,source,helpers,deps,extra);
  };
  helpers.focusReferenceSource=(s,source,generator)=>{
    s.referenceReturn={generatorId:generator.id};
    s.selected=new Set([source.id]);
    helpers.notice(s,'已聚焦到所选节点');
    helpers.draw(s);
  };
  helpers.generationBlockReason=node=>generationBlockReason(node);
  helpers.bindPromptMentions=(textarea,payload)=>bindPromptMentions(textarea,{...payload,helpers,doc:payload.doc||textarea.ownerDocument});
  helpers.mountPromptTools=payload=>{
    const {root,node,promptInput,s,doc}=payload;
    const sheet=doc||root?.ownerDocument;
    if(promptInput)bindPromptMentions(promptInput,{...payload,helpers,doc:sheet});
    const assist=s.composerRunOptions?.prompt_assist;
    const known=assist&&Object.prototype.hasOwnProperty.call(assist,'optimize_available');
    const state=optimizeButtonState({
      available:known?Boolean(assist.optimize_available):(assist?false:null),
      reason:assist?.optimize_unavailable_reason,
      count:s._crs?.optimizeCounts?.[node.id]||0,
      checking:!s.composerRunOptions,
    });
    const optimize=el(sheet,'button','提示词优化','crs-btn crs-optimize');
    optimize.type='button';
    optimize.disabled=Boolean(s.readOnly||state.disabled);
    optimize.title=state.title;
    optimize.addEventListener('click',async()=>{
      try{
        const text=await runOptimize(s,node,helpers,promptInput);
        if(text)openOptimizeDialog(s,node,helpers,promptInput,text);
      }catch(error){if(helpers.live(s))helpers.notice(s,error?.message||'提示词优化失败，请稍后重试');}
    });
    const cases=el(sheet,'button','推荐提示词案例','crs-btn crs-cases');
    cases.type='button';
    cases.addEventListener('click',()=>openPromptCases(s,node,helpers));
    root.append(optimize,cases);
    if(resolveNodeKind(node)==='source'){
      const note=el(sheet,'p','素材节点不能发起生成','crs-source-note');
      const derive=el(sheet,'button','图生图','crs-btn crs-i2i');
      derive.type='button';
      derive.addEventListener('click',()=>{
        helpers.change(s,()=>{
          const created=spawnImageToImage(s.document,node,deps.idFactory||newId);
          s.selected=new Set([created.id]);
        });
      });
      root.append(note,derive);
    }
  };
  helpers.beforeGeneratorSubmit=async(s,node,passedHelpers,eff)=>{
    const apiHelpers=passedHelpers||helpers;
    const live=s.inspector?.querySelector?.('[aria-label="文本或提示词"]');
    const liveText=live&&typeof live.value==='string'?live.value:String(node.text||'');
    const probe={...node,text:liveText,params:node.params};
    const mixed=mixedBindingState(probe,s.document);
    if(mixed.pending){
      const accepted=await confirmMixedBinding(s,mixed);
      if(!accepted){apiHelpers.notice(s,'请先确认提示词中的引用对应关系。');return {ok:false};}
      apiHelpers.change(s,()=>{
        node.text=liveText;
        node.params.vsc_mixed_sig=mixed.signature;
      });
      if(!apiHelpers.live(s))return {ok:false};
    }
    const modelId=eff?.modelId||node.params?.vsc_gen_model_id;
    const rules=inputRulesFor(s.composerRunOptions,modelId);
    const issues=collectInputIssues({rules,references:referenceSnapshots(s,node)});
    if(!issues.length)return {ok:true};
    const fixed=await openInputPreflight(s,node,apiHelpers,rules,deps);
    return {ok:fixed!==false&&apiHelpers.live(s)};
  };
  return helpers;
}
