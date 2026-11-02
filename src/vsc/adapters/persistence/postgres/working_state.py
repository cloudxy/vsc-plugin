"""Transactional working choices and episode-local media references."""
import json

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from . import schema as S
from .values import checked_id, clean, new_id


class WorkingStateRepository:
    def _working_selection(self, conn, p, shot_id, output_kind):
        return conn.execute(select(S.working_selection_versions).join(S.current_working_selections,
            and_(S.current_working_selections.c.project_id==S.working_selection_versions.c.project_id,
                 S.current_working_selections.c.selection_version_id==S.working_selection_versions.c.id))
            .where(S.current_working_selections.c.project_id==p,
                   S.current_working_selections.c.shot_id==shot_id,
                   S.current_working_selections.c.output_kind==output_kind)).mappings().first()

    def _save_working_selection(self, conn, project, payload, actor, *, automatic=False):
        p=project['id'];shot=checked_id(payload['shot_id']);kind=payload['output_kind']
        self._one(conn,S.shots,p,shot)
        current=self._working_selection(conn,p,shot,kind)
        if (current['id'] if current else None)!=payload.get('base_version_id'):
            if automatic:
                return {'selected':False,'reason':'working_selection_changed','selection_version_id':current['id'] if current else None}
            raise Conflict('本镜工作选取已有更新，请重新读取比较','working_selection_conflict')
        candidate_id=payload.get('candidate_id');media=None
        if candidate_id:
            candidate=self._one(conn,S.binding_candidates,p,checked_id(candidate_id))
            slot=self._one(conn,S.binding_slots,p,candidate['slot_id'])
            media=self._media(conn,p,candidate['media_id'])
            if slot['target_object_id']!=shot or media['modality']!=kind:
                raise ResourceError('候选不属于本镜头或输出类型','working_candidate_scope')
        event='auto_select' if automatic else payload.get('event_kind') or ('select' if candidate_id else 'clear')
        if event=='clear' and candidate_id or event!='clear' and not candidate_id:
            raise ResourceError('取消工作选取须明确空候选','working_selection_shape')
        if event=='trim' and (not current or current['candidate_id']!=candidate_id):
            raise Conflict('裁剪必须基于当前选中候选','working_trim_conflict')
        start=end=None
        if media and kind=='video':
            if not media.get('duration_ms'):
                raise ResourceError('候选缺少实测时长，不能保存工作裁剪','working_duration_missing')
            start=payload.get('trim_in_ms',current['trim_in_ms'] if event=='trim' else 0)
            end=payload.get('trim_out_ms',current['trim_out_ms'] if event=='trim' else media['duration_ms'])
            if type(start) is not int or type(end) is not int or not 0<=start<end<=media['duration_ms']:
                raise ResourceError('裁剪区间须位于原片实际时长内','working_trim_range')
        elif 'trim_in_ms' in payload or 'trim_out_ms' in payload:
            raise ResourceError('只有已选视频可以裁剪','working_trim_kind')
        identifier=new_id();version=(current['version']+1 if current else 1)
        values=dict(project_id=p,id=identifier,shot_id=shot,output_kind=kind,version=version,
            candidate_id=candidate_id,event_kind=event,trim_in_ms=start,trim_out_ms=end,
            source_job_id=payload.get('source_job_id') if automatic else None,created_by=actor)
        conn.execute(insert(S.working_selection_versions).values(**values))
        conn.execute(pg_insert(S.current_working_selections).values(project_id=p,id=new_id(),shot_id=shot,
            output_kind=kind,selection_version_id=identifier).on_conflict_do_update(
            index_elements=['project_id','shot_id','output_kind'],set_={'selection_version_id':identifier}))
        return dict(values,selection_version_id=identifier,media_id=media['id'] if media else None,selected=bool(candidate_id))

    def save_working_selection(self, p, payload, **kw):
        return self._mutate(p,'save_working_selection',payload,
            callback=lambda conn,project:self._save_working_selection(conn,project,payload,kw['actor']),**kw)

    def auto_select_working_candidate(self, p, payload, **kw):
        """Completion consumer passes its captured head; late results cannot undo user edits."""
        return self._mutate(p,'auto_select_working_candidate',payload,
            callback=lambda conn,project:self._save_working_selection(conn,project,payload,kw['actor'],automatic=True),**kw)

    def _auto_select_working_candidate(self,conn,project,job,candidate_id):
        """Called after job_outputs inside the producer's existing project transaction."""
        if job['modality'] not in {'image','video'} or job['purpose']=='depth' or job['request_payload'].get('operation') == 'subject_detect':
            return {'selected':False,'reason':'working_selection_kind_unsupported'}
        p=project['id']
        reference=conn.execute(select(S.workbench_run_inputs).where(S.workbench_run_inputs.c.project_id==p,
            S.workbench_run_inputs.c.run_version_id==job['run_version_id'],
            S.workbench_run_inputs.c.shot_id==job['shot_id'],S.workbench_run_inputs.c.output_kind==job['modality'])).mappings().first()
        if not reference:return {'selected':False,'reason':'not_working_run'}
        latest=conn.execute(select(S.workbench_run_inputs.c.run_version_id).join(S.artifact_versions,
            and_(S.artifact_versions.c.project_id==p,S.artifact_versions.c.id==S.workbench_run_inputs.c.run_version_id))
            .where(S.workbench_run_inputs.c.project_id==p,S.workbench_run_inputs.c.shot_id==job['shot_id'],
                   S.workbench_run_inputs.c.output_kind==job['modality'])
            .order_by(S.artifact_versions.c.created_at.desc(),S.artifact_versions.c.id.desc()).limit(1)).scalar_one()
        if latest!=job['run_version_id']:return {'selected':False,'reason':'newer_working_run'}
        first=conn.execute(select(func.min(S.generation_jobs.c.candidate_no)).where(
            S.generation_jobs.c.project_id==p,S.generation_jobs.c.run_version_id==job['run_version_id'],
            S.generation_jobs.c.shot_id==job['shot_id'],S.generation_jobs.c.modality==job['modality'])).scalar_one()
        if job['candidate_no']!=first:return {'selected':False,'reason':'not_primary_candidate'}
        return self._save_working_selection(conn,project,dict(shot_id=job['shot_id'],output_kind=job['modality'],
            candidate_id=candidate_id,source_job_id=job['id'],base_version_id=reference['base_selection_version_id']),
            'working-generation:'+job['id'],automatic=True)

    def list_working_selections(self,p,episode_id=None,shot_id=None):
        with self.engine.connect() as conn:
            project=self._project(conn,p)
            query=select(S.working_selection_versions,S.binding_candidates.c.media_id).join(S.current_working_selections,
                and_(S.current_working_selections.c.project_id==S.working_selection_versions.c.project_id,
                     S.current_working_selections.c.selection_version_id==S.working_selection_versions.c.id))
            query=query.outerjoin(S.binding_candidates,and_(S.binding_candidates.c.project_id==S.working_selection_versions.c.project_id,
                S.binding_candidates.c.id==S.working_selection_versions.c.candidate_id)).where(S.working_selection_versions.c.project_id==p)
            if episode_id:
                self._one(conn,S.episodes,p,checked_id(episode_id))
                query=query.join(S.shots,and_(S.shots.c.project_id==p,S.shots.c.id==S.working_selection_versions.c.shot_id)).join(
                    S.sequences,and_(S.sequences.c.project_id==p,S.sequences.c.id==S.shots.c.parent_id)).join(
                    S.scenes,and_(S.scenes.c.project_id==p,S.scenes.c.id==S.sequences.c.parent_id)).where(S.scenes.c.parent_id==episode_id)
                query=query.order_by(S.scenes.c.ordinal,S.sequences.c.ordinal,S.shots.c.ordinal,S.working_selection_versions.c.output_kind)
            else:
                query=query.order_by(S.working_selection_versions.c.shot_id,S.working_selection_versions.c.output_kind)
            if shot_id:
                self._one(conn,S.shots,p,checked_id(shot_id));query=query.where(S.working_selection_versions.c.shot_id==shot_id)
            items=[dict(row,selection_version_id=row['id']) for row in conn.execute(query).mappings()]
            return clean(dict(items=items,revision=project['revision']))

    def _project_classic_draft_media(self,conn,project,artifact,document):
        """Only called inside the artifact-save transaction, including explicit legacy backfill."""
        p=project['id'];identifier=artifact['id']
        rows=conn.execute(select(S.classic_draft_media).where(S.classic_draft_media.c.project_id==p,
            S.classic_draft_media.c.draft_version_id==identifier).order_by(S.classic_draft_media.c.ordinal)).mappings().all()
        if rows:
            if len(rows)!=len(document.get('references',[])):
                raise ResourceError('已固定草稿引用集合不完整','working_reference_incomplete')
            return [dict(r) for r in rows]
        result=[]
        for ordinal,ref in enumerate(document.get('references',[])):
            media=self._media(conn,p,checked_id(ref['media_id']))
            if ref.get('sha256')!=media['sha256']:
                raise ResourceError('旧草稿引用缺少可核实摘要，请重新保存','working_reference_unverifiable')
            row=dict(project_id=p,id=new_id(),draft_version_id=identifier,ordinal=ordinal,
                role=ref['role'],reference_key=ref.get('reference_key',ref['role']+':'+media['id']),
                display_name=ref.get('display_name',media['name']),media_id=media['id'],
                blob_id=media['blob_id'],blob_sha256=media['sha256'],
                episode_asset_form_version_id=ref.get('episode_asset_form_version_id'),annotation_artifact_id=ref.get('annotation_id'))
            conn.execute(insert(S.classic_draft_media).values(**row));result.append(row)
        return result

    def get_classic_draft_inputs(self,p,draft_version_id):
        with self.engine.connect() as conn:
            artifact=self._one(conn,S.artifact_versions,p,checked_id(draft_version_id))
            if artifact['artifact_type']!='classic-production-draft':
                raise ResourceError('需要固定经典制作草稿','classic_draft_required')
            document=json.loads(artifact['document'])
            rows=[dict(row) for row in conn.execute(select(S.classic_draft_media).where(
                S.classic_draft_media.c.project_id==p,S.classic_draft_media.c.draft_version_id==draft_version_id)
                .order_by(S.classic_draft_media.c.ordinal)).mappings()]
            gaps=[]
            if len(rows)!=len(document.get('references',[])):
                gaps.append({'code':'working_reference_incomplete','message':'旧草稿引用尚未固定，请重新保存或明确回填'})
            return clean(dict(items=rows,draft_version_id=draft_version_id,draft_sha256=artifact['sha256'],legacy=bool(gaps),gaps=gaps))

    def backfill_classic_draft_inputs(self,p,payload,**kw):
        def work(conn,project):
            artifact=self._one(conn,S.artifact_versions,p,checked_id(payload['draft_version_id']))
            if artifact['artifact_type']!='classic-production-draft':raise ResourceError('只能回填经典制作草稿')
            rows=self._project_classic_draft_media(conn,project,artifact,json.loads(artifact['document']))
            return dict(draft_version_id=artifact['id'],count=len(rows))
        return self._mutate(p,'backfill_classic_draft_inputs',payload,callback=work,**kw)

    def save_episode_asset(self,p,payload,**kw):
        def work(conn,project):
            episode=checked_id(payload['episode_id']);self._one(conn,S.episodes,p,episode)
            identifier=checked_id(payload['id']) if payload.get('id') else new_id()
            prior=self._one(conn,S.episode_assets,p,identifier) if payload.get('id') else None
            if prior and prior['episode_id']!=episode:raise ResourceError('集资产条目属于其他集','episode_asset_scope')
            if payload['base_revision']!=(prior['revision'] if prior else 0):
                raise Conflict('本集资产已有更新，请重新读取比较','episode_asset_conflict')
            values=dict(episode_id=episode,asset_key=payload['asset_key'],name=payload['name'],
                asset_kind=payload['asset_kind'],revision=payload['base_revision']+1)
            if prior:
                if prior['asset_key']!=values['asset_key'] or prior['asset_kind']!=values['asset_kind']:
                    raise ResourceError('稳定资产键和类型不可通过改名改变','episode_asset_identity')
                conn.execute(update(S.episode_assets).where(S.episode_assets.c.project_id==p,S.episode_assets.c.id==identifier).values(**values))
            else:conn.execute(insert(S.episode_assets).values(project_id=p,id=identifier,**values))
            output=[]
            for form in payload.get('forms',[]):
                existing=conn.execute(select(S.episode_asset_forms).where(S.episode_asset_forms.c.project_id==p,
                    S.episode_asset_forms.c.episode_asset_id==identifier,S.episode_asset_forms.c.form_key==form['form_key'])).mappings().first()
                base=existing['current_version_id'] if existing else None
                if base!=form.get('base_version_id'):
                    raise Conflict('本集形态已有更新，请重新读取比较','episode_form_conflict')
                form_id=existing['id'] if existing else new_id()
                source=checked_id(form['source_asset_id']) if form.get('source_asset_id') else None
                spec=checked_id(form['spec_id']) if form.get('spec_id') else None
                if bool(source)!=bool(spec):raise ResourceError('源资产和固定形态版本必须同时指定','episode_form_source')
                if source:
                    asset=self._one(conn,S.asset_identities,p,source)
                    specification=self._one(conn,S.asset_spec_versions,p,spec)
                    if specification['asset_id']!=source or asset['asset_kind']!=values['asset_kind']:
                        raise ResourceError('源资产类型或形态版本不匹配','episode_form_source')
                media=self._media(conn,p,checked_id(form['media_id'])) if form.get('media_id') else None
                if media and media['modality']!=('audio' if values['asset_kind']=='voice' else 'image'):
                    raise ResourceError('本集资产形态媒体类型不匹配','episode_form_media')
                if not existing:
                    conn.execute(insert(S.episode_asset_forms).values(project_id=p,id=form_id,episode_asset_id=identifier,
                        form_key=form['form_key'],name=form['name']))
                version=self._one(conn,S.episode_asset_form_versions,p,base)['version']+1 if base else 1
                vid=new_id();row=dict(project_id=p,id=vid,form_id=form_id,version=version,asset_name=values['name'],form_name=form['name'],
                    source_asset_id=source,spec_id=spec,media_id=media['id'] if media else None,blob_id=media['blob_id'] if media else None,
                    blob_sha256=media['sha256'] if media else None,created_by=kw['actor'])
                conn.execute(insert(S.episode_asset_form_versions).values(**row))
                conn.execute(update(S.episode_asset_forms).where(S.episode_asset_forms.c.project_id==p,S.episode_asset_forms.c.id==form_id)
                    .values(name=form['name'],current_version_id=vid))
                output.append(dict(row,id=form_id,form_key=form['form_key'],version_id=vid))
            return dict(id=identifier,asset_revision=values['revision'],forms=output)
        return self._mutate(p,'save_episode_asset',payload,callback=work,**kw)

    def list_episode_assets(self,p,episode_id):
        with self.engine.connect() as conn:
            project=self._project(conn,p);self._one(conn,S.episodes,p,checked_id(episode_id))
            assets=[dict(row,forms=[]) for row in conn.execute(select(S.episode_assets).where(
                S.episode_assets.c.project_id==p,S.episode_assets.c.episode_id==episode_id)
                .order_by(S.episode_assets.c.created_at,S.episode_assets.c.id)).mappings()]
            by_id={a['id']:a for a in assets}
            if by_id:
                rows=conn.execute(select(S.episode_asset_forms,S.episode_asset_form_versions.c.version,
                    S.episode_asset_form_versions.c.source_asset_id,S.episode_asset_form_versions.c.spec_id,
                    S.episode_asset_form_versions.c.media_id,S.episode_asset_form_versions.c.blob_sha256,
                    S.episode_asset_form_versions.c.asset_name,S.episode_asset_form_versions.c.form_name)
                    .outerjoin(S.episode_asset_form_versions,and_(S.episode_asset_form_versions.c.project_id==p,
                        S.episode_asset_form_versions.c.id==S.episode_asset_forms.c.current_version_id))
                    .where(S.episode_asset_forms.c.project_id==p,S.episode_asset_forms.c.episode_asset_id.in_(by_id))
                    .order_by(S.episode_asset_forms.c.created_at,S.episode_asset_forms.c.id)).mappings()
                for row in rows:by_id[row['episode_asset_id']]['forms'].append(dict(row))
            return clean(dict(items=assets,revision=project['revision']))
