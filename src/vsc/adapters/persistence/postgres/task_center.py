"""Read-only aggregation; each original domain continues to own recovery."""
from sqlalchemy import select,func,literal,case,cast,Text,text
from sqlalchemy.dialects.postgresql import JSONB,aggregate_order_by
from urllib.parse import urlencode
from . import schema as S
from .values import clean,checked_id
from vsc.assets.resource_service import ResourceError


def task_sources(project_id):
    sources=[]
    def object_name(identifier,fallback):
        obj=S.creative_objects
        name=select(func.coalesce(func.nullif(obj.c.title,''),obj.c.display_code)).where(obj.c.project_id==project_id,obj.c.id==identifier).scalar_subquery()
        return func.coalesce(name,literal(fallback))
    def source(code,table,title,page,target=None,error=None,joins=(),scope=None,tool=None,token_parts=()):
        parts=[table.c.status]+[table.c[name] for name in ('attempt','result_version_id','output_version_id','plan_artifact_id','output_sha256','media_id','error','error_code') if name in table.c]+list(token_parts)
        token=func.encode(func.sha256(func.convert_to(func.concat_ws('|',*[func.coalesce(cast(value,Text),'') for value in parts]),'UTF8')),'hex')
        query=select(table.c.id,table.c.status,table.c.created_at,title.label("title"),literal(code).label("kind"),
            (literal(page) if isinstance(page,str) else page).label("page"),(target if target is not None else table.c.id).label("target_id"),
            (error if error is not None else literal(None)).label("error"),(scope if scope is not None else literal(None)).label('scope_id'),
            (tool if tool is not None else literal(None)).label('tool_id'),token.label('source_token')).select_from(table)
        for joined,on in joins:query=query.join(joined,on)
        sources.append((code,query.where(table.c.project_id==project_id)))
    j=S.generation_jobs
    source("generation",j,object_name(func.coalesce(j.c.shot_id,j.c.asset_id),'媒体生成'),"candidates",func.coalesce(j.c.shot_id,j.c.asset_id))
    r,v,w=S.edit_render_jobs,S.edit_revisions,S.edit_workspaces
    source("editing",r,object_name(w.c.episode_id,'首版合成'),"editing",w.c.episode_id,r.c.error,
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.edit_version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workspace_id))))
    r,v,w=S.spatial_exports,S.spatial_scene_versions,S.spatial_scenes
    source("spatial",r,literal("空间预演导出"),w.c.mode,w.c.id,r.c.error,
        ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.spatial_scene_id))))
    r = S.spatial_plan_tasks
    source('spatial_plan', r, literal('空间场景规划'), w.c.mode, w.c.id, r.c.error,
        ((v, (v.c.project_id == r.c.project_id) & (v.c.id == r.c.version_id)),
         (w, (w.c.project_id == v.c.project_id) & (w.c.id == v.c.spatial_scene_id))))
    request = S.artifact_versions.alias('lyrics_request')
    result = S.artifact_versions.alias('lyrics_result')
    fixed = cast(func.convert_from(request.c.document, 'UTF8'), JSONB)
    response = cast(func.convert_from(result.c.document, 'UTF8'), JSONB)
    sources.append(('lyrics', select(request.c.id,
        func.coalesce(response['status'].astext, case(
            (request.c.created_at + text("interval '180 seconds'") < func.now(), 'submission_unknown'),
            else_='running')).label('status'), request.c.created_at,
        literal('歌词创作').label('title'), literal('lyrics').label('kind'),
        literal('creative-tools').label('page'), request.c.id.label('target_id'),
        response['error'].astext.label('error'), fixed['episode_id'].astext.label('scope_id'),literal('lyrics').label('tool_id'),
        func.encode(func.sha256(func.convert_to(func.concat_ws('|',cast(result.c.id,Text),func.coalesce(response['status'].astext,'submission_unknown')),'UTF8')),'hex').label('source_token'))
        .select_from(request.outerjoin(result, (result.c.project_id == request.c.project_id) &
            (result.c.artifact_key == literal('lyrics-result:') + cast(request.c.id, Text))))
        .where(request.c.project_id == project_id, request.c.artifact_type == 'lyrics-request')))
    i,b=S.media_import_items,S.media_import_batches
    source("import",i,i.c.filename,"media-imports",b.c.id,i.c.error,((b,(b.c.project_id==i.c.project_id)&(b.c.id==i.c.batch_id)),))
    a,u=S.text_tool_attempts,S.text_tool_units
    source("text",a,u.c.title,"text-tools",u.c.id,a.c.error_code,((u,(u.c.project_id==a.c.project_id)&(u.c.id==a.c.unit_id)),),tool=u.c.tool)
    batch, member = S.text_tool_batches, S.text_tool_batch_items
    first_unit = select(member.c.unit_id).where(member.c.project_id == batch.c.project_id,
        member.c.batch_id == batch.c.id).order_by(member.c.ordinal).limit(1).scalar_subquery()
    member_facts=select(func.string_agg(func.concat_ws(':',cast(member.c.id,Text),member.c.status,
        cast(member.c.attempt_id,Text),member.c.error_code),aggregate_order_by(literal('|'),member.c.ordinal))).where(
        member.c.project_id==batch.c.project_id,member.c.batch_id==batch.c.id).scalar_subquery()
    source('text_batch', batch, literal('批量 ') + batch.c.action, 'text-tools', first_unit, tool=batch.c.tool,token_parts=(member_facts,))
    t,s=S.canvas_agent_turns,S.canvas_agent_sessions
    source('canvas',t,t.c.skill_id,'creative-canvas',s.c.canvas_id,t.c.error,
        ((s,(s.c.project_id==t.c.project_id)&(s.c.id==t.c.session_id)),))
    t,v,w=S.intelligent_tasks,S.intelligent_versions,S.intelligent_workflows
    source('intelligent',t,t.c.stage,case((v.c.route=='storyboard','intelligent-storyboard'),else_='intelligent-creation'),w.c.id,t.c.error,
        ((v,(v.c.project_id==t.c.project_id)&(v.c.id==t.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workflow_id))),scope=w.c.episode_id)
    return sources


def decorate_tasks(conn,project_id,rows):
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
        key='episode' if row['kind']=='editing' else 'scope' if row['kind']=='generation' else 'task_target'
        params={'page':row['page'],'project':project_id,key:row['target_id']}
        if row.get('scope_id'):params['episode']=row['scope_id']
        if row.get('tool_id'):params['tool'] = row['tool_id']
        if row['kind'] == 'lyrics':params['tool'] = 'lyrics'
        row['href']='/?'+urlencode(params)
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

    def query(self,project_id,offset,limit,kind=None,status=None):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,project_id)
            sources=task_sources(project_id)
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
            decorate_tasks(conn,project_id,page_rows)
            return clean({"project_id":project["id"],"revision":project["revision"],"items":rows[offset:offset+limit],"total":total,
                "next_offset":offset+limit if offset+limit<total else None})
