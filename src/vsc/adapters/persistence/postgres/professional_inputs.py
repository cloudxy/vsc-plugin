"""Professional working sources use existing immutable artifacts and typed links."""
import json
from sqlalchemy import select,insert
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.production.professional_inputs import KIND_TYPES,normalize_professional_inputs,normalize_source_workflow,script_texts
from vsc.production.quotes import fingerprint
from . import schema as S
from .values import clean


def _mapped_id(value,kind,id_map):
    """Use the original project projection map; labels are typed, never guessed."""
    return id_map.get(kind,{}).get(value) if isinstance(value,str) else None


def _source_gap(message,code='professional_input_incomplete'):
    raise ResourceError('专业依据缺项：'+message,code)


def _shot_in_scope(value,kind,target,id_map,label):
    identifier=_mapped_id(value,'shot',id_map)
    actual=id_map.get('shot_scopes',{}).get(identifier,{})
    if not identifier or actual.get(kind+'_id')!=target:
        _source_gap(label+' 的镜头不属于登记'+kind+'范围','professional_input_scope')
    return identifier


def _professional_fragments(document,kind,scope,id_map):
    """Read the canonical body without promoting a working source to approval."""
    if not isinstance(document,dict):_source_gap(kind+' 需要结构化正文')
    expected={'episode':scope['episode_id'],'scene':scope['scene_id'],
        'sequence':scope['sequence_id'],'shot':scope['id']}
    for object_kind,target in expected.items():
        field=object_kind+'_id'
        if field in document and _mapped_id(document[field],object_kind,id_map)!=target:
            _source_gap(kind+' 的 '+field+' 不属于本镜范围','professional_input_scope')
    fmt=document.get('format')
    fragments=[]
    if kind=='scene_state':
        from vsc.story.consistency import STATE_FORMAT,derive,state_errors
        if fmt!=STATE_FORMAT:_source_gap('不支持的 scene_state 正文格式')
        try:errors=state_errors(document)
        except (KeyError,TypeError,AttributeError,ValueError):errors=['场景状态结构不完整']
        if errors:_source_gap('scene_state：'+'；'.join(errors))
        matches=[(si,scene,hi,shot) for si,scene in enumerate(document['scenes'])
            for hi,shot in enumerate(scene['shots'])
            if _mapped_id(shot['id'],'shot',id_map)==scope['id']]
        if len(matches)!=1:_source_gap('scene_state 未提供唯一的本镜状态')
        si,scene,hi,shot=matches[0]
        if _mapped_id(scene['id'],'scene',id_map)!=scope['scene_id']:
            _source_gap('scene_state 的本镜不属于登记场次','professional_input_scope')
        for preceding in scene['shots'][:hi+1]:
            _shot_in_scope(preceding['id'],'scene',scope['scene_id'],id_map,'scene_state')
        # Same cumulative baseline + earlier changes as production.context.
        state=derive({'scenes':[scene]})[shot['id']]
        fragments.append(('scenes['+str(si)+'].shots['+str(hi)+']',state))
    elif kind=='sequence_links':
        from vsc.story.sequence import FORMAT,sequence_errors
        if fmt!=FORMAT:_source_gap('不支持的 sequence_links 正文格式')
        try:errors=sequence_errors(document)
        except (KeyError,TypeError,AttributeError,ValueError):errors=['衔接结构不完整']
        if errors:_source_gap('sequence_links：'+'；'.join(errors))
        units={unit['id']:unit for unit in document['units']}
        for unit in units.values():
            target=_mapped_id(unit['id'],unit['kind'],id_map)
            if not target:_source_gap('sequence_links 的单元未按类型登记','professional_input_scope')
            for field in ('entry_shot','exit_shot'):
                _shot_in_scope(unit[field],unit['kind'],target,id_map,'sequence_links')
        for index,link in enumerate(document['links']):
            boundaries=[]
            for side,field,moment in (('from','exit_shot','exit'),('to','entry_shot','entry')):
                unit=units[link[side]]
                if _mapped_id(unit[field],'shot',id_map)!=scope['id']:continue
                if _mapped_id(unit['id'],unit['kind'],id_map)!=expected[unit['kind']]:
                    _source_gap('sequence_links 的边界镜不属于登记单元','professional_input_scope')
                boundaries.append(moment)
            if boundaries:
                fragments.append(('links['+str(index)+']',{'from_unit':units[link['from']],
                    'to_unit':units[link['to']],'link':link,'shot_boundaries':boundaries}))
    elif kind in {'shot_plan','continuity'}:
        if fmt not in (None,'vsc.continuity-plan/v1','vsc.shot-plan/v1'):
            _source_gap('不支持的 '+kind+' 正文格式')
        shots=document.get('shots')
        if not isinstance(shots,list) or any(not isinstance(shot,dict) for shot in shots):
            _source_gap(kind+' 需要 shots 正文')
        matches=[(index,shot) for index,shot in enumerate(shots)
            if _mapped_id(shot.get('shot_id',shot.get('id')),'shot',id_map)==scope['id']]
        if len(matches)!=1:_source_gap(kind+' 未提供唯一的本镜正文')
        from vsc.project.plan_scope import plan_applies
        keys={object_kind:{key for key,identifier in id_map.get(object_kind,{}).items() if identifier==target}
            for object_kind,target in expected.items()}
        if not plan_applies({'document':document},keys):
            _source_gap(kind+' 的计划归属不覆盖本镜','professional_input_scope')
        index,shot=matches[0]
        if not any(value not in (None,'',[],{}) for key,value in shot.items() if key not in {'id','shot_id'}):
            _source_gap(kind+' 只有本镜标识，缺少专业正文')
        for state in ('entry_state','exit_state'):
            scene=shot.get(state,{}).get('scene_id') if isinstance(shot.get(state,{}),dict) else None
            if scene is not None and _mapped_id(scene,'scene',id_map)!=scope['scene_id']:
                _source_gap(kind+' 的本镜状态不属于登记场次','professional_input_scope')
        if index and shots[index-1].get('bridge_to_next'):
            previous=shots[index-1]
            _shot_in_scope(previous.get('shot_id',previous.get('id')),'sequence',scope['sequence_id'],id_map,kind)
            fragments.append(('shots['+str(index-1)+'].bridge_to_next',{
                'from_shot':previous.get('shot_id',previous.get('id')),
                'to_shot':shot.get('shot_id',shot.get('id')),'bridge':previous['bridge_to_next']}))
        fragments.append(('shots['+str(index)+']',shot))
    else:_source_gap('不支持的专业正文类型 '+kind)
    if not fragments:_source_gap(kind+' 未提供适用于本镜的状态或衔接正文')
    return fragments


