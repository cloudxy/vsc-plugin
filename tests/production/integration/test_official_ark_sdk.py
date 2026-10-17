"""Actual optional official SDK + HTTP MockTransport; never a paid request."""
import importlib.util
import json
import unittest
from unittest.mock import patch

from vsc.assets.resource_service import ResourceError
from vsc.adapters.providers.credentials import KEY_ENV, PLAN_BASE
from vsc.adapters.providers.volc_ark.official_sdk import OfficialArkTransport, runtime_snapshot, verify_runtime

HAS_SDK = bool(importlib.util.find_spec("arkruntime")) and bool(importlib.util.find_spec("httpx"))


@unittest.skipUnless(HAS_SDK, "requires the optional official arkruntime SDK")
class OfficialArkSDKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = runtime_snapshot()

    def call(self, body, handler, path="/images/generations"):
        import httpx
        requests = []
        def record(request):
            requests.append(request)
            return handler(request)
        with httpx.Client(transport=httpx.MockTransport(record)) as client, patch.dict("os.environ", {KEY_ENV: "offline-fixture-key"}):
            adapter = OfficialArkTransport(self.snapshot, {"service_provider": "volcengine", "plan": "agent-plan"}, http_client=client)
            return adapter(path, body), requests

    def test_image_wire_and_identity_are_exact(self):
        import httpx
        payload = {"model": "doubao-seedream-5-0-pro-test", "prompt": "固定原文，不改写", "size": "1440x2560",
            "response_format": "url", "watermark": False, "sequential_image_generation": "disabled"}
        raw, requests = self.call(payload, lambda request: httpx.Response(200, json={"model": payload["model"], "created": 1,
            "data": [{"url": "https://example.invalid/image.png"}], "usage": {"generated_images": 1}}))
        self.assertEqual(1, len(requests))
        self.assertEqual(payload, {k: v for k, v in json.loads(requests[0].content).items() if v is not None})
        self.assertEqual(PLAN_BASE + "/images/generations", str(requests[0].url))
        evidence = raw["vsc_execution"]
        self.assertEqual("arkruntime", evidence["tool"])
        self.assertEqual("0.13.0", evidence["tool_version"])
        self.assertEqual(0, evidence["max_retries"])
        self.assertEqual(self.snapshot["sha256"], evidence["runtime_sha256"])
        self.assertNotIn("offline-fixture-key", json.dumps(raw))

    def test_real_sdk_never_retries_error_or_timeout_and_never_follows_redirect(self):
        import httpx
        for status in (401, 403, 429, 500, 307):
            calls = []
            def handle(request):
                calls.append(request)
                return httpx.Response(status, headers={"Location": "https://untrusted.invalid/"}, json={"error": {"message": "offline"}})
            with self.assertRaises(ResourceError):
                self.call({"model": "doubao-seedream-5-test", "prompt": "fixed"}, handle)
            self.assertEqual(1, len(calls), status)
        calls = []
        def timeout(request):
            calls.append(request)
            raise httpx.ReadTimeout("offline timeout", request=request)
        with self.assertRaises(ResourceError):
            self.call({"model": "doubao-seedream-5-test", "prompt": "fixed"}, timeout)
        self.assertEqual(1, len(calls))

    def test_video_create_then_get_recovers_task_without_second_post(self):
        import httpx
        requests = []
        def handle(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"id": "cgt-offline"})
            return httpx.Response(200, json={"id": "cgt-offline", "model": "doubao-seedance-2-5-test", "status": "succeeded",
                "content": {"video_url": "https://example.invalid/video.mp4"}, "usage": {"total_tokens": 321}})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client, patch.dict("os.environ", {KEY_ENV: "offline-fixture-key"}):
            transport = OfficialArkTransport(self.snapshot, {}, http_client=client)
            created = transport("/contents/generations/tasks", {"model": "doubao-seedance-2-5-test",
                "content": [{"type": "text", "text": "fixed"}], "duration": 5, "resolution": "720p"})
            self.assertEqual("cgt-offline", created["id"])
            result = transport("/contents/generations/tasks/" + created["id"])
        self.assertEqual(["POST", "GET"], [request.method for request in requests])
        self.assertEqual("succeeded", result["status"])
        self.assertEqual(321, result["vsc_execution"]["usage"]["total_tokens"])

    def test_runtime_mismatch_and_text_routes_fail_before_network(self):
        with self.assertRaises(ResourceError):
            verify_runtime(dict(self.snapshot, sha256="0" * 64))
        transport = OfficialArkTransport(self.snapshot, {})
        with self.assertRaises(ResourceError):
            transport("/chat/completions", {"model": "text", "messages": []})
