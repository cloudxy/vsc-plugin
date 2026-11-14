// Official publication uses the generated image and frozen, nonsecret provenance.
// The browser recipe history remains local; only a server receipt means published.
export function imageExtension(url='',mime=''){
 const type=(mime||/^data:([^;,]+)/i.exec(url)?.[1]||'').toLowerCase().split(';')[0];
 const known={'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif','image/avif':'avif'};
 if(known[type])return known[type];
 return /\.(png|jpe?g|webp|gif|avif)(?:[?#]|$)/i.exec(url)?.[1]?.toLowerCase()||'img';
}
export async function generatedImageBlob(result){
 const inline=/^data:(image\/[a-z0-9.+-]+)(;base64)?,([\s\S]*)$/i.exec(result.imageUrl);
 if(inline){
  const raw=inline[2]?atob(inline[3]):decodeURIComponent(inline[3]);
  const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
  if(!bytes.length)throw new Error('生成结果不是可上传的图片');
  return new Blob([bytes],{type:inline[1].toLowerCase()});
 }
 const response=await fetch(result.imageUrl);
 if(!response.ok)throw new Error('无法读取这次生成的图片，请检查网络后重试');
 const blob=await response.blob();
 if(!blob.size||!blob.type.startsWith('image/'))throw new Error('生成结果不是可上传的图片');
 return blob;
}
export const defaultResultTitle=result=>(result.recipeSummary&&result.recipeSummary!=='自定义合成'?result.recipeSummary:'AI 角色')+' · '+new Date(result.createdAt).toLocaleString('zh-CN');
export async function newPublication(result,actor,title){
 const bytes=new TextEncoder().encode(JSON.stringify([actor,result.id]));
 const digest=await crypto.subtle.digest('SHA-256',bytes);
 const key='character-studio-'+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
 const provider=String(result.provider||'未知供应商'),model=String(result.model||'未知模型');
 const description=`AI角色合成台生成；供应商：${provider}；模型：${model}；生成时间：${new Date(result.createdAt).toISOString()}；本地结果：${result.id}`;
 const references={};
 for(const slot of ['portrait','costume','pose']){
  const item=result.snapshot?.recipe?.[slot];
  if(item)references[slot]={id:item.id||'',source:item.source||'',name:item.标题||item.发型名称||item.服装名称||item.姿势名称||''};
 }
 return {actor,title,phase:'prepared',importPayload:{library_key:key,title,category:'image',description,
  specification:{source:'character-studio',result_id:result.id,provider,model,generated_at:result.createdAt,prompt:result.prompt||'',style_preset:result.snapshot?.settings?.stylePreset||'',references},
  allowed_purposes:['identity_face'],license:{outcome:'licensed',allow_workspace_reuse:true,evidence:`用户明确确认有权将本次生成图片在工作区共享与复用；供应商：${provider}；模型：${model}；此确认不替代供应商条款或来源许可。`},
  import_key:key,members:[]},commandKey:key};
}
export function publicationPayload(publication){
 const receipt=publication.importReceipt;
 return {entry_id:receipt.entry_id,library_version_id:receipt.library_version_id||receipt.version_id,asset_kind:'character',role_level:'unspecified',role_tag:'AI角色合成',gender:'unspecified',age_band:'unspecified',notes:publication.importPayload.description,command_key:publication.commandKey};
}

export function officialResultRoute(receipt){return {tab:'official',kind:'character',entry:receipt.entry_id};}
const publicationDialogs=new Map();

// Shared by the current-result actions and the local-history recovery menu.
// Store is supplied by each consumer to keep state ownership in one module.
export async function openCharacterPublication(record,ctx,store,{restoreFocus,isActive=()=>true}={}){
 const origin=document.activeElement;
 const restore=()=>{if(restoreFocus){restoreFocus();return;}const target=origin?.isConnected?origin:origin?.dataset?.focusKey?document.querySelector(`[data-focus-key="${origin.dataset.focusKey}"]`):origin?.dataset?.busyKey?document.querySelector(`[data-busy-key="${origin.dataset.busyKey}"]`):null;target?.focus?.();};
 if(!isActive())return false;
 const existing=publicationDialogs.get(record.id);if(existing?.isConnected){existing.focus?.();return existing;}
 const checked=await store.checkOfficialPublication(record.id);if(!checked){restore();return false;}
 if(!isActive())return false;
 const dialog=document.createElement('dialog');dialog.className='cs-dialog cs-publication';dialog.setAttribute('aria-label','放入官方资产库');
 const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
 const title=node('h2','','放入官方资产库'),intro=node('p','cs-field-hint','目标：官方资产 · 人设。图片与生成说明将保存到服务端，供工作区复用。AI角色合成库仍是当前浏览器中的本地配方与生成记录。');
 const preview=node('img','cs-publication-preview');preview.src=record.imageUrl;preview.alt='将入库的这次生成结果';
 const label=node('label','cs-field'),name=node('input');name.type='text';name.maxLength=200;name.value=record.publication?.title||defaultResultTitle(record);name.setAttribute('aria-label','资产名称');name.disabled=Boolean(record.publication);
 label.append(node('span','cs-field-label','资产名称'),name);
 const permission=node('label','cs-publication-permission'),checkbox=node('input');checkbox.type='checkbox';checkbox.checked=false;
 permission.append(checkbox,node('span','','我确认有权将这张生成图片及生成说明在工作区共享与复用，并已核对参考素材与供应商的使用条件。'));
 const feedback=node('p','cs-publication-feedback');feedback.setAttribute('role','status');
 if(record.publication)feedback.textContent='将使用已确认的名称与原请求继续入库，已完成的步骤不会重复执行。';
 const footer=node('div','cs-dialog-foot'),cancel=node('button','','取消'),confirm=node('button','cs-primary','确认入库');cancel.type=confirm.type='button';confirm.disabled=true;
 const update=()=>{confirm.disabled=!checkbox.checked||!name.value.trim();};checkbox.onchange=update;name.oninput=update;
 let submitted=false;
 const unsubscribe=store.subscribe(s=>{
  if(!submitted||s.publicationTask?.resultId!==record.id)return;
  const labels={checking:'正在检查入库权限…',uploading:'正在上传结果…',importing:'正在保存共享版本…',publishing:'正在发布到官方资产库…'};
  confirm.textContent=labels[s.publicationTask.phase]||'入库中…';feedback.textContent=confirm.textContent;
 });
 cancel.onclick=()=>dialog.close();
 confirm.onclick=async()=>{
  if(submitted||confirm.disabled)return;submitted=true;
  confirm.disabled=true;cancel.disabled=true;name.disabled=true;checkbox.disabled=true;confirm.textContent='入库中…';confirm.setAttribute('aria-busy','true');
  const receipt=await store.publishCurrentResult(record.id,{title:name.value,allowWorkspaceReuse:checkbox.checked,actor:checked.actor});
  confirm.removeAttribute('aria-busy');cancel.disabled=false;
  if(receipt){dialog.close();return;}
  submitted=false;const latest=store.getState().currentResult?.id===record.id?store.getState().currentResult:store.getState().history.find(x=>x.id===record.id);
  name.disabled=Boolean(latest?.publication);checkbox.disabled=false;confirm.textContent='重试入库';update();feedback.textContent=latest?.publication?.lastError||(store.getState().resultErrorId===record.id?store.getState().resultError:'')||'入库未完成，图片与已完成的步骤已保留，请重试';
 };
 dialog.addEventListener('cancel',event=>{if(submitted)event.preventDefault();});
 dialog.addEventListener('close',()=>{unsubscribe();publicationDialogs.delete(record.id);dialog.remove();restore();});
 footer.append(cancel,confirm);dialog.append(title,intro,preview,label,permission,feedback,footer);document.body.append(dialog);publicationDialogs.set(record.id,dialog);dialog.showModal?.();(name.disabled?checkbox:name).focus?.();return dialog;
}
