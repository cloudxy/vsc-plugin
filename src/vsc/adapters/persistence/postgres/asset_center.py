"""Shared catalog annotations; reuse stays an original target-project command."""
import uuid
from sqlalchemy import select, insert, update, func, and_, or_, exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.resource_service import ResourceError, Conflict, NotFound
from . import schema as S
from .shared_library import SharedLibraryRepository
from .values import checked_id, clean, digest, new_id, CURRENT_REVISION


class AssetCenterRepository:
    def __init__(self, store, storage):
        self.store, self.storage = store, storage
        self.library = SharedLibraryRepository(store, storage)

    def _latest(self, conn, entry_id):
        row = conn.execute(select(S.library_catalog_edits).where(S.library_catalog_edits.c.entry_id==entry_id)
            .order_by(S.library_catalog_edits.c.revision.desc()).limit(1)).mappings().first()
        if not row:
            return {"revision":0, "tags":[], "review_status":"draft", "asset_kind":"other", "form_name":"", "notes":"", "workspace_id":None}
        return dict(row, tags=list(conn.execute(select(S.library_catalog_tags.c.tag)
            .where(S.library_catalog_tags.c.edit_id==row["id"]).order_by(S.library_catalog_tags.c.tag)).scalars()))

    def search(self, filters, actor):
        e,c = S.library_entries,S.library_catalog_edits
        ranked = select(c,func.row_number().over(partition_by=c.c.entry_id,order_by=c.c.revision.desc()).label("rank")).subquery()
        query = select(e.c.current_version_id).outerjoin(ranked,and_(ranked.c.entry_id==e.c.id,ranked.c.rank==1))
        query=query.where(e.c.status=="active",e.c.rights_status=="active")
        for key in ("asset_kind","workspace_id","form_name"):
            if filters.get(key): query=query.where(ranked.c[key]==filters[key])
        if filters.get("review_status"):
            if filters["review_status"]=="draft":
                query=query.where(or_(ranked.c.id.is_(None),ranked.c.library_version_id!=e.c.current_version_id,ranked.c.review_status=="draft"))
            else: query=query.where(ranked.c.library_version_id==e.c.current_version_id,ranked.c.review_status==filters["review_status"])
        if filters.get("tag"):
            query=query.where(exists(select(1).where(S.library_catalog_tags.c.edit_id==ranked.c.id,S.library_catalog_tags.c.tag==filters["tag"])))
        if filters.get("query"):
            pattern="%"+filters["query"].replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
            query=query.where(e.c.title.ilike(pattern,escape="\\"))
        with self.store.engine.connect() as conn:
            total=conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            ids=list(conn.execute(query.order_by(e.c.title,e.c.id).offset(filters["offset"]).limit(filters["limit"])).scalars())
            rows=self.library._details(conn,ids)
            for row in rows:
                row["catalog"]=self._latest(conn,row["id"])
                if row["catalog"].get("library_version_id")!=row["version_id"]:row["catalog"]["review_status"]="draft"
                owner=conn.execute(select(e.c.created_by).where(e.c.id==row["id"])).scalar_one()
                row["can_edit_catalog"]=owner==actor
            return clean({"items":rows,"total":total,"offset":filters["offset"],"next_offset":filters["offset"]+len(rows) if filters["offset"]+len(rows)<total else None})

    def edit(self, payload, actor):
        request_sha=digest(payload)
        with self.store.engine.begin() as conn:
            from .access_control import authority_lock
            authority_lock(conn)
            if payload["workspace_id"]:
                self.store.access_workspace_guard(conn,payload["workspace_id"],"manage")
            self.library._lock_key(conn,"catalog-command:"+actor+":"+payload["command_key"])
            # Entry lock serializes metadata revisions and new library versions.
            entry=conn.execute(select(S.library_entries).where(S.library_entries.c.id==payload["entry_id"]).with_for_update()).mappings().first()
            if not entry:raise NotFound("共享素材不存在")
            if entry["created_by"]!=actor:raise ResourceError("只有库项维护人可编辑目录信息","library_owner_required",403)
            previous=conn.execute(select(S.library_catalog_edits).where(S.library_catalog_edits.c.actor==actor,S.library_catalog_edits.c.command_key==payload["command_key"])).mappings().first()
            if previous:
                if previous["request_sha256"]!=request_sha:raise Conflict("同一操作标识的内容已改变","idempotency_conflict")
                return clean(dict(previous))
            latest=self._latest(conn,entry["id"])
            if latest["revision"]!=payload["expected_revision"] or entry["current_version_id"]!=payload["library_version_id"]:
                raise Conflict("目录或共享素材版本已变化，请先读回","catalog_revision_conflict")
            row={key:payload[key] for key in ("entry_id","library_version_id","asset_kind","form_name","workspace_id","review_status","notes","command_key")}
            row.update(id=new_id(),revision=latest["revision"]+1,tag_count=len(payload["tags"]),actor=actor,request_sha256=request_sha)
            conn.execute(insert(S.library_catalog_edits).values(**row))
            for tag in payload["tags"]:conn.execute(insert(S.library_catalog_tags).values(edit_id=row["id"],tag=tag))
            return clean(row)

    def cart(self, actor):
        with self.store.engine.connect() as conn:
            rows=conn.execute(select(S.library_cart_items).where(S.library_cart_items.c.actor==actor,S.library_cart_items.c.active)
                .order_by(S.library_cart_items.c.created_at,S.library_cart_items.c.id)).mappings().all()
            result=[]
            for row in rows:
                fixed=self.library._detail(conn,row["library_version_id"])
                member=next(item for item in fixed["members"] if item["member_key"]==row["member_key"])
                result.append(dict(row,title=fixed["title"],member=member,allowed_purposes=fixed["allowed_purposes"]))
            return clean({"items":result})

    def cart_change(self, payload, actor):
        if payload.get("active"):
            self.library.detail(payload["library_version_id"])
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn,"cart:"+actor)
            if payload["active"]:
                count=conn.execute(select(func.count()).select_from(S.library_cart_items).where(S.library_cart_items.c.actor==actor,S.library_cart_items.c.active)).scalar_one()
                existing=conn.execute(select(S.library_cart_items.c.id).where(S.library_cart_items.c.actor==actor,S.library_cart_items.c.library_version_id==payload["library_version_id"],S.library_cart_items.c.member_key==payload["member_key"],S.library_cart_items.c.active)).scalar_one_or_none()
                if count>=200 and not existing:raise ResourceError("选取清单最多保留200项，请先完成导入或移除已用项","cart_limit")
            row=conn.execute(pg_insert(S.library_cart_items).values(id=new_id(),actor=actor,**payload)
                .on_conflict_do_update(index_elements=[S.library_cart_items.c.actor,S.library_cart_items.c.library_version_id,S.library_cart_items.c.member_key],set_={"active":payload["active"]})
                .returning(S.library_cart_items.c.id)).scalar_one()
            return {"id":row,"active":payload["active"]}

    def import_item(self, project_id, payload, **kw):
        with self.store.engine.connect() as conn:
            item=conn.execute(select(S.library_cart_items).where(S.library_cart_items.c.id==payload["cart_id"],S.library_cart_items.c.actor==kw["actor"])).mappings().first()
            if not item:raise NotFound("选取清单中没有这个素材")
            version_id=item["library_version_id"]
        def work(conn,project):
            item=conn.execute(select(S.library_cart_items).where(S.library_cart_items.c.id==payload["cart_id"],S.library_cart_items.c.actor==kw["actor"]).with_for_update()).mappings().one()
            if not item["active"]:raise ResourceError("此素材已移出选取清单","cart_item_removed")
            target=payload.get("target_object_id") or str(uuid.uuid5(uuid.UUID(item["id"]),project["id"]+":asset:"+payload["asset_kind"]))
            existing=conn.execute(select(S.library_cart_imports).where(S.library_cart_imports.c.project_id==project["id"],S.library_cart_imports.c.cart_id==item["id"],S.library_cart_imports.c.target_object_id==target,S.library_cart_imports.c.role==payload["role"])).mappings().first()
            if existing:return clean(dict(existing))
            if not payload.get("target_object_id"):
                fixed=self.library._detail(conn,version_id)
                prior=conn.execute(select(S.creative_objects.c.id).where(S.creative_objects.c.project_id==project["id"],S.creative_objects.c.id==target)).scalar_one_or_none()
                if not prior:self.store._create_object(conn,project,{"id":target,"kind":"asset","asset_kind":payload["asset_kind"],"display_code":"LIB-"+item["id"][:12],"title":fixed["title"]})
            result=self.library.use(project["id"],{"library_version_id":version_id,"member_key":item["member_key"],"target_object_id":target,"role":payload["role"],"slot_key":"main","select":False},
                actor=kw["actor"],expected_revision=CURRENT_REVISION,idempotency_key="center-internal",_transaction=(conn,project))
            row=dict(id=new_id(),project_id=project["id"],cart_id=item["id"],target_object_id=target,role=payload["role"],actor=kw["actor"],media_id=result["media_id"],candidate_id=result["candidate_id"])
            conn.execute(insert(S.library_cart_imports).values(**row))
            return row
        return self.store._mutate(project_id,"import_asset_center_item",payload,callback=work,_library_versions=(version_id,),**kw)

    def download(self, payload, actor):
        # A request receipt records intent, never pretends the client saved bytes.
        self.library.content(payload["library_version_id"],payload["member_key"])
        with self.store.engine.begin() as conn:
            self.library._lock_key(conn,"download:"+actor+":"+payload["command_key"])
            previous=conn.execute(select(S.library_download_requests).where(S.library_download_requests.c.actor==actor,S.library_download_requests.c.command_key==payload["command_key"])).mappings().first()
            if previous:
                if any(previous[k]!=payload[k] for k in ("library_version_id","member_key")):raise Conflict("下载请求标识已用于其他素材","idempotency_conflict")
                return clean(dict(previous))
            row=dict(id=new_id(),actor=actor,**payload)
            conn.execute(insert(S.library_download_requests).values(**row));return row

    def downloads(self, actor, offset, limit):
        with self.store.engine.connect() as conn:
            query=select(S.library_download_requests).where(S.library_download_requests.c.actor==actor)
            total=conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows=conn.execute(query.order_by(S.library_download_requests.c.created_at.desc(),S.library_download_requests.c.id).offset(offset).limit(limit)).mappings().all()
            return clean({"items":[dict(row) for row in rows],"total":total})
