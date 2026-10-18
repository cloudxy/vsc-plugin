#!/usr/bin/env python3
"""scripts/kernel/hosts.py 自测。运行：python3 -B tests/run.py --test kernel.integration.test_vsc_hosts"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from support.paths import ROOT
import vsc.kernel.hosts as HOSTS

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
        cards = json.loads((ROOT / "workflow/roles.json").read_text("utf-8"))
        cards["roles"] = [card for card in cards["roles"] if card["id"] == "director"]
        write(self.root / "workflow/roles.json", json.dumps(cards, ensure_ascii=False))
        stage = {"id": "adapt", "command": "vsc-adapt", "skill": "vsc-adapt",
                 "entry": {"mode": "adapt", "description": "VSC 改编", "argument_hint": "[第N集]"}}
        write(self.root / "workflow/kernel.json", json.dumps({"format": "vsc.workflow-kernel/v1", "stages": [stage]}, ensure_ascii=False))
        hosts = {
            "format": "vsc.hosts/v1",
            "entries": [
                {"id": "skills", "path": ".agents/skills", "source": "skills", "format": "link"},
                {"id": "roles", "path": ".agents/agents", "source": "agents", "format": "role-markdown"},
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
        self.assertFalse((self.root / ".agents/agents/director.md").is_symlink())
        self.assertIn("role_sha256=", (self.root / ".agents/agents/director.md").read_text("utf-8"))
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

    def test_markdown_and_codex_compile_identical_card_and_report_drift(self):
        hosts = json.loads((self.root / "workflow/hosts.json").read_text())
        hosts["entries"][1]["format"] = "role-markdown"
        write(self.root / "workflow/hosts.json", json.dumps(hosts))
        HOSTS.sync(self.root)
        markdown = (self.root / ".agents/agents/director.md").read_text()
        toml = (self.root / ".codex/agents/director.toml").read_text()
        for value in ("视觉叙事明确", "human_approval", "memory_proposals", "role_sha256="):
            self.assertIn(value, markdown)
            self.assertIn(value, toml)
        cards = json.loads((self.root / "workflow/roles.json").read_text())
        cards["roles"][0]["temperament"] = "证据与节奏兼顾"
        write(self.root / "workflow/roles.json", json.dumps(cards))
        self.assertEqual(len(HOSTS.entry_problems(self.root)), 2)
        HOSTS.sync(self.root)
        self.assertIn("证据与节奏兼顾", (self.root / ".agents/agents/director.md").read_text())

    def test_generated_links_keep_source_targets_at_each_declared_location(self):
        source = self.root / "agents/director.md"
        body = source.read_text() + '''
[Card](../workflow/roles.json#roles)
[Guide](../docs/guide.md?view=full#details "Guide title")
![Image](../docs/image(1).png)
[Spaced](<../docs/with space.md#part> "Spaced title")
[Encoded](../docs/with%20space.md)
[Reference][role-card]
[role-card]: ../workflow/roles.json#roles "Reference title"
[Local](#director)
[Remote](https://example.com/docs/guide.md#part)
`[Example](../not-a-document.md)`
```markdown
[Example](../not-a-document.md)
```
'''
        write(source, body)
        for name in ("guide.md", "with space.md", "image(1).png"):
            write(self.root / "docs" / name, "fixture")
        declaration = json.loads((self.root / "workflow/hosts.json").read_text())
        declaration["entries"][1]["path"] = "runtime/nested/roles"
        declaration["entries"][2]["path"] = "runtime/codex"
        write(self.root / "workflow/hosts.json", json.dumps(declaration))
        HOSTS.sync(self.root)
        for relative in ("runtime/nested/roles/director.md", "runtime/codex/director.toml"):
            generated = self.root / relative
            content = generated.read_text()
            if generated.suffix == ".toml" and tomllib:
                content = tomllib.loads(content)["developer_instructions"]
            targets = {name: Path(os.path.relpath(self.root / name, generated.parent)).as_posix()
                       for name in ("workflow/roles.json", "docs/guide.md", "docs/image(1).png", "docs/with space.md")}
            self.assertIn(f'[Card]({targets["workflow/roles.json"]}#roles)', content)
            self.assertIn(f'[Guide]({targets["docs/guide.md"]}?view=full#details "Guide title")', content)
            self.assertIn(f'![Image]({targets["docs/image(1).png"]})', content)
            self.assertIn(f'[Spaced](<{targets["docs/with space.md"]}#part> "Spaced title")', content)
            encoded = targets["docs/with space.md"].replace(" ", "%20")
            self.assertIn(f'[Encoded]({encoded})', content)
            self.assertIn(f'[role-card]: {targets["workflow/roles.json"]}#roles "Reference title"', content)
            for target in [*targets.values(), encoded]:
                self.assertTrue((generated.parent / unquote(urlsplit(target).path)).is_file(), (relative, target))
            self.assertIn('[Local](#director)', content)
            self.assertIn('[Remote](https://example.com/docs/guide.md#part)', content)
            self.assertIn('`[Example](../not-a-document.md)`', content)
            self.assertIn('```markdown\n[Example](../not-a-document.md)\n```', content)
        self.assertEqual(source.read_text(), body)

    def test_repository_markdown_and_toml_consumers_resolve_all_document_links(self):
        checked = 0
        for relative, (kind, _) in HOSTS.expected(ROOT)[1].items():
            if kind != "file" or not relative.endswith((".md", ".toml")) or relative.startswith("commands/"):
                continue
            generated = ROOT / relative
            content = generated.read_text("utf-8")
            if generated.suffix == ".toml" and tomllib:
                content = tomllib.loads(content)["developer_instructions"]
            for target in re.findall(r"\]\(([^)\s]+)", content):
                url = urlsplit(target)
                if not url.scheme and url.path:
                    self.assertTrue((generated.parent / unquote(url.path)).exists(), (relative, target))
                    checked += 1
        self.assertGreaterEqual(checked, 36)


if __name__ == "__main__":
    unittest.main()
