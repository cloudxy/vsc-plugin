"""Immutable quality evidence projections and live run checks.

The standard create_artifact/decide_artifact API is the only authoring and human
approval path. These rows are projections, never another writable ledger.
"""
import json
import math
import uuid
from collections import defaultdict
from sqlalchemy import insert, select
from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import digest

FORMATS = {'vsc.quality-observations/v1', 'vsc.method-evaluation/v1'}


def environment_digest(model, request):
    return digest({'model_id': model['id'], 'provider_id': model['provider_id'],
                   'model_version': model['model_version'], 'capabilities': model['capabilities'],
                   'default_params': model.get('default_params', {}),
                   'modality': request['modality'], 'purpose': request['purpose'],
                   'params': request.get('params', {})})


def project_quality_document(store, conn, p, artifact_id, document):
    if not isinstance(document, dict) or document.get('format') not in FORMATS:
        return False
    if document.get('project_id') != p:
        raise ResourceError('质量证据项目不匹配', 'quality_project_mismatch')
    deps = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
        S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == artifact_id)).scalars())

    def artifact(identifier):
        row = store._one(conn, S.artifact_versions, p, identifier)
        if identifier not in deps or not store._artifact_approved(conn, p, identifier):
            raise ResourceError('质量引用必须是固定批准依赖', 'quality_dependency_missing')
        return row

    def output(job, media):
        if not conn.execute(select(S.job_outputs.c.id).where(S.job_outputs.c.project_id == p,
                S.job_outputs.c.job_id == job['id'], S.job_outputs.c.media_id == media)).first():
            raise ResourceError('质量媒体必须为指定任务真实输出', 'quality_output_mismatch')

    if document['format'] == 'vsc.quality-observations/v1':
        rows = document.get('observations')
        if not isinstance(rows, list) or not rows:
            raise ResourceError('质量观察缺少 observations', 'quality_observation_required')
        seen = set()
        for n, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ResourceError('质量观察必须是对象', 'quality_observation_invalid')
            job = store._one(conn, S.generation_jobs, p, row.get('job_id'))
            artifact(row.get('criteria_artifact_id'))
            if row.get('method_artifact_id'):
                method = artifact(row['method_artifact_id'])
                run = store._one(conn, S.artifact_versions, p, job['run_version_id'])
                run_doc = json.loads(run['document'])
                if run_doc.get('phase') == 'trial' and run_doc.get('trial', {}).get('method_sha256') != method['sha256']:
                    raise ResourceError('观察方法不匹配任务实际试片方法', 'quality_observation_invalid')
            media = row.get('media_id')
            if media:
                output(job, media)
            result = row.get('result')
            if result not in {'usable', 'failed', 'unknown'} or (result == 'usable' and not media):
                raise ResourceError('可用观察必须有真实媒体；未知不能算通过', 'quality_observation_invalid')
            if result in {'usable', 'failed'} and job['status'] not in {'succeeded', 'failed'}:
                raise ResourceError('尚未完成的任务只能记录unknown，不能提前判为成败', 'quality_observation_invalid')
            if not isinstance(row.get('observation'), str) or not row['observation'].strip():
                raise ResourceError('必须先写可观察现象', 'quality_observation_invalid')
            code = row.get('defect_code')
            if result == 'failed' and (not isinstance(code, str) or not code.strip()):
                raise ResourceError('失败观察必须分类 defect_code', 'quality_observation_invalid')
            position = row.get('position')
            if not isinstance(position, dict) or (media and not position):
                raise ResourceError('媒体观察须有定位 position', 'quality_observation_invalid')
            # Position contains measurements/text only, never hidden resource IDs.
            if any(k.endswith(('_id', '_ref', '_ids', '_refs')) for k in position):
                raise ResourceError('位置不得藏资源引用', 'quality_observation_invalid')
            for key in ('effort_seconds', 'wait_seconds'):
                value = row.get(key)
                if value is not None and (type(value) is not int or value < 0):
                    raise ResourceError(key + ' 需非负整数或未知null', 'quality_observation_invalid')
            basis, amount = row.get('cost_basis', 'unknown'), row.get('cost_amount')
            if basis not in {'actual', 'estimate', 'unknown'} or (basis == 'unknown' and amount is not None):
                raise ResourceError('费用须区分实际/估算/未知', 'quality_observation_invalid')
            if amount is not None and (not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount < 0 or not row.get('cost_unit')):
                raise ResourceError('费用需有限非负数及单位', 'quality_observation_invalid')
            identity = (job['id'], media, code)
            if identity in seen:
                raise ResourceError('同文档不重复记录同一观察', 'quality_observation_invalid')
            seen.add(identity)
            values = {key: row.get(key) for key in ('job_id', 'media_id', 'criteria_artifact_id', 'method_artifact_id',
                'defect_code', 'observation', 'position', 'effort_seconds', 'wait_seconds', 'cost_amount', 'cost_unit')}
            conn.execute(insert(S.quality_observations).values(project_id=p, id=str(uuid.uuid5(uuid.UUID(artifact_id), str(n))),
                artifact_id=artifact_id, result=result, cost_basis=basis, **values))
    else:
        for key in ('method_artifact_id', 'trial_run_id', 'criteria_artifact_id'):
            artifact(document.get(key))
        trial = json.loads(artifact(document['trial_run_id'])['document'])
        if trial.get('phase') != 'trial':
            raise ResourceError('方法评测须来自受控 trial run', 'quality_evaluation_invalid')
        method = artifact(document['method_artifact_id'])
        if trial.get('trial', {}).get('method_sha256') != method['sha256']:
            raise ResourceError('评测方法不匹配试片实际固定方法', 'quality_evaluation_invalid')
        baseline = store._one(conn, S.media_items, p, document.get('baseline_media_id'))
        candidate = store._one(conn, S.media_items, p, document.get('output_media_id'))
        if baseline['id'] == candidate['id'] or baseline['modality'] != candidate['modality']:
            raise ResourceError('评测须有不同且同模态的基线媒体', 'quality_evaluation_invalid')
        jobs = list(conn.execute(select(S.generation_jobs).join(S.job_outputs,
            (S.job_outputs.c.project_id == S.generation_jobs.c.project_id) & (S.job_outputs.c.job_id == S.generation_jobs.c.id)).where(
                S.generation_jobs.c.project_id == p, S.generation_jobs.c.run_version_id == document['trial_run_id'],
                S.job_outputs.c.media_id == candidate['id'])).mappings())
        if len(jobs) != 1:
            raise ResourceError('评测输出须能唯一定位真实试片任务', 'quality_evaluation_invalid')
        job = jobs[0]
        model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == job['model_id'])).mappings().one()
        if document.get('environment_sha256') != environment_digest(model, job['request_payload']):
            raise ResourceError('评测环境不匹配实际模型版本/能力/控制参数', 'quality_evaluation_invalid')
        if document.get('result') not in {'pass', 'fail', 'unknown'} or not isinstance(document.get('observations'), str) or not document['observations'].strip():
            raise ResourceError('评测须记录观察和结果，不能裸写pass', 'quality_evaluation_invalid')
        criteria = artifact(document['criteria_artifact_id'])
        for media in (baseline, candidate):
            reviews = list(conn.execute(select(S.media_reviews).join(S.binding_candidates,
                (S.binding_candidates.c.project_id == S.media_reviews.c.project_id) & (S.binding_candidates.c.id == S.media_reviews.c.candidate_id)).where(
                    S.media_reviews.c.project_id == p, S.binding_candidates.c.media_id == media['id'], S.media_reviews.c.reviewer_type == 'human',
                    S.media_reviews.c.criteria_version == criteria['sha256']).order_by(S.media_reviews.c.project_revision.desc())).mappings())
            if not reviews:
                raise ResourceError('基线和试片媒体都需要固定判据的实际人工审查证据', 'quality_evaluation_invalid')
            if media['id'] == candidate['id'] and document['result'] == 'pass' and reviews[0]['outcome'] != 'pass':
                raise ResourceError('最新人工审查未通过，评测不能标pass', 'quality_evaluation_invalid')
        keys = ('method_artifact_id', 'trial_run_id', 'baseline_media_id', 'output_media_id', 'criteria_artifact_id', 'result', 'environment_sha256')
        conn.execute(insert(S.method_evaluations).values(project_id=p, id=str(uuid.uuid5(uuid.UUID(artifact_id), 'evaluation')),
            artifact_id=artifact_id, **{key: document[key] for key in keys}))
    return True


def repeated_failures(store, conn, p, shot_id, purpose):
    """Count unique jobs by defect across all methods/runs, including renamed ones."""
    rows = conn.execute(select(S.quality_observations).join(S.generation_jobs,
        (S.generation_jobs.c.project_id == S.quality_observations.c.project_id) & (S.generation_jobs.c.id == S.quality_observations.c.job_id)).where(
            S.quality_observations.c.project_id == p, S.generation_jobs.c.shot_id == shot_id,
            S.generation_jobs.c.purpose == purpose, S.quality_observations.c.result == 'failed')).mappings()
    defects = defaultdict(set)
    for row in rows:
        # Even revoked observations remain history; a later correction cannot
        # silently delete budget or reset a stop. Explicit route evidence is used.
        decisions = conn.execute(select(S.artifact_decisions.c.id).where(S.artifact_decisions.c.project_id == p,
            S.artifact_decisions.c.artifact_id == row['artifact_id'], S.artifact_decisions.c.outcome == 'approve')).first()
        if decisions:
            defects[row['defect_code']].add(row['job_id'])
    return {code: sorted(jobs) for code, jobs in defects.items()}
