import {setText,bindAttribute,msg} from './i18n.js';

// Persistent by default; callers opt successful transient feedback into a lifetime.
export function createNotice(host){
 let epoch=0,delay=null,fade=null;
 function clearTimers(){clearTimeout(delay);clearTimeout(fade);delay=null;fade=null;}
 function dismiss(){epoch++;clearTimers();host.hidden=true;host.classList.remove('notice-leaving');host.replaceChildren();}
 function show(message,options={}){
  dismiss();if(!message)return;
  const ticket=epoch;
  setText(host,message);host.hidden=false;
  const close=host.ownerDocument.createElement('button');close.type='button';close.className='notice-close';close.textContent='×';
  bindAttribute(close,'aria-label',msg('common.close'));bindAttribute(close,'title',msg('common.close'));
  close.addEventListener('click',()=>{if(ticket===epoch)dismiss();});host.prepend(close);
  const duration=options?.duration;
  if(Number.isFinite(duration)&&duration>0)delay=setTimeout(()=>{
   if(ticket!==epoch)return;
   host.classList.add('notice-leaving');
   fade=setTimeout(()=>{if(ticket===epoch)dismiss();},300);
  },duration);
 }
 return {show,dismiss};
}
