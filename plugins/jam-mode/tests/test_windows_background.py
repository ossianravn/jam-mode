from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows console behavior")
class WindowsBackgroundTests(unittest.TestCase):
    def test_codex_transport_and_probes_have_no_console(self):
        # A detached controller has no console to inherit. Its subprocesses must
        # explicitly suppress allocation, even when all stdio is redirected.
        probe = textwrap.dedent('''\
            import ctypes, json, sys
            from pathlib import Path
            from unittest.mock import patch
            from jam.appserver_transport import AppServerTransport
            from jam.service_doctor import doctor
            console = "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"
            if sys.argv[1] == "transport":
                child = ("import ctypes,json,sys; request=json.loads(sys.stdin.readline()); "
                         "print(json.dumps({'id':request['id'],'result':"
                         "{'console':ctypes.windll.kernel32.GetConsoleWindow()}}),flush=True); "
                         "sys.stdin.read()")
                events = []
                with patch("jam.appserver_transport._codex_command", return_value=[sys.executable, "-c", child]):
                    with AppServerTransport(stderr_path=Path("stderr.log"), event_callback=events.append):
                        result = [events[0]["result"]["console"]]
            else:
                with patch("jam.service_doctor.shutil.which", return_value="codex"), patch(
                    "jam.service_doctor._codex_command", return_value=[sys.executable, "-c", console]
                ):
                    result = [int(c["detail"]) for c in doctor()["checks"]
                              if c["name"] in {"codex_config", "app_server"}]
            print(json.dumps(result))
        ''')
        for mode, expected in (("transport", [0]), ("doctor", [0, 0])):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                           CODEX_HOME=directory, JAM_HOME=directory, PYTHONDONTWRITEBYTECODE="1")
                result = subprocess.run(
                    [sys.executable, "-c", probe, mode], cwd=directory, env=env,
                    capture_output=True, text=True, timeout=20,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)
