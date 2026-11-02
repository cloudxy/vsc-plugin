"""Fixed workbench inputs for an explicit generation action.

Working drafts are not approved screenplay/shot plans. Their exact bytes and
typed media references are fixed for a generation request, while formal
adoption and delivery continue to use the original approval consumers.
"""
import json
import uuid

from sqlalchemy import select

from vsc.assets.resource_service import Conflict, ResourceError, context_digest
from . import schema as S
from .values import checked_id, clean


RUN_TYPE = "workbench-generation-run"


def subject_sources(store, conn, project_id, document):
    """Resolve selection only through an original typed job output or editor export."""
    from vsc.production.digital_human import normalize_selection
    from vsc.production.image_tools import OUTPUT_TYPE, EDIT_TYPE
    chosen = normalize_selection(document.get('subject_selection'))
    refs = {row['role']: row for row in document['references']}
    if (not chosen or set(refs) - {'portrait', 'speech', 'subject_mask'} or
            not refs.get('portrait') or not refs.get('subject_mask') or
            (refs['portrait']['media_id'], refs['portrait']['sha256']) != (chosen['source_media_id'], chosen['source_sha256']) or
            (refs['subject_mask']['media_id'], refs['subject_mask']['sha256']) != (chosen['mask_media_id'], chosen['mask_sha256'])):
        raise ResourceError('请为当前原图重新选择讲话主体', 'subject_selection_mismatch')
    source = store._media(conn, project_id, checked_id(chosen['source_media_id']))
    mask = store._media(conn, project_id, checked_id(chosen['mask_media_id']))
    if (source['sha256'] != chosen['source_sha256'] or mask['sha256'] != chosen['mask_sha256'] or
            source['modality'] != 'image' or mask['modality'] != 'image' or
            (source['width'], source['height']) != (mask['width'], mask['height'])):
        raise ResourceError('原图或主体mask摘要、尺寸已经变化', 'subject_mask_mismatch')
    if chosen['origin'] == 'detected':
        job = store._one(conn, S.generation_jobs, project_id, checked_id(chosen['job_id']))
        request = job['request_payload']
        if (job['status'] != 'succeeded' or job['shot_id'] != document['shot_id'] or
                request.get('operation') != 'subject_detect' or
                (request.get('source_media_id'), request.get('source_sha256')) != (source['id'], source['sha256']) or
                str(uuid.uuid5(uuid.UUID(job['id']), 'output:' + str(chosen['output_index']))) != mask['id']):
            raise ResourceError('主体mask不属于当前原图的成功识别任务', 'subject_detection_mismatch')
        original = conn.execute(select(S.job_input_media.c.id).where(S.job_input_media.c.project_id == project_id,
            S.job_input_media.c.job_id == job['id'], S.job_input_media.c.media_id == source['id'],
            S.job_input_media.c.blob_sha256 == source['sha256'], S.job_input_media.c.role == 'operation_source')).scalar_one_or_none()
        output = conn.execute(select(S.job_outputs.c.id).where(S.job_outputs.c.project_id == project_id,
            S.job_outputs.c.job_id == job['id'], S.job_outputs.c.media_id == mask['id'])).scalar_one_or_none()
        if not original or not output:
            raise ResourceError('识别输入输出关系缺失', 'subject_detection_mismatch')
        return {**chosen, 'dependency_id': job['run_version_id']}
    export = store._one(conn, S.artifact_versions, project_id, checked_id(chosen['export_id']))
    value = json.loads(export['document'])
    if (export['artifact_type'] != OUTPUT_TYPE or value.get('shot_id') != document['shot_id'] or
            (value.get('source_media_id'), value.get('source_sha256')) != (source['id'], source['sha256']) or
            not any((row['role'], row['media_id'], row['sha256']) == ('mask', mask['id'], mask['sha256']) for row in value.get('outputs', []))):
        raise ResourceError('手绘主体须来自当前原图的黑白mask导出', 'subject_export_mismatch')
    edit = store._one(conn, S.artifact_versions, project_id, checked_id(value['edit_version_id']))
    fixed = json.loads(edit['document'])
    if (edit['artifact_type'] != EDIT_TYPE or edit['sha256'] != value['edit_sha256'] or fixed.get('mode') != 'digital_human' or
            fixed['edit']['source_sha256'] != source['sha256'] or
            (fixed['edit']['width'], fixed['edit']['height']) != (source['width'], source['height'])):
        raise ResourceError('手绘主体源版本或用途无效', 'subject_export_mismatch')
    return {**chosen, 'dependency_id': export['id']}


