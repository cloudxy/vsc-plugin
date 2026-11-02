import {msg,setText,bindAttribute,isMessage,option as localizedOption} from './i18n.js';
/* Shared explicit authorization/account choices for production drafts. */
export function createRunScopeControls(parent,{api,session,projectId,onChange=()=>{}}){
 const field=(name,input)=>{const label=document.createElement('label');setText(label,name);bindAttribute(input,'aria-label',name);label.append(input);parent.append(label);return input;};
 const account=field(msg("ui.production_credit_account"),document.createElement('select'));
 if(session().actor)account.append(localizedOption(session().actor,msg("ui.my_allowance_value0",{value0:session().actor})));account.append(localizedOption('',msg("ui.shared_project_budget")));
 const scope=field(msg("ui.production_authorization_scope"),document.createElement('select'));scope.append(localizedOption('',msg("ui.retain_existing_production_limits")),localizedOption('new_batch',msg("ui.new_batch_approve_new_deadlines_and_attempt_limits")));
 const reason=field(msg("ui.reason_for_the_new_batch"),document.createElement('input'));reason.maxLength=2000;reason.disabled=true;
 const note=document.createElement('p');setText(note,msg("ui.recovery_and_continuation_retain_the_original_limits_a_new"));parent.append(note);
 let originals=[],active=true;
 for(const input of [account,scope,reason])input.addEventListener('input',()=>{reason.disabled=scope.value!=='new_batch';onChange();});
 api(`/api/v1/projects/${encodeURIComponent(projectId)}/execution-authorizations`).then(value=>{if(!active)return;originals=value.items;for(const row of originals)scope.append(localizedOption(row.id,msg("ui.continue_batch_value0",{value0:row.reason})));}).catch(error=>{if(active)setText(note,msg("ui.previous_batch_could_not_be_loaded_value0_reopen_this",{value0:error.message}));});
 return {apply(request){request.commerce_account_actor=account.value||null;if(scope.value==='new_batch'){if(!reason.value.trim())throw new Error('请说明新制作批次的原因');request.execution_policy.authorization={mode:'new_batch',reason:reason.value.trim()};}else if(scope.value){const row=originals.find(r=>r.id===scope.value);if(!row)throw new Error('原批次已改变，请重新读取');request.execution_policy.authorization={mode:'continue',run_version_id:row.id,sha256:row.sha256};}return request;},dispose(){active=false;}};
}
