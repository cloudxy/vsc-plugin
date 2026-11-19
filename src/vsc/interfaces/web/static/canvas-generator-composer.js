// Inline node generator composer (Work Package A2: g1_node_generator #1 #7 #10 #12 #16 #17).
// Capabilities-driven by creative-canvas-run-options and synchronized with API settings.
import {buildCanvasModelDropdownList,canvasApiSettingsSignature,subscribeCanvasApiSettings} from './canvas-settings.js';

const SVG_NS='http://www.w3.org/2000/svg';

export const RUN_STATUS_LABELS=Object.freeze({
  pending_submit:'待提交',
  stage_preparing:'准备中',
  stage_submitting:'提交中',
  stage_queued:'排队中',
  queued:'排队中',
  stage_generating:'生成中',
  running:'生成中',
  stage_finalizing:'收尾中',
  succeeded:'已完成',
  success:'已完成',
  failed:'失败',
  submission_unknown:'失败',
  cancelled:'已取消',
  canceled:'已取消',
});

export const RATIO_DIMENSIONS=Object.freeze({
  '9:16':[1080,1920],
  '16:9':[1920,1080],
  '1:1':[1080,1080],
  '21:9':[2520,1080],
  '4:5':[1080,1350],
  '5:4':[1350,1080],
  '4:3':[1440,1080],
  '3:4':[1080,1440],
  '3:2':[1620,1080],
  '2:3':[1080,1620],
  '2:1':[2160,1080],
  adaptive:[1920,1080],
});

const BACKGROUND_LABELS=Object.freeze({
  auto:'自动',
  opaque:'保留背景',
  transparent:'透明背景',
});

const QUALITY_SHORT_LABELS=Object.freeze({
  max:'最高',
  xhigh:'超高',
  high:'高',
  medium:'标准',
  standard:'标准',
  low:'低',
});

const STYLE_TABS=Object.freeze([
  {id:'official',label:'官方'},
  {id:'mine',label:'我的'},
  {id:'3d',label:'3D'},
  {id:'live_action',label:'真人'},
  {id:'2d',label:'2D'},
]);

const QUOTE_DEBOUNCE_MS=300;
const COUNTDOWN_SECONDS=5;

function dom(doc,tag,cls='',text=null){
  const node=doc.createElement(tag);
  if(cls)node.className=cls;
  if(text!==null&&text!==undefined)node.textContent=String(text);
  return node;
}

function svg(doc,viewBox,paths,cls='cgc-svg'){
  const root=doc.createElementNS?doc.createElementNS(SVG_NS,'svg'):doc.createElement('svg');
  root.setAttribute('viewBox',viewBox);
  root.setAttribute('fill','none');
  root.setAttribute('aria-hidden','true');
  if(cls)root.setAttribute('class',cls);
  for(const [tag,attrs] of paths){
    const child=doc.createElementNS?doc.createElementNS(SVG_NS,tag):doc.createElement(tag);
    for(const [k,v] of Object.entries(attrs))child.setAttribute(k,String(v));
    root.append(child);
  }
  return root;
}

