"""Read and append project display choices under the original project transaction."""
from sqlalchemy import insert, select
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id, clean, new_id


def cover_selection(conn, project_id):
    row = conn.execute(select(S.project_cover_versions).where(
        S.project_cover_versions.c.project_id == project_id).order_by(
            S.project_cover_versions.c.version.desc()).limit(1)).mappings().first()
    return dict(row) if row else None


def project_cover(conn, project_id, selection=None):
    from .project_presentation import media_cover
    selection = cover_selection(conn, project_id) if selection is None else selection
    if selection and selection['media_id']:
        from .media_recycle import recycled_ids
        # A deliberate display choice is independent of automatic cover heuristics.
        row = conn.execute(select(S.media_items.c.id, S.media_items.c.modality).where(
            S.media_items.c.project_id == project_id, S.media_items.c.id == selection['media_id'],
            S.media_items.c.modality == 'image',
            S.media_items.c.id.not_in(recycled_ids(project_id)))).mappings().first()
        return (dict(media_id=row['id'], modality=row['modality'],
            content_url='/api/v1/projects/'+project_id+'/media/'+row['id']+'/content') if row else None)
    return media_cover(conn, project_id)


class ProjectCoverRepository:
    def get_project_cover(self, project_id):
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
            project = self._project(conn, checked_id(project_id))
            self._access_require(conn, project['id'], 'read')
            selection = cover_selection(conn, project['id'])
            return clean(dict(project_id=project['id'], revision=project['revision'], selection=selection,
                cover=project_cover(conn, project['id'], selection)))

    def set_project_cover(self, project_id, payload, *, check_media, **kw):
        def work(conn, project):
            p = project['id']; media = None
            if payload['media_id'] is not None:
                media = self._media(conn, p, checked_id(payload['media_id']))
                lifecycle = self._latest(conn, S.media_lifecycle_decisions, p, 'media_id', media['id'])
                if lifecycle and lifecycle['outcome'] == 'deprecate':
                    raise ResourceError('回收或停用的媒体不能设置为封面', 'project_cover_media_unavailable', 409)
                check_media(media)
            previous = cover_selection(conn, p)
            row = conn.execute(insert(S.project_cover_versions).values(project_id=p, id=new_id(),
                version=previous['version']+1 if previous else 1,
                media_id=media['id'] if media else None, blob_id=media['blob_id'] if media else None,
                sha256=media['sha256'] if media else None, created_by=kw['actor'], command_key=kw['idempotency_key'])
                .returning(S.project_cover_versions)).mappings().one()
            return dict(selection=dict(row), cover=project_cover(conn, p, row))
        return self._mutate(project_id, 'set_project_cover', payload, callback=work, **kw)
