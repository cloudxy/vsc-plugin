#!/usr/bin/env python3
"""scripts/kernel/catalog.py 自测。运行：python3 -B tests/run.py --test kernel.integration.test_vsc_kernel"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT, SCRIPTS
KERNEL = SCRIPTS / "kernel/catalog.py"
STATE = SCRIPTS / "project/state.py"


def run(*args):
    return subprocess.run([sys.executable, "-B", str(KERNEL), *map(str, args)], capture_output=True, text=True)


class TestWorkflowKernel(unittest.TestCase):
    def test_doctor_proves_declared_surface_exists(self):
        result = run("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stages=13", result.stdout)
        self.assertIn("roles=14", result.stdout)
        self.assertIn("hosts=5", result.stdout)

    def test_route_is_the_single_machine_readable_dispatch(self):
        result = run("route", "produce", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        route = json.loads(result.stdout)
        self.assertEqual(route["command"], "vsc-produce")
        self.assertEqual(route["roles"], ["generation-producer", "continuity-supervisor"])
        self.assertEqual(route["vendor_skill_stage"], "produce")

    def test_contract_interface_dispatches_to_owned_validator(self):
        result = run("contract", "validate", "vsc.remotion-render-plan/v1", ROOT / "templates/remotion-render-plan.json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALID:", result.stdout)

    def test_unknown_stage_is_rejected(self):
        result = run("route", "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知工作流阶段", result.stderr)

    def test_product_roles_are_discovered_in_maintenance_without_creative_stage(self):
        route = json.loads(run("route", "architecture", "--json").stdout)
        self.assertEqual(route["roles"], ["orchestrator", "product-manager", "product-designer"])
        self.assertEqual(route["profile_stages"], [])
        roles = {card["id"]: card for card in json.loads(run("roles", "--json").stdout)}
        from vsc.project.role_runtime import bind_packet, validate_packet
        for role in ("product-manager", "product-designer"):
            with self.subTest(role=role):
                packet = dict(context_id="CT-product", project={"project_id": "synthetic"}, role=roles[role],
                    task="检查阅读入口", inputs=[], approved_memories=[], rules=[])
                packet = bind_packet(packet, review_mode="fresh")
                self.assertEqual(validate_packet(packet, role), [])
                self.assertEqual(packet["dispatch"]["artifact_access"], "read_only")
                with self.assertRaisesRegex(ValueError, "read-only"):
                    bind_packet(packet, review_mode="fresh", ownership=["reader.js"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "实际生产计划需要FFmpeg")
    def test_batch_contract_requires_and_validates_real_project(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "vsc.json").write_text('{"project_id":"batch-test"}')
            batch = {"format":"vsc.production-batch/v1", "project_id":"batch-test", "id":"batch", "max_remote_jobs":1,
                     "budget":{"max_images":1,"max_video_seconds":0}, "jobs":[{"id":"image", "kind":"image", "depends_on":[],
                         "args":{"out":"06-素材", "name":"prop", "purpose":"asset", "prompt":"one blank envelope"}}]}
            path = project / "batch.json"
            path.write_text(json.dumps(batch))
            missing = run("contract", "validate", batch["format"], path)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("需要 --project", missing.stderr)
            result = run("contract", "validate", batch["format"], path, "--project", project)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["usage_bound"]["images"], 1)
            batch["project_id"] = "foreign"
            path.write_text(json.dumps(batch))
            self.assertNotEqual(run("contract", "validate", batch["format"], path, "--project", project).returncode, 0)

    def test_state_machine_reads_the_registered_role_card(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            init = subprocess.run([sys.executable, "-B", str(STATE), "init", str(project), "--title", "测试"], capture_output=True, text=True)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            build = subprocess.run([sys.executable, "-B", str(STATE), "context", "build", str(project), "--role", "remotion-composer", "--task", "建立预演"], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            packet = json.loads((project / "10-记忆/上下文/CT-0001.json").read_text("utf-8"))
            self.assertEqual(packet["role"]["identity"], "可编程时间线与确定性渲染负责人")
            self.assertEqual(packet["role"]["agent"], "agents/remotion-composer.md")


if __name__ == "__main__":
    unittest.main()
