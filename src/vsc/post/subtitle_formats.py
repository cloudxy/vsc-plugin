"""Lossless source retention with normalized timed subtitle consumers."""
import hashlib
import re
from pathlib import PurePath
from vsc.post.subtitles import parse_srt, to_srt, SubtitleError


def _seconds(value):
    parts=value.strip().replace(',', '.').split(':')
    if len(parts)==2:parts.insert(0,'0')
    if len(parts)!=3:raise SubtitleError(['字幕时码格式无效'])
    return int(parts[0])*3600+int(parts[1])*60+float(parts[2])


def normalize_subtitle(filename,text,*,duration=None,require_timing=False):
    format_=PurePath(filename).suffix.lower().lstrip('.')
    text=text.lstrip('\ufeff').replace('\r\n','\n').replace('\r','\n')
    if format_ not in {'srt','vtt','ass','ssa','txt'}:raise SubtitleError(['支持SRT、VTT、ASS、SSA与TXT字幕'])
    cues=[];untimed=''
    if format_=='srt':cues=parse_srt(text,strict=True,duration=duration)
    elif format_=='vtt':
        for block in re.split(r'\n\s*\n',text):
            lines=block.splitlines()
            if not lines or lines[0].startswith(('WEBVTT','NOTE','STYLE','REGION')):continue
            idx=next((i for i,line in enumerate(lines) if '-->' in line),None)
            if idx is None:continue
            left,right=lines[idx].split('-->',1)
            cues.append((_seconds(left),_seconds(right.strip().split()[0]),'\n'.join(lines[idx+1:])))
    elif format_ in {'ass','ssa'}:
        fields=['layer','start','end','style','name','marginl','marginr','marginv','effect','text'];events=False
        for line in text.splitlines():
            if line.startswith('['):events=line.strip().lower()=='[events]'
            elif events and line.lower().startswith('format:'):fields=[s.strip().lower() for s in line.split(':',1)[1].split(',')]
            elif events and line.lower().startswith('dialogue:'):
                parts=line.split(':',1)[1].strip().split(',',len(fields)-1)
                if len(parts)!=len(fields) or not {'start','end','text'}<=set(fields):raise SubtitleError(['ASS/SSA事件列不完整'])
                row=dict(zip(fields,parts));content=re.sub(r'\{[^}]*\}','',row['text']).replace('\\N','\n').replace('\\n','\n').replace('\\h',' ')
                cues.append((_seconds(row['start']),_seconds(row['end']),content))
    else:
        if '-->' in text:cues=parse_srt(text,strict=True,duration=duration)
        else:
            for line in text.splitlines():
                match=re.match(r'^\s*\[?([\d:.]+)\s*[-–]\s*([\d:.]+)\]?\s+(.+)$',line)
                if match:cues.append((_seconds(match[1]),_seconds(match[2]),match[3]))
                elif line.strip():untimed+=line+'\n'
            if cues and untimed:raise SubtitleError(['TXT中混合有时码与无时码行，请先统一'])
    if cues:cues=parse_srt(to_srt(cues),strict=True,duration=duration)
    elif require_timing:raise SubtitleError(['该字幕没有可核验时码；纯TXT只能用于语义对照'])
    elif format_!='txt':raise SubtitleError(['字幕未解析出有效时间行'])
    return {'format':format_,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'cues':[{'start_ms':round(a*1000),'end_ms':round(b*1000),'text':s} for a,b,s in cues],
            'untimed_text':untimed.strip(),'srt':to_srt(cues)}
