from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
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

    def test_doctor_reports_invalid_codex_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_home = root / "codex-home"
            jam_home = root / "jam-home"
            with (
                patch.dict(
                    os.environ,
                    {"CODEX_HOME": str(codex_home), "JAM_HOME": str(jam_home)},
                    clear=False,
                ),
                patch("jam.service_doctor.shutil.which", return_value="codex"),
                patch("jam.service_doctor.subprocess.run") as run,
            ):
                run.side_effect = [
                    CompletedProcess(
                        ["codex", "features", "list"],
                        1,
                        stdout="",
                        stderr="invalid type in `agents`",
                    ),
                    CompletedProcess(
                        ["codex", "app-server", "--help"],
                        0,
                        stdout="app-server help",
                        stderr="",
                    ),
                ]
                result = doctor()

        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(result["ok"])
        self.assertFalse(checks["codex_config"]["ok"])
        self.assertIn("invalid type", checks["codex_config"]["detail"])


if __name__ == "__main__":
    unittest.main()
