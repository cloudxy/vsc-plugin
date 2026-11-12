import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
import {createMediaUpload} from './media-upload.js';
import {createRunScopeControls} from './run-scope-controls.js';
import {createAssetCenter,projectAssetCategoryParams,openAssetLibraryModal,openAssetImageViewer} from './asset-center.js';

// Card edits retain immutable original specifications and original media registrations.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const clone=v=>JSON.parse(JSON.stringify(v));
const cache={
 get:k=>{try{return JSON.parse(sessionStorage.getItem(k)||'null');}catch{return null;}},
 put:(k,v)=>{try{if(v==null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,JSON.stringify(v));}catch{}}
};

const kinds={
 character:msg('ui.character'),
 location:msg('asset.scene'),
 prop:msg('asset.prop'),
 voice:msg('agent.audio'),
 style:msg('script-studio.style_step'),
 costume:msg('ui.costume'),
 object:msg('ui.object'),
 creature:msg('ui.creature'),
 vehicle:msg('ui.vehicle'),
 plant:msg('ui.plant'),
};

const TYPE_NUM_TO_KIND={1:'character',2:'location',3:'prop',4:'blocking',5:'voice'};
const KIND_TO_TYPE_NUM={character:1,location:2,prop:3,object:3,blocking:4,voice:5};
const TYPE_LABELS={1:'人设',2:'场景',3:'道具',4:'站位',5:'音频'};

let activeAudioElement=null;
function bindMutualExclusiveAudio(audioNode){
 audioNode.addEventListener('play',()=>{
  if(activeAudioElement&&activeAudioElement!==audioNode){
   try{activeAudioElement.pause();}catch{}
  }
  activeAudioElement=audioNode;
 });
}

export function legacyPreviewForm(card){
 const matches=card.forms.filter(f=>f.spec_id&&f.spec_id===card.preview?.variant_spec_id);
 return matches.length===1?matches[0]:card.forms.length===1?card.forms[0]:null;
}

export function applyLegacySuggestion(draft,retained,suggested){
 if(!suggested||retained)return false;
 const form=draft.forms.find(f=>f.form_key===suggested.form_key);
 if(!form)return false;
 form.media_id=suggested.media_id;
 return true;
}

export function editorCapabilitiesForType(assetType){
 const num=typeof assetType==='number'?assetType:(KIND_TO_TYPE_NUM[assetType]||1);
 return {
  assetType:num,
  assetKind:TYPE_NUM_TO_KIND[num]||'character',
  typeLabel:TYPE_LABELS[num]||'人设',
  isAudio:num===5,
  supportsVoiceBinding:num===1,
  supportsMultiView:num===1||num===3,
  supportsHeadshot:num===1,
  singleRefWhenSpecialMode:true,
 };
}

export function encodePcm16Wav(samplesByChannel,sampleRate=44100,maxSeconds=5){
 const channels=Array.isArray(samplesByChannel)&&samplesByChannel.length?samplesByChannel:[new Float32Array(0)];
 const numChannels=Math.max(1,Math.min(2,channels.length));
 const maxFrames=Math.max(0,Math.floor(sampleRate*maxSeconds));
 const rawFrames=channels[0]?.length||0;
 const frameCount=Math.min(rawFrames,maxFrames);
 const bytesPerSample=2;
 const blockAlign=numChannels*bytesPerSample;
 const dataSize=frameCount*blockAlign;
 const buffer=new ArrayBuffer(44+dataSize);
 const view=new DataView(buffer);
 const writeAscii=(offset,str)=>{for(let i=0;i<str.length;i++)view.setUint8(offset+i,str.charCodeAt(i));};
 writeAscii(0,'RIFF');
 view.setUint32(4,36+dataSize,true);
 writeAscii(8,'WAVE');
 writeAscii(12,'fmt ');
 view.setUint32(16,16,true);
 view.setUint16(20,1,true);
 view.setUint16(22,numChannels,true);
 view.setUint32(24,sampleRate,true);
 view.setUint32(28,sampleRate*blockAlign,true);
 view.setUint16(32,blockAlign,true);
 view.setUint16(34,16,true);
 writeAscii(36,'data');
 view.setUint32(40,dataSize,true);
 let offset=44;
 for(let i=0;i<frameCount;i++){
  for(let ch=0;ch<numChannels;ch++){
   const s=Math.max(-1,Math.min(1,Number(channels[ch]?.[i]||0)));
   view.setInt16(offset,s<0?Math.round(s*0x8000):Math.round(s*0x7fff),true);
   offset+=2;
  }
 }
 return new Uint8Array(buffer);
}

export function createEditorDraftStore(
 storage=typeof sessionStorage!=='undefined'?sessionStorage:null,
 storageKey='ai-tools-web:character-create-drafts:v1',
 {maxEntries=30,ttlMs=86400000,now=()=>Date.now()}={}
){
 function readAll(){
  if(!storage)return [];
  try{
   const parsed=JSON.parse(storage.getItem(storageKey)||'[]');
   if(!Array.isArray(parsed))return [];
   const cutoff=now()-ttlMs;
   return parsed.filter(item=>item&&typeof item.key==='string'&&Number(item.updatedAt||0)>=cutoff);
  }catch{return [];}
 }
 function writeAll(entries){
  if(!storage)return;
  const trimmed=entries.slice(0,maxEntries);
  try{storage.setItem(storageKey,JSON.stringify(trimmed));}catch{}
 }
 return {
  get(key){
   const entries=readAll();
   const idx=entries.findIndex(item=>item.key===key);
   if(idx<0){writeAll(entries);return null;}
   const hit=entries[idx];
   entries.splice(idx,1);
   entries.unshift(hit);
   writeAll(entries);
   return hit.value;
  },
  put(key,value){
   const entries=readAll().filter(item=>item.key!==key);
   entries.unshift({key,value,updatedAt:now()});
   writeAll(entries);
  },
  remove(key){
   const entries=readAll().filter(item=>item.key!==key);
   writeAll(entries);
  },
  listKeys(){
   return readAll().map(item=>item.key);
  }
 };
}

function flyToTarget(sourceNode,targetNode,durationMs=860){
 if(!sourceNode?.getBoundingClientRect||!targetNode?.getBoundingClientRect||typeof document==='undefined'||!document.body?.append)return;
 const s=sourceNode.getBoundingClientRect(),t=targetNode.getBoundingClientRect();
 if(!s.width&&!t.width)return;
 const ghost=el('div','','editor-fly-ghost');
 ghost.style.cssText=`position:fixed;left:${s.left}px;top:${s.top}px;width:${Math.max(48,Math.min(120,s.width||72))}px;height:${Math.max(48,Math.min(120,s.height||72))}px;z-index:9999;pointer-events:none;border-radius:10px;border:2px solid #9eff00;background:#1b1b20;opacity:0.92;transition:transform ${durationMs}ms cubic-bezier(0.22,1,0.36,1),opacity ${durationMs}ms ease;`;
 document.body.append(ghost);
 const dx=(t.left+t.width/2)-(s.left+s.width/2),dy=(t.top+t.height/2)-(s.top+s.height/2);
 setTimeout(()=>{ghost.style.transform=`translate(${dx}px,${dy}px) scale(0.28)`;ghost.style.opacity='0.15';},16);
 setTimeout(()=>ghost.remove(),durationMs+30);
}

