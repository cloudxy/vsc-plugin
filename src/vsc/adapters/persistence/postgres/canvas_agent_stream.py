"""Incremental canvas-agent sessions, events, questions and authorization tickets.

Existing turn, queue and session-state commands stay the writers for those tables.
This mixin only adds the stream pointer, append-only events and mutable tickets.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.production.canvas_agent import SKILLS
from vsc.production.canvas_agent_stream import (
    ACTIVE_TURN_STATUSES, CHAT_MODELS, REASONING_EFFORTS, classify_agent_failure,
    reference_only_prompt, ticket_blockers, validate_question_answers,
)
from . import schema as S
from .values import checked_id, clean, new_id

MESSAGE_KINDS = ("user_message", "assistant_message", "assistant_delta")
BUSY_DELETE = "正在执行中的会话不可删除"
RENAME_INVALID = "标题不能为空，且不能超过 30 个字符"


def _json_ready(value):
    return json.loads(json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, default=str))


class CanvasAgentStreamMixin:
    def list_canvas_agent_events(self, project_id, canvas_id, after=0, limit=200):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project["id"], "read")
            self._one(conn, S.creative_canvases, project["id"], canvas_id)
            rows = conn.execute(
                select(S.canvas_agent_events)
                .where(
                    S.canvas_agent_events.c.project_id == project["id"],
                    S.canvas_agent_events.c.canvas_id == canvas_id,
                    S.canvas_agent_events.c.seq > int(after or 0),
                )
                .order_by(S.canvas_agent_events.c.seq)
                .limit(max(1, min(int(limit or 200), 500)))
            ).mappings()
            events = [self._public_event(row) for row in rows]
            cursor = events[-1]["seq"] if events else int(after or 0)
            return clean({"events": events, "cursor": cursor, "revision": project["revision"]})

    def read_canvas_agent_stream(self, project_id, canvas_id, session_id=None, before_id=None, limit=30):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project["id"], "read")
            self._one(conn, S.creative_canvases, project["id"], canvas_id)
            return clean(self._stream_snapshot(conn, project, canvas_id, session_id=session_id, before_id=before_id, limit=limit))

    def mutate_canvas_agent_stream(self, project_id, payload, actor, **kw):
        action = payload.get("action") if isinstance(payload, dict) else None
        handlers = {
            "create_session": self._stream_create_session,
            "select_session": self._stream_select_session,
            "rename_session": self._stream_rename_session,
            "delete_session": self._stream_delete_session,
            "set_prefs": self._stream_set_prefs,
            "send": self._stream_send,
            "stop": self._stream_stop,
            "steer": self._stream_steer,
            "answer": self._stream_answer,
            "authorize": self._stream_authorize,
            "authorize_batch": self._stream_authorize_batch,
            "feedback": self._stream_feedback,
            "action_event": self._stream_action_event,
            "observe": self._stream_observe,
        }
        if action not in handlers:
            raise ResourceError("Agent 流操作无效", "invalid_agent_stream")
        checked_id(payload.get("canvas_id"))

        def work(conn, project):
            canvas = self._one(conn, S.creative_canvases, project["id"], payload["canvas_id"])
            self._require_canvas_edit(conn, project["id"], canvas, actor=actor)
            return handlers[action](conn, project, canvas, payload, actor)

        return self._mutate(project_id, "mutate_canvas_agent_stream", payload, actor=actor, callback=work, **kw)

    def _public_event(self, row):
        created = row["created_at"]
        return {
            "id": row["id"],
            "seq": int(row["seq"]),
            "canvas_id": row["canvas_id"],
            "session_id": row["session_id"],
            "kind": row["kind"],
            "payload": dict(row["payload"] or {}),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        }

    def _append_event(self, conn, project_id, canvas_id, session_id, kind, payload):
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 80:
            raise ResourceError("事件类型无效", "invalid_agent_stream")
        seq = conn.scalar(
            select(func.coalesce(func.max(S.canvas_agent_events.c.seq), 0) + 1).where(
                S.canvas_agent_events.c.project_id == project_id,
                S.canvas_agent_events.c.canvas_id == canvas_id,
            )
        )
        identifier = new_id()
        body = _json_ready(payload)
        conn.execute(insert_event(project_id, identifier, canvas_id, session_id, int(seq), kind, body))
        return {"id": identifier, "seq": int(seq), "kind": kind, "payload": body, "session_id": session_id, "canvas_id": canvas_id}

    def _session_row(self, conn, project_id, canvas, session_id):
        session = self._one(conn, S.canvas_agent_sessions, project_id, checked_id(session_id))
        if session["canvas_id"] != canvas["id"]:
            raise ResourceError("会话不属于当前画布", "canvas_agent_session_scope")
        return session

    def _active_turn(self, conn, project_id, session_id):
        return conn.execute(
            select(S.canvas_agent_turns)
            .where(
                S.canvas_agent_turns.c.project_id == project_id,
                S.canvas_agent_turns.c.session_id == session_id,
                S.canvas_agent_turns.c.status.in_(ACTIVE_TURN_STATUSES),
            )
            .order_by(S.canvas_agent_turns.c.created_at.desc())
        ).mappings().first()

    def _set_current(self, conn, project_id, canvas_id, session_id, actor):
        now = datetime.now(timezone.utc)
        conn.execute(
            pg_insert(S.canvas_agent_current_sessions)
            .values(project_id=project_id, canvas_id=canvas_id, session_id=session_id, updated_by=actor, updated_at=now)
            .on_conflict_do_update(
                index_elements=["project_id", "canvas_id"],
                set_={"session_id": session_id, "updated_by": actor, "updated_at": now},
            )
        )

    def _ensure_prefs(self, conn, project_id, session_id, actor, values=None):
        values = values or {}
        current = conn.execute(
            select(S.canvas_agent_session_prefs).where(
                S.canvas_agent_session_prefs.c.project_id == project_id,
                S.canvas_agent_session_prefs.c.session_id == session_id,
            )
        ).mappings().first()
        chat_model = values.get("chat_model", current["chat_model"] if current else "grok")
        effort = values.get("reasoning_effort", current["reasoning_effort"] if current else "medium")
        skill = values.get("selected_skill", current["selected_skill"] if current else "vsc-script")
        models = values.get("preferred_model_ids", list(current["preferred_model_ids"]) if current else [])
        tier_seen = values.get("tier_seen", bool(current["tier_seen"]) if current else False)
        if chat_model not in CHAT_MODELS:
            raise ResourceError("对话模型不可用", "invalid_agent_chat_model")
        if effort not in REASONING_EFFORTS:
            raise ResourceError("推理强度不可用", "invalid_agent_reasoning")
        if not isinstance(skill, str) or not skill.strip() or len(skill.strip()) > 80 or skill not in SKILLS:
            raise ResourceError("该技能未在当前画布 Agent 中安装，请选择可用技能。", "invalid_agent_skill")
        if not isinstance(models, list) or len(models) > 8 or len(set(models)) != len(models):
            raise ResourceError("最多选择 8 个模型", "invalid_agent_models")
        for model in models:
            item = conn.execute(select(S.provider_models).where(S.provider_models.c.id == checked_id(model))).mappings().first()
            if not item or not item["enabled"]:
                raise ResourceError("模型不存在或未启用", "invalid_agent_models")
        now = datetime.now(timezone.utc)
        conn.execute(
            pg_insert(S.canvas_agent_session_prefs)
            .values(
                project_id=project_id, session_id=session_id, chat_model=chat_model, reasoning_effort=effort,
                selected_skill=skill.strip(), preferred_model_ids=models, tier_seen=bool(tier_seen),
                updated_by=actor, updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["project_id", "session_id"],
                set_={
                    "chat_model": chat_model, "reasoning_effort": effort, "selected_skill": skill.strip(),
                    "preferred_model_ids": models, "tier_seen": bool(tier_seen), "updated_by": actor, "updated_at": now,
                },
            )
        )
        return {"chat_model": chat_model, "reasoning_effort": effort, "selected_skill": skill.strip(), "preferred_model_ids": models, "tier_seen": bool(tier_seen)}

    def _stream_create_session(self, conn, project, canvas, payload, actor):
        title = payload.get("title") or "未命名会话"
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 30 or "\x00" in title:
            raise ResourceError(RENAME_INVALID, "invalid_agent_session_title")
        title = title.strip()
        session_id = new_id()
        conn.execute(insert_session(project["id"], session_id, canvas["id"], title, actor))
        self.update_canvas_agent_session_state(
            project["id"], {"canvas_id": canvas["id"], "session_id": session_id, "title": title, "archived": False, "auto_approve": False},
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-state-" + session_id, _transaction=(conn, project),
        )
        prefs = self._ensure_prefs(conn, project["id"], session_id, actor, payload.get("prefs") if isinstance(payload.get("prefs"), dict) else None)
        self._set_current(conn, project["id"], canvas["id"], session_id, actor)
        event = self._append_event(conn, project["id"], canvas["id"], session_id, "session", {"action": "created", "title": title})
        return {"session_id": session_id, "title": title, "prefs": prefs, "current_session_id": session_id, "cursor": event["seq"]}

    def _stream_select_session(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        self._set_current(conn, project["id"], canvas["id"], session["id"], actor)
        self._backfill_messages(conn, project, canvas, session, actor)
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "session", {"action": "selected"})
        return {"session_id": session["id"], "current_session_id": session["id"], "cursor": event["seq"]}

    def _backfill_messages(self, conn, project, canvas, session, actor):
        existing = set(conn.execute(
            select(S.canvas_agent_events.c.payload["turn_id"].astext).where(
                S.canvas_agent_events.c.project_id == project["id"],
                S.canvas_agent_events.c.session_id == session["id"],
                S.canvas_agent_events.c.kind == "user_message",
            )
        ).scalars())
        turns = conn.execute(
            select(S.canvas_agent_turns)
            .where(S.canvas_agent_turns.c.project_id == project["id"], S.canvas_agent_turns.c.session_id == session["id"])
            .order_by(S.canvas_agent_turns.c.created_at)
        ).mappings()
        for turn in turns:
            if turn["id"] in existing:
                continue
            self._append_event(conn, project["id"], canvas["id"], session["id"], "user_message", {"role": "user", "text": turn["message"], "turn_id": turn["id"]})
            if turn["error"]:
                failure = classify_agent_failure(turn["error"])
                self._append_event(conn, project["id"], canvas["id"], session["id"], "assistant_message", {
                    "role": "assistant", "text": failure["message"], "turn_id": turn["id"], "error_code": failure["code"], "error_text": failure["message"],
                })
            elif turn["host_result"] and isinstance(turn["host_result"], dict) and turn["host_result"].get("message"):
                self._append_event(conn, project["id"], canvas["id"], session["id"], "assistant_message", {
                    "role": "assistant", "text": turn["host_result"]["message"], "turn_id": turn["id"],
                })

    def _stream_rename_session(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 30 or "\x00" in title:
            raise ResourceError(RENAME_INVALID, "invalid_agent_session_title")
        state = self.update_canvas_agent_session_state(
            project["id"], {"canvas_id": canvas["id"], "session_id": session["id"], "title": title.strip()},
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-rename-" + new_id(), _transaction=(conn, project),
        )
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "session", {"action": "renamed", "title": state["title"]})
        return {"session_id": session["id"], "title": state["title"], "cursor": event["seq"]}

    def _stream_delete_session(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        busy = self._active_turn(conn, project["id"], session["id"])
        if busy:
            raise Conflict(BUSY_DELETE, "canvas_agent_session_busy")
        self.update_canvas_agent_session_state(
            project["id"], {"canvas_id": canvas["id"], "session_id": session["id"], "archived": True},
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-delete-" + session["id"], _transaction=(conn, project),
        )
        current = conn.execute(
            select(S.canvas_agent_current_sessions.c.session_id).where(
                S.canvas_agent_current_sessions.c.project_id == project["id"],
                S.canvas_agent_current_sessions.c.canvas_id == canvas["id"],
            )
        ).scalar()
        replacement = None
        if current == session["id"]:
            replacement = self._next_open_session(conn, project["id"], canvas["id"], session["id"])
            if replacement:
                self._set_current(conn, project["id"], canvas["id"], replacement, actor)
            else:
                conn.execute(delete(S.canvas_agent_current_sessions).where(
                    S.canvas_agent_current_sessions.c.project_id == project["id"],
                    S.canvas_agent_current_sessions.c.canvas_id == canvas["id"],
                ))
        self._append_event(conn, project["id"], canvas["id"], session["id"], "session", {"action": "deleted", "deleted": True})
        return {"deleted": True, "session_id": session["id"], "current_session": {"session_id": replacement} if replacement else None}

    def _next_open_session(self, conn, project_id, canvas_id, excluded):
        rows = conn.execute(
            select(S.canvas_agent_sessions.c.id)
            .where(S.canvas_agent_sessions.c.project_id == project_id, S.canvas_agent_sessions.c.canvas_id == canvas_id, S.canvas_agent_sessions.c.id != excluded)
            .order_by(S.canvas_agent_sessions.c.created_at.desc())
        ).scalars()
        for session_id in rows:
            state = conn.execute(
                select(S.canvas_agent_session_states.c.archived).where(
                    S.canvas_agent_session_states.c.project_id == project_id,
                    S.canvas_agent_session_states.c.session_id == session_id,
                )
            ).scalar()
            if not state:
                return session_id
        return None

    def _stream_set_prefs(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        values = {key: payload[key] for key in ("chat_model", "reasoning_effort", "selected_skill", "preferred_model_ids", "tier_seen") if key in payload}
        if "auto_approve" in payload:
            if type(payload["auto_approve"]) is not bool:
                raise ResourceError("权限档位无效", "invalid_agent_session_state")
            self.update_canvas_agent_session_state(
                project["id"], {"canvas_id": canvas["id"], "session_id": session["id"], "auto_approve": payload["auto_approve"]},
                actor=actor, expected_revision=project["revision"], idempotency_key="stream-tier-" + new_id(), _transaction=(conn, project),
            )
        prefs = self._ensure_prefs(conn, project["id"], session["id"], actor, values)
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "session", {"action": "prefs", "prefs": prefs, "auto_approve": payload.get("auto_approve")})
        return {"session_id": session["id"], "prefs": prefs, "cursor": event["seq"]}

    def _stream_send(self, conn, project, canvas, payload, actor):
        canvas_row, version = self._canvas_version(conn, project, canvas["id"])
        if type(payload.get("canvas_revision")) is not int or payload["canvas_revision"] != version["version"]:
            raise Conflict("先保存并读取当前画布版本", "canvas_revision_conflict")
        node_ids = payload.get("node_ids") or []
        attachments = payload.get("attachment_media_ids") or []
        message = reference_only_prompt(payload.get("message"), node_ids, attachments)
        if not message:
            raise ResourceError("请输入新的消息。", "agent_message_required")
        session_id = payload.get("session_id")
        if session_id:
            session = self._session_row(conn, project["id"], canvas_row, session_id)
        else:
            created = self._stream_create_session(conn, project, canvas_row, {"title": message[:30]}, actor)
            session = self._one(conn, S.canvas_agent_sessions, project["id"], created["session_id"])
        prefs = self._ensure_prefs(conn, project["id"], session["id"], actor)
        skill = payload.get("skill_id") or prefs["selected_skill"]
        models = payload.get("model_ids") if "model_ids" in payload else prefs["preferred_model_ids"]
        mode = payload.get("mode") or "manual"
        active = self._active_turn(conn, project["id"], session["id"])
        user_event = self._append_event(conn, project["id"], canvas["id"], session["id"], "user_message", {"role": "user", "text": message})
        if active:
            queued = self.mutate_canvas_agent_queue(
                project["id"], {
                    "canvas_id": canvas["id"], "session_id": session["id"], "action": "enqueue",
                    "message": message, "skill_id": skill, "mode": mode,
                },
                actor=actor, expected_revision=project["revision"], idempotency_key="stream-enqueue-" + user_event["id"], _transaction=(conn, project),
            )
            queue_id = queued["item"]["id"]
            self._insert_record(conn, project["id"], canvas["id"], session["id"], active["id"], "queue_context", "queued", {
                "queue_item_id": queue_id, "message": message, "node_ids": node_ids, "attachment_media_ids": attachments,
                "model_ids": models, "skill_id": skill, "mode": mode, "chat_model": prefs["chat_model"],
                "reasoning_effort": prefs["reasoning_effort"], "message_id": user_event["id"],
            }, actor)
            self._append_event(conn, project["id"], canvas["id"], session["id"], "turn_status", {"status": "queued", "turn_id": active["id"], "disposition": "queued", "queue_id": queue_id})
            return {"disposition": "queued", "queue_id": queue_id, "session_id": session["id"], "active_turn_id": active["id"], "message_id": user_event["id"], "cursor": user_event["seq"]}
        turn = self.create_canvas_agent_turn(
            project["id"], {
                "canvas_id": canvas["id"], "canvas_revision": version["version"], "message": message, "skill_id": skill,
                "node_ids": node_ids, "attachment_media_ids": attachments, "model_ids": models, "session_id": session["id"],
                "mode": mode, "execution_settings": payload.get("execution_settings") or {},
            },
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-turn-" + user_event["id"], _transaction=(conn, project),
        )
        status_event = self._append_event(conn, project["id"], canvas["id"], session["id"], "turn_status", {"status": "queued", "turn_id": turn["id"], "disposition": "started"})
        self._set_current(conn, project["id"], canvas["id"], session["id"], actor)
        return {"disposition": "started", "turn_id": turn["id"], "session_id": session["id"], "message_id": user_event["id"], "cursor": status_event["seq"], "provider_submitted": False}

    def _stream_stop(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        turn_id = payload.get("turn_id")
        turn = self._one(conn, S.canvas_agent_turns, project["id"], checked_id(turn_id)) if turn_id else self._active_turn(conn, project["id"], session["id"])
        if not turn or turn["session_id"] != session["id"]:
            raise ResourceError("当前没有可停止的回合", "canvas_agent_stop_missing")
        if turn["status"] == "stopped":
            return {"stopped": True, "turn_id": turn["id"], "session_id": session["id"]}
        self.decide_canvas_agent_turn(
            project["id"], {"turn_id": turn["id"], "outcome": "stop", "reason": "用户停止当前规划任务"},
            actor=actor, build_preview=None, expected_revision=project["revision"], idempotency_key="stream-stop-" + turn["id"], _transaction=(conn, project),
        )
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "turn_status", {"status": "stopped", "turn_id": turn["id"]})
        return {"stopped": True, "turn_id": turn["id"], "session_id": session["id"], "cursor": event["seq"]}

    def _stream_steer(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        expected = checked_id(payload.get("expected_active_turn_id"))
        active = self._active_turn(conn, project["id"], session["id"])
        if not active or active["id"] != expected:
            raise Conflict("当前活跃回合已变化，请刷新后再插队", "canvas_agent_steer_conflict")
        item = self._one(conn, S.canvas_agent_queue_items, project["id"], checked_id(payload.get("queue_item_id")))
        if item["session_id"] != session["id"] or item["status"] not in {"queued", "steered", "editing"}:
            raise Conflict("该队列消息已处理或已取消", "agent_queue_item_closed")
        context = self._queue_context(conn, project["id"], item["id"]) or {}
        self.decide_canvas_agent_turn(
            project["id"], {"turn_id": active["id"], "outcome": "stop", "reason": "用户确认插队并停止当前回复"},
            actor=actor, build_preview=None, expected_revision=project["revision"], idempotency_key="stream-steer-stop-" + item["id"], _transaction=(conn, project),
        )
        _canvas, version = self._canvas_version(conn, project, canvas["id"])
        turn = self.create_canvas_agent_turn(
            project["id"], {
                "canvas_id": canvas["id"], "canvas_revision": version["version"],
                "message": context.get("message") or item["message"],
                "skill_id": context.get("skill_id") or item["skill_id"],
                "node_ids": context.get("node_ids") or [],
                "attachment_media_ids": context.get("attachment_media_ids") or [],
                "model_ids": context.get("model_ids") or [],
                "session_id": session["id"],
                "mode": context.get("mode") or item["mode"],
                "execution_settings": {},
            },
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-steer-turn-" + item["id"], _transaction=(conn, project),
        )
        self.mutate_canvas_agent_queue(
            project["id"], {
                "canvas_id": canvas["id"], "session_id": session["id"], "action": "mark_dispatched",
                "queue_item_id": item["id"], "turn_id": turn["id"],
            },
            actor=actor, expected_revision=project["revision"], idempotency_key="stream-steer-dispatch-" + item["id"], _transaction=(conn, project),
        )
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "turn_status", {
            "status": "steering", "canceled_turn_id": active["id"], "successor_turn_id": turn["id"], "queue_id": item["id"],
        })
        return {"disposition": "started", "queue_id": item["id"], "canceled_turn_id": active["id"], "successor_turn_id": turn["id"], "session_id": session["id"], "cursor": event["seq"]}

    def _queue_context(self, conn, project_id, queue_id):
        rows = conn.execute(
            select(S.canvas_agent_stream_records)
            .where(
                S.canvas_agent_stream_records.c.project_id == project_id,
                S.canvas_agent_stream_records.c.record_kind == "queue_context",
                S.canvas_agent_stream_records.c.payload["queue_item_id"].astext == queue_id,
            )
            .order_by(S.canvas_agent_stream_records.c.created_at.desc())
        ).mappings()
        row = next(iter(rows), None)
        return dict(row["payload"]) if row else None

    def _insert_record(self, conn, project_id, canvas_id, session_id, turn_id, kind, status, payload, actor, version=1, record_id=None):
        identifier = record_id or new_id()
        now = datetime.now(timezone.utc)
        conn.execute(
            pg_insert(S.canvas_agent_stream_records).values(
                project_id=project_id, id=identifier, canvas_id=canvas_id, session_id=session_id, turn_id=turn_id,
                record_kind=kind, status=status, payload=_json_ready(payload), version=version,
                updated_by=actor, updated_at=now,
            )
        )
        return identifier

    def _load_record(self, conn, project_id, canvas, record_id, kind):
        row = self._one(conn, S.canvas_agent_stream_records, project_id, checked_id(record_id))
        if row["canvas_id"] != canvas["id"] or row["record_kind"] != kind:
            raise ResourceError("记录不属于当前画布", "canvas_agent_record_scope")
        return row

    def _stream_answer(self, conn, project, canvas, payload, actor):
        record = self._load_record(conn, project["id"], canvas, payload.get("batch_id"), "question_batch")
        if payload.get("version") is not None and int(payload["version"]) != int(record["version"]):
            raise Conflict("答题卡已更新，请刷新后再提交", "question_version_conflict")
        if record["status"] != "pending":
            return {"question_batch": self._record_public(record), "unchanged": True}
        result = validate_question_answers(record["payload"], payload.get("answers"), skip=bool(payload.get("skip")))
        if not result["ok"]:
            raise ResourceError(result["message"], result["code"])
        status = "canceled" if payload.get("cancel") else "skipped" if result.get("skipped") else "answered"
        body = dict(record["payload"])
        body["answers"] = result["answers"]
        body["skipped"] = bool(result.get("skipped"))
        self._update_record(conn, project["id"], record["id"], status, body, int(record["version"]) + 1, actor)
        event = self._append_event(conn, project["id"], canvas["id"], record["session_id"], "question_resolved", {"batch_id": record["id"], "status": status, "answers": result["answers"]})
        return {"question_batch": {"id": record["id"], "status": status, "version": int(record["version"]) + 1, "payload": body}, "cursor": event["seq"]}

    def _update_record(self, conn, project_id, record_id, status, payload, version, actor):
        conn.execute(
            S.canvas_agent_stream_records.update().where(
                S.canvas_agent_stream_records.c.project_id == project_id,
                S.canvas_agent_stream_records.c.id == record_id,
            ).values(status=status, payload=_json_ready(payload), version=version, updated_by=actor, updated_at=datetime.now(timezone.utc))
        )

    def _stream_authorize(self, conn, project, canvas, payload, actor):
        record = self._load_record(conn, project["id"], canvas, payload.get("authorization_id"), "authorization")
        return self._decide_ticket(conn, project, canvas, record, payload, actor)

    def _decide_ticket(self, conn, project, canvas, record, payload, actor):
        body = dict(record["payload"] or {})
        approve = payload.get("approve")
        if type(approve) is not bool:
            raise ResourceError("请选择批准或拒绝", "invalid_agent_authorization")
        requester = body.get("requester") or record["updated_by"]
        if requester != actor:
            raise ResourceError("仅发起人可批准或拒绝此请求", "canvas_agent_auth_owner")
        if record["status"] != "pending":
            return {"authorization_id": record["id"], "status": record["status"], "unchanged": True}
        if approve:
            blockers = ticket_blockers(body)
            if not blockers["ok"]:
                if blockers["code"] == "ticket_expired":
                    self._update_record(conn, project["id"], record["id"], "expired", body, int(record["version"]) + 1, actor)
                raise ResourceError(blockers["message"], blockers["code"])
            if body.get("ticket_type") == "delete":
                status = "approved"
            else:
                status = "approved"
                if payload.get("remember_session") is True and record["session_id"]:
                    self.update_canvas_agent_session_state(
                        project["id"], {"canvas_id": canvas["id"], "session_id": record["session_id"], "auto_approve": True},
                        actor=actor, expected_revision=project["revision"], idempotency_key="stream-remember-" + record["id"], _transaction=(conn, project),
                    )
        else:
            reason = payload.get("reason") if isinstance(payload.get("reason"), str) else ""
            if len(reason) > 2000:
                raise ResourceError("拒绝理由过长", "invalid_agent_authorization")
            body["reject_reason"] = reason.strip()
            status = "rejected"
        self._update_record(conn, project["id"], record["id"], status, body, int(record["version"]) + 1, actor)
        event = self._append_event(conn, project["id"], canvas["id"], record["session_id"], "authorization_resolved", {
            "authorization_id": record["id"], "status": status, "ticket_type": body.get("ticket_type") or "paid",
            "node_ids": [node.get("id") for node in body.get("node_list") or [] if isinstance(node, dict)],
        })
        node_ids = [node.get("id") for node in body.get("node_list") or [] if isinstance(node, dict) and node.get("id")]
        return {"authorization_id": record["id"], "status": status, "ticket_type": body.get("ticket_type") or "paid", "node_ids": node_ids, "auto_approve_granted": bool(approve and payload.get("remember_session") and body.get("ticket_type") != "delete"), "cursor": event["seq"], "provider_submitted": False}

    def _stream_authorize_batch(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        rows = conn.execute(
            select(S.canvas_agent_stream_records)
            .where(
                S.canvas_agent_stream_records.c.project_id == project["id"],
                S.canvas_agent_stream_records.c.canvas_id == canvas["id"],
                S.canvas_agent_stream_records.c.session_id == session["id"],
                S.canvas_agent_stream_records.c.record_kind == "authorization",
                S.canvas_agent_stream_records.c.status == "pending",
            )
            .order_by(S.canvas_agent_stream_records.c.created_at)
        ).mappings()
        results = []
        for row in rows:
            body = dict(row["payload"] or {})
            if body.get("ticket_type") == "delete":
                continue
            try:
                decided = self._decide_ticket(conn, project, canvas, row, {"approve": True, "remember_session": False, "authorization_id": row["id"]}, actor)
                results.append({"authorization_id": row["id"], "status": decided["status"]})
            except ResourceError as exc:
                results.append({"authorization_id": row["id"], "status": "error", "error": exc.code, "message": exc.message})
        return {"results": results, "session_id": session["id"]}

    def _stream_feedback(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        message_id = payload.get("message_id")
        verdict = payload.get("verdict")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ResourceError("缺少要评价的消息", "invalid_agent_feedback")
        if verdict not in {"up", "down", "clear"}:
            raise ResourceError("评价只接受点赞、点踩或撤销", "invalid_agent_feedback")
        existing = conn.execute(
            select(S.canvas_agent_stream_records).where(
                S.canvas_agent_stream_records.c.project_id == project["id"],
                S.canvas_agent_stream_records.c.record_kind == "feedback",
                S.canvas_agent_stream_records.c.payload["message_id"].astext == message_id,
            )
        ).mappings().first()
        body = {"message_id": message_id, "verdict": verdict}
        if existing:
            self._update_record(conn, project["id"], existing["id"], verdict, body, int(existing["version"]) + 1, actor)
            record_id = existing["id"]
        else:
            record_id = self._insert_record(conn, project["id"], canvas["id"], session["id"], None, "feedback", verdict, body, actor)
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], "message_feedback", body)
        return {"message_id": message_id, "verdict": verdict, "record_id": record_id, "cursor": event["seq"]}

    def _stream_action_event(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        phase = payload.get("event")
        if phase not in {"frontend_action_started", "frontend_action_completed", "frontend_action_failed"}:
            raise ResourceError("前端动作事件无效", "invalid_agent_action_event")
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id.strip() or len(action_id) > 80:
            raise ResourceError("Agent 未返回 action_id", "missing_action_id")
        body = {
            "action_id": action_id.strip(),
            "event": phase,
            "message": payload.get("message") if isinstance(payload.get("message"), str) else "",
            "focus_ids": payload.get("focus_ids") if isinstance(payload.get("focus_ids"), list) else [],
            "ok": phase == "frontend_action_completed",
        }
        record_id = self._insert_record(conn, project["id"], canvas["id"], session["id"], None, "action_receipt", phase, body, actor)
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], phase, body)
        return {"record_id": record_id, "cursor": event["seq"], "event": phase, "focus_ids": body["focus_ids"]}

    def _stream_observe(self, conn, project, canvas, payload, actor):
        session = self._session_row(conn, project["id"], canvas, payload.get("session_id"))
        kind = payload.get("kind")
        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        allowed = {"user_message", "assistant_message", "assistant_delta", "tool_step", "turn_status", "question_required", "authorization_required"}
        if kind not in allowed:
            raise ResourceError("不能记录该事件", "invalid_agent_stream")
        record_id = None
        if kind == "question_required":
            items = body.get("items")
            if not isinstance(items, list) or not items:
                raise ResourceError("答题卡至少包含一个问题", "invalid_agent_question")
            record_id = self._insert_record(conn, project["id"], canvas["id"], session["id"], body.get("turn_id"), "question_batch", "pending", {"items": items, "title": body.get("title") or "请补充信息"}, actor, version=int(body.get("version") or 1))
            body = dict(body, batch_id=record_id, version=int(body.get("version") or 1))
        elif kind == "authorization_required":
            ticket = dict(body)
            ticket.setdefault("requester", actor)
            ticket.setdefault("ticket_type", "paid")
            if not ticket.get("expires_at"):
                ticket["expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            record_id = self._insert_record(conn, project["id"], canvas["id"], session["id"], ticket.get("turn_id"), "authorization", "pending", ticket, actor)
            body = dict(ticket, authorization_id=record_id)
        elif kind == "assistant_message" and body.get("error"):
            failure = classify_agent_failure(body.get("error"))
            body = dict(body, role="assistant", text=failure["message"], error_code=failure["code"], error_text=failure["message"])
        event = self._append_event(conn, project["id"], canvas["id"], session["id"], kind, body)
        return {"event": event, "record_id": record_id, "cursor": event["seq"]}

    def _record_public(self, row):
        return {"id": row["id"], "status": row["status"], "version": int(row["version"]), "payload": dict(row["payload"] or {}), "session_id": row["session_id"]}

    def _stream_snapshot(self, conn, project, canvas_id, session_id=None, before_id=None, limit=30):
        project_id = project["id"]
        limit = max(1, min(int(limit or 30), 100))
        current = conn.execute(
            select(S.canvas_agent_current_sessions.c.session_id).where(
                S.canvas_agent_current_sessions.c.project_id == project_id,
                S.canvas_agent_current_sessions.c.canvas_id == canvas_id,
            )
        ).scalar()
        sessions = []
        rows = conn.execute(
            select(S.canvas_agent_sessions)
            .where(S.canvas_agent_sessions.c.project_id == project_id, S.canvas_agent_sessions.c.canvas_id == canvas_id)
            .order_by(S.canvas_agent_sessions.c.created_at.desc())
        ).mappings()
        for session in rows:
            state = conn.execute(
                select(S.canvas_agent_session_states).where(
                    S.canvas_agent_session_states.c.project_id == project_id,
                    S.canvas_agent_session_states.c.session_id == session["id"],
                )
            ).mappings().first()
            archived = bool(state["archived"]) if state else False
            if archived:
                continue
            active = self._active_turn(conn, project_id, session["id"])
            sessions.append({
                "id": session["id"],
                "title": state["title"] if state else session["title"],
                "archived": False,
                "auto_approve": bool(state["auto_approve"]) if state else False,
                "is_current": session["id"] == current,
                "has_active_turn": bool(active),
            })
        selected = session_id or current or (sessions[0]["id"] if sessions else None)
        prefs = None
        messages, has_older, older_cursor = [], False, None
        tools, tickets, question, queue, active_turn = [], [], None, [], None
        if selected:
            prefs_row = conn.execute(
                select(S.canvas_agent_session_prefs).where(
                    S.canvas_agent_session_prefs.c.project_id == project_id,
                    S.canvas_agent_session_prefs.c.session_id == selected,
                )
            ).mappings().first()
            if prefs_row:
                prefs = {key: prefs_row[key] for key in ("chat_model", "reasoning_effort", "selected_skill", "preferred_model_ids", "tier_seen")}
            messages, has_older, older_cursor = self._page_messages(conn, project_id, selected, before_id, limit)
            tools = [self._public_event(row) for row in conn.execute(
                select(S.canvas_agent_events).where(
                    S.canvas_agent_events.c.project_id == project_id,
                    S.canvas_agent_events.c.session_id == selected,
                    S.canvas_agent_events.c.kind == "tool_step",
                ).order_by(S.canvas_agent_events.c.seq.desc()).limit(40)
            ).mappings()]
            tools.reverse()
            question_row = conn.execute(
                select(S.canvas_agent_stream_records).where(
                    S.canvas_agent_stream_records.c.project_id == project_id,
                    S.canvas_agent_stream_records.c.session_id == selected,
                    S.canvas_agent_stream_records.c.record_kind == "question_batch",
                ).order_by(S.canvas_agent_stream_records.c.created_at.desc())
            ).mappings().first()
            question = self._record_public(question_row) if question_row else None
            tickets = [self._record_public(row) for row in conn.execute(
                select(S.canvas_agent_stream_records).where(
                    S.canvas_agent_stream_records.c.project_id == project_id,
                    S.canvas_agent_stream_records.c.session_id == selected,
                    S.canvas_agent_stream_records.c.record_kind == "authorization",
                ).order_by(S.canvas_agent_stream_records.c.created_at)
            ).mappings()]
            queue = [dict(row) for row in conn.execute(
                select(S.canvas_agent_queue_items).where(
                    S.canvas_agent_queue_items.c.project_id == project_id,
                    S.canvas_agent_queue_items.c.session_id == selected,
                    S.canvas_agent_queue_items.c.status.in_(("queued", "steered", "editing")),
                ).order_by(S.canvas_agent_queue_items.c.ordinal)
            ).mappings()]
            active = self._active_turn(conn, project_id, selected)
            active_turn = {"id": active["id"], "status": active["status"]} if active else None
        cursor = conn.scalar(
            select(func.coalesce(func.max(S.canvas_agent_events.c.seq), 0)).where(
                S.canvas_agent_events.c.project_id == project_id,
                S.canvas_agent_events.c.canvas_id == canvas_id,
            )
        )
        pending = []
        for ticket in tickets:
            body = ticket["payload"]
            if ticket["status"] == "pending" and body.get("ticket_type") != "delete" and ticket_blockers(body)["ok"]:
                pending.append({"id": ticket["id"], "operation": body.get("operation"), "total_credits": body.get("total_credits")})
        state = next((item for item in sessions if item["id"] == selected), None)
        return {
            "revision": project["revision"],
            "canvas_id": canvas_id,
            "current_session_id": selected,
            "sessions": sessions,
            "prefs": prefs,
            "auto_approve": bool(state and state["auto_approve"]),
            "messages": messages,
            "has_older": has_older,
            "older_cursor": older_cursor,
            "tools": tools,
            "question_batch": question,
            "tickets": tickets,
            "pending_batch": pending,
            "queue": queue,
            "active_turn": active_turn,
            "cursor": int(cursor or 0),
        }

    def _page_messages(self, conn, project_id, session_id, before_id, limit):
        query = select(S.canvas_agent_events).where(
            S.canvas_agent_events.c.project_id == project_id,
            S.canvas_agent_events.c.session_id == session_id,
            S.canvas_agent_events.c.kind.in_(("user_message", "assistant_message")),
        )
        if before_id:
            before = conn.execute(
                select(S.canvas_agent_events.c.seq).where(
                    S.canvas_agent_events.c.project_id == project_id,
                    S.canvas_agent_events.c.id == before_id,
                )
            ).scalar()
            if before is None:
                raise ResourceError("找不到更早消息的位置", "agent_message_cursor")
            query = query.where(S.canvas_agent_events.c.seq < before)
        rows = list(conn.execute(query.order_by(S.canvas_agent_events.c.seq.desc()).limit(limit + 1)).mappings())
        has_older = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        messages = []
        for row in rows:
            payload = dict(row["payload"] or {})
            messages.append({
                "id": row["id"],
                "seq": int(row["seq"]),
                "role": payload.get("role") or ("assistant" if row["kind"] == "assistant_message" else "user"),
                "text": payload.get("text") or "",
                "turn_id": payload.get("turn_id"),
                "error_code": payload.get("error_code"),
                "error_text": payload.get("error_text"),
            })
        older = rows[0]["id"] if rows and has_older else (rows[0]["id"] if has_older else None)
        if has_older and rows:
            older = rows[0]["id"]
        feedbacks = {}
        if messages:
            ids = [item["id"] for item in messages]
            for record in conn.execute(
                select(S.canvas_agent_stream_records).where(
                    S.canvas_agent_stream_records.c.project_id == project_id,
                    S.canvas_agent_stream_records.c.record_kind == "feedback",
                    S.canvas_agent_stream_records.c.payload["message_id"].astext.in_(ids),
                )
            ).mappings():
                feedbacks[record["payload"].get("message_id")] = record["status"]
        for item in messages:
            item["feedback"] = feedbacks.get(item["id"])
        return messages, has_older, older


def insert_event(project_id, identifier, canvas_id, session_id, seq, kind, payload):
    from sqlalchemy import insert
    return insert(S.canvas_agent_events).values(
        project_id=project_id, id=identifier, canvas_id=canvas_id, session_id=session_id,
        seq=seq, kind=kind, payload=payload,
    )


def insert_session(project_id, session_id, canvas_id, title, actor):
    from sqlalchemy import insert
    return insert(S.canvas_agent_sessions).values(
        project_id=project_id, id=session_id, canvas_id=canvas_id, title=title, created_by=actor,
    )
