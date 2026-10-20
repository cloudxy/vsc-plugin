const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {Document}=require('../../support/fixtures/frontend/panel_dom.cjs');
const root=process.env.VSC_TEST_ROOT || path.resolve(__dirname,'../../..');
const source=fs.readFileSync(path.join(root,'src/vsc/interfaces/web/static/review.js'),'utf8');
let serial=0;
async function fixture(){const document=new Document(''),key=++serial;globalThis.__reviewTestEnvironment ||= new Map();globalThis.__reviewTestEnvironment.set(key,{document,crypto:{randomUUID:()=>`key-${++serial}`}});const prefix=`const {document,crypto}=globalThis.__reviewTestEnvironment.get(${key});\n`;const module=await import('data:text/javascript;base64,'+Buffer.from(prefix+source).toString('base64'));globalThis.__reviewTestEnvironment.delete(key);return {document,...module};}

test('literal original opinion stays text and a professional dispatch without artifacts stays unfinished',async()=>{
  const f=await fixture(),html='<img src=x onerror=alert(1)>',history={items:[{source:{artifact_note_id:'note-1'},body:html,responses:[{explanation:'局部处理',limitations:'没有实际媒体',runs:[],proposals:[],dispatches:[{message:'已派给专业角色，尚无实际结果；意见保持待处理',returns:[]}]}]}]};
  const node=f.renderReviewHistory(history);
  assert.ok(node.textContent.includes(html));assert.equal(node.querySelectorAll('img').length,0);
  assert.ok(node.textContent.includes('尚无实际结果'));assert.equal(node.querySelectorAll('button').length,0);
});

test('new component reads persisted result references and opens exact artifact and media',async()=>{
  const f=await fixture(),opened=[];
  const history=JSON.parse(JSON.stringify({items:[{source:{media_review_id:'original'},body:'只重做声音',responses:[{explanation:'本镜声音',limitations:'试听后再决定',runs:[],proposals:[{id:'run-fixed',approved:true,jobs:[{status:'succeeded',outputs:[{media_id:'audio-fixed'}]}]}],dispatches:[]}]}]}));
  const node=f.renderReviewHistory(history,{artifact:id=>opened.push(['artifact',id]),media:id=>opened.push(['media',id])});
  for(const button of node.querySelectorAll('button'))await button.click();
  assert.deepEqual(opened,[['artifact','run-fixed'],['media','audio-fixed']]);assert.ok(node.textContent.includes('试听后再决定'));assert.ok(!node.textContent.includes('意见已完成'));
});

test('artifact opinion pins server target and seconds to frame range, reusing uncertain command key',async()=>{
  const f=await fixture(),writes=[];let fail=true;
  const target={artifact_id:'fixed-artifact',artifact_sha256:'a'.repeat(64),category:'subtitle',render_id:'fixed-render',render_output_id:'fixed-output',media_sha256:'b'.repeat(64),start_frame:0,end_frame:360};
  const form=f.createArtifactReviewForm([{label:'字幕位置',fps_num:30,fps_den:1,duration_frames:360,target}],{currentTime:()=>7.5,save:async(payload,key)=>{writes.push({payload,key});if(fail)throw new Error('网络结果待核实');}});
  form.querySelector('textarea').value='这一句上移';await form.dispatch('submit');fail=false;await form.dispatch('submit');
  assert.equal(writes[0].key,writes[1].key);assert.deepEqual(writes[1].payload,{...target,start_frame:225,end_frame:255,body:'这一句上移'});
  form.querySelector('textarea').value='换一条意见';await form.querySelector('textarea').dispatch('input');await form.dispatch('submit');assert.notEqual(writes[2].key,writes[1].key);
});

test('professional processing prevents concurrent clicks and retains the same key on an uncertain retry',async()=>{
  const f=await fixture(),calls=[];let release;
  const node=f.renderReviewHistory({items:[{source:{artifact_note_id:'one-note'},body:'看不清行动',responses:[]}]},{process:(payload,key)=>{calls.push({payload,key});return new Promise(resolve=>{release=resolve;});}});
  const button=node.querySelector('button'),first=button.click();await button.click();assert.equal(calls.length,1);release();await first;
  const second=button.click();release();await second;assert.equal(calls[0].key,calls[1].key);assert.deepEqual(calls[0].payload,{artifact_note_id:'one-note'});
});

