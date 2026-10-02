#!/usr/bin/env python3
"""vsc_kernel.py 自测。运行：python3 scripts/test_vsc_kernel.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KERNEL = HERE / "vsc_kernel.py"
STATE = HERE / "vsc_state.py"


def run(*args):
    return subprocess.run([sys.executable, "-B", str(KERNEL), *map(str, args)], capture_output=True, text=True)


class TestWorkflowKernel(unittest.TestCase):
    def test_doctor_proves_declared_surface_exists(self):
        result = run("doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stages=13", result.stdout)
        self.assertIn("roles=12", result.stdout)

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
