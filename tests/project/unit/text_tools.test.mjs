import fs from 'node:fs';
import {loadModule} from '../../support/fixtures/frontend/modules.cjs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {test} from 'node:test';
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
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}closest(selector){for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
 addEventListener(k,v){(this.listeners[k]??=[]).push(v);}
 get options(){return this.children.filter(x=>x.tagName==='OPTION');}
 async fire(type,properties={}){const event={target:this,preventDefault(){},...properties};if(this['on'+type])await this['on'+type](event);for(const f of this.listeners[type]||[])await f(event);if(['input','change'].includes(type)&&this.parentElement)await this.parentElement.fire(type,{...properties,target:event.target});}
 focus(){this.ownerDocument.activeElement=this;}showModal(){this.open=true;}close(){this.open=false;return this.fire('close');}
 get selectedOptions(){return this.options.filter(node=>node.selected||node.value===this.value&&!this.multiple);}
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

const toolDefaults={
 novel:{synopsis:'梗概',core_setting:'设定',novel_baseline_version_id:'',characters:[],outline:'分集大纲',scenes:'场景',body:'固定正文',qa_notes:'',chapter_start:1,chapter_end:2,target_episodes:1},
 translation:{body:'Translated text',source_language:'',target_language:'英语',translation_mode:'initial',translation_stage:'draft',episode_number:1,style:'自然对白',style_version_id:'',style_request:false,terms:[],translation_characters:[],reference_version_ids:[],proofread:false},
 scoring:{analysis:'分析',channel:'未知',category:'完整剧本',card_start:1,card_end:1,card_start_line:1,card_end_line:2,card_source_sha256:'',criteria:[{key:'clarity',label:'开场清晰',max_score:10,weight:1}],scores:[{key:'clarity',score:6,evidence:'原文第1行',reason:'明确目标'}],risk_score:100,quality_score:16,confidence:98,review_decision:'keep',review_reason:'已核对来源'},
 breakdown:{media_id:'m1',understanding_mode:'light',observation_basis:'sampled',observations:[{start_ms:0,end_ms:1000,kind:'动作',text:'人物走向门口'}],body:'解析正文'},
 qc:{videos:[{media_id:'m1',name:'one.mp4',sha256:''}],subtitles:[{filename:'one.srt',text:'字幕'}],matches:[],checks:['metadata'],content_rules:[],rule_version:'vsc.media-review/v1',check_ranges:[],base_report_version_id:'',issues:[{rule:'metadata',media_id:'m1',start_ms:0,end_ms:1000,code:'sample',severity:'notice',message:'测试问题',evidence:'实际来源',original_subtitle:'',suggested_subtitle:'',rule_version:'vsc.media-review/v1'}]}
};
const rowShapes={characters:{name:'text',description:'text'},terms:{source:'text',target:'text',aliases:'text'},translation_characters:{source:'text',target:'text',aliases:'text',kind:'text',description:'text'},criteria:{key:'key',label:'text',max_score:'positive',weight:'positive'},scores:{key:'key',score:'number',evidence:'text',reason:'text'},observations:{start_ms:'nonnegative',end_ms:'positive',kind:'text',text:'text'},videos:{media_id:'id',name:'text',sha256:'text'},subtitles:{filename:'text',text:'text'},matches:{video_id:'id',subtitle_name:'text'},check_ranges:{media_id:'id',start_ms:'nonnegative',end_ms:'positive'},issues:{rule:'text',media_id:'text',start_ms:'nonnegative',end_ms:'nonnegative',code:'text',severity:'text',message:'text',evidence:'text',original_subtitle:'text',suggested_subtitle:'text',rule_version:'text'},content_rules:{key:'key',description:'text'}};
async function toolsFixture(){
 const view=document.createElement('main'),requests=[],messages=[],records=new Map();let revision=1;
 for(const [tool,document]of Object.entries(toolDefaults))records.set(tool+'-one',{id:tool+'-one',tool,group_key:'project-'+tool,unit_key:'one',title:tool+' file',ordinal:0,episode_id:null,current_version_id:tool+'-v1',version:1,revision:1,locked:false,document:{source_text:'第一章 起点\n第一行\n第二章 转折\n第二行',source_refs:[],notes:'',...structuredClone(document)},attempts:[],issue_reviews:[]});
 const actions={novel:{synopsis:'梗概建议',characters:'人物小传建议',outline:'分集大纲建议',body:'正文建议'},translation:{terms:'术语建议',translate:'译文建议'},scoring:{analyze:'分析建议',score:'评分'},breakdown:{observe:'分析视频'},qc:{check:'运行质检'}};
 const capabilities={tools:Object.fromEntries(Object.entries(actions).map(([tool,actions])=>[tool,{label:tool,actions,formats:tool==='scoring'?['json','csv']:['txt','json']}])),common:{source_text:'',source_refs:[],notes:''},defaults:structuredClone(toolDefaults),rows:rowShapes,host:{available:false},media_host:{available:false,capabilities:[]}};
 const choices={episodes:[],assets:[],media:[{id:'m1',name:'one.mp4'}],images:[],works:[],scenes:[],shots:[],styles:[{id:'style-v1',style_id:'style',version:1,title:'已保存风格',language:'英语',content:'自然对白'}]};
 const api=async(path,init={})=>{requests.push({path,init});if(init.method==='POST'){const payload=JSON.parse(init.body).payload;if(path.endsWith('/text-tools/units')){const id=payload.unit_id||payload.tool+'-new',old=records.get(id),value={...payload,id,current_version_id:'saved-'+revision,version:(old?.version||0)+1,revision:++revision,locked:false,attempts:[],issue_reviews:[]};records.set(id,value);return {id:value.current_version_id,unit_id:id,revision};}if(path.endsWith('/text-tools/novel-plan'))return {id:'plan',revision:++revision};if(path.endsWith('/text-tools/styles')){const row={...payload,id:'style-v2',style_id:payload.style_id||'new-style',version:2};choices.styles.push(row);return {id:row.id,revision:++revision};}throw new Error('Unexpected write '+path);}
 if(path.endsWith('/capabilities'))return structuredClone(capabilities);if(path.endsWith('/options'))return structuredClone(choices);if(path.includes('/units/'))return structuredClone(records.get(path.split('/').at(-1)));if(path.includes('?tool='))return {items:[...records.values()].filter(row=>row.tool===new URL(path,'http://fixture').searchParams.get('tool')),revision};if(path.endsWith('/batches'))return {items:[],revision};if(path.includes('/batches?'))return {items:[],revision};if(path.endsWith('/media-imports'))return {items:[],revision};if(path.endsWith('/styles'))return {items:structuredClone(choices.styles),revision};if(path==='/api/v1/projects')return {items:[]};if(path.endsWith('/creative-canvases'))return {items:[],revision};throw new Error('Unexpected read '+path);};
 const module=await loadModule('text-tools.js',{document,crypto,console,setTimeout,clearTimeout,URL,AbortController}),instance=module.createTextTools(view,{session:()=>({actor:'tester',writable:true,csrf:'token',revision}),setRevision:r=>revision=r,notice:e=>messages.push(String(e)),navigate(){},api});
 const button=text=>view.querySelectorAll('button').find(node=>node.textContent===text),input=label=>view.querySelectorAll('input,textarea,select').find(node=>node.getAttribute('aria-label')===label),stage=key=>view.querySelectorAll('button').find(node=>node.dataset.stage===key),tick=()=>new Promise(resolve=>setTimeout(resolve,0));
 return {view,instance,requests,messages,records,capabilities,button,input,stage,tick,module};
}
test('novel opens project catalogue, filters, imports in a dialog, and saves the full chapter source before continuing',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'novel'});assert.equal(a.view.dataset.screen,'catalogue');assert.equal(a.view.querySelectorAll('.tt-project-card').length,1);const search=a.input('搜索项目或源文件');search.value='no-match';await search.fire('input');assert.ok(a.view.textContent.includes('没有匹配的项目'));search.value='';await search.fire('input');await a.button('＋ 导入小说').fire('click');await a.tick();assert.ok(a.view.querySelector('.tt-dialog'));assert.ok(a.view.querySelector('.tt-file-drop'));await a.button('取消').fire('click');await a.button('打开项目').fire('click');assert.ok(a.view.querySelector('.tt-chapter-layout'));assert.equal(a.view.querySelectorAll('.tt-chapter-list')[0].querySelectorAll('input').filter(n=>n.type==='checkbox').length,2);const source=a.input('固定原文或转录').value;await a.button('保存拆章并继续').fire('click');assert.equal(a.stage('synopsis').getAttribute('aria-selected'),'true');const save=a.requests.find(r=>r.init.method==='POST');assert.equal(JSON.parse(save.init.body).payload.document.source_text,source);assert.equal(JSON.parse(save.init.body).payload.document.chapter_end,2);assert.ok(a.view.querySelector('.tt-tool-more'));await a.stage('outline').fire('click');const plan=a.view.querySelector('.tt-novel-plan'),outline=plan.querySelector('textarea');outline.value='仅修改分集规划';await outline.fire('input');await plan.querySelectorAll('button').find(node=>node.textContent.includes('创建逐集工作稿')).fire('click');assert.ok(a.requests.some(r=>r.path.endsWith('/text-tools/novel-plan')&&r.init.method==='POST'));a.instance.suspend();
});
test('translation intake links source and target language and leaves older source unknown',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation'});
 const source=a.input('源剧本语言'),target=a.input('目标语言'),intake=a.view.querySelector('.tt-import');
 assert.equal(source.value,'中文（简体）');assert.equal(target.value,'英语');
 source.value='英语';await source.fire('change');assert.equal(target.value,'中文（简体）');assert.equal(a.button('增量翻译').hidden,true);
 assert.equal(intake.documentDefaults().source_language,'英语');assert.equal(intake.documentDefaults().target_language,'中文（简体）');
 source.value='中文（简体）';await source.fire('change');assert.equal(target.value,'英语');assert.equal(a.button('增量翻译').hidden,false);
 await a.button('历史剧本').fire('click');await a.button('→').fire('click');await a.stage('source_text').fire('click');assert.equal(a.input('源剧本语言').value,'');a.instance.suspend();
});
test('translation manual intake keeps its save controls reachable and persists language',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation'});
 const manual=a.view.querySelector('.tt-manual-intake');assert.ok(manual.querySelector('.tt-document-head'));manual.open=true;
 a.input('单元名称').value='人工稿';a.input('固定原文或转录').value='固定原文';a.input('源剧本语言').value='英语';await a.input('源剧本语言').fire('change');
 await a.view.querySelector('form').fire('submit');const req=a.requests.find(r=>r.path.endsWith('/text-tools/units')&&r.init.method==='POST');
 assert.equal(JSON.parse(req.init.body).payload.document.source_language,'英语');assert.equal(JSON.parse(req.init.body).payload.document.target_language,'中文（简体）');a.instance.suspend();
});
test('existing translation drafts update target language without inventing old provenance',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation',targetId:'translation-one'});await a.stage('source_text').fire('click');
 const source=a.input('源剧本语言'),target=a.input('目标语言');assert.equal(source.value,'');source.value='英语';await source.fire('change');
 assert.equal(target.value,'中文（简体）');assert.equal(a.button('增量翻译').hidden,true);await a.view.querySelector('form').fire('submit');
 const req=a.requests.find(r=>r.path.endsWith('/text-tools/units')&&r.init.method==='POST');assert.equal(JSON.parse(req.init.body).payload.document.source_language,'英语');a.instance.suspend();
});
test('translation import uses the filename and rejects oversize files before upload',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation'});
 const intake=a.view.querySelector('.tt-import'),group=a.input('项目名称'),picker=intake.querySelector('.tt-file-drop').querySelector('input');
 assert.ok(intake.textContent.includes('新建项目'));assert.equal(group.parentElement.hidden,true);assert.equal(a.button('上传所选文件').hidden,true);
 picker.files=[{name:'风雨剧本.txt',size:1024}];await picker.fire('change');assert.equal(group.parentElement.hidden,false);assert.equal(group.value,'风雨剧本');assert.equal(a.button('上传所选文件').hidden,false);
 group.value='自选项目';picker.files=[{name:'第二稿.txt',size:1024}];await picker.fire('change');assert.equal(group.value,'自选项目');
 picker.files=[{name:'超限.txt',size:10*1024*1024+1}];await picker.fire('change');assert.equal(a.button('上传所选文件').hidden,true);assert.ok(a.messages.some(m=>m.includes('10 MiB')));assert.equal(a.requests.some(r=>r.init.method==='POST'),false);a.instance.suspend();
});
test('translation mode, history, preview and versioned style save have distinct real-module surfaces',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation'});assert.ok(a.view.querySelector('.tt-translation-intake'));await a.button('增量翻译').fire('click');assert.equal(a.button('增量翻译').getAttribute('aria-pressed'),'true');assert.equal(a.view.querySelector('.tt-incremental-references').hidden,false);await a.button('风格库').fire('click');assert.equal(a.view.dataset.screen,'styles');a.input('名称').value='新风格';a.input('风格语言').value='英语';a.input('风格内容').value='短句与自然对白';await a.input('风格内容').fire('input');await a.button('保存风格').fire('click');assert.equal(JSON.parse(a.requests.find(r=>r.init.method==='POST').init.body).payload.content,'短句与自然对白');await a.button('← 返回').fire('click');await a.button('历史剧本').fire('click');assert.equal(a.view.dataset.screen,'history');await a.button('→').fire('click');assert.equal(a.view.querySelectorAll('.tt-workspace-stages')[0].querySelectorAll('button').length,3);await a.button('预览').fire('click');assert.ok(a.view.querySelector('.tt-dialog').textContent.includes('Translated text'));a.instance.suspend();
});
test('scoring report supports inline cancel and saves review through the original fixed unit version',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'scoring'});assert.ok(a.view.querySelector('.tt-project-table'));await a.button('打开').fire('click');await a.stage('report').fire('click');assert.ok(a.view.querySelector('.tt-inline-review'));await a.button('修改复核').fire('click');const decision=a.input('人工复核结论'),reason=a.input('人工复核理由');decision.value='exclude';await decision.fire('change');reason.value='未保存意见';await reason.fire('input');await a.button('取消').fire('click');assert.equal(decision.value,'keep');assert.equal(reason.value,'已核对来源');assert.equal(a.requests.some(r=>r.init.method==='POST'),false);await a.button('修改复核').fire('click');decision.value='exclude';await decision.fire('change');reason.value='新的复核依据';await reason.fire('input');await a.button('保存复核').fire('click');const save=a.requests.find(r=>r.init.method==='POST');assert.ok(save.path.endsWith('/text-tools/units'));const payload=JSON.parse(save.init.body).payload;assert.equal(payload.base_version_id,'scoring-v1');assert.equal(payload.document.review_decision,'exclude');assert.equal(payload.document.review_reason,'新的复核依据');assert.equal(payload.document.scores[0].evidence,'原文第1行');a.instance.suspend();
});
test('analysis tools default to submission plus history and preserve model capability limits and QC result identity',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'breakdown'});assert.ok(a.view.querySelector('.tt-submit-layout'));assert.ok(a.view.querySelector('.tt-records'));assert.ok(a.view.querySelector('.tt-file-drop'));assert.equal(a.button('保存并开始解析').disabled,true);await a.button('查看结果').fire('click');assert.ok(a.view.querySelector('.tt-result-table').textContent.includes('人物走向门口'));await a.instance.load({project:'p',tool:'qc'});assert.ok(a.view.querySelector('.tt-records'));await a.button('查看结果').fire('click');assert.equal(a.view.querySelector('.tt-qc-issues').querySelectorAll('article').length,1);assert.ok(a.view.textContent.includes('测试问题'));assert.ok(a.view.querySelector('.tt-export-menu'));assert.equal(a.requests.some(r=>r.init.method==='POST'),false);a.instance.suspend();
});
test('chapter view preserves every source byte including preface when splitting and never truncates to a selected chapter',async()=>{
 const {module}=await toolsFixture(),source='序言\n第一章 起点\n甲\n第二章 转折\n乙';const rows=module.splitNovelChapters(source);assert.equal(rows.map(row=>row.text).join(''),source);assert.equal(rows.length,2);assert.ok(rows.some(row=>row.title.includes('第二章')));
});

