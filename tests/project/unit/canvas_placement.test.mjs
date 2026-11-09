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
 querySelectorAll(selector){if(selector.startsWith(':scope > '))return this.children.filter(c=>c.matches(selector.slice(9)));const values=this.children.flatMap(c=>[c,...c.querySelectorAll('*')]);if(selector==='*')return values;return values.filter(c=>selector.split(',').some(x=>c.matches(x.trim())));}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}closest(selector){for(let node=this;node;node=node.parentElement)if(selector.split(',').some(part=>node.matches(part.trim())))return node;return null;}
 getBoundingClientRect(){return {left:0,top:0,width:1200,height:800};}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 get options(){return this.children.filter(x=>x.tagName==='OPTION');}
 get isConnected(){return this.parentElement!==null;}
 async fire(type,properties={}){const event={target:this,preventDefault(){},...properties};if(this['on'+type])await this['on'+type](event);for(const f of this.listeners[type]||[])await f(event);if(['input','change'].includes(type)&&this.parentElement)await this.parentElement.fire(type,{...properties,target:event.target});}
 focus(){this.ownerDocument.activeElement=this;}scrollIntoView(){}showModal(){this.open=true;}close(){this.open=false;return this.fire('close');}
 get selectedOptions(){return this.options.filter(node=>node.selected||node.value===this.value&&!this.multiple);}
}
async function fixture({nodes=[],viewport={x:0,y:0,zoom:1},runOptions=null,apiOverride=null,projects=null,denyProjectStorage=false,store=new Map(),actor='test',search=''}={}) {
  const document={createElement:t=>{const n=new Element(t);n.ownerDocument=document;if(t==='canvas')n.getContext=()=>({drawImage(){},getImageData(){return {data:new Uint8ClampedArray(32)};}});return n;},createElementNS:(ns,t)=>{const n=document.createElement(t);n.namespaceURI=ns;return n;},createTextNode:text=>{const n=new Element('#text',text);n.ownerDocument=document;return n;},documentElement:{}};
  const images=[];class FakeImage{constructor(){images.push(this);}}
  const sessionStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>{if(denyProjectStorage&&k.startsWith('vsc-canvas-project-node:'))throw Error('storage disabled');store.set(k,v);},removeItem:k=>store.delete(k)};
  const listeners=new Map(),window={addEventListener(type,fn){(listeners.get(type)||listeners.set(type,new Set()).get(type)).add(fn);},removeEventListener(type,fn){listeners.get(type)?.delete(fn);},fire(type,event={}){for(const fn of [...listeners.get(type)||[]])fn(event);}},location={search};
  const module=await loadModule('creative-canvas.js',{document,window,location,sessionStorage,crypto,console,Image:FakeImage,requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},setTimeout:()=>0,clearTimeout:()=>{}});
  const root=document.createElement('main');
  const session={actor,csrf:'test',revision:1};
  const ctx={session:()=>session,setRevision(){},opened(){},...(projects?{projects:()=>projects}:{}),api:async(path,options)=>{if(apiOverride){const value=await apiOverride(path,options);if(value!==undefined)return value;}return path.endsWith('/creative-canvases/c1')?{revision:1,canvas_revision:1,title:'Test',episode_id:null,document:{viewport,nodes,edges:[]},jobs:{},runs:[],execution_steps:[]}:path.endsWith('/creative-canvas-run-options')&&runOptions?runOptions:path.endsWith('/creative-canvas-agent-options')?{revision:1,host_available:true,skills:[{id:'image-generation',name:'Image',description:''}],models:[],nodes:[]}:{items:[],revision:1};}};
  const canvas=module.createCreativeCanvasPanel(ctx);await canvas.load(root,'p1',null,'c1');
  return {root,canvas,store,images,document,window,FakeImage,session,location,stage:root.querySelector('.cc-stage'),menu:root.querySelector('.cc-create-menu')};
}
const browserKey=(prefix,{actor='test',project='p1',canvas='c1',shared=false,episode=null,slot=null}={})=>prefix+':v2:'+JSON.stringify([actor,shared,project,canvas,canvas?null:episode,slot]);
const canvasDraftKey=(scope={})=>browserKey('vsc-creative-canvas',scope);
function addImage(menu){const action=menu.querySelectorAll('button').find(b=>b.textContent==='添加图片');assert.ok(action);return action.fire('click');}
function savedNode(store){return JSON.parse(store.get(canvasDraftKey())).document.nodes.at(-1);}
async function selectGrid(a,cells=[[1,1],[1,2],[2,1],[2,2]]){await a.root.querySelectorAll('button').find(b=>b.textContent==='4宫格（2×2）').fire('click');for(const [r,c]of cells)await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']===`宫格 ${r}行${c}列`).fire('click');}
function generateGrid(a){return a.root.querySelectorAll('button').find(b=>b.textContent==='生成图片').fire('click');}
async function openCrossProject(a){await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='项目资产').fire('click');const pick=a.root.querySelectorAll('select').find(n=>n.attrs['aria-label']==='资产项目');pick.value='p2';await pick.fire('change');}
const crossProjects=[{id:'p1',name:'当前项目'},{id:'p2',name:'来源项目'}];
const crossRow={id:'asset1',record_kind:'asset',asset_kind:'character',name:'角色',forms:[{form_key:'master',name:'默认',version_id:'form1',media_id:'source1'}]};
const fixedCrossNode={id:'cross1',type:'image',title:'角色',x:100,y:100,text:'',params:{},media_id:'target1',job_id:null,group:''};
const fixedCross={revision:2,canvas_revision:2,document:{viewport:{x:0,y:0,zoom:1},nodes:[fixedCrossNode],edges:[]}};