test('professional new round is explicit and uses a separate command from the ordinary retry',async()=>{
  const f=await fixture(),calls=[];
  const node=f.renderReviewHistory({items:[{source:{artifact_note_id:'old-opinion'},body:'原意见',responses:[{explanation:'处理',limitations:'已到期',runs:[],proposals:[],dispatches:[{message:'尚无结果',returns:[]}]}]}]},
    {process:async(payload,key)=>calls.push({payload,key})});
  const buttons=node.querySelectorAll('button');assert.equal(buttons.length,2);assert.equal(buttons[1].textContent,'明确新一轮专业处理');
  await buttons[0].click();await buttons[1].click();assert.deepEqual(calls[0].payload,{artifact_note_id:'old-opinion'});assert.deepEqual(calls[1].payload,{artifact_note_id:'old-opinion',new_attempt:true});assert.notEqual(calls[0].key,calls[1].key);
});

test('a sound opinion returns to its original review after proposing; a normal local edit still opens its artifact',async()=>{
  const document=new Document(''),key=++serial,opened=[],returned=[],writes=[];
  globalThis.__reviewTestEnvironment ||= new Map();globalThis.__reviewTestEnvironment.set(key,{document,crypto:{randomUUID:()=>`local-${++serial}`}});
  const code=fs.readFileSync(path.join(root,'src/vsc/interfaces/web/static/local-production.js'),'utf8');
  const {createLocalProduction}=await import('data:text/javascript;base64,'+Buffer.from(`const {document,crypto}=globalThis.__reviewTestEnvironment.get(${key});\n`+code).toString('base64'));
  globalThis.__reviewTestEnvironment.delete(key);
  const dialog=document.createElement('dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;};
  const local=createLocalProduction(dialog,{project:()=> 'P',session:()=>({actor:'human',csrf:'csrf'}),revision:()=>{},onArtifact:id=>opened.push(id),
    api:async(url,options)=>{if(url.includes('/options?'))return {purposes:['dialogue_dry']};const body=JSON.parse(options.body);writes.push(body);if(url.endsWith('/preview'))return {targets:[{label:'本镜声音'}],sources:[],revision:1,preview_sha256:'a'.repeat(64)};return {artifact:{id:'fixed-proposal'},revision:2};}});
  for(const review of [true,false]){
    await local.open('redo_sound',{shot_id:'SHOT',purpose:'dialogue_dry',...(review?{media_review_id:'original-opinion',onReviewProposed:result=>returned.push(result.artifact.id)}:{})});
    const buttons=dialog.querySelectorAll('button');await buttons.find(row=>row.textContent==='预览目标与影响').click();await buttons.find(row=>row.textContent==='提交待审方案').click();
    assert.equal(dialog.open,false);
  }
  assert.deepEqual(returned,['fixed-proposal']);assert.deepEqual(opened,['fixed-proposal']);
  assert.equal(writes[1].payload.media_review_id,'original-opinion');assert.ok(!('onReviewProposed' in writes[1].payload));
});

test('professional preview appears only for a returned artifact with real render output references',async()=>{
  const f=await fixture(),opened=[];
  const history={items:[{source:{artifact_note_id:'one'},note:{category:'subtitle'},body:'字幕上移',responses:[{explanation:'位置改变',limitations:'待回看',runs:[],proposals:[],dispatches:[{message:'已有专业返回',returns:[{artifacts:[{id:'new-plan',previews:[]}]}]}]}]}]};
  const missing=f.renderReviewHistory(history,{artifact:id=>opened.push(id),media:id=>opened.push(id)});
  assert.ok(missing.textContent.includes('新预览尚未登记'));assert.equal(missing.querySelectorAll('button').length,1);
  history.items[0].responses[0].dispatches[0].returns[0].artifacts[0].previews=[{media_id:'real-local-preview'}];
  const ready=f.renderReviewHistory(history,{artifact:id=>opened.push(id),media:id=>opened.push(id)});
  assert.ok(!ready.textContent.includes('新预览尚未登记'));const button=ready.querySelectorAll('button').find(row=>row.textContent==='预览专业修改结果');await button.click();assert.deepEqual(opened,['real-local-preview']);
});

test('persisted edit preview removes obsolete waiting text and a nested history omits its duplicate heading',async()=>{
  const f=await fixture();
  const node=f.renderReviewHistory({items:[{source:{artifact_note_id:'note'},note:{category:'subtitle'},body:'向上移动',
    edit_previews:[{status:'succeeded',output:{content_url:'/api/v1/projects/P/edit-previews/J/content'}}],
    responses:[{explanation:'局部修改',limitations:'已派给原专业角色，尚无实际结果',dispatches:[
      {message:'已有专业返回',returns:[{artifacts:[{id:'draft',previews:[]}]}]}]}]}]}, {heading:false});
  assert.equal(node.querySelectorAll('video').length,1);
  assert.equal(node.querySelectorAll('h3').length,0);
  assert.ok(!node.textContent.includes('新预览尚未登记'));
  assert.ok(!node.textContent.includes('尚无实际结果'));
});

test('a failed preview retries the existing job and keeps its key across a lost response',async()=>{
  const f=await fixture(),calls=[];
  const node=f.renderReviewHistory({items:[{source:{artifact_note_id:'note'},body:'原意见',
    edit_previews:[{id:'job',status:'failed'}],responses:[]}]},
    {retryPreview:async(preview,item,key)=>{calls.push([preview.id,item.source.artifact_note_id,key]);if(calls.length===1)throw new Error('响应中断');},onError:()=>{}});
  const retry=node.querySelector('button');
  await retry.click();await retry.click();
  assert.deepEqual(calls[0],calls[1]);
  assert.deepEqual(calls[0].slice(0,2),['job','note']);
});

test('the media reader puts playback and opinions before default-collapsed technical history',async()=>{
  const f=await fixture(),document=new Document(fs.readFileSync(path.join(root,'src/vsc/interfaces/web/templates/index.html'),'utf8')),requests=[];
  for(const dialog of document.querySelectorAll('dialog')){dialog.close=()=>{dialog.open=false;};dialog.showModal=()=>{dialog.open=true;};}
  const media={id:'M',name:'合成音频',modality:'audio',sha256:'a'.repeat(64),revision:3,registered:false,renditions:[],candidates:[],review_history:{items:[]},review_targets:[]};
  const fetch=async url=>{requests.push(url);if(url==='/api/v1/session')return new Promise(()=>{});const value=url.endsWith('/media/M')?media:url.endsWith('/preview-jobs?media_id=M')?{items:[]}:{items:[],lineage:[]};return {ok:true,status:200,json:async()=>value};};
  const environment={document,fetch,crypto:{randomUUID:()=>`key-${++serial}`},review:{renderReviewHistory:f.renderReviewHistory,createArtifactReviewForm:f.createArtifactReviewForm},artifactTitle:()=>'',renderArtifactContent:()=>({})};
  const key=++serial;globalThis.__reviewTestEnvironment.set(key,environment);
  let panelSource=fs.readFileSync(path.join(root,'src/vsc/interfaces/web/static/panel.js'),'utf8').replace("import {artifactTitle, renderArtifactContent} from './artifact-reader.js';",'').replaceAll("await import('./review.js')",'await Promise.resolve(review)');
  const prefix=`const {document,fetch,crypto,review,artifactTitle,renderArtifactContent}=globalThis.__reviewTestEnvironment.get(${key});\n`;
  const panel=await import('data:text/javascript;base64,'+Buffer.from(prefix+panelSource+'\nexport {openMedia,state};').toString('base64'));globalThis.__reviewTestEnvironment.delete(key);
  panel.state.project='P';panel.state.actor='human';panel.state.writable=true;await panel.openMedia('M');
  const detail=document.getElementById('media-detail'),evidence=detail.querySelector('.media-evidence'),history=detail.querySelector('.review-history');
  assert.ok(detail.children[0].querySelector('audio'));assert.ok(detail.children.indexOf(history)<detail.children.indexOf(evidence));assert.ok(!evidence.open);
  for(const pre of detail.querySelectorAll('pre')){let ancestor=pre;while(ancestor&&ancestor!==evidence)ancestor=ancestor.parentElement;assert.equal(ancestor,evidence);}
  assert.ok(!requests.some(url=>url.includes('/preview-jobs')));evidence.open=true;await evidence.dispatch('toggle');assert.equal(requests.filter(url=>url.includes('/preview-jobs')).length,1);
});
