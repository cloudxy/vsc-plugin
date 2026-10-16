"""Synthetic resource fixtures shared by isolated PostgreSQL test suites."""
import hashlib
import importlib.util
import os
import uuid

HAS_DB_DEPS = all(importlib.util.find_spec(p) for p in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


class ResourceStoreFixture:
    @classmethod
    def setUpClass(cls):
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        cls.db = isolated_postgres(TEST_URL)
        cls.engine = cls.db.__enter__()
        cls.store = PostgresResourceStore(engine=cls.engine)
        cls.service = ResourceService(cls.store)


    @classmethod
    def tearDownClass(cls):
        cls.db.__exit__(None, None, None)


    def setUp(self):
        self.project = self.service.create_project({"name": "资源关系测试", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
        self.p = self.project["id"]
        self.rev = 0


    def write(self, method, payload, **kw):
        result = getattr(self.service, method)(self.p, payload, expected_revision=self.rev,
            idempotency_key=kw.pop("idempotency_key", uuid.uuid4().hex), actor=kw.pop("actor", "test-human"), **kw)
        self.rev = result["revision"]
        return result


    def hierarchy(self):
        parent = None
        objects = {}
        for kind in ("work", "episode", "scene", "sequence", "shot"):
            row = self.write("create_object", {"kind": kind, "display_code": kind.upper(), "parent_id": parent, "ordinal": 0})
            objects[kind] = row["id"]
            parent = row["id"]
        return objects


    def media(self, name="图片", rights="owned", modality="image"):
        sha = hashlib.sha256((name + modality).encode()).hexdigest()
        row = self.write("register_media", {"name": name, "modality": modality, "sha256": sha,
            "size_bytes": len(name.encode()), "mime_type": {"image": "image/png", "video": "video/mp4", "audio": "audio/wav"}[modality],
            "storage": "local", "object_key": sha + ".bin", "rights": rights,
            "source": {"kind": "test-owned", "content": "owned test evidence " + name}})
        self.write("record_media_check", {"media_id": row["id"], "checker": "test-probe", "criteria_version": "1", "outcome": "pass"})
        return row["id"]


    def artifact(self, key="shot", kind="shot-plan", objects=None, projections=None):
        projections = projections or {}
        document = dict({"spec": "固定规格"}, **projections)
        row = self.write("create_artifact", dict({"artifact_key": key, "artifact_type": kind,
            "document": document, "object_ids": objects or []}, **projections))
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "真实测试操作者批准"})
        return row["id"]


    def candidate(self, target, media, role="first_frame", slot_key="main", **extra):
        row = self.write("propose_binding", dict({"target_object_id": target, "media_id": media, "role": role, "slot_key": slot_key}, **extra))
        self.write("record_review", {"candidate_id": row["candidate_id"], "outcome": "pass", "reason": "用途匹配", "reviewer_type": "human"})
        return row


    def select(self, candidate):
        return self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "人工选择该候选"})


    def production_run(self, shot_id, request, purpose="video_clip", modality="video", candidate_count=1):
        from vsc.adapters.persistence.postgres.budget_store import native_units
        context = self.service.compile_shot_context(self.p, shot_id, purpose=purpose)
        pins = [{"id": a["id"], "sha256": a["sha256"]} for a in context["artifacts"]]
        logical = dict(request, shot_id=shot_id, purpose=purpose, modality=modality, context_sha256=context["sha256"])
        row = self.write("create_artifact", {"artifact_key": "run", "artifact_type": "production-run",
            "document": {"approved_inputs": pins, "jobs": [{"candidate_no": number, "request": logical} for number in range(candidate_count)],
                "operations": {"series:%s:%s:%s" % (shot_id, purpose, number): native_units(logical) for number in range(candidate_count)}},
            "object_ids": [shot_id], "dependency_ids": [p["id"] for p in pins]})
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "批准明确任务及固定输入"})
        self.assertEqual(self.service.compile_shot_context(self.p, shot_id, purpose=purpose)["sha256"], context["sha256"])
        return row["id"]


    def seed_generation_timeline_render(self):
        objects = self.hierarchy()
        self.artifact(objects=[objects["shot"]])
        self.artifact("state", "scene-state", [objects["scene"]], {"state_versions": [{"scene_id": objects["scene"]}]})
        first = self.media("首帧")
        chosen = self.select(self.candidate(objects["shot"], first))
        context = self.service.compile_shot_context(self.p, objects["shot"], purpose="video_clip")
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["media"][0]["binding_decision_id"], chosen["decision_id"])
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        provider_id = "fake_" + uuid.uuid4().hex
        model_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider_id, name="offline fake", modality="video", base_url="https://example.invalid", auth_ref="none", enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model_id, provider_id=provider_id, model_key="fake", modality="video",
                model_version="1", capabilities={"purposes": ["video_clip"], "first_frame": True}, default_params={}, cost_rule={}, enabled=True))
        request = {"params": {"seed": 123}, "prompt": "固定画面", "first_frame_media_id": first}
        run = self.production_run(objects["shot"], request)
        context = self.service.compile_shot_context(self.p, objects["shot"], purpose="video_clip")
        job = self.write("create_generation_job", {"run_version_id": run, "shot_id": objects["shot"], "purpose": "video_clip", "modality": "video",
            "model_id": model_id, "context_sha256": context["sha256"], "request_payload": request})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submission_unknown"})
        from vsc.assets.resource_service import ResourceError
        with self.assertRaises(ResourceError):
            self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "ext-1"})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "ext-1", "recovery_evidence": {"query": "found existing"}})
        video = self.media("成片候选", modality="video")
        self.write("update_generation_job", {"job_id": job["id"], "status": "succeeded", "outputs": [{"media_id": video}]})
        usage = self.service.get_media_usage(self.p, first)
        self.assertEqual(usage["job_inputs"][0]["job_id"], job["id"])
        self.assertEqual(self.service.get_media_usage(self.p, video)["job_outputs"][0]["job_id"], job["id"])
        video_candidate = self.candidate(objects["shot"], video, role="video_take")
        video_decision = self.select(video_candidate)
        after = self.service.compile_shot_context(self.p, objects["shot"], purpose="video_clip")
        self.assertNotIn("video_take", {m["role"] for m in after["media"]})
        items = [{"shot_id": objects["shot"], "track_key": "video", "offset_frame": 0, "duration_frames": 120,
                  "media": [{"media_id": video, "binding_decision_id": video_decision["decision_id"],
                             "role": "video_take", "source_out_frame": 120}]}]
        timeline_artifact = self.write("create_artifact", {"artifact_key": "timeline", "artifact_type": "edit-timeline", "document": {"items": items}})
        self.write("decide_artifact", {"artifact_id": timeline_artifact["id"], "reason": "批准固定剪辑"})
        timeline = self.write("freeze_timeline", {"artifact_id": timeline_artifact["id"], "episode_id": objects["episode"], "items": items})
        render_artifact = self.artifact("render", "render-spec")
        delivery = self.media("交付视频", modality="video")
        render = self.write("freeze_render", {"timeline_id": timeline["id"], "artifact_id": render_artifact,
            "tool": "offline-render", "tool_version": "1", "outputs": [{"media_id": delivery}]})
        self.write("retire_binding", {"slot_id": video_candidate["slot_id"], "reason": "只改变未来选择"})
        self.assertEqual(self.service.get_media_usage(self.p, video)["render_inputs"][0]["render_id"], render["id"])
        self.assertEqual(self.service.get_media_usage(self.p, delivery)["render_outputs"][0]["render_id"], render["id"])
