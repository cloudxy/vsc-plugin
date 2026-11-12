"""Typed canvas plans compile original bounded runs; this module owns no queue."""
from copy import deepcopy
import json
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.production.quotes import fingerprint
from vsc.production.run_authorization import normalize_request,validate_capabilities
from vsc.production.run_policy import policy_errors


def route_models(configurations, model_ids, logical, context):
    """Capability routing before any submit; the order and every rejection stay visible."""
    if not isinstance(model_ids,list) or not 1<=len(model_ids)<=8 or len(set(model_ids))!=len(model_ids):
        raise ResourceError('模型顺序须为 1–8 个不同的固定模型')
    available=[];candidates=[]
    for ordinal,mid in enumerate(model_ids):
        model=configurations.get(mid);code=message=None
        if not model:code,message='model_unavailable','固定模型配置已不可用'
        elif not model['enabled']:code,message='model_disabled','模型已停用'
        elif not model.get('adapter_available'):code,message='model_adapter_unavailable','尚无实际适配器'
        elif model['modality']!=logical['modality']:code,message='model_modality_mismatch','模型媒体类型不符'
        elif logical['purpose'] not in model['capabilities'].get('purposes',[]):code,message='model_purpose_mismatch','模型不支持当前用途 '+logical['purpose']
        else:
            try:
                validate_capabilities(model,logical,context)
                image_count=len(logical['reference_media_ids'])+bool(logical.get('first_frame_media_id'))+bool(logical.get('last_frame_media_id'))
                if image_count>model['capabilities'].get('max_reference_images',image_count):
                    raise ResourceError('固定图片参考数量超过模型能力','model_capability_mismatch')
            except ResourceError as error:code,message=error.code,str(error)
        row=dict(model_id=mid,ordinal=ordinal,name=model.get('name') or model.get('model_key') or mid if model else mid,
                 applicable=code is None,code=code,message=message or '适用于当前固定输入')
        if model:row['configuration_sha256']=fingerprint({k:model.get(k) for k in ('id','provider_id','model_version','modality','enabled','adapter_available','capabilities','default_params')})
        candidates.append(row)
        if code is None:available.append(mid)
    return dict(original_model_ids=list(model_ids),model_ids=available,selected_model_id=available[0] if available else None,candidates=candidates)


def draft_logical(document, *, source_media=None):
    """Use the same typed reference roles as the working-generation compiler."""
    from vsc.assets.classic_production import MODES
    mode_def=MODES[document['mode']]
    modality=mode_def['modality'];refs=document['references'];tool=mode_def.get('image_tool')
    by_role={role:[r['media_id'] for r in refs if r['role']==role] for role in mode_def['slots']}
    raw=dict(prompt=document['prompt'],params=document['params'],reference_media_ids=by_role.get('reference_image',[]))
    if modality=='image':
        raw.update(width=document['width'],height=document['height'])
        if tool in {'inpaint','watermark'}:
            src_ref=next((r for r in refs if r['role']=='operation_source'),None)
            mask_ref=next((r for r in refs if r['role']=='operation_mask'),None)
            if src_ref and mask_ref:
                raw.update(source_media_id=src_ref['media_id'],source_sha256=src_ref['sha256'],mask_media_id=mask_ref['media_id'],mask_sha256=mask_ref['sha256'],operation='inpaint')
        elif tool in {'panorama','upscale'} and source_media is not None:
            from vsc.production.fal_tools import image_operation_fields
            raw.update(image_operation_fields(tool,source_media,document.get('tool_settings',{})))
    elif modality=='video':raw.update(duration_ms=document['duration_ms'],first_frame_media_id=next(iter(by_role.get('first_frame',[])),None),last_frame_media_id=next(iter(by_role.get('last_frame',[])),None),reference_video_media_ids=by_role.get('reference_video',[]),reference_audio_media_ids=by_role.get('reference_audio',[]))
    return normalize_request(raw,document['shot_id'],document['purpose'],modality)


