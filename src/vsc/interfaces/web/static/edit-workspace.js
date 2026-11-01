/* Editable first cut. The server owns revisions, media references and exports. */
import {openEditHandoff} from './edit-handoff.js';
const element=(tag,text='',cls='')=>{const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;};
const input=(label,value,type='number')=>{const wrap=element('label',label),field=element('input');field.type=type;field.value=value;wrap.append(field);return {wrap,field};};
const empty=()=>({format:'vsc.edit-workspace/v1',width:720,height:1280,fps:24,clips:[],audio:[],captions:[]});
const copy=value=>JSON.parse(JSON.stringify(value));

export function createEditWorkspace({root,api,project,episodeId,session,onChange,onArtifact}){
  let generation=0,view=null,draft=empty(),draftRevision=0,media=[],mediaTotal=0,dirty=false,editEpoch=0,undo=[],redo=[],poll=null,disposed=false,mounted=false,previewIndex=0,previewPlayer=null;
  const base=`/api/v1/projects/${encodeURIComponent(project)}`;
  const initialIdentity=typeof session==='function'?session():session||{};
  const operator=initialIdentity.identityId||initialIdentity.actor||'read-only';
  const recoveryKey=`vsc.edit-draft:${operator}:${project}:${episodeId}`,requestKey=recoveryKey+':requests',captionKey=recoveryKey+':unapplied-srt';let pending={},captionText=null,captionDirty=false,captionsOpen=false;
  try{const retained=JSON.parse(sessionStorage.getItem(captionKey)||'null');if(typeof retained?.text==='string'){captionText=retained.text;captionDirty=true;captionsOpen=true;}}catch{}
  try{pending=JSON.parse(sessionStorage.getItem(requestKey)||'{}');}catch{}
  const retainRequests=()=>{try{sessionStorage.setItem(requestKey,JSON.stringify(pending));}catch{error('浏览器无法保存操作回执，请保持当前页面并恢复操作后再关闭。');}};
  try{const saved=JSON.parse(sessionStorage.getItem(recoveryKey)||'null');if(saved?.document?.format==='vsc.edit-workspace/v1'&&Number.isInteger(saved.edit_revision)){draft=saved.document;draftRevision=saved.edit_revision;dirty=true;}}catch{}
  function stash(){try{if(dirty)sessionStorage.setItem(recoveryKey,JSON.stringify({document:draft,edit_revision:draftRevision}));else sessionStorage.removeItem(recoveryKey);}catch{error('浏览器恢复空间不可用，请保存当前工作稿后再离开。');}}
  const identity=()=>typeof session==='function'?session():session||{};
  const sameIdentity=()=>(identity().identityId||identity().actor||'read-only')===operator;
  const writable=()=>sameIdentity()&&identity().actor&&identity().writable;
  function stashCaption(){try{if(captionDirty)sessionStorage.setItem(captionKey,JSON.stringify({text:captionText}));else sessionStorage.removeItem(captionKey);}catch{error('未应用字幕无法写入浏览器恢复空间，请保持此页。');}}
  function captionDocument(){const clock=frame=>{let ms=Math.round(frame*1000/draft.fps);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};return draft.captions.map((c,i)=>`${i+1}\n${clock(c.start_frame)} --> ${clock(c.end_frame)}\n${c.text}`).join('\n\n');}
  function captureCaption(){if(!mounted)return;const field=root.querySelector('.edit-srt');if(field&&field.value!==captionText){captionText=field.value;captionDirty=captionText!==captionDocument();stashCaption();}}
  function error(message){if(disposed||!sameIdentity())return;const out=root.querySelector('.edit-notice');if(out){out.textContent=message;out.setAttribute('role','alert');}}
  function mutate(change){undo.push(copy(draft));if(undo.length>50)undo.shift();redo=[];change();editEpoch++;dirty=true;stash();draw();}
  async function write(path,payload){
    const auth=identity();if(!writable())throw new Error('请先建立可写的本机操作会话。');
    if(!sameIdentity())throw new Error('操作身份已切换，请重新打开本集剪辑。');
    const signature=JSON.stringify(payload);let intent=pending[path];
    if(intent&&JSON.stringify(intent.payload)!==signature)throw new Error('上次操作的响应尚未确认，请先“恢复未确认操作”；当前修改会保留。');
    if(!intent){intent={payload,expected_revision:view.project_revision,idempotency_key:crypto.randomUUID()};pending[path]=intent;retainRequests();}
    let result;
    try{result=await api(base+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth.csrf},body:JSON.stringify(intent)});delete pending[path];retainRequests();}
    catch(failure){if(failure.status&&failure.status<500){delete pending[path];retainRequests();}throw failure;}
    if(disposed||!sameIdentity())return result;view.project_revision=result.revision??view.project_revision;onChange?.(result);return result;
  }
  async function save(){
    if(!view)throw new Error('剪辑尚未载入');
    const savedEpoch=editEpoch,savedDocument=copy(draft),basedOn=draftRevision;
    const result=await write('/edit-workspace',{episode_id:episodeId,edit_revision:basedOn,document:savedDocument});
    if(disposed||!sameIdentity()){
      // A receipt belongs to this fixed scope even after navigation. Reconcile
      // only its matching local base; never repaint another scope or replace
      // text typed after submission. A remounted instance keeps its own pending
      // intent and can recover the same receipt while this response is in flight.
      try{const retained=JSON.parse(sessionStorage.getItem(recoveryKey)||'null');if(retained?.edit_revision===basedOn){if(JSON.stringify(retained.document)===JSON.stringify(savedDocument))sessionStorage.removeItem(recoveryKey);else sessionStorage.setItem(recoveryKey,JSON.stringify({...retained,edit_revision:result.edit_revision}));}}catch{}
      return result;
    }
    draftRevision=result.edit_revision;dirty=editEpoch!==savedEpoch;stash();await load();return result;
  }
  function button(title,action,disabled=false){const b=element('button',title);b.type='button';b.disabled=disabled;b.addEventListener('click',async()=>{b.disabled=true;try{await action();}catch(e){error(e.message);}finally{if(b.isConnected)b.disabled=disabled;}});return b;}
  function name(id){return media.find(m=>m.id===id)?.name||'已固定的素材';}
  function attach(item,track){
    const frames=Math.max(1,Math.floor((item.duration_ms||3000)*draft.fps/1000));
    mutate(()=>draft[track].push({id:crypto.randomUUID(),media_id:item.id,in_frame:0,out_frame:frames,volume:track==='audio'?.25:1,muted:false,...(track==='audio'?{at_frame:0,fade_in:0,fade_out:0}:{})}));
  }
  function previewClip(index,play=false){
    const clip=draft.clips[index];if(!clip||!previewPlayer)return;previewIndex=index;
    const item=media.find(m=>m.id===clip.media_id),video=previewPlayer.querySelector('video'),poster=previewPlayer.querySelector('img');
    video.pause();video.hidden=item?.modality==='image';poster.hidden=!video.hidden;
    const url=base+'/media/'+encodeURIComponent(clip.media_id)+'/content';
    if(video.hidden){poster.src=url;poster.alt=name(clip.media_id);}else{video.src=url;video.onloadedmetadata=()=>{video.currentTime=clip.in_frame/draft.fps;video.volume=Math.max(0,Math.min(1,clip.volume??1));video.muted=Boolean(clip.muted);if(play)video.play().catch(()=>{});};video.ontimeupdate=()=>{if(video.currentTime>=clip.out_frame/draft.fps){if(previewIndex+1<draft.clips.length)previewClip(previewIndex+1,true);else video.pause();}};}
    previewPlayer.querySelector('.edit-preview-caption').textContent=(index+1)+' / '+draft.clips.length+' · '+name(clip.media_id);
    for(const card of root.querySelectorAll('.edit-clip'))card.setAttribute('aria-current',card.dataset.clipId===clip.id?'true':'false');
  }
  function trimClip(clip){
    const dialog=element('dialog','','edit-trim-dialog'),heading=element('header'),video=element('video');heading.append(element('h3','裁剪视频'),button('关闭',()=>dialog.close()));video.controls=true;video.preload='metadata';video.src=base+'/media/'+encodeURIComponent(clip.media_id)+'/content';
    const from=input('开始时间（秒）',(clip.in_frame/draft.fps).toFixed(3)),to=input('结束时间（秒）',(clip.out_frame/draft.fps).toFixed(3));from.field.step=to.field.step=String(1/draft.fps);from.field.min=to.field.min='0';video.addEventListener('loadedmetadata',()=>{video.currentTime=clip.in_frame/draft.fps;});from.field.addEventListener('input',()=>{video.currentTime=Number(from.field.value);});
    const problem=element('p','','edit-trim-notice');problem.setAttribute('role','alert');const controls=element('div','','edit-trim-controls');controls.append(from.wrap,to.wrap,button('取消',()=>dialog.close()),button('确定',()=>{const start=Math.round(Number(from.field.value)*draft.fps),end=Math.round(Number(to.field.value)*draft.fps);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||Number.isFinite(video.duration)&&end>Math.ceil(video.duration*draft.fps)){problem.textContent='裁剪范围须位于源片段内，且结束时间大于开始时间。';return;}dialog.close();mutate(()=>{clip.in_frame=start;clip.out_frame=end;});},!writable()));dialog.append(heading,video,controls,problem);dialog.addEventListener('close',()=>{video.pause();dialog.remove();});root.append(dialog);dialog.showModal();
  }
  function renderTrack(track,host){
    draft[track].forEach((clip,index)=>{
      const row=element('div','', 'edit-clip');row.dataset.clipId=clip.id;row.append(element('strong',`${index+1}. ${name(clip.media_id)}`));
      const settings=element('details','','edit-clip-settings');settings.append(element('summary','更多操作'));
      if(track==='clips'){const preview=button('',()=>previewClip(index,true)),item=media.find(m=>m.id===clip.media_id),thumb=element(item?.modality==='image'?'img':'video');preview.className='edit-clip-preview';preview.setAttribute('aria-label','预览片段 '+(index+1));thumb.src=base+'/media/'+encodeURIComponent(clip.media_id)+'/content';if(item?.modality==='image')thumb.alt=name(clip.media_id);else{thumb.muted=true;thumb.preload='metadata';}preview.append(thumb,element('span',((clip.out_frame-clip.in_frame)/draft.fps).toFixed(2)+'s'));row.append(preview,button('裁剪',()=>trimClip(clip)));}
      const from=input('起始帧',clip.in_frame),to=input('结束帧',clip.out_frame),volume=input('音量',clip.volume??1);volume.field.step='.05';
      for(const [control,key] of [[from,'in_frame'],[to,'out_frame'],[volume,'volume']]){
        control.field.addEventListener('change',()=>mutate(()=>clip[key]=Number(control.field.value)));settings.append(control.wrap);
      }
      const mute=element('label','静音 '),check=element('input');check.type='checkbox';check.checked=clip.muted;check.addEventListener('change',()=>mutate(()=>clip.muted=check.checked));mute.append(check);settings.append(mute);
      if(track==='audio'){
        const purpose=element('label','用途 '),select=element('select');
        for(const [value,label] of [['music','音乐'],['dialogue_dry','配音'],['sfx','音效'],['ambience','环境']]){const option=element('option',label);option.value=value;select.append(option);}select.value=clip.purpose||'music';select.addEventListener('change',()=>mutate(()=>clip.purpose=select.value));purpose.append(select);row.append(purpose);
        for(const [label,key] of [['开始位置（帧）','at_frame'],['淡入（帧）','fade_in'],['淡出（帧）','fade_out']]){
          const field=input(label,clip[key]||0);field.field.addEventListener('change',()=>mutate(()=>clip[key]=Number(field.field.value)));row.append(field.wrap);
        }
      }else{
        row.append(button('前移',()=>mutate(()=>{[draft.clips[index-1],draft.clips[index]]=[draft.clips[index],draft.clips[index-1]];}),index===0));
        row.append(button('后移',()=>mutate(()=>{[draft.clips[index+1],draft.clips[index]]=[draft.clips[index],draft.clips[index+1]];}),index===draft.clips.length-1));
        const split=input('分割位置（源帧）',Math.floor((clip.in_frame+clip.out_frame)/2));row.append(split.wrap,button('分割',()=>{
          const point=Number(split.field.value);if(!Number.isInteger(point)||point<=clip.in_frame||point>=clip.out_frame)throw new Error('分割点须位于片段内部');
          mutate(()=>{const right={...clip,id:crypto.randomUUID(),in_frame:point};clip.out_frame=point;draft.clips.splice(index+1,0,right);});
        }));
      }
      row.append(button('移出时间线',()=>mutate(()=>draft[track].splice(index,1))));for(const child of [...row.children]){if(child.tagName==='LABEL'||child.tagName==='BUTTON'&&!child.classList.contains('edit-clip-preview')&&child.textContent!=='裁剪')settings.append(child);}row.append(settings);host.append(row);
    });
  }
  function draw(){
    if(disposed||!sameIdentity())return;captureCaption();const oldSrt=mounted?root.querySelector('.edit-srt'):null,focused=oldSrt&&document.activeElement===oldSrt,selection=focused?[oldSrt.selectionStart,oldSrt.selectionEnd]:null;root.replaceChildren();root.classList.add('edit-workspace');mounted=true;
    const toolbar=element('div','', 'edit-toolbar');toolbar.append(element('h2','本集剪辑'),element('span',dirty?'有未保存修改':view?.workspace?`已保存 · v${view.workspace.revision}`:'新工作稿'));
    toolbar.append(button('保存',save,!writable()),button('合成当前工作稿',async()=>{if(dirty||!view.workspace)await save();if(disposed)return;if(dirty)throw new Error('保存期间有新修改，请保存后再合成');await write('/edit-exports',{edit_version_id:view.current.id});await load();},!writable()||!draft.clips.length));
    toolbar.append(button('恢复未确认操作',async()=>{const entries=Object.entries(pending);if(!entries.length){error('当前没有待恢复的操作。');return;}for(const [path,intent]of entries){const result=await write(path,intent.payload);if(disposed)return;if(path==='/edit-workspace'){draftRevision=result.edit_revision;dirty=JSON.stringify(draft)!==JSON.stringify(intent.payload.document);stash();}}await load();error('已查询原操作回执，未重复创建任务。');},!writable()));
    toolbar.append(button('转为正式时间线',async()=>{if(dirty)throw new Error('请先保存当前剪辑，再固定正式时间线');const current=generation;await openEditHandoff(root,{api,base,versionId:view.current.id,session:identity,write,onArtifact,name,alive:()=>!disposed&&current===generation});},!writable()||!view?.current));
    toolbar.append(button('从本集已采用视频起稿',async()=>{if(dirty||draft.clips.length)throw new Error('请先保存并清空画面轨，再按已采用视频起稿');const epoch=editEpoch;const seed=await api(`${base}/edit-seed?episode_id=${encodeURIComponent(episodeId)}`);if(disposed||editEpoch!==epoch)return;mutate(()=>draft=seed.document);error(seed.gaps.length?`已加入 ${seed.document.clips.length}/${seed.shot_count} 镜：${seed.gaps.map(g=>g.reason).join('；')}`:'本集已采用视频已按镜头顺序加入，保存后可合成。');},!writable()));
    toolbar.append(button('撤销',()=>{redo.push(copy(draft));draft=undo.pop();editEpoch++;dirty=true;stash();draw();},!undo.length),button('重做',()=>{undo.push(copy(draft));draft=redo.pop();editEpoch++;dirty=true;stash();draw();},!redo.length));
    toolbar.append(button('载入已保存版本',async()=>{if(dirty&&!confirm('放弃本机未保存修改，并载入服务端最新剪辑版本？'))return;dirty=false;undo=[];redo=[];editEpoch++;stash();await load();}));
    const advanced=element('details','','edit-advanced');advanced.append(element('summary','工程设置与恢复'));for(const child of [...toolbar.children]){if(child.tagName==='BUTTON'&&!['保存','合成当前工作稿','撤销','重做'].includes(child.textContent))advanced.append(child);}root.append(toolbar,element('p','', 'edit-notice'));
    const layout=element('div','','edit-preview-layout'),clipPanel=element('section','','edit-clips-panel'),playerPanel=element('section','','edit-player-panel');clipPanel.append(element('h3','所有视频片段'),button('预览所有视频',()=>previewClip(0,true),!draft.clips.length));playerPanel.append(element('h3','视频预览'));const stage=element('div','','edit-preview-stage'),player=element('video'),poster=element('img');player.controls=true;player.preload='metadata';poster.hidden=true;stage.append(player,poster);const caption=element('p',draft.clips.length?'':'暂无视频片段','edit-preview-caption'),playback=element('div','','edit-playback-controls');playback.append(button('上一段',()=>previewClip(Math.max(0,previewIndex-1),true),!draft.clips.length),button('播放 / 暂停',()=>{if(player.paused)return player.play();player.pause();},!draft.clips.length),button('下一段',()=>previewClip(Math.min(draft.clips.length-1,previewIndex+1),true),!draft.clips.length));playerPanel.append(stage,caption,playback);layout.append(clipPanel,playerPanel);root.append(layout);previewPlayer=playerPanel;
    if(view?.renderer&&!view.renderer.running)root.append(element('p','后台合成当前未运行。可先保存，在运行设置中继续后台处理后生成。','hint'));
    const settings=element('div','', 'edit-settings');
    for(const [label,key] of [['宽度','width'],['高度','height'],['帧率','fps']]){const field=input(label,draft[key]);field.field.addEventListener('change',()=>{
      const value=Number(field.field.value);
      if(key!=='fps'){mutate(()=>draft[key]=value);return;}
      if(!Number.isInteger(value)||value<12||value>60){field.field.value=draft.fps;error('帧率须为 12–60 的整数。');return;}
      mutate(()=>{
        const scale=value/draft.fps,frame=n=>Math.round(n*scale);
        for(const clip of [...draft.clips,...draft.audio]){
          clip.in_frame=frame(clip.in_frame);clip.out_frame=Math.max(clip.in_frame+1,frame(clip.out_frame));
          for(const name of ['at_frame','fade_in','fade_out'])if(name in clip)clip[name]=frame(clip[name]);
          const duration=clip.out_frame-clip.in_frame;
          if((clip.fade_in||0)+(clip.fade_out||0)>duration)clip.fade_out=Math.max(0,duration-(clip.fade_in||0));
        }
        const total=draft.clips.reduce((sum,clip)=>sum+clip.out_frame-clip.in_frame,0);
        for(const caption of draft.captions){caption.start_frame=Math.min(Math.max(0,total-1),frame(caption.start_frame));caption.end_frame=Math.min(total,Math.max(caption.start_frame+1,frame(caption.end_frame)));}
        draft.fps=value;
      });
    });settings.append(field.wrap);}
    settings.append(element('p','修改帧率会换算所有裁剪、声音与字幕时码，保持实际时长（取整到最近一帧）。','hint'));
    advanced.append(settings);
    if(view?.current){const downloads=element('nav','','edit-downloads');for(const [kind,title]of [['srt','下载已保存字幕'],['project','下载已保存工程及源片']]){const link=element('a',title);link.href=`${base}/edit-workspace/${encodeURIComponent(view.current.id)}/download?kind=${kind}`;downloads.append(link);}advanced.append(downloads);if(dirty)advanced.append(element('p','下载使用上次已保存版本；先保存，才能包含当前修改。','hint'));}
    const library=element('details'),summary=element('summary','添加项目素材');library.append(summary);
    const list=element('div','', 'edit-media-list');
    for(const item of media){if(!['video','image','audio'].includes(item.modality))continue;const row=element('div');row.append(element('span',`${item.name} · ${item.modality}`));
      row.append(button(item.modality==='audio'?'加入声音轨':'加入画面轨',()=>attach(item,item.modality==='audio'?'audio':'clips'),!writable()));
      if(item.modality==='video')row.append(button('仅加入声音',()=>attach(item,'audio'),!writable()));list.append(row);}
    library.append(list);if(media.length<mediaTotal)library.append(button('更多素材',async()=>{const current=generation;const rows=await api(`${base}/media?limit=200&offset=${media.length}`);if(disposed||!sameIdentity()||current!==generation)return;media.push(...rows.items);mediaTotal=rows.total;draw();}));clipPanel.append(library);

    if(draft.clips.length){const strip=element('div','', 'edit-timeline');strip.setAttribute('aria-label','按时间排列的画面片段');let position=0;
      for(const [index,clip] of draft.clips.entries()){const seconds=(clip.out_frame-clip.in_frame)/draft.fps;const item=button(`${index+1} · ${position.toFixed(1)}–${(position+seconds).toFixed(1)} 秒`,()=>{root.querySelector(`[data-clip-id="${CSS.escape(clip.id)}"]`)?.scrollIntoView({block:'center',behavior:'smooth'});});item.style.flexGrow=seconds;item.title=name(clip.media_id);strip.append(item);position+=seconds;}
      playerPanel.append(strip,element('p',`总时长 ${position.toFixed(2)} 秒 · ${draft.clips.length} 段`,'hint'));}
    renderTrack('clips',clipPanel);if(!draft.clips.length)clipPanel.append(element('p','暂无视频片段，添加素材开始剪辑。','edit-empty'));else previewClip(Math.min(previewIndex,draft.clips.length-1));
    const sound=element('details','','edit-sound-panel');sound.append(element('summary','背景音乐、配音与音效'));renderTrack('audio',sound);root.append(sound);
    const captions=element('details'),label=element('label','手工字幕（SRT 时码）'),textarea=element('textarea','','edit-srt');textarea.rows=7;
    if(!captionDirty)captionText=captionDocument();textarea.value=captionText||'';captions.open=captionsOpen||captionDirty;
    captions.addEventListener('toggle',()=>{captionsOpen=captions.open;});
    textarea.addEventListener('input',()=>{captionText=textarea.value;captionDirty=captionText!==captionDocument();captionsOpen=true;stashCaption();const notice=root.querySelector('.edit-caption-state');if(notice)notice.textContent=captionDirty?'字幕输入尚未应用；保存与合成只使用已应用字幕。':'字幕输入已应用到工作稿。';});
    label.append(textarea);captions.append(element('summary','字幕'),label,button('应用字幕',()=>{
      const blocks=textarea.value.trim()?textarea.value.trim().split(/\r?\n\s*\r?\n/):[],parsed=[];
      const time=s=>{const m=s.match(/^(\d+):(\d{2}):(\d{2})[,.](\d{3})$/);if(!m)throw new Error('字幕时码格式应为 00:00:01,000');return Math.round((+m[1]*3600 + +m[2]*60 + +m[3]+ +m[4]/1000)*draft.fps);};
      for(const block of blocks){const lines=block.split(/\r?\n/);if(/^\d+$/.test(lines[0]))lines.shift();const range=lines.shift()?.split(/\s+-->\s+/);if(range?.length!==2)throw new Error('每条字幕须有起止时间');parsed.push({start_frame:time(range[0]),end_frame:time(range[1]),text:lines.join('\n')});}
      captionDirty=false;captionText=textarea.value;mutate(()=>draft.captions=parsed);stashCaption();
    },!writable()),button('放弃未应用字幕',()=>{captionDirty=false;captionText=captionDocument();textarea.value=captionText;stashCaption();draw();},!writable()),element('p',captionDirty?'字幕输入尚未应用；保存与合成只使用已应用字幕。':'字幕输入已应用到工作稿。','edit-caption-state'));root.append(captions);
    if(focused){textarea.focus({preventScroll:true});textarea.setSelectionRange(...selection);}
    if(view?.history?.length>1){const history=element('details');history.append(element('summary','已保存版本'));for(const version of view.history){history.append(button(`恢复 v${version.version}`,async()=>{if(dirty)throw new Error('请先保存当前修改，再恢复历史版');await write('/edit-workspace',{episode_id:episodeId,edit_revision:view.workspace.revision,restore_version_id:version.id});await load();},!writable()));}advanced.append(history);}
    const exports=element('section');exports.append(element('h3','合成结果'));
    for(const job of view?.renders||[]){const card=element('article','', 'edit-export');card.dataset.jobId=job.id;card.append(element('p',`${job.status==='succeeded'?'已完成':job.status==='failed'?'合成失败':job.status==='cancelled'?'已取消':job.cancel_requested?'正在取消':job.status==='running'?'正在合成':'等待合成'}${job.edit_version_id!==view.current?.id?' · 历史剪辑版本':''}`));
      if(job.error)card.append(element('p',job.error));
      if(job.content_url){const video=element('video');video.controls=true;video.preload='metadata';video.src=job.content_url;const links=element('nav','','edit-downloads'),link=element('a','下载工作稿'),cover=element('a','下载当前画面为封面');link.href=job.content_url+'?download=true';cover.href=`${base}/edit-exports/${job.id}/cover`;cover.onclick=()=>{cover.href=`${base}/edit-exports/${job.id}/cover?at_ms=${Math.max(0,Math.min(Math.floor(video.currentTime*1000),Math.ceil(video.duration*1000)-1)||0)}`;};links.append(link,cover);card.append(video,links);}
      if(['queued','running'].includes(job.status))card.append(button(job.cancel_requested?'取消请求已收到':'取消此合成',async()=>{await write(`/edit-exports/${encodeURIComponent(job.id)}/cancel`,{job_id:job.id});await load();},!writable()||job.cancel_requested));
      if(['failed','cancelled'].includes(job.status))card.append(button('恢复此版本合成',async()=>{await write('/edit-exports',{edit_version_id:job.edit_version_id});await load();},!writable()));exports.append(card);}
    root.append(advanced,exports);
  }
  async function load(){
    if(disposed)return;if(!sameIdentity()){root.replaceChildren(element('p','操作身份已切换，请重新进入本集剪辑。'));return;}captureCaption();const current=++generation;if(!episodeId){root.replaceChildren(element('p','先从集列表进入需要剪辑的一集。'));return;}
    const data=await api(`${base}/edit-workspace?episode_id=${encodeURIComponent(episodeId)}`);if(disposed||!sameIdentity()||current!==generation)return;
    view=data;if(!dirty){draft=copy(data.current?.document||empty());draftRevision=data.workspace?.revision||0;}
    const resources=await api(`${base}/media?limit=200`);if(disposed||!sameIdentity()||current!==generation)return;media=resources.items||[];mediaTotal=resources.total||media.length;draw();
    clearTimeout(poll);if(data.renders.some(r=>['queued','running'].includes(r.status)))poll=setTimeout(()=>load().catch(e=>error(e.message)),3000);
  }
  return {load,suspend(){if(disposed)return;captureCaption();stashCaption();disposed=true;generation++;clearTimeout(poll);root.querySelectorAll('dialog').forEach(dialog=>dialog.close());},save};
}
