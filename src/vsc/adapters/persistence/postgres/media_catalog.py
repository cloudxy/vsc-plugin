"""Bounded project-media projection over original registrations and references.

No catalog row, media, job or completion state is written. A share to one canvas
is deliberately insufficient for this complete-project listing.
"""
from urllib.parse import urlencode

from sqlalchemy import and_, case, cast, distinct, exists, false, func, literal, null, or_, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import Text

from vsc.assets.resource_service import ResourceError
from . import schema as S
from .access_control import authority_lock
from .values import clean


def _uuid_null():
    return cast(null(), UUID(as_uuid=False))


class ProjectMediaCatalog:
    def __init__(self, store, configuration):
        self.store, self.configuration = store, configuration

    def _readable_projects(self, conn):
        return self.store._access_project_query(conn, 'read')

    @staticmethod
    def _references(allowed):
        e, sc, sq, sh = S.episodes, S.scenes, S.sequences, S.shots
        edges = union_all(*(select(t.c.project_id, t.c.parent_id, t.c.id.label('child_id'))
            for t in (e, sc, sq, sh))).cte('media_object_edges')
        states = S.management_object_states
        hidden = select(states.c.project_id, states.c.object_id).where(states.c.state != 'active').cte('media_hidden_objects', recursive=True)
        hidden = hidden.union(select(edges.c.project_id, edges.c.child_id)
            .join(hidden, and_(edges.c.project_id == hidden.c.project_id, edges.c.parent_id == hidden.c.object_id)))
        object_episodes = union_all(
            select(e.c.project_id, e.c.id.label('object_id'), e.c.id.label('episode_id')),
            select(sc.c.project_id, sc.c.id, sc.c.parent_id),
            select(sq.c.project_id, sq.c.id, sc.c.parent_id).join(sc, and_(sc.c.project_id == sq.c.project_id, sc.c.id == sq.c.parent_id)),
            select(sh.c.project_id, sh.c.id, sc.c.parent_id).join(sq, and_(sq.c.project_id == sh.c.project_id, sq.c.id == sh.c.parent_id))
                .join(sc, and_(sc.c.project_id == sq.c.project_id, sc.c.id == sq.c.parent_id))
        ).cte('media_object_episodes')
        objects = select(object_episodes).where(~exists(select(1).where(hidden.c.project_id == object_episodes.c.project_id,
            hidden.c.object_id == object_episodes.c.object_id))).cte('media_active_object_episodes')
        bc, bs = S.binding_candidates, S.binding_slots
        bindings = select(bc.c.project_id, bc.c.media_id, objects.c.episode_id, bs.c.target_object_id.label('target_id'),
            _uuid_null().label('canvas_id'), literal('binding').label('source_type'), bc.c.created_at.label('touched_at'))\
            .join(bs, and_(bs.c.project_id == bc.c.project_id, bs.c.id == bc.c.slot_id))\
            .join(objects, and_(objects.c.project_id == bs.c.project_id, objects.c.object_id == bs.c.target_object_id))
        jobs, outputs, inputs = S.generation_jobs, S.job_outputs, S.job_input_media
        job_refs = []
        for table, kind in ((outputs, 'job_output'), (inputs, 'job_input')):
            job_refs.append(select(jobs.c.project_id, table.c.media_id, objects.c.episode_id,
                func.coalesce(jobs.c.shot_id, jobs.c.asset_id).label('target_id'), _uuid_null().label('canvas_id'),
                literal(kind).label('source_type'), jobs.c.updated_at.label('touched_at'))
                .join(table, and_(table.c.project_id == jobs.c.project_id, table.c.job_id == jobs.c.id))
                .outerjoin(objects, and_(objects.c.project_id == jobs.c.project_id, objects.c.object_id == jobs.c.shot_id))
                .where(~exists(select(1).where(hidden.c.project_id == jobs.c.project_id,
                    hidden.c.object_id == func.coalesce(jobs.c.shot_id, jobs.c.asset_id)))))
        canvases, nodes, versions = S.creative_canvases, S.creative_canvas_nodes, S.creative_canvas_versions
        canvas_from = canvases.join(versions, and_(versions.c.project_id == canvases.c.project_id,
            versions.c.id == canvases.c.current_version_id)).join(nodes, and_(nodes.c.project_id == canvases.c.project_id,
                nodes.c.version_id == versions.c.id))
        canvas_active = and_(~exists(select(1).where(hidden.c.project_id == canvases.c.project_id,
            hidden.c.object_id == canvases.c.episode_id)), ~exists(select(1).where(
                S.management_canvas_states.c.project_id == canvases.c.project_id,
                S.management_canvas_states.c.canvas_id == canvases.c.id,
                S.management_canvas_states.c.state != 'active')))
        canvas_media = select(canvases.c.project_id, nodes.c.media_id, canvases.c.episode_id, _uuid_null().label('target_id'),
            canvases.c.id.label('canvas_id'), literal('canvas').label('source_type'), versions.c.created_at.label('touched_at'))\
            .select_from(canvas_from).where(nodes.c.media_id.is_not(None), canvas_active)
        canvas_jobs = select(canvases.c.project_id, outputs.c.media_id, canvases.c.episode_id, _uuid_null().label('target_id'),
            canvases.c.id.label('canvas_id'), literal('canvas').label('source_type'), versions.c.created_at.label('touched_at'))\
            .select_from(canvas_from.join(outputs, and_(outputs.c.project_id == nodes.c.project_id, outputs.c.job_id == nodes.c.job_id)))\
            .where(nodes.c.job_id.is_not(None), canvas_active)
        assets, forms, fv = S.episode_assets, S.episode_asset_forms, S.episode_asset_form_versions
        episode_assets = select(assets.c.project_id, fv.c.media_id, assets.c.episode_id, assets.c.episode_id.label('target_id'),
            _uuid_null().label('canvas_id'), literal('episode_asset').label('source_type'), fv.c.created_at.label('touched_at'))\
            .join(forms, and_(forms.c.project_id == assets.c.project_id, forms.c.episode_asset_id == assets.c.id))\
            .join(fv, and_(fv.c.project_id == forms.c.project_id, fv.c.id == forms.c.current_version_id))\
            .where(fv.c.media_id.is_not(None), ~exists(select(1).where(hidden.c.project_id == assets.c.project_id,
                hidden.c.object_id == assets.c.episode_id)))
        refs = union_all(bindings, *job_refs, canvas_media, canvas_jobs, episode_assets).cte('media_original_references')
        return select(refs).where(refs.c.project_id.in_(allowed)).cte('media_visible_references')

    def search(self, filters):
        media, projects, life = S.media_items, S.projects, S.media_lifecycle_decisions
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            authority_lock(conn)
            allowed = self._readable_projects(conn).where(~exists(select(1).where(
                S.management_project_states.c.project_id == projects.c.id, S.management_project_states.c.state != 'active')))
            if filters['project_id']:
                self.store._access_require(conn, filters['project_id'], 'read')
                allowed = allowed.where(projects.c.id == filters['project_id'])
            allowed = allowed.cte('media_readable_projects')
            refs = self._references(select(allowed.c.id))
            latest = select(life.c.project_id, life.c.media_id, life.c.id, life.c.outcome, life.c.created_at,
                func.row_number().over(partition_by=(life.c.project_id, life.c.media_id),
                    order_by=life.c.decision_sequence.desc()).label('rank')).where(life.c.project_id.in_(select(allowed.c.id))).cte('media_lifecycle_ranked')
            recycled = exists(select(1).select_from(latest.join(S.media_recycle_actions, and_(
                S.media_recycle_actions.c.project_id == latest.c.project_id, S.media_recycle_actions.c.decision_id == latest.c.id)))
                .where(latest.c.project_id == media.c.project_id, latest.c.media_id == media.c.id,
                    latest.c.rank == 1, latest.c.outcome == 'deprecate'))
            query = select(media, projects.c.name.label('project_name')).join(projects, projects.c.id == media.c.project_id)\
                .where(media.c.project_id.in_(select(allowed.c.id)), ~recycled)
            if filters['episode_id']:
                query = query.where(exists(select(1).where(refs.c.project_id == media.c.project_id,
                    refs.c.media_id == media.c.id, refs.c.episode_id == filters['episode_id'])))
            if filters['modality']:
                query = query.where(media.c.modality == filters['modality'])
            if filters['query']:
                pattern = '%' + filters['query'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                query = query.where(media.c.name.ilike(pattern, escape='\\'))
            if filters['created_after']:
                query = query.where(media.c.created_at >= filters['created_after'])
            if filters['created_before']:
                query = query.where(media.c.created_at < filters['created_before'])
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            if not total or filters['offset'] >= total:
                return {'items': [], 'total': total, 'offset': filters['offset'], 'limit': filters['limit'], 'next_offset': None}
            ref_stats = select(refs.c.project_id, refs.c.media_id, func.max(refs.c.touched_at).label('reference_updated_at'),
                func.count(distinct(refs.c.episode_id)).label('episode_count'),
                func.min(cast(refs.c.episode_id, Text)).label('single_episode_id')).group_by(refs.c.project_id, refs.c.media_id).subquery()
            life_updated = select(life.c.project_id, life.c.media_id, func.max(life.c.created_at).label('lifecycle_updated_at'))\
                .where(life.c.project_id.in_(select(allowed.c.id))).group_by(life.c.project_id, life.c.media_id).subquery()
            updated_at = func.greatest(media.c.created_at, ref_stats.c.reference_updated_at, life_updated.c.lifecycle_updated_at).label('updated_at')
            query = query.outerjoin(ref_stats, and_(ref_stats.c.project_id == media.c.project_id, ref_stats.c.media_id == media.c.id))\
                .outerjoin(life_updated, and_(life_updated.c.project_id == media.c.project_id, life_updated.c.media_id == media.c.id))\
                .add_columns(updated_at, ref_stats.c.episode_count, ref_stats.c.single_episode_id)
            sort_at = updated_at if filters['order'] == 'updated_desc' else media.c.created_at
            rows = [dict(row) for row in conn.execute(query.order_by(sort_at.desc(), media.c.project_id, media.c.id)
                .offset(filters['offset']).limit(filters['limit'])).mappings()]
            keys = [(row['project_id'], row['id']) for row in rows]
            sources, jobs_by_media, target_kinds = {}, {}, {}
            if keys:
                priority = case((refs.c.source_type == 'canvas', 0), (refs.c.source_type == 'job_output', 1),
                    (refs.c.source_type == 'binding', 2), else_=3)
                ranked = select(refs, func.row_number().over(partition_by=(refs.c.project_id, refs.c.media_id),
                    order_by=(priority, refs.c.touched_at.desc(), refs.c.target_id, refs.c.canvas_id)).label('rank'))\
                    .where(tuple_(refs.c.project_id, refs.c.media_id).in_(keys))
                if filters['episode_id']:
                    ranked = ranked.where(refs.c.episode_id == filters['episode_id'])
                ranked = ranked.subquery()
                sources = {(r['project_id'], r['media_id']): dict(r) for r in conn.execute(select(ranked).where(ranked.c.rank == 1)).mappings()}
                targets = {(row['project_id'], row['target_id']) for row in sources.values() if row['target_id']}
                if targets:
                    target_kinds = {(r['project_id'], r['id']): r['kind'] for r in conn.execute(select(
                        S.creative_objects.c.project_id, S.creative_objects.c.id, S.creative_objects.c.kind).where(
                            tuple_(S.creative_objects.c.project_id, S.creative_objects.c.id).in_(targets))).mappings()}
                j, o = S.generation_jobs, S.job_outputs
                ranked_jobs = select(j.c.project_id, o.c.media_id, j.c.id, j.c.shot_id, j.c.asset_id,
                    func.row_number().over(partition_by=(j.c.project_id, o.c.media_id),
                        order_by=(j.c.created_at.desc(), j.c.id)).label('rank')).join(o, and_(o.c.project_id == j.c.project_id, o.c.job_id == j.c.id))\
                    .where(tuple_(j.c.project_id, o.c.media_id).in_(keys), j.c.status == 'succeeded')
                ranked_jobs = ranked_jobs.subquery()
                jobs_by_media = {(r['project_id'], r['media_id']): dict(r) for r in conn.execute(select(ranked_jobs)
                    .where(ranked_jobs.c.rank == 1)).mappings()}
            items = []
            for row in rows:
                key = row['project_id'], row['id']
                source, job = sources.get(key), jobs_by_media.get(key)
                episode_id = filters['episode_id'] or (row['single_episode_id'] if row['episode_count'] == 1 else None)
                item = {key: row[key] for key in ('id', 'project_id', 'project_name', 'name', 'modality', 'created_at', 'updated_at')}
                item.update(content_url='/api/v1/projects/' + row['project_id'] + '/media/' + row['id'] + '/content',
                    episode_id=episode_id, episode_count=row['episode_count'] or 0, source_href=None, reuse_href=None,
                    source_job_id=job['id'] if job else None)
                if source:
                    target_kind = target_kinds.get((row['project_id'], source['target_id']))
                    page = ('creative-canvas' if source['canvas_id'] else 'assets' if source['source_type'] == 'episode_asset'
                        or target_kind == 'asset' else 'classic-production' if target_kind == 'shot'
                        and row['modality'] in {'image', 'video'} else 'workbench')
                    params = {'page': page, 'project': row['project_id']}
                    if source['canvas_id']:
                        params['task_target'] = source['canvas_id']
                    elif source['target_id']:
                        params['scope'] = source['target_id']
                    if source['episode_id']:
                        params['episode'] = source['episode_id']
                    if page == 'classic-production':
                        params['kind'] = 'image' if row['modality'] == 'image' else 'video'
                    item['source_href'] = '/?' + urlencode(params)
                if job and job['shot_id'] and row['modality'] in {'image', 'video'}:
                    try:
                        configuration = self.configuration(row['project_id'], job['shot_id'], row['id'])
                    except ResourceError:
                        configuration = None
                    if (configuration and configuration.get('available') and configuration.get('source_job_id') == job['id']
                            and configuration.get('configuration_source') == 'fixed_workbench_draft'):
                        item['reuse_href'] = '/?' + urlencode({'page': 'classic-production', 'project': row['project_id'],
                            'scope': job['shot_id'], 'kind': row['modality'], 'reuse_media': row['id']})
                items.append(item)
            following = filters['offset'] + len(items)
            return clean({'items': items, 'total': total, 'offset': filters['offset'], 'limit': filters['limit'],
                'next_offset': following if following < total else None})
