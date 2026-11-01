"""Append-only workflow revisions reference the original production authority."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib,json
from sqlalchemy import select,insert,update,func,and_
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.production.intelligent_production import DEFINITION,SKILLS,normalize_unit,normalize_document,validate_plan
from . import schema as S
from .values import clean,new_id,checked_id,digest


class IntelligentProductionRepository:
    def _intelligent_version(self,conn,p,workflow_id,version_id=None):
        workflow=self._one(conn,S.intelligent_workflows,p,workflow_id)
        if version_id:
            version=self._one(conn,S.intelligent_versions,p,version_id)
            if version['workflow_id']!=workflow['id']:raise ResourceError('版本不属于当前流程')
        else:
            version=conn.execute(select(S.intelligent_versions).where(S.intelligent_versions.c.project_id==p,S.intelligent_versions.c.workflow_id==workflow['id']).order_by(S.intelligent_versions.c.version.desc()).limit(1)).mappings().one()
        return dict(workflow),dict(version)

    def _intelligent_state(self,conn,p,v):
        def members(table):return [dict(r) for r in conn.execute(select(table).where(table.c.project_id==p,table.c.version_id==v['id'])).mappings()]
        artifact=self._one(conn,S.artifact_versions,p,v['artifact_id'])
        document=json.loads(bytes(artifact['document']))
        strip=lambda row:{k:value for k,value in row.items() if k not in {'project_id','version_id','ordinal'}}
        return dict(document=document,source_artifact_id=v['source_artifact_id'],template_artifact_id=v['template_artifact_id'],route=v['route'],blocking_mode=v['blocking_mode'],assets=[strip(a) for a in sorted(members(S.intelligent_assets),key=lambda a:a['ordinal'])],units=[strip(u) for u in sorted(members(S.intelligent_units),key=lambda u:u['ordinal'])],dependencies=[strip(d) for d in members(S.intelligent_dependencies)],media=[strip(m) for m in members(S.intelligent_media)])

    def list_intelligent_workflows(self,p,episode_id=None):
        from .project_management import filter_management_rows
        with self.engine.connect() as conn:
            project=self._project(conn,p);query=select(S.intelligent_workflows).where(S.intelligent_workflows.c.project_id==project['id'])
            if episode_id:query=query.where(S.intelligent_workflows.c.episode_id==checked_id(episode_id))
            return clean(dict(items=filter_management_rows(conn,project["id"],S.intelligent_workflows,[dict(r) for r in conn.execute(query.order_by(S.intelligent_workflows.c.created_at.desc())).mappings()]),revision=project['revision']))

    def get_intelligent_workflow(self,p,identifier,version_id=None):
        with self.engine.connect() as conn:
            project=self._project(conn,p);workflow,v=self._intelligent_version(conn,p,identifier,version_id)
            if version_id is None:
                from .project_management import filter_management_rows
                if not filter_management_rows(conn,p,S.intelligent_workflows,[workflow]):raise ResourceError("流程所属对象已回收","object_recycled",409)
            state=self._intelligent_state(conn,p,v)
            definition_row=self._one(conn,S.intelligent_definitions,p,workflow['definition_id'])
            definition=json.loads(bytes(self._one(conn,S.artifact_versions,p,definition_row['artifact_id'])['document']))
            versions=[dict(r) for r in conn.execute(select(S.intelligent_versions).where(S.intelligent_versions.c.project_id==p,S.intelligent_versions.c.workflow_id==identifier).order_by(S.intelligent_versions.c.version.desc())).mappings()]
            ids=[r['id'] for r in versions]
            tasks=[self._intelligent_task(conn,project,r) for r in conn.execute(select(S.intelligent_tasks).where(S.intelligent_tasks.c.project_id==p,S.intelligent_tasks.c.version_id.in_(ids)).order_by(S.intelligent_tasks.c.created_at)).mappings()]
            runs=[dict(r) for r in conn.execute(select(S.intelligent_runs).where(S.intelligent_runs.c.project_id==p,S.intelligent_runs.c.version_id.in_(ids))).mappings()]
            later=S.binding_decisions.alias('intelligent_later_decision')
            candidates=[dict(r) for r in conn.execute(select(S.binding_decisions.c.id.label('decision_id'),S.binding_candidates.c.media_id,S.binding_slots.c.target_object_id,S.binding_slots.c.role).join(S.binding_candidates,and_(S.binding_decisions.c.project_id==S.binding_candidates.c.project_id,S.binding_decisions.c.candidate_id==S.binding_candidates.c.id)).join(S.binding_slots,and_(S.binding_slots.c.project_id==S.binding_candidates.c.project_id,S.binding_slots.c.id==S.binding_candidates.c.slot_id)).where(S.binding_decisions.c.project_id==p,S.binding_decisions.c.outcome=='select',~select(later.c.id).where(later.c.project_id==p,later.c.slot_id==S.binding_decisions.c.slot_id,later.c.decision_sequence>S.binding_decisions.c.decision_sequence).exists())).mappings()]
            dependencies=[]
            for d in state['dependencies']:
                source=self._one(conn,S.intelligent_versions,p,d['source_version_id']);source_state=self._intelligent_state(conn,p,source)
                node=next(u for u in source_state['units'] if u['unit_key']==d['source_unit_key'])
                selected=[m for m in source_state['media'] if m['unit_key']==node['unit_key'] and m['purpose']=='blocking']
                dependencies.append(dict(d,source_title=node['title'],selected=selected,skipped=bool(node['skip_reason'])))
            return clean(dict(workflow=workflow,definition=definition,asset_runs=[dict(r) for r in conn.execute(select(S.intelligent_asset_runs).where(S.intelligent_asset_runs.c.project_id==p,S.intelligent_asset_runs.c.version_id==v['id'])).mappings()],version=v,state=state,history=versions,tasks=tasks,runs=runs,selected_media=candidates,dependency_inputs=dependencies,revision=project['revision'],provider_submitted=False))

    def _insert_intelligent_version(self,conn,project,workflow,state,actor,base=None):
        from vsc.production.intelligent_production import ROUTES
        p=project['id'];state=deepcopy(state);identifier=new_id();document=normalize_document(state.get('document',{}))
        if state.get('route') not in ROUTES or state.get('blocking_mode') not in {'2d','3d','skip'}:raise ResourceError('流程路线与站位方式必须明确')
        if state['blocking_mode']=='skip' and not document['skip_blocking_reason'].strip():raise ResourceError('跳过站位需要记录理由')
        units=[normalize_unit(u) for u in state.get('units',[])];assets=state.get('assets',[]);deps=state.get('dependencies',[]);media=state.get('media',[])
        if len(units)>200 or len(assets)>200 or len(deps)>1000 or len(media)>2000:raise ResourceError('流程规模超过当前上限')
        keys={u['unit_key'] for u in units}
        if len(keys)!=len(units):raise ResourceError('单元标识重复')
        for unit in units:
            if unit['shot_id']:
                shot=self._one(conn,S.shots,p,unit['shot_id']);sequence=self._one(conn,S.sequences,p,shot['parent_id']);scene=self._one(conn,S.scenes,p,sequence['parent_id'])
                if scene['parent_id']!=workflow['episode_id']:raise ResourceError('镜头不属于流程所在集')
            if unit['spatial_version_id']:
                spatial=self._one(conn,S.spatial_scene_versions,p,unit['spatial_version_id']);scene=self._one(conn,S.spatial_scenes,p,spatial['spatial_scene_id'])
                if scene['episode_id'] and scene['episode_id']!=workflow['episode_id']:raise ResourceError('三维场景不属于当前集')
        for field in ('source_artifact_id','template_artifact_id'):
            if state.get(field):self._one(conn,S.artifact_versions,p,state[field])
        pins=list({a for a in (state.get('source_artifact_id'),state.get('template_artifact_id')) if a})
        artifact=self._create_artifact(conn,project,dict(artifact_key='intelligent-state:'+workflow['id'],artifact_type='intelligent-workflow-state',document=document,object_ids=[workflow['episode_id']],dependency_ids=pins))
        row=dict(project_id=p,id=identifier,workflow_id=workflow['id'],version=(base['version']+1 if base else 1),parent_id=base['id'] if base else None,artifact_id=artifact['id'],source_artifact_id=state.get('source_artifact_id'),template_artifact_id=state.get('template_artifact_id'),route=state['route'],blocking_mode=state['blocking_mode'],unit_count=len(units),asset_count=len(assets),dependency_count=len(deps),media_count=len(media),created_by=actor)
        conn.execute(insert(S.intelligent_versions).values(**row))
        for i,asset in enumerate(assets):
            if set(asset)!={'asset_key','asset_id','spec_id'}:raise ResourceError('资产链接字段无效')
            conn.execute(insert(S.intelligent_assets).values(project_id=p,version_id=identifier,ordinal=i,**asset))
        for i,unit in enumerate(units):conn.execute(insert(S.intelligent_units).values(project_id=p,version_id=identifier,ordinal=i,**unit))
        for dep in deps:
            if set(dep)!={'unit_key','source_version_id','source_unit_key','purpose'} or dep['unit_key'] not in keys:raise ResourceError('依赖目标已删除或字段不正确')
            if dep['source_version_id']=='current':
                dep['source_version_id']=identifier
                if dep['source_unit_key'] not in keys:raise ResourceError('首子依赖不能悬空')
            conn.execute(insert(S.intelligent_dependencies).values(project_id=p,version_id=identifier,**dep))
        for link in media:
            if set(link)-{'unit_key','purpose','media_id','decision_id','spatial_export_id'} or link.get('unit_key') not in keys:raise ResourceError('媒体链接不属于本次单元')
            item=self._one(conn,S.media_items,p,link['media_id'])
            if item['modality']!='image':raise ResourceError('站位与线稿必须引用真实图片')
            unit=next(u for u in units if u['unit_key']==link['unit_key'])
            if link.get('spatial_export_id'):
                export=self._one(conn,S.spatial_exports,p,link['spatial_export_id'])
                if export['format']!='png' or export['version_id']!=unit['spatial_version_id']:raise ResourceError('截图必须来自单元固定的三维版本')
            conn.execute(insert(S.intelligent_media).values(project_id=p,version_id=identifier,**link))
        return dict(id=workflow['id'],version_id=identifier,version=row['version'],artifact_id=artifact['id'],provider_submitted=False)

    def create_intelligent_workflow(self,p,payload,actor,**kw):
        def work(conn,project):
            episode=self._one(conn,S.episodes,p,payload.get('episode_id'));title=payload.get('title','智能制作')
            if not isinstance(title,str) or not title.strip() or len(title)>200:raise ResourceError('请输入流程标题')
            definition=conn.execute(select(S.intelligent_definitions).where(S.intelligent_definitions.c.project_id==p,S.intelligent_definitions.c.key=='intelligent',S.intelligent_definitions.c.version==1)).mappings().first()
            if not definition:
                artifact=self._create_artifact(conn,project,dict(artifact_key='intelligent-definition:v1',artifact_type='intelligent-workflow-definition',document=DEFINITION))
                definition={'id':new_id()};conn.execute(insert(S.intelligent_definitions).values(project_id=p,id=definition['id'],key='intelligent',version=1,artifact_id=artifact['id']))
            workflow=dict(id=new_id(),episode_id=episode['id'],definition_id=definition['id'],title=title,created_by=actor)
            conn.execute(insert(S.intelligent_workflows).values(project_id=p,**workflow))
            state=dict(document={'script_text':payload.get('script_text','')},route=payload.get('route','creation'),blocking_mode=payload.get('blocking_mode','2d'),source_artifact_id=payload.get('source_artifact_id'),template_artifact_id=None,assets=[],units=[],dependencies=[],media=[])
            if state['source_artifact_id']:
                source=self._one(conn,S.artifact_versions,p,state['source_artifact_id']);fixed=bytes(source['document']).decode('utf8')
                if state['document']['script_text'] and state['document']['script_text']!=fixed:raise ResourceError('引用原剧本版本时正文必须一致；修改请保存新版本')
                state['document']['script_text']=fixed
            if state['document']['script_text'] and not state['source_artifact_id']:
                original=self._create_artifact(conn,project,dict(artifact_key='intelligent-source:'+workflow['id'],artifact_type='script',document=state['document']['script_text'],object_ids=[episode['id']]))
                state['source_artifact_id']=original['id']
            return self._insert_intelligent_version(conn,project,workflow,state,actor)
        return self._mutate(p,'create_intelligent_workflow',payload,actor=actor,callback=work,**kw)

    def save_intelligent_workflow(self,p,payload,actor,build_preview,**kw):
        def work(conn,project):
            workflow,base=self._intelligent_version(conn,p,payload.get('workflow_id'))
            if base['id']!=payload.get('base_version_id'):raise Conflict('流程已有新版本，旧稿保留','intelligent_version_conflict')
            preview=build_preview(p,{k:v for k,v in payload.items() if k!='impact_sha256'})
            if preview['sha256']!=payload.get('impact_sha256'):raise Conflict('影响清单已变化，请重新查看','intelligent_impact_changed')
            state=deepcopy(payload['state']);old=self._intelligent_state(conn,p,base)
            if state['document'].get('script_text')!=old['document']['script_text']:
                source=self._create_artifact(conn,project,dict(artifact_key='intelligent-source:'+workflow['id'],artifact_type='script',document=state['document'].get('script_text',''),object_ids=[workflow['episode_id']]))
                state['source_artifact_id']=source['id']
            if (state['document'].get('template_key'),state['document'].get('template_text'))!=(old['document']['template_key'],old['document']['template_text']) or not state.get('template_artifact_id'):
                template=self._create_artifact(conn,project,dict(artifact_key='intelligent-template:'+workflow['id'],artifact_type='intelligent-template',document={k:state['document'].get(k,'') for k in ('template_key','template_text')},object_ids=[workflow['episode_id']]))
                state['template_artifact_id']=template['id']
            return self._insert_intelligent_version(conn,project,workflow,state,actor,base)
        return self._mutate(p,'save_intelligent_workflow',payload,actor=actor,callback=work,**kw)

    def _intelligent_task(self,conn,project,row):
        row=dict(row);version=self._one(conn,S.intelligent_versions,project['id'],row['version_id']);row['state']=self._intelligent_state(conn,project['id'],version);row['workflow_id']=version['workflow_id']
        row['plan']=json.loads(bytes(self._one(conn,S.artifact_versions,project['id'],row['plan_artifact_id'])['document'])) if row['plan_artifact_id'] else None
        return clean(dict(row,revision=project['revision'],provider_submitted=False))
    def get_intelligent_task(self,p,identifier):
        with self.engine.connect() as conn:return self._intelligent_task(conn,self._project(conn,p),self._one(conn,S.intelligent_tasks,p,identifier))

    def create_intelligent_task(self,p,payload,actor,**kw):
        from vsc.bootstrap import repository_root
        from vsc.project.role_runtime import bind_packet
        def work(conn,project):
            workflow,base=self._intelligent_version(conn,p,payload.get('workflow_id'))
            if base['id']!=payload.get('base_version_id'):raise Conflict('先保存并核对当前流程版本')
            stage=payload.get('stage');message=payload.get('message')
            if stage not in SKILLS or not isinstance(message,str) or not message.strip() or len(message)>6000:raise ResourceError('请选择可规划阶段并输入明确请求')
            state=self._intelligent_state(conn,p,base)
            if not state['document']['script_text'].strip():raise ResourceError('先保存整集剧本')
            if stage=='script' and (not base['template_artifact_id'] or not state['document']['template_text'].strip()):raise ResourceError('先确认并保存有实际规则的固定模板')
            identifier=new_id();skill,role=SKILLS[stage];sha=hashlib.sha256((repository_root()/'skills'/skill/'SKILL.md').read_bytes()).hexdigest()
            packet=bind_packet({'context_id':'intelligent-'+identifier,'project':{'project_id':p},'revision':project['revision'],'role':self._role(role),'task':message,'inputs':[],'approved_memories':[],'scope':workflow['episode_id'],'parent_brief':{'content':json.dumps({'workflow_version_id':base['id'],'artifact_id':base['artifact_id'],'skill_sha256':sha}),'persistence':'context_file_only_not_long_term_memory'},'rules':['输入仅为固定草稿，不获得创作批准。','不得调用媒体供应商；仅返回结构化可编辑建议。']},host='grok-build-intelligent-plan',actor=actor,ownership=[])
            internal=dict(actor=actor,expected_revision=project['revision'],idempotency_key='intelligent-internal',_transaction=(conn,project))
            dispatch=self.create_role_dispatch(p,{'packet':packet},**internal)
            self.consume_role_dispatch(p,dict(dispatch_id=dispatch['dispatch_id'],instance_id=packet['dispatch']['instance_id'],role_id=role,context_sha256=packet['context_sha256'],packet=packet),**internal)
            conn.execute(insert(S.intelligent_tasks).values(project_id=p,id=identifier,version_id=base['id'],dispatch_id=dispatch['dispatch_id'],stage=stage,message=message,skill_id=skill,skill_sha256=sha,status='queued',created_by=actor))
            return dict(id=identifier,status='queued',dispatch_id=dispatch['dispatch_id'],provider_submitted=False)
        return self._mutate(p,'create_intelligent_task',payload,actor=actor,callback=work,**kw)

    def claim_intelligent_task(self,p,identifier):
        with self.engine.begin() as conn:
            from vsc.assets.access_control import current_principal
            principal=current_principal()
            if principal:self.access_transaction_guard(conn,p,'execute_intelligent_task',{'task_id':identifier},principal.actor)
            project=self._project(conn,p,lock=True);row=self._one(conn,S.intelligent_tasks,p,identifier);claimed=row['status']=='queued'
            where=and_(S.intelligent_tasks.c.project_id==p,S.intelligent_tasks.c.id==identifier)
            if claimed:conn.execute(update(S.intelligent_tasks).where(where).values(status='running',started_at=datetime.now(timezone.utc)))
            elif row['status']=='running' and row['started_at']<datetime.now(timezone.utc)-timedelta(seconds=180):conn.execute(update(S.intelligent_tasks).where(where).values(status='submission_unknown',error='intelligent_submission_unknown'))
            return dict(self._intelligent_task(conn,project,self._one(conn,S.intelligent_tasks,p,identifier)),claimed=claimed)
    def persist_intelligent_result(self,p,identifier,result,error):
        with self.engine.begin() as conn:
            self._project(conn,p,lock=True);status='result_ready' if result is not None else 'submission_unknown' if error=='intelligent_submission_unknown' else 'failed'
            conn.execute(update(S.intelligent_tasks).where(S.intelligent_tasks.c.project_id==p,S.intelligent_tasks.c.id==identifier,S.intelligent_tasks.c.status.in_(['running','submission_unknown']),S.intelligent_tasks.c.host_result.is_(None)).values(host_result=result,error=error,status=status))
    def _return_intelligent(self,conn,project,task,artifact=None):
        packet=self._one(conn,S.role_dispatches,project['id'],task['dispatch_id'])['packet'];d=packet['dispatch']
        result=dict(role_id=d['role_id'],role_sha256=d['role_sha256'],context_id=packet['context_id'],context_sha256=packet['context_sha256'],dispatch_id=d['id'],instance_id=d['instance_id'],result_refs=[dict(kind='artifact',id=artifact['id'],sha256=artifact['sha256'])] if artifact else [],memory_proposals=[])
        self.return_role_dispatch(project['id'],dict(dispatch_id=d['id'],instance_id=d['instance_id'],role_id=d['role_id'],context_sha256=packet['context_sha256'],result=result,return_key='intelligent:'+task['id'],closed=True),actor=task['created_by'],expected_revision=project['revision'],idempotency_key='intelligent-return',_transaction=(conn,project))
    def finish_intelligent_task(self,p,payload,actor,**kw):
        def work(conn,project):
            task=self._one(conn,S.intelligent_tasks,p,payload['task_id'])
            if task['status']!='result_ready':return dict(id=task['id'],status=task['status'])
            plan=validate_plan(task['host_result'],task['stage']);version=self._one(conn,S.intelligent_versions,p,task['version_id']);workflow=self._one(conn,S.intelligent_workflows,p,version['workflow_id']);artifact=self._create_artifact(conn,project,dict(artifact_key='intelligent-plan:'+task['id'],artifact_type='intelligent-operation-plan',document=plan,object_ids=[workflow['episode_id']]))
            self._return_intelligent(conn,project,task,artifact);status='needs_input' if plan['questions'] else 'planned'
            conn.execute(update(S.intelligent_tasks).where(S.intelligent_tasks.c.project_id==p,S.intelligent_tasks.c.id==task['id']).values(status=status,plan_artifact_id=artifact['id']))
            return dict(id=task['id'],status=status,artifact_id=artifact['id'])
        return self._mutate(p,'finish_intelligent_task',payload,actor=actor,callback=work,**kw)

    def decide_intelligent_task(self,p,payload,actor,**kw):
        def work(conn,project):
            task=self._one(conn,S.intelligent_tasks,p,payload.get('task_id'));outcome=payload.get('outcome');reason=payload.get('reason','')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ResourceError('需要明确决定理由')
            prior=conn.execute(select(S.intelligent_decisions).where(S.intelligent_decisions.c.project_id==p,S.intelligent_decisions.c.task_id==task['id'])).mappings().first()
            if prior:
                if prior['outcome']!=outcome:raise Conflict('任务已有不同决定')
                return dict(id=task['id'],status=task['status'],output_version_id=task['output_version_id'])
            values={}
            if outcome=='stop' and task['status'] not in {'applied','rejected','stopped'}:
                if not task['plan_artifact_id']:self._return_intelligent(conn,project,task)
                values['status']='stopped'
            elif outcome=='reject' and task['status']=='planned':values['status']='rejected'
            elif outcome=='confirm' and task['status']=='planned':
                version=self._one(conn,S.intelligent_versions,p,task['version_id']);workflow,base=self._intelligent_version(conn,p,version['workflow_id'])
                if base['id']!=version['id']:raise Conflict('当前流程已变化，旧计划不覆盖新稿','intelligent_stale_plan')
                plan=validate_plan(payload.get('plan',task['host_result']),task['stage'])
                if plan['questions']:raise ResourceError('仍有补问，不能导入')
                state=self._intelligent_state(conn,p,base)
                if task['stage']=='assets':
                    mapping=payload.get('asset_mapping',{});links=[]
                    if not isinstance(mapping,dict):raise ResourceError('已有资产映射必须为对象')
                    for row in plan['assets']:
                        asset_id=mapping.get(row['key'])
                        if asset_id:
                            asset=self._one(conn,S.asset_identities,p,asset_id)
                            if asset['asset_kind']!=row['kind']:raise ResourceError('已有身份类型不符')
                        else:asset_id=self._create_object(conn,project,dict(kind='asset',asset_kind=row['kind'],display_code='AI-'+new_id()[:8],title=row['name']))['id']
                        specs=[dict(id=new_id(),asset_id=asset_id,variant_key=v,description=row['description']) for v in row['variants']]
                        self._create_artifact(conn,project,dict(artifact_key='intelligent-asset:'+task['id']+':'+row['key'],artifact_type='asset-bible',document={'asset_specs':specs},asset_specs=specs,object_ids=[asset_id]))
                        links.extend(dict(asset_key=row['key']+'_'+spec['variant_key'],asset_id=asset_id,spec_id=spec['id']) for spec in specs)
                    state['assets']=links
                else:
                    sequence_id=payload.get('sequence_id');mapping=payload.get('shot_mapping',{})
                    if not isinstance(mapping,dict):raise ResourceError('已有镜头映射必须为对象')
                    if sequence_id:
                        seq=self._one(conn,S.sequences,p,sequence_id);scene=self._one(conn,S.scenes,p,seq['parent_id'])
                        if scene['parent_id']!=workflow['episode_id']:raise ResourceError('导入目标不属于该集')
                    kind='blocking' if task['stage']=='blocking' else 'shot';retained=[u for u in state['units'] if u['kind']!=kind];added=[];deps=[]
                    for row in plan['units']:
                        unit=normalize_unit({k:v for k,v in row.items() if k!='parent_key'});shot=mapping.get(row['unit_key'])
                        if not shot:
                            if not sequence_id:raise ResourceError('请明确导入到原片段，或逐项映射已有镜头','intelligent_sequence_required')
                            ordinal=conn.execute(select(func.coalesce(func.max(S.shots.c.ordinal),-1)).where(S.shots.c.project_id==p,S.shots.c.parent_id==sequence_id)).scalar_one()+1
                            shot=self._create_object(conn,project,dict(kind='shot',display_code='AI-'+new_id()[:8],title=unit['title'],parent_id=sequence_id,ordinal=ordinal,duration_ms=unit['duration_ms']))['id']
                        unit['shot_id']=shot;added.append(unit)
                        if row['parent_key']:deps.append(dict(unit_key=unit['unit_key'],source_version_id='current',source_unit_key=row['parent_key'],purpose='anchor'))
                    keys={u['unit_key'] for u in retained}
                    state['units']=retained+added;state['dependencies']=[d for d in state['dependencies'] if d['unit_key'] in keys]+deps;state['media']=[m for m in state['media'] if m['unit_key'] in keys]
                    if added:self._create_artifact(conn,project,dict(artifact_key='intelligent-'+kind+':'+task['id'],artifact_type='shot-plan',document={'units':added},object_ids=list({u['shot_id'] for u in added})))
                result=self._insert_intelligent_version(conn,project,workflow,state,actor,base);values=dict(status='applied',output_version_id=result['version_id'])
            else:raise Conflict('当前任务状态不能接受这个决定')
            conn.execute(insert(S.intelligent_decisions).values(project_id=p,id=new_id(),task_id=task['id'],outcome=outcome,reason=reason,actor=actor))
            conn.execute(update(S.intelligent_tasks).where(S.intelligent_tasks.c.project_id==p,S.intelligent_tasks.c.id==task['id']).values(**values))
            return dict(id=task['id'],provider_submitted=False,**values)
        return self._mutate(p,'decide_intelligent_task',payload,actor=actor,callback=work,**kw)

    def prepare_intelligent_drafts(self,p,payload,actor,compile_drafts,**kw):
        def work(conn,project):
            workflow,version=self._intelligent_version(conn,p,payload.get('workflow_id'))
            if version['id']!=payload.get('version_id'):raise Conflict('单元已修改，请读取当前固定版本')
            documents=compile_drafts(p,payload);items=[]
            for row in documents:
                if row['gaps']:items.append(row);continue
                artifact=self._create_artifact(conn,project,dict(artifact_key='intelligent-classic:'+version['id']+':'+row['unit_key']+':'+payload['purpose'],artifact_type='classic-production-draft',document=row['document'],object_ids=[row['document']['shot_id']]))
                items.append(dict(unit_key=row['unit_key'],draft_artifact_id=artifact['id'],gaps=[]))
            return dict(items=items,version_id=version['id'],provider_submitted=False)
        return self._mutate(p,'prepare_intelligent_drafts',payload,actor=actor,callback=work,**kw)

    def propose_intelligent_runs(self,p,payload,actor,build_preview,**kw):
        def work(conn,project):
            preview=build_preview(p,payload['request'])
            if preview['sha256']!=payload.get('preview_sha256') or preview['revision']!=project['revision']:raise Conflict('批量报价或输入已改变')
            if not preview['ready']:raise ResourceError('本次选择仍有真实依赖缺口','intelligent_batch_not_ready')
            result=[]
            for item in preview['items']:
                artifact=self._create_artifact(conn,project,item['preview']['artifact'])
                conn.execute(insert(S.intelligent_runs).values(project_id=p,id=new_id(),version_id=payload['request']['version_id'],unit_key=item['unit_key'],purpose=payload['request']['purpose'],draft_artifact_id=item['draft_artifact_id'],run_artifact_id=artifact['id']))
                result.append(dict(unit_key=item['unit_key'],artifact_id=artifact['id']))
            return dict(items=result,needs_approval=True,provider_submitted=False)
        return self._mutate(p,'propose_intelligent_runs',payload,actor=actor,callback=work,**kw)

    def copy_intelligent_unit(self,p,payload,actor,**kw):
        def work(conn,project):
            workflow,base=self._intelligent_version(conn,p,payload.get('workflow_id'))
            if base['id']!=payload.get('base_version_id'):raise Conflict('复制前先核对当前版本')
            state=self._intelligent_state(conn,p,base);unit=next((u for u in state['units'] if u['unit_key']==payload.get('unit_key')),None)
            if not unit:raise ResourceError('复制单元不存在')
            copied=deepcopy(unit);copied['unit_key']='copy-'+new_id()[:8];copied['title']+=' · 副本';copied['skip_reason']=''
            if unit['shot_id']:
                original=self._one(conn,S.shots,p,unit['shot_id']);ordinal=conn.execute(select(func.coalesce(func.max(S.shots.c.ordinal),-1)).where(S.shots.c.project_id==p,S.shots.c.parent_id==original['parent_id'])).scalar_one()+1
                copied['shot_id']=self._create_object(conn,project,dict(kind='shot',display_code='COPY-'+new_id()[:8],title=copied['title'],parent_id=original['parent_id'],ordinal=ordinal,duration_ms=copied['duration_ms']))['id']
                self._create_artifact(conn,project,dict(artifact_key='intelligent-copy:'+copied['unit_key'],artifact_type='shot-plan',document={'units':[copied]},object_ids=[copied['shot_id']]))
            state['units'].insert(state['units'].index(unit)+1,copied)
            state['dependencies'].extend(dict(d,unit_key=copied['unit_key']) for d in list(state['dependencies']) if d['unit_key']==unit['unit_key'])
            return self._insert_intelligent_version(conn,project,workflow,state,actor,base)
        return self._mutate(p,'copy_intelligent_unit',payload,actor=actor,callback=work,**kw)

    def intelligent_asset_inputs(self,p,version_id):
        with self.engine.connect() as conn:
            self._one(conn,S.intelligent_versions,p,version_id);output=[]
            for row in conn.execute(select(S.intelligent_assets).where(S.intelligent_assets.c.project_id==p,S.intelligent_assets.c.version_id==version_id).order_by(S.intelligent_assets.c.ordinal)).mappings():
                identity=self._one(conn,S.asset_identities,p,row['asset_id']);spec=self._one(conn,S.asset_spec_versions,p,row['spec_id']);artifact=self._one(conn,S.artifact_versions,p,spec['artifact_id'])
                output.append(dict(row,asset_kind=identity['asset_kind'],specification=dict(spec,document=bytes(artifact['document']).decode('utf8'))))
            return clean(output)

    def propose_intelligent_missing_assets(self,p,payload,build_preview,**kw):
        def work(conn,project):
            preview=build_preview(p,payload.get('request',{}))
            if preview['revision']!=project['revision'] or preview['sha256']!=payload.get('preview_sha256'):raise Conflict('本批缺图或用量已变化，请重新核对')
            output=[]
            for row in preview['items']:
                if not row['ready']:
                    output.append({k:v for k,v in row.items() if k in {'asset_key','status','ready','gaps'}});continue
                artifact=self._create_artifact(conn,project,row['artifact'])
                conn.execute(insert(S.intelligent_asset_runs).values(project_id=p,version_id=preview['version_id'],asset_key=row['asset_key'],run_artifact_id=artifact['id']))
                output.append(dict(asset_key=row['asset_key'],artifact_id=artifact['id'],needs_approval=True))
            return dict(items=output,version_id=preview['version_id'],provider_submitted=False)
        return self._mutate(p,'propose_intelligent_missing_assets',payload,callback=work,**kw)
