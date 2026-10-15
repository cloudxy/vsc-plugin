#!/usr/bin/env python3
"""Small structured story contracts; narrative quality is reviewed by people."""
import argparse
import json
from pathlib import Path


def validation_errors(data):
    errors = []
    def text(value, label):
        if (not isinstance(value, str) or not value.strip() or value in ('TODO','x','内容','待填写')
                or value.startswith(('请填写','请说明','请替换'))):
            errors.append(label+' 必须写明内容')
    fmt = data.get('format')
    if fmt == 'vsc.source-map/v1':
        text(data.get('summary'), 'summary')
        if not isinstance(data.get('source_units'), list) or not data['source_units']: errors.append('source_units 不能为空')
        for unit in data.get('source_units', []):
            for key in ('id','source_id','source_sha256','fact_or_claim','narrative_function','claim_kind'): text(unit.get(key), key)
            if not isinstance(unit.get('locator'), dict): errors.append('locator 必须可解析')
    elif fmt == 'vsc.episode-beats/v1':
        if not isinstance(data.get('episodes'), list) or not data['episodes']: errors.append('episodes 不能为空')
        identifiers = set()
        for episode in data.get('episodes', []):
            text(episode.get('id'), 'episode.id')
            if episode.get('id') in identifiers: errors.append('episode id 重复')
            identifiers.add(episode.get('id'))
            if episode.get('ending_function') not in ('closure','resonance','action','cliffhanger'): errors.append('ending_function 无效')
            text(episode.get('ending'), 'ending')
            if not isinstance(episode.get('beats'), list) or not episode['beats']: errors.append('beats 不能为空')
            for beat in episode.get('beats', []):
                for key in ('id','action','change'): text(beat.get(key), 'beat.'+key)
                if not isinstance(beat.get('screen_unit_ids'), list) or not beat['screen_unit_ids']: errors.append('节拍需对应screen_unit_ids')
    elif fmt == 'vsc.visual-bible/v1':
        for key in ('intent','lighting','composition'): text(data.get(key), key)
        if not isinstance(data.get('palette'), list) or not data['palette']: errors.append('palette 不能为空')
        else:
            for color in data['palette']: text(color, 'palette item')
    else: errors.append('未知 story format')
    return errors


def project_errors(data, project, state, item):
    if data['format'] == 'vsc.source-map/v1':
        from vsc.assets.sources import provenance_errors
        return provenance_errors(data, project, state, item)
    errors = []
    if data['format'] == 'vsc.episode-beats/v1':
        objects = {o['id']:o for o in state.get('objects', [])}
        maps = [json.loads((Path(project)/a['path']).read_text('utf-8')) for a in state['artifacts']
                if a['id'] in item.get('depends_on', []) and a['type']=='vsc.adaptation_plan']
        units = {u['id'] for m in maps for u in m.get('screen_units', [])}
        for episode in data['episodes']:
            if objects.get(episode['id'], {}).get('kind') != 'episode': errors.append('beats episode 未登记')
            if item.get('scope','project') not in ('project',episode['id']): errors.append('beats 超出scope')
            for beat in episode['beats']:
                if set(beat['screen_unit_ids']) - units: errors.append('beat 引用不存在或未依赖的 screen_unit')
    return errors


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('command',choices=('validate',)); parser.add_argument('file')
    args=parser.parse_args()
    try:
        errors=validation_errors(json.loads(Path(args.file).read_text('utf-8')))
        if errors: raise ValueError('；'.join(errors))
        print('STORY: PASS'); return 0
    except (ValueError,OSError,TypeError,KeyError) as exc: print('ERROR: '+str(exc)); return 1


if __name__=='__main__': raise SystemExit(main())
