import {msg,setText,bindAttribute} from './i18n.js';
// A visual editor of the existing tool_settings object, never a second scene model.
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)setText(node,text);if(cls)node.className=cls;return node;};
const svg=(tag,attrs={})=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));return node;};
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const presets={custom:msg("ui.custom"),fisheye:msg("ui.fisheye_view"),tilt:msg("ui.tilted_view"),front_high:msg("ui.front_high_angle"),front_low:msg("ui.front_low_angle"),top:msg("ui.overhead_wide_view"),back:msg("ui.rear_view")};
const presetValues={fisheye:{yaw:0,pitch:0,roll:0,zoom:.5},tilt:{yaw:0,pitch:0,roll:20,zoom:1},front_high:{yaw:0,pitch:30,roll:0,zoom:1},front_low:{yaw:0,pitch:-30,roll:0,zoom:1},top:{yaw:0,pitch:90,roll:0,zoom:1},back:{yaw:180,pitch:0,roll:0,zoom:1}};
const canvasPresets={custom:{yaw:0,pitch:0,roll:0,zoom:1},fisheye:{yaw:0,pitch:30,roll:0,zoom:2},tilt:{yaw:45,pitch:-30,roll:0,zoom:1},front_high:{yaw:0,pitch:60,roll:0,zoom:1},front_low:{yaw:0,pitch:-30,roll:0,zoom:1},top:{yaw:45,pitch:30,roll:0,zoom:.5},back:{yaw:180,pitch:0,roll:0,zoom:1}};
const canvasLightLevels=[.1,.25,.5,.75,1];
const lights={left:{name:msg("ui.left"),point:[40,120]},top:{name:msg("ui.top"),point:[120,35]},right:{name:msg("ui.right"),point:[200,120]},front:{name:msg("ui.front"),point:[93,172]},bottom:{name:msg("ui.bottom"),point:[120,205]},back:{name:msg("ui.back"),point:[151,76]}};

