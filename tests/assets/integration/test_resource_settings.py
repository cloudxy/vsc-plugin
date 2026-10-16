"""Real PG snapshot immutability, defaults and concurrent configuration edits."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from support.fixtures.postgres import isolated_postgres
from support.fixtures.resource_settings import configuration


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL"), "requires explicit isolated PostgreSQL test URL")
class ResourceSettingsPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        cls.db = isolated_postgres(os.environ["VSC_TEST_DATABASE_URL"])
        cls.engine = cls.db.__enter__()
        cls.store = PostgresResourceStore(engine=cls.engine)
        from vsc.production.resource_settings import ResourceSettings
        cls.settings = ResourceSettings(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.db.__exit__(None, None, None)

    def test_schema_matches_migration(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from vsc.adapters.persistence.postgres.schema import metadata
        with self.engine.connect() as conn:
            self.assertEqual([], compare_metadata(MigrationContext.configure(conn), metadata))
        self.store.check_schema()

    def test_snapshot_preserves_connection_and_default_requires_explicit_rebind(self):
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        old = self.settings.save(configuration(), "human")
        self.settings.bind_default("identity_ref", old["id"], "human")
        new = self.settings.save(configuration(id=old["id"], name="新连接"), "human")
        self.assertNotEqual(old["provider_id"], new["provider_id"])
        self.assertNotIn("identity_ref", self.settings.list()["defaults"])
        with self.engine.begin() as conn:
            with self.assertRaises(IntegrityError):
                conn.execute(update(S.providers).where(S.providers.c.id == old["provider_id"]).values(auth_ref="ANOTHER_KEY"))
        self.assertEqual(old["auth_ref"], self.settings.repository.get(old["id"])["auth_ref"])
        self.settings.bind_default("identity_ref", new["id"], "human")
        self.assertEqual(new["id"], self.settings.list()["defaults"]["identity_ref"])
        self.settings.enabled(new["id"], False, "human")
        self.assertNotIn("identity_ref", self.settings.list()["defaults"])
        self.settings.enabled(new["id"], True, "human")
        self.settings.bind_default("identity_ref", new["id"], "human")
        self.settings.bind_default("identity_ref", None, "human")
        self.assertNotIn("identity_ref", self.settings.list()["defaults"])

    def test_concurrent_edits_have_one_successor(self):
        from vsc.assets.resource_service import Conflict
        old = self.settings.save(configuration(), "human")
        barrier = Barrier(2)
        def save(number):
            barrier.wait()
            try:
                self.settings.save(configuration(id=old["id"], name="version" + str(number)), "human")
                return "saved"
            except Conflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(["saved", "conflict"], list(pool.map(save, [1, 2])))

    def test_existing_registry_visible_and_check_has_no_network(self):
        from unittest.mock import Mock
        self.store.register_provider({"id": "volc_ark", "base_url": configuration()["base_url"], "auth_ref": "ARK_AGENT_PLAN_API_KEY"}, "human")
        model = self.store.register_model({"provider_id": "volc_ark", "model_key": "doubao-seedream-existing", "model_version": "1",
            "modality": "image", "capabilities": {"purposes": ["identity_ref"]}}, "human")
        self.assertIn(model["id"], [row["id"] for row in self.settings.list()["configurations"]])
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            result = self.settings.check(model["id"])
            self.assertFalse(result["generation_verified"])
            self.assertEqual("registered_models", self.settings.models(model["id"])["scope"])

    def test_new_job_uses_default_and_old_job_retains_original_snapshot(self):
        import uuid
        from vsc.assets.resource_service import ResourceService
        service = ResourceService(self.store)
        project = service.create_project({"name": "默认模型测试", "profile_snapshot": {"profile_id": "vsc.synthetic", "version": "1", "stages": []}}, actor="human")
        pid, revision = project["id"], 0
        def write(method, payload):
            nonlocal revision
            result = getattr(service, method)(pid, payload, expected_revision=revision, idempotency_key=uuid.uuid4().hex, actor="human")
            revision = result["revision"]
            return result
        asset = write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "CHAR"})["id"]
        specs = {"asset_specs": [{"id": str(uuid.uuid4()), "asset_id": asset, "variant_key": "master"}]}
        bible = write("create_artifact", dict(artifact_key="bible", artifact_type="asset-bible", object_ids=[asset], document=specs, **specs))["id"]
        write("decide_artifact", {"artifact_id": bible, "reason": "测试批准"})
        context = service.compile_asset_context(pid, asset, "identity_ref")
        request = {"shot_id": None, "asset_id": asset, "purpose": "identity_ref", "modality": "image", "prompt": "蓝衣人物参考"}
        run = write("create_artifact", {"artifact_key": "run", "artifact_type": "production-run", "object_ids": [asset], "dependency_ids": [bible],
            "document": {"approved_inputs": [{"id": a["id"], "sha256": a["sha256"]} for a in context["artifacts"]], "jobs": [{"request": request}]}})["id"]
        write("decide_artifact", {"artifact_id": run, "reason": "测试批准"})
        model = self.settings.save(configuration(), "human")
        self.settings.bind_default("identity_ref", model["id"], "human")
        job = write("create_generation_job", {"run_version_id": run, "asset_id": asset, "purpose": "identity_ref", "modality": "image",
            "context_sha256": context["sha256"], "request_payload": request})
        saved = service.get_generation_job(pid, job["id"])
        self.assertEqual(model["id"], saved["model_id"])
        self.assertEqual("agent-plan", saved["provider"]["configuration"]["plan"])
        self.assertTrue(self.settings.repository.active_jobs())
        replacement = self.settings.save(configuration(id=model["id"], name="新版"), "human")
        self.settings.bind_default("identity_ref", replacement["id"], "human")
        recovered = service.get_generation_job(pid, job["id"])
        self.assertEqual(model["provider_id"], recovered["provider_id"])
        self.assertEqual(model["id"], recovered["model_id"])
        self.assertFalse(recovered["model"]["enabled"])
