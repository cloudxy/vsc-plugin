import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from support.paths import ROOT
from vsc.assets.resource_service import ResourceError
from vsc.project.pg_workflow import authority_pointer, check_gate, create_project, legacy_write_guard
from vsc.project.migration import _digest


def migrated_gate_service():
    profile = {"profile_id": "synthetic-legacy", "stages": [{"id": "design", "required": ["plain-spec"]}]}
    state = {"project_id": "legacy-project", "profile_snapshot": profile,
             "artifacts": [{"sha256": "sha-a"}, {"sha256": "sha-b"}]}
    snapshot = {"format": "vsc.legacy-snapshot/v1", "state": state,
        "source": {"authority": "legacy-json", "legacy_project_id": "legacy-project", "state_sha256": _digest(state)}}
    rows = [{"id": "b", "artifact_key": "right-stream", "artifact_type": "plain-spec", "stage": "design", "approved": True,
                "current": True, "parser_version": "legacy-relations/v1", "sha256": "sha-b", "created_at": "2026-01-02"},
            {"id": "a", "artifact_key": "left-stream", "artifact_type": "plain-spec", "stage": "design", "approved": True,
                "current": True, "parser_version": "legacy-relations/v1", "sha256": "sha-a", "created_at": "2026-01-01"},
            {"id": "snapshot", "artifact_type": "vsc.legacy-snapshot/v1", "stage": "migration", "parser_version": "vsc-migration/v1"}]
    versions = {"a": {"id": "a", "sha256": "sha-a", "document": "valid-a"},
                "b": {"id": "b", "sha256": "sha-b", "document": "valid-b"},
                "snapshot": {"id": "snapshot", "document": json.dumps(snapshot)}}
    service = Mock()
    service.store.engine.connect.return_value = MagicMock()
    service.get_project.return_value = {"revision": 10, "profile_snapshot": profile}
    service.list_artifacts.return_value = {"items": rows}
    service.get_artifact_version.side_effect = lambda project, version: versions[version]
    return service, versions


