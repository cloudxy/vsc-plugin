"""Bounded local transformations of fixed media bytes, without generation calls."""
from __future__ import annotations
import json
import math
from pathlib import Path
import subprocess

from vsc.assets.resource_service import ResourceError

LOCAL_TOOLS = frozenset({'extract_frame', 'separate_audio', 'remove_subtitles', 'remove_watermark', 'segment_remake'})
RECIPE = 'vsc.local-media-tools/v1'


def command(args, timeout=60):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResourceError('本机处理工具缺失或超过时间上限；输入仍保留', 'local_tool_unavailable') from exc
    if result.returncode:
        raise ResourceError('固定素材无法按所选参数处理；请检查轨道、区域和输入', 'local_tool_failed')
    return result.stdout


def inspect_video(path):
    data = json.loads(command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-show_streams', '-show_format', '-of', 'json', str(path)], 20))
    video = next((row for row in data.get('streams', []) if row.get('codec_type') == 'video'), None)
    try:
        duration = float(video.get('duration') or data['format']['duration'])
        width, height = int(video['width']), int(video['height'])
    except (TypeError, KeyError, ValueError) as exc:
        raise ResourceError('本机加工需要有效视频及实测时长', 'local_source_invalid') from exc
    if not math.isfinite(duration) or not 0 < duration <= 600 or width * height > 16777216:
        raise ResourceError('单次本机加工限 10 分钟、1600 万像素；请先分段', 'local_source_limit')
    return data, duration, width, height


def frame(path, destination, mode='current', time_ms=0):
    """Select an actual decoded frame timestamp; last means the last video frame."""
    data, duration, width, height = inspect_video(path)
    if mode not in {'first', 'last', 'current'} or type(time_ms) is not int or not 0 <= time_ms < math.ceil(duration * 1000):
        raise ResourceError('帧模式或当前时码越界', 'local_frame_invalid')
    start = max(0, duration - 3) if mode == 'last' else max(0, time_ms / 1000 - 1) if mode == 'current' else 0
    end = duration if mode == 'last' else min(duration, time_ms / 1000 + 2) if mode == 'current' else min(duration, 2)
    stream = next(row for row in data['streams'] if row.get('codec_type') == 'video')
    origin = float(stream.get('start_time') or 0)
    raw = command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-select_streams', 'v:0',
        '-read_intervals', f'{start+origin}%{end+origin}', '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(path)], 20)
    times = sorted(float(row['best_effort_timestamp_time'])-origin for row in json.loads(raw).get('frames', []) if row.get('best_effort_timestamp_time') is not None)
    if mode == 'current':
        times = [value for value in times if value + .000001 >= time_ms / 1000]
    if not times:
        raise ResourceError('所选时码没有可解码的视频帧', 'local_frame_missing')
    selected = times[-1] if mode == 'last' else times[0]
    command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe',
        '-ss', f'{selected:.6f}', '-i', str(path), '-map', '0:v:0', '-frames:v', '1', str(destination)], 30)
    return {'frame_mode': mode, 'requested_time_ms': time_ms, 'selected_time_ms': round(selected * 1000),
            'ffmpeg_version': command(['ffmpeg', '-version'], 10).decode(errors='replace').splitlines()[0],
            'width': width, 'height': height}


