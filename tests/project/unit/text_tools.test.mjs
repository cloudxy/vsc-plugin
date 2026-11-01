import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
class Element {
 constructor(tag,text=''){this.tagName=tag.toUpperCase();this.textContent=text;this.children=[];this.attrs={};this.listeners={};this.value='';this.style={};this.dataset={};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 get options(){return this.children.filter(x=>x.tagName==='OPTION');}
 async fire(type){for(const f of this.listeners[type]||[])await f({preventDefault(){}});}
}
const root=new Element('main');
const walk=e=>[e,...e.children.flatMap(x=>typeof x==='object'?walk(x):[])];
const find=pred=>walk(root).find(pred);
const script=fs.readFileSync('src/vsc/interfaces/web/static/text-tools.js','utf8');
const context={document:{createElement:t=>new Element(t)},Option:function(text,value){const x=new Element('option',text);x.value=value;return x;},crypto,console,setTimeout,clearTimeout,createRunScopeControls:()=>({dispose(){}})};
vm.createContext(context);
vm.runInContext(script.replace(/^import .*;\n/m,'').replace('export function createTextTools','function createTextTools'),context);
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
