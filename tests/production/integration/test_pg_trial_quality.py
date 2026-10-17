"""Synthetic PostgreSQL trials, quality guards and typed formal adoption."""
import copy
import os
import unittest
import uuid

from support.paths import ROOT
from support.fixtures.resource_store import HAS_DB_DEPS
from support.fixtures.trial_quality import TrialQualityFixture


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS, "requires isolated PostgreSQL test connection")
class PostgresTrialQualityTests(TrialQualityFixture, unittest.TestCase):
    def test_trial_before_animatic_is_bounded_and_budgets_at_submission(self):
        from vsc.assets.resource_service import ResourceError
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        run, package, logical = self.fixture_run()
        job = self.job(run, logical)
        self.assertEqual(job["status"], "created")
        with self.assertRaises(ResourceError) as error:
            self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "synthetic"})
        self.assertEqual(error.exception.code, "budget_not_configured")
        self.write("configure_budget", {"limits": {"remote_jobs": 1, "video_seconds": 5}, "reason": "one bounded offline submission"})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "synthetic"})
        self.assertEqual(self.service.budget_status(self.p)["used"], {"remote_jobs": 1, "video_seconds": 5})
        # Existing tasks can still recover/poll after evidence is revoked;
        # these status changes do not create another paid submission.
        self.write("decide_artifact", {"artifact_id": package["id"], "outcome": "revoke", "reason": "test later revocation"})
        self.write("update_generation_job", {"job_id": job["id"], "status": "running"})
        with self.engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(S.job_budget_reservations).where(S.job_budget_reservations.c.project_id == self.p)).all()), 2)

    def test_quality_error_blocks_creation_and_revocation_blocks_first_submission(self):
        from vsc.assets.resource_service import ResourceError
        run, package, logical = self.fixture_run(lambda plan: plan["requirements"][0]["bindings"][0].update(expected="wrong"))
        with self.assertRaises(ResourceError) as error:
            self.job(run, logical)
        self.assertEqual(error.exception.code, "quality_plan_blocked")
        run, package, logical = self.fixture_run()
        job = self.job(run, logical)
        self.write("configure_budget", {"limits": {"remote_jobs": 1, "video_seconds": 5}, "reason": "bounded"})
        claimed = self.service.claim_generation_job("synthetic-worker", project_id=self.p)
        self.rev = claimed["revision"]
        self.write("decide_artifact", {"artifact_id": package["id"], "outcome": "revoke", "reason": "test revocation before paid submit"})
        with self.assertRaises(ResourceError):
            self.write("mark_submission_started", {"job_id": job["id"], "worker_id": "synthetic-worker"})
        self.assertEqual(self.service.get_generation_job(self.p, job["id"])["status"], "created")
        self.assertEqual(self.service.budget_status(self.p)["used"], {})

    def test_trial_scope_method_count_and_production_gate_cannot_be_bypassed(self):
        import json
        from vsc.assets.resource_service import ResourceError
        run, _, logical = self.fixture_run()
        original = json.loads(run["document"])
        for label, mutation, code in (
            ("count", lambda body: body["trial"].update(max_remote_jobs=0), "trial_job_limit"),
            ("method", lambda body: body["trial"].update(method_sha256=self.service.get_artifact_version(self.p, self.script)["sha256"]), "trial_method_missing"),
            ("scope", lambda body: body["trial"].update(allowed_shot_ids=[]), "trial_scope_invalid"),
            ("budget", lambda body: body.update(operations={}), "run_budget_unauthorized")):
            body = copy.deepcopy(original)
            mutation(body)
            changed = self.approved("run-" + label, "production-run", body, dependency_ids=[r["id"] for r in body["approved_inputs"]])
            with self.assertRaises(ResourceError) as error:
                self.job(changed, logical)
            self.assertEqual(error.exception.code, code)
        body = copy.deepcopy(original)
        body["phase"] = "production"
        body.pop("trial")
        production = self.approved("production", "production-run", body, dependency_ids=[r["id"] for r in body["approved_inputs"]])
        with self.assertRaises(ResourceError) as error:
            self.job(production, logical)
        self.assertEqual(error.exception.code, "production_gate_failed")

    def test_pg_formal_missing_risk_evaluation_is_actionable(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres.production_guard import validate_guard
        run, _, _ = self.fixture_run(lambda plan: plan.update(risks=[{
            "id": "camera-risk", "hypothesis": "test camera motion", "stop_condition": "one attempt"}]), phase="production")
        with self.engine.connect() as conn, self.assertRaises(ResourceError) as error:
            validate_guard(self.store, conn, self.store._project(conn, self.p), run)
        self.assertEqual(error.exception.code, "quality_plan_blocked")
        self.assertIn("缺少代表性实片评测", error.exception.message)

    def test_trial_adoption_of_processed_output_is_explicit_typed_and_immutable(self):
        from sqlalchemy import insert, select, update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres.resource_graph import query_graph
        run, _, logical = self.fixture_run()
        job = self.job(run, logical)
        self.write("configure_budget", {"limits": {"remote_jobs": 1, "video_seconds": 5}, "reason": "bounded"})
        self.write("update_generation_job", {"job_id": job["id"], "status": "submitted", "external_task_id": "synthetic"})
        output = self.media("trial output", modality="video")
        self.write("update_generation_job", {"job_id": job["id"], "status": "succeeded", "outputs": [{"media_id": output}]})
        processed = self.media("processed trial", modality="video")
        self.write("create_media_operation", {"operation_type": "trim", "recipe_version": "1", "tool": "offline", "tool_version": "1",
            "inputs": [{"media_id": output}], "outputs": [{"media_id": processed}]})
        candidate = self.candidate(self.objects["shot"], processed, role="video_take")
        usage = self.service.get_media_usage(self.p, processed)
        self.assertEqual(usage["trial_sources"], [{"id": run["id"], "sha256": run["sha256"]}])
        with self.assertRaises(ResourceError) as error:
            self.select(candidate)
        self.assertEqual(error.exception.code, "trial_adoption_required")
        with self.assertRaises(ResourceError) as error:
            self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "invalid adoption",
                "trial_adoption": {"reason": "not an animatic", "animatic_version_id": run["id"]}})
        self.assertEqual(error.exception.code, "trial_animatic_required")
        # Direct SQL cannot bypass the deferred adoption requirement.
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.binding_decisions).values(project_id=self.p, id=str(uuid.uuid4()), slot_id=candidate["slot_id"],
                    candidate_id=candidate["candidate_id"], outcome="select", actor="synthetic", reason="bypass", decision_sequence=99999, based_on_revision=self.rev))
        animatic = self.approved("animatic", "animatic", {"previews": "synthetic review"}, stage="animatic")
        selection = self.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "normal final choice",
            "trial_adoption": {"reason": "trial meets this final shot", "animatic_version_id": animatic["id"]}})
        with self.engine.connect() as conn:
            adoption = conn.execute(select(S.binding_trial_adoptions).where(S.binding_trial_adoptions.c.project_id == self.p)).mappings().one()
            self.assertEqual(adoption["run_version_id"], run["id"])
            self.assertEqual(adoption["decision_id"], selection["decision_id"])
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(update(S.binding_trial_adoptions).where(S.binding_trial_adoptions.c.project_id == self.p).values(animatic_version_id=run["id"]))
        self.write("retire_binding", {"slot_id": candidate["slot_id"], "reason": "future change only"})
        graph = query_graph(self.store, self.p, depth=0, limit=300)
        evidence = [e for e in graph["edges"] if e["kind"] == "trial_adoption"]
        self.assertEqual(evidence[0]["evidence"]["decision_id"], selection["decision_id"])

    def test_migration_matches_current_model(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from vsc.adapters.persistence.postgres.schema import metadata
        with self.engine.connect() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn), metadata), [])
        self.assertEqual(self.store.check_schema()["migration"], "0005_creative_relations")


if __name__ == "__main__":
    unittest.main()
