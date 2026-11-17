"""Canvas operation semantics shared by the catalogue and working-input compiler.

Provider model identities always come from the local registry. An operation in
this catalogue is not a promise that a provider implements it.
"""
from copy import deepcopy

from vsc.assets.resource_service import ResourceError

OPERATION_KEY = 'vsc_operation'


def field(key, label, kind='number', default=None, **limits):
    return dict(key=key, label=label, field_type=kind, default_value=default, **limits)


def port(handle, media_type, minimum=0, maximum=8):
    labels = {'prompt': '文本提示', 'reference': '参考图片', 'first_frame': '首帧',
              'last_frame': '尾帧', 'reference_image': '参考图片', 'reference_video': '参考视频',
              'reference_audio': '参考音频'}
    return dict(handle=handle, label=labels.get(handle, handle), media_type=media_type,
                accept=[media_type], min_count=minimum, max_count=maximum, required=minimum > 0)


# Explicit mappings, rather than remote model aliases or provider-name guesses.
IMAGE_OPERATIONS = {
    'image_three_view': 'three_view', 'image_character_dual_view': 'headshot',
    'image_panorama_generate': 'panorama', 'image_multi_angle': 'angle',
    'image_lighting_generate': 'lighting', 'image_portrait_texture_adjustment': 'texture',
    'image_portrait_emotion_adjustment': 'expression', 'image_face_three_view': 'face_views',
    'image_frame_predict_3s_after': 'frame_predict_3s_after',
    'image_frame_predict_5s_before': 'frame_predict_5s_before',
    'image_cinematic_lighting': 'cinematic_lighting', 'image_multi_camera_grid_2k': 'multi_camera_grid_2k',
    'image_multi_camera_grid_4k': 'multi_camera_grid_4k', 'image_outpaint': 'outpaint',
    'image_story_four_grid': 'story_four_grid', 'image_upscale': 'upscale',
    'image_dewatermark': 'watermark', 'image_matting': 'matting', 'image_inpaint': 'inpaint',
}