test('chapter range stays contiguous and number controls update selection',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'novel',targetId:'novel-one'});
 const source=a.input('固定原文或转录');source.value='第一章 起点\n甲\n第二章 发展\n乙\n第三章 终点\n丙';await source.fire('input');
 const end=a.input('结束章');end.value='3';await end.fire('input');
 let boxes=a.view.querySelector('.tt-chapter-list').querySelectorAll('input').filter(n=>n.type==='checkbox');assert.equal(boxes.length,3);assert.ok(boxes.every(n=>n.checked));
 boxes[1].checked=false;await boxes[1].fire('change');
 boxes=a.view.querySelector('.tt-chapter-list').querySelectorAll('input').filter(n=>n.type==='checkbox');assert.ok(boxes.every(n=>n.checked));assert.ok(a.view.textContent.includes('章节范围必须连续'));
 boxes[2].checked=false;await boxes[2].fire('change');assert.equal(end.value,'2');assert.ok(a.view.textContent.includes('请选择连续章节范围'));a.instance.suspend();
});
test('history exposes only source export, draft records do not pretend to contain a report',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'translation'});await a.button('历史剧本').fire('click');const links=a.view.querySelectorAll('a');assert.ok(links.length);assert.ok(links.every(link=>link.href.includes('view=source')));
 await a.instance.load({project:'p',tool:'qc'});const records=a.view.querySelector('.tt-records');assert.ok(records.textContent.includes('固定工作稿'));assert.ok(records.textContent.includes('工作稿'));a.instance.suspend();
});
test('novel filename suggests a project name but does not overwrite a manually chosen one',async()=>{
 const a=await toolsFixture();await a.instance.load({project:'p',tool:'novel'});await a.button('＋ 导入小说').fire('click');
 const name=a.input('项目名称'),picker=a.view.querySelector('.tt-file-drop').querySelector('input');assert.equal(name.value,'');picker.files=[{name:'第一本.txt'}];await picker.fire('change');assert.equal(name.value,'第一本');
 name.value='人工名称';await name.fire('input');picker.files=[{name:'第二本.txt'}];await picker.fire('change');assert.equal(name.value,'人工名称');a.instance.suspend();
});
test('standalone auto-entry deduplicates requests, ignores stale sessions, and supports retry',async()=>{
 const module=await loadModule('text-tools.js',{document,crypto,console,setTimeout,clearTimeout,URL,AbortController}),view=document.createElement('main');let actor='a',csrf='x',calls=0,finish,fail=false,activated=[];
 const instance=module.createTextTools(view,{session:()=>({actor,csrf,writable:true}),notice(){},setRevision(){},activateWorkspace:async id=>activated.push(id),api:async()=>{calls++;if(fail)throw Error('网络故障');return new Promise(resolve=>finish=resolve);}});
 const first=instance.load({project:null}),second=instance.load({project:null});assert.equal(calls,1);finish({id:'workspace-a'});await Promise.all([first,second]);assert.deepEqual(activated,['workspace-a']);
 const stale=instance.load({project:null});assert.equal(calls,2);actor='b';csrf='y';finish({id:'workspace-a'});await stale;assert.deepEqual(activated,['workspace-a']);
 fail=true;await instance.load({project:null});assert.ok(view.textContent.includes('网络故障'));fail=false;const retry=view.querySelectorAll('button').find(node=>node.textContent==='重试打开工作区').fire('click');assert.equal(calls,4);finish({id:'workspace-b'});await retry;assert.deepEqual(activated,['workspace-a','workspace-b']);instance.suspend();
});

