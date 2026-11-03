import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';

// Small DOM fixture; the production ES module and event handlers remain real.
class Element {
 constructor(tag,text=''){this.tagName=tag.toUpperCase();this._text=text;this.children=[];this.attrs={};this.listeners={};this.value='';this.style={removeProperty(k){delete this[k];}};this.offsetWidth=190;this.offsetHeight=250;this.clientWidth=1200;this.clientHeight=800;this.scrollLeft=0;this.scrollTop=0;this.dataset={};this.parentElement=null;this.className='';this.classList={add:(...v)=>{this.className=[...new Set([...this.className.split(' '),...v])].filter(Boolean).join(' ');},contains:v=>this.className.split(' ').includes(v),remove:(...v)=>{this.className=this.className.split(' ').filter(x=>!v.includes(x)).join(' ')}};}
 set textContent(v){this._text=v;this.children=[];} get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 append(...nodes){for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
 prepend(...nodes){for(const node of nodes.reverse()){node.remove();node.parentElement=this;this.children.unshift(node);}}
 remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;}}
 replaceChildren(...nodes){for(const c of [...this.children])c.remove();this._text='';this.append(...nodes);}
 insertBefore(node,before){node.remove();node.parentElement=this;const i=this.children.indexOf(before);this.children.splice(i<0?this.children.length:i,0,node);}
 removeAttribute(k){delete this.attrs[k];}
 setAttribute(k,v){this.attrs[k]=v;} getAttribute(k){return this.attrs[k]??null;}
 matches(selector){if(selector[0]==='.')return this.classList.contains(selector.slice(1));if(selector[0]==='['){const match=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return match&&(match[2]==null?this.attrs[match[1]]!=null:this.attrs[match[1]]===match[2]);}return this.tagName===selector.toUpperCase();}
 querySelectorAll(selector){const values=this.children.flatMap(c=>[c,...c.querySelectorAll('*')]);if(selector==='*')return values;return values.filter(c=>selector.split(',').some(x=>c.matches(x.trim())));}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}closest(selector){for(let node=this;node;node=node.parentElement)if(selector.split(',').some(part=>node.matches(part.trim())))return node;return null;}
 getBoundingClientRect(){return {left:0,top:0,width:1200,height:800};}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 get options(){return this.children.filter(x=>x.tagName==='OPTION');}
 async fire(type,properties={}){const event={target:this,preventDefault(){},...properties};if(this['on'+type])await this['on'+type](event);for(const f of this.listeners[type]||[])await f(event);if(['input','change'].includes(type)&&this.parentElement)await this.parentElement.fire(type,{...properties,target:event.target});}
 focus(){this.ownerDocument.activeElement=this;}showModal(){this.open=true;}close(){this.open=false;return this.fire('close');}
 get selectedOptions(){return this.options.filter(node=>node.selected||node.value===this.value&&!this.multiple);}
}
async function fixture({nodes=[],viewport={x:0,y:0,zoom:1},runOptions=null}={}) {
  const document={createElement:t=>{const n=new Element(t);n.ownerDocument=document;if(t==='canvas')n.getContext=()=>({drawImage(){},getImageData(){return {data:new Uint8ClampedArray(32)};}});return n;},createElementNS:(ns,t)=>{const n=document.createElement(t);n.namespaceURI=ns;return n;},createTextNode:text=>{const n=new Element('#text',text);n.ownerDocument=document;return n;},documentElement:{}};
  const images=[];class FakeImage{constructor(){images.push(this);}}
  const store=new Map(),sessionStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
  const window={addEventListener(){},removeEventListener(){}},location={search:''};
  const module=await loadModule('creative-canvas.js',{document,window,location,sessionStorage,crypto,console,Image:FakeImage,requestAnimationFrame:()=>1,setTimeout:()=>0,clearTimeout:()=>{}});
  const root=document.createElement('main');
  const ctx={session:()=>({actor:'test',csrf:'test',revision:1}),setRevision(){},opened(){},api:async(path)=>path.endsWith('/creative-canvases/c1')?{revision:1,canvas_revision:1,title:'Test',episode_id:null,document:{viewport,nodes,edges:[]},jobs:{},runs:[],execution_steps:[]}:path.endsWith('/creative-canvas-run-options')&&runOptions?runOptions:{items:[],revision:1}};
  const canvas=module.createCreativeCanvasPanel(ctx);await canvas.load(root,'p1',null,'c1');
  return {root,canvas,store,images,stage:root.querySelector('.cc-stage'),menu:root.querySelector('.cc-create-menu')};
}
function addImage(menu){const action=menu.querySelectorAll('button').find(b=>b.textContent==='添加图片');assert.ok(action);return action.fire('click');}
function savedNode(store){return JSON.parse(store.get('vsc-creative-canvas:p1:c1')).document.nodes.at(-1);}

