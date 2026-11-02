"""Mureka lyrics-to-song adapter; original ResourceWorker owns submission/recovery.

Protocol: https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html
One job explicitly requests one song, avoiding the API's default of two.
"""
from __future__ import annotations
import json
import os
from urllib.parse import quote, urlsplit
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus

BASE = 'https://api.mureka.ai'
KEY_ENV = 'MUREKA_API_KEY'
MODELS = frozenset({'mureka-7.6','mureka-o2','mureka-8','mureka-9','mureka-9.5'})


class MurekaSongProvider:
    def __init__(self, model, provider_id, client=None, read_key=None):
        self.model, self.provider_id, self.client = model, provider_id, client
        self.read_key = read_key or (lambda: os.environ.get(KEY_ENV,''))

    def _key(self):
        value=self.read_key()
        if not isinstance(value,str) or not value:
            raise ResourceError('未加载 MUREKA_API_KEY；请检查 ~/.zshenv，在启动进程的 zsh 中 source ~/.zshenv 后重启，其他启动方式需显式传入环境','credential_not_loaded')
        return value

    def preflight(self, request=None):
        if self.model not in MODELS:
            raise ResourceError('请选择已登记的 Mureka 歌曲模型', 'invalid_model_defaults')
        self._key()
        if request is not None:
            if request.purpose != 'song' or not isinstance(request.lyrics, str) or not 1 <= len(request.lyrics.strip()) <= 5000:
                raise ResourceError('歌曲需要固定的 1–5000 字符歌词', 'song_lyrics_required')
            if not isinstance(request.prompt,str) or not request.prompt.strip() or len(request.prompt) > 1024 or request.params or request.reference_media_ids or request.voice_media_id or request.script_line_ids:
                raise ResourceError('歌曲风格最多1024字符，不接受未实现的音色、参考或参数', 'song_inputs_unsupported')

    def _request(self, method, path, payload=None):
        import httpx
        self.preflight()
        key=self._key()
        client = self.client or httpx.Client(timeout=60, follow_redirects=False)
        try:
            response = client.request(method, BASE + path,
                headers={'Authorization':'Bearer '+key}, **({'json':payload} if payload is not None else {}))
            if response.status_code in {401,403}:
                raise ResourceError('Mureka 凭据或歌曲服务权限被拒绝；请核对 MUREKA_API_KEY 及该账户权限','mureka_authentication_failed')
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):raise ValueError('invalid response')
            return json.loads(json.dumps(value,ensure_ascii=False).replace(key,'[REDACTED]'))
        finally:
            if self.client is None:client.close()

    def submit(self, request):
        self.preflight(request)
        raw = self._request('POST', '/v1/song/generate',
            {'model':self.model,'lyrics':request.lyrics,'prompt':request.prompt,'n':1})
        identifier = raw.get('id')
        if not isinstance(identifier,str) or not identifier.strip() or len(identifier)>200 or raw.get('model',self.model)!=self.model:
            raise ResourceError('歌曲提交回执缺少任务标识；保留原请求，不重发', 'song_receipt_unknown')
        return JobHandle(self.provider_id, self.model, identifier, raw)

    def poll(self, handle):
        if handle.provider != self.provider_id or handle.model != self.model or not handle.external_task_id:
            raise ResourceError('歌曲回执不属于此模型配置', 'provider_handle_mismatch')
        raw = self._request('GET', '/v1/song/query/'+quote(handle.external_task_id, safe=''))
        if raw.get('id') != handle.external_task_id or raw.get('model',self.model)!=self.model:
            raise ResourceError('歌曲查询返回其他任务，保留原任务继续核对', 'song_receipt_unknown')
        state = raw.get('status')
        if state in {'preparing','queued','running','streaming'}:return JobStatus('running',raw=raw)
        if state == 'succeeded':return JobStatus('succeeded',raw=raw)
        if state in {'failed','timeouted','cancelled'}:
            return JobStatus('failed', error_code='mureka_'+state, raw=raw)
        raise ResourceError('无法识别歌曲原任务状态，保留原请求继续查询', 'song_receipt_unknown')

    def parse_result(self, raw):
        choices = raw.get('choices')
        if raw.get('status') != 'succeeded' or not isinstance(choices, list) or len(choices) != 1:
            raise ResourceError('单次歌曲任务必须返回一份已完成音频', 'song_output_invalid')
        choice = choices[0]
        # Song.url is the regular audio, wav_url the documented lossless WAV.
        # Never finalize stream_url: it is only an in-progress preview.
        url = (choice.get('wav_url') or choice.get('url')) if isinstance(choice, dict) else None
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ResourceError('歌曲结果缺少可验证的 HTTPS 音频地址', 'song_output_invalid')
        return [GeneratedAsset('audio',temporary_uri=url,
            metadata={k:choice[k] for k in ('id','duration','lyrics_sections') if k in choice})]


def mureka_factory(job, storage, *, client=None, read_key=None):
    provider = job['provider']; config = provider.get('configuration',{})
    if (config.get('supplier'),config.get('product'),config.get('plan'),config.get('execution')) != ('mureka','music','api','api') or provider['base_url'].rstrip('/') != BASE or provider['auth_ref'] != KEY_ENV or job['modality']!='audio' or job['purpose']!='song' or job['model'].get('default_params'):
        raise ResourceError('Mureka 必须使用官方端点和独立凭据引用', 'invalid_provider_config')
    return MurekaSongProvider(job['model']['model_key'], job['provider_id'],client=client,read_key=read_key)
