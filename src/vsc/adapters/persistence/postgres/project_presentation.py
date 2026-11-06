"""Read-only cards over original project, object and media identities."""
from sqlalchemy import select, func
from . import schema as S
from .values import clean
from .media_recycle import recycled_ids
from .project_management import hidden_object_ids


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
        for source in projects:
            row = dict(source)
            if row.get('storage_policy') != 'postgres-series-v1' or row.get('unavailable'):
                result.append(row)
                continue
            p = row['id']; hidden = hidden_object_ids(conn, p)
            media = visible_media(p).subquery()
            counts = dict(conn.execute(select(media.c.modality, func.count()).group_by(media.c.modality)).all())
            row['counts'] = dict(episodes=conn.execute(select(func.count()).select_from(S.episodes).where(
                S.episodes.c.project_id == p, S.episodes.c.id.not_in(hidden))).scalar_one(),
                images=counts.get('image', 0), videos=counts.get('video', 0),
                canvases=conn.execute(select(func.count()).select_from(S.creative_canvases).where(
                    S.creative_canvases.c.project_id == p,
                    (S.creative_canvases.c.episode_id.is_(None) | S.creative_canvases.c.episode_id.not_in(hidden)))).scalar_one())
            profile = row.get('profile_id') or row.get('profile')
            style = {'2d': '2D动漫', '3d': '3D动漫', 'live': '真人'}.get((row.get('profile_snapshot') or {}).get('character_style'))
            row['project_type'] = style or {'vsc.light-short': '短视频', 'vsc.series-pg': '连续短剧',
                'vsc.text-tools': '文本工具', 'vsc.creative-tools': '创作工具'}.get(profile)
            row['cover'] = media_cover(conn, p)
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
    row['cover'] = media_cover(conn, p, ids)
    row['kind_label'] = {'canvas': '画布', 'editing': '剪辑', 'intelligent': 'Agent 工作流', 'text': '文字创作'}.get(kind, '创作')
    return row