def _document(row):
    raw=bytes(row['document']).decode('utf8')
    try:return json.loads(raw)
    except ValueError:return raw


def _shot_scope_select(p):
    shot,seq,scene,ep=S.shots,S.sequences,S.scenes,S.episodes
    return (select(shot.c.id,seq.c.id.label('sequence_id'),scene.c.id.label('scene_id'),ep.c.id.label('episode_id'),ep.c.parent_id.label('work_id'))
        .join(seq,(seq.c.project_id==shot.c.project_id)&(seq.c.id==shot.c.parent_id))
        .join(scene,(scene.c.project_id==seq.c.project_id)&(scene.c.id==seq.c.parent_id))
        .join(ep,(ep.c.project_id==scene.c.project_id)&(ep.c.id==scene.c.parent_id))
        .where(shot.c.project_id==p))


def shot_scope(conn,p,shot_id):
    row=conn.execute(_shot_scope_select(p).where(S.shots.c.id==shot_id)).mappings().one_or_none()
    if row is None:raise ResourceError('专业依据的镜头范围不存在','professional_input_scope')
    return dict(row)


def _professional_id_map(store,conn,p):
    result=store._projection_id_map(conn,p)
    result['shot_scopes']={row['id']:dict(row) for row in conn.execute(_shot_scope_select(p)).mappings()}
    return result


