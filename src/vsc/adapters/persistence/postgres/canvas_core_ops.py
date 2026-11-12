"""Canvas core local image operations, agent session state/queue, and camera motion templates."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from . import schema as S
from .values import checked_id, clean, new_id


BUILTIN_CAMERA_MOTIONS = (
    {"id": "builtin-push-in", "name": "推进镜头 Push In", "prompt_fragment": "摄影机平稳缓慢向前推进，聚焦主体细节", "horizontal_pan": 0, "vertical_tilt": 0, "zoom_delta": 50, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-pull-out", "name": "拉远镜头 Pull Out", "prompt_fragment": "摄影机平稳向后拉远，逐渐展现完整环境空间", "horizontal_pan": 0, "vertical_tilt": 0, "zoom_delta": -50, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-truck-left", "name": "左移镜头 Truck Left", "prompt_fragment": "摄影机沿水平轨道向左平移跟拍", "horizontal_pan": -55, "vertical_tilt": 0, "zoom_delta": 0, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-truck-right", "name": "右移镜头 Truck Right", "prompt_fragment": "摄影机沿水平轨道向右平移跟拍", "horizontal_pan": 55, "vertical_tilt": 0, "zoom_delta": 0, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-tilt-up", "name": "上摇镜头 Tilt Up", "prompt_fragment": "摄影机由低向高缓慢仰摇，凸显空间纵深与气势", "horizontal_pan": 0, "vertical_tilt": 45, "zoom_delta": 10, "roll_deg": 0, "speed_preset": "slow", "builtin": True},
    {"id": "builtin-tilt-down", "name": "下摇镜头 Tilt Down", "prompt_fragment": "摄影机由高处俯摇下降，自然落幅至人物主体", "horizontal_pan": 0, "vertical_tilt": -45, "zoom_delta": 10, "roll_deg": 0, "speed_preset": "slow", "builtin": True},
    {"id": "builtin-orbit", "name": "环绕运镜 Orbit", "prompt_fragment": "摄影机围绕主体呈圆弧轨迹平滑环绕拍摄", "horizontal_pan": 65, "vertical_tilt": 10, "zoom_delta": 15, "roll_deg": 0, "speed_preset": "normal", "builtin": True},
    {"id": "builtin-handheld", "name": "手持呼吸跟拍 Handheld", "prompt_fragment": "电影感手持摄影机轻微呼吸晃动，贴近角色跟拍", "horizontal_pan": 12, "vertical_tilt": 8, "zoom_delta": 20, "roll_deg": 4, "speed_preset": "fast", "builtin": True},
)

_IMAGE_EDIT_GAP_LABELS = {
    "missing_bytes": "素材文件不可用",
    "rights_unknown_or_restricted": "素材权利待确认或受限制",
    "rights_expired": "素材授权已到期",
    "rights_scope_mismatch": "素材授权不包含图片编辑",
    "media_deprecated": "素材已停用",
    "technical_check_failed": "素材技术检查未通过",
    "library_retired": "素材库条目已停用",
    "library_rights_revoked": "素材库许可已撤回",
    "library_license_expired": "素材库许可已到期",
    "library_purpose_not_allowed": "素材库许可不包含图片编辑",
    "library_source_rights_changed": "素材库来源权利已变化",
    "copy_source_rights_restricted": "来源权利已受限制",
    "copy_source_rights_expired": "来源授权已到期",
    "copy_source_rights_unknown": "来源权利待确认",
    "copy_source_rights_scope_mismatch": "来源授权不包含图片编辑",
}


class CanvasCoreOpsMixin:
    def _verified_canvas_image_source(self, conn, p, document, node_id, action_label):
        source = next((node for node in document["nodes"] if node["id"] == node_id), None)
        if not source or source["type"] != "image" or not source["media_id"]:
            raise ResourceError("请选择已固定图片的画布节点", "canvas_image_source_required")
        media, gaps = self._usable(conn, p, source["media_id"], "image_edit")
        gaps = [gap for gap in gaps if gap != "technical_check_missing"]
        if gaps:
            reason = "、".join(_IMAGE_EDIT_GAP_LABELS.get(gap, "来源或许可不可用") for gap in gaps)
            raise ResourceError(f"原图当前不可{action_label}：{reason}", "canvas_image_source_unusable")
        if media["modality"] != "image":
            raise ResourceError(f"{action_label}只接受图片", "canvas_image_source_required")
        return source, media

    @staticmethod
    def _assert_complete_image_probe(result, error_code):
        probe = result.get("probe", {})
        if (
            result.get("modality") != "image"
            or probe.get("sha256") != result.get("sha256")
            or probe.get("decode", {}).get("status") != "passed"
            or probe.get("decode", {}).get("mode") != "complete"
        ):
            raise ResourceError("派生图片缺少固定字节的完整解码检查", error_code)
        return probe

    def transform_canvas_image(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_image_source(conn, p, document, payload["node_id"], "编辑")
            in_place = bool(payload.get("in_place", False))
            if not in_place and (len(document["nodes"]) + 1 > 200 or len(document["edges"]) + 1 > 800):
                raise ResourceError("编辑输出超过画布节点或连线数量上限", "canvas_transform_capacity")
            result, normalized_settings, title_suffix = build(media)
            probe = self._assert_complete_image_probe(result, "canvas_transform_output_unverified")
            registered = self._register_media(
                conn,
                project,
                {
                    **result,
                    "rights": "unknown",
                    "source": {
                        "kind": "canvas-image-transform",
                        "content": {
                            "canvas_version_id": version["id"],
                            "source_media_id": media["id"],
                            "source_sha256": media["sha256"],
                            "operation": payload["operation"],
                            "settings": normalized_settings,
                        },
                    },
                },
                actor,
            )
            self.record_media_check(
                p,
                {
                    "media_id": registered["id"],
                    "blob_sha256": registered["sha256"],
                    "checker": "canvas-transform-output-decode",
                    "criteria_version": "1",
                    "outcome": "pass",
                    "report": {"source": "local-storage-complete-decode", "probe": probe},
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            group_name = payload.get("group_name") if payload.get("group_name") is not None else source.get("group", "")
            if in_place:
                source["media_id"] = registered["id"]
                source["job_id"] = None
                if group_name:
                    source["group"] = group_name
                node_ids = [source["id"]]
            else:
                key = "transform-" + new_id()
                node_ids = [key]
                document["nodes"].append({
                    "id": key,
                    "type": "image",
                    "title": f"{source['title']} · {title_suffix}"[:200],
                    "x": min(100000, source["x"] + 300),
                    "y": source["y"],
                    "text": "",
                    "params": {},
                    "group": group_name or "",
                    "media_id": registered["id"],
                    "job_id": None,
                })
                document["edges"].append({
                    "id": "derive-" + new_id(),
                    "source": source["id"],
                    "target": key,
                    "port": "derived_from",
                })
            operation = self.create_media_operation(
                p,
                {
                    "operation_type": "image-canvas-transform",
                    "recipe_version": "canvas-transform/v1",
                    "tool": "vsc-local-image-transform",
                    "tool_version": "1",
                    "parameters": {
                        "canvas_version_id": version["id"],
                        "source_sha256": media["sha256"],
                        "operation": payload["operation"],
                        "settings": normalized_settings,
                        "output_count": 1,
                    },
                    "inputs": [{"media_id": media["id"], "role": "source"}],
                    "outputs": [{"media_id": registered["id"], "role": "transformed"}],
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_ids=node_ids, media_ids=[registered["id"]], operation_id=operation["id"])

        return self._mutate(project_id, "transform_canvas_image", payload, actor=actor, callback=work, **kw)

    def capture_canvas_panorama(self, project_id, payload, *, build, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            source, media = self._verified_canvas_image_source(conn, p, document, payload["node_id"], "全景截图")
            expected_count = {"current": 1, "four": 4, "twelve": 12}[payload["mode"]]
            if len(document["nodes"]) + expected_count > 200 or len(document["edges"]) + expected_count > 800:
                raise ResourceError("全景截图数量超过画布节点或连线数量上限", "canvas_panorama_capacity")
            prepared = build(media)
            if len(prepared) != expected_count:
                raise ResourceError("全景截图输出数量与所选模式不符", "canvas_panorama_output_mismatch")
            group_name = payload.get("group_name") if payload.get("group_name") is not None else source.get("group", "")
            node_ids, media_ids = [], []
            for index, item in enumerate(prepared):
                result, view_meta = item["staged"], item["view"]
                probe = self._assert_complete_image_probe(result, "canvas_panorama_output_unverified")
                registered = self._register_media(
                    conn,
                    project,
                    {
                        **result,
                        "rights": "unknown",
                        "source": {
                            "kind": "canvas-panorama-capture",
                            "content": {
                                "canvas_version_id": version["id"],
                                "source_media_id": media["id"],
                                "source_sha256": media["sha256"],
                                "mode": payload["mode"],
                                "yaw": view_meta["yaw"],
                                "pitch": view_meta["pitch"],
                                "fov": view_meta["fov"],
                                "label": view_meta["label"],
                            },
                        },
                    },
                    actor,
                )
                self.record_media_check(
                    p,
                    {
                        "media_id": registered["id"],
                        "blob_sha256": registered["sha256"],
                        "checker": "canvas-panorama-output-decode",
                        "criteria_version": "1",
                        "outcome": "pass",
                        "report": {"source": "local-storage-complete-decode", "probe": probe},
                    },
                    actor=actor,
                    _transaction=(conn, project),
                    **kw,
                )
                key = "pano-" + new_id()
                node_ids.append(key)
                media_ids.append(registered["id"])
                document["nodes"].append({
                    "id": key,
                    "type": "image",
                    "title": f"{source['title']} · {view_meta['label']}"[:200],
                    "x": min(100000, source["x"] + 320 + (index % 4) * 280),
                    "y": min(100000, source["y"] + (index // 4) * 230),
                    "text": "",
                    "params": {},
                    "group": group_name or "",
                    "media_id": registered["id"],
                    "job_id": None,
                })
                document["edges"].append({
                    "id": "derive-" + new_id(),
                    "source": source["id"],
                    "target": key,
                    "port": "derived_from",
                })
            operation = self.create_media_operation(
                p,
                {
                    "operation_type": "image-panorama-capture",
                    "recipe_version": "canvas-panorama/v1",
                    "tool": "vsc-local-panorama-capture",
                    "tool_version": "1",
                    "parameters": {
                        "canvas_version_id": version["id"],
                        "source_sha256": media["sha256"],
                        "mode": payload["mode"],
                        "yaw": payload["yaw"],
                        "pitch": payload["pitch"],
                        "fov": payload["fov"],
                        "output_count": expected_count,
                    },
                    "inputs": [{"media_id": media["id"], "role": "source"}],
                    "outputs": [{"media_id": mid, "role": "view"} for mid in media_ids],
                },
                actor=actor,
                _transaction=(conn, project),
                **kw,
            )
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_ids=node_ids, media_ids=media_ids, operation_id=operation["id"])

        return self._mutate(project_id, "capture_canvas_panorama", payload, actor=actor, callback=work, **kw)

    def replace_canvas_node_media(self, project_id, payload, actor, **kw):
        from .copy_lineage import assert_copy_source
        from .media_recycle import recycled_ids

        def work(conn, project):
            p = project["id"]
            canvas, version, document = self._canvas_current(conn, project, payload)
            self._require_canvas_edit(conn, p, canvas, modified_node_keys=(payload.get("node_id"),), actor=actor)
            target = next((node for node in document["nodes"] if node["id"] == payload["node_id"]), None)
            if not target or target["type"] not in {"image", "video", "audio"}:
                raise ResourceError("请选择图片、视频或音频节点进行素材替换", "canvas_replace_target_invalid")
            media_id = checked_id(payload["media_id"])
            if media_id in set(conn.execute(recycled_ids(p)).scalars()):
                raise ResourceError("目标素材已在回收站中，请先恢复后再替换", "canvas_replace_media_recycled", 409)
            media = self._media(conn, p, media_id)
            if media["modality"] != target["type"]:
                raise ResourceError("替换素材类型必须与节点类型一致", "canvas_media_type")
            assert_copy_source(self, conn, p, media_id)
            gaps = []
            lifecycle = self._latest(conn, S.media_lifecycle_decisions, p, "media_id", media_id)
            if lifecycle and lifecycle["outcome"] == "deprecate":
                gaps.append("media_deprecated")
            checks = conn.execute(
                select(S.media_checks)
                .where(S.media_checks.c.project_id == p, S.media_checks.c.media_id == media_id)
                .order_by(S.media_checks.c.project_revision.desc(), S.media_checks.c.id)
            ).mappings()
            latest = {}
            for check in checks:
                latest.setdefault((check["checker"], check["criteria_version"]), check)
            if any(check["outcome"] != "pass" for check in latest.values()):
                gaps.append("technical_check_failed")
            grid = self._grid_parent(conn, p, media_id)
            if grid:
                _, parents = self._usable(conn, p, grid[0], "image_edit")
                gaps.extend("grid_source_" + gap for gap in parents if gap != "technical_check_missing")
            if gaps:
                raise ResourceError("替换素材当前不可用于画布：" + ", ".join(gaps), "canvas_replace_media_unavailable")
            if not any(loc["available"] for loc in media["locations"]):
                raise ResourceError("替换素材没有可用存储副本", "canvas_replace_media_unavailable")
            target["media_id"] = media["id"]
            target["job_id"] = None
            if payload.get("title"):
                target["title"] = payload["title"].strip()[:200]
            saved = self._insert_canvas_version(
                conn, project, canvas, {"title": version["title"], "document": document}, actor, version
            )
            return dict(saved, node_id=target["id"], media_id=media["id"])

        return self._mutate(project_id, "replace_canvas_node_media", payload, actor=actor, callback=work, **kw)

    def list_canvas_agent_sessions(self, project_id, canvas_id, *, include_archived=False):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            self._access_require(conn, p, "read")
            canvas = self._one(conn, S.creative_canvases, p, canvas_id)
            from .project_management import filter_management_rows
            if not filter_management_rows(conn, p, S.creative_canvases, [canvas]):
                raise ResourceError("画布所属对象已回收", "object_recycled", 409)
            sessions = list(
                conn.execute(
                    select(S.canvas_agent_sessions)
                    .where(S.canvas_agent_sessions.c.project_id == p, S.canvas_agent_sessions.c.canvas_id == canvas_id)
                    .order_by(S.canvas_agent_sessions.c.created_at.desc())
                ).mappings()
            )
            if not sessions:
                return []
            session_ids = [row["id"] for row in sessions]
            state_map = {
                row["session_id"]: dict(row)
                for row in conn.execute(
                    select(S.canvas_agent_session_states).where(
                        S.canvas_agent_session_states.c.project_id == p,
                        S.canvas_agent_session_states.c.session_id.in_(session_ids),
                    )
                ).mappings()
            }
            queue_rows = list(
                conn.execute(
                    select(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id.in_(session_ids),
                        S.canvas_agent_queue_items.c.status.in_(("queued", "steered", "editing")),
                    )
                    .order_by(
                        (S.canvas_agent_queue_items.c.status == "steered").desc(),
                        S.canvas_agent_queue_items.c.ordinal.asc(),
                        S.canvas_agent_queue_items.c.created_at.asc(),
                    )
                ).mappings()
            )
            queues_by_session = {}
            for q in queue_rows:
                queues_by_session.setdefault(q["session_id"], []).append(dict(q))
            output = []
            for session in sessions:
                st = state_map.get(session["id"])
                archived = bool(st["archived"]) if st else False
                if archived and not include_archived:
                    continue
                ids = conn.execute(
                    select(S.canvas_agent_turns.c.id)
                    .where(S.canvas_agent_turns.c.project_id == p, S.canvas_agent_turns.c.session_id == session["id"])
                    .order_by(S.canvas_agent_turns.c.created_at)
                ).scalars()
                effective_title = st["title"] if st else session["title"]
                output.append(
                    dict(
                        session,
                        title=effective_title,
                        original_title=session["title"],
                        archived=archived,
                        auto_approve=bool(st["auto_approve"]) if st else False,
                        queue=queues_by_session.get(session["id"], []),
                        turns=[self._canvas_agent_turn(conn, project, i) for i in ids],
                    )
                )
            return clean({"items": output, "revision": project["revision"]})

    def update_canvas_agent_session_state(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            canvas = self._one(conn, S.creative_canvases, p, payload["canvas_id"])
            self._require_canvas_edit(conn, p, canvas, actor=actor)
            session = self._one(conn, S.canvas_agent_sessions, p, payload["session_id"])
            if session["canvas_id"] != canvas["id"]:
                raise ResourceError("会话不属于当前画布", "canvas_agent_session_scope")
            existing = conn.execute(
                select(S.canvas_agent_session_states).where(
                    S.canvas_agent_session_states.c.project_id == p,
                    S.canvas_agent_session_states.c.session_id == session["id"],
                )
            ).mappings().first()
            next_title = payload["title"].strip() if "title" in payload and payload["title"] is not None else (existing["title"] if existing else session["title"])
            next_archived = payload["archived"] if "archived" in payload and payload["archived"] is not None else (bool(existing["archived"]) if existing else False)
            next_auto = payload["auto_approve"] if "auto_approve" in payload and payload["auto_approve"] is not None else (bool(existing["auto_approve"]) if existing else False)
            now = datetime.now(timezone.utc)
            conn.execute(
                pg_insert(S.canvas_agent_session_states)
                .values(
                    project_id=p,
                    session_id=session["id"],
                    title=next_title,
                    archived=next_archived,
                    auto_approve=next_auto,
                    updated_by=actor,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["project_id", "session_id"],
                    set_={
                        "title": next_title,
                        "archived": next_archived,
                        "auto_approve": next_auto,
                        "updated_by": actor,
                        "updated_at": now,
                    },
                )
            )
            return {
                "session_id": session["id"],
                "canvas_id": canvas["id"],
                "title": next_title,
                "archived": next_archived,
                "auto_approve": next_auto,
            }

        return self._mutate(project_id, "update_canvas_agent_session_state", payload, actor=actor, callback=work, **kw)

    def mutate_canvas_agent_queue(self, project_id, payload, actor, **kw):
        from vsc.production.canvas_agent import SKILLS

        def work(conn, project):
            p = project["id"]
            canvas = self._one(conn, S.creative_canvases, p, payload["canvas_id"])
            self._require_canvas_edit(conn, p, canvas, actor=actor)
            session = self._one(conn, S.canvas_agent_sessions, p, payload["session_id"])
            if session["canvas_id"] != canvas["id"]:
                raise ResourceError("会话不属于当前画布", "canvas_agent_session_scope")
            action = payload["action"]
            now = datetime.now(timezone.utc)
            if action == "enqueue":
                skill_id = payload.get("skill_id", "vsc-script")
                mode = payload.get("mode", "manual")
                message = (payload.get("message") or "").strip()
                if not message or len(message) > 6000 or skill_id not in SKILLS or mode not in {"manual", "auto_drafts"}:
                    raise ResourceError("入队消息需要有效文本、已装技能与模式", "invalid_agent_queue_item")
                active_count = conn.scalar(
                    select(func.count())
                    .select_from(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id == session["id"],
                        S.canvas_agent_queue_items.c.status.in_(("queued", "steered")),
                    )
                )
                if (active_count or 0) >= 20:
                    raise ResourceError("单个会话待发送队列最多保留 20 条消息", "agent_queue_limit")
                ordinal = conn.scalar(
                    select(func.coalesce(func.max(S.canvas_agent_queue_items.c.ordinal), -1) + 1).where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.session_id == session["id"],
                    )
                )
                item_id = new_id()
                conn.execute(
                    insert(S.canvas_agent_queue_items).values(
                        project_id=p,
                        id=item_id,
                        session_id=session["id"],
                        ordinal=int(ordinal or 0),
                        message=message,
                        skill_id=skill_id,
                        mode=mode,
                        status="queued",
                        created_by=actor,
                        created_at=now,
                        updated_at=now,
                    )
                )
                row = dict(self._one(conn, S.canvas_agent_queue_items, p, item_id))
                return {"item": row, "action": "enqueue"}

            item = self._one(conn, S.canvas_agent_queue_items, p, payload.get("queue_item_id"))
            if item["session_id"] != session["id"]:
                raise ResourceError("队列消息不属于当前会话", "agent_queue_item_scope")
            if action == "steer":
                if item["status"] not in {"queued", "steered", "editing"}:
                    raise Conflict("该队列消息已处理或已取消", "agent_queue_item_closed")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="steered", ordinal=0, updated_at=now)
                )
                return {"item": dict(item, status="steered", ordinal=0), "action": "steer"}
            if action == "take_for_edit":
                if item["status"] not in {"queued", "steered"}:
                    raise Conflict("该队列消息不可取回编辑", "agent_queue_item_closed")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="editing", updated_at=now)
                )
                return {"item": dict(item, status="editing"), "action": "take_for_edit"}
            if action == "cancel":
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="cancelled", updated_at=now)
                )
                return {"item": dict(item, status="cancelled"), "action": "cancel"}
            if action == "mark_dispatched":
                turn = self._one(conn, S.canvas_agent_turns, p, payload.get("turn_id"))
                if turn["session_id"] != session["id"]:
                    raise ResourceError("关联轮次不属于当前会话", "agent_queue_item_scope")
                conn.execute(
                    update(S.canvas_agent_queue_items)
                    .where(
                        S.canvas_agent_queue_items.c.project_id == p,
                        S.canvas_agent_queue_items.c.id == item["id"],
                    )
                    .values(status="dispatched", dispatched_turn_id=turn["id"], updated_at=now)
                )
                return {"item": dict(item, status="dispatched", dispatched_turn_id=turn["id"]), "action": "mark_dispatched"}
            raise ResourceError("未知队列操作", "invalid_agent_queue_action")

        return self._mutate(project_id, "mutate_canvas_agent_queue", payload, actor=actor, callback=work, **kw)

    def list_camera_motion_templates(self, project_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            self._access_require(conn, p, "read")
            custom = [
                dict(row, builtin=False)
                for row in conn.execute(
                    select(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.archived.is_(False),
                    )
                    .order_by(
                        S.canvas_camera_motion_templates.c.favorite.desc(),
                        S.canvas_camera_motion_templates.c.updated_at.desc(),
                    )
                ).mappings()
            ]
            return clean({
                "builtin": [deepcopy(item) for item in BUILTIN_CAMERA_MOTIONS],
                "custom": custom,
                "revision": project["revision"],
            })

    def mutate_camera_motion_template(self, project_id, payload, actor, **kw):
        def work(conn, project):
            p = project["id"]
            self._access_require(conn, p, "edit")
            action = payload["action"]
            now = datetime.now(timezone.utc)
            if action == "create":
                item_id = new_id()
                conn.execute(
                    insert(S.canvas_camera_motion_templates).values(
                        project_id=p,
                        id=item_id,
                        name=payload["name"].strip(),
                        prompt_fragment=payload["prompt_fragment"].strip(),
                        horizontal_pan=int(payload.get("horizontal_pan", 0)),
                        vertical_tilt=int(payload.get("vertical_tilt", 0)),
                        zoom_delta=int(payload.get("zoom_delta", 0)),
                        roll_deg=int(payload.get("roll_deg", 0)),
                        speed_preset=payload.get("speed_preset", "normal"),
                        favorite=bool(payload.get("favorite", False)),
                        archived=False,
                        created_by=actor,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return {"item": dict(self._one(conn, S.canvas_camera_motion_templates, p, item_id), builtin=False), "action": "create"}
            row = self._one(conn, S.canvas_camera_motion_templates, p, payload.get("template_id"))
            if action == "favorite":
                fav = bool(payload["favorite"])
                conn.execute(
                    update(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.id == row["id"],
                    )
                    .values(favorite=fav, updated_at=now)
                )
                return {"item": dict(row, favorite=fav, builtin=False), "action": "favorite"}
            if action == "delete":
                conn.execute(
                    update(S.canvas_camera_motion_templates)
                    .where(
                        S.canvas_camera_motion_templates.c.project_id == p,
                        S.canvas_camera_motion_templates.c.id == row["id"],
                    )
                    .values(archived=True, updated_at=now)
                )
                return {"item": dict(row, archived=True, builtin=False), "action": "delete"}
            raise ResourceError("未知运镜模板操作", "invalid_camera_motion_action")

        return self._mutate(project_id, "mutate_camera_motion_template", payload, actor=actor, callback=work, **kw)
