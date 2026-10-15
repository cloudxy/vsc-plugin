"""Adapter shape checks with injected transport; never touches Volc Ark."""
import base64
import unittest

from support.paths import ROOT  # noqa: F401 - add scripts to import path
from vsc_provider import ImageRequest, VideoRequest
from vsc_volc_provider import VolcAdapterError, VolcArkImageProvider, VolcArkVideoProvider


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


if __name__ == "__main__":
    unittest.main()