class AuthorityAndGateTests(unittest.TestCase):
    def test_pg_creation_selects_light_profile_without_changing_legacy_snapshot(self):
        from vsc.project.state import profile_for
        service = Mock()
        service.create_project.return_value = {"id": "project", "revision": 0}
        service.create_object.return_value = {"id": "work", "revision": 1}
        create_project(service, "Synthetic short", "fixture-human", profile_id="vsc.light-short")
        payload = service.create_project.call_args.args[0]
        snapshot = payload["profile_snapshot"]
        self.assertEqual(snapshot["profile_id"], "vsc.light-short")
        self.assertEqual(snapshot["production_policy"], "light-short-v1")
        self.assertEqual(snapshot["storage_policy"], "postgres-series-v1")
        self.assertEqual([stage["id"] for stage in snapshot["stages"]], ["brief", "script", "design", "production", "post", "delivery"])
        self.assertNotIn("vsc.animatic", snapshot["dependency_requirements"]["vsc.selected_takes"])
        self.assertNotIn("storage_policy", profile_for("vsc.light-short"))
        with self.assertRaises(ResourceError):
            create_project(service, "Synthetic short", "fixture-human", profile_id="vsc.series-db")

    def test_multi_scene_plans_partition_gate_and_keep_overlaps_actionable(self):
        service = Mock()
        service.store.engine.connect.return_value = MagicMock()
        service.get_project.return_value = {"revision": 4, "profile_snapshot": {"scope_required_from": "design",
            "stages": [{"id": "design", "required": ["vsc.shot_plan"]}]}}
        nodes = [{"id": "ep", "kind": "episode", "parent_id": None, "display_code": "EP"}]
        rows, versions = [], {}
        for number in range(3):
            scene, shot, identifier = "scene" + str(number), "shot" + str(number), "plan" + str(number)
            nodes.extend([{"id": scene, "kind": "scene", "parent_id": "ep", "display_code": scene},
                          {"id": shot, "kind": "shot", "parent_id": scene, "display_code": shot}])
            rows.append({"id": identifier, "artifact_type": "vsc.shot_plan", "stage": "design", "current": True,
                         "approved": True, "project_wide": False, "object_ids": ["ep"]})
            versions[identifier] = {"id": identifier, "sha256": identifier, "document": json.dumps({
                "format": "vsc.continuity-plan/v1", "scene_id": scene, "shots": [{"id": shot}]})}
        service.get_project_tree.return_value = {"nodes": nodes}
        service.list_artifacts.return_value = {"items": rows}
        service.get_artifact_version.side_effect = lambda project, identifier: versions[identifier]
        with patch("vsc.project.pg_workflow.validate_contract", return_value=[]), patch(
                "vsc.adapters.persistence.postgres.creative_rules.artifact_rule_report", return_value={"errors": [], "warnings": []}):
            result = check_gate(service, "p", "design", "ep")
        self.assertTrue(result["passed"], result["gaps"])
        self.assertEqual(len(result["artifacts"]), 3)
        versions["plan1"]["document"] = json.dumps({"format": "vsc.continuity-plan/v1", "scene_ids": ["scene0", "scene1"],
                                                     "shots": [{"id": "shot0"}, {"id": "shot1"}]})
        result = check_gate(service, "p", "design", "ep")
        conflict = next(gap for gap in result["gaps"] if gap["code"] == "plan_scope_conflict")
        self.assertEqual(conflict["shot_id"], "shot0")
        self.assertEqual(set(conflict["artifact_ids"]), {"plan0", "plan1"})

    def test_explicit_multiscene_scope_does_not_leak_to_another_scene(self):
        from vsc.project.plan_scope import plan_applies
        document = {"format": "vsc.continuity-plan/v1", "scene_id": "SC1", "scene_ids": ["SC1", "SC2"],
                    "shots": [{"id": "SH1"}, {"id": "SH2"}]}
        self.assertTrue(plan_applies({"document": document}, {"scene": {"SC2"}, "shot": {"SH2"}}))
        self.assertFalse(plan_applies({"document": document}, {"scene": {"SC3"}, "shot": {"SH2"}}))
        del document["scene_ids"]
        self.assertFalse(plan_applies({"document": document}, {"scene": {"SC2"}, "shot": {"SH2"}}))

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
        service.store.engine.connect.return_value = MagicMock()
        service.get_project.return_value = {"revision": 4, "profile_snapshot": {"stages": [
            {"id": "design", "required": ["plain-spec"]}]}}
        service.list_artifacts.return_value = {"items": [{"id": "a", "artifact_type": "plain-spec", "stage": "design", "approved": True, "current": False}]}
        self.assertFalse(check_gate(service, "p", "design")["passed"])
        service.list_artifacts.return_value["items"][0]["current"] = True
        service.get_artifact_version.return_value = {"id": "a", "sha256": "fixed", "document": "fixed spec"}
        self.assertTrue(check_gate(service, "p", "design")["passed"])

    def test_scoped_profile_cannot_approve_project_wide_empty_gate(self):
        service = Mock()
        service.store.engine.connect.return_value = MagicMock()
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
        service.store.engine.connect.return_value = MagicMock()
        service.get_project.return_value = {"revision": 0, "profile_snapshot": {"stages": [
            {"id": "brief", "required": ["brief-spec"]}, {"id": "post", "required": []}]}}
        service.list_artifacts.return_value = {"items": []}
        service.list_sources.return_value = []
        result = check_gate(service, "p", "post")
        self.assertEqual({gap["code"] for gap in result["gaps"]}, {"source_required", "missing_or_conflicting_artifact"})

    def test_migrated_legacy_gate_keeps_all_valid_independent_stream_pins(self):
        service, versions = migrated_gate_service()
        with patch("vsc.project.pg_workflow.validate_contract", return_value=[]) as validate:
            gate = check_gate(service, "p", "design")
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["artifacts"], [{"id": "a", "sha256": "sha-a"}, {"id": "b", "sha256": "sha-b"}])
        self.assertEqual([call.args[0] for call in validate.call_args_list], ["valid-a", "valid-b"])
        versions["a"]["document"] = "invalid-a"
        with patch("vsc.project.pg_workflow.validate_contract", side_effect=lambda doc, *_: ["original contract error"] if doc == "invalid-a" else []):
            gate = check_gate(service, "p", "design")
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["artifacts"], [{"id": "b", "sha256": "sha-b"}])

    def test_new_pg_and_unmigrated_custom_profile_keep_strict_conflict_rule(self):
        for variant in ("series-pg", "custom", "tampered-proof"):
            with self.subTest(variant=variant):
                service, versions = migrated_gate_service()
                if variant == "series-pg":
                    service.get_project.return_value["profile_snapshot"]["storage_policy"] = "postgres-series-v1"
                    service.get_project.return_value["profile_snapshot"]["profile_id"] = "vsc.series-pg"
                elif variant == "custom":
                    service.list_artifacts.return_value["items"] = service.list_artifacts.return_value["items"][:2]
                else:
                    snapshot = json.loads(versions["snapshot"]["document"])
                    snapshot["source"]["state_sha256"] = "wrong"
                    versions["snapshot"]["document"] = json.dumps(snapshot)
                with patch("vsc.project.pg_workflow.validate_contract") as validate:
                    gate = check_gate(service, "p", "design")
                self.assertEqual(gate["gaps"], [{"code": "missing_or_conflicting_artifact", "artifact_type": "plain-spec", "count": 2}])
                validate.assert_not_called()

    def test_migrated_legacy_gate_reports_original_contract_errors_when_all_streams_invalid(self):
        service, _ = migrated_gate_service()
        with patch("vsc.project.pg_workflow.validate_contract", side_effect=lambda doc, *_: ["invalid: " + doc]):
            gate = check_gate(service, "p", "design")
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["artifacts"])
        self.assertEqual(gate["gaps"], [{"code": "invalid_contract", "artifact_id": "a", "errors": ["invalid: valid-a"]},
            {"code": "invalid_contract", "artifact_id": "b", "errors": ["invalid: valid-b"]}])
