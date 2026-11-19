"""Persistence for in-canvas director stage recognition, captures and reference video."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update

from vsc.assets.canvas_director_stage import (
    LINKED_REJECT, SHOT_MODES, apply_recognition, dump_json, linked_panorama_blocked, load_preview, load_stage,
    plan_preview_edit,
)
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id, clean, new_id


def _stage_node(document, node_id, allowed):
    node = next((item for item in document["nodes"] if item["id"] == node_id), None)
    if not node or node["type"] not in allowed:
        raise ResourceError("请选择导演台或 3D 预演节点", "invalid_director_stage")
    return node


def _page(payload):
    offset = payload.get("offset", 0)
    limit = payload.get("limit", 20)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ResourceError("识图列表偏移无效", "invalid_director_stage")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ResourceError("识图列表长度须为 1–50", "invalid_director_stage")
    return offset, limit


def _record_row(row):
    result = row["result"]
    return {
        "id": row["id"], "canvas_id": row["canvas_id"], "node_key": row["node_key"],
        "kind": row["kind"], "status": row["status"], "media_id": row["media_id"],
        "result": dump_json(result) if row["status"] == 2 else None,
        "created_at": row["created_at"], "deleted": row["deleted"],
    }


class CanvasDirectorStageOps:
    def create_canvas_pic_recognize(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, project["id"], canvas, modified_node_keys=(payload.get("node_id"), payload.get("image_node_id")), actor=actor)
            stage = _stage_node(document, payload["node_id"], {"director-stage"})
            source, media = self._verified_canvas_image_source(conn, project["id"], document, payload["image_node_id"], "识图")
            doc = load_stage(stage.get("text") or "")
            if linked_panorama_blocked(doc, stage["id"], source["id"], document["edges"]):
                raise ResourceError(LINKED_REJECT, "linked_image_ai_import_unsupported")
            recognized = build(media)
            apply_recognition(doc, recognized, payload["strategy"])
            stage["text"] = dump_json(doc)
            record_id = new_id()
            conn.execute(insert(S.canvas_director_records).values(
                project_id=project["id"], id=record_id, canvas_id=canvas["id"], node_key=stage["id"],
                kind="recognize", status=2, media_id=media["id"], result=recognized, deleted=False,
            ))
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, success=True, task_id=record_id, status=2, result=dump_json(recognized), strategy=payload["strategy"])
        return self._mutate(project_id, "create_canvas_pic_recognize", payload, actor=actor, callback=work, **kw)

    def refresh_canvas_pic_recognize(self, project_id, canvas_id, task_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            canvas = checked_id(canvas_id)
            self._one(conn, S.creative_canvases, project["id"], canvas)
            row = conn.execute(select(S.canvas_director_records).where(
                S.canvas_director_records.c.project_id == project["id"],
                S.canvas_director_records.c.canvas_id == canvas,
                S.canvas_director_records.c.id == checked_id(task_id),
                S.canvas_director_records.c.kind == "recognize",
            )).mappings().first()
            if row is None:
                raise ResourceError("识图记录不存在", "not_found", 404)
            return clean(dict(_record_row(row), revision=project["revision"]))

    def list_canvas_pic_recognize(self, project_id, canvas_id, payload):
        offset, limit = _page(payload if isinstance(payload, dict) else {})
        kind = (payload or {}).get("kind") or "recognize"
        if kind not in {"recognize", "panorama"}:
            raise ResourceError("记录类型无效", "invalid_director_stage")
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            canvas = checked_id(canvas_id)
            self._one(conn, S.creative_canvases, project["id"], canvas)
            table = S.canvas_director_records
            filters = (table.c.project_id == project["id"], table.c.canvas_id == canvas, table.c.kind == kind, table.c.deleted.is_(False))
            total = conn.execute(select(func.count()).select_from(table).where(*filters)).scalar_one()
            rows = conn.execute(select(table).where(*filters).order_by(table.c.created_at.desc()).offset(offset).limit(limit)).mappings()
            return clean({"list": [_record_row(row) for row in rows], "total": int(total), "revision": project["revision"]})

    def delete_canvas_pic_recognize(self, project_id, payload, actor, **kw):
        def work(conn, project):
            canvas = checked_id(payload["canvas_id"])
            self._one(conn, S.creative_canvases, project["id"], canvas)
            table = S.canvas_director_records
            row = conn.execute(select(table).where(
                table.c.project_id == project["id"], table.c.canvas_id == canvas, table.c.id == checked_id(payload["task_id"]),
            )).mappings().first()
            if row is None:
                raise ResourceError("识图记录不存在", "not_found", 404)
            if not row["deleted"]:
                conn.execute(update(table).where(table.c.project_id == project["id"], table.c.id == row["id"]).values(
                    deleted=True, updated_at=datetime.now(timezone.utc)))
            return {"success": True, "task_id": row["id"]}
        return self._mutate(project_id, "delete_canvas_pic_recognize", payload, actor=actor, callback=work, **kw)

    def capture_director_stage_screenshots(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, project["id"], canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            stage = _stage_node(document, payload["node_id"], {"director-stage", "director"})
            prepared = build()
            expected = SHOT_MODES[payload["mode"]]
            if len(prepared) != expected:
                raise ResourceError("截图数量与方位模式不符", "invalid_director_stage")
            if len(document["nodes"]) + expected > 200 or len(document["edges"]) + expected > 800:
                raise ResourceError("截图数量超过画布上限", "invalid_director_stage")
            node_ids, media_ids = [], []
            doc = load_stage(stage["text"]) if stage["type"] == "director-stage" else None
            camera = None
            if doc is not None:
                active = doc["viewport"].get("activeView")
                camera = next((item for item in doc["cameras"] if item["id"] == active), doc["cameras"][0])
            for index, result in enumerate(prepared):
                probe = self._assert_complete_image_probe(result, "canvas_director_shot_unverified")
                registered = self._register_media(conn, project, {**result, "name": result.get("name") or f"导演台截图{index + 1}.png", "rights": "unknown", "source": {
                    "kind": "director-stage-capture",
                    "content": {"canvas_version_id": version["id"], "node_id": stage["id"], "mode": payload["mode"], "index": index},
                }}, actor)
                self.record_media_check(project["id"], {
                    "media_id": registered["id"], "blob_sha256": registered["sha256"],
                    "checker": "director-stage-screenshot", "criteria_version": "1", "outcome": "pass",
                    "report": {"source": "local-storage-complete-decode", "probe": probe},
                }, actor=actor, _transaction=(conn, project), **kw)
                key = "shot-" + new_id()
                node_ids.append(key)
                media_ids.append(registered["id"])
                label = {1: "当前视角", 4: "四方位", 12: "十二方位"}[expected]
                document["nodes"].append({
                    "id": key, "type": "image", "title": f"{stage['title']} · {label}{index + 1}"[:200],
                    "x": min(100000, stage["x"] + 320), "y": min(100000, stage["y"] + index * 180),
                    "text": "", "params": {"director_stage_capture": payload["mode"]}, "group": stage.get("group") or "",
                    "media_id": registered["id"], "job_id": None,
                })
                document["edges"].append({"id": "cap-" + new_id(), "source": stage["id"], "target": key, "port": "directorStageCapture"})
                if camera is not None and len(camera["screenshots"]) < 48:
                    camera["screenshots"].append({"id": "rec-" + key.replace("shot-", "")[:80], "mediaId": registered["id"], "label": f"{label}{index + 1}", "mode": payload["mode"]})
            if doc is not None:
                stage["text"] = dump_json(doc)
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, node_ids=node_ids, media_ids=media_ids, mode=payload["mode"])
        return self._mutate(project_id, "capture_director_stage_screenshots", payload, actor=actor, callback=work, **kw)

    def generate_director_panorama(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, project["id"], canvas, modified_node_keys=(payload.get("node_id"), payload.get("source_node_id")), actor=actor)
            stage = _stage_node(document, payload["node_id"], {"director-stage"})
            if len(document["nodes"]) + 1 > 200 or len(document["edges"]) + 1 > 800:
                raise ResourceError("全景节点超过画布上限", "invalid_director_stage")
            source = None
            media = None
            if payload.get("source_node_id"):
                source, media = self._verified_canvas_image_source(conn, project["id"], document, payload["source_node_id"], "全景生成")
            result = build(media)
            probe = self._assert_complete_image_probe(result, "canvas_director_panorama_unverified")
            registered = self._register_media(conn, project, {**result, "name": result.get("name") or "720全景.png", "rights": "unknown", "source": {
                "kind": "director-stage-panorama",
                "content": {"canvas_version_id": version["id"], "node_id": stage["id"], "source_node_id": source["id"] if source else None, "sourceType": "image_to_panorama"},
            }}, actor)
            self.record_media_check(project["id"], {
                "media_id": registered["id"], "blob_sha256": registered["sha256"],
                "checker": "director-stage-panorama", "criteria_version": "1", "outcome": "pass",
                "report": {"source": "local-equirectangular", "probe": probe},
            }, actor=actor, _transaction=(conn, project), **kw)
            image_id = "pano-" + new_id()
            document["nodes"].append({
                "id": image_id, "type": "image", "title": "720°全景图",
                "x": min(100000, stage["x"] - 320), "y": stage["y"], "text": "",
                "params": {"director_panorama_origin": "image_to_panorama"}, "group": stage.get("group") or "",
                "media_id": registered["id"], "job_id": None,
            })
            document["edges"] = [edge for edge in document["edges"] if not (edge["target"] == stage["id"] and edge["port"] == "panorama_image")]
            document["edges"].append({"id": "pano-edge-" + new_id(), "source": image_id, "target": stage["id"], "port": "panorama_image"})
            doc = load_stage(stage.get("text") or "")
            doc["panorama"]["origin"] = "image_to_panorama"
            doc["panorama"]["radius"] = doc["panorama"].get("radius") or 60
            stage["text"] = dump_json(doc)
            record_id = new_id()
            conn.execute(insert(S.canvas_director_records).values(
                project_id=project["id"], id=record_id, canvas_id=canvas["id"], node_key=stage["id"],
                kind="panorama", status=2, media_id=registered["id"],
                result={"sourceType": "image_to_panorama", "mediaId": registered["id"], "imageNodeId": image_id},
                deleted=False,
            ))
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, success=True, task_id=record_id, media_id=registered["id"], node_id=image_id, status=2)
        return self._mutate(project_id, "generate_director_panorama", payload, actor=actor, callback=work, **kw)

    def export_director_reference_video(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, project["id"], canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            stage = _stage_node(document, payload["node_id"], {"3d-preview"})
            if len(document["nodes"]) + 2 > 200 or len(document["edges"]) + 1 > 800:
                raise ResourceError("参考视频节点超过画布上限", "invalid_reference_video")
            result, meta = build()
            if result.get("modality") != "video" or not isinstance(result.get("duration_ms"), int) or result["duration_ms"] <= 0:
                raise ResourceError("参考视频缺少实测时长", "invalid_reference_video")
            if result.get("size_bytes", 0) > 8 * 1024 * 1024 or max(result.get("width") or 0, result.get("height") or 0) > 960:
                raise ResourceError("参考视频超出画幅或体积约束", "invalid_reference_video")
            registered = self._register_media(conn, project, {**result, "name": "压缩参考视频.mp4", "rights": "unknown", "source": {
                "kind": "director-reference-video",
                "content": {"canvas_version_id": version["id"], "node_id": stage["id"], **meta},
            }}, actor)
            self.record_media_check(project["id"], {
                "media_id": registered["id"], "blob_sha256": registered["sha256"],
                "checker": "director-reference-video", "criteria_version": "1", "outcome": "pass",
                "report": {"source": "local-ffmpeg", **meta},
            }, actor=actor, _transaction=(conn, project), **kw)
            source_id = "refv-" + new_id()
            generator_id = "genv-" + new_id()
            document["nodes"].append({
                "id": source_id, "type": "video", "title": "压缩参考视频",
                "x": min(100000, stage["x"] + 320), "y": stage["y"], "text": "",
                "params": {"vsc_node_kind": "source"}, "group": "", "media_id": registered["id"], "job_id": None,
            })
            document["nodes"].append({
                "id": generator_id, "type": "video", "title": "全能参考生视频",
                "x": min(100000, stage["x"] + 640), "y": stage["y"], "text": "",
                "params": {"vsc_operation": "seedance_omni_video", "vsc_node_kind": "generator"},
                "group": "", "media_id": None, "job_id": None,
            })
            document["edges"].append({"id": "refv-edge-" + new_id(), "source": source_id, "target": generator_id, "port": "reference_video"})
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, media_id=registered["id"], node_ids=[source_id, generator_id], reference_node_id=source_id, generator_node_id=generator_id, **meta)
        return self._mutate(project_id, "export_director_reference_video", payload, actor=actor, callback=work, **kw)

    def edit_preview_scene(self, project_id, payload, actor, **kw):
        def work(conn, project):
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, project["id"], canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            stage = _stage_node(document, payload["node_id"], {"3d-preview"})
            preview = load_preview(stage.get("text") or "", stage["id"])
            plan_preview_edit(preview, payload.get("text") or "", has_image=bool(payload.get("reference_media_id")))
            stage["text"] = dump_json(preview)
            saved = self._insert_canvas_version(conn, project, canvas, {"title": version["title"], "document": document}, actor, version)
            return dict(saved, mode=preview["mode"], playhead=preview["playhead"], object_count=len(preview["stage"]["objects"]),
                        document_ref=preview["documentRef"], timeline=preview["timelineSummary"])
        return self._mutate(project_id, "edit_preview_scene", payload, actor=actor, callback=work, **kw)


def bind_canvas_director_stage_repository(cls):
    for name in (
        "create_canvas_pic_recognize", "refresh_canvas_pic_recognize", "list_canvas_pic_recognize",
        "delete_canvas_pic_recognize", "capture_director_stage_screenshots", "generate_director_panorama",
        "export_director_reference_video", "edit_preview_scene",
    ):
        setattr(cls, name, getattr(CanvasDirectorStageOps, name))
