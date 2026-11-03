// Controlled DOM test of the real component; no browser, rendering or CDP.
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {Document}=require('./panel_dom.cjs');
(async()=>{
  const document=new Document('');document.createElementNS=(_,tag)=>document.createElement(tag);global.document=document;
  const {mountImageControls}=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/image-controls.js')));
  const host=document.createElement('main');document.body.append(host);let alive=true,changes=0;
  const defaults={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true},settings={...defaults};
  const component=mountImageControls(host,{tool:'angle',settings,defaults,onChange:value=>{assert.equal(value,settings);changes++;},isCurrent:()=>alive});
  const label=(tag,name)=>host.querySelectorAll(tag).find(node=>node.getAttribute('aria-label')===name);
  const button=name=>host.querySelectorAll('button').find(node=>node.textContent===name);
  const yaw=label('input','水平环绕（°）');yaw.value='45';await yaw.dispatch('input');assert.equal(settings.yaw,45);
  await button('↑ 向上15°').click();assert.equal(settings.pitch,15);
  await button('背面视角').click();assert.equal(settings.yaw,180);assert.equal(yaw.value,'180');assert.equal(settings.preset,'back');
  const orbit=host.querySelector('svg');orbit.getBoundingClientRect=()=>({left:0,top:0,width:240,height:240});
  await orbit.dispatch('pointerdown',{pointerId:1,clientX:120,clientY:120});await orbit.dispatch('pointermove',{pointerId:1,clientX:0,clientY:60});await orbit.dispatch('pointerup',{pointerId:1});assert.equal(settings.yaw,0);assert.equal(settings.pitch,45);assert.equal(settings.preset,'custom');
  await orbit.dispatch('keydown',{key:'ArrowLeft'});assert.equal(settings.yaw,-15);
  const include=label('input','把角度说明加入模型提示词');include.checked=false;await include.dispatch('input');assert.equal(settings.include_instructions,false);
  const copy=JSON.parse(JSON.stringify(settings));component.dispose();mountImageControls(host,{tool:'angle',settings:copy,defaults,onChange:()=>changes++,isCurrent:()=>alive});assert.equal(label('input','水平环绕（°）').value,'-15');
  await button('重置参数').click();assert.deepEqual(copy,defaults);
  alive=false;const count=changes;await button('背面视角').click();assert.equal(changes,count);assert.deepEqual(copy,defaults);
  host.replaceChildren();alive=true;const lightDefaults={view:'front',direction:'front',intensity:1,color:'#ffffff',cone:45,rim:false},light={...lightDefaults};mountImageControls(host,{tool:'lighting',settings:light,defaults:lightDefaults,onChange:value=>{assert.equal(value,light);changes++;},isCurrent:()=>alive});
  const sphere=host.querySelector('svg');sphere.getBoundingClientRect=()=>({left:0,top:0,width:240,height:240});await sphere.dispatch('pointerdown',{pointerId:2,clientX:200,clientY:120});assert.equal(light.direction,'right');await sphere.dispatch('pointermove',{pointerId:2,clientX:120,clientY:35});assert.equal(light.direction,'top');await sphere.dispatch('pointercancel');
  await button('后方').click();assert.equal(light.direction,'back');assert.equal(button('后方').getAttribute('aria-pressed'),'true');await button('透视').click();assert.equal(light.view,'perspective');
  for(const [name,value,key]of [['光源亮度','2.5','intensity'],['光源颜色','#ff0033','color'],['光锥角度（°）','90','cone']]){const node=label('input',name);node.value=value;await node.dispatch('input');assert.equal(light[key],key==='color'?value:Number(value));}
  const rim=label('input','开启轮廓光');rim.checked=true;await rim.dispatch('input');assert.equal(light.rim,true);await button('重置参数').click();assert.deepEqual(light,lightDefaults);
  host.replaceChildren();const canvasAngle={...defaults},promptState={promptEnabled:false,prompt:''};let submitted=0;
  mountImageControls(host,{tool:'angle',settings:canvasAngle,defaults,onChange:()=>{},canvas:true,promptState,onSubmit:()=>submitted++});
  await button('鱼眼视角').click();assert.equal(promptState.promptEnabled,true);assert.ok(promptState.prompt);assert.equal(label('textarea','补充提示词').hidden,false);
  for(const [name,yaw,pitch,zoom] of [['鱼眼视角',0,30,2],['倾斜视角',45,-30,1],['正面俯拍',0,60,1],['正面仰拍',0,-30,1],['全景俯拍',45,30,.5],['背面视角',180,0,1]]){await button(name).click();assert.deepEqual([canvasAngle.yaw,canvasAngle.pitch,canvasAngle.zoom],[yaw,pitch,zoom]);}assert.equal(promptState.promptEnabled,false);
  const orbitInput=label('input','水平环绕（°）'),zoomInput=label('input','景别缩放');assert.equal(orbitInput.min,'0');assert.equal(orbitInput.max,'315');orbitInput.value='270';await orbitInput.dispatch('input');assert.equal(canvasAngle.yaw,-90);
  zoomInput.value='2';await zoomInput.dispatch('input');assert.equal(canvasAngle.zoom,2);assert.equal(canvasAngle.include_instructions,true);
  const promptSwitch=label('input','提示词'),extra=label('textarea','补充提示词');assert.equal(extra.hidden,true);promptSwitch.checked=true;await promptSwitch.dispatch('change');extra.value='保持服装';await extra.dispatch('input');assert.equal(promptState.prompt,'保持服装');assert.equal(promptState.promptEnabled,true);assert.equal(extra.hidden,false);
  const go=label('button','继续生成');await go.click();assert.equal(submitted,1);
  host.replaceChildren();const canvasLight={...lightDefaults,view:'perspective',intensity:.5};mountImageControls(host,{tool:'lighting',settings:canvasLight,defaults:{...canvasLight},onChange:()=>{},canvas:true,onSubmit:()=>{}});const intensity=label('input','光源亮度');assert.equal(intensity.max,'4');assert.equal(intensity.step,'1');assert.equal(intensity.value,'2');assert.equal(button('透视').getAttribute('aria-pressed'),'true');for(const [index,level] of [.1,.25,.5,.75,1].entries()){intensity.value=String(index);await intensity.dispatch('input');assert.equal(canvasLight.intensity,level);}
  console.log('image controls PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
