"""Read-only aggregation; each original domain continues to own recovery."""
from sqlalchemy import select,func,literal,case,cast,Text,text,or_,false
from sqlalchemy.dialects.postgresql import JSONB,aggregate_order_by
from urllib.parse import urlencode
from . import schema as S
from .values import clean,checked_id
from vsc.assets.resource_service import ResourceError

GROUPS = ('attention', 'running', 'result', 'ended', 'unknown')
ORIGIN_LABELS = {'generation':'媒体生成', 'editing':'首版合成', 'spatial':'空间预演导出',
    'spatial_plan':'空间规划', 'lyrics':'歌词创作', 'import':'媒体导入', 'text':'文本工具',
    'text_batch':'文本批次', 'canvas':'画布助手', 'intelligent':'智能制作'}


def task_group(table):
    """Display groups classify original facts; they never become a task state."""
    return case((table.c.status.in_(('submission_unknown', 'unknown')), 'unknown'),
        ((table.c.status!='stopped') & (table.c.problem_count > 0), 'attention'),
        (table.c.status.in_(('failed', 'needs_input', 'planned', 'awaiting_upload', 'blocked')), 'attention'),
        (table.c.status.in_(('created', 'ready', 'queued', 'pending', 'running', 'submitted', 'polling',
                            'uploaded', 'result_ready', 'cancel_requested')), 'running'),
        (table.c.status.in_(('applied', 'cancelled', 'rejected', 'stopped', 'skipped')), 'ended'),
        (table.c.status.in_(('succeeded','completed')) & (table.c.result_count > 0), 'result'),
        else_='unknown')