def preview_request(service,p,*,target,purpose,modality,prompt,model_ids,logical,execution_policy,billing=None,key='canvas',source=None,working_draft=None):
    """One reusable compiler for canvas targets and current-episode asset gaps."""
    from vsc.production.resource_settings import ResourceSettings
    errors=policy_errors(execution_policy)
    if not execution_policy or errors:raise ResourceError('；'.join(errors) or '需要固定运行次数与期限')
    if not isinstance(model_ids,list) or not 1<=len(model_ids)<=8 or len(set(model_ids))!=len(model_ids):raise ResourceError('模型顺序须为 1–8 个不同的固定模型')
    configurations={m['id']:m for m in ResourceSettings(service.store).list()['configurations']}
    shot=target.get('shot_id');asset=target.get('asset_id')
    if bool(shot)==bool(asset):raise ResourceError('请选择唯一原镜头或资产目标')
    if working_draft:
        from vsc.adapters.persistence.postgres.workbench_generation import working_context
        with service.store.engine.connect() as conn:context=working_context(service.store,conn,service.store._project(conn,p),working_draft['id'],shot_id=shot,purpose=purpose)
        if context['working_draft']!=working_draft:raise Conflict('原工作输入摘要已变化')
    else:context=service.compile_asset_context(p,asset,purpose,spec_version_id=target.get('spec_version_id')) if asset else service.compile_shot_context(p,shot,purpose)
    if context.get('gaps'):return dict(ready=False,gaps=context['gaps'],revision=context['revision'])
    raw=dict(logical,prompt=prompt)
    if asset and target.get('spec_version_id'):raw['spec_version_id']=target['spec_version_id']
    request=normalize_request(raw,shot,purpose,modality,asset_id=asset)
    routing=route_models(configurations,model_ids,request,context)
    if not routing['model_ids']:return dict(ready=False,gaps=[dict(code='canvas_no_applicable_model',message='已选模型均不适用；输入与顺序保留')],routing=routing,revision=context['revision'])
    for media in context.get('media',[]):service._verify_media(p,media['media_id'],media['sha256'])
    request['context_sha256']=context['sha256']
    history=[];offset=0
    while True:
        page=service.list_generation_jobs(p,offset=offset,limit=200);history+=page['items'];offset+=len(page['items'])
        if offset>=page['total'] or not page['items']:break
    candidate=max([j['candidate_no'] for j in history if j.get('shot_id')==shot and j.get('asset_id')==asset and j['purpose']==purpose]+[-1])+1
    pins=[dict(id=a['id'],sha256=a['sha256']) for a in context['artifacts']]
    run=dict(format='vsc.production-run/v1',project_id=p,phase='asset' if asset else 'production',approved_inputs=pins,execution_policy=execution_policy,
             series_batch=dict(jobs=[dict(task_key=key,model_id=routing['selected_model_id'],candidate_no=candidate,request=request)]),canvas_model_routing=routing)
    if working_draft:run['workbench_draft']=working_draft
    if source:run['canvas_source']=source
    quote=service.preview_generation_quote(p,dict(document=run));run['generation_quote']=quote['generation_quote']
    run['operations']={r['operation']:r['native_units'] for r in quote['generation_quote']['jobs']}
    from vsc.production.commerce_quote import attach_commerce_quote
    commerce=attach_commerce_quote(service,p,run,quote,billing or {})
    if quote['revision']!=context['revision']:raise Conflict('输入在报价期间变化')
    artifact=dict(artifact_key=key,artifact_type='workbench-generation-run' if working_draft else 'production-run',stage='workspace' if working_draft else 'production',document=run,dependency_ids=[x['id'] for x in pins],object_ids=[shot or asset])
    return dict(ready=True,gaps=[],revision=quote['revision'],artifact=artifact,preview_sha256=fingerprint(artifact),generation_quote=quote['generation_quote'],commerce_quote=commerce,needs_approval=not working_draft,routing=routing)


