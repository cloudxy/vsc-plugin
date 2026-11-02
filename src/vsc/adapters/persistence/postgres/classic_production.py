"""Classic mode work drafts reuse artifact versions and command receipts."""
from sqlalchemy import select
import json
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.assets.classic_production import DRAFT_TYPE, draft_key
from . import schema as S
from .values import checked_id, clean


class ClassicProductionRepository:
    def next_classic_candidate(self, project_id, shot_id, purpose):
        from sqlalchemy import func
        with self.engine.connect() as conn:
            self._one(conn, S.shots, project_id, checked_id(shot_id))
            latest = conn.scalar(select(func.max(S.generation_jobs.c.candidate_no)).where(
                S.generation_jobs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                S.generation_jobs.c.purpose == purpose))
            return 0 if latest is None else latest + 1

    def list_working_candidates(self, project_id, shot_id, output_kind, *, offset=0, limit=24, filter_kind='all'):
        from sqlalchemy import and_, func, union, exists
        from .classic_preferences import favorite_identity, local_media_predicate

        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._access_require(conn, project_id, 'read')
            self._one(conn, S.shots, project_id, checked_id(shot_id))
            candidates = select(S.binding_candidates.c.media_id).join(S.binding_slots, and_(
                S.binding_slots.c.project_id == S.binding_candidates.c.project_id,
                S.binding_slots.c.id == S.binding_candidates.c.slot_id)).where(
                S.binding_candidates.c.project_id == project_id,
                S.binding_slots.c.target_object_id == shot_id)
            outputs = select(S.job_outputs.c.media_id).join(S.generation_jobs, and_(
                S.generation_jobs.c.project_id == S.job_outputs.c.project_id,
                S.generation_jobs.c.id == S.job_outputs.c.job_id)).where(
                S.job_outputs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                S.generation_jobs.c.modality == output_kind, S.generation_jobs.c.purpose != 'depth',
                S.generation_jobs.c.request_payload['operation'].as_string().is_distinct_from('subject_detect'))
            ids = union(candidates, outputs).subquery()
            query = self._media_query(project_id).where(S.media_items.c.modality == output_kind,
                S.media_items.c.id.in_(select(ids.c.media_id)))
            identity = favorite_identity(self, conn)
            favorite = exists(select(S.classic_media_favorites.c.id).where(
                S.classic_media_favorites.c.project_id == project_id,
                S.classic_media_favorites.c.identity_id == identity,
                S.classic_media_favorites.c.media_id == S.media_items.c.id,
                S.classic_media_favorites.c.active.is_(True)))
            if filter_kind == 'favorites': query = query.where(favorite)
            if filter_kind == 'local': query = query.where(local_media_predicate(project_id))
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = [dict(row) for row in conn.execute(query.order_by(
                S.media_items.c.created_at.desc(), S.media_items.c.id).offset(offset).limit(limit)).mappings()]
            page_ids = [row['id'] for row in rows]
            selection = conn.execute(select(S.working_selection_versions, S.binding_candidates.c.media_id)
                .join(S.current_working_selections, and_(
                    S.current_working_selections.c.project_id == S.working_selection_versions.c.project_id,
                    S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id))
                .outerjoin(S.binding_candidates, and_(
                    S.binding_candidates.c.project_id == S.working_selection_versions.c.project_id,
                    S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id))
                .where(S.working_selection_versions.c.project_id == project_id,
                    S.working_selection_versions.c.shot_id == shot_id,
                    S.working_selection_versions.c.output_kind == output_kind)).mappings().first()
            candidate_by_media, job_by_media = {}, {}
            favorites = {r['media_id']: r for r in conn.execute(select(S.classic_media_favorites).where(
                S.classic_media_favorites.c.project_id == project_id,
                S.classic_media_favorites.c.identity_id == identity,
                S.classic_media_favorites.c.media_id.in_(page_ids))).mappings()}
            local_ids = set(conn.execute(select(S.media_items.c.id).where(S.media_items.c.project_id == project_id,
                S.media_items.c.id.in_(page_ids), local_media_predicate(project_id))).scalars())
            if page_ids:
                for row in conn.execute(select(S.binding_candidates).join(S.binding_slots, and_(
                    S.binding_slots.c.project_id == S.binding_candidates.c.project_id,
                    S.binding_slots.c.id == S.binding_candidates.c.slot_id)).where(
                    S.binding_candidates.c.project_id == project_id,
                    S.binding_slots.c.target_object_id == shot_id,
                    S.binding_candidates.c.media_id.in_(page_ids)).order_by(
                        S.binding_candidates.c.created_at, S.binding_candidates.c.id)).mappings():
                    candidate_by_media[row['media_id']] = row['id']
                for row in conn.execute(select(S.job_outputs.c.media_id,
                    S.generation_jobs.c.id, S.generation_jobs.c.status, S.generation_jobs.c.request_payload,
                    S.generation_jobs.c.raw_response).join(S.generation_jobs, and_(
                        S.generation_jobs.c.project_id == S.job_outputs.c.project_id,
                        S.generation_jobs.c.id == S.job_outputs.c.job_id)).where(
                    S.job_outputs.c.project_id == project_id, S.generation_jobs.c.shot_id == shot_id,
                    S.job_outputs.c.media_id.in_(page_ids)).order_by(
                        S.generation_jobs.c.created_at, S.generation_jobs.c.id)).mappings():
                    job_by_media[row['media_id']] = row
            items = []
            for row in rows:
                selected = bool(selection and selection['media_id'] == row['id'])
                job = job_by_media.get(row['id'], {})
                sample=None
                if job.get('request_payload',{}).get('draft') is True:
                    from vsc.production.video_samples import sample_deadline
                    try:sample={'expires_at':sample_deadline((job.get('raw_response') or {}).get('created_at')).isoformat()}
                    except ResourceError as error:sample={'unavailable':str(error)}
                items.append({key: row.get(key) for key in (
                    'id', 'name', 'modality', 'sha256', 'duration_ms', 'width', 'height', 'created_at')})
                items[-1].update(media_id=row['id'], candidate_id=selection['candidate_id'] if selected
                    else candidate_by_media.get(row['id']), job_id=job.get('id'),
                    job_status=job.get('status'), selected=selected,
                    native_sample=sample, favorite=favorites.get(row['id'], {}).get('active', False),
                    favorite_version=favorites.get(row['id'], {}).get('version', 0),
                    local=row['id'] in local_ids, can_favorite=bool(identity),
                    selection_version_id=selection['id'] if selection else None,
                    trim_in_ms=selection['trim_in_ms'] if selected else 0,
                    trim_out_ms=selection['trim_out_ms'] if selected else row.get('duration_ms'))
            return clean({'items': items, 'total': total,
                'next_offset': offset + len(items) if offset + len(items) < total else None,
                'revision': project['revision']})

    def list_classic_drafts(self, project_id, shot_id):
        with self.engine.connect() as conn:
            project = self._project(conn, checked_id(project_id))
            self._one(conn, S.shots, project["id"], checked_id(shot_id))
            rows = conn.execute(select(S.artifact_versions).where(
                S.artifact_versions.c.project_id == project["id"], S.artifact_versions.c.artifact_type == DRAFT_TYPE,
                S.artifact_versions.c.artifact_key.like("classic:" + shot_id + ":%"))
                .order_by(S.artifact_versions.c.version)).mappings()
            latest = {}
            for row in rows:
                latest[row["artifact_key"]] = {key: row[key] for key in ("id", "version", "sha256", "document", "created_at")}
                latest[row["artifact_key"]]["document"] = json.loads(row["document"])
            return clean({"items": list(latest.values()), "revision": project["revision"]})

    def save_classic_draft(self, project_id, payload, *, build_document, **kw):
        def work(conn, project):
            document = build_document(project_id, payload["document"])
            key = draft_key(document["shot_id"], document["mode"])
            current = conn.execute(select(S.artifact_versions.c.id).where(
                S.artifact_versions.c.project_id == project["id"], S.artifact_versions.c.artifact_key == key)
                .order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if (str(current) if current else None) != payload.get("base_draft_id"):
                raise Conflict("此模式已有更新草稿；输入保留，请先读取比较", "classic_draft_conflict")
            dependencies = [document['tool_settings']['mask_export_id']] if document['mode'] in {'image_inpaint','image_watermark'} and document.get('tool_settings',{}).get('mask_export_id') else []
            if document['mode'] == 'digital_human' and document.get('subject_selection'):
                from .workbench_generation import subject_sources
                dependencies.append(subject_sources(self, conn, project['id'], document)['dependency_id'])
            from .professional_inputs import resolve_professional_inputs
            dependencies.extend(resolve_professional_inputs(self,conn,project,document)['dependency_ids'])
            artifact = self._create_artifact(conn, project, {"artifact_key": key, "artifact_type": DRAFT_TYPE,
                "stage": "production", "document": document, "object_ids": [document["shot_id"]], "supersedes_id": current,
                "dependency_ids":dependencies})
            self._project_classic_draft_media(conn, project, artifact, document)
            return artifact
        return self._mutate(project_id, "save_classic_draft", payload, callback=work, **kw)

    def generate_workbench(self, project_id, payload, *, build_preview, actor, canvas_auto_authorization=None, **kw):
        from sqlalchemy import insert
        from .values import new_id
        from .workbench_generation import RUN_TYPE

        def work(conn, project):
            preview = build_preview(project_id, payload["request"])
            if not preview["ready"]:
                raise ResourceError("输入或模型仍有缺项，请在当前页补齐", "classic_not_ready")
            if preview["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("输入、模型或报价已改变，请确认更新后的报价", "classic_preview_changed")
            if preview["artifact"]["artifact_type"] != RUN_TYPE:
                raise ResourceError("生成入口只接受固定工作请求", "working_run_type")
            authorization = None
            if canvas_auto_authorization is not None:
                authorization = self._validate_canvas_auto_generation(conn, project, payload["request"], preview, actor, canvas_auto_authorization)
            artifact = self._create_artifact(conn, project, preview["artifact"])
            document = preview["artifact"]["document"]
            draft = document["workbench_draft"]
            shots = {item["request"]["shot_id"] for item in document["series_batch"]["jobs"]}
            for shot in shots:
                output_kind = next(item["request"]["modality"] for item in document["series_batch"]["jobs"]
                                   if item["request"]["shot_id"] == shot)
                selection = conn.execute(select(S.current_working_selections.c.selection_version_id).where(
                    S.current_working_selections.c.project_id == project_id,
                    S.current_working_selections.c.shot_id == shot,
                    S.current_working_selections.c.output_kind == output_kind)).scalar_one_or_none()
                conn.execute(insert(S.workbench_run_inputs).values(project_id=project_id, id=new_id(),
                    run_version_id=artifact["id"], shot_id=shot,
                    draft_version_id=draft["id"], draft_sha256=draft["sha256"],
                    output_kind=output_kind, base_selection_version_id=selection))
            self.decide_artifact(project_id, {"artifact_id": artifact["id"], "outcome": "approve",
                "reason": authorization["reason"] if authorization is not None else "用户在制作页确认固定输入与报价并点击生成"}, actor=actor,
                _transaction=(conn, project), **{key: value for key, value in kw.items() if key != '_transaction'})
            jobs = []
            for item in document["series_batch"]["jobs"]:
                if item.get('depends_on'):
                    from vsc.production.bounded import depth_dependency_tasks
                    depth_dependency_tasks(document)
                    continue
                request = item["request"]
                jobs.append(self._create_generation_job(conn, project, {
                    "shot_id": request["shot_id"], "purpose": request["purpose"],
                    "modality": request["modality"], "model_id": item["model_id"],
                    "candidate_no": item["candidate_no"], "run_version_id": artifact["id"],
                    "context_sha256": request["context_sha256"], "request_payload": request}))
            return {"id": artifact["id"], "run_version_id": artifact["id"],
                    "jobs": jobs, "status": "queued"}
        return self._mutate(project_id, "generate_workbench", payload, actor=actor, callback=work, **kw)

    def propose_classic_run(self, project_id, payload, *, build_preview, **kw):
        def work(conn, project):
            preview = build_preview(project_id, payload["request"])
            if not preview["ready"]:
                raise ResourceError("经典草稿仍有输入或执行能力缺口", "classic_not_ready")
            if preview["preview_sha256"] != payload["preview_sha256"]:
                raise Conflict("草稿、固定输入、模型或报价已改变，请重新预览", "classic_preview_changed")
            return self._create_artifact(conn, project, preview["artifact"])
        return self._mutate(project_id, "propose_classic_run", payload, callback=work, **kw)

    def list_classic_reference_edits(self,project_id,shot_id):
        from vsc.production.image_tools import EDIT_TYPE
        with self.engine.connect() as conn:
            self._one(conn,S.shots,project_id,checked_id(shot_id));latest={}
            for row in conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project_id,S.artifact_versions.c.artifact_type==EDIT_TYPE,S.artifact_versions.c.artifact_key.like('classic-edit:'+shot_id+':%')).order_by(S.artifact_versions.c.version)).mappings():
                latest[row['artifact_key']]={k:row[k] for k in ('id','version','sha256')};latest[row['artifact_key']]['document']=json.loads(row['document'])
            return clean({'items':list(latest.values())})

    def save_classic_reference_edit(self,project_id,payload,**kw):
        from vsc.production.image_tools import EDIT_TYPE
        def work(conn,project):
            p=project['id'];self._one(conn,S.shots,p,checked_id(payload['shot_id']));d=payload['document'];media=self._media(conn,p,checked_id(d['source_media_id']))
            if media['sha256']!=d['source_sha256'] or media['modality']!=d['source_modality']:raise Conflict('标注源媒体已改变')
            key='classic-edit:'+payload['shot_id']+':'+payload['mode']+':'+d['id']
            prior=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar_one_or_none()
            if prior!=payload['base_edit_id']:raise Conflict('标注已有新版本；保留本地稿，读取后比较','reference_edit_conflict')
            document={'shot_id':payload['shot_id'],'mode':payload['mode'],'edit':d}
            return self._create_artifact(conn,project,{'artifact_key':key,'artifact_type':EDIT_TYPE,'stage':'production','document':document,'object_ids':[payload['shot_id']],'supersedes_id':prior})
        return self._mutate(project_id,'save_classic_reference_edit',payload,callback=work,**kw)

    def export_classic_reference_edit(self,project_id,payload,*,build,**kw):
        from vsc.production.image_tools import EDIT_TYPE,OUTPUT_TYPE
        def work(conn,project):
            p=project['id'];artifact=self._one(conn,S.artifact_versions,p,checked_id(payload['edit_version_id']))
            if artifact['artifact_type']!=EDIT_TYPE:raise ResourceError('需要保存的参考标注版本')
            doc=json.loads(artifact['document']);d=doc['edit'];media=self._media(conn,p,d['source_media_id'])
            if media['sha256']!=d['source_sha256']:raise Conflict('固定源媒体摘要变化')
            key='classic-edit-output:'+artifact['id'];prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(json.loads(prior['document']),id=prior['id'],already_exported=True)
            outputs=[]
            for item in build(d):
                registered=self._register_media(conn,project,{**item['media'],'rights':'unknown','source':{'kind':'local-reference-edit','content':{'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'source_media_id':media['id'],'source_sha256':media['sha256'],'time_ms':d['time_ms']}}},kw['actor'])
                outputs.append({'media_id':registered['id'],'sha256':registered['sha256'],'role':item['role']})
            operation=self.create_media_operation(p,{'operation_type':'reference-annotation','recipe_version':'reference-edit/v1','tool':'vsc-local-reference-editor','tool_version':'1','parameters':{'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'time_ms':d['time_ms']},'inputs':[{'media_id':media['id'],'role':'source','start_ms':d['time_ms'] if media['modality']=='video' else None}],'outputs':outputs},_transaction=(conn,project),**kw)
            result={'shot_id':doc['shot_id'],'mode':doc['mode'],'edit_version_id':artifact['id'],'edit_sha256':artifact['sha256'],'source_media_id':media['id'],'source_sha256':media['sha256'],'time_ms':d['time_ms'],'outputs':outputs,'operation_id':operation['id']}
            registered=self._create_artifact(conn,project,{'artifact_key':key,'artifact_type':OUTPUT_TYPE,'stage':'production','document':result,'object_ids':[doc['shot_id']],'dependency_ids':[artifact['id']]})
            return dict(result,id=registered['id'],already_exported=False)
        return self._mutate(project_id,'export_classic_reference_edit',payload,callback=work,**kw)

    def change_classic_shots(self,project_id,payload,**kw):
        from sqlalchemy import func,update
        from .values import new_id
        def work(conn,project):
            p=project['id'];parent=checked_id(payload.get('parent_id'));self._one(conn,S.sequences,p,parent)
            rows=list(conn.execute(select(S.shots.c.id,S.shots.c.ordinal).where(S.shots.c.project_id==p,S.shots.c.parent_id==parent).order_by(S.shots.c.ordinal)).mappings())
            if payload['action']=='create':
                title=payload.get('title','').strip()
                if not title or len(title)>200:raise ResourceError('请填写200字以内的镜号名称')
                return self._create_object(conn,project,{'kind':'shot','parent_id':parent,'title':title,'display_code':'SHOT-'+new_id()[:8],'ordinal':max((r['ordinal'] for r in rows),default=-1)+1})
            ids=payload.get('shot_ids')
            if not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!={r['id'] for r in rows}:raise ResourceError('排序必须包含同镜组全部镜号，不能跨组')
            start=max((r['ordinal'] for r in rows),default=-1)+len(rows)+1
            for index,row in enumerate(rows):conn.execute(update(S.shots).where(S.shots.c.project_id==p,S.shots.c.id==row['id']).values(ordinal=start+index))
            for index,identifier in enumerate(ids):conn.execute(update(S.shots).where(S.shots.c.project_id==p,S.shots.c.id==identifier).values(ordinal=index))
            return {'shot_ids':ids,'parent_id':parent}
        return self._mutate(project_id,'change_classic_shots',payload,callback=work,**kw)

    def classic_candidate_configuration(self,project_id,shot_id,media_id):
        with self.engine.connect() as conn:
            self._one(conn,S.shots,project_id,checked_id(shot_id));self._one(conn,S.media_items,project_id,checked_id(media_id))
            row=conn.execute(select(S.generation_jobs).join(S.job_outputs,(S.job_outputs.c.project_id==S.generation_jobs.c.project_id)&(S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(S.generation_jobs.c.project_id==project_id,S.generation_jobs.c.shot_id==shot_id,S.generation_jobs.c.status=='succeeded',S.job_outputs.c.media_id==media_id).order_by(S.generation_jobs.c.created_at.desc()).limit(1)).mappings().first()
            return clean(dict(row)) if row else None
