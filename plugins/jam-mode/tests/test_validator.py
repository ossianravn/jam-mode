from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate_plugin.py"


class ValidatorTests(unittest.TestCase):
    def test_local_plugin_preflight(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(PLUGIN_ROOT)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("validation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