test('cross-project click preserves the original request and recovers after lost receipt',async()=>{
 const requests=[];const a=await fixture({projects:crossProjects,apiOverride:async(path,options)=>{
  if(path.includes('/asset-cards?'))return {revision:1,items:[crossRow],next_offset:null};
  if(path.endsWith('/project-media-node')){requests.push(JSON.parse(options.body));if(requests.length===1)throw Error('response lost');if(requests.length===2){const error=Error('身份已失效');error.status=403;throw error;}return {id:'c1',version_id:'version2',canvas_revision:2,revision:2,node_id:'cross1',media_id:'target1',byte_check:{checked:false,reason:'local_bytes_unavailable'}};}
  if(path.endsWith('/creative-canvases/c1?version=2'))return fixedCross;
 }});
 await openCrossProject(a);await a.root.querySelector('.cc-asset-send').fire('click');assert.equal(requests.length,1);assert.equal(requests[0].payload.source.form_version_id,'form1');assert.equal(requests[0].payload.source_project_id,'p2');
 await a.canvas.load(a.root,'p1',null,'c1');await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='项目资产').fire('click');await a.root.querySelectorAll('button').find(b=>b.textContent==='恢复原项目素材引用').fire('click');
 await new Promise(resolve=>setImmediate(resolve));const pending=JSON.parse(a.store.get('vsc-canvas-project-node:test:p1:c1'));assert.equal(pending.uncertain,true);assert.notEqual(pending.rejected,true);assert.equal(a.root.querySelectorAll('button').some(b=>b.textContent==='结束已拒绝的项目素材请求'),false);
 await a.root.querySelectorAll('button').find(b=>b.textContent==='恢复原项目素材引用').fire('click');assert.deepEqual(requests[1],requests[0]);assert.deepEqual(requests[2],requests[0]);assert.equal(a.root.querySelectorAll('.cc-node').length,1);assert.match(a.root.querySelector('.cc-status').textContent,/生成前需完成媒体检查/);assert.equal(a.store.has('vsc-canvas-project-node:test:p1:c1'),false);a.canvas.suspend();
});

test('a definite initial permission rejection can be ended and local draft saved',async()=>{
 let saved;const a=await fixture({projects:crossProjects,apiOverride:async(path,options)=>{
  if(path.includes('/asset-cards?'))return {revision:1,items:[crossRow],next_offset:null};
  if(path.endsWith('/project-media-node')){const error=Error('无权限');error.status=403;throw error;}
  if(path.endsWith('/creative-canvases/c1')&&options?.method==='PUT'){saved=JSON.parse(options.body);return {revision:2,canvas_revision:2};}
 }});
 await openCrossProject(a);await a.root.querySelector('.cc-asset-send').fire('click');await new Promise(resolve=>setImmediate(resolve));
 const pending=JSON.parse(a.store.get('vsc-canvas-project-node:test:p1:c1'));assert.equal(pending.rejected,true);await a.root.querySelectorAll('button').find(b=>b.textContent==='结束已拒绝的项目素材请求').fire('click');
 await a.stage.fire('dblclick',{clientX:510,clientY:280});await addImage(a.menu);await a.root.querySelector('.cc-save').fire('click');assert.equal(saved.payload.document.nodes.length,1);assert.equal(a.store.has('vsc-canvas-project-node:test:p1:c1'),false);a.canvas.suspend();
});

test('cross-project drop retains edits made while the original request runs',async()=>{
 let resolveRequest,request;const waiting=new Promise(resolve=>{resolveRequest=resolve;});
 const a=await fixture({projects:crossProjects,apiOverride:async(path,options)=>{
  if(path.includes('/asset-cards?'))return {revision:1,items:[crossRow],next_offset:null};
  if(path.endsWith('/project-media-node')){request=JSON.parse(options.body);return waiting;}
  if(path.endsWith('/creative-canvases/c1?version=2'))return fixedCross;
 }});
 await openCrossProject(a);const transfer={value:'',types:['application/x-vsc-canvas-asset'],setData(_type,value){this.value=value;},getData(){return this.value;}};
 await a.root.querySelector('.cc-asset-open').fire('dragstart',{dataTransfer:transfer});const pending=a.stage.fire('drop',{dataTransfer:transfer,clientX:300,clientY:180});
 await new Promise(resolve=>setImmediate(resolve));await a.stage.fire('dblclick',{clientX:510,clientY:280});await addImage(a.menu);resolveRequest({id:'c1',version_id:'version2',canvas_revision:2,revision:2,node_id:'cross1',media_id:'target1'});await pending;
 assert.equal(request.payload.x,220);assert.equal(request.payload.y,132);const saved=JSON.parse(a.store.get(canvasDraftKey())).document;assert.equal(saved.nodes.length,2);assert.ok(saved.nodes.some(n=>n.media_id==='target1'));assert.ok(saved.nodes.some(n=>n.media_id===null));a.canvas.suspend();
});

