#!/usr/bin/env python3
"""Validate the series_batch variant of an approved production run.

Live ShotContext checks run until the run is decided. Afterwards the approval
stays bound to its pinned versions; plan and submit re-check each job against
the current context, so a later selection on one shot cannot void the batch.
"""
import vsc_series_db as db
from vsc_series import _scope, build_shot_context


def operation(job):
    return f"series:{job['request']['shot_id']}:{job['request']['purpose']}:{job['candidate_no']}"


def units(job):
    request = job['request']
    modality = request['modality']
    if modality == 'image':
        return {'remote_jobs': 1, 'images': 1}
    if modality == 'video':
        duration = request.get('duration_ms')
        if type(duration) is not int or duration < 1000 or duration % 1000:
            raise ValueError('系列视频时长须为正整数秒')
        return {'remote_jobs': 1, 'video_seconds': duration // 1000}
    if modality == 'audio':
        prompt = request.get('prompt')
        if not isinstance(prompt, str) or not prompt:
            raise ValueError('系列音频请求须有非空文本')
        return {'remote_jobs': 1, 'audio_jobs': 1, 'speech_chars': len(prompt)}
    raise ValueError('未知系列任务模态')


def project_errors(data, project, state, item):
    errors = []
    if state.get('profile_snapshot', {}).get('storage_policy') != db.POLICY:
        return ['series_batch 只适用于数据库连续剧 Profile']
    if data.get('scope') != item.get('scope', 'project') or data.get('project_id') != state['project_id']:
        errors.append('run 的项目或范围与登记版本不一致')
    batch = data['series_batch']
    if db.digest(batch) != data.get('plan_sha256'):
        errors.append('series_batch 计划摘要不符')
    if any(not isinstance(ref, dict) or not isinstance(ref.get('id'), str)
           or not isinstance(ref.get('sha256'), str) for ref in data['approved_inputs']):
        return errors + ['approved_inputs 须为产物 ID 与 SHA 的对象数组']
    pinned = {(ref['id'], ref['sha256']) for ref in data['approved_inputs']}
    dependencies = {(ref, item.get('dependency_versions', {}).get(ref)) for ref in item.get('depends_on', [])}
    if pinned != dependencies:
        errors.append('series_batch 的全部批准输入须是 run 明确依赖的固定版本')
    if not any(next((a for a in state['artifacts'] if a['id'] == ref), {}).get('type') == 'vsc.animatic'
               for ref, _ in pinned):
        errors.append('系列制作须依赖已批准 animatic')
    live = not (item.get('status') == 'approved' and item.get('decision'))
    operations = {}
    for index, job in enumerate(batch['jobs']):
        try:
            if not isinstance(job, dict) or type(job.get('candidate_no')) is not int or job['candidate_no'] < 1:
                raise ValueError('候选编号须为正整数')
            request = job['request']
            if request.get('format') != 'vsc.generation-request/v1':
                raise ValueError('请求格式无效')
            from vsc_series_jobs import REQUEST_TYPES, audio_binding
            modality = request.get('modality')
            if modality not in REQUEST_TYPES:
                raise ValueError('请求模态无效')
            logical = REQUEST_TYPES[modality](**{key: value for key, value in request.items()
                                                 if key not in ('format', 'modality')})
            if not isinstance(logical.prompt, str) or not logical.prompt.strip() or not isinstance(logical.params, dict):
                raise ValueError('提示词或参数对象无效')
            if any(key in logical.params for key in ('provider', 'model', 'external_task_id', 'base_url', 'auth_ref')):
                raise ValueError('逻辑请求包含供应商参数')
            if not isinstance(logical.reference_media_ids, (list, tuple)) or not all(
                    isinstance(ref, str) and ref for ref in logical.reference_media_ids):
                raise ValueError('参考媒体 ID 必须是字符串数组')
            if _scope(state, request['shot_id'])[0] != data['scope']:
                raise ValueError('镜头不属于 run 分集范围')
            if live:
                context = build_shot_context(project, request['shot_id'])
                if context['sha256'] != request.get('context_sha256'):
                    raise ValueError('镜头上下文已变化')
                if context['unresolved_reference_asset_ids'] or (context['cross_episode_boundary'] and
                        context['cross_episode_boundary']['status'] != 'linked'):
                    raise ValueError('镜头参考或跨集边界尚未就绪')
                if not {(ref['id'], ref['sha256']) for ref in context['input_versions']} <= pinned:
                    raise ValueError('镜头上下文输入未全部钉在 run 批准版本中')
                if modality == 'audio':
                    _, coverage_ref = audio_binding(project, context, logical)
                    if (coverage_ref['id'], coverage_ref['sha256']) not in pinned:
                        raise ValueError('对白覆盖计划未钉在 run 批准版本中')
                media = {ref['media_id']: ref for ref in context['media_references']}
                if any(ref not in media for ref in logical.reference_media_ids):
                    raise ValueError('请求引用了未批准的镜头媒体')
                needed = 'audio' if modality == 'audio' else 'image'
                if any(media[ref]['modality'] != needed for ref in logical.reference_media_ids):
                    raise ValueError('参考媒体模态与请求不符')
                for field, role in (('first_frame_media_id', 'first_frame'), ('last_frame_media_id', 'last_frame'),
                                    ('voice_media_id', 'voice_sample')):
                    ref = getattr(logical, field, None)
                    if ref and (ref not in media or media[ref]['role'] != role):
                        raise ValueError(field + ' 缺有效用途绑定')
            if modality == 'image' and (type(logical.width) is not int or logical.width < 1
                                        or type(logical.height) is not int or logical.height < 1):
                raise ValueError('图片尺寸无效')
            key = operation(job)
            if key in operations:
                raise ValueError('同一镜头用途与候选编号重复')
            operations[key] = units(job)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f'series_batch.jobs[{index}]：{exc}')
    if set(operations) != set(data['operations']):
        errors.append('run.operations 与系列任务列表不一致')
    else:
        from vsc_budget import units as normalise
        for key, value in operations.items():
            try:
                if normalise(data['operations'][key]) != normalise(value):
                    errors.append('系列任务原生单位与批准上限不一致：' + key)
            except ValueError as exc:
                errors.append(str(exc))
    return errors
