"""AI character studio views, workflow helpers and sidebar placement over the real modules."""
from pathlib import Path
import shutil
import subprocess
import unittest
import support.paths  # noqa: F401


class CharacterStudioFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_character_studio(self):
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("character_studio.test.mjs")),
             str(Path(__file__).with_name("character_studio_parity.test.mjs")),
             str(Path(__file__).with_name("character_studio_errors.test.mjs"))],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
