#!/usr/bin/env python3
"""Approved production runs: fixed inputs, budget, human pause points and draft imports."""
import argparse
import copy
import json
from pathlib import Path

from vsc.production import production as production
from vsc.production import budget as budget
from vsc.project.artifacts import digest, snapshot, validate_artifact

FORMAT = 'vsc.production-run/v1'


def operation(job):
    return f"{job['kind']}:{job['args']['out']}/{job['args']['name']}"


def job_units(job):
    return {'remote_jobs': 1, **({'images': job['args'].get('count', 1)} if job['kind'] in ('image', 'grok_image') else {'video_seconds': job['args']['source_seconds'] if job['kind'] == 'grok_edit' else job['args']['duration']})}


def validation_errors(data):
    errors = []
    if data.get('format') != FORMAT:
        errors.append('format 必须是 ' + FORMAT)
    for key in ('project_id', 'scope', 'plan_sha256'):
        if not isinstance(data.get(key), str) or not data[key]:
            errors.append(key + ' 必须非空')
    if sum(bool(data.get(key)) for key in ('batch', 'audio_request', 'series_batch')) != 1:
        errors.append('batch、audio_request、series_batch 必须且只能提供一种')
    if data.get('batch') and (not isinstance(data['batch'], dict) or not all(data['batch'].get(k) for k in ('path', 'sha256'))):
        errors.append('batch 必须绑定 path / sha256')
    if data.get('series_batch') and (not isinstance(data['series_batch'], dict) or not isinstance(data['series_batch'].get('jobs'), list)
                                     or not data['series_batch']['jobs']):
        errors.append('series_batch 必须含非空 jobs 数组')
    if not isinstance(data.get('approved_inputs'), list) or not data['approved_inputs']:
        errors.append('approved_inputs 必须列明确版本')
    if not isinstance(data.get('review_after'), list):
        errors.append('review_after 必须是数组')
    if data.get('phase', 'production') not in ('asset', 'production', 'trial'):
        errors.append('phase 必须为asset、production或trial')
    from vsc.production.run_trial import validation_errors as trial_validation
    errors.extend(trial_validation(data))
    if 'quality_plan' in data and (not isinstance(data['quality_plan'], dict)
            or not all(data['quality_plan'].get(key) for key in ('path', 'sha256'))):
        errors.append('quality_plan 必须固定 path / sha256')
    if not isinstance(data.get('operations'), dict) or not data['operations']:
        errors.append('operations 必须给出每个操作的原生单位')
    else:
        try:
            for bound in data['operations'].values(): budget.units(bound)
        except budget.BudgetError as exc: errors.append(str(exc))
    return errors


