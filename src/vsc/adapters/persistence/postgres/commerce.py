"""One credit ledger, immutable prices/events and original job usage references."""
import base64
import csv
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import re
from urllib.parse import urlsplit
from sqlalchemy import select, insert, update, delete, func, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, NotFound, ResourceError
from vsc.assets.commerce import instant, require_supported_entitlements, validate_plan
from . import schema as S
from .values import CURRENT_REVISION, checked_id, clean, digest, new_id
from .workspace_commerce import WorkspaceCommerceRepository

DEFAULT_SUPPORT_EMAIL = "support@skyproduction.cn"
DEFAULT_SERVICE_HOURS = "周一至周五 10:00-19:00（法定节假日除外）"

PLAN_FIELD_LABELS = {
    "plan_key": "套餐标识",
    "title": "套餐名称",
    "currency": "计价币种",
    "amount_minor": "售价（最小货币单位）",
    "credits": "发放商业信用",
    "bucket_kind": "额度桶类型",
    "validity_days": "额度有效天数",
    "checkout_minutes": "收银支付时限（分钟）",
    "purposes": "允许扣减用途",
    "max_concurrent_jobs": "最大并发任务数",
    "seat_limit": "席位上限",
    "invoice_enabled": "允许开具电子发票",
    "watermark_required": "导出强制水印",
    "refund_policy": "退款策略",
    "renewal_policy": "续期策略",
}

CAMPAIGN_FIELD_LABELS = {
    "title": "活动名称",
    "credits": "赠送商业信用",
    "kind": "额度类型",
    "purposes": "适用用途",
    "starts_at": "活动开始时间",
    "ends_at": "活动结束时间",
    "credit_expires_at": "额度过期时间",
    "daily": "每日可兑",
}


