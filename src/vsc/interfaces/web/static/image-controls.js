import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
// A visual editor of the existing tool_settings object, never a second scene model.
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)setText(node,text);if(cls)node.className=cls;return node;};
const svg=(tag,attrs={})=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));return node;};
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const presets={custom:msg("ui.custom"),fisheye:msg("ui.fisheye_view"),tilt:msg("ui.tilted_view"),front_high:msg("ui.front_high_angle"),front_low:msg("ui.front_low_angle"),top:msg("ui.overhead_wide_view"),back:msg("ui.rear_view")};
const presetValues={fisheye:{yaw:0,pitch:0,roll:0,zoom:.5},tilt:{yaw:0,pitch:0,roll:20,zoom:1},front_high:{yaw:0,pitch:30,roll:0,zoom:1},front_low:{yaw:0,pitch:-30,roll:0,zoom:1},top:{yaw:0,pitch:90,roll:0,zoom:1},back:{yaw:180,pitch:0,roll:0,zoom:1}};
const lights={left:{name:msg("ui.left"),point:[40,120]},top:{name:msg("ui.top"),point:[120,35]},right:{name:msg("ui.right"),point:[200,120]},front:{name:msg("ui.front"),point:[93,172]},bottom:{name:msg("ui.bottom"),point:[120,205]},back:{name:msg("ui.back"),point:[151,76]}};

