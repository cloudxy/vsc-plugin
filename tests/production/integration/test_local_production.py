"""Local proposals retain fixed versions and enqueue only approved exact targets."""
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
import wave

from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture, png_bytes
from vsc.assets.local_production import LocalProduction
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
from vsc.production.resource_worker import ResourceWorker


def prepare_series_script(fixture):
    """Real production-v2 upstream approvals, shared with the browser fixture."""
    from support.paths import ROOT
    from vsc.assets.resource_service import dependency_requirements
    profile = fixture.service.get_project(fixture.p)["profile_snapshot"]
    pins = {}
    for stage in profile["stages"][:3]:
        for kind in stage["required"]:
            if kind == "vsc.creative_brief":
                body = {"format": "vsc.creative-brief/v1", "audience": "Synthetic audience", "desired_experience": "Clarity",
                    "decision_owner": "fixture-human", "objectives": [{"id": "clarity", "goal": "Clear action", "success_evidence": "Offline check"}],
                    "nonnegotiables": [], "conflict_policy": "Fixture human decides"}
            elif kind in {"vsc.adaptation_contract", "vsc.story_bible"}:
                body = "Synthetic fixed upstream evidence"
            else:
                name = {"vsc.source_map": "source-map", "vsc.adaptation_plan": "adaptation-map", "vsc.episode_beats": "episode-beats"}[kind]
                body = json.loads((ROOT / "templates" / (name+".json")).read_text())
                if kind == "vsc.source_map":
                    body["summary"] = "Synthetic source summary"
                    body["source_units"][0].update(fact_or_claim="Synthetic fact", narrative_function="Establish action")
                elif kind == "vsc.adaptation_plan":
                    body["project_id"] = fixture.p
                    body["episodes"][0]["id"] = fixture.objects["episode"]
                    body["screen_units"][0].update(episode_id=fixture.objects["episode"], scene_id=fixture.objects["scene"])
                else:
                    body["episodes"][0].update(id=fixture.objects["episode"], ending="Synthetic closure")
                    body["episodes"][0]["beats"][0].update(action="Synthetic action", change="Action changes", screen_unit_ids=["SC-001"])
            requirements, _ = dependency_requirements(profile, kind)
            identifier = fixture.artifact(kind, kind, body, [pins[key] for key in requirements])
            pins[kind] = identifier
    adaptation = fixture.service.get_artifact_version(fixture.p, pins["vsc.adaptation_plan"])
    document = {"format": "vsc.screenplay/v1", "project_id": fixture.p, "scope": fixture.objects["episode"], "body": "Synthetic screenplay",
        "adaptation_refs": [{"id": adaptation["id"], "sha256": adaptation["sha256"]}], "scenes": [{"id": fixture.objects["scene"],
        "estimated_duration_ms": 1000, "actions": [{"id": "A1", "text": "Synthetic action", "narrative_refs": ["SC-001"]}], "dialogue": [], "silence": []}]}
    requirements, _ = dependency_requirements(profile, "vsc.screenplay")
    row = fixture.write("create_artifact", {"artifact_type": "vsc.screenplay", "artifact_key": "formal-screenplay", "document": document,
        "object_ids": [fixture.objects["episode"]], "dependency_ids": [pins[key] for key in requirements]})
    fixture.write("decide_artifact", {"artifact_id": row["id"], "reason": "Approve real Profile fixed screenplay"})
    return row["id"]