test('double click creates a node at the chosen point and preserves coordinates in the draft',async()=>{
  const a=await fixture();await a.stage.fire('dblclick',{clientX:510,clientY:280});
  assert.equal(a.menu.hidden,false);assert.equal(a.menu.style.left,'510px');assert.equal(a.menu.style.top,'280px');
  await addImage(a.menu);const node=a.root.querySelector('.cc-node');assert.ok(node);assert.deepEqual([node.style.left,node.style.top],['510px','280px']);
  assert.deepEqual([savedNode(a.store).x,savedNode(a.store).y],[430,232]);assert.equal(a.menu.hidden,true);a.canvas.suspend();
});

test('right click maps viewport coordinates through pan and zoom into the saved document',async()=>{
  const a=await fixture({viewport:{x:120,y:80,zoom:2}});let prevented=false;
  await a.stage.fire('contextmenu',{clientX:500,clientY:300,preventDefault(){prevented=true;}});assert.ok(prevented);
  await addImage(a.menu);const node=a.root.querySelector('.cc-node');assert.deepEqual([node.style.left,node.style.top],['310px','190px']);
  assert.deepEqual([savedNode(a.store).x,savedNode(a.store).y],[230,142]);a.canvas.suspend();
});

test('image clicks and keyboard selection update the selected node without changing its document',async()=>{
  const node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});
  const a=await fixture({nodes:[node('first',100),node('second',400)]});
  let cards=a.root.querySelectorAll('.cc-node');assert.equal(cards.length,2);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);
  await cards[0].fire('click',{target:cards[0].querySelector('img')});cards=a.root.querySelectorAll('.cc-node');
  assert.ok(cards[0].classList.contains('selected'));assert.equal(a.root.querySelector('.cc-inspector').hidden,true);await cards[0].querySelector('.cc-node-head').fire('click');cards=a.root.querySelectorAll('.cc-node');assert.equal(a.root.querySelector('.cc-inspector').hidden,false);
  await cards[1].fire('click',{target:cards[1].querySelector('img'),shiftKey:true});cards=a.root.querySelectorAll('.cc-node');
  assert.ok(cards[0].classList.contains('selected'));assert.ok(cards[1].classList.contains('selected'));
  await cards[1].fire('keydown',{key:'Enter'});cards=a.root.querySelectorAll('.cc-node');
  assert.equal(cards[0].classList.contains('selected'),false);assert.ok(cards[1].classList.contains('selected'));
  assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});

