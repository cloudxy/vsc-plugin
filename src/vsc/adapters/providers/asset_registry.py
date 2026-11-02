"""Explicit asset-registration adapter; no URL or successful image implies registration."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from vsc.configuration import get_config
from vsc.assets.resource_service import ResourceError
from vsc.assets.script_ai import _run_bounded,host_environment


class CommandAssetRegistry:
    def __init__(self,settings=None,runner=None):
        self.settings=settings if settings is not None else get_config('VSC_ASSET_REGISTRY',{})
        self.runner=runner or _run_bounded
        self.provider=self.settings.get('provider','');self.account_scope=self.settings.get('account_scope','')
    def available(self):
        command=self.settings.get('command',[])
        return bool(self.provider and self.account_scope and isinstance(command,list) and command and all(isinstance(x,str) for x in command) and shutil.which(command[0]))
    def register(self,request,path):
        if not self.available():raise ResourceError('未配置该供应商的资产注册能力','asset_registry_unavailable')
        with tempfile.TemporaryDirectory(prefix='vsc-provider-asset-') as directory:
            root=Path(directory);image=root/('reference'+path.suffix);shutil.copyfile(path,image)
            if hashlib.sha256(image.read_bytes()).hexdigest()!=request['media_sha256']:raise ResourceError('资产图片摘要变化','asset_registry_media_changed')
            manifest=root/'request.json';response=root/'response.json'
            manifest.write_text(json.dumps({**request,'format':'vsc.provider-asset-request/v1','media_file':str(image)},ensure_ascii=False))
            try:result=self.runner([*self.settings['command'],'--operation','register','--request',str(manifest),'--response',str(response)],cwd=directory,env=host_environment(),timeout=180,capture_output=True,text=True,check=False)
            except subprocess.TimeoutExpired as exc:raise ResourceError('注册回执未知，不会重发原请求','asset_registry_unknown') from exc
            except OSError as exc:raise ResourceError('注册适配器无法启动','asset_registry_failed') from exc
            if result.returncode:raise ResourceError('供应商资产注册明确失败','asset_registry_failed')
            if not response.is_file() or response.stat().st_size>1_000_000:raise ResourceError('注册回执缺失或超限','asset_registry_unknown')
            try:return json.loads(response.read_text())
            except ValueError as exc:raise ResourceError('注册回执格式未知','asset_registry_unknown') from exc


def validated_receipt(value,request):
    if not isinstance(value,dict) or set(value)!={'provider','account_scope','request_id','remote_asset_id','media_sha256','evidence'}:
        raise ResourceError('缺少供应商资产注册的完整回执','asset_registry_unknown')
    for key in ('provider','account_scope','request_id','media_sha256'):
        if value[key]!=request[key]:raise ResourceError('供应商注册回执与原请求不一致','asset_registry_unknown')
    remote=value['remote_asset_id']
    if not isinstance(remote,str) or not 1<=len(remote)<=512 or '://' in remote or not isinstance(value['evidence'],dict) or not value['evidence']:
        raise ResourceError('供应商资产身份必须来自注册回执，不能用图片URL代替','asset_registry_unknown')
    return value