export function mountImageControls(host,{tool,settings,defaults,onChange,isCurrent=()=>true,imageUrl=null,onClose=null,canvas=false,promptState=null,onSubmit=null,onError=null}){
  if(!['angle','lighting'].includes(tool))throw new Error('不支持的图像控件');
  const angle=tool==='angle',fields=new Map(),choices=[],root=el('section',null,`image-controls image-controls--${tool}`);
  bindAttribute(root,'aria-label',angle?msg("ui.multi_angle_editor"):msg("ui.lighting_effects"));host.append(root);
  const header=el('header',null,'image-controls-header');header.append(el('h3',angle?msg("ui.multi_angle_editor"):msg("ui.lighting_effects")));root.append(header);
  if(onClose){const close=el('button','×','image-controls-close');close.type='button';bindAttribute(close,'aria-label',msg('common.close'));close.addEventListener('click',()=>{if(isCurrent())onClose();});header.append(close);}
  const choiceBar=el('div',null,'image-controls-choices');if(angle)root.append(choiceBar);
  const presetDrafts=new Map();
  let activePreset=settings.preset||'custom';
  let syncPromptFields=()=>{};
  let updatePresetPrompt=()=>{};
  const saveCurrentPresetDraft=()=>{
    if(!canvas||!angle)return;
    presetDrafts.set(activePreset,{
      yaw:settings.yaw,pitch:settings.pitch,roll:settings.roll,zoom:settings.zoom,
      promptEnabled:Boolean(promptState?.promptEnabled),prompt:promptState?.prompt||'',presetPrompt:Boolean(promptState?.presetPrompt)
    });
  };
  const commit=patch=>{
    if(!isCurrent())return;
    Object.assign(settings,patch);
    if(canvas&&angle)saveCurrentPresetDraft();
    sync();
    onChange(settings);
  };
  function button(host,label,action){const node=el('button',label);node.type='button';node.addEventListener('click',()=>{if(isCurrent())action();});host.append(node);return node;}
  if(angle)for(const [key,label]of Object.entries(presets)){
    const node=button(choiceBar,label,()=>{
      if(canvas){
        saveCurrentPresetDraft();
        activePreset=key;
        const saved=presetDrafts.get(key);
        if(saved){
          if(promptState){
            promptState.promptEnabled=saved.promptEnabled;
            promptState.prompt=saved.prompt;
            promptState.presetPrompt=saved.presetPrompt;
            syncPromptFields();
          }
          commit({preset:key,yaw:saved.yaw,pitch:saved.pitch,roll:saved.roll,zoom:saved.zoom});
          return;
        }
      }
      commit({preset:key,...((canvas?canvasPresets:presetValues)[key]||{})});
      if(canvas){updatePresetPrompt(key);saveCurrentPresetDraft();}
    });
    choices.push([node,'preset',key]);
  }
  else for(const [key,label]of [['perspective',msg("ui.perspective")],['front',msg("ui.front_view")]]){const node=button(choiceBar,label,()=>commit({view:key}));choices.push([node,'view',key]);}
  const body=el('div',null,'image-controls-body'),visual=svg('svg',{viewBox:'0 0 240 240',role:'group','aria-label':angle?'拖动虚拟摄影机；方向键调节环绕和俯仰':'拖动光源并吸附到六个方向；方向键选择方位',tabindex:0});
  visual.classList.add('image-controls-orbit');const visualColumn=el('div',null,'image-controls-visual');if(!angle)visualColumn.append(choiceBar);visualColumn.append(visual);body.append(visualColumn);root.append(body);
  visual.append(svg('circle',{cx:120,cy:120,r:68,class:'orbit-sphere'}));
  for(const ry of [18,36,52])visual.append(svg('ellipse',{cx:120,cy:120,rx:68,ry,class:'orbit-grid'}));
  for(const rx of [18,36,52])visual.append(svg('ellipse',{cx:120,cy:120,rx,ry:68,class:'orbit-grid'}));
  const cone=svg('path',{class:'orbit-cone'}),subject=svg('g',{class:'orbit-subject'});
  if(imageUrl){const picture=svg('image',{x:100,y:105,width:40,height:30,href:imageUrl,preserveAspectRatio:'xMidYMid slice',class:'orbit-image'});subject.append(picture);}else subject.append(svg('rect',{x:101,y:107,width:38,height:26,rx:2,class:'orbit-picture'}),svg('path',{d:'M105 127 L113 119 L119 124 L126 116 L135 127 M110 112 h2',class:'orbit-picture-line'}));visual.append(cone,subject);
  const marker=svg('g',{class:'orbit-handle'});marker.append(svg('circle',{cx:0,cy:0,r:13}),svg('path',{d:angle?'M-6 -4 H3 V4 H-6 Z M3 -2 L8 -5 V5 L3 2 Z':'M0 -7 V7 M-7 0 H7 M-5 -5 L5 5 M-5 5 L5 -5',class:'orbit-icon'}));visual.append(marker);
  const status=el('p',null,'image-controls-readout');status.setAttribute('role','status');root.append(status);
  const controls=el('div',null,'image-controls-sliders');body.append(controls);
  const advanced=el('details',null,'image-controls-advanced');advanced.append(el('summary',msg('ui.advanced_settings')),el('p',msg('ui.text_parameters_guide_the_image_model_this_control_diagram'),'image-controls-note'));
  const canvasYaw=value=>{const turn=((Math.round(value/45)*45)%360+360)%360;return turn>180?turn-360:turn;};
  const manualPresetPatch=()=>canvas?{preset:activePreset}:{preset:'custom'};
  function input(key,label,type,min,max,step){const wrapper=el('label',null,`image-controls-field image-controls-field--${type}`),caption=el('span',label,'image-controls-caption'),node=el('input'),output=el('output');wrapper.append(caption);node.type=type;bindAttribute(node,'aria-label',label);if(min!=null){node.min=String(min);node.max=String(max);node.step=String(step);}wrapper.append(node,output);(key==='roll'||key==='cone'?advanced:controls).append(wrapper);fields.set(key,{node,output});node.addEventListener('input',()=>{let value=type==='checkbox'?node.checked:type==='color'?node.value:Number(node.value);if(canvas&&key==='yaw')value=canvasYaw(value);if(canvas&&key==='zoom')value=[.5,1,2][value];if(canvas&&key==='intensity')value=canvasLightLevels[value];commit({[key]:value,...(angle&&key!=='include_instructions'?manualPresetPatch():{})});});}
  if(angle){input('yaw',msg("ui.horizontal_orbit"),'range',canvas?0:-180,canvas?315:180,canvas?45:1);input('pitch',msg("ui.vertical_pitch"),'range',canvas?-30:-90,canvas?60:90,canvas?30:1);input('roll',msg("ui.roll"),'range',-180,180,1);input('zoom',msg("ui.framing_zoom"),'range',canvas?0:.25,canvas?2:4,canvas?1:.05);if(!canvas)input('include_instructions',msg("ui.include_angle_instructions_in_the_model_prompt"),'checkbox');
    if(canvas&&promptState){const wrap=el('label',null,'image-controls-field image-controls-field--checkbox'),toggle=el('input'),description=el('textarea');toggle.type='checkbox';toggle.checked=Boolean(promptState.promptEnabled);bindAttribute(toggle,'aria-label','提示词');wrap.append(el('span','提示词'),toggle);controls.append(wrap);bindAttribute(description,'aria-label','补充提示词');description.placeholder='补充需要保留或调整的画面描述';description.value=promptState.prompt||'';description.hidden=!toggle.checked;syncPromptFields=()=>{toggle.checked=Boolean(promptState.promptEnabled);description.hidden=!toggle.checked;description.value=promptState.prompt||'';};toggle.addEventListener('change',()=>{if(!isCurrent())return;promptState.promptEnabled=toggle.checked;description.hidden=!toggle.checked;saveCurrentPresetDraft();});description.addEventListener('input',()=>{if(isCurrent()){promptState.prompt=description.value;promptState.presetPrompt=false;saveCurrentPresetDraft();}});updatePresetPrompt=key=>{const presetText={fisheye:'鱼眼镜头，超广角透视',tilt:'倾斜镜头视角'}[key];promptState.promptEnabled=Boolean(presetText);if(presetText){promptState.prompt=presetText;promptState.presetPrompt=true;}else{promptState.prompt='';promptState.presetPrompt=false;}syncPromptFields();};controls.append(description);}
    const arrows=el('div',null,'image-controls-arrows');visualColumn.append(arrows);for(const [axis,delta,label,icon]of [['yaw',-15,msg("ui.left_15"),'←'],['pitch',15,msg("ui.up_15"),'↑'],['pitch',-15,msg("ui.down_15"),'↓'],['yaw',15,msg("ui.right_15"),'→']])button(arrows,canvas?icon:label,()=>commit({[axis]:canvas&&axis==='yaw'?canvasYaw(settings[axis]+Math.sign(delta)*45):clamp(settings[axis]+(canvas?delta*2:delta),axis==='yaw'?-180:canvas?-30:-90,axis==='yaw'?180:canvas?60:90),...manualPresetPatch()}));
  }else{input('intensity',msg("ui.light_intensity"),'range',0,canvas?4:5,canvas?1:.05);input('color',msg("ui.light_color"),'color');input('cone',msg("ui.light_cone_angle"),'range',1,180,1);const grid=el('div',null,'image-controls-directions');grid.append(el('span',canvas?'主光源':msg('ui.lighting_effects'),'image-controls-direction-label'));controls.append(grid);for(const [key,{name}]of Object.entries(lights)){const node=button(grid,name,()=>commit({direction:key}));choices.push([node,'direction',key]);}input('rim',msg("ui.enable_rim_light"),'checkbox');}
  if(!canvas)controls.append(advanced);
  const footer=el('footer',null,'image-controls-footer');root.append(footer);
  button(footer,msg("ui.reset_parameters"),()=>{
    presetDrafts.clear();
    activePreset=defaults.preset||'custom';
    if(canvas&&promptState){promptState.promptEnabled=false;promptState.prompt='';promptState.presetPrompt=false;syncPromptFields();}
    commit({...defaults});
  });
  if(canvas&&onSubmit){const submit=el('button','↑','image-controls-submit');submit.type='button';bindAttribute(submit,'aria-label','继续生成');submit.addEventListener('click',async()=>{if(!isCurrent()||submit.disabled)return;submit.disabled=true;try{await onSubmit();}catch(error){onError?.(error);}finally{submit.disabled=false;}});footer.append(submit);}
  let drag=null;
  visual.addEventListener('pointerdown',event=>{if(!isCurrent())return;event.preventDefault();visual.setPointerCapture?.(event.pointerId);drag={id:event.pointerId,x:event.clientX,y:event.clientY,yaw:settings.yaw,pitch:settings.pitch};if(!angle)move(event);});
  function move(event){if(!drag||event.pointerId!==drag.id||!isCurrent())return;const box=visual.getBoundingClientRect();if(!box.width||!box.height)return;
    if(angle)commit({yaw:canvas?canvasYaw(drag.yaw+(event.clientX-drag.x)*360/box.width):Math.round(clamp(drag.yaw+(event.clientX-drag.x)*360/box.width,-180,180)),pitch:canvas?Math.round(clamp(drag.pitch-(event.clientY-drag.y)*180/box.height,-30,60)/30)*30:Math.round(clamp(drag.pitch-(event.clientY-drag.y)*180/box.height,-90,90)),...manualPresetPatch()});
    else{const x=(event.clientX-box.left)*240/box.width,y=(event.clientY-box.top)*240/box.height;const direction=Object.entries(lights).sort((a,b)=>Math.hypot(x-a[1].point[0],y-a[1].point[1])-Math.hypot(x-b[1].point[0],y-b[1].point[1]))[0][0];commit({direction});}}
  visual.addEventListener('pointermove',move);for(const event of ['pointerup','pointercancel','lostpointercapture'])visual.addEventListener(event,()=>{drag=null;});
  visual.addEventListener('keydown',event=>{if(!isCurrent()||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(event.key))return;event.preventDefault();if(event.key==='Home'){presetDrafts.clear();activePreset=defaults.preset||'custom';if(canvas&&promptState){promptState.promptEnabled=false;promptState.prompt='';promptState.presetPrompt=false;syncPromptFields();}commit({...defaults});return;}if(angle){const axis=['ArrowLeft','ArrowRight'].includes(event.key)?'yaw':'pitch',delta=['ArrowRight','ArrowUp'].includes(event.key)?15:-15;commit({[axis]:canvas&&axis==='yaw'?canvasYaw(settings[axis]+Math.sign(delta)*45):clamp(settings[axis]+(canvas?delta*2:delta),axis==='yaw'?-180:canvas?-30:-90,axis==='yaw'?180:canvas?60:90),...manualPresetPatch()});}else{const keys=Object.keys(lights),index=keys.indexOf(settings.direction);commit({direction:keys[(index+(['ArrowRight','ArrowDown'].includes(event.key)?1:5))%6]});}});
  function sync(){for(const [key,{node,output}]of fields){if(node.type==='checkbox')node.checked=Boolean(settings[key]);else node.value=String(canvas&&key==='yaw'?(settings[key]+360)%360:canvas&&key==='zoom'?settings[key]<=.5?0:settings[key]>=2?2:1:canvas&&key==='intensity'?canvasLightLevels.indexOf(settings[key]):settings[key]);setText(output,node.type==='checkbox'?'':key==='intensity'?`${Math.round(settings[key]*100)}%`:key==='yaw'&&canvas?`${(settings[key]+360)%360}°`:key==='yaw'||key==='pitch'||key==='roll'?`${settings[key]}°`:canvas&&key==='zoom'?settings[key]<=.5?'全景':settings[key]>=2?'特写':'中景':String(settings[key]));}for(const [node,key,value]of choices)node.setAttribute('aria-pressed',String((canvas&&angle&&key==='preset'?activePreset:settings[key])===value));
    let x,y,back=false;if(angle){const yaw=settings.yaw*Math.PI/180,pitch=settings.pitch*Math.PI/180;x=120+Math.sin(yaw)*Math.cos(pitch)*80;y=120-Math.sin(pitch)*80+Math.cos(yaw)*Math.cos(pitch)*22;back=Math.cos(yaw)<0;}else{[x,y]=lights[settings.direction].point;back=settings.direction==='back';}
    marker.setAttribute('transform',`translate(${x} ${y})`);marker.setAttribute('opacity',back?'.65':'1');const spread=angle?12:clamp(settings.cone/4,2,42);cone.setAttribute('d',`M${x} ${y} L${120-spread} 145 L${120+spread} 145 Z`);cone.setAttribute('fill',angle?'#7b8cff':settings.color);cone.setAttribute('opacity',angle?'.22':String(.08+settings.intensity*.06));cone.setAttribute('stroke-dasharray',back?'4 4':'none');visual.setAttribute('data-view',angle?'camera':settings.view);
    setText(status,angle?msg("ui.orbit_value0_pitch_value1_value2_value3",{value0:settings.yaw,value1:settings.pitch,value2:settings.zoom,value3:settings.include_instructions?'':msg("ui.angle_instructions_excluded_from_prompt")}):msg("ui.value0_key_light_value1_value2_cone_value3",{value0:lights[settings.direction].name,value1:Math.round(settings.intensity*100),value2:settings.cone,value3:settings.rim?msg("ui.rim_light_enabled"):''}));
  }
  if(canvas&&angle)saveCurrentPresetDraft();
  sync();return {sync,dispose(){drag=null;root.remove();}};
}