test('selected image exposes preview and original download without editing canvas data',async()=>{
 const node={id:'image1',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const a=await fixture({nodes:[node],viewport:{x:0,y:0,zoom:.5}});let card=a.root.querySelector('.cc-node');assert.equal(a.root.querySelector('.cc-image-node-tools'),null);
 const image=card.querySelector('img');image.naturalWidth=3840;image.naturalHeight=2160;await image.fire('load');assert.equal(card.querySelector('.cc-node-resolution').textContent,'3840 × 2160');assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);
 await card.fire('click',{target:card.querySelector('img')});card=a.root.querySelector('.cc-node');const toolbar=card.querySelector('.cc-image-node-tools');assert.ok(toolbar);assert.equal(toolbar.style.transform,'scale(2) translateX(-50%)');
 const link=toolbar.querySelector('a');assert.equal(link.href,'/api/v1/projects/p1/media/media1/content?download=true');
 await card.fire('click',{target:link});assert.equal(a.root.querySelector('.cc-node'),card);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);
 await toolbar.querySelectorAll('button').find(b=>b.textContent==='预览').fire('click');const dialog=a.root.querySelector('.cc-image-preview');assert.ok(dialog.open);assert.equal(dialog.querySelector('img').src,'/api/v1/projects/p1/media/media1/content');
 await dialog.querySelector('button').fire('click');assert.equal(a.root.querySelector('.cc-image-preview'),null);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});

test('panorama viewer opens the selected source and closes without changing the canvas',async()=>{
 const node={id:'image1',type:'image',title:'全景参考',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};const a=await fixture({nodes:[node]});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await a.root.querySelectorAll('button').find(b=>b.textContent==='进入全景').fire('click');let dialog=a.root.querySelector('.cc-panorama-preview');assert.ok(dialog.open);assert.equal(a.images[0].src,'/api/v1/projects/p1/media/media1/content');a.images[0].naturalWidth=4;a.images[0].naturalHeight=2;a.images[0].onload();assert.ok(dialog.querySelector('canvas'));assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);
 await dialog.querySelector('button').fire('click');assert.equal(a.root.querySelector('.cc-panorama-preview'),null);await a.root.querySelectorAll('button').find(b=>b.textContent==='进入全景').fire('click');dialog=a.root.querySelector('.cc-panorama-preview');a.images[1].naturalWidth=16;a.images[1].naturalHeight=9;a.images[1].onload();assert.match(dialog.querySelector('p').textContent,/2:1/);await dialog.querySelector('button').fire('click');a.canvas.suspend();
});

test('closing an image tool leaves its source and document untouched',async()=>{
 const node={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const angle={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true};
 const a=await fixture({nodes:[node],runOptions:{revision:1,nodes:[],models:[],image_tools:{angle}}});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await a.root.querySelector('.cc-node-head').fire('click');assert.equal(a.root.querySelector('.cc-inspector').hidden,false);await a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');const panel=a.root.querySelector('.cc-image-tool-panel');assert.ok(panel);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);
 await panel.querySelectorAll('button').find(b=>b.attrs['aria-label']==='关闭').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,false);assert.equal(a.root.querySelectorAll('.cc-node').length,1);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});

test('switching images through the minimap clears image-specific panels',async()=>{
 const node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});const angle={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true};
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:{revision:1,nodes:[],models:[],image_tools:{angle}}});let cards=a.root.querySelectorAll('.cc-node');await cards[0].querySelector('.cc-node-head').fire('click');assert.equal(a.root.querySelector('.cc-inspector').hidden,false);
 await a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');assert.ok(a.root.querySelector('.cc-image-tool-panel'));
 await a.root.querySelector('.cc-minimap').querySelectorAll('button').find(b=>b.title==='second').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);
 await a.root.querySelector('.cc-minimap').querySelectorAll('button').find(b=>b.title==='first').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});