def subject_candidates(store, conn, project_id, shot_id):
    """All completed subject jobs for this shot, never a latest-100 truncation."""
    from vsc.production.digital_human import MAX_MASKS
    result = []
    jobs = conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id == project_id,
        S.generation_jobs.c.shot_id == shot_id, S.generation_jobs.c.status == 'succeeded',
        S.generation_jobs.c.request_payload['operation'].as_string() == 'subject_detect')
        .order_by(S.generation_jobs.c.created_at, S.generation_jobs.c.id)).mappings()
    for job in jobs:
        request = job['request_payload']
        outputs = {row['media_id'] for row in conn.execute(select(S.job_outputs.c.media_id).where(
            S.job_outputs.c.project_id == project_id, S.job_outputs.c.job_id == job['id'])).mappings()}
        for index in range(MAX_MASKS):
            media_id = str(uuid.uuid5(uuid.UUID(job['id']), 'output:' + str(index)))
            if media_id not in outputs:continue
            media = store._media(conn, project_id, media_id)
            result.append({'origin': 'detected', 'job_id': job['id'], 'output_index': index,
                'source_media_id': request['source_media_id'], 'source_sha256': request['source_sha256'],
                'mask_media_id': media_id, 'mask_sha256': media['sha256']})
    return result


def inpaint_sources(store, conn, project_id, document):
    """Resolve the editor export and its typed source/mask, never free-form IDs."""
    from vsc.production.image_tools import OUTPUT_TYPE, EDIT_TYPE
    settings=document.get('tool_settings',{})
    source=next((r for r in document['references'] if r['role']=='operation_source'),None)
    mask=next((r for r in document['references'] if r['role']=='operation_mask'),None)
    if len(document['references'])!=2 or not source or not mask or not settings.get('mask_export_id'):
        raise ResourceError('请从原图编辑器固定原图和修改区域','inpaint_inputs_required')
    artifact=store._one(conn,S.artifact_versions,project_id,checked_id(settings['mask_export_id']))
    value=json.loads(artifact['document'])
    if artifact['artifact_type']!=OUTPUT_TYPE or value.get('shot_id')!=document['shot_id'] or (value.get('source_media_id'),value.get('source_sha256'))!=(source['media_id'],source['sha256']):
        raise ResourceError('遮罩导出与固定原图或镜头不一致','inpaint_export_mismatch')
    if not any((row['role'],row['media_id'],row['sha256'])==('inpaint-mask',mask['media_id'],mask['sha256']) for row in value.get('outputs',[])) or (settings.get('mask_media_id'),settings.get('mask_sha256'))!=(mask['media_id'],mask['sha256']):
        raise ResourceError('遮罩不是该固定导出版本的透明编辑遮罩','inpaint_export_mismatch')
    edit=store._one(conn,S.artifact_versions,project_id,checked_id(value['edit_version_id']))
    source_media=store._media(conn,project_id,checked_id(source['media_id']))
    mask_media=store._media(conn,project_id,checked_id(mask['media_id']))
    d=json.loads(edit['document'])['edit']
    if edit['artifact_type']!=EDIT_TYPE or edit['sha256']!=value['edit_sha256'] or d['source_modality']!='image' or d['source_sha256']!=source['sha256'] or source_media['sha256']!=source['sha256'] or mask_media['sha256']!=mask['sha256'] or (d['width'],d['height'])!=(mask_media['width'],mask_media['height']):
        raise ResourceError('遮罩的固定源版本、摘要或尺寸不匹配','inpaint_export_mismatch')
    if (source_media['width'],source_media['height'])!=(mask_media['width'],mask_media['height']):
        raise ResourceError('遮罩必须使用原图完整尺寸，请新建原尺寸遮罩','inpaint_export_mismatch')
    return {'export_id':artifact['id'],'export_sha256':artifact['sha256'],'source_media_id':source['media_id'],'mask_media_id':mask['media_id']}


def working_media(store, conn, project_id, media_id, purpose):
    """Local drafts use uploaded/generated material without inventing formal review."""
    media, gaps = store._usable(conn, project_id, media_id, purpose)
    rights = store._latest(conn, S.rights_decisions, project_id, 'media_id', media_id)
    permitted = {'technical_check_missing', 'copy_source_rights_unknown'}
    if rights is None or rights['outcome'] == 'unknown':
        permitted.add('rights_unknown_or_restricted')
    return media, [gap for gap in gaps if gap not in permitted]


