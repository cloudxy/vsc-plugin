"""Legacy migration inventory and explicit cutover against temporary PostgreSQL."""
import copy
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from support.paths import ROOT
from support.fixtures.migration import legacy, setup_postgres, teardown_postgres
from vsc.project import migration as M

HAS_DB = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


class LegacyInventoryTest(unittest.TestCase):
    def test_preview_is_readonly_and_reports_unknown_facts_and_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "legacy"
            state = legacy(project)
            state["new_relation"] = {"left": "A", "right": "B"}
            M._write(project / "vsc.json", state)
            (project / "unregistered.md").write_text("待登记文案。")
            before = {path.name: path.read_bytes() for path in project.iterdir()}
            result = M.preview(project)
            self.assertFalse(result["ready"])
            self.assertTrue(any("state:new_relation" in gap for gap in result["gaps"]))
            self.assertTrue(any("file:unregistered.md" in gap for gap in result["gaps"]))
            self.assertFalse((project / M.MARKER).exists())
            for name, original in before.items():
                self.assertEqual((project / name).read_bytes(), original)

    def test_sqlite_authority_is_read_without_modifying_database_or_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "legacy"
            legacy(project, sqlite=True)
            before = {name: (project / name).read_bytes() for name in ("vsc.json", ".vsc-series.sqlite3")}
            result = M.preview(project)
            self.assertEqual(result["source"]["authority"], "sqlite-series-v1")
            self.assertTrue(any(f["category"] == "sqlite:project_state" for f in result["manifest"]["inventory"]))
            for name, original in before.items():
                self.assertEqual((project / name).read_bytes(), original)
            (project / "vsc.json").write_text('{}')
            with self.assertRaisesRegex(M.MigrationError, "镜像与 SQLite"):
                M.preview(project)


