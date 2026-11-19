// Read the same preferences as Settings. This projection never contains a key.
import {PROVIDER_META,PROVIDER_ORDER,VIDEO_PROVIDER_META,VIDEO_PROVIDER_ORDER,isAuthProvider,isVideoAuthProvider} from './character-studio-ai.js';
import {getState,subscribe} from './character-studio-store.js';

export function canvasSettingsModels(){
  const config=getState().apiConfig,providers=[];
  const imageIds=[config.activeProvider,'agy_auth','grok_auth','codex_auth'];
  for(const provider of [...new Set(imageIds)].filter(id=>['agy_auth','grok_auth','codex_auth'].includes(id))){
    const value=config.providers[provider];
    providers.push({provider,model:value.model==='custom'?value.customModel:value.model});
  }
  const video=config.videoProviders.grok_video_auth;
  providers.push({provider:'grok_video_auth',model:video.model==='custom'?video.customModel:video.model});
  return providers;
}

export function subscribeCanvasApiSettings(listener){
  return subscribe(()=>listener());
}

export function canvasApiSettingsSignature(){
  const {apiConfig,authStatus}=getState();
  const img=PROVIDER_ORDER.map(id=>{
    const p=apiConfig.providers?.[id]||{};
    return [id,p.model,p.customModel,Boolean(p.apiKey?.trim())];
  });
  const vid=VIDEO_PROVIDER_ORDER.map(id=>{
    const p=apiConfig.videoProviders?.[id]||{};
    return [id,p.model,p.customModel,Boolean(p.apiKey?.trim())];
  });
  const auth=Object.entries(authStatus||{}).map(([k,v])=>[k,Boolean(v?.ready),v?.status||'']);
  return JSON.stringify([apiConfig.activeProvider,apiConfig.activeVideoProvider,img,vid,auth]);
}

export function buildCanvasModelDropdownList({modality='image',operation=null,runOptions=null}={}){
  const models=Array.isArray(runOptions?.models)?runOptions.models:[];
  const modelParams=runOptions?.model_params||{};
  const {apiConfig,authStatus}=getState();
  const entries=[];
  const byServerId=new Map();

  for(const m of models){
    if(!m||m.enabled===false||m.modality!==modality)continue;
    const spec=modelParams[m.id]||modelParams[m.model_key]||{};
    const supportedByOp=!operation||!Array.isArray(operation.supported_models)||operation.supported_models.includes(m.id)||m.adapter_available===false;
    const adapterOk=m.adapter_available!==false;
    const opMatch=!operation||!Array.isArray(operation.supported_models)||operation.supported_models.includes(m.id);
    const disabled=!adapterOk||!opMatch;
    const disabledReason=!adapterOk
      ?'服务端适配器或本机凭证未就绪，请检查 API 接口配置或本机密钥环境变量'
      :(!opMatch?`当前「${operation.name||operation.op_type}」操作不支持该模型`:'');
    const providerId=String(m.tool_id||'').startsWith('api-settings-')
      ?String(m.tool_id).slice('api-settings-'.length)
      :(m.supplier||'local');
    const item={
      id:m.id,
      modelKey:m.model_key||m.id,
      showName:spec.show_name||m.name||m.model_key||m.id,
      providerId,
      channelLabel:m.name&&spec.show_name&&m.name!==spec.show_name?m.name:'',
      disabled,
      disabledReason,
      browserOnly:false,
      isActiveSetting:false,
      supportedByOp,
      spec,
      raw:m,
    };
    entries.push(item);
    byServerId.set(m.id,item);
  }

  if(modality==='image'||modality==='video'){
    const isVideo=modality==='video';
    const activePid=isVideo?apiConfig.activeVideoProvider:apiConfig.activeProvider;
    const order=isVideo?[activePid,...VIDEO_PROVIDER_ORDER]:[activePid,...PROVIDER_ORDER];
    const metaMap=isVideo?VIDEO_PROVIDER_META:PROVIDER_META;
    const cfgMap=isVideo?(apiConfig.videoProviders||{}):(apiConfig.providers||{});
    const isAuth=isVideo?isVideoAuthProvider:isAuthProvider;

    for(const pid of [...new Set(order)]){
      const meta=metaMap[pid];
      if(!meta)continue;
      const pc=cfgMap[pid]||{};
      const modelKey=String(pc.model==='custom'?pc.customModel:pc.model||'').trim();
      const isActive=pid===activePid;

      if(isAuth(pid)){
        const synced=entries.find(e=>e.raw?.tool_id==='api-settings-'+pid&&(
          !modelKey||e.modelKey===modelKey
        ));
        if(synced){
          if(isActive)synced.isActiveSetting=true;
          continue;
        }
        const authInfo=authStatus?.[meta.authVendor]||{};
        if(isActive||authInfo.status==='unauthenticated'||authInfo.status==='missing_cli'){
          const spec=modelParams[modelKey]||{};
          const labelBase=spec.show_name||modelKey||meta.shortName;
          entries.push({
            id:`unready-auth:${pid}:${modelKey||'default'}`,
            modelKey:modelKey||pid,
            showName:labelBase.includes(meta.shortName)?labelBase:`${meta.shortName} · ${labelBase}`,
            providerId:pid,
            channelLabel:'未授权',
            disabled:true,
            disabledReason:authInfo.message||`本机 ${meta.shortName} 尚未登录授权，请前往「API 接口配置」完成登录`,
            browserOnly:false,
            isActiveSetting:isActive,
            spec,
            raw:null,
          });
        }
        continue;
      }

      const hasKey=Boolean(pc.apiKey?.trim());
      if(!hasKey&&!isActive)continue;
      const serverEquivalent=modelKey
        ?entries.find(e=>!e.disabled&&e.modelKey===modelKey&&!String(e.raw?.tool_id||'').startsWith('api-settings-'))
        :null;
      if(serverEquivalent&&hasKey){
        if(isActive)serverEquivalent.isActiveSetting=true;
        continue;
      }
      const spec=modelParams[modelKey]||{};
      const baseLabel=spec.show_name||modelKey||meta.shortName;
      const reason=!modelKey
        ?'请在「API 接口配置」填写自定义模型 ID'
        :(!hasKey
          ?`当前在「API 接口配置」选中了 ${meta.name}，尚未填写 API Key`
          :'该模型仅在浏览器本地保存了 API Key，画布服务端任务队列不读取浏览器密钥；请在服务端资源配置接入同源模型，或切换本机订阅授权');
      entries.push({
        id:`browser-api:${pid}:${modelKey||'unset'}`,
        modelKey:modelKey||pid,
        showName:`${baseLabel} · ${meta.shortName}`,
        providerId:pid,
        channelLabel:hasKey?'浏览器 Key · 服务端不可用':'未配 Key',
        disabled:true,
        disabledReason:reason,
        browserOnly:true,
        isActiveSetting:isActive,
        spec,
        raw:null,
      });
    }
  }

  entries.sort((a,b)=>{
    if(a.disabled!==b.disabled)return a.disabled?1:-1;
    if(a.isActiveSetting!==b.isActiveSetting)return a.isActiveSetting?-1:1;
    return 0;
  });
  return entries;
}