def sanitize_csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    stripped = text.lstrip(" ")
    if text[:1] in {"\t", "\r"} or stripped[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def make_scope_ref(scope_kind, scope_id=None):
    if scope_kind == "platform":
        return {"scope_kind": "platform", "scope_id": "platform",
                "owner_identity_id": None, "workspace_id": None, "project_id": None}
    if scope_kind == "identity":
        ident = checked_id(scope_id)
        return {"scope_kind": "identity", "scope_id": ident,
                "owner_identity_id": ident, "workspace_id": None, "project_id": None}
    if scope_kind == "workspace":
        ws = checked_id(scope_id)
        return {"scope_kind": "workspace", "scope_id": ws,
                "owner_identity_id": None, "workspace_id": ws, "project_id": None}
    if scope_kind == "project":
        proj = checked_id(scope_id)
        return {"scope_kind": "project", "scope_id": proj,
                "owner_identity_id": None, "workspace_id": None, "project_id": proj}
    raise ResourceError("不支持的商业作用域", "invalid_scope")


class CommerceRepository(WorkspaceCommerceRepository):
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _coerce_scope(scope):
        if isinstance(scope, dict) and "scope_kind" in scope:
            return scope
        return make_scope_ref("project", scope)

    @staticmethod
    def _scope_cols(scope_ref):
        return {
            "scope_kind": scope_ref["scope_kind"],
            "owner_identity_id": scope_ref["owner_identity_id"],
            "workspace_id": scope_ref["workspace_id"],
            "project_id": scope_ref["project_id"],
        }

    @staticmethod
    def _scope_where(table, scope_ref):
        kind = scope_ref["scope_kind"]
        if kind == "project":
            return and_(table.c.scope_kind == "project", table.c.project_id == scope_ref["project_id"])
        if kind == "workspace":
            return and_(table.c.scope_kind == "workspace", table.c.workspace_id == scope_ref["workspace_id"])
        if kind == "identity":
            return and_(table.c.scope_kind == "identity", table.c.owner_identity_id == scope_ref["owner_identity_id"])
        if kind == "platform":
            return table.c.scope_kind == "platform"
        raise ResourceError("不支持的商业作用域", "invalid_scope")

    def _one_scoped(self, conn, table, scope_ref, row_id):
        row = conn.execute(select(table).where(
            self._scope_where(table, scope_ref),
            table.c.id == checked_id(row_id),
        )).mappings().first()
        if row is None:
            raise NotFound()
        return dict(row)

    def resolve_scope(self, scope_kind, scope_id=None, capability="read", *, actor=None):
        from vsc.assets.access_control import current_principal, denied
        principal = current_principal()
        if scope_kind == "project":
            if hasattr(self.store, "authorize_access"):
                self.store.authorize_access(scope_id, capability)
            manage = False
            if hasattr(self.store, "authorize_access"):
                try:
                    self.store.authorize_access(scope_id, "manage")
                    manage = True
                except Exception as exc:
                    if getattr(exc, "status_code", None) not in {401, 403}:
                        raise
            else:
                manage = True
            return make_scope_ref("project", scope_id), manage, False
        if scope_kind == "workspace":
            ws_id = checked_id(scope_id)
            if hasattr(self.store, "authorize_workspace"):
                self.store.authorize_workspace(ws_id, capability)
            manage = False
            if hasattr(self.store, "authorize_workspace"):
                try:
                    self.store.authorize_workspace(ws_id, "manage")
                    manage = True
                except Exception as exc:
                    if getattr(exc, "status_code", None) not in {401, 403}:
                        raise
            else:
                manage = True
            is_admin = False
            if hasattr(self.store, "_access_principal"):
                with self.store.engine.connect() as conn:
                    _, person, _ = self.store._access_principal(conn, principal)
                    is_admin = self.store._is_platform_admin(person, principal)
            return make_scope_ref("workspace", ws_id), manage, is_admin
        if scope_kind == "identity":
            with self.store.engine.connect() as conn:
                if principal is not None and hasattr(self.store, "_access_principal"):
                    _, person, _ = self.store._access_principal(conn, principal)
                    if principal.api_key_id or not person:
                        denied("个人账户与商业账本需要登录成员身份")
                    if scope_id and checked_id(scope_id) != person["id"]:
                        denied("只能访问本人个人商业账本")
                    return make_scope_ref("identity", person["id"]), True, self.store._is_platform_admin(person, principal)
                ident = checked_id(scope_id) if scope_id else None
                if not ident and actor:
                    ident = conn.execute(
                        select(S.access_identities.c.id).where(
                            S.access_identities.c.actor == actor,
                            S.access_identities.c.active.is_(True),
                        )
                    ).scalar_one_or_none()
            if not ident and actor and hasattr(self.store, "ensure_local_access"):
                ident = self.store.ensure_local_access(actor)["identity_id"]
            if not ident:
                denied("缺少有效个人身份")
            return make_scope_ref("identity", ident), True, True
        if scope_kind == "platform":
            if principal is not None and hasattr(self.store, "_access_principal"):
                with self.store.engine.connect() as conn:
                    _, person, _ = self.store._access_principal(conn, principal)
                    if principal.api_key_id or not person:
                        denied("平台商业目录需要登录成员身份")
                    is_admin = self.store._is_platform_admin(person, principal)
                    if capability != "read" and not is_admin:
                        denied("平台级套餐与活动配置仅限平台管理员操作")
                    return make_scope_ref("platform"), is_admin, is_admin
            return make_scope_ref("platform"), True, True
        raise ResourceError("不支持的商业作用域", "invalid_scope")

    def workspace_scope_details(self, workspace_id):
        ws_id = checked_id(workspace_id)
        if not hasattr(self.store, "access_snapshot"):
            return {"workspace_id": ws_id, "workspace_name": ws_id, "projects": [], "members": [], "transfers": []}
        snapshot = self.store.access_snapshot()
        ws_row = next((w for w in snapshot.get("workspaces", []) if w["id"] == ws_id), None)
        projects = [row for row in snapshot.get("projects", []) if row.get("workspace_id") == ws_id]
        members = {
            row["actor"]: row
            for row in snapshot.get("members", [])
            if row.get("active") and row.get("workspace_id") == ws_id
        }
        return clean({
            "workspace_id": ws_id,
            "workspace_name": ws_row["name"] if ws_row else ws_id,
            "projects": projects,
            "members": list(members.values()),
            "transfers": [],
        })

    def _mutate_for_scope(self, scope, action, payload, callback, *, expected_revision=CURRENT_REVISION,
                          idempotency_key=None, actor=None, capability="manage"):
        scope_ref = self._coerce_scope(scope)
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        resolved_actor = actor or (principal.actor if principal and principal.actor else "commerce-consumer")
        key = idempotency_key or new_id()
        if scope_ref["scope_kind"] == "project":
            return self.store._mutate(
                scope_ref["project_id"], action, payload,
                expected_revision=expected_revision, idempotency_key=key, actor=resolved_actor,
                callback=lambda conn, project: callback(conn, scope_ref, project["revision"]),
            )
        return self.store._mutate_scoped(
            "commerce", scope_ref["scope_kind"], scope_ref["scope_id"], action, payload,
            expected_revision=expected_revision, idempotency_key=key, actor=resolved_actor,
            capability=capability,
            callback=lambda conn, state, _person: callback(conn, scope_ref, int(state["revision"])),
        )

    def _internal(self, scope, action, payload, fn, key=None):
        scope_ref = self._coerce_scope(scope)
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        actor = principal.actor if principal and principal.actor else "commerce-consumer"
        if scope_ref["scope_kind"] == "project":
            return self.store._mutate(
                scope_ref["project_id"], action, payload, callback=fn,
                expected_revision=CURRENT_REVISION, idempotency_key=key or new_id(), actor=actor,
            )
        return self.store._mutate_scoped(
            "commerce", scope_ref["scope_kind"], scope_ref["scope_id"], action, payload,
            expected_revision=CURRENT_REVISION, idempotency_key=key or new_id(), actor=actor,
            capability="read",
            callback=lambda conn, state, _person: fn(conn, {"id": scope_ref["scope_id"], "revision": int(state["revision"])}),
        )

    def _plan(self, conn, scope, identifier):
        scope_ref = self._coerce_scope(scope)
        checked = checked_id(identifier)
        if scope_ref["scope_kind"] == "project":
            row = conn.execute(select(S.commerce_plan_versions).where(
                S.commerce_plan_versions.c.id == checked,
                or_(
                    self._scope_where(S.commerce_plan_versions, scope_ref),
                    S.commerce_plan_versions.c.scope_kind == "platform",
                ),
            )).mappings().first()
        elif scope_ref["scope_kind"] == "workspace":
            row = conn.execute(select(S.commerce_plan_versions).where(
                S.commerce_plan_versions.c.id == checked,
                or_(
                    self._scope_where(S.commerce_plan_versions, scope_ref),
                    S.commerce_plan_versions.c.scope_kind == "platform",
                ),
            )).mappings().first()
        elif scope_ref["scope_kind"] == "identity":
            row = conn.execute(select(S.commerce_plan_versions).where(
                S.commerce_plan_versions.c.id == checked,
                S.commerce_plan_versions.c.scope_kind == "platform",
            )).mappings().first()
        else:
            row = conn.execute(select(S.commerce_plan_versions).where(
                S.commerce_plan_versions.c.id == checked,
                S.commerce_plan_versions.c.scope_kind == "platform",
            )).mappings().first()
        if row is None:
            raise NotFound()
        return dict(row)

    def _policy(self, conn, scope, *, allow_platform_fallback=False):
        scope_ref = self._coerce_scope(scope)
        if scope_ref["scope_kind"] in {"project", "workspace", "platform"}:
            row = conn.execute(select(S.commerce_settings).where(
                self._scope_where(S.commerce_settings, scope_ref)
            )).mappings().first()
            if row and row["enabled"]:
                return self._plan(conn, scope_ref, row["price_version_id"])
            if not allow_platform_fallback:
                return None
        row = conn.execute(select(S.commerce_settings).where(
            S.commerce_settings.c.scope_kind == "platform"
        )).mappings().first()
        if row and row["enabled"]:
            return self._plan(conn, make_scope_ref("platform"), row["price_version_id"])
        return None

    @staticmethod
    def _balance(conn, _scope_or_p, bucket_id):
        return int(conn.execute(select(func.coalesce(func.sum(S.commerce_ledger.c.delta), 0)).where(
            S.commerce_ledger.c.bucket_id == bucket_id
        )).scalar_one() or 0)

    def _entry(self, conn, scope, bucket, delta, kind, key, actor, reservation=None,
               attribution_project_id=None, job_id=None):
        if delta:
            scope_ref = self._coerce_scope(scope)
            identifier = new_id()
            values = {
                **self._scope_cols(scope_ref),
                "id": identifier,
                "bucket_id": bucket,
                "delta": delta,
                "kind": kind,
                "event_key": key,
                "actor": actor,
                "reservation_id": reservation if kind in {"reserve", "release"} else None,
                "attribution_project_id": attribution_project_id if kind in {"reserve", "release"} else None,
                "job_id": job_id if kind in {"reserve", "release"} else None,
            }
            conn.execute(insert(S.commerce_ledger).values(**values))
            return identifier
        return None

    def _bucket(self, conn, scope, *, source_key, credits, owner, kind, purposes, expires,
                order=None, parent=None, entry_kind="grant", actor="commerce-consumer"):
        scope_ref = self._coerce_scope(scope)
        identifier = new_id()
        conn.execute(insert(S.commerce_buckets).values(
            **self._scope_cols(scope_ref),
            id=identifier,
            source_key=source_key,
            owner_actor=owner,
            kind=kind,
            purposes=purposes,
            expires_at=expires,
            order_id=order,
            parent_bucket_id=parent,
        ))
        self._entry(conn, scope_ref, identifier, credits, entry_kind, source_key + ":in", actor)
        return identifier

    def _support_contact(self, conn, scope_ref):
        candidates = []
        if scope_ref["scope_kind"] in {"project", "workspace"}:
            candidates.append(self._scope_where(S.service_configuration_versions, scope_ref))
        candidates.append(S.service_configuration_versions.c.scope_kind == "platform")
        support_email = DEFAULT_SUPPORT_EMAIL
        service_hours = DEFAULT_SERVICE_HOURS
        for predicate in candidates:
            row = conn.execute(
                select(S.service_configuration_versions.c.document)
                .where(predicate)
                .order_by(S.service_configuration_versions.c.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            if isinstance(row, dict):
                email_val = (row.get("support_email") or "").strip() if isinstance(row.get("support_email"), str) else ""
                hours_val = (row.get("service_hours") or "").strip() if isinstance(row.get("service_hours"), str) else ""
                if email_val:
                    support_email = email_val
                if hours_val:
                    service_hours = hours_val
                if email_val or hours_val:
                    break
        return support_email, service_hours

    def read_credit_overview(self, conn, scope, actor, manage=False):
        """Constant 2-SQL read model shared by Commerce wallet and ServiceOperations vsc-engine."""
        scope_ref = self._coerce_scope(scope)
        now = datetime.now(timezone.utc)
        soon_cutoff = now + timedelta(days=7)
        full_visibility = bool(manage or scope_ref["scope_kind"] == "identity")

        # SQL #1: Buckets LEFT JOIN Orders LEFT JOIN aggregated Ledger balances
        ledger_sums = (
            select(
                S.commerce_ledger.c.bucket_id.label("bucket_id"),
                func.coalesce(func.sum(S.commerce_ledger.c.delta), 0).label("balance"),
            )
            .where(self._scope_where(S.commerce_ledger, scope_ref))
            .group_by(S.commerce_ledger.c.bucket_id)
            .subquery("commerce_bucket_balances")
        )
        bucket_stmt = (
            select(
                S.commerce_buckets,
                func.coalesce(ledger_sums.c.balance, 0).label("balance"),
                S.commerce_orders.c.status.label("order_status"),
            )
            .select_from(
                S.commerce_buckets
                .outerjoin(S.commerce_orders, S.commerce_orders.c.id == S.commerce_buckets.c.order_id)
                .outerjoin(ledger_sums, ledger_sums.c.bucket_id == S.commerce_buckets.c.id)
            )
            .where(
                self._scope_where(S.commerce_buckets, scope_ref),
                True if full_visibility else or_(
                    S.commerce_buckets.c.owner_actor == actor,
                    S.commerce_buckets.c.owner_actor.is_(None),
                ),
            )
            .order_by(S.commerce_buckets.c.created_at.desc(), S.commerce_buckets.c.id.desc())
        )
        buckets = []
        expiring_soon_credits = 0
        for row in conn.execute(bucket_stmt).mappings():
            data = dict(row)
            order_status = data.pop("order_status", None)
            balance = int(data.pop("balance", 0) or 0)
            expired = bool(data["expires_at"] and data["expires_at"] <= now)
            frozen = bool(order_status in {"refund_unknown", "refunded"})
            available = 0 if expired or frozen else balance
            if available > 0 and data["expires_at"] and data["expires_at"] <= soon_cutoff:
                expiring_soon_credits += available
            data.update(balance=balance, expired=expired, frozen=frozen, available=available)
            buckets.append(data)

        # SQL #2: Full-table Reservations GROUP BY account_actor, status (zero .limit(60) truncation)
        effective_amount = func.coalesce(S.commerce_reservations.c.actual, S.commerce_reservations.c.bound)
        res_stmt = (
            select(
                S.commerce_reservations.c.account_actor,
                S.commerce_reservations.c.status,
                func.count().label("reservation_count"),
                func.coalesce(func.sum(effective_amount), 0).label("credits_used"),
            )
            .where(
                self._scope_where(S.commerce_reservations, scope_ref),
                S.commerce_reservations.c.status.in_(("reserved", "settled")),
                True if full_visibility else S.commerce_reservations.c.account_actor == actor,
            )
            .group_by(S.commerce_reservations.c.account_actor, S.commerce_reservations.c.status)
        )
        reserved_credits = 0
        total_consumed_credits = 0
        grouped_members = {}
        default_pool_label = (
            "个人钱包" if scope_ref["scope_kind"] == "identity"
            else "团队公共池" if scope_ref["scope_kind"] == "workspace"
            else "项目公共池"
        )
        for row in conn.execute(res_stmt).mappings():
            used = int(row["credits_used"] or 0)
            cnt = int(row["reservation_count"] or 0)
            if row["status"] == "reserved":
                reserved_credits += used
            total_consumed_credits += used
            if manage or scope_ref["scope_kind"] in {"workspace", "identity"}:
                owner_key = row["account_actor"] or default_pool_label
                entry = grouped_members.setdefault(owner_key, {"actor": owner_key, "reservation_count": 0, "credits_used": 0})
                entry["reservation_count"] += cnt
                entry["credits_used"] += used

        member_usage = sorted(grouped_members.values(), key=lambda item: (-item["credits_used"], item["actor"]))
        credit_balance = sum(b["available"] for b in buckets)
        return {
            "buckets": buckets,
            "credit_balance": credit_balance,
            "reserved_credits": reserved_credits,
            "expiring_soon_credits": expiring_soon_credits,
            "total_consumed_credits": total_consumed_credits,
            "member_usage": member_usage,
        }

    def recent_activity_for_overview(self, conn, scope, actor, *, manage=False):
        scope_ref = self._coerce_scope(scope)
        overview = self.read_credit_overview(conn, scope_ref, actor, manage=manage)
        full_visibility = bool(manage or scope_ref["scope_kind"] == "identity")
        bucket_ids = [b["id"] for b in overview["buckets"]]
        raw_ledger = [dict(r) for r in conn.execute(
            select(S.commerce_ledger)
            .where(
                self._scope_where(S.commerce_ledger, scope_ref),
                S.commerce_ledger.c.bucket_id.in_(bucket_ids),
            )
            .order_by(S.commerce_ledger.c.created_at.desc(), S.commerce_ledger.c.id.desc())
            .limit(60)
        ).mappings()] if bucket_ids else []
        ledger_records = self._decorate_ledger_rows(conn, scope_ref, raw_ledger, actor=actor)
        recharge_orders = [
            {k: r[k] for k in ("id", "plan_id", "status", "amount_minor", "currency", "credits", "created_at", "paid_at")}
            for r in conn.execute(
                select(S.commerce_orders)
                .where(
                    self._scope_where(S.commerce_orders, scope_ref),
                    True if full_visibility else S.commerce_orders.c.actor == actor,
                )
                .order_by(S.commerce_orders.c.created_at.desc())
                .limit(50)
            ).mappings()
        ]
        reservations = [dict(r) for r in conn.execute(
            select(S.commerce_reservations)
            .where(
                self._scope_where(S.commerce_reservations, scope_ref),
                True if full_visibility else S.commerce_reservations.c.account_actor == actor,
            )
            .order_by(S.commerce_reservations.c.created_at.desc())
            .limit(60)
        ).mappings()]
        return {
            "credit_balance": overview["credit_balance"],
            "reserved_credits": overview["reserved_credits"],
            "expiring_soon_credits": overview["expiring_soon_credits"],
            "total_consumed_credits": overview["total_consumed_credits"],
            "member_usage": overview["member_usage"],
            "ledger_records": ledger_records,
            "recharge_orders": recharge_orders,
            "reservations": reservations,
        }

    @staticmethod
    def identity_remaining_balance(conn, identity_id, actor):
        now = datetime.now(timezone.utc)
        ledger_sums = (
            select(
                S.commerce_ledger.c.bucket_id.label("bucket_id"),
                func.coalesce(func.sum(S.commerce_ledger.c.delta), 0).label("balance"),
            )
            .group_by(S.commerce_ledger.c.bucket_id)
            .subquery()
        )
        rows = conn.execute(
            select(func.coalesce(ledger_sums.c.balance, 0).label("balance"))
            .select_from(
                S.commerce_buckets
                .outerjoin(ledger_sums, ledger_sums.c.bucket_id == S.commerce_buckets.c.id)
                .outerjoin(S.commerce_orders, S.commerce_orders.c.id == S.commerce_buckets.c.order_id)
            )
            .where(
                or_(
                    and_(S.commerce_buckets.c.scope_kind == "identity", S.commerce_buckets.c.owner_identity_id == identity_id),
                    S.commerce_buckets.c.owner_actor == actor,
                ),
                or_(S.commerce_buckets.c.expires_at.is_(None), S.commerce_buckets.c.expires_at > now),
                or_(S.commerce_buckets.c.order_id.is_(None), ~S.commerce_orders.c.status.in_({"refund_unknown", "refunded"})),
            )
        ).scalars().all()
        return sum(max(0, int(val or 0)) for val in rows)

    @staticmethod
    def _serialize_invoice(row, *, include_sensitive=False, include_document=False):
        data = dict(row)
        billing_ws = data.get("billing_workspace_id")
        if data.get("workspace_id") is None and billing_ws is not None:
            data["workspace_id"] = billing_ws
        if not include_document:
            data.pop("document", None)
        if not include_sensitive:
            data.pop("tax_id", None)
            data.pop("email", None)
        return data

    @staticmethod
    def _serialize_invoice_title(row):
        return {
            "id": row["id"],
            "scope_kind": row["scope_kind"],
            "scope_id": row["owner_identity_id"] or row["workspace_id"] or row["project_id"],
            "invoice_type": row["title_type"],
            "title": row["title"],
            "tax_id": row["tax_id"],
            "email": row["email"],
            "bank_name": row["bank_name"],
            "bank_account": row["bank_account_masked"],
            "address_phone": row["billing_address_phone"],
            "is_default": bool(row["is_default"]),
            "persisted": True,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _query_invoice_titles(self, conn, scope_ref, actor, query=""):
        q = (query or "").strip().lower()
        saved_rows = conn.execute(
            select(S.commerce_invoice_titles)
            .where(self._scope_where(S.commerce_invoice_titles, scope_ref))
            .order_by(
                S.commerce_invoice_titles.c.is_default.desc(),
                S.commerce_invoice_titles.c.updated_at.desc(),
                S.commerce_invoice_titles.c.id.asc(),
            )
            .limit(50)
        ).mappings().all()
        items = []
        seen = set()
        for row in saved_rows:
            if q and q not in row["title"].lower() and q not in row["tax_id"].lower():
                continue
            seen.add((row["title"], row["tax_id"]))
            items.append(self._serialize_invoice_title(row))
        if scope_ref["scope_kind"] == "project":
            legacy_rows = conn.execute(
                select(S.commerce_invoices)
                .where(
                    self._scope_where(S.commerce_invoices, scope_ref),
                    S.commerce_invoices.c.actor == actor,
                )
                .order_by(S.commerce_invoices.c.created_at.desc())
                .limit(100)
            ).mappings().all()
            for row in legacy_rows:
                key = (row["title"], row["tax_id"])
                if key in seen:
                    continue
                if q and q not in row["title"].lower() and q not in row["tax_id"].lower():
                    continue
                seen.add(key)
                items.append({
                    "title": row["title"],
                    "tax_id": row["tax_id"],
                    "email": row["email"],
                    "workspace_id": row["billing_workspace_id"] or row["workspace_id"],
                    "invoice_type": "personal" if row["tax_id"].upper() == "PERSONAL" else "enterprise",
                    "is_default": False,
                    "persisted": False,
                    "last_used_at": row["created_at"],
                })
        return items[:50]

    def _scope_label(self, conn, scope_ref, actor=None):
        kind = scope_ref["scope_kind"]
        if kind == "identity":
            row = conn.execute(select(S.access_identities.c.display_name, S.access_identities.c.actor).where(
                S.access_identities.c.id == scope_ref["owner_identity_id"]
            )).mappings().first()
            label = (row["display_name"] or row["actor"]) if row else (actor or scope_ref["scope_id"])
            return f"个人钱包 · {label}"
        if kind == "workspace":
            name = conn.execute(select(S.access_workspaces.c.name).where(
                S.access_workspaces.c.id == scope_ref["workspace_id"]
            )).scalar_one_or_none()
            return f"团队资金池 · {name or scope_ref['scope_id']}"
        if kind == "project":
            name = conn.execute(select(S.projects.c.name).where(
                S.projects.c.id == scope_ref["project_id"]
            )).scalar_one_or_none()
            return f"项目账本 · {name or scope_ref['scope_id']}"
        return "平台公共定价"

    def _decorate_ledger_rows(self, conn, scope_ref, rows, actor=None):
        if not rows:
            return []
        funding_label = self._scope_label(conn, scope_ref, actor=actor)
        attr_pids = {r["attribution_project_id"] for r in rows if r.get("attribution_project_id")}
        proj_names = {}
        if attr_pids:
            proj_names = {
                r["id"]: r["name"]
                for r in conn.execute(select(S.projects.c.id, S.projects.c.name).where(S.projects.c.id.in_(attr_pids))).mappings()
            }
        job_pairs = {(r["attribution_project_id"], r["job_id"]) for r in rows if r.get("attribution_project_id") and r.get("job_id")}
        recorded_bills = set()
        if job_pairs:
            by_proj = {}
            for pid, jid in job_pairs:
                by_proj.setdefault(pid, set()).add(jid)
            for pid, jids in by_proj.items():
                billed = conn.execute(select(S.job_events.c.job_id).where(
                    S.job_events.c.project_id == pid,
                    S.job_events.c.job_id.in_(jids),
                    S.job_events.c.event_type == "bill_recorded",
                )).scalars().all()
                for jid in billed:
                    recorded_bills.add((pid, jid))
        decorated = []
        for row in rows:
            item = dict(row)
            attr_pid = item.get("attribution_project_id")
            jid = item.get("job_id")
            item["funding_scope_kind"] = item["scope_kind"]
            item["funding_scope_label"] = funding_label
            item["attribution_project_name"] = proj_names.get(attr_pid) if attr_pid else None
            item["supplier_bill_status"] = "recorded" if (attr_pid and jid and (attr_pid, jid) in recorded_bills) else "unrecorded"
            decorated.append(item)
        return decorated

    def summary_scoped(self, scope, actor, manage=False):
        scope_ref = self._coerce_scope(scope)
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                project = self.store._project(conn, scope_ref["project_id"])
                revision = int(project["revision"])
                plan_where = self._scope_where(S.commerce_plan_versions, scope_ref)
            else:
                revision = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
                if scope_ref["scope_kind"] == "workspace":
                    plan_where = or_(
                        self._scope_where(S.commerce_plan_versions, scope_ref),
                        S.commerce_plan_versions.c.scope_kind == "platform",
                    )
                else:
                    plan_where = S.commerce_plan_versions.c.scope_kind == "platform"

            plans = {}
            for row in conn.execute(
                select(S.commerce_plan_versions)
                .where(plan_where)
                .order_by(S.commerce_plan_versions.c.version.desc())
            ).mappings():
                plans.setdefault(row["plan_key"], dict(row))

            policy = self._policy(conn, scope_ref, allow_platform_fallback=(scope_ref["scope_kind"] != "project"))
            full_visibility = bool(manage or scope_ref["scope_kind"] == "identity")

            orders = [dict(row) for row in conn.execute(
                select(S.commerce_orders)
                .where(
                    self._scope_where(S.commerce_orders, scope_ref),
                    True if full_visibility else S.commerce_orders.c.actor == actor,
                )
                .order_by(S.commerce_orders.c.created_at.desc())
                .limit(100)
            ).mappings()]

            overview = self.read_credit_overview(conn, scope_ref, actor, manage=manage)
            buckets = overview["buckets"]
            bucket_ids = [b["id"] for b in buckets]

            raw_ledger = [dict(row) for row in conn.execute(
                select(S.commerce_ledger)
                .where(
                    self._scope_where(S.commerce_ledger, scope_ref),
                    S.commerce_ledger.c.bucket_id.in_(bucket_ids),
                )
                .order_by(S.commerce_ledger.c.created_at.desc(), S.commerce_ledger.c.id.desc())
                .limit(200)
            ).mappings()] if bucket_ids else []
            ledger = self._decorate_ledger_rows(conn, scope_ref, raw_ledger, actor=actor)

            invoice_rows = conn.execute(
                select(S.commerce_invoices)
                .where(
                    self._scope_where(S.commerce_invoices, scope_ref),
                    True if full_visibility else S.commerce_invoices.c.actor == actor,
                )
                .order_by(S.commerce_invoices.c.created_at.desc())
                .limit(100)
            ).mappings().all()
            invoices = [self._serialize_invoice(row) for row in invoice_rows]
            active_invoiced_order_ids = {row["order_id"] for row in invoices if row["status"] != "void"}
            paid_orders = [row for row in orders if row["status"] == "paid"]
            support_email, service_hours = self._support_contact(conn, scope_ref)
            invoice_summary = {
                "paid_order_count": len(paid_orders),
                "billable_order_count": sum(1 for row in paid_orders if row["id"] not in active_invoiced_order_ids),
                "invoiced_order_count": sum(1 for row in paid_orders if row["id"] in active_invoiced_order_ids),
                "issued_count": sum(1 for row in invoices if row["status"] == "issued"),
                "pending_count": sum(1 for row in invoices if row["status"] in {"created", "pending", "submission_unknown", "unconfigured"}),
                "support_email": support_email,
                "service_hours": service_hours,
            }

            reservations = [dict(row) for row in conn.execute(
                select(S.commerce_reservations)
                .where(
                    self._scope_where(S.commerce_reservations, scope_ref),
                    True if full_visibility else S.commerce_reservations.c.account_actor == actor,
                )
                .order_by(S.commerce_reservations.c.created_at.desc())
                .limit(100)
            ).mappings()]

            invoice_titles = self._query_invoice_titles(conn, scope_ref, actor)
            access_rev = int(conn.execute(select(func.coalesce(func.max(S.access_state.c.revision), 0))).scalar_one() or 0)
            plan_digest = digest([{"id": p["id"], "v": p["version"]} for p in plans.values()])

            payload = {
                "_etag_seed": f"{scope_ref['scope_kind']}:{scope_ref['scope_id']}:{revision}:{access_rev}:{plan_digest}",
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "revision": revision,
                "plans": list(plans.values()),
                "policy": policy,
                "orders": orders,
                "buckets": buckets,
                "ledger": ledger,
                "invoices": invoices,
                "invoice_titles": invoice_titles,
                "invoice_summary": invoice_summary,
                "reservations": reservations,
                "credit_balance": overview["credit_balance"],
                "reserved_credits": overview["reserved_credits"],
                "expiring_soon_credits": overview["expiring_soon_credits"],
                "total_consumed_credits": overview["total_consumed_credits"],
                "member_usage": overview["member_usage"],
                "credit_unit": "commercial_credit",
                "native_units_are_separate": True,
            }
            if scope_ref["scope_kind"] == "project":
                payload["project_id"] = scope_ref["project_id"]
            return clean(payload)

    def summary(self, p, actor, manage=False):
        return self.summary_scoped(make_scope_ref("project", p), actor, manage=manage)

    def platform_summary(self, *, is_admin=False):
        scope_ref = make_scope_ref("platform")
        with self.store.engine.connect() as conn:
            revision = self.store._scoped_revision(conn, "commerce", "platform")
            plans = {}
            all_versions = []
            for row in conn.execute(
                select(S.commerce_plan_versions)
                .where(S.commerce_plan_versions.c.scope_kind == "platform")
                .order_by(S.commerce_plan_versions.c.version.desc())
            ).mappings():
                item = dict(row)
                all_versions.append(item)
                plans.setdefault(row["plan_key"], item)
            policy = self._policy(conn, scope_ref)
            campaigns = [
                {k: v for k, v in dict(row).items() if k != "code_sha256"}
                for row in conn.execute(
                    select(S.commerce_campaigns)
                    .where(S.commerce_campaigns.c.scope_kind == "platform")
                    .order_by(S.commerce_campaigns.c.created_at.desc())
                    .limit(100)
                ).mappings()
            ]
            provider_models = []
            if is_admin:
                provider_models = [
                    dict(row)
                    for row in conn.execute(
                        select(
                            S.provider_models.c.id,
                            S.provider_models.c.provider_id,
                            S.provider_models.c.model_key,
                            S.provider_models.c.model_version,
                            S.provider_models.c.modality,
                            S.provider_models.c.enabled,
                        ).order_by(S.provider_models.c.provider_id.asc(), S.provider_models.c.model_key.asc())
                    ).mappings()
                ]
            return clean({
                "_etag_seed": f"platform:{revision}:{len(all_versions)}:{len(campaigns)}",
                "scope_kind": "platform",
                "scope_id": "platform",
                "revision": revision,
                "plans": list(plans.values()),
                "plan_history": all_versions[:50],
                "policy": policy,
                "campaigns": campaigns,
                "provider_models": provider_models,
            })

    def invoice_titles_scoped(self, scope, actor, query=""):
        scope_ref = self._coerce_scope(scope)
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                project = self.store._project(conn, scope_ref["project_id"])
                revision = int(project["revision"])
            else:
                revision = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
            items = self._query_invoice_titles(conn, scope_ref, actor, query=query)
            result = {
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "revision": revision,
                "items": items,
            }
            if scope_ref["scope_kind"] == "project":
                result["project_id"] = scope_ref["project_id"]
            return clean(result)

    def invoice_titles(self, p, actor, query=""):
        return self.invoice_titles_scoped(make_scope_ref("project", p), actor, query=query)

    def save_invoice_title(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            _, person, _ = self.store._access_principal(conn)
            creator_id = person["id"] if person else sref["owner_identity_id"]
            if not creator_id:
                row = conn.execute(select(S.access_identities.c.id).where(S.access_identities.c.actor == kw["actor"])).scalar_one_or_none()
                if not row:
                    raise ResourceError("需要真实成员身份保存常用发票抬头", "access_denied", 403)
                creator_id = row
            now = datetime.now(timezone.utc)
            target_id = checked_id(payload["id"]) if payload.get("id") else None
            if payload["is_default"]:
                conn.execute(
                    update(S.commerce_invoice_titles)
                    .where(
                        self._scope_where(S.commerce_invoice_titles, sref),
                        S.commerce_invoice_titles.c.is_default.is_(True),
                    )
                    .values(is_default=False, updated_at=now)
                )
            values = {
                "title_type": payload["invoice_type"],
                "title": payload["title"],
                "tax_id": payload["tax_id"],
                "email": payload["email"],
                "bank_name": payload.get("bank_name"),
                "bank_account_masked": payload.get("bank_account"),
                "billing_address_phone": payload.get("address_phone"),
                "is_default": payload["is_default"],
                "updated_at": now,
            }
            if target_id:
                existing = self._one_scoped(conn, S.commerce_invoice_titles, sref, target_id)
                conn.execute(
                    update(S.commerce_invoice_titles)
                    .where(S.commerce_invoice_titles.c.id == existing["id"])
                    .values(**values)
                )
                saved = self._one_scoped(conn, S.commerce_invoice_titles, sref, existing["id"])
            else:
                identifier = new_id()
                conn.execute(insert(S.commerce_invoice_titles).values(
                    **self._scope_cols(sref),
                    id=identifier,
                    created_by=creator_id,
                    created_at=now,
                    **values,
                ))
                saved = self._one_scoped(conn, S.commerce_invoice_titles, sref, identifier)
            return self._serialize_invoice_title(saved)

        return self._mutate_for_scope(scope_ref, "commerce_save_invoice_title", payload, work, **kw)

    def delete_invoice_title(self, scope, title_id, payload, **kw):
        scope_ref = self._coerce_scope(scope)
        checked = checked_id(title_id)

        def work(conn, sref, _rev):
            existing = self._one_scoped(conn, S.commerce_invoice_titles, sref, checked)
            conn.execute(delete(S.commerce_invoice_titles).where(S.commerce_invoice_titles.c.id == existing["id"]))
            return {"deleted": True, "id": existing["id"]}

        return self._mutate_for_scope(scope_ref, "commerce_delete_invoice_title", dict(payload, title_id=checked), work, **kw)

    def _compute_plan_diff(self, conn, scope_ref, payload):
        doc = payload["document"]
        metering_enabled = bool(payload["metering_enabled"])
        base_version_id = checked_id(payload["base_version_id"]) if payload.get("base_version_id") else None

        if scope_ref["scope_kind"] == "project":
            current_revision = int(self.store._project(conn, scope_ref["project_id"])["revision"])
        else:
            current_revision = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])

        prior = conn.execute(
            select(S.commerce_plan_versions)
            .where(
                self._scope_where(S.commerce_plan_versions, scope_ref),
                S.commerce_plan_versions.c.plan_key == doc["plan_key"],
            )
            .order_by(S.commerce_plan_versions.c.version.desc())
            .limit(1)
        ).mappings().first()

        prior_id = prior["id"] if prior else None
        if prior_id != base_version_id:
            raise Conflict(
                "价格已有新版本，请读取比较",
                "commerce_plan_conflict",
                details={
                    "latest_version_id": prior_id,
                    "latest_version_number": int(prior["version"]) if prior else 0,
                    "latest_document": prior["document"] if prior else None,
                    "current_revision": current_revision,
                },
            )

        model_names = {}
        for rate in doc["rates"]:
            mid = checked_id(rate["model_id"])
            model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == mid)).mappings().first()
            if model is None:
                raise ResourceError("价格引用的模型未登记", "commerce_model_missing", 422, details={"field": "rates", "model_id": mid})
            model_names[mid] = f"{model['provider_id']}/{model['model_key']}"

        canonical_rates = sorted(
            [{"model_id": checked_id(r["model_id"]), "unit": r["unit"], "credits_per_unit": int(r["credits_per_unit"])} for r in doc["rates"]],
            key=lambda item: (item["model_id"], item["unit"]),
        )
        canonical_doc = {
            **{k: doc[k] for k in sorted(PLAN_FIELD_LABELS)},
            "purposes": list(doc["purposes"]),
            "rates": canonical_rates,
        }

        prior_doc = prior["document"] if prior else {}
        field_diffs = []
        for field, label in PLAN_FIELD_LABELS.items():
            before = prior_doc.get(field) if prior else None
            after = canonical_doc[field]
            if not prior or before != after:
                field_diffs.append({"field": field, "label": label, "before": before, "after": after})

        prior_rates = {(r["model_id"], r["unit"]): int(r["credits_per_unit"]) for r in prior_doc.get("rates", [])}
        next_rates = {(r["model_id"], r["unit"]): int(r["credits_per_unit"]) for r in canonical_rates}
        added, changed, removed = [], [], []
        for (mid, unit), price in sorted(next_rates.items()):
            mname = model_names.get(mid, mid)
            if (mid, unit) not in prior_rates:
                added.append({"model_id": mid, "model_name": mname, "unit": unit, "credits_per_unit": price})
            elif prior_rates[(mid, unit)] != price:
                changed.append({"model_id": mid, "model_name": mname, "unit": unit,
                                "before_credits_per_unit": prior_rates[(mid, unit)], "after_credits_per_unit": price})
        for (mid, unit), old_price in sorted(prior_rates.items()):
            if (mid, unit) not in next_rates:
                mrow = conn.execute(select(S.provider_models.c.provider_id, S.provider_models.c.model_key).where(S.provider_models.c.id == mid)).mappings().first()
                mname = f"{mrow['provider_id']}/{mrow['model_key']}" if mrow else mid
                removed.append({"model_id": mid, "model_name": mname, "unit": unit, "credits_per_unit": old_price})

        has_changes = bool(field_diffs or added or changed or removed or not prior)
        diff_sha = digest({
            "scope_kind": scope_ref["scope_kind"],
            "scope_id": scope_ref["scope_id"],
            "base_version_id": base_version_id,
            "metering_enabled": metering_enabled,
            "canonical_document": canonical_doc,
        })
        return {
            "valid": True,
            "plan_key": canonical_doc["plan_key"],
            "base_version_id": base_version_id,
            "base_version_number": int(prior["version"]) if prior else None,
            "next_version_number": int(prior["version"]) + 1 if prior else 1,
            "current_revision": current_revision,
            "has_changes": has_changes,
            "field_diffs": field_diffs,
            "rate_diffs": {"added": added, "changed": changed, "removed": removed},
            "canonical_document": canonical_doc,
            "diff_sha256": diff_sha,
        }

    def preview_plan_diff(self, scope, payload):
        scope_ref = self._coerce_scope(scope)
        with self.store.engine.connect() as conn:
            return clean(self._compute_plan_diff(conn, scope_ref, payload))

    def configure_plan_scoped(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            diff = self._compute_plan_diff(conn, sref, payload)
            if payload.get("diff_sha256") and payload["diff_sha256"] != diff["diff_sha256"]:
                raise Conflict("预检差异摘要与当前提交内容不一致，请重新预览", "commerce_plan_conflict",
                               details={"expected_diff_sha256": diff["diff_sha256"], "current_revision": diff["current_revision"]})
            doc = payload["document"]
            identifier = new_id()
            version = diff["next_version_number"]
            conn.execute(insert(S.commerce_plan_versions).values(
                **self._scope_cols(sref),
                id=identifier,
                base_version_id=diff["base_version_id"],
                plan_key=doc["plan_key"],
                version=version,
                document=doc,
                sha256=digest(doc),
                actor=kw["actor"],
            ))
            for rate in doc["rates"]:
                conn.execute(insert(S.commerce_rates).values(
                    **self._scope_cols(sref),
                    id=new_id(),
                    plan_id=identifier,
                    model_id=checked_id(rate["model_id"]),
                    unit=rate["unit"],
                    credits_per_unit=rate["credits_per_unit"],
                ))
            existing_setting = conn.execute(
                select(S.commerce_settings.c.id).where(self._scope_where(S.commerce_settings, sref))
            ).scalar_one_or_none()
            if existing_setting:
                conn.execute(
                    update(S.commerce_settings)
                    .where(S.commerce_settings.c.id == existing_setting)
                    .values(price_version_id=identifier, enabled=payload["metering_enabled"])
                )
            else:
                conn.execute(insert(S.commerce_settings).values(
                    **self._scope_cols(sref),
                    id=new_id(),
                    price_version_id=identifier,
                    enabled=payload["metering_enabled"],
                ))
            return {"id": identifier, "version": version, "sha256": digest(doc), "plan_key": doc["plan_key"]}

        clean_payload = {k: v for k, v in payload.items() if k in {"document", "base_version_id", "metering_enabled", "diff_sha256", "confirmed"}}
        return self._mutate_for_scope(scope_ref, "commerce_configure_plan", clean_payload, work, **kw)

    def configure_plan(self, p, payload, **kw):
        return self.configure_plan_scoped(make_scope_ref("project", p), payload, **kw)

    def preview_campaign_diff(self, scope, payload):
        scope_ref = self._coerce_scope(scope)
        code_sha = hashlib.sha256(payload["code"].encode()).hexdigest()
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                current_revision = int(self.store._project(conn, scope_ref["project_id"])["revision"])
            else:
                current_revision = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
            dup = conn.execute(select(S.commerce_campaigns.c.id).where(
                self._scope_where(S.commerce_campaigns, scope_ref),
                S.commerce_campaigns.c.code_sha256 == code_sha,
            )).scalar_one_or_none()
            if dup:
                raise Conflict("同一作用域下该活动兑换码已存在", "campaign_code_conflict")
            canonical_doc = {
                "title": payload["title"],
                "credits": int(payload["credits"]),
                "kind": payload["kind"],
                "purposes": list(payload["purposes"]),
                "starts_at": instant(payload["starts_at"]).isoformat(),
                "ends_at": instant(payload["ends_at"]).isoformat(),
                "credit_expires_at": instant(payload["credit_expires_at"]).isoformat(),
                "daily": bool(payload["daily"]),
                "code_sha256": code_sha,
            }
            field_diffs = [
                {"field": field, "label": label, "before": None, "after": canonical_doc[field]}
                for field, label in CAMPAIGN_FIELD_LABELS.items()
            ]
            return clean({
                "valid": True,
                "current_revision": current_revision,
                "has_changes": True,
                "field_diffs": field_diffs,
                "canonical_document": canonical_doc,
                "diff_sha256": digest({"scope_kind": scope_ref["scope_kind"], "scope_id": scope_ref["scope_id"], "campaign": canonical_doc}),
            })

    def configure_campaign_scoped(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            code_sha = hashlib.sha256(payload["code"].encode()).hexdigest()
            dup = conn.execute(select(S.commerce_campaigns.c.id).where(
                self._scope_where(S.commerce_campaigns, sref),
                S.commerce_campaigns.c.code_sha256 == code_sha,
            )).scalar_one_or_none()
            if dup:
                raise Conflict("同一作用域下该活动兑换码已存在", "campaign_code_conflict")
            identifier = new_id()
            values = {k: v for k, v in payload.items() if k in {"title", "credits", "kind", "purposes", "daily"}}
            values.update({k: instant(payload[k]) for k in ("starts_at", "ends_at", "credit_expires_at")})
            conn.execute(insert(S.commerce_campaigns).values(
                **self._scope_cols(sref),
                id=identifier,
                actor=kw["actor"],
                code_sha256=code_sha,
                **values,
            ))
            return {"id": identifier}

        return self._mutate_for_scope(scope_ref, "commerce_configure_campaign", payload, work, **kw)

    def configure_campaign(self, p, payload, **kw):
        return self.configure_campaign_scoped(make_scope_ref("project", p), payload, **kw)

    def create_order_scoped(self, scope, payload, *, gateway, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            plan = self._plan(conn, sref, checked_id(payload["plan_id"]))
            doc = plan["document"]
            require_supported_entitlements(doc)
            plan_scope = make_scope_ref(
                plan["scope_kind"],
                plan["project_id"] or plan["workspace_id"] or "platform",
            )
            latest = conn.execute(
                select(func.max(S.commerce_plan_versions.c.version)).where(
                    self._scope_where(S.commerce_plan_versions, plan_scope),
                    S.commerce_plan_versions.c.plan_key == plan["plan_key"],
                )
            ).scalar_one()
            if plan["version"] != latest:
                raise Conflict("套餐价格已更新，请重新读取", "commerce_plan_conflict")
            renewal = payload.get("renewal_of_order_id")
            if renewal:
                prior = self._one_scoped(conn, S.commerce_orders, sref, renewal)
                if prior["status"] != "paid" or prior["plan_id"] != plan["id"] or doc["renewal_policy"] != "manual_from_payment":
                    raise Conflict("原订单或套餐不支持此手动续期", "renewal_unavailable")
            identifier = new_id()
            conn.execute(insert(S.commerce_orders).values(
                **self._scope_cols(sref),
                id=identifier,
                plan_id=plan["id"],
                renewal_of_order_id=renewal,
                actor=kw["actor"],
                gateway=gateway,
                status="created",
                amount_minor=doc["amount_minor"],
                currency=doc["currency"],
                credits=doc["credits"],
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=doc["checkout_minutes"]),
            ))
            return {"id": identifier, "status": "created"}

        capability = "edit" if scope_ref["scope_kind"] == "project" else "manage"
        return self._mutate_for_scope(scope_ref, "commerce_create_order", payload, work, capability=capability, **kw)

    def create_order(self, p, payload, *, gateway, **kw):
        return self.create_order_scoped(make_scope_ref("project", p), payload, gateway=gateway, **kw)

    def entitlements(self, p, conn=None):
        from contextlib import nullcontext
        with (nullcontext(conn) if conn is not None else self.store.engine.connect()) as connection:
            project = self.store._project(connection, p)
            plan = self._policy(connection, make_scope_ref("project", project["id"]), allow_platform_fallback=False)
            if not plan:
                return {"configured": False}
            return {
                "configured": True,
                "price_version_id": plan["id"],
                **{k: plan["document"][k] for k in ("seat_limit", "max_concurrent_jobs", "watermark_required")},
                "watermark_consumer": "edit-export-v1" if plan["document"]["watermark_required"] else "not_required",
            }

    def order_scoped(self, scope, identifier):
        scope_ref = self._coerce_scope(scope)
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                rev = int(self.store._project(conn, scope_ref["project_id"])["revision"])
            else:
                rev = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
            row = self._one_scoped(conn, S.commerce_orders, scope_ref, identifier)
            return clean(dict(row, revision=rev, scope_id=scope_ref["scope_id"]))

    def order(self, p, identifier):
        return self.order_scoped(make_scope_ref("project", p), identifier)

    def find_order_scope(self, order_id):
        checked = checked_id(order_id)
        with self.store.engine.connect() as conn:
            row = conn.execute(select(S.commerce_orders).where(S.commerce_orders.c.id == checked)).mappings().first()
            if row is None:
                raise NotFound("支付订单不存在")
            scope_id = row["owner_identity_id"] or row["workspace_id"] or row["project_id"]
            return make_scope_ref(row["scope_kind"], scope_id), clean(dict(row))

    def claim_checkout(self, scope, identifier):
        scope_ref = self._coerce_scope(scope)

        def work(conn, _target):
            order = self._one_scoped(conn, S.commerce_orders, scope_ref, identifier)
            claimed = order["status"] == "created"
            if claimed:
                conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.id == order["id"]).values(status="checkout_unknown"))
            return {"claimed": claimed, "order": order}

        return self._internal(scope_ref, "commerce_claim_checkout", {"order_id": identifier}, work)

    def checkout_result(self, scope, identifier, checkout):
        scope_ref = self._coerce_scope(scope)
        url = checkout.get("checkout_url")
        parsed = urlsplit(url or "")
        if url and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ResourceError("收银台地址无效", "checkout_url_invalid")
        if not isinstance(checkout.get("external_id"), str) or not checkout["external_id"]:
            raise ResourceError("缺少支付订单回执", "checkout_receipt_missing")

        def work(conn, _target):
            row = self._one_scoped(conn, S.commerce_orders, scope_ref, identifier)
            if row["status"] == "checkout_unknown":
                conn.execute(
                    update(S.commerce_orders)
                    .where(S.commerce_orders.c.id == row["id"])
                    .values(status="pending", external_id=checkout["external_id"], checkout_url=url)
                )
            return {"id": identifier}

        return self._internal(scope_ref, "commerce_checkout_result", {"order_id": identifier, "checkout": checkout}, work, "checkout:" + identifier)

    def payment_event(self, scope, event, expected_order=None):
        from vsc.adapters.providers.commerce import PaymentEvent
        scope_ref = self._coerce_scope(scope)
        if (
            not isinstance(event, PaymentEvent)
            or event.status not in {"pending", "paid", "expired", "cancelled", "refunded", "refund_rejected"}
            or type(event.amount_minor) is not int
            or event.amount_minor <= 0
            or any(not isinstance(value, str) or not 1 <= len(value) <= 200 for value in (event.event_id, event.external_id, event.gateway))
        ):
            raise ResourceError("支付回执字段不正确", "payment_event_invalid")
        if expected_order and event.order_id != expected_order:
            raise ResourceError("支付查询返回其他订单", "payment_event_invalid")
        document = asdict(event)

        def work(conn, _target):
            order = self._one_scoped(conn, S.commerce_orders, scope_ref, checked_id(event.order_id))
            if (order["gateway"], order["amount_minor"], order["currency"]) != (event.gateway, event.amount_minor, event.currency):
                raise ResourceError("支付回执金额、币种或网关与固定订单不符", "payment_event_mismatch")
            if order["external_id"] and order["external_id"] != event.external_id:
                raise Conflict("外部订单编号不能替换", "payment_event_mismatch")
            prior = conn.execute(select(S.commerce_payment_events).where(
                S.commerce_payment_events.c.gateway == event.gateway,
                S.commerce_payment_events.c.event_id == event.event_id,
            )).mappings().first()
            if prior:
                if prior["sha256"] != digest(document) or prior["order_id"] != order["id"]:
                    raise Conflict("相同支付事件不能改变内容", "payment_event_mismatch")
                return {"id": order["id"], "status": order["status"]}
            conn.execute(insert(S.commerce_payment_events).values(
                **self._scope_cols(scope_ref),
                id=new_id(),
                order_id=order["id"],
                gateway=event.gateway,
                event_id=event.event_id,
                sha256=digest(document),
                document=document,
            ))
            plan = self._plan(conn, scope_ref, order["plan_id"])["document"]
            status = order["status"]
            now = datetime.now(timezone.utc)
            became_refunded = False
            if event.status == "paid" and status not in {"paid", "refunded", "refund_unknown"}:
                if not order["paid_at"]:
                    self._bucket(
                        conn, scope_ref, source_key="order:" + order["id"], credits=order["credits"],
                        owner=order["actor"], kind=plan["bucket_kind"], purposes=plan["purposes"],
                        expires=now + timedelta(days=plan["validity_days"]), order=order["id"],
                    )
                status = "paid"
                conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.id == order["id"]).values(paid_at=order["paid_at"] or now))
            elif event.status == "refund_rejected":
                if status == "refund_unknown":
                    status = "paid"
            elif event.status == "refunded" and status != "refunded":
                buckets = conn.execute(select(S.commerce_buckets).where(
                    self._scope_where(S.commerce_buckets, scope_ref),
                    S.commerce_buckets.c.order_id == order["id"],
                )).mappings().all()
                if not order["paid_at"] or sum(self._balance(conn, scope_ref, b["id"]) for b in buckets) != order["credits"]:
                    raise Conflict("订单存在已发生用量，不能以全额退款抹除", "refund_usage_conflict")
                for bucket in buckets:
                    self._entry(conn, scope_ref, bucket["id"], -self._balance(conn, scope_ref, bucket["id"]),
                                "refund", "refund:" + order["id"] + ":" + bucket["id"], "commerce-gateway")
                status = "refunded"
                became_refunded = True
            elif status not in {"paid", "refund_unknown", "refunded"}:
                status = event.status
            conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.id == order["id"]).values(
                status=status, external_id=event.external_id, error_code=None
            ))
            if became_refunded:
                conn.execute(
                    update(S.commerce_invoices)
                    .where(S.commerce_invoices.c.order_id == order["id"], S.commerce_invoices.c.status != "void")
                    .values(status="void", voided_at=now, void_reason="order_refunded")
                )
            return {"id": order["id"], "status": status}

        from vsc.assets.access_control import current_principal
        principal = current_principal()
        observer = principal.actor if principal and principal.actor else "commerce-consumer"
        return self._internal(
            scope_ref, "commerce_gateway_event", document, work,
            "commerce-event:" + hashlib.sha256((event.gateway + ":" + event.event_id + ":" + observer).encode()).hexdigest(),
        )

    def claim_refund(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, _target):
            order = self._one_scoped(conn, S.commerce_orders, scope_ref, payload["order_id"])
            if order["status"] in {"refund_unknown", "refunded"}:
                return {"claimed": False, "id": order["id"]}
            plan = self._plan(conn, scope_ref, order["plan_id"])["document"]
            buckets = conn.execute(select(S.commerce_buckets.c.id).where(
                self._scope_where(S.commerce_buckets, scope_ref),
                S.commerce_buckets.c.order_id == order["id"],
            )).scalars().all()
            if order["status"] != "paid" or plan["refund_policy"] != "unused_order_only" or sum(self._balance(conn, scope_ref, b) for b in buckets) != order["credits"]:
                raise Conflict("只可按已配置政策退回完全未消费订单；已有用量保留", "refund_unavailable")
            conn.execute(update(S.commerce_orders).where(S.commerce_orders.c.id == order["id"]).values(status="refund_unknown"))
            return {"claimed": True, "id": order["id"]}

        return self._internal(scope_ref, "commerce_claim_refund", payload, work)

    def redeem_scoped(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            now = datetime.now(timezone.utc)
            code_sha = hashlib.sha256(payload["code"].encode()).hexdigest()
            if sref["scope_kind"] == "identity":
                campaign_where = S.commerce_campaigns.c.scope_kind == "platform"
            else:
                campaign_where = or_(
                    self._scope_where(S.commerce_campaigns, sref),
                    S.commerce_campaigns.c.scope_kind == "platform",
                )
            campaign = conn.execute(
                select(S.commerce_campaigns)
                .where(campaign_where, S.commerce_campaigns.c.code_sha256 == code_sha)
                .order_by(
                    (S.commerce_campaigns.c.scope_kind == sref["scope_kind"]).desc(),
                    S.commerce_campaigns.c.created_at.desc(),
                )
                .limit(1)
            ).mappings().first()
            if not campaign or not campaign["starts_at"] <= now < campaign["ends_at"]:
                raise ResourceError("活动码不存在或不在有效期内", "campaign_unavailable")
            redeemed_day = now.date()
            period = redeemed_day.isoformat() if campaign["daily"] else "once"
            prior = conn.execute(select(S.commerce_redemptions).where(
                self._scope_where(S.commerce_redemptions, sref),
                S.commerce_redemptions.c.campaign_id == campaign["id"],
                S.commerce_redemptions.c.actor == kw["actor"],
                S.commerce_redemptions.c.period == period,
            )).mappings().first()
            if prior:
                overview = self.read_credit_overview(conn, sref, kw["actor"], manage=(sref["scope_kind"] != "project"))
                return {
                    "id": prior["id"],
                    "bucket_id": prior["bucket_id"],
                    "already_redeemed": True,
                    "credits_added": 0,
                    "credit_balance": overview["credit_balance"],
                }
            identifier = new_id()
            bucket = self._bucket(
                conn, sref, source_key="campaign:" + identifier, credits=campaign["credits"],
                owner=kw["actor"], kind=campaign["kind"], purposes=campaign["purposes"],
                expires=campaign["credit_expires_at"], actor=kw["actor"],
            )
            conn.execute(insert(S.commerce_redemptions).values(
                **self._scope_cols(sref),
                id=identifier,
                campaign_id=campaign["id"],
                bucket_id=bucket,
                actor=kw["actor"],
                period=period,
                redeemed_day=redeemed_day,
                created_at=now,
            ))
            overview = self.read_credit_overview(conn, sref, kw["actor"], manage=(sref["scope_kind"] != "project"))
            return {
                "id": identifier,
                "bucket_id": bucket,
                "already_redeemed": False,
                "credits_added": int(campaign["credits"]),
                "credit_balance": overview["credit_balance"],
            }

        capability = "edit" if scope_ref["scope_kind"] == "project" else "manage"
        return self._mutate_for_scope(scope_ref, "commerce_redeem", payload, work, capability=capability, **kw)

    def redeem(self, p, payload, **kw):
        return self.redeem_scoped(make_scope_ref("project", p), payload, **kw)

    def allocate_scoped(self, scope, payload, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            source = self._one_scoped(conn, S.commerce_buckets, sref, payload["bucket_id"])
            if payload["target_actor"]:
                if sref["scope_kind"] == "project":
                    if not self.store.access_member_valid(sref["project_id"], payload["target_actor"], conn=conn):
                        raise ResourceError("目标不是有效项目成员", "commerce_member_invalid")
                elif sref["scope_kind"] == "workspace":
                    member = conn.execute(
                        select(S.access_workspace_members.c.identity_id)
                        .join(S.access_identities, S.access_identities.c.id == S.access_workspace_members.c.identity_id)
                        .where(
                            S.access_workspace_members.c.workspace_id == sref["workspace_id"],
                            S.access_workspace_members.c.active.is_(True),
                            S.access_identities.c.active.is_(True),
                            S.access_identities.c.actor == payload["target_actor"],
                        )
                    ).first()
                    if not member:
                        raise ResourceError("目标不是有效工作室成员", "commerce_member_invalid")
                else:
                    raise ResourceError("个人钱包不支持向其他成员划拨额度", "commerce_member_invalid")
            if source["expires_at"] and source["expires_at"] <= datetime.now(timezone.utc):
                raise Conflict("已过期额度不能重新分配", "credit_expired")
            if source["order_id"] and self._one_scoped(conn, S.commerce_orders, sref, source["order_id"])["status"] != "paid":
                raise Conflict("订单额度已冻结", "credit_frozen")
            if payload["reclaim"] and (source["owner_actor"] is None or payload["target_actor"] is not None):
                raise ResourceError("回收将成员未用额度回到公共池", "credit_reclaim_invalid")
            if self._balance(conn, sref, source["id"]) < payload["credits"]:
                raise Conflict("可分配额度不足", "credit_insufficient")
            key = "transfer:" + new_id()
            kind = "reclaim" if payload["reclaim"] else "allocate"
            self._entry(conn, sref, source["id"], -payload["credits"], kind + "_out", key + ":out", kw["actor"])
            identifier = self._bucket(
                conn, sref, source_key=key, credits=payload["credits"], owner=payload["target_actor"],
                kind=source["kind"], purposes=source["purposes"], expires=source["expires_at"],
                order=source["order_id"], parent=source["id"], entry_kind=kind + "_in", actor=kw["actor"],
            )
            return {"id": identifier, "credits": payload["credits"]}

        action = "commerce_reclaim" if payload["reclaim"] else "commerce_allocate"
        return self._mutate_for_scope(scope_ref, action, payload, work, **kw)

    def allocate(self, p, payload, **kw):
        return self.allocate_scoped(make_scope_ref("project", p), payload, **kw)

    @staticmethod
    def _price_by_plan(conn, plan_id, model_id, native):
        if not isinstance(native, dict) or not native or any(type(v) is not int or v < 0 for v in native.values()):
            raise ResourceError("商业报价需要原生单位整数", "commerce_units_invalid")
        rates = conn.execute(select(S.commerce_rates).where(
            S.commerce_rates.c.plan_id == plan_id,
            S.commerce_rates.c.model_id == model_id,
        )).mappings().all()
        if not rates or any(r["unit"] not in native for r in rates):
            raise ResourceError("该模型缺少适用价格版本", "commerce_price_missing")
        return sum(native[r["unit"]] * r["credits_per_unit"] for r in rates)

    def _price(self, conn, _p, plan, model_id, native):
        return self._price_by_plan(conn, plan, model_id, native)

    def _resolve_billing_scope(self, conn, project_id, billing_scope, *, require_execute=False):
        if not isinstance(billing_scope, dict) or billing_scope.get("scope_kind") not in {"identity", "workspace", "project"}:
            raise ResourceError("需要显式指定合法资金池 billing_scope", "invalid_commerce_input")
        from vsc.assets.access_control import current_principal, denied
        principal, person, _ = self.store._access_principal(conn, current_principal())
        if require_execute and principal is not None:
            self.store._access_require(conn, project_id, "execute")
        kind = billing_scope["scope_kind"]
        if kind == "project":
            target_proj = checked_id(billing_scope.get("project_id") or project_id)
            if target_proj != project_id:
                denied("单项目额度桶仅限所属项目任务使用")
            return make_scope_ref("project", project_id)
        if kind == "identity":
            requested_ident = checked_id(billing_scope["owner_identity_id"]) if billing_scope.get("owner_identity_id") else (person["id"] if person else None)
            if not requested_ident:
                denied("个人钱包需要登录成员身份")
            if principal is not None and (not person or person["id"] != requested_ident):
                denied("只能动用本人个人钱包额度")
            return make_scope_ref("identity", requested_ident)
        ws_id = checked_id(billing_scope.get("workspace_id") or "")
        if principal is not None:
            if not person:
                denied("团队资金池需要登录成员身份")
            roles = self.store._workspace_require(conn, ws_id, "read", person["id"])
            from vsc.assets.access_control import CAPABILITIES
            caps = set().union(*(CAPABILITIES[r] for r in roles))
            bound_ws = conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id == project_id)).scalar_one_or_none()
            if bound_ws != ws_id and "manage" not in caps:
                denied("非所属工作室项目仅限工作室管理员授权扣减")
        return make_scope_ref("workspace", ws_id)

    def preview_charge(self, p, payload, *, actor=None):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, p)
            pid = project["id"]
            if "billing_scope" not in payload:
                plan = self._policy(conn, make_scope_ref("project", pid), allow_platform_fallback=False)
                if not plan:
                    return {"enabled": False, "commerce_charge": None, "revision": project["revision"]}
                operations = payload["operations"]
                if not isinstance(operations, list) or not 1 <= len(operations) <= 200:
                    raise ResourceError("商业报价需1–200个固定操作")
                bounds = {}
                for row in operations:
                    if not isinstance(row, dict) or set(row) != {"operation", "model_id", "native_units"} or row["operation"] in bounds:
                        raise ResourceError("商业操作编号或价格输入无效")
                    bounds[row["operation"]] = self._price_by_plan(conn, plan["id"], checked_id(row["model_id"]), row["native_units"])
                return {
                    "enabled": True,
                    "commerce_charge": {
                        "price_version_id": plan["id"],
                        "account_actor": payload["account_actor"],
                        "max_credits_by_operation": bounds,
                    },
                    "revision": project["revision"],
                }

            # Extended Path 3 explicit billing_scope quote
            from .budget_store import native_units, operation_key
            funding_ref = self._resolve_billing_scope(conn, pid, payload["billing_scope"])
            plan = self._policy(conn, funding_ref, allow_platform_fallback=True)
            operations = payload.get("operations")
            if not isinstance(operations, list) or not 1 <= len(operations) <= 200:
                raise ResourceError("商业报价需1–200个操作", "invalid_commerce_input")
            native_totals = {}
            bounds = {}
            for idx, row in enumerate(operations):
                if not isinstance(row, dict) or "model_id" not in row:
                    raise ResourceError("算价项缺少 model_id", "invalid_commerce_input")
                units = row.get("native_units") if isinstance(row.get("native_units"), dict) else native_units(row)
                op_key = row.get("operation") or (
                    operation_key(row, idx) if (row.get("asset_id") or row.get("shot_id")) and row.get("purpose") else f"op:{idx}"
                )
                for u, val in units.items():
                    native_totals[u] = native_totals.get(u, 0) + int(val)
                bounds[op_key] = self._price_by_plan(conn, plan["id"], checked_id(row["model_id"]), units) if plan else 0

            bound_credits = sum(bounds.values())
            overview = self.read_credit_overview(conn, funding_ref, actor, manage=(funding_ref["scope_kind"] != "project"))
            available_credits = overview["credit_balance"]
            limits = {u: v["amount"] for u, v in self.store._limits(conn, pid).items()}
            used = self.store._used(conn, pid)
            native_ok = all(
                (u not in limits) or (used.get(u, 0) + amt <= limits[u])
                for u, amt in native_totals.items()
            )
            billing_dto = {
                "scope_kind": funding_ref["scope_kind"],
                "scope_id": funding_ref["scope_id"],
                **({k: v for k, v in self._scope_cols(funding_ref).items() if k != "scope_kind" and v is not None}),
            }
            return clean({
                "project_id": pid,
                "revision": project["revision"],
                "enabled": bool(plan),
                "billing_scope": billing_dto,
                "price_version_id": plan["id"] if plan else None,
                "bound_credits": bound_credits,
                "available_credits": available_credits,
                "sufficient": bool(available_credits >= bound_credits) if plan else True,
                "native_units_required": native_totals,
                "native_budget_sufficient": native_ok,
                "amount_known": False,
                "supplier_bill_note": "账单未登记 / 报价未知",
                "commerce_charge": {
                    "price_version_id": plan["id"],
                    "account_actor": payload.get("account_actor", actor),
                    "billing_scope": billing_dto,
                    "max_credits_by_operation": bounds,
                } if plan else None,
            })

    def reserve_for_job(self, conn, project, job):
        p = project["id"]
        if conn.execute(select(S.commerce_reservations.c.id).where(
            S.commerce_reservations.c.attribution_project_id == p,
            S.commerce_reservations.c.job_id == job["id"],
        )).first():
            return
        run = self.store._one(conn, S.artifact_versions, p, job["run_version_id"])
        charge = json.loads(run["document"]).get("commerce_charge")
        explicit_scope = charge.get("billing_scope") if isinstance(charge, dict) else None
        funding_ref = (
            self._resolve_billing_scope(conn, p, explicit_scope)
            if explicit_scope is not None
            else make_scope_ref("project", p)
        )
        policy = self._policy(conn, funding_ref, allow_platform_fallback=(funding_ref["scope_kind"] != "project"))
        if not policy:
            return
        require_supported_entitlements(policy["document"])
        if not isinstance(charge, dict) or (set(charge) - {"billing_scope"}) != {"price_version_id", "account_actor", "max_credits_by_operation"}:
            raise ResourceError("已批准运行缺少固定商业承担账户与信用预算", "commerce_charge_required")
        from .budget_store import native_units, operation_key
        logical = job["request_payload"].get("logical_request", job["request_payload"])
        plan = self._plan(conn, funding_ref, charge["price_version_id"])
        require_supported_entitlements(plan["document"])
        cost = self._price_by_plan(conn, plan["id"], job["model_id"], native_units(logical))
        bound = charge["max_credits_by_operation"].get(operation_key(logical, job["candidate_no"]))
        if type(bound) is not int or bound != cost:
            raise ResourceError("商业信用预算与固定价格不一致", "commerce_quote_changed")
        active = conn.execute(select(func.count()).select_from(S.commerce_reservations).where(
            self._scope_where(S.commerce_reservations, funding_ref),
            S.commerce_reservations.c.status == "reserved",
        )).scalar_one()
        if active >= min(plan["document"]["max_concurrent_jobs"], policy["document"]["max_concurrent_jobs"]):
            raise Conflict("已到当前商业方案并发上限", "commerce_concurrency_limit")
        owner = charge["account_actor"]
        if owner is not None and (not isinstance(owner, str) or len(owner) > 200):
            raise ResourceError("商业承担账户无效")
        now = datetime.now(timezone.utc)
        owner_filter = (
            True if funding_ref["scope_kind"] == "identity"
            else or_(S.commerce_buckets.c.owner_actor == owner, S.commerce_buckets.c.owner_actor.is_(None))
            if (funding_ref["scope_kind"] == "workspace" and explicit_scope is not None)
            else S.commerce_buckets.c.owner_actor == owner
        )
        buckets = []
        for row in conn.execute(
            select(S.commerce_buckets)
            .where(
                self._scope_where(S.commerce_buckets, funding_ref),
                owner_filter,
                or_(S.commerce_buckets.c.expires_at.is_(None), S.commerce_buckets.c.expires_at > now),
            )
            .order_by(S.commerce_buckets.c.expires_at.asc().nullslast(), S.commerce_buckets.c.created_at, S.commerce_buckets.c.id)
        ).mappings():
            if job["purpose"] not in row["purposes"] and "*" not in row["purposes"]:
                continue
            if row["order_id"] and self._one_scoped(conn, S.commerce_orders, funding_ref, row["order_id"])["status"] != "paid":
                continue
            buckets.append((row, self._balance(conn, funding_ref, row["id"])))
        if sum(balance for _, balance in buckets) < cost:
            raise Conflict("指定账户可用商业信用不足（类型/用途/有效期已过滤）", "credit_insufficient")
        identifier = new_id()
        conn.execute(insert(S.commerce_reservations).values(
            **self._scope_cols(funding_ref),
            id=identifier,
            attribution_project_id=p,
            job_id=job["id"],
            price_version_id=plan["id"],
            account_actor=owner,
            attempt=job["attempt"] + 1,
            bound=cost,
            status="reserved",
        ))
        remaining = cost
        for bucket, balance in buckets:
            if balance <= 0:
                continue
            used = min(balance, remaining)
            remaining -= used
            self._entry(
                conn, funding_ref, bucket["id"], -used, "reserve",
                "job:" + job["id"] + ":" + bucket["id"], owner or funding_ref["scope_kind"],
                reservation=identifier, attribution_project_id=p, job_id=job["id"],
            )
            if remaining == 0:
                break

    def settle_for_job(self, conn, p, job):
        reservation = conn.execute(select(S.commerce_reservations).where(
            S.commerce_reservations.c.attribution_project_id == p,
            S.commerce_reservations.c.job_id == job["id"],
        )).mappings().first()
        if not reservation or reservation["status"] != "reserved":
            return 0
        scope_id = reservation["owner_identity_id"] or reservation["workspace_id"] or reservation["project_id"]
        funding_ref = make_scope_ref(reservation["scope_kind"], scope_id)
        units = conn.execute(select(S.job_budget_reservations).where(
            S.job_budget_reservations.c.project_id == p,
            S.job_budget_reservations.c.job_id == job["id"],
        )).mappings().all()
        actual = {r["unit"]: r["actual"] for r in units if r["actual"] is not None}
        if job.get("status") == "cancelled" and (not units or (len(actual) == len(units) and all(v == 0 for v in actual.values()))):
            cost = 0
        else:
            cost = (
                self._price_by_plan(conn, reservation["price_version_id"], job["model_id"], actual)
                if units and len(actual) == len(units)
                else reservation["bound"]
            )
        if cost > reservation["bound"]:
            raise Conflict("商业实际用量超过原批准边界", "commerce_actual_exceeded")
        refund = int(reservation["bound"] - cost)
        holds = conn.execute(select(S.commerce_ledger).where(
            S.commerce_ledger.c.reservation_id == reservation["id"],
            S.commerce_ledger.c.kind == "reserve",
        ).order_by(S.commerce_ledger.c.created_at, S.commerce_ledger.c.id)).mappings().all()
        released_total = 0
        for hold in holds:
            returned = min(-hold["delta"], refund)
            refund -= returned
            if returned > 0:
                self._entry(
                    conn, funding_ref, hold["bucket_id"], returned, "release",
                    "settle:" + reservation["id"] + ":" + hold["bucket_id"], "commerce-consumer",
                    reservation=reservation["id"], attribution_project_id=p, job_id=job["id"],
                )
                released_total += returned
        conn.execute(update(S.commerce_reservations).where(
            S.commerce_reservations.c.id == reservation["id"]
        ).values(actual=cost, status="released" if cost == 0 else "settled"))
        return released_total

    def request_invoice_scoped(self, scope, payload, *, gateway, **kw):
        scope_ref = self._coerce_scope(scope)

        def work(conn, sref, _rev):
            order = self._one_scoped(conn, S.commerce_orders, sref, payload["order_id"])
            billing_workspace = payload.get("workspace_id")
            if billing_workspace:
                checked_ws = checked_id(billing_workspace)
                self.store.access_workspace_guard(conn, checked_ws, "manage")
                if sref["scope_kind"] == "project":
                    actual = conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id == sref["project_id"])).scalar_one_or_none()
                    if actual != checked_ws:
                        raise ResourceError("组织发票须属于订单所在工作空间", "commerce_invoice_scope")
                elif sref["scope_kind"] == "workspace" and sref["workspace_id"] != checked_ws:
                    raise ResourceError("组织发票须属于订单所在工作空间", "commerce_invoice_scope")
                billing_workspace = checked_ws
            elif sref["scope_kind"] == "workspace":
                billing_workspace = sref["workspace_id"]
            if order["status"] != "paid" or not self._plan(conn, sref, order["plan_id"])["document"]["invoice_enabled"]:
                raise ResourceError("订单未支付或未配置发票政策", "invoice_order_ineligible")
            old = conn.execute(select(S.commerce_invoices).where(
                self._scope_where(S.commerce_invoices, sref),
                S.commerce_invoices.c.order_id == order["id"],
                S.commerce_invoices.c.status != "void",
            )).mappings().first()
            now = datetime.now(timezone.utc)
            if old:
                if old["status"] == "failed":
                    conn.execute(
                        update(S.commerce_invoices)
                        .where(S.commerce_invoices.c.id == old["id"])
                        .values(status="void", voided_at=now, void_reason="superseded_failed")
                    )
                else:
                    old_ws = old["billing_workspace_id"]
                    if (old["title"], old["tax_id"], old["email"], old_ws) != (
                        payload["title"], payload["tax_id"], payload["email"], billing_workspace
                    ):
                        raise Conflict("此订单已有发票申请，不能静默改抬头", "invoice_conflict")
                    return {"id": old["id"], "status": old["status"]}
            identifier = new_id()
            status = "created" if gateway else "unconfigured"
            conn.execute(insert(S.commerce_invoices).values(
                **self._scope_cols(sref),
                id=identifier,
                order_id=order["id"],
                billing_workspace_id=billing_workspace,
                actor=kw["actor"],
                title=payload["title"],
                tax_id=payload["tax_id"],
                email=payload["email"],
                gateway=gateway or "unconfigured",
                status=status,
            ))
            return {"id": identifier, "status": status}

        capability = "edit" if scope_ref["scope_kind"] == "project" else "manage"
        return self._mutate_for_scope(scope_ref, "commerce_request_invoice", payload, work, capability=capability, **kw)

    def request_invoice(self, p, payload, *, gateway, **kw):
        return self.request_invoice_scoped(make_scope_ref("project", p), payload, gateway=gateway, **kw)

    def invoice_scoped(self, scope, identifier, content=False):
        scope_ref = self._coerce_scope(scope)
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                rev = int(self.store._project(conn, scope_ref["project_id"])["revision"])
            else:
                rev = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
            raw_row = self._one_scoped(conn, S.commerce_invoices, scope_ref, identifier)
            document = bytes(raw_row["document"]) if (content and raw_row.get("document")) else None
            serialized = self._serialize_invoice(raw_row, include_sensitive=True, include_document=False)
            result = clean(dict(serialized, revision=rev, scope_id=scope_ref["scope_id"]))
            if content:
                result["document"] = document
            return result

    def invoice(self, p, identifier, content=False):
        return self.invoice_scoped(make_scope_ref("project", p), identifier, content=content)

    def claim_invoice(self, scope, identifier, gateway):
        scope_ref = self._coerce_scope(scope)

        def work(conn, _target):
            row = self._one_scoped(conn, S.commerce_invoices, scope_ref, identifier)
            claimed = row["status"] in {"created", "unconfigured"}
            if row["gateway"] not in {"unconfigured", gateway}:
                raise Conflict("只能用原发票服务恢复", "invoice_gateway_changed")
            if claimed:
                conn.execute(
                    update(S.commerce_invoices)
                    .where(S.commerce_invoices.c.id == row["id"])
                    .values(status="submission_unknown", gateway=gateway)
                )
            return {"id": identifier, "claimed": claimed}

        return self._internal(scope_ref, "commerce_claim_invoice", {"invoice_id": identifier, "gateway": gateway}, work)

    def invoice_result(self, scope, identifier, result):
        scope_ref = self._coerce_scope(scope)
        if result.status not in {"pending", "issued", "failed"} or not result.external_id:
            raise ResourceError("发票回执无效", "invoice_result_invalid")
        raw = result.document
        if result.status == "issued" and (not isinstance(raw, bytes) or not raw.startswith(b"%PDF-") or not 5 < len(raw) <= 10 * 1024 * 1024):
            raise ResourceError("发票服务尚未返回有效PDF文件", "invoice_document_invalid")

        def work(conn, _target):
            row = self._one_scoped(conn, S.commerce_invoices, scope_ref, identifier)
            if row["status"] == "void":
                raise Conflict("已作废发票不能再写入回执", "invoice_result_changed")
            if row["external_id"] and row["external_id"] != result.external_id:
                raise Conflict("发票编号不能替换", "invoice_result_changed")
            if row["status"] == "issued":
                if result.status != "issued" or row["sha256"] != hashlib.sha256(raw).hexdigest():
                    raise Conflict("已开具发票不能覆盖", "invoice_result_changed")
            else:
                conn.execute(
                    update(S.commerce_invoices)
                    .where(S.commerce_invoices.c.id == row["id"])
                    .values(
                        status=result.status,
                        external_id=result.external_id,
                        document=raw if result.status == "issued" else None,
                        sha256=hashlib.sha256(raw).hexdigest() if result.status == "issued" else None,
                    )
                )
            return {"id": identifier, "status": result.status}

        return self._internal(
            scope_ref, "commerce_invoice_result",
            {"invoice_id": identifier, "status": result.status, "external_id": result.external_id,
             "sha256": hashlib.sha256(raw).hexdigest() if raw else None},
            work,
        )

    def list_ledger_and_reservations(self, scope, actor, *, manage=False, cursor="", limit=50, kind="", attribution_project_id=""):
        scope_ref = self._coerce_scope(scope)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ResourceError("分页条数须在 1–200 之间", "invalid_input", 422, details={"field": "limit"})
        if kind and kind not in {"grant", "allocate_out", "allocate_in", "reclaim_out", "reclaim_in", "reserve", "release", "refund"}:
            raise ResourceError("流水类型筛选值不合法", "invalid_input", 422, details={"field": "kind"})
        attr_pid = checked_id(attribution_project_id) if attribution_project_id else None

        before_ts, before_id = None, None
        if cursor:
            try:
                padded = cursor + "=" * (-len(cursor) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
                before_ts = instant(decoded["t"])
                before_id = checked_id(decoded["i"])
            except Exception as exc:
                raise ResourceError("商业流水游标无效", "invalid_input", 422, details={"field": "cursor"}) from exc

        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                revision = int(self.store._project(conn, scope_ref["project_id"])["revision"])
            else:
                revision = self.store._scoped_revision(conn, "commerce", scope_ref["scope_kind"], scope_ref["scope_id"])
            full_visibility = bool(manage or scope_ref["scope_kind"] == "identity")
            bucket_cond = [self._scope_where(S.commerce_buckets, scope_ref)]
            if not full_visibility:
                bucket_cond.append(or_(S.commerce_buckets.c.owner_actor == actor, S.commerce_buckets.c.owner_actor.is_(None)))
            visible_bucket_ids = select(S.commerce_buckets.c.id).where(*bucket_cond)

            conds = [
                self._scope_where(S.commerce_ledger, scope_ref),
                S.commerce_ledger.c.bucket_id.in_(visible_bucket_ids),
            ]
            if kind:
                conds.append(S.commerce_ledger.c.kind == kind)
            if attr_pid:
                conds.append(S.commerce_ledger.c.attribution_project_id == attr_pid)
            if before_ts is not None and before_id is not None:
                conds.append(or_(
                    S.commerce_ledger.c.created_at < before_ts,
                    and_(S.commerce_ledger.c.created_at == before_ts, S.commerce_ledger.c.id < before_id),
                ))

            fetched = [dict(r) for r in conn.execute(
                select(S.commerce_ledger)
                .where(*conds)
                .order_by(S.commerce_ledger.c.created_at.desc(), S.commerce_ledger.c.id.desc())
                .limit(limit + 1)
            ).mappings()]
            has_more = len(fetched) > limit
            rows = fetched[:limit]
            items = self._decorate_ledger_rows(conn, scope_ref, rows, actor=actor)
            next_cursor = None
            if has_more and rows:
                last = rows[-1]
                ts_iso = last["created_at"].isoformat() if hasattr(last["created_at"], "isoformat") else str(last["created_at"])
                token_raw = json.dumps({"t": ts_iso, "i": str(last["id"])}, separators=(",", ":")).encode()
                next_cursor = base64.urlsafe_b64encode(token_raw).decode().rstrip("=")

            overview = self.read_credit_overview(conn, scope_ref, actor, manage=manage)
            return clean({
                "_etag_seed": f"ledger:{scope_ref['scope_kind']}:{scope_ref['scope_id']}:{revision}",
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "revision": revision,
                "credit_balance": overview["credit_balance"],
                "reserved_credits": overview["reserved_credits"],
                "total_consumed_credits": overview["total_consumed_credits"],
                "items": items,
                "next_cursor": next_cursor,
            })

    def export_ledger_csv(self, scope, actor, *, manage=False, kind="", attribution_project_id=""):
        all_rows = []
        cursor = ""
        for _ in range(25):
            page = self.list_ledger_and_reservations(
                scope, actor, manage=manage, cursor=cursor, limit=200,
                kind=kind, attribution_project_id=attribution_project_id,
            )
            all_rows.extend(page["items"])
            cursor = page.get("next_cursor") or ""
            if not cursor:
                break
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow([
            "id", "created_at", "funding_scope_kind", "funding_scope_label",
            "bucket_id", "kind", "delta", "actor", "attribution_project_id",
            "attribution_project_name", "job_id", "reservation_id", "supplier_bill_status",
        ])
        for row in all_rows:
            writer.writerow([
                sanitize_csv_cell(row.get("id")),
                sanitize_csv_cell(row.get("created_at")),
                sanitize_csv_cell(row.get("funding_scope_kind")),
                sanitize_csv_cell(row.get("funding_scope_label")),
                sanitize_csv_cell(row.get("bucket_id")),
                sanitize_csv_cell(row.get("kind")),
                row.get("delta", 0),
                sanitize_csv_cell(row.get("actor")),
                sanitize_csv_cell(row.get("attribution_project_id")),
                sanitize_csv_cell(row.get("attribution_project_name")),
                sanitize_csv_cell(row.get("job_id")),
                sanitize_csv_cell(row.get("reservation_id")),
                sanitize_csv_cell(row.get("supplier_bill_status")),
            ])
        return buf.getvalue().encode("utf-8")
