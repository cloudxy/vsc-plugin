"""Synthetic handoff documents shared by handoff, delivery and performance tests."""
import json
from pathlib import Path
from vsc.production.handoffs import digest, project_errors


class Fixture:
    def __init__(self, root):
        self.project = Path(root) / "project"
        self.project.mkdir()
        self.state = {"project_id": "synthetic", "objects": [{"id": "EP", "kind": "episode"}], "artifacts": [], "decisions": []}
        for n in (1, 2):
            self.state["objects"].extend([
                {"id": f"SC{n}", "kind": "scene", "parent": "EP"},
                {"id": f"SQ{n}", "kind": "sequence", "parent": f"SC{n}"},
                {"id": f"SH{n}", "kind": "shot", "parent": f"SQ{n}"}])
        adaptation = {"format": "vsc.adaptation-map/v1", "screen_units": [{"id": f"N{n}", "scene_id": f"SC{n}"} for n in (1, 2)]}
        self.adaptation = self.register("vsc.adaptation_plan", adaptation)
        self.screenplay_data = self.base("screenplay", body="Synthetic scene text", adaptation_refs=[self.ref(self.adaptation)], scenes=[
            {"id": f"SC{n}", "estimated_duration_ms": 1000, "actions": [{"id": f"A{n}", "text": "Synthetic action", "narrative_refs": [f"N{n}"]}], "dialogue": [], "silence": []} for n in (1, 2)])
        self.screenplay = self.register("vsc.screenplay", self.screenplay_data, [self.adaptation])
        self.shots, self.sounds = [], []
        for n in (1, 2):
            self.shots.append(self.register("vsc.shot_plan", {"format": "vsc.continuity-plan/v1", "sequence_id": f"SQ{n}", "shots": [{"id": f"SH{n}"}]}))
            self.sounds.append(self.register("vsc.sound_plan", {"format": "vsc.sound-cue-sheet/v1", "sequence_id": f"SQ{n}", "duration_ms": 1000, "ambience_beds": [], "music_cues": [], "boundaries": []}))
        self.coverage_data = self.base("coverage-plan", screenplay=self.ref(self.screenplay), omissions=[], scenes=[
            {"id": f"SC{n}", "sequences": [{"id": f"SQ{n}", "shot_plan": self.ref(self.shots[n-1]), "sound_plan": self.ref(self.sounds[n-1]), "shots": [{"id": f"SH{n}", "screenplay_unit_ids": [f"A{n}"]}]}]} for n in (1, 2)])
        self.coverage = self.register("vsc.coverage_plan", self.coverage_data, [self.screenplay, *self.shots, *self.sounds])
        items, sources = [], []
        for n in (1, 2):
            media = self.media(f"media/SH{n}.bin", f"synthetic media {n}".encode())
            source = self.register("vsc.video_take", (self.project / media["path"]).read_bytes())
            self.state["objects"].append({"id": f"TK{n}", "kind": "take", "parent": f"SH{n}", "artifact": source["id"]})
            sources.append(source)
            items.append({"id": f"SEL{n}", "shot_id": f"SH{n}", "take_id": f"TK{n}", "output_id": f"OUT{n}", "scope": "EP", "purpose": "visual", "usage_rights": "owned", "selected_by": "synthetic fixture", "media": media,
                          "source": {"kind": "manual", "artifact": self.ref(source), "imported_by": "synthetic fixture", "provenance": "Synthetic bytes; not production evidence"}})
        self.selected_data = self.base("selected-takes", items=items)
        self.selected = self.register("vsc.selected_takes", self.selected_data, sources)
        self.plan = {"format": "vsc.remotion-render-plan/v1", "project_id": "synthetic", "composition": {"id": "Test", "width": 320, "height": 240, "fps": 24, "duration_in_frames": 48}, "segments": [
            {"id": f"V{n}", "kind": "video", "source": items[n-1]["media"]["path"], "source_shot_id": f"SH{n}", "from_frame": (n-1)*24, "duration_in_frames": 24, "muted": True} for n in (1, 2)]}
        self.timeline_data = self.base("timeline", selected_takes=self.ref(self.selected), sound_plans=[], render_plan=self.plan, bindings=[
            {"segment_id": f"V{n}", "selected_item_id": f"SEL{n}", "sha256": items[n-1]["media"]["sha256"], "purpose": "visual", "usage_rights": "owned", "audio_role": "none", "cue_id": None} for n in (1, 2)])
        self.timeline = self.register("vsc.timeline", self.timeline_data, [self.selected])
        self.mix_data = self.base("mix", timeline=self.ref(self.timeline), sound_plans=[], layers=[], boundaries=[])
        self.mix = self.register("vsc.mix", self.mix_data, [self.timeline])
        self.render = self.media("final/master.bin", b"synthetic final")
        self.qa_data = {"format": "vsc.media-qa/v1", "status": "passed", "simulated": False, "eligible_for_review": True,
                        "plan_sha256": self.timeline["sha256"], "render": {"status": "passed", "metadata": {"sha256": self.render["sha256"]}}}
        self.qa = self.register("vsc.media_qa", self.qa_data, [self.timeline])
        self.review_data = {"format": "vsc.sample-review/v1", "reviewer": "synthetic fixture", "technical_report_sha256": self.qa["sha256"], "assessments": {key: {"result": "pass", "evidence": "synthetic fixture"} for key in ("story_and_motivation", "physical_continuity", "emotional_continuity", "edit_coverage", "dialogue_and_music")}}
        self.review_data.update(evidence_mode="structured", render_sha256=self.render["sha256"], scope={"kind": "complete", "start_frame": 0, "end_frame": 48, "delivery_id": "SYNTHETIC"})
        self.review = self.register("vsc.sample_review", self.review_data, [self.qa])
        self.manifest_data = self.base("delivery-manifest", delivery_id="SYNTHETIC", release_variants=[{
            "id": "master", "scope": "EP", "render": self.render, "subtitles": [], "timeline": self.ref(self.timeline), "mix": self.ref(self.mix), "qa": self.ref(self.qa), "reviews": [self.ref(self.review)], "specification": {k: self.plan["composition"][k] for k in ("width", "height", "fps", "duration_in_frames")}}],
            package_media=[dict(media, usage_rights="owned", package_permission=True) for media in [self.render, *[row["media"] for row in items]]], engineering_files=[], tool_versions={"fixture": "1"}, render_parameters={})
        self.manifest = self.register("vsc.delivery_manifest", self.manifest_data, [self.timeline, self.mix, self.qa, self.review])

    def base(self, name, **fields):
        return {"format": f"vsc.{name}/v1", "project_id": "synthetic", "scope": "EP", **fields}

    def media(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"path": path, "sha256": digest(target)}

    def register(self, kind, data, depends=(), status="approved"):
        identifier = f"A{len(self.state['artifacts']) + 1}"
        path = f"artifacts/{identifier}" + (".json" if isinstance(data, dict) else ".bin")
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json.dumps(data).encode() if isinstance(data, dict) else data)
        item = {"id": identifier, "type": kind, "scope": "EP", "stage": "synthetic", "path": path, "sha256": digest(target), "status": status, "depends_on": [x["id"] for x in depends], "dependency_versions": {x["id"]: x["sha256"] for x in depends}}
        self.state["artifacts"].append(item)
        return item

    @staticmethod
    def ref(item):
        return {"id": item["id"], "sha256": item["sha256"]}

    def errors(self, data, item):
        return project_errors(data, self.project, self.state, item)
