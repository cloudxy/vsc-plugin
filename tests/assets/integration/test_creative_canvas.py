"""Real PostgreSQL canvas history, typed references, preparation and recovery."""
from copy import deepcopy
import importlib.util
import os
import unittest
import uuid
from unittest.mock import patch

from support.fixtures.resource_store import ResourceStoreFixture

HAS_DB = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DB, "requires configured isolated PostgreSQL")
class CreativeCanvasTests(ResourceStoreFixture, unittest.TestCase):
    def document(self, media=None, job=None):
        return {"nodes": [{"id": "prompt", "type": "text", "text": "固定画面"},
            {"id": "image", "type": "image", "media_id": media},
            {"id": "video", "type": "video", "job_id": job}],
            "edges": [{"id": "text-video", "source": "prompt", "target": "video", "port": "prompt"},
                {"id": "image-video", "source": "image", "target": "video", "port": "first_frame"}]}

    def test_saved_versions_reopen_replay_conflict_and_copy_clear_execution(self):
        from vsc.assets.resource_service import Conflict
        media = self.media()
        canvas = self.write("create_creative_canvas", {"title": "草稿", "document": self.document(media)})
        opened = self.service.get_creative_canvas(self.p, canvas["id"])
        document = opened["document"]
        for node in document["nodes"]:
            node.pop("preview_url", None)
        document["nodes"][0]["text"] = "保存后的画面"
        payload = {"canvas_id": canvas["id"], "canvas_revision": 1, "title": "已编辑", "document": document}
        revision = self.rev
        saved = self.write("save_creative_canvas", payload, idempotency_key="save-canvas")
        replay = self.service.save_creative_canvas(self.p, payload, actor="test-human", expected_revision=revision,
            idempotency_key="save-canvas")
        self.assertEqual(saved, replay)
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"])["document"]["nodes"][0]["text"], "保存后的画面")
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"], 1)["document"]["nodes"][0]["text"], "固定画面")
        with self.assertRaises(Conflict):
            self.write("save_creative_canvas", payload)
        self.assertEqual(len(self.service.creative_canvas_history(self.p, canvas["id"])["items"]), 2)
        copied = self.write("copy_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 1})
        duplicate = self.service.get_creative_canvas(self.p, copied["id"])
        self.assertEqual(duplicate["document"]["nodes"][1]["media_id"], media)
        self.assertEqual(duplicate["preparations"], [])
        self.assertTrue(all(n["job_id"] is None for n in duplicate["document"]["nodes"]))

    def test_rejects_cross_project_type_cycle_dangling_and_sealed_append(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres import schema as S
        from sqlalchemy import insert, select, update
        from sqlalchemy.exc import IntegrityError
        media = self.media()
        for scenario in ("wrong_port", "cycle", "missing_node", "wrong_media", "foreign_media"):
            document = self.document(media)
            if scenario == "wrong_port":
                document["edges"][1]["port"] = "reference_audio"
            elif scenario == "cycle":
                document["nodes"].append({"id": "other", "type": "image"})
                document["edges"].extend([{"id": "a", "source": "image", "target": "other", "port": "reference"},
                    {"id": "b", "source": "other", "target": "image", "port": "reference"}])
            elif scenario == "missing_node":
                document["edges"][1]["source"] = "absent"
            elif scenario == "wrong_media":
                document["nodes"][2]["media_id"] = media
            else:
                document["nodes"][1]["media_id"] = str(uuid.uuid4())
            with self.subTest(scenario=scenario), self.assertRaises(ResourceError):
                self.write("create_creative_canvas", {"title": scenario, "document": document})
        canvas = self.write("create_creative_canvas", {"document": self.document(media)})
        with self.engine.connect() as conn:
            original = dict(conn.execute(select(S.creative_canvas_nodes).where(S.creative_canvas_nodes.c.project_id == self.p,
                S.creative_canvas_nodes.c.version_id == canvas["version_id"])).mappings().first())
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(insert(S.creative_canvas_nodes).values(dict(original, node_key="late", ordinal=99)))
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.creative_canvas_nodes).where(S.creative_canvas_nodes.c.project_id == self.p).values(title="tampered"))
        other = self.service.create_project({"name": "other", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.service.create_creative_canvas(other["id"], {"document": self.document(media)}, expected_revision=0,
                idempotency_key=uuid.uuid4().hex, actor="test-human")

    def test_preparation_consumes_graph_and_original_job_unknown_is_not_resubmitted(self):
        from sqlalchemy import insert, select, func
        from vsc.adapters.persistence.postgres import schema as S
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        self.artifact("state", "scene-state", [objects["scene"]], {"state_versions": [{"scene_id": objects["scene"]}]})
        image = self.media()
        self.select(self.candidate(objects["shot"], image))
        provider, model = "synthetic_" + uuid.uuid4().hex, str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name="synthetic nonexecuting", modality="video",
                base_url="https://example.invalid", auth_ref="none", enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key="synthetic", modality="video",
                model_version="1", capabilities={"purposes": ["video_clip"], "first_frame": True}, default_params={}, cost_rule={}, enabled=True))
        request = {"prompt": "固定画面", "params": {}, "first_frame_media_id": image}
        run = self.production_run(objects["shot"], request)
        context = self.service.compile_shot_context(self.p, objects["shot"], "video_clip")
        job = self.write("create_generation_job", {"run_version_id": run, "shot_id": objects["shot"], "purpose": "video_clip",
            "modality": "video", "model_id": model, "context_sha256": context["sha256"], "request_payload": request})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submission_unknown"})
        canvas = self.write("create_creative_canvas", {"episode_id": objects["episode"], "document": self.document(image, job["id"])})
        payload = {"canvas_id": canvas["id"], "canvas_revision": 1, "node_id": "video"}
        with patch("httpx.Client.post") as provider_submit:
            prepared = self.write("prepare_creative_canvas", payload, idempotency_key="prepare")
            provider_submit.assert_not_called()
        self.assertTrue(prepared["ready"], prepared["gaps"])
        self.assertEqual(prepared["inputs"][0]["media_id"], image)
        self.assertEqual(prepared["prompt"], request["prompt"])
        self.assertEqual(prepared["job"]["status"], "submission_unknown")
        self.assertTrue(prepared["job"]["recovery_required"])
        self.assertFalse(prepared["provider_submitted"])
        replay = self.service.prepare_creative_canvas(self.p, payload, expected_revision=0,
            idempotency_key="prepare", actor="test-human")
        self.assertEqual(prepared, replay)
        run_request = {"canvas_id": canvas["id"], "canvas_revision": 1, "node_id": "video", "shot_id": objects["shot"],
            "model_id": model, "duration_ms": 5000, "execution_policy": {"version": "bounded-v1",
                "first_draft_due_at": "2099-01-01T00:00:00Z", "stop_submitting_at": "2099-01-01T01:00:00Z",
                "max_attempts_per_purpose": 3, "max_repair_rounds": 1}}
        preview = self.service.preview_creative_canvas_run(self.p, run_request)
        proposed = self.write("propose_creative_canvas_run", {"request": run_request, "preview_sha256": preview["preview_sha256"]})
        self.assertTrue(proposed["needs_approval"])
        self.assertFalse(proposed["provider_submitted"])
        import json
        run_artifact = self.service.get_artifact_version(self.p, proposed["artifact_id"])
        run_document = json.loads(run_artifact["document"])
        self.assertEqual(run_document["series_batch"]["jobs"][0]["request"]["prompt"], "固定画面")
        self.assertEqual(run_document["series_batch"]["jobs"][0]["request"]["first_frame_media_id"], image)
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"])["runs"][0]["artifact_id"], proposed["artifact_id"])
        doc = self.document(image, job["id"])
        doc["nodes"][0]["text"] = "不同输入"
        self.write("save_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 1, "document": doc})
        mismatch = self.write("prepare_creative_canvas", dict(payload, canvas_revision=2))
        self.assertIn("job_prompt_mismatch", mismatch["gaps"])
        self.assertFalse(mismatch["ready"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id == self.p)).scalar_one(), 1)
        self.write("save_creative_canvas", {"canvas_id": canvas["id"], "canvas_revision": 2, "document": {"nodes": [], "edges": []}})
        self.assertEqual(self.service.get_generation_job(self.p, job["id"])["status"], "submission_unknown")
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas["id"], 1)["preparations"][0]["job_id"], job["id"])

