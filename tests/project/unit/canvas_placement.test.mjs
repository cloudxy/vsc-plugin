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
async function fixture({nodes=[],viewport={x:0,y:0,zoom:1}}={}) {
  const document={createElement:t=>{const n=new Element(t);n.ownerDocument=document;return n;},createElementNS:(ns,t)=>{const n=document.createElement(t);n.namespaceURI=ns;return n;},createTextNode:text=>{const n=new Element('#text',text);n.ownerDocument=document;return n;},documentElement:{}};
  const store=new Map(),sessionStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
  const window={addEventListener(){},removeEventListener(){}},location={search:''};
  const module=await loadModule('creative-canvas.js',{document,window,location,sessionStorage,crypto,console,setTimeout:()=>0,clearTimeout:()=>{}});
  const root=document.createElement('main');
  const ctx={session:()=>({actor:'test',csrf:'test',revision:1}),setRevision(){},opened(){},api:async(path)=>path.endsWith('/creative-canvases/c1')?{revision:1,canvas_revision:1,title:'Test',episode_id:null,document:{viewport,nodes,edges:[]},jobs:{},runs:[],execution_steps:[]}:{items:[],revision:1}};
  const canvas=module.createCreativeCanvasPanel(ctx);await canvas.load(root,'p1',null,'c1');
  return {root,canvas,store,stage:root.querySelector('.cc-stage'),menu:root.querySelector('.cc-create-menu')};
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
  assert.ok(cards[0].classList.contains('selected'));assert.equal(a.root.querySelector('.cc-inspector').hidden,false);
  await cards[1].fire('click',{target:cards[1].querySelector('img'),shiftKey:true});cards=a.root.querySelectorAll('.cc-node');
  assert.ok(cards[0].classList.contains('selected'));assert.ok(cards[1].classList.contains('selected'));
  await cards[1].fire('keydown',{key:'Enter'});cards=a.root.querySelectorAll('.cc-node');
  assert.equal(cards[0].classList.contains('selected'),false);assert.ok(cards[1].classList.contains('selected'));
  assert.equal(a.store.has('vsc-creative-canvas:p1:c1'),false);a.canvas.suspend();
});
