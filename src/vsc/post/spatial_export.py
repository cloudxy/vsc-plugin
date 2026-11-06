"""Bounded software previs renderer and public glTF 2.0 interchange.

Both editor previews and PNG/video exports use these exact meshes and camera
samples. This is a representative flat-shaded renderer, not a full DCC engine.
"""
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from vsc.assets.resource_service import ResourceError


def add(a, b): return [x + y for x, y in zip(a, b)]
def sub(a, b): return [x - y for x, y in zip(a, b)]
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def unit(a):
    length = math.sqrt(dot(a, a))
    return [x / length for x in a] if length > 1e-10 else [0, 1, 0]


def sample(item, instant):
    result = deepcopy(item)
    frames = item.get("keyframes", [])
    if not frames:
        return result
    frames = ([dict(time=0, **{k: item[k] for k in ("position", "rotation", "target") if k in item})] if frames[0]["time"] > 0 else []) + frames
    before = next((frame for frame in reversed(frames) if frame["time"] <= instant), frames[0])
    after = next((frame for frame in frames if frame["time"] >= instant), frames[-1])
    ratio = (instant - before["time"]) / (after["time"] - before["time"]) if after["time"] != before["time"] else 0
    for field in ("position", "rotation", "target"):
        a, b = before.get(field, item.get(field)), after.get(field, item.get(field))
        if a is not None and b is not None:
            result[field] = [x + (y - x) * ratio for x, y in zip(a, b)]
    return result


def rotate(point, rotation):
    x, y, z = point
    rx, ry, rz = [math.radians(v) for v in rotation]
    y, z = y*math.cos(rx)-z*math.sin(rx), y*math.sin(rx)+z*math.cos(rx)
    x, z = x*math.cos(ry)+z*math.sin(ry), -x*math.sin(ry)+z*math.cos(ry)
    x, y = x*math.cos(rz)-y*math.sin(rz), x*math.sin(rz)+y*math.cos(rz)
    return [x, y, z]


def transform(points, position, rotation, scale):
    return [add(rotate([v*s for v, s in zip(point, scale)], rotation), position) for point in points]


