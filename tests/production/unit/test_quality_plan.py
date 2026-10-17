"""Synthetic CLI/interface tests; no provider or real project is changed."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support.paths import SCRIPTS
import vsc_quality as quality


class QualityPlanTests(unittest.TestCase):
    def test_repair_compares_actual_consumers_and_does_not_reuse_new_media_review(self):
        from vsc.production.repair import compare_repairs
        plan = {'media_id': 'fixed-media', 'generated_seconds': 8, 'options': [
            {'kind': 'retain_interval', 'reason': 'keep valid opening', 'intervals': [[0, 2], [1, 3]], 'estimated_active_seconds': 10},
            {'kind': 'local_edit', 'reason': 'repair prop only', 'estimated_costs': [{'unit': 'CNY', 'amount': 1}]}]}
        usage = {'media_id': 'fixed-media', 'revision': 5, 'timeline_items': [{'id': 'actual-item'}], 'totals': {'timeline_items': 1}}
        report = compare_repairs(plan, usage)
        self.assertEqual(report['choices'][0]['retained_seconds'], 3)
        self.assertEqual(report['choices'][1]['frozen_consumers_to_review']['timeline_items'], [{'id': 'actual-item'}])
        self.assertFalse(report['choices'][1]['media_review_reusable'])
        self.assertIsNone(report['choices'][0]['actual_cost'])
        usage['totals']['timeline_items'] = 2
        self.assertEqual(compare_repairs(plan, usage)['status'], 'incomplete')
        plan['options'][0]['intervals'] = [[0, 9]]
        self.assertEqual(compare_repairs(plan, usage)['status'], 'blocked')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = self.write("spec.json", {"variant": "coat-a"})
        self.request = self.write("request.json", {"variant": "coat-a", "references": ["face-a"]})
        self.assessment = self.write("assessment.json", {"result": "failed", "note": "contact missing"})
        self.media = self.write("clip.bin", b"synthetic media bytes, not a production take")
        self.plan = {"format": "vsc.quality-plan/v1", "project_id": "synthetic",
            "requirements": [{"id": "variant", "priority": "must", "criterion": "same variant",
                "tolerance": "exact", "source": dict(self.spec, pointer="/variant"),
                "bindings": [{"input_id": "request", "pointer": "/variant", "expected": "coat-a"}]}],
            "inputs": [{"id": "request", "channel": "request", "ref": self.request}],
            "attempts": [], "risks": [], "review_reuse": [], "repeated_failure_limit": 2}

    def write(self, name, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        (self.root / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def attempt(self, aid, task="task-a", **changes):
        row = {"id": aid, "logical_shot_id": "shot-1", "purpose": "video_take", "task_id": task,
            "version": aid, "method": "model-v1/reference-mode", "category": "production",
            "result": "failed", "assessment_ref": self.assessment,
            "defects": [{"code": "hand-contact", "observation": "手与道具未接触"}],
            "active_seconds": 20, "wait_seconds": 40,
            "costs": [{"unit": "CNY", "amount": 1.0, "basis": "actual"}]}
        row.update(changes)
        return row

    def test_valid_links_do_not_certify_semantics_or_authorize_production(self):
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["quality_result"], "unknown")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["coverage"][0]["semantic_result"], "requires_review")

    def test_missing_requirement_request_field_and_asset_variant_block(self):
        mutations = [lambda p: p.update(requirements=[]),
            lambda p: p["requirements"][0].update(bindings=[]),
            lambda p: p["requirements"][0]["bindings"][0].update(pointer="/missing"),
            lambda p: p["requirements"][0]["bindings"][0].update(expected="coat-b")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                plan = copy.deepcopy(self.plan)
                mutate(plan)
                self.assertEqual(quality.check(plan, self.root)["status"], "blocked")

    def test_missing_or_drifted_source_is_never_accepted(self):
        (self.root / "spec.json").write_text('{"variant":"changed"}')
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("摘要已改变", " ".join(result["problems"]))
        (self.root / "spec.json").unlink()
        self.assertEqual(quality.check(self.plan, self.root)["status"], "blocked")

    def test_exact_source_binding_cannot_be_weakened_by_a_changed_expectation(self):
        self.plan["inputs"][0]["ref"] = self.write("changed-request.json", {"variant": "coat-b"})
        self.plan["requirements"][0]["bindings"][0].update(equals_source=True, expected="coat-b")
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("固定规格字段不一致", " ".join(result["problems"]))

    def test_empty_or_unstructured_inputs_block(self):
        self.plan["inputs"][0]["ref"] = self.write("empty.json", {})
        self.assertEqual(quality.check(self.plan, self.root)["status"], "blocked")
        self.plan["inputs"][0]["ref"] = self.write("raw.txt", b"prompt without field mapping")
        self.assertEqual(quality.check(self.plan, self.root)["status"], "blocked")

    def test_unknown_attempt_and_unproven_trial_cannot_pass(self):
        self.plan["attempts"] = [self.attempt("a", result="unknown", defects=[])]
        self.plan["risks"] = [{"id": "hand", "hypothesis": "contact", "stop_condition": "two failures"}]
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["rework"][0]["unknown_count"], 1)
        self.assertEqual(result["quality_result"], "unknown")

    def test_failure_limit_survives_new_task_and_version(self):
        self.plan["attempts"] = [self.attempt("a", "task-a"), self.attempt("b", "task-b", method="renamed method")]
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["rework"][0]["recommendation"], "stop_and_compare_routes")
        self.assertEqual(result["rework"][0]["failure_counts"], {"hand-contact": 2})

    def test_different_purpose_and_transport_recovery_do_not_fake_creative_failures(self):
        self.plan["attempts"] = [self.attempt("a"), self.attempt("b", category="recovery"),
                                 self.attempt("c", purpose="reference")]
        result = quality.check(self.plan, self.root)
        self.assertEqual(len(result["rework"]), 2)
        self.assertTrue(all(row["recommendation"] == "review_evidence" for row in result["rework"]))
        self.assertIn("recovery", result["metrics"])

    def test_cause_without_evidence_does_not_become_fact(self):
        row = self.attempt("a")
        row["defects"][0]["cause"] = {"status": "confirmed", "description": "model incapable"}
        self.plan["attempts"] = [row]
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("原因证据", " ".join(result["problems"]))

    def test_units_active_and_wait_and_unknown_cost_are_separate(self):
        row = self.attempt("a", costs=[{"unit": "CNY", "amount": None, "basis": "actual"},
            {"unit": "requests", "amount": 1, "basis": "actual"},
            {"unit": "CNY", "amount": 2, "basis": "estimate"}])
        # Each basis/unit pair is independent; estimates never replace unknown bills.
        self.plan["attempts"] = [row]
        result = quality.check(self.plan, self.root)
        metrics = result["metrics"]["production"]
        self.assertEqual(metrics["actual:CNY"], {"known_total": 0, "unknown_count": 1})
        self.assertEqual(metrics["actual:requests"]["known_total"], 1)
        self.assertEqual(metrics["estimate:CNY"]["known_total"], 2)
        self.assertEqual(metrics["active_seconds"]["known_total"], 20)
        self.assertEqual(metrics["wait_seconds"]["known_total"], 40)

    def test_usable_intervals_union_deduplicates_media_across_uses(self):
        self.plan["attempts"] = [self.attempt("a", media_ref=self.media, generated_seconds=10,
            usable_intervals=[[1, 4], [3, 6]]), self.attempt("b", purpose="insert", media_ref=self.media,
            generated_seconds=10, usable_intervals=[[5, 8]])]
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["media_usage"]["unique_generated_seconds"], 10)
        self.assertEqual(result["media_usage"]["known_usable_seconds"], 7)

    def test_invalid_and_unknown_intervals_are_not_fully_usable(self):
        self.plan["attempts"] = [self.attempt("a", media_ref=self.media, generated_seconds=10,
                                            usable_intervals=[[0, 11]])]
        self.assertEqual(quality.check(self.plan, self.root)["status"], "blocked")
        self.plan["attempts"][0]["usable_intervals"] = None
        result = quality.check(self.plan, self.root)
        self.assertEqual(result["media_usage"]["known_usable_seconds"], 0)
        self.assertEqual(result["media_usage"]["unknown_media_count"], 1)

    def test_review_reuse_checks_content_purpose_criteria_authority_and_dependencies(self):
        snapshot = {"media": self.media, "criteria": self.spec, "authorization": self.assessment,
                    "dependencies": [dict(self.request, id="request")], "purpose": "video_take"}
        self.plan["review_reuse"] = [{"id": "review", "prior": copy.deepcopy(snapshot),
                                     "current": copy.deepcopy(snapshot)}]
        result = quality.check(self.plan, self.root)
        self.assertTrue(result["review_reuse"][0]["eligible_for_reuse"])
        for field in ("media", "criteria", "authorization", "purpose", "dependencies"):
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan["review_reuse"][0]["current"].pop(field)
                self.assertFalse(quality.check(plan, self.root)["review_reuse"][0]["eligible_for_reuse"])
        (self.root / "clip.bin").write_bytes(b"edited media")
        self.assertFalse(quality.check(self.plan, self.root)["review_reuse"][0]["eligible_for_reuse"])

    def test_duplicate_attempt_cross_project_and_nonfinite_values_block(self):
        for attempts in ([self.attempt("a"), self.attempt("a")],
                         [self.attempt("a", project_id="other")],
                         [self.attempt("a", active_seconds=float("nan"))]):
            self.plan["attempts"] = attempts
            self.assertEqual(quality.check(self.plan, self.root)["status"], "blocked")

    def test_changed_criteria_file_cannot_reuse_equal_pointer_value(self):
        changed = self.write("changed-spec.json", {"variant": "coat-a", "tolerance": "new"})
        snapshot = {"media": self.media, "criteria": dict(self.spec, pointer="/variant"),
            "authorization": self.assessment, "dependencies": [dict(self.request, id="request")],
            "purpose": "video_take"}
        current = copy.deepcopy(snapshot)
        current["criteria"] = dict(changed, pointer="/variant")
        self.plan["review_reuse"] = [{"id": "review", "prior": snapshot, "current": current}]
        self.assertFalse(quality.check(self.plan, self.root)["review_reuse"][0]["eligible_for_reuse"])

    def test_cli_runs_read_only_and_empty_plan_exits_blocked(self):
        path = self.root / "plan.json"
        path.write_text(json.dumps(self.plan))
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        proc = subprocess.run([sys.executable, str(SCRIPTS / "vsc_quality.py"), "check", str(path)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["quality_result"], "unknown")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        path.write_text("{}")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "vsc_quality.py"), "check", str(path)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def test_authority_reader_checks_fixed_bytes_without_local_evidence_files(self):
        document = copy.deepcopy(self.plan)
        content = {"spec": (self.root / "spec.json").read_bytes(), "request": (self.root / "request.json").read_bytes()}
        document["requirements"][0]["source"].pop("path")
        document["requirements"][0]["source"]["artifact_id"] = "spec"
        document["inputs"][0]["ref"].pop("path")
        document["inputs"][0]["ref"]["artifact_id"] = "request"
        reader = lambda ref: content[ref["artifact_id"]]
        self.assertEqual(quality.check(document, self.root / "no-files-here", read_ref=reader)["status"], "ready_for_review")
        content["request"] = b'{"variant":"changed"}'
        self.assertEqual(quality.check(document, self.root / "no-files-here", read_ref=reader)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
