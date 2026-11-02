"""Notifications discover original facts; they never execute or complete a task."""
import base64
import json
from urllib.parse import urlencode
from sqlalchemy import select,func,literal,cast,Text,and_,text
from sqlalchemy.dialects.postgresql import insert,UUID
from vsc.assets.access_control import denied
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id,clean,new_id
from .schema_task_notifications import ORIGINS
from .task_center import task_sources

NOTIFY_STATES=('succeeded','completed','failed','submission_unknown','needs_input','result_ready','planned','applied','rejected','stopped','cancelled','awaiting_upload','uploaded')


class TaskNotificationRepository:
    def __init__(self,store):self.store=store

    def _scope(self,conn,project_id):
        from .access_control import authority_lock
        authority_lock(conn)
        p=checked_id(project_id);self.store._project(conn,p)
        principal,person,share=self.store._access_principal(conn)
        if not principal or not person or share or principal.api_key_id:denied('站内通知需要当前成员身份')
        self.store._access_require(conn,p,'read')
        return p,person['id']

    def _sync(self,conn,p):
        # No project-revision high-water or newest-task cap: some original workers
        # finish without a project revision, and old tasks can finish arbitrarily late.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || :p,0))"),{'p':':task-notifications:'+p})
        table=S.task_notification_events
        for kind,query in task_sources(p):
            source=query.subquery();field=ORIGINS[kind][0]
            worthy=source.c.status.in_(NOTIFY_STATES)
            if kind=='text_batch':
                members=S.text_tool_batch_items
                # The original batch stays running when a member fails and blocks
                # subsequent claims. Notify that original failure without completing it.
                worthy=worthy|select(members.c.id).where(members.c.project_id==p,
                    members.c.batch_id==source.c.id,members.c.status.in_(('failed','blocked'))).exists()
            values=select(literal(p,type_=UUID()),func.gen_random_uuid(),literal(kind),source.c.id,source.c.source_token,source.c.status).where(worthy)
            statement=insert(table).from_select(['project_id','id','kind',field,'source_token','observed_status'],values)
            conn.execute(statement.on_conflict_do_nothing(index_elements=['project_id','kind','origin_id','source_token']))

    def _cursor(self,value,p,identity,unread_only):
        if value is None:return None
        try:
            data=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
            if set(data)!={'project','identity','upper','before','unread'} or data['project']!=p or data['identity']!=identity or data['unread']!=unread_only:raise ValueError()
            if type(data['upper'])is not int or type(data['before'])is not int or not 0<data['before']<=data['upper']+1:raise ValueError()
            return data
        except (ValueError,TypeError,UnicodeError):raise ResourceError('通知分页位置不属于当前身份与项目，请刷新','notification_cursor')

    def list(self,project_id,limit=20,cursor=None,unread_only=False):
        with self.store.engine.begin() as conn:
            p,identity=self._scope(conn,project_id);position=self._cursor(cursor,p,identity,unread_only)
            self._sync(conn,p)
            events,reads=S.task_notification_events,S.task_notification_reads
            upper=position['upper'] if position else conn.scalar(select(func.coalesce(func.max(events.c.sequence),0)).where(events.c.project_id==p))
            unread=~select(reads.c.id).where(reads.c.project_id==p,reads.c.identity_id==identity,reads.c.event_id==events.c.id).exists()
            unread_count=conn.scalar(select(func.count()).select_from(events).where(events.c.project_id==p,unread))
            query=select(events,unread.label('unread')).where(events.c.project_id==p,events.c.sequence<=upper)
            if position:query=query.where(events.c.sequence<position['before'])
            if unread_only:query=query.where(unread)
            rows=[dict(row) for row in conn.execute(query.order_by(events.c.sequence.desc()).limit(limit+1)).mappings()]
            more=len(rows)>limit;rows=rows[:limit];items=[]
            for kind,source_query in task_sources(p):
                selected=[r for r in rows if r['kind']==kind]
                if not selected:continue
                source=source_query.subquery()
                origins={r['id']:dict(r) for r in conn.execute(select(source).where(source.c.id.in_([r['origin_id']for r in selected]))).mappings()}
                for event in selected:
                    original=origins[event['origin_id']]
                    key='episode' if kind=='editing' else 'scope' if kind=='generation' else 'task_target'
                    params={'page':original['page'],'project':p,key:original['target_id'],'task_id':event['origin_id']}
                    if original.get('scope_id'):params['episode']=original['scope_id']
                    if original.get('tool_id'):params['tool']=original['tool_id']
                    item={k:event[k] for k in ('id','sequence','kind','origin_id','observed_status','created_at','unread')}
                    item.update(title=original['title'],current_status=original['status'],error=original['error'],href='/?'+urlencode(params),task_created_at=original['created_at'])
                    item['task_href']='/?'+urlencode({'page':'tasks','project':p,'task_kind':kind,'task_id':event['origin_id']})
                    if kind=='text_batch':
                        members=S.text_tool_batch_items
                        counts=dict(conn.execute(select(members.c.status,func.count()).where(members.c.project_id==p,members.c.batch_id==event['origin_id']).group_by(members.c.status)).all())
                        item['progress']={state:counts.get(state,0) for state in ('pending','running','completed','failed','blocked','skipped')};item['progress']['total']=sum(counts.values())
                        item['outcome']='stopped' if original['status']=='stopped' else 'partial' if counts.get('failed') or counts.get('blocked') else 'completed' if original['status']=='completed' else original['status']
                    items.append(item)
            items.sort(key=lambda row:row['sequence'],reverse=True)
            next_=dict(project=p,identity=identity,upper=upper,before=rows[-1]['sequence'],unread=unread_only) if more else None
            return clean(dict(project_id=p,identity_id=identity,items=items,unread_count=unread_count,through_sequence=upper,
                next_cursor=base64.urlsafe_b64encode(json.dumps(next_,separators=(',',':')).encode()).decode().rstrip('=') if next_ else None))

    def read(self,project_id,payload):
        with self.store.engine.begin() as conn:
            p,identity=self._scope(conn,project_id)
            events,reads=S.task_notification_events,S.task_notification_reads
            query=select(events.c.id).where(events.c.project_id==p)
            if 'ids' in payload:
                identifiers=[checked_id(value) for value in payload['ids']]
                found=conn.execute(query.where(events.c.id.in_(identifiers))).scalars().all()
                if len(found)!=len(identifiers):raise ResourceError('通知不属于当前项目','notification_scope')
                query=query.where(events.c.id.in_(identifiers))
            else:
                upper=conn.scalar(select(func.coalesce(func.max(events.c.sequence),0)).where(events.c.project_id==p))
                if payload['through_sequence']>upper:raise ResourceError('已读位置超出当前通知范围','notification_cursor')
                query=query.where(events.c.sequence<=payload['through_sequence'])
            selected=query.subquery()
            statement=insert(reads).from_select(['project_id','id','identity_id','event_id'],select(literal(p,type_=UUID()),func.gen_random_uuid(),literal(identity,type_=UUID()),selected.c.id))
            written=statement.on_conflict_do_nothing(index_elements=['project_id','identity_id','event_id']).returning(reads.c.id).cte('written')
            count=conn.scalar(select(func.count()).select_from(written))
            return dict(project_id=p,identity_id=identity,marked_count=count)
