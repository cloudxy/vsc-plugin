"""Graph projection against random PostgreSQL schemas and synthetic resources."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS, "requires explicit isolated PostgreSQL test connection")
class ResourceGraphPostgresTests(ResourceStoreFixture, unittest.TestCase):
    def graph(self, **options):
        from vsc.assets.resource_graph import ResourceGraph
        from vsc.project.resource_catalog import ResourceCatalog
        with tempfile.TemporaryDirectory() as directory:
            return ResourceGraph(ResourceCatalog(directory, service=self.service)).query(self.p, **options)

    def test_multi_input_direction_and_project_isolation(self):
        from vsc.assets.resource_service import NotFound, Conflict
        first, output = self.media("reference"), self.media("composite")
        op = self.write("create_media_operation", {"operation_type": "composite", "recipe_version": "1", "tool": "offline", "tool_version": "1",
            "inputs": [{"media_id": first, "role": "background"}, {"media_id": first, "role": "foreground"}], "outputs": [{"media_id": output}]})
        before = self.rev
        result = self.graph(focus="operation:" + op["id"], depth=1)
        self.assertEqual({edge["evidence"]["role"] for edge in result["edges"] if edge["kind"] == "operation_input"}, {"background", "foreground"})
        self.assertEqual(len({edge["id"] for edge in result["edges"]}), len(result["edges"]))
        upstream = self.graph(focus="operation:" + op["id"], direction="upstream", depth=1)
        self.assertIn("media:" + first, {node["id"] for node in upstream["nodes"]})
        self.assertNotIn("media:" + output, {node["id"] for node in upstream["nodes"]})
        downstream = self.graph(focus="operation:" + op["id"], direction="downstream", depth=1)
        self.assertIn("media:" + output, {node["id"] for node in downstream["nodes"]})
        self.assertNotIn("media:" + first, {node["id"] for node in downstream["nodes"]})
        self.assertEqual(self.store.get_project(self.p)["revision"], before)
        other = self.service.create_project({"name": "other"}, actor="test-human")["id"]
        from vsc.adapters.persistence.postgres.resource_graph import query_graph
        with self.assertRaises(NotFound):
            query_graph(self.store, other, focus="media:" + first)
        self.assertEqual(query_graph(self.store, other)["nodes"], [])
        with self.assertRaises(Conflict):
            self.graph(revision=before - 1)

    def test_versions_generation_adoption_timeline_and_render(self):
        # The shared synthetic fixture creates official decisions and fixed
        # inputs through production APIs; no real provider is ever invoked.
        self.seed_generation_timeline_render()
        graph = self.graph(limit=300, depth=0)
        kinds = {edge["kind"] for edge in graph["edges"]}
        self.assertTrue({"spec_input", "run_input", "generation_input", "generation_output", "candidate", "selected",
                         "timeline_media", "timeline_item", "render_timeline", "render_input", "render_output"}.issubset(kinds), kinds)
        self.assertTrue(all(edge["source"] in {n["id"] for n in graph["nodes"]} and edge["target"] in {n["id"] for n in graph["nodes"]} for edge in graph["edges"]))
        timeline = next(edge for edge in graph["edges"] if edge["kind"] == "timeline_media")
        self.assertEqual(timeline["evidence"]["source_out_frame"], 120)
        # Retired video adoption disappears, but fixed historical usage survives.
        self.assertFalse(any(edge["kind"] == "selected" and edge["source"] == timeline["source"] for edge in graph["edges"]))
        self.assertTrue(any(edge["kind"] == "candidate" and edge["source"] == timeline["source"] for edge in graph["edges"]))
        serialized = json.dumps(graph)
        for private in ("request_payload", "raw_response", "original_uri", "auth_ref", "document", "object_key"):
            self.assertNotIn('"' + private + '":', serialized)
        self.assertEqual(graph["revision"], self.rev)
        self.assertEqual(graph["snapshot"], "repeatable_read")

    def test_scope_limits_and_stable_pages_keep_isolated_nodes(self):
        from vsc.assets.resource_service import NotFound
        objects = self.hierarchy()
        a, b = self.media("a"), self.media("b")
        self.select(self.candidate(objects["shot"], a))
        result = self.graph(object_id=objects["shot"], depth=2)
        self.assertIn("media:" + a, {node["id"] for node in result["nodes"]})
        self.assertNotIn("media:" + b, {node["id"] for node in result["nodes"]})
        isolated = self.graph(focus="media:" + b, depth=0)
        self.assertEqual(len(isolated["nodes"]), 1)
        self.assertEqual(isolated["edges"], [])
        first = self.graph(limit=2, depth=0)
        second = self.graph(limit=2, depth=0, offset=first["next_offset"], revision=first["revision"])
        self.assertTrue(first["truncated"])
        self.assertFalse({node["id"] for node in first["nodes"]} & {node["id"] for node in second["nodes"]})
        tiny = self.graph(focus="object:" + objects["shot"], limit=1)
        self.assertEqual(len(tiny["nodes"]), 1)
        self.assertIn("node_limit", tiny["truncation_reasons"])
        with self.assertRaises(NotFound):
            self.graph(object_id="00000000-0000-0000-0000-000000000000")


if __name__ == "__main__":
    unittest.main()
