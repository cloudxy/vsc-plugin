"""Portable working edits with original bytes; never a delivery approval."""
import hashlib
import json
import zipfile
from pathlib import Path

from vsc.post.edit_workspace import validate_edit


def subtitles(document):
    validate_edit(document)
    def stamp(frame):
        milliseconds = round(frame * 1000 / document['fps'])
        seconds, ms = divmod(milliseconds, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'
    return '\n\n'.join(f"{index}\n{stamp(row['start_frame'])} --> {stamp(row['end_frame'])}\n{row['text']}"
        for index, row in enumerate(document.get('captions', []), 1)) + '\n'


def write_archive(fixed, paths, destination):
    """Include each fixed media identity once; no paths or secrets from config."""
    document = fixed['document']
    validate_edit(document)
    inputs = {}
    for row in fixed['inputs']:
        path = Path(paths[row['clip_key']])
        suffix = path.suffix if path.suffix.lower() in {'.mp4','.mov','.webm','.png','.jpg','.jpeg','.webp','.wav','.mp3','.m4a','.ogg'} else '.bin'
        name = 'media/' + row['media_id'] + suffix
        inputs[row['clip_key']] = {'path':name, 'media_id':row['media_id'], 'sha256':row['blob_sha256'],
            'modality':row['modality'], 'track':row['track']}
    manifest = {'format':'vsc.edit-workspace-package/v1', 'project_id':fixed['project_id'],
        'episode_id':fixed['episode_id'], 'edit_version_id':fixed['id'], 'edit_sha256':fixed['sha256'],
        'adoption':'unapproved-working-edit', 'inputs':inputs,'export_policy':fixed.get('export_policy',{})}
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
        for name,value in [('edit-workspace.json',document),('manifest.json',manifest)]:
            archive.writestr(name,json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
        archive.writestr('subtitles.srt',subtitles(document))
        archive.writestr('render.py', "from pathlib import Path\nfrom vsc.post.edit_workspace_export import render_package\nprint(render_package(Path(__file__).resolve().parent))\n")
        archive.writestr('README.txt','VSC 可恢复剪辑工作稿\n'
            '此包包含固定剪辑 JSON、实时时码字幕和所用源媒体，不代表正式交付批准。\n'
            'manifest.json 将片段编号映射到包内媒体路径与 SHA256。源片段入出帧、音轨位置和字幕均以 edit-workspace.json 的 fps 为准。\n'
            '在安装了相同版本 VSC、FFmpeg 与 ffprobe 的环境中，运行 python render.py 可核验素材并重渲染到 rendered/。此操作不调用生成供应商。\n'
            '恢复到原项目时，保存 edit-workspace.json 为新的剪辑版本；迁移项目需先登记媒体并明确映射媒体身份。\n')
        written = set()
        for key,row in inputs.items():
            if row['path'] in written:
                continue
            source = Path(paths[key])
            digest = hashlib.sha256()
            with source.open('rb') as stream, archive.open(row['path'], 'w', force_zip64=True) as target:
                for chunk in iter(lambda:stream.read(1024*1024), b''):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != row['sha256']:
                raise ValueError('工程导出的固定素材摘要已改变')
            written.add(row['path'])
    return manifest


def write_clip_archive(fixed, paths, selected, destination):
    """Export each selected clip with its own trim and original sound settings."""
    import tempfile
    from vsc.post.edit_workspace import FirstCutRenderer
    document = fixed['document']
    by_key = {row['clip_key']: row for row in fixed['inputs']}
    manifest = {'format': 'vsc.selected-clips/v1', 'edit_version_id': fixed['id'],
                'edit_sha256': fixed['sha256'], 'clips': []}
    with tempfile.TemporaryDirectory(prefix='vsc-selected-clips-') as directory:
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for index, clip in enumerate(document['clips'], 1):
                if clip['id'] not in selected:
                    continue
                target = Path(directory) / str(index)
                target.mkdir()
                single = {**document, 'clips': [clip], 'audio': [], 'captions': []}
                row = by_key[clip['id']]
                output, receipt = FirstCutRenderer().render(single,
                    {clip['id']: {'path': paths[clip['id']], 'modality': row['modality']}}, target)
                from vsc.post.export_entitlements import watermark
                output,policy_receipt=watermark(output,target/'marked.mp4',fixed.get('export_policy',{}))
                if policy_receipt:receipt['export_policy']=policy_receipt
                filename = f'clip-{index:03d}.mp4'
                archive.write(output, filename)
                manifest['clips'].append({'file': filename, 'clip_id': clip['id'],
                    'source_media_id': clip['media_id'], 'source_sha256': row['blob_sha256'],
                    'in_frame': clip['in_frame'], 'out_frame': clip['out_frame'],
                    'fps': document['fps'], 'receipt': receipt})
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def render_package(directory):
    """Restore this package's exact fixed recipe, rejecting escaped or changed media."""
    from vsc.post.edit_workspace import FirstCutRenderer
    root = Path(directory).resolve()
    manifest = json.loads((root / 'manifest.json').read_text('utf-8'))
    document = json.loads((root / 'edit-workspace.json').read_text('utf-8'))
    validate_edit(document)
    fingerprint = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if manifest.get('format') != 'vsc.edit-workspace-package/v1' or fingerprint != manifest.get('edit_sha256'):
        raise ValueError('工程文档与固定版本摘要不一致')
    expected = {row['id']:row['media_id'] for track in ('clips','audio') for row in document.get(track,[])}
    members = manifest.get('inputs')
    if not isinstance(members,dict) or set(members) != set(expected):
        raise ValueError('工程媒体清单与时间线不一致')
    inputs = {}
    for key,row in members.items():
        if not isinstance(row,dict) or row.get('media_id') != expected[key] or row.get('modality') not in {'image','audio','video'}:
            raise ValueError('工程媒体身份或类型无效')
        name = row.get('path')
        if not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('工程媒体须为包内相对路径')
        path = (root/name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('工程媒体不能越过包目录')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest() != row.get('sha256'):
            raise ValueError('工程媒体字节与固定摘要不一致')
        inputs[key] = {'path':str(path), 'modality':row['modality']}
    target = root/'rendered'
    target.mkdir(exist_ok=False)
    output,receipt = FirstCutRenderer().render(document,inputs,target)
    from vsc.post.export_entitlements import watermark
    output,policy_receipt=watermark(output,target/'marked.mp4',manifest.get('export_policy',{}))
    if policy_receipt:receipt['export_policy']=policy_receipt
    (target/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    return output
