#!/usr/bin/env python3
"""章节衔接作为登记产物时必须绑定真实对象与明确状态版本。"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
import vsc_artifacts as A


class SequenceArtifactTest(unittest.TestCase):
    def test_requires_explicit_state_dependency_and_rechecks_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            timeline = json.loads((ROOT / "templates/scene-state.json").read_text("utf-8"))
            timeline["project_id"] = "p"
            state_path = project / "状态.json"
            state_path.write_text(json.dumps(timeline), "utf-8")
            shots = [s["id"] for sc in timeline["scenes"] for s in sc["shots"]]
            plan = {"format": "vsc.sequence-links/v1", "project_id": "p", "units": [
                {"id": "EP-001", "kind": "episode", "state_path": "状态.json", "state_sha256": A.digest(state_path),
                 "entry_shot": shots[0], "exit_shot": shots[-1]}], "links": []}
            (project / "衔接.json").write_text(json.dumps(plan), "utf-8")
            objects = [{"id": "EP-001", "kind": "episode"}, {"id": "SC-001", "kind": "scene", "parent": "EP-001"},
                       {"id": "SEQ-001", "kind": "sequence", "parent": "SC-001"}]
            objects += [{"id": shot, "kind": "shot", "parent": "SEQ-001"} for shot in shots]
            state = {"project_id": "p", "objects": objects, "artifacts": [
                {"id": "A-001", "type": "vsc.scene_state", "path": "状态.json", "sha256": A.digest(state_path)}]}
            (project / "vsc.json").write_text(json.dumps(state), "utf-8")
            item = {"type": "vsc.sequence_links", "path": "衔接.json", "depends_on": []}
            self.assertTrue(any("必须依赖" in e for e in A.reference_errors(project, state, item)))
            item["depends_on"] = ["A-001"]
            self.assertEqual(A.reference_errors(project, state, item), [])
            foreign = copy.deepcopy(state)
            foreign["objects"][-1]["parent"] = "other-sequence"
            self.assertTrue(any("不属于单元" in e for e in A.reference_errors(project, foreign, item)))
            state_path.write_text(json.dumps(timeline, indent=2), "utf-8")
            self.assertTrue(any("漂移" in e for e in A.reference_errors(project, state, item)))


if __name__ == "__main__":
    unittest.main()