def _operations():
    from vsc.production.image_tools import TOOLS
    rows = []

    def add(key, name, kind, *, consumer='work_generation', ports=(), mode=None, reason=None, tool=None, action=None):
        rows.append(dict(op_type=key, name=name, node_type=kind, category=kind,
            operation_role='source' if consumer == 'source' else 'generator',
            consumer=consumer, mode=mode, image_tool=tool, action=action,
            input_ports=list(ports), output_ports=[dict(handle='output', media_type=kind)],
            params_schema=dict(fields=[]), combination_rules={},
            result_ui_policy=dict(regeneratable=consumer == 'work_generation', preserve_original=True),
            camera_options=None, unavailable_reason=reason))

    for kind, name in [('text', '文本'), ('audio', '音频'), ('image', '图片'), ('video', '视频')]:
        add('source_' + kind, name + '素材', kind, consumer='source')
    add('image_generate', '生图', 'image', ports=[port('prompt', 'text', maximum=200), port('reference', 'image')], mode='image')
    for key, tool in IMAGE_OPERATIONS.items():
        add(key, TOOLS[tool][0], 'image', ports=[port('reference', 'image', 1, 1)], mode='image_' + tool, tool=tool)
    for key, name, mode, inputs in [
        ('text_video', '文生视频', 'text', [port('prompt', 'text', maximum=200)]),
        ('single_image_video', '单图生视频', 'single', [port('prompt', 'text', maximum=200), port('first_frame', 'image', 1, 1)]),
        ('seedance_omni_video', '全能参考生视频', 'omni', [port('prompt', 'text', maximum=200), port('reference_image', 'image'), port('reference_video', 'video'), port('reference_audio', 'audio')]),
        ('head_tail_video', '首尾帧生视频', 'first_last', [port('prompt', 'text', maximum=200), port('first_frame', 'image', 1, 1), port('last_frame', 'image', 1, 1)]),
        ('multi_pic_video', '多图生视频', 'multi', [port('prompt', 'text', maximum=200), port('first_frame', 'image', maximum=1), port('reference_image', 'image', 1)]),
        ('audio_generate', '文本生成音频', 'audio', [port('prompt', 'text', maximum=200)]),
    ]:
        add(key, name, 'audio' if mode == 'audio' else 'video', mode=mode, ports=inputs)
    # These entries open existing editors; they never masquerade as generation.
    for key, name, kind, action in [
        ('lyrics_timeline_extract', '歌词时间线', 'text', 'lyrics'),
        ('shot_script_generate', 'MV 分镜脚本', 'text', 'agent'),
        ('smart_video_breakdown', '智能拉片', 'text', 'agent'),
        ('viral_reference_extract', '爆款复刻参考剧本提取', 'text', 'agent'),
        ('video_story_parse', '视频解析', 'text', 'agent'),
        ('text_generate', '文本生成', 'text', 'agent'),
        ('image_reverse_prompt', '图片反推提示词', 'text', 'agent'),
        ('mv_director_brief', 'MV 导演 Brief', 'text', 'agent'),
        ('audio_clip', '音频裁剪预览', 'audio', 'clip'),
        ('audio_speed', '音频变速预览', 'audio', 'speed'),
        ('video_clip', '视频裁剪预览', 'video', 'clip'),
        ('audio_video_separate', '音视频分离', 'video', 'separate_audio'),
        ('multi_video_edit', '视频剪辑', 'video', 'edit'),
        ('video_soundtrack_compose', '视频配乐合成', 'video', 'music_mix'),
        ('audio_soundtrack', '图片/视频配乐', 'audio', 'music'),
        ('video_script_extract', '剧本拉片', 'text', 'agent'),
        ('video_dewatermark', '字幕区域擦除', 'video', 'remove_subtitles'),
        ('video_depth_map', '深度动作输入', 'video', 'depth_motion'),
        ('video_segment_remake', '已有片段区间替换', 'video', 'segment_remake'),
    ]:
        add(key, name, kind, consumer='editor', action=action)
    for key, name, kind, reason in [
        ('seedance_long_video', '超长视频', 'video', '尚无分段生成与连续性拼接适配；可使用普通视频和剪辑工具。'),
        ('video_upscale', '视频高清', 'video', '样片升级需从原样片任务进入，不能将任意视频当作可升级样片。'),
        ('image_layer_separation', '图层分离', 'image', '本机尚未接通多图层输出适配。'),
        ('image_layer_composition', '图层合成', 'image', '本机尚未接通带顺序与透明度的图层合成适配。'),
    ]:
        add(key, name, kind, consumer='unavailable', reason=reason)
    return rows


def operation_for_node(node):
    """Resolve an explicit operation, while preserving old untagged canvases."""
    key = node.get('params', {}).get(OPERATION_KEY)
    if key is None:
        return None
    operation = next((row for row in _operations() if row['op_type'] == key), None)
    if operation is None or operation['node_type'] != node['type']:
        raise ResourceError('画布操作与节点类型不匹配', 'canvas_operation_mismatch')
    tool = node.get('params', {}).get('vsc_image_tool')
    if operation['image_tool'] != tool:
        raise ResourceError('画布操作与图像工具不匹配', 'canvas_operation_mismatch')
    return operation


