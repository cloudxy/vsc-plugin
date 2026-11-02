// The real ES module and its UI events; no browser rendering or network claim.
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {Document,Element}=require('../../support/fixtures/frontend/panel_dom.cjs');
const clone=value=>JSON.parse(JSON.stringify(value));
const sorted=value=>Array.isArray(value)?value.map(sorted):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,sorted(value[k])])):value;
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const initial={format:'vsc.edit-workspace/v1',width:128,height:128,fps:24,
  clips:[{id:'first',shot_id:'shot',media_id:'video',in_frame:0,out_frame:5}],audio:[],captions:[]};
const key='vsc.edit-draft:operator:project:episode',requestKey=key+':requests',captionKey=key+':unapplied-srt';
const srt='1\n00:00:00,000 --> 00:00:00,100\n尚未应用的字幕';

(async()=>{
 const memory=new Map();
 globalThis.sessionStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
 globalThis.localStorage={getItem:()=>null,setItem(){}};
 globalThis.crypto=require('node:crypto').webcrypto;
 globalThis.document=new Document('');
 const create=document.createElement.bind(document);
 document.createElement=tag=>{const n=create(tag);n.style={};n.paused=true;n.duration=1;n.currentTime=0;n.play=async()=>{n.paused=false;};n.pause=()=>{n.paused=true;};n.load=()=>{};return n;};
 Object.defineProperty(Element.prototype,'isConnected',{get(){return !!this.parentElement;}});
 globalThis.cancelAnimationFrame=()=>{};globalThis.requestAnimationFrame=()=>0;globalThis.confirm=()=>true;
 const {createEditWorkspace}=await import(pathToFileURL(process.cwd()+'/src/vsc/interfaces/web/static/edit-workspace.js'));
 let authoritative=clone(initial),editRevision=1,projectRevision=10,loss=false,hold=null;
 const writes=[],receipts=new Map();let saves=0;
 const api=async(url,options={})=>{
  if(options.method==='POST'){
   assert.ok(url.endsWith('/edit-workspace'));const intent=JSON.parse(options.body);writes.push(intent);
   if(receipts.has(intent.idempotency_key))return clone(receipts.get(intent.idempotency_key));
   if(intent.payload.edit_revision!==editRevision){const error=new Error('edit_revision_conflict');error.status=409;throw error;}
   authoritative=sorted(intent.payload.document);editRevision++;projectRevision++;saves++;
   const receipt={id:'workspace',edit_revision:editRevision,edit_version_id:'version-'+editRevision,revision:projectRevision};receipts.set(intent.idempotency_key,receipt);
   if(hold)await hold.promise;
   if(loss){loss=false;throw new Error('controlled lost response');}
   return clone(receipt);
  }
  if(url.includes('/edit-workspace?'))return {project_revision:projectRevision,workspace:{id:'workspace',revision:editRevision},current:{id:'version-'+editRevision,document:clone(authoritative)},history:[],renders:[]};
  if(url.includes('/media?'))return {items:[{id:'video',name:'受控视频',modality:'video',duration_ms:1000}],total:1};
  if(url.includes('/edit-candidates?'))return {items:[],total:0,next_offset:null};
  if(url.includes('/edit-seed?'))return {document:{clips:[]},gaps:[],shot_count:0};
  throw new Error('Unexpected fixture URL '+url);
 };
 function mount(){const root=document.createElement('main');document.body.append(root);return {root,editor:createEditWorkspace({root,api,project:'project',episodeId:'episode',session:()=>({identityId:'operator',actor:'operator',csrf:'fixed',writable:true})})};}
 const button=(root,title)=>{const found=root.querySelectorAll('button').find(n=>n.textContent===title);assert.ok(found,'button '+title);return found;};
 function trim(root){const handle=root.querySelectorAll('.edit-timeline-handle').find(n=>n.classList.contains('end'));assert.ok(handle);handle.onkeydown({key:'ArrowLeft',preventDefault(){}});}
 async function typeCaption(root){const field=root.querySelector('.edit-srt');assert.ok(field);field.value=srt;await field.dispatch('input');}
 function captionRetained(root){assert.equal(root.querySelector('.edit-srt').value,srt);assert.equal(JSON.parse(memory.get(captionKey)).text,srt);assert.deepEqual(authoritative.captions,[]);}
 const scenario=process.argv[2];
 if(scenario==='lost-response'){
  const {root,editor}=mount();await editor.load();trim(root);await typeCaption(root);loss=true;
  await assert.rejects(editor.save(),/controlled lost response/);assert.equal(saves,1);assert.equal(authoritative.clips[0].out_frame,4);
  const original=clone(writes[0]);assert.ok(memory.get(requestKey).includes(original.idempotency_key));
  await button(root,'恢复未确认操作').click();assert.equal(saves,1);assert.equal(writes.length,2);assert.deepEqual(writes[1],original);
  assert.ok(root.querySelector('.edit-toolbar').textContent.includes('v2'));assert.equal(memory.has(key),false);assert.deepEqual(JSON.parse(memory.get(requestKey)),{});captionRetained(root);
  await editor.save();assert.equal(writes.length,2);editor.suspend();
 }else if(scenario==='equal-remount'){
  const first=mount();await first.editor.load();trim(first.root);await typeCaption(first.root);
  hold=deferred();const inFlight=first.editor.save();await new Promise(resolve=>setImmediate(resolve));assert.equal(saves,1);
  first.editor.suspend();first.root.remove();const second=mount();await second.editor.load();
  assert.ok(second.root.querySelector('.edit-toolbar').textContent.includes('v2'));captionRetained(second.root);assert.equal(memory.has(key),false);assert.deepEqual(JSON.parse(memory.get(requestKey)),{});
  await second.editor.save();assert.equal(writes.length,1);
  // A late original receipt cannot remove a new intent from the remounted editor.
  trim(second.root);const oldHold=hold;hold=deferred();const nextSave=second.editor.save();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(writes[1].payload.edit_revision,2);const nextKey=writes[1].idempotency_key;oldHold.resolve();await inFlight;
  assert.equal(JSON.parse(memory.get(requestKey))['/edit-workspace'].idempotency_key,nextKey);
  hold.resolve();await nextSave;assert.equal(saves,2);assert.equal(authoritative.clips[0].out_frame,3);captionRetained(second.root);second.editor.suspend();
 }else if(scenario==='different-conflict'){
  const first=mount();await first.editor.load();trim(first.root);await typeCaption(first.root);first.editor.suspend();first.root.remove();
  authoritative=sorted({...clone(initial),clips:[{...initial.clips[0],out_frame:8}]});editRevision=3;projectRevision=20;
  const second=mount();await second.editor.load();assert.ok(second.root.textContent.includes('未保存修改'));captionRetained(second.root);
  await assert.rejects(second.editor.save(),/edit_revision_conflict/);assert.equal(saves,0);assert.equal(authoritative.clips[0].out_frame,8);
  const retained=JSON.parse(memory.get(key));assert.equal(retained.document.clips[0].out_frame,4);assert.equal(retained.edit_revision,1);
  assert.equal(writes[0].payload.edit_revision,1);assert.ok(second.root.textContent.includes('未保存修改'));captionRetained(second.root);second.editor.suspend();
 }else throw new Error('Unknown case '+scenario);
 console.log(scenario+' PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
