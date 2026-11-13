"""Read-only cards over original project, object and media identities."""
from sqlalchemy import select, func, exists, false, case, and_, or_
from . import schema as S
from .values import clean, checked_id
from .media_recycle import recycled_ids
from .project_management import hidden_object_ids, inactive_canvas_ids

PROJECT_OWNER = S.access_identities.alias('project_owner')


def catalog_scope(workspace_id=None, relation=None, owner_kind=None):
    """Validate optional directory restrictions; neither parameter grants access."""
    from vsc.assets.resource_service import ResourceError
    if relation not in (None, '', 'created', 'participating'):
        raise ResourceError('项目关系筛选无效', 'invalid_project_scope')
    if owner_kind not in (None, '', 'personal', 'team'):
        raise ResourceError('项目归属类型无效', 'invalid_project_scope')
    return dict(workspace_id=checked_id(workspace_id) if workspace_id else None,
        relation=relation or None, owner_kind=owner_kind or None)


def scope_projects(store, conn, query, filters):
    """Restrict an already-authorized project query before any count or page."""
    workspace_id, relation, owner_kind = filters.get('workspace_id'), filters.get('relation'), filters.get('owner_kind')
    bindings, projects = S.access_projects, S.projects
    if workspace_id:
        query = query.where(projects.c.id.in_(select(bindings.c.project_id).where(bindings.c.workspace_id == workspace_id)))
    if owner_kind:
        owned = exists(select(1).select_from(bindings.join(S.access_workspaces,
            S.access_workspaces.c.id == bindings.c.workspace_id)).where(bindings.c.project_id == projects.c.id,
                S.access_workspaces.c.kind == 'personal' if owner_kind == 'personal'
                    else S.access_workspaces.c.kind.in_(['studio', 'substudio'])))
        # Trusted internal staging and old local imports may precede binding.
        # The user explicitly defines a recorded creator as their personal owner.
        if owner_kind == 'personal':
            owned = or_(owned, and_(projects.c.created_by.is_not(None),
                ~exists(select(1).where(bindings.c.project_id == projects.c.id))))
        query = query.where(owned)
    if relation:
        _, person, _ = store._access_principal(conn)
        if not person:
            return query.where(false())
        # Historical creators remain unknown. They may be in the participation
        # collection but must never be presented as a known other creator.
        query = query.where(projects.c.created_by == person['actor'] if relation == 'created'
            else projects.c.created_by.is_distinct_from(person['actor']))
    return query


def project_relation(created_by, actor):
    if created_by is None or actor is None:
        return 'unknown'
    return 'created' if created_by == actor else 'participating'


def workspace_columns():
    workspace = S.access_workspaces
    creator_name = select(S.access_identities.c.display_name).where(
        S.access_identities.c.actor == S.projects.c.created_by).correlate(S.projects).scalar_subquery()
    return (S.access_projects.c.workspace_id, S.access_workspaces.c.name.label('workspace_name'),
        S.access_workspaces.c.kind.label('workspace_kind'), S.projects.c.created_by.label('project_created_by'),
        case((workspace.c.kind == 'personal', 'personal'),
            (workspace.c.kind.in_(['studio', 'substudio']), 'team'),
            (S.projects.c.created_by.is_not(None), 'personal')).label('owner_kind'),
        case((workspace.c.kind == 'personal', PROJECT_OWNER.c.actor),
            (workspace.c.id.is_(None), S.projects.c.created_by)).label('owner_actor'),
        case((workspace.c.kind == 'personal', func.coalesce(PROJECT_OWNER.c.display_name, PROJECT_OWNER.c.actor)),
            (workspace.c.kind.in_(['studio', 'substudio']), workspace.c.name),
            else_=func.coalesce(creator_name, S.projects.c.created_by)).label('owner_name'))


def visible_media(project_id):
    depth = select(S.job_outputs.c.media_id).join(S.generation_jobs,
        (S.generation_jobs.c.project_id == S.job_outputs.c.project_id) &
        (S.generation_jobs.c.id == S.job_outputs.c.job_id)).where(
            S.job_outputs.c.project_id == project_id, S.generation_jobs.c.purpose == 'depth')
    return select(S.media_items).where(S.media_items.c.project_id == project_id,
        S.media_items.c.id.not_in(recycled_ids(project_id)), S.media_items.c.id.not_in(depth))


def media_cover(conn, project_id, media_ids=None):
    query = visible_media(project_id).where(S.media_items.c.modality.in_(['image', 'video']))
    if media_ids is not None:
        query = query.where(S.media_items.c.id.in_(media_ids))
    row = conn.execute(query.order_by(S.media_items.c.created_at.desc(), S.media_items.c.id.desc()).limit(1)).mappings().first()
    if not row:
        return None
    return dict(media_id=row['id'], modality=row['modality'],
        content_url='/api/v1/projects/'+project_id+'/media/'+row['id']+'/content')


