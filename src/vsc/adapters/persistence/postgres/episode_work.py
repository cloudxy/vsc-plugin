"""Continue an explicitly started episode batch into the original local editor.

Progress is reconstructed from original jobs and current working choices. There
is no second queue and no approval or generation retry in this consumer.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import String, and_, case, cast, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB

from vsc.assets.resource_service import ResourceError
from . import schema as S
from .editor_workspace import EditorWorkspaceRepository
from .values import CURRENT_REVISION, checked_id, clean


class _NoChange(Exception):
    pass


class EpisodeWorkRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def continuation_principal():
        from dataclasses import asdict
        from vsc.assets.access_control import current_principal
        principal = current_principal()
        return asdict(principal) if principal is not None else None

    @staticmethod
    def _document(artifact):
        body = artifact['document']
        return json.loads(body) if isinstance(body, (str, bytes, bytearray)) else body

    def _receipt(self, conn, p, key):
        return conn.execute(select(S.artifact_versions).where(
            S.artifact_versions.c.project_id == p,
            S.artifact_versions.c.artifact_key == key)).mappings().first()

    def _origin(self, conn, p, batch_id):
        # A user-created artifact with the same type cannot authorize automation.
        return conn.execute(select(S.project_revisions.c.actor).join(S.command_receipts,
            and_(S.command_receipts.c.project_id == S.project_revisions.c.project_id,
                 S.command_receipts.c.idempotency_key == S.project_revisions.c.command_key))
            .where(S.project_revisions.c.project_id == p,
                   S.project_revisions.c.action == 'generate_intelligent_work_batch',
                   S.command_receipts.c.response['batch_artifact_id'].astext == batch_id)
            .limit(1)).scalar_one_or_none()

    def _status(self, conn, project, batch_id, now, renderer_available):
        p = project['id']
        artifact = self.store._one(conn, S.artifact_versions, p, checked_id(batch_id))
        if artifact['artifact_type'] != 'intelligent-work-batch':
            raise ResourceError('需要原分集工作批次', 'invalid_intelligent_batch')
        body = self._document(artifact)
        origin = self._origin(conn, p, batch_id)
        if not origin:
            raise ResourceError('批次缺少原始提交授权', 'batch_authorization_missing')
        episode = checked_id(body['episode_id'])
        self.store._one(conn, S.episodes, p, episode)
        due = datetime.fromisoformat(body['execution_policy']['first_draft_due_at'].replace('Z', '+00:00'))
        result = dict(batch_artifact_id=batch_id, episode_id=episode,
            auto_first_cut=body['auto_first_cut'], first_draft_due_at=due,
            overdue=now >= due, status='waiting', gaps=[], warnings=[], jobs=[], revision=project['revision'])
        terminal = self._receipt(conn, p, 'intelligent-first-cut:' + batch_id)
        milestone = self._receipt(conn, p, 'intelligent-first-cut-due:' + batch_id)
        if milestone:
            result['deadline_receipt_id'] = milestone['id']
        if terminal:
            result.update(self._document(terminal))
            result['receipt_id'] = terminal['id']
            if result.get('render_job_id'):
                job = self.store._one(conn, S.edit_render_jobs, p, result['render_job_id'])
                result['status'] = job['status']
                result['render_error'] = job['error']
            return result, None, origin
        if not body['auto_first_cut']:
            result['status'] = 'manual'
            return result, None, origin
        current = conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id == p,
            S.edit_workspaces.c.episode_id == episode)).mappings().first()
        baseline = dict(workspace_id=current['id'] if current else None,
            edit_revision=current['revision'] if current else 0,
            edit_version_id=current['current_version_id'] if current else None)
        if baseline != body['edit_baseline']:
            result.update(status='edit_changed', gaps=[dict(code='edit_changed', reason='剪辑稿已被修改，保留当前版本')])
            return result, ('terminal', None), origin
        for item in body['blocked_items']:
            result['gaps'].append(dict(code='batch_unit_blocked', unit_key=item['unit_key'], details=item.get('gaps', [])))
        for run in body['runs']:
            original = self.store._one(conn, S.artifact_versions, p, run['run_artifact_id'])
            if original['sha256'] != run['run_sha256']:
                raise ResourceError('批次原运行摘要不符', 'batch_run_changed')
            selected = self.store._working_selection(conn, p, run['shot_id'], 'video')
            selected_media = None
            if selected and selected['candidate_id']:
                selected_media = self.store._one(conn, S.binding_candidates, p, selected['candidate_id'])['media_id']
            outputs = set()
            diagnostics = []
            for job_id in run['job_ids']:
                job = self.store._one(conn, S.generation_jobs, p, job_id)
                if job['run_version_id'] != original['id'] or job['shot_id'] != run['shot_id'] or job['modality'] != 'video':
                    raise ResourceError('批次原任务范围不符', 'batch_job_changed')
                result['jobs'].append(dict(id=job_id, status=job['status']))
                if job['status'] == 'succeeded':
                    outputs.update(conn.execute(select(S.job_outputs.c.media_id).where(
                        S.job_outputs.c.project_id == p, S.job_outputs.c.job_id == job_id)).scalars())
                else:
                    diagnostics.append(dict(code='job_' + job['status'], shot_id=run['shot_id'], job_id=job_id))
            if selected_media not in outputs:
                result['gaps'].extend(diagnostics)
                result['gaps'].append(dict(code='batch_video_not_selected', shot_id=run['shot_id'],
                    reason='尚未选中本批成功视频；保留用户当前选择'))
        seed = None
        if not result['gaps']:
            seed = EditorWorkspaceRepository(self.store).seed(p, episode, _transaction=(conn, project))
            result['gaps'].extend(gap for gap in seed['gaps'] if gap.get('severity') != 'warning')
            result['warnings'].extend(gap for gap in seed['gaps'] if gap.get('severity') == 'warning')
            if seed['shot_count'] != len(seed['document']['clips']) or not seed['document']['clips']:
                result['gaps'].append(dict(code='episode_video_incomplete', reason='本集仍有镜头缺少视频'))
            if not renderer_available:
                result['gaps'].append(dict(code='edit_renderer_unavailable', reason='本机合成器或素材存储不可用'))
        if not result['gaps']:
            result['status'] = 'ready'
            return result, ('render', seed), origin
        if now >= due and not milestone:
            return result, ('milestone', None), origin
        return result, None, origin

    def status(self, p, batch_id, *, renderer_available=True, now=None):
        with self.store.engine.connect() as conn:
            value, _, _ = self._status(conn, self.store._project(conn, p), batch_id,
                now or datetime.now(timezone.utc), renderer_available)
            return clean(value)

    def advance(self, p, batch_id, *, renderer_available=True, now=None, actor=None):
        now = now or datetime.now(timezone.utc)
        with self.store.engine.connect() as conn:
            value, action, origin = self._status(conn, self.store._project(conn, p), batch_id, now, renderer_available)
        if action is None:
            return clean(value)
        background = actor is None
        actor = actor or origin

        def work(conn, project):
            value, action, _ = self._status(conn, project, batch_id, now, renderer_available)
            if action is None:
                raise _NoChange()
            kind, seed = action
            if kind == 'render':
                editor = EditorWorkspaceRepository(self.store)
                kw = dict(actor=actor, expected_revision=project['revision'],
                    idempotency_key='episode-first-cut', _transaction=(conn, project))
                saved = editor.save(p, dict(episode_id=value['episode_id'],
                    edit_revision=(self._document(self.store._one(conn, S.artifact_versions, p, batch_id))['edit_baseline']['edit_revision']),
                    document=seed['document']), **kw)
                job = editor.request(p, dict(edit_version_id=saved['edit_version_id']), **kw)
                value.update(status=job['status'], edit_version_id=saved['edit_version_id'], render_job_id=job['id'])
            key = ('intelligent-first-cut-due:' if kind == 'milestone' else 'intelligent-first-cut:') + batch_id
            receipt = self.store._create_artifact(conn, project, dict(artifact_key=key,
                artifact_type='intelligent-first-cut-receipt', object_ids=[value['episode_id']],
                dependency_ids=[batch_id], document=dict(value, recorded_at=now.isoformat(),
                    milestone='deadline_gap' if kind == 'milestone' else 'first_cut', professional_review='not_reviewed')))
            value['deadline_receipt_id' if kind == 'milestone' else 'receipt_id'] = receipt['id']
            return value
        try:
            from vsc.assets.access_control import Principal, set_principal, reset_principal
            principal_token = None
            if background:
                with self.store.engine.connect() as conn:
                    body = self._document(self.store._one(conn,S.artifact_versions,p,batch_id))
                if body.get('continuation_principal') is not None:
                    principal_token = set_principal(Principal(**body['continuation_principal']))
            try:
                return self.store._mutate(p, 'advance_intelligent_work_batch', {'batch_artifact_id': batch_id},
                    expected_revision=CURRENT_REVISION,
                    idempotency_key=('episode-due:' if action[0] == 'milestone' else 'episode-first-cut:') + batch_id,
                    actor=actor, callback=work)
            finally:
                if principal_token is not None:reset_principal(principal_token)
        except _NoChange:
            return self.status(p, batch_id, now=now, renderer_available=renderer_available)

    def pending(self, p=None, limit=50, after=None):
        artifact = S.artifact_versions
        terminal = artifact.alias('first_cut_terminal')
        authorized = exists(select(S.command_receipts.c.project_id).join(S.project_revisions,
            and_(S.command_receipts.c.project_id == S.project_revisions.c.project_id,
                 S.command_receipts.c.idempotency_key == S.project_revisions.c.command_key))
            .where(S.project_revisions.c.project_id == artifact.c.project_id,
                   S.project_revisions.c.action == 'generate_intelligent_work_batch',
                   S.command_receipts.c.response['batch_artifact_id'].astext == artifact.c.id.cast(String)))
        query = select(artifact.c.project_id, artifact.c.id, artifact.c.document).where(
            artifact.c.artifact_type == 'intelligent-work-batch', authorized,
            cast(case((authorized, func.convert_from(artifact.c.document, 'UTF8')), else_='{}'),
                 JSONB)['auto_first_cut'].as_boolean().is_(True),
            ~exists(select(terminal.c.id).where(terminal.c.project_id == artifact.c.project_id,
                terminal.c.artifact_key == 'intelligent-first-cut:' + artifact.c.id.cast(String))))
        if p:
            query = query.where(artifact.c.project_id == checked_id(p))
        if after:
            from sqlalchemy import or_
            query = query.where(or_(artifact.c.created_at > after[0],
                and_(artifact.c.created_at == after[0], artifact.c.id > checked_id(after[1]))))
        with self.store.engine.connect() as conn:
            rows = conn.execute(query.add_columns(artifact.c.created_at).order_by(artifact.c.created_at, artifact.c.id).limit(limit)).mappings()
            return [dict(project_id=row['project_id'], id=row['id'], scan_cursor=(row['created_at'],row['id'])) for row in rows
                    if self._document(row).get('auto_first_cut') is True]
