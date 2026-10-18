// Human review operates on the exact version/hash displayed in this dialog.
const labels={draft:'待审提案',approved:'已批准',rejected:'已拒绝',retired:'已退役',fact:'事实',lesson:'经验',check_method:'检查方法',judgment:'判断',recommendation:'建议',preference:'偏好',decision:'决定',role:'角色私有',project:'项目共享',agent_proposed:'角色提案',unverified_proposal:'待核实提案',human_curated:'历史记忆'};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}

export function createRoleMemory(dialog,{api,session,project,onRevision,onOpenArtifact}){
  let current=null,sequence=0,busy=false,revision=0,rows=[];
  const decisions=new Map();
  const header=el('div','dialog-header'),close=el('button','','关闭');close.type='button';close.addEventListener('click',()=>dialog.close());
  header.append(el('h2','','角色记忆'),close);
  const content=el('div'),message=el('p','hint');message.setAttribute('role','status');
  const refresh=el('button','','刷新记忆');refresh.type='button';refresh.addEventListener('click',()=>load().catch(report));
  dialog.replaceChildren(header,el('p','hint','角色返回先形成待审提案。批准只对下方所见版本生效；来源失效或退役后停止下发，历史记录保留。'),refresh,message,content);
  function report(error){message.textContent=error?.message||String(error);}
  function validSession(){return Boolean(session().actor&&session().csrf);}
  async function load(){
    const request=++sequence,target=current;
    if(!target||project()!==target)throw new Error('当前项目已切换，请重新打开角色记忆。');
    const value=await api(`/api/v1/projects/${encodeURIComponent(target)}/role-memories`);
    if(request!==sequence||project()!==target)return;
    rows=value.items||[];revision=value.revision;render();
  }
  function render(){
    content.replaceChildren();message.textContent='';
    if(!validSession())content.append(el('p','hint','建立顶栏“操作会话”后可审阅并作出决定。'));
    if(!rows.length){content.append(el('p','empty','当前项目没有角色记忆提案。'));return;}
    for(const item of rows){
      const card=el('section','detail-panel');card.append(el('h3','',`${item.role||item.owner_role||'项目'} · ${labels[item.kind]||item.kind} · ${labels[item.status]||item.status}`));
      card.append(el('p','hint',`${labels[item.scope]||item.scope} · ${labels[item.origin]||item.origin||'历史记忆'} · ${item.sensitivity||'project'}`));
      card.append(el('p','readable',item.content));
      const fixed=el('details');fixed.append(el('summary','','固定版本与来源'));
      fixed.append(el('p','hint',`记忆 ${item.id} · 版本 ${item.version||1} · SHA ${item.content_sha256}`));
      const refs=item.source_refs||[{kind:item.source?.startsWith('A-')?'artifact':'source',id:item.source,sha256:item.source_version?.sha256||item.source_sha256}];
      for(const ref of refs.filter(r=>r.id)){
        const row=el('p','hint',`${ref.kind==='artifact'?'产物':'来源'} ${ref.id} · SHA ${ref.sha256||'历史短摘要'}`);
        if(ref.kind==='artifact'&&onOpenArtifact){const open=el('button','','查看依据');open.type='button';open.addEventListener('click',()=>{dialog.close();onOpenArtifact(ref.id);});row.append(open);}
        fixed.append(row);
      }
      card.append(fixed);
      if(item.invalid_reasons?.length)card.append(el('p','hint','来源或批准依据已失效。请回到来源责任环节核对；该条不会下发给新任务。'));
      if(validSession()&&['draft','approved'].includes(item.status)){
        const form=el('form','review-form'),reason=el('textarea'),label=el('label','');
        reason.required=true;reason.placeholder='说明本次决定及适用范围';reason.setAttribute('aria-label','记忆决定说明');
        const confirm=el('input');confirm.type='checkbox';confirm.required=true;label.append(confirm,document.createTextNode('已阅读此固定版本与来源，确认作出下方决定'));
        const action=el('select');action.setAttribute('aria-label','记忆决定');
        for(const [value,text]of item.status==='draft'?[['approved','批准供后续任务使用'],['rejected','拒绝此提案']]:[['retired','退役，停止后续使用']]){
          if(value==='approved'&&item.invalid_reasons?.length)continue;
          const option=el('option','',text);option.value=value;action.append(option);
        }
        const submit=el('button','','记录决定');submit.type='submit';submit.disabled=busy;form.append(reason,label,action,submit);
        const seenActor=session().actor,seenRevision=revision;
        form.addEventListener('submit',async event=>{
          event.preventDefault();if(busy)return;
          if(project()!==current||session().actor!==seenActor){report('项目或操作会话已改变，请重新打开后核对。');return;}
          if(!confirm.checked||!reason.value.trim()){report('请阅读来源，填写说明并确认。');return;}
          busy=true;submit.disabled=true;refresh.disabled=true;
          const target=current,payload={version_id:item.version_id||item.id,content_sha256:item.content_sha256,outcome:action.value,reason:reason.value.trim()};
          const signature=JSON.stringify([target,payload,seenRevision]);
          if(!decisions.has(signature))decisions.set(signature,crypto.randomUUID());
          try{
            const value=await api(`/api/v1/projects/${encodeURIComponent(target)}/role-memory-decisions`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload,confirmed:true,expected_revision:seenRevision,idempotency_key:decisions.get(signature)})});
            if(project()!==target)return;
            onRevision?.(value.revision);busy=false;await load();message.textContent='已记录本次人工决定。';
          }catch(error){report(error);}finally{busy=false;submit.disabled=false;refresh.disabled=false;}
        });card.append(form);
      }
      content.append(card);
    }
  }
  return {async open(){current=project();if(!current)throw new Error('请先选择项目。');await load();dialog.showModal();}};
}