function iconPlus(doc){
  return svg(doc,'0 0 16 16',[['path',{d:'M8 3.2v9.6M3.2 8h9.6',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round'}]]);
}
function iconFocus(doc){
  return svg(doc,'0 0 16 16',[
    ['path',{d:'M3 5.5V3h2.5M10.5 3H13v2.5M13 10.5V13h-2.5M5.5 13H3v-2.5',stroke:'currentColor','stroke-width':'1.4','stroke-linecap':'round','stroke-linejoin':'round'}],
    ['circle',{cx:'8',cy:'8',r:'1.8',stroke:'currentColor','stroke-width':'1.4'}],
  ]);
}
function iconExpand(doc,expanded){
  return expanded
    ?svg(doc,'0 0 16 16',[['path',{d:'M6.2 9.8H3.2m3 0v3m-3-3 3 0M9.8 6.2h3m-3 0v-3m0 3 3.4-3.4M6.2 9.8 2.8 13.2',stroke:'currentColor','stroke-width':'1.4','stroke-linecap':'round','stroke-linejoin':'round'}]])
    :svg(doc,'0 0 16 16',[['path',{d:'M9.8 3.2h3v3M12.8 3.2 9.2 6.8M6.2 12.8h-3v-3M3.2 12.8l3.6-3.6',stroke:'currentColor','stroke-width':'1.4','stroke-linecap':'round','stroke-linejoin':'round'}]]);
}
function iconChevron(doc){
  return svg(doc,'0 0 16 16',[['path',{d:'m4.5 6.2 3.5 3.6 3.5-3.6',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round'}]],'cgc-svg cgc-chevron');
}
function iconSpecs(doc){
  return svg(doc,'0 0 16 16',[
    ['path',{d:'M2.5 4.5h11M2.5 8h11M2.5 11.5h11',stroke:'currentColor','stroke-width':'1.4','stroke-linecap':'round'}],
    ['circle',{cx:'5.5',cy:'4.5',r:'1.3',fill:'currentColor'}],
    ['circle',{cx:'10.5',cy:'8',r:'1.3',fill:'currentColor'}],
    ['circle',{cx:'6.5',cy:'11.5',r:'1.3',fill:'currentColor'}],
  ]);
}
function iconCamera(doc){
  return svg(doc,'0 0 16 16',[
    ['circle',{cx:'8',cy:'8',r:'5.5',stroke:'currentColor','stroke-width':'1.3'}],
    ['circle',{cx:'8',cy:'8',r:'2.1',stroke:'currentColor','stroke-width':'1.3'}],
    ['circle',{cx:'10.4',cy:'5.6',r:'0.8',fill:'currentColor'}],
  ]);
}
function iconPalette(doc){
  return svg(doc,'0 0 16 16',[
    ['path',{d:'M8 2.5a5.5 5.5 0 1 0 0 11h.9a1.4 1.4 0 0 0 1.4-1.4c0-.4-.2-.7-.4-1-.2-.3-.3-.6-.3-.9a1.3 1.3 0 0 1 1.3-1.3h.8A2.8 2.8 0 0 0 13.5 6 4.9 4.9 0 0 0 8 2.5Z',stroke:'currentColor','stroke-width':'1.3','stroke-linejoin':'round'}],
    ['circle',{cx:'5.6',cy:'6.5',r:'0.8',fill:'currentColor'}],
    ['circle',{cx:'8',cy:'5.2',r:'0.8',fill:'currentColor'}],
    ['circle',{cx:'10.3',cy:'6.5',r:'0.8',fill:'currentColor'}],
  ]);
}
function iconTranslate(doc){
  return svg(doc,'0 0 16 16',[
    ['path',{d:'M2.5 4.2h6.6M5.8 2.6v1.6M4 4.2c.3 2.3 1.6 4.2 3.8 5.4M7.4 4.2c-.4 2.1-1.7 4-4.2 5.4',stroke:'currentColor','stroke-width':'1.3','stroke-linecap':'round'}],
    ['path',{d:'m8.8 13.4 2.3-5.8 2.3 5.8M9.5 11.7h3.2',stroke:'currentColor','stroke-width':'1.3','stroke-linecap':'round','stroke-linejoin':'round'}],
  ]);
}
function iconAdvanced(doc){
  return svg(doc,'0 0 16 16',[
    ['path',{d:'M2.8 5.2h10.4M2.8 10.8h10.4',stroke:'currentColor','stroke-width':'1.4','stroke-linecap':'round'}],
    ['rect',{x:'5',y:'3.6',width:'2.4',height:'3.2',rx:'0.8',fill:'currentColor'}],
    ['rect',{x:'8.8',y:'9.2',width:'2.4',height:'3.2',rx:'0.8',fill:'currentColor'}],
  ]);
}
function iconSparkle(doc){
  const mark=dom(doc,'span','cgc-sparkle','✦');
  mark.setAttribute('aria-hidden','true');
  return mark;
}
function iconSend(doc){
  return svg(doc,'0 0 16 16',[['path',{d:'M8 12.6V3.6M4.3 7.1 8 3.4l3.7 3.7',stroke:'currentColor','stroke-width':'1.8','stroke-linecap':'round','stroke-linejoin':'round'}]]);
}
function iconRatioBox(doc,ratio){
  let w=14,h=10;
  if(ratio&&ratio!=='adaptive'&&ratio.includes(':')){
    const [rw,rh]=ratio.split(':').map(Number);
    if(rw>0&&rh>0){
      if(rw>=rh){w=15;h=Math.max(6,Math.round(15*(rh/rw)));}
      else{h=15;w=Math.max(6,Math.round(15*(rw/rh)));}
    }
  }else if(ratio==='adaptive'){w=14;h=11;}
  const x=((18-w)/2).toFixed(1),y=((18-h)/2).toFixed(1);
  return svg(doc,'0 0 18 18',[['rect',{x,y,width:w,height:h,rx:'2',stroke:'currentColor','stroke-width':'1.4'}]],'cgc-ratio-icon');
}

export function inferNodeOperation(node,edges,operations=[]){
  const ops=operations.filter(op=>op.node_type===node.type&&op.consumer==='work_generation');
  const ports=edges.filter(e=>e.target===node.id&&e.port!=='derived_from').map(e=>e.port);
  const inferred=node.type==='video'
    ?(ports.includes('last_frame')?'head_tail_video'
      :(ports.includes('reference_video')||ports.includes('reference_audio'))?'seedance_omni_video'
      :ports.includes('reference_image')?'multi_pic_video'
      :ports.includes('first_frame')?'single_image_video'
      :'text_video')
    :node.type==='audio'?'audio_generate':'image_generate';
  return ops.find(op=>op.op_type===node.params?.vsc_operation)
    ||ops.find(op=>node.params?.vsc_image_tool&&op.image_tool===node.params.vsc_image_tool)
    ||ops.find(op=>op.op_type===inferred)
    ||ops[0]
    ||null;
}

export function promptPlaceholderFor(node,operation){
  const opType=operation?.op_type||node.params?.vsc_operation||'';
  if(opType==='image_three_view')return '系统将基于您的参考图生成三视图';
  if(opType==='image_reverse_prompt')return '根据图片生成提示词';
  if(node.type==='image')return '可直接文字生图，或上传图片输入文字指令对图片进行编辑，如：将背景改为雪夜';
  if(node.type==='video')return '描述你想要生成的画面内容，@引用素材';
  if(node.type==='audio')return '输入要合成的文本';
  return '请输入提示词...';
}

export function resolveEffectiveGeneratorParams(node,operation,modelList=[],runOptions=null){
  const p=node.params||{};
  const modelParams=runOptions?.model_params||{};
  const executableModels=modelList.filter(m=>!m.disabled);
  const savedModel=p.vsc_gen_model_id?executableModels.find(m=>m.id===p.vsc_gen_model_id):null;
  const activeModel=savedModel||executableModels[0]||modelList[0]||null;
  const spec=(activeModel&&(modelParams[activeModel.id]||modelParams[activeModel.modelKey]||activeModel.spec))||{};

  const formats=Array.isArray(spec.output_formats)?spec.output_formats:[];
  const formatTypes=formats.map(f=>f.type);
  const outputFormat=formatTypes.length
    ?(formatTypes.includes(p.vsc_gen_output_format)?p.vsc_gen_output_format:(spec.default_output_format&&formatTypes.includes(spec.default_output_format)?spec.default_output_format:formatTypes[0]))
    :'';
  const formatObj=formats.find(f=>f.type===outputFormat)||null;

  const qualities=Array.isArray(spec.qualities)?spec.qualities:[];
  const qualityValues=qualities.map(q=>q.quality);
  const quality=qualityValues.length
    ?(qualityValues.includes(p.vsc_gen_quality)?p.vsc_gen_quality:(spec.default_quality&&qualityValues.includes(spec.default_quality)?spec.default_quality:qualityValues[0]))
    :'';
  const qualityObj=qualities.find(q=>q.quality===quality)||null;

  const resolutions=Array.isArray(spec.resolutions)?spec.resolutions:[];
  const resolution=resolutions.length
    ?(resolutions.includes(p.vsc_gen_resolution)?p.vsc_gen_resolution:(spec.default_resolution&&resolutions.includes(spec.default_resolution)?spec.default_resolution:resolutions[0]))
    :'';

  const backgrounds=Array.isArray(spec.backgrounds)?spec.backgrounds:[];
  let background=backgrounds.length
    ?(backgrounds.includes(p.vsc_gen_background)?p.vsc_gen_background:(spec.default_background&&backgrounds.includes(spec.default_background)?spec.default_background:backgrounds[0]))
    :'';
  if(outputFormat==='gif'&&background==='transparent'){
    background=backgrounds.includes('auto')?'auto':(backgrounds.find(b=>b!=='transparent')||'');
  }

  const ratios=Array.isArray(spec.aspect_ratios)?spec.aspect_ratios:[];
  const ratio=ratios.length
    ?(ratios.includes(p.vsc_gen_ratio)?p.vsc_gen_ratio:(spec.default_aspect_ratio&&ratios.includes(spec.default_aspect_ratio)?spec.default_aspect_ratio:ratios[0]))
    :(node.type==='video'?'16:9':'9:16');

  const counts=Array.isArray(spec.counts)&&spec.counts.length?spec.counts:[1];
  const savedCount=Number(p.vsc_gen_count);
  const count=counts.includes(savedCount)?savedCount:(counts.includes(spec.default_count)?spec.default_count:counts[0]);

  const durations=Array.isArray(spec.durations)&&spec.durations.length?spec.durations:[];
  const savedDur=Number(p.vsc_gen_duration);
  const duration=durations.length
    ?(durations.includes(savedDur)?savedDur:(durations.includes(spec.default_duration)?spec.default_duration:durations[0]))
    :null;

  const generateAudio=node.type==='video'
    ?(typeof p.vsc_gen_generate_audio==='boolean'?p.vsc_gen_generate_audio:Boolean(spec.generate_audio))
    :false;

  const gifParams=Array.isArray(formatObj?.params)?formatObj.params:[];
  const gifSizeSpec=gifParams.find(x=>x.key==='size');
  const gifFramesSpec=gifParams.find(x=>x.key==='frame_count');
  const gifMsSpec=gifParams.find(x=>x.key==='frame_duration_ms');
  const gifSize=gifSizeSpec?.options?.includes(p.vsc_gen_gif_size)?p.vsc_gen_gif_size:(gifSizeSpec?.default||'512x512');
  const gifFrames=Number.isInteger(Number(p.vsc_gen_gif_frames))&&Number(p.vsc_gen_gif_frames)>=(gifFramesSpec?.min||4)&&Number(p.vsc_gen_gif_frames)<=(gifFramesSpec?.max||24)
    ?Number(p.vsc_gen_gif_frames):(gifFramesSpec?.default||8);
  const gifMs=Number.isInteger(Number(p.vsc_gen_gif_ms))&&Number(p.vsc_gen_gif_ms)>=(gifMsSpec?.min||80)&&Number(p.vsc_gen_gif_ms)<=(gifMsSpec?.max||500)
    ?Number(p.vsc_gen_gif_ms):(gifMsSpec?.default||120);

  const camOpts=operation?.camera_options||null;
  const cameraSupportedByFormat=formatObj?formatObj.supports_camera_params!==false:true;
  const supportsCamera=Boolean(node.type==='image'&&camOpts&&spec.supports_camera!==false&&cameraSupportedByFormat);
  const camBodies=camOpts?.cameras||[];
  const camLenses=camOpts?.lenses||[];
  const camFocals=camOpts?.focal_lengths||[];
  const camApertures=camOpts?.apertures||[];
  const cameraModel=camBodies.some(c=>c.id===p.camera_model)?p.camera_model:(camBodies[0]?.id||'sony_venice');
  const lensModel=camLenses.some(l=>l.id===p.lens_model)?p.lens_model:(camLenses[0]?.id||'zeiss_ultra_prime');
  const savedFocal=Number(p.focal_length_mm);
  const focalMm=camFocals.some(f=>f.value===savedFocal)?savedFocal:(camFocals[0]?.value||8);
  const aperture=camApertures.some(a=>a.id===p.aperture)?p.aperture:(camApertures[0]?.id||'f/1.4');
  const photographyEnabled=supportsCamera&&Boolean(p.photography_enabled);

  const styleId=typeof p.vsc_gen_style_id==='string'&&p.vsc_gen_style_id?p.vsc_gen_style_id:'none';
  const smartRef=p.vsc_gen_smart_ref===undefined?true:Boolean(p.vsc_gen_smart_ref);

  return {
    activeModel,
    modelId:activeModel&&!activeModel.disabled?activeModel.id:'',
    spec,
    formats,
    outputFormat,
    formatObj,
    qualities,
    quality,
    qualityObj,
    resolutions,
    resolution,
    backgrounds,
    background,
    ratios,
    ratio,
    counts,
    count,
    durations,
    duration,
    generateAudio,
    gifSize,
    gifFrames,
    gifMs,
    gifParams,
    camOpts,
    cameraSupportedByFormat,
    supportsCamera,
    photographyEnabled,
    cameraModel,
    lensModel,
    focalMm,
    aperture,
    styleId,
    smartRef,
  };
}

function buildParamsPatch(eff){
  const patch={
    vsc_gen_model_id:eff.modelId||'',
    vsc_gen_ratio:eff.ratio||'',
    vsc_gen_count:eff.count||1,
    vsc_gen_smart_ref:Boolean(eff.smartRef),
  };
  if(eff.outputFormat)patch.vsc_gen_output_format=eff.outputFormat;
  if(eff.quality)patch.vsc_gen_quality=eff.quality;else patch.vsc_gen_quality='';
  if(eff.resolution)patch.vsc_gen_resolution=eff.resolution;else patch.vsc_gen_resolution='';
  if(eff.background)patch.vsc_gen_background=eff.background;else patch.vsc_gen_background='';
  if(eff.duration!==null)patch.vsc_gen_duration=eff.duration;
  if(eff.spec?.modality==='video')patch.vsc_gen_generate_audio=Boolean(eff.generateAudio);
  if(eff.outputFormat==='gif'){
    patch.vsc_gen_gif_size=eff.gifSize;
    patch.vsc_gen_gif_frames=eff.gifFrames;
    patch.vsc_gen_gif_ms=eff.gifMs;
  }
  if(eff.camOpts){
    patch.photography_enabled=Boolean(eff.photographyEnabled&&eff.supportsCamera);
    patch.camera_model=eff.cameraModel;
    patch.lens_model=eff.lensModel;
    patch.focal_length_mm=eff.focalMm;
    patch.aperture=eff.aperture;
  }
  patch.vsc_gen_style_id=eff.styleId||'none';
  return patch;
}

function applyConvergedPatchToNode(node,eff,overrides={}){
  const base=buildParamsPatch(eff);
  Object.assign(node.params,base,overrides);
  for(const [k,v] of Object.entries(node.params)){
    if(k.startsWith('vsc_gen_')&&v==='')delete node.params[k];
  }
}

function countUnitFor(type){
  return type==='image'?'张':type==='audio'?'首':'个';
}

export function formatSpecsSummary(node,eff){
  const unit=countUnitFor(node.type);
  if(node.type==='audio')return `${eff.count}${unit}`;
  if(node.type==='image'&&eff.outputFormat==='gif'){
    return `${eff.gifSize} · ${eff.gifFrames}帧 · ${eff.count}${unit}`;
  }
  const parts=[];
  if(eff.ratio)parts.push(eff.ratio==='adaptive'?'自适应':eff.ratio);
  if(node.type==='image'&&eff.quality){
    parts.push(eff.qualityObj?.label||QUALITY_SHORT_LABELS[eff.quality]||eff.quality);
  }
  if(eff.resolution)parts.push(eff.resolution);
  if(node.type==='video'&&eff.duration!==null)parts.push(`${eff.duration}s`);
  parts.push(`${eff.count}${unit}`);
  return parts.join(' · ');
}

function ensureState(s,helpers){
  if(s._cgc)return s._cgc;
  const ui={
    openPopover:null,
    popoverNodeId:null,
    advancedOpen:false,
    expanded:false,
    styleTab:'official',
    styleQuery:'',
    translatingNodeId:null,
    quoteSeq:0,
    quoteTimer:null,
    quotes:new Map(),
    pendingSubmits:new Map(),
    stageStatuses:new Map(),
    settingsSig:null,
    optionsLoading:null,
    unsubSettings:null,
    onWinKey:null,
    onWinPointer:null,
  };
  ui.unsubSettings=subscribeCanvasApiSettings(()=>{
    if(!helpers.live(s))return;
    const nextSig=canvasApiSettingsSignature();
    if(nextSig===ui.settingsSig)return;
    s.composerRunOptions=null;
    s.settingsModelsKey=null;
    ui.quotes.clear();
    refreshOptions(s,helpers,true);
  });
  if(typeof window!=='undefined'&&window?.addEventListener){
    ui.onWinKey=event=>{
      if(!helpers.live(s))return;
      if(event?.key==='Escape'&&ui.openPopover){
        ui.openPopover=null;
        rerenderIfActive(s,helpers);
      }
    };
    ui.onWinPointer=event=>{
      if(!helpers.live(s)||!ui.openPopover)return;
      const target=event?.target;
      if(target?.closest&&target.closest('.cgc-popover-anchor,.cgc-popover,.cgc-camera-panel'))return;
      ui.openPopover=null;
      rerenderIfActive(s,helpers);
    };
    window.addEventListener('keydown',ui.onWinKey);
    window.addEventListener('pointerdown',ui.onWinPointer);
  }
  s._cgc=ui;
  return ui;
}

export function disposeInlineGeneratorComposer(s){
  const ui=s?._cgc;
  if(!ui)return;
  ui.quoteSeq++;
  if(ui.quoteTimer&&typeof clearTimeout==='function')clearTimeout(ui.quoteTimer);
  for(const item of ui.pendingSubmits.values()){
    item.cancelled=true;
    if(item.timer&&typeof clearTimeout==='function')clearTimeout(item.timer);
  }
  ui.pendingSubmits.clear();
  ui.unsubSettings?.();
  if(typeof window!=='undefined'&&window?.removeEventListener){
    if(ui.onWinKey)window.removeEventListener('keydown',ui.onWinKey);
    if(ui.onWinPointer)window.removeEventListener('pointerdown',ui.onWinPointer);
  }
  s._cgc=null;
}

function rerenderIfActive(s,helpers){
  if(!helpers.live(s)||s.inspector?.hidden||s.inspector?.querySelector?.('.cc-picker'))return;
  const node=s.document.nodes.find(n=>s.selected.has(n.id));
  if(node&&['image','video','audio'].includes(node.type)&&!s.shared){
    (helpers.inspect||helpers.draw)(s);
  }
}

function syncMonotonicRevision(s,helpers,nextRev){
  if(typeof nextRev==='number'&&nextRev>(s.revision||0)){
    helpers.revision(s,nextRev);
  }
}

async function refreshOptions(s,helpers,force=false){
  const ui=ensureState(s,helpers);
  const sig=canvasApiSettingsSignature();
  if(!force&&s.composerRunOptions&&ui.settingsSig===sig)return s.composerRunOptions;
  if(ui.optionsLoading)return ui.optionsLoading;
  const task=(async()=>{
    try{
      const opts=await helpers.loadRunOptions(s);
      if(!helpers.live(s))return null;
      s.composerRunOptions=opts;
      ui.settingsSig=canvasApiSettingsSignature();
      syncMonotonicRevision(s,helpers,opts?.revision);
      rerenderIfActive(s,helpers);
      return opts;
    }catch(error){
      if(helpers.live(s))helpers.notice(s,error?.message||'读取生成能力目录失败');
      return null;
    }finally{
      if(ui.optionsLoading===task)ui.optionsLoading=null;
    }
  })();
  ui.optionsLoading=task;
  return task;
}

function quoteCacheKey(nodeId,payload){
  return nodeId+'::'+JSON.stringify(payload);
}

function scheduleRealtimeQuote(s,node,operation,eff,helpers,{immediate=false}={}){
  const ui=ensureState(s,helpers);
  if(s.readOnly||s.shared||!s.id||!eff.modelId){
    return;
  }
  const payload={
    op_type:operation?.op_type||(node.type==='video'?'text_video':node.type==='audio'?'audio_generate':'image_generate'),
    model_id:eff.modelId,
    resolution:eff.resolution||undefined,
    quality:eff.quality||undefined,
    duration:eff.duration!==null?eff.duration:undefined,
    count:eff.count||1,
    ratio:eff.ratio||undefined,
    generate_audio:node.type==='video'?Boolean(eff.generateAudio):undefined,
  };
  if(typeof helpers.generatorQuoteFields==='function'){
    const extra=helpers.generatorQuoteFields(node,operation,eff)||{};
    for(const [key,value] of Object.entries(extra)){
      if(value!==undefined&&value!=='')payload[key]=value;
    }
  }
  const key=quoteCacheKey(node.id,payload);
  const existing=ui.quotes.get(node.id);
  if(!immediate&&existing&&existing.key===key&&(existing.status==='ready'||existing.status==='loading')){
    return;
  }
  const token=++ui.quoteSeq;
  ui.quotes.set(node.id,{key,status:'loading',price:existing?.price??null,error:'',ready:true,gaps:[],payload});
  if(ui.quoteTimer&&typeof clearTimeout==='function')clearTimeout(ui.quoteTimer);

  const execute=async()=>{
    if(token!==ui.quoteSeq||!helpers.live(s))return;
    try{
      const res=await helpers.api(helpers.url(s)+'/work-quote',{
        method:'POST',
        headers:helpers.headers(),
        body:JSON.stringify({payload}),
      });
      if(token!==ui.quoteSeq||!helpers.live(s))return;
      syncMonotonicRevision(s,helpers,res?.revision);
      const price=res?.total_price!==undefined
        ?res.total_price
        :(res?.commerce_quote?.bound_credits??res?.generation_quote?.native_units?.images??res?.generation_quote?.native_units?.video_seconds??0);
      ui.quotes.set(node.id,{
        key,
        status:'ready',
        price,
        priceBasis:res?.price_basis||'native_units',
        ready:res?.ready!==false,
        gaps:Array.isArray(res?.gaps)?res.gaps:[],
        error:'',
        payload,
      });
    }catch(error){
      if(token!==ui.quoteSeq||!helpers.live(s))return;
      ui.quotes.set(node.id,{
        key,
        status:'error',
        price:null,
        ready:false,
        gaps:[],
        error:error?.message||'获取积分报价失败，请刷新页面后重试。',
        payload,
      });
    }
    updateQuoteDomInPlace(s,node.id,helpers);
  };

  if(immediate){
    execute();
  }else{
    ui.quoteTimer=setTimeout(execute,QUOTE_DEBOUNCE_MS);
  }
}

function updateQuoteDomInPlace(s,nodeId,helpers){
  if(!helpers.live(s)||s.inspector?.hidden)return;
  const host=s.inspector.querySelector('.cgc-quote-box');
  if(!host||host.dataset.nodeId!==nodeId)return;
  const doc=s.inspector.ownerDocument;
  const q=s._cgc?.quotes.get(nodeId);
  renderQuoteContents(doc,host,q,()=>{
    const node=s.document.nodes.find(n=>n.id===nodeId);
    if(!node||!s.composerRunOptions)return;
    const op=inferNodeOperation(node,s.document.edges,s.composerRunOptions.operations||[]);
    const models=buildCanvasModelDropdownList({modality:node.type,operation:op,runOptions:s.composerRunOptions});
    const eff=resolveEffectiveGeneratorParams(node,op,models,s.composerRunOptions);
    scheduleRealtimeQuote(s,node,op,eff,helpers,{immediate:true});
    updateQuoteDomInPlace(s,nodeId,helpers);
  });
}

function renderQuoteContents(doc,host,quoteState,onRetry){
  host.replaceChildren();
  host.classList.remove('is-loading','is-error','is-insufficient');
  if(quoteState?.status==='error'){
    host.classList.add('is-error');
    host.title='获取积分报价失败，请刷新页面后重试。';
    const msgSpan=dom(doc,'span','cgc-quote-err-text','获取积分报价失败，请刷新页面后重试。');
    const retryBtn=dom(doc,'button','cgc-quote-retry','重试');
    retryBtn.type='button';
    retryBtn.setAttribute('aria-label','重试报价');
    retryBtn.addEventListener('click',e=>{e.stopPropagation();onRetry();});
    host.append(msgSpan,retryBtn);
    return;
  }
  if(quoteState?.status==='loading'){
    host.classList.add('is-loading');
  }
  if(quoteState&&quoteState.ready===false){
    host.classList.add('is-insufficient');
  }
  const amount=quoteState?.price!==null&&quoteState?.price!==undefined?String(quoteState.price):'0';
  const gapMsg=(quoteState?.gaps||[]).map(g=>g.message||g.code).filter(Boolean).join('；');
  host.title=gapMsg||(quoteState?.priceBasis==='commerce_credits'?'实时商业额度报价':quoteState?.priceBasis==='cost_rule'?'按模型单价实时估算':'按本地配额单位实时计算');
  host.append(iconSparkle(doc),dom(doc,'span','cgc-quote-amount',amount));
}

export function cancelPendingSubmit(s,nodeId,helpers){
  const ui=s?._cgc;
  const entry=ui?.pendingSubmits.get(nodeId);
  if(!entry)return false;
  entry.cancelled=true;
  if(entry.timer&&typeof clearTimeout==='function')clearTimeout(entry.timer);
  ui.pendingSubmits.delete(nodeId);
  ui.stageStatuses.set(nodeId,{stage:'cancelled',taskId:null});
  helpers.notice(s,'已撤回待提交生成任务');
  helpers.draw(s);
  return true;
}

async function startCountdownSubmit(s,node,operation,eff,helpers){
  const ui=ensureState(s,helpers);
  if(ui.pendingSubmits.has(node.id)||ui.preflighting)return;
  if(typeof helpers.generationBlockReason==='function'){
    const block=helpers.generationBlockReason(node);
    if(block){helpers.notice(s,block);return;}
  }
  if(typeof helpers.beforeGeneratorSubmit==='function'){
    ui.preflighting=true;
    let gate;
    try{gate=await helpers.beforeGeneratorSubmit(s,node,helpers,eff);}finally{ui.preflighting=false;}
    if(!gate||gate.ok===false||!helpers.live(s))return;
  }
  const livePromptInput=s.inspector?.querySelector?.('[aria-label="文本或提示词"]');
  const liveText=livePromptInput&&typeof livePromptInput.value==='string'?livePromptInput.value:String(node.text||'');
  const hasRefs=s.document.edges.some(e=>e.target===node.id&&e.port!=='derived_from');
  if(!liveText.trim()&&!hasRefs){
    helpers.notice(s,'请输入提示词或添加参考素材');
    return;
  }
  if(!eff.modelId){
    helpers.notice(s,eff.activeModel?.disabledReason||'请选择可用的生成模型');
    return;
  }

  // Persist converged params on node if not yet written so reload restores exact submission settings.
  const patch=buildParamsPatch(eff);
  const opType=operation?.op_type||(node.type==='video'?'text_video':node.type==='audio'?'audio_generate':'image_generate');
  const needsParamWrite=liveText!==node.text||Object.entries(patch).some(([k,v])=>v!==''&&node.params?.[k]!==v)||node.params?.vsc_operation!==opType;
  if(needsParamWrite){
    helpers.change(s,()=>{
      node.text=liveText;
      node.params.vsc_operation=opType;
      applyConvergedPatchToNode(node,eff);
    });
  }

  const entry={
    nodeId:node.id,
    remaining:COUNTDOWN_SECONDS,
    cancelled:false,
    submitting:false,
    timer:null,
    snapshot:{
      modelId:eff.modelId,
      count:eff.count||1,
      ratio:eff.ratio||'9:16',
      duration:eff.duration||5,
    },
  };
  ui.stageStatuses.delete(node.id);
  ui.pendingSubmits.set(node.id,entry);

  const step=()=>{
    if(entry.cancelled||!helpers.live(s))return;
    if(entry.remaining>1){
      entry.remaining-=1;
      entry.timer=setTimeout(step,1000);
      helpers.draw(s);
      return;
    }
    executeDeferredSubmit(s,node.id,entry,helpers);
  };
  entry.timer=setTimeout(step,1000);
  helpers.draw(s);
}

async function executeDeferredSubmit(s,nodeId,entry,helpers){
  const ui=s?._cgc;
  if(!ui||entry.cancelled||!helpers.live(s))return;
  entry.submitting=true;
  ui.pendingSubmits.delete(nodeId);
  ui.stageStatuses.set(nodeId,{stage:'stage_preparing',taskId:null});
  helpers.draw(s);

  try{
    const node=s.document.nodes.find(n=>n.id===nodeId);
    if(!node)return;
    if(s.dirty||s.pending){
      const saved=await helpers.save(s);
      if(!saved||entry.cancelled||!helpers.live(s))return;
    }
    const [width,height]=RATIO_DIMENSIONS[entry.snapshot.ratio]||[1080,1920];
    const token=Date.now();
    const fixed=await helpers.auxiliaryWrite(
      s,
      `work-input:${nodeId}:${s.version}:${token}`,
      helpers.url(s)+'/work-input',
      {
        canvas_revision:s.version,
        node_id:nodeId,
        model_id:entry.snapshot.modelId,
        shot_id:null,
        count:entry.snapshot.count,
        duration_ms:entry.snapshot.duration*1000,
        width,
        height,
        ...(node.type==='audio'?{purpose:s.aiMv?'music':'sfx'}:{}),
      },
    );
    if(entry.cancelled||!helpers.live(s))return;

    const request={
      draft_version_id:fixed.draft_version_id,
      execution_policy:{
        version:'bounded-v1',
        first_draft_due_at:new Date(Date.now()+3600000).toISOString(),
        stop_submitting_at:new Date(Date.now()+7200000).toISOString(),
        max_attempts_per_purpose:Math.max(1,entry.snapshot.count),
        max_repair_rounds:0,
      },
    };
    const quote=await helpers.api(helpers.url(s)+'/work-quote',{
      method:'POST',
      headers:helpers.headers(),
      body:JSON.stringify({payload:request}),
    });
    if(entry.cancelled||!helpers.live(s))return;
    syncMonotonicRevision(s,helpers,quote?.revision);
    if(!quote?.ready){
      const msg=(quote?.gaps||[]).map(g=>g.message||g.code).join('；')||'生成输入校验未通过';
      throw new Error(msg);
    }

    ui.stageStatuses.set(nodeId,{stage:'stage_submitting',taskId:null});
    helpers.draw(s);

    const generated=await helpers.auxiliaryWrite(
      s,
      `generate:${quote.preview_sha256}`,
      helpers.url(s)+'/generate',
      {
        canvas_revision:s.version,
        node_id:nodeId,
        request,
        preview_sha256:quote.preview_sha256,
      },
    );
    if(!helpers.live(s))return;
    const firstJobId=Array.isArray(generated?.jobs)&&generated.jobs[0]
      ?(typeof generated.jobs[0]==='string'?generated.jobs[0]:generated.jobs[0].id)
      :null;
    ui.stageStatuses.set(nodeId,{stage:'stage_queued',taskId:firstJobId});
    await helpers.refreshCanvas(s);
    helpers.notice(s,'已提交生成任务');
  }catch(error){
    if(helpers.live(s)){
      ui.stageStatuses.set(nodeId,{stage:'failed',taskId:null,error:error?.message||'提交失败'});
      helpers.notice(s,error?.message||'生成提交失败');
      helpers.draw(s);
    }
  }
}

async function copyTaskIdText(taskId,s,helpers){
  if(!taskId)return;
  try{
    if(typeof navigator!=='undefined'&&navigator.clipboard?.writeText){
      await navigator.clipboard.writeText(String(taskId));
      helpers.notice(s,'TaskID 已复制');
      return;
    }
  }catch{
    helpers.notice(s,'系统剪贴板写入失败');
    return;
  }
  helpers.notice(s,'TaskID: '+String(taskId));
}

export function renderNodeRunStatusBar(s,node,card,helpers){
  if(!card||!node||node.type==='text')return;
  const doc=card.ownerDocument;
  const ui=s?._cgc;
  const pending=ui?.pendingSubmits.get(node.id);
  if(pending){
    const bar=dom(doc,'div','cgc-node-runbar is-pending');
    const badge=dom(doc,'span','cgc-node-status-badge',`${RUN_STATUS_LABELS.pending_submit} · ${pending.remaining}s 后提交`);
    const cancelBtn=dom(doc,'button','cgc-node-cancel-btn','撤回任务');
    cancelBtn.type='button';
    cancelBtn.setAttribute('aria-label','撤回任务');
    cancelBtn.addEventListener('click',e=>{
      e.stopPropagation();
      cancelPendingSubmit(s,node.id,helpers);
    });
    bar.append(badge,cancelBtn);
    card.append(bar);
    return;
  }

  const stepJobs=(s.steps||[]).filter(st=>st.node_key===node.id).flatMap(st=>st.jobs||[]);
  const directJob=s.jobs?.[node.id]&&node.job_id===s.jobs[node.id].id?s.jobs[node.id]:null;
  const latestStepJob=stepJobs.length?stepJobs[stepJobs.length-1]:null;
  const stageInfo=ui?.stageStatuses.get(node.id)||null;

  const rawStatus=directJob?.status||latestStepJob?.status||stageInfo?.stage||'';
  const taskId=directJob?.id||latestStepJob?.id||node.job_id||stageInfo?.taskId||null;
  if(!rawStatus&&!taskId)return;

  const statusLabel=RUN_STATUS_LABELS[rawStatus]||rawStatus||'排队中';
  const tone=(rawStatus==='succeeded'||rawStatus==='success')?'is-success'
    :(rawStatus==='failed'||rawStatus==='submission_unknown')?'is-failed'
    :(rawStatus==='cancelled'||rawStatus==='canceled')?'is-cancelled'
    :'is-running';
  const bar=dom(doc,'div',`cgc-node-runbar ${tone}`);
  const dot=dom(doc,'span','cgc-status-dot');
  const label=dom(doc,'span','cgc-node-status-badge',statusLabel);
  bar.append(dot,label);

  if(taskId){
    const shortId=String(taskId).length>10?String(taskId).slice(0,8)+'…':String(taskId);
    const copyBtn=dom(doc,'button','cgc-copy-taskid',`复制 TaskID (${shortId})`);
    copyBtn.type='button';
    copyBtn.dataset.taskId=String(taskId);
    copyBtn.title=`复制 TaskID: ${taskId}`;
    copyBtn.setAttribute('aria-label','复制 TaskID');
    copyBtn.addEventListener('click',e=>{
      e.stopPropagation();
      copyTaskIdText(taskId,s,helpers);
    });
    bar.append(copyBtn);
  }
  card.append(bar);
}

async function runTranslatePrompt(s,node,helpers){
  const ui=ensureState(s,helpers);
  const livePromptInput=s.inspector?.querySelector?.('[aria-label="文本或提示词"]');
  const text=String((livePromptInput&&typeof livePromptInput.value==='string'?livePromptInput.value:node.text)||'').trim();
  if(!text){
    helpers.notice(s,'提示词为空，请输入内容后点击');
    return;
  }
  if(ui.translatingNodeId)return;
  ui.translatingNodeId=node.id;
  rerenderIfActive(s,helpers);
  try{
    const res=await helpers.api(helpers.url(s)+'/prompt-translate',{
      method:'POST',
      headers:helpers.headers(),
      body:JSON.stringify({payload:{node_id:node.id,text,target_language:'auto'}}),
    });
    if(!helpers.live(s))return;
    if(typeof res?.text==='string'&&res.text.trim()){
      helpers.change(s,()=>{node.text=res.text.trim();});
      helpers.notice(s,'提示词翻译完成');
    }else{
      helpers.notice(s,'提示词翻译失败，请稍后重试');
    }
  }catch(error){
    if(helpers.live(s))helpers.notice(s,error?.message||'提示词翻译失败，请稍后重试');
  }finally{
    ui.translatingNodeId=null;
    rerenderIfActive(s,helpers);
  }
}

function renderModelPopover(doc,s,node,operation,modelList,eff,ui,helpers){
  const pop=dom(doc,'div','cgc-popover cgc-model-popover');
  pop.setAttribute('role','listbox');
  pop.setAttribute('aria-label','选择模型');
  const head=dom(doc,'div','cgc-popover-title','选择模型');
  pop.append(head);

  const list=dom(doc,'div','cgc-model-list');
  if(!modelList.length){
    list.append(dom(doc,'div','cgc-empty-hint','暂无已配置模型，请前往「API 接口配置」添加或授权模型'));
  }
  for(const item of modelList){
    const active=item.id===eff.modelId&&!item.disabled;
    const row=dom(doc,'button','cgc-model-option'+(active?' is-selected':'')+(item.disabled?' is-disabled':''));
    row.type='button';
    row.dataset.modelId=item.id;
    row.dataset.modelKey=item.modelKey;
    row.setAttribute('role','option');
    row.setAttribute('aria-selected',String(active));
    if(item.disabled){
      row.setAttribute('aria-disabled','true');
      row.title=item.disabledReason;
    }
    const body=dom(doc,'div','cgc-model-option-body');
    const titleLine=dom(doc,'div','cgc-model-option-head');
    titleLine.append(dom(doc,'span','cgc-model-option-name',item.showName));
    if(item.channelLabel){
      titleLine.append(dom(doc,'span','cgc-model-badge',item.channelLabel));
    }
    body.append(titleLine);

    if(item.disabled&&item.disabledReason){
      body.append(dom(doc,'div','cgc-model-disabled-reason',item.disabledReason));
    }else if(item.spec){
      const resText=Array.isArray(item.spec.resolutions)&&item.spec.resolutions.length?item.spec.resolutions.join(' / '):'';
      const durText=Array.isArray(item.spec.durations)&&item.spec.durations.length?`${item.spec.durations[0]}-${item.spec.durations[item.spec.durations.length-1]}s`:'';
      const sub=[resText,durText].filter(Boolean).join(' · ');
      if(sub)body.append(dom(doc,'div','cgc-model-option-sub',sub));
    }
    const check=dom(doc,'span','cgc-option-check',active?'✓':'');
    row.append(body,check);

    row.addEventListener('click',e=>{
      e.stopPropagation();
      if(item.disabled){
        helpers.notice(s,item.disabledReason||'该模型当前不可在画布服务端执行');
        return;
      }
      ui.openPopover=null;
      helpers.change(s,()=>{
        node.params.vsc_gen_model_id=item.id;
        const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
        applyConvergedPatchToNode(node,converged);
      });
    });
    list.append(row);
  }
  pop.append(list);
  return pop;
}

function renderFormatPopover(doc,s,node,operation,modelList,eff,ui,helpers){
  const pop=dom(doc,'div','cgc-popover cgc-format-popover');
  pop.setAttribute('role','listbox');
  pop.setAttribute('aria-label','输出格式');
  for(const fmt of eff.formats){
    const active=fmt.type===eff.outputFormat;
    const btn=dom(doc,'button','cgc-format-option'+(active?' is-selected':''));
    btn.type='button';
    btn.dataset.format=fmt.type;
    btn.setAttribute('role','option');
    btn.setAttribute('aria-selected',String(active));
    btn.append(dom(doc,'span','',fmt.label||fmt.type.toUpperCase()),dom(doc,'span','cgc-option-check',active?'✓':''));
    btn.addEventListener('click',e=>{
      e.stopPropagation();
      ui.openPopover=null;
      helpers.change(s,()=>{
        node.params.vsc_gen_output_format=fmt.type;
        if(fmt.supports_camera_params===false)node.params.photography_enabled=false;
        const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
        applyConvergedPatchToNode(node,converged);
      });
    });
    pop.append(btn);
  }
  return pop;
}

function renderSpecsPopover(doc,s,node,operation,modelList,eff,helpers){
  const pop=dom(doc,'div','cgc-popover cgc-specs-popover');
  pop.setAttribute('role','dialog');
  pop.setAttribute('aria-label','规格参数');

  const mutate=fn=>{
    helpers.change(s,()=>{
      fn();
      const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
      applyConvergedPatchToNode(node,converged);
    });
  };

  if(node.type==='image'&&eff.qualities.length){
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='quality';
    sec.append(dom(doc,'div','cgc-spec-label','品质'));
    const row=dom(doc,'div','cgc-spec-seg cgc-spec-seg--quality');
    for(const q of eff.qualities){
      const active=q.quality===eff.quality;
      const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':''),q.label||QUALITY_SHORT_LABELS[q.quality]||q.quality);
      b.type='button';
      b.dataset.quality=q.quality;
      b.title=q.show_quality||q.label||q.quality;
      b.setAttribute('aria-pressed',String(active));
      b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_quality=q.quality;});});
      row.append(b);
    }
    sec.append(row);
    pop.append(sec);
  }

  if(eff.resolutions.length&&!(node.type==='image'&&eff.outputFormat==='gif')){
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='resolution';
    sec.append(dom(doc,'div','cgc-spec-label','分辨率'));
    const row=dom(doc,'div','cgc-spec-seg');
    for(const res of eff.resolutions){
      const active=res===eff.resolution;
      const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':''),res);
      b.type='button';
      b.dataset.resolution=res;
      b.setAttribute('aria-pressed',String(active));
      b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_resolution=res;});});
      row.append(b);
    }
    sec.append(row);
    pop.append(sec);
  }

  if(node.type==='image'&&eff.backgrounds.length){
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='background';
    sec.append(dom(doc,'div','cgc-spec-label','背景'));
    const row=dom(doc,'div','cgc-spec-seg');
    for(const bg of eff.backgrounds){
      const blocked=eff.outputFormat==='gif'&&bg==='transparent';
      const active=!blocked&&bg===eff.background;
      const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':'')+(blocked?' is-disabled':''),BACKGROUND_LABELS[bg]||bg);
      b.type='button';
      b.dataset.background=bg;
      b.disabled=blocked;
      if(blocked)b.title='GIF 不支持透明背景，请选择自动或保留背景';
      b.setAttribute('aria-pressed',String(active));
      b.addEventListener('click',e=>{e.stopPropagation();if(!blocked)mutate(()=>{node.params.vsc_gen_background=bg;});});
      row.append(b);
    }
    sec.append(row);
    pop.append(sec);
  }

  if(node.type==='image'&&eff.outputFormat==='gif'&&eff.gifParams.length){
    const sizeSpec=eff.gifParams.find(p=>p.key==='size');
    if(sizeSpec?.options?.length){
      const sec=dom(doc,'div','cgc-spec-group');
      sec.append(dom(doc,'div','cgc-spec-label','尺寸'));
      const row=dom(doc,'div','cgc-spec-seg');
      for(const sz of sizeSpec.options){
        const active=sz===eff.gifSize;
        const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':''),sz);
        b.type='button';
        b.dataset.gifSize=sz;
        b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_gif_size=sz;});});
        row.append(b);
      }
      sec.append(row);
      pop.append(sec);
    }
  }else if(eff.ratios.length){
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='ratio';
    sec.append(dom(doc,'div','cgc-spec-label','比例'));
    const grid=dom(doc,'div','cgc-ratio-grid');
    for(const r of eff.ratios){
      const active=r===eff.ratio;
      const label=r==='adaptive'?'自适应':r;
      const b=dom(doc,'button','cgc-ratio-btn'+(active?' is-selected':''));
      b.type='button';
      b.dataset.ratio=r;
      b.setAttribute('aria-pressed',String(active));
      b.append(iconRatioBox(doc,r),dom(doc,'span','cgc-ratio-text',label));
      b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_ratio=r;});});
      grid.append(b);
    }
    sec.append(grid);
    pop.append(sec);
  }

  if(node.type==='video'&&eff.durations.length){
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='duration';
    sec.append(dom(doc,'div','cgc-spec-label','视频时长'));
    const selectOrSeg=eff.durations.length<=6?dom(doc,'div','cgc-spec-seg'):null;
    if(selectOrSeg){
      for(const d of eff.durations){
        const active=d===eff.duration;
        const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':''),`${d}s`);
        b.type='button';
        b.dataset.duration=String(d);
        b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_duration=d;});});
        selectOrSeg.append(b);
      }
      sec.append(selectOrSeg);
    }else{
      const sel=dom(doc,'select','cgc-duration-select');
      sel.setAttribute('aria-label','视频时长');
      for(const d of eff.durations){
        const opt=dom(doc,'option','',`${d} 秒`);
        opt.value=String(d);
        if(d===eff.duration)opt.selected=true;
        sel.append(opt);
      }
      sel.value=String(eff.duration);
      sel.addEventListener('change',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_duration=Number(sel.value);});});
      sec.append(sel);
    }
    pop.append(sec);
  }

  if(eff.counts.length){
    const unit=countUnitFor(node.type);
    const sec=dom(doc,'div','cgc-spec-group');
    sec.dataset.group='count';
    sec.append(dom(doc,'div','cgc-spec-label','生成数量'));
    const row=dom(doc,'div','cgc-spec-seg');
    for(const c of eff.counts){
      const active=c===eff.count;
      const b=dom(doc,'button','cgc-seg-btn'+(active?' is-selected':''),`${c}${unit}`);
      b.type='button';
      b.dataset.count=String(c);
      b.setAttribute('aria-pressed',String(active));
      b.addEventListener('click',e=>{e.stopPropagation();mutate(()=>{node.params.vsc_gen_count=c;});});
      row.append(b);
    }
    sec.append(row);
    pop.append(sec);
  }
  return pop;
}

