"""Standard VSC SOP arguments use real PostgreSQL without a JSON state fork."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from support.paths import ROOT
from support.fixtures.postgres import isolated_postgres

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires explicit PostgreSQL test URL")
class PGStateBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(TEST_URL)
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        from vsc.project.pg_workflow import create_project
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(Path(self.temp.name) / "media"))
        self.p = create_project(self.service, "Synthetic workflow", "fixture-human", directory=self.project)["id"]

    def cli(self, *args, expected=0):
        from vsc.project import state
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch("sys.argv", ["vsc_state.py", *map(str, args)]), patch("vsc.bootstrap.service_from_environment", return_value=self.service), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                state.main()
            except SystemExit as error:
                code = error.code
        text = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(code, expected, text)
        return text

    def document(self, filename, payload):
        path = Path(self.temp.name) / filename
        path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=3).replace("\n", "\r\n").encode("utf-8") + b"\r\n")
        return path

    def brief(self, changed=False):
        payload = json.loads((ROOT / "templates/creative-brief.json").read_text())
        payload["audience"] = "synthetic audience" + (" revision" if changed else "")
        payload["desired_experience"] = "synthetic emotional progression"
        payload["decision_owner"] = "fixture-human"
        return self.document("brief-new.json" if changed else "brief.json", payload)

    def add(self, path, artifact_type="vsc.creative_brief", stage="brief", *extra):
        output = self.cli("artifact", "add", self.project, "--type", artifact_type, "--stage", stage, "--file", path, *extra)
        return output.split()[1]

    def decide(self, identifier):
        return self.cli("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "fixture-human", "--note", "synthetic approval")

    def test_standard_artifact_preserves_exact_bytes_and_human_actor(self):
        source = self.brief()
        identifier = self.add(source, "vsc.creative_brief", "brief", "--note", "synthetic registration note")
        row = self.service.get_artifact_version(self.p, identifier)
        self.assertEqual(row["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(row["document"].encode(), source.read_bytes())
        self.assertFalse(row["approved"])
        self.assertEqual(row["registration_note"], "synthetic registration note")
        self.decide(identifier)
        row = self.service.get_artifact_version(self.p, identifier)
        self.assertTrue(row["approved"])
        self.assertEqual(row["decisions"][-1]["actor"], "fixture-human")
        self.assertIn(identifier, self.cli("artifact", "list", self.project, "--type", "vsc.creative_brief"))
        self.assertFalse((self.project / "vsc.json").exists())

    def test_display_hierarchy_and_exact_json_script_projection(self):
        self.cli("object", "add", self.project, "--kind", "episode", "--id", "EP", "--parent", "W001")
        self.cli("object", "add", self.project, "--kind", "scene", "--id", "SC1", "--parent", "EP")
        self.cli("object", "add", self.project, "--kind", "scene", "--id", "SC2", "--parent", "EP")
        self.cli("object", "add", self.project, "--kind", "asset", "--id", "CHAR", "--asset-kind", "character")
        payload = json.loads((ROOT / "templates/screenplay.json").read_text())
        payload["project_id"] = self.p
        payload["body"] = "Synthetic screenplay fixture with two explicit scene units."
        path = self.document("screenplay.json", payload)
        identifier = self.add(path, "vsc.screenplay", "script", "--scope", "EP")
        row = self.service.get_artifact_version(self.p, identifier)
        self.assertEqual(len(row["script_lines"]), 2)
        self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(all(line["source_sha256"] == row["sha256"] for line in row["script_lines"]))
        repeated = self.add(path, "vsc.screenplay", "script", "--scope", "EP")
        second = self.service.get_artifact_version(self.p, repeated)
        self.assertNotEqual(repeated, identifier)
        self.assertEqual(second["sha256"], row["sha256"])
        self.assertFalse({line["id"] for line in second["script_lines"]} & {line["id"] for line in row["script_lines"]})
        self.cli("artifact", "decide", self.project, identifier, "--status", "approved", "--by", "fixture-human", "--note", "missing pinned adaptation", expected=1)
        self.assertIn("SC1 scene", self.cli("object", "list", self.project))
        self.cli("object", "add", self.project, "--kind", "episode", "--id", "EP2", expected=1)
        self.cli("object", "add", self.project, "--kind", "take", "--id", "TAKE", expected=1)

    def test_context_is_bounded_derived_output_and_rejects_drafts(self):
        identifier = self.add(self.brief())
        self.cli("context", "build", self.project, "--role", "director", "--task", "synthetic review", "--artifact", identifier, expected=1)
        self.decide(identifier)
        revision = self.service.get_project(self.p)["revision"]
        output = self.cli("context", "build", self.project, "--role", "director", "--task", "synthetic review", "--artifact", identifier)
        context_id = output.split()[1]
        packet = json.loads((self.project / "10-记忆/上下文" / (context_id + ".json")).read_text())
        self.assertFalse(packet["approved"])
        self.assertEqual(packet["authority"], "derived_task_packet")
        self.assertEqual(packet["inputs"][0]["id"], identifier)
        self.assertEqual(packet["approved_memories"], [])
        self.assertEqual(self.service.get_project(self.p)["revision"], revision)
        self.cli("context", "build", self.project, "--role", "director", "--task", "synthetic", "--artifact", identifier, "--budget-chars", "1", expected=1)

    def test_source_unknown_stays_unknown_and_known_rights_require_human(self):
        source = Path(self.temp.name) / "source.txt"
        raw = "synthetic source\r\n内容\r\n".encode()
        source.write_bytes(raw)
        self.cli("source", "add", self.project, "--kind", "original", "--file", source)
        rows = self.service.list_resources(self.p)["items"]
        self.assertEqual(rows[0]["sha256"], hashlib.sha256(raw).hexdigest())
        detail = self.service.get_media(self.p, rows[0]["id"])
        self.assertEqual(detail["rights"]["outcome"], "unknown")
        source_id = self.service.list_sources(self.p)["items"][0]["id"]
        source_version = self.service.get_source_version(self.p, source_id)
        self.assertEqual(source_version["content"].encode(), raw)
        self.assertEqual(source_version["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(source_version["untrusted_material"])
        output = self.cli("context", "build", self.project, "--role", "story-analyst", "--task", "understand registered source")
        packet = json.loads((self.project / "10-记忆/上下文" / (output.split()[1] + ".json")).read_text())
        self.assertEqual(packet["source_refs"][0]["id"], source_id)
        self.assertEqual(packet["source_refs"][0]["uri"], "source://" + self.p + "/" + source_id)
        self.assertNotIn("synthetic source", json.dumps(packet))
        output = self.cli("context", "build", self.project, "--role", "director", "--task", "review only approved production inputs")
        packet = json.loads((self.project / "10-记忆/上下文" / (output.split()[1] + ".json")).read_text())
        self.assertEqual(packet["source_refs"], [])
        if importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"):
            from fastapi.testclient import TestClient
            from vsc.interfaces.web.app import create_app
            with TestClient(create_app({"projects_root": Path(self.temp.name) / "empty", "allowed_hosts": ["testserver"]}, service=self.service)) as client:
                response = client.get("/api/v1/projects/" + self.p + "/sources/" + source_id)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["content"].encode(), raw)
                self.assertEqual(response.json()["sha256"], hashlib.sha256(raw).hexdigest())
        self.cli("source", "add", self.project, "--kind", "original", "--file", source, "--rights", "owned", expected=1)
        self.cli("source", "add", self.project, "--kind", "original", "--file", source, "--rights", "owned", "--by", "fixture-human")
        self.assertEqual(len(self.service.list_sources(self.p)["items"]), 2)

    def test_superseding_version_keeps_old_bytes_and_rejects_mismatch(self):
        old = self.add(self.brief())
        self.decide(old)
        new = self.add(self.brief(True), "vsc.creative_brief", "brief", "--supersedes", old)
        self.decide(new)
        self.assertEqual(self.service.get_artifact_version(self.p, new)["supersedes_id"], old)
        self.assertTrue(self.service.get_artifact_version(self.p, old)["approved"])
        self.cli("artifact", "add", self.project, "--type", "vsc.creative_brief", "--stage", "brief", "--file", self.brief(True), "--supersedes", old, expected=1)
        self.cli("gate", "check", self.project, "delivery", expected=1)
        self.assertIn("next_stage", self.cli("next", self.project))
