"""Kling AI production adapter contract: stdlib HS256 JWT, pure Base64, zero-retry POST, account isolation & F-002 multi-round poll carry-forward."""
from __future__ import annotations

import base64
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from support.paths import ROOT  # noqa: F401 - ensure repo paths initialized
from vsc.adapters.providers.kling import credentials as kling_credentials
from vsc.adapters.providers.kling import spec as kling_spec
from vsc.adapters.providers.kling.provider import (
    ACCOUNT_FIELD,
    KlingAdapterError,
    KlingImageProvider,
    KlingVideoProvider,
)
from vsc.adapters.providers.worker_factory import worker_adapter_factory
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import ImageRequest, JobHandle, VideoRequest


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


class FakeKlingTransport:
    def __init__(self, responses):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses = list(responses)

    def __call__(self, method: str, path: str, payload=None):
        self.calls.append((method, path, payload))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class KlingCredentialsAndSpecTests(unittest.TestCase):
    def test_hs256_jwt_matches_independent_openssl_vector_and_never_echoes_secrets(self):
        # Independent fixed literal vector verified via openssl dgst -sha256 -hmac & shasum -a 256.
        expected_jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJpc3MiOiJha19maXhlZF92ZWN0b3JfMDEiLCJleHAiOjE3MDAwMDE4MDAsIm5iZiI6MTY5OTk5OTk5NX0."
            "Wj351Ksbyx15vhyeTr07CzC8_QjeRbJTtWg01T3us1M"
        )
        expected_fp = "9a3622fa96849c3aed9356e59295029a55bb6108c36bda00bb040453de6ccb4c"

        jwt_token = kling_credentials.encode_kling_jwt(
            "ak_fixed_vector_01",
            "sk_fixed_vector_01",
            now_sec=1700000000,
        )
        self.assertEqual(jwt_token, expected_jwt)
        parts = jwt_token.split(".")
        self.assertEqual(len(parts), 3)
        self.assertEqual(json.loads(_b64url_decode(parts[0])), {"alg": "HS256", "typ": "JWT"})
        self.assertEqual(
            json.loads(_b64url_decode(parts[1])),
            {"iss": "ak_fixed_vector_01", "exp": 1700001800, "nbf": 1699999995},
        )

        with patch.dict(
            "os.environ",
            {"KLING_ACCESS_KEY": "ak_fixed_vector_01", "KLING_SECRET_KEY": "sk_fixed_vector_01"},
            clear=True,
        ):
            token, fp = kling_credentials.resolve_auth("KLING_ACCESS_KEY", now_sec=1700000000)
            self.assertEqual(token, expected_jwt)
            self.assertEqual(fp, expected_fp)

        # Custom prefix `<PREFIX>_ACCESS_KEY` pairs with `<PREFIX>_SECRET_KEY`.
        self.assertEqual(kling_credentials.paired_secret_env("STUDIO_KLING_ACCESS_KEY"), "STUDIO_KLING_SECRET_KEY")
        self.assertIsNone(kling_credentials.paired_secret_env("KLING_API_KEY"))

        # Single-key Bearer mode.
        with patch.dict("os.environ", {"KLING_API_KEY": "kling-single-bearer-token"}, clear=True):
            single_token, single_fp = kling_credentials.resolve_auth("KLING_API_KEY")
            self.assertEqual(single_token, "kling-single-bearer-token")
            self.assertEqual(
                single_fp,
                hashlib.sha256(b"key:kling-single-bearer-token").hexdigest(),
            )

        # Missing paired KLING_SECRET_KEY reports exact missing var & ~/.zshenv without echoing AK.
        with patch.dict("os.environ", {"KLING_ACCESS_KEY": "SENSITIVE-AK-DO-NOT-ECHO"}, clear=True):
            self.assertEqual(kling_credentials.missing_env_vars("KLING_ACCESS_KEY"), ["KLING_SECRET_KEY"])
            with self.assertRaises(ValueError) as err:
                kling_credentials.resolve_auth("KLING_ACCESS_KEY")
            msg = str(err.exception)
            self.assertIn("KLING_SECRET_KEY", msg)
            self.assertIn("KLING_ACCESS_KEY", msg)
            self.assertIn("KLING_API_KEY", msg)
            self.assertIn("~/.zshenv", msg)
            self.assertIn("source ~/.zshenv", msg)
            self.assertNotIn("SENSITIVE-AK-DO-NOT-ECHO", msg)

    def test_spec_strips_data_uri_and_validates_image_and_video_routes(self):
        self.assertEqual(kling_spec.strip_data_uri_prefix("data:image/png;base64,QUJD"), "QUJD")
        self.assertEqual(kling_spec.strip_data_uri_prefix("QUJD"), "QUJD")
        self.assertEqual(
            kling_spec.strip_data_uri_prefix("https://p1.kwimgs.com/kling/ref.png"),
            "https://p1.kwimgs.com/kling/ref.png",
        )
        for invalid_media in ("", "http://p1.kwimgs.com/ref.png", "data:text/plain;base64,QUJD", "not-base64!!!"):
            with self.subTest(invalid_media=invalid_media), self.assertRaises(kling_spec.KlingSpecError):
                kling_spec.strip_data_uri_prefix(invalid_media)

        # Image compilation with kling-v1-5 subject reference.
        img_path, img_payload = kling_spec.compile_image(
            "kling-v1-5",
            "赛博女侠立绘",
            ["data:image/jpeg;base64,QUJD"],
            "3:4",
            resolution="2k",
            image_reference="subject",
            image_fidelity=0.5,
            negative_prompt="blurry",
        )
        self.assertEqual(img_path, "/v1/images/generations")
        self.assertEqual(img_payload["image"], "QUJD")
        self.assertEqual(img_payload["image_reference"], "subject")
        self.assertEqual(img_payload["image_fidelity"], 0.5)
        self.assertEqual(img_payload["negative_prompt"], "blurry")

        with self.assertRaises(kling_spec.KlingSpecError):
            kling_spec.compile_image("kling-v2-1", "p", ["QUJD", "REVG"], "3:4")
        with self.assertRaises(kling_spec.KlingSpecError):
            kling_spec.compile_image("kling-v2-1", "p", ["QUJD"], "3:4", image_reference="subject")

        # Video route 1: text2video (kling-v2-6 maps sound='on'/'off').
        v_path, v_route, v_payload = kling_spec.compile_video(
            "kling-v2-6",
            "雨夜霓虹街景推轨",
            5000,
            aspect_ratio="16:9",
            resolution="1080p",
            generate_audio=False,
        )
        self.assertEqual((v_path, v_route), ("/v1/videos/text2video", "videos/text2video"))
        self.assertEqual((v_payload["duration"], v_payload["mode"], v_payload["sound"]), ("5", "pro", "off"))

        # Video route 2: image2video with first + tail frame.
        i2v_path, i2v_route, i2v_payload = kling_spec.compile_video(
            "kling-v2-6",
            "角色拔剑转身",
            10000,
            first_frame="data:image/png;base64,QUJD",
            last_frame="data:image/png;base64,REVG",
            resolution="720p",
            generate_audio=True,
        )
        self.assertEqual((i2v_path, i2v_route), ("/v1/videos/image2video", "videos/image2video"))
        self.assertEqual(
            (i2v_payload["image"], i2v_payload["image_tail"], i2v_payload["duration"], i2v_payload["mode"], i2v_payload["sound"]),
            ("QUJD", "REVG", "10", "std", "on"),
        )

        # Video route 3: multi-image2video (up to 4 references).
        m_path, m_route, m_payload = kling_spec.compile_video(
            "kling-v1-6",
            "两位角色对视",
            5000,
            references=["data:image/png;base64,QUJD", "https://p1.kwimgs.com/r2.png"],
        )
        self.assertEqual((m_path, m_route), ("/v1/videos/multi-image2video", "videos/multi-image2video"))
        self.assertEqual(
            m_payload["image_list"],
            [{"image": "QUJD"}, {"image": "https://p1.kwimgs.com/r2.png"}],
        )
        self.assertNotIn("sound", m_payload)

        # Reject invalid durations (6000ms), >4 refs, tail-without-first, and first+refs conflict.
        for bad_kwargs in (
            dict(duration_ms=6000),
            dict(duration_ms=15000),
            dict(duration_ms=5000, references=["QUJD"] * 5),
            dict(duration_ms=5000, last_frame="QUJD"),
            dict(duration_ms=5000, first_frame="QUJD", references=["QUJD"]),
        ):
            with self.subTest(bad_kwargs=bad_kwargs), self.assertRaises(kling_spec.KlingSpecError):
                kling_spec.compile_video("kling-v1-6", "prompt", **bad_kwargs)


class KlingProviderLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            "os.environ",
            {"KLING_ACCESS_KEY": "ak-account-alpha-secret", "KLING_SECRET_KEY": "sk-account-alpha-secret"},
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_multi_round_worker_poll_preserves_kling_route_account_and_submission_f002(self):
        # Simulate ResourceWorker._execute overwriting job["raw_response"] = status.raw
        # across submitted -> processing -> succeed for BOTH image and video via worker_adapter_factory.
        raw_bytes = b"\x89PNG\r\n\x1a\n"
        blob_sha = hashlib.sha256(raw_bytes).hexdigest()
        storage = MagicMock()
        storage.read.return_value = raw_bytes

        # 1. Multi-round Video (image2video) via worker_adapter_factory + ConfiguredKlingProvider.
        video_transport = FakeKlingTransport(
            [
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "vid_task_01", "task_status": "submitted"}},
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "vid_task_01", "task_status": "submitted"}},
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "vid_task_01", "task_status": "processing"}},
                {
                    "code": 0,
                    "message": "SUCCEED",
                    "data": {
                        "task_id": "vid_task_01",
                        "task_status": "succeed",
                        "task_result": {"videos": [{"id": "v1", "url": "https://p2.yximgs.com/kling/out.mp4", "duration": "5.0"}]},
                    },
                },
            ]
        )
        video_job = {
            "id": "job-vid-1",
            "provider_id": "prov-kling-prod",
            "modality": "video",
            "provider": {
                "base_url": "https://api-beijing.klingai.com",
                "auth_ref": "KLING_ACCESS_KEY",
                "configuration": {"supplier": "kling", "product": "kling", "plan": "api", "execution": "api"},
            },
            "model": {
                "model_key": "kling-v2-6",
                "default_params": {"resolution": "720p", "ratio": "16:9", "generate_audio": True},
                "capabilities": {"purposes": ["image_to_video"]},
            },
            "input_media": [
                {
                    "media_id": "m-first",
                    "blob_sha256": blob_sha,
                    "mime_type": "image/png",
                    "locations": [{"storage": "local", "object_key": "blobs/first.png", "available": True}],
                }
            ],
            "request_payload": {"prompt": "镜头推进", "params": {}},
        }
        vid_adapter = worker_adapter_factory(video_job, storage)
        vid_adapter.adapter.transport = video_transport

        req_vid = VideoRequest("SH-1", "image_to_video", "ctx", "镜头推进", (), {}, 5000, "m-first")
        handle_0 = vid_adapter.submit(req_vid)
        self.assertEqual(handle_0.provider, "prov-kling-prod")
        self.assertEqual(handle_0.external_task_id, "vid_task_01")
        self.assertEqual(video_transport.calls[0][1], "/v1/videos/image2video")
        self.assertEqual(video_transport.calls[0][2]["image"], base64.b64encode(raw_bytes).decode("ascii"))

        # Simulate DB raw_response column overwritten by ResourceWorker after every poll round!
        db_raw_response = dict(handle_0.raw)
        for expected_status in ("submitted", "running", "succeeded"):
            rebuilt_handle = JobHandle(
                video_job["provider_id"],
                video_job["model"]["model_key"],
                handle_0.external_task_id,
                db_raw_response,
            )
            polled = vid_adapter.poll(rebuilt_handle)
            self.assertEqual(polled.status, expected_status)
            db_raw_response = dict(polled.raw)
            self.assertEqual(db_raw_response.get("kling_route"), "videos/image2video")
            self.assertIn(ACCOUNT_FIELD, db_raw_response)
            self.assertIsInstance(db_raw_response.get("submission"), dict)

        vid_assets = vid_adapter.parse_result(db_raw_response)
        self.assertEqual(len(vid_assets), 1)
        self.assertEqual(vid_assets[0].modality, "video")
        self.assertEqual(vid_assets[0].temporary_uri, "https://p2.yximgs.com/kling/out.mp4")
        self.assertEqual(
            [c[1] for c in video_transport.calls[1:]],
            ["/v1/videos/image2video/vid_task_01"] * 3,
        )

        # 2. Multi-round Image (`submitted -> processing -> succeed`) carry-forward.
        image_transport = FakeKlingTransport(
            [
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "img_task_01", "task_status": "submitted"}},
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "img_task_01", "task_status": "submitted"}},
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "img_task_01", "task_status": "processing"}},
                {
                    "code": 0,
                    "message": "SUCCEED",
                    "data": {
                        "task_id": "img_task_01",
                        "task_status": "succeed",
                        "task_result": {"images": [{"index": 0, "url": "https://p1.kwimgs.com/kling/out.png"}]},
                    },
                },
            ]
        )
        img_adapter = KlingImageProvider(
            "kling-v2-1",
            lambda mid: "data:image/png;base64,QUJD",
            lambda w, h: "9:16" if (w, h) == (1080, 1920) else None,
            transport=image_transport,
        )
        img_handle = img_adapter.submit(ImageRequest("SH-2", "first_frame", "ctx", "古风街角", ("ref1",), {}, 1080, 1920))
        img_db_raw = dict(img_handle.raw)
        for expected_status in ("submitted", "running", "succeeded"):
            polled_img = img_adapter.poll(JobHandle("kling", "kling-v2-1", "img_task_01", img_db_raw))
            self.assertEqual(polled_img.status, expected_status)
            img_db_raw = dict(polled_img.raw)
            self.assertEqual(img_db_raw.get("kling_route"), "images/generations")
            self.assertIn(ACCOUNT_FIELD, img_db_raw)
            self.assertIsInstance(img_db_raw.get("submission"), dict)

        img_assets = img_adapter.parse_result(img_db_raw)
        self.assertEqual(img_assets[0].temporary_uri, "https://p1.kwimgs.com/kling/out.png")

    def test_submit_makes_strictly_one_post_on_timeout_and_redacts_all_secrets(self):
        import httpx

        # 1. Timeout during POST: strictly 1 POST call, zero retry, no secret leakage.
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.ReadTimeout(
            "Upstream timed out Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhayJ9.sig "
            "ak-account-alpha-secret sk-account-alpha-secret"
        )
        adapter = KlingImageProvider(
            "kling-v2-1",
            lambda mid: mid,
            lambda w, h: "9:16",
            client=mock_http,
        )
        req = ImageRequest("SH-1", "identity_ref", "ctx", "主角正面", (), {}, 1080, 1920)
        with self.assertRaises(KlingAdapterError) as timeout_err:
            adapter.submit(req)
        self.assertEqual(mock_http.post.call_count, 1)
        for leaked in ("ak-account-alpha-secret", "sk-account-alpha-secret", "eyJhbGci"):
            self.assertNotIn(leaked, str(timeout_err.exception))

        # 2. HTTP 401 & 500 error responses scrub AK, SK, and JWT substrings.
        for status_code in (401, 500):
            err_client = MagicMock()
            err_client.post.return_value = httpx.Response(
                status_code,
                text=(
                    '{"code":1002,"message":"bad key ak-account-alpha-secret '
                    'sk-account-alpha-secret eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhayJ9.sig"}'
                ),
            )
            err_adapter = KlingImageProvider("kling-v2-1", lambda mid: mid, lambda w, h: "9:16", client=err_client)
            with self.assertRaises(KlingAdapterError) as http_err:
                err_adapter.submit(req)
            self.assertEqual(err_client.post.call_count, 1)
            for leaked in ("ak-account-alpha-secret", "sk-account-alpha-secret", "eyJhbGci"):
                self.assertNotIn(leaked, str(http_err.exception))

    def test_cross_account_switch_and_missing_route_rejected_in_poll_and_parse(self):
        transport = FakeKlingTransport(
            [
                {"code": 0, "message": "SUCCEED", "data": {"task_id": "t_isolation", "task_status": "submitted"}},
                {
                    "code": 0,
                    "message": "SUCCEED",
                    "data": {
                        "task_id": "t_isolation",
                        "task_status": "succeed",
                        "task_result": {"images": [{"index": 0, "url": "https://p1.kwimgs.com/a.png"}]},
                    },
                },
            ]
        )
        adapter = KlingImageProvider("kling-v2-1", lambda m: m, lambda w, h: "9:16", transport=transport)
        handle = adapter.submit(ImageRequest("S", "identity_ref", "ctx", "hero", (), {}, 1080, 1920))

        # Missing kling_route in handle.raw is rejected before making any GET call.
        bad_route_handle = JobHandle("kling", "kling-v2-1", "t_isolation", {ACCOUNT_FIELD: handle.raw[ACCOUNT_FIELD]})
        with self.assertRaises(KlingAdapterError):
            adapter.poll(bad_route_handle)
        self.assertEqual(len(transport.calls), 1)

        # Switching KLING_ACCESS_KEY to another account blocks poll()!
        with patch.dict(
            "os.environ",
            {"KLING_ACCESS_KEY": "ak-account-beta-other", "KLING_SECRET_KEY": "sk-account-beta-other"},
            clear=False,
        ):
            with self.assertRaises(KlingAdapterError):
                adapter.poll(handle)
        self.assertEqual(len(transport.calls), 1)

        # Original account succeeds poll, then switching account blocks parse_result()!
        done = adapter.poll(handle)
        self.assertEqual(done.status, "succeeded")
        with patch.dict(
            "os.environ",
            {"KLING_ACCESS_KEY": "ak-account-beta-other", "KLING_SECRET_KEY": "sk-account-beta-other"},
            clear=False,
        ):
            with self.assertRaises(KlingAdapterError):
                adapter.parse_result(done.raw)

    def test_preflight_rejects_unknown_params_and_unsupported_video_fields_without_network(self):
        transport = FakeKlingTransport([])
        img_adapter = KlingImageProvider("kling-v2-1", lambda m: m, lambda w, h: "9:16", transport=transport)
        vid_adapter = KlingVideoProvider("kling-v2-6", lambda m: "QUJD", "720p", "16:9", transport=transport)

        for adapter, bad_req in (
            (img_adapter, ImageRequest("S", "identity_ref", "ctx", "p", params={"unknown_flag": True})),
            (img_adapter, ImageRequest("S", "image_edit", "ctx", "p", operation="inpaint", source_media_id="src")),
            (vid_adapter, VideoRequest("S", "image_to_video", "ctx", "p", params={"camera_shake": 99})),
            (vid_adapter, VideoRequest("S", "image_to_video", "ctx", "p", keyframes=(("k1", 2.0),))),
            (vid_adapter, VideoRequest("S", "image_to_video", "ctx", "p", reference_audio_media_ids=("aud1",))),
            (vid_adapter, VideoRequest("S", "image_to_video", "ctx", "p", operation="extend", source_media_id="v1")),
        ):
            with self.subTest(req=bad_req), self.assertRaises(KlingAdapterError):
                adapter.preflight(bad_req)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
