"""Bounded, local glTF 2.0 decoding and animation; no URI or plugin execution.

Scene documents hold original media ID + SHA, never these decoded structures.
Matrices are column-major. Skin positions use jointWorld * inverseBind directly
in model world space, so the mesh node transform is not applied a second time.
"""
from bisect import bisect_right
from copy import deepcopy
import io
import json
import math
import struct

from vsc.assets.resource_service import ResourceError

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
MAX_BYTES = 20 * 1024 * 1024


def fail(message):
    raise ResourceError(message, "invalid_spatial_glb")


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail("GLB 索引或数量越界")
    return value


def finite(value, low=-1e6, high=1e6):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        fail("GLB 数值不是范围内的有限数")
    return float(value)


def vector(value, size, low=-1e6, high=1e6):
    if not isinstance(value, list) or len(value) != size:
        fail("GLB 向量维度错误")
    return [finite(x, low, high) for x in value]


def multiply(a, b):
    return [sum(a[k*4+r]*b[c*4+k] for k in range(4)) for c in range(4) for r in range(4)]


def point(matrix, xyz, w=1):
    return [sum(matrix[c*4+r]*xyz[c] for c in range(3))+matrix[12+r]*w for r in range(3)]


def normalized(q):
    length = math.sqrt(sum(x*x for x in q))
    if length < 1e-10:
        fail("GLB 旋转四元数不能为零")
    return [x/length for x in q]


def matrix(node):
    if "matrix" in node:
        return node["matrix"]
    x, y, z, w = normalized(node.get("rotation", [0, 0, 0, 1]))
    sx, sy, sz = node.get("scale", [1, 1, 1])
    return [(1-2*(y*y+z*z))*sx, 2*(x*y+z*w)*sx, 2*(x*z-y*w)*sx, 0,
            2*(x*y-z*w)*sy, (1-2*(x*x+z*z))*sy, 2*(y*z+x*w)*sy, 0,
            2*(x*z+y*w)*sz, 2*(y*z-x*w)*sz, (1-2*(x*x+y*y))*sz, 0,
            *node.get("translation", [0, 0, 0]), 1]


def normal(matrix, xyz):
    # Inverse-transpose of the affine linear part; cofactor form avoids a full
    # inverse per vertex. Degenerate animated scales produce no useful normal.
    a,b,c = matrix[0:3], matrix[4:7], matrix[8:11]
    def cross(u,v): return [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    cof = [cross(b,c),cross(c,a),cross(a,b)]
    determinant = sum(a[i]*cof[0][i] for i in range(3))
    if abs(determinant) < 1e-12:
        return [0., 1., 0.]
    out = [sum(cof[j][i]*xyz[j] for j in range(3))/determinant for i in range(3)]
    length = math.sqrt(sum(x*x for x in out))
    return [x/length for x in out] if length > 1e-12 else [0.,1.,0.]


def decode_glb(raw):
    try:
        return _decode(raw)
    except ResourceError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, AttributeError,
            struct.error, RecursionError, OSError) as error:
        raise ResourceError("GLB 结构、图像或数值无效", "invalid_spatial_glb") from error


