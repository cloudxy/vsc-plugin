#!/usr/bin/env python3
"""Synthetic two-person speech with actual decoded WAVs; no listening approval."""
import copy
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from support.paths import ROOT
from support.fixtures.handoffs import Fixture
from vsc.production.handoffs import digest, project_errors
from vsc.story.performance import project_sound_errors, timeline_performance_errors


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg")
class Performance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-performance-")
        self.f = Fixture(self.temp.name)
        f = self.f
        self.screenplay_data = copy.deepcopy(f.screenplay_data)
        self.screenplay_data["scenes"][0]["dialogue"] = [
            {"id": "DL1", "speaker": "ALICE", "text": "Synthetic line one.", "narrative_refs": ["N1"]},
            {"id": "DL2", "speaker": "BOB", "text": "Synthetic line two.", "narrative_refs": ["N1"]}]
        self.screenplay = f.register("vsc.screenplay", self.screenplay_data, [f.adaptation])
        self.sound_data = {"format": "vsc.sound-cue-sheet/v1", "project_id": "synthetic", "sequence_id": "SQ1", "duration_ms": 2000, "ambience_beds": [], "music_cues": [], "boundaries": [], "dialogue_cues": [
            {"id": "D1", "line_id": "DL1", "text": "Synthetic line one.", "speaker": "ALICE", "start_ms": 0, "end_ms": 500, "acting_choice": "Synthetic restrained reading", "lip_sync_intent": "offscreen"},
            {"id": "D2", "line_id": "DL2", "text": "Synthetic line two.", "speaker": "BOB", "start_ms": 750, "end_ms": 1500, "acting_choice": "Synthetic calm response", "lip_sync_intent": "offscreen"}]}
        self.sound = f.register("vsc.sound_plan", self.sound_data, [self.screenplay])
        self.selected_data = copy.deepcopy(f.selected_data)
        self.sources = [next(a for a in f.state["artifacts"] if a["id"] == row["source"]["artifact"]["id"]) for row in self.selected_data["items"]]
        for n, duration in ((1, 0.5), (2, 0.75)):
            path = f.project / f"audio/line-{n}.wav"
            path.parent.mkdir(exist_ok=True)
            rate = 24000
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(rate)
                audio.writeframes(b"".join(struct.pack("<h", round(2000 * math.sin(2 * math.pi * (440 + n * 100) * i / rate))) for i in range(round(duration * rate))))
            media = {"path": path.relative_to(f.project).as_posix(), "sha256": digest(path)}
            source = f.register("vsc.audio_take", path.read_bytes())
            self.sources.append(source)
            f.state["objects"].append({"id": f"ATK{n}", "kind": "take", "parent": "SH1", "artifact": source["id"]})
            cue = self.sound_data["dialogue_cues"][n-1]
            performance = {key: cue[key] for key in ("line_id", "text", "speaker", "acting_choice", "lip_sync_intent")}
            performance.update(reviewed_by="synthetic fixture", measured_duration_seconds=duration)
            self.selected_data["items"].append({"id": f"AS{n}", "shot_id": "SH1", "cue_id": f"D{n}", "take_id": f"ATK{n}", "output_id": f"AO{n}", "scope": "EP", "purpose": "dialogue", "usage_rights": "owned", "selected_by": "synthetic fixture", "media": media, "performance": performance,
                                                "source": {"kind": "manual", "artifact": f.ref(source), "imported_by": "synthetic fixture", "provenance": "Synthetic sine tone; no intelligibility claim"}})
        self.selected = f.register("vsc.selected_takes", self.selected_data, self.sources)
        self.timeline_data = copy.deepcopy(f.timeline_data)
        self.timeline_data["selected_takes"] = f.ref(self.selected)
        self.timeline_data["sound_plans"] = [f.ref(self.sound)]
        for n, start, duration in ((1, 0, 12), (2, 18, 18)):
            row = self.selected_data["items"][n+1]
            self.timeline_data["render_plan"]["segments"].append({"id": f"A{n}", "kind": "audio", "source": row["media"]["path"], "from_frame": start, "duration_in_frames": duration})
            self.timeline_data["bindings"].append({"segment_id": f"A{n}", "selected_item_id": row["id"], "sha256": row["media"]["sha256"], "cue_id": f"D{n}", "purpose": "dialogue", "usage_rights": "owned", "audio_role": "dialogue"})
        self.timeline = f.register("vsc.timeline", self.timeline_data, [self.selected, self.sound])

    def tearDown(self):
        self.temp.cleanup()

    def refresh(self):
        f = self.f
        self.selected = f.register("vsc.selected_takes", self.selected_data, self.sources)
        self.timeline_data["selected_takes"] = f.ref(self.selected)
        self.timeline_data["sound_plans"] = [f.ref(self.sound)]
        self.timeline = f.register("vsc.timeline", self.timeline_data, [self.selected, self.sound])

    def errors(self):
        return project_errors(self.timeline_data, self.f.project, self.f.state, self.timeline)

    def generated(self):
        f = self.f
        self.sources = self.sources[:2]
        self.records = []
        for n in (1, 2):
            row = self.selected_data["items"][n+1]
            performance = {key: row["performance"][key] for key in ("line_id", "acting_choice", "lip_sync_intent", "measured_duration_seconds")}
            inputs = {key: performance[key] for key in ("line_id", "acting_choice", "lip_sync_intent")}
            inputs.update(text=row["performance"]["text"], entity=row["performance"]["speaker"], speaker="provider-voice-id",
                          screenplay={"path": self.screenplay["path"], "sha256": self.screenplay["sha256"]})
            record_data = {"format": "vsc.generation-record/v1", "project_id": "synthetic", "kind": "audio", "status": "succeeded", "shot_id": "SH1", "inputs": inputs, "outputs": [dict(row["media"], id=row["output_id"], performance=performance, entity=inputs["entity"])]}
            record = f.register("vsc.generation_record", record_data, status="draft")
            self.records.append((record, record_data))
            self.sources.append(record)
            row["source"] = {"kind": "generation", "artifact": f.ref(record)}
            next(o for o in f.state["objects"] if o["id"] == row["take_id"])["artifact"] = record["id"]
        self.refresh()

    def test_two_manual_speakers_have_matching_real_durations(self):
        self.assertEqual(project_sound_errors(self.sound_data, self.f.project, self.f.state, self.sound), [])
        self.assertEqual(self.errors(), [])

    def repeat_first_audio(self, start=0, **declaration):
        original = next(row for row in self.timeline_data["bindings"] if row["segment_id"] == "A1")
        binding = dict(original, segment_id="A1-replay", **declaration)
        segment = next(row for row in self.timeline_data["render_plan"]["segments"] if row["id"] == "A1")
        self.timeline_data["bindings"].append(binding)
        self.timeline_data["render_plan"]["segments"].append(dict(segment, id=binding["segment_id"], from_frame=start))
        self.refresh()
        return binding

    def test_overlapping_duplicate_cannot_be_excused_by_declaration_or_output_label(self):
        binding = self.repeat_first_audio()
        for changes in ({}, {"output_id": "unvalidated-output"}, {"reuse_declared": "false"},
                        {"reuse_declared": True}, {"reuse_declared": True, "reuse_reason": "intentional replay"}):
            with self.subTest(changes=changes):
                for field in ("output_id", "reuse_declared", "reuse_reason"):
                    binding.pop(field, None)
                binding.update(changes)
                self.assertTrue(self.errors())  # Actual timeline consumer, with fixed selected dependencies.
                errors = timeline_performance_errors(self.timeline_data, self.f.project, self.f.state, self.timeline)
                self.assertTrue(any("重复绑定" in error for error in errors), errors)
                if "output_id" in changes:
                    self.assertTrue(any("output_id" in error for error in errors), errors)
                if changes.get("reuse_declared") == "false":
                    self.assertTrue(any("boolean" in error for error in errors), errors)
                if changes == {"reuse_declared": True}:
                    self.assertTrue(any("reuse_reason" in error for error in errors), errors)

    def test_nonoverlapping_intentional_replay_requires_boolean_and_reason(self):
        binding = self.repeat_first_audio(start=36)
        for declaration in ({}, {"reuse_declared": "false", "reuse_reason": "replay"},
                            {"reuse_declared": 1, "reuse_reason": "replay"},
                            {"reuse_declared": None, "reuse_reason": "replay"},
                            {"reuse_declared": True}, {"reuse_declared": True, "reuse_reason": "  "}):
            with self.subTest(declaration=declaration):
                binding.pop("reuse_declared", None)
                binding.pop("reuse_reason", None)
                binding.update(declaration)
                self.assertTrue(self.errors())
        binding.update(reuse_declared=True, reuse_reason="Intentional audible flashback after the response")
        self.assertEqual(self.errors(), [])
        binding["output_id"] = "AO1"
        self.assertEqual(self.errors(), [])

    def test_generated_output_label_cannot_change_fixed_media_identity(self):
        self.generated()
        binding = self.repeat_first_audio(output_id="AO1")
        self.assertTrue(any("重复绑定" in error for error in self.errors()))
        binding["output_id"] = "invented-output"
        errors = self.errors()
        for marker in ("重复绑定", "output_id"):
            self.assertTrue(any(marker in error for error in errors), errors)

    def test_selected_item_alias_cannot_hide_repeated_media(self):
        binding = self.repeat_first_audio()
        original = self.selected_data["items"][2]
        alias = copy.deepcopy(original)
        alias.update(id="AS1-alias", output_id="another-label", shot_id=None)
        self.selected_data["items"].append(alias)
        binding.update(selected_item_id=alias["id"], output_id=alias["output_id"])
        self.refresh()
        errors = self.errors()
        self.assertTrue(any("重复绑定" in error for error in errors), errors)

    def test_one_audio_interval_can_bridge_three_visual_shots(self):
        first = self.timeline_data["render_plan"]["segments"].pop(0)
        binding = self.timeline_data["bindings"].pop(0)
        for index, start, duration in ((1, 0, 4), (2, 4, 4), (3, 8, 16)):
            identifier = "V1-" + str(index)
            self.timeline_data["render_plan"]["segments"].append(dict(first, id=identifier, from_frame=start,
                                                                    source_in_frame=start, duration_in_frames=duration))
            self.timeline_data["bindings"].append(dict(binding, segment_id=identifier))
        self.refresh()
        self.assertEqual(self.errors(), [])

    def test_silent_plan_and_silent_timeline_add_no_dialogue_requirements(self):
        self.assertEqual(project_sound_errors({"dialogue_cues": []}, self.f.project, self.f.state, {}), [])
        self.assertEqual(timeline_performance_errors(self.f.timeline_data, self.f.project, self.f.state, self.f.timeline), [])

    def test_cue_requires_real_line_exact_text_actor_and_acting_intent(self):
        for key, value in (("line_id", "MISSING"), ("text", "Changed text"), ("speaker", "OTHER"), ("acting_choice", ""), ("lip_sync_intent", "guess")):
            data = copy.deepcopy(self.sound_data)
            data["dialogue_cues"][0][key] = value
            self.assertTrue(project_sound_errors(data, self.f.project, self.f.state, self.sound), key)

    def test_strict_artifact_runtime_calls_spoken_line_contract(self):
        from vsc.project.artifacts import reference_errors
        self.f.state["profile_snapshot"] = {"contract_policy": "production-v2"}
        self.assertEqual(reference_errors(self.f.project, self.f.state, self.sound), [])
        data = copy.deepcopy(self.sound_data)
        data["dialogue_cues"][0]["speaker"] = "OTHER"
        broken = self.f.register("vsc.sound_plan", data, [self.screenplay])
        errors = reference_errors(self.f.project, self.f.state, broken)
        self.assertTrue(any("speaker" in e for e in errors), errors)

    def test_new_screenplay_version_changes_spoken_line_consumer(self):
        changed = copy.deepcopy(self.screenplay_data)
        changed["scenes"][0]["dialogue"][0]["text"] = "Revised synthetic line."
        screenplay = self.f.register("vsc.screenplay", changed, [self.f.adaptation])
        sound = self.f.register("vsc.sound_plan", self.sound_data, [screenplay])
        errors = project_sound_errors(self.sound_data, self.f.project, self.f.state, sound)
        self.assertTrue(any("text" in e for e in errors), errors)
        self.assertEqual(project_sound_errors({"dialogue_cues": []}, self.f.project, self.f.state, sound), [])

    def test_manual_reviewer_and_measured_duration_are_required(self):
        row = self.selected_data["items"][2]
        row["performance"].pop("reviewed_by")
        row["performance"]["measured_duration_seconds"] = 1.25
        self.refresh()
        errors = self.errors()
        self.assertTrue(any("reviewed_by" in e for e in errors), errors)
        self.assertTrue(any("真实媒体不一致" in e for e in errors), errors)

    def test_acting_lip_intent_and_allocated_line_duration_must_match(self):
        row = self.selected_data["items"][2]
        row["performance"]["acting_choice"] = "Different delivery"
        row["performance"]["lip_sync_intent"] = "required"
        self.timeline_data["render_plan"]["segments"][-2]["duration_in_frames"] = 6
        self.refresh()
        errors = self.errors()
        for marker in ("acting_choice", "lip_sync_intent", "完整对白实测时长"):
            self.assertTrue(any(marker in e for e in errors), errors)

    def test_tts_character_uses_entity_not_provider_voice_id(self):
        self.generated()
        self.assertEqual(self.errors(), [])
        record, data = self.records[0]
        data["inputs"].pop("entity")
        data["outputs"][0].pop("entity")
        changed = self.f.register("vsc.generation_record", data, status="draft")
        self.sources[2] = changed
        self.selected_data["items"][2]["source"]["artifact"] = self.f.ref(changed)
        next(o for o in self.f.state["objects"] if o["id"] == "ATK1")["artifact"] = changed["id"]
        self.refresh()
        self.assertTrue(any("entity映射" in e for e in self.errors()))

    def test_tts_fixed_script_sha_input_text_and_performance_must_agree(self):
        self.generated()
        record, data = self.records[0]
        data["inputs"]["screenplay"]["sha256"] = "f" * 64
        data["inputs"]["text"] = "Different source text"
        data["outputs"][0]["performance"]["acting_choice"] = "Different output acting"
        changed = self.f.register("vsc.generation_record", data, status="draft")
        self.sources[2] = changed
        self.selected_data["items"][2]["source"]["artifact"] = self.f.ref(changed)
        next(o for o in self.f.state["objects"] if o["id"] == "ATK1")["artifact"] = changed["id"]
        self.refresh()
        errors = self.errors()
        for marker in ("screenplay SHA", "文本/人物speaker", "输入/output"):
            self.assertTrue(any(marker in e for e in errors), errors)

    def test_narration_requires_explicit_voiceover_route(self):
        self.timeline_data["bindings"][-2]["audio_role"] = "narration"
        self.assertTrue(any("voiceover" in e for e in self.errors()))

    def test_native_video_requires_named_line_bindings_and_real_audio(self):
        f = self.f
        native = f.project / "media/native.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(native)], check=True, capture_output=True, timeout=30)
        media = {"path": native.relative_to(f.project).as_posix(), "sha256": digest(native)}
        imported = f.register("vsc.video_take", native.read_bytes())
        self.sources[0] = imported
        self.selected_data["items"][0]["media"] = media
        self.selected_data["items"][0]["source"]["artifact"] = f.ref(imported)
        next(o for o in f.state["objects"] if o["id"] == "TK1")["artifact"] = imported["id"]
        self.sound_data["dialogue_cues"] = [dict(self.sound_data["dialogue_cues"][0], end_ms=2000, line_ids=["DL1", "DL2"], native_approved_by="synthetic fixture")]
        self.sound = f.register("vsc.sound_plan", self.sound_data, [self.screenplay])
        self.timeline_data["render_plan"]["segments"] = [dict(self.timeline_data["render_plan"]["segments"][0], source=media["path"], duration_in_frames=48, muted=False)]
        self.timeline_data["bindings"] = [dict(self.timeline_data["bindings"][0], sha256=media["sha256"], audio_role="native", cue_id="D1")]
        self.refresh()
        self.assertEqual(self.errors(), [])
        self.sound_data["dialogue_cues"][0].pop("native_approved_by")
        self.sound = f.register("vsc.sound_plan", self.sound_data, [self.screenplay])
        self.refresh()
        self.assertTrue(any("native_approved_by" in e for e in self.errors()))


if __name__ == "__main__":
    unittest.main()
