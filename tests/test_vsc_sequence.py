#!/usr/bin/env python3
"""集／场衔接只读绑定测试。运行：python3 -B tests/test_vsc_sequence.py。"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT, SCRIPTS
import vsc_sequence as S


def state():
    return {
        "format": "vsc.scene-state/v1", "project_id": "test-project",
        "scenes": [
            {"id": "SC-001", "location_id": "room", "baseline": {
                "time": "night", "weather": "dry", "lighting": "lamp",
                "entities": {"actor": {"position": "table", "holding": []}}},
             "shots": [{"id": "A1", "changes": {}},
                       {"id": "A2", "changes": {"entities": {"actor": {"position": "door"}}}}]},
            {"id": "SC-002", "location_id": "room", "baseline": {
                "time": "night", "weather": "dry", "lighting": "lamp",
                "entities": {"actor": {"position": "door", "holding": []}}},
             "shots": [{"id": "B1", "changes": {}}, {"id": "B2", "changes": {}}]},
        ],
    }


class SequenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        (self.project / "vsc.json").write_text(json.dumps({"project_id": "test-project"}), "utf-8")
        self.state = state()
        self.state_path = self.project / "states.json"
        self.write_state()
        self.plan = {
            "format": S.FORMAT, "project_id": "test-project",
            "units": [
                {"id": "SC-001", "kind": "scene", "state_path": "states.json",
                 "state_sha256": self.sha(), "entry_shot": "A1", "exit_shot": "A2"},
                {"id": "SC-002", "kind": "scene", "state_path": "states.json",
                 "state_sha256": self.sha(), "entry_shot": "B1", "exit_shot": "B2"},
            ],
            "links": [{"from": "SC-001", "to": "SC-002", "mode": "continuous",
                       "purpose": "测试作者填写的场间行动承接。",
                       "narrative": {"carry": "前场动作落在门边。", "receive": "后场从门边接续动作。"},
                       "audio": {"strategy": "sound_bridge", "description": "环境声从前场出点延续到后场入点。"},
                       "match_fields": ["location_id", "environment", "entities.actor.position"], "changes": []}],
        }

    def write_state(self):
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), "utf-8")

    def sha(self):
        return hashlib.sha256(self.state_path.read_bytes()).hexdigest()

    def rebind(self):
        self.write_state()
        for unit in self.plan["units"]:
            unit["state_sha256"] = self.sha()

    def check(self):
        return S.sequence_problems(self.plan, self.project)

    def test_template_and_structure_do_not_require_referenced_files(self):
        template = json.loads((ROOT / "templates/sequence-links.json").read_text("utf-8"))
        self.assertEqual(S.sequence_errors(template), [])
        self.state_path.unlink()
        self.assertEqual(S.sequence_errors(self.plan), [])
        self.assertTrue(any("无法绑定状态文件" in error for error in self.check()))

    def test_real_files_derive_exit_changes_and_check_is_read_only(self):
        before = {path: path.read_bytes() for path in self.project.iterdir()}
        self.assertEqual(self.check(), [])  # A2 的出点为 door，A1 的基线为 table。
        self.assertEqual({path: path.read_bytes() for path in self.project.iterdir()}, before)

    def test_links_must_cover_each_ordered_neighbor_exactly_once(self):
        for links in ([], self.plan["links"] * 2,
                      [{**self.plan["links"][0], "from": "SC-002", "to": "SC-001"}],
                      [{**self.plan["links"][0], "to": "SC-003"}]):
            with self.subTest(links=links):
                plan = {**self.plan, "links": links}
                self.assertTrue(any("每对相邻单元" in error for error in S.sequence_errors(plan)))

    def test_state_hash_drift_and_foreign_project_ids_are_rejected(self):
        self.state_path.write_bytes(self.state_path.read_bytes() + b"\n")
        self.assertTrue(any("版本已漂移" in error for error in self.check()))
        self.state["project_id"] = "another-project"
        self.rebind()
        self.assertTrue(any("状态文件与项目的 project_id" in error for error in self.check()))
        self.plan["project_id"] = "another-project"
        self.assertTrue(any("项目 vsc.json 的 project_id" in error for error in self.check()))

    def test_absolute_parent_paths_and_symlink_escape_are_rejected(self):
        for path in ("../outside.json", str(self.state_path), "\\server\\outside.json"):
            with self.subTest(path=path):
                plan = copy.deepcopy(self.plan)
                plan["units"][0]["state_path"] = path
                self.assertTrue(any("相对文件路径" in error for error in S.sequence_errors(plan)))
        outside = Path(self.temp.name) / "outside.json"
        outside.write_bytes(self.state_path.read_bytes())
        (self.project / "escape.json").symlink_to(outside)
        self.plan["units"][0]["state_path"] = "escape.json"
        self.assertTrue(any("超出项目目录" in error for error in self.check()))

    def test_endpoint_shots_must_exist_and_cover_a_complete_scene(self):
        for entry, exit_, expected in (("missing", "A2", "不在"), ("A2", "A1", "之后"),
                                       ("A2", "A2", "覆盖完整"), ("A1", "B2", "覆盖完整")):
            with self.subTest(entry=entry, exit=exit_):
                plan = copy.deepcopy(self.plan)
                plan["units"][0].update(entry_shot=entry, exit_shot=exit_)
                self.assertTrue(any(expected in error for error in S.sequence_problems(plan, self.project)))

    def test_state_file_unit_order_cannot_overlap_or_reverse(self):
        self.plan["units"].reverse()
        self.plan["links"][0].update({"from": "SC-002", "to": "SC-001"})
        self.assertTrue(any("重叠或倒置" in error for error in self.check()))

    def test_continuous_detects_all_undeclared_leaf_changes(self):
        second = self.state["scenes"][1]["baseline"]
        second["time"] = "morning"
        second["lighting"] = "sunlight"
        second["entities"]["actor"]["position"] = "window"
        self.rebind()
        link = self.plan["links"][0]
        link["match_fields"] = ["location_id"]
        errors = self.check()
        for field in ("environment.time", "environment.lighting", "entities.actor.position"):
            self.assertTrue(any(field + " 的变化未" in error for error in errors))
        link["changes"] = [{"field": field, "reason": "作者填写的具体变化理由。"}
                           for field in ("environment.time", "environment.lighting", "entities.actor.position")]
        self.assertEqual(self.check(), [])

    def test_missing_match_field_on_both_endpoints_is_not_equal(self):
        self.plan["links"][0]["match_fields"].append("entities.actor.costume_typo")
        self.assertTrue(any("两端缺失也不能视为相等" in error for error in self.check()))
        self.plan["links"][0]["match_fields"] = ["entities.absent.position"]
        self.assertTrue(any("不存在" in error for error in self.check()))

    def test_match_invariants_cannot_be_overridden_with_change_reasons(self):
        self.state["scenes"][1]["baseline"]["entities"]["actor"]["position"] = "window"
        self.rebind()
        self.plan["links"][0]["changes"] = [{"field": "entities.actor.position", "reason": "作者说明移动。"}]
        self.assertTrue(any("要求连续的 entities.actor.position 不一致" in error for error in self.check()))

    def test_added_removed_entities_can_be_explained_as_objects(self):
        self.state["scenes"][1]["baseline"]["entities"] = {"other": {"position": "door"}}
        self.rebind()
        link = self.plan["links"][0]
        link["match_fields"] = ["location_id"]
        self.assertTrue(any("变化未" in error for error in self.check()))
        link["changes"] = [{"field": "entities.actor", "reason": "作者说明离场。"},
                           {"field": "entities.other", "reason": "作者说明入场。"}]
        self.assertEqual(self.check(), [])
        link["changes"] = [{"field": "entities", "reason": "笼统理由不能掩盖不同字段。"}]
        self.assertTrue(any("须逐叶字段说明" in error for error in self.check()))

    def test_optional_environment_field_is_a_leaf_change_not_a_parent_change(self):
        for key in ("time", "weather", "lighting"):
            del self.state["scenes"][0]["baseline"][key]
            del self.state["scenes"][1]["baseline"][key]
        self.state["scenes"][1]["baseline"]["time"] = "night"
        self.rebind()
        link = self.plan["links"][0]
        link["match_fields"] = ["location_id"]
        self.assertTrue(any("environment.time 的变化未" in error for error in self.check()))
        link["changes"] = [{"field": "environment.time", "reason": "作者在后场明确时间。"}]
        self.assertEqual(self.check(), [])

    def test_ellipsis_and_location_change_explain_differences_without_equal_frames(self):
        self.state["scenes"][1]["location_id"] = "street"
        self.state["scenes"][1]["baseline"]["time"] = "morning"
        self.rebind()
        link = self.plan["links"][0]
        link["match_fields"] = ["entities.actor.position"]
        link["changes"] = [{"field": "location_id", "reason": "作者说明换场。"},
                           {"field": "environment.time", "reason": "作者说明时间省略。"}]
        self.assertTrue(any("地点改变须使用" in error for error in self.check()))
        for mode in ("ellipsis", "location_change"):
            with self.subTest(mode=mode):
                link["mode"] = mode
                self.assertEqual(self.check(), [])
        link["changes"] = []
        self.assertTrue(any("location_id 的变化未" in error for error in self.check()))

    def test_episode_scope_is_entire_bound_file(self):
        self.plan["units"] = [{**self.plan["units"][0], "id": "EP-001", "kind": "episode", "exit_shot": "B2"}]
        self.plan["links"] = []
        self.assertEqual(self.check(), [])
        self.plan["units"][0]["exit_shot"] = "A2"
        self.assertTrue(any("覆盖完整集状态文件" in error for error in self.check()))

    def test_reason_and_handoffs_are_required_and_stale_change_fields_rejected(self):
        for section, key in (("narrative", "carry"), ("narrative", "receive"),
                             ("audio", "strategy"), ("audio", "description")):
            with self.subTest(section=section, key=key):
                plan = copy.deepcopy(self.plan)
                plan["links"][0][section][key] = " "
                self.assertTrue(any(f"{section}.{key}" in error for error in S.sequence_errors(plan)))
        self.plan["links"][0]["changes"] = [{"field": "environment.time", "reason": "仍是同一时间。"},
                                             {"field": "entities.missing", "reason": "拼错字段。"}]
        errors = self.check()
        self.assertTrue(any("没有实际变化" in error for error in errors))
        self.assertTrue(any("在两个端点都不存在" in error for error in errors))

    def test_malformed_state_is_an_error_not_an_uncaught_exception(self):
        self.state["scenes"][0]["shots"][0]["changes"] = {"entities": []}
        self.rebind()
        self.assertTrue(any("无法绑定状态文件" in error for error in self.check()))

    def test_dotted_entity_ids_are_resolved_without_treating_them_as_objects(self):
        for scene in self.state["scenes"]:
            scene["baseline"]["entities"]["actor.v1"] = scene["baseline"]["entities"].pop("actor")
        self.state["scenes"][0]["shots"][1]["changes"]["entities"]["actor.v1"] = {"position": "door"}
        del self.state["scenes"][0]["shots"][1]["changes"]["entities"]["actor"]
        self.rebind()
        self.plan["links"][0]["match_fields"] = ["entities.actor.v1.position"]
        self.assertEqual(self.check(), [])

    def test_cli_validate_check_and_failure_exit_status(self):
        path = self.project / "sequence.json"
        path.write_text(json.dumps(self.plan, ensure_ascii=False), "utf-8")
        for args in (("validate", str(path)), ("check", str(path), "--project", str(self.project))):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_sequence.py"), *args],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("本检查不构成批准", result.stdout)
        self.state_path.unlink()
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_sequence.py"), "check", str(path),
                                 "--project", str(self.project)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("无法绑定状态文件", result.stderr)


if __name__ == "__main__":
    unittest.main()
