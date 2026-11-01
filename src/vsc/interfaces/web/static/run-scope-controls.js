/* Shared explicit authorization/account choices for production drafts. */
export function createRunScopeControls(parent,{api,session,projectId,onChange=()=>{}}){
 const field=(name,input)=>{const label=document.createElement('label');label.textContent=name;input.setAttribute('aria-label',name);label.append(input);parent.append(label);return input;};
 const account=field('制作额度账户',document.createElement('select'));
 if(session().actor)account.append(new Option('我的额度（'+session().actor+'）',session().actor));account.append(new Option('项目共享额度',''));
 const scope=field('制作授权范围',document.createElement('select'));scope.append(new Option('沿用既有制作限制',''),new Option('新批次：重新批准本次时限和次数','new_batch'));
 const reason=field('新批次原因',document.createElement('input'));reason.maxLength=2000;reason.disabled=true;
 const note=document.createElement('p');note.textContent='恢复和续批保留原限制；新批次随制作方案明确批准，项目总额度仍生效。';parent.append(note);
 let originals=[],active=true;
 for(const input of [account,scope,reason])input.addEventListener('input',()=>{reason.disabled=scope.value!=='new_batch';onChange();});
 api(`/api/v1/projects/${encodeURIComponent(projectId)}/execution-authorizations`).then(value=>{if(!active)return;originals=value.items;for(const row of originals)scope.append(new Option('继续批次：'+row.reason,row.id));}).catch(error=>{if(active)note.textContent='旧批次读取失败：'+error.message+'；可重新打开此工具读取。';});
 return {apply(request){request.commerce_account_actor=account.value||null;if(scope.value==='new_batch'){if(!reason.value.trim())throw new Error('请说明新制作批次的原因');request.execution_policy.authorization={mode:'new_batch',reason:reason.value.trim()};}else if(scope.value){const row=originals.find(r=>r.id===scope.value);if(!row)throw new Error('原批次已改变，请重新读取');request.execution_policy.authorization={mode:'continue',run_version_id:row.id,sha256:row.sha256};}return request;},dispose(){active=false;}};
}
