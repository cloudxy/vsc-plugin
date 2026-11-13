"""Local, integrity-checked display media; original case pins remain unchanged."""
from functools import lru_cache
import hashlib
from importlib import resources
import json
from pathlib import Path
import re

from vsc.assets.resource_service import ResourceError


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def load_manifest():
    try:
        manifest = json.loads(resources.files('vsc.assets').joinpath('marketing-assets.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ResourceError('本地营销资源目录无效', 'marketing_assets_integrity', 409) from error
    if not isinstance(manifest, dict) or manifest.get('schema') != 'vsc.marketing-local-assets/v1' or not isinstance(manifest.get('assets'), dict):
        raise ResourceError('本地营销资源目录无效', 'marketing_assets_integrity', 409)
    for key, item in manifest['assets'].items():
        if (not isinstance(item, dict) or key != item.get('id')
                or not re.fullmatch(r'(?:cases/[A-Za-z0-9_-]+/(?:cover|video)|methods/[a-z0-9-]+)', key)
                or not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
                or not isinstance(item.get('object_key'), str)
                or not re.fullmatch(re.escape(item['sha256']) + r'\.(?:mp4|jpg|webp|png)', item.get('object_key', ''))
                or type(item.get('size_bytes')) is not int or item['size_bytes'] < 1
                or item.get('mime_type') not in {'video/mp4', 'image/jpeg', 'image/webp', 'image/png'}
                or not isinstance(item.get('source_url'), str) or not item['source_url'].startswith('https://static.skyproduction.cn/')):
            raise ResourceError('本地营销资源目录无效', 'marketing_assets_integrity', 409)
    return manifest


def assets_root(media_root):
    return Path(media_root).expanduser().resolve() / 'marketing-studio'


@lru_cache(maxsize=512)
def _verified(path, expected, size, mtime, ctime, inode):
    return file_sha256(path) == expected


def local_asset(media_root, asset_id):
    item = load_manifest()['assets'].get(asset_id)
    if item is None:
        raise ResourceError('营销资源不存在', 'marketing_asset_not_found', 404)
    root = assets_root(media_root).resolve()
    path = root / item['object_key']
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        raise ResourceError('营销资源尚未完整保存到本地', 'marketing_asset_missing', 404)
    stat = path.stat()
    if stat.st_size != item['size_bytes'] or not _verified(str(path), item['sha256'], stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino):
        raise ResourceError('本地营销资源校验失败', 'marketing_asset_integrity', 409)
    return path, item, stat
