#!/usr/bin/env python3
"""Formal run integration with real synthetic media, state snapshots and task recovery."""
import contextlib
import copy
import io
import json
import sys
import unittest
from unittest import mock

from support.paths import ROOT
from support.fixtures.production import ProductionFixture
from support.fixtures.project import FixedRunFixture
import vsc_artifacts as artifacts
import vsc_budget as budget
import vsc_production as production
import vsc_run as formal
import vsc_state as state_module


class FormalRunTest(ProductionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fixture = FixedRunFixture(self.project)
        self.batch["jobs"] = self.batch["jobs"][:2]
        self.batch["jobs"][0]["args"].update(purpose="candidate", shot="SH-001", moment="entry",
            bible={"path": "bible.json"}, state={"path": "state.json"})
        bible = self.fixture.register("vsc.asset_bible", json.loads((self.project / "bible.json").read_text()), stage="animatic")
        state = self.fixture.register("vsc.scene_state", json.loads((self.project / "state.json").read_text()), stage="animatic")
        animatic = self.fixture.register("vsc.animatic", {"format": "vsc.animatic/v1", "fixture": "synthetic approved input"}, stage="animatic")
        self.inputs = [bible, state, animatic]
        for job in self.batch["jobs"]:
            job["args"].update(bible={"path": bible["path"]}, state={"path": state["path"]})
        self.batch_path = self.project / "batch.json"
        self.batch_path.write_text(json.dumps(self.batch))
        self.plan_data = production.build_plan(self.project, self.batch)
        self.run_data = {"format": formal.FORMAT, "project_id": "test-project", "scope": "project",
                         "batch": {"path": "batch.json", "sha256": artifacts.digest(self.batch_path)},
                         "plan_sha256": self.plan_data["plan_sha256"],
                         "approved_inputs": [{"id": item["id"], "sha256": item["sha256"]} for item in self.inputs],
                         "review_after": ["image"], "operations": {formal.operation(job): formal.job_units(job) for job in self.plan_data["jobs"]}}
        self.run_item = self.fixture.register("vsc.production_run", self.run_data, self.inputs)
        budget.configure(self.project, {"remote_jobs": 2, "images": 1, "video_seconds": 5}, "synthetic reviewer", "formal-run test cap")
        # Full upstream story/animatic contract QA has separate tests. This suite uses
        # actual approval, dependency, immutable snapshot and gate inputs at this seam.
        for module in (formal, artifacts, state_module):
            patch = mock.patch.object(module, "validate_artifact", side_effect=self.fixture.validator)
            patch.start(); self.addCleanup(patch.stop)

    def read_state(self):
        return state_module.project_state(self.project)

    def execute(self):
        return formal.execute(self.project, self.run_item["id"], self.runner)

    def review(self, outcome="accepted"):
        argv = ["vsc_run.py", "review", self.run_item["id"], "--project", str(self.project), "--job", "image",
                "--by", "synthetic fixture reviewer", "--reason", "synthetic media reviewed for the declared boundary", "--outcome", outcome]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(formal.main(), 0)

    def test_unapproved_run_and_failed_animatic_gate_never_call_runner(self):
        state = self.read_state()
        next(a for a in state["artifacts"] if a["id"] == self.run_item["id"])["status"] = "draft"
        state_module.write_json(self.project / "vsc.json", state)
        runner = mock.Mock(side_effect=AssertionError("must not execute"))
        with self.assertRaisesRegex(ValueError, "run 无效"):
            formal.execute(self.project, self.run_item["id"], runner)
        runner.assert_not_called()
        state["artifacts"][-1]["status"] = "approved"
        next(a for a in state["artifacts"] if a["type"] == "vsc.animatic")["status"] = "draft"
        state_module.write_json(self.project / "vsc.json", state)
        # Isolate the explicit gate after load_run so failure cannot be bypassed by
        # a future load_run refactor that only checks the run's own bytes.
        with mock.patch.object(formal, "load_run", return_value=(state, self.run_item, self.run_data)):
            with self.assertRaisesRegex(ValueError, "质量门"):
                formal.execute(self.project, self.run_item["id"], runner)
        runner.assert_not_called()
        self.assertFalse((self.project / ".vsc-production").exists())

    def test_keyframe_pause_review_resume_and_draft_import_preserve_original_task(self):
        self.assertEqual(formal.project_errors(self.run_data, self.project, self.read_state(), self.run_item), [])
        first = self.execute()
        self.assertEqual(first["status"], "awaiting_review")
        self.assertEqual(set(first["jobs"]), {"image"})
        self.assertEqual([path for path, _ in self.calls], ["/images/generations"])
        original_task = json.loads((self.project / "takes/image-任务.json").read_text())
        imported = [a for a in self.read_state()["artifacts"] if a.get("run_id") == self.run_item["id"]]
        self.assertEqual(len(imported), 1)
        self.assertEqual((imported[0]["status"], imported[0]["decision"]), ("draft", None))
        self.assertIsNone(json.loads((self.project / imported[0]["path"]).read_text())["selection"])
        self.assertEqual(self.execute()["status"], "awaiting_review")
        self.assertEqual(len(self.calls), 1)
        self.review()
        finished = self.execute()
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(sum(path == "/images/generations" for path, _ in self.calls), 1)
        self.assertEqual(sum(path == "/contents/generations/tasks" for path, _ in self.calls), 1)
        resumed_task = json.loads((self.project / "takes/image-任务.json").read_text())
        self.assertEqual(resumed_task["binding"], original_task["binding"])
        self.assertEqual(resumed_task["credential_sha256"], original_task["credential_sha256"])
        state = self.read_state()
        imported = [a for a in state["artifacts"] if a.get("run_id") == self.run_item["id"]]
        self.assertEqual(len(imported), 2)
        self.assertTrue(all(a["status"] == "draft" and a["decision"] is None for a in imported))
        self.assertTrue(all(json.loads((self.project / a["path"]).read_text())["selection"] is None for a in imported))
        self.assertEqual(state["production_reviews"][0]["run_sha256"], self.run_item["sha256"])
        self.assertEqual(state["production_reviews"][0]["outcome"], "accepted")
        count = len(self.calls)
        self.assertEqual(self.execute()["status"], "completed")
        self.assertEqual(len(self.calls), count)
        self.assertEqual(len([a for a in self.read_state()["artifacts"] if a.get("run_id") == self.run_item["id"]]), 2)

    def test_rejected_or_stale_review_keeps_downstream_paused(self):
        self.execute()
        self.review("rejected")
        self.assertEqual(self.execute()["status"], "awaiting_review")
        self.assertEqual(len(self.calls), 1)
        self.review("accepted")
        state = self.read_state()
        state["production_reviews"][-1]["outputs_sha256"] = {"takes/image.png": "f" * 64}
        state_module.write_json(self.project / "vsc.json", state)
        self.assertEqual(self.execute()["status"], "awaiting_review")
        self.assertEqual(len(self.calls), 1)

    def test_missing_dependency_review_and_input_drift_fail_preflight(self):
        missing = copy.deepcopy(self.run_data)
        missing["review_after"] = []
        self.assertTrue(any("review_after" in error for error in formal.project_errors(missing, self.project, self.read_state(), self.run_item)))
        self.batch_path.write_text(json.dumps({**self.batch, "id": "changed-batch"}))
        self.assertTrue(any("batch 文件已漂移" in error for error in formal.project_errors(self.run_data, self.project, self.read_state(), self.run_item)))
        self.assertEqual(self.calls, [])

    def test_strict_project_cannot_execute_low_level_queue_with_only_plan_hash(self):
        with self.assertRaisesRegex(production.ProductionError, "vsc_run.py"):
            production.run(self.project, self.plan_data, self.plan_data["plan_sha256"], self.runner)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