def task_sources(project_id,episode_id=None):
    sources=[]
    shots,sequences,scenes=S.shots,S.sequences,S.scenes
    shot_ids=select(shots.c.id).join(sequences,(sequences.c.project_id==shots.c.project_id)&(sequences.c.id==shots.c.parent_id)).join(
        scenes,(scenes.c.project_id==sequences.c.project_id)&(scenes.c.id==sequences.c.parent_id)).where(shots.c.project_id==project_id,scenes.c.parent_id==episode_id)
    forms,versions,assets=S.episode_asset_forms,S.episode_asset_form_versions,S.episode_assets
    form_assets=select(versions.c.source_asset_id).join(forms,(forms.c.project_id==versions.c.project_id)&(forms.c.id==versions.c.form_id)).join(
        assets,(assets.c.project_id==forms.c.project_id)&(assets.c.id==forms.c.episode_asset_id)).where(versions.c.project_id==project_id,assets.c.episode_id==episode_id,versions.c.source_asset_id.is_not(None))
    uses=S.asset_use_instances
    used_assets=select(uses.c.asset_id).join(scenes,(scenes.c.project_id==uses.c.project_id)&(scenes.c.id==uses.c.scene_id)).where(uses.c.project_id==project_id,scenes.c.parent_id==episode_id)
    asset_ids=form_assets.union(used_assets)
    def object_name(identifier,fallback):
        obj=S.creative_objects
        name=select(func.coalesce(func.nullif(obj.c.title,''),obj.c.display_code)).where(obj.c.project_id==project_id,obj.c.id==identifier).scalar_subquery()
        return func.coalesce(name,literal(fallback))
    def source(code,table,title,page,target=None,error=None,joins=(),scope=None,tool=None,token_parts=(),belongs=None,outer_joins=(),node=None):
        problem_count = literal(0)
        if code == 'generation':
            result_count = select(func.count()).where(S.job_outputs.c.project_id==project_id,
                S.job_outputs.c.job_id==table.c.id).scalar_subquery()
        elif code == 'spatial':
            result_count = select(func.count()).where(S.spatial_export_outputs.c.project_id==project_id,
                S.spatial_export_outputs.c.export_id==table.c.id).scalar_subquery()
        elif code == 'text_batch':
            result_count = select(func.count()).select_from(S.text_tool_batch_items.outerjoin(S.text_tool_attempts,
                (S.text_tool_attempts.c.project_id==S.text_tool_batch_items.c.project_id)&
                (S.text_tool_attempts.c.id==S.text_tool_batch_items.c.attempt_id))).where(S.text_tool_batch_items.c.project_id==project_id,
                S.text_tool_batch_items.c.batch_id==table.c.id,
                or_(S.text_tool_batch_items.c.output_version_id.is_not(None),
                    S.text_tool_attempts.c.result_version_id.is_not(None))).scalar_subquery()
            problem_count = select(func.count()).where(S.text_tool_batch_items.c.project_id==project_id,
                S.text_tool_batch_items.c.batch_id==table.c.id,
                S.text_tool_batch_items.c.status.in_(('failed','blocked'))).scalar_subquery()
        else:
            result_field = {'editing':'output_blob_id','import':'media_id','text':'result_version_id',
                'spatial_plan':'plan_artifact_id','canvas':'plan_artifact_id','intelligent':'plan_artifact_id'}[code]
            result_count = case((table.c[result_field].is_not(None),1),else_=0)
        parts=[table.c.status]+[table.c[name] for name in ('attempt','result_version_id','output_version_id','plan_artifact_id','output_sha256','media_id','error','error_code') if name in table.c]+list(token_parts)
        token=func.encode(func.sha256(func.convert_to(func.concat_ws('|',*[func.coalesce(cast(value,Text),'') for value in parts]),'UTF8')),'hex')
        query=select(table.c.id,table.c.status,table.c.created_at,title.label("title"),literal(code).label("kind"),
            (literal(page) if isinstance(page,str) else page).label("page"),(target if target is not None else table.c.id).label("target_id"),
            (error if error is not None else literal(None)).label("error"),(scope if scope is not None else literal(None)).label('scope_id'),
            (tool if tool is not None else literal(None)).label('tool_id'),
            (node if node is not None else literal(None)).label('focus_node_key'),token.label('source_token'),
            result_count.label('result_count'), problem_count.label('problem_count')).select_from(table)
        for joined,on in joins:query=query.join(joined,on)
        for joined,on in outer_joins:query=query.outerjoin(joined,on)
        query=query.where(table.c.project_id==project_id)
        if episode_id is not None:query=query.where(belongs if belongs is not None else false())
        sources.append((code,query))
    j=S.generation_jobs
    ar,iv,iw=S.intelligent_asset_runs,S.intelligent_versions,S.intelligent_workflows
    asset_run=select(ar.c.run_artifact_id).join(iv,(iv.c.project_id==ar.c.project_id)&(iv.c.id==ar.c.version_id)).join(
        iw,(iw.c.project_id==iv.c.project_id)&(iw.c.id==iv.c.workflow_id)).where(ar.c.project_id==project_id,iw.c.episode_id==episode_id)
    # Use the same fixed producer provenance as the media directory. A later
    # canvas reference to a job is a use, not its original production surface.
    from .media_catalog import ProjectMediaCatalog
    canvas_job=ProjectMediaCatalog._canvas_jobs((project_id,))
    canvas_version,canvas=S.creative_canvas_versions,S.creative_canvases
    source("generation",j,object_name(func.coalesce(j.c.shot_id,j.c.asset_id),'媒体生成'),
        case((canvas.c.id.is_not(None),'creative-canvas'),else_='candidates'),
        func.coalesce(canvas.c.id,j.c.shot_id,j.c.asset_id),scope=canvas.c.episode_id,node=canvas_job.c.node_key,
        outer_joins=((canvas_job,(canvas_job.c.project_id==j.c.project_id)&(canvas_job.c.job_id==j.c.id)),
            (canvas_version,(canvas_version.c.project_id==canvas_job.c.project_id)&(canvas_version.c.id==canvas_job.c.version_id)),
            (canvas,(canvas.c.project_id==canvas_version.c.project_id)&(canvas.c.id==canvas_version.c.canvas_id))),
        belongs=case((canvas.c.id.is_not(None),canvas.c.episode_id==episode_id),
            else_=or_(j.c.shot_id.in_(shot_ids),j.c.asset_id.in_(asset_ids),j.c.run_version_id.in_(asset_run))))
    r,v,w=S.edit_render_jobs,S.edit_revisions,S.edit_workspaces
    source("editing",r,object_name(w.c.episode_id,'首版合成'),"editing",w.c.episode_id,r.c.error,
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.edit_version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workspace_id))),scope=w.c.episode_id,belongs=w.c.episode_id==episode_id)
    r,v,w=S.spatial_exports,S.spatial_scene_versions,S.spatial_scenes
    spatial_scope=func.coalesce(w.c.episode_id,select(scenes.c.parent_id).where(
        scenes.c.project_id==project_id,scenes.c.id==w.c.scene_id).scalar_subquery())
    source("spatial",r,v.c.title,w.c.mode,w.c.id,r.c.error,
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.spatial_scene_id))),
        scope=spatial_scope,belongs=or_(w.c.episode_id==episode_id,w.c.scene_id.in_(select(scenes.c.id).where(scenes.c.project_id==project_id,scenes.c.parent_id==episode_id))))
    r = S.spatial_plan_tasks
    source('spatial_plan', r, v.c.title, w.c.mode, w.c.id, r.c.error,
        ((v, (v.c.project_id == r.c.project_id) & (v.c.id == r.c.version_id)),
         (w, (w.c.project_id == v.c.project_id) & (w.c.id == v.c.spatial_scene_id))),
        scope=spatial_scope,belongs=or_(w.c.episode_id==episode_id,w.c.scene_id.in_(select(scenes.c.id).where(scenes.c.project_id==project_id,scenes.c.parent_id==episode_id))))
    request = S.artifact_versions.alias('lyrics_request')
    result = S.artifact_versions.alias('lyrics_result')
    fixed = cast(func.convert_from(request.c.document, 'UTF8'), JSONB)
    response = cast(func.convert_from(result.c.document, 'UTF8'), JSONB)
    lyrics_query=(select(request.c.id,
        func.coalesce(response['status'].astext, case(
            (request.c.created_at + text("interval '180 seconds'") < func.now(), 'submission_unknown'),
            else_='running')).label('status'), request.c.created_at,
        literal('歌词创作').label('title'), literal('lyrics').label('kind'),
        literal('creative-tools').label('page'), request.c.id.label('target_id'),
        response['error'].astext.label('error'), fixed['episode_id'].astext.label('scope_id'),literal('lyrics').label('tool_id'),
        literal(None).label('focus_node_key'),
        case((response['status'].astext=='completed',1),else_=0).label('result_count'),
        literal(0).label('problem_count'),
        func.encode(func.sha256(func.convert_to(func.concat_ws('|',cast(result.c.id,Text),func.coalesce(response['status'].astext,'submission_unknown')),'UTF8')),'hex').label('source_token'))
        .select_from(request.outerjoin(result, (result.c.project_id == request.c.project_id) &
            (result.c.artifact_key == literal('lyrics-result:') + cast(request.c.id, Text))))
        .where(request.c.project_id == project_id, request.c.artifact_type == 'lyrics-request'))
    if episode_id is not None:lyrics_query=lyrics_query.where(fixed['episode_id'].astext==episode_id)
    sources.append(('lyrics',lyrics_query))
    i,b=S.media_import_items,S.media_import_batches
    source("import",i,i.c.filename,"media-imports",b.c.id,i.c.error,((b,(b.c.project_id==i.c.project_id)&(b.c.id==i.c.batch_id)),),scope=b.c.episode_id,belongs=b.c.episode_id==episode_id)
    a,u=S.text_tool_attempts,S.text_tool_units
    source("text",a,u.c.title,"text-tools",u.c.id,a.c.error_code,((u,(u.c.project_id==a.c.project_id)&(u.c.id==a.c.unit_id)),),scope=u.c.episode_id,tool=u.c.tool,belongs=u.c.episode_id==episode_id)
    batch, member = S.text_tool_batches, S.text_tool_batch_items
    first_unit = select(member.c.unit_id).where(member.c.project_id == batch.c.project_id,
        member.c.batch_id == batch.c.id).order_by(member.c.ordinal).limit(1).scalar_subquery()
    member_facts=select(func.string_agg(func.concat_ws(':',cast(member.c.id,Text),member.c.status,
        cast(member.c.attempt_id,Text),member.c.error_code),aggregate_order_by(literal('|'),member.c.ordinal))).where(
        member.c.project_id==batch.c.project_id,member.c.batch_id==batch.c.id).scalar_subquery()
    batch_episode=select(member.c.id).join(u,(u.c.project_id==member.c.project_id)&(u.c.id==member.c.unit_id)).where(
        member.c.project_id==batch.c.project_id,member.c.batch_id==batch.c.id,u.c.episode_id==episode_id).exists()
    source('text_batch', batch, literal('批量 ') + batch.c.action, 'text-tools', first_unit, tool=batch.c.tool,token_parts=(member_facts,),belongs=batch_episode)
    t,s=S.canvas_agent_turns,S.canvas_agent_sessions
    canvas_episode=select(S.creative_canvases.c.id).where(S.creative_canvases.c.project_id==project_id,S.creative_canvases.c.episode_id==episode_id)
    canvas_subject=select(canvas_version.c.title).where(canvas_version.c.project_id==project_id,
        canvas_version.c.id==t.c.version_id).scalar_subquery()
    source('canvas',t,canvas_subject,'creative-canvas',s.c.canvas_id,t.c.error,
        ((s,(s.c.project_id==t.c.project_id)&(s.c.id==t.c.session_id)),
         (canvas,(canvas.c.project_id==s.c.project_id)&(canvas.c.id==s.c.canvas_id))),scope=canvas.c.episode_id,
        node=t.c.target_node_key,belongs=s.c.canvas_id.in_(canvas_episode))
    t,v,w=S.intelligent_tasks,S.intelligent_versions,S.intelligent_workflows
    source('intelligent',t,w.c.title,case((v.c.route=='storyboard','intelligent-storyboard'),else_='intelligent-creation'),w.c.id,t.c.error,
        ((v,(v.c.project_id==t.c.project_id)&(v.c.id==t.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workflow_id))),scope=w.c.episode_id,belongs=w.c.episode_id==episode_id)
    return sources