test('cross-project reference is not submitted if its recovery receipt cannot be stored',async()=>{
 let submitted=false;const a=await fixture({projects:crossProjects,denyProjectStorage:true,apiOverride:async path=>{if(path.includes('/asset-cards?'))return {revision:1,items:[crossRow],next_offset:null};if(path.endsWith('/project-media-node'))submitted=true;}});
 await openCrossProject(a);await a.root.querySelector('.cc-asset-send').fire('click');assert.equal(submitted,false);assert.match(a.root.querySelector('.cc-status').textContent,/无法保存原引用请求/);a.canvas.suspend();
});

test('cross-project blocking request sends fixed workflow provenance and excludes unavailable or unfixed items',async()=>{
 let request;const source={workflow_id:'flow1',version_id:'workflow1',episode_id:'episode1',unit_key:'unit1',media_id:'source1',spatial_export_id:null};
 const station={id:'blocking:key',record_kind:'blocking',asset_kind:'blocking',name:'站位',forms:[],preview:{media_id:'source1'},source};
 const unavailable={...station,id:'blocked',name:'不可用',preview:null};const legacy={...crossRow,id:'legacy',forms:[{form_key:'master',media_id:'source1',version_id:null}]};
 const a=await fixture({projects:crossProjects,apiOverride:async(path,options)=>{if(path.includes('/asset-cards?'))return {revision:1,items:[station,unavailable,legacy],next_offset:null};if(path.endsWith('/project-media-node')){request=JSON.parse(options.body);return {id:'c1',version_id:'version2',canvas_revision:2,revision:2,node_id:'cross1',media_id:'target1'};}if(path.endsWith('/creative-canvases/c1?version=2'))return fixedCross;}});
 await openCrossProject(a);const items=a.root.querySelectorAll('.cc-asset-item');assert.equal(items[1].querySelector('.cc-asset-send').disabled,true);assert.equal(items[2].querySelector('.cc-asset-send').disabled,true);await items[0].querySelector('.cc-asset-send').fire('click');
 assert.deepEqual(request.payload.source,{kind:'blocking',...source});a.canvas.suspend();
});

test('late cross-project receipt stays with its original canvas after switching',async()=>{
 let resolveRequest,reads=0;const waiting=new Promise(resolve=>{resolveRequest=resolve;});
 const a=await fixture({projects:crossProjects,apiOverride:async path=>{
  if(path.includes('/asset-cards?'))return {revision:1,items:[crossRow],next_offset:null};
  if(path.endsWith('/project-media-node'))return waiting;
  if(path.endsWith('/creative-canvases/c1?version=2')){reads++;return fixedCross;}
  if(path.endsWith('/creative-canvases/c2'))return {revision:1,canvas_revision:1,title:'另一个画布',episode_id:null,document:{viewport:{x:0,y:0,zoom:1},nodes:[],edges:[]},jobs:{},runs:[],execution_steps:[]};
 }});
 await openCrossProject(a);const pending=a.root.querySelector('.cc-asset-send').fire('click');await new Promise(resolve=>setImmediate(resolve));
 await a.canvas.load(a.root,'p1',null,'c2');resolveRequest({id:'c1',version_id:'version2',canvas_revision:2,revision:2,node_id:'cross1',media_id:'target1'});await pending;
 assert.equal(reads,0);assert.equal(a.root.querySelectorAll('.cc-node').length,0);assert.equal(JSON.parse(a.store.get('vsc-canvas-project-node:test:p1:c1')).result.node_id,'cross1');a.canvas.suspend();
});

