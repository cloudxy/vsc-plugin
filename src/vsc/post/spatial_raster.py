"""CPU rasterization of sampled glTF meshes for the shared PNG/video path.

Metallic/roughness lighting is a bounded preview, with texture/normal/occlusion/
emissive inputs and alpha coverage. It is not a ray-traced DCC renderer.
"""
from array import array
import io
import math

from PIL import Image
from vsc.assets.resource_service import ResourceError


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(a):
    length=math.sqrt(dot(a,a))
    return [x/length for x in a] if length>1e-10 else [0,1,0]
def linear(x):return x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4
def srgb(x):return max(0,min(255,round(255*(12.92*x if x<=.0031308 else 1.055*max(0,x)**(1/2.4)-.055))))


def texture_sample(texture,uv,lod=0):
    image=texture["image"];sampler=texture["sampler"]
    levels=image["levels"]
    filtering=sampler.get("magFilter",9729) if lod<=0 else sampler.get("minFilter",9987)
    use_mips=filtering in (9984,9985,9986,9987) and lod>0
    level=max(0,min(len(levels)-1,lod)) if use_mips else 0
    first=int(math.floor(level)) if filtering in (9986,9987) else int(round(level))
    second=min(first+1,len(levels)-1) if filtering in (9986,9987) else first
    bilinear=filtering in (9729,9985,9987)
    def wrap(i,size,mode):
        if mode==33071:return min(size-1,max(0,i))
        if mode==33648:
            i=i%(size*2)
            return i if i<size else 2*size-1-i
        return i%size
    def at(level):
        w,h,pixels=levels[level];u,v=uv[0]*w-.5,uv[1]*h-.5
        def texel(x,y):
            index=(wrap(y,h,sampler.get("wrapT",10497))*w+wrap(x,w,sampler.get("wrapS",10497)))*4
            return [pixels[index+c]/255 for c in range(4)]
        if not bilinear:return texel(math.floor(u+.5),math.floor(v+.5))
        x,y=math.floor(u),math.floor(v);a,b=u-x,v-y
        p00,p10,p01,p11=texel(x,y),texel(x+1,y),texel(x,y+1),texel(x+1,y+1)
        return [(p00[c]*(1-a)+p10[c]*a)*(1-b)+(p01[c]*(1-a)+p11[c]*a)*b for c in range(4)]
    a=at(first)
    if first==second:return a
    b=at(second);blend=level-first
    return [x+(y-x)*blend for x,y in zip(a,b)]


