"""Explicit self-deactivation under the original identity and project locks."""
from datetime import datetime, timezone
from sqlalchemy import select, update, func, or_
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.assets.access_control import denied
from . import schema as S
from .values import clean, digest


class AccountLifecycleRepository:
    def __init__(self, store):
        self.store = store

    def _preview(self, conn, p, request_id):
        from .service_operations import ServiceOperationsRepository
        operations = ServiceOperationsRepository(self.store)
        person = operations._identity(conn)
        request = self.store._one(conn, S.service_requests, p, request_id)
        if request['kind'] != 'account_close' or request['requester_id'] != person['id']:
            denied('只能执行本人的账户停用申请')
        last = operations._latest(conn, p, request_id)
        if last['status'] in {'account_closed', 'withdrawn', 'rejected'}:
            raise Conflict('申请已结束，保留原处理记录', 'service_request_terminal')
        identity = person['id']
        active_ids = set(conn.execute(select(S.access_identities.c.id).where(S.access_identities.c.active.is_(True), S.access_identities.c.id != identity)).scalars())
        blockers = []
        # A sole owner must transfer responsibility through the existing member
        # controls. Empty private workspaces can stay as historical identities.
        owned = conn.execute(select(S.access_workspaces).join(S.access_workspace_members, S.access_workspace_members.c.workspace_id == S.access_workspaces.c.id).where(S.access_workspace_members.c.identity_id == identity, S.access_workspace_members.c.active.is_(True), S.access_workspace_members.c.role == 'owner')).mappings()
        for workspace in owned:
            other = set(conn.execute(select(S.access_workspace_members.c.identity_id).where(S.access_workspace_members.c.workspace_id == workspace['id'], S.access_workspace_members.c.active.is_(True), S.access_workspace_members.c.role == 'owner')).scalars()) & active_ids
            populated = conn.execute(select(S.access_projects.c.project_id).where(S.access_projects.c.workspace_id == workspace['id']).limit(1)).first()
            children = conn.execute(select(S.access_workspaces.c.id).where(S.access_workspaces.c.parent_id == workspace['id']).limit(1)).first()
            peers = conn.execute(select(S.access_workspace_members.c.identity_id).where(S.access_workspace_members.c.workspace_id == workspace['id'], S.access_workspace_members.c.identity_id.in_(active_ids), S.access_workspace_members.c.active.is_(True)).limit(1)).first()
            if not other and (populated or children or peers):
                blockers.append(dict(code='workspace_owner_required', id=workspace['id'], title=workspace['name'], message='先在账户与权限中转交工作室负责人'))
        for project in conn.execute(select(S.access_projects).join(S.access_project_members, S.access_project_members.c.project_id == S.access_projects.c.project_id).where(S.access_project_members.c.identity_id == identity, S.access_project_members.c.active.is_(True), S.access_project_members.c.role == 'owner')).mappings():
            direct = set(conn.execute(select(S.access_project_members.c.identity_id).where(S.access_project_members.c.project_id == project['project_id'], S.access_project_members.c.role == 'owner', S.access_project_members.c.active.is_(True))).scalars()) & active_ids
            inherited = any('owner' in self.store._workspace_roles(conn, project['workspace_id'], other) for other in active_ids)
            if not direct and not inherited:
                blockers.append(dict(code='project_owner_required', id=project['project_id'], message='先在账户与权限中转交项目负责人'))
        financial = [('orders', S.commerce_orders, S.commerce_orders.c.actor == person['actor'], S.commerce_orders.c.status.in_({'created','checkout_unknown','pending','refund_unknown'})),
                     ('reservations', S.commerce_reservations, S.commerce_reservations.c.account_actor == person['actor'], S.commerce_reservations.c.status == 'reserved'),
                     ('invoices', S.commerce_invoices, S.commerce_invoices.c.actor == person['actor'], S.commerce_invoices.c.status.in_({'created','unconfigured','submission_unknown','pending'}))]
        for label, table, owner, unfinished in financial:
            count = conn.execute(select(func.count()).select_from(table).where(owner, unfinished)).scalar_one()
            if count:
                blockers.append(dict(code='unsettled_'+label, count=count, message='请先处理本人的未结订单、预留额度或开票申请'))
        from .commerce import CommerceRepository
        balance = sum(max(0, CommerceRepository(self.store)._balance(conn, row['project_id'], row['id'])) for row in conn.execute(select(S.commerce_buckets).where(S.commerce_buckets.c.owner_actor == person['actor'], or_(S.commerce_buckets.c.expires_at.is_(None), S.commerce_buckets.c.expires_at > datetime.now(timezone.utc)))).mappings())
        if balance:
            blockers.append(dict(code='credit_balance_remaining', count=balance, message='本人仍有未处理额度，请先按原合同结清；停用不会抹除余额'))
        revision = conn.execute(select(S.access_state.c.revision).where(S.access_state.c.id == 1)).scalar_one()
        plan = clean(dict(identity_id=identity, actor=person['actor'], request_id=request_id, request_event_id=last['id'], access_revision=revision, blockers=blockers,
            effect='停用本地身份并撤销登录、API和本人发出的分享/邀请；作品、账务与审计历史保留，已受理任务不会被当作远端取消。'))
        return dict(plan=plan, sha256=digest(plan), ready=not blockers)

    def preview(self, p, request_id):
        from .access_control import authority_lock
        with self.store.engine.begin() as conn:
            authority_lock(conn)
            self.store._access_require(conn, p, 'read')
            return self._preview(conn, p, request_id)

    def close(self, p, payload, **kw):
        def work(conn, project):
            from .service_operations import ServiceOperationsRepository
            result = self._preview(conn, p, payload['request_id'])
            if result['sha256'] != payload['preview_sha256']:
                raise Conflict('账户关系已有变化，请重新预览停用影响', 'account_close_changed')
            plan = result['plan']
            if payload['confirm_actor'] != plan['actor']:
                denied('确认身份必须是当前本人')
            if not result['ready']:
                raise ResourceError('仍有负责人或账务关系未处理，请先查看影响清单', 'account_close_blocked', 409)
            identity = plan['identity_id']
            for table, field in [(S.access_credentials, 'identity_id'), (S.service_api_keys, 'identity_id'), (S.access_shares, 'created_by'), (S.access_invitations, 'created_by')]:
                conn.execute(update(table).where(table.c[field] == identity).values(revoked=True))
            for table in (S.access_project_members, S.access_workspace_members):
                conn.execute(update(table).where(table.c.identity_id == identity).values(active=False))
            conn.execute(update(S.access_identities).where(S.access_identities.c.id == identity).values(active=False))
            ServiceOperationsRepository(self.store)._event(conn, p, payload['request_id'], 'account_closed', '本人已确认并完成本地身份停用；保留原作品与账务审计', identity)
            self.store._access_event(conn, 'account-close:'+payload['request_id'], identity, 'account-close', digest(payload), plan['access_revision'], dict(identity_id=identity, request_id=payload['request_id'], active=False))
            return dict(id=payload['request_id'], active=False, status='account_closed')
        return self.store._mutate(p, 'service_account_close', payload, callback=work, **kw)
