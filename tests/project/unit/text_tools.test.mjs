import fs from 'node:fs';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import crypto from 'node:crypto';
class Element {
 constructor(tag,text=''){this.tagName=tag.toUpperCase();this._text=text;this.children=[];this.attrs={};this.listeners={};this.value='';this.style={};this.dataset={};this.parentElement=null;this.className='';this.classList={add:(...v)=>{this.className=[...new Set([...this.className.split(' '),...v])].filter(Boolean).join(' ');},contains:v=>this.className.split(' ').includes(v)};}
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
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 get options(){return this.children.filter(x=>x.tagName==='OPTION');}
 async fire(type){for(const f of this.listeners[type]||[])await f({preventDefault(){}});}
}
const document={createElement:t=>{const n=new Element(t);n.ownerDocument=document;return n;},createTextNode:text=>{const n=new Element('#text',text);n.ownerDocument=document;return n;}};
const root=document.createElement('main');
const walk=e=>[e,...e.children.flatMap(x=>typeof x==='object'?walk(x):[])];
const find=pred=>walk(root).find(pred);
const context=await loadModule('text-tools.js',{document,crypto,console,setTimeout,clearTimeout});
let stored={id:'u1',tool:'novel',group_key:'main',unit_key:'one',title:'unit',ordinal:0,episode_id:null,current_version_id:'v1',version:1,revision:1,locked:false,document:{body:'initial',characters:[]},attempts:[]};
let submitted,resolveSave;const notices=[];let revision=1;
const caps={tools:{novel:{label:'novel',actions:{},formats:[]}},common:{},defaults:{novel:{body:''}},rows:{},host:{available:false}};
const ctx={session:()=>({actor:'human-1',writable:true,csrf:'test',revision}),setRevision:r=>revision=r,notice:x=>notices.push(x),navigate(){},api:async(path,options)=>{
 if(options?.method==='POST'){submitted=JSON.parse(options.body).payload;return await new Promise(resolve=>resolveSave=()=>{stored={...stored,current_version_id:'v2',version:2,revision:2,document:submitted.document};resolve({id:'v2',unit_id:'u1',revision:2});});}
 if(path.endsWith('capabilities'))return caps;
 if(path.endsWith('options'))return {episodes:[],assets:[],media:[],works:[],scenes:[],shots:[],styles:[]};
 if(path.includes('/units/'))return structuredClone(stored);
 if(path.includes('?tool='))return {items:[stored],revision};
 throw new Error(path);
}};
const instance=context.createTextTools(root,ctx);await instance.load({project:'p1',targetId:'u1'});
const form=find(e=>e.tagName==='FORM'),body=find(e=>e.attrs['aria-label']==='人工正文');
body.value='submitted';await form.fire('input');
const save=form.fire('submit');
while(!resolveSave)await new Promise(r=>setTimeout(r,0));
body.value='typed while save pending';await form.fire('input');
resolveSave();await save;
const visible=find(e=>e.attrs['aria-label']==='人工正文').value;
if(submitted.document.body!=='submitted')throw new Error('submitted snapshot changed');
if(visible!=='typed while save pending')process.exitCode=2;
// A blur/change dispatched by the detached form must not revive its old draft key.
body.value='stale detached input';await form.fire('change');
await instance.load({project:'p1',targetId:'u1'});
if(find(e=>e.attrs['aria-label']==='人工正文').value!=='typed while save pending')process.exitCode=3;
