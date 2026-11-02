"""Original professional versions and Cue provenance for editable first cuts.

No approval gate is introduced here. Fixed references and media rights are
verified; missing timing/coverage is reported rather than invented.
"""
import hashlib
import json
from sqlalchemy import and_, select

from vsc.assets.resource_service import ResourceError
from vsc.production.professional_inputs import KIND_TYPES, normalize_professional_inputs, normalize_source_workflow
from . import schema as S


def _document(row):
    raw = bytes(row['document'])
    if hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise ResourceError('专业来源正文摘要不一致', 'edit_professional_changed')
    text = raw.decode('utf8')
    try:return json.loads(text)
    except ValueError:return text


def _gap(reason, *, severity='warning', **values):
    return dict(reason=reason, severity=severity, **values)


def clip_sources(store, conn, p, episode_id, clip):
    """Resolve only this clip's immutable job/input/unit; never a current head."""
    shot = clip.get('shot_id')
    job_id = clip.get('source_job_id')
    if not shot:
        if job_id:raise ResourceError('固定原任务需要对应镜头', 'edit_professional_job_mismatch')
        return dict(job_id=None, pins=[], workflow=None, condition=None)
    if not job_id and clip.get('working_selection_version_id'):
        selection = store._one(conn, S.working_selection_versions, p, clip['working_selection_version_id'])
        candidate = store._one(conn, S.binding_candidates, p, selection['candidate_id']) if selection['candidate_id'] else None
        if selection['shot_id'] != shot or not candidate or candidate['media_id'] != clip['media_id']:
            raise ResourceError('固定工作选片与片段来源不一致', 'edit_professional_job_mismatch')
        job_id = selection.get('source_job_id')
    query = select(S.generation_jobs).join(S.job_outputs, and_(
        S.job_outputs.c.project_id==S.generation_jobs.c.project_id,
        S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(
        S.generation_jobs.c.project_id==p, S.generation_jobs.c.shot_id==shot,
        S.job_outputs.c.media_id==clip['media_id'], S.generation_jobs.c.status=='succeeded',
        S.generation_jobs.c.modality.in_(['image','video']), S.generation_jobs.c.purpose!='depth')
    if job_id:query = query.where(S.generation_jobs.c.id==job_id)
    jobs = {row['id']: row for row in conn.execute(query).mappings()}
    if job_id and not jobs:raise ResourceError('固定原任务与镜头或视频输出不匹配', 'edit_professional_job_mismatch')
    if len(jobs)>1:raise ResourceError('所选素材有多个原始任务，请明确固定原任务', 'edit_professional_job_ambiguous')
    if not jobs:return dict(job_id=None, pins=[], workflow=None, condition=None)
    job = next(iter(jobs.values()))
    result = dict(job_id=job['id'], pins=[], workflow=None, condition=None)
    original = conn.execute(select(S.workbench_run_inputs).where(
        S.workbench_run_inputs.c.project_id==p, S.workbench_run_inputs.c.run_version_id==job['run_version_id'],
        S.workbench_run_inputs.c.shot_id==shot)).mappings().one_or_none()
    if not original:
        run = store._one(conn, S.artifact_versions, p, job['run_version_id'])
        if run['artifact_type']=='workbench-generation-run':
            raise ResourceError('原工作任务缺少固定工作稿来源', 'edit_professional_source_missing')
        return result  # Original non-workbench jobs remain unreviewed.
    if original['output_kind'] != job['modality']:
        raise ResourceError('原工作稿与任务输出类型不一致', 'edit_professional_job_mismatch')
    artifact = store._one(conn, S.artifact_versions, p, original['draft_version_id'])
    if artifact['sha256'] != original['draft_sha256'] or artifact['artifact_type']!='classic-production-draft':
        raise ResourceError('原始工作稿摘要不一致', 'edit_professional_changed')
    body = _document(artifact)
    if not isinstance(body, dict) or body.get('shot_id') != shot:
        raise ResourceError('原始工作稿不属于本镜头', 'edit_professional_job_mismatch')
    result['pins'] = normalize_professional_inputs(body.get('professional_inputs', []))
    if not body.get('source_workflow'):return result
    fixed = normalize_source_workflow(body['source_workflow'])
    version = store._one(conn, S.intelligent_versions, p, fixed['version_id'])
    origin = store._one(conn, S.artifact_versions, p, fixed['artifact_id'])
    if (version['artifact_id'] != fixed['artifact_id'] or origin['sha256'] != fixed['artifact_sha256'] or
            origin['artifact_type'] not in KIND_TYPES['workflow']):
        raise ResourceError('原制作流程固定版本不一致', 'edit_professional_changed')
    _document(origin)
    workflow = store._one(conn, S.intelligent_workflows, p, version['workflow_id'])
    if workflow['episode_id'] != episode_id:
        raise ResourceError('原制作流程不属于本集', 'edit_professional_scope')
    from vsc.production.quotes import fingerprint
    state = store._intelligent_state(conn, p, version)
    units = [u for u in state['units'] if u['unit_key']==fixed['unit_key']]
    if fingerprint(state) != fixed['state_sha256'] or len(units)!=1 or units[0]['shot_id']!=shot:
        raise ResourceError('原制作流程固定状态不一致', 'edit_professional_changed')
    result['workflow'] = dict(id=fixed['artifact_id'], sha256=fixed['artifact_sha256'], kind='workflow')
    result['pins'].append(result['workflow'])
    result['condition'] = units[0].get('professional', {})
    return result


def cue_intervals(document, covers):
    """Project declared shot-local milliseconds through actual clip trims."""
    fps, offset, result = document['fps'], 0, []
    by_shot = {row['shot_id']: row for row in covers}
    for clip in document['clips']:
        cover = by_shot.get(clip.get('shot_id'))
        if cover and type(cover.get('start_ms')) is int and type(cover.get('end_ms')) is int:
            begin = max(clip['in_frame'] * 1000 / fps, cover['start_ms'])
            end = min(clip['out_frame'] * 1000 / fps, cover['end_ms'])
            if end > begin:
                result.append(dict(clip_id=clip['id'], shot_id=clip['shot_id'],
                    start_ms=offset * 1000 / fps + begin - clip['in_frame'] * 1000 / fps,
                    end_ms=offset * 1000 / fps + end - clip['in_frame'] * 1000 / fps,
                    source_start_ms=begin, source_end_ms=end))
        offset += clip['out_frame'] - clip['in_frame']
    return result


def professional_context(store, conn, p, episode_id, document):
    refs = normalize_professional_inputs(document.get('professional_inputs', []), allow_workflow=True)
    scope = set(store._descendant_ids(conn, p, episode_id)) | {episode_id}
    result = dict(inputs=[], creative_rules=None, script_texts=None, shot_conditions={}, sound_checks=[], gaps=[])
    sources = [(clip, clip_sources(store, conn, p, episode_id, clip)) for clip in document['clips']]
    pins = {ref['id']: ref for ref in refs}
    for clip, source in sources:
        if clip.get('source_job_id') and any(pins.get(pin['id']) != pin for pin in source['pins']):
            raise ResourceError('固定原任务的专业来源未完整保留', 'edit_professional_source_missing')
    sounds = {}
    for ref in refs:
        artifact = store._one(conn, S.artifact_versions, p, ref['id'])
        if artifact['sha256'] != ref['sha256'] or artifact['artifact_type'] not in KIND_TYPES[ref['kind']]:
            raise ResourceError('剪辑专业来源类型或摘要已经变化', 'edit_professional_changed')
        if not artifact['project_wide'] and not set(store._artifact_scopes(conn, p, artifact['id'])) & scope:
            raise ResourceError('专业来源不属于本集', 'edit_professional_scope')
        body = _document(artifact)
        result['inputs'].append(dict(ref, document=body))
        if ref['kind'] == 'screenplay':
            # Raw source paragraphs/actions are not a declaration of subtitles.
            lines = list(conn.execute(select(S.script_lines.c.text).where(S.script_lines.c.project_id==p,
                S.script_lines.c.script_version_id==ref['id'],S.script_lines.c.scene_id.in_(scope),
                S.script_lines.c.line_kind.in_(['dialogue','narration'])).order_by(S.script_lines.c.ordinal,S.script_lines.c.id)).scalars())
            if lines:result['script_texts'] = (result['script_texts'] or []) + lines
        if ref['kind'] == 'creative_rules':
            from vsc.project.creative_rules import rule_errors
            rules = body.get('creative_rules', body) if isinstance(body, dict) else None
            errors = rule_errors(rules)
            if errors:raise ResourceError('；'.join(errors), 'edit_professional_rules_invalid')
            if result['creative_rules'] is not None and result['creative_rules'] != rules:
                raise ResourceError('固定专业来源包含不同字幕规则，请明确本集使用版本', 'edit_professional_rules_conflict')
            result['creative_rules'] = rules
        if ref['kind'] == 'workflow':
            version = conn.execute(select(S.intelligent_versions).where(S.intelligent_versions.c.project_id==p,
                S.intelligent_versions.c.artifact_id==ref['id'])).mappings().one_or_none()
            if not version:raise ResourceError('缺少原流程版本', 'edit_professional_changed')
            workflow = store._one(conn, S.intelligent_workflows, p, version['workflow_id'])
            if workflow['episode_id'] != episode_id:raise ResourceError('原流程不属于本集', 'edit_professional_scope')
            for clip, source in sources:
                if source['workflow'] != ref:continue
                condition = source['condition']
                previous = result['shot_conditions'].get(clip['shot_id'])
                if previous is not None and previous != condition:
                    raise ResourceError('同镜头有不同固定流程条件，请明确使用版本', 'edit_professional_workflow_conflict')
                result['shot_conditions'][clip['shot_id']] = condition
        if ref['kind'] == 'sound_plan':
            for row in conn.execute(select(S.sound_cues).where(S.sound_cues.c.project_id==p,
                    S.sound_cues.c.artifact_id==ref['id'])).mappings():
                cue = dict(row)
                if cue['scope_object_id'] not in scope:continue
                covers = [dict(c) for c in conn.execute(select(S.cue_shots).where(S.cue_shots.c.project_id==p,
                    S.cue_shots.c.cue_id==cue['id'])).mappings()]
                if any(c['shot_id'] not in scope for c in covers):
                    raise ResourceError('声音 Cue 超出当前集', 'edit_cue_scope')
                cue['covers'] = covers
                cue['intervals'] = cue_intervals(document, covers)
                sounds[cue['id']] = cue
                result['sound_checks'].append(dict(cue_id=cue['id'], label=cue['label'], kind=cue['cue_kind'],
                    intervals=cue['intervals'], timing='declared' if covers and all(c['start_ms'] is not None for c in covers) else 'not_declared'))
    for audio in document.get('audio', []):
        if not audio.get('cue_id'):continue
        cue = sounds.get(audio['cue_id'])
        if cue is None:raise ResourceError('音轨 Cue 不属于本稿固定声音计划', 'edit_cue_source')
        decision = store._one(conn, S.binding_decisions, p, audio['binding_decision_id'])
        candidate = store._one(conn, S.binding_candidates, p, decision['candidate_id']) if decision['candidate_id'] else None
        linked = conn.execute(select(S.cue_slots.c.id).where(S.cue_slots.c.project_id==p,
            S.cue_slots.c.cue_id==cue['id'], S.cue_slots.c.slot_id==decision['slot_id'])).scalar_one_or_none()
        if decision['outcome'] != 'select' or not candidate or candidate['media_id'] != audio['media_id'] or not linked:
            raise ResourceError('音轨素材不属于固定 Cue 采用决定', 'edit_cue_binding')
    if not refs:result['gaps'].append(_gap('此工作稿没有固定专业来源，声音与字幕保持未审'))
    for clip in document['clips']:
        route = result['shot_conditions'].get(clip.get('shot_id'),{}).get('sound_route','unknown')
        covered = any(cue['cue_kind']!='silence' and any(interval['clip_id']==clip['id'] for interval in cue['intervals']) for cue in sounds.values())
        if route not in {'native','silent'} and not covered:
            result['gaps'].append(_gap('没有可用的固定声音 Cue，不能证明声音计划覆盖',
                severity='blocking' if route=='separate' else 'warning', clip_id=clip['id'], shot_id=clip.get('shot_id')))
    result['_cues'] = sounds
    return result


def seed_professional(store, conn, p, episode_id, document):
    return merge_professional(store, conn, p, episode_id, document, document['clips'])


def merge_professional(store, conn, p, episode_id, document, added_clips):
    """Enrich only appended clips; existing editorial tracks stay byte-for-byte."""
    refs = {pin['id']: pin for pin in normalize_professional_inputs(document.get('professional_inputs', []), allow_workflow=True)}
    gaps, sound_plans = [], set()
    for clip in added_clips:
        source = clip_sources(store, conn, p, episode_id, clip)
        if source['job_id']:clip['source_job_id'] = source['job_id']
        for pin in source['pins']:
            if pin['id'] in refs and refs[pin['id']] != pin:raise ResourceError('专业来源摘要冲突', 'edit_professional_changed')
            refs[pin['id']] = pin
            if pin['kind']=='sound_plan':sound_plans.add(pin['id'])
    if not refs:return gaps  # Legacy seed semantics remain usable, without claiming review.
    document['professional_inputs'] = normalize_professional_inputs(list(refs.values()), allow_workflow=True)
    context = professional_context(store, conn, p, episode_id, document)
    gaps += context['gaps']
    for clip in added_clips:
        if context['shot_conditions'].get(clip.get('shot_id'), {}).get('sound_route') in {'silent', 'separate'}:
            clip['muted'] = True
    added_shots = {clip.get('shot_id') for clip in added_clips}
    for cue in context['_cues'].values():
        if (cue['cue_kind']=='silence' or cue['artifact_id'] not in sound_plans or
                (cue['covers'] and not any(cover['shot_id'] in added_shots for cover in cue['covers']))):continue
        if any(audio.get('cue_id')==cue['id'] for audio in document['audio']):continue
        try:
            audio = seed_cue(store, conn, p, document, cue)
            if audio:
                document['audio'].append(audio)
                if cue['cue_kind'] in {'dialogue','narration'}:
                    try:
                        caption=seed_caption(store,conn,p,document,cue,audio)
                        if caption and caption not in document['captions']:document['captions'].append(caption)
                    except ResourceError as error:gaps.append(_gap(str(error),cue_id=cue['id'],code=error.code))
        except ResourceError as error:
            # Undeclared Cue timing is a review reminder unless an actual clip
            # explicitly requires separate sound. Media/adoption/trim failures
            # continue to block the automatic first cut.
            separate = any(context['shot_conditions'].get(clip.get('shot_id'),{}).get('sound_route')=='separate'
                           and (not cue['covers'] or any(c['shot_id']==clip.get('shot_id') for c in cue['covers']))
                           for clip in added_clips)
            severity = 'warning' if error.code=='edit_cue_timing_missing' and not separate else 'blocking'
            gaps.append(_gap(str(error), severity=severity, cue_id=cue['id'], code=error.code))
    return gaps


def seed_cue(store, conn, p, document, cue):
    covers, intervals, fps = cue['covers'], cue['intervals'], document['fps']
    if not covers or any(c['start_ms'] is None or c['end_ms'] is None for c in covers):
        raise ResourceError('Cue 缺少明确镜内毫秒范围', 'edit_cue_timing_missing')
    if not intervals:return None  # Entire Cue was deliberately trimmed away.
    ordered_shots = [clip.get('shot_id') for clip in document['clips']]
    if any(c['shot_id'] not in ordered_shots for c in covers) or len(set(ordered_shots)) != len(ordered_shots):
        raise ResourceError('跨镜 Cue 的镜头缺失或重复，不能推断音频播放次序', 'edit_cue_coverage_ambiguous')
    ordered = sorted(covers, key=lambda c: ordered_shots.index(c['shot_id']))
    offsets, elapsed = {}, 0
    for cover in ordered:
        offsets[cover['shot_id']] = elapsed
        elapsed += cover['end_ms'] - cover['start_ms']
    for before, after in zip(intervals, intervals[1:]):
        source_end=offsets[before['shot_id']]+before['source_end_ms']-next(c['start_ms'] for c in covers if c['shot_id']==before['shot_id'])
        source_begin=offsets[after['shot_id']]+after['source_start_ms']-next(c['start_ms'] for c in covers if c['shot_id']==after['shot_id'])
        if abs(before['end_ms']-after['start_ms']) > 1 or abs(source_end-source_begin)>1:
            raise ResourceError('跨镜 Cue 在当前裁剪中不连续，请明确声音剪辑', 'edit_cue_discontinuous')
    rows = conn.execute(select(S.binding_decisions, S.binding_candidates.c.media_id).join(S.cue_slots,
        and_(S.cue_slots.c.project_id==p, S.cue_slots.c.slot_id==S.binding_decisions.c.slot_id))
        .join(S.current_bindings, and_(S.current_bindings.c.project_id==p,
            S.current_bindings.c.decision_id==S.binding_decisions.c.id))
        .join(S.binding_candidates, and_(S.binding_candidates.c.project_id==p,
            S.binding_candidates.c.id==S.binding_decisions.c.candidate_id))
        .where(S.binding_decisions.c.project_id==p, S.cue_slots.c.cue_id==cue['id'],
            S.binding_decisions.c.outcome=='select')).mappings().all()
    if len(rows) != 1:raise ResourceError('Cue 需要唯一的已固定声音采用', 'edit_cue_binding_missing')
    decision = rows[0]
    purpose = {'dialogue':'dialogue_dry','narration':'dialogue_dry','ambience':'ambience','foley':'sfx','sfx':'sfx','music':'music'}[cue['cue_kind']]
    from .workbench_generation import working_media
    media, reasons = working_media(store, conn, p, decision['media_id'], purpose)
    if reasons or media['modality'] not in {'audio','video'} or not media.get('duration_ms'):
        raise ResourceError('Cue 声音素材不可用或无实测时长：'+', '.join(reasons), 'edit_cue_media_unusable')
    start = cue['parameters'].get('source_in_ms')
    if start is None and abs(media['duration_ms']-elapsed) <= 1:start = 0
    if type(start) is not int or start < 0:
        raise ResourceError('Cue 未声明素材入点，且实测音频时长与覆盖不一致', 'edit_cue_source_timing_missing')
    first = intervals[0]
    source_start = start + offsets[first['shot_id']] + first['source_start_ms'] - next(c['start_ms'] for c in covers if c['shot_id']==first['shot_id'])
    duration = intervals[-1]['end_ms'] - first['start_ms']
    if source_start + duration > media['duration_ms'] + 1:
        raise ResourceError('Cue 明确范围超过实测音频时长', 'edit_cue_source_short')
    begin, end = round(source_start*fps/1000), round((source_start+duration)*fps/1000)
    if end <= begin:raise ResourceError('Cue 区间不足一帧', 'edit_cue_timing_missing')
    return dict(id='cue-'+cue['id'],media_id=media['id'],cue_id=cue['id'],binding_decision_id=decision['id'],
        in_frame=begin,out_frame=end,at_frame=round(first['start_ms']*fps/1000),volume=1,muted=False,purpose=purpose)


def seed_caption(store,conn,p,document,cue,audio):
    from vsc.post.subtitles import measurement_errors
    alignment=cue['parameters'].get('subtitle_alignment')
    if not cue['line_id'] or not isinstance(alignment,dict):
        raise ResourceError('对白 Cue 缺少固定台词行或实测字幕时码，未自动生成字幕','edit_caption_timing_missing')
    line=store._one(conn,S.script_lines,p,cue['line_id'])
    media=store._media(conn,p,audio['media_id'])
    if (line['line_kind'] not in {'dialogue','narration'} or
            not any(ref['id']==line['script_version_id'] and ref['sha256']==line['source_sha256'] and ref['kind']=='screenplay'
                for ref in document.get('professional_inputs',[])) or
            alignment.get('script_version_sha256')!=line['source_sha256'] or alignment.get('audio_media_sha256')!=media['sha256']):
        raise ResourceError('字幕时码未绑定当前固定对白与音频摘要','edit_caption_source_mismatch')
    begin,end=alignment.get('start_ms'),alignment.get('end_ms')
    errors=measurement_errors(alignment.get('measurement'),line_key=line['line_key'],audio_sha256=media['sha256'],start_ms=begin,end_ms=end)
    fps=document['fps'];source_in=audio['in_frame']*1000/fps;source_out=audio['out_frame']*1000/fps
    if errors or type(begin)is not int or type(end)is not int or not source_in<=begin<end<=min(source_out,media['duration_ms']):
        raise ResourceError('字幕测量缺失或超出本次声音裁剪范围','edit_caption_timing_invalid')
    start=audio['at_frame']+round((begin-source_in)*fps/1000)
    finish=audio['at_frame']+round((end-source_in)*fps/1000)
    if not 0<=start<finish<=sum(c['out_frame']-c['in_frame'] for c in document['clips']):
        raise ResourceError('字幕测量范围不在当前时间线内','edit_caption_timing_invalid')
    return dict(start_frame=start,end_frame=finish,text=line['text'])
