"""Read-only aggregation; each original domain continues to own recovery."""
from sqlalchemy import select,func,literal,case,cast,Text,text,or_,false
from sqlalchemy.dialects.postgresql import JSONB,aggregate_order_by
from urllib.parse import urlencode
from . import schema as S
from .values import clean,checked_id
from vsc.assets.resource_service import ResourceError


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
        parts=[table.c.status]+[table.c[name] for name in ('attempt','result_version_id','output_version_id','plan_artifact_id','output_sha256','media_id','error','error_code') if name in table.c]+list(token_parts)
        token=func.encode(func.sha256(func.convert_to(func.concat_ws('|',*[func.coalesce(cast(value,Text),'') for value in parts]),'UTF8')),'hex')
        query=select(table.c.id,table.c.status,table.c.created_at,title.label("title"),literal(code).label("kind"),
            (literal(page) if isinstance(page,str) else page).label("page"),(target if target is not None else table.c.id).label("target_id"),
            (error if error is not None else literal(None)).label("error"),(scope if scope is not None else literal(None)).label('scope_id'),
            (tool if tool is not None else literal(None)).label('tool_id'),
            (node if node is not None else literal(None)).label('focus_node_key'),token.label('source_token')).select_from(table)
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
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.edit_version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workspace_id))),belongs=w.c.episode_id==episode_id)
    r,v,w=S.spatial_exports,S.spatial_scene_versions,S.spatial_scenes
    source("spatial",r,literal("空间预演导出"),w.c.mode,w.c.id,r.c.error,
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.spatial_scene_id))),
        belongs=or_(w.c.episode_id==episode_id,w.c.scene_id.in_(select(scenes.c.id).where(scenes.c.project_id==project_id,scenes.c.parent_id==episode_id))))
    r = S.spatial_plan_tasks
    source('spatial_plan', r, literal('空间场景规划'), w.c.mode, w.c.id, r.c.error,
        ((v, (v.c.project_id == r.c.project_id) & (v.c.id == r.c.version_id)),
         (w, (w.c.project_id == v.c.project_id) & (w.c.id == v.c.spatial_scene_id))),
        belongs=or_(w.c.episode_id==episode_id,w.c.scene_id.in_(select(scenes.c.id).where(scenes.c.project_id==project_id,scenes.c.parent_id==episode_id))))
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
        func.encode(func.sha256(func.convert_to(func.concat_ws('|',cast(result.c.id,Text),func.coalesce(response['status'].astext,'submission_unknown')),'UTF8')),'hex').label('source_token'))
        .select_from(request.outerjoin(result, (result.c.project_id == request.c.project_id) &
            (result.c.artifact_key == literal('lyrics-result:') + cast(request.c.id, Text))))
        .where(request.c.project_id == project_id, request.c.artifact_type == 'lyrics-request'))
    if episode_id is not None:lyrics_query=lyrics_query.where(fixed['episode_id'].astext==episode_id)
    sources.append(('lyrics',lyrics_query))
    i,b=S.media_import_items,S.media_import_batches
    source("import",i,i.c.filename,"media-imports",b.c.id,i.c.error,((b,(b.c.project_id==i.c.project_id)&(b.c.id==i.c.batch_id)),),belongs=b.c.episode_id==episode_id)
    a,u=S.text_tool_attempts,S.text_tool_units
    source("text",a,u.c.title,"text-tools",u.c.id,a.c.error_code,((u,(u.c.project_id==a.c.project_id)&(u.c.id==a.c.unit_id)),),tool=u.c.tool,belongs=u.c.episode_id==episode_id)
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
    source('canvas',t,t.c.skill_id,'creative-canvas',s.c.canvas_id,t.c.error,
        ((s,(s.c.project_id==t.c.project_id)&(s.c.id==t.c.session_id)),
         (canvas,(canvas.c.project_id==s.c.project_id)&(canvas.c.id==s.c.canvas_id))),scope=canvas.c.episode_id,
        node=t.c.target_node_key,belongs=s.c.canvas_id.in_(canvas_episode))
    t,v,w=S.intelligent_tasks,S.intelligent_versions,S.intelligent_workflows
    source('intelligent',t,t.c.stage,case((v.c.route=='storyboard','intelligent-storyboard'),else_='intelligent-creation'),w.c.id,t.c.error,
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
    for row in rows:
        if row['kind']!='text_batch':continue
        entries=conn.execute(select(member.c.id,member.c.ordinal,member.c.status,member.c.action,
            member.c.unit_id,member.c.attempt_id,member.c.output_version_id,member.c.error_code,
            u.c.title,u.c.tool).join(u,(u.c.project_id==member.c.project_id)&(u.c.id==member.c.unit_id))
            .where(member.c.project_id==project_id,member.c.batch_id==row['id'])
            .order_by(member.c.ordinal)).mappings().all()
        counts={state:sum(item['status']==state for item in entries)
            for state in ('pending','running','completed','failed','blocked','skipped')}
        row['progress']={**counts,'total':len(entries),
            'terminal':sum(counts[state] for state in ('completed','failed','blocked','skipped'))}
        row['children']=[{**dict(item),'href':'/?'+urlencode({'page':'text-tools','project':project_id,
            'tool':item['tool'],'task_target':item['unit_id']})} for item in entries[:50]]
        row['children_truncated']=len(entries)>50
    for row in rows:
        row['href']=task_origin_href(project_id,row,episode_id)
    return rows


class TaskCenterRepository:
    def __init__(self,store):self.store=store

    def origin(self,project_id,kind,identifier):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,checked_id(project_id));self.store._access_require(conn,project['id'],'read')
            source=dict(task_sources(project['id']))[kind].subquery()
            row=conn.execute(select(source).where(source.c.id==checked_id(identifier))).mappings().first()
            if not row:raise ResourceError('此任务不属于当前项目','task_origin_missing',404)
            item=decorate_tasks(conn,project['id'],[dict(row)])[0]
            if kind=='generation':item['remote_cancel']={'available':False,'reason':'当前供应商适配器没有已核实的远端取消协议；在途任务保留原查询身份。'}
            return clean(dict(project_id=project['id'],revision=project['revision'],task=item))

    def query(self,project_id,offset,limit,kind=None,status=None,episode_id=None):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,project_id)
            self.store._access_require(conn,project_id,'read')
            if episode_id is not None:
                episode_id=checked_id(episode_id)
                self.store._one(conn,S.episodes,project_id,episode_id)
            sources=task_sources(project_id,episode_id)
            rows,total=[],0
            for code,query in sources:
                if kind and code!=kind:continue
                table=query.subquery()
                selected=select(table)
                if status:selected=selected.where(table.c.status==status)
                total+=conn.execute(select(func.count()).select_from(selected.subquery())).scalar_one()
                rows.extend(dict(row) for row in conn.execute(selected.order_by(table.c.created_at.desc(),table.c.id.desc()).limit(offset+limit)).mappings())
            rows.sort(key=lambda row:(row["created_at"],row["kind"],str(row["id"])),reverse=True)
            page_rows=rows[offset:offset+limit]
            decorate_tasks(conn,project_id,page_rows,episode_id)
            return clean({"project_id":project["id"],"episode_id":episode_id,"revision":project["revision"],"items":rows[offset:offset+limit],"total":total,
                "next_offset":offset+limit if offset+limit<total else None})
