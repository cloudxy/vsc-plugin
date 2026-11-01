"""Classic mode work drafts reuse artifact versions and command receipts."""
from sqlalchemy import select
import json
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.assets.classic_production import DRAFT_TYPE, draft_key
from . import schema as S
from .values import checked_id, clean


class ClassicProductionRepository:
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
            return self._create_artifact(conn, project, {"artifact_key": key, "artifact_type": DRAFT_TYPE,
                "stage": "production", "document": document, "object_ids": [document["shot_id"]], "supersedes_id": current})
        return self._mutate(project_id, "save_classic_draft", payload, callback=work, **kw)

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
            row=conn.execute(select(S.generation_jobs).join(S.job_outputs,(S.job_outputs.c.project_id==S.generation_jobs.c.project_id)&(S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(S.generation_jobs.c.project_id==project_id,S.generation_jobs.c.shot_id==shot_id,S.job_outputs.c.media_id==media_id).order_by(S.generation_jobs.c.created_at.desc()).limit(1)).mappings().first()
            return clean(dict(row)) if row else None
