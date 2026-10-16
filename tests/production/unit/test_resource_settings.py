"""Resource settings never call a model or expose environment values."""
import json
import unittest
from unittest.mock import patch
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import ResourceSettings, public_configuration, validate_configuration
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
        future = configuration(supplier="xai", product="api", plan="usage", region="global", auth_ref="XAI_API_KEY",
            base_url="https://api.x.ai/v1", model_key="future", enabled=False)
        self.assertEqual("not_connected", public_configuration(validate_configuration(future))["connection_status"])

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