test('standalone entry ignores a prior session and a suspended view',async()=>{
 const module=await loadModule('text-tools.js',{document,crypto,console,setTimeout,clearTimeout,URL,AbortController});
 const view=document.createElement('main'),requests=[],activated=[];let actor='member-a',csrf='csrf-a';
 const instance=module.createTextTools(view,{
  session:()=>({actor,csrf,writable:true}),notice(){},setRevision(){},
  activateWorkspace:async id=>activated.push(id),
  api:(path,init)=>new Promise((resolve,reject)=>requests.push({path,init,resolve,reject}))
 });
 const old=instance.load({project:null});assert.equal(requests.length,1);
 assert.equal(requests[0].path,'/api/v1/text-tools/workspace');
 assert.equal(requests[0].init.method,'POST');assert.equal(requests[0].init.headers['X-CSRF-Token'],'csrf-a');
 csrf='csrf-b';const fresh=instance.load({project:null});assert.equal(requests.length,2);
 requests[0].resolve({id:'stale-workspace'});await old;assert.deepEqual(activated,[]);
 requests[1].resolve({id:'current-workspace'});await fresh;assert.deepEqual(activated,['current-workspace']);
 const leaving=instance.load({project:null});assert.equal(requests.length,3);instance.suspend();
 requests[2].resolve({id:'left-workspace'});await leaving;assert.deepEqual(activated,['current-workspace']);
 actor='';await instance.load({project:null});assert.equal(requests.length,3);assert.ok(view.textContent.includes('请先登录'));
});

