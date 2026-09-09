from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jam.harnesses.process import run_jsonl, signed_in_environment
from jam.harnesses.types import HarnessError


class HarnessProcessTests(unittest.TestCase):
    def test_native_process_receives_prompt_without_shell_and_retains_events(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            events = []
            prompt = "literal `whoami` $(whoami) & \n" * 10000
            run_jsonl([sys.executable, "-c", "import sys,json; print(json.dumps({'prompt':sys.stdin.read()}))"],
                      prompt=prompt, cwd=folder, environment=dict(os.environ),
                      events_path=root / "events", stderr_path=root / "errors",
                      timeout_seconds=10, on_event=events.append)
            self.assertEqual(events, [{"prompt": prompt}])
            self.assertEqual(json.loads((root / "events").read_text()), events[0])

    def test_deadline_kills_descendant_after_parent_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Child retains the output pipe after its parent has exited.
            child = "import time,pathlib; time.sleep(3); pathlib.Path('escaped').touch()"
            code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}]); print('{{}}',flush=True)"
            with self.assertRaisesRegex(HarnessError, "deadline"):
                run_jsonl([sys.executable, "-c", code], prompt="", cwd=folder,
                          environment=dict(os.environ), events_path=root / "events",
                          stderr_path=root / "errors", timeout_seconds=1, on_event=lambda _: None)
            time.sleep(3)
            self.assertFalse((root / "escaped").exists())

    def test_invalid_stream_and_nonzero_exit_are_errors(self):
        for code, message in [("print('bad json')", "invalid JSON"),
                              ("raise SystemExit(7)", "status 7")]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaisesRegex(HarnessError, message):
                    run_jsonl([sys.executable, "-c", code], prompt="", cwd=folder,
                              environment=dict(os.environ), events_path=root / "events",
                              stderr_path=root / "errors", timeout_seconds=5, on_event=lambda _: None)

    def test_signed_in_environment_excludes_direct_provider_overrides(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test", "OPENAI_BASE_URL": "test",
                                     "CLAUDE_CODE_USE_BEDROCK": "1", "PATH": "native"}, clear=True):
            self.assertEqual(signed_in_environment("claude-code"),
                             {"PATH": "native", "JAM_CHILD_SESSION": "1", "JAM_HARNESS": "claude-code"})
