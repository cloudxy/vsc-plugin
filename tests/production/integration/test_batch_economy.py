"""B3-04/B3-05：十次尝试不倍增核心文案 + 只读执行预览三态清单（离线）。"""
import json
import tempfile
import unittest
from pathlib import Path

from support.fixtures.production import ProductionFixture
from vsc.production import production as P


class BatchEconomyTest(ProductionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.economy_batch = {"format": P.FORMAT, "project_id": "test-project", "id": "eco-1", "max_remote_jobs": 3,
                      "budget": {"max_images": 10, "max_video_seconds": 10}, "jobs": [
                          {"id": "img", "kind": "image", "depends_on": [], "args": {
                              "out": "takes", "name": "img", "prompt": "p", "purpose": "asset"}}]}

    def test_ten_recoveries_submit_once(self):
        plan = P.build_plan(self.project, self.economy_batch)
        # 同一计划重跑十次：journal 复用，生成记录恒为 1 份，无新增文案。
        for _ in range(10):
            journal = P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
            self.assertEqual(journal["jobs"]["img"]["status"], "succeeded")
        records = list((self.project / "takes").glob("*生成记录.json"))
        tasks = list((self.project / "takes").glob("*任务.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(journal["jobs"]["img"]["attempts"], 1)  # 复用不重复调用
        self.assertEqual(sum(path == "/images/generations" for path, _ in self.calls), 1)  # 恰一次付费调用

    def test_ten_explicit_new_samples_keep_core_documents_and_identity_bytes(self):
        core={path.relative_to(self.project):path.read_bytes() for path in self.project.glob('*.json')}
        before={path.relative_to(self.project) for path in self.project.rglob('*') if path.is_file()}
        for index in range(10):
            batch=json.loads(json.dumps(self.economy_batch))
            batch['id']='sample-'+str(index)
            batch['jobs'][0]['args']['name']='sample-'+str(index)
            plan=P.build_plan(self.project,batch)
            self.assertEqual(P.preview(self.project,plan)['usage_bound']['images'],1)
            P.run(self.project,plan,plan['plan_sha256'],runner=self.runner)
        self.assertEqual(sum(path=='/images/generations' for path,_ in self.calls),10)
        self.assertEqual(core,{path.relative_to(self.project):path.read_bytes() for path in self.project.glob('*.json')})
        records=list((self.project/'takes').glob('*生成记录.json'))
        tasks=list((self.project/'takes').glob('*任务.json'))
        self.assertEqual((len(records),len(tasks)),(10,10))
        self.assertEqual(len({json.loads(path.read_text())['inputs']['prompt'] for path in records}),1)
        # Each sample owns necessary candidate/recovery evidence; there is still
        # one immutable bible/state pair and no per-sample core document tree.
        added=[path for path in self.project.rglob('*') if path.is_file() and path.relative_to(self.project) not in before]
        self.assertGreater(sum(path.stat().st_size for path in added),10*len(self.png))
        self.assertTrue(all(path.relative_to(self.project).parts[0] in {'takes','.vsc-production'} for path in added))

    def test_preview_three_states(self):
        plan = P.build_plan(self.project, self.economy_batch)
        preview = P.preview(self.project, plan)
        self.assertEqual(preview["jobs"][0]["state"], "execute")
        self.assertEqual(preview["usage_bound"]["images"], 1)
        P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
        preview = P.preview(self.project, plan)
        self.assertEqual(preview["jobs"][0]["state"], "reuse")  # 成功且校验通过 → 复用，不再付费
        self.assertEqual(preview["usage_bound"], {"remote_jobs": 0, "images": 0, "video_seconds": 0})

    def test_unknown_receipt_and_downstream_preview_match_zero_run_calls(self):
        plan = self.plan()
        def interrupted(*args, **kwargs):
            raise RuntimeError("synthetic transport interrupted before receipt")
        with self.assertRaises(P.ProductionError):
            P.run(self.project, plan, plan["plan_sha256"], runner=interrupted)
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        shown = P.preview(self.project, plan)
        self.assertEqual([row["state"] for row in shown["jobs"]], ["verify"] + ["blocked"] * (len(plan["jobs"]) - 1))
        self.assertEqual(shown["usage_bound"]["remote_jobs"], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
        with self.assertRaisesRegex(P.ProductionError, "提交状态未知"):
            P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_first_failure_stops_independent_job_forecast_and_actual_run(self):
        batch = json.loads(json.dumps(self.economy_batch))
        second = json.loads(json.dumps(batch["jobs"][0]))
        second.update(id="independent")
        second["args"]["name"] = "independent"
        batch["jobs"].append(second)
        plan = self.plan(batch)
        self.assertTrue(all(not job["depends_on"] for job in plan["jobs"]))
        def interrupted(*args, **kwargs):
            raise RuntimeError("synthetic response lost before receipt")
        with self.assertRaises(P.ProductionError):
            P.run(self.project, plan, plan["plan_sha256"], runner=interrupted)
        path = P.journal_path(self.project, plan["id"])
        for first_state in ("verify", "blocked"):
            if first_state == "blocked":
                journal = P.read(path)
                journal["jobs"]["img"]["binding"] = "f" * 64
                path.write_text(json.dumps(journal))
            before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
            with self.subTest(first_state=first_state):
                shown = P.preview(self.project, plan)
                self.assertEqual([row["state"] for row in shown["jobs"]], [first_state, "blocked"])
                self.assertIn("前序任务", shown["jobs"][1]["note"])
                self.assertEqual(shown["usage_bound"], {"remote_jobs": 0, "images": 0, "video_seconds": 0})
                self.assertEqual(before, {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
                with self.assertRaises(P.ProductionError):
                    P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.argv, [])

    def test_stopped_run_can_still_observe_completed_independent_result(self):
        batch = json.loads(json.dumps(self.economy_batch))
        second = json.loads(json.dumps(batch["jobs"][0]))
        second.update(id="independent")
        second["args"]["name"] = "independent"
        batch["jobs"].append(second)
        plan = self.plan(batch)
        self.run_queue(plan)
        first = plan["jobs"][0]
        (self.project / P.record_path(first)).unlink()
        (self.project / P.task_path(first)).unlink()
        count = len(self.calls)
        shown = P.preview(self.project, plan)
        self.assertEqual([row["state"] for row in shown["jobs"]], ["verify", "reuse"])
        self.assertIn("前序任务", shown["jobs"][1]["note"])
        self.assertEqual(shown["usage_bound"]["remote_jobs"], 0)
        with self.assertRaisesRegex(P.ProductionError, "提交状态未知"):
            self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_journal_and_binding_drift_block_preview_and_run(self):
        plan = P.build_plan(self.project, self.economy_batch)
        self.run_queue(plan)
        path = P.journal_path(self.project, plan["id"])
        original = P.read(path)
        for field in ("plan_sha256", "binding", "request_binding_sha256", "outputs_sha256"):
            journal = json.loads(json.dumps(original))
            if field == "plan_sha256":
                journal[field] = "f" * 64
            else:
                journal["jobs"]["img"][field] = {"other.png": "f" * 64} if field == "outputs_sha256" else "f" * 64
            path.write_text(json.dumps(journal))
            count = len(self.calls)
            shown = P.preview(self.project, plan)
            self.assertEqual(shown["jobs"][0]["state"], "blocked", field)
            self.assertEqual(shown["usage_bound"]["images"], 0)
            with self.assertRaises(P.ProductionError):
                P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
            self.assertEqual(len(self.calls), count)

    def test_completed_output_precedes_failed_label_and_attempt_limit(self):
        plan = P.build_plan(self.project, self.economy_batch)
        self.run_queue(plan)
        path = P.journal_path(self.project, plan["id"])
        journal = P.read(path)
        journal["jobs"]["img"].update(status="failed", attempts=plan["max_attempts"])
        path.write_text(json.dumps(journal))
        self.assertEqual(P.preview(self.project, plan)["jobs"][0]["state"], "reuse")
        count = len(self.calls)
        self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_unfinished_receipt_at_attempt_limit_blocks_both_consumers(self):
        plan = P.build_plan(self.project, self.economy_batch)
        self.run_queue(plan)
        (self.project / P.record_path(plan["jobs"][0])).unlink()
        path = P.journal_path(self.project, plan["id"])
        journal = P.read(path)
        journal["jobs"]["img"].update(status="failed", attempts=plan["max_attempts"])
        path.write_text(json.dumps(journal))
        shown = P.preview(self.project, plan)
        self.assertEqual(shown["jobs"][0]["state"], "blocked")
        self.assertEqual(shown["usage_bound"]["remote_jobs"], 0)
        count = len(self.calls)
        with self.assertRaisesRegex(P.ProductionError, "max_attempts"):
            self.run_queue(plan)
        self.assertEqual(len(self.calls), count)

    def test_existing_unowned_output_and_input_drift_do_not_predict_execute(self):
        prompt = self.project / "prompt.txt"
        prompt.write_text("synthetic")
        args = self.economy_batch["jobs"][0]["args"]
        del args["prompt"]
        args["prompt_file"] = {"path": prompt.name}
        plan = P.build_plan(self.project, self.economy_batch)
        prompt.write_text("changed")
        self.assertEqual(P.preview(self.project, plan)["jobs"][0]["state"], "blocked")
        with self.assertRaises(P.ProductionError):
            self.run_queue(plan)
        prompt.write_text("synthetic")
        output = self.project / P.outputs(plan["jobs"][0])["image"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.png)
        self.assertEqual(P.preview(self.project, plan)["usage_bound"]["remote_jobs"], 0)
        with self.assertRaisesRegex(P.ProductionError, "不能接管"):
            self.run_queue(plan)
        self.assertEqual(self.calls, [])

    def test_pending_dependency_forecast_and_explicit_new_sample(self):
        plan = self.plan()
        shown = P.preview(self.project, plan)
        self.assertEqual([row["state"] for row in shown["jobs"]], ["execute"] * len(plan["jobs"]))
        self.assertIn("须先完成上游", shown["jobs"][1]["note"])
        self.run_queue(plan)
        self.assertEqual(P.preview(self.project, plan)["usage_bound"]["remote_jobs"], 0)
        batch = json.loads(json.dumps(self.economy_batch))
        batch["id"] = "new-sample"
        batch["jobs"][0]["args"]["name"] = "new-sample"
        new_plan = self.plan(batch)
        self.assertEqual(P.preview(self.project, new_plan)["usage_bound"]["images"], 1)
        count = len(self.calls)
        self.run_queue(new_plan)
        self.assertEqual(sum(path == "/images/generations" for path, _ in self.calls[count:]), 1)


if __name__ == "__main__":
    unittest.main()
