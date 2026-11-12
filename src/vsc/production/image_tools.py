"""Fixed reference edits: local annotation pixels and explicit image-model instructions."""
from __future__ import annotations
from copy import deepcopy
import io,math,re,subprocess
from pathlib import Path
from vsc.assets.resource_service import ResourceError

EDIT_TYPE='classic-reference-edit'
OUTPUT_TYPE='classic-reference-output'
TOOLS={
 'three_view':('角色三视图',{'layout':'front_side_back'}),
 'face_views':('脸部三视图',{'layout':'front_three_quarter_side'}),
 'headshot':('大头照',{'framing':'head_and_shoulders'}),
 'texture':('人像质感',{'strength':0.5,'scene_blend':'natural','light_match':'natural','skin_polish':'natural','grain':'natural','sharpness':'standard'}),
 'expression':('表情与情绪',{'expression':'自然','strength':0.5,'valence':0,'arousal':0,'brow':0,'eye':0,'mouth':0,'head_tilt':0}),
 'angle':('多角度',{'preset':'custom','yaw':0,'pitch':0,'roll':0,'zoom':1,'include_instructions':True}),
 'lighting':('打光与轮廓光',{'view':'front','direction':'front','intensity':1,'color':'#ffffff','cone':45,'rim':False}),
 'inpaint':('局部重绘',{'mask_media_id':'','mask_sha256':'','mask_export_id':''}),
 'outpaint':('扩图',{'ratio':'16:9','padding':0.25}),
 'matting':('智能抠图',{'subject':'foreground'}),
 'panorama':('720°全景',{'projection':'equirectangular'}),
 'upscale':('4K/8K超分',{'target':'4k','creativity':0.35,'resemblance':0.6}),
 'watermark':('去水印',{'rights_confirmed':False,'mask_media_id':'','mask_sha256':'','mask_export_id':''}),
 'multi_camera_grid_2k':('多机位九宫格2K',{'layout':'3x3','resolution':'2k'}),
 'multi_camera_grid_4k':('多机位九宫格4K',{'layout':'3x3','resolution':'4k'}),
 'story_four_grid':('剧情推进四格',{'layout':'2x2'}),
 'cinematic_lighting':('电影级光影校正',{'grade':'cinematic_natural'}),
 'frame_predict_3s_after':('画面推演3s后',{'delta_seconds':3}),
 'frame_predict_5s_before':('画面推演5s前',{'delta_seconds':-5}),
}
BLOCKED={}

