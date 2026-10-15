#!/usr/bin/env python3
"""Default strict Profile through real CLIs and synthetic media; no creative claims."""
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from support.paths import ROOT
import vsc_state
from media_qa import LocalProbeAdapter, REVIEW_CATEGORIES, check_plan
from vsc_delivery import build_bundle, verify_bundle
from vsc_handoffs import digest, project_errors

CLI = ROOT / "scripts/vsc_state.py"


class StrictPipeline:
    def __init__(self, root):
        self.root, self.project = Path(root), Path(root) / "project"
        self.number = 0
        self.ok("init", self.project, "--title", "Synthetic strict workflow", "--owner", "synthetic fixture")
        self.project_id = self.state()["project_id"]

    def run(self, *args):
        return subprocess.run([sys.executable, "-B", str(CLI), *map(str, args)], capture_output=True, text=True, timeout=120)

    def ok(self, *args):
        result = self.run(*args)
        if result.returncode:
            raise AssertionError("CLI failed: " + " ".join(map(str, args)) + "\n" + result.stdout + result.stderr)
        return result.stdout

    def state(self):
        return json.loads((self.project / "vsc.json").read_text("utf-8"))

    def document(self, name, **fields):
        return {"format": f"vsc.{name}/v1", "project_id": self.project_id, "scope": "project", **fields}

    def add(self, kind, stage, value, depends=(), approve=True):
        self.number += 1
        if isinstance(value, Path):
            path = value
        else:
            path = self.root / f"input-{self.number}.json"
            path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
        identifier = self.ok("artifact", "add", self.project, "--type", kind, "--stage", stage, "--file", path,
                             *[arg for x in depends for arg in ("--depends", x["id"])]).split()[1]
        if approve:
            self.ok("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "synthetic fixture")
        return next(row for row in self.state()["artifacts"] if row["id"] == identifier)

    @staticmethod
    def ref(item):
        return {"id": item["id"], "sha256": item["sha256"]}

    def object(self, kind, identifier, parent=None, artifact=None):
        self.ok("object", "add", self.project, "--kind", kind, "--id", identifier,
                *(["--parent", parent] if parent else []), *(["--artifact", artifact["id"]] if artifact else []))

    def gate(self, stage):
        self.ok("gate", "check", self.project, stage)

    def build(self):
        self.object("episode", "EP")
        for n in (1, 2):
            self.object("scene", f"SC{n}", "EP")
            self.object("sequence", f"SQ{n}", f"SC{n}")
            self.object("shot", f"SH{n}", f"SQ{n}")
        brief_data = json.loads((ROOT / "templates/creative-brief.json").read_text("utf-8"))
        brief_data.update(audience="Synthetic test viewers", desired_experience="Recognize a synthetic completed action", decision_owner="synthetic fixture")
        brief = self.add("vsc.creative_brief", "brief", brief_data)
        self.gate("brief")
        source_file = self.root / "source.txt"
        source_file.write_text("Synthetic action one.\nSynthetic action two.\n", "utf-8")
        self.ok("source", "add", self.project, "--kind", "original", "--file", source_file, "--rights", "owned")
        source = self.state()["sources"][0]
        source_units = [{"id": f"N{n}", "source_id": source["id"], "source_sha256": source["sha256"],
                         "locator": {"kind": "lines", "start": n, "end": n}, "claim_kind": "fact",
                         "fact_or_claim": f"Synthetic source action {n}", "narrative_function": "Synthetic action coverage"} for n in (1, 2)]
        source_map = self.add("vsc.source_map", "source", {"format": "vsc.source-map/v1", "summary": "Two synthetic scene actions", "source_units": source_units}, [brief])
        self.gate("source")
        self.adaptation_data = {"format": "vsc.adaptation-map/v1", "project_id": self.project_id, "source_units": source_units,
            "episodes": [{"id": "EP", "logline": "A synthetic action is completed", "opening_hook": "Synthetic action begins", "ending_function": "closure", "ending": "The action finishes"}],
            "screen_units": [{"id": f"CU{n}", "episode_id": "EP", "scene_id": f"SC{n}", "source_refs": [f"N{n}"], "origin": "source", "visible_action": f"Synthetic action {n}", "character_goal": "Complete action", "obstacle": "Synthetic obstacle", "turn": "Synthetic change", "audience_information": "The synthetic action has changed"} for n in (1, 2)]}
        adaptation = self.add("vsc.adaptation_plan", "adaptation", self.adaptation_data, [source_map])
        beats = self.add("vsc.episode_beats", "adaptation", {"format": "vsc.episode-beats/v1", "episodes": [{"id": "EP", "ending_function": "closure", "ending": "Synthetic completed action", "beats": [{"id": f"B{n}", "action": "Synthetic action", "change": "Synthetic change", "screen_unit_ids": [f"CU{n}"]} for n in (1, 2)]}]}, [adaptation])
        self.gate("adaptation")
        self.screenplay_data = self.document("screenplay", body="Synthetic two-scene text", adaptation_refs=[self.ref(adaptation)], scenes=[{"id": f"SC{n}", "estimated_duration_ms": 1000, "actions": [{"id": f"ACT{n}", "text": "Synthetic visible action", "narrative_refs": [f"CU{n}"]}], "dialogue": [], "silence": []} for n in (1, 2)])
        self.screenplay = self.add("vsc.screenplay", "script", self.screenplay_data, [adaptation, beats])
        self.gate("script")
        self.add("vsc.visual_bible", "design", {"format": "vsc.visual-bible/v1", "intent": "Synthetic plain geometry", "lighting": "Even synthetic light", "composition": "Centered synthetic action", "palette": ["black"]}, [self.screenplay])
        bible = self.add("vsc.asset_bible", "design", {"format": "vsc.asset-bible/v1", "project_id": self.project_id, "entities": [{"id": "LOC", "kind": "location", "name": "Synthetic location", "identity": ["Plain black field"], "variants": {"default": "Synthetic default"}, "references": []}]}, [self.screenplay])
        self.object("asset", "LOC", artifact=bible)
        shots, sounds = [], []
        for n in (1, 2):
            state = {"scene_id": f"SC{n}", "location_id": "LOC", "time_state": "synthetic-time", "lighting_id": "synthetic-light", "soundscape_id": "synthetic-silence", "characters": {"none": "Synthetic geometry"}, "camera": {"framing": "wide", "motion": "static", "screen_direction": "none"}}
            shots.append(self.add("vsc.shot_plan", "design", {"format": "vsc.continuity-plan/v1", "project_id": self.project_id, "sequence_id": f"SQ{n}", "max_clip_ms": 2000, "shots": [{"id": f"SH{n}", "duration_ms": 1000, "reference_asset_ids": ["LOC"], "handles": {"head_ms": 0, "tail_ms": 0}, "entry_state": state, "exit_state": state}]}, [self.screenplay, bible]))
            sounds.append(self.add("vsc.sound_plan", "design", {"format": "vsc.sound-cue-sheet/v1", "project_id": self.project_id, "sequence_id": f"SQ{n}", "duration_ms": 1000, "ambience_beds": [], "music_cues": [], "boundaries": []}, [self.screenplay]))
        self.coverage_data = self.document("coverage-plan", screenplay=self.ref(self.screenplay), omissions=[], scenes=[{"id": f"SC{n}", "sequences": [{"id": f"SQ{n}", "shot_plan": self.ref(shots[n-1]), "sound_plan": self.ref(sounds[n-1]), "shots": [{"id": f"SH{n}", "screenplay_unit_ids": [f"ACT{n}"]}]}]} for n in (1, 2)])
        incomplete = copy.deepcopy(self.coverage_data)
        incomplete["scenes"].pop()
        rejected = self.add("vsc.coverage_plan", "design", incomplete, [self.screenplay, *shots, *sounds], approve=False)
        failed = self.run("artifact", "decide", self.project, rejected["id"], "--status", "approved", "--by", "synthetic fixture")
        if failed.returncode == 0 or "SC2" not in failed.stderr + failed.stdout:
            raise AssertionError("Incomplete two-scene coverage was not rejected: " + failed.stdout + failed.stderr)
        self.coverage = self.add("vsc.coverage_plan", "design", self.coverage_data, [self.screenplay, *shots, *sounds])
        self.gate("design")
        self.media_path = self.project / "media/synthetic.mp4"
        self.media_path.parent.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=24", "-t", "2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.media_path)], check=True, capture_output=True, timeout=30)
        media = {"path": self.media_path.relative_to(self.project).as_posix(), "sha256": digest(self.media_path)}
        animatic = self.add("vsc.animatic", "animatic", self.document("animatic", media=media, coverage_plan=self.ref(self.coverage), plans=[self.ref(shots[0])], temporary_audio=[], unresolved_issues=[]), [self.coverage, bible, shots[0]])
        self.gate("animatic")
        imported = self.add("vsc.video_take", "production", self.media_path)
        self.selected_data = self.document("selected-takes", items=[])
        for n in (1, 2):
            self.object("take", f"TK{n}", f"SH{n}", imported)
            self.selected_data["items"].append({"id": f"SEL{n}", "shot_id": f"SH{n}", "take_id": f"TK{n}", "output_id": f"OUT{n}", "scope": "project", "purpose": "visual", "usage_rights": "owned", "selected_by": "synthetic fixture", "media": media, "source": {"kind": "manual", "artifact": self.ref(imported), "imported_by": "synthetic fixture", "provenance": "Locally generated synthetic color field"}})
        self.selected = self.add("vsc.selected_takes", "production", self.selected_data, [animatic, imported])
        self.gate("production")
        self.timeline_data = self.document("timeline", selected_takes=self.ref(self.selected), sound_plans=[], render_plan={"format": "vsc.remotion-render-plan/v1", "project_id": self.project_id, "composition": {"id": "Synthetic", "width": 320, "height": 240, "fps": 24, "duration_in_frames": 48}, "segments": [{"id": f"V{n}", "kind": "video", "source": media["path"], "source_shot_id": f"SH{n}", "from_frame": (n-1)*24, "duration_in_frames": 24, "muted": True} for n in (1, 2)]}, bindings=[{"segment_id": f"V{n}", "selected_item_id": f"SEL{n}", "sha256": media["sha256"], "purpose": "visual", "usage_rights": "owned", "audio_role": "none", "cue_id": None} for n in (1, 2)])
        self.timeline = self.add("vsc.timeline", "post", self.timeline_data, [self.selected])
        self.mix = self.add("vsc.mix", "post", self.document("mix", timeline=self.ref(self.timeline), sound_plans=[self.ref(s) for s in sounds], layers=[], boundaries=[]), [self.timeline, *sounds])
        self.gate("post")
        self.qa_data = check_plan(self.project / self.timeline["path"], self.project, LocalProbeAdapter(), self.media_path)
        self.qa = self.add("vsc.media_qa", "delivery", self.qa_data, [self.timeline, self.mix])
        qa_source = self.root / "review-qa.json"
        qa_source.write_text(json.dumps(self.qa_data, ensure_ascii=False), "utf-8")
        self.review_data = {"format": "vsc.sample-review/v1", "project_id": self.project_id, "reviewer": "synthetic fixture", "technical_report": str(qa_source), "technical_report_sha256": self.qa["sha256"], "evidence_mode": "structured", "render_sha256": media["sha256"], "scope": {"kind": "complete", "start_frame": 0, "end_frame": 48, "delivery_id": "SYNTHETIC-DELIVERY"}, "assessments": {key: {"result": "pass", "evidence": [{"start_frame": 0, "end_frame": 24, "segment_id": "V1", "shot_id": "SH1", "note": "Synthetic fixture only; no real creative acceptance"}]} for key in REVIEW_CATEGORIES}, "run": {"elapsed_seconds": 1, "cost_amount": 0, "currency": "CNY", "failures": []}}
        self.review = self.add("vsc.sample_review", "delivery", self.review_data, [self.qa])
        self.manifest_data = self.document("delivery-manifest", delivery_id="SYNTHETIC-DELIVERY", release_variants=[{"id": "master", "scope": "project", "render": media, "subtitles": [], "timeline": self.ref(self.timeline), "mix": self.ref(self.mix), "qa": self.ref(self.qa), "reviews": [self.ref(self.review)], "specification": {key: self.timeline_data["render_plan"]["composition"][key] for key in ("width", "height", "fps", "duration_in_frames")}}], package_media=[dict(media, usage_rights="owned", package_permission=True)], engineering_files=[], tool_versions={"fixture": "synthetic"}, render_parameters={"codec": "libx264"})
        self.manifest = self.add("vsc.delivery_manifest", "delivery", self.manifest_data, [self.timeline, self.mix, self.qa, self.review])
        self.gate("delivery")
        return self


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg")
class WorkflowV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vsc-workflow-v2-")
        cls.pipeline = StrictPipeline(cls.temp.name).build()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_default_profile_and_complete_cli_chain(self):
        p = self.pipeline
        self.assertEqual(p.state()["profile_snapshot"]["contract_policy"], "production-v2")
        self.assertEqual(p.ok("next", p.project).strip(), "DONE")
        self.assertIn("所有 Profile 交付关已满足", p.ok("status", p.project))

    def test_unselected_wrong_sha_and_scope_fail_without_mutating_baseline(self):
        p = self.pipeline
        data = copy.deepcopy(p.timeline_data)
        data["bindings"][0]["selected_item_id"] = "UNSELECTED"
        self.assertTrue(any("获选item不存在" in e for e in project_errors(data, p.project, p.state(), p.timeline)))
        data = copy.deepcopy(p.timeline_data)
        data["bindings"][0]["sha256"] = "f" * 64
        self.assertTrue(any("SHA" in e for e in project_errors(data, p.project, p.state(), p.timeline)))
        data["scope"] = "MISSING"
        self.assertTrue(any("scope" in e for e in project_errors(data, p.project, p.state(), p.timeline)))

    def test_strict_review_out_of_bounds_rejected(self):
        p = self.pipeline
        data = copy.deepcopy(p.review_data)
        data["assessments"][REVIEW_CATEGORIES[0]]["evidence"][0]["end_frame"] = 999
        item = p.add("vsc.sample_review", "delivery", data, [p.qa], approve=False)
        result = p.run("artifact", "decide", p.project, item["id"], "--status", "approved", "--by", "synthetic fixture")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("越界", result.stdout + result.stderr)

    def test_delivery_bundle_survives_original_directory_disconnect(self):
        p = self.pipeline
        bundle = p.root / "portable"
        build_bundle(p.project, p.state(), p.manifest["id"], bundle)
        original = p.root / "original-disconnected"
        p.project.rename(original)
        try:
            report = verify_bundle(bundle)
            self.assertEqual(report["status"], "passed", report)
            self.assertEqual(report["qa"][0]["status"], "passed", report)
            self.assertEqual(report["source_revalidation"], "not_checked")
        finally:
            original.rename(p.project)


