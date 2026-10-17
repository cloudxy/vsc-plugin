"""Grok adapter shape checks with injected transport; never touches xAI."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.paths import ROOT  # noqa: F401 - add scripts to import path
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import ImageRequest, JobHandle, VideoRequest
from vsc.adapters.providers.xai_grok.provider import GrokAdapterError, GrokImageProvider, GrokVideoProvider
import vsc.adapters.providers.xai_grok.credentials as grok_credentials


class FakeTransport:
    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    def __call__(self, path, payload=None):
        self.calls.append((path, payload))
        return self.responses.pop(0)


class GrokContract(unittest.TestCase):
    def test_image_maps_ratio_and_parses_url_or_inline_bytes(self):
        transport = FakeTransport([{"data": [{"url": "https://example.invalid/temporary"}]}])
        adapter = GrokImageProvider("grok-imagine-image-2.0", lambda w, h: "9:16" if (w, h) == (1080, 1920) else "", "2k", transport)
        request = ImageRequest("SH1", "shot_keyframe", "sha", "room", (), {}, 1080, 1920)
        handle = adapter.submit(request)
        path, payload = transport.calls[0]
        self.assertEqual(path, "/images/generations")
        self.assertEqual((payload["aspect_ratio"], payload["resolution"], payload["n"], payload["model"]),
                         ("9:16", "2k", 1, "grok-imagine-image-2.0"))
        self.assertEqual(adapter.poll(handle).status, "succeeded")
        self.assertEqual(adapter.parse_result(handle.raw)[0].temporary_uri, "https://example.invalid/temporary")
        inline = adapter.parse_result({"data": [{"b64_json": base64.b64encode(b"pixels").decode()}]})
        self.assertEqual(inline[0].inline_bytes, b"pixels")

    def test_image_rejects_reference_media_and_missing_ratio_before_transport(self):
        transport = FakeTransport([])
        adapter = GrokImageProvider("grok-imagine-image-2.0", lambda w, h: "", transport=transport)
        with self.assertRaises(GrokAdapterError):
            adapter.submit(ImageRequest("SH1", "identity_ref", "sha", "room", ("ref1",), {}, 1080, 1920))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(ImageRequest("SH1", "identity_ref", "sha", "room", (), {}, 1080, 1920))
        self.assertEqual(transport.calls, [])

    def test_video_submits_first_frame_then_polls_fixed_request_id(self):
        transport = FakeTransport([{"request_id": "req-1"}, {"status": "pending"},
                                   {"status": "done", "video": {"url": "https://example.invalid/video", "duration": 6}}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: "data:image/png;base64," + media_id, "720p", transport)
        request = VideoRequest("SH1", "video_clip", "sha", "movement", (), {}, 6000, "frame1")
        handle = adapter.submit(request)
        self.assertEqual(handle.external_task_id, "req-1")
        path, payload = transport.calls[0]
        self.assertEqual(path, "/videos/generations")
        self.assertEqual(payload["image"]["url"], "data:image/png;base64,frame1")
        self.assertEqual((payload["duration"], payload["resolution"]), (6, "720p"))
        self.assertNotIn("aspect_ratio", payload)
        self.assertEqual(adapter.poll(handle).status, "submitted")
        result = adapter.poll(handle)
        self.assertEqual(result.status, "succeeded")
        asset = adapter.parse_result(result.raw)[0]
        self.assertEqual((asset.modality, asset.metadata["duration"]), ("video", 6))
        self.assertTrue(all(call[0] == "/videos/req-1" for call in transport.calls[1:]))

    def test_video_failure_states_and_missing_request_id(self):
        transport = FakeTransport([{"status": "failed", "error": {"code": "internal_error"}}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: media_id, "480p", transport)
        self.assertEqual(adapter.poll(JobHandle("xai_grok", "grok-imagine-video-1.5", "req-2", {})).status, "failed")
        transport.responses = [{"status": "expired"}]
        self.assertEqual(adapter.poll(JobHandle("xai_grok", "grok-imagine-video-1.5", "req-2", {})).error_code, "expired")
        transport.responses = [{"id": "not-a-request-id"}]
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000, "first"))

    def test_video_rejects_last_frame_references_and_bad_duration_before_transport(self):
        transport = FakeTransport([])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: media_id, "480p", transport)
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000, "first", "last"))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", ("ref",), {}, 6000, "first"))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000, reference_audio_media_ids=("speech",)))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 16000, "first"))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 4500, "first"))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000))
        self.assertEqual(transport.calls, [])


class GrokFactoryTest(unittest.TestCase):
    def job(self, **kw):
        value = {"provider_id": "xai_grok",
                 "provider": {"configuration": {"supplier": "xai", "product": "grok-imagine", "plan": "subscription", "execution": "api"},
                              "base_url": "https://api.x.ai/v1", "auth_ref": None},
                 "model": {"model_key": "grok-imagine-video-1.5", "default_params": {"resolution": "480p"}},
                 "request_payload": {"prompt": "move"}, "input_media": [], "modality": "video"}
        value.update(kw)
        return value

    def test_dispatch_and_account_identity(self):
        from vsc.adapters.providers.xai_grok.resource_factory import ConfiguredGrokProvider, xai_grok_factory
        from vsc.adapters.providers.worker_factory import worker_adapter_factory

        class Fake:
            def submit(self, request):
                return JobHandle("xai_grok", "model", "task")

            def poll(self, handle):
                self.seen = handle
                return "running"

        fake = Fake()
        adapter = ConfiguredGrokProvider(fake, "account-snapshot")
        handle = adapter.submit(None)
        self.assertEqual("account-snapshot", handle.provider)
        self.assertEqual("running", adapter.poll(handle))
        self.assertEqual("xai_grok", fake.seen.provider)
        with self.assertRaises(ResourceError):
            adapter.poll(JobHandle("another-account", "model", "task"))
        with tempfile.TemporaryDirectory() as temp:
            login = Path(temp) / "auth.json"
            login.write_text(json.dumps({"https://auth.x.ai::u": {"key": "grok-login-secret-value", "expires_at": "2999-01-01T00:00:00Z"}}), "utf-8")
            with mock.patch.object(grok_credentials, "LOGIN_FILE", login):
                self.assertIsInstance(xai_grok_factory(self.job(), storage=None), ConfiguredGrokProvider)
                # dispatch reaches the grok factory
                self.assertIsInstance(worker_adapter_factory(self.job(), None), ConfiguredGrokProvider)

    def test_foreign_provider_and_missing_login_are_refused(self):
        from vsc.adapters.providers.worker_factory import worker_adapter_factory
        with self.assertRaises(ResourceError) as caught:
            worker_adapter_factory(self.job(provider_id="other", provider={"configuration": {}, "base_url": "", "auth_ref": None}), None)
        self.assertEqual("adapter_unavailable", caught.exception.code)
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(grok_credentials, "LOGIN_FILE", Path(temp) / "auth.json"):
                with self.assertRaises(ResourceError) as caught:
                    worker_adapter_factory(self.job(), None)
                self.assertEqual("credential_missing", caught.exception.code)
                with self.assertRaises(ResourceError) as caught:
                    worker_adapter_factory(self.job(provider={"configuration": {"supplier": "xai", "product": "grok-imagine",
                        "plan": "subscription", "execution": "api"}, "base_url": "https://api.example.com", "auth_ref": None}), None)
                self.assertEqual("invalid_provider_config", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