test('repeated standalone retry shares its in-flight request and activates once',async()=>{
 const module=await loadModule('text-tools.js',{document,crypto,console,setTimeout,clearTimeout,URL,AbortController});
 const view=document.createElement('main'),requests=[],activated=[];
 const instance=module.createTextTools(view,{
  session:()=>({actor:'member',csrf:'csrf',writable:true}),notice(){},setRevision(){},
  activateWorkspace:async id=>activated.push(id),
  api:(path,init)=>new Promise((resolve,reject)=>requests.push({resolve,reject}))
 });
 const first=instance.load({project:null});requests[0].reject(Error('网络故障'));await first;
 const retry=view.querySelectorAll('button').find(node=>node.textContent==='重试打开工作区');assert.ok(retry);
 const attempt=retry.fire('click'),repeat=retry.fire('click');assert.equal(requests.length,2);
 requests[1].resolve({id:'workspace'});await Promise.all([attempt,repeat]);assert.deepEqual(activated,['workspace']);instance.suspend();
});

test('chapter preview follows the saved chapter format and warns about a preface',async()=>{
 const a=await toolsFixture();
 assert.equal(a.module.splitNovelChapters('Chapter 1\nA\nChapter 2\nB').length,1);
 await a.instance.load({project:'p',tool:'novel',targetId:'novel-one'});
 const source=a.input('固定原文或转录');source.value='序言\n第一章 起点\n甲\n第二章 发展\n乙';await source.fire('input');
 assert.ok(a.view.textContent.includes('首章标题前内容保留在原文中，但不纳入章范围。'));
 assert.equal(a.module.splitNovelChapters(source.value).map(row=>row.text).join(''),source.value);
 a.instance.suspend();
});

