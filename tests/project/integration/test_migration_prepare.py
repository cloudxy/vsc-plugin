"""Synthetic legacy preparation: identity, evidence and no invented approvals."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from support.paths import ROOT
from support.fixtures.migration import legacy, setup_postgres, teardown_postgres
from vsc.project import migration as M

HAS_POSTGRES = importlib.util.find_spec("sqlalchemy") is not None
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DB = HAS_POSTGRES and all(importlib.util.find_spec(name) for name in ("psycopg", "alembic"))


def _write(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _legacy(project):
    profile = {"profile_id": "synthetic", "version": "1", "stages": []}
    return legacy(project, profile=profile, revision=9, legacy_profile_digest=True,
        state_overrides={"project_id": "synthetic-project", "title": "工程迁移测试", "owner": "original-owner"})


def _artifact(project, state, old, kind, body, approved=False, dependencies=()):
    path = old + ".json"
    sha = _write(project, path, body)
    artifact = {"id": old, "type": kind, "stage": "production" if "generation" in kind else "design",
        "scope": "project", "path": path, "sha256": sha, "status": "approved" if approved else "draft", "depends_on": list(dependencies)}
    if approved:
        artifact["decision"] = {"by": "original-human", "note": "原始理由", "at": "2026-01-01T10:00:00"}
    state["artifacts"].append(artifact)
    return artifact


@unittest.skipUnless(HAS_POSTGRES, "requires postgres schema dependencies")
class MigrationPreparationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve() / "legacy"
        self.state = _legacy(self.project)

    def prepare(self, **options):
        M._write(self.project / "vsc.json", self.state)
        return M.prepare(self.project, "migration-operator", **options)

    def test_historical_profile_digest_and_complete_file_classes_remain_readonly(self):
        _write(self.project, "image.png", b"\x89PNG\r\n\x1a\nsynthetic")
        _write(self.project, "__pycache__/build.pyc", b"cache")
        _write(self.project, "tool.py", b"print('synthetic')\n")
        _write(self.project, "draft.md", b"draft")
        before = (self.project / "vsc.json").read_bytes()
        result = M.prepare(self.project, "migration-operator")
        self.assertTrue(result["ready"], result["blockers"])
        self.assertEqual(result["counts"]["file_classes"], {"image": 1, "cache": 1, "engineering": 1, "document": 1})
        self.assertEqual((self.project / "vsc.json").read_bytes(), before)
        self.assertFalse((self.project / M.MARKER).exists())
        self.assertFalse((self.project / M.POINTER).exists())
        self.assertEqual(len(result["manifest"]["tables"]["media_sources"]), 4)

    def test_no_objects_and_unapproved_legacy_timeline_do_not_create_structure_or_selection(self):
        _artifact(self.project, self.state, "BRIEF", "vsc.creative_brief", {"text": "synthetic"}, True)
        _artifact(self.project, self.state, "TAKES", "vsc.selected_takes", {"tasks": [{"id": "SH01", "output_path": "candidate.png"}]})
        _artifact(self.project, self.state, "TIMELINE", "vsc.timeline", {"source_takes": ["candidate.png"]})
        _write(self.project, "candidate.png", b"\x89PNG\r\n\x1a\nsynthetic")
        result = self.prepare(work_code="W001")
        self.assertTrue(result["ready"], result["blockers"])
        tables = result["manifest"]["tables"]
        for name in ("creative_objects", "shots", "binding_decisions", "current_bindings", "timeline_versions"):
            self.assertFalse(tables.get(name), name)
        self.assertEqual(len(result["manifest"]["preparation"]["legacy_unindexed"]), 2)
        self.assertEqual(tables["artifact_decisions"][0]["actor"], "original-human")
        self.assertEqual(tables["artifact_decisions"][0]["reason"], "原始理由")

    def test_existing_hierarchy_asset_versions_and_script_lines_have_typed_relations(self):
        self.state["objects"] = [
            {"id": "E1", "kind": "episode", "parent": None}, {"id": "S1", "kind": "scene", "parent": "E1"},
            {"id": "Q1", "kind": "sequence", "parent": "S1"}, {"id": "H1", "kind": "shot", "parent": "Q1"},
            {"id": "C1", "kind": "asset", "parent": None, "artifact": "BIBLE"}]
        bible = _artifact(self.project, self.state, "BIBLE", "vsc.asset_bible", {"format": "vsc.asset-bible/v1", "entities": [
            {"id": "C1", "kind": "character", "variants": {"default": {}}}]}, True)
        script = _artifact(self.project, self.state, "SCRIPT", "vsc.screenplay", {"format": "vsc.screenplay/v1", "scenes": [
            {"id": "S1", "dialogue": [{"id": "L1", "speaker": "C1", "text": "测试对白"}]}]}, True, ["BIBLE"])
        script["asset_versions"] = {"C1": {"id": "BIBLE", "sha256": bible["sha256"]}}
        result = self.prepare(work_code="W001")
        self.assertTrue(result["ready"], result["blockers"])
        tables = result["manifest"]["tables"]
        self.assertEqual(len(tables["creative_objects"]), 6)
        self.assertEqual(tables["script_lines"][0]["line_key"], "L1")
        self.assertEqual(len(tables["artifact_asset_spec_refs"]), 1)
        self.assertEqual(result["manifest"]["preparation"]["original_parents"]["E1"], None)

    def test_missing_parent_and_missing_approved_actor_block_preparation(self):
        self.state["objects"] = [{"id": "H1", "kind": "shot", "parent": "unknown"}]
        item = _artifact(self.project, self.state, "BRIEF", "vsc.creative_brief", {}, True)
        item["decision"].pop("by")
        result = self.prepare(work_code="W001")
        self.assertFalse(result["ready"])
        self.assertTrue({"hierarchy_parent_missing", "approval_evidence_missing"}.issubset({b["code"] for b in result["blockers"]}))
        self.assertFalse(result["manifest"]["tables"].get("artifact_decisions"))

    def test_unregistered_generation_keeps_provenance_and_inputs_outputs_without_selection(self):
        source_sha = _write(self.project, "input.png", b"\x89PNG\r\n\x1a\ninput")
        output_sha = _write(self.project, "output.png", b"\x89PNG\r\n\x1a\noutput")
        _write(self.project, "independent.json", {"format": "vsc.generation-record/v1", "kind": "image", "shot_id": None,
            "inputs": {"references": [{"path": "input.png", "sha256": source_sha, "purpose": "reference"}]},
            "engine": {"provider": "synthetic", "model": "model", "task_id": "original-task"}, "status": "succeeded",
            "outputs": [{"path": "output.png", "sha256": output_sha, "source_url": "https://example.invalid/expired"}]})
        result = self.prepare()
        self.assertTrue(result["ready"], result["blockers"])
        tables = result["manifest"]["tables"]
        self.assertEqual(len(tables["operation_inputs"]), 1)
        self.assertEqual(len(tables["operation_outputs"]), 1)
        self.assertFalse(tables.get("generation_jobs"))
        self.assertFalse(tables.get("binding_decisions"))
        self.assertEqual(result["manifest"]["preparation"]["generation_records"]["unique"], 1)
        self.assertEqual(result["manifest"]["preparation"]["legacy_unbound"][0]["scheduling_eligible"], False)

    def test_approved_unindexed_document_is_rejected_even_if_manifest_is_edited(self):
        _artifact(self.project, self.state, "TIMELINE", "vsc.timeline", {"old_format": True}, True)
        result = self.prepare()
        self.assertFalse(result["ready"])
        self.assertEqual(result["blockers"][0]["code"], "approved_projection_missing")
        manifest = copy.deepcopy(result["manifest"])
        manifest["mappings"]["artifacts:TIMELINE"]["classification"] = "legacy_unindexed"
        row = next(r for r in manifest["tables"]["artifact_versions"] if r["artifact_type"] == "vsc.timeline")
        row["parser_version"] = "legacy-unindexed/v1"
        with self.assertRaisesRegex(M.MigrationError, "已批准产物不能绕过"):
            M.validate_manifest(self.project, manifest)

    def test_cli_prepare_writes_only_requested_manifest_and_does_not_freeze(self):
        import argparse
        parser = argparse.ArgumentParser()
        M.migration_parser(parser.add_subparsers(dest="command", required=True))
        output = self.project / M.CONTROL / "prepared.json"
        args = parser.parse_args(["migrate", str(self.project), "prepare", "--by", "operator", "--work-code", "W001", "--out", str(output)])
        result = M.run_migration_args(args)
        self.assertTrue(result["ready"])
        self.assertEqual(json.loads(output.read_text())["format"], M.FORMAT)
        self.assertFalse((self.project / M.MARKER).exists())
        with self.assertRaisesRegex(M.MigrationError, "输出已存在"):
            M.run_migration_args(args)

    def test_archive_media_copies_exact_bytes_reuses_blobs_and_rejects_conflicts(self):
        original = b"\x89PNG\r\n\x1a\nexact-original"
        _write(self.project, "one.png", original)
        _write(self.project, "copy.png", original)
        media_root = self.project.parent / "controlled"
        result = self.prepare(media_root=media_root, archive_media=True)
        self.assertTrue(result["ready"], result["blockers"])
        archive = result["manifest"]["preparation"]["media_archive"]
        self.assertEqual(archive["copied"], 1)
        item = result["manifest"]["preparation"]["file_inventory"][0]
        copy = media_root / item["object_key"]
        self.assertEqual(copy.read_bytes(), original)
        self.assertEqual((self.project / "one.png").read_bytes(), original)
        retry = self.prepare(media_root=media_root, archive_media=True)
        self.assertEqual(retry["manifest"]["preparation"]["media_archive"]["reused"], 1)
        copy.write_bytes(b"changed")
        with self.assertRaises(M.MigrationError) as caught:
            self.prepare(media_root=media_root, archive_media=True)
        self.assertEqual(caught.exception.code, "media_archive_conflict")

    def test_archive_media_rejects_symlink_and_escape_without_touching_sources(self):
        _write(self.project, "one.png", b"\x89PNG\r\n\x1a\nexact-original")
        root, outside = self.project.parent / "controlled", self.project.parent / "outside"
        root.mkdir(); outside.mkdir()
        (root / "blobs").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(M.MigrationError, "符号链接"):
            self.prepare(media_root=root, archive_media=True)
        self.assertFalse(list(outside.iterdir()))
        with self.assertRaisesRegex(M.MigrationError, "越过"):
            self.prepare(media_root=self.project.parent / "second", media_prefix="../escape", archive_media=True)

    def test_fixed_run_job_and_human_review_keep_evidence_and_reject_tampering(self):
        self.state["objects"] = [{"id": "E1", "kind": "episode", "parent": None}, {"id": "S1", "kind": "scene", "parent": "E1"},
            {"id": "Q1", "kind": "sequence", "parent": "S1"}, {"id": "H1", "kind": "shot", "parent": "Q1"}]
        sha = _write(self.project, "output.png", b"\x89PNG\r\n\x1a\noutput")
        batch_sha = _write(self.project, "batch.json", {"format": "vsc.production-batch/v1", "id": "BATCH", "jobs": [
            {"id": "J1", "kind": "image", "args": {"out": ".", "name": "candidate", "shot": "H1", "model": "synthetic"}}]})
        run = _artifact(self.project, self.state, "RUN", "vsc.production_run", {"format": "vsc.production-run/v1", "batch": {"path": "batch.json", "sha256": batch_sha}}, True)
        binding = {"project_id": self.state["project_id"], "kind": "image", "shot_id": "H1", "inputs": {"prompt": "synthetic"}, "model": "synthetic"}
        record = {"format": "vsc.generation-record/v1", "kind": "image", "shot_id": "H1", "inputs": binding["inputs"],
            "engine": {"provider": "synthetic", "model": "synthetic", "version": "1", "request_sha256": M._digest(binding)},
            "status": "succeeded", "outputs": [{"path": "output.png", "sha256": sha}]}
        gen = _artifact(self.project, self.state, "GEN", "vsc.generation_record", record)
        _write(self.project, "candidate-生成记录.json", record)
        _write(self.project, "task.json", {"binding": binding, "record": record})
        _write(self.project, ".vsc-production/BATCH.json", {"format": "vsc.production-journal/v1", "id": "BATCH", "jobs": {"J1": {"status": "succeeded", "attempts": 1, "inputs_sha256": {}, "outputs_sha256": {"output.png": sha}}}})
        self.state["production_reviews"] = [{"run_id": "RUN", "run_sha256": run["sha256"], "job_id": "J1", "outputs_sha256": {"output.png": sha},
            "by": "original-reviewer", "reason": "原始拒绝原因", "outcome": "rejected", "at": "2026-01-01T11:00:00"}]
        result = self.prepare(work_code="W001")
        self.assertTrue(result["ready"], result["blockers"])
        manifest = result["manifest"]
        self.assertEqual(len(manifest["tables"]["generation_jobs"]), 1)
        self.assertEqual(manifest["tables"]["media_reviews"][0]["outcome"], "fail")
        self.assertFalse(manifest["tables"].get("current_bindings"))
        for field, value in (("outcome", "pass"), ("reviewer", "invented"), ("reason", "invented")):
            modified = copy.deepcopy(manifest)
            modified["tables"]["media_reviews"][0][field] = value
            with self.assertRaisesRegex(M.MigrationError, "人工素材审核"):
                M.validate_manifest(self.project, modified)

    def test_physical_magic_recognizes_raw_mp3_ogg_flac_and_does_not_call_adts_mp3(self):
        from vsc.project.migration_prepare import classify_file
        cases = {"mpeg": (b"\xff\xfb\x90\xc0" + bytes(20), "audio/mpeg"),
            "adts": (b"\xff\xf1\x50\x80" + bytes(20), "audio/aac"),
            "ogg": (b"OggS" + bytes(20), "audio/ogg"), "flac": (b"fLaC" + bytes(20), "audio/flac")}
        for name, (raw, mime) in cases.items():
            _write(self.project, name + ".bin", raw)
            self.assertEqual(classify_file(self.project / (name + ".bin"))["mime_type"], mime)
        for index, header in enumerate((b"\xff\xfb\xf0\xc0", b"\xff\xfb\x9c\xc0", b"\xff\xeb\x90\xc0")):
            _write(self.project, "invalid" + str(index), header + bytes(20))
            self.assertNotEqual(classify_file(self.project / ("invalid" + str(index)))["mime_type"], "audio/mpeg")

    def test_naive_source_timestamps_keep_original_strings_and_explicit_zone(self):
        artifact = _artifact(self.project, self.state, "BRIEF", "vsc.creative_brief", {"text": "synthetic"}, True)
        artifact["created_at"] = "2026-01-01T09:30:00"
        result = self.prepare(source_timezone="Asia/Shanghai")
        self.assertTrue(result["ready"], result["blockers"])
        row = next(r for r in result["manifest"]["tables"]["artifact_versions"] if r["artifact_key"] == "BRIEF")
        self.assertEqual(row["created_at"], "2026-01-01T09:30:00+08:00")
        self.assertIn({"table": "artifact_versions", "key": {"project_id": result["manifest"]["target_project_id"], "id": row["id"]},
            "column": "created_at", "original": "2026-01-01T09:30:00"}, result["manifest"]["preparation"]["original_naive_timestamps"])
        self.assertEqual(json.loads((self.project / "vsc.json").read_text())["artifacts"][0]["created_at"], "2026-01-01T09:30:00")
        self.assertTrue(M._equal(datetime.fromisoformat(row["created_at"]), datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)))


@unittest.skipUnless(TEST_URL and HAS_DB, "requires explicit isolated PostgreSQL URL")
class PreparedGraphPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_postgres(cls, ROOT, TEST_URL)

    @classmethod
    def tearDownClass(cls):
        teardown_postgres(cls)

    def test_terminal_operation_is_finalized_after_input_output_graph_in_real_postgres(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "legacy"
            state = _legacy(project)
            input_sha = _write(project, "input.png", b"\x89PNG\r\n\x1a\ninput")
            output_sha = _write(project, "output.png", b"\x89PNG\r\n\x1a\noutput")
            _write(project, "record.json", {"format": "vsc.generation-record/v1", "kind": "image", "shot_id": None,
                "inputs": {"references": [{"path": "input.png", "sha256": input_sha}]}, "engine": {"provider": "synthetic", "model": "synthetic"},
                "status": "succeeded", "outputs": [{"path": "output.png", "sha256": output_sha}]})
            result = M.prepare(project, "migration-operator")
            self.assertTrue(result["ready"], result["blockers"])
            rows = M.validate_manifest(project, result["manifest"])
            with self.engine.connect() as conn:
                transaction = conn.begin()
                try:
                    M._insert_rows(conn, rows)
                    operation = conn.execute(select(S.media_operations).where(S.media_operations.c.project_id == result["manifest"]["target_project_id"])).mappings().one()
                    self.assertEqual(operation["status"], "succeeded")
                    self.assertEqual(len(conn.execute(select(S.operation_inputs).where(S.operation_inputs.c.operation_id == operation["id"])).all()), 1)
                    self.assertEqual(len(conn.execute(select(S.operation_outputs).where(S.operation_outputs.c.operation_id == operation["id"])).all()), 1)
                    with self.assertRaises(Exception):
                        conn.execute(S.operation_outputs.insert().values(project_id=operation["project_id"], id=str(__import__('uuid').uuid4()),
                            operation_id=operation["id"], media_id=rows["media_items"][0]["id"], role="late", ordinal=9))
                finally:
                    transaction.rollback()

    def test_two_projects_share_content_and_locations_without_merging_resource_contexts(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            manifests = []
            for number, name in enumerate(("same.txt", "same.json")):
                project = root / ("project" + str(number))
                state = _legacy(project)
                state["project_id"] += str(number)
                M._write(project / "vsc.json", state)
                _write(project, name, b"same bytes across extensions")
                prepared = M.prepare(project, "migration-operator", media_root=root / "controlled", archive_media=True)
                self.assertTrue(prepared["ready"], prepared["blockers"])
                manifests.append((project, prepared["manifest"]))
            self.assertEqual(manifests[0][1]["tables"]["blob_locations"][0]["id"], manifests[1][1]["tables"]["blob_locations"][0]["id"])
            self.assertEqual(manifests[0][1]["tables"]["media_blobs"][0]["mime_type"], "text/plain")
            self.assertEqual(manifests[0][1]["tables"]["media_blobs"], manifests[1][1]["tables"]["media_blobs"])
            with self.engine.connect() as conn:
                transaction = conn.begin()
                try:
                    for project, manifest in manifests:
                        M._insert_rows(conn, M.validate_manifest(project, manifest))
                    self.assertEqual(len(conn.execute(select(S.media_blobs)).all()), 1)
                    self.assertEqual(len(conn.execute(select(S.blob_locations)).all()), 1)
                    self.assertEqual(len(conn.execute(select(S.media_items)).all()), 2)
                    self.assertEqual(len(conn.execute(select(S.media_sources)).all()), 2)
                    for project, manifest in manifests:
                        M._compare_rows(conn, M.validate_manifest(project, manifest))
                finally:
                    transaction.rollback()

    def test_legacy_naive_time_roundtrip_and_compare_use_explicit_source_timezone(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve() / "legacy"
            state = _legacy(project)
            artifact = _artifact(project, state, "BRIEF", "vsc.creative_brief", {"text": "synthetic"}, True)
            artifact["created_at"] = "2026-01-01T09:30:00"
            M._write(project / "vsc.json", state)
            result = M.prepare(project, "migration-operator", source_timezone="Asia/Shanghai")
            self.assertTrue(result["ready"], result["blockers"])
            tables = M.validate_manifest(project, result["manifest"])
            with self.engine.connect() as conn:
                transaction = conn.begin()
                try:
                    M._insert_rows(conn, tables)
                    actual = conn.execute(select(S.artifact_versions.c.created_at).where(
                        S.artifact_versions.c.project_id == result["manifest"]["target_project_id"],
                        S.artifact_versions.c.artifact_key == "BRIEF")).scalar_one()
                    self.assertEqual(actual, datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc))
                    M._compare_rows(conn, tables)
                finally:
                    transaction.rollback()


if __name__ == "__main__":
    unittest.main()
