"""Read-only aggregation; each original domain continues to own recovery."""
from sqlalchemy import select,func,literal,case
from urllib.parse import urlencode
from . import schema as S
from .values import clean


class TaskCenterRepository:
    def __init__(self,store):self.store=store

    def query(self,project_id,offset,limit,kind=None,status=None):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,project_id)
            sources=[]
            def source(code,table,title,page,target=None,error=None,joins=(),scope=None):
                query=select(table.c.id,table.c.status,table.c.created_at,title.label("title"),literal(code).label("kind"),
                    (literal(page) if isinstance(page,str) else page).label("page"),(target if target is not None else table.c.id).label("target_id"),
                    (error if error is not None else literal(None)).label("error"),(scope if scope is not None else literal(None)).label('scope_id')).select_from(table)
                for joined,on in joins:query=query.join(joined,on)
                sources.append((code,query.where(table.c.project_id==project["id"])))
            j=S.generation_jobs
            source("generation",j,j.c.purpose,"candidates",func.coalesce(j.c.shot_id,j.c.asset_id))
            r,v,w=S.edit_render_jobs,S.edit_revisions,S.edit_workspaces
            source("editing",r,literal("首版合成"),"editing",w.c.episode_id,r.c.error,
                ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.edit_version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workspace_id))))
            r,v,w=S.spatial_exports,S.spatial_scene_versions,S.spatial_scenes
            source("spatial",r,literal("空间预演导出"),w.c.mode,w.c.id,r.c.error,
                ((v,(v.c.project_id==r.c.project_id)&(v.c.id==r.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.spatial_scene_id))))
            i,b=S.media_import_items,S.media_import_batches
            source("import",i,i.c.filename,"media-imports",b.c.id,i.c.error,((b,(b.c.project_id==i.c.project_id)&(b.c.id==i.c.batch_id)),))
            a,u=S.text_tool_attempts,S.text_tool_units
            source("text",a,u.c.title,"text-tools",u.c.id,a.c.error_code,((u,(u.c.project_id==a.c.project_id)&(u.c.id==a.c.unit_id)),))
            t,s=S.canvas_agent_turns,S.canvas_agent_sessions
            source('canvas',t,t.c.skill_id,'creative-canvas',s.c.canvas_id,t.c.error,
                ((s,(s.c.project_id==t.c.project_id)&(s.c.id==t.c.session_id)),))
            t,v,w=S.intelligent_tasks,S.intelligent_versions,S.intelligent_workflows
            source('intelligent',t,t.c.stage,case((v.c.route=='storyboard','intelligent-storyboard'),else_='intelligent-creation'),w.c.id,t.c.error,
                ((v,(v.c.project_id==t.c.project_id)&(v.c.id==t.c.version_id)),(w,(w.c.project_id==v.c.project_id)&(w.c.id==v.c.workflow_id))),scope=w.c.episode_id)
            rows,total=[],0
            for code,query in sources:
                if kind and code!=kind:continue
                table=query.subquery()
                selected=select(table)
                if status:selected=selected.where(table.c.status==status)
                total+=conn.execute(select(func.count()).select_from(selected.subquery())).scalar_one()
                rows.extend(dict(row) for row in conn.execute(selected.order_by(table.c.created_at.desc(),table.c.id.desc()).limit(offset+limit)).mappings())
            rows.sort(key=lambda row:(row["created_at"],row["kind"],str(row["id"])),reverse=True)
            for row in rows:
                key='episode' if row['kind']=='editing' else 'scope' if row['kind']=='generation' else 'task_target'
                params={'page':row['page'],'project':project['id'],key:row['target_id']}
                if row.get('scope_id'):params['episode']=row['scope_id']
                row['href']='/?'+urlencode(params)
            return clean({"project_id":project["id"],"revision":project["revision"],"items":rows[offset:offset+limit],"total":total,
                "next_offset":offset+limit if offset+limit<total else None})
