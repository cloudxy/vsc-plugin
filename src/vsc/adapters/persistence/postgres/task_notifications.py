"""Notifications discover original facts; they never execute or complete a task."""
import base64
from datetime import datetime
import hashlib
import json
from urllib.parse import urlencode
from sqlalchemy import and_, cast, func, literal, or_, select, text, tuple_, Text
from sqlalchemy.dialects.postgresql import insert, UUID
from vsc.assets.access_control import denied
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import checked_id, clean, new_id
from .schema_task_notifications import ORIGINS
from .task_center import task_sources, task_sources_multi, task_origin_href

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
                batch_counts={}
                if kind=='text_batch':
                    members=S.text_tool_batch_items
                    for batch_id,state,count in conn.execute(select(members.c.batch_id,members.c.status,func.count()).where(
                        members.c.project_id==p,members.c.batch_id.in_(list(origins))).group_by(members.c.batch_id,members.c.status)):
                        batch_counts.setdefault(batch_id,{})[state]=count
                for event in selected:
                    original=origins[event['origin_id']]
                    current=event['source_token']==original['source_token']
                    item={k:event[k] for k in ('id','sequence','kind','origin_id','observed_status','created_at','unread')}
                    # Events retain only the observed state/token. Current errors
                    # and batch progress cannot be reconstructed as past facts.
                    item.update(title=original['title'],current_status=original['status'],current_error=original['error'],
                        is_current_event=current,error=original['error'] if current else None,
                        href=task_origin_href(p,original),task_created_at=original['created_at'])
                    item['task_href']='/?'+urlencode({'page':'tasks','project':p,'task_kind':kind,'task_id':event['origin_id']})
                    if kind=='text_batch' and current:
                        counts=batch_counts.get(event['origin_id'],{})
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

    def _account_scope(self, conn, project_id=None):
        from .access_control import authority_lock
        from .project_management import inactive_project_ids
        authority_lock(conn)
        principal, person, share = self.store._access_principal(conn)
        if not principal or not person or share or principal.api_key_id:
            denied('站内通知需要当前成员身份')
        access_rev = int(conn.execute(select(S.access_state.c.revision).where(S.access_state.c.id == 1)).scalar_one_or_none() or 0)
        readable_q = self.store._access_project_query(conn, 'read').where(~S.projects.c.id.in_(inactive_project_ids()))
        proj_rows = [
            dict(r)
            for r in conn.execute(
                select(S.projects.c.id, S.projects.c.name, S.projects.c.revision)
                .where(S.projects.c.id.in_(readable_q))
                .order_by(S.projects.c.id.asc())
            ).mappings()
        ]
        proj_map = {str(r['id']): r for r in proj_rows}
        if project_id:
            target_pid = checked_id(project_id)
            if target_pid not in proj_map:
                denied('无权读取该项目的站内通知')
            active_pids = [target_pid]
        else:
            active_pids = [str(r['id']) for r in proj_rows]
        return str(person['id']), access_rev, proj_map, active_pids

    def _sync_many(self, conn, sorted_pids):
        if not sorted_pids:
            return
        for pid in sorted_pids:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || :p, 0))"),
                {'p': ':task-notifications:' + pid},
            )
        table = S.task_notification_events
        for kind, query in task_sources_multi(sorted_pids):
            source = query.subquery()
            field = ORIGINS[kind][0]
            worthy = source.c.status.in_(NOTIFY_STATES)
            if kind == 'text_batch':
                members = S.text_tool_batch_items
                worthy = worthy | select(members.c.id).where(
                    members.c.project_id == source.c.project_id,
                    members.c.batch_id == source.c.id,
                    members.c.status.in_(('failed', 'blocked')),
                ).correlate(source).exists()
            values = select(
                source.c.project_id,
                func.gen_random_uuid(),
                literal(kind),
                source.c.id,
                source.c.source_token,
                source.c.status,
            ).where(worthy)
            statement = insert(table).from_select(
                ['project_id', 'id', 'kind', field, 'source_token', 'observed_status'],
                values,
            )
            conn.execute(statement.on_conflict_do_nothing(index_elements=['project_id', 'kind', 'origin_id', 'source_token']))

    @staticmethod
    def _account_cursor(value, identity, unread_only, project_filter):
        if not value:
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
            if (
                set(data) != {'identity', 'unread', 'project', 'upper_ts', 'before_ts', 'before_pid', 'before_seq'}
                or data['identity'] != identity
                or data['unread'] != unread_only
                or data['project'] != (project_filter or '')
                or type(data['before_seq']) is not int
                or data['before_seq'] <= 0
            ):
                raise ValueError()
            upper_dt = datetime.fromisoformat(data['upper_ts'])
            before_dt = datetime.fromisoformat(data['before_ts'])
            before_pid = checked_id(data['before_pid'])
            return {
                'upper_dt': upper_dt,
                'upper_ts': data['upper_ts'],
                'before_dt': before_dt,
                'before_pid': before_pid,
                'before_seq': data['before_seq'],
            }
        except (ValueError, TypeError, UnicodeError, ResourceError) as exc:
            raise ResourceError('通知分页位置不属于当前身份或筛选范围，请刷新', 'notification_cursor') from exc

    def list_account(self, *, limit=20, cursor=None, unread_only=False, project_id=None):
        with self.store.engine.begin() as conn:
            identity, access_rev, proj_map, active_pids = self._account_scope(conn, project_id=project_id)
            position = self._account_cursor(cursor, identity, unread_only, project_id)
            if not active_pids:
                etag_seed = hashlib.sha256(f"{identity}:{access_rev}:empty:{unread_only}:{limit}".encode()).hexdigest()
                return clean({
                    '_etag_seed': etag_seed,
                    'identity_id': identity,
                    'items': [],
                    'unread_count': 0,
                    'authorized_projects': [],
                    'next_cursor': None,
                })
            self._sync_many(conn, active_pids)
            events, reads = S.task_notification_events, S.task_notification_reads
            max_seqs = {
                str(r['project_id']): int(r['max_seq'])
                for r in conn.execute(
                    select(events.c.project_id, func.max(events.c.sequence).label('max_seq'))
                    .where(events.c.project_id.in_(active_pids))
                    .group_by(events.c.project_id)
                ).mappings()
            }
            unread = ~select(reads.c.id).where(
                reads.c.project_id == events.c.project_id,
                reads.c.identity_id == identity,
                reads.c.event_id == events.c.id,
            ).exists()
            unread_count = int(
                conn.scalar(
                    select(func.count()).select_from(events).where(events.c.project_id.in_(active_pids), unread)
                )
                or 0
            )
            upper_dt = (
                position['upper_dt']
                if position
                else conn.scalar(select(func.max(events.c.created_at)).where(events.c.project_id.in_(active_pids)))
            )
            query = select(events, unread.label('unread')).where(events.c.project_id.in_(active_pids))
            if upper_dt is not None:
                query = query.where(events.c.created_at <= upper_dt)
            if position:
                b_dt, b_pid, b_seq = position['before_dt'], position['before_pid'], position['before_seq']
                query = query.where(
                    or_(
                        events.c.created_at < b_dt,
                        and_(events.c.created_at == b_dt, cast(events.c.project_id, Text) > b_pid),
                        and_(
                            events.c.created_at == b_dt,
                            events.c.project_id == b_pid,
                            events.c.sequence < b_seq,
                        ),
                    )
                )
            if unread_only:
                query = query.where(unread)
            rows = [
                dict(r)
                for r in conn.execute(
                    query.order_by(
                        events.c.created_at.desc(),
                        events.c.project_id.asc(),
                        events.c.sequence.desc(),
                    ).limit(limit + 1)
                ).mappings()
            ]
            more = len(rows) > limit
            rows = rows[:limit]

            page_pids = sorted({str(r['project_id']) for r in rows})
            items_by_event_id = {}
            if page_pids:
                for kind, source_query in task_sources_multi(page_pids):
                    selected = [r for r in rows if r['kind'] == kind]
                    if not selected:
                        continue
                    source = source_query.subquery()
                    pairs = [(str(r['project_id']), str(r['origin_id'])) for r in selected]
                    origins = {
                        (str(r['project_id']), str(r['id'])): dict(r)
                        for r in conn.execute(
                            select(source).where(tuple_(source.c.project_id, source.c.id).in_(pairs))
                        ).mappings()
                    }
                    batch_counts = {}
                    if kind == 'text_batch' and origins:
                        members = S.text_tool_batch_items
                        for b_pid, batch_id, state, count in conn.execute(
                            select(members.c.project_id, members.c.batch_id, members.c.status, func.count())
                            .where(tuple_(members.c.project_id, members.c.batch_id).in_(list(origins)))
                            .group_by(members.c.project_id, members.c.batch_id, members.c.status)
                        ):
                            batch_counts.setdefault((str(b_pid), str(batch_id)), {})[state] = count
                    for event in selected:
                        pid = str(event['project_id'])
                        oid = str(event['origin_id'])
                        original = origins.get((pid, oid))
                        if not original:
                            continue
                        current = event['source_token'] == original['source_token']
                        item = {
                            k: event[k]
                            for k in ('id', 'sequence', 'kind', 'origin_id', 'observed_status', 'created_at', 'unread')
                        }
                        item.update(
                            project_id=pid,
                            project_name=proj_map[pid]['name'],
                            title=original['title'],
                            current_status=original['status'],
                            current_error=original['error'],
                            is_current_event=current,
                            error=original['error'] if current else None,
                            href=task_origin_href(pid, original),
                            task_href='/?' + urlencode({'page': 'tasks', 'project': pid, 'task_kind': kind, 'task_id': oid}),
                            task_created_at=original['created_at'],
                        )
                        if kind == 'text_batch' and current:
                            counts = batch_counts.get((pid, oid), {})
                            item['progress'] = {
                                state: counts.get(state, 0)
                                for state in ('pending', 'running', 'completed', 'failed', 'blocked', 'skipped')
                            }
                            item['progress']['total'] = sum(counts.values())
                            item['outcome'] = (
                                'stopped'
                                if original['status'] == 'stopped'
                                else 'partial'
                                if counts.get('failed') or counts.get('blocked')
                                else 'completed'
                                if original['status'] == 'completed'
                                else original['status']
                            )
                        items_by_event_id[str(event['id'])] = item

            ordered_items = [items_by_event_id[str(r['id'])] for r in rows if str(r['id']) in items_by_event_id]
            next_ = None
            if more and rows and upper_dt is not None:
                last = rows[-1]
                next_ = {
                    'identity': identity,
                    'unread': unread_only,
                    'project': project_id or '',
                    'upper_ts': position['upper_ts'] if position else upper_dt.isoformat(),
                    'before_ts': last['created_at'].isoformat(),
                    'before_pid': str(last['project_id']),
                    'before_seq': int(last['sequence']),
                }
            etag_seed = hashlib.sha256(
                json.dumps(
                    [
                        identity,
                        access_rev,
                        [f"{pid}:{proj_map[pid]['revision']}:{max_seqs.get(pid, 0)}" for pid in active_pids],
                        unread_count,
                        cursor or '',
                        unread_only,
                        limit,
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            authorized_projects = [
                {'id': pid, 'name': proj_map[pid]['name'], 'revision': int(proj_map[pid]['revision'])}
                for pid in sorted(proj_map)
            ]
            return clean({
                '_etag_seed': etag_seed,
                'identity_id': identity,
                'items': ordered_items,
                'unread_count': unread_count,
                'authorized_projects': authorized_projects,
                'next_cursor': (
                    base64.urlsafe_b64encode(json.dumps(next_, separators=(',', ':')).encode()).decode().rstrip('=')
                    if next_
                    else None
                ),
            })

    def read_account(self, payload):
        with self.store.engine.begin() as conn:
            project_filter = payload.get('project_id') if isinstance(payload, dict) else None
            identity, _access_rev, proj_map, active_pids = self._account_scope(conn, project_id=project_filter)
            events, reads = S.task_notification_events, S.task_notification_reads
            if 'items' in payload:
                raw_items = payload['items']
                if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 100:
                    raise ResourceError('一次选择 1 至 100 条通知', 'invalid_input')
                pairs = []
                seen = set()
                for entry in raw_items:
                    if not isinstance(entry, dict):
                        raise ResourceError('通知项格式无效', 'invalid_input')
                    pid = checked_id(entry.get('project_id'))
                    eid = checked_id(entry.get('event_id') or entry.get('id'))
                    if pid not in proj_map:
                        denied('通知项目不在当前可读范围')
                    if (pid, eid) not in seen:
                        seen.add((pid, eid))
                        pairs.append((pid, eid))
                found = conn.execute(
                    select(events.c.project_id, events.c.id).where(tuple_(events.c.project_id, events.c.id).in_(pairs))
                ).all()
                if len(found) != len(pairs):
                    raise ResourceError('通知不属于指定项目', 'notification_scope')
                selected = select(events.c.project_id, events.c.id).where(
                    tuple_(events.c.project_id, events.c.id).in_(pairs)
                ).subquery()
            elif payload.get('mark_all') is True or 'upper_ts' in payload:
                if not active_pids:
                    return {'identity_id': identity, 'marked_count': 0}
                q = select(events.c.project_id, events.c.id).where(events.c.project_id.in_(active_pids))
                if payload.get('upper_ts'):
                    try:
                        upper_dt = datetime.fromisoformat(payload['upper_ts'])
                    except (ValueError, TypeError) as exc:
                        raise ResourceError('已读时间上界无效', 'notification_cursor') from exc
                    q = q.where(events.c.created_at <= upper_dt)
                selected = q.subquery()
            else:
                raise ResourceError('已读操作需指定 items 或 mark_all', 'invalid_input')
            statement = insert(reads).from_select(
                ['project_id', 'id', 'identity_id', 'event_id'],
                select(
                    selected.c.project_id,
                    func.gen_random_uuid(),
                    literal(identity, type_=UUID()),
                    selected.c.id,
                ),
            )
            written = (
                statement.on_conflict_do_nothing(index_elements=['project_id', 'identity_id', 'event_id'])
                .returning(reads.c.id)
                .cte('written')
            )
            count = int(conn.scalar(select(func.count()).select_from(written)) or 0)
            return {'identity_id': identity, 'marked_count': count}