test('canvas imports only an available fixed blocking media from its project',async()=>{
 let lastQuery;const a=await fixture({apiOverride:async path=>{if(path.includes('/asset-cards?')){lastQuery=new URL(path,'http://test').searchParams;return {revision:1,items:[{id:'projection-1',record_kind:'blocking',asset_kind:'blocking',name:'站位一',forms:[],preview:{media_id:'fixed-media'}},{id:'projection-2',record_kind:'blocking',asset_kind:'blocking',name:'站位二',forms:[],preview:null}],next_offset:null};}}});
 await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='项目资产').fire('click');
 assert.equal(lastQuery.get('include_blocking'),'true');const kind=a.root.querySelectorAll('select').find(n=>n.attrs['aria-label']==='资产类型');kind.value='blocking';await kind.fire('change');assert.equal(lastQuery.get('asset_kind'),'blocking');const items=a.root.querySelectorAll('.cc-asset-item');assert.equal(items.length,2);
 const send=items.map(item=>item.querySelector('.cc-asset-send'));assert.equal(send[1].disabled,true);await send[0].fire('click');
 assert.equal(savedNode(a.store).media_id,'fixed-media');assert.equal(savedNode(a.store).type,'image');a.canvas.suspend();
});

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
  assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('selected image exposes preview and original download without editing canvas data',async()=>{
 const node={id:'image1',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const a=await fixture({nodes:[node],viewport:{x:0,y:0,zoom:.5}});let card=a.root.querySelector('.cc-node');assert.equal(a.root.querySelector('.cc-image-node-tools'),null);
 const image=card.querySelector('img');image.naturalWidth=3840;image.naturalHeight=2160;await image.fire('load');assert.equal(card.querySelector('.cc-node-resolution').textContent,'3840 × 2160');assert.equal(a.store.has(canvasDraftKey()),false);
 await card.fire('click',{target:card.querySelector('img')});card=a.root.querySelector('.cc-node');const toolbar=card.querySelector('.cc-image-node-tools');assert.ok(toolbar);assert.equal(toolbar.style.transform,'scale(2) translateX(-50%)');
 const link=toolbar.querySelector('a');assert.equal(link.href,'/api/v1/projects/p1/media/media1/content?download=true');
 await card.fire('click',{target:link});assert.equal(a.root.querySelector('.cc-node'),card);assert.equal(a.store.has(canvasDraftKey()),false);
 await toolbar.querySelectorAll('button').find(b=>b.textContent==='预览').fire('click');const dialog=a.root.querySelector('.cc-image-preview');assert.ok(dialog.open);assert.equal(dialog.querySelector('img').src,'/api/v1/projects/p1/media/media1/content');
 await dialog.querySelector('button').fire('click');assert.equal(a.root.querySelector('.cc-image-preview'),null);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('panorama viewer opens inline for the selected image and closes without editing',async()=>{
 const node={id:'image1',type:'image',title:'全景参考',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};const a=await fixture({nodes:[node]});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await a.root.querySelectorAll('button').find(b=>b.textContent==='进入全景').fire('click');card=a.root.querySelector('.cc-node');const viewer=card.querySelector('.cc-panorama-viewer');assert.ok(viewer);assert.equal(a.images[0].src,'/api/v1/projects/p1/media/media1/content');a.images[0].naturalWidth=16;a.images[0].naturalHeight=9;a.images[0].onload();assert.ok(viewer.querySelector('canvas'));assert.doesNotMatch(viewer.querySelector('p').textContent,/2:1/);assert.equal(card.querySelector('.cc-node-resolution').textContent,'16 × 9');assert.equal(a.store.has(canvasDraftKey()),false);
 const late=a.images[0].onload;await card.querySelectorAll('button').find(b=>b.attrs['aria-label']==='退出全景预览').fire('click');assert.equal(a.root.querySelector('.cc-panorama-viewer'),null);assert.ok(a.root.querySelector('.cc-node').querySelector('img'));late();assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('classic panorama viewer still rejects a non-2:1 source',async()=>{
 const a=await fixture(),{mountPanorama}=await loadModule('panorama-viewer.js',{document:a.document,Image:a.FakeImage,requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{}}),host=a.document.createElement('div');
 const viewer=mountPanorama(host,'/flat.png',{isCurrent:()=>true});a.images[0].naturalWidth=16;a.images[0].naturalHeight=9;a.images[0].onload();assert.match(host.querySelector('p').textContent,/2:1/);viewer.dispose();a.canvas.suspend();
});

test('grid split retries the original receipt and places fixed outputs with their source edges',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const tiles=Array.from({length:4},(_,i)=>({id:'tile'+i,type:'image',title:'切图'+i,x:400,y:i*230,text:'',params:{},media_id:'tile-media'+i,job_id:null,group:''}));
 const edges=tiles.map((n,i)=>({id:'edge'+i,source:'source',target:n.id,port:'derived_from'})),requests=[];
 const a=await fixture({nodes:[source],apiOverride:async(path,options)=>{
  if(path.endsWith('/split-image')){requests.push(JSON.parse(options.body));if(requests.length===1)throw Error('连接中断');return {revision:2,canvas_revision:2,node_ids:tiles.map(n=>n.id),media_ids:tiles.map(n=>n.media_id)};}
  if(path.endsWith('?version=2'))return {revision:2,document:{viewport:{x:0,y:0,zoom:1},nodes:[source,...tiles],edges}};
 }});
 let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await selectGrid(a);await generateGrid(a);
 assert.equal(a.root.querySelectorAll('.cc-node').length,1);assert.ok(a.store.has('vsc-canvas-grid:test:p1:c1'));
 await generateGrid(a);
 assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);assert.equal(a.root.querySelectorAll('.cc-node').length,5);assert.equal(a.store.has('vsc-canvas-grid:test:p1:c1'),false);
 assert.equal(a.root.querySelector('.cc-connections').querySelectorAll('path').length,4);a.canvas.suspend();
});

test('grid split preserves edits made while the request is running',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const tiles=Array.from({length:4},(_,i)=>({id:'tile'+i,type:'image',title:'切图'+i,x:400,y:i*230,text:'',params:{},media_id:'tile-media'+i,job_id:null,group:''}));
 const edges=tiles.map((n,i)=>({id:'edge'+i,source:'source',target:n.id,port:'derived_from'}));let finish;
 const waiting=new Promise(resolve=>{finish=resolve;});
 const a=await fixture({nodes:[source],apiOverride:async(path)=>{if(path.endsWith('/split-image')){await waiting;return {revision:2,canvas_revision:2,node_ids:tiles.map(n=>n.id),media_ids:tiles.map(n=>n.media_id)};}if(path.endsWith('?version=2'))return {revision:2,document:{viewport:{x:0,y:0,zoom:1},nodes:[source,...tiles],edges}};}});
 const card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await selectGrid(a);const pending=generateGrid(a);await new Promise(resolve=>setImmediate(resolve));
 await a.stage.fire('dblclick',{clientX:510,clientY:280});await addImage(a.menu);finish();await pending;
 assert.equal(a.root.querySelectorAll('.cc-node').length,6);const draft=JSON.parse(a.store.get(canvasDraftKey()));assert.equal(draft.dirty,true);assert.equal(draft.document.nodes.length,6);assert.equal(draft.document.edges.length,4);a.canvas.suspend();
});

test('grid receipt lost after server save is recovered after reopening without duplicate nodes',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const tiles=Array.from({length:4},(_,i)=>({id:'tile'+i,type:'image',title:'切图'+i,x:400,y:i*230,text:'',params:{},media_id:'tile-media'+i,job_id:null,group:''}));
 const edges=tiles.map((n,i)=>({id:'edge'+i,source:'source',target:n.id,port:'derived_from'}));let saved=false;const requests=[];
 const fixed={revision:2,canvas_revision:2,title:'Test',episode_id:null,document:{viewport:{x:0,y:0,zoom:1},nodes:[source,...tiles],edges},jobs:{},runs:[],execution_steps:[]};
 const a=await fixture({nodes:[source],apiOverride:async(path,options)=>{if(path.endsWith('/split-image')){requests.push(JSON.parse(options.body));if(!saved){saved=true;throw Error('回执丢失');}return {revision:2,canvas_revision:2,node_ids:tiles.map(n=>n.id),media_ids:tiles.map(n=>n.media_id)};}if(saved&&(path.endsWith('/creative-canvases/c1')||path.endsWith('?version=2')))return fixed;}});
 const card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});await selectGrid(a);await generateGrid(a);
 await a.canvas.load(a.root,'p1',null,'c1');assert.equal(a.root.querySelectorAll('.cc-node').length,5);
 await a.root.querySelectorAll('button').find(b=>b.textContent==='恢复原宫格切分').fire('click');
 assert.deepEqual(requests[0],requests[1]);assert.equal(a.root.querySelectorAll('.cc-node').length,5);assert.equal(a.store.has('vsc-canvas-grid:test:p1:c1'),false);a.canvas.suspend();
});

