#!/usr/bin/env python3
"""vsc_library.py 与 vsc_search.py 自测：临时素材库与作品，不联网。运行：python3 tests/test_vsc_library.py"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
import consistency as C
import vsc_library as L
import vsc_search as S

BIBLE = json.loads((ROOT / "templates/asset-bible.json").read_text("utf-8"))
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 32


class SearchTest(unittest.TestCase):
    def test_whole_terms_and_bigram_overlap(self):
        self.assertEqual(S.hit("古寺", "秋日古寺庭院"), 1.0)
        self.assertGreater(S.hit("古寺钟声", "古寺庭院远处钟声"), 0)
        self.assertEqual(S.hit("雨", "晴天"), 0.0)
        self.assertEqual(S.score(S.terms("古寺 雨夜"), [(1, "古寺庭院")]), 0.0)
        found = S.rank(["雨夜街道", "古寺庭院", "古寺雨夜"], "古寺 雨夜", lambda item: [(1, item)])
        self.assertEqual([item for _, item in found], ["古寺雨夜"])


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.library, self.project = root / "library", root / "project"
        self.project.mkdir()
        (self.project / "vsc.json").write_text(json.dumps({"project_id": BIBLE["project_id"]}), "utf-8")
        self.bible = self.project / "资产库.json"
        self.bible.write_text(json.dumps(BIBLE, ensure_ascii=False), "utf-8")
        self.image = root / "老僧.png"
        self.image.write_bytes(PNG)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = L.main(["--library", str(self.library), *argv])
        return code, out.getvalue(), err.getvalue()

    def add_monk(self, rights="generated", commercial=None):
        argv = ["add", "--kind", "character", "--id", "老僧-01", "--name", "老年僧人", "--summary", "六十余岁老僧，赭褐僧袍，左手念珠",
                "--tag", "僧人", "--tag", "古装", "--rights", rights, "--license", "火山方舟服务条款",
                "--attr", 'identity=["年长僧人","光头","白须"]', "--file", f"{self.image}:portrait"]
        return self.cli(*argv, *(["--commercial", commercial] if commercial else []))

    def test_add_search_and_check(self):
        self.assertEqual(self.add_monk()[0], 0)
        code, out, _ = self.cli("search", "老僧", "古装")
        self.assertIn("老僧-01", out)
        self.assertIn("没有匹配", self.cli("search", "雨夜")[1])
        self.assertIn("没有匹配", self.cli("search", "老僧", "--commercial")[1])
        self.assertEqual(self.cli("check")[0], 0)
        self.assertNotEqual(self.add_monk()[0], 0, "同一 ID 不能重复创建")
        (self.library / "character/老僧-01/老僧.png").write_bytes(b"changed")
        code, _, err = self.cli("check")
        self.assertEqual(code, 1)
        self.assertIn("SHA-256 不一致", err)

    def test_use_copies_files_and_creates_a_bible_entity(self):
        self.add_monk()
        code, out, err = self.cli("use", "老僧-01", "--project", str(self.project), "--bible", str(self.bible), "--entity", "CH-elder-01")
        self.assertEqual(code, 0, err)
        self.assertIn("尚未确认可商用", err)
        copied = self.project / out.strip()
        self.assertTrue(copied.is_file())
        bible = json.loads(self.bible.read_text("utf-8"))
        entity = C.entity_index(bible)["CH-elder-01"]
        self.assertEqual((entity["kind"], entity["identity"], entity["references"][0]["library"]), ("character", ["年长僧人", "光头", "白须"], "老僧-01"))
        self.assertEqual(C.bible_errors(bible), [])
        self.assertFalse([problem for problem in C.media_problems(bible, self.project) if problem.startswith("CH-elder-01")])
        item = json.loads((self.library / "character/老僧-01/item.json").read_text("utf-8"))
        self.assertEqual([entry["project_id"] for entry in item["used_by"]], [BIBLE["project_id"]])
        self.cli("use", "老僧-01", "--project", str(self.project), "--bible", str(self.bible), "--entity", "CH-elder-01")
        bible = json.loads(self.bible.read_text("utf-8"))
        self.assertEqual(len(C.entity_index(bible)["CH-elder-01"]["references"]), 1, "重复使用不重复登记")

    def test_unverified_rights_are_refused(self):
        self.add_monk(rights="unknown")
        code, _, err = self.cli("use", "老僧-01", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("授权未核验", err)

    def test_voice_binds_to_the_character(self):
        speaker = BIBLE["entities"][0]["id"]
        self.cli("add", "--kind", "voice", "--id", "沉稳男声", "--name", "沉稳中低音男声", "--summary", "成熟男性温暖沉稳",
                 "--rights", "temp_only", "--attr", "engine=edge-tts", "--attr", "voice=zh-CN-YunjianNeural", "--attr", "rights=temp_only")
        code, _, err = self.cli("use", "沉稳男声", "--project", str(self.project), "--bible", str(self.bible), "--entity", speaker)
        self.assertEqual(code, 0, err)
        self.assertIn("仅限预演", err)
        voice = C.entity_index(json.loads(self.bible.read_text("utf-8")))[speaker]["voice"]
        self.assertEqual((voice["voice"], voice["library"]), ("zh-CN-YunjianNeural", "沉稳男声"))

    def test_promote_brings_provenance_from_the_record(self):
        target = self.project / "06-素材/资产/定妆.png"
        target.parent.mkdir(parents=True)
        shutil.copy2(self.image, target)
        record = {"format": C.RECORD_FORMAT, "project_id": BIBLE["project_id"], "kind": "image", "purpose": "asset", "shot_id": None,
                  "inputs": {"references": [], "prompt": "老僧定妆照"}, "engine": {"provider": "volcengine_ark", "model": "m"},
                  "budget": {"billable": True, "usage": {"images": 1}}, "submitted_at": "t0", "finished_at": "t1", "status": "succeeded",
                  "outputs": [{"id": "定妆", "path": "06-素材/资产/定妆.png", "sha256": L.sha256(target), "face_trust_until": "2026-11-10T00:00:00+08:00"}],
                  "errors": [], "selection": None}
        path = self.project / "06-素材/资产/定妆-生成记录.json"
        path.write_text(json.dumps(record, ensure_ascii=False), "utf-8")
        code, _, err = self.cli("promote", "--project", str(self.project), "--record", str(path), "--kind", "character", "--id", "老僧-02",
                                "--name", "老僧", "--summary", "老年僧人定妆照", "--attr", 'identity=["年长僧人"]')
        self.assertEqual(code, 0, err)
        item = json.loads((self.library / "character/老僧-02/item.json").read_text("utf-8"))
        self.assertEqual((item["rights"]["status"], item["provenance"]["prompt"]), ("generated", "老僧定妆照"))
        self.assertEqual(item["provider_refs"][0]["until"], "2026-11-10T00:00:00+08:00")

    def test_item_rules(self):
        kinds, rights = L.taxonomy()
        item = {"format": L.ITEM_FORMAT, "id": "x", "kind": "music", "name": "n", "summary": "s", "files": [],
                "rights": {"status": "licensed"}}
        errors = L.item_errors(item, kinds, rights)
        self.assertTrue(any("license" in error for error in errors))
        self.assertTrue(any("没有文件" in error for error in errors))

    def test_use_rejects_malformed_entry_before_copy(self):
        self.add_monk()
        path = self.library / "character/老僧-01/item.json"
        item = json.loads(path.read_text("utf-8"))
        item["files"][0]["path"] = "../../../outside.png"
        path.write_text(json.dumps(item), "utf-8")
        code, _, err = self.cli("use", "老僧-01", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("相对路径", err)
        self.assertFalse((self.project / L.COPY_DIR).exists())

    def test_use_cannot_overwrite_an_edited_project_copy(self):
        self.add_monk()
        self.assertEqual(self.cli("use", "老僧-01", "--project", str(self.project))[0], 0)
        target = self.project / L.COPY_DIR / "老僧-01/老僧.png"
        target.write_bytes(b"project edit")
        code, _, err = self.cli("use", "老僧-01", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("不同内容", err)
        self.assertEqual(target.read_bytes(), b"project edit")

    def test_invalid_add_is_atomic_and_can_be_retried(self):
        argv = ["add", "--kind", "character", "--id", "retry", "--name", "n", "--summary", "s", "--file", str(self.image)]
        self.assertEqual(self.cli(*argv, "--rights", "licensed")[0], 1)
        self.assertFalse((self.library / "character/retry").exists())
        self.assertEqual(self.cli(*argv, "--rights", "owned")[0], 0)

    def test_project_mismatch_does_not_copy_or_change_bible(self):
        self.add_monk()
        bible = json.loads(self.bible.read_text("utf-8"))
        bible["project_id"] = "foreign"
        self.bible.write_text(json.dumps(bible), "utf-8")
        before = self.bible.read_bytes()
        code, _, _ = self.cli("use", "老僧-01", "--project", str(self.project), "--bible", str(self.bible), "--entity", "CH-elder-01")
        self.assertEqual(code, 1)
        self.assertEqual(self.bible.read_bytes(), before)
        self.assertFalse((self.project / L.COPY_DIR).exists())

    def test_use_keeps_original_provider_metadata(self):
        self.add_monk()
        path = self.library / "character/老僧-01/item.json"
        item = json.loads(path.read_text("utf-8"))
        item["provenance"] = {"provider": "volcengine_ark"}
        item["files"][0].update(source_url="https://example.org/original.png", source_url_expires_at="2026-11-10T00:00:00+08:00",
                                face_trust_until="2026-11-20T00:00:00+08:00")
        path.write_text(json.dumps(item), "utf-8")
        self.assertEqual(self.cli("use", "老僧-01", "--project", str(self.project))[0], 0)
        manifest = json.loads((self.project / L.COPY_DIR / "老僧-01/来源.json").read_text("utf-8"))
        self.assertEqual(manifest["provider"], "volcengine_ark")
        self.assertEqual(manifest["files"][0]["source_url"], item["files"][0]["source_url"])
        self.assertEqual(manifest["files"][0]["sha256"], L.sha256(self.image))

    def test_reserved_metadata_filenames_cannot_be_assets(self):
        for index, filename in enumerate(("item.json", "来源.json")):
            source = Path(self.temp.name) / filename
            source.write_text('{"keep":"original"}', "utf-8")
            code, _, err = self.cli("add", "--kind", "motion", "--id", f"reserved-{index}", "--name", "n", "--summary", "s",
                                    "--rights", "owned", "--file", str(source))
            self.assertEqual(code, 1)
            self.assertIn("保留文件名", err)
            self.assertEqual(source.read_text("utf-8"), '{"keep":"original"}')
            self.assertFalse((self.library / f"motion/reserved-{index}").exists())

    def test_fileless_use_checks_manifest_containment(self):
        code, _, _ = self.cli("add", "--kind", "motion", "--id", "gesture", "--name", "n", "--summary", "s",
                              "--rights", "owned", "--attr", "beats=wave")
        self.assertEqual(code, 0)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        target = self.project / L.COPY_DIR / "gesture"
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)
        code, _, err = self.cli("use", "gesture", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("来源清单路径", err)
        self.assertFalse((outside / "来源.json").exists())


if __name__ == "__main__":
    unittest.main()
