"""Grok subscription credential checks: local login file only, no network, no key echo."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vsc.adapters.providers.xai_grok.credentials as C

FUTURE = "2999-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


def login_file(directory, key="grok-login-secret-value", expires=FUTURE):
    path = Path(directory) / "auth.json"
    path.write_text(json.dumps({"https://auth.x.ai::u1": {"key": key, "expires_at": expires}}), "utf-8")
    return path


class GrokCredentialsTest(unittest.TestCase):
    def test_missing_file_points_to_grok_login_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(C, "LOGIN_FILE", Path(temp) / "auth.json"):
                problem = C.key_problem()
                self.assertIn("grok", problem)
                self.assertIn("auth.json", problem)
                self.assertFalse(C.login_present())
                with self.assertRaises(RuntimeError):
                    C.read_key()

    def test_nested_account_key_is_read_and_not_echoed(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(C, "LOGIN_FILE", login_file(temp)) as path:
                self.assertIsNone(C.key_problem())
                self.assertTrue(C.login_present())
                self.assertEqual(C.read_key(), "grok-login-secret-value")
                self.assertNotIn("grok-login-secret-value", json.dumps(str(path)))

    def test_expired_or_unreadable_login_requires_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(C, "LOGIN_FILE", login_file(temp, expires=PAST)):
                self.assertIn("过期", C.key_problem())
                self.assertFalse(C.login_present())
            with mock.patch.object(C, "LOGIN_FILE", login_file(temp, key="  ")) as path:
                path.write_text("not-json", "utf-8")
                self.assertFalse(C.login_present())
                self.assertIn("grok", C.key_problem())

    def test_stable_identity_is_required_and_independent_of_token(self):
        with tempfile.TemporaryDirectory() as temp:
            path = login_file(temp)
            with mock.patch.object(C, "LOGIN_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "稳定账号"):
                    C.account_sha256()
                path.write_text(json.dumps({"synthetic": {"key": "token-1", "user_id": "stable-user"}}))
                first = C.account_sha256()
                path.write_text(json.dumps({"synthetic": {"key": "token-2", "user_id": "stable-user"}}))
                self.assertEqual(C.account_sha256(), first)
                path.write_text(json.dumps({"synthetic": {"key": "token-2", "user_id": "other-user"}}))
                self.assertNotEqual(C.account_sha256(), first)

    def test_permission_denied_only_for_auth_statuses_and_never_auto_swaps(self):
        for status in (401, 403):
            message = C.permission_denied(status, "xAI Grok Imagine 接口")
            self.assertIn("订阅", message)
            self.assertIn("不会自动", message)
        self.assertIsNone(C.permission_denied(500, "xAI Grok Imagine 接口"))


if __name__ == "__main__":
    unittest.main()