test('custom grid chooses independent rows and columns before submitting',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};let request;
 const a=await fixture({nodes:[source],apiOverride:async(path,options)=>{if(path.endsWith('/split-image')){request=JSON.parse(options.body);const error=Error('停止测试');error.status=422;throw error;}}});
 const card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});const custom=a.root.querySelector('.cc-grid-custom-panel');const confirm=custom.querySelectorAll('button').find(b=>b.textContent==='确定');assert.equal(confirm.disabled,true);
 await custom.querySelectorAll('button').find(b=>b.attrs['aria-label']==='5行7列').fire('click');assert.equal(confirm.disabled,false);await confirm.fire('click');
 await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='宫格 2行3列').fire('click');await generateGrid(a);
 assert.deepEqual(request.payload,{canvas_revision:1,node_id:'source',rows:5,columns:7,cells:[{row:2,column:3}]});assert.equal(a.store.has('vsc-canvas-grid:test:p1:c1'),false);a.canvas.suspend();
});

test('grid selection follows click order and exiting does not edit the canvas',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};let request;
 const a=await fixture({nodes:[source],apiOverride:async(path,options)=>{if(path.endsWith('/split-image')){request=JSON.parse(options.body);const error=Error('停止测试');error.status=422;throw error;}}});
 const card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});await selectGrid(a,[[2,2],[1,1]]);
 await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='宫格 2行2列').fire('click');await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='宫格 2行2列').fire('click');await generateGrid(a);
 assert.deepEqual(request.payload.cells,[{row:1,column:1},{row:2,column:2}]);await a.root.querySelectorAll('button').find(b=>b.attrs['aria-label']==='退出宫格切分').fire('click');
 assert.equal(a.root.querySelector('.cc-grid-overlay'),null);assert.equal(a.root.querySelectorAll('.cc-node').length,1);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('dragging across a grid selects the covered rectangle',async()=>{
 const source={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};let request;
 const a=await fixture({nodes:[source],apiOverride:async(path,options)=>{if(path.endsWith('/split-image')){request=JSON.parse(options.body);const error=Error('停止测试');error.status=422;throw error;}}});
 const card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});await a.root.querySelectorAll('button').find(b=>b.textContent==='4宫格（2×2）').fire('click');
 const overlay=a.root.querySelector('.cc-grid-overlay');await overlay.querySelectorAll('button').find(b=>b.attrs['aria-label']==='宫格 1行1列').fire('pointerdown',{button:0});await overlay.fire('pointerdown');await overlay.querySelectorAll('button').find(b=>b.attrs['aria-label']==='宫格 2行2列').fire('pointerenter');a.window.fire('pointerup');await generateGrid(a);
 assert.deepEqual(request.payload.cells,[{row:1,column:1},{row:1,column:2},{row:2,column:1},{row:2,column:2}]);a.canvas.suspend();
});

