"""Actual SDK through worker/PG/storage, with synthetic offline HTTP and media."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture, png_bytes
from support.fixtures.resource_settings import configuration
from vsc.adapters.providers.credentials import KEY_ENV

HAS_DEPS = all(importlib.util.find_spec(name) for name in ("arkruntime", "httpx", "sqlalchemy", "psycopg", "alembic"))
TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires isolated test PostgreSQL and optional official SDK")
class OfficialSDKWorkerTest(unittest.TestCase):
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
        from vsc.production.resource_settings import ResourceSettings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PostgresResourceStore(engine=self.engine)
        self.service = ResourceService(self.store, LocalStorage(self.temp.name))
        self.settings = ResourceSettings(self.store)
        self.fixture = ResourceFixture(self.service)
        self.env = patch.dict(os.environ, {KEY_ENV: "offline-fixture-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def model(self, modality="image"):
        data = configuration(execution="official_sdk", modality=modality,
            model_key="doubao-seedream-test" if modality == "image" else "doubao-seedance-test",
            capabilities={"purposes": ["keyframe"] if modality == "image" else ["video_clip"], "first_frame": True},
            default_params={"size_map": {"1080x1920": "1440x2560"}} if modality == "image" else {"resolution": "720p", "ratio": "9:16"})
        return self.settings.save(data, "fixture-human")

    def worker(self, client, download=None):
        from vsc.adapters.providers.volc_ark.resource_factory import volc_ark_factory
        from vsc.production.resource_worker import ResourceWorker
        return ResourceWorker(self.service, lambda job, storage: volc_ark_factory(job, storage, sdk_http_client=client), download=download)

    def test_image_then_async_video_resume_retains_disabled_configuration_and_lineage(self):
        import base64
        import httpx
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path.endswith("/images/generations"):
                return httpx.Response(200, json={"created": 1, "data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]})
            if request.method == "POST":
                return httpx.Response(200, json={"id": "cgt-offline-worker"})
            return httpx.Response(200, json={"id": "cgt-offline-worker", "status": "succeeded",
                "content": {"video_url": "https://fixture.invalid/video.mp4"}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            image_model = self.model()
            image_job = self.fixture.job("image", "keyframe", image_model["id"])
            self.worker(client).run_once(self.fixture.p)
            saved = self.service.get_generation_job(self.fixture.p, image_job["id"])
            image_id = saved["outputs"][0]["media_id"]
            self.assertEqual(saved["raw_response"]["vsc_execution"]["configuration_id"], image_model["id"])
            self.fixture.select_media(image_id, "first_frame")
            video_model = self.model("video")
            video_job = self.fixture.job("video", "video_clip", video_model["id"], {"first_frame_media_id": image_id, "duration_ms": 1000})
            result = self.worker(client).run_once(self.fixture.p)
            self.assertEqual((result["status"], result["external_task_id"]), ("submitted", "cgt-offline-worker"))
            self.settings.enabled(video_model["id"], False, "fixture-human")
            path = Path(self.temp.name) / "fixture.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=16x32:r=24:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
            self.worker(client, lambda url, target: target.write_bytes(path.read_bytes())).run_once(self.fixture.p, poll=True)
            result = self.service.get_generation_job(self.fixture.p, video_job["id"])
            self.assertEqual("succeeded", result["status"])
            self.assertEqual(video_model["id"], result["raw_response"]["vsc_execution"]["configuration_id"])
            self.assertEqual("POST", result["raw_response"]["vsc_execution"]["submission"]["wire"]["method"])
            self.assertEqual("GET", result["raw_response"]["vsc_execution"]["wire"]["method"])
            output = result["outputs"][0]["media_id"]
            self.assertEqual(video_job["id"], self.service.get_media_usage(self.fixture.p, output)["job_outputs"][0]["job_id"])
            self.assertEqual(video_job["id"], self.service.get_media_usage(self.fixture.p, image_id)["job_inputs"][0]["job_id"])
            self.assertIsNone(self.worker(client).run_once(self.fixture.p))
        self.assertEqual(["POST", "POST", "GET"], [request.method for request in calls])

    def test_timeout_remains_unknown_and_cannot_be_resubmitted(self):
        import httpx
        from vsc.assets.resource_service import ResourceError
        calls = []
        def timeout(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic", request=request)
        model = self.model()
        job = self.fixture.job("image", "keyframe", model["id"])
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            worker = self.worker(client)
            with self.assertRaises(ResourceError):
                worker.run_once(self.fixture.p)
            self.assertEqual("submission_unknown", self.service.get_generation_job(self.fixture.p, job["id"])["status"])
            self.assertIsNone(worker.run_once(self.fixture.p))
        self.assertEqual(1, len(calls))
