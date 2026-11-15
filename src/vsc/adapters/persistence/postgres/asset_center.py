"""Shared catalog annotations; reuse stays an original target-project command."""
import uuid
from collections import defaultdict
from sqlalchemy import select, insert, update, func, and_, or_, exists, union, table, column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.resource_service import ResourceError, Conflict, NotFound
from . import schema as S
from .shared_library import SharedLibraryRepository, _version_gaps
from .values import checked_id, clean, digest, new_id, CURRENT_REVISION

CREATURE_TAG = "生物/异兽"
_RAW_TAG_LIMIT = 2001
_CHARACTER_FACET_LIMIT = 400


def load_official_classes(conn, publication_ids):
    """Read sealed class rows. An unknown publication gets empty dimensions."""
    roles, locations, props = defaultdict(list), {}, {}
    if not publication_ids:
        return roles, locations, props
    ids = list(publication_ids)
    for row in conn.execute(
        select(S.official_asset_role_tags.c.publication_id, S.official_asset_role_tags.c.value)
        .where(S.official_asset_role_tags.c.publication_id.in_(ids))
        .order_by(S.official_asset_role_tags.c.publication_id, S.official_asset_role_tags.c.ordinal)
    ):
        roles[row.publication_id].append(row.value)
    for row in conn.execute(
        select(
            S.official_location_classes.c.publication_id,
            S.official_location_classes.c.scene_type,
            S.official_location_classes.c.space,
        ).where(S.official_location_classes.c.publication_id.in_(ids))
    ):
        locations[row.publication_id] = (row.scene_type, row.space)
    for row in conn.execute(
        select(S.official_prop_classes.c.publication_id, S.official_prop_classes.c.prop_type)
        .where(S.official_prop_classes.c.publication_id.in_(ids))
    ):
        props[row.publication_id] = row.prop_type
    return roles, locations, props


def _official_visible_entry_ids():
    """Entries that still have one available image, video, or audio member."""
    from .library_media import available_member

    def ready(media):
        return and_(
            media.c.modality.in_(("image", "video", "audio")),
            available_member(media.c.library_version_id, media.c.member_key),
        )

    media = S.library_version_media
    versions = S.library_entry_versions
    owned = select(versions.c.entry_id.label("entry_id")).select_from(
        media.join(versions, versions.c.id == media.c.library_version_id)
    ).where(ready(media))
    linked_media = media.alias("official_backup_media")
    backups = S.official_asset_backups
    linked = select(backups.c.entry_id.label("entry_id")).select_from(
        backups.join(linked_media, and_(
            linked_media.c.library_version_id == backups.c.library_version_id,
            linked_media.c.member_key == backups.c.member_key,
        ))
    ).where(ready(linked_media))
    return union(owned, linked).subquery("official_visible_entries")


def _official_browse_table():
    publication = S.official_asset_publications
    return table("official_browse_base", *[column(item.name, item.type) for item in publication.columns])


def _stage_official_browse(conn, selectable):
    """One visibility pass. Count, facets, and the page then read this snapshot."""
    compiled = selectable.compile(dialect=conn.dialect, compile_kwargs={"render_postcompile": True})
    conn.exec_driver_sql("DROP TABLE IF EXISTS official_browse_base")
    conn.exec_driver_sql(
        "CREATE TEMP TABLE official_browse_base ON COMMIT DROP AS " + compiled.string,
        compiled.params,
    )


def apply_official_classes(official, roles, locations, props):
    scene, space = locations.get(official["id"], ("", ""))
    official["role_tags"] = list(roles.get(official["id"], []))
    official["scene_type"] = scene
    official["space"] = space
    official["prop_type"] = props.get(official["id"], "")
    return official


