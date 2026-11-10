"""Read-only, authorized canvas directory; original canvases remain authoritative."""
from sqlalchemy import and_, exists, false, func, select, tuple_

from . import schema as S
from .access_control import authority_lock
from .values import clean


class CanvasLibrary:
    def __init__(self, store):
        self.store = store

    def _scope(self, conn):
        projects = S.projects
        active = ~exists(select(1).where(S.management_project_states.c.project_id == projects.c.id,
            S.management_project_states.c.state != 'active'))
        read = self.store._access_project_query(conn, 'read').where(active).cte('canvas_readable_projects')
        edit = self.store._access_project_query(conn, 'edit').where(active).cte('canvas_editable_projects')
        manage = self.store._access_project_query(conn, 'manage').where(active).cte('canvas_managed_projects')
        return read, edit, manage

    @staticmethod
    def _canvases(read):
        c, v, p, ep, obj, states = (S.creative_canvases, S.creative_canvas_versions, S.projects,
            S.episodes, S.creative_objects, S.management_object_states)
        person = S.access_identities
        return select(c.c.id, c.c.project_id, p.c.name.label('project_name'), c.c.episode_id,
            obj.c.title.label('episode_name'), v.c.title, v.c.version.label('canvas_revision'),
            v.c.id.label('version_id'), v.c.created_at.label('updated_at'),
            c.c.created_by.label('creator_id'), func.coalesce(person.c.display_name, c.c.created_by).label('creator_name'))\
            .select_from(c.join(v, and_(v.c.project_id == c.c.project_id, v.c.id == c.c.current_version_id))
                .join(p, p.c.id == c.c.project_id)
                .outerjoin(ep, and_(ep.c.project_id == c.c.project_id, ep.c.id == c.c.episode_id))
                .outerjoin(obj, and_(obj.c.project_id == ep.c.project_id, obj.c.id == ep.c.id))
                .outerjoin(person, person.c.actor == c.c.created_by))\
            .where(c.c.project_id.in_(select(read.c.id)),
                ~exists(select(1).where(states.c.project_id == c.c.project_id, states.c.state != 'active',
                    states.c.object_id.in_((c.c.episode_id, ep.c.parent_id)))),
                ~exists(select(1).where(S.management_canvas_states.c.project_id == c.c.project_id,
                    S.management_canvas_states.c.canvas_id == c.c.id, S.management_canvas_states.c.state != 'active')))

    @staticmethod
    def _covers(conn, rows):
        """One batch, bounded by the current page's fixed versions and node limits."""
        if not rows:
            return {}
        n, m, life, actions = S.creative_canvas_nodes, S.media_items, S.media_lifecycle_decisions, S.media_recycle_actions
        candidates = select(n.c.project_id, n.c.version_id, n.c.ordinal, m.c.id.label('media_id')).join(m,
            and_(m.c.project_id == n.c.project_id, m.c.id == n.c.media_id)).where(
                tuple_(n.c.project_id, n.c.version_id).in_([(r['project_id'], r['version_id']) for r in rows]),
                m.c.modality == 'image').cte('canvas_cover_candidates')
        latest = select(life.c.project_id, life.c.media_id, life.c.id, life.c.outcome,
            func.row_number().over(partition_by=(life.c.project_id, life.c.media_id),
                order_by=life.c.decision_sequence.desc()).label('rank')).where(
                    tuple_(life.c.project_id, life.c.media_id).in_(select(candidates.c.project_id,
                        candidates.c.media_id))).cte('canvas_cover_lifecycle')
        recycled = exists(select(1).select_from(latest.join(actions, and_(
            actions.c.project_id == latest.c.project_id, actions.c.decision_id == latest.c.id)))
            .where(latest.c.project_id == candidates.c.project_id, latest.c.media_id == candidates.c.media_id,
                latest.c.rank == 1, latest.c.outcome == 'deprecate'))
        ranked = select(candidates, func.row_number().over(
            partition_by=(candidates.c.project_id, candidates.c.version_id),
            order_by=(candidates.c.ordinal, candidates.c.media_id)).label('rank')).where(~recycled).subquery()
        return {(r['project_id'], r['version_id']): '/api/v1/projects/' + r['project_id'] + '/media/' + r['media_id'] + '/content'
            for r in conn.execute(select(ranked).where(ranked.c.rank == 1)).mappings()}

    def options(self):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            authority_lock(conn)
            read, edit, _ = self._scope(conn)
            p = S.projects
            projects = [dict(id=r.id, name=r.name, permissions={'can_edit': r.can_edit}) for r in conn.execute(
                select(p.c.id, p.c.name, p.c.id.in_(select(edit.c.id)).label('can_edit'))
                    .where(p.c.id.in_(select(read.c.id))).order_by(p.c.name, p.c.id))]
            visible = self._canvases(read).subquery()
            creators = [dict(id=r.creator_id, name=r.creator_name) for r in conn.execute(
                select(visible.c.creator_id, visible.c.creator_name).distinct()
                    .order_by(visible.c.creator_name, visible.c.creator_id))]
            return clean({'projects': projects, 'creators': creators})

    def search(self, filters):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            authority_lock(conn)
            read, edit, manage = self._scope(conn)
            principal, person, _ = self.store._access_principal(conn)
            query = self._canvases(read)
            c = S.creative_canvases
            if filters['project_id']:
                self.store._access_require(conn, filters['project_id'], 'read')
                query = query.where(c.c.project_id == filters['project_id'])
            if filters['episode_id']:
                self.store._one(conn, S.episodes, filters['project_id'], filters['episode_id'])
                query = query.where(c.c.episode_id == filters['episode_id'])
            if filters['creator_filter'] == 'mine':
                query = query.where(c.c.created_by == person['actor'] if person else false())
            elif filters['creator_filter'] == 'member':
                query = query.where(c.c.created_by == filters['creator_id'])
            can_edit = c.c.project_id.in_(select(edit.c.id))
            if filters['permission'] == 'edit':
                query = query.where(can_edit)
            elif filters['permission'] == 'view':
                query = query.where(~can_edit)
            if filters['query']:
                pattern = '%' + filters['query'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                query = query.where(S.creative_canvas_versions.c.title.ilike(pattern, escape='\\'))
            total = conn.scalar(select(func.count()).select_from(query.subquery()))
            at = S.creative_canvas_versions.c.created_at
            order = at.desc() if filters['order'] == 'updated_desc' else at.asc()
            rows = [dict(r) for r in conn.execute(query.add_columns(can_edit.label('can_edit'),
                c.c.project_id.in_(select(manage.c.id)).label('can_manage')).order_by(order, c.c.project_id, c.c.id)
                .offset(filters['offset']).limit(filters['limit'])).mappings()]
            covers = self._covers(conn, rows)
            for row in rows:
                edit, manage = row.pop('can_edit'), row.pop('can_manage')
                row['permissions'] = dict(can_read=True, can_edit=edit, can_rename=edit, can_copy=edit,
                    can_delete=manage, can_manage_collaboration=False)
                row['cover_url'] = covers.get((row['project_id'], row['version_id']))
            following = filters['offset'] + len(rows)
            return clean(dict(items=rows, total=total, offset=filters['offset'], limit=filters['limit'],
                next_offset=following if following < total else None))
