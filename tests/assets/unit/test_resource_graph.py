"""Query validation and explicit legacy authority boundaries."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT
from vsc.assets.resource_graph import ResourceGraph, validate_query
from vsc.assets.resource_service import ResourceError, Conflict
from vsc.project.resource_catalog import ResourceCatalog


class ResourceGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node for actual frontend module execution")
    def test_frontend_race_focus_and_view_preferences(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/support/fixtures/frontend/resource_canvas_dom.cjs"),
                                 str(ROOT / "src/vsc/interfaces/web/static/canvas.js")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bounded_input_contract(self):
        for kwargs in ({"depth": 9}, {"depth": True}, {"limit": 301}, {"limit": 0}, {"offset": -1}, {"direction": "sideways"},
                       {"focus": "blob:123"}, {"focus": "media:"}, {"focus": "media:123", "offset": 1}, {"revision": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ResourceError):
                validate_query(**kwargs)

    def test_legacy_inventory_stays_disconnected_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "demo"
            project.mkdir()
            marker = project / "vsc.json"
            marker.write_text(json.dumps({"project_id": "legacy", "revision": 3, "title": "synthetic", "objects": [{"id": "SH1", "kind": "shot"}]}))
            (project / "SH1-output.mp4").write_bytes(b"synthetic")
            graph = ResourceGraph(ResourceCatalog(directory))
            result = graph.query("legacy")
            self.assertEqual(len(result["nodes"]), 1)
            self.assertEqual(result["edges"], [])
            self.assertTrue(result["read_only"])
            self.assertTrue(result["warnings"])
            self.assertEqual(graph.query("legacy", object_id="SH1")["nodes"], [])
            focused = graph.query("legacy", focus=result["nodes"][0]["id"])
            self.assertEqual(focused["nodes"][0]["id"], result["nodes"][0]["id"])
            self.assertEqual(json.loads(marker.read_text())["revision"], 3)
            with self.assertRaises(Conflict):
                graph.query("legacy", revision=2)
            marker.write_text(json.dumps({"project_id": "legacy", "profile_snapshot": {"storage_policy": "postgres-series-v1"}}))
            with self.assertRaises(Exception) as raised:
                graph.query("legacy")
            self.assertEqual(raised.exception.code, "authority_unavailable")


if __name__ == "__main__":
    unittest.main()
