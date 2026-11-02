"""Workspace financial views and atomic allocation through existing project ledgers."""
from datetime import datetime,timezone
from sqlalchemy import select,insert,update,or_,func
from vsc.assets.resource_service import ResourceError,Conflict
from . import schema as S
from .values import checked_id,new_id,clean


class WorkspaceCommerceRepository:
    def workspace_summary(self,p):
        snapshot=self.store.access_snapshot()
        project=next(row for row in snapshot['projects'] if row['id']==p)
        workspace=project.get('workspace_id')
        if not workspace:return {'workspace_id':None,'projects':[],'members':[],'transfers':[]}
        # Visibility follows existing grants, including parent owners. No balance copy.
        projects=[row for row in snapshot['projects'] if 'manage' in row['capabilities'] and row.get('workspace_id')]
        eligible=[]
        with self.store.engine.connect() as conn:
            for row in projects:
                try:self._transfer_workspace(conn,p,row['id'])
                except ResourceError:continue
                eligible.append(row)
            ids=[row['id'] for row in eligible]
            names={row['id']:row['name'] for row in eligible}
            transfers=conn.execute(select(S.commerce_workspace_transfers).where(
                S.commerce_workspace_transfers.c.project_id.in_(ids),S.commerce_workspace_transfers.c.target_project_id.in_(ids))
                .order_by(S.commerce_workspace_transfers.c.created_at.desc()).limit(100)).mappings()
            rows=[{**dict(row),'source_project_name':names[row['project_id']],'target_project_name':names[row['target_project_id']]} for row in transfers]
        members={row['actor']:row for row in snapshot['members'] if row['active'] and (row.get('project_id')==p or row.get('workspace_id')==workspace)}
        return clean({'workspace_id':workspace,'workspace_name':project['workspace_name'],'projects':eligible,'members':list(members.values()),'transfers':rows})

    def _transfer_workspace(self,conn,p,target):
        self.store._access_require(conn,p,'manage');self.store._access_require(conn,target,'manage')
        def chain(project):
            workspace=conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==project)).scalar_one_or_none()
            result=[]
            while workspace:
                if workspace in result:raise ResourceError('工作室关系存在循环','invalid_workspace')
                result.append(workspace)
                workspace=conn.execute(select(S.access_workspaces.c.parent_id).where(S.access_workspaces.c.id==workspace)).scalar_one()
            return result
        source=chain(p);destination=set(chain(target));common=next((row for row in source if row in destination),None)
        if not common:raise ResourceError('只能在同一工作室及其子工作室之间分配','commerce_workspace_scope')
        self.store.access_workspace_guard(conn,common,'manage')
        return common

    def transfer_workspace(self,p,payload,**kw):
        target=checked_id(payload['target_project_id'])
        if target==p:raise ResourceError('项目内分配请使用成员额度分配','commerce_workspace_scope')
        def work(conn,project):
            workspace=self._transfer_workspace(conn,p,target)
            destination=self.store._project(conn,target)
            if destination['revision']!=payload['target_revision']:raise Conflict('目标项目已更新，请重新读取分配范围','commerce_target_changed')
            from .project_management import management_transaction_guard
            management_transaction_guard(conn,target,'commerce_allocate',payload)
            source=self.store._one(conn,S.commerce_buckets,p,checked_id(payload['bucket_id']))
            now=datetime.now(timezone.utc)
            if source['expires_at'] and source['expires_at']<=now:raise Conflict('过期额度不能重新分配','credit_expired')
            if source['order_id'] and self.store._one(conn,S.commerce_orders,p,source['order_id'])['status']!='paid':raise Conflict('订单额度已冻结','credit_frozen')
            amount=payload['credits']
            if self._balance(conn,p,source['id'])<amount:raise Conflict('未用额度不足','credit_insufficient')
            identifier=new_id();key='workspace:'+identifier;reclaim=payload.get('reclaim_transfer_id')
            target_bucket=None
            if reclaim:
                original=self.store._one(conn,S.commerce_workspace_transfers,target,checked_id(reclaim))
                if original['target_project_id']!=p or original['target_bucket_id']!=source['id'] or original['reclaim_of_id']:raise ResourceError('回收须对应原分配及原目标额度桶','commerce_reclaim_scope')
                returned=conn.execute(select(func.coalesce(func.sum(S.commerce_workspace_transfers.c.credits),0)).where(S.commerce_workspace_transfers.c.reclaim_project_id==target,S.commerce_workspace_transfers.c.reclaim_of_id==reclaim)).scalar_one()
                if returned+amount>original['credits']:raise Conflict('回收超过原分配额度','commerce_reclaim_exceeded')
                target_bucket=original['source_bucket_id']
            outgoing=self._entry(conn,p,source['id'],-amount,'reclaim_out' if reclaim else 'allocate_out',key+':out',kw['actor'])
            if target_bucket:
                incoming=self._entry(conn,target,target_bucket,amount,'reclaim_in',key+':in',kw['actor'])
            else:
                target_bucket=self._bucket(conn,target,source_key=key,credits=amount,owner=None,kind=source['kind'],purposes=source['purposes'],expires=source['expires_at'],entry_kind='allocate_in',actor=kw['actor'])
                incoming=conn.execute(select(S.commerce_ledger.c.id).where(S.commerce_ledger.c.project_id==target,S.commerce_ledger.c.event_key==key+':in')).scalar_one()
            conn.execute(insert(S.commerce_workspace_transfers).values(project_id=p,id=identifier,source_bucket_id=source['id'],source_entry_id=outgoing,target_project_id=target,target_bucket_id=target_bucket,target_entry_id=incoming,workspace_id=workspace,reclaim_project_id=target if reclaim else None,reclaim_of_id=reclaim,credits=amount,actor=kw['actor']))
            revision=destination['revision']+1
            conn.execute(update(S.projects).where(S.projects.c.id==target).values(revision=revision))
            conn.execute(insert(S.project_revisions).values(project_id=target,revision=revision,actor=kw['actor'],action='commerce_workspace_receive',command_key=key))
            return {'id':identifier,'target_project_id':target,'target_bucket_id':target_bucket,'target_revision':revision,'credits':amount}
        return self.store._mutate(p,'commerce_workspace_transfer',payload,callback=work,_related_projects=(target,),**kw)
