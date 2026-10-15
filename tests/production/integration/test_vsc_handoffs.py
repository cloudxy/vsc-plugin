#!/usr/bin/env python3
"""Synthetic fixtures exercise version/object/media seams; no creative approvals."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT
from support.fixtures.handoffs import Fixture
from vsc_handoffs import digest, project_errors, selections_for, validation_errors




class Handoffs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-handoffs-")
        self.f = Fixture(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_two_scene_handoffs(self):
        f = self.f
        for data, item in ((f.screenplay_data, f.screenplay), (f.coverage_data, f.coverage), (f.selected_data, f.selected), (f.timeline_data, f.timeline), (f.mix_data, f.mix), (f.manifest_data, f.manifest)):
            self.assertEqual(validation_errors(data), [])
            self.assertEqual(f.errors(data, item), [])

    def test_coverage_enumerates_real_object_tree(self):
        data = copy.deepcopy(self.f.coverage_data)
        data["scenes"].pop()
        errors = self.f.errors(data, self.f.coverage)
        for identifier in ("SC2", "SQ2", "SH2", "A2"):
            self.assertTrue(any(identifier in error for error in errors), errors)
        self.f.state["objects"].append({"id": "SH3", "kind": "shot", "parent": "SQ1"})
        self.assertTrue(any("SH3" in error for error in self.f.errors(self.f.coverage_data, self.f.coverage)))

    def test_omission_requires_matching_accepted_human_decision(self):
        data = copy.deepcopy(self.f.coverage_data)
        data["scenes"].pop()
        data["omissions"] = [{"object_id": "SC2", "decision_id": "D1"}]
        self.assertTrue(self.f.errors(data, self.f.coverage))
        self.f.state["decisions"].append({"id": "D1", "kind": "omission", "target": "SC2", "outcome": "accepted", "by": "synthetic fixture", "reason": "synthetic coverage fixture"})
        self.assertEqual(self.f.errors(data, self.f.coverage), [])
        self.f.state["decisions"][0]["target"] = "SC1"
        self.assertTrue(self.f.errors(data, self.f.coverage))

    def test_missing_dialogue_coverage_and_invalid_narrative_ref(self):
        data = copy.deepcopy(self.f.screenplay_data)
        data["scenes"][0]["dialogue"] = [{"id": "DL1", "speaker": "synthetic", "text": "test", "narrative_refs": ["missing"]}]
        self.assertTrue(any("missing" in e for e in self.f.errors(data, self.f.screenplay)))
        screenplay = self.f.register("vsc.screenplay", data, [self.f.adaptation])
        coverage = copy.deepcopy(self.f.coverage_data)
        coverage["screenplay"] = self.f.ref(screenplay)
        item = self.f.register("vsc.coverage_plan", coverage, [screenplay, *self.f.shots, *self.f.sounds])
        self.assertTrue(any("DL1" in e for e in self.f.errors(coverage, item)))

    def test_wrong_plan_sequence_dependency_and_hash(self):
        data = copy.deepcopy(self.f.coverage_data)
        data["scenes"][0]["sequences"][0]["shot_plan"] = self.f.ref(self.f.shots[1])
        self.assertTrue(any("不属于声明sequence" in e for e in self.f.errors(data, self.f.coverage)))
        self.f.coverage["depends_on"].remove(self.f.shots[0]["id"])
        self.assertTrue(any("明确依赖" in e for e in self.f.errors(self.f.coverage_data, self.f.coverage)))

    def test_unselected_and_wrong_take_are_blocked(self):
        data = copy.deepcopy(self.f.timeline_data)
        data["bindings"][0]["selected_item_id"] = "never-selected"
        self.assertTrue(any("获选item不存在" in e for e in self.f.errors(data, self.f.timeline)))
        data = copy.deepcopy(self.f.selected_data)
        data["items"][0]["take_id"] = "TK2"
        self.assertTrue(any("take不属于镜头" in e for e in self.f.errors(data, self.f.selected)))

    def test_media_drift_and_path_escape_are_blocked(self):
        (self.f.project / self.f.selected_data["items"][0]["media"]["path"]).write_bytes(b"changed")
        self.assertTrue(any("SHA漂移" in e for e in self.f.errors(self.f.timeline_data, self.f.timeline)))
        media = self.f.selected_data["items"][0]["media"]
        media["path"] = "../outside"
        self.assertTrue(validation_errors(self.f.selected_data))

    def test_generation_record_draft_can_be_selected_but_output_must_match(self):
        f = self.f
        data = copy.deepcopy(f.selected_data)
        row = data["items"][0]
        generation = f.register("vsc.generation_record", {"format": "vsc.generation-record/v1", "status": "succeeded", "shot_id": "SH1", "outputs": [dict(row["media"], id="OUT1")]}, status="draft")
        row["source"] = {"kind": "generation", "artifact": f.ref(generation)}
        next(o for o in f.state["objects"] if o["id"] == "TK1")["artifact"] = generation["id"]
        item = f.register("vsc.selected_takes", data, [generation, next(a for a in f.state["artifacts"] if a["id"] == data["items"][1]["source"]["artifact"]["id"])])
        self.assertEqual(f.errors(data, item), [])
        row["output_id"] = "OUT2"
        self.assertTrue(any("output_id" in e for e in f.errors(data, item)))

    def test_selection_order_is_irrelevant(self):
        before = selections_for(self.f.selected_data)
        self.f.selected_data["items"].reverse()
        self.assertEqual(selections_for(self.f.selected_data), before)
        duplicate = copy.deepcopy(self.f.selected_data["items"][0])
        duplicate["id"] = "another"
        self.f.selected_data["items"].append(duplicate)
        with self.assertRaises(ValueError):
            selections_for(self.f.selected_data)

    def test_audible_video_requires_cue_and_audio_role(self):
        data = copy.deepcopy(self.f.timeline_data)
        data["render_plan"]["segments"][0]["muted"] = False
        self.assertTrue(any("实际可听" in e for e in self.f.errors(data, self.f.timeline)))

    def test_mix_rejects_missing_cue_and_fake_l_cut(self):
        f = self.f
        sound = f.register("vsc.sound_plan", {"format": "vsc.sound-cue-sheet/v1", "sequence_id": "SQ1", "ambience_beds": [{"id": "AMB", "start_ms": 0, "end_ms": 1000}], "music_cues": [], "boundaries": [{"id": "B1", "from_shot": "SH1", "to_shot": "SH2", "strategy": "L_cut", "tail_ms": 400}]})
        data = copy.deepcopy(f.mix_data)
        data["sound_plans"] = [f.ref(sound)]
        item = f.register("vsc.mix", data, [f.timeline, sound])
        errors = f.errors(data, item)
        self.assertTrue(any("缺失计划Cue" in e for e in errors), errors)
        self.assertTrue(any("没有固定版本复核" in e for e in errors), errors)

    def test_mix_j_l_cuts_check_actual_audio_positions(self):
        f = self.f
        next(obj for obj in f.state["objects"] if obj["id"] == "SH2")["parent"] = "SQ1"
        for strategy in ("L_cut", "J_cut"):
            sound = f.register("vsc.sound_plan", {"format": "vsc.sound-cue-sheet/v1", "sequence_id": "SQ1", "ambience_beds": [{"id": "AMB", "start_ms": 0, "end_ms": 2000}], "music_cues": [], "boundaries": [{"id": "B1", "from_shot": "SH1", "to_shot": "SH2", "strategy": strategy, "tail_ms": 400, "ambience_bed_id": "AMB"}]})
            timeline_data = copy.deepcopy(f.timeline_data)
            timeline_data["render_plan"]["segments"].append({"id": "AUDIO", "kind": "audio", "source": "media/synthetic.wav", "from_frame": 0, "duration_in_frames": 48})
            timeline_data["bindings"].append({"segment_id": "AUDIO", "selected_item_id": "fixture-audio", "sha256": "f" * 64, "purpose": "ambience", "usage_rights": "owned", "audio_role": "ambience", "cue_id": "AMB"})
            timeline_data["sound_plans"] = [f.ref(sound)]
            timeline = f.register("vsc.timeline", timeline_data, [f.selected, sound])
            data = f.base("mix", timeline=f.ref(timeline), sound_plans=[f.ref(sound)], layers=[{"segment_id": "AUDIO", "cue_id": "AMB", "sound_plan": f.ref(sound), "audio_role": "ambience"}], boundaries=[{"boundary_id": "B1", "sound_plan": f.ref(sound), "segment_ids": ["AUDIO"], "result": "passed", "reviewed_by": "synthetic fixture", "evidence": "Synthetic frame placement; no real listening claim"}])
            mix = f.register("vsc.mix", data, [timeline, sound])
            self.assertEqual(f.errors(data, mix), [], strategy)
            audio = timeline_data["render_plan"]["segments"][-1]
            if strategy == "L_cut":
                audio["duration_in_frames"] = 24
            else:
                audio["from_frame"] = 24
                audio["duration_in_frames"] = 24
            changed = f.register("vsc.timeline", timeline_data, [f.selected, sound])
            data["timeline"] = f.ref(changed)
            mix = f.register("vsc.mix", data, [changed, sound])
            self.assertTrue(any("声明" + strategy in e for e in f.errors(data, mix)), strategy)

    def test_animatic_garbage_bytes_cannot_claim_playable_preview(self):
        f = self.f
        data = f.base("animatic", media=f.media("preview/garbage.mp4", b"not playable"), coverage_plan=f.ref(f.coverage), plans=[f.ref(f.shots[0])], temporary_audio=[], unresolved_issues=[])
        item = f.register("vsc.animatic", data, [f.coverage, f.shots[0]])
        self.assertTrue(any("无法完整播放验证" in e for e in f.errors(data, item)))

    def test_bad_subtitle_blocks_delivery(self):
        f = self.f
        subtitle = f.media("final/bad.srt", b"1\n00:00:03,000 --> 00:00:04,000\nBeyond film\n")
        data = copy.deepcopy(f.manifest_data)
        data["release_variants"][0]["subtitles"] = [subtitle]
        data["package_media"].append(dict(subtitle, usage_rights="owned", package_permission=True))
        self.assertTrue(any("字幕无效" in e for e in f.errors(data, f.manifest)))

    def test_delivery_wrong_qa_render_and_missing_episode(self):
        data = copy.deepcopy(self.f.manifest_data)
        data["release_variants"][0]["render"]["sha256"] = "f" * 64
        self.assertTrue(any("QA没有绑定" in e for e in self.f.errors(data, self.f.manifest)))
        self.f.state["objects"].append({"id": "EP2", "kind": "episode"})
        data = copy.deepcopy(self.f.manifest_data)
        data["scope"] = "project"
        self.f.manifest["scope"] = "project"
        self.assertTrue(any("EP2" in e for e in self.f.errors(data, self.f.manifest)))

    def test_templates_have_valid_minimum_structure(self):
        for name in ("screenplay", "coverage-plan", "selected-takes", "animatic", "timeline", "mix", "delivery-manifest"):
            data = json.loads((ROOT / "templates" / (name + ".json")).read_text("utf-8"))
            self.assertEqual(validation_errors(data), [], name)

    def test_malformed_fields_report_errors_and_temporary_rights_are_blocked(self):
        self.assertTrue(validation_errors({"format": {"unhashable": True}}))
        data = copy.deepcopy(self.f.timeline_data)
        data["bindings"][0]["audio_role"] = []
        self.assertTrue(validation_errors(data))
        data = copy.deepcopy(self.f.selected_data)
        data["items"][0]["usage_rights"] = "temp_only"
        self.assertTrue(any("temp_only" in e for e in validation_errors(data)))


if __name__ == "__main__":
    unittest.main()