def task_origin_href(project_id,row,episode_id=None):
    key='episode' if row['kind']=='editing' else 'scope' if row['kind']=='generation' and row['page']=='candidates' else 'task_target'
    params={'page':row['page'],'project':project_id,key:row['target_id'],'task_id':row['id']}
    if row.get('scope_id'):params['episode']=row['scope_id']
    elif episode_id is not None:params['episode']=episode_id
    if row.get('tool_id'):params['tool']=row['tool_id']
    if row['kind']=='canvas':params['agent_turn']=row['id']
    if row.get('focus_node_key'):params['focus_node_key']=row['focus_node_key']
    return '/?'+urlencode(params)


def decorate_tasks(conn,project_id,rows,episode_id=None):
    member,u=S.text_tool_batch_items,S.text_tool_units
    batch_ids=[row['id'] for row in rows if row['kind']=='text_batch']
    members={identifier:[] for identifier in batch_ids}
    if batch_ids:
        entries=conn.execute(select(member.c.id,member.c.ordinal,member.c.status,member.c.action,
            member.c.batch_id,
            member.c.unit_id,member.c.attempt_id,member.c.output_version_id,member.c.error_code,
            u.c.title,u.c.tool,S.text_tool_attempts.c.result_version_id).join(u,(u.c.project_id==member.c.project_id)&(u.c.id==member.c.unit_id))
            .outerjoin(S.text_tool_attempts,(S.text_tool_attempts.c.project_id==member.c.project_id)&
                (S.text_tool_attempts.c.id==member.c.attempt_id))
            .where(member.c.project_id==project_id,member.c.batch_id.in_(batch_ids))
            .order_by(member.c.batch_id,member.c.ordinal)).mappings().all()
        for entry in entries:members[entry['batch_id']].append(entry)
    for row in rows:
        if row['kind']!='text_batch':continue
        entries=members[row['id']]
        counts={state:sum(item['status']==state for item in entries)
            for state in ('pending','running','completed','failed','blocked','skipped')}
        row['progress']={**counts,'total':len(entries),
            'terminal':sum(counts[state] for state in ('completed','failed','blocked','skipped'))}
        row['children']=[{**dict(item),'href':'/?'+urlencode({'page':'text-tools','project':project_id,
            'tool':item['tool'],'task_target':item['unit_id']})} for item in entries[:50]]
        row['children_truncated']=len(entries)>50
    for row in rows:
        row['href']=task_origin_href(project_id,row,episode_id)
    _decorate_results(conn,project_id,rows,members)
    return rows