def _decode(raw):
    if not isinstance(raw, bytes) or not 20 <= len(raw) <= MAX_BYTES:
        fail("GLB 文件须为 20 MiB 以内的二进制 glTF 2.0")
    if struct.unpack_from("<III",raw) != (0x46546c67,2,len(raw)):
        fail("GLB 文件头或长度不正确")
    offset, chunks = 12, []
    while offset < len(raw):
        size, kind = struct.unpack_from("<II",raw,offset);offset += 8
        if size % 4 or offset+size > len(raw):fail("GLB 数据块越界")
        chunks.append((kind,raw[offset:offset+size]));offset += size
    if len(chunks)!=2 or [x[0] for x in chunks]!=[0x4e4f534a,0x004e4942]:
        fail("GLB 需要一个 JSON 块和一个内嵌二进制块")
    doc=json.loads(chunks[0][1]);binary=chunks[1][1]
    if doc["asset"]["version"]!="2.0" or doc["asset"].get("minVersion","2.0")!="2.0":fail("仅支持 glTF 2.0")
    allowed_extensions={"KHR_materials_unlit"}
    if set(doc.get("extensionsUsed",[])) - allowed_extensions or set(doc.get("extensionsRequired",[])) - allowed_extensions:
        fail("GLB 压缩或其他扩展尚未支持；请导出未压缩核心 glTF 2.0")
    def inspect(value,depth=0):
        if depth>40:fail("GLB JSON 嵌套过深")
        if isinstance(value,dict):
            if "uri" in value:fail("GLB 仅接受内嵌 bufferView 图像，不读取 URI 或外部文件")
            if set(value.get("extensions",{}))-allowed_extensions:fail("GLB 包含未支持扩展")
            for child in value.values():inspect(child,depth+1)
        elif isinstance(value,list):
            for child in value:inspect(child,depth+1)
    inspect(doc)
    if len(doc["buffers"])!=1:fail("GLB 仅接受单个内嵌 buffer")
    length=integer(doc["buffers"][0]["byteLength"],1,len(binary))
    if len(binary)-length>3:fail("GLB 二进制填充长度不正确")
    binary=binary[:length]
    views=doc.get("bufferViews",[]);accessors=doc.get("accessors",[])
    if len(views)>4096 or len(accessors)>2048:fail("GLB 数据分块过多")
    def view(index):
        v=views[integer(index,0,len(views)-1)]
        if v.get("buffer")!=0:fail("GLB bufferView 指向非内嵌 buffer")
        start=integer(v.get("byteOffset",0),0,length);size=integer(v["byteLength"],1,length)
        if start+size>length:fail("GLB bufferView 越界")
        return v,start,size
    decoded={};components_read=0
    formats={5120:("b",1,127),5121:("B",1,255),5122:("h",2,32767),5123:("H",2,65535),5125:("I",4,4294967295),5126:("f",4,None)}
    dimensions={"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}
    def read(index,expected=None):
        nonlocal components_read
        a=accessors[integer(index,0,len(accessors)-1)]
        if expected and a["type"]!=expected:fail("GLB accessor 类型与用途不符")
        if index in decoded:return decoded[index]
        dim=dimensions[a["type"]];fmt,size,denominator=formats[a["componentType"]]
        count=integer(a["count"],1,72000);components_read+=count*dim
        if components_read>1000000:fail("GLB 解码数据超过预算")
        norm=a.get("normalized",False)
        if type(norm) is not bool or norm and a["componentType"] in (5125,5126):fail("GLB normalized 类型不正确")
        if a["type"]=="MAT4" and a["componentType"]!=5126:fail("逆绑定矩阵需要浮点 MAT4")
        def unpack(v_index,relative,n,packed=False):
            v,start,span=view(v_index);relative=integer(relative,0,span)
            stride=dim*size if packed else v.get("byteStride",dim*size)
            integer(stride,dim*size,252 if "byteStride" in v and not packed else dim*size)
            if relative%size or (start+relative)%size or stride%size or relative+(n-1)*stride+dim*size>span:
                fail("GLB accessor 对齐、步长或边界不正确")
            return [list(struct.unpack_from("<"+fmt*dim,binary,start+relative+i*stride)) for i in range(n)]
        values=unpack(a["bufferView"],a.get("byteOffset",0),count) if "bufferView" in a else [[0]*dim for _ in range(count)]
        if "sparse" in a:
            sparse=a["sparse"];n=integer(sparse["count"],1,count);indices=sparse["indices"]
            if indices["componentType"] not in (5121,5123,5125):fail("稀疏索引类型不正确")
            f,s,_=formats[indices["componentType"]];v,start,span=view(indices["bufferView"])
            off=integer(indices.get("byteOffset",0),0,span)
            if "byteStride" in v or off+n*s>span or (off+start)%s:fail("稀疏索引边界不正确")
            ids=struct.unpack_from("<"+f*n,binary,start+off)
            if any(i>=count for i in ids) or any(a>=b for a,b in zip(ids,ids[1:])):fail("稀疏索引必须递增且不越界")
            for i,val in zip(ids,unpack(sparse["values"]["bufferView"],sparse["values"].get("byteOffset",0),n,True)):values[i]=val
        if norm:values=[[max(-1,x/denominator) for x in row] for row in values]
        if any(not math.isfinite(x) or abs(x)>1e8 for row in values for x in row):fail("GLB accessor 包含无效数值")
        decoded[index]=values
        return values
    def typed(index,expected,allowed,normalized_required=False):
        a=accessors[integer(index,0,len(accessors)-1)]
        if a["componentType"] not in allowed or normalized_required and a["componentType"]!=5126 and not a.get("normalized"):
            fail("GLB 顶点属性的分量类型不正确")
        return read(index,expected)
    # Decode images once per prepared scene; dimensions checked before decoding.
    from PIL import Image
    images=[];pixel_count=0
    if len(doc.get("images",[]))>16 or len(doc.get("textures",[]))>32:fail("GLB 最多 16 张内嵌图像、32 个纹理")
    for source in doc.get("images",[]):
        mime=source.get("mimeType")
        if mime not in ("image/png","image/jpeg"):fail("GLB 纹理只支持内嵌 PNG/JPEG")
        v,start,span=view(source["bufferView"])
        if "byteStride" in v:fail("GLB 图像不能使用交错步长")
        content=binary[start:start+span]
        try:image=Image.open(io.BytesIO(content))
        except Image.DecompressionBombError:fail("GLB 图像解码尺寸超过预算")
        w,h=image.size;pixel_count+=w*h
        if max(w,h)>2048 or pixel_count>4*1024*1024 or image.format!={"image/png":"PNG","image/jpeg":"JPEG"}[mime]:
            fail("GLB 纹理单边最多 2048，解码像素累计最多 4 Mi")
        image.load();rgba=image.convert("RGBA");levels=[]
        while True:
            levels.append((*rgba.size,rgba.tobytes()))
            if rgba.size==(1,1):break
            rgba=rgba.resize((max(1,rgba.width//2),max(1,rgba.height//2)),Image.Resampling.BOX)
        images.append({"bytes":content,"mime":mime,"size":(w,h),"levels":levels})
    textures=[]
    for texture in doc.get("textures",[]):
        source=integer(texture["source"],0,len(images)-1)
        sampler=doc.get("samplers",[])[integer(texture["sampler"],0,len(doc.get("samplers",[]))-1)] if "sampler" in texture else {}
        for name in ("wrapS","wrapT"):
            if sampler.get(name,10497) not in (10497,33071,33648):fail("GLB 纹理包裹模式无效")
        if sampler.get("magFilter",9729) not in (9728,9729) or sampler.get("minFilter",9987) not in (9728,9729,9984,9985,9986,9987):fail("GLB 采样器无效")
        textures.append({"image":images[source],"sampler":deepcopy(sampler)})
    materials=[]
    for original in doc.get("materials",[{}]):
        m=deepcopy(original);p=m.setdefault("pbrMetallicRoughness",{})
        p["baseColorFactor"]=vector(p.get("baseColorFactor",[1,1,1,1]),4,0,1)
        p["metallicFactor"]=finite(p.get("metallicFactor",1),0,1);p["roughnessFactor"]=finite(p.get("roughnessFactor",1),0,1)
        m["emissiveFactor"]=vector(m.get("emissiveFactor",[0,0,0]),3,0,1)
        if m.get("alphaMode","OPAQUE") not in ("OPAQUE","MASK","BLEND") or type(m.get("doubleSided",False)) is not bool:fail("GLB 材质覆盖模式无效")
        m["alphaCutoff"]=finite(m.get("alphaCutoff",.5),0,1)
        for owner,name in ((p,"baseColorTexture"),(p,"metallicRoughnessTexture"),(m,"normalTexture"),(m,"occlusionTexture"),(m,"emissiveTexture")):
            if name in owner:
                info=owner[name];integer(info["index"],0,len(textures)-1);integer(info.get("texCoord",0),0,1)
                if name=="normalTexture":info["scale"]=finite(info.get("scale",1),0,10)
                if name=="occlusionTexture":info["strength"]=finite(info.get("strength",1),0,1)
        materials.append(m)
    if len(materials)>128:fail("GLB 材质数量超过 128")
    default_material={"pbrMetallicRoughness":{"baseColorFactor":[1,1,1,1],"metallicFactor":1,"roughnessFactor":1},"emissiveFactor":[0,0,0]}
    meshes=[];vertices=faces=0
    for mesh in doc.get("meshes",[]):
        primitives=[]
        for primitive in mesh["primitives"]:
            attrs=primitive["attributes"]
            allowed={"POSITION","NORMAL","TANGENT","TEXCOORD_0","TEXCOORD_1","COLOR_0","JOINTS_0","WEIGHTS_0","JOINTS_1","WEIGHTS_1"}
            if set(attrs)-allowed:fail("GLB 包含未支持的顶点属性（支持两组 UV、八个骨骼影响）")
            points=typed(attrs["POSITION"],"VEC3",{5126});n=len(points)
            if n>6000:fail("GLB 单网格最多 6000 顶点")
            attributes={"POSITION":points}
            for name,index in attrs.items():
                if name=="POSITION":continue
                if name in ("NORMAL","TANGENT"):val=typed(index,"VEC3" if name=="NORMAL" else "VEC4",{5126})
                elif name.startswith("JOINTS"):val=typed(index,"VEC4",{5121,5123})
                elif name=="COLOR_0":
                    if accessors[index]["type"] not in ("VEC3","VEC4"):fail("顶点颜色维度错误")
                    val=typed(index,None,{5126,5121,5123},True)
                    val=[row+[1] if len(row)==3 else row for row in val]
                else:val=typed(index,"VEC2" if name.startswith("TEXCOORD") else "VEC4",{5126,5121,5123},True)
                if len(val)!=n:fail("GLB 顶点属性数量不一致")
                if name.startswith(("WEIGHTS","COLOR")) and any(not 0<=v<=1 for row in val for v in row):fail("GLB 权重或颜色超出范围")
                attributes[name]=val
            for group in (0,1):
                if (f"JOINTS_{group}" in attributes)!=(f"WEIGHTS_{group}" in attributes):fail("GLB 骨骼与权重须配对")
            indices=[x[0] for x in typed(primitive["indices"],"SCALAR",{5121,5123,5125})] if "indices" in primitive else list(range(n))
            if any(type(i) is not int or not 0<=i<n for i in indices):fail("GLB 三角索引越界")
            mode=primitive.get("mode",4)
            if mode==4:
                if len(indices)%3:fail("GLB 三角索引数量不是 3 的倍数")
                triangles=[indices[i:i+3] for i in range(0,len(indices),3)]
            elif mode==5:triangles=[[indices[i+1],indices[i],indices[i+2]] if i%2 else indices[i:i+3] for i in range(len(indices)-2)]
            elif mode==6:triangles=[[indices[0],indices[i],indices[i+1]] for i in range(1,len(indices)-1)]
            else:fail("GLB 只渲染三角形、三角带与三角扇；点线请先转网格")
            material=materials[integer(primitive["material"],0,len(materials)-1)] if "material" in primitive else default_material
            for owner in (material,material["pbrMetallicRoughness"]):
                for name,info in owner.items():
                    if name.endswith("Texture") and "TEXCOORD_"+str(info.get("texCoord",0)) not in attributes:fail("GLB 材质需要的 UV 属性不存在")
            targets=[]
            for target in primitive.get("targets",[]):
                if set(target)-{"POSITION","NORMAL","TANGENT"}:fail("GLB 形变目标属性无效")
                values={name:typed(index,"VEC3",{5126}) for name,index in target.items()}
                if any(len(v)!=n for v in values.values()):fail("GLB 形变目标顶点数量不一致")
                targets.append(values)
            if len(targets)>8:fail("GLB 最多 8 个形变目标")
            vertices+=n;faces+=len(triangles)
            if vertices>12000 or faces>24000:fail("GLB 累计最多 12000 顶点、24000 三角形")
            primitives.append({"attributes":attributes,"triangles":triangles,"material":material,"textures":textures,"targets":targets})
        if not primitives or len(primitives)>64:fail("GLB 网格图元数量无效")
        target_count=len(primitives[0]["targets"])
        if any(len(p["targets"])!=target_count for p in primitives):fail("同一网格的形变目标数量必须相同")
        weights=vector(mesh.get("weights",[0]*target_count),target_count)
        meshes.append({"primitives":primitives,"weights":weights})
    nodes=deepcopy(doc.get("nodes",[]));parents={}
    if not 1<=len(nodes)<=256 or len(meshes)>64:fail("GLB 最多 256 节点、64 网格")
    for i,node in enumerate(nodes):
        if "matrix" in node:
            if set(node)&{"translation","rotation","scale"}:fail("GLB 节点不能同时指定 matrix 与 TRS")
            node["matrix"]=vector(node["matrix"],16)
            if [node["matrix"][j] for j in (3,7,11,15)]!=[0,0,0,1]:fail("GLB 节点矩阵必须为仿射变换")
        else:
            for name,default in (("translation",[0,0,0]),("rotation",[0,0,0,1]),("scale",[1,1,1])):node[name]=vector(node.get(name,default),len(default))
            if abs(sum(x*x for x in node["rotation"])-1)>1e-3:fail("GLB 旋转四元数需要归一化")
        if "mesh" in node:
            mesh=meshes[integer(node["mesh"],0,len(meshes)-1)]
            node["weights"]=vector(node.get("weights",mesh["weights"]),len(mesh["weights"]))
        for child in node.get("children",[]):
            integer(child,0,len(nodes)-1)
            if child==i or child in parents:fail("GLB 节点循环或有多个父节点")
            parents[child]=i
    for i in range(len(nodes)):
        seen=set();j=i
        while j in parents:
            if j in seen or len(seen)>32:fail("GLB 节点循环或层级过深")
            seen.add(j);j=parents[j]
    scenes=doc.get("scenes",[])
    if not 1<=len(scenes)<=16:fail("GLB 需要 1–16 个场景")
    for scene in scenes:
        roots=scene.get("nodes",[])
        if len(set(roots))!=len(roots):fail("GLB 场景根节点重复")
        for index in roots:
            integer(index,0,len(nodes)-1)
            if index in parents:fail("GLB 场景只能引用根节点")
    default_scene=integer(doc.get("scene",0),0,len(scenes)-1)
    skins=[]
    for skin in doc.get("skins",[]):
        joints=skin["joints"]
        if not 1<=len(joints)<=128 or len(set(joints))!=len(joints):fail("GLB skin 最多 128 个不重复关节")
        for joint in joints:integer(joint,0,len(nodes)-1)
        ibm=typed(skin["inverseBindMatrices"],"MAT4",{5126}) if "inverseBindMatrices" in skin else [IDENTITY]*len(joints)
        if len(ibm)!=len(joints):fail("GLB inverseBindMatrices 与关节数量不一致")
        if any([m[j] for j in (3,7,11,15)]!=[0,0,0,1] for m in ibm):fail("GLB 逆绑定矩阵必须为仿射变换")
        skins.append({"joints":joints,"inverse":ibm})
    for node in nodes:
        if "skin" in node:
            skin=skins[integer(node["skin"],0,len(skins)-1)]
            for primitive in meshes[node["mesh"]]["primitives"]:
                a=primitive["attributes"]
                if "JOINTS_0" not in a:fail("GLB 蒙皮网格缺少 JOINTS/WEIGHTS")
                for group in (0,1):
                    if f"JOINTS_{group}" in a and any(type(x) is not int or x>=len(skin["joints"]) for row in a[f"JOINTS_{group}"] for x in row):fail("GLB 关节索引越界")
                for i in range(len(a["POSITION"])):
                    total=sum(sum(a[f"WEIGHTS_{g}"][i]) for g in (0,1) if f"WEIGHTS_{g}" in a)
                    if total<1e-8:fail("GLB 蒙皮顶点权重不能全为零")
    animations=[];key_count=0
    if len(doc.get("animations",[]))>16:fail("GLB 最多 16 个动画")
    for i,animation in enumerate(doc.get("animations",[])):
        channels=[];targets=set();end=0
        if not 1<=len(animation["channels"])<=256:fail("GLB 动画通道数量超过限制")
        for channel in animation["channels"]:
            target=channel["target"]
            if "node" not in target:continue
            ni=integer(target["node"],0,len(nodes)-1);path=target["path"];node=nodes[ni]
            if path not in ("translation","rotation","scale","weights") or "matrix" in node or (ni,path) in targets:fail("GLB 动画通道目标无效或重复")
            targets.add((ni,path));sampler=animation["samplers"][integer(channel["sampler"],0,len(animation["samplers"])-1)]
            times=[row[0] for row in typed(sampler["input"],"SCALAR",{5126})]
            if times[0]<0 or times[-1]>3600 or any(a>=b for a,b in zip(times,times[1:])):fail("GLB 动画时刻必须严格递增，最长 3600 秒")
            key_count+=len(times)
            if len(times)>4096 or key_count>32768:fail("GLB 动画关键帧超过预算")
            interpolation=sampler.get("interpolation","LINEAR")
            if interpolation not in ("LINEAR","STEP","CUBICSPLINE") or interpolation=="CUBICSPLINE" and len(times)<2:fail("GLB 动画插值方式无效")
            size=len(node.get("weights",[])) if path=="weights" else 4 if path=="rotation" else 3
            if not size:fail("GLB weights 动画需要形变目标")
            values=typed(sampler["output"],"SCALAR" if path=="weights" else "VEC4" if path=="rotation" else "VEC3",{5126,5120,5121,5122,5123} if path in ("weights","rotation") else {5126},True)
            if path=="weights":
                flat=[row[0] for row in values];values=[flat[j:j+size] for j in range(0,len(flat),size)]
            if len(values)!=len(times)*(3 if interpolation=="CUBICSPLINE" else 1) or any(len(row)!=size for row in values):fail("GLB 动画输出数量不匹配")
            if path=="rotation":
                rotations=values[1::3] if interpolation=="CUBICSPLINE" else values
                if any(abs(sum(v*v for v in row)-1)>1e-3 for row in rotations):fail("GLB 动画旋转需要单位四元数")
            channels.append({"node":ni,"path":path,"times":times,"values":values,"interpolation":interpolation});end=max(end,times[-1])
        animations.append({"name":str(animation.get("name",f"动画 {i+1}"))[:200],"duration":end,"channels":channels})
    model={"nodes":nodes,"parents":parents,"meshes":meshes,"scenes":scenes,"scene":default_scene,"skins":skins,"animations":animations,"pixel_count":pixel_count}
    # Validate instantiated counts, not only shared mesh arrays.
    for scene in range(len(scenes)):
        sampled=sample_model(model,scene,None,0)
        if sum(len(m["vertices"]) for m in sampled)>12000 or sum(len(m["triangles"]) for m in sampled)>24000:fail("GLB 场景实例化几何超过预算")
    return model


def interpolate(channel, instant):
    times,values,mode=channel["times"],channel["values"],channel["interpolation"]
    index=max(0,min(len(times)-1,bisect_right(times,instant)-1));factor=3 if mode=="CUBICSPLINE" else 1
    a=values[index*factor+(1 if factor==3 else 0)]
    if index==len(times)-1 or instant<=times[0] or mode=="STEP":return a[:]
    dt=times[index+1]-times[index];u=(instant-times[index])/dt;b=values[(index+1)*factor+(1 if factor==3 else 0)]
    if mode=="CUBICSPLINE":
        out=[(2*u**3-3*u*u+1)*x+(u**3-2*u*u+u)*dt*ta+(-2*u**3+3*u*u)*y+(u**3-u*u)*dt*tb for x,y,ta,tb in zip(a,b,values[index*3+2],values[(index+1)*3])]
    elif channel["path"]=="rotation":
        a,b=normalized(a),normalized(b);cosine=sum(x*y for x,y in zip(a,b))
        if cosine<0:b=[-x for x in b];cosine=-cosine
        if cosine>.9995:out=[x+(y-x)*u for x,y in zip(a,b)]
        else:
            angle=math.acos(max(-1,min(1,cosine)));sine=math.sin(angle)
            out=[(x*math.sin((1-u)*angle)+y*math.sin(u*angle))/sine for x,y in zip(a,b)]
    else:out=[x+(y-x)*u for x,y in zip(a,b)]
    return normalized(out) if channel["path"]=="rotation" else out


def sample_model(model, scene, clip, instant):
    integer(scene,0,len(model["scenes"])-1)
    nodes=[dict(node) for node in model["nodes"]]
    if clip is not None:
        animation=model["animations"][integer(clip,0,len(model["animations"])-1)]
        for channel in animation["channels"]:nodes[channel["node"]][channel["path"]]=interpolate(channel,instant)
    world={}
    def world_at(i):
        if i not in world:
            local=matrix(nodes[i]);parent=model["parents"].get(i)
            world[i]=multiply(world_at(parent),local) if parent is not None else local
        return world[i]
    result=[]
    def visit(ni):
        node=nodes[ni];transform=world_at(ni)
        if "mesh" in node:
            skin=model["skins"][node["skin"]] if "skin" in node else None
            matrices=[multiply(world_at(j),ibm) for j,ibm in zip(skin["joints"],skin["inverse"])] if skin else None
            for pi,primitive in enumerate(model["meshes"][node["mesh"]]["primitives"]):
                attrs=primitive["attributes"];positions=[];normals=[];tangents=[]
                for vi,source in enumerate(attrs["POSITION"]):
                    position=source[:];n=attrs.get("NORMAL",[]);n=n[vi][:] if n else None;t=attrs.get("TANGENT",[]);t=t[vi][:] if t else None
                    for weight,target in zip(node.get("weights",[]),primitive["targets"]):
                        if "POSITION" in target:position=[v+weight*d for v,d in zip(position,target["POSITION"][vi])]
                        if n and "NORMAL" in target:n=[v+weight*d for v,d in zip(n,target["NORMAL"][vi])]
                        if t and "TANGENT" in target:t=[v+weight*d for v,d in zip(t[:3],target["TANGENT"][vi])]+[t[3]]
                    vertex_matrix=transform
                    if skin:
                        pairs=[(j,w) for g in (0,1) if f"JOINTS_{g}" in attrs for j,w in zip(attrs[f"JOINTS_{g}"][vi],attrs[f"WEIGHTS_{g}"][vi])]
                        total=sum(w for _,w in pairs)
                        vertex_matrix=[sum(matrices[j][k]*w/total for j,w in pairs) for k in range(16)]
                    positions.append(point(vertex_matrix,position))
                    if n:normals.append(normal(vertex_matrix,n))
                    if t:
                        tangent=point(vertex_matrix,t[:3],0);size=math.sqrt(sum(x*x for x in tangent))
                        tangents.append([x/size for x in tangent]+[t[3]] if size else [1,0,0,t[3]])
                triangles=primitive["triangles"]
                # Preserve front-face orientation when baking mirrored nodes.
                determinant=transform[0]*(transform[5]*transform[10]-transform[9]*transform[6])-transform[4]*(transform[1]*transform[10]-transform[9]*transform[2])+transform[8]*(transform[1]*transform[6]-transform[5]*transform[2])
                if not skin and determinant<0:triangles=[[t[0],t[2],t[1]] for t in triangles]
                row={"name":str(node.get("name",f"网格 {ni+1}"))[:200],"id":f"{ni}-{pi}","vertices":positions,"triangles":triangles,"material":primitive["material"],"textures":primitive["textures"]}
                if normals:row["normals"]=normals
                if tangents:row["tangents"]=tangents
                for name,field in (("TEXCOORD_0","uv0"),("TEXCOORD_1","uv1"),("COLOR_0","colors")):
                    if name in attrs:row[field]=attrs[name]
                result.append(row)
        for child in node.get("children",[]):visit(child)
    for root in model["scenes"][scene].get("nodes",[]):visit(root)
    return result
