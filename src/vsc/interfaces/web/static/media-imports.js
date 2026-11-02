import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Fixed manifests keep completed items when a later file fails. */
const el=(tag,text='')=>{const n=document.createElement(tag);setText(n,text);return n;};
const field=(title,type='text')=>{const label=el('label',title),input=el('input');input.type=type;label.append(input);return {label,input};};
const statusNames={awaiting_upload:'等待上传',uploaded:'已上传，待登记',completed:'已登记',failed:'本文件受阻',cancelled:'已取消'};
async function sha(file){const bytes=await file.arrayBuffer();return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}

export function createMediaImports({root,api,project,episodeId,session,onChange,initialBatchId=null}){
 let disposed=false,busy=false,generation=0,batches=[],current=null,revision=0,selectedFiles=new Map(),transfer=null,createIntent=null,nextOffset=null;
 const base=`/api/v1/projects/${encodeURIComponent(project)}/media-imports`,auth=()=>typeof session==='function'?session():session;
 const writable=()=>!!(auth()?.actor&&auth()?.writable);
 function note(text){const n=root.querySelector('.import-notice');if(n)setText(n,text);}
 function refreshButtons(){for(const n of root.querySelectorAll('button[data-import-base-disabled]'))n.disabled=n.dataset.importBaseDisabled==='true'||(busy&&n.dataset.importWhileBusy!=='true');}
 function button(text,fn,disabled=false,whileBusy=false){const n=el('button',text);n.type='button';n.dataset.importBaseDisabled=String(disabled);n.dataset.importWhileBusy=String(whileBusy);n.disabled=disabled||(busy&&!whileBusy);n.onclick=async()=>{if(busy&&!whileBusy)return;if(!whileBusy)busy=true;refreshButtons();try{await fn();}catch(e){if(!disposed)note(e.message);}finally{if(!whileBusy)busy=false;if(!disposed)refreshButtons();}};return n;}
 async function write(path,payload,key){const r=await api(base+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth().csrf},body:JSON.stringify({payload,expected_revision:revision,idempotency_key:key})});if(!disposed){revision=r.revision??revision;onChange?.(r);}return r;}
 async function readBatch(id){const g=++generation,r=await api(base+'/'+encodeURIComponent(id));if(disposed||g!==generation)return;current=r;revision=r.revision;return r;}
 async function process(item){await readBatch(current.batch.id);if(disposed)return;await write('/process',{batch_id:current.batch.id,item_id:item.id},'media-import-process:'+item.id);await readBatch(current.batch.id);if(!disposed)draw();}
 async function upload(item){
  const file=selectedFiles.get(item.expected_sha256);if(!file)throw new Error('请重新选择清单中的原文件，内容摘要匹配后可续传。');
  const batchId=current.batch.id;await readBatch(batchId);if(disposed)return;item=current.items.find(i=>i.id===item.id);
  if(item.status==='completed'||item.has_upload)return;
  let offset=item.uploaded_bytes;transfer=new AbortController();draw();
  try{
   do{const end=Math.min(file.size,offset+8*1024*1024);const result=await api(`${base}/${batchId}/items/${item.id}/upload?offset=${offset}`,{method:'PUT',headers:{'X-CSRF-Token':auth().csrf,'Content-Type':'application/octet-stream'},body:file.slice(offset,end),signal:transfer.signal});if(disposed)return;offset=result.uploaded_bytes;revision=result.revision??revision;note(`${item.filename}：已接收 ${(offset/1048576).toFixed(1)} / ${(file.size/1048576).toFixed(1)} MiB`);if(offset===file.size)break;}while(offset<file.size);
  }finally{transfer=null;if(!disposed){await readBatch(batchId);draw();}}
 }
 async function continueAll(){
  const batchId=current.batch.id,ids=current.items.map(i=>i.id);let failures=0;
  for(const id of ids){if(disposed)break;await readBatch(batchId);const item=current.items.find(i=>i.id===id);if(['completed','cancelled'].includes(item.status))continue;
   try{if(!item.has_upload)await upload(item);if(disposed)break;await readBatch(batchId);if(current.items.find(i=>i.id===id).has_upload)await process(item);}catch(e){if(e.name==='AbortError'){note('上传已暂停，已收到的分片会保留。');return;}failures++;note(`${item.filename}：${e.message}`);}
  }if(!disposed){await readBatch(batchId);draw();note(failures?`${failures} 个文件受阻，其余结果已保留。`:'本批可处理文件已完成。');}
 }
 async function select(files){const rows=[];for(const file of files){if(disposed)return [];note('正在计算文件摘要：'+file.name);const digest=await sha(file);selectedFiles.set(digest,file);rows.push({filename:file.name,size_bytes:file.size,sha256:digest});}return rows;}
 function draw(){
  if(disposed)return;root.replaceChildren();root.className='media-imports';root.append(el('h2',msg("ui.batch_media_import")),el('p',msg("ui.upload_register_and_recover_files_individually_retrying_the_same")));const notice=el('p');notice.className='import-notice';notice.setAttribute('role','status');root.append(notice);
  const form=el('form'),files=field(msg("ui.select_local_files"),'file');files.input.multiple=true;const title=field(msg("ui.batch_name"));title.input.value='素材导入';const evidence=field(msg("ui.source_and_basis_for_use"));
  const kind=el('select'),kindLabel=el('label',msg("ui.asset_type_after_registration"));bindAttribute(kind,'aria-label',msg("ui.asset_type_after_registration"));for(const [value,text]of [['',msg("ui.add_to_project_media_only")],['character',msg("ui.character_reference_image")],['location',msg("ui.location_reference_image")],['prop',msg("ui.prop_reference_image")],['voice',msg("ui.audio_reference")]]){const o=el('option',text);o.value=value;kind.append(o);}kindLabel.append(kind);
  const rights=el('select'),rightsLabel=el('label',msg("ui.media_rights"));bindAttribute(rights,'aria-label',msg("ui.media_rights"));for(const [value,text]of [['unknown',msg("agent.overseas_remake_workflow_status_2")],['owned',msg("ui.owned")],['licensed',msg("ui.authorized")]]){const o=el('option',text);o.value=value;rights.append(o);}rightsLabel.append(rights);const scope=field(msg("ui.authorized_purposes_comma_separated"));bindAttribute(scope.input,"placeholder",msg("ui.for_example_identity_face_video_take"));
  const create=button(msg("ui.create_manifest_and_import"),async()=>{if(!files.input.files.length)throw new Error('先选择文件');const manifest=await select([...files.input.files]);if(disposed)return;const payload={title:title.input.value,files:manifest,rights:rights.value,source_evidence:evidence.input.value,...(kind.value?{asset_kind:kind.value}:{}),...(episodeId?{episode_id:episodeId}:{})};if(rights.value==='licensed')payload.rights_scope={purposes:scope.input.value.split(',').map(s=>s.trim()).filter(Boolean)};const signature=JSON.stringify(payload);if(createIntent?.signature!==signature)createIntent={signature,key:crypto.randomUUID()};const r=await write('',payload,createIntent.key);if(disposed)return;createIntent=null;await readBatch(r.id);draw();await continueAll();},!writable());
  form.onsubmit=e=>e.preventDefault();form.append(title.label,files.label,kindLabel,rightsLabel,evidence.label,scope.label,create);root.append(form);
  const list=el('section');list.append(el('h3',msg("ui.existing_import_manifests")));for(const batch of batches){const entry=el('div');entry.append(button(batch.title,async()=>{await readBatch(batch.id);draw();}),el('small',new Date(batch.created_at).toLocaleString()));list.append(entry);}if(nextOffset!=null)list.append(button(msg("ui.load_earlier_manifests"),async()=>{const page=await api(base+'?offset='+nextOffset);if(disposed)return;const known=new Set(batches.map(r=>r.id));batches.push(...page.items.filter(r=>!known.has(r.id)));nextOffset=page.next_offset;draw();}));root.append(list);
  if(!current)return;const section=el('section');section.append(el('h3',current.batch.title));const picker=field(msg("ui.select_the_original_files_again_to_resume"),'file');picker.input.multiple=true;picker.input.onchange=async()=>{try{await select([...picker.input.files]);note('已匹配本机原文件，可继续未完成项。');}catch(e){note(e.message);}};section.append(picker.label,button(msg("ui.continue_unfinished_files"),continueAll,!writable()||!!transfer));if(transfer)section.append(button(msg("ui.pause_current_upload"),()=>transfer?.abort(),false,true));
  const table=el('div');table.className='import-items';
  for(const item of current.items){const card=el('article');card.append(el('strong',item.filename),el('p',joinMessages(["",statusNames[item.status]," · ",(item.uploaded_bytes/1048576).toFixed(1)," / ",(item.size_bytes/1048576).toFixed(1)," MiB"])));if(item.error)card.append(el('p',item.error));if(item.media_id){const link=el('a',msg("ui.view_registered_media"));link.href=`?page=media&project=${project}`;card.append(link);}else if(item.status!=='cancelled'){
    card.append(button(item.has_upload?msg("ui.register_this_file"):msg("ui.upload_or_resume"),async()=>{if(item.has_upload)await process(item);else await upload(item);},!writable()||!!transfer),button(msg("ui.cancel_this_file"),async()=>{await readBatch(current.batch.id);await write('/cancel',{batch_id:current.batch.id,item_id:item.id},'import-cancel:'+item.id);await readBatch(current.batch.id);draw();},!writable()||!!transfer));}
   table.append(card);
  }section.append(table);root.append(section);
 }
 async function load(){disposed=false;const g=++generation;const data=await api(base);if(disposed||g!==generation)return;batches=data.items;nextOffset=data.next_offset;revision=data.revision;if(current||initialBatchId)await readBatch(current?.batch.id||initialBatchId);draw();}
 return {load,suspend(){disposed=true;generation++;transfer?.abort();}};
}
