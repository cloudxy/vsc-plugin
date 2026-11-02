"""Fixed Seedance draft provenance and time boundaries, without remote calls.

The repository supplies the source job through its typed output relation under
the original project transaction. No client-supplied external ID is authority.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
from vsc.assets.resource_service import ResourceError

SAMPLE_MODELS=frozenset({'doubao-seedance-2-5-260628'})
UPGRADE_PROMPT='将固定的原生480p样片升级为1080p，沿用原任务内容。'
TTL_CHANGE=datetime(2026,10,28,2,tzinfo=timezone.utc)
BINDING_FIELDS=frozenset({'source_job_id','source_media_id','source_sha256','source_duration_ms',
    'source_request_sha256','external_task_id','provider_id','model_key','created_at'})


def provider_created_at(value):
    try:
        if type(value) in (int,float):result=datetime.fromtimestamp(value,timezone.utc)
        elif isinstance(value,str):result=datetime.fromisoformat(value.replace('Z','+00:00'))
        else:raise ValueError('missing timestamp')
        if result.tzinfo is None:raise ValueError('missing timezone')
        return result.astimezone(timezone.utc)
    except (ValueError,OverflowError,OSError) as exc:
        raise ResourceError('样片缺少供应商created_at，不能推测有效期','sample_created_at_missing') from exc


def sample_deadline(created_at):
    created=provider_created_at(created_at)
    return created+timedelta(days=14 if created>=TTL_CHANGE else 7)


def validate_sample_binding(binding,*,provider_id,model_key,now=None):
    if not isinstance(binding,dict) or set(binding)!=BINDING_FIELDS:
        raise ResourceError('升级需要服务端解析的完整样片来源','sample_binding_invalid')
    if binding['provider_id']!=provider_id or binding['model_key']!=model_key or model_key not in SAMPLE_MODELS:
        raise ResourceError('升级须沿原样片的同一模型和提供者账户','sample_account_mismatch')
    if not isinstance(binding['external_task_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',binding['external_task_id']):
        raise ResourceError('原样片缺少可信任务ID，不能升级','sample_task_id_missing')
    for field in ('source_job_id','source_media_id'):
        if not isinstance(binding[field],str) or not binding[field]:raise ResourceError('样片来源关系不完整','sample_binding_invalid')
    for field in ('source_sha256','source_request_sha256'):
        if not isinstance(binding[field],str) or not re.fullmatch('[0-9a-f]{64}',binding[field]):raise ResourceError('样片来源缺少固定摘要','sample_binding_invalid')
    if type(binding['source_duration_ms']) is not int or binding['source_duration_ms']<=0:
        raise ResourceError('样片缺少真实视频时长','sample_binding_invalid')
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None:raise ValueError('now must be timezone-aware')
    created=provider_created_at(binding['created_at']);deadline=sample_deadline(created.isoformat())
    if created>instant:raise ResourceError('样片供应商创建时间晚于当前时间，需核对原回执','sample_created_at_invalid')
    if instant>=deadline:raise ResourceError('原样片任务已过有效期，保留原480p结果，无法再升级','sample_expired')
    return deadline


def bind_sample(source_job,source_media,target_model,target_provider_id,*,now=None):
    """Caller must obtain source_job through job_outputs in the locked project."""
    request=source_job.get('request_payload',{});request=request.get('logical_request',request)
    raw=source_job.get('raw_response') or {}
    if source_job.get('status')!='succeeded' or source_job.get('modality')!='video' or request.get('draft') is not True or request.get('operation'):
        raise ResourceError('只有已完成的原生Draft样片可以升级','sample_job_required')
    if source_job.get('project_id')!=source_media.get('project_id') or source_media.get('modality')!='video':
        raise ResourceError('样片来源必须属于当前项目的真实视频','sample_scope_mismatch')
    if min(source_media.get('width') or 0,source_media.get('height') or 0)!=480:
        raise ResourceError('原样片实际输出不是480p视频','sample_output_resolution')
    if not any(row.get('media_id')==source_media['id'] for row in source_job.get('outputs',[])):
        raise ResourceError('视频不是该原样片任务的登记输出','sample_output_mismatch')
    if (source_job.get('model') or {}).get('model_key')!=target_model.get('model_key') or source_job.get('provider_id')!=target_provider_id:
        raise ResourceError('升级必须使用原模型与原提供者账户','sample_account_mismatch')
    if (source_job.get('model') or {}).get('default_params',{}).get('resolution')!='480p' or target_model.get('default_params',{}).get('resolution')!='1080p':
        raise ResourceError('样片与升级须分别使用480p和1080p固定报价配置','sample_resolution_mismatch')
    if target_model.get('capabilities',{}).get('video_draft') is not True or (source_job.get('model') or {}).get('capabilities',{}).get('video_draft') is not True:
        raise ResourceError('固定模型配置未声明原生样片能力','sample_capability_missing')
    if raw.get('id')!=source_job.get('external_task_id') or raw.get('status')!='succeeded':
        raise ResourceError('原样片成功回执与任务ID不符','sample_receipt_mismatch')
    if raw.get('model',target_model['model_key'])!=target_model['model_key'] or raw.get('resolution','480p')!='480p' or raw.get('draft',True) is not True:
        raise ResourceError('原回执不属于480p Draft任务','sample_receipt_mismatch')
    binding=dict(source_job_id=source_job['id'],source_media_id=source_media['id'],source_sha256=source_media['sha256'],
        source_duration_ms=source_media.get('duration_ms'),source_request_sha256=source_job['request_sha256'],
        external_task_id=source_job.get('external_task_id'),provider_id=target_provider_id,model_key=target_model['model_key'],
        created_at=provider_created_at(raw.get('created_at')).isoformat())
    validate_sample_binding(binding,provider_id=target_provider_id,model_key=target_model['model_key'],now=now)
    return binding


def upgrade_options(params):
    if not isinstance(params,dict) or set(params)-{'return_last_frame','watermark','output_format'}:
        raise ResourceError('升级只可重新指定尾帧、输出格式和水印，不重复传入原生成参数','sample_options_invalid')
    for name in ('return_last_frame','watermark'):
        if name in params and type(params[name]) is not bool:raise ResourceError('升级输出开关无效','sample_options_invalid')
    if 'output_format' in params and params['output_format'] not in {'mp4','mov'}:
        raise ResourceError('升级输出格式须为mp4或mov','sample_options_invalid')
    return dict(params)


def upgrade_request(source):
    return dict(operation='draft_upgrade',source_media_id=source['id'],source_sha256=source['sha256'],
        source_duration_ms=source['duration_ms'],duration_ms=source['duration_ms'],prompt=UPGRADE_PROMPT)


def validate_sample_output(logical, media):
    target=480 if logical.get('draft') is True else 1080 if logical.get('operation')=='draft_upgrade' else None
    if target is None:return
    if media.get('modality')!='video' or min(media.get('width') or 0,media.get('height') or 0)!=target:
        raise ResourceError('样片或升级结果的实际分辨率不符合固定请求，保留回执供恢复','sample_output_resolution')
    if not media.get('duration_ms') or abs(media['duration_ms']-logical['duration_ms'])>500:
        raise ResourceError('样片或升级结果时长与固定请求不符','sample_output_duration')
