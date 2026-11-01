"""Synthetic embedded texture + two-joint animated model, no external assets."""
import io
import json
import struct
from PIL import Image


def animated_glb(change=None):
    data={"asset":{"version":"2.0"},"scene":0,"scenes":[{"name":"合成舞台","nodes":[0,1]}],"nodes":[{"name":"蒙皮色板","mesh":0,"skin":0,"translation":[10,0,0]},{"name":"根关节","children":[2]},{"name":"转动关节","translation":[1,0,0]}],"meshes":[],"skins":[],"animations":[],"materials":[{"pbrMetallicRoughness":{"baseColorFactor":[1,1,1,1],"baseColorTexture":{"index":0},"metallicFactor":0,"roughnessFactor":1},"doubleSided":True,"extensions":{"KHR_materials_unlit":{}}}],"extensionsUsed":["KHR_materials_unlit"],"textures":[{"source":0,"sampler":0}],"samplers":[{"magFilter":9728,"minFilter":9728,"wrapS":33071,"wrapT":33071}],"images":[],"bufferViews":[],"accessors":[],"buffers":[{}]}
    binary=bytearray()
    def view(raw):
        while len(binary)%4:binary.append(0)
        offset=len(binary);binary.extend(raw);data['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(raw)});return len(data['bufferViews'])-1
    def accessor(values,kind,component=5126):
        size={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[kind];flat=[v for row in values for v in row] if size>1 else values
        fmt={5126:'f',5123:'H',5121:'B'}[component];vi=view(struct.pack('<'+fmt*len(flat),*flat));a={'bufferView':vi,'componentType':component,'count':len(values),'type':kind}
        if kind=='SCALAR':a.update(min=[min(values)],max=[max(values)])
        if kind=='VEC3':a.update(min=[min(r[i] for r in values) for i in range(3)],max=[max(r[i] for r in values) for i in range(3)])
        data['accessors'].append(a);return len(data['accessors'])-1
    positions=accessor([[-1,0,0],[1,0,0],[1,2,0],[-1,2,0]],'VEC3');normals=accessor([[0,0,1]]*4,'VEC3');uv=accessor([[0,1],[1,1],[1,0],[0,0]],'VEC2')
    joints=accessor([[0,0,0,0],[1,0,0,0],[1,0,0,0],[0,0,0,0]],'VEC4',5123);weights=accessor([[1,0,0,0]]*4,'VEC4');indices=accessor([0,1,2,0,2,3],'SCALAR',5123)
    target=accessor([[0,0,0],[0,0,0],[0,0,.8],[0,0,.8]],'VEC3')
    data['meshes']=[{'primitives':[{'attributes':{'POSITION':positions,'NORMAL':normals,'TEXCOORD_0':uv,'JOINTS_0':joints,'WEIGHTS_0':weights},'indices':indices,'material':0,'targets':[{'POSITION':target}]}],'weights':[0]}]
    identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];ibm=identity[:];ibm[12]=-1
    data['skins']=[{'joints':[1,2],'inverseBindMatrices':accessor([identity,ibm],'MAT4')}]
    times=accessor([0,1],'SCALAR')
    for name,path,node,values,kind,mode in [('摆动','rotation',2,[[0,0,0,1],[0,0,2**-.5,2**-.5]],'VEC4','LINEAR'),('阶跃','translation',1,[[0,0,0],[0,1,0]],'VEC3','STEP'),('曲线','translation',2,[[0,0,0],[1,0,0],[0,0,0],[0,0,0],[2,0,0],[0,0,0]],'VEC3','CUBICSPLINE'),('形变','weights',0,[0,1],'SCALAR','LINEAR')]:
        data['animations'].append({'name':name,'samplers':[{'input':times,'output':accessor(values,kind),'interpolation':mode}],'channels':[{'sampler':0,'target':{'node':node,'path':path}}]})
    image=Image.new('RGBA',(4,4));image.putdata([(255,0,0,255) if x<2 and y<2 else (0,255,0,255) if x>=2 and y<2 else (0,0,255,255) if x<2 else (255,255,0,255) for y in range(4) for x in range(4)])
    output=io.BytesIO();image.save(output,format='PNG');data['images']=[{'bufferView':view(output.getvalue()),'mimeType':'image/png'}]
    data['buffers'][0]['byteLength']=len(binary)
    if change:change(data,binary)
    encoded=json.dumps(data,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4);binary.extend(b'\0'*((-len(binary))%4))
    return struct.pack('<III',0x46546c67,2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
