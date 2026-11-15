"""Explicit self-deactivation under ordered authority, access, and scoped domain locks."""
from datetime import datetime, timezone
from sqlalchemy import select, insert, update, func, or_, and_
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.assets.access_control import current_principal, denied
from . import schema as S
from .commerce import CommerceRepository, make_scope_ref
from .values import CURRENT_REVISION, clean, digest


class AccountLifecycleRepository:
    def __init__(self, store):
        self.store = store

    def _preview(self, conn, scope_ref, request_id):
        from .service_operations import ServiceOperationsRepository
        operations = ServiceOperationsRepository(self.store)
        person = operations._identity(conn)
        if scope_ref["scope_kind"] == "project":
            request = self.store._one(conn, S.service_requests, scope_ref["project_id"], request_id)
        else:
            request = operations._one_scoped(conn, S.service_requests, scope_ref, request_id)
        if request["kind"] != "account_close" or request["requester_id"] != person["id"]:
            denied("只能执行本人的账户停用申请")
        last = operations._latest_for_request(conn, request_id)
        if last["status"] in {"account_closed", "withdrawn", "rejected"}:
            raise Conflict("申请已结束，保留原处理记录", "service_request_terminal")

        identity = person["id"]
        actor = person["actor"]
        active_ids = set(
            conn.execute(
                select(S.access_identities.c.id).where(
                    S.access_identities.c.active.is_(True),
                    S.access_identities.c.id != identity,
                )
            ).scalars()
        )
        blockers = []

        owned = conn.execute(
            select(S.access_workspaces)
            .join(S.access_workspace_members, S.access_workspace_members.c.workspace_id == S.access_workspaces.c.id)
            .where(
                S.access_workspace_members.c.identity_id == identity,
                S.access_workspace_members.c.active.is_(True),
                S.access_workspace_members.c.role == "owner",
            )
        ).mappings()
        for workspace in owned:
            other = set(conn.execute(
                select(S.access_workspace_members.c.identity_id).where(
                    S.access_workspace_members.c.workspace_id == workspace["id"],
                    S.access_workspace_members.c.active.is_(True),
                    S.access_workspace_members.c.role == "owner",
                )
            ).scalars()) & active_ids
            populated = conn.execute(select(S.access_projects.c.project_id).where(S.access_projects.c.workspace_id == workspace["id"]).limit(1)).first()
            children = conn.execute(select(S.access_workspaces.c.id).where(S.access_workspaces.c.parent_id == workspace["id"]).limit(1)).first()
            peers = conn.execute(
                select(S.access_workspace_members.c.identity_id).where(
                    S.access_workspace_members.c.workspace_id == workspace["id"],
                    S.access_workspace_members.c.identity_id.in_(active_ids),
                    S.access_workspace_members.c.active.is_(True),
                ).limit(1)
            ).first()
            if not other and (populated or children or peers):
                blockers.append({
                    "code": "workspace_owner_required",
                    "id": workspace["id"],
                    "title": workspace["name"],
                    "target_section": "access",
                    "count": 1,
                    "message": "先在账户与权限中转交工作室负责人",
                })

        for project in conn.execute(
            select(S.access_projects)
            .join(S.access_project_members, S.access_project_members.c.project_id == S.access_projects.c.project_id)
            .where(
                S.access_project_members.c.identity_id == identity,
                S.access_project_members.c.active.is_(True),
                S.access_project_members.c.role == "owner",
            )
        ).mappings():
            direct = set(conn.execute(
                select(S.access_project_members.c.identity_id).where(
                    S.access_project_members.c.project_id == project["project_id"],
                    S.access_project_members.c.role == "owner",
                    S.access_project_members.c.active.is_(True),
                )
            ).scalars()) & active_ids
            inherited = any("owner" in self.store._workspace_roles(conn, project["workspace_id"], other) for other in active_ids)
            if not direct and not inherited:
                blockers.append({
                    "code": "project_owner_required",
                    "id": project["project_id"],
                    "target_section": "access",
                    "count": 1,
                    "message": "先在账户与权限中转交项目负责人",
                })

        financial = [
            (
                "orders", "commerce", S.commerce_orders,
                or_(
                    and_(S.commerce_orders.c.scope_kind == "identity", S.commerce_orders.c.owner_identity_id == identity),
                    S.commerce_orders.c.actor == actor,
                ),
                S.commerce_orders.c.status.in_({"created", "checkout_unknown", "pending", "refund_unknown"}),
            ),
            (
                "reservations", "tasks", S.commerce_reservations,
                or_(
                    and_(S.commerce_reservations.c.scope_kind == "identity", S.commerce_reservations.c.owner_identity_id == identity),
                    S.commerce_reservations.c.account_actor == actor,
                ),
                S.commerce_reservations.c.status == "reserved",
            ),
            (
                "invoices", "commerce", S.commerce_invoices,
                or_(
                    and_(S.commerce_invoices.c.scope_kind == "identity", S.commerce_invoices.c.owner_identity_id == identity),
                    S.commerce_invoices.c.actor == actor,
                ),
                S.commerce_invoices.c.status.in_({"created", "unconfigured", "submission_unknown", "pending"}),
            ),
        ]
        for label, target_sec, table, owner_cond, unfinished in financial:
            count = int(conn.execute(select(func.count()).select_from(table).where(owner_cond, unfinished)).scalar_one() or 0)
            if count:
                blockers.append({
                    "code": "unsettled_" + label,
                    "target_section": target_sec,
                    "count": count,
                    "message": "请先处理本人的未结订单、预留额度或开票申请",
                })

        balance = CommerceRepository.identity_remaining_balance(conn, identity, actor)
        if balance:
            blockers.append({
                "code": "credit_balance_remaining",
                "target_section": "commerce",
                "count": balance,
                "message": "本人仍有未处理额度，请先按原合同结清；停用不会抹除余额",
            })

        revision = conn.execute(select(S.access_state.c.revision).where(S.access_state.c.id == 1)).scalar_one_or_none() or 0
        plan = clean({
            "identity_id": identity,
            "actor": actor,
            "request_id": request["id"],
            "request_event_id": last["id"],
            "access_revision": revision,
            "blockers": blockers,
            "effect": "停用本地身份并撤销登录、API和本人发出的分享/邀请；作品、账务与审计历史保留，已受理任务不会被当作远端取消。",
        })
        sha = digest(plan)
        return {"plan": plan, "sha256": sha, "preview_sha256": sha, "ready": not blockers}

    def preview(self, p, request_id):
        from .access_control import authority_lock
        with self.store.engine.begin() as conn:
            authority_lock(conn)
            self.store._access_require(conn, p, "read")
            return self._preview(conn, make_scope_ref("project", p), request_id)

    def preview_identity(self, request_id):
        from .access_control import authority_lock
        from .service_operations import ServiceOperationsRepository
        with self.store.engine.begin() as conn:
            authority_lock(conn)
            person = ServiceOperationsRepository(self.store)._identity(conn)
            return self._preview(conn, make_scope_ref("identity", person["id"]), request_id)

    def _apply_deactivation(self, conn, scope_ref, payload, result):
        from .service_operations import ServiceOperationsRepository
        if result["sha256"] != payload["preview_sha256"]:
            raise Conflict("账户关系已有变化，请重新预览停用影响", "account_close_changed")
        plan = result["plan"]
        if payload["confirm_actor"] != plan["actor"]:
            denied("确认身份必须是当前本人")
        if not result["ready"]:
            raise ResourceError(
                "仍有负责人或账务关系未处理，请先查看影响清单",
                "account_close_blocked",
                409,
                details={"blockers": plan["blockers"]},
            )
        identity = plan["identity_id"]
        conn.execute(update(S.access_credentials).where(S.access_credentials.c.identity_id == identity).values(revoked=True))
        conn.execute(
            update(S.service_api_keys)
            .where(or_(S.service_api_keys.c.identity_id == identity, S.service_api_keys.c.owner_identity_id == identity))
            .values(revoked=True)
        )
        conn.execute(update(S.access_shares).where(S.access_shares.c.created_by == identity).values(revoked=True))
        conn.execute(update(S.access_invitations).where(S.access_invitations.c.created_by == identity).values(revoked=True))
        for table in (S.access_project_members, S.access_workspace_members):
            conn.execute(update(table).where(table.c.identity_id == identity).values(active=False))
        conn.execute(update(S.access_identities).where(S.access_identities.c.id == identity).values(active=False))

        ops = ServiceOperationsRepository(self.store)
        if scope_ref["scope_kind"] == "project":
            req_row = self.store._one(conn, S.service_requests, scope_ref["project_id"], payload["request_id"])
        else:
            req_row = ops._one_scoped(conn, S.service_requests, scope_ref, payload["request_id"])
        ops._event_for_request(conn, req_row, "account_closed", "本人已确认并完成本地身份停用；保留原作品与账务审计", identity)
        self.store._access_event(
            conn,
            "account-close:" + payload["request_id"],
            identity,
            "account-close",
            digest(payload),
            plan["access_revision"],
            {"identity_id": identity, "request_id": payload["request_id"], "active": False},
        )
        return {"id": payload["request_id"], "active": False, "status": "account_closed"}

    def close(self, p, payload, **kw):
        def work(conn, _project):
            scope_ref = make_scope_ref("project", p)
            result = self._preview(conn, scope_ref, payload["request_id"])
            return self._apply_deactivation(conn, scope_ref, payload, result)

        return self.store._mutate(p, "service_account_close", payload, callback=work, **kw)

    def close_identity(self, payload, **kw):
        expected_revision = kw.get("expected_revision", CURRENT_REVISION)
        idempotency_key = kw.get("idempotency_key")
        actor = kw.get("actor")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 200:
            raise ResourceError("操作标识不合法", "invalid_idempotency_key")
        if expected_revision is not CURRENT_REVISION and (type(expected_revision) is not int or expected_revision < 0):
            raise ResourceError("状态版本必须是非负整数", "invalid_revision")

        from .access_control import authority_lock
        from .service_operations import ServiceOperationsRepository
        with self.store.engine.begin() as conn:
            # Lock Hierarchy L1 -> L2 -> L3 ('commerce' < 'service_operations')
            authority_lock(conn, exclusive=True)
            self.store._access_state(conn)
            principal = current_principal()
            ops = ServiceOperationsRepository(self.store)
            person = ops._identity(conn)
            if principal is not None and principal.actor != actor:
                denied("操作身份必须来自当前会话")
            identity = person["id"]
            self.store._lock_scoped_domain(conn, "commerce", "identity", identity)
            ops_state = self.store._lock_scoped_domain(conn, "service_operations", "identity", identity)

            request_sha = digest({
                "domain": "service_operations",
                "scope_kind": "identity",
                "scope_key": identity,
                "action": "service_account_close",
                "payload": payload,
                "actor": actor,
            })
            receipt = conn.execute(select(S.scoped_command_receipts).where(
                S.scoped_command_receipts.c.domain == "service_operations",
                S.scoped_command_receipts.c.scope_kind == "identity",
                S.scoped_command_receipts.c.scope_key == identity,
                S.scoped_command_receipts.c.idempotency_key == idempotency_key,
            )).mappings().first()
            if receipt:
                if receipt["request_sha256"] != request_sha:
                    raise Conflict("同一幂等键已用于不同请求参数", "idempotency_payload_mismatch")
                return receipt["response"]
            if expected_revision is not CURRENT_REVISION and int(ops_state["revision"]) != expected_revision:
                raise Conflict(
                    "当前状态版本已更新，请刷新后重试",
                    "revision_conflict",
                    details={"current_revision": int(ops_state["revision"])},
                )

            scope_ref = make_scope_ref("identity", identity)
            result = self._preview(conn, scope_ref, payload["request_id"])
            response = self._apply_deactivation(conn, scope_ref, payload, result)
            next_rev = int(ops_state["revision"]) + 1
            now = datetime.now(timezone.utc)
            conn.execute(
                update(S.scoped_domain_states).where(
                    S.scoped_domain_states.c.domain == "service_operations",
                    S.scoped_domain_states.c.scope_kind == "identity",
                    S.scoped_domain_states.c.scope_key == identity,
                ).values(revision=next_rev, updated_at=now)
            )
            response = clean(dict(response, scope_kind="identity", scope_id=identity, revision=next_rev))
            conn.execute(insert(S.scoped_command_receipts).values(
                domain="service_operations",
                scope_kind="identity",
                scope_key=identity,
                idempotency_key=idempotency_key,
                actor=actor,
                action="service_account_close",
                request_sha256=request_sha,
                revision=next_rev,
                response=response,
            ))
            return response
