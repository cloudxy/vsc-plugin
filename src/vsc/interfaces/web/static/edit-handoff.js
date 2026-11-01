/* Explicit mapping to original selections; no approval from the editor itself. */
const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n;};
export async function openEditHandoff(root,{api,base,versionId,session,write,onArtifact,name,alive}){
 const options=await api(`${base}/edit-workspace/${versionId}/timeline-options`);if(!alive())return;
 const dialog=el('dialog'),form=el('form'),report=el('p');report.setAttribute('role','status');dialog.setAttribute('aria-label','正式时间线交接');
 form.append(el('h2','转为正式时间线'),el('p','保留当前剪辑的时码、声音和字幕。为每个片段明确原选片及采用决定，生成待审稿后沿原批准入口继续。'));
 const control=(parent,title,node)=>{const label=el('label',title);node.setAttribute('aria-label',title);label.append(node);parent.append(label);return node;};
 const choice=control(form,'已批准选片清单',el('select'));choice.append(new Option('请选择原选片清单',''));for(const row of options.selected_takes)choice.append(new Option(row.title,row.id));
 if(!options.selected_takes.length)form.append(el('p','本集暂无有效的已批准选片清单。请在原制作流程完成选片后再交接。'));
 const clips=el('section'),actions=el('div'),previewButton=el('button','预览时间线'),save=el('button','登记待审时间线'),close=el('button','关闭');for(const n of [previewButton,save,close])n.type='button';save.disabled=true;close.onclick=()=>dialog.close();actions.append(previewButton,save,close);form.append(clips,actions,report);dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
 let fields=[],preview=null,request=null,inputEpoch=0;
 function draw(){clips.replaceChildren();fields=[];preview=null;save.disabled=true;const selected=options.selected_takes.find(row=>row.id===choice.value);
  for(const [index,member] of options.members.entries()){
   const card=el('fieldset'),legend=el('legend',`${index+1}. ${name(member.media_id)} · ${member.track==='audio'?'声音':'画面'}`);card.append(legend);
   const item=control(card,'选片项 '+(index+1),el('select'));item.append(new Option('请选择对应选片项',''));
   for(const value of selected?.document.items||[])if(value.media.sha256===member.blob_sha256)item.append(new Option(`${value.shot_id||value.cue_id||''} · ${value.id} · ${value.purpose}`,value.id));
   const decision=control(card,'采用决定 '+(index+1),el('select'));decision.append(new Option('请选择已采用用途',''));for(const value of member.decisions)decision.append(new Option(value.role+' · '+value.target_object_id.slice(0,8),value.id));
   const audio=control(card,'声音用途 '+(index+1),el('select'));for(const [value,title]of [['none','无声音（静音片段）'],['native','视频原声'],['dialogue','对白'],['narration','旁白'],['music','音乐'],['ambience','环境'],['sfx','音效']])audio.append(new Option(title,value));
   const cue=control(card,'已批准声音 Cue '+(index+1),el('select'));cue.append(new Option('无声音时留空',''));const cues=[];for(const plan of options.sound_plans)for(const [id,value]of Object.entries(plan.cues)){if(value.silence)continue;cues.push({id,plan_id:plan.id});cue.append(new Option(plan.title+' · '+id,String(cues.length-1)));}
   const reuse=control(card,'重复使用说明 '+(index+1),el('input'));reuse.placeholder='同一选片有意重播时说明原因';card.append(el('p','选片项按固定字节筛选，必须明确选择；不会按摘要自动认定媒体身份。'));clips.append(card);fields.push({member,item,decision,audio,cue,cues,reuse});
  }
 }
 choice.onchange=draw;form.oninput=()=>{inputEpoch++;preview=null;save.disabled=true;};draw();
 previewButton.onclick=async()=>{const epoch=inputEpoch;previewButton.disabled=true;save.disabled=true;try{
  if(!choice.value)throw new Error('请选择已批准选片清单');const assignments={};
  for(const row of fields){if(!row.item.value||!row.decision.value)throw new Error('请为每个片段选择原选片项及采用决定');const cue=row.cue.value===''?null:row.cues[Number(row.cue.value)];assignments[row.member.clip_key]={selected_item_id:row.item.value,binding_decision_id:row.decision.value,audio_role:row.audio.value,cue_id:cue?.id||null,sound_plan_id:cue?.plan_id||null,reuse_reason:row.reuse.value.trim()};}
  request={edit_version_id:versionId,selected_takes_id:choice.value,assignments};
  const result=await api(base+'/edit-timeline/preview',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request})});if(!alive()||!dialog.open||epoch!==inputEpoch)return;preview=result;report.textContent=`已固定 ${result.artifact.document.render_plan.segments.length} 个画面、声音和字幕片段。登记后仍须原时间线批准。`;save.disabled=false;
 }catch(e){report.textContent=e.message;}finally{previewButton.disabled=false;}};
 save.onclick=async()=>{if(!preview)return;save.disabled=true;try{const result=await write('/edit-timeline/proposals',{request,preview_sha256:preview.preview_sha256});if(!alive()||!dialog.open)return;report.textContent='待审时间线已登记，剪辑工作稿和原素材仍保留。';const open=el('button','打开原时间线审阅');open.type='button';open.onclick=()=>onArtifact?.(result.artifact_id);actions.append(open);}catch(e){report.textContent=e.message;save.disabled=false;}};
 for(const row of options.handoffs||[]){const section=el('section');section.append(el('p',row.timeline_id?'此工作稿已有冻结的正式时间线':row.approved?'此工作稿的时间线已批准，可冻结':'此工作稿已有待审时间线'));const open=el('button','打开时间线审阅');open.type='button';open.onclick=()=>onArtifact?.(row.artifact_id);section.append(open);if(row.approved&&!row.timeline_id){const freeze=el('button','冻结已批准时间线');freeze.type='button';freeze.onclick=async()=>{freeze.disabled=true;try{await write('/edit-timeline/freeze',{artifact_id:row.artifact_id});if(alive())report.textContent='已通过原冻结接口，正式剪辑用料已保存。';}catch(e){report.textContent=e.message;freeze.disabled=false;}};section.append(freeze);}form.append(section);}
}
