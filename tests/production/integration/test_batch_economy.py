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

    def test_ten_attempts_do_not_multiply_core_records(self):
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

    def test_preview_three_states(self):
        plan = P.build_plan(self.project, self.economy_batch)
        preview = P.preview(self.project, plan)
        self.assertEqual(preview["jobs"][0]["state"], "execute")
        self.assertEqual(preview["usage_bound"]["images"], 1)
        P.run(self.project, plan, plan["plan_sha256"], runner=self.runner)
        preview = P.preview(self.project, plan)
        self.assertEqual(preview["jobs"][0]["state"], "reuse")  # 成功且校验通过 → 复用，不再付费


if __name__ == "__main__":
    unittest.main()
