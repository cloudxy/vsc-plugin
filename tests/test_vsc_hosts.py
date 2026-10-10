#!/usr/bin/env python3
"""vsc_hosts.py 自测。运行：python3 tests/test_vsc_hosts.py"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
import vsc_hosts as HOSTS

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


class HostEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for skill in ("vsc", "vsc-adapt"):
            write(self.root / "skills" / skill / "SKILL.md", f"---\nname: {skill}\ndescription: test\n---\n")
        write(self.root / "agents/director.md", "---\nname: director\ndescription: \"Plan shots.\"\n---\n\n# Director\n\n镜头服务叙事。\n")
        stage = {"id": "adapt", "command": "vsc-adapt", "skill": "vsc-adapt",
                 "entry": {"mode": "adapt", "description": "VSC 改编", "argument_hint": "[第N集]"}}
        write(self.root / "workflow/kernel.json", json.dumps({"format": "vsc.workflow-kernel/v1", "stages": [stage]}, ensure_ascii=False))
        hosts = {
            "format": "vsc.hosts/v1",
            "entries": [
                {"id": "skills", "path": ".agents/skills", "source": "skills", "format": "link"},
                {"id": "roles", "path": ".agents/agents", "source": "agents", "format": "link"},
                {"id": "codex", "path": ".codex/agents", "source": "agents", "format": "codex-toml"},
                {"id": "commands", "path": "commands", "source": "stages", "format": "plugin-command"},
            ],
            "hosts": [{"id": "kimi-code", "label": "Kimi Code", "instructions": "AGENTS.md", "entries": ["skills", "roles", "codex", "commands"]}],
        }
        write(self.root / "workflow/hosts.json", json.dumps(hosts))

    def tearDown(self):
        self.temp.cleanup()

    def test_sync_generates_every_declared_entry(self):
        HOSTS.sync(self.root)
        self.assertEqual(HOSTS.entry_problems(self.root), [])
        self.assertEqual(os.readlink(self.root / ".agents/skills/vsc"), "../../skills/vsc")
        self.assertEqual(os.readlink(self.root / ".agents/agents/director.md"), "../../agents/director.md")
        command = (self.root / "commands/vsc-adapt.md").read_text("utf-8")
        self.assertIn("skills: vsc-adapt", command)
        self.assertIn("**mode: adapt**", command)
        toml = (self.root / ".codex/agents/director.toml").read_text("utf-8")
        self.assertIn("镜头服务叙事。", toml)
        if tomllib:
            data = tomllib.loads(toml)
            self.assertEqual((data["name"], data["description"]), ("director", "Plan shots."))

    def test_check_reports_drift_and_sync_repairs_it(self):
        HOSTS.sync(self.root)
        (self.root / ".agents/skills/vsc").unlink()
        write(self.root / ".codex/agents/director.toml", "name = \"director\"\n")
        os.symlink("../../skills/retired", self.root / ".agents/skills/retired")
        problems = HOSTS.entry_problems(self.root)
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("缺少入口" in problem for problem in problems))
        self.assertTrue(any("不一致" in problem for problem in problems))
        self.assertTrue(any("多余的入口" in problem for problem in problems))
        HOSTS.sync(self.root)
        self.assertEqual(HOSTS.entry_problems(self.root), [])

    def test_new_source_requires_sync(self):
        HOSTS.sync(self.root)
        write(self.root / "skills/vsc-sound/SKILL.md", "---\nname: vsc-sound\ndescription: test\n---\n")
        self.assertEqual(HOSTS.entry_problems(self.root), ["缺少入口：.agents/skills/vsc-sound"])

    def test_sync_refuses_to_delete_a_real_directory(self):
        HOSTS.sync(self.root)
        (self.root / ".agents/skills/personal").mkdir()
        with self.assertRaises(HOSTS.HostError):
            HOSTS.sync(self.root)
        self.assertTrue((self.root / ".agents/skills/personal").is_dir())

    def test_invalid_declaration_is_reported(self):
        hosts = json.loads((self.root / "workflow/hosts.json").read_text("utf-8"))
        hosts["hosts"][0]["entries"].append("missing")
        write(self.root / "workflow/hosts.json", json.dumps(hosts))
        self.assertIn("未声明的入口", HOSTS.entry_problems(self.root)[0])

    def test_repository_entries_match_sources(self):
        self.assertEqual(HOSTS.entry_problems(ROOT), [])


if __name__ == "__main__":
    unittest.main()
