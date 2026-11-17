// Read the same preferences as Settings. This projection never contains a key.
import {getState} from './character-studio-store.js';

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