test('translation length warning, 4-role classification, style presets, bilingual view, and tr_ trace header work end-to-end',async()=>{
 const a=await toolsFixture();
 assert.equal(a.module.computeTranslationLengthWarning('中文（简体）','甲'.repeat(4501)).exceeded,true);
 assert.equal(a.module.computeTranslationLengthWarning('英语','A'.repeat(64001)).exceeded,true);
 assert.equal(a.module.computeTranslationLengthWarning('英语','A'.repeat(1200)).exceeded,false);
 await a.instance.load({project:'p',tool:'translation',targetId:'translation-one'});
 assert.ok(a.view.querySelector('.tt-translation-flow'));
 await a.stage('terms').fire('click');
 assert.ok(a.view.querySelector('.tt-role-groups').textContent.includes('有名角色：0'));
 await a.button('＋ 添加有名角色').fire('click');
 await a.button('＋ 添加群演角色').fire('click');
 assert.ok(a.view.querySelector('.tt-role-groups').textContent.includes('有名角色：1'));
 assert.ok(a.view.querySelector('.tt-role-groups').textContent.includes('群演角色：1'));
 await a.button('风格：电影级对白风格').fire('click');
 assert.ok(a.input('翻译风格').value.includes('凝练克制'));
 await a.stage('body').fire('click');
 await a.button('双栏对照审校').fire('click');
 assert.equal(a.view.querySelector('.tt-bilingual-compare').hidden,false);
 assert.ok(a.view.querySelector('.tt-bilingual-compare').textContent.includes('Translated text'));
 await a.view.querySelector('form').fire('submit');
 const post=a.requests.find(r=>r.init.method==='POST'&&r.path.endsWith('/text-tools/units'));
 assert.match(post.init.headers['X-Trace-Id'],/^tr_\d+_/);
 assert.equal(JSON.parse(post.init.body).payload.document.translation_characters.length,2);
 a.instance.suspend();
});

