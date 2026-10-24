"""Read-only run pricing over the same normalized jobs, model registry and units."""
from sqlalchemy import text
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.production.quotes import fingerprint, quote_request, quote_errors, quote_policy_errors
from vsc.production.run_authorization import normalize_request, validate_capabilities
from .budget_store import native_units, operation_key
from .values import checked_id, clean


def run_quote(store, conn, project, jobs):
    if not isinstance(jobs, list) or not jobs or len(jobs) > 200:
        raise ResourceError('报价需要1至200个固定任务', 'invalid_generation_quote')
    result, totals, native, operations = [], {}, {}, set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get('request'), dict):
            raise ResourceError('报价任务需要原逻辑request', 'invalid_generation_quote')
        original = job['request']
        asset, shot, purpose, modality = (original.get(key) for key in ('asset_id', 'shot_id', 'purpose', 'modality'))
        if bool(asset) == bool(shot):
            raise ResourceError('报价任务须且仅须指定镜头或资产', 'job_target_required')
        context = (store._compile_asset_context(conn, project, checked_id(asset), purpose) if asset else
                   store._compile_context(conn, project, checked_id(shot), purpose))
        if not context['ready']:
            raise ResourceError('当前固定输入有缺口，不能报价', 'context_gaps')
        if original.get('context_sha256', context['sha256']) != context['sha256']:
            raise Conflict('报价所指固定输入已经改变', 'context_conflict')
        request = normalize_request(original, shot, purpose, modality, asset)
        request['context_sha256'] = context['sha256']
        model, provider = store._generation_model(conn, {'model_id': job.get('model_id'), 'purpose': purpose, 'modality': modality}, lock=False)
        validate_capabilities(dict(model), request, context)
        if request.get('operation'):
            from vsc.production.video_operations import validate_source_metadata
            source, gaps = store._usable(conn, project['id'], checked_id(request['source_media_id']), purpose)
            if gaps:
                raise ResourceError('加工源不可用于此报价', 'operation_source_unusable')
            validate_source_metadata(request, source)
        candidate = job.get('candidate_no', 0)
        if type(candidate) is not int or candidate < 0:
            raise ResourceError('候选编号无效', 'invalid_generation_quote')
        operation = operation_key(request, candidate)
        if operation in operations:
            raise ResourceError('报价任务意图重复', 'invalid_generation_quote')
        operations.add(operation)
        units = native_units(request)
        quote = dict(quote_request(dict(model), request, units), operation=operation)
        result.append(quote)
        for unit, amount in units.items():
            native[unit] = native.get(unit, 0) + amount
        if quote['status'] == 'estimate':
            from decimal import Decimal
            totals[quote['currency']] = totals.get(quote['currency'], Decimal(0)) + Decimal(quote['amount'])
    document = {'format': 'vsc.generation-quote/v1', 'jobs': result, 'native_units': native,
                'all_prices_known': all(row['status'] == 'estimate' for row in result),
                'known_subtotals': {key: str(value) for key, value in totals.items()},
                'unknown_jobs': sum(row['status'] == 'unknown' for row in result)}
    document['quote_sha256'] = fingerprint(document)
    return document


def preview(store, project_id, payload):
    if not isinstance(payload, dict) or set(payload) != {'document'} or not isinstance(payload['document'], dict):
        raise ResourceError('报价需要待授权的运行包document', 'invalid_generation_quote')
    document = payload['document']
    batch = document.get('series_batch', {})
    if not isinstance(batch, dict):
        raise ResourceError('series_batch必须为任务对象', 'invalid_generation_quote')
    jobs = batch.get('jobs', document.get('jobs'))
    with store.engine.connect().execution_options(isolation_level='REPEATABLE READ', vsc_readonly_preview=True) as conn, conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        project = store._project(conn, checked_id(project_id))
        quote = run_quote(store, conn, project, jobs)
        return clean({'project_id': project['id'], 'revision': project['revision'], 'read_only': True,
                      'generation_quote': quote, 'needs_approval': True})


def check_pinned(document, model, request, candidate_no):
    if 'quote_policy' in document and quote_policy_errors(document['quote_policy']):
        raise ResourceError('运行包报价偏差策略无效', 'invalid_generation_quote')
    current = quote_request(dict(model), request, native_units(request))
    pinned = document.get('generation_quote')
    if 'generation_quote' in document:
        if quote_errors(pinned):
            raise ResourceError('运行包固定报价摘要无效', 'invalid_generation_quote')
        operation = operation_key(request, candidate_no)
        rows = [row for row in pinned.get('jobs', []) if row.get('operation') == operation]
        if len(rows) != 1 or rows[0].get('quote_sha256') != current['quote_sha256']:
            raise Conflict('请求、模型或价格已改变，请重新报价并确认运行包', 'generation_quote_stale')
    return current
