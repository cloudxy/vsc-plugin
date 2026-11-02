"""Deterministic product contracts for fixed text inputs; no provider calls."""
from copy import deepcopy
import hashlib
import re

from vsc.assets.resource_service import ResourceError


def sha(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def chapters(source):
    matches=list(re.finditer(r'(?m)^第[零一二三四五六七八九十百千0-9]+章[^\n]*',source))
    if not matches:return [{'ordinal':1,'title':'全文','text':source,'start':0,'end':len(source)}]
    return [{'ordinal':i+1,'title':m.group(),'text':source[m.start():matches[i+1].start() if i+1<len(matches) else len(source)],
             'start':m.start(),'end':matches[i+1].start() if i+1<len(matches) else len(source)} for i,m in enumerate(matches)]


def chapter_text(source,start,end):
    rows=chapters(source)
    if type(start)is not int or type(end)is not int or not 1<=start<=end<=len(rows):
        raise ResourceError('章节范围超出实际原文，请重新选择','novel_chapter_range')
    return ''.join(r['text'] for r in rows[start-1:end])


def novel_plan(document,rows):
    if not document.get('synopsis','').strip() or not document.get('core_setting','').strip():
        raise ResourceError('请先保存全剧梗概与核心设定','novel_baseline_required')
    if not isinstance(rows,list) or len(rows)!=document['target_episodes'] or len(rows)>200:
        raise ResourceError('逐集计划数量必须等于目标集数','novel_episode_count')
    result=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict) or set(row)!={'title','chapter_start','chapter_end','outline'} or not isinstance(row['title'],str) or not row['title'].strip() or not isinstance(row['outline'],str):
            raise ResourceError('逐集计划需要标题、实际章范围与大纲')
        start,end=row['chapter_start'],row['chapter_end']
        if not document['chapter_start']<=start<=end<=document['chapter_end']:
            raise ResourceError('分集章范围必须位于所选全剧范围内','novel_chapter_range')
        result.append(dict(row,ordinal=i+1,source_text=chapter_text(document['source_text'],start,end)))
    return result


def scoring_boundary(document):
    lines=document['source_text'].splitlines()
    start,end=document.get('card_start_line',1),document.get('card_end_line',1)
    if type(start)is not int or type(end)is not int or not 1<=start<=end<=max(1,len(lines)):
        raise ResourceError('首卡行范围超出当前原文','scoring_card_range')
    return {'source_sha256':sha(document['source_text']),'start_line':start,'end_line':end,
            'text':'\n'.join(lines[start-1:end]),'sha256':sha('\n'.join(lines[start-1:end]))}


def translation_residuals(document):
    if document.get('target_language','').lower() not in {'english','en','英语','英文'}:return []
    return [{'line':i,'text':line,'reason':'英文目标中仍含中文字符，请人工判断是否为专名或残留'}
            for i,line in enumerate(document.get('body','').splitlines(),1) if re.search('[\u3400-\u9fff]',line)]


def host_input(tool,document,action):
    value=deepcopy(document)
    if tool=='novel' and not value.get('novel_baseline_version_id'):
        value['source_text']=chapter_text(value['source_text'],value['chapter_start'],value['chapter_end'])
    if tool=='scoring':value['fixed_card']=scoring_boundary(value)
    return value
