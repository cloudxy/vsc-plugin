"""Local operations over original identities, scoped revisions and storage."""
from datetime import datetime, timedelta, timezone
import io
import json
import zipfile
from sqlalchemy import select, insert, update, func, or_, and_, cast, Text
from vsc.assets.resource_service import ResourceError, Conflict, NotFound
from vsc.assets.access_control import Principal, current_principal, set_principal, reset_principal, denied, secret_hash, CAPABILITIES
from . import schema as S
from .commerce import CommerceRepository, make_scope_ref
from .project_management import inactive_project_ids
from .values import CURRENT_REVISION, new_id, checked_id, clean, digest


class ServiceOperationsRepository:
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
    def _entity_cols_from_row(row):
        return {
            "scope_kind": row["scope_kind"],
            "owner_identity_id": row["owner_identity_id"],
            "workspace_id": row["workspace_id"],
            "project_id": row["project_id"],
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
        raise ResourceError("不支持的服务运营作用域", "invalid_scope")

    def _one_scoped(self, conn, table, scope_ref, row_id):
        row = conn.execute(select(table).where(
            self._scope_where(table, scope_ref),
            table.c.id == checked_id(row_id),
        )).mappings().first()
        if row is None:
            raise NotFound()
        return dict(row)

    def _identity(self, conn):
        principal, person, _ = self.store._access_principal(conn)
        if not principal or not person:
            denied("此操作需要现有成员身份")
        if principal.api_key_id:
            denied("API凭据不能管理账户、申请或新的凭据")
        return person

    def resolve_scope(self, scope_kind, scope_id=None, capability="read"):
        principal = current_principal()
        with self.store.engine.connect() as conn:
            person = self._identity(conn)
            is_admin = self.store._is_platform_admin(person, principal)
            if scope_kind == "project":
                p = checked_id(scope_id)
                self.store._project(conn, p)
                access = self.store._access_require(conn, p, capability)
                caps = list(access.get("capabilities", []))
                return make_scope_ref("project", p), person, ("manage" in caps), caps, is_admin
            if scope_kind == "workspace":
                ws_id = checked_id(scope_id)
                roles = self.store._workspace_require(conn, ws_id, capability, person["id"])
                caps = sorted(set().union(*(CAPABILITIES[r] for r in roles)))
                return make_scope_ref("workspace", ws_id), person, ("manage" in caps), caps, is_admin
            if scope_kind == "identity":
                if scope_id and checked_id(scope_id) != person["id"]:
                    denied("只能访问本人的个人运营中心")
                caps = ["read", "edit", "execute"]
                return make_scope_ref("identity", person["id"]), person, False, caps, is_admin
            if scope_kind == "platform":
                if capability != "read" and not is_admin:
                    denied("平台级配置与工单审核仅限平台管理员操作")
                caps = ["read", "manage"] if is_admin else ["read"]
                return make_scope_ref("platform"), person, is_admin, caps, is_admin
        raise ResourceError("不支持的服务运营作用域", "invalid_scope")

    def _mutate_for_scope(self, scope, action, payload, callback, *, capability="manage", **kw):
        scope_ref = self._coerce_scope(scope)
        if scope_ref["scope_kind"] == "project":
            return self.store._mutate(
                scope_ref["project_id"], action, payload,
                callback=lambda conn, project: callback(conn, scope_ref, int(project["revision"])),
                **kw,
            )
        return self.store._mutate_scoped(
            "service_operations", scope_ref["scope_kind"], scope_ref["scope_id"], action, payload,
            expected_revision=kw.get("expected_revision", CURRENT_REVISION),
            idempotency_key=kw.get("idempotency_key"),
            actor=kw.get("actor"),
            capability=capability,
            callback=lambda conn, state, _person: callback(conn, scope_ref, int(state["revision"])),
        )

    def _event_for_request(self, conn, request_row, status, reason, identity_id):
        sequence = conn.execute(
            select(func.coalesce(func.max(S.service_request_events.c.sequence), 0))
            .where(S.service_request_events.c.request_id == request_row["id"])
        ).scalar_one() + 1
        conn.execute(insert(S.service_request_events).values(
            **self._entity_cols_from_row(request_row),
            id=new_id(),
            request_id=request_row["id"],
            sequence=sequence,
            status=status,
            reason=reason,
            created_by=identity_id,
        ))

    def _event(self, conn, p, request_id, status, reason, identity_id):
        row = self.store._one(conn, S.service_requests, p, request_id)
        self._event_for_request(conn, row, status, reason, identity_id)

    def _latest_for_request(self, conn, request_id):
        return dict(conn.execute(
            select(S.service_request_events)
            .where(S.service_request_events.c.request_id == checked_id(request_id))
            .order_by(S.service_request_events.c.sequence.desc())
            .limit(1)
        ).mappings().one())

    def _latest(self, conn, _p, request_id):
        return self._latest_for_request(conn, request_id)

    def feedback_scoped(self, scope_kind, scope_id, *, scope, status, query, category, offset, limit):
        from vsc.assets.service_operations import FEEDBACK_STATUSES
        return self._request_page_scoped(
            scope_kind, scope_id, kinds=("feedback",), scope=scope,
            statuses=FEEDBACK_STATUSES.get(status), query=query, category=category,
            offset=offset, limit=limit,
        )

    def feedback(self, p, *, scope, status, query, category, offset, limit):
        return self.feedback_scoped("project", p, scope=scope, status=status, query=query, category=category, offset=offset, limit=limit)

    def drama_requests_scoped(self, scope_kind, scope_id, *, scope, status, query, offset, limit):
        from vsc.assets.service_operations import DRAMA_STATUSES
        return self._request_page_scoped(
            scope_kind, scope_id, kinds=("studio", "production_service"), scope=scope,
            statuses=DRAMA_STATUSES.get(status), query=query, category="",
            offset=offset, limit=limit,
        )

    def drama_requests(self, p, *, scope, status, query, offset, limit):
        return self.drama_requests_scoped("project", p, scope=scope, status=status, query=query, offset=offset, limit=limit)

    def _request_page_scoped(self, scope_kind, scope_id, *, kinds, scope, statuses, query, category, offset, limit):
        req_cap = "manage" if scope == "manage" else "read"
        scope_ref, person, manage, caps, is_admin = self.resolve_scope(scope_kind, scope_id, req_cap)
        if scope_kind == "identity" and scope == "manage":
            denied("个人视图不支持管理全量反馈，请使用平台治理入口")
        r, e = S.service_requests, S.service_request_events
        latest = (
            select(e.c.status)
            .where(e.c.request_id == r.c.id)
            .order_by(e.c.sequence.desc())
            .limit(1)
            .correlate(r)
            .scalar_subquery()
        )
        with self.store.engine.connect() as conn:
            project_name = None
            if scope_ref["scope_kind"] == "project":
                project = self.store._project(conn, scope_ref["project_id"])
                revision = int(project["revision"])
                project_name = project["name"]
                conditions = [self._scope_where(r, scope_ref), r.c.kind.in_(kinds)]
                if scope == "mine":
                    conditions.append(r.c.requester_id == person["id"])
            elif scope_ref["scope_kind"] == "workspace":
                revision = self.store._scoped_revision(conn, "service_operations", "workspace", scope_ref["workspace_id"])
                conditions = [self._scope_where(r, scope_ref), r.c.kind.in_(kinds)]
                if scope == "mine":
                    conditions.append(r.c.requester_id == person["id"])
            elif scope_ref["scope_kind"] == "identity":
                revision = self.store._scoped_revision(conn, "service_operations", "identity", scope_ref["owner_identity_id"])
                conditions = [r.c.requester_id == person["id"], r.c.kind.in_(kinds)]
            else:
                revision = self.store._scoped_revision(conn, "service_operations", "platform")
                conditions = [r.c.kind.in_(kinds)]
                if scope == "mine" or not is_admin:
                    conditions.append(r.c.requester_id == person["id"])

            if statuses:
                conditions.append(latest.in_(statuses))
            if category:
                conditions.append(r.c.feedback_category.is_(None) if category == "uncategorized" else r.c.feedback_category == category)
            if query:
                conditions.append(or_(*(cast(col, Text).icontains(query, autoescape=True) for col in (r.c.id, r.c.title, r.c.body, r.c.channel))))

            total = conn.execute(select(func.count()).select_from(r).where(*conditions)).scalar_one()
            rows = [dict(row) for row in conn.execute(
                select(r, latest.label("status"), S.access_identities.c.display_name.label("requester_name"))
                .join(S.access_identities, S.access_identities.c.id == r.c.requester_id)
                .where(*conditions)
                .order_by(r.c.created_at.desc(), r.c.id.desc())
                .offset(offset)
                .limit(limit)
            ).mappings()]
            histories = {row["id"]: [] for row in rows}
            if rows:
                for event in conn.execute(
                    select(e).where(e.c.request_id.in_(histories)).order_by(e.c.sequence)
                ).mappings():
                    histories[event["request_id"]].append(dict(event))
            for row in rows:
                row.update(events=histories[row["id"]], mine=(row["requester_id"] == person["id"]))
            result = {
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "revision": revision,
                "identity_id": person["id"],
                "actor": person["actor"],
                "manage": bool(manage),
                "platform_admin": bool(is_admin),
                "capabilities": caps,
                "scope": scope,
                "items": rows,
                "total": total,
                "offset": offset,
                "limit": limit,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            }
            if scope_ref["scope_kind"] == "project":
                result["project_id"] = scope_ref["project_id"]
                result["project_name"] = project_name
            return clean(result)

    def _recent_jobs_for_scope(self, conn, scope_ref):
        cols = (
            S.generation_jobs.c.id, S.generation_jobs.c.project_id, S.generation_jobs.c.purpose,
            S.generation_jobs.c.modality, S.generation_jobs.c.provider_id, S.generation_jobs.c.model_version,
            S.generation_jobs.c.external_task_id, S.generation_jobs.c.status, S.generation_jobs.c.shot_id,
            S.generation_jobs.c.asset_id, S.generation_jobs.c.created_at, S.generation_jobs.c.updated_at,
        )
        if scope_ref["scope_kind"] == "project":
            cond = S.generation_jobs.c.project_id == scope_ref["project_id"]
        elif scope_ref["scope_kind"] == "workspace":
            ws_projects = (
                select(S.access_projects.c.project_id)
                .where(
                    S.access_projects.c.workspace_id == scope_ref["workspace_id"],
                    S.access_projects.c.project_id.in_(self.store._access_project_query(conn, "read")),
                    ~S.access_projects.c.project_id.in_(inactive_project_ids()),
                )
            )
            cond = S.generation_jobs.c.project_id.in_(ws_projects)
        elif scope_ref["scope_kind"] == "identity":
            readable = self.store._access_project_query(conn, "read").where(~S.projects.c.id.in_(inactive_project_ids()))
            cond = S.generation_jobs.c.project_id.in_(readable)
        else:
            return []
        return [dict(r) for r in conn.execute(
            select(*cols).where(cond).order_by(S.generation_jobs.c.created_at.desc()).limit(50)
        ).mappings()]

    def snapshot_scoped(self, scope_kind, scope_id=None):
        scope_ref, person, manage, caps, is_admin = self.resolve_scope(scope_kind, scope_id, "read")
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                project = self.store._project(conn, scope_ref["project_id"])
                revision = int(project["revision"])
                config_where = self._scope_where(S.service_configuration_versions, scope_ref)
                ann_where = self._scope_where(S.service_announcements, scope_ref)
            else:
                revision = self.store._scoped_revision(conn, "service_operations", scope_ref["scope_kind"], scope_ref["scope_id"])
                if scope_ref["scope_kind"] == "workspace":
                    config_where = or_(
                        self._scope_where(S.service_configuration_versions, scope_ref),
                        S.service_configuration_versions.c.scope_kind == "platform",
                    )
                    ann_where = or_(
                        self._scope_where(S.service_announcements, scope_ref),
                        S.service_announcements.c.scope_kind == "platform",
                    )
                else:
                    config_where = S.service_configuration_versions.c.scope_kind == "platform"
                    ann_where = S.service_announcements.c.scope_kind == "platform"

            config = conn.execute(
                select(S.service_configuration_versions)
                .where(config_where)
                .order_by(
                    (S.service_configuration_versions.c.scope_kind == scope_ref["scope_kind"]).desc(),
                    S.service_configuration_versions.c.version.desc(),
                )
                .limit(1)
            ).mappings().first()

            announcements = {}
            for row in conn.execute(
                select(S.service_announcements)
                .where(ann_where)
                .order_by(
                    (S.service_announcements.c.scope_kind == scope_ref["scope_kind"]).desc(),
                    S.service_announcements.c.version.desc(),
                )
            ).mappings():
                announcements.setdefault((row["scope_kind"], row["announcement_key"]), dict(row))

            if scope_ref["scope_kind"] == "platform":
                req_cond = True if is_admin else (S.service_requests.c.requester_id == person["id"])
            elif scope_ref["scope_kind"] == "identity":
                req_cond = S.service_requests.c.requester_id == person["id"]
            else:
                req_cond = and_(
                    self._scope_where(S.service_requests, scope_ref),
                    True if manage else (S.service_requests.c.requester_id == person["id"]),
                )

            raw_requests = [dict(row) for row in conn.execute(
                select(S.service_requests)
                .where(req_cond)
                .order_by(S.service_requests.c.created_at.desc())
                .limit(100)
            ).mappings()]
            req_ids = [r["id"] for r in raw_requests]
            events_by_req = {rid: [] for rid in req_ids}
            exports_by_req = {}
            if req_ids:
                for ev in conn.execute(
                    select(S.service_request_events)
                    .where(S.service_request_events.c.request_id.in_(req_ids))
                    .order_by(S.service_request_events.c.sequence)
                ).mappings():
                    events_by_req[ev["request_id"]].append(dict(ev))
                for ex in conn.execute(
                    select(
                        S.service_export_files.c.id, S.service_export_files.c.request_id,
                        S.service_export_files.c.sha256, S.service_export_files.c.size_bytes,
                        S.service_export_files.c.expires_at,
                    ).where(S.service_export_files.c.request_id.in_(req_ids))
                ).mappings():
                    exports_by_req[ex["request_id"]] = {k: v for k, v in dict(ex).items() if k != "request_id"}

            requests = []
            for value in raw_requests:
                evs = events_by_req.get(value["id"], [])
                value["events"] = evs
                value["status"] = evs[-1]["status"] if evs else "received"
                value["mine"] = value["requester_id"] == person["id"]
                export = exports_by_req.get(value["id"])
                value["export"] = export if export and value["mine"] else None
                requests.append(value)

            if scope_ref["scope_kind"] == "platform":
                keys = []
                calls = []
                engine_overview = {
                    "credit_balance": 0, "reserved_credits": 0, "expiring_soon_credits": 0,
                    "total_consumed_credits": 0, "ledger_records": [], "recharge_orders": [],
                    "reservations": [], "recent_jobs": [], "member_usage": [],
                }
            else:
                keys = [
                    {k: v for k, v in row.items() if k != "secret_sha256"}
                    for row in conn.execute(
                        select(S.service_api_keys)
                        .where(
                            self._scope_where(S.service_api_keys, scope_ref),
                            S.service_api_keys.c.identity_id == person["id"],
                        )
                        .order_by(S.service_api_keys.c.created_at.desc())
                    ).mappings()
                ]
                key_ids = [k["id"] for k in keys]
                if key_ids:
                    call_conds = [S.service_api_calls.c.api_key_id.in_(key_ids)]
                    if scope_ref["scope_kind"] == "project":
                        call_conds.append(S.service_api_calls.c.project_id == scope_ref["project_id"])
                    calls = [dict(r) for r in conn.execute(
                        select(S.service_api_calls)
                        .where(*call_conds)
                        .order_by(S.service_api_calls.c.created_at.desc())
                        .limit(100)
                    ).mappings()]
                else:
                    calls = []

                commerce_activity = CommerceRepository(self.store).recent_activity_for_overview(
                    conn, scope_ref, person["actor"], manage=manage,
                )
                engine_overview = {
                    **commerce_activity,
                    "recent_jobs": self._recent_jobs_for_scope(conn, scope_ref),
                }

            result = {
                "_etag_seed": f"svc:{scope_ref['scope_kind']}:{scope_ref['scope_id']}:{revision}:{person['id']}",
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "revision": revision,
                "identity_id": person["id"],
                "actor": person["actor"],
                "manage": bool(manage),
                "platform_admin": bool(is_admin),
                "capabilities": caps,
                "configuration": dict(config) if config else None,
                "announcements": [
                    v for v in announcements.values()
                    if v["status"] == "published" or (manage and v["scope_kind"] == scope_ref["scope_kind"])
                ],
                "requests": requests,
                "api_keys": keys,
                "api_calls": calls,
                "engine_overview": engine_overview,
                "external_services": {
                    "distribution": "unconfigured",
                    "fcp": "unconfigured",
                    "studio": "unconfigured",
                    "production_service": "unconfigured",
                    "sms": "unconfigured",
                    "account_close": "local_deactivation_available",
                },
            }
            if scope_ref["scope_kind"] == "project":
                result["project_id"] = scope_ref["project_id"]
            return clean(result)

    def snapshot(self, p):
        return self.snapshot_scoped("project", p)

    def find_seedance_job_scoped(self, scope_kind, scope_id, raw_id, *, is_uuid=False):
        scope_ref, _, _, _, _ = self.resolve_scope(scope_kind, scope_id, "read")
        with self.store.engine.connect() as conn:
            cond = (
                (S.generation_jobs.c.id == checked_id(raw_id))
                if is_uuid
                else (func.lower(S.generation_jobs.c.external_task_id) == raw_id.lower())
            )
            if scope_ref["scope_kind"] == "project":
                proj_cond = S.generation_jobs.c.project_id == scope_ref["project_id"]
            else:
                readable = self.store._access_project_query(conn, "read").where(~S.projects.c.id.in_(inactive_project_ids()))
                proj_cond = S.generation_jobs.c.project_id.in_(readable)
            row = conn.execute(
                select(
                    S.generation_jobs.c.id, S.generation_jobs.c.project_id,
                    S.generation_jobs.c.external_task_id, S.generation_jobs.c.provider_id,
                    S.generation_jobs.c.model_version, S.generation_jobs.c.modality,
                    S.generation_jobs.c.purpose, S.generation_jobs.c.status,
                    S.generation_jobs.c.shot_id, S.generation_jobs.c.asset_id,
                    S.generation_jobs.c.created_at, S.generation_jobs.c.updated_at,
                )
                .where(proj_cond, cond)
                .order_by(S.generation_jobs.c.created_at.desc())
                .limit(1)
            ).mappings().first()
            return clean(dict(row)) if row else None

    def find_seedance_job(self, p, raw_id, *, is_uuid=False):
        return self.find_seedance_job_scoped("project", p, raw_id, is_uuid=is_uuid)

    def diagnostic_ping_scoped(self, scope_kind, scope_id=None):
        scope_ref, person, _, _, _ = self.resolve_scope(scope_kind, scope_id, "read")
        with self.store.engine.connect() as conn:
            if scope_ref["scope_kind"] == "project":
                project = self.store._project(conn, scope_ref["project_id"])
                return clean({
                    "ok": True,
                    "scope_kind": "project",
                    "scope_id": project["id"],
                    "project_id": project["id"],
                    "revision": project["revision"],
                    "database": "connected",
                    "server_time": datetime.now(timezone.utc).isoformat(),
                })
            revision = self.store._scoped_revision(conn, "service_operations", scope_ref["scope_kind"], scope_ref["scope_id"])
            return clean({
                "ok": True,
                "scope_kind": scope_ref["scope_kind"],
                "scope_id": scope_ref["scope_id"],
                "identity_id": person["id"],
                "revision": revision,
                "database": "connected",
                "server_time": datetime.now(timezone.utc).isoformat(),
            })

    def diagnostic_ping(self, p):
        return self.diagnostic_ping_scoped("project", p)

    def configure_scoped(self, scope_kind, scope_id, payload, **kw):
        if scope_kind not in {"platform", "workspace", "project"}:
            raise ResourceError("个人作用域不支持全局运营配置", "invalid_scope")
        scope_ref = make_scope_ref(scope_kind, scope_id)

        def work(conn, sref, _rev):
            person = self._identity(conn)
            old = conn.execute(
                select(S.service_configuration_versions)
                .where(self._scope_where(S.service_configuration_versions, sref))
                .order_by(S.service_configuration_versions.c.version.desc())
                .limit(1)
            ).mappings().first()
            if (old["id"] if old else None) != payload["base_version_id"]:
                raise Conflict("运营配置已有新版本", "service_configuration_conflict")
            identifier = new_id()
            conn.execute(insert(S.service_configuration_versions).values(
                **self._scope_cols(sref),
                id=identifier,
                version=old["version"] + 1 if old else 1,
                document=payload["document"],
                sha256=digest(payload["document"]),
                created_by=person["id"],
            ))
            return {"id": identifier}

        return self._mutate_for_scope(scope_ref, "service_operations_configure", payload, work, capability="manage", **kw)

    def configure(self, p, payload, **kw):
        return self.configure_scoped("project", p, payload, **kw)

    def publish_scoped(self, scope_kind, scope_id, payload, **kw):
        if scope_kind not in {"platform", "workspace", "project"}:
            raise ResourceError("个人作用域不支持发布全局公告", "invalid_scope")
        scope_ref = make_scope_ref(scope_kind, scope_id)

        def work(conn, sref, _rev):
            person = self._identity(conn)
            old = conn.execute(
                select(S.service_announcements)
                .where(
                    self._scope_where(S.service_announcements, sref),
                    S.service_announcements.c.announcement_key == payload["announcement_key"],
                )
                .order_by(S.service_announcements.c.version.desc())
                .limit(1)
            ).mappings().first()
            if (old["id"] if old else None) != payload["base_version_id"]:
                raise Conflict("公告已有新版本", "service_announcement_conflict")
            identifier = new_id()
            conn.execute(insert(S.service_announcements).values(
                **self._scope_cols(sref),
                id=identifier,
                created_by=person["id"],
                version=old["version"] + 1 if old else 1,
                **{k: v for k, v in payload.items() if k != "base_version_id"},
            ))
            return {"id": identifier}

        return self._mutate_for_scope(scope_ref, "service_announcement_publish", payload, work, capability="manage", **kw)

    def publish(self, p, payload, **kw):
        return self.publish_scoped("project", p, payload, **kw)

    def create_request_scoped(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "identity":
            scope_ref, _, _, _, _ = self.resolve_scope("identity", scope_id, "read")
        else:
            scope_ref = make_scope_ref(scope_kind, scope_id)

        def work(conn, sref, _rev):
            person = self._identity(conn)
            artifact_id = payload.get("artifact_id")
            media_id = payload.get("media_id")
            if sref["scope_kind"] == "project":
                p = sref["project_id"]
                if artifact_id:
                    self.store._one(conn, S.artifact_versions, p, checked_id(artifact_id))
                if media_id:
                    self.store._one(conn, S.media_items, p, checked_id(media_id))
                if payload["kind"] == "distribution":
                    if not artifact_id:
                        raise ResourceError("分发申请需要固定内容版本", "distribution_version_required")
                    if not self.store._artifact_approved(conn, p, artifact_id):
                        raise ResourceError("分发申请须绑定已批准版本", "distribution_unapproved")
            else:
                if artifact_id or media_id:
                    raise ResourceError("非项目级工单不能直接附带项目版本或媒体附件", "invalid_service_operations")
                if payload["kind"] == "distribution":
                    raise ResourceError("内容分发申请须在具体项目内发起", "distribution_version_required")
            identifier = new_id()
            values = {
                "kind": payload["kind"],
                "title": payload["title"],
                "body": payload["body"],
                "contact": payload.get("contact") or "",
                "channel": payload.get("channel") or "",
                "artifact_id": artifact_id,
                "media_id": media_id,
                "requested_fields": payload.get("requested_fields", []),
            }
            if "feedback_category" in payload:
                values["feedback_category"] = payload["feedback_category"]
            row_values = {
                **self._scope_cols(sref),
                "id": identifier,
                "requester_id": person["id"],
                **values,
            }
            conn.execute(insert(S.service_requests).values(**row_values))
            status = "awaiting_configuration" if payload["kind"] in {"fcp", "studio", "production_service", "distribution"} else "received"
            self._event_for_request(conn, row_values, status, "已保存本地申请；没有向外部服务发送", person["id"])
            return {"id": identifier, "status": status}

        capability = "read" if scope_kind in {"project", "identity"} else "manage"
        return self._mutate_for_scope(scope_ref, "service_request_create", payload, work, capability=capability, **kw)

    def create_request(self, p, payload, **kw):
        return self.create_request_scoped("project", p, payload, **kw)

    def transition_scoped(self, scope_kind, scope_id, payload, withdraw=False, **kw):
        if scope_kind == "identity":
            scope_ref, _, _, _, _ = self.resolve_scope("identity", scope_id, "read")
        elif scope_kind == "platform":
            scope_ref = make_scope_ref("platform")
        else:
            scope_ref = make_scope_ref(scope_kind, scope_id)

        def work(conn, sref, _rev):
            person = self._identity(conn)
            req_id = checked_id(payload["request_id"])
            if sref["scope_kind"] == "platform":
                row = conn.execute(select(S.service_requests).where(S.service_requests.c.id == req_id)).mappings().first()
                if row is None:
                    raise NotFound()
                row = dict(row)
            elif sref["scope_kind"] == "identity" and withdraw:
                row = conn.execute(select(S.service_requests).where(
                    S.service_requests.c.id == req_id,
                    S.service_requests.c.requester_id == person["id"],
                )).mappings().first()
                if row is None:
                    denied("只能撤回本人的申请")
                row = dict(row)
            else:
                row = self._one_scoped(conn, S.service_requests, sref, req_id)
            last = self._latest_for_request(conn, row["id"])
            if last["id"] != payload["base_event_id"]:
                raise Conflict("申请已有新处理记录，请先读取", "service_request_conflict")
            if withdraw and row["requester_id"] != person["id"]:
                denied("只能撤回本人的申请")
            status = "withdrawn" if withdraw else payload["status"]
            if last["status"] in {"withdrawn", "export_ready", "rejected", "account_closed"}:
                raise Conflict("申请已结束，保留原处理记录", "service_request_terminal")
            if row["kind"] == "personal_export" and not withdraw:
                raise ResourceError("个人导出只由本人实际生成文件完成", "export_owner_required")
            self._event_for_request(conn, row, status, payload["reason"], person["id"])
            return {"id": row["id"], "status": status}

        action = "service_request_withdraw" if withdraw else "service_request_process"
        capability = "read" if withdraw else "manage"
        return self._mutate_for_scope(scope_ref, action, payload, work, capability=capability, **kw)

    def transition(self, p, payload, withdraw=False, **kw):
        return self.transition_scoped("project", p, payload, withdraw=withdraw, **kw)

    def issue_key_scoped(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "identity":
            scope_ref, _, _, _, _ = self.resolve_scope("identity", scope_id, "read")
        elif scope_kind in {"workspace", "project"}:
            scope_ref = make_scope_ref(scope_kind, scope_id)
        else:
            raise ResourceError("平台目录不支持直接签发开放接口密钥", "invalid_scope")

        def work(conn, sref, _rev):
            person = self._identity(conn)
            if sref["scope_kind"] == "project":
                p = sref["project_id"]
                if not conn.execute(select(S.access_projects.c.project_id).where(S.access_projects.c.project_id == p)).first():
                    raise ResourceError("请先将项目归属到个人空间或工作室，再发放范围凭据", "api_project_unassigned")
                for cap in payload["capabilities"]:
                    self.store._access_require(conn, p, cap)
            elif sref["scope_kind"] == "workspace":
                for cap in payload["capabilities"]:
                    self.store._workspace_require(conn, sref["workspace_id"], cap, person["id"])
            dup = conn.execute(
                select(S.service_api_keys.c.id).where(
                    self._scope_where(S.service_api_keys, sref),
                    S.service_api_keys.c.identity_id == person["id"],
                    S.service_api_keys.c.revoked.is_(False),
                    func.lower(func.btrim(S.service_api_keys.c.name)) == payload["name"].strip().lower(),
                )
            ).first()
            if dup:
                raise Conflict("当前范围内已存在同名有效 API 凭据", "api_key_name_conflict")
            identifier = new_id()
            conn.execute(insert(S.service_api_keys).values(
                **self._scope_cols(sref),
                id=identifier,
                identity_id=person["id"],
                name=payload["name"],
                secret_sha256=secret_hash(payload["secret"]),
                prefix=payload["secret"][:8],
                capabilities=payload["capabilities"],
                expires_at=payload["expires_at"],
                ip_allowlist=payload["ip_allowlist"],
                requests_per_minute=payload["requests_per_minute"],
            ))
            return {"id": identifier, "prefix": payload["secret"][:8], "secret_returned": False}

        values = {k: v for k, v in payload.items() if k != "secret"}
        values["secret_sha256"] = secret_hash(payload["secret"])
        capability = "read" if scope_kind in {"project", "identity"} else "manage"
        return self._mutate_for_scope(scope_ref, "service_api_key_issue", values, work, capability=capability, **kw)

    def issue_key(self, p, payload, **kw):
        return self.issue_key_scoped("project", p, payload, **kw)

    def revoke_key_scoped(self, scope_kind, scope_id, payload, **kw):
        if scope_kind == "identity":
            scope_ref, _, _, _, _ = self.resolve_scope("identity", scope_id, "read")
        elif scope_kind in {"workspace", "project"}:
            scope_ref = make_scope_ref(scope_kind, scope_id)
        else:
            raise ResourceError("不支持的密钥作用域", "invalid_scope")

        def work(conn, sref, _rev):
            person = self._identity(conn)
            key = self._one_scoped(conn, S.service_api_keys, sref, payload["key_id"])
            if key["identity_id"] != person["id"]:
                denied("只能撤销本人API凭据")
            conn.execute(
                update(S.service_api_keys)
                .where(self._scope_where(S.service_api_keys, sref), S.service_api_keys.c.id == key["id"])
                .values(revoked=True)
            )
            return {"id": key["id"], "revoked": True}

        capability = "read" if scope_kind in {"project", "identity"} else "manage"
        return self._mutate_for_scope(scope_ref, "service_api_key_revoke", payload, work, capability=capability, **kw)

    def revoke_key(self, p, payload, **kw):
        return self.revoke_key_scoped("project", p, payload, **kw)

    def validate_api_key(self, conn, principal, project_id=None, capability=None):
        key = conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.id == checked_id(principal.api_key_id))).mappings().first()
        if not key or key["revoked"] or key["expires_at"] <= datetime.now(timezone.utc) or key["identity_id"] != principal.identity_id:
            denied("API凭据已撤销、过期或身份不符")
        if project_id is not None:
            if key["scope_kind"] == "project" and key["project_id"] != project_id:
                denied("API凭据不属于此项目")
            elif key["scope_kind"] == "workspace":
                bound_ws = conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id == project_id)).scalar_one_or_none()
                if not bound_ws:
                    denied("API凭据不属于未绑定工作室的项目")
                cursor = bound_ws
                matched = False
                visited = set()
                while cursor and cursor not in visited:
                    if cursor == key["workspace_id"]:
                        matched = True
                        break
                    visited.add(cursor)
                    cursor = conn.execute(select(S.access_workspaces.c.parent_id).where(S.access_workspaces.c.id == cursor)).scalar_one_or_none()
                if not matched:
                    denied("API凭据不属于此项目所在工作室")
        if capability is not None and capability not in key["capabilities"]:
            denied("API凭据未授予此能力")
        return dict(key)

    def authenticate_api_key(self, secret):
        hashed = secret_hash(secret)
        with self.store.engine.connect() as conn:
            key = conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.secret_sha256 == hashed)).mappings().first()
            if not key:
                denied("API凭据无效")
            person = self.store._access_identity(conn, key["identity_id"])
            principal = Principal(identity_id=person["id"], actor=person["actor"], api_key_id=key["id"])
            self.validate_api_key(conn, principal)
            if key["scope_kind"] == "project":
                token = set_principal(principal)
                try:
                    self.store._access_require(conn, key["project_id"], "read")
                finally:
                    reset_principal(token)
            elif key["scope_kind"] == "workspace":
                self.store._workspace_require(conn, key["workspace_id"], "read", person["id"])
            return principal

    def call_event(self, p, call_id, operation, phase, status_code, error_code=None, run_id=None, job_ids=(), client_ip=None):
        principal = current_principal()
        if not principal or not principal.api_key_id:
            denied("开放接口需要专用API凭据")
        failure = None
        proj_scope = self._scope_cols(make_scope_ref("project", p))
        with self.store.engine.begin() as conn:
            if phase == "started":
                from .access_control import authority_lock
                authority_lock(conn)
                self.store._access_require(conn, p, "read")
                key = conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.id == principal.api_key_id).with_for_update()).mappings().one()
                import ipaddress
                if key["ip_allowlist"]:
                    try:
                        allowed = any(ipaddress.ip_address(client_ip) in ipaddress.ip_network(n) for n in key["ip_allowlist"])
                    except (ValueError, TypeError):
                        allowed = False
                    if not allowed:
                        failure = ("来源IP不在此凭据白名单内", "api_ip_denied", 403)
                if not failure and key["requests_per_minute"]:
                    count = conn.execute(
                        select(func.count()).select_from(S.service_api_calls).where(
                            S.service_api_calls.c.api_key_id == key["id"],
                            S.service_api_calls.c.phase == "started",
                            S.service_api_calls.c.status_code == 0,
                            S.service_api_calls.c.created_at > datetime.now(timezone.utc) - timedelta(minutes=1),
                        )
                    ).scalar_one()
                    if count >= key["requests_per_minute"]:
                        failure = ("此凭据已达到每分钟调用上限，请稍后查询原任务", "api_rate_limited", 429)
                if failure:
                    status_code = failure[2]
                    error_code = failure[1]
            elif not conn.execute(
                select(S.service_api_calls.c.id).where(
                    S.service_api_calls.c.project_id == p,
                    S.service_api_calls.c.api_key_id == principal.api_key_id,
                    S.service_api_calls.c.call_id == call_id,
                    S.service_api_calls.c.phase == "started",
                )
            ).first():
                denied("调用记录缺少起点")
            identifier = new_id()
            conn.execute(insert(S.service_api_calls).values(
                **proj_scope,
                id=identifier,
                api_key_id=principal.api_key_id,
                call_id=call_id,
                phase=phase,
                operation=operation,
                status_code=status_code,
                error_code=error_code,
                run_version_id=run_id,
            ))
            for job_id in set(job_ids):
                conn.execute(insert(S.service_api_call_jobs).values(
                    project_id=p, id=new_id(), call_event_id=identifier, job_id=job_id,
                ))
            if failure:
                conn.execute(insert(S.service_api_calls).values(
                    **proj_scope,
                    id=new_id(),
                    api_key_id=principal.api_key_id,
                    call_id=call_id,
                    phase="finished",
                    operation=operation,
                    status_code=failure[2],
                    error_code=failure[1],
                ))
        if failure:
            raise ResourceError(*failure)

    def build_export_scoped(self, scope_kind, scope_id, payload, storage, **kw):
        if scope_kind == "identity":
            scope_ref, _, _, _, _ = self.resolve_scope("identity", scope_id, "read")
        else:
            scope_ref = make_scope_ref(scope_kind, scope_id)

        def work(conn, sref, current_rev):
            person = self._identity(conn)
            row = self._one_scoped(conn, S.service_requests, sref, payload["request_id"])
            if row["requester_id"] != person["id"] or row["kind"] != "personal_export":
                denied("只可导出本人申请的个人信息")
            last = self._latest_for_request(conn, row["id"])
            if last["status"] == "export_ready":
                old = conn.execute(
                    select(S.service_export_files).where(
                        self._scope_where(S.service_export_files, sref),
                        S.service_export_files.c.request_id == row["id"],
                    )
                ).mappings().one()
                return {"id": old["id"], "request_id": row["id"], "status": "export_ready"}
            if last["status"] in {"withdrawn", "rejected"}:
                raise Conflict("申请已结束", "service_request_terminal")
            fields = row["requested_fields"]
            snapshot = {
                "format": "vsc.personal-data/v1",
                "scope_kind": sref["scope_kind"],
                "scope_id": sref["scope_id"],
                "snapshot_revision": current_rev,
                "identity_id": person["id"],
                "requested_fields": fields,
            }
            if sref["scope_kind"] == "project":
                snapshot["project_id"] = sref["project_id"]
                snapshot["project_revision"] = current_rev
            if "profile" in fields:
                snapshot["profile"] = {k: person[k] for k in ("id", "actor", "display_name", "active", "created_at")}
            if "memberships" in fields:
                if sref["scope_kind"] == "project":
                    access = self.store._access_require(conn, sref["project_id"], "read")
                    snapshot["project_access"] = {
                        k: access.get(k) for k in ("project_id", "workspace_id", "current_identity_id", "effective_role", "capabilities")
                    }
                else:
                    ws_memberships = [dict(r) for r in conn.execute(
                        select(S.access_workspace_members.c.workspace_id, S.access_workspace_members.c.role, S.access_workspaces.c.name, S.access_workspaces.c.kind)
                        .join(S.access_workspaces, S.access_workspaces.c.id == S.access_workspace_members.c.workspace_id)
                        .where(S.access_workspace_members.c.identity_id == person["id"], S.access_workspace_members.c.active.is_(True))
                    ).mappings()]
                    proj_memberships = [dict(r) for r in conn.execute(
                        select(S.access_project_members.c.project_id, S.access_project_members.c.role)
                        .where(S.access_project_members.c.identity_id == person["id"], S.access_project_members.c.active.is_(True))
                    ).mappings()]
                    snapshot["memberships"] = {"workspaces": ws_memberships, "projects": proj_memberships}
            if "requests" in fields:
                req_where = (
                    and_(S.service_requests.c.project_id == sref["project_id"], S.service_requests.c.requester_id == person["id"])
                    if sref["scope_kind"] == "project"
                    else (S.service_requests.c.requester_id == person["id"])
                )
                snapshot["requests"] = [dict(r) for r in conn.execute(select(S.service_requests).where(req_where)).mappings()]
            if "orders" in fields:
                ord_where = (
                    and_(S.commerce_orders.c.project_id == sref["project_id"], S.commerce_orders.c.actor == person["actor"])
                    if sref["scope_kind"] == "project"
                    else or_(
                        and_(S.commerce_orders.c.scope_kind == "identity", S.commerce_orders.c.owner_identity_id == person["id"]),
                        S.commerce_orders.c.actor == person["actor"],
                    )
                )
                snapshot["orders"] = [
                    {k: r[k] for k in ("id", "scope_kind", "plan_id", "status", "amount_minor", "currency", "credits", "created_at", "paid_at")}
                    for r in conn.execute(select(S.commerce_orders).where(ord_where)).mappings()
                ]
            snapshot = clean(snapshot)
            raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2).encode()
            if len(raw) > 10 * 1024 * 1024:
                raise ResourceError("本地导出超过10MB，请缩小字段范围", "export_too_large")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("personal-data.json", raw)
                archive.writestr("README.txt", "本人在所选范围内的固定信息快照。此文件不是账户注销或外部服务完成证明。")
            stream.seek(0)
            staged = storage.stage_upload(stream, "personal-data.zip")
            blob = storage.commit_upload(staged["staged_upload"])
            identifier = new_id()
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            conn.execute(insert(S.service_export_files).values(
                **self._scope_cols(sref),
                id=identifier,
                request_id=row["id"],
                requester_id=person["id"],
                snapshot_revision=current_rev,
                snapshot=snapshot,
                snapshot_sha256=digest(snapshot),
                object_key=blob["object_key"],
                sha256=blob["sha256"],
                size_bytes=blob["size_bytes"],
                expires_at=expires_at,
            ))
            self._event_for_request(conn, row, "export_ready", "本地文件已生成，下载时再次核对身份与权限", person["id"])
            return {"id": identifier, "request_id": row["id"], "status": "export_ready", "expires_at": expires_at}

        capability = "read" if scope_kind in {"project", "identity"} else "manage"
        return self._mutate_for_scope(scope_ref, "service_export_build", payload, work, capability=capability, **kw)

    def build_export(self, p, payload, storage, **kw):
        return self.build_export_scoped("project", p, payload, storage, **kw)

    def export_file_scoped(self, scope_kind, scope_id, identifier):
        scope_ref, _, _, _, _ = self.resolve_scope(scope_kind, scope_id, "read")
        with self.store.engine.connect() as conn:
            person = self._identity(conn)
            if scope_ref["scope_kind"] == "identity":
                row = conn.execute(select(S.service_export_files).where(
                    S.service_export_files.c.id == checked_id(identifier),
                    S.service_export_files.c.requester_id == person["id"],
                )).mappings().first()
                if row is None:
                    raise NotFound()
                row = dict(row)
            else:
                row = self._one_scoped(conn, S.service_export_files, scope_ref, identifier)
            if row["requester_id"] != person["id"]:
                denied("此文件属于其他身份")
            if row["expires_at"] <= datetime.now(timezone.utc):
                raise ResourceError("导出包已超过24小时有效期，请重新生成", "export_expired", 410)
            return row

    def export_file(self, p, identifier):
        return self.export_file_scoped("project", p, identifier)

    def cancel_job(self, p, payload, **kw):
        def work(conn, project):
            job = self.store._one(conn, S.generation_jobs, p, payload["job_id"])
            if job["status"] != "created" or job["claim_owner"]:
                raise Conflict("只可取消尚未由工作者领取的本地待执行任务；远端任务需原恢复流程", "api_cancel_unavailable")
            return self.store._update_generation_job(p, {"job_id": job["id"], "status": "cancelled"}, _transaction=(conn, project), **kw)

        return self.store._mutate(p, "service_api_cancel", payload, callback=work, **kw)
