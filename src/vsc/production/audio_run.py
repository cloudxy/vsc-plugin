#!/usr/bin/env python3
"""The same formal-run and budget protocol for speech and generated sound."""
import json
from pathlib import Path

from vsc.production import budget as budget
from vsc.adapters.providers import credentials as credentials
from vsc.project.artifacts import digest


def prepare(project, request):
    from vsc.adapters.providers.speech import audio as doubao_audio
    from vsc.adapters.providers.speech import tts as doubao_speech
    if request.get('kind') not in ('speech', 'audio', 'inspect') or not isinstance(request.get('argv'), list):
        raise ValueError('单次请求需要 kind speech|audio|inspect 和 argv 数组')
    if not all(isinstance(a, str) for a in request['argv']): raise ValueError('argv 只能是文本')
    if any(a.split('=')[0] in ('--project','--execute','--budget-reservation') for a in request['argv']):
        raise ValueError('音频请求不能覆盖 project、执行模式或预算预留')
    if request['kind'] == 'inspect':
        from vsc.adapters.providers.volc_ark import api as volc_ark
        args = volc_ark.parser().parse_args(['inspect','--project',str(project),*request['argv']])
        binding, _, _, _ = volc_ark.prepare_inspection(args)
        return volc_ark,args,binding,'inspect:'+binding['inputs']['media']['path'],{'remote_jobs':1,'vision_jobs':1}
    module = doubao_speech if request['kind'] == 'speech' else doubao_audio
    command = 'synthesize' if request['kind'] == 'speech' else 'generate'
    # The parser is shared with the real provider; invalid options fail locally.
    args = module.parser().parse_args([command, '--project', str(project), '--dry-run', *request['argv']])
    project, out, payload, binding = module.plan(args)
    operation = request['kind'] + ':' + str(out.relative_to(project)) + '/' + args.name
    bound = {'remote_jobs':1, **({'speech_chars':len(binding['inputs']['prompt'])} if request['kind']=='speech' else {'audio_jobs':1})}
    return module, args, binding, operation, bound


def project_errors(data, project, state, item):
    errors = []
    try:
        _, _, binding, operation, bound = prepare(project, data['audio_request'])
        if binding != data['audio_request'].get('binding'): errors.append('audio_request 输入/声音版本已漂移')
        if data.get('operations') != {operation: bound}: errors.append('音频 operation 单位与请求不一致')
        from vsc.adapters.providers.speech.tts import digest_json
        if data.get('plan_sha256') != digest_json(binding): errors.append('音频 plan_sha256 不一致')
        approved = []
        for ref in data.get('approved_inputs', []):
            artifact = next((a for a in state['artifacts'] if a['id']==ref.get('id')), None)
            if not artifact or artifact.get('sha256') != ref.get('sha256') or ref['id'] not in item.get('depends_on', []):
                errors.append('音频 approved_inputs 必须绑定明确依赖')
            else: approved.append(artifact)
        required = 'vsc.asset_bible' if data.get('phase') == 'asset' else 'vsc.animatic'
        if not any(a['type']==required for a in approved): errors.append('单次正式请求缺批准输入：'+required)
        for key in ('bible', 'screenplay', 'state'):
            if binding['inputs'].get(key) and binding['inputs'][key]['sha256'] not in {a['sha256'] for a in approved}:
                errors.append(key+' 没有明确批准输入版本')
        if data.get('scope') != item.get('scope', 'project'): errors.append('音频 scope 不一致')
    except (ValueError, OSError, KeyError, SystemExit) as exc:
        errors.append('音频预检失败：'+str(exc))
    return errors


def execute(project, identifier):
    from vsc.production.run import load_run, import_candidate
    from vsc.project.state import gate_problems
    state, item, data = load_run(project, identifier)
    gate = 'script' if data.get('phase') == 'asset' else 'animatic'
    gaps = gate_problems(Path(project), state, gate, None if data['scope']=='project' else data['scope'])
    if gaps: raise ValueError('音频制作质量门未满足：'+'；'.join(gaps))
    module, args, binding, operation, bound = prepare(project, data['audio_request'])
    if data['audio_request']['kind'] == 'inspect':
        # Agent Plan 规则禁止直接调用文本模型；在预留额度之前拒绝，不留占用。
        problem = credentials.text_model_problem()
        if problem: raise ValueError(problem)
    reservation = budget.reserve(project, identifier, operation, bound)
    args.execute = True; args.dry_run = False; args.budget_reservation = reservation
    if data['audio_request']['kind'] == 'inspect':
        from vsc.project.state import project_lock, project_state, next_id, now, append_event, save
        from vsc.project.artifacts import snapshot
        path = module.inspect(args)
        budget.record_completion(project, reservation, evidence=str(path))
        with project_lock(Path(project)):
            state = project_state(Path(project))
            sha = digest(path)
            old = next((a for a in state['artifacts'] if a.get('run_id')==identifier and a['type']=='vsc.visual_check' and a['sha256']==sha),None)
            if not old:
                aid=next_id(state['artifacts'],'A'); fixed,sha=snapshot(project,path,aid)
                state['artifacts'].append({'id':aid,'type':'vsc.visual_check','stage':'design' if data.get('phase')=='asset' else 'production',
                    'scope':item['scope'],'path':fixed,'sha256':sha,'status':'draft','decision':None,
                    'depends_on':[identifier],'dependency_versions':{identifier:item['sha256']},'run_id':identifier,'created_at':now()})
                append_event(state,'visual_check_imported',artifact_id=aid,run_id=identifier);save(Path(project),state)
        return json.loads(Path(path).read_text('utf-8'))
    record = module.synthesize(args) if data['audio_request']['kind']=='speech' else module.generate(args)
    budget.record_completion(project, reservation, evidence='verified generation record; platform usage unknown')
    job = {'id': args.name, 'args': {'out': args.out, 'name': args.name}}
    # Audio adapters share the generation-record basename with the video adapter.
    import_candidate(project, item, job, record)
    return record
