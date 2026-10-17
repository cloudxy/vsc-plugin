"""Resource settings never call a model or expose environment values."""
import json
import unittest
from unittest.mock import patch
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import PRESETS, ResourceSettings, public_configuration, validate_configuration
from support.fixtures.resource_settings import configuration


class ResourceSettingsTest(unittest.TestCase):
    def test_no_database_is_read_only_and_not_fake_storage(self):
        settings = ResourceSettings()
        self.assertFalse(settings.list()["available"])
        with self.assertRaises(ResourceError):
            settings.save(configuration(), "human")

    def test_only_environment_reference_allowed_and_secret_values_not_returned(self):
        with patch.dict("os.environ", {"ARK_AGENT_PLAN_API_KEY": "DO-NOT-EXPOSE-TEST-SECRET"}):
            result = public_configuration(validate_configuration(configuration()))
            self.assertEqual("loaded_unverified", result["connection_status"])
            self.assertNotIn("DO-NOT-EXPOSE-TEST-SECRET", json.dumps(result))
        for payload in (configuration(api_key="literal"), configuration(auth_ref="sk-not-an-env"),
                        configuration(default_params={"nested": {"api_key": "literal"}}),
                        configuration(base_url="https://secret@example.com/api")):
            with self.assertRaises(ResourceError):
                validate_configuration(payload)

    def test_wrong_plan_model_and_pending_route_cannot_be_enabled(self):
        for payload in (configuration(plan="pay-as-you-go"), configuration(model_key="text-model"),
                        configuration(capabilities={"purposes": ["sfx"]}),
                        configuration(execution="official_cli"),
                        configuration(modality="audio", model_key="seed-tts-2.0", capabilities={"purposes": ["sfx"]})):
            with self.assertRaises(ResourceError):
                validate_configuration(payload)
        future = configuration(supplier="alibaba", product="dashscope", plan="api", region="cn-beijing",
            auth_ref="DASHSCOPE_API_KEY", base_url="https://dashscope.example.com", model_key="future", enabled=False)
        self.assertEqual("not_connected", public_configuration(validate_configuration(future))["connection_status"])

    def test_xai_grok_subscription_route_requires_official_shape_and_login_state(self):
        import tempfile
        from pathlib import Path
        from vsc.adapters.providers.xai_grok import credentials as grok_credentials
        grok_image = dict(supplier="xai", product="grok-imagine", plan="subscription", region="global",
            execution="api", base_url="https://api.x.ai/v1", auth_ref="", model_key="grok-imagine-image-2.0",
            default_params={"ratio_map": {"1080x1920": "9:16"}, "resolution": "2k"})
        for override in (dict(product="api", plan="usage", auth_ref="XAI_API_KEY", model_key="future"),
                         dict(auth_ref="XAI_API_KEY"),
                         dict(base_url="https://api.example.com/v1"),
                         dict(modality="video", model_key="grok-imagine-image-2.0"),
                         dict(default_params={"resolution": "2k"}),
                         dict(default_params={"ratio_map": {"1080x1920": "9:16"}, "resolution": "4k"})):
            with self.assertRaises(ResourceError):
                validate_configuration(configuration(**{**grok_image, **override}))
        grok_video = dict(supplier="xai", product="grok-imagine", plan="subscription", region="global",
            execution="api", base_url="https://api.x.ai/v1", auth_ref="", model_key="grok-imagine-video-1.5",
            modality="video", capabilities={"purposes": ["image_to_video"]},
            default_params={"resolution": "480p"})
        with self.assertRaises(ResourceError):
            validate_configuration(configuration(**dict(grok_video, default_params={"resolution": "4k"})))
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "auth.json"
            with patch.object(grok_credentials, "LOGIN_FILE", missing):
                row = public_configuration(validate_configuration(configuration(**grok_image)))
                self.assertTrue(row["adapter_available"])
                self.assertEqual("not_loaded", row["connection_status"])
            login = Path(temp) / "login.json"
            login.write_text('{"https://auth.x.ai::u": {"key": "grok-login-secret-value", "expires_at": "2999-01-01T00:00:00Z"}}', "utf-8")
            with patch.object(grok_credentials, "LOGIN_FILE", login):
                row = public_configuration(validate_configuration(configuration(**grok_image)))
                self.assertEqual("loaded_unverified", row["connection_status"])
                self.assertNotIn("grok-login-secret-value", json.dumps(row))
        self.assertTrue({"xai-grok-imagine-image", "xai-grok-imagine-video"} <= {preset["id"] for preset in PRESETS})

    def test_sdk_snapshot_is_server_owned_and_missing_sdk_only_allows_draft(self):
        from unittest.mock import Mock
        settings = ResourceSettings()
        settings.repository = Mock()
        settings.repository.save.side_effect = lambda payload, actor: payload
        data = configuration(execution="official_sdk", enabled=False, default_params={"sdk_runtime": {"sha256": "user-supplied"}})
        with patch("vsc.adapters.providers.volc_ark.official_sdk.runtime_snapshot", return_value={"sha256": "server-fixed"}):
            self.assertEqual({"sha256": "server-fixed"}, settings.save(data, "human")["default_params"]["sdk_runtime"])
        with patch("vsc.adapters.providers.volc_ark.official_sdk.runtime_snapshot", side_effect=ResourceError("missing", "sdk_unavailable")):
            self.assertNotIn("sdk_runtime", settings.save(data, "human")["default_params"])
            with self.assertRaises(ResourceError):
                settings.save(dict(data, enabled=True), "human")

    def test_enabled_sdk_configuration_rechecks_fixed_environment(self):
        data = configuration(execution="official_sdk")
        data["default_params"]["sdk_runtime"] = {"sha256": "old"}
        with patch("vsc.adapters.providers.volc_ark.official_sdk.verify_runtime", side_effect=ResourceError("changed", "sdk_runtime_changed")):
            with self.assertRaises(ResourceError) as caught:
                validate_configuration(data)
            self.assertEqual("sdk_runtime_changed", caught.exception.code)
        with patch("vsc.adapters.providers.volc_ark.official_sdk.verify_runtime", return_value={}):
            with self.assertRaises(ResourceError) as caught:
                validate_configuration(configuration(execution="official_sdk", default_params={}))
            self.assertEqual("invalid_model_defaults", caught.exception.code)

    def test_configured_provider_handles_preserve_account_identity(self):
        from vsc.adapters.providers.volc_ark.resource_factory import ConfiguredArkProvider
        from vsc.production.providers import JobHandle
        class Fake:
            def submit(self, request):
                return JobHandle("volc_ark", "model", "task")
            def poll(self, handle):
                self.handle = handle
                return "running"
        fake = Fake()
        adapter = ConfiguredArkProvider(fake, "account-snapshot")
        handle = adapter.submit(None)
        self.assertEqual("account-snapshot", handle.provider)
        self.assertEqual("running", adapter.poll(handle))
        self.assertEqual("volc_ark", fake.handle.provider)
        with self.assertRaises(ResourceError):
            adapter.poll(JobHandle("another-account", "model", "task"))
