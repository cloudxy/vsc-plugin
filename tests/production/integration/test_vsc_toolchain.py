#!/usr/bin/env python3
"""只读工具就绪诊断行为测试；仅临时项目/素材库，不访问供应商。"""
import contextlib
import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from support.paths import ROOT
import vsc.story.consistency as C
import vsc.adapters.providers.volc_ark.api as A
import vsc.assets.library as L
import vsc.knowledge.recipes as R
import vsc.adapters.media.toolchain as T


class ToolchainTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "测试 作品"
        self.project.mkdir()
        self.library = self.root / "素材 库"
        self.write("vsc.json", {"project_id": "test-project"})
        self.audio = self.project / "sample.wav"
        with wave.open(str(self.audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(b"\x00\x00" * 480)

    def write(self, name, value):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
        return path

    def record(self, provider="doubao_speech", kind="audio"):
        return {"format": C.RECORD_FORMAT, "project_id": "test-project", "kind": kind,
                "purpose": "asset" if kind != "video" else "candidate", "shot_id": "SH-1" if kind == "video" else None,
                "inputs": {"prompt": "test fixture", "references": []}, "engine": {"provider": provider, "model": "test-model"},
                "budget": {"billable": False}, "submitted_at": "2026-10-11T00:00:00+08:00", "finished_at": "2026-10-11T00:00:01+08:00",
                "status": "succeeded", "errors": [], "selection": None,
                "outputs": [{"id": "sample", "path": "sample.wav", "sha256": A.sha256(self.audio)}]}

    def cli(self, *args, project=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = T.main(["--project", str(project or self.project), "--library", str(self.library), *args])
        return code, out.getvalue(), err.getvalue()

    def report(self):
        code, out, err = self.cli("--json")
        return code, json.loads(out), err

    def tools(self, report):
        return {item["id"]: item for item in report["tools"]}

    def test_environment_presence_never_counts_as_verified_candidate(self):
        secrets = {name: "secret-test-" + str(index) for index, name in enumerate(T.ENV_NAMES)}
        with mock.patch.dict(os.environ, secrets):
            code, report, err = self.report()
        self.assertEqual(code, 0, err)
        tools = self.tools(report)
        visual = tools["ark_visual"]
        self.assertFalse(visual["configured"])
        self.assertEqual(visual["configuration"]["status"], "blocked_by_plan_rules")
        self.assertIn("Agent Plan", visual["configuration"]["blocked_reason"])
        for identifier in ("ark_image", "ark_video", "doubao_speech", "seed_audio"):
            tool = tools[identifier]
            self.assertTrue(tool["implemented"])
            self.assertTrue(tool["configured"])
            self.assertEqual(tool["verified_candidates"]["count"], 0)
            self.assertEqual(tool["permission_verification"], "not_probed")
            self.assertIsNone(tool["configuration"]["missing_hint"])
            self.assertEqual(tool["human_review"], "pending")
        self.assertFalse(report["network_probed"])
        self.assertFalse(report["approval_granted"])
        self.assertIn("不验证模型权限", report["meaning"]["configured"])

    def test_missing_credentials_are_pending_with_zero_exit(self):
        blank = {name: "" for name in T.ENV_NAMES}
        with mock.patch.dict(os.environ, blank):
            code, report, err = self.report()
        self.assertEqual(code, 0, err)
        for identifier in ("ark_image", "ark_video", "ark_visual", "doubao_speech", "seed_audio"):
            tool = self.tools(report)[identifier]
            self.assertFalse(tool["configured"])
            self.assertEqual(tool["configuration"]["status"],
                             "blocked_by_plan_rules" if identifier == "ark_visual" else "pending")
            self.assertEqual(tool["configuration"]["present_env_names"], [])
            self.assertIn("source ~/.zshenv", tool["configuration"]["missing_hint"])
        for identifier in ("procedural_audio", "queue", "recipes", "craft", "sequence", "ffmpeg", "ffprobe"):
            self.assertIn(identifier, self.tools(report))
        self.assertEqual(report["errors"], [])
        with mock.patch.dict(os.environ, blank):
            code, out, _ = self.cli()
        self.assertEqual(code, 0)
        self.assertIn("configuration=pending", out)
        self.assertIn("ARK_AGENT_PLAN_API_KEY", out)
        self.assertIn("火山方舟 Agent 版本", out)
        self.assertIn("~/.zshenv", out)

    def test_grok_subscription_tools_follow_login_state_without_env(self):
        import vsc.adapters.providers.xai_grok.credentials as grok_credentials
        blank = {name: "" for name in T.ENV_NAMES}
        with mock.patch.dict(os.environ, blank, clear=True):
            with mock.patch.object(grok_credentials, "LOGIN_FILE", Path("/nonexistent/auth.json")):
                code, report, err = self.report()
                self.assertEqual(code, 0, err)
                for identifier in ("grok_image", "grok_video"):
                    tool = self.tools(report)[identifier]
                    self.assertTrue(tool["implemented"])
                    self.assertFalse(tool["configured"])
                    self.assertEqual(tool["configuration"]["status"], "pending")
                    self.assertEqual(tool["configuration"]["any_env_names"], [])
                    self.assertIn("grok", tool["configuration"]["missing_hint"])
            login = self.root / "auth.json"
            login.write_text(json.dumps({"https://auth.x.ai::u": {"key": "grok-login-secret-value",
                                                                  "expires_at": "2999-01-01T00:00:00Z"}}), "utf-8")
            with mock.patch.object(grok_credentials, "LOGIN_FILE", login):
                code, report, err = self.report()
                self.assertEqual(code, 0, err)
                for identifier in ("grok_image", "grok_video"):
                    tool = self.tools(report)[identifier]
                    self.assertTrue(tool["configured"])
                    self.assertEqual(tool["configuration"]["status"], "present")
                    self.assertIsNone(tool["configuration"]["missing_hint"])
                    self.assertEqual(tool["verified_candidates"]["count"], 0)
                self.assertNotIn("grok-login-secret-value", json.dumps(report))

    def test_actual_same_project_schema_success_and_sha_evidence_counts(self):
        for index, (provider, kind, tool) in enumerate((
                ("volcengine_ark", "image", "ark_image"), ("volcengine_ark", "video", "ark_video"),
                ("doubao_speech", "audio", "doubao_speech"), ("doubao_audio", "audio", "seed_audio"),
                ("vsc_procedural_audio", "audio", "procedural_audio"))):
            self.write(f"evidence/{index}-生成记录.json", self.record(provider, kind))
        # 凭证缺失不抹去已经存在的文件证据，也不把该证据称为现在有权限。
        with mock.patch.dict(os.environ, {name: "" for name in T.ENV_NAMES}):
            code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(report["project_evidence"]["verified_candidates"]), 5)
        for identifier in ("ark_image", "ark_video", "doubao_speech", "seed_audio", "procedural_audio"):
            self.assertEqual(self.tools(report)[identifier]["verified_candidates"]["count"], 1)
        self.assertFalse(self.tools(report)["ark_image"]["configured"])
        self.assertEqual(report["human_review"], "pending")

    def test_failed_foreign_error_and_invalid_schema_do_not_count(self):
        failed = self.record()
        failed.update(status="failed", outputs=[], errors=[{"error": "fixture failure"}])
        self.write("failed-生成记录.json", failed)
        foreign = self.record()
        foreign["project_id"] = "different-project"
        self.write("foreign-生成记录.json", foreign)
        error = self.record()
        error["errors"] = [{"error": "retained failure"}]
        self.write("error-生成记录.json", error)
        invalid = self.record()
        del invalid["engine"]
        self.write("invalid-生成记录.json", invalid)
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])
        self.assertEqual(len(report["project_evidence"]["rejected"]), 4)
        self.assertTrue(report["errors"])

    def test_bad_missing_or_escaping_output_sha_never_counts(self):
        bad = self.record()
        bad["outputs"][0]["sha256"] = "0" * 64
        self.write("bad-生成记录.json", bad)
        missing = self.record()
        missing["outputs"][0]["path"] = "missing.wav"
        self.write("missing-生成记录.json", missing)
        outside = self.root / "outside.wav"
        outside.write_bytes(self.audio.read_bytes())
        (self.project / "escape.wav").symlink_to(outside)
        escape = self.record()
        escape["outputs"][0]["path"] = "escape.wav"
        self.write("escape-生成记录.json", escape)
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])
        self.assertEqual(len(report["errors"]), 3)

    def test_only_selected_project_and_no_duplicate_snapshots_count(self):
        value = self.record()
        self.write("take-生成记录.json", value)
        self.write("snapshot/take-生成记录.json", value)
        other = self.root / "other-project"
        other.mkdir()
        (other / "other-生成记录.json").write_text(json.dumps(value), "utf-8")
        code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(report["project_evidence"]["verified_candidates"]), 1)

    def test_abandoned_snapshot_and_hidden_records_are_not_active_evidence(self):
        invalid = self.record()
        invalid["outputs"][0]["sha256"] = "0" * 64
        for directory in ("废弃", ".vsc-production", "09-台账", "10-记忆", "node_modules", "build", ".cache"):
            self.write(f"06-素材/{directory}/bad-生成记录.json", invalid)
            self.write(f"{directory}/valid-生成记录.json", self.record())
        self.write("active-生成记录.json", self.record())
        code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["project_evidence"]["rejected"], [])
        self.assertEqual(len(report["project_evidence"]["verified_candidates"]), 1)
        self.assertEqual(report["project_evidence"]["verified_candidates"][0]["record"], "active-生成记录.json")

    def test_legacy_non_contract_is_rejected_without_claiming_availability(self):
        self.write("old/生成记录.json", {"status": "succeeded", "model": "legacy", "files": ["sample.wav"]})
        self.write("old/视觉检查.json", {"format": "legacy-visual/v0", "passed": True})
        code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])
        self.assertEqual(report["project_evidence"]["verified_visual_reports"], [])
        self.assertEqual([entry["reason"] for entry in report["project_evidence"]["rejected"]],
                         ["legacy/non-contract", "legacy/non-contract"])
        for tool in report["tools"]:
            self.assertEqual(tool["verified_candidates"]["count"], 0)
            self.assertEqual(tool["human_review"], "pending")

    def test_visual_evidence_is_separate_advisory_and_subject_sha_checked(self):
        visual = json.loads((ROOT / "templates/visual-check.json").read_text("utf-8"))
        visual["project_id"] = "test-project"
        visual["subject"] = {"path": "sample.wav", "sha256": A.sha256(self.audio)}
        self.write("sample-视觉检查.json", visual)
        code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])
        self.assertEqual(self.tools(report)["ark_visual"]["verified_candidates"]["count"], 0)
        self.assertEqual(self.tools(report)["ark_visual"]["verified_visual_reports"]["count"], 1)
        self.assertTrue(report["project_evidence"]["verified_visual_reports"][0]["advisory"])
        visual["subject"]["sha256"] = "0" * 64
        self.write("sample-视觉检查.json", visual)
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["project_evidence"]["verified_visual_reports"], [])

    def test_library_all_taxonomy_specs_are_not_media(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main(["install", "--all", "--library", str(self.library)]), 0)
            self.assertEqual(L.main(["--library", str(self.library), "add", "--kind", "ambience", "--id", "real-local-audio",
                                    "--name", "测试环境底", "--summary", "test fixture", "--rights", "owned", "--file", str(self.audio) + ":loop"]), 0)
        code, report, err = self.report()
        self.assertEqual(code, 0, err)
        self.assertEqual(set(report["library"]["kinds"]), set(L.taxonomy()[0]))
        self.assertEqual(report["library"]["specification_count"], 20)
        self.assertEqual(report["library"]["media_count"], 1)
        for kind, counts in report["library"]["kinds"].items():
            self.assertEqual(counts["specification_count"], 1)
            self.assertEqual(counts["media_count"], int(kind == "ambience"))
        # 素材库媒体存在也不是该作品已实测的供应商证据。
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])

    def test_invalid_library_entry_and_invalid_project_are_errors(self):
        folder = self.library / "prop" / "broken"
        folder.mkdir(parents=True)
        (folder / "item.json").write_text("{}", "utf-8")
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertTrue(report["errors"])
        code, out, _ = self.cli("--json", project=self.root / "missing-project")
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out)["errors"])

    def test_malformed_record_and_project_index_are_reported_without_traceback(self):
        (self.project / "broken-生成记录.json").write_text("{not json", "utf-8")
        malformed = self.record()
        malformed["outputs"][0]["id"] = {"not": "a string"}
        self.write("nested-生成记录.json", malformed)
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["project_evidence"]["verified_candidates"], [])
        self.assertEqual(len(report["errors"]), 2)
        self.write("vsc.json", [])
        code, report, _ = self.report()
        self.assertEqual(code, 1)
        self.assertIsNone(report["project_id"])

    def test_json_and_text_are_read_only_and_do_not_leak_secrets(self):
        secret = "super-secret-never-output-toolchain-test"
        value = self.record(provider=secret)
        value["inputs"]["prompt"] = secret
        self.write("take-生成记录.json", value)
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with mock.patch.dict(os.environ, {name: secret for name in T.ENV_NAMES}):
            for args in (("--json",), ()):
                code, out, err = self.cli(*args)
                self.assertEqual(code, 0, err)
                self.assertNotIn(secret, out + err)
            self.assertIn("ARK_AGENT_PLAN_API_KEY", self.cli("--json")[1])
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(self.library.exists())


if __name__ == "__main__":
    unittest.main()