def box():
    vertices = [[x, y, z] for x, y, z in [(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),
        (-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]]
    return vertices, [[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[3,7,6],[3,6,2],[0,4,7],[0,7,3],[1,2,6],[1,6,5]]


def sphere():
    vertices, triangles = [], []
    for lat in range(9):
        phi = math.pi * lat / 8
        for lon in range(12):
            theta = 2 * math.pi * lon / 12
            vertices.append([.5*math.sin(phi)*math.cos(theta), .5*math.cos(phi), .5*math.sin(phi)*math.sin(theta)])
    for lat in range(8):
        for lon in range(12):
            a, b, c, d = lat*12+lon, lat*12+(lon+1)%12, (lat+1)*12+lon, (lat+1)*12+(lon+1)%12
            triangles += [[a,c,b],[b,c,d]]
    return vertices, triangles


def actor_mesh(item):
    vertices, faces = [], []
    pose, joints = item.get("pose", "stand"), item.get("joints", {})
    crouch = pose in {"sit", "crouch"}
    hip = .65 if crouch else 1.05
    torso_tilt = joints.get("torso", 20 if pose == "crouch" else 0)
    arm = -145 if pose == "arms_up" else 20 if pose == "walk" else 0
    parts = [([0,hip+.28,0],[.5,.65,.25],[torso_tilt,0,0],False),
        ([0,hip+.85,.03],[.37,.42,.37],[0,joints.get("head",0),0],True),
        ([-.35,hip+.25,0],[.16,.67,.17],[joints.get("left_arm",arm),0,-8],False),
        ([.35,hip+.25,0],[.16,.67,.17],[joints.get("right_arm",-arm if pose=='walk' else arm),0,8],False)]
    for side in (-1,1):
        if crouch:
            parts.extend([([side*.16,.52,.2],[.21,.22,.6],[0,0,0],False),([side*.16,.25,.45],[.19,.5,.19],[0,0,0],False)])
        else:
            parts.append(([side*.16,.5,0],[.21,.98,.22],[side*20 if pose=='walk' else 0,0,0],False))
    for position, scale, rotation, rounded in parts:
        pts, tris = sphere() if rounded else box()
        offset = len(vertices)
        vertices += transform(pts, position, rotation, scale)
        faces += [[i+offset for i in triangle] for triangle in tris]
    return vertices, faces


def scene_meshes(document, instant):
    result = []
    for original in document["objects"]:
        item = sample({k:v for k,v in original.items() if k != "_gltf"}, instant)
        if not item["visible"] or item["kind"] in {"light", "reference"}:
            continue
        if item["kind"] == "mesh" and "source_sha256" in item["geometry"]:
            from vsc.post.spatial_gltf import sample_model, normal
            model = original.get("_gltf")
            if model is None:
                raise ResourceError("GLB 必须通过所属项目读取固定媒体后渲染", "spatial_model_unresolved")
            animation = item["animation"];time = max(0, instant*animation["speed"]+animation["offset"])
            if animation["clip"] is not None:
                duration = model["animations"][animation["clip"]]["duration"]
                time = time%duration if animation["loop"] and duration else min(time,duration)
            # Object transforms surround the already sampled node/skin hierarchy.
            basis = transform([[1,0,0],[0,1,0],[0,0,1]],[0,0,0],item["rotation"],item["scale"])
            affine = [v for column in basis for v in column+[0]]+item["position"]+[1]
            tint = [int(item["color"][i:i+2],16)/255 for i in (1,3,5)]
            for mesh in sample_model(model,item["geometry"]["scene"],animation["clip"],time):
                mesh["vertices"] = transform(mesh["vertices"],item["position"],item["rotation"],item["scale"])
                if "normals" in mesh:mesh["normals"] = [normal(affine,n) for n in mesh["normals"]]
                if "tangents" in mesh:mesh["tangents"] = [unit(rotate([x*s for x,s in zip(t[:3],item["scale"])],item["rotation"]))+[t[3]] for t in mesh["tangents"]]
                mesh["id"] = item["id"]+"-"+mesh["id"];mesh["name"] = item["name"]+" / "+mesh["name"]
                mesh["material"] = deepcopy(mesh["material"])
                pbr = mesh["material"]["pbrMetallicRoughness"]
                pbr["baseColorFactor"] = [v*t for v,t in zip(pbr["baseColorFactor"][:3],tint)]+[pbr["baseColorFactor"][3]]
                result.append(mesh)
            continue
        if item["kind"] == "mesh":
            points, triangles = item["geometry"]["vertices"], item["geometry"]["triangles"]
        elif item["kind"] == "actor":
            points, triangles = actor_mesh(item)
        else:
            points, triangles = sphere() if item["kind"] == "sphere" else box()
        result.append({"id": item["id"], "name": item["name"], "color": item["color"],
            "vertices": transform(points, item["position"], item["rotation"], item["scale"]), "triangles": triangles})
    return result


def camera_at(document, camera_id, instant):
    original = next((item for item in document["cameras"] if item["id"] == camera_id), None)
    if original is None:
        raise ResourceError("所选机位不属于固定场景", "spatial_camera_missing")
    camera = sample(original, instant)
    forward = unit(sub(camera["target"], camera["position"]))
    if dot(sub(camera["target"], camera["position"]), sub(camera["target"], camera["position"])) < .0001:
        raise ResourceError("该时刻机位与注视目标重合", "spatial_camera_degenerate")
    right = unit(cross(forward, [0, 1, 0] if abs(forward[1]) < .99 else [0, 0, 1]))
    up = unit(cross(right, forward))
    return camera, right, up, forward


def render_png(document, camera_id, instant, maximum=None):
    from vsc.post.spatial_raster import rasterize
    lights = [sample(item, instant)["position"] for item in document["objects"] if item["kind"] == "light" and item["visible"]] or [[5,10,8]]
    return rasterize(document, scene_meshes(document, instant), camera_at(document, camera_id, instant), lights, maximum)


# Measured still sizes from the reference previs: 16:9 video 960×540 becomes
# PNG 1920×1080, and 9:16 video 540×960 becomes PNG 1080×1920. Other frame
# sizes stay as stored; unmeasured aspect presets are not scaled here.
STILL_FROM_VIDEO = {(960, 540): (1920, 1080), (540, 960): (1080, 1920)}


def still_frame_size(width, height):
    return STILL_FROM_VIDEO.get((width, height), (width, height))


def render_still_png(document, camera_id, instant):
    width, height = still_frame_size(document["width"], document["height"])
    framed = document if (width, height) == (document["width"], document["height"]) else dict(document, width=width, height=height)
    return render_png(framed, camera_id, instant)


def export_glb(document, camera_id, instant, *, animated=False):
    """Export a fixed pose or editable scene animation using embedded media only."""
    if animated:return export_animated_glb(document,camera_id,instant)
    data = {"asset": {"version": "2.0", "generator": "VSC bounded spatial renderer 1"}, "scene": 0,
        "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "materials": [], "cameras": [],
        "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [], "images": [], "textures": [], "samplers": [],
        "extras": {"source_camera": camera_id, "source_time_seconds": instant, "animation_baked": True,
            "bake_description": "Selected scene time; skins and morphs baked to static meshes; materials and embedded textures preserved"}}
    binary = bytearray()
    def accessor(values, components, component_type, target):
        while len(binary)%4:
            binary.append(0)
        offset = len(binary)
        fmt = "f" if component_type == 5126 else "I"
        flat = [v for row in values for v in row] if components>1 else values
        binary.extend(struct.pack("<"+fmt*len(flat), *flat))
        view = len(data["bufferViews"])
        data["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":len(binary)-offset,"target":target})
        entry = {"bufferView":view,"componentType":component_type,"count":len(values),"type":{1:"SCALAR",2:"VEC2",3:"VEC3",4:"VEC4"}[components]}
        if components == 3:
            entry.update(min=[min(row[i] for row in values) for i in range(3)], max=[max(row[i] for row in values) for i in range(3)])
        data["accessors"].append(entry)
        return len(data["accessors"])-1
    image_indices = {};texture_indices = {};used_extensions = set()
    def export_texture(texture):
        import hashlib
        image = texture["image"];sha = hashlib.sha256(image["bytes"]).hexdigest()
        if sha not in image_indices:
            while len(binary)%4:binary.append(0)
            offset=len(binary);binary.extend(image["bytes"])
            data["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":len(image["bytes"])})
            image_indices[sha]=len(data["images"])
            data["images"].append({"bufferView":len(data["bufferViews"])-1,"mimeType":image["mime"]})
        key=(sha,json.dumps(texture["sampler"],sort_keys=True))
        if key not in texture_indices:
            data["samplers"].append(texture["sampler"]);texture_indices[key]=len(data["textures"])
            data["textures"].append({"source":image_indices[sha],"sampler":len(data["samplers"])-1})
        return texture_indices[key]
    for mesh in scene_meshes(document, instant):
        position = accessor(mesh["vertices"], 3, 5126, 34962)
        attributes = {"POSITION":position}
        for field,name,size in (("normals","NORMAL",3),("tangents","TANGENT",4),("uv0","TEXCOORD_0",2),("uv1","TEXCOORD_1",2),("colors","COLOR_0",4)):
            if field in mesh:attributes[name]=accessor(mesh[field],size,5126,34962)
        indices = accessor([i for triangle in mesh["triangles"] for i in triangle], 1, 5125, 34963)
        material = len(data["materials"])
        if "material" in mesh:
            mat=deepcopy(mesh["material"])
            if mat.get("alphaMode", "OPAQUE") != "MASK":mat.pop("alphaCutoff", None)
            for owner in (mat,mat["pbrMetallicRoughness"]):
                for name,info in owner.items():
                    if name.endswith("Texture"):info["index"]=export_texture(mesh["textures"][info["index"]])
            used_extensions.update(mat.get("extensions",{}))
        else:
            rgb = [int(mesh["color"][i:i+2],16)/255 for i in (1,3,5)]
            mat={"pbrMetallicRoughness":{"baseColorFactor":rgb+[1],"metallicFactor":0,"roughnessFactor":1},"doubleSided":True}
        data["materials"].append(mat)
        data["meshes"].append({"name":mesh["name"],"primitives":[{"attributes":attributes,"indices":indices,"material":material,"mode":4}]})
        data["scenes"][0]["nodes"].append(len(data["nodes"]))
        data["nodes"].append({"name":mesh["name"],"mesh":len(data["meshes"])-1,"extras":{"vsc_object_id":mesh["id"]}})
    for original in document["cameras"]:
        camera,right,up,forward = camera_at(document,original["id"],instant)
        data["cameras"].append({"name":camera["name"],"type":"perspective","perspective":{
            "aspectRatio":document["width"]/document["height"],"yfov":math.radians(camera["fov"]),"znear":.05,"zfar":20000}})
        # glTF matrices are column-major and cameras look along local -Z.
        matrix = right+[0]+up+[0]+[-v for v in forward]+[0]+camera["position"]+[1]
        data["scenes"][0]["nodes"].append(len(data["nodes"]))
        data["nodes"].append({"name":camera["name"],"camera":len(data["cameras"])-1,"matrix":matrix})
    for name in ("images","textures","samplers"):
        if not data[name]:data.pop(name)
    if used_extensions:data["extensionsUsed"]=sorted(used_extensions)
    data["buffers"][0]["byteLength"] = len(binary)
    if not binary:
        for name in ("buffers", "bufferViews", "accessors", "meshes", "materials"):
            data.pop(name)
    encoded = json.dumps(data,ensure_ascii=False,separators=(",",":")).encode()
    encoded += b" "*((-len(encoded))%4)
    binary.extend(b"\0"*((-len(binary))%4))
    size=12+8+len(encoded)+(8+len(binary) if binary else 0)
    return struct.pack("<III",0x46546c67,2,size)+struct.pack("<II",len(encoded),0x4e4f534a)+encoded+(struct.pack("<II",len(binary),0x004e4942)+binary if binary else b"")