def preview_canvas(service,p,payload):
    allowed={'canvas_id','canvas_revision','node_id','shot_id','asset_id','spec_version_id','model_id','model_ids','purpose','duration_ms','width','height','execution_policy','commerce_account_actor','script_line_ids','voice_media_id'}
    if not isinstance(payload,dict) or set(payload)-allowed:raise ResourceError('画布运行输入字段不正确')
    canvas=service.get_creative_canvas(p,payload.get('canvas_id'))
    if canvas['canvas_revision']!=payload.get('canvas_revision'):raise Conflict('先保存并核对当前画布版本','canvas_revision_conflict')
    nodes={n['id']:n for n in canvas['document']['nodes']};node=nodes.get(payload.get('node_id'))
    if not node or node['type']=='text':raise ResourceError('文本节点只作为输入；请选择图像、音频或视频节点')
    tree=service.get_project_tree(p);objects={x['id']:x for x in tree['nodes']};shot=objects.get(payload.get('shot_id'))
    if payload.get('shot_id'):
        if not shot or shot['kind']!='shot':raise ResourceError('请选择原镜头')
        ancestor=shot
        while ancestor and ancestor['kind']!='episode':ancestor=objects.get(ancestor.get('parent_id'))
        if not ancestor or canvas['episode_id'] and canvas['episode_id']!=ancestor['id']:raise ResourceError('镜头不属于当前画布集','canvas_job_scope')
    prompt=[];logical={'params':node['params']};waiting=[]
    if node['type']=='image':logical.update(width=payload.get('width',1080),height=payload.get('height',1920))
    if node['type']=='video':logical['duration_ms']=payload.get('duration_ms',5000)
    if node['type']=='audio':logical.update(script_line_ids=payload.get('script_line_ids',[]),voice_media_id=payload.get('voice_media_id'))
    for edge in canvas['document']['edges']:
        if edge['target']!=node['id']:continue
        parent=nodes[edge['source']];port=edge['port']
        if port=='prompt':prompt.append(parent['text']);continue
        media_id=parent['media_id']
        if not media_id:
            waiting.append(dict(code='canvas_dependency_waiting',message='依赖节点须有实际媒体并在原目标采用',node_id=parent['id']));continue
        media=service.get_media(p,media_id)
        if media['modality']!=parent['type']:raise ResourceError('节点实际媒体模态不符')
        field={'first_frame':'first_frame_media_id','last_frame':'last_frame_media_id','reference_audio':'reference_audio_media_ids','reference_video':'reference_video_media_ids'}.get(port,'reference_media_ids')
        if node['type']=='audio' and port=='reference_audio':
            if logical.get('voice_media_id')!=media_id:raise ResourceError('音频参考仅接原已配置音色；须明确同一 voice_media_id','canvas_audio_reference_adapter_missing')
        elif field.endswith('_ids'):logical.setdefault(field,[]).append(media_id)
        else:logical[field]=media_id
    if node['text'].strip():prompt.append(node['text'])
    if waiting:return dict(ready=False,gaps=waiting,revision=canvas['revision'],canvas_version_id=canvas['version_id'],node_id=node['id'])
    purpose=payload.get('purpose') or {'image':'identity_ref' if payload.get('asset_id') else 'first_frame','video':'video_clip','audio':'sfx'}[node['type']]
    models=payload.get('model_ids') or [payload.get('model_id')]
    result=preview_request(service,p,target=payload,purpose=purpose,modality=node['type'],prompt='\n'.join(prompt),model_ids=models,logical=logical,execution_policy=payload.get('execution_policy'),billing={k:payload[k] for k in ['commerce_account_actor'] if k in payload},key='canvas-run:'+canvas['version_id']+':'+node['id'])
    result.update(canvas_version_id=canvas['version_id'],node_id=node['id'],model_ids=result.get('routing',{}).get('model_ids',models),target={k:payload.get(k) for k in ('shot_id','asset_id','spec_version_id')})
    if result['ready']:result['preview_sha256']=fingerprint({k:result[k] for k in ('artifact','canvas_version_id','node_id','model_ids','target')})
    return result


def advance_runs(service,p,run_ids,actor):
    """Explicit bounded tick; original jobs are the only durable execution state."""
    from vsc.production.bounded import execute_batch
    service.authorize_access(p,'execute')
    output=[]
    for rid in dict.fromkeys(run_ids):
        artifact=service.get_artifact_version(p,rid)
        if not artifact.get('approved'):
            output.append(dict(run_version_id=rid,status='needs_approval',tasks=[]));continue
        output.append(dict(status='advanced',**execute_batch(service,p,dict(run_version_id=rid),actor)))
    return dict(runs=output,revision=service.get_project(p)['revision'],provider_submitted=False)
