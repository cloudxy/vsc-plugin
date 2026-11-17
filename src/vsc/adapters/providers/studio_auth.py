"""Adapter for the installed API-settings CLI execution seam, with fixed media."""
import base64
import math
import re

from vsc.assets.resource_service import ResourceError
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
from vsc.production.studio_models import is_studio_auth_configuration


class StudioAuthImageProvider:
    def __init__(self,job,storage,generate):
        self.job,self.storage,self.generate=job,storage,generate

    def preflight(self,request=None):
        if not callable(self.generate):
            raise ResourceError('本机订阅执行器尚未接入当前宿主','studio_auth_executor_unavailable')
        if request is not None and (request.params or request.operation):
            raise ResourceError('该订阅通道仅接受提示词和参考图，当前原生处理参数不支持','unsupported_params')

    def submit(self,request):
        self.preflight(request)
        fixed={item['media_id']:item for item in self.job['input_media']}
        references=[]
        for media_id in request.reference_media_ids:
            item=fixed.get(media_id)
            if not item:raise ResourceError('参考图不属于原任务固定输入','unfixed_reference')
            location=next((loc for loc in item['locations'] if loc['storage']=='local' and loc['available']),None)
            if not location:raise ResourceError('参考图没有可读本地字节','media_unavailable')
            data=self.storage.read(location['object_key'],item['blob_sha256'])
            references.append('data:'+item['mime_type']+';base64,'+base64.b64encode(data).decode('ascii'))
        divisor=math.gcd(request.width,request.height)
        body=dict(model=self.job['model']['model_key'],prompt=request.prompt,references=references,
                  aspect_ratio=f'{request.width//divisor}:{request.height//divisor}')
        provider=self.job['provider']['configuration']['tool_id'].removeprefix('api-settings-')
        result=self.generate(provider,body)
        return JobHandle(self.job['provider_id'],self.job['model']['model_key'],None,result)

    def poll(self,handle):
        if handle.provider!=self.job['provider_id'] or handle.model!=self.job['model']['model_key']:
            raise ResourceError('原任务句柄与模型不符','invalid_provider_handle')
        if isinstance(handle.raw,dict) and handle.raw.get('error'):
            code=handle.raw.get('http_status')
            known_rejection=isinstance(code,int) and 400<=code<500 and code!=408
            return JobStatus('failed' if known_rejection else 'submission_unknown',raw=handle.raw,
                             error_code='studio_auth_generation_failed')
        return JobStatus('succeeded',raw=handle.raw)

    def parse_result(self,raw):
        uri=raw.get('image_url','') if isinstance(raw,dict) else ''
        match=re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',uri)
        if not match or len(uri)>24*1024*1024:
            raise ResourceError('订阅通道未返回可验证图片字节','output_missing')
        try:data=base64.b64decode(match[1],validate=True)
        except ValueError as exc:raise ResourceError('生成图片编码无效','output_decode_failed') from exc
        return [GeneratedAsset('image',inline_bytes=data)]


def studio_auth_factory(job,storage,generate):
    value=dict(job['provider']['configuration'],modality=job['modality'],model_key=job['model']['model_key'],
           base_url=job['provider']['base_url'],auth_ref=job['provider']['auth_ref'],
           capabilities=job['model']['capabilities'],default_params=job['model']['default_params'])
    if not is_studio_auth_configuration(value):
        raise ResourceError('本机订阅模型固定配置无效','invalid_provider_config')
    return StudioAuthImageProvider(job,storage,generate)