def _decorate_results(conn,project_id,rows,members):
    """Read only page-bound facts, in batches per source; never load all tasks."""
    by_kind={kind:[row for row in rows if row['kind']==kind] for kind in ORIGIN_LABELS}
    facts={}
    tables={'generation':S.generation_jobs,'editing':S.edit_render_jobs,'spatial':S.spatial_exports,
        'spatial_plan':S.spatial_plan_tasks,'import':S.media_import_items,'text':S.text_tool_attempts,
        'canvas':S.canvas_agent_turns,'intelligent':S.intelligent_tasks}
    for kind,table in tables.items():
        ids=[row['id'] for row in by_kind[kind]]
        if ids:
            fields=[table.c.id]+[table.c[name] for name in ('shot_id','asset_id','result_version_id',
                'output_blob_id','media_id','plan_artifact_id','output_version_id','run_artifact_id',
                'progress_frames','total_frames') if name in table.c]
            facts[kind]={r['id']:dict(r) for r in conn.execute(select(*fields).where(
                table.c.project_id==project_id,table.c.id.in_(ids))).mappings()}
    outputs={}
    for kind,table,key in (('generation',S.job_outputs,'job_id'),('spatial',S.spatial_export_outputs,'export_id')):
        ids=[row['id'] for row in by_kind[kind]]
        if ids:
            for result in conn.execute(select(table.c[key],table.c.media_id).where(
                    table.c.project_id==project_id,table.c[key].in_(ids))).mappings():
                outputs.setdefault((kind,result[key]),[]).append({'kind':'media','id':result['media_id']})
    ids=[row['id'] for row in by_kind['lyrics']]
    if ids:
        import json
        for result in conn.execute(select(S.artifact_versions.c.id,S.artifact_versions.c.artifact_key,
                S.artifact_versions.c.document).where(S.artifact_versions.c.project_id==project_id,
                S.artifact_versions.c.artifact_key.in_(['lyrics-result:'+str(i) for i in ids]))).mappings():
            if json.loads(result['document']).get('status')=='completed':
                outputs[('lyrics',result['artifact_key'].split(':',1)[1])]=[{'kind':'artifact','id':result['id']}]
    # Current working choices and formal bindings are different authorities.
    choices,adoptions={},{}
    ids=[row['id'] for row in by_kind['generation']]
    if ids:
        output,candidate=S.job_outputs,S.binding_candidates
        for target,result_map in ((S.current_bindings,adoptions),(S.current_working_selections,choices)):
            query=select(output.c.job_id,func.count(func.distinct(candidate.c.media_id)).label('count')).select_from(output).join(
                candidate,(candidate.c.project_id==output.c.project_id)&(candidate.c.media_id==output.c.media_id)).join(
                S.generation_jobs,(S.generation_jobs.c.project_id==output.c.project_id)&(S.generation_jobs.c.id==output.c.job_id))
            if target is S.current_bindings:
                slot=S.binding_slots
                query=query.join(target,(target.c.project_id==candidate.c.project_id)&(target.c.candidate_id==candidate.c.id)).join(
                    slot,(slot.c.project_id==candidate.c.project_id)&(slot.c.id==candidate.c.slot_id)&
                    (slot.c.target_object_id==func.coalesce(S.generation_jobs.c.shot_id,S.generation_jobs.c.asset_id)))
            else:
                choice=S.working_selection_versions
                query=query.join(choice,(choice.c.project_id==candidate.c.project_id)&(choice.c.candidate_id==candidate.c.id)).join(
                    target,(target.c.project_id==choice.c.project_id)&(target.c.selection_version_id==choice.c.id)&
                    (target.c.shot_id==S.generation_jobs.c.shot_id))
            result_map.update({item['job_id']:item['count'] for item in conn.execute(query.where(
                output.c.project_id==project_id,output.c.job_id.in_(ids)).group_by(output.c.job_id)).mappings()})
    object_ids={row.get('scope_id') for row in rows}|{row.get('target_id') for row in rows}
    for values in facts.values():
        for value in values.values():object_ids.update((value.get('shot_id'),value.get('asset_id')))
    object_ids.discard(None)
    paths={}
    if object_ids:
        from sqlalchemy import union_all
        obj=S.creative_objects
        parents=union_all(*[select(table.c.id,table.c.parent_id).where(table.c.project_id==project_id)
            for table in (S.episodes,S.scenes,S.sequences,S.shots)]).subquery()
        ancestors=select(obj.c.id.label('root_id'),obj.c.id,parents.c.parent_id,obj.c.title,obj.c.display_code,
            literal(0).label('depth')).outerjoin(parents,parents.c.id==obj.c.id).where(
            obj.c.project_id==project_id,obj.c.id.in_(object_ids)).cte('task_object_ancestors',recursive=True)
        ancestors=ancestors.union_all(select(ancestors.c.root_id,obj.c.id,parents.c.parent_id,obj.c.title,
            obj.c.display_code,(ancestors.c.depth+1).label('depth')).select_from(ancestors).join(
            obj,(obj.c.project_id==project_id)&(obj.c.id==ancestors.c.parent_id)).outerjoin(
            parents,parents.c.id==obj.c.id).where(ancestors.c.depth<8))
        for value in conn.execute(select(ancestors).order_by(ancestors.c.depth.desc())).mappings():
            label=value['title'] or value['display_code']
            paths.setdefault(value['root_id'],[]).append(label)
    for row in rows:
        kind,identifier=row['kind'],row['id'];fact=facts.get(kind,{}).get(identifier,{})
        refs=list(outputs.get((kind,identifier),[]))
        if kind=='text_batch':refs=[{'kind':'artifact','id':item[field]} for item in members[identifier]
            for field in ('output_version_id','result_version_id') if item[field]]
        for field,ref_kind in (('media_id','media'),('result_version_id','artifact'),('output_blob_id','media_blob'),
                ('plan_artifact_id','artifact'),('output_version_id',{'canvas':'canvas_version',
                    'intelligent':'intelligent_version','spatial_plan':'spatial_version'}.get(kind,'version')),
                ('run_artifact_id','artifact')):
            if fact.get(field):refs.append({'kind':ref_kind,'id':fact[field]})
        refs=[dict(pair) for pair in {tuple(sorted(ref.items())) for ref in refs}]
        refs.sort(key=lambda ref:(ref['kind'],str(ref['id'])))
        working_known=kind=='generation' and fact.get('shot_id') is not None
        result={'available':bool(refs),'count':len(refs),'refs':refs,
            'working_selection':{'known':working_known,'count':choices.get(identifier,0) if working_known else None},
            'adoption':{'known':kind=='generation','count':adoptions.get(identifier,0) if kind=='generation' else None},
            'label':str(len(refs))+' 个已登记结果' if refs else '尚无已登记结果',
            'detail':'结果登记与原对象的当前工作选材、正式绑定分别记录；未覆盖的采用关系请到原任务核对'}
        row['result']=result
        if 'progress_frames' in fact:row['progress']={'completed':fact['progress_frames'],'total':fact['total_frames']}
        group=row.pop('_group',None)
        if group is None:
            state=row['status']
            group=('unknown' if state in ('submission_unknown','unknown') else
                'attention' if state!='stopped' and row.get('problem_count',0)>0 or state in ('failed','needs_input','planned','awaiting_upload','blocked') else
                'running' if state in ('created','ready','queued','pending','running','submitted','polling','uploaded','result_ready','cancel_requested') else
                'ended' if state in ('applied','cancelled','rejected','stopped','skipped') else
                'result' if state in ('succeeded','completed') and row.get('result_count',0)>0 else 'unknown')
        state_labels={'result_ready':'登记中','submission_unknown':'待核对提交','awaiting_upload':'等待上传','failed':'失败',
            'needs_input':'等待补充','planned':'方案待处理','applied':'已写入工作版本','succeeded':'已完成','completed':'已完成',
            'cancelled':'已取消','stopped':'已停止','rejected':'已拒绝','created':'等待执行器','queued':'等待执行器',
            'ready':'等待执行','running':'处理中','submitted':'远端处理中','uploaded':'等待导入处理'}
        state_detail=('提交结果尚未核实，请到原任务核对；不要重复提交' if row['status']=='submission_unknown' else
            '供应商或宿主结果已返回，正在登记原域结果' if row['status']=='result_ready' else
            '批次含失败或阻塞子项，请到原批次继续处理' if group=='attention' and row.get('problem_count',0)>0 else
            '方案已经登记，请在原页面查看并决定下一步' if row['status']=='planned' else
            '方案已写入原工作版本，正式批准另行记录' if row['status']=='applied' else
            '原任务已结束，但未查询到已登记结果，请到原任务核对' if group=='unknown' and row['status'] in ('succeeded','completed') else
            row.get('error') or '原任务进展与结果按原域记录；采用需另行核对')
        target=fact.get('shot_id') or fact.get('asset_id') or row.get('target_id')
        path=' / '.join(paths.get(target) or paths.get(row.get('scope_id'),[])+[row['title']])
        row['presentation']={'group':group,'state_label':state_labels.get(row['status'],
            {'running':'进行中','attention':'需处理','result':'有结果','ended':'已结束','unknown':'需核对'}[group]),
            'state_detail':state_detail,'origin_label':ORIGIN_LABELS[kind],'object_path':path,
            'primary_label':'核对原任务' if group=='unknown' else '查看结果' if result['available'] else '查看原任务',
            'result_label':result['label'],'result_detail':result['detail']}


