#!/usr/bin/env python3
"""Behavior tests for retrieval, controlled trials, failures and method transfer."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import vsc_learning as learning


STATE = Path(__file__).with_name("vsc_state.py")


class TestRetrieval(unittest.TestCase):
    def test_task_relevance_budget_and_explicit_selection(self):
        candidates = [
            {"category": "memory", "value": {"id": "M-0001", "content": "打斗时保持动作方向线。"}, "search": "打斗 动作"},
            {"category": "memory", "value": {"id": "M-0002", "content": "品牌产品应保持包装字体。"}, "search": "品牌 产品 包装"},
        ]
        selected, stats = learning.retrieve("设计武打动作", candidates, 1000)
        self.assertEqual([entry["value"]["id"] for entry in selected], ["M-0001"])
        self.assertLessEqual(stats["used_chars"], stats["budget_chars"])
        selected, _ = learning.retrieve("设计武打动作", candidates, 1000, ["M-0002"])
        self.assertEqual(selected[0]["value"]["id"], "M-0002")
        with self.assertRaisesRegex(ValueError, "超出检索字符预算"):
            learning.retrieve("设计武打动作", candidates, 1, ["M-0001"])

    def test_method_package_rejects_project_payload(self):
        package = {"format": learning.METHOD_FORMAT, "name": "方向线", "kind": "action",
                   "method": "先交代方向，再切动作。", "limits": "仅用于合适动作场景。",
                   "allowed_roles": ["director"], "tags": ["动作"]}
        package["method_sha256"] = learning.method_digest(package)
        self.assertEqual(learning.validate_method_package(package, ["director"])["name"], "方向线")
        with self.assertRaisesRegex(ValueError, "禁止携带"):
            learning.validate_method_package({**package, "project_id": "private"}, ["director"])


class TestLearningWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-learning-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.ok("init", self.project, "--title", "动作试验", "--owner", "导演")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run([sys.executable, "-B", str(STATE), *map(str, args)], capture_output=True, text=True)

    def ok(self, *args):
        result = self.command(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def bad(self, *args):
        result = self.command(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def state(self):
        return json.loads((self.project / "vsc.json").read_text(encoding="utf-8"))

    def artifact(self, name, kind="vsc.learning_sample", stage="production", deps=()):
        content = "已完成的受控试验内容 " + name
        if kind == "vsc.creative_brief":
            content = json.dumps({"format": "vsc.creative-brief/v1", "audience": "短剧观众", "desired_experience": "理解动作方向",
                                  "decision_owner": "导演", "objectives": [{"id": "continuity", "goal": "方向一致",
                                  "success_evidence": "试看片段后能准确复述动作方向"}], "nonnegotiables": [],
                                  "conflict_policy": "由导演裁决目标冲突并记录理由"}, ensure_ascii=False)
        path = self.write(name, content)
        args = ["artifact", "add", self.project, "--type", kind, "--stage", stage, "--file", path]
        for dependency in deps:
            args.extend(["--depends", dependency])
        artifact_id = self.ok(*args).split()[1]
        self.ok("artifact", "decide", self.project, artifact_id, "--status", "approved", "--by", "导演")
        return artifact_id

    def pilot(self):
        source = self.write("sample.txt", "授权的动作参考样片说明")
        source_id = self.ok("source", "add", self.project, "--kind", "document", "--file", source, "--rights", "owned").split()[1]
        evidence = self.write("positive.txt", "保持方向线便于理解。")
        observation = self.ok("learn", "observe", self.project, "--kind", "action", "--source", source_id,
                              "--file", evidence, "--content", "保持方向线。", "--polarity", "positive").split()[1]
        negative = self.write("negative.txt", "跨轴切换导致动作方向错乱。")
        self.ok("learn", "observe", self.project, "--kind", "action", "--source", source_id,
                "--file", negative, "--content", "无提示跨轴是反例。", "--polarity", "negative")
        capability = self.ok("capability", "propose", self.project, "--name", "方向线方法", "--kind", "action",
                             "--observation", observation, "--observation", "O-0002", "--method", "先建立方向线再切动作镜头。",
                             "--limits", "仅用于动作方向明确的场景。", "--role", "director", "--tag", "动作").split()[1]
        self.ok("capability", "decide", self.project, capability, "--status", "pilot", "--by", "导演")
        input_id = self.artifact("input.txt", "vsc.creative_brief", "brief")
        context = self.ok("context", "build", self.project, "--role", "director", "--task", "设计打斗动作",
                          "--artifact", input_id, "--pilot", capability).split()[1]
        baseline = self.artifact("baseline.txt", deps=[input_id])
        output = self.artifact("output.txt", deps=[input_id])
        report = self.artifact("report.txt", "vsc.learning_evaluation", deps=[baseline, output])
        return capability, input_id, context, baseline, output, report

    def evaluate(self, fixture, result="pass", resolves=(), criteria="方向清晰且人物动作衔接优于基线"):
        capability, _input, context, baseline, output, report = fixture
        args = ["capability", "evaluate", self.project, capability, "--result", result, "--context", context,
                "--output", output, "--baseline", baseline, "--evidence", report,
                "--criteria", criteria, "--by", "导演", "--note", "已比较同输入下的基线与候选"]
        for evaluation_id in resolves:
            args.extend(["--resolves", evaluation_id])
        return self.ok(*args)

    def test_pilot_is_explicit_and_trial_binding_is_recorded(self):
        fixture = self.pilot()
        capability, input_id, context, *_ = fixture
        packet_path = self.project / "10-记忆" / "上下文" / (context + ".json")
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["approved_capabilities"], [])
        self.assertEqual(packet["pilot_capabilities"][0]["id"], capability)
        trial = self.state()["learning"]["trials"][0]
        self.assertEqual(trial["input_versions"][0]["id"], input_id)
        self.assertEqual(trial["context_id"], context)
        self.ok("context", "build", self.project, "--role", "director", "--task", "设计打斗动作")
        normal = json.loads((self.project / "10-记忆" / "上下文" / "CT-0002.json").read_text(encoding="utf-8"))
        self.assertEqual(normal["pilot_capabilities"], [])
        self.assertIn("必须提供", self.bad("context", "build", self.project, "--role", "director", "--task", "打斗", "--pilot", capability))
        self.assertIn("超出", self.bad("context", "build", self.project, "--role", "director", "--task", "打斗", "--pilot", capability,
                                       "--artifact", input_id, "--budget-chars", "1"))

    def test_a_later_fail_blocks_prior_pass_until_explicit_comparable_retest(self):
        fixture = self.pilot()
        capability = fixture[0]
        self.evaluate(fixture, "pass")
        self.evaluate(fixture, "fail")
        self.assertIn("未解决", self.bad("capability", "decide", self.project, capability, "--status", "approved", "--by", "导演"))
        self.evaluate(fixture, "pass", ["EV-0002"])
        self.ok("capability", "decide", self.project, capability, "--status", "approved", "--by", "导演")
        entries = self.state()["learning"]["capabilities"][0]["evaluations"]
        self.assertEqual([entry["result"] for entry in entries], ["pass", "fail", "pass"])
        self.assertEqual(entries[-1]["resolves"], ["EV-0002"])

    def test_tampered_context_or_output_cannot_become_learning_evidence(self):
        fixture = self.pilot()
        capability, _, context, baseline, output, report = fixture
        context_path = self.project / "10-记忆" / "上下文" / (context + ".json")
        context_path.write_text("{}", encoding="utf-8")
        message = self.bad("capability", "evaluate", self.project, capability, "--result", "pass", "--context", context,
                           "--baseline", baseline, "--output", output, "--evidence", report,
                           "--criteria", "方向线", "--by", "导演", "--note", "probe")
        self.assertIn("上下文文件", message)
        self.assertEqual(self.state()["learning"]["capabilities"][0]["evaluations"], [])

    def test_superseded_output_invalidates_pass_before_promotion(self):
        fixture = self.pilot()
        capability, *_ = fixture
        self.evaluate(fixture)
        output = fixture[4]
        replacement = self.write("replacement.txt", "改进后的新动作输出")
        replacement_id = self.ok("artifact", "add", self.project, "--type", "vsc.learning_sample", "--stage", "production", "--file", replacement,
                                 "--depends", fixture[1], "--supersedes", output).split()[1]
        self.ok("artifact", "decide", self.project, replacement_id, "--status", "approved", "--by", "导演")
        self.assertIn("没有有效", self.bad("capability", "decide", self.project, capability, "--status", "approved", "--by", "导演"))

    def test_cross_project_import_is_a_method_only_and_requires_new_evaluation(self):
        fixture = self.pilot()
        self.evaluate(fixture)
        capability = fixture[0]
        self.ok("capability", "decide", self.project, capability, "--status", "approved", "--by", "导演")
        destination = self.root / "method.json"
        self.ok("capability", "export", self.project, capability, "--file", destination, "--name", "通用方向线",
                "--reusable-method", "切换动作镜头前先交代运动方向。", "--reusable-limits", "不能替代审片。", "--confirm-generalized")
        package = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(set(package), learning.METHOD_FIELDS)
        self.assertNotIn(self.state()["project_id"], json.dumps(package))
        second = self.root / "second"
        self.ok("init", second, "--title", "新项目", "--owner", "导演")
        self.ok("capability", "import", second, "--file", destination)
        imported = json.loads((second / "vsc.json").read_text(encoding="utf-8"))["learning"]["capabilities"][0]
        self.assertEqual((imported["status"], imported["evaluations"], imported["observation_ids"]), ("draft", [], []))
        self.assertIn("不能为空", self.bad("capability", "decide", second, imported["id"], "--status", "pilot", "--by", "导演"))
        self.ok("capability", "decide", second, imported["id"], "--status", "pilot", "--by", "导演", "--note", "已确认方法适用本项目")
        self.assertIn("没有有效", self.bad("capability", "decide", second, imported["id"], "--status", "approved", "--by", "导演"))
        self.project = second
        input_id = self.artifact("second-input.txt", "vsc.creative_brief", "brief")
        context = self.ok("context", "build", second, "--role", "director", "--task", "打斗方向线试用",
                          "--artifact", input_id, "--pilot", imported["id"]).split()[1]
        baseline = self.artifact("second-baseline.txt", deps=[input_id])
        output = self.artifact("second-output.txt", deps=[input_id])
        report = self.artifact("second-report.txt", "vsc.learning_evaluation", deps=[baseline, output])
        self.evaluate((imported["id"], input_id, context, baseline, output, report))
        self.ok("capability", "decide", second, imported["id"], "--status", "approved", "--by", "导演")
        self.assertEqual(self.state()["learning"]["capabilities"][0]["status"], "approved")

    def test_old_pass_is_not_valid_learning_evidence(self):
        fixture = self.pilot()
        state = self.state()
        state["learning"]["capabilities"][0]["evaluations"].append({"result": "pass", "evidence": fixture[-1], "by": "旧版本"})
        (self.project / "vsc.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.assertIn("旧评测", self.bad("capability", "decide", self.project, fixture[0], "--status", "approved", "--by", "导演"))
        self.assertEqual([entry["polarity"] for entry in self.state()["learning"]["observations"]], ["positive", "negative"])

    def test_changed_observation_source_prevents_further_trial_or_promotion(self):
        fixture = self.pilot()
        self.evaluate(fixture)
        self.write("sample.txt", "同路径已换成另一个来源内容")
        message = self.bad("capability", "decide", self.project, fixture[0], "--status", "approved", "--by", "导演")
        self.assertIn("来源 S-0001 文件缺失或已改变", message)
        self.assertIn("来源不可用", self.bad("context", "build", self.project, "--role", "director", "--task", "打斗动作",
                                             "--pilot", fixture[0], "--artifact", fixture[1]))

    def test_context_retrieves_relevant_visible_memory_and_reports_budget(self):
        for text, sensitivity in (("打斗动作要保持方向线", "project"), ("品牌包装有固定字体", "project"), ("打斗演员内部身份", "restricted")):
            memory_id = self.ok("memory", "add", self.project, "--scope", "project", "--kind", "lesson",
                                "--content", text, "--sensitivity", sensitivity).split()[1]
            self.ok("memory", "decide", self.project, memory_id, "--status", "approved", "--by", "导演")
        context = self.ok("context", "build", self.project, "--role", "director", "--task", "打斗动作设计", "--budget-chars", "500").split()[1]
        packet = json.loads((self.project / "10-记忆" / "上下文" / (context + ".json")).read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in packet["approved_memories"]], ["M-0001"])
        self.assertLessEqual(packet["retrieval"]["used_chars"], 500)
        self.assertIn("不可用", self.bad("context", "build", self.project, "--role", "director", "--task", "打斗动作设计", "--memory", "M-0003"))


if __name__ == "__main__":
    unittest.main()
