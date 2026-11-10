"""Discover original creative objects and templates within current access grants."""
from urllib.parse import urlencode
from sqlalchemy import select,literal,case,func,tuple_
from vsc.assets.classic_production import DRAFT_TYPE,MODES
from . import schema as S
from .values import clean
from .project_presentation import present_recent
from .project_management import hidden_object_ids, inactive_canvas_ids


def _classic_recent_query(project_ids, hidden):
    """One latest saved draft per visible episode and image/video workspace."""
    a,scope,shot,sequence,scene,obj = (S.artifact_versions,S.artifact_object_scopes,
        S.shots,S.sequences,S.scenes,S.creative_objects)
    mode=func.split_part(a.c.artifact_key,':',3)
    kinds={name:spec['modality'] for name,spec in MODES.items()
        if spec['modality'] in {'image','video'} and not spec.get('internal')}
    heads=select(a.c.project_id,shot.c.id.label('target_id'),scene.c.parent_id.label('episode_id'),
        obj.c.title,a.c.id.label('version_id'),a.c.version,a.c.sha256,a.c.created_at,
        mode.label('mode'),case(kinds,value=mode).label('production_kind')).select_from(a).join(scope,
            (scope.c.project_id==a.c.project_id)&(scope.c.artifact_id==a.c.id)).join(shot,
            (shot.c.project_id==scope.c.project_id)&(shot.c.id==scope.c.object_id)).join(sequence,
            (sequence.c.project_id==shot.c.project_id)&(sequence.c.id==shot.c.parent_id)).join(scene,
            (scene.c.project_id==sequence.c.project_id)&(scene.c.id==sequence.c.parent_id)).join(obj,
            (obj.c.project_id==shot.c.project_id)&(obj.c.id==shot.c.id)).where(
                a.c.project_id.in_(project_ids),a.c.artifact_type==DRAFT_TYPE,mode.in_(kinds),
                a.c.artifact_key==func.concat('classic:',shot.c.id,':',mode),
                tuple_(shot.c.project_id,shot.c.id).not_in([(p,i) for p,items in hidden.items() for i in items]))
    # Saved drafts are unapproved working versions; current_artifact_versions is an approval pointer.
    heads=heads.distinct(a.c.project_id,a.c.artifact_key).order_by(
        a.c.project_id,a.c.artifact_key,a.c.version.desc()).subquery('classic_draft_heads')
    ranked=select(heads,func.row_number().over(
        partition_by=(heads.c.project_id,heads.c.episode_id,heads.c.production_kind),
        order_by=(heads.c.created_at.desc(),heads.c.version_id.desc())).label('recent_rank')).subquery('classic_recent')
    return select(*(ranked.c[name] for name in heads.c.keys())).where(ranked.c.recent_rank==1)


def discover(store,limit=24):
    snapshot=store.access_snapshot()
    from .project_management import inactive_project_ids
    with store.engine.connect() as conn:
        inactive=set(conn.execute(select(S.projects.c.id).where(S.projects.c.id.in_(inactive_project_ids()))).scalars())
        projects=[row for row in snapshot['projects'] if row['id'] not in inactive]
        ids=[row['id'] for row in projects];names={row['id']:row['name'] for row in projects}
        rows=[]; hidden={p:hidden_object_ids(conn,p) for p in ids}
        def add(query,kind,page,target='task_target',tool=None):
            for value in conn.execute(query.order_by(query.selected_columns.created_at.desc(),query.selected_columns.target_id.desc()).limit(limit)).mappings():
                row=dict(value)
                if row.get('episode_id') in hidden[row['project_id']]:continue
                params={'page':page,'project':row['project_id'],target:row['target_id']}
                if row.get('episode_id'):params['episode']=row['episode_id']
                if tool:params['tool']=row[tool]
                if row.get('production_kind'):
                    params.update(kind=row['production_kind'],mode=row['mode'])
                rows.append({**row,'kind':kind,'project_name':names[row['project_id']],'href':'/?'+urlencode(params)})
        add(_classic_recent_query(ids,hidden),'classic','classic-production','scope')
        c,v=S.creative_canvases,S.creative_canvas_versions
        add(select(c.c.project_id,c.c.id.label('target_id'),c.c.episode_id,v.c.title,v.c.created_at).join(v,(v.c.project_id==c.c.project_id)&(v.c.id==c.c.current_version_id)).where(c.c.project_id.in_(ids),c.c.id.not_in(inactive_canvas_ids(c.c.project_id)),tuple_(c.c.project_id,c.c.episode_id).not_in([(p,i) for p,items in hidden.items() for i in items]) | c.c.episode_id.is_(None)),'canvas','creative-canvas')
        u,a=S.text_tool_units,S.artifact_versions
        add(select(u.c.project_id,u.c.id.label('target_id'),u.c.title,u.c.tool,a.c.created_at).join(a,(a.c.project_id==u.c.project_id)&(a.c.id==u.c.current_version_id)).where(u.c.project_id.in_(ids)),'text','text-tools',tool='tool')
        w,v=S.edit_workspaces,S.edit_revisions
        add(select(w.c.project_id,w.c.episode_id.label('target_id'),w.c.episode_id,literal('剪辑工作稿').label('title'),v.c.created_at).join(v,(v.c.project_id==w.c.project_id)&(v.c.id==w.c.current_version_id)).where(w.c.project_id.in_(ids)),'editing','editing','episode')
        w,v=S.intelligent_workflows,S.intelligent_versions
        latest=v.alias('latest_intelligent')
        head=select(latest.c.id).where(latest.c.project_id==w.c.project_id,latest.c.workflow_id==w.c.id).order_by(latest.c.version.desc()).limit(1).correlate(w).scalar_subquery()
        for route,page in (('creation','intelligent-creation'),('storyboard','intelligent-storyboard'),('storyboard_video','intelligent-creation'),('multi_reference_video','intelligent-creation')):
            add(select(w.c.project_id,w.c.id.label('target_id'),w.c.episode_id,w.c.title,v.c.created_at).select_from(w).join(v,(v.c.project_id==w.c.project_id)&(v.c.id==head)).where(w.c.project_id.in_(ids),v.c.route==route),'intelligent',page)
        rows.sort(key=lambda row:(row['created_at'],row['target_id']),reverse=True)
        t,v=S.canvas_templates,S.creative_canvas_versions
        templates=[dict(row,project_name=names[row['project_id']]) for row in conn.execute(select(t,v.c.version,v.c.canvas_id).join(v,(v.c.project_id==t.c.project_id)&(v.c.id==t.c.version_id)).where(t.c.project_id.in_(ids)).order_by(t.c.created_at.desc(),t.c.id.desc()).limit(100)).mappings()]
        favorites=set(conn.execute(select(S.canvas_template_favorites.c.template_id).where(S.canvas_template_favorites.c.project_id.in_(ids),S.canvas_template_favorites.c.actor==snapshot['identity']['actor'],S.canvas_template_favorites.c.active.is_(True))).scalars())
        for row in templates:
            row['favorite']=row['id'] in favorites
            row['href']='/?'+urlencode({'page':'creative-canvas','project':row['project_id'],'task_target':row['canvas_id']})
        # Fixed template records remain available through their history APIs.
        from .project_management import filter_management_rows
        templates=[row for row in templates if filter_management_rows(conn,row['project_id'],S.canvas_templates,[row])]
        return clean({'recent':[present_recent(conn,row) for row in rows[:limit]],'templates':templates,'projects':projects})