@unittest.skipUnless(TEST_URL and HAS_DB, 'requires isolated PostgreSQL')
class CanvasExecutionTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.artifact(objects=[self.objects['shot']]);self.artifact('state','scene-state',[self.objects['scene']],{'state_versions':[{'scene_id':self.objects['scene']}]})
        self.policy=dict(version='bounded-v1',first_draft_due_at='2099-01-01T00:00:00Z',stop_submitting_at='2099-01-01T01:00:00Z',max_attempts_per_purpose=3,max_repair_rounds=1,authorization={'mode':'new_batch','reason':'合成工程批次'})
        self.models=[]
        for modality,purpose in [('image','shot_keyframe'),('image','shot_keyframe'),('audio','sfx'),('video','video_clip')]:
            provider='synthetic_'+uuid.uuid4().hex;self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_TEST_KEY'),actor='test-admin')
            model=self.service.register_model(dict(provider_id=provider,model_key=modality,model_version='offline',modality=modality,capabilities=dict(purposes=[purpose],first_frame=True)),actor='test-admin');self.models.append(dict(model,adapter_available=True,enabled=True))
        self.config=patch('vsc.production.resource_settings.ResourceSettings.list',return_value={'configurations':self.models});self.config.start();self.addCleanup(self.config.stop)
        self.canvas=self.write('create_creative_canvas',dict(episode_id=self.objects['episode'],document={'nodes':[{'id':'i','type':'image','text':'独立构图'},{'id':'a','type':'audio','text':'雨声'},{'id':'v','type':'video','text':'走近'}],'edges':[{'id':'iv','source':'i','target':'v','port':'first_frame'}]}))
    def request(self,node='i'):
        model=self.models[0 if node=='i' else 2 if node=='a' else 3]
        return dict(canvas_id=self.canvas['id'],canvas_revision=1,node_id=node,shot_id=self.objects['shot'],purpose=model['capabilities']['purposes'][0],model_ids=[model['id']]+([self.models[1]['id']] if node=='i' else []),execution_policy=self.policy)
    def prepare(self,node='i'):
        request=self.request(node);preview=self.service.preview_creative_canvas_run(self.p,request);self.assertTrue(preview['ready'],preview)
        return self.write('propose_creative_canvas_run',dict(request=request,preview_sha256=preview['preview_sha256']))
    def test_typed_image_audio_dependency_and_original_approval_boundary(self):
        batch=self.service.preview_canvas_execution_batch(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,nodes=[{k:v for k,v in self.request(n).items() if k not in {'canvas_id','canvas_revision'}} for n in ['i','a','v']]))
        self.assertEqual([x['result']['ready'] for x in batch['items']],[True,True,False]);self.assertEqual(batch['items'][2]['result']['gaps'][0]['code'],'canvas_dependency_waiting')
        image=self.prepare();audio=self.prepare('a');result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id'],audio['step_id']]),'test-human')
        self.assertTrue(all(r['status']=='needs_approval' for r in result['runs']));self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        self.write('decide_artifact',dict(artifact_id=image['artifact_id'],reason='合成工程批准固定运行'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id']]),'test-human');self.rev=result['revision']
        self.assertEqual(result['runs'][0]['created_count'],1,result)
        again=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[image['step_id']]),'test-human');self.assertEqual(again['runs'][0]['existing_count'],1);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
        self.write('decide_artifact',dict(artifact_id=audio['artifact_id'],reason='合成声音固定运行批准'))
        sound=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[audio['step_id']]),'test-human');self.rev=sound['revision'];self.assertEqual(sound['runs'][0]['created_count'],1,sound)
        sound_job=self.service.get_generation_job(self.p,sound['runs'][0]['tasks'][0]['job_id']);self.assertEqual((sound_job['modality'],sound_job['purpose']),('audio','sfx'))
        step=self.service.get_creative_canvas(self.p,self.canvas['id'])['execution_steps'][0];self.assertEqual(step['shot_id'],self.objects['shot']);self.assertEqual(step['run_artifact_id'],image['artifact_id'])
    def test_unknown_job_never_creates_a_fallback_or_resubmits(self):
        from vsc.assets.resource_service import ResourceError
        row=self.prepare();self.write('decide_artifact',dict(artifact_id=row['artifact_id'],reason='合成工程批准'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.rev=result['revision'];job=result['runs'][0]['tasks'][0]['job_id']
        self.write('update_generation_job',dict(job_id=job,status='submission_unknown',raw_response={'synthetic':'unknown submission'}))
        with self.assertRaises(ResourceError) as caught:self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.assertEqual(caught.exception.code,'canvas_fallback_not_terminal')
        again=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.assertEqual(again['runs'][0]['existing_count'],1);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1);self.assertEqual(self.service.get_generation_job(self.p,job)['status'],'submission_unknown')

    def test_ordered_fallback_rejects_unfinished_and_requires_new_approval(self):
        from vsc.assets.resource_service import ResourceError
        row=self.prepare()
        with self.assertRaises(ResourceError):self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.write('decide_artifact',dict(artifact_id=row['artifact_id'],reason='合成工程批准'))
        result=self.service.advance_canvas_execution(self.p,dict(canvas_id=self.canvas['id'],canvas_revision=1,step_ids=[row['step_id']]),'test-human');self.rev=result['revision'];job=result['runs'][0]['tasks'][0]['job_id']
        with self.assertRaises(ResourceError):self.service.preview_canvas_fallback(self.p,row['step_id'])
        self.write('update_generation_job',dict(job_id=job,status='failed',raw_response={'synthetic':'definite local failure before submission'}))
        preview=self.service.preview_canvas_fallback(self.p,row['step_id']);self.assertEqual(preview['model_ids'],[self.models[1]['id']]);self.assertEqual(preview['artifact']['document']['execution_policy']['authorization']['run_version_id'],row['artifact_id'])
        successor=self.write('propose_canvas_fallback',dict(step_id=row['step_id'],preview_sha256=preview['preview_sha256']));self.assertFalse(self.service.get_artifact_version(self.p,successor['artifact_id'])['approved']);self.assertEqual(self.service.list_generation_jobs(self.p)['total'],1)
