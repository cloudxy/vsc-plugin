"""Volcano credential policy: one Agent Plan key; a missing key asks for that key; values never print."""
import contextlib
import io
import os
import unittest
from unittest import mock

from support.paths import ROOT  # noqa: F401 - add scripts to import path
import vsc_credentials as credentials


class CredentialPolicy(unittest.TestCase):
    def test_missing_key_asks_for_the_agent_plan_key(self):
        with mock.patch.dict(os.environ, {"HUO_SHAN_API_KEY": "other-value-123"}, clear=True):
            problem = credentials.key_problem()
            self.assertIn("火山方舟 Agent 版本", problem)
            self.assertIn(credentials.KEY_ENV, problem)
            self.assertIn("source ~/.zshenv", problem)
            self.assertNotIn("HUO_SHAN_API_KEY", problem)
            with self.assertRaisesRegex(ValueError, "Agent 版本") as error:
                credentials.read_key(error=ValueError)
            self.assertNotIn("other-value-123", str(error.exception))
            self.assertIn("TEAM_KEY", credentials.key_problem("TEAM_KEY"))
            self.assertIn("环境变量名", credentials.key_problem("not a name"))
        self.assertIn("Agent Plan", credentials.text_model_problem())

    def test_key_is_read_silently(self):
        environment = {credentials.KEY_ENV: " plan-value-456 ", "HUO_SHAN_API_KEY": "other-value-789"}
        with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(credentials.read_key(), "plan-value-456")
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
