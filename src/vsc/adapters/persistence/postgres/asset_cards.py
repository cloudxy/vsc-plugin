"""Asset card commands compose original objects, artifact projections and media registrations."""
from datetime import datetime, timezone
import json
from sqlalchemy import select, insert, update, delete, func, and_, or_, case, exists, literal, cast, Text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.resource_service import ResourceError, Conflict
from . import schema as S
from .values import checked_id, new_id, clean


class AssetCardsRepository:
    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        return getattr(self.store, name)

    def _legacy_preview(self, conn, p, asset_id, asset_kind, usability_cache):
        # This is a card-level display hint, never a form or production binding.
        # Prefer an identity master over secondary views; within a role prefer
        # the newest current selection, then use IDs as a deterministic tie-break.
        roles = {
            "character": ("identity_face", "costume"),
            "location": ("location_master", "location_view"),
            "style": ("style_reference",),
            "costume": ("costume",),
            "prop": ("prop",),
            "object": ("prop",),
            "creature": ("prop",),
            "vehicle": ("prop",),
            "plant": ("prop",),
        }.get(asset_kind, ())
        if not roles:
            return None
        slots, current, candidates, decisions, media = (
            S.binding_slots,
            S.current_bindings,
            S.binding_candidates,
            S.binding_decisions,
            S.media_items,
        )
        lifecycle = (
            select(S.media_lifecycle_decisions.c.outcome)
            .where(
                S.media_lifecycle_decisions.c.project_id == p,
                S.media_lifecycle_decisions.c.media_id == media.c.id,
            )
            .order_by(S.media_lifecycle_decisions.c.decision_sequence.desc())
            .limit(1)
            .scalar_subquery()
        )
        available = (
            select(S.blob_locations.c.id)
            .where(
                S.blob_locations.c.blob_id == media.c.blob_id,
                S.blob_locations.c.available.is_(True),
            )
            .exists()
        )
        query = (
            select(
                slots.c.id.label('slot_id'),
                slots.c.role,
                slots.c.slot_key,
                slots.c.variant_spec_id,
                candidates.c.id.label('candidate_id'),
                candidates.c.media_id,
                candidates.c.spec_version_id,
                decisions.c.id.label('decision_id'),
                decisions.c.decision_sequence,
            )
            .select_from(
                slots.join(current, and_(current.c.project_id == slots.c.project_id, current.c.slot_id == slots.c.id))
                .join(
                    candidates,
                    and_(
                        candidates.c.project_id == current.c.project_id,
                        candidates.c.slot_id == current.c.slot_id,
                        candidates.c.id == current.c.candidate_id,
                    ),
                )
                .join(
                    decisions,
                    and_(
                        decisions.c.project_id == current.c.project_id,
                        decisions.c.slot_id == current.c.slot_id,
                        decisions.c.candidate_id == current.c.candidate_id,
                        decisions.c.id == current.c.decision_id,
                    ),
                )
                .join(media, and_(media.c.project_id == candidates.c.project_id, media.c.id == candidates.c.media_id))
            )
            .where(
                slots.c.project_id == p,
                slots.c.target_object_id == asset_id,
                slots.c.role.in_(roles),
                media.c.modality == 'image',
                decisions.c.outcome == 'select',
                func.coalesce(lifecycle, '') != 'deprecate',
                available,
            )
            .order_by(
                case({role: index for index, role in enumerate(roles)}, value=slots.c.role),
                decisions.c.decision_sequence.desc(),
                slots.c.id,
                candidates.c.id,
            )
        )
        for row in conn.execute(query).mappings():
            if row['spec_version_id'] and not self._artifact_approved(conn, p, row['spec_version_id']):
                continue
            key = (row['media_id'], row['role'])
            if key not in usability_cache:
                _, gaps = self._usable(conn, p, *key)
                usability_cache[key] = not gaps
            if not usability_cache[key]:
                continue
            return dict(
                media_id=row['media_id'],
                source='current_binding',
                slot_id=row['slot_id'],
                slot_key=row['slot_key'],
                role=row['role'],
                variant_spec_id=row['variant_spec_id'],
                candidate_id=row['candidate_id'],
                decision_id=row['decision_id'],
            )
        return None

    def _voice_meta(self, conn, p, voice_spec_id):
        if not voice_spec_id:
            return None, ''
        row = conn.execute(
            select(S.voice_spec_versions.c.reference_media_id, S.voice_spec_versions.c.diction)
            .where(S.voice_spec_versions.c.project_id == p, S.voice_spec_versions.c.id == voice_spec_id)
        ).mappings().first()
        if not row:
            return None, ''
        diction = row['diction'] if isinstance(row['diction'], dict) else {}
        return row['reference_media_id'], str(diction.get('description', '') or '')

    def _asset_card(self, conn, p, asset_id, actor=None, include_preview=False, usability_cache=None):
        from .project_management import hidden_object_ids
        asset = self._one(conn, S.asset_identities, p, asset_id)
        if asset_id in hidden_object_ids(conn, p):
            raise ResourceError('此资产已移入回收', 'object_recycled', 409)
        obj = self._one(conn, S.creative_objects, p, asset_id)
        state = conn.execute(
            select(S.asset_card_states).where(
                S.asset_card_states.c.project_id == p, S.asset_card_states.c.asset_id == asset_id
            )
        ).mappings().first()
        folder_id = conn.execute(
            select(S.object_folder_memberships.c.folder_id).where(
                S.object_folder_memberships.c.project_id == p, S.object_folder_memberships.c.object_id == asset_id
            )
        ).scalar_one_or_none()
        rows = []
        latest_updated_at = obj['created_at']
        for form in conn.execute(
            select(S.asset_card_forms)
            .where(S.asset_card_forms.c.project_id == p, S.asset_card_forms.c.asset_id == asset_id)
            .order_by(S.asset_card_forms.c.created_at, S.asset_card_forms.c.id)
        ).mappings():
            fixed = self._one(conn, S.asset_card_form_versions, p, form['current_version_id'])
            if fixed.get('created_at') and (not latest_updated_at or fixed['created_at'] > latest_updated_at):
                latest_updated_at = fixed['created_at']
            spec = self._one(conn, S.asset_spec_versions, p, fixed['spec_id'])
            artifact = self._one(conn, S.artifact_versions, p, spec['artifact_id'])
            doc = json.loads(bytes(artifact['document']))
            body = next((x for x in doc.get('asset_specs', []) if x['id'] == spec['id']), {})
            history = [
                dict(v)
                for v in conn.execute(
                    select(
                        S.asset_card_form_versions.c.id,
                        S.asset_card_form_versions.c.version,
                        S.asset_card_form_versions.c.form_name,
                        S.asset_card_form_versions.c.media_id,
                    )
                    .where(
                        S.asset_card_form_versions.c.project_id == p,
                        S.asset_card_form_versions.c.form_id == form['id'],
                    )
                    .order_by(S.asset_card_form_versions.c.version.desc())
                ).mappings()
            ]
            voice_media_id, voice_prompt = self._voice_meta(conn, p, fixed['voice_spec_id'])
            rows.append(
                dict(
                    form,
                    version_id=fixed['id'],
                    version=fixed['version'],
                    spec_id=spec['id'],
                    description=body.get('description', ''),
                    media_id=fixed['media_id'],
                    voice_spec_id=fixed['voice_spec_id'],
                    voice_reference_media_id=voice_media_id,
                    voice_prompt=voice_prompt,
                    history=history,
                )
            )
        # Existing identities remain visible before the first working card is saved.
        has_working_card = bool(rows)
        if not rows:
            seen = set()
            for spec in conn.execute(
                select(S.asset_spec_versions)
                .join(
                    S.artifact_versions,
                    and_(
                        S.artifact_versions.c.project_id == p,
                        S.artifact_versions.c.id == S.asset_spec_versions.c.artifact_id,
                    ),
                )
                .where(S.asset_spec_versions.c.project_id == p, S.asset_spec_versions.c.asset_id == asset_id)
                .order_by(S.artifact_versions.c.created_at.desc())
            ).mappings():
                if spec['variant_key'] in seen:
                    continue
                seen.add(spec['variant_key'])
                document = json.loads(bytes(self._one(conn, S.artifact_versions, p, spec['artifact_id'])['document']))
                body = next((x for x in document.get('asset_specs', []) if x.get('id') == spec['id']), {})
                rows.append(
                    dict(
                        form_key=spec['variant_key'],
                        name=spec['variant_key'],
                        version_id=None,
                        version=0,
                        spec_id=spec['id'],
                        description=body.get('description', ''),
                        media_id=None,
                        voice_spec_id=None,
                        voice_reference_media_id=None,
                        voice_prompt='',
                        history=[],
                    )
                )
        favorite = (
            conn.execute(
                select(S.asset_card_favorites.c.active).where(
                    S.asset_card_favorites.c.project_id == p,
                    S.asset_card_favorites.c.asset_id == asset_id,
                    S.asset_card_favorites.c.actor == actor,
                )
            ).scalar_one_or_none()
            if actor
            else False
        )
        preview = (
            self._legacy_preview(
                conn,
                p,
                asset_id,
                asset['asset_kind'],
                usability_cache if usability_cache is not None else {},
            )
            if include_preview and not has_working_card
            else None
        )
        return dict(
            id=asset_id,
            name=obj['title'] or obj['display_code'],
            asset_kind=asset['asset_kind'],
            revision=state['revision'] if state else 0,
            folder_id=folder_id,
            updated_at=latest_updated_at,
            forms=rows,
            favorite=bool(favorite),
            preview=preview,
        )

    def _folders_projection(self, conn, p, hidden, asset_kind='', include_object=False, folder_id=''):
        folder_rows = [
            dict(r)
            for r in conn.execute(
                select(
                    S.management_folders.c.id,
                    S.management_folders.c.title,
                    S.management_folders.c.ordinal,
                    S.management_folders.c.created_at,
                )
                .where(S.management_folders.c.project_id == p, S.management_folders.c.parent_id.is_(None))
                .order_by(S.management_folders.c.ordinal, S.management_folders.c.id)
            ).mappings()
        ]
        current_folder = None
        if folder_id and folder_id != 'root':
            found = conn.execute(
                select(
                    S.management_folders.c.id,
                    S.management_folders.c.title,
                    S.management_folders.c.ordinal,
                ).where(S.management_folders.c.project_id == p, S.management_folders.c.id == checked_id(folder_id))
            ).mappings().first()
            if not found:
                raise ResourceError('文件夹不属于当前项目', 'folder_scope')
            current_folder = dict(found)
        if not folder_rows:
            return [], current_folder
        ofm = S.object_folder_memberships
        member_q = (
            select(ofm.c.folder_id, S.asset_identities.c.id.label('asset_id'))
            .join(
                S.asset_identities,
                and_(S.asset_identities.c.project_id == p, S.asset_identities.c.id == ofm.c.object_id),
            )
            .where(ofm.c.project_id == p, S.asset_identities.c.id.not_in(hidden))
        )
        if asset_kind == 'blocking':
            member_q = member_q.where(literal(False))
        elif asset_kind:
            member_q = member_q.where(
                S.asset_identities.c.asset_kind.in_(['prop', 'object'])
                if include_object
                else S.asset_identities.c.asset_kind == asset_kind
            )
        by_folder = {r['id']: [] for r in folder_rows}
        for row in conn.execute(member_q).mappings():
            if row['folder_id'] in by_folder:
                by_folder[row['folder_id']].append(row['asset_id'])
        all_ids = [aid for ids in by_folder.values() for aid in ids]
        cover_by_asset = {}
        if all_ids:
            for row in conn.execute(
                select(S.asset_card_forms.c.asset_id, S.asset_card_form_versions.c.media_id)
                .join(
                    S.asset_card_form_versions,
                    and_(
                        S.asset_card_form_versions.c.project_id == p,
                        S.asset_card_form_versions.c.id == S.asset_card_forms.c.current_version_id,
                    ),
                )
                .where(
                    S.asset_card_forms.c.project_id == p,
                    S.asset_card_forms.c.asset_id.in_(all_ids),
                    S.asset_card_form_versions.c.media_id.is_not(None),
                )
                .order_by(S.asset_card_forms.c.created_at, S.asset_card_forms.c.id)
            ).mappings():
                cover_by_asset.setdefault(row['asset_id'], row['media_id'])
        explicit_covers = {}
        for row in conn.execute(
            select(S.media_folder_memberships.c.folder_id, S.media_folder_memberships.c.media_id)
            .where(S.media_folder_memberships.c.project_id == p)
            .order_by(S.media_folder_memberships.c.id)
        ).mappings():
            explicit_covers.setdefault(row['folder_id'], row['media_id'])
        summary = []
        for f in folder_rows:
            aids = by_folder.get(f['id'], [])
            covers = [cover_by_asset[aid] for aid in aids if aid in cover_by_asset][:4]
            summary.append(
                dict(
                    id=f['id'],
                    title=f['title'],
                    ordinal=f['ordinal'],
                    asset_count=len(aids),
                    cover_media_id=explicit_covers.get(f['id']),
                    cover_media_ids=covers,
                )
            )
        return summary, current_folder

    def _blocking_projection(self, p, hidden):
        """Fixed workflow references only; this creates no asset identity or approval."""
        w, v, u, m = S.intelligent_workflows, S.intelligent_versions, S.intelligent_units, S.intelligent_media
        image, blob = S.media_items, S.media_blobs
        newer = v.alias('newer_workflow_version')
        d, c, slot = S.binding_decisions, S.binding_candidates, S.binding_slots
        ws, wc = S.working_selection_versions, S.binding_candidates.alias('working_candidate')
        shot, sequence, episode_scene = S.shots, S.sequences, S.scenes.alias('working_episode_scene')
        form, ef, ea = S.episode_asset_form_versions, S.episode_asset_forms, S.episode_assets
        export, out, spatial, scene = (
            S.spatial_exports,
            S.spatial_export_outputs,
            S.spatial_scene_versions,
            S.spatial_scenes,
        )
        spatial_episode_scene = S.scenes.alias('spatial_episode_scene')

        def same(a, b):
            return a.c.project_id == b.c.project_id

        decision = exists(
            select(1)
            .select_from(
                d.join(c, and_(same(d, c), d.c.candidate_id == c.c.id)).join(
                    slot, and_(same(c, slot), c.c.slot_id == slot.c.id)
                )
            )
            .where(
                d.c.project_id == p,
                d.c.id == m.c.decision_id,
                d.c.outcome == 'select',
                c.c.media_id == m.c.media_id,
                slot.c.target_object_id.not_in(hidden),
            )
        )
        working = exists(
            select(1)
            .select_from(
                ws.join(wc, and_(same(ws, wc), ws.c.candidate_id == wc.c.id))
                .join(shot, and_(same(ws, shot), ws.c.shot_id == shot.c.id))
                .join(sequence, and_(same(shot, sequence), shot.c.parent_id == sequence.c.id))
                .join(episode_scene, and_(same(sequence, episode_scene), sequence.c.parent_id == episode_scene.c.id))
            )
            .where(
                ws.c.project_id == p,
                ws.c.id == m.c.working_selection_version_id,
                ws.c.output_kind == 'image',
                ws.c.event_kind != 'clear',
                ws.c.shot_id.not_in(hidden),
                episode_scene.c.parent_id == w.c.episode_id,
                wc.c.media_id == m.c.media_id,
            )
        )
        episode_form = exists(
            select(1)
            .select_from(
                form.join(ef, and_(same(form, ef), form.c.form_id == ef.c.id)).join(
                    ea, and_(same(ef, ea), ef.c.episode_asset_id == ea.c.id)
                )
            )
            .where(
                form.c.project_id == p,
                form.c.id == m.c.episode_asset_form_version_id,
                form.c.media_id == m.c.media_id,
                ea.c.episode_id == w.c.episode_id,
                or_(form.c.source_asset_id.is_(None), form.c.source_asset_id.not_in(hidden)),
            )
        )
        spatial_source = exists(
            select(1)
            .select_from(
                export.join(out, and_(same(export, out), out.c.export_id == export.c.id))
                .join(spatial, and_(same(export, spatial), export.c.version_id == spatial.c.id))
                .join(scene, and_(same(spatial, scene), spatial.c.spatial_scene_id == scene.c.id))
                .join(spatial_episode_scene, and_(same(scene, spatial_episode_scene), scene.c.scene_id == spatial_episode_scene.c.id))
            )
            .where(
                export.c.project_id == p,
                export.c.id == m.c.spatial_export_id,
                export.c.format == 'png',
                export.c.status == 'succeeded',
                export.c.version_id == u.c.spatial_version_id,
                out.c.media_id == m.c.media_id,
                out.c.sha256 == blob.c.sha256,
                scene.c.mode == 'blocking',
                scene.c.scene_id.not_in(hidden),
                spatial_episode_scene.c.parent_id == w.c.episode_id,
                or_(scene.c.episode_id.is_(None), scene.c.episode_id == w.c.episode_id),
            )
        )
        lifecycle = (
            select(S.media_lifecycle_decisions.c.outcome)
            .where(
                S.media_lifecycle_decisions.c.project_id == p,
                S.media_lifecycle_decisions.c.media_id == image.c.id,
            )
            .order_by(S.media_lifecycle_decisions.c.decision_sequence.desc())
            .limit(1)
            .scalar_subquery()
        )
        location = exists(
            select(1).where(S.blob_locations.c.blob_id == image.c.blob_id, S.blob_locations.c.available.is_(True))
        )
        key = func.concat('blocking:', cast(v.c.id, Text), ':', u.c.unit_key, ':', cast(m.c.media_id, Text))
        name = func.coalesce(func.nullif(u.c.title, ''), image.c.name)
        source_key = func.coalesce(cast(m.c.spatial_export_id, Text), key)
        rows = (
            select(
                literal('blocking').label('record_kind'),
                key.label('record_id'),
                name.label('name'),
                v.c.created_at.label('updated_at'),
                w.c.id.label('workflow_id'),
                v.c.id.label('version_id'),
                w.c.episode_id.label('episode_id'),
                u.c.unit_key,
                m.c.media_id,
                m.c.spatial_export_id,
                func.row_number()
                .over(
                    partition_by=source_key,
                    order_by=(v.c.created_at.desc(), v.c.id, u.c.unit_key, m.c.media_id),
                )
                .label('source_rank'),
            )
            .select_from(
                w.join(v, and_(same(w, v), v.c.workflow_id == w.c.id))
                .join(u, and_(same(v, u), u.c.version_id == v.c.id))
                .join(m, and_(same(u, m), m.c.version_id == u.c.version_id, m.c.unit_key == u.c.unit_key))
                .join(image, and_(same(m, image), image.c.id == m.c.media_id))
                .join(blob, blob.c.id == image.c.blob_id)
            )
            .where(
                w.c.project_id == p,
                w.c.episode_id.not_in(hidden),
                u.c.kind == 'blocking',
                m.c.purpose == 'blocking',
                or_(u.c.shot_id.is_(None), u.c.shot_id.not_in(hidden)),
                image.c.modality == 'image',
                func.coalesce(lifecycle, '') != 'deprecate',
                location,
                ~exists(select(1).where(newer.c.project_id == p, newer.c.workflow_id == w.c.id, newer.c.version > v.c.version)),
                or_(decision, working, episode_form, spatial_source),
                or_(m.c.spatial_export_id.is_(None), spatial_source),
            )
        )
        return rows.subquery('blocking_projection')

    def _latest_card_timestamp_expr(self, p):
        latest_form = (
            select(func.max(S.asset_card_form_versions.c.created_at))
            .select_from(
                S.asset_card_forms.join(
                    S.asset_card_form_versions,
                    and_(
                        S.asset_card_form_versions.c.project_id == p,
                        S.asset_card_form_versions.c.form_id == S.asset_card_forms.c.id,
                    ),
                )
            )
            .where(
                S.asset_card_forms.c.project_id == p,
                S.asset_card_forms.c.asset_id == S.asset_identities.c.id,
            )
            .correlate(S.asset_identities)
            .scalar_subquery()
        )
        return func.coalesce(latest_form, S.creative_objects.c.created_at)

    def _apply_folder_filter(self, q, p, folder_id):
        ofm = S.object_folder_memberships
        if folder_id == 'root':
            return q.where(
                ~exists(
                    select(1).where(ofm.c.project_id == p, ofm.c.object_id == S.asset_identities.c.id)
                )
            )
        if folder_id:
            fid = checked_id(folder_id)
            return q.where(
                exists(
                    select(1).where(
                        ofm.c.project_id == p,
                        ofm.c.object_id == S.asset_identities.c.id,
                        ofm.c.folder_id == fid,
                    )
                )
            )
        return q

    def list_asset_cards(
        self,
        p,
        query='',
        asset_kind='',
        offset=0,
        limit=24,
        actor=None,
        favorites=False,
        include_object=False,
        include_blocking=False,
        folder_id='',
        order_by='name_asc',
    ):
        from .project_management import hidden_object_ids
        options = {'vsc_readonly_preview': True}
        if include_blocking:
            options['isolation_level'] = 'REPEATABLE READ'
        with self.engine.connect().execution_options(**options) as conn:
            project = self._project(conn, p)
            hidden = hidden_object_ids(conn, p)
            folders, current_folder = self._folders_projection(conn, p, hidden, asset_kind, include_object, folder_id)
            if include_blocking:
                return self._list_with_blocking(
                    conn,
                    project,
                    p,
                    hidden,
                    query,
                    asset_kind,
                    offset,
                    limit,
                    actor,
                    favorites,
                    include_object,
                    folder_id=folder_id,
                    order_by=order_by,
                    folders=folders,
                    current_folder=current_folder,
                )
            updated_expr = self._latest_card_timestamp_expr(p)
            q = (
                select(S.asset_identities.c.id)
                .join(
                    S.creative_objects,
                    and_(
                        S.creative_objects.c.project_id == p,
                        S.creative_objects.c.id == S.asset_identities.c.id,
                    ),
                )
                .where(S.asset_identities.c.project_id == p, S.asset_identities.c.id.not_in(hidden))
            )
            q = self._apply_folder_filter(q, p, folder_id)
            if query:
                q = q.where(S.creative_objects.c.title.ilike('%' + query + '%'))
            if asset_kind:
                q = q.where(
                    S.asset_identities.c.asset_kind.in_(['prop', 'object'])
                    if include_object
                    else S.asset_identities.c.asset_kind == asset_kind
                )
            if favorites:
                q = q.join(
                    S.asset_card_favorites,
                    and_(
                        S.asset_card_favorites.c.project_id == p,
                        S.asset_card_favorites.c.asset_id == S.asset_identities.c.id,
                        S.asset_card_favorites.c.actor == actor,
                        S.asset_card_favorites.c.active,
                    ),
                )
            total = conn.scalar(select(func.count()).select_from(q.subquery()))
            if order_by == 'name_desc':
                ordering = (S.creative_objects.c.title.desc(), S.asset_identities.c.id)
            elif order_by == 'updated_desc':
                ordering = (updated_expr.desc(), S.creative_objects.c.title, S.asset_identities.c.id)
            else:
                ordering = (S.creative_objects.c.title, S.asset_identities.c.id)
            ids = conn.execute(q.order_by(*ordering).offset(offset).limit(limit)).scalars()
            usability_cache = {}
            return clean(
                dict(
                    items=[
                        self._asset_card(conn, p, i, actor, include_preview=True, usability_cache=usability_cache)
                        for i in ids
                    ],
                    folders=folders,
                    current_folder=current_folder,
                    order_by=order_by,
                    total=total,
                    offset=offset,
                    next_offset=offset + limit if offset + limit < total else None,
                    revision=project['revision'],
                )
            )

    def _list_with_blocking(
        self,
        conn,
        project,
        p,
        hidden,
        query,
        asset_kind,
        offset,
        limit,
        actor,
        favorites,
        include_object,
        folder_id='',
        order_by='name_asc',
        folders=None,
        current_folder=None,
    ):
        from .project_management import management_project_guard
        self._access_require(conn, p, 'read')
        management_project_guard(conn, p)
        source_fields = ('workflow_id', 'version_id', 'episode_id', 'unit_key', 'media_id', 'spatial_export_id')
        updated_expr = self._latest_card_timestamp_expr(p)
        identity = (
            select(
                literal('asset').label('record_kind'),
                cast(S.asset_identities.c.id, Text).label('record_id'),
                S.creative_objects.c.title.label('name'),
                updated_expr.label('updated_at'),
                *(cast(literal(None), Text).label(k) for k in source_fields),
            )
            .join(
                S.creative_objects,
                and_(
                    S.creative_objects.c.project_id == p,
                    S.creative_objects.c.id == S.asset_identities.c.id,
                ),
            )
            .where(S.asset_identities.c.project_id == p, S.asset_identities.c.id.not_in(hidden))
        )
        identity = self._apply_folder_filter(identity, p, folder_id)
        if asset_kind == 'blocking':
            identity = identity.where(literal(False))
        elif asset_kind:
            identity = identity.where(
                S.asset_identities.c.asset_kind.in_(['prop', 'object'])
                if include_object
                else S.asset_identities.c.asset_kind == asset_kind
            )
        if favorites:
            identity = identity.join(
                S.asset_card_favorites,
                and_(
                    S.asset_card_favorites.c.project_id == p,
                    S.asset_card_favorites.c.asset_id == S.asset_identities.c.id,
                    S.asset_card_favorites.c.actor == actor,
                    S.asset_card_favorites.c.active,
                ),
            )
        station = self._blocking_projection(p, hidden)
        blocking = select(
            station.c.record_kind,
            station.c.record_id,
            station.c.name,
            station.c.updated_at,
            *(cast(station.c[k], Text).label(k) for k in source_fields),
        ).where(station.c.source_rank == 1)
        if (asset_kind and asset_kind != 'blocking') or favorites or (folder_id and folder_id != 'root'):
            blocking = blocking.where(literal(False))
        combined = union_all(identity, blocking).subquery('project_asset_projection')
        q = select(combined).where(combined.c.name.ilike('%' + query + '%')) if query else select(combined)
        total = conn.scalar(select(func.count()).select_from(q.subquery()))
        if order_by == 'name_desc':
            ordering = (combined.c.name.desc(), combined.c.record_kind, combined.c.record_id)
        elif order_by == 'updated_desc':
            ordering = (combined.c.updated_at.desc(), combined.c.name, combined.c.record_kind, combined.c.record_id)
        else:
            ordering = (combined.c.name, combined.c.record_kind, combined.c.record_id)
        page = conn.execute(q.order_by(*ordering).offset(offset).limit(limit)).mappings().all()
        cache = {}
        media_cache = {}
        grid_cache = {}
        items = []
        for row in page:
            if row['record_kind'] == 'asset':
                items.append(
                    dict(
                        self._asset_card(conn, p, row['record_id'], actor, include_preview=True, usability_cache=cache),
                        record_kind='asset',
                    )
                )
                continue
            source = {k: row[k] for k in source_fields}
            media_id = source['media_id']
            if media_id not in media_cache:
                _, media_cache[media_id] = self._usable(conn, p, media_id, 'reference_image', _grid_cache=grid_cache)
            gaps = media_cache[media_id]
            preview_gaps = [gap for gap in gaps if gap != 'technical_check_missing']
            purpose_gaps = {
                'rights_scope_mismatch',
                'copy_source_rights_scope_mismatch',
                'library_purpose_not_allowed',
                'library_source_rights_changed',
                'grid_source_rights_scope_mismatch',
                'grid_source_copy_source_rights_scope_mismatch',
                'grid_source_library_purpose_not_allowed',
                'grid_source_library_source_rights_changed',
            }
            if preview_gaps and all(gap in purpose_gaps for gap in preview_gaps):
                for purpose in ('first_frame', 'last_frame', 'image_edit', 'identity_face', 'location_master', 'prop'):
                    _, alternate = self._usable(conn, p, media_id, purpose, _grid_cache=grid_cache)
                    if not [gap for gap in alternate if gap != 'technical_check_missing']:
                        preview_gaps = []
                        break
            items.append(
                dict(
                    id=row['record_id'],
                    record_kind='blocking',
                    name=row['name'],
                    asset_kind='blocking',
                    revision=None,
                    folder_id=None,
                    updated_at=row['updated_at'],
                    forms=[],
                    favorite=False,
                    preview=None if preview_gaps else dict(media_id=media_id, source='fixed_workflow'),
                    source=source,
                    availability_gaps=gaps,
                )
            )
        return clean(
            dict(
                items=items,
                folders=folders or [],
                current_folder=current_folder,
                order_by=order_by,
                total=total,
                offset=offset,
                next_offset=offset + limit if offset + limit < total else None,
                revision=project['revision'],
            )
        )

    def get_asset_card(self, p, asset_id, actor=None):
        with self.engine.connect().execution_options(vsc_readonly_preview=True) as conn:
            return clean(
                dict(
                    self._asset_card(conn, p, checked_id(asset_id), actor, include_preview=True),
                    project_revision=self._project(conn, p)['revision'],
                )
            )

    def _save_asset_card(self, conn, project, payload, actor):
        p = project['id']
        identifier = payload.get('asset_id')
        prior = None
        if identifier:
            prior = self._asset_card(conn, p, checked_id(identifier))
            if prior['asset_kind'] != payload['asset_kind']:
                raise ResourceError('资产身份类型不能通过编辑改变')
        if payload['base_revision'] != (prior['revision'] if prior else 0):
            raise Conflict('资产卡已有更新，本机输入保留', 'asset_card_conflict')
        folder_id = payload.get('folder_id')
        if folder_id is not None:
            self._one(conn, S.management_folders, p, checked_id(folder_id))
        if not identifier:
            identifier = self._create_object(
                conn,
                project,
                dict(
                    kind='asset',
                    asset_kind=payload['asset_kind'],
                    display_code='AS-' + new_id()[:8],
                    title=payload['name'],
                ),
            )['id']
        else:
            conn.execute(
                update(S.creative_objects)
                .where(S.creative_objects.c.project_id == p, S.creative_objects.c.id == identifier)
                .values(title=payload['name'])
            )
        if 'folder_id' in payload:
            conn.execute(
                delete(S.object_folder_memberships).where(
                    S.object_folder_memberships.c.project_id == p,
                    S.object_folder_memberships.c.object_id == identifier,
                )
            )
            if folder_id:
                conn.execute(
                    insert(S.object_folder_memberships).values(
                        project_id=p, id=new_id(), object_id=identifier, folder_id=checked_id(folder_id)
                    )
                )
        conn.execute(
            pg_insert(S.asset_card_states)
            .values(project_id=p, id=new_id(), asset_id=identifier, revision=payload['base_revision'] + 1)
            .on_conflict_do_update(
                index_elements=['project_id', 'asset_id'], set_={'revision': payload['base_revision'] + 1}
            )
        )
        result = []
        for supplied in payload['forms']:
            form = conn.execute(
                select(S.asset_card_forms).where(
                    S.asset_card_forms.c.project_id == p,
                    S.asset_card_forms.c.asset_id == identifier,
                    S.asset_card_forms.c.form_key == supplied['form_key'],
                )
            ).mappings().first()
            if supplied.get('base_version_id') != (form['current_version_id'] if form else None):
                raise Conflict('资产形态已有新版本', 'asset_form_conflict')
            form_id = form['id'] if form else new_id()
            spec_id = new_id()
            voice_id = supplied.get('voice_spec_id')
            media = self._media(conn, p, supplied['media_id']) if supplied.get('media_id') else None
            if media and media['modality'] != ('audio' if payload['asset_kind'] == 'voice' else 'image'):
                raise ResourceError('形态素材类型不匹配')
            spec = dict(
                id=spec_id,
                asset_id=identifier,
                variant_key=supplied['form_key'],
                description=supplied.get('description', ''),
            )
            doc = {'asset_specs': [spec]}
            if payload['asset_kind'] == 'voice':
                voice_id = new_id()
                doc['voice_specs'] = [
                    dict(
                        id=voice_id,
                        voice_id=identifier,
                        reference_media_id=media['id'] if media else None,
                        diction=supplied.get('voice_details', {}).get(
                            'diction', {'description': supplied.get('description', '')}
                        ),
                        post_chain=supplied.get('voice_details', {}).get('post_chain', {}),
                    )
                ]
            elif voice_id:
                if payload['asset_kind'] != 'character':
                    raise ResourceError('只有角色可以绑定声线')
                self._one(conn, S.voice_spec_versions, p, voice_id)
                doc['voice_bindings'] = [dict(character_id=identifier, voice_spec_id=voice_id)]
            self._create_artifact(
                conn,
                project,
                dict(
                    artifact_key='asset-card:' + identifier + ':' + supplied['form_key'],
                    artifact_type='asset-bible',
                    document=doc,
                    object_ids=[identifier],
                    **doc,
                ),
            )
            if not form:
                conn.execute(
                    insert(S.asset_card_forms).values(
                        project_id=p,
                        id=form_id,
                        asset_id=identifier,
                        form_key=supplied['form_key'],
                        name=supplied['name'],
                    )
                )
            v = self._one(conn, S.asset_card_form_versions, p, form['current_version_id'])['version'] + 1 if form else 1
            version_id = new_id()
            row = dict(
                project_id=p,
                id=version_id,
                form_id=form_id,
                version=v,
                spec_id=spec_id,
                asset_name=payload['name'],
                form_name=supplied['name'],
                media_id=media['id'] if media else None,
                blob_id=media['blob_id'] if media else None,
                blob_sha256=media['sha256'] if media else None,
                voice_spec_id=voice_id,
                created_by=actor,
            )
            conn.execute(insert(S.asset_card_form_versions).values(**row))
            conn.execute(
                update(S.asset_card_forms)
                .where(S.asset_card_forms.c.project_id == p, S.asset_card_forms.c.id == form_id)
                .values(name=supplied['name'], current_version_id=version_id)
            )
            result.append(
                dict(
                    form_key=supplied['form_key'],
                    version_id=version_id,
                    spec_id=spec_id,
                    media_id=row['media_id'],
                )
            )
        return dict(id=identifier, asset_revision=payload['base_revision'] + 1, forms=result)

    def save_asset_card(self, p, payload, actor, **kw):
        return self._mutate(
            p,
            'save_asset_card',
            payload,
            actor=actor,
            callback=lambda c, pr: self._save_asset_card(c, pr, payload, actor),
            **kw,
        )

    def favorite_asset_card(self, p, payload, actor, **kw):
        def work(conn, project):
            self._one(conn, S.asset_identities, p, payload['asset_id'])
            conn.execute(
                pg_insert(S.asset_card_favorites)
                .values(project_id=p, id=new_id(), asset_id=payload['asset_id'], actor=actor, active=payload['active'])
                .on_conflict_do_update(
                    index_elements=['project_id', 'asset_id', 'actor'], set_={'active': payload['active']}
                )
            )
            return dict(asset_id=payload['asset_id'], active=payload['active'])

        return self._mutate(p, 'favorite_asset_card', payload, actor=actor, callback=work, **kw)

    def reference_asset_card(self, p, payload, actor, **kw):
        def work(conn, project):
            card = self._asset_card(conn, p, payload['asset_id'])
            outputs = []
            if card['revision'] != payload['asset_revision']:
                raise Conflict('源资产已更新，请先读回形态')
            for episode in payload['episode_ids']:
                self._one(conn, S.episodes, p, episode)
                key = 'asset:' + card['id']
                prior = conn.execute(
                    select(S.episode_assets).where(
                        S.episode_assets.c.project_id == p,
                        S.episode_assets.c.episode_id == episode,
                        S.episode_assets.c.asset_key == key,
                    )
                ).mappings().first()
                old = (
                    {
                        r['form_key']: r
                        for r in conn.execute(
                            select(S.episode_asset_forms).where(
                                S.episode_asset_forms.c.project_id == p,
                                S.episode_asset_forms.c.episode_asset_id == prior['id'],
                            )
                        ).mappings()
                    }
                    if prior
                    else {}
                )
                forms = [
                    dict(
                        form_key=f['form_key'],
                        name=old[f['form_key']]['name'] if f['form_key'] in old else f['name'],
                        base_version_id=old.get(f['form_key'], {}).get('current_version_id'),
                        source_asset_id=card['id'],
                        spec_id=f['spec_id'],
                        media_id=f['media_id'],
                    )
                    for f in card['forms']
                    if f.get('spec_id')
                ]
                outputs.append(
                    self.save_episode_asset(
                        p,
                        dict(
                            episode_id=episode,
                            **({'id': prior['id']} if prior else {}),
                            base_revision=prior['revision'] if prior else 0,
                            asset_key=key,
                            name=prior['name'] if prior else card['name'],
                            asset_kind=card['asset_kind'],
                            forms=forms,
                        ),
                        actor=actor,
                        expected_revision=project['revision'],
                        idempotency_key='asset-card-episode',
                        _transaction=(conn, project),
                    )
                )
            return dict(items=outputs)

        return self._mutate(p, 'reference_asset_card', payload, actor=actor, callback=work, **kw)

    def copy_asset_card(self, p, payload, actor, **kw):
        source = checked_id(payload['source_project_id'])

        def work(conn, project):
            original = self._asset_card(conn, source, payload['source_asset_id'])
            requested = payload['form_version_ids']
            forms = []
            media_map = {}
            voice_map = {}

            def copied_media(mid):
                if not mid:
                    return None
                if mid in media_map:
                    return media_map[mid]
                from .copy_lineage import assert_copy_source
                item = self._media(conn, source, mid)
                rights = assert_copy_source(self.store, conn, source, mid)
                if rights and rights['outcome'] not in {'owned', 'licensed', 'unknown'}:
                    raise ResourceError('来源素材权利已限制，不可复制')
                location = next((loc for loc in item['locations'] if loc['available']), None)
                if not location:
                    raise ResourceError('源素材没有可用副本')
                copied = self._register_media(
                    conn,
                    project,
                    dict(
                        item,
                        id=new_id(),
                        storage=location['storage'],
                        object_key=location['object_key'],
                        rights=rights['outcome'] if rights else 'unknown',
                        rights_scope=rights['scope'] if rights else {'purposes': []},
                        rights_expires_at=rights['expires_at'] if rights else None,
                        source={
                            'kind': 'project-asset-copy',
                            'content': {
                                'source_project_id': source,
                                'source_asset_id': original['id'],
                                'source_media_id': mid,
                                'sha256': item['sha256'],
                            },
                        },
                    ),
                    actor,
                )
                media_map[mid] = copied['id']
                return copied['id']

            def copied_voice(vid):
                if not vid:
                    return None
                if vid in voice_map:
                    return voice_map[vid]
                voice = self._one(conn, S.voice_spec_versions, source, vid)
                identity = self._one(conn, S.creative_objects, source, voice['voice_id'])
                saved = self._save_asset_card(
                    conn,
                    project,
                    dict(
                        name=identity['title'] or '复制声线',
                        asset_kind='voice',
                        base_revision=0,
                        forms=[
                            dict(
                                form_key='master',
                                name='默认声线',
                                base_version_id=None,
                                description='从源人物固定声线复制',
                                media_id=copied_media(voice['reference_media_id']),
                                voice_details=dict(diction=voice['diction'], post_chain=voice['post_chain']),
                            )
                        ],
                    ),
                    actor,
                )
                copied = self._one(conn, S.asset_card_form_versions, p, saved['forms'][0]['version_id'])['voice_spec_id']
                voice_map[vid] = copied
                return copied

            for version_id in requested:
                fixed = self._one(conn, S.asset_card_form_versions, source, version_id)
                form = self._one(conn, S.asset_card_forms, source, fixed['form_id'])
                if form['asset_id'] != original['id']:
                    raise ResourceError('复制形态不属于源资产')
                spec = self._one(conn, S.asset_spec_versions, source, fixed['spec_id'])
                doc = json.loads(bytes(self._one(conn, S.artifact_versions, source, spec['artifact_id'])['document']))
                body = next(x for x in doc['asset_specs'] if x['id'] == spec['id'])
                forms.append(
                    dict(
                        form_key=form['form_key'],
                        name=fixed['form_name'],
                        base_version_id=None,
                        description=body.get('description', ''),
                        media_id=copied_media(fixed['media_id']),
                        voice_spec_id=copied_voice(fixed['voice_spec_id']) if original['asset_kind'] == 'character' else None,
                        voice_details=dict(self._one(conn, S.voice_spec_versions, source, fixed['voice_spec_id']))
                        if original['asset_kind'] == 'voice' and fixed['voice_spec_id']
                        else {},
                    )
                )
            result = self._save_asset_card(
                conn,
                project,
                dict(
                    name=payload.get('name') or original['name'],
                    asset_kind=original['asset_kind'],
                    base_revision=0,
                    forms=forms,
                ),
                actor,
            )
            for before, after in zip(requested, result['forms']):
                conn.execute(
                    insert(S.asset_card_copy_sources).values(
                        project_id=p,
                        id=new_id(),
                        target_form_version_id=after['version_id'],
                        source_project_id=source,
                        source_form_version_id=before,
                        created_by=actor,
                    )
                )
            return dict(result, copied_voice_count=len(voice_map))

        from .copy_lineage import source_projects_for_copy
        with self.engine.connect() as c:
            related = source_projects_for_copy(c, source)
        return self._mutate(p, 'copy_asset_card', payload, actor=actor, callback=work, _related_projects=related, **kw)

    def create_asset_folder(self, p, payload, actor, **kw):
        def work(conn, project):
            proj_id = project['id']
            maximum = conn.execute(
                select(func.max(S.management_folders.c.ordinal)).where(
                    S.management_folders.c.project_id == proj_id, S.management_folders.c.parent_id.is_(None)
                )
            ).scalar_one_or_none()
            ordinal = (maximum if maximum is not None else -1) + 1
            fid = new_id()
            conn.execute(
                insert(S.management_folders).values(
                    project_id=proj_id,
                    id=fid,
                    parent_id=None,
                    title=payload['title'],
                    ordinal=ordinal,
                )
            )
            cover_media_id = payload.get('cover_media_id')
            if cover_media_id:
                media = self._media(conn, proj_id, checked_id(cover_media_id))
                if media['modality'] != 'image':
                    raise ResourceError('文件夹封面必须是图像素材')
                conn.execute(
                    delete(S.media_folder_memberships).where(
                        S.media_folder_memberships.c.project_id == proj_id,
                        S.media_folder_memberships.c.media_id == media['id'],
                    )
                )
                conn.execute(
                    insert(S.media_folder_memberships).values(
                        project_id=proj_id, id=new_id(), media_id=media['id'], folder_id=fid
                    )
                )
            folder_obj = dict(id=fid, title=payload['title'], ordinal=ordinal, asset_count=0, cover_media_id=cover_media_id, cover_media_ids=[])
            return dict(folder_id=fid, title=payload['title'], ordinal=ordinal, cover_media_id=cover_media_id, folder=folder_obj)

        return self._mutate(p, 'asset_folder_create', payload, actor=actor, callback=work, **kw)

    def update_asset_folder(self, p, payload, actor, **kw):
        def work(conn, project):
            proj_id = project['id']
            fid = checked_id(payload['folder_id'])
            self._one(conn, S.management_folders, proj_id, fid)
            conn.execute(
                update(S.management_folders)
                .where(S.management_folders.c.project_id == proj_id, S.management_folders.c.id == fid)
                .values(title=payload['title'])
            )
            if 'cover_media_id' in payload:
                conn.execute(
                    delete(S.media_folder_memberships).where(
                        S.media_folder_memberships.c.project_id == proj_id,
                        S.media_folder_memberships.c.folder_id == fid,
                    )
                )
                if payload['cover_media_id']:
                    media = self._media(conn, proj_id, checked_id(payload['cover_media_id']))
                    if media['modality'] != 'image':
                        raise ResourceError('文件夹封面必须是图像素材')
                    conn.execute(
                        delete(S.media_folder_memberships).where(
                            S.media_folder_memberships.c.project_id == proj_id,
                            S.media_folder_memberships.c.media_id == media['id'],
                        )
                    )
                    conn.execute(
                        insert(S.media_folder_memberships).values(
                            project_id=proj_id, id=new_id(), media_id=media['id'], folder_id=fid
                        )
                    )
            folder_obj = dict(id=fid, title=payload['title'], cover_media_id=payload.get('cover_media_id'))
            return dict(folder_id=fid, title=payload['title'], cover_media_id=payload.get('cover_media_id'), folder=folder_obj)

        return self._mutate(p, 'asset_folder_update', payload, actor=actor, callback=work, **kw)

    def delete_asset_folder(self, p, payload, actor, **kw):
        def work(conn, project):
            proj_id = project['id']
            fid = checked_id(payload['folder_id'])
            self._one(conn, S.management_folders, proj_id, fid)
            if conn.execute(
                select(S.management_folders.c.id)
                .where(S.management_folders.c.project_id == proj_id, S.management_folders.c.parent_id == fid)
                .limit(1)
            ).first():
                raise ResourceError('请先移除子目录后再删除此文件夹', 'folder_has_children')
            released_objects = conn.execute(
                delete(S.object_folder_memberships).where(
                    S.object_folder_memberships.c.project_id == proj_id,
                    S.object_folder_memberships.c.folder_id == fid,
                )
            ).rowcount
            conn.execute(
                delete(S.media_folder_memberships).where(
                    S.media_folder_memberships.c.project_id == proj_id,
                    S.media_folder_memberships.c.folder_id == fid,
                )
            )
            conn.execute(
                delete(S.management_folders).where(
                    S.management_folders.c.project_id == proj_id,
                    S.management_folders.c.id == fid,
                )
            )
            return dict(folder_id=fid, released_asset_count=int(released_objects or 0))

        return self._mutate(p, 'asset_folder_delete', payload, actor=actor, callback=work, **kw)

    def move_assets_to_folder(self, p, payload, actor, **kw):
        def work(conn, project):
            from .project_management import hidden_object_ids
            proj_id = project['id']
            hidden = hidden_object_ids(conn, proj_id)
            dest = checked_id(payload['folder_id']) if payload.get('folder_id') else None
            if dest:
                self._one(conn, S.management_folders, proj_id, dest)
            asset_ids = [checked_id(aid) for aid in payload['asset_ids']]
            found = set(
                conn.execute(
                    select(S.asset_identities.c.id).where(
                        S.asset_identities.c.project_id == proj_id,
                        S.asset_identities.c.id.in_(asset_ids),
                    )
                ).scalars()
            )
            if len(found) != len(set(asset_ids)):
                raise ResourceError('跨项目不支持拖拽移动', 'cross_project_move')
            if found & hidden:
                raise ResourceError('选中的资产包含已回收项，请先恢复', 'object_recycled', 409)
            conn.execute(
                delete(S.object_folder_memberships).where(
                    S.object_folder_memberships.c.project_id == proj_id,
                    S.object_folder_memberships.c.object_id.in_(asset_ids),
                )
            )
            if dest:
                for aid in asset_ids:
                    conn.execute(
                        insert(S.object_folder_memberships).values(
                            project_id=proj_id,
                            id=new_id(),
                            object_id=aid,
                            folder_id=dest,
                        )
                    )
            return dict(moved_count=len(asset_ids), folder_id=dest)

        return self._mutate(p, 'asset_folder_move_items', payload, actor=actor, callback=work, **kw)

    def batch_recycle_assets(self, p, payload, actor, **kw):
        def work(conn, project):
            from .project_management import management_project_guard
            proj_id = project['id']
            management_project_guard(conn, proj_id)
            asset_ids = [checked_id(aid) for aid in payload['asset_ids']]
            found = set(
                conn.execute(
                    select(S.asset_identities.c.id).where(
                        S.asset_identities.c.project_id == proj_id,
                        S.asset_identities.c.id.in_(asset_ids),
                    )
                ).scalars()
            )
            if len(found) != len(set(asset_ids)):
                raise ResourceError('部分资产不属于当前项目', 'asset_scope')
            recycled_ids = []
            protected = []
            now = datetime.now(timezone.utc)
            for aid in asset_ids:
                ids = self._descendant_ids(conn, proj_id, aid)
                reasons = self._management_protections(conn, proj_id, ids, permanent=False, whole=False)
                if reasons:
                    protected.append({'asset_id': aid, 'reasons': reasons})
                    continue
                old = conn.execute(
                    select(S.management_object_states).where(
                        S.management_object_states.c.project_id == proj_id,
                        S.management_object_states.c.object_id == aid,
                    )
                ).mappings().first()
                if old and old['state'] == 'purged':
                    raise ResourceError('此资产已永久停用', 'object_purged', 409)
                values = {'state': 'trashed', 'reason': payload['reason'], 'actor': actor, 'changed_at': now}
                if old:
                    conn.execute(
                        update(S.management_object_states)
                        .where(
                            S.management_object_states.c.project_id == proj_id,
                            S.management_object_states.c.object_id == aid,
                        )
                        .values(**values)
                    )
                else:
                    conn.execute(
                        insert(S.management_object_states).values(
                            project_id=proj_id, id=new_id(), object_id=aid, **values
                        )
                    )
                recycled_ids.append(aid)
            return dict(recycled_ids=recycled_ids, recycled_count=len(recycled_ids), protected=protected)

        return self._mutate(p, 'management_trash', payload, actor=actor, callback=work, **kw)

    def save_manifestation_voice(self, p, payload, actor, **kw):
        def work(conn, project):
            proj_id = project['id']
            card = self._asset_card(conn, proj_id, checked_id(payload['asset_id']))
            if card['asset_kind'] != 'character':
                raise ResourceError('只有人设资产支持按形态绑定参考音色')
            if card['revision'] != payload['base_revision']:
                raise Conflict('资产卡已有更新，请先读回最新版本', 'asset_card_conflict')
            ref = payload['form_ref']
            target_form = next(
                (f for f in card['forms'] if f.get('form_key') == ref or str(f.get('id') or '') == ref),
                None,
            )
            if not target_form and not card['forms'] and ref == 'master':
                target_form = {
                    'form_key': 'master',
                    'name': '默认形态',
                    'version_id': None,
                    'description': '',
                    'media_id': None,
                    'voice_spec_id': None,
                }
            if not target_form:
                raise ResourceError('未找到指定的角色形态')
            new_voice_spec_id = None
            audio_media_id = None
            voice_prompt = payload.get('voice_prompt', '')
            if not payload.get('clear'):
                if payload.get('voice_spec_id') and not payload.get('audio_media_id') and not voice_prompt:
                    existing_voice = self._one(conn, S.voice_spec_versions, proj_id, checked_id(payload['voice_spec_id']))
                    new_voice_spec_id = existing_voice['id']
                    audio_media_id = existing_voice['reference_media_id']
                    voice_prompt = str((existing_voice['diction'] or {}).get('description', '') or '')
                else:
                    prior_media_id, prior_prompt = self._voice_meta(conn, proj_id, target_form.get('voice_spec_id'))
                    audio_media_id = payload['audio_media_id'] if payload.get('audio_media_id') is not None else prior_media_id
                    if 'voice_prompt' not in payload:
                        voice_prompt = prior_prompt
                    if audio_media_id:
                        media = self._media(conn, proj_id, checked_id(audio_media_id))
                        if media['modality'] != 'audio':
                            raise ResourceError('绑定的参考音色必须是音频素材')
                    owned_voice_asset = None
                    owned_base_rev = 0
                    owned_base_ver = None
                    if target_form.get('voice_spec_id'):
                        prior_spec = conn.execute(
                            select(S.voice_spec_versions).where(
                                S.voice_spec_versions.c.project_id == proj_id,
                                S.voice_spec_versions.c.id == target_form['voice_spec_id'],
                            )
                        ).mappings().first()
                        prior_diction = prior_spec['diction'] if prior_spec and isinstance(prior_spec['diction'], dict) else {}
                        if prior_diction.get('owner_asset_id') == card['id'] and prior_diction.get('owner_form_key') == target_form['form_key']:
                            try:
                                existing_vcard = self._asset_card(conn, proj_id, prior_spec['voice_id'])
                                owned_voice_asset = existing_vcard['id']
                                owned_base_rev = existing_vcard['revision']
                                master_form = next((vf for vf in existing_vcard['forms'] if vf.get('form_key') == 'master'), None)
                                owned_base_ver = master_form['version_id'] if master_form else None
                            except ResourceError:
                                owned_voice_asset = None
                    voice_payload = dict(
                        name=card['name'] + ' · ' + target_form['name'] + ' 音色',
                        asset_kind='voice',
                        base_revision=owned_base_rev,
                        forms=[
                            dict(
                                form_key='master',
                                name=target_form['name'] + '参考音色',
                                base_version_id=owned_base_ver,
                                description=voice_prompt,
                                media_id=audio_media_id,
                                voice_details={
                                    'diction': {
                                        'description': voice_prompt,
                                        'owner_asset_id': card['id'],
                                        'owner_form_key': target_form['form_key'],
                                    },
                                    'post_chain': {},
                                },
                            )
                        ],
                    )
                    if owned_voice_asset:
                        voice_payload['asset_id'] = owned_voice_asset
                    voice_card = self._save_asset_card(conn, project, voice_payload, actor)
                    new_voice_spec_id = self._one(
                        conn, S.asset_card_form_versions, proj_id, voice_card['forms'][0]['version_id']
                    )['voice_spec_id']
            forms_payload = []
            base_forms = card['forms'] or [target_form]
            for f in base_forms:
                is_target = f.get('form_key') == target_form['form_key']
                forms_payload.append(
                    dict(
                        form_key=f['form_key'],
                        name=f['name'],
                        base_version_id=f.get('version_id'),
                        description=f.get('description', ''),
                        media_id=f.get('media_id'),
                        voice_spec_id=new_voice_spec_id if is_target else f.get('voice_spec_id'),
                    )
                )
            saved = self._save_asset_card(
                conn,
                project,
                dict(
                    asset_id=card['id'],
                    name=card['name'],
                    asset_kind='character',
                    base_revision=card['revision'],
                    forms=forms_payload,
                ),
                actor,
            )
            updated_card = self._asset_card(conn, proj_id, card['id'], actor=actor)
            return dict(
                asset_id=card['id'],
                asset_revision=saved['asset_revision'],
                form_key=target_form['form_key'],
                voice_spec_id=new_voice_spec_id,
                voice_reference_media_id=audio_media_id,
                voice_prompt='' if payload.get('clear') else voice_prompt,
                forms=updated_card['forms'],
            )

        return self._mutate(p, 'save_manifestation_voice', payload, actor=actor, callback=work, **kw)