def rasterize(document,meshes,camera_basis,lights,maximum=None):
    camera,right,up,forward=camera_basis
    width,height=document["width"],document["height"]
    if maximum and max(width,height)>maximum:
        scale=maximum/max(width,height);width,height=max(1,round(width*scale)),max(1,round(height*scale))
    focal=height/(2*math.tan(math.radians(camera["fov"])/2))
    background=bytes(int(document["background"][i:i+2],16) for i in (1,3,5))
    pixels=bytearray(background*(width*height));depths=array('f',[0])*(width*height)
    pano=document.get("_panorama")
    if pano:
        pw,ph,pbytes=pano
        two_pi=2*math.pi
        for py in range(height):
            sy=height/2-(py+.5)
            row_base=[forward[c]*focal+up[c]*sy for c in range(3)]
            for px in range(width):
                sx=px+.5-width/2
                dx,dy,dz=row_base[0]+right[0]*sx,row_base[1]+right[1]*sx,row_base[2]+right[2]*sx
                inv_len=1.0/max(1e-9,math.sqrt(dx*dx+dy*dy+dz*dz))
                nx,ny,nz=dx*inv_len,max(-1.0,min(1.0,dy*inv_len)),dz*inv_len
                u=(0.5+math.atan2(nx,nz)/two_pi)%1.0
                v=max(0.0,min(0.999999,0.5-math.asin(ny)/math.pi))
                src=(int(v*ph)*pw+int(u*pw))*3
                dst=(py*width+px)*3
                pixels[dst:dst+3]=pbytes[src:src+3]
    opaque=[];transparent=[];work=0
    for mesh in meshes:
        world=mesh["vertices"]
        material=mesh.get("material")
        for face in mesh["triangles"]:
            a,b,c=[world[i] for i in face];normal=unit(cross(sub(b,a),sub(c,a)))
            center=[(a[i]+b[i]+c[i])/3 for i in range(3)]
            back=dot(normal,sub(camera["position"],center))<0
            if material and back and not material.get("doubleSided",False):continue
            vertices=[]
            for i in face:
                relative=sub(world[i],camera["position"])
                row={"camera":[dot(relative,right),dot(relative,up),dot(relative,forward)],"world":world[i]}
                for field in ("normals","tangents","uv0","uv1","colors"):
                    if field in mesh:row[field]=mesh[field][i]
                vertices.append(row)
            # Clip against the near plane, preserving all interpolated attributes.
            clipped=[]
            for current,previous in zip(vertices,vertices[-1:]+vertices[:-1]):
                inside=current["camera"][2]>=.05;before=previous["camera"][2]>=.05
                if inside!=before:
                    t=(.05-previous["camera"][2])/(current["camera"][2]-previous["camera"][2])
                    clipped.append({key:[x+(y-x)*t for x,y in zip(previous[key],current[key])] for key in current})
                if inside:clipped.append(current)
            for j in range(1,len(clipped)-1):
                triangle=[clipped[0],clipped[j],clipped[j+1]]
                projected=[(width/2+v["camera"][0]*focal/v["camera"][2],height/2-v["camera"][1]*focal/v["camera"][2],v["camera"][2]) for v in triangle]
                entry=(projected,triangle,mesh,normal,center,back)
                (transparent if material and material.get("alphaMode")=="BLEND" else opaque).append(entry)
    transparent.sort(key=lambda row:sum(p[2] for p in row[0]),reverse=True)
    for projection,vertices,mesh,face_normal,center,back in opaque+transparent:
        (ax,ay,az),(bx,by,bz),(cx,cy,cz)=projection
        det=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        if abs(det)<1e-9:continue
        left=max(0,math.floor(min(ax,bx,cx)));right_edge=min(width-1,math.ceil(max(ax,bx,cx)))
        top=max(0,math.floor(min(ay,by,cy)));bottom=min(height-1,math.ceil(max(ay,by,cy)))
        if left>right_edge or top>bottom:continue
        work+=(right_edge-left+1)*(bottom-top+1)
        if work>16000000:raise ResourceError("当前机位的重叠三角像素超过 1600 万预算；请简化模型或缩小画幅", "spatial_render_limit")
        material=mesh.get("material");legacy=None
        if material:
            pbr=material["pbrMetallicRoughness"];mode=material.get("alphaMode","OPAQUE")
            textures=mesh["textures"];unlit="KHR_materials_unlit" in material.get("extensions",{})
            # A per-triangle screen derivative supplies bounded mip selection.
            lods={}
            for uv_field in ("uv0","uv1"):
                if uv_field in vertices[0]:
                    for ti,texture in enumerate(textures):
                        w,h=texture["image"]["size"]
                        ratios=[]
                        for i,k in ((0,1),(1,2),(2,0)):
                            screen=math.hypot(projection[i][0]-projection[k][0],projection[i][1]-projection[k][1])
                            delta=sub(vertices[i][uv_field],vertices[k][uv_field])
                            ratios.append(math.hypot(delta[0]*w,delta[1]*h)/max(screen,1e-6))
                        lods[(uv_field,ti)]=max(0,math.log2(max(max(ratios),1e-6)))
            tangent_basis=None
            if "normalTexture" in material and "tangents" not in vertices[0]:
                uv_field="uv"+str(material["normalTexture"].get("texCoord",0));u0,u1,u2=[v[uv_field] for v in vertices]
                du1,dv1=sub(u1,u0);du2,dv2=sub(u2,u0);denom=du1*dv2-du2*dv1
                if abs(denom)>1e-12:
                    edge1=sub(vertices[1]["world"],vertices[0]["world"]);edge2=sub(vertices[2]["world"],vertices[0]["world"])
                    tangent_basis=(unit([(x*dv2-y*dv1)/denom for x,y in zip(edge1,edge2)]),unit([(y*du1-x*du2)/denom for x,y in zip(edge1,edge2)]))
        else:
            rgb=[int(mesh["color"][i:i+2],16) for i in (1,3,5)]
            illumination=min(1,.35+.65*max(abs(dot(face_normal,unit(sub(light,center)))) for light in lights))
            legacy=[round(channel*illumination) for channel in rgb];mode="OPAQUE"
        iza,izb,izc=1/az,1/bz,1/cz;step_a=(by-cy)/det;step_b=(cy-ay)/det
        for y in range(top,bottom+1):
            wa=((by-cy)*(left+.5-cx)+(cx-bx)*(y+.5-cy))/det
            wb=((cy-ay)*(left+.5-cx)+(ax-cx)*(y+.5-cy))/det;index=y*width+left
            for x in range(left,right_edge+1):
                wc=1-wa-wb
                if wa>=-1e-7 and wb>=-1e-7 and wc>=-1e-7:
                    reciprocal=wa*iza+wb*izb+wc*izc
                    if reciprocal>depths[index]:
                        alpha=1.;shade=legacy
                        if material:
                            weights=[wa*iza/reciprocal,wb*izb/reciprocal,wc*izc/reciprocal]
                            def interp(field):return [sum(vertices[j][field][k]*weights[j] for j in range(3)) for k in range(len(vertices[0][field]))]
                            def tex(info):
                                field="uv"+str(info.get("texCoord",0));return texture_sample(textures[info["index"]],interp(field),lods[(field,info["index"])])
                            base=pbr["baseColorFactor"][:]
                            if "baseColorTexture" in pbr:
                                t=tex(pbr["baseColorTexture"]);base=[base[k]*(linear(t[k]) if k<3 else t[k]) for k in range(4)]
                            if "colors" in vertices[0]:base=[a*b for a,b in zip(base,interp("colors"))]
                            alpha=base[3] if mode!="OPAQUE" else 1
                            if mode=="MASK":alpha=1 if alpha>=material.get("alphaCutoff",.5) else 0
                            if alpha>0:
                                if unlit:lit=base[:3]
                                else:
                                    n=unit(interp("normals")) if "normals" in vertices[0] else face_normal[:]
                                    if "normalTexture" in material:
                                        normal_tex=material["normalTexture"];t=tex(normal_tex);mapped=[(t[0]*2-1)*normal_tex.get("scale",1),(t[1]*2-1)*normal_tex.get("scale",1),t[2]*2-1]
                                        if "tangents" in vertices[0]:
                                            tangent=interp("tangents");tangent_xyz=unit(sub(tangent[:3],[v*dot(n,tangent[:3]) for v in n]));bitangent=[v*tangent[3] for v in cross(n,tangent_xyz)]
                                        elif tangent_basis:tangent_xyz,bitangent=tangent_basis
                                        else:tangent_xyz=unit(cross([0,1,0] if abs(n[1])<.99 else [1,0,0],n));bitangent=cross(n,tangent_xyz)
                                        n=unit([tangent_xyz[k]*mapped[0]+bitangent[k]*mapped[1]+n[k]*mapped[2] for k in range(3)])
                                    if back:n=[-v for v in n]
                                    world=interp("world");view=unit(sub(camera["position"],world));ndv=max(.001,dot(n,view))
                                    metal=pbr["metallicFactor"];rough=max(.045,pbr["roughnessFactor"])
                                    if "metallicRoughnessTexture" in pbr:
                                        t=tex(pbr["metallicRoughnessTexture"]);metal*=t[2];rough=max(.045,rough*t[1])
                                    ao=1
                                    if "occlusionTexture" in material:
                                        info=material["occlusionTexture"];ao=1+info.get("strength",1)*(tex(info)[0]-1)
                                    lit=[v*.18*ao for v in base[:3]]
                                    for light in lights[:8]:
                                        direction=unit(sub(light,world));ndl=max(0,dot(n,direction));half=unit([a+b for a,b in zip(direction,view)]);ndh=max(0,dot(n,half));vdh=max(0,dot(view,half))
                                        a2=rough**4;distribution=a2/(math.pi*max(1e-8,(ndh*ndh*(a2-1)+1)**2));k=(rough+1)**2/8
                                        geometry=ndl/(ndl*(1-k)+k)*ndv/(ndv*(1-k)+k)
                                        for c in range(3):
                                            f0=.04*(1-metal)+base[c]*metal;fresnel=f0+(1-f0)*(1-vdh)**5
                                            diffuse=(1-fresnel)*(1-metal)*base[c]/math.pi;specular=distribution*geometry*fresnel/max(.0001,4*ndl*ndv)
                                            lit[c]+=(diffuse+specular)*ndl*2.2/len(lights[:8])
                                    emissive=material.get("emissiveFactor",[0,0,0])
                                    if "emissiveTexture" in material:emissive=[v*linear(t) for v,t in zip(emissive,tex(material["emissiveTexture"])[:3])]
                                    lit=[a+b for a,b in zip(lit,emissive)]
                                shade=[srgb(v) for v in lit]
                        if alpha>0:
                            pixel=index*3
                            for c in range(3):
                                pixels[pixel+c]=shade[c] if alpha==1 else srgb(linear(shade[c]/255)*alpha+linear(pixels[pixel+c]/255)*(1-alpha))
                            if mode!="BLEND":depths[index]=reciprocal
                wa+=step_a;wb+=step_b;index+=1
    output=io.BytesIO();Image.frombytes("RGB",(width,height),bytes(pixels)).save(output,format="PNG")
    return output.getvalue()