def split_grid_image(content, rows, columns, cells):
 """Crop selected cells in caller order from fixed original image bytes."""
 from PIL import Image, ImageOps, UnidentifiedImageError
 try:
  with Image.open(io.BytesIO(content)) as opened:
   if opened.width * opened.height > 16777216:raise ResourceError('图片切分最多支持1600万像素','canvas_grid_image_too_large')
   image=ImageOps.exif_transpose(opened);image.load()
   if image.width < columns or image.height < rows:raise ResourceError('宫格行列不能超过图片像素尺寸','canvas_grid_dimensions')
   result=[]
   for cell in cells:
    row,column=cell['row']-1,cell['column']-1
    box=(column*image.width//columns,row*image.height//rows,(column+1)*image.width//columns,(row+1)*image.height//rows)
    tile=image.crop(box);stream=io.BytesIO();tile.save(stream,format='PNG')
    result.append({'bytes':stream.getvalue(),'row':row+1,'column':column+1})
   return result
 except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
  raise ResourceError('固定图片无法解码','canvas_grid_decode_failed') from exc

def finite(value,low,high):
 if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ResourceError('编辑数值超出范围','invalid_reference_edit')
 return value

def normalize_tool(tool,settings):
 if tool not in TOOLS:raise ResourceError('未知图像工具','invalid_image_tool')
 defaults=TOOLS[tool][1]
 if not isinstance(settings,dict) or set(settings)-set(defaults):raise ResourceError('图像工具参数不匹配','invalid_image_tool')
 value={**defaults,**settings}
 for k,v in value.items():
  if type(defaults[k]) is bool and type(v)is not bool:raise ResourceError('图像工具开关无效')
  if isinstance(defaults[k],str) and (not isinstance(v,str) or len(v)>200):raise ResourceError('图像工具文本参数无效')
 for key,lo,hi in [('strength',0,1),('creativity',0,1),('resemblance',0,1),('padding',0.05,2),('valence',-1,1),('arousal',-1,1),('brow',-100,100),('eye',-100,100),('mouth',-100,100),('head_tilt',-100,100),('delta_seconds',-30,30),('yaw',-180,180),('pitch',-90,90),('roll',-180,180),('zoom',0.25,4),('intensity',0,5),('cone',1,180)]:
  if key in value:finite(value[key],lo,hi)
 if 'color'in value and not re.fullmatch('#[0-9a-fA-F]{6}',value['color']):raise ResourceError('光源颜色无效')
 if tool=='angle' and value['preset'] not in {'custom','fisheye','tilt','front_high','front_low','top','back'}:raise ResourceError('角度预设无效')
 if tool=='lighting' and (value['direction'] not in {'front','back','left','right','top','bottom'} or value['view'] not in {'front','perspective'}):raise ResourceError('光源方向无效')
 if tool=='upscale' and value['target'] not in {'4k','8k'}:raise ResourceError('超分规格无效')
 if tool=='panorama' and value['projection']!='equirectangular':raise ResourceError('全景预览使用VSC 2:1等距柱状合同')
 if tool=='texture':
  if value['scene_blend'] not in {'light','natural','deep'} or value['light_match'] not in {'soft','natural','dramatic'} or value['skin_polish'] not in {'clean','natural','micro'} or value['grain'] not in {'soft','natural','film_grain'} or value['sharpness'] not in {'soft_focus','standard','hd_sharp'}:
   raise ResourceError('人像质感五维选项无效')
 return value

def tool_instruction(tool,value):
 # Prompt-based reference edits have a real existing ImageRequest consumer.
 label=TOOLS[tool][0]
 if tool=='angle' and not value['include_instructions']:return ''
 description={
  'three_view':'同一人物正面、侧面、背面三视图，保持身份、服装和比例；布局 '+str(value.get('layout')),
  'face_views':'同一面孔正面、四分之三侧面和侧面，保持身份；布局 '+str(value.get('layout')),
  'headshot':'保持人物身份的大头照；取景 '+str(value.get('framing')),
  'texture':'保留人物身份，人景 '+str(value.get('scene_blend'))+'，光影 '+str(value.get('light_match'))+'，肤质 '+str(value.get('skin_polish'))+'，纹理 '+str(value.get('grain'))+'，锐度 '+str(value.get('sharpness'))+'，强度 '+str(value.get('strength')),
  'expression':'保持人物身份，表情 '+str(value.get('expression'))+'，情绪坐标('+str(value.get('valence'))+','+str(value.get('arousal'))+')，五官微调('+str(value.get('brow'))+','+str(value.get('eye'))+','+str(value.get('mouth'))+','+str(value.get('head_tilt'))+')，程度 '+str(value.get('strength')),
  'angle':'保持主体身份；相机预设 '+str(value.get('preset'))+'，水平 '+str(value.get('yaw'))+'°，俯仰 '+str(value.get('pitch'))+'°，倾斜 '+str(value.get('roll'))+'°，景别倍率 '+str(value.get('zoom')),
  'lighting':'保持主体身份；视图 '+str(value.get('view'))+'，主光 '+str(value.get('direction'))+'，强度 '+str(value.get('intensity'))+'，颜色 '+str(value.get('color'))+'，光锥 '+str(value.get('cone'))+'°，轮廓光 '+str(value.get('rim')),
  'multi_camera_grid_2k':'保持主体与场景连续性，生成 3×3 多机位九宫格分镜（2K 规格）',
  'multi_camera_grid_4k':'保持主体与场景连续性，生成 3×3 多机位九宫格分镜（4K 规格）',
  'story_four_grid':'保持人物与环境一致，生成 2×2 剧情推进四格关键帧',
  'cinematic_lighting':'保持人物与构图不变，执行电影级光影与影调校正（'+str(value.get('grade'))+'）',
  'frame_predict_3s_after':'推演当前画面 3 秒后的动作与镜头延续帧',
  'frame_predict_5s_before':'反推当前画面 5 秒前的前置动作与起因帧',
  'outpaint':'向外自然延展画面边界，目标比例 '+str(value.get('ratio'))+'，延展幅度 '+str(value.get('padding')),
  'matting':'提取前景主体并保持边缘发丝干净'}
 return label+'：'+description.get(tool,'按保存的工具规格处理。')+'。模型按文字指令解释，不保证精确几何。'

def normalize_edit(value):
 fields={'format','id','source_media_id','source_sha256','source_modality','time_ms','width','height','description','operations','brightness','saturation','grid'}
 if not isinstance(value,dict) or set(value)-fields:raise ResourceError('参考编辑文档字段无效','invalid_reference_edit')
 d=deepcopy(value);d.setdefault('format','vsc.reference-edit/v1')
 if d['format']!='vsc.reference-edit/v1':raise ResourceError('参考编辑版本不支持')
 for field in ('id','source_media_id'):
  if not isinstance(d.get(field),str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',d[field]):raise ResourceError('参考编辑身份无效')
 if not isinstance(d.get('source_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',d['source_sha256']):raise ResourceError('需要固定源媒体摘要')
 if d.get('source_modality') not in {'image','video'}:raise ResourceError('参考编辑只接受图像或视频')
 for name,lo,hi in [('time_ms',0,86400000),('width',1,16384),('height',1,16384)]:
  if type(d.get(name))is not int or not lo<=d[name]<=hi:raise ResourceError('时码或图像尺寸无效')
 if d['width']*d['height']>16777216:raise ResourceError('单次标注最多1600万像素')
 if d['source_modality']=='image' and d['time_ms']!=0:raise ResourceError('静态图像不带视频时码')
 d.setdefault('description','');d.setdefault('brightness',1);d.setdefault('saturation',1)
 if not isinstance(d['description'],str) or len(d['description'])>20000:raise ResourceError('修改说明过长')
 finite(d['brightness'],0,3);finite(d['saturation'],0,3)
 grid=d.setdefault('grid',{'rows':1,'columns':1})
 if not isinstance(grid,dict) or set(grid)!={'rows','columns'} or any(type(v)is not int or not 1<=v<=4 for v in grid.values()):raise ResourceError('宫格行列需为1到4')
 operations=d.setdefault('operations',[])
 if not isinstance(operations,list) or len(operations)>300:raise ResourceError('标注最多300步')
 total=0;ids=set()
 for op in operations:
  if not isinstance(op,dict) or set(op)-{'id','tool','points','color','width','text'}:raise ResourceError('标注操作字段无效')
  if op.get('tool') not in {'pen','rectangle','arrow','text','eraser','mask','marker'} or not isinstance(op.get('id'),str) or op['id'] in ids:raise ResourceError('标注工具或身份无效')
  ids.add(op['id']);points=op.get('points');total+=len(points) if isinstance(points,list) else 0
  if not isinstance(points,list) or not 1<=len(points)<=4000 or total>12000:raise ResourceError('标注点数超过范围')
  for pair in points:
   if not isinstance(pair,list) or len(pair)!=2:raise ResourceError('标注坐标无效')
   for v in pair:finite(v,0,1)
  if not re.fullmatch('#[0-9a-fA-F]{6}',str(op.get('color',''))):raise ResourceError('标注颜色无效')
  finite(op.get('width'),0.00001,0.15)
  if not isinstance(op.get('text',''),str) or len(op.get('text',''))>500:raise ResourceError('标注文字过长')
 return d

def render_reference(path,document):
 """Render only original pixels, explicit vector marks and color adjustments; no model."""
 from PIL import Image,ImageDraw,ImageFont,ImageEnhance,ImageOps
 d=normalize_edit(document)
 try:
  if d['source_modality']=='video':
   r=subprocess.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-ss',str(d['time_ms']/1000),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,timeout=20)
   if r.returncode or not r.stdout:raise ResourceError('无法提取指定视频帧','reference_frame_failed')
   source=Image.open(io.BytesIO(r.stdout));source.load()
  else:source=Image.open(path);source.load()
 except (OSError,ValueError,subprocess.TimeoutExpired) as exc:raise ResourceError('固定媒体无法解码为编辑画面','reference_decode_failed') from exc
 source=ImageOps.exif_transpose(source).convert('RGB').resize((d['width'],d['height']));source=ImageEnhance.Brightness(source).enhance(d['brightness']);source=ImageEnhance.Color(source).enhance(d['saturation'])
 overlay=Image.new('RGBA',source.size,(0,0,0,0));mask=Image.new('L',source.size,0)
 for op in d['operations']:
  points=[(round(x*(d['width']-1)),round(y*(d['height']-1))) for x,y in op['points']];width=max(1,round(op['width']*min(source.size)));tool=op['tool']
  layer=mask if tool=='mask' else overlay;draw=ImageDraw.Draw(layer);color=255 if tool=='mask' else (0,0,0,0) if tool=='eraser' else op['color']
  if tool=='rectangle':
   a,b=points[0],points[-1];draw.rectangle((min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])),outline=color,width=width)
  elif tool=='text':
   font=None
   for filename in ['/System/Library/Fonts/PingFang.ttc','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
    if Path(filename).is_file():font=ImageFont.truetype(filename,max(12,width*4));break
   draw.text(points[0],op.get('text',''),fill=color,font=font)
  else:
   if len(points)>1:draw.line(points,fill=color,width=width,joint='curve')
   for x,y in points:draw.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=color)
   if tool=='arrow' and len(points)>1:
    a,b=points[0],points[-1];angle=math.atan2(b[1]-a[1],b[0]-a[0]);length=max(12,width*4)
    for delta in (-.5,.5):draw.line([b,(b[0]-length*math.cos(angle+delta),b[1]-length*math.sin(angle+delta))],fill=color,width=width)
 source=Image.alpha_composite(source.convert('RGBA'),overlay)
 outputs=[]
 # Keep the established black/white export; the native edit protocol receives
 # a separately fixed alpha mask, with transparent pixels marking the edit.
 alpha_mask=Image.new('RGBA',source.size,(255,255,255,255));alpha_mask.putalpha(ImageOps.invert(mask))
 for role,image in [('annotation',source),('mask',mask),('inpaint-mask',alpha_mask)]:
  stream=io.BytesIO();image.save(stream,format='PNG');outputs.append({'role':role,'bytes':stream.getvalue()})
 grid=d['grid']
 if grid['rows']*grid['columns']>1:
  for row in range(grid['rows']):
   for column in range(grid['columns']):
    tile=source.crop((column*d['width']//grid['columns'],row*d['height']//grid['rows'],(column+1)*d['width']//grid['columns'],(row+1)*d['height']//grid['rows']));stream=io.BytesIO();tile.save(stream,format='PNG');outputs.append({'role':'tile-'+str(row+1)+'-'+str(column+1),'bytes':stream.getvalue()})
 return outputs
