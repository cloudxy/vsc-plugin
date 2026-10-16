"""Bounded pre-animatic experiments using existing pilot and run decisions."""
from pathlib import Path

from vsc.knowledge import learning
from vsc.project.artifacts import validate_artifact


def validation_errors(data):
    if data.get('phase') != 'trial':
        return ['trial 规格只能用于 phase=trial'] if 'trial' in data else []
    trial = data.get('trial')
    if not isinstance(trial, dict):
        return ['phase=trial 需要 trial 规格']
    errors = []
    if not data.get('batch') or data.get('series_batch') or data.get('audio_request'):
        errors.append('本地 trial 只支持明确 batch 图像／视频，不能绕过其他存储权威')
    for key in ('trial_id', 'context_sha256', 'method_sha256', 'hypothesis', 'criteria', 'stop_condition'):
        if not isinstance(trial.get(key), str) or not trial[key].strip():
            errors.append('trial.' + key + ' 必须非空')
    if type(trial.get('max_remote_jobs')) is not int or trial['max_remote_jobs'] < 1:
        errors.append('trial.max_remote_jobs 必须为正整数')
    for key in ('allowed_shot_ids', 'allowed_asset_ids'):
        value = trial.get(key)
        if (not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value)
                or (all(isinstance(v, str) for v in value) and len(set(value)) != len(value))):
            errors.append('trial.' + key + ' 必须为非空唯一 ID 数组')
    if not data.get('quality_plan'):
        errors.append('trial 必须绑定 quality_plan')
    return errors


def project_errors(data, project, state, item, plan, approved):
    if data.get('phase') != 'trial':
        return []
    errors = validation_errors(data)
    if errors:
        return errors
    if state.get('profile_snapshot', {}).get('storage_policy'):
        return ['本地 trial 不得用于数据库权威项目；使用该权威的试片入口']
    config = data['trial']
    trial = next((row for row in state.get('learning', {}).get('trials', []) if row['id'] == config['trial_id']), None)
    capability = next((row for row in state.get('learning', {}).get('capabilities', [])
                       if trial and row['id'] == trial.get('capability_id')), None)
    if not trial or not capability:
        return ['trial 必须绑定 context build --pilot 建立的真实试用']
    if capability.get('status') not in ('pilot', 'approved') or not capability.get('decision'):
        errors.append('trial 方法必须经过真实 pilot 决定且未退役')
    if trial.get('context_sha256') != config['context_sha256'] or trial.get('method_sha256') != config['method_sha256']:
        errors.append('trial 上下文或方法摘要不匹配')
    errors.extend(learning.capability_source_problems(project, state, capability,
                                                     lambda path: learning.file_digest(path)[:16]))
    errors.extend(learning.context_problems(project, state, trial, capability, validate_artifact,
                                            lambda path: learning.file_digest(path)[:16]))
    pinned = {(a['id'], a['sha256']) for a in approved}
    if not {(ref['id'], ref['sha256']) for ref in trial.get('input_versions', [])} <= pinned:
        errors.append('trial 全部上下文输入必须列为 run 的固定批准依赖')
    kinds = {a['type'] for a in approved}
    if not {'vsc.screenplay', 'vsc.asset_bible', 'vsc.shot_plan'} <= kinds:
        errors.append('trial 需要批准 screenplay、asset_bible 与 shot_plan')
    if len(plan['jobs']) > config['max_remote_jobs']:
        errors.append('trial 任务数超过限定次数')
    allowed_shots, allowed_assets = set(config['allowed_shot_ids']), set(config['allowed_asset_ids'])
    known_shots, known_assets = set(), set()
    for artifact in approved:
        if artifact['type'] not in ('vsc.shot_plan', 'vsc.asset_bible'):
            continue
        import json
        body = json.loads((Path(project) / artifact['path']).read_text('utf-8'))
        if artifact['type'] == 'vsc.shot_plan':
            known_shots.update(row['id'] for row in body.get('shots', []))
        else:
            known_assets.update(row['id'] for row in body.get('entities', []))
    if not allowed_shots <= known_shots or not allowed_assets <= known_assets:
        errors.append('trial 限定镜头／资产不属于批准规格')
    if data.get('scope') != 'project':
        from vsc.production.handoffs import _within
        objects = {row['id']: row for row in state.get('objects', [])}
        if any(not _within(objects, shot, data['scope']) for shot in allowed_shots):
            errors.append('trial 限定镜头超出 run.scope')
    from vsc.story import consistency
    import json
    for job in plan['jobs']:
        args = job['args']
        if args.get('shot') not in allowed_shots or not args.get('bible') or not args.get('state'):
            errors.append('trial 每个任务须绑定限定镜头及资产／状态：' + job['id'])
            continue
        if job['kind'] == 'image' and args.get('purpose') != 'candidate':
            errors.append('trial 图像只能作为镜头试片候选，资产母版准备走 asset phase')
        bible = json.loads((Path(project) / args['bible']['path']).read_text('utf-8'))
        scene = json.loads((Path(project) / args['state']['path']).read_text('utf-8'))
        pack = consistency.anchor_pack(bible, scene, args['shot'])
        used = set(pack['entities']) | {pack['location']['id']}
        if not used <= allowed_assets:
            errors.append('trial 镜头引用超出限定资产：' + job['id'])
    return errors


def adoption_errors(data, project, state, item):
    """Re-use the normal selected-takes approval, with explicit trial adoption."""
    artifacts = {row['id']: row for row in state.get('artifacts', [])}
    trial_refs = set()
    for selection in data.get('items', []):
        source = selection.get('source', {}).get('artifact', {})
        artifact = artifacts.get(source.get('id'), {})
        run = artifacts.get(artifact.get('run_id'), {})
        if not run:
            continue
        import json
        try:
            body = json.loads((Path(project) / run['path']).read_text('utf-8'))
        except (OSError, ValueError):
            return ['试片来源 run 无法读取，不能推定为正式候选']
        if body.get('phase') == 'trial':
            trial_refs.add((source.get('id'), source.get('sha256')))
    if not trial_refs:
        return []
    errors = []
    adoptions = data.get('trial_adoptions', [])
    if not isinstance(adoptions, list):
        return ['trial_adoptions 必须列明本次正式采用的试片来源和理由']
    declared = set()
    for adoption in adoptions:
        if not isinstance(adoption, dict) or not isinstance(adoption.get('reason'), str) or not adoption['reason'].strip():
            errors.append('trial_adoptions 每项必须给出采用理由')
            continue
        ref = adoption.get('artifact', {})
        if not isinstance(ref, dict) or not isinstance(ref.get('id'), str) or not isinstance(ref.get('sha256'), str):
            errors.append('trial_adoptions 来源版本无效')
            continue
        declared.add((ref['id'], ref['sha256']))
    if declared != trial_refs:
        errors.append('试片不能直接正式采用；selected-takes 须显式列出准确 trial_adoptions')
    from vsc.project.state import gate_problems
    errors.extend('试片正式采用需满足 animatic Gate：' + error for error in
                  gate_problems(Path(project), state, 'animatic', None if item.get('scope', 'project') == 'project' else item['scope']))
    return errors