test('closing an image tool leaves its source and document untouched',async()=>{
 const node={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const angle={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true};
 const a=await fixture({nodes:[node],runOptions:{revision:1,nodes:[],models:[],image_tools:{angle}}});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
 await a.root.querySelector('.cc-node-head').fire('click');assert.equal(a.root.querySelector('.cc-inspector').hidden,false);await a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');const panel=a.root.querySelector('.cc-image-tool-panel');assert.ok(panel);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);
 await panel.querySelectorAll('button').find(b=>b.attrs['aria-label']==='关闭').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,false);assert.equal(a.root.querySelectorAll('.cc-node').length,1);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('switching images through the minimap clears image-specific panels',async()=>{
 const node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});const angle={preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true};
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:{revision:1,nodes:[],models:[],image_tools:{angle}}});let cards=a.root.querySelectorAll('.cc-node');await cards[0].querySelector('.cc-node-head').fire('click');assert.equal(a.root.querySelector('.cc-inspector').hidden,false);
 await a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');assert.ok(a.root.querySelector('.cc-image-tool-panel'));
 await a.root.querySelector('.cc-minimap').querySelectorAll('button').find(b=>b.title==='second').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);
 await a.root.querySelector('.cc-minimap').querySelectorAll('button').find(b=>b.title==='first').fire('click');assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.root.querySelector('.cc-inspector').hidden,true);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
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
 const doc=JSON.parse(a.store.get(canvasDraftKey())).document,target=doc.nodes.find(n=>n.id!=='source');
 assert.equal(target.params.vsc_image_tool,'angle');assert.equal(JSON.parse(target.params.vsc_image_tool_settings).yaw,-45);assert.equal(JSON.parse(target.params.vsc_image_tool_settings).include_instructions,true);assert.equal(target.text,'保持服装');
 assert.deepEqual(doc.edges.map(e=>[e.source,e.target,e.port]),[['source',target.id,'reference']]);assert.ok(a.root.querySelector('.cc-run-form'));a.canvas.suspend();
});

test('image generation presets fix the original reference before opening generation',async()=>{
 const node={id:'source',type:'image',title:'参考图',x:100,y:100,text:'',params:{},media_id:'media1',job_id:null,group:''};
 const image_tools={three_view:{layout:'front_side_back'},headshot:{framing:'head_and_shoulders'},face_views:{layout:'front_three_quarter_side'}};
 for(const [tool,label] of [['three_view','角色三视图'],['headshot','生成大头照'],['face_views','角色脸部三视图']]){
  const a=await fixture({nodes:[node],runOptions:{revision:1,nodes:[],models:[{id:'model1',enabled:true,modality:'image',model_key:'编辑模型',model_version:'1',capabilities:{purposes:['image_edit']}}],image_tools}});let card=a.root.querySelector('.cc-node');await card.fire('click',{target:card.querySelector('img')});
  const menu=a.root.querySelector('.cc-image-generate-menu--presets');assert.ok(menu);assert.equal(menu.querySelectorAll('button').find(b=>b.textContent==='剧情推进四格').disabled,true);
  await menu.querySelectorAll('button').find(b=>b.textContent===label).fire('click');const doc=JSON.parse(a.store.get(canvasDraftKey())).document,target=doc.nodes.find(n=>n.id!=='source');
  assert.equal(target.params.vsc_image_tool,tool);assert.deepEqual(JSON.parse(target.params.vsc_image_tool_settings),image_tools[tool]);assert.deepEqual(doc.edges.map(e=>[e.source,e.target,e.port]),[['source',target.id,'reference']]);assert.ok(a.root.querySelector('.cc-run-form'));a.canvas.suspend();
 }
});

