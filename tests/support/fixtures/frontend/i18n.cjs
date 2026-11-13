// Controlled DOM evidence only; no browser or rendering claim.
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
const {pathToFileURL}=require('node:url');
class TextNode {constructor(value,doc){this.nodeValue=value;this.ownerDocument=doc;this.parentElement=null;}get textContent(){return this.nodeValue;}set textContent(value){this.nodeValue=value;}}
class Element {constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.attributes={};this.value='';this.selectionStart=0;this.selectionEnd=0;this.listeners={};}replaceChildren(...values){for(const c of this.children)c.parentElement=null;this.children=[];this.append(...values);}append(...values){for(const c of values){c.parentElement=this;this.children.push(c);}}setAttribute(k,v){this.attributes[k]=String(v);}removeAttribute(k){delete this.attributes[k];}getAttribute(k){return this.attributes[k];}addEventListener(k,fn){this.listeners[k]=fn;}get textContent(){return this.children.map(x=>x.nodeValue??x.textContent).join('');}set textContent(s){this.replaceChildren(this.ownerDocument.createTextNode(String(s)));}}
const doc={createElement:tag=>new Element(tag,doc),createTextNode:s=>new TextNode(s,doc)};doc.documentElement=new Element('html',doc);globalThis.document=doc;
const stored=new Map([['vsc.ui.locale.v1','zh']]);globalThis.localStorage={getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)};
const url=pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/i18n.js')).href;
const i=await import(url);assert.equal(i.getLocale(),'zh-cn');assert.equal(i.LOCALES.length,27);
const label=doc.createElement('label'),input=doc.createElement('textarea');input.value='保存 中文剧本 <b>不是HTML</b>';input.selectionStart=3;input.selectionEnd=8;i.setText(label,i.msg('common.save'));const text=label.children[0];label.append(input);
const pending={idempotencyKey:'fixed-key',draft:{prompt:input.value},dirty:true};const before=JSON.stringify(pending);let changes=0;input.addEventListener('input',()=>changes++);
const userNode=doc.createElement('div');i.setText(userNode,'保存');const placeholder=doc.createElement('input');i.bindAttribute(placeholder,'placeholder',i.msg('common.name'));
for(const locale of i.LOCALES){i.setLocale(locale.code);assert.equal(i.getLocale(),locale.code);assert.equal(label.children[0],text);assert.equal(label.children[1],input);assert.equal(input.value,pending.draft.prompt);assert.equal(input.selectionStart,3);assert.equal(input.selectionEnd,8);assert.equal(userNode.textContent,'保存');assert.ok(text.nodeValue.length>0);assert.ok(i.messageInfo(i.msg('common.save')).language);assert.ok(i.fallbackNotice());}
assert.equal(changes,0);assert.equal(JSON.stringify(pending),before);
i.setLocale('en');assert.equal(label.children[0].nodeValue,'Save');assert.equal(placeholder.getAttribute('placeholder'),'Name');i.setText(label,'用户固定内容');i.setLocale('ja');assert.equal(label.textContent,'用户固定内容');
const fallback=doc.createElement('p');i.setText(fallback,i.msg('auth.login_title'));assert.equal(fallback.getAttribute('data-i18n-fallback'),'en');assert.equal(fallback.textContent,'Sign in to VSC');
assert.throws(()=>i.bindAttribute(input,'value',i.msg('common.save')));assert.throws(()=>JSON.stringify({prompt:i.msg('common.save')}));assert.throws(()=>i.msg('unknown.key'));
const op=i.option('image_to_video',i.msg('nav.video'));i.setLocale('en');assert.equal(op.value,'image_to_video');assert.equal(op.textContent,'Video');
i.setLocale('zh-tw');assert.equal(stored.get('vsc.ui.locale.v1'),'zh-tw');const restored=await import(url+'?reload=1');assert.equal(restored.getLocale(),'zh-tw');
console.log(JSON.stringify({passed:true,locales:27,preserved:['input node','selection','draft','dirty','pending key','user text','option value'],input_events:changes}));

