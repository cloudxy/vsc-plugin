"""Explicit local publication, governance and configured distribution consumers."""
from dataclasses import asdict
import base64,re,uuid
from urllib.parse import urlsplit
from vsc.assets.resource_service import ResourceError
from vsc.assets.service_operations import fields,text
from vsc.adapters.providers.distribution import DistributionReceipt,DistributionUnavailable,DistributionUnknown,HttpDistributionAdapter

class CommunityServiceMixin:
    def _community(self):
        from vsc.adapters.persistence.postgres.community import CommunityRepository
        return CommunityRepository(self.store)
    def community_feed(self,query='',offset=0,limit=24):
        if not isinstance(query,str) or len(query)>200 or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=100:raise ResourceError('社区检索或分页无效')
        return self._community().feed(query,offset,limit)
    def community_snapshot(self,p):
        self.authorize_access(p,'read');result=self._community().snapshot(p)
        for channel in result['channels']:
            channel['available'],channel['unavailable_reason']=self._distribution_availability(channel)
        return result
    def community_detail(self,p,identifier,version_id=None):
        self.authorize_access(p,'read');return self._community().detail(p,identifier,version_id)
    def save_community_rule(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'base_version_id title body');text(payload['title'],'规则标题',200);text(payload['body'],'规则正文',20000)
        return self._community().save_rule(p,payload,**kw)
    def save_community_publication(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'edit');fields(payload,'publication_id base_version_id title description scope rule_id media_id template_id')
        text(payload['title'],'作品标题',200);text(payload['description'],'作品介绍',10000,True)
        if payload['scope'] not in {'project','workspace'} or bool(payload['media_id'])==bool(payload['template_id']):raise ResourceError('选择发布范围与一种固定内容')
        return self._community().save_publication(p,payload,**kw)
    def set_community_publication_state(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'publish');fields(payload,'version_id base_event_id status reason');text(payload['reason'],'发布或撤回说明',2000)
        if payload['status'] not in {'published','withdrawn'}:raise ResourceError('只能明确发布或撤回当前版本')
        if payload['status']=='published':
            version=self._community_version(p,payload['version_id'])
            if version['media_id']:self._verify_media(p,version['media_id'])
            else:
                for identifier in self._canvas_templates().media_ids(p,version['template_id']):self._verify_media(p,identifier)
        return self._community().transition(p,payload,**kw)
    def _community_version(self,p,identifier):
        from vsc.adapters.persistence.postgres import schema as S
        with self.store.engine.connect() as c:return self.store._one(c,S.community_versions,p,identifier)
    def report_community_publication(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'read');fields(payload,'version_id reason');text(payload['reason'],'举报事实与依据',4000)
        return self._community().report(p,payload,**kw)
    def moderate_community_publication(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'version_id report_id base_decision_id action reason');text(payload['reason'],'处理依据',4000)
        if payload['action'] not in {'restrict','release','dismiss'}:raise ResourceError('选择限制、撤销限制或驳回举报')
        return self._community().moderate(p,payload,**kw)
    def community_content(self,p,version_id):
        self.authorize_access(p,'read');v=self._community_version(p,version_id);detail=self._community().detail(p,v['publication_id'],v['id'])
        if detail['status']!='published':raise ResourceError('此内容版本当前不在社区发布','community_not_published',409)
        if not v['media_id']:raise ResourceError('模板从固定画布版本查看')
        with self.store.engine.connect() as c:self._community()._check_rights(c,p,v)
        self._verify_media(p,v['media_id']);media=self.get_media(p,v['media_id']);location=next((l for l in media['locations'] if l['available'] and l['storage']=='local'),None)
        if not self.storage or not location:raise ResourceError('固定内容暂无可读本地副本')
        return self.storage.read(location['object_key'],media['sha256']),media['mime_type']
    def save_distribution_channel(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'manage');fields(payload,'channel_key base_version_id name adapter endpoint credential_env enabled')
        for key,limit in [('channel_key',80),('name',200),('adapter',80),('endpoint',2000),('credential_env',100)]:text(payload[key],key,limit)
        if type(payload['enabled'])is not bool:raise ResourceError('请明确渠道启用状态')
        if payload['adapter']!='http-json-v1' and payload['adapter'] not in getattr(self,'distribution_adapters',{}):raise ResourceError('没有此分发适配器')
        url=urlsplit(payload['endpoint'])
        if url.scheme!='https' or not url.hostname or url.username or url.query or url.fragment:raise ResourceError('渠道端点须为明确 HTTPS 根地址')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}',payload['credential_env']):raise ResourceError('这里只填写凭据环境变量名称，不能保存密钥')
        return self._community().save_channel(p,payload,**kw)
    def _distribution_adapter(self,channel):
        if not channel['enabled']:raise DistributionUnavailable('此分发渠道已停用')
        injected=getattr(self,'distribution_adapters',{}).get(channel['adapter'])
        if injected is not None:return injected
        if channel['adapter']!='http-json-v1':raise DistributionUnavailable('此分发适配器未安装')
        return HttpDistributionAdapter(channel)
    def _distribution_availability(self,channel):
        try:self._distribution_adapter(channel);return True,None
        except DistributionUnavailable as exc:return False,str(exc)
    def prepare_distribution(self,p,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'publish');fields(payload,'version_id channel_id caption');text(payload['caption'],'分发介绍',10000,True)
        return self._community().prepare_distribution(p,payload,**kw)
    def distribution_detail(self,p,identifier):self.authorize_access(p,'read');return self._community().distribution(p,identifier)
    def run_distribution(self,p,identifier,action,payload,**kw):
        self._validate_write(payload,**kw);self.authorize_access(p,'publish');fields(payload,'request_sha256')
        if action not in {'execute','refresh','cancel'}:raise ResourceError('分发操作无效')
        repo=self._community();row=repo.distribution(p,identifier)
        if row['request_sha256']!=payload['request_sha256']:raise ResourceError('固定分发请求摘要不匹配')
        if row['status'] in {'completed','failed','cancelled'}:return row
        if action=='cancel' and row['status']=='prepared':
            repo.cancel_prepared_distribution(p,identifier,payload,**kw);return repo.distribution(p,identifier)
        try:adapter=self._distribution_adapter(row['channel'])
        except DistributionUnavailable as exc:raise ResourceError(str(exc),'distribution_unconfigured',409) from exc
        if action=='execute' and row['status']=='prepared':
            self._verify_media(p,row['version']['media_id']);media=self.get_media(p,row['version']['media_id']);location=next((l for l in media['locations'] if l['available'] and l['storage']=='local'),None)
            if not self.storage or not location:raise ResourceError('固定分发媒体没有可读本地副本')
            if media['size_bytes']>128*1024*1024:raise ResourceError('当前 JSON 分发端口单个媒体上限128 MiB')
            content=self.storage.read(location['object_key'],media['sha256'])
            claimed=repo.start_distribution(p,dict(request_id=identifier,request_sha256=row['request_sha256']),**kw)
            if not claimed['started']:return repo.distribution(p,identifier)
            request=dict(request_key=row['request_key'],request_sha256=row['request_sha256'],title=row['version']['title'],caption=row['caption'],content_sha256=media['sha256'],mime_type=media['mime_type'],content_base64=base64.b64encode(content).decode())
            try:receipt=adapter.submit(request)
            except Exception:receipt=DistributionReceipt('unknown',error_code='submission_receipt_unknown')
        elif action=='cancel':
            if row['status'] in {'submitting','unknown'} or not row['last'].get('remote_id'):raise ResourceError('提交结果未知时只查询原请求，不能重发或假称已取消','distribution_query_required',409)
            try:receipt=adapter.cancel(row['last']['remote_id'])
            except Exception:receipt=DistributionReceipt('unknown',remote_id=row['last']['remote_id'],error_code='cancel_receipt_unknown')
        else:
            if row['status']=='prepared':return row
            try:receipt=adapter.query(row['request_key'])
            except Exception:receipt=DistributionReceipt('unknown',remote_id=row['last'].get('remote_id'),error_code='query_unavailable')
        if not isinstance(receipt,DistributionReceipt) or receipt.status not in {'submitted','completed','failed','cancelled','unknown'}:receipt=DistributionReceipt('unknown',error_code='invalid_adapter_receipt')
        repo.finish_distribution(p,identifier,receipt,actor=kw['actor'],idempotency_key='distribution-response:'+uuid.uuid4().hex)
        return repo.distribution(p,identifier)
