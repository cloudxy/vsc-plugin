"""Consumer checks for pinned public teaching, independent of projects/providers."""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT, SCRIPTS


class CraftTeachingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-craft-teaching-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "workflow 安装"
        (self.root / "workflow").mkdir(parents=True)
        (self.root / "workflow/kernel.json").write_text("{}", "utf-8")
        (self.root / ".zcode-plugin").mkdir()
        (self.root / ".zcode-plugin/plugin.json").write_text('{"version":"test-1"}', "utf-8")
        self.relative = "skills/vsc-script/references/fixture.md"
        self.teaching_file = self.root / self.relative
        self.teaching_file.parent.mkdir(parents=True)
        self.section = ('## 教学单元 <a id="chapter"></a>\n\n'
                        '条件：固定原事实。\n\n### 案例\n原稿→修改稿。\n\n'
                        '### 反例及回退\n必要旁白应保留。  \n\n')
        self.document = "# 教材\n前言不检索。\n\n" + self.section + "## 其他单元\n外部内容。\n"
        self.teaching_file.write_text(self.document, "utf-8")
        self.catalog_file = self.root / "knowledge/craft.json"
        self.catalog_file.parent.mkdir()
        self.data = {"format": "vsc.craft-catalog/v1", "sources": [
            {"id": sid, "title": sid, "publisher": "原创说明", "checked_at": "2026-10-19",
             "url": "https://example.org/" + sid} for sid in ("z", "a", "unused")], "cards": [
            {"id": "method", "name": "教学方法", "category": "script", "principle": "固定事实，比较行动。",
             "source_basis": "原创解释", "tags": ["行动", "比较"], "stages": ["script"],
             "steps": ["固定目标", "比较修改"], "pitfalls": ["不可漏事实"], "sources": ["z", "a"],
             "teaching_ref": {"path": self.relative, "anchor": "chapter"}},
            {"id": "legacy", "name": "旧方法", "category": "script", "principle": "原方法原行为。",
             "source_basis": "原创说明", "tags": ["旧卡"], "stages": ["script"],
             "steps": ["观察"], "pitfalls": ["不武断"], "sources": ["z"]}]}
        self.save()

    def save(self, data=None):
        self.catalog_file.write_text(json.dumps(self.data if data is None else data, ensure_ascii=False), "utf-8")

    def cli(self, *args, root=None, success=True):
        environment = os.environ.copy()
        environment["VSC_WORKFLOW_ROOT"] = str(root or self.root)
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "knowledge/craft.py"), *map(str, args)],
                                env=environment, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        if not success:
            self.assertEqual(result.stdout, "", "失败不应先输出卡或教学正文")
            self.assertIn("ERROR:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        return result

    def show(self, method="method", *flags, root=None):
        return json.loads(self.cli("show", method, *flags, root=root).stdout)

    def expected_digest(self, card, teaching):
        payload = {"format": "vsc.craft-teaching-digest/v1", "method_id": card["id"], "card": card,
                   "source_details": sorted([s for s in self.data["sources"] if s["id"] in card["sources"]],
                                            key=lambda s: s["id"]), "teaching": teaching}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def test_cli_retains_basic_show_search_and_legacy_cards(self):
        self.assertIn("VALID: 2 条方法", self.cli("validate").stdout)
        for card in self.data["cards"]:
            expected = {**card, "source_details": [s for s in self.data["sources"] if s["id"] in card["sources"]]}
            self.assertEqual(self.show(card["id"]), expected)
        result = self.show("legacy", "--with-teaching")
        self.assertIsNone(result["teaching"])
        self.assertEqual(result["teaching_chars"], 0)
        self.assertEqual(result["teaching_sha256"], self.expected_digest(self.data["cards"][1], None))
        self.assertEqual(self.show("legacy", "--expected-sha", result["teaching_sha256"]), result)
        self.assertIn("method [script]", self.cli("search", "教学方法", "--stage", "script", "--limit", "1").stdout)
        self.assertEqual(self.cli("search", "仅在教材正文中的独特词语").stdout, "没有匹配的方法\n")
        self.cli("show", "missing-method", "--with-teaching", success=False)

    def test_full_section_and_canonical_digest_are_pinned_before_stdout(self):
        result = self.show("method", "--with-teaching")
        self.assertEqual(result["teaching"], {"path": self.relative, "anchor": "chapter", "body": self.section})
        self.assertEqual(result["teaching_sha256"], self.expected_digest(self.data["cards"][0], result["teaching"]))
        self.assertEqual(result["teaching_chars"], len(self.section))
        self.assertEqual(result["release_version"], "test-1")
        self.assertFalse(result["teaching_over_soft_target"])
        self.assertEqual(self.show("method", "--expected-sha", result["teaching_sha256"]), result)
        self.assertIn("重建固定输入/context", self.cli("show", "method", "--expected-sha", "0" * 64,
                                                  success=False).stderr)
        self.cli("show", "method", "--expected-sha", "", success=False)

    def test_digest_is_lf_normalized_and_independent_of_root_release_and_source_order(self):
        initial = self.show("method", "--with-teaching")
        for newline in ("\r\n", "\r"):
            with self.subTest(newline=repr(newline)):
                self.teaching_file.write_bytes(self.document.replace("\n", newline).encode("utf-8"))
                self.assertEqual(self.show("method", "--expected-sha", initial["teaching_sha256"])["teaching"], initial["teaching"])
        self.data["sources"].reverse()
        next(s for s in self.data["sources"] if s["id"] == "unused")["title"] = "无关来源改变"
        self.data["cards"][1]["principle"] = "另一个方法改变，不影响选中方法。"
        self.save()
        self.teaching_file.write_text(self.document.replace("外部内容。", "完整章节以外的改动。"), "utf-8")
        relocated = self.base / "another installation"
        shutil.copytree(self.root, relocated)
        (relocated / ".zcode-plugin/plugin.json").write_text('{"version":"test-2"}', "utf-8")
        actual = self.show("method", "--expected-sha", initial["teaching_sha256"], root=relocated)
        self.assertEqual(actual["teaching_sha256"], initial["teaching_sha256"])
        self.assertEqual(actual["teaching"], initial["teaching"])
        self.assertEqual(actual["release_version"], "test-2")
        self.assertNotIn(str(self.root), json.dumps(actual))
        self.cli("show", "legacy", "--expected-sha", initial["teaching_sha256"], success=False)

    def test_changed_card_source_or_section_invalidates_pinned_input(self):
        initial = self.show("method", "--with-teaching")["teaching_sha256"]
        mutations = (lambda data: data["cards"][0].update(principle="同方法的新解释"),
                     lambda data: data["sources"][0].update(title="已引用来源修订"),
                     lambda data: data["cards"][0]["tags"].reverse(),
                     lambda data: data["cards"][0].update(extra_note="完整卡字段也受摘要保护"))
        for mutation in mutations:
            data = copy.deepcopy(self.data)
            mutation(data)
            self.save(data)
            self.cli("show", "method", "--expected-sha", initial, success=False)
        self.save()
        self.teaching_file.write_text(self.document.replace("必要旁白应保留。", "必要旁白须在此目标下保留。"), "utf-8")
        self.cli("show", "method", "--expected-sha", initial, success=False)
        self.assertNotEqual(self.show("method", "--with-teaching")["teaching_sha256"], initial)

    def test_fenced_headings_and_anchors_do_not_split_or_duplicate_the_section(self):
        for opener, closer in (("```markdown", "```"), ("~~~~", "~~~~~"), ("````markdown", "````")):
            with self.subTest(opener=opener):
                block = opener + '\n## 伪标题 <a id="chapter"></a>\n' + "```\n代码\n" + closer + "\n"
                # With a three-backtick opener the first ``` closes it; omit that inner line.
                if opener == "```markdown":
                    block = block.replace("```\n代码\n", "代码\n", 1)
                expected = ('  ## 教学 <a id=\'chapter\'></a>\n条件。\n' + block
                            + "### 子节\n反例。\n#### 更深\n回退。\n\n")
                self.teaching_file.write_text("# 上级\n" + expected + "# 后一单元\n不可泄漏。\n", "utf-8")
                self.assertEqual(self.show("method", "--with-teaching")["teaching"]["body"], expected)

    def test_invalid_or_missing_anchor_is_an_explicit_cli_failure(self):
        cases = {"missing": "## 没有锚点\n正文。\n",
                 "duplicate": self.section + self.section,
                 "unattached": '<a id="chapter"></a>\n## 标题\n正文。\n',
                 "heading-without-space": '##标题 <a id="chapter"></a>\n正文。\n',
                 "setext": '标题 <a id="chapter"></a>\n---\n正文。\n',
                 "empty": '## 标题 <a id="chapter"></a>\n\n## 后文\n正文。\n',
                 "fenced-only": '```\n## 标题 <a id="chapter"></a>\n正文。\n```\n',
                 "duplicate-unattached": self.section + '<a id="chapter"></a>\n'}
        for label, document in cases.items():
            with self.subTest(label=label):
                self.teaching_file.write_text(document, "utf-8")
                self.cli("validate", success=False)
                self.cli("show", "method", "--with-teaching", success=False)
        self.teaching_file.write_bytes(b"\xff\xfeinvalid utf8")
        self.cli("validate", success=False)

    def test_invalid_reference_types_paths_and_files_fail_without_traceback(self):
        refs = [None, [], "fixture", {}, {"path": self.relative}, {"path": self.relative, "anchor": 1},
                {"path": 1, "anchor": "chapter"}, {"path": self.relative, "anchor": "中文"},
                {"path": self.relative, "anchor": ""}, {"path": self.relative, "anchor": "has space"},
                {"path": self.relative, "anchor": "chapter", "extra": True}]
        bad_paths = (str(self.teaching_file), "../outside.md", "https://example.org/lesson.md",
                     "skills/vsc-script/references/../fixture.md", "skills/./references/fixture.md",
                     "skills//vsc-script/references/fixture.md", "skills/vsc-script/references/fixture.txt",
                     "skills/vsc-script/fixture.md", "knowledge/fixture.md", "C:/fixture.md",
                     "skills\\vsc-script\\references\\fixture.md", "skills/vsc-script/references/missing.md",
                     "skills/vsc-script/references/\x00.md", "skills/vsc-script/references/directory.md")
        (self.teaching_file.parent / "directory.md").mkdir()
        refs.extend({"path": path, "anchor": "chapter"} for path in bad_paths)
        for ref in refs:
            with self.subTest(ref=ref):
                data = copy.deepcopy(self.data)
                data["cards"][0]["teaching_ref"] = ref
                self.save(data)
                self.cli("validate", success=False)

    def test_symlinks_cannot_escape_root_or_allowed_reference_directory(self):
        outside = self.base / "outside.md"
        outside.write_text(self.section, "utf-8")
        inside = self.root / "knowledge/inside.md"
        inside.write_text(self.section, "utf-8")
        for name, destination in (("outside-link.md", outside), ("inside-wrong-dir.md", inside),
                                  ("dangling.md", self.base / "missing.md")):
            with self.subTest(name=name):
                link = self.teaching_file.parent / name
                link.symlink_to(destination)
                data = copy.deepcopy(self.data)
                data["cards"][0]["teaching_ref"]["path"] = str(link.relative_to(self.root))
                self.save(data)
                self.cli("validate", success=False)
        safe = self.teaching_file.parent / "safe-link.md"
        safe.symlink_to(self.teaching_file)
        self.data["cards"][0]["teaching_ref"]["path"] = str(safe.relative_to(self.root))
        self.save()
        self.assertEqual(self.show("method", "--with-teaching")["teaching"]["body"], self.section)

    def test_soft_target_reports_complete_body_and_teaching_is_not_search_content(self):
        expected = self.section + "仅供教材检索隔离探针" + "字" * 1700 + "\n\n"
        self.teaching_file.write_text(expected + "## 后文\n不能拼入。\n", "utf-8")
        result = self.show("method", "--with-teaching")
        self.assertEqual(result["teaching"]["body"], expected)
        self.assertEqual(result["teaching_chars"], len(expected))
        self.assertEqual(result["teaching_soft_target_chars"], 1600)
        self.assertTrue(result["teaching_over_soft_target"])
        self.assertEqual(self.cli("search", "仅供教材检索隔离探针").stdout, "没有匹配的方法\n")
        self.assertEqual(self.show("method", "--expected-sha", result["teaching_sha256"])["teaching"]["body"], expected)

    def test_all_34_original_cards_still_validate_and_show_without_teaching(self):
        data = json.loads((ROOT / "knowledge/craft.json").read_text("utf-8"))
        self.assertGreaterEqual(len(data["cards"]), 34)
        # Recreate the pre-extension catalog independently of live teaching edits.
        for card in data["cards"]:
            card.pop("teaching_ref", None)
        self.save(data)
        self.cli("validate")
        for card in data["cards"]:
            with self.subTest(method=card["id"]):
                expected = {**card, "source_details": [s for s in data["sources"] if s["id"] in card["sources"]]}
                self.assertEqual(self.show(card["id"]), expected)


if __name__ == "__main__":
    unittest.main()
