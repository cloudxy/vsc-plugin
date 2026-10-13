"""Offline serial Profile regressions; no provider calls or creative approvals."""
import contextlib
import copy
import hashlib
import io
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
import vsc_series_dispatch as dispatch
import vsc_series_export as series_export
import vsc_series_query as series_query
import vsc_budget as budget
from vsc_provider import GeneratedAsset, JobHandle, JobStatus
from vsc_state import project_state, save


class FakeImageAdapter:
    """Offline stand-in for a provider; counts every remote-shaped call."""

    def __init__(self):
        self.submits = 0
        self.polls = 0

    def submit(self, req):
        self.submits += 1
        return JobHandle("volc_ark", "symbolic-model", "external-1")

    def poll(self, handle):
        self.polls += 1
        return JobStatus("succeeded", raw={"data": [{"url": "https://example.invalid/x.png?sig=secret"}]})

    def parse_result(self, raw):
        return [GeneratedAsset("image", temporary_uri=raw["data"][0]["url"])]


class SeriesDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-series-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "series"
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/vsc_state.py"),
            "init", str(self.project), "--title", "synthetic", "--profile", "vsc.series-db"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _artifact(self, state, kind, data, scope="EP1", depends=()):
        aid = f"A-{len(state['artifacts']) + 1}"
        path = self.project / "artifacts" / (aid + ".json")
        path.parent.mkdir(exist_ok=True)
        content = json.dumps(data, ensure_ascii=False).encode()
        path.write_bytes(content)
        item = {"id": aid, "type": kind, "stage": "synthetic", "scope": scope,
                "path": str(path.relative_to(self.project)), "sha256": hashlib.sha256(content).hexdigest(),
                "status": "approved", "depends_on": [item["id"] for item in depends],
                "dependency_versions": {item["id"]: item["sha256"] for item in depends},
                "decision": {"by": "synthetic fixture", "note": "test only", "at": "2026-10-13"}}
        state["artifacts"].append(item)
        return item

    def _shot_fixture(self, shots=("SH1",)):
        state = project_state(self.project)
        state["objects"] = [
            {"id": "EP1", "kind": "episode"},
            {"id": "SC1", "kind": "scene", "parent": "EP1"},
            {"id": "SQ1", "kind": "sequence", "parent": "SC1"},
            *({"id": shot, "kind": "shot", "parent": "SQ1"} for shot in shots),
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
             "shots": [{"id": shot, "changes": {}} for shot in shots]}]})
        plan = self._artifact(state, "vsc.shot_plan", {"format": "vsc.continuity-plan/v1", "sequence_id": "SQ1",
            "shots": [{"id": shot, "duration_ms": 5000, "reference_asset_ids": ["char", "loc"]} for shot in shots]})
        script = self._artifact(state, "vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [
            {"id": "SC1", "actions": [{"id": "AC1", "text": "Enters"}],
             "dialogue": [{"id": "L1", "speaker": "char", "text": "Hello"}]}]})
        style = self._artifact(state, "vsc.visual_bible", {"format": "vsc.visual-bible/v1", "palette": ["warm"]})
        save(self.project, state)
        return bible, scene, plan, script, style

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
        inputs = self._shot_fixture()
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
            self.assertEqual(series_query.asset(self.project, "char")["bindings"][0]["media"]["id"], "face-day")
            self.assertEqual(series_query.script_line(self.project, "EP1", "L1")["line"]["text"], "Hello")
            self.assertEqual(series_query.episode(self.project, "EP1")["shots"][0]["id"], "SH1")
            vsc_series.validate_context_file(context)
            request = {"format": "vsc.generation-request/v1", "modality": "image", "shot_id": "SH1",
                "purpose": "shot_keyframe", "context_sha256": context["sha256"], "prompt": "Synthetic shot",
                "reference_media_ids": ["face-day", "room"], "width": 1080, "height": 1920}
            state = project_state(self.project)
            animatic = self._artifact(state, "vsc.animatic", {"format": "vsc.animatic/v1", "synthetic": True})
            batch = {"jobs": [{"request": request, "candidate_no": 1}]}
            operation = "series:SH1:shot_keyframe:1"
            run = self._artifact(state, "vsc.production_run", {
                "format": "vsc.production-run/v1", "project_id": state["project_id"], "scope": "EP1",
                "series_batch": batch, "plan_sha256": db.digest(batch),
                "approved_inputs": [{"id": item["id"], "sha256": item["sha256"]} for item in (*inputs, animatic)],
                "review_after": [], "operations": {operation: {"remote_jobs": 1, "images": 1}}},
                depends=(*inputs, animatic))
            save(self.project, state)
            from vsc_series_run import project_errors as series_run_errors
            self.assertEqual(series_run_errors(json.loads(db.artifact_document(self.project, run["id"])),
                self.project, project_state(self.project), run), [])
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

    def _image_job(self):
        """One approved image job behind a fake adapter; no provider is contacted."""
        inputs = self._shot_fixture()
        self._reference("face-day", "char", "identity_face", "day")
        self._reference("room", "loc", "location_master")
        context = vsc_series.build_shot_context(self.project, "SH1")
        request = {"format": "vsc.generation-request/v1", "modality": "image", "shot_id": "SH1",
            "purpose": "shot_keyframe", "context_sha256": context["sha256"], "prompt": "Synthetic shot",
            "reference_media_ids": ["face-day", "room"], "width": 1080, "height": 1920}
        state = project_state(self.project)
        animatic = self._artifact(state, "vsc.animatic", {"format": "vsc.animatic/v1", "synthetic": True})
        batch = {"jobs": [{"request": request, "candidate_no": 1}]}
        run = self._artifact(state, "vsc.production_run", {
            "format": "vsc.production-run/v1", "project_id": state["project_id"], "scope": "EP1",
            "series_batch": batch, "plan_sha256": db.digest(batch),
            "approved_inputs": [{"id": item["id"], "sha256": item["sha256"]} for item in (*inputs, animatic)],
            "review_after": [], "operations": {"series:SH1:shot_keyframe:1": {"remote_jobs": 1, "images": 1}}},
            depends=(*inputs, animatic))
        save(self.project, state)
        jobs.register_provider(self.project, "volc_ark", ["image"], "env:ARK_API_KEY")
        jobs.register_model(self.project, "volc_ark", "model-1", "symbolic-model", "image", "fixed-version",
            {"purposes": ["shot_keyframe"], "reference_media": True},
            {"size_map": {"1080x1920": "2K"}})
        jobs.set_route(self.project, "image", "shot_keyframe", "model-1")
        job_id = jobs.plan_job(self.project, run["id"], request)["job_id"]
        budget.configure(self.project, {"remote_jobs": 1, "images": 1}, "fixture", "offline test")
        image = Path(self.temp.name) / "result.png"
        result = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=c=red:s=32x32", "-frames:v", "1", str(image)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return job_id, context, image

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_approved_series_job_dispatch_resume_transfer_and_rights(self):
        with patch.object(vsc_series, "validate_artifact", return_value=[]):
            job_id, context, image = self._image_job()
            fake = FakeImageAdapter()
            downloads = []

            def download(url, target):
                downloads.append(url)
                shutil.copyfile(image, target)

            with patch("vsc_artifacts.validate_artifact", return_value=[]), patch.object(dispatch, "gate_problems", return_value=[]):
                self.assertEqual(dispatch.submit_job(self.project, job_id, fake)["status"], "submitted")
                with self.assertRaises(vsc_series.SeriesError):
                    dispatch.submit_job(self.project, job_id, fake)
                polled = dispatch.resume_pending(self.project, adapter_factory=lambda _project, _job: fake, download=download)
                self.assertEqual(len(polled), 1)
                self.assertEqual(polled[0]["job_id"], job_id)
                completed = {key: value for key, value in polled[0].items() if key != "job_id"}
                self.assertEqual(completed["status"], "succeeded")
                self.assertEqual(dispatch.resume_job(self.project, job_id, fake, download)["assets"], completed["assets"])
                self.assertEqual(dispatch.resume_pending(self.project, adapter_factory=lambda _project, _job: fake,
                                                         download=download), [])
            self.assertEqual(fake.submits, 1)
            self.assertEqual(fake.polls, 1)
            self.assertEqual(len(downloads), 1)
            media_id = completed["assets"][0]["media_id"]
            with db.connect(self.project) as connection:
                media = connection.execute("SELECT rights FROM media_assets WHERE id=?", (media_id,)).fetchone()
                generated = connection.execute("SELECT original_uri FROM generated_assets WHERE media_id=?", (media_id,)).fetchone()
            self.assertEqual(media["rights"], "unknown")
            self.assertEqual(generated["original_uri"], "https://example.invalid/x.png")
            record = series_export.generation_record(self.project, job_id, fake)
            self.assertEqual(record["outputs"][0]["sha256"], completed["assets"][0]["sha256"])
            self.assertEqual(record["purpose"], "candidate")
            self.assertEqual(record["inputs"]["anchors_sha256"], context["visual_anchor"]["sha256"])
            self.assertNotIn("audio_anchors_sha256", record["inputs"])
            self.assertEqual({(ref["entity_id"], ref["purpose"]) for ref in record["inputs"]["references"]},
                             {("char", "identity"), ("loc", "composition")})
            self.assertTrue(all(ref["path"].startswith(".vsc-media/") for ref in record["inputs"]["references"]))
            self.assertEqual(record["budget"]["usage"], {"remote_jobs": 1, "images": 1})
            out = self.project / "drafts" / "nested" / (job_id + ".json")
            with patch.object(series_export, "generation_record", return_value=record), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(series_export.main([str(self.project), "--job", job_id, "--out", str(out)]), 0)
                self.assertEqual(json.loads(out.read_text("utf-8")), record)
                self.assertEqual(series_export.main([str(self.project), "--job", job_id, "--out", str(out)]), 1)
            self.assertIn("拒绝覆盖", errors.getvalue())
            self.assertEqual(series_query.shot_jobs(self.project, "SH1")["jobs"][0]["outputs"][0]["id"], media_id)
            face = series_query.media(self.project, "face-day")
            self.assertEqual(face["bytes"], "ok")
            self.assertEqual([item["id"] for item in face["referenced_by_jobs"]], [job_id])
            self.assertEqual(face["bindings"][0]["target_id"], "char")
            produced = series_query.media(self.project, media_id)
            self.assertEqual(produced["generated_by"]["job_id"], job_id)
            self.assertEqual(series_query.scene(self.project, "SC1")["shots"][0]["entry"]["entities"]["char"]["variant"], "day")
            vsc_series.bind_media(self.project, "B-result", "SH1", media_id, "composition")
            with self.assertRaises(vsc_series.SeriesError):
                vsc_series.decide_binding(self.project, "B-result", "approved", "fixture", "candidate")
            vsc_series.decide_media_rights(self.project, media_id, "owned", "fixture", "reviewed output")
            vsc_series.decide_binding(self.project, "B-result", "approved", "fixture", "candidate")
            self.assertEqual(series_query.media(self.project, media_id)["rights_decisions"][0]["previous"], "unknown")
            with budget.ledger(self.project) as ledger:
                self.assertEqual(next(iter(ledger["reservations"].values()))["status"], "usage_unknown")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(dispatch.main(["resume-pending", str(self.project)]), 0)
            self.assertEqual(json.loads(printed.getvalue()), [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_resume_pending_finishes_interrupted_transfer_once(self):
        with patch.object(vsc_series, "validate_artifact", return_value=[]):
            job_id, _, image = self._image_job()
            fake = FakeImageAdapter()
            attempts = []

            def flaky(url, target):
                attempts.append(url)
                if len(attempts) == 1:
                    raise RuntimeError("temporary URL expired")
                shutil.copyfile(image, target)

            with patch("vsc_artifacts.validate_artifact", return_value=[]), patch.object(dispatch, "gate_problems", return_value=[]):
                dispatch.submit_job(self.project, job_id, fake)
                factory = lambda _project, _job: fake
                first = dispatch.resume_pending(self.project, adapter_factory=factory, download=flaky)
                self.assertEqual([item["status"] for item in first], ["poll_error"])
                self.assertIn("expired", first[0]["error"])
                second = dispatch.resume_pending(self.project, adapter_factory=factory, download=flaky)
                self.assertEqual([item["status"] for item in second], ["succeeded"])
                self.assertEqual(fake.polls, 1)
                with budget.ledger(self.project) as ledger:
                    reservation = next(iter(ledger["reservations"]))
                budget.settle(self.project, reservation, actual={"remote_jobs": 1, "images": 1}, evidence="synthetic bill")
                dispatch.resume_job(self.project, job_id, fake, flaky)
                self.assertEqual(dispatch.resume_pending(self.project, adapter_factory=factory, download=flaky), [])
            with budget.ledger(self.project) as ledger:
                self.assertEqual(ledger["reservations"][reservation]["status"], "settled")
            with db.connect(self.project) as connection:
                events = [row[0] for row in connection.execute(
                    "SELECT status FROM job_events WHERE job_id=? ORDER BY created_at,id", (job_id,))]
            self.assertEqual(events.count("transferred"), 1)
            self.assertEqual(events.count("poll_error"), 1)

    def test_approved_run_survives_selection_and_blocks_only_stale_jobs(self):
        inputs = self._shot_fixture(("SH1", "SH2"))
        self._reference("face-day", "char", "identity_face", "day")
        self._reference("room", "loc", "location_master")
        with patch.object(vsc_series, "validate_artifact", return_value=[]):
            requests = {}
            for shot in ("SH1", "SH2"):
                context = vsc_series.build_shot_context(self.project, shot)
                requests[shot] = {"format": "vsc.generation-request/v1", "modality": "image", "shot_id": shot,
                    "purpose": "shot_keyframe", "context_sha256": context["sha256"], "prompt": "Synthetic shot",
                    "reference_media_ids": ["face-day"], "width": 1080, "height": 1920}
            state = project_state(self.project)
            animatic = self._artifact(state, "vsc.animatic", {"format": "vsc.animatic/v1", "synthetic": True})
            batch = {"jobs": [{"request": requests[shot], "candidate_no": 1} for shot in ("SH1", "SH2")]}
            run = self._artifact(state, "vsc.production_run", {
                "format": "vsc.production-run/v1", "project_id": state["project_id"], "scope": "EP1",
                "series_batch": batch, "plan_sha256": db.digest(batch),
                "approved_inputs": [{"id": item["id"], "sha256": item["sha256"]} for item in (*inputs, animatic)],
                "review_after": [], "operations": {f"series:{shot}:shot_keyframe:1": {"remote_jobs": 1, "images": 1}
                                                   for shot in ("SH1", "SH2")}},
                depends=(*inputs, animatic))
            save(self.project, state)
            from vsc_series_run import project_errors as series_run_errors
            document = json.loads(db.artifact_document(self.project, run["id"]))
            self.assertEqual(series_run_errors(document, self.project, project_state(self.project), run), [])
            before = vsc_series.build_shot_context(self.project, "SH2")["sha256"]
            self._reference("SH2-take", "SH2", "video_take")
            self.assertEqual(vsc_series.build_shot_context(self.project, "SH2")["sha256"], before)
            self._reference("SH1-pick", "SH1", "composition")
            state = project_state(self.project)
            self.assertEqual(series_run_errors(document, self.project, state, run), [])
            pending = dict(run, status="draft", decision=None)
            self.assertTrue(any("镜头上下文已变化" in problem
                                for problem in series_run_errors(document, self.project, state, pending)))
            jobs.register_provider(self.project, "volc_ark", ["image"], "env:ARK_API_KEY")
            jobs.register_model(self.project, "volc_ark", "model-1", "symbolic-model", "image", "fixed-version",
                {"purposes": ["shot_keyframe"], "reference_media": True}, {"size_map": {"1080x1920": "2K"}})
            jobs.set_route(self.project, "image", "shot_keyframe", "model-1")
            self.assertEqual(jobs.plan_job(self.project, run["id"], requests["SH2"])["status"], "created")
            with self.assertRaises(vsc_series.SeriesError):
                jobs.plan_job(self.project, run["id"], requests["SH1"])

    def test_export_frame_provenance(self):
        timestamp = "2026-10-13"
        with db.connect(self.project) as connection:
            for media_id in ("own", "exit", "plain"):
                connection.execute("INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?)",
                    (media_id, "0" * 64, ".vsc-media/" + media_id, "image", "owned", "fixture", "{}", timestamp))
            for job_id, shot, modality in (("J-own", "SH1", "image"), ("J-prev", "SH0", "video")):
                connection.execute("INSERT INTO generation_jobs (id,run_artifact_id,target_id,purpose,modality,candidate_no,"
                    "provider,model,model_version,context_sha256,request_sha256,idempotency_key,status,request,created_at,"
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job_id, "A-run", shot, "keyframe", modality, 1, "fake", "fake", "v", "c", "r", job_id,
                     "succeeded", "{}", timestamp, timestamp))
            connection.execute("INSERT INTO generated_assets VALUES (?,?,?,?,?,?)", ("J-own", "own", "image", None, "{}", timestamp))
            connection.execute("INSERT INTO generated_assets VALUES (?,?,?,?,?,?)", ("J-prev", "exit", "image", None, "{}", timestamp))
            frames = {media_id: series_export._frame(connection, {"media_id": media_id, "path": ".vsc-media/" + media_id,
                                                                  "sha256": "0" * 64}, "SH1")
                      for media_id in ("own", "exit", "plain")}
        self.assertEqual(frames["own"]["from"], "generated")
        self.assertEqual((frames["exit"]["from"], frames["exit"]["shot"]), ("previous_exit", "SH0"))
        self.assertEqual(frames["plain"]["from"], "reference")

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
        state = project_state(self.project)
        state["objects"].extend([
            {"id": "EP1", "kind": "episode"}, {"id": "SC1", "kind": "scene", "parent": "EP1"},
            {"id": "SQ1", "kind": "sequence", "parent": "SC1"},
            {"id": "SH1", "kind": "shot", "parent": "SQ1"},
        ])
        save(self.project, state)
        video = Path(self.temp.name) / "take.mp4"
        result = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=c=red:s=32x32:r=24", "-t", "1", "-c:v", "mpeg4", str(video)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        vsc_series.import_media(self.project, "take-1", video, "video", "owned", "fixture")
        vsc_series.bind_media(self.project, "B-take", "SH1", "take-1", "video_take")
        vsc_series.decide_binding(self.project, "B-take", "approved", "fixture", "selected")
        with db.connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM media_binding_decisions").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