// Exercise the actual account preference consumer without rebuilding any form.
const {createAccessControl}=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/access-control.js')));
globalThis.window={addEventListener(){}};
const profileWrites=[];let failReceipt=true;
const controller=createAccessControl(doc.createElement('main'),{session:()=>({actor:'member:fixed',csrf:'csrf'}),api:async(url,options)=>{
 if(url==='/api/v1/access')return {identity:{actor:'member:fixed',display_name:'服务器姓名',preferences:{language:'zh',compact:true}},access_revision:7};
 assert.equal(url,'/api/v1/access/commands/profile');const body=JSON.parse(options.body);profileWrites.push(body);if(failReceipt)throw new Error('lost receipt');return {access_revision:8};
}});
i.setLocale('ja');await assert.rejects(controller.saveLanguage('ja'),/lost receipt/);assert.equal(i.getLocale(),'ja');
assert.deepEqual(profileWrites[0].payload,{display_name:'服务器姓名',preferences:{language:'ja',compact:true}});
failReceipt=false;await controller.saveLanguage('ja');assert.equal(profileWrites[1].idempotency_key,profileWrites[0].idempotency_key);assert.equal(profileWrites[1].expected_revision,7);assert.equal(input.value,pending.draft.prompt);assert.equal(JSON.stringify(pending),before);
// Composite labels retain nested messages while literal user strings stay opaque.
const composite=doc.createElement('p');i.setText(composite,i.joinMessages([i.msg('common.save'),' · 用户标题']));i.setLocale('en');assert.equal(composite.textContent,'Save · 用户标题');i.setLocale('zh-cn');assert.equal(composite.textContent,'保存 · 用户标题');
assert.equal(i.translate(i.msg('ui.version_value0',{value0:i.msg('common.save')}),'en'),'Version Save');
// Real production components use the binding helper without firing edit handlers.
const {Document}=require('./panel_dom.cjs'),componentDocument=new Document('');componentDocument.createElementNS=(_,tag)=>componentDocument.createElement(tag);globalThis.document=componentDocument;
const {mountImageControls}=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/image-controls.js')));
i.setLocale('zh-cn');const controlRoot=componentDocument.createElement('main');componentDocument.body.append(controlRoot);const settings={preset:'custom',yaw:35,pitch:10,roll:0,zoom:1.5,include_instructions:true},settingsBefore=JSON.stringify(settings);let modelChanges=0;
mountImageControls(controlRoot,{tool:'angle',settings,defaults:{...settings},onChange:()=>modelChanges++});
const yaw=controlRoot.querySelectorAll('input').find(n=>n.getAttribute('aria-label')==='水平环绕（°）');const valueBefore=yaw.value;
i.setLocale('en');assert.equal(yaw.getAttribute('aria-label'),'Horizontal orbit (°)');assert.equal(yaw.value,valueBefore);assert.equal(JSON.stringify(settings),settingsBefore);assert.equal(modelChanges,0);
i.setLocale('ja');assert.equal(yaw.value,valueBefore);i.setLocale('zh-cn');assert.equal(yaw.getAttribute('aria-label'),'水平环绕（°）');assert.equal(modelChanges,0);
const {createProductionPlatform}=await import(pathToFileURL(path.resolve(__dirname,'../../../../src/vsc/interfaces/web/static/production-platform.js')));
const home=componentDocument.createElement('main');componentDocument.body.append(home);let calls=0;
const authorizedProject={id:'project-fixed',name:'原始中文项目',owner_kind:'personal',owner_name:'xuyun',owner_actor:'xuyun',created_by:'creator:original',access_capabilities:['read']};
const platform=createProductionPlatform(home,{projects:()=>[authorizedProject],api:async url=>{calls++;assert.equal(url,'/api/v1/discovery');return {recent:[{href:'/?page=canvas',project_id:authorizedProject.id,kind:'canvas',kind_label:'画布',title:'用户保存',project_name:authorizedProject.name,created_at:new Date().toISOString()},{href:'/?page=canvas',project_id:'project-outside',kind:'canvas',kind_label:'画布',title:'不可访问的创作',project_name:'其他项目',created_at:new Date().toISOString()}],skills:[],tutorials:[],templates:[],projects:[]};},session:()=>({actor:'member:fixed',csrf:'fixed'}),notice:()=>{}});
await platform.load({page:'home'});const heading=home.querySelector('h1'),headingText=heading.textContent;
i.setLocale('en');assert.notEqual(heading.textContent,headingText);assert.equal(home.querySelector('h1'),heading);assert.ok(home.textContent.includes('用户保存'));assert.ok(home.textContent.includes('原始中文项目'));assert.ok(!home.textContent.includes('不可访问的创作'));assert.equal(calls,1);
i.setLocale('zh-cn');assert.equal(heading.textContent,headingText);assert.ok(home.textContent.includes('用户保存'));assert.ok(home.textContent.includes('原始中文项目'));assert.ok(!home.textContent.includes('不可访问的创作'));assert.equal(calls,1);assert.deepEqual(authorizedProject,{id:'project-fixed',name:'原始中文项目',owner_kind:'personal',owner_name:'xuyun',owner_actor:'xuyun',created_by:'creator:original',access_capabilities:['read']});
console.log('i18n bindings PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
