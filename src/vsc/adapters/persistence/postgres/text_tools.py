"""Original project transactions own editing, fixed attempts and result adoption."""
import json
from sqlalchemy import select,insert,update,and_
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.assets.text_tools import TOOLS,text,validated_result,normalize_document
from . import schema as S
from .values import checked_id,new_id,clean,digest,CURRENT_REVISION


class TextToolsRepository:
    def text_tool_workspace_identity(self,actor):
        from .access_control import authority_lock
        from vsc.assets.access_control import denied
        with self.engine.begin() as conn:
            authority_lock(conn)
            principal,person,_=self._access_principal(conn)
            if not principal or not person or principal.api_key_id or person['actor']!=actor:
                denied('独立工具需要已登录的成员身份')
            return person['id']

    def _text_copy_plan(self,conn,target,payload):
        required={'source_project_id','source_unit_id','source_version_id','source_sha256'}
        if not isinstance(payload,dict) or set(payload)!=required:
            raise ResourceError('导入需要明确的来源单元、固定版本和摘要')
        source=checked_id(payload['source_project_id'])
        if source==target['id']:raise ResourceError('请选择另一个目标项目')
        self._access_require(conn,source,'read')
        from .project_management import management_project_guard,management_object_guard
        management_project_guard(conn,source)
        unit=self._text_unit(conn,source,payload['source_unit_id'])
        if unit['episode_id']:management_object_guard(conn,source,unit['episode_id'])
        version,doc=self._text_version(conn,source,unit,payload['source_version_id'])
        if version['sha256']!=payload['source_sha256']:raise Conflict('来源版本摘要不符','text_tool_source_changed')
        if unit['tool'] not in {'novel','translation','scoring'}:
            raise ResourceError('含视频引用的工具需先显式导入媒体；此入口只复制纯文字工作稿','text_tool_copy_media_required')
        copied=conn.execute(select(S.text_tool_copies).where(S.text_tool_copies.c.project_id==target['id'],S.text_tool_copies.c.source_project_id==source,S.text_tool_copies.c.source_version_id==version['id'])).mappings().first()
        doc=dict(doc);detached=['source_refs'] if doc.get('source_refs') else [];doc['source_refs']=[]
        if unit['tool']=='novel' and doc.get('novel_baseline_version_id'):
            from vsc.production.text_tools import chapters
            detached.append('novel_baseline_version_id');doc.update(novel_baseline_version_id='',chapter_start=1,chapter_end=len(chapters(doc['source_text'])))
        if unit['tool']=='translation':
            detached.extend(k for k in ('style_version_id','reference_version_ids') if doc.get(k))
            doc.update(style_version_id='',reference_version_ids=[],proofread=False,translation_mode='initial')
        return {'source':source,'unit':dict(unit),'version':dict(version),'document':doc,'detached':detached,'copied':dict(copied) if copied else None}

    def preview_text_tool_copy(self,project_id,payload):
        from .access_control import authority_lock
        with self.engine.begin() as conn:
            authority_lock(conn);self._access_require(conn,project_id,'edit')
            target=self._project(conn,project_id);plan=self._text_copy_plan(conn,target,payload)
            return {'project_id':target['id'],'revision':target['revision'],'source_title':plan['unit']['title'],
                'tool':plan['unit']['tool'],'detached_references':plan['detached'],
                'source_preserved':True,'source_sha256':plan['version']['sha256'],
                'existing_unit_id':plan['copied']['unit_id'] if plan['copied'] else None,
                'preview_sha256':digest({'request':payload,'target_revision':target['revision']})}

    def copy_text_tool_to_project(self,project_id,payload,**kw):
        if set(payload)!={'request','preview_sha256'}:raise ResourceError('导入需要先预览固定来源和目标')
        request=payload['request']
        def work(conn,project):
            if payload['preview_sha256']!=digest({'request':request,'target_revision':project['revision']}):
                raise Conflict('目标已变化，请重新预览导入','text_tool_copy_stale')
            plan=self._text_copy_plan(conn,project,request)
            if plan['copied']:return dict(plan['copied'],already_copied=True)
            unit=plan['unit'];draft={'tool':unit['tool'],'group_key':'imported-tools','unit_key':'copy-'+plan['version']['id'],
                'title':unit['title'],'ordinal':unit['ordinal'],'episode_id':None,'document':plan['document'],'base_version_id':None}
            saved=self.save_text_tool(project['id'],draft,normalize=lambda p,t,d:normalize_document(t,d),actor=kw['actor'],
                expected_revision=project['revision'],idempotency_key='copy-source',_transaction=(conn,project))
            identifier=new_id()
            conn.execute(insert(S.text_tool_copies).values(project_id=project['id'],id=identifier,
                source_project_id=plan['source'],source_version_id=plan['version']['id'],unit_id=saved['unit_id'],version_id=saved['id']))
            return {'id':identifier,'unit_id':saved['unit_id'],'version_id':saved['id'],'source_project_id':plan['source'],'source_version_id':plan['version']['id']}
        return self._mutate(project_id,'copy_text_tool_to_project',payload,callback=work,**kw)

    def _text_unit(self,conn,p,unit_id):
        return self._one(conn,S.text_tool_units,p,checked_id(unit_id))

    def _text_version(self,conn,p,unit,version_id=None):
        row=self._one(conn,S.artifact_versions,p,version_id or unit["current_version_id"])
        if row["artifact_type"]!="text-tool-draft" or row["artifact_key"]!="text-tool:"+unit["id"]:
            raise ResourceError("固定版本不属于本工具单元","text_tool_scope")
        return row,json.loads(row["document"])

    def _overseas_fixed(self,conn,project,payload,current=False):
        unit=self._text_unit(conn,project["id"],payload.get("unit_id"))
        if unit["tool"]!="overseas":raise ResourceError("需要出海工作单元")
        version,document=self._text_version(conn,project["id"],unit,payload.get("version_id"))
        if current and (unit["locked"] or unit["current_version_id"]!=version["id"]):raise Conflict("出海稿已更新或锁定，请保留输入并重新读取")
        return unit,version,normalize_document("overseas",document)

    def _overseas_baseline(self,conn,project,unit,identifier,phase,document=None):
        from vsc.production.overseas_production import BASELINE_TYPES,snapshot
        row=self._one(conn,S.artifact_versions,project["id"],checked_id(identifier));data=json.loads(row["document"])
        if row["artifact_type"]!=BASELINE_TYPES[phase] or data["unit_id"]!=unit["id"]:raise ResourceError("确认版本不属于此出海单元与阶段")
        if not self._artifact_approved(conn,project["id"],row["id"]):raise ResourceError("此固定阶段尚未获原人工批准","overseas_baseline_unapproved")
        if document is not None and data["content"]!=snapshot(document,phase):raise Conflict("工作稿与固定确认内容不同，请明确提交修订版本","overseas_baseline_changed")
        return row,data

    def _overseas_merge_plan(self,conn,project,payload):
        from vsc.production.overseas_production import merge
        if not isinstance(payload,dict) or set(payload)!={"unit_id","version_id","source_key","target_key"}:raise ResourceError("合并需要固定稿与来源、目标 UID")
        unit,version,document=self._overseas_fixed(conn,project,payload,True)
        after,impact=merge(document,payload["source_key"],payload["target_key"])
        return dict(unit_id=unit["id"],version_id=version["id"],source_sha256=version["sha256"],document=after,impact=impact)

    def preview_overseas_merge(self,project_id,payload):
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id));plan=self._overseas_merge_plan(conn,project,payload)
            return clean({"plan":plan,"preview_sha256":digest(plan),"revision":project["revision"]})

    def merge_overseas_entities(self,project_id,payload,**kw):
        if set(payload)!={"request","preview_sha256"}:raise ResourceError("请先预览实体合并影响")
        def work(conn,project):
            plan=self._overseas_merge_plan(conn,project,payload["request"])
            if digest(plan)!=payload["preview_sha256"]:raise Conflict("合并影响已变化，请重新预览")
            unit=self._text_unit(conn,project["id"],plan["unit_id"])
            saved=self._text_store_document(conn,project,unit,plan["document"],plan["version_id"])
            self._create_artifact(conn,project,{"artifact_type":"overseas-entity-merge","artifact_key":"overseas-merge:"+saved["id"],"stage":"script","document":dict(plan,output_version_id=saved["id"]),"object_ids":[unit["episode_id"]] if unit["episode_id"] else []})
            return dict(saved,unit_id=unit["id"],impact=plan["impact"])
        return self._mutate(project_id,"merge_overseas_entities",payload,callback=work,**kw)

    def stage_overseas_baseline(self,project_id,payload,**kw):
        from vsc.production.overseas_production import BASELINE_TYPES,snapshot,coverage
        if set(payload)!={"unit_id","version_id","phase"} or payload["phase"] not in BASELINE_TYPES:raise ResourceError("请固定理解或改写阶段版本")
        def work(conn,project):
            unit,version,document=self._overseas_fixed(conn,project,payload,True);phase=payload["phase"]
            source=self._media(conn,project["id"],checked_id(document["source_media_id"]))
            coverage(document,source.get("duration_ms"));dependencies=[]
            if not document["understanding"].strip():raise ResourceError("请保存明确标出观察依据的理解稿")
            if phase=="localization":
                baseline,_=self._overseas_baseline(conn,project,unit,document["understanding_version_id"],"understanding",document)
                dependencies=[baseline["id"]]
                if not document["target_language"].strip() or not document["body"].strip() or any(not r["localized_text"].strip() for r in document["segments"]):raise ResourceError("改写确认需要目标语言、正文与每镜改写")
            content=snapshot(document,phase);key=BASELINE_TYPES[phase]+":"+unit["id"]
            rows=list(conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_key==key).order_by(S.artifact_versions.c.version.desc())).mappings())
            for row in rows:
                if json.loads(row["document"])["content"]==content:return dict(id=row["id"],phase=phase,already_staged=True,needs_approval=not self._artifact_approved(conn,project["id"],row["id"]))
            approved=conn.execute(select(S.current_artifact_versions.c.artifact_id).where(S.current_artifact_versions.c.project_id==project["id"],S.current_artifact_versions.c.artifact_key==key)).scalar()
            saved=self._create_artifact(conn,project,{"artifact_type":BASELINE_TYPES[phase],"artifact_key":key,"stage":"script","supersedes_id":approved,
                "document":{"format":"vsc.overseas-baseline/v1","unit_id":unit["id"],"phase":phase,"source_version_id":version["id"],"source_version_sha256":version["sha256"],"source_media_sha256":source["sha256"],"content":content},
                "dependency_ids":dependencies,"object_ids":[unit["episode_id"]] if unit["episode_id"] else []})
            return dict(saved,phase=phase,needs_approval=True)
        return self._mutate(project_id,"stage_overseas_baseline",payload,callback=work,**kw)

    def overseas_status(self,project_id,unit_id):
        from vsc.production.overseas_production import BASELINE_TYPES
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id));unit=self._text_unit(conn,project["id"],unit_id);baselines=[];groups=[];assets=[]
            rows=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_type.in_([*BASELINE_TYPES.values(),"overseas-group-draft","overseas-asset-image-draft"])).order_by(S.artifact_versions.c.created_at,S.artifact_versions.c.version)).mappings()
            for row in rows:
                data=json.loads(row["document"])
                if data.get("unit_id")!=unit["id"]:continue
                if row["artifact_type"] in BASELINE_TYPES.values():baselines.append(dict(id=row["id"],version=row["version"],phase=data["phase"],approved=self._artifact_approved(conn,project["id"],row["id"]),document=data))
                else:
                    runs=list(conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_key.in_(["overseas-run:"+row["id"],"workbench-run:"+data["classic_draft_id"]]))).mappings())
                    run_values=[]
                    for run in runs:
                        jobs=list(conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==project["id"],S.generation_jobs.c.run_version_id==run["id"])).mappings())
                        run_values.append(dict(id=run["id"],working=run["artifact_type"]=="workbench-generation-run",approved=self._artifact_approved(conn,project["id"],run["id"]),jobs=[dict(id=j["id"],status=j["status"],outputs=[dict(o) for o in conn.execute(select(S.job_outputs).where(S.job_outputs.c.project_id==project["id"],S.job_outputs.c.job_id==j["id"])).mappings()]) for j in jobs]))
                    if row['artifact_type']=='overseas-asset-image-draft':assets.append(dict(data,id=row['id'],runs=run_values))
                    else:
                        selection=self._working_selection(conn,project['id'],data['group']['shot_id'],'video')
                        groups.append(dict(data,id=row['id'],runs=run_values,working_selection_version_id=selection['id'] if selection else None))
            return clean(dict(baselines=baselines,groups=groups,asset_images=assets,revision=project["revision"],limitations=["默认视觉理解只使用抽样图像，不能推断对白。","供应商注册必须有独立身份与回执；未配置时使用原参考图。", "工作选取用于本机剪辑；正式交付保留原审阅。"]))

    def prepare_overseas_asset_image(self,project_id,payload,*,build_document,**kw):
        if set(payload)!={'unit_id','version_id','entity_key','settings','attempt_key','base_classic_draft_id'}:raise ResourceError('资产图需要固定实体、镜头图像设置与明确尝试')
        checked_id(payload['attempt_key'])
        def work(conn,project):
            key='overseas-asset-image:'+payload['unit_id']+':'+payload['attempt_key']
            old=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project['id'],S.artifact_versions.c.artifact_key==key)).mappings().first()
            if old:
                data=json.loads(old['document'])
                if data['request_sha256']!=digest(payload):raise Conflict('原资产图尝试不可更改输入')
                return dict(data,id=old['id'])
            unit,version,doc=self._overseas_fixed(conn,project,payload,True);entity=next((r for r in doc['entities'] if r['key']==payload['entity_key']),None)
            if not entity:raise ResourceError('实体不属于当前工作稿')
            settings=payload['settings']
            if not isinstance(settings,dict) or set(settings)-{'shot_id','model_id','count','width','height'}:raise ResourceError('资产图只接受明确镜头及模型尺寸设置')
            classic=build_document(project['id'],{**settings,'mode':'image','purpose':'identity_ref','prompt':json.dumps({'entity':entity,'target_language':doc['target_language']},ensure_ascii=False),'references':[{'role':'reference_image','media_id':entity['media_id']}] if entity['media_id'] else []})
            if unit['episode_id'] and unit['episode_id'] not in self._ancestor_chain(classic['shot_id'],self._object_parents(conn,project['id'])):raise ResourceError('资产图镜头不属于此单元关联集')
            saved=self.save_classic_draft(project['id'],{'document':classic,'base_draft_id':payload['base_classic_draft_id']},build_document=lambda _p,d:d,_transaction=(conn,project),**kw)
            data={'unit_id':unit['id'],'source_version_id':version['id'],'entity_key':entity['key'],'entity':entity,'classic_draft_id':saved['id'],'request_sha256':digest(payload)}
            artifact=self._create_artifact(conn,project,{'artifact_type':'overseas-asset-image-draft','artifact_key':key,'stage':'workspace','document':data,'dependency_ids':[version['id']]})
            return dict(data,id=artifact['id'])
        return self._mutate(project_id,'prepare_overseas_asset_image',payload,callback=work,**kw)

    def select_overseas_asset_image(self,project_id,payload,**kw):
        if set(payload)!={'unit_id','version_id','asset_draft_id','job_id','media_id'}:raise ResourceError('资产图采用需固定原任务与候选')
        def work(conn,project):
            unit,version,doc=self._overseas_fixed(conn,project,payload,True)
            fixed=self._one(conn,S.artifact_versions,project['id'],payload['asset_draft_id']);data=json.loads(fixed['document'])
            if fixed['artifact_type']!='overseas-asset-image-draft' or data['unit_id']!=unit['id']:raise ResourceError('资产图稿不属于此单元')
            entity=next((r for r in doc['entities'] if r['key']==data['entity_key']),None)
            if not entity or any(entity[k]!=data['entity'][k] for k in ('kind','name','localized','asset_id')):raise Conflict('实体设定已修改，请比较新的资产图输入')
            job=self._one(conn,S.generation_jobs,project['id'],payload['job_id']);run=self._one(conn,S.artifact_versions,project['id'],job['run_version_id'])
            if job['status']!='succeeded' or run['artifact_key']!='workbench-run:'+data['classic_draft_id']:raise ResourceError('候选不属于原资产图成功任务')
            if not conn.execute(select(S.job_outputs.c.id).where(S.job_outputs.c.project_id==project['id'],S.job_outputs.c.job_id==job['id'],S.job_outputs.c.media_id==checked_id(payload['media_id']))).first():raise ResourceError('不是该任务的实际输出')
            if self._media(conn,project['id'],payload['media_id'])['modality']!='image':raise ResourceError('需要图像输出')
            entity['media_id']=payload['media_id'];saved=self._text_store_document(conn,project,unit,doc,version['id'])
            return dict(saved,unit_id=unit['id'])
        return self._mutate(project_id,'select_overseas_asset_image',payload,callback=work,**kw)

    def _overseas_group_input(self,conn,project,identifier):
        row=self._one(conn,S.artifact_versions,project["id"],checked_id(identifier))
        if row["artifact_type"]!="overseas-group-draft":raise ResourceError("需要固定的出海分组制作稿")
        data=json.loads(row["document"]);unit=self._text_unit(conn,project["id"],data["unit_id"])
        self._overseas_baseline(conn,project,unit,data["localization_version_id"],"localization")
        return data

    def overseas_group_input(self,project_id,identifier):
        with self.engine.connect() as conn:return clean(self._overseas_group_input(conn,self._project(conn,checked_id(project_id)),identifier))

    def prepare_overseas_group(self,project_id,payload,*,build_document,**kw):
        from vsc.production.overseas_production import classic_document
        from vsc.assets.classic_production import draft_key
        if set(payload)-{"base_classic_draft_id"}!={"unit_id","version_id","localization_version_id","group_key","settings","attempt_key","new_attempt"} or type(payload["new_attempt"])is not bool:raise ResourceError("分组准备需要固定版本、制作设置与显式尝试身份")
        checked_id(payload["attempt_key"])
        def work(conn,project):
            p=project["id"];key="overseas-group:"+payload["unit_id"]+":"+payload["group_key"]+":"+payload["attempt_key"]
            prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:
                data=json.loads(prior["document"])
                if data["request_sha256"]!=digest(payload):raise Conflict("同一分组尝试不能改变请求")
                return dict(id=prior["id"],**data,already_prepared=True)
            unit,version,document=self._overseas_fixed(conn,project,payload,True)
            self._overseas_baseline(conn,project,unit,payload["localization_version_id"],"localization",document)
            previous=[]
            for old in conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_type=="overseas-group-draft")).mappings():
                data=json.loads(old["document"])
                if data["unit_id"]==unit["id"] and data["group_key"]==payload["group_key"]:previous.append(old)
            if previous and not payload["new_attempt"]:raise Conflict("已有分组制作稿，请恢复原稿；新尝试须明确选择","overseas_attempt_exists")
            for old in previous:
                runs=list(conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key.in_(["overseas-run:"+old["id"],"workbench-run:"+json.loads(old["document"])["classic_draft_id"]]))).mappings())
                for run in runs:
                    statuses=list(conn.execute(select(S.generation_jobs.c.status).where(S.generation_jobs.c.project_id==p,S.generation_jobs.c.run_version_id==run["id"])).scalars())
                    decision=self._latest(conn,S.artifact_decisions,p,"artifact_id",run["id"])
                    if any(s not in {"succeeded","failed","cancelled"} for s in statuses) or (not statuses and not (decision and decision["outcome"]!="approve")):
                        raise Conflict("此组原运行仍待确认、执行或回执；请恢复原运行，不重复发起","overseas_run_unsettled")
            classic=build_document(p,classic_document(document,payload["group_key"],payload["settings"]))
            if unit["episode_id"]:
                parents=self._object_parents(conn,p)
                if unit["episode_id"] not in self._ancestor_chain(classic["shot_id"],parents):raise ResourceError("分组镜头不属于单元关联集")
            prior_classic=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==draft_key(classic["shot_id"],classic["mode"])).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if prior_classic!=payload.get("base_classic_draft_id"):raise Conflict("原镜头此模式已有新稿，请重新读取配置并比较","classic_draft_conflict")
            saved=self.save_classic_draft(p,{"document":classic,"base_draft_id":prior_classic},build_document=lambda _p,d:d,_transaction=(conn,project),**kw)
            data={"unit_id":unit["id"],"source_version_id":version["id"],"source_sha256":version["sha256"],"group_key":payload["group_key"],"localization_version_id":payload["localization_version_id"],"classic_draft_id":saved["id"],"request_sha256":digest(payload),"group":next(g for g in document["groups"] if g["key"]==payload["group_key"])}
            link=self._create_artifact(conn,project,{"artifact_type":"overseas-group-draft","artifact_key":key,"stage":"production","document":data,"object_ids":[classic["shot_id"]]})
            return dict(id=link["id"],**data,already_prepared=False)
        return self._mutate(project_id,"prepare_overseas_group",payload,callback=work,**kw)

    def propose_overseas_group_run(self,project_id,payload,*,build_preview,**kw):
        if set(payload)!={"request","preview_sha256"}:raise ResourceError("请先预览原运行方案")
        def work(conn,project):
            identifier=payload["request"]["group_draft_id"];self._overseas_group_input(conn,project,identifier)
            previous=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_key=="overseas-run:"+identifier)).mappings().first()
            if previous:return dict(id=previous["id"],already_proposed=True,needs_approval=not self._artifact_approved(conn,project["id"],previous["id"]))
            preview=build_preview(project["id"],payload["request"])
            if not preview["ready"]:raise ResourceError("分组原制作输入尚有缺口","overseas_not_ready")
            if preview["preview_sha256"]!=payload["preview_sha256"]:raise Conflict("分组原制作输入或报价已变化，请重新预览")
            return dict(self._create_artifact(conn,project,preview["artifact"]),needs_approval=True)
        return self._mutate(project_id,"propose_overseas_group_run",payload,callback=work,**kw)

    def select_overseas_candidate(self,project_id,payload,*,normalize,**kw):
        if set(payload)-{"working_selection_version_id"}!={"unit_id","version_id","group_draft_id","job_id","media_id","candidate_in_ms"}:raise ResourceError("候选选择须固定原组、任务、媒体与剪入点")
        def work(conn,project):
            unit,version,document=self._overseas_fixed(conn,project,payload,True);fixed=self._overseas_group_input(conn,project,payload["group_draft_id"])
            if fixed["unit_id"]!=unit["id"]:raise ResourceError("制作组不属于当前单元")
            self._overseas_baseline(conn,project,unit,fixed["localization_version_id"],"localization",document)
            job=self._one(conn,S.generation_jobs,project["id"],checked_id(payload["job_id"]))
            run=self._one(conn,S.artifact_versions,project["id"],job["run_version_id"])
            if run["artifact_key"] not in {"overseas-run:"+payload["group_draft_id"],"workbench-run:"+fixed["classic_draft_id"]} or job["status"]!="succeeded":raise ResourceError("请选择本组原成功任务的候选")
            output=conn.execute(select(S.job_outputs.c.id).where(S.job_outputs.c.project_id==project["id"],S.job_outputs.c.job_id==job["id"],S.job_outputs.c.media_id==checked_id(payload["media_id"]))).first()
            if not output:raise ResourceError("候选媒体不是此原任务输出")
            group=next((g for g in document["groups"] if g["key"]==fixed["group_key"]),None)
            if not group:raise Conflict("工作稿已移除此组")
            if run['artifact_type']=='workbench-generation-run':
                from vsc.production.overseas_production import duration
                if 'working_selection_version_id' not in payload:raise ResourceError('工作候选选择须固定所见选择版本')
                candidate=conn.execute(select(S.binding_candidates.c.id).join(S.binding_slots,(S.binding_slots.c.project_id==S.binding_candidates.c.project_id)&(S.binding_slots.c.id==S.binding_candidates.c.slot_id)).where(S.binding_candidates.c.project_id==project['id'],S.binding_candidates.c.media_id==payload['media_id'],S.binding_slots.c.target_object_id==group['shot_id']).order_by(S.binding_candidates.c.created_at.desc()).limit(1)).scalar()
                if not candidate:raise ResourceError('成功输出尚未形成原镜头候选')
                self._save_working_selection(conn,project,{'shot_id':group['shot_id'],'output_kind':'video','candidate_id':candidate,'base_version_id':payload['working_selection_version_id'],'trim_in_ms':payload['candidate_in_ms'],'trim_out_ms':payload['candidate_in_ms']+duration(group)},kw['actor'])
            group.update(candidate_media_id=payload["media_id"],candidate_in_ms=payload["candidate_in_ms"])
            saved=self._text_store_document(conn,project,unit,normalize(project["id"],"overseas",document),version["id"])
            return dict(saved,unit_id=unit["id"],message="已固定工作稿候选；正式选片仍由原审阅决定")
        return self._mutate(project_id,"select_overseas_candidate",payload,callback=work,**kw)

    def _text_store_document(self,conn,project,unit,document,previous):
        if unit['tool']=='novel' and previous:
            relation=conn.execute(select(S.text_tool_novel_episodes.c.plan_id).where(S.text_tool_novel_episodes.c.project_id==project['id'],S.text_tool_novel_episodes.c.unit_id==unit['id'])).scalar()
            if relation:
                fixed_plan=self._one(conn,S.text_tool_novel_plans,project['id'],relation)
                if document.get('novel_baseline_version_id')!=fixed_plan['plan_version_id']:raise Conflict('逐集工作稿不得脱离固定全剧计划','novel_baseline_changed')
        if unit['tool']=='novel' and document.get('novel_baseline_version_id'):
            fixed=self._one(conn,S.artifact_versions,project['id'],document['novel_baseline_version_id']);plan=json.loads(fixed['document'])
            if any(document.get(key)!=plan[key] for key in ('synopsis','core_setting','characters')):
                raise Conflict('共享全剧设定已固定，请从原文单元建立修订计划','novel_baseline_changed')
            planned=next((r for r in plan['episodes'] if r['ordinal']==unit['ordinal']),None)
            if not planned or any(document[key]!=planned[key] for key in ('source_text','chapter_start','chapter_end')):
                raise Conflict('本集原文必须匹配固定计划的实际章范围','novel_chapter_range')
        if unit['tool']=='translation' and document.get('reference_version_ids'):
            refs=[]
            for identifier in document['reference_version_ids']:
                fixed=self._one(conn,S.artifact_versions,project['id'],identifier)
                owner=self._text_unit(conn,project['id'],fixed['artifact_key'].split(':',1)[1])
                prior=json.loads(fixed['document'])
                if owner['group_key']!=unit['group_key'] or owner['id']==unit['id'] or prior.get('target_language')!=document['target_language']:
                    raise ResourceError('精校参考须为同工作组、同目标语言的前集','translation_reference_scope')
                if prior.get('source_language') and document.get('source_language') and prior['source_language']!=document['source_language']:
                    raise ResourceError('精校参考与当前原稿的源语言不一致','translation_reference_scope')
                refs.append(prior.get('episode_number',1))
            if refs!=list(range(1,len(refs)+1)) or document['episode_number']<=refs[-1]:
                raise ResourceError('精校参考须从第1集连续排列，且不得与目标集重叠','translation_reference_range')
        value=self._create_artifact(conn,project,{"artifact_type":"text-tool-draft","artifact_key":"text-tool:"+unit["id"],
            "stage":"script","document":document,"object_ids":[unit["episode_id"]] if unit["episode_id"] else [],
            "supersedes_id":previous})
        conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==project["id"],S.text_tool_units.c.id==unit["id"]).values(current_version_id=value["id"]))
        return value

    def list_text_tools(self,project_id,tool,group_key=None):
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id))
            query=select(S.text_tool_units).where(S.text_tool_units.c.project_id==project["id"],S.text_tool_units.c.tool==tool)
            if group_key is not None:query=query.where(S.text_tool_units.c.group_key==group_key)
            rows=[dict(r) for r in conn.execute(query.order_by(S.text_tool_units.c.group_key,S.text_tool_units.c.ordinal,S.text_tool_units.c.id)).mappings()]
            for row in rows:
                if tool=="translation":row["proofread"]=self._text_version(conn,project["id"],row)[1].get("proofread",False)
                if tool=="scoring":
                    doc=self._text_version(conn,project["id"],row)[1];scores={r["key"]:r["score"] for r in doc["scores"]}
                    row.update(review_decision=doc["review_decision"],channel=doc["channel"],weighted_score=None)
                    if doc["criteria"] and set(scores)=={r["key"] for r in doc["criteria"]}:
                        row["weighted_score"]=round(sum(scores[r["key"]]*r["weight"] for r in doc["criteria"])*100/sum(r["max_score"]*r["weight"] for r in doc["criteria"]),2)
            return clean({"items":rows,"revision":project["revision"],"total":len(rows)})

    def get_text_tool(self,project_id,unit_id):
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id))
            unit=self._text_unit(conn,project["id"],unit_id)
            version,document=self._text_version(conn,project["id"],unit)
            attempts=[dict(r) for r in conn.execute(select(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==project["id"],S.text_tool_attempts.c.unit_id==unit["id"]).order_by(S.text_tool_attempts.c.created_at.desc(),S.text_tool_attempts.c.id)).mappings()]
            for run in attempts:
                if run["result_version_id"]:
                    result=self._one(conn,S.artifact_versions,project["id"],run["result_version_id"])
                    run["result"]=json.loads(result["document"])
            history=[dict(r) for r in conn.execute(select(S.artifact_versions.c.id,S.artifact_versions.c.version,S.artifact_versions.c.sha256,S.artifact_versions.c.created_at).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_key==version["artifact_key"]).order_by(S.artifact_versions.c.version.desc())).mappings()]
            return clean({**unit,"document":document,"version":version["version"],"sha256":version["sha256"],"attempts":attempts,"history":history,"revision":project["revision"]})

    def create_novel_plan(self,project_id,payload,**kw):
        from vsc.production.text_tools import novel_plan
        if set(payload)!={'unit_id','version_id','episodes'}:raise ResourceError('全剧计划需要保存稿与逐集章范围')
        def work(conn,project):
            p=project['id'];unit=self._text_unit(conn,p,payload['unit_id'])
            version,doc=self._text_version(conn,p,unit,payload['version_id'])
            if unit['tool']!='novel' or unit['locked'] or unit['current_version_id']!=version['id'] or doc.get('novel_baseline_version_id'):
                raise Conflict('请从当前未锁定的全剧小说原文建立分集计划')
            rows=novel_plan(doc,payload['episodes'])
            key='novel-plan:'+digest(payload)
            old=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).scalar()
            if old:
                plan=conn.execute(select(S.text_tool_novel_plans).where(S.text_tool_novel_plans.c.project_id==p,S.text_tool_novel_plans.c.plan_version_id==old)).mappings().one()
                return {'id':plan['id'],'plan_version_id':old,'already_created':True}
            fixed=self._create_artifact(conn,project,{'artifact_type':'novel-adaptation-plan','artifact_key':key,'stage':'script',
                'document':{'format':'vsc.novel-plan/v1','baseline_version_id':version['id'],'baseline_sha256':version['sha256'],
                    'synopsis':doc['synopsis'],'core_setting':doc['core_setting'],'characters':doc['characters'],'episodes':rows},'dependency_ids':[version['id']]})
            plan_id=new_id();conn.execute(insert(S.text_tool_novel_plans).values(project_id=p,id=plan_id,unit_id=unit['id'],baseline_version_id=version['id'],plan_version_id=fixed['id']))
            created=[]
            for row in rows:
                identifier=new_id();child={'id':identifier,'project_id':p,'tool':'novel','group_key':'novel-'+plan_id,'unit_key':'episode-'+str(row['ordinal']),
                    'title':row['title'],'ordinal':row['ordinal'],'episode_id':None,'current_version_id':None,'locked':False}
                conn.execute(insert(S.text_tool_units).values(**child))
                content=normalize_document('novel',dict(doc,source_text=row['source_text'],chapter_start=row['chapter_start'],chapter_end=row['chapter_end'],
                    outline=row['outline'],body='',scenes='',qa_notes='',novel_baseline_version_id=fixed['id']))
                saved=self._text_store_document(conn,project,child,content,None)
                conn.execute(insert(S.text_tool_novel_episodes).values(project_id=p,id=new_id(),plan_id=plan_id,unit_id=identifier,
                    ordinal=row['ordinal'],chapter_start=row['chapter_start'],chapter_end=row['chapter_end']))
                created.append({'unit_id':identifier,'version_id':saved['id'],'title':row['title']})
            return {'id':plan_id,'plan_version_id':fixed['id'],'episodes':created,'already_created':False}
        return self._mutate(project_id,'create_novel_plan',payload,callback=work,**kw)

    def get_novel_plan(self,project_id,unit_id):
        with self.engine.connect() as conn:
            self._project(conn,project_id)
            child=conn.execute(select(S.text_tool_novel_episodes.c.plan_id).where(S.text_tool_novel_episodes.c.project_id==project_id,S.text_tool_novel_episodes.c.unit_id==unit_id)).scalar()
            query=select(S.text_tool_novel_plans).where(S.text_tool_novel_plans.c.project_id==project_id)
            query=query.where(S.text_tool_novel_plans.c.id==child) if child else query.where(S.text_tool_novel_plans.c.unit_id==unit_id)
            plan=conn.execute(query.order_by(S.text_tool_novel_plans.c.created_at.desc()).limit(1)).mappings().first()
            if not plan:return None
            rows=conn.execute(select(S.text_tool_novel_episodes).where(S.text_tool_novel_episodes.c.project_id==project_id,S.text_tool_novel_episodes.c.plan_id==plan['id']).order_by(S.text_tool_novel_episodes.c.ordinal)).mappings()
            episodes=[]
            for row in rows:
                unit=self._text_unit(conn,project_id,row['unit_id']);version,doc=self._text_version(conn,project_id,unit)
                episodes.append({**dict(row),'title':unit['title'],'version_id':version['id'],'has_body':bool(doc['body'].strip()),'locked':unit['locked']})
            return clean(dict(plan,episodes=episodes))

    def _novel_batch_plan(self,conn,project,payload):
        from sqlalchemy import func
        if set(payload)!={'plan_id','work_id','code_prefix'}:raise ResourceError('整剧导入需要计划、目标作品与分集编号前缀')
        text(payload['code_prefix'],40,False)
        plan=self._one(conn,S.text_tool_novel_plans,project['id'],checked_id(payload['plan_id']))
        next_ordinal=conn.execute(select(func.coalesce(func.max(S.episodes.c.ordinal),-1)+1).where(S.episodes.c.project_id==project['id'],S.episodes.c.parent_id==checked_id(payload['work_id']))).scalar_one()
        rows=conn.execute(select(S.text_tool_novel_episodes).where(S.text_tool_novel_episodes.c.project_id==project['id'],S.text_tool_novel_episodes.c.plan_id==plan['id']).order_by(S.text_tool_novel_episodes.c.ordinal)).mappings()
        requests=[];plans=[]
        for row in rows:
            unit=self._text_unit(conn,project['id'],row['unit_id'])
            request={'unit_id':unit['id'],'version_id':unit['current_version_id'],'episode_id':None,
                'new_episode':{'work_id':payload['work_id'],'display_code':payload['code_prefix']+str(row['ordinal']).zfill(3),'title':unit['title'],'ordinal':next_ordinal+row['ordinal']-1},
                'scene_id':None,'new_scene_title':unit['title']+' · 工作场次','asset_mapping':{}}
            requests.append(request);plans.append(self._novel_import_plan(conn,project,request))
        return {'plan_id':plan['id'],'requests':requests,'episodes':plans}

    def preview_novel_batch_import(self,project_id,payload):
        with self.engine.connect() as conn:
            project=self._project(conn,project_id);plan=self._novel_batch_plan(conn,project,payload)
            return {'plan':plan,'preview_sha256':digest(plan),'revision':project['revision']}

    def import_novel_batch(self,project_id,payload,**kw):
        if set(payload)!={'request','preview_sha256'}:raise ResourceError('整剧导入需要固定差异预览')
        def work(conn,project):
            key='novel-batch-import:'+digest(payload)
            old=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project['id'],S.artifact_versions.c.artifact_key==key)).mappings().first()
            if old:return dict(json.loads(old['document']),already_imported=True)
            plan=self._novel_batch_plan(conn,project,payload['request'])
            if digest(plan)!=payload['preview_sha256']:raise Conflict('分集工作稿或目标已变化，请重新预览','novel_batch_stale')
            results=[]
            for request,item in zip(plan['requests'],plan['episodes']):
                result=self.import_text_tool_novel(project['id'],{'request':request,'preview_sha256':digest(item)},actor=kw['actor'],expected_revision=project['revision'],idempotency_key='novel-batch-item',_transaction=(conn,project))
                results.append(result)
            document={'plan_id':plan['plan_id'],'episodes':results,'automatic_approval':False}
            fixed=self._create_artifact(conn,project,{'artifact_type':'novel-batch-import','artifact_key':key,'stage':'script','document':document})
            return dict(document,id=fixed['id'],already_imported=False)
        return self._mutate(project_id,'import_novel_batch',payload,callback=work,**kw)

    def scoring_export_document(self,project_id,version_id):
        from vsc.production.text_tools import scoring_boundary
        with self.engine.connect() as conn:
            fixed=self._one(conn,S.artifact_versions,project_id,version_id);doc=json.loads(fixed['document'])
            unit=self._text_unit(conn,project_id,fixed['artifact_key'].split(':',1)[1]);runs=[]
            for row in conn.execute(select(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==project_id,S.text_tool_attempts.c.unit_id==unit['id'],S.text_tool_attempts.c.created_at<=fixed['created_at']).order_by(S.text_tool_attempts.c.created_at)).mappings():
                if not row['result_version_id']:continue
                result_version=self._one(conn,S.artifact_versions,project_id,row['result_version_id'])
                if result_version['created_at']>fixed['created_at']:continue
                source=self._one(conn,S.artifact_versions,project_id,row['input_version_id']);input_=json.loads(source['document'])
                result=json.loads(result_version['document'])
                runs.append({'id':row['id'],'status':row['status'],'backend':row['backend'],'input_version_id':source['id'],'input_sha256':source['sha256'],'card':scoring_boundary(input_),'result':result,'error_code':row['error_code']})
            return dict(doc,fixed_version_id=version_id,card=scoring_boundary(doc),runs=runs)

    def save_text_tool(self,project_id,payload,*,normalize,**kw):
        allowed={"unit_id","tool","group_key","unit_key","title","ordinal","episode_id","document","base_version_id"}
        if set(payload)-allowed or payload.get("tool") not in TOOLS:raise ResourceError("工具保存字段无效")
        for field in ("group_key","unit_key","title"):text(payload.get(field),200 if field=="title" else 100,False)
        if type(payload.get("ordinal")) is not int or payload["ordinal"]<0:raise ResourceError("单元顺序无效")
        def work(conn,project):
            p=project["id"];identifier=payload.get("unit_id")
            if identifier:
                unit=self._text_unit(conn,p,identifier)
                if unit["locked"]:raise Conflict("该单元已停止并锁定；请显式解锁后编辑","text_tool_locked")
                if any(unit[k]!=payload.get(k) for k in ("tool","group_key","unit_key")) or unit["episode_id"]!=payload.get("episode_id"):
                    raise ResourceError("单元身份与集范围不可隐式变更")
                if unit["current_version_id"]!=payload.get("base_version_id"):raise Conflict("人工稿已有新版本，输入已保留","text_tool_version_conflict")
                if unit['tool']=='novel' and unit['ordinal']!=payload['ordinal'] and conn.execute(select(S.text_tool_novel_episodes.c.id).where(S.text_tool_novel_episodes.c.project_id==p,S.text_tool_novel_episodes.c.unit_id==identifier)).first():
                    raise Conflict('已规划的分集顺序属于固定全剧计划，请建立修订计划','novel_baseline_changed')
                conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==p,S.text_tool_units.c.id==identifier).values(title=payload["title"],ordinal=payload["ordinal"]))
            else:
                if payload.get("base_version_id"):raise ResourceError("新建单元不应带旧版本")
                identifier=new_id()
                if payload.get("episode_id"):self._one(conn,S.episodes,p,checked_id(payload["episode_id"]))
                unit={"id":identifier,"project_id":p,**{k:payload[k] for k in ("tool","group_key","unit_key","title","ordinal")},"episode_id":payload.get("episode_id"),"current_version_id":None,"locked":False}
                conn.execute(insert(S.text_tool_units).values(**unit))
            document=normalize(p,payload["tool"],payload["document"])
            saved=self._text_store_document(conn,project,unit,document,unit["current_version_id"])
            return {**saved,"unit_id":identifier,"version_id":saved["id"],"document":document}
        return self._mutate(project_id,"save_text_tool",payload,callback=work,**kw)

    def set_text_tool_lock(self,project_id,payload,**kw):
        def work(conn,project):
            unit=self._text_unit(conn,project["id"],payload["unit_id"])
            if unit['tool']=='translation' and not payload['locked'] and self._text_version(conn,project['id'],unit)[1].get('translation_stage')=='complete':raise Conflict('完成译文请使用重新打开编辑，保留完成状态历史')
            conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==project["id"],S.text_tool_units.c.id==unit["id"]).values(locked=payload["locked"]))
            return {"id":unit["id"],"locked":payload["locked"],"message":"已开始的调用保留结果，但不会覆盖人工稿"}
        return self._mutate(project_id,"set_text_tool_lock",payload,callback=work,**kw)

    def start_text_tool_attempt(self,project_id,payload,*,backend,caller,materials_artifact_id=None,**kw):
        def work(conn,project):
            p=project["id"];unit=self._text_unit(conn,p,payload.get("unit_id"))
            if unit["locked"]:raise Conflict("该单元已停止并锁定","text_tool_locked")
            version,doc=self._text_version(conn,p,unit,payload.get("input_version_id"))
            if version["id"]!=unit["current_version_id"]:raise Conflict("运行输入不是当前保存稿","text_tool_version_conflict")
            action=payload.get("action")
            if action not in TOOLS[unit["tool"]]["actions"]:raise ResourceError("该工具不支持此动作")
            if unit["tool"]=="overseas" and action=="localize":
                doc=normalize_document("overseas",doc)
                self._overseas_baseline(conn,project,unit,doc["understanding_version_id"],"understanding",doc)
            packet=None
            if materials_artifact_id:
                packet=self._one(conn,S.artifact_versions,p,materials_artifact_id);body=json.loads(bytes(packet['document']))
                if unit['tool']!='novel' or packet['artifact_type']!='text-tool-role-materials' or body.get('format')!='vsc.text-tool-role-materials/v1' or body.get('tool')!='novel' or action not in body.get('actions',{}):raise ResourceError('排队材料不属于此小说动作','role_materials_invalid')
                dependencies=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==p,S.artifact_dependencies.c.artifact_id==packet['id'])).scalars())
                if version['id'] not in dependencies:raise ResourceError('排队材料未固定本次小说输入','role_materials_invalid')
            def reuse(previous):
                if packet:
                    manifests=[]
                    for raw in conn.execute(select(S.artifact_versions.c.document).join(S.text_tool_attempt_inputs,and_(S.text_tool_attempt_inputs.c.project_id==p,S.text_tool_attempt_inputs.c.version_id==S.artifact_versions.c.id)).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_type=='text-tool-role-materials',S.text_tool_attempt_inputs.c.attempt_id==previous['id'])).scalars():
                        manifests.append(json.loads(raw).get('actions',{}).get(action))
                    if manifests!=[body['actions'][action]]:raise Conflict('原尝试的专业材料与本批不同，请明确发起新的尝试','role_materials_changed')
                return {'id':previous['id'],'caller':None}
            query=select(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==p,S.text_tool_attempts.c.unit_id==unit["id"])
            active=conn.execute(query.where(S.text_tool_attempts.c.status.in_(["running","submission_unknown"]))).mappings().first()
            if active:return reuse(active)
            if not payload.get("new_attempt"):
                previous=conn.execute(query.where(S.text_tool_attempts.c.input_version_id==version["id"],S.text_tool_attempts.c.action==action).order_by(S.text_tool_attempts.c.created_at.desc()).limit(1)).mappings().first()
                if previous:return reuse(previous)
            identifier=new_id()
            references=list(doc.get('reference_version_ids',[]))
            if unit['tool']=='novel':
                if doc.get('novel_baseline_version_id'):references.append(doc['novel_baseline_version_id'])
                if action=='qa_notes':
                    child=conn.execute(select(S.text_tool_novel_episodes.c.plan_id).where(S.text_tool_novel_episodes.c.project_id==p,S.text_tool_novel_episodes.c.unit_id==unit['id'])).scalar()
                    query=select(S.text_tool_novel_plans.c.id).where(S.text_tool_novel_plans.c.project_id==p)
                    query=query.where(S.text_tool_novel_plans.c.id==child) if child else query.where(S.text_tool_novel_plans.c.unit_id==unit['id'])
                    plan=conn.execute(query.order_by(S.text_tool_novel_plans.c.created_at.desc()).limit(1)).scalar()
                    if plan:
                        for row in conn.execute(select(S.text_tool_novel_episodes).where(S.text_tool_novel_episodes.c.project_id==p,S.text_tool_novel_episodes.c.plan_id==plan).order_by(S.text_tool_novel_episodes.c.ordinal)).mappings():
                            references.append(self._text_unit(conn,p,row['unit_id'])['current_version_id'])
            references=list(dict.fromkeys(references))
            if unit['tool']=='novel':
                if packet is None:
                    from vsc.production.text_tools import novel_materials_packet
                    packet=self._create_artifact(conn,project,dict(artifact_type='text-tool-role-materials',artifact_key='text-attempt-role-materials:'+identifier,document=novel_materials_packet([action]),dependency_ids=list(dict.fromkeys([version['id']]+references)),object_ids=[unit['episode_id']] if unit['episode_id'] else []))
                references.append(packet['id'])
            elif materials_artifact_id:raise ResourceError('此文本工具不能使用小说角色材料','role_materials_invalid')
            conn.execute(insert(S.text_tool_attempts).values(project_id=p,id=identifier,unit_id=unit["id"],input_version_id=version["id"],action=action,backend="local-ffprobe-subtitles/v3" if action=="check" and not(set(doc['checks'])-{'metadata','subtitles','decode'}) else backend,status="running",input_count=len(references),created_by=kw["actor"]))
            for ordinal,ref in enumerate(references):
                conn.execute(insert(S.text_tool_attempt_inputs).values(project_id=p,id=new_id(),attempt_id=identifier,version_id=ref,ordinal=ordinal))
            return {"id":identifier,"caller":caller}
        return self._mutate(project_id,"start_text_tool_attempt",payload,callback=work,**kw)

    def get_text_tool_attempt(self,project_id,attempt_id):
        with self.engine.connect() as conn:
            p=checked_id(project_id);project=self._project(conn,p)
            row=self._one(conn,S.text_tool_attempts,p,checked_id(attempt_id))
            if row["result_version_id"]:row["result"]=json.loads(self._one(conn,S.artifact_versions,p,row["result_version_id"])["document"])
            refs=[]
            for ref in conn.execute(select(S.text_tool_attempt_inputs.c.version_id).where(S.text_tool_attempt_inputs.c.project_id==p,S.text_tool_attempt_inputs.c.attempt_id==row['id']).order_by(S.text_tool_attempt_inputs.c.ordinal)).scalars():
                fixed=self._one(conn,S.artifact_versions,p,ref);document=json.loads(fixed['document'])
                if fixed['artifact_type']=='text-tool-role-materials':
                    if row.get('role_materials_manifest') or document.get('format')!='vsc.text-tool-role-materials/v1' or document.get('tool')!='novel' or row['action'] not in document.get('actions',{}):raise ResourceError('原任务的角色材料关联无效','role_materials_invalid')
                    row=dict(row,role_materials_manifest=document['actions'][row['action']],materials_artifact_id=fixed['id']);continue
                refs.append({'id':ref,'sha256':fixed['sha256'],'document':document})
            row=dict(row,references=refs)
            return clean({**row,"revision":project["revision"]})

    def recover_text_tool_attempt(self,project_id,payload,**kw):
        from datetime import datetime,timezone,timedelta
        def work(conn,project):
            row=self._one(conn,S.text_tool_attempts,project["id"],checked_id(payload["attempt_id"]))
            receipt=conn.execute(select(S.text_tool_receipts).where(S.text_tool_receipts.c.project_id==project['id'],S.text_tool_receipts.c.attempt_id==row['id'])).mappings().first()
            if receipt:
                return self._finish_text_tool_result(conn,project,row,receipt['result'],receipt['error_code'])
            # Bounded host is killed at 120s. Allow a generous grace for receipt writes.
            if row["status"]=="running":
                if row["created_at"]+timedelta(minutes=10)>datetime.now(timezone.utc):
                    raise Conflict("调用仍在回执宽限期内，请稍后刷新；不会重复提交","text_tool_still_running")
                conn.execute(update(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==project["id"],S.text_tool_attempts.c.id==row["id"]).values(status="submission_unknown",error_code="text_submission_unknown"))
            return {"id":row["id"],"status":"submission_unknown" if row["status"]=="running" else row["status"]}
        return self._mutate(project_id,"recover_text_tool_attempt",payload,callback=work,**kw)

    def persist_text_tool_receipt(self,project_id,attempt_id,result,error):
        """Internal response sink for the claimed call; no public write route."""
        with self.engine.begin() as conn:
            p=self._project(conn,project_id,lock=True)['id']
            row=self._one(conn,S.text_tool_attempts,p,checked_id(attempt_id))
            previous=conn.execute(select(S.text_tool_receipts).where(S.text_tool_receipts.c.project_id==p,S.text_tool_receipts.c.attempt_id==row['id'])).mappings().first()
            if previous:
                if previous['result']!=result or previous['error_code']!=error:
                    raise Conflict('已返回的固定文本结果不能被替换','text_tool_result_changed')
                return
            if row['status'] not in {'running','submission_unknown'}:
                raise Conflict('该调用已经结束','text_tool_attempt_finished')
            conn.execute(insert(S.text_tool_receipts).values(project_id=p,id=new_id(),attempt_id=row['id'],result=result,error_code=error))

    def _finish_text_tool_result(self,conn,project,run,result,error):
        attempt_id=run['id']
        if run["status"] not in {"running","submission_unknown"}:return {"id":attempt_id,"status":run["status"],"result_version_id":run["result_version_id"]}
        unit=self._text_unit(conn,project["id"],run["unit_id"])
        artifact_id=None
        if error is None:
            _,doc=self._text_version(conn,project["id"],unit,run["input_version_id"])
            patch=validated_result(unit["tool"],run["action"],result,doc)
            artifact=self._create_artifact(conn,project,{"artifact_type":"text-tool-result","artifact_key":"text-tool-result:"+attempt_id,"stage":"script",
                "document":{"format":"vsc.text-tool-result/v1","tool":unit["tool"],"unit_id":unit["id"],"input_version_id":run["input_version_id"],"action":run["action"],"backend":run["backend"],"patch":patch},
                "object_ids":[unit["episode_id"]] if unit["episode_id"] else []})
            artifact_id=artifact["id"]
        status="completed" if artifact_id else "submission_unknown" if error=="text_submission_unknown" else "failed"
        conn.execute(update(S.text_tool_attempts).where(S.text_tool_attempts.c.project_id==project["id"],S.text_tool_attempts.c.id==attempt_id).values(status=status,error_code=error,result_version_id=artifact_id))
        return {"id":attempt_id,"status":status,"result_version_id":artifact_id,"error_code":error}

    def finish_text_tool_attempt(self,project_id,attempt_id,result,error,*,actor):
        payload={"attempt_id":attempt_id,"result":result,"error":error}
        def work(conn,project):
            run=self._one(conn,S.text_tool_attempts,project["id"],attempt_id)
            return self._finish_text_tool_result(conn,project,run,result,error)
        return self._mutate(project_id,"finish_text_tool_attempt",payload,callback=work,expected_revision=CURRENT_REVISION,idempotency_key="text-tool-finish:"+attempt_id,actor=actor)

    def accept_text_tool_result(self,project_id,payload,*,normalize,**kw):
        def work(conn,project):
            p=project["id"];run=self._one(conn,S.text_tool_attempts,p,checked_id(payload["attempt_id"]));unit=self._text_unit(conn,p,run["unit_id"])
            if unit["locked"]:raise Conflict("单元已锁定，请先解锁")
            if run["status"]!="completed":raise ResourceError("此尝试尚无可接受结果")
            if payload["base_version_id"]!=unit["current_version_id"] or run["input_version_id"]!=unit["current_version_id"]:raise Conflict("人工稿已改变，结果只供比较，不自动覆盖","text_tool_result_stale")
            if run['action']=='qa_notes':
                for ref in conn.execute(select(S.text_tool_attempt_inputs.c.version_id).where(S.text_tool_attempt_inputs.c.project_id==p,S.text_tool_attempt_inputs.c.attempt_id==run['id'])).scalars():
                    fixed=self._one(conn,S.artifact_versions,p,ref)
                    if fixed['artifact_type']=='text-tool-draft':
                        referenced=self._text_unit(conn,p,fixed['artifact_key'].split(':',1)[1])
                        if referenced['current_version_id']!=ref:raise Conflict('联合QA涉及的其他分集已更新，请基于新稿重新检查','text_tool_result_stale')
            _,document=self._text_version(conn,p,unit)
            result=json.loads(self._one(conn,S.artifact_versions,p,run["result_version_id"])["document"])
            next_doc=normalize(p,unit["tool"],{**document,**result["patch"]})
            if unit['tool']=='translation' and run['action']=='translate' and not document.get('style_request'):next_doc.update(translation_stage='translated',proofread=False)
            if unit['tool']=='translation' and run['action']=='terms':next_doc['translation_stage']='draft'
            saved=self._text_store_document(conn,project,unit,next_doc,unit["current_version_id"])
            return {**saved,"unit_id":unit["id"],"version_id":saved["id"],"document":next_doc}
        return self._mutate(project_id,"accept_text_tool_result",payload,callback=work,**kw)

    def merge_text_tools(self,project_id,payload,**kw):
        def work(conn,project):
            if len(set(payload["version_ids"]))!=len(payload["version_ids"]):raise ResourceError("合并版本不能重复")
            units=[]
            for version_id in payload["version_ids"]:
                version=self._one(conn,S.artifact_versions,project["id"],checked_id(version_id))
                doc=json.loads(version["document"])
                if version["artifact_type"]!="text-tool-draft" or doc.get("format")!="vsc.text-tool/"+payload["tool"]+"/v1":raise ResourceError("合并须为同工具的明确固定稿")
                unit=self._text_unit(conn,project["id"],version["artifact_key"].split(":",1)[1])
                units.append({"id":version["id"],"sha256":version["sha256"],"title":unit["title"],"ordinal":unit["ordinal"],"document":doc})
            if len({row["document"].get("format") for row in units})!=1:raise ResourceError("合并类型不一致")
            return self._create_artifact(conn,project,{"artifact_type":"text-tool-bundle","artifact_key":"text-tool-merge:"+new_id(),"stage":"script","document":{"format":"vsc.text-tool-bundle/v1","tool":payload["tool"],"title":payload["title"],"units":units}})
        return self._mutate(project_id,"merge_text_tools",payload,callback=work,**kw)

    def _text_import_plan(self,conn,project,payload):
        from vsc.post.text_tool_exports import paragraphs
        p=project["id"];unit=self._text_unit(conn,p,payload.get("unit_id"));version,doc=self._text_version(conn,p,unit,payload.get("version_id"))
        if unit["tool"]=="overseas":
            from vsc.production.overseas_production import duration
            doc=normalize_document("overseas",doc)
            episode=payload.get("episode_id") or unit["episode_id"]
            self._one(conn,S.episodes,p,checked_id(episode))
            current=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==p,S.edit_workspaces.c.episode_id==episode)).mappings().first()
            if not doc["groups"] or any(not g["candidate_media_id"] for g in doc["groups"]):raise ResourceError("每个出海组必须显式选择可用候选视频","localization_candidates_missing")
            fps=24
            clips=[{"id":"group-"+g["key"],"media_id":g["candidate_media_id"],"in_frame":round(g["candidate_in_ms"]*fps/1000),"out_frame":round((g["candidate_in_ms"]+duration(g))*fps/1000),"volume":1,"muted":False} for g in doc["groups"]]
            for group,clip in zip(doc['groups'],clips):
                if not group['shot_id']:continue
                selection=conn.execute(select(S.working_selection_versions.c.id).join(S.binding_candidates,and_(S.binding_candidates.c.project_id==p,S.binding_candidates.c.id==S.working_selection_versions.c.candidate_id)).where(
                    S.working_selection_versions.c.project_id==p,S.working_selection_versions.c.shot_id==group['shot_id'],S.working_selection_versions.c.output_kind=='video',
                    S.binding_candidates.c.media_id==group['candidate_media_id'],S.working_selection_versions.c.trim_in_ms==group['candidate_in_ms'],
                    S.working_selection_versions.c.trim_out_ms==group['candidate_in_ms']+duration(group)).order_by(S.working_selection_versions.c.created_at.desc()).limit(1)).scalar()
                if selection:clip.update(shot_id=group['shot_id'],working_selection_version_id=str(selection))
            plan={"kind":"editing","unit_id":unit["id"],"version_id":version["id"],"episode_id":episode,"edit_revision":current["revision"] if current else 0,
                  "change":"update" if current else "create","previous_document":self._one(conn,S.edit_revisions,p,current["current_version_id"])["document"] if current else None,"document":{"format":"vsc.edit-workspace/v1","width":720,"height":1280,"fps":fps,"clips":clips,"audio":[],"captions":[]}}
        else:
            source_key="text-tool-import:"+unit["id"]
            previous=conn.execute(select(S.source_versions.c.id).where(S.source_versions.c.project_id==p,S.source_versions.c.source_key==source_key).order_by(S.source_versions.c.version.desc()).limit(1)).scalar()
            body="\n".join(paragraphs(doc))
            if not body.strip():raise ResourceError("没有可导入正文")
            plan={"kind":"source","unit_id":unit["id"],"version_id":version["id"],"source_key":source_key,"previous_source_id":previous,
                  "change":"update" if previous else "create","title":unit["title"],"content":body,"intent":"screenplay" if unit["tool"] in {"novel","translation","breakdown"} else "reference"}
        return clean(plan)

    def preview_text_tool_import(self,project_id,payload):
        if not isinstance(payload,dict) or set(payload)-{"unit_id","version_id","episode_id"}:raise ResourceError("导入预览需要固定单元版本")
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id));plan=self._text_import_plan(conn,project,payload)
            return {"plan":plan,"preview_sha256":digest(plan),"revision":project["revision"],"needs_confirmation":True}

    def import_text_tool(self,project_id,payload,**kw):
        if set(payload)!={"request","preview_sha256"}:raise ResourceError("导入需要已预览的固定请求和摘要")
        def work(conn,project):
            plan=self._text_import_plan(conn,project,payload["request"])
            if digest(plan)!=payload["preview_sha256"]:raise Conflict("导入目标或固定结果已改变，请重新预览")
            if plan["kind"]=="editing":
                from .editor_workspace import EditorWorkspaceRepository
                return EditorWorkspaceRepository(self).save(project_id,{k:plan[k] for k in ("episode_id","edit_revision","document")},_transaction=(conn,project),**kw)
            return self.create_source_intake(project_id,{k:plan[k] for k in ("source_key","title","content","intent")},_transaction=(conn,project),**kw)
        return self._mutate(project_id,"import_text_tool",payload,callback=work,**kw)


    def list_translation_styles(self,project_id):
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id))
            rows=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_type=="translation-style").order_by(S.artifact_versions.c.created_at.desc()).limit(500)).mappings()
            return clean({"items":[dict(json.loads(row["document"]),id=row["id"],style_id=row["artifact_key"].split(":",1)[1],version=row["version"],sha256=row["sha256"]) for row in rows],"revision":project["revision"]})

    def save_translation_style(self,project_id,payload,**kw):
        if set(payload)!={"style_id","base_version_id","title","language","content"}:raise ResourceError("风格需要身份、前版、标题、语言和正文")
        for name,maximum in [("title",200),("language",100),("content",20000)]:text(payload[name],maximum,False)
        def work(conn,project):
            identifier=checked_id(payload["style_id"]) if payload["style_id"] else new_id();key="translation-style:"+identifier
            prior=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==project["id"],S.artifact_versions.c.artifact_key==key).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            if prior!=payload["base_version_id"]:raise Conflict("翻译风格已有新版本，请比较后保存")
            document={"format":"vsc.translation-style/v1",**{key:payload[key] for key in ("title","language","content")}}
            value=self._create_artifact(conn,project,{"artifact_type":"translation-style","artifact_key":key,"stage":"script","document":document,"supersedes_id":prior})
            return dict(value,style_id=identifier)
        return self._mutate(project_id,"save_translation_style",payload,callback=work,**kw)

    def _novel_import_plan(self,conn,project,payload):
        allowed={"unit_id","version_id","episode_id","new_episode","scene_id","new_scene_title","asset_mapping"}
        if not isinstance(payload,dict) or set(payload)-allowed:raise ResourceError("小说回流映射字段无效")
        p=project["id"];unit=self._text_unit(conn,p,payload.get("unit_id"));version,doc=self._text_version(conn,p,unit,payload.get("version_id"))
        if unit["tool"]!="novel" or not doc["body"].strip():raise ResourceError("需要已保存的小说剧本正文结果")
        episode_id=payload.get("episode_id");new_episode=payload.get("new_episode")
        if bool(episode_id)==bool(new_episode):raise ResourceError("请选择现有分集或明确新建分集")
        if episode_id:
            episode_id=checked_id(episode_id);episode=self._one(conn,S.episodes,p,episode_id)
            draft=self._draft(conn,p,episode_id)
            _,types=self._script_types(project["profile_snapshot"].get("stages",[]))
            current=self._current_scripts(conn,p,types);parents=self._object_parents(conn,p)
            covering=[row for row in current if row["project_wide"] or any(scope in self._ancestor_chain(episode_id,parents) for scope in row["scopes"])]
            if any(row["project_wide"] or row["scopes"]!={episode_id} for row in covering):raise ResourceError("已有跨集批准剧本，请先在原剧本入口明确拆分范围","script_scope_change_required")
            if len(covering)>1:raise ResourceError("本集存在多个批准剧本流，请先在原入口处理")
            baseline=covering[0] if covering else None
        else:
            if not isinstance(new_episode,dict) or set(new_episode)!={"work_id","display_code","title","ordinal"}:raise ResourceError("新建分集需作品、编号、标题与序号")
            self._one(conn,S.works,p,checked_id(new_episode["work_id"]))
            for name in ("display_code","title"):text(new_episode[name],200,False)
            if type(new_episode["ordinal"])is not int or new_episode["ordinal"]<0:raise ResourceError("分集序号无效")
            if conn.execute(select(S.creative_objects.c.id).where(S.creative_objects.c.project_id==p,S.creative_objects.c.display_code==new_episode["display_code"])).first():raise Conflict("分集编号已存在，请明确选择更新目标")
            draft,baseline=None,None
        scene_id=payload.get("scene_id")
        if scene_id:
            scene=self._one(conn,S.scenes,p,checked_id(scene_id))
            if not episode_id or scene["parent_id"]!=episode_id:raise ResourceError("资产需求场次不属于目标集")
        else:text(payload.get("new_scene_title"),200,False)
        mapping=payload.get("asset_mapping",{})
        if not isinstance(mapping,dict) or set(mapping)-{str(i) for i in range(len(doc["characters"]))}:raise ResourceError("资产映射必须对应固定人物行号")
        requirements=[]
        for i,row in enumerate(doc["characters"]):
            asset_id=mapping.get(str(i)) or None
            if asset_id:
                asset=self._one(conn,S.asset_identities,p,checked_id(asset_id))
                if asset["asset_kind"]!="character":raise ResourceError("人物需求只能映射人物身份")
            requirements.append(dict(requirement_key="character-"+str(i),category_code="character",purpose="*",description=row["name"]+"："+row["description"],asset_id=asset_id))
        return clean(dict(unit_id=unit["id"],version_id=version["id"],source_sha256=version["sha256"],episode_id=episode_id,new_episode=new_episode,
            scene_id=scene_id,new_scene_title=payload.get("new_scene_title"),body=doc["body"],previous_body=(draft or {}).get("content",{}).get("body",""),previous_content=(draft or {}).get("content"),
            base_draft_revision=(draft or {}).get("draft_revision",0),baseline_artifact_id=(baseline or {}).get("id"),
            requirements=requirements,change="update" if draft else "create",automatic_approval=False))

    def preview_novel_tool_import(self,project_id,payload):
        with self.engine.connect() as conn:
            project=self._project(conn,checked_id(project_id));plan=self._novel_import_plan(conn,project,payload)
            return {"plan":plan,"preview_sha256":digest(plan),"revision":project["revision"]}

    def import_text_tool_novel(self,project_id,payload,**kw):
        if set(payload)!={"request","preview_sha256"}:raise ResourceError("小说回流需要已预览的固定映射")
        def work(conn,project):
            p=project["id"];request=payload["request"];key="novel-tool-import:"+digest(request)
            prior=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if prior:return dict(json.loads(prior["document"]),id=prior["id"],already_imported=True)
            plan=self._novel_import_plan(conn,project,request)
            if digest(plan)!=payload["preview_sha256"]:raise Conflict("分集、正文或草稿基线已变化，请重新预览")
            episode_id=plan["episode_id"]
            if not episode_id:
                new=plan["new_episode"]
                episode_id=self._create_object(conn,project,dict(kind="episode",parent_id=new["work_id"],display_code=new["display_code"],title=new["title"],ordinal=new["ordinal"]))["id"]
            scene_id=plan["scene_id"]
            if not scene_id:
                from sqlalchemy import func
                ordinal=conn.execute(select(func.coalesce(func.max(S.scenes.c.ordinal),-1)).where(S.scenes.c.project_id==p,S.scenes.c.parent_id==episode_id)).scalar_one()+1
                scene_id=self._create_object(conn,project,dict(kind="scene",parent_id=episode_id,display_code="TXT-SC-"+new_id()[:12],title=plan["new_scene_title"],ordinal=ordinal))["id"]
            draft=self._draft(conn,p,episode_id,lock=True)
            if (draft["draft_revision"] if draft else 0)!=plan["base_draft_revision"]:raise Conflict("剧本工作稿已更新，请重新预览")
            content={"format":"vsc.screenplay/v1","project_id":p,"scope":episode_id,"body":plan["body"],"scenes":[],
                "text_tool_source":{"id":plan["version_id"],"sha256":plan["source_sha256"]},"notes":"固定小说工具正文；场景与台词结构需在原剧本入口校对，不自动批准。"}
            if draft:
                conn.execute(update(S.script_drafts).where(S.script_drafts.c.project_id==p,S.script_drafts.c.id==draft["id"]).values(content=content,draft_revision=draft["draft_revision"]+1,updated_by=kw["actor"]))
                draft_id=draft["id"]
            else:
                draft_id=new_id();conn.execute(insert(S.script_drafts).values(project_id=p,id=draft_id,scope_key=episode_id,content=content,draft_revision=1,updated_by=kw["actor"],base_artifact_id=plan["baseline_artifact_id"]))
            requirements=[dict(row,scene_id=scene_id) for row in plan["requirements"]]
            reqkey="novel-tool-requirements:"+plan["unit_id"]+":"+episode_id
            previous=conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==reqkey).order_by(S.artifact_versions.c.version.desc()).limit(1)).scalar()
            req=self._create_artifact(conn,project,dict(artifact_key=reqkey,artifact_type="asset-requirements",stage="assets",object_ids=[episode_id],dependency_ids=[plan["version_id"]],supersedes_id=previous,
                document={"format":"vsc.novel-resource-requirements/v1","project_id":p,"resource_requirements":requirements,"text_tool_version_id":plan["version_id"]}))
            result=dict(episode_id=episode_id,scene_id=scene_id,draft_id=draft_id,draft_revision=plan["base_draft_revision"]+1,requirements_version_id=req["id"],source_version_id=plan["version_id"],approved_baseline_preserved=plan["baseline_artifact_id"],automatic_approval=False)
            receipt=self._create_artifact(conn,project,dict(artifact_key=key,artifact_type="novel-tool-import",stage="script",document=result,dependency_ids=[plan["version_id"],req["id"]],object_ids=[episode_id]))
            return dict(result,id=receipt["id"],already_imported=False)
        return self._mutate(project_id,"import_text_tool_novel",payload,callback=work,**kw)


    def capture_text_tool_evidence(self,project_id,payload,*,build,**kw):
        def work(conn,project):
            p=project["id"];version=self._one(conn,S.artifact_versions,p,checked_id(payload["version_id"]));doc=json.loads(version["document"])
            if version["artifact_type"]!="text-tool-draft" or doc.get("format")!="vsc.text-tool/qc/v1":raise ResourceError("证据帧需要固定质检稿")
            index=payload["issue_index"]
            if not 0<=index<len(doc["issues"]):raise ResourceError("问题序号越界")
            issue=doc["issues"][index];media,gaps=self._usable(conn,p,issue["media_id"],"video_take")
            if [g for g in gaps if g!="technical_check_missing"]:raise ResourceError("证据源媒体当前不可用","qc_source_unusable")
            if not any(r["media_id"]==media["id"] and r["sha256"]==media["sha256"] for r in doc["videos"]):raise Conflict("质检证据不对应固定源视频")
            key="qc-evidence:"+version["id"]+":"+str(index)
            previous=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==p,S.artifact_versions.c.artifact_key==key)).mappings().first()
            if previous:return dict(json.loads(previous["document"]),id=previous["id"],already_captured=True)
            at=min(issue["start_ms"],max(0,(media.get("duration_ms") or 1)-1))
            item,receipt=build(media,at)
            registered=self._register_media(conn,project,dict(item,rights="unknown",source={"kind":"qc-evidence","content":{"version_id":version["id"],"issue_index":index,"source_media_id":media["id"],"source_sha256":media["sha256"],"receipt":receipt}}),kw["actor"])
            op=self.create_media_operation(p,dict(operation_type="qc-evidence-frame",recipe_version="vsc.local-media-tools/v1",tool="ffmpeg",tool_version=receipt["ffmpeg_version"],parameters={"report_version_id":version["id"],"issue_index":index},execution=receipt,inputs=[{"media_id":media["id"],"role":"source","start_ms":at}],outputs=[{"media_id":registered["id"],"role":"evidence"}]),_transaction=(conn,project),**kw)
            result=dict(media_id=registered["id"],sha256=registered["sha256"],operation_id=op["id"],source_media_id=media["id"],report_version_id=version["id"],issue_index=index,receipt=receipt)
            saved=self._create_artifact(conn,project,dict(artifact_key=key,artifact_type="qc-evidence",stage="post",document=result,dependency_ids=[version["id"]]))
            return dict(result,id=saved["id"],already_captured=False)
        return self._mutate(project_id,"capture_text_tool_evidence",payload,callback=work,**kw)

    def _text_subtitle_plan(self,conn,project,payload):
        from copy import deepcopy
        from vsc.post.subtitles import parse_srt
        if not isinstance(payload,dict) or set(payload)!={"version_id","episode_id","clip_id","subtitle_filename"}:raise ResourceError("字幕回流需要固定质检稿、集、片段与字幕文件名")
        p=project["id"];version=self._one(conn,S.artifact_versions,p,checked_id(payload["version_id"]));doc=json.loads(version["document"])
        if version["artifact_type"]!="text-tool-draft" or doc.get("format")!="vsc.text-tool/qc/v1":raise ResourceError("字幕回流需要固定质检稿")
        workspace=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==p,S.edit_workspaces.c.episode_id==checked_id(payload["episode_id"]))).mappings().first()
        if not workspace:raise ResourceError("先在目标集加入原视频片段")
        edit=self._one(conn,S.edit_revisions,p,workspace["current_version_id"]);document=deepcopy(edit["document"]);fps=document["fps"]
        clip=next((r for r in document["clips"] if r["id"]==payload["clip_id"]),None)
        if not clip:raise ResourceError("目标片段不属于本集当前剪辑")
        video=next((r for r in doc["videos"] if r["media_id"]==clip["media_id"]),None)
        subtitle=next((r for r in doc["subtitles"] if r["filename"]==payload["subtitle_filename"]),None)
        if not video or not subtitle:raise ResourceError("目标原视频或字幕不在固定质检版本中")
        media=self._media(conn,p,clip["media_id"])
        if video["sha256"]!=media["sha256"]:raise Conflict("固定质检源片变化")
        from vsc.post.subtitle_formats import normalize_subtitle
        normalized=normalize_subtitle(subtitle['filename'],subtitle['text'],duration=media['duration_ms']/1000,require_timing=True)
        entries=[(r['start_ms']/1000,r['end_ms']/1000,r['text']) for r in normalized['cues']]
        offset=0
        for row in document["clips"]:
            if row["id"]==clip["id"]:break
            offset+=row["out_frame"]-row["in_frame"]
        end=offset+clip["out_frame"]-clip["in_frame"]
        before=deepcopy(document["captions"])
        # Preserve portions of old captions outside the explicitly replaced clip interval.
        retained=[]
        for row in before:
            if row["end_frame"]<=offset or row["start_frame"]>=end:retained.append(row)
            else:
                if row["start_frame"]<offset:retained.append(dict(row,end_frame=offset))
                if row["end_frame"]>end:retained.append(dict(row,start_frame=end))
        added=[]
        for i,(a,b,body) in enumerate(entries):
            start=max(clip["in_frame"],round(a*fps));stop=min(clip["out_frame"],round(b*fps))
            if stop>start:added.append(dict(start_frame=offset+start-clip["in_frame"],end_frame=offset+stop-clip["in_frame"],text=body))
        if not added:raise ResourceError("字幕没有覆盖所选片段区间")
        document["captions"]=sorted(retained+added,key=lambda r:(r["start_frame"],r["end_frame"]))
        return dict(episode_id=workspace["episode_id"],edit_revision=workspace["revision"],edit_version_id=edit["id"],report_version_id=version["id"],clip_id=clip["id"],replace_interval={"start_frame":offset,"end_frame":end},captions_before=before,document=document)

    def preview_text_tool_subtitles(self,project_id,payload):
        with self.engine.connect() as conn:
            project=self._project(conn,project_id);plan=self._text_subtitle_plan(conn,project,payload)
            return {"plan":plan,"preview_sha256":digest(plan),"revision":project["revision"]}

    def apply_text_tool_subtitles(self,project_id,payload,**kw):
        if set(payload)!={"request","preview_sha256"}:raise ResourceError("先预览字幕回流范围")
        def work(conn,project):
            from .editor_workspace import EditorWorkspaceRepository
            plan=self._text_subtitle_plan(conn,project,payload["request"])
            if digest(plan)!=payload["preview_sha256"]:raise Conflict("质检稿或剪辑已变化，请重新预览")
            return EditorWorkspaceRepository(self).save(project_id,{k:plan[k] for k in ("episode_id","edit_revision","document")},_transaction=(conn,project),**kw)
        return self._mutate(project_id,"apply_text_tool_subtitles",payload,callback=work,**kw)

    def create_text_batch(self,project_id,payload,**kw):
        if set(payload)-{'tool','action','unit_ids','auto_accept','overwrite','qa_unit_id'} or payload.get('tool') not in TOOLS or payload.get('action') not in TOOLS[payload['tool']]['actions']:
            raise ResourceError('批次需要明确工具、动作和工作单元')
        ids=payload.get('unit_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=200 or len(set(ids))!=len(ids):raise ResourceError('批次需要1–200个不重复单元')
        if type(payload.get('auto_accept',False))is not bool or type(payload.get('overwrite',False))is not bool:raise ResourceError('批次采用和改写标记无效')
        def work(conn,project):
            p=project['id'];identifier=new_id();rows=[]
            for uid in ids:
                unit=self._text_unit(conn,p,uid);fixed,doc=self._text_version(conn,p,unit)
                if unit['tool']!=payload['tool'] or unit['locked']:raise Conflict('批次单元类型不一致或已锁定')
                if unit['tool']=='translation' and payload['action']=='translate' and doc.get('translation_stage')=='complete':raise Conflict('完成译文须显式重新打开编辑')
                status='skipped' if payload['action'] in {'body','translate'} and doc.get('body','').strip() and not payload.get('overwrite') else 'pending'
                rows.append(dict(unit_id=uid,input_version_id=fixed['id'],action=payload['action'],status=status))
            qa=payload.get('qa_unit_id')
            if qa:
                if payload['tool']!='novel' or payload['action']!='body' or not payload.get('auto_accept'):raise ResourceError('跨集QA需要自动采用正文批次')
                base=self._text_unit(conn,p,qa);fixed,_=self._text_version(conn,p,base)
                plan=conn.execute(select(S.text_tool_novel_plans).where(S.text_tool_novel_plans.c.project_id==p,S.text_tool_novel_plans.c.unit_id==qa).order_by(S.text_tool_novel_plans.c.created_at.desc()).limit(1)).mappings().first()
                linked=set(conn.execute(select(S.text_tool_novel_episodes.c.unit_id).where(S.text_tool_novel_episodes.c.project_id==p,S.text_tool_novel_episodes.c.plan_id==plan['id'])).scalars()) if plan else set()
                if linked!=set(ids):raise ResourceError('联合QA批次必须覆盖当前计划的完整分集')
                rows.append(dict(unit_id=qa,input_version_id=fixed['id'],action='qa_notes',status='pending'))
            materials_id=None
            if payload['tool']=='novel':
                from vsc.production.text_tools import novel_materials_packet
                materials_id=self._create_artifact(conn,project,dict(artifact_type='text-tool-role-materials',artifact_key='text-batch-role-materials:'+identifier,document=novel_materials_packet([r['action'] for r in rows]),dependency_ids=list(dict.fromkeys(r['input_version_id'] for r in rows))))['id']
            conn.execute(insert(S.text_tool_batches).values(project_id=p,id=identifier,tool=payload['tool'],action=payload['action'],auto_accept=payload.get('auto_accept',False),status='ready',item_count=len(rows),materials_artifact_id=materials_id,created_by=kw['actor']))
            for index,row in enumerate(rows):conn.execute(insert(S.text_tool_batch_items).values(project_id=p,id=new_id(),batch_id=identifier,ordinal=index,**row))
            return {'id':identifier,'count':len(rows),'status':'ready'}
        return self._mutate(project_id,'create_text_batch',payload,callback=work,**kw)

    def get_text_batch(self,project_id,batch_id):
        with self.engine.connect() as conn:
            project=self._project(conn,project_id);batch=self._one(conn,S.text_tool_batches,project_id,checked_id(batch_id))
            items=[dict(r) for r in conn.execute(select(S.text_tool_batch_items).where(S.text_tool_batch_items.c.project_id==project_id,S.text_tool_batch_items.c.batch_id==batch_id).order_by(S.text_tool_batch_items.c.ordinal)).mappings()]
            for row in items:row['title']=self._text_unit(conn,project_id,row['unit_id'])['title']
            return clean(dict(batch,items=items,revision=project['revision']))

    def list_text_batches(self,project_id,tool):
        with self.engine.connect() as conn:
            project=self._project(conn,project_id)
            rows=conn.execute(select(S.text_tool_batches).where(S.text_tool_batches.c.project_id==project_id,S.text_tool_batches.c.tool==tool).order_by(S.text_tool_batches.c.created_at.desc()).limit(50)).mappings()
            return clean({'items':[dict(r) for r in rows],'revision':project['revision']})

    def claim_text_batch(self,project_id,payload,**kw):
        def work(conn,project):
            p=project['id'];batch=self._one(conn,S.text_tool_batches,p,payload['batch_id'])
            if batch['status'] in {'stopped','completed'}:return dict(batch,item=None)
            rows=conn.execute(select(S.text_tool_batch_items).where(S.text_tool_batch_items.c.project_id==p,S.text_tool_batch_items.c.batch_id==batch['id']).order_by(S.text_tool_batch_items.c.ordinal)).mappings().all()
            item=next((dict(r) for r in rows if r['status'] not in {'completed','skipped'}),None)
            if item and item['status'] in {'failed','blocked'}:return dict(batch,item=None)
            conn.execute(update(S.text_tool_batches).where(S.text_tool_batches.c.project_id==p,S.text_tool_batches.c.id==batch['id']).values(status='running' if item else 'completed'))
            if item:conn.execute(update(S.text_tool_batch_items).where(S.text_tool_batch_items.c.project_id==p,S.text_tool_batch_items.c.id==item['id']).values(status='running'))
            return dict(batch,item=item)
        return self._mutate(project_id,'claim_text_batch',payload,callback=work,**kw)

    def finish_text_batch_item(self,project_id,payload,**kw):
        def work(conn,project):
            row=self._one(conn,S.text_tool_batch_items,project['id'],payload['item_id'])
            if row['status'] in {'completed','skipped'}:return dict(row)
            if payload.get('attempt_id'):
                attempt=self._one(conn,S.text_tool_attempts,project['id'],payload['attempt_id'])
                if attempt['unit_id']!=row['unit_id'] or attempt['input_version_id']!=row['input_version_id'] or attempt['action']!=row['action']:raise ResourceError('批次回执不属于固定单元输入')
            values={k:payload.get(k) for k in ('status','attempt_id','output_version_id','error_code')}
            conn.execute(update(S.text_tool_batch_items).where(S.text_tool_batch_items.c.project_id==project['id'],S.text_tool_batch_items.c.id==row['id']).values(**values))
            return dict(row,**values)
        return self._mutate(project_id,'finish_text_batch_item',payload,callback=work,**kw)

    def stop_text_batch(self,project_id,payload,**kw):
        def work(conn,project):
            batch=self._one(conn,S.text_tool_batches,project['id'],payload['batch_id'])
            if batch['status']!='completed':conn.execute(update(S.text_tool_batches).where(S.text_tool_batches.c.project_id==project['id'],S.text_tool_batches.c.id==batch['id']).values(status='stopped'))
            return {'id':batch['id'],'status':'stopped','in_flight_preserved':True}
        return self._mutate(project_id,'stop_text_batch',payload,callback=work,**kw)

    def decide_text_issue(self,project_id,payload,**kw):
        if set(payload)!={'version_id','issue_index','decision','reason'} or payload['decision'] not in {'open','fixed','dismissed'} or type(payload['issue_index'])is not int:raise ResourceError('问题处理需要固定报告、行号、决定与理由')
        text(payload['reason'],2000,False)
        def work(conn,project):
            fixed=self._one(conn,S.artifact_versions,project['id'],payload['version_id']);doc=json.loads(fixed['document'])
            if fixed['artifact_type']!='text-tool-draft' or doc.get('format')!='vsc.text-tool/qc/v1' or not 0<=payload['issue_index']<len(doc['issues']):raise ResourceError('问题处理不属于固定质检报告')
            identifier=new_id();conn.execute(insert(S.text_tool_issue_decisions).values(project_id=project['id'],id=identifier,created_by=kw['actor'],**payload))
            return {'id':identifier,**payload}
        return self._mutate(project_id,'decide_text_issue',payload,callback=work,**kw)

    def text_issue_reviews(self,project_id,version_id):
        with self.engine.connect() as conn:
            self._project(conn,project_id)
            rows=conn.execute(select(S.text_tool_issue_decisions).where(S.text_tool_issue_decisions.c.project_id==project_id,S.text_tool_issue_decisions.c.version_id==version_id).order_by(S.text_tool_issue_decisions.c.created_at)).mappings()
            latest={r['issue_index']:dict(r) for r in rows};return clean(list(latest.values()))

    def freeze_text_review_report(self,project_id,payload,**kw):
        def work(conn,project):
            fixed=self._one(conn,S.artifact_versions,project['id'],payload['version_id']);doc=json.loads(fixed['document'])
            if fixed['artifact_type']!='text-tool-draft' or doc.get('format')!='vsc.text-tool/qc/v1':raise ResourceError('需要固定质检工作稿')
            decisions=conn.execute(select(S.text_tool_issue_decisions).where(S.text_tool_issue_decisions.c.project_id==project['id'],S.text_tool_issue_decisions.c.version_id==fixed['id']).order_by(S.text_tool_issue_decisions.c.created_at)).mappings()
            doc['review_decisions']=clean(list({r['issue_index']:dict(r) for r in decisions}.values()));doc['evidence_images']=[]
            for row in conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project['id'],S.artifact_versions.c.artifact_type=='qc-evidence')).mappings():
                evidence=json.loads(row['document'])
                if evidence['report_version_id']==fixed['id']:doc['evidence_images'].append({k:evidence[k] for k in ('issue_index','media_id','sha256')})
            doc['report_source_version_id']=fixed['id'];doc['report_source_sha256']=fixed['sha256']
            return self._create_artifact(conn,project,{'artifact_type':'text-tool-review-report','artifact_key':'text-review:'+new_id(),'stage':'post','document':doc,'dependency_ids':[fixed['id']]})
        return self._mutate(project_id,'freeze_text_review_report',payload,callback=work,**kw)

    def set_translation_stage(self,project_id,payload,**kw):
        if set(payload)!={'unit_id','version_id','stage'} or payload['stage'] not in {'draft','terms_reviewed','translated','complete'}:raise ResourceError('翻译阶段变更无效')
        def work(conn,project):
            unit=self._text_unit(conn,project['id'],payload['unit_id']);fixed,doc=self._text_version(conn,project['id'],unit,payload['version_id'])
            if unit['tool']!='translation' or unit['current_version_id']!=fixed['id']:raise Conflict('翻译工作稿已变化')
            if payload['stage'] in {'translated','complete'} and not doc['body'].strip():raise ResourceError('先保存译文')
            if payload['stage']=='complete' and not doc.get('proofread'):raise ResourceError('完成前须明确人工精校')
            saved=self._text_store_document(conn,project,unit,dict(doc,translation_stage=payload['stage'],proofread=False if payload['stage']=='draft' else doc['proofread']),fixed['id'])
            conn.execute(update(S.text_tool_units).where(S.text_tool_units.c.project_id==project['id'],S.text_tool_units.c.id==unit['id']).values(locked=payload['stage']=='complete'))
            return dict(saved,unit_id=unit['id'],stage=payload['stage'])
        return self._mutate(project_id,'set_translation_stage',payload,callback=work,**kw)

    def _breakdown_canvas_plan(self,conn,project,payload):
        if set(payload)!={'unit_id','version_id','canvas_id','canvas_revision','source_node_id','dimension'} or payload['dimension'] not in {'storyboard','video','audio'}:raise ResourceError('拉片回流需固定工作稿、原画布源节点与维度')
        unit=self._text_unit(conn,project['id'],payload['unit_id']);fixed,doc=self._text_version(conn,project['id'],unit,payload['version_id'])
        if unit['tool']!='breakdown' or not doc['observations']:raise ResourceError('请先保存带时码观察结果')
        canvas,current=self._canvas_version(conn,project,payload['canvas_id'])
        if current['version']!=payload['canvas_revision']:raise Conflict('原画布已有新版本，请重新预览')
        document=self._canvas_document(conn,project['id'],current);source=next((n for n in document['nodes'] if n['id']==payload['source_node_id']),None)
        if not source or source['type']!='video' or source['media_id']!=doc['media_id']:raise ResourceError('回流源节点必须引用本次理解的固定视频')
        allowed={'storyboard':{'scene','character','action','screen_text'},'video':{'scene','action','camera','visual'},'audio':{'dialogue','audio','music'}}[payload['dimension']]
        observations=[r for r in doc['observations'] if r['kind'] in allowed]
        if payload['dimension']=='audio' and doc.get('observation_basis')=='sampled_frames_no_audio':raise ResourceError('抽帧观察没有音轨证据，不能产生音频维度结果')
        if not observations:raise ResourceError('所选维度没有可用的实际观察')
        if len(document['nodes'])+len(observations)>200:raise ResourceError('回流超过单画布200节点，请分批')
        nodes=[];edges=[]
        for i,row in enumerate(observations):
            key='analysis-'+fixed['id'][:12]+'-'+payload['dimension']+'-'+str(i)
            if any(n['id']==key for n in document['nodes']):continue
            nodes.append({'id':key,'type':'text','title':{'storyboard':'分镜观察','video':'视频区间','audio':'音频观察'}[payload['dimension']]+' '+str(i+1),
                'x':source['x']+360,'y':source['y']+i*180,'text':str(row['start_ms'])+'–'+str(row['end_ms'])+' ms\n'+row['text'],
                'params':{'analysis_dimension':payload['dimension'],'source_start_ms':row['start_ms'],'source_end_ms':row['end_ms'],'source_version_id':fixed['id'],'observation_basis':doc.get('observation_basis','manual')},'group':'analysis-'+fixed['id'][:12]})
            edges.append({'id':'edge-'+key,'source':source['id'],'target':key,'port':'derived_from'})
        return {'canvas_id':canvas['id'],'canvas_revision':current['version'],'title':current['title'],'source_version_id':fixed['id'],'document':dict(document,nodes=document['nodes']+nodes,edges=document['edges']+edges),'added_count':len(nodes)}

    def preview_breakdown_canvas(self,project_id,payload):
        with self.engine.connect() as conn:
            project=self._project(conn,project_id);plan=self._breakdown_canvas_plan(conn,project,payload)
            return {'plan':plan,'preview_sha256':digest(plan),'revision':project['revision']}

    def apply_breakdown_canvas(self,project_id,payload,**kw):
        if set(payload)!={'request','preview_sha256'}:raise ResourceError('回流需要固定预览')
        def work(conn,project):
            key='breakdown-canvas:'+digest(payload)
            old=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==project['id'],S.artifact_versions.c.artifact_key==key)).mappings().first()
            if old:return json.loads(old['document'])
            plan=self._breakdown_canvas_plan(conn,project,payload['request'])
            if digest(plan)!=payload['preview_sha256']:raise Conflict('画布或理解结果发生变化，请重新预览')
            saved=self.save_creative_canvas(project['id'],{k:plan[k] for k in ('canvas_id','canvas_revision','title','document')},_transaction=(conn,project),**kw)
            result={'canvas_id':plan['canvas_id'],'version_id':saved['version_id'],'added_count':plan['added_count']}
            self._create_artifact(conn,project,{'artifact_key':key,'artifact_type':'breakdown-canvas-import','stage':'direct','document':result,'dependency_ids':[plan['source_version_id']]})
            return result
        return self._mutate(project_id,'apply_breakdown_canvas',payload,callback=work,**kw)
