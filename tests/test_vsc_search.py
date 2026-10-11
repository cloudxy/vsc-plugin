#!/usr/bin/env python3
"""检索公开方法、项目产物和本机素材；无网络、不持久化第二份索引。"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
import vsc_craft as C
import vsc_search as S


class CraftTest(unittest.TestCase):
    def test_catalog_sources_and_topics(self):
        data = C.load()
        self.assertGreaterEqual(len(data["cards"]), 20)
        self.assertTrue({"运镜", "构图", "表演", "对白", "动作", "特效", "声音", "叙事", "剪辑"} <= {c["category"] for c in data["cards"]})
        self.assertIn("eyeline-match", [card["id"] for _, card in S.rank(data["cards"], "视线", C.fields)])
        broken = copy.deepcopy(data)
        broken["cards"][0]["sources"] = ["missing"]
        self.assertTrue(any("未知来源" in x for x in C.errors(broken)))
        broken = copy.deepcopy(data)
        broken["cards"].append(broken["cards"][0])
        self.assertTrue(any("唯一" in x for x in C.errors(broken)))

    def test_show_includes_primary_sources(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(C.main(["show", "axis-map"]), 0)
        card = json.loads(out.getvalue())
        self.assertEqual(card["source_details"][0]["publisher"], "Columbia University")


class ProjectSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "p", "profile_id": "narrative-video",
            "objects": [{"id": "SH-01", "kind": "shot", "parent": "SC-01"}],
            "artifacts": [{"id": "A-01", "type": "vsc.screenplay", "scope": "EP-01", "stage": "script", "status": "draft", "depends_on": ["A-00"]}]}), "utf-8")
        (self.project / "03-剧本").mkdir()
        self.script = self.project / "03-剧本/场次.md"
        self.script.write_text("人物看向门口，手中紧握信封。", "utf-8")
        (self.project / "01-来源").mkdir()
        (self.project / "01-来源/原文.txt").write_text("秘密原文不应默认扫描", "utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_project_file_and_artifact_lookup(self):
        items = S.entries("projects", project=self.project)
        found = S.rank(items, "信封", S.entry_fields)
        self.assertEqual(Path(found[0][1]["path"]), self.script.resolve())
        artifact = S.rank(items, "A-01", S.entry_fields)[0][1]
        self.assertIn("draft", artifact["summary"])
        self.assertIn("A-00", artifact["summary"])
        self.assertFalse(S.rank(items, "秘密原文", S.entry_fields))
        self.script.write_text("修改后为雨夜街市", "utf-8")
        self.assertFalse(S.rank(S.entries("projects", project=self.project), "信封", S.entry_fields))
        self.assertFalse((self.project / "search-index.json").exists())

    def test_symlink_outside_project_is_excluded(self):
        outside = Path(self.temp.name) / "private.txt"
        outside.write_text("外部文件内容", "utf-8")
        (self.project / "03-剧本/link.txt").symlink_to(outside)
        self.assertFalse(S.rank(S.project_entries(self.project), "外部文件", S.entry_fields))

    def test_cli_returns_usable_paths_and_snippets(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = S.main(["信封", "--in", "projects", "--project", str(self.project), "--json"])
        self.assertEqual(code, 0)
        item = json.loads(out.getvalue())[0]
        self.assertEqual(item["path"], str(self.script.resolve()))
        self.assertIn("信封", item["snippet"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(S.main(["--limit", "0"]), 1)


if __name__ == "__main__":
    unittest.main()
