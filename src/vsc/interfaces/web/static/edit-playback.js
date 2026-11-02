import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* One timeline clock for picture trims, sound tracks and captions. */
export function createEditPlayback({stage, video, poster, document:edit, media, url, onPosition, onError}) {
  const subtitle=globalThis.document.createElement('div');subtitle.className='edit-preview-subtitle';stage.append(subtitle);
  const soundtrack=edit.audio.map(clip=>({clip,element:globalThis.document.createElement('audio')}));
  for(const item of soundtrack){item.element.preload='metadata';item.element.src=url(item.clip.media_id);}
  let frame=0,playing=false,origin=0,raf=0,index=-1,disposed=false,context=null;
  const gains=new Map(),starts=[];let total=0;
  for(const clip of edit.clips){starts.push(total);total+=clip.out_frame-clip.in_frame;}
  function gain(element,value){
    if(context){let node=gains.get(element);if(!node){const source=context.createMediaElementSource(element);node=context.createGain();source.connect(node);node.connect(context.destination);gains.set(element,node);}node.gain.value=value;element.volume=1;}
    else element.volume=Math.min(1,Math.max(0,value));
  }
  function synchronize(element,time,active,volume){
    gain(element,volume);element.muted=volume===0;
    if(Number.isFinite(element.duration)&&Math.abs(element.currentTime-time)>.10)element.currentTime=Math.min(element.duration,Math.max(0,time));
    if(active&&element.paused)element.play().catch(error=>{if(!disposed&&playing&&error.name!=='AbortError')onError?.('预览声音或画面无法播放，请检查素材。');});
    else if(!active&&!element.paused)element.pause();
  }
  function paint(){
    const next=starts.findIndex((start,i)=>frame>=start&&frame<start+edit.clips[i].out_frame-edit.clips[i].in_frame);
    if(next>=0){
      const clip=edit.clips[next],isImage=media.find(item=>item.id===clip.media_id)?.modality==='image';
      if(next!==index){index=next;video.pause();video.hidden=isImage;poster.hidden=!isImage;if(isImage){poster.src=url(clip.media_id);bindAttribute(poster,"alt",msg("ui.current_image_clip"));}else video.src=url(clip.media_id);}
      const local=frame-starts[next],duration=clip.out_frame-clip.in_frame;
      const alpha=Math.min(clip.fade_in_frames?Math.max(0,local/clip.fade_in_frames):1,clip.fade_out_frames?Math.max(0,(duration-1-local)/clip.fade_out_frames):1,1);
      video.style.opacity=poster.style.opacity=String(alpha);stage.style.backgroundColor='black';
      if(!isImage)synchronize(video,(clip.in_frame+frame-starts[next])/edit.fps,playing,clip.muted?0:clip.volume??1);
    }
    for(const {clip,element} of soundtrack){
      const offset=frame-(clip.at_frame||0),length=clip.out_frame-clip.in_frame,active=offset>=0&&offset<length;
      let volume=clip.muted||!active?0:clip.volume??1;
      if(clip.fade_in)volume*=Math.min(1,Math.max(0,offset/clip.fade_in));
      if(clip.fade_out)volume*=Math.min(1,Math.max(0,(length-offset)/clip.fade_out));
      synchronize(element,(clip.in_frame+Math.max(0,offset))/edit.fps,playing&&active,volume);
    }
    setText(subtitle,edit.captions.filter(c=>frame>=c.start_frame&&frame<c.end_frame).map(c=>c.text).join('\n'));
    onPosition?.({frame,total,index,playing});
  }
  function tick(now){if(disposed||!playing)return;frame=Math.min(total,(now-origin)*edit.fps/1000);if(frame>=total){frame=Math.max(0,total-1);pause();return;}paint();raf=requestAnimationFrame(tick);}
  function pause(){playing=false;cancelAnimationFrame(raf);video.pause();for(const item of soundtrack)item.element.pause();paint();}
  function play(){if(disposed||!total)return;if(frame>=total-1)frame=0;const Audio=globalThis.AudioContext||globalThis.webkitAudioContext;if(Audio&&!context)context=new Audio();context?.resume().catch(()=>{});playing=true;origin=performance.now()-frame*1000/edit.fps;paint();cancelAnimationFrame(raf);raf=requestAnimationFrame(tick);}
  function seek(value){frame=Math.min(Math.max(0,value),Math.max(0,total-1));origin=performance.now()-frame*1000/edit.fps;paint();}
  video.controls=false;video.onloadedmetadata=()=>paint();paint();
  return {play,pause,toggle(){playing?pause():play();},seek,clip(i,autoplay=false){seek(starts[i]||0);if(autoplay)play();},
    dispose(){disposed=true;playing=false;cancelAnimationFrame(raf);video.pause();video.onloadedmetadata=null;video.style.opacity=poster.style.opacity='';for(const item of soundtrack){item.element.pause();item.element.removeAttribute('src');item.element.load();}context?.close().catch(()=>{});subtitle.remove();}};
}