def validate_work_operation(node, edges, nodes):
    operation = operation_for_node(node)
    if operation is None:
        return None
    if operation['consumer'] != 'work_generation':
        raise ResourceError(operation['unavailable_reason'] or '此操作须从对应编辑工具执行', 'canvas_operation_unavailable')
    ports = {p['handle']: p for p in operation['input_ports']}
    counts = {key: 0 for key in ports}
    for edge in edges:
        if edge['target'] != node['id'] or edge['port'] == 'derived_from':
            continue
        slot = ports.get(edge['port'])
        if slot is None or nodes[edge['source']]['type'] not in slot['accept']:
            raise ResourceError('所选操作不接受当前参考端口', 'canvas_operation_port')
        counts[edge['port']] += 1
    for key, slot in ports.items():
        if not slot['min_count'] <= counts[key] <= slot['max_count']:
            raise ResourceError(slot['label'] + '数量不符合所选操作要求', 'canvas_operation_port')
    if operation['mode'] == 'omni' and not any(counts.get(k, 0) for k in ('reference_image', 'reference_video', 'reference_audio')):
        raise ResourceError('全能参考生视频至少需要一份媒体参考', 'canvas_operation_port')
    return operation


def canvas_capabilities(models):
    """Build a fresh capability projection; never retain models across requests."""
    from vsc.assets.creative_canvas import NODE_TYPES
    rows = _operations()
    for row in rows:
        kind = row['node_type']
        applicable = []
        for model in models:
            if not model.get('enabled') or model.get('modality') != kind or model.get('adapter_available') is False:
                continue
            caps = model.get('capabilities') or {}
            if row['image_tool'] and 'image_edit' not in caps.get('purposes', []):
                continue
            native = {'panorama': 'panorama', 'upscale': 'upscale', 'inpaint': 'inpaint', 'watermark': 'inpaint'}.get(row['image_tool'])
            if native and native not in caps.get('image_operations', []):
                continue
            if row['mode'] in {'single', 'first_last'} and not caps.get('first_frame'):
                continue
            if row['mode'] == 'first_last' and not caps.get('last_frame'):
                continue
            if row['mode'] in {'multi', 'omni'} and not caps.get('reference_media'):
                continue
            applicable.append(model['id'])
        row['supported_models'] = applicable if row['consumer'] == 'work_generation' else []
        row['default_model_id'] = next(iter(row['supported_models']), None)
        row['available'] = row['consumer'] in {'source', 'editor'} or bool(row['supported_models'])
        if row['consumer'] == 'work_generation':
            row['params_schema']['fields'] = [
                field('count', '候选数量', default=1, min=1, max=8, step=1),
            ]
            if kind in {'image', 'video'}:
                row['params_schema']['fields'].append(field('dimensions', '画幅', 'select', '1080,1920', options=[
                    {'value': value, 'label': label} for value, label in [('1080,1920', '竖屏 9:16'), ('1920,1080', '横屏 16:9'),
                    ('1080,1080', '方形 1:1'), ('2520,1080', '宽银幕 21:9'), ('1080,1350', '竖版 4:5'),
                    ('1350,1080', '横版 5:4'), ('1440,1080', '经典横版 4:3'), ('1080,1440', '经典竖版 3:4'),
                    ('1620,1080', '胶片横版 3:2'), ('1080,1620', '胶片竖版 2:3'), ('2160,1080', '全景 2:1')]]))
            if kind in {'video', 'audio'}:
                row['params_schema']['fields'].append(field('duration_seconds', '时长（秒）', default=5, min=1, max=60, step=1))
            if kind == 'audio':
                row['params_schema']['fields'].append(field('purpose', '声音用途', 'select', 'sfx', options=[
                    {'value': v, 'label': label} for v, label in [('sfx', '音效'), ('music', '音乐'), ('ambience', '环境声')]]))
            if not row['available']:
                row['unavailable_reason'] = '没有支持此操作的已启用本地模型，请检查模型设置。'
    return deepcopy(dict(layout=dict(version=1, strategies=['explicit', 'grid'], profiles=[dict(id='grid', columns=4, horizontal_gap=280, vertical_gap=230)]),
        operations=rows, node_types=[dict(node_type=key, **value) for key, value in NODE_TYPES.items()],
        model_overrides={}, model_params={m['id']: m.get('default_params', {}) for m in models},
        validation_rules=dict(max_nodes=200, max_edges=800, max_candidates=8, first_last_frame_max_count=1)))
