"""Script workspace frontend behavior via the shared DOM fixture (F01/F02/F03)."""
import shutil
import subprocess
import unittest

from support.paths import ROOT


class ScriptWorkspaceFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node for frontend behavior verification")
    def test_save_session_queue_and_field_preservation(self):
        result = subprocess.run(["node", "--test", "--test-timeout=5000",
                                 str(ROOT / "tests/project/unit/script-workspace.test.cjs")],
                                capture_output=True, text=True, cwd=str(ROOT),
                                env={"VSC_TEST_ROOT": str(ROOT), "PATH": __import__("os").environ.get("PATH", "")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