def replace_segments(path,replacement,document,directory):
    """Replace decoded CFR frame spans; preserve the source timeline length."""
    from fractions import Fraction
    data,duration,width,height=inspect_video(path);other,other_duration,_,_=inspect_video(replacement)
    video=next(row for row in data['streams'] if row.get('codec_type')=='video')
    try:fps=Fraction(video['avg_frame_rate'])
    except (KeyError,ValueError,ZeroDivisionError) as error:raise ResourceError('区间替换需要有效固定帧率') from error
    if not 1<=float(fps)<=120 or abs(float(Fraction(video.get('r_frame_rate') or str(fps)))-float(fps))>.01:
        raise ResourceError('区间替换暂需固定帧率视频；先在原剪辑中规范化','local_replace_cfr_required')
    if any(abs(float(row.get('rotation') or 0))>.01 for row in video.get('side_data_list',[])):
        raise ResourceError('带旋转元数据的源片请先规范化后替换')
    params=document['params'];ranges=document['ranges']
    if set(params)-{'replacement_in_ms','audio_mode'} or not 1<=len(ranges)<=5:
        raise ResourceError('替换需要1至5个明确区间、替换片剪入点和音频方式')
    offset=params.get('replacement_in_ms',0);audio_mode=params.get('audio_mode','keep_source')
    if type(offset)is not int or offset<0 or audio_mode not in {'keep_source','replace'}:raise ResourceError('替换片剪入点或音频方式无效')
    timestamps=json.loads(command(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],60)).get('frames',[])
    try:times=[float(r['best_effort_timestamp_time']) for r in timestamps]
    except (KeyError,ValueError) as error:raise ResourceError('无法核验源片每帧时码') from error
    if not times or any(abs((b-a)-1/float(fps))>.0002 for a,b in zip(times,times[1:])):raise ResourceError('实测帧间隔不恒定，请先规范化后替换','local_replace_cfr_required')
    total_frames=len(times);cursor=0;spans=[];replacement_cursor=offset/1000;frame_ranges=[]
    for row in ranges:
        a,b=row['start_ms']/1000,row['end_ms']/1000;start,end=round(a*float(fps)),round(b*float(fps))
        if not cursor<=start<end<=total_frames or abs(start/float(fps)-a)>.001 or abs(end/float(fps)-b)>.001:
            raise ResourceError('替换区间须对齐源片实际帧边界且不重叠；不会自动挪动区间','local_replace_frame_boundary')
        if start>cursor:spans.append((0,cursor/float(fps),(start-cursor)/float(fps)))
        frame_ranges.append(dict(start_frame=start,end_frame=end))
        length=(end-start)/float(fps)
        if replacement_cursor+length>other_duration+.001:raise ResourceError('替换素材不足以覆盖所选全部区间','local_replacement_short')
        spans.append((1,replacement_cursor,length));replacement_cursor+=length;cursor=end
    if cursor<total_frames:spans.append((0,cursor/float(fps),(total_frames-cursor)/float(fps)))
    has_audio=[any(r.get('codec_type')=='audio' for r in d['streams']) for d in (data,other)]
    filters=[];parts=[];timeline=0.;include_audio=has_audio[0] or audio_mode=='replace' and has_audio[1]
    for i,(source,start,length) in enumerate(spans):
        v=f'v{i}';a=f'a{i}'
        filters.append(f'[{source}:v:0]setpts=PTS-STARTPTS,trim=start={start:.9f}:duration={length:.9f},setpts=PTS-STARTPTS,fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[{v}]')
        if include_audio:
            sound=source if audio_mode=='replace' else 0;sound_start=start if audio_mode=='replace' else timeline
            if has_audio[sound]:filters.append(f'[{sound}:a:0]asetpts=PTS-STARTPTS,atrim=start={sound_start:.9f}:duration={length:.9f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={length:.9f}[{a}]')
            else:filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length:.9f},asetpts=PTS-STARTPTS[{a}]')
        parts.append(f'[{v}]'+(f'[{a}]' if include_audio else ''));timeline+=length
    filters.append(''.join(parts)+f'concat=n={len(parts)}:v=1:a={1 if include_audio else 0}[outv]'+('[outa]' if include_audio else ''))
    output=Path(directory)/'interval-replaced.mp4'
    args=['ffmpeg','-v','error','-nostdin','-y','-protocol_whitelist','file,pipe','-i',str(path),'-protocol_whitelist','file,pipe','-i',str(replacement),'-filter_complex',';'.join(filters),'-map','[outv]']
    if include_audio:args+=['-map','[outa]','-c:a','aac','-b:a','192k']
    command(args+['-c:v','libx264','-profile:v','high','-crf','12','-preset','fast','-pix_fmt','yuv420p','-r',str(fps),'-t',f'{timeline:.9f}','-movflags','+faststart',str(output)],120)
    return [{'role':'video','path':output}],dict(recipe=RECIPE,method='fixed-frame-interval-replacement/v1',ranges=ranges,replacement_in_ms=offset,
        audio_mode=audio_mode,source_frame_ranges=frame_ranges,source_duration_ms=round(duration*1000),output_duration_ms=round(timeline*1000),fps=str(fps),encoding='h264-high-yuv420p-crf12+aac',
        ffmpeg_version=command(['ffmpeg','-version'],10).decode(errors='replace').splitlines()[0],
        limitation='源区间外内容按原时间保留；统一帧率/像素格式并重新编码，音频为AAC，不承诺压缩字节相同。未生成新画面。')


