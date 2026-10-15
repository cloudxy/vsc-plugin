"""Regression cases found by independent budget review; all approvals are isolated fixtures."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from support.paths import ROOT  # noqa: F401
from support.fixtures.project import FixedRunFixture
import vsc_artifacts as artifacts
import vsc_audio_run as audio_run
import vsc_budget as budget
import vsc_production as production
import vsc_run as formal


@unittest.skipUnless(shutil.which("ffprobe") and shutil.which("ffmpeg"), "Production preflight requires local FFmpeg tools")
class BudgetReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-budget-review-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = FixedRunFixture(Path(self.temp.name) / "project")
        self.project = self.fixture.project
        # Human creative/content approval is outside this test. Fixed versions,
        # approval status and dependency hashes remain checked by the fixture.
        check = mock.patch.object(artifacts, "validate_artifact", side_effect=self.fixture.validator)
        check.start(); self.addCleanup(check.stop)
        self.animatic = self.fixture.register("vsc.animatic", {"format": "vsc.animatic/v1", "fixture": "isolated creative approval"}, stage="animatic")

    def ledger(self):
        with budget.ledger(self.project) as data:
            return copy.deepcopy(data)

    def image_run(self, name="image", scope="project", shot=None):
        args = {"out": "takes", "name": name, "prompt": "fixed synthetic image", "purpose": "asset"}
        if shot:
            args["shot"] = shot
        batch = {"format": production.FORMAT, "project_id": self.fixture.state["project_id"], "id": name,
                 "max_remote_jobs": 1, "budget": {"max_images": 1, "max_video_seconds": 0},
                 "jobs": [{"id": name, "kind": "image", "depends_on": [], "args": args}]}
        path = self.project / (name + "-batch.json")
        path.write_text(json.dumps(batch), "utf-8")
        plan = production.build_plan(self.project, batch)
        job = plan["jobs"][0]
        operation, bound = formal.operation(job), formal.job_units(job)
        data = {"format": formal.FORMAT, "project_id": self.fixture.state["project_id"], "scope": scope,
                "batch": {"path": path.name, "sha256": artifacts.digest(path)}, "plan_sha256": plan["plan_sha256"],
                "approved_inputs": [{"id": self.animatic["id"], "sha256": self.animatic["sha256"]}],
                "review_after": [], "operations": {operation: bound}}
        item = self.fixture.register("vsc.production_run", data, [self.animatic])
        item["scope"] = scope
        self.fixture.write_state()
        return item, job, operation, bound

    def speech_run(self, scope="EP-001", line="DL-001"):
        script = self.fixture.register("vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [{"dialogue": [
            {"id": line, "speaker": "CHAR-001", "text": "Synthetic dialogue."}]}]}, stage="animatic")
        request = {"kind": "speech", "argv": ["--name", "voice", "--text", "Synthetic dialogue.", "--speaker", "synthetic-speaker",
                   "--max-chars", "100", "--line-id", line, "--screenplay", script["path"],
                   "--acting-choice", "restrained", "--lip-sync-intent", "voiceover"]}
        _, _, binding, operation, bound = audio_run.prepare(self.project, request)
        inputs = [self.animatic, script]
        data = {"format": formal.FORMAT, "project_id": self.fixture.state["project_id"], "scope": scope,
                "audio_request": {**request, "binding": binding}, "plan_sha256": production.ark.digest_json(binding),
                "approved_inputs": [{"id": a["id"], "sha256": a["sha256"]} for a in inputs],
                "review_after": [], "operations": {operation: bound}}
        item = self.fixture.register("vsc.production_run", data, inputs)
        item["scope"] = scope
        self.fixture.write_state()
        self.assertEqual(audio_run.project_errors(data, self.project, self.fixture.read_state(), item), [])
        return item, binding, operation, bound

    def test_extra_semantic_parameters_are_rejected_without_consuming_hold(self):
        item, job, operation, bound = self.image_run()
        budget.configure(self.project, bound, "fixture reviewer", "one synthetic request")
        reservation = budget.reserve(self.project, item["id"], operation, bound)
        original = self.ledger()
        additions = {"base_frame": str(self.project / "unapproved.png"), "bible": "unapproved-bible.json",
                     "state": "unapproved-state.json", "shot": "SH-UNAPPROVED", "moment": "entry",
                     "prompt_file": "unapproved-prompt.txt"}
        for key, value in additions.items():
            with self.subTest(key=key), self.assertRaisesRegex(budget.BudgetError, key):
                budget.check_authorization(self.project, reservation, operation, bound, request={**job["args"], key: value})
            self.assertEqual(self.ledger(), original, "rejected semantics must leave reservation available")
        changed_refs = {**job["args"], "ref": [str(self.project / "unapproved.png")]}
        with self.assertRaisesRegex(budget.BudgetError, "ref"):
            budget.check_authorization(self.project, reservation, operation, bound, request=changed_refs)
        # Free polling options do not change the paid payload.
        budget.check_authorization(self.project, reservation, operation, bound,
                                   request={**job["args"], "max_polls": 2, "poll_interval": 0})
        held = self.ledger()["reservations"][reservation]
        self.assertEqual(held["status"], "submitted_unknown")
        self.assertIsNone(held["currency_cost"])
        with self.assertRaises(budget.BudgetError):
            budget.check_authorization(self.project, reservation, operation, bound, request=job["args"])

    def test_summary_preserves_episode_shot_line_and_unknown_usage_units(self):
        first, first_job, first_op, first_bound = self.image_run("first", "EP-001", "SH-001")
        second, _, second_op, second_bound = self.image_run("second", "EP-002", "SH-002")
        speech, binding, speech_op, speech_bound = self.speech_run()
        limit = {"remote_jobs": 3, "images": 2, "speech_chars": speech_bound["speech_chars"]}
        budget.configure(self.project, limit, "fixture reviewer", "native units across episodes")
        first_res = budget.reserve(self.project, first["id"], first_op, first_bound)
        second_res = budget.reserve(self.project, second["id"], second_op, second_bound)
        speech_res = budget.reserve(self.project, speech["id"], speech_op, speech_bound)
        budget.check_authorization(self.project, first_res, first_op, first_bound, request=first_job["args"])
        budget.settle(self.project, first_res, evidence="offline fixture; provider usage intentionally unknown")
        budget.check_authorization(self.project, speech_res, speech_op, speech_bound, request=binding)
        data = self.ledger()
        groups = budget.summary(data)
        self.assertEqual(groups["by_scope"]["EP-001"]["remote_jobs"], 2)
        self.assertEqual(groups["by_scope"]["EP-002"], budget.units(second_bound))
        self.assertEqual(groups["by_shot"]["SH-001"], budget.units(first_bound))
        self.assertEqual(groups["by_shot"]["SH-002"], budget.units(second_bound))
        self.assertEqual(groups["by_shot"]["DL-001"], budget.units(speech_bound))
        self.assertEqual(groups["by_status"]["usage_unknown"], budget.units(first_bound))
        self.assertEqual(groups["by_status"]["reserved"], budget.units(second_bound))
        self.assertEqual(groups["by_status"]["submitted_unknown"], budget.units(speech_bound))
        self.assertEqual(budget.usage(data), budget.units(limit))
        self.assertEqual(data["reservations"][second_res]["shot_id"], "SH-002")
        self.assertEqual(data["reservations"][speech_res]["line_id"], "DL-001")
        self.assertTrue(all(item["currency_cost"] is None for item in data["reservations"].values()))
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["vsc_budget.py", "status", "--project", str(self.project)]), contextlib.redirect_stdout(output):
            self.assertEqual(budget.main(), 0)
        exported = json.loads(output.getvalue())
        self.assertEqual({key: exported[key] for key in groups}, groups)
        self.assertEqual(exported["occupied"], budget.units(limit))


if __name__ == "__main__":
    unittest.main()
