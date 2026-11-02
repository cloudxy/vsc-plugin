import './classic-controls-messages.js';
import {msg,setText,bindAttribute,option} from './i18n.js';
const label=key=>msg('classic_controls.'+key);
const el=(tag,text)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);return n;};
// This controller keeps each result attached to its original draft. Applying is a local edit.
export function mountPromptAssist(host,{state,saveDraft,getDraft,write,read,isCurrent,remember,onApply,writable,notice}){
  const tools=el('div'),result=el('section');tools.className='classic-prompt-tools';result.className='classic-prompt-suggestion';
  const smart=el('input');smart.type='checkbox';smart.checked=state.assistSmart!==false;bindAttribute(smart,'aria-label',label('smart_refs'));
  const smartLabel=el('label',label('smart_refs'));smartLabel.append(smart);bindAttribute(smartLabel,'title',label('smart_hint'));
  const language=el('select');bindAttribute(language,'aria-label',label('language'));for(const [id,title]of [['en','English'],['zh-cn','简体中文'],['ja','日本語'],['ko','한국어']])language.append(option(id,title));language.value=state.assistLanguage||'en';
  smart.addEventListener('change',()=>{state.assistSmart=smart.checked;remember();});language.addEventListener('change',()=>{state.assistLanguage=language.value;remember();});
  tools.append(smartLabel,language);host.prepend(tools);host.append(result);let busy=false;const buttons=[];
  function button(text,fn){const b=el('button',text);b.type='button';b.addEventListener('click',async()=>{if(b.disabled)return;try{await fn();}catch(error){if(isCurrent())notice(error.message);}finally{if(isCurrent())draw();}});return b;}
  const unchanged=()=>state.assist?.snapshot===JSON.stringify(getDraft().document);
  async function recover(){
    if(busy||!state.assist)return;busy=true;draw();
    try{const a=state.assist;a.value=a.value?.id?await read(a.value.id):await write(a.request);remember();}
    finally{busy=false;if(isCurrent())draw();}
  }
  async function request(operation){
    if(busy)return;busy=true;draw();
    try{
      await saveDraft();if(!isCurrent())return;const current=getDraft();if(current.dirty)throw new Error(String(label('changed')));
      const request={draft_version_id:current.saved.id,draft_sha256:current.saved.sha256,operation,target_language:language.value,include_references:smart.checked};
      state.assist={request,snapshot:JSON.stringify(current.document),value:null};remember();
      state.assist.value=await write(request);remember();
    }catch(error){if(error.status>=400&&error.status<500){state.assist=null;remember();}throw error;}finally{busy=false;if(isCurrent())draw();}
  }
  for(const kind of ['translate','optimize','recognize']){const b=button(label(kind),()=>request(kind));b.dataset.promptAction=kind;buttons.push(b);tools.append(b);}
  function draw(){
    if(!isCurrent())return;const a=state.assist,v=a?.value,unknown=Boolean(a&&(!v||v.status==='submission_unknown'));
    for(const b of buttons)b.disabled=!writable||busy||unknown;
    language.disabled=smart.disabled=busy||unknown;result.replaceChildren();result.hidden=!a&&!busy;
    if(busy){result.append(el('p',label('working')));return;}
    if(!a)return;
    if(unknown){result.append(el('p',label('unknown')),button(label('recover'),recover));return;}
    if(v.status!=='completed'){result.append(el('p',msg('classic_controls.failed',{value:v.error||v.status})));return;}
    result.append(el('h3',label('suggestion')),el('p',label('suggestion_only')),el('pre',v.result.text),el('p',v.result.explanation));
    const apply=button(label('apply'),()=>{if(!unchanged())throw new Error(String(label('changed')));onApply(v.result.text);state.assist=null;remember();});apply.disabled=!writable||!unchanged();result.append(apply,button(label('discard'),()=>{state.assist=null;remember();}));
    if(!unchanged())result.append(el('p',label('changed')));
  }
  draw();return {refresh:draw};
}