function renderCameraPanel(doc,s,node,operation,modelList,eff,ui,helpers){
  const panel=dom(doc,'div','cgc-camera-panel');
  panel.setAttribute('role','dialog');
  panel.setAttribute('aria-label','摄像机');

  const head=dom(doc,'div','cgc-camera-head');
  const titleWrap=dom(doc,'div','cgc-camera-title-wrap');
  titleWrap.append(dom(doc,'strong','cgc-camera-title','摄像机'));

  const toggleBtn=dom(doc,'button','cgc-camera-toggle'+(eff.photographyEnabled?' is-on':''),eff.photographyEnabled?'已开启':'已关闭');
  toggleBtn.type='button';
  toggleBtn.setAttribute('role','switch');
  toggleBtn.setAttribute('aria-checked',String(eff.photographyEnabled));
  toggleBtn.setAttribute('aria-label',eff.photographyEnabled?'关闭':'开启');
  toggleBtn.addEventListener('click',e=>{
    e.stopPropagation();
    helpers.change(s,()=>{
      node.params.photography_enabled=!eff.photographyEnabled;
      const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
      applyConvergedPatchToNode(node,converged);
    });
  });
  titleWrap.append(toggleBtn);

  const closeBtn=dom(doc,'button','cgc-icon-btn cgc-camera-close','×');
  closeBtn.type='button';
  closeBtn.setAttribute('aria-label','关闭摄像机面板');
  closeBtn.addEventListener('click',e=>{
    e.stopPropagation();
    ui.openPopover=null;
    rerenderIfActive(s,helpers);
  });
  head.append(titleWrap,closeBtn);
  panel.append(head);

  const cols=dom(doc,'div','cgc-camera-columns');
  const columnDefs=[
    {key:'camera_model',label:'相机',items:eff.camOpts?.cameras||[],current:eff.cameraModel,toVal:x=>x.id},
    {key:'lens_model',label:'镜头',items:eff.camOpts?.lenses||[],current:eff.lensModel,toVal:x=>x.id},
    {key:'focal_length_mm',label:'焦距',items:eff.camOpts?.focal_lengths||[],current:eff.focalMm,toVal:x=>x.value},
    {key:'aperture',label:'光圈',items:eff.camOpts?.apertures||[],current:eff.aperture,toVal:x=>x.id},
  ];

  for(const col of columnDefs){
    const colEl=dom(doc,'div','cgc-camera-col');
    colEl.dataset.cameraColumn=col.key;
    colEl.append(dom(doc,'div','cgc-camera-col-label',col.label));
    const idx=Math.max(0,col.items.findIndex(item=>col.toVal(item)===col.current));

    const stepSelect=delta=>{
      if(!col.items.length)return;
      const nextItem=col.items[(idx+delta+col.items.length)%col.items.length];
      helpers.change(s,()=>{
        node.params.photography_enabled=true;
        node.params[col.key]=col.toVal(nextItem);
        const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
        applyConvergedPatchToNode(node,converged);
      });
    };

    const prevBtn=dom(doc,'button','cgc-wheel-step','▲');
    prevBtn.type='button';
    prevBtn.setAttribute('aria-label',`${col.label}上一个`);
    prevBtn.addEventListener('click',e=>{e.stopPropagation();stepSelect(-1);});

    const wheel=dom(doc,'div','cgc-wheel-list');
    for(const item of col.items){
      const val=col.toVal(item);
      const selected=val===col.current;
      const optBtn=dom(doc,'button','cgc-wheel-item'+(selected?' is-selected':''),item.label);
      optBtn.type='button';
      optBtn.dataset.cameraValue=String(val);
      optBtn.setAttribute('aria-pressed',String(selected));
      optBtn.addEventListener('click',e=>{
        e.stopPropagation();
        helpers.change(s,()=>{
          node.params.photography_enabled=true;
          node.params[col.key]=val;
          const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
          applyConvergedPatchToNode(node,converged);
        });
      });
      wheel.append(optBtn);
    }

    const nextBtn=dom(doc,'button','cgc-wheel-step','▼');
    nextBtn.type='button';
    nextBtn.setAttribute('aria-label',`${col.label}下一个`);
    nextBtn.addEventListener('click',e=>{e.stopPropagation();stepSelect(1);});

    colEl.append(prevBtn,wheel,nextBtn);
    cols.append(colEl);
  }

  panel.append(cols);
  return panel;
}

