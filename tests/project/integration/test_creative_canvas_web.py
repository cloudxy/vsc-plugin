"""HTTP/session → canvas service → migrated PostgreSQL → original media read."""
import importlib.util
import io
import json
import os
import struct
import tempfile
import unittest
import uuid
import zlib
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires configured isolated PostgreSQL and web dependencies")
class CreativeCanvasWebTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.interfaces.web.app import create_app
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service.storage = LocalStorage(self.directory.name)
        self.client = TestClient(create_app({"projects_root": self.directory.name + "/projects", "media_root": self.directory.name, "allowed_hosts": ["testserver"],
            "allowed_origins": ["http://testserver"], "human_identity": "test-human", "access_token": "test-token"}, service=self.service))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def command(self, path, payload, method="POST", expected=None, key=None):
        response = self.client.request(method, self.base + path, headers=self.headers,
            json={"payload": payload, "expected_revision": self.rev if expected is None else expected,
                  "idempotency_key": key or uuid.uuid4().hex})
        if response.status_code == 200:
            self.rev = response.json()["revision"]
        return response

    def test_catalogue_work_input_replay_and_operation_requirements_over_http(self):
        provider='catalogue_'+uuid.uuid4().hex
        self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
        model=self.service.register_model(dict(provider_id=provider,model_key='image',model_version='offline',modality='image',
            capabilities=dict(purposes=['first_frame'],reference_media=True)),actor='test-admin')
        with patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':[dict(model,adapter_available=True)]}):
            options=self.client.get(self.base+'/creative-canvas-run-options').json()
        self.assertEqual(len(options['operations']),53)
        self.assertIn('layout',options)
        self.assertEqual(next(op for op in options['operations'] if op['op_type']=='image_generate')['supported_models'],[model['id']])
        created=self.command('/creative-canvases',dict(title='Operation contract',document=dict(nodes=[dict(id='image',type='image',text='合成输入',params=dict(vsc_operation='image_generate',seed=42))],edges=[]))).json()
        path='/creative-canvases/'+created['id']
        payload=dict(canvas_revision=1,node_id='image',model_id=model['id'])
        before=self.rev
        fixed=self.command(path+'/work-input',payload,key='catalogue-input')
        self.assertEqual(fixed.status_code,200,fixed.text)
        self.assertEqual(fixed.json()['document']['params'],{'seed':42})
        replay=self.command(path+'/work-input',payload,key='catalogue-input',expected=before)
        self.assertEqual(replay.json(),fixed.json())
        missing=self.command('/creative-canvases',dict(document=dict(nodes=[dict(id='v',type='video',params=dict(vsc_operation='head_tail_video'))],edges=[]))).json()
        denied=self.command('/creative-canvases/'+missing['id']+'/work-input',dict(canvas_revision=1,node_id='v',model_id=model['id']))
        self.assertEqual(denied.status_code,422,denied.text)
        self.assertEqual(denied.json()['error'],'canvas_operation_port')
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_canvas_edit_transfers_real_segments_to_original_editor_without_fake_output(self):
        from support.fixtures.media import production_media
        objects=self.hierarchy()
        staged=self.service.storage.stage_upload(io.BytesIO(production_media()['mp4']),'segment.mp4')
        media=self.write('register_media',dict(staged_upload=staged['staged_upload'],name='Real segment',rights='owned',
            rights_scope={'purposes':['*']},source={'kind':'synthetic','content':'test-only generated video'}))['id']
        segments=[dict(source_node_key='v',source_media_id=media,start_time=0.05,end_time=0.3,muted=True)]
        document=dict(nodes=[dict(id='v',type='video',media_id=media),dict(id='edit',type='edit',params={'segments_json':json.dumps(segments)})],
            edges=[dict(id='input',source='v',target='edit',port='visual')])
        created=self.command('/creative-canvases',dict(episode_id=objects['episode'],document=document)).json()
        path='/creative-canvases/'+created['id']
        original_revision=self.rev;payload=dict(canvas_revision=1,node_id='edit')
        saved=self.command(path+'/edit-input',payload,key='edit-replay')
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertFalse(saved.json()['rendered'])
        edit=self.client.get(self.base+'/edit-workspace?episode_id='+objects['episode']).json()
        clip=edit['current']['document']['clips'][0]
        self.assertEqual((clip['media_id'],clip['in_frame'],clip['out_frame'],clip['muted']),(media,1,7,True))
        replay=self.command(path+'/edit-input',payload,key='edit-replay',expected=original_revision)
        self.assertEqual(replay.json(),saved.json())
        fixed=self.client.get(self.base+path).json()
        self.assertEqual(len(fixed['document']['nodes']),2)
        node=next(n for n in fixed['document']['nodes'] if n['id']=='edit')
        self.assertEqual(node['domain_version_id'],saved.json()['edit_version_id'])
        rendered=self.command('/edit-exports',dict(edit_version_id=saved.json()['edit_version_id']))
        self.assertEqual(rendered.status_code,200,rendered.text)
        from vsc.post.first_cut_worker import FirstCutWorker
        self.assertEqual(FirstCutWorker(self.store,self.service.storage).run_once(self.p)['status'],'succeeded')
        content=self.client.get(self.base+'/edit-exports/'+rendered.json()['id']+'/content')
        self.assertEqual(content.status_code,200,content.text[:100] if content.status_code!=200 else '')
        self.assertGreater(len(content.content),100)
        self.rev=self.service.get_project(self.p)['revision']
        # A changed editor must not be overwritten by the old canvas binding.
        newer=self.command('/edit-workspace',dict(episode_id=objects['episode'],edit_revision=edit['workspace']['revision'],document=edit['current']['document']))
        self.assertEqual(newer.status_code,200,newer.text)
        conflict=self.command(path+'/edit-input',dict(canvas_revision=fixed['canvas_revision'],node_id='edit'))
        self.assertEqual(conflict.status_code,409,conflict.text)

    def test_canvas_list_projects_current_version_title_time_and_creator_after_rename(self):
        created = self.command("/creative-canvases", {"title": "First title", "document": {"nodes": [], "edges": []}})
        self.assertEqual(created.status_code, 200, created.text)
        canvas = created.json()["id"]
        before = self.client.get(self.base + "/creative-canvases").json()["items"][0]
        changed = self.command("/creative-canvases/" + canvas, {"title": "Renamed", "canvas_revision": 1,
            "document": {"nodes": [], "edges": []}}, method="PUT")
        self.assertEqual(changed.status_code, 200, changed.text)
        row = self.client.get(self.base + "/creative-canvases").json()["items"][0]
        self.assertEqual(row["id"], canvas)
        self.assertEqual(row["title"], "Renamed")
        self.assertEqual(row["version"], 2)
        self.assertEqual(row["created_by"], before["created_by"])
        self.assertEqual(row["created_at"], before["created_at"])
        self.assertGreater(row["updated_at"], before["updated_at"])

    def test_actual_upload_reference_save_reopen_history_conflict_and_auth(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x30\x60\x90")) + chunk(b"IEND", b"")
        staged = self.client.post(self.base + "/uploads", content=png, headers={**self.headers, "X-Filename": "canvas.png"})
        self.assertEqual(staged.status_code, 200, staged.text)
        registered = self.command("/media", {"staged_upload": staged.json()["staged_upload"], "name": "画布真实图片",
            "rights": "owned", "rights_scope": {"purposes": ["*"]}, "source": {"kind": "synthetic-owned", "content": "Synthetic canvas fixture"}})
        self.assertEqual(registered.status_code, 200, registered.text)
        media = registered.json()["id"]
        document = {"nodes": [{"id": "text", "type": "text", "text": "首帧推进"},
            {"id": "image", "type": "image", "media_id": media}, {"id": "video", "type": "video"}],
            "edges": [{"id": "prompt", "source": "text", "target": "video", "port": "prompt"},
                {"id": "frame", "source": "image", "target": "video", "port": "first_frame"}]}
        created = self.command("/creative-canvases", {"title": "真实HTTP画布", "document": document})
        self.assertEqual(created.status_code, 200, created.text)
        canvas = created.json()["id"]
        reopened = self.client.get(self.base + "/creative-canvases/" + canvas)
        self.assertEqual(reopened.status_code, 200, reopened.text)
        image_node = reopened.json()["document"]["nodes"][1]
        self.assertEqual(self.client.get(image_node["preview_url"]).content, png)
        self.assertEqual(len(reopened.json()["document"]["edges"]), 2)
        document["nodes"][0]["text"] = "新提示词"
        path = "/creative-canvases/" + canvas
        old_revision = self.rev
        payload = {"canvas_revision": 1, "title": "新版本", "document": document}
        saved = self.command(path, payload, "PUT", key="saved-response-lost")
        self.assertEqual(saved.status_code, 200, saved.text)
        replay = self.command(path, payload, "PUT", expected=old_revision, key="saved-response-lost")
        self.assertEqual(saved.json(), replay.json())
        conflict = self.command(path, payload, "PUT")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"], "canvas_revision_conflict")
        self.assertEqual(self.client.get(self.base + path).json()["document"]["nodes"][0]["text"], "新提示词")
        self.assertEqual(len(self.client.get(self.base + path + "/history").json()["items"]), 2)
        prepared = self.command(path + "/prepare", {"canvas_revision": 2, "node_id": "video"})
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertEqual(prepared.json()["inputs"][0]["media_id"], media)
        self.assertIn("original_generation_job_required", prepared.json()["gaps"])
        self.assertFalse(prepared.json()["provider_submitted"])
        denied = self.client.put(self.base + path, json={"payload": dict(payload, canvas_revision=2), "expected_revision": self.rev,
            "idempotency_key": "no-session-header"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get("/static/creative-canvas.js").status_code, 200)
        self.assertEqual(self.client.get("/static/creative-canvas.css").status_code, 200)

    def test_agent_fixed_plan_confirm_template_favorite_copy_over_http(self):
        class Backend:
            name="synthetic-http-plan"
            calls=0
            def available(self):return True
            def generate(self,packet,turn,skill):
                self.calls+=1
                return {"message":"明确追加文字的合成计划","questions":[],"action":{"kind":"append_text","title":"HTTP建议","text":"真实保存的建议正文","source_node_id":""}}
        backend=Backend();self.service.canvas_agent_backend=backend
        created=self.command("/creative-canvases",{"title":"HTTP Agent","document":{"nodes":[{"id":"prompt","type":"text","text":"输入"}],"edges":[]}})
        self.assertEqual(created.status_code,200,created.text);canvas=created.json()["id"];path="/creative-canvases/"+canvas
        turn=self.command(path+"/agent-turns",{"canvas_revision":1,"message":"追加一段文字","skill_id":"vsc-script","node_ids":["prompt"]})
        self.assertEqual(turn.status_code,200,turn.text);turn_path="/creative-canvas-agent-turns/"+turn.json()["id"]
        planned=self.client.post(self.base+turn_path+"/execute",headers=self.headers)
        self.assertEqual(planned.status_code,200,planned.text);self.rev=planned.json()["revision"]
        self.assertEqual(planned.json()["status"],"planned")
        self.assertEqual(self.client.post(self.base+turn_path+"/execute",headers=self.headers).status_code,200)
        self.assertEqual(backend.calls,1)
        denied=self.client.post(self.base+turn_path+"/decisions",json={"payload":{"outcome":"confirm","reason":"未授权"},"expected_revision":self.rev,"idempotency_key":"forbidden"})
        self.assertEqual(denied.status_code,403)
        confirmed=self.command(turn_path+"/decisions",{"outcome":"confirm","reason":"明确保存计划"})
        self.assertEqual(confirmed.status_code,200,confirmed.text)
        read=self.client.get(self.base+path).json();self.assertEqual(read["document"]["nodes"][-1]["text"],"真实保存的建议正文")
        published=self.command("/creative-canvas-templates",{"canvas_id":canvas,"canvas_revision":2,"title":"HTTP固定模板"})
        self.assertEqual(published.status_code,200,published.text)
        template=published.json()["id"]
        self.assertEqual(self.command("/creative-canvas-templates/"+template+"/favorite",{"active":True}).status_code,200)
        listing=self.client.get(self.base+"/creative-canvas-templates")
        self.assertEqual(listing.status_code,200,listing.text);self.assertTrue(listing.json()["items"][0]["favorite"])
        fixed=self.client.get(self.base+"/creative-canvas-versions/"+published.json()["version_id"])
        self.assertEqual(fixed.status_code,200,fixed.text);self.assertTrue(fixed.json()["read_only"])
        copied=self.command("/creative-canvas-template-copies",{"template_id":template})
        self.assertEqual(copied.status_code,200,copied.text)
        self.assertEqual(len(self.client.get(self.base+"/creative-canvases/"+copied.json()["id"]).json()["document"]["nodes"]),2)
