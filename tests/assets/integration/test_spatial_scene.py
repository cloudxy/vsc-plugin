"""Real PG versions, frozen camera/time exports and recoverable worker leases."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "PIL"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(HAS_DB, "requires image dependencies")
class SpatialGltfTests(unittest.TestCase):
    def test_core_texture_skin_animation_sampling_and_baked_visual_roundtrip(self):
        from support.fixtures.spatial_glb import animated_glb
        from vsc.post.spatial_gltf import decode_glb, sample_model
        from vsc.post.spatial_export import render_png, export_glb
        from vsc.assets.spatial_scene import normalize_scene
        from PIL import Image
        model=decode_glb(animated_glb())
        before=sample_model(model,0,0,0)[0];middle=sample_model(model,0,0,.5)[0]
        self.assertEqual(before["vertices"],[[-1.,0.,0.],[1.,0.,0.],[1.,2.,0.],[-1.,2.,0.]])
        self.assertAlmostEqual(middle["vertices"][2][0],1-2**.5)
        self.assertAlmostEqual(middle["vertices"][2][1],2**.5)
        self.assertEqual(sample_model(model,0,1,.99)[0]["vertices"],before["vertices"])
        self.assertEqual(sample_model(model,0,1,1)[0]["vertices"][0],[-1.,1.,0.])
        self.assertAlmostEqual(sample_model(model,0,2,.5)[0]["vertices"][1][0],1.5)
        self.assertAlmostEqual(sample_model(model,0,3,.5)[0]["vertices"][2][2],.4)
        doc=normalize_scene({"width":320,"height":180,"duration":2,"objects":[{"id":"model","kind":"mesh","color":"#ffffff","media_id":str(uuid.uuid4()),"geometry":{"source_sha256":"a"*64,"scene":0},"animation":{"clip":0}}],"cameras":[{"id":"eye","position":[0,1,6],"target":[0,1,0]}]})
        doc["objects"][0]["_gltf"]=model
        png0=render_png(doc,"eye",0);png1=render_png(doc,"eye",.5)
        self.assertNotEqual(png0,png1)
        colors=set(Image.open(io.BytesIO(png0)).getdata())
        self.assertTrue({(255,0,0),(0,255,0),(0,0,255),(255,255,0)}<=colors)
        baked=decode_glb(export_glb(doc,"eye",.5))
        self.assertEqual(baked["animations"],[])
        doc["objects"][0]["_gltf"]=baked;doc["objects"][0]["animation"]["clip"]=None
        self.assertEqual(render_png(doc,"eye",0),png1)
        doc["objects"][0]["_gltf"]=model;doc["objects"][0]["animation"].update(clip=0,speed=2,offset=0,loop=True)
        self.assertEqual(render_png(doc,"eye",.75),png1)
        doc["objects"][0]["animation"].update(speed=0,offset=.5,loop=False)
        self.assertEqual(render_png(doc,"eye",1.5),png1)

    def test_material_maps_alpha_and_untrusted_glb_limits(self):
        from support.fixtures.spatial_glb import animated_glb
        from vsc.post.spatial_gltf import decode_glb
        from vsc.post.spatial_export import render_png
        from vsc.assets.spatial_scene import normalize_scene
        from vsc.assets.resource_service import ResourceError
        from PIL import Image
        doc=normalize_scene({"width":320,"height":180,"objects":[{"id":"model","kind":"mesh","color":"#ffffff","media_id":str(uuid.uuid4()),"geometry":{"source_sha256":"a"*64,"scene":0}}],"cameras":[{"id":"eye","position":[0,1,6],"target":[0,1,0]}]})
        def rendered(change):
            doc["objects"][0]["_gltf"]=decode_glb(animated_glb(change));return render_png(doc,"eye",0)
        def lit(data,_):data["materials"][0].pop("extensions");data.pop("extensionsUsed")
        baseline=rendered(lit)
        def mapped(data,binary):
            lit(data,binary);m=data["materials"][0]
            m["pbrMetallicRoughness"].update(metallicFactor=1,metallicRoughnessTexture={"index":0})
            m.update(normalTexture={"index":0,"scale":.5},occlusionTexture={"index":0,"strength":.8},emissiveTexture={"index":0},emissiveFactor=[.2,.2,.2])
        self.assertNotEqual(baseline,rendered(mapped))
        def mask(data,_):data["materials"][0].update(alphaMode="MASK");data["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][3]=0
        self.assertEqual(len(set(Image.open(io.BytesIO(rendered(mask))).getdata())),1)
        def blend(data,_):data["materials"][0].update(alphaMode="BLEND");data["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][3]=.5
        blended=rendered(blend)
        self.assertNotEqual(blended,rendered(lambda *_:None))
        self.assertEqual(Image.open(io.BytesIO(blended)).getpixel((160,90)),(238,243,175))
        changes=[lambda d,b:d["buffers"][0].update(uri="https://example.invalid/model.bin"),
            lambda d,b:d.update(extensionsRequired=["KHR_draco_mesh_compression"]),
            lambda d,b:d["nodes"][2].update(children=[1]),
            lambda d,b:d["accessors"][0].update(count=999999999),
            lambda d,b:d["skins"][0].update(joints=[1]),
            lambda d,b:d["images"][0].update(mimeType="image/svg+xml"),
            lambda d,b:d["meshes"][0]["primitives"][0]["attributes"].pop("TEXCOORD_0")]
        for change in changes:
            with self.subTest(change=changes.index(change)),self.assertRaises(ResourceError):decode_glb(animated_glb(change))


@unittest.skipUnless(TEST_URL and HAS_DB, "requires configured isolated PostgreSQL and image support")
class SpatialSceneTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.service.storage=LocalStorage(self.directory.name)

    def scene(self, **kw):
        from vsc.assets.spatial_scene import default_scene
        doc=default_scene();doc.update(width=320,height=180,duration=1)
        doc["objects"][1]["keyframes"]=[{"time":1,"position":[2,0,0]}]
        return self.write("create_spatial_scene",dict(title="合成场景",document=doc,**kw))

    def export(self,scene,fmt="png",**kw):
        result=self.write("create_spatial_export",dict(spatial_scene_id=scene["id"],scene_revision=scene["scene_revision"],camera_id="camera-a",format=fmt,time=0,**kw))
        completed=self.service.execute_spatial_export(self.p,result["id"])
        self.rev=self.store.get_project(self.p)["revision"]
        self.assertEqual(completed["status"],"succeeded",completed)
        media=self.service.get_media(self.p,completed["media_id"])
        content=self.service.storage.read(media["locations"][0]["object_key"],media["sha256"])
        return result,completed,content

    def test_referenced_animated_glb_original_media_versions_and_real_exports(self):
        from support.fixtures.spatial_glb import animated_glb
        from vsc.post.spatial_gltf import decode_glb, sample_model
        from vsc.assets.resource_service import ResourceError
        raw=animated_glb();staged=self.service.storage.stage_upload(io.BytesIO(raw),"animated.glb")
        media=self.write("register_media",{"name":"animated.glb","staged_upload":staged["staged_upload"],"rights":"owned","source":{"kind":"synthetic","content":"two joints and four-color texture"}})
        imported=self.service.import_spatial_glb(self.p,media["id"])
        self.assertEqual(len(imported["model_catalog"][media["sha256"]]["clips"]),4)
        doc={"width":320,"height":180,"duration":1,"objects":imported["objects"],"cameras":[{"id":"camera-a","position":[0,1,6],"target":[0,1,0]}]}
        scene=self.write("create_spatial_scene",{"title":"固定动画来源","document":doc})
        current=self.service.get_spatial_scene(self.p,scene["id"])
        self.assertNotIn("_gltf",json.dumps(current["document"]))
        self.assertLess(len(json.dumps(current["document"])),2000)
        preview=self.service.preview_spatial_scene(self.p,{"document":doc,"camera_id":"camera-a","time":.5})
        def output(fmt,instant=0,**kw):
            job=self.write("create_spatial_export",dict(spatial_scene_id=scene["id"],scene_revision=1,camera_id="camera-a",format=fmt,time=instant,**kw))
            done=self.service.execute_spatial_export(self.p,job["id"]);self.rev=self.store.get_project(self.p)["revision"]
            self.assertEqual(done["status"],"succeeded")
            item=self.service.get_media(self.p,done["media_id"])
            return job,done,self.service.storage.read(item["locations"][0]["object_key"],item["sha256"])
        _,done,png=output("png",.5);self.assertEqual(png,preview)
        _,_,glb=output("glb",.5);baked=decode_glb(glb)
        self.assertEqual(len(baked["animations"]),1)
        self.assertEqual(baked["animations"][0]["name"],"VSC scene timeline")
        self.assertAlmostEqual(sample_model(baked,0,0,.5)[0]["vertices"][2][0],1-2**.5,places=6)
        self.assertNotEqual(sample_model(baked,0,0,0),sample_model(baked,0,0,.5))
        job,video,mp4=output("mp4",duration=1)
        path=Path(self.directory.name)/"animated.mp4";path.write_bytes(mp4)
        stream=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(path)],capture_output=True,check=True).stdout)["streams"][0]
        self.assertEqual((stream["codec_name"],stream["width"],stream["height"],stream["nb_frames"]),("h264",320,180,"12"))
        frames=subprocess.run(["ffmpeg","-v","error","-i",str(path),"-f","rawvideo","-pix_fmt","rgb24","-"],capture_output=True,check=True).stdout
        self.assertNotEqual(frames[:320*180*3],frames[-320*180*3:])
        with patch("vsc.post.spatial_export.render_png",side_effect=AssertionError("completed export rerendered")):
            self.assertEqual(self.service.execute_spatial_export(self.p,job["id"])["output"]["media_id"],video["media_id"])
        doc["objects"][0]["animation"].update(clip=2,speed=.5)
        old=self.rev;payload={"spatial_scene_id":scene["id"],"scene_revision":1,"title":"新动画设置","document":doc}
        saved=self.write("save_spatial_scene",payload,idempotency_key="model-settings")
        self.assertEqual(saved,self.service.save_spatial_scene(self.p,payload,actor="test-human",expected_revision=old,idempotency_key="model-settings"))
        self.assertEqual(self.service.get_spatial_scene(self.p,scene["id"],1)["document"]["objects"][0]["animation"]["clip"],0)
        bad=deepcopy(doc);bad["objects"][0]["geometry"]["source_sha256"]="0"*64
        with self.assertRaises(ResourceError) as mismatch:self.service.preview_spatial_scene(self.p,{"document":bad,"camera_id":"camera-a"})
        self.assertEqual(mismatch.exception.code,"spatial_model_sha_mismatch")
        with self.assertRaises(ResourceError) as store_mismatch:
            self.store.save_spatial_scene(self.p,{"spatial_scene_id":scene["id"],"scene_revision":2,"title":"失配来源应拒绝","document":bad},
                actor="test-human",expected_revision=self.rev,idempotency_key="bad-model-sha")
        self.assertEqual(store_mismatch.exception.code,"spatial_model_sha_mismatch")
        self.assertEqual(self.store.get_spatial_scene(self.p,scene["id"])["scene_revision"],2)

    def test_two_scopes_versions_actual_png_glb_video_and_original_media_canvas(self):
        from vsc.post.spatial_export import import_glb,render_png,scene_meshes
        from vsc.assets.resource_service import Conflict
        from PIL import Image
        hierarchy=self.hierarchy()
        bu=self.scene(mode="blocking",scene_id=hierarchy["scene"])
        second=self.scene(mode="blocking",scene_id=hierarchy["scene"])
        independent=self.scene(mode="previs")
        self.assertEqual(len(self.service.list_spatial_scenes(self.p,"blocking")["items"]),2)
        current=self.service.get_spatial_scene(self.p,bu["id"])
        self.assertEqual(current["episode_id"],hierarchy["episode"])
        self.assertIsNone(self.service.get_spatial_scene(self.p,independent["id"])["scene_id"])
        png_job,png,png_bytes=self.export(bu)
        self.assertEqual(Image.open(io.BytesIO(png_bytes)).size,(320,180))
        self.assertEqual(png_bytes,render_png(current["document"],"camera-a",0))
        self.assertNotEqual(png_bytes,render_png(current["document"],"camera-b",0))
        self.assertNotEqual(png_bytes,render_png(current["document"],"camera-a",1))
        _,glb,glb_bytes=self.export(bu,"glb")
        self.assertEqual(struct.unpack("<III",glb_bytes[:12]),(0x46546c67,2,len(glb_bytes)))
        imported=import_glb(glb_bytes)
        self.assertEqual(len(imported["meshes"]),len(scene_meshes(current["document"],0)))
        from_media=self.service.import_spatial_glb(self.p,glb["media_id"])
        self.assertEqual(from_media["objects"][0]["media_id"],glb["media_id"])
        _,video,video_bytes=self.export(bu,"mp4",duration=.5)
        path=Path(self.directory.name)/"check.mp4";path.write_bytes(video_bytes)
        probe=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(path)],check=True,capture_output=True).stdout)
        self.assertEqual(probe["streams"][0]["codec_name"],"h264")
        self.assertEqual(probe["streams"][0]["nb_frames"],"6")
        self.assertEqual(probe["streams"][0]["width"],320)
        canvas=self.write("spatial_export_to_canvas",{"export_id":png_job["id"]})
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas["id"])["document"]["nodes"][0]["media_id"],png["media_id"])
        doc=deepcopy(current["document"]);doc["objects"][1]["position"]=[3,0,0]
        payload={"spatial_scene_id":bu["id"],"scene_revision":1,"title":"修订","description":"保留描述","document":doc}
        old=self.rev;saved=self.write("save_spatial_scene",payload,idempotency_key="spatial-save")
        replay=self.service.save_spatial_scene(self.p,payload,actor="test-human",expected_revision=old,idempotency_key="spatial-save")
        self.assertEqual(replay,saved)
        with self.assertRaises(Conflict):self.write("save_spatial_scene",payload)
        self.assertEqual(self.service.get_spatial_scene(self.p,bu["id"],1)["document"],current["document"])
        self.assertEqual(self.service.get_spatial_scene(self.p,second["id"])["scene_revision"],1)
        self.assertEqual(self.service.get_spatial_export(self.p,png_job["id"])["scene_version"],1)
        self.assertEqual(self.service.execute_spatial_export(self.p,png_job["id"])["output"]["media_id"],png["media_id"])

    def test_expired_lease_stale_worker_cancel_and_failed_job_retry_same_id(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        scene=self.scene()
        job=self.write("create_spatial_export",{"spatial_scene_id":scene["id"],"scene_revision":1,"camera_id":"camera-a","format":"png"})
        first=self.store.claim_spatial_export(self.p,job["id"])
        self.assertNotIn("claim_token",self.store.claim_spatial_export(self.p,job["id"]))
        with self.engine.begin() as conn:conn.execute(update(S.spatial_exports).where(S.spatial_exports.c.id==job["id"]).values(claim_until=datetime.now(timezone.utc)-timedelta(seconds=1)))
        second=self.store.claim_spatial_export(self.p,job["id"])
        self.assertNotEqual(first["claim_token"],second["claim_token"])
        self.assertFalse(self.store.progress_spatial_export(self.p,job["id"],first["claim_token"],1))
        self.write("cancel_spatial_export",{"export_id":job["id"]})
        self.assertFalse(self.store.progress_spatial_export(self.p,job["id"],second["claim_token"],1))
        self.assertEqual(self.service.execute_spatial_export(self.p,job["id"])["status"],"cancelled")
        self.assertIsNone(self.service.get_spatial_export(self.p,job["id"])["output"])
        retry=self.write("create_spatial_export",{"spatial_scene_id":scene["id"],"scene_revision":1,"camera_id":"camera-b","format":"png"})
        with patch("vsc.post.spatial_export.render_png",side_effect=RuntimeError("synthetic failure")), self.assertRaises(ResourceError):
            self.service.execute_spatial_export(self.p,retry["id"])
        self.assertEqual(self.service.get_spatial_export(self.p,retry["id"])["status"],"failed")
        done=self.service.execute_spatial_export(self.p,retry["id"])
        self.assertEqual(done["id"],retry["id"])
        self.assertEqual(self.service.get_spatial_export(self.p,retry["id"])["attempt"],2)

    def test_invalid_scope_cross_project_immutable_members_and_missing_output(self):
        from sqlalchemy import select,insert,update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.spatial_scene import default_scene
        with self.assertRaises(ResourceError):self.scene(mode="blocking")
        with self.assertRaises(ResourceError):self.scene(mode="blocking",scene_id=str(uuid.uuid4()))
        scene=self.scene()
        with self.engine.connect() as conn:member=dict(conn.execute(select(S.spatial_objects).where(S.spatial_objects.c.version_id==scene["version_id"])).mappings().first())
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:conn.execute(insert(S.spatial_objects).values(dict(member,object_key="late",ordinal=99)))
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:conn.execute(update(S.spatial_objects).where(S.spatial_objects.c.version_id==scene["version_id"]).values(spec={}))
        job=self.write("create_spatial_export",{"spatial_scene_id":scene["id"],"scene_revision":1,"camera_id":"camera-a","format":"png"})
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:conn.execute(update(S.spatial_exports).where(S.spatial_exports.c.id==job["id"]).values(status="succeeded"))
        other=self.service.create_project({"name":"隔离项目","profile_snapshot":{"profile_id":"vsc.synthetic","version":"1","stages":[]}},actor="test-human")
        with self.assertRaises(ResourceError):self.service.get_spatial_scene(other["id"],scene["id"])
        doc=default_scene();doc["objects"][0]["media_id"]=str(uuid.uuid4())
        with self.assertRaises(ResourceError):self.write("save_spatial_scene",{"spatial_scene_id":scene["id"],"scene_revision":1,"document":doc})

    def test_depth_occlusion_is_independent_of_object_order_and_malformed_glb_rejected(self):
        from vsc.assets.spatial_scene import normalize_scene
        from vsc.post.spatial_export import render_png,import_glb
        from vsc.assets.resource_service import ResourceError
        from PIL import Image
        doc=normalize_scene({"width":320,"height":180,"objects":[
            {"id":"ground","kind":"box","position":[0,-.15,0],"scale":[10,.2,10],"color":"#00ff00"},
            {"id":"front","kind":"box","position":[0,1,0],"color":"#ff0000"}],
            "cameras":[{"id":"eye","position":[0,3,6],"target":[0,1,0]}]})
        image=render_png(doc,"eye",0);pixel=Image.open(io.BytesIO(image)).getpixel((160,90))
        self.assertGreater(pixel[0],pixel[1]+20)
        doc["objects"].reverse();self.assertEqual(image,render_png(doc,"eye",0))
        content=json.dumps({"asset":{"version":"2.0"},"buffers":[{"byteLength":0}],"scenes":[{"nodes":[0]}],"nodes":[{"children":[0]}]}).encode()
        content+=b" "*((-len(content))%4)
        bad=struct.pack("<III",0x46546c67,2,28+len(content))+struct.pack("<II",len(content),0x4e4f534a)+content+struct.pack("<II",0,0x004e4942)
        with self.assertRaises(ResourceError):import_glb(bad)

    def test_viewport_capture_is_a_still_download_without_media_canvas_or_workflow(self):
        from copy import deepcopy
        from sqlalchemy import func, select
        from PIL import Image
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.spatial_scene import default_scene
        wide=default_scene();wide.update(width=960,height=540)
        wide["objects"].append({"id":"lamp","kind":"light","position":[0,2,1],"color":"#fff1c2"})
        portrait=deepcopy(wide);portrait.update(width=540,height=960)
        small=deepcopy(wide);small.update(width=320,height=180)
        dark=deepcopy(small)
        dark["objects"]=[item for item in dark["objects"] if item["kind"]!="light"]
        empty={"objects":[],"cameras":wide["cameras"],"width":960,"height":540,"duration":5}
        revision=self.service.get_project(self.p)["revision"]
        with self.engine.connect() as conn:
            before={name:conn.scalar(select(func.count()).select_from(table)) for name,table in (
                ("exports",S.spatial_exports),("media",S.media_items),("canvases",S.creative_canvases),("workflows",S.intelligent_workflows))}
        captured=self.service.capture_spatial_viewport(self.p,{"document":wide,"camera_id":"camera-a","time":0})
        self.assertEqual(Image.open(io.BytesIO(captured)).size,(1920,1080))
        self.assertEqual(Image.open(io.BytesIO(self.service.capture_spatial_viewport(self.p,{"document":portrait,"camera_id":"camera-a","time":0}))).size,(1080,1920))
        near=self.service.capture_spatial_viewport(self.p,{"document":small,"camera_id":"camera-a","time":0})
        far=self.service.capture_spatial_viewport(self.p,{"document":dark,"camera_id":"camera-a","time":0})
        self.assertEqual(Image.open(io.BytesIO(near)).size,(320,180))
        self.assertNotEqual(near,far)
        with self.assertRaises(ResourceError) as empty_view:
            self.service.capture_spatial_viewport(self.p,{"document":empty,"camera_id":"camera-a","time":0})
        self.assertEqual(empty_view.exception.code,"spatial_viewport_empty")
        self.assertEqual(self.service.get_project(self.p)["revision"],revision)
        with self.engine.connect() as conn:
            after={name:conn.scalar(select(func.count()).select_from(table)) for name,table in (
                ("exports",S.spatial_exports),("media",S.media_items),("canvases",S.creative_canvases),("workflows",S.intelligent_workflows))}
        self.assertEqual(before,after)

    def test_registered_png_export_uses_measured_still_and_video_keeps_scene_size(self):
        import subprocess
        from sqlalchemy import func, select
        from PIL import Image
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.assets.spatial_scene import default_scene
        from vsc.post.spatial_export import render_png, render_still_png
        wide=default_scene();wide.update(width=960,height=540,duration=1)
        portrait=default_scene();portrait.update(width=540,height=960,duration=1)
        wide_scene=self.write("create_spatial_scene",{"title":"横屏预演","document":wide})
        portrait_scene=self.write("create_spatial_scene",{"title":"竖屏预演","document":portrait})
        _,_,png_bytes=self.export(wide_scene)
        saved=self.service.get_spatial_scene(self.p,wide_scene["id"])["document"]
        self.assertEqual((saved["width"],saved["height"]),(960,540))
        self.assertEqual(Image.open(io.BytesIO(png_bytes)).size,(1920,1080))
        self.assertEqual(png_bytes,render_still_png(saved,"camera-a",0))
        self.assertNotEqual(png_bytes,render_png(saved,"camera-a",0))
        _,_,portrait_bytes=self.export(portrait_scene)
        self.assertEqual(Image.open(io.BytesIO(portrait_bytes)).size,(1080,1920))
        _,_,video_bytes=self.export(wide_scene,"mp4",duration=.1,fps=12)
        path=Path(self.directory.name)/"still-vs-video.mp4";path.write_bytes(video_bytes)
        stream=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(path)],capture_output=True,check=True).stdout)["streams"][0]
        self.assertEqual((stream["width"],stream["height"]),(960,540))
        blank=default_scene();blank["objects"]=[]
        empty=self.write("create_spatial_scene",{"title":"空场景","document":blank})
        revision=self.service.get_project(self.p)["revision"]
        with self.engine.connect() as conn:
            before=conn.scalar(select(func.count()).select_from(S.spatial_exports))
        with self.assertRaises(ResourceError) as blocked:
            self.write("create_spatial_export",{"spatial_scene_id":empty["id"],"scene_revision":empty["scene_revision"],"camera_id":"camera-a","format":"png"})
        self.assertEqual(blocked.exception.code,"spatial_export_empty")
        self.assertEqual(self.service.get_project(self.p)["revision"],revision)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.spatial_exports)),before)

@unittest.skipUnless(TEST_URL and HAS_DB,'requires isolated PostgreSQL')
class SpatialPlannerTests(ResourceStoreFixture,unittest.TestCase):
    scene=SpatialSceneTests.scene
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup);self.service.storage=LocalStorage(self.directory.name)
    def test_scene_text_plan_preview_adoption_stale_and_unknown_original_task(self):
        from vsc.assets.resource_service import ResourceError,Conflict
        scene=self.scene();service=self.service
        class Planner:
            calls=0
            def available(self):return True
            def generate(self,packet,task,skill):
                self.calls+=1;document=deepcopy(task['document']);document['objects'][1]['position'][0]=3
                return dict(message='合成机位与站位修改',questions=[],document=document)
        planner=Planner();service.spatial_planner=planner
        task=self.write('create_spatial_plan_task',dict(spatial_scene_id=scene['id'],scene_revision=1,message='人物右移'))
        planned=service.execute_spatial_plan_task(self.p,task['id']);self.rev=service.get_project(self.p)['revision'];self.assertEqual(planned['status'],'planned');self.assertEqual(service.get_spatial_scene(self.p,scene['id'])['scene_revision'],1)
        self.assertTrue(service.preview_spatial_scene(self.p,dict(document=planned['plan']['document'],camera_id='camera-a',time=0)).startswith(b'\x89PNG'))
        self.write('decide_spatial_plan_task',dict(task_id=task['id'],outcome='confirm',reason='明确采纳合成修改',document=planned['plan']['document']))
        self.assertEqual(service.get_spatial_scene(self.p,scene['id'])['document']['objects'][1]['position'][0],3);self.assertEqual(service.get_spatial_scene(self.p,scene['id'],1)['document']['objects'][1]['position'][0],-1)
        task=self.write('create_spatial_plan_task',dict(spatial_scene_id=scene['id'],scene_revision=2,message='合成未知提交'))
        def unknown(*args):planner.calls+=1;raise ResourceError('synthetic timeout','spatial_plan_submission_unknown')
        planner.generate=unknown
        self.assertEqual(service.execute_spatial_plan_task(self.p,task['id'])['status'],'submission_unknown');self.assertEqual(service.execute_spatial_plan_task(self.p,task['id'])['status'],'submission_unknown');self.assertEqual(planner.calls,2)

    def test_stale_scene_plan_cannot_replace_new_saved_structure(self):
        from vsc.assets.resource_service import Conflict
        scene=self.scene()
        class Planner:
            def available(self):return True
            def generate(self,packet,task,skill):return dict(message='合成原场景计划',questions=[],document=task['document'])
        self.service.spatial_planner=Planner();task=self.write('create_spatial_plan_task',dict(spatial_scene_id=scene['id'],scene_revision=1,message='合成场景修改'));plan=self.service.execute_spatial_plan_task(self.p,task['id']);self.rev=self.service.get_project(self.p)['revision']
        current=self.service.get_spatial_scene(self.p,scene['id']);document=current['document'];document['objects'][1]['position'][0]=8
        self.write('save_spatial_scene',dict(spatial_scene_id=scene['id'],scene_revision=1,title='新的人工结构',document=document))
        with self.assertRaises(Conflict) as error:self.write('decide_spatial_plan_task',dict(task_id=task['id'],outcome='confirm',reason='合成旧计划尝试',document=plan['plan']['document']))
        self.assertEqual(error.exception.code,'spatial_plan_stale');self.assertEqual(self.service.get_spatial_scene(self.p,scene['id'])['document']['objects'][1]['position'][0],8)

    def test_direct_generation_saves_one_editable_version_and_preserves_original(self):
        scene=self.scene();calls=[]
        class Planner:
            def available(self):return True
            def generate(self,packet,task,skill):
                calls.append(task['id']);document=deepcopy(task['document']);document['objects'][1]['position'][0]=4
                return dict(message='合成直接修改',questions=[],document=document)
        self.service.spatial_planner=Planner()
        task=self.write('create_spatial_plan_task',dict(spatial_scene_id=scene['id'],scene_revision=1,message='直接修改人物位置',apply_mode='direct'))
        result=self.service.execute_spatial_plan_task(self.p,task['id'])
        self.assertEqual(result['status'],'applied');self.assertEqual(result['apply_mode'],'direct')
        current=self.service.get_spatial_scene(self.p,scene['id'])
        self.assertEqual(current['scene_revision'],2);self.assertEqual(current['document']['objects'][1]['position'][0],4)
        self.assertEqual(self.service.get_spatial_scene(self.p,scene['id'],1)['document']['objects'][1]['position'][0],-1)
        self.assertEqual(current['plans'][0]['output_version_id'],current['version_id'])
        self.service.execute_spatial_plan_task(self.p,task['id'])
        self.assertEqual(len(calls),1);self.assertEqual(self.service.get_spatial_scene(self.p,scene['id'])['scene_revision'],2)
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.artifact_decisions).where(S.artifact_decisions.c.project_id==self.p)).scalar(),0)
            decision=conn.execute(select(S.spatial_plan_decisions).where(S.spatial_plan_decisions.c.project_id==self.p,S.spatial_plan_decisions.c.task_id==task['id'])).mappings().one()
            self.assertEqual(decision['actor'],'test-human')

    def test_direct_generation_retains_questions_stale_changes_and_stopped_late_result(self):
        fixture=self;scene=self.scene()
        class Planner:
            effect='questions'
            def available(self):return True
            def generate(self,packet,task,skill):
                document=deepcopy(task['document']);document['objects'][1]['position'][0]=3
                if self.effect=='stale':
                    edited=deepcopy(task['document']);edited['objects'][1]['position'][0]=8
                    fixture.write('save_spatial_scene',dict(spatial_scene_id=scene['id'],scene_revision=task['scene_revision'],title='并发修改',document=edited))
                if self.effect=='stop':fixture.write('decide_spatial_plan_task',dict(task_id=task['id'],outcome='stop',reason='用户停止本次生成'))
                return dict(message='合成回复',questions=['人物朝向？'] if self.effect=='questions' else [],document=document)
        planner=Planner();self.service.spatial_planner=planner
        for effect,version,status in [('questions',1,'needs_input'),('stale',1,'planned'),('stop',2,'stopped')]:
            with self.subTest(effect=effect):
                self.rev=self.service.get_project(self.p)['revision'];planner.effect=effect
                task=self.write('create_spatial_plan_task',dict(spatial_scene_id=scene['id'],scene_revision=version,message=effect,apply_mode='direct'))
                result=self.service.execute_spatial_plan_task(self.p,task['id'])
                self.assertEqual(result['status'],status)
                current=self.service.get_spatial_scene(self.p,scene['id']);self.assertEqual(current['scene_revision'],2 if effect!='questions' else 1)
                if effect=='stale':self.assertEqual(result['error'],'spatial_plan_stale');self.assertEqual(current['document']['objects'][1]['position'][0],8)
                if effect=='stop':self.assertIsNone(result['host_result']);self.assertIsNone(result['plan_artifact_id'])
