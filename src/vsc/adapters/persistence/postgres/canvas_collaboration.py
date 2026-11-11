"""Authoritative PostgreSQL canvas collaboration permissions, tickets, sessions, locks and conflict recovery."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets

from sqlalchemy import and_, delete, insert, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.access_control import CAPABILITIES, Principal, current_principal, denied, reset_principal, set_principal
from vsc.assets.creative_canvas import _key, normalize_document
from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from . import schema as S
from .access_control import authority_lock
from .values import checked_id, clean, new_id

COLLAB_COLORS = (
    "#38bdf8",
    "#a855f7",
    "#f97316",
    "#22c55e",
    "#ec4899",
    "#eab308",
    "#14b8a6",
    "#6366f1",
)
TICKET_TTL_SECONDS = 60
LOCK_TTL_SECONDS = 24
SESSION_STALE_SECONDS = 90
EDGE_ERROR_CODES = frozenset({
    "canvas_missing_node",
    "canvas_port_mismatch",
    "canvas_port_cardinality",
    "canvas_cycle",
})


def collab_color(seed):
    token = str(seed or "anonymous")
    index = int(sha256(token.encode("utf-8")).hexdigest()[:8], 16) % len(COLLAB_COLORS)
    return COLLAB_COLORS[index]


def _summarize_node(node, title_override=None):
    if title_override is not None:
        return f"画布标题：{title_override}"
    if node is None:
        return "节点已删除"
    parts = [f"{node.get('type', 'node')} · {node.get('title', '')}"]
    text = (node.get("text") or "").strip()
    if text:
        excerpt = text[:80] + ("…" if len(text) > 80 else "")
        parts.append(f"内容：{excerpt}")
    if node.get("media_id"):
        parts.append(f"媒体：{str(node['media_id'])[:8]}")
    parts.append(f"坐标：({int(round(node.get('x', 0)))}, {int(round(node.get('y', 0)))})")
    return "；".join(parts)


def _diff_node_keys(before_doc, after_doc):
    before_nodes = {n["id"]: n for n in (before_doc or {}).get("nodes", [])}
    after_nodes = {n["id"]: n for n in (after_doc or {}).get("nodes", [])}
    changed = {
        key for key in (set(before_nodes) | set(after_nodes))
        if before_nodes.get(key) != after_nodes.get(key)
    }
    before_edges = {
        (e["source"], e["target"], e["port"]): e
        for e in (before_doc or {}).get("edges", [])
    }
    after_edges = {
        (e["source"], e["target"], e["port"]): e
        for e in (after_doc or {}).get("edges", [])
    }
    for sig in set(before_edges) ^ set(after_edges):
        if sig[1] in before_nodes or sig[1] in after_nodes:
            changed.add(sig[1])
    return changed


def _normalize_with_collab_codes(document):
    try:
        return normalize_document(document)
    except ResourceError as exc:
        if exc.code in EDGE_ERROR_CODES or "连线" in str(exc) or "端口" in str(exc) or "成环" in str(exc):
            raise ResourceError(
                str(exc),
                exc.code,
                422,
                details={"error_code": 11105, "reason": "invalid_edge"},
            ) from exc
        raise


def _apply_operations_to_document(base_title, base_document, operations, explicit_title=None, explicit_document=None):
    title = explicit_title if isinstance(explicit_title, str) and explicit_title.strip() else base_title
    doc = deepcopy(base_document)
    nodes_by_id = {n["id"]: n for n in doc.get("nodes", [])}
    node_order = [n["id"] for n in doc.get("nodes", [])]
    edges_by_id = {e["id"]: e for e in doc.get("edges", [])}
    edge_order = [e["id"] for e in doc.get("edges", [])]
    touched = set()

    if explicit_document is not None:
        normalized = _normalize_with_collab_codes(explicit_document)
        touched.update(_diff_node_keys(base_document, normalized))
        return title.strip(), normalized, touched

    for item in operations:
        if not isinstance(item, dict) or not isinstance(item.get("op"), str):
            raise ResourceError("协作操作格式无效", "invalid_collab_op")
        kind = item["op"]
        if kind == "replace_document":
            if isinstance(item.get("title"), str) and item["title"].strip():
                title = item["title"].strip()
            normalized = _normalize_with_collab_codes(item.get("document") or {})
            nodes_by_id = {n["id"]: deepcopy(n) for n in normalized["nodes"]}
            node_order = [n["id"] for n in normalized["nodes"]]
            edges_by_id = {e["id"]: deepcopy(e) for e in normalized["edges"]}
            edge_order = [e["id"] for e in normalized["edges"]]
            doc["viewport"] = deepcopy(normalized["viewport"])
            touched.update(_diff_node_keys(base_document, normalized))
        elif kind == "rename_canvas":
            next_title = item.get("title")
            if not isinstance(next_title, str) or not 1 <= len(next_title.strip()) <= 200:
                raise ResourceError("画布名称须为 1–200 字", "invalid_canvas_title")
            title = next_title.strip()
        elif kind in {"upsert_node", "update_node"}:
            node = item.get("node")
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                raise ResourceError("节点操作缺少有效节点定义", "invalid_collab_op")
            nid = _key(node["id"])
            prior = nodes_by_id.get(nid, {})
            merged = {**deepcopy(prior), **{k: v for k, v in deepcopy(node).items() if k != "preview_url"}}
            nodes_by_id[nid] = merged
            if nid not in node_order:
                node_order.append(nid)
            touched.add(nid)
        elif kind == "move_node":
            nid = _key(item.get("node_id") or item.get("node_key"))
            if nid not in nodes_by_id:
                raise ResourceError("移动目标节点不存在", "canvas_missing_node")
            nodes_by_id[nid]["x"] = item.get("x", nodes_by_id[nid]["x"])
            nodes_by_id[nid]["y"] = item.get("y", nodes_by_id[nid]["y"])
            touched.add(nid)
        elif kind == "delete_node":
            nid = _key(item.get("node_id") or item.get("node_key"))
            if nid in nodes_by_id:
                nodes_by_id.pop(nid, None)
                node_order = [k for k in node_order if k != nid]
                for eid in list(edge_order):
                    edge = edges_by_id.get(eid)
                    if edge and (edge["source"] == nid or edge["target"] == nid):
                        edges_by_id.pop(eid, None)
                        edge_order.remove(eid)
            touched.add(nid)
        elif kind == "upsert_edge":
            edge = item.get("edge")
            if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
                raise ResourceError("连线操作缺少有效连线定义", "invalid_collab_op")
            eid = _key(edge["id"])
            edges_by_id[eid] = deepcopy(edge)
            if eid not in edge_order:
                edge_order.append(eid)
            if isinstance(edge.get("target"), str):
                touched.add(edge["target"])
        elif kind == "delete_edge":
            eid = _key(item.get("edge_id") or item.get("edge_key"))
            removed = edges_by_id.pop(eid, None)
            edge_order = [k for k in edge_order if k != eid]
            if removed and isinstance(removed.get("target"), str):
                touched.add(removed["target"])
        elif kind == "viewport":
            if isinstance(item.get("viewport"), dict):
                doc["viewport"] = {**doc.get("viewport", {}), **item["viewport"]}
        else:
            raise ResourceError("不支持的协作操作类型: " + kind, "invalid_collab_op")

    candidate = {
        "nodes": [nodes_by_id[k] for k in node_order if k in nodes_by_id],
        "edges": [edges_by_id[k] for k in edge_order if k in edges_by_id],
        "viewport": doc.get("viewport", {"x": 0, "y": 0, "zoom": 1}),
    }
    normalized = _normalize_with_collab_codes(candidate)
    touched.update(_diff_node_keys(base_document, normalized))
    return title.strip(), normalized, touched


class CanvasCollaborationRepository:
    def _default_canvas_collaboration_enabled(self, conn, actor, payload=None):
        if isinstance(payload, dict) and "collaboration_enabled" in payload and payload["collaboration_enabled"] is not None:
            if type(payload["collaboration_enabled"]) is not bool:
                raise ResourceError("多人协作开关须为布尔值", "invalid_collaboration_flag")
            return payload["collaboration_enabled"]
        if not actor:
            return False
        prefs = conn.execute(
            select(S.access_identities.c.preferences).where(
                S.access_identities.c.actor == actor,
                S.access_identities.c.active.is_(True),
            )
        ).scalar_one_or_none()
        return bool(((prefs or {}).get("collaboration") or {}).get("enabled_on_new_canvas", False))

    def _workspace_is_personal(self, conn, project_id, principal=None):
        binding = conn.execute(
            select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id == project_id)
        ).scalar_one_or_none()
        if binding:
            kind = conn.execute(
                select(S.access_workspaces.c.kind).where(S.access_workspaces.c.id == binding)
            ).scalar_one_or_none()
            return kind == "personal"
        if principal is None:
            return False
        if principal.workspace_id:
            kind = conn.execute(
                select(S.access_workspaces.c.kind).where(S.access_workspaces.c.id == principal.workspace_id)
            ).scalar_one_or_none()
            if kind is not None:
                return kind == "personal"
        return True

    def _forbidden_canvas_permission(self, canvas):
        return {
            "mode": "forbidden",
            "can_edit": False,
            "is_owner": False,
            "is_studio_admin": False,
            "can_manage_collaboration": False,
            "is_personal_workspace": True,
            "collaboration_enabled": bool(canvas.get("collaboration_enabled", False)),
        }

    def _canvas_permission_for_principal(self, conn, project_id, canvas, principal):
        collab_enabled = bool(canvas.get("collaboration_enabled", False))
        if principal is None:
            return {
                "mode": "manage",
                "can_edit": True,
                "is_owner": True,
                "is_studio_admin": True,
                "can_manage_collaboration": True,
                "is_personal_workspace": False,
                "collaboration_enabled": collab_enabled,
            }
        token = set_principal(principal)
        try:
            try:
                _, person, share = self._access_principal(conn, principal)
            except ResourceError as exc:
                if exc.code == "access_denied":
                    return self._forbidden_canvas_permission(canvas)
                raise
            valid_canvas_share = bool(
                share
                and share["project_id"] == project_id
                and share["canvas_id"] == canvas["id"]
            )
            if share and not person:
                if valid_canvas_share:
                    can_edit = share["mode"] == "edit"
                    return {
                        "mode": "edit" if can_edit else "readonly",
                        "can_edit": can_edit,
                        "is_owner": False,
                        "is_studio_admin": False,
                        "can_manage_collaboration": False,
                        "is_personal_workspace": True,
                        "collaboration_enabled": collab_enabled,
                        "via_share": True,
                    }
                return self._forbidden_canvas_permission(canvas)
            try:
                scope = self._access_require(
                    conn,
                    project_id,
                    "read",
                    target_type="canvas",
                    target_id=canvas["id"],
                )
            except ResourceError as exc:
                if exc.code == "access_denied":
                    if valid_canvas_share:
                        can_edit = share["mode"] == "edit"
                        return {
                            "mode": "edit" if can_edit else "readonly",
                            "can_edit": can_edit,
                            "is_owner": False,
                            "is_studio_admin": False,
                            "can_manage_collaboration": False,
                            "is_personal_workspace": True,
                            "collaboration_enabled": collab_enabled,
                            "via_share": True,
                        }
                    return self._forbidden_canvas_permission(canvas)
                raise
        finally:
            reset_principal(token)

        caps = set(scope.get("capabilities") or ())
        if scope.get("share_id"):
            can_edit = scope.get("mode") == "edit"
            return {
                "mode": "edit" if can_edit else "readonly",
                "can_edit": can_edit,
                "is_owner": False,
                "is_studio_admin": False,
                "can_manage_collaboration": False,
                "is_personal_workspace": True,
                "collaboration_enabled": collab_enabled,
                "via_share": True,
            }

        is_personal = self._workspace_is_personal(conn, project_id, principal)
        has_edit = "edit" in caps
        has_manage = "manage" in caps
        share_can_edit = bool(valid_canvas_share and share["mode"] == "edit")
        is_owner = bool(person and person["actor"] == canvas["created_by"] and has_edit)
        is_studio_admin = bool((not is_personal) and has_manage)
        can_manage = bool(is_owner or is_studio_admin)
        if not has_edit:
            can_edit = share_can_edit
            mode = "edit" if share_can_edit else "readonly"
        elif not collab_enabled:
            can_edit = bool(is_owner or share_can_edit)
            mode = "manage" if can_manage else ("edit" if share_can_edit else "readonly")
        else:
            can_edit = True
            mode = "manage" if can_manage else "edit"
        return {
            "mode": mode,
            "can_edit": can_edit,
            "is_owner": is_owner,
            "is_studio_admin": is_studio_admin,
            "can_manage_collaboration": can_manage,
            "is_personal_workspace": is_personal,
            "collaboration_enabled": collab_enabled,
        }

    def _session_principal_and_permission(self, conn, project_id, canvas, identity_id, actor):
        if not identity_id:
            return None, self._forbidden_canvas_permission(canvas)
        try:
            person = self._access_identity(conn, identity_id)
        except ResourceError:
            return None, self._forbidden_canvas_permission(canvas)
        is_local = person["subject_key"].startswith("local:")
        if not is_local:
            has_any_cred = (
                conn.execute(
                    select(1).where(S.access_credentials.c.identity_id == person["id"]).limit(1)
                ).first()
                is not None
            )
            if has_any_cred:
                has_active_cred = (
                    conn.execute(
                        select(1)
                        .where(
                            S.access_credentials.c.identity_id == person["id"],
                            S.access_credentials.c.revoked.is_(False),
                        )
                        .limit(1)
                    ).first()
                    is not None
                )
                if not has_active_cred:
                    return None, self._forbidden_canvas_permission(canvas)
        synthetic = Principal(
            identity_id=person["id"],
            actor=person["actor"],
            local=is_local,
        )
        return person, self._canvas_permission_for_principal(conn, project_id, canvas, synthetic)

    def _canvas_permission(self, conn, project_id, canvas):
        return self._canvas_permission_for_principal(conn, project_id, canvas, current_principal())

    def _canvas_creator_info(self, conn, canvas):
        actor = canvas["created_by"]
        row = conn.execute(
            select(S.access_identities.c.id, S.access_identities.c.display_name).where(
                S.access_identities.c.actor == actor
            )
        ).mappings().first()
        seed = row["id"] if row else actor
        return {
            "id": row["id"] if row else actor,
            "actor": actor,
            "display_name": row["display_name"] if row else actor,
            "color": collab_color(seed),
        }

    def _project_collaborators(self, conn, project_id, canvas):
        binding = conn.execute(
            select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id == project_id)
        ).scalar_one_or_none()
        is_personal = True
        if binding:
            ws_kind = conn.execute(
                select(S.access_workspaces.c.kind).where(S.access_workspaces.c.id == binding)
            ).scalar_one_or_none()
            is_personal = ws_kind == "personal"

        roles_by_identity = {}
        identities = {}

        if binding:
            ws = S.access_workspaces
            ancestry = (
                select(
                    ws.c.id.label("workspace_id"),
                    ws.c.parent_id.label("parent_id"),
                    literal(0).label("depth"),
                )
                .where(ws.c.id == binding)
                .cte("collab_ws_ancestry", recursive=True)
            )
            parent_ws = ws.alias("parent_ws")
            ancestry = ancestry.union(
                select(
                    parent_ws.c.id,
                    parent_ws.c.parent_id,
                    (ancestry.c.depth + 1).label("depth"),
                )
                .join(ancestry, parent_ws.c.id == ancestry.c.parent_id)
                .where(ancestry.c.parent_id.is_not(None), ancestry.c.depth < 8)
            )
            wm = S.access_workspace_members
            ident = S.access_identities
            ws_member_rows = conn.execute(
                select(
                    wm.c.identity_id,
                    wm.c.role,
                    ident.c.actor,
                    ident.c.display_name,
                )
                .select_from(
                    ancestry.join(wm, wm.c.workspace_id == ancestry.c.workspace_id)
                    .join(ident, ident.c.id == wm.c.identity_id)
                )
                .where(
                    wm.c.active.is_(True),
                    ident.c.active.is_(True),
                    or_(ancestry.c.depth == 0, wm.c.role == "owner"),
                )
                .limit(500)
            ).mappings()
            for row in ws_member_rows:
                roles_by_identity.setdefault(row["identity_id"], set()).add(row["role"])
                identities[row["identity_id"]] = {
                    "id": row["identity_id"],
                    "actor": row["actor"],
                    "display_name": row["display_name"],
                }

        for row in conn.execute(
            select(
                S.access_project_members.c.identity_id,
                S.access_project_members.c.role,
                S.access_identities.c.actor,
                S.access_identities.c.display_name,
            )
            .join(S.access_identities, S.access_identities.c.id == S.access_project_members.c.identity_id)
            .where(
                S.access_project_members.c.project_id == project_id,
                S.access_project_members.c.active.is_(True),
                S.access_identities.c.active.is_(True),
            )
        ).mappings():
            roles_by_identity.setdefault(row["identity_id"], set()).add(row["role"])
            identities[row["identity_id"]] = {
                "id": row["identity_id"],
                "actor": row["actor"],
                "display_name": row["display_name"],
            }

        creator_row = conn.execute(
            select(S.access_identities.c.id, S.access_identities.c.actor, S.access_identities.c.display_name).where(
                S.access_identities.c.actor == canvas["created_by"],
                S.access_identities.c.active.is_(True),
            )
        ).mappings().first()
        if creator_row and creator_row["id"] not in identities:
            roles_by_identity[creator_row["id"]] = {"owner"}
            identities[creator_row["id"]] = dict(creator_row)

        collab_enabled = bool(canvas.get("collaboration_enabled", False))
        members = []
        for ident_id, person in identities.items():
            roles = roles_by_identity.get(ident_id, set())
            caps = set().union(*(CAPABILITIES[r] for r in roles)) if roles else set()
            effective_role = next((r for r in CAPABILITIES if r in roles), "viewer")
            is_owner = person["actor"] == canvas["created_by"] and ("edit" in caps or not roles)
            is_studio_admin = (not is_personal) and ("manage" in caps)
            can_edit = bool(is_owner or (collab_enabled and "edit" in caps))
            access_label = (
                "创建者"
                if is_owner
                else ("管理员 · 可编辑" if collab_enabled else "管理员 · 仅权限管理")
                if is_studio_admin
                else "可编辑"
                if can_edit
                else "仅查看"
            )
            members.append({
                "id": ident_id,
                "actor": person["actor"],
                "display_name": person["display_name"],
                "role": effective_role,
                "is_owner": is_owner,
                "is_studio_admin": is_studio_admin,
                "can_edit": can_edit,
                "access_label": access_label,
                "color": collab_color(ident_id),
            })
        members.sort(key=lambda m: (0 if m["is_owner"] else 1 if m["is_studio_admin"] else 2, m["display_name"], m["actor"]))
        return members

    def _purge_expired_canvas_locks(self, conn, project_id, canvas_id, now=None):
        now = now or datetime.now(timezone.utc)
        expired = [
            dict(r)
            for r in conn.execute(
                select(S.canvas_node_locks).where(
                    S.canvas_node_locks.c.project_id == project_id,
                    S.canvas_node_locks.c.canvas_id == canvas_id,
                    S.canvas_node_locks.c.expires_at <= now,
                )
            ).mappings()
        ]
        if expired:
            conn.execute(
                delete(S.canvas_node_locks).where(
                    S.canvas_node_locks.c.project_id == project_id,
                    S.canvas_node_locks.c.canvas_id == canvas_id,
                    S.canvas_node_locks.c.expires_at <= now,
                )
            )
        return expired

    def _active_canvas_locks(self, conn, project_id, canvas_id, now=None):
        now = now or datetime.now(timezone.utc)
        rows = conn.execute(
            select(S.canvas_node_locks)
            .where(
                S.canvas_node_locks.c.project_id == project_id,
                S.canvas_node_locks.c.canvas_id == canvas_id,
                S.canvas_node_locks.c.expires_at > now,
            )
            .order_by(S.canvas_node_locks.c.node_key)
        ).mappings()
        return [
            {
                "node_key": r["node_key"],
                "session_id": r["session_id"],
                "owner_user_id": r["identity_id"] or r["owner_actor"],
                "owner_actor": r["owner_actor"],
                "owner_name": r["owner_name"],
                "color": r["color"],
                "intent": r["intent"],
                "fencing_token": int(r["fencing_token"]),
                "expires_at": r["expires_at"].isoformat(),
            }
            for r in rows
        ]

    def _assert_canvas_nodes_unlocked(self, conn, project_id, canvas_id, node_keys, actor=None, session_id=None, lock_credentials=None):
        keys = sorted({k for k in (node_keys or ()) if isinstance(k, str) and k and k != "__canvas_title__"})
        if not keys:
            return
        now = datetime.now(timezone.utc)
        self._purge_expired_canvas_locks(conn, project_id, canvas_id, now)
        rows = conn.execute(
            select(S.canvas_node_locks).where(
                S.canvas_node_locks.c.project_id == project_id,
                S.canvas_node_locks.c.canvas_id == canvas_id,
                S.canvas_node_locks.c.node_key.in_(keys),
                S.canvas_node_locks.c.expires_at > now,
            )
        ).mappings().all()
        conflicting = []
        creds = lock_credentials if isinstance(lock_credentials, dict) else {}
        for r in rows:
            if session_id is not None:
                same_owner = r["session_id"] == session_id
                tok = creds.get(r["node_key"])
                token_ok = type(tok) is int and tok >= int(r["fencing_token"])
                if not same_owner or not token_ok:
                    conflicting.append(r)
            else:
                if actor is None or r["owner_actor"] != actor:
                    conflicting.append(r)
                elif r["node_key"] in creds:
                    tok = creds.get(r["node_key"])
                    if type(tok) is not int or tok < int(r["fencing_token"]):
                        conflicting.append(r)
        if conflicting:
            locks = [
                {
                    "node_key": r["node_key"],
                    "owner_user_id": r["identity_id"] or r["owner_actor"],
                    "owner_actor": r["owner_actor"],
                    "owner_name": r["owner_name"],
                    "color": r["color"],
                    "fencing_token": int(r["fencing_token"]),
                    "expires_at": r["expires_at"].isoformat(),
                }
                for r in conflicting
            ]
            names = "、".join(sorted({r["owner_name"] for r in conflicting}))
            raise Conflict(
                f"节点正由 {names} 编辑锁定中，请等待释放后再试",
                "node_locked",
                details={"locks": locks},
            )

    def _require_canvas_edit(self, conn, project_id, canvas, modified_node_keys=(), actor=None, session_id=None, lock_credentials=None):
        perm = self._canvas_permission(conn, project_id, canvas)
        if not perm["can_edit"]:
            raise ResourceError(
                "当前画布未开启多人协作或您仅有查看权限，无法编辑此画布",
                "canvas_edit_denied",
                403,
                details={"permission": perm},
            )
        if modified_node_keys:
            self._assert_canvas_nodes_unlocked(
                conn,
                project_id,
                canvas["id"],
                modified_node_keys,
                actor=actor,
                session_id=session_id,
                lock_credentials=lock_credentials,
            )
        return perm

    def _active_canvas_members(self, conn, project_id, canvas, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=SESSION_STALE_SECONDS)
        locks = self._active_canvas_locks(conn, project_id, canvas["id"], now)
        locked_by_session = {}
        for lock in locks:
            locked_by_session.setdefault(lock["session_id"], []).append(lock["node_key"])
        sessions = conn.execute(
            select(S.canvas_collab_sessions)
            .where(
                S.canvas_collab_sessions.c.project_id == project_id,
                S.canvas_collab_sessions.c.canvas_id == canvas["id"],
                S.canvas_collab_sessions.c.status == "active",
                S.canvas_collab_sessions.c.last_seen_at > cutoff,
            )
            .order_by(S.canvas_collab_sessions.c.created_at, S.canvas_collab_sessions.c.id)
        ).mappings()
        members = []
        for s in sessions:
            members.append({
                "session_id": s["id"],
                "user_id": s["identity_id"] or s["actor"],
                "actor": s["actor"],
                "nickname": s["display_name"],
                "display_name": s["display_name"],
                "is_owner": s["actor"] == canvas["created_by"],
                "mode": s["mode"],
                "color": s["color"],
                "page_session_id": s["page_session_id"],
                "active_node_keys": sorted(locked_by_session.get(s["id"], [])),
            })
        return members, locks

    def _record_canvas_collab_op(self, conn, project_id, canvas_id, seq, version_id, op_kind, ops, actor, session_id=None, client_op_id=None):
        conn.execute(
            insert(S.canvas_collab_ops).values(
                project_id=project_id,
                id=new_id(),
                canvas_id=canvas_id,
                seq=seq,
                version_id=version_id,
                op_kind=op_kind,
                ops=ops,
                actor=actor,
                session_id=session_id,
                client_op_id=client_op_id,
            )
        )

    def set_canvas_collaboration(self, project_id, payload, actor, **kw):
        from .project_management import management_canvas_guard
        command_key = kw["idempotency_key"]

        def work(conn, project):
            p = project["id"]
            canvas = self._one(conn, S.creative_canvases, p, required(payload, "canvas_id"))
            management_canvas_guard(conn, p, canvas["id"])
            if type(payload.get("collaboration_enabled")) is not bool:
                raise ResourceError("多人协作开关须为布尔值", "invalid_collaboration_flag")
            perm = self._canvas_permission(conn, p, canvas)
            if not perm["can_manage_collaboration"]:
                denied("仅画布创建者或工作室管理员可修改多人协作设置")
            _, person, _ = self._access_principal(conn)
            enabled = payload["collaboration_enabled"]
            new_seq = conn.execute(
                update(S.creative_canvases)
                .where(S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == canvas["id"])
                .values(collaboration_enabled=enabled, collab_seq=S.creative_canvases.c.collab_seq + 1)
                .returning(S.creative_canvases.c.collab_seq)
            ).scalar_one()
            conn.execute(
                insert(S.canvas_collaboration_decisions).values(
                    project_id=p,
                    id=new_id(),
                    canvas_id=canvas["id"],
                    collaboration_enabled=enabled,
                    actor=actor,
                    identity_id=person["id"] if person else None,
                    command_key=command_key,
                )
            )
            self._record_canvas_collab_op(
                conn,
                p,
                canvas["id"],
                int(new_seq),
                canvas["current_version_id"],
                "collaboration_toggled",
                [{"op": "collaboration_toggled", "collaboration_enabled": enabled}],
                actor,
            )
            unlocked_keys = []
            if not enabled:
                non_owner_locks = conn.execute(
                    select(S.canvas_node_locks.c.node_key).where(
                        S.canvas_node_locks.c.project_id == p,
                        S.canvas_node_locks.c.canvas_id == canvas["id"],
                        S.canvas_node_locks.c.owner_actor != canvas["created_by"],
                    )
                ).scalars().all()
                unlocked_keys = sorted(set(non_owner_locks))
                if unlocked_keys:
                    conn.execute(
                        delete(S.canvas_node_locks).where(
                            S.canvas_node_locks.c.project_id == p,
                            S.canvas_node_locks.c.canvas_id == canvas["id"],
                            S.canvas_node_locks.c.owner_actor != canvas["created_by"],
                        )
                    )
                conn.execute(
                    update(S.canvas_collab_sessions)
                    .where(
                        S.canvas_collab_sessions.c.project_id == p,
                        S.canvas_collab_sessions.c.canvas_id == canvas["id"],
                        S.canvas_collab_sessions.c.status == "active",
                        S.canvas_collab_sessions.c.mode == "edit",
                        S.canvas_collab_sessions.c.actor != canvas["created_by"],
                    )
                    .values(mode="presence")
                )
            updated_canvas = dict(canvas, collaboration_enabled=enabled, collab_seq=int(new_seq))
            updated_perm = self._canvas_permission(conn, p, updated_canvas)
            members, locks = self._active_canvas_members(conn, p, updated_canvas)
            return {
                "id": canvas["id"],
                "canvas_id": canvas["id"],
                "collaboration_enabled": enabled,
                "canvas_seq": int(new_seq),
                "permission": updated_perm,
                "creator": self._canvas_creator_info(conn, updated_canvas),
                "collaborators": self._project_collaborators(conn, p, updated_canvas),
                "members": members,
                "locks": locks,
                "unlocked_node_keys": unlocked_keys,
            }

        return self._mutate(project_id, "set_canvas_collaboration", payload, actor=actor, callback=work, **kw)

    def issue_canvas_collab_ticket(self, project_id, canvas_id, payload, actor):
        from .project_management import filter_management_rows
        if not isinstance(payload, dict):
            raise ResourceError("协作票据请求格式无效", "invalid_collab_ticket")
        mode = payload.get("mode", "presence")
        page_session_id = payload.get("page_session_id")
        if mode not in {"edit", "presence"} or not isinstance(page_session_id, str) or not 1 <= len(page_session_id.strip()) <= 120:
            raise ResourceError("协作模式或页面会话标识无效", "invalid_collab_ticket")
        page_session_id = page_session_id.strip()

        with self.engine.begin() as conn:
            authority_lock(conn)
            project = self._project(conn, project_id)
            p = project["id"]
            canvas, version = self._canvas_version(conn, project, canvas_id)
            if not filter_management_rows(conn, p, S.creative_canvases, [canvas]):
                raise ResourceError("画布所属对象已回收", "object_recycled", 409)
            principal, person, _ = self._access_principal(conn)
            if principal is not None:
                if principal.actor != actor:
                    denied("操作身份必须来自当前会话")
                if principal.api_key_id or principal.local_read or person is None:
                    denied("实时协作票据仅限已认证成员申请")
            elif person is None:
                row = conn.execute(
                    select(S.access_identities).where(
                        S.access_identities.c.actor == actor,
                        S.access_identities.c.active.is_(True),
                    )
                ).mappings().first()
                if row:
                    person = dict(row)
                else:
                    subject = "local:" + sha256(actor.encode("utf-8")).hexdigest()
                    existing = conn.execute(
                        select(S.access_identities).where(S.access_identities.c.subject_key == subject)
                    ).mappings().first()
                    if existing:
                        if not existing["active"]:
                            denied("身份已停用")
                        person = dict(existing)
                    else:
                        person = {
                            "id": new_id(),
                            "subject_key": subject,
                            "actor": actor,
                            "display_name": actor,
                            "preferences": {},
                            "active": True,
                        }
                        conn.execute(insert(S.access_identities).values(**person))
                        self._personal_workspace(conn, person)
            perm = self._canvas_permission(conn, p, canvas)
            if perm["mode"] == "forbidden" or perm.get("via_share"):
                denied()
            if mode == "edit" and not perm["can_edit"]:
                raise ResourceError(
                    "当前画布处于只读模式，无法申请协作编辑票据",
                    "canvas_edit_denied",
                    403,
                    details={"permission": perm},
                )
            raw_ticket = secrets.token_urlsafe(32)
            token_sha = sha256(raw_ticket.encode("utf-8")).hexdigest()
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=TICKET_TTL_SECONDS)
            conn.execute(
                insert(S.canvas_collab_tickets).values(
                    project_id=p,
                    id=new_id(),
                    canvas_id=canvas["id"],
                    identity_id=person["id"],
                    actor=actor,
                    mode=mode,
                    page_session_id=page_session_id,
                    token_sha256=token_sha,
                    expires_at=expires_at,
                )
            )
            return clean({
                "ticket": raw_ticket,
                "expires_at": expires_at.isoformat(),
                "expires_at_ms": int(expires_at.timestamp() * 1000),
                "mode": mode,
                "page_session_id": page_session_id,
                "sync_protocol": 2,
                "canvas_seq": int(canvas["collab_seq"]),
                "version": version["version"],
                "permission": perm,
            })

    def consume_canvas_collab_ticket(self, project_id, canvas_id, raw_ticket, client_last_seq=None):
        if not isinstance(raw_ticket, str) or not 16 <= len(raw_ticket) <= 200:
            raise ResourceError("协作票据无效", "invalid_collab_ticket", 403)
        token_sha = sha256(raw_ticket.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        with self.engine.begin() as conn:
            authority_lock(conn)
            project = self._project(conn, project_id)
            p = project["id"]
            canvas = conn.execute(
                select(S.creative_canvases)
                .where(
                    S.creative_canvases.c.project_id == p,
                    S.creative_canvases.c.id == checked_id(canvas_id),
                )
                .with_for_update()
            ).mappings().first()
            if not canvas:
                raise NotFound("画布不存在")
            canvas = dict(canvas)
            ticket = conn.execute(
                select(S.canvas_collab_tickets)
                .where(
                    S.canvas_collab_tickets.c.project_id == p,
                    S.canvas_collab_tickets.c.canvas_id == canvas["id"],
                    S.canvas_collab_tickets.c.token_sha256 == token_sha,
                )
                .with_for_update()
            ).mappings().first()
            if not ticket or ticket["consumed_at"] is not None or ticket["expires_at"] <= now:
                raise ResourceError("协作票据已失效或已被使用", "collab_ticket_expired", 403)
            conn.execute(
                update(S.canvas_collab_tickets)
                .where(
                    S.canvas_collab_tickets.c.project_id == p,
                    S.canvas_collab_tickets.c.canvas_id == canvas["id"],
                    S.canvas_collab_tickets.c.id == ticket["id"],
                )
                .values(consumed_at=now)
            )
            person, perm = self._session_principal_and_permission(
                conn, p, canvas, ticket["identity_id"], ticket["actor"]
            )
            if perm["mode"] == "forbidden" or perm.get("via_share"):
                denied()
            effective_mode = "edit" if (ticket["mode"] == "edit" and perm["can_edit"]) else "presence"

            kicked_session_ids = []
            unlocked_keys = set()
            same_user_cond = (
                S.canvas_collab_sessions.c.identity_id == ticket["identity_id"]
                if ticket["identity_id"]
                else S.canvas_collab_sessions.c.actor == ticket["actor"]
            )
            prior_sessions = conn.execute(
                select(S.canvas_collab_sessions).where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == canvas["id"],
                    S.canvas_collab_sessions.c.status == "active",
                    same_user_cond,
                )
            ).mappings().all()
            for prior in prior_sessions:
                if prior["page_session_id"] == ticket["page_session_id"]:
                    held = conn.execute(
                        select(S.canvas_node_locks.c.node_key).where(
                            S.canvas_node_locks.c.project_id == p,
                            S.canvas_node_locks.c.session_id == prior["id"],
                        )
                    ).scalars().all()
                    unlocked_keys.update(held)
                    conn.execute(
                        delete(S.canvas_node_locks).where(
                            S.canvas_node_locks.c.project_id == p,
                            S.canvas_node_locks.c.session_id == prior["id"],
                        )
                    )
                    conn.execute(
                        update(S.canvas_collab_sessions)
                        .where(
                            S.canvas_collab_sessions.c.project_id == p,
                            S.canvas_collab_sessions.c.canvas_id == canvas["id"],
                            S.canvas_collab_sessions.c.id == prior["id"],
                        )
                        .values(status="closed", last_seen_at=now)
                    )
                elif effective_mode == "edit" and prior["mode"] == "edit":
                    held = conn.execute(
                        select(S.canvas_node_locks.c.node_key).where(
                            S.canvas_node_locks.c.project_id == p,
                            S.canvas_node_locks.c.session_id == prior["id"],
                        )
                    ).scalars().all()
                    unlocked_keys.update(held)
                    conn.execute(
                        delete(S.canvas_node_locks).where(
                            S.canvas_node_locks.c.project_id == p,
                            S.canvas_node_locks.c.session_id == prior["id"],
                        )
                    )
                    conn.execute(
                        update(S.canvas_collab_sessions)
                        .where(
                            S.canvas_collab_sessions.c.project_id == p,
                            S.canvas_collab_sessions.c.canvas_id == canvas["id"],
                            S.canvas_collab_sessions.c.id == prior["id"],
                        )
                        .values(status="kicked", kicked_reason="same_user_takeover", last_seen_at=now)
                    )
                    kicked_session_ids.append(prior["id"])

            session_id = new_id()
            display_name = person["display_name"] if person else ticket["actor"]
            color = collab_color(ticket["identity_id"] or ticket["actor"])
            conn.execute(
                insert(S.canvas_collab_sessions).values(
                    project_id=p,
                    id=session_id,
                    canvas_id=canvas["id"],
                    ticket_id=ticket["id"],
                    identity_id=ticket["identity_id"],
                    actor=ticket["actor"],
                    display_name=display_name,
                    color=color,
                    mode=effective_mode,
                    page_session_id=ticket["page_session_id"],
                    sync_protocol=2,
                    status="active",
                    last_seen_at=now,
                )
            )
            expired_locks = self._purge_expired_canvas_locks(conn, p, canvas["id"], now)
            unlocked_keys.update(r["node_key"] for r in expired_locks)
            version_row = self._one(conn, S.creative_canvas_versions, p, canvas["current_version_id"])
            document = self._canvas_document(conn, p, version_row)
            members, locks = self._active_canvas_members(conn, p, canvas, now)

            missed_ops = []
            sync_required = False
            current_seq = int(canvas["collab_seq"])
            if client_last_seq is not None and isinstance(client_last_seq, int) and client_last_seq < current_seq:
                rows = conn.execute(
                    select(S.canvas_collab_ops)
                    .where(
                        S.canvas_collab_ops.c.project_id == p,
                        S.canvas_collab_ops.c.canvas_id == canvas["id"],
                        S.canvas_collab_ops.c.seq > client_last_seq,
                    )
                    .order_by(S.canvas_collab_ops.c.seq)
                    .limit(501)
                ).mappings().all()
                if not rows or len(rows) > 500 or int(rows[0]["seq"]) != client_last_seq + 1:
                    sync_required = True
                else:
                    missed_ops = [
                        {
                            "seq": int(r["seq"]),
                            "op_kind": r["op_kind"],
                            "ops": r["ops"],
                            "actor": r["actor"],
                            "version_id": r["version_id"],
                        }
                        for r in rows
                    ]

            return clean({
                "session": {
                    "id": session_id,
                    "user_id": ticket["identity_id"] or ticket["actor"],
                    "actor": ticket["actor"],
                    "display_name": display_name,
                    "color": color,
                    "mode": effective_mode,
                    "page_session_id": ticket["page_session_id"],
                    "sync_protocol": 2,
                },
                "permission": perm,
                "members": members,
                "locks": locks,
                "version": version_row["version"],
                "version_id": version_row["id"],
                "title": version_row["title"],
                "document": document,
                "canvas_seq": current_seq,
                "revision": project["revision"],
                "kicked_session_ids": kicked_session_ids,
                "unlocked_node_keys": sorted(unlocked_keys),
                "missed_ops": missed_ops,
                "sync_required": sync_required,
            })

    def touch_canvas_collab_session(self, project_id, canvas_id, session_id):
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                update(S.canvas_collab_sessions)
                .where(
                    S.canvas_collab_sessions.c.project_id == checked_id(project_id),
                    S.canvas_collab_sessions.c.canvas_id == checked_id(canvas_id),
                    S.canvas_collab_sessions.c.id == checked_id(session_id),
                    S.canvas_collab_sessions.c.status == "active",
                )
                .values(last_seen_at=now)
            )

    def close_canvas_collab_session(self, project_id, canvas_id, session_id):
        now = datetime.now(timezone.utc)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        with self.engine.begin() as conn:
            canvas = conn.execute(
                select(S.creative_canvases)
                .where(S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == cid)
                .with_for_update()
            ).mappings().first()
            if not canvas:
                return {"unlocked_node_keys": [], "members": [], "locks": []}
            canvas = dict(canvas)
            held = conn.execute(
                select(S.canvas_node_locks.c.node_key, S.canvas_node_locks.c.fencing_token).where(
                    S.canvas_node_locks.c.project_id == p,
                    S.canvas_node_locks.c.canvas_id == cid,
                    S.canvas_node_locks.c.session_id == sid,
                )
            ).mappings().all()
            conn.execute(
                delete(S.canvas_node_locks).where(
                    S.canvas_node_locks.c.project_id == p,
                    S.canvas_node_locks.c.canvas_id == cid,
                    S.canvas_node_locks.c.session_id == sid,
                )
            )
            conn.execute(
                update(S.canvas_collab_sessions)
                .where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == cid,
                    S.canvas_collab_sessions.c.id == sid,
                    S.canvas_collab_sessions.c.status == "active",
                )
                .values(status="closed", last_seen_at=now)
            )
            members, locks = self._active_canvas_members(conn, p, canvas, now)
            return clean({
                "unlocked": [{"node_key": r["node_key"], "fencing_token": int(r["fencing_token"])} for r in held],
                "unlocked_node_keys": sorted({r["node_key"] for r in held}),
                "members": members,
                "locks": locks,
            })

    def canvas_collab_room_state(self, project_id, canvas_id):
        now = datetime.now(timezone.utc)
        p, cid = checked_id(project_id), checked_id(canvas_id)
        with self.engine.begin() as conn:
            authority_lock(conn)
            canvas = conn.execute(
                select(S.creative_canvases).where(
                    S.creative_canvases.c.project_id == p,
                    S.creative_canvases.c.id == cid,
                )
            ).mappings().first()
            if not canvas:
                return None
            canvas = dict(canvas)
            self._purge_expired_canvas_locks(conn, p, cid, now)
            members, locks = self._active_canvas_members(conn, p, canvas, now)
            cutoff = now - timedelta(seconds=SESSION_STALE_SECONDS)
            session_permissions = {}
            sessions = conn.execute(
                select(S.canvas_collab_sessions).where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == cid,
                    S.canvas_collab_sessions.c.status == "active",
                    S.canvas_collab_sessions.c.last_seen_at > cutoff,
                )
            ).mappings().all()
            for s in sessions:
                _, s_perm = self._session_principal_and_permission(
                    conn, p, canvas, s["identity_id"], s["actor"]
                )
                session_permissions[s["id"]] = {
                    "permission": s_perm,
                    "mode": s["mode"],
                }
            return clean({
                "canvas_id": cid,
                "collaboration_enabled": bool(canvas["collaboration_enabled"]),
                "canvas_seq": int(canvas["collab_seq"]),
                "members": members,
                "locks": locks,
                "session_permissions": session_permissions,
            })

    def _active_edit_session(self, conn, p, cid, sid, now):
        session = conn.execute(
            select(S.canvas_collab_sessions)
            .where(
                S.canvas_collab_sessions.c.project_id == p,
                S.canvas_collab_sessions.c.canvas_id == cid,
                S.canvas_collab_sessions.c.id == sid,
            )
            .with_for_update()
        ).mappings().first()
        if not session or session["status"] != "active":
            return None, "session_inactive"
        canvas = conn.execute(
            select(S.creative_canvases)
            .where(S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == cid)
            .with_for_update()
        ).mappings().first()
        if not canvas:
            return None, "canvas_missing"
        canvas = dict(canvas)
        _, perm = self._session_principal_and_permission(
            conn, p, canvas, session["identity_id"], session["actor"]
        )
        if perm["mode"] == "forbidden":
            conn.execute(
                update(S.canvas_collab_sessions)
                .where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == cid,
                    S.canvas_collab_sessions.c.id == sid,
                )
                .values(status="closed", last_seen_at=now)
            )
            return (dict(session), canvas, perm), "access_denied"
        if session["mode"] != "edit" or not perm["can_edit"]:
            return (dict(session), canvas, perm), "readonly"
        conn.execute(
            update(S.canvas_collab_sessions)
            .where(
                S.canvas_collab_sessions.c.project_id == p,
                S.canvas_collab_sessions.c.canvas_id == cid,
                S.canvas_collab_sessions.c.id == sid,
            )
            .values(last_seen_at=now)
        )
        return (dict(session), canvas, perm), None

    def acquire_canvas_node_locks(self, project_id, canvas_id, session_id, node_keys, intent="edit"):
        if intent not in {"edit", "move", "delete"}:
            raise ResourceError("节点锁意图无效", "invalid_lock_intent")
        if not isinstance(node_keys, list) or not 1 <= len(node_keys) <= 200:
            raise ResourceError("请选择 1–200 个待锁定节点", "invalid_lock_keys")
        validated = [_key(k) for k in node_keys]
        if len(set(validated)) != len(validated) or validated != sorted(validated):
            raise ResourceError("多节点同时加锁须去重并按 node_key 字典序升序排列", "unsorted_lock_keys")

        now = datetime.now(timezone.utc)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        with self.engine.begin() as conn:
            authority_lock(conn)
            ctx, err = self._active_edit_session(conn, p, cid, sid, now)
            if err is not None:
                perm = ctx[2] if isinstance(ctx, tuple) and len(ctx) == 3 else None
                return clean({
                    "accepted": False,
                    "reason": err,
                    "node_keys": validated,
                    "permission": perm,
                    "conflicts": [],
                })
            session, canvas, _ = ctx
            self._purge_expired_canvas_locks(conn, p, cid, now)
            existing = conn.execute(
                select(S.canvas_node_locks).where(
                    S.canvas_node_locks.c.project_id == p,
                    S.canvas_node_locks.c.canvas_id == cid,
                    S.canvas_node_locks.c.node_key.in_(validated),
                    S.canvas_node_locks.c.expires_at > now,
                )
            ).mappings().all()
            conflicts = [
                {
                    "node_key": r["node_key"],
                    "owner_user_id": r["identity_id"] or r["owner_actor"],
                    "owner_actor": r["owner_actor"],
                    "owner_name": r["owner_name"],
                    "color": r["color"],
                    "fencing_token": int(r["fencing_token"]),
                    "expires_at": r["expires_at"].isoformat(),
                }
                for r in existing
                if r["session_id"] != sid
            ]
            if conflicts:
                return clean({
                    "accepted": False,
                    "reason": "locked_by_other",
                    "node_keys": validated,
                    "conflicts": conflicts,
                })
            fencing_token = int(
                conn.execute(
                    update(S.creative_canvases)
                    .where(S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == cid)
                    .values(fencing_seq=S.creative_canvases.c.fencing_seq + 1)
                    .returning(S.creative_canvases.c.fencing_seq)
                ).scalar_one()
            )
            expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
            for key in validated:
                values = {
                    "project_id": p,
                    "canvas_id": cid,
                    "node_key": key,
                    "session_id": sid,
                    "identity_id": session["identity_id"],
                    "owner_actor": session["actor"],
                    "owner_name": session["display_name"],
                    "color": session["color"],
                    "intent": intent,
                    "fencing_token": fencing_token,
                    "expires_at": expires_at,
                    "updated_at": now,
                }
                conn.execute(
                    pg_insert(S.canvas_node_locks)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=["project_id", "canvas_id", "node_key"],
                        set_={k: v for k, v in values.items() if k not in {"project_id", "canvas_id", "node_key"}},
                    )
                )
            members, locks = self._active_canvas_members(conn, p, canvas, now)
            return clean({
                "accepted": True,
                "node_keys": validated,
                "owner_user_id": session["identity_id"] or session["actor"],
                "owner_actor": session["actor"],
                "owner_name": session["display_name"],
                "color": session["color"],
                "intent": intent,
                "fencing_token": fencing_token,
                "expires_at": expires_at.isoformat(),
                "members": members,
                "locks": locks,
            })

    def renew_canvas_node_locks(self, project_id, canvas_id, session_id, locks):
        if not isinstance(locks, list) or not locks:
            return {"renewed": [], "rejected": []}
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        with self.engine.begin() as conn:
            authority_lock(conn)
            ctx, err = self._active_edit_session(conn, p, cid, sid, now)
            if err is not None:
                return clean({"renewed": [], "rejected": [item.get("node_key") for item in locks if isinstance(item, dict)]})
            self._purge_expired_canvas_locks(conn, p, cid, now)
            renewed, rejected = [], []
            for item in locks:
                if not isinstance(item, dict) or not isinstance(item.get("node_key"), str) or type(item.get("fencing_token")) is not int:
                    continue
                updated = conn.execute(
                    update(S.canvas_node_locks)
                    .where(
                        S.canvas_node_locks.c.project_id == p,
                        S.canvas_node_locks.c.canvas_id == cid,
                        S.canvas_node_locks.c.node_key == item["node_key"],
                        S.canvas_node_locks.c.session_id == sid,
                        S.canvas_node_locks.c.fencing_token == item["fencing_token"],
                    )
                    .values(expires_at=expires_at, updated_at=now)
                ).rowcount
                if updated:
                    renewed.append({
                        "node_key": item["node_key"],
                        "fencing_token": item["fencing_token"],
                        "expires_at": expires_at.isoformat(),
                    })
                else:
                    rejected.append(item["node_key"])
            return clean({"renewed": renewed, "rejected": rejected})

    def release_canvas_node_locks(self, project_id, canvas_id, session_id, locks):
        if not isinstance(locks, list) or not locks:
            return {"unlocked": [], "members": [], "locks": []}
        now = datetime.now(timezone.utc)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        with self.engine.begin() as conn:
            canvas = conn.execute(
                select(S.creative_canvases)
                .where(S.creative_canvases.c.project_id == p, S.creative_canvases.c.id == cid)
                .with_for_update()
            ).mappings().first()
            if not canvas:
                return {"unlocked": [], "members": [], "locks": []}
            canvas = dict(canvas)
            unlocked = []
            for item in locks:
                if not isinstance(item, dict) or not isinstance(item.get("node_key"), str):
                    continue
                token = item.get("fencing_token")
                conds = [
                    S.canvas_node_locks.c.project_id == p,
                    S.canvas_node_locks.c.canvas_id == cid,
                    S.canvas_node_locks.c.node_key == item["node_key"],
                    S.canvas_node_locks.c.session_id == sid,
                ]
                if type(token) is int:
                    conds.append(S.canvas_node_locks.c.fencing_token <= token)
                removed = conn.execute(
                    delete(S.canvas_node_locks).where(*conds).returning(S.canvas_node_locks.c.fencing_token)
                ).scalars().all()
                for ftok in removed:
                    unlocked.append({"node_key": item["node_key"], "fencing_token": int(ftok)})
            members, active_locks = self._active_canvas_members(conn, p, canvas, now)
            return clean({"unlocked": unlocked, "members": members, "locks": active_locks})

    def validate_transient_node_preview(self, project_id, canvas_id, session_id, updates):
        if not isinstance(updates, list) or not 1 <= len(updates) <= 100:
            return {"accepted": False, "reason": "invalid_updates"}
        now = datetime.now(timezone.utc)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        with self.engine.begin() as conn:
            ctx, err = self._active_edit_session(conn, p, cid, sid, now)
            if err is not None:
                return {"accepted": False, "reason": err}
            session, _, _ = ctx
            self._purge_expired_canvas_locks(conn, p, cid, now)
            keys = [u.get("node_key") for u in updates if isinstance(u, dict) and isinstance(u.get("node_key"), str)]
            active = {
                r["node_key"]: r
                for r in conn.execute(
                    select(S.canvas_node_locks).where(
                        S.canvas_node_locks.c.project_id == p,
                        S.canvas_node_locks.c.canvas_id == cid,
                        S.canvas_node_locks.c.node_key.in_(keys),
                        S.canvas_node_locks.c.expires_at > now,
                    )
                ).mappings()
            }
            sanitized = []
            for u in updates:
                if not isinstance(u, dict) or not isinstance(u.get("node_key"), str):
                    continue
                key = u["node_key"]
                lock = active.get(key)
                if lock and lock["session_id"] != sid:
                    return {"accepted": False, "reason": "locked_by_other", "node_key": key}
                if lock and type(u.get("fencing_token")) is int and u["fencing_token"] < int(lock["fencing_token"]):
                    return {"accepted": False, "reason": "stale_fencing_token", "node_key": key}
                x, y = u.get("x"), u.get("y")
                if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    continue
                entry = {"node_key": key, "x": float(x), "y": float(y)}
                if type(u.get("fencing_token")) is int:
                    entry["fencing_token"] = u["fencing_token"]
                sanitized.append(entry)
            if not sanitized:
                return {"accepted": False, "reason": "empty_updates"}
            return clean({
                "accepted": True,
                "updates": sanitized,
                "owner_user_id": session["identity_id"] or session["actor"],
                "owner_name": session["display_name"],
                "color": session["color"],
            })

    def _compute_conflicts_and_merge(
        self,
        conn,
        p,
        canvas,
        current_row,
        current_doc,
        base_version,
        operations,
        explicit_title=None,
        explicit_document=None,
    ):
        if base_version == current_row["version"]:
            next_title, next_doc, touched = _apply_operations_to_document(
                current_row["title"],
                current_doc,
                operations,
                explicit_title=explicit_title,
                explicit_document=explicit_document,
            )
            return {"conflicts": [], "title": next_title, "document": next_doc, "touched": touched}

        base_row = conn.execute(
            select(S.creative_canvas_versions).where(
                S.creative_canvas_versions.c.project_id == p,
                S.creative_canvas_versions.c.canvas_id == canvas["id"],
                S.creative_canvas_versions.c.version == base_version,
            )
        ).mappings().first()
        if not base_row:
            base_title = current_row["title"]
            base_doc = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
        else:
            base_title = base_row["title"]
            base_doc = self._canvas_document(conn, p, dict(base_row))

        local_title, local_doc, _ = _apply_operations_to_document(
            base_title,
            base_doc,
            operations,
            explicit_title=explicit_title,
            explicit_document=explicit_document,
        )
        base_nodes = {n["id"]: n for n in base_doc["nodes"]}
        local_nodes = {n["id"]: n for n in local_doc["nodes"]}
        remote_nodes = {n["id"]: n for n in current_doc["nodes"]}

        local_changed = {k for k in (set(base_nodes) | set(local_nodes)) if base_nodes.get(k) != local_nodes.get(k)}
        remote_changed = {k for k in (set(base_nodes) | set(remote_nodes)) if base_nodes.get(k) != remote_nodes.get(k)}
        conflict_keys = sorted(
            k for k in (local_changed & remote_changed)
            if local_nodes.get(k) != remote_nodes.get(k)
        )

        title_conflict = (
            local_title != base_title
            and current_row["title"] != base_title
            and local_title != current_row["title"]
        )

        # Also check if a locally added edge points to a node deleted remotely
        base_edges = {(e["source"], e["target"], e["port"]): e for e in base_doc["edges"]}
        local_edges = {(e["source"], e["target"], e["port"]): e for e in local_doc["edges"]}
        remote_edges = {(e["source"], e["target"], e["port"]): e for e in current_doc["edges"]}
        for sig in set(local_edges) - set(base_edges):
            for endpoint in (sig[0], sig[1]):
                if endpoint not in remote_nodes and endpoint not in local_changed and endpoint not in conflict_keys:
                    conflict_keys.append(endpoint)
        conflict_keys = sorted(set(conflict_keys))

        locks_by_key = {l["node_key"]: l for l in self._active_canvas_locks(conn, p, canvas["id"])}
        conflicts = []
        if title_conflict:
            conflicts.append({
                "node_id": "__canvas_title__",
                "node_title": "画布标题",
                "conflict_type": "title_modified",
                "local_summary": _summarize_node(None, local_title),
                "remote_summary": _summarize_node(None, current_row["title"]),
                "local_draft": {"title": local_title},
                "remote_node": {"title": current_row["title"]},
                "locked_by": None,
            })
        for key in conflict_keys:
            ln, rn, bn = local_nodes.get(key), remote_nodes.get(key), base_nodes.get(key)
            ctype = (
                "deleted_remotely"
                if rn is None
                else "deleted_locally"
                if ln is None
                else "concurrent_modify"
            )
            conflicts.append({
                "node_id": key,
                "node_title": (ln or rn or bn or {}).get("title", key),
                "conflict_type": ctype,
                "local_summary": _summarize_node(ln),
                "remote_summary": _summarize_node(rn),
                "local_draft": deepcopy(ln) if ln else None,
                "remote_node": deepcopy(rn) if rn else None,
                "locked_by": locks_by_key.get(key),
            })

        # Build merged document (applying local changes on top of remote snapshot)
        merged_nodes_map = {n["id"]: deepcopy(n) for n in current_doc["nodes"]}
        merged_order = [n["id"] for n in current_doc["nodes"]]
        for key in local_changed:
            if key in local_nodes:
                merged_nodes_map[key] = deepcopy(local_nodes[key])
                if key not in merged_order:
                    merged_order.append(key)
            else:
                merged_nodes_map.pop(key, None)
                merged_order = [k for k in merged_order if k != key]
        for n in local_doc["nodes"]:
            if n["id"] in local_changed and n["id"] not in merged_order:
                merged_order.append(n["id"])

        merged_edges_map = dict(remote_edges)
        for sig in set(base_edges) - set(local_edges):
            merged_edges_map.pop(sig, None)
        for sig, edge in local_edges.items():
            if sig not in base_edges:
                merged_edges_map[sig] = deepcopy(edge)
        valid_edges = [
            e for e in merged_edges_map.values()
            if e["source"] in merged_nodes_map and e["target"] in merged_nodes_map
        ]
        merged_title = local_title if local_title != base_title else current_row["title"]
        merged_doc = _normalize_with_collab_codes({
            "nodes": [merged_nodes_map[k] for k in merged_order if k in merged_nodes_map],
            "edges": valid_edges,
            "viewport": local_doc.get("viewport") or current_doc.get("viewport"),
        })
        return {
            "conflicts": conflicts,
            "title": merged_title,
            "document": merged_doc,
            "touched": local_changed | set(conflict_keys),
            "locks_by_key": locks_by_key,
        }

    def recover_canvas_batch(self, project_id, payload, actor, **kw):
        from .project_management import management_canvas_guard

        def work(conn, project):
            p = project["id"]
            if not isinstance(payload, dict) or payload.get("protocol_version") != 1:
                raise ResourceError("离线恢复批次需要 protocol_version = 1", "invalid_recovery_batch")
            base_version = payload.get("base_version")
            operations = payload.get("operations")
            force_overwrite = payload.get("force_overwrite", False)
            if (
                type(base_version) is not int
                or base_version < 1
                or not isinstance(operations, list)
                or len(operations) > 500
                or type(force_overwrite) is not bool
            ):
                raise ResourceError("离线恢复批次字段无效", "invalid_recovery_batch")

            canvas, current = self._canvas_version(conn, project, required(payload, "canvas_id"))
            management_canvas_guard(conn, p, canvas["id"])
            perm = self._require_canvas_edit(conn, p, canvas, actor=actor)
            current_doc = self._canvas_document(conn, p, current)

            if base_version > current["version"]:
                raise Conflict("恢复基准版本高于服务端当前版本，请重新同步", "canvas_revision_conflict")

            if not operations and payload.get("document") is None and payload.get("title") is None:
                return {
                    "id": canvas["id"],
                    "canvas_id": canvas["id"],
                    "version_id": current["id"],
                    "canvas_revision": current["version"],
                    "version": current["version"],
                    "canvas_seq": int(canvas["collab_seq"]),
                    "title": current["title"],
                    "sha256": current["sha256"],
                    "document": current_doc,
                    "collaboration_enabled": bool(canvas["collaboration_enabled"]),
                    "permission": perm,
                }

            plan = self._compute_conflicts_and_merge(
                conn,
                p,
                canvas,
                current,
                current_doc,
                base_version,
                operations,
                explicit_title=payload.get("title"),
                explicit_document=payload.get("document"),
            )
            if plan["conflicts"] and not force_overwrite:
                raise Conflict(
                    "检测到多人协作修改冲突，请确认保留版本",
                    "canvas_conflict",
                    details={
                        "error_code": 11103,
                        "reason": "version_conflict",
                        "conflicts": plan["conflicts"],
                        "version": current["version"],
                        "canvas_seq": int(canvas["collab_seq"]),
                        "canvas_meta_version": current["version"],
                        "node_versions": {n["id"]: current["version"] for n in current_doc["nodes"]},
                        "entity_versions": {},
                        "collaboration_enabled": bool(canvas["collaboration_enabled"]),
                        "locks": list(plan.get("locks_by_key", {}).values()),
                    },
                )

            self._assert_canvas_nodes_unlocked(
                conn,
                p,
                canvas["id"],
                plan["touched"],
                actor=actor,
                lock_credentials=payload.get("lock_credentials"),
            )
            saved = self._insert_canvas_version(
                conn,
                project,
                canvas,
                {"title": plan["title"], "document": plan["document"]},
                actor,
                current,
                collab_op_kind="recovery_batch",
                collab_ops=operations or [{"op": "replace_document"}],
            )
            return {
                **saved,
                "canvas_id": canvas["id"],
                "version": saved["canvas_revision"],
                "document": self._canvas_document(conn, p, self._one(conn, S.creative_canvas_versions, p, saved["version_id"])),
                "collaboration_enabled": bool(canvas["collaboration_enabled"]),
                "permission": perm,
            }

        return self._mutate(project_id, "recover_canvas_batch", payload, actor=actor, callback=work, **kw)

    def submit_canvas_collab_ops(self, project_id, canvas_id, session_id, payload):
        from .project_management import management_canvas_guard
        if not isinstance(payload, dict) or not isinstance(payload.get("ops"), list) or not 1 <= len(payload["ops"]) <= 200:
            return {"accepted": False, "error_code": 400, "reason": "invalid_ops", "message": "需要 1–200 条有效操作"}

        now = datetime.now(timezone.utc)
        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        try:
            with self.engine.begin() as conn:
                authority_lock(conn)
                project = self._project(conn, p, lock=True)
                management_canvas_guard(conn, p, cid)
                ctx, err = self._active_edit_session(conn, p, cid, sid, now)
                if err is not None:
                    perm = ctx[2] if isinstance(ctx, tuple) and len(ctx) == 3 else None
                    return clean({
                        "accepted": False,
                        "error_code": 403,
                        "reason": err,
                        "message": "当前画布已变为只读，未提交修改无法继续保存",
                        "permission": perm,
                    })
                session, canvas, perm = ctx
                current = self._one(conn, S.creative_canvas_versions, p, canvas["current_version_id"])
                current_doc = self._canvas_document(conn, p, current)

                client_op_id = payload.get("client_op_id")
                if isinstance(client_op_id, str) and client_op_id:
                    dup = conn.execute(
                        select(S.canvas_collab_ops).where(
                            S.canvas_collab_ops.c.project_id == p,
                            S.canvas_collab_ops.c.canvas_id == cid,
                            S.canvas_collab_ops.c.session_id == sid,
                            S.canvas_collab_ops.c.client_op_id == client_op_id,
                        )
                    ).mappings().first()
                    if dup:
                        return clean({
                            "accepted": True,
                            "duplicate": True,
                            "canvas_seq": int(dup["seq"]),
                            "version": current["version"],
                            "version_id": current["id"],
                            "revision": project["revision"],
                            "title": current["title"],
                            "document": current_doc,
                            "client_op_id": client_op_id,
                        })

                base_version = payload.get("base_version")
                if base_version is None and type(payload.get("base_seq")) is int and payload["base_seq"] >= 1:
                    if payload["base_seq"] >= int(canvas["collab_seq"]):
                        base_version = current["version"] if payload["base_seq"] == int(canvas["collab_seq"]) else None
                    else:
                        seq_op = conn.execute(
                            select(S.canvas_collab_ops.c.version_id)
                            .where(
                                S.canvas_collab_ops.c.project_id == p,
                                S.canvas_collab_ops.c.canvas_id == cid,
                                S.canvas_collab_ops.c.seq <= payload["base_seq"],
                                S.canvas_collab_ops.c.version_id.is_not(None),
                            )
                            .order_by(S.canvas_collab_ops.c.seq.desc())
                            .limit(1)
                        ).scalar_one_or_none()
                        if seq_op:
                            base_version = conn.execute(
                                select(S.creative_canvas_versions.c.version).where(
                                    S.creative_canvas_versions.c.project_id == p,
                                    S.creative_canvas_versions.c.canvas_id == cid,
                                    S.creative_canvas_versions.c.id == seq_op,
                                )
                            ).scalar_one_or_none()
                        elif payload["base_seq"] == 1:
                            base_version = 1
                if type(base_version) is not int or base_version < 1:
                    return clean({
                        "accepted": False,
                        "error_code": 400,
                        "reason": "invalid_base_version",
                        "message": "需要有效的基准版本号 base_version",
                    })
                if base_version > current["version"]:
                    return clean({
                        "accepted": False,
                        "error_code": 409,
                        "reason": "canvas_revision_conflict",
                        "message": "基准版本高于服务端当前版本，请重新同步",
                        "version": current["version"],
                        "canvas_seq": int(canvas["collab_seq"]),
                    })

                plan = self._compute_conflicts_and_merge(
                    conn,
                    p,
                    canvas,
                    current,
                    current_doc,
                    base_version,
                    payload["ops"],
                )
                if plan["conflicts"]:
                    return clean({
                        "accepted": False,
                        "error_code": 11103,
                        "reason": "version_conflict",
                        "message": "检测到多人协作修改冲突，请确认保留版本",
                        "conflicts": plan["conflicts"],
                        "version": current["version"],
                        "canvas_seq": int(canvas["collab_seq"]),
                        "collaboration_enabled": bool(canvas["collaboration_enabled"]),
                        "locks": list(plan.get("locks_by_key", {}).values()),
                    })

                self._assert_canvas_nodes_unlocked(
                    conn,
                    p,
                    cid,
                    plan["touched"],
                    actor=session["actor"],
                    session_id=sid,
                    lock_credentials=payload.get("lock_credentials"),
                )
                saved = self._insert_canvas_version(
                    conn,
                    project,
                    canvas,
                    {"title": plan["title"], "document": plan["document"]},
                    session["actor"],
                    current,
                    collab_op_kind="ops_batch",
                    collab_ops=payload["ops"],
                    collab_session_id=sid,
                    client_op_id=client_op_id if isinstance(client_op_id, str) else None,
                )
                next_rev = project["revision"] + 1
                cmd_key = "ws-ops:" + new_id()
                conn.execute(update(S.projects).where(S.projects.c.id == p).values(revision=next_rev))
                conn.execute(
                    insert(S.project_revisions).values(
                        project_id=p,
                        revision=next_rev,
                        actor=session["actor"],
                        action="save_creative_canvas",
                        command_key=cmd_key,
                    )
                )
                saved_doc = self._canvas_document(conn, p, self._one(conn, S.creative_canvas_versions, p, saved["version_id"]))
                response = clean({
                    **saved,
                    "project_id": p,
                    "revision": next_rev,
                })
                conn.execute(
                    insert(S.command_receipts).values(
                        project_id=p,
                        idempotency_key=cmd_key,
                        request_sha256=saved["sha256"],
                        response=response,
                    )
                )
                return clean({
                    "accepted": True,
                    "canvas_seq": saved["canvas_seq"],
                    "version": saved["canvas_revision"],
                    "version_id": saved["version_id"],
                    "revision": next_rev,
                    "title": saved["title"],
                    "document": saved_doc,
                    "ops": payload["ops"],
                    "actor": session["actor"],
                    "author_name": session["display_name"],
                    "session_id": sid,
                    "client_op_id": client_op_id,
                    "permission": perm,
                })
        except Conflict as exc:
            details = exc.details or {}
            return clean({
                "accepted": False,
                "error_code": details.get("error_code", 409),
                "reason": exc.code,
                "message": str(exc),
                **details,
            })
        except ResourceError as exc:
            details = exc.details or {}
            return clean({
                "accepted": False,
                "error_code": details.get("error_code", exc.status_code),
                "reason": exc.code,
                "message": str(exc),
                **details,
            })

    def sync_canvas_collab_ops(self, project_id, canvas_id, session_id, client_last_seq):
        from .project_management import management_canvas_guard

        p, cid, sid = checked_id(project_id), checked_id(canvas_id), checked_id(session_id)
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            authority_lock(conn)
            self._project(conn, p)
            canvas = conn.execute(
                select(S.creative_canvases).where(
                    S.creative_canvases.c.project_id == p,
                    S.creative_canvases.c.id == cid,
                )
            ).mappings().first()
            if not canvas:
                raise NotFound("画布不存在")
            canvas = dict(canvas)
            management_canvas_guard(conn, p, cid)
            session = conn.execute(
                select(S.canvas_collab_sessions)
                .where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == cid,
                    S.canvas_collab_sessions.c.id == sid,
                    S.canvas_collab_sessions.c.status == "active",
                )
                .with_for_update()
            ).mappings().first()
            if not session:
                raise ResourceError("协作会话已关闭或失效", "collab_session_inactive", 403)
            _, perm = self._session_principal_and_permission(
                conn, p, canvas, session["identity_id"], session["actor"]
            )
            if perm["mode"] == "forbidden":
                conn.execute(
                    update(S.canvas_collab_sessions)
                    .where(
                        S.canvas_collab_sessions.c.project_id == p,
                        S.canvas_collab_sessions.c.canvas_id == cid,
                        S.canvas_collab_sessions.c.id == sid,
                    )
                    .values(status="closed", last_seen_at=now)
                )
                denied("已无权继续同步此画布")
            conn.execute(
                update(S.canvas_collab_sessions)
                .where(
                    S.canvas_collab_sessions.c.project_id == p,
                    S.canvas_collab_sessions.c.canvas_id == cid,
                    S.canvas_collab_sessions.c.id == sid,
                    S.canvas_collab_sessions.c.status == "active",
                )
                .values(last_seen_at=now)
            )
            current_seq = int(canvas["collab_seq"])
            version = self._one(conn, S.creative_canvas_versions, p, canvas["current_version_id"])
            document = self._canvas_document(conn, p, version)
            members, locks = self._active_canvas_members(conn, p, canvas, now)
            if type(client_last_seq) is not int or client_last_seq < 0 or client_last_seq > current_seq:
                return clean({
                    "sync_required": True,
                    "canvas_seq": current_seq,
                    "version": version["version"],
                    "title": version["title"],
                    "document": document,
                    "members": members,
                    "locks": locks,
                })
            if client_last_seq == current_seq:
                return clean({
                    "sync_required": False,
                    "ops": [],
                    "canvas_seq": current_seq,
                    "version": version["version"],
                    "title": version["title"],
                    "document": document,
                    "members": members,
                    "locks": locks,
                })
            rows = conn.execute(
                select(S.canvas_collab_ops)
                .where(
                    S.canvas_collab_ops.c.project_id == p,
                    S.canvas_collab_ops.c.canvas_id == cid,
                    S.canvas_collab_ops.c.seq > client_last_seq,
                )
                .order_by(S.canvas_collab_ops.c.seq)
                .limit(501)
            ).mappings().all()
            if not rows or len(rows) > 500 or int(rows[0]["seq"]) != client_last_seq + 1:
                return clean({
                    "sync_required": True,
                    "canvas_seq": current_seq,
                    "version": version["version"],
                    "title": version["title"],
                    "document": document,
                    "members": members,
                    "locks": locks,
                })
            return clean({
                "sync_required": False,
                "ops": [
                    {
                        "seq": int(r["seq"]),
                        "op_kind": r["op_kind"],
                        "ops": r["ops"],
                        "actor": r["actor"],
                        "version_id": r["version_id"],
                    }
                    for r in rows
                ],
                "canvas_seq": current_seq,
                "version": version["version"],
                "title": version["title"],
                "document": document,
                "members": members,
                "locks": locks,
            })
