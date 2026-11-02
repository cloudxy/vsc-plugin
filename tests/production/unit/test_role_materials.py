"""Real local reading and captured tool-free requests; no host, DB or provider."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vsc.assets.resource_service import ResourceError
from vsc.bootstrap import repository_root
from vsc.knowledge.craft import read_teaching, teaching_digest
from vsc.production.role_materials import TASKS, compile_role_materials, validate_role_materials
from vsc.production.role_planner import run_role_plan
from vsc.production.text_tool_host import GrokBuildTextTools

ROOT = repository_root()


class RoleMaterialsTests(unittest.TestCase):
    def copy_inputs(self, directory, bundle):
        root = Path(directory)
        for path in {item["path"] for item in bundle["materials"]}:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        return root

    def test_all_task_selections_read_real_bounded_body_not_link_inventory(self):
        for task, (role, skill, _) in TASKS.items():
            with self.subTest(task=task):
                bundle = compile_role_materials(role, skill, task)
                self.assertEqual(bundle, validate_role_materials(bundle))
                self.assertLessEqual(bundle["manifest"]["total_chars"], 24000)
                for item in bundle["materials"]:
                    self.assertEqual(item["sha256"], hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest())
                    self.assertEqual(item["text_sha256"], hashlib.sha256(item["text"].encode()).hexdigest())
                self.assertEqual(bundle["materials"][0]["text"], (ROOT / "agents" / (role + ".md")).read_text())
                self.assertEqual(bundle["materials"][1]["text"], (ROOT / "skills" / skill / "SKILL.md").read_text())
        bundle = compile_role_materials("screenwriter", "vsc-script", "novel-body")
        action = next(item["text"] for item in bundle["materials"] if item["selector"] == "anchor:visual-dialogue")
        self.assertIn("行动必须产生可追的后果", action)
        self.assertNotIn("短片集中一个核心变化", action)
        self.assertNotIn("skills/vsc-sound/references/voice-space.md", {item["path"] for item in bundle["materials"]})

    def test_selected_method_contains_card_sources_and_canonical_teaching_digest(self):
        bundle = compile_role_materials("director", "vsc-direct", "script", method_ids=["motivated-push", "tracking-block"])
        catalog = json.loads((ROOT / "knowledge/craft.json").read_text())
        methods = [json.loads(item["text"]) for item in bundle["materials"] if item["kind"] == "method"]
        self.assertEqual(len(methods), 2)
        for method in methods:
            card = method["card"]
            sources = [source for source in catalog["sources"] if source["id"] in card["sources"]]
            self.assertEqual(method["teaching_sha256"], teaching_digest(card, sources, read_teaching(card["teaching_ref"])))
            self.assertTrue(method["teaching_available"])
        self.assertEqual(sum(item["selector"] == "anchor:camera-choice" for item in bundle["materials"]), 1)
        no_teaching = compile_role_materials("director", "vsc-direct", "script", method_ids=["angle-context"])
        card = next(json.loads(item["text"]) for item in no_teaching["materials"] if item["kind"] == "method")
        self.assertFalse(card["teaching_available"])

    def test_invalid_selection_path_method_stage_and_budget_fail_closed(self):
        cases = [
            (("director", "vsc-direct", "../../outside"), {}),
            (("screenwriter", "vsc-direct", "script"), {}),
            (("director", "vsc-direct", "script"), {"method_ids": ["https://example.invalid/method"]}),
            (("director", "vsc-direct", "script"), {"method_ids": ["dialogue-space"]}),
            (("director", "vsc-direct", "script"), {"method_ids": ["axis-map", "axis-map"]}),
            (("director", "vsc-direct", "script"), {"max_chars": 100}),
            (("director", "vsc-direct", "script"), {"max_chars": 24001}),
        ]
        for args, kwargs in cases:
            with self.subTest(args=args, kwargs=kwargs), self.assertRaises(ResourceError):
                compile_role_materials(*args, **kwargs)

    def test_missing_drift_and_symlink_escape_reject_original_manifest(self):
        bundle = compile_role_materials("director", "vsc-direct", "blocking")
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = self.copy_inputs(directory, bundle)
            main = root / "skills/vsc-direct/SKILL.md"
            original = main.read_bytes()
            main.write_bytes(original + b"\nchanged\n")
            with self.assertRaises(ResourceError) as changed:
                compile_role_materials("director", "vsc-direct", "blocking", root=root, expected_manifest=bundle["manifest"])
            self.assertEqual(changed.exception.code, "role_materials_changed")
            main.unlink()
            with self.assertRaises(ResourceError) as missing:
                compile_role_materials("director", "vsc-direct", "blocking", root=root)
            self.assertEqual(missing.exception.code, "role_materials_missing")
            escaped = Path(outside) / "external.md"
            escaped.write_bytes(original)
            main.symlink_to(escaped)
            with self.assertRaises(ResourceError) as escaped_error:
                compile_role_materials("director", "vsc-direct", "blocking", root=root)
            self.assertEqual(escaped_error.exception.code, "role_materials_missing")

    def test_section_missing_is_not_silently_skipped(self):
        bundle = compile_role_materials("director", "vsc-direct", "blocking")
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_inputs(directory, bundle)
            path = root / "skills/vsc-direct/references/blocking-coverage.md"
            path.write_text(path.read_text().replace('id="space-blocking"', 'id="gone"'))
            with self.assertRaises(ResourceError) as error:
                compile_role_materials("director", "vsc-direct", "blocking", root=root)
            self.assertEqual(error.exception.code, "role_materials_missing")

    def test_actual_role_and_reference_text_enter_single_turn_prompt_with_manifest(self):
        bundle = compile_role_materials("director", "vsc-direct", "blocking")
        observed = {}

        def runner(command, **kwargs):
            observed["command"], observed["kwargs"] = command, kwargs
            observed["blocks"] = json.loads(Path(command[command.index("--prompt-file") + 1]).read_text())
            return SimpleNamespace(returncode=0, stdout=json.dumps({"structuredOutput": {"plan": "ok"}}))

        skill = bundle["materials"][1]["text"]
        block = {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixed"}}
        value = run_role_plan({"role": {"id": "director"}}, {"fixed_input": "source"}, skill,
            {"required": ["plan"]}, "instructions", materials=bundle, runner=runner, media_blocks=[block])
        self.assertEqual(value, {"plan": "ok"})
        text = observed["blocks"][0]["text"]
        payload = json.loads(text[text.index('{"role_context"'):])
        self.assertEqual(payload["role_materials"], bundle)
        self.assertEqual(payload["input"], {"fixed_input": "source"})
        self.assertNotIn("text", payload["skill"])
        self.assertEqual(observed["blocks"][1], block)
        command = observed["command"]
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--max-turns") + 1], "1")
        self.assertIn("--no-subagents", command)
        self.assertIn("--disable-web-search", command)
        self.assertEqual(observed["kwargs"]["timeout"], 120)

    def test_tampered_text_manifest_or_wrong_role_never_launch_host(self):
        bundle = compile_role_materials("director", "vsc-direct", "blocking")
        altered = copy.deepcopy(bundle)
        altered["materials"][0]["text"] += " fabricated"
        changed_manifest = copy.deepcopy(bundle)
        changed_manifest["manifest"]["sha256"] = "0" * 64
        cases = [(altered, "director", bundle["materials"][1]["text"]),
                 (changed_manifest, "director", bundle["materials"][1]["text"]),
                 (bundle, "screenwriter", bundle["materials"][1]["text"]),
                 (bundle, "director", "stale skill")]
        with patch("vsc.production.role_planner._run_bounded") as runner:
            for materials, role, skill in cases:
                with self.subTest(role=role, skill=skill[:12]), self.assertRaises(ResourceError):
                    run_role_plan({"role": {"id": role}}, {}, skill, {"required": ["plan"]}, "", materials=materials)
            runner.assert_not_called()

    def test_old_transport_shape_and_unknown_timeout_keep_one_submission(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(json.loads(Path(command[command.index("--prompt-file") + 1]).read_text())[0]["text"])
            return SimpleNamespace(returncode=0, stdout='{"result":"{\\"plan\\":\\"legacy\\"}"}')

        self.assertEqual(run_role_plan({}, {"value": 1}, "legacy skill", {"required": ["plan"]}, "", runner=runner), {"plan": "legacy"})
        self.assertEqual(json.loads(calls[0]), {"role_context": {}, "input": {"value": 1}, "skill": "legacy skill"})
        bundle = compile_role_materials("director", "vsc-direct", "blocking")
        with patch("vsc.production.role_planner._run_bounded", side_effect=subprocess.TimeoutExpired("grok", 1)) as runner:
            with self.assertRaises(ResourceError) as error:
                run_role_plan({}, {}, bundle["materials"][1]["text"], {"required": ["plan"]}, "", materials=bundle, error_prefix="canvas")
            self.assertEqual(error.exception.code, "canvas_submission_unknown")
            self.assertEqual(runner.call_count, 1)

    def test_novel_actions_receive_matching_profession_but_translation_scoring_do_not(self):
        captured = []

        def runner(command, **kwargs):
            text = json.loads(Path(command[command.index("--prompt-file") + 1]).read_text())[0]["text"]
            captured.append(json.loads(text[text.index('{"tool"'):]))
            schema = json.loads(command[command.index("--json-schema") + 1])
            result = {key: [] if item["type"] == "array" else 1 if item["type"] == "integer" else "fixed"
                      for key, item in schema["properties"].items()}
            return SimpleNamespace(returncode=0, stdout=json.dumps(result))

        host = GrokBuildTextTools(runner=runner)
        for action in ("synopsis", "characters", "outline", "scenes", "body", "qa_notes"):
            with self.subTest(action=action):
                host.generate("novel", action, {"body": "user draft unchanged"}, [{"fixed": "reference"}])
                payload = captured[-1]
                self.assertEqual(payload["role_materials"]["task"], "novel-" + action)
                self.assertEqual(payload["role_materials"]["role_id"], TASKS["novel-" + action][0])
                self.assertEqual(payload["document"], {"body": "user draft unchanged"})
                self.assertEqual(payload["proofread_references"], [{"fixed": "reference"}])
        for tool, action in (("translation", "translate"), ("scoring", "score"), ("overseas", "localize")):
            with self.subTest(tool=tool):
                host.generate(tool, action, {}, [])
                self.assertNotIn("role_materials", captured[-1])

    def test_fixed_novel_materials_wrong_action_and_foreign_tool_are_rejected(self):
        bundle = compile_role_materials("screenwriter", "vsc-script", "novel-body")
        host = GrokBuildTextTools(runner=lambda *args, **kwargs: self.fail("host should not launch"))
        for tool, action in (("novel", "outline"), ("translation", "translate")):
            with self.subTest(tool=tool), self.assertRaises(ResourceError):
                host.generate(tool, action, {}, [], materials=bundle)
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_inputs(directory, bundle)
            target = root / "agents/screenwriter.md"
            target.write_text(target.read_text() + "\nchanged")
            with patch("vsc.production.role_materials.repository_root", return_value=root):
                with self.assertRaises(ResourceError) as error:
                    host.generate("novel", "body", {}, [], materials=bundle)
            self.assertEqual(error.exception.code, "role_materials_changed")


if __name__ == "__main__":
    unittest.main()