def working_context(store, conn, project, draft_id, *, shot_id=None, purpose=None):
    from vsc.assets.classic_production import DRAFT_TYPE, normalize_draft, MODES

    p = project["id"]
    artifact = store._one(conn, S.artifact_versions, p, checked_id(draft_id))
    if artifact["artifact_type"] != DRAFT_TYPE:
        raise ResourceError("生成输入必须是已保存的制作草稿", "classic_draft_required")
    document = normalize_draft(json.loads(artifact["document"]))
    shot = store._one(conn, S.shots, p, checked_id(document["shot_id"]))
    if shot_id is not None and shot["id"] != shot_id or purpose is not None and document["purpose"] != purpose and not (document['mode']=='depth_motion' and purpose=='depth'):
        raise ResourceError("固定草稿不属于当前镜头与用途", "working_input_scope")
    references = conn.execute(select(S.classic_draft_media).where(
        S.classic_draft_media.c.project_id == p,
        S.classic_draft_media.c.draft_version_id == artifact["id"])
        .order_by(S.classic_draft_media.c.ordinal)).mappings().all()
    if len(references) != len(document["references"]):
        raise ResourceError("草稿引用尚未完整登记，请重新保存当前输入", "working_reference_incomplete")
    media, gaps = [], []
    for expected, ref in zip(document["references"], references):
        if (expected["media_id"], expected["role"], expected["sha256"]) != (ref["media_id"], ref["role"], ref["blob_sha256"]):
            raise Conflict("草稿引用与固定媒体关系不一致", "working_reference_changed")
        item, missing = working_media(store, conn, p, ref["media_id"], document["purpose"])
        if item["sha256"] != ref["blob_sha256"] or item["modality"] != MODES[document["mode"]]["slots"][ref["role"]]:
            raise Conflict("固定参考素材已变化", "working_reference_changed")
        gaps.extend({"code": code, "media_id": item["id"]} for code in missing)
        media.append({"media_id": item["id"], "blob_id": item["blob_id"], "sha256": item["sha256"],
                      "role": ref["role"], "binding_decision_id": None})
    context = {"project_id": p, "shot_id": shot["id"], "purpose": purpose or document["purpose"],
               "revision": project["revision"], "working_draft": {"id": artifact["id"], "sha256": artifact["sha256"]},
               "artifacts": [], "media": media, "gaps": gaps, "ready": not gaps}
    if document['mode']=='audio_speech':
        context['working_speech']={'draft_id':artifact['id'],'text':document['prompt'],'speaker':document['tool_settings']['speaker']}
    if document['mode']=='audio_song':
        context['working_song']={'draft_id':artifact['id'],'lyrics':document['lyrics'],'prompt':document['prompt']}
    if document['mode'] == 'image_subject_detect':
        from vsc.production.digital_human import detection_request_fields
        if len(document['references']) != 1:
            raise ResourceError('主体识别需要唯一原图', 'subject_image_invalid')
        source = store._media(conn, p, document['references'][0]['media_id'])
        context['working_native_media'] = detection_request_fields(source, document['params'])
    if document['mode'] == 'digital_human':
        from vsc.production.digital_human import avatar_request_fields
        fixed = subject_sources(store, conn, p, document)
        dependency = conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id == p,
            S.artifact_dependencies.c.artifact_id == artifact['id'], S.artifact_dependencies.c.dependency_id == fixed['dependency_id'])).scalar_one_or_none()
        audio_refs = [row for row in document['references'] if row['role'] == 'speech']
        if not dependency or len(audio_refs) != 1:
            raise ResourceError('数字人需要固定主体来源依赖和唯一驱动音轨', 'subject_selection_required')
        source = store._media(conn, p, fixed['source_media_id']); mask = store._media(conn, p, fixed['mask_media_id'])
        audio = store._media(conn, p, audio_refs[0]['media_id'])
        context['working_avatar'] = {'selection': fixed, 'request': avatar_request_fields(source, audio, mask,
            document['performance_prompt'], document['params'])}
    if document['mode']=='video_upgrade' and document['references'] and document['model_id']:
        from vsc.production.video_samples import upgrade_request
        from .video_samples import resolve_sample
        if len(document['references'])!=1:raise ResourceError('升级需要唯一固定样片','sample_output_mismatch')
        source=store._media(conn,p,document['references'][0]['media_id'])
        model=conn.execute(select(S.provider_models).where(S.provider_models.c.id==checked_id(document['model_id']))).mappings().one_or_none()
        if model is None:raise ResourceError('升级模型配置不存在，请重新选择','model_unavailable')
        context['working_sample']=resolve_sample(store,conn,project,upgrade_request(source),dict(model))
    if document['mode'] in {'image_inpaint','image_watermark'}:
        fixed=inpaint_sources(store,conn,p,document)
        dependency=conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==p,S.artifact_dependencies.c.artifact_id==artifact['id'],S.artifact_dependencies.c.dependency_id==fixed['export_id'])).scalar_one_or_none()
        if not dependency:raise ResourceError('局部重绘草稿没有固定遮罩导出依赖','inpaint_export_mismatch')
        context['working_inpaint']=fixed
        if document['mode']=='image_watermark' and document['tool_settings'].get('rights_confirmed') is not True:
            raise ResourceError('去水印须明确确认有权处理此来源','watermark_rights_required')
    if document['mode'] in {'image_panorama','image_upscale','video_depth'}:
        from vsc.production.fal_tools import image_operation_fields, depth_operation_fields
        if len(document['references'])!=1:raise ResourceError('原生媒体操作需要唯一固定原件','fal_source_invalid')
        source=store._media(conn,p,document['references'][0]['media_id'])
        context['working_native_media']=(depth_operation_fields(source,document['tool_settings']) if document['mode']=='video_depth'
            else image_operation_fields(document['mode'][6:],source,document['tool_settings']))
    if document['mode']=='depth_motion':
        from vsc.production.fal_tools import depth_operation_fields
        refs={ref['role']:ref for ref in document['references']}
        if len(document['references'])!=2 or set(refs)!={'operation_source','character'}:
            raise ResourceError('深度动作需要唯一源视频和唯一人物图','depth_motion_inputs')
        settings={k:v for k,v in document['tool_settings'].items() if k!='depth_model_id'}
        context['working_native_media']=depth_operation_fields(store._media(conn,p,refs['operation_source']['media_id']),settings)
        context['working_dependency_contract']='depth-motion/v1'
    from .professional_inputs import resolve_professional_inputs,validate_saved_sources
    professional=resolve_professional_inputs(store,conn,project,document)
    validate_saved_sources(conn,p,artifact['id'],document,professional)
    context.update(professional['context'])
    context["sha256"] = context_digest(context)
    return clean(context)