test('canvas image tool fixes source, settings and extra prompt before opening generation',async()=>{
 const node={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const angle={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true},lighting={view:'perspective',direction:'front',intensity:.5,color:'#ffffff',cone:45,rim:false};
 const a=await fixture({nodes:[node],runOptions:{revision:1,nodes:[],models:[{id:'model1',enabled:true,modality:'image',model_key:'编辑模型',model_version:'1',capabilities:{purposes:['image_edit']}}],image_tools:{angle,lighting}}});
 let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');
 const panel=a.root.querySelector('.cc-image-tool-panel');assert.ok(panel);const inputs=panel.querySelectorAll('input');
 const yaw=inputs.find(n=>n.attrs['aria-label']==='水平环绕（°）');assert.equal(yaw.min,'0');assert.equal(yaw.max,'315');yaw.value='315';await yaw.fire('input');
 const prompt=inputs.find(n=>n.attrs['aria-label']==='提示词');assert.equal(prompt.checked,false);prompt.checked=true;await prompt.fire('change');
 const extra=panel.querySelector('textarea');extra.value='保持服装';await extra.fire('input');
 await panel.querySelectorAll('button').find(b=>b.attrs['aria-label']==='继续生成').fire('click');
 const doc=JSON.parse(a.store.get('vsc-creative-canvas:p1:c1')).document,target=doc.nodes.find(n=>n.id!=='source');
 assert.equal(target.params.vsc_image_tool,'angle');assert.equal(JSON.parse(target.params.vsc_image_tool_settings).yaw,-45);assert.equal(JSON.parse(target.params.vsc_image_tool_settings).include_instructions,true);assert.equal(target.text,'保持服装');
 assert.deepEqual(doc.edges.map(e=>[e.source,e.target,e.port]),[['source',target.id,'reference']]);assert.ok(a.root.querySelector('.cc-run-form'));a.canvas.suspend();
});

test('image generation presets fix the original reference before opening generation',async()=>{
 const node={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const image_tools={three_view:{layout:'front_side_back'},headshot:{framing:'head_and_shoulders'},face_views:{layout:'front_three_quarter_side'}};
 for(const [tool,label] of [['three_view','角色三视图'],['headshot','生成大头照'],['face_views','角色脸部三视图']]){
  const a=await fixture({nodes:[node],runOptions:{revision:1,nodes:[],models:[{id:'model1',enabled:true,modality:'image',model_key:'编辑模型',model_version:'1',capabilities:{purposes:['image_edit']}}],image_tools}});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
  const menu=a.root.querySelector('.cc-image-generate-menu--presets');assert.ok(menu);assert.equal(menu.querySelectorAll('button').find(b=>b.textContent==='剧情推进四格').disabled,true);
  await menu.querySelectorAll('button').find(b=>b.textContent===label).fire('click');const doc=JSON.parse(a.store.get('vsc-creative-canvas:p1:c1')).document,target=doc.nodes.find(n=>n.id!=='source');
  assert.equal(target.params.vsc_image_tool,tool);assert.deepEqual(JSON.parse(target.params.vsc_image_tool_settings),image_tools[tool]);assert.deepEqual(doc.edges.map(e=>[e.source,e.target,e.port]),[['source',target.id,'reference']]);assert.ok(a.root.querySelector('.cc-run-form'));a.canvas.suspend();
 }
});

test('late image tool options do not reopen the panel for a different selection',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:waiting});let cards=a.root.querySelectorAll('.cc-node');await cards[0].fire('click',{target:cards[0].querySelector('img')});
 const opening=a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');cards=a.root.querySelectorAll('.cc-node');await cards[1].fire('click',{target:cards[1].querySelector('img')});
 resolve({revision:1,nodes:[],models:[],image_tools:{angle:{preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true}}});await opening;
 assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});

test('late image preset options do not create a node for a different selection',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:waiting});let cards=a.root.querySelectorAll('.cc-node');await cards[0].fire('click',{target:cards[0].querySelector('img')});
 const opening=a.root.querySelectorAll('button').find(b=>b.textContent==='角色三视图').fire('click');cards=a.root.querySelectorAll('.cc-node');await cards[1].fire('click',{target:cards[1].querySelector('img')});
 resolve({revision:1,nodes:[],models:[],image_tools:{three_view:{layout:'front_side_back'}}});await opening;
 assert.equal(a.root.querySelectorAll('.cc-node').length,2);assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});