class OfflineProvider:
    def __init__(self, modality, content):
        self.modality, self.content = modality, content
    def submit(self, request):
        return JobHandle("fixture", "offline", None, {"offline": True})
    def poll(self, handle):
        return JobStatus("succeeded", raw=handle.raw)
    def parse_result(self, raw):
        return [GeneratedAsset(self.modality, inline_bytes=self.content)]


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL"), "requires explicit isolated PostgreSQL URL")
class LocalProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(os.environ["VSC_TEST_DATABASE_URL"])
        cls.engine = cls.database.__enter__()
    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)
    def setUp(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(self.temp.name))
        self.fixture = ResourceFixture(self.service)
        self.local = LocalProduction(self.service)
        self.service.register_provider({"id": "fixture", "base_url": "https://example.invalid", "auth_ref": "OFFLINE_KEY"}, actor="fixture-human")
    def write(self, method, payload, key=None):
        return getattr(self.local, method)(self.fixture.p, payload, expected_revision=self.service.get_project(self.fixture.p)["revision"],
            idempotency_key=key or uuid.uuid4().hex, actor="fixture-human")
    def propose(self, payload):
        preview = self.local.preview(self.fixture.p, payload)
        return preview, self.write("propose", dict(payload, preview_sha256=preview["preview_sha256"]))
    def model(self, modality, purposes, **extra):
        return self.service.register_model(dict(provider_id="fixture", model_key="local-"+uuid.uuid4().hex, model_version="1",
            modality=modality, capabilities={"purposes": purposes}, **extra), actor="fixture-human")["id"]
    def complete(self, job, modality, content):
        ResourceWorker(self.service, lambda j, s: OfflineProvider(modality, content)).run_once(self.fixture.p)
        self.assertEqual(self.service.get_generation_job(self.fixture.p, job["id"])["status"], "succeeded")

    def test_resample_new_approved_run_enqueues_exact_candidate_and_replay_reuses_it(self):
        model = self.model("image", ["keyframe"])
        source = self.fixture.job("image", "keyframe", model, {"params": {"seed": 1}})
        self.complete(source, "image", png_bytes())
        option = self.local.options(self.fixture.p, "resample", source["id"])["job"]
        self.assertEqual((option["params"], option["model"]["id"]), ({"seed": 1}, model))
        other_project = ResourceFixture(self.service)
        with self.assertRaises(ResourceError):
            self.local.options(other_project.p, "resample", source["id"])
        payload = {"action": "resample", "job_id": source["id"], "params": {"seed": 2}}
        preview, proposal = self.propose(payload)
        self.assertEqual(len(preview["targets"]), 1)
        target = preview["targets"][0]
        self.assertEqual((target["id"], target["after_params"]["seed"], target["candidate_no"]), (source["id"], 2, 1))
        run = proposal["artifact"]["id"]
        with self.assertRaises(ResourceError) as caught:
            self.write("enqueue", {"artifact_id": run})
        self.assertEqual(caught.exception.code, "run_unapproved")
        self.fixture.write("decide_artifact", {"artifact_id": run, "reason": "Approve exact resampling request"})
        result = self.write("enqueue", {"artifact_id": run}, key="explicit-sample-once")
        self.fixture.artifact("shot-spec", "shot-plan", {"spec": "New current input after enqueue"})
        replay = self.write("enqueue", {"artifact_id": run}, key="explicit-sample-once")
        self.assertEqual(result, replay)
        new = self.service.get_generation_job(self.fixture.p, result["jobs"][0]["id"])
        self.assertNotEqual(new["id"], source["id"])
        self.assertEqual((new["shot_id"], new["purpose"], new["candidate_no"], new["request_payload"]["params"]),
                         (self.fixture.objects["shot"], "keyframe", 1, {"seed": 2}))
        self.assertEqual(self.service.list_generation_jobs(self.fixture.p)["total"], 2)
        with self.assertRaises(ResourceError):
            self.write("enqueue", {"artifact_id": run, "candidate_no": 999})

    def test_unknown_source_and_changed_preview_do_not_create_proposals(self):
        model = self.model("image", ["keyframe"])
        source = self.fixture.job("image", "keyframe", model)
        self.fixture.write("update_generation_job", {"job_id": source["id"], "status": "submission_unknown"})
        with self.assertRaises(ResourceError) as caught:
            self.local.preview(self.fixture.p, {"action": "resample", "job_id": source["id"]})
        self.assertEqual(caught.exception.code, "local_recovery_required")
        other = self.fixture.job("image", "keyframe", model)
        self.complete(other, "image", png_bytes())
        payload = {"action": "resample", "job_id": other["id"]}
        preview = self.local.preview(self.fixture.p, payload)
        self.fixture.write("create_object", {"kind": "asset", "asset_kind": "prop", "display_code": "REVISION"})
        with self.assertRaises(ResourceError) as caught:
            self.write("propose", dict(payload, preview_sha256=preview["preview_sha256"]))
        self.assertEqual(caught.exception.code, "local_preview_changed")

    def test_replace_one_instance_retains_other_instance_identity_and_historical_spec(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        cup = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "prop", "display_code": "CUP"})["id"]
        specs = []
        for number in (1, 2):
            artifact = self.fixture.artifact("cup-spec", "asset-bible", {"asset_specs": [{"asset_id": cup, "variant_key": "v"+str(number)}]})
            with self.engine.connect() as conn:
                specs.append((artifact, conn.execute(select(S.asset_spec_versions.c.id).where(S.asset_spec_versions.c.project_id == self.fixture.p,
                    S.asset_spec_versions.c.artifact_id == artifact)).scalar_one()))
        document = {"format": "vsc.creative-relations/v1", "project_id": self.fixture.p, "instances": [
            {"key": key, "label": key, "asset_id": cup, "spec_version_id": specs[0][1], "scene_id": self.fixture.objects["scene"],
             "shot_id": self.fixture.objects["shot"], "state": {"position": position}} for key, position in (("cup-left", "left"), ("cup-right", "right"))]}
        original = self.fixture.artifact("cups", "creative-relations", document, [specs[0][0]])
        with self.engine.connect() as conn:
            instance = conn.execute(select(S.asset_use_instances.c.id).where(S.asset_use_instances.c.project_id == self.fixture.p,
                S.asset_use_instances.c.artifact_id == original, S.asset_use_instances.c.instance_key == "cup-left")).scalar_one()
        options = self.local.options(self.fixture.p, "replace_instance", instance)
        self.assertEqual({row["id"] for row in options["specs"]}, {row[1] for row in specs})
        other_project = ResourceFixture(self.service)
        with self.assertRaises(ResourceError):
            self.local.options(other_project.p, "replace_instance", instance)
        preview, proposal = self.propose({"action": "replace_instance", "instance_id": instance, "replacement_spec_version_id": specs[1][1]})
        self.assertEqual([target["key"] for target in preview["targets"]], ["cup-left"])
        revised = json.loads(self.service.get_artifact_version(self.fixture.p, proposal["artifact"]["id"])["content"])
        self.assertEqual(revised["instances"][1], document["instances"][1])
        self.assertEqual(revised["instances"][0]["spec_version_id"], specs[1][1])
        self.assertTrue(next(row for row in self.service.list_artifacts(self.fixture.p)["items"] if row["id"] == original)["current"])
        self.fixture.write("decide_artifact", {"artifact_id": proposal["artifact"]["id"], "reason": "Approve one physical instance revision"})
        self.assertEqual(json.loads(self.service.get_artifact_version(self.fixture.p, original)["content"]), document)
        with self.engine.connect() as conn:
            rows = conn.execute(select(S.asset_use_instances).where(S.asset_use_instances.c.project_id == self.fixture.p,
                S.asset_use_instances.c.artifact_id == proposal["artifact"]["id"])).mappings().all()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["asset_id"] for row in rows}, {cup})
        from vsc.assets.resource_impact import ResourceImpact
        impact = ResourceImpact(SimpleNamespace(service=self.service, _reader=lambda p: None)).query(self.fixture.p,
            source="artifact:"+specs[0][0], replacement="artifact:"+specs[1][0])
        self.assertEqual(impact["comparison"]["status"], "changed")
        self.assertTrue(any(item["kind"] == "instance" for item in impact["consumers"]))

    def test_redo_sound_requires_purpose_and_never_enqueues_neighbor_shot(self):
        character = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "CHAR"})["id"]
        voice = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "voice", "display_code": "VOICE"})["id"]
        audio = BytesIO()
        with wave.open(audio, "wb") as writer:
            writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(24000); writer.writeframes(b"\x00\x00"*24000)
        for target, role, content, name in ((character,"identity_face",png_bytes(),"face.png"),(voice,"voice_sample",audio.getvalue(),"voice.wav")):
            staged = self.service.storage.stage_upload(BytesIO(content),name)
            media = self.fixture.write("register_media", {"staged_upload": staged["staged_upload"], "name": name,
                "source": {"kind":"fixture","content":"owned synthetic bytes"},"rights":"unknown"})["id"]
            self.fixture.select_media(media,role,target)
        own = self.fixture.objects["shot"]
        neighbor = self.fixture.write("create_object", {"kind":"shot","parent_id":self.fixture.objects["sequence"],"display_code":"NEIGHBOR","ordinal":1})["id"]
        line, voice_spec = str(uuid.uuid4()), str(uuid.uuid4())
        script = self.fixture.artifact("script","screenplay",{"script_lines":[{"id":line,"scene_id":self.fixture.objects["scene"],"speaker_id":character,"line_key":"L001","text":"Synthetic line"}]})
        self.fixture.artifact("coverage","coverage-plan",{"line_coverage":[{"shot_id":shot,"line_id":line,"start_char":0,"end_char":len("Synthetic line")} for shot in (own,neighbor)]},[script])
        self.fixture.artifact("voice","voice-spec",{"voice_specs":[{"id":voice_spec,"voice_id":voice}],"voice_bindings":[{"character_id":character,"voice_spec_id":voice_spec}]})
        model=self.model("audio",["dialogue_dry"],default_params={"voice_map":{voice:{"engine":"fixture","voice":"voice"}}})
        for shot in (own,neighbor):
            self.fixture.objects["shot"]=shot
            if shot != own:
                self.fixture.artifact("state-"+shot,"scene-state",{"state_versions":[{"scene_id":self.fixture.objects["scene"],"shot_id":shot,"entities":[]}]})
            job=self.fixture.job("audio","dialogue_dry",model,{"prompt":"Synthetic line","script_line_ids":["L001"]})
            self.complete(job,"audio",audio.getvalue())
        self.fixture.objects["shot"]=own
        self.assertEqual(self.local.options(self.fixture.p,"redo_sound",own)["purposes"],["dialogue_dry"])
        with self.assertRaises(ResourceError):
            self.local.preview(self.fixture.p,{"action":"redo_sound","shot_id":own})
        preview,proposal=self.propose({"action":"redo_sound","shot_id":own,"purpose":"dialogue_dry"})
        self.assertEqual({target["shot_id"] for target in preview["targets"]},{own})
        self.assertEqual({target["modality"] for target in preview["targets"]},{"audio"})
        self.fixture.write("decide_artifact",{"artifact_id":proposal["artifact"]["id"],"reason":"Approve own-shot sound only"})
        result=self.write("enqueue",{"artifact_id":proposal["artifact"]["id"]})
        targets=[self.service.get_generation_job(self.fixture.p,row["id"]) for row in result["jobs"]]
        self.assertEqual(len(targets),1)
        self.assertEqual((targets[0]["shot_id"],targets[0]["purpose"],targets[0]["modality"]),(own,"dialogue_dry","audio"))

    def test_real_profile_run_contract_is_preserved_and_invalid_legacy_source_cannot_bypass_it(self):
        from vsc.project.state import profile_for
        from vsc.adapters.persistence.postgres.production_guard import requests_for
        from vsc.adapters.persistence.postgres.budget_store import native_units, operation_key
        from vsc.adapters.persistence.postgres.values import digest
        self.fixture = ResourceFixture(self.service, profile_for("vsc.series-pg"))
        prepare_series_script(self.fixture)
        model = self.model("image", ["keyframe"])
        context = self.service.compile_shot_context(self.fixture.p, self.fixture.objects["shot"], "keyframe")
        request = dict(shot_id=self.fixture.objects["shot"], modality="image", purpose="keyframe", prompt="Offline fixed image", params={})
        pins = [{"id": row["id"], "sha256": row["sha256"]} for row in context["artifacts"]]
        body = {"format": "vsc.production-run/v1", "project_id": self.fixture.p, "scope": "project", "phase": "production",
            "approved_inputs": pins, "review_after": [], "quality_policy": {"requires_human_review": True},
            "series_batch": {"jobs": [{"candidate_no": 0, "request": request}]},
            "operations": {operation_key(request, 0): native_units(request)}}
        body["plan_sha256"] = digest(requests_for(body))
        def source(document, unchecked=False):
            payload = {"artifact_type": "vsc.production_run", "artifact_key": "formal-"+uuid.uuid4().hex,
                "stage": "production", "document": document, "dependency_ids": [row["id"] for row in pins]}
            if unchecked:
                # Explicit legacy repository fixture: a previously unchecked
                # immutable run must not let the new public proposal bypass its contract.
                kw = dict(actor="fixture-human", expected_revision=self.service.get_project(self.fixture.p)["revision"], idempotency_key=uuid.uuid4().hex)
                run = self.service.store.create_artifact(self.fixture.p, payload, **kw)
                kw.update(expected_revision=run["revision"], idempotency_key=uuid.uuid4().hex)
                self.service.store.decide_artifact(self.fixture.p, {"artifact_id": run["id"], "reason": "Explicit legacy fixture"}, **kw)
            else:
                run = self.fixture.write("create_artifact", payload)
                self.fixture.write("decide_artifact", {"artifact_id": run["id"], "reason": "Approve typed offline fixture"})
            # Seed an old terminal intent through the real relational writer,
            # without claiming that this incomplete Profile passed a production Gate.
            job = self.service.store.create_generation_job(self.fixture.p, {"run_version_id": run["id"],
                "shot_id": self.fixture.objects["shot"], "purpose": "keyframe", "modality": "image", "model_id": model,
                "request_payload": request, "context_sha256": context["sha256"]}, actor="fixture-human",
                expected_revision=self.service.get_project(self.fixture.p)["revision"], idempotency_key=uuid.uuid4().hex)
            self.fixture.write("update_generation_job", {"job_id": job["id"], "status": "cancelled"})
            return job
        job = source(body)
        preview, proposal = self.propose({"action": "resample", "job_id": job["id"]})
        self.assertEqual((preview["artifact"]["artifact_type"], preview["artifact"]["stage"]), ("vsc.production_run", "production"))
        document = preview["artifact"]["document"]
        self.assertEqual((document["format"], document["phase"], document["quality_policy"]),
            (body["format"], body["phase"], body["quality_policy"]))
        self.assertNotEqual(document["plan_sha256"], body["plan_sha256"])
        self.fixture.write("decide_artifact", {"artifact_id": proposal["artifact"]["id"], "reason": "Approve exact formal proposal"})
        with self.assertRaises(ResourceError) as caught:
            self.write("enqueue", {"artifact_id": proposal["artifact"]["id"]})
        self.assertEqual(caught.exception.code, "production_gate_failed")
        broken = source(dict(body, review_after="invalid legacy field"), unchecked=True)
        count = self.service.list_artifacts(self.fixture.p)["total"]
        with self.assertRaises(ResourceError) as caught:
            self.local.preview(self.fixture.p, {"action": "resample", "job_id": broken["id"]})
        self.assertEqual(caught.exception.code, "invalid_contract")
        with self.assertRaises(ResourceError) as caught:
            self.write("propose", {"action": "resample", "job_id": broken["id"], "preview_sha256": "0"*64})
        self.assertEqual(caught.exception.code, "invalid_contract")
        self.assertEqual(self.service.list_artifacts(self.fixture.p)["total"], count)

    def test_one_identity_ten_shots_two_instances_keep_every_old_fixed_input(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_impact import ResourceImpact
        cup = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "prop", "display_code": "TEN-CUP"})["id"]
        specs = []
        for number in (1, 2):
            artifact = self.fixture.artifact("ten-cup-spec", "asset-bible", {"asset_specs": [{"asset_id": cup, "variant_key": "v"+str(number)}]})
            with self.engine.connect() as conn:
                specs.append((artifact, conn.execute(select(S.asset_spec_versions.c.id).where(
                    S.asset_spec_versions.c.project_id == self.fixture.p, S.asset_spec_versions.c.artifact_id == artifact)).scalar_one()))
        shots = [self.fixture.objects["shot"]] + [self.fixture.write("create_object", {"kind": "shot", "parent_id": self.fixture.objects["sequence"],
            "display_code": "TEN-"+str(number), "ordinal": number})["id"] for number in range(1, 10)]
        documents, originals, instances = {}, {}, {}
        for number, shot in enumerate(shots):
            document = {"format": "vsc.creative-relations/v1", "project_id": self.fixture.p, "instances": [
                {"key": str(number)+"-"+side, "label": "Cup "+side, "asset_id": cup, "spec_version_id": specs[0][1],
                 "scene_id": self.fixture.objects["scene"], "shot_id": shot, "state": {"position": side}}
                for side in (["left", "right"] if number == 0 else ["left"])]}
            artifact = self.fixture.artifact("shot-cups-"+str(number), "creative-relations", document, [specs[0][0]])
            documents[shot], originals[shot] = document, artifact
            with self.engine.connect() as conn:
                instances[shot] = conn.execute(select(S.asset_use_instances.c.id).where(S.asset_use_instances.c.project_id == self.fixture.p,
                    S.asset_use_instances.c.artifact_id == artifact).order_by(S.asset_use_instances.c.instance_key)).scalars().all()
        model = self.model("image", ["keyframe"])
        fixed_job = self.fixture.job("image", "keyframe", model)
        before_job = self.service.get_generation_job(self.fixture.p, fixed_job["id"])
        with self.engine.connect() as conn:
            before_inputs = [dict(row) for row in conn.execute(select(S.job_input_versions).where(
                S.job_input_versions.c.project_id == self.fixture.p, S.job_input_versions.c.job_id == fixed_job["id"])).mappings()]
        self.fixture.artifact("ten-cup-spec", "asset-bible", {"asset_specs": [{"asset_id": cup, "variant_key": "v3"}]})
        impact = ResourceImpact(SimpleNamespace(service=self.service, _reader=lambda p: None)).query(self.fixture.p,
            source="artifact:"+specs[0][0], replacement="artifact:"+specs[1][0])
        self.assertEqual({row["id"] for row in impact["consumers"] if row["kind"] == "instance"}, {"instance:"+item for values in instances.values() for item in values})
        _, proposal = self.propose({"action": "replace_instance", "instance_id": instances[shots[0]][0], "replacement_spec_version_id": specs[1][1]})
        self.fixture.write("decide_artifact", {"artifact_id": proposal["artifact"]["id"], "reason": "Only this one cup"})
        revised = json.loads(self.service.get_artifact_version(self.fixture.p, proposal["artifact"]["id"])["document"])
        self.assertEqual(revised["instances"][1], documents[shots[0]]["instances"][1])
        self.assertEqual(revised["instances"][0]["spec_version_id"], specs[1][1])
        for shot in shots:
            self.assertEqual(json.loads(self.service.get_artifact_version(self.fixture.p, originals[shot])["document"]), documents[shot])
        with self.engine.connect() as conn:
            historical = conn.execute(select(S.asset_use_instances.c.spec_version_id).where(S.asset_use_instances.c.project_id == self.fixture.p,
                S.asset_use_instances.c.artifact_id.in_(list(originals.values())))).scalars().all()
        self.assertEqual(historical, [specs[0][1]]*11)
        after_job = self.service.get_generation_job(self.fixture.p, fixed_job["id"])
        self.assertEqual((after_job["request_payload"], after_job["request_sha256"]),
            (before_job["request_payload"], before_job["request_sha256"]))
        with self.engine.connect() as conn:
            after_inputs = [dict(row) for row in conn.execute(select(S.job_input_versions).where(
                S.job_input_versions.c.project_id == self.fixture.p, S.job_input_versions.c.job_id == fixed_job["id"])).mappings()]
        self.assertEqual(after_inputs, before_inputs)