def context_for_run(store, conn, project, run, shot_id, purpose):
    document = json.loads(run["document"]) if isinstance(run.get("document"), (str, bytes, bytearray)) else run.get("document", run)
    working = document.get("workbench_draft")
    if run.get("artifact_type") != RUN_TYPE:
        if working:
            raise ResourceError("正式制作不能用工作草稿替换批准输入", "working_run_type")
        return store._compile_context(conn, project, shot_id, purpose)
    if not isinstance(working, dict) or set(working) != {"id", "sha256"}:
        raise ResourceError("工作生成缺少固定草稿", "working_input_missing")
    reference = conn.execute(select(S.workbench_run_inputs).where(
        S.workbench_run_inputs.c.project_id == project["id"],
        S.workbench_run_inputs.c.run_version_id == run["id"],
        S.workbench_run_inputs.c.shot_id == shot_id)).mappings().one_or_none()
    if reference is None or (reference["draft_version_id"], reference["draft_sha256"]) != (working["id"], working["sha256"]):
        raise ResourceError("工作生成来源关系不完整", "working_input_missing")
    context = working_context(store, conn, project, working["id"], shot_id=shot_id, purpose=purpose)
    if context["working_draft"]["sha256"] != working["sha256"]:
        raise Conflict("工作生成固定输入摘要已变化", "working_input_changed")
    if context.get('working_dependency_contract')=='depth-motion/v1' and purpose=='reference_to_video':
        from vsc.production.bounded import depth_dependency_tasks
        import uuid
        depth,final=depth_dependency_tasks(document)
        jobs=conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==project['id'],S.generation_jobs.c.run_version_id==run['id'],
            S.generation_jobs.c.shot_id==shot_id,S.generation_jobs.c.purpose=='depth',S.generation_jobs.c.candidate_no==depth['candidate_no'])).mappings().all()
        if len(jobs)>1:raise ResourceError('深度中间任务不唯一','task_job_conflict')
        if jobs and jobs[0]['status']=='succeeded':
            identifier=str(uuid.uuid5(uuid.UUID(jobs[0]['id']),'output:0'))
            output=conn.execute(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==project['id'],S.job_outputs.c.job_id==jobs[0]['id'],S.job_outputs.c.media_id==identifier)).scalar_one_or_none()
            if not output:raise ResourceError('深度中间任务缺少固定序号输出','task_output_missing')
            media,gaps=working_media(store,conn,project['id'],output,purpose)
            if media['modality']!='video':raise ResourceError('深度中间结果不是视频','task_output_missing')
            context['media'].append({'media_id':output,'blob_id':media['blob_id'],'sha256':media['sha256'],'role':'reference_video','binding_decision_id':None,'working_run_output':jobs[0]['id']})
            context['gaps'].extend({'code':gap,'media_id':output} for gap in gaps);context['ready']=not context['gaps']
            context['sha256']=context_digest(context)
    return context