function renderStylePopover(doc,s,node,operation,modelList,eff,ui,helpers){
  const pop=dom(doc,'div','cgc-popover cgc-style-popover');
  pop.dataset.slot='style-library';
  pop.setAttribute('role','dialog');
  pop.setAttribute('aria-label','风格');

  const topRow=dom(doc,'div','cgc-style-top');
  const search=dom(doc,'input','cgc-style-search');
  search.type='search';
  search.placeholder='搜索官方和我的风格';
  search.setAttribute('aria-label','搜索官方和我的风格');
  search.value=ui.styleQuery;
  search.addEventListener('input',e=>{e.stopPropagation();ui.styleQuery=search.value;if(typeof helpers.filterStyleLibrary==='function')helpers.filterStyleLibrary(search.value);});

  const customSlot=dom(doc,'button','cgc-style-custom-btn','+ 自定义');
  customSlot.type='button';
  customSlot.dataset.slot='style-custom-action';
  customSlot.disabled=typeof helpers.openCustomStyle!=='function';
  customSlot.title=typeof helpers.openCustomStyle==='function'?'自定义风格':'自定义风格库插槽';
  if(typeof helpers.openCustomStyle==='function')customSlot.addEventListener('click',e=>{e.stopPropagation();helpers.openCustomStyle({s,node,ui,doc});});
  topRow.append(search,customSlot);

  const tabs=dom(doc,'div','cgc-style-tabs');
  tabs.dataset.slot='style-tabs';
  tabs.setAttribute('role','tablist');
  for(const tab of STYLE_TABS){
    const active=ui.styleTab===tab.id;
    const tb=dom(doc,'button','cgc-style-tab'+(active?' is-active':''),tab.label);
    tb.type='button';
    tb.dataset.styleTab=tab.id;
    tb.setAttribute('role','tab');
    tb.setAttribute('aria-selected',String(active));
    tb.addEventListener('click',e=>{
      e.stopPropagation();
      ui.styleTab=tab.id;
      rerenderIfActive(s,helpers);
    });
    tabs.append(tb);
  }

  const list=dom(doc,'div','cgc-style-grid');
  list.dataset.slot='style-list';
  const noneActive=!eff.styleId||eff.styleId==='none';
  const noneCard=dom(doc,'button','cgc-style-card'+(noneActive?' is-selected':''));
  noneCard.type='button';
  noneCard.dataset.styleId='none';
  noneCard.setAttribute('aria-pressed',String(noneActive));
  noneCard.append(dom(doc,'span','cgc-style-none-icon','⊘'),dom(doc,'span','cgc-style-card-name','无风格'));
  noneCard.addEventListener('click',e=>{
    e.stopPropagation();
    ui.openPopover=null;
    helpers.change(s,()=>{
      helpers.clearGeneratorStyle?.(node);
      node.params.vsc_gen_style_id='none';
      const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
      applyConvergedPatchToNode(node,converged);
    });
  });
  list.append(noneCard);

  if(typeof helpers.mountStyleLibrarySlot==='function'){
    helpers.mountStyleLibrarySlot({root:list,tabs,tab:ui.styleTab,query:ui.styleQuery,selectedStyleId:eff.styleId,node,s,ui,doc});
  }else{
    list.append(dom(doc,'div','cgc-style-slot-placeholder','暂无风格'));
  }

  pop.append(topRow,tabs,list);
  return pop;
}

