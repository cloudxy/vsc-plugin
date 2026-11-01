import copy
from datetime import datetime, timezone
import json
import unittest
import uuid

import support.paths  # noqa: F401
from vsc.assets.resource_service import ResourceError
from vsc.production.bounded import execute_batch, graph_errors, preview_batch, resolve_request
from vsc.production.run_authorization import authorize_run, normalize_request
from vsc.production.run_policy import enforce_execution_policy, policy_errors, production_gate, production_input


def policy():
    return {"version": "bounded-v1", "first_draft_due_at": "2099-01-01T01:00:00+00:00",
            "stop_submitting_at": "2099-01-01T02:00:00+00:00", "max_attempts_per_purpose": 2,
            "max_repair_rounds": 1}


def task(key="first", shot="shot-a", depends=()):
    return {"task_key": key, "model_id": "model", "candidate_no": 0, "depends_on": list(depends),
            "request": {"shot_id": shot, "purpose": "keyframe", "modality": "image", "prompt": "synthetic"}}


def run():
    return {"execution_policy": policy(), "approved_inputs": [{"id": "spec", "sha256": "s"}],
            "series_batch": {"jobs": [task(), task("later", "shot-b", ["first"]), task("independent", "shot-c")]}}


class Service:
    def __init__(self):
        self.run = run()
        self.jobs = []
        self.creations = []
        self.revision = 0

    def get_artifact_version(self, project, identifier):
        return {"id": identifier, "artifact_type": "production-run", "approved": True,
                "sha256": "fixed", "document": json.dumps(self.run)}

    def list_generation_jobs(self, project, **kw):
        return {"items": copy.deepcopy(self.jobs), "total": len(self.jobs)}

    def get_generation_job(self, project, identifier):
        return next(row for row in self.jobs if row["id"] == identifier)

    def compile_shot_context(self, project, shot, purpose):
        return {"ready": True, "sha256": "context", "media": [], "artifacts": [{"id": "spec", "sha256": "s"}]}

    def get_project(self, project):
        return {"revision": self.revision}

    def create_generation_job(self, project, payload, **kw):
        self.creations.append((payload, kw))
        self.revision += 1
        job = dict(payload, project_id=project, id=str(uuid.uuid4()), status="created", outputs=[], attempt=0)
        self.jobs.append(job)
        return job


