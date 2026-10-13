"""Volcano credential policy: one Agent Plan key; retired names explain the change; values never print."""
import contextlib
import io
import os
import unittest
from unittest import mock

from _paths import ROOT  # noqa: F401 - add scripts to import path
import vsc_credentials as credentials


class CredentialPolicy(unittest.TestCase):
    def test_retired_names_and_stale_sessions_explain_the_change(self):
        with mock.patch.dict(os.environ, {"HUO_SHAN_API_KEY": "retired-value-123"}, clear=True):
            self.assertIn("已更换", credentials.key_problem("DOUBAO_SPEECH_API_KEY"))
            self.assertIn("已停用的 HUO_SHAN_API_KEY", credentials.key_problem())
            with self.assertRaisesRegex(ValueError, "已更换") as error:
                credentials.read_key(error=ValueError)
            self.assertNotIn("retired-value-123", str(error.exception))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("缺少 " + credentials.KEY_ENV, credentials.key_problem())
            self.assertIn("环境变量名", credentials.key_problem("not a name"))
        self.assertIn("Agent Plan", credentials.text_model_problem())

    def test_new_key_is_read_and_a_stale_session_is_told_once(self):
        environment = {credentials.KEY_ENV: " plan-value-456 ", "ARK_API_KEY": "retired-value-789"}
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(credentials, "_noticed", False), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(credentials.read_key(), "plan-value-456")
            credentials.read_key()
        self.assertEqual(err.getvalue().count("已更换"), 1)
        self.assertIn("ARK_API_KEY", err.getvalue())
        self.assertNotIn("value", err.getvalue())


if __name__ == "__main__":
    unittest.main()
