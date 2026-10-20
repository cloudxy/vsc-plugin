"""Reusable real synthetic clean-master fixture for tests and local UI acceptance.

Only use with an isolated PostgreSQL engine; no production objects or approvals.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from support.fixtures.resource_store import ResourceStoreFixture
from vsc.post.edit_preview import EditPreviewConverter, RECIPE_VERSION


class EditPreviewFixture(ResourceStoreFixture):
    def seed(self, missing=False, canonical=False):
        from vsc.post import subtitle_burn as SB, remotion_plan as RP
        self.master = self.root / "clean.mp4"
        if canonical:
            import array
            import math
            import wave
            samples = array.array("h", [0]*48000*6)
            windows = [(1500, 2500), (3000, 4000), (4500, 6000)]
            for begin, end in windows:
                for index in range(begin*48, end*48):
                    samples[index] = round(10000*math.sin(index*2*math.pi*440/48000))
            active = [sum(v*v for v in samples[offset:offset+480])/480 > 500**2 for offset in range(0,len(samples),480)]
            measured, begin = [], None
            for i,present in enumerate(active+[False]):
                if present and begin is None:
                    begin = i*10
                elif not present and begin is not None:
                    measured.append((begin,i*10))
                    begin = None
            if measured != windows:
                raise AssertionError("synthetic audio RMS windows differ from expected measured intervals")
            windows = measured
            audio_path = self.root / "measured.wav"
            with wave.open(str(audio_path), "wb") as wav:
                wav.setparams((1, 2, 48000, 0, "NONE", "uncompressed"))
                wav.writeframes(samples.tobytes())
            audio_args = ["-i", str(audio_path)]
        else:
            audio_args = ["-f", "lavfi", "-i",
                "aevalsrc=if(lt(t\\,3)\\,0.3*sin(2*PI*440*t)\\,0.3*sin(2*PI*880*t)):s=48000:d=6"]
        subprocess.run([self.converter.ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            "color=c=navy:s=240x320:r=24:d=6", *audio_args,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-threads", "1", "-shortest", str(self.master)],
            check=True, capture_output=True)
        font = SB.DEFAULT_FONT
        if not font.is_file():
            raise RuntimeError("test requires installed pinned subtitle font")
        objects = self.hierarchy()
        def register(path, name):
            with path.open("rb") as data:
                staged = self.storage.stage_upload(data, path.name)
            row = self.write("register_media", {"staged_upload": staged["staged_upload"], "name": name,
                "rights": "owned", "source": {"kind": "synthetic_test", "content": "Real local synthetic media fixture"}})
            self.write("record_media_check", {"media_id": row["id"], "checker": "test-ffmpeg-and-font",
                "criteria_version": "1", "outcome": "pass"})
            return row["id"]
        master_id, font_id = register(self.master, "clean master"), register(font, "fixed font")
        self.master_id, self.font_id = master_id, font_id
        selected = self.select(self.candidate(objects["shot"], master_id, role="video_take"))
        items = [{"shot_id": objects["shot"], "track_key": "video", "offset_frame": 0, "duration_frames": 144,
            "media": [{"media_id": master_id, "binding_decision_id": selected["decision_id"], "role": "video_take", "source_out_frame": 144}]}]
        composition = {"id": "PreviewTest", "width": 240, "height": 320, "fps": 24, "duration_in_frames": 144}
        dependencies = []
        if canonical:
            from sqlalchemy import select
            from vsc.adapters.persistence.postgres import schema as S
            audio_id = register(audio_path, "measured caption audio")
            self.audio_id = audio_id
            audio_sha = hashlib.sha256(audio_path.read_bytes()).hexdigest()
            lines = [{"id": str(uuid.uuid4()), "line_key": "L"+str(i), "scene_id": objects["scene"],
                "ordinal": i, "text": text} for i,text in enumerate(("固定第一句", "只移动这句", "保持最后句"))]
            script = self.write("create_artifact", {"artifact_key": "caption-script", "artifact_type": "screenplay",
                "document": {"script_lines": lines}, "script_lines": lines})
            self.write("decide_artifact", {"artifact_id": script["id"], "reason": "Synthetic measured package script"})
            covers = [{"shot_id": objects["shot"], "line_id": line["id"], "start_char": 0, "end_char": len(line["text"])} for line in lines]
            coverage = self.write("create_artifact", {"artifact_key": "caption-coverage", "artifact_type": "coverage-plan",
                "document": {"line_coverage": covers}, "line_coverage": covers, "dependency_ids": [script["id"]]})
            self.write("decide_artifact", {"artifact_id": coverage["id"], "reason": "Synthetic measured package coverage"})
            dependencies = [script["id"], coverage["id"]]
            for i,(line,(begin,end)) in enumerate(zip(lines, windows)):
                with self.engine.connect() as conn:
                    coverage_id = conn.execute(select(S.shot_line_coverage.c.id).where(S.shot_line_coverage.c.project_id==self.p,
                        S.shot_line_coverage.c.line_id==line["id"])).scalar_one()
                audio_decision = self.select(self.candidate(objects["shot"], audio_id, role="dialogue_dry",
                    slot_key="line-"+str(i), line_coverage_id=coverage_id))
                items.append({"shot_id": objects["shot"], "track_key": "dialogue-"+str(i), "offset_frame": begin*24//1000,
                    "duration_frames": (end-begin)*24//1000, "media": [{"media_id": audio_id, "role": "dialogue_dry",
                        "binding_decision_id": audio_decision["id"], "source_in_frame": begin*24//1000, "source_out_frame": end*24//1000}]})
        timeline_doc = {"items": items, "composition": composition, "subtitle_style": {"font_size": 24, "position": "bottom"}}
        timeline_artifact = self.write("create_artifact", {"artifact_key": "caption-timeline", "artifact_type": "timeline",
            "document": timeline_doc, "dependency_ids": dependencies})["id"]
        self.write("decide_artifact", {"artifact_id": timeline_artifact, "reason": "Synthetic fixed timeline"})
        timeline = self.write("freeze_timeline", {"artifact_id": timeline_artifact, "episode_id": objects["episode"],
            "items": items, "fps_num": 24})["id"]
        self.plan = {"format": RP.FORMAT, "project_id": self.p,
            "composition": composition,
            "subtitle_style": {"font_size": 24, "position": "bottom"},
            "segments": [
                {"id": "V1", "kind": "video", "source": "clean.mp4", "source_shot_id": "SHOT", "from_frame": 0, "duration_in_frames": 144},
                {"id": "C1", "kind": "caption", "text": "固定第一句", "from_frame": 36, "duration_in_frames": 24},
                {"id": "C2", "kind": "caption", "text": "只移动这句", "from_frame": 72, "duration_in_frames": 24},
                {"id": "C3", "kind": "caption", "text": "保持最后句", "from_frame": 108, "duration_in_frames": 36}]}
        self.caption_id = "C2"
        if canonical:
            frozen = self.service.get_timeline(self.p, timeline)
            audio_items = {item["track_key"]: item for item in frozen["items"] if item["track_key"].startswith("dialogue-")}
            cues = []
            for i,(line,(begin,end)) in enumerate(zip(lines,windows)):
                measurement = {"method": "pcm_activity_scan", "version": "synthetic-rms/v1", "line_key": line["line_key"],
                    "audio_media_sha256": audio_sha, "start_ms": begin, "end_ms": end,
                    "evidence": {"sample_rate": 48000, "sample_count": len(samples), "window_samples": 480,
                                "activity_intervals": windows, "threshold": 500}}
                cues.append({"key": "cue-"+str(i), "kind": "dialogue", "scope_object_id": objects["episode"], "line_id": line["id"],
                    "shots": [{"shot_id": objects["shot"]}], "timeline_item_ids": [audio_items["dialogue-"+str(i)]["id"]],
                    "parameters": {"subtitle_alignment": {"script_version_sha256": script["sha256"], "audio_media_sha256": audio_sha,
                        "start_ms": begin, "end_ms": end, "measurement": measurement}}})
            cue_artifact = self.write("create_artifact", {"artifact_key": "caption-cues", "artifact_type": "creative-relations",
                "document": {"format": "vsc.creative-relations/v1", "project_id": self.p, "cues": cues},
                "dependency_ids": [*dependencies, timeline_artifact]})
            self.write("decide_artifact", {"artifact_id": cue_artifact["id"], "reason": "Synthetic measured cue fixtures"})
            from vsc.post.resource_export import export_render_package
            self.package_root = self.root / "canonical-package"
            export_render_package(self.service, self.p, timeline, self.package_root)
            self.plan = json.loads((self.package_root / "render-plan.json").read_text())
            self.caption_id = [s["id"] for s in self.plan["segments"] if s["kind"]=="caption"][1]
        source = self.write("create_artifact", {"artifact_key": "caption-render", "artifact_type": "render-plan", "document": self.plan})
        self.write("decide_artifact", {"artifact_id": source["id"], "reason": "Fixed synthetic baseline"})
        initial = self.root / "original"
        initial.mkdir()
        if canonical:
            shutil.copytree(self.package_root / "media", initial / "media")
        self.master_sha, self.font_sha = (hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.master, font))
        output, _ = self.converter.convert({"recipe_version": RECIPE_VERSION, "tool_version": self.converter.capabilities()["tool_version"],
            "document": self.plan, "start_frame": 0, "end_frame": 144, "master_sha256": self.master_sha,
            "font_sha256": self.font_sha, "draft_sha256": source["sha256"]}, self.master, font, initial)
        self.original = output
        final_id = register(output, "original captioned render")
        outputs = [{"media_id": final_id, "role": "delivery"}]
        caption_inputs = [{"media_id": font_id, "role": "subtitle_font"}, {"media_id": master_id, "role": "clean_master"}]
        proof = {"plan_sha256": RP.document_sha256(self.plan), "sha256": self.master_sha, "font_sha256": self.font_sha,
                 "subtitles_absent": True, "caption_count": 0, "composition": self.plan["composition"],
                 "producer": "ffmpeg-lavfi-synthetic", "producer_version": "1"}
        rendered = self.write("freeze_render", {"artifact_id": source["id"], "timeline_id": timeline,
            "tool": "synthetic-test", "tool_version": "1", "outputs": outputs,
            **({"caption_inputs": caption_inputs} if not missing else {}), "parameters": {"edit_preview_clean_master": proof}})
        self.render_id, self.source_id, self.final_id, self.timeline_id = rendered["id"], source["id"], final_id, timeline
        capability = self.repository.capability(self.p, media_id=final_id)
        self.target = dict(capability["target"], start_frame=72, end_frame=96)
        return capability



def seed_edit_preview(service, root):
    """Return the fixture and its readable IDs for an isolated acceptance server."""
    from vsc.adapters.storage.local.store import LocalStorage
    from vsc.adapters.persistence.postgres.edit_preview_store import EditPreviewRepository
    fixture = EditPreviewFixture()
    fixture.root = Path(root)
    fixture.root.mkdir(parents=True, exist_ok=True)
    fixture.service, fixture.store = service, service.store
    fixture.engine = service.store.engine
    fixture.storage = service.storage or LocalStorage(fixture.root / "storage")
    service.storage = fixture.storage
    fixture.converter = EditPreviewConverter()
    fixture.repository = EditPreviewRepository(fixture.store)
    fixture.project = service.create_project({"name": "字幕位置修改验证", "profile_snapshot": {
        "profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="test-human")
    fixture.p, fixture.rev = fixture.project["id"], 0
    fixture.capability = fixture.seed()
    return fixture