test('late image tool options do not reopen the panel for a different selection',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:waiting});let cards=a.root.querySelectorAll('.cc-node');await cards[0].fire('click',{target:cards[0].querySelector('img')});
 const opening=a.root.querySelectorAll('button').find(b=>b.textContent==='多角度').fire('click');cards=a.root.querySelectorAll('.cc-node');await cards[1].fire('click',{target:cards[1].querySelector('img')});
 resolve({revision:1,nodes:[],models:[],image_tools:{angle:{preset:'custom',yaw:0,pitch:0,roll:0,zoom:1,include_instructions:true}}});await opening;
 assert.equal(a.root.querySelector('.cc-image-tool-panel'),null);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('late image preset options do not create a node for a different selection',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r),node=(id,x)=>({id,type:'image',title:id,x,y:100,text:'',params:{},media_id:id,job_id:null,group:''});
 const a=await fixture({nodes:[node('first',100),node('second',400)],runOptions:waiting});let cards=a.root.querySelectorAll('.cc-node');await cards[0].fire('click',{target:cards[0].querySelector('img')});
 const opening=a.root.querySelectorAll('button').find(b=>b.textContent==='角色三视图').fire('click');cards=a.root.querySelectorAll('.cc-node');await cards[1].fire('click',{target:cards[1].querySelector('img')});
 resolve({revision:1,nodes:[],models:[],image_tools:{three_view:{layout:'front_side_back'}}});await opening;
 assert.equal(a.root.querySelectorAll('.cc-node').length,2);assert.equal(a.store.has(canvasDraftKey()),false);a.canvas.suspend();
});

test('canvas drafts restore for their actor while another actor on the same canvas sees only the server version',async()=>{
 const a=await fixture();await a.stage.fire('dblclick',{clientX:510,clientY:280});await addImage(a.menu);
 const original=a.store.get(canvasDraftKey());assert.ok(original);await a.canvas.load(a.root,'p1',null,'c1');assert.equal(a.root.querySelectorAll('.cc-node').length,1);
 a.session.actor='other';await a.canvas.load(a.root,'p1',null,'c1');assert.equal(a.root.querySelectorAll('.cc-node').length,0);assert.equal(a.store.has(canvasDraftKey({actor:'other'})),false);
 await a.root.querySelector('.cc-stage').fire('dblclick',{clientX:300,clientY:180});await addImage(a.root.querySelector('.cc-create-menu'));
 const other=JSON.parse(a.store.get(canvasDraftKey({actor:'other'})));assert.equal(other.document.nodes.length,1);assert.notEqual(other.document.nodes[0].id,JSON.parse(original).document.nodes[0].id);
 a.session.actor='test';await a.canvas.load(a.root,'p1',null,'c1');assert.equal(a.root.querySelector('.cc-node').dataset.nodeId,JSON.parse(original).document.nodes[0].id);a.canvas.suspend();
});

test('same actor draft survives a component restart and project or episode navigation without crossing projects',async()=>{
 const a=await fixture();await a.stage.fire('dblclick',{clientX:510,clientY:280});await addImage(a.menu);const id=savedNode(a.store).id;a.canvas.suspend();
 const b=await fixture({store:a.store});assert.equal(b.root.querySelector('.cc-node').dataset.nodeId,id);
 await b.canvas.load(b.root,'p2','episode-two','c1');assert.equal(b.root.querySelectorAll('.cc-node').length,0);
 await b.canvas.load(b.root,'p1','episode-one','c1');assert.equal(b.root.querySelector('.cc-node').dataset.nodeId,id);b.canvas.suspend();
});

test('shared drafts stay separate from private canvases and retain their own actor recovery',async()=>{
 const a=await fixture(),shared={project_id:'p1',canvas_id:'c1',mode:'edit',project_revision:1,version:1,title:'Shared',media_ids:[],document:{viewport:{x:0,y:0,zoom:1},nodes:[],edges:[]}};
 await a.canvas.loadShared(a.root,shared);await a.root.querySelectorAll('button').find(n=>n.textContent==='添加文本').fire('click');assert.ok(a.store.has(canvasDraftKey({shared:true})));
 await a.canvas.load(a.root,'p1',null,'c1');assert.equal(a.root.querySelectorAll('.cc-node').length,0);
 await a.canvas.loadShared(a.root,shared);assert.equal(a.root.querySelectorAll('.cc-node').length,1);
 a.session.actor='other';await a.canvas.loadShared(a.root,shared);assert.equal(a.root.querySelectorAll('.cc-node').length,0);a.canvas.suspend();
});

const marketingNodes=()=>[
 {id:'marketing-brief',type:'text',title:'营销需求',text:'服务器原始营销需求',params:{},x:80,y:80,group:''},
 {id:'marketing-method',type:'text',title:'营销方法',text:'服务器固定方法',params:{},x:360,y:80,group:''},
 {id:'marketing-material-fixed',type:'image',title:'商品参考',text:'',params:{},x:640,y:80,media_id:'fixed',job_id:null,group:''}
];
const agentMessage=a=>a.root.querySelector('.cc-agent-composer').querySelector('textarea');
const agentSend=a=>a.root.querySelector('.cc-agent-send');
const marketingSearch='?marketing=1&skill=image-generation';

