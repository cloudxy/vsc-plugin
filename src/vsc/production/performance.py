"""Executable professional handoff checks, independent of persistence or providers.

Identity/media references live in the typed execution relations. Parameters here
describe observable performance; compiling them never claims the model can do it.
"""
import json
import math

DOMAINS = frozenset({'combat', 'dance', 'vfx', 'voice'})
ROUTES = frozenset({'generation', 'live', '2d', '3d', 'composite'})
FIELDS = {
    'combat': ('purpose', 'distance', 'direction', 'attack_defense', 'support_foot', 'force', 'after_state'),
    'dance': ('phrase', 'orientation', 'formation', 'path', 'synchronization', 'camera', 'retiming'),
    'vfx': ('trigger', 'world_rule', 'trajectory', 'contact', 'occlusion', 'light_response', 'environment_response', 'aftereffects', 'sound'),
    'voice': ('pronunciation', 'accent', 'rate', 'breath', 'emotion', 'delivery', 'overlap', 'processing', 'intelligibility', 'sync_criterion'),
}
COMBAT_PHASES = ('preparation', 'initiation', 'contact', 'reaction', 'recovery')


def _chain_problems(chain):
    """Optional causal graph, with explicit instance identities rather than roles."""
    if not isinstance(chain, list) or len(chain) < 2:
        return ['combat chain 必须至少有两个动作节点']
    errors, nodes = [], {}
    for node in chain:
        if not isinstance(node, dict):
            errors.append('chain 节点必须为对象')
            continue
        key = node.get('id')
        if not isinstance(key, str) or not key.strip() or key in nodes:
            errors.append('chain.id 必须非空且唯一')
            continue
        nodes[key] = node
        actor, other = node.get('actor_instance'), node.get('counterpart_instance')
        if any(not isinstance(v, str) or not v.strip() for v in (actor, other)) or actor == other:
            errors.append('chain 必须明确两个不同的 actor_instance/counterpart_instance')
        after = node.get('after')
        if not isinstance(after, list) or any(not isinstance(x, str) or not x.strip() for x in after) or len(set(after)) != len(after):
            errors.append('chain.after 必须为不重复的前驱ID数组')
        phases = node.get('phases')
        if not isinstance(phases, list) or [p.get('phase') if isinstance(p, dict) else None for p in phases] != list(COMBAT_PHASES):
            errors.append('chain 每招必须依序含五相位')
        elif any(not isinstance(p.get('action'), str) or not p['action'].strip() for p in phases):
            errors.append('chain 每相位须有可观察 action')
        if 'start_seconds' in node or 'end_seconds' in node:
            start, end = node.get('start_seconds'), node.get('end_seconds')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
                errors.append('chain 节点时间须为非负起点和更晚的有限结束秒数')
    edges = {}
    for key, node in nodes.items():
        after = node.get('after')
        if not isinstance(after, list) or any(not isinstance(x, str) for x in after):
            continue
        edges[key] = after
        for prior in after:
            if prior not in nodes:
                errors.append('chain 前驱不存在：' + prior)
            elif all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                     for v in (nodes[prior].get('end_seconds'), node.get('start_seconds'))):
                if nodes[prior]['end_seconds'] > node['start_seconds']:
                    errors.append('chain 因果节点不能早于前驱结束')
    indegree = {key: sum(prior in nodes for prior in edges.get(key, [])) for key in nodes}
    followers = {key: [] for key in nodes}
    for key, after in edges.items():
        for prior in after:
            if prior in nodes:
                followers[prior].append(key)
    ready, visited = [key for key, count in indegree.items() if not count], 0
    while ready:
        key = ready.pop()
        visited += 1
        for follower in followers[key]:
            indegree[follower] -= 1
            if not indegree[follower]:
                ready.append(follower)
    if visited != len(nodes):
        errors.append('chain 前驱不能成环')
    return errors


def participant_problems(domain, parameters, participants):
    """Use resolved existing instance IDs; same-role participants remain distinct."""
    if domain != 'combat' or 'chain' not in parameters:
        return []
    if not isinstance(participants, list) or any(not isinstance(p, dict) for p in participants):
        return ['chain participants 必须为数组']
    identifiers = [p.get('instance') for p in participants]
    if any(not isinstance(x, str) or not x for x in identifiers) or len(set(identifiers)) != len(identifiers):
        return ['chain participants 必须明确不重复的参与实例']
    identities = [p['identity'] for p in participants if p.get('identity')]
    if len(set(identities)) != len(identities):
        return ['chain 不同参与实例不能隐式复制同一身份；须先明确不同身份规格']
    return ['chain 节点引用未登记参与实例：' + str(node.get(field))
            for node in parameters.get('chain', []) if isinstance(node, dict)
            for field in ('actor_instance', 'counterpart_instance') if node.get(field) not in identifiers]


