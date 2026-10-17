"""Consume an optional pinned quality package at the approved-run boundary."""
from pathlib import Path

from vsc.production.quality_plan import _Evidence, check
from vsc.knowledge import learning
from vsc.project.artifacts import validate_artifact


def quality_errors(data, project, state, item, requests, *, read_ref=None, evaluate_risk=None):
    """Validate coverage against actual fixed requests, for local and PG callers.

    requests maps stable run job IDs to their exact logical request dictionaries.
    No mutation, provider call, authority decision, or project mirror is made.
    """
    if not data.get('quality_plan'):
        return ['trial 必须绑定 quality_plan'] if data.get('phase') == 'trial' else []
    errors = []
    evidence = _Evidence(project, errors, read_ref)
    package = evidence.read(data['quality_plan'], 'run.quality_plan', structured=True)
    if not isinstance(package, dict):
        return errors or ['quality_plan 必须是 JSON 对象']
    if package.get('project_id') != data.get('project_id'):
        errors.append('quality_plan 项目不匹配')
    binding = package.get('run_binding', {})
    if not isinstance(binding, dict) or binding.get('plan_sha256') != data.get('plan_sha256'):
        errors.append('quality_plan 未绑定当前 run.plan_sha256')
    job_ids = binding.get('job_ids') if isinstance(binding, dict) else None
    if not isinstance(job_ids, list) or any(not isinstance(key, str) for key in job_ids):
        errors.append('quality_plan.run_binding.job_ids 必须列明全部任务')
    elif len(set(job_ids)) != len(job_ids) or set(job_ids) != set(requests):
        errors.append('quality_plan 任务范围与实际 run 不一致')
    report = check(package, project, read_ref=read_ref)
    errors.extend(report['problems'])
    if any(row['recommendation'] == 'stop_and_compare_routes' for row in report['rework']):
        errors.append('quality_plan 同类失败达到阈值，停止原路线')
    inputs = package.get('inputs', [])
    inputs = inputs if isinstance(inputs, list) else []
    covered_jobs, request_input_ids = set(), set()
    for row in inputs:
        if not isinstance(row, dict) or row.get('channel') != 'request':
            continue
        job_id = row.get('job_id')
        if not isinstance(job_id, str) or job_id not in requests:
            errors.append('quality_plan request input 缺少真实 job_id')
            continue
        actual = evidence.read(row.get('ref'), 'quality_plan request ' + job_id, structured=True)
        if actual != requests[job_id]:
            errors.append('quality_plan 请求内容未匹配实际固定输入：' + job_id)
        else:
            covered_jobs.add(job_id)
            if isinstance(row.get('id'), str):
                request_input_ids.add(row['id'])
    if covered_jobs != set(requests):
        errors.append('quality_plan 未覆盖全部实际请求')
    pinned = {ref.get('sha256') for ref in data.get('approved_inputs', []) if isinstance(ref, dict)}
    requirements = package.get('requirements', [])
    requirements = requirements if isinstance(requirements, list) else []
    required_jobs = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or requirement.get('priority') != 'must':
            continue
        source = requirement.get('source', {})
        if not isinstance(source, dict) or source.get('sha256') not in pinned:
            errors.append('quality_plan 必要要求来源不属于 run 批准输入')
        links = requirement.get('bindings', [])
        links = links if isinstance(links, list) else []
        linked = {link.get('input_id') for link in links if isinstance(link, dict) and isinstance(link.get('input_id'), str)}
        if not linked & request_input_ids:
            errors.append('quality_plan 必要要求未覆盖实际请求字段')
        required_jobs.update(row['job_id'] for row in inputs if isinstance(row, dict)
                             and isinstance(row.get('id'), str)
                             and row['id'] in linked and row['id'] in request_input_ids)
    if required_jobs != set(requests):
        errors.append('quality_plan 每个实际任务至少需要一项必要要求')
    # A trial is precisely the authorized experiment for its unproven risks.
    # Production may use valid existing evaluations, never a standalone pass label.
    resolved_risks = set()
    for risk in package.get('risks', []) if isinstance(package.get('risks', []), list) else []:
        if not isinstance(risk, dict):
            continue
        if data.get('phase') == 'trial':
            resolved_risks.add(str(risk.get('id')))
            continue
        ref = risk.get('evaluation_ref')
        if not ref:
            continue
        evaluation = evidence.read(ref, 'quality_plan risk evaluation', structured=True)
        if not isinstance(evaluation, dict):
            continue
        if evaluate_risk is not None:
            problems = evaluate_risk(risk, evaluation)
            errors.extend('quality_plan 风险评测：' + problem for problem in problems)
            if not problems:
                resolved_risks.add(str(risk.get('id')))
            continue
        capability = next((c for c in state.get('learning', {}).get('capabilities', [])
                           if any(ev == evaluation for ev in c.get('evaluations', []))), None)
        if not capability or evaluation.get('result') != 'pass':
            errors.append('quality_plan 风险评测不属于项目真实 pass 记录')
            continue
        problems = learning.evaluation_problems(project, state, capability, evaluation,
                                                validate_artifact, lambda path: learning.file_digest(path)[:16])
        errors.extend('quality_plan 风险评测：' + problem for problem in problems)
        if not problems:
            resolved_risks.add(str(risk.get('id')))
    for unknown in report['unknowns']:
        if not any(unknown.startswith(identifier + ':') for identifier in resolved_risks):
            errors.append('quality_plan 尚有未决证据：' + unknown)
    return errors
