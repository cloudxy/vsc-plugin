"""Configured JSON distribution port. Callers persist intent before submit; unknown is query-only."""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlsplit
import os,re

class DistributionUnavailable(Exception):pass
class DistributionUnknown(Exception):pass

@dataclass(frozen=True)
class DistributionReceipt:
    status:str
    remote_id:str|None=None
    public_url:str|None=None
    error_code:str|None=None

class HttpDistributionAdapter:
    """Contract: POST /submissions, GET /submissions/by-key/{key}, POST /submissions/{id}/cancel."""
    def __init__(self,configuration,client=None):
        self.configuration=configuration;self.client=client
        parsed=urlsplit(configuration['endpoint'])
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:raise DistributionUnavailable('分发端点须为配置的 HTTPS 根地址')
        env=configuration['credential_env']
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}',env):raise DistributionUnavailable('分发凭据引用无效')
        self.token=os.environ.get(env)
        if not self.token:raise DistributionUnavailable('分发凭据未加载：'+env)
    def _request(self,method,path,payload=None):
        import httpx
        own=self.client is None;client=self.client or httpx.Client(timeout=30,follow_redirects=False)
        try:
            response=client.request(method,self.configuration['endpoint'].rstrip('/')+path,headers={'Authorization':'Bearer '+self.token},json=payload)
            if response.status_code==404:return DistributionReceipt('unknown',error_code='not_found_by_request_key')
            if response.status_code>=500:raise DistributionUnknown('分发服务未返回可核对的回执')
            if not 200<=response.status_code<300:return DistributionReceipt('unknown',error_code='http_'+str(response.status_code))
            value=response.json()
            if not isinstance(value,dict):raise DistributionUnknown('分发回执必须为对象')
            status=value.get('status')
            if status not in {'submitted','completed','failed','cancelled','unknown'}:raise DistributionUnknown('分发回执状态无法识别')
            remote=value.get('remote_id');url=value.get('public_url');error=value.get('error_code')
            if remote is not None and (not isinstance(remote,str) or len(remote)>300):raise DistributionUnknown('分发回执标识无效')
            if status in {'submitted','completed'} and not remote:raise DistributionUnknown('分发回执缺少远端标识')
            if url and (not isinstance(url,str) or len(url)>2000 or urlsplit(url).scheme!='https'):raise DistributionUnknown('分发回执链接无效')
            return DistributionReceipt(status,remote,url,str(error)[:200] if error else None)
        except (httpx.RequestError,ValueError,TypeError) as exc:raise DistributionUnknown('分发连接或响应未确认') from exc
        finally:
            if own:client.close()
    def submit(self,request):return self._request('POST','/submissions',request)
    def query(self,request_key):
        from urllib.parse import quote
        return self._request('GET','/submissions/by-key/'+quote(request_key,safe=''))
    def cancel(self,remote_id):
        from urllib.parse import quote
        return self._request('POST','/submissions/'+quote(remote_id,safe='')+'/cancel',{})
