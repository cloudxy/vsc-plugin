import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from support.paths import ROOT
from vsc.assets.resource_service import ResourceError
from vsc.project.pg_workflow import authority_pointer, check_gate, legacy_write_guard


class AuthorityAndGateTests(unittest.TestCase):
    def test_cutover_or_freeze_blocks_legacy_write_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_write_guard(root)
            (root / ".vsc-migration.json").write_text(json.dumps({"status": "frozen"}))
            with self.assertRaises(ResourceError) as frozen:
                legacy_write_guard(root)
            self.assertEqual(frozen.exception.code, "migration_frozen")
            (root / ".vsc-postgres.json").write_text(json.dumps({"storage_policy": "postgres-series-v1", "project_id": "fixed-id"}))
            self.assertEqual(authority_pointer(root)["project_id"], "fixed-id")
            with self.assertRaises(ResourceError) as changed:
                legacy_write_guard(root)
            self.assertEqual(changed.exception.code, "authority_changed")

    def test_gate_uses_pinned_profile_and_current_approved_versions(self):
        service = Mock()
        service.get_project.return_value = {"revision": 4, "profile_snapshot": {"stages": [
            {"id": "design", "required": ["plain-spec"]}]}}
        service.list_artifacts.return_value = {"items": [{"id": "a", "artifact_type": "plain-spec", "stage": "design", "approved": True, "current": False}]}
        self.assertFalse(check_gate(service, "p", "design")["passed"])
        service.list_artifacts.return_value["items"][0]["current"] = True
        service.get_artifact_version.return_value = {"id": "a", "sha256": "fixed", "document": "fixed spec"}
        self.assertTrue(check_gate(service, "p", "design")["passed"])

    def test_scoped_profile_cannot_approve_project_wide_empty_gate(self):
        service = Mock()
        service.get_project.return_value = {"revision": 0, "profile_snapshot": {"scope_required_from": "script", "stages": [
            {"id": "script", "required": []}]}}
        service.get_project_tree.return_value = {"nodes": []}
        self.assertEqual(check_gate(service, "p", "script")["gaps"], [{"code": "scope_required"}])
        service.list_artifacts.assert_not_called()

    def test_frozen_sqlite_connection_rejects_direct_mutations(self):
        import sqlite3
        from vsc.adapters.persistence.sqlite import series
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"revision": 1, "objects": [], "artifacts": [], "sources": [], "decisions": []}
            series.commit_state(root, state, 0)
            (root / ".vsc-migration.json").write_text(json.dumps({"status": "frozen"}))
            with series.connect(root) as connection:
                self.assertEqual(connection.execute("SELECT revision FROM project_state").fetchone()[0], 1)
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute("UPDATE project_state SET revision=2")
            with self.assertRaises(series.SeriesStoreError):
                series.commit_state(root, state, 1)

    def test_later_gate_cannot_skip_prior_stage_or_source(self):
        service = Mock()
        service.get_project.return_value = {"revision": 0, "profile_snapshot": {"stages": [
            {"id": "brief", "required": ["brief-spec"]}, {"id": "post", "required": []}]}}
        service.list_artifacts.return_value = {"items": []}
        service.list_sources.return_value = []
        result = check_gate(service, "p", "post")
        self.assertEqual({gap["code"] for gap in result["gaps"]}, {"source_required", "missing_or_conflicting_artifact"})
