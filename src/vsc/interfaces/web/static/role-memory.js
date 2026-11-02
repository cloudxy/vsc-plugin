import {msg,joinMessages,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
// Human review operates on the exact version/hash displayed in this dialog.
const labels={draft:msg("ui.proposal_awaiting_review"),approved:msg("ui.approved"),rejected:msg("ui.rejected"),retired:msg("ui.retired"),fact:msg("ui.fact"),lesson:msg("ui.lesson"),check_method:msg("ui.check_method"),judgment:msg("ui.judgment"),recommendation:msg("ui.suggestion"),preference:msg("ui.preference"),decision:msg("ui.decision"),role:msg("ui.private_to_role"),project:msg("ui.shared_in_project"),agent_proposed:msg("ui.role_proposal"),unverified_proposal:msg("ui.unverified_proposal"),human_curated:msg("ui.historical_memory")};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)setText(n,text);return n;}

export function createRoleMemory(dialog,{api,session,project,onRevision,onOpenArtifact}){
  let current=null,sequence=0,busy=false,revision=0,rows=[];
  const decisions=new Map();
  const header=el('div','dialog-header'),close=el('button','',msg("common.close"));close.type='button';close.addEventListener('click',()=>dialog.close());
  header.append(el('h2','',msg("ui.role_memory")),close);
  const content=el('div'),message=el('p','hint');message.setAttribute('role','status');
  const refresh=el('button','',msg("ui.refresh_memories"));refresh.type='button';refresh.addEventListener('click',()=>load().catch(report));
  dialog.replaceChildren(header,el('p','hint',msg("ui.role_returns_create_proposals_awaiting_review_approval_applies_only")),refresh,message,content);
  function report(error){setText(message,error?.message||String(error));}
  function validSession(){return Boolean(session().actor&&session().csrf);}
  async function load(){
    const request=++sequence,target=current;
    if(!target||project()!==target)throw new Error('当前项目已切换，请重新打开角色记忆。');
    const value=await api(`/api/v1/projects/${encodeURIComponent(target)}/role-memories`);
    if(request!==sequence||project()!==target)return;
    rows=value.items||[];revision=value.revision;render();
  }
  function render(){
    content.replaceChildren();setText(message,'');
    if(!validSession())content.append(el('p','hint',msg("ui.establish_an_action_session_in_the_top_bar_to")));
    if(!rows.length){content.append(el('p','empty',msg("ui.no_role_memory_proposals_in_this_project")));return;}
    for(const item of rows){
      const card=el('section','detail-panel');card.append(el('h3','',joinMessages(["",item.role||item.owner_role||msg("common.project")," · ",labels[item.kind]||item.kind," · ",labels[item.status]||item.status,""])));
      card.append(el('p','hint',joinMessages(["",labels[item.scope]||item.scope," · ",labels[item.origin]||item.origin||msg("ui.historical_memory")," · ",item.sensitivity||'project',""])));
      card.append(el('p','readable',item.content));
      const fixed=el('details');fixed.append(el('summary','',msg("ui.fixed_version_and_source")));
      fixed.append(el('p','hint',msg("ui.memory_value0_version_value1_sha_value2",{value0:item.id,value1:item.version||1,value2:item.content_sha256})));
      const refs=item.source_refs||[{kind:item.source?.startsWith('A-')?'artifact':'source',id:item.source,sha256:item.source_version?.sha256||item.source_sha256}];
      for(const ref of refs.filter(r=>r.id)){
        const row=el('p','hint',joinMessages(["",ref.kind==='artifact'?msg("ui.artifact"):msg("ui.source")," ",ref.id," · SHA ",ref.sha256||msg("ui.historical_short_summary"),""]));
        if(ref.kind==='artifact'&&onOpenArtifact){const open=el('button','',msg("ui.view_evidence"));open.type='button';open.addEventListener('click',()=>{dialog.close();onOpenArtifact(ref.id);});row.append(open);}
        fixed.append(row);
      }
      card.append(fixed);
      if(item.invalid_reasons?.length)card.append(el('p','hint',msg("ui.source_or_approval_evidence_is_invalid_return_to_the")));
      if(validSession()&&['draft','approved'].includes(item.status)){
        const form=el('form','review-form'),reason=el('textarea'),label=el('label','');
        reason.required=true;bindAttribute(reason,"placeholder",msg("ui.explain_this_decision_and_its_applicable_scope"));bindAttribute(reason,'aria-label',msg("ui.memory_decision_explanation"));
        const confirm=el('input');confirm.type='checkbox';confirm.required=true;label.append(confirm,document.createTextNode('已阅读此固定版本与来源，确认作出下方决定'));
        const action=el('select');bindAttribute(action,'aria-label',msg("ui.memory_decision"));
        for(const [value,text]of item.status==='draft'?[['approved','批准供后续任务使用'],['rejected','拒绝此提案']]:[['retired','退役，停止后续使用']]){
          if(value==='approved'&&item.invalid_reasons?.length)continue;
          const option=el('option','',text);option.value=value;action.append(option);
        }
        const submit=el('button','',msg("ui.record_decision"));submit.type='submit';submit.disabled=busy;form.append(reason,label,action,submit);
        const seenActor=session().actor,seenRevision=revision;
        form.addEventListener('submit',async event=>{
          event.preventDefault();if(busy)return;
          if(project()!==current||session().actor!==seenActor){report(msg("ui.project_or_action_session_changed_reopen_and_verify"));return;}
          if(!confirm.checked||!reason.value.trim()){report(msg("ui.read_the_source_enter_an_explanation_and_confirm"));return;}
          busy=true;submit.disabled=true;refresh.disabled=true;
          const target=current,payload={version_id:item.version_id||item.id,content_sha256:item.content_sha256,outcome:action.value,reason:reason.value.trim()};
          const signature=JSON.stringify([target,payload,seenRevision]);
          if(!decisions.has(signature))decisions.set(signature,crypto.randomUUID());
          try{
            const value=await api(`/api/v1/projects/${encodeURIComponent(target)}/role-memory-decisions`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload,confirmed:true,expected_revision:seenRevision,idempotency_key:decisions.get(signature)})});
            if(project()!==target)return;
            onRevision?.(value.revision);busy=false;await load();setText(message,msg("ui.human_decision_recorded"));
          }catch(error){report(error);}finally{busy=false;submit.disabled=false;refresh.disabled=false;}
        });card.append(form);
      }
      content.append(card);
    }
  }
  return {async open(){current=project();if(!current)throw new Error('请先选择项目。');await load();dialog.showModal();}};
}