test('legacy identity-free canvas, chat, attachment and Agent request entries remain intact but never replace marketing handoff',async()=>{
 const legacy=new Map([
  ['vsc-creative-canvas:p1:c1',JSON.stringify({document:{viewport:{x:0,y:0,zoom:1},nodes:[{...marketingNodes()[0],text:'旧身份画布秘密'}],edges:[]},title:'Old',version:1})],
  ['vsc-canvas-chat:p1:c1',JSON.stringify({message:'旧身份消息秘密'})],
  ['vsc-creative-canvas:p1:c1:agent-attachments',JSON.stringify([{id:'old',name:'旧身份附件秘密'}])],
  ['vsc-canvas-operation:p1:c1:agent-send',JSON.stringify({path:'/old',method:'POST',body:{payload:{message:'旧身份请求秘密'},expected_revision:1,idempotency_key:'old-key'}})]
 ]),original=new Map(legacy),requests=[];
 const a=await fixture({store:legacy,nodes:marketingNodes(),search:marketingSearch,apiOverride:async(path,options)=>{if(path.endsWith('/agent-turns')){requests.push(JSON.parse(options.body));throw Error('response lost');}}});
 assert.ok(a.root.querySelector('.cc-agent'));assert.equal(agentMessage(a).value,'服务器原始营销需求');assert.doesNotMatch(a.root.querySelector('.cc-agent').textContent,/旧身份附件秘密/);
 assert.equal(a.root.querySelectorAll('.cc-node').filter(n=>n.classList.contains('selected')).length,3);
 await agentSend(a).fire('click');assert.equal(requests.length,1);assert.equal(requests[0].payload.message,'服务器原始营销需求');assert.deepEqual(requests[0].payload.node_ids,['marketing-brief','marketing-method','marketing-material-fixed']);assert.notEqual(requests[0].idempotency_key,'old-key');
 for(const [key,value]of original)assert.equal(a.store.get(key),value);a.canvas.suspend();
});

test('Agent messages restore for the same actor across restart and marketing prefill ignores another actor message',async()=>{
 const a=await fixture({nodes:marketingNodes(),search:marketingSearch});agentMessage(a).value='身份A未发送消息';await agentMessage(a).fire('input');a.canvas.suspend();
 const b=await fixture({store:a.store,nodes:marketingNodes(),search:marketingSearch});assert.equal(agentMessage(b).value,'身份A未发送消息');
 b.session.actor='other';await b.canvas.load(b.root,'p1',null,'c1');assert.equal(agentMessage(b).value,'服务器原始营销需求');
 agentMessage(b).value='身份B未发送消息';await agentMessage(b).fire('input');
 b.session.actor='test';await b.canvas.load(b.root,'p1',null,'c1');assert.equal(agentMessage(b).value,'身份A未发送消息');assert.equal(JSON.parse(b.store.get(browserKey('vsc-canvas-chat',{actor:'other'}))).message,'身份B未发送消息');b.canvas.suspend();
});

test('Agent request recovery keeps the same actor original receipt and another actor sends its own fixed payload',async()=>{
 const requests=[];let fail=true;const a=await fixture({nodes:marketingNodes(),search:marketingSearch,apiOverride:async(path,options)=>{
  if(path.endsWith('/agent-turns')){requests.push(JSON.parse(options.body));if(fail)throw Error('lost receipt');return {id:'turn',session_id:'session'};}
 }});
 agentMessage(a).value='身份A固定请求';await agentMessage(a).fire('input');const oldSend=agentSend(a);await oldSend.fire('click');assert.equal(requests.length,1);
 const aKey=browserKey('vsc-canvas-operation',{slot:'agent-send'});assert.ok(a.store.has(aKey));
 a.session.actor='other';await a.canvas.load(a.root,'p1',null,'c1');await oldSend.fire('click');assert.equal(requests.length,1);
 agentMessage(a).value='身份B自己的请求';await agentMessage(a).fire('input');await agentSend(a).fire('click');assert.equal(requests.length,2);assert.equal(requests[1].payload.message,'身份B自己的请求');assert.notEqual(requests[1].idempotency_key,requests[0].idempotency_key);assert.ok(a.store.has(aKey));
 const bKey=browserKey('vsc-canvas-operation',{actor:'other',slot:'agent-send'});const bReceipt=a.store.get(bKey);
 a.session.actor='test';await a.canvas.load(a.root,'p1',null,'c1');assert.equal(agentMessage(a).value,'身份A固定请求');fail=false;await agentSend(a).fire('click');
 assert.equal(requests.length,3);assert.deepEqual(requests[2],requests[0]);assert.equal(a.store.has(aKey),false);assert.equal(a.store.get(bKey),bReceipt);a.canvas.suspend();
});