class BoundedRunTests(unittest.TestCase):
    def test_original_screenplay_keeps_fixed_brief_and_old_profile_rules(self):
        from vsc.production.handoffs import screenplay_policy_errors, validation_errors
        document = {"format": "vsc.screenplay/v1", "project_id": "p", "scope": "ep", "body": "Synthetic original",
            "source_mode": "original", "adaptation_refs": [], "original_brief": {"id": "brief", "sha256": "0" * 64},
            "scenes": [{"id": "scene", "estimated_duration_ms": 1000,
                "actions": [{"id": "action", "text": "Synthetic action", "narrative_refs": []}], "dialogue": [], "silence": []}]}
        self.assertFalse(validation_errors(document))
        profile = {"production_policy": "light-short-v1"}
        deps = [{"id": "brief", "sha256": "0" * 64, "approved": True, "artifact_type": "vsc.creative_brief"}]
        self.assertFalse(screenplay_policy_errors(document, profile, deps))
        self.assertTrue(screenplay_policy_errors(document, {}, deps))
        self.assertTrue(screenplay_policy_errors(document, profile, []))
        deps[0]["sha256"] = "1" * 64
        self.assertTrue(screenplay_policy_errors(document, profile, deps))
        document["source_mode"] = "adapted"
        self.assertTrue(validation_errors(document))

    def test_profile_gate_uses_fixed_policy_not_profile_label(self):
        self.assertEqual(production_gate({"production_policy": "light-short-v1"}), "design")
        self.assertEqual(production_input({"production_policy": "light-short-v1"}), "vsc.shot_plan")
        self.assertEqual(production_gate({"profile_id": "vsc.light-short", "version": "2.0"}), "animatic")
        self.assertEqual(production_gate({"production_policy": "light-short-v1"}, "asset"), "script")

    def test_policy_rejects_unbounded_or_naive_limits(self):
        for change in ({"stop_submitting_at": "2099-01-01T02:00:00"}, {"max_attempts_per_purpose": True},
                       {"max_repair_rounds": 2}, {"repair_round": 2}, {"max_repair_rounds": "1", "repair_round": 1}):
            with self.subTest(change=change):
                self.assertTrue(policy_errors(dict(policy(), **change)))

    def test_graph_rejects_cycle_outside_scope_and_duplicate_logical_task(self):
        self.assertFalse(graph_errors(run()))
        for malformed in (None, [], {"series_batch": []}):
            self.assertTrue(graph_errors(malformed))
        for mutation in ("cycle", "outside", "duplicate", "model", "target", "malformed"):
            with self.subTest(mutation=mutation):
                document = run()
                rows = document["series_batch"]["jobs"]
                if mutation == "cycle": rows[0]["depends_on"] = ["later"]
                if mutation == "outside": rows[0]["depends_on"] = ["outside-run"]
                if mutation == "duplicate": rows[2]["request"]["shot_id"] = "shot-a"
                if mutation == "model": rows[0].pop("model_id")
                if mutation == "target": rows[0]["request"]["asset_id"] = "asset"
                if mutation == "malformed": rows[0]["task_key"] = []
                self.assertTrue(graph_errors(document))

    def test_renamed_run_cannot_reset_unknown_attempt_or_extend_deadline(self):
        job = {"id": "new", "project_id": "p", "shot_id": "shot", "purpose": "video"}
        history = [dict(job, id="old-1", attempt=1, status="succeeded", execution_policy=policy()),
                   dict(job, id="old-2", attempt=1, status="submission_unknown", execution_policy=policy())]
        now = datetime(2098, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(ResourceError) as caught:
            enforce_execution_policy({"execution_policy": dict(policy(), max_attempts_per_purpose=10)}, job, history, now)
        self.assertEqual(caught.exception.code, "production_attempts_exhausted")
        history = history[:1]
        with self.assertRaises(ResourceError) as caught:
            enforce_execution_policy({"execution_policy": dict(policy(), stop_submitting_at="2100-01-01T00:00:00Z")},
                job, history, datetime(2099, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(caught.exception.code, "production_deadline_reached")
        other = dict(job, purpose="audio")
        self.assertEqual(enforce_execution_policy({"execution_policy": policy()}, other, history, now)["attempts_used"], 0)

    def test_output_requires_actual_success_selected_role_and_sha(self):
        row = task("later", "shot-b", ["first"])
        row["output_inputs"] = [{"task_key": "first", "field": "reference_media_ids", "role": "identity_face"}]
        job_id = str(uuid.uuid4())
        media_id = str(uuid.uuid5(uuid.UUID(job_id), "output:0"))
        outputs = {"first": {"job_id": job_id, "status": "succeeded", "outputs": [{"media_id": media_id, "sha256": "sha"}]}}
        context = {"media": [{"media_id": media_id, "sha256": "sha", "role": "identity_face", "binding_decision_id": "decision"}]}
        self.assertEqual(resolve_request(row, context, outputs)["reference_media_ids"], [media_id])
        for mutation in ("sha", "role", "selection", "status"):
            with self.subTest(mutation=mutation):
                changed, upstream = copy.deepcopy(context), copy.deepcopy(outputs)
                if mutation == "sha": changed["media"][0]["sha256"] = "other"
                if mutation == "role": changed["media"][0]["role"] = "prop"
                if mutation == "selection": changed["media"][0]["binding_decision_id"] = None
                if mutation == "status": upstream["first"]["status"] = "submission_unknown"
                with self.assertRaises(ResourceError): resolve_request(row, changed, upstream)

    def test_authorization_still_rejects_extra_reference_or_model(self):
        document = run()
        context = {"sha256": "context", "artifacts": [{"id": "spec", "sha256": "s"}], "media": []}
        logical = normalize_request(task()["request"], "shot-a", "keyframe", "image")
        self.assertEqual(authorize_run(document, "production-run", context, logical, 0, model_id="model"), {("spec", "s")})
        for change in ("model", "reference"):
            modified = dict(logical, reference_media_ids=["unapproved"]) if change == "reference" else logical
            with self.assertRaises(ResourceError):
                authorize_run(document, "production-run", context, modified, 0, model_id="wrong" if change == "model" else "model")

    def test_partial_batch_failure_does_not_block_independent_and_restart_is_idempotent(self):
        service = Service()
        result = execute_batch(service, "p", {"run_version_id": "run"}, "test-worker")
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["waiting_count"], 1)
        self.assertEqual(len(service.creations), 2)
        service.jobs[0]["status"] = "failed"
        restarted = execute_batch(service, "p", {"run_version_id": "run"}, "new-worker")
        self.assertEqual(len(service.creations), 2)
        self.assertEqual(restarted["blocked_count"], 1)
        self.assertEqual(restarted["existing_count"], 2)
        service.jobs[0]["status"] = "succeeded"
        continued = execute_batch(service, "p", {"run_version_id": "run"}, "new-worker")
        self.assertEqual(continued["created_count"], 1)
        self.assertEqual(len(service.creations), 3)
        with self.assertRaises(ResourceError):
            preview_batch(service, "p", {"run_version_id": "run", "run_sha256": "stale"})
        with self.assertRaises(ResourceError):
            preview_batch(service, "p", {"run_version_id": "run", "task_keys": ["outside"]})


if __name__ == "__main__":
    unittest.main()
