#!/usr/bin/env python3
"""原生制作规格包离线验证：python3 tests/test_vsc_recipes.py。"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT
import vsc_library as L
import vsc_recipes as R


class RecipeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "素材 库"
        self.data = R.load()

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = R.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def catalog(self, data, name="规格 包.json"):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        return str(path)

    def install(self, *args):
        return self.cli("install", *args, "--library", str(self.library))

    def test_taxonomy_coverage_and_production_boundaries(self):
        self.assertEqual(R.errors(self.data), [])
        self.assertEqual({x["kind"] for x in self.data["recipes"]}, set(L.taxonomy()[0]))
        self.assertGreaterEqual(len(self.data["recipes"]), 20)
        craft_ids = {x["id"] for x in json.loads((ROOT / "knowledge/craft.json").read_text("utf-8"))["cards"]}
        for recipe in self.data["recipes"]:
            self.assertEqual(recipe["rights"]["status"], "owned")
            self.assertEqual(recipe["rights"]["scope"], "specification_only")
            self.assertIn("acceptance", recipe["spec"])
            self.assertTrue(set(recipe.get("craft_refs", [])) <= craft_ids)
            self.assertNotIn("craft_refs", recipe["spec"])
            if recipe["kind"] in ("motion", "fight"):
                for key in ("safety", "entry_state", "exit_state", "camera", "duration", "beats"):
                    self.assertTrue(recipe["spec"][key])
            if recipe["kind"] == "voice":
                self.assertIsNone(recipe["spec"]["speaker_binding"]["voice_id"])
                self.assertTrue(recipe["spec"]["speaker_binding"]["lock_after_selection"])
        self.assertEqual(self.cli("validate")[0], 0)

    def test_schema_rejects_malformed_catalogs_without_traceback(self):
        cases = [[], {"format": R.FORMAT, "version": "1.0.0", "recipes": []}]
        for field, value in (("id", "../../escape"), ("kind", []), ("version", 1), ("rights", "owned"),
                             ("spec", []), ("tags", [None]), ("craft_refs", [{}])):
            data = copy.deepcopy(self.data)
            data["recipes"][0][field] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data_type=type(data).__name__):
                self.assertTrue(R.errors(data))
                code, _, err = self.cli("validate", self.catalog(data))
                self.assertEqual(code, 1)
                self.assertIn("ERROR:", err)
        duplicate = copy.deepcopy(self.data)
        duplicate["recipes"].append(duplicate["recipes"][0])
        self.assertTrue(any("唯一" in x for x in R.errors(duplicate)))
        missing = copy.deepcopy(self.data)
        missing["recipes"] = missing["recipes"][:-1]
        self.assertTrue(any("缺少分类" in x for x in R.errors(missing)))

    def test_required_specialized_contracts_and_voice_placeholder(self):
        for kind, key in (("fight", "safety"), ("motion", "entry_state"), ("music", "loop"),
                          ("ambience", "dialogue_space"), ("sfx", "rights_gate"), ("voice", "speaker_binding")):
            data = copy.deepcopy(self.data)
            recipe = next(x for x in data["recipes"] if x["kind"] == kind)
            del recipe["spec"][key]
            self.assertTrue(R.errors(data), (kind, key))
        voice = copy.deepcopy(self.data)
        next(x for x in voice["recipes"] if x["kind"] == "voice")["spec"]["speaker_binding"]["voice_id"] = "made-up-voice"
        self.assertTrue(R.errors(voice))
        invalid_safety = copy.deepcopy(self.data)
        next(x for x in invalid_safety["recipes"] if x["kind"] == "fight")["spec"]["safety"] = 7
        self.assertTrue(R.errors(invalid_safety))

    def test_search_list_show_and_invalid_filter(self):
        code, out, err = self.cli("search", "打斗", "--kind", "fight", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual([x["kind"] for x in json.loads(out)], ["fight"])
        code, out, _ = self.cli("search", "纸张", "--kind", "sfx")
        self.assertEqual(code, 0)
        self.assertIn("AR-sfx-soft-paper", out)
        self.assertIn("没有匹配", self.cli("search", "不存在的无关关键词")[1])
        self.assertEqual(len(json.loads(self.cli("list", "--json")[1])), len(self.data["recipes"]))
        rid = self.data["recipes"][0]["id"]
        self.assertEqual(json.loads(self.cli("show", rid)[1])["id"], rid)
        self.assertEqual(self.cli("show", "../../escape")[0], 1)
        self.assertEqual(self.cli("list", "--kind", "unknown")[0], 1)
        self.assertEqual(self.cli("search", "--limit", "0")[0], 1)

    def test_install_calls_library_api_and_is_idempotent(self):
        rid = self.data["recipes"][0]["id"]
        with mock.patch.object(L, "add", wraps=L.add) as add:
            self.assertEqual(self.install(rid)[0], 0)
            self.assertEqual(add.call_count, 1)
            path, item = L.find(self.library, rid)
            original = (path / "item.json").read_bytes()
            code, out, err = self.install(rid)
            self.assertEqual(code, 0, err)
            self.assertIn("UNCHANGED:", out)
            self.assertEqual(add.call_count, 1, "相同规格不可重复调用创建")
            self.assertEqual((path / "item.json").read_bytes(), original)
        self.assertEqual(item["attributes"]["asset_type"], "specification")
        self.assertFalse(item["attributes"]["is_media"])
        self.assertTrue(item["attributes"]["requires_human_selection"])
        self.assertEqual(item["files"], [])
        self.assertEqual(item["provider_refs"], [])
        self.assertEqual(L.item_errors(item, *L.taxonomy()), [])

    def test_all_install_and_library_check(self):
        code, out, err = self.install("--all")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("INSTALLED:"), len(self.data["recipes"]))
        self.assertEqual(len(L.load_items(self.library)), len(self.data["recipes"]))
        code, out, err = self.install("--all")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("UNCHANGED:"), len(self.data["recipes"]))
        self.assertEqual(L.check(type("Args", (), {"library": str(self.library)})())[1], [])

    def test_version_or_content_conflict_never_overwrites(self):
        recipe = self.data["recipes"][0]
        self.install(recipe["id"])
        folder, _ = L.find(self.library, recipe["id"])
        before = (folder / "item.json").read_bytes()
        for key, value in (("version", "2.0.0"), ("summary", "已修改规格")):
            data = copy.deepcopy(self.data)
            data["recipes"][0][key] = value
            code, _, err = self.cli("--catalog", self.catalog(data), "install", recipe["id"], "--library", str(self.library))
            self.assertEqual(code, 1)
            self.assertIn("版本冲突或不同内容", err)
            self.assertEqual((folder / "item.json").read_bytes(), before)
        # 即使 digest 未改，本机编辑规格也不能被重复安装覆盖。
        item = json.loads(before)
        item["attributes"]["spec"]["fixed"][0] = "本机编辑"
        (folder / "item.json").write_text(json.dumps(item), "utf-8")
        self.assertEqual(self.install(recipe["id"])[0], 1)

    def test_all_preflights_conflict_before_creating_any_recipe(self):
        last = self.data["recipes"][-1]
        self.install(last["id"])
        data = copy.deepcopy(self.data)
        data["recipes"][-1]["version"] = "2.0.0"
        code, _, _ = self.cli("--catalog", self.catalog(data), "install", "--all", "--library", str(self.library))
        self.assertEqual(code, 1)
        self.assertEqual(len(L.load_items(self.library)), 1)

    def test_input_paths_missing_invalid_and_spaced(self):
        self.assertEqual(self.cli("--catalog", self.catalog(self.data), "list")[0], 0)
        self.assertEqual(self.cli("validate", str(self.root / "missing.json"))[0], 1)
        path = self.root / "broken.json"
        path.write_text("{bad", "utf-8")
        self.assertEqual(self.cli("--catalog", str(path), "install", "--all", "--library", str(self.library))[0], 1)
        self.assertFalse(self.library.exists())
        data = copy.deepcopy(self.data)
        data["recipes"][0]["id"] = "../outside"
        self.assertEqual(self.cli("--catalog", self.catalog(data), "install", "--all", "--library", str(self.library))[0], 1)
        self.assertFalse(self.library.exists())

    def test_install_refuses_symlink_escape_and_unindexed_directory(self):
        recipe = self.data["recipes"][0]
        outside = self.root / "outside"
        outside.mkdir()
        self.library.mkdir()
        (self.library / recipe["kind"]).symlink_to(outside, target_is_directory=True)
        code, _, err = self.install(recipe["id"])
        self.assertEqual(code, 1)
        self.assertIn("符号链接", err)
        self.assertEqual(list(outside.iterdir()), [])
        (self.library / recipe["kind"]).unlink()
        target = self.library / recipe["kind"] / recipe["id"]
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("keep", "utf-8")
        self.assertEqual(self.install(recipe["id"])[0], 1)
        self.assertEqual((target / "keep.txt").read_text("utf-8"), "keep")

    def test_malformed_existing_library_is_reported_without_creation(self):
        folder = self.library / "prop" / "broken"
        folder.mkdir(parents=True)
        (folder / "item.json").write_text(json.dumps({"id": {"bad": True}}), "utf-8")
        code, _, err = self.install("--all")
        self.assertEqual(code, 1)
        self.assertIn("条目无效", err)
        self.assertEqual(len(L.load_items(self.library)), 1)


if __name__ == "__main__":
    unittest.main()