def project_errors(data, project, state, item):
    errors = validation_errors(data)
    if errors: return errors
    if data.get('series_batch'):
        from vsc.production.series_run import project_errors as series_errors
        from vsc.production.series_run import operation as series_operation
        from vsc.production.run_quality import quality_errors
        return series_errors(data, project, state, item) + quality_errors(data, project, state, item,
            {series_operation(job): job['request'] for job in data['series_batch']['jobs']})
    if data.get('audio_request'):
        from vsc.production.audio_run import project_errors as audio_errors
        from vsc.production.run_quality import quality_errors
        return audio_errors(data, project, state, item) + quality_errors(data, project, state, item,
            {key: data['audio_request']['binding'] for key in data['operations']})
    if data['scope'] != item.get('scope', 'project'):
        errors.append('run scope 与登记范围不一致')
    try:
        path = production.path_in(project, data['batch']['path'])
        if digest(path) != data['batch']['sha256']:
            return errors + ['batch 文件已漂移']
        plan = production.build_plan(project, production.read(path))
        if data['plan_sha256'] != plan['plan_sha256']:
            errors.append('run 计划 SHA 与完整预检不一致')
        expected = {operation(j): job_units(j) for j in plan['jobs']}
        if {k: budget.units(v) for k,v in data['operations'].items()} != {k: budget.units(v) for k,v in expected.items()}:
            errors.append('run.operations 与实际任务及上限不一致')
        required_reviews = {r['job'] for j in plan['jobs'] for key in production.MEDIA & set(j['args'])
                            for r in (j['args'][key] if key in production.MULTI or key == 'keyframe' else [j['args'][key]]) if 'job' in r}
        if not required_reviews <= set(data['review_after']):
            errors.append('生成结果被下游使用前必须声明 review_after 暂停点')
        if set(data['review_after']) - {j['id'] for j in plan['jobs']}:
            errors.append('review_after 引用了未知 job')
        approved = []
        for ref in data['approved_inputs']:
            artifact = next((a for a in state['artifacts'] if a['id'] == ref.get('id')), None)
            if not artifact or artifact.get('sha256') != ref.get('sha256') or ref['id'] not in item.get('depends_on', []):
                errors.append('approved_inputs 必须是 run 明确依赖的固定产物')
            else: approved.append(artifact)
        prerequisite = 'vsc.asset_bible' if data.get('phase') in ('asset', 'trial') else 'vsc.animatic'
        if not any(a['type'] == prerequisite for a in approved):
            errors.append('正式制作缺已批准输入：' + prerequisite)
        if data.get('phase') == 'asset' and any(j['kind'] not in ('image', 'grok_image') or j['args']['purpose'] != 'asset' for j in plan['jobs']):
            errors.append('资产准备批次只允许asset图像，镜头候选应进入production阶段')
        pinned = {a['sha256'] for a in approved}
        # Local plans/bibles/state files must be precisely the approved input bytes.
        for job in plan['jobs']:
            for key in ('bible', 'state'):
                if key in job['args'] and plan['inputs_sha256'].get(job['args'][key]['path']) not in pinned:
                    errors.append(key + ' 未绑定 approved_inputs 的版本')
        from vsc.production.run_trial import project_errors as trial_errors
        errors.extend(trial_errors(data, project, state, item, plan, approved))
        from vsc.production.run_quality import quality_errors
        batch = production.read(path)
        errors.extend(quality_errors(data, project, state, item, {j['id']: j['args'] for j in batch['jobs']}))
    except (OSError, ValueError, KeyError, TypeError, production.ProductionError) as exc:
        errors.append('正式 run 预检失败：' + str(exc))
    return errors


def load_run(project, identifier):
    from vsc.project.state import project_state
    state = project_state(Path(project))
    item = next((a for a in state['artifacts'] if a['id'] == identifier), None)
    if not item or item['type'] != 'vsc.production_run':
        raise ValueError('未找到正式 production_run 产物')
    errors = validate_artifact(project, state, item)
    if errors: raise ValueError('run 无效：' + '；'.join(errors))
    return state, item, production.read(Path(project) / item['path'])


def import_candidate(project, run_item, job, record):
    from vsc.project.state import project_lock, project_state, next_id, now, append_event, save
    source = production.path_in(project, production.record_path(job))
    with project_lock(Path(project)):
        state = project_state(Path(project))
        sha = digest(source)
        old = next((a for a in state['artifacts'] if a.get('run_id') == run_item['id'] and a.get('job_id') == job['id']), None)
        if old:
            if old['sha256'] != sha: raise ValueError('已导入候选记录漂移')
            return old['id']
        identifier = next_id(state['artifacts'], 'A')
        path, sha = snapshot(project, source, identifier)
        item = {'id': identifier, 'type': 'vsc.generation_record', 'stage': 'production', 'path': path,
                'sha256': sha, 'scope': run_item['scope'], 'status': 'draft', 'decision': None,
                'depends_on': [run_item['id']], 'dependency_versions': {run_item['id']: run_item['sha256']},
                'created_at': now(), 'run_id': run_item['id'], 'job_id': job['id']}
        run_data = production.read(Path(project) / run_item['path'])
        if run_data.get('phase') == 'trial':
            item['production_phase'] = 'trial'
            item['trial_id'] = run_data['trial']['trial_id']
            # Existing capability evaluate requires the output to retain all
            # pilot inputs directly, not just an opaque dependency on this run.
            for ref in run_data['approved_inputs']:
                if ref['id'] not in item['depends_on']:
                    item['depends_on'].append(ref['id'])
                    item['dependency_versions'][ref['id']] = ref['sha256']
        state['artifacts'].append(item)
        append_event(state, 'candidate_imported', artifact_id=identifier, run_id=run_item['id'], job_id=job['id'])
        save(Path(project), state)
        return identifier


