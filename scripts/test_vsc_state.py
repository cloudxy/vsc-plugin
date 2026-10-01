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
        self.assertEqual((state["schema_version"], state["profile_id"]), (2, "vsc.narrative-base"))
        self.assertTrue(state["project_id"].startswith("vsc-project-"))
        for rel in ("00-委托/创作委托.md", "04-视听设计/镜头/镜头表.md", "09-台账/README.md",
                    "10-记忆/README.md", "11-学习/README.md", "12-评测/README.md"):
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


class TestMemoryAndContext(Base):
    def test_approved_curated_memory_and_ephemeral_parent_brief(self):
        brief = self.artifact("vsc.creative_brief", "brief", "00-委托/brief.md")
        output = self.ok("memory", "add", self.project, "--scope", "role", "--role", "director",
                         "--kind", "lesson", "--source", brief, "--content", "追逐镜头先交代出口，再提高剪辑密度。")
        memory_id = output.split()[1]
        self.ok("memory", "decide", self.project, memory_id, "--status", "approved", "--by", "导演")
        restricted = self.ok("memory", "add", self.project, "--scope", "project", "--kind", "fact",
                             "--content", "仅授权剪辑师查看的联系信息。", "--sensitivity", "restricted").split()[1]
        self.ok("memory", "decide", self.project, restricted, "--status", "approved", "--by", "制片")
        output = self.ok("context", "build", self.project, "--role", "director", "--task", "设计追逐镜头",
                         "--artifact", brief, "--parent-brief", "本轮用户希望镜头更紧张。")
        self.assertIn("CT-0001", output)
        packet = json.loads((self.project / "10-记忆/上下文/CT-0001.json").read_text("utf-8"))
        self.assertEqual(packet["role"]["id"], "director")
        self.assertEqual(packet["inputs"][0]["id"], brief)
        self.assertEqual(packet["parent_brief"]["persistence"], "ephemeral_not_saved")
        self.assertEqual([x["id"] for x in packet["approved_memories"]], [memory_id])
        state = json.loads((self.project / "vsc.json").read_text("utf-8"))
        self.assertNotIn("本轮用户希望镜头更紧张", json.dumps(state, ensure_ascii=False))


class TestLearningLifecycle(Base):
    def test_owned_material_can_be_evaluated_and_promoted(self):
        source = self.write("01-来源/武打样片.mp4", "placeholder video")
        self.ok("source", "add", self.project, "--kind", "video", "--file", source, "--rights", "owned")
        evidence = self.write("11-学习/观察/打斗节拍.md", "每次动作前先建立方向线。")
        output = self.ok("learn", "observe", self.project, "--kind", "action", "--source", "S-0001", "--file", evidence,
                         "--content", "记录起势、交手、受击、停顿、反转五拍；保留方向线。")
        observation = output.split()[1]
        output = self.ok("capability", "propose", self.project, "--name", "五拍打斗节奏", "--kind", "action",
                         "--observation", observation, "--method", "按五拍拆分镜头并为每拍写方向线。",
                         "--limits", "仅用于已获授权项目；不复制人物身份或特定作品画面。", "--role", "director")
        capability = output.split()[1]
        self.ok("capability", "decide", self.project, capability, "--status", "pilot", "--by", "导演")
        evaluation = self.artifact("vsc.learning_evaluation", "production", "12-评测/五拍打斗.md")
        self.ok("capability", "evaluate", self.project, capability, "--result", "pass", "--evidence", evaluation,
                "--by", "导演", "--note", "节奏、方向和人物连续性均可复核。")
        self.ok("capability", "decide", self.project, capability, "--status", "approved", "--by", "导演")
        self.assertIn("[approved]", self.ok("capability", "list", self.project, "--status", "approved"))
        output = self.ok("context", "build", self.project, "--role", "director", "--task", "设计下一场动作戏")
        self.assertIn("CT-0001", output)
        packet = json.loads((self.project / "10-记忆/上下文/CT-0001.json").read_text("utf-8"))
        self.assertEqual(packet["approved_capabilities"][0]["id"], capability)

    def test_unknown_rights_cannot_enter_pilot(self):
        source = self.write("01-来源/参考图.jpg", "placeholder image")
        self.ok("source", "add", self.project, "--kind", "image", "--file", source)
        evidence = self.write("11-学习/观察/构图.md", "中心构图")
        observation = self.ok("learn", "observe", self.project, "--kind", "layout", "--source", "S-0001", "--file", evidence,
                              "--content", "前景遮挡与中景人物形成层次。").split()[1]
        capability = self.ok("capability", "propose", self.project, "--name", "层次构图", "--kind", "layout",
                             "--observation", observation, "--method", "先定前中后景。", "--limits", "仅作研究。", "--role", "director").split()[1]
        self.assertIn("不能进入试用", self.bad("capability", "decide", self.project, capability, "--status", "pilot", "--by", "导演"))


class TestMigration(Base):
    def test_schema_one_migrates_conservatively(self):
        source = self.write("01-来源/小说.txt", "来源")
        self.ok("source", "add", self.project, "--kind", "novel", "--file", source, "--rights", "owned")
        path = self.project / "vsc.json"
        state = json.loads(path.read_text("utf-8"))
        state["schema_version"] = 1
        state.pop("memories"); state.pop("contexts"); state.pop("learning")
        state["sources"][0].pop("rights")
        path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
        self.assertIn("需要迁移", self.bad("status", self.project))
        self.ok("migrate", self.project)
        migrated = json.loads(path.read_text("utf-8"))
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["sources"][0]["rights"], "unknown")
        self.assertEqual(migrated["learning"], {"observations": [], "capabilities": []})


