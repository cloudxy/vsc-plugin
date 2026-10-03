#!/usr/bin/env python3
"""Regression tests through the project CLI, including actual concurrent writers."""
import concurrent.futures
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import vsc_state as state_module

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "vsc_state.py"


class Integrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-integrity-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.ok("init", self.project, "--title", "完整性试验")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(CLI), *map(str, args)], capture_output=True, text=True)

    def ok(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def bad(self, *args):
        result = self.run_cli(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value, encoding="utf-8")
        return path

    def state(self):
        return json.loads((self.project / "vsc.json").read_text("utf-8"))

    def brief(self):
        value = json.loads((ROOT / "templates" / "creative-brief.json").read_text("utf-8"))
        value.update(audience="悬疑短片观众", desired_experience="理解人物选择并感到紧张", decision_owner="导演")
        return value

    def add(self, kind="vsc.creative_brief", stage="brief", value=None, extra=()):
        path = self.write("source-" + str(len(self.state()["artifacts"])) + (".json" if isinstance(value, dict) or value is None else ".md"), self.brief() if value is None else value)
        identifier = self.ok("artifact", "add", self.project, "--type", kind, "--stage", stage, "--file", path, *extra).split()[1]
        return identifier, path

    def approve(self, identifier):
        return self.ok("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "导演")

    def version(self, identifier):
        item = next(x for x in self.state()["artifacts"] if x["id"] == identifier)
        return self.project / item["path"]

    def objects(self):
        for kind, identifier, parent in (("episode", "EP-001", None), ("scene", "EP-001-SC-001", "EP-001"),
                                         ("sequence", "SEQ-001", "EP-001-SC-001"), ("shot", "SH-001", "SEQ-001"),
                                         ("shot", "SH-002", "SEQ-001")):
            self.ok("object", "add", self.project, "--kind", kind, "--id", identifier,
                    *(["--parent", parent] if parent else []))

    def test_empty_json_and_template_cannot_be_approved(self):
        identifier, _ = self.add(value={})
        self.assertIn("不能批准", self.bad("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "导演"))
        value = json.loads((ROOT / "templates" / "creative-brief.json").read_text("utf-8"))
        identifier, _ = self.add(value=value)
        self.assertIn("模板占位", self.bad("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "导演"))
        self.bad("gate", "check", self.project, "brief")

    def test_wrong_owner_stage_is_rejected(self):
        path = self.write("empty.json", {})
        self.assertIn("所属阶段", self.bad("artifact", "add", self.project, "--type", "vsc.creative_brief",
                                         "--stage", "delivery", "--file", path))

    def test_source_edit_does_not_mutate_approved_version(self):
        identifier, original = self.add()
        self.approve(identifier)
        original.write_text("{}", encoding="utf-8")
        self.ok("gate", "check", self.project, "brief")
        original.unlink()
        self.ok("context", "build", self.project, "--role", "director", "--task", "按原批准目标设计镜头", "--artifact", identifier)
        self.assertEqual(json.loads(self.version(identifier).read_text("utf-8"))["audience"], "悬疑短片观众")

    def test_changed_version_is_rejected_by_gate_and_context(self):
        identifier, _ = self.add()
        self.approve(identifier)
        self.version(identifier).write_text("{}", encoding="utf-8")
        self.assertIn("版本内容已变化", self.bad("gate", "check", self.project, "brief"))
        self.assertIn("版本内容已变化", self.bad("context", "build", self.project, "--role", "director", "--task", "镜头", "--artifact", identifier))

    def test_deleted_version_is_rejected(self):
        identifier, _ = self.add()
        self.approve(identifier)
        self.version(identifier).unlink()
        self.assertIn("版本文件不存在", self.bad("gate", "check", self.project, "brief"))

    def test_dependency_rejection_invalidates_downstream(self):
        identifier, _ = self.add()
        self.approve(identifier)
        source = self.write("novel.txt", "小说来源")
        self.ok("source", "add", self.project, "--kind", "novel", "--file", source)
        dependent, _ = self.add("vsc.source_map", "source", "来源事实与推断已区分", ["--depends", identifier])
        self.approve(dependent)
        self.ok("gate", "check", self.project, "source")
        self.ok("artifact", "decide", self.project, identifier, "--status", "rejected", "--by", "导演")
        self.assertIn("依赖", self.bad("context", "build", self.project, "--role", "director", "--task", "来源", "--artifact", dependent))

    def test_supersession_invalidates_old_downstream(self):
        original, _ = self.add()
        self.approve(original)
        dependent, _ = self.add("vsc.learning_sample", "production", "候选试验", ["--depends", original])
        self.approve(dependent)
        replacement, _ = self.add(extra=["--supersedes", original])
        self.approve(replacement)
        self.ok("gate", "check", self.project, "brief")
        self.assertIn("替代", self.bad("context", "build", self.project, "--role", "director", "--task", "试验", "--artifact", dependent))

    def test_draft_dependency_blocks_approval(self):
        original, _ = self.add()
        dependent, _ = self.add("vsc.learning_sample", "production", "候选试验", ["--depends", original])
        self.assertIn("尚未批准", self.bad("artifact", "decide", self.project, dependent, "--status", "approved", "--by", "导演"))

    def test_supersession_cannot_invalidate_itself_through_dependencies(self):
        original, _ = self.add()
        self.approve(original)
        child, _ = self.add("vsc.learning_sample", "production", "候选", ["--depends", original])
        self.approve(child)
        path = self.write("replacement.json", self.brief())
        for dependency in (original, child):
            self.assertIn("不能依赖被替代", self.bad("artifact", "add", self.project, "--type", "vsc.creative_brief",
                                                   "--stage", "brief", "--file", path, "--supersedes", original, "--depends", dependency))

    def test_concurrent_cli_writes_preserve_all_results(self):
        paths = [self.write(f"source-{index}.txt", f"来源 {index}") for index in range(12)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda path: self.run_cli("source", "add", self.project, "--kind", "novel", "--file", path), paths))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = self.state()
        self.assertEqual(len(state["sources"]), 12)
        self.assertEqual(len({x["id"] for x in state["sources"]}), 12)
        self.assertEqual(len({x["id"] for x in state["events"]}), 13)

    def test_profile_snapshot_does_not_follow_current_catalog(self):
        state = self.state()
        updated = copy.deepcopy(state["profile_snapshot"])
        updated["version"] = "future"
        updated["stages"][0]["required"].append("vsc.new_requirement")
        with patch.object(state_module, "profile_catalog", return_value={updated["profile_id"]: updated}):
            pinned = state_module.project_profile(state)
            self.assertNotEqual(pinned["version"], "future")
            self.assertNotIn("vsc.new_requirement", pinned["stages"][0]["required"])

    def test_stale_in_process_write_is_refused(self):
        first = state_module.project_state(self.project)
        stale = copy.deepcopy(first)
        state_module.save(self.project, first)
        with self.assertRaises(SystemExit):
            state_module.save(self.project, stale)

    def test_unknown_sound_shots_fail_project_check_and_approval(self):
        self.objects()
        value = json.loads((ROOT / "templates" / "sound-cue-sheet.json").read_text("utf-8"))
        value["project_id"] = self.state()["project_id"]
        value["boundaries"][0]["to_shot"] = "NONEXISTENT"
        path = self.write("sound.json", value)
        self.assertIn("不存在的 shot", self.bad("sound", "validate", path, "--project", self.project))
        identifier = self.ok("artifact", "add", self.project, "--type", "vsc.sound_cue_sheet", "--stage", "post", "--file", path).split()[1]
        self.assertIn("不存在的 shot", self.bad("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "导演"))

    def test_continuity_requires_real_asset_versions(self):
        self.objects()
        value = json.loads((ROOT / "templates" / "continuity-plan.json").read_text("utf-8"))
        value["project_id"] = self.state()["project_id"]
        path = self.write("continuity.json", value)
        self.assertIn("不存在的 asset", self.bad("continuity", "validate", path, "--project", self.project))
        asset, _ = self.add("vsc.asset_reference", "design", "角色与场景参考图说明")
        self.approve(asset)
        for identifier in ("角色-主角-v1", "场景-客厅-v1"):
            self.ok("object", "add", self.project, "--kind", "asset", "--id", identifier, "--artifact", asset)
        self.ok("continuity", "validate", path, "--project", self.project)
        self.version(asset).unlink()
        self.assertIn("版本文件失效", self.bad("continuity", "validate", path, "--project", self.project))

    def test_reference_asset_inherits_dependency_validity(self):
        self.objects()
        brief, _ = self.add()
        self.approve(brief)
        asset, _ = self.add("vsc.asset_reference", "design", "具体参考资产", ["--depends", brief])
        self.approve(asset)
        for identifier in ("角色-主角-v1", "场景-客厅-v1"):
            self.ok("object", "add", self.project, "--kind", "asset", "--id", identifier, "--artifact", asset)
        value = json.loads((ROOT / "templates" / "continuity-plan.json").read_text("utf-8"))
        value["project_id"] = self.state()["project_id"]
        path = self.write("asset-plan.json", value)
        self.ok("continuity", "validate", path, "--project", self.project)
        self.ok("artifact", "decide", self.project, brief, "--status", "rejected", "--by", "导演")
        self.assertIn("尚未批准", self.bad("continuity", "validate", path, "--project", self.project))

    def test_shot_state_cannot_silently_change_sequence_scene(self):
        self.objects()
        self.ok("object", "add", self.project, "--kind", "scene", "--id", "SC-OTHER", "--parent", "EP-001")
        asset, _ = self.add("vsc.asset_reference", "design", "参考资产")
        self.approve(asset)
        for identifier in ("角色-主角-v1", "场景-客厅-v1"):
            self.ok("object", "add", self.project, "--kind", "asset", "--id", identifier, "--artifact", asset)
        value = json.loads((ROOT / "templates" / "continuity-plan.json").read_text("utf-8"))
        value["project_id"] = self.state()["project_id"]
        for shot in value["shots"]:
            shot["entry_state"]["scene_id"] = shot["exit_state"]["scene_id"] = "SC-OTHER"
        path = self.write("wrong-scene.json", value)
        self.assertIn("sequence 所属场景不一致", self.bad("continuity", "validate", path, "--project", self.project))

    def test_serial_requires_separate_episode_scope(self):
        self.project = self.root / "serial"
        self.ok("init", self.project, "--title", "两集试验", "--profile", "vsc.novel-serial")
        for identifier in ("EP-1", "EP-2"):
            self.ok("object", "add", self.project, "--kind", "episode", "--id", identifier)
            self.ok("object", "add", self.project, "--kind", "scene", "--id", identifier + "-SC", "--parent", identifier)
        brief, _ = self.add()
        self.approve(brief)
        contract, _ = self.add("vsc.adaptation_contract", "brief", "保留人物动机；允许压缩事件")
        self.approve(contract)
        source = self.write("serial-source.txt", "原著来源")
        self.ok("source", "add", self.project, "--kind", "novel", "--file", source)
        source_ids = []
        for kind in ("vsc.source_map", "vsc.story_bible"):
            identifier, _ = self.add(kind, "source", "来源事实与故事线索", ["--depends", brief, "--depends", contract])
            self.approve(identifier)
            source_ids.append(identifier)
        mapping = {"format": "vsc.adaptation-map/v1", "project_id": self.state()["project_id"],
                   "source_units": [{"id": "SRC-1", "locator": "ch1:p1", "fact_or_claim": "原著事件", "narrative_function": "建立动机"}],
                   "episodes": [{"id": ep, "logline": "人物选择", "opening_hook": "未知来信", "exit_hook": "新的阻碍"} for ep in ("EP-1", "EP-2")],
                   "screen_units": [{"id": ep + "-UNIT", "episode_id": ep, "source_refs": ["SRC-1"], "scene_id": ep + "-SC",
                                     "visible_action": "人物打开信件", "character_goal": "寻找真相", "obstacle": "缺失信息",
                                     "turn": "发现隐瞒", "audience_information": "来信者认识人物"} for ep in ("EP-1", "EP-2")]}
        adaptation = []
        for kind, value in (("vsc.adaptation_plan", mapping), ("vsc.episode_beats", "每集人物目标、阻碍与转折")):
            identifier, _ = self.add(kind, "adaptation", value, [arg for ref in source_ids for arg in ("--depends", ref)])
            self.approve(identifier)
            adaptation.append(identifier)
        dependency_args = [arg for ref in adaptation for arg in ("--depends", ref)]
        unscoped, _ = self.add("vsc.screenplay", "script", "一份分集剧本")
        self.assertIn("episode 范围", self.bad("artifact", "decide", self.project, unscoped, "--status", "approved", "--by", "导演"))
        first, _ = self.add("vsc.screenplay", "script", "第一集剧本", ["--scope", "EP-1", *dependency_args])
        self.approve(first)
        self.assertIn("[EP-2]", self.bad("gate", "check", self.project, "script"))

    def test_migration_preserves_backup_but_does_not_inherit_approval(self):
        identifier, _ = self.add()
        self.approve(identifier)
        state = self.state()
        state["schema_version"] = 2
        state["profile_version"] = "historical-missing"
        (self.project / "vsc.json").write_text(json.dumps(state), encoding="utf-8")
        self.assertIn("历史 Profile", self.bad("migrate", self.project))
        self.ok("migrate", self.project, "--accept-current-profile")
        migrated = self.state()
        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(migrated["artifacts"][0]["status"], "draft")
        self.assertTrue(list((self.project / "09-台账").glob("vsc-schema-2-*.json")))
        self.bad("gate", "check", self.project, "brief")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "real media integration needs FFmpeg")
    def test_delivery_binds_real_media_and_relative_review_resources(self):
        import media_qa
        self.objects()
        media_root = self.root / "media"
        media_root.mkdir()
        clip = media_root / "fixture.mp4"
        generated = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24",
                                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1",
                                    "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(clip)], capture_output=True, text=True)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.ok("source", "add", self.project, "--kind", "original", "--file", self.write("story.txt", "人物发现来信"))
        asset, _ = self.add("vsc.asset_reference", "design", "synthetic fixture reference, not AI quality evidence")
        self.approve(asset)
        for identifier in ("角色-主角-v1", "场景-客厅-v1"):
            self.ok("object", "add", self.project, "--kind", "asset", "--id", identifier, "--artifact", asset)
        mapping = {"format": "vsc.adaptation-map/v1", "project_id": self.state()["project_id"],
                   "source_units": [{"id": "SRC", "locator": "paragraph1", "fact_or_claim": "发现来信", "narrative_function": "建立疑问"}],
                   "episodes": [{"id": "EP-001", "logline": "发现隐瞒", "opening_hook": "未知来信", "exit_hook": "门外来人"}],
                   "screen_units": [{"id": "UNIT", "episode_id": "EP-001", "source_refs": ["SRC"], "scene_id": "EP-001-SC-001",
                                     "visible_action": "打开信件", "character_goal": "找真相", "obstacle": "信息不足", "turn": "发现名字",
                                     "audience_information": "来信者认识主角"}]}
        continuity = json.loads((ROOT / "templates" / "continuity-plan.json").read_text("utf-8"))
        continuity["project_id"] = self.state()["project_id"]
        for shot in continuity["shots"]:
            shot.update(duration_ms=500, handles={"head_ms": 50, "tail_ms": 50})
        plan = {"format": "vsc.remotion-render-plan/v1", "project_id": self.state()["project_id"],
                "composition": {"id": "fixture", "width": 64, "height": 64, "fps": 24, "duration_in_frames": 24},
                "segments": [{"id": "V1", "kind": "video", "source": "fixture.mp4", "source_shot_id": "SH-001",
                              "from_frame": 0, "duration_in_frames": 12, "muted": True},
                             {"id": "V2", "kind": "video", "source": "fixture.mp4", "source_shot_id": "SH-002",
                              "from_frame": 12, "duration_in_frames": 12, "source_in_frame": 12, "muted": True},
                             {"id": "A1", "kind": "audio", "source": "fixture.mp4", "from_frame": 0, "duration_in_frames": 24}]}
        content = {"vsc.creative_brief": self.brief(), "vsc.adaptation_plan": mapping,
                   "vsc.shot_plan": continuity, "vsc.timeline": plan}
        previous, timeline = [], None
        for stage in self.state()["profile_snapshot"]["stages"]:
            if stage["id"] == "delivery":
                break
            current = []
            for kind in stage["required"]:
                identifier, _ = self.add(kind, stage["id"], content.get(kind, "fixture workflow evidence for " + kind),
                                         [arg for ref in previous for arg in ("--depends", ref)])
                self.approve(identifier)
                current.append(identifier)
                if kind == "vsc.timeline":
                    timeline = identifier
            previous = current
        self.assertIn("vsc.sample_review", self.bad("gate", "check", self.project, "delivery"))
        plan_path = self.write("fixture-plan.json", plan)
        qa = media_qa.check_plan(plan_path, media_root, media_qa.LocalProbeAdapter(), clip)
        self.assertEqual(qa["status"], "passed", qa["errors"])
        qa_path = self.write("qa.json", qa)
        qa_id, _ = self.add("vsc.media_qa", "post", qa, ["--depends", timeline])
        self.approve(qa_id)
        review = {"format": "vsc.sample-review/v1", "project_id": self.state()["project_id"], "reviewer": "fixture tester",
                  "technical_report": "qa.json", "technical_report_sha256": media_qa.sha256(qa_path),
                  "assessments": {key: {"result": "pass", "evidence": "00:00 synthetic fixture: validates record binding only"}
                                  for key in media_qa.REVIEW_CATEGORIES},
                  "run": {"elapsed_seconds": 1, "cost_amount": 0, "currency": "CNY", "failures": []}}
        manifest, _ = self.add("vsc.delivery_manifest", "delivery", "fixture export, not a professional film", ["--depends", timeline])
        self.approve(manifest)
        review_id, _ = self.add("vsc.sample_review", "delivery", review, ["--depends", timeline, "--depends", qa_id])
        self.approve(review_id)
        self.assertTrue((self.version(review_id).parent / "qa.json").is_file())
        self.ok("gate", "check", self.project, "delivery")
        clip.unlink()
        self.assertIn("失效", self.bad("gate", "check", self.project, "delivery"))


if __name__ == "__main__":
    unittest.main()