def resolve_professional_inputs(store,conn,project,draft_doc):
    p=project['id'];refs=normalize_professional_inputs(draft_doc.get('professional_inputs',[]))
    workflow=normalize_source_workflow(draft_doc['source_workflow']) if draft_doc.get('source_workflow') else None
    if not refs and not workflow:return {'pins':[],'dependency_ids':[],'conditions':{},'semantic_inputs':[],'context':{}}
    scope=shot_scope(conn,p,draft_doc['shot_id']);ancestors=set(scope.values());pins=[];dependencies=[];semantics=[];texts=[];rules={};conditions={};id_map=None
    for ref in refs:
        row=store._one(conn,S.artifact_versions,p,ref['id'])
        if row['sha256']!=ref['sha256'] or row['artifact_type'] not in KIND_TYPES[ref['kind']]:
            raise Conflict('专业依据类型或固定摘要不符','professional_input_changed')
        scopes=set(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
            S.artifact_object_scopes.c.project_id==p,S.artifact_object_scopes.c.artifact_id==row['id'])).scalars())
        if not row['project_wide'] and not scopes.intersection(ancestors):
            raise ResourceError('专业依据不属于本镜或本集','professional_input_scope')
        document=_document(row);pins.append(ref);dependencies.append(row['id'])
        if ref['kind']=='screenplay':texts.extend(script_texts(document))
        if ref['kind']=='creative_rules' and isinstance(document,dict):
            declared=document.get('creative_rules',document.get('rules',{}))
            if isinstance(declared,dict):rules.update(declared)
        if ref['kind'] in {'shot_plan','scene_state','sequence_links','continuity'}:
            if id_map is None:id_map=_professional_id_map(store,conn,p)
            for path,item in _professional_fragments(document,ref['kind'],scope,id_map):
                semantics.append(dict(id=row['id'],sha256=row['sha256'],kind=ref['kind'],path=path,text=json.dumps(item,ensure_ascii=False,sort_keys=True)))
    if workflow:
        version=store._one(conn,S.intelligent_versions,p,workflow['version_id'])
        origin=store._one(conn,S.artifact_versions,p,workflow['artifact_id'])
        if version['artifact_id']!=origin['id'] or origin['artifact_type'] not in KIND_TYPES['workflow'] or origin['sha256']!=workflow['artifact_sha256']:
            raise Conflict('分集专业规划来源已变化','professional_workflow_changed')
        parent=store._one(conn,S.intelligent_workflows,p,version['workflow_id'])
        if parent['episode_id']!=scope['episode_id']:
            raise ResourceError('专业规划不属于本集','professional_input_scope')
        state=store._intelligent_state(conn,p,version)
        if fingerprint(state)!=workflow['state_sha256']:
            raise Conflict('分集专业规划固定状态摘要不符','professional_workflow_changed')
        unit=next((u for u in state['units'] if u['unit_key']==workflow['unit_key']),None)
        if not unit or unit['shot_id']!=draft_doc['shot_id']:
            raise ResourceError('专业规划单元不属于本镜','professional_input_scope')
        declared=unit.get('professional',{})
        conditions={'unit_key':unit['unit_key'],**declared}
        labels={'narrative_purpose':'本镜叙事任务','entry_state':'入点状态','exit_state':'出点状态','bridge':'与邻镜的衔接','sound_route':'声音路线'}
        for key,label in labels.items():
            value=declared.get(key)
            if isinstance(value,str) and value and value!='unknown':
                semantics.append(dict(id=origin['id'],sha256=origin['sha256'],kind='workflow',path='unit_conditions.'+unit['unit_key']+'.'+key,text=label+'：'+value))
        pins.append(dict(id=origin['id'],sha256=origin['sha256'],kind='workflow'))
        dependencies.append(origin['id'])
    context={'professional_inputs':pins,'professional_conditions':conditions,'semantic_inputs':semantics,
        'professional_script_texts':texts,'professional_creative_rules':rules,
        'professional_review':{'status':'not_reviewed','missing':[k for k in ('narrative_purpose','entry_state','exit_state','bridge','sound_route') if not conditions.get(k) or conditions.get(k)=='unknown']}}
    if workflow:context['source_workflow']=workflow
    return clean(dict(pins=pins,dependency_ids=list(dict.fromkeys(dependencies)),conditions=conditions,semantic_inputs=semantics,context=context))


def project_source_workflow(store,conn,project,artifact,document):
    """Persist the source relation with the same draft/media transaction."""
    if not document.get('source_workflow'):return
    fixed=normalize_source_workflow(document['source_workflow'])
    resolve_professional_inputs(store,conn,project,document)
    prior=conn.execute(select(S.classic_draft_workflows).where(S.classic_draft_workflows.c.project_id==project['id'],S.classic_draft_workflows.c.draft_version_id==artifact['id'])).mappings().one_or_none()
    if prior:
        if any(prior[k]!=v for k,v in fixed.items()):raise Conflict('既有专业来源投影不可覆盖','professional_input_changed')
        return
    conn.execute(insert(S.classic_draft_workflows).values(project_id=project['id'],draft_version_id=artifact['id'],**fixed))


def validate_saved_sources(conn,p,draft_id,document,resolved):
    if not resolved['pins']:return
    declared=set(resolved['dependency_ids'])
    actual=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
        S.artifact_dependencies.c.project_id==p,S.artifact_dependencies.c.artifact_id==draft_id)).scalars())
    if not declared<=actual:raise ResourceError('专业草稿来源关系未完整固定','professional_input_incomplete')
    if document.get('source_workflow'):
        row=conn.execute(select(S.classic_draft_workflows).where(S.classic_draft_workflows.c.project_id==p,S.classic_draft_workflows.c.draft_version_id==draft_id)).mappings().one_or_none()
        expected=normalize_source_workflow(document['source_workflow'])
        if not row or any(row[k]!=v for k,v in expected.items()):
            raise ResourceError('分集专业来源投影与原稿不一致','professional_input_incomplete')


def prompt_with_conditions(prompt,context):
    values=[r['text'] for r in context.get('semantic_inputs',[]) if r.get('text')]
    return prompt if not values else prompt+'\n\n【本镜固定专业条件】\n'+'\n'.join(values)