test('novel custom folder creation, model preference, and review status gate persist cleanly',async()=>{
 const a=await toolsFixture();
 a.capabilities.defaults.novel.model_preference='claude-opus-high';
 a.capabilities.defaults.novel.review_status='pending';
 await a.instance.load({project:'p',tool:'novel'});
 const folderName=a.input('新建文件夹名称');folderName.value='女频重生档';
 await a.button('＋ 新建文件夹').fire('click');
 assert.ok(a.view.querySelector('.tt-folders').textContent.includes('女频重生档 · 0'));
 await a.button('＋ 导入小说').fire('click');
 assert.equal(a.input('项目名称').value,'女频重生档');
 assert.equal(a.input('导入默认深度思考模型').value,'claude-opus-high');
 await a.button('取消').fire('click');
 await a.instance.load({project:'p',tool:'novel',targetId:'novel-one'});
 assert.ok(a.view.querySelector('.tt-novel-flow'));
 const model=a.input('改编深度思考模型'),gate=a.input('阶段审核状态');
 model.value='gpt-5.6-high';await model.fire('change');
 gate.value='approved';await gate.fire('change');
 await a.view.querySelector('form').fire('submit');
 const post=a.requests.find(r=>r.init.method==='POST'&&r.path.endsWith('/text-tools/units'));
 assert.match(post.init.headers['X-Trace-Id'],/^novel_\d+_/);
 const doc=JSON.parse(post.init.body).payload.document;
 assert.equal(doc.model_preference,'gpt-5.6-high');
 assert.equal(doc.review_status,'approved');
 a.instance.suspend();
});

