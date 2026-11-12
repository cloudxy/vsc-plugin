import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Editable first cut. The server owns revisions, media references and exports. */
import {openEditHandoff} from './edit-handoff.js';
import {createEditPlayback} from './edit-playback.js';
const element=(tag,text='',cls='')=>{const node=document.createElement(tag);setText(node,text);if(cls)node.className=cls;return node;};
const input=(label,value,type='number')=>{const wrap=element('label',label),field=element('input');field.type=type;field.value=value;wrap.append(field);return {wrap,field};};
const empty=()=>({format:'vsc.edit-workspace/v1',width:720,height:1280,fps:24,clips:[],audio:[],captions:[]});
const copy=value=>JSON.parse(JSON.stringify(value));
// PostgreSQL JSON objects may return keys in a different order. Array order and
// every value remain significant when confirming an already-saved document.
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const sameDocument=(left,right)=>JSON.stringify(canonical(left))===JSON.stringify(canonical(right));

export function createEditWorkspace({root,api,project,episodeId,session,onChange,onArtifact,autoSave=false,multiClipGuard=false,onMultiClipBlocked=null}){
  let generation=0,view=null,draft=empty(),draftRevision=0,media=[],mediaTotal=0,dirty=false,editEpoch=0,undo=[],redo=[],poll=null,autoSaveTimer=null,guideDismissed=false,disposed=false,mounted=false,previewIndex=0,previewPlayer=null;
  let playback=null,seed=null,batchMode=false,selectedSources=new Set(),selectedClips=new Set(),loadedMediaCount=0,candidates=[],candidateTotal=0,nextCandidateOffset=null,candidateLoading=false;
  const base=`/api/v1/projects/${encodeURIComponent(project)}`;
  const initialIdentity=typeof session==='function'?session():session||{};
  const operator=initialIdentity.identityId||initialIdentity.actor||'read-only';
  const recoveryKey=`vsc.edit-draft:${operator}:${project}:${episodeId}`,requestKey=recoveryKey+':requests',captionKey=recoveryKey+':unapplied-srt';let pending={},captionText=null,captionDirty=false,captionsOpen=false;
  try{const retained=JSON.parse(sessionStorage.getItem(captionKey)||'null');if(typeof retained?.text==='string'){captionText=retained.text;captionDirty=true;captionsOpen=true;}}catch{}
  try{pending=JSON.parse(sessionStorage.getItem(requestKey)||'{}');}catch{}
  const retainRequests=()=>{try{sessionStorage.setItem(requestKey,JSON.stringify(pending));}catch{error('浏览器无法保存操作回执，请保持当前页面并恢复操作后再关闭。');}};
  function confirmRequest(path,intent){
    if(pending[path]?.idempotency_key===intent.idempotency_key)delete pending[path];
    // A late response from an unmounted instance must not erase a newer intent.
    try{const stored=JSON.parse(sessionStorage.getItem(requestKey)||'{}');if(stored[path]?.idempotency_key===intent.idempotency_key){delete stored[path];sessionStorage.setItem(requestKey,JSON.stringify(stored));}}catch{error('浏览器无法保存操作回执，请保持当前页面并恢复操作后再关闭。');}
  }
  try{const saved=JSON.parse(sessionStorage.getItem(recoveryKey)||'null');if(saved?.document?.format==='vsc.edit-workspace/v1'&&Number.isInteger(saved.edit_revision)){draft=saved.document;draftRevision=saved.edit_revision;dirty=true;}}catch{}
  function stash(){try{if(dirty)sessionStorage.setItem(recoveryKey,JSON.stringify({document:draft,edit_revision:draftRevision}));else sessionStorage.removeItem(recoveryKey);}catch{error('浏览器恢复空间不可用，请保存当前工作稿后再离开。');}}
  const identity=()=>typeof session==='function'?session():session||{};
  const sameIdentity=()=>(identity().identityId||identity().actor||'read-only')===operator;
  const writable=()=>sameIdentity()&&identity().actor&&identity().writable;
  function stashCaption(){try{if(captionDirty)sessionStorage.setItem(captionKey,JSON.stringify({text:captionText}));else sessionStorage.removeItem(captionKey);}catch{error('未应用字幕无法写入浏览器恢复空间，请保持此页。');}}
  function captionDocument(){const clock=frame=>{let ms=Math.round(frame*1000/draft.fps);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};return draft.captions.map((c,i)=>`${i+1}\n${clock(c.start_frame)} --> ${clock(c.end_frame)}\n${c.text}`).join('\n\n');}
  function captureCaption(){if(!mounted)return;const field=root.querySelector('.edit-srt');if(field&&field.value!==captionText){captionText=field.value;captionDirty=captionText!==captionDocument();stashCaption();}}
  function error(message){if(disposed||!sameIdentity())return;const out=root.querySelector('.edit-notice');if(out){setText(out,message);out.setAttribute('role','alert');}}
  function scheduleAutoSave(){
    if(!autoSave)return;
    clearTimeout(autoSaveTimer);
    autoSaveTimer=setTimeout(()=>{
      if(!disposed&&sameIdentity()&&writable()&&dirty&&view&&!pending['/edit-workspace']){
        save().catch(e=>error(e.message));
      }
    },1500);
  }
  function mutate(change){undo.push(copy(draft));if(undo.length>50)undo.shift();redo=[];change();editEpoch++;dirty=true;stash();draw();scheduleAutoSave();}
  async function write(path,payload){
    const auth=identity();if(!writable())throw new Error('请先建立可写的本机操作会话。');
    if(!sameIdentity())throw new Error('操作身份已切换，请重新打开本集剪辑。');
    let intent=pending[path];
    if(intent&&!sameDocument(intent.payload,payload))throw new Error('上次操作的响应尚未确认，请先“恢复未确认操作”；当前修改会保留。');
    if(!intent){intent={payload,expected_revision:view.project_revision,idempotency_key:crypto.randomUUID()};pending[path]=intent;retainRequests();}
    let result;
    try{result=await api(base+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth.csrf},body:JSON.stringify(intent)});confirmRequest(path,intent);}
    catch(failure){if(failure.status&&failure.status<500)confirmRequest(path,intent);throw failure;}
    if(disposed||!sameIdentity())return result;view.project_revision=result.revision??view.project_revision;onChange?.(result);return result;
  }
  async function save(){
    if(!view)throw new Error('剪辑尚未载入');
    if(!dirty&&view.current&&!pending['/edit-workspace'])return currentReceipt();
    const savedEpoch=editEpoch,savedDocument=copy(draft),basedOn=draftRevision;
    let result;
    try{result=await write('/edit-workspace',{episode_id:episodeId,edit_revision:basedOn,document:savedDocument});}
    catch(failure){
      if(failure.status===409&&!disposed&&sameIdentity()){
        // A response may have been lost although this exact document committed.
        // Only an equal authoritative read can resolve that conflict locally.
        try{await load();}catch{}
        if(!dirty&&sameDocument(draft,savedDocument))return currentReceipt();
      }
      throw failure;
    }
    if(disposed||!sameIdentity()){
      // A receipt belongs to this fixed scope even after navigation. Reconcile
      // only its matching local base; never repaint another scope or replace
      // text typed after submission. A remounted instance keeps its own pending
      // intent and can recover the same receipt while this response is in flight.
      try{const retained=JSON.parse(sessionStorage.getItem(recoveryKey)||'null');if(retained?.edit_revision===basedOn){if(sameDocument(retained.document,savedDocument))sessionStorage.removeItem(recoveryKey);else sessionStorage.setItem(recoveryKey,JSON.stringify({...retained,edit_revision:result.edit_revision}));}}catch{}
      return result;
    }
    draftRevision=result.edit_revision;dirty=editEpoch!==savedEpoch;stash();await load();return result;
  }
  function currentReceipt(){return {id:view.workspace.id,edit_revision:view.workspace.revision,edit_version_id:view.current.id,revision:view.project_revision};}
  function reconcileRead(data){
    const intent=pending['/edit-workspace'];
    if(data.current&&sameDocument(draft,data.current.document)){
      dirty=false;
      if(intent?.payload.episode_id===episodeId&&sameDocument(intent.payload.document,data.current.document))confirmRequest('/edit-workspace',intent);
    }
    if(!dirty){draft=copy(data.current?.document||empty());draftRevision=data.workspace?.revision||0;stash();}
  }
  function button(title,action,disabled=false){const b=element('button',title);b.type='button';b.disabled=disabled;b.addEventListener('click',async()=>{b.disabled=true;try{await action();}catch(e){error(e.message);}finally{if(b.isConnected)b.disabled=disabled;}});return b;}
  function name(id){return media.find(m=>m.id===id)?.name||'已固定的素材';}
  function attach(item,track){
    const frames=Math.max(1,Math.floor((item.duration_ms||3000)*draft.fps/1000));
    mutate(()=>draft[track].push({id:crypto.randomUUID(),media_id:item.id,in_frame:0,out_frame:frames,volume:track==='audio'?.25:1,muted:false,...(track==='audio'?{at_frame:0,fade_in:0,fade_out:0}:{})}));
  }
  function previewClip(index,play=false){
    if(!draft.clips[index]||!playback)return;previewIndex=index;playback.clip(index,play);
  }
  function trimClip(clip){
    const dialog=element('dialog','','edit-trim-dialog'),heading=element('header'),video=element('video');heading.append(element('h3',msg("common.clip_video")),button(msg("common.close"),()=>dialog.close()));video.controls=true;video.preload='metadata';video.src=base+'/media/'+encodeURIComponent(clip.media_id)+'/content';
    const from=input(msg("agent.overseas_remake_start_seconds"),(clip.in_frame/draft.fps).toFixed(3)),to=input(msg("agent.overseas_remake_end_seconds"),(clip.out_frame/draft.fps).toFixed(3));from.field.step=to.field.step=String(1/draft.fps);from.field.min=to.field.min='0';video.addEventListener('loadedmetadata',()=>{video.currentTime=clip.in_frame/draft.fps;});from.field.addEventListener('input',()=>{video.currentTime=Number(from.field.value);});
    const problem=element('p','','edit-trim-notice');problem.setAttribute('role','alert');const controls=element('div','','edit-trim-controls');controls.append(from.wrap,to.wrap,button(msg("common.cancel"),()=>dialog.close()),button(msg("common.confirm"),()=>{const start=Math.round(Number(from.field.value)*draft.fps),end=Math.round(Number(to.field.value)*draft.fps);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||Number.isFinite(video.duration)&&end>Math.ceil(video.duration*draft.fps)){setText(problem,msg("ui.trim_must_stay_within_the_source_clip_with_the"));return;}dialog.close();mutate(()=>{clip.in_frame=start;clip.out_frame=end;});},!writable()));dialog.append(heading,video,controls,problem);dialog.addEventListener('close',()=>{video.pause();dialog.remove();});root.append(dialog);dialog.showModal();
  }
  const candidateKey=clip=>clip.shot_id+':'+clip.media_id;
  function sourceClip(clip){return {id:crypto.randomUUID(),shot_id:clip.shot_id,media_id:clip.media_id,in_frame:Math.round(clip.trim_in_ms*draft.fps/1000),out_frame:Math.round(clip.trim_out_ms*draft.fps/1000),volume:1,muted:false,...(clip.working_selection_version_id?{working_selection_version_id:clip.working_selection_version_id}:{})};}
  async function loadCandidates(append=false){
    const current=generation,offset=append?nextCandidateOffset:0;if(offset==null||candidateLoading)return;candidateLoading=true;
    try{const result=await api(`${base}/edit-candidates?`+new URLSearchParams({episode_id:episodeId,offset,limit:48}));if(disposed||!sameIdentity()||current!==generation)return;
      candidates=append?[...candidates,...result.items]:result.items;candidateTotal=result.total;nextCandidateOffset=result.next_offset;
      for(const item of result.items)if(!media.some(m=>m.id===item.id))media.push(item);
    }finally{candidateLoading=false;if(!disposed&&sameIdentity()&&current===generation)draw();}
  }
  function renderSources(host){
    const section=element('section','','edit-selected-sources');
    section.append(element('h3',msg("ui.episode_video_candidates_value0",{value0:candidateTotal})),button(batchMode?msg("ui.cancel_batch_placement"):msg("ui.batch_placement"),()=>{batchMode=!batchMode;selectedSources.clear();draw();},!writable()||!candidates.length));
    const available=candidates.filter(clip=>clip.can_add&&!draft.clips.some(existing=>existing.media_id===clip.media_id&&existing.shot_id===clip.shot_id));
    if(batchMode){const batch=element('div','','edit-source-batch');batch.append(button(msg("ui.select_all_loaded_candidates"),()=>{selectedSources=new Set(available.map(candidateKey));draw();}),button(msg("ui.invert_loaded_candidate_selection"),()=>{selectedSources=new Set(available.filter(c=>!selectedSources.has(candidateKey(c))).map(candidateKey));draw();}),button(msg("ui.place_value0_selected_clips_on_tracks",{value0:selectedSources.size}),()=>{mutate(()=>{for(const clip of available)if(selectedSources.has(candidateKey(clip)))draft.clips.push(sourceClip(clip));});batchMode=false;selectedSources.clear();draw();},!selectedSources.size));section.append(batch);}
    const groups=new Map();for(const clip of candidates){if(!groups.has(clip.shot_id))groups.set(clip.shot_id,[]);groups.get(clip.shot_id).push(clip);}
    for(const clips of groups.values()){
      const group=element('section','','edit-source-group'),first=clips[0],cards=element('div','','edit-source-cards');group.append(element('h4',msg("ui.shot_value0_value1",{value0:first.shot_number,value1:first.shot_title||first.shot_code})),cards);
      for(const [index,clip]of clips.entries()){
        const card=element('article','','edit-source-card'),added=draft.clips.some(c=>c.media_id===clip.media_id&&c.shot_id===clip.shot_id),thumbnail=element('video');thumbnail.src=clip.content_url;thumbnail.preload='metadata';thumbnail.muted=true;bindAttribute(thumbnail,'aria-label',msg("ui.preview_shot_value0_candidate_value1",{value0:clip.shot_number,value1:index+1}));
        thumbnail.controls=true;card.append(thumbnail,element('span',clip.name||msg("ui.candidate_value0",{value0:index+1}),'edit-source-name'),element('span',clip.duration_ms?msg("ui.value0_seconds_value1",{value0:(clip.duration_ms/1000).toFixed(2),value1:clip.selected?msg("ui.current_selection"):''}):msg("ui.duration_unconfirmed")));
        if(clip.can_add&&writable()){
          card.draggable=true;
          card.ondragstart=e=>{e.dataTransfer?.setData('application/x-vsc-edit-source',JSON.stringify({shot_id:clip.shot_id,media_id:clip.media_id,trim_in_ms:clip.trim_in_ms||0,trim_out_ms:clip.trim_out_ms||clip.duration_ms||3000,working_selection_version_id:clip.working_selection_version_id||null}));};
        }
        if(added)card.append(element('span',msg("ui.already_on_timeline"),'edit-source-added'));else if(!clip.can_add)card.append(element('span',clip.disabled_reason,'hint'));else if(batchMode){const label=element('label',msg("ui.select_shot_value0_candidate_value1",{value0:clip.shot_number,value1:index+1})),check=element('input');check.type='checkbox';check.checked=selectedSources.has(candidateKey(clip));check.onchange=()=>{check.checked?selectedSources.add(candidateKey(clip)):selectedSources.delete(candidateKey(clip));draw();};label.append(check);card.append(label);}else card.append(button(msg("ui.add_to_video_track"),()=>mutate(()=>draft.clips.push(sourceClip(clip))),!writable()));
        cards.append(card);
      }section.append(group);
    }
    if(nextCandidateOffset!=null)section.append(button(msg("ui.more_episode_candidates_value0_value1_shown",{value0:candidates.length,value1:candidateTotal}),()=>loadCandidates(true),candidateLoading));
    if(!candidates.length)section.append(element('p',msg("ui.no_video_candidates_exist_for_this_episode_yet_generated"),'hint'));
    host.append(section);
  }
  function trimHandle(item,clip,side){
    const handle=element('span','','edit-timeline-handle '+side);handle.tabIndex=0;handle.setAttribute('role','slider');bindAttribute(handle,'aria-label',side==='start'?msg("ui.adjust_clip_start"):msg("ui.adjust_clip_end"));handle.setAttribute('aria-valuenow',String(side==='start'?clip.in_frame:clip.out_frame));
    const maximum=Math.floor((media.find(m=>m.id===clip.media_id)?.duration_ms||clip.out_frame*1000/draft.fps)*draft.fps/1000);
    const next=delta=>side==='start'?Math.max(0,Math.min(clip.out_frame-1,clip.in_frame+delta)):Math.min(maximum,Math.max(clip.in_frame+1,clip.out_frame+delta));
    handle.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key)||!writable())return;e.preventDefault();const value=next(e.key==='ArrowLeft'?-1:1);mutate(()=>clip[side==='start'?'in_frame':'out_frame']=value);};
    handle.onpointerdown=e=>{if(!writable())return;e.stopPropagation();e.preventDefault();const start=e.clientX,scale=(clip.out_frame-clip.in_frame)/item.getBoundingClientRect().width;let value=side==='start'?clip.in_frame:clip.out_frame;handle.setPointerCapture(e.pointerId);handle.onpointermove=event=>{value=next(Math.round((event.clientX-start)*scale));handle.title=(value/draft.fps).toFixed(2)+' 秒';handle.setAttribute('aria-valuenow',String(value));};handle.onpointerup=event=>{handle.releasePointerCapture(event.pointerId);handle.onpointermove=null;handle.onpointerup=null;mutate(()=>clip[side==='start'?'in_frame':'out_frame']=value);};};
    handle.onclick=e=>e.stopPropagation();item.append(handle);
  }
  function renderTrack(track,host){
    draft[track].forEach((clip,index)=>{
      const row=element('div','', 'edit-clip');row.dataset.clipId=clip.id;row.append(element('strong',joinMessages(["",index+1,". ",name(clip.media_id),""])));
      if(track==='clips'){const choice=element('label',msg("ui.select_clip"),'edit-clip-choice'),check=element('input');check.type='checkbox';check.checked=selectedClips.has(clip.id);check.onchange=()=>{check.checked?selectedClips.add(clip.id):selectedClips.delete(clip.id);draw();};choice.append(check);row.append(choice);row.draggable=true;row.ondragstart=e=>{e.dataTransfer.setData('application/x-vsc-edit-clip',clip.id);};row.ondragover=e=>e.preventDefault();row.ondrop=e=>{e.preventDefault();const srcRaw=e.dataTransfer?.getData('application/x-vsc-edit-source');if(srcRaw){if(!writable())return;const parsed=JSON.parse(srcRaw);if(globalThis.confirm&&!globalThis.confirm('替换视频片段：确认使用拖入的视频候选替换当前轨道片段？'))return;mutate(()=>{const nextClip=sourceClip(parsed);draft.clips[index]={...nextClip,id:clip.id,...(clip.transition?{transition:clip.transition}:{})};});return;}const id=e.dataTransfer.getData('application/x-vsc-edit-clip'),from=draft.clips.findIndex(c=>c.id===id);if(from>=0&&from!==index)mutate(()=>draft.clips.splice(index,0,draft.clips.splice(from,1)[0]));};}
      const settings=element('details','','edit-clip-settings');settings.append(element('summary',msg("project.more_actions")));
      if(track==='clips'){const preview=button('',()=>previewClip(index,true)),item=media.find(m=>m.id===clip.media_id),thumb=element(item?.modality==='image'?'img':'video');preview.className='edit-clip-preview';bindAttribute(preview,'aria-label',msg("ui.preview_clip_value0",{value0:index+1}));thumb.src=base+'/media/'+encodeURIComponent(clip.media_id)+'/content';if(item?.modality==='image')bindAttribute(thumb,"alt",name(clip.media_id));else{thumb.muted=true;thumb.preload='metadata';}preview.append(thumb,element('span',joinMessages([((clip.out_frame-clip.in_frame)/draft.fps).toFixed(2),"s"])));row.append(preview,button(msg("common.crop"),()=>trimClip(clip)));}
      const from=input(msg("ui.start_frame"),clip.in_frame),to=input(msg("ui.end_frame"),clip.out_frame),volume=input(msg("common.volume"),clip.volume??1);volume.field.step='.05';
      for(const [control,key] of [[from,'in_frame'],[to,'out_frame'],[volume,'volume']]){
        control.field.addEventListener('change',()=>mutate(()=>clip[key]=Number(control.field.value)));settings.append(control.wrap);
      }
      const mute=element('label',msg("ui.mute")),check=element('input');check.type='checkbox';check.checked=clip.muted;check.addEventListener('change',()=>mutate(()=>clip.muted=check.checked));mute.append(check);settings.append(mute);
      if(track==='audio'){
        const purpose=element('label',msg("ui.purpose_273")),select=element('select');
        for(const [value,label] of [['music',msg("ui.music")],['dialogue_dry',msg("ui.voiceover")],['sfx',msg("agent.overseas_remake_dialogue_type_sound_effect")],['ambience',msg("ui.ambience_arrays_44")]]){const option=element('option',label);option.value=value;select.append(option);}select.value=clip.purpose||'music';select.addEventListener('change',()=>mutate(()=>clip.purpose=select.value));purpose.append(select);row.append(purpose);
        for(const [label,key] of [[msg("ui.start_position_frames"),'at_frame'],[msg("ui.fade_in_frames"),'fade_in'],[msg("ui.fade_out_frames"),'fade_out']]){
          const field=input(label,clip[key]||0);field.field.addEventListener('change',()=>mutate(()=>clip[key]=Number(field.field.value)));row.append(field.wrap);
        }
      }else{
        const trWrap=element('label','转场效果'),trSelect=element('select');bindAttribute(trSelect,'aria-label','转场效果');
        for(const [val,label]of [['none','无转场'],['fade_in_out','淡入淡出'],['crossfade','交叉淡化']])trSelect.append(localizedOption(val,label));
        trSelect.value=clip.transition||'none';
        trSelect.addEventListener('change',()=>mutate(()=>{if(trSelect.value==='none')delete clip.transition;else clip.transition=trSelect.value;}));
        trWrap.append(trSelect);settings.append(trWrap);
        for(const [title,key]of [[msg("ui.picture_fade_in_frames"),'fade_in_frames'],[msg("ui.picture_fade_out_frames"),'fade_out_frames']]){const fade=input(title,clip[key]||0);bindAttribute(fade.field,'aria-label',title);fade.field.min='0';fade.field.max=String(clip.out_frame-clip.in_frame);fade.field.onchange=()=>{const value=Number(fade.field.value),other=key==='fade_in_frames'?'fade_out_frames':'fade_in_frames';if(!Number.isInteger(value)||value<0||value+(clip[other]||0)>clip.out_frame-clip.in_frame){error('画面淡入淡出不能超过片段长度。');fade.field.value=clip[key]||0;return;}mutate(()=>clip[key]=value);};settings.append(fade.wrap);}
        settings.append(button(msg("ui.fade_through_black_into_the_next_clip"),()=>mutate(()=>{const next=draft.clips[index+1],frames=Math.min(Math.round(draft.fps/4),Math.floor((clip.out_frame-clip.in_frame-(clip.fade_in_frames||0))/2),Math.floor((next.out_frame-next.in_frame-(next.fade_out_frames||0))/2));if(frames<1)throw new Error('相邻片段过短，无法淡黑衔接');clip.fade_out_frames=frames;next.fade_in_frames=frames;}),index===draft.clips.length-1));
        row.append(button(msg("ui.move_earlier"),()=>mutate(()=>{[draft.clips[index-1],draft.clips[index]]=[draft.clips[index],draft.clips[index-1]];}),index===0));
        row.append(button(msg("ui.move_later"),()=>mutate(()=>{[draft.clips[index+1],draft.clips[index]]=[draft.clips[index],draft.clips[index+1]];}),index===draft.clips.length-1));
        const split=input(msg("ui.split_position_source_frame"),Math.floor((clip.in_frame+clip.out_frame)/2));row.append(split.wrap,button(msg("common.split"),()=>{
          const point=Number(split.field.value);if(!Number.isInteger(point)||point<=clip.in_frame||point>=clip.out_frame)throw new Error('分割点须位于片段内部');
          mutate(()=>{const right={...clip,id:crypto.randomUUID(),in_frame:point};delete right.fade_in_frames;delete clip.fade_out_frames;clip.out_frame=point;draft.clips.splice(index+1,0,right);});
        }));
      }
      row.append(button(msg("ui.remove_from_timeline"),()=>mutate(()=>draft[track].splice(index,1))));for(const child of [...row.children]){if(child.tagName==='LABEL'&&!child.classList.contains('edit-clip-choice')||child.tagName==='BUTTON'&&!child.classList.contains('edit-clip-preview')&&child.textContent!=='裁剪')settings.append(child);}row.append(settings);host.append(row);
    });
  }
  function draw(){
    playback?.dispose();playback=null;
    if(disposed||!sameIdentity())return;captureCaption();const oldSrt=mounted?root.querySelector('.edit-srt'):null,focused=oldSrt&&document.activeElement===oldSrt,selection=focused?[oldSrt.selectionStart,oldSrt.selectionEnd]:null;root.replaceChildren();root.classList.add('edit-workspace');mounted=true;
    const toolbar=element('div','', 'edit-toolbar');toolbar.append(element('h2',msg("ui.episode_edit")),element('span',dirty?msg("ui.unsaved_changes"):view?.workspace?msg("ui.saved_v_value0",{value0:view.workspace.revision}):msg("ui.new_working_draft")));
    toolbar.append(button(msg("common.save"),save,!writable()),button(msg("ui.compose_the_current_working_draft"),async()=>{if(dirty||!view.workspace)await save();if(disposed)return;if(dirty)throw new Error('保存期间有新修改，请保存后再合成');await write('/edit-exports',{edit_version_id:view.current.id});await load();},!writable()||!draft.clips.length));
    toolbar.append(button(msg("ui.recover_unconfirmed_operation"),async()=>{const entries=Object.entries(pending);if(!entries.length){await load();error('当前没有待恢复的操作，已读取服务端版本。');return;}for(const [path,intent]of entries){const result=await write(path,intent.payload);if(disposed)return;if(path==='/edit-workspace'){draftRevision=result.edit_revision;dirty=!sameDocument(draft,intent.payload.document);stash();}}await load();error('已查询原操作回执，未重复创建任务。');},!writable()));
    toolbar.append(button(msg("ui.convert_to_a_formal_timeline"),async()=>{if(dirty)throw new Error('请先保存当前剪辑，再固定正式时间线');const current=generation;await openEditHandoff(root,{api,base,versionId:view.current.id,session:identity,write,onArtifact,name,alive:()=>!disposed&&current===generation});},!writable()||!view?.current));
    toolbar.append(button(msg("ui.start_from_selected_episode_videos"),async()=>{if(dirty||draft.clips.length)throw new Error('请先保存并清空画面轨，再按所选视频起稿');const epoch=editEpoch;const seed=await api(`${base}/edit-seed?episode_id=${encodeURIComponent(episodeId)}`);if(disposed||editEpoch!==epoch)return;mutate(()=>draft=seed.document);error(seed.gaps.length?`已加入 ${seed.document.clips.length}/${seed.shot_count} 镜：${seed.gaps.map(g=>g.reason).join('；')}`:'本集所选视频和裁剪范围已按镜头顺序加入，保存后可合成。');},!writable()));
    toolbar.append(button(msg("common.undo"),()=>{redo.push(copy(draft));draft=undo.pop();editEpoch++;dirty=true;stash();draw();},!undo.length),button(msg("common.redo"),()=>{undo.push(copy(draft));draft=redo.pop();editEpoch++;dirty=true;stash();draw();},!redo.length));
    toolbar.append(button(msg("ui.load_saved_version"),async()=>{if(dirty&&!confirm('放弃本机未保存修改，并载入服务端最新剪辑版本？'))return;dirty=false;undo=[];redo=[];editEpoch++;stash();await load();}));
    const advanced=element('details','','edit-advanced');advanced.append(element('summary',msg("ui.project_settings_and_recovery")));for(const child of [...toolbar.children]){if(child.tagName==='BUTTON'&&!['保存','合成当前工作稿','撤销','重做'].includes(child.textContent))advanced.append(child);}root.append(toolbar,element('p','', 'edit-notice'));
    const layout=element('div','','edit-preview-layout'),clipPanel=element('section','','edit-clips-panel'),playerPanel=element('section','','edit-player-panel');
    const allTrackMuted=draft.clips.length>0&&draft.clips.every(c=>c.muted===true);
    clipPanel.append(
      element('h3',msg("ui.all_video_clips")),
      button(allTrackMuted?'恢复视频轨声音':'静音视频轨',()=>mutate(()=>{for(const c of draft.clips)c.muted=!allTrackMuted;}),!writable()||!draft.clips.length),
      button(msg("ui.preview_all_videos"),()=>previewClip(0,true),!draft.clips.length),
    );
    playerPanel.append(element('h3',msg("common.route_video_review")));const stage=element('div','','edit-preview-stage'),player=element('video'),poster=element('img');player.controls=true;player.preload='metadata';poster.hidden=true;stage.append(player,poster);const caption=element('p',draft.clips.length?'':msg("ui.no_video_clips"),'edit-preview-caption'),playbackControls=element('div','','edit-playback-controls');playbackControls.append(button(msg("ui.previous_clip"),()=>previewClip(Math.max(0,previewIndex-1),true),!draft.clips.length),button(msg("ui.play_pause"),()=>{playback?.toggle();},!draft.clips.length),button(msg("ui.next_clip"),()=>previewClip(Math.min(draft.clips.length-1,previewIndex+1),true),!draft.clips.length));playerPanel.append(stage,caption,playbackControls);layout.append(clipPanel,playerPanel);root.append(layout);previewPlayer=playerPanel;
    const seek=element('input');seek.type='range';seek.min='0';seek.max=String(Math.max(0,draft.clips.reduce((sum,c)=>sum+c.out_frame-c.in_frame,0)-1));seek.step='1';seek.value='0';bindAttribute(seek,'aria-label',msg("ui.preview_time_position"));seek.oninput=()=>playback?.seek(Number(seek.value));playerPanel.append(seek);
    playback=createEditPlayback({stage,video:player,poster,document:draft,media,url:id=>base+'/media/'+encodeURIComponent(id)+'/content',onError:error,onPosition:position=>{
      seek.value=String(Math.floor(position.frame));previewIndex=Math.max(0,position.index);
      setText(caption,msg("ui.value0_value1_seconds_picture_sound_and_subtitle_preview",{value0:(position.frame/draft.fps).toFixed(2),value1:(position.total/draft.fps).toFixed(2)}));
      for(const card of root.querySelectorAll('.edit-clip'))card.setAttribute('aria-current',card.dataset.clipId===draft.clips[previewIndex]?.id?'true':'false');
    }});
    renderSources(clipPanel);
    if(view?.current&&selectedClips.size){const download=element('a',msg("ui.download_value0_selected_clips",{value0:selectedClips.size}));download.href=`${base}/edit-workspace/${view.current.id}/download?kind=clips&clip_keys=${encodeURIComponent([...selectedClips].join(','))}`;download.onclick=e=>{if(dirty){e.preventDefault();error('请先保存当前裁剪，再下载所选片段。');}};playerPanel.append(download);}

    if(view?.renderer&&!view.renderer.running)root.append(element('p',msg("ui.background_composition_is_not_running_save_now_and_resume"),'hint'));
    const settings=element('div','', 'edit-settings');
    for(const [label,key] of [[msg("ui.width"),'width'],[msg("ui.height"),'height'],[msg("agent.overseas_remake_source_fps"),'fps']]){const field=input(label,draft[key]);field.field.addEventListener('change',()=>{
      const value=Number(field.field.value);
      if(key!=='fps'){mutate(()=>draft[key]=value);return;}
      if(!Number.isInteger(value)||value<12||value>60){field.field.value=draft.fps;error('帧率须为 12–60 的整数。');return;}
      mutate(()=>{
        const scale=value/draft.fps,frame=n=>Math.round(n*scale);
        for(const clip of [...draft.clips,...draft.audio]){
          clip.in_frame=frame(clip.in_frame);clip.out_frame=Math.max(clip.in_frame+1,frame(clip.out_frame));
          for(const name of ['at_frame','fade_in','fade_out','fade_in_frames','fade_out_frames'])if(name in clip)clip[name]=frame(clip[name]);
          const duration=clip.out_frame-clip.in_frame;
          if((clip.fade_in||0)+(clip.fade_out||0)>duration)clip.fade_out=Math.max(0,duration-(clip.fade_in||0));
        }
        const total=draft.clips.reduce((sum,clip)=>sum+clip.out_frame-clip.in_frame,0);
        for(const caption of draft.captions){caption.start_frame=Math.min(Math.max(0,total-1),frame(caption.start_frame));caption.end_frame=Math.min(total,Math.max(caption.start_frame+1,frame(caption.end_frame)));}
        draft.fps=value;
      });
    });settings.append(field.wrap);}
    settings.append(element('p',msg("ui.changing_frame_rate_converts_trim_audio_and_subtitle_timecodes"),'hint'));
    advanced.append(settings);
    if(view?.current){const downloads=element('nav','','edit-downloads');for(const [kind,title]of [['srt',msg("ui.download_saved_subtitles")],['project',msg("ui.download_saved_project_and_source_clips")]]){const link=element('a',title);link.href=`${base}/edit-workspace/${encodeURIComponent(view.current.id)}/download?kind=${kind}`;downloads.append(link);}advanced.append(downloads);if(dirty)advanced.append(element('p',msg("ui.downloads_use_the_last_saved_version_save_first_to"),'hint'));}
    const library=element('details'),summary=element('summary',msg("ui.add_project_media"));library.append(summary);
    const list=element('div','', 'edit-media-list');
    for(const item of media){if(!['video','image','audio'].includes(item.modality))continue;const row=element('div');row.append(element('span',joinMessages(["",item.name," · ",item.modality,""])));
      row.append(button(item.modality==='audio'?msg("ui.add_to_sound_track"):msg("ui.add_to_video_track"),()=>attach(item,item.modality==='audio'?'audio':'clips'),!writable()));
      if(item.modality==='video')row.append(button(msg("ui.add_audio_only"),()=>attach(item,'audio'),!writable()));list.append(row);}
    library.append(list);if(loadedMediaCount<mediaTotal)library.append(button(msg("ui.more_media"),async()=>{const current=generation;const rows=await api(`${base}/media?limit=200&offset=${loadedMediaCount}`);if(disposed||!sameIdentity()||current!==generation)return;loadedMediaCount+=rows.items.length;for(const item of rows.items)if(!media.some(m=>m.id===item.id))media.push(item);mediaTotal=rows.total;draw();}));clipPanel.append(library);

    if(draft.clips.length){const strip=element('div','', 'edit-timeline');bindAttribute(strip,'aria-label',msg("ui.video_clips_in_timeline_order"));let position=0;
      for(const [index,clip] of draft.clips.entries()){const seconds=(clip.out_frame-clip.in_frame)/draft.fps;const item=button(msg("ui.value0_value1_value2_seconds",{value0:index+1,value1:position.toFixed(1),value2:(position+seconds).toFixed(1)}),()=>{root.querySelector(`[data-clip-id="${CSS.escape(clip.id)}"]`)?.scrollIntoView({block:'center',behavior:'smooth'});});item.style.flexGrow=seconds;item.title=name(clip.media_id);item.classList.add('edit-timeline-item');trimHandle(item,clip,'start');trimHandle(item,clip,'end');strip.append(item);position+=seconds;}
      playerPanel.append(strip,element('p',msg("ui.total_value0_seconds_value1_clips",{value0:position.toFixed(2),value1:draft.clips.length}),'hint'));}
    renderTrack('clips',clipPanel);
    if(!draft.clips.length){
      clipPanel.append(element('p',msg("ui.no_video_clips_yet_add_media_to_start_editing"),'edit-empty'));
      if(!guideDismissed){
        const guide=element('section','','edit-onboarding-guide');
        guide.append(
          element('strong','多段视频剪辑三步指引'),
          element('p','1. 从上方「本集视频候选」一键加入或拖拽片段到视频轨（拖拽到已有片段可替换）'),
          element('p','2. 拖动首尾裁剪滑块、调整片段顺序并选择淡入淡出／交叉淡化转场'),
          element('p','3. 配置配乐与 SRT 字幕后点击「合成当前工作稿」输出成片'),
          button('我知道了',()=>{guideDismissed=true;draw();}),
        );
        clipPanel.append(guide);
      }
    }else previewClip(Math.min(previewIndex,draft.clips.length-1));
    const sound=element('details','','edit-sound-panel');sound.append(element('summary',msg("ui.background_music_dialogue_and_effects")));renderTrack('audio',sound);
    if(draft.professional_inputs?.length)sound.append(element('p',`保留 ${draft.professional_inputs.length} 份固定专业来源；剪辑、声音与字幕仍是未审工作稿。`,'hint'));
    for(const gap of seed?.gaps||[])if(gap.cue_id||gap.code?.startsWith('edit_cue')||gap.code?.startsWith('edit_caption'))sound.append(element('p',gap.reason,'hint'));
    root.append(sound);
    const captions=element('details'),label=element('label',msg("ui.manual_subtitles_srt_timecodes")),textarea=element('textarea','','edit-srt');textarea.rows=7;
    if(!captionDirty)captionText=captionDocument();textarea.value=captionText||'';captions.open=captionsOpen||captionDirty;
    captions.addEventListener('toggle',()=>{captionsOpen=captions.open;});
    textarea.addEventListener('input',()=>{captionText=textarea.value;captionDirty=captionText!==captionDocument();captionsOpen=true;stashCaption();const notice=root.querySelector('.edit-caption-state');if(notice)setText(notice,captionDirty?msg("ui.subtitle_input_has_not_been_applied_saving_and_rendering"):msg("ui.subtitle_input_applied_to_the_working_draft"));});
    label.append(textarea);captions.append(element('summary',msg("agent.subtitle")),label,button(msg("ui.apply_subtitles"),()=>{
      const blocks=textarea.value.trim()?textarea.value.trim().split(/\r?\n\s*\r?\n/):[],parsed=[];
      const time=s=>{const m=s.match(/^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/);if(!m)throw new Error('字幕时码格式应为 00:00:01,000');return Math.round((+m[1]*3600 + +m[2]*60 + +m[3]+ +m[4]/1000)*draft.fps);};
      for(const block of blocks){const lines=block.split(/\r?\n/);if(/^\d+$/.test(lines[0]))lines.shift();const range=lines.shift()?.split(/\s+-->\s+/);if(range?.length!==2)throw new Error('每条字幕须有起止时间');parsed.push({start_frame:time(range[0]),end_frame:time(range[1]),text:lines.join('\n')});}
      captionDirty=false;captionText=textarea.value;mutate(()=>draft.captions=parsed);stashCaption();
    },!writable()),button(msg("ui.discard_unapplied_subtitles"),()=>{captionDirty=false;captionText=captionDocument();textarea.value=captionText;stashCaption();draw();},!writable()),element('p',captionDirty?msg("ui.subtitle_input_has_not_been_applied_saving_and_rendering"):msg("ui.subtitle_input_applied_to_the_working_draft"),'edit-caption-state'));root.append(captions);
    if(focused){textarea.focus({preventScroll:true});textarea.setSelectionRange(...selection);}
    if(view?.history?.length>1){const history=element('details');history.append(element('summary',msg("ui.saved_versions")));for(const version of view.history){history.append(button(msg("ui.restore_v_value0",{value0:version.version}),async()=>{if(dirty)throw new Error('请先保存当前修改，再恢复历史版');await write('/edit-workspace',{episode_id:episodeId,edit_revision:view.workspace.revision,restore_version_id:version.id});await load();},!writable()));}advanced.append(history);}
    const exports=element('section');exports.append(element('h3',msg("ui.composition_outputs")));
    for(const job of view?.renders||[]){const card=element('article','', 'edit-export');card.dataset.jobId=job.id;card.append(element('p',joinMessages(["",job.status==='succeeded'?msg("common.completed"):job.status==='failed'?msg("video.combine_failed"):job.status==='cancelled'?msg("common.cancelled"):job.cancel_requested?msg("ui.cancelling"):job.status==='running'?msg("ui.rendering"):msg("ui.waiting_to_render"),"",job.edit_version_id!==view.current?.id?msg("ui.historical_edit_version"):'',""])));
      if(job.error)card.append(element('p',job.error));
      if(job.receipt){const receipt=job.receipt,checks=element('details','','edit-checks');checks.append(element('summary','声音与字幕检查（未审工作稿）'));
        for(const warning of [...(receipt.sound_checks?.warnings||[]),...(receipt.subtitle_warnings||[])])checks.append(element('p',warning,'hint'));
        if(receipt.subtitle_checks){const state=receipt.subtitle_checks;checks.append(element('p',state.text_coverage==='passed'?'固定对白文字覆盖已检查；台词行绑定与音频对齐仍未验证。':state.text_coverage==='missing_captions'?'已有固定对白，尚无字幕时码；台词与音频对齐未验证。':'没有可验证的固定字幕行覆盖；台词与音频对齐未验证。'));
          for(const measure of receipt.subtitle_measurements||[])checks.append(element('p',`字幕 ${measure.cue}：${(measure.duration_ms/1000).toFixed(2)} 秒，${measure.visible_characters} 字，${measure.cps.toFixed(2)} 字/秒。`));}
        for(const boundary of receipt.sound_checks?.boundaries||[])checks.append(element('p',`${(boundary.at_ms/1000).toFixed(2)} 秒声音边界：${boundary.status==='continuous'?'同一音轨持续覆盖':'存在覆盖缺口'}；听感未审。`));
        card.append(checks);}
      if(job.content_url){const video=element('video');video.controls=true;video.preload='metadata';video.src=job.content_url;const links=element('nav','','edit-downloads'),link=element('a',msg("ui.download_working_draft")),cover=element('a',msg("ui.download_current_frame_as_cover"));link.href=job.content_url+'?download=true';cover.href=`${base}/edit-exports/${job.id}/cover`;cover.onclick=()=>{cover.href=`${base}/edit-exports/${job.id}/cover?at_ms=${Math.max(0,Math.min(Math.floor(video.currentTime*1000),Math.ceil(video.duration*1000)-1)||0)}`;};links.append(link,cover);card.append(video,links);}
      if(['queued','running'].includes(job.status))card.append(button(job.cancel_requested?msg("ui.cancellation_request_received"):msg("ui.cancel_this_render"),async()=>{await write(`/edit-exports/${encodeURIComponent(job.id)}/cancel`,{job_id:job.id});await load();},!writable()||job.cancel_requested));
      if(['failed','cancelled'].includes(job.status))card.append(button(msg("ui.resume_composition_for_this_version"),async()=>{await write('/edit-exports',{edit_version_id:job.edit_version_id});await load();},!writable()));exports.append(card);}
    root.append(advanced,exports);
  }
  async function load(){
    if(disposed)return;if(!sameIdentity()){root.replaceChildren(element('p',msg("ui.the_operation_identity_changed_reopen_this_episode_s_edit")));return;}captureCaption();const current=++generation;if(!episodeId){const emptyCard=element('section','','edit-empty-episode-card');emptyCard.append(element('p',msg("ui.open_the_episode_you_want_to_edit_from_the")));root.replaceChildren(emptyCard);return;}
    const data=await api(`${base}/edit-workspace?episode_id=${encodeURIComponent(episodeId)}`);if(disposed||!sameIdentity()||current!==generation)return;
    view=data;reconcileRead(data);
    const resources=await api(`${base}/media?limit=200`);if(disposed||!sameIdentity()||current!==generation)return;media=resources.items||[];loadedMediaCount=media.length;mediaTotal=resources.total||media.length;draw();
    await loadCandidates();if(disposed||!sameIdentity()||current!==generation)return;
    if(multiClipGuard){
      const playableIds=new Set([...candidates.filter(c=>c.can_add!==false).map(c=>c.media_id),...draft.clips.map(c=>c.media_id)].filter(Boolean));
      if(playableIds.size<2){
        const guardMsg='至少需要 2 个可预览视频才能开启视频剪辑';
        error(guardMsg);
        if(onMultiClipBlocked){onMultiClipBlocked(guardMsg);return;}
      }
    }
    const selected=await api(`${base}/edit-seed?episode_id=${encodeURIComponent(episodeId)}`);if(disposed||!sameIdentity()||current!==generation)return;seed=selected;
    const missing=[...new Set([...draft.clips,...draft.audio,...(seed.document?.clips||[]),...(seed.document?.audio||[])].map(c=>c.media_id))].filter(id=>!media.some(item=>item.id===id));
    const details=await Promise.all(missing.map(id=>api(`${base}/media/${encodeURIComponent(id)}`)));if(disposed||!sameIdentity()||current!==generation)return;media.push(...details);draw();
    clearTimeout(poll);if(data.renders.some(r=>['queued','running'].includes(r.status)))poll=setTimeout(()=>load().catch(e=>error(e.message)),3000);
  }
  return {load,async beforeContextSwitch(){captureCaption();stashCaption();if(dirty){try{await save();}catch{stash();}}let retained=false;try{retained=(!dirty||JSON.stringify(JSON.parse(sessionStorage.getItem(recoveryKey)||'null')?.document)===JSON.stringify(draft))&&(!captionDirty||JSON.parse(sessionStorage.getItem(captionKey)||'null')?.text===captionText);}catch{}return {ready:retained,message:retained?'未保存的剪辑输入已保留在原集。':'浏览器无法保留当前剪辑，请先保存后切换。'}},suspend(){if(disposed)return;captureCaption();stashCaption();disposed=true;playback?.dispose();generation++;clearTimeout(poll);clearTimeout(autoSaveTimer);root.querySelectorAll('dialog').forEach(dialog=>dialog.close());},save};
}
