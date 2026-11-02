"""Apply an explicit export watermark to derived files; preserve source bytes."""
from pathlib import Path
import hashlib
import shutil


def available():
    import importlib.util
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe') and importlib.util.find_spec('PIL'))


def watermark(source,destination,policy,*,cancelled=None):
    from PIL import Image,ImageDraw,ImageFont
    from vsc.post.edit_workspace import _probe,_run
    source,destination=Path(source),Path(destination)
    if not policy.get('watermark_required'):return source,{}
    if not available():raise ValueError('导出水印需要本机 FFmpeg、ffprobe 和 Pillow')
    info=_probe(source,cancelled);video=next(row for row in info['streams'] if row['codec_type']=='video')
    size=max(12,round(video['width']/32));font=ImageFont.load_default(size=size)
    image=Image.new('RGBA',(size*4,size*2),(0,0,0,110));draw=ImageDraw.Draw(image)
    draw.text((size//2,size//3),'VSC',font=font,fill=(255,255,255,220))
    mark=destination.with_suffix('.watermark.png');image.save(mark)
    _run(['ffmpeg','-v','error','-nostdin','-y','-i',str(source),'-i',str(mark),
        '-filter_complex',"[0:v][1:v]overlay=x='max(0,W-w-16)':y='max(0,H-h-16)'[marked]",
        '-map','[marked]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','20',
        '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(destination)],cancelled=cancelled)
    return destination,{'watermark_required':True,'price_version_id':policy.get('price_version_id'),
        'label':'VSC','recipe':'vsc.export-watermark/v1','sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