@unittest.skipUnless(TEST_URL and HAS_DB, "requires explicit temporary PostgreSQL URL and postgres dependencies")
class PostgresMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_postgres(cls, ROOT, TEST_URL)

    @classmethod
    def tearDownClass(cls):
        teardown_postgres(cls)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "legacy"
        self.state = legacy(self.project)
        self.original = '{"format":"vsc.creative-brief/v1","text":"保留原字节、标点。"}\n'.encode()
        self.sha = hashlib.sha256(self.original).hexdigest()
        (self.project / "approved.json").write_bytes(self.original)
        self.state["artifacts"] = [{"id": "A-OLD", "type": "vsc.creative_brief", "stage": "brief", "scope": "project",
            "path": "approved.json", "sha256": self.sha, "status": "approved", "depends_on": [],
            "decision": {"by": "original-human", "status": "approved", "note": "原人工选择"}}]
        M._write(self.project / "vsc.json", self.state)
        self.manifest = M.preview(self.project)["manifest"]
        self.target = self.manifest["target_project_id"]
        artifact_id, decision_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.artifact_id = artifact_id
        artifact = {"project_id": self.target, "id": artifact_id, "artifact_key": "A-OLD", "version": 1,
                    "artifact_type": "vsc.creative_brief", "stage": "brief", "document": {"legacy_file": "approved.json"},
                    "mime_type": "application/json", "sha256": self.sha, "project_wide": True, "parser_version": "legacy/v1"}
        decision = {"project_id": self.target, "id": decision_id, "artifact_id": artifact_id, "outcome": "approve",
                    "actor": "original-human", "reason": "原人工选择", "decision_sequence": 1, "based_on_revision": 0}
        self.manifest["tables"]["artifact_versions"].append(artifact)
        self.manifest["tables"]["artifact_decisions"] = [decision]
        self.manifest["tables"]["current_artifact_versions"] = [{"project_id": self.target, "artifact_key": "A-OLD", "artifact_id": artifact_id, "decision_id": decision_id}]
        self.manifest["tables"]["projects"][0]["decision_sequence"] = 1
        artifact_ref = {"table": "artifact_versions", "key": {"project_id": self.target, "id": artifact_id}}
        decision_ref = {"table": "artifact_decisions", "key": {"project_id": self.target, "id": decision_id}}
        self.manifest["mappings"]["artifacts:A-OLD"] = {"targets": [artifact_ref, decision_ref]}
        self.manifest["mappings"]["file:approved.json"] = {"targets": [artifact_ref]}
        self.manifest["decision_evidence"]["artifact_decisions:" + decision_id] = "artifacts:A-OLD"
        self.manifest["id_mapping"]["A-OLD"] = artifact_id
        self.path = self.project / M.CONTROL / "manifest.json"
        self.persist()

    def persist(self):
        M._write(self.path, self.manifest)

    def rebase_manifest(self):
        previous = self.manifest
        old_target = self.target
        fresh = M.preview(self.project)["manifest"]
        self.target = fresh["target_project_id"]

        def replace(value):
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return self.target if value == old_target else value

        for name, rows in previous["tables"].items():
            if name != "projects":
                retained = [row for row in rows if row.get("artifact_type") != "vsc.legacy-snapshot/v1"]
                fresh["tables"].setdefault(name, []).extend(replace(retained))
        fresh["tables"]["projects"][0]["decision_sequence"] = previous["tables"]["projects"][0]["decision_sequence"]
        for key in ("artifacts:A-OLD", "file:approved.json"):
            fresh["mappings"][key] = replace(previous["mappings"][key])
        fresh["decision_evidence"] = previous["decision_evidence"]
        fresh["id_mapping"] = previous["id_mapping"]
        self.manifest = fresh
        self.persist()

    def frozen(self):
        M.backup(self.project, self.path, "migration-operator")
        M.freeze(self.project, self.path, "migration-operator")

    def imported(self):
        self.frozen()
        M.import_manifest(self.project, self.path, self.store, "migration-operator")

    def test_backup_freeze_import_compare_cutover_preserves_original_approval_and_bytes(self):
        from vsc.assets.resource_service import Conflict, ResourceError
        from vsc.project.state import save
        self.imported()
        with self.assertRaises(ResourceError):
            save(self.project, self.state)
        with self.assertRaises(Conflict) as caught:
            self.store.create_object(self.target, {"kind": "work", "display_code": "W1", "title": "forbidden", "ordinal": 0},
                                     actor="human", expected_revision=4, idempotency_key="before-activate")
        self.assertEqual(caught.exception.code, "migration_pending")
        M.import_manifest(self.project, self.path, self.store, "migration-operator")
        M.compare(self.project, self.path, self.store, "migration-operator")
        result = M.cutover(self.project, self.path, self.store, "VSC_DATABASE_URL", "migration-operator")
        self.assertEqual(result["pointer"]["storage_policy"], "postgres-series-v1")
        self.assertNotIn("postgresql", json.dumps(result["pointer"]))
        loaded = self.store.get_artifact_version(self.target, self.artifact_id)
        self.assertEqual(loaded["document"].encode("utf-8"), self.original)
        self.assertEqual(loaded["sha256"], self.sha)
        self.assertEqual((self.project / "approved.json").read_bytes(), self.original)
        self.assertEqual(self.store.get_project(self.target)["revision"], 5)
        self.assertEqual(M.cutover(self.project, self.path, self.store, "VSC_DATABASE_URL", "migration-operator"), result)

    def test_source_or_backup_changes_prevent_import(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.frozen()
        original = (self.project / "vsc.json").read_bytes()
        changed = copy.deepcopy(self.state); changed["revision"] += 1
        M._write(self.project / "vsc.json", changed)
        with self.assertRaises(M.MigrationError) as caught:
            M.import_manifest(self.project, self.path, self.store, "operator")
        self.assertEqual(caught.exception.code, "source_changed")
        (self.project / "vsc.json").write_bytes(original)
        record = M.status(self.project)["migration"]
        backup = self.project / record["backup"] / "files/approved.json"
        backup.write_bytes(b"changed")
        with self.assertRaises(M.MigrationError) as caught:
            M.import_manifest(self.project, self.path, self.store, "operator")
        self.assertEqual(caught.exception.code, "backup_changed")
        with self.engine.connect() as conn:
            self.assertIsNone(conn.execute(select(S.projects).where(S.projects.c.id == self.target)).first())
        self.assertFalse((self.project / M.POINTER).exists())

    def test_sqlite_provenance_keeps_original_nested_approval_reason(self):
        from vsc.adapters.persistence.sqlite import series
        self.state["profile_snapshot"]["storage_policy"] = series.POLICY
        self.state["profile_sha256"] = M._digest(self.state["profile_snapshot"])
        M._write(self.project / "vsc.json", self.state)
        series.commit_state(self.project, self.state, 3)
        self.rebase_manifest()
        artifact_mapping = self.manifest["mappings"]["artifacts:A-OLD"]
        decision_ref = next(ref for ref in artifact_mapping["targets"] if ref["table"] == "artifact_decisions")
        for fact in self.manifest["inventory"]:
            if fact["category"] == "sqlite:artifact_versions":
                self.manifest["mappings"][fact["key"]] = copy.deepcopy(artifact_mapping)
            elif fact["category"] == "sqlite:approval_decisions":
                self.manifest["mappings"][fact["key"]] = {"targets": [decision_ref]}
                self.manifest["decision_evidence"]["artifact_decisions:" + decision_ref["key"]["id"]] = fact["key"]
        self.persist()
        self.imported()
        record = M.status(self.project)["migration"]
        self.assertTrue((self.project / record["backup"] / ".vsc-series.sqlite3").is_file())
        M.compare(self.project, self.path, self.store, "operator")
        self.assertEqual(M.cutover(self.project, self.path, self.store, "VSC_DATABASE_URL", "operator")["status"], "cut_over")

    def test_fixed_asset_versions_cannot_be_replaced_by_archive_only(self):
        self.state["artifacts"][0]["asset_versions"] = {"legacy-character": {"id": "A-OLD", "sha256": self.sha}}
        M._write(self.project / "vsc.json", self.state)
        self.rebase_manifest()
        with self.assertRaises(M.MigrationError) as caught:
            M.validate_manifest(self.project, self.manifest)
        self.assertEqual(caught.exception.code, "asset_versions_unmapped")
        self.assertFalse((self.project / M.POINTER).exists())

    def test_mapping_requires_real_decision_identity_known_columns_and_project_isolation(self):
        M.validate_manifest(self.project, self.manifest)
        for kind in ("actor", "unknown_column", "cross_project", "incomplete"):
            value = copy.deepcopy(self.manifest)
            if kind == "actor":
                value["tables"]["artifact_decisions"][0]["actor"] = "forged-human"
            elif kind == "unknown_column":
                value["tables"]["artifact_versions"][0]["universal_payload"] = {}
            elif kind == "cross_project":
                value["tables"]["artifact_versions"][0]["project_id"] = str(uuid.uuid4())
            else:
                value["mappings"].pop("file:approved.json")
            with self.subTest(kind=kind), self.assertRaises(M.MigrationError):
                M.validate_manifest(self.project, value)
        self.assertFalse((self.project / M.POINTER).exists())

    def test_foreign_key_failure_rolls_back_entire_import(self):
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        self.manifest["tables"]["artifact_dependencies"] = [{"project_id": self.target, "artifact_id": self.artifact_id, "dependency_id": str(uuid.uuid4())}]
        self.persist()
        self.frozen()
        with self.assertRaises(IntegrityError):
            M.import_manifest(self.project, self.path, self.store, "operator")
        with self.engine.connect() as conn:
            self.assertIsNone(conn.execute(select(S.projects).where(S.projects.c.id == self.target)).first())
        self.assertEqual(M.status(self.project)["migration"]["status"], "frozen")

    def test_activation_commit_failure_stays_readonly_and_retry_recovers(self):
        from vsc.assets.resource_service import Conflict
        self.imported()
        M.compare(self.project, self.path, self.store, "operator")
        original_begin = self.engine.begin

        @contextlib.contextmanager
        def abort_after_write():
            with original_begin() as conn:
                yield conn
                raise RuntimeError("simulated activation commit failure")

        with patch.object(self.engine, "begin", abort_after_write), self.assertRaises(RuntimeError):
            M.cutover(self.project, self.path, self.store, "VSC_DATABASE_URL", "operator")
        self.assertTrue((self.project / M.POINTER).exists())
        with self.assertRaises(Conflict) as caught:
            self.store.create_object(self.target, {"kind": "work", "display_code": "W1", "title": "forbidden", "ordinal": 0},
                                     actor="human", expected_revision=4, idempotency_key="still-frozen")
        self.assertEqual(caught.exception.code, "migration_pending")
        self.assertEqual(M.cutover(self.project, self.path, self.store, "VSC_DATABASE_URL", "operator")["status"], "cut_over")


if __name__ == "__main__":
    unittest.main()
