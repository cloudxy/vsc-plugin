"""Offline serial Profile regressions; no provider calls or creative approvals."""
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _paths import ROOT
import vsc_series
import vsc_series_db as db
import vsc_series_jobs as jobs
from vsc_state import project_state, save


class SeriesDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-series-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "series"
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/vsc_state.py"),
            "init", str(self.project), "--title", "synthetic", "--profile", "vsc.series-db"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _artifact(self, state, kind, data, scope="EP1"):
        aid = f"A-{len(state['artifacts']) + 1}"
        path = self.project / "artifacts" / (aid + ".json")
        path.parent.mkdir(exist_ok=True)
        content = json.dumps(data, ensure_ascii=False).encode()
        path.write_bytes(content)
        item = {"id": aid, "type": kind, "stage": "synthetic", "scope": scope,
                "path": str(path.relative_to(self.project)), "sha256": hashlib.sha256(content).hexdigest(),
                "status": "approved", "depends_on": [], "dependency_versions": {},
                "decision": {"by": "synthetic fixture", "note": "test only", "at": "2026-10-13"}}
        state["artifacts"].append(item)
        return item

    def _shot_fixture(self):
        state = project_state(self.project)
        state["objects"] = [
            {"id": "EP1", "kind": "episode"},
            {"id": "SC1", "kind": "scene", "parent": "EP1"},
            {"id": "SQ1", "kind": "sequence", "parent": "SC1"},
            {"id": "SH1", "kind": "shot", "parent": "SQ1"},
            {"id": "char", "kind": "asset"},
            {"id": "loc", "kind": "asset"},
        ]
        bible = self._artifact(state, "vsc.asset_bible", {"format": "vsc.asset-bible/v1", "entities": [
            {"id": "char", "kind": "character", "name": "Synthetic", "identity": ["fixed face"],
             "variants": {"day": "day costume", "night": "night costume"}, "references": []},
            {"id": "loc", "kind": "location", "name": "Room", "identity": ["door left"],
             "variants": {"default": "warm"}, "references": []},
        ]})
        scene = self._artifact(state, "vsc.scene_state", {"format": "vsc.scene-state/v1", "scenes": [
            {"id": "SC1", "location_id": "loc", "baseline": {"time": "day", "lighting": "warm", "weather": "clear",
             "entities": {"char": {"variant": "day", "position": "left"}}},
             "shots": [{"id": "SH1", "changes": {}}]}]})
        plan = self._artifact(state, "vsc.shot_plan", {"format": "vsc.continuity-plan/v1", "sequence_id": "SQ1",
            "shots": [{"id": "SH1", "duration_ms": 5000, "reference_asset_ids": ["char", "loc"]}]})
        script = self._artifact(state, "vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [
            {"id": "SC1", "actions": [{"id": "AC1", "text": "Enters"}],
             "dialogue": [{"id": "L1", "speaker": "char", "text": "Hello"}]}]})
        style = self._artifact(state, "vsc.visual_bible", {"format": "vsc.visual-bible/v1", "palette": ["warm"]})
        refs = [{"id": item["id"], "sha256": item["sha256"]} for item in (bible, scene, plan, script, style)]
        run = self._artifact(state, "vsc.production_run", {"format": "vsc.production-run/v1", "approved_inputs": refs})
        save(self.project, state)
        return run

    def _reference(self, media_id, target, role, variant=None):
        content = b"synthetic-media-" + media_id.encode()
        path = self.project / ".vsc-media" / media_id
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        with db.connect(self.project) as connection:
            connection.execute("INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?)",
                (media_id, hashlib.sha256(content).hexdigest(), str(path.relative_to(self.project)),
                 "image", "owned", "synthetic fixture", "{}", "2026-10-13"))
            connection.execute("INSERT INTO media_bindings VALUES (?,?,?,?,?,?,?,?,?)",
                ("B-" + media_id, target, role, variant, media_id, "approved", "fixture", "test only", "2026-10-13"))

    def test_db_is_authority_and_mirror_is_repairable(self):
        self.assertEqual(project_state(self.project)["profile_id"], "vsc.series-db")
        mirror = self.project / "vsc.json"
        altered = json.loads(mirror.read_text())
        altered["title"] = "tampered"
        mirror.write_text(json.dumps(altered))
        with self.assertRaises(SystemExit):
            project_state(self.project)
        vsc_series.repair_mirror(self.project)
        self.assertEqual(project_state(self.project)["title"], "synthetic")
        with db.connect(self.project) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA)

    def test_existing_json_project_changes_authority_only_after_explicit_migration(self):
        legacy = Path(self.temp.name) / "legacy"
        cli = [sys.executable, "-B", str(ROOT / "scripts/vsc_state.py")]
        result = subprocess.run([*cli, "init", str(legacy), "--title", "old"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((legacy / db.DATABASE).exists())
        preview = subprocess.run([*cli, "profile", "migrate", str(legacy), "--profile", "vsc.series-db"],
            capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        plan = json.loads(preview.stdout)
        self.assertFalse((legacy / db.DATABASE).exists())
        apply = subprocess.run([*cli, "profile", "migrate", str(legacy), "--profile", "vsc.series-db",
            "--apply", "--plan-hash", plan["plan_sha256"], "--by", "fixture", "--reason", "explicit migration"],
            capture_output=True, text=True)
        self.assertEqual(apply.returncode, 0, apply.stderr)
        self.assertTrue((legacy / db.DATABASE).is_file())
        self.assertEqual(project_state(legacy)["profile_id"], "vsc.series-db")

    def test_db_rejects_in_place_identity_and_dependency_changes(self):
        self._shot_fixture()
        original = project_state(self.project)
        for mutate in (
            lambda value: value["objects"][1].update(parent="other"),
            lambda value: value["artifacts"][0].update(type="vsc.screenplay"),
            lambda value: value["artifacts"][0].update(depends_on=["A-2"]),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            changed["revision"] += 1
            with self.assertRaises(db.SeriesStoreError):
                db.commit_state(self.project, changed, original["revision"])
            self.assertEqual(db.load_state(self.project), original)

    def test_snapshot_index_context_and_idempotent_plan(self):
        run = self._shot_fixture()
        with db.connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT text FROM script_lines WHERE line_id='L1'").fetchone()[0], "Hello")
            self.assertEqual(connection.execute("SELECT outcome FROM approval_decisions WHERE id='artifact:A-1'").fetchone()[0], "approved")
        self._reference("face-day", "char", "identity_face", "day")
        self._reference("face-night", "char", "identity_face", "night")
        self._reference("room", "loc", "location_master")
        with patch.object(vsc_series, "validate_artifact", return_value=[]):
            context = vsc_series.build_shot_context(self.project, "SH1")
            self.assertEqual({r["media_id"] for r in context["media_references"]}, {"face-day", "room"})
            self.assertEqual(context["unresolved_reference_asset_ids"], [])
            vsc_series.validate_context_file(context)
            request = {"format": "vsc.generation-request/v1", "modality": "image", "shot_id": "SH1",
                "purpose": "shot_keyframe", "context_sha256": context["sha256"], "prompt": "Synthetic shot",
                "reference_media_ids": ["face-day", "room"], "width": 1080, "height": 1920}
            jobs.register_provider(self.project, "volc_ark", ["image"], "env:ARK_API_KEY")
            jobs.register_model(self.project, "volc_ark", "model-1", "symbolic-model", "image", "fixed-version",
                {"purposes": ["shot_keyframe"], "reference_media": True},
                {"size_map": {"1080x1920": "2K"}})
            jobs.set_route(self.project, "image", "shot_keyframe", "model-1")
            first = jobs.plan_job(self.project, run["id"], request)
            from vsc_volc_provider import VolcArkImageProvider
            self.assertIsInstance(jobs.adapter_for_job(self.project, first["job_id"], transport=lambda *_: None),
                                  VolcArkImageProvider)
            self.assertEqual(first, jobs.plan_job(self.project, run["id"], request))
            with self.assertRaises(vsc_series.SeriesError):
                jobs.plan_job(self.project, run["id"], dict(request, prompt="changed"))
            jobs.record_status(self.project, first["job_id"], "submission_unknown")
            with self.assertRaises(vsc_series.SeriesError):
                jobs.record_status(self.project, first["job_id"], "submission_unknown")
            jobs.record_status(self.project, first["job_id"], "submitted", "external-1")
            with db.connect(self.project) as connection:
                self.assertEqual(connection.execute("SELECT external_task_id FROM generation_jobs WHERE id=?",
                    (first["job_id"],)).fetchone()[0], "external-1")
        context["shot_spec"]["duration_ms"] = 999
        with self.assertRaises(vsc_series.SeriesError):
            vsc_series.validate_context_file(context)

    def test_cross_episode_boundary_requires_recorded_match(self):
        self._shot_fixture()
        state = project_state(self.project)
        state["objects"].extend([
            {"id": "EP2", "kind": "episode"}, {"id": "SC2", "kind": "scene", "parent": "EP2"},
            {"id": "SQ2", "kind": "sequence", "parent": "SC2"},
            {"id": "SH2", "kind": "shot", "parent": "SQ2"},
        ])
        self._artifact(state, "vsc.asset_bible", {"format": "vsc.asset-bible/v1", "entities": [
            {"id": "char", "kind": "character", "name": "Synthetic", "identity": ["fixed face"],
             "variants": {"day": "day costume"}, "references": []},
            {"id": "loc", "kind": "location", "name": "Room", "identity": ["door left"],
             "variants": {"default": "warm"}, "references": []}]}, "EP2")
        self._artifact(state, "vsc.scene_state", {"format": "vsc.scene-state/v1", "scenes": [
            {"id": "SC2", "location_id": "loc", "baseline": {"time": "day", "lighting": "warm", "weather": "clear",
             "entities": {"char": {"variant": "day", "position": "left"}}},
             "shots": [{"id": "SH2", "changes": {}}]}]}, "EP2")
        self._artifact(state, "vsc.shot_plan", {"format": "vsc.continuity-plan/v1", "sequence_id": "SQ2",
            "shots": [{"id": "SH2", "duration_ms": 5000, "reference_asset_ids": []}]}, "EP2")
        self._artifact(state, "vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [
            {"id": "SC2", "actions": [], "dialogue": []}]}, "EP2")
        self._artifact(state, "vsc.visual_bible", {"format": "vsc.visual-bible/v1", "palette": ["warm"]}, "EP2")
        save(self.project, state)
        with patch.object(vsc_series, "validate_artifact", return_value=[]):
            before = vsc_series.build_shot_context(self.project, "SH2")
            self.assertEqual(before["cross_episode_boundary"]["status"], "unlinked")
            vsc_series.link_boundary(self.project, "SH1", "SH2", "continuous", "fixture", "same action")
            after = vsc_series.build_shot_context(self.project, "SH2")
            self.assertEqual(after["cross_episode_boundary"]["status"], "linked")
            self.assertNotEqual(before["sha256"], after["sha256"])
            with self.assertRaises(vsc_series.SeriesError):
                vsc_series.link_boundary(self.project, "SH1", "SH2", "continuous", "fixture", "duplicate")
            vsc_series.link_boundary(self.project, "SH1", "SH2", "intentional_jump", "fixture", "reviewed cut", replace=True)
            with db.connect(self.project) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM continuity_edges WHERE status='superseded'").fetchone()[0], 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_media_copy_rights_and_binding_decisions(self):
        state = project_state(self.project)
        state["objects"].append({"id": "loc", "kind": "asset"})
        save(self.project, state)
        image = Path(self.temp.name) / "image.png"
        result = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32",
            "-frames:v", "1", str(image)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        media = vsc_series.import_media(self.project, "master", image, "image", "owned", "fixture")
        image.unlink()
        self.assertTrue((self.project / media["path"]).is_file())
        vsc_series.bind_media(self.project, "B1", "loc", "master", "location_master")
        vsc_series.decide_binding(self.project, "B1", "approved", "fixture", "test only")
        vsc_series.bind_media(self.project, "B2", "loc", "master", "location_master")
        with self.assertRaises(vsc_series.SeriesError):
            vsc_series.decide_binding(self.project, "B2", "approved", "fixture", "duplicate")
        vsc_series.retire_binding(self.project, "B1", "fixture", "new version")
        vsc_series.decide_binding(self.project, "B2", "approved", "fixture", "replacement")
        with db.connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM media_binding_decisions").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
