"""B4-02 payload 对照、B3-03 任务尝试对照与 B3-06 整理预览（离线纯函数）。"""
import json
import tempfile
import unittest
from pathlib import Path

import support.paths  # noqa: F401
from vsc.production.performance import performance_payload_coverage
from vsc.project.organize import organize_preview


class PayloadCoverageTest(unittest.TestCase):
    MODEL = {"capabilities": {"performance_controls": {"rate": "speech_rate", "delivery": "context_texts"}},
             "default_params": {"speech_rate": 1.0}}

    def test_consumed_unconsumed_and_unsupported_fields_listed(self):
        result = performance_payload_coverage({"delivery": "speech", "emotion": "温柔",
            "controls": [{"field": "rate", "model_default": "speech_rate", "expected": 1.0},
                         {"field": "pace", "model_default": "pace_key", "expected": "x"}]}, self.MODEL)
        self.assertEqual([row["consumed"] for row in result["controls"]], [True, False])
        self.assertEqual(result["fields_without_model_control"], ["emotion"])
        self.assertIn("speech_rate", result["payload_note"])

    def test_empty_controls_yield_empty_rows(self):
        self.assertEqual(performance_payload_coverage({"delivery": "speech"}, self.MODEL)["controls"], [])

    def test_configured_value_is_not_consumption_when_effective_request_drops_it(self):
        model={"capabilities":{"performance_controls":{"delivery":"context_texts","rate":"speech_rate","pace":"unmapped"}},
               "default_params":{"context_texts":["whisper"],"speech_rate":0,"unmapped":"x"}}
        params={"controls":[{"field":"delivery","model_default":"context_texts","expected":["whisper"]},
                            {"field":"pace","model_default":"unmapped","expected":"x"}]}
        self.assertEqual([r['consumed'] for r in performance_payload_coverage(params,model)['controls']],[True,False])
        result=performance_payload_coverage(params,model,{"req_params":{"audio_params":{"speech_rate":0}}})
        self.assertEqual([r['consumed'] for r in result['controls']],[False,False])


class OrganizePreviewTest(unittest.TestCase):
    def test_five_categories_and_readonly(self):
        import hashlib
        from vsc.project.migration import inventory
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            digest = hashlib.sha256(b"synthetic").hexdigest()
            paths = ["final.mp4", "old.mp4", "unknown.mp4", "backup.mp4", "source.mp4", "preview.mp4", "recover.mp4", ".vsc-local/unknown.png"]
            for relative in paths:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic")
            state = {"project_id": "isolated", "artifacts": [
                {"id": "old", "path": "old.mp4", "sha256": digest, "status": "approved", "superseded_by": "final"},
                {"id": "final", "path": "final.mp4", "sha256": digest, "status": "approved"}],
                "events": [{"id": "evt", "event": "schema_migrated", "backup": "backup.mp4"}]}
            (project / "vsc.json").write_text(json.dumps(state))
            recovery = project / ".vsc-production/recovery.json"
            recovery.parent.mkdir()
            recovery.write_text(json.dumps({"format": "vsc.production-journal/v1", "jobs": {
                "job": {"outputs_sha256": {"recover.mp4": digest}}}}))
            snapshot = inventory(project)
            # Exact typed fact shape emitted by SQLite inventory, including its
            # explicit local preview recipe and immutable original source.
            snapshot["facts"].extend([
                {"key": "parent", "category": "sqlite:media_assets", "payload": {"id": "P", "path": "source.mp4", "sha256": digest}},
                {"key": "child", "category": "sqlite:media_assets", "payload": {"id": "C", "path": "preview.mp4", "sha256": digest}},
                {"key": "preview", "category": "sqlite:asset_derivations", "payload": {"parent_id": "P", "child_id": "C", "relation": "proxy_video",
                 "parameters": json.dumps({"recipe_version": "vsc-preview-v1", "source_sha256": digest})}}])
            before = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            result = organize_preview(project, snapshot)
            self.assertTrue(all(result["counts"].values()))
            self.assertIn("final.mp4", result["files"]["current"])
            self.assertEqual(result["files"]["history"], ["old.mp4", "source.mp4"])
            self.assertEqual(result["files"]["renewable"], ["preview.mp4"])
            self.assertIn("unknown.mp4", result["files"]["unknown"])
            self.assertIn(".vsc-local/unknown.png", result["files"]["unknown"])
            self.assertIn("recover.mp4", result["files"]["backup"])
            self.assertTrue(next(row for row in result["details"] if row["path"] == "final.mp4")["references"])
            self.assertEqual(before, {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()})
            self.assertTrue(result["read_only"])
            self.assertIn("不计为清理完成", result["meaning"])
            self.assertIn("未知归属", result["actions"]["unknown"])
            snapshot["facts"].append({"key": "selected-preview", "category": "sqlite:media_bindings", "payload": {
                "id": "B", "media_id": "C", "status": "approved"}})
            bound = organize_preview(project, snapshot)
            self.assertIn("preview.mp4", bound["files"]["current"])
            self.assertEqual(bound["files"]["renewable"], [])

    def test_inventory_input_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            result = organize_preview(project, inventory={"files": [{"path": "06-素材/a.png"}, {"path": "x.md"}]})
            self.assertEqual(result["counts"]["renewable"], 0)
            self.assertEqual(result["counts"]["unknown"], 2)

    def test_current_consumer_keeps_its_superseded_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "old.json").write_text("{}")
            (project / "new.json").write_text("{}")
            result = organize_preview(project, {"state": {"artifacts": [
                {"id": "old", "path": "old.json", "superseded_by": "new"},
                {"id": "new", "path": "new.json", "depends_on": ["old"]}]}})
            self.assertEqual(result["files"]["current"], ["new.json", "old.json"])
            self.assertEqual(result["files"]["history"], [])

    def test_source_checkout_cli_starts_without_installed_package(self):
        import subprocess
        import sys
        from support.paths import ROOT
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "unknown.mp4").write_bytes(b"synthetic")
            completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/project/organize.py"), str(project)], cwd=temp, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["files"]["unknown"], ["unknown.mp4"])

    def test_postgres_pointer_never_falls_back_to_legacy_mirror(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / ".vsc-postgres.json").write_text("{}")
            (project / "vsc.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "不能用旧镜像"):
                organize_preview(project)


if __name__ == "__main__":
    unittest.main()
