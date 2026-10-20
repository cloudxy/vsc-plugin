"""Host isolation is verified against child processes, without calling a model."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import support.paths  # noqa: F401
from vsc.assets.resource_service import ResourceError
from vsc.assets.script_ai import GrokBuildSuggestions, _run_bounded, host_environment


class ScriptHostIsolationTests(unittest.TestCase):
    def test_host_receives_only_allowlisted_environment_and_subscription_home(self):
        captured = {}
        def run(command, **kwargs):
            captured.update(command=command, **kwargs)
            self.assertNotEqual(Path(kwargs["cwd"]), Path.cwd())
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            return SimpleNamespace(returncode=0, stdout='{"suggestions":[]}')
        secrets = {"VSC_DATABASE_URL": "synthetic-db", "VSC_HUMAN_TOKEN": "synthetic-human",
            "ARK_AGENT_PLAN_API_KEY": "synthetic-ark", "XAI_API_KEY": "synthetic-paid",
            "GROK_API_KEY": "synthetic-paid", "BASH_ENV": "/synthetic/rc", "NODE_OPTIONS": "--inspect",
            "PYTHONPATH": "/synthetic/modules", "DYLD_INSERT_LIBRARIES": "/synthetic/lib"}
        with patch.dict(os.environ, secrets), patch("vsc.assets.script_ai.shutil.which", return_value="/test/grok"):
            self.assertEqual(GrokBuildSuggestions(runner=run).generate({}, "bounded"), [])
        self.assertFalse(set(secrets) & set(captured["env"]))
        self.assertEqual(captured["env"]["HOME"], os.environ["HOME"])
        self.assertNotIn("shell", captured)
        self.assertEqual(captured["command"][captured["command"].index("--tools") + 1], "")
        self.assertIn("--no-subagents", captured["command"])
        self.assertIn("--disable-web-search", captured["command"])
        self.assertNotIn("-l", captured["command"])

    def test_real_child_cannot_read_application_or_other_provider_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {"VSC_DATABASE_URL": "synthetic-secret", "XAI_API_KEY": "synthetic-secret"}):
            result = _run_bounded([sys.executable, "-c",
                "import os; print(os.getenv('VSC_DATABASE_URL')); print(os.getenv('XAI_API_KEY'))"],
                cwd=directory, env=host_environment(), timeout=5)
        self.assertEqual(result.stdout, "None\nNone\n")

    def test_real_child_output_and_lifetime_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ResourceError) as caught:
                _run_bounded([sys.executable, "-c", "import os; os.write(1,b'x'*100000)"],
                    cwd=directory, env=host_environment(), timeout=5, maximum_bytes=1024)
            self.assertEqual(caught.exception.code, "suggestion_output_limit")
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_bounded([sys.executable, "-c", "import time; time.sleep(10)"],
                    cwd=directory, env=host_environment(), timeout=.1)


if __name__ == "__main__":
    unittest.main()
