import {msg,joinMessages,setText,bindAttribute,isMessage,translate,getLocale,option as localizedOption} from './i18n.js';
import {mountDiscovery} from './discovery.js';
import {mountAssetCards} from './asset-cards.js';
import {scopedProjects,directoryScope,scopedDirectoryPath} from './project-scope.js';
import {createCanvasLibrary} from './canvas-library.js';
// Independent management views over the original project, object, task and media authorities.
const label = {created:msg("ui.waiting_for_worker"),queued:msg("ui.waiting_for_worker"),submitted:msg("ui.remote_task_in_transit"),running:msg("ui.processing_remotely"),polling:msg("ui.remote_task_in_transit"),succeeded:msg("ui.result_available"),failed:msg("ui.execution_failed"),submission_unknown:msg("ui.submission_needs_reconciliation"),cancelled:msg("script-studio.text_057"),ready:msg("ui.inputs_ready"),blocked:msg("ui.missing_items"),waiting:msg("ui.waiting_for_predecessor"),existing:msg("ui.task_exists"),video_clip:msg("ui.shot_video"),image:msg("ui.image"),dialogue_dry:msg("agent.overseas_remake_dialogue"),images:msg("ui.image_count"),video_seconds:msg("ui.video_seconds"),remote_jobs:msg("ui.remote_tasks"),speech_chars:msg("ui.speech_characters"),audio_jobs:msg("ui.audio_tasks")};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)setText(n,text);if(cls)n.className=cls;return n;};
const gapNames={shot_spec_missing:msg("ui.confirmed_shot_plan_missing"),state_missing:msg("ui.scene_state_evidence_missing"),first_frame_missing:msg("ui.no_usable_first_frame_selected"),binding_missing:msg("ui.no_media_selected_for_this_role"),media_unavailable:msg("ui.fixed_media_is_unreadable"),task_dependency_waiting:msg("ui.waiting_for_predecessor_result"),task_dependency_failed:msg("ui.predecessor_task_failed"),production_deadline_reached:msg("ui.deadline_for_new_tasks_reached"),identity_unresolved:msg("ui.asset_identity_unresolved"),fixed_spec_missing_or_unapproved:msg("ui.fixed_specification_missing_or_unapproved"),instance_spec_conflict:msg("ui.instance_conflicts_with_fixed_specification"),identity_or_binding_conflict:msg("ui.identity_or_role_binding_conflict"),reference_missing:msg("ui.usable_reference_missing"),requirement_binding_missing:msg("ui.requirement_has_no_role_media_binding"),requirement_binding_unusable:msg("ui.requirement_s_bound_media_is_unavailable"),asset_context_spec_mismatch:msg("ui.asset_inputs_do_not_match_the_required_specification"),asset_generation_unsupported:msg("ui.no_executable_generation_route_for_this_asset_type")};
const gapText=g=>g.message||gapNames[g.code]||g.code||String(g);
const text=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
const uid=()=>crypto.randomUUID();
export const quickViews=[['script','制作方案'],['assets','资产准备'],['production','镜头制作'],['editing','成片修补'],['delivery','交付']];
export function createProductionPlatform(root,ctx){
  let ticket=0,scope=null,data=null,offset=0,busy=false,poll=null,assetCards=null,canvasLibrary=null,mediaLibrary=null;
  const drafts=new Map(),pending=new Map(),creationFiles=new Map();let closeCreation=null,homeOpening=null,episodeOpening=null;
  const remember=(key,value)=>{try{if(value==null)sessionStorage.removeItem(key);else sessionStorage.setItem(key,JSON.stringify(value));}catch{}},recall=key=>{try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}},episodeDraft=p=>'vsc-platform-episode:'+session().actor+':'+p;
  const endpoint=(p,suffix)=>`/api/v1/projects/${encodeURIComponent(p)}/${suffix}`;
  const same=(t,s=scope)=>t===ticket&&s===scope;
  const session=()=>ctx.session();
  const writable=()=>Boolean(session().actor&&session().writable);
  function button(title,fn,disabled=false){const n=el('button',title);n.type='button';n.disabled=disabled;n.addEventListener('click',async()=>{try{await fn();}catch(e){ctx.notice(e.message);}});return n;}
  function link(title,page,object=scope?.object,project=scope?.project,options={}){const a=el('a',title);a.href='?'+new URLSearchParams({page,...(project?{project}:{}),...(object?{scope:object}:{}),...options});a.addEventListener('click',e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();ctx.navigate(page,object,project,options);});return a;}
  function field(form,title,input){const f=el('label',title,'field');bindAttribute(input,'aria-label',title);f.append(input);form.append(f);return input;}
  function card(title){const n=el('article',null,'platform-card');n.append(el('h3',title));return n;}
  function header(title,description){const h=el('header',null,'platform-heading');h.append(el('p',msg("ui.vsc_creative_workbench"),'platform-kicker'),el('h1',title));if(description)h.append(el('p',description,'hint'));root.append(h);return h;}
  function actions(...children){const n=el('div',null,'platform-actions');n.append(...children);return n;}
  function empty(title,detail){const n=card(title);n.append(el('p',detail,'hint'));return n;}
  function pagination(total,next,read){const nav=el('nav',null,'pagination');bindAttribute(nav,'aria-label',msg("ui.page_navigation"));nav.append(button(msg("common.previous_page"),()=>read(Math.max(0,offset-24)),offset===0),el('span',joinMessages(["",total?offset+1:0,"–",Math.min(total,offset+24)," / ",total,""])),button(msg("common.next_page"),()=>read(next),next==null));return nav;}
  async function read(path,t){const value=await ctx.api(path);return same(t)?value:null;}
  async function write(path,payload){
    if(!writable())throw new Error('当前项目只读，或尚未建立操作会话');
    const s=scope,t=ticket,keyTag='vsc-platform-request:'+session().actor+':'+s.project+':'+path;
    if(busy)throw new Error('上一操作仍在处理中');
    const prior=pending.get(keyTag)||recall(keyTag);if(prior&&JSON.stringify(prior.payload)!==JSON.stringify(payload))throw new Error('原操作回执未确认，请先按原输入重试；新输入已保留。');
    const request=prior||{payload,expected_revision:session().revision,idempotency_key:uid(),confirmed:true};busy=true;pending.set(keyTag,request);remember(keyTag,request);
    try{const result=await ctx.api(endpoint(s.project,path),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request)});
      pending.delete(keyTag);remember(keyTag,null);if(same(t,s))ctx.setRevision(result.revision,s.project);return result;
    }catch(error){if(error.status>=400&&error.status<500){pending.delete(keyTag);remember(keyTag,null);}throw error;}finally{if(same(t,s))busy=false;}
  }
  async function reload(){await load({...scope,offset});}
  function professional(){const nav=el('nav',null,'platform-professional');bindAttribute(nav,'aria-label',msg("ui.full_specialist_entry"));for(const [p,title]of [['project-management',msg("shell.project_directory")],['source',msg("ui.source_parsing")],['script',msg("nav.script")],['designs',msg("ui.scene_and_shot_design")],['library',msg("ui.project_asset_library")],['classic-production',msg("ui.classic_production")],['candidates',msg("ui.generation_and_candidates")],['editing',msg("ui.edit_workspace")],['delivery',msg("ui.edit_delivery")],['workbench',msg("ui.scene_and_shot_relationships")],['media',msg("ui.media")],['artifacts',msg("ui.documents_and_versions")],['canvas',msg("ui.relationship_canvas")],['creative-canvas',msg("ui.creative_canvas")],['blocking',msg("ui.staging_design")],['previs',msg("ui.spatial_previs")],['creative-tools',msg("ui.music_and_video_tools")],['text-tools',msg("ui.script_and_analysis_tools")],['media-imports',msg("common.batch_import")]])nav.append(link(title,p));return nav;}
  function artwork(name,alt=''){const img=el('img');img.src='/static/workbench-art/'+name;bindAttribute(img,"alt",alt);img.loading='lazy';return img;}
  function createFlow(type='series'){createProject(type);}
  const currentProjects=()=>scopedProjects(ctx.projects(),session(),directoryScope(scope?.projectScope));
  const creationProjects=()=>scopedProjects(ctx.projects(),session()).filter(row=>!row.unavailable&&row.storage_policy==='postgres-series-v1'&&!['vsc.text-tools','vsc.creative-tools'].includes(row.profile_id||row.profile)&&!['text-tools','creative-tools'].includes(row.profile_snapshot?.workspace_kind));
  const homeIdentity=()=>JSON.stringify([session().actor,session().identityId]);
  async function homeContext(current){
    await ctx.refreshProjects({isCurrent:current});if(!current())return;
    const projects=creationProjects();if(!projects.length)return {empty:true};
    const discovery=await ctx.api('/api/v1/discovery',{headers:{'X-CSRF-Token':session().csrf}});if(!current())return;
    const recent=discovery.recent.find(row=>projects.some(project=>project.id===row.project_id));
    const project=projects.find(row=>row.id===recent?.project_id)||projects[0];
    let first=null,episode=null,offset=0;
    do{
      const result=await ctx.api(endpoint(project.id,'production-platform?'+new URLSearchParams({offset:String(offset),limit:'100'})));if(!current())return;
      const rows=result.episodes.items;first||=rows[0];episode=rows.find(row=>row.id===recent?.episode_id)||episode;
      offset=result.episodes.next_offset;
    }while(recent?.episode_id&&!episode&&offset!=null);
    episode||=first;if(!episode)throw new Error('项目中没有可用剧集，请先在项目中创建剧集。');
    return {project,episode,recent};
  }
  async function openHomeCreation(page,options={}){
    const t=ticket,s=scope,identity=homeIdentity();if(homeOpening?.current())return;
    const operation={current:()=>same(t,s)&&identity===homeIdentity()};homeOpening=operation;
    const controls=[...root.querySelectorAll('.home-tool'),...root.querySelectorAll('.home-canvas-card'),...root.querySelectorAll('.home-feature')].filter(node=>node.tagName==='BUTTON');
    for(const control of controls)control.disabled=true;
    try{
      if(options.ai_mv==='1'){if(!session().actor||!session().writeAvailable)throw new Error('当前会话不能创建项目。');await ctx.createEmptyCanvasProject({isCurrent:operation.current,aiMv:true});return;}
      const context=await homeContext(operation.current);if(!operation.current())return;
      if(context.empty){if(!session().actor||!session().writeAvailable)throw new Error('当前会话不能创建项目。');if(page==='creative-canvas')await ctx.createEmptyCanvasProject({isCurrent:operation.current});else createProject('series',{page,options,homeDefault:true});return;}
      let target={...options,episode:context.episode.id};
      if(page==='creative-canvas'){
        const p=context.project.id,e=context.episode.id,key='vsc-home-canvas:'+identity+':'+p+':'+e;
        let request=recall(key);
        if(!request){
          const listing=await ctx.api(endpoint(p,'creative-canvases?episode_id='+encodeURIComponent(e)));if(!operation.current())return;
          const recent=listing.items.find(row=>row.id===context.recent?.target_id&&context.recent?.kind==='canvas');
          const canvas=recent||listing.items[0];
          if(canvas)target.task_target=canvas.id;
          else{
            if(!session().writeAvailable||context.project.read_only)throw new Error('当前项目没有画布，且没有创建权限。');
            request={payload:{episode_id:e,title:'未命名画布',document:{nodes:[],edges:[]}},expected_revision:listing.revision,idempotency_key:uid()};remember(key,request);
          }
        }
        if(request){const saved=await ctx.api(endpoint(p,'creative-canvases'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request)});if(!operation.current())return;target.task_target=saved.id;}
        await ctx.navigate(page,null,p,target);remember(key,null);
      }else await ctx.navigate(page,null,context.project.id,target);
    }catch(error){if(operation.current())ctx.notice(error.message);}
    finally{if(homeOpening===operation)homeOpening=null;if(operation.current())for(const control of controls)control.disabled=false;}
  }
  function openCreation(page,options={}){
    const rows=scopedProjects(ctx.projects(),session()).filter(r=>!['vsc.text-tools','vsc.creative-tools'].includes(r.profile_id||r.profile));
    const dialog=el('dialog',null,'platform-create');bindAttribute(dialog,'aria-label',msg("ui.select_a_creative_project"));dialog.append(el('h2',msg("ui.select_a_creative_project")));
    for(const row of rows)dialog.append(button(row.name,async()=>{dialog.close();await ctx.navigate(page,null,row.id,options);}));
    dialog.append(actions(button(msg("ui.new_short_drama"),()=>{dialog.close();createProject('series',{page,options});}),button(msg("ui.new_short_video"),()=>{dialog.close();createProject('short',{page,options});}),button(msg("common.cancel"),()=>dialog.close())));
    root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  }
  async function home(t){
    root.classList.add('platform-home');header(msg("home.creation_hero_title"));
    const section=el('div',null,'home-section-heading');section.append(el('h2',msg("home.creation_canvas_subtitle")),link(msg("ui.view_existing_canvases"),'projects',null,null,{tab:'canvases'}));root.append(section);
    const hero=el('div',null,'home-hero'),main=button('',()=>openHomeCreation('creative-canvas'));main.className='home-canvas-card';
    main.append(artwork('canvas.svg'),el('span',msg("ui.connect_your_creative_ideas_on_one_canvas"),'home-canvas-slogan'),el('span',msg("ui.open_intelligent_canvas"),'home-canvas-action'));hero.append(main);
    const features=el('div',null,'home-feature-grid');
    for(const [title,desc,file,tool,badges]of [[msg('replica.commerce_skills_title'),msg('replica.commerce_skills_description'),'commerce-skills.webp','skills',['Agent']],['AI MV',msg("ui.upload_music_and_let_ai_direct_your_mv"),'aimv.jpg','mv',['Agent',msg('replica.skill_tag')]],[msg("home.creation_segment_remake_title"),msg("home.creation_segment_remake_description"),'remake.jpg','segment_remake',['SD 2.5',msg('replica.official_example')]],[msg("home.creation_video_depth_title"),msg("home.creation_video_depth_description"),'motion.jpg','breakdown',['SD 2.5',msg('replica.official_example')]]]){
      const card=tool==='skills'?link('', 'marketing-studio',null,null):tool==='mv'?button('',()=>openHomeCreation('creative-canvas',{ai_mv:'1'})):link('', 'creative-tools',null,null,{tool});card.className='home-feature';const tags=el('small',null,'home-feature-badge');for(const badge of badges)tags.append(el('span',badge));card.append(artwork(file),tags);if(tool==='skills')card.append(el('span','NEW','home-feature-new'));const copy=el('div',null,'home-feature-copy');copy.append(el('h3',title),el('p',desc));card.append(copy);features.append(card);
    }hero.append(features);root.append(hero,el('h2',msg("ui.start_creating_with_agent_tools"),'home-tool-heading'));
    const grid=el('div',null,'home-tools');
    for(const [title,desc,page,tool,icon,tag]of [[msg("home.creation_ai_video_generation_title"),msg("home.creation_ai_video_generation_description"),'classic-production','video','video',msg("home.creation_tag_tool")],[msg("home.creation_ai_storyboard_title"),msg("home.creation_ai_storyboard_description"),'classic-production','image','image',msg("home.creation_tag_tool")],[msg("ui.script_breakdown"),msg("ui.reconstruct_dialogue_and_shots_frame_by_frame_to_create"),'text-tools','breakdown','breakdown','Agent'],[msg("home.creation_agent_creation_title"),msg("home.creation_agent_creation_description"),'intelligent-creation','','agent','Agent'],[msg("nav.script_scoring"),msg("home.creation_script_scoring_description"),'text-tools','scoring','scoring','Agent'],[msg("nav.novel_parser"),msg("home.creation_novel_parser_description"),'text-tools','novel','novel','Agent'],[msg("nav.script_translation"),msg("home.creation_script_translation_description"),'text-tools','translation','translation','Agent'],[msg("nav.video_quality_check"),msg("ui.check_video_subtitle_and_content_issues"),'text-tools','qc','qc','Agent']]){
      const card=page==='classic-production'||page==='intelligent-creation'?button('',()=>openHomeCreation(page,page==='classic-production'?{kind:tool}:{})):link('',page,null,null,{tool});card.className='home-tool';card.append(artwork(icon+'.svg'),el('small',tag,'home-tool-tag'));const copy=el('div'),titleRow=el('div',null,'home-tool-title');titleRow.append(el('h3',title));if(tool==='breakdown')titleRow.append(el('span','NEW','home-tool-new'));copy.append(titleRow,el('p',desc));card.append(copy);grid.append(card);
    }root.append(grid);
    const footer=el('footer',null,'home-footer');footer.append(el('span',msg("ui.vsc_creative_workbench")),link(msg("ui.resource_and_model_settings"),'settings',null),link(msg("shell.tasks"),'tasks'),link(msg("ui.workspace_maintenance"),'maintenance',null));root.append(footer);await homeDiscovery(t);
  }
  async function homeDiscovery(t){
    const region=el('section',null,'home-discovery');bindAttribute(region,'aria-label',msg('home.recent_creations'));root.append(region);
    async function refresh(){
      const identity=session().actor,current=()=>same(t)&&identity===session().actor;
      if(!current())return;const loading=el('p',msg('ui.loading_recent_creations'),'hint');region.replaceChildren(loading);region.setAttribute('aria-busy','true');
      try{const visible=new Set(scopedProjects(ctx.projects(),session()).map(row=>row.id));await mountDiscovery(region,{...ctx,api:async(path,options)=>{const data=await ctx.api(path,options);if(path==='/api/v1/discovery')return {...data,recent:data.recent.filter(row=>visible.has(row.project_id)),projects:data.projects.filter(row=>visible.has(row.id)),templates:data.templates.filter(row=>visible.has(row.project_id))};return data;}},{isCurrent:current});if(current())loading.remove();}
      catch(error){if(current()){const heading=el('div',null,'home-section-heading');heading.append(el('h2',msg('home.recent_creations')));region.replaceChildren(heading,el('p',error.status===403?msg('ui.start_a_session_to_see_recent_creations'):error.message,'hint'),button(msg('ui.reload'),refresh));}}
      finally{if(current())region.removeAttribute('aria-busy');}
    }
    await refresh();
  }
  function projectCover(row,title,open){
    const tile=el('article',null,'project-tile'),cover=button('',open);cover.className='project-cover';bindAttribute(cover,'aria-label',msg("ui.open_value0",{value0:title}));
    if(row.cover){const preview=el(row.cover.modality==='video'?'video':'img');preview.src=row.cover.content_url;if(preview.tagName==='VIDEO'){preview.muted=true;preview.preload='metadata';}else{bindAttribute(preview,"alt",'');preview.loading='lazy';}preview.addEventListener('error',()=>{preview.remove();cover.append(el('span',msg("ui.preview_is_currently_unavailable"),'project-cover-empty'));},{once:true});cover.append(preview);}else cover.append(el('span',msg("ui.no_project_preview_yet"),'project-cover-empty'));
    const mark=el('span',null,'project-cover-mark');mark.innerHTML='<svg viewBox="0 0 64 64" fill="none" aria-hidden="true"><rect x="17" y="11" width="32" height="42" rx="3" fill="currentColor"/><path d="M13 16v40h31" stroke="currentColor" stroke-width="3"/><path d="M24 20h18M24 26h14" stroke="#1d1d1d" stroke-width="2"/></svg>';if(!row.cover)cover.append(mark);
    tile.append(cover,el('h3',title,'project-title'));return {tile,cover};
  }
  const projectCategories=[['personal','workspace.personal_projects'],['participating','workspace.participating_projects'],['team','workspace.team_projects']];
  function projectCategoryTabs(){
    const current=directoryScope(scope.projectScope),viewTab=scope.tab,nav=el('nav',null,'project-category-tabs');
    nav.setAttribute('role','tablist');bindAttribute(nav,'aria-label',msg('workspace.project_categories'));
    const activate=async key=>{await ctx.navigate('projects',null,null,{...(viewTab?{tab:viewTab}:{}),project_scope:key});root.querySelector('#project-category-'+key)?.focus?.();};
    projectCategories.forEach(([key,label],index)=>{
      const tab=el('a',msg(label));tab.href='?'+new URLSearchParams({page:'projects',...(viewTab?{tab:viewTab}:{}),project_scope:key});tab.id='project-category-'+key;
      tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(key===current));tab.setAttribute('aria-controls','project-category-results');tab.tabIndex=key===current?0:-1;
      tab.addEventListener('click',async event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();await activate(key);});
      tab.addEventListener('keydown',async event=>{const next=event.key==='ArrowRight'?(index+1)%3:event.key==='ArrowLeft'?(index+2)%3:event.key==='Home'?0:event.key==='End'?2:null;if(next==null)return;event.preventDefault();await activate(projectCategories[next][0]);});nav.append(tab);
    });return nav;
  }
  async function projects(t){
    const category=directoryScope(scope.projectScope),canvases=scope.tab==='canvases'||scope.tab==='canvas',media=scope.tab==='media';
    root.classList.add('platform-projects');
    const heading=header(msg('workspace.project_directory')),add=button(msg('ui.new_project'),()=>createFlow(),!session().actor||!session().writeAvailable);add.className='primary project-create-action';heading.append(add);
    const navigation=el('div',null,'project-directory-navigation'),libraries=el('nav',null,'project-library-links');bindAttribute(libraries,'aria-label',msg('ui.project_category'));
    if(canvases||media)libraries.append(link(msg('workspace.back_to_projects'),'projects',null,null,{project_scope:category}));
    for(const [label,tab]of [['workspace.canvas_library','canvases'],['workspace.media_library','media']]){const a=link(msg(label),'projects',null,null,{tab,project_scope:category});if((canvases&&tab==='canvases')||(media&&tab==='media'))a.setAttribute('aria-current','page');libraries.append(a);}
    navigation.append(projectCategoryTabs(),libraries);root.append(navigation);
    const region=el('section',null,'project-category-results');region.id='project-category-results';region.setAttribute('role','tabpanel');region.setAttribute('aria-labelledby','project-category-'+category);
    if(canvases||media){root.append(region);if(canvases)await canvasCatalog(t);else{const slot=el('div',null,'project-toolbar');region.append(slot);await mediaCatalog(t,slot);}return;}
    const toolbar=el('div',null,'project-directory-toolbar'),query=el('input'),total=el('span',null,'project-total');query.type='search';bindAttribute(query,'placeholder',msg('replica.search_projects'));bindAttribute(query,'aria-label',msg('ui.search_projects'));total.setAttribute('role','status');toolbar.append(query,total);root.append(toolbar,region);
    const rows=currentProjects().filter(row=>!['vsc.text-tools','vsc.creative-tools'].includes(row.profile)&&!['vsc.text-tools','vsc.creative-tools'].includes(row.profile_id)&&!['text-tools','creative-tools'].includes(row.profile_snapshot?.workspace_kind)),grid=el('div',null,'project-grid');region.append(grid);
    const draw=()=>{
      grid.replaceChildren();const filtered=rows.filter(row=>row.name.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()));setText(total,msg('replica.project_count',{count:filtered.length}));
      if(!filtered.length){
        const empty=el('div',null,'project-directory-empty');
        if(query.value.trim()){empty.append(el('p',msg('workspace.no_search_results')),button(msg('workspace.clear_search'),()=>{query.value='';draw();query.focus?.();}));}
        else{empty.append(el('p',msg('workspace.'+category+'_empty')));if(category!=='personal')empty.append(el('small',msg('workspace.'+category+'_hint')));}
        grid.append(empty);return;
      }
      for(const row of filtered){
        const {tile,cover}=projectCover(row,row.name,()=>ctx.navigate(row.storage_policy==='postgres-series-v1'?'project':'script',null,row.id));tile.dataset.projectId=row.id;
        const frame=el('div',null,'project-cover-wrap');cover.replaceWith(frame);frame.append(cover);
        if(row.read_only)frame.append(el('span',msg('ui.read_only_project'),'project-readonly'));
        if(!row.read_only){
          const operations=el('div',null,'project-card-actions');
          for(const [operation,label,shape]of [['rename','workspace.rename_project','<path d="m4 12 9-9 4 4-9 9-5 1Z M11 5l4 4 M17 12v6H3V4h6"/>'],['trash','workspace.delete_project','<path d="M3 5h14 M6 5V2h8v3 M5 5l1 13h8l1-13 M8 8v7 M12 8v7"/>']]){
            const action=button('',()=>manageCard(row,operation),!session().actor);bindAttribute(action,'aria-label',msg(label,{name:row.name}));bindAttribute(action,'title',msg(label,{name:row.name}));
            action.innerHTML='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+shape+'</svg>';operations.append(action);
          }frame.append(operations);
        }
        const meta=el('p',null,'project-date'),date=new Date(row.updated_at||row.created_at);
        if(Number.isFinite(date.getTime())){const time=el('time',new Intl.DateTimeFormat(getLocale(),{year:'numeric',month:'2-digit',day:'2-digit'}).format(date));time.dateTime=date.toISOString();meta.append(time);}
        if(row.project_type)meta.append(el('span',row.project_type,'project-type'));tile.append(meta);grid.append(tile);
      }
    };query.addEventListener('input',draw);draw();
  }
  async function mediaCatalog(t,toolbarSlot=null){
    root.classList.add('platform-media');const host=el('section');(root.querySelector('.project-category-results')||root).append(host);
    const {createMediaLibrary}=await import('./media-library.js');if(!same(t))return;
    mediaLibrary=createMediaLibrary(host,{...ctx,toolbarSlot,api:(path,options)=>ctx.api(path.startsWith('/api/v1/project-media?')?scopedDirectoryPath(path,session(),scope.projectScope):path,options),
      projects:async({isCurrent,signal})=>{if(!same(t)||!isCurrent())return;const value=await ctx.api('/api/v1/projects',{signal});if(!same(t)||!isCurrent())return;if(!Array.isArray(value.items))throw new Error(translate(msg('media.library.invalid_response')));return {items:scopedProjects(value.items,session(),scope.projectScope).filter(row=>row.storage_policy==='postgres-series-v1'&&!row.unavailable)};},
      episodes:async(project,{isCurrent,signal})=>{const items=[];let next=0;do{if(!same(t)||!isCurrent())return;const value=await ctx.api(endpoint(project,'production-platform?'+new URLSearchParams({offset:String(next),limit:'100'})),{signal});if(!same(t)||!isCurrent())return;const page=value.episodes;if(!page||!Array.isArray(page.items)||!(page.next_offset===null||Number.isInteger(page.next_offset)&&page.next_offset>next))throw new Error(translate(msg('media.library.invalid_response')));items.push(...page.items);next=page.next_offset;}while(next!=null);return {items};}
    });
    await mediaLibrary.load();
  }
  async function manageCard(row,operation){
    if(operation==='rename')return createProject('series',{edit:row});
    const removing=operation==='trash',t=ticket,identity=session().actor,dialog=el('dialog',null,'platform-create'),form=el('form');
    bindAttribute(dialog,'aria-label',operation==='rename'?msg("ui.rename_project"):msg("ui.tip"));
    form.append(el('h2',operation==='rename'?msg("ui.rename_project"):msg("ui.tip")));
    if(removing)form.append(el('p',msg("ui.delete_project_confirm",{value0:row.name})));else form.append(el('p',row.name));
    const value=removing?null:field(form,msg("novel-parser.project_name"),el('input'));
    if(value){value.required=true;value.maxLength=200;value.value=row.name;}
    const message=el('p',null,'hint'),save=el('button',operation==='rename'?msg("ui.save_name"):msg("common.confirm"));
    if(removing)save.className='danger';
    save.type='submit';form.append(message,actions(save,button(msg("common.cancel"),()=>dialog.close())));dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();if(value)value.focus();
    const requestKey='vsc-project-card:'+identity+':'+row.id+':'+operation;let request=recall(requestKey);
    if(request){if(value)value.value=request.payload.title||'';setText(message,msg("ui.the_previous_receipt_is_unconfirmed_retrying_will_recover_the"));}
    form.addEventListener('submit',async e=>{e.preventDefault();if(!same(t)||identity!==session().actor)return;save.disabled=true;try{if(!request){const current=await ctx.api(endpoint(row.id,'management?limit=1'));if(!same(t)||identity!==session().actor)return;request={payload:operation==='rename'?{operation,title:value.value.trim()}:{operation,target_type:'project',target_id:row.id,reason:translate(msg("ui.delete_project"))},expected_revision:current.revision,idempotency_key:uid()};remember(requestKey,request);}const result=await ctx.api(endpoint(row.id,'management'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request)});if(!same(t)||identity!==session().actor)return;remember(requestKey,null);if(result.status==='protected'){request=null;throw new Error(result.reasons.map(r=>r.message).join('；'));}dialog.close();if(removing)ctx.notice(msg("ui.project_deleted"));await ctx.refreshProjects?.();if(same(t))await reload();}catch(error){if(error.status>=400&&error.status<500){request=null;remember(requestKey,null);}setText(message,error.message+(request?'；重试将恢复同一操作回执。':''));}finally{if(dialog.isConnected)save.disabled=false;}});
  }
  async function canvasCatalog(t){
    const host=el('section');(root.querySelector('.project-category-results')||root).append(host);
    canvasLibrary=createCanvasLibrary(host,{...ctx,api:(path,options)=>ctx.api(path.startsWith('/api/v1/canvas-library')?scopedDirectoryPath(path,session(),scope.projectScope):path,options),
      projects:async({isCurrent})=>{if(!same(t)||!isCurrent())return;const value=await ctx.api(scopedDirectoryPath('/api/v1/canvas-library/options',session(),scope.projectScope));if(!same(t)||!isCurrent())return;if(!Array.isArray(value.projects)||!Array.isArray(value.creators))throw new Error(translate(msg('canvas.library.invalid_response')));return {items:value.projects,creators:value.creators};},
      episodes:async(project,{isCurrent})=>{const items=[];let next=0;do{if(!same(t)||!isCurrent())return;const value=await ctx.api(endpoint(project,'production-platform?'+new URLSearchParams({offset:String(next),limit:'100'})));if(!same(t)||!isCurrent())return;const page=value.episodes;if(!page||!Array.isArray(page.items)||!(page.next_offset===null||Number.isInteger(page.next_offset)&&page.next_offset>next))throw new Error(translate(msg('canvas.library.invalid_response')));items.push(...page.items);next=page.next_offset;}while(next!=null);return {items};}
    });
    // The directory uses the explicit workspace/aggregate scope, never an incidental open project.
    await canvasLibrary.load();
  }
  async function createProject(type,next={}){
    closeCreation?.();
    const editing=next.edit,canvas=type==='canvas',dialog=el('dialog',null,'platform-create'+(canvas?'':' project-create-dialog'));bindAttribute(dialog,'aria-label',editing?msg('project.edit_project'):canvas?msg("shell.new_canvas"):msg("project.create_project"));const form=el('form');
    const s=scope,t=ticket,identity=session().actor,identityKey=homeIdentity(),requestKey=editing?'vsc-platform-edit:'+identityKey+':'+editing.id:'vsc-platform-create:'+identityKey+':'+type,draftKey=requestKey+':draft';
    let request=recall(requestKey),submitted=false,closed=false,selecting=false,fileTicket=0,previewUrl=null,selected=creationFiles.get(requestKey)||null,editBaseline=null,editLoading=Boolean(editing),baseCover=editing?.cover||null,coverSelection=null,clearCover=false;
    const current=()=>same(t,s)&&identityKey===homeIdentity()&&!closed;
    if(request?.cover&&selected?.sha256!==request.cover.sha256)selected=null;
    const heading=el('header',null,'project-create-heading');heading.append(el('h2',editing?msg('project.edit_project'):canvas?msg('shell.new_canvas'):msg('project.create_project')));
    const close=button('×',()=>dialog.close());close.className='project-create-close';bindAttribute(close,'aria-label',msg('common.close'));heading.append(close);form.append(heading);
    const body=el('div',null,'project-create-body'),nameLabel=el('label',null,'project-create-field'),nameText=el('span','名称'),required=el('span','*','project-create-required');required.setAttribute('aria-hidden','true');nameText.append(required);nameLabel.append(nameText);
    const nameWrap=el('div',null,'project-name-input'),name=el('input'),count=el('span','0 / 50','project-name-count');name.required=true;name.maxLength=50;name.placeholder='请输入名称';bindAttribute(name,'aria-label',msg('ui.sky_project_name'));nameWrap.append(name,count);nameLabel.append(nameWrap);body.append(nameLabel);
    const showCount=()=>setText(count,`${name.value.length} / 50`);name.addEventListener('input',showCount);
    let episodes=null;const styles=[],steps=[];
    if(!canvas){
      const episodeLabel=el('label',null,'project-create-field'),title=el('span',msg('ui.episode_count'));title.append(el('span','*','project-create-required'));episodeLabel.append(title);
      const wrap=el('div',null,'project-count-input');episodes=el('input');episodes.type='number';episodes.required=true;episodes.min='1';episodes.max='500';episodes.step='1';episodes.value='1';bindAttribute(episodes,'aria-label',msg('ui.episode_count'));
      const adjust=delta=>{if(!episodes.disabled)episodes.value=String(Math.min(500,Math.max(1,Math.trunc(Number(episodes.value)||1)+delta)));};
      const stepper=el('div',null,'project-count-steps');for(const [delta,title,glyph]of [[1,'增加集数','⌃'],[-1,'减少集数','⌄']]){const b=button(glyph,()=>adjust(delta));bindAttribute(b,'aria-label',title);steps.push(b);stepper.append(b);}wrap.append(episodes,stepper);episodeLabel.append(wrap);body.append(episodeLabel);
      const kinds=el('fieldset',null,'project-create-field project-type-options');kinds.append(el('legend',msg('project.project_type')));const group=el('div'),groupName='project-style-'+uid();
      for(const [value,title]of [['2d',msg('ui.style_2d')],['3d',msg('ui.style_3d')],['live',msg('ui.style_live')]]){const label=el('label'),radio=el('input');radio.type='radio';radio.name=groupName;radio.value=value;radio.checked=value==='live';bindAttribute(radio,'aria-label',title);styles.push(radio);label.append(radio,el('span',title));group.append(label);}kinds.append(group);body.append(kinds);
    }
    const coverSection=el('div',null,'project-cover-field'),coverLabel=el('p','上传封面'),coverHint=el('p','封面图建议正方形尺寸，大小不超过5MB','project-cover-hint'),upload=el('label',null,'project-cover-upload'),fileInput=el('input'),preview=el('div',null,'project-cover-preview'),fileNotice=el('p',null,'project-cover-feedback');
    fileNotice.setAttribute('role','status');fileInput.type='file';fileInput.accept='image/*';bindAttribute(fileInput,'aria-label','上传封面');upload.append(preview,fileInput);const remove=button('移除封面',()=>{fileTicket++;selecting=false;if(editing&&!selected)clearCover=true;selected=null;creationFiles.delete(requestKey);fileInput.value='';setText(fileNotice,'');drawCover();retainDraft();});remove.className='project-cover-remove';coverSection.append(coverLabel,coverHint,upload,remove,fileNotice);if(!canvas)body.append(coverSection);
    const message=el('p',null,'hint project-create-status');message.setAttribute('role','status');const save=el('button',canvas?msg('ui.create_project'):'确定');save.type='submit';save.className='project-create-confirm';
    const footer=el('footer',null,'project-create-footer');footer.append(button(msg('common.cancel'),()=>dialog.close()),save);form.append(body,message,footer);
    if(canvas){form.replaceChildren(el('h2',msg('shell.new_canvas')));field(form,msg('ui.sky_project_name'),name);form.append(message,actions(save,button(msg('common.cancel'),()=>dialog.close())));}
    const ownerChoice=el('select');bindAttribute(ownerChoice,'aria-label',msg('workspace.project_owner'));ownerChoice.append(localizedOption('',msg('workspace.personal_owner',{name:session().actor||''})));for(const team of session().ownerships||[])if(team.kind!=='personal'&&team.roles?.some(role=>['owner','editor'].includes(role)))ownerChoice.append(localizedOption(team.id,team.name));if(request)ownerChoice.value=request.workspace_id||'';if(!editing){const ownerLabel=el('label',msg('workspace.project_owner'),'project-create-workspace');ownerLabel.append(ownerChoice);form.prepend(ownerLabel);}
    dialog.append(form);root.append(dialog);
    const lock=()=>{const frozen=submitted||editLoading||Boolean(editing&&!editBaseline)||Boolean(request);for(const input of [name,episodes,ownerChoice,...styles,...steps])if(input)input.disabled=frozen;fileInput.disabled=editLoading||submitted||Boolean(editing&&!editBaseline)||selecting||Boolean(request&&(!request.cover||selected||request.cover.applied));remove.disabled=frozen;save.disabled=submitted||editLoading||selecting||!identity||!session().writeAvailable;};
    function drawCover(){
      if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}preview.replaceChildren();
      if(selected){previewUrl=URL.createObjectURL(selected.file);const image=el('img');image.src=previewUrl;image.alt='封面预览';preview.append(image);}else if(request?.cover?.content_url||editing&&!clearCover&&baseCover?.content_url){const image=el('img');image.src=request?.cover?.content_url||baseCover.content_url;image.alt='封面预览';preview.append(image);}else preview.append(el('span','+','project-cover-plus'),el('span',request?.cover?'重新选择原封面':'上传图片'));
      remove.hidden=(!selected&&!(editing&&coverSelection?.media_id&&!clearCover))||Boolean(request);setText(remove,editing&&!selected?msg('ui.restore_automatic_cover'):'移除封面');lock();
    }
    fileInput.addEventListener('change',async()=>{
      const file=fileInput.files?.[0],token=++fileTicket;if(!file)return;selecting=true;lock();setText(fileNotice,'正在读取封面…');
      try{
        if(file.size>5*1024*1024)throw new Error('封面大小不能超过5MB');if(!file.size)throw new Error('请选择有效的图像文件');
        const image=await createImageBitmap(file);const valid=image.width>0&&image.height>0;image.close();if(!valid)throw new Error('请选择有效的图像文件');
        const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),n=>n.toString(16).padStart(2,'0')).join('');
        if(!current()||token!==fileTicket)return;if(request?.cover&&sha256!==request.cover.sha256)throw new Error('请重新选择上次的原封面文件；文件内容不能更换');
        selected={file,filename:file.name,size_bytes:file.size,sha256};clearCover=false;creationFiles.set(requestKey,selected);setText(fileNotice,'');drawCover();
      }catch(error){if(current()&&token===fileTicket){fileInput.value='';setText(fileNotice,error.name==='InvalidStateError'?'请选择可读取的图像文件':error.message);}}
      finally{if(current()&&token===fileTicket){selecting=false;lock();}}
    });
    if(editing){name.value=editing.name;episodes.value=String(editing.counts?.episodes||1);for(const radio of styles)radio.checked=radio.value===(editing.profile_snapshot?.character_style||'live');}
    const draft=editing?recall(draftKey):null;if(draft){name.value=draft.name;episodes.value=draft.count;for(const radio of styles)radio.checked=radio.value===draft.style;clearCover=Boolean(draft.clearCover);}
    const retainDraft=()=>{if(editing&&!request)remember(draftKey,{name:name.value,count:episodes.value,style:styles.find(r=>r.checked)?.value||'live',clearCover});};
    if(editing){form.addEventListener('input',retainDraft);form.addEventListener('change',retainDraft);}
    if(request){clearCover=Boolean(request.clearCover);name.value=request.payload.name||request.payload.title;if(episodes)episodes.value=String(request.count??request.payload.episode_count);for(const radio of styles)radio.checked=radio.value===(request.payload.character_style||'live');setText(message,request.phase==='readback'?(editing?'项目已保存，重试将刷新项目列表。':'项目已创建，重试将继续打开已创建项目。'):msg('ui.the_previous_receipt_is_unconfirmed_retrying_will_recover_the'));}
    showCount();drawCover();dialog.showModal();const closeThis=()=>dialog.close();closeCreation=closeThis;
    async function loadEditBaseline(preserve=false){
      editLoading=true;lock();setText(message,msg('ui.loading'));
      try{const [latest,cover]=await Promise.all([ctx.api(endpoint(editing.id,'management?limit=1')),ctx.api(endpoint(editing.id,'cover'))]);if(!current())return;
        editBaseline=latest;coverSelection=cover.selection;baseCover=cover.cover;if(!preserve&&!request&&!draft){name.value=latest.project.name;episodes.value=String(Math.max(1,latest.episode_count));for(const radio of styles)radio.checked=radio.value===(latest.project.profile_snapshot?.character_style||'live');}
        setText(message,request?request.phase==='readback'?'项目已保存，重试将刷新项目列表。':'原编辑操作已保留，重试将恢复同一操作。':'');showCount();drawCover();
      }catch(error){if(current())setText(message,error.message+'；点击确定重新读取，未保存的编辑已保留。');}
      finally{if(current()){editLoading=false;lock();}}
    }
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(editing&&!editBaseline&&!request){if(!editLoading&&current())await loadEditBaseline(true);return;}if(submitted||selecting||!current()||!identity||!session().writeAvailable)return;submitted=true;save.disabled=true;
      try{
        if(!request){
          if(editing){const total=Number(episodes.value);if(!name.value.trim()||name.value.length>50)throw new Error('项目名称需为1至50字');if(!Number.isInteger(total)||total<1||total>500)throw new Error('项目集数需为1至500的整数');if(total<editBaseline.episode_count)throw new Error('减少集数需在项目管理中明确选择要回收的剧集；当前编辑不会删除剧集');}
          const count=episodes?Math.min(500,Math.max(1,Math.trunc(Number(episodes.value)||1))):0;request={payload:{name:name.value.trim(),profile:canvas||count<=1?'vsc.light-short':'vsc.series-pg',...(canvas?{}:{character_style:styles.find(r=>r.checked)?.value||'live'})},count,idempotency_key:uid(),offset:0,phase:'write',next,...(!canvas&&selected?{cover:{filename:selected.filename,size_bytes:selected.size_bytes,sha256:selected.sha256}}:{})};if(editing)request={payload:{operation:'edit',title:name.value.trim(),episode_count:count,character_style:styles.find(r=>r.checked)?.value||'live'},project_id:editing.id,expected_revision:editBaseline.revision,revision:editBaseline.revision,idempotency_key:request.idempotency_key,phase:'write',...(request.cover?{cover:request.cover}:{}),clearCover};remember(requestKey,request);lock();}
        if(editing&&request.rebaseCover){const latest=await ctx.api(endpoint(request.project_id,'cover'));if(!current())return;request.revision=latest.revision;
          if(request.cover){if(!request.cover.batch_id)delete request.cover.batch_request;if(!request.cover.media_id)delete request.cover.process_request;if(!request.cover.applied)delete request.cover.selection_request;}
          if(!request.coverCleared)delete request.clearRequest;request.rebaseCover=false;remember(requestKey,request);
        }
        if(editing&&!request.saved){const result=await ctx.api(endpoint(request.project_id,'management'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request.payload,expected_revision:request.expected_revision,idempotency_key:request.idempotency_key})});request.saved=true;request.revision=result.revision;remember(requestKey,request);if(!current())return;}
        if(!request.project_id){
          if(!Object.hasOwn(request,'workspace_id')){request.workspace_id=ownerChoice.value||null;remember(requestKey,request);}const result=await ctx.api('/api/v1/projects',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request.payload,idempotency_key:request.idempotency_key,workspace_id:request.workspace_id||null})});
          request.project_id=result.id;request.revision=result.revision??0;remember(requestKey,request);if(!current())return;
        }
        while(!editing&&request.offset<request.count){
          const start=request.offset,titles=Array.from({length:Math.min(50,request.count-start)},(_,index)=>'第'+(start+index+1)+'集');
          const saved=await ctx.api('/api/v1/projects/'+encodeURIComponent(request.project_id)+'/episode-batches',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:{titles,initial_shot_count:0},expected_revision:request.revision,idempotency_key:request.idempotency_key+':episodes:'+start})});
          request.revision=saved.revision??request.revision;request.offset=start+titles.length;remember(requestKey,request);if(!current())return;
        }
        if(request.cover&&!await uploadProjectCover(request,{current,retain:()=>remember(requestKey,request),file:()=>creationFiles.get(requestKey)?.file,progress:text=>{if(current())setText(message,text);}}))return;
        if(editing&&request.clearCover&&!request.coverCleared){request.clearRequest||={payload:{media_id:null},expected_revision:request.revision,idempotency_key:request.idempotency_key+':cover-clear'};remember(requestKey,request);const cleared=await ctx.api(endpoint(request.project_id,'cover'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify(request.clearRequest)});request.coverCleared=true;request.revision=cleared.revision;remember(requestKey,request);if(!current())return;}
        request.phase='readback';remember(requestKey,request);
        await ctx.refreshProjects({isCurrent:current});if(!current())return;
        if(editing){remember(requestKey,null);remember(draftKey,null);creationFiles.delete(requestKey);ctx.notice(msg('ui.project_saved'));dialog.close();await reload();return;}
        const target=request.next||{};let targetOptions=target.options||{};
        if(target.homeDefault){const result=await ctx.api(endpoint(request.project_id,'production-platform?offset=0&limit=1'));if(!current())return;const first=result.episodes.items[0];if(!first)throw new Error('已创建项目中没有可用剧集，请重新读取原项目。');targetOptions={...targetOptions,episode:first.id};}
        ctx.notice(msg('ui.project_created'));
        await ctx.navigate(target.page||(canvas?'creative-canvas':'project'),null,request.project_id,targetOptions);
        remember(requestKey,null);creationFiles.delete(requestKey);if(!closed)dialog.close();
      }catch(error){
        if(editing&&request?.saved&&request.phase!=='readback'&&error.status===409){request.rebaseCover=true;remember(requestKey,request);}
        if(editing&&!request?.saved&&error.status>=400&&error.status<500){request=null;remember(requestKey,null);retainDraft();if(error.status===409)editBaseline=null;}
        if(!request?.project_id&&error.status>=400&&error.status<500&&error.status!==409){request=null;remember(requestKey,null);}
        if(current()){lock();setText(message,editing?(request?.phase==='readback'?'项目已保存，刷新未完成；重试只会重新读取。 '+error.message:error.message+(request?.rebaseCover?'；原编辑已保存。重试会读取最新版本，再继续原封面选择。':request?'；原编辑操作已保留，重试将恢复同一操作。':!editBaseline?'；点击确定读取最新版本后再保存。':'')):request?.phase==='readback'?'项目已创建，打开未完成。重试将继续打开已创建项目。 '+error.message:error.message+(request?'；原创建操作已保留，重试将继续该项目。':''));}
      }finally{if(current()){submitted=false;lock();}else if(!closed)dialog.close();}
    });
    dialog.addEventListener('close',()=>{retainDraft();closed=true;fileTicket++;if(previewUrl)URL.revokeObjectURL(previewUrl);if(closeCreation===closeThis)closeCreation=null;dialog.remove();},{once:true});name.focus();
    if(editing)await loadEditBaseline();
  }
  async function uploadProjectCover(request,{current,retain,file,progress}){
    const cover=request.cover,p=request.project_id,base=endpoint(p,'media-imports'),headers=()=>({'Content-Type':'application/json','X-CSRF-Token':session().csrf});
    const post=(path,body)=>ctx.api(path,{method:'POST',headers:headers(),body:JSON.stringify(body)});
    if(!current())return false;if(cover.applied)return true;request.phase='cover';progress('正在保存项目封面…');retain();
    if(!cover.batch_id){
      cover.batch_request||={payload:{title:'项目封面',rights:'unknown',files:[{filename:cover.filename,size_bytes:cover.size_bytes,sha256:cover.sha256}]},expected_revision:request.revision,idempotency_key:request.idempotency_key+':cover-import'};retain();
      const result=await post(base,cover.batch_request);cover.batch_id=result.id;request.revision=result.revision??request.revision;retain();if(!current())return false;
    }
    let batch=await ctx.api(base+'/'+encodeURIComponent(cover.batch_id));if(!current())return false;request.revision=batch.revision;let item=batch.items[0];cover.item_id=item.id;cover.media_id=item.media_id||cover.media_id;retain();
    if(!item.has_upload&&!cover.media_id){
      const original=file();if(!original)throw new Error('请重新选择上次的原封面文件继续上传；已保存的项目和分集已保留');
      const result=await ctx.api(base+'/'+encodeURIComponent(cover.batch_id)+'/items/'+encodeURIComponent(item.id)+'/upload?offset='+item.uploaded_bytes,{method:'PUT',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':session().csrf},body:original.slice(item.uploaded_bytes)});request.revision=result.revision??request.revision;retain();if(!current())return false;
      batch=await ctx.api(base+'/'+encodeURIComponent(cover.batch_id));if(!current())return false;request.revision=batch.revision;item=batch.items[0];cover.media_id=item.media_id||cover.media_id;retain();
    }
    if(!cover.media_id){
      cover.process_request||={payload:{batch_id:cover.batch_id,item_id:cover.item_id},expected_revision:request.revision,idempotency_key:request.idempotency_key+':cover-process'};retain();
      const result=await post(base+'/process',cover.process_request);cover.media_id=result.media_id;request.revision=result.revision??request.revision;retain();if(!current())return false;
    }
    cover.selection_request||={payload:{media_id:cover.media_id},expected_revision:request.revision,idempotency_key:request.idempotency_key+':cover-selection'};retain();
    const selected=await post(endpoint(p,'cover'),cover.selection_request);if(selected.selection?.media_id!==cover.media_id||!selected.cover?.content_url)throw new Error('封面结果尚未读回，请重试恢复原操作');cover.applied=true;cover.content_url=selected.cover.content_url;request.revision=selected.revision??request.revision;retain();return current();
  }
  async function openEpisodeTool(row,page,options={}){
    const s=scope,t=ticket,identity=homeIdentity();if(episodeOpening?.current())return;
    const operation={current:()=>same(t,s)&&identity===homeIdentity()};episodeOpening=operation;
    const controls=[...root.querySelectorAll('.episode-tool')];for(const control of controls)control.disabled=true;
    const key='vsc-episode-canvas:'+identity+':'+s.project+':'+row.id;let request=page==='creative-canvas'?recall(key):null;
    try{
      if(!session().actor)throw new Error('请先建立操作会话');
      let entry=null;
      // An unconfirmed create must reconcile its receipt before another empty-list decision.
      if(!request){entry=await ctx.api(endpoint(s.project,'production-platform/episode-entry?'+new URLSearchParams({episode_id:row.id})));if(!operation.current())return;
        if(entry.project_id!==s.project||entry.episode_id!==row.id)throw new Error('剧集范围已改变，请刷新当前项目');
        if(page==='creative-canvas'){
          if(entry.canvas!==null&&(!entry.canvas||typeof entry.canvas.id!=='string'||!entry.canvas.id))throw new Error('画布列表读取不完整，请重新读取当前剧集');
          if(entry.canvas===null){if(!writable())throw new Error('当前剧集没有可用画布，且没有创建权限');request={payload:{episode_id:row.id,title:'未命名画布',document:{nodes:[],edges:[]}},expected_revision:entry.revision,idempotency_key:uid()};remember(key,request);}
        }
      }
      const target={...options,episode:row.id};
      if(page==='creative-canvas'){
        if(request){
          if(!request.canvas_id){const result=await ctx.api(endpoint(s.project,'creative-canvases'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request.payload,expected_revision:request.expected_revision,idempotency_key:request.idempotency_key})});if(!result.id)throw new Error('画布回执缺少身份，请重试原操作');request.canvas_id=result.id;remember(key,request);if(!operation.current())return;}
          else{const saved=await ctx.api(endpoint(s.project,'creative-canvases/'+encodeURIComponent(request.canvas_id)));if(!operation.current())return;if(saved.id!==request.canvas_id||saved.episode_id!==row.id)throw new Error('画布不属于当前剧集，请重新读取');}
          target.task_target=request.canvas_id;
        }
        else target.task_target=entry.canvas.id;
      }
      await ctx.navigate(page,null,s.project,target);if(page==='creative-canvas')remember(key,null);
    }catch(error){
      if(request&&[400,404,409,422].includes(error.status)){remember(key,null);request=null;}
      if(operation.current())ctx.notice(error.message+(request?'；重试将恢复原画布请求。':''));
    }finally{if(episodeOpening===operation)episodeOpening=null;if(operation.current())for(const control of controls)control.disabled=false;}
  }
  async function episodes(t){
    const value=await read(endpoint(scope.project,'production-platform?'+new URLSearchParams({offset:String(offset),limit:'24'})),t);if(!value)return;if(value.project_id!==scope.project)throw new Error('项目范围已改变，请重新读取');data=value;ctx.setRevision(value.revision,scope.project);
    root.classList.add('platform-episodes');const heading=header(ctx.projectName()||msg('ui.project_episode_list'),msg('ui.manage_episodes_in_this_project_choose_an_episode_to'));heading.querySelector('h1').prepend(link(msg('project.all_projects'),'projects',null,null),el('span',' / ','episode-breadcrumb'));
    const toolbar=el('div',null,'episode-toolbar');toolbar.append(button(msg('workspace.project_members'),()=>ctx.navigateAccess?.({area:'members',project:scope.project})),button(msg('workspace.project_transfer'),()=>ctx.navigateAccess?.({area:'workspace',project:scope.project})));const more=el('details',null,'episode-project-tools'),projectTools=actions(link(msg('ui.project_assets_and_requirements'),'assets',null),link(msg('ui.project_tasks'),'tasks',null),link(msg('ui.sources_and_scripts'),'source',null));more.append(el('summary',msg('ui.project_tools')),projectTools);toolbar.append(more,el('span',msg('ui.value0_episodes',{value0:value.episodes.total}),'hint'));
    if(!value.read_only){
      projectTools.append(button(msg('ui.create_multiple_episodes'),()=>{const dialog=el('dialog',null,'platform-create'),form=episodeForm(value);form.open=true;bindAttribute(dialog,'aria-label',msg('ui.create_multiple_episodes'));dialog.append(el('h2',msg('ui.create_multiple_episodes')),form,button(msg('common.cancel'),()=>dialog.close()));root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();},!writable()));
      const create=button(msg('ui.create_episode'),()=>openEpisodeEditor(),!writable());create.className='primary';toolbar.append(create);
    }else toolbar.append(el('p',value.message,'hint'));root.append(toolbar);
    const grid=el('div',null,'project-grid episode-index');
    for(const row of value.episodes.items){
      const {tile:box,cover}=projectCover(row,row.title||row.display_code||row.id,()=>ctx.navigate('script',row.id,scope.project,{episode:row.id}));box.dataset.episodeId=row.id;
      const controls=el('div',null,'episode-actions');
      for(const [title,page,options]of [[msg('nav.canvas'),'creative-canvas',{}],[msg('nav.agent_workflow'),'intelligent-creation',{}],[msg('common.route_storyboard'),'classic-production',{kind:'image'}],[msg('common.route_video'),'classic-production',{kind:'video'}]]){
        const control=button(title,()=>openEpisodeTool(row,page,options),!session().actor||value.read_only);control.className='episode-tool';controls.append(control);
      }
      const frame=el('div',null,'episode-cover');cover.replaceWith(frame);frame.append(cover,controls);
      const footer=el('div',null,'episode-card-footer'),copy=el('div',null,'episode-card-copy'),title=box.querySelector('h3');copy.append(title,el('p',msg('ui.value0_storyboard_shots',{value0:row.shot_count??'—'}),'project-date'));footer.append(copy);
      const menu=el('details',null,'episode-card-menu'),summary=el('summary','⋯');bindAttribute(summary,'aria-label',msg('ui.episode_actions'));const menuItems=actions(link(msg('ui.production_progress'),'production',row.id),link(msg('nav.script'),'script',row.id,scope.project,{episode:row.id}));menu.append(summary,menuItems);
      if(!value.read_only){menuItems.prepend(button(msg('project.edit_episode'),()=>{menu.open=false;return openEpisodeEditor(row);},!writable()));for(const[title,direction]of [[msg('agent.overseas_remake_move_up'),'up'],[msg('agent.overseas_remake_move_down'),'down']])menuItems.append(button(title,async()=>{await write('episode-order',{episode_id:row.id,direction});if(same(t))await reload();},!writable()));}
      footer.append(menu);box.append(footer);grid.append(box);
    }
    if(!value.episodes.total)grid.append(empty(msg('ui.no_episodes_yet'),msg('ui.create_an_episode_or_import_a_script_to_start')));root.append(grid);if(value.episodes.total>24)root.append(pagination(value.episodes.total,value.episodes.next_offset,n=>load({...scope,offset:n})));
  }
  async function openEpisodeEditor(row=null){
    closeCreation?.();const s=scope,t=ticket,identity=homeIdentity(),key='vsc-episode-save:'+identity+':'+s.project+':'+(row?.id||'new'),draftKey=key+':draft';
    let request=recall(key),baseline=null,loading=false,saving=false,closed=false,readToken=0,initialized=false;const retained=recall(draftKey);
    const current=()=>same(t,s)&&identity===homeIdentity()&&!closed;
    const dialog=el('dialog',null,'platform-create project-create-dialog episode-edit-dialog'),form=el('form'),heading=el('header',null,'project-create-heading'),title=row?msg('project.edit_episode'):msg('project.create_episode');bindAttribute(dialog,'aria-label',title);heading.append(el('h2',title));const close=button('×',()=>dialog.close());close.className='project-create-close';bindAttribute(close,'aria-label',msg('common.close'));heading.append(close);
    const body=el('div',null,'project-create-body');
    const nameLabel=el('label',null,'project-create-field'),nameCaption=el('span',msg('ui.episode_name'));nameCaption.append(el('span','*','project-create-required'));const nameWrap=el('div',null,'project-name-input'),name=el('input'),counter=el('span','0 / 50','project-name-count');name.required=true;name.maxLength=50;bindAttribute(name,'aria-label',msg('ui.episode_name'));nameWrap.append(name,counter);nameLabel.append(nameCaption,nameWrap);body.append(nameLabel);
    const shots=el('input');shots.type='number';shots.required=true;shots.min='1';shots.max='500';shots.step='1';shots.value=String(Math.max(1,row?.shot_count||1));const shotField=field(body,msg('ui.storyboard_count'),shots);shotField.parentElement.className='project-create-field';
    const parent=el('select'),parentField=el('label',msg('ui.parent_work'),'project-create-field');bindAttribute(parent,'aria-label',msg('ui.parent_work'));parentField.append(parent);parentField.hidden=true;body.append(parentField);
    const position=el('input');position.type='text';position.inputMode='numeric';position.pattern='[0-9]*';bindAttribute(position,'aria-label',msg('ui.episode_position'));const positionField=field(body,msg('ui.episode_position'),position);positionField.parentElement.className='project-create-field';const positionHint=el('p',null,'episode-position-hint');positionField.parentElement.append(positionHint);
    const message=el('p',null,'hint project-create-status');message.setAttribute('role','status');const save=el('button',msg('common.confirm'));save.type='submit';save.className='project-create-confirm';const footer=el('footer',null,'project-create-footer');footer.append(button(msg('common.cancel'),()=>dialog.close()),save);form.append(heading,body,message,footer);dialog.append(form);root.append(dialog);
    const retain=()=>{if(!request)remember(draftKey,{title:name.value,shot_count:shots.value,parent_id:parent.value,position:position.value});};
    const lock=()=>{const frozen=loading||saving||Boolean(request)||!baseline;for(const control of [name,shots,parent,position])control.disabled=frozen;save.disabled=loading||saving||!writable();};
    const countName=()=>setText(counter,`${name.value.length} / 50`);name.addEventListener('input',countName);position.addEventListener('input',()=>{position.value=position.value.replace(/[^0-9]/g,'');});form.addEventListener('input',retain);form.addEventListener('change',retain);
    name.value=row?.title||'';if(retained){name.value=retained.title;shots.value=retained.shot_count;position.value=retained.position||'';}
    if(request){name.value=request.payload.title;shots.value=String(request.payload.shot_count);position.value=request.payload.position==null?'':String(request.payload.position);}
    async function readEditor(preserve=false){
      const token=++readToken;loading=true;lock();setText(message,msg('ui.loading'));
      const chosen=parent.value||request?.payload.parent_id||(!initialized?retained?.parent_id:null),params=new URLSearchParams(row?{episode_id:row.id}:chosen?{parent_id:chosen}:{});
      try{const value=await ctx.api(endpoint(s.project,'production-platform/episode-editor?'+params));if(!current()||token!==readToken)return;
        if(value.project_id!==s.project||row&&value.episode?.id!==row.id)throw new Error('剧集范围已改变，请重新读取');baseline=value;
        parent.replaceChildren(localizedOption('',msg('ui.default_parent_work')));for(const work of value.works||[])parent.append(localizedOption(work.id,work.title));parent.value=value.parent_id||'';parentField.hidden=Boolean(row)||(value.works||[]).length<=1;
        if(!initialized&&!preserve&&!retained&&!request){name.value=value.episode?.title||'';shots.value=String(Math.max(1,value.episode?.shot_count||1));}
        position.placeholder=value.episode?translate(msg('ui.episode_current_position',{position:value.episode.position})):'';setText(positionHint,msg('ui.episode_position_hint',{max:value.max_position}));initialized=true;countName();setText(message,request?.phase==='readback'?'剧集已保存，重试将刷新列表。':request?'原操作尚未确认，重试将恢复同一回执。':'');
      }catch(error){if(current()&&token===readToken){baseline=null;setText(message,error.message+'；点击确定重新读取，输入已保留。');}}
      finally{if(current()&&token===readToken){loading=false;lock();}}
    }
    parent.addEventListener('change',()=>{position.value='';retain();baseline=null;return readEditor(true);});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(!current()||loading||saving||!writable())return;if(!baseline&&!request){await readEditor(true);return;}saving=true;lock();
      try{
        if(!request){const title=name.value.trim(),count=Number(shots.value),place=position.value===''?null:Number(position.value);if(!title||name.value.length>50)throw new Error('剧集名称需为1至50字');if(!Number.isInteger(count)||count<1||count>500)throw new Error('分镜数需为1至500的整数');if(place!==null&&(!Number.isInteger(place)||place<1||place>baseline.max_position))throw new Error('排序位置不在当前所属部范围内');if(baseline.needs_parent)throw new Error('请先选择所属部');if(row&&count<baseline.episode.shot_count)throw new Error('减少分镜数需要明确选择要回收的镜头；当前编辑不会删除镜头');
          request={payload:{title,shot_count:count,...(row?{episode_id:row.id}:parent.value?{parent_id:parent.value}:{}),...(place===null?{}:{position:place})},expected_revision:baseline.revision,idempotency_key:uid(),phase:'write'};remember(key,request);lock();
        }
        if(request.phase!=='readback'){const saved=await ctx.api(endpoint(s.project,'episode-save'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request.payload,expected_revision:request.expected_revision,idempotency_key:request.idempotency_key})});if(!saved.episode_id)throw new Error('剧集回执缺少身份，请重试原操作');request.phase='readback';request.episode_id=saved.episode_id;request.episode_index=saved.episode_index;remember(key,request);if(!current())return;}
        await ctx.refreshProjects?.({isCurrent:current});if(!current())return;
        const nextOffset=Math.floor((request.episode_index||0)/24)*24;remember(key,null);remember(draftKey,null);ctx.notice(msg('ui.episode_saved'));dialog.close();await load({...s,offset:nextOffset});
      }catch(error){
        if(request?.phase!=='readback'&&[400,404,409,422].includes(error.status)){request=null;remember(key,null);retain();if(error.status===409||error.status===404)baseline=null;}
        if(current())setText(message,error.message+(request?.phase==='readback'?'；剧集已保存，重试只刷新列表。':request?'；重试将恢复原操作回执。':!baseline?'；点击确定重新读取后再保存。':''));
      }finally{if(current()){saving=false;lock();}else if(!closed)dialog.close();}
    });
    const closeThis=()=>dialog.close();closeCreation=closeThis;dialog.addEventListener('close',()=>{retain();closed=true;readToken++;if(closeCreation===closeThis)closeCreation=null;dialog.remove();},{once:true});countName();dialog.showModal();await readEditor();if(current())name.focus();
  }
  function episodeForm(value){
    const retained=recall(episodeDraft(scope.project))||{};const details=el('details',null,'platform-form');details.append(el('summary',msg("ui.create_multiple_episodes")));const form=el('form'),titles=el('textarea');titles.rows=4;bindAttribute(titles,"placeholder",msg("ui.episode_1_episode_2"));titles.value=retained.titles??drafts.get(scope.project)??'';field(form,msg("ui.episode_names_one_per_line_up_to_50"),titles);
    const parent=el('select');parent.append(localizedOption('',msg("ui.default_parent_work")));for(const row of value.episodes.works||[])parent.append(localizedOption(row.id,row.title));if((value.episodes.works||[]).length>1)field(form,msg("ui.parent_work"),parent);
    const initial=field(form,msg("ui.initial_storyboard_count_per_episode"),el('input'));initial.type='number';initial.min='0';initial.max='200';initial.value=retained.initial??'1';const position=field(form,msg("ui.insert_position"),el('select'));position.append(localizedOption('',msg("ui.place_last")));for(const row of value.episodes.items)position.append(localizedOption(row.id,msg("ui.before_value0",{value0:row.title||row.display_code})));
    parent.value=retained.parent||'';position.value=retained.position||'';const retain=()=>remember(episodeDraft(scope.project),{titles:titles.value,initial:initial.value,parent:parent.value,position:position.value});form.addEventListener('input',retain);form.addEventListener('change',retain);
    const preview=el('p',null,'hint');const show=()=>{drafts.set(scope.project,titles.value);retain();setText(preview,titles.value.split('\n').map(s=>s.trim()).filter(Boolean).map((s,i)=>`${i+1}. ${s}`).join(' · ')||msg("ui.enter_values_to_show_episode_names_in_this_batch"));};titles.addEventListener('input',show);show();form.append(preview);
    const save=el('button',msg("ui.create_these_episodes"));save.type='submit';save.disabled=!writable();form.append(save);const s=scope,t=ticket;
    form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{await write('episode-batches',{titles:titles.value.split('\n').map(s=>s.trim()).filter(Boolean),initial_shot_count:Number(initial.value),...(position.value?{insert_before_id:position.value}:{}),...(parent.value?{parent_id:parent.value}:{})});drafts.delete(s.project);remember(episodeDraft(s.project),null);if(same(t,s)){ctx.notice(msg("ui.episode_created"));await reload();}}catch(error){if(same(t,s)){ctx.notice(msg("ui.value0_inputs_are_preserved_reload_to_continue",{value0:error.message}));save.disabled=!writable();}}});details.append(form);return details;
  }
  async function production(t){
    if(!scope.object){await ctx.navigate('project',null,scope.project);return;}
    const value=await read(endpoint(scope.project,'production-platform?'+new URLSearchParams({episode_id:scope.object})),t);if(!value)return;data=value;ctx.setRevision(value.revision,scope.project);
    header(value.episode?.title||msg("ui.episode_production"),msg("ui.inputs_tasks_candidates_and_final_outputs_come_from_fixed"));root.append(actions(link(msg("ui.back_to_episode_list"),'project',null),link(msg("ui.episode_tasks"),'tasks'),button(msg("ui.refresh_this_episode"),reload)));
    if(value.read_only){root.append(el('p',value.message,'hint'),professional());return;}
    const quick=el('nav',null,'platform-quick');bindAttribute(quick,'aria-label',msg("ui.quick_five_view_setup"));quickViews.forEach(([page,name],i)=>quick.append(link(joinMessages(["",i+1," ",name,""]),page)));root.append(quick,professional());
    const stats=el('div',null,'platform-stats');for(const [title,count]of [[msg("ui.episode_shots"),value.shots.total],[msg("ui.episode_tasks"),value.jobs.total],[msg("ui.missing_asset_requirements"),value.requirements.unmet_count]])stats.append(empty(String(count),title));root.append(stats);
    const renders=value.renders.items.filter(r=>r.kind==='video');if(renders.length){const r=[...renders].sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)))[0],box=card(msg("ui.latest_playable_version"));const video=el('video');video.controls=true;video.preload='metadata';video.src=endpoint(scope.project,`media/${encodeURIComponent(r.media_id)}/content`);box.append(video,el('p',joinMessages(["",r.status==='current'?msg("ui.current_fixed_version"):msg("ui.historical_output_does_not_indicate_completion_of_the_current")," · ",r.created_at||'',""]),'hint'),link(msg("ui.view_delivery_and_checks"),'delivery'));root.append(box);}else root.append(empty(msg("ui.this_episode_has_no_playable_final_output"),msg("ui.images_and_generation_tasks_alone_are_not_a_complete")));
    const panel=card(msg("ui.shots_in_this_batch")),selected=new Set(),result=el('div',null,'platform-batch-result');
    panel.append(el('p',msg("ui.select_shots_to_check_once_inputs_are_ready_execute"),'hint'));
    let lastScene=null;for(const shot of value.shots.items){if(shot.scene_id!==lastScene){panel.append(el('h4',shot.scene_title||shot.scene_code||msg("ui.current_scene")));lastScene=shot.scene_id;}
      const row=el('div',null,'platform-shot'),choose=el('input');choose.type='checkbox';bindAttribute(choose,'aria-label',msg("ui.select_value0",{value0:shot.title}));choose.addEventListener('change',()=>choose.checked?selected.add(shot.id):selected.delete(shot.id));row.append(choose,link(shot.title||shot.display_code,'workbench',shot.id),el('span',msg("ui.value0_seconds_value1_roles_selected",{value0:(shot.duration_ms||0)/1000,value1:shot.selected_count}),'hint'),link(msg("ui.candidates_and_inputs"),'candidates',shot.id));panel.append(row);}
    const preview=button(msg("ui.preview_missing_inputs_for_selected_shots"),async()=>{const s=scope;preview.disabled=true;try{const res=await ctx.api(endpoint(s.project,'shot-batch/preview'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:{episode_id:s.object,shot_ids:[...selected],purpose:'video_clip'}})});if(!same(t,s))return;result.replaceChildren(el('h4',msg("ui.value0_value1_shots_have_ready_inputs",{value0:res.ready_count,value1:res.total})));for(const row of res.items){const box=card(row.title||row.shot_id);box.append(el('p',row.ready?msg("ui.inputs_are_ready_fix_the_run_plan_and_allowance"):msg("ui.missing_value0",{value0:row.gaps.map(gapText).join('、')})));box.append(link(msg("ui.locate_shot"),'workbench',row.shot_id));result.append(box);}}finally{if(same(t,s))preview.disabled=false;}},!value.shots.items.length);
    panel.append(preview,result);if(value.shots.truncated)panel.append(el('p',msg("ui.showing_value0_value1_shots_use_scene_and_shot_workbench",{value0:value.shots.items.length,value1:value.shots.total}),'hint'));panel.append(button(msg("ui.plan_the_first_production_pass_for_selected_shots"),()=>firstPlan(value,[...selected],t),!writable()||!value.shots.items.length));root.append(panel,batchPanel(value,t));
  }
  async function firstPlan(value,ids,t){
    if(!ids.length)throw new Error('请先选择本批镜头');
    const s=scope,[config,authorizations]=await Promise.all([read('/api/v1/resource-settings',t),read(endpoint(s.project,'execution-authorizations'),t)]);if(!config||!authorizations)return;
    const models=(config.configurations||[]).filter(row=>row.enabled&&row.modality==='video'&&row.adapter_available!==false);
    const dialog=el('dialog',null,'platform-plan');bindAttribute(dialog,'aria-label',msg("ui.first_production_plan"));const form=el('form');form.append(el('h2',msg("ui.first_production_plan_for_this_batch")),el('p',msg("ui.fix_the_selected_shots_existing_references_models_usage_and"),'hint'));
    const model=el('select');model.required=true;model.append(localizedOption('',msg("ui.select_an_actually_available_model")));for(const row of models)model.append(localizedOption(row.id,joinMessages(["",row.name||row.model_key," · ",row.model_version,""])));field(form,msg("ui.model_and_configuration_version"),model);
    const purpose=field(form,msg("ui.purpose"),el('select'));const fillPurposes=()=>{purpose.replaceChildren();for(const code of models.find(row=>row.id===model.value)?.capabilities?.purposes||[])purpose.append(localizedOption(code,label[code]||code));if([...purpose.options].some(o=>o.value==='video_clip'))purpose.value='video_clip';};model.addEventListener('change',fillPurposes);
    const shotInputs=[];for(const shot of value.shots.items.filter(r=>ids.includes(r.id))){const section=card(shot.title),prompt=el('textarea');prompt.rows=3;prompt.required=true;field(section,msg("ui.visual_action_and_audio_requirements_for_this_shot"),prompt);const duration=el('input');duration.type='number';duration.min='1';duration.step='1';duration.required=true;duration.value=String(Math.max(1,Math.round((shot.duration_ms||5000)/1000)));field(section,msg("ui.video_duration_seconds"),duration);form.append(section);shotInputs.push({shot_id:shot.id,prompt,duration});}
    const parameters=el('textarea');parameters.rows=2;parameters.value='{}';field(form,msg("ui.shared_model_parameters_json_selected_shots_only"),parameters);
    const billing=el('select');bindAttribute(billing,'aria-label',msg("ui.production_credit_account"));if(session().actor)billing.append(localizedOption(session().actor,msg("ui.my_allowance_value0",{value0:session().actor})));billing.append(localizedOption('',msg("ui.shared_project_budget")));field(form,msg("ui.production_credit_account"),billing);
    const authorization=el('select');bindAttribute(authorization,'aria-label',msg("ui.production_authorization_scope"));authorization.append(localizedOption('',msg("ui.retain_existing_production_limits")),localizedOption('new_batch',msg("ui.new_batch_approve_new_deadlines_and_attempt_limits")));
    for(const row of authorizations.items)authorization.append(localizedOption(row.id,msg("ui.continue_batch_value0",{value0:row.reason})));field(form,msg("ui.production_authorization_scope"),authorization);
    const reason=field(form,msg("ui.reason_for_the_new_batch"),el('input'));reason.maxLength=2000;reason.disabled=true;authorization.addEventListener('change',()=>{reason.disabled=authorization.value!=='new_batch';reason.required=!reason.disabled;});
    form.append(el('p',msg("ui.recovery_and_continuation_retain_the_original_attempt_limits_and"),'hint'));
    const localTime=minutes=>{const d=new Date(Date.now()+minutes*60000);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,16);};
    const due=el('input');due.type='datetime-local';due.value=localTime(45);due.required=true;field(form,msg("ui.first_draft_target_time"),due);const stop=el('input');stop.type='datetime-local';stop.value=localTime(60);stop.required=true;field(form,msg("ui.stop_submitting_new_generations_at"),stop);const attempts=el('input');attempts.type='number';attempts.min='1';attempts.max='20';attempts.value='2';field(form,msg("ui.maximum_attempts_per_object_and_purpose"),attempts);
    const report=el('div',null,'platform-plan-report');let preview=null,request=null,loading=false,formVersion=0;
    const save=button(msg("ui.save_plan_for_review"),async()=>{if(!preview||!request)throw new Error('请先预览当前方案');save.disabled=true;try{const result=await write('first-production/proposals',{request,preview_sha256:preview.preview_sha256});if(!same(t,s))return;dialog.close();await ctx.artifact(result.id);}catch(e){if(same(t,s))save.disabled=false;throw e;}},true);
    const check=el('button',msg("ui.preview_inputs_and_usage"));check.type='submit';check.disabled=!models.length;form.append(actions(check,save,button(msg("common.cancel"),()=>dialog.close())),report);
    form.addEventListener('input',()=>{formVersion++;preview=null;save.disabled=true;});form.addEventListener('change',()=>{formVersion++;preview=null;save.disabled=true;});
    form.addEventListener('submit',async e=>{e.preventDefault();if(loading)return;loading=true;const submittedVersion=formVersion;check.disabled=true;save.disabled=true;try{const params=JSON.parse(parameters.value);request={episode_id:s.object,model_id:model.value,purpose:purpose.value,shots:shotInputs.map(row=>({shot_id:row.shot_id,prompt:row.prompt.value.trim(),duration_ms:Number(row.duration.value)*1000,params})),execution_policy:{version:'bounded-v1',first_draft_due_at:new Date(due.value).toISOString(),stop_submitting_at:new Date(stop.value).toISOString(),max_attempts_per_purpose:Number(attempts.value),max_repair_rounds:1}};
      request.commerce_account_actor=billing.value||null;
      if(authorization.value==='new_batch')request.execution_policy.authorization={mode:'new_batch',reason:reason.value.trim()};else if(authorization.value){const original=authorizations.items.find(row=>row.id===authorization.value);request.execution_policy.authorization={mode:'continue',run_version_id:original.id,sha256:original.sha256};}
      const response=await ctx.api(endpoint(s.project,'first-production/preview'),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({payload:request})});if(!same(t,s))return;if(submittedVersion!==formVersion){report.replaceChildren(el('p',msg("ui.inputs_have_changed_preview_the_current_plan_again"),'hint'));return;}preview=response;ctx.setRevision(response.revision,s.project);const q=response.generation_quote;report.replaceChildren(el('h3',msg("ui.fixed_usage_for_this_batch")),el('p',Object.entries(q.native_units||{}).map(([unit,count])=>`${label[unit]||unit} ${count}`).join(' · ')),el('p',q.all_prices_known?msg("ui.estimate_value0",{value0:Object.entries(q.known_subtotals||{}).map(([unit,count])=>`${count} ${unit}`).join('；')}):msg("ui.prices_are_unknown_for_value0_items_unknown_does_not",{value0:q.unknown_jobs}),'hint'),el('p',msg("ui.the_selected_inputs_and_model_quote_are_fixed_save"),'hint'));if(response.commerce_quote?.enabled){const charge=response.commerce_quote.commerce_charge;report.append(el('p',msg("ui.commercial_allowance_cap_value0_paying_account_value1",{value0:Object.values(charge.max_credits_by_operation).reduce((a,b)=>a+b,0),value1:charge.account_actor||msg("ui.shared_project_budget")})));}save.disabled=false;
    }catch(error){if(same(t,s))report.replaceChildren(el('p',error.message,'hint'));}finally{loading=false;if(same(t,s))check.disabled=false;}});
    if(!models.length)report.append(el('p',msg("ui.no_connected_enabled_video_model_is_available_configure_an"),'hint'));dialog.append(form);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  }
  function batchPanel(value,t){
    const box=card(msg("ui.execute_an_approved_production_batch")),select=el('select');bindAttribute(select,'aria-label',msg("ui.fixed_run_plan"));select.append(localizedOption('',msg("ui.select_run_plan")));
    for(const row of value.versions.items.filter(r=>['production-run','vsc.production_run'].includes(r.kind)||['production-run','vsc.production_run'].includes(r.artifact_type)))select.append(localizedOption(row.id,row.title||row.id));
    const report=el('div'),start=button(msg("ui.start_ready_tasks_in_this_batch"),async()=>{if(!manifest)throw new Error('请先预览本批');const s=scope;start.disabled=true;try{const res=await write('production-batch/execute',{run_version_id:manifest.run_version_id,run_sha256:manifest.run_sha256});if(!same(t,s))return;ctx.notice(msg("ui.processed_within_the_fixed_run_scope_view_each_item"));report.replaceChildren(el('pre',text(res)));}finally{if(same(t,s))start.disabled=false;}},true);let manifest=null;
    const preview=button(msg("ui.preview_this_production_batch"),async()=>{if(!select.value)throw new Error('请选择已批准的运行方案');const s=scope;const res=await ctx.api(endpoint(s.project,'production-batch/preview'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:{run_version_id:select.value}})});if(!same(t,s))return;manifest=res;report.replaceChildren(el('p',msg("ui.ready_value0_waiting_value1_blocked_value2",{value0:res.ready_count??0,value1:res.waiting_count??0,value2:res.blocked_count??0})));for(const task of res.tasks||[])report.append(el('p',joinMessages(["",task.task_key," · ",label[task.status]||task.status,"",task.gaps?.length?joinMessages([" · ",task.gaps.map(gapText).join('、')]):'',""])));start.disabled=!writable()||!res.ready_count;});
    select.addEventListener('change',()=>{manifest=null;start.disabled=true;report.replaceChildren();});box.append(select,actions(preview,start,link(msg("ui.view_plan_and_approval"),'artifacts')),report);if(select.options.length===1)box.append(el('p',msg("ui.no_fixed_run_plan_exists_record_inputs_routes_attempts"),'hint'));return box;
  }
  async function assets(t){
    const s=scope;root.classList.add('platform-assets');
    const host=el('section');root.append(host);assetCards=await mountAssetCards(host,ctx,{projectId:s.project,objectId:s.object,isCurrent:()=>same(t,s)});
  }
  async function demandPanel(t){
    const s=scope,box=card(msg("ui.summarize_actual_usage_in_this_batch")),report=el('div',null,'platform-demand-report');root.append(box);
    const episodes=await read(endpoint(s.project,'production-platform?limit=100'),t);if(!episodes)return;
    if(episodes.read_only){box.append(el('p',msg("ui.requirements_from_the_legacy_project_remain_read_only_read")));return;}
    const selected=new Set(),picker=el('details');picker.open=!s.object;picker.append(el('summary',msg("ui.select_episodes_for_this_batch")));
    for(const row of episodes.episodes.items){const label=el('label',null,'platform-demand-episode'),check=el('input');check.type='checkbox';check.checked=s.object===row.id;if(check.checked)selected.add(row.id);check.addEventListener('change',()=>{check.checked?selected.add(row.id):selected.delete(row.id);request++;preview.disabled=false;report.replaceChildren(el('p',msg("ui.the_episode_scope_has_changed_summarize_it_again"),'hint'));});label.append(check,el('span',row.title||row.display_code||row.id));picker.append(label);}box.append(picker);
    if(episodes.episodes.next_offset!=null)box.append(el('p',msg("ui.the_first_100_episodes_are_selectable_here_for_later"),'hint'));
    let request=0;const run=async()=>{const turn=++request;preview.disabled=true;try{const value=await ctx.api(endpoint(s.project,'production-requirements/preview'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:{episode_ids:[...selected],purpose:'video_clip'}})});if(!same(t,s)||turn!==request)return;ctx.setRevision(value.revision,s.project);report.replaceChildren(el('p',msg("ui.value0_value1_shots_have_ready_inputs_value2_required_references",{value0:value.shot_readiness.filter(row=>row.ready).length,value1:value.shot_readiness.length,value2:value.asset_tasks.length,value3:value.future_count})));
      const names={reuse:'已有可复用引用',variant:'固定变体',new_identity:'身份尚待明确',needs_reference:'需要补齐参考',conflict:'身份或规格冲突'};
      for(const [code,name]of Object.entries(names)){const rows=value.groups.filter(row=>row.classification===code),group=el('section',null,'platform-demand-group');group.append(el('h4',joinMessages([name," · ",rows.length])));for(const row of rows){const item=el('article',null,'platform-requirement');item.append(el('h5',row.title||row.asset_id||msg("ui.requirement_unspecified")),el('p',msg("ui.used_by_value0_shots_in_this_batch_value1_value2",{value0:row.consumer_shot_ids.length,value1:row.purpose,value2:row.variant_key||msg("ui.variant_not_fixed")}),'hint'));for(const gap of row.gaps||[])item.append(el('p',gapText(gap)));for(const media of row.selected_media||[])if(media.media_id)item.append(button(msg("ui.review_selected_media"),()=>ctx.media(media.media_id)));for(const ref of row.source_refs||[])item.append(button(msg("ui.view_fixed_source"),()=>ctx.artifact(ref.id)));if(row.consumer_shot_ids.length)item.append(link(msg("ui.locate_actual_consumers"),'designs',row.consumer_shot_ids[0]));group.append(item);}report.append(group);}
      if(value.asset_tasks.length){const pending=el('details');pending.append(el('summary',msg("ui.required_reference_task_candidates_not_queued")));for(const task of value.asset_tasks)pending.append(el('p',joinMessages(["",task.asset_id," · ",task.variant_key||msg("ui.variant_not_fixed")," · ",task.purpose," · ",task.execution_available?msg("ui.reference_task_inputs_available"):msg("ui.prerequisite_gaps_remain"),""])));report.append(pending);}report.append(el('p',msg("ui.future_requirements_are_excluded_from_this_batch_this_query"),'hint'));
    }catch(error){if(same(t,s)&&turn===request)report.replaceChildren(el('p',error.message));}finally{if(same(t,s)&&turn===request)preview.disabled=false;}};
    const preview=button(msg("ui.summarize_selected_episode_requirements"),run);box.append(preview,report);if(selected.size)await run();
  }
  async function tasks(t){
    const s=scope;header(msg("ui.production_tasks_and_usage"),msg("ui.unclaimed_remote_in_transit_failed_and_completed_tasks_are"));root.append(actions(link(msg("ui.back_to_this_episode"),s.object?'production':'project'),button(msg("ui.refresh_tasks"),reload),link(msg("ui.models_and_default_purposes"),'settings')));
    if(s.taskId&&s.taskKind){const value=await read(endpoint(s.project,'task-center/'+encodeURIComponent(s.taskKind)+'/'+encodeURIComponent(s.taskId)),t);if(!value)return;const row=value.task,focus=card(msg("ui.located_original_task_value0",{value0:row.title}));focus.classList.add('platform-task-focus');focus.dataset.taskId=row.id;focus.append(el('p',label[row.status]||({completed:'已完成',needs_input:'待补充输入',result_ready:'结果待确认',planned:'方案待确认',stopped:'已停止'}[row.status])||row.status));if(row.error)focus.append(el('p',row.error));if(row.progress){const v=row.progress;focus.append(el('p',msg("ui.batch_terminal_items_value0_value1_succeeded_value2_failed_value3",{value0:v.terminal,value1:v.total,value2:v.completed,value3:v.failed,value4:v.blocked,value5:v.skipped})));}const recover=el('a',msg("ui.open_the_working_draft_that_owns_this_task"));recover.href=row.href;focus.append(recover);if(row.kind==='generation')focus.append(button(msg("ui.view_this_task_s_fixed_record_and_outputs"),()=>jobDetail(row,t)));if(row.remote_cancel){const cancel=button(msg("ui.cancel_remote_task"),()=>{});cancel.disabled=true;cancel.title=row.remote_cancel.reason;focus.append(cancel,el('p',row.remote_cancel.reason,'hint'));}root.append(focus);}
    const params=new URLSearchParams({limit:'24',offset:String(offset)});
    if(s.taskKind)params.set('kind',s.taskKind);if(s.taskStatus)params.set('status',s.taskStatus);if(s.episode)params.set('episode_id',s.episode);
    const values=await Promise.all([ctx.api(endpoint(s.project,'task-center?'+params)),ctx.api('/api/v1/execution'),ctx.api(endpoint(s.project,'production-platform/budget')).catch(e=>({error:e.message}))]);if(!same(t,s))return;const [jobs,runtime,budget]=values;ctx.setRevision(jobs.revision,s.project);
    const generation=runtime.generation||{};root.append(el('p',generation.available?generation.accepting_submissions?msg("ui.the_worker_can_claim_authorized_tasks_remote_tasks_remain"):msg("ui.new_submissions_stopped_submitted_results_remain_tracked"):msg("ui.no_generation_worker_is_available_waiting_tasks_are_not"),'hint'));
    if(session().actor&&runtime.enabled&&generation.available)root.append(button(generation.accepting_submissions?msg("ui.pause_new_submissions"):msg("ui.continue_processing"),async()=>{await ctx.api('/api/v1/execution',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session().csrf},body:JSON.stringify({action:generation.accepting_submissions?'pause':'resume'})});if(same(t,s))await reload();}));
    const taskKinds={intelligent:'智能制作',generation:'媒体生成',editing:'首版合成',spatial:'空间导出',spatial_plan:'空间规划',lyrics:'歌词创作',import:'素材导入',text:'剧本与分析工具',text_batch:'文字工具批次',canvas:'画布助手'},taskStates={completed:'已完成',awaiting_upload:'等待续传',uploaded:'已上传，待登记',result_ready:'规划结果待登记',needs_input:'待补充输入',planned:'待确认方案',applied:'已应用方案',rejected:'已拒绝',stopped:'已停止'};
    root.append(el('p',msg("ui.shows_generation_composition_imports_spatial_exports_text_tools_and"),'hint'));
    const filters=el('form'),kind=field(filters,msg("task.task_type"),el('select')),status=field(filters,msg("ui.task_status"),el('select'));kind.append(localizedOption('',msg("ui.all_types")));for(const [value,title]of Object.entries(taskKinds))kind.append(localizedOption(value,title));kind.value=s.taskKind||'';status.append(localizedOption('',msg("asset.all_status")));for(const value of ['created','queued','submitted','running','submission_unknown','succeeded','failed','cancelled',...Object.keys(taskStates)])status.append(localizedOption(value,label[value]||taskStates[value]));status.value=s.taskStatus||'';const filter=el('button',msg("ui.filter_tasks"));filter.type='submit';filters.append(filter);filters.addEventListener('submit',e=>{e.preventDefault();load({...s,offset:0,taskKind:kind.value,taskStatus:status.value});});root.append(filters);
    const grid=el('div',null,'platform-grid');for(const row of jobs.items){const box=card(label[row.title]||row.title);box.append(el('p',joinMessages([taskKinds[row.kind]||row.kind," · ",label[row.status]||taskStates[row.status]||row.status])),el('p',row.created_at||'','hint'));if(row.error)box.append(el('p',row.error,'hint'));if(row.progress){const progress=el('progress');progress.max=row.progress.total||1;progress.value=row.progress.terminal||0;bindAttribute(progress,'aria-label',msg("ui.terminal_batch_items"));box.append(progress,el('p',msg("ui.terminal_value0_value1_succeeded_value2_failed_value3_blocked_value4",{value0:row.progress.terminal,value1:row.progress.total,value2:row.progress.completed,value3:row.progress.failed,value4:row.progress.blocked,value5:row.progress.skipped,value6:row.progress.pending,value7:row.progress.running})));const children=el('details');children.append(el('summary',msg("ui.view_batch_subtasks")));const states={pending:'等待',running:'执行中',completed:'已完成',failed:'失败',blocked:'受阻',skipped:'跳过'};for(const child of row.children||[]){const item=el('div',null,'platform-task-child');item.append(el('p',joinMessages([child.title||msg("ui.child_task_value0",{value0:child.ordinal+1})," · ",states[child.status]||child.status])));if(child.error_code)item.append(el('p',msg("ui.reason_value0",{value0:child.error_code}),'hint'));if(child.href){const locate=el('a',child.output_version_id?msg("ui.view_fixed_result"):msg("ui.locate_and_recover"));locate.href=child.href;item.append(locate);}children.append(item);}if(row.children_truncated)children.append(el('p',msg("ui.the_first_50_items_are_shown_open_the_original"),'hint'));box.append(children);}if(row.kind==='generation')box.append(button(msg("ui.view_records_and_outputs"),()=>jobDetail(row,t)));const destination=el('a',msg("ui.locate_and_recover"));destination.href=row.href;box.append(destination);grid.append(box);}if(!jobs.total)grid.append(empty(msg("ui.no_tasks_match_the_current_filters"),msg("ui.adjust_filters_or_check_accepted_tasks_and_results_after")));root.append(grid,pagination(jobs.total,jobs.next_offset,n=>load({...scope,offset:n})));
    const usage=card(msg("ui.native_usage"));if(budget.error)usage.append(el('p',msg("ui.usage_could_not_be_loaded_value0",{value0:budget.error})));else{const units=new Set([...Object.keys(budget.limits||{}),...Object.keys(budget.used||{})]);for(const unit of units)usage.append(el('p',msg("ui.value0_reserved_used_value1_cap_value2_remaining_value3",{value0:label[unit]||unit,value1:budget.used?.[unit]??0,value2:budget.limits?.[unit]??msg("ui.not_set"),value3:budget.remaining?.[unit]??msg("agent.overseas_remake_dialogue_type_unknown")})));if(!units.size)usage.append(el('p',msg("ui.no_budget_records_yet")));usage.append(el('p',msg("ui.unknown_cost_is_not_zero_usage_is_shown_separately"),'hint'));if(writable()){const form=el('form'),details=el('details'),key='budget:'+s.project,retained=drafts.get(key)||{},fields={};details.append(el('summary',msg("ui.set_project_native_usage_limits")));for(const unit of ['remote_jobs','images','video_seconds','audio_jobs','speech_chars','vision_jobs']){const control=el('input');control.type='number';control.min=String(budget.used?.[unit]||0);control.step='1';control.value=retained[unit]??budget.limits?.[unit]??'';fields[unit]=control;field(form,label[unit]||unit,control);}const reason=field(form,msg("ui.reason_for_setting_or_changing_limits"),el('input'));reason.required=true;reason.value=retained.reason||'';form.addEventListener('input',()=>drafts.set(key,{...Object.fromEntries(Object.entries(fields).map(([u,n])=>[u,n.value])),reason:reason.value}));const save=el('button',msg("ui.save_usage_limits"));save.type='submit';form.append(save);form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{await write('production-budgets',{limits:Object.fromEntries(Object.entries(fields).filter(([,n])=>n.value!=='').map(([u,n])=>[u,Number(n.value)])),reason:reason.value.trim()});drafts.delete(key);if(same(t,s)){ctx.notice(msg("ui.usage_cap_saved"));await reload();}}catch(error){if(same(t,s)){ctx.notice(error.message);save.disabled=false;}}});details.append(form);usage.append(details);}}root.append(usage);
    poll=setTimeout(()=>{if(same(t,s)&&!document.hidden&&!busy&&!drafts.has('budget:'+s.project))reload().catch(e=>ctx.notice(e.message));},15000);
  }
  async function jobDetail(row,t){const s=scope,value=await read(endpoint(s.project,`production-platform/jobs/${encodeURIComponent(row.id)}`),t);if(!value)return;const dialog=el('dialog');bindAttribute(dialog,'aria-label',msg("ui.task_records"));dialog.append(el('h2',label[value.purpose]||value.purpose),el('p',label[value.status]||value.status),el('p',msg("ui.candidates_value0_attempts_value1",{value0:value.candidate_no??0,value1:value.attempt??0}),'hint'));const usage=value.usage,quote=usage?.quote,actual=usage?.reconciliation;
    if(value.elapsed_ms!=null)dialog.append(el('p',msg("ui.value0_seconds_from_creation_to_latest_status_update",{value0:(value.elapsed_ms/1000).toFixed(1)}),'hint'));
    if(quote){const table=el('table'),head=el('tr');for(const title of [msg("ui.measurement_unit"),msg("ui.submitted_quote"),msg("ui.settled_usage"),msg("ui.difference")])head.append(el('th',title));table.append(head);for(const unit of new Set([...Object.keys(quote.native_units||{}),...Object.keys(actual?.actual_units||{})])){const tr=el('tr');for(const cell of [label[unit]||unit,quote.native_units?.[unit]??'—',actual?.actual_units?.[unit]??'待结算',actual?.native_delta?.[unit]??'—'])tr.append(el('td',String(cell)));table.append(tr);}dialog.append(table,el('p',msg("ui.quoted_amount_value0",{value0:quote.amount==null?msg("agent.overseas_remake_dialogue_type_unknown"):joinMessages([quote.amount," ",quote.currency])})),el('p',msg("ui.actual_bill_value0",{value0:actual?.actual_amount==null?msg("ui.not_registered"):joinMessages([actual.actual_amount," ",actual.actual_currency])})));if(actual?.actual_cost_evidence)dialog.append(el('p',actual.actual_cost_evidence,'hint'));}
    for(const output of value.outputs||[])dialog.append(button(msg("ui.review_outputs"),()=>ctx.media(output.media_id)));for(const event of value.events||[])dialog.append(el('p',joinMessages(["",event.created_at||''," · ",event.event_type,""]),'hint'));dialog.append(button(msg("common.close"),()=>dialog.close()));root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();}
  async function settings(t){header(msg("ui.settings_and_maintenance"),msg("ui.configuration_applies_to_future_tasks_fixed_tasks_retain_original"));root.append(actions(button(msg("ui.models_default_purposes_and_updates"),ctx.settings),button(msg("ui.role_memory"),ctx.memory),button(msg("settings.local_management_credential"),ctx.account),link(msg("ui.runtime_and_connection_diagnostics"),'maintenance'),link(msg("common.route_recycle_bin"),'trash')));const value=await read('/api/v1/resource-settings',t);if(!value)return;const grid=el('div',null,'platform-grid');for(const row of value.configurations||[]){const box=card(row.name||row.model_key);box.append(el('p',joinMessages(["",row.model_key," · ",row.model_version,""]),'hint'),el('p',joinMessages(["",row.enabled?msg("common.enabled"):msg("ui.disabled")," · ",typeof row.connection_status==='object'?(row.connection_status.message||row.connection_status.status):row.connection_status||msg("ui.not_verified_online_yet"),""])),button(msg("ui.view_and_edit_configuration"),ctx.settings));grid.append(box);}if(!value.configurations?.length)grid.append(empty(msg("ui.no_model_configurations"),msg("ui.open_models_default_purposes_and_updates_to_configure_routes")));root.append(grid);}
  async function maintenance(t){header(msg("ui.workspace_maintenance"),msg("ui.service_status_and_connection_settings_come_from_the_local"));root.append(actions(link(msg("ui.back_to_project"),'projects',null),link(msg("ui.models_and_settings"),'settings'),button(msg("ui.refresh_diagnostics"),reload)));const values=await Promise.all([ctx.api('/api/v1/execution'),ctx.api('/api/v1/resource-settings')]);if(!same(t))return;const [execution,settings]=values;const diagnostic={execution,configuration_available:settings.available!==false,configuration_count:settings.configurations?.length||0};root.append(el('p',execution.message,'hint'),el('pre',text(diagnostic),'platform-diagnostic'));root.append(button(msg("ui.download_redacted_diagnostics"),()=>{const blob=new Blob([JSON.stringify(diagnostic,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='vsc-diagnostic.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));}
  async function load(options){closeCreation?.();assetCards?.suspend();assetCards=null;canvasLibrary?.suspend();canvasLibrary=null;mediaLibrary?.suspend();mediaLibrary=null;clearTimeout(poll);poll=null;ticket++;const t=ticket;scope={...options};offset=options.offset||0;busy=false;data=null;root.replaceChildren(el('p',msg("ui.loading"),'hint'));root.setAttribute('aria-busy','true');try{root.replaceChildren();root.classList.remove('platform-home','platform-projects','platform-episodes','platform-assets','platform-media');if(scope.page==='home')await home(t);else if(scope.page==='projects')await projects(t);else if(scope.page==='settings')await settings(t);else if(scope.page==='maintenance')await maintenance(t);else if(!scope.project)root.append(empty(msg("ui.select_a_project_first_dynamic_76"),msg("ui.create_or_open_a_project_from_the_project_list")));else if(scope.page==='project')await episodes(t);else if(scope.page==='production')await production(t);else if(scope.page==='assets')await assets(t);else if(scope.page==='tasks')await tasks(t);if(options.create==='canvas'){if(typeof window!=='undefined'){const q=new URLSearchParams(window.location.search);q.delete('create');window.history.replaceState(null,'','?'+q);}createProject('canvas');}}catch(error){if(same(t)){root.append(empty(msg("ui.loading_incomplete"),error.message),button(msg("ui.reload"),reload));ctx.notice(error.message);}}finally{if(same(t))root.removeAttribute('aria-busy');}}
  return {load,suspend(){closeCreation?.();assetCards?.suspend();canvasLibrary?.suspend();canvasLibrary=null;mediaLibrary?.suspend();mediaLibrary=null;ticket++;clearTimeout(poll);poll=null;}};
}
