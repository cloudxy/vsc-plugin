// ComfyUI workflow presets for the character studio. The default preset is the
// MIT-licensed Qwen Image Edit 2509 three-image API workflow from ai-pose-gallery.
export const QWEN_2509_3IMG_WORKFLOW={"1":{"class_type":"LoadImage","inputs":{"image":"portrait_ref.png"},"_meta":{"title":"图1：人像参考 (Portrait)"}},"2":{"class_type":"LoadImage","inputs":{"image":"costume_ref.png"},"_meta":{"title":"图2：服装参考 (Costume)"}},"3":{"class_type":"LoadImage","inputs":{"image":"pose_ref.png"},"_meta":{"title":"图3：姿势参考 (Pose)"}},"4":{"class_type":"UNETLoader","inputs":{"unet_name":"qwen_image_edit_2509_fp8_e4m3fn.safetensors","weight_dtype":"default"},"_meta":{"title":"加载 Qwen Image Edit 2509 模型"}},"5":{"class_type":"LoraLoaderModelOnly","inputs":{"model":["4",0],"lora_name":"Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors","strength_model":1.0},"_meta":{"title":"Lightning 4 步加速 LoRA (2509 专用)"}},"6":{"class_type":"ModelSamplingAuraFlow","inputs":{"model":["5",0],"shift":3.0},"_meta":{"title":"ModelSamplingAuraFlow"}},"7":{"class_type":"CFGNorm","inputs":{"model":["6",0],"strength":1.0},"_meta":{"title":"CFGNorm"}},"8":{"class_type":"CLIPLoader","inputs":{"clip_name":"qwen_2.5_vl_7b_fp8_scaled.safetensors","type":"qwen_image","device":"default"},"_meta":{"title":"加载 Qwen2.5-VL 7B 文本编码器"}},"9":{"class_type":"VAELoader","inputs":{"vae_name":"qwen_image_vae.safetensors"},"_meta":{"title":"加载 Qwen Image VAE"}},"10":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["3",0],"upscale_method":"lanczos","megapixels":1.0,"resolution_steps":16},"_meta":{"title":"按姿势图比例确定输出尺寸 (megapixels 越小越省显存)"}},"11":{"class_type":"VAEEncode","inputs":{"pixels":["10",0],"vae":["9",0]},"_meta":{"title":"输出画布 Latent"}},"12":{"class_type":"TextEncodeQwenImageEditPlus","inputs":{"clip":["8",0],"image1":["1",0],"image2":["2",0],"image3":["3",0],"prompt":""},"_meta":{"title":"正向提示词 (Positive Prompt，三图均送入视觉语言编码器)"}},"13":{"class_type":"TextEncodeQwenImageEditPlus","inputs":{"clip":["8",0],"image1":["1",0],"image2":["2",0],"image3":["3",0],"prompt":""},"_meta":{"title":"反向提示词 (Negative Prompt，cfg=1 时不生效)"}},"14":{"class_type":"KSampler","inputs":{"model":["7",0],"positive":["25",0],"negative":["27",0],"latent_image":["11",0],"seed":20261031,"steps":4,"cfg":1.0,"sampler_name":"euler","scheduler":"simple","denoise":1.0},"_meta":{"title":"KSampler (4 步 Lightning)"}},"15":{"class_type":"VAEDecode","inputs":{"samples":["14",0],"vae":["9",0]},"_meta":{"title":"VAE 解码"}},"16":{"class_type":"SaveImage","inputs":{"images":["15",0],"filename_prefix":"pose_studio/result"},"_meta":{"title":"保存生成结果"}},"20":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["1",0],"upscale_method":"lanczos","megapixels":1.0,"resolution_steps":16},"_meta":{"title":"人像参考缩放"}},"21":{"class_type":"VAEEncode","inputs":{"pixels":["20",0],"vae":["9",0]},"_meta":{"title":"人像参考 Latent"}},"22":{"class_type":"ImageScaleToTotalPixels","inputs":{"image":["2",0],"upscale_method":"lanczos","megapixels":1.0,"resolution_steps":16},"_meta":{"title":"服装参考缩放"}},"23":{"class_type":"VAEEncode","inputs":{"pixels":["22",0],"vae":["9",0]},"_meta":{"title":"服装参考 Latent"}},"24":{"class_type":"ReferenceLatent","inputs":{"conditioning":["12",0],"latent":["21",0]},"_meta":{"title":"正向：附加人像参考"}},"25":{"class_type":"ReferenceLatent","inputs":{"conditioning":["24",0],"latent":["23",0]},"_meta":{"title":"正向：附加服装参考"}},"26":{"class_type":"ReferenceLatent","inputs":{"conditioning":["13",0],"latent":["21",0]},"_meta":{"title":"反向：附加人像参考"}},"27":{"class_type":"ReferenceLatent","inputs":{"conditioning":["26",0],"latent":["23",0]},"_meta":{"title":"反向：附加服装参考"}}};

