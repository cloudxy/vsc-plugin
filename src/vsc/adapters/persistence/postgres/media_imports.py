"""Original project commands compose file registration without duplicate results."""
import secrets
import uuid
from sqlalchemy import select, insert, update, func

from vsc.assets.resource_service import ResourceError, Conflict
from . import schema as S
from .values import CURRENT_REVISION, checked_id, new_id, clean, verify_sha


class MediaImportRepository:
    def __init__(self, store):
        self.store = store

    def list(self, project_id, offset=0, limit=50):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            query = select(S.media_import_batches).where(S.media_import_batches.c.project_id==project["id"])
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(query.order_by(S.media_import_batches.c.created_at.desc(), S.media_import_batches.c.id)
                .offset(offset).limit(limit)).mappings().all()
            return clean({"items": [dict(r) for r in rows], "total":total, "next_offset":offset+len(rows) if offset+len(rows)<total else None,
                          "revision": project["revision"]})

    def get(self, project_id, batch_id):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            batch = self.store._one(conn, S.media_import_batches, project["id"], batch_id)
            items = conn.execute(select(S.media_import_items).where(S.media_import_items.c.project_id==project["id"],
                S.media_import_items.c.batch_id==batch["id"]).order_by(S.media_import_items.c.ordinal)).mappings().all()
            return clean({"batch": batch, "items": [dict(row) for row in items], "revision": project["revision"]})

    def _item(self, conn, project_id, batch_id, item_id):
        self.store._one(conn, S.media_import_batches, project_id, batch_id)
        item = self.store._one(conn, S.media_import_items, project_id, item_id)
        if item["batch_id"] != checked_id(batch_id):
            raise ResourceError("文件不属于本次导入清单", "import_scope_mismatch")
        return item

    def item(self, project_id, batch_id, item_id):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            return clean(self._item(conn, project["id"], batch_id, item_id))

    def create(self, project_id, payload, **kw):
        def work(conn, project):
            p, row_id = project["id"], new_id()
            if payload.get("episode_id"):
                self.store._one(conn, S.episodes, p, payload["episode_id"])
            conn.execute(insert(S.media_import_batches).values(project_id=p, id=row_id,
                episode_id=payload.get("episode_id"), title=str(payload.get("title") or "素材导入")[:200],
                asset_kind=payload.get("asset_kind"), rights=payload["rights"], rights_scope=payload["rights_scope"],
                source_evidence=payload["source_evidence"], member_count=len(payload["files"]), created_by=kw["actor"]))
            for ordinal, file in enumerate(payload["files"]):
                conn.execute(insert(S.media_import_items).values(project_id=p, id=new_id(), batch_id=row_id,
                    ordinal=ordinal, filename=file["filename"], size_bytes=file["size_bytes"],
                    expected_sha256=verify_sha(file["sha256"]) if file.get("sha256") else None,
                    upload_key=secrets.token_hex(24), status="awaiting_upload"))
            return {"id": row_id, "item_count": len(payload["files"])}
        return self.store._mutate(project_id, "create_media_import", payload, callback=work, **kw)

    def uploaded(self, project_id, batch_id, item_id, metadata, actor):
        def work(conn, project):
            item = self._item(conn, project["id"], batch_id, item_id)
            if item["status"] == "cancelled":
                raise Conflict("该文件已取消，收到的字节不会继续登记", "import_cancelled")
            if metadata["size_bytes"] != item["size_bytes"] or item["expected_sha256"] not in {None, metadata["sha256"]}:
                raise ResourceError("已上传字节与清单不符", "import_manifest_mismatch")
            if item["uploaded_metadata"]:
                if item["uploaded_metadata"]["sha256"] != metadata["sha256"]:
                    raise Conflict("已固定文件不能被另一份字节替换", "import_upload_changed")
                return {"id": item_id, "status": item["status"]}
            conn.execute(update(S.media_import_items).where(S.media_import_items.c.project_id==project["id"],
                S.media_import_items.c.id==item_id).values(status="uploaded", uploaded_metadata=metadata, error=None))
            return {"id": item_id, "status": "uploaded"}
        return self.store._mutate(project_id, "finish_import_upload", {"batch_id": batch_id, "item_id": item_id, "sha256": metadata["sha256"]},
            callback=work, expected_revision=CURRENT_REVISION, actor=actor, idempotency_key="import-upload:"+item_id+":"+metadata["sha256"])

    def process(self, project_id, payload, **kw):
        def work(conn, project):
            p = project["id"]
            item = self._item(conn, p, payload["batch_id"], payload["item_id"])
            if item["status"] == "completed":
                return {"id": item["id"], "status": "completed", "media_id": item["media_id"], "asset_id": item["asset_id"]}
            if item["status"] == "cancelled" or not item["uploaded_metadata"]:
                raise ResourceError("文件尚未完整上传或已取消", "import_not_uploaded")
            batch = self.store._one(conn, S.media_import_batches, p, item["batch_id"])
            data = item["uploaded_metadata"]
            kind = batch["asset_kind"]
            if kind and data["modality"] != ("audio" if kind=="voice" else "image"):
                raise ResourceError("文件类型不适用于所选资产；已上传文件保留在清单", "import_asset_modality")
            media_id = str(uuid.uuid5(uuid.UUID(item["id"]), "media"))
            self.store._register_media(conn, project, dict(data, id=media_id, name=item["filename"],
                rights=batch["rights"], rights_scope=batch["rights_scope"],
                source={"kind": "file-import", "source_key": "import:"+item["id"],
                        "content": {"filename": item["filename"], "sha256": data["sha256"], "evidence": batch["source_evidence"]}}), kw["actor"])
            asset_id = None
            if kind:
                asset_id = str(uuid.uuid5(uuid.UUID(item["id"]), "asset"))
                self.store._create_object(conn, project, {"id": asset_id, "kind": "asset", "asset_kind": kind,
                    "display_code": "IMPORT-"+item["id"][:12], "title": item["filename"]})
                role = {"character": "identity_face", "location": "location_master", "prop": "prop", "voice": "voice_sample"}[kind]
                self.store.propose_binding(p, {"target_object_id": asset_id, "media_id": media_id, "role": role, "slot_key": "main"},
                    expected_revision=CURRENT_REVISION, idempotency_key="import-binding:"+item["id"], actor=kw["actor"], _transaction=(conn, project))
                from .asset_cards import AssetCardsRepository
                cards=AssetCardsRepository(self.store)
                saved=cards._save_asset_card(conn,project,dict(asset_id=asset_id,name=item["filename"],asset_kind=kind,base_revision=0,forms=[dict(form_key="master",name="默认形态",base_version_id=None,media_id=media_id,description="")]),kw["actor"])
                if batch['episode_id']:
                    cards.reference_asset_card(p,dict(asset_id=asset_id,asset_revision=saved['asset_revision'],episode_ids=[batch['episode_id']]),actor=kw['actor'],expected_revision=CURRENT_REVISION,idempotency_key='import-episode:'+item['id'],_transaction=(conn,project))
            conn.execute(update(S.media_import_items).where(S.media_import_items.c.project_id==p,
                S.media_import_items.c.id==item["id"]).values(status="completed", media_id=media_id, asset_id=asset_id, error=None))
            return {"id": item["id"], "status": "completed", "media_id": media_id, "asset_id": asset_id}
        try:
            return self.store._mutate(project_id, "process_media_import_item", payload, callback=work, **kw)
        except Conflict:
            raise
        except ResourceError as error:
            self.fail(project_id, payload["batch_id"], payload["item_id"], error.message, kw["actor"])
            raise

    def fail(self, project_id, batch_id, item_id, message, actor):
        def work(conn, project):
            item = self._item(conn, project["id"], batch_id, item_id)
            if item["status"] in {"completed", "cancelled"}:
                return {"id": item_id, "status": item["status"]}
            conn.execute(update(S.media_import_items).where(S.media_import_items.c.project_id==project["id"],
                S.media_import_items.c.id==item_id).values(status="failed", error=message[:1200]))
            return {"id": item_id, "status": "failed"}
        return self.store._mutate(project_id, "fail_media_import_item", {"item_id": item_id, "message": message[:1200]},
            expected_revision=CURRENT_REVISION, idempotency_key="import-fail:"+new_id(), actor=actor, callback=work)

    def cancel(self, project_id, payload, **kw):
        def work(conn, project):
            item = self._item(conn, project["id"], payload["batch_id"], payload["item_id"])
            if item["status"] == "completed":
                raise ResourceError("已经登记的素材请从素材回收入口处理", "import_already_completed", 409)
            conn.execute(update(S.media_import_items).where(S.media_import_items.c.project_id==project["id"],
                S.media_import_items.c.id==item["id"]).values(status="cancelled"))
            return {"id": item["id"], "status": "cancelled"}
        return self.store._mutate(project_id, "cancel_media_import_item", payload, callback=work, **kw)
