// AI 角色合成台 and API 接口配置 views, ported from ai-pose-gallery studio/settings.
import {openAssetImageViewer} from './asset-center.js';
import {PROVIDER_META,PROVIDER_ORDER,STYLE_PRESETS,referenceImageUrl,poseThumbPath,poseImagePath,selectCostumeView,uploadedReferences,fileToDataUrl,
 detectComfyUi,fetchComfyObjectInfo,checkComfyWorkflow,comparisonReferences,recipeImageList} from './character-studio-ai.js';
import {COMFYUI_WORKFLOW_TEMPLATES,parseComfyWorkflowNodes as parseNodes,autoDetectComfyMappings,getWorkflowControls,getWorkflowImages,workflowIdentity,validControlValue,validateReferenceCombinations} from './character-studio-workflows.js';
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

export function createCharacterStudio(root,ctx){
 let mode='studio',disposed=false,renderSig='',settingsProvider=null,showKey=false,objectInfo=null,objectInfoIdentity='',checkResult=null,busy=new Set(),scopes={portrait:'similar',costume:'similar',pose:'similar'},unsub=null,pasteHandler=null,progressNode=null,errorNode=null;
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
   const img=el('img');img.src=slot==='pose'?referenceImageUrl(poseThumbPath(item)):referenceImageUrl(item.缩略图||item.预览图||item.原图);img.alt=SLOT_LABEL[slot];img.loading='lazy';thumb.append(img);
   thumb.onclick=()=>zoom(slot==='pose'?poseImagePath(item):slot==='costume'?item.预览图||item.原图||item.缩略图:item.原图||item.缩略图,SLOT_LABEL[slot]);
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
  if(p==='gpt'){
   const g=cfg.gptParams;
   box.append(field('接口模式',select([['images_edits_json','/v1/images/edits JSON（URL 直传）'],['images_edits','/v1/images/edits multipart'],['responses','/v1/responses'],['chat','Chat Completions 中转']],g.endpointMode,up('gptParams','endpointMode'))),
    field('输出尺寸 (size)',select([['1024x1536','1024x1536'],['1024x1024','1024x1024'],['1536x1024','1536x1024'],['auto','auto']],g.size,up('gptParams','size'))),
    field('渲染质量 (quality)',select(['high','xhigh','max','medium','low','auto'].map(v=>[v,v]),g.quality,up('gptParams','quality'))),
    field('参考还原度 (input_fidelity)',select([['high','high'],['low','low']],g.inputFidelity,up('gptParams','inputFidelity'))),
    field('背景模式 (background)',select(['auto','transparent','opaque'].map(v=>[v,v]),g.background,up('gptParams','background'))),
    field('图片格式 (output_format)',select(['png','webp','jpeg'].map(v=>[v,v]),g.outputFormat,up('gptParams','outputFormat'))));
  }else if(p==='gemini'){
   const g=cfg.geminiParams;
   box.append(field('接口模式',select([['native','原生 generateContent'],['openai_chat','OpenAI 兼容 Chat']],g.endpointMode,up('geminiParams','endpointMode'))),
    field('画幅比例',select(['3:4','1:1','4:3','9:16','16:9'].map(v=>[v,v]),g.aspectRatio,up('geminiParams','aspectRatio'))),
    field('分辨率 (Gemini 3)',select(['1K','2K','4K'].map(v=>[v,v]),g.imageSize,up('geminiParams','imageSize'))));
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
  }else{
   const c=cfg.comfyuiParams,nodes=parseNodes(c.workflowJson);
   const timeout=el('input');timeout.type='number';timeout.min='60';timeout.step='30';timeout.value=String(c.timeoutSec||600);timeout.dataset.focusKey='comfy-timeout';
   timeout.onchange=()=>store.updateParams('comfyuiParams',{timeoutSec:Math.max(60,Number(timeout.value)||600)});
   box.append(field('三合一拼图节点 (可选)',select([['none','不绑定'],...nodes.imageNodes.map(n=>[n.id,`#${n.id} ${n.title}`])],c.stitchedNodeId,up('comfyuiParams','stitchedNodeId'))),
    field('最长等待时间（秒）',timeout),
    field('随机种子 (seed)',toggle(c.randomizeSeed,up('comfyuiParams','randomizeSeed'),c.randomizeSeed?'每次随机':'保持工作流种子')));
  }
  if(p!=='comfyui'){
   box.append(field('图片传参方式',select([['url','URL'],['base64','Base64']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))),
    field('附带合成拼图',toggle(cfg.sendStitchedSheet,v=>store.updateApiConfig({sendStitchedSheet:v}),cfg.sendStitchedSheet?'附带':'不附带')),
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用':'浏览器直连')));
  }
  return box;
 }

 function comfyPanel(){
  const cfg=state().apiConfig,c=cfg.comfyuiParams,wrap=el('div','cs-comfy');
  const presets=[...Object.entries(COMFYUI_WORKFLOW_TEMPLATES).map(([id,t])=>[id,t.label]),['custom','自定义工作流（已导入 JSON）']];
  wrap.append(field('工作流模板 (API 格式)',select(presets,c.workflowPreset,value=>{
   if(value==='custom')return;
   const tpl=COMFYUI_WORKFLOW_TEMPLATES[value];objectInfo=null;checkResult=null;
   store.updateParams('comfyuiParams',{workflowPreset:value,workflowJson:JSON.stringify(tpl.workflow,null,2),...tpl.defaults,parameterOverrides:undefined});notice(`已切换为：${tpl.label}`);
  })));
  const tools=el('div','cs-row-actions');
  const importInput=el('input');importInput.type='file';importInput.accept='.json,application/json';importInput.hidden=true;
  importInput.onchange=async()=>{const f=importInput.files?.[0];importInput.value='';if(!f)return;try{applyWorkflowJson(await f.text(),f.name);}catch{notice('读取 JSON 文件失败');}};
  tools.append(importInput,action('导入 JSON',()=>importInput.click()),action('编辑 JSON',()=>jsonEditor()),
   action('导出 JSON',()=>{try{JSON.parse(c.workflowJson);const blob=new Blob([c.workflowJson],{type:'application/json'}),url=URL.createObjectURL(blob);download(url,`comfyui-workflow-${Date.now()}.json`);setTimeout(()=>URL.revokeObjectURL(url),1500);notice('已导出 ComfyUI API 工作流 JSON');}catch{notice('当前工作流 JSON 格式有误，无法导出');}}),
   action('检测本机模型',async()=>{
    const p=cfg.providers.comfyui;
    objectInfo=await fetchComfyObjectInfo(p.baseUrl,p.apiKey,c.workflowJson);objectInfoIdentity=workflowIdentity(c.workflowJson);
    checkResult=await checkComfyWorkflow(p.baseUrl,p.apiKey,c.workflowJson,[c.portraitNodeId,c.costumeNodeId,c.poseNodeId,c.stitchedNodeId],objectInfo);
    if(checkResult.fixedJson)store.updateParams('comfyuiParams',{workflowJson:checkResult.fixedJson,workflowPreset:'custom'});
    notice(checkResult.ok?'工作流与本机模型匹配':'工作流与本机不匹配，请查看检测结果');
   },'','comfy-check'));
  wrap.append(tools);
  if(checkResult){
   const box=el('div','cs-check '+(checkResult.ok?'is-ok':'is-error'));
   box.append(el('strong','',checkResult.ok?'检测通过':'检测未通过'));
   for(const line of [...checkResult.errors,...checkResult.warnings,...checkResult.fixes])box.append(el('p','',line));
   wrap.append(box);
  }
  const nodes=parseNodes(c.workflowJson);
  if(!nodes.valid)wrap.append(el('p','cs-error',nodes.error||'工作流 JSON 无效'));
  const imageOpts=[['none','不绑定'],...nodes.imageNodes.map(n=>[n.id,`#${n.id} ${n.title}`])];
  const grid=el('div','cs-grid2');
  for(const [key,label]of [['portraitNodeId','人像图节点 (LoadImage)'],['costumeNodeId','服装图节点 (LoadImage)'],['poseNodeId','姿势图节点 (LoadImage)']])
   grid.append(field(label,select(imageOpts,c[key],v=>store.updateParams('comfyuiParams',{[key]:v}))));
  grid.append(field('正向提示词节点 (Prompt)',select([['none','不绑定'],...nodes.promptNodes.map(n=>[n.id,`#${n.id} ${n.title} · ${n.field}`])],c.promptNodeId,v=>store.updateParams('comfyuiParams',{promptNodeId:v}))));
  wrap.append(grid,action('重新识别节点',()=>{store.updateParams('comfyuiParams',autoDetectComfyMappings(c.workflowJson));notice('已重新识别节点映射');}));
  if(objectInfo&&objectInfoIdentity===workflowIdentity(c.workflowJson)){
   const mapped=[c.portraitNodeId,c.costumeNodeId,c.poseNodeId,c.stitchedNodeId];
   const images=getWorkflowImages(c.workflowJson,mapped,objectInfo);
   if(images.length){
    const box=el('div','cs-workflow-images');box.append(el('h3','','工作流附加图片'));
    const identity=workflowIdentity(c.workflowJson),current=state().recipe.workflowImagesIdentity===identity?state().recipe.workflowImages||{}:{};
    for(const node of images){
     const row=el('div','cs-workflow-image'),img=current[node.nodeId];
     row.append(el('span','',`${node.label}${node.optional?'（可选）':''}`));
     if(img){const t=el('img');t.src=referenceImageUrl(img.url);t.alt=node.label;row.append(t,action('移除',()=>store.setWorkflowImage(node.nodeId,null,identity)));}
     const up=el('label','cs-upload-btn','上传');const f=el('input');f.type='file';f.accept='image/*';
     f.onchange=async()=>{const file=f.files?.[0];f.value='';if(!file)return;const {url}=await fileToDataUrl(file);store.setWorkflowImage(node.nodeId,{id:crypto.randomUUID(),name:node.label,url,...(node.role?{role:node.role}:{})},identity);};
     up.append(f);row.append(up);box.append(row);
    }
    wrap.append(box);
   }
   const excluded=new Set([...mapped.filter(id=>id&&id!=='none').map(id=>`${id}.image`),c.promptNodeId&&c.promptNodeId!=='none'?nodes.promptNodes.filter(n=>n.id===c.promptNodeId).map(n=>`${n.id}.${n.field}`)[0]:'']);
   const controls=getWorkflowControls(c.workflowJson,objectInfo,excluded);
   if(controls.length){
    const details=el('details','cs-workflow-params');details.append(el('summary','',`工作流参数 (${controls.length})`));
    const saved=c.parameterOverrides?.workflowId===workflowIdentity(c.workflowJson)?c.parameterOverrides.values||{}:{};
    const grid2=el('div','cs-grid2');
    for(const control of controls){
     const current=saved[control.nodeId]?.[control.input]??control.value;
     const save=value=>{
      if(!validControlValue(control,value)){notice('参数值超出允许范围');return;}
      const values=JSON.parse(JSON.stringify(saved));values[control.nodeId]={...(values[control.nodeId]||{}),[control.input]:value};
      store.updateParams('comfyuiParams',{parameterOverrides:{workflowId:workflowIdentity(c.workflowJson),values}});
     };
     let input;
     if(control.type==='enum')input=select(control.options.map(o=>[JSON.stringify(o),control.optionLabels?.[JSON.stringify(o)]||String(o)]),JSON.stringify(current),v=>save(JSON.parse(v)));
     else if(control.type==='boolean')input=toggle(current,save,current?'开启':'关闭');
     else if(control.type==='number'){input=el('input');input.type='number';input.value=String(current);if(control.min!=null)input.min=String(control.min);if(control.max!=null)input.max=String(control.max);if(control.step!=null)input.step=String(control.step);input.onchange=()=>save(Number(input.value));}
     else{input=el(control.multiline?'textarea':'input');input.value=String(current);input.onchange=()=>save(input.value);}
     input.dataset.focusKey='wf-'+control.key;
     grid2.append(field(control.label,input,control.description));
    }
    details.append(grid2);wrap.append(details);
   }
  }
  return wrap;
 }
 function applyWorkflowJson(text,name='工作流'){
  const info=parseNodes(text);
  if(!info.valid){notice(info.error||'工作流 JSON 无效');return false;}
  objectInfo=null;checkResult=null;
  store.updateParams('comfyuiParams',{workflowPreset:'custom',workflowJson:JSON.stringify(JSON.parse(text),null,2),...autoDetectComfyMappings(text),parameterOverrides:undefined});
  notice(`已导入${name}：识别到 ${info.imageNodes.length} 个图片节点、${info.promptNodes.length} 个提示词节点`);return true;
 }
 function jsonEditor(){
  const dialog=el('dialog','cs-dialog cs-json');dialog.setAttribute('aria-label','编辑工作流 JSON');
  const head=el('header','cs-dialog-head');head.append(el('h2','','编辑 ComfyUI API 工作流 JSON'),action('×',()=>dialog.close(),'cs-icon-btn'));
  const area=el('textarea');area.value=state().apiConfig.comfyuiParams.workflowJson;area.spellcheck=false;
  const status=el('p','cs-field-hint','请粘贴「工作流 → 导出 (API)」得到的 JSON。');
  area.oninput=()=>{const info=parseNodes(area.value);status.textContent=info.valid?`有效：${info.imageNodes.length} 个图片节点、${info.promptNodes.length} 个提示词节点`:info.error;};
  const foot=el('footer','cs-dialog-foot');foot.append(action('应用',()=>{if(applyWorkflowJson(area.value,'编辑后的工作流'))dialog.close();},'cs-primary'),action('取消',()=>dialog.close()));
  dialog.append(head,area,status,foot);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal?.();
 }

 function connectionStatus(){
  const conn=state().comfyConnection,box=el('div','cs-conn is-'+conn.status);box.setAttribute('role','status');
  box.append(el('span','cs-conn-badge',`ComfyUI · ${store.COMFY_CONNECTION_LABELS[conn.status]||conn.status}`));
  if(conn.info&&conn.status==='connected')box.append(el('span','',conn.info));
  if(conn.error)box.append(el('span','cs-error',conn.error));
  box.append(el('small','',conn.checkedAt?`最近检测 ${new Date(conn.checkedAt).toLocaleTimeString()}；HTTP 检测不代表任务 WebSocket 已连接`:'尚无检测记录'));
  box.append(action('检测连接',()=>store.checkComfyConnection(),'','comfy-conn'));
  return box;
 }

 function engineSection(){
  const cfg=state().apiConfig,p=cfg.activeProvider,meta=PROVIDER_META[p],pc=cfg.providers[p];
  const keyBtn=action('配置 Key',()=>{settingsProvider=p;ctx.navigate?.('api-settings');},'cs-ghost');
  const sec=section('2. 生图引擎与参数',{actions:keyBtn});
  const grid=el('div','cs-grid2');
  grid.append(field('接口协议',select(PROVIDER_ORDER.map(id=>{const conf=id==='comfyui'?'':cfg.providers[id].apiKey.trim()?' · 已配置':' · 未配置 Key';return [id,PROVIDER_META[id].name+conf];}),p,v=>store.updateApiConfig({activeProvider:v}))));
  grid.append(field('画风预设',select(Object.entries(STYLE_PRESETS).map(([k,v])=>[k,v.label]),cfg.stylePreset,v=>store.updateApiConfig({stylePreset:v}))));
  if(p!=='comfyui'){
   grid.append(field('模型 ID',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>store.updateProviderConfig(p,{model:v}))));
   if(pc.model==='custom'){const input=el('input');input.value=pc.customModel;input.placeholder='输入模型 ID';input.dataset.focusKey='custom-model';input.onchange=()=>store.updateProviderConfig(p,{customModel:input.value});grid.append(field('自定义模型 ID',input));}
   if(!pc.apiKey.trim())sec.body.append(el('p','cs-warn',`尚未配置 ${meta.name} 的 API Key，请点击右上角「配置 Key」。`));
  }
  sec.body.append(grid);
  if(p==='comfyui'){sec.body.append(connectionStatus(),comfyPanel());}
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
  const gen=action(s.isGenerating?'生成中…':`生成角色图${count?` (${count} 张参考)`:''}`,async()=>{
   const cfg=s.apiConfig;
   if(cfg.activeProvider==='comfyui'){
    const c=cfg.comfyuiParams,missing=[['portraitNodeId','portrait'],['costumeNodeId','costume'],['poseNodeId','pose']].filter(([k,slot])=>c[k]&&c[k]!=='none'&&!s.recipe[slot]).map(([,slot])=>SLOT_LABEL[slot]);
    if(missing.length){notice(`当前工作流需要：${missing.join('、')}参考图`);return;}
    const combo=validateReferenceCombinations(c.workflowJson,[['portraitNodeId','portrait'],['costumeNodeId','costume'],['poseNodeId','pose']].filter(([k,slot])=>c[k]&&c[k]!=='none'&&s.recipe[slot]).map(([k])=>c[k]));
    if(combo){notice(combo);return;}
   }
   await store.startGeneration();
  },'cs-primary cs-generate');
  gen.disabled=s.isGenerating||!s.hydrated||Boolean(s.activeTask);
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
  if(p?.connection)progressNode.append(el('small','',{connecting:'正在连接任务通道',connected:'任务通道已连接',reconnecting:'任务通道重连中',degraded:'任务通道不稳定，改用 HTTP 轮询'}[p.connection]||''));
  const bar=el('div','cs-bar'),fill=el('span');bar.append(fill);
  if(typeof p?.percent==='number'){fill.style.width=`${Math.max(2,Math.min(100,p.percent))}%`;}else bar.classList.add('is-indeterminate');
  progressNode.append(bar);
 }
 function taskSection(){
  const s=state();if(!s.activeTask)return null;
  const sec=section('待确认任务');
  sec.body.append(el('p','',s.activeTask.task?`ComfyUI 任务 ${s.activeTask.task.promptId}（${s.activeTask.summary}）`:'上次提交结果未知：服务端可能已接受任务，请先检查 ComfyUI 队列与历史记录。'));
  const acts=el('div','cs-row-actions');
  if(s.activeTask.task)acts.append(action('恢复跟踪',()=>store.resumeGeneration(),'cs-primary'));
  acts.append(action('停止跟踪',()=>store.stopTracking()));
  sec.body.append(acts);return sec.node;
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
  const title=el('div','cs-title');title.append(el('h1','','AI 角色合成台'),el('p','','从人像颜值库、服装穿搭库、动作姿势库挑选参考，组合生成角色图。API Key 仅保存在本机浏览器。'));
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
  right.append(resultSection());const task=taskSection();if(task)right.append(task);right.append(historySection());
  cols.append(left,right);page.append(cols);
  return page;
 }

 // ------------------------------------------------------------------ settings
 function settingsView(){
  const cfg=state().apiConfig,pid=settingsProvider||cfg.activeProvider,meta=PROVIDER_META[pid],pc=cfg.providers[pid];
  const page=el('div','cs-page cs-settings');
  const head=el('header','cs-page-head');
  const title=el('div','cs-title');title.append(el('h1','','API 接口配置'),el('p','','五种生图接口的连接设置。API Key 只保存在当前浏览器本地存储，不上传到 VSC 服务器或作品数据库。'));
  head.append(title,action('返回 AI 角色合成台',()=>ctx.navigate?.('character-studio'),'cs-primary'));page.append(head);
  const tabs=el('div','cs-provider-tabs');tabs.setAttribute('role','tablist');
  for(const id of PROVIDER_ORDER){
   const m=PROVIDER_META[id],hasKey=id==='comfyui'?Boolean(cfg.providers.comfyui.baseUrl.trim()):Boolean(cfg.providers[id].apiKey.trim());
   const status=id==='comfyui'?store.COMFY_CONNECTION_LABELS[state().comfyConnection.status]:hasKey?'已配置':'未配置 Key';
   const b=el('button','cs-provider-tab');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(pid===id));
   const text=el('span','cs-provider-text');text.append(el('strong','',m.name),el('small','',status));
   const dot=el('span','cs-dot'+(id==='comfyui'&&state().comfyConnection.status==='connected'?' is-ok':hasKey?' is-set':''));dot.title=status;
   b.append(text,dot);
   b.onclick=()=>{settingsProvider=id;store.updateApiConfig({activeProvider:id});if(id==='comfyui')store.checkComfyConnection();};
   tabs.append(b);
  }
  page.append(tabs);
  if(pid==='comfyui')page.append(connectionStatus());
  const acts=el('div','cs-row-actions');
  if(pid==='comfyui')acts.append(action('自动检测端口',async()=>{const found=await detectComfyUi(pc.baseUrl,pc.apiKey);if(!found){notice('未检测到可用的 ComfyUI，请确认已启动');return;}store.updateProviderConfig('comfyui',{baseUrl:found.baseUrl});notice(`已自动识别 ComfyUI 地址：${found.baseUrl}（${found.info}）`);store.checkComfyConnection();},'','detect-comfy'));
  const doc=el('a','cs-link','文档');doc.href=meta.docUrl;doc.target='_blank';doc.rel='noreferrer';acts.append(doc);
  acts.append(action('恢复默认',()=>{store.updateProviderConfig(pid,{baseUrl:meta.defaultBaseUrl,model:meta.models[0].value});notice('已恢复默认');}));
  const sec=section(`${meta.name} 连接配置`,{actions:acts});
  const base=el('input');base.type=pid==='comfyui'?'text':'url';base.value=pc.baseUrl;base.placeholder=meta.defaultBaseUrl;base.dataset.focusKey='set-base';
  base.onchange=()=>store.updateProviderConfig(pid,{baseUrl:base.value});
  sec.body.append(field(pid==='comfyui'?'ComfyUI 地址 (Base URL)':'Base URL',base,pid==='comfyui'?`默认 /comfy（VSC 同源代理，依次连接本机 8000 / 8188 端口，可用环境变量 COMFYUI_URL 指定）；直连时 ComfyUI 需加启动参数 --enable-cors-header "${typeof window!=='undefined'?window.location.origin:'*'}"。`:undefined));
  const keyWrap=el('div','cs-key'),key=el('input');key.type=showKey?'text':'password';key.value=pc.apiKey;key.autocomplete='off';key.dataset.focusKey='set-key';
  key.placeholder=pid==='comfyui'?'本地 ComfyUI 无需填写，远程鉴权可填 Token':'输入 API Key（仅保存在本地浏览器）';
  key.onchange=()=>store.updateProviderConfig(pid,{apiKey:key.value.trim()});
  const eye=el('button','cs-icon-btn',showKey?'隐藏':'显示');eye.type='button';eye.setAttribute('aria-label',showKey?'隐藏 API Key':'显示 API Key');eye.onclick=()=>{showKey=!showKey;render(true);};
  keyWrap.append(key,eye);
  sec.body.append(field(pid==='comfyui'?'API Key（可选，本地留空）':'API Key',keyWrap,'Key 保存在浏览器 localStorage；清除浏览器数据会一并删除。请勿在共享电脑上保存。'));
  if(pid!=='comfyui'){
   sec.body.append(field('默认模型 ID',select(meta.models.map(m=>[m.value,m.label]),pc.model,v=>store.updateProviderConfig(pid,{model:v}))));
   if(pc.model==='custom'){const custom=el('input');custom.value=pc.customModel;custom.placeholder=pid==='doubao'?'ep-2026xxxx 或模型 ID':'输入模型 ID';custom.dataset.focusKey='set-custom';custom.onchange=()=>store.updateProviderConfig(pid,{customModel:custom.value});sec.body.append(field('自定义模型 ID',custom));}
  }else sec.body.append(el('p','cs-field-hint','模型由工作流决定。请返回合成台导入工作流，并设置人像、服装和姿势节点。'));
  page.append(sec.node);
  if(pid!=='comfyui'){
   const g=section('全局请求选项');
   g.body.append(field('参考图传参方式',select([['url','传递图片 URL（免上传文件，推荐）'],['base64','转 Base64 编码传输']],cfg.imagePassMode,v=>store.updateApiConfig({imagePassMode:v}))),
    field('服务端 CORS 代理 (/api/proxy)',toggle(cfg.useProxy,v=>store.updateApiConfig({useProxy:v}),cfg.useProxy?'已启用（解决跨域限制）':'已关闭（浏览器直连）'),'默认关闭（浏览器直连）；切换到阿里云百炼 (Qwen) 或火山方舟 (Doubao) 时会自动开启。仅转发白名单 HTTPS 域名（服务端环境变量 PROXY_ALLOWED_ORIGINS 可扩展）。'));
   page.append(g.node);
  }
  const foot=el('div','cs-row-actions cs-end');foot.append(action('保存配置',()=>{const active=document.activeElement;active?.dispatchEvent?.(new Event('change'));notice('配置已保存（仅本机浏览器）');},'cs-primary'));
  page.append(foot);
  return page;
 }

 // ------------------------------------------------------------------ render loop
 function signature(){
  const s=state();
  return JSON.stringify([mode,settingsProvider,showKey,[...busy],s.recipe,s.apiConfig,s.history.map(h=>h.id),s.safeMode,s.poseDepthMode,s.customPrompt,s.previewUrl,s.isGenerating,s.generationError,s.activeTask,s.hydrated,s.comfyConnection,Boolean(objectInfo),checkResult]);
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
  async load({mode:nextMode='studio'}={}){
   disposed=false;mode=nextMode==='settings'?'settings':'studio';
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
   if(state().apiConfig.activeProvider==='comfyui'||mode==='settings'&&(settingsProvider||state().apiConfig.activeProvider)==='comfyui')store.checkComfyConnection();
   render(true);
  },
  suspend(){
   disposed=true;unsub?.();unsub=null;
   if(pasteHandler){document.removeEventListener('paste',pasteHandler);pasteHandler=null;}
   for(const d of document.querySelectorAll('dialog.cs-dialog'))d.close?.();
  },
  stitchList:()=>recipeImageList(state().recipe),
 };
}
