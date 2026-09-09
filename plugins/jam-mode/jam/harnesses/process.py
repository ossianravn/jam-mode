from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .types import HarnessError
from .process_tree import launch, stop as _stop_process


def find_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise HarnessError(f"{name} is not installed on this host's PATH.")
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        raise HarnessError(f"{name} requires a native executable on Windows; shell wrappers are unsupported.")
    return executable


def signed_in_environment(harness: str) -> dict[str, str]:
    """Keep native sign-in, excluding direct-provider credentials and overrides."""
    prefixes = ("ANTHROPIC_", "OPENAI_", "AZURE_OPENAI_", "AWS_", "BEDROCK_",
                "GOOGLE_", "GEMINI_", "VERTEX_", "COPILOT_PROVIDER_", "COPILOT_CUSTOM_")
    excluded = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_SUBAGENT_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "COPILOT_MODEL", "COPILOT_ALLOW_ALL",
                "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "OPENCODE_PERMISSION"}
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in excluded and not key.upper().startswith(prefixes)}
    environment["JAM_CHILD_SESSION"] = "1"
    environment["JAM_HARNESS"] = harness
    return environment


def run_jsonl(command: list[str], *, prompt: str, cwd: str, environment: dict[str, str],
              events_path: Path, stderr_path: Path, timeout_seconds: float,
              on_event: Callable[[dict], None]) -> None:
    """Run a bounded native process, retaining raw output without shell interpolation."""
    if timeout_seconds <= 0:
        raise HarnessError("Episode deadline has already expired.")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    messages: queue.Queue = queue.Queue(maxsize=256)
    done = threading.Event()
    with tempfile.TemporaryFile() as input_file, stderr_path.open("wb") as errors, events_path.open("wb") as events:
        input_file.write(prompt.encode("utf-8"))
        input_file.seek(0)
        try:
            process = launch(command, cwd=cwd, env=environment, stdin=input_file,
                             stdout=subprocess.PIPE, stderr=errors)
        except OSError as exc:
            raise HarnessError(f"Unable to start {Path(command[0]).name}: {exc}") from exc

        def read_lines() -> None:
            try:
                while not done.is_set():
                    line = process.stdout.readline(8 * 1024 * 1024 + 1)
                    while not done.is_set():
                        try:
                            messages.put(line, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                    if not line:
                        break
            except OSError:
                # Closing the owned process pipe during cancellation ends the reader.
                while not done.is_set():
                    try:
                        messages.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            finally:
                process.stdout.close()

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HarnessError("Harness exceeded the episode deadline.")
                try:
                    line = messages.get(timeout=remaining)
                except queue.Empty as exc:
                    raise HarnessError("Harness exceeded the episode deadline.") from exc
                if line is None:
                    raise HarnessError("Harness output could not be read.")
                if not line:
                    break
                events.write(line)
                events.flush()
                if len(line) > 8 * 1024 * 1024:
                    raise HarnessError("Harness emitted an oversized event.")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise HarnessError(f"Harness emitted invalid JSON; see {events_path}.") from exc
                if not isinstance(event, dict):
                    raise HarnessError("Harness events must be JSON objects.")
                on_event(event)
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if code:
                raise HarnessError(f"Harness exited with status {code}; see {stderr_path}.")
        except subprocess.TimeoutExpired as exc:
            raise HarnessError("Harness exceeded the episode deadline.") from exc
        finally:
            done.set()
            _stop_process(process)
            reader.join(timeout=1)
