"""Source intake and typed resource navigation through actual browser modules."""
import os
import shutil
import subprocess
import unittest

from support.paths import ROOT


class SourceResourceFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node for frontend module behavior")
    def test_source_and_resource_user_paths(self):
        result = subprocess.run(["node", "--test", "--test-timeout=5000",
            str(ROOT / "tests/project/unit/source_resource.test.cjs")],
            capture_output=True, text=True, cwd=str(ROOT),
            env={"VSC_TEST_ROOT": str(ROOT), "PATH": os.environ.get("PATH", "")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