// ---------------------------------------------------------------------------
// Workflow templates, node parsing and parameter overrides (ported from the
// ai-pose-gallery studio; logic kept identical so saved configs stay valid).
// ---------------------------------------------------------------------------
const clone=value=>JSON.parse(JSON.stringify(value));

function buildQwen2509TwoImage(){
 const wf=clone(QWEN_2509_3IMG_WORKFLOW);
 for(const id of ['2','22','23','25','27'])delete wf[id];
 wf['1']._meta={title:'图1：人物/服装参考 (Person)'};
 wf['3']._meta={title:'图2：姿势参考 (Pose)'};
 for(const id of ['12','13']){wf[id].inputs.image2=['3',0];delete wf[id].inputs.image3;}
 wf['14'].inputs.positive=['24',0];
 wf['14'].inputs.negative=['26',0];
 return wf;
}

function buildQwen21Workflow(threeImages){
 const wf={
  '1':{inputs:{image:'portrait_ref.png'},class_type:'LoadImage',_meta:{title:threeImages?'图1：人像参考 (Portrait)':'图2：人物/服装参考图 (Person)'}},
  '4':{inputs:{unet_name:'image2image/qwen_image_2.1_bf16.safetensors',weight_dtype:'default'},class_type:'UNETLoader',_meta:{title:'加载 Qwen Image 2.1 基础模型'}},
  '5':{inputs:{model:['4',0],lora_name:'qwen2.1/动作编辑VNCCS_QI2_PoseStudioV2_3294845.safetensors',strength_model:1.0},class_type:'LoraLoaderModelOnly',_meta:{title:'加载姿态编辑 LoRA 适配器 (Qwen 2.1 专用)'}},
  '6':{inputs:{device:'auto',dtype:'default',model:['5',0]},class_type:'QwenImage21Cache',_meta:{title:'Qwen Image 2.1 条件缓存'}},
  '7':{inputs:{clip_name:'text_encoders/qwen3vl_8b_bf16.safetensors',type:'qwen_image',device:'default'},class_type:'CLIPLoader',_meta:{title:'加载 Qwen3-VL 8B 编码器'}},
  '8':{inputs:{vae_name:'vae/qwen_image_2.1_vae_bf16.safetensors'},class_type:'VAELoader',_meta:{title:'加载 Qwen Image 2.1 VAE'}},
  '9':{inputs:{prompt:'',negative_prompt:'',resolution:1024,clip:['7',0],vae:['8',0]},class_type:'TextEncodeQwenImage21',_meta:{title:'正向提示词与多图编码 (Qwen 2.1)'}},
  '10':{inputs:{seed:20261031,steps:25,cfg:1.0,sampler_name:'euler',scheduler:'simple',denoise:1.0,model:['6',0],positive:['9',0],negative:['9',1],latent_image:['9',2]},class_type:'KSampler',_meta:{title:'KSampler 采样器'}},
  '11':{inputs:{samples:['10',0],vae:['8',0]},class_type:'VAEDecode',_meta:{title:'VAE 解码'}},
  '12':{inputs:{filename_prefix:'pose_studio/result',images:['11',0]},class_type:'SaveImage',_meta:{title:'保存生成结果'}},
 };
 if(threeImages){
  wf['2']={inputs:{image:'costume_ref.png'},class_type:'LoadImage',_meta:{title:'图2：服装参考 (Costume)'}};
  wf['3']={inputs:{image:'pose_ref.png'},class_type:'LoadImage',_meta:{title:'图3：姿势参考 (Pose)'}};
  Object.assign(wf['9'].inputs,{'images.image_1':['1',0],'images.image_2':['2',0],'images.image_3':['3',0]});
 }else{
  wf['2']={inputs:{image:'pose_reference.png'},class_type:'LoadImage',_meta:{title:'图1：姿势参考图 (Pose)'}};
  Object.assign(wf['9'].inputs,{'images.image_1':['2',0],'images.image_2':['1',0]});
 }
 return wf;
}

