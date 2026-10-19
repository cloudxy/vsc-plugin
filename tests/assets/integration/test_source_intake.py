"""Source extraction and import through real isolated PostgreSQL migrations."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import support.paths  # noqa: F401
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from support.fixtures.source_intake import docx_bytes, xlsx_bytes, pdf_bytes
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires explicit test PostgreSQL URL and dependencies")
class SourceIntakeFlow(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        from vsc.adapters.storage.local.store import LocalStorage
        self.files = tempfile.TemporaryDirectory(prefix="vsc-source-test-")
        self.addCleanup(self.files.cleanup)
        self.service.storage = LocalStorage(self.files.name)
        self.project = self.service.create_project({"name": "Synthetic source intake",
            "profile_snapshot": {"profile_id": "vsc.synthetic-source", "version": "1",
                "dependency_policy": "previous_stage", "scope_required_from": "script", "stages": [
                    {"id": "adapt", "required": ["adaptation-plan"]},
                    {"id": "script", "required": ["vsc.screenplay"]},
                    {"id": "design", "required": ["asset-bible"]}]}}, actor="test-human")
        self.p, self.rev = self.project["id"], 0

    def source(self, text="SC1\nAlice: Hello\nHe turns.", intent="screenplay", **extra):
        return self.write("create_source_intake", dict(intent=intent, content=text, title="Synthetic source", **extra))

    def job(self, sources, intent="screenplay", parameters=None):
        result = self.write("create_parse_job", {"intent": intent, "inputs": [
            {"source_id": source["id"], "source_sha256": source["sha256"]} for source in sources],
            "parameters": parameters or {}})
        attempt = self.write("run_parse_job", {"job_id": result["id"]})
        return result, attempt

    def prepared(self, job, attempt):
        return self.write("prepare_parse_import", {"job_id": job["id"], "attempt_id": attempt["attempt_id"], "confirmed": True})

    def import_payload(self, job, attempt, prepared):
        return {"job_id": job["id"], "attempt_id": attempt["attempt_id"], "scope_key": prepared["scope_key"],
                "base_draft_revision": 0, "scene_mapping": prepared["scene_mapping"],
                "speaker_mapping": prepared["speaker_mapping"],
                "durations_ms": {key: 4000 for key in prepared["scene_mapping"]}}

    def approved_adaptation(self, scope, scene_ids):
        # Actual immutable fixture artifact and explicit human test decision.
        result = self.write("create_artifact", {"artifact_key": "adaptation", "artifact_type": "adaptation-plan",
            "document": {"screen_units": [{"id": "N" + str(i), "scene_id": scene} for i, scene in enumerate(scene_ids, 1)]},
            "object_ids": [scope]})
        self.write("decide_artifact", {"artifact_id": result["id"], "reason": "Synthetic human accepts adaptation"})
        return result

    def test_empty_project_multi_source_to_corrected_draft_frozen_lines_and_approval(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        source_a = self.source()
        source_b = self.source("SC2\nBob: Second source.")
        typed = {row["source_id"]: row for row in self.store.list_source_intake_documents(self.p)["items"]}
        self.assertEqual(typed[source_a["id"]]["title"], "Synthetic source")
        self.assertEqual(typed[source_a["id"]]["intent"], "screenplay")
        self.assertEqual(typed[source_a["id"]]["format"], "paste")
        self.assertEqual(self.service.get_source_version(self.p, source_a["id"])["kind"], "intake")
        self.assertIsNone(self.service.get_source_version(self.p, source_a["id"])["evidence_uri"])
        job, attempt = self.job([source_a, source_b])
        self.assertEqual(attempt["status"], "succeeded")
        preview = self.service.preview_parse_job(self.p, job["id"])
        self.assertEqual(len(preview["proposal"]["scenes"]), 2)
        self.assertTrue(preview["defaults_preview"]["requires_confirmation"])
        prepared = self.prepared(job, attempt)
        self.assertTrue(any(row["system_default"] for row in prepared["system_created"]))
        self.assertFalse(any(row["kind"] == "shot" for row in prepared["system_created"]))
        payload = self.import_payload(job, attempt, prepared)
        payload["corrections"] = {"U1": "Human corrected dialogue"}
        imported = self.write("import_parse_job", payload)
        if evidence_dir := os.environ.get("VSC_SOURCE_EVIDENCE_DIR"):
            destination = Path(evidence_dir)
            destination.mkdir(parents=True, exist_ok=True)
            for name, value in (("workspace", self.service.get_source_workspace(self.p)),
                                ("preview", preview), ("prepare", prepared), ("import", imported)):
                (destination / (name + "-sample.json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
        self.assertEqual(imported["source_ref_count"], 3)
        self.assertIn("Human corrected dialogue", imported["content"]["body"])
        draft = self.service.get_script_draft(self.p, prepared["scope_key"])
        # No auto approval and no premature downstream production.
        with self.assertRaises(ResourceError) as caught:
            self.write("create_artifact", {"artifact_key": "design", "artifact_type": "asset-bible",
                "document": {"synthetic": True}, "object_ids": [prepared["scope_key"]]})
        self.assertEqual(caught.exception.code, "script_confirmation_required")
        with self.assertRaises(ResourceError) as caught:
            self.write("submit_script_draft", {"scope_key": prepared["scope_key"], "base_draft_revision": 1,
                "artifact_type": "vsc.screenplay"})
        self.assertEqual(caught.exception.code, "invalid_contract")
        adaptation = self.approved_adaptation(prepared["scope_key"], list(prepared["scene_mapping"].values()))
        content = copy.deepcopy(draft["content"])
        content["adaptation_refs"] = [{"id": adaptation["id"], "sha256": adaptation["sha256"]}]
        for index, scene in enumerate(content["scenes"], 1):
            for kind in ("actions", "dialogue", "silence"):
                for unit in scene[kind]:
                    unit["narrative_refs"] = ["N" + str(index)]
        content["body"] = "Stale duplicate body must be regenerated"
        saved = self.service.save_script_draft(self.p, {"scope_key": prepared["scope_key"], "base_draft_revision": 1,
            "content": content}, actor="test-human")
        self.assertEqual(saved["draft_revision"], 2)
        submitted = self.write("submit_script_draft", {"scope_key": prepared["scope_key"], "base_draft_revision": 2,
            "artifact_type": "vsc.screenplay", "dependency_ids": [adaptation["id"]]})["artifact"]
        with self.engine.connect() as conn:
            refs = list(conn.execute(select(S.script_line_sources).where(S.script_line_sources.c.project_id == self.p)).mappings())
            self.assertEqual(len(refs), 3)
            frozen = conn.execute(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id == submitted["id"])).scalar_one()
            self.assertNotIn("Stale duplicate", json.loads(frozen)["body"])
            self.assertEqual(len(list(conn.execute(select(S.source_versions).where(S.source_versions.c.project_id == self.p)))), 2)
        anchor = self.service.get_source_anchor(self.p, refs[0]["anchor_id"])
        self.assertIn(anchor["text"], "SC1\nAlice: Hello\nHe turns.\nSC2\nBob: Second source.")
        self.write("decide_artifact", {"artifact_id": submitted["id"], "reason": "Synthetic human approves frozen corrected script"})
        self.assertEqual(self.service.get_script_draft(self.p, prepared["scope_key"])["submitted"]["state"], "approved")

    def test_command_replay_and_retry_keep_immutable_attempts(self):
        source = self.source("中文".encode("gb18030").decode("latin1"))
        job, first = self.job([source])
        key = uuid.uuid4().hex
        payload = {"job_id": job["id"]}
        second = self.write("run_parse_job", payload, idempotency_key=key)
        replay = self.service.run_parse_job(self.p, payload, expected_revision=0, idempotency_key=key, actor="test-human")
        self.assertEqual(second, replay)
        self.assertEqual(second["attempt_no"], first["attempt_no"] + 1)
        self.assertEqual(len(self.service.get_parse_job(self.p, job["id"])["attempts"]), 2)

    def test_unsupported_file_is_registered_failed_and_retry_keeps_both_errors(self):
        staged = self.service.storage.stage_upload(io.BytesIO(b"opaque unsupported data"), "source.bin")
        source = self.write("create_source_intake", {"intent": "screenplay", "staged_upload": staged["staged_upload"]})
        job, first = self.job([source])
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["error_code"], "extractor_unavailable")
        second = self.write("run_parse_job", {"job_id": job["id"]})
        self.assertEqual(second["attempt_no"], 2)
        self.assertEqual(len(self.service.get_parse_job(self.p, job["id"])["extractions"]), 0)
        with self.assertRaises(ResourceError):
            self.service.preview_parse_job(self.p, job["id"])

    def test_controlled_docx_xlsx_and_pdf_store_manifest_and_real_anchors(self):
        import shutil
        cases = [("source.docx", docx_bytes(), {}), ("source.xlsx", xlsx_bytes(),
            {"column_mapping": {"sheet": "Script", "columns": {"scene": "A", "speaker": "B", "text": "C"}}})]
        if shutil.which("pdftotext"):
            cases.append(("source.pdf", pdf_bytes(), {}))
        for name, raw, params in cases:
            with self.subTest(name=name):
                staged = self.service.storage.stage_upload(io.BytesIO(raw), name)
                source = self.write("create_source_intake", {"intent": "screenplay", "staged_upload": staged["staged_upload"], "filename": name})
                self.assertEqual(source["original_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertNotEqual(source["original_sha256"], source["sha256"])
                version = self.service.get_source_version(self.p, source["id"])
                self.assertEqual(json.loads(version["content"])["format"], "vsc.source-file/v1")
                self.assertEqual(len(version["media"]), 1)
                job, attempt = self.job([source], parameters=params)
                self.assertEqual(attempt["status"], "succeeded", attempt)
                preview = self.service.preview_parse_job(self.p, job["id"])
                self.assertTrue(preview["extractions"][0]["anchors"])

    def test_novel_cannot_be_relabeled_or_imported_past_profile_adaptation(self):
        source = self.source("Synthetic novel paragraph", intent="novel")
        with self.assertRaises(ResourceError) as caught:
            self.job([source], intent="screenplay")
        self.assertEqual(caught.exception.code, "source_intent_mismatch")
        job, attempt = self.job([source], intent="novel")
        preview = self.service.preview_parse_job(self.p, job["id"])
        self.assertFalse(preview["can_import"])
        self.assertEqual(preview["next_step"], "profile_adaptation_required")
        with self.assertRaises(ResourceError) as caught:
            self.write("create_parse_job", {"intent": "novel", "inputs": [
                {"source_id": source["id"], "source_sha256": source["sha256"], "format": "pdf"}]})
        self.assertEqual(caught.exception.code, "source_format_mismatch")
        with self.assertRaises(ResourceError) as caught:
            self.prepared(job, attempt)
        self.assertEqual(caught.exception.code, "adaptation_required")

    def test_stale_attempt_and_draft_revision_never_overwrite_work(self):
        source = self.source()
        job, first = self.job([source])
        prepared = self.prepared(job, first)
        self.write("run_parse_job", {"job_id": job["id"]})
        with self.assertRaises(ResourceError) as caught:
            self.write("import_parse_job", self.import_payload(job, first, prepared))
        self.assertEqual(caught.exception.code, "parse_attempt_conflict")
        latest = self.service.get_parse_job(self.p, job["id"])["attempts"][-1]
        first["attempt_id"] = latest["id"]
        imported = self.write("import_parse_job", self.import_payload(job, first, prepared))
        content = copy.deepcopy(imported["content"])
        content["scenes"][0]["actions"][0]["text"] = "Human newer edit"
        self.service.save_script_draft(self.p, {"scope_key": prepared["scope_key"], "base_draft_revision": 1, "content": content}, actor="test-human")
        with self.assertRaises(ResourceError) as caught:
            self.write("import_parse_job", dict(self.import_payload(job, first, prepared), base_draft_revision=1))
        self.assertEqual(caught.exception.code, "draft_revision_conflict")
        self.assertIn("Human newer edit", self.service.get_script_draft(self.p, prepared["scope_key"])["content"]["body"])

    def test_cross_project_source_and_anchor_fk_are_rejected_and_results_immutable(self):
        from sqlalchemy import insert, update
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        source = self.source()
        job, attempt = self.job([source])
        preview = self.service.preview_parse_job(self.p, job["id"])
        other = self.service.create_project({"name": "Other synthetic project", "profile_snapshot": {"profile_id": "vsc.synthetic-other", "version": "1", "stages": []}}, actor="test-human")
        with self.assertRaises(ResourceError):
            self.service.create_parse_job(other["id"], {"intent": "screenplay", "inputs": [{"source_id": source["id"], "source_sha256": source["sha256"]}]},
                expected_revision=0, idempotency_key=uuid.uuid4().hex, actor="test-human")
        extraction = preview["extractions"][0]
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.source_anchors).values(project_id=other["id"], id=str(uuid.uuid4()),
                    extraction_id=extraction["id"], source_id=source["id"], anchor_key="bad", start_char=0, end_char=1, locator={}))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(update(S.source_extractions).where(S.source_extractions.c.id == extraction["id"]).values(text="Changed"))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.source_intake_documents).values(project_id=other["id"], source_id=source["id"],
                    title="Cross-project forgery", intent="screenplay", format="txt"))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(update(S.source_intake_documents).where(S.source_intake_documents.c.project_id == self.p,
                    S.source_intake_documents.c.source_id == source["id"]).values(title="Overwritten metadata"))

    def test_removing_import_marker_cannot_create_second_editable_body(self):
        source = self.source()
        job, attempt = self.job([source])
        prepared = self.prepared(job, attempt)
        imported = self.write("import_parse_job", self.import_payload(job, attempt, prepared))
        content = copy.deepcopy(imported["content"])
        content.pop("structured_source")
        content["body"] = "Independent divergent body"
        content["scenes"][0]["actions"][0]["text"] = "Single structural truth"
        self.service.save_script_draft(self.p, {"scope_key": prepared["scope_key"], "base_draft_revision": 1,
            "content": content}, actor="test-human")
        draft = self.service.get_script_draft(self.p, prepared["scope_key"])
        self.assertTrue(draft["content"]["structured_source"])
        self.assertIn("Single structural truth", draft["content"]["body"])
        self.assertNotIn("Independent divergent", draft["content"]["body"])
        line = draft["content"]["scenes"][0]["dialogue"][0]
        suggestion = self.write("add_script_suggestion", {"scope_key": prepared["scope_key"], "base_draft_revision": 2,
            "scene_id": prepared["scene_mapping"]["scene-1"], "line_id": line["id"], "kind": "dialogue",
            "field": "text", "before_value": line["text"], "after_value": "Human accepts suggested correction", "reason": "Synthetic correction"})
        for outcome, expected in (("accept", "Human accepts suggested correction"), ("undo_accept", line["text"])):
            self.write("decide_script_suggestion", {"scope_key": prepared["scope_key"], "suggestion_id": suggestion["id"],
                "outcome": outcome, "reason": "Synthetic human decision"})
            updated = self.service.get_script_draft(self.p, prepared["scope_key"])
            self.assertIn(expected, updated["content"]["body"])
            self.assertEqual(len(updated["source_refs"]), imported["source_ref_count"])

    def test_malformed_imported_draft_keeps_saved_content_and_provenance(self):
        source = self.source()
        job, attempt = self.job([source])
        prepared = self.prepared(job, attempt)
        imported = self.write("import_parse_job", self.import_payload(job, attempt, prepared))
        for mutation in ("scene", "group", "unit"):
            with self.subTest(mutation=mutation):
                broken = copy.deepcopy(imported["content"])
                if mutation == "scene":
                    broken["scenes"].append(None)
                elif mutation == "group":
                    broken["scenes"][0]["actions"] = None
                else:
                    broken["scenes"][0]["dialogue"].append(None)
                with self.assertRaises(ResourceError) as caught:
                    self.service.save_script_draft(self.p, {"scope_key": prepared["scope_key"],
                        "base_draft_revision": 1, "content": broken}, actor="test-human")
                self.assertEqual(caught.exception.code, "invalid_source_structure")
                draft = self.service.get_script_draft(self.p, prepared["scope_key"])
                self.assertEqual(draft["draft_revision"], 1)
                self.assertEqual(draft["content"], imported["content"])
                self.assertEqual(len(draft["source_refs"]), imported["source_ref_count"])

    def test_database_rejects_anchor_bounds_wrong_job_source_and_draft_ref_revision(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        source = self.source()
        other_source = self.source("SC2\nBob: Not in job")
        job, attempt = self.job([source])
        preview = self.service.preview_parse_job(self.p, job["id"])
        extraction = preview["extractions"][0]
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.source_anchors).values(project_id=self.p, id=str(uuid.uuid4()),
                    extraction_id=extraction["id"], source_id=source["id"], anchor_key="OUTSIDE", start_char=0,
                    end_char=len(extraction["text"]) + 1, locator={"kind": "line", "line": 1}))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                conn.execute(insert(S.source_extractions).values(project_id=self.p, id=str(uuid.uuid4()),
                    attempt_id=attempt["attempt_id"], source_id=other_source["id"], source_sha256=other_source["sha256"],
                    output_key="FORGED", text="X", text_sha256=hashlib.sha256(b"X").hexdigest(), layout={}, warnings=[]))
        prepared = self.prepared(job, attempt)
        imported = self.write("import_parse_job", self.import_payload(job, attempt, prepared))
        anchor = extraction["anchors"][1]
        for changes in ({"draft_revision": 2}, {"line_key": "not-a-real-unit"}):
            with self.subTest(changes=changes):
                with self.assertRaises(DBAPIError):
                    with self.engine.begin() as conn:
                        fields = {"project_id": self.p, "id": str(uuid.uuid4()), "draft_id": imported["draft_id"],
                            "draft_revision": 1, "scene_key": prepared["scene_mapping"]["scene-1"],
                            "line_key": "src-" + anchor["id"], "anchor_id": anchor["id"], "role": "forged"}
                        fields.update(changes)
                        conn.execute(insert(S.draft_source_refs).values(**fields))

    def test_existing_source_without_intake_metadata_requires_explicit_format(self):
        raw = b"SC1\nAlice: Explicit legacy format"
        uri = "https://example.invalid/original-manuscript"
        with self.engine.begin() as conn:
            source_id = self.store._insert_source(conn, self.p, {"kind": "legacy-original", "content": raw.decode(), "evidence_uri": uri})
        source = self.service.get_source_version(self.p, source_id)
        self.assertEqual(source["evidence_uri"], uri)
        request = {"intent": "screenplay", "inputs": [{"source_id": source_id, "source_sha256": source["sha256"]}]}
        with self.assertRaises(ResourceError) as caught:
            self.write("create_parse_job", request)
        self.assertEqual(caught.exception.code, "missing_field")
        request["inputs"][0]["format"] = "txt"
        job = self.write("create_parse_job", request)
        result = self.write("run_parse_job", {"job_id": job["id"]})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.store.list_source_intake_documents(self.p)["items"], [])


if __name__ == "__main__":
    unittest.main()
