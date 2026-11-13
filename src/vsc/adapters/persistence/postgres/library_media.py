"""Reversible media visibility and explicit, reference-aware physical cleanup.

Fixed library snapshots remain immutable. A lifecycle applies to one typed
version/member, including any explicit official backup links to that member.
"""
from urllib.parse import quote

from sqlalchemy import select, insert, update, exists, and_, or_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import ResourceError, Conflict, NotFound
from . import schema as S
from .values import clean, digest, new_id


def available_member(version_column, key_column):
    s = S.library_media_states
    return ~exists(select(1).where(s.c.library_version_id == version_column,
        s.c.member_key == key_column, s.c.state != 'active'))


def require_available(conn, version_id, member_key):
    state = conn.execute(select(S.library_media_states.c.state).where(
        S.library_media_states.c.library_version_id == version_id,
        S.library_media_states.c.member_key == member_key)).scalar_one_or_none()
    if state and state != 'active':
        raise ResourceError('此媒体已移入回收站或彻底删除，请刷新后选择其他媒体', 'library_media_deleted', 409)


class LibraryMediaRepository:
    def __init__(self, store, storage):
        self.store, self.storage = store, storage

    @staticmethod
    def publisher(actor):
        from .asset_center import AssetCenterRepository
        AssetCenterRepository._official_publisher(actor)

    def detail(self, entry_id, actor):
        from .shared_library import SharedLibraryRepository
        library = SharedLibraryRepository(self.store, self.storage)
        with self.store.engine.connect() as conn:
            publications = conn.execute(select(S.official_asset_publications).where(
                S.official_asset_publications.c.entry_id == entry_id).order_by(
                S.official_asset_publications.c.created_at.desc(), S.official_asset_publications.c.id.desc())).mappings().all()
            if not publications:
                raise NotFound('官方资产不存在')
            primary_id = publications[0]['library_version_id']
            row = library._detail(conn, primary_id)
            versions = list(conn.execute(select(S.library_entry_versions.c.id).where(
                S.library_entry_versions.c.entry_id == entry_id).order_by(S.library_entry_versions.c.version.desc())).scalars())
            links = list(conn.execute(select(S.official_asset_backups).where(
                S.official_asset_backups.c.entry_id == entry_id).order_by(
                S.official_asset_backups.c.created_at, S.official_asset_backups.c.library_version_id,
                S.official_asset_backups.c.member_key)).mappings())
            ordered = list(dict.fromkeys([primary_id, *versions, *[r['library_version_id'] for r in links]]))
            linked = {(r['library_version_id'], r['member_key']) for r in links}
            own = set(versions)
            media = library._members(conn, ordered)
            media.sort(key=lambda m: (ordered.index(m['library_version_id']), m['ordinal']))
            gallery = []
            states = {(r['library_version_id'], r['member_key']): r for r in conn.execute(
                select(S.library_media_states).where(S.library_media_states.c.library_version_id.in_(ordered))).mappings()}
            for m in media:
                key = (m['library_version_id'], m['member_key'])
                state = states.get(key, {})
                if m['library_version_id'] not in own and key not in linked:
                    continue
                if state.get('state', 'active') != 'active':
                    continue
                gallery.append(dict(library._public_member(m), library_version_id=m['library_version_id'],
                    revision=state.get('revision', 0)))
            try:
                self.publisher(actor)
                can_manage = True
            except ResourceError as error:
                if error.code != 'official_publisher_required':
                    raise
                can_manage = False
            return dict(row, source='official', official=clean(dict(publications[0])), gallery=gallery, can_manage_media=can_manage)

    def attach_backup(self, payload, actor):
        self.publisher(actor)
        with self.store.engine.begin() as conn:
            if not conn.execute(select(S.official_asset_publications.c.id).where(
                    S.official_asset_publications.c.entry_id == payload['entry_id']).limit(1)).first():
                raise NotFound('目标官方资产不存在')
            member = conn.execute(select(S.library_version_media).where(
                S.library_version_media.c.library_version_id == payload['library_version_id'],
                S.library_version_media.c.member_key == payload['member_key'])).mappings().first()
            if not member:
                raise NotFound('备份媒体不存在')
            conn.execute(pg_insert(S.official_asset_backups).values(**payload, actor=actor).on_conflict_do_nothing())
        return {'attached': True}

    def recycle(self, actor, offset=0, limit=24):
        self.publisher(actor)
        s, m, v = S.library_media_states, S.library_version_media, S.library_entry_versions
        query = select(s, v.c.title, m.c.modality).join(m, and_(m.c.library_version_id == s.c.library_version_id,
            m.c.member_key == s.c.member_key)).join(v, v.c.id == s.c.library_version_id).where(or_(s.c.state == 'trashed', s.c.cleanup_pending))
        with self.store.engine.connect() as conn:
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = clean([dict(r) for r in conn.execute(query.order_by(s.c.changed_at.desc(), s.c.library_version_id,
                s.c.member_key).offset(offset).limit(limit)).mappings()])
        for r in rows:
            r['preview_url'] = '/api/v1/asset-center/official/recycle/content/' + r['library_version_id'] + '/' + quote(r['member_key'], safe='') if r['state'] == 'trashed' else None
        return {'items': rows, 'total': total, 'offset': offset, 'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def recycle_content(self, version_id, member_key, actor):
        self.publisher(actor)
        from .shared_library import SharedLibraryRepository
        lib = SharedLibraryRepository(self.store, self.storage)
        with self.store.engine.connect() as conn:
            state = conn.execute(select(S.library_media_states.c.state).where(
                S.library_media_states.c.library_version_id == version_id,
                S.library_media_states.c.member_key == member_key)).scalar_one_or_none()
            if state != 'trashed':
                raise NotFound('回收媒体不存在')
            member = next((m for m in lib._members(conn, version_id) if m['member_key'] == member_key), None)
            if not member:
                raise NotFound('回收媒体不存在')
            return lib._verify(member), member['mime_type']

    def command(self, payload, actor):
        self.publisher(actor)
        from .shared_library import SharedLibraryRepository
        lib = SharedLibraryRepository(self.store, self.storage)
        s, a, m = S.library_media_states, S.library_media_actions, S.library_version_media
        version_id, key, operation = (payload[k] for k in ('library_version_id', 'member_key', 'operation'))
        request_sha = digest(payload)
        with self.store.engine.begin() as conn:
            lib._lock_key(conn, 'media-command:' + actor + ':' + payload['command_key'])
            previous = conn.execute(select(a).where(a.c.actor == actor, a.c.command_key == payload['command_key'])).mappings().first()
            if previous:
                if previous['request_sha256'] != request_sha:
                    raise Conflict('原操作标识已用于其他输入', 'idempotency_conflict')
                result = clean(dict(previous))
            else:
                version = conn.execute(select(S.library_entry_versions).where(S.library_entry_versions.c.id == version_id)).mappings().first()
                if not version:
                    raise NotFound('库版本不存在')
                # Same lock order as fixed-reference adoption: entry then member.
                conn.execute(select(S.library_entries.c.id).where(S.library_entries.c.id == version['entry_id']).with_for_update()).one()
                lib._lock_key(conn, 'media:' + version_id + ':' + key)
                eligible = or_(exists(select(1).where(S.official_asset_publications.c.entry_id == version['entry_id'])),
                    exists(select(1).where(S.official_asset_backups.c.library_version_id == version_id, S.official_asset_backups.c.member_key == key)))
                member = conn.execute(select(m).where(m.c.library_version_id == version_id, m.c.member_key == key, eligible)).mappings().first()
                if not member:
                    raise NotFound('官方资产媒体不存在')
                state = conn.execute(select(s).where(s.c.library_version_id == version_id, s.c.member_key == key)).mappings().first()
                revision, current = (state['revision'], state['state']) if state else (0, 'active')
                if revision != payload['expected_revision']:
                    raise Conflict('媒体状态已改变，请刷新后重试', 'revision_conflict')
                if current == 'purged' or operation in {'restore', 'purge'} and current != 'trashed' or operation == 'trash' and current != 'active':
                    raise Conflict('当前状态不允许此操作', 'media_state_conflict')
                desired = {'trash': 'trashed', 'restore': 'active', 'purge': 'purged'}[operation]
                result = dict(id=new_id(), library_version_id=version_id, member_key=key, operation=operation,
                    revision=revision + 1, actor=actor, reason=payload['reason'], command_key=payload['command_key'], request_sha256=request_sha)
                conn.execute(insert(a).values(**result))
                values = dict(library_version_id=version_id, member_key=key, state=desired, revision=revision + 1,
                    actor=actor, reason=payload['reason'], changed_at=func.now(), cleanup_pending=operation == 'purge')
                if state:
                    conn.execute(update(s).where(s.c.library_version_id == version_id, s.c.member_key == key).values(**values))
                else:
                    conn.execute(insert(s).values(**values))
                if operation != 'restore':
                    conn.execute(update(S.library_cart_items).where(S.library_cart_items.c.library_version_id == version_id,
                        S.library_cart_items.c.member_key == key).values(active=False))
        # Persist the irreversible tombstone before touching files. A replay of
        # the original command resumes cleanup after a crash or storage error.
        return dict(result, **(self._cleanup(version_id, key) if operation == 'purge' else {}))

    def _cleanup(self, version_id, key):
        if self.storage is None:
            return {'cleanup_pending': True, 'bytes_removed': False}
        m, s = S.library_version_media, S.library_media_states
        with self.store.engine.begin() as conn:
            member = conn.execute(select(m).where(m.c.library_version_id == version_id, m.c.member_key == key)).mappings().first()
            if not member:
                raise NotFound('媒体成员不存在')
            # FOR UPDATE conflicts with new FK references to this shared blob.
            conn.execute(select(S.media_blobs.c.id).where(S.media_blobs.c.id == member['blob_id']).with_for_update()).one()
            state = conn.execute(select(s).where(s.c.library_version_id == version_id, s.c.member_key == key).with_for_update()).mappings().first()
            if not state or state['state'] != 'purged':
                raise Conflict('只有已确认彻底删除的图片可以继续清理', 'media_state_conflict')
            if not state['cleanup_pending']:
                return {'cleanup_pending': False, 'bytes_removed': not bool(conn.execute(select(S.blob_locations.c.id).where(
                    S.blob_locations.c.blob_id == member['blob_id'], S.blob_locations.c.available).limit(1)).first())}
            shared = conn.execute(select(m.c.member_key).where(m.c.blob_id == member['blob_id'],
                ~exists(select(1).where(s.c.library_version_id == m.c.library_version_id,
                    s.c.member_key == m.c.member_key, s.c.state == 'purged'))).limit(1)).first()
            used = conn.execute(select(S.media_items.c.id).where(S.media_items.c.blob_id == member['blob_id']).limit(1)).first()
            if shared or used:
                conn.execute(update(s).where(s.c.library_version_id == version_id, s.c.member_key == key).values(cleanup_pending=False))
                return {'cleanup_pending': False, 'bytes_removed': False, 'shared_bytes_retained': True}
            locations = list(conn.execute(select(S.blob_locations).where(S.blob_locations.c.blob_id == member['blob_id'],
                S.blob_locations.c.available)).mappings())
            if any(r['storage'] != 'local' for r in locations):
                return {'cleanup_pending': True, 'bytes_removed': False}
            try:
                for location in locations:
                    self.storage.resolve(location['object_key']).unlink(missing_ok=True)
            except OSError:
                return {'cleanup_pending': True, 'bytes_removed': False}
            conn.execute(update(S.blob_locations).where(S.blob_locations.c.blob_id == member['blob_id']).values(available=False))
            conn.execute(update(s).where(s.c.library_version_id == version_id, s.c.member_key == key).values(cleanup_pending=False))
            return {'cleanup_pending': False, 'bytes_removed': True}