def execution_problems(domain, parameters):
    """Reject incomplete professional specs before relational registration."""
    if domain not in DOMAINS:
        return ['未知专业执行 domain']
    if not isinstance(parameters, dict):
        return ['专业执行 parameters 必须为对象']
    errors = []
    for key in ('purpose', 'acceptance', 'fallback') + FIELDS[domain]:
        value = parameters.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(domain + ' 缺少可执行 ' + key)
    if parameters.get('route') not in ROUTES:
        errors.append('route 必须明确 generation/live/2d/3d/composite')
    if domain == 'combat':
        phases = parameters.get('phases')
        required = list(COMBAT_PHASES)
        if not isinstance(phases, list) or [p.get('phase') if isinstance(p, dict) else None for p in phases] != required:
            errors.append('combat phases 必须依序包含准备、发起、接触、反应、恢复')
        else:
            for phase in phases:
                for key in ('actor_role', 'action', 'counterpart_role'):
                    if not isinstance(phase.get(key), str) or not phase[key].strip():
                        errors.append('combat phase 缺少 ' + key)
        if 'chain' in parameters:
            errors.extend(_chain_problems(parameters['chain']))
    if domain == 'dance':
        beats = parameters.get('beats')
        if not isinstance(beats, list) or not beats:
            errors.append('dance 必须有可定位 beats')
        else:
            last = -1
            for beat in beats:
                seconds = beat.get('seconds') if isinstance(beat, dict) else None
                if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= last:
                    errors.append('dance beats.seconds 须递增且为非负有限秒数')
                else:
                    last = seconds
                if not isinstance(beat, dict) or not isinstance(beat.get('pose'), str) or not beat['pose'].strip():
                    errors.append('dance beat 缺少关键姿态 pose')
    if domain == 'vfx':
        layers = parameters.get('layers')
        if not isinstance(layers, list) or not layers:
            errors.append('vfx 必须明确 layers 和合成用途')
        else:
            for layer in layers:
                if not isinstance(layer, dict) or any(not isinstance(layer.get(k), str) or not layer[k].strip() for k in ('name', 'purpose', 'occlusion')):
                    errors.append('vfx layer 需要 name/purpose/occlusion')
    if domain == 'voice':
        duration = parameters.get('target_seconds')
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
            errors.append('voice target_seconds 必须为正数；实测时长另由媒体探测记录')
        if parameters.get('delivery') not in {'speech', 'whisper', 'shout', 'singing', 'nonverbal'}:
            errors.append('voice delivery 必须明确 speech/whisper/shout/singing/nonverbal')
        controls = parameters.get('controls', [])
        if not isinstance(controls, list) or any(not isinstance(c, dict) or not isinstance(c.get('field'), str) or not isinstance(c.get('model_default'), str) or 'expected' not in c for c in controls):
            errors.append('voice controls 须明确field/model_default/expected，不向台词添加指令')
    return errors


def prompt_fragment(domain, parameters):
    """Stable literal required in a generation request; no provider hidden fields."""
    problems = execution_problems(domain, parameters)
    if problems:
        raise ValueError('; '.join(problems))
    return 'VSC ' + domain + ' execution: ' + json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def voice_control_problems(parameters, model, voice_spec_id, voices):
    """Check actual model defaults while leaving the spoken prompt untouched."""
    if not any(voice.get('id', voice.get('voice_spec_id')) == voice_spec_id for voice in voices):
        return ['专业配音声线与真实角色声线不一致']
    caps = model.get('capabilities', {}) if model else {}
    if parameters['delivery'] not in caps.get('voice_deliveries', ['speech']):
        return ['当前模型未支持该配音表演控制；改设计、实录或后期路线']
    controls = parameters.get('controls', [])
    fields = {control.get('field') for control in controls if isinstance(control, dict)}
    required = {'rate'} | ({'delivery'} if parameters['delivery'] != 'speech' else set())
    if not required <= fields:
        return ['专业配音必须把语速及非普通delivery绑定真实模型控制']
    declared = caps.get('performance_controls', {})
    coverage = performance_payload_coverage(parameters, model)
    for control, row in zip(controls, coverage['controls']):
        key = control.get('model_default')
        if declared.get(control.get('field')) != key or not row['consumed']:
            return ['配音控制未匹配模型已声明并实际消费的默认参数']
    return []


def performance_payload_coverage(parameters, model, payload=None):
    """B4-02：逐项对照表演控制与最终 TTS payload 字段，输出 已消费/未消费/缺口。

    纯函数：不做决定，只列事实，供提交前界面与审阅展示"哪些要求由什么承担"。
    """
    caps = model.get("capabilities", {}) if isinstance(model, dict) else {}
    defaults = model.get("default_params", {}) if isinstance(model, dict) else {}
    parameters = parameters if isinstance(parameters, dict) else {}
    controls = parameters.get("controls", [])
    if payload is None:
        from vsc.adapters.providers.volc_ark.provider import audio_request_payload
        payload = audio_request_payload("", "", defaults)
    req = payload.get("req_params", {})
    effective = dict(req.get("audio_params", {}))
    additions = req.get("additions", {})
    try:
        additions = json.loads(additions) if isinstance(additions, str) else additions
    except (ValueError, TypeError):
        additions = {}
    if isinstance(additions, dict) and "context_texts" in additions:
        effective["context_texts"] = additions["context_texts"]
    rows = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        field, key, expected = control.get("field"), control.get("model_default"), control.get("expected")
        consumed = (caps.get("performance_controls", {}).get(field) == key
                    and key in effective and effective[key] == expected)
        rows.append({"field": field, "model_default": key, "expected": expected,
                     "configured": defaults.get(key), "actual": effective.get(key), "consumed": consumed})
    unsupported = [name for name in ("emotion", "breath", "accent", "pronunciation")
                   if parameters.get(name) and name not in caps.get("performance_controls", {})]
    return {"controls": rows,
            "declared_performance_controls": sorted(caps.get("performance_controls", {})),
            "fields_without_model_control": unsupported,
            "evidence": "compiled_request",
            "payload_note": "按实际TTS请求编译器对照 speech_rate/context_texts；这里只证明请求映射，表演效果仍需审听"}
