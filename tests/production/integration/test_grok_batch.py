"""Grok batch kinds: plan-time validation via the shared compiler (offline, no POST)."""
import json
import tempfile
import unittest
from pathlib import Path

import support.paths  # noqa: F401 - put src on sys.path before vsc imports
from support.fixtures.media import production_media
from vsc.production import production as P


class GrokBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "grok-batch"}), "utf-8")
        (self.project / "first.png").write_bytes(production_media()["png"])
        (self.project / "take.mp4").write_bytes(production_media()["mp4"])
        from support.paths import ROOT
        for name, template in (("bible.json", "asset-bible.json"), ("state.json", "scene-state.json")):
            value = json.loads((ROOT / "templates" / template).read_text())
            value["project_id"] = "grok-batch"
            (self.project / name).write_text(json.dumps(value))

    def batch(self, jobs):
        return {"format": P.FORMAT, "project_id": "grok-batch", "id": "B1",
                "max_remote_jobs": 5, "budget": {"max_images": 5, "max_video_seconds": 60},
                "jobs": jobs}

    def test_grok_image_reference_edit_plan_and_invalid_combo(self):
        plan = P.build_plan(self.project, self.batch([
            {"id": "J1", "kind": "grok_image", "depends_on": [],
             "args": {"out": "素材", "name": "hero-edit", "prompt": "只把外套改成米白色",
                      "ref": [{"path": "first.png"}], "resolution": "2k", "purpose": "asset"}}]))
        self.assertEqual(plan["jobs"][0]["args"]["model"], "grok-imagine-image-2.0")
        self.assertEqual(plan["usage_bound"]["images"], 1)
        with self.assertRaisesRegex(P.ProductionError, "每个逻辑候选固定一张"):
            P.build_plan(self.project, self.batch([
                {"id": "J2", "kind": "grok_image", "depends_on": [],
                 "args": {"out": "素材", "name": "bad", "prompt": "p", "count": 3, "purpose": "asset",
                          "ref": [{"path": "first.png"}]}}]))
        with self.assertRaisesRegex(P.ProductionError, "grok-imagine-image-"):
            P.build_plan(self.project, self.batch([
                {"id": "J3", "kind": "grok_image", "depends_on": [],
                 "args": {"out": "素材", "name": "wrong-model", "prompt": "p", "purpose": "asset",
                          "model": "doubao-seedream-5-0"}}]))

    def test_grok_video_modes_validated_by_shared_compiler(self):
        base = {"out": "视频", "name": "v1", "prompt": "<IMAGE_0> 走向 <IMAGE_1>",
                "shot": "SH-001", "bible": {"path": "bible.json"}, "state": {"path": "state.json"},
                "ref_image": [{"path": "first.png"}], "resolution": "720p", "duration": 6, "ratio": "9:16"}
        plan = P.build_plan(self.project, self.batch([
            {"id": "V1", "kind": "grok_video", "depends_on": [], "args": dict(base)}]))
        self.assertEqual(plan["usage_bound"]["video_seconds"], 6)
        with self.assertRaisesRegex(P.ProductionError, "参考模式分辨率最高 720p"):
            P.build_plan(self.project, self.batch([
                {"id": "V2", "kind": "grok_video", "depends_on": [],
                 "args": dict(base, name="v2", resolution="1080p")}]))
        # 经典模型：首帧与参考图同用被共用编译器在计划期拒绝
        with self.assertRaisesRegex(P.ProductionError, "经典"):
            P.build_plan(self.project, self.batch([
                {"id": "V3", "kind": "grok_video", "depends_on": [],
                 "args": dict(base, name="v3", model="grok-imagine-video",
                              first_frame={"path": "first.png"})}]))

    def test_grok_edit_and_extend_plans_with_probe_budget(self):
        edit = {"id": "E1", "kind": "grok_edit", "depends_on": [],
                "args": {"out": "视频", "name": "take-edit", "shot": "SH-001", "prompt": "把雨势加大",
                         "video": {"path": "take.mp4"}}}
        extend = {"id": "X1", "kind": "grok_extend", "depends_on": [],
                  "args": {"out": "视频", "name": "take-extend", "shot": "SH-001", "prompt": "他继续走",
                           "video": {"path": "take.mp4"}, "duration": 6}}
        plan = P.build_plan(self.project, self.batch([edit, extend]))
        seconds = plan["usage_bound"]["video_seconds"]
        self.assertGreaterEqual(seconds, 6)  # 续接按新增 6 秒计
        self.assertTrue(any(job["args"].get("source_seconds") for job in plan["jobs"]))  # 编辑按探测时长计
        with self.assertRaisesRegex(P.ProductionError, "prompt"):  # 队列层先拒绝空提示词
            P.build_plan(self.project, self.batch([
                {"id": "X2", "kind": "grok_extend", "depends_on": [],
                 "args": {"out": "视频", "name": "x2", "shot": "SH-001",
                          "video": {"path": "take.mp4"}, "duration": 6, "prompt": ""}}]))
        with self.assertRaisesRegex(P.ProductionError, "经典"):
            P.build_plan(self.project, self.batch([
                {"id": "E2", "kind": "grok_edit", "depends_on": [],
                 "args": {"out": "视频", "name": "e2", "shot": "SH-001", "prompt": "p",
                          "model": "grok-imagine-video-1.5", "video": {"path": "take.mp4"}}}]))


if __name__ == "__main__":
    unittest.main()
