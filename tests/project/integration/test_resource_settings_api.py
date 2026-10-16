"""All resource setting mutations share the panel's origin/session/CSRF check."""
import json
import importlib.util
import tempfile
from unittest.mock import Mock, patch
import unittest
from support.fixtures.resource_settings import configuration

HAS_WEB = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
if HAS_WEB:
    from fastapi.testclient import TestClient
    from vsc.interfaces.web.app import create_app

@unittest.skipUnless(HAS_WEB, "requires optional web/test dependencies")
class ResourceSettingsAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"projects_root": self.temp.name, "access_token": "local-test-session-token",
            "human_identity": "real-human", "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"]})
        self.client = TestClient(self.app)
        self.model = "e277a55b-d582-40e2-bf17-e3229d867834"

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/v1/session", json={"token": "local-test-session-token"}, headers={"origin": "http://testserver"})
        return {"origin": "http://testserver", "x-csrf-token": response.json()["csrf_token"]}

    def test_every_write_action_needs_trusted_origin_and_human_session(self):
        prefix = "/api/v1/resource-settings"
        actions = [("/configurations", {"payload": configuration()}),
            ("/configurations/" + self.model + "/enabled", {"enabled": True}),
            ("/defaults", {"purpose": "identity_ref", "configuration_id": self.model}),
            ("/configurations/" + self.model + "/check", {}),
            ("/configurations/" + self.model + "/models", {}),
            ("/updates/check", {}), ("/updates/tool", {"expected_revision": "a" * 40})]
        for path, body in actions:
            self.assertEqual(403, self.client.post(prefix + path, json=body).status_code, path)
        headers = self.login()
        for path, body in actions:
            self.assertEqual(403, self.client.post(prefix + path, json=body,
                headers=dict(headers, origin="https://untrusted.invalid")).status_code, path)
            self.assertEqual(403, self.client.post(prefix + path, json=body,
                headers={"origin": "http://testserver"}).status_code, path)

    def test_save_uses_session_actor_and_http_never_contains_key(self):
        repo = Mock()
        row = dict(configuration(), id=self.model)
        repo.save.return_value = row
        repo.get.return_value = row
        repo.list.return_value = ([row], {})
        self.app.state.resource_settings.repository = repo
        headers = self.login()
        with patch.dict("os.environ", {"ARK_AGENT_PLAN_API_KEY": "PRIVATE-TEST-KEY-DO-NOT-EXPOSE"}):
            response = self.client.post("/api/v1/resource-settings/configurations", json={"payload": configuration()}, headers=headers)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual("real-human", repo.save.call_args.args[1])
            check = self.client.post("/api/v1/resource-settings/configurations/" + self.model + "/check", json={}, headers=headers)
            self.assertTrue(check.json()["credential_loaded"])
            self.assertFalse(check.json()["generation_verified"])
            listing = self.client.get("/api/v1/resource-settings")
            for output in (response, check, listing):
                self.assertNotIn("PRIVATE-TEST-KEY-DO-NOT-EXPOSE", output.text)
        denied = self.client.post("/api/v1/resource-settings/configurations", json={"payload": configuration(), "actor": "forged"}, headers=headers)
        self.assertEqual(422, denied.status_code)
