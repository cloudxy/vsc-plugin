"""Transactional typed projections from immutable creative relation versions.

Document is sole authoring input. Projection IDs are deterministic per version;
external object/version references are checked and version dependencies pinned.
No registration implies approval, adoption or proven method capability.
"""
import json
import uuid
from sqlalchemy import insert, select
from vsc.assets.resource_service import ResourceError, required
from . import schema as S
from .values import checked_id

FORMAT = 'vsc.creative-relations/v1'


def project_relations(store, conn, project_id, artifact_id, document, dependency_ids):
    if not isinstance(document, dict) or document.get('format') != FORMAT:
        return
    if document.get('project_id') != project_id:
        raise ResourceError('创作关系文档项目不一致', 'document_project_mismatch')
    p, deps, local = project_id, set(dependency_ids), {}
    artifact = store._one(conn,S.artifact_versions,p,artifact_id)
    if artifact['artifact_type'] != 'creative-relations':
        raise ResourceError('创作关系格式必须登记为creative-relations类型', 'creative_artifact_type')
    declared = set(conn.execute(select(S.artifact_object_scopes.c.object_id).where(S.artifact_object_scopes.c.project_id==p,S.artifact_object_scopes.c.artifact_id==artifact_id)).scalars())
    allowed = set()
    if not artifact['project_wide']:
        for sid in declared:
            allowed.update(store._descendant_ids(conn,p,sid))
            allowed.add(sid)
    def scoped(identifier):
        if not artifact['project_wide'] and identifier not in allowed:
            raise ResourceError('关系实例超出文档登记范围', 'creative_scope_mismatch')
    if document.keys() - {'format','project_id','instances','interactions','dispositions','performances','cues','notes'}:
        raise ResourceError('创作关系文档存在未识别字段', 'creative_relation_fields')

    def identifier(group, key):
        return str(uuid.uuid5(uuid.UUID(artifact_id), group + ':' + str(key)))

    def add(table, values, key=None):
        row = dict(values, project_id=p, id=identifier(table.name, key or str(len(local))))
        conn.execute(insert(table).values(**row))
        local[row['id']] = (table.name, row)
        return row['id']

    def ref(table, value, *, optional=False):
        if value is None and optional:
            return None
        value = checked_id(value)
        row = store._one(conn, table, p, value)
        owner = row.get('artifact_id') or row.get('script_version_id') or row.get('scope_version_id')
        if table is S.timeline_items:
            owner = store._one(conn,S.timeline_versions,p,row['timeline_id'])['artifact_id']
        if table is S.artifact_versions:
            owner = value
        if owner and owner != artifact_id and owner not in deps:
            raise ResourceError('关系引用必须声明固定版本依赖: ' + owner, 'creative_dependency_missing')
        return value

    def params(value):
        value = value or {}
        if not isinstance(value, dict):
            raise ResourceError('状态/执行参数必须是对象')
        def check(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key.endswith(('_id','_ids','_ref','_refs')):
                        raise ResourceError('对象引用须用有类型关系字段，不放入参数: ' + key, 'creative_untyped_reference')
                    check(item)
            elif isinstance(node, list):
                for item in node:
                    check(item)
        check(value)
        return value

    def shot_scene(shot_id):
        shot = store._one(conn, S.shots, p, shot_id)
        return store._one(conn, S.sequences, p, shot['parent_id'])['parent_id']

    def rows(key):
        values = document.get(key, [])
        if not isinstance(values, list) or len(values) > 10000:
            raise ResourceError('关系集合必须为最多10000行的列表')
        fields={
            'instances':{'key','label','asset_id','spec_version_id','state_id','scene_id','shot_id','state'},
            'interactions':{'subject','object','relation','hand','parameters'},
            'dispositions':{'line_id','disposition','reason'},
            'performances':{'key','label','domain','method_artifact_id','line_id','voice_spec_id','parameters','shot_ids','participants','materials','slots'},
            'cues':{'key','label','kind','scope_object_id','line_id','voice_spec_id','execution','subtitle_version_id','lipsync_version_id','parameters','shots','slot_ids','timeline_item_ids'}}
        for value in values:
            if not isinstance(value,dict) or value.keys()-fields[key]:
                raise ResourceError('关系行存在未识别字段: '+key,'creative_relation_fields')
            if 'key' in value and (not isinstance(value['key'],str) or not value['key'].strip()):
                raise ResourceError('关系key必须是非空文本','creative_relation_fields')
        return values

    instances, executions, cues = {}, {}, {}
    for item in rows('instances'):
        key = required(item, 'key')
        scene = ref(S.scenes, required(item,'scene_id'))
        shot = ref(S.shots, item.get('shot_id'), optional=True)
        state = ref(S.state_versions, item.get('state_id'), optional=True)
        scoped(shot or scene)
        if shot and shot_scene(shot) != scene:
            raise ResourceError('使用实例的场与镜头归属不一致', 'creative_scope_mismatch')
        if state:
            row = store._one(conn, S.state_versions, p, state)
            if row['scene_id'] != scene or (row['shot_id'] and row['shot_id'] != shot):
                raise ResourceError('使用实例引用了其他场镜状态', 'creative_scope_mismatch')
        instances[key] = add(S.asset_use_instances, dict(artifact_id=artifact_id,
            instance_key=key,label=item.get('label',key),scene_id=scene,shot_id=shot,
            asset_id=ref(S.asset_identities,required(item,'asset_id')),
            spec_version_id=ref(S.asset_spec_versions,item.get('spec_version_id'),optional=True),
            state_id=state,state=params(item.get('state'))),key)
    def instance(value):
        return ref(S.asset_use_instances, instances.get(value,value))
    for n,item in enumerate(rows('interactions')):
        subject, obj = instance(required(item,'subject')), instance(required(item,'object'))
        a,b = (store._one(conn,S.asset_use_instances,p,x) for x in (subject,obj))
        if a['scene_id'] != b['scene_id'] or (a['shot_id'] and b['shot_id'] and a['shot_id'] != b['shot_id']):
            raise ResourceError('交互双方必须位于同场且兼容镜头范围', 'creative_scope_mismatch')
        add(S.instance_interactions,dict(artifact_id=artifact_id,subject_id=subject,object_id=obj,
            relation=required(item,'relation'),hand=item.get('hand'),parameters=params(item.get('parameters'))),str(n))
    for item in rows('dispositions'):
        line = ref(S.script_lines,required(item,'line_id'))
        scoped(store._one(conn,S.script_lines,p,line)['scene_id'])
        add(S.script_line_dispositions,dict(artifact_id=artifact_id,line_id=line,
            disposition=required(item,'disposition'),reason=required(item,'reason')),line)
    for item in rows('performances'):
        key = required(item,'key')
        domain = required(item,'domain')
        if domain in {'combat','dance','vfx','voice'}:
            from vsc.production.performance import execution_problems
            errors = execution_problems(domain,item.get('parameters'))
            method = ref(S.artifact_versions,required(item,'method_artifact_id'))
            fixed_method = store._one(conn,S.artifact_versions,p,method)
            try:
                method_doc=json.loads(fixed_method['document'])
            except (ValueError,UnicodeDecodeError):
                method_doc={}
            legacy_method=fixed_method['artifact_type']=='trial-method' and isinstance(method_doc.get('method'),str) and method_doc['method'].strip()
            from vsc.knowledge.learning import validate_method_package
            from vsc.kernel.catalog import role_cards
            structured_method=False
            if method_doc.get('format')=='vsc.capability-method/v1':
                try:
                    validate_method_package(method_doc,role_cards())
                    structured_method=True
                except ValueError as error:
                    errors.append(str(error))
            if not (legacy_method or structured_method):
                errors.append('方法须为明确trial-method正文或vsc.capability-method/v1结构，任意已批准文档不能代替方法')
            if not store._artifact_approved(conn,p,method):
                errors.append('专业执行方法必须固定已批准版本')
            roles = {x.get('role') for x in item.get('participants',[])}
            materials = {x.get('role') for x in item.get('materials',[])}
            if domain=='combat':
                if len(item.get('participants',[]))<2:errors.append('交互动作须明确至少两个参与实例')
                for phase in item.get('parameters',{}).get('phases',[]):
                    if phase.get('actor_role') not in roles or phase.get('counterpart_role') not in roles:errors.append('动作双方须引用已登记参与者role')
            if domain=='dance' and 'music' not in materials:errors.append('舞蹈须固定music素材关系')
            if domain=='vfx' and not {'caster','target'}<=roles:errors.append('特效须明确caster/target实例')
            if domain=='vfx':
                for layer in item.get('parameters',{}).get('layers',[]):
                    for role in ('plate','mask','depth'):
                        if layer.get('requires_'+role) and role not in materials:errors.append('特效缺少固定'+role+'素材')
            if domain=='voice' and not (item.get('line_id') and item.get('voice_spec_id')):errors.append('声音表演须固定台词与声线规格')
            if errors:raise ResourceError('; '.join(errors),'professional_execution_invalid')
        ex = add(S.execution_instances,dict(artifact_id=artifact_id,execution_key=key,label=item.get('label',key),
            domain=required(item,'domain'),method_artifact_id=ref(S.artifact_versions,item.get('method_artifact_id'),optional=True),
            line_id=ref(S.script_lines,item.get('line_id'),optional=True),
            voice_spec_id=ref(S.voice_spec_versions,item.get('voice_spec_id'),optional=True),parameters=params(item.get('parameters'))),key)
        executions[key] = ex
        if not item.get('shot_ids'):
            raise ResourceError('执行实例须明确至少一个镜头', 'creative_scope_missing')
        for shot in item['shot_ids']:
            scoped(shot)
            add(S.execution_shots,dict(execution_id=ex,shot_id=ref(S.shots,shot)),ex+shot)
        for participant in item.get('participants',[]):
            iid = instance(required(participant,'instance'))
            use = store._one(conn,S.asset_use_instances,p,iid)
            if use['shot_id'] and use['shot_id'] not in item['shot_ids']:
                raise ResourceError('参与实例不属于执行镜头范围','creative_scope_mismatch')
            if not any(shot_scene(sid)==use['scene_id'] for sid in item['shot_ids']):
                raise ResourceError('参与实例不属于执行场次','creative_scope_mismatch')
            add(S.execution_participants,dict(execution_id=ex,instance_id=iid,role=required(participant,'role')),ex+iid+participant['role'])
        for field,table,target,idfield in [('materials',S.execution_materials,S.media_items,'media_id'),('slots',S.execution_slots,S.binding_slots,'slot_id')]:
            for use in item.get(field,[]):
                rid=ref(target,required(use,idfield))
                if target is S.binding_slots:
                    slot_target=store._one(conn,S.binding_slots,p,rid)['target_object_id']
                    if not set(item['shot_ids']) & store._descendant_ids(conn,p,slot_target):
                        raise ResourceError('执行用途不属于执行镜头范围','creative_scope_mismatch')
                add(table,dict(execution_id=ex,**{idfield:rid},role=required(use,'role')),ex+rid+use['role'])
    for item in rows('cues'):
        key = required(item,'key')
        cue_scope=ref(S.creative_objects,required(item,'scope_object_id'))
        scoped(cue_scope)
        if store._one(conn,S.creative_objects,p,cue_scope)['kind']=='asset':
            raise ResourceError('声音Cue范围必须为结构对象','creative_scope_mismatch')
        cue_scope_ids=store._descendant_ids(conn,p,cue_scope)
        cue = add(S.sound_cues,dict(artifact_id=artifact_id,cue_key=key,label=item.get('label',key),
            cue_kind=required(item,'kind'),scope_object_id=ref(S.creative_objects,required(item,'scope_object_id')),
            line_id=ref(S.script_lines,item.get('line_id'),optional=True),
            voice_spec_id=ref(S.voice_spec_versions,item.get('voice_spec_id'),optional=True),
            execution_id=ref(S.execution_instances,executions.get(item.get('execution'),item.get('execution')),optional=True),
            subtitle_version_id=ref(S.artifact_versions,item.get('subtitle_version_id'),optional=True),
            lipsync_version_id=ref(S.artifact_versions,item.get('lipsync_version_id'),optional=True),
            parameters=params(item.get('parameters'))),key)
        cues[key]=cue
        for cover in item.get('shots',[]):
            sid=ref(S.shots,required(cover,'shot_id'))
            scoped(sid)
            if item['scope_object_id'] != sid and sid not in store._descendant_ids(conn,p,item['scope_object_id']):
                raise ResourceError('声音Cue覆盖镜头超出Cue范围','creative_scope_mismatch')
            add(S.cue_shots,dict(cue_id=cue,shot_id=sid,start_ms=cover.get('start_ms'),end_ms=cover.get('end_ms')),cue+sid)
        for field,table,target,idfield in [('slot_ids',S.cue_slots,S.binding_slots,'slot_id'),('timeline_item_ids',S.cue_timeline_items,S.timeline_items,'item_id')]:
            for value in item.get(field,[]):
                rid=ref(target,value)
                use=store._one(conn,target,p,rid)
                if target is S.binding_slots and use['target_object_id'] not in cue_scope_ids:
                    raise ResourceError('Cue用途超出声音范围','creative_scope_mismatch')
                if target is S.timeline_items:
                    if use['shot_id'] and use['shot_id'] not in cue_scope_ids:
                        raise ResourceError('Cue时间线用料超出声音范围','creative_scope_mismatch')
                    timeline=store._one(conn,S.timeline_versions,p,use['timeline_id'])
                    if cue_scope not in store._descendant_ids(conn,p,timeline['episode_id']):
                        raise ResourceError('Cue时间线分集范围不相容','creative_scope_mismatch')
                add(table,dict(cue_id=cue,**{idfield:rid}),cue+rid)
