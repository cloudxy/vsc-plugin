#!/usr/bin/env python3
"""Atomic project budgets with fixed synthetic run snapshots; no provider calls."""
import concurrent.futures
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.paths import ROOT
import vsc.project.artifacts as artifacts
import vsc.production.budget as budget
import vsc.project.state as state_module
import vsc.production.audio_run as audio_run
import vsc.production.production as production


from support.fixtures.project import FixedRunFixture


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-budget-test-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = FixedRunFixture(Path(self.temp.name) / "project")
        self.project = self.fixture.project
        patch = mock.patch.object(artifacts, "validate_artifact", side_effect=self.fixture.validator)
        patch.start(); self.addCleanup(patch.stop)

    def ledger(self):
        with budget.ledger(self.project) as data:
            return copy.deepcopy(data)

    def test_reserve_many_is_atomic_when_aggregate_request_exceeds_limit(self):
        operations = {"image:takes/a": {"remote_jobs": 1, "images": 1}, "image:takes/b": {"remote_jobs": 1, "images": 1}}
        run = self.fixture.register("vsc.production_run", {"operations": operations})
        budget.configure(self.project, {"remote_jobs": 1, "images": 1}, "synthetic reviewer", "synthetic cap")
        before = self.ledger()
        with self.assertRaisesRegex(budget.BudgetError, "共享预算不足"):
            budget.reserve_many(self.project, run["id"], operations)
        self.assertEqual(self.ledger(), before)

    def test_two_runs_atomically_share_one_project_limit(self):
        bound = {"remote_jobs": 1, "images": 1}
        runs = [self.fixture.register("vsc.production_run", {"operations": {f"image:takes/{n}": bound}}) for n in (1, 2)]
        budget.configure(self.project, bound, "synthetic reviewer", "shared one-image cap")
        def reserve(index):
            try:
                return budget.reserve(self.project, runs[index]["id"], f"image:takes/{index + 1}", bound)
            except budget.BudgetError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (0, 1)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(budget.usage(self.ledger())["images"], 1)

    def test_unknown_submission_keeps_units_and_cannot_be_submitted_again(self):
        run, _, binding, operation, bound = self.fixture.audio_run()
        budget.configure(self.project, bound, "synthetic reviewer", "speech cap")
        reservation = budget.reserve(self.project, run["id"], operation, bound)
        budget.check_authorization(self.project, reservation, operation, bound, request=binding)
        budget.settle(self.project, reservation, evidence="offline response lost; platform usage unknown")
        with self.assertRaisesRegex(budget.BudgetError, "用量证据"):
            budget.settle(self.project, reservation, actual={"speech_chars": 0})
        ledger = self.ledger()
        self.assertEqual(ledger["reservations"][reservation]["status"], "usage_unknown")
        self.assertEqual(budget.usage(ledger)["speech_chars"], len(binding["inputs"]["prompt"]))
        self.assertEqual(budget.reserve(self.project, run["id"], operation, bound), reservation)
        with self.assertRaisesRegex(budget.BudgetError, "缺有效"):
            budget.check_authorization(self.project, reservation, operation, bound, request=binding)
        second, _, _, second_op, second_bound = self.fixture.audio_run(name="another")
        with self.assertRaisesRegex(budget.BudgetError, "共享预算不足"):
            budget.reserve(self.project, second["id"], second_op, second_bound)

    def test_audio_native_units_and_approved_request_drift_are_checked(self):
        text = "Synthetic speech with punctuation."
        run, _, binding, operation, bound = self.fixture.audio_run(text)
        self.assertEqual(bound, {"remote_jobs": 1, "speech_chars": len(text)})
        budget.configure(self.project, bound, "synthetic reviewer", "speech native units")
        reservation = budget.reserve(self.project, run["id"], operation, bound)
        changed = copy.deepcopy(binding)
        changed["inputs"]["speaker"] = "other-speaker"
        with self.assertRaisesRegex(budget.BudgetError, "绑定不一致"):
            budget.check_authorization(self.project, reservation, operation, bound, request=changed)
        self.assertEqual(self.ledger()["reservations"][reservation]["status"], "reserved")
        with self.assertRaisesRegex(budget.BudgetError, "超过预留"):
            budget.check_authorization(self.project, reservation, operation, {**bound, "speech_chars": len(text) + 1}, request=binding)
        budget.check_authorization(self.project, reservation, operation, bound, request=binding)
        self.assertEqual(self.ledger()["reservations"][reservation]["status"], "submitted_unknown")

    def test_approval_is_rechecked_after_reserving_and_legacy_is_explicit(self):
        run, _, binding, operation, bound = self.fixture.audio_run()
        budget.configure(self.project, bound, "synthetic reviewer", "approval check")
        reservation = budget.reserve(self.project, run["id"], operation, bound)
        state = self.fixture.read_state()
        next(a for a in state["artifacts"] if a["id"] == run["id"])["status"] = "rejected"
        self.fixture.write_state()
        with self.assertRaisesRegex(budget.BudgetError, "run 已失效"):
            budget.check_authorization(self.project, reservation, operation, bound, request=binding)
        with self.assertRaises(budget.BudgetError):
            budget.check_authorization(self.project, None, operation, bound, request=binding)
        state["profile_snapshot"].pop("contract_policy")
        state["profile_sha256"] = state_module.profile_digest(state["profile_snapshot"])
        self.fixture.write_state()
        budget.check_authorization(self.project, None, operation, bound, request=binding)

    def test_image_reservation_requires_the_approved_fixed_request(self):
        batch = {"format": production.FORMAT, "project_id": "test-project", "id": "approved-image", "max_remote_jobs": 1,
                 "budget": {"max_images": 1, "max_video_seconds": 0}, "jobs": [{"id": "image", "kind": "image", "depends_on": [],
                 "args": {"out": "takes", "name": "image", "prompt": "fixed synthetic prompt", "purpose": "asset"}}]}
        batch_path = self.project / "batch.json"
        batch_path.write_text(json.dumps(batch))
        plan = production.build_plan(self.project, batch)
        job = plan["jobs"][0]
        operation, bound = "image:takes/image", {"remote_jobs": 1, "images": 1}
        run = self.fixture.register("vsc.production_run", {"batch": {"path": "batch.json", "sha256": artifacts.digest(batch_path)},
                                                          "operations": {operation: bound}})
        budget.configure(self.project, bound, "synthetic reviewer", "fixed image request")
        reservation = budget.reserve(self.project, run["id"], operation, bound)
        request = copy.deepcopy(job["args"])
        request["prompt"] = "changed synthetic prompt"
        with self.assertRaisesRegex(budget.BudgetError, "prompt"):
            budget.check_authorization(self.project, reservation, operation, bound, request=request)
        self.assertEqual(self.ledger()["reservations"][reservation]["status"], "reserved")
        budget.check_authorization(self.project, reservation, operation, bound, request=job["args"])


if __name__ == "__main__":
    unittest.main()
