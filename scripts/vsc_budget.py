#!/usr/bin/env python3
"""Project-wide native-unit budget, atomic reservations and uncertain submissions."""
import argparse
import contextlib
import fcntl
import json
import math
import uuid
from pathlib import Path

UNITS = ('remote_jobs', 'images', 'video_seconds', 'speech_chars', 'audio_jobs', 'vision_jobs')


class BudgetError(ValueError):
    pass


def units(value):
    if not isinstance(value, dict) or set(value) - set(UNITS):
        raise BudgetError('预算只接受原生单位：' + ', '.join(UNITS))
    if any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 for n in value.values()):
        raise BudgetError('预算单位必须是有限非负数')
    return {key: value.get(key, 0) for key in UNITS}


@contextlib.contextmanager
def ledger(project):
    from vsc_state import write_json
    root = Path(project).resolve() / '.vsc-budget'
    if root.is_symlink():
        raise BudgetError('预算目录不能是符号链接')
    root.mkdir(exist_ok=True)
    with (root / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / 'ledger.json'
        if path.is_symlink():
            raise BudgetError('预算台账不能是符号链接')
        data = json.loads(path.read_text('utf-8')) if path.exists() else {
            'format': 'vsc.project-budget/v1', 'limits': None, 'reservations': {}, 'history': []}
        yield data
        write_json(path, data)


def configure(project, limits, by, reason):
    limits = units(limits)
    if not by.strip() or not reason.strip():
        raise BudgetError('配置预算需真实负责人和理由')
    with ledger(project) as data:
        totals = usage(data)
        if any(totals[k] > limits[k] for k in UNITS):
            raise BudgetError('新上限低于已占用额度，不能抹掉历史')
        data['history'].append({'limits': data['limits'], 'by': by, 'reason': reason})
        data['limits'] = limits


def usage(data):
    total = dict.fromkeys(UNITS, 0)
    for item in data['reservations'].values():
        amount = item.get('actual_units') if item['status'] == 'settled' else item['bound']
        if item['status'] == 'cancelled':
            continue
        for key, value in amount.items():
            total[key] += value
    return total


def reserve(project, run_id, operation, bound):
    return reserve_many(project, run_id, {operation: bound})[operation]


def reserve_many(project, run_id, operations):
    from vsc_state import project_state
    from vsc_artifacts import validate_artifact
    state = project_state(Path(project))
    artifact = next((a for a in state['artifacts'] if a['id'] == run_id), None)
    if not artifact or artifact['type'] != 'vsc.production_run' or validate_artifact(project, state, artifact):
        raise BudgetError('预留额度必须绑定有效已批准 production_run')
    run = json.loads((Path(project) / artifact['path']).read_text('utf-8'))
    allowed = run.get('operations', {})
    requested = {key: units(value) for key, value in operations.items()}
    if any(key not in allowed or units(allowed[key]) != value for key, value in requested.items()):
        raise BudgetError('操作与单位上限必须出现在已批准 run.operations 中')
    with ledger(project) as data:
        if data['limits'] is None:
            raise BudgetError('先配置项目共享预算')
        occupied = usage(data)
        result, pending = {}, {}
        for operation, bound in requested.items():
            old = [(key,value) for key,value in data['reservations'].items()
                   if value['run_id'] == run_id and value['operation'] == operation]
            if old:
                key, value = old[0]
                if value['bound'] != bound: raise BudgetError('旧预留输入已漂移')
                result[operation] = key
                continue
            for key in UNITS: occupied[key] += bound[key]
            identifier = 'BR-' + uuid.uuid4().hex
            result[operation] = identifier
            pending[identifier] = {'run_id': run_id, 'operation': operation,
                'bound': bound, 'status': 'reserved', 'currency_cost': None, 'scope':run.get('scope','project')}
            batch = run.get('batch')
            if batch:
                source = json.loads((Path(project) / batch['path']).read_text('utf-8'))
                job = next((j for j in source['jobs'] if f"{j['kind']}:{j['args']['out']}/{j['args']['name']}" == operation), {})
                pending[identifier]['shot_id'] = job.get('args', {}).get('shot')
            else:
                binding = run.get('audio_request', {}).get('binding', {})
                pending[identifier]['line_id'] = binding.get('inputs', {}).get('line_id')
        if any(occupied[k] > data['limits'][k] for k in UNITS):
            raise BudgetError('项目共享预算不足（含未知提交和弃用候选）')
        # Commit the complete set or none; no partial holds after a failed batch.
        data['reservations'].update(pending)
        return result


def check_authorization(project, reservation_id, operation, required=None, request=None):
    """Called immediately before a paid POST, once. GET/download resume is free."""
    state_path = Path(project) / 'vsc.json'
    state = json.loads(state_path.read_text('utf-8'))
    if state.get('profile_snapshot', {}).get('contract_policy') != 'production-v2' and not reservation_id:
        return  # explicit legacy compatibility; no managed-budget claim
    with ledger(project) as data:
        item = data['reservations'].get(reservation_id)
        if not item or item['operation'] != operation or item['status'] != 'reserved':
            raise BudgetError('付费提交缺有效共享预算预留；查看 vsc_budget.py status 和已批准 production_run')
        if required and any(units(required)[k] > item['bound'][k] for k in UNITS):
            raise BudgetError('请求超过预留原生单位')
        # Recheck upstream approval at submission, not merely at reservation.
        from vsc_state import project_state
        from vsc_artifacts import validate_artifact
        state = project_state(Path(project))
        artifact = next(a for a in state['artifacts'] if a['id'] == item['run_id'])
        if validate_artifact(project, state, artifact):
            raise BudgetError('预留所依赖的正式 run 已失效')
        run = json.loads((Path(project) / artifact['path']).read_text('utf-8'))
        if request is None:
            raise BudgetError('正式付费提交必须核对请求参数')
        if run.get('audio_request'):
            if request != run['audio_request']['binding']:
                raise BudgetError('音频请求与已批准 run 的绑定不一致')
        else:
            import vsc_production as production
            plan = production.build_plan(project, production.read(Path(project) / run['batch']['path']))
            jobs = {j['id']: j for j in plan['jobs']}
            from vsc_run import operation as job_operation
            job = next((j for j in plan['jobs'] if job_operation(j) == operation), None)
            if job is None: raise BudgetError('操作不在已批准 batch 中')
            argv, _ = production.resolve_args(project, job, jobs)
            expected = {}
            i = 3  # kind --project PATH
            while i < len(argv):
                token = argv[i][2:]
                if '=' in token:
                    key, value = token.split('=', 1)
                elif token.replace('-', '_') in production.MULTI:
                    key, value = token, argv[i+1]; i += 1
                else:
                    key, value = token, True
                key = key.replace('-', '_')
                if key in production.MULTI: expected.setdefault(key, []).append(value)
                else: expected[key] = value
                i += 1
            semantic_keys = production.COMMON | (production.IMAGE if job['kind'] == 'image' else production.VIDEO)
            for key in semantic_keys:
                if key not in job['args']:
                    if request.get(key) not in (None, [], False):
                        raise BudgetError('提交增加了未批准的参数：' + key)
                    continue
                value = job['args'][key]
                want = expected.get(key, False if type(value) is bool else [] if isinstance(value, list) else None)
                actual = request.get(key)
                if isinstance(want, list): actual = [str(v) for v in actual or []]
                elif not isinstance(want, bool): actual = str(actual)
                if actual != want:
                    raise BudgetError('提交参数与已批准任务不一致：' + key)
        item['status'] = 'submitted_unknown'


def settle(project, identifier, actual=None, evidence=None):
    with ledger(project) as data:
        item = data['reservations'].get(identifier)
        if not item or item['status'] == 'reserved':
            raise BudgetError('未提交的预留不能结算')
        if actual is not None:
            amount = units(actual)
            if not evidence or any(amount[k] > item['bound'][k] for k in UNITS) or amount['remote_jobs'] != item['bound']['remote_jobs']:
                raise BudgetError('结算需用量证据且不能超过预留；超额需人工核账')
            item.update(status='settled', actual_units=amount, evidence=evidence)
        else:
            item.update(status='usage_unknown', evidence=evidence)
        # Currency is deliberately unknown unless independently supplied billing.


def summary(data):
    groups = {'by_scope': {}, 'by_shot': {}, 'by_status': {}}
    for item in data['reservations'].values():
        amount = usage({'reservations': {'item': item}})
        for name, key in (('by_scope', item.get('scope','project')), ('by_shot',item.get('shot_id') or item.get('line_id') or 'unassigned'), ('by_status',item['status'])):
            total = groups[name].setdefault(key, dict.fromkeys(UNITS,0))
            for unit in UNITS: total[unit] += amount[unit]
    return groups


def record_completion(project, identifier, evidence):
    """A verified adapter return may reuse existing bytes without a new POST."""
    with ledger(project) as data:
        item = data['reservations'][identifier]
        if item['status'] == 'reserved':
            item.update(status='cancelled', evidence=evidence, completion='verified_cached_reuse')
            return
        if item['status'] == 'cancelled': return
    settle(project, identifier, evidence=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('configure', 'status', 'reserve', 'settle'))
    parser.add_argument('--project', required=True); parser.add_argument('--units')
    parser.add_argument('--by'); parser.add_argument('--reason'); parser.add_argument('--run')
    parser.add_argument('--operation'); parser.add_argument('--reservation'); parser.add_argument('--evidence')
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            configure(args.project, json.loads(args.units), args.by or '', args.reason or '')
        elif args.command == 'reserve':
            print(reserve(args.project, args.run, args.operation, json.loads(args.units)))
        elif args.command == 'settle':
            settle(args.project, args.reservation, json.loads(args.units) if args.units else None, args.evidence)
        else:
            with ledger(args.project) as data:
                print(json.dumps({**data, 'occupied': usage(data), **summary(data)}, ensure_ascii=False, indent=2))
        return 0
    except (BudgetError, OSError, ValueError, TypeError) as exc:
        print('ERROR: ' + str(exc)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
