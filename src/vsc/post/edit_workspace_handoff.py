"""Compile an editable cut into the original canonical timeline contract."""
from vsc.post.edit_workspace import validate_edit
from vsc.post.remotion_plan import validate
from vsc.production.handoffs import AUDIO_ROLES


def timeline_document(project_id, episode_id, version, selected, assignments, plans):
    document = version['document']
    total = validate_edit(document)
    choices = {row['id']:row for row in selected['document']['items']}
    segments, bindings, source_map, used_plans = [], [], {}, {}
    position = 0
    for track in ('clips','audio'):
        for clip in document.get(track, []):
            ref = assignments[clip['id']]
            choice = choices[ref['selected_item_id']]
            kind = ref['modality'] if track=='clips' else 'audio'
            duration = clip['out_frame']-clip['in_frame']
            if clip.get('volume',1)>1:
                raise ValueError('正式时间线音量范围为0–1，请先在工作稿调整超过1的片段')
            start = position if track=='clips' else clip.get('at_frame',0)
            if start+duration>total:
                raise ValueError('正式时间线声音区间不能越过画面末尾，请先裁剪该音轨')
            segment = dict(id=clip['id'],kind=kind,source=choice['media']['path'],from_frame=start,
                duration_in_frames=duration,source_in_frame=clip['in_frame'],
                volume=clip.get('volume',1),muted=clip.get('muted',False),track_key=track)
            if kind in {'image','video'}:
                segment.update(source_shot_id=choice['shot_id'],fit='contain')
            if track=='audio':
                segment.update(audio_fade_in_frames=clip.get('fade_in',0),audio_fade_out_frames=clip.get('fade_out',0))
            audible = kind in {'audio','video'} and not segment['muted'] and segment['volume']>0
            role, cue = ref.get('audio_role','none'), ref.get('cue_id')
            if role not in AUDIO_ROLES or (audible and (role=='none' or not cue)) or (not audible and role!='none'):
                raise ValueError('可听声音须明确声音用途和Cue，静音片段须选择无声音')
            if audible:
                plan = plans.get(ref.get('sound_plan_id'))
                if not plan or cue not in plan['cues'] or plan['cues'][cue].get('silence') is True:
                    raise ValueError('声音Cue须来自本次固定声音计划，且不能是静默Cue')
                if choice.get('cue_id') and choice['cue_id']!=cue:
                    raise ValueError('声音Cue与原选片用途不一致')
                cue_media = plan['cues'][cue].get('media')
                if cue_media and cue_media != choice['media']:
                    raise ValueError('声音Cue的固定素材与所选用料不一致')
                used_plans[plan['id']]={'id':plan['id'],'sha256':plan['sha256']}
            binding = dict(segment_id=clip['id'],selected_item_id=choice['id'],sha256=choice['media']['sha256'],
                purpose=choice['purpose'],usage_rights=choice['usage_rights'],audio_role=role,cue_id=cue if audible else None)
            if ref.get('reuse_reason'):
                binding.update(reuse_declared=True,reuse_reason=ref['reuse_reason'])
            mapping={'media_id':clip['media_id'],'binding_decision_id':ref['binding_decision_id']}
            if choice['id'] in source_map and source_map[choice['id']]!=mapping:
                raise ValueError('同一选片项不能映射到不同媒体身份或采用决定')
            source_map[choice['id']]=mapping
            segments.append(segment);bindings.append(binding)
            if track=='clips':position+=duration
    for index,caption in enumerate(document.get('captions', [])):
        segments.append(dict(id='caption-'+str(index),kind='caption',text=caption['text'],
            from_frame=caption['start_frame'],duration_in_frames=caption['end_frame']-caption['start_frame']))
    result={'format':'vsc.timeline/v1','project_id':project_id,'scope':episode_id,
        'selected_takes':{'id':selected['id'],'sha256':selected['sha256']},'sound_plans':list(used_plans.values()),
        'render_plan':{'format':'vsc.remotion-render-plan/v1','project_id':project_id,
            'composition':{'id':'Edit-'+version['id'],'width':document['width'],'height':document['height'],
                'fps':document['fps'],'duration_in_frames':total},'segments':segments},
        'bindings':bindings,'edit_handoff':{'version_id':version['id'],'sha256':version['sha256'],'selected_media':source_map}}
    errors=validate(result)
    if errors:raise ValueError('；'.join(errors))
    return result