def process(path, document, directory, replacement=None):
    tool, params, ranges = document['tool'], document['params'], document['ranges']
    if tool not in LOCAL_TOOLS:
        raise ResourceError('此工具没有本机处理消费者', 'local_tool_unsupported')
    if tool=='segment_remake':
        if replacement is None:raise ResourceError('请显式选择已存在的替换视频；提示词不会生成替换内容')
        return replace_segments(path,replacement,document,directory)
    root = Path(directory)
    data, duration, width, height = inspect_video(path)
    if tool == 'extract_frame':
        if set(params) - {'frame_mode', 'time_ms'} or ranges:
            raise ResourceError('帧提取只接受帧模式和当前毫秒时码')
        output = root / 'frame.png'
        receipt = frame(path, output, params.get('frame_mode', 'first'), params.get('time_ms', 0))
        return [{'role': 'frame', 'path': output}], {'recipe': RECIPE, **receipt}
    if tool == 'separate_audio':
        if params or ranges:
            raise ResourceError('轨道分离保持完整源片，不接受人声分离或区间参数')
        if not any(row.get('codec_type') == 'audio' for row in data.get('streams', [])):
            raise ResourceError('源视频没有音轨', 'local_audio_missing')
        video, audio = root / 'video-no-audio.mp4', root / 'audio-track.wav'
        command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(path),
            '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', str(video)])
        command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(path),
            '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', str(audio)])
        return [{'role': 'video', 'path': video}, {'role': 'audio', 'path': audio}], {
            'ffmpeg_version': command(['ffmpeg', '-version'], 10).decode(errors='replace').splitlines()[0],
            'recipe': RECIPE, 'method': 'video-stream-copy+first-audio-pcm', 'vocal_separation': False,
            'source_duration_ms': round(duration * 1000)}
    if set(params) != {'rectangle'} or not isinstance(params['rectangle'], dict) or set(params['rectangle']) != {'x', 'y', 'width', 'height'}:
        raise ResourceError('区域处理需要 x/y/width/height 像素矩形', 'local_rectangle_invalid')
    rect = params['rectangle']
    if any(type(value) is not int for value in rect.values()):
        raise ResourceError('矩形坐标须为整数像素', 'local_rectangle_invalid')
    x, y, w, h = (rect[key] for key in ('x', 'y', 'width', 'height'))
    if not (1 <= x and 1 <= y and w >= 2 and h >= 2 and x + w < width - 1 and y + h < height - 1):
        raise ResourceError('插值区域须在源画面内并保留边界像素', 'local_rectangle_invalid')
    if not ranges or any(row['end_ms'] > math.ceil(duration * 1000) for row in ranges):
        raise ResourceError('区域处理需要明确且不越界的时间区间', 'local_range_invalid')
    enabled = '+'.join(f"gte(t,{row['start_ms']/1000:.3f})*lt(t,{row['end_ms']/1000:.3f})" for row in ranges)
    output = root / 'region-processed.mp4'
    command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(path),
        '-map', '0:v:0', '-map', '0:a?', '-vf', f"delogo=x={x}:y={y}:w={w}:h={h}:show=0:enable='{enabled}'",
        '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', str(output)])
    return [{'role': 'video', 'path': output}], {'recipe': RECIPE, 'method': 'ffmpeg-delogo-boundary-interpolation',
        'ffmpeg_version': command(['ffmpeg', '-version'], 10).decode(errors='replace').splitlines()[0],
        'rectangle': rect, 'ranges': ranges, 'source_duration_ms': round(duration * 1000),
        'limitation': '矩形边界插值，不识别字幕、不恢复被遮挡原画；处理区间外保留画面内容但视频重新编码'}