def export_animated_glb(document, camera_id, instant):
    """Keep mesh/skin/morph structure; export scene-time channels, never static poses."""
    from vsc.post.spatial_gltf import interpolate, MAX_BYTES
    def quaternion(right, up, back):
        m=[right,up,back];trace=sum(m[i][i] for i in range(3))
        if trace>0:
            w=math.sqrt(1+trace)*.5;v=[(m[1][2]-m[2][1])/(4*w),(m[2][0]-m[0][2])/(4*w),(m[0][1]-m[1][0])/(4*w),w]
        else:
            i=max(range(3),key=lambda j:m[j][j]);j=(i+1)%3;k=(i+2)%3;t=math.sqrt(1+m[i][i]-m[j][j]-m[k][k]);v=[0.,0.,0.,0.];v[i]=t*.5;v[j]=(m[i][j]+m[j][i])/(2*t);v[k]=(m[i][k]+m[k][i])/(2*t);v[3]=(m[j][k]-m[k][j])/(2*t)
        length=math.sqrt(sum(x*x for x in v));return [x/length for x in v]
    def rotation(angles):return quaternion(*[rotate(a,angles) for a in ([1,0,0],[0,1,0],[0,0,1])])
    local=deepcopy(document);local['objects']=[]
    for original in document['objects']:
        if original['kind']=='mesh' and original.get('_gltf'):continue
        item=deepcopy(original);item.update(position=[0,0,0],rotation=[0,0,0],scale=[1,1,1],keyframes=[]);local['objects'].append(item)
    raw=export_glb(local,camera_id,0);size=struct.unpack_from('<I',raw,12)[0];data=json.loads(raw[20:20+size]);binary=bytearray(raw[28+size:])
    for key in ('bufferViews','accessors','meshes','materials','textures','images','samplers','skins'):data.setdefault(key,[])
    animation={'name':'VSC scene timeline','channels':[],'samplers':[]};key_count=0
    def accessor(values,size,component=5126,target=None):
        while len(binary)%4:binary.append(0)
        start=len(binary);flat=[x for row in values for x in row] if size>1 else values
        binary.extend(struct.pack('<'+{5126:'f',5123:'H',5125:'I'}[component]*len(flat),*flat));view={'buffer':0,'byteOffset':start,'byteLength':len(binary)-start}
        if target:view['target']=target
        data['bufferViews'].append(view);entry={'bufferView':len(data['bufferViews'])-1,'componentType':component,'count':len(values),'type':{1:'SCALAR',2:'VEC2',3:'VEC3',4:'VEC4',16:'MAT4'}[size]}
        if size in (1,3):entry.update(min=[min(values)] if size==1 else [min(r[i] for r in values) for i in range(3)],max=[max(values)] if size==1 else [max(r[i] for r in values) for i in range(3)])
        data['accessors'].append(entry);return len(data['accessors'])-1
    def channel(node,path,times,values,interpolation='LINEAR'):
        nonlocal key_count
        key_count+=len(times)
        if key_count>32768 or len(animation['channels'])>=256:raise ResourceError('场景动画关键帧或通道超过导出上限，请缩短时间或减少对象','spatial_animation_limit')
        output=[v for row in values for v in row] if path=='weights' else values
        animation['samplers'].append({'input':accessor(times,1),'output':accessor(output,1 if path=='weights' else 4 if path=='rotation' else 3),'interpolation':interpolation})
        animation['channels'].append({'sampler':len(animation['samplers'])-1,'target':{'node':node,'path':path}})
    times=sorted({0.,float(document['duration']),*[min(document['duration'],i/24) for i in range(1,math.ceil(document['duration']*24))]})
    def object_transform(node,original):
        initial=sample(original,0);node.update(translation=initial['position'],rotation=rotation(initial['rotation']),scale=original['scale'])
        if original['keyframes']:
            index=data['nodes'].index(node);channel(index,'translation',times,[sample(original,t)['position'] for t in times]);channel(index,'rotation',times,[rotation(sample(original,t)['rotation']) for t in times])
    for node in data['nodes']:
        identity=node.get('extras',{}).get('vsc_object_id')
        if identity:object_transform(node,next(o for o in document['objects'] if o['id']==identity))
        if 'camera' in node:
            original=document['cameras'][node['camera']];camera,right,up,forward=camera_at(document,original['id'],0);node.pop('matrix',None);node.update(translation=camera['position'],rotation=quaternion(right,up,[-x for x in forward]))
            if original['keyframes']:
                index=data['nodes'].index(node);channel(index,'translation',times,[sample(original,t)['position'] for t in times]);channel(index,'rotation',times,[quaternion(right,up,[-x for x in forward]) for _,right,up,forward in [camera_at(document,original['id'],t) for t in times]])
    def texture(value):
        image=value['image'];offset=len(binary)
        while offset%4:binary.append(0);offset+=1
        binary.extend(image['bytes']);data['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(image['bytes'])});data['images'].append({'bufferView':len(data['bufferViews'])-1,'mimeType':image['mime']});data['samplers'].append(value['sampler']);data['textures'].append({'source':len(data['images'])-1,'sampler':len(data['samplers'])-1});return len(data['textures'])-1
    for original in document['objects']:
        model=original.get('_gltf')
        if not model or not original['visible']:continue
        parent=len(data['nodes']);node={'name':original['name'],'children':[],'extras':{'vsc_object_id':original['id']}};data['nodes'].append(node);data['scenes'][0]['nodes'].append(parent);object_transform(node,original)
        node_offset=len(data['nodes']);mesh_offset=len(data['meshes']);skin_offset=len(data['skins'])
        for mesh in model['meshes']:
            primitives=[]
            for primitive in mesh['primitives']:
                attrs={name:accessor(values,len(values[0]),5123 if name.startswith('JOINTS') else 5126,34962) for name,values in primitive['attributes'].items()}
                mat=deepcopy(primitive['material']);tint=[int(original['color'][i:i+2],16)/255 for i in (1,3,5)];pbr=mat['pbrMetallicRoughness'];pbr['baseColorFactor']=[v*t for v,t in zip(pbr['baseColorFactor'][:3],tint)]+pbr['baseColorFactor'][3:]
                for owner in (mat,pbr):
                    for name,info in owner.items():
                        if name.endswith('Texture'):info['index']=texture(primitive['textures'][info['index']])
                data['materials'].append(mat);value={'attributes':attrs,'indices':accessor([i for tri in primitive['triangles'] for i in tri],1,5125,34963),'material':len(data['materials'])-1,'mode':4}
                if primitive['targets']:value['targets']=[{name:accessor(rows,3,5126,34962) for name,rows in target.items()} for target in primitive['targets']]
                primitives.append(value)
            data['meshes'].append({'primitives':primitives,**({'weights':mesh['weights']} if mesh['weights'] else {})})
        for skin in model['skins']:data['skins'].append({'joints':[i+node_offset for i in skin['joints']],'inverseBindMatrices':accessor(skin['inverse'],16)})
        for source in model['nodes']:
            value={k:deepcopy(v) for k,v in source.items() if k in {'name','translation','rotation','scale','matrix','weights'}}
            if 'mesh' in source:value['mesh']=mesh_offset+source['mesh']
            if 'skin' in source:value['skin']=skin_offset+source['skin']
            if 'children' in source:value['children']=[i+node_offset for i in source['children']]
            data['nodes'].append(value)
        node['children']=[i+node_offset for i in model['scenes'][original['geometry']['scene']]['nodes']]
        config=original['animation'];clip=config['clip']
        if clip is not None:
            source=model['animations'][clip];duration=source['duration']
            def source_time(t):
                value=max(0,t*config['speed']+config['offset']);return value%duration if config['loop'] and duration else min(value,duration)
            for c in source['channels']:
                index=node_offset+c['node'];values=[interpolate(c,source_time(t)) for t in times];data['nodes'][index][c['path']]=values[0];channel(index,c['path'],times,values,'STEP' if c['interpolation']=='STEP' else 'LINEAR')
    if len(data['nodes'])>256 or len(data['meshes'])>64:raise ResourceError('组合场景超过GLB的256节点或64网格上限，请拆分后导出','spatial_animation_limit')
    data['extras'].update(animation_baked=False,source_time_seconds=instant,bake_description='Editable transforms, skins and morph targets; timeline sampled at 24 fps',duration_seconds=document['duration'])
    if animation['channels']:data['animations']=[animation]
    for key in ('textures','images','samplers','skins'):
        if not data[key]:data.pop(key)
    data['buffers']=[{'byteLength':len(binary)}];encoded=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4);binary.extend(b'\0'*((-len(binary))%4));size=28+len(encoded)+len(binary)
    if size>MAX_BYTES:raise ResourceError('动画GLB超过20MiB，请减少几何或时间','spatial_animation_limit')
    return struct.pack('<III',0x46546c67,2,size)+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary


def import_glb(raw):
    """Decode a GLB for transient sampling; persisted scenes reference its media."""
    from vsc.post.spatial_gltf import decode_glb
    return decode_glb(raw)


class SpatialExporter:
    def __init__(self, service):
        self.service,self.store=service,service.store

    def run(self, project_id, export_id):
        if self.service.storage is None:
            raise ResourceError("未配置受控媒体存储", "storage_unavailable")
        claimed=self.store.claim_spatial_export(project_id,export_id)
        if claimed.get("status")!="running" or not claimed.get("claim_token"):
            return claimed
        token=claimed["claim_token"]
        try:
            scene=self.store.get_spatial_scene(project_id,claimed["scene_id"],claimed["scene_version"])
            document=self.service.prepare_spatial_scene(project_id,scene["document"])
            with tempfile.TemporaryDirectory(prefix="vsc-spatial-") as directory:
                suffix=claimed["format"]
                path=Path(directory)/('preview.'+suffix)
                if suffix=="png":
                    path.write_bytes(render_png(document,claimed["camera_id"],claimed["time"]))
                elif suffix=="glb":
                    path.write_bytes(export_glb(document,claimed["camera_id"],claimed["time"],animated=True))
                else:
                    ffmpeg=shutil.which("ffmpeg")
                    if not ffmpeg:raise ResourceError("未找到 FFmpeg", "spatial_encoder_missing")
                    if sum(len(m["triangles"]) for m in scene_meshes(document,claimed["time"]))>6000:
                        raise ResourceError("当前有界视频导出最多 6000 三角面；请简化模型", "spatial_render_limit")
                    count=claimed["total_frames"]
                    if count*document["width"]*document["height"]>64000000:
                        raise ResourceError("视频导出累计画幅超过 6400 万像素预算；请缩短时长或缩小画幅", "spatial_render_limit")
                    for frame in range(count):
                        if not self.store.progress_spatial_export(project_id,export_id,token,frame):
                            return self.store.get_spatial_export(project_id,export_id)
                        instant=claimed["time"]+frame/claimed["fps"]
                        (Path(directory)/('%05d.png'%frame)).write_bytes(render_png(document,claimed["camera_id"],instant))
                    command=[ffmpeg,"-hide_banner","-loglevel","error","-y","-framerate",str(claimed["fps"]),"-i",str(Path(directory)/"%05d.png"),
                        "-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(path)]
                    subprocess.run(command,check=True,capture_output=True,timeout=90)
                if not self.store.progress_spatial_export(project_id,export_id,token,claimed["total_frames"]):
                    return self.store.get_spatial_export(project_id,export_id)
                with path.open('rb') as stream:
                    staged=self.service.storage.stage_upload(stream,path.name)
                verified=self.service.storage.commit_upload(staged["staged_upload"])
                return self.store.finish_spatial_export(project_id,export_id,token,verified)
        except Exception as error:
            code=error.code if isinstance(error,ResourceError) else "spatial_export_failed"
            self.store.fail_spatial_export(project_id,export_id,token,code)
            if isinstance(error,ResourceError):raise
            raise ResourceError("导出失败，原场景与旧输出已保留；可从原记录重试",code) from error
