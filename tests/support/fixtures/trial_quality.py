"""Shared offline trial/quality fixture. No test cases are imported."""
import uuid
from support.fixtures.resource_store import ResourceStoreFixture


class TrialQualityFixture(ResourceStoreFixture):
    def setUp(self):
        self.project = self.service.create_project({"name": "synthetic trial", "profile_snapshot": {
            "profile_id": "vsc.synthetic", "version": "1", "stages": [
                {"id": "script", "required": ["screenplay"]}, {"id": "animatic", "required": ["animatic"]}]}}, actor="test-human")
        self.p, self.rev = self.project["id"], 0
        self.objects = self.hierarchy()
        self.script = self.artifact("script", "screenplay")
        self.artifact("bible", "asset-bible")
        self.artifact("shots", "shot-plan", [self.objects["shot"]])
        self.artifact("state", "scene-state", [self.objects["scene"]], {"state_versions": [{"scene_id": self.objects["scene"]}]})
        self.first = self.media("first frame")
        self.select(self.candidate(self.objects["shot"], self.first))
        provider = "offline_" + uuid.uuid4().hex
        self.service.register_provider({"id": provider, "base_url": "https://example.invalid", "auth_ref": "UNUSED_TEST_CREDENTIAL"}, actor="test-human")
        model = self.service.register_model({"provider_id": provider, "model_key": "synthetic", "model_version": "1", "modality": "video",
            "capabilities": {"purposes": ["video_clip"], "first_frame": True}}, actor="test-human")
        self.model = model["id"]
        self.context = self.service.compile_shot_context(self.p, self.objects["shot"], purpose="video_clip")
        self.assertTrue(self.context["ready"], self.context["gaps"])

    def approved(self, key, kind, document, **extra):
        row = self.write("create_artifact", dict(artifact_key=key, artifact_type=kind, document=document, **extra))
        self.write("decide_artifact", {"artifact_id": row["id"], "reason": "synthetic human approval"})
        return self.service.get_artifact_version(self.p, row["id"])

    def fixture_run(self, mutate=None, phase="trial"):
        from vsc.production.run_authorization import normalize_request
        from vsc.adapters.persistence.postgres.production_guard import requests_for
        from vsc.adapters.persistence.postgres.values import digest
        from vsc.adapters.persistence.postgres.budget_store import native_units
        raw = {"prompt": "synthetic frame", "first_frame_media_id": self.first}
        logical = normalize_request(raw, self.objects["shot"], "video_clip", "video")
        requests = requests_for({"jobs": [{"candidate_no": 0, "request": logical}]})
        key = next(iter(requests))
        method = self.approved("method", "trial-method", {"method": "synthetic bounded camera method"})
        request = self.approved("fixed-request", "quality-request", logical)
        spec = self.service.get_artifact_version(self.p, self.script)
        plan = {"format": "vsc.quality-plan/v1", "project_id": self.p,
            "run_binding": {"plan_sha256": digest(requests), "job_ids": [key]},
            "inputs": [{"id": "actual", "job_id": key, "channel": "request", "ref": {"artifact_id": request["id"], "sha256": request["sha256"]}}],
            "requirements": [{"id": "identity", "priority": "must", "criterion": "preserve identity", "tolerance": "fixed",
                "source": {"artifact_id": spec["id"], "sha256": spec["sha256"], "pointer": "/spec"},
                "bindings": [{"input_id": "actual", "pointer": "/prompt", "expected": "synthetic frame"}]}],
            "risks": [], "attempts": []}
        if mutate:
            mutate(plan)
        package = self.approved("quality", "quality-plan", plan)
        pins = [{"id": a["id"], "sha256": a["sha256"]} for a in self.context["artifacts"]]
        pins += [{"id": a["id"], "sha256": a["sha256"]} for a in (method, request, package)]
        run = {"project_id": self.p, "phase": phase, "plan_sha256": digest(requests), "approved_inputs": pins,
            "jobs": [{"candidate_no": 0, "request": logical}], "operations": {key: native_units(logical)},
            "quality_plan": {"artifact_id": package["id"], "sha256": package["sha256"]},
            "trial": {"trial_id": "synthetic-trial", "hypothesis": "one controlled camera move", "criteria": "fixed framing",
                "stop_condition": "one candidate only", "context_sha256": self.context["sha256"], "method_sha256": method["sha256"],
                "max_remote_jobs": 1, "allowed_shot_ids": [self.objects["shot"]], "allowed_asset_ids": [], "output_use": "preproduction_only"}}
        if phase != "trial":
            run.pop("trial")
        row = self.approved("run", "production-run", run, dependency_ids=[a["id"] for a in pins])
        return row, package, logical

    def job(self, run, logical):
        return self.write("create_generation_job", {"run_version_id": run["id"], "shot_id": self.objects["shot"], "purpose": "video_clip",
            "modality": "video", "model_id": self.model, "context_sha256": self.context["sha256"], "request_payload": logical})
