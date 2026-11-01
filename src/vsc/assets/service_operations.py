"""Operations consumers retain original account, task, budget and storage authority."""
from datetime import datetime,timezone
from urllib.parse import urlsplit
import uuid

KINDS={'feedback','support','fcp','studio','production_service','distribution','account_close','personal_export'}
EXPORT_FIELDS={'profile','memberships','requests','orders'}

def error(message,code='invalid_service_operations'):
    from vsc.assets.resource_service import ResourceError
    raise ResourceError(message,code)

def text(value,name,limit=200,empty=False):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or not empty and not value.strip():error(name+'为空或超过长度')
    return value.strip()

def fields(payload,names):
    if not isinstance(payload,dict) or set(payload)!=set(names.split()):error('操作字段不完整或包含未授权字段')

class ServiceOperationsService:
    def preview_account_close(self,p,payload):
        self.authorize_access(p,'read');fields(payload,'request_id')
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).preview(p,payload['request_id'])

    def close_service_account(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'request_id preview_sha256 confirm_actor')
        from vsc.adapters.persistence.postgres.account_lifecycle import AccountLifecycleRepository
        return AccountLifecycleRepository(self.store).close(p,payload,**kw)

    def _operations(self):
        from vsc.adapters.persistence.postgres.service_operations import ServiceOperationsRepository
        return ServiceOperationsRepository(self.store)

    def service_operations_snapshot(self,p):
        self.authorize_access(p,'read');return self._operations().snapshot(p)

    def configure_service_operations(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'document base_version_id');doc=payload['document'];fields(doc,'support_text terms_url privacy_url api_documentation')
        for name in ('support_text','api_documentation'):text(doc[name],name,5000,True)
        for name in ('terms_url','privacy_url'):
            value=text(doc[name],name,2000,True)
            if value and (urlsplit(value).scheme!='https' or not urlsplit(value).hostname or urlsplit(value).username):error('条款/隐私链接须为明确HTTPS地址')
        return self._operations().configure(p,payload,**kw)

    def publish_service_announcement(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'announcement_key base_version_id title body status')
        for name,limit in (('announcement_key',80),('title',200),('body',10000)):text(payload[name],name,limit)
        if payload['status'] not in {'published','withdrawn'}:error('选择发布或撤回公告')
        return self._operations().publish(p,payload,**kw)

    def create_service_request(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'kind title body contact channel artifact_id media_id requested_fields')
        if payload['kind'] not in KINDS:error('申请类型未支持')
        for name,limit,empty in (('title',200,False),('body',10000,False),('contact',254,True),('channel',200,True)):text(payload[name],name,limit,empty)
        selected=payload['requested_fields']
        if not isinstance(selected,list) or any(not isinstance(x,str) or x not in EXPORT_FIELDS for x in selected) or len(set(selected))!=len(selected):error('导出字段范围不正确')
        if (payload['kind']=='personal_export') != bool(selected):error('个人导出需要明确字段，其他申请不能附带导出字段')
        return self._operations().create_request(p,payload,**kw)

    def process_service_request(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'request_id base_event_id status reason');text(payload['reason'],'处理说明',3000)
        if payload['status'] not in {'under_review','awaiting_configuration','local_approved','rejected'}:error('处理记录不能冒充实际执行完成')
        return self._operations().transition(p,payload,**kw)

    def withdraw_service_request(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'request_id base_event_id reason');text(payload['reason'],'撤回说明',3000)
        return self._operations().transition(p,payload,withdraw=True,**kw)

    def issue_service_api_key(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read')
        payload=dict(payload);payload.setdefault('ip_allowlist',[]);payload.setdefault('requests_per_minute',0)
        fields(payload,'name secret capabilities expires_at ip_allowlist requests_per_minute');text(payload['name'],'凭据名称',100)
        import ipaddress
        networks=payload['ip_allowlist']
        if not isinstance(networks,list) or len(networks)>100 or any(not isinstance(n,str) for n in networks):error('IP白名单需要至多100项IP或CIDR网段')
        try:payload['ip_allowlist']=sorted(set(str(ipaddress.ip_network(n,strict=False)) for n in networks))
        except ValueError:error('IP白名单包含无效IP或网段')
        limit=payload['requests_per_minute']
        if type(limit)is not int or not 0<=limit<=10000:error('每分钟调用上限须为0–10000；0表示不设置此项限制')
        from vsc.assets.access_control import secret_hash
        secret_hash(payload['secret']);caps=payload['capabilities']
        if not isinstance(caps,list) or any(c not in {'read','execute'} for c in caps) or 'read' not in caps or len(set(caps))!=len(caps):error('API范围只可为read或read+execute')
        from vsc.assets.commerce import instant
        expiry=instant(payload['expires_at'])
        if not 0<(expiry-datetime.now(timezone.utc)).total_seconds()<=366*86400:error('API凭据有效期须在未来一年内')
        return self._operations().issue_key(p,dict(payload,expires_at=expiry),**kw)

    def revoke_service_api_key(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'key_id');return self._operations().revoke_key(p,payload,**kw)

    def authenticate_service_api_key(self,secret):return self._operations().authenticate_api_key(secret)

    def build_service_export(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'request_id')
        if self.storage is None:error('本地受控存储未配置，导出申请已保留','export_storage_unconfigured')
        return self._operations().build_export(p,payload,self.storage,**kw)

    def service_export_content(self,p,identifier):
        row=self._operations().export_file(p,identifier)
        if self.storage is None:error('本地受控存储未配置','export_storage_unconfigured')
        return self.storage.read(row['object_key'],row['sha256']),row['sha256']

    def service_api_operation(self,p,operation,payload=None,*,client_ip=None):
        from vsc.assets.access_control import current_principal,denied
        principal=current_principal()
        if not principal or not principal.api_key_id:denied('开放接口只接受专用API凭据')
        capability='execute' if operation in {'execute','cancel'} else 'read';self.authorize_access(p,capability)
        if operation not in {'jobs','job','usage','preview','execute','cancel'}:error('开放操作不存在')
        payload=payload or {};call_id=str(uuid.uuid4());repo=self._operations();repo.call_event(p,call_id,operation,'started',0,client_ip=client_ip)
        try:
            if operation=='jobs':
                if payload:fields(payload,'offset limit')
                offset,limit=payload.get('offset',0),payload.get('limit',50)
                if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=200:error('任务分页需要非负offset与1–200的limit')
                rows=self.list_generation_jobs(p,offset=offset,limit=limit);result=dict(total=rows['total'],offset=offset,limit=limit,items=[self._api_job(r) for r in rows['items']])
            elif operation=='job':fields(payload,'job_id');result=self._api_job(self.get_generation_job(p,payload['job_id']))
            elif operation=='usage':fields(payload,'');result=self.budget_status(p)
            elif operation in {'preview','execute'}:
                if set(payload)-{'run_version_id','run_sha256','task_keys'} or not payload.get('run_sha256'):error('API执行需要已批准运行编号、所见摘要及可选固定任务编号')
                from vsc.production.bounded import preview_batch,execute_batch
                result=execute_batch(self,p,payload,principal.actor) if operation=='execute' else preview_batch(self,p,payload)
                for item in result['tasks']:item.pop('payload',None)
            else:
                fields(payload,'job_id expected_revision idempotency_key')
                command={'job_id':payload['job_id']};kw=dict(actor=principal.actor,expected_revision=payload['expected_revision'],idempotency_key=payload['idempotency_key']);self._validate_write(command,**kw);result=repo.cancel_job(p,command,**kw)
        except Exception as exc:
            repo.call_event(p,call_id,operation,'finished',getattr(exc,'status_code',500),getattr(exc,'code','internal_error'));raise
        job_ids=[r['job_id'] for r in result.get('tasks',[]) if r.get('job_id')]
        if operation in {'job','cancel'}:job_ids.append(payload['job_id'])
        repo.call_event(p,call_id,operation,'finished',200,run_id=result.get('run_version_id') if operation in {'execute','preview'} else None,job_ids=job_ids)
        return dict(result,api_call_id=call_id)

    @staticmethod
    def _api_job(value):return {k:value.get(k) for k in ('id','project_id','run_version_id','shot_id','asset_id','purpose','modality','candidate_no','status','attempt','created_at','updated_at','outputs')}