export function mountInlineGeneratorComposer(s,node,helpers){
  if(!s?.inspector||!node||!['image','video','audio'].includes(node.type)||s.shared)return;
  const doc=s.inspector.ownerDocument;
  const ui=ensureState(s,helpers);
  if(ui.popoverNodeId&&ui.popoverNodeId!==node.id){
    ui.openPopover=null;
  }
  ui.popoverNodeId=node.id;

  s.inspector.classList.add('cgc-active');
  if(ui.expanded)s.inspector.classList.add('cgc-expanded');
  else s.inspector.classList.remove('cgc-expanded');

  const advancedDetails=s.inspector.querySelector('.cc-node-advanced');
  const advancedBody=advancedDetails?.querySelector('div')||advancedDetails;
  const promptInput=s.inspector.querySelector('[aria-label="文本或提示词"]');
  const promptWrapper=promptInput?.parentElement;

  for(const child of [...s.inspector.children]){
    if(child===advancedDetails||child.classList?.contains('cc-run-form'))continue;
    if(child===promptWrapper)continue;
    if(advancedBody)advancedBody.append(child);
  }

  const runOptions=s.composerRunOptions||null;
  if(!runOptions)refreshOptions(s,helpers,false);

  const operations=runOptions?.operations||[];
  const operation=inferNodeOperation(node,s.document.edges,operations);
  const modelList=runOptions
    ?buildCanvasModelDropdownList({modality:node.type,operation,runOptions})
    :[];
  const eff=resolveEffectiveGeneratorParams(node,operation,modelList,runOptions);

  // 1. Top capsule bar (+参考 | 聚焦 ... 放大/退出放大)
  const topBar=dom(doc,'div','cgc-top-bar');
  const topLeft=dom(doc,'div','cgc-top-left');

  const connectedEdges=s.document.edges.filter(e=>e.target===node.id&&e.port!=='derived_from');
  const refSupports=eff.formatObj?eff.formatObj.supports_reference_materials!==false:true;
  const refBtn=dom(doc,'button','cgc-pill cgc-ref-btn');
  refBtn.type='button';
  refBtn.disabled=Boolean(s.readOnly||!refSupports);
  refBtn.title=!refSupports?'当前格式不支持参考素材，请移除参考素材或切换格式':'点击后在画布中选择支持的参考节点';
  refBtn.setAttribute('aria-label','参考');
  refBtn.append(iconPlus(doc),dom(doc,'span','','参考'));
  if(connectedEdges.length){
    refBtn.append(dom(doc,'span','cgc-pill-count',String(connectedEdges.length)));
  }
  refBtn.addEventListener('click',()=>{if(typeof helpers.beginReferencePick==='function')helpers.beginReferencePick(s,node);else helpers.referencePanel(s,node);});
  topLeft.append(refBtn);

  const focusBtn=dom(doc,'button','cgc-pill cgc-focus-btn');
  focusBtn.type='button';
  focusBtn.title='聚焦';
  focusBtn.setAttribute('aria-label','聚焦');
  focusBtn.append(iconFocus(doc),dom(doc,'span','','聚焦'));
  focusBtn.addEventListener('click',()=>{if(typeof helpers.openFocusCapture==='function')helpers.openFocusCapture(s,node);else helpers.focusNode(s,node);});
  topLeft.append(focusBtn);

  for(const edge of connectedEdges){
    const src=s.document.nodes.find(n=>n.id===edge.source);
    if(!src)continue;
    const chip=dom(doc,'span','cgc-ref-chip');
    chip.append(dom(doc,'span','cgc-ref-chip-text',`@${src.title||src.id.slice(0,6)}`));
    if(!s.readOnly){
      if(typeof helpers.openFocusCapture==='function'&&src.type==='image'&&src.media_id){
        const focus=dom(doc,'button','cgc-ref-chip-focus','聚焦');
        focus.type='button';
        focus.setAttribute('aria-label',`聚焦 ${src.title||src.id}`);
        focus.addEventListener('click',event=>{event.stopPropagation();helpers.openFocusCapture(s,node,{sourceId:src.id,edgeId:edge.id});});
        chip.append(focus);
      }
      const rm=dom(doc,'button','cgc-ref-chip-remove','×');
      rm.type='button';
      rm.setAttribute('aria-label',`移除参考 ${src.title||src.id}`);
      rm.addEventListener('click',()=>{
        helpers.change(s,()=>{s.document.edges=s.document.edges.filter(x=>x.id!==edge.id);});
      });
      chip.append(rm);
    }
    if(typeof helpers.focusReferenceSource==='function')chip.addEventListener('dblclick',event=>{event.stopPropagation();helpers.focusReferenceSource(s,src,node);});
    topLeft.append(chip);
  }

  const topRight=dom(doc,'div','cgc-top-right');
  const expandLabel=ui.expanded?'退出放大':'放大';
  const expandBtn=dom(doc,'button','cgc-icon-btn cgc-expand-btn');
  expandBtn.type='button';
  expandBtn.title=expandLabel;
  expandBtn.setAttribute('aria-label',expandLabel);
  expandBtn.setAttribute('aria-pressed',String(ui.expanded));
  expandBtn.append(iconExpand(doc,ui.expanded));
  expandBtn.addEventListener('click',()=>{
    ui.expanded=!ui.expanded;
    rerenderIfActive(s,helpers);
  });
  topRight.append(expandBtn);
  topBar.append(topLeft,topRight);

  // 2. Prompt area
  const promptArea=dom(doc,'div','cgc-prompt-wrap');
  const placeholderText=promptPlaceholderFor(node,operation);
  if(promptInput&&promptWrapper){
    promptWrapper.classList.add('cgc-prompt-label');
    promptInput.classList.add('cgc-prompt-input');
    promptInput.setAttribute('placeholder',placeholderText);
    promptInput.rows=ui.expanded?7:3;
    promptArea.append(promptWrapper);
    if(typeof helpers.mountPromptTools==='function'){
      const tools=dom(doc,'div','crs-prompt-tools');
      tools.dataset.slot='prompt-tools';
      promptArea.append(tools);
      helpers.mountPromptTools({root:tools,node,promptInput,s,doc,operation,eff});
    }
  }

  // 3. Bottom parameter bar
  const bottomBar=dom(doc,'div','cgc-bottom-bar');
  const leftControls=dom(doc,'div','cgc-controls-left');

  const togglePopover=name=>{
    ui.openPopover=ui.openPopover===name?null:name;
    rerenderIfActive(s,helpers);
  };

  // 3a. Model dropdown
  const modelAnchor=dom(doc,'div','cgc-popover-anchor cgc-model-anchor');
  const modelBtn=dom(doc,'button','cgc-bar-btn cgc-model-trigger'+(ui.openPopover==='model'?' is-open':''));
  modelBtn.type='button';
  modelBtn.disabled=Boolean(s.readOnly);
  const modelDisplay=eff.activeModel&&!eff.activeModel.disabled
    ?eff.activeModel.showName
    :(runOptions?(modelList[0]?.showName||'请选择模型'):'加载中');
  modelBtn.title=eff.activeModel?.disabled?eff.activeModel.disabledReason:modelDisplay;
  modelBtn.setAttribute('aria-label','选择模型');
  modelBtn.setAttribute('aria-expanded',String(ui.openPopover==='model'));
  modelBtn.append(dom(doc,'span','cgc-model-label',modelDisplay),iconChevron(doc));
  modelBtn.addEventListener('click',e=>{e.stopPropagation();togglePopover('model');});
  modelAnchor.append(modelBtn);
  if(ui.openPopover==='model'){
    modelAnchor.append(renderModelPopover(doc,s,node,operation,modelList,eff,ui,helpers));
  }
  leftControls.append(modelAnchor);

  // 3b. Output format dropdown (image)
  if(node.type==='image'&&eff.formats.length){
    const fmtAnchor=dom(doc,'div','cgc-popover-anchor cgc-format-anchor');
    const fmtLabel=eff.formatObj?.label||(eff.outputFormat||'png').toUpperCase();
    const fmtBtn=dom(doc,'button','cgc-bar-btn cgc-format-trigger'+(ui.openPopover==='format'?' is-open':''));
    fmtBtn.type='button';
    fmtBtn.disabled=Boolean(s.readOnly);
    fmtBtn.title='输出格式';
    fmtBtn.setAttribute('aria-label','输出格式');
    fmtBtn.setAttribute('aria-expanded',String(ui.openPopover==='format'));
    fmtBtn.append(dom(doc,'span','cgc-format-label',fmtLabel),iconChevron(doc));
    fmtBtn.addEventListener('click',e=>{e.stopPropagation();togglePopover('format');});
    fmtAnchor.append(fmtBtn);
    if(ui.openPopover==='format'){
      fmtAnchor.append(renderFormatPopover(doc,s,node,operation,modelList,eff,ui,helpers));
    }
    leftControls.append(fmtAnchor);
  }

  leftControls.append(dom(doc,'span','cgc-divider'));

  // 3c. Merged specs button + popover
  const specsAnchor=dom(doc,'div','cgc-popover-anchor cgc-specs-anchor');
  const specsSummary=formatSpecsSummary(node,eff);
  const specsBtn=dom(doc,'button','cgc-bar-btn cgc-specs-trigger'+(ui.openPopover==='specs'?' is-open':''));
  specsBtn.type='button';
  specsBtn.disabled=Boolean(s.readOnly);
  specsBtn.title='参数';
  specsBtn.setAttribute('aria-label','参数');
  specsBtn.setAttribute('aria-expanded',String(ui.openPopover==='specs'));
  specsBtn.append(iconSpecs(doc),dom(doc,'span','cgc-specs-label',specsSummary),iconChevron(doc));
  specsBtn.addEventListener('click',e=>{e.stopPropagation();togglePopover('specs');});
  specsAnchor.append(specsBtn);
  if(ui.openPopover==='specs'){
    specsAnchor.append(renderSpecsPopover(doc,s,node,operation,modelList,eff,helpers));
  }
  leftControls.append(specsAnchor);

  // 3d. Virtual camera (image_generate)
  if(node.type==='image'&&eff.camOpts){
    leftControls.append(dom(doc,'span','cgc-divider'));
    const camAnchor=dom(doc,'div','cgc-popover-anchor cgc-camera-anchor');
    const camDisabled=Boolean(s.readOnly||!eff.supportsCamera);
    const camBtn=dom(doc,'button','cgc-icon-btn cgc-camera-trigger'+(eff.photographyEnabled?' is-enabled':'')+(ui.openPopover==='camera'?' is-open':''));
    camBtn.type='button';
    camBtn.disabled=camDisabled;
    camBtn.setAttribute('aria-label','摄像机');
    camBtn.setAttribute('aria-expanded',String(ui.openPopover==='camera'));
    if(!eff.cameraSupportedByFormat){
      camBtn.title='当前格式不支持镜头参数，请关闭镜头参数或切换格式';
    }else{
      camBtn.title='摄像机';
    }
    camBtn.append(iconCamera(doc));
    if(eff.photographyEnabled)camBtn.append(dom(doc,'span','cgc-camera-dot'));
    camBtn.addEventListener('click',e=>{e.stopPropagation();if(!camDisabled)togglePopover('camera');});

    const camBodyLabel=(eff.camOpts.cameras||[]).find(c=>c.id===eff.cameraModel)?.label||eff.cameraModel;
    const camLensLabel=(eff.camOpts.lenses||[]).find(l=>l.id===eff.lensModel)?.label||eff.lensModel;
    const hoverCard=dom(doc,'div','cgc-camera-hover');
    hoverCard.append(
      dom(doc,'span','cgc-camera-hover-spec',`${camBodyLabel} | ${camLensLabel} / ${eff.focalMm}mm / ${eff.aperture}`),
      dom(doc,'span','cgc-camera-hover-status'+(eff.photographyEnabled?' is-on':''),eff.photographyEnabled?'已开启':'已关闭'),
    );
    camAnchor.append(camBtn,hoverCard);
    if(ui.openPopover==='camera'){
      camAnchor.append(renderCameraPanel(doc,s,node,operation,modelList,eff,ui,helpers));
    }
    leftControls.append(camAnchor);
  }

  // 3e. Style entry + slot (#11)
  if(node.type==='image'){
    leftControls.append(dom(doc,'span','cgc-divider'));
    const styleAnchor=dom(doc,'div','cgc-popover-anchor cgc-style-anchor');
    const styleLabel=typeof helpers.styleLabelFor==='function'?helpers.styleLabelFor(eff.styleId,node):(eff.styleId&&eff.styleId!=='none'?eff.styleId:'风格');
    const styleBtn=dom(doc,'button','cgc-bar-btn cgc-style-trigger'+(ui.openPopover==='style'?' is-open':''));
    styleBtn.type='button';
    styleBtn.disabled=Boolean(s.readOnly);
    styleBtn.title='风格';
    styleBtn.setAttribute('aria-label','风格');
    styleBtn.setAttribute('aria-expanded',String(ui.openPopover==='style'));
    styleBtn.append(iconPalette(doc),dom(doc,'span','cgc-style-label',styleLabel),iconChevron(doc));
    styleBtn.addEventListener('click',e=>{e.stopPropagation();togglePopover('style');});
    styleAnchor.append(styleBtn);
    if(ui.openPopover==='style'){
      styleAnchor.append(renderStylePopover(doc,s,node,operation,modelList,eff,ui,helpers));
    }
    leftControls.append(styleAnchor);
  }

  // Slot for video/audio mode controls (#8 / #9)
  const modeSlot=dom(doc,'div','cgc-mode-slot');
  modeSlot.dataset.slot='mode-controls';
  modeSlot.dataset.modality=node.type;
  if(node.type==='video'&&eff.spec?.modality==='video'){
    const audioToggle=dom(doc,'button','cgc-bar-btn cgc-audio-toggle'+(eff.generateAudio?' is-active':''),eff.generateAudio?'有声':'静音');
    audioToggle.type='button';
    audioToggle.disabled=Boolean(s.readOnly);
    audioToggle.title='生成音频';
    audioToggle.setAttribute('aria-label','生成音频');
    audioToggle.setAttribute('aria-pressed',String(eff.generateAudio));
    audioToggle.addEventListener('click',()=>{
      helpers.change(s,()=>{
        node.params.vsc_gen_generate_audio=!eff.generateAudio;
        const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
        applyConvergedPatchToNode(node,converged);
      });
    });
    modeSlot.append(audioToggle);
  }
  if(typeof helpers.mountGeneratorModeSlot==='function'){
    helpers.mountGeneratorModeSlot({root:modeSlot,node,operation,eff});
  }
  leftControls.append(modeSlot);

  // 3f. Translate button
  const promptAssist=runOptions?.prompt_assist;
  const translateAvailable=Boolean(promptAssist?.available);
  const translateBusy=ui.translatingNodeId===node.id;
  const translateReason=!runOptions
    ?'正在检测本地翻译工具状态'
    :(!translateAvailable?(promptAssist?.unavailable_reason||'本地文本翻译工具不可用'):'翻译');
  const translateBtn=dom(doc,'button','cgc-icon-btn cgc-translate-btn'+(translateBusy?' is-busy':''));
  translateBtn.type='button';
  translateBtn.disabled=Boolean(s.readOnly||!translateAvailable||translateBusy);
  translateBtn.title=translateReason;
  translateBtn.setAttribute('aria-label','翻译');
  if(!translateAvailable&&promptAssist?.unavailable_reason){
    translateBtn.dataset.disabledReason=promptAssist.unavailable_reason;
  }
  translateBtn.append(iconTranslate(doc));
  translateBtn.addEventListener('click',()=>runTranslatePrompt(s,node,helpers));
  leftControls.append(translateBtn);

  // 3g. Advanced settings button
  const advBtn=dom(doc,'button','cgc-icon-btn cgc-advanced-btn'+(ui.advancedOpen?' is-active':''));
  advBtn.type='button';
  advBtn.title='高级设置';
  advBtn.setAttribute('aria-label','高级设置');
  advBtn.setAttribute('aria-expanded',String(ui.advancedOpen));
  advBtn.append(iconAdvanced(doc));
  advBtn.addEventListener('click',()=>{
    ui.advancedOpen=!ui.advancedOpen;
    rerenderIfActive(s,helpers);
  });
  leftControls.append(advBtn);

  // Right controls: Real-time quote + Send / 5s Countdown
  const rightControls=dom(doc,'div','cgc-controls-right');
  const quoteBox=dom(doc,'div','cgc-quote-box');
  quoteBox.dataset.nodeId=node.id;
  const currentQuote=ui.quotes.get(node.id);
  renderQuoteContents(doc,quoteBox,currentQuote,()=>{
    scheduleRealtimeQuote(s,node,operation,eff,helpers,{immediate:true});
    updateQuoteDomInPlace(s,node.id,helpers);
  });
  rightControls.append(quoteBox);

  const pending=ui.pendingSubmits.get(node.id);
  const sendArea=dom(doc,'div','cgc-send-area');
  if(pending){
    const cdWrap=dom(doc,'div','cgc-countdown-pill');
    const cdText=dom(doc,'span','cgc-countdown-text',`${pending.remaining}s 后提交`);
    const cancelBtn=dom(doc,'button','cgc-cancel-submit-btn','撤回任务');
    cancelBtn.type='button';
    cancelBtn.setAttribute('aria-label','撤回任务');
    cancelBtn.addEventListener('click',()=>cancelPendingSubmit(s,node.id,helpers));
    cdWrap.append(cdText,cancelBtn);
    sendArea.append(cdWrap);
  }else{
    const quoteBlocked=currentQuote&&currentQuote.status==='ready'&&currentQuote.ready===false;
    const sendBtn=dom(doc,'button','cgc-send-btn cc-generator-send');
    sendBtn.type='button';
    sendBtn.dataset.canvasSend='true';
    sendBtn.setAttribute('aria-label','生成');
    const syncSendState=()=>{
      const curText=promptInput&&typeof promptInput.value==='string'?promptInput.value:String(node.text||'');
      const hasInput=Boolean(curText.trim()||connectedEdges.length);
      const blockReason=typeof helpers.generationBlockReason==='function'?helpers.generationBlockReason(node):'';
      const canSend=Boolean(!s.readOnly&&eff.modelId&&hasInput&&!quoteBlocked&&!blockReason);
      sendBtn.disabled=!canSend;
      sendBtn.title=blockReason||(!eff.modelId
        ?(eff.activeModel?.disabledReason||'请选择可用的生成模型')
        :(!hasInput?'请输入提示词或添加参考素材'
          :(quoteBlocked?((currentQuote.gaps||[]).map(g=>g.message).join('；')||'当前额度不足'):'生成')));
    };
    sendBtn.append(iconSend(doc));
    syncSendState();
    if(promptInput)promptInput.addEventListener('input',syncSendState);
    sendBtn.addEventListener('click',()=>startCountdownSubmit(s,node,operation,eff,helpers));
    sendArea.append(sendBtn);
  }
  rightControls.append(sendArea);
  bottomBar.append(leftControls,rightControls);

  // 4. Advanced settings drawer (智能引用 switch)
  const composerFragment=[topBar,promptArea,bottomBar];
  if(ui.advancedOpen){
    const drawer=dom(doc,'div','cgc-advanced-drawer');
    const drawerHead=dom(doc,'div','cgc-advanced-head');
    drawerHead.append(iconAdvanced(doc),dom(doc,'span','','高级设置'));
    const smartRow=dom(doc,'div','cgc-advanced-row');
    smartRow.append(dom(doc,'span','cgc-advanced-row-label','智能引用'));
    const smartSwitch=dom(doc,'button','cgc-switch'+(eff.smartRef?' is-on':''));
    smartSwitch.type='button';
    smartSwitch.disabled=Boolean(s.readOnly);
    smartSwitch.setAttribute('role','switch');
    smartSwitch.setAttribute('aria-label','智能引用');
    smartSwitch.setAttribute('aria-checked',String(eff.smartRef));
    smartSwitch.append(dom(doc,'span','cgc-switch-thumb'));
    smartSwitch.addEventListener('click',()=>{
      helpers.change(s,()=>{
        node.params.vsc_gen_smart_ref=!eff.smartRef;
        const converged=resolveEffectiveGeneratorParams(node,operation,modelList,s.composerRunOptions);
        applyConvergedPatchToNode(node,converged);
      });
    });
    smartRow.append(smartSwitch);
    drawer.append(drawerHead,smartRow);
    composerFragment.push(drawer);
  }

  const anchorBefore=s.inspector.children?.[0]||advancedDetails||null;
  if(anchorBefore){
    for(const item of composerFragment)s.inspector.insertBefore(item,anchorBefore);
  }else{
    s.inspector.append(...composerFragment);
  }

  if(runOptions&&eff.modelId){
    scheduleRealtimeQuote(s,node,operation,eff,helpers,{immediate:false});
  }
}
