const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {Document}=require('../../support/fixtures/frontend/panel_dom.cjs');
const button=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
const flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate);};
function fixture(){
  const document=new Document(''),root=document.createElement('section'),calls=[],memory=new Map(),revisions=[];
  document.body.append(root);const create=document.createElement.bind(document);
  document.createElement=tag=>{const node=create(tag);if(tag==='dialog'){
    const listeners=[];node.addEventListener=(type,callback,options={})=>{if(type==='close')listeners.push({callback,once:options.once});};
    node.showModal=()=>{node.open=true;};node.close=value=>{node.open=false;node.returnValue=value;queueMicrotask(async()=>{for(const item of [...listeners]){if(item.once)listeners.splice(listeners.indexOf(item),1);await item.callback();}});};
  }return node;};
  const row={id:'entry',version_id:'fixed-version',title:'固定参考图',allowed_purposes:['first_frame'],members:[{member_key:'reference',modality:'image',preview_url:'/fixed-bytes'}]};
  const context=vm.createContext({document,URLSearchParams,console,crypto:{randomUUID:()=> 'one-intent'},confirm:()=>true,sessionStorage:{getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)}});
  vm.runInContext(fs.readFileSync(path.join(process.env.VSC_TEST_ROOT,'src/vsc/interfaces/web/static/shared-library.js'),'utf8').replace('export function createSharedLibrary','function createSharedLibrary'),context);
  const library=context.createSharedLibrary({session:()=>({actor:'human',csrf:'csrf',writable:true}),notice:()=>{},projects:()=>[{id:'other-project',name:'另一项目'}],canWrite:()=>true,setRevision:(revision,project)=>revisions.push([revision,project]),api:async(url,options)=>{
    calls.push({url,options});if(url==='/api/v1/library/versions/fixed-version')return row;
    if(url.startsWith('/api/v1/library?'))return {items:[{...row,current_version_id:row.version_id}],total:1};
    if(url.includes('/workbench?'))return {scope:url.includes('object_id=shot')?{id:'shot',kind:'shot',title:'目标镜头'}:null,sections:{children:{items:url.includes('object_id=shot')?[]:[{id:'shot',kind:'shot',title:'目标镜头'}]}}};
    if(url.endsWith('/preview-use'))return {available:true,revision:4};
    if(url.endsWith('/use'))return {project_id:'other-project',selected:true,revision:5};
    throw new Error('Unexpected URL '+url);
  }});
  return {root,document,calls,revisions,library};
}
test('global fixed library use chooses its actual target, retains cancel context and returns after asynchronous dialog close',async()=>{
  const f=fixture();await f.library.load(f.root);assert.ok(f.root.textContent.includes('透明特效叠层'));await button(f.root,'查看固定版本').click();await button(f.root,'用于项目中的镜头').click();
  let select=f.root.querySelectorAll('select').find(node=>node.getAttribute('aria-label')==='目标项目');select.value='other-project';await select.dispatch('change');await flush();
  await button(f.root,'目标镜头').click();await button(f.root,'确定用于此镜头').click();
  let dialog=f.document.body.querySelector('dialog');await button(dialog,'取消并返回原处').click();await flush();
  select=f.root.querySelectorAll('select').find(node=>node.getAttribute('aria-label')==='目标项目');assert.equal(select.value,'other-project');assert.ok(f.root.textContent.includes('目标镜头'));
  await button(f.root,'确定用于此镜头').click();await button(dialog,'检查并用于此处').click();await flush();
  assert.equal(dialog.open,false);assert.ok(f.root.textContent.includes('固定参考图'));assert.ok(!f.root.textContent.includes('正在读取固定版本'));
  const use=f.calls.find(call=>call.url.endsWith('/use')),body=JSON.parse(use.options.body);assert.equal(body.payload.target_object_id,'shot');assert.equal(body.payload.role,'first_frame');assert.equal(body.expected_revision,4);assert.equal(body.confirmed,true);assert.deepEqual(f.revisions,[[5,'other-project']]);
});