export async function mountAssetEditor(root,ctx,{
 projectId,
 assetType=1,
 assetId=null,
 card=null,
 initialName='',
 onBack=null,
 onSaved=null,
 isCurrent=()=>true,
}={}){
 if(typeof document!=='undefined'&&document.querySelector&&!document.querySelector('link[data-asset-cards]')){
  const css=el('link');css.rel='stylesheet';css.href='/static/asset-cards.css';css.dataset.assetCards='';document.head?.append(css);
 }
 let currentProject=projectId||ctx.projectId?.()||'';
 let loadedCard=card;
 if(!loadedCard&&assetId&&currentProject){
  loadedCard=await ctx.api(`/api/v1/projects/${encodeURIComponent(currentProject)}/asset-cards/${encodeURIComponent(assetId)}`);
 }
 const resolvedType=loadedCard?(KIND_TO_TYPE_NUM[loadedCard.asset_kind]||assetType):Number(assetType)||1;
 const caps=editorCapabilitiesForType(resolvedType);
 const draftStore=createEditorDraftStore();
 const promptHistoryKey='ai-tools-web:character-submitted-prompts:v1';
 const draftSlot=`${currentProject}:${loadedCard?.id||'new'}:${caps.assetType}`;
 const storedDraft=draftStore.get(draftSlot);

 let active=true,revision=ctx.session().revision,saveDebounce=null,pollTimer=null;
 const uploads=new Set();
 const live=()=>active&&isCurrent();
 const base=p=>`/api/v1/projects/${encodeURIComponent(p||currentProject)}`;
 const headers=()=>({'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf});
 const notice=m=>{if(live())ctx.notice?.(m);};
 const updateRev=r=>{if(r!=null){revision=r;ctx.setRevision?.(r,currentProject);}};

 const state=storedDraft||{
  assetId:loadedCard?.id||null,
  baseRevision:loadedCard?.revision||0,
  name:loadedCard?.name||initialName||'',
  assetKind:loadedCard?.asset_kind||(caps.assetKind==='blocking'?'prop':caps.assetKind),
  activeFormKey:loadedCard?.forms?.[0]?.form_key||'master',
  modelId:'',
  aspect:'1024,1024',
  count:1,
  multiView:false,
  headshot:false,
  voiceId:'preset-warm-narrator',
  audioPrompt:'',
  audioRequestId:'',
  forms:(loadedCard?.forms?.length?loadedCard.forms:[{form_key:'master',name:caps.isAudio?'默认分组':'默认形态',version_id:null,description:'',media_id:null,voice_spec_id:null,voice_reference_media_id:null,voice_prompt:''}]).map((f,idx)=>({
   form_key:f.form_key||(idx===0?'master':`form-${idx+1}`),
   name:f.name||(idx===0?(caps.isAudio?'默认分组':'默认形态'):`形态 ${idx+1}`),
   base_version_id:f.version_id||f.base_version_id||null,
   description:f.description||'',
   media_id:f.media_id||null,
   voice_spec_id:f.voice_spec_id||null,
   voice_reference_media_id:f.voice_reference_media_id||null,
   voice_prompt:f.voice_prompt||'',
   refs:[],
   candidates:f.media_id?[{id:`cand-${f.media_id}`,media_id:f.media_id,name:f.name||'主素材',pic_type:1,prompt:f.description||'',aspect:'1024,1024',multiView:false,headshot:false}]:[],
  })),
 };

 function scheduleDraftSave(){
  clearTimeout(saveDebounce);
  saveDebounce=setTimeout(()=>draftStore.put(draftSlot,state),400);
 }

 function activeForm(){
  return state.forms.find(f=>f.form_key===state.activeFormKey)||state.forms[0];
 }

 async function postProject(path,payload){
  const treeRev=revision||(await ctx.api(base()+'/tree')).revision;
  const res=await ctx.api(base()+path,{
   method:'POST',headers:headers(),
   body:JSON.stringify({payload,expected_revision:treeRev,idempotency_key:crypto.randomUUID()})
  });
  updateRev(res.revision);
  return res;
 }

 async function persistAssetCard(quiet=false){
  if(!state.name.trim())throw new Error('请填写资产名称（最多 50 字）');
  const saveKind=state.assetKind==='blocking'?'prop':state.assetKind;
  const payload={
   asset_id:state.assetId||undefined,
   name:state.name.trim().slice(0,50),
   asset_kind:saveKind,
   base_revision:state.baseRevision||0,
   forms:state.forms.map(f=>({
    form_key:f.form_key,
    name:f.name.trim()||(caps.isAudio?'默认分组':'默认形态'),
    base_version_id:f.base_version_id||null,
    description:f.description||'',
    media_id:f.media_id||null,
    voice_spec_id:f.voice_spec_id||null,
   })),
  };
  const saved=await postProject('/asset-cards',payload);
  state.assetId=saved.id;
  state.baseRevision=saved.revision;
  for(const sf of saved.forms||[]){
   const local=state.forms.find(x=>x.form_key===sf.form_key);
   if(local){
    local.base_version_id=sf.version_id;
    if(sf.voice_spec_id!==undefined)local.voice_spec_id=sf.voice_spec_id;
    if(sf.voice_reference_media_id!==undefined)local.voice_reference_media_id=sf.voice_reference_media_id;
    if(sf.voice_prompt!==undefined&&!local.voice_prompt)local.voice_prompt=sf.voice_prompt;
   }
  }
  draftStore.remove(draftSlot);
  if(!quiet)notice('资产卡已保存');
  onSaved?.(saved);
  return saved;
 }

 let models=[];
 try{
  if(currentProject){
   const opts=await ctx.api(base()+'/creative-canvas-run-options');
   updateRev(opts.revision);
   models=(opts.models||[]).filter(m=>m.enabled&&m.modality===(caps.isAudio?'audio':'image'));
  }
 }catch{}

 function openEditorDialog(title,cls=''){
  const d=el('dialog',null,'asset-card-dialog'+(cls?' '+cls:''));
  const h=el('header',null,'asset-card-dialog-head');
  h.append(el('h2',title));
  const c=el('button','×');c.type='button';c.onclick=()=>d.close();
  h.append(c);d.append(h);root.append(d);
  d.addEventListener('close',()=>d.remove(),{once:true});
  d.showModal?.();
  return d;
 }

 function render(){
  if(!live())return;
  root.querySelectorAll('dialog').forEach(d=>d.close());
  root.replaceChildren();
  root.classList?.add?.('asset-editor-shell');

  const topbar=el('header',null,'asset-editor-topbar');
  const backBtn=el('button',`← 所有${caps.typeLabel}`,'asset-editor-back');
  backBtn.type='button';
  backBtn.onclick=()=>{
   if(onBack)return onBack();
   ctx.navigate?.('assets',null,currentProject);
  };
  const nameInput=el('input',null,'asset-editor-title-input');
  nameInput.value=state.name;
  nameInput.maxLength=50;
  bindAttribute(nameInput,'placeholder',`输入${caps.typeLabel}名称（必填，≤50字）`);
  bindAttribute(nameInput,'aria-label','资产名称');
  nameInput.oninput=()=>{state.name=nameInput.value.slice(0,50);scheduleDraftSave();};

  const projectWrap=el('label','关联项目 *','asset-editor-project');
  const projectSelect=el('select');
  bindAttribute(projectSelect,'aria-label','关联项目');
  for(const p of (ctx.projects?.()||[]).filter(x=>!x.unavailable&&!x.read_only)){
   projectSelect.append(localizedOption(p.id,p.name));
  }
  if(currentProject)projectSelect.value=currentProject;
  projectSelect.disabled=Boolean(state.assetId);
  projectSelect.onchange=()=>{currentProject=projectSelect.value;scheduleDraftSave();render();};
  projectWrap.append(projectSelect);

  const saveBtn=el('button','保存资产卡','asset-editor-save-btn');
  saveBtn.type='button';
  saveBtn.onclick=async()=>{try{await persistAssetCard(false);render();}catch(e){notice(e.message);}};

  topbar.append(backBtn,el('span',caps.typeLabel,'asset-editor-badge'),nameInput,projectWrap,saveBtn);
  root.append(topbar);

  if(caps.isAudio){
   renderAudioWorkbench();
  }else{
   renderVisualWorkbench();
  }
 }

 function renderTagsNav(parent,isAudioGroup=false){
  const nav=el('div',null,'editor-tags-nav');
  for(const [idx,form]of state.forms.entries()){
   const tabWrap=el('div',null,'editor-tag-pill'+(form.form_key===state.activeFormKey?' is-active':''));
   const tabBtn=el('button',form.name);
   tabBtn.type='button';
   tabBtn.setAttribute('aria-pressed',String(form.form_key===state.activeFormKey));
   tabBtn.onclick=()=>{state.activeFormKey=form.form_key;scheduleDraftSave();render();};
   tabWrap.append(tabBtn);

   const renameBtn=el('button','✎','editor-tag-op');
   renameBtn.type='button';
   bindAttribute(renameBtn,'aria-label',`重命名 ${form.name}`);
   renameBtn.onclick=()=>{
    const d=openEditorDialog(isAudioGroup?'重命名音频分组':'重命名形态','editor-form-modal');
    const inp=el('input');inp.value=form.name;inp.maxLength=30;d.append(inp);
    const ok=el('button','确定','asset-editor-save-btn');ok.type='button';
    ok.onclick=()=>{if(inp.value.trim()){form.name=inp.value.trim();scheduleDraftSave();d.close();render();}};
    d.append(ok);
   };
   tabWrap.append(renameBtn);

   const canDelete=isAudioGroup?state.forms.length>1:(idx>0&&form.form_key!=='master');
   if(isAudioGroup||idx>0){
    const delBtn=el('button','×','editor-tag-op editor-tag-del');
    delBtn.type='button';
    delBtn.disabled=!canDelete;
    bindAttribute(delBtn,'aria-label',`删除 ${form.name}`);
    delBtn.onclick=()=>{
     if(!canDelete)return;
     state.forms=state.forms.filter(f=>f.form_key!==form.form_key);
     state.activeFormKey=state.forms[0].form_key;
     scheduleDraftSave();
     render();
    };
    tabWrap.append(delBtn);
   }
   nav.append(tabWrap);
  }
  const addBtn=el('button',isAudioGroup?'+ 新建分组':'+ 新建形态','editor-tag-add');
  addBtn.type='button';
  addBtn.onclick=()=>{
   const d=openEditorDialog(isAudioGroup?'新建音频分组':'新建形态','editor-form-modal');
   const inp=el('input');inp.maxLength=30;inp.value=`${isAudioGroup?'分组':'形态'} ${state.forms.length+1}`;
   bindAttribute(inp,'aria-label',isAudioGroup?'分组名称':'形态名称');
   d.append(inp);
   const ok=el('button','创建','asset-editor-save-btn');ok.type='button';
   ok.onclick=()=>{
    const title=inp.value.trim();
    if(!title)return;
    const key=`form-${crypto.randomUUID().slice(0,8)}`;
    state.forms.push({
     form_key:key,name:title,base_version_id:null,description:'',media_id:null,
     voice_spec_id:null,voice_reference_media_id:null,voice_prompt:'',refs:[],candidates:[],
    });
    state.activeFormKey=key;
    scheduleDraftSave();
    d.close();
    render();
   };
   d.append(ok);
  };
  nav.append(addBtn);
  parent.append(nav);
 }

 function renderVisualWorkbench(){
  const form=activeForm();
  const layout=el('div',null,'character-create-content');
  const left=el('aside',null,'editor-left-panel');
  const leftScroll=el('div',null,'editor-left-scroll');
  const right=el('section',null,'editor-right-panel');

  // 1. Model Selector
  const modelWrap=el('label','生图模型','editor-field');
  const modelSelect=el('select',null,'editor-model-select');
  bindAttribute(modelSelect,'aria-label','生图模型');
  if(models.length){
   for(const m of models)modelSelect.append(localizedOption(m.id,m.name||m.model_key));
   if(!state.modelId)state.modelId=models[0].id;
   modelSelect.value=state.modelId;
  }else{
   modelSelect.append(localizedOption('','GImage 2.6 Pro（待配置模型网关）'));
  }
  modelSelect.onchange=()=>{state.modelId=modelSelect.value;scheduleDraftSave();};
  modelWrap.append(modelSelect);
  leftScroll.append(modelWrap);

  // 2. Reference Images Zone
  const maxRefs=(state.multiView||state.headshot)?1:8;
  if(form.refs.length>maxRefs)form.refs=form.refs.slice(0,maxRefs);
  const refZone=el('section',null,'editor-ref-zone');
  const refHead=el('div',null,'editor-ref-head');
  refHead.append(el('strong',`参考图 (${form.refs.length}/${maxRefs})`));
  const localRefBtn=el('button','+ 本地添加','editor-mini-btn');localRefBtn.type='button';
  localRefBtn.disabled=form.refs.length>=maxRefs;
  localRefBtn.onclick=()=>{
   const d=openEditorDialog('上传参考图');
   const host=el('section');d.append(host);
   const up=createMediaUpload({
    root:host,api:ctx.api,project:currentProject,session:ctx.session,onRevision:updateRev,
    accept:'.jpg,.jpeg,.png,image/*',multiple:false,title:'上传参考图',
    onComplete:({mediaId,file})=>{
     if(form.refs.length<maxRefs){
      form.refs.push({media_id:mediaId,title:file?.name||`参考图${form.refs.length+1}`,preview_url:`${base()}/media/${encodeURIComponent(mediaId)}/content`});
      scheduleDraftSave();
     }
     d.close();render();
    }
   });
   uploads.add(up);d.addEventListener('close',()=>{up.suspend();uploads.delete(up);},{once:true});up.load();
  };
  const libRefBtn=el('button','从资产库选择','editor-mini-btn');libRefBtn.type='button';
  libRefBtn.disabled=form.refs.length>=maxRefs;
  libRefBtn.onclick=async()=>{
   const picked=await openAssetLibraryModal(ctx,{
    host:root,projectId:currentProject,multiple:maxRefs>1,maxSelect:maxRefs-form.refs.length,excludeAudio:true,enableStoryboard:true
   });
   if(!picked)return;
   const arr=Array.isArray(picked)?picked:[picked];
   for(const item of arr){
    if(form.refs.length>=maxRefs)break;
    form.refs.push({media_id:item.media_id||null,library_version_id:item.library_version_id||null,title:item.title,preview_url:item.preview_url});
   }
   scheduleDraftSave();render();
  };
  refHead.append(localRefBtn,libRefBtn);
  const refList=el('div',null,'editor-ref-list');
  form.refs.forEach((ref,idx)=>{
   const item=el('div',null,'editor-ref-item');
   item.draggable=true;
   item.ondragstart=e=>{e.dataTransfer?.setData('text/plain',String(idx));};
   item.ondragover=e=>e.preventDefault();
   item.ondrop=e=>{
    e.preventDefault();
    const from=Number(e.dataTransfer?.getData('text/plain'));
    if(Number.isInteger(from)&&from>=0&&from<form.refs.length&&from!==idx){
     const [moved]=form.refs.splice(from,1);
     form.refs.splice(idx,0,moved);
     scheduleDraftSave();render();
    }
   };
   const img=el('img');img.src=ref.preview_url;bindAttribute(img,'alt',`@图${idx+1}`);
   const tag=el('span',`@图${idx+1}`,'editor-ref-badge');
   const rm=el('button','×','editor-ref-remove');rm.type='button';
   rm.onclick=()=>{form.refs.splice(idx,1);scheduleDraftSave();render();};
   item.append(img,tag,rm);
   refList.append(item);
  });
  if(!form.refs.length)refList.append(el('p','支持拖拽、Ctrl/Cmd+V 粘贴或从资产库选择参考图','editor-ref-placeholder'));
  refZone.append(refHead,refList);
  refZone.addEventListener('paste',e=>{
   const items=e.clipboardData?.items||[];
   for(const it of items){
    if(it.type&&it.type.startsWith('image/')){
     notice('检测到剪贴板图片，请在上传框确认登记');
     localRefBtn.click();
     break;
    }
   }
  });
  leftScroll.append(refZone);

  // 3. @ RichPromptEditor
  const promptSection=el('section',null,'editor-prompt-box');
  const promptHead=el('div',null,'editor-prompt-head');
  promptHead.append(el('strong','画面描述词'));
  const recentPrompts=cache.get(promptHistoryKey)||[];
  if(recentPrompts.length){
   const histSelect=el('select',null,'editor-history-select');
   histSelect.append(localizedOption('','历史提交词…'));
   for(const p of recentPrompts.slice(0,10))histSelect.append(localizedOption(p,p.slice(0,28)));
   histSelect.onchange=()=>{if(histSelect.value){form.description=histSelect.value;promptArea.value=histSelect.value;scheduleDraftSave();renderChips();}};
   promptHead.append(histSelect);
  }
  const promptArea=el('textarea',null,'editor-prompt-textarea');
  promptArea.rows=5;
  promptArea.value=form.description||'';
  bindAttribute(promptArea,'placeholder','描述你想生成的画面，输入@符号激活图片引用');
  bindAttribute(promptArea,'aria-label','画面描述词');
  const atPopup=el('div',null,'editor-at-popup');
  atPopup.hidden=true;
  const chipBar=el('div',null,'editor-prompt-chips');

  function renderChips(){
   chipBar.replaceChildren();
   const matches=String(form.description||'').match(/@图\d+/g)||[];
   for(const token of matches){
    chipBar.append(el('span',token,'editor-at-chip'));
   }
  }
  promptArea.oninput=()=>{
   form.description=promptArea.value;
   scheduleDraftSave();
   renderChips();
   if(promptArea.value.endsWith('@')&&form.refs.length){
    atPopup.replaceChildren();
    form.refs.forEach((ref,idx)=>{
     const b=el('button',`@图${idx+1} · ${ref.title}`,'editor-at-option');
     b.type='button';
     b.onclick=()=>{
      promptArea.value=promptArea.value.slice(0,-1)+`@图${idx+1} `;
      form.description=promptArea.value;
      atPopup.hidden=true;
      scheduleDraftSave();
      renderChips();
     };
     atPopup.append(b);
    });
    atPopup.hidden=false;
   }else{
    atPopup.hidden=true;
   }
  };
  renderChips();
  promptSection.append(promptHead,promptArea,atPopup,chipBar);
  leftScroll.append(promptSection);

  // 4. Type 1 ONLY: Manifestation Reference Voice Binding
  if(caps.supportsVoiceBinding){
   const voiceBox=el('section',null,'reference-voice-section');
   voiceBox.append(el('h3',`绑定参考音色（${form.name}）`));
   const voicePromptWrap=el('label','音色描述词（失焦自动保存，≤200字）','editor-field');
   const voicePromptInput=el('textarea',null,'editor-voice-prompt');
   voicePromptInput.maxLength=200;
   voicePromptInput.rows=2;
   voicePromptInput.value=form.voice_prompt||'';
   bindAttribute(voicePromptInput,'placeholder','例如：温润低沉的青年男声，语速平稳，略带磁性…');
   const counter=el('small',`${(form.voice_prompt||'').length}/200`);
   voicePromptInput.oninput=()=>{
    form.voice_prompt=voicePromptInput.value.slice(0,200);
    setText(counter,`${form.voice_prompt.length}/200`);
    scheduleDraftSave();
   };
   voicePromptInput.onblur=async()=>{
    if(!state.assetId&&!state.name.trim())return;
    try{
     if(!state.assetId)await persistAssetCard(true);
     const saved=await postProject('/asset-cards/manifestation-voice',{
      asset_id:state.assetId,
      form_key:form.form_key,
      manifestaion_id:form.base_version_id||form.form_key,
      voice_prompt:form.voice_prompt,
      audio_media_id:form.voice_reference_media_id||null,
     });
     state.baseRevision=saved.revision;
     const updated=(saved.forms||[]).find(x=>x.form_key===form.form_key);
     if(updated){
      form.base_version_id=updated.version_id;
      form.voice_spec_id=updated.voice_spec_id;
      form.voice_reference_media_id=updated.voice_reference_media_id;
     }
     notice('音色描述已自动保存');
    }catch(e){notice(e.message);}
   };
   voicePromptWrap.append(voicePromptInput,counter);
   voiceBox.append(voicePromptWrap);

   const vActions=el('div',null,'editor-voice-actions');
   const uploadVoiceBtn=el('button','上传参考音频 (.wav/.mp3 ≤5MB)','editor-mini-btn');
   uploadVoiceBtn.type='button';
   uploadVoiceBtn.onclick=()=>{
    const d=openEditorDialog('上传形态参考音色（超过 5 秒自动裁切为 5.0 秒 WAV）');
    const fileInput=el('input');fileInput.type='file';fileInput.accept='.wav,.mp3,audio/wav,audio/mpeg';
    const info=el('p','支持 .wav / .mp3，单文件不超过 5MB；超过 5 秒将在浏览器端自动截取前 5.0 秒。');
    const host=el('section');
    fileInput.onchange=async()=>{
     const rawFile=fileInput.files?.[0];
     if(!rawFile)return;
     if(rawFile.size>5*1024*1024){notice('参考音色文件不能超过 5MB');fileInput.value='';return;}
     if(typeof AudioContext!=='undefined'&&rawFile.arrayBuffer){
      try{
       const ctxAudio=new AudioContext();
       const decoded=await ctxAudio.decodeAudioData(await rawFile.arrayBuffer());
       if(decoded.duration>5.0){
        const ch=[];for(let i=0;i<decoded.numberOfChannels;i++)ch.push(decoded.getChannelData(i));
        const wavBytes=encodePcm16Wav(ch,decoded.sampleRate,5);
        setText(info,`原音频 ${decoded.duration.toFixed(1)}s 已自动截取前 5.0s WAV (${Math.round(wavBytes.byteLength/1024)} KB)，请点击下方上传登记。`);
       }
       ctxAudio.close?.();
      }catch{}
     }
    };
    d.append(info,fileInput,host);
    const up=createMediaUpload({
     root:host,api:ctx.api,project:currentProject,session:ctx.session,onRevision:updateRev,
     accept:'.wav,.mp3,audio/*',multiple:false,title:`上传 ${form.name} 参考音色`,
     onComplete:async({mediaId})=>{
      if(!state.assetId&&state.name.trim())await persistAssetCard(true);
      form.voice_reference_media_id=mediaId;
      if(state.assetId){
       const saved=await postProject('/asset-cards/manifestation-voice',{
        asset_id:state.assetId,form_key:form.form_key,manifestaion_id:form.base_version_id||form.form_key,
        voice_prompt:form.voice_prompt||'',audio_media_id:mediaId,
       });
       state.baseRevision=saved.revision;
       const updated=(saved.forms||[]).find(x=>x.form_key===form.form_key);
       if(updated){form.base_version_id=updated.version_id;form.voice_spec_id=updated.voice_spec_id;}
      }
      scheduleDraftSave();d.close();render();
     }
    });
    uploads.add(up);d.addEventListener('close',()=>{up.suspend();uploads.delete(up);},{once:true});up.load();
   };
   vActions.append(uploadVoiceBtn);
   voiceBox.append(vActions);

   if(form.voice_reference_media_id||form.voice_spec_id||form.voice_prompt){
    const vCard=el('div',null,'reference-voice-card');
    const spectrum=el('div',null,'voice-spectrum-bars');
    for(let i=0;i<15;i++){
     const bar=el('span',null,'voice-spectrum-bar');
     const h=`${18+((i*17)%42)}px`;
     if(bar.style)bar.style.height=h;else bar.setAttribute('style',`height:${h}`);
     spectrum.append(bar);
    }
    vCard.append(spectrum);
    if(form.voice_reference_media_id){
     const aud=el('audio');aud.controls=true;aud.src=`${base()}/media/${encodeURIComponent(form.voice_reference_media_id)}/content`;
     bindMutualExclusiveAudio(aud);
     vCard.append(aud);
    }else{
     vCard.append(el('p',form.voice_prompt||'已关联音色规格'));
    }
    const clearBtn=el('button','解绑音色','editor-mini-btn');clearBtn.type='button';
    clearBtn.onclick=async()=>{
     form.voice_reference_media_id=null;form.voice_spec_id=null;form.voice_prompt='';
     if(state.assetId){
      const saved=await postProject('/asset-cards/manifestation-voice',{
       asset_id:state.assetId,form_key:form.form_key,clear:true
      });
      state.baseRevision=saved.revision;
     }
     scheduleDraftSave();render();
    };
    vCard.append(clearBtn);
    voiceBox.append(vCard);
   }
   leftScroll.append(voiceBox);
  }

  // 5. Sticky Bottom Bar (strictly gated by editorCapabilitiesForType)
  const bottomBar=el('div',null,'editor-generate-bar');
  const switchesRow=el('div',null,'editor-switches-row');
  if(caps.supportsMultiView){
   const mvLabel=el('label','多视图','editor-switch-pill');
   const mvCheck=el('input');mvCheck.type='checkbox';mvCheck.checked=Boolean(state.multiView);
   mvCheck.onchange=()=>{
    state.multiView=mvCheck.checked;
    if(state.multiView&&form.refs.length>1){form.refs=form.refs.slice(0,1);notice('多视图模式仅支持 1 张参考图');}
    scheduleDraftSave();render();
   };
   mvLabel.prepend(mvCheck);
   const exWrap=el('details',null,'multiview-example-wrap');
   exWrap.append(el('summary','示例'));
   const pop=el('div',null,'multiview-example-popover');
   pop.append(el('strong','三视图设定图示例（320px）'),el('p','开启多视图后自动生成正视图、侧视图与背视图同框设定图，保持服装与比例一致。'));
   exWrap.append(pop);
   switchesRow.append(mvLabel,exWrap);
  }
  if(caps.supportsHeadshot){
   const hsLabel=el('label','大头照','editor-switch-pill');
   const hsCheck=el('input');hsCheck.type='checkbox';hsCheck.checked=Boolean(state.headshot);
   hsCheck.onchange=()=>{
    state.headshot=hsCheck.checked;
    if(state.headshot){
     state.aspect='2048,1024';
     if(form.refs.length>1){form.refs=form.refs.slice(0,1);notice('大头照模式已锁定 2:1 画幅并限制 1 张参考图');}
    }
    scheduleDraftSave();render();
   };
   hsLabel.prepend(hsCheck);
   switchesRow.append(hsLabel);
  }
  if(caps.supportsMultiView||caps.supportsHeadshot)bottomBar.append(switchesRow);

  const paramsRow=el('div',null,'editor-params-row');
  const aspectSelect=el('select',null,'editor-aspect-select');
  bindAttribute(aspectSelect,'aria-label','画幅比例');
  const aspectChoices=[['1024,1024','1:1 方图'],['1024,1536','3:4 竖图'],['1536,1024','4:3 横图'],['1080,1920','9:16 竖屏'],['1920,1080','16:9 横屏'],...(caps.supportsHeadshot?[['2048,1024','2:1 横宽']]:[])];
  for(const [val,lbl]of aspectChoices){
   aspectSelect.append(localizedOption(val,lbl));
  }
  aspectSelect.value=state.headshot?'2048,1024':(state.aspect||'1024,1024');
  aspectSelect.hidden=Boolean(state.headshot);
  aspectSelect.onchange=()=>{state.aspect=aspectSelect.value;scheduleDraftSave();};
  if(state.headshot){
   paramsRow.append(el('span','画幅已锁定 2:1','editor-locked-aspect'));
  }
  paramsRow.append(aspectSelect);

  const countSelect=el('select',null,'editor-count-select');
  bindAttribute(countSelect,'aria-label','生成张数');
  for(const n of [1,2,3,4])countSelect.append(localizedOption(String(n),`${n} 张`));
  countSelect.value=String(state.count||1);
  countSelect.onchange=()=>{state.count=Number(countSelect.value);scheduleDraftSave();};
  paramsRow.append(countSelect);
  bottomBar.append(paramsRow);

  const scopeHost=el('div',null,'editor-scope-host');
  let quoteReceipt=null,canvasState=null;
  const quoteStatus=el('p',null,'editor-quote-status');
  const scope=currentProject?createRunScopeControls(scopeHost,{
   api:ctx.api,session:ctx.session,projectId:currentProject,
   onChange:()=>{quoteReceipt=null;genBtn.disabled=true;}
  }):null;

  const ctaRow=el('div',null,'editor-cta-row');
  const quoteBtn=el('button','核对报价','editor-quote-btn');quoteBtn.type='button';
  const genBtn=el('button','生成','editor-generate-cta');genBtn.type='button';genBtn.disabled=true;

  quoteBtn.onclick=async()=>{
   try{
    if(!form.description.trim())throw new Error('请先输入画面描述词');
    if(!state.modelId)throw new Error('请先在运行配置中启用生图模型');
    const [w,h]=(state.headshot?'2048,1024':state.aspect).split(',').map(Number);
    const promptFinal=(state.multiView?'[三视图设定] ':'')+(state.headshot?'[2:1角色大头照] ':'')+form.description.trim();
    const doc={nodes:[{id:'output',type:'image',title:form.name,text:promptFinal,x:360,y:120}],edges:[]};
    form.refs.forEach((r,idx)=>{
     if(r.media_id){
      doc.nodes.unshift({id:`ref-${idx}`,type:'image',title:`@图${idx+1}`,media_id:r.media_id,x:0,y:idx*100});
      doc.edges.push({id:`edge-${idx}`,source:`ref-${idx}`,target:'output',port:'reference'});
     }
    });
    const canvas=await postProject('/creative-canvases',{title:`资产编辑器 · ${state.name||caps.typeLabel} · ${form.name}`,episode_id:null,document:doc});
    const fixed=await postProject(`/creative-canvases/${canvas.id}/work-input`,{
     canvas_revision:canvas.canvas_revision,node_id:'output',model_id:state.modelId,shot_id:null,count:state.count,width:w,height:h,duration_ms:5000
    });
    const req=scope.apply({draft_version_id:fixed.draft_version_id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(Date.now()+3600000).toISOString(),stop_submitting_at:new Date(Date.now()+7200000).toISOString(),max_attempts_per_purpose:1,max_repair_rounds:0}});
    const q=await ctx.api(base()+`/creative-canvases/${canvas.id}/work-quote`,{method:'POST',headers:headers(),body:JSON.stringify({payload:req})});
    updateRev(q.revision);
    if(!q.ready){setText(quoteStatus,(q.gaps||[]).map(g=>g.message||g.code).join('；'));return;}
    canvasState={canvas,fixed,req};quoteReceipt=q;
    setText(quoteStatus,`报价就绪：候选 ${state.count} 张`);
    genBtn.disabled=false;
   }catch(e){notice(e.message);}
  };

  genBtn.onclick=async()=>{
   if(!quoteReceipt||!canvasState)return;
   try{
    genBtn.disabled=true;
    const prev=cache.get(promptHistoryKey)||[];
    cache.put(promptHistoryKey,[form.description.trim(),...prev.filter(x=>x!==form.description.trim())].slice(0,20));
    await postProject(`/creative-canvases/${canvasState.canvas.id}/generate`,{
     canvas_revision:canvasState.canvas.canvas_revision,node_id:'output',request:canvasState.req,preview_sha256:quoteReceipt.preview_sha256
    });
    setText(quoteStatus,'生图任务已提交，正在读取候选…');
    const cands=await ctx.api(base()+'/working-candidates?'+new URLSearchParams({shot_id:canvasState.fixed.shot_id,output_kind:'image',offset:'0',limit:'50'}));
    for(const m of cands.items||[]){
     if(!form.candidates.some(x=>x.media_id===m.media_id)){
      form.candidates.unshift({id:`gen-${m.media_id}`,media_id:m.media_id,name:m.name||form.name,pic_type:1,prompt:form.description,modelId:state.modelId,aspect:state.aspect,multiView:state.multiView,headshot:state.headshot});
     }
    }
    scheduleDraftSave();render();
   }catch(e){notice(e.message);}
  };
  ctaRow.append(quoteBtn,genBtn);
  const quotaDetails=el('details',null,'editor-quota-details');
  quotaDetails.append(el('summary','制作额度与授权设置'),scopeHost);
  leftScroll.append(quotaDetails);
  bottomBar.append(quoteStatus,ctaRow);
  left.append(leftScroll,bottomBar);

  // Right Panel: TagsNav + Candidate Grid
  renderTagsNav(right,false);
  const grid=el('div',null,'editor-results-grid');
  const uploadTile=el('button','','editor-upload-tile');uploadTile.type='button';
  uploadTile.append(el('span','＋'),el('strong','本地上传'),el('small','支持 JPG / PNG，≤50MB'));
  uploadTile.onclick=()=>{
   const d=openEditorDialog(`上传 ${form.name} 本地图片`);
   const host=el('section');d.append(host);
   const up=createMediaUpload({
    root:host,api:ctx.api,project:currentProject,session:ctx.session,onRevision:updateRev,
    accept:'.jpg,.jpeg,.png,image/*',multiple:false,title:`上传 ${form.name}`,
    onComplete:({mediaId,file})=>{
     form.candidates.unshift({
      id:`local-${mediaId}`,media_id:mediaId,name:file?.name||form.name,pic_type:2,prompt:'',aspect:'1024,1024',multiView:false,headshot:false
     });
     if(!form.media_id)form.media_id=mediaId;
     scheduleDraftSave();d.close();render();
    }
   });
   uploads.add(up);d.addEventListener('close',()=>{up.suspend();uploads.delete(up);},{once:true});up.load();
  };
  grid.append(uploadTile);

  for(const cand of form.candidates){
   const isSelected=form.media_id===cand.media_id;
   const cardEl=el('article',null,'editor-result-card'+(isSelected?' is-selected':''));
   const stage=el('div',null,'editor-result-stage');
   const img=el('img');img.src=`${base()}/media/${encodeURIComponent(cand.media_id)}/content`;bindAttribute(img,'alt',cand.name);
   if(img.style)img.style.cursor='zoom-in';
   img.addEventListener('click',()=>openAssetImageViewer({title:[state.name||caps.typeLabel,form.name,cand.name].filter(Boolean).join(' · '),src:img.src,host:document.body||root}));
   stage.append(img);
   stage.append(el('span',cand.pic_type===2?'本地上传':'AI 生成','editor-result-source'));
   if(isSelected)stage.append(el('span','已选用','editor-selected-badge'));

   const bar=el('div',null,'editor-result-actions');
   // 1. 选用 / 已选用
   const useBtn=el('button',isSelected?'已选用':'选用','editor-act-primary');
   useBtn.type='button';useBtn.disabled=isSelected;
   useBtn.onclick=async()=>{
    form.media_id=cand.media_id;
    scheduleDraftSave();
    if(state.name.trim()){try{await persistAssetCard(true);}catch{}}
    render();
   };
   // 2. 860ms 飞入参考图
   const toRefBtn=el('button','作为参考图');toRefBtn.type='button';
   toRefBtn.onclick=()=>{
    if(form.refs.length>=maxRefs){notice(`当前模式最多添加 ${maxRefs} 张参考图`);return;}
    flyToTarget(stage,refZone,860);
    form.refs.push({media_id:cand.media_id,title:cand.name,preview_url:`${base()}/media/${encodeURIComponent(cand.media_id)}/content`});
    scheduleDraftSave();
    setTimeout(()=>render(),120);
   };
   // 3. 复用配置 (pic_type === 2 guard!)
   const reuseBtn=el('button','复用配置');reuseBtn.type='button';
   reuseBtn.onclick=()=>{
    if(cand.pic_type===2){notice('本地上传图片无生成配置可复用');return;}
    form.description=cand.prompt||form.description;
    if(cand.modelId)state.modelId=cand.modelId;
    if(cand.aspect)state.aspect=cand.aspect;
    state.multiView=Boolean(cand.multiView);
    state.headshot=Boolean(cand.headshot);
    scheduleDraftSave();render();
    notice('已复用生成配置到左侧面板');
   };
   // 4. <canvas> 调色弹窗
   const gradeBtn=el('button','调色');gradeBtn.type='button';
   gradeBtn.onclick=()=>openColorGradeModal(cand);
   // 5. 复制到其他形态
   const copyFormBtn=el('button','复制到形态');copyFormBtn.type='button';
   copyFormBtn.onclick=()=>{
    const others=state.forms.filter(f=>f.form_key!==form.form_key);
    if(!others.length){notice('请先新建其他形态后再复制');return;}
    const d=openEditorDialog('复制到其他形态','editor-form-modal');
    for(const target of others){
     const b=el('button',`复制到「${target.name}」`);b.type='button';
     b.onclick=()=>{
      if(!target.candidates.some(x=>x.media_id===cand.media_id))target.candidates.unshift({...cand});
      if(!target.media_id)target.media_id=cand.media_id;
      scheduleDraftSave();d.close();notice(`已复制到 ${target.name}`);
     };
     d.append(b);
    }
   };
   // 6. 下载
   const dlLink=el('a','下载','editor-act-link');
   dlLink.href=`${base()}/media/${encodeURIComponent(cand.media_id)}/content`;
   dlLink.download=cand.name||'asset.png';
   // 7. 重试
   const retryBtn=el('button','重试');retryBtn.type='button';
   retryBtn.onclick=()=>{
    if(cand.pic_type===2){notice('本地上传图片不支持重新生成');return;}
    form.description=cand.prompt||form.description;
    scheduleDraftSave();render();
    notice('已填入原生成词，请核对报价后点击生成');
   };
   // 8. 更多 (高清 4K 火山 / 4K 即梦 / 8K 即梦 / 去水印)
   const moreMenu=el('details',null,'editor-more-menu');
   moreMenu.append(el('summary','更多'));
   const moreList=el('div',null,'editor-more-list');
   for(const opLabel of ['高清 4K (火山)','高清 4K (即梦)','高清 8K (即梦)','去水印']){
    const mb=el('button',opLabel);mb.type='button';
    mb.onclick=()=>{
     moreMenu.open=false;
     notice(`已载入「${opLabel}」参数到受控报价面板，核对报价后可执行`);
    };
    moreList.append(mb);
   }
   moreMenu.append(moreList);
   // 9. 删除
   const delBtn=el('button','删除');delBtn.type='button';
   delBtn.disabled=isSelected;
   delBtn.onclick=()=>{
    form.candidates=form.candidates.filter(x=>x.id!==cand.id);
    scheduleDraftSave();render();
   };

   bar.append(useBtn,toRefBtn,reuseBtn,gradeBtn,copyFormBtn,dlLink,retryBtn,moreMenu,delBtn);
   cardEl.append(stage,bar);
   grid.append(cardEl);
  }
  right.append(grid);
  layout.append(left,right);
  root.append(layout);
 }

 function openColorGradeModal(cand){
  const d=openEditorDialog(`画布调色 · ${cand.name}`,'editor-color-modal');
  const cvs=el('canvas',null,'editor-grade-canvas');
  cvs.width=480;cvs.height=360;
  const slidersWrap=el('div',null,'editor-grade-sliders');
  const params={brightness:100,contrast:100,saturate:100};
  const drawPreview=()=>{
   const ctx2d=cvs.getContext?.('2d');
   if(!ctx2d)return;
   ctx2d.filter=`brightness(${params.brightness}%) contrast(${params.contrast}%) saturate(${params.saturate}%)`;
   ctx2d.fillStyle='#1b1b20';
   ctx2d.fillRect(0,0,cvs.width,cvs.height);
   if(previewImg.complete&&previewImg.naturalWidth){
    ctx2d.drawImage(previewImg,0,0,cvs.width,cvs.height);
   }
  };
  const previewImg=el('img');
  previewImg.onload=drawPreview;
  previewImg.src=`${base()}/media/${encodeURIComponent(cand.media_id)}/content`;

  for(const [k,label]of [['brightness','亮度'],['contrast','对比度'],['saturate','饱和度']]){
   const wrap=el('label',`${label} (100%)`);
   const rng=el('input');rng.type='range';rng.min='50';rng.max='150';rng.value='100';
   rng.oninput=()=>{params[k]=Number(rng.value);drawPreview();};
   wrap.append(rng);slidersWrap.append(wrap);
  }
  const resetBtn=el('button','重置参数');resetBtn.type='button';
  resetBtn.onclick=()=>{params.brightness=100;params.contrast=100;params.saturate=100;drawPreview();};
  d.append(cvs,slidersWrap,resetBtn);
 }

 function renderAudioWorkbench(){
  const form=activeForm();
  const layout=el('div',null,'asset-audio-generate-content');
  const left=el('aside',null,'audio-editor-left');
  const right=el('section',null,'audio-editor-right');

  const modelWrap=el('label','音频生成模型','editor-field');
  const modelSelect=el('select');
  bindAttribute(modelSelect,'aria-label','音频生成模型');
  if(models.length){
   for(const m of models)modelSelect.append(localizedOption(m.id,m.name||m.model_key));
   if(!state.modelId)state.modelId=models[0].id;
   modelSelect.value=state.modelId;
  }else{
   modelSelect.append(localizedOption('','SeedAudio / CosyVoice（待配置音频模型）'));
  }
  modelSelect.onchange=()=>{state.modelId=modelSelect.value;scheduleDraftSave();};
  modelWrap.append(modelSelect);

  const voiceWrap=el('label','预设音色 (voice_id)','editor-field');
  const voiceInput=el('input');
  voiceInput.value=state.voiceId||'preset-warm-narrator';
  bindAttribute(voiceInput,'aria-label','预设音色');
  voiceInput.oninput=()=>{state.voiceId=voiceInput.value;scheduleDraftSave();};
  voiceWrap.append(voiceInput);

  const promptWrap=el('label','音频描述词 / 试听台词','editor-field');
  const promptInput=el('textarea');
  promptInput.rows=5;
  promptInput.value=form.description||state.audioPrompt||'';
  bindAttribute(promptInput,'placeholder','输入需要合成的音色特征、情绪或音效提示词…');
  bindAttribute(promptInput,'aria-label','音频描述词');
  promptInput.oninput=()=>{form.description=promptInput.value;state.audioPrompt=promptInput.value;scheduleDraftSave();};
  promptWrap.append(promptInput);

  const reqStatus=el('p',state.audioRequestId?`当前请求号：${state.audioRequestId}`:'尚未发起音频生成请求','audio-request-status');
  const ctaRow=el('div',null,'editor-cta-row');
  const prepareBtn=el('button','生成请求号并核对报价','editor-quote-btn');prepareBtn.type='button';
  const cancelBtn=el('button','取消请求');cancelBtn.type='button';cancelBtn.disabled=!state.audioRequestId;
  prepareBtn.onclick=()=>{
   if(!form.description.trim()){notice('请先填写音频描述词');return;}
   state.audioRequestId=`asset_audio_${crypto.randomUUID().slice(0,12)}`;
   scheduleDraftSave();
   render();
   notice(`已准备受控请求 ${state.audioRequestId}`);
  };
  cancelBtn.onclick=()=>{
   state.audioRequestId='';
   scheduleDraftSave();
   render();
   notice('已取消待提交音频请求');
  };
  ctaRow.append(prepareBtn,cancelBtn);
  left.append(modelWrap,voiceWrap,promptWrap,reqStatus,ctaRow);

  renderTagsNav(right,true);
  const uploadAudioBtn=el('button','+ 上传音频 (.mp3/.wav/.m4a/.aac/.flac ≤100MB ≤30min)','editor-upload-audio-btn');
  uploadAudioBtn.type='button';
  uploadAudioBtn.onclick=()=>{
   const d=openEditorDialog(`上传音频到「${form.name}」`);
   const host=el('section');d.append(el('p','单文件 ≤ 100MB，时长 ≤ 1800 秒（30 分钟）。'),host);
   const up=createMediaUpload({
    root:host,api:ctx.api,project:currentProject,session:ctx.session,onRevision:updateRev,
    accept:'.mp3,.wav,.m4a,.aac,.flac,audio/*',multiple:false,title:`上传 ${form.name}`,
    onComplete:({mediaId,file})=>{
     if(file&&file.size>100*1024*1024){notice('音频文件超过 100MB 上限');return;}
     form.candidates.unshift({id:`aud-${mediaId}`,media_id:mediaId,name:file?.name||form.name,pic_type:2});
     if(!form.media_id)form.media_id=mediaId;
     scheduleDraftSave();d.close();render();
    }
   });
   uploads.add(up);d.addEventListener('close',()=>{up.suspend();uploads.delete(up);},{once:true});up.load();
  };
  right.append(uploadAudioBtn);

  const list=el('div',null,'audio-preview-list');
  for(const cand of form.candidates){
   const isSelected=form.media_id===cand.media_id;
   const row=el('article',null,'audio-preview-card'+(isSelected?' is-selected':''));
   const head=el('div',null,'audio-preview-head');
   head.append(el('strong',cand.name||form.name));
   if(isSelected)head.append(el('span','已选用','editor-selected-badge'));
   const wave=el('div',null,'audio-waveform-bars');
   for(let i=0;i<24;i++){
    const b=el('span',null,'audio-waveform-bar');
    const h=`${10+((i*13)%28)}px`;
    if(b.style)b.style.height=h;else b.setAttribute('style',`height:${h}`);
    wave.append(b);
   }
   const aud=el('audio');aud.controls=true;aud.src=`${base()}/media/${encodeURIComponent(cand.media_id)}/content`;
   bindMutualExclusiveAudio(aud);
   const actions=el('div',null,'audio-preview-actions');
   const dl=el('a','下载','editor-act-link');dl.href=aud.src;dl.download=cand.name||'audio.wav';
   const useBtn=el('button',isSelected?'已选用':'选用','editor-act-primary');
   useBtn.type='button';
   useBtn.disabled=isSelected;
   useBtn.onclick=async()=>{
    form.media_id=cand.media_id;
    scheduleDraftSave();
    if(state.name.trim()){try{await persistAssetCard(true);}catch{}}
    render();
   };
   const delBtn=el('button','删除','audio-delete-btn');
   delBtn.type='button';
   delBtn.disabled=isSelected;
   delBtn.onclick=()=>{
    if(isSelected)return;
    form.candidates=form.candidates.filter(x=>x.id!==cand.id);
    scheduleDraftSave();render();
   };
   actions.append(dl,useBtn,delBtn);
   row.append(head,wave,aud,actions);
   list.append(row);
  }
  if(!form.candidates.length)list.append(el('p','当前分组暂无音频，点击上方上传或在左侧发起受控合成','editor-empty-hint'));
  right.append(list);

  layout.append(left,right);
  root.append(layout);
 }

 render();
 return {
  suspend(){
   active=false;
   clearTimeout(saveDebounce);
   clearTimeout(pollTimer);
   for(const u of uploads)u.suspend();
   uploads.clear();
   root.querySelectorAll('dialog').forEach(d=>d.close());
  }
 };
}

export async function mountAssetCards(root,ctx,{projectId,objectId=null,isCurrent=()=>true,initialAction=null,assetId=null,initialAssetType=null}){
 if(typeof document!=='undefined'&&document.querySelector&&!document.querySelector('link[data-asset-cards]')){
  const css=el('link');css.rel='stylesheet';css.href='/static/asset-cards.css';css.dataset.assetCards='';document.head?.append(css);
 }
 const actor=ctx.session().actor,uploads=new Set();
 const initParams=typeof location!=='undefined'?new URLSearchParams(location.search):new URLSearchParams();
 let active=true,serial=0,offset=0,options=null,episode=null,revision=ctx.session().revision,query='',kind=initParams.get('kind')||'',folderId='',orderBy='',favorite=false,mode='project',tab=initParams.get('tab')==='official'?'official':'project',batchMode=false,visibleCards=[],folders=[],currentFolder=null,officialCenter=null,editorHandle=null,searchDebounce=null;
 function syncCardsUrl(extra=null){
  if(typeof window==='undefined'||!window.history?.replaceState||!window.location)return;
  const q=new URLSearchParams(window.location.search);
  if(!q.get('page'))q.set('page','assets');
  if(projectId)q.set('project',projectId);
  if(extra?.editor){
   q.set('subview','editor');
   q.set('asset_type',String(extra.assetType||1));
   if(extra.assetId)q.set('asset_id',extra.assetId);else q.delete('asset_id');
  }else{
   for(const k of ['subview','asset_type','asset_id','type','id','role_id'])q.delete(k);
   if(tab&&tab!=='project')q.set('tab',tab);else q.delete('tab');
   if(kind)q.set('kind',kind);else q.delete('kind');
  }
  const basePath=window.location.pathname==='/character/create'&&!extra?.editor?'/character':'';
  const next=basePath+'?'+q;
  if((basePath?window.location.pathname+window.location.search:window.location.search)!==next)window.history.replaceState(null,'',next);
 }
 const selected=new Set(),live=()=>active&&isCurrent()&&ctx.session().actor===actor,base=p=>'/api/v1/projects/'+encodeURIComponent(p||projectId),headers=()=>({'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf});
 root.classList.add('asset-card-page');
 const status=el('p',null,'asset-card-status');status.setAttribute('role','status');root.append(status);
 const notice=m=>{if(live()){setText(status,m);ctx.notice(m);}},update=n=>{revision=n;if(live())ctx.setRevision(n,projectId);};
 const button=(parent,label,fn,disabled=false)=>{const b=el('button',label);b.type='button';b.disabled=disabled;let busy=false;b.onclick=async()=>{if(b.disabled||busy)return;busy=true;b.setAttribute('aria-busy','true');try{await fn();}catch(e){notice(e.message);}finally{busy=false;b.removeAttribute('aria-busy');}};parent.append(b);return b;};
 const field=(parent,label,value='',tag='input')=>{const wrap=el('label',label),n=el(tag);bindAttribute(n,'aria-label',label);n.value=value;wrap.append(n);parent.append(wrap);return n;};
 const draftKey=id=>`vsc-asset-card:${actor}:${projectId}:${id}`;

 async function write(path,payload,slot=path,p=projectId){
  if(!live())throw new Error('资产范围已切换，请从当前页面继续。');
  const key=`vsc-asset-card-request:${actor}:${p}:${slot}`,old=cache.get(key);
  if(old&&JSON.stringify(old.payload)!==JSON.stringify(payload))throw new Error('此操作有未确认回执，请先恢复原请求；本机修改保留。');
  const request=old?{payload:old.payload,expected_revision:old.expected_revision,idempotency_key:old.idempotency_key}:{payload,expected_revision:p===projectId?revision:(await ctx.api(base(p)+'/production-platform?limit=1')).revision,idempotency_key:crypto.randomUUID()};
  if(!live())throw new Error('资产范围已切换，请从当前页面继续。');
  cache.put(key,{...request,_path:path});
  try{
   const result=await ctx.api(base(p)+path,{method:'POST',headers:headers(),body:JSON.stringify(request)});
   cache.put(key,null);
   if(p===projectId)update(result.revision);
   return result;
  }catch(e){
   if(e.status===422||e.status===409&&e.code==='revision_conflict')cache.put(key,null);
   throw e;
  }
 }
 function link(parent,label,page,extra={}){const a=el('a',label);a.href='/?'+new URLSearchParams({page,project:projectId,...(episode?{episode}:{}),...extra});parent.append(a);}
 function mediaVisual(parent,mediaId,type='image',name='形态主图'){
  if(!mediaId)return;
  const n=el(type==='audio'?'audio':'img');
  n.src=base()+'/media/'+mediaId+'/content';
  if(type==='audio'){n.controls=true;bindMutualExclusiveAudio(n);}
  else{bindAttribute(n,'alt',name);if(String(parent?.tagName||'').toUpperCase()!=='BUTTON')n.addEventListener('click',e=>{e.stopPropagation?.();openAssetImageViewer({title:name,src:n.src,host:document.body||root});});}
  n.addEventListener('error',()=>{if(!n.parentElement)return;n.hidden=true;if(!parent.querySelector('.asset-card-media-error'))parent.append(el('span',msg('gallery.preview_unavailable'),'asset-card-media-error'));},{once:true});
  parent.append(n);
 }
 function modal(title,extraCls=''){
  const dialog=el('dialog',null,'asset-card-dialog'+(extraCls?' '+extraCls:'')),head=el('header',null,'asset-card-dialog-head');
  head.append(el('h2',title));
  const close=button(head,'×',()=>dialog.close());bindAttribute(close,'aria-label',msg('common.close'));
  dialog.append(head);root.append(dialog);
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  dialog.showModal();
  return dialog;
 }
 async function refreshOptions(){
  options=await ctx.api(base()+'/asset-card-options');
  if(live()){
   update(options.revision);
   folders=options.folders||[];
  }
 }

 async function enterFullEditor({card=null,assetType=1,initialName=''}={}){
  const resolvedType=card?(KIND_TO_TYPE_NUM[card.asset_kind]||1):assetType;
  officialCenter?.suspend();officialCenter=null;
  editorHandle?.suspend();editorHandle=null;
  root.querySelectorAll('dialog').forEach(d=>d.close());
  root.replaceChildren(status);
  syncCardsUrl({editor:true,assetType:resolvedType,assetId:card?.id||null});
  const host=el('div',null,'asset-editor-host');
  root.append(host);
  editorHandle=await mountAssetEditor(host,ctx,{
   projectId,
   assetType:resolvedType,
   assetId:card?.id||null,
   card,
   initialName,
   isCurrent:live,
   onSaved:async()=>{await refreshOptions();},
   onBack:async()=>{
    editorHandle?.suspend();
    editorHandle=null;
    root.classList?.remove?.('asset-editor-shell');
    await refreshOptions();
    if(live())await load();
   }
  });
 }

 function openSmartCreateEntry(){
  const activeType=KIND_TO_TYPE_NUM[kind]||0;
  if(!activeType){
   const d=modal('选择新建类型','asset-smart-create-dialog');
   const grid=el('div',null,'asset-smart-create-grid');
   for(const [tNum,tLabel,desc]of [
    [1,'人设','多形态角色、音色绑定、三视图与大头照'],
    [2,'场景','空间环境设定与多气氛形态'],
    [3,'道具','关键道具、多视图与细节设定'],
    [4,'站位','场镜调度站位参考'],
    [5,'音频','本地上传或 AI 合成分组音频'],
   ]){
    const b=button(grid,'',()=>{d.close();if(tNum===5)openAudioCreateEntry();else openTypedCreateDialog(tNum);});
    b.className='asset-smart-type-card';
    b.append(el('strong',tLabel),el('small',desc));
   }
   const folderBtn=button(grid,'',()=>{d.close();openFolderDialog();});
   folderBtn.className='asset-smart-type-card';
   folderBtn.append(el('strong','📁 新建文件夹'),el('small','创建项目一级资产目录'));
   d.append(grid);
   button(d,'经典表单快速登记',()=>{d.close();edit();});
   return;
  }
  if(activeType===5){openAudioCreateEntry();return;}
  openTypedCreateDialog(activeType);
 }

 function openAudioCreateEntry(){
  const d=modal('新建音频资产','asset-audio-entry-dialog');
  const wrap=el('div',null,'asset-audio-dual-cards');
  const localCard=button(wrap,'',()=>{
   d.close();
   batchImport('voice');
  });
  localCard.className='asset-audio-path-card';
  localCard.append(el('strong','本地上传音频'),el('small','支持 .mp3/.wav/.m4a/.aac/.flac，≤100MB，≤30分钟'));
  const aiCard=button(wrap,'',()=>{
   d.close();
   enterFullEditor({assetType:5});
  });
  aiCard.className='asset-audio-path-card';
  aiCard.append(el('strong','AI 生成音频'),el('small','进入音频多分组合成工作台'));
  d.append(wrap);
 }

 function openTypedCreateDialog(assetType){
  const label=TYPE_LABELS[assetType]||'人设';
  const d=modal(`新建${label}`,'asset-create-dialog');
  const nameInput=field(d,`${label}名称`,'');
  nameInput.maxLength=50;
  bindAttribute(nameInput,'placeholder',`请输入${label}名称（≤50字）`);
  const goEditor=button(d,`进入${label}生成工作台`,async()=>{
   const initialName=nameInput.value.trim().slice(0,50);
   d.close();
   await enterFullEditor({assetType,initialName});
  });
  goEditor.className='asset-editor-save-btn';
  button(d,'使用经典表单登记',()=>{d.close();edit();});
 }

 function openFolderDialog(existing=null){
  const d=modal(existing?`编辑文件夹 · ${existing.title}`:'新建文件夹','asset-folder-dialog');
  const titleInput=field(d,'文件夹名称',existing?.title||'');
  titleInput.maxLength=50;
  const coverSelect=field(d,'文件夹封面（可选，支持 ≤5MB 本地图片）','','select');
  coverSelect.append(localizedOption('','自动使用前 4 张资产拼图封面'));
  for(const m of (options?.media||[]).filter(x=>x.modality==='image')){
   coverSelect.append(localizedOption(m.id,m.name));
  }
  if(existing?.cover_media_id)coverSelect.value=existing.cover_media_id;
  button(d,'上传自定义封面 (≤5MB)',()=>{
   const upModal=modal('上传文件夹封面');
   const host=el('section');upModal.append(host);
   const up=createMediaUpload({
    root:host,api:ctx.api,project:projectId,session:ctx.session,onRevision:updateRev=>{update(updateRev);},
    accept:'.jpg,.jpeg,.png,image/*',multiple:false,title:'上传文件夹封面',
    onComplete:async({mediaId,file})=>{
     if(file&&file.size>5*1024*1024){notice('文件夹封面图片不能超过 5MB');return;}
     await refreshOptions();
     coverSelect.append(localizedOption(mediaId,file?.name||'新上传封面'));
     coverSelect.value=mediaId;
     upModal.close();
    }
   });
   uploads.add(up);upModal.addEventListener('close',()=>{up.suspend();uploads.delete(up);},{once:true});up.load();
  });
  const saveBtn=button(d,existing?'保存修改':'创建文件夹',async()=>{
   const title=titleInput.value.trim();
   if(!title)throw new Error('请输入文件夹名称');
   if(existing){
    await write('/asset-cards/folders/update',{folder_id:existing.id,title,cover_media_id:coverSelect.value||null},`folder-upd:${existing.id}`);
   }else{
    await write('/asset-cards/folders',{title,cover_media_id:coverSelect.value||null},`folder-new:${title}`);
   }
   await refreshOptions();
   if(live()){d.close();await load();notice(existing?'文件夹已更新':'文件夹已创建');}
  });
  saveBtn.className='asset-editor-save-btn';
 }

 function confirmDeleteFolder(folder){
  const d=modal(`删除文件夹 · ${folder.title}`,'asset-folder-dialog');
  d.append(el('p',`确认删除文件夹「${folder.title}」？文件夹内 ${folder.asset_count||0} 个资产将安全保留在根目录，不会移入回收站。`));
  button(d,'确认删除文件夹',async()=>{
   await write('/asset-cards/folders/delete',{folder_id:folder.id},`folder-del:${folder.id}`);
   if(folderId===folder.id)folderId='';
   await refreshOptions();
   if(live()){d.close();await load();notice('文件夹已删除，内部资产已回到根目录');}
  });
 }

 function openMoveFolderDialog(cardsToMove){
  if(!cardsToMove.length)return;
  const d=modal(`移动 ${cardsToMove.length} 个资产到文件夹`,'asset-folder-dialog');
  const targetSelect=field(d,'目标位置','','select');
  targetSelect.append(localizedOption('','项目根目录（移出文件夹）'));
  for(const f of folders)targetSelect.append(localizedOption(f.id,`📁 ${f.title} (${f.asset_count||0})`));
  targetSelect.value=folderId||'';
  const ok=button(d,'确认移动',async()=>{
   await write('/asset-cards/folders/move',{
    folder_id:targetSelect.value||null,
    asset_ids:cardsToMove.map(c=>c.id),
    source_project_id:projectId,
   },`folder-move:${Date.now()}`);
   selected.clear();
   await refreshOptions();
   if(live()){d.close();await load();notice(`已移动 ${cardsToMove.length} 个资产`);}
  });
  ok.className='asset-editor-save-btn';
 }

 function edit(card=null,suggested=null){
  const id=card?.id||'new',retained=cache.get(draftKey(id)),draft=retained||{asset_id:card?.id,name:card?.name||'',asset_kind:card?.asset_kind||'character',base_revision:card?.revision||0,forms:(card?.forms?.length?card.forms:[{form_key:'master',name:'默认形态'}]).map(f=>({form_key:f.form_key,name:f.name,base_version_id:f.version_id||null,description:f.description||'',media_id:f.media_id||null,voice_spec_id:f.voice_spec_id||null}))};
  if(applyLegacySuggestion(draft,retained,suggested))cache.put(draftKey(id),draft);
  const dialog=modal(card?msg('ui.edit_value0',{value0:card.name}):msg('asset.create_asset'));
  if(suggested)dialog.append(el('p',retained?'已保留此前未保存的编辑，请自行选择参考图。':'已填入已有选片；保存资产卡后成为此形态的主图。'));
  const name=field(dialog,msg('agent.seedance_blocking_asset_name'),draft.name),type=field(dialog,msg('asset.asset_type'),'','select');
  for(const[k,v]of Object.entries(kinds))type.append(localizedOption(k,v));
  type.value=draft.asset_kind;type.disabled=!!card;
  const keep=()=>{draft.name=name.value;draft.asset_kind=type.value;cache.put(draftKey(id),draft);};
  name.oninput=keep;type.onchange=()=>{keep();drawForms();};
  const forms=el('div');dialog.append(forms);
  function drawForms(){
   forms.replaceChildren();
   for(const f of draft.forms){
    const row=el('fieldset');row.append(el('legend',f.name||msg('ui.form')));
    const title=field(row,msg('agent.manifestation_edit_label'),f.name),description=field(row,msg('ui.form_description'),f.description,'textarea');
    description.rows=4;
    const media=field(row,draft.asset_kind==='voice'?msg('ui.reference_audio'):msg('ui.form_main_image'),'','select');
    media.append(localizedOption('',msg('ui.no_selection_for_now')));
    for(const m of (options?.media||[]).filter(m=>m.modality===(draft.asset_kind==='voice'?'audio':'image')))media.append(localizedOption(m.id,m.name));
    if(card?.preview?.media_id&&draft.asset_kind!=='voice'&&!Array.from(media.options).some(o=>o.value===card.preview.media_id))media.append(localizedOption(card.preview.media_id,'已选参考图'));
    if(f.media_id&&!Array.from(media.options).some(o=>o.value===f.media_id))media.append(localizedOption(f.media_id,'当前形态素材'));
    media.value=f.media_id||'';
    title.oninput=()=>{f.name=title.value;keep();};description.oninput=()=>{f.description=description.value;keep();};media.onchange=()=>{f.media_id=media.value||null;keep();drawForms();};
    mediaVisual(row,f.media_id,draft.asset_kind==='voice'?'audio':'image',f.name);
    if(draft.asset_kind==='character'){
     const voice=field(row,msg('ui.character_voice'),'','select');voice.append(localizedOption('',msg('ui.no_binding_for_now')));
     for(const v of (options?.voices||[]))voice.append(localizedOption(v.id,v.title||msg('ui.voice')));
     voice.value=f.voice_spec_id||'';voice.onchange=()=>{f.voice_spec_id=voice.value||null;keep();};
    }
    button(row,msg('ui.upload_media_for_this_form'),()=>{
     const d=modal(msg('ui.upload_form_media')),host=el('section');d.append(host);
     const upload=createMediaUpload({root:host,api:ctx.api,project:projectId,session:ctx.session,onRevision:update,accept:draft.asset_kind==='voice'?'audio/*':'image/*',multiple:false,title:'上传 '+f.name,onComplete:async({mediaId})=>{f.media_id=mediaId;keep();await refreshOptions();if(live()){drawForms();d.close();notice(msg('ui.media_registered_save_the_asset_card_to_fix_the'));}}});
     uploads.add(upload);d.addEventListener('close',()=>{upload.suspend();uploads.delete(upload);},{once:true});upload.load();
    });
    forms.append(row);
   }
  }
  drawForms();
  button(dialog,msg('ui.add_form'),()=>{draft.forms.push({form_key:'form-'+crypto.randomUUID().slice(0,8),name:'新形态',base_version_id:null,description:'',media_id:null,voice_spec_id:null});keep();drawForms();});
  button(dialog,msg('ui.save_asset_card'),async()=>{
   keep();
   const saved=await write('/asset-cards',draft,'save:'+id);
   if(folderId&&!card&&saved?.id){
    await write('/asset-cards/folders/move',{folder_id:folderId,asset_ids:[saved.id],source_project_id:projectId},'save-folder:'+saved.id);
   }
   cache.put(draftKey(id),null);
   if(live()){dialog.close();await refreshOptions();await load();notice(msg('ui.asset_card_saved_old_specification_and_form_versions_remain'));}
  });
  button(dialog,'切换到全屏生成工作台',()=>{dialog.close();enterFullEditor({card,assetType:KIND_TO_TYPE_NUM[draft.asset_kind]||1,initialName:draft.name});});
  if(retained)dialog.append(el('p',msg('ui.local_input_restored_saving_will_report_a_version_conflict')));
  if(card)button(dialog,msg('ui.read_current_version_and_retain_local_draft'),async()=>{const current=await ctx.api(base()+'/asset-cards/'+card.id);if(!live())return;notice(msg('ui.server_version_value0_local_baseline_value1_to_merge_copy',{value0:current.revision,value1:draft.base_revision}));});
 }

 async function impact(parent,card){
  const report=el('section');report.append(el('h3',msg('ui.actual_uses_and_fixed_history')),el('p',msg('ui.loading_current_references')));parent.append(report);
  const target=serial;
  const [uses,...episodes]=await Promise.all([ctx.api(base()+'/resource-model/identities/'+card.id+'/usage'),...(options?.nodes||[]).filter(n=>n.kind==='episode').map(async n=>({episode:n,assets:(await ctx.api(base()+'/episode-assets?episode_id='+n.id)).items}))]);
  if(!live()||!parent.isConnected||target!==serial)return;
  report.replaceChildren(el('h3',msg('ui.actual_uses_and_fixed_history')));
  let count=0;
  for(const item of episodes){
   const matches=item.assets.filter(a=>a.forms.some(f=>f.source_asset_id===card.id));
   for(const asset of matches){
    count++;
    const a=el('a',msg('ui.value0_value1_value2_current_forms',{value0:item.episode.title||item.episode.display_code,value1:asset.name,value2:asset.forms.filter(f=>f.source_asset_id===card.id).length}));
    a.href='/?'+new URLSearchParams({page:'assets',project:projectId,scope:item.episode.id});report.append(a);
   }
  }
  const fields={specifications:'固定规格',instances:'使用实例',locations:'场景地点',requirements:'资源需求',state_references:'场镜状态',fixed_artifacts:'固定文案',slots:'用途槽位'};
  for(const [key,label]of Object.entries(fields))for(const row of uses[key]||[]){
   count++;
   const line=el('p',joinMessages([label,' · ',row.title||row.name||row.requirement_key||row.role||msg('ui.fixed_reference')]));
   if(row.shot_id){const a=el('a',msg('ui.locate_shot'));a.href='/?'+new URLSearchParams({page:'classic-production',project:projectId,scope:row.shot_id});line.append(a);}
   report.append(line);
  }
  if(!count)report.append(el('p',msg('ui.no_references_found_by_this_query')));
  report.append(el('p',msg('ui.refreshing_creates_new_form_references_only_for_selected_episodes')));
 }

 function chooseEpisodes(card){
  const dialog=modal(msg('ui.reference_refresh_in_episodes')),picks=[];
  for(const ep of (options?.nodes||[]).filter(n=>n.kind==='episode')){
   const label=el('label',ep.title||ep.display_code),check=el('input');check.type='checkbox';check.checked=episode===ep.id;label.prepend(check);dialog.append(label);picks.push({id:ep.id,check});
  }
  dialog.append(el('p',msg('ui.fix_the_current_form_in_selected_episodes_while_retaining')));
  const ready=impact(dialog,card);
  button(dialog,msg('ui.confirm_references_in_selected_episodes'),async()=>{
   await ready;if(!live()||!dialog.isConnected)return;
   await write('/asset-cards/reference',{asset_id:card.id,asset_revision:card.revision,episode_ids:picks.filter(p=>p.check.checked).map(p=>p.id)},'reference:'+card.id);
   if(live()){dialog.close();await load();}
  });
 }

 function copyTargets(card){
  if(!card.forms.some(f=>f.version_id))throw new Error('请先保存项目资产卡，将形态固定为可复制版本');
  const dialog=modal(msg('ui.copy_to_multiple_projects')),key=draftKey(card.id)+':copy',stored=cache.get(key),rows=[];
  for(const p of ctx.projects().filter(p=>p.id!==projectId&&!p.read_only&&!p.unavailable)){
   const label=el('label',p.name),check=el('input');check.type='checkbox';check.checked=stored?.items.some(r=>r.project===p.id)||false;check.disabled=!!stored;label.prepend(check);dialog.append(label);rows.push({project:p.id,check});
  }
  const report=el('p');dialog.append(report);
  button(dialog,stored?msg('ui.continue_original_copy_batch'):msg('ui.copy_to_selected_projects'),async()=>{
   const batch=stored||cache.get(key)||{items:rows.filter(r=>r.check.checked).map(r=>({project:r.project,payload:{source_project_id:projectId,source_asset_id:card.id,form_version_ids:card.forms.filter(f=>f.version_id).map(f=>f.version_id)}}))};
   if(!batch.items.length)throw new Error('请至少选择一个目标项目');
   cache.put(key,batch);
   for(const item of batch.items){
    if(item.result)continue;
    try{item.result=await write('/asset-cards/copy',item.payload,'copy:'+card.id,item.project);item.error=null;}catch(e){item.error=e.message;}
    cache.put(key,batch);if(!live())return;
    setText(report,batch.items.map(r=>(ctx.projects().find(p=>p.id===r.project)?.name||'目标项目')+'：'+(r.result?'已复制':r.error||'等待')).join('\n'));
   }
   if(batch.items.every(r=>r.result)){cache.put(key,null);notice(msg('ui.copies_to_selected_projects_completed_source_asset_remains_target'));}
  });
 }

 async function generateForm(card,form){
  const key=draftKey(card.id)+':generation:'+form.form_key,state=cache.get(key)||{prompt:form.description||card.name+' · '+form.name,count:1,width:1024,height:1024},dialog=modal(msg('ui.generate_missing_image_value0_value1',{value0:card.name,value1:form.name})),valid=()=>live()&&dialog.isConnected;
  const prompt=field(dialog,msg('ui.prompt_for_this_form_s_missing_image'),state.prompt,'textarea'),models=field(dialog,msg('ui.missing_image_model'),'','select'),count=field(dialog,msg('ui.missing_image_candidate_count'),String(state.count));
  count.type='number';count.min='1';count.max='4';
  const aspect=field(dialog,msg('ui.missing_image_aspect_ratio'),'','select');
  for(const [label,value]of [[msg('ui.square'),'1024,1024'],[msg('ui.portrait_arrays_55'),'1024,1536'],[msg('ui.landscape'),'1536,1024']])aspect.append(localizedOption(value,label));
  aspect.value=state.width+','+state.height;
  const report=el('p'),results=el('div',null,'asset-card-generation-results');dialog.append(report,results);
  let quote=null,request=null,timer=null,revisionToken=0;
  const retain=()=>{state.prompt=prompt.value;state.model=models.value;state.count=Number(count.value);[state.width,state.height]=aspect.value.split(',').map(Number);cache.put(key,state);};
  const scope=createRunScopeControls(dialog,{api:ctx.api,session:ctx.session,projectId,onChange:()=>{quote=null;confirm.disabled=true;revisionToken++;}});
  dialog.addEventListener('close',()=>{clearTimeout(timer);scope.dispose();},{once:true});
  const changed=()=>{retain();quote=null;confirm.disabled=true;revisionToken++;};
  for(const input of [prompt,models,count,aspect])input.addEventListener('input',changed);
  button(dialog,msg('ui.check_the_quote_for_this_form_s_image'),async()=>{
   retain();if(state.pending)throw new Error('原补图请求回执未确认，请先恢复原补图请求。提示词修改已保留。');
   const token=++revisionToken;quote=null;confirm.disabled=true;
   if(!state.prompt.trim()||!state.model)throw new Error('请填写补图提示词并选择已配置模型');
   if(!Number.isInteger(state.count)||state.count<1||state.count>4)throw new Error('每次生成1–4个候选');
   const document={nodes:[{id:'output',type:'image',title:form.name,text:state.prompt,x:360,y:120}],edges:[]};
   if(form.media_id){document.nodes.unshift({id:'reference',type:'image',title:'当前形态参考',media_id:form.media_id,x:0,y:120});document.edges.push({id:'reference-edge',source:'reference',target:'output',port:'reference'});}
   const signature=JSON.stringify({document,model:state.model,count:state.count,width:state.width,height:state.height});
   if(!state.canvas||state.signature!==signature){const canvas=await write('/creative-canvases',{title:'资产补图 · '+card.name+' · '+form.name,episode_id:episode||null,document},'form-canvas:'+card.id+':'+form.form_key);state.canvas=canvas;state.signature=signature;state.fixed=null;cache.put(key,state);}
   if(!valid()||token!==revisionToken)return;
   if(!state.fixed){state.fixed=await write('/creative-canvases/'+state.canvas.id+'/work-input',{canvas_revision:state.canvas.canvas_revision,node_id:'output',model_id:state.model,shot_id:null,count:state.count,width:state.width,height:state.height,duration_ms:5000},'form-input:'+state.canvas.id);cache.put(key,state);}
   if(!valid()||token!==revisionToken)return;
   request=scope.apply({draft_version_id:state.fixed.draft_version_id,execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(Date.now()+3600000).toISOString(),stop_submitting_at:new Date(Date.now()+7200000).toISOString(),max_attempts_per_purpose:1,max_repair_rounds:0}});
   quote=await ctx.api(base()+'/creative-canvases/'+state.canvas.id+'/work-quote',{method:'POST',headers:headers(),body:JSON.stringify({payload:request})});
   if(!valid()||token!==revisionToken)return;update(quote.revision);
   if(!quote.ready){setText(report,quote.gaps.map(g=>g.message||g.code).join('；'));return;}
   setText(report,msg('ui.inputs_usable_generate_value0_candidates_value1_value2',{value0:state.count,value1:Object.entries(quote.generation_quote?.native_units||{}).map(([k,v])=>({images:'图像次数',remote_jobs:'远端任务',video_seconds:'视频秒数',audio_jobs:'音频任务'}[k]||k)+' '+v).join(' · '),value2:quote.generation_quote?.all_prices_known?'':msg('ui.some_prices_unknown')}));
   confirm.disabled=false;
  });
  const confirm=button(dialog,msg('ui.confirm_quote_and_generate_missing_image'),async()=>{if(!quote||confirm.disabled)return;confirm.disabled=true;state.pending={canvas_revision:state.canvas.canvas_revision,node_id:'output',request,preview_sha256:quote.preview_sha256};cache.put(key,state);recoverBtn.disabled=false;await submit();},true);
  async function submit(){if(!state.pending)throw new Error('没有待恢复的补图请求');const result=await write('/creative-canvases/'+state.canvas.id+'/generate',state.pending,'form-generate:'+state.canvas.id);state.run=result;state.pending=null;cache.put(key,state);if(valid()){setText(report,msg('ui.missing_image_task_registered_loading_the_original_task'));await refreshResults();}}
  const recoverBtn=button(dialog,msg('ui.recover_original_missing_image_request'),submit,!state.pending);
  button(dialog,msg('ui.refresh_missing_image_candidates'),refreshResults);
  async function refreshResults(){
   clearTimeout(timer);if(!state.fixed||!valid())return;
   const data=await ctx.api(base()+'/working-candidates?'+new URLSearchParams({shot_id:state.fixed.shot_id,output_kind:'image',offset:'0',limit:'100'}));
   if(!valid())return;update(data.revision);results.replaceChildren();
   for(const media of data.items){
    const box=el('article');mediaVisual(box,media.media_id,'image',form.name);box.append(el('p',media.name));
    button(box,msg('ui.use_as_this_form_s_main_image'),async()=>{
     const current=await ctx.api(base()+'/asset-cards/'+card.id);
     if(current.revision!==card.revision)throw new Error('资产卡已有新修改，请关闭后重开比较，候选保留。');
     const payload={asset_id:card.id,name:card.name,asset_kind:card.asset_kind,base_revision:card.revision,forms:card.forms.map(f=>({form_key:f.form_key,name:f.name,base_version_id:f.version_id,description:f.description,media_id:f.form_key===form.form_key?media.media_id:f.media_id,voice_spec_id:f.voice_spec_id}))};
     await write('/asset-cards',payload,'generated-form:'+card.id+':'+form.form_key);
     if(valid()){dialog.close();await refreshOptions();await load();notice(msg('ui.generated_image_fixed_as_the_form_s_new_main'));}
    });
    results.append(box);
   }
   if(state.run?.jobs?.length){
    const jobs=await Promise.all(state.run.jobs.map(j=>ctx.api(base()+'/production-platform/jobs/'+j.id)));
    if(!valid())return;
    const names={created:'排队中',queued:'排队中',claimed:'等待执行',submitted:'已提交',running:'生成中',succeeded:'已完成',failed:'失败',cancelled:'已取消',submission_unknown:'待恢复'};
    setText(report,msg('ui.image_generation_tasks_value0',{value0:jobs.map(j=>names[j.status]||j.status).join('、')}));
    if(jobs.some(j=>['created','queued','claimed','submitted','running','polling'].includes(j.status)))timer=setTimeout(()=>refreshResults().catch(e=>notice(e.message)),3000);
   }
  }
  const opts=await ctx.api(base()+'/creative-canvas-run-options');if(!valid())return;update(opts.revision);
  for(const m of opts.models.filter(m=>m.enabled&&m.modality==='image'))models.append(localizedOption(m.id,m.name||m.model_key));
  if(state.model)models.value=state.model;else state.model=models.value;
  await refreshResults();
 }

 function cardActions(card,parent){
  button(parent,'进入生成工作台',()=>enterFullEditor({card}));
  button(parent,msg('common.edit'),()=>edit(card));
  button(parent,card.favorite?msg('common.unfavorite'):msg('common.favorite'),async()=>{await write('/asset-cards/favorite',{asset_id:card.id,active:!card.favorite},'favorite:'+card.id);if(live())await load();});
  button(parent,'移动到文件夹',()=>openMoveFolderDialog([card]));
  button(parent,msg('ui.reference_in_episodes'),()=>chooseEpisodes(card));
  button(parent,msg('asset.copy_to_project'),()=>copyTargets(card));
  button(parent,msg('ui.view_uses'),async()=>{const d=modal(msg('ui.uses_value0',{value0:card.name}));await impact(d,card);});
  button(parent,msg('ui.move_to_recycle_bin_337'),()=>recycle([card]));
 }

 async function recycle(cards){
  if(!cards.length)return;
  const d=modal(cards.length===1?msg('ui.trash_asset_value0',{value0:cards[0].name}):`回收所选 ${cards.length} 个资产`),report=el('p');
  d.append(report);
  for(const card of cards.slice(0,8)){d.append(el('h3',card.name));await impact(d,card);if(!live()||!d.isConnected)return;}
  if(cards.length>8)d.append(el('p',`其余 ${cards.length-8} 个资产将在同一批次移入项目回收站。`));
  button(d,msg('ui.confirm_recycling'),async()=>{
   if(cards.length>1){
    await write('/asset-cards/batch-recycle',{asset_ids:cards.map(c=>c.id),reason:'用户核对引用后批量移入回收站'},`batch-trash:${cards.map(c=>c.id).join(',')}`);
    for(const c of cards)selected.delete(c.id);
   }else{
    const card=cards[0];
    await write('/management',{operation:'trash',target_type:'object',target_id:card.id,reason:'用户核对实际引用后从资产卡移入回收'},'trash:'+card.id);
    selected.delete(card.id);
   }
   if(live()){d.close();await refreshOptions();await load();}
  });
 }

 function preview(card){
  const d=modal(card.name);d.classList.add('asset-card-preview-dialog');
  if(card.record_kind==='blocking'){
   if(card.preview?.media_id)mediaVisual(d,card.preview.media_id,'image',card.name);
   else d.append(el('p','素材当前不可预览'));
   return;
  }
  const openEditorCta=button(d,'进入全屏生成工作台',()=>{d.close();enterFullEditor({card});});
  openEditorCta.className='asset-editor-save-btn';
  if(card.preview?.media_id&&!card.forms.some(f=>f.media_id)){
   const selectedSec=el('section',null,'asset-card-legacy-preview');
   selectedSec.append(el('h3','已选参考图'));
   mediaVisual(selectedSec,card.preview.media_id,'image',card.name);
   const form=legacyPreviewForm(card);
   selectedSec.append(el('p',form?'该图片来自已有选片，可填入形态主图后保存。':'该图片来自已有选片；请在编辑中选择对应形态的主图。'));
   if(form)button(selectedSec,'用此图编辑主图',()=>{d.close();edit(card,{form_key:form.form_key,media_id:card.preview.media_id});});
   d.append(selectedSec);
  }
  const forms=el('div',null,'asset-card-form-list');
  for(const f of card.forms){
   const row=el('section');row.append(el('h3',f.name));
   mediaVisual(row,f.media_id,card.asset_kind==='voice'?'audio':'image',f.name);
   if(f.description)row.append(el('p',f.description));
   const actions=el('div',null,'asset-card-actions');
   if(card.asset_kind!=='voice')button(actions,msg('ui.generate_missing_image'),()=>generateForm(card,f));
   if(f.media_id){
    if(card.asset_kind!=='voice')button(actions,'查看大图',()=>openAssetImageViewer({title:`${card.name} · ${f.name}`,src:base()+'/media/'+f.media_id+'/content',host:document.body||root}));
    const a=el('a',msg('common.download'));a.href=base()+'/media/'+f.media_id+'/content';a.download=f.name;actions.append(a);
    button(actions,msg('ui.send_to_canvas'),async()=>{
     const canvas=await write('/creative-canvases',{episode_id:episode||null,title:card.name+' · '+f.name,document:{nodes:[{id:'asset-'+crypto.randomUUID().slice(0,8),type:card.asset_kind==='voice'?'audio':'image',title:f.name,x:120,y:120,media_id:f.media_id}],edges:[]}},'canvas:'+f.version_id);
     if(live())await ctx.navigate('creative-canvas',null,projectId,{task_target:canvas.id,...(episode?{episode}:{})});
    });
   }
   if(f.voice_spec_id||f.voice_reference_media_id)row.append(el('small',msg('ui.linked_voice')));
   row.append(actions);forms.append(row);
  }
  d.append(forms);
  const tools=el('div',null,'asset-card-actions');cardActions(card,tools);d.append(tools);
 }

 function attachDropTarget(targetNode,targetFolderId){
  targetNode.addEventListener('dragover',e=>{
   e.preventDefault();
   targetNode.setAttribute('data-drop-hover','true');
  });
  targetNode.addEventListener('dragleave',()=>targetNode.removeAttribute('data-drop-hover'));
  targetNode.addEventListener('drop',async e=>{
   e.preventDefault();
   targetNode.removeAttribute('data-drop-hover');
   let parsed=null;
   try{parsed=JSON.parse(e.dataTransfer?.getData('application/x-vsc-asset-move')||'null');}catch{}
   if(!parsed||!Array.isArray(parsed.asset_ids)||!parsed.asset_ids.length)return;
   if(parsed.project_id&&parsed.project_id!==projectId){
    notice('跨项目不支持拖拽移动');
    return;
   }
   try{
    await write('/asset-cards/folders/move',{
     folder_id:targetFolderId||null,
     asset_ids:parsed.asset_ids,
     source_project_id:parsed.project_id||projectId,
    },`drag-move:${Date.now()}`);
    await refreshOptions();
    if(live()){await load();notice('资产已移入目标文件夹');}
   }catch(err){notice(err.message);}
  });
 }

 function folderCardView(folder,parent){
  const box=el('article',null,'asset-folder-card');
  const cover=el('button','','asset-folder-cover');
  cover.type='button';
  bindAttribute(cover,'aria-label',`打开文件夹 ${folder.title}`);
  cover.onclick=()=>{folderId=folder.id;offset=0;selected.clear();load();};
  if(folder.cover_media_id){
   mediaVisual(cover,folder.cover_media_id,'image',folder.title);
  }else if((folder.cover_media_ids||[]).length){
   const collage=el('div',null,'asset-folder-collage');
   for(const mid of folder.cover_media_ids.slice(0,4))mediaVisual(collage,mid,'image',folder.title);
   cover.append(collage);
  }else{
   cover.append(el('span','📁','asset-folder-icon'));
  }
  cover.append(el('span',`${folder.asset_count||0} 项`,'asset-folder-count'));
  const info=el('div',null,'asset-folder-info');
  const openTitle=button(info,folder.title,()=>{folderId=folder.id;offset=0;selected.clear();load();});
  openTitle.className='asset-folder-title-btn';
  const menu=el('details',null,'asset-folder-menu');
  menu.append(el('summary','⋯'));
  const actions=el('div',null,'asset-card-actions');
  button(actions,'编辑名称/封面',()=>openFolderDialog(folder));
  button(actions,'删除文件夹',()=>confirmDeleteFolder(folder));
  menu.append(actions);
  info.append(menu);
  box.append(cover,info);
  attachDropTarget(box,folder.id);
  parent.append(box);
 }

 function cardView(card,parent){
  const box=el('article',null,'asset-card'),cover=el('div',null,'asset-card-cover'),first=card.forms.find(f=>f.media_id);
  if(card.record_kind!=='blocking'){
   box.draggable=true;
   box.addEventListener('dragstart',e=>{
    box.setAttribute('data-dragging','true');
    const ids=selected.has(card.id)?Array.from(selected):[card.id];
    e.dataTransfer?.setData('application/x-vsc-asset-move',JSON.stringify({project_id:projectId,asset_ids:ids}));
   });
   box.addEventListener('dragend',()=>box.removeAttribute('data-dragging'));
  }
  if(first&&card.asset_kind==='voice')mediaVisual(cover,first.media_id,'audio',card.name);
  else{
   const open=button(cover,'',()=>preview(card));open.className='asset-card-preview';bindAttribute(open,'aria-label',msg('gallery.preview',{name:card.name}));
   if(first)mediaVisual(open,first.media_id,'image',card.name);
   else if(card.preview?.media_id)mediaVisual(open,card.preview.media_id,'image',card.name);
   else open.append(el('span',kinds[card.asset_kind==='object'?'prop':card.asset_kind]));
  }
  const badge=el('span',card.record_kind==='blocking'?msg('gallery.blocking'):kinds[card.asset_kind==='object'?'prop':card.asset_kind],'asset-card-kind');
  cover.append(badge);
  if(batchMode&&card.record_kind!=='blocking'){
   const check=el('input');check.type='checkbox';check.checked=selected.has(card.id);check.className='asset-card-check';
   bindAttribute(check,'aria-label',msg('ui.select_value0',{value0:card.name}));
   check.onchange=()=>{check.checked?selected.add(card.id):selected.delete(card.id);drawBatchBar();};
   cover.append(check);
  }
  if(card.record_kind!=='blocking'&&!batchMode){
   const hoverBar=el('div',null,'asset-card-hover-bar');
   button(hoverBar,'编辑',()=>enterFullEditor({card}));
   button(hoverBar,'移动',()=>openMoveFolderDialog([card]));
   button(hoverBar,'删除',()=>recycle([card]));
   cover.append(hoverBar);
  }
  const info=el('div',null,'asset-card-info'),title=el('h3'),open=button(title,card.name,()=>preview(card));
  bindAttribute(open,'title',card.name);info.append(title);
  if(card.record_kind!=='blocking'){
   const menu=el('details',null,'asset-card-menu');menu.append(el('summary','⋯'));
   bindAttribute(menu,'aria-label',msg('ui.edit_value0',{value0:card.name}));
   const tools=el('div',null,'asset-card-actions');cardActions(card,tools);menu.append(tools);info.append(menu);
  }
  box.append(cover,info);parent.append(box);
 }

 function episodeCard(asset,parent){
  const card=el('article',null,'asset-card');card.append(el('h3',asset.name));
  for(const f of asset.forms){const row=el('section');row.append(el('strong',f.name));mediaVisual(row,f.media_id,asset.asset_kind==='voice'?'audio':'image',f.name);card.append(row);}
  button(card,msg('ui.edit_episode_alias_and_form'),()=>{
   const dialog=modal(asset.name),draft=cache.get(draftKey('episode:'+asset.id))||clone(asset),name=field(dialog,msg('ui.episode_asset_name'),draft.name);
   const retain=()=>{draft.name=name.value;cache.put(draftKey('episode:'+asset.id),draft);};name.oninput=retain;
   for(const form of draft.forms){
    const title=field(dialog,msg('ui.episode_form_name'),form.name),media=field(dialog,msg('ui.episode_form_s_main_media'),'','select');
    media.append(localizedOption('',msg('ui.no_selection_for_now')));
    for(const m of (options?.media||[]).filter(m=>m.modality===(asset.asset_kind==='voice'?'audio':'image')))media.append(localizedOption(m.id,m.name));
    media.value=form.media_id||'';title.oninput=()=>{form.name=title.value;retain();};media.onchange=()=>{form.media_id=media.value||null;retain();};
   }
   button(dialog,msg('ui.save_episode_reference'),async()=>{
    retain();
    await write('/episode-assets',{id:draft.id,episode_id:episode,base_revision:draft.revision,asset_key:draft.asset_key,name:draft.name,asset_kind:draft.asset_kind,forms:draft.forms.map(f=>({form_key:f.form_key,name:f.name,base_version_id:f.current_version_id,source_asset_id:f.source_asset_id,spec_id:f.spec_id,media_id:f.media_id||null}))},'episode:'+draft.id);
    cache.put(draftKey('episode:'+draft.id),null);if(live()){dialog.close();await load();}
   });
  });
  if(asset.asset_key.startsWith('asset:'))button(card,msg('ui.refresh_project_form_reference'),async()=>{const source=await ctx.api(base()+'/asset-cards/'+asset.asset_key.slice(6));if(live())chooseEpisodes(source);});
  parent.append(card);
 }

 function batchImport(presetKind=''){
  const d=modal(msg('asset.batch_import_title'),'asset-batch-import-dialog');
  d.append(el('p','单次最多 200 个文件；图片支持 .jpg/.jpeg/.png（≤50MB、边长 ≤16383px），音频支持 .mp3/.wav/.m4a/.aac/.flac（≤100MB、时长 ≤1800s）。'));
  const type=field(d,msg('ui.imported_asset_type'),'','select');
  for(const k of ['character','location','prop','voice'])type.append(localizedOption(k,kinds[k]));
  if(presetKind)type.value=presetKind;
  else if(kind&&['character','location','prop','voice'].includes(kind))type.value=kind;
  const folderPick=field(d,'导入目标文件夹','','select');
  folderPick.append(localizedOption('','项目根目录'));
  for(const f of folders)folderPick.append(localizedOption(f.id,`📁 ${f.title}`));
  if(folderId)folderPick.value=folderId;
  const start=button(d,msg('ui.start_selecting_files'),()=>{
   type.disabled=true;folderPick.disabled=true;start.disabled=true;
   const host=el('section');d.append(host);
   const upload=createMediaUpload({
    root:host,api:ctx.api,project:projectId,session:ctx.session,onRevision:update,
    assetKind:type.value,episodeId:episode,
    accept:type.value==='voice'?'.mp3,.wav,.m4a,.aac,.flac,audio/*':'.jpg,.jpeg,.png,image/*',
    title:'批量导入项目资产（≤200项）',
    onComplete:async({assetId:newAssetId})=>{
     if(folderPick.value&&newAssetId){
      try{await write('/asset-cards/folders/move',{folder_id:folderPick.value,asset_ids:[newAssetId],source_project_id:projectId},`import-move:${newAssetId}`);}catch{}
     }
     await refreshOptions();
     notice(msg('ui.original_media_and_project_asset_card_registered_close_to'));
    }
   });
   uploads.add(upload);d.addEventListener('close',()=>{upload.suspend();uploads.delete(upload);if(live())load();},{once:true});upload.load();
  });
 }

 async function recover(){
  if(!live())return;
  const prefix=`vsc-asset-card-request:${actor}:${projectId}:`;
  for(let i=0;i<sessionStorage.length;i++){
   if(!live())return;
   const key=sessionStorage.key(i);if(!key.startsWith(prefix))continue;
   const request=cache.get(key),slot=key.slice(prefix.length);
   const path=slot.startsWith('form-')?null:request._path||(slot.startsWith('save:')?'/asset-cards':slot.startsWith('upload:')?'/media':slot.startsWith('reference:')?'/asset-cards/reference':slot.startsWith('episode:')?'/episode-assets':slot.startsWith('favorite:')?'/asset-cards/favorite':slot.startsWith('trash:')?'/management':null);
   if(!path)continue;
   await write(path,request.payload,slot);
   if(slot.startsWith('save:'))cache.put(draftKey(slot.slice(5)),null);
   if(slot.startsWith('episode:'))cache.put(draftKey(slot),null);
   i--;
  }
  if(live())await load();
 }

 function drawBatchBar(){
  root.querySelector('.asset-card-batch-bar')?.remove();
  if(!batchMode||mode!=='project')return;
  const editable=visibleCards.filter(c=>c.record_kind!=='blocking'),bar=el('div',null,'asset-card-batch-bar project-batch-bar'),label=el('label','全选本页'),all=el('input');
  all.type='checkbox';all.checked=editable.length>0&&editable.every(c=>selected.has(c.id));all.indeterminate=selected.size>0&&!all.checked;
  all.onchange=()=>{for(const c of editable)all.checked?selected.add(c.id):selected.delete(c.id);load();};
  label.prepend(all);bar.append(label,el('span','已选 '+selected.size+' 项'));
  button(bar,'全选所有页',async()=>{
   let cursor=0,baselineTotal=null;
   const collected=[];
   while(cursor!=null){
    const pageParams={query,asset_kind:kind,...projectAssetCategoryParams(kind),offset:String(cursor),limit:'100',favorites:String(favorite)};
    if(folderId)pageParams.folder_id=folderId;
    const page=await ctx.api(base()+'/asset-cards?'+new URLSearchParams(pageParams));
    if(baselineTotal===null)baselineTotal=page.total;
    else if(page.total!==baselineTotal)throw new Error('列表在扫描期间已变更，请重新全选');
    for(const item of page.items||[])if(item.record_kind!=='blocking')collected.push(item.id);
    cursor=page.next_offset;
   }
   for(const id of collected)selected.add(id);
   await load();
  });
  button(bar,'移动到文件夹',()=>openMoveFolderDialog(visibleCards.filter(c=>selected.has(c.id))),!selected.size);
  button(bar,msg('common.favorite'),async()=>{for(const c of visibleCards.filter(c=>selected.has(c.id))){await write('/asset-cards/favorite',{asset_id:c.id,active:true},'favorite:'+c.id);if(!live())return;}await load();},!selected.size);
  button(bar,msg('ui.move_to_recycle_bin_337'),()=>recycle(visibleCards.filter(c=>selected.has(c.id))),!selected.size);
  button(bar,msg('common.cancel'),()=>{batchMode=false;selected.clear();load();});
  root.append(bar);
 }

 async function load(){
  const read=++serial;
  officialCenter?.suspend();officialCenter=null;
  editorHandle?.suspend();editorHandle=null;
  root.querySelectorAll('dialog').forEach(d=>d.close());
  root.replaceChildren();
  syncCardsUrl();
  const tabs=el('nav',null,'asset-card-tabs');
  for(const [value,title]of [['project',msg('asset.project_source')],['official','官方资产']]){
   const b=button(tabs,title,()=>{tab=value;selected.clear();return load();});
   if(b.dataset)b.dataset.tab=value;
   b.setAttribute('data-tab',value);
   b.setAttribute('aria-pressed',String(tab===value));
  }
  link(tabs,msg('shell.shared_library'),'asset-center',{tab:'shared'});
  root.append(tabs,status);setText(status,'');
  if(tab==='official'){
   const host=el('section');root.append(host);
   officialCenter=createAssetCenter(host,{...ctx,projectId:()=>projectId,session:()=>({...ctx.session(),revision}),setRevision:(value,p)=>{if(!p||p===projectId)update(value);}},{source:'official',embedded:true});
   await officialCenter.load();return;
  }

  const toolbar=el('div',null,'asset-card-toolbar'),project=field(toolbar,msg('common.project'),'','select');
  for(const p of ctx.projects())if(!p.unavailable)project.append(localizedOption(p.id,p.name));
  project.value=projectId;project.onchange=()=>ctx.navigate('assets',null,project.value);project.parentElement.className='asset-card-project';

  const categories=el('nav',null,'asset-card-categories');
  for(const [value,title]of [['',msg('common.all')],['character','人设'],['location',msg('asset.scene')],['prop',msg('asset.prop')],['blocking',msg('gallery.blocking')],['voice','音频']]){
   const b=button(categories,title,()=>{kind=value;offset=0;selected.clear();return load();});
   b.setAttribute('aria-pressed',String(kind===value));
  }
  toolbar.append(categories);

  const count=el('span',null,'asset-card-count'),search=field(toolbar,msg('ui.search_assets'),query);
  search.type='search';search.parentElement.className='asset-card-search';bindAttribute(search,'placeholder','搜索资产…');
  const submit=()=>{clearTimeout(searchDebounce);query=search.value;offset=0;selected.clear();return load();};
  search.oninput=()=>{clearTimeout(searchDebounce);searchDebounce=setTimeout(()=>{query=search.value;offset=0;selected.clear();load();},300);};
  search.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();submit();}};
  button(toolbar,msg('ui.search'),submit).className='asset-card-search-submit';

  const sortSelect=field(toolbar,'排序','','select');
  sortSelect.parentElement.className='asset-card-sort';
  for(const [val,lbl]of [['','最新更新'],['name_asc','名称 A-Z'],['name_desc','名称 Z-A']]){
   sortSelect.append(localizedOption(val,lbl));
  }
  sortSelect.value=orderBy;
  sortSelect.onchange=()=>{orderBy=sortSelect.value;offset=0;load();};

  toolbar.append(count);
  if(mode==='project'&&!folderId){
   button(toolbar,'新建文件夹',()=>openFolderDialog());
  }
  const batch=button(toolbar,'批量操作',()=>{batchMode=!batchMode;selected.clear();return load();},mode!=='project');
  batch.setAttribute('aria-pressed',String(batchMode));
  button(toolbar,'批量导入',()=>batchImport());

  const more=el('details',null,'asset-card-options');more.append(el('summary','⋯'));
  const moreBody=el('div');
  const filter=field(moreBody,msg('asset.asset_type'),'','select');
  filter.append(localizedOption('',msg('asset.all_assets')));
  for(const[k,v]of Object.entries(kinds))filter.append(localizedOption(k,v));
  filter.append(localizedOption('blocking',msg('gallery.blocking')));
  filter.value=kind;filter.onchange=()=>{kind=filter.value;offset=0;selected.clear();load();};
  if(episode){
   const pick=field(moreBody,msg('ui.asset_scope'),'','select');
   pick.append(localizedOption('project',msg('asset.project_source')),localizedOption('episode',msg('ui.episode_reference')));
   pick.value=mode;pick.onchange=()=>{mode=pick.value;offset=0;selected.clear();load();};
  }
  button(moreBody,favorite?msg('ui.show_all'):msg('ui.favorites_only'),()=>{favorite=!favorite;offset=0;selected.clear();load();});
  button(moreBody,msg('ui.recover_unconfirmed_operation'),recover);
  more.append(moreBody);toolbar.append(more);root.append(toolbar);

  if(folderId&&mode==='project'){
   const projName=ctx.projects().find(p=>p.id===projectId)?.name||'当前项目';
   const fObj=folders.find(f=>f.id===folderId)||currentFolder||{id:folderId,title:'文件夹'};
   const crumb=el('div',null,'asset-folder-breadcrumb');
   const rootBtn=button(crumb,`← ${projName}`,()=>{folderId='';offset=0;selected.clear();load();});
   rootBtn.className='asset-breadcrumb-root';
   attachDropTarget(rootBtn,null);
   crumb.append(el('span','>','asset-breadcrumb-sep'),el('strong',fObj.title));
   button(crumb,'编辑文件夹',()=>openFolderDialog(fObj));
   button(crumb,'删除文件夹',()=>confirmDeleteFolder(fObj));
   root.append(crumb);
  }

  const grid=el('div',null,'asset-card-grid');root.append(grid);
  if(mode==='project'){
   const create=button(grid,'',()=>openSmartCreateEntry());
   create.className='asset-card-create';
   create.append(el('span','＋'),el('strong',msg('asset.create_asset')),el('small',kind?`新建${TYPE_LABELS[KIND_TO_TYPE_NUM[kind]]||'资产'}`:'选择类型'));
  }

  try{
   if(mode==='episode'){
    const data=await ctx.api(base()+'/episode-assets?episode_id='+episode);
    if(!live()||read!==serial)return;update(data.revision);
    const items=data.items.filter(a=>(!kind||a.asset_kind===kind||kind==='prop'&&a.asset_kind==='object')&&a.name.includes(query));
    setText(count,'共'+items.length+'个资产');
    for(const a of items)episodeCard(a,grid);
    if(!items.length)grid.append(el('p',msg('ui.choose_reference_in_episodes_from_a_project_asset_first'),'asset-card-empty'));
    return;
   }
   const listParams={query,asset_kind:kind,...projectAssetCategoryParams(kind),offset:String(offset),limit:'24',favorites:String(favorite)};
   if(folderId)listParams.folder_id=folderId;
   if(orderBy)listParams.order_by=orderBy;
   const data=await ctx.api(base()+'/asset-cards?'+new URLSearchParams(listParams));
   if(!live()||read!==serial)return;
   update(data.revision);
   if(Array.isArray(data.folders))folders=data.folders;
   currentFolder=data.current_folder||null;
   if(!folderId&&offset===0&&!favorite&&!kind){
    for(const f of folders.filter(x=>!query||x.title.includes(query)))folderCardView(f,grid);
   }
   visibleCards=data.items;
   setText(count,'共'+data.total+'个资产');
   for(const c of data.items)cardView(c,grid);
   drawBatchBar();
   if(data.total>24){
    const paging=el('div',null,'asset-card-pagination');
    button(paging,msg('common.previous_page'),()=>{offset=Math.max(0,offset-24);selected.clear();load();},offset===0);
    paging.append(el('span',msg('ui.value0_items_in_total',{value0:data.total})));
    button(paging,msg('common.next_page'),()=>{offset=data.next_offset;selected.clear();load();},data.next_offset==null);
    root.append(paging);
   }
  }catch(e){if(live()&&read===serial){notice(e.message);button(root,msg('ui.reload'),load);}}
 }

 await refreshOptions();
 if(!live())return {suspend(){active=false;}};
 let node=(options?.nodes||[]).find(n=>n.id===objectId);
 while(node&&node.kind!=='episode')node=(options?.nodes||[]).find(n=>n.id===node.parent_id);
 episode=node?.id||null;

 const urlParams=typeof location!=='undefined'?new URLSearchParams(location.search):new URLSearchParams();
 const urlWantsEditor=initialAction==='editor'||urlParams.get('subview')==='editor'||(typeof location!=='undefined'&&location.pathname==='/character/create');
 if(urlWantsEditor){
  const urlType=Number(initialAssetType||urlParams.get('asset_type')||urlParams.get('type')||1)||1;
  const targetId=assetId||urlParams.get('asset_id')||null;
  let targetCard=null;
  if(targetId)targetCard=await ctx.api(base()+'/asset-cards/'+encodeURIComponent(targetId));
  if(live())await enterFullEditor({card:targetCard,assetType:urlType});
 }else{
  await load();
  if(live()&&initialAction){
   if(initialAction==='create')edit();
   else if(initialAction==='import')batchImport();
   else if(assetId){
    const card=await ctx.api(base()+'/asset-cards/'+encodeURIComponent(assetId));
    if(live()){
     if(initialAction==='edit')edit(card);
     else if(initialAction==='copy')copyTargets(card);
     else if(initialAction==='preview')preview(card);
     else if(initialAction==='recycle')recycle([card]);
    }
   }
  }
 }

 return {
  suspend(){
   active=false;serial++;
   clearTimeout(searchDebounce);
   officialCenter?.suspend();
   editorHandle?.suspend();
   for(const u of uploads)u.suspend();
   uploads.clear();
   root.querySelectorAll('dialog').forEach(d=>d.close());
  }
 };
}
