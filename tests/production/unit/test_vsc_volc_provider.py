"""Adapter shape checks with injected transport; never touches Volc Ark."""
import base64
import unittest

from support.paths import ROOT  # noqa: F401 - add scripts to import path
from vsc.production.providers import ImageRequest, VideoRequest
from vsc.adapters.providers.volc_ark.provider import VolcAdapterError, VolcArkImageProvider, VolcArkVideoProvider


class FakeTransport:
    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    def __call__(self, path, payload=None):
        self.calls.append((path, payload))
        return self.responses.pop(0)


class VolcContract(unittest.TestCase):
    def test_image_maps_logical_request_and_parses_url_or_inline_bytes(self):
        transport = FakeTransport([{"data": [{"url": "https://example.invalid/temporary"}]}])
        adapter = VolcArkImageProvider("symbolic-image-model", lambda media_id: "data:image/png;base64," + media_id,
                                       lambda width, height: "2K" if (width, height) == (1080, 1920) else "", transport)
        request = ImageRequest("SH1", "shot_keyframe", "sha", "room", ("ref1",), {}, 1080, 1920)
        handle = adapter.submit(request)
        self.assertEqual(transport.calls[0][0], "/images/generations")
        self.assertEqual(transport.calls[0][1]["image"], ["data:image/png;base64,ref1"])
        self.assertEqual(adapter.poll(handle).status, "succeeded")
        self.assertEqual(adapter.parse_result(handle.raw)[0].temporary_uri, "https://example.invalid/temporary")
        inline = adapter.parse_result({"data": [{"b64_json": base64.b64encode(b"pixels").decode()}]})
        self.assertEqual(inline[0].inline_bytes, b"pixels")

    def test_video_submits_once_then_polls_by_fixed_task_id(self):
        transport = FakeTransport([{"id": "task-1"}, {"status": "running"},
                                   {"status": "succeeded", "content": {"video_url": "https://example.invalid/video"}}])
        adapter = VolcArkVideoProvider("symbolic-video-model", lambda media_id: "https://example.invalid/" + media_id,
                                       "720p", "9:16", False, transport)
        request = VideoRequest("SH1", "video_clip", "sha", "movement", (), {}, 5000, "frame1")
        handle = adapter.submit(request)
        self.assertEqual(handle.external_task_id, "task-1")
        self.assertEqual(transport.calls[0][1]["content"][1]["role"], "first_frame")
        self.assertNotIn("ratio", transport.calls[0][1])
        self.assertEqual(adapter.poll(handle).status, "running")
        result = adapter.poll(handle)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(adapter.parse_result(result.raw)[0].modality, "video")
        self.assertTrue(all(call[0].startswith("/contents/generations/tasks/task-1") for call in transport.calls[1:]))

    def test_hard_frame_and_reference_conflict_fails_before_transport(self):
        transport = FakeTransport([])
        adapter = VolcArkVideoProvider("symbolic-model", lambda media_id: media_id, "720p", "9:16", transport=transport)
        request = VideoRequest("SH1", "video_clip", "sha", "movement", ("other",), {}, 5000, "first")
        with self.assertRaises(VolcAdapterError):
            adapter.submit(request)
        self.assertEqual(transport.calls, [])

    def test_reference_audio_retains_modality_and_cannot_mix_with_hard_frames(self):
        from vsc.production.run_authorization import normalize_request, validate_capabilities
        from vsc.assets.resource_service import ResourceError
        transport = FakeTransport([{"id": "audio-reference-task"}])
        adapter = VolcArkVideoProvider("symbolic-model", lambda media_id: "https://example.invalid/" + media_id,
                                       "720p", "16:9", True, transport)
        request = VideoRequest("SH1", "reference_video", "sha", "movement", ("image",), {},
                               5000, reference_audio_media_ids=("speech",))
        adapter.submit(request)
        payload = transport.calls[0][1]
        self.assertEqual(payload["ratio"], "16:9")
        self.assertTrue(payload["generate_audio"])
        self.assertEqual(payload["content"][-1], {"type": "audio_url", "audio_url": {
            "url": "https://example.invalid/speech"}, "role": "reference_audio"})
        with self.assertRaises(VolcAdapterError):
            adapter.submit(VideoRequest("SH1", "video_clip", "sha", "movement", (), {},
                           5000, "first", reference_audio_media_ids=("speech",)))
        self.assertEqual(len(transport.calls), 1)
        logical = normalize_request({"prompt": "movement", "reference_media_ids": ["image"],
            "reference_audio_media_ids": ["speech"]}, "SH1", "reference_video", "video")
        context = {"media": [{"media_id": "image", "role": "composition"},
                             {"media_id": "speech", "role": "reference_audio"}]}
        model = {"capabilities": {"purposes": ["reference_video"], "reference_media": True,
                                  "reference_audio": True}}
        validate_capabilities(model, logical, context)
        for invalid in (dict(logical, reference_audio_media_ids=["image"]),
                        dict(logical, reference_audio_media_ids=["unselected"]),
                        dict(logical, reference_media_ids=["speech"])):
            with self.subTest(invalid=invalid), self.assertRaises(ResourceError):
                validate_capabilities(model, invalid, context)
        with self.assertRaises(ResourceError):
            validate_capabilities({"capabilities": dict(model["capabilities"], reference_audio=False)}, logical, context)

    def test_worker_rejects_audio_outside_frozen_inputs_before_provider_use(self):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.assets.resource_service import ResourceError
        worker = ResourceWorker.__new__(ResourceWorker)
        job = {"modality": "video", "shot_id": "SH1", "purpose": "reference_video", "context_sha256": "sha",
            "request_payload": {"prompt": "movement", "reference_audio_media_ids": ["speech"]},
            "input_media": [{"media_id": "speech"}]}
        self.assertEqual(worker._request(job).reference_audio_media_ids, ["speech"])
        job["input_media"] = []
        with self.assertRaises(ResourceError):
            worker._request(job)


if __name__ == "__main__":
    unittest.main()
