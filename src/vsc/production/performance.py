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
        required = ['preparation', 'initiation', 'contact', 'reaction', 'recovery']
        if not isinstance(phases, list) or [p.get('phase') if isinstance(p, dict) else None for p in phases] != required:
            errors.append('combat phases 必须依序包含准备、发起、接触、反应、恢复')
        else:
            for phase in phases:
                for key in ('actor_role', 'action', 'counterpart_role'):
                    if not isinstance(phase.get(key), str) or not phase[key].strip():
                        errors.append('combat phase 缺少 ' + key)
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
    for control in controls:
        key = control.get('model_default')
        if declared.get(control.get('field')) != key or key not in model.get('default_params', {}) or model['default_params'][key] != control.get('expected'):
            return ['配音控制未匹配模型已声明并实际消费的默认参数']
    return []


def performance_payload_coverage(parameters, model):
    """B4-02：逐项对照表演控制与最终 TTS payload 字段，输出 已消费/未消费/缺口。

    纯函数：不做决定，只列事实，供提交前界面与审阅展示"哪些要求由什么承担"。
    """
    caps = model.get("capabilities", {}) if isinstance(model, dict) else {}
    defaults = model.get("default_params", {}) if isinstance(model, dict) else {}
    controls = parameters.get("controls", []) if isinstance(parameters, dict) else []
    rows = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        field, key, expected = control.get("field"), control.get("model_default"), control.get("expected")
        consumed = key in defaults and defaults.get(key) == expected
        rows.append({"field": field, "model_default": key, "expected": expected,
                     "actual": defaults.get(key), "consumed": consumed})
    unsupported = [name for name in ("emotion", "breath", "accent", "pronunciation")
                   if parameters.get(name) and name not in caps.get("performance_controls", {})]
    return {"controls": rows,
            "declared_performance_controls": sorted(caps.get("performance_controls", {})),
            "fields_without_model_control": unsupported,
            "payload_note": "最终豆包 payload 实际消费 speech_rate 与 context_texts；未列出的专业字段由表演记录/审听承担，不进入请求"}
