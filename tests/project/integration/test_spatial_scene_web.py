"""Session-authorized HTTP scenes and independently readable export bytes."""
import importlib.util
import io
import os
import tempfile
import unittest
import uuid
from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS=all(importlib.util.find_spec(n) for n in ("sqlalchemy","psycopg","alembic","fastapi","httpx","PIL"))


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DEPS,"requires configured isolated PostgreSQL and web dependencies")
class SpatialSceneWebTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.service.storage=LocalStorage(self.directory.name)
        self.client=TestClient(create_app({"projects_root":self.directory.name+"/projects","media_root":self.directory.name,"allowed_hosts":["testserver"],"allowed_origins":["http://testserver"],"human_identity":"test-human","access_token":"test-token"},service=self.service))
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        session=self.client.post("/api/v1/session",headers={"Origin":"http://testserver"},json={"token":"test-token"}).json()
        self.headers={"Origin":"http://testserver","X-CSRF-Token":session["csrf_token"]};self.base="/api/v1/projects/"+self.p

    def command(self,path,payload,method="POST",key=None,expected=None):
        result=self.client.request(method,self.base+path,headers=self.headers,json={"payload":payload,"expected_revision":self.rev if expected is None else expected,"idempotency_key":key or uuid.uuid4().hex})
        if result.status_code==200:self.rev=result.json()["revision"]
        return result

    def test_http_animated_model_scope_sha_catalog_and_preview(self):
        from support.fixtures.spatial_glb import animated_glb
        from copy import deepcopy
        raw=animated_glb();staged=self.service.storage.stage_upload(io.BytesIO(raw),"animated-web.glb")
        media=self.write("register_media",{"name":"animated-web.glb","staged_upload":staged["staged_upload"],"rights":"owned","source":{"kind":"synthetic","content":"owned generated test geometry"}})
        imported=self.client.post(self.base+"/spatial-model-import",headers=self.headers,json={"media_id":media["id"]})
        self.assertEqual(imported.status_code,200,imported.text)
        value=imported.json();doc={"width":320,"height":180,"duration":1,"objects":value["objects"],"cameras":[{"id":"eye","position":[0,1,6],"target":[0,1,0]}]}
        created=self.command("/spatial-scenes",{"title":"HTTP纹理动画","document":doc})
        self.assertEqual(created.status_code,200,created.text)
        current=self.client.get(self.base+"/spatial-scenes/"+created.json()["id"]).json()
        self.assertEqual(len(current["model_catalog"][media["sha256"]]["clips"]),4)
        images=[]
        for time in (0,.5):
            response=self.client.post(self.base+"/spatial-preview",headers=self.headers,json={"document":doc,"camera_id":"eye","time":time})
            self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else "")
            images.append(response.content)
        self.assertNotEqual(*images)
        bad=deepcopy(doc);bad["objects"][0]["geometry"]["source_sha256"]="0"*64
        response=self.client.post(self.base+"/spatial-preview",headers=self.headers,json={"document":bad,"camera_id":"eye"})
        self.assertGreaterEqual(response.status_code,400)
        other=self.service.create_project({"name":"模型范围隔离","profile_snapshot":{"profile_id":"vsc.synthetic","version":"1","stages":[]}},actor="test-human")["id"]
        response=self.client.post("/api/v1/projects/"+other+"/spatial-preview",headers=self.headers,json={"document":doc,"camera_id":"eye"})
        self.assertGreaterEqual(response.status_code,400)
        self.assertEqual(self.client.get(self.base+"/spatial-scenes/"+created.json()["id"]).json()["scene_revision"],1)

    def test_http_viewer_cannot_claim_or_cancel_an_owner_export(self):
        from datetime import datetime,timedelta,timezone
        import secrets
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from vsc.assets.spatial_scene import default_scene
        created=self.command("/spatial-scenes",{"title":"只读导出边界","document":default_scene()}).json()
        job=self.command("/spatial-scenes/"+created["id"]+"/exports",{"scene_revision":1,"camera_id":"camera-a","format":"png"}).json()
        owner=self.service.ensure_local_access("test-human");token=set_principal(Principal(**owner))
        try:
            def command(action,payload):return self.service.access_command(action,payload,actor=owner["actor"],expected_revision=self.service.access_snapshot()["access_revision"],idempotency_key=uuid.uuid4().hex)
            preview=self.service.access_migration_preview(self.p,owner["workspace_id"])
            command("assign-project",{"project_id":self.p,"workspace_id":owner["workspace_id"],"preview_sha256":preview["sha256"]})
            invitation,credential=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            command("invitation",{"scope":"project","scope_id":self.p,"role":"viewer","secret":invitation,"expires_at":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
            self.service.accept_access_invitation({"invitation_secret":invitation,"credential_secret":credential,"display_name":"只读三维成员"})
        finally:reset_principal(token)
        login=self.client.post("/api/v1/access/login",json={"secret":credential},headers={"Origin":"http://testserver"})
        self.assertEqual(login.status_code,200,login.text)
        headers={"Origin":"http://testserver","X-CSRF-Token":login.json()["csrf_token"]}
        self.assertEqual(self.client.get(self.base+"/spatial-scenes/"+created["id"]).status_code,200)
        self.assertEqual(self.client.post(self.base+"/spatial-exports/"+job["id"]+"/execute",headers=headers).status_code,403)
        self.assertEqual(self.client.post(self.base+"/spatial-exports/"+job["id"]+"/cancel",headers=headers,json={"payload":{},"expected_revision":self.rev,"idempotency_key":uuid.uuid4().hex}).status_code,403)
        self.assertEqual(self.store.get_spatial_export(self.p,job["id"])["status"],"queued")

    def test_http_scene_preview_frozen_export_replay_content_and_model_import(self):
        from PIL import Image
        options=self.client.get(self.base+"/spatial-scene-options").json();doc=options["default_document"];doc.update(width=320,height=180,duration=1)
        created=self.command("/spatial-scenes",{"title":"HTTP预演","mode":"previs","document":doc})
        self.assertEqual(created.status_code,200,created.text);scene=created.json()["id"];path="/spatial-scenes/"+scene
        preview=self.client.post(self.base+"/spatial-preview",headers=self.headers,json={"document":doc,"camera_id":"camera-b","time":.25})
        self.assertEqual(preview.status_code,200,preview.text[:100] if preview.status_code!=200 else "")
        self.assertEqual(Image.open(io.BytesIO(preview.content)).size,(320,180))
        old=self.rev;payload={"scene_revision":1,"camera_id":"camera-b","time":.25,"format":"png"}
        job=self.command(path+"/exports",payload,key="response-lost")
        self.assertEqual(job.status_code,200,job.text)
        self.assertEqual(self.command(path+"/exports",payload,key="response-lost",expected=old).json(),job.json())
        export_path="/spatial-exports/"+job.json()["id"]
        denied=self.client.post(self.base+export_path+"/execute")
        self.assertEqual(denied.status_code,403)
        done=self.client.post(self.base+export_path+"/execute",headers=self.headers)
        self.assertEqual(done.status_code,200,done.text);self.rev=done.json()["revision"]
        content=self.client.get(self.base+"/media/"+done.json()["media_id"]+"/content")
        self.assertEqual(content.content,preview.content)
        self.assertEqual(self.client.post(self.base+export_path+"/execute",headers=self.headers).json()["output"]["media_id"],done.json()["media_id"])
        canvas=self.command(export_path+"/canvas",{})
        self.assertEqual(canvas.status_code,200,canvas.text)
        self.assertEqual(self.client.get(self.base+"/creative-canvases/"+canvas.json()["id"]).json()["document"]["nodes"][0]["media_id"],done.json()["media_id"])
        glb_job=self.command(path+"/exports",dict(payload,format="glb"))
        glb=self.client.post(self.base+"/spatial-exports/"+glb_job.json()["id"]+"/execute",headers=self.headers)
        self.assertEqual(glb.status_code,200,glb.text);self.rev=glb.json()["revision"]
        imported=self.client.post(self.base+"/spatial-model-import",headers=self.headers,json={"media_id":glb.json()["media_id"]})
        self.assertEqual(imported.status_code,200,imported.text)
        doc["objects"]+=imported.json()["objects"]
        saved=self.command(path,{"scene_revision":1,"title":"模型回流","document":doc},"PUT")
        self.assertEqual(saved.status_code,200,saved.text)
        read=self.client.get(self.base+path).json()
        self.assertEqual(read["document"]["objects"][-1]["media_id"],glb.json()["media_id"])
        self.assertEqual(read["exports"][0]["scene_version"],1)
        self.assertEqual(self.command(path,{"scene_revision":1,"document":doc},"PUT").status_code,409)
        self.assertEqual(self.client.get("/static/spatial-scene.js").status_code,200)
        script=self.client.get("/static/spatial-scene.js").text
        self.assertIn("/spatial-viewport",script)
        self.assertIn("link.download=",script)
        self.assertIn("width===960&&height===540",script)
        self.assertIn("ui.previs_export_sizes",script)
        self.assertIn("s.exportButtons",script)
        before=self.client.get(self.base+"/spatial-scenes/"+scene).json()
        view=self.client.post(self.base+"/spatial-viewport",headers=self.headers,json={"document":doc,"camera_id":"camera-b","time":.25})
        self.assertEqual(view.status_code,200,view.text[:180] if view.status_code!=200 else "")
        self.assertTrue(view.headers["content-type"].startswith("image/png"),view.headers["content-type"])
        self.assertEqual(Image.open(io.BytesIO(view.content)).size,(320,180))
        after=self.client.get(self.base+"/spatial-scenes/"+scene).json()
        self.assertEqual(after["revision"],before["revision"])
        self.assertEqual(after["exports"],before["exports"])
        self.assertGreaterEqual(len(before["exports"]),1)
        self.assertEqual(self.client.get("/static/spatial-scene.css").status_code,200)