class AssetCenterRepository:
    def __init__(self, store, storage):
        self.store, self.storage = store, storage
        self.library = SharedLibraryRepository(store, storage)

    def _latest(self, conn, entry_id):
        row = conn.execute(
            select(S.library_catalog_edits)
            .where(S.library_catalog_edits.c.entry_id == entry_id)
            .order_by(S.library_catalog_edits.c.revision.desc())
            .limit(1)
        ).mappings().first()
        if not row:
            return {
                "revision": 0,
                "tags": [],
                "review_status": "draft",
                "asset_kind": "other",
                "display_kind": "other",
                "form_name": "",
                "notes": "",
                "workspace_id": None,
            }
        tags = list(
            conn.execute(
                select(S.library_catalog_tags.c.tag)
                .where(S.library_catalog_tags.c.edit_id == row["id"])
                .order_by(S.library_catalog_tags.c.tag)
            ).scalars()
        )
        display_kind = "creature" if row["asset_kind"] == "other" and CREATURE_TAG in tags else row["asset_kind"]
        return dict(row, tags=tags, display_kind=display_kind)

    def search(self, filters, actor):
        if filters.get("source") == "official":
            return self._search_official(filters)
        e, c = S.library_entries, S.library_catalog_edits
        ranked = select(
            c, func.row_number().over(partition_by=c.c.entry_id, order_by=c.c.revision.desc()).label("rank")
        ).subquery()
        heat_sub = (
            select(func.count())
            .select_from(S.library_download_requests)
            .where(S.library_download_requests.c.library_version_id == e.c.current_version_id)
            .correlate(e)
            .scalar_subquery()
        )
        query = select(e.c.current_version_id).outerjoin(ranked, and_(ranked.c.entry_id == e.c.id, ranked.c.rank == 1))
        query = query.where(e.c.status == "active", e.c.rights_status == "active", e.c.visibility == "workspace")
        if filters.get("media_only"):
            query = query.where(
                exists(
                    select(1).where(
                        S.library_version_media.c.library_version_id == e.c.current_version_id,
                        S.library_version_media.c.modality.in_(["image", "video", "audio"]),
                    )
                )
            )
        if filters.get("asset_kind") == "creature":
            query = query.where(
                func.coalesce(ranked.c.asset_kind, "other") == "other",
                exists(
                    select(1).where(
                        S.library_catalog_tags.c.edit_id == ranked.c.id,
                        S.library_catalog_tags.c.tag == CREATURE_TAG,
                    )
                ),
            )
        elif filters.get("asset_kind"):
            query = query.where(func.coalesce(ranked.c.asset_kind, "other") == filters["asset_kind"])
        for key in ("workspace_id", "form_name"):
            if filters.get(key):
                query = query.where(ranked.c[key] == filters[key])
        if filters.get("review_status"):
            if filters["review_status"] == "draft":
                query = query.where(
                    or_(
                        ranked.c.id.is_(None),
                        ranked.c.library_version_id != e.c.current_version_id,
                        ranked.c.review_status == "draft",
                    )
                )
            else:
                query = query.where(
                    ranked.c.library_version_id == e.c.current_version_id,
                    ranked.c.review_status == filters["review_status"],
                )
        if filters.get("tag"):
            query = query.where(
                exists(
                    select(1).where(
                        S.library_catalog_tags.c.edit_id == ranked.c.id,
                        S.library_catalog_tags.c.tag == filters["tag"],
                    )
                )
            )
        if filters.get("query"):
            pattern = "%" + filters["query"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(
                or_(
                    e.c.title.ilike(pattern, escape="\\"),
                    ranked.c.form_name.ilike(pattern, escape="\\"),
                    exists(
                        select(1).where(
                            S.library_catalog_tags.c.edit_id == ranked.c.id,
                            S.library_catalog_tags.c.tag.ilike(pattern, escape="\\"),
                        )
                    ),
                )
            )
        order_by = filters.get("order_by", "")
        if order_by == "heat":
            ordering = (heat_sub.desc(), e.c.title, e.c.id)
        elif order_by == "latest":
            ordering = (e.c.created_at.desc(), e.c.title, e.c.id)
        else:
            ordering = (e.c.title, e.c.id)
        with self.store.engine.connect() as conn:
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            ids = list(conn.execute(query.order_by(*ordering).offset(filters["offset"]).limit(filters["limit"])).scalars())
            rows = self.library._details(conn, ids)
            counts = (
                {
                    r["library_version_id"]: int(r["cnt"])
                    for r in conn.execute(
                        select(
                            S.library_download_requests.c.library_version_id,
                            func.count().label("cnt"),
                        )
                        .where(S.library_download_requests.c.library_version_id.in_(ids))
                        .group_by(S.library_download_requests.c.library_version_id)
                    ).mappings()
                }
                if ids
                else {}
            )
            for row in rows:
                row["source"] = "shared"
                row["download_count"] = counts.get(row["version_id"], 0)
                row["catalog"] = self._latest(conn, row["id"])
                if row["catalog"].get("library_version_id") != row["version_id"]:
                    row["catalog"]["review_status"] = "draft"
                owner = conn.execute(select(e.c.created_by).where(e.c.id == row["id"])).scalar_one()
                row["can_edit_catalog"] = owner == actor
            return clean(
                {
                    "items": rows,
                    "total": total,
                    "offset": filters["offset"],
                    "next_offset": filters["offset"] + len(rows) if filters["offset"] + len(rows) < total else None,
                }
            )

    @staticmethod
    def _official_publisher(actor):
        from vsc.configuration import get_config
        publishers = get_config("VSC_OFFICIAL_ASSET_PUBLISHERS", [])
        if not isinstance(publishers, (list, tuple)) or any(
            not isinstance(p, str) or not p.strip() or len(p) > 200 for p in publishers
        ):
            raise ResourceError("官方发布者配置需要明确的身份列表", "official_publisher_config", 503)
        if actor not in publishers:
            raise ResourceError("当前身份没有平台官方资产发布权限", "official_publisher_required", 403)

    def official_capabilities(self, actor):
        try:
            self._official_publisher(actor)
        except ResourceError as error:
            if error.code != "official_publisher_required":
                raise
            return {"can_publish": False}
        return {"can_publish": True}

    def publish_official(self, payload, actor):
        self._official_publisher(actor)
        request_sha = digest(payload)
        o, v, e = S.official_asset_publications, S.library_entry_versions, S.library_entries
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn, "official-command:" + actor + ":" + payload["command_key"])
            previous = conn.execute(
                select(o).where(o.c.publisher == actor, o.c.command_key == payload["command_key"])
            ).mappings().first()
            if previous:
                if previous["request_sha256"] != request_sha:
                    raise Conflict("官方发布请求标识的内容已改变", "idempotency_conflict")
                return clean(dict(previous))
            version = conn.execute(
                select(v).where(v.c.id == payload["library_version_id"], v.c.entry_id == payload["entry_id"])
            ).mappings().first()
            if not version:
                raise NotFound("原共享库固定版本不存在或不属于该库项")
            sources = conn.execute(
                select(S.library_reuses.c.project_id).where(
                    S.library_reuses.c.library_version_id == version["id"], S.library_reuses.c.reuse_mode == "publish"
                )
            ).scalars()
            for project_id in sorted(set(sources)):
                conn.execute(select(S.projects.c.id).where(S.projects.c.id == project_id).with_for_update(read=True)).one()
            entry = conn.execute(select(e).where(e.c.id == version["entry_id"]).with_for_update()).mappings().one()
            if not version["allowed_purposes"]:
                raise ResourceError("原共享版本没有许可用途", "library_purpose_not_allowed")
            for purpose in version["allowed_purposes"]:
                gaps = _version_gaps(self.store, conn, version, purpose, new_use=True)
                if gaps:
                    raise ResourceError("原共享素材当前不允许发布：" + ", ".join(gaps), gaps[0])
            if entry["visibility"] != "workspace":
                raise ResourceError("官方目录仅接受已明确共享的原固定版本", "official_shared_required")
            existing = conn.execute(select(o).where(o.c.library_version_id == version["id"])).mappings().first()
            if existing:
                raise Conflict("此固定库版本已有不可变官方发布记录", "official_publication_exists")
            row = dict(payload, id=new_id(), publisher=actor, request_sha256=request_sha)
            conn.execute(insert(o).values(**row))
            return clean(dict(conn.execute(select(o).where(o.c.id == row["id"])).mappings().one()))

    def _search_official(self, filters):
        o, v, e = S.official_asset_publications, S.library_entry_versions, S.library_entries
        query = select(o).join(v, and_(v.c.id == o.c.library_version_id, v.c.entry_id == o.c.entry_id)).join(e, e.c.id == o.c.entry_id)
        query = query.where(
            e.c.status == "active",
            e.c.rights_status == "active",
            e.c.visibility == "workspace",
            or_(v.c.expires_at.is_(None), v.c.expires_at > func.now()),
        )
        latest = (
            select(o.c.id)
            .distinct(o.c.entry_id)
            .order_by(o.c.entry_id, o.c.created_at.desc(), o.c.id.desc())
        )
        query = query.where(o.c.id.in_(latest))
        if filters.get("asset_kind"):
            query = query.where(o.c.asset_kind == filters["asset_kind"])
        if filters.get("media_only"):
            visible = _official_visible_entry_ids()
            query = query.where(o.c.entry_id.in_(select(visible.c.entry_id)))
        if filters.get("query"):
            pattern = "%" + filters["query"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.where(
                or_(
                    v.c.title.ilike(pattern, escape="\\"),
                    v.c.description.ilike(pattern, escape="\\"),
                    o.c.role_tag.ilike(pattern, escape="\\"),
                )
            )
        # Dimension chips stay selectable, so gender and role stay off this snapshot.
        # Search text and media availability do scope it; otherwise another test's
        # publication leaks into this result's facet set.
        with self.store.engine.begin() as conn:
            _stage_official_browse(conn, query)
            base = _official_browse_table()
            facets = {}
            facets_truncated = False
            for key in ("role_level", "gender", "age_band"):
                values = list(conn.execute(select(base.c[key]).distinct().order_by(base.c[key]).limit(101)).scalars())
                facets[key] = values[:100]
                facets_truncated = facets_truncated or len(values) > 100
            kind = filters.get("asset_kind") or ""
            if kind == "character":
                segments = list(conn.execute(
                    select(S.official_asset_role_tags.c.value)
                    .select_from(S.official_asset_role_tags.join(
                        base, base.c.id == S.official_asset_role_tags.c.publication_id))
                    .distinct().order_by(S.official_asset_role_tags.c.value)
                    .limit(_CHARACTER_FACET_LIMIT + 1)
                ).scalars())
                facets["role_tag"] = segments[:_CHARACTER_FACET_LIMIT]
                facets_truncated = facets_truncated or len(segments) > _CHARACTER_FACET_LIMIT
            else:
                raw_tags = list(conn.execute(
                    select(base.c.role_tag).distinct().order_by(base.c.role_tag).limit(_RAW_TAG_LIMIT)
                ).scalars())
                facets["role_tag"] = raw_tags[:100]
                facets_truncated = facets_truncated or len(raw_tags) > 100
                if kind == "location":
                    facets["scene_type"] = list(conn.execute(
                        select(S.official_location_classes.c.scene_type)
                        .select_from(S.official_location_classes.join(
                            base, base.c.id == S.official_location_classes.c.publication_id))
                        .distinct().order_by(S.official_location_classes.c.scene_type)
                    ).scalars())
                    facets["space"] = list(conn.execute(
                        select(S.official_location_classes.c.space)
                        .select_from(S.official_location_classes.join(
                            base, base.c.id == S.official_location_classes.c.publication_id))
                        .distinct().order_by(S.official_location_classes.c.space)
                    ).scalars())
                elif kind == "prop":
                    facets["prop_type"] = list(conn.execute(
                        select(S.official_prop_classes.c.prop_type)
                        .select_from(S.official_prop_classes.join(
                            base, base.c.id == S.official_prop_classes.c.publication_id))
                        .distinct().order_by(S.official_prop_classes.c.prop_type)
                    ).scalars())
            criteria = []
            for key in ("role_level", "gender", "age_band"):
                if filters.get(key):
                    criteria.append(base.c[key] == filters[key])
            if filters.get("role_tag"):
                criteria.append(exists(select(1).where(
                    S.official_asset_role_tags.c.publication_id == base.c.id,
                    S.official_asset_role_tags.c.value == filters["role_tag"],
                )))
            if filters.get("scene_type"):
                criteria.append(exists(select(1).where(
                    S.official_location_classes.c.publication_id == base.c.id,
                    S.official_location_classes.c.scene_type == filters["scene_type"],
                )))
            if filters.get("space"):
                criteria.append(exists(select(1).where(
                    S.official_location_classes.c.publication_id == base.c.id,
                    S.official_location_classes.c.space == filters["space"],
                )))
            if filters.get("prop_type"):
                criteria.append(exists(select(1).where(
                    S.official_prop_classes.c.publication_id == base.c.id,
                    S.official_prop_classes.c.prop_type == filters["prop_type"],
                )))
            order_by = filters.get("order_by", "")
            if order_by == "title":
                ordering = (v.c.title, base.c.library_version_id)
            elif order_by == "heat":
                heat_sub = (
                    select(func.count())
                    .where(S.library_download_requests.c.library_version_id == base.c.library_version_id)
                    .correlate(base)
                    .scalar_subquery()
                )
                ordering = (heat_sub.desc(), base.c.created_at.desc(), v.c.title, base.c.library_version_id)
            else:
                ordering = (base.c.created_at.desc(), v.c.created_at.desc(), v.c.title, base.c.library_version_id)
            total = conn.execute(select(func.count()).select_from(base).where(*criteria)).scalar_one()
            page = (
                select(base)
                .select_from(base.join(v, and_(
                    v.c.id == base.c.library_version_id, v.c.entry_id == base.c.entry_id)))
                .where(*criteria)
                .order_by(*ordering)
                .offset(filters["offset"])
                .limit(filters["limit"])
            )
            publications = [dict(row) for row in conn.execute(page).mappings()]
            details = self.library._details(conn, [row["library_version_id"] for row in publications])
            by_version = {row["library_version_id"]: row for row in publications}
            roles, locations, props = load_official_classes(conn, [row["id"] for row in publications])
            for row in details:
                official = apply_official_classes(dict(by_version[row["version_id"]]), roles, locations, props)
                row.update(source="official", official=official, can_edit_catalog=False)
                if not row['members']:
                    from .library_media import LibraryMediaRepository
                    gallery = LibraryMediaRepository(self.store, self.storage).detail(row['id'], None)['gallery']
                    row['members'] = gallery[:1]
                    if gallery:
                        row['version_id'] = gallery[0]['library_version_id']
            return clean(
                {
                    "items": details,
                    "total": total,
                    "offset": filters["offset"],
                    "limit": filters["limit"],
                    "facets": facets,
                    "facets_truncated": facets_truncated,
                    "next_offset": filters["offset"] + len(details) if filters["offset"] + len(details) < total else None,
                }
            )

    def edit(self, payload, actor):
        request_sha = digest(payload)
        with self.store.engine.begin() as conn:
            from .access_control import authority_lock
            authority_lock(conn)
            if payload["workspace_id"]:
                self.store.access_workspace_guard(conn, payload["workspace_id"], "manage")
            self.library._lock_key(conn, "catalog-command:" + actor + ":" + payload["command_key"])
            entry = conn.execute(
                select(S.library_entries).where(S.library_entries.c.id == payload["entry_id"]).with_for_update()
            ).mappings().first()
            if not entry:
                raise NotFound("共享素材不存在")
            if entry["created_by"] != actor:
                raise ResourceError("只有库项维护人可编辑目录信息", "library_owner_required", 403)
            previous = conn.execute(
                select(S.library_catalog_edits).where(
                    S.library_catalog_edits.c.actor == actor,
                    S.library_catalog_edits.c.command_key == payload["command_key"],
                )
            ).mappings().first()
            if previous:
                if previous["request_sha256"] != request_sha:
                    raise Conflict("同一操作标识的内容已改变", "idempotency_conflict")
                out = dict(previous)
                out["tags"] = list(payload["tags"])
                out["display_kind"] = "creature" if out["asset_kind"] == "other" and "生物/异兽" in payload["tags"] else out["asset_kind"]
                return clean(out)
            latest = self._latest(conn, entry["id"])
            if latest["revision"] != payload["expected_revision"] or entry["current_version_id"] != payload["library_version_id"]:
                raise Conflict("目录或共享素材版本已变化，请先读回", "catalog_revision_conflict")
            row = {
                key: payload[key]
                for key in (
                    "entry_id",
                    "library_version_id",
                    "asset_kind",
                    "form_name",
                    "workspace_id",
                    "review_status",
                    "notes",
                    "command_key",
                )
            }
            row.update(
                id=new_id(),
                revision=latest["revision"] + 1,
                tag_count=len(payload["tags"]),
                actor=actor,
                request_sha256=request_sha,
            )
            conn.execute(insert(S.library_catalog_edits).values(**row))
            for tag in payload["tags"]:
                conn.execute(insert(S.library_catalog_tags).values(edit_id=row["id"], tag=tag))
            out = dict(row, tags=list(payload["tags"]))
            out["display_kind"] = "creature" if out["asset_kind"] == "other" and "生物/异兽" in payload["tags"] else out["asset_kind"]
            return clean(out)

    def cart(self, actor):
        with self.store.engine.connect() as conn:
            rows = conn.execute(
                select(S.library_cart_items)
                .where(S.library_cart_items.c.actor == actor, S.library_cart_items.c.active)
                .order_by(S.library_cart_items.c.created_at, S.library_cart_items.c.id)
            ).mappings().all()
            publications = {
                row["library_version_id"]: dict(row)
                for row in conn.execute(
                    select(S.official_asset_publications).where(
                        S.official_asset_publications.c.library_version_id.in_({row["library_version_id"] for row in rows})
                    )
                ).mappings()
            } if rows else {}
            roles, locations, props = load_official_classes(conn, [row["id"] for row in publications.values()])
            for official in publications.values():
                apply_official_classes(official, roles, locations, props)
            result = []
            for row in rows:
                fixed = self.library._detail(conn, row["library_version_id"])
                member = next((item for item in fixed["members"] if item["member_key"] == row["member_key"]), None)
                if member is None:
                    continue
                official = publications.get(row["library_version_id"])
                result.append(
                    dict(
                        row,
                        title=fixed["title"],
                        member=member,
                        allowed_purposes=fixed["allowed_purposes"],
                        source="official" if official else "shared",
                        official=dict(official) if official else None,
                    )
                )
            return clean({"items": result})

    def cart_change(self, payload, actor):
        if payload.get("active"):
            self.library.detail(payload["library_version_id"])
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn, "cart:" + actor)
            if payload["active"]:
                self.library._fixed_reference(conn, payload)
                count = conn.execute(
                    select(func.count())
                    .select_from(S.library_cart_items)
                    .where(S.library_cart_items.c.actor == actor, S.library_cart_items.c.active)
                ).scalar_one()
                existing = conn.execute(
                    select(S.library_cart_items.c.id).where(
                        S.library_cart_items.c.actor == actor,
                        S.library_cart_items.c.library_version_id == payload["library_version_id"],
                        S.library_cart_items.c.member_key == payload["member_key"],
                        S.library_cart_items.c.active,
                    )
                ).scalar_one_or_none()
                if count >= 200 and not existing:
                    raise ResourceError("选取清单最多保留200项，请先完成导入或移除已用项", "cart_limit")
            row = conn.execute(
                pg_insert(S.library_cart_items)
                .values(id=new_id(), actor=actor, **payload)
                .on_conflict_do_update(
                    index_elements=[
                        S.library_cart_items.c.actor,
                        S.library_cart_items.c.library_version_id,
                        S.library_cart_items.c.member_key,
                    ],
                    set_={"active": payload["active"]},
                )
                .returning(S.library_cart_items.c.id)
            ).scalar_one()
            return {"id": row, "active": payload["active"]}

    def cart_clear(self, actor):
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn, "cart:" + actor)
            cleared = conn.execute(
                update(S.library_cart_items)
                .where(S.library_cart_items.c.actor == actor, S.library_cart_items.c.active)
                .values(active=False)
            ).rowcount
            count = int(cleared or 0)
            return {"cleared_count": count, "cleared": count}

    def import_item(self, project_id, payload, **kw):
        with self.store.engine.connect() as conn:
            item = conn.execute(
                select(S.library_cart_items).where(
                    S.library_cart_items.c.id == payload["cart_id"], S.library_cart_items.c.actor == kw["actor"]
                )
            ).mappings().first()
            if not item:
                raise NotFound("选取清单中没有这个素材")
            version_id = item["library_version_id"]

        def work(conn, project):
            item = conn.execute(
                select(S.library_cart_items)
                .where(S.library_cart_items.c.id == payload["cart_id"], S.library_cart_items.c.actor == kw["actor"])
                .with_for_update()
            ).mappings().one()
            if not item["active"]:
                raise ResourceError("此素材已移出选取清单", "cart_item_removed")
            target = payload.get("target_object_id") or str(
                uuid.uuid5(uuid.UUID(item["id"]), project["id"] + ":asset:" + payload["asset_kind"])
            )
            existing = conn.execute(
                select(S.library_cart_imports).where(
                    S.library_cart_imports.c.project_id == project["id"],
                    S.library_cart_imports.c.cart_id == item["id"],
                    S.library_cart_imports.c.target_object_id == target,
                    S.library_cart_imports.c.role == payload["role"],
                )
            ).mappings().first()
            if existing:
                return clean(dict(existing))
            if not payload.get("target_object_id"):
                fixed = self.library._detail(conn, version_id)
                prior = conn.execute(
                    select(S.creative_objects.c.id).where(
                        S.creative_objects.c.project_id == project["id"], S.creative_objects.c.id == target
                    )
                ).scalar_one_or_none()
                if not prior:
                    self.store._create_object(
                        conn,
                        project,
                        {
                            "id": target,
                            "kind": "asset",
                            "asset_kind": payload["asset_kind"],
                            "display_code": "LIB-" + item["id"][:12],
                            "title": fixed["title"],
                        },
                    )
            result = self.library.use(
                project["id"],
                {
                    "library_version_id": version_id,
                    "member_key": item["member_key"],
                    "target_object_id": target,
                    "role": payload["role"],
                    "slot_key": "main",
                    "select": False,
                },
                actor=kw["actor"],
                expected_revision=CURRENT_REVISION,
                idempotency_key="center-internal",
                _transaction=(conn, project),
            )
            if not payload.get("target_object_id"):
                from .asset_cards import AssetCardsRepository
                cards = AssetCardsRepository(self.store)
                current = cards._asset_card(conn, project["id"], target)
                cards._save_asset_card(
                    conn,
                    project,
                    dict(
                        asset_id=target,
                        name=current["name"],
                        asset_kind=payload["asset_kind"],
                        base_revision=current["revision"],
                        forms=[
                            dict(
                                form_key="master",
                                name="默认形态",
                                base_version_id=None,
                                media_id=result["media_id"],
                                description=fixed.get("description", ""),
                            )
                        ],
                    ),
                    kw["actor"],
                )
            row = dict(
                id=new_id(),
                project_id=project["id"],
                cart_id=item["id"],
                target_object_id=target,
                role=payload["role"],
                actor=kw["actor"],
                media_id=result["media_id"],
                candidate_id=result["candidate_id"],
            )
            conn.execute(insert(S.library_cart_imports).values(**row))
            return row

        return self.store._mutate(
            project_id,
            "import_asset_center_item",
            payload,
            callback=work,
            _library_versions=(version_id,),
            **kw,
        )

    def download(self, payload, actor):
        self.library.content(payload["library_version_id"], payload["member_key"])
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn, "download:" + actor + ":" + payload["command_key"])
            previous = conn.execute(
                select(S.library_download_requests).where(
                    S.library_download_requests.c.actor == actor,
                    S.library_download_requests.c.command_key == payload["command_key"],
                )
            ).mappings().first()
            if previous:
                if any(previous[k] != payload[k] for k in ("library_version_id", "member_key")):
                    raise Conflict("下载请求标识已用于其他素材", "idempotency_conflict")
                return clean(dict(previous))
            row = dict(id=new_id(), actor=actor, **payload)
            conn.execute(insert(S.library_download_requests).values(**row))
            return row

    def downloads(self, actor, offset, limit):
        with self.store.engine.connect() as conn:
            query = select(S.library_download_requests).where(S.library_download_requests.c.actor == actor)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(S.library_download_requests.c.created_at.desc(), S.library_download_requests.c.id)
                .offset(offset)
                .limit(limit)
            ).mappings().all()
            return clean({"items": [dict(row) for row in rows], "total": total})
