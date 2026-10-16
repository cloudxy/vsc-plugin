/* Execute the actual ES module with a small DOM and controllable network.
   This verifies asynchronous state and view preferences, not visual fidelity. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.listeners={};this.parentElement=null;this._text='';this.value='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  set id(value){this.setAttribute('id',value);} get id(){return this.getAttribute('id');}
  set className(value){this.setAttribute('class',value);} get className(){return this.getAttribute('class')||'';}
  setAttribute(k,v){this.attributes[k]=String(v);}getAttribute(k){return this.attributes[k]??null;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this._text='';this.append(...children);}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  async dispatch(type,extra={}){for(const fn of this.listeners[type]||[])await fn({type,target:this,button:0,preventDefault(){},stopPropagation(){},...extra});}
  closest(selector){for(let e=this;e;e=e.parentElement){if(selector==='[data-node-id]'&&e.getAttribute('data-node-id'))return e;if(selector[0]==='.'&&e.className.split(' ').includes(selector.slice(1)))return e;}return null;}
  getBoundingClientRect(){return {left:0,top:0,width:1200,height:650};}
  setPointerCapture(){}
  all(predicate){return this.children.flatMap(c=>[...(predicate(c)?[c]:[]),...c.all(predicate)]);}
}
const doc={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};
const memory=new Map(), requests=[], pending=[];
const context=vm.createContext({document:doc,localStorage:{getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)},URLSearchParams,AbortController,setTimeout,clearTimeout,console,
  fetch:(url,options)=>{requests.push({url,options});return new Promise(resolve=>pending.push(resolve));}});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8').replace('export function createResourceCanvas','function createResourceCanvas'),context);
const container=new Element('section'), opened=[];
const canvas=context.createResourceCanvas(container,{onSelect:n=>opened.push(n)});
function graph(project,id,label=id){return {project_id:project,revision:4,nodes:[{id:'media:'+id,kind:'media',entity_id:id,label,summary:{modality:'image'}}],edges:[],groups:[{kind:'media',total:1}],warnings:[],next_offset:null};}
function respond(data,ok=true){assert.ok(pending.length);pending.shift()({ok,json:async()=>data});}
function find(text){return container.all(e=>e.tagName==='button'&&e.textContent===text)[0];}
function node(){return container.all(e=>e.getAttribute('data-node-id'))[0];}
function surface(){return container.all(e=>e.className==='canvas-surface')[0];}

(async()=>{
  const old=canvas.load({projectId:'old',userId:'alice'});
  const fresh=canvas.load({projectId:'new',userId:'alice'});
  const oldResolve=pending.shift();respond(graph('new','b','private-label-new'));await fresh;
  oldResolve({ok:true,json:async()=>graph('old','a','stale-old-project')});await old;
  assert.equal(node().getAttribute('data-node-id'),'media:b');
  assert.ok(!container.textContent.includes('stale-old-project'));
  assert.equal(requests[0].options.signal.aborted,true);
  // A captured pointerup is retargeted to the SVG, so it must still select the node.
  const clickSurface=surface();
  await clickSurface.dispatch('pointerdown',{target:node(),clientX:100,clientY:100,pointerId:1});
  await clickSurface.dispatch('pointerup',{clientX:100,clientY:100,pointerId:1});
  assert.equal(opened.length,0);
  await find('打开详情').dispatch('click');assert.equal(opened[0].entity_id,'b');
  const focus=canvas.focus('media:outside-page');assert.ok(requests.at(-1).url.includes('focus=media%3Aoutside-page'));
  respond(graph('new','outside-page'));await focus;
  const expand=find('下游一层').dispatch('click');assert.ok(requests.at(-1).url.includes('revision=4'));assert.ok(requests.at(-1).url.includes('direction=downstream'));
  respond({message:'画布快照已变化，请刷新'},false);await expand;
  assert.ok(container.textContent.includes('画布快照已变化'));assert.equal(node().getAttribute('data-node-id'),'media:outside-page');
  const scene=surface(), before=scene.getAttribute('viewBox');
  await scene.dispatch('wheel',{deltaY:100,clientX:600,clientY:325});assert.notEqual(scene.getAttribute('viewBox'),before);
  const active=node();await scene.dispatch('pointerdown',{target:active,clientX:100,clientY:100,pointerId:1});
  await scene.dispatch('pointermove',{clientX:200,clientY:170});await scene.dispatch('pointerup');
  const movedTransform=node().getAttribute('transform'),savedView=scene.getAttribute('viewBox');
  canvas.destroy();
  const stored=[...memory.values()].join('');assert.ok(!stored.includes('private-label'));assert.ok(!stored.includes('modality'));assert.ok(!stored.includes('revision'));
  assert.ok([...memory.keys()].some(k=>k.includes('alice')&&k.includes('new')));
  const canvas2=context.createResourceCanvas(container,{});
  const restored=canvas2.load({projectId:'new',userId:'alice'});respond(graph('new','outside-page'));await restored;
  assert.equal(node().getAttribute('transform'),movedTransform);assert.equal(surface().getAttribute('viewBox'),savedView);
  const another=canvas2.load({projectId:'new',userId:'bob'});respond(graph('new','outside-page'));await another;
  assert.notEqual(node().getAttribute('transform'),movedTransform);
  canvas2.destroy();assert.ok(requests.every(r=>!r.options.method || r.options.method==='GET'));
  console.log('canvas race, focus, revision conflict, geometry, user isolation and read-only tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