def project_cards(store, projects):
    """Enrich already-authorized rows; legacy authority rows remain untouched."""
    result = []
    with store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        _, person, _ = store._access_principal(conn)
        actor = person['actor'] if person else None
        ids = [row['id'] for row in projects if row.get('storage_policy') == 'postgres-series-v1' and not row.get('unavailable')]
        metadata = {r['id']: dict(r) for r in conn.execute(select(S.projects.c.id, *workspace_columns())
            .outerjoin(S.access_projects, S.access_projects.c.project_id == S.projects.c.id)
            .outerjoin(S.access_workspaces, S.access_workspaces.c.id == S.access_projects.c.workspace_id)
            .outerjoin(PROJECT_OWNER, PROJECT_OWNER.c.id == S.access_workspaces.c.created_by)
            .where(S.projects.c.id.in_(ids))).mappings()} if ids else {}
        for source in projects:
            row = dict(source)
            if row.get('storage_policy') != 'postgres-series-v1' or row.get('unavailable'):
                result.append(row)
                continue
            facts = metadata.get(row['id'], {})
            row.update(workspace_id=facts.get('workspace_id'), workspace_name=facts.get('workspace_name'),
                workspace_kind=facts.get('workspace_kind'), created_by=facts.get('project_created_by'),
                owner_kind=facts.get('owner_kind', source.get('owner_kind')),
                owner_actor=facts.get('owner_actor', source.get('owner_actor')),
                owner_name=facts.get('owner_name', source.get('owner_name')),
                project_relation=project_relation(facts.get('project_created_by'), actor), my_role=None)
            scope = store._access_require(conn, row['id'])
            row['my_role'] = scope.get('effective_role')
            p = row['id']; hidden = hidden_object_ids(conn, p)
            media = visible_media(p).subquery()
            counts = dict(conn.execute(select(media.c.modality, func.count()).group_by(media.c.modality)).all())
            row['counts'] = dict(episodes=conn.execute(select(func.count()).select_from(S.episodes).where(
                S.episodes.c.project_id == p, S.episodes.c.id.not_in(hidden))).scalar_one(),
                images=counts.get('image', 0), videos=counts.get('video', 0),
                canvases=conn.execute(select(func.count()).select_from(S.creative_canvases).where(
                    S.creative_canvases.c.project_id == p,
                    S.creative_canvases.c.id.not_in(inactive_canvas_ids(p)),
                    (S.creative_canvases.c.episode_id.is_(None) | S.creative_canvases.c.episode_id.not_in(hidden)))).scalar_one())
            profile = row.get('profile_id') or row.get('profile')
            style = {'2d': '2D动漫', '3d': '3D动漫', 'live': '真人'}.get((row.get('profile_snapshot') or {}).get('character_style'))
            row['project_type'] = style or {'vsc.light-short': '短视频', 'vsc.series-pg': '连续短剧',
                'vsc.text-tools': '文本工具', 'vsc.creative-tools': '创作工具'}.get(profile)
            from .project_cover import project_cover
            row['cover'] = project_cover(conn, p)
            result.append(row)
    return clean(result)


def present_recent(conn, row):
    """A recent object cover is taken only from that object's typed media links."""
    p = row['project_id']; target = row['target_id']; kind = row['kind']
    episode = row.get('episode_id')
    if episode:
        row['episode_name'] = conn.execute(select(S.creative_objects.c.title).where(
            S.creative_objects.c.project_id == p, S.creative_objects.c.id == episode)).scalar_one_or_none()
    ids = []
    if kind == 'canvas':
        ids = select(S.creative_canvas_nodes.c.media_id).join(S.creative_canvases,
            (S.creative_canvases.c.project_id == S.creative_canvas_nodes.c.project_id) &
            (S.creative_canvases.c.current_version_id == S.creative_canvas_nodes.c.version_id)).where(
                S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == target,
                S.creative_canvas_nodes.c.media_id.is_not(None))
    elif kind == 'editing':
        ids = select(S.edit_revision_media.c.media_id).join(S.edit_workspaces,
            (S.edit_workspaces.c.project_id == S.edit_revision_media.c.project_id) &
            (S.edit_workspaces.c.current_version_id == S.edit_revision_media.c.edit_version_id)).where(
                S.edit_workspaces.c.project_id == p, S.edit_workspaces.c.episode_id == episode,
                S.edit_revision_media.c.track == 'clips')
    elif kind == 'classic':
        ids = select(S.classic_draft_media.c.media_id).where(
            S.classic_draft_media.c.project_id == p,
            S.classic_draft_media.c.draft_version_id == row['version_id'])
    row['cover'] = media_cover(conn, p, ids)
    row['kind_label'] = ({'video': '视频', 'image': '分镜'}.get(row.get('production_kind'))
        if kind == 'classic' else {'canvas': '画布', 'editing': '剪辑', 'intelligent': 'Agent', 'text': '文字创作'}.get(kind, '创作'))
    return row