class ScopedV2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-three-scopes-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        result = subprocess.run([sys.executable, "-B", str(CLI), "init", str(self.project), "--title", "Synthetic scopes", "--profile", "vsc.novel-serial"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.state = json.loads((self.project / "vsc.json").read_text("utf-8"))
        self.state["objects"] = [{"id": f"EP{n}", "kind": "episode"} for n in (1, 2, 3)]
        source = self.project / "source.txt"
        source.write_text("Synthetic source", "utf-8")
        self.state["sources"] = [{"id": "S1", "path": "source.txt", "sha256": digest(source), "snapshot": True}]
        self.state["artifacts"] = []
        for stage in self.state["profile_snapshot"]["stages"]:
            scopes = ["project"] if stage["id"] in ("brief", "source", "adaptation") else ["EP1"] + (["EP2"] if stage["id"] == "script" else [])
            for scope in scopes:
                for kind in stage["required"]:
                    self.state["artifacts"].append({"id": f"A{len(self.state['artifacts'])}", "type": kind, "stage": stage["id"], "scope": scope, "status": "approved"})

    def tearDown(self):
        self.temp.cleanup()

    def test_three_episodes_keep_independent_gates_next_and_status(self):
        with patch.object(vsc_state, "validate_artifact", return_value=[]):
            self.assertEqual(vsc_state.gate_problems(self.project, self.state, "delivery", "EP1"), [])
            self.assertIsNone(vsc_state.first_open_stage(self.project, self.state, "EP1"))
            self.assertEqual(vsc_state.first_open_stage(self.project, self.state, "EP2")["id"], "design")
            self.assertEqual(vsc_state.first_open_stage(self.project, self.state, "EP3")["id"], "script")
            self.assertIsNotNone(vsc_state.first_open_stage(self.project, self.state))
            self.assertTrue(any("EP3" in e for e in vsc_state.gate_problems(self.project, self.state, "delivery")))
            with patch.object(vsc_state, "project_state", return_value=self.state):
                for scope, expected in (("EP1", "DONE"), ("EP2", "design"), ("EP3", "script")):
                    stream = io.StringIO()
                    with redirect_stdout(stream):
                        vsc_state.cmd_next(SimpleNamespace(project=self.project, scope=scope))
                    self.assertEqual(stream.getvalue().strip(), expected)
                stream = io.StringIO()
                with redirect_stdout(stream):
                    vsc_state.cmd_status(SimpleNamespace(project=self.project, scope="EP2"))
                self.assertIn("design", stream.getvalue())

    def test_cli_exposes_scope_and_rejects_unknown_scope(self):
        for command in (("status",), ("next",), ("gate", "check")):
            result = subprocess.run([sys.executable, "-B", str(CLI), *command, "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--scope", result.stdout)
        result = subprocess.run([sys.executable, "-B", str(CLI), "gate", "check", str(self.project), "delivery", "--scope", "MISSING"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("episode", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