export function mountImageControls(host,{tool,settings,defaults,onChange,isCurrent=()=>true}){
  if(!['angle','lighting'].includes(tool))throw new Error('不支持的图像控件');
  const angle=tool==='angle',fields=new Map(),choices=[],root=el('section',null,'image-controls');
  bindAttribute(root,'aria-label',angle?msg("ui.multi_angle_editor"):msg("ui.lighting_effects"));host.append(root);
  root.append(el('h3',angle?msg("ui.multi_angle_editor"):msg("ui.lighting_effects")),el('p',msg("ui.text_parameters_guide_the_image_model_this_control_diagram"),'image-controls-note'));
  const choiceBar=el('div',null,'image-controls-choices');root.append(choiceBar);
  const commit=patch=>{if(!isCurrent())return;Object.assign(settings,patch);sync();onChange(settings);};
  function button(host,label,action){const node=el('button',label);node.type='button';node.addEventListener('click',()=>{if(isCurrent())action();});host.append(node);return node;}
  if(angle)for(const [key,label]of Object.entries(presets)){const node=button(choiceBar,label,()=>commit({preset:key,...(presetValues[key]||{})}));choices.push([node,'preset',key]);}
  else for(const [key,label]of [['perspective',msg("ui.perspective")],['front',msg("ui.front_view")]]){const node=button(choiceBar,label,()=>commit({view:key}));choices.push([node,'view',key]);}
  const body=el('div',null,'image-controls-body'),visual=svg('svg',{viewBox:'0 0 240 240',role:'group','aria-label':angle?'拖动虚拟摄影机；方向键调节环绕和俯仰':'拖动光源并吸附到六个方向；方向键选择方位',tabindex:0});
  visual.classList.add('image-controls-orbit');body.append(visual);root.append(body);
  visual.append(svg('circle',{cx:120,cy:120,r:86,class:'orbit-sphere'}),svg('ellipse',{cx:120,cy:120,rx:86,ry:28,class:'orbit-grid'}),svg('ellipse',{cx:120,cy:120,rx:30,ry:86,class:'orbit-grid'}));
  const cone=svg('path',{class:'orbit-cone'}),subject=svg('g',{class:'orbit-subject'});
  subject.append(svg('circle',{cx:120,cy:100,r:10}),svg('path',{d:'M120 110 L120 144 M102 127 L120 116 L138 127 M120 144 L109 163 M120 144 L131 163'}));visual.append(cone,subject);
  const marker=svg('g',{class:'orbit-handle'});marker.append(svg('circle',{cx:0,cy:0,r:13}),svg('path',{d:angle?'M-6 -4 H3 V4 H-6 Z M3 -2 L8 -5 V5 L3 2 Z':'M0 -7 V7 M-7 0 H7 M-5 -5 L5 5 M-5 5 L5 -5',class:'orbit-icon'}));visual.append(marker);
  const status=el('p',null,'image-controls-readout');status.setAttribute('role','status');root.append(status);
  const controls=el('div',null,'image-controls-sliders');body.append(controls);
  function input(key,label,type,min,max,step){const wrapper=el('label',label),node=el('input'),output=el('output');node.type=type;bindAttribute(node,'aria-label',label);if(min!=null){node.min=String(min);node.max=String(max);node.step=String(step);}wrapper.append(node,output);controls.append(wrapper);fields.set(key,{node,output});node.addEventListener('input',()=>commit({[key]:type==='checkbox'?node.checked:type==='color'?node.value:Number(node.value),...(angle&&key!=='include_instructions'?{preset:'custom'}:{})}));}
  if(angle){input('yaw',msg("ui.horizontal_orbit"),'range',-180,180,1);input('pitch',msg("ui.vertical_pitch"),'range',-90,90,1);input('roll',msg("ui.roll"),'range',-180,180,1);input('zoom',msg("ui.framing_zoom"),'range',.25,4,.05);input('include_instructions',msg("ui.include_angle_instructions_in_the_model_prompt"),'checkbox');
    const arrows=el('div',null,'image-controls-arrows');controls.append(arrows);for(const [axis,delta,label]of [['yaw',-15,msg("ui.left_15")],['pitch',15,msg("ui.up_15")],['pitch',-15,msg("ui.down_15")],['yaw',15,msg("ui.right_15")]])button(arrows,label,()=>commit({[axis]:clamp(settings[axis]+delta,axis==='yaw'?-180:-90,axis==='yaw'?180:90),preset:'custom'}));
  }else{input('intensity',msg("ui.light_intensity"),'range',0,5,.05);input('color',msg("ui.light_color"),'color');input('cone',msg("ui.light_cone_angle"),'range',1,180,1);input('rim',msg("ui.enable_rim_light"),'checkbox');const grid=el('div',null,'image-controls-directions');controls.append(grid);for(const [key,{name}]of Object.entries(lights)){const node=button(grid,name,()=>commit({direction:key}));choices.push([node,'direction',key]);}}
  button(root,msg("ui.reset_parameters"),()=>commit({...defaults}));
  let drag=null;
  visual.addEventListener('pointerdown',event=>{if(!isCurrent())return;event.preventDefault();visual.setPointerCapture?.(event.pointerId);drag={id:event.pointerId,x:event.clientX,y:event.clientY,yaw:settings.yaw,pitch:settings.pitch};if(!angle)move(event);});
  function move(event){if(!drag||event.pointerId!==drag.id||!isCurrent())return;const box=visual.getBoundingClientRect();if(!box.width||!box.height)return;
    if(angle)commit({yaw:Math.round(clamp(drag.yaw+(event.clientX-drag.x)*360/box.width,-180,180)),pitch:Math.round(clamp(drag.pitch-(event.clientY-drag.y)*180/box.height,-90,90)),preset:'custom'});
    else{const x=(event.clientX-box.left)*240/box.width,y=(event.clientY-box.top)*240/box.height;const direction=Object.entries(lights).sort((a,b)=>Math.hypot(x-a[1].point[0],y-a[1].point[1])-Math.hypot(x-b[1].point[0],y-b[1].point[1]))[0][0];commit({direction});}}
  visual.addEventListener('pointermove',move);for(const event of ['pointerup','pointercancel','lostpointercapture'])visual.addEventListener(event,()=>{drag=null;});
  visual.addEventListener('keydown',event=>{if(!isCurrent()||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(event.key))return;event.preventDefault();if(event.key==='Home'){commit({...defaults});return;}if(angle){const axis=['ArrowLeft','ArrowRight'].includes(event.key)?'yaw':'pitch',delta=['ArrowRight','ArrowUp'].includes(event.key)?15:-15;commit({[axis]:clamp(settings[axis]+delta,axis==='yaw'?-180:-90,axis==='yaw'?180:90),preset:'custom'});}else{const keys=Object.keys(lights),index=keys.indexOf(settings.direction);commit({direction:keys[(index+(['ArrowRight','ArrowDown'].includes(event.key)?1:5))%6]});}});
  function sync(){for(const [key,{node,output}]of fields){if(node.type==='checkbox')node.checked=Boolean(settings[key]);else node.value=String(settings[key]);setText(output,node.type==='checkbox'?'':String(settings[key]));}for(const [node,key,value]of choices)node.setAttribute('aria-pressed',String(settings[key]===value));
    let x,y,back=false;if(angle){const yaw=settings.yaw*Math.PI/180,pitch=settings.pitch*Math.PI/180;x=120+Math.sin(yaw)*Math.cos(pitch)*80;y=120-Math.sin(pitch)*80+Math.cos(yaw)*Math.cos(pitch)*22;back=Math.cos(yaw)<0;}else{[x,y]=lights[settings.direction].point;back=settings.direction==='back';}
    marker.setAttribute('transform',`translate(${x} ${y})`);marker.setAttribute('opacity',back?'.65':'1');const spread=angle?12:clamp(settings.cone/4,2,42);cone.setAttribute('d',`M${x} ${y} L${120-spread} 145 L${120+spread} 145 Z`);cone.setAttribute('fill',angle?'#7b8cff':settings.color);cone.setAttribute('opacity',angle?'.22':String(.08+settings.intensity*.06));cone.setAttribute('stroke-dasharray',back?'4 4':'none');visual.setAttribute('data-view',angle?'camera':settings.view);
    setText(status,angle?msg("ui.orbit_value0_pitch_value1_value2_value3",{value0:settings.yaw,value1:settings.pitch,value2:settings.zoom,value3:settings.include_instructions?'':msg("ui.angle_instructions_excluded_from_prompt")}):msg("ui.value0_key_light_value1_value2_cone_value3",{value0:lights[settings.direction].name,value1:Math.round(settings.intensity*100),value2:settings.cone,value3:settings.rim?msg("ui.rim_light_enabled"):''}));
  }
  sync();return {sync,dispose(){drag=null;root.remove();}};
}