test('scoring loads 10 standard dimensions, quick channels, and breakdown/qc studio controls seek video and expose 8-col report',async()=>{
 const a=await toolsFixture();
 a.capabilities.tools.qc.formats=['xlsx','json','zip'];
 a.capabilities.defaults.qc.voice_language='中文（普通话）';
 await a.instance.load({project:'p',tool:'scoring',targetId:'scoring-one'});
 await a.button('女频').fire('click');
 assert.equal(a.input('频道').value,'女频');
 await a.button('载入天工10维标准指标').fire('click');
 await a.view.querySelector('form').fire('submit');
 const scoreSave=a.requests.find(r=>r.init.method==='POST'&&r.path.endsWith('/text-tools/units'));
 assert.ok(JSON.parse(scoreSave.init.body).payload.document.criteria.length>=10);
 const matches=a.module.computeSubtitleMatches([{media_id:'v1',name:'ep01.mp4'},{media_id:'v2',name:'ep01.zh.mp4'}],[{filename:'ep01.zh.srt'}]);
 assert.equal(matches[0].status,'conflict');
 await a.instance.load({project:'p',tool:'breakdown',targetId:'breakdown-one'});
 assert.ok(a.view.querySelector('.tt-model-badge').textContent.includes('SkyScript'));
 const bVideo=a.view.querySelector('video');assert.ok(bVideo);
 await a.button('跳至时码').fire('click');
 await a.instance.load({project:'p',tool:'qc',targetId:'qc-one'});
 const qVideo=a.view.querySelector('video');assert.ok(qVideo);
 await a.button('定位问题画面').fire('click');
 const skyLink=a.view.querySelectorAll('a').find(n=>n.href?.includes('view=sky_qc'));
 assert.ok(skyLink);
 const filter=a.input('筛选问题类型');filter.value='typo';await filter.fire('change');
 assert.ok(a.view.querySelector('.tt-qc-issues').textContent.includes('当前筛选条件下暂无问题记录'));
 a.instance.suspend();
});