export const DEFAULT_COMFY_PRESET='qwen2509_3img';
export const COMFYUI_WORKFLOW_TEMPLATES={
 qwen2509_3img:{label:'Qwen Image Edit 2509 三图合成（人像+服装+姿势）· 推荐',workflow:QWEN_2509_3IMG_WORKFLOW,defaults:{promptNodeId:'12',portraitNodeId:'1',costumeNodeId:'2',poseNodeId:'3',stitchedNodeId:'none'}},
 qwen2509_2img:{label:'Qwen Image Edit 2509 双图姿态迁移（人物+姿势）',workflow:buildQwen2509TwoImage(),defaults:{promptNodeId:'12',portraitNodeId:'1',costumeNodeId:'none',poseNodeId:'3',stitchedNodeId:'none'}},
 qwen21_3img:{label:'Qwen-Image 2.1 三图合成（需另装 2.1 模型）',workflow:buildQwen21Workflow(true),defaults:{promptNodeId:'9',portraitNodeId:'1',costumeNodeId:'2',poseNodeId:'3',stitchedNodeId:'none'}},
 qwen21_2img:{label:'Qwen-Image 2.1 双图姿态迁移（需另装 2.1 模型）',workflow:buildQwen21Workflow(false),defaults:{promptNodeId:'9',portraitNodeId:'1',costumeNodeId:'none',poseNodeId:'2',stitchedNodeId:'none'}},
};

export function parseComfyWorkflowNodes(workflowJson){
 if(!String(workflowJson||'').trim())return {valid:false,isUiFormat:false,error:'工作流 JSON 为空',imageNodes:[],promptNodes:[]};
 try{
  const parsed=JSON.parse(workflowJson);
  if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))return {valid:false,isUiFormat:false,error:'无效的 JSON 对象',imageNodes:[],promptNodes:[]};
  if(Array.isArray(parsed.nodes)&&Array.isArray(parsed.links))return {valid:false,isUiFormat:true,error:'检测到普通画布格式 JSON，请在 ComfyUI 中使用「工作流 → 导出 (API)」得到 API 格式 JSON',imageNodes:[],promptNodes:[]};
  const imageNodes=[],promptNodes=[];
  for(const [id,node]of Object.entries(parsed)){
   if(!node||typeof node!=='object'||!node.class_type)continue;
   const classType=String(node.class_type),title=String(node._meta?.title||classType),inputs=node.inputs||{};
   if(classType==='LoadImage'||typeof inputs.image==='string'){
    imageNodes.push({id,title,classType,currentImage:String(inputs.image||''),...(classType==='LoadImageGoohai'?{emptyValue:'无'}:{}),...(node._meta?.studio?.imageRole==='character_sheet'?{role:'character_sheet'}:{})});
   }
   for(const field of ['prompt','text','string','positive']){
    if(Array.isArray(node._meta?.studio?.hiddenInputs)&&node._meta.studio.hiddenInputs.includes(field))continue;
    if(typeof inputs[field]==='string'){promptNodes.push({id,title,classType,field});break;}
   }
  }
  if(!imageNodes.length&&!promptNodes.length)return {valid:false,isUiFormat:false,error:'未在 JSON 中找到任何 ComfyUI 节点',imageNodes,promptNodes};
  return {valid:true,isUiFormat:false,imageNodes,promptNodes};
 }catch(err){return {valid:false,isUiFormat:false,error:`JSON 解析失败: ${err?.message||'语法错误'}`,imageNodes:[],promptNodes:[]};}
}

export function autoDetectComfyMappings(workflowJson){
 const parsed=parseComfyWorkflowNodes(workflowJson);
 let promptNodeId='none',portraitNodeId='none',costumeNodeId='none',poseNodeId='none',stitchedNodeId='none';
 const pos=parsed.promptNodes.find(n=>!/negative|反向|负面/i.test(n.title))||parsed.promptNodes[0];
 if(pos)promptNodeId=pos.id;
 const used=new Set(),slots=parsed.imageNodes.filter(n=>n.role!=='character_sheet');
 for(const n of slots){
  if(/人像|脸|人物|portrait|face|person/i.test(n.title)&&portraitNodeId==='none'){portraitNodeId=n.id;used.add(n.id);}
  else if(/服装|衣|穿搭|costume|cloth|outfit/i.test(n.title)&&costumeNodeId==='none'){costumeNodeId=n.id;used.add(n.id);}
  else if(/姿势|动作|骨架|pose/i.test(n.title)&&poseNodeId==='none'){poseNodeId=n.id;used.add(n.id);}
  else if(/拼图|合成|stitch/i.test(n.title)&&stitchedNodeId==='none'){stitchedNodeId=n.id;used.add(n.id);}
 }
 const remaining=slots.filter(n=>!used.has(n.id));
 if(portraitNodeId==='none'&&remaining[0])portraitNodeId=remaining.shift().id;
 if(costumeNodeId==='none'&&remaining[0])costumeNodeId=remaining.shift().id;
 if(poseNodeId==='none'&&remaining[0])poseNodeId=remaining.shift().id;
 return {promptNodeId,portraitNodeId,costumeNodeId,poseNodeId,stitchedNodeId};
}