class TestCreativeContracts(Base):
    def state(self, scene, pose):
        return {
            "scene_id": scene, "location_id": "雨巷", "time_state": "夜雨", "lighting_id": "路灯冷光",
            "soundscape_id": "雨声-远车", "characters": {"女主": {"costume_id": "女主-风衣-v1", "pose": pose}},
            "camera": {"framing": "中景", "motion": "右移", "screen_direction": "左到右"},
        }

    def test_adaptation_continuity_and_sound_contracts(self):
        adaptation = self.write("02-改编/改编映射.json", json.dumps({
            "format": "vsc.adaptation-map/v1", "project_id": "雨夜计划",
            "source_units": [{"id": "SRC-1", "locator": "ch01:p4", "fact_or_claim": "她未签收信", "narrative_function": "制造误读"}],
            "episodes": [{"id": "EP-01", "logline": "假信带来追逐", "opening_hook": "雨夜假信", "exit_hook": "信封背面出现名字"}],
            "screen_units": [{"id": "SC-1", "episode_id": "EP-01", "source_refs": ["SRC-1"], "scene_id": "雨巷追逐",
                              "visible_action": "她攥住信封转身逃跑", "character_goal": "摆脱跟踪", "obstacle": "巷口被拦住",
                              "turn": "发现信封背面有自己的名字", "audience_information": "跟踪者知道她的身份"}],
        }, ensure_ascii=False))
        self.assertIn("ADAPTATION: PASS", self.ok("adaptation", "validate", adaptation))
        continuity = self.write("05-预演/连续性计划.json", json.dumps({
            "format": "vsc.continuity-plan/v1", "project_id": "雨夜计划", "sequence_id": "EP01-SC01", "max_clip_ms": 8000,
            "shots": [
                {"id": "SH-01", "duration_ms": 6000, "reference_asset_ids": ["角色-女主-v1", "场景-雨巷-v1"], "handles": {"head_ms": 300, "tail_ms": 500},
                 "entry_state": self.state("雨巷追逐", "起跑"), "exit_state": self.state("雨巷追逐", "奔跑中"),
                 "bridge_to_next": {"strategy": "match_action", "purpose": "保持逃跑方向和紧张感", "match_fields": ["location_id", "characters.女主.costume_id", "characters.女主.pose", "camera.screen_direction"]}},
                {"id": "SH-02", "duration_ms": 6000, "reference_asset_ids": ["角色-女主-v1", "场景-雨巷-v1"], "handles": {"head_ms": 500, "tail_ms": 300},
                 "entry_state": self.state("雨巷追逐", "奔跑中"), "exit_state": self.state("雨巷追逐", "停下回望")},
            ],
        }, ensure_ascii=False))
        self.assertIn("CONTINUITY: PASS", self.ok("continuity", "validate", continuity))
        sound = self.write("07-后期/声音提示表.json", json.dumps({
            "format": "vsc.sound-cue-sheet/v1", "project_id": "雨夜计划", "sequence_id": "EP01-SC01", "duration_ms": 12000,
            "ambience_beds": [{"id": "AMB-01", "start_ms": 0, "end_ms": 12000, "soundscape_id": "雨声-远车", "usage_rights": "owned"}],
            "music_cues": [{"id": "MUS-01", "start_ms": 0, "end_ms": 12000, "narrative_function": "追逐张力", "emotion": "焦灼", "intensity": 3,
                              "entry": "低音渐入", "exit": "停在回望前", "usage_rights": "licensed", "stems": ["节奏", "低音"]}],
            "boundaries": [{"id": "B-01", "from_shot": "SH-01", "to_shot": "SH-02", "at_ms": 6000, "strategy": "L_cut", "tail_ms": 400,
                            "purpose": "让脚步声先带入下一镜", "ambience_bed_id": "AMB-01"}],
        }, ensure_ascii=False))
        self.assertIn("SOUND: PASS", self.ok("sound", "validate", sound))

    def test_continuity_rejects_unmatched_boundary(self):
        plan = self.write("05-预演/错位.json", json.dumps({
            "format": "vsc.continuity-plan/v1", "project_id": "雨夜计划", "sequence_id": "EP01-SC01", "max_clip_ms": 8000,
            "shots": [
                {"id": "SH-01", "duration_ms": 6000, "reference_asset_ids": ["角色-女主-v1"], "handles": {"head_ms": 300, "tail_ms": 300},
                 "entry_state": self.state("雨巷追逐", "起跑"), "exit_state": self.state("雨巷追逐", "向右跑"),
                 "bridge_to_next": {"strategy": "match_action", "purpose": "保持动作", "match_fields": ["characters.女主.pose"]}},
                {"id": "SH-02", "duration_ms": 6000, "reference_asset_ids": ["角色-女主-v1"], "handles": {"head_ms": 300, "tail_ms": 300},
                 "entry_state": self.state("雨巷追逐", "向左跑"), "exit_state": self.state("雨巷追逐", "停下")},
            ],
        }, ensure_ascii=False))
        self.assertIn("不一致", self.bad("continuity", "validate", plan))


if __name__ == "__main__":
    unittest.main()