def execute(project, identifier, runner=None):
    state, item, data = load_run(project, identifier)
    if data.get('series_batch'):
        raise ValueError('系列数据库正式任务须使用 scripts/production/dispatch.py，不可走旧批次队列')
    if data.get('audio_request'):
        from vsc.production.audio_run import execute as execute_audio
        return execute_audio(project, identifier)
    from vsc.project.state import gate_problems, project_state
    gate = 'script' if data.get('phase') in ('asset', 'trial') else 'animatic'
    gaps = gate_problems(Path(project), state, gate, None if data['scope'] == 'project' else data['scope'])
    if gaps: raise ValueError('正式制作质量门未满足：' + '；'.join(gaps))
    # Keep the new opt-in guards explicit even if load_run is adapted by a host.
    if data.get('quality_plan') or data.get('phase') == 'trial':
        problems = project_errors(data, project, state, item)
        if problems: raise ValueError('run 制作前检查未满足：' + '；'.join(problems))
    plan = production.build_plan(project, production.read(Path(project) / data['batch']['path']))
    grok_jobs = [j for j in plan['jobs'] if j['kind'] in production.GROK_KINDS]
    if any(production.completed(project, j) is None for j in grok_jobs):
        from vsc.adapters.providers.xai_grok import api as grok
        grok.base_url()
        grok.api_key()
        grok.grok_credentials.account_sha256(error=grok.GrokError)
    held = budget.reserve_many(project, identifier, {operation(j): job_units(j) for j in plan['jobs']})
    reservations = {j['id']: held[operation(j)] for j in plan['jobs']}

    def approved(job, journal):
        latest = project_state(Path(project))
        matches = [r for r in latest.get('production_reviews', []) if r['run_id'] == identifier and r['job_id'] == job['id']]
        if not matches: return False
        saved = journal['jobs'].get(job['id'], {})
        review = matches[-1]
        return review['outcome'] == 'accepted' and review['outputs_sha256'] == saved.get('outputs_sha256') and review['run_sha256'] == item['sha256']

    def before(job, journal):
        for dep in job['depends_on']:
            if dep in data['review_after'] and not approved({'id': dep}, journal): return None
        return ['--budget-reservation', reservations[job['id']]]

    def after(job, record, journal):
        import_candidate(project, item, job, record)
        reservation = reservations[job['id']]
        # A verified cached result consumes no new paid units.
        budget.record_completion(project, reservation, evidence=production.record_path(job))
        return job['id'] not in data['review_after'] or approved(job, journal)

    return production.run(project, plan, plan['plan_sha256'], runner, before, after, formal=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'plan', 'plan-audio', 'plan-request', 'execute', 'review'))
    parser.add_argument('file_or_id'); parser.add_argument('--project'); parser.add_argument('--scope', default='project')
    parser.add_argument('--input', action='append', default=[]); parser.add_argument('--review-after', action='append', default=[])
    parser.add_argument('--phase', choices=('asset','production','trial'), default='production')
    parser.add_argument('--trial-spec', help='trial 规格 JSON；复用既有 pilot 上下文与 run 批准')
    parser.add_argument('--quality-plan', help='固定质量检查包；绑定本次 plan_sha256 与全部任务')
    parser.add_argument('--job'); parser.add_argument('--by'); parser.add_argument('--reason'); parser.add_argument('--outcome', choices=('accepted','rejected'))
    args = parser.parse_args()
    try:
        if args.command == 'validate':
            errors = validation_errors(production.read(args.file_or_id))
            if errors: raise ValueError('；'.join(errors))
            print('RUN: PASS'); return 0
        if not args.project: raise ValueError('--project 必填')
        if args.command in ('plan', 'plan-audio', 'plan-request'):
            from vsc.project.state import project_state
            state = project_state(Path(args.project))
            extras = {}
            if args.phase == 'trial':
                if args.command != 'plan' or not args.trial_spec or not args.quality_plan:
                    raise ValueError('trial 使用 plan 并明确 --trial-spec 与 --quality-plan')
                extras['trial'] = production.read(args.trial_spec)
            elif args.trial_spec:
                raise ValueError('--trial-spec 仅用于 --phase trial')
            if args.quality_plan:
                quality_path = Path(args.quality_plan).resolve()
                extras['quality_plan'] = {'path': str(quality_path.relative_to(Path(args.project).resolve())),
                                          'sha256': digest(quality_path)}
            if args.command in ('plan-audio','plan-request'):
                from vsc.production.audio_run import prepare
                from vsc.adapters.providers.speech.tts import digest_json
                request = production.read(args.file_or_id)
                _, _, binding, op, bound = prepare(args.project, request)
                refs = [{'id': a['id'], 'sha256': a['sha256']} for a in state['artifacts'] if a['id'] in args.input]
                print(json.dumps({'format': FORMAT, 'project_id': state['project_id'], 'scope': args.scope, 'phase':args.phase,
                    'audio_request': {**request, 'binding': binding}, 'plan_sha256': digest_json(binding),
                    'approved_inputs': refs, 'review_after': [], 'operations': {op: bound}, **extras}, ensure_ascii=False, indent=2))
                return 0
            batch = Path(args.file_or_id).resolve()
            relative = str(batch.relative_to(Path(args.project).resolve()))
            plan = production.build_plan(args.project, production.read(batch))
            refs = [{'id': a['id'], 'sha256': a['sha256']} for a in state['artifacts'] if a['id'] in args.input]
            print(json.dumps({'format': FORMAT, 'project_id': state['project_id'], 'scope': args.scope, 'phase':args.phase,
                  'batch': {'path': relative, 'sha256': digest(batch)}, 'plan_sha256': plan['plan_sha256'],
                  'approved_inputs': refs, 'review_after': args.review_after,
                  'operations': {operation(j): job_units(j) for j in plan['jobs']}, **extras}, ensure_ascii=False, indent=2))
        elif args.command == 'execute':
            print(json.dumps(execute(args.project, args.file_or_id), ensure_ascii=False, indent=2))
        else:
            from vsc.project.state import project_lock, project_state, append_event, now, save
            _, item, data = load_run(args.project, args.file_or_id)
            if not args.by or not args.reason or not args.outcome: raise ValueError('审阅需 --by / --reason / --outcome')
            plan = production.build_plan(args.project, production.read(Path(args.project) / data['batch']['path']))
            job = next(j for j in plan['jobs'] if j['id'] == args.job)
            record = production.completed(args.project, job)
            if not record: raise ValueError('没有可审阅的成功候选')
            with project_lock(Path(args.project)):
                state = project_state(Path(args.project))
                review = {'run_id': item['id'], 'run_sha256': item['sha256'], 'job_id': args.job,
                          'outputs_sha256': {o['path']: o['sha256'] for o in record['outputs']},
                          'by': args.by, 'reason': args.reason, 'outcome': args.outcome, 'at': now()}
                state.setdefault('production_reviews', []).append(review)
                append_event(state, 'production_reviewed', **review); save(Path(args.project), state)
            print('OK 决定已保存；execute 续跑原 run，不自动发布或批准获选素材')
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print('ERROR: ' + str(exc)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
