"""Grok batch kinds: plan-time validation via the shared compiler (offline, no POST)."""
import json
import tempfile
import unittest
import contextlib
import io
from unittest import mock
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


    def test_formal_four_modes_use_actual_cli_budget_guard_and_valid_media(self):
        from support.fixtures.project import FixedRunFixture
        from vsc.production import run as formal, budget
        from vsc.project import artifacts, state as state_module
        from vsc.adapters.providers.xai_grok import api as grok
        fixture = FixedRunFixture(self.project)
        inputs = []
        for kind, name in (("vsc.asset_bible", "bible.json"), ("vsc.scene_state", "state.json")):
            data = json.loads((self.project / name).read_text())
            data["project_id"] = "test-project"
            inputs.append(fixture.register(kind, data, stage="animatic"))
        inputs.append(fixture.register("vsc.animatic", {"format": "vsc.animatic/v1"}, stage="animatic"))
        common = {"out": "out", "prompt": "synthetic motion", "shot": "SH-001"}
        jobs = [
            {"id": "I", "kind": "grok_image", "depends_on": [], "args": {**common, "name": "i", "purpose": "asset"}},
            {"id": "V", "kind": "grok_video", "depends_on": [], "args": {**common, "name": "v", "duration": 6,
                "bible": {"path": inputs[0]["path"]}, "state": {"path": inputs[1]["path"]},
                "keyframe": [{"path": "first.png", "at": 3}], "voice_id": ["eve"], "no_audio": True}},
            {"id": "E", "kind": "grok_edit", "depends_on": [], "args": {**common, "name": "e", "video": {"path": "take.mp4"}}},
            {"id": "X", "kind": "grok_extend", "depends_on": [], "args": {**common, "name": "x", "video": {"path": "take.mp4"}, "duration": 2}}]
        batch = self.batch(jobs)
        batch["project_id"] = "test-project"
        batch_path = self.project / "batch.json"
        batch_path.write_text(json.dumps(batch))
        plan = P.build_plan(self.project, batch)
        data = {"format": formal.FORMAT, "project_id": "test-project", "scope": "project", "phase": "production",
            "batch": {"path": "batch.json", "sha256": artifacts.digest(batch_path)}, "plan_sha256": plan["plan_sha256"],
            "approved_inputs": [{"id": a["id"], "sha256": a["sha256"]} for a in inputs], "review_after": [],
            "operations": {formal.operation(j): formal.job_units(j) for j in plan["jobs"]}}
        run = fixture.register("vsc.production_run", data, inputs)
        budget.configure(self.project, {"remote_jobs": 4, "images": 1, "video_seconds": 9}, "synthetic reviewer", "offline cap")
        login = self.project / "synthetic-login.json"
        login.write_text(json.dumps({"synthetic": {"user_id": "offline-account", "key": "offline-token"}}))
        calls = []
        def transport(path, payload=None):
            calls.append((path, payload))
            if path.startswith("/images/"):
                return {"data": [{"url": "https://example.invalid/out.png"}]}
            if payload is not None:
                return {"request_id": "remote-" + str(len(calls))}
            return {"status": "done", "video": {"url": "https://example.invalid/out.mp4", "duration": 0.4}}
        def download(url, target):
            target.write_bytes(production_media()["png" if url.endswith("png") else "mp4"])
        def runner(argv, script=None):
            self.assertEqual(script, "providers/xai/grok.py")
            if grok.main(argv) != 0:
                raise RuntimeError("offline actual CLI failed")
        with contextlib.ExitStack() as stack:
            for module in (formal, artifacts, state_module):
                stack.enter_context(mock.patch.object(module, "validate_artifact", side_effect=fixture.validator))
            stack.enter_context(mock.patch.object(grok.grok_credentials, "LOGIN_FILE", login))
            stack.enter_context(mock.patch.object(grok, "call", transport))
            stack.enter_context(mock.patch.object(grok, "download", download))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            self.assertEqual(formal.project_errors(data, self.project, fixture.read_state(), run), [])
            with mock.patch.dict("os.environ", {"GROK_BASE_URL": "https://invalid.example/v1"}):
                with self.assertRaisesRegex(RuntimeError, "GROK_BASE_URL"):
                    formal.execute(self.project, run["id"], runner)
            with budget.ledger(self.project) as ledger:
                self.assertEqual(ledger["reservations"], {})
            self.assertEqual(calls, [])
            self.assertEqual(formal.execute(self.project, run["id"], runner)["status"], "completed")
            self.assertEqual(len([p for p, value in calls if value is not None]), 4)
            self.assertEqual(next(value for p, value in calls if p == "/videos/extensions")["duration"], 2)
            video = next(value for p, value in calls if p == "/videos/generations")
            self.assertEqual(video["reference_audios"], [{"voice_id": "eve"}])
            self.assertEqual(video["keyframes"][0]["timestamp_s"], 3)
            self.assertFalse(video["generate_audio"])
            self.assertEqual(len([a for a in fixture.read_state()["artifacts"] if a.get("run_id") == run["id"]]), 4)
            with budget.ledger(self.project) as ledger:
                image_reservation = next(k for k, v in ledger["reservations"].items() if v["operation"].startswith("grok_image:"))
                ledger["reservations"][image_reservation]["status"] = "reserved"
            image_job = plan["jobs"][0]
            image_argv, _ = P.resolve_args(self.project, image_job, {j["id"]: j for j in plan["jobs"]})
            changed = vars(grok.parser().parse_args(image_argv))
            changed["count"] = 2
            with self.assertRaisesRegex(budget.BudgetError, "参数"):
                budget.check_authorization(self.project, image_reservation, formal.operation(image_job), request=changed)
            with budget.ledger(self.project) as ledger:
                ledger["reservations"][image_reservation]["status"] = "usage_unknown"
            login.unlink()
            before = len(calls)
            self.assertEqual(formal.execute(self.project, run["id"], runner)["status"], "completed")
            self.assertEqual(len(calls), before)
            with budget.ledger(self.project) as ledger:
                self.assertTrue(all(v["status"] == "usage_unknown" for v in ledger["reservations"].values()))

    def test_dynamic_png_output_reference_uses_record_and_grok_has_no_synthetic_tail(self):
        image = {"id": "I", "kind": "grok_image", "depends_on": [],
            "args": {"out": "out", "name": "i", "prompt": "p", "purpose": "asset"}}
        video = {"id": "V", "kind": "grok_video", "depends_on": ["I"], "args": {
            "out": "out", "name": "v", "prompt": "p", "shot": "SH-001", "bible": {"path": "bible.json"},
            "state": {"path": "state.json"}, "first_frame": {"job": "I", "output": "image"}}}
        plan = P.build_plan(self.project, self.batch([image, video]))
        png = self.project / "out/i.png"
        png.parent.mkdir()
        png.write_bytes(production_media()["png"])
        record = {"outputs": [{"id": "i", "path": "out/i.png"}]}
        with mock.patch.object(P, "completed", return_value=record):
            argv, hashes = P.resolve_args(self.project, plan["jobs"][1], {j["id"]: j for j in plan["jobs"]})
        self.assertIn("--first-frame=" + str(png.resolve()), argv)
        self.assertIn("out/i.png", hashes)
        self.assertEqual(set(P.outputs(plan["jobs"][1])), {"video"})


    def test_extend_duration_payload_and_source_boundaries_are_preflighted(self):
        from vsc.adapters.providers.xai_grok import spec
        for seconds in (2, 6, 10):
            path, payload = spec.compile_video_operation("grok-imagine-video", "source", "continue", "extend", seconds)
            self.assertEqual((path, payload["duration"]), ("/videos/extensions", seconds))
        for seconds in (None, True, 1, 11, 2.5):
            with self.assertRaises(spec.GrokSpecError):
                spec.compile_video_operation("grok-imagine-video", "source", "continue", "extend", seconds)
        with self.assertRaisesRegex(spec.GrokSpecError, "不支持另设"):
            spec.compile_video_operation("grok-imagine-video", "source", "edit", "edit", 2)
        with self.assertRaisesRegex(P.ProductionError, "固定一张"):
            P.build_plan(self.project, self.batch([{"id": "I", "kind": "grok_image", "depends_on": [],
                "args": {"out": "out", "name": "i", "prompt": "p", "purpose": "asset", "count": 2}}]))
        from vsc.adapters.providers.xai_grok import api as grok
        import subprocess
        source = self.project / "long.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=blue:size=16x16:rate=5",
            "-t", "9", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, timeout=30)
        with self.assertRaisesRegex(grok.GrokError, "8.7"):
            grok.video_source_info(source, "edit")
        source.write_bytes(b"not a video")
        with self.assertRaises(grok.GrokError):
            grok.video_source_info(source, "extend")


if __name__ == "__main__":
    unittest.main()
