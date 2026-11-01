const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const names={work:'部',episode:'集',scene:'场',sequence:'镜组',shot:'镜头',asset:'资产',image:'图片',video:'视频',audio:'音频',active:'可用',trashed:'已回收',parent_trashed:'父级已回收'};
export function createProjectManagement(root,ctx){
  let ticket=0,project=null,data=null,busy=false,identity=null,filters={folder:'',kind:'',q:'',offset:0};
  const drafts=new Map(),pending=new Map();
  const endpoint=p=>`/api/v1/projects/${encodeURIComponent(p)}/management`;
  const session=()=>ctx.session();
  const actorKey=()=>session().identityId||session().actor||'reader';
  const scopeKey=()=>actorKey()+'|'+project;
  const same=(t,p)=>ticket===t&&project===p&&identity===actorKey();
  function button(label,fn,disabled=false){const b=el('button',label);b.type='button';b.disabled=disabled;b.onclick=async()=>{try{await fn();}catch(e){ctx.notice(e.message);}};return b;}
  function field(parent,title,input,key,initial=''){const label=el('label',title,'field');input.setAttribute('aria-label',title);if(key){input.value=drafts.get(scopeKey()+':'+key)??initial;input.addEventListener('input',()=>drafts.set(scopeKey()+':'+key,input.value));}label.append(input);parent.append(label);return input;}
  function form(title){const n=el('form',null,'management-form');n.append(el('h3',title));return n;}
  function selector(withRoot=true){const s=el('select');if(withRoot)s.append(new Option('未归类 / 根目录',''));for(const f of data.folders)s.append(new Option(folderLabel(f.id),f.id));return s;}
  function folderLabel(id){const seen=new Set(),parts=[];while(id&&!seen.has(id)){seen.add(id);const f=data.folders.find(x=>x.id===id);if(!f)break;parts.unshift(f.title);id=f.parent_id;}return parts.join(' / ');}
  function submit(form,label,build){const b=el('button',label);b.type='submit';b.disabled=!session().actor||busy;form.append(b);form.onsubmit=async e=>{e.preventDefault();try{await write(build());}catch(error){ctx.notice(error.message);}};}
  async function write(payload,resume=false){
    if(!session().actor)throw new Error('请先建立操作会话');
    if(busy)throw new Error('当前操作尚未完成');
    const p=project,t=ticket,key=scopeKey();
    if(pending.has(key)&&!resume)throw new Error('上次操作回执未知，请先恢复原请求');
    let request=pending.get(key);if(!request){request={payload,expected_revision:data.revision,idempotency_key:crypto.randomUUID()};pending.set(key,request);}
    busy=true;render();
    try{const result=await ctx.api(endpoint(p),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request)});pending.delete(key);
      if(!same(t,p))return;ctx.setRevision?.(result.revision,p);
      if(result.status==='protected')ctx.notice('操作未执行：'+result.reasons.map(r=>r.message+'（'+r.table+'）').join('；'));
      else ctx.notice(result.unchanged?'状态已一致。':'已保存；原身份与固定审计保留。');
      await ctx.onProjectsChanged?.();if(same(t,p))await load({project:p,keepFilters:true});
    }catch(error){if(error.status>=400&&error.status<500)pending.delete(key);if(same(t,p)){busy=false;render();}throw error;}
    finally{if(same(t,p)){busy=false;render();}}
  }
  function lifecycle(target,operation){
    const dialog=el('dialog'),f=form(operation==='purge'?'永久停用（保留审计）':operation==='trash'?'移入回收':'恢复原关系');
    f.append(el('p',target.title));if(operation==='purge')f.append(el('p','此操作不可恢复；固定身份、证据与审计仍保留，不释放存储字节。'));
    const reason=field(f,'操作原因',el('input'),'reason:'+target.id+operation);reason.required=true;reason.maxLength=2000;
    const confirm=operation==='purge'?field(f,'完整输入目标名称',el('input'),null):null;if(confirm)confirm.required=true;
    const save=el('button',operation==='purge'?'确认永久停用':operation==='trash'?'确认移入回收':'确认恢复');save.type='submit';f.append(save,button('取消',()=>dialog.close()));
    const p=project,t=ticket;f.onsubmit=async e=>{e.preventDefault();if(!same(t,p)){dialog.close();return;}save.disabled=true;try{await write({operation,target_type:target.type,target_id:target.id,reason:reason.value,...(confirm?{confirm_name:confirm.value}:{})});dialog.close();}catch(error){ctx.notice(error.message);save.disabled=false;}};
    dialog.append(f);root.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();
  }
  function render(){
    if(!data)return;root.replaceChildren();const head=el('header');head.append(el('h1',project?'项目管理':'回收站'),el('p',project?'管理项目名称、文件夹与留存设置':'查看已回收的项目，恢复后可继续创作','hint'));root.append(head);
    const choices=el('select');choices.setAttribute('aria-label','管理项目');choices.append(new Option('请选择项目',''));for(const r of data.projects)choices.append(new Option(r.name+(r.state==='trashed'?' · 已回收':''),r.id));choices.value=project||'';choices.onchange=()=>{const next=choices.value||null;ctx.onScope?.(next,data.projects.find(r=>r.id===next));filters={folder:'',kind:'',q:'',offset:0};load({project:next});};root.append(choices,button('刷新管理状态',()=>load({project,keepFilters:true})));
    if(!project||!data.project){const grid=el('div',null,'management-recycled');for(const row of data.projects.filter(r=>r.state==='trashed')){const card=el('article',null,'management-recycled-card'),cover=el('div','▤','management-cover');card.append(cover,el('h3',row.name),button('查看与恢复',async()=>{ctx.onScope?.(row.id,row);await load({project:row.id});}));grid.append(card);}if(!grid.children.length)grid.append(el('div','回收站为空','management-empty'));root.append(grid);return;}
    const pendingRequest=pending.get(scopeKey());if(pendingRequest){const recovery=el('aside',null,'management-recovery');recovery.append(el('p',busy?'正在提交固定操作…':'上次操作回执未知，保留原输入与请求标识。'),button('恢复原操作回执',()=>write(null,true),busy));root.append(recovery);}
    const summary=el('section',null,'management-card');summary.append(el('h2',data.project.name),el('p',data.state==='active'?'项目可用':data.state==='trashed'?'项目已回收；固定历史仍可读，恢复后继续工作。':'项目永久停用，保留审计。'));
    const target={type:'project',id:project,title:data.project.name};if(data.state==='active')summary.append(button('回收此项目',()=>lifecycle(target,'trash'),busy));else if(data.state==='trashed')summary.append(button('恢复此项目',()=>lifecycle(target,'restore'),busy),button('永久停用此项目',()=>lifecycle(target,'purge'),busy));root.append(summary);
    const layout=el('div',null,'management-grid'),settings=el('details',null,'management-settings');settings.append(el('summary','项目名称、文件夹与留存设置'),layout);root.append(settings);
    if(data.state==='active'){
      const rename=form('项目名称'),title=field(rename,'项目名称',el('input'),'project-name',data.project.name);title.required=true;title.maxLength=200;if(title.value!==data.project.name)rename.append(el('p','名称有未保存修改。','hint'));submit(rename,'保存项目名称',()=>({operation:'rename',title:title.value}));layout.append(rename);
      const create=form('新建文件夹'),folderTitle=field(create,'文件夹名称',el('input'),'new-folder');folderTitle.required=true;folderTitle.maxLength=200;const parent=field(create,'上级文件夹',selector(),'new-parent');submit(create,'创建文件夹',()=>({operation:'folder_create',title:folderTitle.value,parent_id:parent.value||null}));layout.append(create);
    }
    const retention=form('显式留存'),days=field(retention,'留存天数（留空不设期限）',el('input'),'retention',data.retention_days??'');days.type='number';days.min='1';days.max='36500';retention.append(el('p','仅显示到期日期；不会自动删除。永久停用始终需要明确操作且检查在途和引用。','hint'));submit(retention,'保存留存设置',()=>({operation:'retention',days:days.value===''?null:Number(days.value)}));layout.append(retention);
    if(data.state==='active'){
      const folders=el('section',null,'management-card');folders.append(el('h2','项目内文件夹'));
      for(const f of data.folders){const row=el('div',null,'management-folder');row.append(el('strong',folderLabel(f.id)));const title=el('input');title.setAttribute('aria-label','目录名称 '+f.title);title.value=drafts.get(scopeKey()+':folder-title:'+f.id)??f.title;title.oninput=()=>drafts.set(scopeKey()+':folder-title:'+f.id,title.value);const parent=selector();parent.setAttribute('aria-label','目录父级 '+f.title);parent.value=f.parent_id||'';const siblings=data.folders.filter(x=>x.parent_id===f.parent_id).sort((a,b)=>a.ordinal-b.ordinal),at=siblings.findIndex(x=>x.id===f.id);
        row.append(title,button('改名',()=>write({operation:'folder_update',folder_id:f.id,title:title.value}),busy),parent,button('移动目录',()=>write({operation:'folder_move',folder_id:f.id,parent_id:parent.value||null}),busy),button('上移',()=>{const ids=siblings.map(x=>x.id);[ids[at-1],ids[at]]=[ids[at],ids[at-1]];return write({operation:'folder_order',parent_id:f.parent_id,folder_ids:ids});},busy||at===0),button('删除空目录',()=>write({operation:'folder_remove',folder_id:f.id}),busy));folders.append(row);}
      root.append(folders);
    }
    const query=form('内容筛选'),folder=field(query,'所在文件夹',selector());folder.options[0].textContent='全部文件夹';folder.append(new Option('仅未归类','unfiled'));folder.value=filters.folder;const kind=field(query,'内容类型',el('select'));for(const [v,l]of [['','可用对象与媒资'],['object','可用对象'],['media','可用媒资'],['trashed','回收对象']])kind.append(new Option(l,v));kind.value=filters.kind;const search=field(query,'名称或标识',el('input'));search.value=filters.q;const filter=el('button','筛选');filter.type='submit';query.append(filter);query.onsubmit=e=>{e.preventDefault();filters={folder:folder.value,kind:kind.value,q:search.value,offset:0};load({project,keepFilters:true});};root.append(query);
    const list=el('div',null,'management-items');for(const row of data.items){const card=el('article',null,'management-card');card.append(el('h3',row.title||row.id),el('p',(names[row.kind]||row.kind)+' · '+(names[row.state]||row.state)+' · '+(row.folder_id?folderLabel(row.folder_id):'未归类'),'hint'));
      if(row.changed_at)card.append(el('p','回收于 '+row.changed_at+(row.due_at?' · 到期 '+row.due_at+(row.expired?'（等待明确操作）':''):''),'hint'));
      if(row.state==='active'&&data.state==='active'){const dest=selector();dest.value=row.folder_id||'';dest.setAttribute('aria-label','移动 '+row.title);card.append(dest,button('移动归类',()=>write({operation:'move',target_type:row.type,target_id:row.id,folder_id:dest.value||null}),busy));
        if(row.type==='object')card.append(button('回收对象',()=>lifecycle(row,'trash'),busy),button('打开对象',()=>ctx.navigate('project',row.id,project)));
        else card.append(button('打开素材',()=>ctx.media?.(row.id)),button('素材回收入口',()=>ctx.navigate('trash',null,project)));
      }else if(row.state==='trashed')card.append(button('恢复对象',()=>lifecycle(row,'restore'),busy),button('永久停用对象',()=>lifecycle(row,'purge'),busy));else if(row.state==='parent_trashed')card.append(el('p','请先恢复父级；原归类关系仍保留。'));
      list.append(card);}
    if(!data.items.length)list.append(el('p','此筛选下没有内容。'));root.append(list);
    const pager=el('nav');pager.append(button('上一页',()=>{filters.offset=Math.max(0,filters.offset-100);return load({project,keepFilters:true});},!filters.offset),el('span',`共 ${data.total} 项`),button('下一页',()=>{filters.offset=data.next_offset;return load({project,keepFilters:true});},data.next_offset==null));root.append(pager);
  }
  async function load(options={}){
    const p=options.project||null,t=++ticket;project=p;identity=actorKey();busy=false;if(!options.keepFilters)filters={folder:'',kind:'',q:'',offset:0};root.replaceChildren(el('p','正在读取目录与回收状态…'));
    try{const headers={'X-CSRF-Token':session().csrf||''};const [active,recycled]=await Promise.all([ctx.api('/api/v1/projects'),session().actor?ctx.api('/api/v1/project-management/recycled',{headers}):Promise.resolve({items:[]})]);if(!same(t,p))return;const projects=[...active.items,...recycled.items];
      const query=new URLSearchParams({offset:String(filters.offset),limit:'100'});if(filters.folder)query.set('folder_id',filters.folder);if(filters.kind)query.set('kind',filters.kind);if(filters.q)query.set('q',filters.q);
      const value=p?await ctx.api(endpoint(p)+'?'+query):{};if(!same(t,p))return;data={...value,projects};if(value.revision!=null)ctx.setRevision?.(value.revision,p);render();
    }catch(error){if(same(t,p)){root.replaceChildren(el('p',error.message),button('重新读取',()=>load({project:p,keepFilters:true})));}}
  }
  return {load,suspend(){ticket++;busy=false;}};
}
