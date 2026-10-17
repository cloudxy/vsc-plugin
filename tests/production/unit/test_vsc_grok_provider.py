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
        adapter = GrokImageProvider("grok-imagine-image-2.0", lambda media_id: "data:image/png;base64," + media_id,
                                    lambda w, h: "9:16" if (w, h) == (1080, 1920) else "", "2k", transport)
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

    def test_image_reference_media_goes_to_edits_endpoint(self):
        transport = FakeTransport([{"data": [{"url": "https://example.invalid/edited"}]}])
        adapter = GrokImageProvider("grok-imagine-image-2.0", lambda media_id: "data:image/png;base64," + media_id,
                                    lambda w, h: "", "2k", transport)
        handle = adapter.submit(ImageRequest("SH1", "image_edit", "sha", "只改外套颜色", ("ref1",), {}, 1080, 1920))
        path, payload = transport.calls[0]
        self.assertEqual(path, "/images/edits")
        self.assertEqual(payload["image"], {"url": "data:image/png;base64,ref1", "type": "image_url"})
        self.assertEqual(handle.raw["data"][0]["url"], "https://example.invalid/edited")
        transport.responses = [{"data": [{"url": "https://example.invalid/merged"}]}]
        adapter.submit(ImageRequest("SH1", "image_edit", "sha", "人物来自参考1，商品来自参考2", ("a", "b"), {}, 1080, 1920))
        payload = transport.calls[1][1]
        self.assertEqual([row["url"] for row in payload["images"]],
                         ["data:image/png;base64,a", "data:image/png;base64,b"])
        with self.assertRaises(GrokAdapterError):
            adapter.submit(ImageRequest("SH1", "image_edit", "sha", "p", ("1", "2", "3", "4", "5", "6"), {}, 1080, 1920))
        self.assertEqual(len(transport.calls), 2)

    def test_video_submits_first_frame_then_polls_fixed_request_id(self):
        transport = FakeTransport([{"request_id": "req-1"}, {"status": "pending"},
                                   {"status": "done", "video": {"url": "https://example.invalid/video", "duration": 6}}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: "data:image/png;base64," + media_id, "720p", transport=transport)
        request = VideoRequest("SH1", "video_clip", "sha", "movement", (), {}, 6000, "frame1")
        handle = adapter.submit(request)
        self.assertEqual(handle.external_task_id, "req-1")
        path, payload = transport.calls[0]
        self.assertEqual(path, "/videos/generations")
        self.assertEqual(payload["image"]["url"], "data:image/png;base64,frame1")
        self.assertEqual((payload["duration"], payload["resolution"]), (6, "720p"))
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("reference_images", payload)
        self.assertEqual(adapter.poll(handle).status, "submitted")
        result = adapter.poll(handle)
        self.assertEqual(result.status, "succeeded")
        asset = adapter.parse_result(result.raw)[0]
        self.assertEqual((asset.modality, asset.metadata["duration"]), ("video", 6))
        self.assertTrue(all(call[0] == "/videos/req-1" for call in transport.calls[1:]))

    def test_video_reference_mode_pins_first_frame_and_ratio(self):
        transport = FakeTransport([{"request_id": "req-ref"}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: "https://example.invalid/" + media_id,
                                    "720p", "9:16", transport)
        adapter.submit(VideoRequest("SH1", "video_clip", "sha", "<IMAGE_0> 的人走向 <IMAGE_1> 的门", ("door", "hero", "prop"), {}, 6000, "hero"))
        payload = transport.calls[0][1]
        self.assertEqual(payload["image"], {"url": "https://example.invalid/hero"})
        self.assertEqual([row["url"] for row in payload["reference_images"]],
                         ["https://example.invalid/door", "https://example.invalid/hero", "https://example.invalid/prop"])
        self.assertEqual(payload["aspect_ratio"], "9:16")
        hd = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: "https://example.invalid/" + media_id,
                               "1080p", transport=FakeTransport([]))
        with self.assertRaises(GrokAdapterError):  # 参考模式分辨率上限 720p
            hd.submit(VideoRequest("SH1", "video_clip", "sha", "p", ("a",), {}, 6000, "hero"))

    def test_video_last_frame_and_text_only_modes(self):
        transport = FakeTransport([{"request_id": "req-last"}, {"request_id": "req-text"}, {"request_id": "req-pair"}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: "https://example.invalid/" + media_id, "1080p", transport=transport)
        adapter.submit(VideoRequest("SH1", "video_clip", "sha", "收在门口", (), {}, 6000, None, "exit_frame"))
        payload = transport.calls[0][1]
        self.assertNotIn("image", payload)
        self.assertEqual(payload["last_frame"], {"url": "https://example.invalid/exit_frame"})
        adapter.submit(VideoRequest("SH1", "video_clip", "sha", "空镜缓慢横移", (), {}, 5000))
        payload = transport.calls[1][1]
        for absent in ("image", "last_frame", "reference_images"):
            self.assertNotIn(absent, payload)
        adapter.submit(VideoRequest("SH1", "video_clip", "sha", "推近", (), {}, 6000, "entry", "exit"))
        payload = transport.calls[2][1]
        self.assertEqual((payload["image"]["url"], payload["last_frame"]["url"]),
                         ("https://example.invalid/entry", "https://example.invalid/exit"))

    def test_video_failure_states_and_missing_request_id(self):
        transport = FakeTransport([{"status": "failed", "error": {"code": "internal_error"}}])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: media_id, "480p", transport=transport)
        self.assertEqual(adapter.poll(JobHandle("xai_grok", "grok-imagine-video-1.5", "req-2", {})).status, "failed")
        transport.responses = [{"status": "expired"}]
        self.assertEqual(adapter.poll(JobHandle("xai_grok", "grok-imagine-video-1.5", "req-2", {})).error_code, "expired")
        transport.responses = [{"id": "not-a-request-id"}]
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000, "first"))

    def test_video_rejects_audio_references_and_bad_duration_before_transport(self):
        transport = FakeTransport([])
        adapter = GrokVideoProvider("grok-imagine-video-1.5", lambda media_id: media_id, "480p", transport=transport)
        with self.assertRaises(GrokAdapterError):  # reference_audios 只接平台预置 voice_id，不接音频素材
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 6000, reference_audio_media_ids=("speech",)))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 16000, "first"))
        with self.assertRaises(GrokAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", (), {}, 4500, "first"))
        with self.assertRaises(GrokAdapterError):  # 参考图最多 14 张
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "move", tuple("r%d" % i for i in range(15)), {}, 6000, "first"))
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