export function parseParameterWorkflow(json){
 try{
  const value=JSON.parse(json);
  if(!value||typeof value!=='object'||Array.isArray(value)||!Object.keys(value).length)return null;
  if(!Object.values(value).every(node=>node&&typeof node==='object'&&typeof node.class_type==='string'&&node.inputs&&typeof node.inputs==='object'&&!Array.isArray(node.inputs)))return null;
  return value;
 }catch{return null;}
}
function canonical(value){
 if(Array.isArray(value))return `[${value.map(canonical).join(',')}]`;
 if(value&&typeof value==='object')return `{${Object.entries(value).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>`${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
 return JSON.stringify(value)??'';
}
export function workflowIdentity(json){
 const workflow=parseParameterWorkflow(json);if(!workflow)return '';
 const value=canonical(workflow);let a=2166136261,b=5381;
 for(let i=0;i<value.length;i++){a=Math.imul(a^value.charCodeAt(i),16777619);b=Math.imul(b,33)^value.charCodeAt(i);}
 return `${value.length}-${(a>>>0).toString(16)}-${(b>>>0).toString(16)}`;
}
const scalar=v=>typeof v==='string'||typeof v==='boolean'||(typeof v==='number'&&Number.isFinite(v));
const own=(obj,key)=>Object.prototype.hasOwnProperty.call(obj||{},key);

export function getWorkflowControls(json,schemas,excluded=new Set()){
 const workflow=parseParameterWorkflow(json);if(!workflow)return [];
 const controls=[];
 for(const [nodeId,node]of Object.entries(workflow)){
  const schema=schemas?.[node.class_type]?.input,declared=node._meta?.studio?.hiddenInputs;
  const hidden=Array.isArray(declared)&&declared.every(x=>typeof x==='string')?new Set(declared):new Set();
  for(const [input,value]of Object.entries(node.inputs)){
   if(!scalar(value)||hidden.has(input)||excluded.has(`${nodeId}.${input}`)||own(schema?.hidden,input))continue;
   const definition=schema?.required?.[input]??schema?.optional?.[input];
   if(!Array.isArray(definition))continue;
   const [kind,raw]=definition,settings=raw&&typeof raw==='object'?raw:{};
   if(settings.forceInput||settings.hidden||settings.socket||settings.image_upload)continue;
   const annotations=node._meta?.studio?.controls;
   const annotation=Array.isArray(annotations)?annotations.find(c=>c&&typeof c==='object'&&!Array.isArray(c)&&c.input===input):undefined;
   let type,options;
   const schemaOptions=Array.isArray(kind)?kind:kind==='COMBO'&&Array.isArray(settings.options)?settings.options:undefined;
   if(schemaOptions&&schemaOptions.every(scalar)){type='enum';options=schemaOptions;if(!options.some(o=>o===value))continue;}
   else if(kind==='BOOLEAN'&&typeof value==='boolean')type='boolean';
   else if((kind==='INT'||kind==='FLOAT')&&typeof value==='number')type='number';
   else if(kind==='STRING'&&typeof value==='string')type='string';
   else continue;
   const optionLabels={};
   if(Array.isArray(annotation?.options)){
    const suggested=annotation.options.flatMap(option=>{
     if(!scalar(option)&&(!option||typeof option!=='object'||Array.isArray(option)||typeof option.label!=='string'||!scalar(option.value)))return [];
     const candidate=scalar(option)?option:option.value;
     if(!scalar(candidate)||typeof candidate!==typeof value||(options&&!options.includes(candidate)))return [];
     if(typeof candidate==='number'&&((kind==='INT'&&!Number.isInteger(candidate))||(typeof settings.min==='number'&&candidate<settings.min)||(typeof settings.max==='number'&&candidate>settings.max)))return [];
     if(!scalar(option)&&typeof option?.label==='string')optionLabels[JSON.stringify(candidate)]=option.label;
     return [candidate];
    });
    if(suggested.length&&suggested.includes(value)){options=suggested;type='enum';}
   }
   controls.push({key:`${nodeId}.${input}`,nodeId,input,value,type,options,optionLabels,
    label:typeof annotation?.label==='string'?annotation.label:`${node._meta?.title||node.class_type} · ${input}`,
    description:typeof annotation?.description==='string'?annotation.description:undefined,group:typeof annotation?.group==='string'?annotation.group:undefined,recommended:Boolean(annotation),
    min:typeof settings.min==='number'?settings.min:undefined,max:typeof settings.max==='number'?settings.max:undefined,
    step:typeof settings.step==='number'?settings.step:kind==='INT'?1:undefined,integer:kind==='INT',multiline:Boolean(settings.multiline)});
  }
 }
 return controls.sort((a,b)=>Number(b.recommended)-Number(a.recommended));
}

export function validControlValue(control,value){
 if(!scalar(value)||typeof value!==typeof control.value)return false;
 if(control.options&&!control.options.includes(value))return false;
 if(typeof value==='number'&&((control.integer&&!Number.isInteger(value))||(control.min!==undefined&&value<control.min)||(control.max!==undefined&&value>control.max)))return false;
 return true;
}

export function applyWorkflowOverrides(json,saved,schemas){
 const workflow=parseParameterWorkflow(json);
 if(!workflow||!saved||!schemas||saved.workflowId!==workflowIdentity(json))return json;
 const controls=new Map(getWorkflowControls(json,schemas).map(c=>[c.key,c]));
 for(const [nodeId,fields]of Object.entries(saved.values||{})){
  const node=workflow[nodeId];if(!node||!fields||typeof fields!=='object')continue;
  for(const [input,value]of Object.entries(fields)){
   if(!own(node.inputs,input)||!scalar(node.inputs[input])||!scalar(value)||typeof node.inputs[input]!==typeof value)continue;
   const control=controls.get(`${nodeId}.${input}`);
   if(!control||!validControlValue(control,value))continue;
   node.inputs[input]=value;
  }
 }
 return JSON.stringify(workflow,null,2);
}

export function getWorkflowImages(json,mappedNodeIds,schemas){
 return Object.entries(parseParameterWorkflow(json)||{}).filter(([nodeId,node])=>{
  if(mappedNodeIds.includes(nodeId)||typeof node.inputs.image!=='string')return false;
  const definition=schemas?.[node.class_type]?.input?.required?.image??schemas?.[node.class_type]?.input?.optional?.image;
  return /^LoadImage(?:Goohai)?$/.test(node.class_type)||(schemas?.[node.class_type]?.output?.includes('IMAGE')&&Array.isArray(definition)&&Boolean(definition[1]?.image_upload));
 }).map(([nodeId,node])=>({nodeId,role:node._meta?.studio?.imageRole==='character_sheet'?'character_sheet':undefined,
  label:node._meta?.studio?.imageRole==='character_sheet'?'角色设定集':typeof node._meta?.title==='string'?node._meta.title:`参考图 · ${nodeId}`,
  optional:node.class_type==='LoadImageGoohai'})).sort((a,b)=>Number(b.role==='character_sheet')-Number(a.role==='character_sheet'));
}

export function validateReferenceCombinations(json,uploadedNodeIds){
 const workflow=parseParameterWorkflow(json)||{};
 const declarations=Object.values(workflow).map(n=>n._meta?.studio?.referenceCombinations).filter(v=>Array.isArray(v)&&v.length>0&&v.every(r=>Array.isArray(r)&&r.every(id=>typeof id==='string')));
 const selected=JSON.stringify([...new Set(uploadedNodeIds)].sort());
 for(const combos of declarations){
  if(combos.some(c=>JSON.stringify([...new Set(c)].sort())===selected))continue;
  const label=id=>workflow[id]?._meta?.studio?.imageRole==='character_sheet'?'角色设定集':workflow[id]?._meta?.title||('参考图 #'+id);
  return '当前参考图组合不受此工作流支持，可用组合：'+combos.map(c=>c.map(label).join('＋')).join('、')+'。';
 }
 return null;
}
