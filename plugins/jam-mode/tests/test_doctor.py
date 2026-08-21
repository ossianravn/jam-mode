from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.service import doctor


class DoctorTests(unittest.TestCase):
    def test_doctor_does_not_create_state_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex-home"
            jam_home = root / "jam-home"
            with patch.dict(
                os.environ,
                {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                clear=False,
            ):
                self.assertFalse(codex_home.exists())
                self.assertFalse(jam_home.exists())
                result = doctor()
                self.assertFalse(codex_home.exists())
                self.assertFalse(jam_home.exists())
                names = {item["name"] for item in result["checks"]}
                self.assertIn("jam_home", names)
                self.assertIn("plugin_root", names)


if __name__ == "__main__":
    unittest.main()
