"""Recoverable media organization using the existing lifecycle decision authority."""
from sqlalchemy import and_, func, insert, select

from vsc.assets.resource_service import ResourceError, required
from . import schema as S
from .values import checked_id, clean, new_id


def recycled_ids(project_id):
    ranked = select(S.media_lifecycle_decisions.c.media_id,
                    S.media_lifecycle_decisions.c.id,
                    S.media_lifecycle_decisions.c.outcome,
                    func.row_number().over(
                        partition_by=S.media_lifecycle_decisions.c.media_id,
                        order_by=S.media_lifecycle_decisions.c.decision_sequence.desc()).label("rank")
                    ).where(S.media_lifecycle_decisions.c.project_id == project_id).subquery()
    actions = select(S.media_recycle_actions.c.decision_id).where(
        S.media_recycle_actions.c.project_id == project_id)
    return select(ranked.c.media_id).where(
        ranked.c.rank == 1, ranked.c.outcome == "deprecate", ranked.c.id.in_(actions))


class MediaRecycleRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def ids(value):
        if (not isinstance(value, list) or not 1 <= len(value) <= 100
                or any(not isinstance(item, str) for item in value)
                or len(set(value)) != len(value)):
            raise ResourceError("一次选择1至100个不同素材", "invalid_recycle_selection")
        return [checked_id(item) for item in value]

    def protections(self, conn, p, media_id):
        """Conservative fixed-input protection; history stays readable after trash."""
        reasons = []
        selected = select(S.current_bindings.c.slot_id).select_from(
            S.current_bindings.join(S.binding_candidates, and_(
                S.current_bindings.c.project_id == S.binding_candidates.c.project_id,
                S.current_bindings.c.candidate_id == S.binding_candidates.c.id))).where(
                    S.current_bindings.c.project_id == p,
                    S.binding_candidates.c.media_id == media_id).limit(1)
        if conn.execute(selected).first():
            reasons.append({"code": "selected", "label": "正在采用，请先替换或退役当前用料"})
        # These tables hold provenance, opinions or outputs. Keeping the blob and
        # registration makes their historical references safe; none is deleted.
        history = {"media_sources", "rights_decisions", "media_lifecycle_decisions",
                   "media_recycle_actions", "library_reuses", "media_checks",
                   "media_renditions", "binding_candidates", "operation_outputs",
                   "job_outputs", "quality_observations", "media_category_links",
                   "edit_preview_outputs"}
        labels = {
            "operation_inputs": "制作操作的固定输入",
            "job_input_media": "生成任务的固定输入",
            "voice_spec_versions": "角色声纹参考",
            "timeline_item_media": "剪辑用料",
            "render_inputs": "渲染输入", "render_outputs": "成片或已冻结输出",
            "execution_materials": "制作执行证据", "method_evaluations": "方法比较证据",
            "dispatch_media_refs": "专业任务的固定引用",
            "shot_design_panels": "分镜设计引用", "edit_preview_inputs": "修改预览输入",
        }
        for table in S.metadata.tables.values():
            if table.name in history or "project_id" not in table.c:
                continue
            columns = {fk.parent.name for fk in table.foreign_keys
                       if fk.column.table.name == "media_items" and fk.column.name == "id"}
            for column in columns:
                query = select(table.c[column]).where(
                    table.c.project_id == p, table.c[column] == media_id)
                if table.name == "preview_jobs":
                    query = query.where(table.c.status.in_(["created", "running"]))
                if conn.execute(query.limit(1)).first():
                    reasons.append({"code": table.name,
                                    "label": labels.get(table.name, "仍有制作任务或固定资料引用")})
                    break
        return reasons

    def _item(self, conn, p, row, recycled):
        row = dict(row)
        row["recycled"] = row["id"] in recycled
        row["can_restore"] = row["recycled"]
        row["reasons"] = self.protections(conn, p, row["id"])
        row["protected"] = bool(row["reasons"])
        return row

    def preview(self, project_id, media_ids):
        ids = self.ids(media_ids)
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            p = project["id"]
            recycled = set(conn.execute(recycled_ids(p)).scalars())
            rows = []
            for media_id in ids:
                row = self.store._media(conn, p, media_id)
                rows.append(self._item(conn, p, {key: row[key] for key in
                    ("id", "name", "modality", "sha256", "size_bytes")}, recycled))
            return clean({"project_id": p, "revision": project["revision"], "items": rows,
                          "released_bytes": 0, "permanent_delete_available": False})

    def read(self, project_id, view="trash", offset=0, limit=24):
        if (view not in {"trash", "duplicates"} or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 50):
            raise ResourceError("回收列表范围不合法", "invalid_page")
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            p = project["id"]
            recycled = set(conn.execute(recycled_ids(p)).scalars())
            query = select(S.media_items.c.id, S.media_items.c.name, S.media_items.c.modality,
                           S.media_items.c.blob_id, S.media_blobs.c.sha256, S.media_blobs.c.size_bytes
                           ).select_from(S.media_items.join(S.media_blobs)).where(
                               S.media_items.c.project_id == p)
            if view == "trash":
                query = query.where(S.media_items.c.id.in_(recycled_ids(p)))
                total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
                rows = conn.execute(query.order_by(S.media_items.c.name, S.media_items.c.id)
                                    .offset(offset).limit(limit)).mappings()
                items = [self._item(conn, p, row, recycled) for row in rows]
            else:
                groups = select(S.media_items.c.blob_id, func.count().label("count")).where(
                    S.media_items.c.project_id == p).group_by(S.media_items.c.blob_id).having(func.count() > 1)
                total = conn.execute(select(func.count()).select_from(groups.subquery())).scalar_one()
                items = []
                for blob_id, count in conn.execute(groups.order_by(S.media_items.c.blob_id)
                                                  .offset(offset).limit(limit)):
                    members = list(conn.execute(query.where(S.media_items.c.blob_id == blob_id)
                                                .order_by(S.media_items.c.id).limit(100)).mappings())
                    items.append({"id": blob_id, "sha256": members[0]["sha256"],
                                  "size_bytes": members[0]["size_bytes"], "total": count,
                                  "truncated": count > len(members),
                                  "items": [self._item(conn, p, row, recycled) for row in members]})
            return clean({"project_id": p, "revision": project["revision"], "items": items,
                          "total": total, "offset": offset, "limit": limit, "released_bytes": 0,
                          "permanent_delete_available": False})

    def act(self, project_id, payload, actor, **kw):
        ids = self.ids(required(payload, "media_ids"))
        action = payload.get("action")
        reason = required(payload, "reason")
        if (action not in {"trash", "restore"} or not isinstance(reason, str)
                or not reason.strip() or set(payload) - {"media_ids", "action", "reason"}):
            raise ResourceError("选择移入回收站或恢复，并说明原因", "invalid_payload")

        def work(conn, project):
            p = project["id"]
            recycled = set(conn.execute(recycled_ids(p)).scalars())
            results = []
            for media_id in ids:
                self.store._one(conn, S.media_items, p, media_id)
                if (action == "trash") == (media_id in recycled):
                    results.append({"id": media_id, "status": "unchanged"})
                    continue
                reasons = self.protections(conn, p, media_id) if action == "trash" else []
                if reasons:
                    results.append({"id": media_id, "status": "protected", "reasons": reasons})
                    continue
                decision = new_id()
                conn.execute(insert(S.media_lifecycle_decisions).values(
                    project_id=p, id=decision, media_id=media_id,
                    outcome="deprecate" if action == "trash" else "restore",
                    **self.store._decision(conn, project, actor, reason)))
                conn.execute(insert(S.media_recycle_actions).values(
                    project_id=p, id=new_id(), media_id=media_id, decision_id=decision))
                results.append({"id": media_id, "status": "trashed" if action == "trash" else "restored",
                                "decision_id": decision})
            return {"items": results, "released_bytes": 0}
        return self.store._mutate(project_id, "recycle_media", payload, actor=actor, callback=work, **kw)
