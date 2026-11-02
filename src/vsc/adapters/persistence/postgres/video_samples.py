"""Resolve native sample provenance through existing project/job output FKs."""
from sqlalchemy import select

from vsc.assets.resource_service import ResourceError
from vsc.production.video_samples import bind_sample
from . import schema as S
from .values import checked_id


def resolve_sample(store, conn, project, logical, model, *, now=None):
    """Called within the original project transaction; never accept a task ID.

    The media FK selects the job, and the job's stored provider receipt selects
    the remote draft. No URL, environment variable name, or client task ID is
    used as an account or source identity.
    """
    p=project['id'];source=store._media(conn,p,checked_id(logical.get('source_media_id')))
    if logical.get('operation')!='draft_upgrade' or (logical.get('source_sha256'),logical.get('source_duration_ms'))!=(source['sha256'],source['duration_ms']):
        raise ResourceError('升级来源必须固定原样片摘要和真实时长','sample_output_mismatch')
    jobs=conn.execute(select(S.generation_jobs.c.id).join(S.job_outputs,
        (S.job_outputs.c.project_id==S.generation_jobs.c.project_id)&
        (S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(
        S.job_outputs.c.project_id==p,S.job_outputs.c.media_id==source['id'])).scalars().all()
    if len(jobs)!=1:
        raise ResourceError('来源必须是唯一原生样片任务的登记输出','sample_job_required')
    job=store._job_detail(conn,project,str(jobs[0]))
    return bind_sample(job,source,model,model['provider_id'],now=now)
