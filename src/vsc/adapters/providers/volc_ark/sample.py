"""Native Draft payloads; never re-upload an old preview as ordinary video.

Verified 2026-11-02: https://docs.volcengine.com/docs/ark/seedance-2-5?lang=en
"""
from __future__ import annotations
from vsc.assets.resource_service import ResourceError
from vsc.production.video_samples import SAMPLE_MODELS,validate_sample_binding,upgrade_options


def validate_draft_request(request,model,resolution,enabled):
    draft=getattr(request,'draft',False)
    if type(draft) is not bool:raise ResourceError('样片开关必须为布尔值','invalid_sample_request')
    if draft and (not enabled or model not in SAMPLE_MODELS or resolution!='480p' or getattr(request,'operation',None)):
        raise ResourceError('原生Draft需要明确开启的Seedance2.5能力与480p配置','sample_capability_missing')
    return draft


def upgrade_payload(request,model,provider_id,binding,*,resolution,enabled,now=None):
    if not enabled or resolution!='1080p' or getattr(request,'draft',False) is not False or getattr(request,'operation',None)!='draft_upgrade':
        raise ResourceError('样片升级需要1080p配置与明确升级操作','invalid_sample_upgrade')
    validate_sample_binding(binding,provider_id=provider_id,model_key=model,now=now)
    for name in ('source_media_id','source_sha256','source_duration_ms'):
        if getattr(request,name,None)!=binding[name]:raise ResourceError('升级请求与原样片固定来源不符','sample_binding_mismatch')
    if any(getattr(request,name,None) for name in ('first_frame_media_id','last_frame_media_id','reference_media_ids','reference_audio_media_ids','reference_video_media_ids','keyframes')):
        raise ResourceError('升级自动复用原任务，不接收新的素材引用','sample_references_forbidden')
    return {'model':model,'content':[{'type':'draft_task','draft_task':{'id':binding['external_task_id']}}],
            'resolution':'1080p','draft':False,**upgrade_options(request.params)}
