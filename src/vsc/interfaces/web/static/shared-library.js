/* Global shared library: a fixed library version is used through the original
   target-project transaction. This module never reads a source project's media. */
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
export function createSharedLibrary(ctx){
  let ticket=0,offset=0,query='',category='',dialog=null;
  const button=(text,action)=>{const node=el('button',text);node.type='button';node.addEventListener('click',async()=>{if(node.disabled)return;try{await action();}catch(error){ctx.notice(error.message);}});return node;};
  const headers=()=>({'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf});
  const purposes=[['first_frame','镜头首帧'],['composition','构图参考'],['identity_face','人物正脸'],['location_master','场景母版'],['vfx_overlay','透明特效叠层'],['voice_sample','声音参考'],['ambience','环境声'],['music','配乐'],['sfx','音效']];
  function entryForm(root,{media=null,projectId=null,onDone}={}){
    const formTicket=ticket;
    const form=el('form',null,'library-entry-form');form.append(el('h2',media?'发布当前素材到公共库':'导入共享素材'));
    const field=(text,kind='input')=>{const label=el('label',text),input=el(kind);input.name=text;input.autocomplete='off';input.setAttribute('aria-label',text);label.append(input);form.append(label);return input;};
    const title=field('共享名称');title.required=true;title.value=media?.name||'';
    const description=field('公开说明','textarea');description.required=true;description.rows=3;
    const category=field('类别','select');for(const [value,text]of [['image','图片'],['audio','声音'],['video','视频'],['specification','纯规格']]){const option=el('option',text);option.value=value;category.append(option);}category.value=media?.modality||'image';
    const specification=field('规格或使用说明（纯规格导入必填）','textarea');specification.rows=3;
    let file=null;if(!media){file=field('原文件（纯规格可留空）');file.type='file';}
    const rights=field('来源许可','select');for(const [value,text]of [['owned','本人拥有可共享的权利'],['licensed','已获工作区复用许可']]){const option=el('option',text);option.value=value;rights.append(option);}
    const evidence=field('许可依据（仅公开可分享的说明）','textarea');evidence.required=true;evidence.rows=3;
    const allowed=el('fieldset');allowed.append(el('legend','允许的用途'));const checks=[];for(const [value,text]of purposes){const label=el('label',text),check=el('input');check.type='checkbox';check.value=value;label.prepend(check);allowed.append(label);checks.push(check);}form.append(allowed);
    const consent=el('label','我确认可将以上固定内容在本工作区跨项目复用，不包含私人提示词或未获许可的内容。'),check=el('input');check.type='checkbox';check.required=true;consent.prepend(check);form.append(consent);
    const submit=el('button',media?'确认发布固定素材':'确认导入共享素材');submit.type='submit';const status=el('p');status.setAttribute('role','status');form.append(submit,status);root.append(form);
    let identity=null,staged=null;
    form.addEventListener('input',()=>{identity=null;});file?.addEventListener('change',()=>{staged=null;});
    form.addEventListener('submit',async event=>{event.preventDefault();if(submit.disabled)return;const allowed_purposes=checks.filter(c=>c.checked).map(c=>c.value);if(!allowed_purposes.length){status.textContent='请选择明确的允许用途。';return;}if(!media&&!file.files?.length&&!specification.value.trim()){status.textContent='请选择原文件，或填写独立规格。';return;}
      if(!ctx.session().actor){status.textContent='请先建立操作会话，再导入共享内容。';return;}submit.disabled=true;identity ||= crypto.randomUUID();
      try{if(formTicket!==ticket)throw new Error('所见页面已切换，请回到原处继续。');const payload={library_key:'shared-'+identity,title:title.value,category:category.value,description:description.value,specification:specification.value.trim()?{description:specification.value}:{},allowed_purposes,license:{outcome:rights.value,allow_workspace_reuse:check.checked,evidence:evidence.value},members:[]};
        let url;if(media){url=`/api/v1/projects/${encodeURIComponent(projectId)}/library/publish`;payload.members=[{media_id:media.id,member_key:'reference',role:allowed_purposes[0]}];}
        else{url='/api/v1/library/import';payload.import_key=identity;if(file.files?.length){staged ||= await ctx.api('/api/v1/library/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.files[0].name),'X-CSRF-Token':ctx.session().csrf},body:file.files[0]});payload.members=[{staged_upload:staged.staged_upload,member_key:'reference',role:allowed_purposes[0]}];}}
        if(formTicket!==ticket)return;const result=await ctx.api(url,{method:'POST',headers:headers(),body:JSON.stringify({payload,confirmed:true,expected_revision:ctx.session().revision,idempotency_key:identity})});if(formTicket!==ticket)return;if(result.revision!=null)ctx.setRevision(result.revision);status.textContent='固定共享版本已登记。';onDone?.(result);
      }catch(error){status.textContent=`${error.message}。填写内容保留，可修正后继续。`;}finally{submit.disabled=false;}
    });return form;
  }
  function preview(member){
    if(!member.preview_url)return el('p','此固定版本没有可读取的预览。','hint');
    const media=el(member.modality==='image'?'img':member.modality==='audio'?'audio':member.modality==='video'?'video':'a');
    if(media.tagName==='A'){media.href=member.preview_url;media.textContent='读取固定素材';}
    else{media.src=member.preview_url;if(member.modality==='image'){media.alt='共享素材预览';media.width=320;media.height=240;media.loading='lazy';}else{media.controls=true;media.preload='metadata';}}
    media.addEventListener('error',()=>{const message=el('p','预览读取受阻，请重新读取；原引用仍保留。','hint');media.replaceWith(message);},{once:true});return media;
  }
  async function render(root,target=null){
    const current=++ticket;root.className='shared-library';root.replaceChildren();
    const header=el('header',null,'library-header');header.append(el('h1',target?'为当前对象选择共享素材':'公共素材库'));
    if(target)header.append(el('p',`用于当前对象的 ${target.role}；选取后回到原位置。`,'hint'));
    root.append(header);
    root.append(el('p','旧素材库仍沿原记录读取，不会自动成为共享素材。共享前需固定来源许可和适用用途，再显式迁移。','hint'));
    if(!target&&ctx.session().actor){const add=el('details',null,'library-import');add.append(el('summary','导入共享素材（无需项目）'));const body=el('div');add.append(body);entryForm(body,{onDone:()=>render(root,target)});root.append(add);}
    const form=el('form',null,'library-search'),search=el('input');search.type='search';search.name='library_query';search.value=query;search.placeholder='搜索共享素材…';search.setAttribute('aria-label','搜索共享素材');
    const filter=el('input');filter.name='library_category';filter.value=category;filter.placeholder='类别（可选）…';filter.setAttribute('aria-label','共享素材类别');
    const submit=el('button','查找');submit.type='submit';form.append(search,filter,submit);root.append(form);
    form.addEventListener('submit',event=>{event.preventDefault();query=search.value;category=filter.value;offset=0;render(root,target);});
    const content=el('section',null,'library-results'),status=el('p','正在读取公共素材…','hint');status.setAttribute('role','status');content.append(status);root.append(content);
    try{
      const data=await ctx.api('/api/v1/library?'+new URLSearchParams({query,category,offset:String(offset),limit:'24'}));if(current!==ticket)return;
      content.replaceChildren();
      for(const row of data.items||[]){const card=el('article',null,'library-card');card.append(el('h2',row.title),el('p',row.description||`固定版本 ${row.version||''}`,'hint'));
        const member=row.members?.[0];if(member)card.append(preview(member));
        card.append(button('查看固定版本',()=>detail(root,row.current_version_id||row.version_id,target)));content.append(card);}
      if(!data.items?.length)content.append(el('p','没有符合条件的共享素材。项目素材需经明确发布后才会进入公共库。','empty'));
      const paging=el('nav',null,'library-pagination');for(const [label,next]of [['上一页',offset>0?Math.max(0,offset-24):null],['下一页',offset+(data.items?.length||0)<data.total?offset+24:null]]){const b=button(label,()=>{offset=next;return render(root,target);});b.disabled=next==null;paging.append(b);}root.append(paging);
    }catch(error){if(current===ticket)content.replaceChildren(el('p',`公共库读取受阻：${error.message}`),button('重新读取',()=>render(root,target)));}
  }
  async function detail(root,versionId,target){
    const current=++ticket;root.replaceChildren(el('p','正在读取固定版本…','hint'));
    try{
      const row=await ctx.api(`/api/v1/library/versions/${encodeURIComponent(versionId)}`);if(current!==ticket)return;
      root.replaceChildren(button('返回素材列表',()=>render(root,target)),el('h1',row.title),el('p',row.description||''));
      if(row.specification&&Object.keys(row.specification).length){const section=el('section',null,'library-specification');section.append(el('h2',row.members?.length?'规格与使用说明':'纯规格内容'));
        const {renderArtifactContent}=await import('./artifact-reader.js');if(current!==ticket)return;section.append(renderArtifactContent(row.specification,{mimeType:'application/json'}).body);root.append(section);
      }
      if(!row.members?.length)root.append(el('p','此条目是纯规格，没有图片、视频或声音媒体。可阅读规格；媒体用途需要实际媒体后再检查。','hint'));
      for(const member of row.members||[]){const card=el('article',null,'library-member');card.append(el('h2',member.member_key),preview(member));
        if(target){const use=button('检查并用于此处',async()=>{
          if(!ctx.session().actor||!(ctx.canWrite?.(target.projectId)??ctx.session().writable))throw new Error('请建立当前目标项目的操作会话后再使用。');
          use.disabled=true;const status=el('p','正在检查当前目标与用途…');status.setAttribute('role','status');card.append(status);
          const payload={library_version_id:versionId,member_key:member.member_key,target_object_id:target.target_object_id,role:target.role,select:true};
          try{const base=`/api/v1/projects/${encodeURIComponent(target.projectId)}/library`,headers={'Content-Type':'application/json','X-CSRF-Token':ctx.session().csrf};
            const check=await ctx.api(`${base}/preview-use`,{method:'POST',headers,body:JSON.stringify({payload})});
            if(current!==ticket)return;
            if(!check.available){status.textContent=(check.gaps||[]).map(g=>g.message).join('；')||'当前目标尚不满足使用条件。';return;}
            if(!confirm('确认将此固定共享版本用于当前对象和用途？目标项目将保留独立的来源、权利与采用记录。'))return;
            // Retain this intent across a failed response; clicking again restores
            // the same original receipt rather than creating another candidate.
            const keyName=JSON.stringify([target.projectId,versionId,member.member_key,target.target_object_id,target.role]);
            let key;try{key=sessionStorage.getItem('vsc-library-use:'+keyName);if(!key){key=crypto.randomUUID();sessionStorage.setItem('vsc-library-use:'+keyName,key);}}catch{key=crypto.randomUUID();}
            const result=await ctx.api(`${base}/use`,{method:'POST',headers,body:JSON.stringify({payload,expected_revision:check.revision,idempotency_key:key,confirmed:true})});
            if(current!==ticket)return;ctx.setRevision(result.revision,target.projectId);status.textContent=result.selected?'已用于此处，采用记录已保存。':'已登记候选，尚未采用。';
            if(dialog?.open){dialog.addEventListener('close',()=>target.onUsed?.(result),{once:true});dialog.close('used');}else target.onUsed?.(result);
          }finally{if(current===ticket)use.disabled=false;}
        });card.append(use);}else card.append(button('用于项目中的镜头',()=>targetPicker(root,row,member)));root.append(card);}
      root.append(el('p',`适用用途：${(row.allowed_purposes||[]).join('、')||'以目标项目检查为准'}`,'hint'));
      if(!target&&ctx.session().actor){const lifecycle=el('details',null,'library-lifecycle');lifecycle.append(el('summary','停用推荐或撤回共享权利'));const label=el('label','原因'),reason=el('textarea'),status=el('p');reason.setAttribute('aria-label','停用或撤权原因');status.setAttribute('role','status');label.append(reason);lifecycle.append(label);for(const [outcome,text]of [['retire','停止推荐这个条目'],['revoke_rights','撤回共享权利']])lifecycle.append(button(text,async()=>{if(!reason.value.trim()){status.textContent='请填写具体原因。';return;}if(!confirm(outcome==='retire'?'停止新推荐，合法历史引用仍可保留。确认？':'撤回共享权利会影响后续正式使用，确认？'))return;try{await ctx.api(`/api/v1/library/entries/${encodeURIComponent(row.id)}/retire`,{method:'POST',headers:headers(),body:JSON.stringify({payload:{outcome,reason:reason.value},confirmed:true,idempotency_key:crypto.randomUUID()})});await render(root,target);}catch(error){status.textContent=error.message;}}));lifecycle.append(status);root.append(lifecycle);}
    }catch(error){if(current===ticket)root.replaceChildren(el('p',error.message),button('返回素材列表',()=>render(root,target)));}
  }
  async function targetPicker(root,version,member,resume={}){
    const current=++ticket,section=el('section',null,'library-target-picker');root.replaceChildren(section);
    section.append(button('返回固定素材详情',()=>detail(root,version.library_version_id||version.version_id,null)),el('h2','选择一次目标项目、镜头和用途'));
    const projectLabel=el('label','目标项目'),project=el('select'),roleLabel=el('label','用于'),role=el('select'),results=el('div');project.setAttribute('aria-label','目标项目');role.setAttribute('aria-label','素材用途');projectLabel.append(project);roleLabel.append(role);section.append(projectLabel,roleLabel,results);
    const empty=el('option','请选择项目…');empty.value='';project.append(empty);
    for(const row of ctx.projects?.()||[]){const option=el('option',row.name);option.value=row.id;option.disabled=ctx.canWrite?.(row.id)===false;project.append(option);}
    if(resume.projectId)project.value=resume.projectId;
    const allowed=version.allowed_purposes?.includes('*')?purposes.map(([value])=>value):version.allowed_purposes||[];
    for(const value of allowed){const option=el('option',purposes.find(([key])=>key===value)?.[1]||value);option.value=value;role.append(option);}
    if(resume.role)role.value=resume.role;
    let request=0;
    const read=async(scope=null,offset=0)=>{const projectId=project.value;if(!projectId){results.textContent='选择目标项目后，按已登记目录定位镜头。';return;}const call=++request;results.textContent='正在读取目标目录…';try{const params=new URLSearchParams({section:'children',limit:'24',offset:String(offset)});if(scope)params.set('object_id',scope);const data=await ctx.api(`/api/v1/projects/${encodeURIComponent(projectId)}/workbench?${params}`);if(current!==ticket||call!==request||projectId!==project.value)return;results.replaceChildren();const trail=el('nav');trail.setAttribute('aria-label','目标目录');trail.append(button('项目目录',()=>read()));for(const ancestor of data.ancestors||[])trail.append(button(ancestor.title||ancestor.display_code,()=>read(ancestor.id)));results.append(trail);
        if(data.scope)results.append(el('h3',data.scope.title||data.scope.display_code));
        if(data.scope?.kind==='shot')results.append(button('确定用于此镜头',()=>choose({projectId,target_object_id:data.scope.id,role:role.value,
          onCancel:()=>targetPicker(root,version,member,{projectId,objectId:data.scope.id,role:role.value}),
          onUsed:()=>{ctx.notice('固定共享素材已用于所选项目和镜头，目标的来源与采用记录已保留。');return detail(root,version.library_version_id||version.version_id,null);}},version.library_version_id||version.version_id)));
        for(const row of data.sections?.children?.items||[])if(['work','episode','scene','sequence','shot'].includes(row.kind))results.append(button(row.title||row.display_code,()=>read(row.id)));
        const next=data.sections?.children?.next_offset;if(offset)results.append(button('上一页',()=>read(scope,Math.max(0,offset-24))));if(next!=null)results.append(button('下一页',()=>read(scope,next)));
        if(!data.sections?.children?.items?.length&&data.scope?.kind!=='shot')results.append(el('p','此目录还没有镜头，请从目标项目的来源与场镜继续建立内容。','hint'));
      }catch(error){if(current===ticket&&call===request)results.textContent=error.message;}};
    project.addEventListener('change',()=>read());await read(resume.objectId||null);
  }
  async function choose(target,versionId=null){
    if(!target.projectId||!target.target_object_id||!target.role)throw new Error('请先定位具体对象和用途，再从此处选择共享素材。');
    if(!dialog){dialog=el('dialog',null,'library-dialog');dialog.setAttribute('aria-label','为当前对象选择共享素材');document.body.append(dialog);dialog.addEventListener('close',()=>{ticket++;dialog.querySelectorAll('audio,video').forEach(node=>node.pause());});}
    const prior=document.activeElement;dialog.replaceChildren();dialog.returnValue='';const close=button('取消并返回原处',()=>dialog.close('cancel')),body=el('div');dialog.append(close,body);dialog.addEventListener('close',()=>{prior?.focus?.();if(dialog.returnValue!=='used')target.onCancel?.();},{once:true});dialog.showModal();if(versionId)await detail(body,versionId,target);else await render(body,target);
  }
  return {load:root=>render(root),choose,suspend:()=>{ticket++;},publish:(root,media,projectId)=>entryForm(root,{media,projectId,onDone:()=>ctx.notice('当前固定素材已发布到公共库，可从公共素材库查看。')})};
}