test('script root pill order matches SkyProduction 5-studio header and supports styles/history/parse-smart subview deep-links',async()=>{
 const a=await toolsFixture();
 await a.instance.load({project:'p'});
 assert.equal(a.view.dataset.tool,'translation');
 const pillOrder=a.view.querySelector('.tt-tabs').querySelectorAll('button').map(b=>b.textContent);
 assert.deepEqual(pillOrder,['breakdown','novel','translation','scoring','qc']);

 await a.instance.load({project:'p',tool:'translation',subview:'styles'});
 assert.equal(a.view.dataset.screen,'styles');
 assert.ok(a.view.querySelector('.tt-style-name-count').textContent.includes('0/128'));
 a.input('名称').value='短剧快节奏';await a.input('名称').fire('input');
 assert.ok(a.view.querySelector('.tt-style-name-count').textContent.includes('5/128'));

 await a.instance.load({project:'p',tool:'translation',subview:'history'});
 assert.equal(a.view.dataset.screen,'history');
 assert.ok(a.input('目标语言筛选'));

 await a.instance.load({project:'p',tool:'translation',subview:'parse-smart'});
 assert.equal(a.view.querySelector('.tt-manual-intake').open,true);

 await a.instance.load({project:'p',tool:'novel',subview:'overview'});
 const novelSelected=a.view.querySelector('.tt-workspace-stages').querySelectorAll('button').find(b=>b.getAttribute('aria-selected')==='true');
 assert.equal(novelSelected?.dataset.stage,'synopsis');

 await a.instance.load({project:'p',tool:'novel',subview:'episodes'});
 const epSelected=a.view.querySelector('.tt-workspace-stages').querySelectorAll('button').find(b=>b.getAttribute('aria-selected')==='true');
 assert.equal(epSelected?.dataset.stage,'outline');

 await a.instance.load({project:'p',tool:'translation',subview:'style'});
 const trSelected=a.view.querySelector('.tt-workspace-stages')?.querySelectorAll('button').find(b=>b.getAttribute('aria-selected')==='true');
 assert.equal(trSelected?.dataset.stage,'terms');
 a.instance.suspend();
});
