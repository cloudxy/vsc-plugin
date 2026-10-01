#!/usr/bin/env python3
"""VSC 状态机自测。运行：python3 scripts/test_vsc_state.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = str(HERE / "vsc_state.py")


def run(*args):
    result = subprocess.run([sys.executable, "-B", STATE, *map(str, args)], capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "雨夜计划"
        code, output = run("init", self.project, "--title", "雨夜计划", "--owner", "导演")
        self.assertEqual(code, 0, output)

    def tearDown(self):
        self.temp.cleanup()

    def ok(self, *args):
        code, output = run(*args)
        self.assertEqual(code, 0, output)
        return output

    def bad(self, *args):
        code, output = run(*args)
        self.assertEqual(code, 1, output)
        return output

    def write(self, rel, content="内容"):
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return path

    def artifact(self, kind, stage, rel, depends=None):
        path = self.write(rel)
        output = self.ok("artifact", "add", self.project, "--type", kind, "--stage", stage, "--file", path,
                         *sum((["--depends", value] for value in (depends or [])), []))
        artifact_id = output.split()[1]
        self.ok("artifact", "decide", self.project, artifact_id, "--status", "approved", "--by", "导演")
        return artifact_id


class TestInitAndProfiles(Base):
    def test_layout_and_identity(self):
        state = json.loads((self.project / "vsc.json").read_text("utf-8"))
        self.assertEqual((state["schema_version"], state["profile_id"]), (1, "vsc.narrative-base"))
        self.assertTrue(state["project_id"].startswith("vsc-project-"))
        for rel in ("00-委托/创作委托.md", "04-视听设计/镜头/镜头表.md", "09-台账/README.md"):
            self.assertTrue((self.project / rel).is_file(), rel)
        self.assertIn("brief", self.ok("next", self.project))

    def test_unknown_profile_rejected(self):
        project = Path(self.temp.name) / "坏项目"
        self.assertIn("未知 Profile", self.bad("init", project, "--title", "坏项目", "--profile", "vsc.unknown"))
        self.assertIn("vsc.novel-serial", self.ok("profile", "list"))


class TestArtifactsAndGates(Base):
    def test_gate_requires_source_and_approved_artifacts(self):
        self.assertIn("vsc.creative_brief", self.bad("gate", "check", self.project, "brief"))
        self.artifact("vsc.creative_brief", "brief", "00-委托/创作委托-v1.md")
        self.ok("gate", "check", self.project, "brief")
        self.assertIn("尚未登记来源", self.bad("gate", "check", self.project, "source"))
        novel = self.write("01-来源/原著.txt", "雨夜里，她没有签收那封信。")
        self.ok("source", "add", self.project, "--kind", "novel", "--file", novel)
        source_map = self.artifact("vsc.source_map", "source", "01-来源/来源映射.md")
        self.ok("gate", "check", self.project, "source")
        self.assertIn("改编设计", self.ok("status", self.project))
        self.assertIn("A-0002", source_map)

    def test_dependency_and_decision_are_recorded(self):
        brief = self.artifact("vsc.creative_brief", "brief", "00-委托/brief.md")
        self.bad("artifact", "add", self.project, "--type", "vsc.source_map", "--stage", "source",
                 "--file", self.write("01-来源/map.md"), "--depends", "A-9999")
        source_map = self.artifact("vsc.source_map", "source", "01-来源/map.md", [brief])
        out = self.ok("decision", "add", self.project, "--kind", "baseline", "--target", source_map,
                      "--outcome", "accepted", "--by", "作者", "--reason", "保留原文中的信息差")
        self.assertIn("D-0001", out)
        state = json.loads((self.project / "vsc.json").read_text("utf-8"))
        self.assertEqual(state["decisions"][0]["target"], source_map)


class TestHandoff(Base):
    def test_generic_handoff_only(self):
        manifest = self.write("01-来源/handoff.json", json.dumps({
            "format": "creative-handoff/v1", "package_id": "package-001", "source": {"title": "外部小说"},
            "artifacts": [], "decisions": []}, ensure_ascii=False))
        self.assertIn("HANDOFF: PASS", self.ok("handoff", "validate", manifest))
        self.assertIn("package-001", self.ok("source", "import", self.project, "--manifest", manifest))
        invalid = self.write("01-来源/not-handoff.json", "{}")
        self.assertIn("格式必须是", self.bad("handoff", "validate", invalid))


if __name__ == "__main__":
    unittest.main()
