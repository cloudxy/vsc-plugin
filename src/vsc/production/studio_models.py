"""Project existing API-settings subscription choices into the production registry.

Only public model preferences cross this seam. Login state remains owned by the
existing local CLI adapters; browser API keys are never copied into the registry.
"""
from vsc.assets.resource_service import ResourceError

AUTH_MODELS = {
    'agy_auth': ('google', 'agy', 'AGY 授权', 'image-generator'),
    'codex_auth': ('openai', 'codex', 'Codex 订阅', 'image-generation'),
    'grok_auth': ('xai', 'grok', 'Grok 授权', 'image_edit'),
    'grok_video_auth': ('xai', 'grok', 'Grok 视频订阅', 'grok-imagine-video'),
}


def auth_configuration(provider, model=None):
    if provider not in AUTH_MODELS:
        raise ResourceError('未知的本机订阅通道', 'invalid_studio_model')
    supplier, _, label, default = AUTH_MODELS[provider]
    model = model or default
    if not isinstance(model,str) or not 1 <= len(model) <= 120 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in model):
        raise ResourceError('订阅模型名称无效', 'invalid_studio_model')
    if provider == 'codex_auth' and model != default:
        raise ResourceError('Codex 使用已有内置生图模型', 'invalid_studio_model')
    if provider == 'grok_video_auth' or provider == 'grok_auth' and model.startswith('grok-imagine-image-'):
        video = provider == 'grok_video_auth'
        from vsc.adapters.providers.xai_grok.spec import advanced_model,lite_model,REFERENCE_LIMIT
        ratios={'1080x1920':'9:16','1920x1080':'16:9','1080x1080':'1:1','1440x1080':'4:3',
                '1080x1440':'3:4','1620x1080':'3:2','1080x1620':'2:3','2160x1080':'2:1','2520x1080':'21:9'}
        return dict(name=label+' · '+model,supplier='xai',product='grok-imagine',plan='subscription',
            region='global',execution='api',modality='video' if video else 'image',model_key=model,model_version='settings-v1',
            base_url='https://api.x.ai/v1',auth_ref='',enabled=True,tool_id='api-settings-'+provider,
            capabilities=dict(purposes=['text_to_video','image_to_video','reference_to_video'] if video else ['first_frame','identity_ref','image_edit'],
                reference_media=True,first_frame=video,last_frame=video and advanced_model(model) and not lite_model(model),max_reference_images=REFERENCE_LIMIT if video else 5,
                **({'min_duration_ms':1000,'max_duration_ms':15000 if advanced_model(model) else 10000} if video else {})),
            default_params=dict(resolution='720p',ratio='9:16',generate_audio=True) if video else dict(resolution='2k',ratio_map=ratios))
    return dict(name=label+' · '+model,supplier=supplier,product='studio-auth',plan='subscription',
        region='local',execution='host_tool',modality='image',model_key=model,model_version='settings-v1',
        base_url='',auth_ref='',enabled=True,tool_id='api-settings-'+provider,
        capabilities=dict(purposes=['first_frame','identity_ref','image_edit'],reference_media=True,max_reference_images=5 if provider=='grok_auth' else 8),default_params={})


def is_studio_auth_configuration(value):
    provider = str(value.get('tool_id') or '').removeprefix('api-settings-')
    if provider not in AUTH_MODELS or provider == 'grok_video_auth':
        return False
    try:
        expected = auth_configuration(provider,value.get('model_key'))
    except ResourceError:
        return False
    fields = ('supplier','product','plan','region','execution','modality','model_key','base_url','auth_ref','capabilities','default_params')
    return expected['product']=='studio-auth' and all(value.get(key)==expected[key] for key in fields)


def sync_settings_models(service, providers, actor):
    if not isinstance(providers,list) or len(providers)>4:
        raise ResourceError('请选择现有设置中的订阅通道','invalid_studio_model')
    status = getattr(service,'studio_auth_status',lambda:{})()
    from vsc.production.resource_settings import ResourceSettings, validate_configuration
    settings = ResourceSettings(service.store)
    models=[];seen=set()
    for item in providers:
        if not isinstance(item,dict) or set(item)!={'provider','model'} or not isinstance(item['provider'],str) or item['provider'] not in AUTH_MODELS or item['provider'] in seen:
            raise ResourceError('同步仅接受公开通道与模型名称，不接受凭证','invalid_studio_model')
        seen.add(item['provider'])
        vendor=AUTH_MODELS[item['provider']][1]
        if not status.get(vendor,{}).get('ready'):
            continue
        payload=validate_configuration(auth_configuration(item['provider'],item['model']))
        models.append(settings._repository().ensure_settings_model(payload,actor))
    return dict(models=models)
