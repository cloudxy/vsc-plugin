"""Opt-in constraints and original subtitle compiler semantics."""
import copy
import unittest
from vsc.project.creative_rules import resolve_rules, rule_errors, document_diagnostics, context_diagnostics, visible_characters
from vsc.post import subtitles as S


class CreativeRulesTest(unittest.TestCase):
    def test_no_declaration_preserves_old_reading_and_display_behavior(self):
        text = "AI模型3.14万元，涨了5%！"
        result = S.compile_cues([(0, .01, text)])
        self.assertEqual(result["cues"][0][2], "AI模型3.14万元涨了5%")
        self.assertEqual(result["checks"]["reading_rules"], "not_declared")
        self.assertEqual(result["warnings"], [])

    def test_declared_cps_and_duration_boundaries_warnings_and_nonfinite(self):
        for key, limit, cue in (("max_cps", 3, (0, 1, "四个字啊")), ("min_cue_ms", 500, (0, .1, "字")), ("max_cue_ms", 500, (0, 1, "字"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                S.compile_cues([cue], rules={"subtitle": {key: {"value": limit, "level": "error"}}})
        warning = S.compile_cues([(0, 1, "四个字啊")], rules={"subtitle": {"max_cps": {"value": 3, "level": "warning"}}})
        self.assertTrue(warning["warnings"])
        self.assertEqual(warning["checks"]["reading_rules"], "warnings")
        self.assertEqual(S.compile_cues([(0, 1, "四个字啊")], rules={"subtitle": {"max_cps": {"value": 4, "level": "error"}}})["measurements"][0]["cps"], 4)
        with self.assertRaises(ValueError):
            S.compile_cues([(0, 0, "字")])
        self.assertTrue(rule_errors({"subtitle": {"max_cps": {"value": float("nan"), "level": "error"}}}))

    def test_mixed_spacing_is_derived_and_preserves_numeric_units(self):
        raw = "采用AI模型HTML5版本，3.14万元和20集涨5%。"
        expected = "采用 AI 模型 HTML5 版本3.14万元和20集涨5%"
        self.assertEqual(S.display_text(raw, mixed_spacing=True), expected)
        self.assertEqual(S.display_text(expected, mixed_spacing=True), expected)
        self.assertEqual(raw, "采用AI模型HTML5版本，3.14万元和20集涨5%。")
        self.assertEqual(visible_characters("e\u0301中A20!", punctuation=False), 5)

    def test_profile_then_brief_partial_override_and_invalid_safe_area(self):
        profile = {"creative_rules": {"subtitle": {"safe_area": {"bottom": .2}, "mixed_spacing": True}}}
        brief = {"creative_rules": {"subtitle": {"safe_area": {"right": .3}}}}
        rules = resolve_rules(profile, brief)
        self.assertEqual(rules["subtitle"]["safe_area"], {"bottom": .2, "right": .3})
        self.assertEqual(S.caption_top({"position": "bottom", "custom_position": 70}, 1000, 100, rules), 700)
        self.assertTrue(rule_errors({"subtitle": {"safe_area": {"top": .6, "bottom": .6}}}))
        self.assertTrue(rule_errors({"subtitle": {"safe_area": {"right": -1}}}))

    def test_stage_duration_uses_scene_budgets_and_final_composition_with_union(self):
        screenplay = {"format": "vsc.screenplay/v1", "scenes": [
            {"estimated_duration_ms": 1000, "dialogue": [{"id": "L", "text": "旁白并行", "duration_ms": 1000}]},
            {"estimated_duration_ms": 2000, "dialogue": []}]}
        self.assertEqual(document_diagnostics(screenplay, {"duration": {"target_ms": 3000}})["errors"], [])
        plan = {"format": "vsc.remotion-render-plan/v1", "composition": {"fps": 100, "duration_in_frames": 200}, "segments": [
            {"kind": "image", "from_frame": 0, "duration_in_frames": 100},
            {"kind": "image", "from_frame": 50, "duration_in_frames": 100},
            {"kind": "audio", "from_frame": 0, "duration_in_frames": 200}]}
        checked = document_diagnostics(plan, {"duration": {"target_ms": 2000, "tolerance_ms": 0}})
        self.assertEqual(checked["errors"], [])
        self.assertEqual(checked["metrics"]["visual_coverage_ms"], 1500)
        layered = dict(plan, segments=[*plan["segments"], {"kind": "image", "from_frame": 0, "duration_in_frames": 200, "overlay": {"alpha": .5}}])
        self.assertEqual(document_diagnostics(layered, {})["metrics"]["visual_coverage_ms"], 1500)
        self.assertEqual(checked["metrics"]["overlapping_visual_ms"], 500)
        self.assertEqual(checked["metrics"]["uncovered_visual_ms"], 500)
        shots = {"format": "vsc.continuity-plan/v1", "shots": [{"duration_ms": 1000}]}
        self.assertFalse(document_diagnostics(shots, {"duration": {"target_ms": 2000}})["errors"])
        self.assertTrue(document_diagnostics(shots, {"duration": {"target_ms": 2000}})["warnings"])

    def test_unapproved_or_unpinned_brief_cannot_supply_current_scope_rules(self):
        objects = [{"id": "EP1", "kind": "episode"}, {"id": "EP2", "kind": "episode"},
                   {"id": "SC1", "kind": "scene", "parent": "EP1"}]
        data = {"format": "vsc.screenplay/v1", "project_id": "P", "scope": "EP1",
            "scenes": [{"id": "SC1", "estimated_duration_ms": 1000, "dialogue": [{"id": "L", "text": "你好12"}]}]}
        brief = {"id": "BR", "type": "vsc.creative_brief", "status": "draft", "scope": "EP1", "sha256": "a" * 64,
            "document": {"creative_rules": {"duration": {"target_ms": 2000}, "line_length": {"max_characters": 2, "level": "error"}}}}
        self.assertEqual(context_diagnostics(data, {}, [brief], {"BR"}, "EP1", objects)["errors"], [])
        brief["status"] = "approved"
        self.assertTrue(context_diagnostics(data, {}, [brief], set(), "EP1", objects)["errors"])
        checked = context_diagnostics(data, {}, [brief], {"BR"}, "EP1", objects)
        self.assertTrue(any("字数" in row for row in checked["errors"]))
        self.assertTrue(any("时长" in row for row in checked["errors"]))
        self.assertEqual(context_diagnostics(data, {}, [dict(brief, scope="EP2")], {"BR"}, "EP1", objects)["errors"], [])

    def test_risk_ids_use_one_fixed_quality_plan_and_scope(self):
        objects = [{"id": "EP1", "kind": "episode"}, {"id": "EP2", "kind": "episode"},
            {"id": "SQ", "kind": "sequence", "parent": "EP1"}, {"id": "SH", "kind": "shot", "parent": "SQ"}]
        quality = {"id": "Q", "type": "vsc.quality_plan", "status": "approved", "scope": "project", "sha256": "a" * 64,
            "document": {"format": "vsc.quality-plan/v1", "project_id": "P", "risks": [
                {"id": "R", "hypothesis": "bounded action", "stop_condition": "two attempts", "scope": "EP1", "shot_ids": ["SH"]}]}}
        data = {"format": "vsc.continuity-plan/v1", "project_id": "P", "sequence_id": "SQ",
            "quality_plan": {"id": "Q", "sha256": "a" * 64}, "shots": [{"id": "SH", "duration_ms": 1000, "risk_ids": ["R"]}]}
        self.assertEqual(context_diagnostics(data, {}, [quality], {"Q"}, "EP1", objects)["errors"], [])
        other = copy.deepcopy(quality); other["document"]["risks"][0]["scope"] = "EP2"
        self.assertTrue(context_diagnostics(data, {}, [other], {"Q"}, "EP1", objects)["errors"])
        self.assertTrue(context_diagnostics(data, {}, [quality], set(), "EP1", objects)["errors"])
        data["shots"][0]["risks"] = [{"id": "R"}]
        self.assertTrue(context_diagnostics(data, {}, [quality], {"Q"}, "EP1", objects)["errors"])

    def test_malformed_declared_brief_and_risk_scope_return_diagnostics(self):
        for data in ({"format": "vsc.creative-brief/v1", "creative_rules": {"duration": []}},
            {"format": "vsc.quality-plan/v1", "project_id": "P", "risks": [{"id": "R",
                "hypothesis": "fixture", "stop_condition": "fixture", "scope": {"invalid": "object"}}]}):
            self.assertTrue(context_diagnostics(data, {}, [], set(), "project", [])["errors"])