class TaskCenterRepository:
    def __init__(self,store):self.store=store

    def origin(self,project_id,kind,identifier):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,checked_id(project_id));self.store._access_require(conn,project['id'],'read')
            source=dict(task_sources(project['id']))[kind].subquery()
            row=conn.execute(select(source).where(source.c.id==checked_id(identifier))).mappings().first()
            if not row:raise ResourceError('此任务不属于当前项目','task_origin_missing',404)
            item=decorate_tasks(conn,project['id'],[dict(row)])[0]
            if kind=='generation':
                item['remote_cancel']={'available':False,'reason':'当前供应商适配器没有已核实的远端取消协议；在途任务保留原查询身份。'}
                item['usage']=self.store.task_usage_detail(project['id'],identifier)
            else:item['usage']={'coverage':'not_recorded','units':[],'quote':None,'reconciliation':None,
                'actual_cost':None,'amount_known':False,'detail':'此域未接入项目原生计量；不能据此认定免费'}
            return clean(dict(project_id=project['id'],revision=project['revision'],task=item))

    def query(self,project_id,offset,limit,kind=None,status=None,episode_id=None,group=None):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,project_id)
            self.store._access_require(conn,project_id,'read')
            if episode_id is not None:
                episode_id=checked_id(episode_id)
                self.store._one(conn,S.episodes,project_id,episode_id)
            sources=task_sources(project_id,episode_id)
            rows,total=[],0
            groups={key:0 for key in GROUPS}
            for code,query in sources:
                if kind and code!=kind:continue
                table=query.subquery()
                selected=select(table)
                if status:selected=selected.where(table.c.status==status)
                filtered=selected.subquery()
                classified=select(filtered,task_group(filtered).label('_group')).subquery()
                for count in conn.execute(select(classified.c._group,func.count().label('count')).group_by(classified.c._group)).mappings():
                    groups[count['_group']]+=count['count']
                selected=select(classified)
                if group:selected=selected.where(classified.c._group==group)
                rows.extend(dict(row) for row in conn.execute(selected.order_by(classified.c.created_at.desc(),classified.c.id.desc()).limit(offset+limit)).mappings())
            groups['all']=sum(groups.values())
            total=groups[group] if group else groups['all']
            rows.sort(key=lambda row:(row["created_at"],row["kind"],str(row["id"])),reverse=True)
            page_rows=rows[offset:offset+limit]
            decorate_tasks(conn,project_id,page_rows,episode_id)
            return clean({"project_id":project["id"],"episode_id":episode_id,"revision":project["revision"],"items":rows[offset:offset+limit],"total":total,
                'groups':groups,
                "next_offset":offset+limit if offset+limit<total else None})
