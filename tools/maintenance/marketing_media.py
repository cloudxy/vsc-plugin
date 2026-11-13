"""Explicitly restore or verify the fixed marketing display assets on disk."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from vsc.assets.marketing_media import assets_root, file_sha256, load_manifest, local_asset
from vsc.assets.resource_service import ResourceError
from vsc.configuration import get_config


def restore(media_root, item):
    root = assets_root(media_root)
    root.mkdir(parents=True, exist_ok=True)
    if not shutil.which('curl'):
        raise ValueError('恢复本地营销资源需要 curl')
    with tempfile.TemporaryDirectory(prefix='.marketing-download-', dir=root) as directory:
        downloaded = Path(directory) / 'download'
        result = subprocess.run(['curl', '--fail', '--location', '--proto', '=https', '--silent', '--show-error',
            '--retry', '2', '--connect-timeout', '20', '--max-time', '240', '--header', 'Accept-Encoding: identity',
            '--output', str(downloaded), '--write-out', '%{http_code}', item['source_url']],
            capture_output=True, text=True)
        if result.returncode or result.stdout != '200':
            raise ValueError(item['id'] + ' 下载失败；现有本地文件保留')
        if item.get('embedded_data_uri_sha256'):
            if file_sha256(downloaded) != item['source_document_sha256']:
                raise ValueError(item['id'] + ' 来源脚本已改变')
            uri = next((uri for uri in re.findall(r'data:image/webp;base64,[A-Za-z0-9+/=]+', downloaded.read_text())
                if hashlib.sha256(uri.encode()).hexdigest() == item['embedded_data_uri_sha256']), None)
            if not uri:
                raise ValueError(item['id'] + ' 内嵌封面不存在')
            downloaded.write_bytes(base64.b64decode(uri.split(',', 1)[1], validate=True))
        if downloaded.stat().st_size != item['size_bytes'] or file_sha256(downloaded) != item['sha256']:
            raise ValueError(item['id'] + ' 原始字节摘要不符；现有本地文件保留')
        downloaded.replace(root / item['object_key'])


def main(argv=None):
    parser = argparse.ArgumentParser(description='营销工作室资源本地校验；仅 --sync 显式联网恢复')
    parser.add_argument('--media-root', default=None, help='默认沿用 config/.env 中的 VSC_MEDIA_ROOT')
    parser.add_argument('--sync', action='store_true', help='下载缺失或损坏的固定原文件，不更新来源版本')
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args(argv)
    media_root = args.media_root or get_config('VSC_MEDIA_ROOT')
    items = load_manifest()['assets']

    def check(pair):
        key, item = pair
        try:
            local_asset(media_root, key)
        except ResourceError:
            if not args.sync:
                raise
            restore(media_root, item)
            local_asset(media_root, key)
        return key

    failed, verified = {}, 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(check, pair): pair[0] for pair in items.items()}
        for job in as_completed(jobs):
            try:
                job.result()
                verified += 1
            except (ResourceError, OSError, ValueError) as error:
                failed[jobs[job]] = str(error)
    print(json.dumps(dict(expected=len(items), verified=verified, failed=failed), ensure_ascii=False))
    return 1 if failed else 0
