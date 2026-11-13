"""Local operations over original identities, project revisions and storage."""
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
import hashlib,io,json,zipfile
from sqlalchemy import select,insert,update,func,or_
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.assets.access_control import Principal,current_principal,set_principal,reset_principal,denied,secret_hash
from . import schema as S
from .values import new_id,checked_id,clean,digest


class ServiceOperationsRepository:
    def __init__(self,store):self.store=store

    def _identity(self,conn):
        principal,person,_=self.store._access_principal(conn)
        if not principal or not person:denied('此操作需要现有成员身份')
        if principal.api_key_id:denied('API凭据不能管理账户、申请或新的凭据')
        return person

    def _event(self,conn,p,request_id,status,reason,identity_id):
        sequence=conn.execute(select(func.coalesce(func.max(S.service_request_events.c.sequence),0)).where(S.service_request_events.c.project_id==p,S.service_request_events.c.request_id==request_id)).scalar_one()+1
        conn.execute(insert(S.service_request_events).values(project_id=p,id=new_id(),request_id=request_id,sequence=sequence,status=status,reason=reason,created_by=identity_id))

    def _latest(self,conn,p,request_id):
        return dict(conn.execute(select(S.service_request_events).where(S.service_request_events.c.project_id==p,S.service_request_events.c.request_id==request_id).order_by(S.service_request_events.c.sequence.desc()).limit(1)).mappings().one())

    def feedback(self,p,*,scope,status,query,category,offset,limit):
        from vsc.assets.service_operations import FEEDBACK_STATUSES
        r,e=S.service_requests,S.service_request_events
        latest=select(e.c.status).where(e.c.project_id==r.c.project_id,e.c.request_id==r.c.id).order_by(e.c.sequence.desc()).limit(1).correlate(r).scalar_subquery()
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);person=self._identity(conn)
            access=self.store._access_require(conn,p,'manage' if scope=='manage' else 'read')
            conditions=[r.c.project_id==p,r.c.kind=='feedback']
            if scope=='mine':conditions.append(r.c.requester_id==person['id'])
            if status!='all':conditions.append(latest.in_(FEEDBACK_STATUSES[status]))
            if category:conditions.append(r.c.feedback_category.is_(None) if category=='uncategorized' else r.c.feedback_category==category)
            if query:
                # contains(autoescape) treats user-entered % and _ literally.
                from sqlalchemy import cast,Text
                conditions.append(or_(*(cast(col,Text).icontains(query,autoescape=True) for col in (r.c.id,r.c.title,r.c.body,r.c.channel))))
            total=conn.execute(select(func.count()).select_from(r).where(*conditions)).scalar_one()
            rows=[dict(row) for row in conn.execute(select(r,latest.label('status'),S.access_identities.c.display_name.label('requester_name'))
                .join(S.access_identities,S.access_identities.c.id==r.c.requester_id).where(*conditions)
                .order_by(r.c.created_at.desc(),r.c.id.desc()).offset(offset).limit(limit)).mappings()]
            histories={row['id']:[] for row in rows}
            if rows:
                for event in conn.execute(select(e).where(e.c.project_id==p,e.c.request_id.in_(histories)).order_by(e.c.sequence)).mappings():
                    histories[event['request_id']].append(dict(event))
            for row in rows:
                row.update(events=histories[row['id']],mine=row['requester_id']==person['id'])
            return clean(dict(project_id=p,revision=project['revision'],identity_id=person['id'],actor=person['actor'],
                manage='manage' in access['capabilities'],capabilities=access['capabilities'],scope=scope,
                items=rows,total=total,offset=offset,limit=limit,next_offset=offset+len(rows) if offset+len(rows)<total else None))

    def snapshot(self,p):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);person=self._identity(conn);scope=self.store._access_require(conn,p,'read');manage='manage' in scope.get('capabilities',[])
            config=conn.execute(select(S.service_configuration_versions).where(S.service_configuration_versions.c.project_id==p).order_by(S.service_configuration_versions.c.version.desc()).limit(1)).mappings().first()
            announcements={}
            for row in conn.execute(select(S.service_announcements).where(S.service_announcements.c.project_id==p).order_by(S.service_announcements.c.version.desc())).mappings():announcements.setdefault(row['announcement_key'],dict(row))
            requests=[]
            for row in conn.execute(select(S.service_requests).where(S.service_requests.c.project_id==p,True if manage else S.service_requests.c.requester_id==person['id']).order_by(S.service_requests.c.created_at.desc()).limit(100)).mappings():
                value=dict(row);value['events']=[dict(e) for e in conn.execute(select(S.service_request_events).where(S.service_request_events.c.project_id==p,S.service_request_events.c.request_id==row['id']).order_by(S.service_request_events.c.sequence)).mappings()]
                value['status']=value['events'][-1]['status'];value['mine']=row['requester_id']==person['id']
                export=conn.execute(select(S.service_export_files.c.id,S.service_export_files.c.sha256,S.service_export_files.c.size_bytes,S.service_export_files.c.expires_at).where(S.service_export_files.c.project_id==p,S.service_export_files.c.request_id==row['id'])).mappings().first()
                value['export']=dict(export) if export and value['mine'] else None;requests.append(value)
            keys=[{k:v for k,v in row.items() if k!='secret_sha256'} for row in conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.project_id==p,S.service_api_keys.c.identity_id==person['id']).order_by(S.service_api_keys.c.created_at.desc())).mappings()]
            calls=[dict(r) for r in conn.execute(select(S.service_api_calls).where(S.service_api_calls.c.project_id==p,S.service_api_calls.c.api_key_id.in_([k['id'] for k in keys])).order_by(S.service_api_calls.c.created_at.desc()).limit(100)).mappings()]
            now=datetime.now(timezone.utc)
            bucket_rows=conn.execute(select(S.commerce_buckets).where(
                S.commerce_buckets.c.project_id==p,
                True if manage else or_(S.commerce_buckets.c.owner_actor==person['actor'],S.commerce_buckets.c.owner_actor.is_(None)),
            )).mappings().all()
            available_credits=0
            bucket_ids=[]
            for b in bucket_rows:
                bucket_ids.append(b['id'])
                if b['expires_at'] and b['expires_at']<=now:continue
                if b['order_id']:
                    ord_row=conn.execute(select(S.commerce_orders.c.status).where(S.commerce_orders.c.project_id==p,S.commerce_orders.c.id==b['order_id'])).scalar_one_or_none()
                    if ord_row in {'refund_unknown','refunded'}:continue
                bal=conn.execute(select(func.coalesce(func.sum(S.commerce_ledger.c.delta),0)).where(S.commerce_ledger.c.project_id==p,S.commerce_ledger.c.bucket_id==b['id'])).scalar_one()
                available_credits+=int(bal or 0)
            ledger_rows=[dict(r) for r in conn.execute(select(S.commerce_ledger).where(
                S.commerce_ledger.c.project_id==p,
                S.commerce_ledger.c.bucket_id.in_(bucket_ids) if bucket_ids else False,
            ).order_by(S.commerce_ledger.c.created_at.desc()).limit(60)).mappings()] if bucket_ids else []
            recharge_orders=[{k:r[k] for k in ('id','plan_id','status','amount_minor','currency','credits','created_at','paid_at')} for r in conn.execute(select(S.commerce_orders).where(
                S.commerce_orders.c.project_id==p,
                True if manage else S.commerce_orders.c.actor==person['actor'],
            ).order_by(S.commerce_orders.c.created_at.desc()).limit(50)).mappings()]
            reservations=[dict(r) for r in conn.execute(select(S.commerce_reservations).where(
                S.commerce_reservations.c.project_id==p,
                True if manage else S.commerce_reservations.c.account_actor==person['actor'],
            ).order_by(S.commerce_reservations.c.created_at.desc()).limit(60)).mappings()]
            total_consumed=sum(int(r['actual'] if r['actual'] is not None else r['bound']) for r in reservations if r['status'] in {'reserved','settled'})
            recent_jobs=[dict(r) for r in conn.execute(select(
                S.generation_jobs.c.id,S.generation_jobs.c.purpose,S.generation_jobs.c.modality,
                S.generation_jobs.c.provider_id,S.generation_jobs.c.model_version,S.generation_jobs.c.external_task_id,
                S.generation_jobs.c.status,S.generation_jobs.c.shot_id,S.generation_jobs.c.asset_id,
                S.generation_jobs.c.created_at,S.generation_jobs.c.updated_at,
            ).where(S.generation_jobs.c.project_id==p).order_by(S.generation_jobs.c.created_at.desc()).limit(50)).mappings()]
            member_usage=[]
            if manage:
                grouped={}
                for r in reservations:
                    owner=r['account_actor'] or '项目公共池'
                    entry=grouped.setdefault(owner,{'actor':owner,'reservation_count':0,'credits_used':0})
                    entry['reservation_count']+=1
                    if r['status'] in {'reserved','settled'}:
                        entry['credits_used']+=int(r['actual'] if r['actual'] is not None else r['bound'])
                member_usage=sorted(grouped.values(),key=lambda x:(-x['credits_used'],x['actor']))
            engine_overview=dict(
                credit_balance=available_credits,
                total_consumed_credits=total_consumed,
                ledger_records=ledger_rows,
                recharge_orders=recharge_orders,
                reservations=reservations,
                recent_jobs=recent_jobs,
                member_usage=member_usage,
            )
            return clean(dict(project_id=p,revision=project['revision'],identity_id=person['id'],actor=person['actor'],manage=manage,capabilities=scope['capabilities'],configuration=dict(config) if config else None,announcements=[v for v in announcements.values() if v['status']=='published' or manage],requests=requests,api_keys=keys,api_calls=calls,engine_overview=engine_overview,external_services={'distribution':'unconfigured','fcp':'unconfigured','studio':'unconfigured','production_service':'unconfigured','sms':'unconfigured','account_close':'local_deactivation_available'}))

    def find_seedance_job(self,p,raw_id,*,is_uuid=False):
        with self.store.engine.connect() as conn:
            self.store._project(conn,p);self.store._access_require(conn,p,'read')
            cond=(S.generation_jobs.c.id==checked_id(raw_id)) if is_uuid else (func.lower(S.generation_jobs.c.external_task_id)==raw_id.lower())
            row=conn.execute(select(
                S.generation_jobs.c.id,S.generation_jobs.c.external_task_id,S.generation_jobs.c.provider_id,
                S.generation_jobs.c.model_version,S.generation_jobs.c.modality,S.generation_jobs.c.purpose,
                S.generation_jobs.c.status,S.generation_jobs.c.shot_id,S.generation_jobs.c.asset_id,
                S.generation_jobs.c.created_at,S.generation_jobs.c.updated_at,
            ).where(S.generation_jobs.c.project_id==p,cond).order_by(S.generation_jobs.c.created_at.desc()).limit(1)).mappings().first()
            return clean(dict(row)) if row else None

    def diagnostic_ping(self,p):
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,p);self.store._access_require(conn,p,'read')
            return clean(dict(
                ok=True,
                project_id=project['id'],
                revision=project['revision'],
                database='connected',
                server_time=datetime.now(timezone.utc).isoformat(),
            ))

    def configure(self,p,payload,**kw):
        def work(conn,project):
            person=self._identity(conn);old=conn.execute(select(S.service_configuration_versions).where(S.service_configuration_versions.c.project_id==p).order_by(S.service_configuration_versions.c.version.desc()).limit(1)).mappings().first()
            if (old['id'] if old else None)!=payload['base_version_id']:raise Conflict('运营配置已有新版本','service_configuration_conflict')
            identifier=new_id();conn.execute(insert(S.service_configuration_versions).values(project_id=p,id=identifier,version=old['version']+1 if old else 1,document=payload['document'],sha256=digest(payload['document']),created_by=person['id']))
            return {'id':identifier}
        return self.store._mutate(p,'service_operations_configure',payload,callback=work,**kw)

    def publish(self,p,payload,**kw):
        def work(conn,project):
            person=self._identity(conn);old=conn.execute(select(S.service_announcements).where(S.service_announcements.c.project_id==p,S.service_announcements.c.announcement_key==payload['announcement_key']).order_by(S.service_announcements.c.version.desc()).limit(1)).mappings().first()
            if (old['id'] if old else None)!=payload['base_version_id']:raise Conflict('公告已有新版本','service_announcement_conflict')
            identifier=new_id();conn.execute(insert(S.service_announcements).values(project_id=p,id=identifier,created_by=person['id'],version=old['version']+1 if old else 1,**{k:v for k,v in payload.items() if k!='base_version_id'}))
            return {'id':identifier}
        return self.store._mutate(p,'service_announcement_publish',payload,callback=work,**kw)

    def create_request(self,p,payload,**kw):
        def work(conn,project):
            person=self._identity(conn)
            if payload['artifact_id']:self.store._one(conn,S.artifact_versions,p,checked_id(payload['artifact_id']))
            if payload['media_id']:self.store._one(conn,S.media_items,p,checked_id(payload['media_id']))
            if payload['kind']=='distribution':
                if not payload['artifact_id']:raise ResourceError('分发申请需要固定内容版本','distribution_version_required')
                if not self.store._artifact_approved(conn,p,payload['artifact_id']):raise ResourceError('分发申请须绑定已批准版本','distribution_unapproved')
            identifier=new_id();conn.execute(insert(S.service_requests).values(project_id=p,id=identifier,requester_id=person['id'],**payload))
            status='awaiting_configuration' if payload['kind'] in {'fcp','studio','production_service','distribution'} else 'received'
            self._event(conn,p,identifier,status,'已保存本地申请；没有向外部服务发送',person['id'])
            return {'id':identifier,'status':status}
        return self.store._mutate(p,'service_request_create',payload,callback=work,**kw)

    def transition(self,p,payload,withdraw=False,**kw):
        def work(conn,project):
            person=self._identity(conn);row=self.store._one(conn,S.service_requests,p,payload['request_id']);last=self._latest(conn,p,row['id'])
            if last['id']!=payload['base_event_id']:raise Conflict('申请已有新处理记录，请先读取','service_request_conflict')
            if withdraw and row['requester_id']!=person['id']:denied('只能撤回本人的申请')
            status='withdrawn' if withdraw else payload['status']
            if last['status'] in {'withdrawn','export_ready','rejected','account_closed'}:raise Conflict('申请已结束，保留原处理记录','service_request_terminal')
            if row['kind']=='personal_export' and not withdraw:raise ResourceError('个人导出只由本人实际生成文件完成','export_owner_required')
            self._event(conn,p,row['id'],status,payload['reason'],person['id']);return {'id':row['id'],'status':status}
        return self.store._mutate(p,'service_request_withdraw' if withdraw else 'service_request_process',payload,callback=work,**kw)

    def issue_key(self,p,payload,**kw):
        def work(conn,project):
            person=self._identity(conn)
            if not conn.execute(select(S.access_projects.c.project_id).where(S.access_projects.c.project_id==p)).first():raise ResourceError('请先将项目归属到个人空间或工作室，再发放范围凭据','api_project_unassigned')
            for cap in payload['capabilities']:self.store._access_require(conn,p,cap)
            identifier=new_id();conn.execute(insert(S.service_api_keys).values(project_id=p,id=identifier,identity_id=person['id'],name=payload['name'],secret_sha256=secret_hash(payload['secret']),prefix=payload['secret'][:8],capabilities=payload['capabilities'],expires_at=payload['expires_at'],ip_allowlist=payload['ip_allowlist'],requests_per_minute=payload['requests_per_minute']))
            return {'id':identifier,'prefix':payload['secret'][:8],'secret_returned':False}
        # Receipts hold metadata only, never the generated raw secret.
        values={k:v for k,v in payload.items() if k!='secret'};values['secret_sha256']=secret_hash(payload['secret'])
        return self.store._mutate(p,'service_api_key_issue',values,callback=work,**kw)

    def revoke_key(self,p,payload,**kw):
        def work(conn,project):
            person=self._identity(conn);key=self.store._one(conn,S.service_api_keys,p,payload['key_id'])
            if key['identity_id']!=person['id']:denied('只能撤销本人API凭据')
            conn.execute(update(S.service_api_keys).where(S.service_api_keys.c.project_id==p,S.service_api_keys.c.id==key['id']).values(revoked=True))
            return {'id':key['id'],'revoked':True}
        return self.store._mutate(p,'service_api_key_revoke',payload,callback=work,**kw)

    def validate_api_key(self,conn,principal,project_id=None,capability=None):
        key=conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.id==checked_id(principal.api_key_id))).mappings().first()
        if not key or key['revoked'] or key['expires_at']<=datetime.now(timezone.utc) or key['identity_id']!=principal.identity_id:denied('API凭据已撤销、过期或身份不符')
        if project_id is not None and key['project_id']!=project_id:denied('API凭据不属于此项目')
        if capability is not None and capability not in key['capabilities']:denied('API凭据未授予此能力')
        return dict(key)

    def authenticate_api_key(self,secret):
        hashed=secret_hash(secret)
        with self.store.engine.connect() as conn:
            key=conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.secret_sha256==hashed)).mappings().first()
            if not key:denied('API凭据无效')
            person=self.store._access_identity(conn,key['identity_id'])
            principal=Principal(identity_id=person['id'],actor=person['actor'],api_key_id=key['id'])
            self.validate_api_key(conn,principal)
            token=set_principal(principal)
            try:self.store._access_require(conn,key['project_id'],'read')
            finally:reset_principal(token)
            return principal

    def call_event(self,p,call_id,operation,phase,status_code,error_code=None,run_id=None,job_ids=(),client_ip=None):
        principal=current_principal()
        if not principal or not principal.api_key_id:denied('开放接口需要专用API凭据')
        failure=None
        with self.store.engine.begin() as conn:
            if phase=='started':
                from .access_control import authority_lock
                authority_lock(conn)
                self.store._access_require(conn,p,'read')
                key=conn.execute(select(S.service_api_keys).where(S.service_api_keys.c.id==principal.api_key_id).with_for_update()).mappings().one()
                import ipaddress
                if key['ip_allowlist']:
                    try:allowed=any(ipaddress.ip_address(client_ip) in ipaddress.ip_network(n) for n in key['ip_allowlist'])
                    except (ValueError,TypeError):allowed=False
                    if not allowed:failure=('来源IP不在此凭据白名单内','api_ip_denied',403)
                if not failure and key['requests_per_minute']:
                    count=conn.execute(select(func.count()).select_from(S.service_api_calls).where(S.service_api_calls.c.api_key_id==key['id'],S.service_api_calls.c.phase=='started',S.service_api_calls.c.status_code==0,S.service_api_calls.c.created_at>datetime.now(timezone.utc)-timedelta(minutes=1))).scalar_one()
                    if count>=key['requests_per_minute']:failure=('此凭据已达到每分钟调用上限，请稍后查询原任务','api_rate_limited',429)
                if failure:status_code=failure[2];error_code=failure[1]
            elif not conn.execute(select(S.service_api_calls.c.id).where(S.service_api_calls.c.project_id==p,S.service_api_calls.c.api_key_id==principal.api_key_id,S.service_api_calls.c.call_id==call_id,S.service_api_calls.c.phase=='started')).first():denied('调用记录缺少起点')
            # Completion is an audit fact for the already started call, even if
            # revocation prevented its business mutation in the meantime.
            identifier=new_id();conn.execute(insert(S.service_api_calls).values(project_id=p,id=identifier,api_key_id=principal.api_key_id,call_id=call_id,phase=phase,operation=operation,status_code=status_code,error_code=error_code,run_version_id=run_id))
            for job_id in set(job_ids):conn.execute(insert(S.service_api_call_jobs).values(project_id=p,id=new_id(),call_event_id=identifier,job_id=job_id))
            if failure:conn.execute(insert(S.service_api_calls).values(project_id=p,id=new_id(),api_key_id=principal.api_key_id,call_id=call_id,phase='finished',operation=operation,status_code=failure[2],error_code=failure[1]))
        if failure:raise ResourceError(*failure)

    def build_export(self,p,payload,storage,**kw):
        def work(conn,project):
            person=self._identity(conn);row=self.store._one(conn,S.service_requests,p,payload['request_id'])
            if row['requester_id']!=person['id'] or row['kind']!='personal_export':denied('只可导出本人申请的个人信息')
            last=self._latest(conn,p,row['id'])
            if last['status']=='export_ready':
                old=conn.execute(select(S.service_export_files).where(S.service_export_files.c.project_id==p,S.service_export_files.c.request_id==row['id'])).mappings().one();return {'id':old['id'],'request_id':row['id'],'status':'export_ready'}
            if last['status'] in {'withdrawn','rejected'}:raise Conflict('申请已结束','service_request_terminal')
            fields=row['requested_fields'];snapshot=dict(format='vsc.personal-data/v1',project_id=p,project_revision=project['revision'],identity_id=person['id'],requested_fields=fields)
            if 'profile' in fields:snapshot['profile']={k:person[k] for k in ('id','actor','display_name','active','created_at')}
            if 'memberships' in fields:
                scope=self.store._access_require(conn,p,'read');snapshot['project_access']={k:scope.get(k) for k in ('project_id','workspace_id','current_identity_id','effective_role','capabilities')}
            if 'requests' in fields:snapshot['requests']=[dict(r) for r in conn.execute(select(S.service_requests).where(S.service_requests.c.project_id==p,S.service_requests.c.requester_id==person['id'])).mappings()]
            if 'orders' in fields:
                snapshot['orders']=[{k:r[k] for k in ('id','plan_id','status','amount_minor','currency','credits','created_at','paid_at')} for r in conn.execute(select(S.commerce_orders).where(S.commerce_orders.c.project_id==p,S.commerce_orders.c.actor==person['actor'])).mappings()]
            snapshot=clean(snapshot);raw=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,indent=2).encode();stream=io.BytesIO()
            if len(raw)>10*1024*1024:raise ResourceError('本地导出超过10MB，请缩小字段范围','export_too_large')
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('personal-data.json',raw);archive.writestr('README.txt','本人在所选项目范围内的固定信息快照。此文件不是账户注销或外部服务完成证明。')
            stream.seek(0);staged=storage.stage_upload(stream,'personal-data.zip');blob=storage.commit_upload(staged['staged_upload']);identifier=new_id()
            conn.execute(insert(S.service_export_files).values(project_id=p,id=identifier,request_id=row['id'],requester_id=person['id'],snapshot_revision=project['revision'],snapshot=snapshot,snapshot_sha256=digest(snapshot),object_key=blob['object_key'],sha256=blob['sha256'],size_bytes=blob['size_bytes'],expires_at=datetime.now(timezone.utc)+timedelta(hours=24)))
            self._event(conn,p,row['id'],'export_ready','本地文件已生成，下载时再次核对身份与权限',person['id'])
            return {'id':identifier,'request_id':row['id'],'status':'export_ready'}
        return self.store._mutate(p,'service_export_build',payload,callback=work,**kw)

    def export_file(self,p,identifier):
        with self.store.engine.connect() as conn:
            self.store._access_require(conn,p,'read');person=self._identity(conn);row=self.store._one(conn,S.service_export_files,p,checked_id(identifier))
            if row['requester_id']!=person['id']:denied('此文件属于其他身份')
            if row['expires_at']<=datetime.now(timezone.utc):raise ResourceError('下载已过期，请重新申请当前信息','export_expired',410)
            return dict(row)

    def cancel_job(self,p,payload,**kw):
        def work(conn,project):
            job=self.store._one(conn,S.generation_jobs,p,payload['job_id'])
            if job['status']!='created' or job['claim_owner']:raise Conflict('只可取消尚未由工作者领取的本地待执行任务；远端任务需原恢复流程','api_cancel_unavailable')
            return self.store._update_generation_job(p,{'job_id':job['id'],'status':'cancelled'},_transaction=(conn,project),**kw)
        return self.store._mutate(p,'service_api_cancel',payload,callback=work,**kw)
